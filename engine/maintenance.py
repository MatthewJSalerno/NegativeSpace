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
from engine import constants, destinations, fileinfo, jobs, ns_db, runtime, scan, store, thumbnails


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
                        value = fileinfo.compute_phash(str(path))
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
                conn.execute('UPDATE contents SET phash=?,phash_state=? WHERE content_id=? AND digest=?',
                             (phash,state,row['content_id'],row['sha1_hash']))
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


def _check_destination_file(path: str, expected: Optional[tuple], full: bool) -> dict:
    """One destination file for the destination check, in a worker process. Reads only.

    `expected` is (photo_id, sha1, size, mtime) for a catalogued copy, None for a file
    the catalog did not put there. Returns a finding dict (ns_db.record_destination_findings)
    with an extra 'outcome': 'ok', 'missing', 'changed', 'unreadable' or 'unknown'.
    """
    photo_id, sha1, size, mtime = expected or (None, None, None, None)
    finding = {"path": path, "photo_id": photo_id, "expected_sha1": sha1}
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return dict(finding, outcome="missing", kind="missing")
    except OSError as exc:
        kind = "unknown" if expected is None else "unreadable"
        return dict(finding, outcome=kind, kind=kind, detail=f"{type(exc).__name__}: {exc}")
    finding.update(size=st.st_size, mtime=st.st_mtime)
    # Quick trusts an unchanged size and modification time: a copy keeps the source's
    # mtime to the nanosecond, so a match means nothing has rewritten the file since.
    if (expected is not None and not full and size is not None and mtime is not None
            and st.st_size == size and abs(st.st_mtime - mtime) < 1e-6):
        return dict(finding, outcome="ok", kind=None)
    try:
        observed = fileinfo.compute_sha1(path)
    except OSError as exc:
        kind = "unknown" if expected is None else "unreadable"
        return dict(finding, outcome=kind, kind=kind, detail=f"{type(exc).__name__}: {exc}")
    finding["observed_sha1"] = observed
    if expected is None:
        return dict(finding, outcome="unknown", kind="unknown")
    if observed == sha1:
        return dict(finding, outcome="ok", kind=None)
    return dict(finding, outcome="changed", kind="changed")


def check_destination(db_path: Path, dest_root: Path, run_id: int, depth: str, workers: int,
                      extensions: set, log_dir: Path) -> str:
    """The destination check (engine-spec 9.1). Returns the run outcome.

    Answers "is my destination still intact?", which Index cannot: it never reads
    --dest. Every delivered copy the catalog records under `dest_root` is looked up
    directly - never inferred missing from the walk, which can skip an unreadable
    folder - and found ok, missing, changed or unreadable. `quick` trusts an unchanged
    size and mtime and hashes the rest; `full` hashes everything, which also finds
    silent corruption. The walk then finds files the catalog did not put there,
    limited to the run's extensions; they are always hashed, so redundancy something
    outside the engine created shows up grouped by content.

    Read only, and an observation: no file is touched and no photo's status changes.
    What is not intact is stored in destination_findings; intact copies are counted.
    """
    full = depth == "full"
    dest_root = Path(dest_root).resolve()
    expected = {}
    with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
        for photo_id, path, sha1, size, mtime in conn.execute(
                f"SELECT id, dest_path, sha1_hash, file_size, file_mtime FROM photos "
                f"WHERE status IN ({constants.sql_values(constants.ANCHOR_DELIVERED_STATUSES)}) AND dest_path IS NOT NULL "
                f"ORDER BY id"):
            if destinations._is_under(path, dest_root):
                expected.setdefault(path, (photo_id, sha1, size, mtime))

    runtime.run_progress.start("discovering", None)

    def discovered(eligible, excluded):
        runtime.run_progress.set_count("eligible", eligible)
        runtime.run_progress.set_count("excluded", excluded)
        runtime.run_progress.maybe_write_now()
    walk_errors: List[tuple] = []
    # Only the library is walked: folders beside it (Rejects, RAW originals) hold files the
    # engine put there on purpose and are not "files NegativeSpace did not put there".
    library = ns_db.library_root(dest_root)
    walked = scan.discover_source_files(library, extensions, errors=walk_errors, excluded={},
                                   on_directory=discovered) if library.is_dir() else []
    runtime.run_progress.write_now()
    work = [(path, exp) for path, exp in expected.items()]
    work += [(path, None) for path in walked if path not in expected]
    unknown_count = len(work) - len(expected)
    runtime.logger.info(f"Checking the destination ({'every file read in full' if full else 'quick'}): "
                f"{len(expected):,} catalogued cop(ies), {unknown_count:,} file(s) the catalog did not "
                f"put there.")
    if walk_errors:
        runtime.logger.warning(f"{len(walk_errors)} destination folder(s) or file(s) could not be read; files "
                       f"inside them could not be checked for being unknown.")

    runtime.run_progress.start("checking_destination", len(work))
    counts = collections.Counter()
    outcome = RunStatus.COMPLETED
    batch_size = max(workers * 4, 16)
    last_log = time.monotonic()
    with worker_pool.pool(workers, False, str(log_dir)) as executor, \
            contextlib.closing(store.get_db_connection(str(db_path))) as conn:
        for start in range(0, len(work), batch_size):
            if runtime.cancel_requested.is_set():
                runtime.logger.warning(f"Cancellation requested - stopping the destination check after "
                               f"{sum(counts.values()):,} of {len(work):,}. Findings so far are kept.")
                outcome = RunStatus.CANCELLED
                break
            futures = [executor.submit(_check_destination_file, path, exp, full)
                       for path, exp in work[start:start + batch_size]]
            results = list(worker_pool.results(futures))
            if runtime.cancel_requested.is_set():
                outcome = RunStatus.CANCELLED
            with ns_db.transaction(conn):
                ns_db.record_destination_findings(
                    conn, run_id, [{k: v for k, v in r.items() if k != "outcome"} for r in results
                                   if r["kind"] is not None])
                for r in results:
                    counts[r["outcome"]] += 1
                    runtime.run_progress.add(r["outcome"])
                runtime.run_progress.write(conn)
            if time.monotonic() - last_log >= constants.PROGRESS_INTERVAL_SECONDS:
                runtime.logger.info(f"Checking the destination: {sum(counts.values()):,} of {len(work):,}.")
                last_log = time.monotonic()
    runtime.logger.info(f"Destination check: {counts['ok']:,} intact, {counts['missing']:,} missing, "
                f"{counts['changed']:,} changed, {counts['unreadable']:,} unreadable, "
                f"{counts['unknown']:,} not put there by NegativeSpace. Nothing was changed.")
    return outcome


def run_destination_check(args, db_path: Path, log_dir: Path, lock_fd) -> int:
    """--check-destination, as a job (run_maintenance_job)."""
    dest_root = Path(args.dest).resolve()
    return jobs.run_maintenance_job(
        args, db_path, lock_fd, mode="CHECK", label="Destination check",
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
