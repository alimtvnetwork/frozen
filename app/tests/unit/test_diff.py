from click.testing import CliRunner

from idle_shutdown.capture.apps import AppInfo
from idle_shutdown.capture.chrome import (
    ChromeProfileInfo, ChromeSession, ChromeTabInfo, ChromeWindowInfo,
)
from idle_shutdown.cli import cli
from idle_shutdown.db.connection import connect, init_db
from idle_shutdown.db.repos import SnapshotReadRepo
from idle_shutdown.diff import compute_snapshot_diff
from idle_shutdown.enums import SnapshotTriggerKind
from idle_shutdown.snapshot import SnapshotProviders, take_snapshot


def _snap(apps, tabs):
    chrome = ChromeSession(
        executable_path="/usr/bin/chrome",
        profiles=(ChromeProfileInfo(
            profile_dir="Default", profile_name="Default",
            windows=(ChromeWindowInfo(tabs=tuple(tabs)),),
        ),) if tabs else (),
    )
    p = SnapshotProviders(
        capture_desktops_fn=lambda: (1, {}),
        enumerate_apps_fn=lambda _m: apps,
        capture_chrome_fn=lambda: chrome,
    )
    return take_snapshot(SnapshotTriggerKind.Manual, p, record_log=False)


def test_diff_detects_app_and_tab_changes(temp_db):
    init_db()
    a_id = _snap(
        [AppInfo("/bin/code", None, None, 0)],
        [ChromeTabInfo("https://a", "A"), ChromeTabInfo("https://b", "B")],
    ).snapshot_id
    b_id = _snap(
        [AppInfo("/bin/code", None, None, 0),
         AppInfo("/bin/notepad", None, None, 0)],
        [ChromeTabInfo("https://b", "B"), ChromeTabInfo("https://c", "C")],
    ).snapshot_id
    with connect() as conn:
        repo = SnapshotReadRepo(conn)
        a = repo.get_detail(a_id); b = repo.get_detail(b_id)
    d = compute_snapshot_diff(a, b)
    assert [x.executable_path for x in d.apps_added] == ["/bin/notepad"]
    assert d.apps_removed == []
    assert [x.url for x in d.tabs_added] == ["https://c"]
    assert [x.url for x in d.tabs_removed] == ["https://a"]
    assert d.is_empty is False


def test_diff_empty_when_identical(temp_db):
    init_db()
    apps = [AppInfo("/bin/code", None, None, 0)]
    tabs = [ChromeTabInfo("https://a", "A")]
    a_id = _snap(apps, tabs).snapshot_id
    b_id = _snap(apps, tabs).snapshot_id
    with connect() as conn:
        repo = SnapshotReadRepo(conn)
        a = repo.get_detail(a_id); b = repo.get_detail(b_id)
    d = compute_snapshot_diff(a, b)
    assert d.is_empty is True


def test_diff_cli_human_and_json(temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    a_id = _snap([AppInfo("/bin/x", None, None, 0)],
                 [ChromeTabInfo("https://a", "A")]).snapshot_id
    b_id = _snap([AppInfo("/bin/y", None, None, 0)],
                 [ChromeTabInfo("https://b", "B")]).snapshot_id
    res = runner.invoke(cli, ["diff", str(a_id), str(b_id)])
    assert res.exit_code == 0, res.output
    assert "apps:+1/-1" in res.output
    assert "tabs:+1/-1" in res.output

    res = runner.invoke(cli, ["diff", str(a_id), str(b_id), "--json"])
    assert res.exit_code == 0, res.output
    import json
    payload = json.loads(res.output)
    assert payload["a"] == a_id and payload["b"] == b_id
    assert len(payload["apps_added"]) == 1
    assert len(payload["tabs_removed"]) == 1


def test_diff_unknown_id(temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    res = runner.invoke(cli, ["diff", "1", "2"])
    assert res.exit_code != 0