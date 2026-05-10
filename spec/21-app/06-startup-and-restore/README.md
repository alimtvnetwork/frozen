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
3. For each `AppProcess`, apply the **duplicate-prevention rule** below; if not skipped, `subprocess.Popen([ExecutablePath, DocumentPath?], cwd=WorkingDirectory)`. Failures logged, restore continues.
4. Launch Chrome: `chrome.exe --restore-last-session`. If Chrome's session is stale, also pass each `ChromeTab.Url` as a positional arg.
5. Stretch: after each launch, find new HWND and move to recorded desktop.

## Duplicate-prevention rule (locked)
Before launching an `AppProcess` row, enumerate live processes via `psutil`. **Skip** the launch if any running process satisfies BOTH:
- `proc.exe()` case-insensitive equals `AppProcess.ExecutablePath`, AND
- `AppProcess.DocumentPath` is null OR appears (case-insensitive substring match) in `proc.cmdline()`.

Comparison details:
- Path comparison normalizes via `os.path.normcase(os.path.normpath(...))`.
- Skipped launches are logged at `INFO`: `skip_relaunch exe=<path> doc=<path|null> reason=already_running pid=<pid>`.
- A skip counts as success for restore-progress reporting.

## Restore idempotency
`restore` MUST be safe to invoke multiple times back-to-back without spawning duplicates. The rule above is the sole guard; do not rely on time windows.

## Restore completion marker
After restore finishes (success or partial), write `Setting('LastRestoredSnapshotId', '<id>')` and `Setting('LastRestoredAt', '<iso8601>')`. Auto-restore on boot only runs when latest `Snapshot.SnapshotId > LastRestoredSnapshotId`.

## Manual restore
`python -m idle_shutdown restore [--snapshot-id N]` — defaults to latest.
