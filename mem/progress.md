---
name: Phase progress
description: Current build phase status for the Idle Shutdown utility
type: feature
---
Phase 0 (spec) — done
Phase 0.5 (spec hardening) — done
Phase 1 (project skeleton + DB init + 16 tests) — done
Phase 2 (monitor + popup + state machine + 13 new tests; total 29 passing; `run` CLI wired but snapshot+shutdown placeholder) — done
Phase 3 (snapshot capture: apps, Chrome, desktops; transactional orchestrator; wire `snapshot` CLI) — todo
Phase 4 (shutdown sequence WM_CLOSE + shutdown.exe; HKCU autostart install/uninstall; restore with duplicate-prevention; wire those CLIs) — todo
Phase 5 (final CLI polish, output column contracts, build/idle-shutdown.spec PyInstaller config + version.txt, walk 11 acceptance criteria) — todo
On `next`, advance the lowest-numbered todo phase.
