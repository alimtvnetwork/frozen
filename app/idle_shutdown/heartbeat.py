"""Crash-safe background snapshot + clean-shutdown marker.

Phase A/B of the unexpected-shutdown plan. Designed to be cheap enough to
invoke from the 1 Hz monitor tick: it only does real work every N minutes
(``BackgroundSnapshotIntervalMinutes``) and otherwise returns immediately.

Keeps two pieces of persistent state in the ``Setting`` table:

* ``CleanShutdown`` — set to ``"false"`` when the service starts, flipped
  back to ``"true"`` only on a graceful exit. If next boot reads ``"false"``
  we know the previous run was killed (power loss, OS crash, kernel panic).
* ``LastHeartbeatAt`` — ISO-8601 UTC of the last successful tick. Used by
  the recovery dialog to tell the user how long ago the snapshot is.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from idle_shutdown.db.connection import connect, utc_now_iso
from idle_shutdown.db.repos import SettingsRepo, SnapshotRepo
from idle_shutdown.enums import SnapshotTriggerKind

logger = logging.getLogger(__name__)

_HEARTBEAT_WRITE_INTERVAL_S = 30.0


class HeartbeatScheduler:
    """Drives periodic background snapshots from the monitor tick.

    Call :meth:`tick` once per monitor tick; pass ``busy=True`` when the
    activity guard says the user is in a call / movie / etc. — heartbeat
    timestamps still update, but the snapshot is skipped (the previous one
    is still on disk and ≤ N minutes old).
    """

    def __init__(
        self,
        take_snapshot: Callable[[SnapshotTriggerKind], object],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._take_snapshot = take_snapshot
        self._clock = clock
        self._last_snapshot_at: float | None = None
        self._last_heartbeat_write: float = 0.0

    # ----- lifecycle -------------------------------------------------------

    def mark_started(self) -> None:
        """Mark the service as live. Call once on startup, before tick()."""
        try:
            with connect() as conn:
                repo = SettingsRepo(conn)
                repo.set("CleanShutdown", "false")
                repo.set("LastHeartbeatAt", utc_now_iso())
        except Exception:  # noqa: BLE001
            logger.exception("event=heartbeat_mark_started_failed")

    def mark_clean_exit(self) -> None:
        """Flip CleanShutdown=true. Call from graceful shutdown paths."""
        try:
            with connect() as conn:
                SettingsRepo(conn).set("CleanShutdown", "true")
        except Exception:  # noqa: BLE001
            logger.exception("event=heartbeat_mark_clean_exit_failed")

    # ----- per-tick --------------------------------------------------------

    def tick(self, busy: bool) -> None:
        now = self._clock()
        # Cheap heartbeat write every ~30 s, regardless of busy state.
        if now - self._last_heartbeat_write >= _HEARTBEAT_WRITE_INTERVAL_S:
            self._last_heartbeat_write = now
            try:
                with connect() as conn:
                    SettingsRepo(conn).set("LastHeartbeatAt", utc_now_iso())
            except Exception:  # noqa: BLE001
                logger.exception("event=heartbeat_write_failed")

        # Background snapshot cadence.
        try:
            with connect() as conn:
                repo = SettingsRepo(conn)
                enabled = str(repo.get("BackgroundSnapshotsEnabled")).lower() == "true"
                interval_min = int(repo.get("BackgroundSnapshotIntervalMinutes"))
                retention_days = int(repo.get("BackgroundSnapshotRetentionDays"))
        except Exception:  # noqa: BLE001
            return
        if not enabled:
            return
        if busy:
            return  # keep the older snapshot; don't capture during call/movie
        interval_s = max(60, interval_min * 60)
        if self._last_snapshot_at is not None and (now - self._last_snapshot_at) < interval_s:
            return
        self._last_snapshot_at = now
        try:
            res = self._take_snapshot(SnapshotTriggerKind.Background)
            logger.info(
                "event=background_snapshot snapshot_id=%s",
                getattr(res, "snapshot_id", "?"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("event=background_snapshot_failed")
            return
        # Phase D: prune old Background snapshots.
        try:
            with connect() as conn:
                deleted = SnapshotRepo(conn).prune_background_older_than(retention_days)
                if deleted:
                    logger.info(
                        "event=background_snapshots_pruned deleted=%d retention_days=%d",
                        deleted, retention_days,
                    )
        except Exception:  # noqa: BLE001
            logger.exception("event=background_snapshot_prune_failed")


# ----- crash recovery query -------------------------------------------------


def detect_crash_recovery_candidate() -> tuple[bool, int | None, str | None]:
    """Return ``(is_crash, snapshot_id, last_heartbeat_iso)``.

    ``is_crash`` is True when the previous run did not flip ``CleanShutdown``
    back to ``"true"`` AND there is at least one snapshot on disk that
    hasn't been restored yet.
    """
    try:
        with connect() as conn:
            repo = SettingsRepo(conn)
            clean = str(repo.get("CleanShutdown")).lower() == "true"
            last_hb = str(repo.get("LastHeartbeatAt") or "")
            last_restored = int(repo.get("LastRestoredSnapshotId") or 0)
            latest = SnapshotRepo(conn).latest_id()
    except Exception:  # noqa: BLE001
        logger.exception("event=crash_recovery_detect_failed")
        return (False, None, None)
    if clean:
        return (False, latest, last_hb or None)
    if latest is None or latest <= last_restored:
        return (False, latest, last_hb or None)
    return (True, latest, last_hb or None)