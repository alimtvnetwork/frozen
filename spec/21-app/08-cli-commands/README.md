# 08 — CLI Commands

Implemented with `click`. Entrypoint: `python -m idle_shutdown <command>`.

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

## Output
Use `rich` for tables (`history`, `settings show`). Plain text otherwise so output is pipe-friendly.
