"""Rename, Reject and Return to library: moving delivered files within the destination."""

import contextlib
import ctypes
import errno
import json
import os
from pathlib import Path

from engine.ns_db import (
    PhotoStatus, RunStatus, OPERATION_CANCELLED, OPERATION_SKIPPED, OPERATION_RENAMED,
    OPERATION_RETURNED, IN_REJECTS_STATUSES, SUPPORTED_EXTENSIONS)
from engine import (
    backups, constants, destinations, durable, fileinfo, jobs, ns_db, reconcile, runtime, store,
    targeting)


class RenameRefused(Exception):
    """A rename that cannot proceed, with a reason the user can act on. Nothing changed."""


class NoReplaceUnsupported(OSError):
    """The destination filesystem offers no way to rename without risking an overwrite."""


_RENAME_NOREPLACE = 1
_AT_FDCWD = -100


def _rename_noreplace(old: str, new: str) -> str:
    """Renames `old` to `new` only if `new` does not exist, and says how.

    Linux renameat2(RENAME_NOREPLACE) first: one atomic step, so an interruption
    leaves the file at exactly one of the two names. Filesystems without it (NFS
    among them) get link-then-unlink, which is still no-overwrite - link() fails
    when the name exists - but has a moment with both names on one inode, which
    recovery completes (_reconcile_interrupted_renames). A filesystem offering
    neither raises NoReplaceUnsupported: a plain rename() would silently replace a
    file created at the new name in the meantime, and the no-overwrite promise is
    not weakened to accommodate it. Raises FileExistsError when `new` is taken.
    """
    renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if renameat2 is not None:
        if renameat2(_AT_FDCWD, os.fsencode(old), _AT_FDCWD, os.fsencode(new), _RENAME_NOREPLACE) == 0:
            return "renameat2"
        err = ctypes.get_errno()
        if err == errno.EEXIST:
            raise FileExistsError(err, os.strerror(err), new)
        if err not in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
            raise OSError(err, os.strerror(err), old)
    try:
        os.link(old, new)
    except FileExistsError:
        raise
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK, errno.ENOSYS):
            raise NoReplaceUnsupported(exc.errno, f"this filesystem supports neither an atomic "
                                                  f"no-replace rename nor hard links ({exc.strerror})")
        raise
    # If unlink fails, preserve both names and the durable intent. Rolling the
    # link back is another fallible mutation and can erase recovery's evidence.
    os.unlink(old)
    return "link"


def rename_candidates(db_path: Path, photo_id: int) -> dict:
    """The filenames a delivered photo's content has carried, for the Rename tab
    (webui-spec 7.3): every catalogued copy's source name, current and historical,
    across its exact-duplicate group. Read only; no lock.

    Returns {'photo_id', 'current_path', 'candidates': [{'name', 'seen_at': [paths]}],
    'error'}; the current name is not a candidate."""
    result = {"photo_id": photo_id, "current_path": None, "candidates": [], "error": None}
    if not Path(db_path).exists():
        return dict(result, error="There is no catalog yet.")
    with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
        ns_db.require_schema(conn)
        row = conn.execute("SELECT sha1_hash, dest_path, status FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if row is None:
            return dict(result, error="No catalogued photo has this id.")
        sha1, current, status = row
        if status not in constants.ANCHOR_DELIVERED_STATUSES or not current or not sha1:
            return dict(result, error="This photo has not been delivered to the destination.")
        seen = {}
        for (path,) in conn.execute(
                "SELECT source_path FROM photos WHERE sha1_hash = ? AND source_path IS NOT NULL "
                "UNION SELECT o.source_path FROM operations o JOIN photos p ON p.id = o.photo_id "
                "WHERE p.sha1_hash = ? AND o.source_path IS NOT NULL", (sha1, sha1)):
            stem = Path(path).stem
            if stem != Path(current).stem:
                seen.setdefault(stem, set()).add(path)
    return dict(result, current_path=current,
                candidates=[{"name": stem, "seen_at": sorted(paths)} for stem, paths in sorted(seen.items())])


def _new_name_stem(name: str, current_suffix: str) -> str:
    """The stem a requested name gives. The delivered file's real extension is always
    kept, so a trailing extension the engine knows (or the current one) is dropped;
    anything else - "Trip.2019" - is part of the name. Raises RenameRefused."""
    name = name.strip()
    suffix = Path(name).suffix.lower()
    stem = name[:-len(suffix)] if suffix and (suffix in SUPPORTED_EXTENSIONS or
                                              suffix == current_suffix.lower()) else name
    if not stem or stem in (".", ".."):
        raise RenameRefused("The new name is empty.")
    if "/" in stem or "\0" in stem:
        raise RenameRefused("A name cannot contain '/'; the date folder is kept as it is.")
    if stem.startswith("."):
        raise RenameRefused("A name starting with '.' would be hidden, and hidden files are skipped.")
    if len(os.fsencode(stem + current_suffix)) > 255:
        raise RenameRefused("The name is too long for a file name (255 bytes).")
    return stem


def plan_rename(conn, dest_root: Path, photo_id: int, name: str) -> dict:
    """Where a rename would put the file, checked against the files there now: the
    requested stem with the file's real extension, in the same date folder, with the
    `_N` suffix on a collision (webui-spec 7.3 "a typed name validates live against
    the destination folder"). Reads only. Raises RenameRefused.

    Returns {'photo_id', 'sha1', 'current_path', 'new_path', 'collision', 'unchanged'}."""
    row = conn.execute("SELECT sha1_hash, dest_path, status FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if row is None:
        raise RenameRefused("No catalogued photo has this id.")
    sha1, current, status = row
    if status not in constants.ANCHOR_DELIVERED_STATUSES or not current or not sha1:
        raise RenameRefused("This photo has not been delivered to the destination.")
    if not destinations._is_under(current, dest_root):
        raise RenameRefused(f"This photo was delivered outside the current destination ({dest_root}).")
    current_path = Path(current)
    stem = _new_name_stem(name, current_path.suffix)
    wanted = current_path.parent / f"{stem}{current_path.suffix}"
    candidate, counter = wanted, 1
    while candidate != current_path and os.path.lexists(candidate):
        candidate = current_path.parent / f"{stem}_{counter}{current_path.suffix}"
        counter += 1
    return {"photo_id": photo_id, "sha1": sha1, "current_path": current, "new_path": str(candidate),
            "collision": candidate != wanted and candidate != current_path,
            "unchanged": candidate == current_path}


def preview_rename(db_path: Path, dest_root: Path, photo_id: int, name: str) -> dict:
    """--rename --dry-run: the plan, or why there is none. No lock, changes nothing."""
    if not Path(db_path).exists():
        return {"photo_id": photo_id, "error": "There is no catalog yet."}
    with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
        ns_db.require_schema(conn)
        try:
            plan = plan_rename(conn, dest_root, photo_id, name)
        except RenameRefused as exc:
            return {"photo_id": photo_id, "error": str(exc)}
    plan.pop("sha1")
    return dict(plan, error=None)


def rename_delivered_file(db_path: Path, dest_root: Path, backups_dir: Path, base_dir: Path,
                          run_id: int, photo_id: int, name: str) -> str:
    """Gives a delivered file a new name (engine-spec 9.4). Returns the run outcome.

    Planning, verification and backup precede any file changes. Once intent is
    recorded, an uncertain filesystem error remains recoverable:
      1. Plan it against the files there now; the same name again changes nothing.
      2. Verify the file live: present, and its SHA-1 still the catalog's. A missing
         or changed file is a destination mismatch (webui-spec 7.6), recorded Failed.
      3. Back up the catalog (trigger pre_action). If that fails, nothing is renamed.
      4. Record intent, durably, then rename without overwriting (_rename_noreplace)
         and make the directory entry durable.
      5. In one commit: every catalog row pointing at the old path now points at the
         new one, the file identity's current path moves with it, and the operation
         settles Renamed with both paths. Historical operations keep their paths.
    """
    conn = store.get_db_connection(str(db_path), synchronous="FULL")
    try:
        try:
            plan = plan_rename(conn, dest_root, photo_id, name)
        except RenameRefused as exc:
            runtime.logger.error(f"Rename refused: {exc} Nothing was changed.")
            return RunStatus.FAILED
        old, new = plan["current_path"], plan["new_path"]
        if plan["unchanged"]:
            runtime.logger.info(f"Photo #{photo_id} is already named {Path(old).name}; nothing to change.")
            return RunStatus.COMPLETED
        file_id = (conn.execute("SELECT file_id FROM file_states WHERE current_path = ? AND "
                                "location_role = 'destination' AND presence_state = 'present'",
                                (old,)).fetchone() or [None])[0]

        mismatch = None
        try:
            if fileinfo.compute_sha1(old) != plan["sha1"]:
                mismatch = "its content no longer matches the catalog"
        except FileNotFoundError:
            mismatch = "it is no longer there"
        except OSError as exc:
            mismatch = f"it could not be read ({type(exc).__name__}: {exc})"
        if mismatch:
            note = (f"Not renamed: the destination file {old} differs from the catalog - {mismatch}. "
                    f"Nothing was changed. The destination differs from the catalog; see the "
                    f"destination check and the fresh-destination workflow.")
            with ns_db.transaction(conn):
                op = ns_db.begin_operation(conn, run_id=run_id, photo_id=photo_id, source_path=old,
                                           dest_path=new, kind="rename")
                ns_db.settle_operation(conn, op, status=PhotoStatus.FAILED, step="rename",
                                       outcome="destination_mismatch", error_message=note)
            runtime.logger.error(note)
            return RunStatus.FAILED

        backup = ns_db.backup_catalog(db_path, backups_dir, base_dir, trigger="pre_action",
                                      related_run_id=run_id)
        backups._log_backup(backup, "before the rename")
        if backup["outcome"] != "succeeded":
            runtime.logger.error("No files were changed because the catalog backup failed.")
            return RunStatus.FAILED

        with ns_db.transaction(conn):
            op = ns_db.begin_operation(conn, run_id=run_id, photo_id=photo_id, source_path=old,
                                       dest_path=new, kind="rename",
                                       expected={"old_path": old, "new_path": new, "file_id": file_id,
                                                 "sha1_hash": plan["sha1"]})
        phase = "rename"
        try:
            method = _rename_noreplace(old, new)
            phase = "sync"
            durable._fsync_directory(Path(new).parent)
        except OSError as exc:
            _record_relocation_failure(conn, op, "rename", phase, old, new, file_id, exc)
            return RunStatus.FAILED
        with ns_db.transaction(conn):
            _record_rename(conn, op, old, new, file_id, detail={"method": method})
        runtime.logger.info(f"Renamed {Path(old).name} to {Path(new).name} in {Path(new).parent}"
                    + (" (the name was taken, so a suffix was added)" if plan["collision"] else "") + ".")
        return RunStatus.COMPLETED
    finally:
        conn.close()


def _record_rename(conn, operation_id, old: str, new: str, file_id, detail=None, step="rename"):
    """Points the catalog at a renamed file, in the caller's transaction."""
    _record_relocation(conn, operation_id, old, new, file_id, detail=detail, step=step,
                       operation_status=OPERATION_RENAMED)


def _record_relocation(conn, operation_id, old: str, new: str, file_id, *, detail=None, step: str,
                       operation_status: str, photo_id=None, status_after=None):
    """Points the catalog at a file moved within the destination (a rename, a reject, a
    return), in the caller's transaction: every row naming the old path, the file
    identity's current path, the photo's new status when it has one, and the operation
    settled with both paths. Historical operations keep their paths."""
    conn.execute("UPDATE photos SET dest_path = ? WHERE dest_path = ?", (new, old))
    if photo_id is not None and status_after:
        conn.execute("UPDATE photos SET status = ? WHERE id = ?", (status_after, photo_id))
    if file_id is not None:
        conn.execute("UPDATE file_states SET current_path = ?, revision = revision + 1 WHERE file_id = ?",
                     (new, file_id))
        conn.execute("INSERT OR IGNORE INTO operation_files VALUES (?,?,'destination')", (operation_id, file_id))
    return ns_db.settle_operation(conn, operation_id, status=operation_status, step=step, outcome="completed",
                                 detail=dict(detail or {}, old_path=old, new_path=new))


# What an interrupted move within the destination was, in recovery's messages.
_RELOCATION_NOUNS = {"rename": "rename", "reject": "reject", "return": "return to the library"}


def _record_relocation_failure(conn, operation_id, kind, phase, old, new, file_id, exc):
    """Record a refusal only when no photo mutation was possible. Otherwise keep
    the intent recoverable, with last-known catalog state and explicit uncertainty.
    Returns whether recovery is needed. A failed attempt is not a terminal outcome.
    """
    uncertain = not (phase == "prepare" or
                     (phase == "rename" and isinstance(exc, (FileExistsError, NoReplaceUnsupported))))
    noun = _RELOCATION_NOUNS[kind]
    if uncertain:
        note = (f"The {noun} could not be confirmed: {exc}. The file may already be at {new}; "
                f"the catalog still records {old}. Restore destination access, then run Index "
                "to verify both paths and recover the recorded operation before trying this action again.")
    else:
        reason = "the new name was taken a moment ago" if isinstance(exc, FileExistsError) else str(exc)
        note = f"The {noun} was refused: {reason}. No photo was moved."
    with ns_db.transaction(conn):
        if uncertain:
            # unsettled_operations deliberately uses terminal events, not status.
            # Logs can report this attempt as Failed without hiding it from recovery.
            conn.execute("UPDATE operations SET status=?,error_message=? WHERE id=?",
                         (PhotoStatus.FAILED, note, operation_id))
            evidence = []
            for role, path in (("source", old), ("destination", new)):
                state = reconcile._recovery_observe(Path(path))
                evidence.append(ns_db.record_evidence(conn, operation_id=operation_id,
                    location_role=role, observed_path=path, observation_kind="stat",
                    result="unreadable" if state == "not_file" else state,
                    details={"state": state, "phase": phase, "error": str(exc)}))
            ns_db.open_attention_issue(conn, operation_id=operation_id, file_id=file_id,
                category="unestablished_outcome", summary=note, evidence_ids=evidence)
        else:
            ns_db.settle_operation(conn, operation_id, status=PhotoStatus.FAILED, step=kind,
                                   outcome="failed", error_message=note)
    runtime.logger.error(note)
    return uncertain


def run_rename(args, db_path: Path, base_dir: Path, lock_fd) -> int:
    """--rename PHOTO_ID --name NAME, as a job (run_maintenance_job)."""
    dest_root = Path(args.dest).resolve()
    return jobs.run_maintenance_job(
        args, db_path, lock_fd, mode="RENAME", label="Rename",
        submitted={"photo_id": args.rename, "name": args.name, "dest": str(dest_root)},
        defaults={}, overrides={},
        body=lambda run_id, config: rename_delivered_file(db_path, dest_root, Path(args.backups), base_dir,
                                                          run_id, args.rename, args.name))


def _status_before_reject(conn, photo_id: int, status: str) -> str:
    """What a rejected photo goes back to on Return to library. Rejected after a Copy with
    its source still here: Copied. Otherwise the delivered status it had when rejected
    (Completed or Found_At_Destination), and Completed when no reject recorded one, as
    for a copy that arrived again and went to Rejects in its own right."""
    if status == PhotoStatus.REJECTED_COPIED:
        return PhotoStatus.COPIED
    row = conn.execute(
        "SELECT e.detail_json FROM operation_events e JOIN operations o ON o.id = e.operation_id "
        "WHERE o.photo_id = ? AND o.status = ? AND e.step IN ('reject', 'recovery') "
        "AND e.outcome = 'completed' ORDER BY e.event_id DESC LIMIT 1",
        (photo_id, PhotoStatus.REJECTED)).fetchone()
    before = (json.loads(row[0]) if row and row[0] else {}).get("status_before")
    return before if before in (PhotoStatus.COMPLETED, PhotoStatus.FOUND_AT_DESTINATION) else PhotoStatus.COMPLETED


# Why a selected photo was left alone, by its status: every selected photo gets an outcome.
def _relocation_skip_reason(status: str, returning: bool) -> str:
    if status in (PhotoStatus.DUPLICATE, PhotoStatus.REMOVED_DUPLICATE):
        return ("A copy of another photo; it follows that photo." if returning else
                "A copy of another photo; reject that photo and its copies follow it.")
    if status == PhotoStatus.REJECTED_EMPTIED:
        return ("Rejects has been emptied of this photo, so there is nothing to return." if returning
                else "Already rejected; Rejects has since been emptied of it.")
    if returning:
        return "Already in the library." if status in constants.ANCHOR_DELIVERED_STATUSES else "Not in Rejects."
    if status in IN_REJECTS_STATUSES:
        return "Already in Rejects."
    return "Not organized yet: only photos in the library can be rejected."


def relocate_in_destination(db_path: Path, dest_root: Path, backups_dir: Path, base_dir: Path,
                            run_id: int, args, returning: bool) -> str:
    """Reject (engine-spec 9.5): moves each selected organized photo's file from
    dest/library to its place in dest/rejects. Return to library: moves a rejected photo
    back to its date folder. Nothing is deleted; the user empties Rejects.

    Per photo, as Rename (rename_delivered_file): the file is verified live against the
    catalog, intent is recorded durably, the file is renamed without overwriting and the
    directory entries made durable, and then one commit points every catalog row at the
    new path and sets the photo's status. The catalog is backed up once, before the first
    file moves; if that fails nothing moves. A photo's exact duplicates need no step of
    their own: they follow the photo's status (Move and Copy, engine-spec 9.5).
    """
    durable._destination_root = dest_root
    durable._verified_directories.clear()
    verb, past = ("Return to library", "returned") if returning else ("Reject", "rejected")
    kind = "return" if returning else "reject"
    from_root = ns_db.rejects_root(dest_root) if returning else ns_db.library_root(dest_root)
    acts_on = IN_REJECTS_STATUSES if returning else constants.ANCHOR_DELIVERED_STATUSES
    if args.source_subdir:
        source_root = Path(args.source).resolve()
        if not destinations._is_under(str((source_root / args.source_subdir).resolve()), source_root):
            runtime.logger.error(f"--source-subdir must resolve to a path under --source ({source_root}). "
                         f"Nothing was changed.")
            return RunStatus.FAILED
    predicate, params = targeting._targeting_predicate(args)
    conn = store.get_db_connection(str(db_path), synchronous="FULL")
    try:
        rows = conn.execute("SELECT id, source_path, dest_path, sha1_hash, status, metadata_json FROM photos "
                            "WHERE 1 = 1" + predicate + " ORDER BY id", params).fetchall()
        act = [r for r in rows if r[4] in acts_on]
        runtime.run_progress.start("transferring", len(rows))
        with ns_db.transaction(conn):
            for photo_id, src, dest, _, status, _ in rows:
                if status not in acts_on:
                    store.log_operation(conn, run_id, photo_id, src, dest, OPERATION_SKIPPED,
                                  _relocation_skip_reason(status, returning), commit=False)
            runtime.run_progress.add(OPERATION_SKIPPED, len(rows) - len(act))
            runtime.run_progress.write(conn)
        if not act:
            runtime.logger.info(f"{verb}: none of the {len(rows):,} selected photo(s) can be {past}; nothing was changed.")
            return RunStatus.COMPLETED

        backup = ns_db.backup_catalog(db_path, backups_dir, base_dir, trigger="pre_action", related_run_id=run_id)
        backups._log_backup(backup, f"before {verb.lower()}")
        if backup["outcome"] != "succeeded":
            with ns_db.transaction(conn):
                for photo_id, src, dest, _, _, _ in act:
                    store.log_operation(conn, run_id, photo_id, src, dest, PhotoStatus.FAILED,
                                  f"Not {past}: the catalog backup failed. Nothing was changed.", commit=False)
                runtime.run_progress.add(PhotoStatus.FAILED, len(act))
                runtime.run_progress.write(conn)
            runtime.logger.error("No files were moved because the catalog backup failed.")
            return RunStatus.FAILED

        done = failed = 0
        needs_recovery = False
        for index, (photo_id, src, old, sha1, status, metadata_json) in enumerate(act):
            if runtime.cancel_requested.is_set():
                remaining = act[index:]
                with ns_db.transaction(conn):
                    for cancelled_id, cancelled_src, cancelled_dest, _, _, _ in remaining:
                        store.log_operation(conn, run_id, cancelled_id, cancelled_src, cancelled_dest,
                                      OPERATION_CANCELLED, commit=False)
                    runtime.run_progress.add(OPERATION_CANCELLED, len(remaining))
                    runtime.run_progress.write(conn)
                runtime.logger.warning(f"Cancelled: {len(remaining):,} photo(s) left where they were.")
                break
            if runtime.run_progress.due():
                with ns_db.transaction(conn):
                    runtime.run_progress.write(conn)

            problem = None
            if not old or not sha1:
                problem = "the catalog records no file for it"
            elif not destinations._is_under(old, from_root):
                problem = f"its file is not in {from_root} ({old})"
            else:
                try:
                    if fileinfo.compute_sha1(old) != sha1:
                        problem = "its file no longer matches the catalog"
                except FileNotFoundError:
                    problem = f"its file {old} is no longer there"
                except OSError as exc:
                    problem = f"its file could not be read ({type(exc).__name__}: {exc})"
                if problem:
                    problem += (". The destination differs from the catalog; see the destination check "
                                "and the fresh-destination workflow")
            if problem:
                with ns_db.transaction(conn):
                    store.log_operation(conn, run_id, photo_id, src, old, PhotoStatus.FAILED,
                                  f"Not {past}: {problem}. Nothing was changed.", commit=False)
                runtime.logger.error(f"Not {past}: photo #{photo_id}: {problem}.")
                failed += 1
                runtime.run_progress.add(PhotoStatus.FAILED)
                continue

            if returning:
                fallback = str(destinations._library_path_for(dest_root, old))
                folder = Path(destinations._destination_for(dest_root, src, metadata_json, fallback)).parent
                wanted = folder / Path(old).name
                status_after = _status_before_reject(conn, photo_id, status)
                operation_status = OPERATION_RETURNED
            else:
                wanted = destinations._rejects_path_for(dest_root, old)
                status_after = PhotoStatus.REJECTED_COPIED if status == PhotoStatus.COPIED else PhotoStatus.REJECTED
                operation_status = PhotoStatus.REJECTED
            new = str(destinations.get_unique_dest_path(wanted))
            file_id = (conn.execute("SELECT file_id FROM file_states WHERE current_path = ? AND "
                                    "location_role = 'destination' AND presence_state = 'present'",
                                    (old,)).fetchone() or [None])[0]
            with ns_db.transaction(conn):
                operation_id = ns_db.begin_operation(
                    conn, run_id=run_id, photo_id=photo_id, source_path=old, dest_path=new, kind=kind,
                    expected={"old_path": old, "new_path": new, "file_id": file_id, "sha1_hash": sha1,
                              "status_before": status, "status_after": status_after,
                              "operation_status": operation_status})
            phase = "prepare"
            try:
                durable._mkdir_durable(Path(new).parent)
                phase = "rename"
                method = _rename_noreplace(old, new)
                phase = "sync"
                durable._fsync_directory(Path(new).parent)
                durable._fsync_directory(Path(old).parent)
            except OSError as exc:
                uncertain = _record_relocation_failure(conn, operation_id, kind, phase, old, new, file_id, exc)
                needs_recovery = needs_recovery or uncertain
                failed += 1
                runtime.run_progress.add(PhotoStatus.FAILED)
                continue
            with ns_db.transaction(conn):
                _record_relocation(conn, operation_id, old, new, file_id, step=kind,
                                   detail={"method": method, "status_before": status},
                                   operation_status=operation_status, photo_id=photo_id,
                                   status_after=status_after)
            done += 1
            runtime.run_progress.add(operation_status)

        with ns_db.transaction(conn):
            runtime.run_progress.write(conn)
        held, size = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM photos "
                                  f"WHERE status IN ({constants.sql_values(IN_REJECTS_STATUSES)})").fetchone()
        runtime.logger.info(f"{verb}: {done:,} photo(s) {past}" + (f", {failed:,} failed" if failed else "") +
                    f". Rejects now holds {held:,} photo(s), {size / 1e6:,.1f} MB, in "
                    f"{ns_db.rejects_root(dest_root)}; empty it yourself when you are sure.")
        return RunStatus.FAILED if needs_recovery else RunStatus.COMPLETED
    finally:
        conn.close()


def run_relocation(args, db_path: Path, base_dir: Path, lock_fd) -> int:
    """--reject or --return-to-library, as a job (run_maintenance_job)."""
    dest_root = Path(args.dest).resolve()
    returning = bool(args.return_to_library)
    return jobs.run_maintenance_job(
        args, db_path, lock_fd, mode="RETURN" if returning else "REJECT",
        label="Return to library" if returning else "Reject", submitted={}, targeted=True,
        defaults={}, overrides={},
        body=lambda run_id, config: relocate_in_destination(db_path, dest_root, Path(args.backups), base_dir,
                                                            run_id, args, returning))
