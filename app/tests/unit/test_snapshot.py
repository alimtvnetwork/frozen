import pytest

from idle_shutdown.capture.apps import AppInfo
from idle_shutdown.capture.chrome import ChromeSession, ChromeTabInfo, ChromeWindowInfo
from idle_shutdown.db.connection import connect, init_db
from idle_shutdown.db.repos import ShutdownCounterRepo, ShutdownLogRepo
from idle_shutdown.enums import ShutdownOutcomeStatus, SnapshotTriggerKind
from idle_shutdown.errors import SnapshotError
from idle_shutdown.snapshot import SnapshotProviders, take_snapshot


def _providers(*, desktops=2, apps=None, chrome=None, fail_in=None):
    apps = apps if apps is not None else [
        AppInfo("C:\\Apps\\code.exe", "C:\\u", None, 0),
        AppInfo("C:\\Apps\\notepad.exe", None, "C:\\u\\n.txt", 1),
    ]
    chrome = chrome if chrome is not None else ChromeSession(
        executable_path="C:\\Apps\\chrome.exe",
        windows=(ChromeWindowInfo(tabs=(
            ChromeTabInfo("https://a", "A"),
            ChromeTabInfo("https://b", "B"),
        )),),
    )

    def _desktops():
        if fail_in == "desktops":
            raise RuntimeError("boom")
        return (desktops, {1: 0, 2: 1})

    def _apps(_pid_map):
        if fail_in == "apps":
            raise RuntimeError("boom")
        return apps

    def _chrome():
        if fail_in == "chrome":
            raise RuntimeError("boom")
        return chrome

    return SnapshotProviders(
        capture_desktops_fn=_desktops,
        enumerate_apps_fn=_apps,
        capture_chrome_fn=_chrome,
    )


def test_manual_snapshot_writes_all_rows(temp_db):
    init_db()
    result = take_snapshot(SnapshotTriggerKind.Manual, _providers(), record_log=False)
    with connect() as conn:
        n_snap = conn.execute("SELECT COUNT(*) AS c FROM Snapshot").fetchone()["c"]
        n_desk = conn.execute("SELECT COUNT(*) AS c FROM VirtualDesktop").fetchone()["c"]
        n_apps = conn.execute("SELECT COUNT(*) AS c FROM AppProcess").fetchone()["c"]
        n_win = conn.execute("SELECT COUNT(*) AS c FROM ChromeWindow").fetchone()["c"]
        n_tabs = conn.execute("SELECT COUNT(*) AS c FROM ChromeTab").fetchone()["c"]
        n_log = conn.execute("SELECT COUNT(*) AS c FROM ShutdownLog").fetchone()["c"]
    assert n_snap == 1
    assert n_desk == 2 and result.desktop_count == 2
    assert n_apps == 2 and result.app_count == 2
    assert n_win == 1 and n_tabs == 2
    assert n_log == 0  # manual snapshot doesn't write a shutdown log


def test_auto_snapshot_increments_counter_and_logs_completed(temp_db):
    init_db()
    take_snapshot(SnapshotTriggerKind.Auto, _providers(), record_log=True)
    with connect() as conn:
        assert ShutdownCounterRepo(conn).total() == 1
        rows = ShutdownLogRepo(conn).recent()
    assert len(rows) == 1
    assert rows[0].outcome == "Completed"
    assert rows[0].snapshot_id is not None


def test_snapshot_failure_rolls_back_and_logs_failed(temp_db):
    init_db()
    with pytest.raises(SnapshotError):
        take_snapshot(SnapshotTriggerKind.Auto, _providers(fail_in="apps"))
    with connect() as conn:
        n_snap = conn.execute("SELECT COUNT(*) AS c FROM Snapshot").fetchone()["c"]
        rows = ShutdownLogRepo(conn).recent()
        counter = ShutdownCounterRepo(conn).total()
    assert n_snap == 0  # rolled back
    assert counter == 0
    assert len(rows) == 1 and rows[0].outcome == "Failed" and rows[0].snapshot_id is None


def test_chrome_path_cached_in_settings(temp_db):
    init_db()
    take_snapshot(SnapshotTriggerKind.Manual, _providers(), record_log=False)
    with connect() as conn:
        from idle_shutdown.db.repos import SettingsRepo
        assert SettingsRepo(conn).get("ChromeExecutablePath") == "C:\\Apps\\chrome.exe"


def test_snapshot_command(temp_db):
    from click.testing import CliRunner
    from idle_shutdown.cli import cli

    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    # Patch providers in the snapshot module so the CLI uses fakes.
    import idle_shutdown.snapshot as snap_mod
    orig = snap_mod.SnapshotProviders
    fake = _providers()
    snap_mod.SnapshotProviders = lambda: fake  # type: ignore
    try:
        result = runner.invoke(cli, ["snapshot"])
    finally:
        snap_mod.SnapshotProviders = orig  # type: ignore
    assert result.exit_code == 0, result.output
    assert "snapshot 1" in result.output
    assert "apps=2" in result.output