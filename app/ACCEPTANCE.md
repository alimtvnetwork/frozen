# Acceptance Criteria — Phase 5 walkthrough

Cross-references `spec/21-app/10-acceptance-criteria/`. For each criterion
below: **Code** = where it is implemented, **Auto** = automated coverage,
**Manual** = the Windows QA step a human must still perform on a real box
(the sandbox is Linux, so anything touching Win32 / Tk / shutdown.exe /
registry must be QA'd on Windows).

| # | Criterion | Code | Auto | Manual |
|---|---|---|---|---|
| 1 | Auto-starts on Windows login | `autostart.py` (`install_autostart` writes `HKCU\...\Run\IdleShutdown`) + CLI `install-autostart` | `tests/unit/test_autostart.py` (registry mocked) | Run `idle-shutdown.exe install-autostart`, sign out / in, confirm process in Task Manager |
| 2 | Idle detected within ±2s of threshold | `monitor.py` 1 Hz tick + `service.py` threshold dispatch | `tests/unit/test_monitor.py`, `test_service.py` | Set `IdleThresholdMinutes=1`, leave idle, time popup |
| 3 | Always-on-top popup with countdown | `popup.py` Tk Toplevel `-topmost`, 250 ms tick | n/a (Tk is not headless-testable here) | Visual: popup is on top, countdown ticks, focus does not steal input from full-screen apps |
| 4 | Yes resets / No or timeout shuts down | `service.py` `IdleService` state machine | `test_service.py` (yes / no / timeout / activity-during-prompt) | Click each button + let it time out |
| 5 | Snapshot captures Chrome tabs, apps (path+cwd or doc), virtual desktops | `snapshot.py` + `capture/{apps,chrome,desktops,snss}.py` (SNSS framing + base::Pickle decoder for `kCommandUpdateTabNavigation`) | `test_snapshot.py`, `test_capture_apps.py`, `test_capture_chrome.py`, `test_snss.py` (synthetic v1 + v3 fixtures) | After `snapshot`, open SQLite, verify rows incl. real Chrome tab URLs/titles. **Remaining sub-gap:** `ChromeTab.GroupName` still NULL — tab-group commands deferred (need real-Windows fixtures). |
| 6 | Counter + timestamped log per shutdown | `db/repos.py` `ShutdownCounterRepo`, `ShutdownLogRepo`; `snapshot.py` records on auto-trigger | `test_settings_repo.py`, `test_snapshot.py` (log row asserted) | Run `run`, force a shutdown path, then `idle-shutdown counter` / `history` |
| 7 | Clean Windows shutdown, no orphans | `shutdown.py` (`WM_CLOSE` 5 s grace then `shutdown.exe /s /t 0 /f`) | `tests/unit/test_shutdown.py` (Win32 calls mocked) | Cold-boot test on Windows; check Event Viewer for clean stop |
| 8 | Restore recreates desktops, relaunches apps, reopens Chrome tabs | `restore.py` + `--restore-last-session` Chrome flag; per-desktop routing via injectable `ensure_desktops` / `switch_to_desktop` / `move_to_desktop` (pyvda defaults) | `tests/unit/test_restore.py` incl. per-desktop switch + move + single-desktop skip | After auto-shutdown, log in, watch restore land each app on its original desktop |
| 9 | SQLite is single source; deleting DB resets | `db/connection.py` `init_db()` + `schema.sql` seeds | `test_init_db.py` | Delete `%APPDATA%\IdleShutdown\state.sqlite`, run `init-db`, `settings show` shows defaults |
| 10 | All CLI commands functional | `cli.py` (init-db, settings show / set-idle / set-countdown, counter, history, run, snapshot, restore, install-autostart, uninstall-autostart, disable, enable) | `test_cli_phase1.py` + every phase's tests | Walk `spec/21-app/08-cli-commands/` table on Windows, confirm exit codes (10, 20, 21, 22, 30, 40, 41, 42) |
| 11 | MVP build stays within 4–5 h | n/a | n/a | Sum phase timestamps in `mem/progress.md` |

## How to run the automated suite

```bash
cd app
python -m pytest -q
```

Current count: **63 unit tests passing** on Linux (Win32-specific code paths
are isolated behind injectable sources / mocks so they still execute).

## How to produce the shipping artifact

On Windows x64:

```powershell
cd app
pwsh -File build\build.ps1
```

Output: `app\dist\idle-shutdown.exe` + a SHA256 line on stdout. Copy the exe
to any folder, then `idle-shutdown.exe install-autostart` once.

### Optional: signed-style installer

After `build.ps1` succeeds, build the per-user installer with Inno Setup 6:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer.iss
```

Output: `app\dist\IdleShutdownSetup-0.1.0.exe`. Installs to
`%LOCALAPPDATA%\Programs\IdleShutdown`, optional autostart + init-db tasks,
removes autostart on uninstall, preserves `%APPDATA%\IdleShutdown\` for
reinstall.

## Documented MVP gaps (accepted)

- `ChromeTab.GroupName` always NULL (tab-group SNSS commands deferred).
- No code signing — SmartScreen warning expected on first launch.