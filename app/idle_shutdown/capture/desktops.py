"""Virtual desktop capture via pyvda.

Returns ``(desktop_count, pid_to_desktop_index)``. On any failure we degrade
to a single-desktop fallback so capture never blocks shutdown.
"""
from __future__ import annotations

import logging
import sys
from typing import Tuple

from idle_shutdown.platform import OSKind, current_os

logger = logging.getLogger(__name__)

DesktopMap = dict[int, int]


def capture_desktops() -> Tuple[int, DesktopMap]:
    kind = current_os()
    if kind is OSKind.Linux:  # pragma: no cover
        return _capture_linux_desktops()
    if kind is not OSKind.Windows:  # pragma: no cover
        # macOS Mission Control "Spaces" has no public API for enumeration —
        # snapshot a single virtual desktop so apps still get captured.
        logger.info("event=desktops_stub reason=non_windows os=%s", kind.value)
        return (1, {})
    try:
        import pyvda  # type: ignore
        import ctypes
        from ctypes import wintypes

        desktops = list(pyvda.get_virtual_desktops())
        count = max(1, len(desktops))

        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        pid_to_index: DesktopMap = {}

        def _cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                view = pyvda.AppView(hwnd=hwnd)
                pid_to_index[int(pid.value)] = int(view.desktop.number) - 1
            except Exception:  # noqa: BLE001
                pass
            return True

        user32.EnumWindows(EnumWindowsProc(_cb), 0)
        return (count, pid_to_index)
    except Exception as e:  # noqa: BLE001
        logger.warning("event=desktops_capture_failed err=%s", e)
        return (1, {})


def _capture_linux_desktops() -> Tuple[int, DesktopMap]:  # pragma: no cover
    """X11 only: parse ``wmctrl -d`` and ``wmctrl -lp``."""
    import shutil as _sh
    import subprocess
    if not _sh.which("wmctrl"):
        logger.info("event=desktops_stub reason=no_wmctrl")
        return (1, {})
    try:
        d_out = subprocess.check_output(["wmctrl", "-d"], text=True, timeout=2)
        count = max(1, len([l for l in d_out.splitlines() if l.strip()]))
        w_out = subprocess.check_output(["wmctrl", "-lp"], text=True, timeout=2)
        pid_to_index: DesktopMap = {}
        for line in w_out.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            try:
                desk = int(parts[1])
                pid = int(parts[2])
            except ValueError:
                continue
            if desk < 0:
                continue  # sticky/all-desktops window
            pid_to_index[pid] = desk
        return (count, pid_to_index)
    except Exception as e:
        logger.warning("event=desktops_capture_failed err=%s", e)
        return (1, {})