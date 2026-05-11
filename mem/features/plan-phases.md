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
- Chromium variants (Edge/Brave/Beta/Canary/Chromium) — DONE. Setting `CaptureChromiumVariants` (default false). `ChromeProfile.BrowserName` column with migration. `show` CLI renders Browser column. Variants are captured for inspection only — restore.py still launches primary Chrome with --restore-last-session.
- Camera-in-use ActivityGuard signal — DONE. Setting `GuardCameraEnabled` (default true). macOS: `ioreg -c AppleCamera`. Windows: webcam ConsentStore registry. Linux: `fuser /dev/video*`. Signal name `camera_active`.
- Tray/menu-bar icon — TODO.
- Restore CLI exists (`idle-shutdown restore`); now also launches Chromium variants (Edge/Brave/Chromium/Beta/Canary) via `detect_variant_executable()` with per-OS exe candidates. Each variant launched with `--restore-last-session` + its tab URLs. RestoreResult.variants_launched lists which ones started.
- Snapshot diff — DONE. `idle-shutdown diff <id1> <id2> [--json]`. App identity = (normpath(exe), normpath(doc)); tab identity = (browser_name, profile_dir, url). Indices/titles ignored to avoid noise. Pure helper in `idle_shutdown/diff.py`.
