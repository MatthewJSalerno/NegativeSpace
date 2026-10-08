"""Starting, watching and cancelling engine jobs (webui-spec 5.6, 5.7)."""
import errno
import contextlib
import fcntl
import json
import os
import posixpath
import re
import signal
import stat
import subprocess
import threading
import time
import uuid
from typing import Optional

from engine import ns_db
from . import catalog, catalog_backups, outcomes
from .config import ENGINE_CWD, Config

MODES = {"index": None, "copy": "--copy", "move": "--move",
         "reject": "--reject", "return": "--return-to-library"}
# Reject and Return to library act on what the user chose, never on everything.
NEEDS_SELECTION = {"reject", "return"}
# Photo ids are SQLite signed 64-bit integers.
MAX_PHOTO_ID = 2**63 - 1


def validate_request_id(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value)):
        raise JobRefused(400, {"error": "invalid_request", "message": "request_id must contain 1–128 letters, digits, underscores or hyphens."})
    return value
# How long a started engine has to create its run before the start is reported
# as failed. It creates the run right after taking its lock, before any file work.
RUN_APPEAR_SECONDS = 30.0
# What the API waits for a job to stop after SIGTERM when the server shuts down.
# Inside the 300 s stop timeout the README and compose file set: a cancel finishes
# the file being copied, and one large file over a network share can take minutes.
SHUTDOWN_GRACE_SECONDS = 290.0
# How long a check for a running engine waits on another check before concluding a
# job is being started: probes hold the start lock for microseconds, starts for seconds.
START_WAIT_SECONDS = 1.0
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


def validate_request(cfg: Config, mode: str, file_ids=None, source_subdir=None) -> tuple:
    """The engine flags for a job request and its selection (ascending photo ids, or
    None), validated here as well as by the engine (webui-spec 5.6): defence in depth,
    and a clean 400 instead of a failed job. A selection reaches the engine in a file
    (_launch), whatever its size."""
    if not isinstance(mode, str) or mode not in MODES:
        raise JobRefused(400, {"error": "invalid_request", "message": f"Unknown job mode: {mode!r}."})
    if file_ids is not None and source_subdir is not None:
        raise JobRefused(400, {"error": "invalid_request",
                               "message": "Choose photos or a folder, not both."})
    if mode in NEEDS_SELECTION and file_ids is None and source_subdir is None:
        raise JobRefused(400, {"error": "invalid_request",
                               "message": "Choose photos or a folder to act on."})
    flags = [MODES[mode]] if MODES[mode] else []
    selection = None
    if file_ids is not None:
        try:
            selection = ns_db.normalize_selection(file_ids)
        except ns_db.SelectionRefused:
            raise JobRefused(400, {"error": "invalid_request",
                                   "message": "file_ids must be a non-empty list of positive 64-bit integer photo ids."})
    if source_subdir is not None:
        if not isinstance(source_subdir, str) or not source_subdir or "\0" in source_subdir:
            raise JobRefused(400, {"error": "invalid_request", "message": "The folder is empty or invalid."})
        # Spaces are legal filename characters, including an entire component.
        # Match the gallery's literal folder filter; trimming can select a sibling.
        normal = posixpath.normpath(source_subdir)
        if posixpath.isabs(normal) or normal == ".." or normal.startswith("../"):
            raise JobRefused(400, {"error": "invalid_request",
                                   "message": "The folder must be inside the source."})
        flags += ["--source-subdir", normal]
    return flags, selection


class JobRunner:
    """One engine at a time. The engine's own lock is the guarantee; this is the fast
    check and the bookkeeping of the processes this server started."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._start_lock = threading.Lock()
        self._procs = {}                      # run_id -> Popen
        self._previews = threading.BoundedSemaphore(PREVIEW_CONCURRENCY)
        self._backing_up = False
        if self._selections().is_dir():
            with self._selection_lease() as lease:
                if lease is not None:
                    self._cleanup_selections()

    def _selections(self):
        return self.cfg.base / "selections"

    @contextlib.contextmanager
    def _selection_lease(self):
        """Coordinate publication and cleanup across API processes and engine children.

        Never unlink this lock file. Closing releases this process's reference;
        LOCK_UN would also release a surviving child's inherited lock.
        """
        fd = os.open(self.cfg.base / 'selection-start.lock',
                     os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    raise
                yield None
            else:
                yield fd
        finally:
            os.close(fd)

    def _cleanup_selections(self):
        """With the selection lease held, no participating writer or child uses these."""
        for path in self._selections().glob('*'):
            if not re.fullmatch(r'(?:[A-Za-z0-9_-]{1,128}\.ids|\.[A-Za-z0-9_-]{1,128}\.ids\.tmp)', path.name):
                continue
            with contextlib.suppress(FileNotFoundError):
                info = path.lstat()
                if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid():
                    path.unlink()

    # -- The lock -------------------------------------------------------------

    def engine_busy(self) -> bool:
        """Whether an engine holds its lock right now. While this server is starting
        one, the answer is yes without probing: the probe takes the lock for an
        instant, and an engine starting in that instant would refuse to run.
        Another probe holds the start lock too, for microseconds; so a check waits its
        turn, and only a lock held past START_WAIT_SECONDS, which only a start or a
        backup does, means busy. Answering busy at once showed a job that was not
        there whenever two checks overlapped."""
        if not self._start_lock.acquire(timeout=START_WAIT_SECONDS):
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
        run = outcomes.newest_active_run(self.cfg.db_path)
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

    def start(self, mode: str, file_ids=None, source_subdir=None, request_id=None) -> int:
        validate_request_id(request_id)
        flags, selection = validate_request(self.cfg, mode, file_ids, source_subdir)
        status = catalog.status(self.cfg.db_path)
        if status["state"] != "ok":
            raise JobRefused(409, {"error": f"catalog_{status['state']}", "message": status["detail"]})
        if mode != "index" and status["photos"] == 0:
            raise JobRefused(409, {"error": "catalog_empty",
                                   "message": "Run a Scan first - NegativeSpace acts on indexed photos."})
        # No fixed limit: a selection is bounded by the catalog it was chosen from.
        if selection is not None and len(selection) > status["photos"]:
            raise JobRefused(400, {"error": "invalid_request",
                                   "message": "The selection names more photos than the catalog holds."})
        with self._start_lock:
            return self._launch(flags, request_id, selection)

    def review_decision(self, body):
        with self._start_lock:
            if self._probe_lock():
                raise self._busy()
            try:
                result = subprocess.run(self.cfg.engine_argv('--review-decision'), input=json.dumps(body),
                                        text=True, capture_output=True, cwd=ENGINE_CWD, timeout=30)
                answer = json.loads(result.stdout)
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                raise JobRefused(503, {'error': 'review_unavailable',
                    'message': 'The review decision could not be confirmed. Reload the photo before retrying.'}) from exc
            if result.returncode:
                raise JobRefused(409 if result.returncode == 3 else 400, answer)
            return answer

    def repair_similarity(self, scope, photo_id=None, request_id=None):
        validate_request_id(request_id)
        if scope not in ('missing','comparisons') or (photo_id is not None and
                (scope != 'missing' or type(photo_id) is not int or not 1 <= photo_id <= MAX_PHOTO_ID)):
            raise JobRefused(400, {'error':'invalid_request', 'message':'Choose missing hashes or comparisons and a valid optional photo ID.'})
        status = catalog.status(self.cfg.db_path)
        if status['state'] != 'ok':
            raise JobRefused(409, {'error':'catalog_unavailable', 'message':status['detail']})
        flags = ['--repair-similarity',scope]
        if photo_id is not None:
            flags += ['--repair-photo',str(photo_id)]
        with self._start_lock:
            return self._launch(flags,request_id)

    def answer(self, run_id, question, answer, request_id=None):
        validate_request_id(request_id)
        if type(run_id) is not int or not 1 <= run_id <= MAX_PHOTO_ID:
            raise JobRefused(400, {"error": "invalid_request", "message": "The run id must be a positive 64-bit integer."})
        choices = {"source_empty": {"confirm_empty", "retry"},
                   "network_destination": {"copy", "confirm_move"}}
        if not isinstance(question, str) or not isinstance(answer, str) or answer not in choices.get(question, set()):
            raise JobRefused(400, {"error": "invalid_request", "message": "Unknown safety question or answer."})
        with self._start_lock:
            with catalog.connect(self.cfg.db_path) as conn:
                row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
                if row is None:
                    raise JobRefused(409, {"error": "stale_question", "message": "This question is no longer current. Refresh the job status."})
                current = question in outcomes.safety_questions(conn, dict(row))
                if row["source_path"] != str(self.cfg.source.resolve()) or row["dest_path"] != str(self.cfg.dest.resolve()):
                    raise JobRefused(409, {"error": "scope_changed", "message": "The source or destination changed. Start a new job with the intended folders."})
                mode = row["mode"].lower()
                targeting = json.loads(row["file_ids_filter"]) if row["file_ids_filter"] else {}
                if not isinstance(targeting, dict) or set(targeting) - {"selection", "sha256", "source_subdir"}:
                    raise JobRefused(409, {"error": "scope_changed", "message": "This job's scope cannot be retried safely."})
                # The job's own record of what it was asked to act on.
                chosen = [r[0] for r in conn.execute(
                    "SELECT photo_id FROM run_selections WHERE run_id = ? ORDER BY photo_id", (run_id,))] or None
                prior = conn.execute("SELECT submitted_request_json FROM job_requests WHERE run_id=?", (run_id,)).fetchone()
                submitted = (json.loads(prior[0]).get("submitted") or {}) if prior else {}
            if question == "network_destination":
                if mode != "move":
                    raise JobRefused(409, {"error": "stale_question", "message": "Network confirmation applies only to Move."})
                mode = "copy" if answer == "copy" else "move"
            flags, selection = validate_request(self.cfg, mode, chosen, targeting.get("source_subdir"))
            # Carry only explicit answers from the preceding request in this chain.
            # New jobs through /start never inherit permission from an earlier run.
            if answer == "confirm_empty" or submitted.get("confirm_source_empty") is True:
                flags.append("--confirm-source-empty")
            if mode == "move" and (answer == "confirm_move" or submitted.get("confirm_network_destination") is True):
                flags.append("--confirm-network-destination")
            replay = self._replay(flags, request_id, selection)
            if replay is not None:
                return replay
            if not current:
                raise JobRefused(409, {"error": "stale_question", "message": "This question is no longer current. Refresh the job status."})
            return self._launch(flags, request_id, selection)

    def _replay(self, flags, request_id, selection=None):
        if request_id is None:
            return None
        record = outcomes.request_record(self.cfg.db_path, request_id)
        if record is None:
            return None
        def argument(flag):
            return flags[flags.index(flag) + 1] if flag in flags else None
        targeting = ({"selection": len(selection), "sha256": ns_db.selection_digest(selection)}
                     if selection else {"source_subdir": argument("--source-subdir")}
                     if "--source-subdir" in flags else None)
        expected = {"mode": "MOVE" if "--move" in flags else "COPY" if "--copy" in flags else "INDEX",
                    "source": str(self.cfg.source.resolve()), "destination": str(self.cfg.dest.resolve()),
                    "targeting": targeting, "overrides": {},
                    "submitted": {"force_rehash": False, "thumbnails": True, "cache": str(self.cfg.cache.resolve()),
                                  "confirm_source_empty": "--confirm-source-empty" in flags,
                                  "confirm_network_destination": "--confirm-network-destination" in flags}}
        for flag, mode in (("--reject", "REJECT"), ("--return-to-library", "RETURN")):
            if flag in flags:
                expected = {**expected, "mode": mode, "submitted": {}}
        if '--repair-similarity' in flags:
            expected = {'mode':'SIMILARITY', 'source':None, 'destination':None,
                        'targeting':None, 'overrides':{}, 'submitted':{
                            'scope':argument('--repair-similarity'),
                            'photo_id':int(argument('--repair-photo')) if '--repair-photo' in flags else None,
                            'dest':str(self.cfg.dest.resolve())}}
        if record["request"] != expected:
            raise JobRefused(409, {"error": "request_conflict", "message": "This request ID was already used for different input."})
        return record["run_id"]

    def _launch(self, flags, request_id=None, selection=None):
        """Start with the API start lock held; the engine owns the filesystem lock. A
        selection goes to the engine in a file named by the request ID (never by the
        client), removed once the engine has recorded it with the run or stopped."""
        replay = self._replay(flags, request_id, selection)
        if replay is not None:
            return replay
        if self._probe_lock():
            raise self._busy()
        request_id = request_id or uuid.uuid4().hex
        with contextlib.ExitStack() as ownership:
            selection_file, lease = None, None
            try:
                if selection:
                    try:
                        lease = ownership.enter_context(self._selection_lease())
                        if lease is None:
                            raise self._busy()
                        # Reclaim files abandoned since startup, before reusing a request ID.
                        self._cleanup_selections()
                        replay = self._replay(flags, request_id, selection)
                        if replay is not None:
                            return replay
                        selection_file = ns_db.write_selection_file(self._selections(), request_id, selection)
                    except (OSError, ns_db.SelectionRefused) as exc:
                        raise JobRefused(503, {"error": "selection_unavailable",
                            "message": f"The selection could not be prepared: {exc}. "
                                       "This attempt did not start the engine. Check application-data storage "
                                       "and any pending submission before retrying the same request."}) from exc
                    flags = [*flags, "--file-ids-from", str(selection_file)]
                return self._spawn(flags, request_id, selection, selection_lease=lease)
            finally:
                if selection_file is not None:
                    selection_file.unlink(missing_ok=True)

    def _spawn(self, flags, request_id, selection, *, selection_lease=None):
        log = self.cfg.base / "logs" / "engine-console.log"
        proc = None
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "w") as out:
                # The engine releases the inherited lock once it has read its selection.
                proc = subprocess.Popen(self.cfg.engine_argv("--request-id", request_id, *flags), cwd=ENGINE_CWD,
                                        stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                        pass_fds=(() if selection_lease is None else (selection_lease,)),
                                        env=(None if selection_lease is None else
                                             {**os.environ, "NS_SELECTION_LEASE_FD": str(selection_lease)}))
        except OSError as exc:
            if proc is not None:
                raise  # A failure closing the log is not evidence the child never started.
            raise JobRefused(500, {"error": "engine_start_failed",
                "message": f"The engine could not be started: {exc}. "
                           "Check application-data storage and engine permissions, then retry the same request."}) from exc
        deadline = time.monotonic() + RUN_APPEAR_SECONDS
        while True:
            run_id = outcomes.run_for_request(self.cfg.db_path, request_id)
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
        # Another API process or CLI may bind the ID after our initial lookup.
        # The engine refuses mismatched reuse; do not return that other payload's
        # run merely because its ID has appeared in the acceptance table.
        try:
            self._replay(flags, request_id, selection)
        except JobRefused:
            threading.Thread(target=proc.wait, daemon=True).start()
            raise
        self._procs[run_id] = proc
        threading.Thread(target=self._reap, args=(run_id, proc), daemon=True).start()
        return run_id

    def _reap(self, run_id: int, proc: subprocess.Popen):
        proc.wait()
        # Kept briefly so a client polling right after exit still sees the handle.
        time.sleep(2)
        self._procs.pop(run_id, None)

    def _busy(self) -> JobRefused:
        run = outcomes.newest_active_run(self.cfg.db_path)
        active = {k: run[k] for k in ("id", "mode", "started_at")} if run else None
        return JobRefused(409, {"error": "job_already_running", "active_run": active,
                                "message": "A job is already running - wait for it to finish or cancel it."})

    def cancel(self, run_id: int) -> None:
        """SIGTERM, which the engine treats as a cancel: it finishes the file in hand
        and records the rest (webui-spec 4.1). Only a process this server started can
        be signalled; one started before a restart has no handle here."""
        proc = self._procs.get(run_id)
        if proc is None or proc.poll() is not None:
            run = outcomes.get_run(self.cfg.db_path, run_id)
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
            before = catalog_backups.newest_backup_attempt(self.cfg.db_path)
            self._backing_up = True
            try:
                proc = subprocess.run(self.cfg.engine_argv("--backup-now"), cwd=ENGINE_CWD, stdin=subprocess.DEVNULL,
                                      capture_output=True, text=True, timeout=BACKUP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                raise JobRefused(500, {"error": "backup_timeout",
                                       "message": "The backup did not finish in time. Check the backup storage."})
            finally:
                self._backing_up = False
            attempt = catalog_backups.newest_backup_attempt(self.cfg.db_path)
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
            proc = subprocess.run(self.cfg.engine_argv("--preview", photo_id), cwd=ENGINE_CWD, stdin=subprocess.DEVNULL,
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
            # Only the reason, for a person: not the log's time, level and process, the
            # word FATAL, or argparse's "engine: error:".
            reason = line.split("] ", 1)[-1]
            reason = re.sub(r"^\(pid:[^)]*\)\s*", "", reason)
            return re.sub(r"^(FATAL:|\S+: error:)\s*", "", reason).strip()
    return lines[-1].strip() if lines else None
