"""Session restore: replay the latest (or given) snapshot.

Implements the duplicate-prevention rule from spec/21-app/06-startup-and-restore/:
for each AppProcess row, skip the launch if a running process matches the
executable path AND the document path (case/normpath-insensitive).

Runs are idempotent: a second invocation with the same snapshot must launch
nothing. ``LastRestoredSnapshotId`` and ``LastRestoredAt`` settings are
updated on completion.

Per-desktop restore (Phase 5 stretch): apps captured on virtual desktop *N*
are relaunched on virtual desktop *N*. Implementation:
  1. ``ensure_desktops(N)`` creates missing virtual desktops up to N.
  2. Apps are launched grouped by ``desktop_index``. Before each group we
     ``switch_to_desktop(idx)`` so newly spawned top-level windows land
     there; after spawn we additionally call ``move_to_desktop(pid, idx)``
     to handle apps that pop their main window asynchronously.
All three desktop callbacks are injectable; defaults use ``pyvda`` on Windows
and no-op elsewhere so the test suite stays cross-platform.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from itertools import groupby
from typing import Callable, Iterable, Optional

from idle_shutdown.db.connection import connect, utc_now_iso
from idle_shutdown.db.repos import RestoreExclusionRepo, SettingsRepo
from idle_shutdown.errors import RestoreError
from idle_shutdown.capture.chrome import detect_variant_executable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppRow:
    executable_path: str
    working_directory: str | None
    document_path: str | None
    desktop_index: int


@dataclass(frozen=True)
class TabRow:
    url: str
    title: str


@dataclass(frozen=True)
class BrowserSession:
    browser_name: str
    executable_path: str | None
    tabs: tuple[TabRow, ...]


@dataclass(frozen=True)
class SnapshotData:
    snapshot_id: int
    desktop_count: int
    apps: tuple[AppRow, ...]
    chrome_executable: str | None
    chrome_tabs: tuple[TabRow, ...]
    variant_sessions: tuple[BrowserSession, ...] = ()


@dataclass(frozen=True)
class LiveProcess:
    pid: int
    exe: str
    cmdline: tuple[str, ...]


def _norm(path: str) -> str:
    return os.path.normpath(path.replace("\\", os.sep)).lower()


def _read_snapshot(snapshot_id: int | None) -> SnapshotData:
    with connect() as conn:
        if snapshot_id is None:
            row = conn.execute(
                "SELECT SnapshotId FROM Snapshot ORDER BY SnapshotId DESC LIMIT 1"
            ).fetchone()
            if row is None:
                raise RestoreError("no snapshot available to restore")
            sid = int(row["SnapshotId"])
        else:
            row = conn.execute(
                "SELECT SnapshotId FROM Snapshot WHERE SnapshotId = ?", (snapshot_id,)
            ).fetchone()
            if row is None:
                raise RestoreError(f"snapshot {snapshot_id} not found")
            sid = int(row["SnapshotId"])

        desks = conn.execute(
            "SELECT COUNT(*) AS c FROM VirtualDesktop WHERE SnapshotId = ?", (sid,)
        ).fetchone()
        apps_rows = conn.execute(
            "SELECT a.ExecutablePath, a.WorkingDirectory, a.DocumentPath, v.DesktopIndex "
            "FROM AppProcess a JOIN VirtualDesktop v ON v.VirtualDesktopId = a.VirtualDesktopId "
            "WHERE v.SnapshotId = ? ORDER BY a.AppProcessId",
            (sid,),
        ).fetchall()
        tab_rows = conn.execute(
            "SELECT t.Url, t.Title, "
            "       COALESCE(p.BrowserName, 'Chrome') AS BrowserName "
            "FROM ChromeTab t "
            "JOIN ChromeWindow w ON w.ChromeWindowId = t.ChromeWindowId "
            "LEFT JOIN ChromeProfile p ON p.ChromeProfileId = w.ChromeProfileId "
            "WHERE w.SnapshotId = ? ORDER BY p.BrowserName, w.WindowIndex, t.TabIndex",
            (sid,),
        ).fetchall()
        chrome_exe = SettingsRepo(conn).get_raw("ChromeExecutablePath") or None

    # Split tabs by browser. Anything labelled "Chrome" (or unlabelled,
    # legacy rows) goes into the primary chrome_tabs list. The rest become
    # one BrowserSession per browser, in stable alphabetical order.
    by_browser: dict[str, list[TabRow]] = {}
    for r in tab_rows:
        bname = str(r["BrowserName"]) or "Chrome"
        by_browser.setdefault(bname, []).append(TabRow(str(r["Url"]), str(r["Title"])))
    chrome_tabs = tuple(by_browser.pop("Chrome", []))
    variants = tuple(
        BrowserSession(
            browser_name=name,
            executable_path=detect_variant_executable(name),
            tabs=tuple(tabs),
        )
        for name, tabs in sorted(by_browser.items())
    )

    return SnapshotData(
        snapshot_id=sid,
        desktop_count=int(desks["c"]) or 1,
        apps=tuple(AppRow(
            executable_path=str(r["ExecutablePath"]),
            working_directory=(str(r["WorkingDirectory"]) if r["WorkingDirectory"] else None),
            document_path=(str(r["DocumentPath"]) if r["DocumentPath"] else None),
            desktop_index=int(r["DesktopIndex"]),
        ) for r in apps_rows),
        chrome_executable=chrome_exe,
        chrome_tabs=chrome_tabs,
        variant_sessions=variants,
    )


def _default_live_processes() -> list[LiveProcess]:  # pragma: no cover
    import psutil  # type: ignore
    out: list[LiveProcess] = []
    for p in psutil.process_iter(["pid", "exe", "cmdline"]):
        try:
            i = p.info
            if not i.get("exe"):
                continue
            out.append(LiveProcess(
                pid=int(i["pid"]), exe=str(i["exe"]),
                cmdline=tuple(i.get("cmdline") or [])
            ))
        except Exception:  # noqa: BLE001
            continue
    return out


def _ensure_desktops_default(count: int) -> None:  # pragma: no cover
    """Create virtual desktops until at least ``count`` exist. Win32 only."""
    import sys
    if sys.platform != "win32" or count <= 1:
        return
    try:
        import pyvda  # type: ignore
        existing = len(list(pyvda.get_virtual_desktops()))
        for _ in range(max(0, count - existing)):
            pyvda.VirtualDesktop.create()
    except Exception as e:  # noqa: BLE001
        logger.warning("event=ensure_desktops_failed count=%d err=%s", count, e)


def _switch_to_desktop_default(index: int) -> None:  # pragma: no cover
    import sys
    if sys.platform != "win32":
        return
    try:
        import pyvda  # type: ignore
        desktops = list(pyvda.get_virtual_desktops())
        if 0 <= index < len(desktops):
            desktops[index].go()
    except Exception as e:  # noqa: BLE001
        logger.warning("event=switch_desktop_failed index=%d err=%s", index, e)


def _move_to_desktop_default(pid: int, index: int) -> None:  # pragma: no cover
    """Best-effort: poll briefly for a top-level window of ``pid`` and pin it."""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        import pyvda  # type: ignore

        desktops = list(pyvda.get_virtual_desktops())
        if not (0 <= index < len(desktops)):
            return
        target = desktops[index]

        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            found: list[int] = []

            def _cb(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                wpid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
                if int(wpid.value) == pid:
                    found.append(int(hwnd))
                return True

            user32.EnumWindows(EnumWindowsProc(_cb), 0)
            if found:
                for hwnd in found:
                    try:
                        pyvda.AppView(hwnd=hwnd).move(target)
                    except Exception:  # noqa: BLE001
                        pass
                return
            time.sleep(0.1)
    except Exception as e:  # noqa: BLE001
        logger.warning("event=move_desktop_failed pid=%d index=%d err=%s", pid, index, e)


def _is_duplicate(app: AppRow, live: Iterable[LiveProcess]) -> bool:
    target_exe = _norm(app.executable_path)
    target_doc = _norm(app.document_path) if app.document_path else None
    for proc in live:
        if _norm(proc.exe) != target_exe:
            continue
        if target_doc is None:
            return True
        joined = " ".join(proc.cmdline).lower().replace("\\", os.sep)
        if target_doc in joined:
            return True
    return False


@dataclass(frozen=True)
class RestoreResult:
    snapshot_id: int
    apps_launched: int
    apps_skipped: int
    chrome_launched: bool
    variants_launched: tuple[str, ...] = ()
    apps_excluded: int = 0


def restore(
    snapshot_id: int | None = None,
    *,
    live_processes: Callable[[], list[LiveProcess]] | None = None,
    spawn: Callable[[list[str], str | None], Optional[int]] | None = None,
    ensure_desktops: Callable[[int], None] = _ensure_desktops_default,
    switch_to_desktop: Callable[[int], None] = _switch_to_desktop_default,
    move_to_desktop: Callable[[int, int], None] = _move_to_desktop_default,
    now_iso: Callable[[], str] = utc_now_iso,
    dry_run: bool = False,
) -> RestoreResult:
    data = _read_snapshot(snapshot_id)
    live_fn = live_processes or _default_live_processes

    def _default_spawn(argv: list[str], cwd: str | None) -> Optional[int]:
        proc = subprocess.Popen(argv, cwd=cwd)  # noqa: S603
        return proc.pid

    spawn_fn = spawn or _default_spawn

    logger.info("event=restore_started snapshot_id=%d apps=%d chrome_tabs=%d",
                data.snapshot_id, len(data.apps), len(data.chrome_tabs))
    if not dry_run:
        ensure_desktops(data.desktop_count)

    live = list(live_fn())
    launched = skipped = excluded = 0
    with connect() as conn:
        excluded_paths = RestoreExclusionRepo(conn).excluded_paths()

    # Group apps by target desktop so we switch once per desktop, preserving
    # the original AppProcessId order within each group.
    apps_sorted = sorted(enumerate(data.apps), key=lambda t: (t[1].desktop_index, t[0]))
    for desk_idx, group in groupby(apps_sorted, key=lambda t: t[1].desktop_index):
        group_apps = [a for _, a in group]
        if data.desktop_count > 1 and not dry_run:
            switch_to_desktop(desk_idx)
        for app in group_apps:
            if excluded_paths and _norm(app.executable_path) in excluded_paths:
                logger.info("event=skip_relaunch exe=%s reason=excluded",
                            app.executable_path)
                excluded += 1
                continue
            if _is_duplicate(app, live):
                logger.info("event=skip_relaunch exe=%s doc=%s reason=already_running",
                            app.executable_path, app.document_path)
                skipped += 1
                continue
            argv = [app.executable_path]
            if app.document_path:
                argv.append(app.document_path)
            try:
                pid = spawn_fn(argv, app.working_directory)
                launched += 1
                logger.info("event=restore_item exe=%s desktop=%d status=launched",
                            app.executable_path, desk_idx)
                if pid is not None and data.desktop_count > 1:
                    move_to_desktop(int(pid), desk_idx)
            except Exception as e:  # noqa: BLE001
                logger.warning("event=restore_item exe=%s status=failed err=%s",
                               app.executable_path, e)

    chrome_launched = False
    if data.chrome_executable:
        if _is_duplicate(
            AppRow(data.chrome_executable, None, None, 0), live
        ):
            logger.info("event=skip_relaunch exe=%s reason=already_running",
                        data.chrome_executable)
        else:
            argv = [data.chrome_executable, "--restore-last-session"]
            argv.extend(t.url for t in data.chrome_tabs)
            try:
                spawn_fn(argv, None)
                chrome_launched = True
                logger.info("event=restore_item exe=chrome status=launched tabs=%d",
                            len(data.chrome_tabs))
            except Exception as e:  # noqa: BLE001
                logger.warning("event=restore_item exe=chrome status=failed err=%s", e)

    variants_launched: list[str] = []
    for v in data.variant_sessions:
        if not v.executable_path:
            logger.warning(
                "event=restore_variant_skipped browser=%s reason=exe_not_found tabs=%d",
                v.browser_name, len(v.tabs),
            )
            continue
        if _is_duplicate(AppRow(v.executable_path, None, None, 0), live):
            logger.info("event=skip_relaunch exe=%s reason=already_running",
                        v.executable_path)
            continue
        argv = [v.executable_path, "--restore-last-session"]
        argv.extend(t.url for t in v.tabs)
        try:
            spawn_fn(argv, None)
            variants_launched.append(v.browser_name)
            logger.info(
                "event=restore_item browser=%s status=launched tabs=%d",
                v.browser_name, len(v.tabs),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("event=restore_item browser=%s status=failed err=%s",
                           v.browser_name, e)

    if not dry_run:
        with connect() as conn:
            repo = SettingsRepo(conn)
            repo.set("LastRestoredSnapshotId", data.snapshot_id)
            repo.set("LastRestoredAt", now_iso())

    logger.info("event=restore_completed snapshot_id=%d launched=%d skipped=%d",
                data.snapshot_id, launched, skipped)
    return RestoreResult(
        snapshot_id=data.snapshot_id,
        apps_launched=launched,
        apps_skipped=skipped,
        chrome_launched=chrome_launched,
        variants_launched=tuple(variants_launched),
        apps_excluded=excluded,
    )