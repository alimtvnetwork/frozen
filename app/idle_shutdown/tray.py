"""System-tray icon (Phase 6 — optional UX).

Lightweight status surface that runs in its own thread alongside the monitor.
Uses ``pystray`` + ``Pillow`` — both optional. Install via:
    pip install -e ".[tray]"

The tray shows:
  - current idle seconds (refreshed every 5 s)
  - latest snapshot id + age
  - quick actions: Snapshot now / Snooze N min / Open data folder / Quit

Designed to be import-safe even when pystray/Pillow are absent so the rest
of the CLI keeps working.
"""
from __future__ import annotations

import logging
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from idle_shutdown.config import app_data_dir

logger = logging.getLogger(__name__)


def _try_import():
    try:
        import pystray  # type: ignore
        from PIL import Image, ImageDraw  # type: ignore
        return pystray, Image, ImageDraw
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Tray icon requires optional deps. Install with:\n"
            '  pip install -e ".[tray]"\n'
            f"(import error: {e})"
        ) from e


def _make_icon_image(active: bool):
    """Tiny 64x64 status dot — green=active, grey=disabled."""
    _, Image, ImageDraw = _try_import()
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (46, 160, 67, 255) if active else (130, 130, 130, 255)
    d.ellipse((6, 6, 58, 58), fill=color, outline=(20, 20, 20, 255), width=2)
    return img


def _fmt_age(iso: Optional[str]) -> str:
    if not iso:
        return "never"
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        s = int(delta.total_seconds())
        if s < 60:
            return f"{s}s ago"
        if s < 3600:
            return f"{s // 60}m ago"
        if s < 86400:
            return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"
    except Exception:  # noqa: BLE001
        return iso


def run_tray(
    *,
    get_idle_seconds: Callable[[], int],
    get_service_enabled: Callable[[], bool],
    get_latest_snapshot: Callable[[], tuple[Optional[int], Optional[str]]],
    get_snooze_minutes: Callable[[], int],
    snapshot_now: Callable[[], None],
    snooze: Callable[[int], None],
    on_quit: Callable[[], None],
) -> None:
    """Block the calling thread running the tray loop. Call from a daemon thread."""
    pystray, _Image, _Draw = _try_import()

    state = {"active": True, "idle": 0, "snap_id": None, "snap_age": "never"}

    def _title() -> str:
        return (
            f"Idle Shutdown — {'on' if state['active'] else 'off'}\n"
            f"idle: {state['idle']}s\n"
            f"last snapshot: #{state['snap_id'] or '-'} ({state['snap_age']})"
        )

    def _on_snapshot(_icon, _item):  # noqa: ANN001
        try:
            snapshot_now()
        except Exception as e:  # noqa: BLE001
            logger.warning("tray snapshot failed: %s", e)

    def _on_snooze(_icon, _item):  # noqa: ANN001
        try:
            snooze(int(get_snooze_minutes()))
        except Exception as e:  # noqa: BLE001
            logger.warning("tray snooze failed: %s", e)

    def _on_open_folder(_icon, _item):  # noqa: ANN001
        path = app_data_dir()
        try:
            webbrowser.open(Path(path).as_uri())
        except Exception as e:  # noqa: BLE001
            logger.warning("open folder failed: %s", e)

    def _on_quit(icon, _item):  # noqa: ANN001
        try:
            on_quit()
        finally:
            icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda _i: f"Idle: {state['idle']}s", None, enabled=False),
        pystray.MenuItem(
            lambda _i: f"Snapshot #{state['snap_id'] or '-'} ({state['snap_age']})",
            None, enabled=False,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Snapshot now", _on_snapshot),
        pystray.MenuItem(
            lambda _i: f"Snooze {int(get_snooze_minutes())}m", _on_snooze),
        pystray.MenuItem("Open data folder", _on_open_folder),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", _on_quit),
    )
    icon = pystray.Icon(
        "idle-shutdown",
        _make_icon_image(True),
        "Idle Shutdown",
        menu,
    )

    def _refresh_loop() -> None:
        last_active = True
        while getattr(icon, "visible", False) is False and not getattr(icon, "_running", False):
            time.sleep(0.1)
        while True:
            try:
                state["idle"] = int(get_idle_seconds())
                state["active"] = bool(get_service_enabled())
                snap_id, iso = get_latest_snapshot()
                state["snap_id"] = snap_id
                state["snap_age"] = _fmt_age(iso)
                if state["active"] != last_active:
                    icon.icon = _make_icon_image(state["active"])
                    last_active = state["active"]
                icon.title = _title()
            except Exception as e:  # noqa: BLE001
                logger.debug("tray refresh error: %s", e)
            time.sleep(5)

    t = threading.Thread(target=_refresh_loop, daemon=True, name="tray-refresh")
    t.start()
    icon.run()