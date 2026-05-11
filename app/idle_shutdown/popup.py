"""Tk Toplevel countdown popup.

Behavior locked in spec/21-app/03-idle-popup/. Always-on-top, two buttons
(Yes / No), live countdown updated every 250 ms. Returns one of the
:class:`~idle_shutdown.enums.PopupResult` values via the supplied callback.

The Tk import is local so this module is import-safe on headless test
environments. The render path is integration-tested only on Windows.
"""
from __future__ import annotations

from typing import Callable

from idle_shutdown.enums import PopupResult


def show_popup(
    countdown_seconds: int,
    on_result: Callable[[PopupResult], None],
) -> None:  # pragma: no cover - GUI
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    win = tk.Toplevel(root)
    win.title("Idle Shutdown")
    win.attributes("-topmost", True)
    win.protocol("WM_DELETE_WINDOW", lambda: _finish(PopupResult.No))
    win.geometry("360x140")

    state = {"remaining_ms": countdown_seconds * 1000, "done": False}

    label = tk.Label(win, text="Are you still at your desk?", font=("Segoe UI", 12))
    label.pack(pady=(16, 4))
    countdown = tk.Label(win, text="", font=("Segoe UI", 10))
    countdown.pack(pady=(0, 12))
    btns = tk.Frame(win)
    btns.pack()

    def _finish(result: PopupResult) -> None:
        if state["done"]:
            return
        state["done"] = True
        try:
            on_result(result)
        finally:
            try:
                win.destroy()
            finally:
                root.destroy()

    tk.Button(btns, text="Yes", width=10, command=lambda: _finish(PopupResult.Yes)).pack(side="left", padx=8)
    tk.Button(btns, text="No",  width=10, command=lambda: _finish(PopupResult.No)).pack(side="left", padx=8)

    def _tick() -> None:
        if state["done"]:
            return
        remaining = state["remaining_ms"]
        if remaining <= 0:
            _finish(PopupResult.Timeout)
            return
        countdown.config(text=f"Auto-shutdown in {remaining // 1000}s")
        state["remaining_ms"] = remaining - 250
        win.after(250, _tick)

    _tick()
    root.mainloop()


def show_info_popup(title: str, message: str) -> None:  # pragma: no cover - GUI
    """Modal info popup with a single OK button. Blocks until dismissed.

    Used by dry-run mode to surface "would shut down now" without touching
    the OS shutdown command.
    """
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    win = tk.Toplevel(root)
    win.title(title)
    win.attributes("-topmost", True)
    win.geometry("460x220")

    tk.Label(win, text=title, font=("Segoe UI", 13, "bold")).pack(pady=(14, 6))
    body = tk.Label(win, text=message, font=("Segoe UI", 10), justify="left", wraplength=420)
    body.pack(padx=14, pady=(0, 12))

    def _close() -> None:
        try:
            win.destroy()
        finally:
            root.destroy()

    win.protocol("WM_DELETE_WINDOW", _close)
    tk.Button(win, text="OK", width=12, command=_close).pack(pady=(0, 14))
    root.mainloop()