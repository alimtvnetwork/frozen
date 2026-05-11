from idle_shutdown.capture.apps import AppInfo
from idle_shutdown.capture.chrome import (
    ChromeProfileInfo, ChromeSession, ChromeTabInfo, ChromeWindowInfo,
)
from idle_shutdown.db.connection import init_db
from idle_shutdown.enums import SnapshotTriggerKind
from idle_shutdown.restore import restore
from idle_shutdown.snapshot import SnapshotProviders, take_snapshot


def _seed(monkeypatch, *, edge_exe="/Applications/Microsoft Edge.app/x"):
    """Snapshot with one Chrome profile + one Edge profile."""
    chrome = ChromeSession(
        executable_path="/usr/bin/google-chrome",
        profiles=(
            ChromeProfileInfo(
                profile_dir="Default", profile_name="Personal",
                browser_name="Chrome",
                windows=(ChromeWindowInfo(tabs=(ChromeTabInfo("https://chrome", "C"),)),),
            ),
            ChromeProfileInfo(
                profile_dir="Default", profile_name="Work",
                browser_name="Edge",
                windows=(ChromeWindowInfo(tabs=(
                    ChromeTabInfo("https://edge1", "E1"),
                    ChromeTabInfo("https://edge2", "E2"),
                )),),
            ),
        ),
    )
    providers = SnapshotProviders(
        capture_desktops_fn=lambda: (1, {}),
        enumerate_apps_fn=lambda _m: [],
        capture_chrome_fn=lambda: chrome,
    )
    take_snapshot(SnapshotTriggerKind.Manual, providers, record_log=False)
    # Stub variant exe detection so the test is OS-independent.
    import idle_shutdown.restore as restore_mod
    monkeypatch.setattr(
        restore_mod, "detect_variant_executable",
        lambda name: edge_exe if name == "Edge" else None,
    )


def test_variants_launched_when_exe_detected(temp_db, monkeypatch):
    init_db()
    _seed(monkeypatch)
    spawned: list[list[str]] = []
    res = restore(live_processes=lambda: [],
                  spawn=lambda argv, cwd: spawned.append(argv))
    edge_call = next(c for c in spawned if "Edge" in c[0])
    assert "https://edge1" in edge_call and "https://edge2" in edge_call
    assert "--restore-last-session" in edge_call
    assert res.variants_launched == ("Edge",)
    # Primary chrome still launched separately
    assert res.chrome_launched is True


def test_variants_skipped_when_exe_missing(temp_db, monkeypatch):
    init_db()
    _seed(monkeypatch, edge_exe=None)
    spawned: list[list[str]] = []
    res = restore(live_processes=lambda: [],
                  spawn=lambda argv, cwd: spawned.append(argv))
    assert all("Edge" not in c[0] for c in spawned)
    assert res.variants_launched == ()
    assert res.chrome_launched is True