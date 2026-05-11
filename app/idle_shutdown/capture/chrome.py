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
import json

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
class ChromeProfileInfo:
    profile_dir: str            # raw directory name (e.g. "Default", "Profile 1")
    profile_name: str           # human label from Local State; falls back to profile_dir
    windows: tuple[ChromeWindowInfo, ...] = field(default_factory=tuple)
    browser_name: str = "Chrome"


@dataclass(frozen=True)
class ChromeSession:
    executable_path: str | None
    profiles: tuple[ChromeProfileInfo, ...] = field(default_factory=tuple)

    @property
    def windows(self) -> tuple[ChromeWindowInfo, ...]:
        """Flat list of every window across every profile (compat shim)."""
        out: list[ChromeWindowInfo] = []
        for p in self.profiles:
            out.extend(p.windows)
        return tuple(out)


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
    read_text: Callable[[str], str | None] | None = None,
    list_dir: Callable[[str], list[str]] | None = None,
    include_variants: bool = False,
) -> ChromeSession:
    e = env if env is not None else dict(os.environ)
    exe = detect_chrome_path(reg_read=reg_read, env=e, exists=exists)
    if not exe:
        logger.warning("event=chrome_not_detected reason=missing_exe")
        # Variants may still exist (e.g. Edge-only Windows machine).
        primary: list[ChromeProfileInfo] = []
    else:
        user_data_root = _chrome_user_data_root(exe, e)
        if user_data_root and exists(user_data_root):
            primary = _capture_profiles_for(
                user_data_root, "Chrome",
                exists=exists, snss_reader=snss_reader,
                read_text=read_text, list_dir=list_dir,
            )
        else:
            logger.warning("event=chrome_not_detected reason=missing_user_data")
            primary = []

    profiles: list[ChromeProfileInfo] = list(primary)

    if include_variants:
        for variant in _enumerate_chromium_variants(e):
            if not exists(variant.user_data_root):
                continue
            profiles.extend(_capture_profiles_for(
                variant.user_data_root, variant.browser_name,
                exists=exists, snss_reader=snss_reader,
                read_text=read_text, list_dir=list_dir,
            ))

    return ChromeSession(executable_path=exe, profiles=tuple(profiles))


def _capture_profiles_for(
    user_data_root: str,
    browser_name: str,
    *,
    exists: Callable[[str], bool],
    snss_reader: Callable[[Path], list[ChromeWindowInfo]] | None,
    read_text: Callable[[str], str | None] | None,
    list_dir: Callable[[str], list[str]] | None,
) -> list[ChromeProfileInfo]:
    if snss_reader is None:
        from idle_shutdown.capture.snss import default_snss_reader
        snss_reader = default_snss_reader

    profile_names = _read_profile_names(user_data_root, read_text=read_text)
    profile_dirs = _list_profile_dirs(user_data_root, exists=exists, list_dir=list_dir)
    out: list[ChromeProfileInfo] = []
    for pdir in profile_dirs:
        sessions = os.path.join(user_data_root, pdir, "Sessions")
        try:
            windows = snss_reader(Path(sessions)) if exists(sessions) else []
        except Exception as ex:  # noqa: BLE001
            logger.warning("event=chrome_snss_failed browser=%s profile=%s err=%s",
                           browser_name, pdir, ex)
            windows = []
        if not windows:
            continue
        out.append(ChromeProfileInfo(
            profile_dir=pdir,
            profile_name=profile_names.get(pdir, pdir),
            windows=tuple(windows),
            browser_name=browser_name,
        ))
    return out


# ---------- profile discovery ----------------------------------------------


def _read_profile_names(
    user_data_root: str,
    *,
    read_text: Callable[[str], str | None] | None = None,
) -> dict[str, str]:
    """Parse ``Local State`` JSON. Returns ``{profile_dir: human_name}``."""
    rt = read_text or _default_read_text
    raw = rt(os.path.join(user_data_root, "Local State"))
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        cache = ((data.get("profile") or {}).get("info_cache")) or {}
        return {str(k): str(v.get("name") or k) for k, v in cache.items()}
    except (ValueError, AttributeError) as ex:
        logger.warning("event=chrome_local_state_unparseable err=%s", ex)
        return {}


def _default_read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _list_profile_dirs(
    user_data_root: str,
    *,
    exists: Callable[[str], bool] = os.path.exists,
    list_dir: Callable[[str], list[str]] | None = None,
) -> list[str]:
    """Return profile directory names under ``user_data_root``.

    Always includes ``Default`` first (if present), then ``Profile N`` dirs in
    numeric order. Unknown sibling directories are ignored.
    """
    ld = list_dir or _default_list_dir
    try:
        entries = ld(user_data_root)
    except OSError:
        entries = []
    out: list[str] = []
    if "Default" in entries and exists(os.path.join(user_data_root, "Default")):
        out.append("Default")
    profiles = sorted(
        (e for e in entries if e.startswith("Profile ")),
        key=lambda n: _profile_sort_key(n),
    )
    for p in profiles:
        if exists(os.path.join(user_data_root, p)):
            out.append(p)
    return out


def _profile_sort_key(name: str) -> int:
    try:
        return int(name.split(" ", 1)[1])
    except (IndexError, ValueError):
        return 1 << 30


def _default_list_dir(path: str) -> list[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []


def _chrome_user_data_root(exe: str, e: dict[str, str]) -> str | None:
    """Return the Chrome ``User Data`` directory (parent of profile dirs)
    for the current OS, or ``None`` if it cannot be determined."""
    kind = current_os()
    if kind is OSKind.Windows:
        win_local = e.get("LOCALAPPDATA")
        if win_local:
            return _WIN_SEP.join([win_local, "Google", "Chrome", "User Data"])
        return None
    home = e.get("HOME") or os.path.expanduser("~")
    if kind is OSKind.MacOS:
        return os.path.join(home, "Library", "Application Support", "Google", "Chrome")
    if kind is OSKind.Linux:
        for sub in ("google-chrome", "chromium"):
            root = os.path.join(home, ".config", sub)
            if os.path.exists(root):
                return root
        return os.path.join(home, ".config", "google-chrome")
    win_local = e.get("LOCALAPPDATA")
    if win_local:
        return _WIN_SEP.join([win_local, "Google", "Chrome", "User Data"])
    return None


# ---------- Chromium variants (Edge, Brave, Chrome Beta/Canary, Chromium) ---


@dataclass(frozen=True)
class ChromiumVariant:
    browser_name: str
    user_data_root: str


def _enumerate_chromium_variants(e: dict[str, str]) -> list[ChromiumVariant]:
    """Return user-data roots for known Chromium-based browsers.

    Only path candidates that are non-empty strings are returned; existence
    check is done by the caller so test fakes can decide.
    """
    kind = current_os()
    home = e.get("HOME") or os.path.expanduser("~")
    win_local = e.get("LOCALAPPDATA")

    def _join_win(*parts: str) -> str:
        return _WIN_SEP.join(parts)

    out: list[ChromiumVariant] = []

    def _add(name: str, path: str | None) -> None:
        if path:
            out.append(ChromiumVariant(browser_name=name, user_data_root=path))

    if kind is OSKind.Windows:
        if win_local:
            _add("Edge",         _join_win(win_local, "Microsoft", "Edge", "User Data"))
            _add("Brave",        _join_win(win_local, "BraveSoftware", "Brave-Browser", "User Data"))
            _add("Chrome Beta",  _join_win(win_local, "Google", "Chrome Beta", "User Data"))
            _add("Chrome Canary",_join_win(win_local, "Google", "Chrome SxS", "User Data"))
            _add("Chromium",     _join_win(win_local, "Chromium", "User Data"))
    elif kind is OSKind.MacOS:
        appsup = os.path.join(home, "Library", "Application Support")
        _add("Edge",         os.path.join(appsup, "Microsoft Edge"))
        _add("Brave",        os.path.join(appsup, "BraveSoftware", "Brave-Browser"))
        _add("Chrome Beta",  os.path.join(appsup, "Google", "Chrome Beta"))
        _add("Chrome Canary",os.path.join(appsup, "Google", "Chrome Canary"))
        _add("Chromium",     os.path.join(appsup, "Chromium"))
    elif kind is OSKind.Linux:
        cfg = os.path.join(home, ".config")
        _add("Edge",        os.path.join(cfg, "microsoft-edge"))
        _add("Brave",       os.path.join(cfg, "BraveSoftware", "Brave-Browser"))
        _add("Chrome Beta", os.path.join(cfg, "google-chrome-beta"))
        _add("Chromium",    os.path.join(cfg, "chromium"))
    return out