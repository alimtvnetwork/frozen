"""Per-app restore exclusions (Phase 7)."""
from __future__ import annotations

from idle_shutdown.capture.apps import AppInfo
from idle_shutdown.capture.chrome import ChromeSession
from idle_shutdown.db.connection import connect, init_db
from idle_shutdown.db.repos import RestoreExclusionRepo
from idle_shutdown.enums import SnapshotTriggerKind
from idle_shutdown.restore import restore
from idle_shutdown.snapshot import SnapshotProviders, take_snapshot


def _seed(temp_db) -> None:
    init_db()
    apps = [
        AppInfo(executable_path="C:\\Apps\\notepad.exe",
                document_path="C:\\U\\N.TXT",
                working_directory=None, desktop_index=0),
        AppInfo(executable_path="C:\\Apps\\1Password.exe",
                document_path=None,
                working_directory=None, desktop_index=0),
    ]
    providers = SnapshotProviders(
        capture_desktops_fn=lambda: (1, {}),
        enumerate_apps_fn=lambda _pids: apps,
        capture_chrome_fn=lambda: ChromeSession(executable_path=None, profiles=()),
    )
    take_snapshot(SnapshotTriggerKind.Manual, providers, record_log=False)


def test_exclusion_add_list_remove(temp_db):
    init_db()
    with connect() as conn:
        repo = RestoreExclusionRepo(conn)
        repo.add("C:\\Apps\\1Password.exe", reason="password manager")
        rows = repo.list()
        assert len(rows) == 1
        assert rows[0].executable_path == "c:/apps/1password.exe"
        assert rows[0].reason == "password manager"
        # Idempotent (UPSERT updates reason).
        repo.add("C:\\Apps\\1PASSWORD.exe", reason="updated")
        assert repo.list()[0].reason == "updated"
        # Remove.
        assert repo.remove("c:\\apps\\1password.exe") == 1
        assert repo.list() == []


def test_excluded_app_is_not_relaunched(temp_db):
    _seed(temp_db)
    with connect() as conn:
        RestoreExclusionRepo(conn).add("C:\\Apps\\1Password.exe", "vault")

    spawned: list[list[str]] = []
    result = restore(
        live_processes=lambda: [],
        spawn=lambda argv, cwd: spawned.append(argv),
    )
    launched_exes = [c[0] for c in spawned]
    assert "C:\\Apps\\1Password.exe" not in launched_exes
    assert "C:\\Apps\\notepad.exe" in launched_exes
    assert result.apps_launched == 1
    assert result.apps_excluded == 1