# Error Management

## Exception taxonomy
| Class | Raised when | Recovery |
|---|---|---|
| `ConfigError` | invalid setting value (out of range, wrong type) | reject in CLI; log + use default in service |
| `SnapshotError` | snapshot transaction fails | rollback; write `ShutdownLog(OutcomeStatusId=Failed)` separately; abort shutdown |
| `RestoreError` | restore step fails for one app/tab | log + continue with next item |
| `MonitorError` | activity hook fails | log + retry once after 5s; if still failing, exit with non-zero |
| `AutostartError` | registry write/delete fails | surface to CLI with actionable message |

## Logging
- File: `%LOCALAPPDATA%\IdleShutdownRestore\Logs\app.log`
- Format: `%(asctime)s %(levelname)s %(name)s %(message)s`
- `RotatingFileHandler` — 1 MB × 5 files.
- Level default `INFO`, `--verbose` raises to `DEBUG`.

## Retry policy
- Snapshot: no retry (would delay shutdown). Single attempt + log.
- Restore: per-item retry once with 1s backoff.
- Monitor: tick failures retry next tick silently; consecutive 10 failures escalate to `MonitorError`.

## User-visible errors
CLI errors print red via `click.secho(..., fg='red')` and exit non-zero. Background service never shows error popups — they go to the log.
