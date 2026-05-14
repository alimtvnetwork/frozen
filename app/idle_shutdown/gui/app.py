"""Main Tk window: sidebar + paged content, like a Settings app."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from idle_shutdown.config import SETTING_DEFS, get_setting_def
from idle_shutdown.db.connection import connect, init_db
from idle_shutdown.db.repos import (
    SettingsRepo,
    ShutdownCounterRepo,
    ShutdownLogRepo,
    SnapshotReadRepo,
)
from idle_shutdown.errors import IdleShutdownError

logger = logging.getLogger(__name__)

# Theme colors — semantic, used across all panels
COLORS = {
    "bg":          "#1e1e1e",
    "sidebar":     "#252526",
    "sidebar_hi":  "#37373d",
    "panel":       "#1e1e1e",
    "fg":          "#e8e8e8",
    "fg_muted":    "#9d9d9d",
    "accent":      "#0a84ff",
    "accent_hi":   "#3b9eff",
    "ok":          "#30d158",
    "warn":        "#ff9f0a",
    "err":         "#ff453a",
    "border":      "#3a3a3a",
    "input_bg":    "#2d2d30",
}

SECTIONS = [
    ("dashboard", "  ⏻   Dashboard"),
    ("settings",  "  ⚙   Settings"),
    ("snapshots", "  ⌘   Snapshots"),
    ("about",     "  ⓘ   About"),
]


# ---------- cross-platform colored "button" --------------------------------
#
# tk.Button on macOS ignores ``bg`` / ``fg`` (Aqua paints a native white
# button), which leaves our white text unreadable. A tk.Label with click
# bindings honors colors on every platform, so we use it for every colored
# action button in the app.


def _make_button(parent, *, text: str, bg: str, fg: str, hover_bg: str,
                 command, font=("Helvetica", 11, "bold"),
                 padx: int = 16, pady: int = 10):
    import tkinter as tk

    lbl = tk.Label(
        parent, text=text, bg=bg, fg=fg, font=font,
        padx=padx, pady=pady, cursor="hand2", anchor="center",
    )
    lbl._bg = bg            # type: ignore[attr-defined]
    lbl._hover_bg = hover_bg  # type: ignore[attr-defined]

    def _enter(_e):
        lbl.configure(bg=lbl._hover_bg)  # type: ignore[attr-defined]

    def _leave(_e):
        lbl.configure(bg=lbl._bg)  # type: ignore[attr-defined]

    def _click(_e):
        if command:
            command()

    lbl.bind("<Enter>", _enter)
    lbl.bind("<Leave>", _leave)
    lbl.bind("<Button-1>", _click)
    return lbl


def _set_button_colors(btn, *, text: str, bg: str, hover_bg: str,
                       fg: str = "#ffffff") -> None:
    btn.configure(text=text, bg=bg, fg=fg)
    btn._bg = bg          # type: ignore[attr-defined]
    btn._hover_bg = hover_bg  # type: ignore[attr-defined]


# ---------- helpers ---------------------------------------------------------


def _get_setting(key: str):
    with connect() as conn:
        return SettingsRepo(conn).get(key)


def _set_setting(key: str, value) -> None:
    with connect() as conn:
        SettingsRepo(conn).set(key, value)


def _all_settings() -> dict[str, str]:
    with connect() as conn:
        return {r.key: r.value for r in SettingsRepo(conn).all()}


# ---------- main app --------------------------------------------------------


def launch_gui() -> None:  # pragma: no cover - GUI entrypoint
    import tkinter as tk
    from tkinter import ttk

    # Make sure DB exists before the first query
    try:
        init_db()
    except IdleShutdownError as e:
        logger.error("init-db failed: %s", e)

    root = tk.Tk()
    root.title("Frozen — Idle Shutdown & Restore")
    root.geometry("960x600")
    root.minsize(820, 520)
    root.configure(bg=COLORS["bg"])

    _apply_ttk_theme(ttk)

    # Crash-recovery prompt — runs once on startup, before the main UI.
    _maybe_show_crash_recovery(root, tk)

    # First-run wizard
    if str(_get_setting("FirstRunCompleted")).lower() != "true":
        _run_first_run_wizard(root, tk, ttk)

    app = _MainWindow(root, tk, ttk)
    app.show("dashboard")
    # Do NOT auto-start the monitor — the countdown should only begin once
    # the user explicitly presses "Start monitor" on the sidebar.
    app.start_ui_heartbeat()
    root.mainloop()


def _maybe_show_crash_recovery(root, tk) -> None:  # pragma: no cover - GUI
    """If the previous run did not exit cleanly, offer to restore."""
    from tkinter import messagebox
    from idle_shutdown.heartbeat import detect_crash_recovery_candidate
    from idle_shutdown.db.repos import SnapshotReadRepo

    is_crash, snapshot_id, last_hb = detect_crash_recovery_candidate()
    if not is_crash or snapshot_id is None:
        return
    # Build a friendly summary.
    try:
        with connect() as conn:
            detail = SnapshotReadRepo(conn).get_detail(snapshot_id)
    except Exception:  # noqa: BLE001
        detail = None
    apps_n = len(detail.apps) if detail else 0
    tabs_n = len(detail.tabs) if detail else 0
    when = last_hb or (detail.created_at if detail else "earlier")
    msg = (
        "Your last session ended unexpectedly "
        f"(last heartbeat: {when}).\n\n"
        f"Snapshot #{snapshot_id} contains:\n"
        f"  • {apps_n} application(s)\n"
        f"  • {tabs_n} browser tab(s)\n\n"
        "Restore it now?"
    )
    answer = messagebox.askyesno("Frozen — Recover last session", msg, parent=root)
    if answer:
        try:
            from idle_shutdown.restore import restore
            result = restore(snapshot_id)
            messagebox.showinfo(
                "Frozen — Restore complete",
                f"Restored snapshot #{result.snapshot_id}: "
                f"launched={result.apps_launched}, skipped={result.apps_skipped}.",
                parent=root,
            )
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(
                "Frozen — Restore failed", str(e), parent=root,
            )
    else:
        # User declined: mark this snapshot as "handled" so we don't ask again.
        try:
            with connect() as conn:
                SettingsRepo(conn).set("LastRestoredSnapshotId", snapshot_id)
        except Exception:  # noqa: BLE001
            logger.exception("recovery decline write failed")


def _apply_ttk_theme(ttk) -> None:
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:  # noqa: BLE001
        pass
    style.configure(".", background=COLORS["bg"], foreground=COLORS["fg"],
                    fieldbackground=COLORS["input_bg"], borderwidth=0)
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("Sidebar.TFrame", background=COLORS["sidebar"])
    style.configure("Panel.TFrame", background=COLORS["panel"])
    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["fg"])
    style.configure("Title.TLabel", font=("Helvetica", 20, "bold"),
                    background=COLORS["panel"], foreground=COLORS["fg"])
    style.configure("H2.TLabel", font=("Helvetica", 13, "bold"),
                    background=COLORS["panel"], foreground=COLORS["fg"])
    style.configure("Muted.TLabel", background=COLORS["panel"],
                    foreground=COLORS["fg_muted"])
    style.configure("Big.TLabel", font=("Helvetica", 28, "bold"),
                    background=COLORS["panel"], foreground=COLORS["accent"])
    style.configure("OK.TLabel",   background=COLORS["panel"], foreground=COLORS["ok"])
    style.configure("Warn.TLabel", background=COLORS["panel"], foreground=COLORS["warn"])
    style.configure("Err.TLabel",  background=COLORS["panel"], foreground=COLORS["err"])

    style.configure("TButton", padding=(14, 8), background=COLORS["sidebar_hi"],
                    foreground=COLORS["fg"], borderwidth=0, focuscolor=COLORS["accent"])
    style.map("TButton",
              background=[("active", COLORS["accent"]), ("pressed", COLORS["accent_hi"])])
    style.configure("Accent.TButton", padding=(14, 8),
                    background=COLORS["accent"], foreground="#ffffff",
                    borderwidth=0)
    style.map("Accent.TButton",
              background=[("active", COLORS["accent_hi"])])
    style.configure("Danger.TButton", padding=(14, 8),
                    background=COLORS["err"], foreground="#ffffff", borderwidth=0)

    style.configure("TEntry", fieldbackground=COLORS["input_bg"],
                    foreground=COLORS["fg"], insertcolor=COLORS["fg"],
                    bordercolor=COLORS["border"], lightcolor=COLORS["border"],
                    darkcolor=COLORS["border"])
    style.configure("TCheckbutton", background=COLORS["panel"],
                    foreground=COLORS["fg"], focuscolor=COLORS["accent"])
    style.map("TCheckbutton", background=[("active", COLORS["panel"])])
    style.configure("TCombobox", fieldbackground=COLORS["input_bg"],
                    background=COLORS["input_bg"], foreground=COLORS["fg"],
                    arrowcolor=COLORS["fg"])
    style.map("TCombobox",
              fieldbackground=[("readonly", COLORS["input_bg"])],
              foreground=[("readonly", COLORS["fg"])],
              background=[("readonly", COLORS["input_bg"])],
              selectbackground=[("readonly", COLORS["input_bg"])],
              selectforeground=[("readonly", COLORS["fg"])])
    style.configure("TSpinbox", fieldbackground=COLORS["input_bg"],
                    background=COLORS["input_bg"], foreground=COLORS["fg"],
                    insertcolor=COLORS["fg"], arrowcolor=COLORS["fg"],
                    bordercolor=COLORS["border"], lightcolor=COLORS["border"],
                    darkcolor=COLORS["border"])
    style.map("TSpinbox",
              fieldbackground=[("readonly", COLORS["input_bg"]),
                               ("!disabled", COLORS["input_bg"])],
              foreground=[("!disabled", COLORS["fg"])])
    # Card-styled labels for the settings panel
    style.configure("Card.TFrame", background=COLORS["sidebar"])
    style.configure("CardTitle.TLabel", background=COLORS["sidebar"],
                    foreground=COLORS["fg"], font=("Helvetica", 13, "bold"))
    style.configure("CardMuted.TLabel", background=COLORS["sidebar"],
                    foreground=COLORS["fg_muted"], font=("Helvetica", 11))
    style.configure("Card.TCheckbutton", background=COLORS["sidebar"],
                    foreground=COLORS["fg"], focuscolor=COLORS["accent"])
    style.map("Card.TCheckbutton",
              background=[("active", COLORS["sidebar"])],
              foreground=[("active", COLORS["fg"])])
    style.configure("Treeview", background=COLORS["input_bg"],
                    fieldbackground=COLORS["input_bg"],
                    foreground=COLORS["fg"], borderwidth=0, rowheight=26)
    style.configure("Treeview.Heading", background=COLORS["sidebar_hi"],
                    foreground=COLORS["fg"], borderwidth=0)
    style.map("Treeview", background=[("selected", COLORS["accent"])])


# ---------- main window -----------------------------------------------------


class _MainWindow:  # pragma: no cover - GUI
    def __init__(self, root, tk, ttk) -> None:
        self.root = root
        self.tk = tk
        self.ttk = ttk
        # Monitor state — driven from the Tk main loop via root.after().
        self._monitor_running: bool = False
        self._tick_job: Optional[str] = None
        self._heartbeat_job: Optional[str] = None
        self._idle_source = None  # built lazily on the main thread
        self._service = None
        self._monitor = None
        self._activity_guard = None
        self._popup_win = None  # active in-window countdown popup, if any
        self._popup_state = None

        # Live status vars — Dashboard binds to these so the countdown
        # updates every second without rebuilding the panel.
        self.idle_var = tk.StringVar(value="—")
        self.remaining_var = tk.StringVar(value="—")
        self.monitor_state_var = tk.StringVar(value="Stopped")
        self.busy_reason_var = tk.StringVar(value="—")

        # Layout: sidebar (left) + content (right)
        self.sidebar = ttk.Frame(root, style="Sidebar.TFrame", width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = tk.Label(self.sidebar, text="❄  Frozen",
                         bg=COLORS["sidebar"], fg=COLORS["fg"],
                         font=("Helvetica", 16, "bold"), anchor="w", padx=20, pady=22)
        brand.pack(fill="x")

        self._nav_buttons: dict[str, tk.Label] = {}
        for key, label in SECTIONS:
            btn = tk.Label(self.sidebar, text=label, bg=COLORS["sidebar"],
                           fg=COLORS["fg"], anchor="w", padx=12, pady=10,
                           font=("Helvetica", 11))
            btn.pack(fill="x", padx=8, pady=2)
            btn.bind("<Button-1>", lambda _e, k=key: self.show(k))
            btn.bind("<Enter>", lambda _e, b=btn: self._hover(b, True))
            btn.bind("<Leave>", lambda _e, b=btn: self._hover(b, False))
            self._nav_buttons[key] = btn

        # Footer: monitor toggle (colored Label; tk.Button ignores bg on macOS)
        self.monitor_btn = _make_button(
            self.sidebar, text="▶  Start monitor",
            bg=COLORS["accent"], hover_bg=COLORS["accent_hi"], fg="#ffffff",
            command=self._toggle_monitor,
        )
        self.monitor_btn.pack(side="bottom", fill="x", padx=12, pady=14)

        # Content area
        self.content = ttk.Frame(root, style="Panel.TFrame")
        self.content.pack(side="right", fill="both", expand=True)

        self._current_key: str | None = None

    def _hover(self, btn, on: bool) -> None:
        if self._current_key and self._nav_buttons.get(self._current_key) is btn:
            return
        btn.configure(bg=COLORS["sidebar_hi"] if on else COLORS["sidebar"])

    def show(self, key: str) -> None:
        for w in self.content.winfo_children():
            w.destroy()
        for k, b in self._nav_buttons.items():
            b.configure(bg=COLORS["sidebar_hi"] if k == key else COLORS["sidebar"])
        self._current_key = key

        if key == "dashboard":
            DashboardPanel(self.content, self.tk, self.ttk, self).build()
        elif key == "settings":
            SettingsPanel(self.content, self.tk, self.ttk).build()
        elif key == "snapshots":
            SnapshotsPanel(self.content, self.tk, self.ttk).build()
        elif key == "about":
            AboutPanel(self.content, self.tk, self.ttk).build()

    # ---------- monitor lifecycle ----------

    def monitor_running(self) -> bool:
        return self._monitor_running

    def start_monitor_if_enabled(self) -> None:
        try:
            enabled = _get_setting("ServiceState") == "Enabled"
        except Exception:  # noqa: BLE001
            enabled = False
        if enabled and not self.monitor_running():
            self._start_monitor()
            self._refresh_monitor_btn()

    def _toggle_monitor(self) -> None:
        if self.monitor_running():
            self._stop_monitor()
        else:
            self._start_monitor()
        self._refresh_monitor_btn()
        if self._current_key == "dashboard":
            self.show("dashboard")

    def _refresh_monitor_btn(self) -> None:
        if self.monitor_running():
            _set_button_colors(self.monitor_btn,
                               text="■  Stop monitor",
                               bg=COLORS["err"], hover_bg="#ff6b62")
            self.monitor_state_var.set("Running")
        else:
            _set_button_colors(self.monitor_btn,
                               text="▶  Start monitor",
                               bg=COLORS["accent"], hover_bg=COLORS["accent_hi"])
            self.monitor_state_var.set("Stopped")

    def _ensure_idle_source(self):
        if self._idle_source is None:
            from idle_shutdown.monitor import get_default_idle_source
            self._idle_source = get_default_idle_source()
        return self._idle_source

    def _read_idle_ms(self) -> int:
        try:
            return int(self._ensure_idle_source().get_idle_ms())
        except Exception:  # noqa: BLE001
            return 0

    def _threshold_ms(self) -> int:
        try:
            return max(1, int(_get_setting("IdleThresholdMinutes"))) * 60_000
        except Exception:  # noqa: BLE001
            return 60_000

    def _busy_label(self, reason: str | None) -> str:
        labels = {
            "audio_playing": "Media playing",
            "mic_active": "Call or microphone active",
            "camera_active": "Camera active",
            "fullscreen": "Fullscreen app active",
        }
        return labels.get(reason or "", "Busy")

    def _read_busy_state(self) -> tuple[bool, str | None]:
        if self._activity_guard is None:
            return False, None
        try:
            return self._activity_guard.is_busy()
        except Exception:  # noqa: BLE001
            return False, None

    @staticmethod
    def _fmt_ms(ms: int) -> str:
        s = max(0, ms // 1000)
        return f"{s // 60:02d}:{s % 60:02d}"

    def start_ui_heartbeat(self) -> None:
        """1 Hz UI tick — updates idle/remaining labels and (if the monitor
        is on) drives the IdleMonitor.tick() on the main thread."""
        self._heartbeat_tick()

    def _heartbeat_tick(self) -> None:
        # Only watch input / count down when the monitor is actually
        # running. Before "Start monitor" is pressed, the dashboard should
        # show neutral placeholders rather than a live ticking countdown.
        if self._monitor_running and self._monitor is not None:
            idle_ms = self._read_idle_ms()
            threshold = self._threshold_ms()
            try:
                self._monitor.tick()
            except Exception:  # noqa: BLE001
                logger.exception("monitor tick failed")
            busy = bool(getattr(self._monitor, "busy", False))
            busy_reason = getattr(self._monitor, "busy_reason", None)
            if busy:
                self._close_popup()
                self.idle_var.set("Paused")
                self.remaining_var.set("Paused")
                self.busy_reason_var.set(self._busy_label(busy_reason))
            else:
                effective_idle_ms = int(getattr(self._monitor, "last_effective_idle_ms", idle_ms))
                remaining = max(0, threshold - effective_idle_ms)
                self.idle_var.set(self._fmt_ms(effective_idle_ms))
                self.remaining_var.set(self._fmt_ms(remaining))
                self.busy_reason_var.set("—")
        else:
            self.idle_var.set("—")
            self.remaining_var.set("Not running")
            self.busy_reason_var.set("—")
        self._heartbeat_job = self.root.after(1000, self._heartbeat_tick)

    def _start_monitor(self) -> None:
        if self._monitor_running:
            return
        from idle_shutdown.monitor import IdleMonitor
        from idle_shutdown.service import IdleService, ServiceCallbacks
        from idle_shutdown.snapshot import take_snapshot
        from idle_shutdown.enums import SnapshotTriggerKind
        from idle_shutdown.activity_guard import ActivityGuard, GuardConfig
        from tkinter import messagebox

        def _take_snapshot_and_shutdown() -> None:
            try:
                res = take_snapshot(SnapshotTriggerKind.Auto, record_log=True)
            except Exception as e:  # noqa: BLE001
                logger.exception("snapshot failed")
                messagebox.showerror("Snapshot failed", str(e))
                return
            messagebox.showinfo(
                "Idle Shutdown — Dry Run",
                f"Would shut down now.\nSnapshot #{res.snapshot_id} saved\n"
                f"({res.app_count} apps, {res.chrome_tab_count} tabs).",
            )

        callbacks = ServiceCallbacks(
            show_popup=self._show_popup_inwindow,
            take_snapshot_and_shutdown=_take_snapshot_and_shutdown,
            get_idle_threshold_minutes=lambda: int(_get_setting("IdleThresholdMinutes")),
            get_popup_countdown_seconds=lambda: int(_get_setting("PopupCountdownSeconds")),
            get_service_enabled=lambda: _get_setting("ServiceState") == "Enabled",
            get_snooze_minutes=lambda: int(_get_setting("SnoozeMinutes")),
        )
        self._service = IdleService(callbacks)
        def _guard_cfg() -> GuardConfig:
            return GuardConfig(
                mic_enabled=str(_get_setting("GuardMicEnabled")).lower() == "true",
                audio_enabled=str(_get_setting("GuardAudioEnabled")).lower() == "true",
                fullscreen_enabled=str(_get_setting("GuardFullscreenEnabled")).lower() == "true",
                camera_enabled=str(_get_setting("GuardCameraEnabled")).lower() == "true",
            )
        self._activity_guard = ActivityGuard(_guard_cfg)
        self._monitor = IdleMonitor(
            source=self._ensure_idle_source(),
            threshold_ms_provider=self._service.threshold_ms,
            on_threshold=self._service.on_threshold_reached,
            on_activity=self._service.on_activity_during_prompt,
            is_busy=self._read_busy_state,
        )
        self._monitor_running = True
        logger.info("event=gui_monitor_started")

    def _stop_monitor(self) -> None:
        self._monitor_running = False
        self._monitor = None
        self._service = None
        self._activity_guard = None
        self._close_popup()
        logger.info("event=gui_monitor_stopped")

    # ---------- in-window popup (main-thread safe) ----------

    def _close_popup(self) -> None:
        state = self._popup_state
        if state is not None:
            state["done"] = True
            after = state.get("after")
            if after and self._popup_win is not None:
                try:
                    self._popup_win.after_cancel(after)
                except Exception:  # noqa: BLE001
                    pass
            self._popup_state = None
        if self._popup_win is not None:
            try:
                self._popup_win.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._popup_win = None

    def _show_popup_inwindow(self, countdown_seconds: int, on_result) -> None:
        """Toplevel popup attached to the existing Tk root. Safe on macOS
        because it runs on the main thread."""
        from idle_shutdown.enums import PopupResult
        tk = self.tk
        if self._popup_win is not None:
            return
        win = tk.Toplevel(self.root)
        self._popup_win = win
        win.title("Frozen — are you still there?")
        win.configure(bg=COLORS["panel"])
        win.attributes("-topmost", True)
        win.geometry("420x180")
        win.transient(self.root)
        try:
            win.lift()
            win.focus_force()
            self.root.bell()
        except Exception:  # noqa: BLE001
            pass

        state = {"remaining_ms": int(countdown_seconds) * 1000,
                 "done": False, "after": None}
        self._popup_state = state

        tk.Label(win, text="Are you still at your desk?",
                 bg=COLORS["panel"], fg=COLORS["fg"],
                 font=("Helvetica", 14, "bold")).pack(pady=(20, 6))
        cd = tk.Label(win, text="", bg=COLORS["panel"], fg=COLORS["fg_muted"],
                      font=("Helvetica", 11))
        cd.pack(pady=(0, 12))

        def finish(result) -> None:
            if state["done"]:
                return
            state["done"] = True
            self._popup_state = None
            if state["after"]:
                try:
                    win.after_cancel(state["after"])
                except Exception:  # noqa: BLE001
                    pass
            self._close_popup()
            try:
                on_result(result)
            except Exception:  # noqa: BLE001
                logger.exception("popup result handler failed")

        win.protocol("WM_DELETE_WINDOW", lambda: finish(PopupResult.No))

        btns = tk.Frame(win, bg=COLORS["panel"])
        btns.pack()
        # Use Label-based buttons so the colored bg is visible on macOS
        # (native tk.Button ignores bg/fg under Aqua and stays white).
        _make_button(btns, text="Yes, I'm here",
                     bg=COLORS["accent"], hover_bg=COLORS["accent_hi"],
                     fg="#ffffff",
                     command=lambda: finish(PopupResult.Yes),
                     padx=24, pady=10).pack(side="left", padx=8, pady=8)
        try:
            snooze_min = int(_get_setting("SnoozeMinutes"))
        except Exception:  # noqa: BLE001
            snooze_min = 30
        _make_button(btns, text=f"Snooze {snooze_min}m",
                     bg=COLORS["sidebar_hi"], hover_bg=COLORS["border"],
                     fg=COLORS["fg"],
                     command=lambda: finish(PopupResult.Snooze),
                     padx=18, pady=10).pack(side="left", padx=8, pady=8)
        _make_button(btns, text="No, shut down",
                     bg=COLORS["err"], hover_bg="#ff6b62",
                     fg="#ffffff",
                     command=lambda: finish(PopupResult.No),
                     padx=24, pady=10).pack(side="left", padx=8, pady=8)

        def tick() -> None:
            if state["done"]:
                return
            remaining = state["remaining_ms"]
            if remaining <= 0:
                finish(PopupResult.Timeout)
                return
            cd.config(text=f"Auto-shutdown in {remaining // 1000}s")
            state["remaining_ms"] = remaining - 250
            state["after"] = win.after(250, tick)

        tick()


# ---------- panels ----------------------------------------------------------


class _PanelBase:  # pragma: no cover - GUI
    def __init__(self, parent, tk, ttk) -> None:
        self.parent = parent
        self.tk = tk
        self.ttk = ttk

    def _scrollable(self):
        canvas = self.tk.Canvas(self.parent, bg=COLORS["panel"],
                                highlightthickness=0)
        scroll = self.ttk.Scrollbar(self.parent, orient="vertical",
                                    command=canvas.yview)
        inner = self.ttk.Frame(canvas, style="Panel.TFrame")
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return inner


class DashboardPanel(_PanelBase):  # pragma: no cover - GUI
    def __init__(self, parent, tk, ttk, win: _MainWindow) -> None:
        super().__init__(parent, tk, ttk)
        self.win = win

    def build(self) -> None:
        wrap = self._scrollable()
        ttk = self.ttk
        pad = {"padx": 32}

        ttk.Label(wrap, text="Dashboard", style="Title.TLabel").pack(
            anchor="w", pady=(28, 4), **pad)
        ttk.Label(wrap, text="Status of the idle watcher and your last snapshot.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 20), **pad)

        # Status cards
        cards = ttk.Frame(wrap, style="Panel.TFrame")
        cards.pack(fill="x", pady=(0, 16), **pad)

        running = self.win.monitor_running()
        self._card(cards, "Monitor",
                   "Running" if running else "Stopped",
                   "OK.TLabel" if running else "Warn.TLabel", col=0)

        # Live countdown — bound to win.remaining_var, updated every 1s.
        self._var_card(cards, "Time until prompt",
                       self.win.remaining_var, col=1)
        self._var_card(cards, "Guard status",
                       self.win.busy_reason_var, col=2)

        for c in range(3):
            cards.columnconfigure(c, weight=1, uniform="cards")

        # Second row: idle timer + counters
        cards2 = ttk.Frame(wrap, style="Panel.TFrame")
        cards2.pack(fill="x", pady=(0, 16), **pad)
        self._var_card(cards2, "Idle for",
                       self.win.idle_var, col=2)
        try:
            with connect() as conn:
                total = ShutdownCounterRepo(conn).total()
                last_id = SnapshotReadRepo(conn).latest_id()
        except Exception:  # noqa: BLE001
            total, last_id = 0, None
        self._card(cards2, "Total auto-shutdowns", str(total), "Big.TLabel", col=0)
        self._card(cards2, "Latest snapshot",
                   f"#{last_id}" if last_id else "—", "Big.TLabel", col=1)
        for c in range(3):
            cards2.columnconfigure(c, weight=1, uniform="cards2")

        # Settings summary
        ttk.Label(wrap, text="Current configuration",
                  style="H2.TLabel").pack(anchor="w", pady=(20, 8), **pad)
        s = _all_settings()
        summary = (
            f"• Prompts after  {s.get('IdleThresholdMinutes', '?')} minutes idle\n"
            f"• Popup countdown  {s.get('PopupCountdownSeconds', '?')} seconds\n"
            f"• Service  {s.get('ServiceState', '?')}\n"
            f"• Auto-restore on boot  {s.get('AutoRestoreOnBoot', '?')}\n"
            f"• Dry run (no real shutdown)  {s.get('DryRun', '?')}"
        )
        ttk.Label(wrap, text=summary, style="Muted.TLabel",
                  justify="left").pack(anchor="w", **pad)

        # Crash-recovery banner — shows when previous run didn't exit cleanly.
        try:
            from idle_shutdown.heartbeat import detect_crash_recovery_candidate
            is_crash, snap_id, last_hb = detect_crash_recovery_candidate()
        except Exception:  # noqa: BLE001
            is_crash, snap_id, last_hb = False, None, None
        if is_crash and snap_id is not None:
            ttk.Label(wrap, text="Recover last session",
                      style="H2.TLabel").pack(anchor="w", pady=(24, 8), **pad)
            banner = self.tk.Frame(wrap, bg=COLORS["sidebar"],
                                   highlightthickness=1,
                                   highlightbackground=COLORS["warn"])
            banner.pack(fill="x", **pad)
            self.tk.Label(banner,
                          text=f"⚠  Previous session ended unexpectedly "
                               f"(last heartbeat: {last_hb or 'unknown'}).",
                          bg=COLORS["sidebar"], fg=COLORS["warn"],
                          font=("Helvetica", 11, "bold"),
                          anchor="w", padx=14, pady=(12, 2)).pack(fill="x")
            self.tk.Label(banner,
                          text=f"Snapshot #{snap_id} is ready to restore.",
                          bg=COLORS["sidebar"], fg=COLORS["fg_muted"],
                          font=("Helvetica", 10),
                          anchor="w", padx=14, pady=(0, 10)).pack(fill="x")
            row = self.tk.Frame(banner, bg=COLORS["sidebar"])
            row.pack(anchor="w", padx=10, pady=(0, 12))

            def _do_restore() -> None:
                from tkinter import messagebox
                from idle_shutdown.restore import restore as _restore
                try:
                    res = _restore(snap_id)
                    messagebox.showinfo(
                        "Frozen — Restore complete",
                        f"Restored snapshot #{res.snapshot_id}: "
                        f"launched={res.apps_launched}, "
                        f"skipped={res.apps_skipped}.",
                    )
                except Exception as e:  # noqa: BLE001
                    messagebox.showerror("Restore failed", str(e))
                self.win.show("dashboard")

            def _dismiss() -> None:
                try:
                    with connect() as conn:
                        SettingsRepo(conn).set("LastRestoredSnapshotId", snap_id)
                except Exception:  # noqa: BLE001
                    pass
                self.win.show("dashboard")

            _make_button(row, text="Restore now",
                         bg=COLORS["accent"], hover_bg=COLORS["accent_hi"],
                         fg="#ffffff", command=_do_restore,
                         padx=18, pady=8).pack(side="left", padx=4)
            _make_button(row, text="Dismiss",
                         bg=COLORS["sidebar_hi"], hover_bg=COLORS["border"],
                         fg=COLORS["fg"], command=_dismiss,
                         padx=18, pady=8).pack(side="left", padx=4)

        # Recent shutdowns
        ttk.Label(wrap, text="Recent shutdowns",
                  style="H2.TLabel").pack(anchor="w", pady=(24, 8), **pad)
        try:
            with connect() as conn:
                rows = ShutdownLogRepo(conn).recent(limit=8)
        except Exception:  # noqa: BLE001
            rows = []
        if not rows:
            ttk.Label(wrap, text="No shutdowns recorded yet.",
                      style="Muted.TLabel").pack(anchor="w", pady=(0, 24), **pad)
        else:
            tv = self.ttk.Treeview(wrap, columns=("when", "outcome", "snap"),
                                   show="headings", height=min(8, len(rows)))
            tv.heading("when", text="When (UTC)")
            tv.heading("outcome", text="Outcome")
            tv.heading("snap", text="Snapshot")
            tv.column("when", width=240)
            tv.column("outcome", width=140)
            tv.column("snap", width=100, anchor="center")
            for r in rows:
                tv.insert("", "end", values=(r.occurred_at,
                                             r.outcome.name if hasattr(r.outcome, "name") else str(r.outcome),
                                             r.snapshot_id or "—"))
            tv.pack(fill="x", pady=(0, 24), **pad)

    def _card(self, parent, title: str, value: str, value_style: str, col: int) -> None:
        f = self.ttk.Frame(parent, style="Panel.TFrame")
        f.grid(row=0, column=col, sticky="nsew", padx=(0, 12) if col < 2 else (0, 0))
        f.configure(padding=0)
        # rounded card via tk.Frame with bg
        inner = self.tk.Frame(f, bg=COLORS["sidebar"], padx=18, pady=16,
                              highlightthickness=1, highlightbackground=COLORS["border"])
        inner.pack(fill="both", expand=True)
        self.tk.Label(inner, text=title, bg=COLORS["sidebar"],
                      fg=COLORS["fg_muted"], font=("Helvetica", 10),
                      anchor="w").pack(anchor="w")
        color = (COLORS["ok"] if value_style == "OK.TLabel"
                 else COLORS["warn"] if value_style == "Warn.TLabel"
                 else COLORS["accent"])
        self.tk.Label(inner, text=value, bg=COLORS["sidebar"], fg=color,
                      font=("Helvetica", 22, "bold"),
                      anchor="w").pack(anchor="w", pady=(6, 0))

    def _var_card(self, parent, title: str, var, col: int) -> None:
        f = self.ttk.Frame(parent, style="Panel.TFrame")
        f.grid(row=0, column=col, sticky="nsew",
               padx=(0, 12) if col < 2 else (0, 0))
        inner = self.tk.Frame(f, bg=COLORS["sidebar"], padx=18, pady=16,
                              highlightthickness=1,
                              highlightbackground=COLORS["border"])
        inner.pack(fill="both", expand=True)
        self.tk.Label(inner, text=title, bg=COLORS["sidebar"],
                      fg=COLORS["fg_muted"], font=("Helvetica", 10),
                      anchor="w").pack(anchor="w")
        self.tk.Label(inner, textvariable=var, bg=COLORS["sidebar"],
                      fg=COLORS["accent"], font=("Helvetica", 22, "bold"),
                      anchor="w").pack(anchor="w", pady=(6, 0))


class SettingsPanel(_PanelBase):  # pragma: no cover - GUI
    def build(self) -> None:
        from tkinter import messagebox
        wrap = self._scrollable()
        ttk = self.ttk
        pad = {"padx": 32}

        ttk.Label(wrap, text="Settings", style="Title.TLabel").pack(
            anchor="w", pady=(28, 4), **pad)
        ttk.Label(wrap, text="All values are saved to the local database.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 20), **pad)

        s = _all_settings()
        vars: dict[str, object] = {}

        def card(label: str, helptext: str, widget_factory) -> None:
            outer = self.tk.Frame(wrap, bg=COLORS["panel"])
            outer.pack(fill="x", pady=6, **pad)
            inner = self.tk.Frame(
                outer, bg=COLORS["sidebar"], padx=20, pady=16,
                highlightthickness=1, highlightbackground=COLORS["border"],
            )
            inner.pack(fill="x")
            self.tk.Label(inner, text=label, bg=COLORS["sidebar"],
                          fg=COLORS["fg"], font=("Helvetica", 13, "bold"),
                          anchor="w", justify="left").pack(anchor="w")
            if helptext:
                self.tk.Label(inner, text=helptext, bg=COLORS["sidebar"],
                              fg=COLORS["fg_muted"], font=("Helvetica", 11),
                              anchor="w", justify="left",
                              wraplength=720).pack(anchor="w", pady=(2, 10))
            widget_factory(inner).pack(anchor="w", pady=(2, 0))

        # Idle threshold
        v_idle = self.tk.StringVar(value=s.get("IdleThresholdMinutes", "10"))
        vars["IdleThresholdMinutes"] = v_idle
        card("Prompt after idle minutes",
            "How long the computer must be untouched before Frozen asks "
            "“are you still there?” (1–240).",
            lambda f: ttk.Spinbox(f, from_=1, to=240, width=8, textvariable=v_idle))

        # Countdown
        v_cd = self.tk.StringVar(value=s.get("PopupCountdownSeconds", "10"))
        vars["PopupCountdownSeconds"] = v_cd
        card("Popup countdown (seconds)",
            "How long the popup waits for an answer before snapshotting "
            "and shutting down (5–120).",
            lambda f: ttk.Spinbox(f, from_=5, to=120, width=8, textvariable=v_cd))

        # Service state
        v_svc = self.tk.StringVar(value=s.get("ServiceState", "Enabled"))
        vars["ServiceState"] = v_svc
        card("Service state",
            "Disable to keep Frozen installed but never auto-shut down.",
            lambda f: ttk.Combobox(f, values=["Enabled", "Disabled"],
                                   textvariable=v_svc, width=14, state="readonly"))

        def bool_row(key: str, label: str, helptext: str) -> None:
            v = self.tk.BooleanVar(value=str(s.get(key, "false")).lower() == "true")
            vars[key] = v
            outer = self.tk.Frame(wrap, bg=COLORS["panel"])
            outer.pack(fill="x", pady=6, **pad)
            inner = self.tk.Frame(
                outer, bg=COLORS["sidebar"], padx=20, pady=14,
                highlightthickness=1, highlightbackground=COLORS["border"],
            )
            inner.pack(fill="x")
            row = self.tk.Frame(inner, bg=COLORS["sidebar"])
            row.pack(fill="x")
            text_col = self.tk.Frame(row, bg=COLORS["sidebar"])
            text_col.pack(side="left", fill="x", expand=True)
            self.tk.Label(text_col, text=label, bg=COLORS["sidebar"],
                          fg=COLORS["fg"], font=("Helvetica", 12, "bold"),
                          anchor="w", justify="left",
                          wraplength=620).pack(anchor="w")
            if helptext:
                self.tk.Label(text_col, text=helptext, bg=COLORS["sidebar"],
                              fg=COLORS["fg_muted"], font=("Helvetica", 10),
                              anchor="w", justify="left",
                              wraplength=620).pack(anchor="w", pady=(2, 0))
            toggle = self.tk.Label(
                row, bg=COLORS["sidebar"], cursor="hand2",
                font=("Helvetica", 14, "bold"), padx=14, pady=4,
            )
            toggle.pack(side="right", padx=(12, 0))

            def render(*_a) -> None:
                if v.get():
                    toggle.configure(text="ON ●", fg="#ffffff",
                                     bg=COLORS["accent"])
                else:
                    toggle.configure(text="● OFF", fg=COLORS["fg_muted"],
                                     bg=COLORS["input_bg"])

            def flip(_e=None) -> None:
                v.set(not v.get())
                render()

            toggle.bind("<Button-1>", flip)
            render()

        bool_row("DryRun",
                 "Dry run (do not actually shut down)",
                 "Recommended while testing. The snapshot is still taken.")
        bool_row("AutoRestoreOnBoot",
                 "Restore last session on boot",
                 "Re-launches your apps and Chrome tabs after sign-in.")
        bool_row("GuardMicEnabled",
                 "Don't shut down while microphone is in use", "")
        bool_row("GuardAudioEnabled",
                 "Don't shut down while audio is playing", "")
        bool_row("GuardFullscreenEnabled",
                 "Don't shut down while a fullscreen app is active", "")
        bool_row("GuardCameraEnabled",
                 "Don't shut down while the camera is in use", "")

        # Buttons
        btns = self.tk.Frame(wrap, bg=COLORS["panel"])
        btns.pack(fill="x", pady=(20, 28), **pad)

        def save() -> None:
            errors: list[str] = []
            for key, var in vars.items():
                raw = "true" if isinstance(var, self.tk.BooleanVar) and var.get() \
                      else "false" if isinstance(var, self.tk.BooleanVar) \
                      else str(var.get())
                try:
                    get_setting_def(key).validate(raw)
                    _set_setting(key, raw)
                except IdleShutdownError as e:
                    errors.append(f"{key}: {e.message}")
            if errors:
                messagebox.showerror("Some settings could not be saved",
                                     "\n".join(errors))
            else:
                messagebox.showinfo("Saved", "Settings updated.")

        save_btn = _make_button(
            btns, text="Save changes", bg=COLORS["accent"],
            hover_bg=COLORS["accent_hi"], fg="#ffffff", command=save,
        )
        save_btn.pack(side="left")
        reload_btn = _make_button(
            btns, text="Reload", bg=COLORS["sidebar_hi"],
            hover_bg=COLORS["border"], fg=COLORS["fg"],
            command=lambda: SettingsPanel(self.parent, self.tk, self.ttk).build(),
        )
        reload_btn.pack(side="left", padx=(10, 0))


class SnapshotsPanel(_PanelBase):  # pragma: no cover - GUI
    def build(self) -> None:
        from tkinter import messagebox
        from idle_shutdown.enums import SnapshotTriggerKind
        from idle_shutdown.snapshot import take_snapshot
        from idle_shutdown.restore import restore as run_restore

        wrap = self._scrollable()
        ttk = self.ttk
        pad = {"padx": 32}

        ttk.Label(wrap, text="Snapshots", style="Title.TLabel").pack(
            anchor="w", pady=(28, 4), **pad)
        ttk.Label(wrap, text="Take a snapshot of your current session, "
                            "or restore one from the database.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 20), **pad)

        # Action buttons
        actions = ttk.Frame(wrap, style="Panel.TFrame")
        actions.pack(fill="x", pady=(0, 18), **pad)

        latest_label_var = self.tk.StringVar(value="")

        def refresh_latest() -> None:
            try:
                with connect() as conn:
                    lid = SnapshotReadRepo(conn).latest_id()
            except Exception:  # noqa: BLE001
                lid = None
            latest_label_var.set(f"Latest snapshot: #{lid}" if lid else
                                 "No snapshots yet.")

        def do_snapshot() -> None:
            try:
                res = take_snapshot(SnapshotTriggerKind.Manual, record_log=False)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Snapshot failed", str(e))
                return
            messagebox.showinfo(
                "Snapshot taken",
                f"#{res.snapshot_id}\n\n"
                f"{res.app_count} apps · {res.chrome_profile_count} Chrome profiles\n"
                f"{res.chrome_window_count} windows · {res.chrome_tab_count} tabs\n"
                f"{res.desktop_count} virtual desktops",
            )
            refresh_latest()
            refresh_history()

        def do_restore() -> None:
            if not messagebox.askyesno(
                    "Restore latest snapshot?",
                    "This will re-launch the apps and Chrome tabs from the most "
                    "recent snapshot. Continue?"):
                return
            try:
                res = run_restore(None)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Restore failed", str(e))
                return
            messagebox.showinfo(
                "Restore complete",
                f"Snapshot #{res.snapshot_id}\n"
                f"Apps launched: {res.apps_launched} · skipped: {res.apps_skipped}\n"
                f"Chrome launched: {'yes' if res.chrome_launched else 'no'}",
            )

        ttk.Button(actions, text="📸  Take snapshot now",
                   style="Accent.TButton",
                   command=do_snapshot).pack(side="left")
        ttk.Button(actions, text="↺  Restore latest",
                   command=do_restore).pack(side="left", padx=(8, 0))
        ttk.Label(actions, textvariable=latest_label_var,
                  style="Muted.TLabel").pack(side="left", padx=(20, 0))
        refresh_latest()

        # Snapshot list (latest 30)
        ttk.Label(wrap, text="History", style="H2.TLabel").pack(
            anchor="w", pady=(20, 8), **pad)

        from idle_shutdown.enums import SnapshotTriggerKind as STK
        empty_var = self.tk.StringVar(value="")
        empty_lbl = ttk.Label(wrap, textvariable=empty_var,
                              style="Muted.TLabel")
        empty_lbl.pack(anchor="w", pady=(0, 8), **pad)

        tv = ttk.Treeview(wrap, columns=("id", "when", "trigger"),
                          show="headings", height=12)
        tv.heading("id", text="ID")
        tv.heading("when", text="Created (UTC)")
        tv.heading("trigger", text="Trigger")
        tv.column("id", width=80, anchor="center")
        tv.column("when", width=260)
        tv.column("trigger", width=120)
        tv.pack(fill="x", pady=(0, 8), **pad)

        def refresh_history() -> None:
            for iid in tv.get_children():
                tv.delete(iid)
            rows: list[tuple] = []
            err: str | None = None
            try:
                with connect() as conn:
                    cur = conn.execute(
                        "SELECT SnapshotId, CreatedAt, TriggerKindId "
                        "FROM Snapshot ORDER BY SnapshotId DESC LIMIT 30")
                    rows = list(cur.fetchall())
            except Exception as e:  # noqa: BLE001
                err = str(e)
            if err:
                empty_var.set(f"Could not read snapshots: {err}")
                return
            if not rows:
                empty_var.set("No snapshots in database yet.")
                return
            empty_var.set("")
            for r in rows:
                try:
                    trig = STK(r[2]).name
                except Exception:  # noqa: BLE001
                    trig = str(r[2])
                tv.insert("", "end", values=(r[0], r[1], trig))

        refresh_history()

        def _selected_snapshot_id() -> int | None:
            sel = tv.selection()
            if not sel:
                return None
            try:
                return int(tv.item(sel[0], "values")[0])
            except Exception:  # noqa: BLE001
                return None

        def do_restore_selected(_event=None) -> None:  # noqa: ANN001
            sid = _selected_snapshot_id()
            if sid is None:
                messagebox.showinfo(
                    "No snapshot selected",
                    "Pick a snapshot from the list first.")
                return
            if not messagebox.askyesno(
                    "Restore snapshot?",
                    f"Reopen the apps and Chrome tabs from snapshot #{sid}?"):
                return
            try:
                res = run_restore(sid)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Restore failed", str(e))
                return
            messagebox.showinfo(
                "Restore complete",
                f"Snapshot #{res.snapshot_id}\n"
                f"Apps launched: {res.apps_launched}\n"
                f"Chrome launched: {'yes' if res.chrome_launched else 'no'}")

        tv.bind("<Double-1>", do_restore_selected)

        row_actions = ttk.Frame(wrap, style="Panel.TFrame")
        row_actions.pack(fill="x", pady=(0, 28), **pad)
        ttk.Button(row_actions, text="↺  Open selected snapshot",
                   style="Primary.TButton",
                   command=do_restore_selected).pack(side="left")
        ttk.Button(row_actions, text="⟳  Refresh",
                   command=refresh_history).pack(side="left", padx=(8, 0))
        ttk.Label(row_actions,
                  text="Tip: double-click a row to open it.",
                  style="Muted.TLabel").pack(side="left", padx=(12, 0))


class AboutPanel(_PanelBase):  # pragma: no cover - GUI
    def build(self) -> None:
        wrap = self.ttk.Frame(self.parent, style="Panel.TFrame")
        wrap.pack(fill="both", expand=True)
        pad = {"padx": 32}
        self.ttk.Label(wrap, text="About Frozen", style="Title.TLabel").pack(
            anchor="w", pady=(28, 4), **pad)
        body = (
            "Frozen is an idle-shutdown and session-restore utility.\n\n"
            "When your computer is idle for the configured number of minutes, "
            "Frozen pops up to ask if you're still there. If you don't answer, "
            "it captures your open apps, virtual desktops and Chrome tabs to a "
            "local database, then shuts down. On the next sign-in it can put "
            "everything back.\n\n"
            "Everything stays on this machine — no cloud, no telemetry."
        )
        self.ttk.Label(wrap, text=body, style="Muted.TLabel",
                       wraplength=620, justify="left").pack(anchor="w", **pad)
        self.ttk.Label(wrap, text="Tip: leave Dry run ON until you've tested "
                                  "the popup at least once.",
                       style="Muted.TLabel").pack(anchor="w", pady=(20, 0), **pad)


# ---------- first-run wizard ------------------------------------------------


def _run_first_run_wizard(root, tk, ttk) -> None:  # pragma: no cover - GUI
    """Modal wizard asking for the basics, then marks FirstRunCompleted=true."""
    from tkinter import messagebox

    win = tk.Toplevel(root)
    win.title("Welcome to Frozen")
    win.configure(bg=COLORS["panel"])
    win.geometry("560x520")
    win.transient(root)
    win.grab_set()

    pad = {"padx": 32}
    ttk.Label(win, text="Welcome to Frozen ❄", style="Title.TLabel").pack(
        anchor="w", pady=(28, 4), **pad)
    ttk.Label(win,
              text="A few quick questions, then you're ready.",
              style="Muted.TLabel").pack(anchor="w", pady=(0, 20), **pad)

    # Idle minutes
    ttk.Label(win, text="After how many minutes of inactivity should I ask "
                        "if you're still at the desk?",
              style="H2.TLabel", wraplength=480).pack(anchor="w", **pad)
    v_idle = tk.StringVar(value=str(_get_setting("IdleThresholdMinutes") or 10))
    ttk.Spinbox(win, from_=1, to=240, width=8,
                textvariable=v_idle).pack(anchor="w", pady=(6, 16), **pad)

    # Countdown
    ttk.Label(win, text="When the popup appears, how many seconds should it "
                        "wait for an answer before saving and shutting down?",
              style="H2.TLabel", wraplength=480).pack(anchor="w", **pad)
    v_cd = tk.StringVar(value=str(_get_setting("PopupCountdownSeconds") or 30))
    ttk.Spinbox(win, from_=5, to=120, width=8,
                textvariable=v_cd).pack(anchor="w", pady=(6, 16), **pad)

    # Dry run
    v_dry = tk.BooleanVar(
        value=str(_get_setting("DryRun") or "true").lower() == "true")
    ttk.Checkbutton(win,
                    text="Dry run for now (don't really shut down — just save "
                         "the snapshot and show a popup)",
                    variable=v_dry).pack(anchor="w", pady=(8, 4), **pad)

    # Auto restore
    v_auto = tk.BooleanVar(
        value=str(_get_setting("AutoRestoreOnBoot") or "true").lower() == "true")
    ttk.Checkbutton(win, text="Restore my last session after I sign back in",
                    variable=v_auto).pack(anchor="w", pady=(0, 4), **pad)

    btns = ttk.Frame(win, style="Panel.TFrame")
    btns.pack(side="bottom", fill="x", pady=20, **pad)

    def finish() -> None:
        try:
            get_setting_def("IdleThresholdMinutes").validate(v_idle.get())
            get_setting_def("PopupCountdownSeconds").validate(v_cd.get())
        except IdleShutdownError as e:
            messagebox.showerror("Invalid value", e.message)
            return
        _set_setting("IdleThresholdMinutes", v_idle.get())
        _set_setting("PopupCountdownSeconds", v_cd.get())
        _set_setting("DryRun", "true" if v_dry.get() else "false")
        _set_setting("AutoRestoreOnBoot", "true" if v_auto.get() else "false")
        _set_setting("FirstRunCompleted", "true")
        win.grab_release()
        win.destroy()

    ttk.Button(btns, text="Get started", style="Accent.TButton",
               command=finish).pack(side="right")
    ttk.Button(btns, text="Skip",
               command=lambda: (_set_setting("FirstRunCompleted", "true"),
                                 win.grab_release(), win.destroy())
               ).pack(side="right", padx=(0, 8))

    root.wait_window(win)