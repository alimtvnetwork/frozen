from click.testing import CliRunner

from idle_shutdown.cli import cli
from idle_shutdown.db.connection import connect, init_db
from idle_shutdown.db.repos import ShutdownCounterRepo, ShutdownLogRepo
from idle_shutdown.enums import ShutdownOutcomeStatus


def test_init_db_command(temp_db):
    runner = CliRunner()
    result = runner.invoke(cli, ["init-db"])
    assert result.exit_code == 0, result.output
    assert "Initialized database" in result.output


def test_settings_show_lists_all_keys(temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    result = runner.invoke(cli, ["settings", "show"])
    assert result.exit_code == 0, result.output
    for key in (
        "IdleThresholdMinutes", "PopupCountdownSeconds", "ServiceState",
        "AutoRestoreOnBoot", "ChromeExecutablePath",
        "LastRestoredSnapshotId", "LastRestoredAt", "DisabledUntil",
    ):
        assert key in result.output


def test_settings_set_idle_rejects_zero(temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    result = runner.invoke(cli, ["settings", "set-idle", "0"])
    assert result.exit_code != 0


def test_settings_set_idle_accepts_valid(temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    result = runner.invoke(cli, ["settings", "set-idle", "15"])
    assert result.exit_code == 0, result.output


def test_counter_prints_total(temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    with connect() as conn:
        ShutdownCounterRepo(conn).increment()
    result = runner.invoke(cli, ["counter"])
    assert result.exit_code == 0
    assert result.output.strip() == "1"


def test_history_renders_table(temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    with connect() as conn:
        ShutdownLogRepo(conn).insert(None, ShutdownOutcomeStatus.Failed)
    result = runner.invoke(cli, ["history"])
    assert result.exit_code == 0
    assert "OccurredAt" in result.output
    assert "Failed" in result.output


def test_disable_then_enable(temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    r1 = runner.invoke(cli, ["disable", "--minutes", "5"])
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(cli, ["enable"])
    assert r2.exit_code == 0, r2.output