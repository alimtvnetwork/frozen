"""Graceful shutdown sequence.

Steps locked in spec/21-app/05-shutdown-sequence/:
1. Enumerate top-level visible windows.
2. Skip own pid and ``explorer.exe``.
3. Send WM_CLOSE; wait up to 5 s per app.
4. Invoke ``shutdown.exe /s /t 5 /f /c "Idle auto-shutdown"``.

All OS surfaces are injected so unit tests run anywhere.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from idle_shutdown.config import SHUTDOWN_COMMAND, WM_CLOSE_TIMEOUT_SECONDS
from idle_shutdown.platform import current_os, OSKind, shutdown_command, is_dry_run_default

logger = logging.getLogger(__name__)

OWN_DENY_NAMES = {"explorer.exe", "idle-shutdown.exe", "idle-shutdown",
                  "Finder", "Dock", "SystemUIServer"}


@dataclass(frozen=True)
class WindowRef:
    hwnd: int
    pid: int
    process_name: str


def _default_visible_windows() -> list[WindowRef]:  # pragma: no cover - Windows only
    if sys.platform != "win32":
        return []
    import ctypes
    import psutil  # type: ignore
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    out: list[WindowRef] = []

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            name = psutil.Process(int(pid.value)).name()
        except Exception:  # noqa: BLE001
            return True
        out.append(WindowRef(hwnd=int(hwnd), pid=int(pid.value), process_name=name))
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return out


def _default_post_close(hwnd: int) -> None:  # pragma: no cover - Windows only
    import ctypes
    WM_CLOSE = 0x0010
    ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def _default_pid_alive(pid: int) -> bool:  # pragma: no cover
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001
        return False


def execute_shutdown(
    *,
    visible_windows: Callable[[], Iterable[WindowRef]] | None = None,
    post_close: Callable[[int], None] | None = None,
    pid_alive: Callable[[int], bool] | None = None,
    run_command: Callable[[list[str]], int] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    own_pid: int | None = None,
    command: list[str] | None = None,
    dry_run: bool | None = None,
) -> int:
    """Run the locked shutdown sequence. Returns the ``shutdown.exe`` exit code."""
    vw = visible_windows or _default_visible_windows
    pc = post_close or _default_post_close
    alive = pid_alive or _default_pid_alive
    run = run_command or (lambda cmd: subprocess.call(cmd))
    own = own_pid if own_pid is not None else os.getpid()
    # Default command: keep the Windows constant when callers inject their
    # own ``run_command`` (the test suite). For real callers on POSIX use the
    # platform-native command.
    if command is None:
        if run_command is not None or current_os() is OSKind.Windows:
            command = list(SHUTDOWN_COMMAND)
        else:
            command = shutdown_command()
    if dry_run is None:
        # If a custom run_command was injected (tests), default to NOT dry-run
        # so test assertions on the invoked command still fire. Otherwise honor
        # the platform default (dry-run on macOS/Linux unless forced).
        dry_run = is_dry_run_default() if run_command is None else False

    pids_targeted: set[int] = set()
    # WM_CLOSE step is Windows-specific; on POSIX we skip the per-window
    # close (apps will be SIGTERM'd by the OS shutdown command itself).
    if current_os() is OSKind.Windows or visible_windows is not None:
        for w in vw():
            if w.pid == own:
                continue
            if w.process_name.lower() in {n.lower() for n in OWN_DENY_NAMES}:
                continue
            pc(w.hwnd)
            pids_targeted.add(w.pid)
            logger.info("event=wm_close pid=%d name=%s", w.pid, w.process_name)

    deadline = time.monotonic() + WM_CLOSE_TIMEOUT_SECONDS
    while pids_targeted and time.monotonic() < deadline:
        pids_targeted = {p for p in pids_targeted if alive(p)}
        if not pids_targeted:
            break
        sleeper(0.25)

    if dry_run:
        logger.info("event=shutdown_dry_run cmd=%s", command)
        return 0
    logger.info("event=shutdown_invoked cmd=%s", command)
    rc = run(list(command))
    return int(rc)