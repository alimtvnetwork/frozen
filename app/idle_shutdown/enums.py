"""Authoritative enum values. Lookup tables in SQLite are seeded from these."""
from __future__ import annotations

from enum import Enum, IntEnum


class SnapshotTriggerKind(IntEnum):
    Auto = 1
    Manual = 2
    Scheduled = 3


class ShutdownOutcomeStatus(IntEnum):
    Completed = 1
    Cancelled = 2
    Failed = 3


class ServiceState(str, Enum):
    Enabled = "Enabled"
    Disabled = "Disabled"


class PopupResult(str, Enum):
    Yes = "Yes"
    No = "No"
    Timeout = "Timeout"
    ActivityDuringPrompt = "ActivityDuringPrompt"


class MonitorStateName(str, Enum):
    Idle = "Idle"
    Prompting = "Prompting"
    Snapshotting = "Snapshotting"
    ShuttingDown = "ShuttingDown"