from idle_shutdown.db.connection import connect, init_db
from idle_shutdown.enums import ShutdownOutcomeStatus, SnapshotTriggerKind


def test_enum_values_match_seed_rows(temp_db):
    init_db()
    with connect() as conn:
        triggers = {r["SnapshotTriggerKindId"]: r["KindName"] for r in conn.execute(
            "SELECT SnapshotTriggerKindId, KindName FROM SnapshotTriggerKind"
        )}
        outcomes = {r["ShutdownOutcomeStatusId"]: r["StatusName"] for r in conn.execute(
            "SELECT ShutdownOutcomeStatusId, StatusName FROM ShutdownOutcomeStatus"
        )}
    for member in SnapshotTriggerKind:
        assert triggers[int(member)] == member.name
    for member in ShutdownOutcomeStatus:
        assert outcomes[int(member)] == member.name