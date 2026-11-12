"""Repair (engine-spec 9.2): fixes what the latest library check found, by moving or copying
files back to where the catalog records them. Every fix is previewed first and recorded in
the photo's lineage; nothing is deleted, and a file that changed since the check is left
alone and reported.

Built: Move it back (a photo found elsewhere in the Library), Move back from Rejects and
Copy it back from the source. Everything else the check found is listed as not fixable
here, with what the user can do.
"""

import collections
import contextlib
import os
from pathlib import Path
from typing import Optional

from engine import (backups, durable, fileinfo, library_check, metadata_relocate, ns_db, relocate,
                    runtime, store)
from engine.ns_db import PhotoStatus, RunStatus, OPERATION_CANCELLED, OPERATION_REPAIRED, OPERATION_SKIPPED

# What each fix does, in the preview's and the lineage's words (webui-spec 7.6).
FIXES = ("move_back", "from_rejects", "copy_back")

# Advice for what Repair cannot fix (webui-spec 7.6).
NO_COPY_TODO = "If the original is still somewhere in your source, Index source finds it; then check the library again."
UNREADABLE_TODO = "Fix its permissions, then check the library again."


def latest_check(conn) -> Optional[int]:
    return conn.execute(library_check.LATEST_COMPLETED_SQL).fetchone()[0]


def _pending(conn, check_run: int, photo_ids=None) -> list:
    """The latest check's unsettled findings for Library photos still where and what it
    checked (library_check.pending_sql), with each photo's source path."""
    columns = [d[0] for d in conn.execute("SELECT * FROM destination_findings LIMIT 0").description]
    sql = (f"SELECT f.*, p.source_path AS photo_source FROM destination_findings f JOIN photos p ON p.id=f.photo_id "
           f"WHERE f.run_id=? AND f.settled_by IS NULL AND f.path=p.dest_path AND f.expected_sha1 IS p.sha1_hash "
           f"AND p.status IN ({ns_db.sql_values(ns_db.DELIVERED_STATUSES)})")
    if photo_ids is None:
        batches = [None]
    else:
        ids = sorted({int(i) for i in photo_ids})
        batches = [ids[i:i + 500] for i in range(0, len(ids), 500)]
    rows = []
    for batch in batches:
        where = "" if batch is None else f" AND f.photo_id IN ({','.join('?' * len(batch))})"
        rows += [dict(zip(columns + ["photo_source"], r))
                 for r in conn.execute(sql + where + " ORDER BY f.path", (check_run, *(batch or ())))]
    return rows


def classify(conn, f: dict, library: Path, dest_root: Path, holders: collections.Counter) -> dict:
    """One photo's finding as Repair sees it: a fix ({'repair', 'from', 'to'}) or what
    the user can do instead ({'todo'})."""
    rel = lambda p: library_check.shown_path(p, library)
    described = library_check.describe(f, library, {})
    item = {"photo_id": f["photo_id"], "path": f["path"], "relative": rel(f["path"]),
            "finding": described["finding"], "what": described["what"]}
    where, found = f.get("found_in"), f.get("found_path")
    folder = os.path.dirname(f["path"])
    if f["kind"] == "missing" and where:
        if where == "library" and os.path.dirname(found) == folder:
            if holders[f["expected_sha1"]] > 1:
                return {**item, "todo": f"Its content is in {holders[f['expected_sha1']]} files in this folder. Keep "
                                        f"one, then check the library again."}
            return {**item, "todo": "It was renamed, and its XMP sidecar NegativeSpace delivered still has the old "
                                    "name. Repair can't rename the pair yet: rename the .xmp to match, then check "
                                    "the library again."}
        if metadata_relocate.current(conn, f["path"]) is not None:
            return {**item, "todo": f"NegativeSpace delivered an XMP sidecar with it, and Repair can't move the pair "
                                    f"yet. Put the photo and its .xmp back in {rel(folder)} yourself, then check the "
                                    f"library again."}
        if where == "rejects":
            owner = conn.execute("SELECT id FROM photos WHERE dest_path=?", (found,)).fetchone()
            if owner:
                return {**item, "todo": f"Its content is photo #{owner[0]}, which you rejected. Return that photo "
                                        f"to the library if you want it back."}
        to = os.path.join(folder, os.path.basename(found)) if where == "library" else f["path"]
        return {**item, "repair": {"library": "move_back", "rejects": "from_rejects", "source": "copy_back"}[where],
                "from": found, "to": to, "from_relative": rel(found) if where != "source" else None,
                "to_relative": rel(to), "folder": rel(folder)}
    if f["kind"] == "missing":
        return {**item, "todo": NO_COPY_TODO, "index_source": True}
    if f["kind"] == "unreadable":
        copy = ""
        if where == "source":
            copy = " A copy is in the source, so the photo isn't lost."
        elif where:
            copy = f" A copy is at {rel(found)}, so the photo isn't lost."
        return {**item, "todo": UNREADABLE_TODO + copy, "reason": f.get("detail"),
                "from_destination": os.path.relpath(f["path"], dest_root)}
    return {**item, "todo": described["todo"]}


def plan(conn, dest_root: Path, photo_ids=None) -> dict:
    """What Repair would do for the given photos (all the latest check's, without ids):
    the fixes grouped by kind and target folder, and what it cannot fix (webui-spec 7.6).
    Reads only the catalog."""
    dest_root = Path(dest_root).resolve()
    check_run = latest_check(conn)
    if check_run is None:
        return {"check_run": None, "groups": [], "cannot": [], "unreadable": [], "fixes": 0}
    library = Path(conn.execute("SELECT library FROM library_checks WHERE run_id=?", (check_run,)).fetchone()[0])
    rows = _pending(conn, check_run, photo_ids)
    holders = collections.Counter(r[0] for r in conn.execute(
        "SELECT observed_sha1 FROM destination_findings WHERE run_id=? AND kind='unknown' AND observed_sha1 IS NOT NULL",
        (check_run,)))
    items = [classify(conn, f, library, dest_root, holders) for f in rows]
    groups = {}
    for item in items:
        if "repair" in item:
            groups.setdefault((FIXES.index(item["repair"]), item["folder"]), []).append(item)
    fix_groups = [{"repair": FIXES[kind], "folder": folder, "items": members}
                  for (kind, folder), members in sorted(groups.items())]
    cannot = [i for i in items if "repair" not in i]
    return {"check_run": check_run, "groups": fix_groups, "cannot": cannot,
            "unreadable": [{"path": i["from_destination"], "reason": i.get("reason")}
                           for i in cannot if "from_destination" in i],
            "fixes": sum(len(g["items"]) for g in fix_groups)}


def _settle_findings(conn, check_run: int, operation_id: int, *paths) -> None:
    conn.execute(f"UPDATE destination_findings SET settled_by=? WHERE run_id=? AND path IN ({','.join('?' * len(paths))})",
                 (operation_id, check_run, *paths))


def _move(conn, run_id: int, check_run: int, dest_root: Path, item: dict, sha1: str) -> tuple:
    """Move it back, or back from Rejects: a verified, no-overwrite rename with its intent
    recorded first, as Return to library does (relocate.relocate_in_destination).
    Returns (status, needs_recovery)."""
    old, recorded, kind = item["from"], item["path"], item["repair"]
    if kind == "from_rejects":
        new = recorded
    else:
        new = str(metadata_relocate.choose_target(conn, dest_root, old, Path(item["to"]), "repair"))
    file_id = (conn.execute("SELECT file_id FROM file_states WHERE current_path=? AND location_role='destination' "
                            "AND presence_state='present'", (recorded,)).fetchone() or [None])[0]
    expected = {"old_path": old, "new_path": new, "recorded_path": recorded, "file_id": file_id, "sha1_hash": sha1,
                "operation_status": OPERATION_REPAIRED, "repair": kind, "check_run": check_run}
    with ns_db.transaction(conn):
        op = ns_db.begin_operation(conn, run_id=run_id, photo_id=item["photo_id"], source_path=old, dest_path=new,
                                   kind="repair", expected=expected)
    phase = "prepare"
    try:
        durable._mkdir_durable(Path(new).parent)
        phase = "rename"
        method = relocate._rename_noreplace(old, new)
        phase = "sync"
        durable._fsync_directory(Path(new).parent)
        durable._fsync_directory(Path(old).parent)
    except (OSError, ValueError) as exc:
        return PhotoStatus.FAILED, relocate._record_relocation_failure(conn, op, "repair", phase, old, new, file_id, exc)
    with ns_db.transaction(conn):
        relocate._record_relocation(conn, op, old, new, file_id, step="repair", operation_status=OPERATION_REPAIRED,
                                    photo_id=item["photo_id"], recorded=recorded,
                                    detail={"method": method, "repair": kind, "check_run": check_run})
        _settle_findings(conn, check_run, op, recorded, old)
    runtime.logger.info(f"Repaired photo #{item['photo_id']}: {old} -> {new}.")
    return OPERATION_REPAIRED, False


def _copy(conn, run_id: int, check_run: int, item: dict, sha1: str) -> tuple:
    """Copy it back from the source: staged beside the recorded path, verified against the
    photo's recorded checksum, then published without overwriting. The catalog already
    names that path, so an interruption leaves nothing to recover: no file, or the photo."""
    source, recorded = item["from"], Path(item["path"])
    durable._mkdir_durable(recorded.parent)
    partial = durable._stage_copy(Path(source), recorded)
    try:
        if fileinfo.compute_sha1(str(partial)) != sha1:
            raise ValueError("the copy in the source changed since the check")
        durable._finalize_partial(partial, recorded)
        partial = None
    finally:
        if partial is not None:
            with contextlib.suppress(OSError):
                partial.unlink()
    file_id = (conn.execute("SELECT file_id FROM file_states WHERE current_path=? AND location_role='destination' "
                            "AND presence_state='present'", (str(recorded),)).fetchone() or [None])[0]
    with ns_db.transaction(conn):
        op = ns_db.begin_operation(conn, run_id=run_id, photo_id=item["photo_id"], source_path=source,
                                   dest_path=str(recorded), kind="repair",
                                   expected={"repair": "copy_back", "check_run": check_run, "sha1_hash": sha1})
        if file_id is not None:
            conn.execute("INSERT OR IGNORE INTO operation_files VALUES (?,?,'destination')", (op, file_id))
        ns_db.settle_operation(conn, op, status=OPERATION_REPAIRED, step="repair", outcome="completed",
                               detail={"repair": "copy_back", "check_run": check_run, "source": source,
                                       "new_path": str(recorded)})
        _settle_findings(conn, check_run, op, str(recorded))
    runtime.logger.info(f"Repaired photo #{item['photo_id']}: copied {source} back to {recorded}.")
    return OPERATION_REPAIRED, False


def _stale(item: dict, sha1: str) -> Optional[str]:
    """Why a planned fix must not run now (engine-spec 9.2, Guards), or None."""
    if os.path.lexists(item["path"]):
        return "a file is at its recorded place again"
    try:
        if fileinfo.compute_sha1(item["from"]) != sha1:
            return "the file the check found has changed since"
    except FileNotFoundError:
        return "the file the check found is no longer there"
    except OSError as exc:
        return f"the file the check found can't be read ({type(exc).__name__}: {exc})"
    return None


def repair(db_path: Path, dest_root: Path, backups_dir: Path, base_dir: Path, run_id: int, check_run: int) -> str:
    """--repair-library CHECK_RUN for the selected photos (webui-spec 7.6). Each photo is
    planned again from the catalog; one the preview offered nothing for, or whose file
    changed since the check, is skipped with its reason. The catalog is backed up before
    the first fix, and nothing is fixed if that fails, and again after."""
    dest_root = Path(dest_root).resolve()
    durable._destination_root = dest_root
    durable._verified_directories.clear()
    conn = store.get_db_connection(str(db_path), synchronous="FULL")
    try:
        selected = [r[0] for r in conn.execute("SELECT photo_id FROM run_selections WHERE run_id=? ORDER BY photo_id",
                                               (run_id,))]
        runtime.run_progress.start("transferring", len(selected))
        latest = latest_check(conn)
        if latest != check_run:
            with ns_db.transaction(conn):
                for photo_id, path in conn.execute("SELECT p.id, p.dest_path FROM run_selections s JOIN photos p "
                                                   "ON p.id=s.photo_id WHERE s.run_id=? ORDER BY p.id", (run_id,)).fetchall():
                    store.log_operation(conn, run_id, photo_id, path, None, OPERATION_SKIPPED,
                                        "Not repaired: a newer library check ran since this Repair was previewed. "
                                        "Open Repair again to see what it found.", commit=False)
                runtime.run_progress.add(OPERATION_SKIPPED, len(selected))
                runtime.run_progress.write(conn)
            runtime.logger.error("A newer library check ran since this Repair was previewed; nothing was changed.")
            return RunStatus.FAILED
        planned = plan(conn, dest_root, selected)
        items = {i["photo_id"]: i for g in planned["groups"] for i in g["items"]}
        items.update({i["photo_id"]: i for i in planned["cannot"]})
        fixes = [items[p] for p in selected if p in items and "repair" in items[p]]
        with ns_db.transaction(conn):
            for photo_id in selected:
                item = items.get(photo_id)
                if item is None or "repair" not in item:
                    reason = item["todo"] if item else ("Nothing to repair: the latest check found it as recorded, "
                                                        "or it has been repaired.")
                    path = item["path"] if item else conn.execute("SELECT dest_path FROM photos WHERE id=?",
                                                                  (photo_id,)).fetchone()[0]
                    store.log_operation(conn, run_id, photo_id, path, None, OPERATION_SKIPPED,
                                        f"Not repaired. {reason}", commit=False)
            runtime.run_progress.add(OPERATION_SKIPPED, len(selected) - len(fixes))
            runtime.run_progress.write(conn)
        if not fixes:
            runtime.logger.info(f"Repair: nothing in the {len(selected):,} selected photo(s) can be fixed here.")
            return RunStatus.COMPLETED

        backup = ns_db.backup_catalog(db_path, backups_dir, base_dir, trigger="pre_action", related_run_id=run_id)
        backups._log_backup(backup, "before repair")
        if backup["outcome"] != "succeeded":
            with ns_db.transaction(conn):
                for item in fixes:
                    store.log_operation(conn, run_id, item["photo_id"], item["from"], item["path"], PhotoStatus.FAILED,
                                        "Not repaired: the catalog backup failed. Nothing was changed.", commit=False)
                runtime.run_progress.add(PhotoStatus.FAILED, len(fixes))
                runtime.run_progress.write(conn)
            runtime.logger.error("Nothing was repaired because the catalog backup failed.")
            return RunStatus.FAILED

        done = failed = 0
        needs_recovery = False
        for index, item in enumerate(fixes):
            if runtime.cancel_requested.is_set():
                remaining = fixes[index:]
                with ns_db.transaction(conn):
                    for left in remaining:
                        store.log_operation(conn, run_id, left["photo_id"], left["from"], left["path"],
                                            OPERATION_CANCELLED, commit=False)
                    runtime.run_progress.add(OPERATION_CANCELLED, len(remaining))
                    runtime.run_progress.write(conn)
                runtime.logger.warning(f"Cancelled: {len(remaining):,} photo(s) left as they were.")
                break
            if runtime.run_progress.due():
                with ns_db.transaction(conn):
                    runtime.run_progress.write(conn)
            sha1 = conn.execute("SELECT sha1_hash FROM photos WHERE id=?", (item["photo_id"],)).fetchone()[0]
            problem = _stale(item, sha1)
            if problem:
                with ns_db.transaction(conn):
                    store.log_operation(conn, run_id, item["photo_id"], item["from"], item["path"], OPERATION_SKIPPED,
                                        f"Not repaired: {problem}. Nothing was changed; check the library again.",
                                        commit=False)
                runtime.run_progress.add(OPERATION_SKIPPED)
                continue
            try:
                if item["repair"] == "copy_back":
                    status, uncertain = _copy(conn, run_id, check_run, item, sha1)
                else:
                    status, uncertain = _move(conn, run_id, check_run, dest_root, item, sha1)
            except (OSError, ValueError, durable.DestinationExistsError) as exc:
                reason = "a file is at its recorded place again" if isinstance(exc, durable.DestinationExistsError) \
                    else str(exc)
                with ns_db.transaction(conn):
                    store.log_operation(conn, run_id, item["photo_id"], item["from"], item["path"], PhotoStatus.FAILED,
                                        f"Not repaired: {reason}. Nothing was changed.", commit=False)
                status, uncertain = PhotoStatus.FAILED, False
            needs_recovery = needs_recovery or uncertain
            if status == OPERATION_REPAIRED:
                done += 1
            else:
                failed += 1
            runtime.run_progress.add(status)

        with ns_db.transaction(conn):
            runtime.run_progress.write(conn)
        runtime.logger.info(f"Repair: {done:,} photo(s) repaired" + (f", {failed:,} failed" if failed else "") + ".")
        return RunStatus.FAILED if needs_recovery else RunStatus.COMPLETED
    finally:
        conn.close()
        backups.backup_after_job(db_path, backups_dir, base_dir, run_id)


def run_repair(args, db_path: Path, base_dir: Path, lock_fd) -> int:
    """--repair-library CHECK_RUN with a selection, as a job (run_maintenance_job)."""
    dest_root = Path(args.dest).resolve()
    from engine import jobs
    return jobs.run_maintenance_job(
        args, db_path, lock_fd, mode="REPAIR", label="Repair", submitted={"check_run": args.repair_library},
        targeted=True, defaults={}, overrides={},
        body=lambda run_id, config: repair(db_path, dest_root, Path(args.backups), base_dir, run_id,
                                           args.repair_library))
