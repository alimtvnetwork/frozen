# 04d — Shutdown Log & Counter

## Tables
- `ShutdownLog(OccurredAt, SnapshotId nullable, OutcomeStatusId)`
- `ShutdownCounter` — single-row table seeded with `TotalCount=0` at `init-db`.

## Write rules
Every shutdown attempt writes exactly one `ShutdownLog` row, even on failure (`SnapshotId` may be null, `OutcomeStatusId = Failed`).
`ShutdownCounter.TotalCount` increments only on `OutcomeStatusId = Completed`.

## CLI surface
`history` subcommand reads `ShutdownLog` joined to `ShutdownOutcomeStatus`, ordered by `OccurredAt DESC`, paginated.
