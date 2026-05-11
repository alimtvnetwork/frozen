from click.testing import CliRunner

from idle_shutdown.db.connection import connect, init_db
from idle_shutdown.db.repos import SettingsRepo, SnapshotRepo
from idle_shutdown.enums import SnapshotTriggerKind
from idle_shutdown.snapshot import take_snapshot

from .test_snapshot import _providers


def _count_snapshots() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM Snapshot").fetchone()["c"]


def test_prune_keeps_newest_n(temp_db):
    init_db()
    with connect() as conn:
        repo = SnapshotRepo(conn)
        ids = [repo.insert(SnapshotTriggerKind.Manual) for _ in range(5)]
        deleted = repo.prune(2)
        conn.commit()
    assert deleted == 3
    with connect() as conn:
        rows = conn.execute("SELECT SnapshotId FROM Snapshot ORDER BY SnapshotId").fetchall()
    kept = [r["SnapshotId"] for r in rows]
    assert kept == ids[-2:]


def test_prune_cascades_to_children(temp_db):
    init_db()
    # Create 3 snapshots with full child rows.
    for _ in range(3):
        take_snapshot(SnapshotTriggerKind.Manual, _providers(), record_log=False)
    with connect() as conn:
        deleted = SnapshotRepo(conn).prune(1)
        conn.commit()
    assert deleted == 2
    with connect() as conn:
        n_snap = conn.execute("SELECT COUNT(*) AS c FROM Snapshot").fetchone()["c"]
        n_apps = conn.execute("SELECT COUNT(*) AS c FROM AppProcess").fetchone()["c"]
        n_tabs = conn.execute("SELECT COUNT(*) AS c FROM ChromeTab").fetchone()["c"]
        n_prof = conn.execute("SELECT COUNT(*) AS c FROM ChromeProfile").fetchone()["c"]
    assert n_snap == 1
    # Each providers() builds 2 apps + 2 tabs + 1 profile per snapshot.
    assert n_apps == 2 and n_tabs == 2 and n_prof == 1


def test_take_snapshot_auto_prunes(temp_db):
    init_db()
    with connect() as conn:
        SettingsRepo(conn).set("SnapshotKeepCount", "2")
    for _ in range(4):
        take_snapshot(SnapshotTriggerKind.Manual, _providers(), record_log=False)
    assert _count_snapshots() == 2


def test_prune_cli(temp_db):
    from idle_shutdown.cli import cli

    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    with connect() as conn:
        repo = SnapshotRepo(conn)
        for _ in range(4):
            repo.insert(SnapshotTriggerKind.Manual)
        conn.commit()
    res = runner.invoke(cli, ["prune", "--keep", "1"])
    assert res.exit_code == 0, res.output
    assert "pruned 3" in res.output
    assert _count_snapshots() == 1