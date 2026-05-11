---
name: Plan phases
description: Implementation phases for the idle-shutdown dry-run + multi-profile feature set
type: feature
---
Source plan: .lovable/plan.md

- Phase 1 — Dry-run + 10s popup. DONE. Settings: DryRun, PopupCountdownSeconds default 10.
- Phase 2 — ActivityGuard (mic/audio/fullscreen). DONE. Settings: GuardMicEnabled/AudioEnabled/FullscreenEnabled.
- Phase 3 — Multi-profile Chrome capture (ChromeProfile table + ChromeWindow.ChromeProfileId). DONE.
- Phase 4 — `idle-shutdown show` inspector CLI. DONE.
- Phase 5 — Flip DryRun off + add Snooze button. DEFERRED until user says go-live.

Follow-ups:
- Auto-prune snapshots — DONE. Setting `SnapshotKeepCount` (default 50, range 1..10000); runs after every commit; manual `idle-shutdown prune [--keep N]`. ShutdownLog rows preserved (FK SET NULL).
- Chromium variants (Edge/Brave/Beta/Canary) — TODO.
- Camera-in-use ActivityGuard signal — TODO.
- Tray/menu-bar icon — TODO.
- Restore CLI already exists (`idle-shutdown restore`).
