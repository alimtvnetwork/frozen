"""Session restore: replay the latest (or given) snapshot.

Implements the duplicate-prevention rule from spec/21-app/06-startup-and-restore/:
for each AppProcess row, skip the launch if a running process matches the
executable path AND the document path (case/normpath-insensitive).

Runs are idempotent: a second invocation with the same snapshot must launch
nothing. ``LastRestoredSnapshotId`` and ``LastRestoredAt`` settings are
updated on completion.
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable

from idle_shutdown.db.connection import connect, utc_now_iso
from idle_shutdown.db.repos import SettingsRepo
from idle_shutdown.errors import RestoreError

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
class SnapshotData:
    snapshot_id: int
    desktop_count: int
    apps: tuple[AppRow, ...]
    chrome_executable: str | None
    chrome_tabs: tuple[TabRow, ...]


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
            "SELECT t.Url, t.Title FROM ChromeTab t "
            "JOIN ChromeWindow w ON w.ChromeWindowId = t.ChromeWindowId "
            "WHERE w.SnapshotId = ? ORDER BY w.WindowIndex, t.TabIndex",
            (sid,),
        ).fetchall()
        chrome_exe = SettingsRepo(conn).get_raw("ChromeExecutablePath") or None

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
        chrome_tabs=tuple(TabRow(str(r["Url"]), str(r["Title"])) for r in tab_rows),
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


def _ensure_desktops_default(_count: int) -> None:  # pragma: no cover
    # MVP: pyvda will be wired in Phase 5 stretch. No-op keeps tests cross-platform.
    return


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


def restore(
    snapshot_id: int | None = None,
    *,
    live_processes: Callable[[], list[LiveProcess]] | None = None,
    spawn: Callable[[list[str], str | None], None] | None = None,
    ensure_desktops: Callable[[int], None] = _ensure_desktops_default,
    now_iso: Callable[[], str] = utc_now_iso,
) -> RestoreResult:
    data = _read_snapshot(snapshot_id)
    live_fn = live_processes or _default_live_processes
    spawn_fn = spawn or (lambda argv, cwd: subprocess.Popen(argv, cwd=cwd))  # type: ignore[arg-type]

    logger.info("event=restore_started snapshot_id=%d apps=%d chrome_tabs=%d",
                data.snapshot_id, len(data.apps), len(data.chrome_tabs))
    ensure_desktops(data.desktop_count)

    live = list(live_fn())
    launched = skipped = 0
    for app in data.apps:
        if _is_duplicate(app, live):
            logger.info("event=skip_relaunch exe=%s doc=%s reason=already_running",
                        app.executable_path, app.document_path)
            skipped += 1
            continue
        argv = [app.executable_path]
        if app.document_path:
            argv.append(app.document_path)
        try:
            spawn_fn(argv, app.working_directory)
            launched += 1
            logger.info("event=restore_item exe=%s status=launched", app.executable_path)
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
    )