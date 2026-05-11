import json

from idle_shutdown.capture.chrome import (
    ChromeWindowInfo, ChromeTabInfo,
    _list_profile_dirs, _read_profile_names, capture_chrome_session,
)


def test_list_profile_dirs_orders_default_first_then_numeric():
    entries = ["Profile 2", "Profile 10", "Default", "System Profile", "Profile 1"]
    out = _list_profile_dirs(
        "/root",
        exists=lambda _p: True,
        list_dir=lambda _p: entries,
    )
    assert out == ["Default", "Profile 1", "Profile 2", "Profile 10"]


def test_list_profile_dirs_skips_default_when_missing():
    out = _list_profile_dirs(
        "/root",
        exists=lambda _p: not _p.endswith("Default"),
        list_dir=lambda _p: ["Default", "Profile 1"],
    )
    assert out == ["Profile 1"]


def test_read_profile_names_extracts_human_labels():
    payload = json.dumps({"profile": {"info_cache": {
        "Default": {"name": "Personal"},
        "Profile 1": {"name": "Work"},
    }}})
    names = _read_profile_names("/root", read_text=lambda _p: payload)
    assert names == {"Default": "Personal", "Profile 1": "Work"}


def test_read_profile_names_falls_back_to_dir_when_unparseable():
    names = _read_profile_names("/root", read_text=lambda _p: "{not json")
    assert names == {}


def test_capture_chrome_session_walks_all_profiles(monkeypatch, tmp_path):
    # Build a fake user-data tree with two profiles.
    root = tmp_path / "Chrome"
    (root / "Default" / "Sessions").mkdir(parents=True)
    (root / "Profile 1" / "Sessions").mkdir(parents=True)
    (root / "Local State").write_text(json.dumps({"profile": {"info_cache": {
        "Default": {"name": "Personal"},
        "Profile 1": {"name": "Work"},
    }}}))

    # Stub OS resolution to point at our fake tree on macOS code path.
    from idle_shutdown.capture import chrome as chrome_mod
    monkeypatch.setattr(chrome_mod, "_chrome_user_data_root",
                        lambda exe, e: str(root))

    fake_reader_calls: list[str] = []

    def fake_reader(p):
        fake_reader_calls.append(p.name)
        # Only "Default" gets a window; "Profile 1" returns empty.
        if "Default" in str(p):
            return [ChromeWindowInfo(tabs=(ChromeTabInfo("https://x", "X"),))]
        return []

    sess = capture_chrome_session(
        env={"HOME": str(tmp_path)},
        exists=lambda p: True,  # pretend Chrome.app exists
        snss_reader=fake_reader,
    )
    # Profile with empty windows is omitted; only "Default" survives.
    assert [p.profile_dir for p in sess.profiles] == ["Default"]
    assert sess.profiles[0].profile_name == "Personal"
    assert sess.profiles[0].windows[0].tabs[0].url == "https://x"
    # Compat shim still works.
    assert len(sess.windows) == 1