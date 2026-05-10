from idle_shutdown.errors import MonitorError
from idle_shutdown.monitor import IdleMonitor, StubIdleSource


class _Recorder:
    def __init__(self) -> None:
        self.threshold = 0
        self.activity = 0


def _build(threshold_ms: int = 60_000):
    src = StubIdleSource(0)
    rec = _Recorder()
    mon = IdleMonitor(
        source=src,
        threshold_ms_provider=lambda: threshold_ms,
        on_threshold=lambda: setattr(rec, "threshold", rec.threshold + 1),
        on_activity=lambda: setattr(rec, "activity", rec.activity + 1),
    )
    return src, rec, mon


def test_below_threshold_no_transition():
    src, rec, mon = _build()
    src.set(10_000)
    mon.tick()
    assert rec.threshold == 0
    assert mon.prompting is False


def test_at_threshold_transitions_to_prompting():
    src, rec, mon = _build(threshold_ms=60_000)
    src.set(60_000)
    mon.tick()
    assert rec.threshold == 1
    assert mon.prompting is True


def test_idle_to_active_during_prompting_fires_activity():
    src, rec, mon = _build()
    src.set(60_000); mon.tick()
    src.set(500); mon.tick()
    assert rec.activity == 1
    assert mon.prompting is False


def test_repeat_threshold_does_not_double_fire():
    src, rec, mon = _build()
    src.set(60_000); mon.tick(); mon.tick(); mon.tick()
    assert rec.threshold == 1


def test_threshold_reload_each_tick():
    src = StubIdleSource(0)
    threshold = {"v": 60_000}
    rec = _Recorder()
    mon = IdleMonitor(
        source=src,
        threshold_ms_provider=lambda: threshold["v"],
        on_threshold=lambda: setattr(rec, "threshold", rec.threshold + 1),
        on_activity=lambda: setattr(rec, "activity", rec.activity + 1),
    )
    src.set(30_000); mon.tick()
    assert rec.threshold == 0
    threshold["v"] = 20_000
    mon.tick()
    assert rec.threshold == 1


def test_consecutive_failures_escalate_to_monitor_error():
    class Boom:
        def get_idle_ms(self) -> int:
            raise RuntimeError("hook dead")
    rec = _Recorder()
    mon = IdleMonitor(
        source=Boom(),
        threshold_ms_provider=lambda: 1_000,
        on_threshold=lambda: setattr(rec, "threshold", rec.threshold + 1),
        on_activity=lambda: setattr(rec, "activity", rec.activity + 1),
    )
    for _ in range(9):
        mon.tick()  # absorbed
    import pytest
    with pytest.raises(MonitorError):
        mon.tick()