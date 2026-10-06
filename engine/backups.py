"""Catalog backups after a job and on request."""

import contextlib
import sqlite3
from pathlib import Path

from engine.ns_db import OPERATION_CANCELLED, OPERATION_SKIPPED
from engine import ns_db, runtime, store


def backup_after_job(db_path: Path, backups_dir: Path, base_dir: Path, run_id: int):
    """One automatic backup after a job that recorded changes, including a failed
    or cancelled one. Skipped and Cancelled rows record that nothing was done, so
    a job holding only those (a repeated Copy, an unchanged Index) gets none:
    otherwise every no-op run would push a meaningful backup out of retention.
    A failed backup is reported beside the job's result and never changes it."""
    try:
        with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
            recorded = conn.execute(
                "SELECT COUNT(*) FROM operations WHERE run_id = ? AND status NOT IN (?, ?)",
                (run_id, OPERATION_SKIPPED, OPERATION_CANCELLED)).fetchone()[0]
        if not recorded:
            runtime.logger.info("No catalog changes recorded by this run; no backup needed.")
            return
        result = ns_db.backup_catalog(db_path, backups_dir, base_dir,
                                      trigger="post_job", related_run_id=run_id)
    except Exception as exc:
        runtime.logger.warning(f"Catalog backup after run #{run_id} could not be attempted: {exc}. "
                       f"The run's own result is unaffected.")
        return
    _log_backup(result, f"after run #{run_id}")


def run_manual_backup(db_path: Path, backups_dir: Path, base_dir: Path, lock_fd) -> int:
    """--backup-now. Exit 0 when a verified backup was written, 1 otherwise."""
    try:
        if not db_path.exists():
            runtime.logger.error(f"FATAL: there is no catalog at {db_path} to back up.")
            return 1
        try:
            result = ns_db.backup_catalog(db_path, backups_dir, base_dir, trigger="manual")
        except (ns_db.SchemaError, sqlite3.DatabaseError) as exc:
            runtime.logger.error(f"FATAL: the catalog cannot be backed up: {exc}")
            return 1
        _log_backup(result, "requested manually")
        return 0 if result["outcome"] == "succeeded" else 1
    finally:
        runtime.release_single_instance_lock(lock_fd)


def _log_backup(result: dict, context: str):
    if result["outcome"] == "succeeded":
        runtime.logger.info(f"Catalog backup {context}: {result['filename']} "
                    f"({result['size'] / 1e6:.1f} MB), verified.")
        if result["pruned"]:
            runtime.logger.info(f"Retention removed {len(result['pruned'])} older automatic backup(s).")
    else:
        runtime.logger.warning(f"Catalog backup {context} FAILED ({result['error_category']}): "
                       f"{result['error_detail']}. Catalog changes since the last successful "
                       f"backup are not backed up. No photo was affected.")
