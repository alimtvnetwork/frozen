# Phase 5 — Go-Live Runbook

This runbook flips Idle-Shutdown from **dry-run** (logs only) to **live**
(actually powers off the machine). Read it once before flipping.

## What changed in defaults (Phase 5)

| Setting | Old default | New default | Why |
|---|---|---|---|
| `IdleThresholdMinutes` | 10 | **15** | Fewer false-positive prompts during real work |
| `PopupCountdownSeconds` | 10 | **60** | Enough time to react / hit Snooze when you walk back |
| `DryRun` | `true` | `true` *(unchanged — flip manually, see below)* | Safety net |

The popup countdown range is now `5..300` s (was `5..120`).

## Behavior on snapshot failure

If `snapshot.capture()` raises during the shutdown sequence, the shutdown is
**aborted** (see `cli.py::_take_snapshot_and_shutdown`). You will still have
the most recent background snapshot (≤5 min old) for crash recovery.

## Pre-flight (do this once on the real Windows box)

1. Make sure the app is registered in `HKCU\...\Run` so it starts at logon:
   ```
   idle-shutdown autostart enable
   ```
2. Confirm a clean DB and recent background snapshot:
   ```
   idle-shutdown status
   idle-shutdown snapshots list --limit 5
   ```
   You should see at least one `Background` snapshot from the last few minutes.
3. Do one **manual restore drill** against a throwaway snapshot to confirm
   Chrome relaunches with the right tabs:
   ```
   idle-shutdown restore <snapshot-id> --dry-run
   idle-shutdown restore <snapshot-id>
   ```

## Flipping to live

```
idle-shutdown settings set DryRun false
idle-shutdown settings set IdleThresholdMinutes 15      # or your preference
idle-shutdown settings set PopupCountdownSeconds 60     # or your preference
```

Restart the service so the new settings are picked up:
```
idle-shutdown stop && idle-shutdown run
```

## Smoke test (real shutdown)

1. Save all open work. Seriously.
2. Lower the threshold for the test only:
   `idle-shutdown settings set IdleThresholdMinutes 2`
3. Walk away from the keyboard for >2 min.
4. Popup appears → let the 60 s countdown expire (do not click).
5. Machine shuts down. Snapshot ID is logged in `%LOCALAPPDATA%\IdleShutdownRestore\Logs\app.log`.
6. Power back on, log in. The crash-recovery banner should **not** appear
   (clean shutdown). The `Restore last session` action should be available
   from the dashboard.
7. Restore. Verify apps + Chrome tabs come back.
8. Reset threshold: `idle-shutdown settings set IdleThresholdMinutes 15`.

## Rollback

If anything misbehaves:
```
idle-shutdown settings set DryRun true
```
No restart needed — `DryRun` is read on every shutdown attempt.

## Known limits (unchanged)

- Unsaved in-app work is the app's responsibility, not ours.
- Window positions / scroll / focus are not restored.
- `ChromeTab.GroupName` is always NULL in this build (deferred — needs SNSS
  tab-group parser with real Windows fixtures).