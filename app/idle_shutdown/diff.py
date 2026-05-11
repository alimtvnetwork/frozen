"""Pure-functional diff between two ``SnapshotDetail`` records.

Identity rules (chosen so trivial reorderings don't show up as churn):
- App identity: ``(normpath(exe), normpath(document) or "")``.
- Tab identity: ``(browser_name or "Chrome", profile_dir or "", url)``.

Window/tab indices and titles are intentionally ignored — Chrome reshuffles
them across sessions, which would otherwise drown the real signal.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from idle_shutdown.db.repos import AppRow, SnapshotDetail, TabRow


def _norm(p: str | None) -> str:
    if not p:
        return ""
    return os.path.normpath(p.replace("\\", os.sep)).lower()


def _app_key(a: AppRow) -> tuple[str, str]:
    return (_norm(a.executable_path), _norm(a.document_path))


def _tab_key(t: TabRow) -> tuple[str, str, str]:
    return (
        (t.browser_name or "Chrome"),
        (t.profile_dir or ""),
        t.url,
    )


@dataclass(frozen=True)
class SnapshotDiff:
    a_id: int
    b_id: int
    apps_added: list[AppRow]
    apps_removed: list[AppRow]
    tabs_added: list[TabRow]
    tabs_removed: list[TabRow]

    @property
    def is_empty(self) -> bool:
        return not (self.apps_added or self.apps_removed
                    or self.tabs_added or self.tabs_removed)


def compute_snapshot_diff(a: SnapshotDetail, b: SnapshotDetail) -> SnapshotDiff:
    """Return changes going from snapshot ``a`` to snapshot ``b``."""
    a_app_keys = {_app_key(x) for x in a.apps}
    b_app_keys = {_app_key(x) for x in b.apps}
    apps_added = [x for x in b.apps if _app_key(x) not in a_app_keys]
    apps_removed = [x for x in a.apps if _app_key(x) not in b_app_keys]

    a_tab_keys = {_tab_key(x) for x in a.tabs}
    b_tab_keys = {_tab_key(x) for x in b.tabs}
    tabs_added = [x for x in b.tabs if _tab_key(x) not in a_tab_keys]
    tabs_removed = [x for x in a.tabs if _tab_key(x) not in b_tab_keys]

    return SnapshotDiff(
        a_id=a.snapshot_id,
        b_id=b.snapshot_id,
        apps_added=apps_added,
        apps_removed=apps_removed,
        tabs_added=tabs_added,
        tabs_removed=tabs_removed,
    )