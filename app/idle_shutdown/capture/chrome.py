"""Chrome detection + tab capture.

MVP: detect ``chrome.exe`` via registry → Program Files → LOCALAPPDATA. If
the executable or the user-data directory is absent, capture is a clean
no-op with one warning log line. SNSS parsing is best-effort and can be
swapped later; for the MVP we always rely on Chrome's own
``--restore-last-session`` and store an empty tab list when SNSS is
unavailable. Existing rows are still useful for the history view.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Force Windows-style paths in candidate strings so tests are deterministic on
# any host. On Windows ``os.sep`` is already ``\\``; on POSIX we still emit
# ``\\`` because Chrome paths are inherently Windows.
_WIN_SEP = "\\"

from idle_shutdown.config import REGISTRY_CHROME_APP_PATHS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChromeTabInfo:
    url: str
    title: str
    group: str | None = None


@dataclass(frozen=True)
class ChromeWindowInfo:
    tabs: tuple[ChromeTabInfo, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ChromeSession:
    executable_path: str | None
    windows: tuple[ChromeWindowInfo, ...] = field(default_factory=tuple)


RegRead = Callable[[str, str, str], str | None]


def _default_reg_read(hive: str, subkey: str, value_name: str) -> str | None:  # pragma: no cover
    if sys.platform != "win32":
        return None
    import winreg  # type: ignore
    hive_h = getattr(winreg, hive)
    try:
        with winreg.OpenKey(hive_h, subkey) as k:
            data, _ = winreg.QueryValueEx(k, value_name)
            return str(data) if data else None
    except OSError:
        return None


def detect_chrome_path(
    *,
    reg_read: RegRead | None = None,
    env: dict[str, str] | None = None,
    exists: Callable[[str], bool] = os.path.exists,
) -> str | None:
    """Resolve ``chrome.exe`` per the locked detection order."""
    rr = reg_read or _default_reg_read
    e = env if env is not None else dict(os.environ)

    candidates: list[str | None] = [
        rr("HKEY_LOCAL_MACHINE", REGISTRY_CHROME_APP_PATHS, ""),
        rr("HKEY_CURRENT_USER", REGISTRY_CHROME_APP_PATHS, ""),
    ]
    for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = e.get(env_var)
        if base:
            candidates.append(_WIN_SEP.join([base, "Google", "Chrome", "Application", "chrome.exe"]))

    for c in candidates:
        if c and exists(c):
            return c
    return None


def capture_chrome_session(
    *,
    reg_read: RegRead | None = None,
    env: dict[str, str] | None = None,
    exists: Callable[[str], bool] = os.path.exists,
    snss_reader: Callable[[Path], list[ChromeWindowInfo]] | None = None,
) -> ChromeSession:
    e = env if env is not None else dict(os.environ)
    exe = detect_chrome_path(reg_read=reg_read, env=e, exists=exists)
    if not exe:
        logger.warning("event=chrome_not_detected reason=missing_exe")
        return ChromeSession(executable_path=None, windows=())

    user_data_root = e.get("LOCALAPPDATA")
    if not user_data_root:
        logger.warning("event=chrome_not_detected reason=missing_user_data")
        return ChromeSession(executable_path=exe, windows=())
    sessions_root = _WIN_SEP.join(
        [user_data_root, "Google", "Chrome", "User Data", "Default"]
    )
    sessions_dir = sessions_root + _WIN_SEP + "Sessions"
    if not exists(sessions_root):
        logger.warning("event=chrome_not_detected reason=missing_user_data")
        return ChromeSession(executable_path=exe, windows=())

    if snss_reader is None:
        # MVP: empty tab list; restore relies on Chrome's --restore-last-session.
        return ChromeSession(executable_path=exe, windows=())
    try:
        windows = snss_reader(Path(sessions_dir))
        return ChromeSession(executable_path=exe, windows=tuple(windows))
    except Exception as ex:  # noqa: BLE001
        logger.warning("event=chrome_snss_failed err=%s", ex)
        return ChromeSession(executable_path=exe, windows=())