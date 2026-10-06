"""What a run shares: results, the log, cancellation, progress and the single-instance lock."""

import collections
import contextlib
import fcntl
import logging
import logging.handlers
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from engine.ns_db import RunStatus
from engine import constants, ns_db, store


# --- Data Models ---
@dataclass
class ProcessingResult:
    """Container for data gathered by the Producer process."""
    file_path: str
    sha1_hash: str
    phash: str
    metadata: dict
    status: str
    dest_path: str
    run_id: int
    has_name_collision: bool = False
    collision_group: Optional[int] = None
    is_master: bool = False
    error_message: Optional[str] = None
    file_size: Optional[int] = None
    file_mtime: Optional[float] = None
    birthtime: Optional[float] = None
    observed_at: Optional[str] = None
    thumbnail: Optional["ThumbnailResult"] = None


@dataclass
class ThumbnailResult:
    """What one thumbnail attempt produced, carried back from the worker process.

    `width`/`height` are the SOURCE photo's dimensions, not the thumbnail's:
    they describe content and are recorded on `contents`. They are populated
    even on some failures, since the header can be readable when the pixel data
    is not.
    """
    availability: str                       # 'present' or 'failed'
    cache_filename: Optional[str] = None    # relative to the cache root
    bytes: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    failure_category: Optional[str] = None
    failure_detail: Optional[str] = None
    reused: bool = False                    # an existing cache entry, not a new render


# --- Producer-Consumer Queue ---
result_queue = queue.Queue(maxsize=constants.DB_QUEUE_SIZE)


# --- Logging Initialization ---
# The log rotates only at startup, in the process holding the single-instance
# lock (rotate_log_if_large), never by size mid-write: every worker process
# holds the same file open, and a rotation by one of them would leave the rest
# writing into the renamed file. One run's log is therefore never split, and
# the total is bounded by these plus one run's output.
LOG_ROTATE_BYTES = 50 * 1024 * 1024
LOG_BACKUP_COUNT = 5


def rotate_log_if_large():
    """Rotates organizer.log once it exceeds LOG_ROTATE_BYTES. Call only while holding the lock."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            try:
                if os.path.getsize(handler.baseFilename) > LOG_ROTATE_BYTES:
                    handler.doRollover()
            except OSError as e:
                logger.warning(f"Could not rotate {handler.baseFilename}: {e}")


def configure_logging(log_dir: Path, console: bool = True):
    """
    Points logging at the console and <base>/logs/organizer.log.

    Called in the main process AND once per worker process (via
    _init_worker_process), because worker log records must not depend on
    inheriting the parent's handlers across a fork — see that function for
    why. basicConfig() is a no-op when the root logger already has handlers,
    so the fork case keeps exactly what it inherited and only a genuinely
    unconfigured process (spawn/forkserver) sets up its own.

    The process id is in the format for the same reason: worker records
    otherwise all claim to be "MainThread" and there is no way to tell which
    process emitted which line.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "organizer.log"

    # Route warnings.warn() through logging so they reach organizer.log.
    # Without this they go straight to stderr and never touch a handler, so
    # "Truncated File Read" and rawpy's OpenMP warning would reach the console
    # while the log file recorded nothing — the log would look clean precisely
    # where something was wrong. These matter: a truncated TIFF names a file
    # worth investigating.
    logging.captureWarnings(True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] (pid:%(process)d/%(threadName)s) %(message)s',
        handlers=([logging.StreamHandler(sys.stdout)] if console else []) + [
            # maxBytes=0: never rotates on write; see rotate_log_if_large.
            logging.handlers.RotatingFileHandler(
                log_file, mode="a", maxBytes=0, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
            )
        ]
    )


logger = logging.getLogger("NegativeSpace")

# --- Cancellation Support ---
# Set by a SIGTERM/SIGINT handler registered in main(). Checked between
# files in the Move/Copy loop — never mid-file — so a cancellation always
# lets the file currently being copy-verified finish cleanly rather than
# risking a partial/corrupt state for that one file.
cancel_requested = threading.Event()


def _handle_cancel_signal(signum, frame):
    logger.warning(f"Received signal {signum} — finishing current file, then cancelling the rest of this run.")
    cancel_requested.set()


class RunProgress:
    """The drawer's live progress for the current run (webui-spec 4.1), kept in memory
    and written to run_progress about once a second.

    Counts are added where each outcome is decided, not re-derived from the operations
    log: unchanged files write no operation, and recovery rows written during a scan
    are run-level issues the drawer keeps separate (webui-spec 5.5). `done` is the sum
    of the counts. Unbound (no run), every call is a no-op, so in-process callers and
    tests need no setup. Thread-safe: the scan's writer thread adds, the main thread
    starts phases.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.bind(None, None)

    def bind(self, db_path, run_id):
        with self._lock:
            self.db_path, self.run_id = db_path, run_id
            self.phase, self.seq, self.total, self.counts = None, 0, None, collections.Counter()
            self.started_at, self._dirty, self._written_at = None, False, 0.0

    def start(self, phase: str, total: Optional[int]):
        """Enters a phase and records it at once, so the drawer names it before any
        file finishes."""
        if self.run_id is None:
            return
        with self._lock:
            self.seq += 1
            self.phase, self.total, self.counts = phase, total, collections.Counter()
            self.started_at, self._dirty = ns_db.utc_now(), True
        self.write_now()

    def set_total(self, total: int):
        with self._lock:
            self.total, self._dirty = total, True

    def add(self, outcome: str, n: int = 1):
        if self.run_id is None or self.phase is None or n <= 0:
            return
        with self._lock:
            self.counts[outcome] += n
            self._dirty = True

    def set_count(self, outcome: str, n: int):
        """For a running tally owned elsewhere, such as files found by the walk."""
        if self.run_id is None or self.phase is None:
            return
        with self._lock:
            self.counts[outcome] = n
            self._dirty = True

    def due(self) -> bool:
        return (self.run_id is not None and self._dirty
                and time.monotonic() - self._written_at >= constants.PROGRESS_SNAPSHOT_SECONDS)

    def write(self, conn):
        """Writes the snapshot into the caller's open transaction; the caller commits."""
        if self.run_id is None or self.phase is None:
            return
        with self._lock:
            snapshot = dict(phase=self.phase, seq=self.seq, total=self.total,
                            counts=dict(self.counts), started_at=self.started_at)
            self._dirty, self._written_at = False, time.monotonic()
        ns_db.write_progress(conn, self.run_id, **snapshot)

    def write_now(self):
        """On its own connection. Never raises: progress is a display, and failing to
        show it must not fail the job."""
        if self.run_id is None or self.phase is None:
            return
        try:
            with contextlib.closing(store.get_db_connection(self.db_path)) as conn, ns_db.transaction(conn):
                self.write(conn)
        except Exception as exc:
            logger.warning(f"Could not record job progress: {exc}")

    def maybe_write_now(self):
        if self.due():
            self.write_now()


run_progress = RunProgress()


def watch_for_cancellation(db_path: str, run_id: int):
    """Records Cancelling as soon as a cancel arrives, so a reader sees the request
    was accepted while the current file finishes. A thread rather than the signal
    handler: a handler runs between arbitrary bytecodes of the main thread, possibly
    inside one of its transactions. Losing this write loses only the interim state;
    the terminal status is written by the run itself either way."""
    cancel_requested.wait()
    try:
        with contextlib.closing(store.get_db_connection(db_path)) as conn:
            if ns_db.transition_run(conn, run_id, RunStatus.CANCELLING):
                logger.info(f"Run #{run_id} is Cancelling.")
    except Exception as exc:
        logger.warning(f"Could not record run #{run_id} as Cancelling: {exc}")


def await_cancelling_record(watcher: threading.Thread):
    """Before a cancelled run settles, lets the watcher's Cancelling write land.
    Without this the two race: a run whose current file finished quickly could
    settle first, and its history would skip Cancelling. Bounded, because the
    write itself is bounded by the busy timeout; a watcher still stuck after
    that only loses the interim state, never the terminal one."""
    if cancel_requested.is_set():
        watcher.join(timeout=10)


# --- Progress in the log ---
def format_duration(seconds: float) -> str:
    """Compact human duration: 45s, 12m 30s, 1h 05m."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


def log_scan_progress(scanned: int, total: int, started_at: float,
                      window_files: int, window_bytes: int, window_seconds: float,
                      label: str = "Progress"):
    """
    Reports progress as RECENT rate plus THROUGHPUT, not a cumulative file count.

    Files differ enormously in cost — in one measured library RAW was 13% of
    the files but 50% of the bytes, roughly 21 MB against 3 MB — so:

    - A cumulative average decays misleadingly. Indexing RAW first, it fell
      from "34 files/sec" to "7 files/sec" over five minutes while the true
      rate was flat at 5.05 the entire time: it looks like degradation and
      is not.
    - A file count cannot distinguish "saturated link" from "broken". At 5.05
      files/sec the engine was moving ~101 MB/s, which is 1GbE at line rate —
      recognisable as physics rather than a bug only if throughput is on
      screen.

    The ETA uses the recent rate rather than the average, so it responds when
    the workload changes character instead of averaging RAW and JPEG together.
    """
    elapsed = time.monotonic() - started_at
    overall_rate = scanned / elapsed if elapsed > 0 else 0
    recent_rate = (window_files / window_seconds) if window_seconds > 0 else overall_rate
    recent_mbps = (window_bytes / window_seconds / 1e6) if window_seconds > 0 else 0.0
    remaining = (total - scanned) / recent_rate if recent_rate > 0 else 0
    pct = (scanned / total * 100) if total else 100.0
    logger.info(
        f"{label}: {scanned:,} of {total:,} files ({pct:.1f}%) — "
        f"{recent_rate:.1f} files/sec, {recent_mbps:.0f} MB/s — "
        f"~{format_duration(remaining)} left at this rate "
        f"(overall avg {overall_rate:.1f} files/sec)."
    )


# --- Single-Instance Enforcement ---
def acquire_single_instance_lock(base_dir: Path):
    """
    Acquires an exclusive, non-blocking OS-level lock (docs/engine-spec.md
    §4.1/§7) so at most one engine process ever runs against a given
    --base at a time — Index, Move, and Copy alike, since a rescan racing
    a physical operation on the same database is exactly as unsafe as two
    physical operations racing each other.

    Returns the open file descriptor (caller must keep a reference to it
    for the lock's lifetime — closing it releases the lock) on success, or
    None if another process already holds it.

    Deliberately a flock, not a PID-file-existence check or a DB-row flag:
    the lock is tied to the holding process's open file descriptor, not to
    the file's mere presence on disk, so it is released automatically by
    the kernel on ANY exit path — normal completion, an exception, or an
    uncatchable SIGKILL — with no manual cleanup possible or needed. This
    was verified directly: hard-killing a lock-holding process left the
    lock file sitting on disk looking exactly like a "stale" lock, but a
    fresh process was able to re-acquire it instantly, no waiting, no
    error. A container being force-stopped (`docker stop` timing out into
    SIGKILL) cannot leave this lock in a state requiring manual deletion.

    Caveat: flock reliability is weaker over NFS depending on lockd/statd
    configuration. Not a concern for a local disk or standard Docker
    volume backing --base, but worth a second look if --base is ever
    NFS-mounted.
    """
    lock_path = base_dir / constants.LOCK_FILENAME
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os.close(fd)
        return None
    # Diagnostic content only — purely informational for a human inspecting
    # the file later, has no bearing on the lock's actual semantics (which
    # are entirely kernel-side, keyed off the open file descriptor above).
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"PID {os.getpid()} — held since {datetime.now().isoformat()}\n".encode())
    except OSError:
        pass
    return fd


def release_single_instance_lock(lock_fd):
    """
    Best-effort explicit release for a clean, immediate unlock on normal
    completion. Not required for correctness — the OS releases the lock
    automatically the moment this process's file descriptors close, on
    every exit path including a crash — but tidier for anything chaining
    multiple engine invocations back-to-back in quick succession.
    """
    if lock_fd is None:
        return
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    except OSError:
        pass
