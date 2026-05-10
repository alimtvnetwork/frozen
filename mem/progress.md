---
name: Phase progress
description: Current build phase status for the Idle Shutdown utility
type: feature
---
Phase 0 (spec) — done
Phase 0.5 (spec hardening) — done
Phase 1 (skeleton + DB init) — done
Phase 2 (monitor + popup + state machine) — done
Phase 3 (snapshot capture: apps/chrome/desktops + orchestrator + `snapshot` CLI) — done
Phase 4 (shutdown.py WM_CLOSE + locked shutdown.exe; autostart.py HKCU Run install/uninstall; restore.py with duplicate-prevention + idempotency markers; single_instance.py file-lock; wired `run` snapshot+shutdown, `restore`, `install-autostart`, `uninstall-autostart`. 63 unit tests passing.) — done
Phase 5 (build/idle-shutdown.spec, build/version.txt VERSIONINFO, build/build.ps1 reproducible build, build/requirements.lock.README.md generation recipe, ACCEPTANCE.md walking all 11 criteria with code refs + auto vs manual coverage) — done

MVP build complete. All 5 phases shipped.

Phase 5+ stretch shipped:
- Per-desktop restore (lifts criterion 8 gap).
- Inno Setup installer: `app/build/installer.iss` — per-user install,
  optional autostart + init-db tasks, autostart removed on uninstall,
  preserves %APPDATA%\IdleShutdown\ across reinstall. README updated.

Remaining stretch items (only if requested):
- Chrome SNSS parsing → ChromeTab.GroupName (deep work: needs Chromium
  base::Pickle decoder + real-Windows SNSS fixtures to validate; deferred).
- Code signing (needs cert; out of scope).
- Manual Windows x64 QA: run `app/build/build.ps1`, then `ISCC build\installer.iss`,
  then walk `app/ACCEPTANCE.md` Manual column.
