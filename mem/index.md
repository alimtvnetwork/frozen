# Project Memory

## Core
Spec lives in `spec/21-app/`. Implementation lives in `app/` (separate from the TanStack web stack in `src/`). Plan in `plan.md`.
Build phases: 1 done; remaining 2 (monitor+popup), 3 (capture), 4 (shutdown+autostart+restore), 5 (CLI polish + tests).
Locked decisions: PyInstaller frozen .exe; restore skips when same exe + same DocumentPath running; Chrome auto-detect via registry then Program Files, skip if absent; full test plan (unit + integration + manual QA).
Always list remaining tasks at end of each reply; reload from this memory on `next`.

## Memories
- [Phase progress](mem://progress) — which build phase is complete and what comes next
