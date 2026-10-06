"""Settings, limits and the status sets the engine works with."""

import errno

from engine.ns_db import PhotoStatus, REJECTED_STATUSES
from engine import ns_db


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
# How often the drawer's progress snapshot is written (webui-spec 4.1: about once a second).
PROGRESS_SNAPSHOT_SECONDS = 1.0
SHA1_CHUNK_SIZE = 65536
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0  # Seconds
# The formats the engine reads live in ns_db (RAW_EXTENSIONS, RASTER_EXTENSIONS,
# SUPPORTED_EXTENSIONS), shared with the API's settings validation.
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
# The Inspector's detail preview: generated on first view, never at Index
# (webui-spec 4.2.1), so only photos someone opens pay for it.
PREVIEW_SIZE = 1024
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

# Exit codes for a run started with --request-id that did NOT start work. Both
# are distinct from 1 (failed) so the caller can tell "already accepted" and
# "ID reused for different input" apart from an engine error without parsing
# the log. Neither creates a run, touches a file or reconciles earlier work.
EXIT_REQUEST_CONFLICT = 3
EXIT_REQUEST_ALREADY_ACCEPTED = 4

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
# for an export that is the download date, so photos from the 2000s would land
# in 2024/ and 2025/ folders. Those files go here instead,
# subdivided by year so the folder stays navigable at ~8% of a library without
# the tree ever claiming to know when the photograph was taken.
#
# The year comes from the file's own modification time. That is a real fact
# about the FILE even when it is not a fact about the PHOTOGRAPH, which is
# exactly why it may organise the folder but must not name a date folder.
UNDATED_FOLDER = "Undated"

# The CPUs this container may really use, not the host's count: a --cpus quota or
# --cpuset-cpus set is invisible to os.cpu_count() (ns_db.available_cpus).
MAX_WORKER_PROCESSES = ns_db.available_cpus()["available"]

# Statuses that mean "already delivered to the destination and verified".
ANCHOR_DELIVERED_STATUSES = (PhotoStatus.COMPLETED, PhotoStatus.COPIED,
                             PhotoStatus.FOUND_AT_DESTINATION)

# Statuses in which a row can stand as the original of its duplicate group:
# its content is delivered, being delivered, or queued to be.
ANCHOR_STATUSES = (PhotoStatus.PENDING, PhotoStatus.PROCESSING) + ANCHOR_DELIVERED_STATUSES

# Statuses that represent a settled record — the file has been examined and
# its row is trustworthy. partition_unchanged() will only skip re-reading a
# file whose row is in one of these; anything mid-flight or failed is always
# rescanned rather than trusted on the strength of a stat.
SETTLED_STATUSES = (
    PhotoStatus.PENDING, PhotoStatus.COMPLETED, PhotoStatus.COPIED,
    PhotoStatus.DUPLICATE, PhotoStatus.REMOVED_DUPLICATE, PhotoStatus.FOUND_AT_DESTINATION,
) + REJECTED_STATUSES

# Statuses whose source file is legitimately gone: see ns_db.SOURCE_CONSUMED_STATUSES.
SOURCE_CONSUMED_STATUSES = ns_db.SOURCE_CONSUMED_STATUSES

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
