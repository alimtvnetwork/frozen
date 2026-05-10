"""click-based CLI. Phase 1: init-db, settings show/set, counter, history stub.

Subsequent phases extend this group; the dispatcher + error mapping below stay
stable.
"""
from __future__ import annotations

import sys
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from idle_shutdown.config import SETTING_DEFS
from idle_shutdown.db.connection import connect, init_db
from idle_shutdown.db.repos import SettingsRepo, ShutdownCounterRepo, ShutdownLogRepo
from idle_shutdown.errors import IdleShutdownError
from idle_shutdown.logging_setup import setup_logging

console = Console()
err_console = Console(stderr=True)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="DEBUG-level logging.")
@click.option("--db", "db_override", type=click.Path(), default=None,
              help="Override DB path (also IDLE_SHUTDOWN_DB).")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, db_override: Optional[str]) -> None:
    """Idle Shutdown & Session Restore."""
    if db_override:
        import os
        os.environ["IDLE_SHUTDOWN_DB"] = db_override
    setup_logging(verbose=verbose)
    ctx.ensure_object(dict)


# ----- init-db ---------------------------------------------------------------


@cli.command("init-db")
def cmd_init_db() -> None:
    """Create the DB file, apply schema, seed defaults."""
    path = init_db()
    click.echo(f"Initialized database at {path}")


# ----- settings --------------------------------------------------------------


@cli.group("settings")
def cmd_settings() -> None:
    """View and edit configuration."""


@cmd_settings.command("show")
def cmd_settings_show() -> None:
    with connect() as conn:
        repo = SettingsRepo(conn)
        rows = repo.all()
    table = Table(title="Settings")
    table.add_column("Key")
    table.add_column("Value")
    table.add_column("UpdatedAt (UTC)")
    known = {s.key for s in SETTING_DEFS}
    seen = set()
    for r in rows:
        seen.add(r.key)
        table.add_row(r.key, r.value, r.updated_at)
    # Surface missing keys (shouldn't happen post-init) as a hint
    for missing in sorted(known - seen):
        table.add_row(missing, "<missing>", "")
    console.print(table)


@cmd_settings.command("set-idle")
@click.argument("minutes", type=int)
def cmd_settings_set_idle(minutes: int) -> None:
    with connect() as conn:
        SettingsRepo(conn).set("IdleThresholdMinutes", minutes)
    click.echo(f"IdleThresholdMinutes = {minutes}")


@cmd_settings.command("set-countdown")
@click.argument("seconds", type=int)
def cmd_settings_set_countdown(seconds: int) -> None:
    with connect() as conn:
        SettingsRepo(conn).set("PopupCountdownSeconds", seconds)
    click.echo(f"PopupCountdownSeconds = {seconds}")


# ----- counter ---------------------------------------------------------------


@cli.command("counter")
def cmd_counter() -> None:
    with connect() as conn:
        click.echo(str(ShutdownCounterRepo(conn).total()))


# ----- history ---------------------------------------------------------------


@cli.command("history")
@click.option("--limit", type=click.IntRange(1, 1000), default=20)
def cmd_history(limit: int) -> None:
    with connect() as conn:
        rows = ShutdownLogRepo(conn).recent(limit=limit)
    table = Table(title="Shutdown history")
    table.add_column("OccurredAt (UTC)")
    table.add_column("Outcome")
    table.add_column("SnapshotId")
    for r in rows:
        table.add_row(r.occurred_at, r.outcome, "" if r.snapshot_id is None else str(r.snapshot_id))
    console.print(table)


# ----- placeholders for later phases ----------------------------------------


@cli.command("run")
@click.option("--silent", is_flag=True, help="Suppress console window (Phase 2).")
def cmd_run(silent: bool) -> None:  # noqa: ARG001
    """Foreground service: idle monitor + popup loop."""
    from idle_shutdown.monitor import IdleMonitor, get_default_idle_source
    from idle_shutdown.popup import show_popup
    from idle_shutdown.service import IdleService, ServiceCallbacks

    def _settings_provider(key: str):
        with connect() as conn:
            return SettingsRepo(conn).get(key)

    def _take_snapshot_and_shutdown() -> None:
        # Phase 3/4 will wire the real implementation; for now log + exit popup.
        click.echo("snapshot+shutdown wiring lands in Phase 3/4")

    callbacks = ServiceCallbacks(
        show_popup=show_popup,
        take_snapshot_and_shutdown=_take_snapshot_and_shutdown,
        get_idle_threshold_minutes=lambda: int(_settings_provider("IdleThresholdMinutes")),
        get_popup_countdown_seconds=lambda: int(_settings_provider("PopupCountdownSeconds")),
        get_service_enabled=lambda: _settings_provider("ServiceState") == "Enabled",
    )
    service = IdleService(callbacks)
    monitor = IdleMonitor(
        source=get_default_idle_source(),
        threshold_ms_provider=service.threshold_ms,
        on_threshold=service.on_threshold_reached,
        on_activity=service.on_activity_during_prompt,
    )
    click.echo("idle monitor running (Ctrl+C to stop)")
    monitor.run_forever()


@cli.command("snapshot")
def cmd_snapshot() -> None:
    """Capture a session snapshot now (TriggerKind = Manual). Does NOT shut down."""
    from idle_shutdown.enums import SnapshotTriggerKind
    from idle_shutdown.snapshot import take_snapshot

    result = take_snapshot(SnapshotTriggerKind.Manual, record_log=False)
    click.echo(
        f"snapshot {result.snapshot_id}: desktops={result.desktop_count} "
        f"apps={result.app_count} chrome_windows={result.chrome_window_count} "
        f"chrome_tabs={result.chrome_tab_count}"
    )


@cli.command("restore")
@click.option("--snapshot-id", type=int, default=None)
def cmd_restore(snapshot_id: Optional[int]) -> None:  # noqa: ARG001
    raise click.ClickException("restore: implemented in Phase 4")


@cli.command("install-autostart")
def cmd_install_autostart() -> None:
    raise click.ClickException("install-autostart: implemented in Phase 4")


@cli.command("uninstall-autostart")
def cmd_uninstall_autostart() -> None:
    raise click.ClickException("uninstall-autostart: implemented in Phase 4")


@cli.command("disable")
@click.option("--minutes", type=click.IntRange(1, 1440), default=None)
def cmd_disable(minutes: Optional[int]) -> None:
    from idle_shutdown.db.connection import utc_now_iso
    from datetime import datetime, timedelta, timezone
    with connect() as conn:
        repo = SettingsRepo(conn)
        repo.set("ServiceState", "Disabled")
        if minutes is not None:
            until = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            repo.set("DisabledUntil", until)
        else:
            repo.set("DisabledUntil", "")
    _ = utc_now_iso  # keep import side-effect free
    click.echo("Service disabled")


@cli.command("enable")
def cmd_enable() -> None:
    with connect() as conn:
        repo = SettingsRepo(conn)
        repo.set("ServiceState", "Enabled")
        repo.set("DisabledUntil", "")
    click.echo("Service enabled")


# ----- entrypoint with exit-code mapping ------------------------------------


def main(argv: Optional[list[str]] = None) -> None:
    try:
        cli.main(args=argv, standalone_mode=False)
    except click.exceptions.UsageError as e:
        e.show()
        sys.exit(e.exit_code or 2)
    except click.exceptions.ClickException as e:
        e.show()
        sys.exit(e.exit_code)
    except IdleShutdownError as e:
        err_console.print(f"[red]error:[/red] {e.message}")
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()