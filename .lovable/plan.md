
# Plan — Dry-run idle detector + multi-profile Chrome capture

Goal for now: prove the full pipeline works end-to-end **without actually shutting anything down**. Detect idle → ignore if you're in a call / watching a video → ask for 10 seconds → if no answer, snapshot all open apps + Chrome tabs (across every Chrome profile) into the DB and show a "would shut down now" popup. Nothing closes, nothing reboots.

Phases are ordered so you can stop after any one and still have a working app.

---

## Phase 1 — Dry-run mode + 10s popup (smallest useful slice)

Make the existing `run` loop completely safe to leave on:

- Add a `DryRun` setting (default `true` for now). When true, `_take_snapshot_and_shutdown` takes the snapshot and shows a **"Would shut down now"** info popup instead of calling `execute_shutdown()`. No `shutdown` / `osascript` / `systemctl` is ever invoked.
- Change default `PopupCountdownSeconds` from 5 → **10**.
- Popup now lists what *would* be saved: app count, Chrome window/tab count, snapshot id — so you can verify visually.
- New CLI: `idle-shutdown run --dry-run` flag (overrides setting for one run).

Acceptance: leave `./run.sh run` going, walk away, come back to a popup listing your apps + tab count. DB has a new snapshot row. System is untouched.

---

## Phase 2 — Activity guard (mic / audio / fullscreen video)

Suppress the "are you idle?" check when you're clearly busy. A new `ActivityGuard` module returns `busy=true` if **any** of these hold; `IdleMonitor.tick` skips firing `on_threshold` while busy.

Signals (all best-effort, each one independently skippable):
- **Microphone in use** — macOS: read `tccutil`/CoreAudio `AudioObjectGetPropertyData` for input device "is running" flag (via pyobjc `CoreAudio`). Windows: query `IAudioSessionManager2` for any active capture session. Linux: `pactl list source-outputs`.
- **Audio playback active** — same APIs, render side. Catches Spotify, YouTube, Zoom playback.
- **Fullscreen window** — macOS: `NSWorkspace` active app + `kCGWindowIsOnscreen` bounds == screen bounds. Windows: `GetForegroundWindow` + compare rect to monitor rect. Covers movies / fullscreen YouTube / games.
- **Camera in use** (bonus, cheap on macOS via the same CoreMediaIO path).

Each signal is wrapped so a missing dependency just disables that signal — never crashes the loop. New settings: `GuardMicEnabled`, `GuardAudioEnabled`, `GuardFullscreenEnabled` (all default `true`).

Logged once per state change: `event=activity_guard busy=true reason=mic_active`.

---

## Phase 3 — Multi-profile Chrome capture

Today `capture/chrome.py` only reads the `Default` profile. Real users have `Profile 1`, `Profile 2`, "Work", "Personal" etc., plus the whole Chrome **Beta** / **Canary** install.

Approach:
1. Read Chrome's `Local State` JSON (sibling of `Default/`) — it contains `profile.info_cache` mapping each profile dir → human name (e.g. `"Profile 1" → "Work"`).
2. For each profile dir, parse its own `Sessions/` folder with the existing SNSS reader.
3. Schema additions (one migration, additive only — won't break existing DB):
   - `ChromeProfile(ChromeProfileId PK, SnapshotId FK, ProfileDir TEXT, ProfileName TEXT)`
   - `ChromeWindow.ChromeProfileId` nullable FK (old rows stay valid).
4. Snapshot output now reads `chrome_profiles=2 chrome_windows=5 chrome_tabs=143`.
5. Same loop optionally walks Chrome Beta / Edge / Brave user-data dirs (gated by `CaptureChromiumVariants` setting, default `false` for now).

Open question for you: do you want each profile's tabs treated as **one combined list**, or kept **grouped per profile** in the eventual UI? (Schema supports both; this only changes how we display.)

---

## Phase 4 — Inspector view (sanity check what got saved)

A read-only CLI to eyeball the latest snapshot without writing SQL:
- `idle-shutdown show` → prints latest snapshot summary (apps with paths, profiles, windows, tabs with URL+title) as a Rich table.
- `idle-shutdown show --snapshot-id N` for a specific one.
- `idle-shutdown show --json` for piping.

This is the "did it really save what I think it saved?" command.

---

## Phase 5 (deferred — flip the switch later)

When you're ready to go live: set `DryRun=false`, raise countdown back to your real value, optionally add a "Snooze 30 min" button to the popup. No code changes needed beyond toggling the setting and re-enabling `execute_shutdown()` from Phase 1.

---

## Technical notes (skip if not interested)

- All new settings live in `Setting` table via existing `SettingsRepo` — no new infra.
- Schema migration in Phase 3 is additive (`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN` guarded by a `PRAGMA table_info` check) so existing snapshots 17–21 keep working.
- Activity guard runs on the same 1 Hz tick as `IdleMonitor`; cost is ~one syscall per signal per second.
- Multi-profile capture reuses `_iter_commands` / `read_snss_file` from `capture/snss.py` unchanged — only the directory enumeration changes.
- Tests: each phase ships with unit tests using fakes (mock mic state, fake `Local State` JSON, fake SNSS files) so nothing depends on a real Chrome being installed.

---

## Questions before I start

1. **Phase order OK?** Suggest doing **Phase 1 first** (safest, immediate value), then Phase 3 (multi-profile — directly answers your Chrome accounts question), then Phase 2 (guard).
2. **Multi-profile display:** combined list or grouped per profile name?
3. **Other Chromium browsers** (Edge, Brave, Chrome Beta) — care about them now, or Chrome only?

Tell me which phase to execute and I'll ship it.
