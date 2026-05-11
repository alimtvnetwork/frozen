"""Transactional snapshot orchestrator.

Order matches spec/21-app/04-snapshot-capture/. On any failure inside the
main transaction, the whole snapshot rolls back and a separate
``ShutdownLog`` row is written with ``OutcomeStatusId = Failed``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from idle_shutdown.capture.apps import AppInfo, enumerate_user_apps
from idle_shutdown.capture.chrome import ChromeSession, capture_chrome_session
from idle_shutdown.capture.desktops import capture_desktops
from idle_shutdown.db.connection import connect
from idle_shutdown.db.repos import (
    CaptureRepo,
    SettingsRepo,
    ShutdownCounterRepo,
    ShutdownLogRepo,
    SnapshotRepo,
)
from idle_shutdown.enums import ShutdownOutcomeStatus, SnapshotTriggerKind
from idle_shutdown.errors import SnapshotError

logger = logging.getLogger(__name__)


@dataclass
class SnapshotProviders:
    """Injection seam used by tests to feed deterministic data."""

    capture_desktops_fn: Callable[[], tuple[int, dict[int, int]]] = capture_desktops
    enumerate_apps_fn: Callable[[dict[int, int]], list[AppInfo]] = enumerate_user_apps
    capture_chrome_fn: Callable[[], ChromeSession] = capture_chrome_session


@dataclass(frozen=True)
class SnapshotResult:
    snapshot_id: int
    desktop_count: int
    app_count: int
    chrome_profile_count: int
    chrome_window_count: int
    chrome_tab_count: int


def take_snapshot(
    trigger: SnapshotTriggerKind,
    providers: SnapshotProviders | None = None,
    *,
    record_log: bool = True,
) -> SnapshotResult:
    """Capture a session snapshot atomically.

    On success, a ``ShutdownLog`` row with ``OutcomeStatusId = Completed`` is
    written and the counter is incremented (unless ``record_log=False``,
    used by the manual ``snapshot`` CLI which does not represent a shutdown).
    On failure, a separate ``Failed`` log row is written and ``SnapshotError``
    is raised.
    """
    p = providers or SnapshotProviders()
    logger.info("event=snapshot_started trigger=%s", trigger.name)
    try:
        with connect() as conn:
            conn.execute("BEGIN")
            snap_repo = SnapshotRepo(conn)
            cap_repo = CaptureRepo(conn)
            snapshot_id = snap_repo.insert(trigger)

            desktop_count, pid_to_desktop = p.capture_desktops_fn()
            desktop_ids: dict[int, int] = {}
            for idx in range(max(1, desktop_count)):
                desktop_ids[idx] = cap_repo.insert_virtual_desktop(snapshot_id, idx)

            apps = p.enumerate_apps_fn(pid_to_desktop)
            for app in apps:
                vd_id = desktop_ids.get(app.desktop_index, desktop_ids[0])
                cap_repo.insert_app_process(
                    vd_id, app.executable_path, app.working_directory, app.document_path
                )

            chrome = p.capture_chrome_fn()
            chrome_windows_total = 0
            chrome_tabs_total = 0
            for prof in chrome.profiles:
                profile_id = cap_repo.insert_chrome_profile(
                    snapshot_id, prof.profile_dir, prof.profile_name,
                    browser_name=prof.browser_name,
                )
                for w_idx, win in enumerate(prof.windows):
                    cw_id = cap_repo.insert_chrome_window(
                        snapshot_id, w_idx, chrome_profile_id=profile_id,
                    )
                    chrome_windows_total += 1
                    tabs = [
                        (t_idx, tab.url, tab.title, tab.group)
                        for t_idx, tab in enumerate(win.tabs)
                    ]
                    chrome_tabs_total += len(tabs)
                    if tabs:
                        cap_repo.insert_chrome_tabs(cw_id, tabs)

            # Cache last-detected Chrome path
            if chrome.executable_path:
                SettingsRepo(conn).set("ChromeExecutablePath", chrome.executable_path)

            if record_log:
                ShutdownLogRepo(conn).insert(snapshot_id, ShutdownOutcomeStatus.Completed)
                ShutdownCounterRepo(conn).increment()
            conn.execute("COMMIT")
            logger.info(
                "event=snapshot_committed snapshot_id=%d apps=%d chrome_profiles=%d "
                "chrome_windows=%d chrome_tabs=%d",
                snapshot_id, len(apps), len(chrome.profiles),
                chrome_windows_total, chrome_tabs_total,
            )
            # Auto-prune old snapshots in a separate transaction so a failure
            # here can never roll back the just-committed snapshot.
            try:
                with connect() as prune_conn:
                    keep_raw = SettingsRepo(prune_conn).get("SnapshotKeepCount") or "50"
                    keep = max(1, int(keep_raw))
                    deleted = SnapshotRepo(prune_conn).prune(keep)
                    if deleted:
                        logger.info(
                            "event=snapshots_pruned kept=%d deleted=%d",
                            keep, deleted,
                        )
            except Exception:  # noqa: BLE001
                logger.exception("event=snapshot_prune_failed")
            return SnapshotResult(
                snapshot_id=snapshot_id,
                desktop_count=max(1, desktop_count),
                app_count=len(apps),
                chrome_profile_count=len(chrome.profiles),
                chrome_window_count=chrome_windows_total,
                chrome_tab_count=chrome_tabs_total,
            )
    except Exception as e:  # noqa: BLE001
        logger.error("event=snapshot_failed err=%s", e)
        # Best-effort: record the failure in a *separate* transaction.
        try:
            with connect() as conn:
                ShutdownLogRepo(conn).insert(None, ShutdownOutcomeStatus.Failed)
        except Exception:  # noqa: BLE001
            logger.exception("event=snapshot_failed_log_write_failed")
        raise SnapshotError(str(e)) from e