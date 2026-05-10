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
from idle_shutdown.platform import OSKind, current_os

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

    # macOS / Linux fallbacks. Tests inject deterministic ``exists`` so these
    # extra candidates are harmless on Windows.
    if current_os() is OSKind.MacOS:
        candidates += [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    elif current_os() is OSKind.Linux:
        candidates += [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]

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

    sessions_root, sessions_dir = _chrome_user_data_paths(exe, e)
    if not sessions_root:
        logger.warning("event=chrome_not_detected reason=missing_user_data")
        return ChromeSession(executable_path=exe, windows=())
    if not exists(sessions_root):
        logger.warning("event=chrome_not_detected reason=missing_user_data")
        return ChromeSession(executable_path=exe, windows=())

    if snss_reader is None:
        from idle_shutdown.capture.snss import default_snss_reader
        snss_reader = default_snss_reader
    try:
        windows = snss_reader(Path(sessions_dir))
        return ChromeSession(executable_path=exe, windows=tuple(windows))
    except Exception as ex:  # noqa: BLE001
        logger.warning("event=chrome_snss_failed err=%s", ex)
        return ChromeSession(executable_path=exe, windows=())


def _chrome_user_data_paths(exe: str, e: dict[str, str]) -> tuple[str | None, str | None]:
    """Return ``(profile_root, sessions_dir)`` for the current OS or
    ``(None, None)`` if the user-data dir cannot be determined."""
    # Windows path inferred from LOCALAPPDATA (preserves prior behavior even
    # if ``exe`` came from a non-Windows fallback — tests inject env).
    win_local = e.get("LOCALAPPDATA")
    if win_local:
        root = _WIN_SEP.join([win_local, "Google", "Chrome", "User Data", "Default"])
        return root, root + _WIN_SEP + "Sessions"
    kind = current_os()
    home = e.get("HOME") or os.path.expanduser("~")
    if kind is OSKind.MacOS:
        root = os.path.join(home, "Library", "Application Support", "Google", "Chrome", "Default")
        return root, os.path.join(root, "Sessions")
    if kind is OSKind.Linux:
        # Try google-chrome first, then chromium.
        for sub in ("google-chrome", "chromium"):
            root = os.path.join(home, ".config", sub, "Default")
            if os.path.exists(root):
                return root, os.path.join(root, "Sessions")
        # Default guess (won't exist → caller logs missing_user_data).
        root = os.path.join(home, ".config", "google-chrome", "Default")
        return root, os.path.join(root, "Sessions")
    return None, None