"""End-to-end CLI flow: init-db → settings → snapshot → counter/history → restore.

Drives ``idle_shutdown.cli`` via Click's CliRunner. OS-edge calls (capture
providers, subprocess spawn, single-instance lock, virtual-desktop calls)
are patched at module boundaries so the test runs anywhere.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from click.testing import CliRunner

from idle_shutdown import cli as cli_mod
from idle_shutdown.capture.apps import AppInfo
from idle_shutdown.capture.chrome import (
    ChromeSession,
    ChromeProfileInfo,
    ChromeTabInfo,
    ChromeWindowInfo,
)


@contextmanager
def _noop_lock():
    yield


@pytest.fixture()
def runner(temp_db, monkeypatch):
    monkeypatch.setattr(
        "idle_shutdown.single_instance.acquire_single_instance",
        lambda: _noop_lock(),
    )
    return CliRunner()


def _ok(runner, *args):
    res = runner.invoke(cli_mod.cli, list(args), catch_exceptions=False)
    assert res.exit_code == 0, f"{args} exit={res.exit_code} out={res.output}"
    return res


def test_full_cli_flow(runner, monkeypatch):
    # 1. init-db
    assert "Initialized database" in _ok(runner, "init-db").output

    # 2. settings show + set
    assert "IdleThresholdMinutes" in _ok(runner, "settings", "show").output
    _ok(runner, "settings", "set-idle", "7")
    _ok(runner, "settings", "set-countdown", "45")
    show = _ok(runner, "settings", "show").output
    assert "7" in show and "45" in show

    # 3. snapshot — patch SnapshotProviders default to deterministic fakes
    import idle_shutdown.snapshot as snap_mod

    fake_apps = [
        AppInfo("C:\\Apps\\code.exe", "C:\\u", None, 0),
        AppInfo("C:\\Apps\\notepad.exe", None, "C:\\u\\n.txt", 1),
    ]
    fake_chrome = ChromeSession(
        executable_path="C:\\Apps\\chrome.exe",
        profiles=(ChromeProfileInfo(
            profile_dir="Default", profile_name="Default",
            windows=(ChromeWindowInfo(tabs=(
                ChromeTabInfo("https://example.com/", "Example"),
            )),),
        ),),
    )
    OriginalProviders = snap_mod.SnapshotProviders

    def _fake_default():
        return OriginalProviders(
            capture_desktops_fn=lambda: (2, {}),
            enumerate_apps_fn=lambda _m: fake_apps,
            capture_chrome_fn=lambda: fake_chrome,
        )

    # Replace the class so `SnapshotProviders()` calls return our fake.
    monkeypatch.setattr(snap_mod, "SnapshotProviders", _fake_default)

    snap_out = _ok(runner, "snapshot").output
    assert "desktops=2" in snap_out
    assert "apps=2" in snap_out
    assert "chrome_tabs=1" in snap_out

    # 4. counter + history (manual snapshot doesn't increment counter)
    assert _ok(runner, "counter").output.strip() == "0"
    assert "Shutdown history" in _ok(runner, "history").output

    # 5. restore — wrap to inject pure-function callbacks
    import idle_shutdown.restore as restore_mod
    from idle_shutdown.restore import restore as real_restore

    spawned: list[list[str]] = []

    def _wrapped(snapshot_id=None, **kw):
        kw.setdefault("live_processes", lambda: [])
        kw.setdefault("spawn", lambda argv, cwd: (spawned.append(argv), 1234)[1])
        kw.setdefault("ensure_desktops", lambda n: None)
        kw.setdefault("switch_to_desktop", lambda i: None)
        kw.setdefault("move_to_desktop", lambda pid, i: None)
        return real_restore(snapshot_id, **kw)

    monkeypatch.setattr(restore_mod, "restore", _wrapped)

    out = _ok(runner, "restore").output
    assert "restored snapshot" in out
    assert any(s[0] == "C:\\Apps\\code.exe" for s in spawned)
    assert any(s[0] == "C:\\Apps\\notepad.exe" for s in spawned)
    assert any(s[0] == "C:\\Apps\\chrome.exe" for s in spawned)

    # 6. enable / disable round-trip
    assert "disabled" in _ok(runner, "disable").output.lower()
    assert "enabled" in _ok(runner, "enable").output.lower()


def test_cli_unknown_command_returns_usage_error(runner):
    _ok(runner, "init-db")
    res = runner.invoke(cli_mod.cli, ["does-not-exist"], catch_exceptions=False)
    assert res.exit_code == 2
