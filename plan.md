# Idle Shutdown & Session Restore — Build Plan

Standalone Windows Python utility. Code lives in `app/` (separate from this repo's TanStack web stack). Spec lives in `spec/21-app/`. SQLite is the only persistence store.

## Defaults locked (from approved plan)

1. Chrome tabs: capture URL + title per window; tab groups deferred to a Phase-2 companion extension.
2. Virtual desktops: capture count + best-effort window→desktop map; restore recreates N desktops, relaunches apps on desktop 1 (assignment is stretch).
3. Auto-start: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
4. Final integration testing happens on Windows; sandbox-safe unit tests where possible.

## Phases

| Phase | Goal | Trigger |
|---|---|---|
| 0 | Full spec tree under `spec/21-app/` + this `plan.md` | done now |
| 1 | Project skeleton: `app/`, config, enums, SQLite schema, `init-db` CLI | `next` |
| 2 | Activity monitor (GetLastInputInfo) + Tk popup + idle state machine | `next` |
| 3 | Snapshot capture (apps, Chrome, virtual desktops) + log/counter | `next` |
| 4 | Graceful shutdown + HKCU autostart + restore | `next` |
| 5 | CLI polish (`click`) + walk the 11 acceptance criteria | `next` |

## MVP cut-lines (4–5h budget)

- In: idle detect, popup, snapshot to SQLite, shutdown, autostart, restore of apps + Chrome URLs, full CLI.
- Deferred: per-desktop restore mapping, Chrome tab groups, per-app graceful quit semantics beyond WM_CLOSE.

## Storage paths

- DB: `%LOCALAPPDATA%\IdleShutdownRestore\IdleShutdown.db`
- Logs: `%LOCALAPPDATA%\IdleShutdownRestore\Logs\app.log`
- Snapshot artifacts: `%LOCALAPPDATA%\IdleShutdownRestore\Snapshots\`

See `spec/21-app/` for per-area detail.
