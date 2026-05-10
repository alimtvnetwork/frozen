"""Cross-platform helpers shared by the service code.

Single source of truth for "which OS am I on?" plus a couple of small
factories. Keeps if/elif platform branches out of the higher-level modules.
"""
from __future__ import annotations

import os
import sys
from enum import Enum


class OSKind(str, Enum):
    Windows = "windows"
    MacOS = "macos"
    Linux = "linux"
    Other = "other"


def current_os() -> OSKind:
    if sys.platform == "win32":
        return OSKind.Windows
    if sys.platform == "darwin":
        return OSKind.MacOS
    if sys.platform.startswith("linux"):
        return OSKind.Linux
    return OSKind.Other


def shutdown_command() -> list[str]:
    """Return the locked OS-native shutdown invocation."""
    kind = current_os()
    if kind is OSKind.Windows:
        return ["shutdown.exe", "/s", "/t", "5", "/f", "/c", "Idle auto-shutdown"]
    if kind is OSKind.MacOS:
        # macOS uses BSD shutdown; +1 = 1 minute warning.
        return ["sudo", "shutdown", "-h", "+1", "Idle auto-shutdown"]
    if kind is OSKind.Linux:
        return ["shutdown", "-h", "+1", "Idle auto-shutdown"]
    return ["true"]  # no-op on unknown OS


def is_dry_run_default() -> bool:
    """On non-Windows the shutdown step is dry-run unless explicitly forced.

    Override with env var IDLE_SHUTDOWN_FORCE=1 (force real shutdown) or
    IDLE_SHUTDOWN_DRY_RUN=0 / =1 to set explicitly.
    """
    explicit = os.environ.get("IDLE_SHUTDOWN_DRY_RUN")
    if explicit is not None:
        return explicit not in ("0", "false", "False", "")
    if os.environ.get("IDLE_SHUTDOWN_FORCE") in ("1", "true", "True"):
        return False
    return current_os() is not OSKind.Windows
