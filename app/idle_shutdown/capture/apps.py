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
    return os.path.normcase(os.path.normpath(path))


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
    if sys.platform != "win32":
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


def enumerate_user_apps(
    pid_to_desktop: dict[int, int],
    *,
    process_iter: Callable[[], Iterable[_ProcSnap]] | None = None,
    visible_pids: Callable[[], set[int]] | None = None,
    require_visible: bool = True,
) -> list[AppInfo]:
    proc_iter = process_iter or _default_process_iter
    vis_pids = (visible_pids or _default_visible_pids)() if require_visible else None
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