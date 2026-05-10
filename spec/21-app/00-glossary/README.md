# 00 — Glossary

Terms used across the spec. When in doubt, refer here.

| Term | Definition |
|---|---|
| **Activity** | Any mouse, keyboard, or touch input recognized by Win32 `GetLastInputInfo`. |
| **Idle time** | `GetTickCount() - LastInputInfo.dwTime`, in milliseconds. |
| **Idle threshold** | Configured ms after which the popup is shown. From `Setting('IdleThresholdMinutes')`. |
| **Service state** | High-level on/off switch for the monitor. Values: `Enabled`, `Disabled`. |
| **Monitor** | The 1 Hz polling loop that reads idle time and drives state transitions. |
| **Popup** | The Tk Toplevel "Are you still at your desk?" prompt with countdown. |
| **Snapshot** | An atomically-captured record of desktops + apps + Chrome at a point in time. One row in `Snapshot`. |
| **Trigger kind** | Why a snapshot was captured: `Auto` (idle), `Manual` (`snapshot` CLI), `Scheduled` (future). |
| **Shutdown sequence** | The ordered steps after a successful snapshot: WM_CLOSE → `shutdown /s /t 5 /f`. |
| **Outcome status** | Result of a shutdown attempt: `Completed`, `Cancelled`, `Failed`. |
| **Restore** | The boot-time replay of a snapshot: recreate desktops → relaunch apps → reopen Chrome. |
| **Duplicate-prevention rule** | The exe + DocumentPath match defined in `06-startup-and-restore/`. |
| **Owned exe** | This application's own `idle-shutdown.exe` process; never targeted by WM_CLOSE / restore filters. |
| **App data dir** | `%LOCALAPPDATA%\IdleShutdownRestore\` — sole on-disk footprint. |

## State machine names (canonical)
`Idle` → `Prompting` → (`Snapshotting` → `ShuttingDown`) | `Idle`. No other state names appear in code or logs.