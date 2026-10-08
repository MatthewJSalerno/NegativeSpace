"""Library stats (webui-spec 5.9): the library in figures."""

import json
from pathlib import Path
from typing import Optional

from engine import ns_db
from engine.ns_db import PhotoStatus, RunStatus, OPERATION_RENAMED
from . import catalog, catalog_backups


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


def _coverage(runs) -> dict:
    """How current the duplicate figures are (webui-spec 5.9, 6.2). Coverage is set by the
    last Index that scanned the whole source for every supported type and completed with no
    run-level failure: untargeted, Completed, no photo-less Failed operation, and effective
    extensions covering every type the engine reads. Completing is not covering: an Index
    of a detached source completes, finds nothing and records a run-level failure. Returned
    with the Index runs since that had issues and every run since, of any mode, so the gap
    is shown rather than hidden."""
    def full_scan(r):
        exts = json.loads(r["exts"]) if r["exts"] else None
        every_type = exts is None or ns_db.SUPPORTED_EXTENSIONS <= {e.lower() for e in exts}
        return (r["mode"] == "INDEX" and r["file_ids_filter"] is None and r["status"] == RunStatus.COMPLETED
                and not r["issues"] and every_type)
    covering = [r for r in runs if full_scan(r)]
    last = covering[-1] if covering else None
    since = [r for r in runs if last is None or r["id"] > last["id"]]
    return {"last_complete_scan": last["at"] if last else None,
            "established_by_run": last["id"] if last else None,
            "scans_with_issues_since": sum(1 for r in since if r["mode"] == "INDEX" and r["file_ids_filter"] is None
                                           and r["issues"]),
            "run_ids_since": [r["id"] for r in since]}


def _by_folder(rows, source_root: Optional[Path]) -> list:
    """Duplicates per top-level folder of the source: an archive of the library added in
    its own folder shows how many of its files were copies of photos already catalogued
    (webui-spec 5.9). Which copy is the original is the one indexed first, so a later
    archive carries the duplicates. Files directly in the source root are "" (top level)."""
    if source_root is None:
        return []
    root = str(source_root).rstrip("/") + "/"
    folders = {}
    for path, status, size in rows:
        if not path.startswith(root):
            continue
        rel = path[len(root):]
        name = rel.split("/", 1)[0] if "/" in rel else ""
        f = folders.setdefault(name, {"folder": name, "files": 0, "duplicates": 0, "duplicate_bytes": 0})
        f["files"] += 1
        if status in catalog.COPIES:
            f["duplicates"] += 1
            f["duplicate_bytes"] += size or 0
    return sorted(folders.values(), key=lambda f: f["folder"].lower())


def library_stats(db_path: Path, backups_dir: Path, appdata_dir: Path, source_root: Optional[Path] = None) -> dict:
    """Everything the Stats page shows, read from the catalog in one pass: the library,
    its dates, duplicates, the work done, and the catalog's health. Only what is
    recorded: figures that need unbuilt features (near-duplicates, EXIF edits) are None."""
    shown = ns_db.sql_values(tuple(s for s in catalog.VIEWS["all"] if s != PhotoStatus.FAILED))
    with catalog.connect(db_path) as conn:
        failed_source = conn.execute("SELECT COUNT(*) FROM photos WHERE status=?", (PhotoStatus.FAILED,)).fetchone()[0]
        photos = conn.execute(
            f"SELECT p.status, p.file_size, COALESCE(CASE WHEN p.status IN ({ns_db.sql_values(catalog.DELIVERED)}) "
            "THEN p.dest_path END, p.source_path) AS path, "
            "json_extract(p.metadata_json, '$.Make') AS make, json_extract(p.metadata_json, '$.Model') AS model, "
            "json_extract(p.metadata_json, '$.LensModel') AS lens, "
            "json_extract(p.metadata_json, '$.GPSLatitude') AS gps, "
            "json_extract(p.metadata_json, '$.Orientation') AS orientation, "
            "json_extract(p.metadata_json, '$.date_taken') AS date_taken, "
            "json_extract(p.metadata_json, '$.date_source') AS date_source, "
            "json_extract(p.metadata_json, '$.DateTimeOriginal') AS original, "
            "json_extract(p.metadata_json, '$.OffsetTimeOriginal') AS offset, c.width, c.height "
            f"FROM photos p LEFT JOIN contents c ON c.digest = p.sha1_hash AND c.hash_algorithm = 'sha1' WHERE p.status IN ({shown})").fetchall()
        dup = conn.execute(
            f"SELECT COUNT(*) AS copies, COALESCE(SUM(file_size), 0) AS bytes, "
            f"COALESCE(SUM(CASE WHEN status = ? THEN file_size END), 0) AS in_source, "
            f"COALESCE(SUM(CASE WHEN status = ? THEN file_size END), 0) AS removed, "
            f"COUNT(DISTINCT sha1_hash) AS groups FROM photos WHERE status IN ({ns_db.sql_values(catalog.COPIES)})",
            (PhotoStatus.DUPLICATE, PhotoStatus.REMOVED_DUPLICATE)).fetchone()
        # Saved at the destination only once the content is delivered there (webui-spec 5.9):
        # a duplicate whose original is not yet copied has saved nothing so far.
        saved = conn.execute(
            f"SELECT COUNT(*), COALESCE(SUM(d.file_size), 0) FROM photos d WHERE d.status IN ({ns_db.sql_values(catalog.COPIES)}) "
            "AND EXISTS (SELECT 1 FROM photos a WHERE a.sha1_hash = d.sha1_hash AND a.id != d.id AND a.status IN (?, ?))",
            (PhotoStatus.COPIED, PhotoStatus.COMPLETED)).fetchone()
        # Coverage (webui-spec 6.2): every run, with what decides whether it established it.
        coverage_runs = conn.execute(
            "SELECT r.id, r.mode, r.status, r.file_ids_filter, COALESCE(r.ended_at, r.started_at) AS at, "
            "EXISTS (SELECT 1 FROM operations o WHERE o.run_id = r.id AND o.status = ? AND o.photo_id IS NULL) AS issues, "
            "json_extract(c.effective_config_json, '$.exts') AS exts "
            "FROM runs r LEFT JOIN run_configs c ON c.run_id = r.id ORDER BY r.id", (PhotoStatus.FAILED,)).fetchall()
        every_file = conn.execute("SELECT source_path, status, file_size FROM photos WHERE source_path IS NOT NULL").fetchall()
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
        rejects = catalog.rejects_summary(conn)
        findings = dict(conn.execute("SELECT kind, COUNT(*) FROM destination_findings WHERE run_id = ? GROUP BY kind",
                                     (check[0],)).fetchall()) if check else {}

    # The library
    organized = [p for p in photos if p["status"] in catalog.DELIVERED]
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
            if v is not None and v != "":
                v = str(v)
                counts[v] = counts.get(v, 0) + 1
        return [{"name": k, "photos": v} for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]
    # Metadata JSON may contain numeric model/lens identifiers; display labels
    # are text, while zero is a valid identifier rather than missing metadata.
    cameras = top(" ".join(str(x) for x in (p["make"], p["model"]) if x is not None and x != "") or None
                  for p in photos)
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
    backup = catalog_backups.backups(db_path, backups_dir, appdata_dir)
    return {
        "library": {"failed_source": failed_source, "photos": len(photos), "bytes": total_bytes,
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
                       "saved_at_destination": saved[1], "copies_not_written": saved[0],
                       "move_would_free": dup["in_source"], "freed_by_moves": dup["removed"], "near_duplicates": None,
                       "coverage": _coverage(coverage_runs),
                       "by_folder": _by_folder(every_file, source_root)},
        "activity": {"jobs": mode_counts, "last_index": last_index,
                     "copied": ops.get(PhotoStatus.COPIED, 0), "moved": ops.get(PhotoStatus.COMPLETED, 0),
                     "bytes_transferred": moved_bytes,
                     "bytes_per_second": round(moved_run_bytes / moved_seconds) if moved_seconds else None,
                     "failures": failures, "renames": ops.get(OPERATION_RENAMED, 0), "exif_edits": None},
        "rejects": rejects,
        "health": {"last_backup": backup["last_success"], "backup_bytes": backup["present_bytes"],
                   "backups": backup["present_count"], "unbacked_changes": backup["unbacked"]["count"],
                   "catalog_bytes": catalog_bytes, "thumbnail_cache": cache,
                   "destination_check": {"at": check[1], "findings": findings} if check else None},
    }
