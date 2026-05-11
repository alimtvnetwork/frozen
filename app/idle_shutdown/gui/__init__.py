"""Tk-based desktop UI for Idle Shutdown.

Sidebar-style window inspired by macOS System Settings / VS Code.
Sections: Dashboard, Settings, Snapshots, About.
"""
from idle_shutdown.gui.app import launch_gui

__all__ = ["launch_gui"]