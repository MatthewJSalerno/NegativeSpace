"""Reconciliation at the start of every job: what an interrupted run left behind, and what changed outside the app."""

import hashlib
import json
import os
import stat
from pathlib import Path

from engine.ns_db import (
    PhotoStatus, RunStatus, OPERATION_RENAMED, OPERATION_EMPTIED, IN_REJECTS_STATUSES)
from engine import constants, durable, ns_db, relocate, runtime, store


def _recovery_observe(path: Path):
    """A non-file (including a symlink) is not an absent or verified photo."""
    try:
        return "present" if stat.S_ISREG(path.lstat().st_mode) else "not_file"
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unreadable"


def _recovery_verify(path: Path, expected):
    """Hash a stable regular file, without following a replacement symlink or
    blocking on a substituted FIFO. Recovery observes; it never edits this file.
    """
    def identity(st):
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns
    details = {"expected_sha1": expected}
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                return "not_file", details
            digest = hashlib.sha1()
            for chunk in iter(lambda: stream.read(constants.SHA1_CHUNK_SIZE), b""):
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            details["observed_sha1"] = digest.hexdigest()
            if identity(before) != identity(after) or identity(after) != identity(path.lstat()):
                return "changed", details
        if not expected:
            return "unestablished", details
        return ("match" if details["observed_sha1"] == expected else "mismatch"), details
    except OSError as exc:
        details["error"] = type(exc).__name__
        return "unreadable", details


def reconcile_interrupted_state(db_path: Path, run_id: int):
    """
    Settles work a previous run left mid-flight by OBSERVING, recording what it
    observed, and only then concluding.

    Every mutation records durable intent before touching a file, so interrupted
    work is an operation carrying intent and no terminal event. Recovery reads
    that intent, looks at both locations, writes an evidence row per location,
    and settles the operation against what it found.

    A present destination must be a stable regular file whose SHA-1 matches the
    durable intent (or indexed digest when the intent omits it). Presence alone is not
    evidence of delivery. Mismatch or unverifiable content requires attention.

      * destination verified, source gone - settle the Move and repair lineage.
      * destination gone, source present   - nothing was published; retry it.
      * BOTH present, destination verified - the copy landed and the source was
        never removed. The published file is registered as its own identity and
        the operation is recorded INCOMPLETE. Recovery never deletes the source;
        an explicit Move may, after verifying both sides live.
      * BOTH gone, or either unreadable    - the outcome cannot be established.
        An attention issue is opened carrying the evidence, and the row is NOT
        reset to Pending, which would claim the file is waiting for work it can
        never receive.

    Runs at synchronous=FULL. These conclusions are drawn from evidence that may
    not be observable again - storage disappears, files are replaced - so losing
    them to a power cut is not the benign case that NORMAL assumes elsewhere.
    """
    if not db_path.exists():
        return

    runtime.logger.info("Checking database for interrupted tasks from previous runs...")
    conn = store.get_db_connection(str(db_path), synchronous="FULL")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='photos';")
        if not cursor.fetchone():
            return

        cursor.execute(
            f"SELECT id, source_path, dest_path, sha1_hash FROM photos "
            f"WHERE status = '{PhotoStatus.PROCESSING}'"
        )
        for record_id, src_str, dst_str, sha1 in cursor.fetchall():
            src, dst = Path(src_str), Path(dst_str)

            # Partials carry a random suffix (see _stage_copy), so they are found
            # by prefix. Only regular files are removed: a symlink at a
            # partial-looking name was not created by this engine.
            prefix = dst.name + constants.PARTIAL_SUFFIX + "."
            orphans = []
            try:
                with os.scandir(dst.parent) as entries:
                    orphans = [e.path for e in entries
                               if e.name.startswith(prefix) and e.is_file(follow_symlinks=False)]
            except FileNotFoundError:
                pass
            for orphan in orphans:
                runtime.logger.warning(f"Found orphaned partial file: {Path(orphan).name}. Removing.")
                os.unlink(orphan)

            duplicate_removal = cursor.execute(
                f"SELECT 1 FROM photos WHERE id != ? AND sha1_hash = ? AND dest_path = ? "
                f"AND status IN ({constants.sql_values(constants.ANCHOR_DELIVERED_STATUSES)}) LIMIT 1",
                (record_id, sha1, dst_str)
            ).fetchone() is not None

            source_state, dest_state = _recovery_observe(src), _recovery_observe(dst)
            unsettled = ns_db.unsettled_operations(conn, record_id)
            prior_id = unsettled[-1][0] if unsettled else None
            intent_row = conn.execute(
                "SELECT detail_json FROM operation_events WHERE operation_id=? AND step='intent' ORDER BY event_id LIMIT 1",
                (prior_id,)).fetchone() if prior_id else None
            intent = json.loads(intent_row[0]) if intent_row and intent_row[0] else {}
            expected = intent.get("expected") or {}
            kind = intent.get("kind")
            if kind:
                duplicate_removal = kind == "duplicate_removal"
            expected_sha1 = expected.get("sha1_hash") or sha1
            verification, verification_details = (None, None)
            if dest_state == "present":
                verification, verification_details = _recovery_verify(dst, expected_sha1)

            # One transaction per reconciled row: evidence, the settled
            # operation and the photo's new status commit together or not at
            # all. Opened explicitly: no earlier write in this loop opens one,
            # so the first evidence write would otherwise run outside it.
            conn.execute("BEGIN IMMEDIATE")
            operation_id = prior_id if prior_id is not None else ns_db.begin_operation(
                conn, run_id=run_id, photo_id=record_id, source_path=src_str,
                dest_path=dst_str, kind="recovered_without_intent")

            for role, path, state in (("source", src_str, source_state),
                                      ("destination", dst_str, dest_state)):
                ns_db.record_evidence(conn, operation_id=operation_id, location_role=role,
                                      observed_path=path, observation_kind="stat",
                                      result="unreadable" if state == "not_file" else state,
                                      details={"state": state})
            if verification is not None:
                ns_db.record_evidence(conn, operation_id=operation_id, location_role="destination",
                                      observed_path=dst_str, observation_kind="sha1",
                                      result=verification if verification in ("match", "mismatch") else "unreadable",
                                      details={**verification_details, "verification": verification})
            for orphan in orphans:
                ns_db.record_evidence(conn, operation_id=operation_id, location_role="partial",
                                      observed_path=orphan, observation_kind="stat",
                                      result="present", details={"removed": True})

            if (any(state in ("unreadable", "not_file") for state in (source_state, dest_state))
                    or (source_state == "absent" and dest_state == "absent")
                    or (dest_state == "present" and verification != "match")
                    or (kind == "copy" and source_state == "absent")):
                # Neither guess is honest. The source is gone or unexaminable and
                # nothing verifiable stands at the destination, so this run cannot
                # say whether the photo was delivered.
                final = PhotoStatus.FAILED
                if source_state == "absent":
                    # Absence is observed, but removal by this operation is not
                    # established without a verified delivery.
                    conn.execute("UPDATE file_states SET presence_state='missing',revision=revision+1 "
                                 "WHERE file_id=(SELECT file_id FROM photo_files WHERE photo_id=?) "
                                 "AND location_role='source'", (record_id,))
                note = (f"Recovery could not establish what happened: the source is "
                        f"{source_state} and the destination is {dest_state} "
                        f"(content verification: {verification or 'unavailable'}). The file's "
                        f"recorded history is kept and this needs attention.")
                ns_db.settle_operation(conn, operation_id, status=final, step="recovery",
                                       outcome="unestablished", error_message=note)
                evidence_ids = [r[0] for r in conn.execute(
                    "SELECT evidence_id FROM operation_evidence WHERE operation_id=?",
                    (operation_id,))]
                ns_db.open_attention_issue(
                    conn, operation_id=operation_id, category="unestablished_outcome",
                    summary=note,
                    file_id=(conn.execute("SELECT file_id FROM photo_files WHERE photo_id=?",
                                          (record_id,)).fetchone() or [None])[0],
                    evidence_ids=evidence_ids)
            elif dest_state == "present" and source_state == "absent":
                already_recorded = conn.execute(
                    "SELECT 1 FROM file_states WHERE current_path=? AND location_role='destination' "
                    "AND presence_state='present'", (dst_str,)).fetchone() is not None
                ns_db.record_delivery(conn, operation_id=operation_id, photo_id=record_id,
                                      run_id=run_id, destination=dst_str, source_removed=True,
                                      created=bool(expected.get("created")) and not already_recorded,
                                      sha1_hash=expected_sha1)
                final = PhotoStatus.REMOVED_DUPLICATE if duplicate_removal else PhotoStatus.COMPLETED
                note = (f"Recovered after an interrupted run: the source is gone and the "
                        f"destination content is verified at {dst}.")
                ns_db.settle_operation(conn, operation_id, status=final, step="recovery",
                                       outcome="completed", error_message=note)
            elif dest_state == "present" and source_state == "present":
                # The copy landed; the source was never removed. Two real files,
                # one logical relocation. Register the published file as its own
                # identity and leave the Move incomplete - the source stays
                # eligible for an explicit Move that verifies both sides live.
                final = PhotoStatus.DUPLICATE if duplicate_removal else PhotoStatus.PENDING
                note = ("File delivered; source not removed. The destination copy is present "
                        "and the source is still here, so the Move did not finish. Run Move "
                        "again for this source to verify both copies and remove it.")
                already_recorded = conn.execute(
                    "SELECT 1 FROM file_states WHERE current_path=? AND location_role='destination' "
                    "AND presence_state='present'", (dst_str,)).fetchone() is not None
                ns_db.record_delivery(conn, operation_id=operation_id, photo_id=record_id,
                                      run_id=run_id, destination=dst_str, source_removed=False,
                                      created=bool(expected.get("created")) and not already_recorded,
                                      sha1_hash=expected_sha1)
                ns_db.settle_operation(conn, operation_id, status=final, step="move",
                                       outcome="incomplete", error_message=note)
            else:
                final = PhotoStatus.DUPLICATE if duplicate_removal else PhotoStatus.PENDING
                note = ("Recovered after an interrupted run: nothing was published at the "
                        "destination, so it will be retried.")
                ns_db.settle_operation(conn, operation_id, status=final, step="recovery",
                                       outcome="not_started", error_message=note)

            if expected.get("rejected"):
                # A rejected photo's Move goes to Rejects; whatever happened, it stays
                # rejected (engine-spec 9.5): delivered there, or still waiting with its source.
                final = {PhotoStatus.COMPLETED: PhotoStatus.REJECTED,
                         PhotoStatus.PENDING: PhotoStatus.REJECTED_COPIED}.get(final, final)

            # The repair belongs to the run that performed it, linked to the
            # operation it repairs. The interrupted operation keeps its own
            # settled outcome and its evidence; this row is what a reader sees
            # when asking what THIS run did, and reconciles_operation_id is what
            # keeps requested work and recovery separable.
            recovery_id = ns_db.begin_operation(
                conn, run_id=run_id, photo_id=record_id, source_path=src_str,
                dest_path=dst_str, kind="recovery", reconciles=operation_id)
            conn.execute("INSERT OR IGNORE INTO operation_files(operation_id,file_id,role) "
                         "SELECT ?,file_id,role FROM operation_files WHERE operation_id=? AND role<>'source'",
                         (recovery_id, operation_id))
            ns_db.settle_operation(conn, recovery_id, status=final, step="recovery",
                                   outcome="recorded", error_message=note)
            cursor.execute("UPDATE photos SET status = ? WHERE id = ?", (final, record_id))
            conn.commit()
            runtime.logger.info(f"Reconciled interrupted record {record_id} as {final}.")

        _reconcile_interrupted_renames(conn, run_id)
        _notice_emptied_rejects(conn, run_id)

        # A run killed uncatchably never reaches finish_run(), so its row stays
        # in an active state with no end time. This process holds the
        # single-instance lock, so no other run can still be alive: mark them
        # Interrupted, naming this run as the one that found them. The end time
        # stays unknown — now is when the death was noticed, not when it happened.
        placeholders = ','.join('?' * len(ns_db.ACTIVE_RUN_STATUSES))
        dead = conn.execute(
            f"SELECT id, status FROM runs WHERE status IN ({placeholders}) AND id != ?",
            (*ns_db.ACTIVE_RUN_STATUSES, run_id)).fetchall()
        # Deliberately not `run_id`: rebinding it would destroy the reconciling
        # run's own id, which the evidence above is written against.
        for dead_run_id, was in dead:
            runtime.logger.warning(f"Run #{dead_run_id} was left '{was}' by an unclean shutdown - "
                           f"marking Interrupted.")
            ns_db.transition_run(conn, dead_run_id, RunStatus.INTERRUPTED, reconciled_by=run_id)
    except BaseException:
        # Never swallowed. A failed reconciliation leaves rows Processing, and a
        # run that continued would treat an unsettled catalog as settled.
        conn.rollback()
        runtime.logger.error("Startup state reconciliation failed; the catalog was not settled.",
                     exc_info=True)
        raise
    finally:
        conn.close()


def _reconcile_interrupted_renames(conn, run_id: int):
    """Settles a rename, reject or return to the library that a failed or killed run left without
    an outcome, from what is on disk. All three are one no-replace rename within the
    destination (_rename_noreplace).

    Success requires a stable regular file matching the intent's hash. Both names
    on that verified inode mean link-then-unlink stopped between its steps; recheck
    both names before removing the old link. Only the verified old name present
    means nothing happened. Unverifiable outcomes need attention, without removal.
    """
    def observe(path):
        try:
            info = os.lstat(path)
            return info if stat.S_ISREG(info.st_mode) else "not_file"
        except FileNotFoundError:
            return None
        except OSError:
            return "unreadable"

    def signature(info):
        if not isinstance(info, os.stat_result):
            return info
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns

    def state_name(info):
        return "present" if isinstance(info, os.stat_result) else info or "absent"

    for operation_id, photo_id, old, new in ns_db.unsettled_operations(conn):
        intent = conn.execute("SELECT detail_json FROM operation_events WHERE operation_id = ? AND "
                              "step = 'intent'", (operation_id,)).fetchone()
        detail = json.loads(intent[0]) if intent and intent[0] else {}
        kind = detail.get("kind")
        if kind not in relocate._RELOCATION_NOUNS:
            continue
        expected = detail.get("expected") or {}
        file_id = expected.get("file_id")
        noun = relocate._RELOCATION_NOUNS[kind]
        states = {"old": observe(old), "new": observe(new)}
        o, n = states["old"], states["new"]
        same_file = (isinstance(o, os.stat_result) and isinstance(n, os.stat_result)
                     and (o.st_dev, o.st_ino) == (n.st_dev, n.st_ino))
        candidate = ("new" if isinstance(n, os.stat_result) and (o is None or same_file) else
                     "old" if isinstance(o, os.stat_result) and n is None else None)
        verification, verified = None, {}
        if candidate:
            verification, verified = _recovery_verify(Path(new if candidate == "new" else old),
                                                      expected.get("sha1_hash"))
            if verification == "match" and candidate == "new":
                # Establish the retained directory entry before dropping an old hard link.
                durable._fsync_directory(Path(new).parent)
        conn.execute("BEGIN IMMEDIATE")
        recovered_event = None
        for role, path in (("source", old), ("destination", new)):
            state = states["old" if role == "source" else "new"]
            ns_db.record_evidence(conn, operation_id=operation_id, location_role=role, observed_path=path,
                                  observation_kind="stat",
                                  result="unreadable" if state == "not_file" else state_name(state),
                                  details={"state": state_name(state)})
        if verification == "match":
            for role, path in (("old", old), ("new", new)):
                current = observe(path)
                if signature(current) != signature(states[role]):
                    verification = "changed"
                    verified.setdefault("changed_paths", []).append(role)
                    ns_db.record_evidence(conn, operation_id=operation_id,
                        location_role="source" if role == "old" else "destination", observed_path=path,
                        observation_kind="stat", result="unreadable" if current == "not_file" else state_name(current),
                        details={"state": state_name(current), "after_verification": True})
        if candidate:
            ns_db.record_evidence(conn, operation_id=operation_id,
                location_role="destination" if candidate == "new" else "source",
                observed_path=new if candidate == "new" else old, observation_kind="sha1",
                result=verification if verification in ("match", "mismatch") else "unreadable",
                details={**verified, "verification": verification})
        if candidate == "new" and verification == "match":
            if same_file:
                os.unlink(old)
            # Retry the old-directory barrier even when a prior attempt already
            # removed the old name and failed on this very sync.
            if same_file or Path(old).parent != Path(new).parent:
                durable._fsync_directory(Path(old).parent)
            recovered_event = relocate._record_relocation(conn, operation_id, old, new, file_id,
                               detail={"recovered": True, "status_before": expected.get("status_before")},
                               step="recovery",
                               operation_status=expected.get("operation_status", OPERATION_RENAMED),
                               photo_id=photo_id if kind != "rename" else None,
                               status_after=expected.get("status_after"))
            runtime.logger.info(f"Recovered an interrupted {noun}: {old} is now {new}.")
        elif candidate == "old" and verification == "match":
            recovered_event = ns_db.settle_operation(conn, operation_id, status=PhotoStatus.FAILED, step="recovery",
                                   outcome="not_started", error_message=f"The {noun} was interrupted "
                                   "before it happened; the file stays where it was. Nothing was changed.")
        else:
            reason = {"mismatch": "the content differs from the recorded hash",
                      "changed": "a file or path changed during verification",
                      "unreadable": "the file could not be read",
                      "not_file": "the path is not a regular file",
                      "unestablished": "the intent records no expected hash"}.get(verification)
            old_state = "not a regular file" if o == "not_file" else state_name(o)
            new_state = "not a regular file" if n == "not_file" else state_name(n)
            note = (f"An interrupted {noun} could not be settled: the old path {old} is "
                    f"{old_state} and the new path {new} is {new_state}"
                    f"{' (a different file)' if o and n and not same_file else ''}"
                    f"{'; ' + reason if reason else ''}. Nothing was removed. "
                    "Review both locations outside NegativeSpace before taking further action.")
            ns_db.settle_operation(conn, operation_id, status=PhotoStatus.FAILED, step="recovery",
                                   outcome="unestablished", error_message=note)
            if conn.execute("SELECT 1 FROM attention_issues WHERE operation_id=? "
                            "AND category='unestablished_outcome' AND resolved_at IS NULL",
                            (operation_id,)).fetchone():
                conn.execute("UPDATE attention_issues SET summary=? WHERE operation_id=? "
                             "AND category='unestablished_outcome' AND resolved_at IS NULL", (note, operation_id))
            else:
                ns_db.open_attention_issue(conn, operation_id=operation_id, category="unestablished_outcome",
                                           summary=note, file_id=file_id)
            runtime.logger.warning(note)
        if recovered_event is not None:
            for (issue_id,) in conn.execute("SELECT issue_id FROM attention_issues WHERE operation_id=? "
                                           "AND category='unestablished_outcome' AND resolved_at IS NULL",
                                           (operation_id,)).fetchall():
                ns_db.resolve_attention_issue(conn, issue_id, event_id=recovered_event)
        conn.commit()


def _notice_emptied_rejects(conn, run_id: int) -> int:
    """Records rejected photos whose file is gone from Rejects: the user emptied it
    (engine-spec 9.5). Run as every job starts, so it is noticed without an Index. Reads
    no file, one stat each. Recorded as observed, never guessed at: the photo leaves the
    Rejects view, and keeps its fingerprints, so an identical file is still recognised
    as rejected. A destination that is not mounted (no library folder beside Rejects)
    proves nothing, and nothing is recorded."""
    marker = f"/{ns_db.REJECTS_FOLDER}/"
    noticed = 0
    for photo_id, src, path, status in conn.execute(
            f"SELECT id, source_path, dest_path, status FROM photos WHERE dest_path IS NOT NULL "
            f"AND status IN ({constants.sql_values(IN_REJECTS_STATUSES)}) ORDER BY id").fetchall():
        if marker not in path or not os.path.isdir(ns_db.library_root(path[:path.rindex(marker)])):
            continue
        # An uncertain relocation can explain a missing old Rejects path. Its
        # attention issue must not be overwritten by an inference that the user
        # emptied the file; this applies on later starts as well as this one.
        if conn.execute("SELECT 1 FROM attention_issues a JOIN operations o ON o.id=a.operation_id "
                        "WHERE a.resolved_at IS NULL AND a.category='unestablished_outcome' "
                        "AND o.photo_id=? AND o.source_path=? LIMIT 1", (photo_id, path)).fetchone():
            continue
        try:
            os.lstat(path)
            continue
        except FileNotFoundError:
            pass
        except OSError:
            continue
        last = conn.execute("SELECT status, dest_path FROM operations WHERE photo_id = ? ORDER BY id DESC LIMIT 1",
                            (photo_id,)).fetchone()
        if last == (OPERATION_EMPTIED, path):
            continue    # Rejected after a Copy: noticed already, and its source still waits for a Move.
        with ns_db.transaction(conn):
            conn.execute("UPDATE file_states SET presence_state = 'missing', revision = revision + 1 "
                         "WHERE current_path = ? AND location_role = 'destination' AND presence_state = 'present'",
                         (path,))
            if status == PhotoStatus.REJECTED:
                conn.execute("UPDATE photos SET status = ? WHERE id = ?", (PhotoStatus.REJECTED_EMPTIED, photo_id))
            store.log_operation(conn, run_id, photo_id, src, path, OPERATION_EMPTIED,
                          "No longer in Rejects when this job started: emptied outside NegativeSpace. "
                          "Its fingerprints stay in the catalog, so an identical file is recognised as "
                          "rejected.", commit=False)
        noticed += 1
    if noticed:
        runtime.logger.info(f"{noticed:,} rejected photo(s) are no longer in Rejects: emptied, recorded in their history.")
    return noticed
