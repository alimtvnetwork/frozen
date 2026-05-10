# idle-shutdown

Windows utility that detects idle, prompts the user, snapshots the session to SQLite, shuts down cleanly, and restores everything on next boot. See `../spec/21-app/` for the authoritative specification.

## Dev quickstart (Windows)
```
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
python -m idle_shutdown init-db
python -m idle_shutdown settings show
```

## Build the shipping exe
```
pyinstaller build/idle-shutdown.spec --noconfirm --clean
```

## Test
```
pytest tests/unit            # cross-platform (Win32 modules mocked)
pytest tests/integration     # Windows only
```