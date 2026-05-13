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


@cli.command("gui")
def cmd_gui() -> None:
    """Launch the desktop UI (sidebar window with Settings, Snapshots, Status)."""
    from idle_shutdown.gui import launch_gui
    launch_gui()


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


# ----- status ----------------------------------------------------------------


@cli.command("status")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a table.")
def cmd_status(as_json: bool) -> None:
    """Concise live health check: service state, idle, snapshots, crash flag."""
    import json as _json
    from datetime import datetime, timezone
    from idle_shutdown.heartbeat import detect_crash_recovery_candidate

    def _age(iso: str | None) -> str:
        if not iso:
            return "never"
        try:
            ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            s = int((datetime.now(timezone.utc) - ts).total_seconds())
            if s < 60:
                return f"{s}s ago"
            if s < 3600:
                return f"{s // 60}m ago"
            if s < 86400:
                return f"{s // 3600}h ago"
            return f"{s // 86400}d ago"
        except Exception:  # noqa: BLE001
            return str(iso)

    with connect() as conn:
        s = SettingsRepo(conn)
        settings = {k: s.get(k) for k in (
            "ServiceState", "DryRun", "IdleThresholdMinutes",
            "PopupCountdownSeconds", "SnoozeMinutes",
            "BackgroundSnapshotsEnabled", "BackgroundSnapshotIntervalMinutes",
            "DisabledUntil", "LastHeartbeatAt", "CleanShutdown",
            "LastRestoredSnapshotId", "LastRestoredAt",
        )}
        snap_row = conn.execute(
            "SELECT SnapshotId, CreatedAt, TriggerKindId FROM Snapshot "
            "ORDER BY SnapshotId DESC LIMIT 1"
        ).fetchone()
        snap_total = conn.execute(
            "SELECT COUNT(*) AS n FROM Snapshot"
        ).fetchone()["n"]

    is_crash, recover_id, recover_hb = detect_crash_recovery_candidate()

    # Idle source (best-effort; some platforms not wired in this env).
    idle_seconds: int | None
    try:
        from idle_shutdown.platform import get_default_idle_source
        idle_seconds = int(get_default_idle_source().get_idle_ms() / 1000)
    except Exception:  # noqa: BLE001
        idle_seconds = None

    payload = {
        "service_state": settings["ServiceState"],
        "dry_run": str(settings["DryRun"]).lower() == "true",
        "idle_seconds": idle_seconds,
        "idle_threshold_minutes": int(settings["IdleThresholdMinutes"]),
        "popup_countdown_seconds": int(settings["PopupCountdownSeconds"]),
        "snooze_minutes": int(settings["SnoozeMinutes"]),
        "snooze_until": settings["DisabledUntil"] or None,
        "background_snapshots": {
            "enabled": str(settings["BackgroundSnapshotsEnabled"]).lower() == "true",
            "interval_minutes": int(settings["BackgroundSnapshotIntervalMinutes"]),
            "last_heartbeat": settings["LastHeartbeatAt"] or None,
            "last_heartbeat_age": _age(settings["LastHeartbeatAt"] or None),
        },
        "snapshots": {
            "total": int(snap_total),
            "latest_id": int(snap_row["SnapshotId"]) if snap_row else None,
            "latest_at": str(snap_row["CreatedAt"]) if snap_row else None,
            "latest_age": _age(str(snap_row["CreatedAt"]) if snap_row else None),
        },
        "last_restored": {
            "snapshot_id": int(settings["LastRestoredSnapshotId"] or 0) or None,
            "at": settings["LastRestoredAt"] or None,
        },
        "crash_recovery": {
            "needs_recovery": bool(is_crash),
            "candidate_snapshot_id": recover_id,
            "last_heartbeat": recover_hb,
            "clean_shutdown_flag": str(settings["CleanShutdown"]).lower() == "true",
        },
    }

    if as_json:
        click.echo(_json.dumps(payload, indent=2, default=str))
        return

    t = Table(title="Idle Shutdown — status", show_header=False)
    t.add_column("Key", style="bold")
    t.add_column("Value")
    t.add_row("Service",
              f"{payload['service_state']}"
              + (" [DRY RUN]" if payload['dry_run'] else " [LIVE]"))
    t.add_row("Idle now",
              "n/a" if payload['idle_seconds'] is None else f"{payload['idle_seconds']}s "
              f"(threshold {payload['idle_threshold_minutes']}m)")
    t.add_row("Popup", f"{payload['popup_countdown_seconds']}s countdown · "
                       f"snooze {payload['snooze_minutes']}m")
    if payload['snooze_until']:
        t.add_row("Snoozed until", payload['snooze_until'])
    bg = payload['background_snapshots']
    t.add_row("Background", f"{'on' if bg['enabled'] else 'off'} · "
                            f"every {bg['interval_minutes']}m · "
                            f"last heartbeat {bg['last_heartbeat_age']}")
    sn = payload['snapshots']
    t.add_row("Snapshots",
              f"{sn['total']} total · latest #{sn['latest_id'] or '-'} ({sn['latest_age']})")
    lr = payload['last_restored']
    t.add_row("Last restored",
              f"#{lr['snapshot_id']} at {lr['at']}" if lr['snapshot_id'] else "never")
    cr = payload['crash_recovery']
    if cr['needs_recovery']:
        t.add_row("⚠ Crash recovery",
                  f"unexpected shutdown — restore snapshot #{cr['candidate_snapshot_id']} "
                  f"(last heartbeat {cr['last_heartbeat'] or 'unknown'})")
    else:
        t.add_row("Crash recovery", "clean — nothing to recover")
    console.print(t)


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
    from idle_shutdown.heartbeat import HeartbeatScheduler

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
        get_snooze_minutes=lambda: int(_settings_provider("SnoozeMinutes")),
    )
    service = IdleService(callbacks)
    def _guard_cfg() -> GuardConfig:
        return GuardConfig(
            mic_enabled=str(_settings_provider("GuardMicEnabled")).lower() == "true",
            audio_enabled=str(_settings_provider("GuardAudioEnabled")).lower() == "true",
            fullscreen_enabled=str(_settings_provider("GuardFullscreenEnabled")).lower() == "true",
            camera_enabled=str(_settings_provider("GuardCameraEnabled")).lower() == "true",
        )
    guard = ActivityGuard(_guard_cfg)
    # Crash-recovery notice (Phase C — console fallback for headless runs).
    try:
        from idle_shutdown.heartbeat import detect_crash_recovery_candidate
        is_crash, snap_id, last_hb = detect_crash_recovery_candidate()
        if is_crash and snap_id is not None:
            click.echo(
                f"⚠ previous session ended unexpectedly (last heartbeat: "
                f"{last_hb or 'unknown'}). "
                f"Run `idle-shutdown restore --snapshot-id {snap_id}` to recover."
            )
    except Exception:  # noqa: BLE001
        pass
    heartbeat = HeartbeatScheduler(
        take_snapshot=lambda trigger: take_snapshot(trigger, record_log=False),
    )
    heartbeat.mark_started()
    monitor = IdleMonitor(
        source=get_default_idle_source(),
        threshold_ms_provider=service.threshold_ms,
        on_threshold=service.on_threshold_reached,
        on_activity=service.on_activity_during_prompt,
        is_busy=guard.is_busy,
        on_tick=heartbeat.tick,
    )
    with acquire_single_instance():
        click.echo("idle monitor running (Ctrl+C to stop)")
        try:
            monitor.run_forever()
        finally:
            heartbeat.mark_clean_exit()


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
@click.option("--dry-run", is_flag=True,
              help="Preview what would launch (no apps started, no Chrome).")
@click.option("--apps-only", is_flag=True,
              help="Restore native apps only (skip Chrome and variant browsers).")
@click.option("--chrome-only", is_flag=True,
              help="Restore Chrome + variant tabs only (skip native apps).")
def cmd_restore(snapshot_id: Optional[int], dry_run: bool,
                apps_only: bool, chrome_only: bool) -> None:
    """Restore the latest (or given) snapshot.

    With ``--dry-run``: prints the full launch plan (apps + Chrome tabs per
    profile) and exits without spawning anything. Recommended before the
    Phase 5 real-shutdown smoke test.
    """
    from idle_shutdown.restore import restore
    from idle_shutdown.single_instance import acquire_single_instance

    if dry_run:
        planned: list[list[str]] = []

        def _fake_spawn(argv: list[str], cwd: Optional[str]) -> Optional[int]:
            planned.append(argv + ([f"  (cwd={cwd})"] if cwd else []))
            return None  # no real PID — also disables move_to_desktop calls

        result = restore(snapshot_id, spawn=_fake_spawn, dry_run=True,
                         apps_only=apps_only, chrome_only=chrome_only)
        click.echo(
            f"DRY RUN — snapshot {result.snapshot_id}\n"
            f"  would launch: {result.apps_launched} app(s)\n"
            f"  would skip:   {result.apps_skipped} (already running)\n"
            f"  Chrome:       {'would launch' if result.chrome_launched else 'no'}"
            + (f"\n  variants:     {', '.join(result.variants_launched)}"
               if result.variants_launched else "")
        )
        if planned:
            click.echo("\nPlanned commands:")
            for argv in planned:
                click.echo("  $ " + " ".join(argv))
        return

    with acquire_single_instance():
        result = restore(snapshot_id,
                         apps_only=apps_only, chrome_only=chrome_only)
    click.echo(
        f"restored snapshot {result.snapshot_id}: "
        f"launched={result.apps_launched} skipped={result.apps_skipped} "
        f"excluded={result.apps_excluded} "
        f"chrome={'yes' if result.chrome_launched else 'no'}"
        + (f" variants={','.join(result.variants_launched)}"
           if result.variants_launched else "")
    )


@cli.command("recover")
def cmd_recover() -> None:
    """Detect an unexpected shutdown and report what's recoverable."""
    from idle_shutdown.heartbeat import detect_crash_recovery_candidate
    is_crash, snap_id, last_hb = detect_crash_recovery_candidate()
    if not is_crash:
        click.echo("no crash detected — last shutdown was clean")
        return
    click.echo(
        f"⚠ unexpected shutdown detected. Last heartbeat: {last_hb or 'unknown'}.\n"
        f"Latest snapshot: #{snap_id}.\n"
        f"To restore: idle-shutdown restore --snapshot-id {snap_id}"
    )


@cli.command("install-autostart")
def cmd_install_autostart() -> None:
    """Write the HKCU Run entry so the service starts on login."""
    from idle_shutdown.autostart import default_executable_path, install_autostart
    cmd = install_autostart(default_executable_path())
    click.echo(f"autostart installed: {cmd}")


# ----- exclude (per-app restore exclusions) ---------------------------------


@cli.group("exclude")
def cmd_exclude() -> None:
    """Manage apps that should never be relaunched by `restore`."""


@cmd_exclude.command("add")
@click.argument("executable_path")
@click.option("--reason", default="", help="Free-text note (e.g. 'password manager').")
def cmd_exclude_add(executable_path: str, reason: str) -> None:
    from idle_shutdown.db.repos import RestoreExclusionRepo
    with connect() as conn:
        RestoreExclusionRepo(conn).add(executable_path, reason)
    click.echo(f"excluded: {executable_path}")


@cmd_exclude.command("remove")
@click.argument("executable_path")
def cmd_exclude_remove(executable_path: str) -> None:
    from idle_shutdown.db.repos import RestoreExclusionRepo
    with connect() as conn:
        n = RestoreExclusionRepo(conn).remove(executable_path)
    if n:
        click.echo(f"removed: {executable_path}")
    else:
        click.echo(f"not found: {executable_path}", err=True)
        raise click.exceptions.Exit(1)


@cmd_exclude.command("list")
def cmd_exclude_list() -> None:
    from idle_shutdown.db.repos import RestoreExclusionRepo
    with connect() as conn:
        rows = RestoreExclusionRepo(conn).list()
    if not rows:
        click.echo("(no exclusions)")
        return
    t = Table(title="Restore exclusions")
    t.add_column("Executable")
    t.add_column("Reason")
    t.add_column("Added")
    for r in rows:
        t.add_row(r.executable_path, r.reason or "-", r.created_at)
    console.print(t)


# ----- doctor ----------------------------------------------------------------


@cli.command("doctor")
def cmd_doctor() -> None:
    """Preflight diagnostic. Run before the Phase 5 real-shutdown smoke test.

    Checks: DB writable, schema present, idle source, Chrome detected,
    autostart installed, single-instance lock free, latest snapshot freshness.
    Exits 0 if all green, 1 if any FAIL.
    """
    import os
    from datetime import datetime, timezone
    from idle_shutdown.config import db_path, app_data_dir, lock_path

    results: list[tuple[str, str, str]] = []  # (status, name, detail)
    OK, WARN, FAIL = "OK", "WARN", "FAIL"

    # 1. App dir + DB
    try:
        ad = app_data_dir()
        ad.mkdir(parents=True, exist_ok=True)
        results.append((OK, "app data dir", str(ad)))
    except Exception as e:  # noqa: BLE001
        results.append((FAIL, "app data dir", str(e)))

    try:
        with connect() as conn:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table'"
            ).fetchone()["n"]
        results.append((OK, "database", f"{db_path()} ({n} tables)"))
    except Exception as e:  # noqa: BLE001
        results.append((FAIL, "database",
                        f"{e} — run `idle-shutdown init-db`"))

    # 2. Single-instance lock
    try:
        lp = lock_path()
        if lp.exists():
            results.append((WARN, "instance lock",
                            f"lock file present at {lp} — another instance may be running"))
        else:
            results.append((OK, "instance lock", "free"))
    except Exception as e:  # noqa: BLE001
        results.append((WARN, "instance lock", str(e)))

    # 3. Idle source
    try:
        from idle_shutdown.platform import get_default_idle_source
        ms = get_default_idle_source().get_idle_ms()
        results.append((OK, "idle source", f"reports {int(ms / 1000)}s"))
    except Exception as e:  # noqa: BLE001
        results.append((WARN, "idle source",
                        f"{e} — popup/countdown won't trigger automatically"))

    # 4. Chrome detected
    try:
        from idle_shutdown.capture.chrome import detect_chrome_path
        exe = detect_chrome_path()
        if exe:
            results.append((OK, "chrome", exe))
        else:
            results.append((WARN, "chrome",
                            "not detected — tab capture/restore will be skipped"))
    except Exception as e:  # noqa: BLE001
        results.append((WARN, "chrome", str(e)))

    # 5. Autostart
    try:
        from idle_shutdown.autostart import is_autostart_installed
        if is_autostart_installed():
            results.append((OK, "autostart", "registered (HKCU Run)"))
        else:
            results.append((WARN, "autostart",
                            "not installed — run `idle-shutdown install-autostart`"))
    except Exception as e:  # noqa: BLE001
        results.append((WARN, "autostart", str(e)))

    # 6. Latest snapshot freshness (compare against background interval)
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT SnapshotId, CreatedAt FROM Snapshot "
                "ORDER BY SnapshotId DESC LIMIT 1"
            ).fetchone()
            interval_min = int(SettingsRepo(conn).get(
                "BackgroundSnapshotIntervalMinutes") or 5)
        if not row:
            results.append((WARN, "latest snapshot",
                            "none yet — run `idle-shutdown snapshot`"))
        else:
            ts = datetime.fromisoformat(
                str(row["CreatedAt"]).replace("Z", "+00:00"))
            age_s = int((datetime.now(timezone.utc) - ts).total_seconds())
            label = f"#{row['SnapshotId']} · {age_s}s old"
            # Allow up to 3x background interval before warning.
            if age_s > interval_min * 60 * 3:
                results.append((WARN, "latest snapshot",
                                f"{label} (older than 3× background interval)"))
            else:
                results.append((OK, "latest snapshot", label))
    except Exception as e:  # noqa: BLE001
        results.append((WARN, "latest snapshot", str(e)))

    # 7. DryRun banner — informational, never failing
    try:
        with connect() as conn:
            dry = str(SettingsRepo(conn).get("DryRun") or "true").lower() == "true"
        results.append((OK if dry else WARN, "shutdown mode",
                        "DRY RUN (safe)" if dry else "LIVE — will power off the machine"))
    except Exception as e:  # noqa: BLE001
        results.append((WARN, "shutdown mode", str(e)))

    table = Table(title="idle-shutdown doctor")
    table.add_column("Status")
    table.add_column("Check")
    table.add_column("Detail")
    color = {OK: "green", WARN: "yellow", FAIL: "red"}
    for status, name, detail in results:
        table.add_row(f"[{color[status]}]{status}[/]", name, detail)
    console.print(table)

    if any(s == FAIL for s, _, _ in results):
        raise click.exceptions.Exit(1)


@cli.command("tray")
def cmd_tray() -> None:
    """Run the system-tray status icon (requires the optional 'tray' extras).

    Install with:  pip install -e ".[tray]"
    Reads live state from the DB; safe to run alongside `idle-shutdown run`.
    """
    from idle_shutdown.db.repos import SettingsRepo
    from idle_shutdown.enums import SnapshotTriggerKind
    from idle_shutdown.snapshot import take_snapshot
    try:
        from idle_shutdown.platform import get_default_idle_source
    except Exception:  # noqa: BLE001
        get_default_idle_source = None  # type: ignore[assignment]

    idle_src = get_default_idle_source() if get_default_idle_source else None

    def _idle_seconds() -> int:
        if idle_src is None:
            return 0
        try:
            return int(idle_src.get_idle_ms() / 1000)
        except Exception:  # noqa: BLE001
            return 0

    def _service_enabled() -> bool:
        with connect() as conn:
            return SettingsRepo(conn).get("ServiceState") == "Enabled"

    def _latest_snapshot() -> tuple[Optional[int], Optional[str]]:
        with connect() as conn:
            row = conn.execute(
                "SELECT SnapshotId, CreatedAt FROM Snapshot "
                "ORDER BY SnapshotId DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None, None
            return int(row["SnapshotId"]), str(row["CreatedAt"])

    def _snooze_minutes() -> int:
        with connect() as conn:
            return int(SettingsRepo(conn).get("SnoozeMinutes") or 30)

    def _snapshot_now() -> None:
        take_snapshot(SnapshotTriggerKind.Manual, record_log=False)

    def _snooze(mins: int) -> None:
        from idle_shutdown.db.connection import utc_now_iso
        from datetime import datetime, timedelta, timezone
        until = datetime.now(timezone.utc) + timedelta(minutes=mins)
        with connect() as conn:
            SettingsRepo(conn).set(
                "DisabledUntil", until.strftime("%Y-%m-%dT%H:%M:%SZ"))

    def _quit() -> None:
        click.echo("tray: quit")

    try:
        from idle_shutdown.tray import run_tray
        run_tray(
            get_idle_seconds=_idle_seconds,
            get_service_enabled=_service_enabled,
            get_latest_snapshot=_latest_snapshot,
            get_snooze_minutes=_snooze_minutes,
            snapshot_now=_snapshot_now,
            snooze=_snooze,
            on_quit=_quit,
        )
    except RuntimeError as e:
        raise click.ClickException(str(e))


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


# ----- diff ------------------------------------------------------------------


@cli.command("diff")
@click.argument("snapshot_a", type=int)
@click.argument("snapshot_b", type=int)
@click.option("--json", "as_json", is_flag=True,
              help="Emit the diff as JSON for piping.")
def cmd_diff(snapshot_a: int, snapshot_b: int, as_json: bool) -> None:
    """Compare two snapshots: apps and tabs added or removed."""
    import json as _json
    from idle_shutdown.diff import compute_snapshot_diff

    with connect() as conn:
        repo = SnapshotReadRepo(conn)
        a = repo.get_detail(snapshot_a)
        b = repo.get_detail(snapshot_b)
    if a is None:
        click.echo(f"snapshot {snapshot_a} not found", err=True); sys.exit(1)
    if b is None:
        click.echo(f"snapshot {snapshot_b} not found", err=True); sys.exit(1)

    d = compute_snapshot_diff(a, b)

    if as_json:
        click.echo(_json.dumps({
            "a": d.a_id, "b": d.b_id,
            "apps_added": [x.__dict__ for x in d.apps_added],
            "apps_removed": [x.__dict__ for x in d.apps_removed],
            "tabs_added": [x.__dict__ for x in d.tabs_added],
            "tabs_removed": [x.__dict__ for x in d.tabs_removed],
        }, indent=2))
        return

    console.print(
        f"[bold]Diff[/bold] #{d.a_id} → #{d.b_id}  "
        f"apps:+{len(d.apps_added)}/-{len(d.apps_removed)}  "
        f"tabs:+{len(d.tabs_added)}/-{len(d.tabs_removed)}"
    )
    if d.is_empty:
        console.print("[dim]no changes[/dim]")
        return

    def _apps_table(title, rows):
        t = Table(title=title)
        t.add_column("Desktop", justify="right")
        t.add_column("Executable", overflow="fold")
        t.add_column("Document", overflow="fold")
        for r in rows:
            t.add_row(str(r.desktop_index), r.executable_path, r.document_path or "")
        return t

    def _tabs_table(title, rows):
        t = Table(title=title)
        t.add_column("Browser")
        t.add_column("Profile")
        t.add_column("Title", overflow="fold", max_width=40)
        t.add_column("URL", overflow="fold", max_width=70)
        for r in rows:
            t.add_row(r.browser_name or "-",
                      r.profile_name or r.profile_dir or "-",
                      r.title, r.url)
        return t

    if d.apps_added:
        console.print(_apps_table("Apps added (in B, not in A)", d.apps_added))
    if d.apps_removed:
        console.print(_apps_table("Apps removed (in A, not in B)", d.apps_removed))
    if d.tabs_added:
        console.print(_tabs_table("Tabs added", d.tabs_added))
    if d.tabs_removed:
        console.print(_tabs_table("Tabs removed", d.tabs_removed))


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


@cli.command("export")
@click.option("--snapshot-id", "snapshot_id", type=int, default=None,
              help="Snapshot to export (default: latest).")
@click.option("--format", "fmt", type=click.Choice(["json", "html"]),
              default="json", show_default=True)
@click.option("--output", "-o", type=click.Path(dir_okay=False), default=None,
              help="Output path. Default: <snapshots_dir>/snapshot-<id>.<ext>.")
@click.option("--stdout", "to_stdout", is_flag=True,
              help="Write to stdout instead of a file.")
def cmd_export(snapshot_id: Optional[int], fmt: str,
               output: Optional[str], to_stdout: bool) -> None:
    """Export a snapshot as portable JSON or self-contained HTML."""
    from pathlib import Path
    from idle_shutdown.config import ensure_app_dirs, snapshots_dir
    from idle_shutdown.export import snapshot_to_html, snapshot_to_json

    with connect() as conn:
        repo = SnapshotReadRepo(conn)
        if snapshot_id is None:
            snapshot_id = repo.latest_id()
            if snapshot_id is None:
                click.echo("no snapshots found", err=True); sys.exit(1)
        detail = repo.get_detail(snapshot_id)
    if detail is None:
        click.echo(f"snapshot {snapshot_id} not found", err=True); sys.exit(1)

    payload = (snapshot_to_html(detail) if fmt == "html"
               else snapshot_to_json(detail))

    if to_stdout:
        click.echo(payload)
        return

    if output is None:
        ensure_app_dirs()
        output = str(snapshots_dir() / f"snapshot-{detail.snapshot_id}.{fmt}")
    Path(output).write_text(payload, encoding="utf-8")
    click.echo(f"wrote {output}")


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