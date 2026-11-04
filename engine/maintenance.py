"""Maintenance jobs: similarity repair, the destination check and thumbnail rebuilds."""

import collections
import contextlib
import os
import stat
import time
from pathlib import Path
from typing import Optional, List

from engine.ns_db import PhotoStatus, RunStatus, SUPPORTED_EXTENSIONS
from engine import workers as worker_pool
from engine import constants, destinations, fileinfo, jobs, library_check, ns_db, runtime, scan, store, thumbnails


def repair_similarity(db_path: Path, dest_root: Path, scope: str, photo_id=None):
    """Rebuild missing hashes from verified destination originals; never write photos."""
    from engine import ns_similarity_recovery as recovery
    from engine import ns_similarity
    with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
        work = [r for r in recovery.rows(conn, photo_id) if r['kind'] == 'missing_hash'
                and recovery.describe(r)['retryable']
                and (photo_id is not None or recovery.describe(r)['action'] == 'generate')] if scope == 'missing' else []
        runtime.run_progress.start('scanning', len(work))
        for row in work:
            if runtime.cancel_requested.is_set():
                return RunStatus.CANCELLED
            path = Path(row['dest_path'])
            state, phash = 'repair_unreadable', None
            measures = {}
            read_error = None
            try:
                if not path.resolve().is_relative_to(dest_root.resolve()):
                    state = 'repair_outside'
                elif not path.exists():
                    state = 'repair_missing'
                else:
                    before = path.stat()
                    if not stat.S_ISREG(before.st_mode):
                        state = 'repair_unreadable'
                    elif fileinfo.compute_sha1(str(path)) != row['sha1_hash']:
                        state = 'repair_changed'
                    else:
                        value = fileinfo.compute_phash(str(path), measures=measures)
                        after = path.stat()
                        fingerprint = lambda s: (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
                        if (fingerprint(before) != fingerprint(after)
                                or fileinfo.compute_sha1(str(path)) != row['sha1_hash']):
                            state = 'repair_changed'
                        elif ns_similarity.usable(value):
                            phash, state = value.lower(), 'ok'
                        else:
                            state = 'not_supported' if value == 'not_supported' else 'repair_decode'
            except FileNotFoundError:
                state = 'repair_missing'
            except OSError as exc:
                state = 'repair_unreadable'
                read_error = str(exc)
            if runtime.cancel_requested.is_set():
                return RunStatus.CANCELLED
            with ns_db.transaction(conn):
                conn.execute('UPDATE contents SET phash=?,phash_state=?,mean_brightness=?,mean_gradient=? '
                             'WHERE content_id=? AND digest=?',
                             (phash,state,measures.get('mean_brightness') if phash else None,
                              measures.get('mean_gradient') if phash else None,row['content_id'],row['sha1_hash']))
                if phash is not None:
                    conn.execute('UPDATE photos SET phash=? WHERE sha1_hash=?', (phash,row['sha1_hash']))
                if phash is None and runtime.run_progress.run_id is not None:
                    reason = recovery.describe({**row, 'phash_state': state})['message']
                    detail = f"Visual hash recovery failed [{state}]: {reason}"
                    if read_error:
                        detail += f" Read error: {read_error}"
                    # A failed read is an audit result, not a failed transfer or a
                    # change to the photo's delivered status. Keep the file intact.
                    store.log_operation(conn, runtime.run_progress.run_id, row['id'], str(path), str(path),
                                  PhotoStatus.FAILED, detail, commit=False)
                runtime.run_progress.add('made' if phash else 'failed')
                runtime.run_progress.write(conn)
            runtime.logger.info(f"Visual hash recovery: photo #{row['id']}: {state}.")
        runtime.run_progress.start('matching', None)
        def progress(done, total):
            runtime.run_progress.set_total(total)
            runtime.run_progress.set_count('Compared', done)
            if runtime.run_progress.due():
                runtime.run_progress.write_now()
        complete = ns_similarity.refresh(conn, cancelled=runtime.cancel_requested.is_set, progress=progress)
        return RunStatus.COMPLETED if complete else RunStatus.CANCELLED


def run_similarity_repair(args, db_path: Path, lock_fd):
    return jobs.run_maintenance_job(args, db_path, lock_fd, mode='SIMILARITY', label='Similarity recovery',
        submitted={'scope':args.repair_similarity, 'photo_id':args.repair_photo, 'dest':str(Path(args.dest).resolve())},
        defaults={}, overrides={}, reconcile_files=False,
        body=lambda run_id, config: repair_similarity(db_path, Path(args.dest), args.repair_similarity, args.repair_photo))


def _check_destination_file(path: str, expected: Optional[tuple], full: bool, photo_type: bool = True) -> dict:
    """One library file for the check, in a worker process. Reads only.

    `expected` is (photo_id, sha1, size, mtime, phash) for a catalogued copy, None for a
    file the catalog did not put there, which library_check.unknown_file names by its
    content (`photo_type`: its extension is one the run selects). Returns a finding dict
    (ns_db.record_destination_findings) with an extra 'outcome': 'ok', 'missing',
    'changed', 'unreadable' or 'unknown'.
    """
    if expected is None:
        return library_check.unknown_file(path, photo_type)
    photo_id, sha1, size, mtime, phash = expected
    finding = {"path": path, "photo_id": photo_id, "expected_sha1": sha1}
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return dict(finding, outcome="missing", kind="missing")
    except OSError as exc:
        return dict(finding, outcome="unreadable", kind="unreadable", detail=f"{type(exc).__name__}: {exc}")
    finding.update(size=st.st_size, mtime=st.st_mtime)
    # Quick trusts an unchanged size and modification time: a copy keeps the source's
    # mtime to the nanosecond, so a match means nothing has rewritten the file since.
    if (not full and size is not None and mtime is not None
            and st.st_size == size and abs(st.st_mtime - mtime) < 1e-6):
        return dict(finding, outcome="ok", kind=None)
    try:
        observed = fileinfo.compute_sha1(path)
    except OSError as exc:
        return dict(finding, outcome="unreadable", kind="unreadable", detail=f"{type(exc).__name__}: {exc}")
    finding["observed_sha1"] = observed
    if observed == sha1:
        return dict(finding, outcome="ok", kind=None)
    return dict(finding, outcome="changed", kind="changed", look=library_check.look(path, phash))


def check_destination(db_path: Path, dest_root: Path, run_id: int, depth: str, workers: int,
                      extensions: set, log_dir: Path) -> str:
    """Check library (engine-spec 9.1, 9.2). Returns the run outcome.

    Answers "is my library still as recorded?", which Index cannot: it never reads
    --dest. With no library folder it stops, recording no findings: a destination
    that is not connected proves nothing. Every delivered copy the catalog records is
    looked up directly - never inferred missing from the walk, which can skip an
    unreadable folder - and found ok, missing, changed or unreadable. `quick` trusts
    an unchanged size and mtime and hashes the rest; `full` hashes everything, which
    also finds silent corruption. The walk then finds files the catalog did not put
    there and names each by its content (library_check.unknown_file); other programs'
    housekeeping and sidecars beside photos are only counted. Last, it looks for the
    content of each missing photo elsewhere in the library, in Rejects and the source.

    Read only, and an observation: no file is touched and no photo's status changes.
    What is not intact is stored in destination_findings; intact copies are counted.
    """
    full = depth == "full"
    dest_root = Path(dest_root).resolve()
    library = ns_db.library_root(dest_root)
    expected = {}
    with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
        with ns_db.transaction(conn):
            library_check.start(conn, run_id, depth, library)
        if not library.is_dir():
            with ns_db.transaction(conn):
                library_check.stop(conn, run_id, "library_missing")
            runtime.logger.error(f"The library folder isn't there ({library}). Is the destination connected? "
                                 f"Nothing was checked and no findings were recorded.")
            return RunStatus.FAILED
        for photo_id, path, sha1, size, mtime, phash in conn.execute(
                f"SELECT id, dest_path, sha1_hash, file_size, file_mtime, phash FROM photos "
                f"WHERE status IN ({constants.sql_values(constants.ANCHOR_DELIVERED_STATUSES)}) AND dest_path IS NOT NULL "
                f"ORDER BY id"):
            if destinations._is_under(path, dest_root):
                expected.setdefault(path, (photo_id, sha1, size, mtime, phash))

    runtime.run_progress.start("discovering", None)

    def discovered(eligible, excluded):
        runtime.run_progress.set_count("eligible", eligible)
        runtime.run_progress.set_count("excluded", excluded)
        runtime.run_progress.maybe_write_now()
    walk_errors: List[tuple] = []
    # Only the library is walked: folders beside it (Rejects, RAW originals) hold files the
    # engine put there on purpose and are not "files NegativeSpace did not put there".
    photos, others, housekeeping, sidecars = library_check.walk_library(library, extensions, walk_errors,
                                                                       on_directory=discovered)
    runtime.run_progress.write_now()
    work = [(path, exp, True) for path, exp in expected.items()]
    work += [(path, None, True) for path in photos if path not in expected]
    work += [(path, None, False) for path in others if path not in expected]
    unknown_count = len(work) - len(expected)
    runtime.logger.info(f"Checking the library ({'every file read in full' if full else 'quick'}): "
                f"{len(expected):,} catalogued cop(ies), {unknown_count:,} file(s) the catalog did not "
                f"put there, {sum(housekeeping.values()):,} file(s) from other programs, {sidecars:,} sidecar(s).")
    if walk_errors:
        runtime.logger.warning(f"{len(walk_errors)} library folder(s) or file(s) could not be read; files "
                       f"inside them could not be checked for being unknown.")

    runtime.run_progress.start("checking_destination", len(work))
    counts = collections.Counter()
    outcome = RunStatus.COMPLETED
    batch_size = max(workers * 4, 16)
    last_log = time.monotonic()
    present = {}
    with worker_pool.pool(workers, False, str(log_dir)) as executor, \
            contextlib.closing(store.get_db_connection(str(db_path))) as conn:
        with ns_db.transaction(conn):
            library_check.record_counts(conn, run_id, {**housekeeping, **({"sidecars": sidecars} if sidecars else {})})
        for start in range(0, len(work), batch_size):
            if runtime.cancel_requested.is_set():
                runtime.logger.warning(f"Cancellation requested - stopping the library check after "
                               f"{sum(counts.values()):,} of {len(work):,}. Findings so far are kept.")
                outcome = RunStatus.CANCELLED
                break
            futures = [executor.submit(_check_destination_file, path, exp, full, photo_type)
                       for path, exp, photo_type in work[start:start + batch_size]]
            results = list(worker_pool.results(futures))
            if runtime.cancel_requested.is_set():
                outcome = RunStatus.CANCELLED
            for r in results:
                if r["kind"] == "missing":
                    r["gone_folder"] = library_check.gone_folder(r["path"], library, present)
            with ns_db.transaction(conn):
                ns_db.record_destination_findings(
                    conn, run_id, [{k: v for k, v in r.items() if k != "outcome"} for r in results
                                   if r["kind"] is not None])
                for r in results:
                    counts[r["outcome"]] += 1
                    runtime.run_progress.add(r["outcome"])
                runtime.run_progress.write(conn)
            if time.monotonic() - last_log >= constants.PROGRESS_INTERVAL_SECONDS:
                runtime.logger.info(f"Checking the library: {sum(counts.values()):,} of {len(work):,}.")
                last_log = time.monotonic()
        if outcome == RunStatus.COMPLETED:
            rows = ns_db.read_destination_check(conn, run_id)["findings"]
            library_check.locate(conn, rows, ns_db.rejects_root(dest_root), runtime.cancel_requested.is_set)
            with ns_db.transaction(conn):
                conn.executemany("UPDATE destination_findings SET found_in=?, found_path=? WHERE run_id=? AND path=?",
                                 [(f["found_in"], f["found_path"], run_id, f["path"]) for f in rows if f.get("found_in")])
            if runtime.cancel_requested.is_set():
                outcome = RunStatus.CANCELLED
    runtime.logger.info(f"Library check: {counts['ok']:,} intact, {counts['missing']:,} missing, "
                f"{counts['changed']:,} changed, {counts['unreadable']:,} unreadable, "
                f"{counts['unknown']:,} not put there by NegativeSpace. Nothing was changed.")
    return outcome


def run_destination_check(args, db_path: Path, log_dir: Path, lock_fd) -> int:
    """--check-destination, as a job (run_maintenance_job)."""
    dest_root = Path(args.dest).resolve()
    return jobs.run_maintenance_job(
        args, db_path, lock_fd, mode="CHECK", label="Library check",
        submitted={"depth": args.check_destination, "dest": str(dest_root)},
        defaults={"workers": constants.MAX_WORKER_PROCESSES, "exts": sorted(SUPPORTED_EXTENSIONS)},
        overrides={**({"workers": args.workers} if args.workers is not None else {}),
                   **({"exts": sorted(scan.normalize_extensions(args.exts))} if args.exts is not None else {})},
        body=lambda run_id, config: check_destination(db_path, dest_root, run_id, args.check_destination,
                                                      config["workers"], set(config["exts"]), log_dir))


def run_thumbnail_rebuild(args, db_path: Path, log_dir: Path, lock_fd) -> int:
    """--rebuild-thumbnails, as a job (run_maintenance_job)."""
    cache_root = Path(args.cache).resolve()
    return jobs.run_maintenance_job(
        args, db_path, lock_fd, mode="REBUILD", label="Thumbnail rebuild",
        submitted={"scope": args.rebuild_thumbnails, "cache": str(cache_root)},
        defaults={"workers": constants.MAX_WORKER_PROCESSES},
        overrides={"workers": args.workers} if args.workers is not None else {},
        body=lambda run_id, config: thumbnails.rebuild_thumbnails(db_path, cache_root, args.rebuild_thumbnails,
                                                       config["workers"], log_dir))
