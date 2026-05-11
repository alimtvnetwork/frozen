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
from idle_shutdown.db.repos import (
    SettingsRepo, ShutdownCounterRepo, ShutdownLogRepo, SnapshotReadRepo,
    SnapshotRepo,
)
from idle_shutdown.errors import IdleShutdownError
from idle_shutdown.logging_setup import setup_logging

console = Console()
err_console = Console(stderr=True)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="DEBUG-level logging.")
@click.option("--log-json", "log_json", is_flag=True,
              help="Emit logs as one JSON object per line (overrides IDLE_SHUTDOWN_LOG_JSON).")
@click.option("--db", "db_override", type=click.Path(), default=None,
              help="Override DB path (also IDLE_SHUTDOWN_DB).")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, log_json: bool,
        db_override: Optional[str]) -> None:
    """Idle Shutdown & Session Restore."""
    if db_override:
        import os
        os.environ["IDLE_SHUTDOWN_DB"] = db_override
    setup_logging(verbose=verbose, json_format=True if log_json else None)
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


# ----- show ------------------------------------------------------------------


@cli.command("show")
@click.option("--snapshot-id", type=int, default=None,
              help="Inspect a specific snapshot. Defaults to the latest.")
@click.option("--json", "as_json", is_flag=True,
              help="Emit the snapshot detail as JSON for piping.")
@click.option("--max-tabs", type=click.IntRange(1, 10000), default=200,
              help="Truncate the tab table to this many rows in human view.")
def cmd_show(snapshot_id: Optional[int], as_json: bool, max_tabs: int) -> None:
    """Print a saved snapshot: apps, Chrome profiles, windows, tabs."""
    import json as _json
    with connect() as conn:
        repo = SnapshotReadRepo(conn)
        sid = snapshot_id if snapshot_id is not None else repo.latest_id()
        if sid is None:
            click.echo("no snapshots found", err=True)
            sys.exit(1)
        detail = repo.get_detail(sid)
    if detail is None:
        click.echo(f"snapshot {sid} not found", err=True)
        sys.exit(1)

    if as_json:
        click.echo(_json.dumps({
            "snapshot_id": detail.snapshot_id,
            "created_at": detail.created_at,
            "trigger": detail.trigger,
            "desktop_count": detail.desktop_count,
            "apps": [a.__dict__ for a in detail.apps],
            "profiles": [
                {"profile_dir": d, "profile_name": n,
                 "tab_count": c, "browser_name": b}
                for d, n, c, b in detail.profile_summary
            ],
            "tabs": [t.__dict__ for t in detail.tabs],
        }, indent=2))
        return

    console.print(
        f"[bold]Snapshot #{detail.snapshot_id}[/bold]  "
        f"trigger={detail.trigger}  created={detail.created_at}  "
        f"desktops={detail.desktop_count}  apps={len(detail.apps)}  "
        f"profiles={len(detail.profile_summary)}  tabs={len(detail.tabs)}"
    )

    apps_table = Table(title="Applications", show_lines=False)
    apps_table.add_column("Desktop", justify="right")
    apps_table.add_column("Executable", overflow="fold")
    apps_table.add_column("CWD", overflow="fold")
    apps_table.add_column("Document", overflow="fold")
    for a in detail.apps:
        apps_table.add_row(
            str(a.desktop_index), a.executable_path,
            a.working_directory or "", a.document_path or "",
        )
    console.print(apps_table)

    if detail.profile_summary:
        prof_table = Table(title="Chrome profiles")
        prof_table.add_column("Browser")
        prof_table.add_column("ProfileDir")
        prof_table.add_column("Name")
        prof_table.add_column("Tabs", justify="right")
        for d, n, c, b in detail.profile_summary:
            prof_table.add_row(b, d, n, str(c))
        console.print(prof_table)

    if detail.tabs:
        tabs_table = Table(title=f"Tabs (showing first {min(max_tabs, len(detail.tabs))} of {len(detail.tabs)})")
        tabs_table.add_column("Browser")
        tabs_table.add_column("Profile")
        tabs_table.add_column("Win", justify="right")
        tabs_table.add_column("Idx", justify="right")
        tabs_table.add_column("Title", overflow="fold", max_width=40)
        tabs_table.add_column("URL", overflow="fold", max_width=70)
        for t in detail.tabs[:max_tabs]:
            tabs_table.add_row(
                t.browser_name or "-",
                t.profile_name or t.profile_dir or "-",
                str(t.window_index), str(t.tab_index),
                t.title, t.url,
            )
        console.print(tabs_table)


# ----- placeholders for later phases ----------------------------------------


@cli.command("run")
@click.option("--silent", is_flag=True, help="Suppress console window (Phase 2).")
@click.option("--dry-run/--no-dry-run", "dry_run_flag", default=None,
              help="Override DryRun setting for this run. In dry-run mode the "
                   "snapshot is taken and an info popup is shown, but the OS "
                   "shutdown command is never invoked.")
def cmd_run(silent: bool, dry_run_flag: Optional[bool]) -> None:  # noqa: ARG001
    """Foreground service: idle monitor + popup loop."""
    from idle_shutdown.monitor import IdleMonitor, get_default_idle_source
    from idle_shutdown.popup import show_info_popup, show_popup
    from idle_shutdown.service import IdleService, ServiceCallbacks
    from idle_shutdown.shutdown import execute_shutdown
    from idle_shutdown.snapshot import take_snapshot
    from idle_shutdown.enums import SnapshotTriggerKind
    from idle_shutdown.single_instance import acquire_single_instance
    from idle_shutdown.activity_guard import ActivityGuard, GuardConfig

    def _settings_provider(key: str):
        with connect() as conn:
            return SettingsRepo(conn).get(key)

    def _is_dry_run() -> bool:
        if dry_run_flag is not None:
            return dry_run_flag
        return str(_settings_provider("DryRun")).lower() == "true"

    def _take_snapshot_and_shutdown() -> None:
        try:
            res = take_snapshot(SnapshotTriggerKind.Auto, record_log=True)
        except Exception as e:  # noqa: BLE001
            click.echo(f"snapshot failed: {e}", err=True)
            return
        if _is_dry_run():
            msg = (
                f"DRY RUN — your system would shut down now.\n\n"
                f"Snapshot #{res.snapshot_id} saved to the database:\n"
                f"  • {res.app_count} application(s)\n"
                f"  • {res.chrome_profile_count} Chrome profile(s), "
                f"{res.chrome_window_count} window(s), "
                f"{res.chrome_tab_count} tab(s)\n"
                f"  • {res.desktop_count} virtual desktop(s)\n\n"
                f"Nothing was closed. Click OK to dismiss."
            )
            click.echo(f"dry-run: would shut down (snapshot {res.snapshot_id})")
            try:
                show_info_popup("Idle Shutdown — Dry Run", msg)
            except Exception as e:  # noqa: BLE001
                click.echo(f"dry-run popup failed: {e}", err=True)
            return
        execute_shutdown()

    callbacks = ServiceCallbacks(
        show_popup=show_popup,
        take_snapshot_and_shutdown=_take_snapshot_and_shutdown,
        get_idle_threshold_minutes=lambda: int(_settings_provider("IdleThresholdMinutes")),
        get_popup_countdown_seconds=lambda: int(_settings_provider("PopupCountdownSeconds")),
        get_service_enabled=lambda: _settings_provider("ServiceState") == "Enabled",
    )
    service = IdleService(callbacks)
    def _guard_cfg() -> GuardConfig:
        return GuardConfig(
            mic_enabled=str(_settings_provider("GuardMicEnabled")).lower() == "true",
            audio_enabled=str(_settings_provider("GuardAudioEnabled")).lower() == "true",
            fullscreen_enabled=str(_settings_provider("GuardFullscreenEnabled")).lower() == "true",
        )
    guard = ActivityGuard(_guard_cfg)
    monitor = IdleMonitor(
        source=get_default_idle_source(),
        threshold_ms_provider=service.threshold_ms,
        on_threshold=service.on_threshold_reached,
        on_activity=service.on_activity_during_prompt,
        is_busy=guard.is_busy,
    )
    with acquire_single_instance():
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
        f"apps={result.app_count} chrome_profiles={result.chrome_profile_count} "
        f"chrome_windows={result.chrome_window_count} "
        f"chrome_tabs={result.chrome_tab_count}"
    )


@cli.command("simulate")
@click.option("--countdown", type=click.IntRange(1, 120), default=5,
              help="Override popup countdown seconds for this run.")
@click.option("--no-popup", is_flag=True,
              help="Skip the GUI popup (useful in headless CI).")
@click.option("--force", is_flag=True,
              help="Actually run the OS shutdown command (otherwise dry-run).")
def cmd_simulate(countdown: int, no_popup: bool, force: bool) -> None:
    """Pretend the user just went idle: show the popup, run the countdown,
    then take a snapshot and invoke the shutdown step (dry-run by default
    on macOS/Linux). Use this to test the full workflow without waiting."""
    import os as _os
    from idle_shutdown.popup import show_popup
    from idle_shutdown.service import IdleService, ServiceCallbacks
    from idle_shutdown.snapshot import take_snapshot
    from idle_shutdown.shutdown import execute_shutdown
    from idle_shutdown.enums import SnapshotTriggerKind

    if force:
        _os.environ["IDLE_SHUTDOWN_FORCE"] = "1"
        _os.environ.pop("IDLE_SHUTDOWN_DRY_RUN", None)

    def _take_snapshot_and_shutdown() -> None:
        try:
            res = take_snapshot(SnapshotTriggerKind.Auto, record_log=True)
            click.echo(
                f"simulated snapshot {res.snapshot_id}: apps={res.app_count} "
                f"chrome_tabs={res.chrome_tab_count}"
            )
        except Exception as e:  # noqa: BLE001
            click.echo(f"snapshot failed: {e}", err=True)
            return
        rc = execute_shutdown()
        click.echo(f"shutdown step rc={rc}")

    def _popup(secs, on_result):
        if no_popup:
            from idle_shutdown.enums import PopupResult
            click.echo(f"(no-popup) auto-timeout in {secs}s")
            import time as _t
            _t.sleep(secs)
            on_result(PopupResult.Timeout)
        else:
            show_popup(secs, on_result)

    callbacks = ServiceCallbacks(
        show_popup=_popup,
        take_snapshot_and_shutdown=_take_snapshot_and_shutdown,
        get_idle_threshold_minutes=lambda: 1,
        get_popup_countdown_seconds=lambda: countdown,
        get_service_enabled=lambda: True,
    )
    click.echo("simulating idle threshold reached…")
    IdleService(callbacks).on_threshold_reached()


@cli.command("restore")
@click.option("--snapshot-id", type=int, default=None)
def cmd_restore(snapshot_id: Optional[int]) -> None:
    """Restore the latest (or given) snapshot."""
    from idle_shutdown.restore import restore
    from idle_shutdown.single_instance import acquire_single_instance

    with acquire_single_instance():
        result = restore(snapshot_id)
    click.echo(
        f"restored snapshot {result.snapshot_id}: "
        f"launched={result.apps_launched} skipped={result.apps_skipped} "
        f"chrome={'yes' if result.chrome_launched else 'no'}"
    )


@cli.command("install-autostart")
def cmd_install_autostart() -> None:
    """Write the HKCU Run entry so the service starts on login."""
    from idle_shutdown.autostart import default_executable_path, install_autostart
    cmd = install_autostart(default_executable_path())
    click.echo(f"autostart installed: {cmd}")


@cli.command("uninstall-autostart")
def cmd_uninstall_autostart() -> None:
    """Remove the HKCU Run entry."""
    from idle_shutdown.autostart import uninstall_autostart
    uninstall_autostart()
    click.echo("autostart uninstalled")


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


@cli.command("prune")
@click.option("--keep", type=click.IntRange(1, 10000), default=None,
              help="Override SnapshotKeepCount for this run.")
def cmd_prune(keep: Optional[int]) -> None:
    """Delete old snapshots, keeping only the most recent N."""
    with connect() as conn:
        if keep is None:
            raw = SettingsRepo(conn).get("SnapshotKeepCount") or "50"
            keep = int(raw)
        deleted = SnapshotRepo(conn).prune(keep)
        conn.commit()
    click.echo(f"pruned {deleted} snapshot(s); kept newest {keep}")


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