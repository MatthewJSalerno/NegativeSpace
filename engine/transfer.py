"""Copy and Move: delivering photos, duplicates, and files found at the destination."""

import contextlib
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from engine.ns_db import (
    PhotoStatus, RunStatus, OPERATION_CANCELLED, OPERATION_SKIPPED, IN_REJECTS_STATUSES,
    REJECTED_STATUSES)
from engine import (
    constants, destinations, durable, fileinfo, ns_db, runtime, scan, store, targeting)


# --- Pre-Flight Space Validation ---
def _nearest_existing_dir(path: Path) -> Path:
    """
    Walks up until it finds a directory that actually exists. Used to ask the
    filesystem about free space on the volume a not-yet-created path will
    land on, without creating anything to find out.
    """
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return Path(path.anchor or '.')


def verify_sufficient_disk_space(dest_path: Path, required_bytes: int,
                                 safety_margin_mb: int = 500) -> tuple:
    """
    Checks whether the destination volume has room for `required_bytes`.

    Returns (ok, free_bytes, needed_bytes) rather than a bare bool, so a
    caller can record what was required against what was available — a
    shortfall is a run-level failure, and "not enough space" with no figures
    is not something a user can act on.

    Strictly read-only: asking whether there is room must not create anything,
    or a run that then aborts for insufficient space leaves directory trees
    behind. Free space is a property of the VOLUME, so querying the nearest
    existing ancestor answers the same question without writing. The real
    destination directories are created when a file is actually written
    (copy_verify_delete).
    """
    stat = shutil.disk_usage(_nearest_existing_dir(dest_path))
    buffer_bytes = safety_margin_mb * 1024 * 1024
    total_needed = required_bytes + buffer_bytes

    if stat.free < total_needed:
        required_gb = required_bytes / (1024 ** 3)
        free_gb = stat.free / (1024 ** 3)
        runtime.logger.error(
            f"Insufficient disk space on destination! "
            f"Required: {required_gb:.2f} GB (+{safety_margin_mb}MB safety buffer), "
            f"Available: {free_gb:.2f} GB."
        )
        return False, stat.free, total_needed
    return True, stat.free, total_needed


def _duplicate_skip_reason(cursor, sha1_hash: str, copying: bool) -> tuple:
    """
    (reason, pointer) for a duplicate this run deliberately leaves alone. The
    reason names the original that carries its content; the pointer is where
    that content already sits, when it has been delivered.

    The web UI groups Skipped outcomes by how these reasons begin
    (webui/catalog.py _SKIP_REASONS): keep the openings stable, or update the
    grouping with them.
    """
    cursor.execute(
        f"SELECT id, source_path, dest_path, status FROM photos WHERE sha1_hash = ? "
        f"AND status IN ({constants.sql_values(constants.ANCHOR_STATUSES + (PhotoStatus.FAILED,))}) "
        f"ORDER BY CASE WHEN status IN ({constants.sql_values(constants.ANCHOR_DELIVERED_STATUSES)}) THEN 0 ELSE 1 END, id "
        f"LIMIT 1",
        (sha1_hash,)
    )
    row = cursor.fetchone()
    if row is None:
        rejected = cursor.execute(
            f"SELECT id, source_path, dest_path, status FROM photos WHERE sha1_hash = ? "
            f"AND status IN ({constants.sql_values(REJECTED_STATUSES)}) ORDER BY id DESC LIMIT 1",
            (sha1_hash,)).fetchone()
        if rejected is not None:
            rejected_id, rejected_src, rejected_dest, rejected_status = rejected
            where = ("its copy is in Rejects" if rejected_status in IN_REJECTS_STATUSES
                     else "Rejects has since been emptied")
            if copying:
                return (f"Already rejected: identical to photo #{rejected_id} "
                        f"({Path(rejected_src).name}), which you rejected; {where}, so it is not "
                        f"copied into the library.",
                        rejected_dest if rejected_status in IN_REJECTS_STATUSES else None)
            then = ("once that photo's own source is moved" if rejected_status == PhotoStatus.REJECTED_COPIED
                    else "once its copy in Rejects is verified")
            return (f"Already rejected: identical to photo #{rejected_id} "
                    f"({Path(rejected_src).name}), which you rejected; {where}. This source is "
                    f"removed {then}.",
                    rejected_dest if rejected_status in IN_REJECTS_STATUSES else None)
        return ("Duplicate with no original left in the catalog; run an Index so it can be "
                "reclassified.", None)
    anchor_id, anchor_src, anchor_dest, anchor_status = row
    name = Path(anchor_src).name
    if anchor_status in constants.ANCHOR_DELIVERED_STATUSES:
        if copying:
            return (f"Duplicate of photo #{anchor_id} ({name}); its content is already at "
                    f"{anchor_dest}, so there is nothing to copy.", anchor_dest)
        return (f"Duplicate of photo #{anchor_id} ({name}), whose content was copied but not "
                f"moved; this source is removed once that photo is moved.", anchor_dest)
    if anchor_status == PhotoStatus.FAILED:
        return (f"Duplicate of photo #{anchor_id} ({name}), whose own transfer failed; its "
                f"content is delivered once that photo succeeds.", None)
    return (f"Duplicate of photo #{anchor_id} ({name}), which was not part of this selection; "
            f"its content is delivered when that photo is copied or moved.", None)


def _rejected_outcome(status: str) -> tuple:
    """(photo status, operation status) for a Move of a rejected photo whose source was
    still here: it went to Rejects, not the library, and stays rejected whatever happened.
    A failure leaves it as it was, waiting with its source still in place."""
    return {PhotoStatus.COMPLETED: (PhotoStatus.REJECTED, PhotoStatus.REJECTED),
            PhotoStatus.COPIED: (PhotoStatus.REJECTED_COPIED, PhotoStatus.REJECTED_COPIED),
            }.get(status, (PhotoStatus.REJECTED_COPIED, status))


def _promote_rejected_duplicates(conn, run_id: int, dest_root: Path, predicate: str, params) -> int:
    """A rejected photo arriving again after Rejects was emptied (engine-spec 9.5): one of
    its copies in this Move's scope takes the rejected photo's place, Rejected_Copied and
    pointed at a free path in Rejects, so the Move carries it there with the same copy,
    verify and delete as any photo, and its other copies are then removed against it.
    A Move therefore never ends with no copy at all of a photo the user only rejected.
    Catalog only; the Move does the file work. Returns how many were promoted."""
    rows = conn.execute(
        f"SELECT id, source_path, sha1_hash, metadata_json FROM photos WHERE status = '{PhotoStatus.DUPLICATE}' "
        f"AND sha1_hash IN (SELECT sha1_hash FROM photos WHERE status IN ({constants.sql_values(REJECTED_STATUSES)}))"
        + predicate + " ORDER BY id", params).fetchall()
    promoted, seen = 0, set()
    for record_id, src, sha1, metadata_json in rows:
        if sha1 in seen:
            continue
        seen.add(sha1)
        held = conn.execute(
            f"SELECT status, dest_path FROM photos WHERE sha1_hash = ? AND status IN ({constants.sql_values(IN_REJECTS_STATUSES)})",
            (sha1,)).fetchall()
        # A copy still in Rejects, or a rejected photo whose own source is still here and
        # carries the content there when it is moved: nothing to promote.
        if any(status == PhotoStatus.REJECTED_COPIED or (path and os.path.lexists(path)) for status, path in held):
            continue
        earlier = conn.execute(
            f"SELECT id, dest_path FROM photos WHERE sha1_hash = ? AND status IN ({constants.sql_values(REJECTED_STATUSES)}) "
            f"ORDER BY id DESC LIMIT 1", (sha1,)).fetchone()
        rejects = ns_db.rejects_root(dest_root)
        if earlier[1] and destinations._is_under(earlier[1], rejects):
            target = Path(earlier[1])
        else:
            library_path = Path(destinations._destination_for(dest_root, src, metadata_json,
                                                 str(ns_db.library_root(dest_root) / constants.UNDATED_FOLDER / Path(src).name)))
            target = destinations._rejects_path_for(dest_root, library_path)
        target = destinations.get_unique_dest_path(target)
        with ns_db.transaction(conn):
            conn.execute("UPDATE photos SET status = ?, dest_path = ? WHERE id = ?",
                         (PhotoStatus.REJECTED_COPIED, str(target), record_id))
            store.log_operation(conn, run_id, record_id, src, str(target), PhotoStatus.REJECTED_COPIED,
                          f"Identical to photo #{earlier[0]}, which you rejected and which has since "
                          f"been emptied from Rejects. This copy takes its place, so the Move puts it "
                          f"in Rejects rather than deleting every copy.", commit=False)
        promoted += 1
    if promoted:
        runtime.logger.info(f"{promoted} rejected photo(s) arrived again after Rejects was emptied; one copy "
                    f"of each goes back to Rejects.")
    return promoted


def normalize_duplicate_groups(db_path: str) -> tuple:
    """
    Re-derives Pending versus Duplicate for every content group from the
    catalog as it is NOW. Returns (promoted, demoted).

    Duplicate is not a property of a file; it is a relation to OTHER rows. The
    unchanged-file skip means a file's own row is not re-examined when a
    different row changes, so a duplicate whose original was edited (new
    hash), failed, or vanished stayed Duplicate with nothing left to deliver
    its content, and was never organized. Reading hashes is the expensive part
    and is not repeated here; this reclassifies from stored values only.

    Per content hash: if any row is Completed, Copied or Processing, the
    content is delivered or in flight, and every Pending or Duplicate row in
    the group is a Duplicate. A rejected row counts the same way: its content
    was turned down, and an identical file must not become a new photo. Otherwise exactly one row — the oldest Pending,
    else the oldest Duplicate — is Pending and the rest are Duplicates. Failed
    rows and removed duplicates take no part. On a catalog built by ordinary
    Index runs this changes nothing; it only repairs groups that drifted.
    """
    delivered_or_in_flight = constants.ANCHOR_DELIVERED_STATUSES + (PhotoStatus.PROCESSING,) + REJECTED_STATUSES
    open_statuses = (PhotoStatus.PENDING, PhotoStatus.DUPLICATE)
    conn = store.get_db_connection(db_path)
    try:
        groups = {}
        for row_id, sha1, status in conn.execute(
            f"SELECT id, sha1_hash, status FROM photos "
            f"WHERE sha1_hash IS NOT NULL AND sha1_hash != '' "
            f"AND status IN ({constants.sql_values(open_statuses + delivered_or_in_flight)}) ORDER BY id"
        ):
            groups.setdefault(sha1, []).append((row_id, status))

        promote, demote = [], []
        for members in groups.values():
            open_rows = [(i, s) for i, s in members if s in open_statuses]
            if not open_rows:
                continue
            if any(s in delivered_or_in_flight for _, s in members):
                keep = None
            else:
                pending = [i for i, s in open_rows if s == PhotoStatus.PENDING]
                keep = pending[0] if pending else open_rows[0][0]
            for i, s in open_rows:
                wanted = PhotoStatus.PENDING if i == keep else PhotoStatus.DUPLICATE
                if wanted != s:
                    (promote if wanted == PhotoStatus.PENDING else demote).append(i)

        conn.executemany("UPDATE photos SET status = ? WHERE id = ?",
                         [(PhotoStatus.PENDING, i) for i in promote]
                         + [(PhotoStatus.DUPLICATE, i) for i in demote])
        conn.commit()
    finally:
        conn.close()
    return len(promote), len(demote)


# Filesystems reached over a network. On these an fsync can be acknowledged before the
# data is on the server's disk (an NFS export marked async, for one), and the client
# cannot see how the share is exported. A Move's deletion is only as safe as that
# acknowledgement, so a Move to one of these is asked about first.
NETWORK_FILESYSTEMS = frozenset({
    "nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "sshfs", "ceph",
    "glusterfs", "fuse.glusterfs", "9p", "afs", "fuse.rclone", "davfs", "fuse.davfs2",
})
NETWORK_DESTINATION_ISSUE = "network_destination_unconfirmed"


def filesystem_type(path: Path, mountinfo: str = "/proc/self/mountinfo") -> Optional[str]:
    """The filesystem type `path` lives on, from the mount whose mount point is the
    longest prefix of it, or None when the mount table cannot be read. Inside a
    container a bind mount reports the type of the storage behind it (nfs4, ext4)."""
    try:
        target = str(Path(path).resolve())
        best, best_type = "", None
        with open(mountinfo) as f:
            for line in f:
                fields = line.split()
                if "-" not in fields:
                    continue
                point = fields[4].encode().decode("unicode_escape")
                fstype = fields[fields.index("-") + 1]
                if (target == point or target.startswith(point.rstrip("/") + "/")) and len(point) >= len(best):
                    best, best_type = point, fstype
        return best_type
    except OSError:
        return None


def _run_move_or_copy(args, db_path: Path, dest_path: Path, run_id: int) -> str:
    """
    Runs the Pre-flight space check, then the Move/Copy loop, then (Move
    only) duplicate source cleanup. Returns the overall run outcome string.
    Checks cancel_requested between files — never mid-file — so a
    cancellation always lets the file currently being copy-verified finish.
    """
    action_verb = "Moving" if args.move else "Copying"
    runtime.logger.info(f"{'Move' if args.move else 'Copy'} Mode enabled. Initiating Pre-flight Space Checks...")
    # This run's durability barriers start unestablished: directories left by
    # an earlier run prove only that mkdir returned, not that their entries
    # reached disk (see _mkdir_durable).
    # The unsupported-fsync notice resets with them, so each run reports its
    # own storage rather than only the first run in a process ever doing so.
    durable._destination_root = dest_path
    durable._verified_directories.clear()
    durable._unsupported_dir_fsync_reported = False
    # FULL rather than the default NORMAL, and this is the only caller that
    # asks. Every delete here commits status=Processing with dest_path BEFORE
    # unlinking, and reconcile_interrupted_state finds interrupted work by that
    # marker alone. Under NORMAL a commit is not fsynced, so a power cut can
    # take the marker while the unlink — which IS fsynced — survives, and the
    # next run finds the source gone with nothing explaining it.
    #
    # Affordable because this path is already fsync-heavy per file: measured
    # 1.42x here (+1.9ms per photo) against the ~4.4x that NORMAL buys on the
    # scan path, which batches a hundred rows per commit and writes no markers.
    # db_writer_worker keeps NORMAL. The loop's audit rows ride along for free,
    # since log_operation commits immediately here on this same connection.
    conn = store.get_db_connection(str(db_path), synchronous="FULL")
    cursor = conn.cursor()

    predicate, predicate_params = targeting._targeting_predicate(args)
    if args.move:
        _promote_rejected_duplicates(conn, run_id, dest_path, predicate, predicate_params)
    # Why --move also takes Copied rows: ns_db.TRANSFER_ELIGIBLE. The web UI counts
    # "Copy all" and "Move all" from the same table.
    eligible = ns_db.TRANSFER_ELIGIBLE["move" if args.move else "copy"]
    cursor.execute(
        f"SELECT id, source_path, dest_path, metadata_json FROM photos "
        f"WHERE status IN ({constants.sql_values(eligible)})" + predicate,
        predicate_params
    )
    pending_records = cursor.fetchall()
    # Rejected photos whose source is still here (engine-spec 9.5): the Move carries them
    # to their place in Rejects, not into the library, and they stay rejected.
    rejected_ids = {row[0] for row in cursor.execute(
        f"SELECT id FROM photos WHERE status = '{PhotoStatus.REJECTED_COPIED}'" + predicate,
        predicate_params)} if args.move else set()

    # A Move to a network share deletes sources on the strength of an fsync the
    # server may acknowledge before the data is on its disk, and the engine cannot
    # see how the share is exported. So it asks first: nothing is copied or
    # deleted, Copy is recommended (the only way to guarantee no loss), and the
    # user answers Copy instead, Move anyway (--confirm-network-destination), or
    # nothing. Copy never deletes, so it is never asked.
    fstype = filesystem_type(dest_path) if args.move else None
    confirmed = getattr(args, "confirm_network_destination", False)
    if fstype in NETWORK_FILESYSTEMS and not confirmed:
        cursor.execute(f"SELECT id, source_path FROM photos WHERE status IN "
                       f"({constants.sql_values(eligible + (PhotoStatus.DUPLICATE,))})" + predicate,
                       predicate_params)
        selected = cursor.fetchall()
        summary = (f"The destination {dest_path} is on a network share ({fstype}). A Move deletes "
                   f"each source once the share says its copy is saved, and a share can say so "
                   f"before the data is really on its disk; NegativeSpace cannot check how the "
                   f"share is set up. Nothing was copied or deleted. Recommended: run Copy "
                   f"instead, which never deletes a source. To Move anyway, confirm the share is "
                   f"exported 'sync' and run the Move with --confirm-network-destination.")
        already = conn.execute("SELECT 1 FROM attention_issues WHERE category = ? AND resolved_at IS NULL",
                               (NETWORK_DESTINATION_ISSUE,)).fetchone()
        runtime.run_progress.start("transferring", len(selected))
        with ns_db.transaction(conn):
            if not already:
                operation_id = ns_db.begin_operation(conn, run_id=run_id, photo_id=None,
                                                     source_path=None, dest_path=str(dest_path),
                                                     kind="network_destination")
                ns_db.settle_operation(conn, operation_id, status=PhotoStatus.FAILED, step="preflight",
                                       outcome="needs_attention", error_message=summary)
                ns_db.open_attention_issue(conn, operation_id=operation_id,
                                           category=NETWORK_DESTINATION_ISSUE, summary=summary)
            for skipped_id, skipped_src in selected:
                store.log_operation(conn, run_id, skipped_id, skipped_src, None, OPERATION_SKIPPED,
                              "Not attempted: the destination is a network share and the Move "
                              "was not confirmed. See the needs-attention note. Nothing was "
                              "changed.", commit=False)
            runtime.run_progress.add(OPERATION_SKIPPED, len(selected))
            runtime.run_progress.write(conn)
        runtime.logger.warning(summary)
        conn.close()
        return RunStatus.COMPLETED
    if confirmed or not args.move:
        # Answered: a confirmed Move, or a Copy chosen instead. Either closes it.
        with ns_db.transaction(conn):
            conn.execute("UPDATE attention_issues SET resolved_at = ? WHERE category = ? "
                         "AND resolved_at IS NULL", (ns_db.utc_now(), NETWORK_DESTINATION_ISSUE))

    # One stat per file, not exists() then stat(): on a network share each is a
    # round trip, all before any data moves. stat() answers both questions, and
    # its failure IS the "missing" case.
    total_bytes_needed = 0
    missing = 0
    already_delivered = 0
    delivered_bytes = 0
    sizes = {}
    for candidate_id, candidate_src, candidate_dst, _ in pending_records:
        try:
            sizes[candidate_id] = os.stat(candidate_src).st_size
        except OSError:
            missing += 1
            continue
        # A row whose recorded destination already holds a file of the same
        # size is not written again: the loop re-verifies both sides live and,
        # for --move, finishes by deleting the source. Budgeting for those
        # bytes would abort Copy-then-Move on a destination with ample room for
        # what the run actually writes. This is only the estimate — the live
        # hash comparison still decides, and a row that does turn out to need
        # writing is caught per file by the copy itself, which fails that one
        # file with a recorded reason and leaves its source intact.
        if candidate_dst:
            try:
                if os.stat(candidate_dst).st_size == sizes[candidate_id]:
                    already_delivered += 1
                    delivered_bytes += sizes[candidate_id]
                    continue
            except OSError:
                pass
        total_bytes_needed += sizes[candidate_id]
    if missing:
        runtime.logger.warning(
            f"{missing:,} of {len(pending_records):,} pending file(s) could not be stat'd and are "
            f"excluded from the space estimate. Each will be recorded with its own reason when "
            f"the loop reaches it."
        )
    if already_delivered:
        runtime.logger.info(
            f"{already_delivered:,} file(s) are already at the destination "
            f"({delivered_bytes / (1024 ** 2):.2f} MB) and need no new space; each is still "
            f"verified live before anything is deleted."
        )

    space_ok, free_bytes, needed_bytes = verify_sufficient_disk_space(dest_path, total_bytes_needed)
    if not space_ok:
        # A pre-flight abort is a run-level failure and must leave a row: the
        # Error Center reads operations, so a shortfall that is only logged is
        # invisible there — the run would read Failed with nothing saying why.
        shortfall = (
            f"Insufficient space at the destination: {needed_bytes / (1024 ** 3):.2f} GB required "
            f"(including the safety margin), {free_bytes / (1024 ** 3):.2f} GB free. Nothing was "
            f"copied, moved or deleted."
        )
        runtime.logger.error(f"Aborting: {shortfall}")
        store.log_operation(conn, run_id, None, str(dest_path), None, PhotoStatus.FAILED, shortfall,
                      commit=False)
        conn.commit()
        conn.close()
        return RunStatus.FAILED

    runtime.logger.info(
        f"Disk space verified. {action_verb} {len(pending_records)} items "
        f"({total_bytes_needed / (1024 ** 2):.2f} MB)..."
    )

    source_root = Path(args.source).resolve()
    runtime.run_progress.start("transferring", len(pending_records))
    # Every selected source gone is what an unplugged share looks like — and also a
    # Move that took everything and then lost its records. The same test the scan
    # applies (nothing found), per selection, so targeted runs are covered too. Stops
    # at the first source that exists, so a normal run pays one stat.
    all_sources_missing = bool(pending_records) and not any(
        not scan._source_missing(src) for _, src, _, _ in pending_records)
    ask_about_empty_source = all_sources_missing and not getattr(args, "confirm_source_empty", False)
    if ask_about_empty_source and pending_records:
        # Ask, don't guess: a detached share and a Move that took everything look
        # the same. Nothing is attempted; every selected photo gets an outcome
        # pointing at the question, in one commit.
        scan.open_source_empty_issue(conn, run_id, source_root, len(pending_records))
        for skipped_id, skipped_src, _, _ in pending_records:
            store.log_operation(conn, run_id, skipped_id, skipped_src, None, OPERATION_SKIPPED,
                          "Not attempted: the source folder is empty. Unplugged, or really "
                          "empty? See the needs-attention note. Nothing was changed.",
                          commit=False)
        runtime.run_progress.add(OPERATION_SKIPPED, len(pending_records))
        runtime.run_progress.write(conn)
        conn.commit()
        pending_records = []
    transfer_started = time.monotonic()
    last_progress_at, last_progress_done, last_progress_bytes = transfer_started, 0, 0
    bytes_done = 0
    was_cancelled = False
    for index, (record_id, src, stored_dst, metadata_json) in enumerate(pending_records):
        if runtime.cancel_requested.is_set():
            was_cancelled = True
            remaining = pending_records[index:]
            runtime.logger.warning(f"Cancellation requested — logging {len(remaining)} remaining item(s) as Cancelled.")
            # One transaction, not one per row. This connection commits at FULL, so a
            # commit per row would be an fsync per row: ~17 s for 24,000 remaining
            # photos, longer than docker stop's default 10 s grace, after which
            # Docker kills the run mid-cancel. All-or-nothing is the right failure mode anyway: a kill
            # during this commit loses only bookkeeping, the photos stay Pending, and
            # the run is recorded Interrupted.
            for cancelled_id, cancelled_src, cancelled_dst, _ in remaining:
                store.log_operation(conn, run_id, cancelled_id, cancelled_src, cancelled_dst,
                              OPERATION_CANCELLED, commit=False)
            runtime.run_progress.add(OPERATION_CANCELLED, len(remaining))
            runtime.run_progress.write(conn)
            conn.commit()
            break
        if runtime.run_progress.due():
            # Its own commit, at most once a second: one extra fsync per second on a
            # loop that already fsyncs several times per file.
            runtime.run_progress.write(conn)
            conn.commit()

        # The same recent-rate progress the scan reports, so a long transfer
        # shows its throughput.
        now = time.monotonic()
        if now - last_progress_at >= constants.PROGRESS_INTERVAL_SECONDS:
            runtime.log_scan_progress(
                index, len(pending_records), transfer_started,
                window_files=index - last_progress_done,
                window_bytes=bytes_done - last_progress_bytes,
                window_seconds=now - last_progress_at,
                label=f"{action_verb} progress",
            )
            last_progress_at, last_progress_done, last_progress_bytes = now, index, bytes_done
        bytes_done += sizes.get(record_id, 0)

        label = destinations._display_path(src, source_root)
        rejected = record_id in rejected_ids
        dst = stored_dst if rejected else destinations._destination_for(dest_path, src, metadata_json, stored_dst)

        if rejected and scan._source_missing(src):
            # Rejected after a Copy, and its source has gone since: nothing to remove.
            # Recorded as observed; the photo stays rejected either way.
            recorded_sha1 = cursor.execute("SELECT sha1_hash FROM photos WHERE id = ?",
                                           (record_id,)).fetchone()[0]
            found = destinations.find_delivered_copy(dst, recorded_sha1)
            cursor.execute("UPDATE photos SET status = ? WHERE id = ?",
                           (PhotoStatus.REJECTED if found else PhotoStatus.REJECTED_EMPTIED, record_id))
            store.log_operation(conn, run_id, record_id, src, dst, OPERATION_SKIPPED,
                          "The source of this rejected photo is already gone; " +
                          ("its copy in Rejects is verified." if found
                           else "its copy is no longer in Rejects either."), commit=False)
            conn.commit()
            runtime.run_progress.add(OPERATION_SKIPPED)
            continue

        # A source that is gone may already be delivered: the state a power cut
        # leaves when this loop's catalog commits are lost and its file work is
        # not. Recorded from what is found, never inferred. An empty source root
        # never reaches here unconfirmed (see above the loop).
        if scan._source_missing(src):
            recorded_sha1 = cursor.execute("SELECT sha1_hash FROM photos WHERE id = ?",
                                           (record_id,)).fetchone()[0]
            found = destinations.find_delivered_copy(dst, recorded_sha1)
            if found is not None:
                destinations.record_found_at_destination(conn, run_id, record_id, src, found, recorded_sha1)
                runtime.run_progress.add(PhotoStatus.FOUND_AT_DESTINATION)
                continue

        # Resolve the final filename HERE, immediately before the file is
        # written — not back at Index time. docs/engine-spec.md 4.3 requires the
        # check to happen "before writing to a computed destination path", and
        # the distinction is not academic: at Index time the destination tree
        # is normally empty, so every same-named file is told its name is free.
        # Two different photos named IMG_0001.jpg (two camera cards, say) would
        # both be assigned the identical destination, and the second one moved
        # would silently destroy the first — source already deleted, both
        # operations reporting success. By this point in the run, anything
        # already written is really on disk, so exists() answers truthfully.
        already_present = False
        source_identity = None
        verified_sha1 = None
        resolved_path = Path(dst)
        if resolved_path.exists():
            # Only hash when the name is actually contested — the common case
            # (free name) pays nothing. The source is re-hashed live rather
            # than trusting the indexed value, so a source edited since the
            # last Index can never be mistaken for "already delivered." Its
            # identity is taken first, so an edit after hashing is caught too.
            with contextlib.suppress(OSError):
                source_identity = durable._file_identity(src)
            verified_sha1 = destinations._sha1_of(Path(src))
            resolved_path, already_present = destinations.resolve_destination(Path(dst), verified_sha1)
        resolved_dst = str(resolved_path)
        has_collision = (resolved_dst != dst)

        intent_id = None
        if already_present:
            # An identical copy is already sitting at the destination from an
            # earlier run. Re-copying would just create IMG_0001_1.jpg beside
            # it, and another one next cycle. For --move the operation is still
            # completed by removing the now-redundant source.
            #
            # Logged BEFORE attempting the delete: the delete can fail noisily
            # (a :ro source, say), and having the explanation arrive after the
            # errors it explains makes the log read backwards.
            runtime.logger.info(f"Already present at destination, skipping copy: {label} -> {resolved_dst}")
            if args.move:
                # Intent first, as the copy path does, so a crash between the
                # delete and the final update leaves a Processing row that
                # reconciliation settles from what is actually on disk.
                cursor.execute("UPDATE photos SET status = ?, dest_path = ? WHERE id = ?",
                               (PhotoStatus.PROCESSING, resolved_dst, record_id))
                intent_id = ns_db.begin_operation(
                    conn, run_id=run_id, photo_id=record_id, source_path=src,
                    dest_path=resolved_dst, kind="move_already_present",
                    expected={"sha1_hash": verified_sha1, "source_removed": True,
                              **({"rejected": True} if rejected else {})})
                conn.commit()
                try:
                    if source_identity is None:
                        raise durable.SourceRemovalRefused("the source could not be examined before verification")
                    durable._remove_verified_source(Path(src), resolved_path, source_identity,
                                            f"Delete already-copied source {Path(src).name}")
                    final_status = PhotoStatus.COMPLETED
                    skip_error = None
                except durable.SourceRemovalRefused as e:
                    final_status = PhotoStatus.FAILED
                    skip_error = f"Source kept: {e}"
                    runtime.logger.warning(f"{skip_error} ({src})")
                except OSError as e:
                    # The copy there was verified above; only the delete failed.
                    final_status = PhotoStatus.COPIED
                    skip_error = f"{ns_db.ORIGINAL_KEPT}: {type(e).__name__}: {e}"
                    runtime.logger.warning(f"Already at the destination, but {skip_error} ({src})")
                except Exception as e:
                    final_status = PhotoStatus.FAILED
                    skip_error = f"{type(e).__name__}: {e}"
            else:
                final_status = PhotoStatus.COPIED
                skip_error = None
            # The final state and its audit entry commit together, so a row can
            # never read Completed without the operation that says so.
            row_status, final_status = _rejected_outcome(final_status) if rejected else (final_status, final_status)
            cursor.execute(
                "UPDATE photos SET status = ?, dest_path = ? WHERE id = ?",
                (row_status, resolved_dst, record_id)
            )
            store.log_operation(conn, run_id, record_id, src, resolved_dst, final_status, skip_error,
                          has_collision, commit=False, operation_id=intent_id,
                          step="move_already_present",
                          delivery=dict(source_removed=row_status in (PhotoStatus.COMPLETED, PhotoStatus.REJECTED),
                                        created=False, sha1_hash=verified_sha1)
                          if final_status != PhotoStatus.FAILED else None)
            conn.commit()
            runtime.run_progress.add(final_status)
            continue

        if has_collision:
            runtime.logger.info(
                f"Destination name already taken by different content — writing "
                f"{Path(dst).name} as {Path(resolved_dst).name} instead."
            )
            cursor.execute(
                "UPDATE photos SET dest_path = ?, has_name_collision = 1 WHERE id = ?",
                (resolved_dst, record_id)
            )

        # DO NOT BATCH THE COMMITS IN THIS LOOP. Unlike the scan phase (see
        # db_writer_worker, which does batch), these commits are not
        # bookkeeping — they are the crash-recovery protocol. The 'Processing'
        # marker must be DURABLE BEFORE the filesystem is touched, because
        # reconcile_interrupted_state() finds interrupted work by looking for
        # rows stuck in exactly this status and then inspecting the filesystem
        # to decide what really happened.
        #
        # Defer this commit and a kill mid-copy leaves the row reading
        # 'Pending' for a file that has already been moved and deleted from
        # source, which reconciliation never examines. The next run would then
        # find the source missing; the check above records such a photo as
        # Found_At_Destination from its content there, but that is the fallback,
        # not the protocol. This connection commits at FULL (see the note where
        # it is opened), so the marker is fsynced before the source is touched.
        #
        # dest_path is written WITH the marker: reconciliation reads it to find
        # the partial and decide what happened, so it must name where this
        # file is actually being written, not where the catalog last put it.
        cursor.execute("UPDATE photos SET status = ?, dest_path = ? WHERE id = ?",
                       (PhotoStatus.PROCESSING, resolved_dst, record_id))
        intent_id = ns_db.begin_operation(
            conn, run_id=run_id, photo_id=record_id, source_path=src, dest_path=resolved_dst,
            kind="move" if args.move else "copy",
            expected={"source_removed": bool(args.move), "created": True,
                      **({"rejected": True} if rejected else {})})
        conn.commit()

        # --move deletes the verified source (delete_source=True, the
        # default); --copy leaves it untouched (delete_source=False).
        verified_content = {}
        success, error_message = durable.copy_verify_delete(src, resolved_dst, delete_source=args.move,
                                                    label=label, verified_content=verified_content)

        # A Move whose original could not be deleted delivered a verified copy: Copied.
        copied_only = args.move and not success and verified_content.get("original_kept", False)
        if args.move:
            final_status = (PhotoStatus.COMPLETED if success
                            else PhotoStatus.COPIED if copied_only else PhotoStatus.FAILED)
        else:
            final_status = PhotoStatus.COPIED if success else PhotoStatus.FAILED
        row_status, final_status = _rejected_outcome(final_status) if rejected else (final_status, final_status)
        cursor.execute("UPDATE photos SET status = ? WHERE id = ?", (row_status, record_id))
        store.log_operation(conn, run_id, record_id, src, resolved_dst, final_status, error_message,
                      has_collision, commit=False, operation_id=intent_id,
                      step="move" if args.move else "copy",
                      delivery=dict(source_removed=args.move and success, created=True,
                                    sha1_hash=verified_content.get("sha1_hash"))
                      if success or copied_only else None)
        conn.commit()
        runtime.run_progress.add(final_status)
    runtime.run_progress.write(conn)
    conn.commit()

    if args.move and not was_cancelled:
        # Duplicate source-file removal is a --move-only step. It's
        # deliberately gated on status='Completed', which only a --move
        # run ever produces (--copy runs produce 'Copied' instead) — so
        # this block naturally never touches anything from a --copy run,
        # keeping --copy fully non-destructive as intended, with no
        # separate mode check needed here. Skipped entirely if this run was
        # cancelled, since acting on duplicates from a run that didn't
        # finish its primary moves could delete a source file whose "kept"
        # copy was itself never confirmed. Every deletion below additionally
        # requires live bytes on both sides to match — see the verification
        # block.
        # Scoped to whatever this run targeted: a two-file --file-ids move
        # must never delete duplicate sources outside the user's selection.
        cursor.execute(
            f"SELECT id, source_path, sha1_hash FROM photos WHERE status = '{PhotoStatus.DUPLICATE}'"
            + predicate,
            predicate_params
        )
        duplicate_records = cursor.fetchall()
        removed_count = 0
        if duplicate_records:
            runtime.run_progress.start("removing_duplicates", len(duplicate_records))
        for index, (record_id, dup_src_str, sha1_hash) in enumerate(duplicate_records):
            if runtime.run_progress.due():
                runtime.run_progress.write(conn)
                conn.commit()
            # Checked before each duplicate, as the copy loop checks before
            # each file: the one in progress finishes, nothing further starts.
            if runtime.cancel_requested.is_set():
                was_cancelled = True
                remaining = duplicate_records[index:]
                runtime.logger.warning(f"Cancellation requested — {len(remaining)} duplicate(s) left in "
                               f"place and recorded as Cancelled.")
                for cancelled_id, cancelled_src, _ in remaining:
                    store.log_operation(conn, run_id, cancelled_id, cancelled_src, None,
                                  OPERATION_CANCELLED, commit=False)
                runtime.run_progress.add(OPERATION_CANCELLED, len(remaining))
                runtime.run_progress.write(conn)
                conn.commit()
                break

            dup_src = Path(dup_src_str)
            if scan._source_missing(dup_src_str):
                # Gone already. If its content is on the destination, record that
                # as observed; otherwise there is nothing to clean up.
                found = None if ask_about_empty_source else destinations.find_content_on_destination(conn, sha1_hash)
                if found is not None:
                    destinations.record_found_at_destination(conn, run_id, record_id, dup_src_str, found, sha1_hash)
                    runtime.run_progress.add(PhotoStatus.FOUND_AT_DESTINATION)
                else:
                    # Nothing to remove and nothing found, so nothing is recorded.
                    runtime.run_progress.add("Already_Gone")
                continue

            # Every row recording a delivered copy of this content, not just
            # the first. LIMIT 1 could pick a row whose file has since been
            # edited or removed and conclude there is no copy, while another
            # row names a copy that is still byte-perfect.
            # A rejected photo's copy in Rejects counts too: the duplicates follow the
            # reject (engine-spec 9.5), removed only against its verified copy there.
            cursor.execute(
                f"SELECT DISTINCT dest_path FROM photos WHERE sha1_hash = ? "
                f"AND status IN ({constants.sql_values((PhotoStatus.COMPLETED, PhotoStatus.FOUND_AT_DESTINATION, PhotoStatus.REJECTED))}) "
                f"AND dest_path IS NOT NULL",
                (sha1_hash,)
            )
            candidates = [row[0] for row in cursor.fetchall()]
            # A copy with an unresolved needs-attention issue never authorizes deleting a
            # source, even with matching bytes (TODO.md claim 15): the source stays until
            # the issue is resolved, and the outcome says so.
            flagged = ns_db.paths_needing_attention(conn, candidates)
            if flagged:
                candidates = [c for c in candidates if c not in flagged]
                if not candidates:
                    reason = (f"Kept: its copy at {sorted(flagged)[0]} has an unresolved needs-attention "
                              f"issue, so it cannot be relied on to remove this source. Resolve the issue, "
                              f"then Move again.")
                    runtime.logger.info(f"Kept duplicate source {destinations._display_path(dup_src_str, source_root)}: {reason}")
                    store.log_operation(conn, run_id, record_id, dup_src_str, sorted(flagged)[0],
                                  OPERATION_SKIPPED, reason)
                    runtime.run_progress.add(OPERATION_SKIPPED)
                    continue
            if not candidates:
                # Nothing delivered to verify against, so the source stays.
                # Recorded as an outcome, not only logged: a duplicate selected
                # without its original otherwise ended the run with no trace.
                reason, pointer = _duplicate_skip_reason(cursor, sha1_hash, copying=False)
                runtime.logger.info(f"Kept duplicate source {destinations._display_path(dup_src_str, source_root)}: {reason}")
                store.log_operation(conn, run_id, record_id, dup_src_str, pointer, OPERATION_SKIPPED, reason)
                runtime.run_progress.add(OPERATION_SKIPPED)
                continue

            # Verify LIVE BYTES on both sides before deleting anything.
            #
            # The catalog's hashes identify candidates; they do not prove the
            # files still match. Either side can have changed since the Index
            # that recorded them — the source edited in place, or the
            # destination copy modified or truncated by something outside this
            # engine. Checking only that the destination path exists is not
            # enough: a file that exists is not a file that matches, and an
            # edited destination would authorize deleting the last remaining
            # copy of a photo.
            #
            # An unreadable candidate must never count as a match either: a
            # permission error or an I/O fault is an absence of evidence, not
            # evidence of a good copy.
            try:
                source_identity = durable._file_identity(dup_src)
                source_sha1 = fileinfo.compute_sha1(dup_src_str)
                verified = None
                read_error = None
                for candidate in candidates:
                    try:
                        if fileinfo.compute_sha1(candidate) == source_sha1:
                            verified = candidate
                            break
                    except OSError as e:
                        read_error = e
                if verified is None:
                    if read_error is not None:
                        raise read_error
                    raise ValueError(
                        "ChecksumMismatch: duplicate source and destination no longer match"
                    )
            except Exception as e:
                # Recorded, not merely logged. The photo stays Duplicate so a
                # later run can retry it once the cause is addressed, and the
                # operations row is what the Error Center reads — a warning in
                # the log is invisible to it.
                error_message = f"Duplicate verification failed: {type(e).__name__}: {e}"
                runtime.logger.warning(f"{error_message} — leaving source file in place: {dup_src}")
                store.log_operation(conn, run_id, record_id, dup_src_str, candidates[0],
                              PhotoStatus.FAILED, error_message)
                runtime.run_progress.add(PhotoStatus.FAILED)
                continue

            # Intent before the delete, with dest_path naming the copy that
            # verified. That pointer is also how reconciliation tells an
            # interrupted duplicate removal (the destination belongs to another
            # row) from an interrupted move of a row's own file.
            cursor.execute("UPDATE photos SET status = ?, dest_path = ? WHERE id = ?",
                           (PhotoStatus.PROCESSING, verified, record_id))
            dup_intent_id = ns_db.begin_operation(
                conn, run_id=run_id, photo_id=record_id, source_path=dup_src_str,
                dest_path=verified, kind="duplicate_removal",
                expected={"sha1_hash": source_sha1, "source_removed": True})
            conn.commit()
            try:
                durable._remove_verified_source(dup_src, Path(verified), source_identity,
                                        f"Deleting verified duplicate {dup_src.name}")
            except Exception as e:
                # Recorded like a verification failure, for the same reason:
                # the source stays, and the operations row is the only thing
                # the Error Center can read to say why. The source is still
                # there, so the row goes back to Duplicate.
                if isinstance(e, durable.SourceRemovalRefused):
                    error_message = f"Source kept: {e}"
                else:
                    error_message = f"Duplicate removal failed: {type(e).__name__}: {e}"
                runtime.logger.warning(f"{error_message} — {dup_src}")
                cursor.execute("UPDATE photos SET status = ? WHERE id = ?",
                               (PhotoStatus.DUPLICATE, record_id))
                store.log_operation(conn, run_id, record_id, dup_src_str, verified,
                              PhotoStatus.FAILED, error_message, commit=False,
                              operation_id=dup_intent_id, step="duplicate_removal")
                conn.commit()
                runtime.run_progress.add(PhotoStatus.FAILED)
                continue
            cursor.execute("UPDATE photos SET status = ?, dest_path = ? WHERE id = ?",
                           (PhotoStatus.REMOVED_DUPLICATE, verified, record_id))
            store.log_operation(conn, run_id, record_id, dup_src_str, verified,
                          PhotoStatus.REMOVED_DUPLICATE, commit=False,
                          operation_id=dup_intent_id, step="duplicate_removal",
                          delivery=dict(source_removed=True, created=False, sha1_hash=source_sha1))
            conn.commit()
            runtime.run_progress.add(PhotoStatus.REMOVED_DUPLICATE)
            removed_count += 1
            runtime.logger.info(f"Removed duplicate source file: {dup_src} (verified copy at {verified})")

        runtime.run_progress.write(conn)
        conn.commit()
        if duplicate_records:
            runtime.logger.info(f"Duplicate cleanup: removed {removed_count} of {len(duplicate_records)} flagged duplicates.")

    if args.copy and not was_cancelled:
        # --copy never writes a duplicate: its original carries the content.
        # Record that for each duplicate in scope, so every selected photo has
        # an outcome. A selection holding only duplicates otherwise did
        # nothing, exited 0 and recorded nothing — which a UI shows as success.
        cursor.execute(
            f"SELECT id, source_path, sha1_hash FROM photos WHERE status = '{PhotoStatus.DUPLICATE}'"
            + predicate,
            predicate_params
        )
        # Part of the Copy's scope, so they join its denominator and its counts
        # in the one commit that records them.
        copy_skips = 0
        for record_id, dup_src_str, sha1_hash in cursor.fetchall():
            reason, pointer = _duplicate_skip_reason(cursor, sha1_hash, copying=True)
            store.log_operation(conn, run_id, record_id, dup_src_str, pointer, OPERATION_SKIPPED, reason,
                          commit=False)
            copy_skips += 1

        # A photo an EARLIER run delivered is not a copy candidate and is not a
        # duplicate either, so a selection naming it finished with no record at
        # all — the same silence §5.3 objects to for duplicate-only selections.
        # The reason states what the catalog holds: this run read and verified
        # nothing, so it must not be shown as confirmation that the destination
        # file is still present and intact.
        #
        # Excluding what this run already recorded is what keeps "earlier" true.
        # This runs after the copy loop, by which point the rows it just wrote
        # are themselves 'Copied', and without the exclusion every delivered
        # photo ended its own job with two contradictory outcomes. Keying on
        # this run's operations rather than a list of copied ids also covers
        # the files it failed or cancelled: one outcome per photo per run.
        cursor.execute(
            f"SELECT id, source_path, dest_path FROM photos WHERE status = '{PhotoStatus.COPIED}'"
            + predicate
            + " AND id NOT IN (SELECT photo_id FROM operations "
              "WHERE run_id = ? AND photo_id IS NOT NULL)",
            tuple(predicate_params) + (run_id,)
        )
        for record_id, copied_src, copied_dst in cursor.fetchall():
            store.log_operation(
                conn, run_id, record_id, copied_src, copied_dst, OPERATION_SKIPPED,
                f"Already copied to {copied_dst} by an earlier run, so there is nothing to copy; "
                f"this run re-verified nothing. Index reads sources, never the destination — if "
                f"that file is missing, re-index with --force-rehash and copy again. Use --move "
                f"to finish moving it.",
                commit=False
            )
            copy_skips += 1
        runtime.run_progress.set_total((runtime.run_progress.total or 0) + copy_skips)
        runtime.run_progress.add(OPERATION_SKIPPED, copy_skips)
        runtime.run_progress.write(conn)
        conn.commit()

    # Point every duplicate at the copy that actually exists.
    #
    # A Duplicate row keeps the dest_path projected for it at Index time — a
    # path under its OWN filename that is never written, because only Pending
    # rows are copied. The row therefore described a file that does not exist,
    # which is useless precisely when it matters: answering "this source file
    # was a duplicate, so where did its content actually end up?"
    #
    # Rewriting it to the surviving copy's real path makes each duplicate
    # record a usable pointer. The group is already queryable by sha1_hash;
    # this makes each member individually answerable too. Runs after the
    # move/copy loop and duplicate cleanup, so the anchor's dest_path is final
    # (collision suffixes included) rather than still a projection.
    if not was_cancelled:
        cursor.execute(
            "UPDATE photos SET dest_path = ("
            "    SELECT anchor.dest_path FROM photos AS anchor"
            "     WHERE anchor.sha1_hash = photos.sha1_hash"
            f"       AND anchor.status IN ({constants.sql_values(constants.ANCHOR_DELIVERED_STATUSES)})"
            "     LIMIT 1)"
            # Duplicate only. A Removed_Duplicate row already names the copy
            # its deletion was verified against; overwriting it with the first
            # delivered row found could point it at a different, stale copy.
            f" WHERE status = '{PhotoStatus.DUPLICATE}'"
            "   AND EXISTS ("
            "    SELECT 1 FROM photos AS anchor"
            "     WHERE anchor.sha1_hash = photos.sha1_hash"
            f"       AND anchor.status IN ({constants.sql_values(constants.ANCHOR_DELIVERED_STATUSES)}))" + predicate,
            predicate_params
        )
        if cursor.rowcount:
            # Deliberately does NOT say "verified". This step only rewrites a
            # pointer from the catalog; it reads no files. The one place that
            # acts destructively on that pointer — duplicate cleanup above —
            # hashes both sides live before deleting anything, and that is
            # where the guarantee lives. Claiming verification here would be
            # the same overstatement this function's caller exists to prevent.
            runtime.logger.info(
                f"Repointed {cursor.rowcount} duplicate record(s) at the destination recorded "
                f"for their content."
            )
        conn.commit()

    if was_cancelled:
        # Each loop above records what it abandoned — but only for the pass it
        # was in. A cancellation during the primary transfers sets this flag,
        # which then skips the duplicate pass (--move) and the skipped-outcome
        # pass (--copy) outright, so every duplicate in the selection, and
        # every already-delivered file in a --copy selection, ended the run
        # with no row at all. Not Cancelled — nothing. That is the same
        # silence §5.3 objects to, and it breaks the promise the block above
        # states in its own comment: every selected photo has an outcome.
        #
        # Reconciling the selection against what was actually recorded keeps
        # that promise for whatever the loops never reached, without either
        # pass having to know what the other did. The statuses are the ones
        # this run's selections were drawn from; anything those passes did
        # handle already carries an operations row for THIS run and is
        # excluded by it. Keying on the recorded rows rather than re-deriving
        # scope from status is what makes that reliable — the loops rewrite
        # status as they go, so by here it no longer describes the selection.
        cursor.execute(
            f"SELECT id, source_path FROM photos "
            f"WHERE status IN ({constants.sql_values(constants.CANCELLABLE_SELECTION_STATUSES)})" + predicate
            + " AND id NOT IN (SELECT photo_id FROM operations "
              "WHERE run_id = ? AND photo_id IS NOT NULL)",
            tuple(predicate_params) + (run_id,)
        )
        unreached = cursor.fetchall()
        for record_id, unreached_src in unreached:
            # No dest_path recorded: this run neither wrote nor verified
            # anything for this file, and a Duplicate row's stored dest_path
            # is an Index-time projection that was never written. Naming it
            # here would point the audit record at a file that does not exist.
            store.log_operation(conn, run_id, record_id, unreached_src, None, OPERATION_CANCELLED,
                          "The run was cancelled before this file was reached. Nothing was "
                          "attempted on it and nothing about it changed.",
                          commit=False)
        if unreached:
            conn.commit()
            runtime.logger.info(f"Cancellation: {len(unreached)} selected file(s) were never reached and "
                        f"are recorded as Cancelled.")

    conn.close()

    if was_cancelled:
        runtime.logger.info(f"{'Move' if args.move else 'Copy'} operation cancelled by user request.")
        return RunStatus.CANCELLED

    runtime.logger.info(f"All {'move' if args.move else 'copy'} operations finished.")
    return RunStatus.COMPLETED
