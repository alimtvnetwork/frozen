from idle_shutdown.capture.apps import AppInfo, _ProcSnap, enumerate_user_apps


def _proc(pid, name, exe, cwd="C:\\u", cmdline=None):
    return _ProcSnap(pid=pid, name=name, exe=exe, cwd=cwd, cmdline=cmdline or [exe])


def _iter(items):
    return lambda: iter(items)


def test_filters_system_paths():
    procs = [
        _proc(1, "svchost.exe", "C:\\Windows\\System32\\svchost.exe"),
        _proc(2, "code.exe", "C:\\Apps\\code.exe"),
    ]
    out = enumerate_user_apps({}, process_iter=_iter(procs), require_visible=False)
    assert [a.executable_path for a in out] == ["C:\\Apps\\code.exe"]


def test_filters_deny_list():
    procs = [
        _proc(1, "explorer.exe", "C:\\Apps\\explorer.exe"),
        _proc(2, "dwm.exe", "C:\\Apps\\dwm.exe"),
        _proc(3, "code.exe", "C:\\Apps\\code.exe"),
    ]
    out = enumerate_user_apps({}, process_iter=_iter(procs), require_visible=False)
    assert {a.executable_path for a in out} == {"C:\\Apps\\code.exe"}


def test_requires_visible_window():
    procs = [
        _proc(1, "code.exe", "C:\\Apps\\code.exe"),
        _proc(2, "background.exe", "C:\\Apps\\bg.exe"),
    ]
    out = enumerate_user_apps(
        {}, process_iter=_iter(procs), visible_pids=lambda: {1}, require_visible=True
    )
    assert [a.executable_path for a in out] == ["C:\\Apps\\code.exe"]


def test_document_path_extracted_from_cmdline():
    procs = [_proc(1, "notepad.exe", "C:\\Apps\\notepad.exe",
                   cmdline=["C:\\Apps\\notepad.exe", "C:\\users\\x\\notes.txt"])]
    out = enumerate_user_apps({}, process_iter=_iter(procs), require_visible=False)
    assert out[0].document_path == "C:\\users\\x\\notes.txt"


def test_assigns_desktop_index_from_map():
    procs = [_proc(7, "code.exe", "C:\\Apps\\code.exe")]
    out = enumerate_user_apps({7: 2}, process_iter=_iter(procs), require_visible=False)
    assert out[0].desktop_index == 2


def test_missing_exe_skipped():
    procs = [_ProcSnap(pid=1, name="x", exe=None, cwd=None, cmdline=[])]
    out = enumerate_user_apps({}, process_iter=_iter(procs), require_visible=False)
    assert out == []