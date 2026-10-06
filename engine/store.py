"""The catalog connection, run records, the operations log and the result writer."""

import contextlib
import json
import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional, List, Tuple

from engine.ns_db import PhotoStatus, OPERATION_SKIPPED
from engine import constants, ns_db, runtime


# --- SQLite Connection Helper ---
def get_db_connection(db_path: str, synchronous: str = "NORMAL") -> sqlite3.Connection:
    """
    Creates a connection with WAL mode, an extended busy timeout for concurrent
    safety, and the caller's synchronous level — NORMAL unless asked otherwise.

    synchronous=NORMAL (rather than SQLite's default FULL) stops the engine
    fsyncing on every single commit, which measured ~4.4x faster on its own.
    The safety tradeoff is specifically bounded: under WAL, NORMAL still
    survives *process* death — SIGKILL, an OOM-kill, `docker stop` timing out
    — because committed data is already in the OS page cache and is replayed
    from the WAL on the next open. Only a kernel panic or power loss can lose
    recently committed transactions, and process death is by far the likelier
    failure here.

    That bound covers the CATALOG only; it does nothing for the photo files,
    which is why the file protocol carries its own ordering. A source is
    deleted only after its verified copy, the copy's directory entry, and
    every directory entry from --dest down to it have been fsynced (see
    _remove_verified_source and _mkdir_durable). With those in place, a power
    loss can leave a stale row, or a photo present at both ends — recoverable
    by re-indexing — but not a deleted original without a copy on storage
    that honours fsync.

    **_run_move_or_copy asks for FULL, and is the only caller that does.** That
    loop commits status=Processing with dest_path before unlinking a source,
    and reconciliation finds interrupted work by that marker alone; losing it
    to a power cut leaves a delivered photo recorded Failed, which a probe
    reproduced. FULL measured 1.42x on that path — not the ~4.4x above, which
    is the scan path batching a hundred rows per commit and writing no markers.
    The scan path therefore keeps NORMAL and only the move loop pays.

    The level is whitelisted rather than interpolated blindly: a PRAGMA value
    cannot be bound as a parameter, so it is checked instead.
    """
    return ns_db.connect(db_path, synchronous=synchronous)


# --- Database Schema Initialization ---
def init_database(db_path: str):
    """Explicitly initialize the engine-owned schema; never migrate old evidence."""
    ns_db.initialize(db_path)


def start_run(
    db_path: str, mode: str, source_path: str, dest_path: str,
    file_ids: Optional[List[int]], source_subdir: Optional[str] = None,
    *, defaults=None, overrides=None, request_id=None, submitted=None, strict_selection=False
) -> Tuple[int, bool]:
    """
    Inserts the `runs` row for this invocation and returns (run_id, created).
    `file_ids` and `source_subdir` are mutually exclusive targeting
    mechanisms (enforced at the CLI level) — at most one is ever set.
    Persisted as a self-describing JSON object so the audit trail can tell
    which targeting mechanism (if any) scoped the run; a selection's photo ids
    go to run_selections with the run, its targeting their count and checksum.

    With a `request_id` already bound to identical input, no row is inserted:
    created is False and run_id is the run that request produced. The same ID
    with different input raises ns_db.RequestConflict.
    """
    if file_ids:
        targeting_filter = None          # ns_db.create_run records the selection itself
    elif source_subdir:
        targeting_filter = json.dumps({"source_subdir": source_subdir})
    else:
        targeting_filter = None
    with contextlib.closing(get_db_connection(db_path, synchronous="FULL")) as conn:
        return ns_db.create_run(
            conn, mode=mode, source=source_path, destination=dest_path,
            targeting=json.loads(targeting_filter) if targeting_filter else None,
            defaults=defaults, overrides=overrides,
            request_id=request_id, submitted=submitted,
            selection=file_ids or None, strict_selection=strict_selection,
        )


def finish_run(db_path: str, run_id: int, status: str):
    """Finalizes the `runs` row — called on normal completion, cancellation, or failure.

    At synchronous=FULL, which makes this commit fsync the WAL. That is one fsync
    of the whole file, so it also makes durable every earlier NORMAL commit in it:
    the scan path's batched results and audit rows. A settled run's history is
    therefore durable for one history-settle fsync (a dirty count-cache rebuild
    has its own preceding commit), where FULL on the scan
    path itself would cost the ~4.4x it was measured at.
    """
    conn = get_db_connection(db_path, synchronous="FULL")
    try:
        from engine import ns_similarity_cache
        ns_similarity_cache.refresh(conn, cancelled=runtime.cancel_requested.is_set)
    except Exception as exc:
        runtime.logger.warning(f"Similarity count cache not refreshed; queries will use current catalog data: {exc}")
    if not ns_db.transition_run(conn, run_id, status):
        # Only another run's reconciliation settles a run, and it cannot while
        # this process holds the lock — so this is a defect, not a race.
        raise RuntimeError(f"run #{run_id} could not move to {status}: it had already settled")
    conn.commit()
    conn.close()


def log_operation(conn: sqlite3.Connection, run_id: int, photo_id: Optional[int], source_path: str,
                   dest_path: Optional[str], status: str, error_message: Optional[str] = None,
                   has_name_collision: bool = False, commit: bool = True, delivery=None,
                   operation_id: Optional[int] = None, step: str = "transfer"):
    """
    Appends one row to the operations audit log. Never overwrites — every call
    is new history.

    The row also records the photo's content hash, read from its catalog row
    in the same statement so no caller has to supply it. photo_id is valid
    only inside one catalog; the hash names the same content in any catalog,
    so a photo's history can be matched up again after a rebuild. A file that
    could not be read has no hash and records NULL.

    commit=False leaves the row in the caller's open transaction, for the scan
    phase where many rows are committed together. The Move/Copy loop always
    uses the default: there, each audit row must be durable alongside the file
    operation it describes.

    That last sentence is enforced rather than merely intended: the Move/Copy
    loop opens its connection at synchronous=FULL (see get_db_connection), so
    committing here fsyncs. On the scan path, which stays at NORMAL, a power
    cut can still lose recently batched rows — they describe reading rather
    than deleting, and a re-Index reproduces them.
    """
    if operation_id is None:
        cur = conn.execute(
            """INSERT INTO operations
               (run_id, photo_id, original_filename, source_path, dest_path, status, error_message,
                has_name_collision, timestamp, sha1_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                       (SELECT NULLIF(sha1_hash, '') FROM photos WHERE id = ?))""",
            (
                run_id, photo_id, Path(source_path).name if source_path else None, source_path, dest_path,
                status, error_message, 1 if has_name_collision else 0, ns_db.utc_now(),
                photo_id
            )
        )
        record = cur.lastrowid
        ns_db.link_operation(conn, record, photo_id)
    else:
        # Settling intent recorded BEFORE the mutation: update that row rather
        # than inserting a second one, and close it with a terminal event. An
        # operation carrying intent and no terminal event is what recovery
        # recognises as interrupted, so this is what stops a completed transfer
        # from looking interrupted on the next run.
        record = operation_id
        conn.execute(
            """UPDATE operations SET status = ?, error_message = ?, dest_path = ?,
                   has_name_collision = ?, timestamp = ?,
                   sha1_hash = (SELECT NULLIF(sha1_hash, '') FROM photos WHERE id = ?)
                 WHERE id = ?""",
            (status, error_message, dest_path, 1 if has_name_collision else 0,
             ns_db.utc_now(), photo_id, record))
        ns_db.record_event(conn, operation_id=record, step=step,
                           outcome="completed" if delivery is not None else "failed",
                           detail={"status": status})
    if delivery is not None:
        ns_db.record_delivery(conn, operation_id=record, photo_id=photo_id,
                              run_id=run_id, destination=dest_path, **delivery)
    if status == OPERATION_SKIPPED and dest_path:
        # A relationship to the recorded retained file is not a fresh verification.
        conn.execute("INSERT OR IGNORE INTO operation_files SELECT ?,file_id,'retained_copy' FROM file_states WHERE current_path=? AND location_role='destination' AND presence_state='present'",
                     (record,dest_path))
    if commit:
        conn.commit()


def drain_result_queue(db_thread: threading.Thread):
    """
    Waits for the writer to consume every queued result — but never forever.

    Queue.join() blocks until task_done() has been called for each item, which
    can only happen while the writer is alive. If it has died the queue can
    never drain and join() hangs until something external kills the process:
    no error, no log line, just a run that never ends.

    Checking liveness between bounded waits turns that into an immediate,
    named failure.
    """
    while True:
        with runtime.result_queue.all_tasks_done:
            if runtime.result_queue.unfinished_tasks == 0:
                return
            runtime.result_queue.all_tasks_done.wait(timeout=1.0)
            if runtime.result_queue.unfinished_tasks == 0:
                return
        if not db_thread.is_alive():
            raise RuntimeError(
                f"Database writer thread died with {runtime.result_queue.unfinished_tasks} result(s) "
                f"still queued — aborting instead of waiting forever. Check the log above for "
                f"the error that killed it."
            )


def put_result(result, db_thread: threading.Thread):
    """
    Hands a result to the writer. Same reasoning as drain_result_queue: the
    queue is bounded (DB_QUEUE_SIZE), so a dead writer makes put() block
    forever once it fills. Fails loudly instead.
    """
    while True:
        try:
            runtime.result_queue.put(result, timeout=1.0)
            return
        except queue.Full:
            if not db_thread.is_alive():
                raise RuntimeError(
                    "Database writer thread died and the result queue is full — aborting. "
                    "Check the log above for the error that killed it."
                )


# --- Database Consumer (Thread) ---
# Scan results the writer could not persist, as (path, reason). Filled by
# db_writer_worker and read by main() once the writer has been joined: a run
# whose catalog writes failed must neither report success nor go on to move
# or copy files against a catalog that does not reflect what was scanned.
writer_failures: List[tuple] = []


def db_writer_worker(db_path: str):
    """
    The Consumer: only this thread touches SQLite during scanning.

    Commits are batched (DB_COMMIT_BATCH_SIZE rows, or DB_COMMIT_INTERVAL_SECONDS
    elapsed, whichever comes first) rather than one per file. This is safe here
    in a way it would NOT be in the Move/Copy loop, because indexing only READS
    the filesystem — it writes hashes, metadata and a projected destination, and
    mutates nothing on disk. A kill mid-batch loses the uncommitted tail of scan
    RESULTS, so those files are simply not catalogued yet and the next Index
    re-reads them. There is no filesystem state for the database to disagree
    with, so the two cannot drift out of sync; the only cost is recomputation.

    Batching does not weaken duplicate detection either: the per-file lookup
    below runs on this same connection, which sees its own uncommitted rows, so
    a duplicate pair landing inside one batch is still detected.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    writer_failures.clear()
    runtime.logger.info("Database worker thread started.")

    pending_writes = 0
    last_flush = time.monotonic()
    date_sources = {constants.DATE_SOURCE_EXIF: 0, constants.DATE_SOURCE_MTIME: 0}
    status_counts = {}
    phash_failures = 0
    thumbnails_written = 0
    thumbnail_failures = 0

    def flush():
        """
        Commits the pending batch. NEVER raises: this is called from the
        queue-timeout and sentinel paths, which sit outside the per-row
        try/except, so an exception here would kill the writer thread — and a
        dead writer means task_done() is never called again, so the main
        thread blocks on the queue forever with nothing logged. That exact
        failure mode is why the per-row body is wrapped (see below), and why
        neither of these call sites may raise either.
        """
        nonlocal pending_writes, last_flush
        try:
            if pending_writes:
                # The drawer's snapshot rides in the same commit as the rows it
                # counts, so it never shows more than the catalog holds.
                runtime.run_progress.write(conn)
                conn.commit()
                pending_writes = 0
        except Exception as e:
            # The whole batch is lost, not just unacknowledged: roll it back so
            # the connection is usable again, and record the loss so main()
            # fails the run instead of reporting a catalog it does not have.
            with contextlib.suppress(Exception):
                conn.rollback()
            writer_failures.append((f"(batch of {pending_writes} row(s))", f"commit failed: {e}"))
            runtime.logger.error(f"DB writer failed to commit a batch of {pending_writes} row(s): {e}")
            pending_writes = 0
        last_flush = time.monotonic()

    while True:
        try:
            # The timeout is what lets a partial batch reach disk while the
            # scan is producing slowly (large RAWs). Blocking forever on get()
            # would hold finished rows in an open transaction indefinitely,
            # and the web UI polls this database for live progress.
            result = runtime.result_queue.get(timeout=constants.DB_COMMIT_INTERVAL_SECONDS)
        except queue.Empty:
            flush()
            continue

        if result is None:
            flush()
            runtime.result_queue.task_done()
            break

        # The whole body is guarded: main()'s result_queue.join() waits for
        # task_done() on every item, so an exception escaping this loop would
        # hang the run with no error surfaced. A bad row is rolled back and
        # counted in writer_failures instead.
        try:
            # Each scan result is one unit: its catalog row and its audit entry
            # are written together or not at all. The savepoint nests inside
            # the batch transaction, so a failure undoes only this file's
            # partial writes and the rest of the batch still commits. BEGIN is
            # explicit because releasing an OUTERMOST savepoint would commit.
            if not conn.in_transaction:
                conn.execute("BEGIN")
            conn.execute("SAVEPOINT scan_row")

            # The row this file updates: the one at its path among files still in the
            # source. A row whose source a Move consumed stays with the photo it
            # delivered; a file later found at that path is a new arrival with a row of
            # its own (idx_photos_live_source), compared below against that delivered
            # content like any other file, so it becomes its duplicate (engine-spec 6.5).
            live = cursor.execute(
                "SELECT id, status FROM photos WHERE source_path = ? AND (status IS NULL OR status NOT IN "
                f"({constants.sql_values(constants.SOURCE_CONSUMED_STATUSES)}))", (result.file_path,)).fetchone()
            live_id, prior_status = live if live else (None, None)

            # Exclude the file's own row (by id: a consumed row at the same path is a
            # different, delivered photo and counts) and rows that are themselves
            # Duplicate/Removed_Duplicate. Without the status exclusion, re-scanning a
            # duplicate pair would cascade: each file would find the other's persisted
            # Duplicate status and count it as the original, leaving both Duplicate with
            # no anchor, so the photo could never be moved or cleaned up.
            # normalize_duplicate_groups() re-derives the final classification after the scan.
            cursor.execute(
                "SELECT id FROM photos WHERE sha1_hash = ? AND id != ? "
                f"AND status NOT IN ({constants.sql_values((PhotoStatus.DUPLICATE, PhotoStatus.REMOVED_DUPLICATE))})",
                (result.sha1_hash, live_id if live_id is not None else -1)
            )
            existing = cursor.fetchone()

            status = result.status
            if existing and status != PhotoStatus.FAILED:
                status = PhotoStatus.DUPLICATE

            values = (result.dest_path, result.sha1_hash, result.phash, result.collision_group,
                      1 if result.is_master else 0, status, json.dumps(result.metadata),
                      1 if result.has_name_collision else 0, result.file_size, result.file_mtime)
            if live_id is not None:
                # Re-scanning a file already catalogued refreshes its row in place.
                cursor.execute(
                    "UPDATE photos SET dest_path = ?, sha1_hash = ?, phash = ?, collision_group = ?, "
                    "is_master = ?, status = ?, metadata_json = ?, has_name_collision = ?, file_size = ?, "
                    "file_mtime = ? WHERE id = ?", values + (live_id,))
                photo_id = live_id
            else:
                cursor.execute(
                    "INSERT INTO photos (source_path, dest_path, sha1_hash, phash, collision_group, is_master, "
                    "status, metadata_json, has_name_collision, file_size, file_mtime) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (result.file_path,) + values)
                photo_id = cursor.lastrowid

            file_id = ns_db.record_source_observation(
                conn, photo_id=photo_id, run_id=result.run_id,
                source_path=result.file_path, sha1_hash=result.sha1_hash,
                file_size=result.file_size, file_mtime=result.file_mtime,
                birthtime=result.birthtime, metadata=result.metadata,
                error=result.error_message, prior_status=prior_status,
                observed_at=result.observed_at,
            )

            # Content identity, which thumbnails and similarity both key on so
            # that byte-identical copies share one row. Written here rather than
            # in the worker because only this thread touches SQLite during a
            # scan, and it joins this file's savepoint so identity and thumbnail
            # state land with the catalog row or not at all.
            if result.sha1_hash:
                decoded = result.phash not in ("", "error", "not_supported", None)
                content_id = ns_db.content_for_digest(
                    conn, digest=result.sha1_hash,
                    phash=result.phash if decoded else None,
                    phash_state="ok" if decoded else (result.phash or "error"),
                    width=result.thumbnail.width if result.thumbnail else None,
                    height=result.thumbnail.height if result.thumbnail else None,
                )
                if result.thumbnail is not None:
                    ns_db.record_thumbnail(
                        conn, content_id=content_id, size=constants.THUMBNAIL_SIZE,
                        availability=result.thumbnail.availability,
                        cache_filename=result.thumbnail.cache_filename,
                        bytes_on_disk=result.thumbnail.bytes,
                        attempted_file_id=file_id, observed_path=result.file_path,
                        failure_category=result.thumbnail.failure_category,
                        failure_detail=result.thumbnail.failure_detail,
                    )
                    if result.thumbnail.availability == "failed":
                        thumbnail_failures += 1
                    elif not result.thumbnail.reused:
                        thumbnails_written += 1
            log_operation(
                conn, result.run_id, photo_id, result.file_path, result.dest_path, status,
                result.error_message, result.has_name_collision, commit=False
            )
            conn.execute("RELEASE scan_row")

            # Counted only once the row is safely in the batch.
            source = result.metadata.get("date_source") if result.metadata else None
            if source in date_sources:
                date_sources[source] += 1
            status_counts[status] = status_counts.get(status, 0) + 1
            if result.phash in ("error", "not_supported"):
                phash_failures += 1
            runtime.run_progress.add("failed" if status == PhotoStatus.FAILED else
                             "duplicates" if status == PhotoStatus.DUPLICATE else "indexed")

            pending_writes += 1
            # A commit at least once a second while progress changes, rather than
            # every DB_COMMIT_INTERVAL_SECONDS: the drawer refreshes about once a
            # second, and a commit here does not fsync (synchronous=NORMAL).
            if pending_writes >= constants.DB_COMMIT_BATCH_SIZE or runtime.run_progress.due() or (
                time.monotonic() - last_flush >= constants.DB_COMMIT_INTERVAL_SECONDS
            ):
                flush()
        except Exception as e:
            # Undo this row's partial writes, keep the rest of the batch, and
            # remember the failure: main() fails the run and skips the
            # physical phase rather than acting on a catalog it could not
            # update. A status the CHECK constraints reject lands here too.
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK TO scan_row")
                conn.execute("RELEASE scan_row")
            writer_failures.append((result.file_path, f"{type(e).__name__}: {e}"))
            runtime.logger.error(f"DB writer failed to record {result.file_path}: {e}")
            runtime.run_progress.add("failed")
        finally:
            runtime.result_queue.task_done()

    try:
        flush()
    except Exception as e:
        runtime.logger.error(f"DB writer failed to flush its final batch: {e}")

    # Where each file's date came from, and therefore which files the
    # container's timezone actually affected. EXIF timestamps carry no zone and
    # are used as the camera wrote them; an mtime is interpreted in local time,
    # so a photo modified late in the evening can land in the next day's folder
    # under a different TZ. Surfacing the count makes that visible per run
    # instead of being something you discover in the organized tree later.
    # One line that answers "what actually happened?" without reading the whole
    # log. A bare file count makes a scan where hundreds of files failed look
    # identical to a clean one.
    total = sum(status_counts.values())
    if total:
        breakdown = ", ".join(f"{n:,} {st.lower()}" for st, n in sorted(status_counts.items()))
        runtime.logger.info(f"Index summary: {total:,} file(s) recorded — {breakdown}.")
        failed = status_counts.get(PhotoStatus.FAILED, 0)
        if failed:
            runtime.logger.warning(
                f"{failed:,} file(s) failed and were recorded with a reason — query them with: "
                f"SELECT source_path, error_message FROM operations "
                f"WHERE status = '{PhotoStatus.FAILED}' AND run_id = (SELECT MAX(id) FROM runs);"
            )
        if phash_failures:
            runtime.logger.warning(
                f"{phash_failures:,} file(s) produced no perceptual hash (undecodable or "
                f"unsupported format). They are indexed and will move/copy normally, but "
                f"cannot participate in similarity matching."
            )
        if thumbnails_written or thumbnail_failures:
            runtime.logger.info(f"Thumbnails: {thumbnails_written:,} generated, {thumbnail_failures:,} failed.")
            # Reported per size because the two are managed separately, and summed from
            # the recorded bytes rather than walked on disk (webui-spec.md 4.2.1).
            # Never allowed to cost the run: this is the last thing the writer does, so
            # an exception here would kill the thread after the work is already done.
            try:
                for size, photos, cached_bytes in ns_db.thumbnail_cache_totals(conn):
                    runtime.logger.info(
                        f"Thumbnail cache: {photos:,} photo(s) at {size}px, "
                        f"{cached_bytes / 1048576:.1f} MB."
                    )
            except Exception as e:
                runtime.logger.debug(f"Could not summarize the thumbnail cache: {e}")
        if thumbnail_failures:
            runtime.logger.warning(
                f"{thumbnail_failures:,} file(s) produced no thumbnail. They are indexed and "
                f"will move/copy normally; the gallery shows a placeholder with the recorded "
                f"reason. A thumbnail is disposable cache and never fails an Index."
            )

    from_exif = date_sources[constants.DATE_SOURCE_EXIF]
    from_mtime = date_sources[constants.DATE_SOURCE_MTIME]
    if from_exif or from_mtime:
        runtime.logger.info(f"Date sources: {from_exif} from EXIF, {from_mtime} from file modification time.")
    if from_mtime:
        runtime.logger.warning(
            f"{from_mtime} file(s) had no usable EXIF date, so their date folder was chosen from "
            f"the file's modification time. The files themselves are not changed. Those times "
            f"are interpreted in this container's timezone (logged above) — pass -e TZ=<zone> "
            f"if the folders look a day off."
        )
    conn.close()
    runtime.logger.info("Database worker thread shut down cleanly.")
