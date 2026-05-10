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

MVP build complete. All 5 phases shipped; 63 unit tests passing.
Remaining work is **manual Windows QA only** (run `app/build/build.ps1` on a
Windows x64 box, then walk `app/ACCEPTANCE.md` Manual column).
On future `next`: nothing pending unless the user reports QA findings or
requests a stretch item (per-desktop restore, Chrome SNSS parsing for
`GroupName`, code signing, installer).
