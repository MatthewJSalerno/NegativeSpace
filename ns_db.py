"""Engine-owned catalog schema and shared persistence primitives.

No photo filesystem operations live here. Callers own/close connections; initialization
is explicit, and settings access never silently creates a catalog. The transfer tables
(photos, runs, operations) sit alongside the file-identity and lineage records.
"""
import contextlib
import errno
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import zstandard

SCHEMA_VERSION = 7

class PhotoStatus:
    """State of one source file in the catalog. One row per source_path."""
    PENDING = "Pending"                       # catalogued, not yet acted on
    PROCESSING = "Processing"                 # durable crash-recovery marker; see _run_move_or_copy
    COMPLETED = "Completed"                   # --move finished: copied, verified, source deleted
    COPIED = "Copied"                         # --copy finished: copied, verified, source kept
    FAILED = "Failed"                          # unreadable, vanished, or the write failed
    DUPLICATE = "Duplicate"                   # identical SHA-1 to another row holding an anchor status
    REMOVED_DUPLICATE = "Removed_Duplicate"   # duplicate whose source was deleted against a verified copy
    FOUND_AT_DESTINATION = "Found_At_Destination"  # source gone, exact content observed on the
                                              # destination; recorded from observation, no action taken


class RunStatus:
    """Lifecycle of one engine invocation. Says whether the process ran to its end,
    not whether the work succeeded: a Completed run can hold every file Failed."""
    PREPARING = "Preparing"                   # accepted; reconciling earlier work before any file work
    RUNNING = "Running"                       # doing the requested file work
    CANCELLING = "Cancelling"                 # cancel received; current work is stopping safely
    COMPLETED = "Completed"                   # ran to its end
    CANCELLED = "Cancelled"                   # cancellation stopped work that remained
    FAILED = "Failed"                         # a job-level error prevented normal completion
    INTERRUPTED = "Interrupted"               # died without settling; marked by the next run's startup


# 'Cancelled' appears in the audit log but never on a photo: work cancelled
# before it started leaves the photo row Pending, so the file is picked up
# again by a re-run. The operations row records that the run reached it and
# stopped.
OPERATION_CANCELLED = "Cancelled"

# 'Skipped' is also an outcome, never a photo state: the run reached a
# selected photo and deliberately did nothing to it — a duplicate whose
# original carries its content — and records why, so that every selected
# photo ends a run with an outcome rather than silence.
OPERATION_SKIPPED = "Skipped"

PHOTO_STATUSES = (
    PhotoStatus.PENDING, PhotoStatus.PROCESSING, PhotoStatus.COMPLETED,
    PhotoStatus.COPIED, PhotoStatus.FAILED, PhotoStatus.DUPLICATE,
    PhotoStatus.REMOVED_DUPLICATE, PhotoStatus.FOUND_AT_DESTINATION,
)
OPERATION_STATUSES = PHOTO_STATUSES + (OPERATION_CANCELLED, OPERATION_SKIPPED)
RUN_STATUSES = (
    RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.CANCELLING, RunStatus.COMPLETED,
    RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.INTERRUPTED,
)
# A run in one of these may still own the active-operation slot. Only a process
# holding the engine lock can tell a live one from a dead one.
ACTIVE_RUN_STATUSES = (RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.CANCELLING)
# Allowed moves, keyed by the state being left. Terminal states have none.
# Cancelling may still end Completed: a job that finished before cancellation
# took effect reports what actually happened. Preparing never ends Completed,
# because no requested work has run. Interrupted is written only by another
# run's reconciliation, never by the run itself.
RUN_TRANSITIONS = {
    RunStatus.PREPARING: {RunStatus.RUNNING, RunStatus.CANCELLING, RunStatus.CANCELLED,
                          RunStatus.FAILED, RunStatus.INTERRUPTED},
    RunStatus.RUNNING: {RunStatus.CANCELLING, RunStatus.COMPLETED, RunStatus.CANCELLED,
                        RunStatus.FAILED, RunStatus.INTERRUPTED},
    RunStatus.CANCELLING: {RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED,
                           RunStatus.INTERRUPTED},
}


# Extensions scanned by default. A missing entry is worse than a failure: the
# file is not indexed, not counted, not reported — it is simply invisible, and
# you find out when it is still sitting in the source folder after an organize
# pass. So every spelling of a format is listed ('.tif' and '.tiff'; '.jpg',
# '.jpeg', '.jpe' and '.jfif').
# Formats that need rawpy/LibRaw to decode. PIL cannot open these at all, so
# compute_phash() routes them to the RAW branch; a format that reached PIL
# instead would always fail its perceptual hash.
RAW_EXTENSIONS = {
    '.raw', '.dng',           # generic / Adobe
    '.cr2', '.cr3', '.crw',   # Canon
    '.nef', '.nrw',           # Nikon
    '.arw', '.srf', '.sr2',   # Sony
    '.raf',                   # Fujifilm
    '.orf',                   # Olympus
    '.rw2',                   # Panasonic
    '.pef', '.ptx',           # Pentax
    '.srw',                   # Samsung
    '.erf',                   # Epson
    '.3fr', '.fff',           # Hasselblad
    '.iiq',                   # Phase One
    '.mos',                   # Leaf
    '.mrw',                   # Minolta
    '.x3f',                   # Sigma
}

# Everything PIL can open directly.
RASTER_EXTENSIONS = {
    '.jpg', '.jpeg', '.jpe', '.jfif', '.png', '.gif', '.bmp', '.webp',
    '.tif', '.tiff', '.heic', '.heif', '.avif',
}

# Derived, never hand-maintained: a RAW format in SUPPORTED_EXTENSIONS but not
# RAW_EXTENSIONS would be discovered by the scan, handed to PIL, and silently
# store "error" as the perceptual hash of every file of that type.
SUPPORTED_EXTENSIONS = RASTER_EXTENSIONS | RAW_EXTENSIONS


def extension_support(extension):
    """What the engine does with files of this extension, for Settings (the API's
    validate-extension) and the run log. Informative, never blocking: a user may
    select any extension (webui-spec 3.2).

    Returns {'extension', 'supported', 'warning'}. `supported` means the engine reads
    the format as a photo: it decodes it for the perceptual hash and the thumbnail, and
    ExifTool reads its metadata. An unsupported extension still gets catalogued, and
    Copy and Move still carry its files into the destination, so the warning says so.
    """
    ext = str(extension).strip().lower()
    ext = ext if ext.startswith(".") else "." + ext
    if ext in SUPPORTED_EXTENSIONS:
        return {"extension": ext, "supported": True, "warning": None}
    return {"extension": ext, "supported": False,
            "warning": (f"NegativeSpace cannot read {ext} files as photos. They would still be "
                        f"catalogued, and Copy and Move would carry them into the destination, "
                        f"usually under Undated/<year> by modification time, with no thumbnail "
                        f"and no similarity matching.")}


def sql_values(values):
    if any(not value.replace("_", "").isalnum() for value in values):
        raise ValueError("invalid status constant")
    return ", ".join("'" + value + "'" for value in values)

def _create_legacy_tables(conn):
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT UNIQUE,
            dest_path TEXT,
            sha1_hash TEXT,
            phash TEXT,
            collision_group INTEGER,
            is_master BOOLEAN DEFAULT 0,
            status TEXT,
            metadata_json TEXT,
            has_name_collision BOOLEAN DEFAULT 0,
            file_size INTEGER,
            file_mtime REAL,
            CHECK (status IS NULL OR status IN ({sql_values(PHOTO_STATUSES)}))
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            source_path TEXT,
            dest_path TEXT,
            file_ids_filter TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL,
            -- The run whose startup found this one dead. ended_at stays NULL
            -- then: the moment of death is unknown, and the reconciler's
            -- start is when it was noticed, not when it ended.
            reconciled_by_run_id INTEGER REFERENCES runs(id),
            CHECK (status IN ({sql_values(RUN_STATUSES)}))
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            photo_id INTEGER,
            original_filename TEXT,
            source_path TEXT,
            dest_path TEXT,
            status TEXT NOT NULL,
            error_message TEXT,
            has_name_collision BOOLEAN DEFAULT 0,
            timestamp TEXT NOT NULL,
            sha1_hash TEXT,
            reconciles_operation_id INTEGER REFERENCES operations(id),
            CHECK (status IN ({sql_values(OPERATION_STATUSES)})),
            FOREIGN KEY(run_id) REFERENCES runs(id),
            FOREIGN KEY(photo_id) REFERENCES photos(id)
        )
    """)


    # Without these, the per-file duplicate check below (one lookup for EVERY
    # file scanned) degrades into a full table scan of a table that is itself
    # growing with every file — quadratic over the size of the library. The
    # status index does the same job for the Pending/Duplicate sweeps, and
    # operations(run_id) is what the web UI's per-job history view will page over.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_photos_sha1 ON photos(sha1_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_photos_status ON photos(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_operations_run ON operations(run_id)")
    # operations is append-only and grows with every file x every run, so
    # the web UI's per-photo history panel would scan the whole audit log
    # without this.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_operations_photo ON operations(photo_id)")
    # "Everything that ever happened to this content" — across its duplicates
    # and across catalog rebuilds, where photo_id does not survive.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_operations_sha1 ON operations(sha1_hash)")
    # Change detection on re-index: partition_unchanged() looks up every
    # candidate by source_path and compares the recorded size/mtime, so the
    # index has to cover all three columns or the lookup pays a row fetch
    # per file.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_photos_source_stat "
        "ON photos(source_path, file_size, file_mtime)"
    )
    # The match gallery groups photos by perceptual hash on every view,
    # and any "does this image already exist here" question joins on phash.
    # Unindexed, each of those is a full scan of the whole library.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_photos_phash ON photos(phash)")




class SchemaError(RuntimeError):
    pass


class RevisionConflict(RuntimeError):
    pass


class RequestConflict(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def connect(db_path, synchronous="NORMAL", *, timeout=5.0, create=False):
    """Existing catalogs only by default; WAL configured at explicit initialization."""
    if synchronous not in ("NORMAL", "FULL"):
        raise ValueError(f"unsupported synchronous level: {synchronous!r}")
    if not 0 <= timeout <= 60:
        raise ValueError("timeout must be between 0 and 60 seconds")
    uri = Path(db_path).absolute().as_uri() + ("?mode=rwc" if create else "?mode=rw")
    conn = sqlite3.connect(uri, uri=True, timeout=timeout)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA synchronous={synchronous}")
        conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        return conn
    except BaseException:
        conn.close()
        raise


@contextlib.contextmanager
def transaction(conn):
    """One outcome unit: caller must not swallow failures or commit within this block."""
    if conn.in_transaction:
        raise RuntimeError("transaction requires an idle connection")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


FOUNDATION_DDL = (
    f"CREATE TABLE catalog_schema (version INTEGER NOT NULL CHECK(version={SCHEMA_VERSION}))",
    f"INSERT INTO catalog_schema VALUES ({SCHEMA_VERSION})",
    """CREATE TABLE files (
        file_id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_run_id INTEGER NOT NULL REFERENCES runs(id),
        created_at TEXT NOT NULL)""",
    """CREATE TABLE file_origins (
        file_id INTEGER PRIMARY KEY REFERENCES files(file_id),
        origin_file_id INTEGER REFERENCES files(file_id),
        kind TEXT NOT NULL CHECK(kind IN ('indexed','copy','observed_destination')))""",
    """CREATE TABLE file_states (
        file_id INTEGER PRIMARY KEY REFERENCES files(file_id),
        current_path TEXT NOT NULL,
        location_role TEXT NOT NULL CHECK(location_role IN ('source','destination')),
        presence_state TEXT NOT NULL CHECK(presence_state IN ('present','removed','missing')),
        sha1_hash TEXT, revision INTEGER NOT NULL DEFAULT 0)""",
    "CREATE UNIQUE INDEX idx_present_destination ON file_states(current_path) WHERE location_role='destination' AND presence_state='present'",
    """CREATE TABLE photo_files (
        photo_id INTEGER PRIMARY KEY REFERENCES photos(id),
        file_id INTEGER NOT NULL UNIQUE REFERENCES files(file_id),
        revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0))""",
    """CREATE TABLE source_snapshots (
        file_id INTEGER PRIMARY KEY REFERENCES files(file_id),
        run_id INTEGER NOT NULL REFERENCES runs(id), source_path TEXT NOT NULL,
        sha1_hash TEXT, file_size INTEGER, file_mtime REAL, birthtime REAL,
        metadata_json TEXT NOT NULL, observed_at TEXT NOT NULL,
        error_message TEXT)""",
    """CREATE TABLE file_observations (
        observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL REFERENCES files(file_id),
        run_id INTEGER NOT NULL REFERENCES runs(id), source_path TEXT NOT NULL,
        sha1_hash TEXT, file_size INTEGER, file_mtime REAL, birthtime REAL,
        metadata_json TEXT NOT NULL, observed_at TEXT NOT NULL,
        error_message TEXT)""",
    """CREATE TABLE operation_files (
        operation_id INTEGER NOT NULL REFERENCES operations(id),
        file_id INTEGER NOT NULL REFERENCES files(file_id),
        role TEXT NOT NULL CHECK(role IN ('source','destination','retained_copy')), PRIMARY KEY(operation_id,file_id,role))""",
    """CREATE TABLE settings (
        key TEXT PRIMARY KEY CHECK(key IN ('workers','exts','backup_retention')),
        value_json TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
        updated_at TEXT NOT NULL)""",
    """CREATE TABLE run_configs (
        run_id INTEGER PRIMARY KEY REFERENCES runs(id),
        effective_config_json TEXT NOT NULL)""",
    """CREATE TABLE job_requests (
        request_id TEXT PRIMARY KEY, run_id INTEGER NOT NULL UNIQUE REFERENCES runs(id),
        submitted_request_json TEXT NOT NULL)""",
    # Shared content identity. Similarity pairs and the thumbnail cache both key
    # on content rather than on a file, so identical copies are compared and
    # rendered once. Defined now; nothing populates it until those steps land.
    """CREATE TABLE contents (
        content_id INTEGER PRIMARY KEY AUTOINCREMENT,
        hash_algorithm TEXT NOT NULL, digest TEXT NOT NULL,
        phash TEXT, phash_state TEXT, width INTEGER, height INTEGER,
        UNIQUE(hash_algorithm, digest))""",
    # Append-only step outcomes for one operation. A terminal event and the
    # current-state update commit together; an interrupted operation has intent
    # recorded with no terminal event, which is how recovery finds it.
    """CREATE TABLE operation_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_id INTEGER NOT NULL REFERENCES operations(id),
        timestamp TEXT NOT NULL, step TEXT NOT NULL, outcome TEXT NOT NULL,
        detail_json TEXT)""",
    # What recovery OBSERVED, kept separate from what the engine DID. An
    # unreadable location is not an absent one, and neither is a mutation.
    """CREATE TABLE operation_evidence (
        evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_id INTEGER NOT NULL REFERENCES operations(id),
        file_id INTEGER REFERENCES files(file_id),
        observed_at TEXT NOT NULL,
        location_role TEXT NOT NULL CHECK(location_role IN ('source','destination','partial')),
        observed_path TEXT NOT NULL, observation_kind TEXT NOT NULL,
        observed_content_id INTEGER REFERENCES contents(content_id),
        result TEXT NOT NULL CHECK(result IN ('present','absent','unreadable','match','mismatch')),
        details_json TEXT)""",
    # Deliberately mutable: an issue is resolved by evidence, not deleted.
    """CREATE TABLE attention_issues (
        issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_id INTEGER NOT NULL REFERENCES operations(id),
        file_id INTEGER REFERENCES files(file_id),
        category TEXT NOT NULL, summary TEXT NOT NULL, opened_at TEXT NOT NULL,
        resolved_at TEXT, resolution_event_id INTEGER REFERENCES operation_events(event_id))""",
    """CREATE TABLE attention_evidence (
        issue_id INTEGER NOT NULL REFERENCES attention_issues(issue_id),
        evidence_id INTEGER NOT NULL REFERENCES operation_evidence(evidence_id),
        PRIMARY KEY(issue_id, evidence_id))""",
    """CREATE TABLE file_changes (
        change_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL REFERENCES operation_events(event_id),
        file_id INTEGER NOT NULL REFERENCES files(file_id),
        before_content_id INTEGER REFERENCES contents(content_id),
        after_content_id INTEGER REFERENCES contents(content_id),
        before_path TEXT, after_path TEXT,
        before_values_json TEXT, after_values_json TEXT)""",
    # One row per unordered pair; the CHECK is what prevents a reversed duplicate.
    """CREATE TABLE content_similarity (
        low_content_id INTEGER NOT NULL REFERENCES contents(content_id),
        high_content_id INTEGER NOT NULL REFERENCES contents(content_id),
        distance INTEGER NOT NULL, computed_at TEXT NOT NULL,
        PRIMARY KEY(low_content_id, high_content_id),
        CHECK(low_content_id < high_content_id))""",
    # Cache state, not lineage: a thumbnail failure is a diagnostic, and
    # generation never modifies the photo.
    # Keyed on (content_id, size): a photo has a grid thumbnail and may also have a
    # larger detail preview, and the two are managed independently - previews are
    # generated lazily and can be cleared without touching the grid. `bytes` is
    # recorded so per-size totals are a SUM rather than a walk of the cache tree.
    """CREATE TABLE thumbnail_cache (
        content_id INTEGER NOT NULL REFERENCES contents(content_id),
        size INTEGER NOT NULL CHECK(size > 0),
        cache_filename TEXT, bytes INTEGER,
        availability TEXT NOT NULL CHECK(availability IN ('present','absent','failed')),
        attempted_file_id INTEGER REFERENCES files(file_id), observed_path TEXT,
        failure_category TEXT, failure_detail TEXT, updated_at TEXT NOT NULL,
        PRIMARY KEY(content_id, size))""",
    "CREATE INDEX idx_thumbnail_size ON thumbnail_cache(size, availability)",
    # An attempt is history; an artifact's availability is current observed state.
    # What a full Index walk found, by file type (webui-spec 5.1). Measured counts
    # only: a scoped run walks nothing and has no row. Excluded files are untouched
    # and are not failures. `unreadable` counts folders and entries the walk could
    # not examine; any at all makes the counts partial.
    """CREATE TABLE run_discovery (
        run_id INTEGER PRIMARY KEY REFERENCES runs(id),
        files_found INTEGER NOT NULL, eligible INTEGER NOT NULL, excluded INTEGER NOT NULL,
        excluded_by_extension_json TEXT NOT NULL, unreadable INTEGER NOT NULL,
        CHECK(files_found = eligible + excluded))""",
    # outcome is NULL only while an attempt runs; one found NULL under the
    # engine lock was interrupted.
    """CREATE TABLE backup_attempts (
        attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
        trigger_kind TEXT NOT NULL CHECK(trigger_kind IN ('manual','post_job','pre_action')),
        related_run_id INTEGER REFERENCES runs(id),
        started_at TEXT NOT NULL, ended_at TEXT,
        outcome TEXT CHECK(outcome IN ('succeeded','failed','interrupted')),
        error_category TEXT, error_detail TEXT)""",
    # 'pruned' is the retention limit removing the file; 'missing' is the file
    # gone for a reason the application did not record.
    """CREATE TABLE backup_artifacts (
        artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id INTEGER NOT NULL UNIQUE REFERENCES backup_attempts(attempt_id),
        relative_filename TEXT NOT NULL, size INTEGER NOT NULL,
        compression_format TEXT, created_at TEXT NOT NULL,
        availability TEXT NOT NULL CHECK(availability IN ('present','missing','unknown','pruned')),
        last_checked_at TEXT, pruned_at TEXT)""",
    "CREATE INDEX idx_evidence_operation ON operation_evidence(operation_id,evidence_id)",
    "CREATE INDEX idx_events_operation ON operation_events(operation_id,event_id)",
    "CREATE INDEX idx_open_attention ON attention_issues(file_id) WHERE resolved_at IS NULL",
    "CREATE INDEX idx_observations_file ON file_observations(file_id,observation_id)",
    "CREATE INDEX idx_lineage_file ON operation_files(file_id,operation_id)",
)


def initialize(db_path):
    """Initialize a fresh development catalog; fail closed on unknown existing schema."""
    with contextlib.closing(connect(db_path, synchronous="FULL", create=True)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables:
            require_schema(conn)
            return
        conn.execute("PRAGMA journal_mode=WAL")
        with transaction(conn):
            # Another initializer may have won the write lock after our first read.
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_schema'").fetchone():
                require_schema(conn)
                return
            _create_legacy_tables(conn)
            for statement in FOUNDATION_DDL:
                conn.execute(statement)
            for table in ('files', 'file_origins', 'source_snapshots', 'file_observations', 'operation_files',
                          'run_configs', 'job_requests', 'operation_events', 'operation_evidence',
                          'file_changes', 'attention_evidence'):
                for action in ('UPDATE', 'DELETE'):
                    conn.execute(f"CREATE TRIGGER immutable_{table}_{action} BEFORE {action} ON {table} "
                                 "BEGIN SELECT RAISE(ABORT, 'immutable lineage/configuration'); END")


def require_schema(conn):
    try:
        rows = conn.execute("SELECT version FROM catalog_schema").fetchall()
        if rows != [(SCHEMA_VERSION,)]:
            raise SchemaError("Unsupported catalog schema version")
        required = {'photos','runs','operations','files','photo_files','source_snapshots',
                    'file_observations','operation_files','settings','run_configs','job_requests',
                    'file_origins','file_states','contents','operation_events','operation_evidence',
                    'attention_issues','attention_evidence','file_changes','content_similarity',
                    'thumbnail_cache','backup_attempts','backup_artifacts','run_discovery'}
        present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= present:
            raise SchemaError("Incomplete catalog schema")
    except sqlite3.DatabaseError as exc:
        raise SchemaError("Catalog has no compatible schema marker; preserve it and use a new development catalog") from exc


def validate_settings(values):
    if not isinstance(values, dict):
        raise ValueError("settings must be an object")
    normalized = {}
    for key, value in values.items():
        if key == 'workers':
            if type(value) is not int or value < 1:
                raise ValueError("workers must be a positive integer")
        elif key == 'backup_retention':
            if type(value) is not int or value < 1:
                raise ValueError("backup_retention must be a positive integer")
        elif key == 'exts':
            if not isinstance(value, list) or not value or any(
                not isinstance(v, str) or not re.fullmatch(r'\.?[A-Za-z0-9]+', v) for v in value
            ):
                raise ValueError("exts must be a nonempty list of file extensions")
            value = sorted({'.' + v.lower().lstrip('.') for v in value})
        else:
            raise ValueError(f"unsupported setting: {key}")
        normalized[key] = value
    return normalized


def read_settings(conn):
    require_schema(conn)
    return {key: {'value': json.loads(value), 'revision': revision}
            for key, value, revision in conn.execute("SELECT key,value_json,revision FROM settings")}


def save_settings(conn, values, *, expected_revisions):
    """Scoped API entry point. Atomic patch with optimistic revision checks."""
    values = validate_settings(values)
    if set(expected_revisions) != set(values) or any(type(v) is not int or v < 0 for v in expected_revisions.values()):
        raise ValueError("supply a nonnegative expected revision for every changed setting")
    require_schema(conn)
    with transaction(conn):
        for key, value in values.items():
            row = conn.execute("SELECT revision FROM settings WHERE key=?", (key,)).fetchone()
            revision = row[0] if row else 0
            if revision != expected_revisions[key]:
                raise RevisionConflict(f"setting changed: {key}")
            conn.execute("INSERT INTO settings VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                         "value_json=excluded.value_json,revision=excluded.revision,updated_at=excluded.updated_at",
                         (key, _json(value), revision + 1, utc_now()))
    return read_settings(conn)


def create_run(conn, *, mode, source, destination, targeting=None, request_id=None,
               submitted=None, defaults=None, overrides=None):
    """Engine-owned acceptance primitive. Caller owns the file-operation lock.

    Same request/payload returns (existing_id, False), without consulting changed
    settings. This does not launch workers or permit the API to bypass engine locking.
    """
    require_schema(conn)
    if request_id is not None and (not isinstance(request_id, str) or not request_id or len(request_id) > 256):
        raise ValueError("invalid request ID")
    payload = _json({'mode': mode, 'source': source, 'destination': destination,
                     'targeting': targeting, 'submitted': submitted, 'overrides': overrides or {}})
    with transaction(conn):
        if request_id is not None:
            row = conn.execute("SELECT run_id,submitted_request_json FROM job_requests WHERE request_id=?", (request_id,)).fetchone()
            if row:
                if row[1] != payload:
                    raise RequestConflict("request ID was already used for different input")
                return row[0], False
        config = dict(defaults or {})
        config.update({k: v['value'] for k,v in read_settings(conn).items()})
        config.update(overrides or {})
        cur = conn.execute("INSERT INTO runs(mode,source_path,dest_path,file_ids_filter,started_at,status) VALUES(?,?,?,?,?,?)",
                           (mode, source, destination, _json(targeting) if targeting else None, utc_now(), RunStatus.PREPARING))
        run_id = cur.lastrowid
        conn.execute("INSERT INTO run_configs VALUES(?,?)", (run_id, _json(config)))
        if request_id is not None:
            conn.execute("INSERT INTO job_requests VALUES(?,?,?)", (request_id, run_id, payload))
        return run_id, True


def transition_run(conn, run_id, to, *, reconciled_by=None):
    """Moves a run to `to` if RUN_TRANSITIONS allows it from its current state.

    Returns False, changing nothing, when the run has already left every state `to`
    may follow: a cancellation arriving after the run settled is a no-op, not an
    error. Callers that require the move (the run settling itself) check the result.
    A terminal state stamps ended_at, except Interrupted, whose end is unknown.
    """
    if to == RunStatus.INTERRUPTED and reconciled_by is None:
        raise ValueError("Interrupted is recorded by the run that found it")
    sources = [s for s, targets in RUN_TRANSITIONS.items() if to in targets]
    # Every state reachable here except these three ends the run.
    ended_at = None if to in (RunStatus.RUNNING, RunStatus.CANCELLING, RunStatus.INTERRUPTED) else utc_now()
    with transaction(conn):
        cur = conn.execute(
            f"UPDATE runs SET status=?, ended_at=COALESCE(?, ended_at), "
            f"reconciled_by_run_id=COALESCE(?, reconciled_by_run_id) "
            f"WHERE id=? AND status IN ({','.join('?' * len(sources))})",
            (to, ended_at, reconciled_by, run_id, *sources))
        return cur.rowcount == 1


def record_source_observation(conn, *, photo_id, run_id, source_path, sha1_hash,
                              file_size, file_mtime, birthtime, metadata, error,
                              prior_status=None, observed_at=None):
    """Participates in caller's scan savepoint, never commits independently."""
    if not conn.in_transaction:
        raise RuntimeError("source observation requires caller transaction")
    row = conn.execute("SELECT file_id FROM photo_files WHERE photo_id=?", (photo_id,)).fetchone()
    # A known consumed source returning is a new arrival, not a new version of the
    # file now at destination. Ordinary rescans retain the binding.
    new = row is None or prior_status in (PhotoStatus.COMPLETED, PhotoStatus.REMOVED_DUPLICATE)
    now = observed_at or utc_now()
    if new:
        file_id = conn.execute("INSERT INTO files(created_run_id,created_at) VALUES(?,?)", (run_id, now)).lastrowid
        conn.execute("INSERT INTO photo_files VALUES(?,?,0) ON CONFLICT(photo_id) DO UPDATE SET "
                     "file_id=excluded.file_id,revision=photo_files.revision+1", (photo_id,file_id))
    else:
        file_id = row[0]
        conn.execute("UPDATE photo_files SET revision=revision+1 WHERE photo_id=?", (photo_id,))
    values = (file_id,run_id,source_path,sha1_hash or None,file_size,file_mtime,birthtime,_json(metadata),now,error)
    if new:
        conn.execute("INSERT INTO file_origins VALUES(?,?,'indexed')", (file_id,file_id))
        conn.execute("INSERT INTO file_states VALUES(?,?,'source','present',?,0)",
                     (file_id,source_path,sha1_hash or None))
    else:
        conn.execute("UPDATE file_states SET current_path=?,sha1_hash=?,revision=revision+1 WHERE file_id=? AND location_role='source'",
                     (source_path,sha1_hash or None,file_id))
    if new:
        conn.execute("INSERT INTO source_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)", values)
    conn.execute("INSERT INTO file_observations(file_id,run_id,source_path,sha1_hash,file_size,file_mtime,birthtime,metadata_json,observed_at,error_message) VALUES(?,?,?,?,?,?,?,?,?,?)", values)
    return file_id


def link_operation(conn, operation_id, photo_id):
    conn.execute("INSERT INTO operation_files SELECT ?,file_id,'source' FROM photo_files WHERE photo_id=?", (operation_id,photo_id))


def advance_revision(conn, photo_id, expected_revision):
    """Guard a state/history update inside the caller's outcome transaction."""
    if not conn.in_transaction:
        raise RuntimeError("revision changes require an outcome transaction")
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("expected revision must be a nonnegative integer")
    cur = conn.execute("UPDATE photo_files SET revision=revision+1 WHERE photo_id=? AND revision=?",
                       (photo_id, expected_revision))
    if cur.rowcount != 1:
        raise RevisionConflict("photo changed or is no longer available; refresh before applying")


def record_delivery(conn, *, operation_id, photo_id, run_id, destination,
                    source_removed, created, sha1_hash=None):
    """Record a successful verified transfer in its outcome transaction.

    No filesystem inference or commits. Failed/interrupted operations are left for
    evidence-based recovery. Uncatalogued retained output has unknown creation origin.
    """
    if not conn.in_transaction:
        raise RuntimeError("delivery requires an outcome transaction")
    binding = conn.execute("SELECT file_id FROM photo_files WHERE photo_id=?", (photo_id,)).fetchone()
    if binding is None:
        raise SchemaError("Transfer source has no indexed file identity")
    source_id = binding[0]
    row = conn.execute("SELECT file_id FROM file_states WHERE current_path=? AND location_role='destination' AND presence_state='present'",
                       (destination,)).fetchone()
    retained_id = row[0] if row else None
    if created and retained_id is not None:
        # A fresh publication proves the previously recorded occupant was absent.
        # Keep its identity/history rather than assigning the new bytes to it.
        conn.execute("UPDATE file_states SET presence_state='missing',revision=revision+1 WHERE file_id=?", (retained_id,))
        retained_id = None
    if retained_id is None and created and source_removed:
        retained_id = source_id
        conn.execute("UPDATE file_states SET current_path=?,location_role='destination',presence_state='present',sha1_hash=?,revision=revision+1 WHERE file_id=?",
                     (destination,sha1_hash,source_id))
    elif retained_id is None:
        retained_id = conn.execute("INSERT INTO files(created_run_id,created_at) VALUES(?,?)", (run_id,utc_now())).lastrowid
        origin = conn.execute("SELECT origin_file_id FROM file_origins WHERE file_id=?", (source_id,)).fetchone()[0] if created else None
        conn.execute("INSERT INTO file_origins VALUES(?,?,?)", (retained_id,origin,'copy' if created else 'observed_destination'))
        conn.execute("INSERT INTO file_states VALUES(?,?,'destination','present',?,0)", (retained_id,destination,sha1_hash))
    if retained_id != source_id and source_removed:
        conn.execute("UPDATE file_states SET presence_state='removed',revision=revision+1 WHERE file_id=?", (source_id,))
    role = 'destination' if created else 'retained_copy'
    conn.execute("INSERT INTO operation_files VALUES(?,?,?)", (operation_id,retained_id,role))
    conn.execute("UPDATE photo_files SET revision=revision+1 WHERE photo_id=?", (photo_id,))
    return retained_id


def record_event(conn, *, operation_id, step, outcome, detail=None, timestamp=None):
    """Append one step outcome. A terminal event commits with its state update."""
    if not conn.in_transaction:
        raise RuntimeError("events require the caller's outcome transaction")
    return conn.execute(
        "INSERT INTO operation_events(operation_id,timestamp,step,outcome,detail_json) VALUES(?,?,?,?,?)",
        (operation_id, timestamp or utc_now(), step, outcome,
         _json(detail) if detail is not None else None)).lastrowid


def record_evidence(conn, *, operation_id, location_role, observed_path, observation_kind,
                    result, file_id=None, observed_content_id=None, details=None, observed_at=None):
    """Record what was OBSERVED, never what was done. Unreadable is not absent."""
    if not conn.in_transaction:
        raise RuntimeError("evidence requires the caller's outcome transaction")
    return conn.execute(
        "INSERT INTO operation_evidence(operation_id,file_id,observed_at,location_role,observed_path,"
        "observation_kind,observed_content_id,result,details_json) VALUES(?,?,?,?,?,?,?,?,?)",
        (operation_id, file_id, observed_at or utc_now(), location_role, observed_path,
         observation_kind, observed_content_id, result,
         _json(details) if details is not None else None)).lastrowid


def open_attention_issue(conn, *, operation_id, category, summary, file_id=None, evidence_ids=()):
    """Unresolved outcome: retain what is known and say so, rather than guessing."""
    if not conn.in_transaction:
        raise RuntimeError("attention issues require the caller's outcome transaction")
    issue = conn.execute(
        "INSERT INTO attention_issues(operation_id,file_id,category,summary,opened_at) VALUES(?,?,?,?,?)",
        (operation_id, file_id, category, summary, utc_now())).lastrowid
    for evidence_id in evidence_ids:
        conn.execute("INSERT INTO attention_evidence VALUES(?,?)", (issue, evidence_id))
    return issue


def resolve_attention_issue(conn, issue_id, *, event_id=None):
    """Cleared by established evidence only; there is no mark-resolved bypass."""
    if not conn.in_transaction:
        raise RuntimeError("resolving an issue requires the caller's outcome transaction")
    cur = conn.execute(
        "UPDATE attention_issues SET resolved_at=?,resolution_event_id=? WHERE issue_id=? AND resolved_at IS NULL",
        (utc_now(), event_id, issue_id))
    if cur.rowcount != 1:
        raise RuntimeError("attention issue is unknown or already resolved")


def content_for_digest(conn, *, digest, algorithm='sha1', phash=None, phash_state=None,
                       width=None, height=None):
    """Content identity for one digest, created on first sight and returned thereafter.

    Thumbnails and similarity key on content rather than on a particular
    catalogued copy, so byte-identical files share one row — which is what lets
    duplicates reuse a single thumbnail. COALESCE on update so a later scan that
    learned less (a thumbnail that failed, so no dimensions) never erases what an
    earlier one established.
    """
    if not conn.in_transaction:
        raise RuntimeError("content identity requires the caller's transaction")
    if not digest:
        raise ValueError("content identity requires a digest")
    conn.execute(
        "INSERT INTO contents(hash_algorithm,digest,phash,phash_state,width,height) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(hash_algorithm,digest) DO UPDATE SET "
        "phash=COALESCE(excluded.phash,contents.phash), "
        "phash_state=COALESCE(excluded.phash_state,contents.phash_state), "
        "width=COALESCE(excluded.width,contents.width), "
        "height=COALESCE(excluded.height,contents.height)",
        (algorithm, digest, phash, phash_state, width, height))
    return conn.execute("SELECT content_id FROM contents WHERE hash_algorithm=? AND digest=?",
                        (algorithm, digest)).fetchone()[0]


def record_thumbnail(conn, *, content_id, size, availability, cache_filename=None,
                     bytes_on_disk=None, attempted_file_id=None, observed_path=None,
                     failure_category=None, failure_detail=None):
    """Current cache state for one content at one size.

    Deliberately mutable, and deliberately not lineage: a thumbnail is a
    disposable artifact whose availability is current observed state, so a
    regenerated or cleared entry overwrites rather than appending history.
    `bytes` is recorded so a per-size total is a SUM instead of a walk of the
    cache tree (webui-spec.md 4.2.1).
    """
    if not conn.in_transaction:
        raise RuntimeError("thumbnail cache state requires the caller's transaction")
    conn.execute(
        "INSERT INTO thumbnail_cache(content_id,size,cache_filename,bytes,availability,"
        "attempted_file_id,observed_path,failure_category,failure_detail,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(content_id,size) DO UPDATE SET "
        "cache_filename=excluded.cache_filename,bytes=excluded.bytes,"
        "availability=excluded.availability,attempted_file_id=excluded.attempted_file_id,"
        "observed_path=excluded.observed_path,failure_category=excluded.failure_category,"
        "failure_detail=excluded.failure_detail,updated_at=excluded.updated_at",
        (content_id, size, cache_filename, bytes_on_disk, availability, attempted_file_id,
         observed_path, failure_category, failure_detail, utc_now()))


NO_EXTENSION = ""


def record_discovery(conn, run_id, *, eligible, excluded_by_extension, unreadable):
    """Stores one full walk's file-type accounting. `excluded_by_extension` maps a
    lower-case extension (NO_EXTENSION for none) to a count."""
    excluded = sum(excluded_by_extension.values())
    with transaction(conn):
        conn.execute("INSERT INTO run_discovery VALUES (?,?,?,?,?,?)",
                     (run_id, eligible + excluded, eligible, excluded,
                      _json(dict(sorted(excluded_by_extension.items()))), unreadable))


def read_discovery(conn, run_id):
    """A run's discovery summary, or None when the run walked nothing (scoped runs)."""
    row = conn.execute("SELECT files_found, eligible, excluded, excluded_by_extension_json, "
                       "unreadable FROM run_discovery WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    found, eligible, excluded, by_ext, unreadable = row
    return {'files_found': found, 'eligible': eligible, 'excluded': excluded,
            'excluded_by_extension': json.loads(by_ext), 'unreadable': unreadable,
            'partial': unreadable > 0}


def orphaned_thumbnails(conn):
    """Cache entries whose content no catalogued photo holds: (content_id, size,
    cache_filename). Every photo row counts whatever its status - a moved or delivered
    copy keeps its hash - so an entry turns orphan only when content itself went away,
    as when a re-Index records an edited file under a new hash. webui-spec 4.2.1:
    lineage alone does not keep a thumbnail."""
    return conn.execute(
        "SELECT t.content_id, t.size, t.cache_filename FROM thumbnail_cache t "
        "JOIN contents c USING(content_id) "
        "WHERE NOT EXISTS (SELECT 1 FROM photos p WHERE p.sha1_hash = c.digest)").fetchall()


def present_thumbnails(conn, size):
    """Every cache entry of one size that names a file: (content_id, cache_filename).
    Failed and absent rows are left out - they name no file, and they keep the reason
    a photo has no preview."""
    return conn.execute(
        "SELECT content_id, cache_filename FROM thumbnail_cache "
        "WHERE size = ? AND availability = 'present' AND cache_filename IS NOT NULL",
        (size,)).fetchall()


def forget_thumbnail(conn, content_id, size):
    """Removes one cache entry's record; the content identity it belonged to stays."""
    with transaction(conn):
        conn.execute("DELETE FROM thumbnail_cache WHERE content_id = ? AND size = ?", (content_id, size))


def thumbnail_cache_totals(conn):
    """Per-size cache totals: photos cached at each size, and bytes on disk.

    A SUM over the recorded `bytes` rather than a walk of the cache tree - which is the
    reason thumbnail_cache records that column at all, and why it is keyed on
    (content_id, size). The existing idx_thumbnail_size(size, availability) covers
    exactly this query.

    Counts `present` entries ONLY. A failed or absent row names no cache file and
    carries a NULL `bytes`, so including it would overstate both the size on disk and
    the number of photos the gallery can actually render.

    Returns (size, photos, bytes) smallest size first. The sizes are reported
    separately because they are managed separately: clearing detail previews must not
    touch grid thumbnails, and the two have different economics (webui-spec.md 4.2.1).
    """
    require_schema(conn)
    return [tuple(row) for row in conn.execute(
        "SELECT size, COUNT(*), COALESCE(SUM(bytes),0) FROM thumbnail_cache "
        "WHERE availability='present' GROUP BY size ORDER BY size")]


def keeper_candidates(conn, sha1_hash):
    """Destination paths that may authorize deleting a duplicate source.

    A file carrying an unresolved attention issue is excluded: recovery could
    not establish what is at that path, and an unknown copy must never
    authorize removing a known one.
    """
    require_schema(conn)
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT fs.current_path FROM file_states fs "
        "WHERE fs.location_role='destination' AND fs.presence_state='present' AND fs.sha1_hash=? "
        "AND NOT EXISTS(SELECT 1 FROM attention_issues ai "
        "               WHERE ai.file_id=fs.file_id AND ai.resolved_at IS NULL) "
        "ORDER BY fs.current_path", (sha1_hash,))]


def open_issues_for_path(conn, path):
    """Unresolved issues touching whatever identity currently sits at `path`."""
    return [r[0] for r in conn.execute(
        "SELECT ai.issue_id FROM attention_issues ai JOIN file_states fs ON fs.file_id=ai.file_id "
        "WHERE fs.current_path=? AND ai.resolved_at IS NULL", (path,))]


def begin_operation(conn, *, run_id, photo_id, source_path, dest_path, kind, expected=None,
                    reconciles=None):
    """Durable intent, written and committed BEFORE the file mutation.

    The operations row IS the intent; operation_events records what then
    happened to it. An interrupted operation is therefore one carrying an
    'intent' event and no terminal event, which is how recovery finds work
    that was started and never settled. Without this an interruption leaves
    no operation at all, and there is nothing for evidence to attach to.
    """
    operation_id = conn.execute(
        "INSERT INTO operations(run_id,photo_id,original_filename,source_path,dest_path,status,"
        "timestamp,reconciles_operation_id) VALUES(?,?,?,?,?,?,?,?)",
        (run_id, photo_id, source_path.rsplit('/', 1)[-1] if source_path else None,
         source_path, dest_path, PhotoStatus.PROCESSING, utc_now(), reconciles)).lastrowid
    link_operation(conn, operation_id, photo_id)
    record_event(conn, operation_id=operation_id, step='intent', outcome='recorded',
                 detail={'kind': kind, 'expected': expected})
    return operation_id


def settle_operation(conn, operation_id, *, status, step, outcome, error_message=None, detail=None):
    """Terminal event and the operation's recorded status, committed together."""
    if not conn.in_transaction:
        raise RuntimeError("settling an operation requires the caller's outcome transaction")
    conn.execute("UPDATE operations SET status=?,error_message=?,timestamp=? WHERE id=?",
                 (status, error_message, utc_now(), operation_id))
    return record_event(conn, operation_id=operation_id, step=step, outcome=outcome, detail=detail)


def unsettled_operations(conn, photo_id=None):
    """Operations with recorded intent and no terminal event: started, never settled."""
    sql = ("SELECT o.id, o.photo_id, o.source_path, o.dest_path FROM operations o "
           "WHERE EXISTS(SELECT 1 FROM operation_events e "
           "             WHERE e.operation_id=o.id AND e.step='intent') "
           "  AND NOT EXISTS(SELECT 1 FROM operation_events e "
           "                 WHERE e.operation_id=o.id AND e.step<>'intent')")
    params = ()
    if photo_id is not None:
        sql += " AND o.photo_id=?"
        params = (photo_id,)
    return conn.execute(sql + " ORDER BY o.id", params).fetchall()


# --- Catalog backups -------------------------------------------------------
#
# One consistent SQLite file per backup, taken with SQLite's online backup API
# (an ordinary copy of a live WAL database can capture a torn state). Catalog
# information only, never photos or thumbnails. Callers hold the engine lock:
# a backup is refused while a job runs, which is also what lets an attempt
# found without an outcome be settled as interrupted.

BACKUP_RETENTION_DEFAULT = 20
BACKUP_PREFIX = "ns-catalog-"
CONTAINER_BACKUPS = "/backups"
_PARTIAL = ".partial"
# Zstandard at level 10, measured on a 524 MB full-library catalog: 19.3 MB (27x)
# in 1.2 s. Levels 9-12 land within 0.5 MB of each other; 13 changes strategy and
# took 4.9 s for a larger file. Smaller files cost time spent holding the engine
# lock: zstd -19 16.6 MB in 47 s, xz -6 16.1 MB in 27 s. The full comparison is in
# webui-spec 9.
BACKUP_COMPRESSION = "zstd"
BACKUP_ZSTD_LEVEL = 10
BACKUP_SUFFIX = ".db.zst"


class BackupFailed(RuntimeError):
    def __init__(self, category, detail):
        super().__init__(f"{category}: {detail}")
        self.category, self.detail = category, detail


def _overlap(appdata, backups):
    appdata, backups = Path(appdata).resolve(), Path(backups).resolve()
    if appdata == backups or backups.is_relative_to(appdata) or appdata.is_relative_to(backups):
        return f"{backups} and {appdata} overlap"
    try:
        if os.path.samefile(appdata, backups):
            return f"{backups} and {appdata} are one directory reached by two paths"
    except OSError:
        pass
    return None


def _check_backup_storage(backups_dir, appdata_dir):
    backups = Path(backups_dir)
    if not backups.is_dir():
        raise BackupFailed("storage_unavailable", f"{backups} does not exist or is not a folder")
    # The image creates /backups so the mount has somewhere to land. Unmounted,
    # a backup would live in the container's own layer and vanish with it: the
    # silent fallback webui-spec 9 forbids. Another path passed explicitly
    # (development, tests) is the operator's own choice and taken as given.
    if backups.resolve() == Path(CONTAINER_BACKUPS) and not os.path.ismount(backups):
        raise BackupFailed("storage_not_mounted",
                           f"{backups} is not a mounted volume; a backup written there would be "
                           f"lost when the container is replaced")
    overlap = _overlap(appdata_dir, backups)
    if overlap:
        # A backup inside the thing it backs up dies with it.
        raise BackupFailed("storage_overlaps_appdata", overlap)
    if not os.access(backups, os.W_OK | os.X_OK):
        raise BackupFailed("storage_unwritable", f"{backups} is not writable")


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError as exc:
        if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
            raise
    finally:
        os.close(fd)


def settle_interrupted_backups(conn, backups_dir):
    """Marks attempts left without an outcome as interrupted and removes their
    partial files. Only safe under the engine lock, which proves no attempt is live."""
    with transaction(conn):
        n = conn.execute("UPDATE backup_attempts SET outcome='interrupted' WHERE outcome IS NULL").rowcount
    try:
        for leftover in Path(backups_dir).glob(BACKUP_PREFIX + "*" + _PARTIAL):
            leftover.unlink(missing_ok=True)
    except OSError:
        pass  # storage unreachable: the next attempt reports it
    return n


class _Digest:
    """A write-only sink that hashes what it is given, for streaming comparisons."""
    def __init__(self):
        self.hash = hashlib.sha256()

    def write(self, data):
        self.hash.update(data)
        return len(data)


def _file_digest(path):
    digest = _Digest()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.write(block)
    return digest.hash.digest()


def _compress_and_verify(raw, packed):
    """Compresses `raw` to `packed` with a frame checksum, then decompresses the
    result and compares it with `raw`. A backup nobody can restore is worse than
    none, so the compressed file is proven before it is published."""
    compressor = zstandard.ZstdCompressor(level=BACKUP_ZSTD_LEVEL, write_checksum=True)
    with open(raw, "rb") as source, open(packed, "wb") as target:
        compressor.copy_stream(source, target, size=raw.stat().st_size)
        target.flush()
        os.fsync(target.fileno())
    restored = _Digest()
    with open(packed, "rb") as source:
        zstandard.ZstdDecompressor().copy_stream(source, restored)
    if restored.hash.digest() != _file_digest(raw):
        raise BackupFailed("verification_failed", "the compressed backup does not decompress "
                                                   "to the verified snapshot")


def _snapshot(conn, attempt_id, final):
    """Copies the live catalog beside `final`, verifies it, compresses it, verifies
    the compressed file, publishes it. Returns the published (compressed) size."""
    raw = final.with_name(final.name[:-len(".zst")] + _PARTIAL)   # <name>.db.partial
    packed = final.with_name(final.name + _PARTIAL)                # <name>.db.zst.partial
    try:
        dst = sqlite3.connect(raw)
        try:
            conn.backup(dst)
            # Self-contained file: no -wal/-shm companions beside a backup, which
            # the manual restore instructions say must never travel with it.
            dst.execute("PRAGMA journal_mode=DELETE")
            # The snapshot was taken while this attempt was in flight. Recording
            # its success inside the copy stops a restored catalog from settling
            # the very backup it came from as interrupted.
            dst.execute("UPDATE backup_attempts SET outcome='succeeded', ended_at=? WHERE attempt_id=?",
                        (utc_now(), attempt_id))
            dst.commit()
            check = dst.execute("PRAGMA quick_check").fetchone()[0]
            version = dst.execute("SELECT version FROM catalog_schema").fetchone()[0]
        finally:
            dst.close()
        if check != "ok" or version != SCHEMA_VERSION:
            raise BackupFailed("verification_failed", f"quick_check={check}, schema version={version}")
        _compress_and_verify(raw, packed)
        os.rename(packed, final)
        _fsync_dir(final.parent)
        raw.unlink()
        return final.stat().st_size
    except BackupFailed:
        for leftover in (raw, packed):
            leftover.unlink(missing_ok=True)
        raise
    except (OSError, sqlite3.Error, zstandard.ZstdError) as exc:
        for leftover in (raw, packed):
            try:
                leftover.unlink(missing_ok=True)
            except OSError:
                pass
        category = "insufficient_space" if getattr(exc, "errno", None) == errno.ENOSPC or \
            "full" in str(exc).lower() else "write_failed"
        raise BackupFailed(category, str(exc)) from exc


def backup_catalog(db_path, backups_dir, appdata_dir, *, trigger, related_run_id=None):
    """Records an attempt, writes one verified snapshot, then applies retention.
    The caller holds the engine lock (see settle_interrupted_backups).

    Returns {'attempt_id', 'outcome', 'filename', 'size', 'pruned', 'error_category',
    'error_detail'}. A failure is recorded and returned, never raised: whether it
    stops anything is the caller's decision (a pre-action backup must; a post-job
    backup must not turn completed work into a failure).
    """
    if trigger not in ("manual", "post_job", "pre_action"):
        raise ValueError(f"unknown backup trigger: {trigger}")
    # FULL: a handful of commits per backup, and losing the outcome row to a
    # power cut would leave a verified file recorded as an interrupted attempt.
    conn = connect(db_path, synchronous="FULL")
    try:
        require_schema(conn)
        settle_interrupted_backups(conn, backups_dir)
        started_at = utc_now()
        with transaction(conn):
            attempt_id = conn.execute(
                "INSERT INTO backup_attempts(trigger_kind,related_run_id,started_at) VALUES(?,?,?)",
                (trigger, related_run_id, started_at)).lastrowid
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{BACKUP_PREFIX}{stamp}-{attempt_id:06d}-{trigger}{BACKUP_SUFFIX}"
        try:
            _check_backup_storage(backups_dir, appdata_dir)
            size = _snapshot(conn, attempt_id, Path(backups_dir) / filename)
        except BackupFailed as exc:
            with transaction(conn):
                conn.execute("UPDATE backup_attempts SET outcome='failed', ended_at=?, "
                             "error_category=?, error_detail=? WHERE attempt_id=?",
                             (utc_now(), exc.category, exc.detail, attempt_id))
            return {'attempt_id': attempt_id, 'outcome': 'failed', 'filename': None, 'size': None,
                    'pruned': [], 'error_category': exc.category, 'error_detail': exc.detail}
        now = utc_now()
        with transaction(conn):
            conn.execute("UPDATE backup_attempts SET outcome='succeeded', ended_at=? WHERE attempt_id=?",
                         (now, attempt_id))
            conn.execute("INSERT INTO backup_artifacts(attempt_id,relative_filename,size,compression_format,"
                         "created_at,availability,last_checked_at) VALUES(?,?,?,?,?,'present',?)",
                         (attempt_id, filename, size, BACKUP_COMPRESSION, now, now))
        # Pruned only after a new backup succeeded, so retention never leaves
        # fewer usable backups than before the attempt.
        pruned = prune_automatic_backups(conn, backups_dir)
        return {'attempt_id': attempt_id, 'outcome': 'succeeded', 'filename': filename, 'size': size,
                'pruned': pruned, 'error_category': None, 'error_detail': None}
    finally:
        conn.close()


def unbacked_changes(conn, *, exclude_run_id=None):
    """Catalog records no successful backup holds: operations written after the newest
    successful backup started, other than Skipped and Cancelled rows, which record that
    nothing was done. Returns (count, newest successful backup's start or None, sorted
    run ids). `exclude_run_id` leaves out a run still in progress, whose own post-job
    backup will cover it. webui-spec 9: report this after an interruption or a failed
    backup; never take a backup automatically at startup."""
    row = conn.execute("SELECT started_at FROM backup_attempts WHERE outcome = 'succeeded' "
                       "ORDER BY julianday(started_at) DESC LIMIT 1").fetchone()
    since = row[0] if row else None
    sql = ("SELECT COUNT(*), GROUP_CONCAT(DISTINCT run_id) FROM operations "
           "WHERE status NOT IN (?, ?)")
    params = [OPERATION_SKIPPED, OPERATION_CANCELLED]
    if since:
        sql += " AND julianday(timestamp) > julianday(?)"
        params.append(since)
    if exclude_run_id is not None:
        sql += " AND run_id != ?"
        params.append(exclude_run_id)
    count, runs = conn.execute(sql, params).fetchone()
    return count, since, sorted(int(r) for r in runs.split(",")) if runs else []


def backup_retention(conn):
    setting = read_settings(conn).get('backup_retention')
    return setting['value'] if setting else BACKUP_RETENTION_DEFAULT


def _retained_automatic(conn):
    return conn.execute(
        "SELECT a.artifact_id, a.relative_filename FROM backup_artifacts a "
        "JOIN backup_attempts t USING(attempt_id) "
        "WHERE t.trigger_kind != 'manual' AND a.availability = 'present' "
        "ORDER BY a.created_at DESC, a.artifact_id DESC").fetchall()


def automatic_backups_beyond(conn, limit):
    """How many automatic backups a retention limit of `limit` would remove now:
    what Settings shows before a lower limit is applied."""
    return max(0, len(_retained_automatic(conn)) - limit)


def prune_automatic_backups(conn, backups_dir):
    """Removes the oldest automatic backups beyond the retention limit. Manual
    backups are never pruned. A file that cannot be removed stays recorded
    present and is retried at the next prune."""
    pruned = []
    for artifact_id, name in _retained_automatic(conn)[backup_retention(conn):]:
        try:
            (Path(backups_dir) / name).unlink(missing_ok=True)
        except OSError:
            continue
        with transaction(conn):
            conn.execute("UPDATE backup_artifacts SET availability='pruned', pruned_at=? "
                         "WHERE artifact_id=?", (utc_now(), artifact_id))
        pruned.append(name)
    return pruned


def refresh_backup_availability(conn, backups_dir):
    """Re-observes every unpruned artifact. An unreachable /backups makes each one
    'unknown' rather than 'missing': storage trouble is not evidence of deletion."""
    reachable = Path(backups_dir).is_dir() and os.access(backups_dir, os.R_OK | os.X_OK)
    now = utc_now()
    rows = conn.execute("SELECT artifact_id, relative_filename FROM backup_artifacts "
                        "WHERE availability != 'pruned'").fetchall()
    with transaction(conn):
        for artifact_id, name in rows:
            state = ('present' if (Path(backups_dir) / name).is_file() else 'missing') if reachable else 'unknown'
            conn.execute("UPDATE backup_artifacts SET availability=?, last_checked_at=? WHERE artifact_id=?",
                         (state, now, artifact_id))
    return reachable
