# Plan — Surviving Unexpected Shutdowns (Power Loss / Crash)

## Problem
Today the app only snapshots when *it* triggers the shutdown (idle → countdown → snapshot → shutdown). If the power cuts, the OS crashes, or the battery dies, **no snapshot is taken**, so on next boot there is nothing to restore. We need the app to continuously keep a "last known good" session on disk so that even a sudden power loss leaves us with something to restore from.

## Goal
After an unexpected shutdown, when the user logs back in, the app:
1. Detects that the previous session ended abnormally (no clean shutdown marker).
2. Offers to restore the most recent **background snapshot** (apps + Chrome tabs across all profiles + virtual desktops).
3. User clicks Restore → same restore path we already have for idle-triggered snapshots.

---

## Phase A — Background snapshots (heartbeat)

Add a low-cost periodic capture so we always have a recent session on disk.

- New setting `BackgroundSnapshotIntervalMinutes` (default `5`, min `1`, max `60`).
- New setting `BackgroundSnapshotsEnabled` (default `true`).
- In `service.py`'s tick loop, every N minutes call the existing `snapshot.capture()` with `TriggerKindId = Background` (new enum value) inside `DryRun=true`-ish mode — i.e. captures and writes to DB but never shuts down.
- Reuse the existing transaction in `snapshot.py`; no schema change required beyond the new enum row.
- Skip the background snapshot if `ActivityGuard.busy` (avoid interrupting a call/movie capture cost) — the previous snapshot is still on disk.
- Log: `event=background_snapshot id=<n> apps=<x> chrome_tabs=<y>`.

## Phase B — Clean-shutdown marker (crash detection)

We need to know on next boot whether the last session ended cleanly.

- On app start: read `Setting('CleanShutdown')`. If value is `false` → previous run crashed.
- Immediately after start, set `Setting('CleanShutdown', 'false')` and `Setting('LastHeartbeatAt', <iso>)`.
- Update `LastHeartbeatAt` every 30 s from the monitor tick (cheap UPDATE).
- On graceful exit (our own shutdown path, Ctrl-C handler, `SIGTERM`/`WM_QUERYENDSESSION`): set `Setting('CleanShutdown', 'true')`.
- On next boot, if `CleanShutdown=false` AND a snapshot exists newer than `LastRestoredSnapshotId` → treat as crash recovery candidate.

This is the same pattern Word/VS Code use for "recovered documents".

## Phase C — Recovery prompt on next launch

- New GUI dialog `RecoveryDialog` shown once on startup when crash detected.
- Shows: "Last session ended unexpectedly at ~HH:MM. Restore N apps and M Chrome tabs?"
- Buttons: **Restore**, **Discard**, **Show details** (lists apps + tab count per Chrome profile, like the existing dry-run popup).
- Restore → existing `restore.run_restore(snapshot_id=latest)` path (already idempotent via duplicate-prevention rule in spec 06).
- Discard → just sets `LastRestoredSnapshotId = latest` so we don't ask again.

## Phase D — Pruning / disk hygiene

Background snapshots every 5 min = ~288/day. Add retention.

- New setting `BackgroundSnapshotRetentionDays` (default `7`).
- On each background capture, delete `Snapshot` rows where `TriggerKindId = Background` AND `CreatedAt < now - retention`. Cascades clean up `AppProcess` / `ChromeWindow` / `ChromeTab` via existing FKs.
- Idle-triggered snapshots are **never** auto-pruned.

## Phase E — Tests

- `test_background_snapshot.py` — fake clock, asserts capture fires every N minutes, skipped while guard busy.
- `test_crash_recovery.py` — seed DB with `CleanShutdown=false` + a snapshot, assert recovery candidate detected; seed with `true`, assert not.
- `test_prune.py` already exists — extend to cover background-only retention.
- `test_clean_shutdown_marker.py` — graceful exit sets flag true; simulated abrupt exit leaves it false.

---

## Limits (be honest with the user)

What we **cannot** recover even with this plan:
- Unsaved work inside apps (Word doc you didn't save, browser form input). That's the app's job, not ours.
- Exact window positions / focus / scroll position — we restore *which* apps and *which* URLs, not pixel state.
- Apps that require a document path we never saw (e.g. a file opened via "Recent" menu after our last heartbeat).

What we **will** recover:
- Every app that was running at the last heartbeat (≤ N minutes old).
- Every Chrome tab across every profile at the last heartbeat.
- Virtual desktop count.

## Settings summary (new)

| Key | Default | Purpose |
|---|---|---|
| `BackgroundSnapshotsEnabled` | `true` | Master switch |
| `BackgroundSnapshotIntervalMinutes` | `5` | Heartbeat capture cadence |
| `BackgroundSnapshotRetentionDays` | `7` | Auto-prune older background snapshots |
| `CleanShutdown` | `true` | Crash-detection flag (managed automatically) |
| `LastHeartbeatAt` | — | Last-known-alive timestamp (managed automatically) |

## Phase order
A → B → C → D → E. Each phase is independently shippable; after A+B you already have the data and the signal, C is just the UI on top.

## Open questions for you
1. Default interval **5 min** OK, or do you want **2 min** (more recent, more disk) / **10 min** (less disk)?
2. On crash recovery, should we **auto-restore silently** or always **prompt** first? I recommend prompt — safer, but louder.
3. Should background snapshots also run while the **activity guard says busy** (call / movie)? Default in this plan: skip. Alternative: still capture (cheap), just don't shut down.
