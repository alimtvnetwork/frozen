# Contributing

## Dev loop (any OS)

The test suite runs cross-platform — Win32-specific code paths are isolated
behind injectable sources / mocks, so you do **not** need a Windows host to
iterate on logic.

```bash
cd app
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest -q
```

Expected: **78 tests passing** on Linux / macOS / Windows.

### Useful one-liners

| | |
|---|---|
| Run a single test file | `pytest tests/unit/test_snss.py -q` |
| Run a single test | `pytest tests/unit/test_snss.py::test_v1_single_command -q` |
| Show coverage | `pytest --cov=idle_shutdown --cov-report=term-missing` |
| Lint | `ruff check .` |
| Type-check | `mypy idle_shutdown` |
| Use a throwaway DB | `IDLE_SHUTDOWN_DB=/tmp/x.db idle-shutdown init-db` |
| JSON logs | `idle-shutdown --log-json snapshot` (or `IDLE_SHUTDOWN_LOG_JSON=1`) |

## Repo layout

```
app/
  idle_shutdown/        ← source
    capture/            ← apps, chrome, desktops, snss
    db/                 ← schema.sql + repos
    cli.py              ← click entrypoint (idle_shutdown.cli:main)
    monitor.py          ← idle source + 1 Hz tick
    popup.py            ← Tk popup
    service.py          ← state machine
    snapshot.py         ← transactional capture
    restore.py          ← per-desktop replay
    shutdown.py         ← WM_CLOSE then shutdown.exe
    autostart.py        ← HKCU\…\Run
    single_instance.py  ← file lock (exit 42)
    logging_setup.py    ← rotating file logger + JSON mode
  tests/
    unit/               ← pure-function + injected-mock tests
    integration/        ← CliRunner-driven end-to-end
  build/                ← PyInstaller spec, version.txt, build.ps1, installer.iss
  USER_GUIDE.md         ← end-user docs
  ACCEPTANCE.md         ← Phase 5 acceptance walkthrough
spec/21-app/            ← authoritative spec (read-only direction of truth)
mem/progress.md         ← phase progress + remaining stretch
```

## Adding code

- **Keep Win32 calls behind an injectable source.** See
  `monitor.IdleSource`, `restore.spawn`, `capture/desktops.capture_desktops`.
  Default impls live next to the protocol; tests pass fakes.
- **All times are UTC ISO-8601** (`db.connection.utc_now_iso`).
- **Errors map to exit codes** (`errors.py`). Add a new subclass with a fresh
  code rather than reusing an existing one — codes are part of the CLI
  contract documented in `USER_GUIDE.md` and `spec/21-app/12-config-and-paths/`.
- **Logging is event-style**: `logger.info("event=foo key=val …")`. The
  JSON formatter picks up `event=` automatically — no extra wiring needed.
- **DB writes go through repos** in `db/repos.py`. Never inline SQL in
  feature code; the repo layer is what tests stub.
- **Spec is the source of truth.** If code disagrees with `spec/21-app/`,
  update one or the other in the same change — never let them drift.

## Adding a CLI command

1. Add the command function in `cli.py` under the right `@cli.command(...)`.
2. Map any new failure to an `IdleShutdownError` subclass with an exit code.
3. Document it in `USER_GUIDE.md` (command table) and
   `spec/21-app/08-cli-commands/`.
4. Add a test in `tests/unit/` (or extend the integration test).

## Releasing

On a Windows x64 host:

```powershell
cd app
pwsh -File build\build.ps1
# Optional installer:
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer.iss
```

Bump `pyproject.toml [project].version` and `build/version.txt` together.
Regenerate `build/requirements.lock` with `pip-compile` whenever
`pyproject.toml` `[project].dependencies` changes — commit both in the same
change.

## What is intentionally out of scope (MVP)

- Tab-group capture (`ChromeTab.GroupName` stays NULL — needs real-Windows
  SNSS fixtures).
- Code signing.
- Multi-monitor / multi-window restore (single window, original desktop).
- Non-Chrome browsers.