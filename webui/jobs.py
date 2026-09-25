"""Starting, watching and cancelling engine jobs (webui-spec 5.6, 5.7)."""
import errno
import fcntl
import json
import os
import posixpath
import signal
import subprocess
import threading
import time
import uuid
from typing import Optional

from . import catalog
from .config import Config

MODES = {"index": None, "copy": "--copy", "move": "--move"}
# Each selected id becomes part of the engine's command line, which has a real
# OS length limit; larger selections use a folder (webui-spec 2).
MAX_FILE_IDS = 1000
# How long a started engine has to create its run before the start is reported
# as failed. It creates the run right after taking its lock, before any file work.
RUN_APPEAR_SECONDS = 30.0
# What the API waits for a job to stop after SIGTERM when the server shuts down.
# Inside the 300 s stop timeout the README and compose file set: a cancel finishes
# the file being copied, and one large file over a network share can take minutes.
SHUTDOWN_GRACE_SECONDS = 290.0
# Detail previews are made by the engine on request; bound how many run at once
# when a user pages quickly through photos.
PREVIEW_CONCURRENCY = 2
# A manual backup holds the engine lock; measured at about a second on a 524 MB
# catalog (webui-spec 9), so this bound only catches a hung backup storage.
BACKUP_TIMEOUT_SECONDS = 600


class JobRefused(Exception):
    """A job that was not started, with an HTTP status and a body for the client."""

    def __init__(self, status: int, body: dict):
        super().__init__(body.get("message", body.get("error")))
        self.status, self.body = status, body


def validate_request(cfg: Config, mode: str, file_ids=None, source_subdir=None) -> list:
    """The engine flags for a job request, validated here as well as by the engine
    (webui-spec 5.6): defence in depth, and a clean 400 instead of a failed job."""
    if mode not in MODES:
        raise JobRefused(400, {"error": "invalid_request", "message": f"Unknown job mode: {mode!r}."})
    if file_ids is not None and source_subdir is not None:
        raise JobRefused(400, {"error": "invalid_request",
                               "message": "Choose photos or a folder, not both."})
    flags = [MODES[mode]] if MODES[mode] else []
    if file_ids is not None:
        if (not isinstance(file_ids, list) or not file_ids
                or any(type(i) is not int or i < 1 for i in file_ids)):
            raise JobRefused(400, {"error": "invalid_request",
                                   "message": "file_ids must be a non-empty list of photo ids."})
        ids = sorted(set(file_ids))
        if len(ids) > MAX_FILE_IDS:
            raise JobRefused(400, {"error": "selection_too_large", "limit": MAX_FILE_IDS,
                                   "message": f"{MAX_FILE_IDS:,} file limit for individual selection - "
                                              f"try Folder Selection for larger batches."})
        flags += ["--file-ids", ",".join(str(i) for i in ids)]
    if source_subdir is not None:
        if not isinstance(source_subdir, str) or not source_subdir.strip() or "\0" in source_subdir:
            raise JobRefused(400, {"error": "invalid_request", "message": "The folder is empty or invalid."})
        normal = posixpath.normpath(source_subdir.strip())
        if posixpath.isabs(normal) or normal == ".." or normal.startswith("../"):
            raise JobRefused(400, {"error": "invalid_request",
                                   "message": "The folder must be inside the source."})
        flags += ["--source-subdir", normal]
    return flags


class JobRunner:
    """One engine at a time. The engine's own lock is the guarantee; this is the fast
    check and the bookkeeping of the processes this server started."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._start_lock = threading.Lock()
        self._procs = {}                      # run_id -> Popen
        self._previews = threading.BoundedSemaphore(PREVIEW_CONCURRENCY)
        self._backing_up = False

    # -- The lock -------------------------------------------------------------

    def engine_busy(self) -> bool:
        """Whether an engine holds its lock right now. While this server is starting
        one, the answer is yes without probing: the probe takes the lock for an
        instant, and an engine starting in that instant would refuse to run."""
        if not self._start_lock.acquire(blocking=False):
            return True
        try:
            return self._probe_lock()
        finally:
            self._start_lock.release()

    def _probe_lock(self) -> bool:
        """The engine's lock, probed without waiting. The runs table alone cannot say
        whether an engine runs: a crash leaves a run recorded active with no engine
        behind it (webui-spec 5.7)."""
        try:
            fd = os.open(self.cfg.lock_path, os.O_RDONLY)
        except FileNotFoundError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                return True
            raise
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        finally:
            os.close(fd)

    def active(self) -> Optional[dict]:
        """The job to show as running, if any. A run recorded active while no engine
        holds the lock is shown as interrupted and awaiting reconciliation; the API
        never writes that - the next engine run does (webui-spec 5.7)."""
        busy = self.engine_busy()
        run = catalog.newest_active_run(self.cfg.db_path)
        if run is None:
            # An engine is starting, backing up, or was run by hand outside this server.
            return {"id": None, "mode": "backup" if self._backing_up else None, "status": "Preparing", "unrecorded": True} if busy else None
        if busy:
            run["cancellable"] = run["id"] in self._procs and self._procs[run["id"]].poll() is None
            return run
        run["presented_status"] = "Interrupted"
        run["awaiting_reconciliation"] = True
        run["cancellable"] = False
        return run

    # -- Starting and stopping ------------------------------------------------

    def start(self, mode: str, file_ids=None, source_subdir=None) -> int:
        flags = validate_request(self.cfg, mode, file_ids, source_subdir)
        status = catalog.status(self.cfg.db_path)
        if status["state"] != "ok":
            raise JobRefused(409, {"error": f"catalog_{status['state']}", "message": status["detail"]})
        if mode != "index" and status["photos"] == 0:
            raise JobRefused(409, {"error": "catalog_empty",
                                   "message": "Run a Scan first - NegativeSpace acts on indexed photos."})
        with self._start_lock:
            if self._probe_lock():
                raise self._busy()
            request_id = uuid.uuid4().hex
            log = self.cfg.base / "logs" / "engine-console.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "w") as out:
                proc = subprocess.Popen(self.cfg.engine_argv("--request-id", request_id, *flags),
                                        stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + RUN_APPEAR_SECONDS
            while True:
                run_id = catalog.run_for_request(self.cfg.db_path, request_id)
                if run_id is not None:
                    break
                if proc.poll() is not None:
                    reason = _last_error(log)
                    if "another NegativeSpace engine process is already running" in (reason or ""):
                        raise self._busy()
                    raise JobRefused(409 if proc.returncode == 1 else 500,
                                     {"error": "engine_refused", "message": reason or
                                      f"The engine stopped before starting (exit {proc.returncode})."})
                if time.monotonic() > deadline:
                    proc.terminate()
                    raise JobRefused(500, {"error": "engine_start_timeout",
                                           "message": "The engine did not start the job in time."})
                time.sleep(0.05)
            self._procs[run_id] = proc
            threading.Thread(target=self._reap, args=(run_id, proc), daemon=True).start()
            return run_id

    def _reap(self, run_id: int, proc: subprocess.Popen):
        proc.wait()
        # Kept briefly so a client polling right after exit still sees the handle.
        time.sleep(2)
        self._procs.pop(run_id, None)

    def _busy(self) -> JobRefused:
        run = catalog.newest_active_run(self.cfg.db_path)
        active = {k: run[k] for k in ("id", "mode", "started_at")} if run else None
        return JobRefused(409, {"error": "job_already_running", "active_run": active,
                                "message": "A job is already running - wait for it to finish or cancel it."})

    def cancel(self, run_id: int) -> None:
        """SIGTERM, which the engine treats as a cancel: it finishes the file in hand
        and records the rest (webui-spec 4.1). Only a process this server started can
        be signalled; one started before a restart has no handle here."""
        proc = self._procs.get(run_id)
        if proc is None or proc.poll() is not None:
            run = catalog.get_run(self.cfg.db_path, run_id)
            if run is None:
                raise JobRefused(404, {"error": "unknown_run", "message": "No such job."})
            if run["status"] not in catalog.ns_db.ACTIVE_RUN_STATUSES:
                raise JobRefused(409, {"error": "not_running", "message": "That job has already finished."})
            raise JobRefused(409, {"error": "not_cancellable",
                                   "message": "This job was started before the web server last restarted, "
                                              "so it cannot be cancelled from here. Stopping the container "
                                              "cancels it."})
        proc.send_signal(signal.SIGTERM)

    def shutdown(self):
        """On server shutdown (docker stop), cancel any running job and wait for it to
        settle, so it ends Cancelled rather than killed and Interrupted."""
        running = [p for p in self._procs.values() if p.poll() is None]
        for proc in running:
            proc.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + SHUTDOWN_GRACE_SECONDS
        for proc in running:
            try:
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass

    # -- Catalog backups ------------------------------------------------------

    def backup_now(self) -> dict:
        """--backup-now, waited for (webui-spec 9). Refused while a job runs, like
        every write to the catalog: the engine refuses too, under its lock. Returns
        the attempt the engine recorded, succeeded or failed."""
        status = catalog.status(self.cfg.db_path)
        if status["state"] != "ok":
            raise JobRefused(409, {"error": f"catalog_{status['state']}", "message": status["detail"]})
        with self._start_lock:
            if self._probe_lock():
                raise self._busy()
            before = catalog.newest_backup_attempt(self.cfg.db_path)
            self._backing_up = True
            try:
                proc = subprocess.run(self.cfg.engine_argv("--backup-now"), stdin=subprocess.DEVNULL,
                                      capture_output=True, text=True, timeout=BACKUP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                raise JobRefused(500, {"error": "backup_timeout",
                                       "message": "The backup did not finish in time. Check the backup storage."})
            finally:
                self._backing_up = False
            attempt = catalog.newest_backup_attempt(self.cfg.db_path)
        if attempt is None or (before is not None and attempt["attempt_id"] == before["attempt_id"]):
            output = (proc.stderr + proc.stdout)
            if "another NegativeSpace engine process is already running" in output:
                raise self._busy()
            reason = next((l.split("] ", 1)[-1].strip() for l in reversed(output.splitlines())
                           if "FATAL" in l or "error:" in l), None)
            raise JobRefused(500, {"error": "engine_refused", "message": reason or
                                   f"The engine stopped before backing up (exit {proc.returncode})."})
        return attempt

    # -- Detail previews ------------------------------------------------------

    def preview(self, photo_id: int) -> dict:
        """The engine's --preview answer (engine-spec 4.1): it takes no lock, so a
        photo can be opened while a job runs."""
        with self._previews:
            proc = subprocess.run(self.cfg.engine_argv("--preview", photo_id), stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=120)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        try:
            return json.loads(lines[-1])
        except (IndexError, ValueError):
            return {"photo_id": photo_id, "availability": "unavailable", "failure_category": "engine_error",
                    "failure_detail": (proc.stderr or proc.stdout).strip()[-500:] or
                                      f"The engine answered nothing (exit {proc.returncode})."}


def _last_error(log_path) -> Optional[str]:
    """The engine's own reason for refusing to start, from its console output."""
    try:
        lines = log_path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if "FATAL" in line or "error:" in line:
            return line.split("] ", 1)[-1].strip()
    return lines[-1].strip() if lines else None
