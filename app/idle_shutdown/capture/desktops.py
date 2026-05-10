"""Virtual desktop capture via pyvda.

Returns ``(desktop_count, pid_to_desktop_index)``. On any failure we degrade
to a single-desktop fallback so capture never blocks shutdown.
"""
from __future__ import annotations

import logging
import sys
from typing import Tuple

logger = logging.getLogger(__name__)

DesktopMap = dict[int, int]


def capture_desktops() -> Tuple[int, DesktopMap]:
    if sys.platform != "win32":  # pragma: no cover
        logger.info("event=desktops_stub reason=non_windows")
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