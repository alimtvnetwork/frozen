import pytest

from idle_shutdown.capture.apps import AppInfo
from idle_shutdown.capture.chrome import (
    ChromeProfileInfo, ChromeSession, ChromeTabInfo, ChromeWindowInfo,
)
from idle_shutdown.db.connection import connect, init_db
from idle_shutdown.db.repos import SettingsRepo
from idle_shutdown.enums import SnapshotTriggerKind
from idle_shutdown.errors import RestoreError
from idle_shutdown.restore import LiveProcess, restore
from idle_shutdown.snapshot import SnapshotProviders, take_snapshot


def _seed_snapshot(*, with_chrome=True, desktop_count=1, app_desktops=(0, 0)):
    apps = [
        AppInfo("C:\\Apps\\code.exe", "C:\\u", None, app_desktops[0]),
        AppInfo("C:\\Apps\\notepad.exe", None, "C:\\u\\n.txt", app_desktops[1]),
    ]
    chrome = (
        ChromeSession(
            executable_path="C:\\Apps\\chrome.exe",
            profiles=(ChromeProfileInfo(
                profile_dir="Default", profile_name="Default",
                windows=(ChromeWindowInfo(tabs=(
                    ChromeTabInfo("https://a", "A"),
                    ChromeTabInfo("https://b", "B"),
                )),),
            ),),
        ) if with_chrome else ChromeSession(executable_path=None, profiles=())
    )
    providers = SnapshotProviders(
        capture_desktops_fn=lambda: (desktop_count, {}),
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


def test_dry_run_records_plan_without_side_effects(temp_db):
    init_db()
    _seed_snapshot()
    spawned: list[list[str]] = []
    desktops_calls: list[int] = []
    switch_calls: list[int] = []
    result = restore(
        live_processes=lambda: [],
        spawn=lambda argv, cwd: spawned.append(argv),
        ensure_desktops=lambda n: desktops_calls.append(n),
        switch_to_desktop=lambda i: switch_calls.append(i),
        dry_run=True,
    )
    # Plan was captured (apps + chrome).
    assert result.apps_launched == 2
    assert result.chrome_launched is True
    assert any("--restore-last-session" in c for c in spawned)
    # No real-world side effects ran.
    assert desktops_calls == []
    assert switch_calls == []
    # No persisted markers.
    with connect() as conn:
        repo = SettingsRepo(conn)
        assert repo.get("LastRestoredSnapshotId") == 0
        assert repo.get("LastRestoredAt") == ""


def test_restore_missing_snapshot_raises(temp_db):
    init_db()
    with pytest.raises(RestoreError):
        restore(snapshot_id=999, live_processes=lambda: [], spawn=lambda *_: None)


def test_apps_only_skips_chrome(temp_db):
    init_db()
    _seed_snapshot()
    spawned: list[list[str]] = []
    result = restore(
        live_processes=lambda: [],
        spawn=lambda argv, cwd: spawned.append(argv),
        apps_only=True,
    )
    assert result.apps_launched == 2
    assert result.chrome_launched is False
    assert all("chrome.exe" not in c[0].lower() for c in spawned)


def test_chrome_only_skips_apps(temp_db):
    init_db()
    _seed_snapshot()
    spawned: list[list[str]] = []
    result = restore(
        live_processes=lambda: [],
        spawn=lambda argv, cwd: spawned.append(argv),
        chrome_only=True,
    )
    assert result.apps_launched == 0
    assert result.chrome_launched is True
    assert any("--restore-last-session" in c for c in spawned)


def test_apps_only_and_chrome_only_mutually_exclusive(temp_db):
    init_db()
    _seed_snapshot()
    with pytest.raises(RestoreError):
        restore(live_processes=lambda: [], spawn=lambda *_: None,
                apps_only=True, chrome_only=True)


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

def test_per_desktop_switch_and_move_called(temp_db):
    init_db()
    _seed_snapshot(desktop_count=3, app_desktops=(2, 0))
    spawned: list[list[str]] = []
    switches: list[int] = []
    moves: list[tuple[int, int]] = []
    ensured: list[int] = []
    next_pid = {"v": 1000}

    def _spawn(argv, cwd):
        spawned.append(argv)
        next_pid["v"] += 1
        return next_pid["v"]

    restore(
        live_processes=lambda: [],
        spawn=_spawn,
        ensure_desktops=lambda n: ensured.append(n),
        switch_to_desktop=lambda i: switches.append(i),
        move_to_desktop=lambda pid, i: moves.append((pid, i)),
    )
    assert ensured == [3]
    # Apps grouped: desktop 0 (notepad) then desktop 2 (code)
    assert switches == [0, 2]
    # Each app launched gets a move call (chrome on desktop 0 also gets switch but no move call here)
    assert (1001, 0) in moves and (1002, 2) in moves


def test_single_desktop_skips_switch_and_move(temp_db):
    init_db()
    _seed_snapshot(desktop_count=1, app_desktops=(0, 0))
    switches: list[int] = []
    moves: list[tuple[int, int]] = []
    restore(
        live_processes=lambda: [],
        spawn=lambda argv, cwd: 1234,
        ensure_desktops=lambda n: None,
        switch_to_desktop=lambda i: switches.append(i),
        move_to_desktop=lambda pid, i: moves.append((pid, i)),
    )
    assert switches == []
    assert moves == []
