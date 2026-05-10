"""Idle service state machine.

Pure controller — the owning ``run`` command wires real implementations of
the popup, snapshot, and shutdown callables. Tests inject fakes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from idle_shutdown.enums import MonitorStateName, PopupResult

logger = logging.getLogger(__name__)


@dataclass
class ServiceCallbacks:
    show_popup: Callable[[int, Callable[[PopupResult], None]], None]
    take_snapshot_and_shutdown: Callable[[], None]
    get_idle_threshold_minutes: Callable[[], int]
    get_popup_countdown_seconds: Callable[[], int]
    get_service_enabled: Callable[[], bool]


class IdleService:
    """Glue between :class:`IdleMonitor` callbacks and the rest of the app."""

    def __init__(self, callbacks: ServiceCallbacks) -> None:
        self.cb = callbacks
        self.state: MonitorStateName = MonitorStateName.Idle
        self._popup_open = False

    # Threshold provider for IdleMonitor ------------------------------------
    def threshold_ms(self) -> int:
        minutes = self.cb.get_idle_threshold_minutes()
        return max(1, minutes) * 60_000

    # IdleMonitor → on_threshold -------------------------------------------
    def on_threshold_reached(self) -> None:
        if not self.cb.get_service_enabled():
            logger.info("event=threshold_skipped reason=disabled")
            return
        if self._popup_open:
            logger.debug("event=threshold_skipped reason=popup_already_open")
            return
        self.state = MonitorStateName.Prompting
        self._popup_open = True
        countdown = self.cb.get_popup_countdown_seconds()
        logger.info("event=popup_shown countdown=%d", countdown)
        self.cb.show_popup(countdown, self._handle_popup_result)

    # IdleMonitor → on_activity --------------------------------------------
    def on_activity_during_prompt(self) -> None:
        if self._popup_open:
            self._popup_open = False
            self.state = MonitorStateName.Idle
            logger.info("event=popup_result result=%s", PopupResult.ActivityDuringPrompt.value)

    # Popup result handler --------------------------------------------------
    def _handle_popup_result(self, result: PopupResult) -> None:
        self._popup_open = False
        logger.info("event=popup_result result=%s", result.value)
        if result == PopupResult.Yes:
            self.state = MonitorStateName.Idle
            return
        if result == PopupResult.ActivityDuringPrompt:
            self.state = MonitorStateName.Idle
            return
        # No or Timeout → snapshot + shutdown
        self.state = MonitorStateName.Snapshotting
        try:
            self.cb.take_snapshot_and_shutdown()
        finally:
            self.state = MonitorStateName.ShuttingDown