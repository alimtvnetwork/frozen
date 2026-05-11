"""Snapshot export to portable JSON or self-contained HTML.

Pure helpers — no I/O. The CLI wires these to ``snapshots_dir()``.
"""
from __future__ import annotations

import html
import json
from dataclasses import asdict

from idle_shutdown.db.repos import SnapshotDetail


def snapshot_to_dict(detail: SnapshotDetail) -> dict:
    return {
        "snapshot_id": detail.snapshot_id,
        "created_at": detail.created_at,
        "trigger": detail.trigger,
        "desktop_count": detail.desktop_count,
        "apps": [asdict(a) for a in detail.apps],
        "tabs": [asdict(t) for t in detail.tabs],
        "profiles": [
            {"profile_dir": p[0], "profile_name": p[1],
             "tab_count": p[2], "browser_name": p[3]}
            for p in detail.profile_summary
        ],
    }


def snapshot_to_json(detail: SnapshotDetail, *, indent: int = 2) -> str:
    return json.dumps(snapshot_to_dict(detail), indent=indent, ensure_ascii=False)


def _e(s: object) -> str:
    return html.escape("" if s is None else str(s))


def snapshot_to_html(detail: SnapshotDetail) -> str:
    """Self-contained HTML report — no external CSS/JS, safe to share."""
    d = detail
    apps_rows = "\n".join(
        f"<tr><td>{_e(a.desktop_index)}</td><td>{_e(a.executable_path)}</td>"
        f"<td>{_e(a.document_path)}</td><td>{_e(a.working_directory)}</td></tr>"
        for a in d.apps
    ) or '<tr><td colspan="4"><em>none</em></td></tr>'
    tabs_rows = "\n".join(
        f"<tr><td>{_e(t.browser_name or 'Chrome')}</td>"
        f"<td>{_e(t.profile_name or t.profile_dir)}</td>"
        f"<td>{_e(t.window_index)}.{_e(t.tab_index)}</td>"
        f"<td>{_e(t.title)}</td>"
        f"<td><a href=\"{_e(t.url)}\">{_e(t.url)}</a></td></tr>"
        for t in d.tabs
    ) or '<tr><td colspan="5"><em>none</em></td></tr>'
    prof_rows = "\n".join(
        f"<tr><td>{_e(p[3])}</td><td>{_e(p[1] or p[0])}</td><td>{_e(p[2])}</td></tr>"
        for p in d.profile_summary
    ) or '<tr><td colspan="3"><em>none</em></td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Snapshot #{d.snapshot_id}</title>
<style>
 body{{font:14px/1.4 -apple-system,Segoe UI,sans-serif;margin:24px;color:#222}}
 h1{{margin:0 0 4px}} .meta{{color:#666;margin-bottom:24px}}
 table{{border-collapse:collapse;width:100%;margin-bottom:24px}}
 th,td{{border:1px solid #ddd;padding:6px 8px;vertical-align:top;text-align:left}}
 th{{background:#f4f4f4}} td{{word-break:break-all}}
 a{{color:#06c;text-decoration:none}} a:hover{{text-decoration:underline}}
</style></head><body>
<h1>Snapshot #{d.snapshot_id}</h1>
<div class="meta">Created {_e(d.created_at)} · trigger <b>{_e(d.trigger)}</b>
 · {d.desktop_count} desktop(s) · {len(d.apps)} app(s) · {len(d.tabs)} tab(s)</div>
<h2>Browser profiles</h2>
<table><thead><tr><th>Browser</th><th>Profile</th><th>Tabs</th></tr></thead>
<tbody>{prof_rows}</tbody></table>
<h2>Apps</h2>
<table><thead><tr><th>Desktop</th><th>Executable</th><th>Document</th><th>CWD</th></tr></thead>
<tbody>{apps_rows}</tbody></table>
<h2>Tabs</h2>
<table><thead><tr><th>Browser</th><th>Profile</th><th>Win.Tab</th><th>Title</th><th>URL</th></tr></thead>
<tbody>{tabs_rows}</tbody></table>
</body></html>
"""