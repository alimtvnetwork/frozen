"""Filesystem paths, env vars, registry keys, and setting validators.

Single source of truth — mirrors spec/21-app/12-config-and-paths/.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from idle_shutdown.errors import ConfigError, EnvError

APP_DIR_NAME = "IdleShutdownRestore"
DB_FILENAME = "IdleShutdown.db"
LOG_DIR_NAME = "Logs"
LOG_FILENAME = "app.log"
LOCK_FILENAME = "idle-shutdown.lock"
SNAPSHOTS_DIR_NAME = "Snapshots"

REGISTRY_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_RUN_VALUE_NAME = "IdleShutdownRestore"
REGISTRY_CHROME_APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"

SHUTDOWN_COMMAND = ["shutdown.exe", "/s", "/t", "5", "/f", "/c", "Idle auto-shutdown"]
WM_CLOSE_TIMEOUT_SECONDS = 5


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EnvError(f"Required environment variable not set: {name}")
    return value


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        # On non-Windows dev/test machines fall back to XDG-ish path so unit tests run anywhere.
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def db_path() -> Path:
    override = os.environ.get("IDLE_SHUTDOWN_DB")
    if override:
        return Path(override)
    return app_data_dir() / DB_FILENAME


def log_dir() -> Path:
    return app_data_dir() / LOG_DIR_NAME


def log_path() -> Path:
    return log_dir() / LOG_FILENAME


def lock_path() -> Path:
    return app_data_dir() / LOCK_FILENAME


def snapshots_dir() -> Path:
    return app_data_dir() / SNAPSHOTS_DIR_NAME


def ensure_app_dirs() -> None:
    for p in (app_data_dir(), log_dir(), snapshots_dir()):
        p.mkdir(parents=True, exist_ok=True)


def require_localappdata() -> str:
    """Strict check used by ``init-db`` on Windows. Raises EnvError → exit 41."""
    return _require_env("LOCALAPPDATA")


# ----- Setting key registry --------------------------------------------------


def _validate_int_range(low: int, high: int) -> Callable[[str], str]:
    def _v(raw: str) -> str:
        try:
            n = int(raw)
        except (TypeError, ValueError) as e:
            raise ConfigError(f"value must be an integer in {low}..{high}") from e
        if not (low <= n <= high):
            raise ConfigError(f"value must be in {low}..{high}")
        return str(n)

    return _v


def _validate_enum(allowed: tuple[str, ...]) -> Callable[[str], str]:
    def _v(raw: str) -> str:
        if raw not in allowed:
            raise ConfigError(f"value must be one of {allowed}")
        return raw

    return _v


def _validate_bool(raw: str) -> str:
    low = str(raw).lower()
    if low not in ("true", "false"):
        raise ConfigError("value must be 'true' or 'false'")
    return low


def _validate_text(raw: str) -> str:
    return str(raw)


def _validate_iso8601_or_empty(raw: str) -> str:
    if raw == "":
        return raw
    # Strict ISO-8601 check is overkill; accept anything containing 'T' and 'Z'/offset.
    if "T" not in raw:
        raise ConfigError("value must be ISO-8601 UTC or empty")
    return raw


@dataclass(frozen=True)
class SettingDef:
    key: str
    default: str
    validate: Callable[[str], str]
    cast: Callable[[str], object]


SETTING_DEFS: tuple[SettingDef, ...] = (
    # Production defaults (Phase 5 go-live):
    #   - 15 min idle before prompt
    #   - 60 s countdown on popup before auto-shutdown
    SettingDef("IdleThresholdMinutes", "15", _validate_int_range(1, 240), int),
    SettingDef("PopupCountdownSeconds", "60", _validate_int_range(5, 300), int),
    SettingDef("ServiceState", "Enabled",
               _validate_enum(("Enabled", "Disabled")), str),
    SettingDef("AutoRestoreOnBoot", "true", _validate_bool,
               lambda v: v == "true"),
    SettingDef("DryRun", "true", _validate_bool, lambda v: v == "true"),
    SettingDef("GuardMicEnabled", "true", _validate_bool, lambda v: v == "true"),
    SettingDef("GuardAudioEnabled", "true", _validate_bool, lambda v: v == "true"),
    SettingDef("GuardFullscreenEnabled", "true", _validate_bool, lambda v: v == "true"),
    SettingDef("GuardCameraEnabled", "true", _validate_bool, lambda v: v == "true"),
    SettingDef("CaptureChromiumVariants", "false", _validate_bool,
               lambda v: v == "true"),
    SettingDef("SnapshotKeepCount", "50",
               _validate_int_range(1, 10000), int),
    SettingDef("ChromeExecutablePath", "", _validate_text, str),
    SettingDef("LastRestoredSnapshotId", "0", _validate_int_range(0, 2**31 - 1), int),
    SettingDef("LastRestoredAt", "", _validate_iso8601_or_empty, str),
    SettingDef("DisabledUntil", "", _validate_iso8601_or_empty, str),
    SettingDef("FirstRunCompleted", "false", _validate_bool, lambda v: v == "true"),
    # --- Crash-safe background snapshots (Phase A–D) ---
    SettingDef("BackgroundSnapshotsEnabled", "true", _validate_bool,
               lambda v: v == "true"),
    SettingDef("BackgroundSnapshotIntervalMinutes", "5",
               _validate_int_range(1, 60), int),
    SettingDef("BackgroundSnapshotRetentionDays", "7",
               _validate_int_range(1, 365), int),
    SettingDef("CleanShutdown", "true", _validate_bool, lambda v: v == "true"),
    SettingDef("LastHeartbeatAt", "", _validate_iso8601_or_empty, str),
    SettingDef("SnoozeMinutes", "30", _validate_int_range(1, 240), int),
)

SETTINGS_BY_KEY: dict[str, SettingDef] = {s.key: s for s in SETTING_DEFS}


def get_setting_def(key: str) -> SettingDef:
    try:
        return SETTINGS_BY_KEY[key]
    except KeyError as e:
        raise ConfigError(f"unknown setting key: {key}") from e