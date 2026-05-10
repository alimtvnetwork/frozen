"""HKCU Run registry entry for auto-start on user login.

The ``winreg`` import is local; tests inject a fake registry namespace.
"""
from __future__ import annotations

import logging
import sys
from typing import Protocol

from idle_shutdown.config import REGISTRY_RUN_KEY, REGISTRY_RUN_VALUE_NAME
from idle_shutdown.errors import AutostartError

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


def get_default_registry() -> RegistryNamespace:
    return _Win32Registry()


def build_run_command(executable_path: str) -> str:
    """Quote the exe path and append ``run --silent``."""
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
    # Dev path: ``python -m idle_shutdown``
    return f'{sys.executable} -m idle_shutdown'