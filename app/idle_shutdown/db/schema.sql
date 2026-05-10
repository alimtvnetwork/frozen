-- Idle Shutdown & Session Restore — authoritative schema.
-- Mirrors spec/21-app/07-sqlite-schema/. Idempotent: safe to re-run.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS SnapshotTriggerKind (
  SnapshotTriggerKindId INTEGER PRIMARY KEY,
  KindName TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS ShutdownOutcomeStatus (
  ShutdownOutcomeStatusId INTEGER PRIMARY KEY,
  StatusName TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS Setting (
  SettingId INTEGER PRIMARY KEY AUTOINCREMENT,
  KeyName TEXT NOT NULL UNIQUE,
  Value TEXT NOT NULL,
  UpdatedAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Snapshot (
  SnapshotId INTEGER PRIMARY KEY AUTOINCREMENT,
  CreatedAt TEXT NOT NULL,
  TriggerKindId INTEGER NOT NULL REFERENCES SnapshotTriggerKind(SnapshotTriggerKindId)
);

CREATE TABLE IF NOT EXISTS VirtualDesktop (
  VirtualDesktopId INTEGER PRIMARY KEY AUTOINCREMENT,
  SnapshotId INTEGER NOT NULL REFERENCES Snapshot(SnapshotId) ON DELETE CASCADE,
  DesktopIndex INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS AppProcess (
  AppProcessId INTEGER PRIMARY KEY AUTOINCREMENT,
  VirtualDesktopId INTEGER NOT NULL REFERENCES VirtualDesktop(VirtualDesktopId) ON DELETE CASCADE,
  ExecutablePath TEXT NOT NULL,
  WorkingDirectory TEXT,
  DocumentPath TEXT
);

CREATE TABLE IF NOT EXISTS ChromeWindow (
  ChromeWindowId INTEGER PRIMARY KEY AUTOINCREMENT,
  SnapshotId INTEGER NOT NULL REFERENCES Snapshot(SnapshotId) ON DELETE CASCADE,
  WindowIndex INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ChromeTab (
  ChromeTabId INTEGER PRIMARY KEY AUTOINCREMENT,
  ChromeWindowId INTEGER NOT NULL REFERENCES ChromeWindow(ChromeWindowId) ON DELETE CASCADE,
  TabIndex INTEGER NOT NULL,
  Url TEXT NOT NULL,
  Title TEXT NOT NULL,
  GroupName TEXT
);

CREATE TABLE IF NOT EXISTS ShutdownLog (
  ShutdownLogId INTEGER PRIMARY KEY AUTOINCREMENT,
  OccurredAt TEXT NOT NULL,
  SnapshotId INTEGER REFERENCES Snapshot(SnapshotId) ON DELETE SET NULL,
  OutcomeStatusId INTEGER NOT NULL REFERENCES ShutdownOutcomeStatus(ShutdownOutcomeStatusId)
);

CREATE TABLE IF NOT EXISTS ShutdownCounter (
  ShutdownCounterId INTEGER PRIMARY KEY AUTOINCREMENT,
  TotalCount INTEGER NOT NULL DEFAULT 0,
  UpdatedAt TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS IX_Snapshot_CreatedAt ON Snapshot(CreatedAt DESC);
CREATE INDEX IF NOT EXISTS IX_ShutdownLog_OccurredAt ON ShutdownLog(OccurredAt DESC);

-- Lookup seeds (idempotent)
INSERT OR IGNORE INTO SnapshotTriggerKind (SnapshotTriggerKindId, KindName) VALUES
  (1, 'Auto'), (2, 'Manual'), (3, 'Scheduled');

INSERT OR IGNORE INTO ShutdownOutcomeStatus (ShutdownOutcomeStatusId, StatusName) VALUES
  (1, 'Completed'), (2, 'Cancelled'), (3, 'Failed');