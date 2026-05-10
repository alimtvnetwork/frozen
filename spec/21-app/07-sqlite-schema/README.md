# 07 — SQLite Schema

## File
`%LOCALAPPDATA%\IdleShutdownRestore\IdleShutdown.db`

## Conventions
- Table names: PascalCase singular (`Snapshot`, not `Snapshots`).
- Primary key: `{TableName}Id INTEGER PRIMARY KEY AUTOINCREMENT`.
- Enum FKs: `SMALLINT` referencing lookup table.
- All `DATETIME` stored as ISO-8601 UTC text.
- `PRAGMA foreign_keys = ON;` set on every connection.
- `PRAGMA journal_mode = WAL;` for crash safety mid-snapshot.

## DDL (authoritative)
```sql
CREATE TABLE SnapshotTriggerKind (
  SnapshotTriggerKindId SMALLINT PRIMARY KEY,
  KindName TEXT NOT NULL UNIQUE
);

CREATE TABLE ShutdownOutcomeStatus (
  ShutdownOutcomeStatusId SMALLINT PRIMARY KEY,
  StatusName TEXT NOT NULL UNIQUE
);

CREATE TABLE Setting (
  SettingId INTEGER PRIMARY KEY AUTOINCREMENT,
  KeyName TEXT NOT NULL UNIQUE,
  Value TEXT NOT NULL,
  UpdatedAt DATETIME NOT NULL
);

CREATE TABLE Snapshot (
  SnapshotId INTEGER PRIMARY KEY AUTOINCREMENT,
  CreatedAt DATETIME NOT NULL,
  TriggerKindId SMALLINT NOT NULL REFERENCES SnapshotTriggerKind
);

CREATE TABLE VirtualDesktop (
  VirtualDesktopId INTEGER PRIMARY KEY AUTOINCREMENT,
  SnapshotId INTEGER NOT NULL REFERENCES Snapshot ON DELETE CASCADE,
  DesktopIndex SMALLINT NOT NULL
);

CREATE TABLE AppProcess (
  AppProcessId INTEGER PRIMARY KEY AUTOINCREMENT,
  VirtualDesktopId INTEGER NOT NULL REFERENCES VirtualDesktop ON DELETE CASCADE,
  ExecutablePath TEXT NOT NULL,
  WorkingDirectory TEXT,
  DocumentPath TEXT
);

CREATE TABLE ChromeWindow (
  ChromeWindowId INTEGER PRIMARY KEY AUTOINCREMENT,
  SnapshotId INTEGER NOT NULL REFERENCES Snapshot ON DELETE CASCADE,
  WindowIndex SMALLINT NOT NULL
);

CREATE TABLE ChromeTab (
  ChromeTabId INTEGER PRIMARY KEY AUTOINCREMENT,
  ChromeWindowId INTEGER NOT NULL REFERENCES ChromeWindow ON DELETE CASCADE,
  TabIndex SMALLINT NOT NULL,
  Url TEXT NOT NULL,
  Title TEXT NOT NULL,
  GroupName TEXT
);

CREATE TABLE ShutdownLog (
  ShutdownLogId INTEGER PRIMARY KEY AUTOINCREMENT,
  OccurredAt DATETIME NOT NULL,
  SnapshotId INTEGER REFERENCES Snapshot ON DELETE SET NULL,
  OutcomeStatusId SMALLINT NOT NULL REFERENCES ShutdownOutcomeStatus
);

CREATE TABLE ShutdownCounter (
  ShutdownCounterId INTEGER PRIMARY KEY AUTOINCREMENT,
  TotalCount INTEGER NOT NULL DEFAULT 0,
  UpdatedAt DATETIME NOT NULL
);

CREATE INDEX IX_Snapshot_CreatedAt ON Snapshot(CreatedAt DESC);
CREATE INDEX IX_ShutdownLog_OccurredAt ON ShutdownLog(OccurredAt DESC);
```

## Seed rows
Inserted by `init-db`, mirroring Python `Enum` values (see `09-enums/`).
- `SnapshotTriggerKind`: (1,'Auto'), (2,'Manual'), (3,'Scheduled')
- `ShutdownOutcomeStatus`: (1,'Completed'), (2,'Cancelled'), (3,'Failed')
- `Setting` defaults: `IdleThresholdMinutes=10`, `PopupCountdownSeconds=30`, `ServiceState=Enabled`, `AutoRestoreOnBoot=true`
- `ShutdownCounter`: single row, `TotalCount=0`

## Migrations
Single `schema.sql` is idempotent (`CREATE TABLE IF NOT EXISTS`). For MVP a hand-cut migration runner is overkill — version is implicit in code. Future: `Setting('SchemaVersion','N')`.
