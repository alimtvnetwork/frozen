import os
import sys
from pathlib import Path

import pytest

# Ensure `idle_shutdown` resolves from the app/ source tree.
APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("IDLE_SHUTDOWN_DB", str(db_file))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    yield db_file