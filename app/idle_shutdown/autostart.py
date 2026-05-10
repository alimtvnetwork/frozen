"""HKCU Run registry entry for auto-start on user login.

The ``winreg`` import is local; tests inject a fake registry namespace.
"""
from __future__ import annotations

import logging
import sys
from typing import Protocol

from idle_shutdown.config import REGISTRY_RUN_KEY, REGISTRY_RUN_VALUE_NAME
from idle_shutdown.errors import AutostartError
from idle_shutdown.platform import OSKind, current_os

logger = logging.getLogger(__name__)


class RegistryNamespace(Protocol):
    def write_run_value(self, value_name: str, command: str) -> None: ...
    def delete_run_value(self, value_name: str) -> None: ...
    def read_run_value(self, value_name: str) -> str | None: ...


class _Win32Registry:  # pragma: no cover - Windows only
    def write_run_value(self, value_name: str, command: str) -> None:
        import winreg  # type: ignore
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_KEY,
                                    0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, value_name, 0, winreg.REG_SZ, command)
        except OSError as e:
            raise AutostartError(f"registry write failed: {e}") from e

    def delete_run_value(self, value_name: str) -> None:
        import winreg  # type: ignore
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_KEY,
                                0, winreg.KEY_SET_VALUE) as k:
                try:
                    winreg.DeleteValue(k, value_name)
                except FileNotFoundError:
                    return
        except OSError as e:
            raise AutostartError(f"registry delete failed: {e}") from e

    def read_run_value(self, value_name: str) -> str | None:
        import winreg  # type: ignore
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_KEY) as k:
                v, _ = winreg.QueryValueEx(k, value_name)
                return str(v)
        except OSError:
            return None


class _MacLaunchAgent:  # pragma: no cover - macOS only
    """Write/remove ~/Library/LaunchAgents/<label>.plist."""

    LABEL = "com.idle-shutdown.agent"

    def _plist_path(self):
        from pathlib import Path
        return Path.home() / "Library" / "LaunchAgents" / f"{self.LABEL}.plist"

    def write_run_value(self, value_name: str, command: str) -> None:
        import shlex
        try:
            argv = shlex.split(command, posix=True)
        except Exception as e:
            raise AutostartError(f"bad command: {e}") from e
        args_xml = "\n".join(f"      <string>{a}</string>" for a in argv)
        plist = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            f'  <key>Label</key><string>{self.LABEL}</string>\n'
            '  <key>ProgramArguments</key><array>\n' + args_xml + '\n  </array>\n'
            '  <key>RunAtLoad</key><true/>\n'
            '  <key>KeepAlive</key><false/>\n'
            '</dict></plist>\n'
        )
        try:
            p = self._plist_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(plist, encoding="utf-8")
        except OSError as e:
            raise AutostartError(f"plist write failed: {e}") from e

    def delete_run_value(self, value_name: str) -> None:
        try:
            self._plist_path().unlink(missing_ok=True)
        except OSError as e:
            raise AutostartError(f"plist delete failed: {e}") from e

    def read_run_value(self, value_name: str) -> str | None:
        p = self._plist_path()
        return p.read_text(encoding="utf-8") if p.exists() else None


class _LinuxXdgAutostart:  # pragma: no cover - Linux only
    """Write/remove ~/.config/autostart/<name>.desktop."""

    NAME = "idle-shutdown"

    def _desktop_path(self):
        from pathlib import Path
        import os
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(base) / "autostart" / f"{self.NAME}.desktop"

    def write_run_value(self, value_name: str, command: str) -> None:
        body = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Idle Shutdown\n"
            f"Exec={command}\n"
            "X-GNOME-Autostart-enabled=true\n"
            "Terminal=false\n"
        )
        try:
            p = self._desktop_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        except OSError as e:
            raise AutostartError(f"autostart write failed: {e}") from e

    def delete_run_value(self, value_name: str) -> None:
        try:
            self._desktop_path().unlink(missing_ok=True)
        except OSError as e:
            raise AutostartError(f"autostart delete failed: {e}") from e

    def read_run_value(self, value_name: str) -> str | None:
        p = self._desktop_path()
        return p.read_text(encoding="utf-8") if p.exists() else None


def get_default_registry() -> RegistryNamespace:
    kind = current_os()
    if kind is OSKind.MacOS:
        return _MacLaunchAgent()
    if kind is OSKind.Linux:
        return _LinuxXdgAutostart()
    return _Win32Registry()


def build_run_command(executable_path: str) -> str:
    """Quote the exe path and append ``run --silent``.

    On Windows we use double-quotes (registry REG_SZ convention). On POSIX
    the quoting style is the same and works for shell-style ``Exec=`` lines.
    """
    return f'"{executable_path}" run --silent'


def install_autostart(executable_path: str, registry: RegistryNamespace | None = None) -> str:
    reg = registry or get_default_registry()
    command = build_run_command(executable_path)
    reg.write_run_value(REGISTRY_RUN_VALUE_NAME, command)
    logger.info("event=autostart_installed value=%s", REGISTRY_RUN_VALUE_NAME)
    return command


def uninstall_autostart(registry: RegistryNamespace | None = None) -> None:
    reg = registry or get_default_registry()
    reg.delete_run_value(REGISTRY_RUN_VALUE_NAME)
    logger.info("event=autostart_uninstalled value=%s", REGISTRY_RUN_VALUE_NAME)


def is_autostart_installed(registry: RegistryNamespace | None = None) -> bool:
    reg = registry or get_default_registry()
    return reg.read_run_value(REGISTRY_RUN_VALUE_NAME) is not None


def default_executable_path() -> str:
    """Best-effort path to the shipping exe, used when CLI invokes install."""
    if getattr(sys, "frozen", False):
        return sys.executable
    # Dev path: prefer the venv ``idle-shutdown`` console script if present,
    # otherwise fall back to ``python -m idle_shutdown``.
    import shutil as _sh
    found = _sh.which("idle-shutdown")
    if found:
        return found
    return f'{sys.executable} -m idle_shutdown'