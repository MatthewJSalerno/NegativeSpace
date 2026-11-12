"""Check library's screens (webui-spec 7.6): the sidebar's library status, one check's
findings for its Logs entry, and their export. Reads only."""

import csv
import io
import json
from pathlib import Path
from typing import Optional

from engine import repair, library_check

from . import catalog

# Fields each exported finding carries (webui-spec 7.6).
EXPORT_COLUMNS = ("finding", "tone", "relative", "path", "folder", "found_in", "found_path", "size", "checksum",
                  "photo_id", "what", "todo", "repaired_by")


def _last_index(conn, source: Path) -> Optional[dict]:
    """The latest Completed Index of the whole source with no run-level failure, the
    rule Index coverage uses (engine/index_history.py)."""
    row = conn.execute(
        "SELECT r.id, r.ended_at FROM runs r WHERE r.mode = 'INDEX' AND r.status = 'Completed' "
        "AND r.ended_at IS NOT NULL AND r.file_ids_filter IS NULL AND rtrim(r.source_path, '/') = ? "
        "AND NOT EXISTS (SELECT 1 FROM operations o WHERE o.run_id = r.id "
        "AND o.photo_id IS NULL AND o.status = 'Failed') ORDER BY r.id DESC LIMIT 1",
        (str(source).rstrip('/'),)).fetchone()
    return {"run_id": row[0], "at": row[1]} if row else None


def status(db_path: Path, source: Path) -> dict:
    """The sidebar's status: the source's last Index, the newest check (running,
    stopped or finished) and the newest completed one, which a later check that could
    not run leaves standing."""
    with catalog.connect(db_path) as conn:
        conn.row_factory = None
        newest = library_check.latest(conn)
        done = library_check.latest(conn, completed=True)
        return {"source": _last_index(conn, source),
                "latest": library_check.report(conn, newest[0], findings=False) if newest else None,
                "result": library_check.report(conn, done[0], findings=False) if done else None}


def findings(db_path: Path, run_id: int, page: int, page_size: int) -> Optional[dict]:
    """One check's findings, most serious first, a page at a time."""
    with catalog.connect(db_path) as conn:
        conn.row_factory = None
        result = library_check.report(conn, run_id)
    if result is None:
        return None
    every = result.pop("findings")
    start = (page - 1) * page_size
    return {**result, "total": len(every), "page": page, "findings": every[start:start + page_size]}


def export(db_path: Path, run_id: int, form: str):
    """Every finding of one check as CSV or JSON text chunks, or None if no such check."""
    with catalog.connect(db_path) as conn:
        conn.row_factory = None
        result = library_check.report(conn, run_id)
    if result is None:
        return None
    rows = [{k: f.get(k) for k in EXPORT_COLUMNS} for f in result["findings"]]
    if form == "json":
        return [json.dumps(rows)]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return [out.getvalue()]


def is_library_check(conn, run_id: int) -> bool:
    return conn.execute("SELECT 1 FROM library_checks WHERE run_id=?", (run_id,)).fetchone() is not None



# What the Repair preview shows of each planned change (webui-spec 7.6): paths from the
# Library or the destination folder, never the app's own paths inside its container.
_REPAIR_ITEM = ("photo_id", "relative", "finding", "what", "todo", "repair", "from_relative", "to_relative",
                "folder", "index_source")


def repair_preview(db_path: Path, dest: Path, photo_ids) -> dict:
    """Repair's preview for the given photos, or every photo the latest check found."""
    with catalog.connect(db_path) as conn:
        found = repair.plan(conn, dest, photo_ids)
    keep = lambda item: {k: item[k] for k in _REPAIR_ITEM if k in item}
    return {**found, "groups": [{**g, "items": [keep(i) for i in g["items"]]} for g in found["groups"]],
            "cannot": [keep(i) for i in found["cannot"]]}
