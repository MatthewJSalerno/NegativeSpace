"""Index: discovering source files, reading them in worker processes, noticing what vanished."""

import os
from pathlib import Path
from typing import Optional, Callable, List

from engine.ns_db import PhotoStatus, SUPPORTED_EXTENSIONS
from engine import constants, destinations, fileinfo, ns_db, runtime, store, targeting, thumbnails


def _failed_result(file_path_str: str, run_id: int, error_message: str) -> runtime.ProcessingResult:
    """Builds the Failed result for a file that could not be scanned at all."""
    return runtime.ProcessingResult(
        file_path=file_path_str, sha1_hash="", phash="", metadata={}, status=PhotoStatus.FAILED,
        dest_path="", run_id=run_id, error_message=error_message
    )


def not_an_image(file_path: Path, file_size: Optional[int], metadata: dict) -> Optional[str]:
    """Why a file with a photo's extension is not a photo, or None. Judged by content,
    as ExifTool identified it, never by the name: a PNG named .jpg is still an image.
    Such a file is recorded Failed with this reason, so it appears in the log and is
    never copied, moved or filed (maintainer's rule, engine-spec 4.1). Without
    ExifTool's answer (its PIL fallback), nothing is concluded: a photo is never
    refused on a guess. An extension the user selected that is not a photo format
    (.mov) is outside this rule: it is catalogued and carried, with its own warning
    (webui-spec 3.2)."""
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None
    if file_size == 0:
        return "Not an image: the file is empty"
    if metadata.get("Error"):
        return f"Not an image: {metadata['Error']}"
    mime = metadata.get("MIMEType")
    if mime and not str(mime).startswith("image/"):
        return f"Not an image: its content is {metadata.get('FileType') or mime}, not a photo"
    return None


def process_file_task(file_path_str: str, dest_base_path: str, run_id: int,
                      cache_root: Optional[str] = None,
                      original_mtime: Optional[float] = None) -> runtime.ProcessingResult:
    """
    Scans one file: SHA-1, pHash, metadata/date, and its projected destination.

    NEVER raises. Any per-file failure comes back as a Failed result carrying
    a human-readable reason, because an exception escaping here propagates
    through future.result() in main() and aborts the ENTIRE run — discarding
    every other file's completed work and leaving no record of which file was
    responsible.
    """
    file_path = Path(file_path_str)

    # Checked explicitly, before any attempt to open the file, so a stale
    # selection surfaces as a specific reason in the Error Center rather than
    # a raw FileNotFoundError traceback (docs/engine-spec.md 4.2).
    if not file_path.exists():
        return _failed_result(
            file_path_str, run_id,
            f"Source file changed: no longer found at {file_path}. It may have been moved, "
            f"renamed, or deleted outside NegativeSpace since the last Index."
        )

    file_size = file_mtime = birthtime = None
    observed_at = ns_db.utc_now()
    try:
        # Cheap next to reading the whole file, and it is what lets progress
        # report THROUGHPUT rather than only a file count — see
        # log_scan_progress for why that distinction matters.
        try:
            _st = file_path.stat()
            file_size, file_mtime = _st.st_size, _st.st_mtime
            birthtime = getattr(_st, "st_birthtime", None)
        except OSError:
            pass

        sha1 = fileinfo.compute_sha1(str(file_path))
        phash = fileinfo.compute_phash(str(file_path))

        dt, metadata = fileinfo.get_metadata_and_date(file_path, original_mtime)
        refusal = not_an_image(file_path, file_size, metadata)
        if not refusal and file_path.suffix.lower() in SUPPORTED_EXTENSIONS and phash in ("", "error", "not_supported"):
            decode_error = fileinfo.image_decode_error(str(file_path))
            if decode_error:
                refusal = (f"Cannot decode image: {decode_error}. Left in the source; "
                           "repair or replace the file, or check decoder support, then run Index again.")
        if refusal:
            result = _failed_result(file_path_str, run_id, refusal)
            result.file_size, result.file_mtime = file_size, file_mtime
            result.birthtime, result.observed_at = birthtime, observed_at
            return result
        # Keep an explicit, guaranteed-present date_taken key regardless of which
        # capture path produced `metadata`, since downstream consumers (path
        # computation here, and the inspector UI later) shouldn't need to know
        # ExifTool's exact tag-naming conventions just to find "the date."
        metadata["date_taken"] = dt.isoformat()

        # Pixel validation is separate from disposable cache output. A cache write
        # failure must not prevent a readable image from being organized.
        thumbnail = thumbnails.generate_thumbnail(file_path, sha1, cache_root) if cache_root and sha1 else None

        # A photo the engine could not date does not enter the date tree: its
        # only date is the file's mtime, which for an export is the download
        # time. Filing it beside photos whose dates came from a camera makes a
        # guess indistinguishable from a fact. See UNDATED_FOLDER.
        #
        # This is a PROJECTION and is recomputed before the write, so both this
        # and _destination_for() must agree about Undated/ — otherwise the
        # catalog advertises a folder the file never occupies.
        if metadata.get("date_source") == constants.DATE_SOURCE_MTIME:
            target_folder = ns_db.library_root(dest_base_path) / constants.UNDATED_FOLDER / dt.strftime("%Y")
        else:
            year_dir = dt.strftime("%Y")
            month_dir = dt.strftime("%m")
            day_dir = dt.strftime("%d")
            target_folder = ns_db.library_root(dest_base_path) / year_dir / month_dir / day_dir

        # This destination is a PROJECTION, not a reservation, and
        # has_name_collision stays False here by design. The authoritative
        # unique-name resolution happens immediately before the file is
        # actually written (see _run_move_or_copy). Resolving it here would be
        # silent data loss: at Index time the destination tree is normally
        # still empty, so two different photos sharing a filename would both
        # be told the name was free, and whichever got written second would
        # overwrite the first — with both runs reporting success.
        return runtime.ProcessingResult(
            file_path=str(file_path),
            sha1_hash=sha1,
            phash=phash,
            metadata=metadata,
            status=PhotoStatus.PENDING,
            dest_path=str(target_folder / file_path.name),
            run_id=run_id,
            has_name_collision=False,
            file_size=file_size,
            file_mtime=file_mtime, birthtime=birthtime, observed_at=observed_at,
            thumbnail=thumbnail
        )
    except Exception as e:
        result = _failed_result(file_path_str, run_id, f"{type(e).__name__}: {e}")
        result.file_size, result.file_mtime = file_size, file_mtime
        result.birthtime, result.observed_at = birthtime, observed_at
        return result


# --- Discovering source files ---
def describe_root_overlap(source: Path, dest: Path) -> Optional[str]:
    """
    Explains how two RESOLVED roots overlap, or returns None if they do not.

    Detects what the paths and the kernel can show: one path, one nested in
    the other (symlinks are already resolved by the caller), and one directory
    reachable at two paths, such as a bind mount, via samefile(). Two separate
    network mounts of one export appear as different devices and are NOT
    detected — which is why _remove_verified_source() also refuses per file,
    and why overlapping storage stays documented as unsupported.
    """
    if source == dest:
        return f"both are {source}"
    if dest.is_relative_to(source):
        return f"the destination {dest} is inside the source {source}"
    if source.is_relative_to(dest):
        return f"the source {source} is inside the destination {dest}"
    try:
        if dest.exists() and os.path.samefile(source, dest):
            return f"{source} and {dest} are the same directory reached by two paths"
    except OSError:
        pass
    return None


def discover_source_files(root: Path, extensions: set, errors: Optional[list] = None,
                          excluded: Optional[dict] = None,
                          on_directory: Optional[Callable[[int, int], None]] = None) -> List[str]:
    """
    Walks `root` and returns the files worth scanning.

    Uses os.scandir rather than Path.rglob because of what each costs on a
    NETWORK share. rglob yields bare paths, so the caller must then ask
    p.is_file() and p.is_symlink() — two stat() calls per entry, and over NFS a
    stat() is a round trip rather than a page-cache hit. Measured: 28-40
    seconds merely to enumerate 29,047 files, which is almost exactly
    29,047 x 2 x ~0.5ms of round trips. os.scandir's DirEntry carries the type
    from readdir(), so the same walk usually needs no extra syscall at all;
    measured 8x faster even on a local filesystem, where there is no network
    latency to hide.

    The extension test is also checked BEFORE the filesystem questions, so a
    directory full of video or sidecar files costs string comparisons instead
    of syscalls.

    `excluded`, when given, counts regular files left out by extension, keyed by
    lower-case extension ("" for none), for the discovery summary (webui-spec
    5.1). Hidden entries are skipped before any counting, as they always were.
    DirEntry.is_file reads the type readdir already returned, so counting them
    adds no round trip on a network share.

    `on_directory(eligible, excluded)`, when given, is called after each folder with
    the running totals, for live progress while the total is still unknown.
    """
    found: List[str] = []
    stack = [str(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    # A leading dot at any level: skip the whole subtree. This
                    # covers .Trashes/, .Spotlight-V100/ and macOS AppleDouble
                    # sidecars ("._IMG_0001.jpg") that carry real photo
                    # extensions and would otherwise index as photographs.
                    if entry.name.startswith('.'):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext not in extensions:
                            if excluded is not None and entry.is_file(follow_symlinks=False):
                                excluded[ext] = excluded.get(ext, 0) + 1
                            continue
                        if entry.is_file(follow_symlinks=False):
                            found.append(entry.path)
                    except OSError as e:
                        runtime.logger.warning(f"Could not inspect {entry.path}: {e}")
                        if errors is not None:
                            errors.append((entry.path, f"Could not inspect during the scan: "
                                                       f"{type(e).__name__}: {e}"))
        except OSError as e:
            # An unreadable directory must not abort the whole scan, for the
            # same reason an unreadable file does not — but it must not vanish
            # into the log either. `errors` lets the caller record it.
            runtime.logger.warning(f"Could not read directory {current}: {e}")
            if errors is not None:
                errors.append((current, f"Could not read this folder during the scan, so photos "
                                        f"inside it were not examined: {type(e).__name__}: {e}"))
        if on_directory is not None:
            on_directory(len(found), sum(excluded.values()) if excluded is not None else 0)
    return found


def original_source_mtimes(db_path: str, candidates: List[str]) -> dict:
    """source_path -> the modification time recorded at that file's FIRST Index.

    Read here, in the main thread, because the scan workers are separate
    processes with no database handle — and the date has to be decided in the
    worker, alongside the destination projection it feeds, or the catalog ends
    up advertising a folder the file never occupies.

    Rows whose status is SOURCE_CONSUMED_STATUSES are excluded, and that
    exclusion is load-bearing rather than tidiness: a file put back at a path a
    Move consumed is a NEW photo row with a fresh identity and snapshot.
    Pinning it to the snapshot of the identity the Move consumed would date a
    new arrival by a file that is gone.
    """
    if not candidates:
        return {}
    conn = store.get_db_connection(db_path)
    try:
        return {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT p.source_path, ss.file_mtime FROM photos p "
                "JOIN photo_files pf ON pf.photo_id = p.id "
                "JOIN source_snapshots ss ON ss.file_id = pf.file_id "
                "WHERE ss.file_mtime IS NOT NULL "
                f"AND p.status NOT IN ({constants.sql_values(constants.SOURCE_CONSUMED_STATUSES)})"
            )
        }
    finally:
        conn.close()


def partition_unchanged(db_path: str, candidates: List[str], force: bool = False) -> tuple:
    """
    Splits discovered files into (to_scan, unchanged), returning paths whose
    size and mtime still match what the catalog recorded as `unchanged`.

    Without this check every Index reads EVERY file in full — SHA-1 over the
    whole file, a complete pixel decode for the perceptual hash, and an
    ExifTool pass — because SHA-1 cannot serve as the skip test: it is the
    RESULT of reading the file, not something knowable beforehand. Measured on
    one 29,047-file library, two consecutive indexes took 24m57s and 25m27s,
    the second gaining nothing from the first.

    Comparing size and mtime costs one stat per file instead of reading it —
    roughly 21 MB of network traffic replaced by a single metadata round trip
    for a RAW file. A library that has not changed re-indexes in seconds.

    Rows predating this check have NULL size/mtime, which reads as "unknown"
    and forces one full pass for those files; it is self-correcting after that.
    A file whose row is not in a settled state is always rescanned, so
    interrupted or failed work is never skipped on the strength of a stat.

    force=True bypasses the comparison entirely (--force-rehash), for when the
    concern is content changed without size or mtime moving — which editors do
    not do in practice, but verification should not require deleting the
    database.
    """
    if force or not candidates:
        return list(candidates), []

    conn = store.get_db_connection(db_path)
    try:
        known = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT source_path, file_size, file_mtime FROM photos "
                "WHERE file_size IS NOT NULL AND file_mtime IS NOT NULL "
                f"AND status IN ({constants.sql_values(tuple(v for v in constants.SETTLED_STATUSES if v not in constants.SOURCE_CONSUMED_STATUSES))})"
            )
        }
    finally:
        conn.close()

    if not known:
        return list(candidates), []

    to_scan, unchanged = [], []
    for path in candidates:
        recorded = known.get(path)
        if recorded is None:
            to_scan.append(path)
            continue
        try:
            st = os.stat(path)
        except OSError:
            # Cannot stat it, so cannot claim it is unchanged. Let the normal
            # pipeline record the real failure with its reason.
            to_scan.append(path)
            continue
        if recorded[0] == st.st_size and abs(recorded[1] - st.st_mtime) < 1e-6:
            unchanged.append(path)
        else:
            to_scan.append(path)
    return to_scan, unchanged


def normalize_extensions(raw: str) -> set:
    """
    Parses --exts into the form Path.suffix actually produces.

    Path.suffix ALWAYS includes the leading dot (".jpg") and the scan compares
    against it directly, so an unnormalised `--exts jpg,png` would match
    nothing and report "Discovered 0 files" with no hint why. Both spellings
    are accepted, along with surrounding whitespace and any casing:
        ".jpg, PNG , .HEIC"  ->  {".jpg", ".png", ".heic"}
    """
    extensions = set()
    for item in raw.split(','):
        item = item.strip().lower()
        if not item:
            continue
        extensions.add(item if item.startswith('.') else f".{item}")
    return extensions


SOURCE_EMPTY_ISSUE = "source_root_empty"


def open_source_empty_issue(conn, run_id: int, root: Path, rows: int):
    """Asks instead of guessing when the source root is empty but the catalog holds rows
    there: an unplugged share and a Move that took everything look the same. One open
    issue per root, but every refused run records its own failure so it cannot
    establish scan coverage. Scan and transfer may ask within the same run."""
    summary = (f"The source folder {root} is empty while the catalog holds {rows:,} photo(s) "
               f"from it. Is the drive unplugged or unmounted, or is the folder really empty? "
               f"If it is unplugged, reconnect it and run again. If it is really empty, run again "
               f"with --confirm-source-empty to record photos whose content is on the "
               f"destination as found there.")
    already = conn.execute("SELECT 1 FROM attention_issues WHERE category = ? AND resolved_at IS NULL "
                           "AND summary LIKE ?", (SOURCE_EMPTY_ISSUE, f"The source folder {root} is%")).fetchone()
    with ns_db.transaction(conn):
        recorded = conn.execute(
            "SELECT 1 FROM operations o JOIN operation_events e ON e.operation_id = o.id "
            "WHERE o.run_id = ? AND o.source_path = ? AND o.photo_id IS NULL "
            "AND e.step = 'intent' AND json_extract(e.detail_json, '$.kind') = ? LIMIT 1",
            (run_id, str(root), SOURCE_EMPTY_ISSUE)).fetchone()
        if recorded:
            return
        operation_id = ns_db.begin_operation(conn, run_id=run_id, photo_id=None, source_path=str(root),
                                             dest_path=None, kind="source_root_empty")
        ns_db.settle_operation(conn, operation_id, status=PhotoStatus.FAILED, step="scan",
                               outcome="needs_attention", error_message=summary)
        if not already:
            ns_db.open_attention_issue(conn, operation_id=operation_id, category=SOURCE_EMPTY_ISSUE,
                                       summary=summary)
    runtime.logger.warning(summary)


def resolve_source_empty_issues(conn, root: Path):
    """Closes the open empty-source question for `root` once it is answered: files are
    back, or the user confirmed the folder is really empty."""
    with ns_db.transaction(conn):
        conn.execute("UPDATE attention_issues SET resolved_at = ? WHERE category = ? AND "
                     "resolved_at IS NULL AND summary LIKE ?",
                     (ns_db.utc_now(), SOURCE_EMPTY_ISSUE, f"The source folder {root} is%"))


def _source_missing(path: str) -> bool:
    """True only when stat() says the file does not exist; unreadable is not absent."""
    try:
        os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return True
    except OSError:
        return False
    return False


def mark_vanished_sources(db_path: str, run_id: int, root: Path, discovered: List[str],
                          dest_root: Optional[Path] = None, confirm_empty: bool = False) -> int:
    """
    After a full walk of `root`, settles catalogued files that no longer exist.
    Returns how many were marked Failed.

    A full Index only updates the files it finds, so without this a photo
    deleted outside the engine would keep its row Pending indefinitely, and
    go on standing as the original of its duplicate group, so the duplicate
    would never be delivered. Failed rows take no part in duplicate grouping,
    which lets the reclassification that follows promote a surviving duplicate.

    Before anything is marked Failed, a row whose source is gone is checked
    against the destination: a Pending or Failed row at the place it was meant
    to go, a Duplicate at any delivered copy of its content. If the exact content
    is there it is recorded Found_At_Destination instead (see
    record_found_at_destination). That covers a Move whose catalog commits were
    lost, and a row an earlier targeted Index already marked Failed. Duplicates
    are settled after the rows they may depend on.

    A file counts as gone only when stat() says it does not exist. Anything
    else — a permission error, an I/O fault, an --exts filter that simply did
    not list it — leaves the row alone: unreadable is not absent.

    A walk that found NOTHING is not believed while the catalog still holds
    Pending or Duplicate rows here. An unmounted share leaves exactly that shape
    — a directory that exists and is empty — and every stat() beneath it then
    says "not found", so the sweep would condemn the entire catalogue under this
    root in one pass. Instead the user is asked: an attention issue says the
    folder is empty and how to answer (open_source_empty_issue), and nothing is
    changed. `confirm_empty` is that answer — the folder really is empty — and
    lets the sweep run. The check lives here rather than at the call site so no
    caller can skip it.
    """
    seen = set(discovered)
    clause, params = targeting._path_prefix_clause(root)
    conn = store.get_db_connection(db_path)
    try:
        rows = conn.execute(
            f"SELECT id, source_path, dest_path, status, sha1_hash, metadata_json FROM photos "
            f"WHERE status IN ({constants.sql_values((PhotoStatus.PENDING, PhotoStatus.DUPLICATE, PhotoStatus.FAILED))})"
            + clause,
            params
        ).fetchall()
        open_rows = sum(1 for r in rows if r[3] != PhotoStatus.FAILED)

        if not discovered and open_rows:
            if not confirm_empty:
                open_source_empty_issue(conn, run_id, root, open_rows)
                return 0
            runtime.logger.info(f"--confirm-source-empty: treating {root} as really empty.")
        if discovered or confirm_empty:
            resolve_source_empty_issues(conn, root)

        # Photos before duplicates: a duplicate's content may be found through a
        # row this same pass is about to record as found.
        rows.sort(key=lambda r: r[3] == PhotoStatus.DUPLICATE)
        gone = []
        for row_id, path, dest, status, sha1, metadata_json in rows:
            if path in seen or not _source_missing(path):
                continue
            found = None
            if dest_root is not None and status in (PhotoStatus.PENDING, PhotoStatus.FAILED):
                found = destinations.find_delivered_copy(destinations._destination_for(dest_root, path, metadata_json, dest), sha1)
            elif status == PhotoStatus.DUPLICATE:
                found = destinations.find_content_on_destination(conn, sha1)
            if found is not None:
                destinations.record_found_at_destination(conn, run_id, row_id, path, found, sha1)
                continue
            if status != PhotoStatus.FAILED:
                gone.append((row_id, path, dest))
        for row_id, path, dest in gone:
            conn.execute("UPDATE photos SET status = ? WHERE id = ?", (PhotoStatus.FAILED, row_id))
            store.log_operation(
                conn, run_id, row_id, path, dest, PhotoStatus.FAILED,
                f"Source file changed: no longer found at {path}. It may have been moved, renamed, "
                f"or deleted outside NegativeSpace since the last Index.",
                commit=False
            )
        conn.commit()
    finally:
        conn.close()
    return len(gone)
