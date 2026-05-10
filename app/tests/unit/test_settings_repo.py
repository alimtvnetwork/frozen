import time

import pytest

from idle_shutdown.db.connection import connect, init_db
from idle_shutdown.db.repos import SettingsRepo
from idle_shutdown.errors import ConfigError


def test_get_returns_typed_value(temp_db):
    init_db()
    with connect() as conn:
        assert SettingsRepo(conn).get("IdleThresholdMinutes") == 10
        assert SettingsRepo(conn).get("AutoRestoreOnBoot") is True


def test_set_rejects_out_of_range(temp_db):
    init_db()
    with connect() as conn:
        with pytest.raises(ConfigError):
            SettingsRepo(conn).set("IdleThresholdMinutes", 0)
        with pytest.raises(ConfigError):
            SettingsRepo(conn).set("PopupCountdownSeconds", 10)


def test_set_rejects_unknown_key(temp_db):
    init_db()
    with connect() as conn:
        with pytest.raises(ConfigError):
            SettingsRepo(conn).set("Bogus", "x")


def test_set_updates_updated_at(temp_db):
    init_db()
    with connect() as conn:
        repo = SettingsRepo(conn)
        before = next(r.updated_at for r in repo.all() if r.key == "IdleThresholdMinutes")
        time.sleep(0.01)
        repo.set("IdleThresholdMinutes", 15)
        after = next(r.updated_at for r in repo.all() if r.key == "IdleThresholdMinutes")
    assert after > before