"""Exception taxonomy. Exit codes are locked in spec/21-app/12-config-and-paths/."""
from __future__ import annotations


class IdleShutdownError(Exception):
    """Base. Carries a numeric exit code mapped to the CLI."""

    exit_code: int = 1

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message


class ConfigError(IdleShutdownError):
    exit_code = 10


class SnapshotError(IdleShutdownError):
    exit_code = 20


class MonitorError(IdleShutdownError):
    exit_code = 21


class RestoreError(IdleShutdownError):
    exit_code = 22


class AutostartError(IdleShutdownError):
    exit_code = 30


class DBNotInitializedError(IdleShutdownError):
    exit_code = 40


class EnvError(IdleShutdownError):
    exit_code = 41


class AlreadyRunningError(IdleShutdownError):
    exit_code = 42