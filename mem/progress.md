---
name: Phase progress
description: Current build phase status for the Idle Shutdown utility
type: feature
---
Phase 0 (spec) — done
Phase 0.5 (spec hardening) — done
Phase 1 (project skeleton + DB init; 16 tests) — done
Phase 2 (monitor + popup + state machine; +13 tests = 29) — done
Phase 3 (capture/desktops, capture/apps, capture/chrome, snapshot orchestrator with rollback, `snapshot` CLI wired; +16 tests = 45 passing) — done
Phase 4 (shutdown.py WM_CLOSE+shutdown.exe; autostart.py HKCU Run install/uninstall; restore.py with duplicate-prevention rule + idempotency markers; wire `restore`, `install-autostart`, `uninstall-autostart` CLIs; single-instance lock for `run`/`restore`) — todo
Phase 5 (final CLI polish + output column contracts; build/idle-shutdown.spec + version.txt for PyInstaller; requirements.lock recipe; walk 11 acceptance criteria) — todo
On `next`, advance the lowest-numbered todo phase.
