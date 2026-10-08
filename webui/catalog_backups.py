"""Catalog backups as the screens list and download them (webui-spec 9)."""

import os
from pathlib import Path
from typing import Optional

from engine import ns_db
from . import catalog


# --- Catalog backups (webui-spec 9) -------------------------------------------

def _backup_file(backups_dir: Path, name: str) -> Optional[Path]:
    """A recorded backup's file, only if the name is a plain file name: the catalog
    is the engine's, but a path built from it is still checked before it is served."""
    if not name or "/" in name or "\0" in name or name in (".", ".."):
        return None
    try:
        root = backups_dir.resolve()
        path = (root / name).resolve()
    except (OSError, RuntimeError):
        return None
    # A plain recorded name may now be a symlink. Serve only resolved files
    # within this storage root, as thumbnail/preview downloads do for cache.
    return path if root in path.parents else None


def backups(db_path: Path, backups_dir: Path, appdata_dir: Path) -> dict:
    """Every recorded backup attempt, newest first, with its file's availability
    observed now. Read-only: the recorded availability is the engine's to update
    (refresh_backup_availability), so an unreachable /backups makes each file
    'unknown' here rather than 'missing' - storage trouble is not deletion."""
    problem = ns_db.backup_storage_problem(backups_dir, appdata_dir)
    reachable = backups_dir.is_dir() and os.access(backups_dir, os.R_OK | os.X_OK)
    with catalog.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT t.attempt_id, t.trigger_kind, t.related_run_id, t.started_at, t.ended_at, t.outcome, "
            "t.error_category, t.error_detail, a.relative_filename, a.size, a.compression_format, "
            "a.availability AS recorded_availability "
            "FROM backup_attempts t LEFT JOIN backup_artifacts a USING(attempt_id) "
            "ORDER BY julianday(t.started_at) DESC, t.attempt_id DESC").fetchall()
        conn.row_factory = None
        unbacked, since, runs = ns_db.unbacked_changes(conn)
        retention = ns_db.backup_retention(conn)
    items = []
    for row in rows:
        item = dict(row)
        recorded = item.pop("recorded_availability")
        if item["relative_filename"] is None:
            item["availability"] = None
        elif recorded == "pruned":
            item["availability"] = "pruned"
        elif not reachable:
            item["availability"] = "unknown"
        else:
            path = _backup_file(backups_dir, item["relative_filename"])
            item["availability"] = "present" if path and path.is_file() else "missing"
        items.append(item)
    present = [i for i in items if i["availability"] == "present"]
    succeeded = [i for i in items if i["outcome"] == "succeeded"]
    return {
        "items": items,
        "storage": {"ok": problem is None, "error_category": problem[0] if problem else None,
                    "error_detail": problem[1] if problem else None},
        "retention": retention,
        "automatic_retained": sum(1 for i in present if i["trigger_kind"] != "manual"),
        "present_count": len(present),
        "present_bytes": sum(i["size"] for i in present),
        "last_success": succeeded[0]["started_at"] if succeeded else None,
        "unbacked": {"count": unbacked, "since": since, "runs": runs},
    }


def backup_download(db_path: Path, backups_dir: Path, attempt_id: int) -> Optional[Path]:
    """The file of a succeeded backup that is present now, or None."""
    with catalog.connect(db_path) as conn:
        row = conn.execute(
            "SELECT a.relative_filename FROM backup_attempts t JOIN backup_artifacts a USING(attempt_id) "
            "WHERE t.attempt_id = ? AND t.outcome = 'succeeded' AND a.availability != 'pruned'",
            (attempt_id,)).fetchone()
    path = _backup_file(backups_dir, row[0]) if row else None
    return path if path and path.is_file() else None


def newest_backup_attempt(db_path: Path) -> Optional[dict]:
    with catalog.connect(db_path) as conn:
        row = conn.execute(
            "SELECT t.attempt_id, t.trigger_kind, t.started_at, t.outcome, t.error_category, t.error_detail, "
            "a.relative_filename, a.size FROM backup_attempts t LEFT JOIN backup_artifacts a USING(attempt_id) "
            "ORDER BY t.attempt_id DESC LIMIT 1").fetchone()
    return dict(row) if row else None
