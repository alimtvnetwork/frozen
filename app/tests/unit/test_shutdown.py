from idle_shutdown.config import SHUTDOWN_COMMAND
from idle_shutdown.shutdown import WindowRef, execute_shutdown


def test_skips_own_pid_and_explorer():
    closed: list[int] = []
    windows = [
        WindowRef(hwnd=1, pid=999, process_name="own.exe"),
        WindowRef(hwnd=2, pid=10, process_name="explorer.exe"),
        WindowRef(hwnd=3, pid=20, process_name="code.exe"),
    ]
    cmds: list[list[str]] = []
    execute_shutdown(
        visible_windows=lambda: windows,
        post_close=closed.append,
        pid_alive=lambda _: False,
        run_command=lambda c: (cmds.append(c) or 0),
        sleeper=lambda _t: None,
        own_pid=999,
    )
    assert closed == [3]
    assert cmds == [list(SHUTDOWN_COMMAND)]


def test_invokes_locked_shutdown_command():
    cmds: list[list[str]] = []
    rc = execute_shutdown(
        visible_windows=lambda: [],
        post_close=lambda _h: None,
        pid_alive=lambda _: False,
        run_command=lambda c: (cmds.append(c) or 7),
        sleeper=lambda _t: None,
        own_pid=1,
    )
    assert cmds == [["shutdown.exe", "/s", "/t", "5", "/f", "/c", "Idle auto-shutdown"]]
    assert rc == 7


def test_waits_for_pids_to_exit_then_proceeds():
    state = {"alive": True}
    def alive(_pid):
        # First tick alive, then dies — proves wait loop polls.
        v = state["alive"]
        state["alive"] = False
        return v
    cmds: list[list[str]] = []
    execute_shutdown(
        visible_windows=lambda: [WindowRef(1, 100, "code.exe")],
        post_close=lambda _h: None,
        pid_alive=alive,
        run_command=lambda c: (cmds.append(c) or 0),
        sleeper=lambda _t: None,
        own_pid=999,
    )
    assert cmds  # shutdown was eventually invoked