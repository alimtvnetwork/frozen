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
Phase 5 (CLI polish + output column contracts double-check; build/idle-shutdown.spec for PyInstaller; build/version.txt VERSIONINFO; build/build.ps1 reproducible build script; requirements.lock recipe; walk all 11 acceptance criteria; final spec audit) — todo
On `next`, advance Phase 5.
