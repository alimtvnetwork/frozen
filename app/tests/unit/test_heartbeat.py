from idle_shutdown.db.connection import connect, init_db
from idle_shutdown.db.repos import SettingsRepo, SnapshotRepo
from idle_shutdown.enums import SnapshotTriggerKind
from idle_shutdown.heartbeat import (
    HeartbeatScheduler,
    detect_crash_recovery_candidate,
)


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_heartbeat_marks_started_and_clean_exit(temp_db):
    init_db()
    hb = HeartbeatScheduler(take_snapshot=lambda _t: None)
    hb.mark_started()
    with connect() as conn:
        assert SettingsRepo(conn).get("CleanShutdown") is False
    hb.mark_clean_exit()
    with connect() as conn:
        assert SettingsRepo(conn).get("CleanShutdown") is True


def test_background_snapshot_fires_on_interval_and_skips_when_busy(temp_db):
    init_db()
    with connect() as conn:
        SettingsRepo(conn).set("BackgroundSnapshotIntervalMinutes", 1)
    calls: list[SnapshotTriggerKind] = []

    def _take(trigger):
        calls.append(trigger)

        class _R:
            snapshot_id = 0

        return _R()

    clk = _Clock()
    hb = HeartbeatScheduler(take_snapshot=_take, clock=clk)
    hb.tick(busy=False)
    assert len(calls) == 1
    # Within interval: nothing.
    clk.advance(30)
    hb.tick(busy=False)
    assert len(calls) == 1
    # After interval but busy: still skipped.
    clk.advance(60)
    hb.tick(busy=True)
    assert len(calls) == 1
    # After interval, idle: fires again.
    clk.advance(60)
    hb.tick(busy=False)
    assert len(calls) == 2
    assert all(t == SnapshotTriggerKind.Background for t in calls)


def test_crash_recovery_detected_when_clean_shutdown_false(temp_db):
    init_db()
    with connect() as conn:
        SnapshotRepo(conn).insert(SnapshotTriggerKind.Background)
        SettingsRepo(conn).set("CleanShutdown", "false")
    is_crash, snap_id, _ = detect_crash_recovery_candidate()
    assert is_crash is True
    assert snap_id is not None


def test_crash_recovery_not_flagged_after_clean_exit(temp_db):
    init_db()
    with connect() as conn:
        SnapshotRepo(conn).insert(SnapshotTriggerKind.Background)
        SettingsRepo(conn).set("CleanShutdown", "true")
    is_crash, _, _ = detect_crash_recovery_candidate()
    assert is_crash is False


def test_crash_recovery_skipped_when_already_restored(temp_db):
    init_db()
    with connect() as conn:
        sid = SnapshotRepo(conn).insert(SnapshotTriggerKind.Background)
        SettingsRepo(conn).set("CleanShutdown", "false")
        SettingsRepo(conn).set("LastRestoredSnapshotId", sid)
    is_crash, _, _ = detect_crash_recovery_candidate()
    assert is_crash is False


def test_prune_background_older_than_only_touches_background(temp_db):
    init_db()
    with connect() as conn:
        repo = SnapshotRepo(conn)
        bg_old = repo.insert(SnapshotTriggerKind.Background)
        manual = repo.insert(SnapshotTriggerKind.Manual)
        # Backdate the background snapshot 30 days.
        conn.execute(
            "UPDATE Snapshot SET CreatedAt = datetime('now', '-30 days') "
            "WHERE SnapshotId = ?",
            (bg_old,),
        )
        bg_recent = repo.insert(SnapshotTriggerKind.Background)
        deleted = repo.prune_background_older_than(7)
    assert deleted == 1
    with connect() as conn:
        ids = {r["SnapshotId"] for r in conn.execute(
            "SELECT SnapshotId FROM Snapshot"
        ).fetchall()}
    assert bg_old not in ids
    assert manual in ids and bg_recent in ids


def test_snapshot_failure_notification_fires_after_threshold(temp_db):
    init_db()
    with connect() as conn:
        SettingsRepo(conn).set("BackgroundSnapshotIntervalMinutes", 1)
        SettingsRepo(conn).set("SnapshotFailureNotifyThreshold", 2)

    def _boom(_t):
        raise RuntimeError("snapshot exploded")

    notes: list[tuple[str, str]] = []
    clk = _Clock()
    hb = HeartbeatScheduler(
        take_snapshot=_boom, clock=clk,
        notifier=lambda t, m: notes.append((t, m)),
    )
    hb.tick(busy=False)  # failure 1
    assert notes == []
    clk.advance(120)
    hb.tick(busy=False)  # failure 2 -> notify
    assert len(notes) == 1
    # No re-notification on the same streak.
    clk.advance(120)
    hb.tick(busy=False)
    assert len(notes) == 1
    with connect() as conn:
        assert int(SettingsRepo(conn).get("ConsecutiveSnapshotFailures")) == 3


def test_snapshot_failure_counter_resets_on_success(temp_db):
    init_db()
    with connect() as conn:
        SettingsRepo(conn).set("BackgroundSnapshotIntervalMinutes", 1)
        SettingsRepo(conn).set("ConsecutiveSnapshotFailures", 5)

    class _R:
        snapshot_id = 99

    clk = _Clock()
    hb = HeartbeatScheduler(take_snapshot=lambda _t: _R(), clock=clk)
    hb.tick(busy=False)
    with connect() as conn:
        assert int(SettingsRepo(conn).get("ConsecutiveSnapshotFailures")) == 0