# 08 — CLI Commands

Implemented with `click`. Shipping entrypoint: `idle-shutdown.exe <command> [args]` (PyInstaller-frozen). Dev entrypoint: `python -m idle_shutdown <command>`. Both MUST behave identically.

Global flags (apply to every subcommand):
- `--verbose / -v` — raise log level to DEBUG.
- `--db PATH` — override DB path (also via `IDLE_SHUTDOWN_DB`). Useful for tests.
- `--help` — click default.

| Command | Description |
|---|---|
| `init-db` | Create DB file, apply schema, seed lookups + defaults |
| `run [--silent]` | Foreground service: monitor + popup loop. `--silent` hides console |
| `settings show` | Print all rows from `Setting` |
| `settings set-idle <minutes>` | Update `IdleThresholdMinutes` (1–240) |
| `settings set-countdown <seconds>` | Update `PopupCountdownSeconds` (30–60) |
| `history [--limit N]` | List shutdown events with timestamp + outcome |
| `snapshot` | Manually capture a snapshot (`TriggerKind = Manual`), no shutdown |
| `disable [--minutes N]` | Set `ServiceState = Disabled`, optional auto-re-enable timer |
| `enable` | Set `ServiceState = Enabled` |
| `restore [--snapshot-id N]` | Restore latest (or given) snapshot |
| `install-autostart` | Write HKCU Run entry |
| `uninstall-autostart` | Remove HKCU Run entry |
| `counter` | Print `ShutdownCounter.TotalCount` |

## Exit codes
See `12-config-and-paths/` for the full table. Summary per command:

| Command | Success | Notable failures |
|---|---|---|
| `init-db` | 0 | 41 (no `LOCALAPPDATA`) |
| `run` | 0 on clean stop | 21 (monitor), 42 (already running) |
| `settings show` | 0 | 40 (DB missing) |
| `settings set-*` | 0 | 10 (out of range), 40 |
| `history` | 0 | 40 |
| `snapshot` | 0 | 20 (snapshot failed), 40 |
| `disable` / `enable` | 0 | 10, 40 |
| `restore` | 0 | 22 (fatal), 42 (already running), 40 |
| `install-autostart` / `uninstall-autostart` | 0 | 30 |
| `counter` | 0 | 40 |

## Argument contracts
- `settings set-idle <minutes>` — integer 1..240. Out of range → exit 10, message: `IdleThresholdMinutes must be 1..240`.
- `settings set-countdown <seconds>` — integer 30..60. Out of range → exit 10.
- `history --limit N` — N is integer 1..1000. Default 20.
- `disable --minutes N` — integer 1..1440. Optional; if omitted, disabled until `enable`.
- `restore --snapshot-id N` — must reference an existing `Snapshot.SnapshotId`; otherwise exit 22 with message `snapshot N not found`.

## Output contracts
- Tables (`history`, `settings show`) use `rich.table.Table`. Columns are ordered and named exactly as listed below — downstream parsers may rely on column order.
  - `history`: `OccurredAt (UTC)`, `Outcome`, `SnapshotId`.
  - `settings show`: `Key`, `Value`, `UpdatedAt (UTC)`.
- `counter` prints a single integer followed by `\n`. No labels, no spaces.
- All other commands print human-readable status to stdout; warnings/errors to stderr.

## Output
Use `rich` for tables (`history`, `settings show`). Plain text otherwise so output is pipe-friendly.
