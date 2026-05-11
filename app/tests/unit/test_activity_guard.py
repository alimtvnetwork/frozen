from idle_shutdown.activity_guard import ActivityGuard, GuardConfig


def _guard(signals, *, mic=True, audio=True, fs=True, cam=True):
    return ActivityGuard(
        config_provider=lambda: GuardConfig(
            mic_enabled=mic, audio_enabled=audio, fullscreen_enabled=fs,
            camera_enabled=cam,
        ),
        signals=signals,
    )


def test_no_signals_means_not_busy():
    g = _guard({})
    assert g.is_busy() == (False, None)


def test_first_truthy_signal_wins():
    g = _guard({
        "mic_active": lambda: False,
        "audio_playing": lambda: True,
        "fullscreen": lambda: True,
    })
    busy, reason = g.is_busy()
    assert busy is True
    assert reason == "audio_playing"


def test_disabled_signal_is_skipped():
    g = _guard({
        "mic_active": lambda: True,
        "audio_playing": lambda: False,
    }, mic=False)
    assert g.is_busy() == (False, None)


def test_signal_exception_is_swallowed():
    def boom() -> bool:
        raise RuntimeError("denied")
    g = _guard({
        "mic_active": boom,
        "audio_playing": lambda: True,
    })
    busy, reason = g.is_busy()
    assert (busy, reason) == (True, "audio_playing")


def test_all_false_returns_not_busy():
    g = _guard({
        "mic_active": lambda: False,
        "audio_playing": lambda: False,
        "fullscreen": lambda: False,
        "camera_active": lambda: False,
    })
    assert g.is_busy() == (False, None)


def test_camera_signal_marks_busy():
    g = _guard({
        "mic_active": lambda: False,
        "camera_active": lambda: True,
    })
    assert g.is_busy() == (True, "camera_active")


def test_camera_signal_can_be_disabled():
    g = _guard({
        "camera_active": lambda: True,
    }, cam=False)
    assert g.is_busy() == (False, None)