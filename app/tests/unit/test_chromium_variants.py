import json

from idle_shutdown.capture import chrome as chrome_mod
from idle_shutdown.capture.chrome import (
    ChromeTabInfo, ChromeWindowInfo, capture_chrome_session,
    _enumerate_chromium_variants,
)
from idle_shutdown.platform import OSKind


def _make_user_data(root, names):
    """Create a fake Chrome-style user-data dir with a Default profile."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "Default" / "Sessions").mkdir(parents=True)
    (root / "Local State").write_text(json.dumps({
        "profile": {"info_cache": {"Default": {"name": names}}}
    }))


def test_enumerate_variants_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(chrome_mod, "current_os", lambda: OSKind.MacOS)
    out = _enumerate_chromium_variants({"HOME": str(tmp_path)})
    names = [v.browser_name for v in out]
    assert "Edge" in names and "Brave" in names and "Chromium" in names
    # All paths should be under our fake home
    for v in out:
        assert str(tmp_path) in v.user_data_root


def test_enumerate_variants_windows(monkeypatch):
    monkeypatch.setattr(chrome_mod, "current_os", lambda: OSKind.Windows)
    out = _enumerate_chromium_variants({"LOCALAPPDATA": "C:\\Users\\a\\AppData\\Local"})
    names = [v.browser_name for v in out]
    assert "Edge" in names and "Brave" in names
    assert "Chrome Canary" in names  # SxS folder


def test_capture_includes_variants_when_enabled(monkeypatch, tmp_path):
    chrome_root = tmp_path / "Chrome"
    edge_root = tmp_path / "Edge"
    _make_user_data(chrome_root, "Personal")
    _make_user_data(edge_root, "Work")

    monkeypatch.setattr(chrome_mod, "_chrome_user_data_root",
                        lambda exe, e: str(chrome_root))
    monkeypatch.setattr(chrome_mod, "_enumerate_chromium_variants",
                        lambda e: [chrome_mod.ChromiumVariant("Edge", str(edge_root))])

    def fake_reader(_p):
        return [ChromeWindowInfo(tabs=(ChromeTabInfo("https://x", "X"),))]

    sess = capture_chrome_session(
        env={"HOME": str(tmp_path)},
        exists=lambda p: True,
        snss_reader=fake_reader,
        include_variants=True,
    )
    browsers = sorted({p.browser_name for p in sess.profiles})
    assert browsers == ["Chrome", "Edge"]


def test_capture_excludes_variants_by_default(monkeypatch, tmp_path):
    chrome_root = tmp_path / "Chrome"
    _make_user_data(chrome_root, "Personal")

    monkeypatch.setattr(chrome_mod, "_chrome_user_data_root",
                        lambda exe, e: str(chrome_root))
    # Should not be called when include_variants=False.
    monkeypatch.setattr(chrome_mod, "_enumerate_chromium_variants",
                        lambda e: (_ for _ in ()).throw(AssertionError("called")))

    sess = capture_chrome_session(
        env={"HOME": str(tmp_path)},
        exists=lambda p: True,
        snss_reader=lambda _p: [
            ChromeWindowInfo(tabs=(ChromeTabInfo("https://x", "X"),))
        ],
    )
    assert all(p.browser_name == "Chrome" for p in sess.profiles)