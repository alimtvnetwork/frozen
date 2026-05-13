from idle_shutdown.config import SETTING_DEFS
from idle_shutdown.db.connection import connect, init_db


def _all_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return {r["name"] for r in rows}


def test_init_db_creates_all_tables(temp_db):
    init_db()
    with connect() as conn:
        names = _all_tables(conn)
    expected = {
        "SnapshotTriggerKind", "ShutdownOutcomeStatus", "Setting", "Snapshot",
        "VirtualDesktop", "AppProcess", "ChromeWindow", "ChromeTab",
        "ShutdownLog", "ShutdownCounter",
    }
    assert expected.issubset(names)


def test_init_db_seeds_lookups(temp_db):
    init_db()
    with connect() as conn:
        triggers = conn.execute("SELECT KindName FROM SnapshotTriggerKind ORDER BY SnapshotTriggerKindId").fetchall()
        outcomes = conn.execute("SELECT StatusName FROM ShutdownOutcomeStatus ORDER BY ShutdownOutcomeStatusId").fetchall()
        counter = conn.execute("SELECT TotalCount FROM ShutdownCounter").fetchone()
    assert [r["KindName"] for r in triggers] == [
        "Auto", "Manual", "Scheduled", "Background",
    ]
    assert [r["StatusName"] for r in outcomes] == ["Completed", "Cancelled", "Failed"]
    assert counter["TotalCount"] == 0


def test_init_db_seeds_default_settings(temp_db):
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT KeyName, Value FROM Setting").fetchall()
    seen = {r["KeyName"]: r["Value"] for r in rows}
    for s in SETTING_DEFS:
        assert seen.get(s.key) == s.default, s.key


def test_init_db_idempotent(temp_db):
    init_db()
    init_db()
    with connect() as conn:
        n_settings = conn.execute("SELECT COUNT(*) AS c FROM Setting").fetchone()["c"]
        n_counter = conn.execute("SELECT COUNT(*) AS c FROM ShutdownCounter").fetchone()["c"]
    assert n_settings == len(SETTING_DEFS)
    assert n_counter == 1