import json

from click.testing import CliRunner

from idle_shutdown.capture.apps import AppInfo
from idle_shutdown.capture.chrome import (
    ChromeProfileInfo, ChromeSession, ChromeTabInfo, ChromeWindowInfo,
)
from idle_shutdown.cli import cli
from idle_shutdown.db.connection import init_db
from idle_shutdown.enums import SnapshotTriggerKind
from idle_shutdown.snapshot import SnapshotProviders, take_snapshot


def _seed(temp_db):
    init_db()
    chrome = ChromeSession(
        executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        profiles=(
            ChromeProfileInfo("Default", "Personal", windows=(
                ChromeWindowInfo(tabs=(
                    ChromeTabInfo("https://a.example", "A"),
                    ChromeTabInfo("https://b.example", "B"),
                )),
            )),
            ChromeProfileInfo("Profile 1", "Work", windows=(
                ChromeWindowInfo(tabs=(
                    ChromeTabInfo("https://w.example", "W"),
                )),
            )),
        ),
    )
    providers = SnapshotProviders(
        capture_desktops_fn=lambda: (1, {}),
        enumerate_apps_fn=lambda _m: [AppInfo("/Apps/code", "/u", None, 0)],
        capture_chrome_fn=lambda: chrome,
    )
    return take_snapshot(SnapshotTriggerKind.Manual, providers, record_log=False)


def test_show_latest_human(temp_db):
    res = _seed(temp_db)
    runner = CliRunner()
    out = runner.invoke(cli, ["show"])
    assert out.exit_code == 0, out.output
    assert f"Snapshot #{res.snapshot_id}" in out.output
    assert "Personal" in out.output
    assert "Work" in out.output
    assert "https://a.example" in out.output


def test_show_json(temp_db):
    res = _seed(temp_db)
    runner = CliRunner()
    out = runner.invoke(cli, ["show", "--snapshot-id", str(res.snapshot_id), "--json"])
    assert out.exit_code == 0, out.output
    payload = json.loads(out.output)
    assert payload["snapshot_id"] == res.snapshot_id
    assert payload["trigger"] == "Manual"
    assert len(payload["profiles"]) == 2
    assert len(payload["tabs"]) == 3
    assert {p["profile_name"] for p in payload["profiles"]} == {"Personal", "Work"}


def test_show_unknown_id(temp_db):
    init_db()
    runner = CliRunner()
    out = runner.invoke(cli, ["show"])
    assert out.exit_code != 0
    assert "no snapshots" in out.output