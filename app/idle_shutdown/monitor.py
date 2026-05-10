"""Idle-time source + polling loop.

Win32 implementation uses ``GetLastInputInfo``. On non-Windows hosts the
import resolves to a stub source that always returns 0 idle ms — useful for
unit tests and for keeping the module import-safe on the dev sandbox.
"""
from __future__ import annotations

import sys
import time
from typing import Callable, Protocol

from idle_shutdown.errors import MonitorError


class IdleSource(Protocol):
    def get_idle_ms(self) -> int: ...


class StubIdleSource:
    """Test/non-Windows fallback. Always reports the configured value."""

    def __init__(self, idle_ms: int = 0) -> None:
        self._idle_ms = idle_ms

    def set(self, idle_ms: int) -> None:
        self._idle_ms = idle_ms

    def get_idle_ms(self) -> int:
        return self._idle_ms


def _build_win32_source() -> IdleSource:  # pragma: no cover - exercised on Windows only
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)

    class _Source:
        def get_idle_ms(self) -> int:
            if not user32.GetLastInputInfo(ctypes.byref(lii)):
                raise MonitorError("GetLastInputInfo failed")
            return int(kernel32.GetTickCount()) - int(lii.dwTime)

    return _Source()


def get_default_idle_source() -> IdleSource:
    if sys.platform == "win32":
        return _build_win32_source()
    return StubIdleSource()


class IdleMonitor:
    """Polls an :class:`IdleSource` on a 1 Hz tick.

    Pure logic — does not touch the GUI, the DB, or shutdown. The owning
    :class:`~idle_shutdown.service.IdleService` reacts to ``on_threshold`` and
    ``on_activity`` callbacks.
    """

    def __init__(
        self,
        source: IdleSource,
        threshold_ms_provider: Callable[[], int],
        on_threshold: Callable[[], None],
        on_activity: Callable[[], None],
        poll_interval_s: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._source = source
        self._threshold_ms_provider = threshold_ms_provider
        self._on_threshold = on_threshold
        self._on_activity = on_activity
        self._poll_interval_s = poll_interval_s
        self._sleeper = sleeper
        self._prompting = False
        self._consecutive_failures = 0
        self._stop = False

    @property
    def prompting(self) -> bool:
        return self._prompting

    def mark_prompting(self, value: bool) -> None:
        self._prompting = value

    def request_stop(self) -> None:
        self._stop = True

    def tick(self) -> None:
        """Single tick. Pure; safe to call from tests."""
        try:
            idle_ms = self._source.get_idle_ms()
            self._consecutive_failures = 0
        except Exception as e:  # noqa: BLE001
            self._consecutive_failures += 1
            if self._consecutive_failures >= 10:
                raise MonitorError(f"activity hook failed 10x: {e}") from e
            return

        threshold_ms = self._threshold_ms_provider()
        if idle_ms >= threshold_ms and not self._prompting:
            self._prompting = True
            self._on_threshold()
        elif idle_ms < threshold_ms and self._prompting:
            self._prompting = False
            self._on_activity()

    def run_forever(self) -> None:  # pragma: no cover - infinite loop
        while not self._stop:
            self.tick()
            self._sleeper(self._poll_interval_s)