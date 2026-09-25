"""Catalog reads for the API. Every write except settings belongs to the engine."""
import contextlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

import ns_db
from ns_db import PhotoStatus, RunStatus, OPERATION_SKIPPED, OPERATION_CANCELLED, OPERATION_RENAMED

GRID_SIZE = 320
DELIVERED = (PhotoStatus.COMPLETED, PhotoStatus.COPIED, PhotoStatus.FOUND_AT_DESTINATION)
NOT_ORGANIZED = (PhotoStatus.PENDING, PhotoStatus.PROCESSING, PhotoStatus.FAILED)
# A duplicate's content is shown once, on its anchor, with a duplicate count: the
# gallery lists photographs, not every copy of one (webui-spec 7.2).
COPIES = (PhotoStatus.DUPLICATE, PhotoStatus.REMOVED_DUPLICATE)
VIEWS = {"all": DELIVERED + NOT_ORGANIZED, "organized": DELIVERED, "unorganized": NOT_ORGANIZED}
SORTS = {
    # Undated rows carry their modification-time fallback in date_taken, labelled by
    # date_source (webui-spec 3.1); a row with no date at all sorts last either way.
    "newest": "(date_taken IS NULL), date_taken DESC, p.id DESC",
    "oldest": "(date_taken IS NULL), date_taken ASC, p.id ASC",
    "largest": "p.file_size DESC, p.id DESC",
    "smallest": "p.file_size ASC, p.id ASC",
    "name": "filename COLLATE NOCASE ASC, p.id ASC",
}


class CatalogUnavailable(Exception):
    """No usable catalog: `state` is missing, incompatible or error, with a reason."""

    def __init__(self, state: str, detail: str):
        super().__init__(detail)
        self.state, self.detail = state, detail


def _basename(path):
    return path.rsplit("/", 1)[-1] if path else None


@contextlib.contextmanager
def connect(db_path: Path):
    """A catalog connection for reads. Never creates a catalog: a missing one is
    reported, not silently replaced (webui-spec 3)."""
    if not db_path.exists():
        raise CatalogUnavailable("missing", "No catalog found.")
    try:
        conn = ns_db.connect(db_path)
    except sqlite3.Error as exc:
        raise CatalogUnavailable("error", f"The catalog could not be opened: {exc}") from exc
    try:
        try:
            ns_db.require_schema(conn)
        except ns_db.SchemaError as exc:
            raise CatalogUnavailable(
                "incompatible", f"{exc}. The catalog was left as it is; this version of NegativeSpace "
                                f"cannot read it.") from exc
        conn.create_function("basename", 1, _basename, deterministic=True)
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()


def status(db_path: Path) -> dict:
    """What the first screen needs: whether a catalog exists and is usable, and
    whether it holds anything yet."""
    try:
        with connect(db_path) as conn:
            photos = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
            indexed = conn.execute("SELECT COUNT(*) FROM runs WHERE mode = 'INDEX'").fetchone()[0]
        return {"state": "ok", "detail": None, "photos": photos, "indexed": indexed > 0}
    except CatalogUnavailable as exc:
        return {"state": exc.state, "detail": exc.detail, "photos": 0, "indexed": False}


def create(db_path: Path) -> dict:
    """Creates an empty catalog with default settings, without running an Index.
    Refuses to replace one that exists, including one appearing since the user
    was shown that there was none (webui-spec 3)."""
    if db_path.exists():
        raise FileExistsError("A catalog already exists; nothing was replaced.")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    probe = db_path.parent / ".write-test"
    try:
        probe.write_text("")
        probe.unlink()
    except OSError as exc:
        raise PermissionError(f"Application data is not writable ({exc}).") from exc
    ns_db.initialize(db_path)
    return status(db_path)


_LIST_COLUMNS = f"""
    p.id, p.status, p.file_size, p.sha1_hash,
    json_extract(p.metadata_json, '$.date_taken') AS date_taken,
    json_extract(p.metadata_json, '$.date_source') AS date_source,
    basename(COALESCE(CASE WHEN p.status IN ({ns_db.sql_values(DELIVERED)}) THEN p.dest_path END,
                      p.source_path)) AS filename
"""


def _search_clause(q: Optional[str]):
    """Filename search: current and original names, including names of removed
    duplicates of the same content, never folder names (webui-spec 2)."""
    if not q:
        return "", ()
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return (" AND (basename(p.source_path) LIKE ? ESCAPE '\\' OR basename(p.dest_path) LIKE ? ESCAPE '\\'"
            " OR EXISTS (SELECT 1 FROM photos d WHERE d.sha1_hash = p.sha1_hash AND d.id != p.id"
            "            AND basename(d.source_path) LIKE ? ESCAPE '\\'))", (like, like, like))


def list_photos(db_path: Path, *, view="all", sort="newest", q=None, page=1, page_size=60) -> dict:
    if view not in VIEWS:
        raise ValueError(f"unknown view: {view}")
    if sort not in SORTS:
        raise ValueError(f"unknown sort: {sort}")
    if page < 1 or not 1 <= page_size <= 200:
        raise ValueError("page must be at least 1 and page_size between 1 and 200")
    search, search_params = _search_clause(q)
    with connect(db_path) as conn:
        counts = {}
        for name, statuses in VIEWS.items():
            counts[name] = conn.execute(
                f"SELECT COUNT(*) FROM photos p WHERE p.status IN ({ns_db.sql_values(statuses)})" + search,
                search_params).fetchone()[0]
        rows = conn.execute(
            f"SELECT {_LIST_COLUMNS} FROM photos p WHERE p.status IN ({ns_db.sql_values(VIEWS[view])})"
            + search + f" ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?",
            search_params + (page_size, (page - 1) * page_size)).fetchall()
        items = []
        for r in rows:
            item = dict(r)
            sha1 = item.pop("sha1_hash")
            item["duplicates"] = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE sha1_hash = ? AND id != ?", (sha1, r["id"])
            ).fetchone()[0] if sha1 else 0
            items.append(item)
    return {"items": items, "page": page, "page_size": page_size, "total": counts[view], "counts": counts}


def timeline(db_path: Path, *, view="all", q=None) -> dict:
    """Photos per month for a view and search, newest month first, for jumping to a date
    in a large library. Months are the recorded date's calendar month (a file date for an
    undated photo, as the gallery shows it); `undated` counts rows with no date at all,
    which every date sort places last."""
    if view not in VIEWS:
        raise ValueError(f"unknown view: {view}")
    search, params = _search_clause(q)
    base = f"FROM photos p WHERE p.status IN ({ns_db.sql_values(VIEWS[view])})" + search
    with connect(db_path) as conn:
        months = [{"month": r[0], "count": r[1]} for r in conn.execute(
            f"SELECT substr(json_extract(p.metadata_json, '$.date_taken'), 1, 7) AS month, COUNT(*) {base} "
            "AND json_extract(p.metadata_json, '$.date_taken') IS NOT NULL GROUP BY month ORDER BY month DESC",
            params)]
        undated = conn.execute(
            f"SELECT COUNT(*) {base} AND json_extract(p.metadata_json, '$.date_taken') IS NULL", params).fetchone()[0]
    return {"months": months, "undated": undated}


def thumbnail_record(conn, photo_id: int, size: int):
    """The cache record for a photo's content at `size`: (cache_filename, availability,
    failure_category, failure_detail), or None when nothing was recorded (pending)."""
    row = conn.execute(
        "SELECT t.cache_filename, t.availability, t.failure_category, t.failure_detail FROM photos p "
        "JOIN contents c ON c.digest = p.sha1_hash "
        "JOIN thumbnail_cache t ON t.content_id = c.content_id AND t.size = ? WHERE p.id = ?",
        (size, photo_id)).fetchone()
    return tuple(row) if row else None


def photo_exists(conn, photo_id: int) -> bool:
    return conn.execute("SELECT 1 FROM photos WHERE id = ?", (photo_id,)).fetchone() is not None


def inspect_photo(db_path: Path, photo_id: int) -> Optional[dict]:
    """The Inspector's details (webui-spec 4.2, 6.2): paths, dates with their source,
    hashes, dimensions, camera, and every catalogued copy of the same content."""
    with connect(db_path) as conn:
        p = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if p is None:
            return None
        meta = json.loads(p["metadata_json"]) if p["metadata_json"] else {}
        content = conn.execute("SELECT width, height FROM contents WHERE digest = ?",
                               (p["sha1_hash"],)).fetchone() if p["sha1_hash"] else None
        copies = [dict(r) for r in conn.execute(
            "SELECT id, status, source_path, dest_path, file_size FROM photos "
            "WHERE sha1_hash = ? AND id != ? ORDER BY id", (p["sha1_hash"], photo_id))] if p["sha1_hash"] else []
        grid = thumbnail_record(conn, photo_id, GRID_SIZE)
        # The file's own times as its first scan observed them (source_snapshots),
        # which later rescans, edits and transfers never overwrite (webui-spec 3.1).
        snapshot = conn.execute(
            "SELECT s.birthtime, s.file_mtime FROM photo_files pf JOIN source_snapshots s USING(file_id) "
            "WHERE pf.photo_id = ?", (photo_id,)).fetchone()
    camera = " ".join(v for v in (meta.get("Make"), meta.get("Model")) if v) or None
    return {
        "id": p["id"], "status": p["status"],
        "filename": _basename(p["dest_path"] if p["status"] in DELIVERED else p["source_path"]),
        "source_path": p["source_path"], "dest_path": p["dest_path"],
        "dest_path_is_projection": p["status"] not in DELIVERED,
        "has_collision_rename": bool(p["has_name_collision"]),
        "file_size": p["file_size"],
        # Epoch seconds, or None: many filesystems (NFS among them) report no creation time.
        "file_created": snapshot["birthtime"] if snapshot else None,
        "file_modified": snapshot["file_mtime"] if snapshot else p["file_mtime"],
        "date_taken": meta.get("date_taken"), "date_source": meta.get("date_source"),
        "camera": camera,
        # A capture time's offset, when the camera recorded one; without it the
        # time zone is unknown and must not be shown as UTC (webui-spec 10).
        "date_offset": meta.get("OffsetTimeOriginal"),
        "iso": meta.get("ISO"), "aperture": meta.get("FNumber"), "shutter": meta.get("ExposureTime"),
        "width": content["width"] if content else None, "height": content["height"] if content else None,
        "sha1": p["sha1_hash"], "phash": p["phash"],
        "duplicates": copies,
        "thumbnail": {"availability": grid[1] if grid else "pending",
                      "failure_category": grid[2] if grid else None,
                      "failure_detail": grid[3] if grid else None},
    }


# --- Runs and their derived outcome (webui-spec 5.5) -------------------------

# Per phase: which progress outcomes are the work the user asked for having
# happened, which are failures, and which are deliberate non-actions.
_SUCCESS = {"indexed", "duplicates", PhotoStatus.COPIED, PhotoStatus.COMPLETED,
            PhotoStatus.FOUND_AT_DESTINATION, PhotoStatus.REMOVED_DUPLICATE, "made", "ok", OPERATION_RENAMED}
_FAILURE = {"failed", PhotoStatus.FAILED, "missing", "changed", "unreadable"}
_SKIPPED = {"unchanged", OPERATION_SKIPPED, "already", "kept", "Already_Gone", "unknown"}
_REQUESTED_PHASES = {"INDEX": ("scanning",), "COPY": ("scanning", "transferring"),
                     "MOVE": ("scanning", "transferring", "removing_duplicates"),
                     "REBUILD": ("rebuilding_thumbnails",), "CHECK": ("checking_destination",)}
_TERMINAL_WINS = {RunStatus.CANCELLED: "cancelled", RunStatus.INTERRUPTED: "interrupted",
                  RunStatus.FAILED: "failed"}


def _outcome(conn, run: dict, progress: list) -> dict:
    """A run's result as the user should read it, not its lifecycle status: a run
    where every file failed still ends Completed.

    Requested work comes from the run's progress counts, which exclude recovery of
    earlier work and run-level issues by construction (engine-spec 4.3). For a Copy or
    Move the transfer phases are the requested work; its scan is reported alongside.
    """
    phases = {p["phase"]: p for p in progress}
    wanted = _REQUESTED_PHASES.get(run["mode"], ())
    main = [phases[name] for name in wanted if name in phases and
            (run["mode"] in ("INDEX", "REBUILD", "CHECK") or name != "scanning")]
    counts = {}
    for p in main:
        for key, n in p["counts"].items():
            counts[key] = counts.get(key, 0) + n
    succeeded = sum(n for k, n in counts.items() if k in _SUCCESS)
    failed = sum(n for k, n in counts.items() if k in _FAILURE)
    skipped = sum(n for k, n in counts.items() if k in _SKIPPED)
    cancelled = counts.get(OPERATION_CANCELLED, 0)
    issues = conn.execute(
        "SELECT COUNT(*) FROM operations WHERE run_id = ? AND photo_id IS NULL AND status = ? "
        "AND reconciles_operation_id IS NULL", (run["id"], PhotoStatus.FAILED)).fetchone()[0]
    recovered = conn.execute("SELECT COUNT(*) FROM operations WHERE run_id = ? AND "
                             "reconciles_operation_id IS NOT NULL", (run["id"],)).fetchone()[0]
    if run["status"] in ns_db.ACTIVE_RUN_STATUSES:
        verdict = "running"
    elif run["status"] in _TERMINAL_WINS:
        verdict = _TERMINAL_WINS[run["status"]]
    elif succeeded and not failed and not issues:
        verdict = "success"
    elif succeeded:
        verdict = "partial"
    elif failed or issues:
        verdict = "failed"
    else:
        verdict = "no_change"
    total = sum(p["total"] or 0 for p in main) if main and all(p["total"] is not None for p in main) else None
    return {"verdict": verdict, "succeeded": succeeded, "failed": failed, "skipped": skipped,
            "cancelled": cancelled, "run_level_issues": issues, "recovered_earlier_work": recovered,
            "total": total, "counts": counts}


def _run_dict(conn, row) -> dict:
    run = dict(row)
    run["targeting"] = json.loads(run.pop("file_ids_filter")) if run.get("file_ids_filter") else None
    run["progress"] = ns_db.read_progress(conn, run["id"])
    run["outcome"] = _outcome(conn, run, run["progress"])
    return run


_RUN_COLUMNS = "id, mode, status, started_at, ended_at, file_ids_filter, reconciled_by_run_id"


def get_run(db_path: Path, run_id: int) -> Optional[dict]:
    with connect(db_path) as conn:
        row = conn.execute(f"SELECT {_RUN_COLUMNS} FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run_dict(conn, row) if row else None


def newest_active_run(db_path: Path) -> Optional[dict]:
    """The newest run recorded Preparing, Running or Cancelling - which may be a run
    whose engine died; the caller decides that from the lock (webui-spec 5.7)."""
    try:
        with connect(db_path) as conn:
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM runs WHERE status IN "
                f"({ns_db.sql_values(ns_db.ACTIVE_RUN_STATUSES)}) ORDER BY id DESC LIMIT 1").fetchone()
            return _run_dict(conn, row) if row else None
    except CatalogUnavailable:
        return None


def last_run(db_path: Path) -> Optional[dict]:
    try:
        with connect(db_path) as conn:
            row = conn.execute(f"SELECT {_RUN_COLUMNS} FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            return _run_dict(conn, row) if row else None
    except CatalogUnavailable:
        return None


def run_for_request(db_path: Path, request_id: str) -> Optional[int]:
    """The run an engine created for a request ID, once it has (engine-spec 4.1)."""
    if not db_path.exists():
        return None
    try:
        with contextlib.closing(ns_db.connect(db_path)) as conn:
            row = conn.execute("SELECT run_id FROM job_requests WHERE request_id = ?", (request_id,)).fetchone()
            return row[0] if row else None
    except sqlite3.Error:
        return None


def cache_file(cache_root: Path, cache_filename: str) -> Optional[Path]:
    """A recorded cache filename as a file under the cache root, or None if it
    escapes the root or is not there. A stored path does not guarantee the file."""
    root = cache_root.resolve()
    path = (root / cache_filename).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def settings(db_path: Path, *, detected_workers: int, supported_extensions) -> dict:
    """Saved settings with their revisions, or the engine's defaults (revision 0) for
    any never saved - the value a job started now would use."""
    with connect(db_path) as conn:
        conn.row_factory = None          # ns_db's schema check compares plain tuples
        saved = ns_db.read_settings(conn)
        retention_default = ns_db.backup_retention(conn)
    defaults = {"workers": detected_workers, "exts": sorted(supported_extensions),
                "backup_retention": retention_default}
    out = {}
    for key, default in defaults.items():
        entry = saved.get(key, {"value": default, "revision": 0})
        out[key] = {"value": entry["value"], "revision": entry["revision"], "default": default}
    out["exts"]["support"] = [dict(ns_db.extension_support(e), extension=e) for e in out["exts"]["value"]]
    out["workers"]["detected"] = detected_workers
    return out
