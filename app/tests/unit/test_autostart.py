import pytest

from idle_shutdown.autostart import (
    build_run_command,
    install_autostart,
    is_autostart_installed,
    uninstall_autostart,
)
from idle_shutdown.config import REGISTRY_RUN_VALUE_NAME
from idle_shutdown.errors import AutostartError


class FakeRegistry:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.fail_writes = False

    def write_run_value(self, name: str, command: str) -> None:
        if self.fail_writes:
            raise AutostartError("denied")
        self.values[name] = command

    def delete_run_value(self, name: str) -> None:
        self.values.pop(name, None)

    def read_run_value(self, name: str) -> str | None:
        return self.values.get(name)


def test_build_run_command_quotes_path():
    assert build_run_command("C:\\Program Files\\app.exe") == \
        '"C:\\Program Files\\app.exe" run --silent'


def test_install_writes_locked_value_name_and_data():
    reg = FakeRegistry()
    install_autostart("C:\\Apps\\idle-shutdown.exe", registry=reg)
    assert reg.values[REGISTRY_RUN_VALUE_NAME] == \
        '"C:\\Apps\\idle-shutdown.exe" run --silent'
    assert is_autostart_installed(registry=reg)


def test_uninstall_removes_value():
    reg = FakeRegistry()
    install_autostart("C:\\Apps\\x.exe", registry=reg)
    uninstall_autostart(registry=reg)
    assert not is_autostart_installed(registry=reg)


def test_uninstall_when_absent_is_noop():
    reg = FakeRegistry()
    uninstall_autostart(registry=reg)  # must not raise


def test_install_failure_raises_autostart_error():
    reg = FakeRegistry()
    reg.fail_writes = True
    with pytest.raises(AutostartError):
        install_autostart("C:\\Apps\\x.exe", registry=reg)