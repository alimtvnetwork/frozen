# 04 — Snapshot Capture (orchestrator)

Captures full session in one SQLite transaction before shutdown. Order:

1. Open transaction.
2. Insert `Snapshot` row (`TriggerKindId`).
3. Capture virtual desktops → insert `VirtualDesktop` rows.
4. Capture running apps → insert `AppProcess` rows linked to desktops.
5. Capture Chrome windows + tabs → insert `ChromeWindow` / `ChromeTab` rows.
6. Insert `ShutdownLog` row referencing the snapshot, with outcome `Completed`.
7. Increment `ShutdownCounter.TotalCount`.
8. Commit.

If any step throws, the whole transaction rolls back and a `ShutdownLog` row with outcome `Failed` is written in a separate transaction so failures are observable.

Sub-areas: `chrome-tabs/`, `running-apps/`, `virtual-desktops/`, `shutdown-log/`.
