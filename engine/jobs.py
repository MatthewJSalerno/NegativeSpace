"""Running a job that is not Index, Copy or Move: its run record, lock, reconciliation and backup."""

import contextlib
import json
import signal
import sqlite3
import threading
from pathlib import Path

from engine.ns_db import RunStatus
from engine import constants, ns_db, reconcile, runtime, store, targeting


def run_maintenance_job(args, db_path: Path, lock_fd, *, mode: str, label: str, submitted: dict,
                        defaults: dict, overrides: dict, body, reconcile_files=True, targeted=False) -> int:
    """A job that is not Index/Copy/Move, run like any other: a runs row (with
    --request-id replay and conflict handling), reconciliation first, cancellation,
    live progress, and a settled status. `body(run_id, config)` does the work and
    returns the run outcome. Releases the lock. Exits 0 unless the run Failed.
    `targeted` records the run's source, destination and --file-ids/--source-subdir
    selection as Copy and Move do, for a job that acts on a selection."""
    try:
        try:
            store.init_database(str(db_path))
        except (ns_db.SchemaError, sqlite3.DatabaseError) as exc:
            runtime.logger.error(f"FATAL: catalog initialization failed: {exc}. Nothing was started.")
            return 1
        signal.signal(signal.SIGTERM, runtime._handle_cancel_signal)
        signal.signal(signal.SIGINT, runtime._handle_cancel_signal)
        try:
            where = ((str(Path(args.source).resolve()), str(Path(args.dest).resolve()), args.file_ids,
                      args.source_subdir) if targeted else (None, None, None))
            run_id, created = store.start_run(str(db_path), mode, *where, defaults=defaults,
                                        overrides=overrides, request_id=args.request_id,
                                        submitted=submitted, strict_selection=bool(args.file_ids_from))
        except ns_db.SelectionRefused as exc:
            runtime.logger.error(f"FATAL: {exc}")
            return 1
        except ns_db.RequestConflict:
            runtime.logger.error(f"FATAL: request ID {args.request_id!r} was already used for a different "
                         f"submission. Nothing was started. A new attempt needs a new request ID.")
            return constants.EXIT_REQUEST_CONFLICT
        if not created:
            runtime.logger.warning(f"Request ID {args.request_id!r} was already accepted as run #{run_id}. "
                           f"Nothing was started.")
            return constants.EXIT_REQUEST_ALREADY_ACCEPTED
        args.run_id = run_id
        if targeted and args.file_ids:
            targeting._log_selection(args)
        with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
            config = json.loads(conn.execute(
                "SELECT effective_config_json FROM run_configs WHERE run_id=?", (run_id,)).fetchone()[0])
        runtime.run_progress.bind(str(db_path), run_id)
        cancel_watcher = threading.Thread(target=runtime.watch_for_cancellation, args=(str(db_path), run_id), daemon=True)
        cancel_watcher.start()
        outcome = RunStatus.FAILED
        try:
            if reconcile_files:
                reconcile.reconcile_interrupted_state(db_path, run_id)
            else:
                # Matching recovery must not resume a filesystem mutation.
                with contextlib.closing(store.get_db_connection(str(db_path), synchronous="FULL")) as old_runs:
                    for (old_id,) in old_runs.execute("SELECT id FROM runs WHERE mode='SIMILARITY' AND id!=? AND status IN ('Preparing','Running','Cancelling')", (run_id,)).fetchall():
                        ns_db.transition_run(old_runs, old_id, RunStatus.INTERRUPTED, reconciled_by=run_id)
            with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
                ns_db.transition_run(conn, run_id, RunStatus.RUNNING)
            outcome = body(run_id, config)
        except Exception as exc:
            runtime.logger.error(f"{label} failed: {exc}", exc_info=True)
        finally:
            if runtime.cancel_requested.is_set() and outcome == RunStatus.COMPLETED:
                outcome = RunStatus.CANCELLED
            runtime.run_progress.write_now()
            runtime.await_cancelling_record(cancel_watcher)
            store.finish_run(str(db_path), run_id, outcome)
            runtime.logger.info(f"Run #{run_id} finished with status: {outcome}")
        return 1 if outcome == RunStatus.FAILED else 0
    finally:
        runtime.release_single_instance_lock(lock_fd)
