"""Jobs as the screens show them: a run and its derived outcome (webui-spec 5.5), safety questions and request records."""

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Optional

from engine import ns_db
from engine.ns_db import (PhotoStatus, RunStatus, OPERATION_SKIPPED, OPERATION_CANCELLED, OPERATION_RENAMED, OPERATION_RETURNED)
from . import catalog


# --- Runs and their derived outcome (webui-spec 5.5) -------------------------

# Per phase: which progress outcomes are the work the user asked for having
# happened, which are failures, and which are deliberate non-actions.
_SUCCESS = {"indexed", "duplicates", PhotoStatus.COPIED, PhotoStatus.COMPLETED,
            PhotoStatus.FOUND_AT_DESTINATION, PhotoStatus.REMOVED_DUPLICATE, "made", "ok", "Compared", OPERATION_RENAMED,
            PhotoStatus.REJECTED, PhotoStatus.REJECTED_COPIED, OPERATION_RETURNED}
_FAILURE = {"failed", PhotoStatus.FAILED, "missing", "changed", "unreadable"}
_SKIPPED = {"unchanged", OPERATION_SKIPPED, "already", "kept", "Already_Gone", "unknown"}
_REQUESTED_PHASES = {"INDEX": ("scanning",), "COPY": ("scanning", "transferring"),
                     "MOVE": ("scanning", "transferring", "removing_duplicates"),
                     "SIMILARITY": ("scanning", "matching"), "REBUILD": ("rebuilding_thumbnails",), "CHECK": ("checking_destination",),
                     "REJECT": ("transferring",), "RETURN": ("transferring",)}
_TERMINAL_WINS = {RunStatus.CANCELLED: "cancelled", RunStatus.INTERRUPTED: "interrupted",
                  RunStatus.FAILED: "stopped"}


# Why a photo was skipped, by the start of the reason the engine recorded. The engine
# writes these sentences (engine/transfer.py: _duplicate_skip_reason and the Copy/Move loop);
# tests/webui_api_test.py runs real jobs so a reworded reason fails there, not here.
_SKIP_REASONS = (("Duplicate", "duplicate"), ("Already copied", "already_copied"),
                 ("Already rejected", "already_rejected"), ("Already in Rejects", "already_in_rejects"),
                 ("Not organized yet", "not_organized"), ("A copy of another photo", "copy_follows_original"),
                 ("Already in the library", "already_in_library"), ("Not in Rejects", "not_in_rejects"),
                 ("Rejects has been emptied", "rejects_emptied"),
                 ("Not attempted: the destination is a network share", "network_share_unconfirmed"),
                 ("Not attempted: the source folder is empty", "source_looked_empty"))


def _skip_reason(message: Optional[str]) -> str:
    if message and message.startswith("Duplicate") and "not part of this selection" in message:
        return "duplicate_original_not_selected"
    for prefix, reason in _SKIP_REASONS:
        if message and message.startswith(prefix):
            return reason
    return "other"


def _outcome(conn, run: dict, progress: list) -> dict:
    """A run's result as the user should read it, not its lifecycle status: a run
    where every file failed still ends Completed.

    Requested work comes from the run's progress counts, which exclude recovery of
    earlier work and run-level issues by construction (engine-spec 4.3). For a Copy or
    Move the transfer phases are the requested work, plus prerequisite scan failures
    that prevented a photo from reaching those phases. Successful scans are not
    deliveries and must not count the same photo twice.
    """
    phases = {p["phase"]: p for p in progress}
    wanted = _REQUESTED_PHASES.get(run["mode"], ())
    main = [phases[name] for name in wanted if name in phases and
            (run["mode"] in ("INDEX", "REBUILD", "CHECK", "SIMILARITY") or name != "scanning")]
    counts = {}
    for p in main:
        for key, n in p["counts"].items():
            counts[key] = counts.get(key, 0) + n
    scan_failed = 0
    if run["mode"] in ("COPY", "MOVE"):
        # The engine excludes failed scan results from both transfer and duplicate
        # removal candidates. These are disjoint failed requests, not extra work.
        scan_failed = phases.get("scanning", {}).get("counts", {}).get("failed", 0)
        if scan_failed:
            counts["failed"] = counts.get("failed", 0) + scan_failed
    # In a Move, Copied means the original could not be deleted: not the Move asked for,
    # and not a failure either. Counted apart, with its reasons.
    # A rejected photo whose original could not be deleted is the same, its copy in Rejects.
    copied_only = (counts.get(PhotoStatus.COPIED, 0) + counts.get(PhotoStatus.REJECTED_COPIED, 0)
                   if run["mode"] == "MOVE" else 0)
    succeeded = sum(n for k, n in counts.items() if k in _SUCCESS) - copied_only
    failed = sum(n for k, n in counts.items() if k in _FAILURE)
    skipped = sum(n for k, n in counts.items() if k in _SKIPPED)
    cancelled = counts.get(OPERATION_CANCELLED, 0)
    issues = conn.execute(
        "SELECT COUNT(*) FROM operations WHERE run_id = ? AND photo_id IS NULL AND status = ? "
        "AND reconciles_operation_id IS NULL", (run["id"], PhotoStatus.FAILED)).fetchone()[0]
    recovered = conn.execute("SELECT COUNT(*) FROM operations WHERE run_id = ? AND "
                             "reconciles_operation_id IS NOT NULL", (run["id"],)).fetchone()[0]
    skip_reasons = {}
    for (message,) in conn.execute("SELECT error_message FROM operations WHERE run_id = ? AND status = ? "
                                   "AND reconciles_operation_id IS NULL", (run["id"], OPERATION_SKIPPED)):
        reason = _skip_reason(message)
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    # Why the run's requested work failed, grouped by reason, for the banner's hover.
    failure_reasons = {}
    for (message,) in conn.execute("SELECT error_message FROM operations WHERE run_id = ? AND status = ? "
                                   "AND reconciles_operation_id IS NULL", (run["id"], PhotoStatus.FAILED)):
        reason = catalog.failure_reason(message) or "No reason recorded"
        failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
    kept_reasons = {}
    for (message,) in conn.execute("SELECT error_message FROM operations WHERE run_id = ? AND status IN (?, ?) "
                                   "AND reconciles_operation_id IS NULL AND error_message LIKE ?",
                                   (run["id"], PhotoStatus.COPIED, PhotoStatus.REJECTED_COPIED, catalog._KEPT_LIKE)):
        reason = catalog.kept_reason(message)
        kept_reasons[reason] = kept_reasons.get(reason, 0) + 1
    if run["status"] in ns_db.ACTIVE_RUN_STATUSES:
        verdict = "running"
    elif run["status"] in _TERMINAL_WINS:
        verdict = _TERMINAL_WINS[run["status"]]
    elif copied_only and not failed and not issues:
        verdict = "originals_kept"
    elif succeeded and not failed and not issues:
        verdict = "success"
    # A job that ran to its end never reads "failed" (webui-spec 5.5): with some work done,
    # or some found to need none, it finished with failures; with nothing but failures,
    # it finished and nothing succeeded. Only a job an error stopped is "stopped".
    elif (failed or issues) and (succeeded or copied_only or skipped):
        verdict = "partial"
    elif failed or issues:
        verdict = "none_succeeded"
    else:
        verdict = "no_change"
    total = sum(p["total"] or 0 for p in main) if main and all(p["total"] is not None for p in main) else None
    if total is not None:
        total += scan_failed
    return {"verdict": verdict, "succeeded": succeeded, "failed": failed, "skipped": skipped,
            "cancelled": cancelled, "run_level_issues": issues, "recovered_earlier_work": recovered,
            "copied_only": copied_only, "skip_reasons": skip_reasons, "failure_reasons": failure_reasons,
            "kept_reasons": kept_reasons,
            "total": total, "counts": counts}


def safety_questions(conn, run) -> list:
    """Only the latest settled request can be answered; use its recorded refusal."""
    if run["status"] in ns_db.ACTIVE_RUN_STATUSES or run["id"] != conn.execute("SELECT MAX(id) FROM runs").fetchone()[0]:
        return []
    open_categories = {r[0] for r in conn.execute(
        "SELECT category FROM attention_issues WHERE resolved_at IS NULL "
        "AND category IN ('source_root_empty','network_destination_unconfirmed')")}
    if not open_categories:
        return []
    kinds = {r[0] for r in conn.execute(
        "SELECT json_extract(e.detail_json, '$.kind') FROM operation_events e "
        "JOIN operations o ON o.id=e.operation_id WHERE o.run_id=? AND o.photo_id IS NULL AND e.step='intent'",
        (run["id"],))}
    network_refused = "network_destination_unconfirmed" in open_categories and conn.execute(
        "SELECT 1 FROM operations WHERE run_id=? AND status='Skipped' "
        "AND error_message LIKE 'Not attempted: the destination is a network share%' LIMIT 1",
        (run["id"],)).fetchone() is not None
    questions = []
    if "source_root_empty" in kinds and "source_root_empty" in open_categories:
        questions.append("source_empty")
    if ("network_destination" in kinds or network_refused) and "network_destination_unconfirmed" in open_categories:
        questions.append("network_destination")
    return questions


def _run_dict(conn, row) -> dict:
    run = dict(row)
    run["targeting"] = json.loads(run.pop("file_ids_filter")) if run.get("file_ids_filter") else None
    run["progress"] = ns_db.read_progress(conn, run["id"])
    run["outcome"] = _outcome(conn, run, run["progress"])
    run["questions"] = safety_questions(conn, run)
    return run


_RUN_COLUMNS = "id, mode, status, started_at, ended_at, file_ids_filter, reconciled_by_run_id"


def get_run(db_path: Path, run_id: int) -> Optional[dict]:
    with catalog.connect(db_path) as conn:
        row = conn.execute(f"SELECT {_RUN_COLUMNS} FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run_dict(conn, row) if row else None


def newest_active_run(db_path: Path) -> Optional[dict]:
    """The newest run recorded Preparing, Running or Cancelling - which may be a run
    whose engine died; the caller decides that from the lock (webui-spec 5.7)."""
    try:
        with catalog.connect(db_path) as conn:
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM runs WHERE status IN "
                f"({ns_db.sql_values(ns_db.ACTIVE_RUN_STATUSES)}) ORDER BY id DESC LIMIT 1").fetchone()
            return _run_dict(conn, row) if row else None
    except catalog.CatalogUnavailable:
        return None


def last_run(db_path: Path) -> Optional[dict]:
    try:
        with catalog.connect(db_path) as conn:
            row = conn.execute(f"SELECT {_RUN_COLUMNS} FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            return _run_dict(conn, row) if row else None
    except catalog.CatalogUnavailable:
        return None


def request_record(db_path: Path, request_id: str):
    """Exact durable acceptance; a missing row is unknown, never proof of refusal."""
    if not db_path.exists():
        return None
    with catalog.connect(db_path) as conn:
        row = conn.execute("SELECT run_id,submitted_request_json FROM job_requests WHERE request_id=?", (request_id,)).fetchone()
        return {"run_id": row[0], "request": json.loads(row[1])} if row else None


def run_for_request(db_path: Path, request_id: str) -> Optional[int]:
    """The run an engine created for a request ID, once it has (engine-spec 4.1)."""
    if not db_path.exists():
        return None
    try:
        with contextlib.closing(ns_db.connect(db_path)) as conn:
            row = conn.execute("SELECT run_id FROM job_requests WHERE request_id = ?", (request_id,)).fetchone()
            return row[0] if row else None
    except sqlite3.Error:
        return None
