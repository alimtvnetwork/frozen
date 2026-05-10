# Error Management

## Exception taxonomy
| Class | Exit code | Raised when | Recovery |
|---|---|---|---|
| `ConfigError` | 10 | invalid setting value (out of range, wrong type, unknown key) | reject in CLI; log + use default in service |
| `SnapshotError` | 20 | snapshot transaction fails | rollback; write `ShutdownLog(OutcomeStatusId=Failed)` separately; abort shutdown |
| `MonitorError` | 21 | activity hook fails after one retry | log + exit `run` non-zero |
| `RestoreError` | 22 (fatal only) | DB unreadable, target snapshot missing | per-item failures DO NOT raise; only fatal cases exit |
| `AutostartError` | 30 | registry write/delete fails | surface to CLI with actionable message |
| `DBNotInitializedError` | 40 | DB file missing or schema absent | print `run init-db first` |
| `EnvError` | 41 | required env var missing | print which var |
| `AlreadyRunningError` | 42 | lock file held | print pid of holder |

Every exception subclasses a base `IdleShutdownError(message, exit_code)` so `cli.main` has one `except` clause that maps to `sys.exit(exc.exit_code)` and a red `click.secho` of `exc.message`.

## Logging
- File: `%LOCALAPPDATA%\IdleShutdownRestore\Logs\app.log`
- Format: `%(asctime)s %(levelname)s %(name)s %(message)s`
- `RotatingFileHandler` — 1 MB × 5 files.
- Level default `INFO`, `--verbose` raises to `DEBUG`.
- Time in UTC ISO-8601.
- Structured key=value tail on event lines (e.g. `event=snapshot_started snapshot_id=42 trigger=Auto`). Reserved event names: `snapshot_started`, `snapshot_committed`, `snapshot_failed`, `shutdown_invoked`, `popup_shown`, `popup_result`, `restore_started`, `restore_item`, `restore_completed`, `skip_relaunch`, `chrome_not_detected`.

## Retry policy
- Snapshot: no retry (would delay shutdown). Single attempt + log.
- Restore: per-item retry once with 1s backoff.
- Monitor: tick failures retry next tick silently; consecutive 10 failures escalate to `MonitorError`.

## User-visible errors
CLI errors print red via `click.secho(..., fg='red')` and exit non-zero. Background service never shows error popups — they go to the log.
