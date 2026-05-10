# 10 — Acceptance Criteria

| # | Criterion | Verification |
|---|---|---|
| 1 | Auto-starts on Windows login | After `install-autostart`, sign out / in; process appears in Task Manager |
| 2 | Idle detected within ±2s of threshold | Set threshold to 1 min, idle, observe popup time |
| 3 | Popup is always-on-top, non-blocking, with countdown | Manual visual check |
| 4 | Yes resets timer; No / timeout starts shutdown | Click each path; observe behavior |
| 5 | Snapshot captures Chrome tabs, apps (path+cwd or doc), virtual desktops | Inspect SQLite after `snapshot` |
| 6 | Shutdown counter increments + timestamped row each time | `history` and `counter` after run |
| 7 | Windows shuts down cleanly with no orphan processes | Cold boot, Event Viewer check |
| 8 | Restore recreates desktops, relaunches apps, reopens Chrome tabs | After auto-shutdown, observe boot |
| 9 | SQLite is single source; deleting DB resets to defaults | Delete DB, run `init-db`, verify defaults |
| 10 | All CLI commands functional | Walk the table in `08-cli-commands/` |
| 11 | MVP build stays within 4–5h | Time-boxed phases 1–5 |

## Known MVP gaps (documented, accepted)
- Criterion 5 — `GroupName` always null (Phase-2 extension).
- Criterion 8 — apps relaunched on desktop 1, not original desktop (stretch).
