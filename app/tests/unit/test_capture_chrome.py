from idle_shutdown.capture.chrome import capture_chrome_session, detect_chrome_path


def _exists_in(allowed):
    s = set(allowed)
    return lambda p: p in s


def test_detect_chrome_via_hklm():
    def reg(hive, _sub, _name):
        return "C:\\Apps\\chrome.exe" if hive == "HKEY_LOCAL_MACHINE" else None
    out = detect_chrome_path(
        reg_read=reg, env={}, exists=_exists_in(["C:\\Apps\\chrome.exe"]))
    assert out == "C:\\Apps\\chrome.exe"


def test_detect_chrome_program_files_fallback():
    def reg(*_):
        return None
    pf = "C:\\Program Files"
    expected = f"{pf}\\Google\\Chrome\\Application\\chrome.exe"
    out = detect_chrome_path(
        reg_read=reg, env={"PROGRAMFILES": pf}, exists=_exists_in([expected]))
    assert out == expected


def test_detect_chrome_missing_returns_none():
    out = detect_chrome_path(reg_read=lambda *_: None, env={}, exists=lambda _: False)
    assert out is None


def test_capture_with_no_chrome_returns_empty():
    sess = capture_chrome_session(
        reg_read=lambda *_: None, env={}, exists=lambda _: False)
    assert sess.executable_path is None
    assert sess.windows == ()


def test_capture_with_no_user_data_returns_no_windows():
    exe = "C:\\Apps\\chrome.exe"
    sess = capture_chrome_session(
        reg_read=lambda h, *_: exe if h == "HKEY_LOCAL_MACHINE" else None,
        env={"LOCALAPPDATA": "C:\\Users\\x\\AppData\\Local"},
        exists=_exists_in([exe]),
    )
    assert sess.executable_path == exe
    assert sess.windows == ()