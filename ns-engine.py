"""
Project: NegativeSpace (Core Engine)
Description: A backend engine for organizing large photo collections based on spec.

Runtime Arguments:
Source and destination must be separate, non-overlapping underlying folders.
Never mount the same folder at both paths or nest one inside the other,
including on network shares. Overlapping mounts can cause unintended file
deletion and are not reliably detected by the engine.

- --source <path> (Optional) Path to unorganized source directory (default: "/data/source").
- --dest <path> (Optional) Path for organized output directory (default: "/data/dest").
- --base <path> (Optional) Base directory for app artifacts (default: "/data").
  Creates/uses <base>/db/ for SQLite and <base>/logs/ for logs.
- --workers <N> (Optional) Override the worker process count used for
  hashing/date resolution (default: os.cpu_count()).
- --exts <.ext1,.ext2,...> (Optional) Comma-separated extension list,
  replacing the built-in default set for directory scanning. Has no effect
  on --file-ids targeting, since that bypasses directory scanning entirely.
- --file-ids <id1,id2,...> (Optional) Comma-separated database row IDs to
  target, bypassing the directory scan and processing exactly these
  already-cataloged files. A file must have gone through at least one prior
  Index for its ID to exist. This is what powers selection-scoped
  operations from the web UI — e.g. "Move just these 3 photos" —
  but works identically from the CLI. Mutually exclusive with
  --source-subdir.
- --source-subdir <path> (Optional) Path, relative to --source, scoping the
  run to already-cataloged files beneath it. Queries the catalog by
  source_path prefix instead of walking the filesystem or enumerating IDs,
  which is what lets the web UI offer "operate on this whole folder" for
  selections far larger than --file-ids can express (there is a real OS
  limit on command-line length). Mutually exclusive with --file-ids.

Per-file failures never abort a run: an unreadable, vanished, or otherwise
unprocessable file is recorded as status='Failed' with a human-readable
reason in operations.error_message, and the scan carries on with the rest.

Mode flags (mutually exclusive — pick at most one; omitting both runs the
default Index):
- --move: Execute physical migration (Copy-Verify-Delete). Source files are
  moved: deleted after a verified copy lands at the destination. Confirmed
  exact duplicates are also removed from source once a verified copy of
  their content exists elsewhere at the destination.
- --copy: Non-destructive. Same verified Copy-Verify step as --move, but the
  source file is never deleted or modified afterward. Duplicate source files
  are also left untouched in this mode — nothing is ever removed from source.
- (neither of the above): Index — full scan, hashing, and destination-path
  resolution, exactly like --move/--copy would compute, but no physical
  action is taken. This is the safe default described in spec §4.1.

Cancellation: sending SIGTERM or SIGINT (e.g. `docker stop`, or Ctrl+C)
during a --move/--copy run lets the file currently being copy-verified
finish, then stops before starting the next one. During the Index/scan
phase it takes effect at the next batch boundary, and a scan cancelled that
way skips the move/copy phase entirely rather than entering it; everything
already written to the database is kept, so re-running simply continues. Every file that didn't get
a chance to run is written to the operations log with status='Cancelled' —
current, un-started work stays 'Pending' in the photos table (so a plain
re-run naturally picks it back up), while the operations log keeps a full
historical record of exactly what happened during that specific run,
including which items never got reached. Duplicate-source cleanup is
skipped entirely for a cancelled run, since it depends on every Pending
item's fate being fully known first.

Retries: there is no dedicated retry mechanism. If some files fail (or a
run is cancelled), just re-run the same command — files already moved are
gone from --source and won't be reprocessed; only what's still there (still
'Pending', or previously 'Failed' and re-flagged 'Pending' by the next
Index) gets touched again. This is fast because nothing already-successful
needs to be redone.

No result is ever silently lost across crashes either: a run interrupted by
something uncatchable (SIGKILL, OOM-kill, power loss) leaves its `runs` row
at status='Running' with no end time — the next invocation's startup
reconciliation detects this and marks it 'Crashed' with a real end
timestamp, rather than leaving a phantom "still running" entry forever.

System & Python Dependencies:
- System Binary (HARD REQUIREMENT — the engine refuses to start without
  both this binary and the PyExifTool Python package; see Metadata
  Extraction below for exactly what ExifTool is used for and why Pillow/
  rawpy/imagehash are still required alongside it, not replaced by it):
  - ExifTool
    Linux: sudo apt install libimage-exiftool-perl
    macOS: brew install exiftool
    Windows: choco install exiftool
  - Python package: pip install pyexiftool

Metadata Extraction:
    ExifTool is used via a PERSISTENT process per worker (PyExifTool's
    `-stay_open` mode, one instance per ProcessPoolExecutor worker,
    started once via `_init_worker_process` and reused for every file that
    worker handles) rather than spawning a fresh `exiftool` subprocess per
    file. Measured directly: a repeat query against an already-running
    instance took ~2.6ms vs ~24ms+ paying process-spawn overhead — roughly
    a 10x difference that compounds significantly across a large library.

    For every file, the engine captures BOTH "date taken" (used to compute
    the destination folder) AND the full metadata set available (camera
    make/model, ISO, aperture, shutter speed, and whatever else the source
    exposes) from the same underlying capture. Fallback order, falling
    through only if the previous step fails or finds nothing at all:

    1. ExifTool (persistent per-worker process, full tag set, not a
       curated subset) — the primary and now-guaranteed-available source.
       The only method that can read metadata from RAW-family files
       (.cr2, .nef, .arw, .raf, .raw, .dng), since neither PIL nor rawpy
       expose EXIF/metadata fields for those formats (rawpy only decodes
       pixel data, for pHash generation — it has no metadata-reading API
       at all).
    2. PIL (Image.getexif(), PLUS the "Exif" sub-IFD via get_ifd(0x8769))
       — a defensive per-FILE fallback, not a "ExifTool isn't installed"
       fallback anymore (that case can no longer happen — see above). Used
       only if ExifTool genuinely ran but returned nothing usable for a
       specific file. Works for standard formats (JPEG, PNG, TIFF, HEIC
       with pillow-heif); cannot open RAW-family formats at all.
    3. File modification time — used only if neither of the above
       produces a usable date. No richer metadata is available at this
       fallback level; the stored metadata is just {"date_taken": ...}.

    IMPORTANT — ExifTool being a hard requirement does NOT mean Pillow,
    rawpy, and imagehash became optional or got removed. They do a
    completely different job that ExifTool cannot do at all: ExifTool
    reads embedded metadata tags, it does not decode pixel data. pHash
    generation (compute_phash()) and thumbnail generation both require
    actually opening and decoding the image (PIL for standard/HEIC
    formats, rawpy for RAW-family formats) and feeding real pixel data to
    `imagehash.phash()` — there is no metadata-only substitute for this,
    and ExifTool's ability to extract an already-embedded camera preview
    image (where one exists) doesn't change that, since imagehash still
    needs that extracted preview decoded through PIL to hash it anyway.
"""

import argparse
import contextlib
import errno
import fcntl
import hashlib
import io
import json
import logging
import logging.handlers
import warnings
import multiprocessing as mp
import os
import shutil
import signal
import sqlite3
import sys
import tempfile
import threading
import queue
import time
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from typing import Optional, Callable, Any, List

# --- Configuration & Constants ---
MAX_WORKER_PROCESSES = os.cpu_count() or 4
DB_QUEUE_SIZE = 1000

# Scan-phase commit batching. Only the INDEX path batches (see
# db_writer_worker); the Move/Copy loop deliberately keeps its per-file
# commits because they are its crash-recovery protocol, not bookkeeping.
# 100 captures ~9.8x of an ~11.6x ceiling measured against ExifTool-sized
# metadata rows — ten times the batch buys under 20% more while risking ten
# times the rework on a kill. The time bound matters independently of the
# row count: at one large RAW every few seconds a pure row-count batch would
# leave the database (and the web UI's progress polling) frozen for a minute at
# a stretch, so whichever limit trips first wins.
DB_COMMIT_BATCH_SIZE = 100
DB_COMMIT_INTERVAL_SECONDS = 3.0

# How often the scan reports progress. A real 29,000-file library took ~25
# minutes and printed nothing at all between "Discovered 29047 files" and
# completion — no way to tell a working run from a wedged one, and no basis for
# the progress bar the web UI needs. Time-based rather than every-N-files so the
# cadence stays readable whether a library is 200 files or 200,000.
PROGRESS_INTERVAL_SECONDS = 15.0
SHA1_CHUNK_SIZE = 65536
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0  # Seconds
# Extensions scanned by default. A missing entry is worse than a failure: the
# file is not indexed, not counted, not reported — it is simply invisible, and
# you find out when it is still sitting in the source folder after an organize
# pass. '.tif' was absent while '.tiff' was present, which silently skipped
# every TIFF written by the more common spelling.
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
# The storage engine is named in the file so a second store can sit beside it
# without ambiguity — a DuckDB companion may sit beside it for all-pairs
# perceptual-hash matching, which SQLite is the wrong shape for.
# See docs/engine-spec.md 9.3.
DB_FILENAME = "ns_sqlite.db"

PARTIAL_SUFFIX = ".organizing.partial"

# Longest edge of the grid thumbnail, in pixels. The rule of thumb is roughly
# twice the CSS size a tile is displayed at, because a HiDPI screen renders two
# device pixels per CSS pixel — 320px stays sharp to about a 160px tile. The
# 1024px detail preview (webui-spec.md 4.2.1) is generated lazily on first view
# and is deliberately NOT produced here: generating both up front measured 14
# minutes and 19GB for a 150,000-image catalog against 3.3 minutes and 2.3GB,
# most of it previews nobody opens.
THUMBNAIL_SIZE = 320
THUMBNAIL_DIR_NAME = "thumbnails"
THUMBNAIL_JPEG_QUALITY = 85
# Distinct from PARTIAL_SUFFIX: that one marks a half-written PHOTO at the
# destination and is what recovery looks for. A half-written thumbnail is
# disposable and must never be mistaken for one.
THUMBNAIL_PARTIAL_SUFFIX = ".thumb.partial"

# os.link() failures that mean "this filesystem cannot hard-link at all"
# (FAT/exFAT, some network shares). Only these may fall back to rename(), which
# replaces an existing file silently; any other link failure fails the publish.
_NO_HARDLINK_ERRNOS = frozenset({errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP})

# fsync() on a directory is not implemented by every filesystem. These errnos
# report the operation as absent, not as a failure to persist, so they are
# tolerated; anything else propagates.
_DIR_FSYNC_UNSUPPORTED_ERRNOS = frozenset({errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP})
LOCK_FILENAME = "engine.lock"

# Recorded in each photo's metadata_json as "date_source", so it is always
# answerable after the fact where a file's date — and therefore its YYYY/MM/DD
# folder — actually came from. EXIF timestamps carry no timezone and are used
# exactly as the camera wrote them; a filesystem mtime is interpreted in the
# container's timezone, so only DATE_SOURCE_MTIME files are affected by TZ.
DATE_SOURCE_EXIF = "exif"
DATE_SOURCE_MTIME = "file_mtime"

# Where a photo goes when the engine could not read a date from it.
#
# Filing by modification time puts a date on a photo that nobody vouched for —
# for an export that is the download date, which is how photos from the 2000s
# landed in 2024/ and 2025/ folders on a real run. Those files go here instead,
# subdivided by year so the folder stays navigable at ~8% of a library without
# the tree ever claiming to know when the photograph was taken.
#
# The year comes from the file's own modification time. That is a real fact
# about the FILE even when it is not a fact about the PHOTOGRAPH, which is
# exactly why it may organise the folder but must not name a date folder.
UNDATED_FOLDER = "Undated"

# --- Status vocabularies -----------------------------------------------------
#
# Every value any of the three tables may hold in its `status` column, named
# once, because scattered literals fail silently: SQLite accepts any string,
# and a misspelling in a WHERE clause matches zero rows rather than
# raising. A typo in the duplicate-cleanup anchor check would simply stop
# removing duplicate sources; a typo in the 'Processing' marker would make
# crash recovery blind to a file interrupted mid-move. Nothing would error and
# nothing would be logged.
#
# The CHECK constraints below are generated from these same tuples, so the
# database enforces exactly the set the code knows about — including against
# the web API and ad-hoc sqlite3 sessions, neither of which import this
# module.

from ns_db import (PhotoStatus, RunStatus, PHOTO_STATUSES, RUN_STATUSES,
                   OPERATION_STATUSES, OPERATION_CANCELLED, OPERATION_SKIPPED)
import ns_db

# Statuses that mean "already delivered to the destination and verified".
ANCHOR_DELIVERED_STATUSES = (PhotoStatus.COMPLETED, PhotoStatus.COPIED)

# Statuses in which a row can stand as the original of its duplicate group:
# its content is delivered, being delivered, or queued to be.
ANCHOR_STATUSES = (PhotoStatus.PENDING, PhotoStatus.PROCESSING) + ANCHOR_DELIVERED_STATUSES

# Statuses that represent a settled record — the file has been examined and
# its row is trustworthy. partition_unchanged() will only skip re-reading a
# file whose row is in one of these; anything mid-flight or failed is always
# rescanned rather than trusted on the strength of a stat.
SETTLED_STATUSES = (
    PhotoStatus.PENDING, PhotoStatus.COMPLETED, PhotoStatus.COPIED,
    PhotoStatus.DUPLICATE, PhotoStatus.REMOVED_DUPLICATE,
)

# Statuses whose source file is legitimately gone because a prior --move run
# consumed it on purpose. Targeted re-runs skip these rather than re-scanning
# them: the source is *supposed* to be missing, so re-indexing would overwrite
# a real Completed audit state with a spurious Failed.
SOURCE_CONSUMED_STATUSES = (PhotoStatus.COMPLETED, PhotoStatus.REMOVED_DUPLICATE)

# Every status a --move or --copy selection is drawn from, which is the same
# set for both modes: the primaries each transfers (Pending, plus Copied —
# --move finishes those, --copy reports them as already delivered) and the
# duplicates each cleans up or records as skipped. A cancelled run reconciles
# the selection against this set to find the members it never reached.
# Deliberately excludes Processing: cancellation is checked between files, so
# no row is mid-flight by then, and recording "nothing was attempted" for a
# half-attempted file would be a false record rather than a missing one.
CANCELLABLE_SELECTION_STATUSES = (
    PhotoStatus.PENDING, PhotoStatus.COPIED, PhotoStatus.DUPLICATE,
)


def sql_values(statuses) -> str:
    """Renders a status tuple as a SQL literal list: "'Pending', 'Failed'".

    Values are module constants, never user input — but they are still
    validated as bare identifiers-with-underscores so this can never become a
    string-building hole if someone adds a value carelessly.
    """
    for value in statuses:
        if not value.replace("_", "").isalnum():
            raise ValueError(f"status value is not a bare word, refusing to inline it: {value!r}")
    return ", ".join(f"'{v}'" for v in statuses)


# --- Dependency Check ---
try:
    import imagehash
    IMAGEHASH_SUPPORTED = True
except ImportError:
    IMAGEHASH_SUPPORTED = False

try:
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    PIL_SUPPORTED = True
except ImportError:
    PIL_SUPPORTED = False

# rawpy decodes RAW-family files (.raw/.dng/.cr2/.nef/.arw/.raf) for the
# perceptual hash (docs/engine-spec.md 3.3). PIL cannot read real sensor data;
# without rawpy every such file would store "error" as its phash.
try:
    import rawpy
    RAWPY_SUPPORTED = True
except ImportError:
    RAWPY_SUPPORTED = False


# --- Dependency Check: ExifTool is a HARD requirement (see module docstring
# for why) — checked here, enforced with a clear fatal error in main(). Two
# things must both be true: the PyExifTool Python package is importable, AND
# the actual `exiftool` system binary is on PATH (the package is just a thin
# wrapper — it does nothing without the real binary installed).
try:
    import exiftool as pyexiftool
    PYEXIFTOOL_PACKAGE_AVAILABLE = True
except ImportError:
    PYEXIFTOOL_PACKAGE_AVAILABLE = False

EXIFTOOL_BINARY_AVAILABLE = shutil.which('exiftool') is not None
EXIFTOOL_SUPPORTED = PYEXIFTOOL_PACKAGE_AVAILABLE and EXIFTOOL_BINARY_AVAILABLE


def configure_multiprocessing_start_method() -> str:
    """
    Moves worker creation off plain fork(), and returns the method chosen.

    rawpy is built with OpenMP, and an OpenMP runtime that has already started
    its thread pool does not survive fork() — the child inherits the pool's
    state without its threads, and the next parallel region can deadlock. rawpy
    warns about this itself. It is a real hazard, not a lint: the RAW decode
    path runs inside these workers, so a large library with RAW files is
    exactly where it would bite, and a deadlock there looks like the scan
    simply stopping.

    forkserver is preferred over spawn: workers are forked from a small clean
    template process that never imported rawpy or touched OpenMP, so startup
    stays cheap while avoiding the unsafe fork. spawn is the fallback for
    platforms without forkserver (Windows), where it is the only safe option
    anyway.

    Note this is what makes per-worker logging setup load-bearing rather than
    belt-and-braces: neither method inherits the parent's handlers, so without
    the explicit configure_logging() in _init_worker_process every worker-side
    log line would vanish.
    """
    available = mp.get_all_start_methods()
    for method in ("forkserver", "spawn"):
        if method in available:
            mp.set_start_method(method, force=True)
            return method
    return mp.get_start_method()


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
result_queue = queue.Queue(maxsize=DB_QUEUE_SIZE)


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


def configure_logging(log_dir: Path):
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
    # Without this they go straight to stderr and never touch a handler, so a
    # real library scan showed "Truncated File Read" and rawpy's OpenMP warning
    # on the console while the log file recorded nothing — the log looked clean
    # precisely where something was wrong. These matter: a truncated TIFF names
    # a file worth investigating.
    logging.captureWarnings(True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] (pid:%(process)d/%(threadName)s) %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
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


# --- Resilient Network IO Wrapper ---
# Conditions that are a property of the path or the filesystem, not a hiccup.
# Retrying these cannot possibly succeed, and sleeping through the backoff
# first turns a fast, clear failure into a slow one. The case that exposed
# this: --move against a source mounted :ro raises EROFS on every delete, so
# each file burned the full 1s + 2s backoff before failing — three seconds per
# file, guaranteed, which on a 10,000-photo library is over eight hours of
# sleeping to arrive at "nothing worked". Genuinely transient conditions
# (below, the reason this wrapper exists at all) still get the full backoff.
PERMANENT_IO_ERRNOS = frozenset({
    errno.EROFS,          # read-only filesystem — e.g. a :ro volume mount
    errno.EACCES,         # permission denied
    errno.EPERM,
    errno.ENOENT,         # the file is gone; waiting will not bring it back
    errno.EISDIR,
    errno.ENOTDIR,
    errno.ENOSPC,         # out of space — retrying the same write is futile
    errno.EXDEV,          # cross-device link
    errno.ENAMETOOLONG,
})



def retry_io_operation(action_description: str, func: Callable[..., Any], *args, **kwargs) -> Any:
    """Executes an IO function with exponential backoff to handle transient network share issues."""
    delay = INITIAL_RETRY_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except (OSError, PermissionError, IOError) as e:
            if getattr(e, "errno", None) in PERMANENT_IO_ERRNOS:
                logger.error(
                    f"IO operation cannot succeed [{action_description}]: {e}. "
                    f"Not retrying — this is a permanent condition, not a transient one."
                )
                raise
            if attempt == MAX_RETRIES:
                logger.error(f"IO Operation failed after {MAX_RETRIES} attempts [{action_description}]: {e}")
                raise e
            logger.warning(
                f"Transient IO error during [{action_description}]: {e}. "
                f"Retrying in {delay:.1f}s (Attempt {attempt}/{MAX_RETRIES})..."
            )
            time.sleep(delay)
            delay *= 2.0


# --- SQLite Connection Helper ---
def get_db_connection(db_path: str, synchronous: str = "NORMAL") -> sqlite3.Connection:
    """
    Creates a connection with WAL mode, an extended busy timeout for concurrent
    safety, and the caller's synchronous level — NORMAL unless asked otherwise.

    synchronous=NORMAL (rather than SQLite's default FULL) stops the engine
    fsyncing on every single commit, which measured ~4.4x faster on its own.
    The safety tradeoff is specifically bounded: under WAL, NORMAL still
    survives *process* death — SIGKILL, an OOM-kill, `docker stop` timing out
    — because committed data is already in the OS page cache and is replayed
    from the WAL on the next open. Only a kernel panic or power loss can lose
    recently committed transactions, and process death is by far the likelier
    failure here.

    That bound covers the CATALOG only; it does nothing for the photo files,
    which is why the file protocol carries its own ordering. A source is
    deleted only after its verified copy, the copy's directory entry, and
    every directory entry from --dest down to it have been fsynced (see
    _remove_verified_source and _mkdir_durable). With those in place, a power
    loss can leave a stale row, or a photo present at both ends — recoverable
    by re-indexing — but not a deleted original without a copy on storage
    that honours fsync.

    **_run_move_or_copy asks for FULL, and is the only caller that does.** That
    loop commits status=Processing with dest_path before unlinking a source,
    and reconciliation finds interrupted work by that marker alone; losing it
    to a power cut leaves a delivered photo recorded Failed, which a probe
    reproduced. FULL measured 1.42x on that path — not the ~4.4x above, which
    is the scan path batching a hundred rows per commit and writing no markers.
    The scan path therefore keeps NORMAL and only the move loop pays.

    The level is whitelisted rather than interpolated blindly: a PRAGMA value
    cannot be bound as a parameter, so it is checked instead.
    """
    return ns_db.connect(db_path, synchronous=synchronous)


# --- Database Schema Initialization ---
def init_database(db_path: str):
    """Explicitly initialize the engine-owned schema; never migrate old evidence."""
    ns_db.initialize(db_path)


def start_run(
    db_path: str, mode: str, source_path: str, dest_path: str,
    file_ids: Optional[List[int]], source_subdir: Optional[str] = None,
    *, defaults=None, overrides=None
) -> int:
    """
    Inserts the `runs` row for this invocation and returns its id.
    `file_ids` and `source_subdir` are mutually exclusive targeting
    mechanisms (enforced at the CLI level) — at most one is ever set.
    Persisted as a self-describing JSON object so the audit trail can tell
    which targeting mechanism (if any) scoped the run.
    """
    if file_ids:
        targeting_filter = json.dumps({"file_ids": file_ids})
    elif source_subdir:
        targeting_filter = json.dumps({"source_subdir": source_subdir})
    else:
        targeting_filter = None
    with contextlib.closing(get_db_connection(db_path, synchronous="FULL")) as conn:
        run_id, _ = ns_db.create_run(
            conn, mode=mode, source=source_path, destination=dest_path,
            targeting=json.loads(targeting_filter) if targeting_filter else None,
            defaults=defaults, overrides=overrides,
        )
        return run_id


def finish_run(db_path: str, run_id: int, status: str):
    """Finalizes the `runs` row — called on normal completion, cancellation, or crash."""
    conn = get_db_connection(db_path)
    conn.execute(
        "UPDATE runs SET status = ?, ended_at = ? WHERE id = ?",
        (status, datetime.now().isoformat(), run_id)
    )
    conn.commit()
    conn.close()


def log_operation(conn: sqlite3.Connection, run_id: int, photo_id: Optional[int], source_path: str,
                   dest_path: Optional[str], status: str, error_message: Optional[str] = None,
                   has_name_collision: bool = False, commit: bool = True, delivery=None,
                   operation_id: Optional[int] = None, step: str = "transfer"):
    """
    Appends one row to the operations audit log. Never overwrites — every call
    is new history.

    The row also records the photo's content hash, read from its catalog row
    in the same statement so no caller has to supply it. photo_id is valid
    only inside one catalog; the hash names the same content in any catalog,
    so a photo's history can be matched up again after a rebuild. A file that
    could not be read has no hash and records NULL.

    commit=False leaves the row in the caller's open transaction, for the scan
    phase where many rows are committed together. The Move/Copy loop always
    uses the default: there, each audit row must be durable alongside the file
    operation it describes.

    That last sentence is enforced rather than merely intended: the Move/Copy
    loop opens its connection at synchronous=FULL (see get_db_connection), so
    committing here fsyncs. On the scan path, which stays at NORMAL, a power
    cut can still lose recently batched rows — they describe reading rather
    than deleting, and a re-Index reproduces them.
    """
    if operation_id is None:
        cur = conn.execute(
            """INSERT INTO operations
               (run_id, photo_id, original_filename, source_path, dest_path, status, error_message,
                has_name_collision, timestamp, sha1_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                       (SELECT NULLIF(sha1_hash, '') FROM photos WHERE id = ?))""",
            (
                run_id, photo_id, Path(source_path).name if source_path else None, source_path, dest_path,
                status, error_message, 1 if has_name_collision else 0, datetime.now().isoformat(),
                photo_id
            )
        )
        record = cur.lastrowid
        ns_db.link_operation(conn, record, photo_id)
    else:
        # Settling intent recorded BEFORE the mutation: update that row rather
        # than inserting a second one, and close it with a terminal event. An
        # operation carrying intent and no terminal event is what recovery
        # recognises as interrupted, so this is what stops a completed transfer
        # from looking interrupted on the next run.
        record = operation_id
        conn.execute(
            """UPDATE operations SET status = ?, error_message = ?, dest_path = ?,
                   has_name_collision = ?, timestamp = ?,
                   sha1_hash = (SELECT NULLIF(sha1_hash, '') FROM photos WHERE id = ?)
                 WHERE id = ?""",
            (status, error_message, dest_path, 1 if has_name_collision else 0,
             datetime.now().isoformat(), photo_id, record))
        ns_db.record_event(conn, operation_id=record, step=step,
                           outcome="completed" if delivery is not None else "failed",
                           detail={"status": status})
    if delivery is not None:
        ns_db.record_delivery(conn, operation_id=record, photo_id=photo_id,
                              run_id=run_id, destination=dest_path, **delivery)
    if status == OPERATION_SKIPPED and dest_path:
        # A relationship to the recorded retained file is not a fresh verification.
        conn.execute("INSERT OR IGNORE INTO operation_files SELECT ?,file_id,'retained_copy' FROM file_states WHERE current_path=? AND location_role='destination' AND presence_state='present'",
                     (record,dest_path))
    if commit:
        conn.commit()


def drain_result_queue(db_thread: threading.Thread):
    """
    Waits for the writer to consume every queued result — but never forever.

    Queue.join() blocks until task_done() has been called for each item, which
    can only happen while the writer is alive. If it has died the queue can
    never drain and join() hangs until something external kills the process:
    no error, no log line, just a run that never ends. Observed exactly once in
    CI as a 300-second timeout with a clean log above it, which is precisely
    what an unobservable hang looks like.

    Checking liveness between bounded waits turns that into an immediate,
    named failure.
    """
    while True:
        with result_queue.all_tasks_done:
            if result_queue.unfinished_tasks == 0:
                return
            result_queue.all_tasks_done.wait(timeout=1.0)
            if result_queue.unfinished_tasks == 0:
                return
        if not db_thread.is_alive():
            raise RuntimeError(
                f"Database writer thread died with {result_queue.unfinished_tasks} result(s) "
                f"still queued — aborting instead of waiting forever. Check the log above for "
                f"the error that killed it."
            )


def put_result(result, db_thread: threading.Thread):
    """
    Hands a result to the writer. Same reasoning as drain_result_queue: the
    queue is bounded (DB_QUEUE_SIZE), so a dead writer makes put() block
    forever once it fills. Fails loudly instead.
    """
    while True:
        try:
            result_queue.put(result, timeout=1.0)
            return
        except queue.Full:
            if not db_thread.is_alive():
                raise RuntimeError(
                    "Database writer thread died and the result queue is full — aborting. "
                    "Check the log above for the error that killed it."
                )


# --- Database Consumer (Thread) ---
# Scan results the writer could not persist, as (path, reason). Filled by
# db_writer_worker and read by main() once the writer has been joined: a run
# whose catalog writes failed must neither report success nor go on to move
# or copy files against a catalog that does not reflect what was scanned.
writer_failures: List[tuple] = []


def db_writer_worker(db_path: str):
    """
    The Consumer: only this thread touches SQLite during scanning.

    Commits are batched (DB_COMMIT_BATCH_SIZE rows, or DB_COMMIT_INTERVAL_SECONDS
    elapsed, whichever comes first) rather than one per file. This is safe here
    in a way it would NOT be in the Move/Copy loop, because indexing only READS
    the filesystem — it writes hashes, metadata and a projected destination, and
    mutates nothing on disk. A kill mid-batch loses the uncommitted tail of scan
    RESULTS, so those files are simply not catalogued yet and the next Index
    re-reads them. There is no filesystem state for the database to disagree
    with, so the two cannot drift out of sync; the only cost is recomputation.

    Batching does not weaken duplicate detection either: the per-file lookup
    below runs on this same connection, which sees its own uncommitted rows, so
    a duplicate pair landing inside one batch is still detected.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    writer_failures.clear()
    logger.info("Database worker thread started.")

    pending_writes = 0
    last_flush = time.monotonic()
    date_sources = {DATE_SOURCE_EXIF: 0, DATE_SOURCE_MTIME: 0}
    status_counts = {}
    phash_failures = 0
    thumbnails_written = 0
    thumbnail_failures = 0

    def flush():
        """
        Commits the pending batch. NEVER raises: this is called from the
        queue-timeout and sentinel paths, which sit outside the per-row
        try/except, so an exception here would kill the writer thread — and a
        dead writer means task_done() is never called again, so the main
        thread blocks on the queue forever with nothing logged. That exact
        failure mode is why the per-row body is wrapped (see below), and why
        neither of these call sites may raise either.
        """
        nonlocal pending_writes, last_flush
        try:
            if pending_writes:
                conn.commit()
                pending_writes = 0
        except Exception as e:
            # The whole batch is lost, not just unacknowledged: roll it back so
            # the connection is usable again, and record the loss so main()
            # fails the run instead of reporting a catalog it does not have.
            with contextlib.suppress(Exception):
                conn.rollback()
            writer_failures.append((f"(batch of {pending_writes} row(s))", f"commit failed: {e}"))
            logger.error(f"DB writer failed to commit a batch of {pending_writes} row(s): {e}")
            pending_writes = 0
        last_flush = time.monotonic()

    while True:
        try:
            # The timeout is what lets a partial batch reach disk while the
            # scan is producing slowly (large RAWs). Blocking forever on get()
            # would hold finished rows in an open transaction indefinitely,
            # and the web UI polls this database for live progress.
            result = result_queue.get(timeout=DB_COMMIT_INTERVAL_SECONDS)
        except queue.Empty:
            flush()
            continue

        if result is None:
            flush()
            result_queue.task_done()
            break

        # The whole body is guarded: main()'s result_queue.join() waits for
        # task_done() on every item, so an exception escaping this loop would
        # hang the run with no error surfaced. A bad row is rolled back and
        # counted in writer_failures instead.
        try:
            # Each scan result is one unit: its catalog row and its audit entry
            # are written together or not at all. The savepoint nests inside
            # the batch transaction, so a failure undoes only this file's
            # partial writes and the rest of the batch still commits. BEGIN is
            # explicit because releasing an OUTERMOST savepoint would commit.
            if not conn.in_transaction:
                conn.execute("BEGIN")
            conn.execute("SAVEPOINT scan_row")

            # Exclude the file's own previous row ("source_path != ?") and
            # rows that are themselves Duplicate/Removed_Duplicate. Without
            # the status exclusion, re-scanning a duplicate pair would
            # cascade: each file would find the other's persisted Duplicate
            # status and count it as the original, leaving both Duplicate
            # with no anchor, so the photo could never be moved or cleaned
            # up. normalize_duplicate_groups() re-derives the final
            # classification after the scan.
            cursor.execute(
                "SELECT id FROM photos WHERE sha1_hash = ? AND source_path != ? "
                f"AND status NOT IN ({sql_values((PhotoStatus.DUPLICATE, PhotoStatus.REMOVED_DUPLICATE))})",
                (result.sha1_hash, result.file_path)
            )
            existing = cursor.fetchone()

            status = result.status
            if existing and status != PhotoStatus.FAILED:
                status = PhotoStatus.DUPLICATE

            prior_row = cursor.execute(
                "SELECT status FROM photos WHERE source_path=?", (result.file_path,)
            ).fetchone()
            prior_status = prior_row[0] if prior_row else None

            # UPSERT on source_path: re-scanning a file already catalogued (a
            # repeated Index, or Index then Move) refreshes its row in place
            # rather than violating the UNIQUE constraint.
            cursor.execute(
                """INSERT INTO photos
                   (source_path, dest_path, sha1_hash, phash, collision_group, is_master, status,
                    metadata_json, has_name_collision, file_size, file_mtime)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_path) DO UPDATE SET
                       dest_path = excluded.dest_path,
                       sha1_hash = excluded.sha1_hash,
                       phash = excluded.phash,
                       collision_group = excluded.collision_group,
                       is_master = excluded.is_master,
                       status = excluded.status,
                       metadata_json = excluded.metadata_json,
                       has_name_collision = excluded.has_name_collision,
                       file_size = excluded.file_size,
                       file_mtime = excluded.file_mtime
                """,
                (
                    result.file_path,
                    result.dest_path,
                    result.sha1_hash,
                    result.phash,
                    result.collision_group,
                    1 if result.is_master else 0,
                    status,
                    json.dumps(result.metadata),
                    1 if result.has_name_collision else 0,
                    result.file_size,
                    result.file_mtime
                )
            )

            # Audit log entry for this scan result. Looked up by source_path
            # rather than trusting cursor.lastrowid, since that's unreliable
            # across the UPDATE branch of an upsert.
            cursor.execute("SELECT id FROM photos WHERE source_path = ?", (result.file_path,))
            photo_row = cursor.fetchone()
            photo_id = photo_row[0] if photo_row else None
            file_id = ns_db.record_source_observation(
                conn, photo_id=photo_id, run_id=result.run_id,
                source_path=result.file_path, sha1_hash=result.sha1_hash,
                file_size=result.file_size, file_mtime=result.file_mtime,
                birthtime=result.birthtime, metadata=result.metadata,
                error=result.error_message, prior_status=prior_status,
                observed_at=result.observed_at,
            )

            # Content identity, which thumbnails and similarity both key on so
            # that byte-identical copies share one row. Written here rather than
            # in the worker because only this thread touches SQLite during a
            # scan, and it joins this file's savepoint so identity and thumbnail
            # state land with the catalog row or not at all.
            if result.sha1_hash:
                decoded = result.phash not in ("", "error", "not_supported", None)
                content_id = ns_db.content_for_digest(
                    conn, digest=result.sha1_hash,
                    phash=result.phash if decoded else None,
                    phash_state="ok" if decoded else (result.phash or "error"),
                    width=result.thumbnail.width if result.thumbnail else None,
                    height=result.thumbnail.height if result.thumbnail else None,
                )
                if result.thumbnail is not None:
                    ns_db.record_thumbnail(
                        conn, content_id=content_id, size=THUMBNAIL_SIZE,
                        availability=result.thumbnail.availability,
                        cache_filename=result.thumbnail.cache_filename,
                        bytes_on_disk=result.thumbnail.bytes,
                        attempted_file_id=file_id, observed_path=result.file_path,
                        failure_category=result.thumbnail.failure_category,
                        failure_detail=result.thumbnail.failure_detail,
                    )
                    if result.thumbnail.availability == "failed":
                        thumbnail_failures += 1
                    elif not result.thumbnail.reused:
                        thumbnails_written += 1
            log_operation(
                conn, result.run_id, photo_id, result.file_path, result.dest_path, status,
                result.error_message, result.has_name_collision, commit=False
            )
            conn.execute("RELEASE scan_row")

            # Counted only once the row is safely in the batch.
            source = result.metadata.get("date_source") if result.metadata else None
            if source in date_sources:
                date_sources[source] += 1
            status_counts[status] = status_counts.get(status, 0) + 1
            if result.phash in ("error", "not_supported"):
                phash_failures += 1

            pending_writes += 1
            if pending_writes >= DB_COMMIT_BATCH_SIZE or (
                time.monotonic() - last_flush >= DB_COMMIT_INTERVAL_SECONDS
            ):
                flush()
        except Exception as e:
            # Undo this row's partial writes, keep the rest of the batch, and
            # remember the failure: main() fails the run and skips the
            # physical phase rather than acting on a catalog it could not
            # update. A status the CHECK constraints reject lands here too.
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK TO scan_row")
                conn.execute("RELEASE scan_row")
            writer_failures.append((result.file_path, f"{type(e).__name__}: {e}"))
            logger.error(f"DB writer failed to record {result.file_path}: {e}")
        finally:
            result_queue.task_done()

    try:
        flush()
    except Exception as e:
        logger.error(f"DB writer failed to flush its final batch: {e}")

    # Where each file's date came from, and therefore which files the
    # container's timezone actually affected. EXIF timestamps carry no zone and
    # are used as the camera wrote them; an mtime is interpreted in local time,
    # so a photo modified late in the evening can land in the next day's folder
    # under a different TZ. Surfacing the count makes that visible per run
    # instead of being something you discover in the organized tree later.
    # One line that answers "what actually happened?" without reading the whole
    # log. A bare file count makes a scan where hundreds of files failed look
    # identical to a clean one.
    total = sum(status_counts.values())
    if total:
        breakdown = ", ".join(f"{n:,} {st.lower()}" for st, n in sorted(status_counts.items()))
        logger.info(f"Index summary: {total:,} file(s) recorded — {breakdown}.")
        failed = status_counts.get(PhotoStatus.FAILED, 0)
        if failed:
            logger.warning(
                f"{failed:,} file(s) failed and were recorded with a reason — query them with: "
                f"SELECT source_path, error_message FROM operations "
                f"WHERE status = '{PhotoStatus.FAILED}' AND run_id = (SELECT MAX(id) FROM runs);"
            )
        if phash_failures:
            logger.warning(
                f"{phash_failures:,} file(s) produced no perceptual hash (undecodable or "
                f"unsupported format). They are indexed and will move/copy normally, but "
                f"cannot participate in similarity matching."
            )
        if thumbnails_written or thumbnail_failures:
            logger.info(f"Thumbnails: {thumbnails_written:,} generated, {thumbnail_failures:,} failed.")
        if thumbnail_failures:
            logger.warning(
                f"{thumbnail_failures:,} file(s) produced no thumbnail. They are indexed and "
                f"will move/copy normally; the gallery shows a placeholder with the recorded "
                f"reason. A thumbnail is disposable cache and never fails an Index."
            )

    from_exif = date_sources[DATE_SOURCE_EXIF]
    from_mtime = date_sources[DATE_SOURCE_MTIME]
    if from_exif or from_mtime:
        logger.info(f"Date sources: {from_exif} from EXIF, {from_mtime} from file modification time.")
    if from_mtime:
        logger.warning(
            f"{from_mtime} file(s) had no usable EXIF date, so their date folder was chosen from "
            f"the file's modification time. The files themselves are not changed. Those times "
            f"are interpreted in this container's timezone (logged above) — pass -e TZ=<zone> "
            f"if the folders look a day off."
        )
    conn.close()
    logger.info("Database worker thread shut down cleanly.")


# --- Startup Recovery & Reconciliation ---
def _observe(path: Path):
    """What is actually there, distinguishing unreadable from absent."""
    try:
        return "present" if path.is_file() else "absent"
    except OSError:
        return "unreadable"


def reconcile_interrupted_state(db_path: Path, run_id: Optional[int] = None):
    """
    Settles work a previous run left mid-flight by OBSERVING, recording what it
    observed, and only then concluding.

    Every mutation records durable intent before touching a file, so interrupted
    work is an operation carrying intent and no terminal event. Recovery reads
    that intent, looks at both locations, writes an evidence row per location,
    and settles the operation against what it found.

    Four outcomes, and the two that are not simply "finished" or "never started"
    are the point of this function:

      * destination present, source gone   - the move completed; settle it.
      * destination gone, source present   - nothing was published; retry it.
      * BOTH present                       - the copy landed and the source was
        never removed. The published file is registered as its own identity and
        the operation is recorded INCOMPLETE. Recovery never deletes the source;
        an explicit Move may, after verifying both sides live.
      * BOTH gone, or either unreadable    - the outcome cannot be established.
        An attention issue is opened carrying the evidence, and the row is NOT
        reset to Pending, which would claim the file is waiting for work it can
        never receive.

    Runs at synchronous=FULL. These conclusions are drawn from evidence that may
    not be observable again - storage disappears, files are replaced - so losing
    them to a power cut is not the benign case that NORMAL assumes elsewhere.
    """
    if not db_path.exists():
        return

    logger.info("Checking database for interrupted tasks from previous runs...")
    conn = get_db_connection(str(db_path), synchronous="FULL")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='photos';")
        if not cursor.fetchone():
            return

        cursor.execute(
            f"SELECT id, source_path, dest_path, sha1_hash FROM photos "
            f"WHERE status = '{PhotoStatus.PROCESSING}'"
        )
        for record_id, src_str, dst_str, sha1 in cursor.fetchall():
            src, dst = Path(src_str), Path(dst_str)

            # Partials carry a random suffix (see _stage_copy), so they are found
            # by prefix. Only regular files are removed: a symlink at a
            # partial-looking name was not created by this engine.
            prefix = dst.name + PARTIAL_SUFFIX + "."
            orphans = []
            try:
                with os.scandir(dst.parent) as entries:
                    orphans = [e.path for e in entries
                               if e.name.startswith(prefix) and e.is_file(follow_symlinks=False)]
            except FileNotFoundError:
                pass
            for orphan in orphans:
                logger.warning(f"Found orphaned partial file: {Path(orphan).name}. Removing.")
                os.unlink(orphan)

            duplicate_removal = cursor.execute(
                f"SELECT 1 FROM photos WHERE id != ? AND sha1_hash = ? AND dest_path = ? "
                f"AND status IN ({sql_values(ANCHOR_DELIVERED_STATUSES)}) LIMIT 1",
                (record_id, sha1, dst_str)
            ).fetchone() is not None

            source_state, dest_state = _observe(src), _observe(dst)

            # One transaction per reconciled row: evidence, the settled
            # operation and the photo's new status commit together or not at
            # all. Relying on an incidental write to open one left the first
            # evidence write without a transaction whenever intent already
            # existed, which is every interrupted row now that intent is
            # recorded before the mutation.
            conn.execute("BEGIN IMMEDIATE")
            unsettled = ns_db.unsettled_operations(conn, record_id)
            operation_id = unsettled[-1][0] if unsettled else ns_db.begin_operation(
                conn, run_id=run_id, photo_id=record_id, source_path=src_str,
                dest_path=dst_str, kind="recovered_without_intent")

            for role, path, state in (("source", src_str, source_state),
                                      ("destination", dst_str, dest_state)):
                ns_db.record_evidence(conn, operation_id=operation_id, location_role=role,
                                      observed_path=path, observation_kind="stat", result=state)
            for orphan in orphans:
                ns_db.record_evidence(conn, operation_id=operation_id, location_role="partial",
                                      observed_path=orphan, observation_kind="stat",
                                      result="present", details={"removed": True})

            if "unreadable" in (source_state, dest_state) or (
                    source_state == "absent" and dest_state == "absent"):
                # Neither guess is honest. The source is gone or unexaminable and
                # nothing verifiable stands at the destination, so this run cannot
                # say whether the photo was delivered.
                final = PhotoStatus.FAILED
                note = (f"Recovery could not establish what happened: the source is "
                        f"{source_state} and the destination is {dest_state}. The file's "
                        f"recorded history is kept and this needs attention.")
                ns_db.settle_operation(conn, operation_id, status=final, step="recovery",
                                       outcome="unestablished", error_message=note)
                evidence_ids = [r[0] for r in conn.execute(
                    "SELECT evidence_id FROM operation_evidence WHERE operation_id=?",
                    (operation_id,))]
                ns_db.open_attention_issue(
                    conn, operation_id=operation_id, category="unestablished_outcome",
                    summary=note,
                    file_id=(conn.execute("SELECT file_id FROM photo_files WHERE photo_id=?",
                                          (record_id,)).fetchone() or [None])[0],
                    evidence_ids=evidence_ids)
            elif dest_state == "present" and source_state == "absent":
                final = PhotoStatus.REMOVED_DUPLICATE if duplicate_removal else PhotoStatus.COMPLETED
                note = (f"Recovered after an interrupted run: the source is gone and the "
                        f"destination copy is present at {dst}.")
                ns_db.settle_operation(conn, operation_id, status=final, step="recovery",
                                       outcome="completed", error_message=note)
            elif dest_state == "present" and source_state == "present":
                # The copy landed; the source was never removed. Two real files,
                # one logical relocation. Register the published file as its own
                # identity and leave the Move incomplete - the source stays
                # eligible for an explicit Move that verifies both sides live.
                final = PhotoStatus.DUPLICATE if duplicate_removal else PhotoStatus.PENDING
                note = ("File delivered; source not removed. The destination copy is present "
                        "and the source is still here, so the Move did not finish. Run Move "
                        "again for this source to verify both copies and remove it.")
                if not duplicate_removal:
                    # created= must describe what recovery OBSERVED, not assert an
                    # event. The crashed run published this file; whether it also
                    # RECORDED it decides the flag. If a destination identity
                    # already exists, passing created=True would apply the
                    # "a fresh publication proves the previous occupant absent"
                    # rule to a file nothing replaced - superseding a live
                    # identity and minting a duplicate for the same bytes.
                    already_recorded = conn.execute(
                        "SELECT 1 FROM file_states WHERE current_path=? AND location_role='destination' "
                        "AND presence_state='present'", (dst_str,)).fetchone() is not None
                    with contextlib.suppress(ns_db.SchemaError):
                        ns_db.record_delivery(conn, operation_id=operation_id, photo_id=record_id,
                                              run_id=run_id, destination=dst_str,
                                              source_removed=False, created=not already_recorded,
                                              sha1_hash=sha1)
                ns_db.settle_operation(conn, operation_id, status=final, step="move",
                                       outcome="incomplete", error_message=note)
            else:
                final = PhotoStatus.DUPLICATE if duplicate_removal else PhotoStatus.PENDING
                note = ("Recovered after an interrupted run: nothing was published at the "
                        "destination, so it will be retried.")
                ns_db.settle_operation(conn, operation_id, status=final, step="recovery",
                                       outcome="not_started", error_message=note)

            # The repair belongs to the run that performed it, linked to the
            # operation it repairs. The interrupted operation keeps its own
            # settled outcome and its evidence; this row is what a reader sees
            # when asking what THIS run did, and reconciles_operation_id is what
            # keeps requested work and recovery separable.
            recovery_id = ns_db.begin_operation(
                conn, run_id=run_id, photo_id=record_id, source_path=src_str,
                dest_path=dst_str, kind="recovery", reconciles=operation_id)
            ns_db.settle_operation(conn, recovery_id, status=final, step="recovery",
                                   outcome="recorded", error_message=note)
            cursor.execute("UPDATE photos SET status = ? WHERE id = ?", (final, record_id))
            conn.commit()
            logger.info(f"Reconciled interrupted record {record_id} as {final}.")

        # A run killed uncatchably never reaches finish_run(), so its row stays
        # Running with no end time. This process holds the single-instance lock,
        # so no other run can still be alive: mark them Crashed.
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='runs';")
        if cursor.fetchone():
            conn.execute("BEGIN IMMEDIATE")
            cursor.execute("SELECT id FROM runs WHERE status = ? AND id != ?",
                           (RunStatus.RUNNING, run_id if run_id is not None else -1))
            # Deliberately not `run_id`: rebinding the loop variable would destroy
            # the reconciling run's own id, which the evidence above is written
            # against.
            for (crashed_run_id,) in cursor.fetchall():
                logger.warning(f"Run #{crashed_run_id} was left 'Running' by an unclean "
                               f"shutdown - marking Crashed.")
                cursor.execute("UPDATE runs SET status = ?, ended_at = ? WHERE id = ?",
                               (RunStatus.CRASHED, datetime.now().isoformat(), crashed_run_id))
            conn.commit()
    except BaseException:
        # Never swallowed. A failed reconciliation leaves rows Processing, and a
        # run that continued would treat an unsettled catalog as settled.
        conn.rollback()
        logger.error("Startup state reconciliation failed; the catalog was not settled.",
                     exc_info=True)
        raise
    finally:
        conn.close()


# --- Pre-Flight Space Validation ---
def _nearest_existing_dir(path: Path) -> Path:
    """
    Walks up until it finds a directory that actually exists. Used to ask the
    filesystem about free space on the volume a not-yet-created path will
    land on, without creating anything to find out.
    """
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return Path(path.anchor or '.')


def verify_sufficient_disk_space(dest_path: Path, required_bytes: int,
                                 safety_margin_mb: int = 500) -> tuple:
    """
    Checks whether the destination volume has room for `required_bytes`.

    Returns (ok, free_bytes, needed_bytes) rather than a bare bool, so a
    caller can record what was required against what was available — a
    shortfall is a run-level failure, and "not enough space" with no figures
    is not something a user can act on.

    Strictly read-only: asking whether there is room must not create anything,
    or a run that then aborts for insufficient space leaves directory trees
    behind. Free space is a property of the VOLUME, so querying the nearest
    existing ancestor answers the same question without writing. The real
    destination directories are created when a file is actually written
    (copy_verify_delete).
    """
    stat = shutil.disk_usage(_nearest_existing_dir(dest_path))
    buffer_bytes = safety_margin_mb * 1024 * 1024
    total_needed = required_bytes + buffer_bytes

    if stat.free < total_needed:
        required_gb = required_bytes / (1024 ** 3)
        free_gb = stat.free / (1024 ** 3)
        logger.error(
            f"Insufficient disk space on destination! "
            f"Required: {required_gb:.2f} GB (+{safety_margin_mb}MB safety buffer), "
            f"Available: {free_gb:.2f} GB."
        )
        return False, stat.free, total_needed
    return True, stat.free, total_needed


# --- Helper Functions ---
def parse_exif_date(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(str(value)[:19], '%Y:%m:%d %H:%M:%S')
    except (ValueError, TypeError):
        return None


# --- Persistent Per-Worker ExifTool Process ---
# ProcessPoolExecutor spawns separate OS processes, so a single shared
# ExifTool instance can't be passed between them. Instead, each worker
# process gets its OWN persistent ExifTool subprocess, started once (via
# ProcessPoolExecutor's `initializer=`) and reused for every file that
# worker handles — this is what actually delivers the performance win:
# avoiding a fresh subprocess spawn per FILE, not per worker. Verified via
# direct timing: a repeat query against an already-running instance took
# ~2.6ms vs ~24ms+ for one paying process-spawn overhead — roughly a 10x
# difference that compounds across a large library.
_worker_exiftool: Optional["pyexiftool.ExifToolHelper"] = None

# Consecutive ExifTool failures in this worker. The self-healing respawn below
# is worth doing for a one-off bad file, but repeating it forever is not: if
# ExifTool is broken in this process rather than confused by one image, every
# subsequent file pays a terminate-and-respawn — silently, since the failure
# was logged at DEBUG. That cost a real library run 4.75 seconds PER FILE with
# the CPU almost idle (112% of 2400% available) and not one line in the log to
# explain it. After this many consecutive failures the worker stops trying and
# falls through to the PIL path, which is the documented fallback anyway.
_worker_exiftool_failures = 0
MAX_CONSECUTIVE_EXIFTOOL_FAILURES = 3


def _init_worker_process(exiftool_supported: bool, log_dir: Optional[str] = None):
    """
    ProcessPoolExecutor initializer — runs once when each worker process
    starts, before it's given any files. Sets up this worker's logging and
    its persistent ExifTool instance, and registers cleanup so the ExifTool
    subprocess doesn't outlive its parent worker.

    Logging is configured explicitly here rather than relying on the worker
    inheriting the parent's handlers, because that inheritance only happens
    under the `fork` start method. Verified directly: a forked worker sees
    the parent's handlers and its records reach organizer.log, but a spawned
    worker has ZERO handlers, so every logger call falls through to
    logging.lastResort — printed bare to stderr, never written to the log
    file at all. That is the default on macOS (since 3.8) and Windows, and
    CPython is moving Linux off plain `fork` as well, so worker-side
    diagnostics would silently disappear from the log exactly where they are
    hardest to reproduce.
    """
    global _worker_exiftool
    if log_dir:
        configure_logging(Path(log_dir))
    if not exiftool_supported:
        return
    try:
        _worker_exiftool = pyexiftool.ExifToolHelper(
            common_args=[]  # deliberately override PyExifTool's default
                             # ["-G", "-n"] (grouped tag names + raw numeric
                             # values) to match the flat-key, human-readable
                             # output the rest of this module already parses
                             # (extract_date_from_metadata expects a bare
                             # "DateTimeOriginal" key, not "EXIF:DateTimeOriginal"),
                             # and so metadata_json's shape doesn't silently
                             # change for anything already reading it.
        )
    except Exception:
        _worker_exiftool = None
    import atexit
    atexit.register(_shutdown_worker_exiftool)


def _shutdown_worker_exiftool():
    """Terminates this worker's persistent ExifTool subprocess on normal exit."""
    global _worker_exiftool
    if _worker_exiftool is not None:
        try:
            # Bounded: ProcessPoolExecutor's shutdown waits for every worker,
            # and this runs via atexit in each of them, so an ExifTool process
            # that will not exit stalls the whole run's teardown. PyExifTool's
            # default is a 30 s wait per instance.
            _worker_exiftool.terminate(timeout=5)
        except Exception:
            pass
        _worker_exiftool = None


def get_full_exif_via_exiftool(file_path: Path) -> Optional[dict]:
    """
    Returns the COMPLETE tag set ExifTool can extract for this file, as a
    dict, or None if ExifTool isn't available / fails / returns nothing.
    This is deliberately the full tag set rather than a curated subset,
    storing everything now means EXIF inspection/editing doesn't
    need to re-scan the whole library later to get fields nobody thought to
    whitelist today.

    Uses this worker process's persistent ExifTool instance (see
    _init_worker_process) instead of spawning a subprocess per file.
    """
    global _worker_exiftool, _worker_exiftool_failures
    if _worker_exiftool is None:
        return None
    try:
        result = _worker_exiftool.get_metadata([str(file_path)])
        if result and isinstance(result, list):
            _worker_exiftool_failures = 0   # consecutive, not cumulative
            return result[0]
    except Exception as e:
        _worker_exiftool_failures += 1

        # WARNING, not DEBUG. This path costs a process teardown and respawn
        # per file; a run that silently spends seconds per file on it looks
        # like a mysteriously slow scan with a clean log, which is exactly how
        # it presented on a real library.
        logger.warning(
            f"ExifTool extraction failed for {file_path.name} "
            f"(failure {_worker_exiftool_failures} of {MAX_CONSECUTIVE_EXIFTOOL_FAILURES} "
            f"before this worker gives up on it): {e}"
        )

        try:
            # Bounded. PyExifTool's terminate() waits up to 30s by default,
            # which is indistinguishable from a hang when it happens per file.
            try:
                _worker_exiftool.terminate(timeout=5)
            except TypeError:
                _worker_exiftool.terminate()
        except Exception:
            pass

        if _worker_exiftool_failures >= MAX_CONSECUTIVE_EXIFTOOL_FAILURES:
            # Broken in this process, not confused by one file. Stop paying the
            # respawn on every remaining file and use the PIL fallback.
            logger.error(
                f"ExifTool has failed {_worker_exiftool_failures} times consecutively in this "
                f"worker — disabling it here and falling back to PIL for metadata. Dates and "
                f"camera details will still be read where PIL can supply them, but the full tag "
                f"set will be missing and RAW files cannot be read at all."
            )
            _worker_exiftool = None
            return None

        try:
            _worker_exiftool = pyexiftool.ExifToolHelper(common_args=[])
        except Exception as spawn_error:
            logger.error(f"Could not restart ExifTool in this worker: {spawn_error}")
            _worker_exiftool = None
    return None


def get_exif_via_pil(file_path: Path) -> Optional[dict]:
    """
    Per-file fallback for when ExifTool is running but yields nothing usable
    for this particular file. Converts PIL's raw numeric-tag-id EXIF dict into
    a named-tag dict using PIL's own tag name table, so the stored JSON is
    human-readable either way this function is reached. Only works for formats
    PIL can open (not RAW).

    img.getexif() returns only the top-level "0th" IFD (Make, Model and
    similar); it does NOT expand the "Exif" sub-IFD at tag 0x8769 /
    "ExifOffset", which is where DateTimeOriginal, ISO, FNumber and
    ExposureTime actually live. That sub-IFD must be fetched explicitly via
    get_ifd(0x8769), or date resolution and camera-settings capture fail here
    even when the file carries the data, and the date falls back to mtime.
    """
    if not PIL_SUPPORTED:
        return None
    try:
        from PIL.ExifTags import TAGS
        with Image.open(file_path) as img:
            exif_data = img.getexif()
            if not exif_data:
                return None
            result = {TAGS.get(tag, str(tag)): str(value) for tag, value in exif_data.items()}
            try:
                exif_ifd = exif_data.get_ifd(0x8769)  # the "Exif" sub-IFD
                if exif_ifd:
                    result.update({TAGS.get(tag, str(tag)): str(value) for tag, value in exif_ifd.items()})
            except Exception:
                pass
            return result if result else None
    except Exception as e:
        logger.debug(f"PIL EXIF read failed on {file_path.name}: {e}")
        return None


def extract_date_from_metadata(metadata: dict) -> Optional[datetime]:
    """Pulls a usable 'date taken' out of whichever metadata dict was captured."""
    for key in ("DateTimeOriginal", "CreateDate", "DateTime"):
        if key in metadata:
            parsed = parse_exif_date(metadata[key])
            if parsed:
                return parsed
    return None


def get_metadata_and_date(file_path: Path) -> tuple:
    """
    Metadata Extraction Fallback Chain (see module docstring for the full
    rationale): ExifTool -> PIL -> file mtime. Returns (datetime, metadata
    dict) together, both sourced from one underlying capture rather than two
    separate passes.

    ExifTool is a hard requirement for the engine to start at all (see module
    docstring), so the PIL/mtime steps do not cover for it being missing —
    that cannot happen. They are a defensive per-FILE fallback for the
    narrower case where
    ExifTool is genuinely running but fails on one specific file (corrupted
    data, an unusual format edge case) — the persistent process itself
    already self-heals from that in get_full_exif_via_exiftool(); this is
    the next layer down if a file just doesn't yield usable metadata at all.
    """
    def _mtime_fallback(meta: dict) -> tuple:
        meta["date_source"] = DATE_SOURCE_MTIME
        return datetime.fromtimestamp(os.path.getmtime(file_path)), meta

    metadata = get_full_exif_via_exiftool(file_path)
    if metadata:
        dt = extract_date_from_metadata(metadata)
        if dt:
            metadata["date_source"] = DATE_SOURCE_EXIF
            return dt, metadata
        # ExifTool ran but found no usable date tag — still keep whatever
        # metadata it did find, just fall through for the date itself.
        return _mtime_fallback(metadata)

    metadata = get_exif_via_pil(file_path)
    if metadata:
        dt = extract_date_from_metadata(metadata)
        if dt:
            metadata["date_source"] = DATE_SOURCE_EXIF
            return dt, metadata
        return _mtime_fallback(metadata)

    # Neither source found anything at all.
    return _mtime_fallback({})


def compute_sha1(file_path: str) -> str:
    def _hash():
        h = hashlib.sha1()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(SHA1_CHUNK_SIZE), b''):
                h.update(chunk)
        return h.hexdigest()
    return retry_io_operation(f"SHA1 Hash {file_path}", _hash)


@contextlib.contextmanager
def warnings_attributed_to(file_path: str):
    """
    Captures library warnings raised while reading one file and re-logs them
    naming that file.

    Two problems this solves:

    1. The warnings arrive with no indication of WHICH file produced them — on
       a 29,000-file library that is an alarm with no address.

    2. The wording is actively misleading. PIL's "Truncated File Read" is
       raised by ImageFile._safe_read as an OSError, then caught and
       downgraded to a warning by TiffImagePlugin's EXIF IFD parser
       (ImageFileDirectory_v2.load). It therefore means "the EXIF metadata
       block is malformed", NOT "the image is truncated" — the parser
       returns early and the pixel data decodes normally. Files that emit
       this warning still produce a correct SHA-1 and a correct pHash; the
       only loss is EXIF tags after the bad one, which can push a photo onto
       its mtime for dating. Saying "metadata warning" keeps that straight.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield
    for w in caught:
        logger.warning(f"{w.category.__name__} metadata warning for {file_path}: {w.message}")


def compute_phash(file_path: str) -> str:
    if not IMAGEHASH_SUPPORTED:
        return "not_supported"

    ext = Path(file_path).suffix.lower()

    # RAW-family formats need rawpy to decode at all — PIL can't open
    # them. Demosaic at half_size for speed, since a perceptual hash only
    # needs a coarse visual fingerprint, not full resolution.
    if ext in RAW_EXTENSIONS:
        if not (RAWPY_SUPPORTED and PIL_SUPPORTED):
            return "not_supported"
        try:
            with warnings_attributed_to(file_path):
                with rawpy.imread(file_path) as raw:
                    rgb = raw.postprocess(
                        use_camera_wb=True, half_size=True, no_auto_bright=True, output_bps=8
                    )
                img = Image.fromarray(rgb)
                return str(imagehash.phash(img))
        except Exception as e:
            logger.debug(f"rawpy pHash failed for {file_path}: {e}")
            return "error"

    if not PIL_SUPPORTED:
        return "not_supported"
    try:
        with warnings_attributed_to(file_path):
            with Image.open(file_path) as img:
                return str(imagehash.phash(img))
    except Exception as e:
        logger.debug(f"PIL pHash failed for {file_path}: {e}")
        return "error"


class ThumbnailWriteError(Exception):
    """The cache could not be written — distinct from the photo failing to decode.

    Both surface as OSError, and they mean opposite things to a user: one is a
    full or read-only /cache, the other is a damaged photo. The UI shows
    different placeholder text for each (webui-spec.md 4.2.1), so the engine has
    to tell them apart rather than recording a generic failure.
    """


def thumbnail_cache_path(cache_root, sha1_hash: str, size: int = THUMBNAIL_SIZE) -> Path:
    """
    Where one content's thumbnail lives: <cache>/thumbnails/<ab>/<sha1>.jpg.

    Fanned out by the hash's first two characters so no directory holds tens of
    thousands of flat entries, and keyed by content hash rather than catalog id
    or path — so byte-identical duplicates share one file, and the cache
    survives a catalog rebuild where row ids would not.

    The grid size keeps the bare `<sha1>.jpg` name the README documents; any
    other size is suffixed. Without that, the 320px grid thumbnail and the
    1024px detail preview — separate rows, since thumbnail_cache is keyed on
    (content_id, size) — would collide on a single filename.
    """
    name = f"{sha1_hash}.jpg" if size == THUMBNAIL_SIZE else f"{sha1_hash}-{size}.jpg"
    return Path(cache_root) / THUMBNAIL_DIR_NAME / sha1_hash[:2] / name


def _write_thumbnail(img, dest: Path, size: int) -> int:
    """Downscale and write one JPEG atomically; returns its size in bytes.

    Written under a temporary name and renamed into place, so a killed engine
    never leaves a truncated JPEG that a later run would find and reuse as a
    cache hit — the reuse check trusts existence, and a half-written file would
    be silently wrong forever.
    """
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    # The real decode happens here, not at open(): a truncated or damaged photo
    # raises from this call, which is why it sits OUTSIDE the write guard below.
    img.thumbnail((size, size), Image.LANCZOS)
    tmp = dest.with_name(dest.name + THUMBNAIL_PARTIAL_SUFFIX)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(tmp, "JPEG", quality=THUMBNAIL_JPEG_QUALITY, optimize=True)
        os.replace(tmp, dest)
        return dest.stat().st_size
    except OSError as e:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise ThumbnailWriteError(str(e)) from e


def _raw_preview(raw, size: int):
    """
    The adaptive RAW rule: probe the embedded preview, use it when its longest
    edge is at least the target, otherwise demosaic.

    A camera's embedded preview is the cheap path — about 17.8ms against 268ms
    to demosaic — but a preview existing is not enough: it must be large enough,
    or upscaling it would look worse than a fresh render. Probing and failing
    costs about 0.4ms, 0.15% of a demosaic, so the probe is effectively free and
    the rule self-tunes to whatever library it meets instead of baking in a
    threshold. In one 300-file sample only 26% of RAWs carried a usable preview
    at 320px, split almost entirely by format — so both paths are live.
    """
    try:
        thumb = raw.extract_thumb()
    except Exception:
        thumb = None
    if thumb is not None:
        try:
            if thumb.format == rawpy.ThumbFormat.JPEG:
                preview = Image.open(io.BytesIO(thumb.data))
            else:
                preview = Image.fromarray(thumb.data)
            if max(preview.size) >= size:
                # The embedded preview is stored unrotated, carrying its own
                # orientation tag — measured landscape on a Rotate 90 CW file.
                # The demosaic below needs NO such call: LibRaw applies the
                # sensor flip itself, so transposing that would turn it twice.
                # A quarter turn does not change the longest edge, so the
                # size check above is unaffected by where this sits.
                return ImageOps.exif_transpose(preview)
        except Exception:
            pass  # Unreadable preview is not a failure; fall through and render one.
    # half_size halves each dimension during demosaic, which is far cheaper and
    # still far larger than any thumbnail target. compute_phash() does the same.
    rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True, output_bps=8)
    return Image.fromarray(rgb)


def generate_thumbnail(file_path: Path, sha1_hash: str, cache_root: str,
                       size: int = THUMBNAIL_SIZE) -> ThumbnailResult:
    """
    Produce the grid thumbnail for one file. READS the photo and NEVER raises.

    A thumbnail is disposable cache, so nothing here may fail an otherwise
    successful Index (webui-spec.md 4.2.1). Every failure comes back as a
    recorded category and detail, which the UI turns into placeholder text —
    "Photo file unavailable", "Image could not be decoded" — rather than a
    blank tile with no explanation. A generic decoder failure is NOT evidence
    of corruption and is not reported as such.
    """
    dest = thumbnail_cache_path(cache_root, sha1_hash, size)
    relative = str(dest.relative_to(Path(cache_root)))

    # A cache hit is the point of keying on content: exact duplicates, including
    # copies in unrelated directories, reuse one render instead of each doing
    # their own. This is also what makes a re-Index nearly free.
    try:
        existing = dest.stat()
        if existing.st_size > 0:
            return ThumbnailResult(availability="present", cache_filename=relative,
                                   bytes=existing.st_size, reused=True)
    except OSError:
        pass

    if not PIL_SUPPORTED:
        return ThumbnailResult(availability="failed", failure_category="decoder_unavailable",
                               failure_detail="Pillow is not installed")

    width = height = None
    try:
        with warnings_attributed_to(str(file_path)):
            if file_path.suffix.lower() in RAW_EXTENSIONS:
                if not RAWPY_SUPPORTED:
                    return ThumbnailResult(
                        availability="failed", failure_category="decoder_unavailable",
                        failure_detail="rawpy is not installed; RAW files cannot be decoded")
                with rawpy.imread(str(file_path)) as raw:
                    # sizes.width/height are PRE-flip: a portrait shot reports
                    # landscape here, because they describe the sensor rather
                    # than the photograph. LibRaw flip 5 and 6 are the quarter
                    # turns, so swap for those to record the shape the photo is
                    # actually displayed at.
                    width, height = int(raw.sizes.width), int(raw.sizes.height)
                    if raw.sizes.flip in (5, 6):
                        width, height = height, width
                    written = _write_thumbnail(_raw_preview(raw, size), dest, size)
            else:
                with Image.open(file_path) as img:
                    # Read the dimensions BEFORE draft(): draft() replaces the
                    # image with a reduced-scale decode, so img.size afterwards
                    # is the decode size, not the photograph's real dimensions —
                    # and these are recorded on `contents` as facts about the
                    # content.
                    width, height = img.size
                    # A portrait photo is very often stored landscape with an
                    # EXIF orientation tag telling the viewer to rotate it. The
                    # dimensions that describe the CONTENT are the ones it is
                    # displayed at, so swap them for the quarter-turn values —
                    # otherwise every rotated photo in the library is recorded
                    # with its width and height the wrong way round.
                    orientation = img.getexif().get(0x0112, 1)
                    if orientation in (5, 6, 7, 8):
                        width, height = height, width
                    # Decodes AT a reduced scale rather than decoding fully and
                    # throwing most of it away: 8.2ms against 13.5ms.
                    img.draft("RGB", (size, size))
                    # Image.open() does NOT apply the orientation tag, but
                    # browsers and viewers do. Without this the thumbnail is
                    # rotated a quarter turn against the photo it represents —
                    # measured at 20.1% of a real library. Applied after draft()
                    # so the reduced-scale decode is still what gets rotated.
                    written = _write_thumbnail(ImageOps.exif_transpose(img), dest, size)
    except ThumbnailWriteError as e:
        return ThumbnailResult(availability="failed", failure_category="cache_write_failed",
                               failure_detail=f"Thumbnail cache could not be written: {e}",
                               width=width, height=height)
    except FileNotFoundError:
        return ThumbnailResult(availability="failed", failure_category="file_unavailable",
                               failure_detail="Photo file unavailable", width=width, height=height)
    except PermissionError:
        return ThumbnailResult(availability="failed", failure_category="permission_denied",
                               failure_detail="Permission denied reading photo",
                               width=width, height=height)
    except Exception as e:
        logger.debug(f"Thumbnail generation failed for {file_path}: {e}")
        return ThumbnailResult(availability="failed", failure_category="decode_failed",
                               failure_detail=f"Image could not be decoded ({type(e).__name__})",
                               width=width, height=height)

    return ThumbnailResult(availability="present", cache_filename=relative, bytes=written,
                           width=width, height=height)


def get_unique_dest_path(target_path: Path) -> Path:
    """Thin wrapper kept for callers that only want a free name, no content check."""
    resolved, _ = resolve_destination(target_path, None)
    return resolved


def resolve_destination(target_path: Path, expected_sha1: Optional[str]) -> tuple:
    """
    Finds where this file should actually be written, returning
    (path, already_present).

    Walks the numeric-suffix chain (name.jpg -> name_1.jpg -> name_2.jpg ...)
    until it finds a free name. If `expected_sha1` is given and one of the
    OCCUPIED candidates already holds exactly that content, that file IS this
    photo — already delivered by an earlier run — and it is returned with
    already_present=True so the caller can skip rewriting it.

    That content check is what makes re-runs idempotent. Without it an
    Index -> Copy -> Index -> Copy cycle multiplies identical files: the
    re-index resets the row to Pending, the destination name is already taken
    by the copy the previous cycle delivered, so the next copy writes
    IMG_0001_1.jpg beside it, then IMG_0001_2.jpg, and so on every cycle.

    Suffixes are always built from the ORIGINAL stem, so a collision yields
    IMG_0001_3.jpg rather than a name that grows a segment each time
    (IMG_0001_1_2_3.jpg).
    """
    candidate = target_path
    counter = 1
    while candidate.exists():
        if expected_sha1 and _sha1_of(candidate) == expected_sha1:
            return candidate, True
        candidate = target_path.parent / f"{target_path.stem}_{counter}{target_path.suffix}"
        counter += 1
    return candidate, False


def _sha1_of(path: Path) -> Optional[str]:
    """SHA-1 of an existing file, or None if it can't be read. Never raises."""
    try:
        return compute_sha1(str(path))
    except Exception:
        return None


def _path_prefix_clause(root: Path) -> tuple:
    """
    Builds the (sql_fragment, params) matching a directory and everything
    beneath it, compared as literal, case-sensitive text.

    A range comparison rather than LIKE. LIKE reads '_' and '%' as wildcards,
    so "My_Photos" matched "MyXPhotos"; and it ignores ASCII case, so "Album"
    matched "album" — two different folders on a case-sensitive filesystem.
    Under --move either one deletes sources outside the selection.

    Under TEXT's default BINARY collation, every path beneath `root/` sorts at
    or after `root/` and strictly before `root0`, because '0' is the character
    immediately after '/'. The half-open range is therefore exact, needs no
    escaping, and can use the index on source_path. (Paths are POSIX here: the
    engine already depends on fcntl.)
    """
    root_str = str(root)
    return (
        " AND (source_path = ? OR (source_path >= ? AND source_path < ?))",
        [root_str, root_str + "/", root_str + "0"],
    )


def _targeting_predicate(args) -> tuple:
    """
    Returns (sql_fragment, params) narrowing a `photos` query to whatever this
    run was scoped to — a --file-ids list, a --source-subdir prefix, or the
    whole library — and always to this run's own --source root. The fragment
    is written to be appended after an existing WHERE clause.

    Single source of truth deliberately: the Pending sweep, duplicate cleanup
    and the repoint must agree on what "this run" covers. The root bound
    matters because one catalog can hold rows from several source roots; an
    unbounded full run acted on every Pending row in the catalog, so moving
    one root also moved another's photos.
    """
    root = Path(args.source).resolve()
    if args.source_subdir:
        # Validated in main() to lie under --source, so it is the tighter bound.
        return _path_prefix_clause((root / args.source_subdir).resolve())
    clause, params = _path_prefix_clause(root)
    if args.file_ids:
        placeholders = ','.join('?' * len(args.file_ids))
        return clause + f" AND id IN ({placeholders})", params + list(args.file_ids)
    return clause, params


# --- Copy-Verify-Delete Core Protocol ---
class SourceRemovalRefused(Exception):
    """
    Raised when a source file must NOT be deleted even though its content
    matched. Deliberately not an OSError, so retry_io_operation() never
    retries it: "this is the same file" and "this changed" are not transient.
    """


def _file_identity(path) -> tuple:
    """(device, inode, size, mtime_ns) — enough to notice a file was replaced or edited."""
    st = os.stat(path)
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _fsync_file(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory(directory):
    """
    Makes a directory's entries durable, tolerating filesystems without
    directory fsync.

    EINVAL/ENOTSUP mean the operation is ABSENT rather than failed, so the move
    proceeds. But the power-loss guarantee is correspondingly weaker there, and
    saying so only in the spec left a user on exFAT or an odd network mount to
    infer it: the run itself was silent.

    Reported once per RUN, naming the first directory that reported it. Once
    per directory would be a line per date folder on a real library, which is
    how a warning becomes noise and then becomes ignored.
    """
    global _unsupported_dir_fsync_reported
    fd = os.open(str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    except OSError as e:
        if e.errno in _DIR_FSYNC_UNSUPPORTED_ERRNOS:
            if not _unsupported_dir_fsync_reported:
                _unsupported_dir_fsync_reported = True
                logger.warning(
                    f"{directory} is on a filesystem that cannot fsync directories "
                    f"({errno.errorcode.get(e.errno, e.errno)}). Directory entries there are "
                    f"not made durable, so a power loss can lose a file that was written and "
                    f"verified — a weaker guarantee than --move gives elsewhere, and the "
                    f"reason it is tolerated rather than refused (engine-spec.md 4.2). "
                    f"Reported once per run."
                )
            return
        # Says what could not be established, rather than surfacing a bare
        # "[Errno 5] Input/output error" that a user cannot act on. The errno
        # is preserved for anything matching on it.
        raise OSError(e.errno, f"{directory} could not be made durable: "
                               f"{e.strerror or e}") from e
    finally:
        os.close(fd)


# The run's --dest, and the directories whose entry in their parent this
# process has already persisted. Both are per-run state: a fresh process has
# verified nothing, so it re-establishes every barrier rather than trusting
# directories that a failed attempt left behind. Nothing is written to the
# destination to track this — a restart re-deriving it gives the same
# guarantee without putting engine bookkeeping in the user's library.
_destination_root: Optional[Path] = None
_verified_directories: set = set()

# Whether this run has already said that the filesystem cannot fsync
# directories. Per-run for the same reason as the two above: each run should
# tell its own user about its own storage, so a long-lived process does not
# stay quiet for every run after the first.
_unsupported_dir_fsync_reported: bool = False


def _mkdir_durable(directory: Path):
    """
    Creates `directory` and persists the entry of every directory along the
    way, from the destination root down.

    fsync on a file does not persist the entry naming it in its parent — that
    is why publishing fsyncs the destination directory — and the same is true
    of each folder created on the way down. Syncing only the deepest one
    leaves the first photo of a new day durable inside a day folder whose own
    entry in the month folder never reached disk: after a power loss the copy
    is unreachable, and in --move the source is already gone.

    The walk itself is _fsync_chain_to_root, which is also called at the
    deletion gate — creating a directory is not the only moment the chain has
    to hold.
    """
    directory.mkdir(parents=True, exist_ok=True)
    _fsync_chain_to_root(directory)


def _fsync_chain_to_root(directory: Path):
    """
    Persists the entry of every directory from `directory` up to --dest,
    skipping any already known durable in this run.

    Separate from _mkdir_durable because a source is also deleted against a
    copy an EARLIER run delivered, and that run's mkdir is no evidence its
    entries reached disk. _remove_verified_source calls this at the single
    deletion gate, so a caller cannot establish the barrier for itself or
    forget to — which is precisely how it came to be missing on two of the
    three deletion paths.

    Existence is not durability. A directory exists the moment mkdir returns,
    which is before its entry is durable in its parent — so a failed sync that
    leaves its directories behind must not let the next file treat them as
    established. Each entry is therefore recorded as verified only when its
    fsync SUCCEEDS; a failure leaves it outstanding, and the next call — in
    this run or after a restart — tries again and refuses the move until it
    holds.

    Keyed on the child rather than the parent, because a parent that was
    verified when one month folder appeared is dirty again when the next one
    does. Costs one fsync per folder whose entry is not yet known durable:
    once per new date folder in a run, not once per file. A caller that has
    already established the chain pays nothing.
    """
    root = _destination_root
    if root is None:
        # No run context (a direct call): persist the immediate entry only.
        _fsync_directory(directory.parent)
        return

    chain = []
    probe = directory
    reached_root = False
    while probe.parent != probe:
        if probe == root:
            reached_root = True
            break
        chain.append(probe)
        probe = probe.parent

    if not reached_root:
        # This destination is not under the run's --dest. _destination_for
        # falls back to a row's stored path when it has no usable recorded
        # date, and that path was computed against whatever --dest was current
        # when the row was written. Persist the immediate entry and nothing
        # above it: walking on would fsync directories outside the destination
        # the engine was given, which can fail on permissions and refuse a
        # legitimate move, or quietly persist someone else's directories.
        _fsync_directory(directory.parent)
        return

    for child in reversed(chain):  # shallowest first: each entry in the parent that holds it
        if str(child) in _verified_directories:
            continue
        _fsync_directory(child.parent)
        _verified_directories.add(str(child))


def _remove_verified_source(source: Path, verified_copy: Path, source_identity: tuple,
                            description: str):
    """
    The ONLY place a user's source file is deleted.

    Every caller has already compared live hashes of the source and the copy.
    That is necessary and not sufficient, so this refuses the deletion unless
    three more things hold, and fails closed on any doubt:

    1. The copy is a DIFFERENT file. Two paths can name one file — one folder
       mounted at both source and destination, a bind mount, a hard link — and
       then the hash comparison compared the file with itself; deleting the
       "source" deletes the only copy. samefile() compares device and inode.
       It cannot see two separate network mounts of one export, which is why
       overlapping storage remains documented as unsupported, but it catches
       every alias the kernel can identify.
    2. The copy is DURABLE. Verification may have read it back from page
       cache. On a network source the server commits the delete as soon as
       the call returns, so a local power loss before the copy reached disk
       would leave no copy anywhere. The copy and its own directory entry are
       fsynced here, and so is every entry above it up to --dest
       (_fsync_chain_to_root).

       The chain is established HERE, at the gate, not left to the caller.
       Only one of the three callers copies the file itself and so passes
       through _mkdir_durable; the other two delete against a copy an earlier
       run delivered, and that run's mkdir proves nothing — a directory exists
       the moment mkdir returns, which is before its entry is durable in its
       parent. A caller that already established the chain pays nothing, since
       the verified set is consulted first.
    3. The source is still the file that was verified. An edit or replacement
       after its hash was taken means the copy holds OLD content, and
       deleting the source would destroy the new content.
    """
    try:
        same = os.path.samefile(source, verified_copy)
    except OSError as e:
        raise SourceRemovalRefused(
            f"could not confirm the copy is a separate file ({type(e).__name__}: {e})")
    if same:
        raise SourceRemovalRefused(
            f"it is the same file as the destination copy ({verified_copy}) — "
            f"source and destination storage overlap")
    try:
        _fsync_file(verified_copy)
        _fsync_directory(Path(verified_copy).parent)
        _fsync_chain_to_root(Path(verified_copy).parent)
    except OSError as e:
        raise SourceRemovalRefused(
            f"the destination copy could not be made durable ({type(e).__name__}: {e})")
    try:
        unchanged = _file_identity(source) == source_identity
    except OSError as e:
        raise SourceRemovalRefused(
            f"could not re-check the source before deleting it ({type(e).__name__}: {e})")
    if not unchanged:
        raise SourceRemovalRefused(
            "the source changed after it was verified, so its current content has no copy")
    retry_io_operation(description, source.unlink)


def _stage_copy(source: Path, dest: Path) -> Path:
    """
    Copies `source` into a NEW, uniquely named partial file beside `dest`,
    makes it durable, and returns its path.

    The name is created exclusively (O_EXCL) with a random suffix, and every
    write reopens it with O_NOFOLLOW, so staging never writes through a file
    or symlink already holding a predictable name. That matters because the
    engine's no-overwrite check — the publish in _finalize_partial — only
    runs AFTER staging.

    Mode and timestamps are copied as copy2 does, so the delivered file keeps
    the source's mtime; the fsync comes after, so data and metadata land
    together.
    """
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=f"{dest.name}{PARTIAL_SUFFIX}.")
    os.close(fd)
    partial = Path(tmp)
    try:
        def _write():
            out = os.open(tmp, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
            with os.fdopen(out, "wb") as dst_f, open(source, "rb") as src_f:
                shutil.copyfileobj(src_f, dst_f, SHA1_CHUNK_SIZE * 16)
        retry_io_operation(f"Copying {source.name}", _write)
        shutil.copystat(str(source), tmp)
        _fsync_file(tmp)
    except BaseException:
        with contextlib.suppress(OSError):
            partial.unlink()
        raise
    return partial


class DestinationExistsError(Exception):
    """
    Raised when the final destination name is already occupied at the moment
    the verified partial file is about to be published under it.

    Deliberately NOT an OSError subclass: retry_io_operation() catches
    OSError to ride out transient network-share hiccups, and retrying a
    name collision would just burn the backoff delays before failing
    anyway. This is a permanent condition for this filename, not a blip.
    """


def _finalize_partial(partial_dest: Path, dest: Path):
    """
    Publishes the verified partial file under its final name WITHOUT ever
    overwriting an existing file, then makes the new directory entry durable.

    Path.rename() cannot be used directly here: on POSIX it silently
    replaces an existing destination, so a same-named file already sitting
    at `dest` would be destroyed with no error raised and no record kept.
    os.link() is the no-overwrite alternative — it fails with
    FileExistsError rather than clobbering — and since the partial always
    lives in the same directory as its final name, it never crosses
    filesystems.

    Only a filesystem that genuinely cannot hard-link (FAT/exFAT, some
    network shares — see _NO_HARDLINK_ERRNOS) falls back to an existence
    check plus rename(). That fallback leaves a window in which a file
    appearing at `dest` from outside this engine would be replaced, so it is
    used for nothing else: any other link failure (an I/O error, a full
    disk) fails the publish rather than quietly weakening the guarantee.
    """
    try:
        os.link(str(partial_dest), str(dest))
    except FileExistsError:
        raise DestinationExistsError(f"Destination already exists, refusing to overwrite: {dest}")
    except OSError as e:
        if e.errno not in _NO_HARDLINK_ERRNOS:
            raise
        if dest.exists():
            raise DestinationExistsError(f"Destination already exists, refusing to overwrite: {dest}")
        partial_dest.rename(dest)
    else:
        partial_dest.unlink()
    _fsync_directory(dest.parent)



def copy_verify_delete(source_str: str, dest_str: str, delete_source: bool = True,
                       label: Optional[str] = None, verified_content: Optional[dict] = None) -> tuple:
    """
    Copies source to dest via a staged, verified, no-overwrite publish.

    Create the destination folder with every directory entry from --dest down
    made durable (_mkdir_durable); stage into a unique partial beside the
    destination and fsync it; verify its SHA-1 against the source's; publish
    it with a no-overwrite link and fsync the directory.
    delete_source=True (the --move behavior) then hands
    the source to _remove_verified_source(), which deletes it only if the
    copy is a separate, durable file and the source is unchanged since the
    copy began. delete_source=False (the --copy behavior) stops after
    publishing — non-destructive.

    Returns (success: bool, error_message: Optional[str]) — the message is
    None on success, and a human-readable description of what failed
    otherwise, so callers can persist the real reason to the operations
    log instead of just a bare pass/fail. `verified_content`, when supplied,
    receives the verified digest without requiring another read for lineage.
    """
    source = Path(source_str)
    dest = Path(dest_str)
    partial_dest = None

    try:
        _mkdir_durable(dest.parent)
        # Taken BEFORE the copy, so any edit from here on — during the copy,
        # during verification, after publishing — is visible at deletion time.
        source_identity = _file_identity(source)
        partial_dest = _stage_copy(source, dest)

        src_sha1 = compute_sha1(str(source))
        partial_sha1 = compute_sha1(str(partial_dest))

        if src_sha1 != partial_sha1:
            error_message = f"ChecksumMismatch: SHA1 verification failed for {source.name}"
            logger.error(error_message)
            partial_dest.unlink()
            return False, error_message

        if verified_content is not None:
            verified_content["sha1_hash"] = partial_sha1
        _finalize_partial(partial_dest, dest)
        partial_dest = None  # published: nothing left to clean up

        if delete_source:
            try:
                _remove_verified_source(source, dest, source_identity,
                                        f"Delete original {source.name}")
            except SourceRemovalRefused as e:
                error_message = f"Copied and verified, but the source was kept: {e}"
                logger.warning(f"{error_message} ({source_str})")
                return False, error_message
            logger.info(f"Successfully migrated: {label or source.name} -> {dest}")
        else:
            logger.info(f"Successfully copied: {label or source.name} -> {dest} (source untouched)")
        return True, None
    except Exception as e:
        error_message = f"{type(e).__name__}: {e}"
        logger.error(f"Failed transactional copy for {source_str}: {error_message}")
        if partial_dest is not None:
            with contextlib.suppress(OSError):
                partial_dest.unlink()
        return False, error_message


# --- Processing Worker ---
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

    Both distinctions were learned the hard way on a real library. Files differ
    enormously in cost — RAW was 13% of that library's files but 50% of its
    bytes, roughly 21 MB against 3 MB — so:

    - A cumulative average decays misleadingly. Indexing RAW first showed
      "34 files/sec" falling to "7 files/sec" over five minutes while the true
      rate was flat at 5.05 the entire time. That looks like something
      degrading. Nothing was.
    - A file count cannot distinguish "saturated link" from "broken". At 5.05
      files/sec the engine was moving ~101 MB/s, which is 1GbE at line rate —
      instantly recognisable as physics rather than a bug, but only if
      throughput is on screen. Without it an hour went into diagnosing a
      correctly-working scan.

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


def _failed_result(file_path_str: str, run_id: int, error_message: str) -> ProcessingResult:
    """Builds the Failed result for a file that could not be scanned at all."""
    return ProcessingResult(
        file_path=file_path_str, sha1_hash="", phash="", metadata={}, status=PhotoStatus.FAILED,
        dest_path="", run_id=run_id, error_message=error_message
    )


def process_file_task(file_path_str: str, dest_base_path: str, run_id: int,
                      cache_root: Optional[str] = None) -> ProcessingResult:
    """
    Scans one file: SHA-1, pHash, metadata/date, and its projected destination.

    NEVER raises. Any per-file failure comes back as a Failed result carrying
    a human-readable reason, because an exception escaping here propagates
    through future.result() in main() and aborts the ENTIRE run — discarding
    every other file's completed work and leaving no record of which file was
    responsible.
    """
    file_path = Path(file_path_str)

    # Checked explicitly, before any attempt to open the file, so a stale
    # selection surfaces as a specific reason in the Error Center rather than
    # a raw FileNotFoundError traceback (docs/engine-spec.md 4.2).
    if not file_path.exists():
        return _failed_result(
            file_path_str, run_id,
            f"Source file changed: no longer found at {file_path}. It may have been moved, "
            f"renamed, or deleted outside NegativeSpace since the last Index."
        )

    file_size = file_mtime = birthtime = None
    observed_at = ns_db.utc_now()
    try:
        # Cheap next to reading the whole file, and it is what lets progress
        # report THROUGHPUT rather than only a file count — see
        # log_scan_progress for why that distinction matters.
        try:
            _st = file_path.stat()
            file_size, file_mtime = _st.st_size, _st.st_mtime
            birthtime = getattr(_st, "st_birthtime", None)
        except OSError:
            pass

        sha1 = compute_sha1(str(file_path))
        phash = compute_phash(str(file_path))

        # Generated here, in the worker, because this process has already paid
        # to open and decode the file. It only ever READS the photo, and it
        # never raises — a thumbnail is disposable cache and must not decide
        # whether a file is catalogued (webui-spec.md 4.2.1).
        thumbnail = generate_thumbnail(file_path, sha1, cache_root) if cache_root and sha1 else None

        dt, metadata = get_metadata_and_date(file_path)
        # Keep an explicit, guaranteed-present date_taken key regardless of which
        # capture path produced `metadata`, since downstream consumers (path
        # computation here, and the inspector UI later) shouldn't need to know
        # ExifTool's exact tag-naming conventions just to find "the date."
        metadata["date_taken"] = dt.isoformat()

        # A photo the engine could not date does not enter the date tree: its
        # only date is the file's mtime, which for an export is the download
        # time. Filing it beside photos whose dates came from a camera makes a
        # guess indistinguishable from a fact. See UNDATED_FOLDER.
        #
        # This is a PROJECTION and is recomputed before the write, so both this
        # and _destination_for() must agree about Undated/ — otherwise the
        # catalog advertises a folder the file never occupies.
        if metadata.get("date_source") == DATE_SOURCE_MTIME:
            target_folder = Path(dest_base_path) / UNDATED_FOLDER / dt.strftime("%Y")
        else:
            year_dir = dt.strftime("%Y")
            month_dir = dt.strftime("%m")
            day_dir = dt.strftime("%d")
            target_folder = Path(dest_base_path) / year_dir / month_dir / day_dir

        # This destination is a PROJECTION, not a reservation, and
        # has_name_collision stays False here by design. The authoritative
        # unique-name resolution happens immediately before the file is
        # actually written (see _run_move_or_copy). Resolving it here instead
        # was silent data loss: at Index time the destination tree is normally
        # still empty, so two different photos sharing a filename were both
        # told the name was free, and whichever got written second overwrote
        # the first — with both runs reporting success.
        return ProcessingResult(
            file_path=str(file_path),
            sha1_hash=sha1,
            phash=phash,
            metadata=metadata,
            status=PhotoStatus.PENDING,
            dest_path=str(target_folder / file_path.name),
            run_id=run_id,
            has_name_collision=False,
            file_size=file_size,
            file_mtime=file_mtime, birthtime=birthtime, observed_at=observed_at,
            thumbnail=thumbnail
        )
    except Exception as e:
        result = _failed_result(file_path_str, run_id, f"{type(e).__name__}: {e}")
        result.file_size, result.file_mtime = file_size, file_mtime
        result.birthtime, result.observed_at = birthtime, observed_at
        return result


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
    lock_path = base_dir / LOCK_FILENAME
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


# --- Main Execution ---
def is_hidden_path(path: Path, root: Path) -> bool:
    """
    True if any path segment below `root` starts with a dot.

    Checking every segment, not just the filename, is what makes this cover
    whole junk trees (.Trashes/, .Spotlight-V100/, .thumbnails/) and not just
    individual dotfiles.

    The case that actually motivated this: macOS writes an AppleDouble
    sidecar named "._IMG_0001.jpg" beside every real file on non-HFS volumes
    (SD cards, USB drives, network shares). Those carry a real photo
    extension, so the scan happily indexed each one as a photograph —
    hashing it, failing to find EXIF, filing it by mtime, and on --move
    dutifully migrating a few KB of resource-fork metadata into the library
    as if it were a picture. Every SD card import brought a shadow copy of
    itself. .DS_Store never matched an extension so it was harmless; these
    were not.
    """
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = Path(path.name)
    return any(part.startswith('.') for part in relative.parts)


def describe_root_overlap(source: Path, dest: Path) -> Optional[str]:
    """
    Explains how two RESOLVED roots overlap, or returns None if they do not.

    Detects what the paths and the kernel can show: one path, one nested in
    the other (symlinks are already resolved by the caller), and one directory
    reachable at two paths, such as a bind mount, via samefile(). Two separate
    network mounts of one export appear as different devices and are NOT
    detected — which is why _remove_verified_source() also refuses per file,
    and why overlapping storage stays documented as unsupported.
    """
    if source == dest:
        return f"both are {source}"
    if dest.is_relative_to(source):
        return f"the destination {dest} is inside the source {source}"
    if source.is_relative_to(dest):
        return f"the source {source} is inside the destination {dest}"
    try:
        if dest.exists() and os.path.samefile(source, dest):
            return f"{source} and {dest} are the same directory reached by two paths"
    except OSError:
        pass
    return None


def discover_source_files(root: Path, extensions: set, errors: Optional[list] = None) -> List[str]:
    """
    Walks `root` and returns the files worth scanning.

    Uses os.scandir rather than Path.rglob because of what each costs on a
    NETWORK share. rglob yields bare paths, so the caller must then ask
    p.is_file() and p.is_symlink() — two stat() calls per entry, and over NFS a
    stat() is a round trip rather than a page-cache hit. A real library spent
    28-40 seconds merely enumerating 29,047 files, which is almost exactly
    29,047 x 2 x ~0.5ms of round trips. os.scandir's DirEntry carries the type
    from readdir(), so the same walk usually needs no extra syscall at all;
    measured 8x faster even on a local filesystem, where there is no network
    latency to hide.

    The extension test is also checked BEFORE the filesystem questions, so a
    directory full of video or sidecar files costs string comparisons instead
    of syscalls.
    """
    found: List[str] = []
    stack = [str(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    # A leading dot at any level: skip the whole subtree. This
                    # covers .Trashes/, .Spotlight-V100/ and macOS AppleDouble
                    # sidecars ("._IMG_0001.jpg") that carry real photo
                    # extensions and would otherwise index as photographs.
                    if entry.name.startswith('.'):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        if os.path.splitext(entry.name)[1].lower() not in extensions:
                            continue
                        if entry.is_file(follow_symlinks=False):
                            found.append(entry.path)
                    except OSError as e:
                        logger.warning(f"Could not inspect {entry.path}: {e}")
                        if errors is not None:
                            errors.append((entry.path, f"Could not inspect during the scan: "
                                                       f"{type(e).__name__}: {e}"))
        except OSError as e:
            # An unreadable directory must not abort the whole scan, for the
            # same reason an unreadable file does not — but it must not vanish
            # into the log either. `errors` lets the caller record it.
            logger.warning(f"Could not read directory {current}: {e}")
            if errors is not None:
                errors.append((current, f"Could not read this folder during the scan, so photos "
                                        f"inside it were not examined: {type(e).__name__}: {e}"))
    return found


def partition_unchanged(db_path: str, candidates: List[str], force: bool = False) -> tuple:
    """
    Splits discovered files into (to_scan, unchanged), returning paths whose
    size and mtime still match what the catalog recorded as `unchanged`.

    Without this check every Index reads EVERY file in full — SHA-1 over the
    whole file, a complete pixel decode for the perceptual hash, and an
    ExifTool pass — because SHA-1 cannot serve as the skip test: it is the
    RESULT of reading the file, not something knowable beforehand. Measured on
    one 29,047-file library, two consecutive indexes took 24m57s and 25m27s,
    the second gaining nothing from the first.

    Comparing size and mtime costs one stat per file instead of reading it —
    roughly 21 MB of network traffic replaced by a single metadata round trip
    for a RAW file. A library that has not changed re-indexes in seconds.

    Rows predating this check have NULL size/mtime, which reads as "unknown"
    and forces one full pass for those files; it is self-correcting after that.
    A file whose row is not in a settled state is always rescanned, so
    interrupted or failed work is never skipped on the strength of a stat.

    force=True bypasses the comparison entirely (--force-rehash), for when the
    concern is content changed without size or mtime moving — which editors do
    not do in practice, but verification should not require deleting the
    database.
    """
    if force or not candidates:
        return list(candidates), []

    conn = get_db_connection(db_path)
    try:
        known = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT source_path, file_size, file_mtime FROM photos "
                "WHERE file_size IS NOT NULL AND file_mtime IS NOT NULL "
                f"AND status IN ({sql_values(tuple(v for v in SETTLED_STATUSES if v not in SOURCE_CONSUMED_STATUSES))})"
            )
        }
    finally:
        conn.close()

    if not known:
        return list(candidates), []

    to_scan, unchanged = [], []
    for path in candidates:
        recorded = known.get(path)
        if recorded is None:
            to_scan.append(path)
            continue
        try:
            st = os.stat(path)
        except OSError:
            # Cannot stat it, so cannot claim it is unchanged. Let the normal
            # pipeline record the real failure with its reason.
            to_scan.append(path)
            continue
        if recorded[0] == st.st_size and abs(recorded[1] - st.st_mtime) < 1e-6:
            unchanged.append(path)
        else:
            to_scan.append(path)
    return to_scan, unchanged


def normalize_extensions(raw: str) -> set:
    """
    Parses --exts into the form Path.suffix actually produces.

    Path.suffix ALWAYS includes the leading dot (".jpg") and the scan compares
    against it directly, so an unnormalised `--exts jpg,png` would match
    nothing and report "Discovered 0 files" with no hint why. Both spellings
    are accepted, along with surrounding whitespace and any casing:
        ".jpg, PNG , .HEIC"  ->  {".jpg", ".png", ".heic"}
    """
    extensions = set()
    for item in raw.split(','):
        item = item.strip().lower()
        if not item:
            continue
        extensions.add(item if item.startswith('.') else f".{item}")
    return extensions


def positive_int(value: str) -> int:
    """argparse type for --workers: zero or a negative count is an error, not the default."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number, got: {value}")
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got: {value}")
    return number


def parse_file_ids(value: str) -> List[int]:
    try:
        return [int(x.strip()) for x in value.split(',') if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f"--file-ids must be a comma-separated list of integers, got: {value}")


def _query_source_subdir(db_path: str, subdir_filter_path: Path) -> List[str]:
    """
    Looks up already-cataloged `photos.source_path` values falling under
    `subdir_filter_path` (the exact directory itself, or recursively below
    it). Rows whose source a prior --move already consumed on purpose are
    excluded (SOURCE_CONSUMED_STATUSES); everything else is returned even if
    the file is missing from disk, so process_file_task can record it as
    Failed with a real reason instead of it silently vanishing from the run.
    Used for Index-mode re-scans scoped to a subdirectory; the Move/Copy
    targeting path additionally filters on `status = 'Pending'` inline
    rather than calling this helper.
    """
    conn = get_db_connection(db_path)
    placeholders = ','.join('?' * len(SOURCE_CONSUMED_STATUSES))
    # Same escaped prefix the Move/Copy targeting path uses, so an Index-mode
    # rescan and the action that follows it can never disagree about which
    # files "this subdirectory" means.
    prefix_sql, prefix_params = _path_prefix_clause(subdir_filter_path)
    rows = conn.execute(
        f"SELECT source_path FROM photos WHERE 1=1{prefix_sql} "
        f"AND status NOT IN ({placeholders})",
        (*prefix_params, *SOURCE_CONSUMED_STATUSES)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def main():
    parser = argparse.ArgumentParser(
        description="NegativeSpace - Photo Collection Organizer (Engine)",
        epilog="WARNING: Source and destination must map to separate, non-overlapping underlying "
               "folders, including on network shares. Never mount the same folder at both paths "
               "or nest one inside the other. Different container paths do not ensure separate "
               "storage. Overlapping mounts can cause unintended file deletion and are not "
               "reliably detected by the engine."
    )
    parser.add_argument("--source", default="/data/source", help="Path to source directory (default: /data/source).")
    parser.add_argument("--dest", default="/data/dest", help="Path to destination directory (default: /data/dest).")
    parser.add_argument("--base", default="/appdata", help="Base directory for DB and logs (default: /appdata).")
    parser.add_argument(
        "--workers", type=positive_int, default=None,
        help=f"Worker process count for hashing/date resolution (default: {MAX_WORKER_PROCESSES}, auto-detected CPU count)."
    )
    parser.add_argument(
        "--exts", type=str, default=None,
        help="Comma-separated list of extensions to scan (e.g. '.jpg,.png'), replacing the built-in default set. "
             "Only affects directory scanning, not --file-ids targeting."
    )
    parser.add_argument(
        "--cache", default="/cache",
        help="Directory holding generated thumbnails (default: /cache). Written by the scan "
             "phase, which every mode begins with; the transfer phase itself — copy, verify, "
             "delete — never touches it. Everything under it is reproducible from the photo "
             "it came from, so it is safe to delete and should be excluded from backups."
    )
    parser.add_argument(
        "--no-thumbnails", action="store_true",
        help="Skip thumbnail generation during the scan. Indexing is otherwise unchanged; "
             "the gallery shows placeholders until a later run generates them."
    )
    parser.add_argument(
        "--force-rehash", action="store_true",
        help="Re-read every file even if its size and modification time are unchanged since the "
             "last Index. Normally unchanged files are skipped without being read at all, which "
             "is what makes re-indexing fast; use this to verify content that changed without "
             "size or mtime moving."
    )
    targeting_group = parser.add_mutually_exclusive_group()
    targeting_group.add_argument(
        "--file-ids", type=parse_file_ids, default=None,
        help="Comma-separated list of existing photo IDs (from a prior Index) to target. "
             "Bypasses the full directory scan — processes exactly these already-cataloged files."
    )
    targeting_group.add_argument(
        "--source-subdir", type=str, default=None,
        help="Path, relative to --source, to scope this run to. Queries already-cataloged rows whose "
             "source_path falls under <source>/<subdir> instead of walking the filesystem or enumerating "
             "--file-ids — the mechanism behind the web UI's folder-selection option for batches too large "
             "for --file-ids. Only reflects files known as of the last Index over that path. "
             "Mutually exclusive with --file-ids."
    )

    # Only one mode may be active per run — default (no flag) is the existing
    # Index: full scan + hash + date/dest-path resolution, no physical
    # action. The two flags below are mutually exclusive with each other.
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--move", action="store_true",
        help="Execute physical migration (Copy-Verify-Delete, source files are moved/deleted)."
    )
    mode_group.add_argument(
        "--copy", action="store_true",
        help="Non-destructive: copy source files to destination, verified, but never delete or modify the source."
    )
    args = parser.parse_args()

    start_method = configure_multiprocessing_start_method()
    worker_count = args.workers if args.workers else MAX_WORKER_PROCESSES
    active_extensions = normalize_extensions(args.exts) if args.exts else SUPPORTED_EXTENSIONS

    # 1. Resolve Base Path & Setup Subdirectories
    base_dir = Path(args.base).resolve()
    db_dir = base_dir / "db"
    log_dir = base_dir / "logs"
    db_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / DB_FILENAME

    # 2. Configure Logging
    configure_logging(log_dir)

    # 2a. Single-instance enforcement (docs/engine-spec.md 4.1/7) — before
    # touching the database or source/dest paths at all. Applies to every
    # mode, including Index, not just --move/--copy.
    lock_fd = acquire_single_instance_lock(base_dir)
    if lock_fd is not None:
        # Only the lock holder rotates: a rejected second instance must not
        # rename the running engine's log out from under it.
        rotate_log_if_large()
    if lock_fd is None:
        logger.error(
            f"FATAL: another NegativeSpace engine process is already running against --base {base_dir} "
            f"(lock file: {base_dir / LOCK_FILENAME}). Only one operation may run at a time. "
            f"Wait for it to finish, or cancel it, then retry."
        )
        sys.exit(1)

    # 2b. ExifTool is a hard requirement (module docstring) — fail fast and
    # clearly, before touching source/dest/the database at all, rather than
    # limping along in a degraded PIL-only mode.
    if not EXIFTOOL_SUPPORTED:
        missing = []
        if not PYEXIFTOOL_PACKAGE_AVAILABLE:
            missing.append("the 'PyExifTool' Python package (pip install pyexiftool)")
        if not EXIFTOOL_BINARY_AVAILABLE:
            missing.append("the 'exiftool' system binary (apt install libimage-exiftool-perl)")
        logger.error(
            "FATAL: ExifTool is a hard requirement for NegativeSpace and is not available. "
            f"Missing: {' and '.join(missing)}."
        )
        sys.exit(1)

    source_path = Path(args.source).resolve()
    dest_path = Path(args.dest).resolve()

    # Invalid input is an error, not an empty success: the caller (the web UI,
    # a script) reads the exit code, and exit 0 said "nothing to do".
    if not source_path.exists():
        logger.error(f"FATAL: source path does not exist: {source_path}")
        release_single_instance_lock(lock_fd)
        sys.exit(1)
    if not source_path.is_dir():
        logger.error(f"FATAL: source path is not a folder: {source_path}")
        release_single_instance_lock(lock_fd)
        sys.exit(1)

    # Source and destination must be separate storage. When they are one
    # folder, or one contains the other, a file already in its date folder has
    # its own path as its computed destination: the already-present check
    # hashes the file against itself, matches, and --move deletes the only
    # copy while reporting success. Refused for every mode — overlapping roots
    # are unsupported whatever the run would have done.
    overlap = describe_root_overlap(source_path, dest_path)
    if overlap:
        logger.error(
            f"FATAL: source and destination overlap — {overlap}. They must be separate, "
            f"non-overlapping folders; check the host folders behind the container mounts. "
            f"Nothing was changed."
        )
        release_single_instance_lock(lock_fd)
        sys.exit(1)

    # --source-subdir scopes targeting to already-indexed rows under this
    # path, rather than re-walking the filesystem or enumerating IDs. Resolve
    # it now and confirm it doesn't escape --source (e.g. via `..` segments)
    # before it's ever used in a query.
    subdir_filter_path = None
    if args.source_subdir:
        subdir_filter_path = (source_path / args.source_subdir).resolve()
        try:
            subdir_filter_path.relative_to(source_path)
        except ValueError:
            logger.error(
                f"--source-subdir must resolve to a path under --source ({source_path}); "
                f"got: {subdir_filter_path}"
            )
            release_single_instance_lock(lock_fd)
            sys.exit(1)

    mode_label = "COPY" if args.copy else ("MOVE" if args.move else "INDEX")
    logger.info(f"Initializing NegativeSpace Engine. Mode: {mode_label}")
    logger.info(f"Base Directory: {base_dir}")
    logger.info(f"Source Directory: {source_path}")
    logger.info(f"Destination Directory: {dest_path}")
    logger.info(f"Database Path: {db_path}")

    # Log the resolved timezone explicitly: it silently decides which
    # YYYY/MM/DD folder a file lands in, and a container defaults to UTC
    # regardless of the host's zone unless TZ is passed in. EXIF dates are
    # used exactly as the camera recorded them (they carry no zone, so no
    # conversion happens), but the file-mtime fallback — every file without a
    # usable EXIF date — is interpreted in this zone. A photo taken at 21:00
    # local buckets into the NEXT day under UTC.
    logger.info(f"Worker start method: {start_method} (avoids unsafe fork with rawpy/OpenMP).")
    _local_now = datetime.now().astimezone()
    logger.info(
        f"Timezone: {_local_now.tzname()} (UTC{_local_now.strftime('%z')}) — "
        f"used for date bucketing when a file has no EXIF date. Pass -e TZ=<zone> to change it."
    )
    if args.file_ids:
        logger.info(f"Targeted file IDs: {args.file_ids}")
    if subdir_filter_path is not None:
        logger.info(f"Targeted source subdirectory: {subdir_filter_path}")

    # 3. Schema + Startup Recovery
    try:
        init_database(str(db_path))
    except (ns_db.SchemaError, sqlite3.DatabaseError) as exc:
        logger.error(f"FATAL: catalog initialization failed: {exc}. No files were processed.")
        release_single_instance_lock(lock_fd)
        sys.exit(1)

    # 4. Register cancellation handlers and open the run record. Everything
    # from here down is wrapped in try/except/finally so the `runs` row is
    # always finalized — Completed on normal exit, Cancelled if a signal
    # arrived, Failed if anything unexpected blew up — never left "Running"
    # forever from a crash.
    signal.signal(signal.SIGTERM, _handle_cancel_signal)
    signal.signal(signal.SIGINT, _handle_cancel_signal)
    run_id = start_run(
        str(db_path), mode_label, str(source_path), str(dest_path), args.file_ids, args.source_subdir,
        defaults={"workers": MAX_WORKER_PROCESSES, "exts": sorted(SUPPORTED_EXTENSIONS)},
        overrides={**({"workers": args.workers} if args.workers is not None else {}),
                   **({"exts": sorted(normalize_extensions(args.exts))} if args.exts is not None else {})},
    )
    with contextlib.closing(get_db_connection(str(db_path))) as config_conn:
        config = json.loads(config_conn.execute(
            "SELECT effective_config_json FROM run_configs WHERE run_id=?", (run_id,)
        ).fetchone()[0])
    worker_count, active_extensions = config["workers"], set(config["exts"])
    # Reconciled AFTER the run exists, so what it concludes is recorded as
    # operations of this run rather than as silently rewritten statuses.
    # Outside the try/finally below, so a raised failure would otherwise leave
    # the run Running forever. Settle it here instead of swallowing the error.
    try:
        reconcile_interrupted_state(db_path, run_id)
    except Exception as exc:
        logger.error(f"FATAL: could not reconcile interrupted work: {exc}")
        finish_run(str(db_path), run_id, RunStatus.FAILED)
        release_single_instance_lock(lock_fd)
        sys.exit(1)
    run_outcome = RunStatus.FAILED

    try:
        # 5. Start DB Writer Thread
        db_thread = threading.Thread(target=db_writer_worker, args=(str(db_path),), daemon=True)
        db_thread.start()

        if args.file_ids:
            # Targeted mode: look up already-cataloged paths by ID instead of
            # scanning the filesystem. A file must have gone through at least
            # one prior Index for its ID to exist at all.
            conn = get_db_connection(str(db_path))
            placeholders = ','.join('?' * len(args.file_ids))
            rows = conn.execute(
                f"SELECT id, source_path, status FROM photos WHERE id IN ({placeholders})", args.file_ids
            ).fetchall()
            conn.close()
            found_ids = {r[0] for r in rows}
            missing = set(args.file_ids) - found_ids
            if missing:
                logger.warning(f"file-ids not found in database (never indexed?): {sorted(missing)}")
            # Bounded by this run's --source like every other targeting mode:
            # an ID recorded under another source root is not this run's to act on.
            outside = [r for r in rows if not _is_under(r[1], source_path)]
            if outside:
                logger.warning(
                    f"{len(outside)} requested file ID(s) belong to a different source root than "
                    f"{source_path} and are left out of this run: {sorted(r[0] for r in outside)}"
                )
                rows = [r for r in rows if _is_under(r[1], source_path)]
            already_done = [r for r in rows if r[2] in SOURCE_CONSUMED_STATUSES]
            if already_done:
                logger.info(
                    f"Skipping {len(already_done)} targeted file(s) already completed by a prior run — "
                    f"their source was removed on purpose."
                )
            # Files missing for any OTHER reason are deliberately NOT filtered
            # out: they flow through to process_file_task, which records each
            # one as Failed with a specific reason. Dropping them here (the
            # previous behavior) made a stale selection silently shrink, with
            # nothing in the audit log explaining where those files went.
            candidates = [r[1] for r in rows if r[2] not in SOURCE_CONSUMED_STATUSES]
            logger.info(f"Targeting {len(candidates)} of {len(args.file_ids)} requested file IDs.")
        elif subdir_filter_path is not None:
            # Same idea as --file-ids: query already-cataloged rows instead of
            # walking the filesystem. Only rows from a prior Index over this
            # path are visible — a fresh subtree needs a full scan first.
            candidates = _query_source_subdir(str(db_path), subdir_filter_path)
            logger.info(f"Targeting {len(candidates)} already-indexed file(s) under source subdirectory.")
        else:
            discovery_errors: List[tuple] = []
            candidates = discover_source_files(source_path, active_extensions, errors=discovery_errors)
            logger.info(
                f"Discovered {len(candidates):,} supported photo/image files "
                f"(extensions: {', '.join(sorted(active_extensions))})."
            )
            if discovery_errors:
                record_run_failures(str(db_path), run_id, discovery_errors)
                logger.warning(
                    f"{len(discovery_errors)} folder(s) or file(s) could not be read during the scan; "
                    f"each is recorded as a failure of this run."
                )
            # Only a full walk can say what is no longer there.
            vanished = mark_vanished_sources(str(db_path), run_id, source_path, candidates)
            if vanished:
                logger.warning(
                    f"{vanished:,} catalogued file(s) under {source_path} no longer exist; recorded as "
                    f"Failed so any duplicates of them can stand in as the original."
                )

        # A targeting mode that matches nothing is a user-visible mistake, not
        # a successful no-op. Both targeted modes read the CATALOG rather than
        # the filesystem, so against a database that has never been indexed
        # they match zero rows and the run "completes successfully (0 files)"
        # — indistinguishable from a run that genuinely had nothing to do.
        # The web UI derives job outcome from recorded operations, so such a job
        # would show green having done nothing at all. Say what happened and
        # what to do about it.
        if not candidates:
            if args.file_ids:
                logger.warning(
                    f"None of the {len(args.file_ids)} requested file ID(s) resolved to work for this "
                    f"run. IDs exist only for files a previous Index recorded, and IDs whose source a "
                    f"prior --move already consumed are skipped on purpose. Nothing will be "
                    f"{'copied' if args.copy else 'moved' if args.move else 'scanned'}."
                )
            elif subdir_filter_path is not None:
                logger.warning(
                    f"No indexed files found under {subdir_filter_path}. --source-subdir targets rows "
                    f"the catalog already holds; it does not walk the filesystem. Run an Index over "
                    f"this source first (no --file-ids/--source-subdir), then re-run this command. "
                    f"Nothing will be {'copied' if args.copy else 'moved' if args.move else 'scanned'}."
                )
            else:
                logger.warning(
                    f"No supported files found under {source_path} "
                    f"(extensions: {', '.join(sorted(active_extensions))}). Check the source mount "
                    f"and --exts."
                )

        # Applies to ALL THREE targeting modes, not just the full scan.
        #
        # Re-reading an unchanged file costs a full SHA-1, a pixel decode for
        # the perceptual hash, and an ExifTool pass; over a network share, a
        # scoped run of ~9,500 files spends minutes on that before the first
        # byte is copied. Scoped runs are exactly what the web UI issues.
        # Skipping is safe because an unchanged file's row already holds its
        # hashes and date, which is all the Move/Copy phase reads.
        files_to_process, unchanged = partition_unchanged(
            str(db_path), candidates, force=args.force_rehash
        )
        if unchanged:
            logger.info(
                f"Skipping {len(unchanged):,} unchanged file(s) — size and modification time "
                f"still match the catalog, so they are not re-read. "
                f"{len(files_to_process):,} file(s) to scan. Pass --force-rehash to re-read everything."
            )
        elif args.force_rehash:
            logger.info("--force-rehash: re-reading every file regardless of the catalog.")

        # Submitted in bounded batches rather than all at once. Every
        # completed future holds its ProcessingResult — including the FULL
        # ExifTool tag set for that file — until it is drained, so submitting
        # an entire library up front made peak memory scale with the number of
        # photos (hundreds of MB to GBs on a large collection) no matter how
        # small the queue's maxsize was. Batching also gives cancellation a
        # checkpoint between batches; without one, Cancel Job (and `docker
        # stop`, which escalates to SIGKILL after ~10s) could not stop a long
        # Index.
        # Thumbnails are written by the scan phase only — the Move/Copy phase
        # never touches the cache. A cache root that cannot be created disables
        # generation for this run rather than failing an Index that is otherwise
        # fine: everything under it is reproducible from the photos themselves.
        cache_root = None if args.no_thumbnails else Path(args.cache)
        if cache_root is not None:
            try:
                (cache_root / THUMBNAIL_DIR_NAME).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.warning(
                    f"Thumbnail cache at {cache_root} is not writable ({e}) — continuing without "
                    f"thumbnails. Indexing is unaffected; the gallery will show placeholders "
                    f"until a run with a writable cache generates them."
                )
                cache_root = None
        elif args.no_thumbnails:
            logger.info("--no-thumbnails: skipping thumbnail generation for this run.")

        scan_batch_size = max(worker_count * 4, 16)
        scanned = 0
        scan_started_at = time.monotonic()
        last_progress_at = scan_started_at
        last_progress_scanned = 0
        bytes_done = 0
        last_progress_bytes = 0
        with ProcessPoolExecutor(
            max_workers=worker_count,
            initializer=_init_worker_process,
            initargs=(EXIFTOOL_SUPPORTED, str(log_dir))
        ) as executor:
            for batch_start in range(0, len(files_to_process), scan_batch_size):
                if cancel_requested.is_set():
                    logger.warning(
                        f"Cancellation requested — stopping scan after {scanned} of "
                        f"{len(files_to_process)} file(s). Nothing already written to the "
                        f"database is lost; re-run to continue."
                    )
                    break
                batch = files_to_process[batch_start:batch_start + scan_batch_size]
                futures = [executor.submit(process_file_task, f, str(dest_path), run_id,
                                           str(cache_root) if cache_root else None)
                           for f in batch]
                for future in futures:
                    result = future.result()
                    bytes_done += result.file_size or 0
                    put_result(result, db_thread)
                scanned += len(batch)

                now = time.monotonic()
                if now - last_progress_at >= PROGRESS_INTERVAL_SECONDS:
                    log_scan_progress(
                        scanned, len(files_to_process), scan_started_at,
                        window_files=scanned - last_progress_scanned,
                        window_bytes=bytes_done - last_progress_bytes,
                        window_seconds=now - last_progress_at,
                    )
                    last_progress_at = now
                    last_progress_scanned = scanned
                    last_progress_bytes = bytes_done

        drain_result_queue(db_thread)
        result_queue.put(None)
        db_thread.join(timeout=60)
        if db_thread.is_alive():
            logger.error("Database writer did not shut down within 60s — continuing without it.")
            writer_failures.append(("(database writer)", "did not shut down within 60s"))

        if cancel_requested.is_set():
            logger.info(
                f"Scan cancelled after {scanned} file(s) — skipping the move/copy phase. "
                f"Everything already indexed is saved; re-run to continue."
            )
            run_outcome = RunStatus.CANCELLED
        elif writer_failures:
            first_path, first_reason = writer_failures[0]
            logger.error(
                f"{len(writer_failures):,} scan result(s) could not be recorded in the catalog "
                f"(first: {first_path} — {first_reason}). The catalog does not reflect this scan, "
                f"so no files will be moved or copied. Nothing was changed on disk."
            )
            run_outcome = RunStatus.FAILED
        else:
            gb = bytes_done / 1e9
            elapsed = time.monotonic() - scan_started_at
            logger.info(
                f"Scan and indexing completed successfully ({scanned:,} file(s), {gb:.1f} GB "
                f"in {format_duration(elapsed)} — {bytes_done/elapsed/1e6:.0f} MB/s average). "
                f"Database updated."
            )
            promoted, demoted = normalize_duplicate_groups(str(db_path))
            if promoted or demoted:
                logger.info(
                    f"Reclassified duplicates against the current catalog: {promoted} promoted to "
                    f"Pending (their original changed, failed or disappeared), {demoted} marked "
                    f"Duplicate (their content is already delivered or queued)."
                )
            if args.move or args.copy:
                run_outcome = _run_move_or_copy(args, db_path, dest_path, run_id)
            else:
                run_outcome = RunStatus.COMPLETED
                logger.info(
                    "Index finished. Pass `--move` to move files, or `--copy` to copy them non-destructively."
                )

    finally:
        if cancel_requested.is_set() and run_outcome != RunStatus.CANCELLED:
            # Cancellation arrived during the scan phase itself (before the
            # move/copy loop even started) — nothing file-level to log as
            # Cancelled yet since no per-file work was scoped out, but the
            # run itself still needs to be marked accordingly.
            run_outcome = RunStatus.CANCELLED
        finish_run(str(db_path), run_id, run_outcome)
        logger.info(f"Run #{run_id} finished with status: {run_outcome}")
        release_single_instance_lock(lock_fd)

    # A failed run is an error to whatever invoked the engine, not a success
    # with a sad log line. The web UI reads the exit code as well as the record.
    if run_outcome == RunStatus.FAILED:
        sys.exit(1)


def record_run_failures(db_path: str, run_id: int, failures: List[tuple]):
    """Records (path, reason) failures that belong to the run rather than to any catalogued photo."""
    conn = get_db_connection(db_path)
    try:
        for path, reason in failures:
            log_operation(conn, run_id, None, path, None, PhotoStatus.FAILED, reason, commit=False)
        conn.commit()
    finally:
        conn.close()


def mark_vanished_sources(db_path: str, run_id: int, root: Path, discovered: List[str]) -> int:
    """
    After a full walk of `root`, marks catalogued Pending/Duplicate files that
    no longer exist as Failed, with a recorded reason. Returns how many.

    A full Index only updates the files it finds, so without this a photo
    deleted outside the engine would keep its row Pending indefinitely, and
    go on standing as the original of its duplicate group, so the duplicate
    would never be delivered. Failed rows take no part in duplicate grouping, which lets the
    reclassification that follows promote a surviving duplicate.

    A file counts as gone only when stat() says it does not exist. Anything
    else — a permission error, an I/O fault, an --exts filter that simply did
    not list it — leaves the row alone: unreadable is not absent.

    A walk that found NOTHING is refused outright while the catalog still holds
    rows here. An unmounted share leaves exactly that shape — a directory that
    exists and is empty — and every stat() beneath it then says "not found", so
    the sweep would condemn the entire catalogue under this root in one pass.
    Failed rows leave their duplicate group, so a copy in another archive is
    silently promoted to anchor meanwhile.

    The check lives here rather than at the call site deliberately: the same
    reasoning as the durability barrier at the deletion gate, where being each
    caller's responsibility is exactly how two callers came to forget it.

    The cost is accepted knowingly. A root whose files really were all deleted
    keeps its rows, and nothing promotes their duplicates until a supported
    file is present here again. That is recoverable and visible; a catalogue
    marked Failed wholesale is neither. Returns 0 when it refuses.
    """
    seen = set(discovered)
    clause, params = _path_prefix_clause(root)
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            f"SELECT id, source_path, dest_path FROM photos "
            f"WHERE status IN ({sql_values((PhotoStatus.PENDING, PhotoStatus.DUPLICATE))})" + clause,
            params
        ).fetchall()

        if not discovered and rows:
            reason = (
                f"Refused to reconcile {root}: the scan found no supported files there while the "
                f"catalog still holds {len(rows):,}. That is what a detached or unmounted source "
                f"looks like, so no row was changed."
            )
            logger.warning(
                f"{reason} If the storage is missing, restore it and run Index again. If every "
                f"file under this root really was removed, those rows stay as they are — nothing "
                f"will promote their duplicates until a supported file is present here again."
            )
            # Recorded, not merely logged: the Error Center reads operations,
            # and a warning in the log is invisible to it.
            log_operation(conn, run_id, None, str(root), None, PhotoStatus.FAILED,
                          reason, commit=False)
            conn.commit()
            return 0

        gone = []
        for row_id, path, dest in rows:
            if path in seen:
                continue
            try:
                os.stat(path)
            except (FileNotFoundError, NotADirectoryError):
                gone.append((row_id, path, dest))
            except OSError:
                continue
        for row_id, path, dest in gone:
            conn.execute("UPDATE photos SET status = ? WHERE id = ?", (PhotoStatus.FAILED, row_id))
            log_operation(
                conn, run_id, row_id, path, dest, PhotoStatus.FAILED,
                f"Source file changed: no longer found at {path}. It may have been moved, renamed, "
                f"or deleted outside NegativeSpace since the last Index.",
                commit=False
            )
        conn.commit()
    finally:
        conn.close()
    return len(gone)


def _is_under(path: str, root: Path) -> bool:
    """Literal, case-sensitive containment — the same rule _path_prefix_clause applies in SQL."""
    root_str = str(root)
    return path == root_str or path.startswith(root_str + "/")


def _display_path(path: str, root: Path) -> str:
    """A source path as shown in per-file log lines: relative to the run's --source root."""
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return Path(path).name


def _destination_for(dest_root: Path, source_path: str, metadata_json: Optional[str],
                     fallback: str) -> str:
    """
    The file's projected destination under THIS run's --dest, computed now.

    The catalog's dest_path was computed against whatever --dest was current
    when the file was last read, and the unchanged-file skip means that can be
    long ago — so trusting it would copy into the OLD destination after
    checking free space on the new one. The date that picks the folder is
    stored separately, so recomputing costs nothing. The stored path remains
    the fallback for a row with no recorded date, and is therefore the one
    case where the result may NOT lie under the current --dest; anything
    walking up from it has to allow for that (see _mkdir_durable).
    """
    try:
        metadata = json.loads(metadata_json or "{}")
        taken = datetime.fromisoformat(metadata.get("date_taken"))
    except (TypeError, ValueError, AttributeError):
        return fallback

    # Undated photos never enter the date tree — see UNDATED_FOLDER. This must
    # stay in step with the projection the scan writes, or the catalog names a
    # folder the file never occupies and the staging screen, which projects
    # from the catalog, shows the wrong destination for every undated photo.
    if metadata.get("date_source") == DATE_SOURCE_MTIME:
        return str(Path(dest_root) / UNDATED_FOLDER / taken.strftime("%Y")
                   / Path(source_path).name)

    return str(Path(dest_root) / taken.strftime("%Y") / taken.strftime("%m") / taken.strftime("%d")
               / Path(source_path).name)


def _duplicate_skip_reason(cursor, sha1_hash: str, copying: bool) -> tuple:
    """
    (reason, pointer) for a duplicate this run deliberately leaves alone. The
    reason names the original that carries its content; the pointer is where
    that content already sits, when it has been delivered.
    """
    cursor.execute(
        f"SELECT id, source_path, dest_path, status FROM photos WHERE sha1_hash = ? "
        f"AND status IN ({sql_values(ANCHOR_STATUSES + (PhotoStatus.FAILED,))}) "
        f"ORDER BY CASE WHEN status IN ({sql_values(ANCHOR_DELIVERED_STATUSES)}) THEN 0 ELSE 1 END, id "
        f"LIMIT 1",
        (sha1_hash,)
    )
    row = cursor.fetchone()
    if row is None:
        return ("Duplicate with no original left in the catalog; run an Index so it can be "
                "reclassified.", None)
    anchor_id, anchor_src, anchor_dest, anchor_status = row
    name = Path(anchor_src).name
    if anchor_status in ANCHOR_DELIVERED_STATUSES:
        if copying:
            return (f"Duplicate of photo #{anchor_id} ({name}); its content is already at "
                    f"{anchor_dest}, so there is nothing to copy.", anchor_dest)
        return (f"Duplicate of photo #{anchor_id} ({name}), whose content was copied but not "
                f"moved; this source is removed once that photo is moved.", anchor_dest)
    if anchor_status == PhotoStatus.FAILED:
        return (f"Duplicate of photo #{anchor_id} ({name}), whose own transfer failed; its "
                f"content is delivered once that photo succeeds.", None)
    return (f"Duplicate of photo #{anchor_id} ({name}), which was not part of this selection; "
            f"its content is delivered when that photo is copied or moved.", None)


def normalize_duplicate_groups(db_path: str) -> tuple:
    """
    Re-derives Pending versus Duplicate for every content group from the
    catalog as it is NOW. Returns (promoted, demoted).

    Duplicate is not a property of a file; it is a relation to OTHER rows. The
    unchanged-file skip means a file's own row is not re-examined when a
    different row changes, so a duplicate whose original was edited (new
    hash), failed, or vanished stayed Duplicate with nothing left to deliver
    its content, and was never organized. Reading hashes is the expensive part
    and is not repeated here; this reclassifies from stored values only.

    Per content hash: if any row is Completed, Copied or Processing, the
    content is delivered or in flight, and every Pending or Duplicate row in
    the group is a Duplicate. Otherwise exactly one row — the oldest Pending,
    else the oldest Duplicate — is Pending and the rest are Duplicates. Failed
    rows and removed duplicates take no part. On a catalog built by ordinary
    Index runs this changes nothing; it only repairs groups that drifted.
    """
    delivered_or_in_flight = ANCHOR_DELIVERED_STATUSES + (PhotoStatus.PROCESSING,)
    open_statuses = (PhotoStatus.PENDING, PhotoStatus.DUPLICATE)
    conn = get_db_connection(db_path)
    try:
        groups = {}
        for row_id, sha1, status in conn.execute(
            f"SELECT id, sha1_hash, status FROM photos "
            f"WHERE sha1_hash IS NOT NULL AND sha1_hash != '' "
            f"AND status IN ({sql_values(open_statuses + delivered_or_in_flight)}) ORDER BY id"
        ):
            groups.setdefault(sha1, []).append((row_id, status))

        promote, demote = [], []
        for members in groups.values():
            open_rows = [(i, s) for i, s in members if s in open_statuses]
            if not open_rows:
                continue
            if any(s in delivered_or_in_flight for _, s in members):
                keep = None
            else:
                pending = [i for i, s in open_rows if s == PhotoStatus.PENDING]
                keep = pending[0] if pending else open_rows[0][0]
            for i, s in open_rows:
                wanted = PhotoStatus.PENDING if i == keep else PhotoStatus.DUPLICATE
                if wanted != s:
                    (promote if wanted == PhotoStatus.PENDING else demote).append(i)

        conn.executemany("UPDATE photos SET status = ? WHERE id = ?",
                         [(PhotoStatus.PENDING, i) for i in promote]
                         + [(PhotoStatus.DUPLICATE, i) for i in demote])
        conn.commit()
    finally:
        conn.close()
    return len(promote), len(demote)


def _run_move_or_copy(args, db_path: Path, dest_path: Path, run_id: int) -> str:
    """
    Runs the Pre-flight space check, then the Move/Copy loop, then (Move
    only) duplicate source cleanup. Returns the overall run outcome string.
    Checks cancel_requested between files — never mid-file — so a
    cancellation always lets the file currently being copy-verified finish.
    """
    action_verb = "Moving" if args.move else "Copying"
    logger.info(f"{'Move' if args.move else 'Copy'} Mode enabled. Initiating Pre-flight Space Checks...")
    # This run's durability barriers start unestablished: directories left by
    # an earlier run prove only that mkdir returned, not that their entries
    # reached disk (see _mkdir_durable).
    # The unsupported-fsync notice resets with them, so each run reports its
    # own storage rather than only the first run in a process ever doing so.
    global _destination_root, _unsupported_dir_fsync_reported
    _destination_root = dest_path
    _verified_directories.clear()
    _unsupported_dir_fsync_reported = False
    # FULL rather than the default NORMAL, and this is the only caller that
    # asks. Every delete here commits status=Processing with dest_path BEFORE
    # unlinking, and reconcile_interrupted_state finds interrupted work by that
    # marker alone. Under NORMAL a commit is not fsynced, so a power cut can
    # take the marker while the unlink — which IS fsynced — survives; the next
    # Index then finds a source gone with nothing explaining it and records a
    # successfully delivered photo as Failed. A probe reproduced exactly that.
    #
    # Affordable because this path is already fsync-heavy per file: measured
    # 1.42x here (+1.9ms per photo) against the ~4.4x that NORMAL buys on the
    # scan path, which batches a hundred rows per commit and writes no markers.
    # db_writer_worker keeps NORMAL. The loop's audit rows ride along for free,
    # since log_operation commits immediately here on this same connection.
    conn = get_db_connection(str(db_path), synchronous="FULL")
    cursor = conn.cursor()

    predicate, predicate_params = _targeting_predicate(args)
    # --move also takes Copied rows. A verified copy already exists, so the
    # move completes by deleting the source against it — the already-present
    # branch below re-verifies both sides live first. Without this, --copy
    # followed by --move of an unchanged file could never finish the move.
    eligible = (PhotoStatus.PENDING, PhotoStatus.COPIED) if args.move else (PhotoStatus.PENDING,)
    cursor.execute(
        f"SELECT id, source_path, dest_path, metadata_json FROM photos "
        f"WHERE status IN ({sql_values(eligible)})" + predicate,
        predicate_params
    )
    pending_records = cursor.fetchall()

    # One stat per file, not exists() then stat(): on a network share each is a
    # round trip, all before any data moves. stat() answers both questions, and
    # its failure IS the "missing" case.
    total_bytes_needed = 0
    missing = 0
    already_delivered = 0
    delivered_bytes = 0
    sizes = {}
    for candidate_id, candidate_src, candidate_dst, _ in pending_records:
        try:
            sizes[candidate_id] = os.stat(candidate_src).st_size
        except OSError:
            missing += 1
            continue
        # A row whose recorded destination already holds a file of the same
        # size is not written again: the loop re-verifies both sides live and,
        # for --move, finishes by deleting the source. Budgeting for those
        # bytes aborted Copy-then-Move on a destination with ample room for
        # what the run actually writes. This is only the estimate — the live
        # hash comparison still decides, and a row that does turn out to need
        # writing is caught per file by the copy itself, which fails that one
        # file with a recorded reason and leaves its source intact.
        if candidate_dst:
            try:
                if os.stat(candidate_dst).st_size == sizes[candidate_id]:
                    already_delivered += 1
                    delivered_bytes += sizes[candidate_id]
                    continue
            except OSError:
                pass
        total_bytes_needed += sizes[candidate_id]
    if missing:
        logger.warning(
            f"{missing:,} of {len(pending_records):,} pending file(s) could not be stat'd and are "
            f"excluded from the space estimate. Each will be recorded with its own reason when "
            f"the loop reaches it."
        )
    if already_delivered:
        logger.info(
            f"{already_delivered:,} file(s) are already at the destination "
            f"({delivered_bytes / (1024 ** 2):.2f} MB) and need no new space; each is still "
            f"verified live before anything is deleted."
        )

    space_ok, free_bytes, needed_bytes = verify_sufficient_disk_space(dest_path, total_bytes_needed)
    if not space_ok:
        # A pre-flight abort is a run-level failure and must leave a row: the
        # Error Center reads operations, so a shortfall that only logged was
        # invisible there — the run reported Failed with nothing saying why.
        shortfall = (
            f"Insufficient space at the destination: {needed_bytes / (1024 ** 3):.2f} GB required "
            f"(including the safety margin), {free_bytes / (1024 ** 3):.2f} GB free. Nothing was "
            f"copied, moved or deleted."
        )
        logger.error(f"Aborting: {shortfall}")
        log_operation(conn, run_id, None, str(dest_path), None, PhotoStatus.FAILED, shortfall,
                      commit=False)
        conn.commit()
        conn.close()
        return RunStatus.FAILED

    logger.info(
        f"Disk space verified. {action_verb} {len(pending_records)} items "
        f"({total_bytes_needed / (1024 ** 2):.2f} MB)..."
    )

    source_root = Path(args.source).resolve()
    transfer_started = time.monotonic()
    last_progress_at, last_progress_done, last_progress_bytes = transfer_started, 0, 0
    bytes_done = 0
    was_cancelled = False
    for index, (record_id, src, stored_dst, metadata_json) in enumerate(pending_records):
        if cancel_requested.is_set():
            was_cancelled = True
            remaining = pending_records[index:]
            logger.warning(f"Cancellation requested — logging {len(remaining)} remaining item(s) as Cancelled.")
            for cancelled_id, cancelled_src, cancelled_dst, _ in remaining:
                log_operation(conn, run_id, cancelled_id, cancelled_src, cancelled_dst,
                              OPERATION_CANCELLED)
            break

        # The same recent-rate progress the scan reports, so a long transfer
        # shows its throughput.
        now = time.monotonic()
        if now - last_progress_at >= PROGRESS_INTERVAL_SECONDS:
            log_scan_progress(
                index, len(pending_records), transfer_started,
                window_files=index - last_progress_done,
                window_bytes=bytes_done - last_progress_bytes,
                window_seconds=now - last_progress_at,
                label=f"{action_verb} progress",
            )
            last_progress_at, last_progress_done, last_progress_bytes = now, index, bytes_done
        bytes_done += sizes.get(record_id, 0)

        label = _display_path(src, source_root)
        dst = _destination_for(dest_path, src, metadata_json, stored_dst)

        # Resolve the final filename HERE, immediately before the file is
        # written — not back at Index time. docs/engine-spec.md 4.3 requires the
        # check to happen "before writing to a computed destination path", and
        # the distinction is not academic: at Index time the destination tree
        # is normally empty, so every same-named file is told its name is free.
        # Two different photos named IMG_0001.jpg (two camera cards, say) would
        # both be assigned the identical destination, and the second one moved
        # would silently destroy the first — source already deleted, both
        # operations reporting success. By this point in the run, anything
        # already written is really on disk, so exists() answers truthfully.
        already_present = False
        source_identity = None
        verified_sha1 = None
        resolved_path = Path(dst)
        if resolved_path.exists():
            # Only hash when the name is actually contested — the common case
            # (free name) pays nothing. The source is re-hashed live rather
            # than trusting the indexed value, so a source edited since the
            # last Index can never be mistaken for "already delivered." Its
            # identity is taken first, so an edit after hashing is caught too.
            with contextlib.suppress(OSError):
                source_identity = _file_identity(src)
            verified_sha1 = _sha1_of(Path(src))
            resolved_path, already_present = resolve_destination(Path(dst), verified_sha1)
        resolved_dst = str(resolved_path)
        has_collision = (resolved_dst != dst)

        intent_id = None
        if already_present:
            # An identical copy is already sitting at the destination from an
            # earlier run. Re-copying would just create IMG_0001_1.jpg beside
            # it, and another one next cycle. For --move the operation is still
            # completed by removing the now-redundant source.
            #
            # Logged BEFORE attempting the delete: the delete can fail noisily
            # (a :ro source, say), and having the explanation arrive after the
            # errors it explains makes the log read backwards.
            logger.info(f"Already present at destination, skipping copy: {label} -> {resolved_dst}")
            if args.move:
                # Intent first, as the copy path does, so a crash between the
                # delete and the final update leaves a Processing row that
                # reconciliation settles from what is actually on disk.
                cursor.execute("UPDATE photos SET status = ?, dest_path = ? WHERE id = ?",
                               (PhotoStatus.PROCESSING, resolved_dst, record_id))
                intent_id = ns_db.begin_operation(
                    conn, run_id=run_id, photo_id=record_id, source_path=src,
                    dest_path=resolved_dst, kind="move_already_present",
                    expected={"sha1_hash": verified_sha1, "source_removed": True})
                conn.commit()
                try:
                    if source_identity is None:
                        raise SourceRemovalRefused("the source could not be examined before verification")
                    _remove_verified_source(Path(src), resolved_path, source_identity,
                                            f"Delete already-copied source {Path(src).name}")
                    final_status = PhotoStatus.COMPLETED
                    skip_error = None
                except SourceRemovalRefused as e:
                    final_status = PhotoStatus.FAILED
                    skip_error = f"Source kept: {e}"
                    logger.warning(f"{skip_error} ({src})")
                except Exception as e:
                    final_status = PhotoStatus.FAILED
                    skip_error = f"{type(e).__name__}: {e}"
            else:
                final_status = PhotoStatus.COPIED
                skip_error = None
            # The final state and its audit entry commit together, so a row can
            # never read Completed without the operation that says so.
            cursor.execute(
                "UPDATE photos SET status = ?, dest_path = ? WHERE id = ?",
                (final_status, resolved_dst, record_id)
            )
            log_operation(conn, run_id, record_id, src, resolved_dst, final_status, skip_error,
                          has_collision, commit=False, operation_id=intent_id,
                          step="move_already_present",
                          delivery=dict(source_removed=args.move, created=False,
                                        sha1_hash=verified_sha1) if skip_error is None else None)
            conn.commit()
            continue

        if has_collision:
            logger.info(
                f"Destination name already taken by different content — writing "
                f"{Path(dst).name} as {Path(resolved_dst).name} instead."
            )
            cursor.execute(
                "UPDATE photos SET dest_path = ?, has_name_collision = 1 WHERE id = ?",
                (resolved_dst, record_id)
            )

        # DO NOT BATCH THE COMMITS IN THIS LOOP. Unlike the scan phase (see
        # db_writer_worker, which does batch), these commits are not
        # bookkeeping — they are the crash-recovery protocol. The 'Processing'
        # marker must be DURABLE BEFORE the filesystem is touched, because
        # reconcile_interrupted_state() finds interrupted work by looking for
        # rows stuck in exactly this status and then inspecting the filesystem
        # to decide what really happened.
        #
        # Defer this commit and a kill mid-copy leaves the row reading
        # 'Pending' for a file that has already been moved and deleted from
        # source. Reconciliation never examines it, the next run tries to move
        # a source that no longer exists and records Failed — while the photo
        # sits safely at the destination, unrecorded. That is the one way this
        # engine can genuinely lose track of a file it migrated successfully.
        #
        # The fsync cost this would otherwise pay is addressed instead by
        # synchronous=NORMAL (see get_db_connection), which keeps the ordering
        # guarantees intact against process death.
        #
        # dest_path is written WITH the marker: reconciliation reads it to find
        # the partial and decide what happened, so it must name where this
        # file is actually being written, not where the catalog last put it.
        cursor.execute("UPDATE photos SET status = ?, dest_path = ? WHERE id = ?",
                       (PhotoStatus.PROCESSING, resolved_dst, record_id))
        intent_id = ns_db.begin_operation(
            conn, run_id=run_id, photo_id=record_id, source_path=src, dest_path=resolved_dst,
            kind="move" if args.move else "copy",
            expected={"source_removed": bool(args.move), "created": True})
        conn.commit()

        # --move deletes the verified source (delete_source=True, the
        # default); --copy leaves it untouched (delete_source=False).
        verified_content = {}
        success, error_message = copy_verify_delete(src, resolved_dst, delete_source=args.move,
                                                    label=label, verified_content=verified_content)

        if args.move:
            final_status = PhotoStatus.COMPLETED if success else PhotoStatus.FAILED
        else:
            final_status = PhotoStatus.COPIED if success else PhotoStatus.FAILED
        cursor.execute("UPDATE photos SET status = ? WHERE id = ?", (final_status, record_id))
        log_operation(conn, run_id, record_id, src, resolved_dst, final_status, error_message,
                      has_collision, commit=False, operation_id=intent_id,
                      step="move" if args.move else "copy",
                      delivery=dict(source_removed=args.move, created=True,
                                    sha1_hash=verified_content.get("sha1_hash")) if success else None)
        conn.commit()

    if args.move and not was_cancelled:
        # Duplicate source-file removal is a --move-only step. It's
        # deliberately gated on status='Completed', which only a --move
        # run ever produces (--copy runs produce 'Copied' instead) — so
        # this block naturally never touches anything from a --copy run,
        # keeping --copy fully non-destructive as intended, with no
        # separate mode check needed here. Skipped entirely if this run was
        # cancelled, since acting on duplicates from a run that didn't
        # finish its primary moves could delete a source file whose "kept"
        # copy was itself never confirmed. Every deletion below additionally
        # requires live bytes on both sides to match — see the verification
        # block.
        # Scoped to whatever this run targeted: a two-file --file-ids move
        # must never delete duplicate sources outside the user's selection.
        cursor.execute(
            f"SELECT id, source_path, sha1_hash FROM photos WHERE status = '{PhotoStatus.DUPLICATE}'"
            + predicate,
            predicate_params
        )
        duplicate_records = cursor.fetchall()
        removed_count = 0
        for index, (record_id, dup_src_str, sha1_hash) in enumerate(duplicate_records):
            # Checked before each duplicate, as the copy loop checks before
            # each file: the one in progress finishes, nothing further starts.
            if cancel_requested.is_set():
                was_cancelled = True
                remaining = duplicate_records[index:]
                logger.warning(f"Cancellation requested — {len(remaining)} duplicate(s) left in "
                               f"place and recorded as Cancelled.")
                for cancelled_id, cancelled_src, _ in remaining:
                    log_operation(conn, run_id, cancelled_id, cancelled_src, None,
                                  OPERATION_CANCELLED, commit=False)
                conn.commit()
                break

            dup_src = Path(dup_src_str)
            if not dup_src.exists():
                continue  # already gone (e.g. handled in a prior run)

            # Every row recording a delivered copy of this content, not just
            # the first. LIMIT 1 could pick a row whose file has since been
            # edited or removed and conclude there is no copy, while another
            # row names a copy that is still byte-perfect.
            cursor.execute(
                f"SELECT DISTINCT dest_path FROM photos WHERE sha1_hash = ? "
                f"AND status = '{PhotoStatus.COMPLETED}' AND dest_path IS NOT NULL",
                (sha1_hash,)
            )
            candidates = [row[0] for row in cursor.fetchall()]
            if not candidates:
                # Nothing delivered to verify against, so the source stays.
                # Recorded as an outcome, not only logged: a duplicate selected
                # without its original otherwise ended the run with no trace.
                reason, pointer = _duplicate_skip_reason(cursor, sha1_hash, copying=False)
                logger.info(f"Kept duplicate source {_display_path(dup_src_str, source_root)}: {reason}")
                log_operation(conn, run_id, record_id, dup_src_str, pointer, OPERATION_SKIPPED, reason)
                continue

            # Verify LIVE BYTES on both sides before deleting anything.
            #
            # The catalog's hashes identify candidates; they do not prove the
            # files still match. Either side can have changed since the Index
            # that recorded them — the source edited in place, or the
            # destination copy modified or truncated by something outside this
            # engine — and the previous code checked only that the destination
            # path existed. A file that exists is not a file that matches, so
            # an edited destination was enough to authorize deleting the last
            # remaining copy of a photo.
            #
            # An unreadable candidate must never count as a match either: a
            # permission error or an I/O fault is an absence of evidence, not
            # evidence of a good copy.
            try:
                source_identity = _file_identity(dup_src)
                source_sha1 = compute_sha1(dup_src_str)
                verified = None
                read_error = None
                for candidate in candidates:
                    try:
                        if compute_sha1(candidate) == source_sha1:
                            verified = candidate
                            break
                    except OSError as e:
                        read_error = e
                if verified is None:
                    if read_error is not None:
                        raise read_error
                    raise ValueError(
                        "ChecksumMismatch: duplicate source and destination no longer match"
                    )
            except Exception as e:
                # Recorded, not merely logged. The photo stays Duplicate so a
                # later run can retry it once the cause is addressed, and the
                # operations row is what the Error Center reads — a warning in
                # the log is invisible to it.
                error_message = f"Duplicate verification failed: {type(e).__name__}: {e}"
                logger.warning(f"{error_message} — leaving source file in place: {dup_src}")
                log_operation(conn, run_id, record_id, dup_src_str, candidates[0],
                              PhotoStatus.FAILED, error_message)
                continue

            # Intent before the delete, with dest_path naming the copy that
            # verified. That pointer is also how reconciliation tells an
            # interrupted duplicate removal (the destination belongs to another
            # row) from an interrupted move of a row's own file.
            cursor.execute("UPDATE photos SET status = ?, dest_path = ? WHERE id = ?",
                           (PhotoStatus.PROCESSING, verified, record_id))
            dup_intent_id = ns_db.begin_operation(
                conn, run_id=run_id, photo_id=record_id, source_path=dup_src_str,
                dest_path=verified, kind="duplicate_removal",
                expected={"sha1_hash": source_sha1, "source_removed": True})
            conn.commit()
            try:
                _remove_verified_source(dup_src, Path(verified), source_identity,
                                        f"Deleting verified duplicate {dup_src.name}")
            except Exception as e:
                # Recorded like a verification failure, for the same reason:
                # the source stays, and the operations row is the only thing
                # the Error Center can read to say why. The source is still
                # there, so the row goes back to Duplicate.
                if isinstance(e, SourceRemovalRefused):
                    error_message = f"Source kept: {e}"
                else:
                    error_message = f"Duplicate removal failed: {type(e).__name__}: {e}"
                logger.warning(f"{error_message} — {dup_src}")
                cursor.execute("UPDATE photos SET status = ? WHERE id = ?",
                               (PhotoStatus.DUPLICATE, record_id))
                log_operation(conn, run_id, record_id, dup_src_str, verified,
                              PhotoStatus.FAILED, error_message, commit=False,
                              operation_id=dup_intent_id, step="duplicate_removal")
                conn.commit()
                continue
            cursor.execute("UPDATE photos SET status = ?, dest_path = ? WHERE id = ?",
                           (PhotoStatus.REMOVED_DUPLICATE, verified, record_id))
            log_operation(conn, run_id, record_id, dup_src_str, verified,
                          PhotoStatus.REMOVED_DUPLICATE, commit=False,
                          operation_id=dup_intent_id, step="duplicate_removal",
                          delivery=dict(source_removed=True, created=False, sha1_hash=source_sha1))
            conn.commit()
            removed_count += 1
            logger.info(f"Removed duplicate source file: {dup_src} (verified copy at {verified})")

        if duplicate_records:
            logger.info(f"Duplicate cleanup: removed {removed_count} of {len(duplicate_records)} flagged duplicates.")

    if args.copy and not was_cancelled:
        # --copy never writes a duplicate: its original carries the content.
        # Record that for each duplicate in scope, so every selected photo has
        # an outcome. A selection holding only duplicates otherwise did
        # nothing, exited 0 and recorded nothing — which a UI shows as success.
        cursor.execute(
            f"SELECT id, source_path, sha1_hash FROM photos WHERE status = '{PhotoStatus.DUPLICATE}'"
            + predicate,
            predicate_params
        )
        for record_id, dup_src_str, sha1_hash in cursor.fetchall():
            reason, pointer = _duplicate_skip_reason(cursor, sha1_hash, copying=True)
            log_operation(conn, run_id, record_id, dup_src_str, pointer, OPERATION_SKIPPED, reason,
                          commit=False)

        # A photo an EARLIER run delivered is not a copy candidate and is not a
        # duplicate either, so a selection naming it finished with no record at
        # all — the same silence §5.3 objects to for duplicate-only selections.
        # The reason states what the catalog holds: this run read and verified
        # nothing, so it must not be shown as confirmation that the destination
        # file is still present and intact.
        #
        # Excluding what this run already recorded is what keeps "earlier" true.
        # This runs after the copy loop, by which point the rows it just wrote
        # are themselves 'Copied', and without the exclusion every delivered
        # photo ended its own job with two contradictory outcomes. Keying on
        # this run's operations rather than a list of copied ids also covers
        # the files it failed or cancelled: one outcome per photo per run.
        cursor.execute(
            f"SELECT id, source_path, dest_path FROM photos WHERE status = '{PhotoStatus.COPIED}'"
            + predicate
            + " AND id NOT IN (SELECT photo_id FROM operations "
              "WHERE run_id = ? AND photo_id IS NOT NULL)",
            tuple(predicate_params) + (run_id,)
        )
        for record_id, copied_src, copied_dst in cursor.fetchall():
            log_operation(
                conn, run_id, record_id, copied_src, copied_dst, OPERATION_SKIPPED,
                f"Already copied to {copied_dst} by an earlier run, so there is nothing to copy; "
                f"this run re-verified nothing. Index reads sources, never the destination — if "
                f"that file is missing, re-index with --force-rehash and copy again. Use --move "
                f"to finish moving it.",
                commit=False
            )
        conn.commit()

    # Point every duplicate at the copy that actually exists.
    #
    # A Duplicate row keeps the dest_path projected for it at Index time — a
    # path under its OWN filename that is never written, because only Pending
    # rows are copied. The row therefore described a file that does not exist,
    # which is useless precisely when it matters: answering "this source file
    # was a duplicate, so where did its content actually end up?"
    #
    # Rewriting it to the surviving copy's real path makes each duplicate
    # record a usable pointer. The group is already queryable by sha1_hash;
    # this makes each member individually answerable too. Runs after the
    # move/copy loop and duplicate cleanup, so the anchor's dest_path is final
    # (collision suffixes included) rather than still a projection.
    if not was_cancelled:
        cursor.execute(
            "UPDATE photos SET dest_path = ("
            "    SELECT anchor.dest_path FROM photos AS anchor"
            "     WHERE anchor.sha1_hash = photos.sha1_hash"
            f"       AND anchor.status IN ({sql_values(ANCHOR_DELIVERED_STATUSES)})"
            "     LIMIT 1)"
            # Duplicate only. A Removed_Duplicate row already names the copy
            # its deletion was verified against; overwriting it with the first
            # delivered row found could point it at a different, stale copy.
            f" WHERE status = '{PhotoStatus.DUPLICATE}'"
            "   AND EXISTS ("
            "    SELECT 1 FROM photos AS anchor"
            "     WHERE anchor.sha1_hash = photos.sha1_hash"
            f"       AND anchor.status IN ({sql_values(ANCHOR_DELIVERED_STATUSES)}))" + predicate,
            predicate_params
        )
        if cursor.rowcount:
            # Deliberately does NOT say "verified". This step only rewrites a
            # pointer from the catalog; it reads no files. The one place that
            # acts destructively on that pointer — duplicate cleanup above —
            # hashes both sides live before deleting anything, and that is
            # where the guarantee lives. Claiming verification here would be
            # the same overstatement this function's caller exists to prevent.
            logger.info(
                f"Repointed {cursor.rowcount} duplicate record(s) at the destination recorded "
                f"for their content."
            )
        conn.commit()

    if was_cancelled:
        # Each loop above records what it abandoned — but only for the pass it
        # was in. A cancellation during the primary transfers sets this flag,
        # which then skips the duplicate pass (--move) and the skipped-outcome
        # pass (--copy) outright, so every duplicate in the selection, and
        # every already-delivered file in a --copy selection, ended the run
        # with no row at all. Not Cancelled — nothing. That is the same
        # silence §5.3 objects to, and it breaks the promise the block above
        # states in its own comment: every selected photo has an outcome.
        #
        # Reconciling the selection against what was actually recorded keeps
        # that promise for whatever the loops never reached, without either
        # pass having to know what the other did. The statuses are the ones
        # this run's selections were drawn from; anything those passes did
        # handle already carries an operations row for THIS run and is
        # excluded by it. Keying on the recorded rows rather than re-deriving
        # scope from status is what makes that reliable — the loops rewrite
        # status as they go, so by here it no longer describes the selection.
        cursor.execute(
            f"SELECT id, source_path FROM photos "
            f"WHERE status IN ({sql_values(CANCELLABLE_SELECTION_STATUSES)})" + predicate
            + " AND id NOT IN (SELECT photo_id FROM operations "
              "WHERE run_id = ? AND photo_id IS NOT NULL)",
            tuple(predicate_params) + (run_id,)
        )
        unreached = cursor.fetchall()
        for record_id, unreached_src in unreached:
            # No dest_path recorded: this run neither wrote nor verified
            # anything for this file, and a Duplicate row's stored dest_path
            # is an Index-time projection that was never written. Naming it
            # here would point the audit record at a file that does not exist.
            log_operation(conn, run_id, record_id, unreached_src, None, OPERATION_CANCELLED,
                          "The run was cancelled before this file was reached. Nothing was "
                          "attempted on it and nothing about it changed.",
                          commit=False)
        if unreached:
            conn.commit()
            logger.info(f"Cancellation: {len(unreached)} selected file(s) were never reached and "
                        f"are recorded as Cancelled.")

    conn.close()

    if was_cancelled:
        logger.info(f"{'Move' if args.move else 'Copy'} operation cancelled by user request.")
        return RunStatus.CANCELLED

    logger.info(f"All {'move' if args.move else 'copy'} operations finished.")
    return RunStatus.COMPLETED


if __name__ == "__main__":
    main()
