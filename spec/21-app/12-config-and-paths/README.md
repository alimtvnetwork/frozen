# 12 — Configuration, Paths, Exit Codes

The single source of every filesystem path, registry key, environment variable, and process exit code. Implementations MUST use these exact strings.

## Filesystem paths
| Purpose | Path |
|---|---|
| App data root | `%LOCALAPPDATA%\IdleShutdownRestore\` |
| SQLite DB | `%LOCALAPPDATA%\IdleShutdownRestore\IdleShutdown.db` |
| SQLite WAL/SHM | `IdleShutdown.db-wal`, `IdleShutdown.db-shm` (auto, same dir) |
| Log directory | `%LOCALAPPDATA%\IdleShutdownRestore\Logs\` |
| Active log file | `Logs\app.log` (rotated → `app.log.1` … `app.log.5`) |
| Lock file (single-instance) | `%LOCALAPPDATA%\IdleShutdownRestore\idle-shutdown.lock` |
| Snapshot artifacts dir | `%LOCALAPPDATA%\IdleShutdownRestore\Snapshots\` (reserved; unused in MVP) |
| Chrome user data probe | `%LOCALAPPDATA%\Google\Chrome\User Data\Default\` |

The app data root is created with `os.makedirs(..., exist_ok=True)` on every command. Permissions: inherit user default. No ACL changes.

## Registry keys
| Purpose | Key | Value name | Type | Data |
|---|---|---|---|---|
| Auto-start | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` | `IdleShutdownRestore` | `REG_SZ` | `"<install dir>\idle-shutdown.exe" run --silent` |
| Chrome auto-detect (read) | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe` | `(Default)` | `REG_SZ` | (read-only) |
| Chrome auto-detect fallback (read) | `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe` | `(Default)` | `REG_SZ` | (read-only) |

The app NEVER writes to `HKLM`.

## Environment variables (read)
| Name | Use | Default if absent |
|---|---|---|
| `LOCALAPPDATA` | base for app data root | error: exit `41` |
| `PROGRAMFILES`, `PROGRAMFILES(X86)` | Chrome detection | skip that probe |
| `IDLE_SHUTDOWN_DB` | override DB path (tests) | derived from `LOCALAPPDATA` |
| `IDLE_SHUTDOWN_LOG_LEVEL` | override log level | `INFO` |

No other env vars are read. The app sets none.

## Process exit codes (locked)
| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Generic CLI usage error (click default) |
| `10` | `ConfigError` — invalid setting value |
| `20` | `SnapshotError` — snapshot transaction failed |
| `21` | `MonitorError` — activity hook failed after retry |
| `22` | `RestoreError` — fatal restore failure (DB unreadable, no snapshot) |
| `30` | `AutostartError` — registry write/delete failed |
| `40` | DB missing or unreadable; run `init-db` |
| `41` | Required environment variable missing (`LOCALAPPDATA`) |
| `42` | Another instance already running (lock file held) |
| `130` | User-cancelled (Ctrl+C) |

Per-item failures inside snapshot/restore (one app, one tab) do NOT change the exit code; they are logged and counted.

## Single-instance enforcement
On startup of `run` and `restore`, acquire an exclusive OS lock on `idle-shutdown.lock` via `msvcrt.locking(LK_NBLCK)`. On failure, exit `42`. CLI commands that don't touch the monitor (`settings`, `history`, `counter`, `snapshot`, `install-autostart`, `uninstall-autostart`, `init-db`) skip the lock.

## Setting keys (authoritative list)
| Key | Type | Default | Range |
|---|---|---|---|
| `IdleThresholdMinutes` | int (text) | `10` | `1..240` |
| `PopupCountdownSeconds` | int (text) | `30` | `30..60` |
| `ServiceState` | enum text | `Enabled` | `Enabled`, `Disabled` |
| `AutoRestoreOnBoot` | bool text | `true` | `true`, `false` |
| `ChromeExecutablePath` | text | `""` | absolute path or empty |
| `LastRestoredSnapshotId` | int (text) | `0` | `0..` |
| `LastRestoredAt` | iso8601 text | `""` | empty or ISO-8601 UTC |
| `DisabledUntil` | iso8601 text | `""` | empty or future ISO-8601 UTC |

Out-of-range writes raise `ConfigError` and exit `10`. Unknown keys are rejected.

## Time format
All `DATETIME` columns and ISO-8601 settings use `YYYY-MM-DDTHH:MM:SS.ffffffZ` (UTC, microsecond precision). Local-time conversion happens only at display in the `history` table.