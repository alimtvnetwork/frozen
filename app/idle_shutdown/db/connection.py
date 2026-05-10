"""Connection helpers + schema initialization."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from idle_shutdown.config import SETTING_DEFS, db_path, ensure_app_dirs
from idle_shutdown.errors import DBNotInitializedError

SCHEMA_RESOURCE = ("idle_shutdown.db", "schema.sql")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _read_schema() -> str:
    pkg, name = SCHEMA_RESOURCE
    return resources.files(pkg).joinpath(name).read_text(encoding="utf-8")


def connect(path: Path | None = None, *, require_initialized: bool = True) -> sqlite3.Connection:
    target = Path(path) if path else db_path()
    if require_initialized and not target.exists():
        raise DBNotInitializedError(
            f"Database not found at {target}. Run: idle-shutdown init-db"
        )
    conn = sqlite3.connect(str(target), isolation_level=None)  # autocommit; we manage txns
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(path: Path | None = None) -> Path:
    """Create the DB file, apply schema, seed lookups + default settings.

    Idempotent: re-running on an initialized DB is a no-op for existing rows.
    Returns the resolved DB path.
    """
    ensure_app_dirs()
    target = Path(path) if path else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.executescript(_read_schema())
        now = utc_now_iso()
        # Seed default settings (idempotent)
        for s in SETTING_DEFS:
            conn.execute(
                "INSERT OR IGNORE INTO Setting (KeyName, Value, UpdatedAt) VALUES (?, ?, ?)",
                (s.key, s.default, now),
            )
        # Seed single-row counter
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM ShutdownCounter"
        ).fetchone()
        if row["c"] == 0:
            conn.execute(
                "INSERT INTO ShutdownCounter (TotalCount, UpdatedAt) VALUES (0, ?)",
                (now,),
            )
    finally:
        conn.close()
    return target