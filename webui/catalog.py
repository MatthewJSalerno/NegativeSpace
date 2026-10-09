"""Catalog reads for the API: the connection, its status, settings and the status sets the screens share. Every write except settings belongs to the engine."""

import contextlib
import json
import re
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engine import ns_db
from engine.ns_db import PhotoStatus, IN_REJECTS_STATUSES


GRID_SIZE = 320
DELIVERED = (PhotoStatus.COMPLETED, PhotoStatus.COPIED, PhotoStatus.FOUND_AT_DESTINATION)
# A Move that delivered a verified copy but could not delete the original is recorded
# as Copied with a reason (ns_db.ORIGINAL_KEPT). The log shows it as its own status,
# derived here and never stored, so it reads as neither a Move nor a failure.
COPIED_ONLY = "Copied_Only"
LOG_STATUSES = ns_db.OPERATION_STATUSES + (COPIED_ONLY,)
_KEPT_LIKE = ns_db.ORIGINAL_KEPT.replace("%", "") + "%"
_OP_STATUS = (f"(CASE WHEN o.status = '{PhotoStatus.COPIED}' AND o.error_message LIKE '{_KEPT_LIKE}' "
              f"THEN '{COPIED_ONLY}' ELSE o.status END)")
NOT_ORGANIZED = (PhotoStatus.PENDING, PhotoStatus.PROCESSING, PhotoStatus.FAILED)
# A duplicate's content is shown once, on its anchor, with a duplicate count: the
# gallery lists photographs, not every copy of one (webui-spec 7.2).
COPIES = (PhotoStatus.DUPLICATE, PhotoStatus.REMOVED_DUPLICATE)
# Every photo whose original is still in the source, for Source folders' "Everything still
# in the source" (webui-spec 2): what is waiting, plus what was copied, or rejected after a
# Copy, whose Move would remove the original. Identical extra copies stay on their
# anchor's card, as everywhere.
STILL_IN_SOURCE = NOT_ORGANIZED + (PhotoStatus.COPIED, PhotoStatus.REJECTED_COPIED)
# Rejected photos leave every other view; the Rejects view shows those whose file is
# still in dest/rejects (engine-spec 9.5).
VIEWS = {"all": DELIVERED + NOT_ORGANIZED, "organized": DELIVERED, "unorganized": NOT_ORGANIZED, "similar": DELIVERED,
         "suspicious": DELIVERED + NOT_ORGANIZED, "rejects": IN_REJECTS_STATUSES, "review": DELIVERED,
         "source": STILL_IN_SOURCE}
# Photos whose catalogued file is at the destination, in the library or in Rejects.
AT_DESTINATION = DELIVERED + IN_REJECTS_STATUSES
# How long one listing of dest/rejects answers "is this file still there", so a gallery
# page reads the folder once rather than every file (in_rejects).
REJECTS_LISTING_SECONDS = 5.0
_rejects_listings = {}
SORTS = {
    "matches": "similar_count DESC, p.id ASC",
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


def _extension(path):
    """A path's file type as the Types filter names it: the extension, lower case, no dot."""
    if not path:
        return None
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _basename(path):
    return path.rsplit("/", 1)[-1] if path else None


def in_rejects(path) -> int:
    """Whether a rejected photo's file is still in Rejects (engine-spec 9.5): the user
    empties dest/rejects outside the app, and the Rejects view must not wait for the
    next job, which records it, to stop showing what is gone. Answered from a listing
    of the folder (a directory read per folder, no file reads), taken at most every
    REJECTS_LISTING_SECONDS; a file the listing does not hold, such as one rejected
    since it was taken, is looked up on its own, so only files really gone cost a
    lookup each. A destination with no library folder beside Rejects is not mounted,
    which proves nothing, so the catalog's word stands."""
    marker = f"/{ns_db.REJECTS_FOLDER}/"
    cut = path.rfind(marker) if path else -1
    if cut < 0:
        return 0
    root = path[:cut + len(marker) - 1]
    now = time.monotonic()
    listed = _rejects_listings.get(root)
    if listed is None or now - listed[0] > REJECTS_LISTING_SECONDS:
        if not os.path.isdir(ns_db.library_root(path[:cut])):
            return 1
        present = set()
        for folder, _, files in os.walk(root):
            present.update(os.path.join(folder, name) for name in files)
        listed = _rejects_listings[root] = (now, present)
    return 1 if path in listed[1] or os.path.lexists(path) else 0


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
        conn.create_function("extension", 1, _extension, deterministic=True)
        conn.create_function("in_rejects", 1, in_rejects)
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
            rejects = rejects_summary(conn)
            rejects["reminder"] = rejects_reminder(conn, rejects)
        eligible = {mode: sum(by_status.get(s, 0) for s in statuses)
                    for mode, statuses in ns_db.TRANSFER_ELIGIBLE.items()}
        return {"state": "ok", "detail": None, "photos": photos, "indexed": indexed > 0,
                "library_photos": sum(by_status.get(s, 0) for s in DELIVERED), "eligible": eligible, "copied": by_status.get(PhotoStatus.COPIED, 0),
                "rejected_with_source": by_status.get(PhotoStatus.REJECTED_COPIED, 0), "rejects": rejects}
    except CatalogUnavailable as exc:
        return {"state": exc.state, "detail": exc.detail, "photos": 0, "indexed": False,
                "eligible": {"copy": 0, "move": 0}, "copied": 0, "rejected_with_source": 0, "rejects": None}


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


def failure_reason(message: Optional[str]) -> Optional[str]:
    """An engine failure message as a reason a person reads, and one that groups: the
    exception name, the error number and the quoted path go, so "OSError: [Errno 30]
    Read-only file system: '/data/source/a.jpg'" reads "Read-only file system"."""
    if not message:
        return None
    text = re.sub(r"^[A-Za-z]*(Error|Exception|Mismatch): ", "", message.strip())
    text = re.sub(r"\[Errno \d+\]\s*", "", text)
    text = re.sub(r"""(:\s*)?('[^']*'|"[^"]*")""", "", text)
    text = re.sub(r"\s+", " ", text).strip(" :.")
    return (text[:117] + "…") if len(text) > 120 else text or None


def kept_reason(message: Optional[str]) -> Optional[str]:
    """Why a Move kept an original, readable and grouping as failure_reason does."""
    if not message or not message.startswith(ns_db.ORIGINAL_KEPT):
        return None
    return failure_reason(message[len(ns_db.ORIGINAL_KEPT):].lstrip(": ")) or "No reason recorded"


def rejects_summary(conn) -> dict:
    """What Rejects holds now (photos, bytes, the oldest reject) and what has been emptied
    from it so far: a rejected photo whose file is gone, recorded by a job or not yet."""
    from . import gallery   # here, not at the top: gallery imports this module as it loads
    in_rejects_sql = gallery._view_clause("rejects")
    row = conn.execute(
        f"SELECT COUNT(*) FILTER (WHERE {in_rejects_sql}), "
        f"COALESCE(SUM(p.file_size) FILTER (WHERE {in_rejects_sql}), 0), "
        f"MIN((SELECT MAX(o.timestamp) FROM operations o WHERE o.photo_id = p.id AND o.status IN (?, ?))) "
        f"FILTER (WHERE {in_rejects_sql}), "
        f"COUNT(*) FILTER (WHERE NOT ({in_rejects_sql})), "
        f"COALESCE(SUM(p.file_size) FILTER (WHERE NOT ({in_rejects_sql})), 0) "
        f"FROM photos p WHERE p.status IN ({ns_db.sql_values(ns_db.REJECTED_STATUSES)})",
        (PhotoStatus.REJECTED, PhotoStatus.REJECTED_COPIED)).fetchone()
    return {"photos": row[0], "bytes": row[1], "oldest_rejected_at": row[2],
            "emptied": {"photos": row[3], "bytes": row[4]}}


def rejects_reminder(conn, summary: dict, now: Optional[datetime] = None) -> dict:
    """Whether Rejects is past a reminder limit (webui-spec 7.8): its size, or its oldest
    reject's age. Each limit is a setting; null switches it off."""
    saved = {k: json.loads(v) for k, v in conn.execute(
        "SELECT key, value_json FROM settings WHERE key IN (?, ?)", tuple(ns_db.REJECTS_REMINDER_DEFAULTS))}
    limits = {k: saved.get(k, default) for k, default in ns_db.REJECTS_REMINDER_DEFAULTS.items()}
    size, days = limits["rejects_reminder_bytes"], limits["rejects_reminder_days"]
    oldest = summary["oldest_rejected_at"]
    age_days = None
    if oldest:
        at = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        age_days = ((now or datetime.now(timezone.utc)) - at).total_seconds() / 86400
    return {"over_size": size is not None and summary["photos"] > 0 and summary["bytes"] >= size,
            "over_age": days is not None and age_days is not None and age_days >= days,
            "bytes_limit": size, "days_limit": days}


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
                "backup_retention": retention_default, "small_image_min": None, "suspicious_min_year": ns_db.SUSPICIOUS_MIN_YEAR_DEFAULT, **ns_db.REJECTS_REMINDER_DEFAULTS}
    out = {}
    for key, default in defaults.items():
        entry = saved.get(key, {"value": default, "revision": 0})
        out[key] = {"value": entry["value"], "revision": entry["revision"], "default": default}
    out["exts"]["support"] = [dict(ns_db.extension_support(e), extension=e) for e in out["exts"]["value"]]
    out["workers"]["detected"] = cpus["available"]
    out["workers"]["host"] = cpus["host"]
    out["workers"]["limited_by"] = cpus["limited_by"]
    return out
