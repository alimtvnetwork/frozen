"""End-to-end CLI run: init-db → settings → snapshot (with mocked OS calls)
→ history/counter → restore (with mocked spawn) → enable/disable.

Exercises ``idle_shutdown.cli.main`` exactly as the shipped exe does, with
sys.argv injected via Click's CliRunner. OS-edge calls (psutil, pyvda, Win32
shutdown, single-instance lock) are patched at module boundaries.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from click.testing import CliRunner

from idle_shutdown import cli as cli_mod


@contextmanager
def _noop_lock():
    yield


@pytest.fixture()
def runner(temp_db, monkeypatch):
    # Replace single-instance lock so `run`/`restore` don't touch the FS.
    monkeypatch.setattr(
        "idle_shutdown.single_instance.acquire_single_instance",
        lambda: _noop_lock(),
    )
    return CliRunner()


def _invoke(runner: CliRunner, *args: str):
    res = runner.invoke(cli_mod.cli, list(args), catch_exceptions=False)
    assert res.exit_code == 0, f"{args} failed: {res.output}"
    return res


def test_full_flow(runner: CliRunner, monkeypatch):
    # --- 1. init-db + defaults visible -------------------------------------
    out = _invoke(runner, "init-db").output
    assert "Initialized database" in out

    show = _invoke(runner, "settings", "show").output
    assert "IdleThresholdMinutes" in show
    assert "PopupCountdownSeconds" in show

    _invoke(runner, "settings", "set-idle", "7")
    _invoke(runner, "settings", "set-countdown", "45")
    show2 = _invoke(runner, "settings", "show").output
    assert "7" in show2 and "45" in show2

    # --- 2. snapshot with deterministic providers --------------------------
    from idle_shutdown.capture.apps import AppInfo
    from idle_shutdown.capture.chrome import (
        ChromeSession, ChromeTabInfo, ChromeWindowInfo,
    )
    from idle_shutdown.snapshot import SnapshotProviders
    import idle_shutdown.snapshot as snap_mod

    fake = SnapshotProviders(
        capture_desktops_fn=lambda: (2, {}),
        enumerate_apps_fn=lambda _m: [
            AppInfo("C:\\Apps\\code.exe", "C:\\u", None, 0),
            AppInfo("C:\\Apps\\notepad.exe", None, "C:\\u\\n.txt", 1),
        ],
        capture_chrome_fn=lambda: ChromeSession(
            executable_path="C:\\Apps\\chrome.exe",
            windows=(ChromeWindowInfo(tabs=(
                ChromeTabInfo("https://example.com/", "Example"),
            )),),
        ),
    )
    monkeypatch.setattr(snap_mod, "default_providers", lambda: fake)

    snap_out = _invoke(runner, "snapshot").output
    assert "desktops=2" in snap_out
    assert "apps=2" in snap_out
    assert "chrome_tabs=1" in snap_out

    # --- 3. counter + history are still in defaults state ------------------
    assert _invoke(runner, "counter").output.strip() == "0"
    hist = _invoke(runner, "history").output
    assert "Shutdown history" in hist  # table renders even when empty

    # --- 4. restore with mocked OS callbacks -------------------------------
    spawned: list[list[str]] = []
    import idle_shutdown.restore as restore_mod

    real_restore = restore_mod.restore

    def _patched_restore(snapshot_id=None, **kw):
        kw.setdefault("live_processes", lambda: [])
        kw.setdefault("spawn", lambda argv, cwd: spawned.append(argv))
        kw.setdefault("ensure_desktops", lambda n: None)
        kw.setdefault("switch_to_desktop", lambda i: None)
        kw.setdefault("move_to_desktop", lambda pid, i: None)
        return real_restore(snapshot_id, **kw)

    monkeypatch.setattr("idle_shutdown.cli.__dict__")  # noqa  (placeholder; real patch below)
