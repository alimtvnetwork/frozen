# 06 — Startup & Restore

## Auto-start (HKCU Run)
On first run (or via `install-autostart`), write:
```
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
  Value: IdleShutdownRestore
  Data:  "<python.exe>" -m idle_shutdown run --silent
```
No admin rights required. `uninstall-autostart` deletes the value.

## Boot sequence
1. App launches silently (`--silent` skips console window).
2. Begin idle monitor immediately.
3. If `Setting.KeyName = 'AutoRestoreOnBoot'` is `true` (default `true`) AND a snapshot newer than last completed restore exists, run restore.

## Restore steps
1. Read latest `Snapshot` row.
2. Ensure virtual desktop count via `pyvda` (create as needed).
3. For each `AppProcess`: `subprocess.Popen([ExecutablePath, DocumentPath?], cwd=WorkingDirectory)`. Failures logged, restore continues.
4. Launch Chrome: `chrome.exe --restore-last-session`. If Chrome's session is stale, also pass each `ChromeTab.Url` as a positional arg.
5. Stretch: after each launch, find new HWND and move to recorded desktop.

## Manual restore
`python -m idle_shutdown restore [--snapshot-id N]` — defaults to latest.
