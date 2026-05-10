from idle_shutdown.enums import MonitorStateName, PopupResult
from idle_shutdown.service import IdleService, ServiceCallbacks


class _Fakes:
    def __init__(self, *, enabled: bool = True, threshold: int = 10, countdown: int = 30):
        self.enabled = enabled
        self.threshold = threshold
        self.countdown = countdown
        self.snapshots = 0
        self.popup_calls = 0
        self._on_result = None

    def show_popup(self, countdown, on_result):
        self.popup_calls += 1
        self._on_result = on_result

    def deliver(self, result: PopupResult):
        assert self._on_result is not None
        cb, self._on_result = self._on_result, None
        cb(result)

    def take(self):
        self.snapshots += 1

    def build(self) -> IdleService:
        return IdleService(ServiceCallbacks(
            show_popup=self.show_popup,
            take_snapshot_and_shutdown=self.take,
            get_idle_threshold_minutes=lambda: self.threshold,
            get_popup_countdown_seconds=lambda: self.countdown,
            get_service_enabled=lambda: self.enabled,
        ))


def test_threshold_when_disabled_skips_popup():
    f = _Fakes(enabled=False)
    s = f.build()
    s.on_threshold_reached()
    assert f.popup_calls == 0
    assert s.state == MonitorStateName.Idle


def test_threshold_opens_popup_once():
    f = _Fakes()
    s = f.build()
    s.on_threshold_reached()
    s.on_threshold_reached()  # second call must be a no-op
    assert f.popup_calls == 1
    assert s.state == MonitorStateName.Prompting


def test_popup_yes_returns_to_idle():
    f = _Fakes()
    s = f.build()
    s.on_threshold_reached()
    f.deliver(PopupResult.Yes)
    assert f.snapshots == 0
    assert s.state == MonitorStateName.Idle


def test_popup_no_triggers_snapshot():
    f = _Fakes()
    s = f.build()
    s.on_threshold_reached()
    f.deliver(PopupResult.No)
    assert f.snapshots == 1
    assert s.state == MonitorStateName.ShuttingDown


def test_popup_timeout_triggers_snapshot():
    f = _Fakes()
    s = f.build()
    s.on_threshold_reached()
    f.deliver(PopupResult.Timeout)
    assert f.snapshots == 1


def test_activity_during_prompt_cancels():
    f = _Fakes()
    s = f.build()
    s.on_threshold_reached()
    s.on_activity_during_prompt()
    assert s.state == MonitorStateName.Idle
    # New threshold should be allowed to open a fresh popup
    s.on_threshold_reached()
    assert f.popup_calls == 2


def test_threshold_ms_uses_minutes():
    s = _Fakes(threshold=2).build()
    assert s.threshold_ms() == 120_000