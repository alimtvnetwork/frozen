import pytest

from idle_shutdown.capture.apps import AppInfo
from idle_shutdown.capture.chrome import ChromeSession, ChromeTabInfo, ChromeWindowInfo
from idle_shutdown.db.connection import connect, init_db
from idle_shutdown.db.repos import SettingsRepo
from idle_shutdown.enums import SnapshotTriggerKind
from idle_shutdown.errors import RestoreError
from idle_shutdown.restore import LiveProcess, restore
from idle_shutdown.snapshot import SnapshotProviders, take_snapshot


def _seed_snapshot(*, with_chrome=True):
    apps = [
        AppInfo("C:\\Apps\\code.exe", "C:\\u", None, 0),
        AppInfo("C:\\Apps\\notepad.exe", None, "C:\\u\\n.txt", 0),
    ]
    chrome = (
        ChromeSession(
            executable_path="C:\\Apps\\chrome.exe",
            windows=(ChromeWindowInfo(tabs=(
                ChromeTabInfo("https://a", "A"),
                ChromeTabInfo("https://b", "B"),
            )),),
        ) if with_chrome else ChromeSession(executable_path=None, windows=())
    )
    providers = SnapshotProviders(
        capture_desktops_fn=lambda: (1, {}),
        enumerate_apps_fn=lambda _m: apps,
        capture_chrome_fn=lambda: chrome,
    )
    return take_snapshot(SnapshotTriggerKind.Manual, providers, record_log=False)


def test_restore_launches_all_when_nothing_running(temp_db):
    init_db()
    _seed_snapshot()
    spawned: list[list[str]] = []
    result = restore(
        live_processes=lambda: [],
        spawn=lambda argv, cwd: spawned.append(argv),
    )
    assert result.apps_launched == 2
    assert result.apps_skipped == 0
    assert result.chrome_launched is True
    # Chrome args
    chrome_call = next(c for c in spawned if c[0] == "C:\\Apps\\chrome.exe")
    assert "--restore-last-session" in chrome_call
    assert "https://a" in chrome_call and "https://b" in chrome_call


def test_duplicate_prevention_skips_when_exe_and_doc_match(temp_db):
    init_db()
    _seed_snapshot()
    live = [
        LiveProcess(pid=1, exe="c:/apps/notepad.exe", cmdline=("c:\\apps\\notepad.exe", "C:\\U\\N.TXT")),
    ]
    spawned: list[list[str]] = []
    result = restore(
        live_processes=lambda: live,
        spawn=lambda argv, cwd: spawned.append(argv),
    )
    # notepad.exe + n.txt → skip; code.exe (no doc) → launch; chrome → launch
    assert result.apps_skipped == 1
    assert result.apps_launched == 1


def test_duplicate_prevention_launches_when_doc_differs(temp_db):
    init_db()
    _seed_snapshot()
    live = [
        LiveProcess(pid=1, exe="C:\\Apps\\notepad.exe", cmdline=("notepad.exe", "C:\\other.txt")),
    ]
    spawned: list[list[str]] = []
    result = restore(
        live_processes=lambda: live,
        spawn=lambda argv, cwd: spawned.append(argv),
    )
    assert result.apps_skipped == 0
    assert result.apps_launched == 2


def test_idempotent_second_call_skips_everything(temp_db):
    init_db()
    _seed_snapshot()

    def _sim(argvs, calls):
        # After "launch" record a live process matching that exe + doc
        def _spawn(argv, cwd):
            argvs.append(argv)
            doc = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else None
            calls.append(LiveProcess(
                pid=100 + len(calls), exe=argv[0],
                cmdline=tuple([argv[0]] + ([doc] if doc else []))
            ))
        return _spawn

    live: list[LiveProcess] = []
    argvs: list[list[str]] = []
    restore(live_processes=lambda: list(live), spawn=_sim(argvs, live))
    first = len(argvs)
    restore(live_processes=lambda: list(live), spawn=_sim(argvs, live))
    assert len(argvs) == first  # second invocation launched nothing


def test_chrome_skipped_when_path_unset(temp_db):
    init_db()
    _seed_snapshot(with_chrome=False)
    spawned: list[list[str]] = []
    result = restore(
        live_processes=lambda: [],
        spawn=lambda argv, cwd: spawned.append(argv),
    )
    assert result.chrome_launched is False
    assert all(s[0] != "C:\\Apps\\chrome.exe" for s in spawned)


def test_writes_last_restored_markers(temp_db):
    init_db()
    res = _seed_snapshot()
    restore(live_processes=lambda: [], spawn=lambda *_: None)
    with connect() as conn:
        repo = SettingsRepo(conn)
        assert repo.get("LastRestoredSnapshotId") == res.snapshot_id
        assert repo.get("LastRestoredAt") != ""


def test_restore_missing_snapshot_raises(temp_db):
    init_db()
    with pytest.raises(RestoreError):
        restore(snapshot_id=999, live_processes=lambda: [], spawn=lambda *_: None)


def test_per_item_failure_continues(temp_db):
    init_db()
    _seed_snapshot()
    calls = {"n": 0}
    def _spawn(argv, cwd):
        calls["n"] += 1
        if argv[0] == "C:\\Apps\\code.exe":
            raise OSError("denied")
    result = restore(live_processes=lambda: [], spawn=_spawn)
    # code.exe failed, notepad.exe + chrome still launched
    assert calls["n"] == 3
    assert result.apps_launched == 1  # only notepad counted as launched