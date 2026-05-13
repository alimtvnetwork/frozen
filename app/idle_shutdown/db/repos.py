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

    def prune(self, keep: int) -> int:
        """Delete all but the most recent ``keep`` snapshots.

        Children (VirtualDesktop, AppProcess, ChromeProfile, ChromeWindow,
        ChromeTab) cascade via FK ON DELETE CASCADE. ShutdownLog rows have
        ON DELETE SET NULL on SnapshotId, so log history is preserved.
        Returns the number of Snapshot rows deleted.
        """
        if keep < 1:
            raise ValueError("keep must be >= 1")
        cur = self.conn.execute(
            "DELETE FROM Snapshot WHERE SnapshotId NOT IN ("
            "  SELECT SnapshotId FROM Snapshot "
            "  ORDER BY SnapshotId DESC LIMIT ?"
            ")",
            (keep,),
        )
        return cur.rowcount or 0

    def prune_background_older_than(self, retention_days: int) -> int:
        """Delete Background snapshots older than ``retention_days`` days.

        Other trigger kinds (Auto, Manual, Scheduled) are never touched here.
        Returns rows deleted. Children cascade via FK.
        """
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1")
        from idle_shutdown.enums import SnapshotTriggerKind
        cur = self.conn.execute(
            "DELETE FROM Snapshot "
            "WHERE TriggerKindId = ? "
            "  AND CreatedAt < datetime('now', ?)",
            (int(SnapshotTriggerKind.Background), f"-{int(retention_days)} days"),
        )
        return cur.rowcount or 0


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
        browser_name: str = "Chrome",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO ChromeProfile (SnapshotId, ProfileDir, ProfileName, BrowserName) "
            "VALUES (?, ?, ?, ?)",
            (snapshot_id, profile_dir, profile_name, browser_name),
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


# ----- Snapshot reads (used by `idle-shutdown show`) ------------------------


@dataclass(frozen=True)
class AppRow:
    executable_path: str
    working_directory: str | None
    document_path: str | None
    desktop_index: int


@dataclass(frozen=True)
class TabRow:
    profile_dir: str | None
    profile_name: str | None
    window_index: int
    tab_index: int
    url: str
    title: str
    browser_name: str | None = None


@dataclass(frozen=True)
class SnapshotDetail:
    snapshot_id: int
    created_at: str
    trigger: str
    desktop_count: int
    apps: list[AppRow]
    tabs: list[TabRow]
    profile_summary: list[tuple[str, str, int, str]]
    # (profile_dir, profile_name, tab_count, browser_name)


class SnapshotReadRepo:
    """Read-only queries for the inspector CLI."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def latest_id(self) -> int | None:
        row = self.conn.execute(
            "SELECT SnapshotId FROM Snapshot ORDER BY SnapshotId DESC LIMIT 1"
        ).fetchone()
        return int(row["SnapshotId"]) if row else None

    def get_detail(self, snapshot_id: int) -> SnapshotDetail | None:
        head = self.conn.execute(
            "SELECT s.SnapshotId, s.CreatedAt, t.KindName "
            "FROM Snapshot s "
            "JOIN SnapshotTriggerKind t ON t.SnapshotTriggerKindId = s.TriggerKindId "
            "WHERE s.SnapshotId = ?",
            (snapshot_id,),
        ).fetchone()
        if head is None:
            return None

        desktop_count = int(self.conn.execute(
            "SELECT COUNT(*) AS c FROM VirtualDesktop WHERE SnapshotId = ?",
            (snapshot_id,),
        ).fetchone()["c"])

        apps = [
            AppRow(
                executable_path=str(r["ExecutablePath"]),
                working_directory=(r["WorkingDirectory"]),
                document_path=(r["DocumentPath"]),
                desktop_index=int(r["DesktopIndex"]),
            )
            for r in self.conn.execute(
                "SELECT a.ExecutablePath, a.WorkingDirectory, a.DocumentPath, "
                "       d.DesktopIndex "
                "FROM AppProcess a "
                "JOIN VirtualDesktop d ON d.VirtualDesktopId = a.VirtualDesktopId "
                "WHERE d.SnapshotId = ? "
                "ORDER BY d.DesktopIndex, a.AppProcessId",
                (snapshot_id,),
            ).fetchall()
        ]

        tabs = [
            TabRow(
                profile_dir=(r["ProfileDir"]),
                profile_name=(r["ProfileName"]),
                window_index=int(r["WindowIndex"]),
                tab_index=int(r["TabIndex"]),
                url=str(r["Url"]),
                title=str(r["Title"]),
                browser_name=(r["BrowserName"]),
            )
            for r in self.conn.execute(
                "SELECT p.ProfileDir, p.ProfileName, p.BrowserName, w.WindowIndex, "
                "       t.TabIndex, t.Url, t.Title "
                "FROM ChromeTab t "
                "JOIN ChromeWindow w ON w.ChromeWindowId = t.ChromeWindowId "
                "LEFT JOIN ChromeProfile p ON p.ChromeProfileId = w.ChromeProfileId "
                "WHERE w.SnapshotId = ? "
                "ORDER BY p.BrowserName, p.ProfileDir, w.WindowIndex, t.TabIndex",
                (snapshot_id,),
            ).fetchall()
        ]

        profile_summary = [
            (str(r["ProfileDir"]), str(r["ProfileName"]),
             int(r["TabCount"]), str(r["BrowserName"]))
            for r in self.conn.execute(
                "SELECT p.ProfileDir, p.ProfileName, p.BrowserName, "
                "       COUNT(t.ChromeTabId) AS TabCount "
                "FROM ChromeProfile p "
                "LEFT JOIN ChromeWindow w ON w.ChromeProfileId = p.ChromeProfileId "
                "LEFT JOIN ChromeTab t ON t.ChromeWindowId = w.ChromeWindowId "
                "WHERE p.SnapshotId = ? "
                "GROUP BY p.ChromeProfileId "
                "ORDER BY p.ChromeProfileId",
                (snapshot_id,),
            ).fetchall()
        ]

        return SnapshotDetail(
            snapshot_id=int(head["SnapshotId"]),
            created_at=str(head["CreatedAt"]),
            trigger=str(head["KindName"]),
            desktop_count=desktop_count,
            apps=apps,
            tabs=tabs,
            profile_summary=profile_summary,
        )