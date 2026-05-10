# 09 — Enums

Python `Enum` values are the authoritative ID set. Lookup tables in SQLite are seeded from these enums at `init-db`. Code must never use raw integers when an enum exists.

```python
class SnapshotTriggerKind(IntEnum):
    Auto      = 1
    Manual    = 2
    Scheduled = 3

class ShutdownOutcomeStatus(IntEnum):
    Completed = 1
    Cancelled = 2
    Failed    = 3

class ServiceState(Enum):
    Enabled  = "Enabled"
    Disabled = "Disabled"
```

`ServiceState` is stored as text in the `Setting` row, not a lookup table — it is a single-valued setting, not a foreign key.

## Smallest viable types
Lookup table PKs are `SMALLINT`. Enum FKs in fact tables are `SMALLINT`. Do not widen.

## Sync rule
Adding an enum value requires:
1. Update the Python `IntEnum`.
2. Add a seed `INSERT OR IGNORE` line in `db/schema.sql`.
3. Add a row to the matching table in `07-sqlite-schema/README.md`.
