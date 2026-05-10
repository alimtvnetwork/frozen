
## Context & Feasibility Note

This project's repo is a TanStack Start web app, but the requested deliverable is a **standalone Windows Python utility**. The Python code will live in a new top-level `app/` directory (separate from the web stack) and won't be wired into Vite/React. The `spec/` tree will live at the repo root as requested.

**4–5h MVP feasibility: confirmed with caveats.** Realistic in that window:
- Idle detection (GetLastInputInfo via pywin32)
- Tk popup w/ countdown
- SQLite schema + settings/snapshot/log persistence
- Running-app capture (psutil) + graceful shutdown
- Auto-start via registry
- CLI (argparse / click)
- Basic restore (relaunch exes, reopen Chrome via `--restore-last-session` or URL list)

**Risky inside 5h — flagged for post-MVP unless trimmed:**
- Per-virtual-desktop app *assignment* capture & restore (Windows VirtualDesktop COM API is undocumented; `pyvda` works but desktop→window mapping for restore is fragile). MVP will record desktop **count** + best-effort assignment, restore by recreating N desktops and launching apps on desktop 1, with assignment as a stretch goal.
- Chrome tab capture with full window/group structure. MVP path: parse Chrome's `Current Session`/`Current Tabs` SNSS files (or fall back to Bookmarks-style URL list); full group fidelity requires the companion extension — documented as Phase 2.
- True "graceful close" of every app (each app has its own quit semantics). MVP issues WM_CLOSE then falls back to Windows shutdown which handles the rest.

These trade-offs are written into the spec's `10-acceptance-criteria/` and `01-overview/` so scope is explicit before coding.

## Phase 0 — Spec & Plan (this phase, on `next`)

Create the full folder tree exactly as specified and populate every leaf with focused markdown. No Python yet.

```text
spec/21-app/
  01-overview/README.md            scope, stack, MVP cut-lines, feasibility
  02-activity-monitor/README.md    GetLastInputInfo design, polling loop, thresholds
  03-idle-popup/README.md          Tk always-on-top, countdown, non-blocking
  04-snapshot-capture/
    README.md                      orchestration
    chrome-tabs/README.md          SNSS parsing + extension fallback
    running-apps/README.md         psutil filter rules, working dir, doc path
    virtual-desktops/README.md     pyvda usage, count + assignment best-effort
    shutdown-log/README.md         counter + timestamped rows
  05-shutdown-sequence/README.md   close order, WM_CLOSE, shutdown.exe /s /t
  06-startup-and-restore/README.md HKCU\...\Run registration, restore order
  07-sqlite-schema/
    README.md                      DDL, indexes, migrations
    erd.md                         Mermaid ERD of all tables + lookups
  08-cli-commands/README.md        argparse command table + examples
  09-enums/README.md               Python Enum ↔ lookup-table mirror rules
  10-acceptance-criteria/README.md the 11 criteria + verification method each
  error-manage/README.md           exception taxonomy, log rotation, retry policy

plan.md                            phased build plan (mirrors phases below)
```

## Phase 1 — Project skeleton (next)

```text
app/
  pyproject.toml                pywin32, psutil, pynput, pyvda, click, rich
  idle_shutdown/
    __init__.py
    __main__.py                 entrypoint: `python -m idle_shutdown`
    config.py                   paths (%LOCALAPPDATA%\IdleShutdownRestore\…)
    enums.py                    SnapshotTriggerKind, ShutdownOutcomeStatus, ServiceState
    db/
      schema.sql                full DDL incl. lookup seed rows
      connection.py             sqlite3 conn + migration runner
      repositories.py           SettingRepo, SnapshotRepo, ShutdownLogRepo
    logging_setup.py            rotating file handler → Logs\app.log
```

Outcome: `python -m idle_shutdown init-db` creates the DB at the spec'd path with all tables + seeded enums.

## Phase 2 — Activity monitor + popup + idle loop (next)

- `monitor.py`: thread polling `GetLastInputInfo` every 1s.
- `popup.py`: Tk Toplevel, `-topmost 1`, countdown label, Yes/No → asyncio-safe queue.
- `service.py`: state machine Idle → Prompting → Snapshotting → ShuttingDown / Cancelled.

Outcome: runs in foreground, popup fires after configured threshold, Yes resets, No/timeout transitions to snapshot stub.

## Phase 3 — Snapshot capture (next)

- `capture/apps.py` (psutil)
- `capture/chrome.py` (SNSS parse; if parse fails, read `Last Tabs` / `Last Session` filenames and store URL list only)
- `capture/desktops.py` (pyvda; record count, attempt window→desktop map)
- Persist via `SnapshotRepo` in one transaction; write `ShutdownLog` row + bump `ShutdownCounter`.

Outcome: `python -m idle_shutdown snapshot` writes a complete snapshot row tree.

## Phase 4 — Shutdown + auto-start + restore (next)

- `shutdown.py`: WM_CLOSE to top-level windows, then `shutdown /s /t 5 /f`.
- `autostart.py`: write `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value.
- `restore.py`: read latest snapshot, ensure N virtual desktops via pyvda, `subprocess.Popen` each exe with cwd, launch Chrome with `--restore-last-session` plus URL list fallback.

Outcome: end-to-end loop verified in a VM; `restore` CLI command works on demand.

## Phase 5 — CLI polish + acceptance pass (next)

`click` group with: `settings show`, `settings set-idle <minutes>`, `settings set-countdown <seconds>`, `history`, `snapshot`, `disable [--minutes N]`, `enable`, `restore`, `install-autostart`, `uninstall-autostart`. Walk through the 11 acceptance criteria, mark pass/defer.

## Database (verbatim, locked)

Schema, PascalCase table/column names, `{TableName}Id INTEGER PK AUTOINCREMENT`, SMALLINT enum FKs, lookup tables seeded from Python `Enum` at `init-db`. ERD rendered in `spec/21-app/07-sqlite-schema/erd.md` as Mermaid `erDiagram`.

## Open questions before Phase 0

1. **Chrome tab fidelity**: OK to ship MVP with **URL+title list per window** (no group names) and defer full group capture to a Phase-2 companion extension? Verbatim asks for groups but lists the extension as one of three acceptable sources.
2. **Per-desktop app assignment**: OK to ship MVP that records desktop **count** and relaunches all apps on desktop 1, with per-desktop mapping as a stretch within the 5h budget?
3. **Auto-start mechanism**: prefer **HKCU Run registry** (simpler, no admin) over Task Scheduler? Verbatim allows either.
4. **Confirm target environment**: this will be developed/tested on Windows (not in this Linux sandbox). I'll write code + unit tests that can run cross-platform where possible, but final integration testing requires you to run on Windows. OK?

Reply with answers (or just `next` to accept defaults: 1=URL+title list, 2=count only + desktop 1, 3=HKCU Run, 4=yes) and I'll execute Phase 0.
