"""Running-application capture.

Filters per spec/21-app/04-snapshot-capture/running-apps/. The OS surface is
narrowed to two injectable callables (``process_iter`` and ``visible_pids``)
so the unit tests can drive deterministic fixtures without touching psutil
or Win32.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from idle_shutdown.platform import OSKind, current_os

logger = logging.getLogger(__name__)

SYSTEM_ROOTS = ("c:\\windows\\system32", "c:\\windows\\syswow64", "c:\\windows\\winsxs")

DENY_LIST = {
    "explorer.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "textinputhost.exe", "applicationframehost.exe", "runtimebroker.exe",
    "dwm.exe", "csrss.exe", "idle-shutdown.exe",
}


@dataclass(frozen=True)
class AppInfo:
    executable_path: str
    working_directory: str | None
    document_path: str | None
    desktop_index: int


def _norm(path: str) -> str:
    """Lower-case + canonicalize separators. Cross-platform safe for tests."""
    return os.path.normpath(path.replace("\\", os.sep)).lower()


def _is_system_path(exe: str) -> bool:
    n = _norm(exe)
    return any(n.startswith(_norm(root)) for root in SYSTEM_ROOTS)


def _document_from_cmdline(cmdline: Sequence[str]) -> str | None:
    """Return the first arg that looks like an existing path, else None."""
    for arg in list(cmdline)[1:]:
        if not arg or arg.startswith("-") or arg.startswith("/"):
            continue
        if any(sep in arg for sep in ("\\", "/")) or arg.lower().endswith(
            (".txt", ".pdf", ".docx", ".xlsx", ".md", ".py", ".png", ".jpg")
        ):
            return arg
    return None


@dataclass
class _ProcSnap:
    pid: int
    name: str
    exe: str | None
    cwd: str | None
    cmdline: Sequence[str]


def _default_process_iter() -> Iterable[_ProcSnap]:  # pragma: no cover
    import psutil  # type: ignore

    for p in psutil.process_iter(["pid", "name", "exe", "cwd", "cmdline"]):
        try:
            info = p.info
            yield _ProcSnap(
                pid=int(info["pid"]),
                name=str(info["name"] or ""),
                exe=info.get("exe"),
                cwd=info.get("cwd"),
                cmdline=list(info.get("cmdline") or []),
            )
        except Exception:  # noqa: BLE001 - access denied / gone
            continue


def _default_visible_pids() -> set[int]:  # pragma: no cover
    kind = current_os()
    if kind is OSKind.MacOS:
        return _macos_visible_pids()
    if kind is OSKind.Linux:
        return _linux_visible_pids()
    if kind is not OSKind.Windows:
        return set()
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    pids: set[int] = set()

    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pids.add(int(pid.value))
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return pids


def _macos_visible_pids() -> set[int]:  # pragma: no cover
    """Use Quartz CGWindowListCopyWindowInfo for on-screen, layer-0 windows."""
    try:
        from Quartz import (  # type: ignore
            CGWindowListCopyWindowInfo,
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID,
        )
    except Exception:
        return set()
    pids: set[int] = set()
    try:
        windows = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID
        ) or []
        for w in windows:
            if int(w.get("kCGWindowLayer", 1)) != 0:
                continue  # skip menubar / dock layers
            pid = w.get("kCGWindowOwnerPID")
            if pid is not None:
                pids.add(int(pid))
    except Exception:
        return set()
    return pids


def _linux_visible_pids() -> set[int]:  # pragma: no cover
    """Parse ``wmctrl -lp`` for top-level visible window PIDs (X11)."""
    import shutil as _sh
    import subprocess
    if not _sh.which("wmctrl"):
        return set()
    pids: set[int] = set()
    try:
        out = subprocess.check_output(["wmctrl", "-lp"], text=True, timeout=2)
        for line in out.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            try:
                pids.add(int(parts[2]))
            except ValueError:
                continue
    except Exception:
        return set()
    return pids


def enumerate_user_apps(
    pid_to_desktop: dict[int, int],
    *,
    process_iter: Callable[[], Iterable[_ProcSnap]] | None = None,
    visible_pids: Callable[[], set[int]] | None = None,
    require_visible: bool = True,
) -> list[AppInfo]:
    proc_iter = process_iter or _default_process_iter
    vis_pids: set[int] | None = None
    if require_visible:
        vis_pids = (visible_pids or _default_visible_pids)()
        # If the platform backend can't enumerate visible windows (e.g. Quartz
        # missing on macOS, no wmctrl on Linux), don't silently drop every
        # process — disable the filter and warn instead.
        if not vis_pids:
            logger.warning(
                "event=visible_pids_unavailable action=disable_visibility_filter "
                "hint='install pyobjc-framework-Quartz on macOS / wmctrl on Linux'"
            )
            vis_pids = None
    out: list[AppInfo] = []
    own_exe = _norm(sys.executable) if sys.executable else ""
    for proc in proc_iter():
        if not proc.exe:
            continue
        if proc.name.lower() in DENY_LIST:
            continue
        if _is_system_path(proc.exe):
            continue
        if own_exe and _norm(proc.exe) == own_exe:
            continue
        if vis_pids is not None and proc.pid not in vis_pids:
            continue
        doc = _document_from_cmdline(proc.cmdline)
        out.append(AppInfo(
            executable_path=proc.exe,
            working_directory=proc.cwd,
            document_path=doc,
            desktop_index=pid_to_desktop.get(proc.pid, 0),
        ))
    return out