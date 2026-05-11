import json

from click.testing import CliRunner

from idle_shutdown.capture.apps import AppInfo
from idle_shutdown.capture.chrome import (
    ChromeProfileInfo, ChromeSession, ChromeTabInfo, ChromeWindowInfo,
)
from idle_shutdown.cli import cli
from idle_shutdown.config import snapshots_dir
from idle_shutdown.enums import SnapshotTriggerKind
from idle_shutdown.snapshot import SnapshotProviders, take_snapshot


def _snap():
    chrome = ChromeSession(
        executable_path="/usr/bin/chrome",
        profiles=(ChromeProfileInfo(
            profile_dir="Default", profile_name="Default",
            windows=(ChromeWindowInfo(tabs=(
                ChromeTabInfo("https://a", "<A>"),
            )),),
        ),),
    )
    p = SnapshotProviders(
        capture_desktops_fn=lambda: (1, {}),
        enumerate_apps_fn=lambda _m: [AppInfo("/bin/code", None, "/tmp/x.py", 0)],
        capture_chrome_fn=lambda: chrome,
    )
    return take_snapshot(SnapshotTriggerKind.Manual, p, record_log=False)


def test_export_json_default_path(temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    sid = _snap().snapshot_id
    res = runner.invoke(cli, ["export", "--snapshot-id", str(sid)])
    assert res.exit_code == 0, res.output
    out = snapshots_dir() / f"snapshot-{sid}.json"
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["snapshot_id"] == sid
    assert payload["apps"][0]["executable_path"] == "/bin/code"
    assert payload["tabs"][0]["url"] == "https://a"


def test_export_html_to_file(tmp_path, temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    sid = _snap().snapshot_id
    out = tmp_path / "report.html"
    res = runner.invoke(cli, ["export", "--snapshot-id", str(sid),
                              "--format", "html", "-o", str(out)])
    assert res.exit_code == 0, res.output
    body = out.read_text()
    assert "<!doctype html>" in body
    assert f"Snapshot #{sid}" in body
    assert "&lt;A&gt;" in body
    assert "https://a" in body


def test_export_stdout_uses_latest(temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    _snap()
    sid2 = _snap().snapshot_id
    res = runner.invoke(cli, ["export", "--stdout"])
    assert res.exit_code == 0
    payload = json.loads(res.output)
    assert payload["snapshot_id"] == sid2


def test_export_unknown_id(temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    res = runner.invoke(cli, ["export", "--snapshot-id", "999"])
    assert res.exit_code != 0


def test_export_no_snapshots(temp_db):
    runner = CliRunner()
    runner.invoke(cli, ["init-db"])
    res = runner.invoke(cli, ["export"])
    assert res.exit_code != 0
