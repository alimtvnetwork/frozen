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
