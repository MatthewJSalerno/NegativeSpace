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
    """What the first screen needs: whether a catalog exists and is usable, whether
    it holds anything yet, and how many photos a Copy all and a Move all would take
    (ns_db.TRANSFER_ELIGIBLE, the engine's own rule), whatever the gallery shows."""
    try:
        with connect(db_path) as conn:
            photos = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
            indexed = conn.execute("SELECT COUNT(*) FROM runs WHERE mode = 'INDEX'").fetchone()[0]
            by_status = dict(conn.execute("SELECT status, COUNT(*) FROM photos GROUP BY status").fetchall())
        eligible = {mode: sum(by_status.get(s, 0) for s in statuses)
                    for mode, statuses in ns_db.TRANSFER_ELIGIBLE.items()}
        return {"state": "ok", "detail": None, "photos": photos, "indexed": indexed > 0,
                "eligible": eligible, "copied": by_status.get(PhotoStatus.COPIED, 0)}
    except CatalogUnavailable as exc:
        return {"state": exc.state, "detail": exc.detail, "photos": 0, "indexed": False,
                "eligible": {"copy": 0, "move": 0}, "copied": 0}


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


# No capture date in the photo's EXIF: dated by its file's modification time instead
# (date_source 'file_mtime'), or not dated at all. These are the photos filed under
# Undated (webui-spec 3.1).
_UNDATED = ("(json_extract(p.metadata_json, '$.date_source') = 'file_mtime' "
            "OR json_extract(p.metadata_json, '$.date_taken') IS NULL)")


_DATE_TAKEN = "json_extract(p.metadata_json, '$.date_taken')"
# The largest selection the engine can be handed as --file-ids (jobs.MAX_FILE_IDS).
SELECTION_MAX = 1000


def _dates_clause(dates):
    """The date tree's "Show only" filter: years ("2023"), months ("2023-06") and
    "none" for photos with no date at all, as the timeline groups them. The dates
    are the gallery's own (a file date for an undated photo). None or empty: no filter."""
    if not dates:
        return "", ()
    years = [d for d in dates if len(d) == 4 and d.isdigit()]
    months = [d for d in dates if len(d) == 7 and d[:4].isdigit() and d[4] == "-" and d[5:].isdigit()]
    none = "none" in dates
    if len(years) + len(months) + none != len(dates):
        raise ValueError("dates must be years (2023), months (2023-06) or none")
    parts, params = [], []
    if years:
        parts.append(f"substr({_DATE_TAKEN}, 1, 4) IN ({','.join('?' * len(years))})")
        params += years
    if months:
        parts.append(f"substr({_DATE_TAKEN}, 1, 7) IN ({','.join('?' * len(months))})")
        params += months
    if none:
        parts.append(f"{_DATE_TAKEN} IS NULL")
    return " AND (" + " OR ".join(parts) + ")", tuple(params)


def _filters(q, undated, dates):
    """Search, no-capture-date and date-tree filters, shared by the list, its ids and
    its counts, so Select all takes exactly what the gallery shows."""
    search, search_params = _search_clause(q)
    date_sql, date_params = _dates_clause(dates)
    return search + (f" AND {_UNDATED}" if undated else "") + date_sql, tuple(search_params) + date_params


def _check_view(view, sort=None, page=None, page_size=None):
    if view not in VIEWS:
        raise ValueError(f"unknown view: {view}")
    if sort is not None and sort not in SORTS:
        raise ValueError(f"unknown sort: {sort}")
    if page is not None and (page < 1 or not 1 <= page_size <= 240):
        raise ValueError("page must be at least 1 and page_size between 1 and 240")


def _items(conn, rows) -> list:
    items = []
    for r in rows:
        item = dict(r)
        sha1 = item.pop("sha1_hash")
        item["duplicates"] = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE sha1_hash = ? AND id != ?", (sha1, r["id"])
        ).fetchone()[0] if sha1 else 0
        items.append(item)
    return items


def list_photos(db_path: Path, *, view="all", sort="newest", q=None, page=1, page_size=60, undated=False,
                dates=None) -> dict:
    _check_view(view, sort, page, page_size)
    search, search_params = _search_clause(q)
    date_sql, date_params = _dates_clause(dates)
    filtered, filtered_params = _filters(q, undated, dates)
    with connect(db_path) as conn:
        # The views' counts ignore No capture date, which has its own count: turning it
        # on must not make All photos read as if the library had shrunk.
        counts = {}
        for name, statuses in VIEWS.items():
            counts[name] = conn.execute(
                f"SELECT COUNT(*) FROM photos p WHERE p.status IN ({ns_db.sql_values(statuses)})" + search + date_sql,
                tuple(search_params) + date_params).fetchone()[0]
        total = conn.execute(
            f"SELECT COUNT(*) FROM photos p WHERE p.status IN ({ns_db.sql_values(VIEWS[view])})" + filtered,
            filtered_params).fetchone()[0]
        # How many in this view, search and dates have no capture date, filter on or off, for its label.
        counts["undated"] = conn.execute(
            f"SELECT COUNT(*) FROM photos p WHERE p.status IN ({ns_db.sql_values(VIEWS[view])})"
            + search + f" AND {_UNDATED}" + date_sql, tuple(search_params) + date_params).fetchone()[0]
        rows = conn.execute(
            f"SELECT {_LIST_COLUMNS} FROM photos p WHERE p.status IN ({ns_db.sql_values(VIEWS[view])})"
            + filtered + f" ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?",
            filtered_params + (page_size, (page - 1) * page_size)).fetchall()
        items = _items(conn, rows)
    return {"items": items, "page": page, "page_size": page_size, "total": total, "counts": counts}


def photo_ids(db_path: Path, *, view="all", q=None, undated=False, dates=None, limit=SELECTION_MAX) -> dict:
    """Every photo id the gallery would show for these filters, across all pages, for
    Select all. More than `limit` is refused with the total, never cut short: a
    partial Select all would silently act on some of what the user saw."""
    _check_view(view)
    filtered, params = _filters(q, undated, dates)
    base = f"FROM photos p WHERE p.status IN ({ns_db.sql_values(VIEWS[view])})" + filtered
    with connect(db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        ids = [] if total > limit else [r[0] for r in conn.execute(f"SELECT p.id {base} ORDER BY p.id", params)]
    return {"ids": ids, "total": total, "limit": limit, "over_limit": total > limit}


def photos_by_ids(db_path: Path, ids, *, sort="newest", page=1, page_size=60) -> dict:
    """The selected photos, whatever view, search or dates would hide them, one page at a
    time (webui-spec 2, Show only selected and the review before Copy/Move). `missing` names ids no longer in the catalog,
    so a selection is never silently shortened."""
    _check_view("all", sort, page, page_size)
    if not isinstance(ids, list) or any(type(i) is not int or i < 1 for i in ids) or len(ids) > SELECTION_MAX:
        raise ValueError(f"ids must be a list of at most {SELECTION_MAX:,} photo ids")
    wanted = sorted(set(ids))
    # json_each reads the list as a table, with no write to the catalog.
    join = "FROM photos p JOIN json_each(?) w ON w.value = p.id"
    with connect(db_path) as conn:
        found = {r[0] for r in conn.execute(f"SELECT p.id {join}", (json.dumps(wanted),))}
        rows = conn.execute(f"SELECT {_LIST_COLUMNS} {join} ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?",
                            (json.dumps(wanted), page_size, (page - 1) * page_size)).fetchall()
        items = _items(conn, rows)
    return {"items": items, "page": page, "page_size": page_size, "total": len(found),
            "missing": [i for i in wanted if i not in found]}


def timeline(db_path: Path, *, view="all", q=None, undated=False, dates=None) -> dict:
    """Photos per month for a view and search, newest month first: the date tree's counts
    and the page each month starts on. Months are the recorded date's calendar month (a
    file date for an undated photo, as the gallery shows it); `undated` counts rows with
    no date at all, which every date sort places last. The tree asks without `dates`, so
    an unticked month keeps its count; jumping asks with them, to land on the right page."""
    _check_view(view)
    filtered, params = _filters(q, undated, dates)
    base = f"FROM photos p WHERE p.status IN ({ns_db.sql_values(VIEWS[view])})" + filtered
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


# The EXIF date fields and the offset tag each one pairs with (EXIF 2.31).
_EXIF_DATES = (("taken", "DateTimeOriginal", "OffsetTimeOriginal"),
               ("digitized", "CreateDate", "OffsetTimeDigitized"),
               ("modified", "ModifyDate", "OffsetTime"))


# Keys the engine adds to a photo's metadata beside ExifTool's tags: its own reading of
# the date, and where that reading came from.
_ENGINE_KEYS = {"date_taken", "date_source"}


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
        # The file's modification time as its first scan observed it (source_snapshots),
        # which later rescans, edits and transfers never overwrite (webui-spec 3.1).
        snapshot = conn.execute(
            "SELECT s.file_mtime FROM photo_files pf JOIN source_snapshots s USING(file_id) "
            "WHERE pf.photo_id = ?", (photo_id,)).fetchone()
    camera = " ".join(v for v in (meta.get("Make"), meta.get("Model")) if v) or None
    return {
        "id": p["id"], "status": p["status"],
        "filename": _basename(p["dest_path"] if p["status"] in DELIVERED else p["source_path"]),
        "source_path": p["source_path"], "dest_path": p["dest_path"],
        "dest_path_is_projection": p["status"] not in DELIVERED,
        "has_collision_rename": bool(p["has_name_collision"]),
        "file_size": p["file_size"],
        "file_modified": snapshot["file_mtime"] if snapshot else p["file_mtime"],
        "date_taken": meta.get("date_taken"), "date_source": meta.get("date_source"),
        "camera": camera,
        # A capture time's offset, when the camera recorded one; without it the
        # time zone is unknown and must not be shown as UTC (webui-spec 10).
        "date_offset": meta.get("OffsetTimeOriginal"),
        # Every EXIF date the photo carries, each with the offset recorded for it, if any.
        "exif_dates": [{"field": field, "value": meta[key], "offset": meta.get(offset_key)}
                       for field, key, offset_key in _EXIF_DATES if meta.get(key)],
        "iso": meta.get("ISO"), "aperture": meta.get("FNumber"), "shutter": meta.get("ExposureTime"),
        "width": content["width"] if content else None, "height": content["height"] if content else None,
        "sha1": p["sha1_hash"], "phash": p["phash"],
        "duplicates": copies,
        # Every tag the Index recorded (ExifTool's full set, not a curated subset), for
        # Show all metadata. The engine's own keys, which are not the photo's, are left out.
        "metadata": sorted(([k, v] for k, v in meta.items() if k not in _ENGINE_KEYS),
                           key=lambda kv: kv[0].lower()),
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


# Why a photo was skipped, by the start of the reason the engine recorded. The engine
# writes these sentences (ns-engine.py _duplicate_skip_reason and the Copy/Move loop);
# tests/webui_api_test.py runs real jobs so a reworded reason fails there, not here.
_SKIP_REASONS = (("Duplicate", "duplicate"), ("Already copied", "already_copied"),
                 ("Not attempted: the destination is a network share", "network_share_unconfirmed"),
                 ("Not attempted: the source folder is empty", "source_looked_empty"))


def _skip_reason(message: Optional[str]) -> str:
    if message and message.startswith("Duplicate") and "not part of this selection" in message:
        return "duplicate_original_not_selected"
    for prefix, reason in _SKIP_REASONS:
        if message and message.startswith(prefix):
            return reason
    return "other"


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
    skip_reasons = {}
    for (message,) in conn.execute("SELECT error_message FROM operations WHERE run_id = ? AND status = ? "
                                   "AND reconciles_operation_id IS NULL", (run["id"], OPERATION_SKIPPED)):
        reason = _skip_reason(message)
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
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
            "skip_reasons": skip_reasons,
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


def settings(db_path: Path, *, cpus: dict, supported_extensions) -> dict:
    """Saved settings with their revisions, or the engine's defaults (revision 0) for
    any never saved - the value a job started now would use."""
    with connect(db_path) as conn:
        conn.row_factory = None          # ns_db's schema check compares plain tuples
        saved = ns_db.read_settings(conn)
        retention_default = ns_db.backup_retention(conn)
    defaults = {"workers": cpus["available"], "exts": sorted(supported_extensions),
                "backup_retention": retention_default}
    out = {}
    for key, default in defaults.items():
        entry = saved.get(key, {"value": default, "revision": 0})
        out[key] = {"value": entry["value"], "revision": entry["revision"], "default": default}
    out["exts"]["support"] = [dict(ns_db.extension_support(e), extension=e) for e in out["exts"]["value"]]
    out["workers"]["detected"] = cpus["available"]
    out["workers"]["host"] = cpus["host"]
    out["workers"]["limited_by"] = cpus["limited_by"]
    return out


# --- The operations log and the Error Center (webui-spec 5.3, 5.4) -----------

LOG_PAGE_MAX = 500


def _operations_where(*, runs=None, statuses=None, photo=None, q=None, since=None, until=None):
    """The WHERE clause for a log view. Every filter narrows; none is required.

    `photo` follows the photo's file identities, not only its photos.id: operations
    linked through operation_files to its source identity, or to a copy made from it,
    so a Move or a destination copy stays in its history (webui-spec 6.3). `since` and
    `until` are ISO instants; the engine stores timestamps as UTC ISO strings, which
    compare correctly as text once both sides carry an offset.
    """
    clauses, params = [], []
    if runs:
        clauses.append(f"o.run_id IN ({','.join('?' * len(runs))})")
        params += list(runs)
    if statuses:
        clauses.append(f"o.status IN ({','.join('?' * len(statuses))})")
        params += list(statuses)
    if photo is not None:
        clauses.append("(o.photo_id = ? OR o.id IN (SELECT of.operation_id FROM operation_files of WHERE of.file_id IN ("
                       "  SELECT pf.file_id FROM photo_files pf WHERE pf.photo_id = ?"
                       "  UNION SELECT fo.file_id FROM file_origins fo JOIN photo_files pf ON fo.origin_file_id = pf.file_id"
                       "  WHERE pf.photo_id = ?)))")
        params += [photo, photo, photo]
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append("(o.source_path LIKE ? ESCAPE '\\' OR o.dest_path LIKE ? ESCAPE '\\' "
                       "OR o.error_message LIKE ? ESCAPE '\\')")
        params += [like, like, like]
    if since:
        clauses.append("o.timestamp >= ?")
        params.append(since)
    if until:
        clauses.append("o.timestamp < ?")
        params.append(until)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


_OP_COLUMNS = ("o.id, o.run_id, r.mode, o.photo_id, o.timestamp, o.source_path, o.dest_path, o.status, "
               "o.error_message, p.status AS photo_status, (o.reconciles_operation_id IS NOT NULL) AS recovery")
# Left joins: a failure with no photo (an unreadable folder) must never drop out
# of the Error Center (webui-spec 5.3).
_OP_FROM = "FROM operations o LEFT JOIN runs r ON r.id = o.run_id LEFT JOIN photos p ON p.id = o.photo_id"


def _op_dict(row) -> dict:
    item = dict(row)
    item["recovery"] = bool(item["recovery"])
    # A failure with no photo is about a folder or the run, not a file (webui-spec 5.3).
    item["run_level"] = item["photo_id"] is None
    return item


def list_operations(db_path: Path, *, page=1, page_size=100, **filters) -> dict:
    """One page of the log, newest first, with counts per status for the same filters
    minus the status filter, so the status buttons can show what each would find, and
    counts per job for all of them, so the log can list the jobs that match."""
    if page < 1 or not 1 <= page_size <= LOG_PAGE_MAX:
        raise ValueError(f"page must be at least 1 and page_size between 1 and {LOG_PAGE_MAX}")
    where, params = _operations_where(**filters)
    unfiltered_status = {k: v for k, v in filters.items() if k != "statuses"}
    count_where, count_params = _operations_where(**unfiltered_status)
    with connect(db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) {_OP_FROM}{where}", params).fetchone()[0]
        rows = conn.execute(f"SELECT {_OP_COLUMNS} {_OP_FROM}{where} ORDER BY o.id DESC LIMIT ? OFFSET ?",
                            params + [page_size, (page - 1) * page_size]).fetchall()
        counts = dict(conn.execute(f"SELECT o.status, COUNT(*) {_OP_FROM}{count_where} GROUP BY o.status",
                                   count_params).fetchall())
        per_run = {str(run): n for run, n in conn.execute(
            f"SELECT o.run_id, COUNT(*) {_OP_FROM}{where} GROUP BY o.run_id", params)}
    return {"items": [_op_dict(r) for r in rows], "page": page, "page_size": page_size, "total": total,
            "status_counts": counts, "run_counts": per_run}


def iter_operations(db_path: Path, **filters):
    """Every matching operation, oldest first, for export."""
    where, params = _operations_where(**filters)
    with connect(db_path) as conn:
        for row in conn.execute(f"SELECT {_OP_COLUMNS} {_OP_FROM}{where} ORDER BY o.id", params):
            yield _op_dict(row)


def operation_photo_ids(db_path: Path, limit: int, **filters) -> list:
    """The distinct photos behind matching operations, for retrying failures: taken
    from the operations, never from photos.status, which can disagree with a failed
    attempt (webui-spec 5.3). At most `limit` + 1, so the caller can tell it was cut."""
    where, params = _operations_where(**filters)
    with connect(db_path) as conn:
        return [r[0] for r in conn.execute(
            f"SELECT DISTINCT o.photo_id {_OP_FROM}{where}{' AND' if where else ' WHERE'} o.photo_id IS NOT NULL "
            f"ORDER BY o.photo_id LIMIT ?", params + [limit + 1])]


def list_runs(db_path: Path, limit=100) -> list:
    """The newest runs with their derived outcome, for choosing a job in the log."""
    with connect(db_path) as conn:
        return [_run_dict(conn, row) for row in conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM runs ORDER BY id DESC LIMIT ?", (limit,))]


# --- Catalog backups (webui-spec 9) -------------------------------------------

def _backup_file(backups_dir: Path, name: str) -> Optional[Path]:
    """A recorded backup's file, only if the name is a plain file name: the catalog
    is the engine's, but a path built from it is still checked before it is served."""
    if not name or "/" in name or name in (".", ".."):
        return None
    return backups_dir / name


def backups(db_path: Path, backups_dir: Path, appdata_dir: Path) -> dict:
    """Every recorded backup attempt, newest first, with its file's availability
    observed now. Read-only: the recorded availability is the engine's to update
    (refresh_backup_availability), so an unreachable /backups makes each file
    'unknown' here rather than 'missing' - storage trouble is not deletion."""
    problem = ns_db.backup_storage_problem(backups_dir, appdata_dir)
    reachable = backups_dir.is_dir() and os.access(backups_dir, os.R_OK | os.X_OK)
    with connect(db_path) as conn:
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
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT a.relative_filename FROM backup_attempts t JOIN backup_artifacts a USING(attempt_id) "
            "WHERE t.attempt_id = ? AND t.outcome = 'succeeded' AND a.availability != 'pruned'",
            (attempt_id,)).fetchone()
    path = _backup_file(backups_dir, row[0]) if row else None
    return path if path and path.is_file() else None


def newest_backup_attempt(db_path: Path) -> Optional[dict]:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT t.attempt_id, t.trigger_kind, t.started_at, t.outcome, t.error_category, t.error_detail, "
            "a.relative_filename, a.size FROM backup_attempts t LEFT JOIN backup_artifacts a USING(attempt_id) "
            "ORDER BY t.attempt_id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


# --- A photo's lineage (webui-spec 6.3) ----------------------------------------

def photo_lineage(db_path: Path, photo_id: int) -> Optional[dict]:
    """Everything the catalog records about a photo's files, for the lineage tree: its
    source file and every file descended from it (file_origins), the same for each exact
    duplicate, and every operation that touched any of them with the role each file
    played. The engine proves this assembles for every file in every status (TODO.md
    claim 11); this only reads it."""
    with connect(db_path) as conn:
        photo = conn.execute("SELECT id, sha1_hash, status FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if photo is None:
            return None
        photos = [photo_id] + ([r[0] for r in conn.execute(
            "SELECT id FROM photos WHERE sha1_hash = ? AND id != ? ORDER BY id", (photo["sha1_hash"], photo_id))]
            if photo["sha1_hash"] else [])
        marks = ",".join("?" * len(photos))
        tree = (f"WITH RECURSIVE tree(file_id) AS (SELECT file_id FROM photo_files WHERE photo_id IN ({marks}) "
                "UNION SELECT o.file_id FROM file_origins o JOIN tree t ON o.origin_file_id = t.file_id) ")
        files = [dict(r) for r in conn.execute(
            tree + "SELECT t.file_id, o.origin_file_id, o.kind AS origin_kind, s.current_path AS path, "
            "s.location_role AS role, s.presence_state AS presence, s.sha1_hash, snap.file_size, "
            "snap.source_path AS indexed_path, f.created_at, pf.photo_id, ph.status AS photo_status "
            "FROM tree t JOIN files f ON f.file_id = t.file_id "
            "LEFT JOIN file_origins o ON o.file_id = t.file_id LEFT JOIN file_states s ON s.file_id = t.file_id "
            "LEFT JOIN source_snapshots snap ON snap.file_id = t.file_id "
            "LEFT JOIN photo_files pf ON pf.file_id = t.file_id LEFT JOIN photos ph ON ph.id = pf.photo_id "
            "ORDER BY t.file_id", photos)]
        links = conn.execute(
            tree + "SELECT of.operation_id, of.file_id, of.role FROM operation_files of JOIN tree t USING(file_id) "
            "ORDER BY of.operation_id", photos).fetchall()
        op_ids = sorted({r["operation_id"] for r in links})
        operations = [dict(r) for r in conn.execute(
            "SELECT o.id, o.run_id, r.mode, o.status, o.timestamp, o.error_message, o.photo_id, "
            "o.source_path, o.dest_path, (o.reconciles_operation_id IS NOT NULL) AS recovery "
            f"FROM operations o LEFT JOIN runs r ON r.id = o.run_id WHERE o.id IN ({','.join('?' * len(op_ids))}) "
            "ORDER BY o.id", op_ids)] if op_ids else []
    by_op = {}
    for r in links:
        by_op.setdefault(r["operation_id"], []).append({"file_id": r["file_id"], "role": r["role"]})
    size = next((f["file_size"] for f in files if f["file_size"] is not None), None)
    for f in files:
        # A copy is byte-identical to its origin (verified when made), so it shares its size.
        f["file_size"] = f["file_size"] if f["file_size"] is not None else size
        f["matches"] = bool(photo["sha1_hash"]) and f["sha1_hash"] == photo["sha1_hash"]
    for op in operations:
        op["recovery"] = bool(op["recovery"])
        op["files"] = by_op.get(op["id"], [])
    return {"photo_id": photo_id, "sha1": photo["sha1_hash"], "photos": photos, "files": files, "operations": operations}


# --- Library stats (webui-spec 5.9) ---------------------------------------------

# Why an attempt failed, by the start of the reason the engine recorded; the Error
# Center shows the same attempts, one link away.
_FAILURE_KINDS = (("Not an image", "not_an_image"), ("PermissionError", "permission"),
                  ("Source file changed", "changed_since_index"), ("Duplicate verification failed", "duplicate_check"),
                  ("Insufficient space", "no_space"))
_MEGAPIXEL_BANDS = ((1, "under 1 MP"), (4, "1–4 MP"), (12, "4–12 MP"), (24, "12–24 MP"), (None, "24 MP and up"))


def _failure_kind(message: Optional[str]) -> str:
    for prefix, kind in _FAILURE_KINDS:
        if message and (message.startswith(prefix) or prefix in message[:60]):
            return kind
    return "other"


def _seconds(start: Optional[str], end: Optional[str]) -> Optional[float]:
    from datetime import datetime
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return None


def library_stats(db_path: Path, backups_dir: Path, appdata_dir: Path) -> dict:
    """Everything the Stats page shows, read from the catalog in one pass: the library,
    its dates, duplicates, the work done, and the catalog's health. Only what is
    recorded: figures that need unbuilt features (near-duplicates, EXIF edits) are None."""
    shown = ns_db.sql_values(VIEWS["all"])
    with connect(db_path) as conn:
        photos = conn.execute(
            f"SELECT p.status, p.file_size, COALESCE(CASE WHEN p.status IN ({ns_db.sql_values(DELIVERED)}) "
            "THEN p.dest_path END, p.source_path) AS path, "
            "json_extract(p.metadata_json, '$.Make') AS make, json_extract(p.metadata_json, '$.Model') AS model, "
            "json_extract(p.metadata_json, '$.LensModel') AS lens, "
            "json_extract(p.metadata_json, '$.GPSLatitude') AS gps, "
            "json_extract(p.metadata_json, '$.Orientation') AS orientation, "
            "json_extract(p.metadata_json, '$.date_taken') AS date_taken, "
            "json_extract(p.metadata_json, '$.date_source') AS date_source, "
            "json_extract(p.metadata_json, '$.DateTimeOriginal') AS original, "
            "json_extract(p.metadata_json, '$.OffsetTimeOriginal') AS offset, c.width, c.height "
            f"FROM photos p LEFT JOIN contents c ON c.digest = p.sha1_hash WHERE p.status IN ({shown})").fetchall()
        dup = conn.execute(
            f"SELECT COUNT(*) AS copies, COALESCE(SUM(file_size), 0) AS bytes, "
            f"COALESCE(SUM(CASE WHEN status = ? THEN file_size END), 0) AS in_source, "
            f"COALESCE(SUM(CASE WHEN status = ? THEN file_size END), 0) AS removed, "
            f"COUNT(DISTINCT sha1_hash) AS groups FROM photos WHERE status IN ({ns_db.sql_values(COPIES)})",
            (PhotoStatus.DUPLICATE, PhotoStatus.REMOVED_DUPLICATE)).fetchone()
        ops = dict(conn.execute("SELECT status, COUNT(*) FROM operations GROUP BY status").fetchall())
        moved_bytes = conn.execute(
            "SELECT COALESCE(SUM(p.file_size), 0) FROM operations o JOIN photos p ON p.id = o.photo_id "
            "WHERE o.status IN (?, ?)", (PhotoStatus.COPIED, PhotoStatus.COMPLETED)).fetchone()[0]
        failures = {}
        for (message,) in conn.execute("SELECT error_message FROM operations WHERE status = ?", (PhotoStatus.FAILED,)):
            kind = _failure_kind(message)
            failures[kind] = failures.get(kind, 0) + 1
        runs = conn.execute("SELECT id, mode, status, started_at, ended_at FROM runs ORDER BY id").fetchall()
        transfer_bytes = dict(conn.execute(
            "SELECT o.run_id, SUM(p.file_size) FROM operations o JOIN photos p ON p.id = o.photo_id "
            "WHERE o.status IN (?, ?) GROUP BY o.run_id", (PhotoStatus.COPIED, PhotoStatus.COMPLETED)).fetchall())
        conn.row_factory = None
        cache = [{"size": s, "photos": n, "bytes": b} for s, n, b in ns_db.thumbnail_cache_totals(conn)]
        check = conn.execute("SELECT id, started_at FROM runs WHERE mode = 'CHECK' AND status = ? ORDER BY id DESC LIMIT 1",
                             (RunStatus.COMPLETED,)).fetchone()
        findings = dict(conn.execute("SELECT kind, COUNT(*) FROM destination_findings WHERE run_id = ? GROUP BY kind",
                                     (check[0],)).fetchall()) if check else {}

    # The library
    organized = [p for p in photos if p["status"] in DELIVERED]
    total_bytes = sum(p["file_size"] or 0 for p in photos)
    formats = {}
    for p in photos:
        ext = Path(p["path"] or "").suffix.lower().lstrip(".") or "none"
        f = formats.setdefault(ext, {"format": ext, "photos": 0, "bytes": 0})
        f["photos"] += 1
        f["bytes"] += p["file_size"] or 0
    def top(values, n=8):
        counts = {}
        for v in values:
            if v:
                counts[v] = counts.get(v, 0) + 1
        return [{"name": k, "photos": v} for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]
    cameras = top(" ".join(x for x in (p["make"], p["model"]) if x) or None for p in photos)
    bands = {label: 0 for _, label in _MEGAPIXEL_BANDS}
    portrait = landscape = square = 0
    for p in photos:
        if not p["width"] or not p["height"]:
            continue
        mp = p["width"] * p["height"] / 1e6
        bands[next(label for limit, label in _MEGAPIXEL_BANDS if limit is None or mp < limit)] += 1
        w, h = p["width"], p["height"]
        if "90" in str(p["orientation"] or "") or "270" in str(p["orientation"] or ""):
            w, h = h, w                           # a quarter turn: shown the other way up
        portrait += h > w
        landscape += w > h
        square += w == h

    # Dates: only a date taken from the photo counts; a file date is not one.
    dated = [p for p in photos if p["date_source"] != "file_mtime" and p["date_taken"]]
    years, days = {}, {}
    for p in dated:
        years[p["date_taken"][:4]] = years.get(p["date_taken"][:4], 0) + 1
        days[p["date_taken"][:10]] = days.get(p["date_taken"][:10], 0) + 1
    busiest = max(days.items(), key=lambda kv: (kv[1], kv[0])) if days else None
    undated = [p for p in photos if p["date_source"] == "file_mtime"]
    unusable = sum(1 for p in undated if p["original"])

    # Activity
    mode_counts = {}
    for r in runs:
        mode_counts[r["mode"]] = mode_counts.get(r["mode"], 0) + 1
    last_index = next((r["ended_at"] or r["started_at"] for r in reversed(runs) if r["mode"] == "INDEX"), None)
    moved_seconds = sum(s for r in runs if r["mode"] in ("COPY", "MOVE") and r["id"] in transfer_bytes
                        for s in [_seconds(r["started_at"], r["ended_at"])] if s)
    moved_run_bytes = sum(b for rid, b in transfer_bytes.items() if b)

    status_path = db_path
    catalog_bytes = sum(Path(f"{status_path}{suffix}").stat().st_size
                        for suffix in ("", "-wal") if Path(f"{status_path}{suffix}").exists())
    backup = backups(db_path, backups_dir, appdata_dir)
    return {
        "library": {"photos": len(photos), "bytes": total_bytes,
                    "organized": len(organized), "organized_bytes": sum(p["file_size"] or 0 for p in organized),
                    "not_organized": len(photos) - len(organized),
                    "formats": sorted(formats.values(), key=lambda f: (-f["bytes"], f["format"])),
                    "cameras": cameras, "lenses": top(p["lens"] for p in photos),
                    "megapixels": [{"band": k, "photos": v} for k, v in bands.items()],
                    "under_1mp": bands[_MEGAPIXEL_BANDS[0][1]],
                    "orientation": {"landscape": landscape, "portrait": portrait, "square": square},
                    "with_location": sum(1 for p in photos if p["gps"] is not None)},
        "dates": {"per_year": [{"year": y, "photos": n} for y, n in sorted(years.items())],
                  "oldest": min((p["date_taken"] for p in dated), default=None),
                  "newest": max((p["date_taken"] for p in dated), default=None),
                  "busiest_day": {"day": busiest[0], "photos": busiest[1]} if busiest else None,
                  "undated": len(undated), "undated_no_date": len(undated) - unusable, "undated_unusable": unusable,
                  "with_time_zone": sum(1 for p in dated if p["offset"])},
        "duplicates": {"groups": dup["groups"], "extra_copies": dup["copies"], "bytes": dup["bytes"],
                       "saved_at_destination": dup["bytes"], "move_would_free": dup["in_source"],
                       "freed_by_moves": dup["removed"], "near_duplicates": None},
        "activity": {"jobs": mode_counts, "last_index": last_index,
                     "copied": ops.get(PhotoStatus.COPIED, 0), "moved": ops.get(PhotoStatus.COMPLETED, 0),
                     "bytes_transferred": moved_bytes,
                     "bytes_per_second": round(moved_run_bytes / moved_seconds) if moved_seconds else None,
                     "failures": failures, "renames": ops.get(OPERATION_RENAMED, 0), "exif_edits": None},
        "health": {"last_backup": backup["last_success"], "backup_bytes": backup["present_bytes"],
                   "backups": backup["present_count"], "unbacked_changes": backup["unbacked"]["count"],
                   "catalog_bytes": catalog_bytes, "thumbnail_cache": cache,
                   "destination_check": {"at": check[1], "findings": findings} if check else None},
    }
