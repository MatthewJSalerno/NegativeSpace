"""The destination: where a file is filed, Rejects and library paths, content already there."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from engine.ns_db import PhotoStatus
from engine import constants, fileinfo, ns_db, runtime


def get_unique_dest_path(target_path: Path) -> Path:
    """Thin wrapper kept for callers that only want a free name, no content check."""
    resolved, _ = resolve_destination(target_path, None)
    return resolved


def resolve_destination(target_path: Path, expected_sha1: Optional[str]) -> tuple:
    """
    Finds where this file should actually be written, returning
    (path, already_present).

    Walks the numeric-suffix chain (name.jpg -> name_1.jpg -> name_2.jpg ...)
    until it finds a free name. If `expected_sha1` is given and one of the
    OCCUPIED candidates already holds exactly that content, that file IS this
    photo — already delivered by an earlier run — and it is returned with
    already_present=True so the caller can skip rewriting it.

    That content check is what makes re-runs idempotent. Without it an
    Index -> Copy -> Index -> Copy cycle multiplies identical files: the
    re-index resets the row to Pending, the destination name is already taken
    by the copy the previous cycle delivered, so the next copy writes
    IMG_0001_1.jpg beside it, then IMG_0001_2.jpg, and so on every cycle.

    Suffixes are always built from the ORIGINAL stem, so a collision yields
    IMG_0001_3.jpg rather than a name that grows a segment each time
    (IMG_0001_1_2_3.jpg).
    """
    candidate = target_path
    counter = 1
    while candidate.exists():
        if expected_sha1 and _sha1_of(candidate) == expected_sha1:
            return candidate, True
        candidate = target_path.parent / f"{target_path.stem}_{counter}{target_path.suffix}"
        counter += 1
    return candidate, False


def _sha1_of(path: Path) -> Optional[str]:
    """SHA-1 of an existing file, or None if it can't be read. Never raises."""
    try:
        return fileinfo.compute_sha1(str(path))
    except Exception:
        return None


def _rejects_path_for(dest_root: Path, library_path) -> Path:
    """A library file's place in Rejects: the same folders under rejects/ (engine-spec 9.9)."""
    return ns_db.rejects_root(dest_root) / Path(library_path).relative_to(ns_db.library_root(dest_root))


def _library_path_for(dest_root: Path, rejects_path) -> Path:
    """Where a file in Rejects sat in the library, by the same mirroring."""
    return ns_db.library_root(dest_root) / Path(rejects_path).relative_to(ns_db.rejects_root(dest_root))


def find_delivered_copy(destination: str, recorded_sha1: Optional[str]) -> Optional[Path]:
    """The file at `destination`, or at one of its numbered variants, that holds exactly
    `recorded_sha1`, or None. Read-only: it hashes occupied candidates and changes nothing."""
    if not recorded_sha1:
        return None
    path, present = resolve_destination(Path(destination), recorded_sha1)
    return path if present else None


def find_content_on_destination(conn, sha1: Optional[str]) -> Optional[Path]:
    """A destination file, recorded by any delivered row, that holds exactly `sha1` now.

    For a duplicate, which is never written to the destination itself: its content is
    there if the row that stands for it was delivered. Every recorded copy is hashed live
    and the first match wins; a recorded path that no longer matches is not evidence.
    """
    if not sha1:
        return None
    for (dest,) in conn.execute(
            f"SELECT DISTINCT dest_path FROM photos WHERE sha1_hash = ? AND dest_path IS NOT NULL "
            f"AND status IN ({constants.sql_values(constants.ANCHOR_DELIVERED_STATUSES)})", (sha1,)).fetchall():
        if _sha1_of(Path(dest)) == sha1:
            return Path(dest)
    return None


def record_found_at_destination(conn, run_id: int, record_id: int, source: str, found: Path,
                                sha1: str):
    """Records a photo or duplicate whose source is gone and whose exact content is on
    the destination, as Found_At_Destination.

    This is the state a power cut leaves when a Move's catalog commits are lost and its
    file operations survive, but it is recorded as observed, not as an action: the engine
    cannot tell a lost Move from a source deleted by hand, and this run copied and deleted
    nothing. Evidence (source absent, destination match), the found file registered as an
    observed destination or linked if already recorded, the source identity marked missing
    rather than removed, the settled operation and the new status commit together.
    """
    note = (f"The source is gone and its exact content is on the destination at {found}. "
            f"Recorded as found there; nothing was copied or deleted.")
    with ns_db.transaction(conn):
        operation_id = ns_db.begin_operation(
            conn, run_id=run_id, photo_id=record_id, source_path=source,
            dest_path=str(found), kind="found_at_destination", expected={"sha1_hash": sha1})
        ns_db.record_evidence(conn, operation_id=operation_id, location_role="source",
                              observed_path=source, observation_kind="stat", result="absent")
        ns_db.record_evidence(conn, operation_id=operation_id, location_role="destination",
                              observed_path=str(found), observation_kind="sha1", result="match",
                              details={"sha1_hash": sha1})
        ns_db.record_delivery(conn, operation_id=operation_id, photo_id=record_id,
                              run_id=run_id, destination=str(found), source_removed=False,
                              created=False, sha1_hash=sha1)
        conn.execute("UPDATE file_states SET presence_state = 'missing', revision = revision + 1 "
                     "WHERE file_id = (SELECT file_id FROM photo_files WHERE photo_id = ?)",
                     (record_id,))
        ns_db.settle_operation(conn, operation_id, status=PhotoStatus.FOUND_AT_DESTINATION,
                               step="found_at_destination", outcome="recorded", error_message=note)
        conn.execute("UPDATE photos SET status = ?, dest_path = ? WHERE id = ?",
                     (PhotoStatus.FOUND_AT_DESTINATION, str(found), record_id))
    runtime.logger.info(f"Source gone, exact content on the destination: recorded as found at {found}")


def _is_under(path: str, root: Path) -> bool:
    """Literal, case-sensitive containment — the same rule _path_prefix_clause applies in SQL."""
    root_str = str(root)
    return path == root_str or path.startswith(root_str + "/")


def _display_path(path: str, root: Path) -> str:
    """A source path as shown in per-file log lines: relative to the run's --source root."""
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return Path(path).name


def _destination_for(dest_root: Path, source_path: str, metadata_json: Optional[str],
                     fallback: str) -> str:
    """
    The file's projected destination under THIS run's --dest, computed now.

    The catalog's dest_path was computed against whatever --dest was current
    when the file was last read, and the unchanged-file skip means that can be
    long ago — so trusting it would copy into the OLD destination after
    checking free space on the new one. The date that picks the folder is
    stored separately, so recomputing costs nothing. The stored path remains
    the fallback for a row with no recorded date, and is therefore the one
    case where the result may NOT lie under the current --dest; anything
    walking up from it has to allow for that (see _mkdir_durable).
    """
    try:
        metadata = json.loads(metadata_json or "{}")
        taken = datetime.fromisoformat(metadata.get("date_taken"))
    except (TypeError, ValueError, AttributeError):
        return fallback

    # Undated photos never enter the date tree — see UNDATED_FOLDER. This must
    # stay in step with the projection the scan writes, or the catalog names a
    # folder the file never occupies and the staging screen, which projects
    # from the catalog, shows the wrong destination for every undated photo.
    library = ns_db.library_root(dest_root)
    if metadata.get("date_source") == constants.DATE_SOURCE_MTIME:
        return str(library / constants.UNDATED_FOLDER / taken.strftime("%Y") / Path(source_path).name)

    return str(library / taken.strftime("%Y") / taken.strftime("%m") / taken.strftime("%d")
               / Path(source_path).name)
