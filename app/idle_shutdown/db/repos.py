"""Repositories — thin SQL wrappers. No business logic."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from idle_shutdown.config import get_setting_def
from idle_shutdown.db.connection import utc_now_iso
from idle_shutdown.enums import ShutdownOutcomeStatus, SnapshotTriggerKind


# ----- Settings --------------------------------------------------------------


@dataclass(frozen=True)
class SettingRow:
    key: str
    value: str
    updated_at: str


class SettingsRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_raw(self, key: str) -> str:
        get_setting_def(key)  # validates key exists
        row = self.conn.execute(
            "SELECT Value FROM Setting WHERE KeyName = ?", (key,)
        ).fetchone()
        if row is None:
            # Should never happen post-init; fall back to default.
            return get_setting_def(key).default
        return str(row["Value"])

    def get(self, key: str) -> Any:
        defn = get_setting_def(key)
        return defn.cast(self.get_raw(key))

    def set(self, key: str, value: Any) -> None:
        defn = get_setting_def(key)
        normalized = defn.validate(str(value))
        self.conn.execute(
            "INSERT INTO Setting (KeyName, Value, UpdatedAt) VALUES (?, ?, ?) "
            "ON CONFLICT(KeyName) DO UPDATE SET Value = excluded.Value, UpdatedAt = excluded.UpdatedAt",
            (key, normalized, utc_now_iso()),
        )

    def all(self) -> list[SettingRow]:
        rows = self.conn.execute(
            "SELECT KeyName, Value, UpdatedAt FROM Setting ORDER BY KeyName"
        ).fetchall()
        return [SettingRow(r["KeyName"], r["Value"], r["UpdatedAt"]) for r in rows]


# ----- Snapshot --------------------------------------------------------------


class SnapshotRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert(self, trigger: SnapshotTriggerKind) -> int:
        cur = self.conn.execute(
            "INSERT INTO Snapshot (CreatedAt, TriggerKindId) VALUES (?, ?)",
            (utc_now_iso(), int(trigger)),
        )
        return int(cur.lastrowid)

    def latest_id(self) -> int | None:
        row = self.conn.execute(
            "SELECT SnapshotId FROM Snapshot ORDER BY SnapshotId DESC LIMIT 1"
        ).fetchone()
        return int(row["SnapshotId"]) if row else None


# ----- Shutdown log + counter -----------------------------------------------


@dataclass(frozen=True)
class ShutdownLogRow:
    log_id: int
    occurred_at: str
    snapshot_id: int | None
    outcome: str


class ShutdownLogRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert(self, snapshot_id: int | None, outcome: ShutdownOutcomeStatus) -> int:
        cur = self.conn.execute(
            "INSERT INTO ShutdownLog (OccurredAt, SnapshotId, OutcomeStatusId) VALUES (?, ?, ?)",
            (utc_now_iso(), snapshot_id, int(outcome)),
        )
        return int(cur.lastrowid)

    def recent(self, limit: int = 20) -> list[ShutdownLogRow]:
        rows = self.conn.execute(
            "SELECT l.ShutdownLogId, l.OccurredAt, l.SnapshotId, s.StatusName "
            "FROM ShutdownLog l "
            "JOIN ShutdownOutcomeStatus s ON s.ShutdownOutcomeStatusId = l.OutcomeStatusId "
            "ORDER BY l.OccurredAt DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            ShutdownLogRow(
                log_id=int(r["ShutdownLogId"]),
                occurred_at=str(r["OccurredAt"]),
                snapshot_id=(int(r["SnapshotId"]) if r["SnapshotId"] is not None else None),
                outcome=str(r["StatusName"]),
            )
            for r in rows
        ]


class ShutdownCounterRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def total(self) -> int:
        row = self.conn.execute(
            "SELECT TotalCount FROM ShutdownCounter ORDER BY ShutdownCounterId LIMIT 1"
        ).fetchone()
        return int(row["TotalCount"]) if row else 0

    def increment(self) -> int:
        self.conn.execute(
            "UPDATE ShutdownCounter SET TotalCount = TotalCount + 1, UpdatedAt = ? "
            "WHERE ShutdownCounterId = (SELECT ShutdownCounterId FROM ShutdownCounter LIMIT 1)",
            (utc_now_iso(),),
        )
        return self.total()


# ----- Capture writes (used by Phase 3) -------------------------------------


class CaptureRepo:
    """Bulk-insert helpers used during snapshot capture transactions."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert_virtual_desktop(self, snapshot_id: int, index: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO VirtualDesktop (SnapshotId, DesktopIndex) VALUES (?, ?)",
            (snapshot_id, index),
        )
        return int(cur.lastrowid)

    def insert_app_process(
        self,
        virtual_desktop_id: int,
        executable_path: str,
        working_directory: str | None,
        document_path: str | None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO AppProcess (VirtualDesktopId, ExecutablePath, WorkingDirectory, DocumentPath) "
            "VALUES (?, ?, ?, ?)",
            (virtual_desktop_id, executable_path, working_directory, document_path),
        )
        return int(cur.lastrowid)

    def insert_chrome_profile(
        self, snapshot_id: int, profile_dir: str, profile_name: str,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO ChromeProfile (SnapshotId, ProfileDir, ProfileName) "
            "VALUES (?, ?, ?)",
            (snapshot_id, profile_dir, profile_name),
        )
        return int(cur.lastrowid)

    def insert_chrome_window(
        self, snapshot_id: int, index: int,
        chrome_profile_id: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO ChromeWindow (SnapshotId, WindowIndex, ChromeProfileId) "
            "VALUES (?, ?, ?)",
            (snapshot_id, index, chrome_profile_id),
        )
        return int(cur.lastrowid)

    def insert_chrome_tabs(
        self,
        chrome_window_id: int,
        tabs: Iterable[tuple[int, str, str, str | None]],
    ) -> None:
        self.conn.executemany(
            "INSERT INTO ChromeTab (ChromeWindowId, TabIndex, Url, Title, GroupName) "
            "VALUES (?, ?, ?, ?, ?)",
            [(chrome_window_id, idx, url, title, group) for (idx, url, title, group) in tabs],
        )