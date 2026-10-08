"""
Project: NegativeSpace (Core Engine)
Description: A backend engine for organizing large photo collections based on spec.
Run it as `python -m engine` from the folder holding this package.

Package layout, by area: cli (arguments and the job each mode runs), scan (Index),
transfer (Copy and Move), relocate (Rename, Reject, Return to library), reconcile
(settling interrupted work at the start of every job), durable (copy-verify-delete and
the fsync steps), store (catalog writes), fileinfo (dates, metadata, hashes), thumbnails,
destinations, targeting (which photos a run acts on), jobs, maintenance, backups,
runtime (shared run state), workers (cancellable read-only pools), constants and deps; ns_db (the catalog schema and its rules,
shared with the web API), review (catalog-only review decisions), and the ns_similarity modules.

Modules refer to one another as `module.name`, never `from module import name`: one
binding per name, so replacing a function (a test injecting a fault) replaces it for
every caller, and modules may import each other in either order (Google Python Style
Guide 2.2, "use import statements for packages and modules only"). A leading underscore
marks a name internal to the engine, not to its module.

Runtime Arguments:
Source and destination must be separate, non-overlapping underlying folders.
Never mount the same folder at both paths or nest one inside the other,
including on network shares. Overlapping mounts can cause unintended file
deletion and are not reliably detected by the engine.

- --review-decision (Optional) Record one catalog-only review decision from JSON stdin,
  under the engine lock. Returns JSON; never changes photo bytes or transfer status.

- -h / --help: show all arguments and exit without starting a job.
- --source <path> (Optional) Path to unorganized source directory (default: "/data/source").
- --dest <path> (Optional) Path for organized output directory (default: "/data/dest").
- --base <path> (Optional) Base directory for app artifacts (default: "/appdata").
  Creates/uses <base>/db/ for SQLite and <base>/logs/ for logs.
- --workers <N> (Optional) Override the worker process count used for
  hashing/date resolution (default: the CPUs the container may use,
  ns_db.available_cpus()).
- --exts <.ext1,.ext2,...> (Optional) Comma-separated extension list,
  replacing the built-in default set for directory scanning. Has no effect
  on --file-ids targeting, since that bypasses directory scanning entirely.
- --file-ids <id1,id2,...> (Optional) Comma-separated database row IDs to
  target, bypassing the directory scan and processing exactly these
  already-cataloged files. A file must have gone through at least one prior
  Index for its ID to exist. This is what powers selection-scoped
  operations from the CLI — e.g. "Move just these 3 photos". The command
  line has a length limit, so the web UI passes its selections with
  --file-ids-from instead. Either way the ids are recorded with the run
  (run_selections). Mutually exclusive with --file-ids-from and --source-subdir.
- --file-ids-from <path> --request-id <id> (Optional) The same, read from a
  selection file (ns_db.write_selection_file) of any size. The job is
  refused whole, touching nothing, if the file is damaged or names a photo
  no longer catalogued in this source.
- --request-id <id> (Optional) Caller-chosen submission ID, stored with the run.
  Repeating the ID with identical arguments starts nothing and reports the existing
  run; different arguments are refused. A deliberate new attempt needs a new ID.
  Required with --file-ids-from, whose contents must name this same ID.
- --source-subdir <path> (Optional) Path, relative to --source, scoping the
  run to already-cataloged files beneath it. Queries the catalog by
  source_path prefix instead of walking the filesystem or enumerating IDs.
  Mutually exclusive with --file-ids and --file-ids-from.
- --cache <path> (Optional) Generated thumbnails and previews (default: /cache).
  Reproducible from the photos, so safe to delete and to leave out of backups.
- --backups <path> (Optional) Catalog backups (default: /backups). Must be separate
  storage from --base: a backup inside what it backs up dies with it.
- --no-thumbnails: skip thumbnail generation during the scan; the gallery shows
  placeholders until a later run makes them.
- --force-rehash: re-read every file even if its size and modification time are
  unchanged since the last Index (normally such files are skipped unread).
- --confirm-network-destination: Move to a network-share destination anyway. Without it
  a Move there stops before copying or deleting and asks; confirm only for a share
  exported 'sync', or use --copy.
- --confirm-source-empty: answer that an empty --source really is empty, not unplugged.

Per-file failures never abort a run: an unreadable, vanished, or otherwise
unprocessable file is recorded as status='Failed' with a human-readable
reason in operations.error_message, and the scan carries on with the rest.
Photo formats must have decodable pixels to become eligible for Copy/Move. Missing
EXIF or a cache-write failure alone does not prevent organization; failed sources
remain untouched and a later Index reassesses them after external correction.

Mode flags (mutually exclusive — pick at most one; omitting all runs the
default Index):
- --move: Execute physical migration (Copy-Verify-Delete). Source files are
  moved: deleted after a verified copy lands at the destination. Confirmed
  exact duplicates are also removed from source once a verified copy of
  their content exists elsewhere at the destination.
- --copy: Non-destructive. Same verified Copy-Verify step as --move, but the
  source file is never deleted or modified afterward. Duplicate source files
  are also left untouched in this mode — nothing is ever removed from source.
- (none of these): Index — full scan, hashing, and destination-path
  resolution, exactly like --move/--copy would compute, but no physical
  action is taken. This is the safe default described in spec §4.1.
- --preview PHOTO_ID / --clear-previews: make one 1024px detail preview, or
  remove them all. Cache only; no run, no engine lock.
- --backup-now: one manual catalog backup, under the engine lock.
- --rebuild-thumbnails missing|all: a job that makes grid thumbnails from any
  catalogued copy, under the engine lock.
- --check-destination quick|full: a read-only job that reports what under --dest
  is missing, changed, unreadable or not put there by NegativeSpace.
- --rename PHOTO_ID --name NAME [--dry-run] / --rename-candidates PHOTO_ID: give a
  delivered file a new name, or list the names its duplicate group carried.
- --reject / --return-to-library, with --file-ids(-from) or --source-subdir: move organized
  photos from dest/library to dest/rejects, or back (spec §9.5). Nothing is deleted.
- --repair-similarity missing|comparisons: recover missing visual hashes from
  destination originals, or resume stored-hash comparisons; never edits photos.
  --repair-photo PHOTO_ID limits the missing-hash recovery to one photo.

Cancellation: sending SIGTERM or SIGINT (e.g. `docker stop`, or Ctrl+C)
during a --move/--copy run lets the file currently being copy-verified
finish, then stops before starting the next one. During the Index/scan
phase it stops read-only workers and their decoder children; a scan cancelled that
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

Unfinished Index results may need rescanning after a crash: results are saved
in batches, and an unsettled run does not have the durability guarantee of a
settled run (TODO.md claim 12). Index never modifies source photos. A run
interrupted by something uncatchable (SIGKILL, OOM-kill, power loss) leaves its `runs` row
in an active state (Preparing, Running or Cancelling) — the next invocation's
startup reconciliation marks it 'Interrupted' and records itself as the run
that found it, rather than leaving a phantom "still running" entry forever.
The end time stays unknown: reconciliation is when the death was noticed.

Worker pools (`workers.py`) isolate decoder process groups for user-requested
cancellation; an uninterruptible filesystem call may still delay shutdown.
Transfer verification and deletion never run inside those pools.

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
       curated subset) — the primary source, always available because the
       engine refuses to start without it.
       The only method that can read metadata from RAW-family files
       (.cr2, .nef, .arw, .raf, .raw, .dng), since neither PIL nor rawpy
       expose EXIF/metadata fields for those formats (rawpy only decodes
       pixel data, for pHash generation — it has no metadata-reading API
       at all).
    2. PIL (Image.getexif(), PLUS the "Exif" sub-IFD via get_ifd(0x8769))
       — a defensive per-FILE fallback, not an "ExifTool is missing"
       fallback, which cannot happen (see above). Used
       only if ExifTool genuinely ran but returned nothing usable for a
       specific file. Works for standard formats (JPEG, PNG, TIFF, HEIC
       with pillow-heif); cannot open RAW-family formats at all.
    3. File modification time — used only if neither of the above
       produces a usable capture date. Keep any metadata already extracted,
       and mark date_source as mtime; the scan adds the resolved date_taken.
       Re-indexing uses the original source snapshot's mtime when available.

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
