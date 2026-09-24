# Engine Design Specification: NegativeSpace (`ns-engine.py`)

This specification covers the processing engine: everything that reads source
files, computes hashes and metadata, decides where a photo belongs, moves or
copies it, and owns the SQLite catalog. The browser-facing half of the project
is specified in [webui-spec.md](./webui-spec.md), and the project's scope
boundary, architecture and component status in
[project-spec.md](./project-spec.md).

## 1. Scope and Role

The engine is the workhorse. It runs as a standalone CLI process; the web UI's
API layer invokes it as a child process rather than replacing it, which is why
its flags stay documented and usable even though end users never type them
(see `webui-spec.md` §1).

**The engine is the only component that touches photo files.** It owns the catalog schema and writes photo state and operation history. The
browser accesses neither SQLite nor photo files directly. The API writes settings through shared database/validation code; the web UI
manages them without direct browser access to SQLite. See §9.8.

**Two properties shape every decision below**, and both are stated in
`project-spec.md` §1:

*   **The `YYYY/MM/DD` tree is for the human browsing the filesystem**, not a
    contract with any consuming application. Folder-layout questions are
    usability questions, not correctness ones.
*   **Metadata correctness is a deliverable.** A consuming gallery reads EXIF
    from the files themselves, never from this project's catalog — which is
    local and includes irreplaceable operation history. A date this project knows but the file
    does not is a date the gallery will get wrong. That is what eventually
    forces metadata corrections out of the catalog and into the files (or
    sidecars beside them); see §9.

## 2. Operational Modes

Three mutually exclusive modes — at most one flag; the engine refuses to start
if more than one is given. Full detail in §4.1.

| Mode | Flag | Source files | Destination |
| :--- | :--- | :--- | :--- |
| **Index** (default) | *(none)* | Untouched | Nothing written |
| **Move** | `--move` | Deleted after a verified copy lands; confirmed exact duplicates also removed | Files organized into `YYYY/MM/DD`, or `Undated/<year>/` when undatable |
| **Copy** | `--copy` | Never touched — fully non-destructive | Same as Move |

A photo with no usable EXIF date is filed under `Undated/<year>/` rather than
into the date tree, by the file's modification time — which organises the
folder without the tree ever claiming to know when the photograph was taken.
The decision and its reasoning are in `webui-spec.md` §3.1.

## 3. Engine Architecture

Handles filesystem crawling (or targeted ID lookup), EXIF/full-metadata
extraction, SHA1/pHash generation, and physical file manipulation.

### 3.1. Concurrency

*   A `ProcessPoolExecutor` (sized to `os.cpu_count()`, overridable via `--workers`) parallelizes hashing and metadata extraction across CPU cores.
*   A Producer-Consumer model hands results to a single dedicated background thread, which is the *only* thread that ever writes to SQLite — this is what guarantees the "single writer" thread-safety requirement in §7, rather than relying on SQLite's own locking alone.

### 3.2. Invocation

Runs as a standalone CLI process. The web UI's API layer spawns it as a child
process, passing `--file-ids` or `--source-subdir` for selection-scoped
operations, and sends `SIGTERM` for graceful cancellation. That layer is the
only thing that talks to both the engine and the database directly; the
frontend talks only to it. Argument construction across that boundary is a
security concern, specified in `webui-spec.md` §5.6.

### 3.3. Key Libraries and Hard Requirements

*   `Pillow` (+ `pillow-heif` for HEIC) — standard-format image decoding and EXIF reads.
*   `imagehash` — pHash generation.
*   `rawpy` — RAW-family pixel decoding, required for pHash generation on `.raw/.dng/.cr2/.nef/.arw/.raf` files (Pillow cannot open these formats at all).
*   `ExifTool` (external system binary + `PyExifTool` Python wrapper) — **hard requirement**, not optional. Invoked as a persistent per-worker process (`-stay_open` mode) rather than a fresh subprocess per file — measured directly at roughly a 30x reduction in per-file ExifTool overhead (~74ms → ~2.5ms) for the ExifTool call itself. The only method in the engine that can read metadata from RAW-family files. The engine refuses to start if either the binary or the Python package is missing, rather than silently degrading — see §4.2 for exactly what it's used for and why Pillow/rawpy/imagehash are still required alongside it, not replaced by it.

## 4. Functional Requirements
### 4.1. Input & Configuration
*   **Source/destination separation:** The underlying source and destination folders must be distinct and non-overlapping: neither may contain the other. Different container paths are insufficient if their host folders or network-share mappings overlap. This applies to local storage and NFS alike. Overlapping mounts are unsupported and can cause unintended processing or deletion. The engine refuses to start when it can see the overlap — the same folder, one inside the other, or one directory reachable at both paths — and refuses to delete any source that is the same file as its copy. It cannot see every alias (two separate network mounts of one share look like different storage), so document this deployment requirement; do not promise automatic detection of every mount alias.
*   **One catalog per destination:** the single-instance lock is scoped to `--base`, so two installations with different `--base` directories are not serialised against one another. Sharing one `--dest` between them is unsupported. It is not a content-safety hazard — every deletion still requires the deleting engine's own live verification of the copy it made — but it produces unexplained failures: one catalog's crash recovery removes partials by target name and can delete a partial the other is still writing; both can resolve the same free collision name and one loses the no-overwrite publish; and duplicate detection is per-catalog, so identical content can be delivered twice under different names. Several sources feeding one destination is the supported shape of that need: one catalog, several runs.
*   **Path Definitions:** `--source` (default `/data/source`), `--dest` (default `/data/dest`), `--base` (default `/appdata`, holding `<base>/db/ns_sqlite.db` and `<base>/logs/organizer.log`), `--cache` (default `/cache`, holding generated thumbnails under `<cache>/thumbnails/`), and `--backups` (default `/backups`, holding catalog backups; see Catalog backups below). `--cache` is deliberately outside `--base`: everything under it is reproducible from the photos themselves and is excluded from backups, while everything under `--base` is not.
*   **Tuning:**
    *   `--workers <N>` — overrides the `ProcessPoolExecutor` worker count (default: `os.cpu_count()`).
    *   `--exts <.ext1,.ext2,...>` — overrides the default extension set for directory scanning. Has no effect on `--file-ids` targeting.
    *   `--force-rehash` — re-reads every targeted file in full even when the catalog already holds a current record for it, bypassing the unchanged-file skip described in §4.2. For the case where content changed without size or mtime moving; not something editors do in practice, but verification should not require deleting the catalog.
    *   `--cache <path>` — where generated thumbnails are written (default `/cache`). Written by the scan phase, which every mode begins with; the transfer phase itself never touches it. A cache root that cannot be created disables generation for that run with a warning rather than failing an otherwise good Index.
    *   `--no-thumbnails` — skips thumbnail generation entirely. Cataloguing, hashing and content identity are unaffected; only the cache writes stop. Useful when indexing purely to refresh the catalog, and for runs on storage where the cache is not mounted.
    *   `--preview <photo_id>` — makes the 1024px detail preview for one catalogued photo if it is not cached yet, and prints one line of JSON: `photo_id`, `availability` (`present`, `failed` or `unavailable`), `cache_filename` (relative to `--cache`), `bytes`, `reused`, `failure_category` and `failure_detail`. It exits `0` when a preview is present and `1` otherwise. The web API calls it when a photo is opened (`webui-spec.md` §4.2.1), so image decoding and every catalog write other than settings stay in the engine. It starts no run and **takes no engine lock**: it changes no photo file, only one disposable cache image and its `thumbnail_cache` row, written in a single short transaction, so a photo can be opened while a job runs. The preview is keyed on content, so identical copies share one. It is made from a delivered destination copy first, then a source that still exists, and only from a copy whose size and modification time still match the catalog, so an edited file never produces the preview for different content. A cached preview is served even when no usable copy remains. Nothing is logged to the console, so stdout carries only the answer. Measured end to end on a ~1,200-file sample, engine start included: a first view has a median of 110–195ms per format (JPEG, CR2, DNG, WebP, PNG, TIFF), and a cached repeat takes about 85ms.
    *   `--clear-previews` — the web UI's **Free up** (`webui-spec.md` §4.2.1): removes every recorded detail preview and prints one line of JSON, `removed`, `bytes_freed` and `not_removed`. It exits `1` when any file could not be removed. Grid thumbnails stay, and so do recorded preview failures, which name no file and keep the reason a photo has no preview. Only files the catalog records are removed, so the space freed matches the per-size total the page showed. Each file goes before its record, and a file that cannot be removed keeps its record. Like `--preview`, it starts no run and takes no engine lock. If it races a preview request, the worst case is a record whose file is gone, and the next request regenerates it.
    *   `--rebuild-thumbnails missing|all` — the web UI's grid repair and rebuild (`webui-spec.md` §4.2.1). A job: it takes the engine lock, opens a `REBUILD` run, reconciles interrupted work first, honours cancellation between batches and settles `Completed`, `Cancelled` or `Failed`. It needs no `--source`. `missing` makes the grid thumbnails not on disk, and `all` regenerates every one. Each is made from `catalogued_copies`: a delivered destination copy first, then a live source, and only one whose size and modification time still match the catalog. Under `all`, an existing thumbnail is replaced only when a copy supplies a new one, never discarded for lack of one. It uses `--workers` like a scan, records no operation, takes no backup, and exits `1` only when the run Failed. Refused with `--no-thumbnails`.
    *   The database write-queue size is intentionally **not** configurable — left as a hardcoded internal constant rather than exposed, since there was no concrete need identified for tuning it separately from `--workers`.
*   **Targeted Processing** (mutually exclusive with each other — pick at most one, or omit both for a full directory scan):
    *   `--file-ids <id1,id2,...>` — comma-separated `photos.id` values from a prior Index. Bypasses the directory scan entirely; looks up each ID's `source_path` directly and processes exactly those files. IDs not found in the database are logged as a warning and skipped, not treated as fatal. This is what a web UI's individual/multi-select maps onto, but works identically from the CLI.
    *   `--source-subdir <path>` — scopes the operation to every already-indexed file whose `source_path` falls under this directory, recursively. Queries the existing `photos` catalog by prefix rather than re-walking the filesystem, which means it inherently excludes symlinks (they were already excluded at the original Index that populated those rows) and — critically — avoids passing a large ID list as a command-line argument at all. This is the mechanism behind the web UI's "select a folder" option, and the recommended path for large selections instead of enumerating thousands of individual `--file-ids` (see `webui-spec.md` §2 for the UI-side selection-size limit this replaces for bulk operations). Only reflects files known as of the last Index over that path — newly added files need a rescan first, same as the whole-library case. The prefix match is a literal, case-sensitive range comparison on the path, not SQL `LIKE`: `LIKE` treats `%` and `_` as wildcards (`My_Photos` would match `MyXPhotos`) and ignores letter case (`Album` would match `album`), and under `--move` either one would delete sources the user never selected. Both the Index-mode rescan and the Move/Copy targeting share one builder so they cannot disagree about which files a subdirectory contains.
    *   **Every run is bounded by its own `--source` root** — full, `--file-ids` or `--source-subdir` alike. One catalog can hold rows from several source roots; an unbounded run would act on every `Pending` row in the catalog and move another root's photos. `--file-ids` recorded under a different root are left out with a warning.
*   **Operational Modes** (mutually exclusive — at most one flag; the engine will refuse to start if more than one is given):
    *   **Index (default, no flag):** Full scan (or `--file-ids`/`--source-subdir`-scoped lookup), hashing, metadata resolution, and destination-path computation. Every result is written to the database (including duplicate flagging), but no file is copied, moved, or deleted.
    *   **`--move`:** Runs the Copy-Verify-Delete protocol (§4.2) for every targeted `Pending` file. Source files are deleted only after a verified copy lands at the destination. Confirmed exact duplicates are also removed from source once a verified copy of their content exists elsewhere at the destination.
    *   **`--copy`:** Runs the same verified Copy-Verify step as `--move`, but the source file is never deleted or modified — including duplicate source files, which are left untouched. Fully non-destructive; safe to run against a read-only-mounted source.
*   **Format Support:** 36 extensions — 13 raster (`.jpg`, `.jpeg`, `.jpe`, `.jfif`, `.png`, `.gif`, `.bmp`, `.webp`, `.tif`, `.tiff`, `.heic`, `.heif`, `.avif`) and 23 RAW (`.raw`, `.dng`, `.cr2`, `.cr3`, `.crw`, `.nef`, `.nrw`, `.arw`, `.srf`, `.sr2`, `.raf`, `.orf`, `.rw2`, `.pef`, `.ptx`, `.srw`, `.erf`, `.3fr`, `.fff`, `.iiq`, `.mos`, `.mrw`, `.x3f`). RAW decoding goes through rawpy/LibRaw, which PIL cannot do at all. The supported set is **derived** as the union of `RASTER_EXTENSIONS` and `RAW_EXTENSIONS` (in `ns_db.py`) rather than maintained as a third list: a RAW format present in one list and missing from the other would be discovered by the scan, handed to PIL, and store `"error"` as its perceptual hash for every file of that type. `--exts` accepts values with or without a leading dot. The sets live in `ns_db.py`, shared with the API. An extension the engine cannot read is accepted but warned about at the start of every run that selects it (`ns_db.extension_support`): such files are still catalogued and still carried into the destination by Copy and Move, with no thumbnail or perceptual hash.
*   **Cancellation:** Sending `SIGTERM` or `SIGINT` during a `--move`/`--copy` run lets the file currently being copy-verified finish, then stops before starting the next one. See §4.2 for what happens to the rest of the batch. The run is recorded `Cancelling` as soon as the signal arrives and settles `Cancelled` only if cancellation stopped work that remained. A signal landing after the work finished leaves the real outcome: a finished job reads `Completed`, and a job-level failure stays `Failed` and exits `1`. The photos it did not reach are recorded `Cancelled` in **one transaction**. The move loop's connection commits at `FULL`, so a commit per row would be an fsync per row: measured at ~17 s for 24,000 photos on the catalog's disk, longer than `docker stop`'s default 10 s grace, after which Docker kills the run mid-cancel. The documented `docker run` commands pass `--stop-timeout 300`, and compose sets `stop_grace_period: 5m`, because the file being copied can still take longer than 10 s over a network share.
*   **Retries:** No dedicated retry mechanism or `retry_count` tracking. Re-running the same command retries whatever's still `Pending` (including previously `Failed` files, which are reset to `Pending` by the next Index) — already-successful files are gone from `--source` and won't be reprocessed, so this is cheap even for a large batch with only a few failures.
*   **Single-Instance Enforcement:** At startup, before touching the database, the engine acquires an exclusive OS-level lock (`fcntl.flock`, non-blocking) on a fixed lock file (`<base>/engine.lock`). If the lock is already held, the process logs a clear error and exits immediately without modifying anything — **this applies to every mode**, including Index, not just `--move`/`--copy`, since a rescan racing a physical operation on the same database is exactly as unsafe as two physical operations racing each other (see §4.2). The lock is held for the entire process lifetime and released automatically by the OS on any exit path — normal completion, an unhandled exception, or an uncatchable `SIGKILL` — so there is no manual "is the lock stale" reconciliation step needed, unlike the `runs`-table crash recovery in §4.2, which exists for a different purpose (historical accuracy of run records, not mutual exclusion). Verified: after a lock holder is `SIGKILL`ed, its lock file remains on disk with the dead PID in it, and a fresh invocation against the same `--base` proceeds immediately with no cleanup, so a force-stopped container never leaves the lock needing intervention. Two different `--base` directories are independent locks and run concurrently.
*   **Catalog backups:** one verified snapshot of the whole catalog (photo records, lineage, history, settings; never photo files or thumbnails) is written to `--backups` after every Index, Copy or Move that recorded changes — including a failed or cancelled one — once the run has settled and before the lock is released, so the snapshot holds the run's final status. A job whose only records are `Skipped` or `Cancelled`, such as an unchanged Index or a repeated Copy, changed nothing and is not backed up. **Why not back up every job:** each no-op run would push a meaningful automatic backup out of the retention limit and replace it with a near-identical one. `--backup-now` writes one manual backup and exits `0`, or `1` when it fails. It takes the engine lock like any other action and is therefore refused while a job runs. **Why not allow it during a job:** a mid-job snapshot records a catalog halfway through changes the job is still making, the post-job backup captures the finished state moments later, and a backup outside the lock could not safely settle an attempt left unfinished by a kill. Mechanics (`ns_db.backup_catalog`):
    *   SQLite's online backup API into `<name>.db.partial` beside the destination, switched to `journal_mode=DELETE` so no `-wal`/`-shm` companion ever sits beside a backup, and checked with `quick_check` and the schema version. It is then compressed and verified as described below, and the compressed file is renamed into place and the directory fsynced. The copy records its own attempt as succeeded, so a restored catalog does not settle the backup it came from as interrupted.
    *   Storage is never created or substituted. A missing folder (`storage_unavailable`), one overlapping `--base` (`storage_overlaps_appdata`), an unwritable one (`storage_unwritable`) or the image's own `/backups` left unmounted (`storage_not_mounted`: a backup there would vanish with the container) fails the attempt with that category. Write errors are `insufficient_space` or `write_failed`; the partial file is removed.
    *   A failed post-job backup is logged beside the job's result and never changes it, and nothing retries it automatically. An attempt found without an outcome at startup was interrupted: it is recorded so and its partial file removed. After reconciling, every start also reports what is **left outside every backup**. `ns_db.unbacked_changes` counts the operations written after the newest successful backup started, excluding `Skipped` and `Cancelled` rows and the current run, which backs itself up. When that count is above zero, the engine logs a warning naming the runs and the last good backup, or saying there has never been one, and pointing at `--backup-now`. It is a report, never an automatic backup (`webui-spec.md` §9).
    *   Retention: the `backup_retention` setting (default 20) limits automatic backups. After a new backup succeeds, the oldest automatic ones beyond the limit are deleted and marked `pruned`; manual backups are never pruned. `automatic_backups_beyond(conn, n)` answers how many a lower limit would remove, before it is applied. `refresh_backup_availability` re-observes each unpruned file as `present` or `missing`, or `unknown` when `--backups` itself cannot be reached.
    *   Compressed with Zstandard at level 10, with a frame checksum, as `<name>.db.zst` (`webui-spec.md` §9 has the measurements behind the choice). The verified snapshot is compressed to `<name>.db.zst.partial` and fsynced, then decompressed again and compared with the snapshot by hash. Only then is it renamed into place and the uncompressed `<name>.db.partial` removed. A mismatch fails the attempt as `verification_failed` and publishes nothing. `compression_format` records `zstd` for each such backup, and NULL for backups written before compression. The backup screen reads it per backup to say which library compressed the file and how to open it, so it describes the file itself, never a setting.
*   **Moving to a network share asks first.** An `fsync` on a network share can be acknowledged before the data is on the server's disk (an NFS export marked `async`), and a client cannot see how a share is exported, so a Move's deletion there rests on a promise the engine cannot check. `filesystem_type` reads the destination's type from `/proc/self/mountinfo`: inside a container, a bind mount reports the storage behind it, `nfs4` or `ext4`. For a network filesystem (`NETWORK_FILESYSTEMS`: NFS, SMB/CIFS, sshfs, Ceph and the like), a Move stops before its space check, copying or deleting anything. It opens one `network_destination_unconfirmed` needs-attention issue recommending Copy, and records every selected photo, duplicates included, `Skipped` with a reason pointing at it. `--confirm-network-destination` (Move anyway) or a Copy (the recommended answer) closes it. Copy is never stopped, since it deletes nothing. A mount table that cannot be read is treated as local. **Why not refuse Move outright:** a share exported `sync` is as safe as local disk, and the user can know that where the engine cannot.
*   **Request association:** `--request-id <id>` (1–256 characters) binds one submission to the run it creates, in the same transaction that creates it (`job_requests`, §6.5), after the single-instance lock is held and before any file work or reconciliation. Delivering the same ID again with identical input starts nothing: no run, no scan, no reconciliation. The engine logs the run the ID already created and its recorded status, and exits `4`. The same ID with different input is a conflict: nothing starts and the engine exits `3`. "Input" is what the caller submitted — mode, paths, targeting, `--workers`/`--exts` overrides, `--force-rehash`, `--no-thumbnails` and `--cache` — never the saved settings a new run would resolve today, so a settings change between two deliveries does not turn a replay into a conflict. A replayed run still in an active state is reported as not finished, not settled: marking it `Interrupted` is reconciliation, and the next run that does real work records that under itself. A run refused before acceptance (lock held, missing `--source`, overlap) records nothing, so the same ID may be used again once the cause is fixed. Without `--request-id` every invocation is a new run.
*   **NFS caveat:** `flock` reliability is weaker over NFS, depending on the NFS server/client's `lockd`/`statd` configuration — locks that work reliably on local disk or a standard Docker volume can behave inconsistently if `--base` is ever backed by an NFS mount. Not a concern for the deployment described in §5.1 (a plain host-directory volume mount), but worth re-checking if that assumption ever changes.
*   **Settings are fixed at process start.** `--workers`, `--exts`, and every other flag are read once at launch and never revisited — there is no live-reload concept in the engine itself. (This is already inherently true given the engine is a plain CLI process; the operational rule that a running job ignores subsequent settings changes lives at the web UI's orchestration layer — see `webui-spec.md` §3 — not here.)

### 4.2. Processing Logic

**Capture-date policy:** dated placement uses a usable EXIF `DateTimeOriginal`
and nothing else. Without one the file goes to `Undated/<year>/`, the year taken
from the source's filesystem modification time as recorded at its original Index
(§10), never its creation time.

*Why not `CreateDate` or `DateTime`?* Both are real timestamps and neither is the
moment the photograph was taken: `CreateDate` is when this file was created — a
re-export, a format conversion, a download — and `DateTime` is when it was last
modified. Filing by either puts a photo into the dated tree under a date nobody
vouched for, which is the guess-indistinguishable-from-a-fact problem `Undated/`
exists to prevent. Both remain in captured metadata as review evidence: retaining
a clue and promoting it to a capture date are different things. Undated review
categories are defined in `webui-spec.md` §3.1.

Because exactly one key is accepted, `date_source` is sufficient to answer which
field a placement came from — `exif` means `DateTimeOriginal` and nothing else.

**A catalogue written under a looser rule does not correct itself.** The
unchanged-file skip (§4.2) compares size and mtime and never re-reads a file that
matches, so a photo already recorded with a placement from some other date field
keeps it indefinitely: a plain re-Index changes nothing. `--force-rehash` re-reads
the sources and re-applies the current rule. Verified by constructing exactly that
state — a file catalogued under a looser rule stayed in the dated tree across a
re-Index and moved to `Undated/<year>` only under `--force-rehash`. Files already
delivered to a destination are a further step: re-reading a source updates the
catalogue, not the tree, so relocating them is a separate action.

*   **Deduplication:**
    *   **Exact Match:** Files with identical SHA1 hashes (excluding the file's own row, and excluding other rows already flagged `Duplicate`/`Removed_Duplicate`, to prevent a duplicate pair from cascading into mutually flagging each other across repeated scans) are flagged `status = 'Duplicate'`.
    *   **Duplicate removal (`--move` only):** After all targeted `Pending` files are processed, the engine looks up each `Duplicate`-flagged file's matching `Completed` row. **Scoped to the same targeting as the run itself** (`--file-ids` / `--source-subdir` / whole library) — a selective operation never deletes duplicate source files outside the user's selection. Only if a verified copy is confirmed present on disk at that row's `dest_path` is the duplicate's source file deleted (status becomes `Removed_Duplicate`). If no verified copy is found, the source file is left in place and a warning is logged — this prevents data loss in the case where the "kept" copy's own migration failed. Skipped entirely if the run was cancelled (see below).
    *   **Fuzzy Match:** pHash is generated and stored for every file, but no fuzzy-matching/clustering logic acts on it yet. What acts on it — the precomputed pair table, and the similarity review it backs — is specified in §9.3 and `webui-spec.md` §7.
*   **Source Enumeration:** the directory walk uses `os.scandir` over an explicit stack rather than `Path.rglob` plus `is_file()`/`is_symlink()`. `scandir` returns an entry's type from the directory read itself, so the extension test happens before any `stat`; the `rglob` form cost two extra `stat` calls per entry, each a network round trip on a network-mounted source. Hidden files and directories (leading `.`) are skipped and hidden subtrees pruned rather than descended — this is what excludes macOS `.DS_Store`, AppleDouble `._` sidecars and `.Trashes`. A directory that cannot be read is logged and skipped rather than aborting the scan.

*   **Unchanged-File Skip:** before any file is read, the engine compares each candidate's current `stat()` against the `file_size` and `file_mtime` recorded in the catalog. A file whose size and mtime both still match is not re-read — no SHA-1, no pixel decode, no ExifTool pass — because the existing row is already correct. SHA-1 cannot serve this purpose: it is the *result* of reading the file, not something knowable beforehand. This applies to **all three targeting modes**, not only the full scan; the targeted modes are the ones a web UI issues, and re-reading a scoped selection in full was measured costing about seven minutes of network transfer on a ~9,500-file selection before any file was copied. Rows in a non-settled state are always rescanned rather than trusted on the strength of a stat, and a row with no recorded size/mtime reads as "unknown" and is read in full. `--force-rehash` bypasses the comparison entirely.

*   **Metadata Extraction:** for every file, the engine captures BOTH "date taken" (used to compute the destination folder) AND the full metadata set available (camera make/model, ISO, aperture, shutter speed, and whatever else the source exposes), from the same underlying capture:
    1.  **ExifTool** (persistent per-worker process via `PyExifTool`'s `-stay_open` mode — one instance started per `ProcessPoolExecutor` worker and reused for every file that worker handles, not a fresh subprocess per file) — the primary source, and always available, since the engine will not start without it (§3.3). Captures the COMPLETE tag set ExifTool can extract, not a curated subset. The only method that works for RAW-family formats. Measured: the persistent process costs ~2.5 ms/file of ExifTool-call overhead against ~74 ms/file for a subprocess per file — roughly 30x, which compounds across a large library.
    2.  **PIL** (`Image.getexif()`, plus the "Exif" sub-IFD via `get_ifd(0x8769)`) — a defensive per-*file* fallback, not an "ExifTool is missing" fallback: that cannot happen, since §3.3's startup check refuses to run without it. Used only if ExifTool genuinely ran but returned nothing usable for one specific file. Works for standard/HEIC formats; cannot open RAW-family formats at all. Note: `getexif()` alone only returns the top-level "0th" IFD (Make/Model); `DateTimeOriginal`/ISO/aperture/shutter live in the separate Exif sub-IFD and must be explicitly fetched, or they silently go missing even when present.
    3.  **File modification time** — used only if neither of the above produces a usable date. No richer metadata is captured at this fallback level.

    **ExifTool being a hard requirement does not make Pillow, rawpy and imagehash optional.** They do a fundamentally different job ExifTool cannot do at all: ExifTool reads embedded metadata tags, it does not decode pixel data. pHash generation and thumbnail generation both require actually decoding the image (PIL for standard/HEIC, rawpy for RAW-family) and feeding real pixel data to `imagehash.phash()` — ExifTool's ability to extract an already-embedded camera preview (where one exists) doesn't change that, since `imagehash` still needs that extracted preview decoded through PIL to hash it. See §3.3 for the full library breakdown.

    **Self-healing:** if a worker's persistent ExifTool subprocess dies mid-batch (crash, killed externally), the next file processed by that worker detects the failure and transparently restarts it — tested by killing the underlying subprocess: the very next query recovers, and the worker keeps ExifTool for the rest of its files.
*   **Unique Filename Enforcement:** Resolved immediately *before* the file is written, never at Index time. This timing is load-bearing: during Index the destination tree is typically still empty, so every same-named file would be told its name is free — two distinct photos named `IMG_0001.jpg` (two camera cards, say) would be assigned the identical destination and whichever moved second would silently destroy the first. The destination recorded at Index time is therefore a **projection**, refreshed with the real value when the write happens. Recorded via `has_name_collision` (see §6).
    *   **Content-aware:** if an occupied candidate name already holds *exactly this file's content* (SHA-1 match), that file is recognized as this photo, already delivered by an earlier run. The write is skipped rather than producing another identical copy under the next free name — this is what makes repeated Index→Copy cycles idempotent instead of accumulating `_1`, `_2`, `_3`... duplicates. The source is re-hashed live at that moment rather than trusting the indexed hash, so a file edited since the last Index is never mistaken for already-delivered. In `--move` the operation still completes by removing the now-redundant source.
    *   Suffixes are always built from the original stem (`IMG_0001_3.jpg`), never by re-suffixing a previous result (`IMG_0001_1_2_3.jpg`).
    *   **Overwrite is structurally impossible, not merely avoided:** publishing the verified partial uses `os.link()`, which *fails* on an occupied name rather than replacing it (`Path.rename()` silently overwrites on POSIX). A refused write leaves the destination untouched, the source intact, and no partial behind. Filesystems without hard-link support (FAT/exFAT, some network shares) fall back to a checked rename.
*   **Safety Protocols:**
    *   **Copy-Verify-Delete / Copy-Verify:** The file is copied into a new, uniquely named partial (`<filename><ext>.organizing.partial.<random>`) in the destination directory — created exclusively, never following a symlink — and fsynced. Its SHA1 is recomputed and compared against the source's; only on a match is it published under its final name with a no-overwrite hard link (falling back to rename only on filesystems that cannot hard-link), and the directory is fsynced. **Every directory entry from `--dest` down to the file's own folder is fsynced too**: a file's entry is durable only if the directory holding it is, and that applies to each folder in the chain in turn — syncing only the deepest one can leave the first photo of a new day inside a day folder whose own entry in the month folder never reached disk. The chain is derived from the destination root rather than from whichever folders a particular call happened to create, because **existence is not durability**: a directory exists the moment `mkdir` returns, which is before its entry has reached disk, so a sync that failed a moment earlier must not be certified by the directory it left behind. Each entry is recorded as established only when its fsync *succeeds*; a failure leaves it outstanding, and the next file — in this run or after a restart — retries it and keeps refusing the move until it holds. That costs one fsync per folder whose entry is not yet known durable: once per new date folder in a run, never per file. Filesystems that do not implement directory fsync at all (reporting `EINVAL`/`ENOTSUP`) are tolerated rather than refused, because the operation is *absent* rather than failed; on those the power-loss guarantee is correspondingly weaker, and `--move` there accepts that. **The run says so when it happens** — once per run, naming the first directory that reported it — so a user on exFAT or an odd network mount learns it from their own run rather than by inferring it from this document. Once per run rather than once per directory: a line per date folder is how a warning becomes noise and then gets ignored. Any other sync error keeps the source and is recorded with a reason naming durability. The source is deleted afterward only in `--move` mode. The real error text (not just pass/fail) is captured and returned on any failure — see §6's `operations` table.
    *   **Deleting a source:** One routine deletes every source file the engine removes — after a move, when the destination already holds it, and during duplicate cleanup. Beyond the live hash comparison each caller makes, it refuses unless the copy is a *different* file (a file reached through two mounts, or a hard link, compared with itself would "verify"), the copy, its own directory entry, **and every entry above it up to `--dest`** have been fsynced (so a power loss cannot leave the source deleted and the copy either unreachable or still in page cache), and the source is unchanged since it was verified (so an edit made mid-move is never deleted). **That chain is established here, at the single deletion gate, rather than by each caller.** Only one of the three callers copies the file itself and so passes through directory creation; the other two delete against a copy an earlier run delivered, and that run's `mkdir` is no evidence its entries reached disk — a directory exists the moment `mkdir` returns, which is before its entry is durable in its parent. A caller that already established the chain pays nothing, since entries already known durable in this run are skipped. A refusal keeps the source and is recorded as a failed operation with the reason. Sources are assumed not to be edited by other programs during a Move; the unchanged-source check narrows that window but is not a concurrency guarantee.
    *   **Retry with backoff:** Transient IO errors (e.g., flaky network shares) during copy/rename/delete operations are retried up to 3 times with exponential backoff (1s, 2s) before the operation is considered failed. (This is unrelated to the "no retry mechanism" decision in §4.1 — that refers to re-attempting a whole failed *file* across separate runs, not this in-process backoff for transient IO errors during a single attempt.)
    *   **Pre-flight disk space check:** Before `--move`/`--copy` begins, the engine sums the size of the targeted files and confirms the destination volume has enough free space (plus a 500MB safety margin), aborting before any file operations start if not. Rows whose recorded destination already holds a file of the same size are **excluded from the sum**: they are not written again, since the loop re-verifies both sides live and a `--move` finishes by deleting the source. Counting them would abort the documented Copy-then-Move workflow on a destination with ample room for what the run actually writes, since `--move` is eligible for `Copied` rows whose content is already delivered. The estimate never authorizes anything: the live hash comparison still decides, and a file that does need writing after all fails on its own with a recorded reason, source intact. A shortfall is recorded as a run-level `Failed` operation carrying the required and available figures, not only logged.
    *   **Orphan Cleanup:** On startup, leftover partial files belonging to an interrupted row (`<filename><ext>.organizing.partial.*` beside that row's destination) are removed. Only regular files are removed, never symlinks.
    *   **Crash Recovery — file level:** Every mutation records **durable intent before touching a file**: an `operations` row with an `intent` event, committed at `synchronous=FULL` alongside `photos.status = 'Processing'` and the `dest_path` the work relies on. An interrupted operation is therefore one carrying intent and **no terminal event**, which is how recovery finds work that was started and never settled; without the intent row an interruption would leave nothing for a conclusion to attach to.

        On startup, after the new run is recorded, recovery **observes** both locations, writes an `operation_evidence` row for each, and only then concludes. Four outcomes, and the two in the middle are the point:

        | Observed | Conclusion |
        | :--- | :--- |
        | destination present, source absent | the work finished — `Completed`, or `Removed_Duplicate` when that destination belongs to another delivered row with the same hash |
        | destination absent, source present | nothing was published — back to `Pending` or `Duplicate` so the next run retries |
        | **both present** | the copy landed and the source was never removed. The published file is registered as its own identity and the operation is recorded **incomplete**. Recovery never deletes the source; an explicit Move may, after verifying both sides live |
        | **both absent, or either unreadable** | the outcome **cannot be established**. An attention issue is opened carrying the evidence, and the row is *not* reset to `Pending` — which would claim a file is waiting for work it can never receive |

        **Recovery observes; it does not publish.** When it finds a destination that is already a recorded identity, it *links* to that identity rather than registering a new one. Registering implies a publication event, and the engine treats a fresh publication as proof that any previously recorded occupant is gone — correct for a genuine re-publication, and wrong for a file nothing replaced. Registering instead would mint a second identity for the same bytes and mark the real one missing — invisible to summary counts, so the contract suite pins the rule from both sides.

        Each row is settled in its own transaction: evidence, the settled operation and the new status commit together or not at all. The repair is recorded as an operation of the **reconciling** run, linked to the operation it repairs through `reconciles_operation_id`, so requested work and recovery of earlier work stay separable rather than both reading as this run's output. A reconciliation that fails is never swallowed: it rolls back, and the run is marked `Failed` rather than continuing against a catalog it could not settle.
    *   **Crash Recovery — run level:** On startup, any `runs` row still in an active state — `Preparing`, `Running` or `Cancelling`, meaning that process was killed uncatchably (`SIGKILL`, OOM-kill, power loss) and bypassed the normal shutdown path — is marked `Interrupted` rather than left showing as perpetually in progress. `reconciled_by_run_id` names the run that found it and `ended_at` stays NULL. **Why not stamp the reconciliation time as the end:** the next run can start days later, and a duration computed to that moment is fiction that looks like data. The run's last recorded operation bounds the death from below, and the reconciler's start bounds it from above; a reader wanting an approximation can take either and say which.
    *   **Re-scan safety:** Re-running the engine against a source directory that still contains previously-cataloged files (the normal Index → review → `--move` workflow) updates existing database rows in place (`INSERT ... ON CONFLICT(source_path) DO UPDATE`) rather than failing on a duplicate-key error.
    *   **Cancellation:** Checked between files, never mid-file — the in-flight file always finishes its Copy-Verify(-Delete) before the loop stops. Every remaining targeted file that never got a chance to run is logged to `operations` with `status = 'Cancelled'`, while its `photos.status` stays `Pending` (not overwritten), so a plain re-run picks it back up naturally. Duplicate-source cleanup is skipped entirely for a cancelled run, since it depends on knowing the final fate of every targeted `Pending` file first. A cancellation that arrives *during* duplicate cleanup is checked before each duplicate in the same way: the removal in progress finishes, the remaining duplicates are left in place and logged as `Cancelled`, and the run ends `Cancelled`.
    *   **Source file changed since Index:** If a targeted file's `source_path` no longer exists on disk when the engine actually tries to process it (moved, renamed, or deleted outside NegativeSpace since the last Index — most likely with `--file-ids`/`--source-subdir` targeting a stale selection), this is detected explicitly *before* attempting to open the file, rather than surfacing as a raw `FileNotFoundError` traceback. Recorded as `status = 'Failed'` with a specific, human-readable `error_message`: `"Source file changed: no longer found at <path>. It may have been moved, renamed, or deleted outside NegativeSpace since the last Index."` The distinct wording matters for the Error Center (`webui-spec.md` §5.3) — a user seeing this should understand to re-index, not assume a permissions or disk problem.
        A full (untargeted) run also detects this at Index time: after walking the source root, any `Pending` or `Duplicate` row under it that was not found is checked with `stat()`, and only a file that definitely does not exist is marked `Failed` with the same message. Otherwise a photo deleted outside the engine would stay `Pending` indefinitely and keep standing as the original of its duplicate group, so its duplicate would never be delivered; as a `Failed` row it leaves the group and a surviving duplicate is promoted. A permission or I/O error is never treated as absence.

        **A missing source whose content is on the destination is recorded `Found_At_Destination`, not `Failed`.** Before the Move/Copy loop, duplicate cleanup or a full Index records a missing source as `Failed`, it looks for the photo's exact content on the destination:
        *   for a photo, at the destination it was meant for, and that name's numbered variants;
        *   for a duplicate, at any delivered copy of its content, each hashed live.

        If a file holding the recorded SHA-1 is there, the row is recorded `Found_At_Destination`. **Why not `Completed` or `Removed_Duplicate`:** those describe an action — a Move delivered it, a duplicate source was deleted — and this run took none. The engine cannot tell a lost Move from a source deleted by hand, so the record states only what was observed, in one transaction:
        *   evidence rows: source `absent`, destination `match`;
        *   the found file registered as an `observed_destination` identity, or linked if already recorded;
        *   the source identity marked `missing`, not `removed`;
        *   the operation settled as `Found_At_Destination`.

        Nothing is copied or deleted. This is the state a power cut leaves when a Move's catalog commits are lost and its file operations survive (`TODO.md` claim 10). A full Index also applies it to a row an earlier targeted Index already marked `Failed`. `Found_At_Destination` counts as delivered wherever that matters — as a duplicate group's anchor, as a copy duplicate cleanup verifies against, and as a source a later run must not re-scan.

        **An empty source folder raises a question instead of a guess.** An unplugged share and a Move that took every photo look identical: an existing, empty directory. When a full walk finds no supported files under the source root while the catalog holds `Pending` or `Duplicate` rows there — or when *none* of a Move/Copy selection's sources exist — the engine changes no status and opens one needs-attention issue (`source_root_empty`) asking which it is. Unsupported files left in the folder do not count: a Move leaves them behind by design. A Move/Copy records each selected photo `Skipped` with a reason pointing at the question. The answer is `--confirm-source-empty` (a button in the web UI): the folder really is empty, so the checks above run, rows found on the destination are recorded `Found_At_Destination`, the rest are marked missing, and the issue is closed. Files reappearing in the folder close it too. **Why not decide automatically:** a guess either way writes a false record — photos still on an unplugged drive recorded as found elsewhere, or delivered photos recorded as lost.
    *   **Nothing unreadable is only logged:** A folder that cannot be listed, or a file that cannot be inspected, during discovery is recorded as a `Failed` operation of the run, with `photo_id` NULL and the folder or file path as `source_path`. A scan result the database writer cannot store is rolled back on its own (each result's row and operation are one unit), and the run is then marked `Failed` without moving or copying anything, since the catalog no longer reflects what was scanned.
    *   **Exit status:** The engine exits `0` only when the run did not fail. A `Failed` run, a missing `--source`, or a `--source` that is not a folder exits `1`; invalid arguments such as `--workers 0` exit `2`. `--backup-now` exits `1` when no verified backup was written. A request ID reused for different input exits `3`, and one already accepted exits `4`; neither starts anything (§4.1). A cancelled run exits `0` — it did what was asked.
    *   **ExifTool startup check:** Before touching the database or source/dest paths at all, the engine verifies both the `exiftool` binary and the `PyExifTool` package are available and exits immediately with a clear fatal error if either is missing (§3.3) — tested with the binary hidden from `PATH`: it fails cleanly and creates no directories or database files.

### 4.3. Reporting & Feedback
*   **Logging:** Structured logs to both console and `<base>/logs/organizer.log`, covering every stage (scan discovery, hashing, metadata resolution, space checks, copy/verify/delete, duplicate cleanup, cancellation). At startup, once the engine holds the single-instance lock, a log over 50 MB is rotated to `organizer.log.1`, keeping five older logs. It is never rotated mid-run, because every worker process writes to the same file, so one run's log is never split.
*   **Discovery accounting:** a full Index (no `--file-ids`, no `--source-subdir`) records what its walk found in `run_discovery`: files found, eligible by the run's extension selection, and excluded by file type, with a per-extension breakdown in which `""` means no extension. Hidden entries are skipped before counting, as the walk always skipped them, and a symlink is not counted as a file. Any folder or entry the walk could not read sets `unreadable`, and the counts are then **partial**. The log states the same summary, for example *"Discovered 7 file(s): 3 eligible by file type, 4 excluded by file type (.xmp 2, .mov 1, no extension 1)."* Scoped runs walk nothing and record nothing rather than a guess. `ns_db.read_discovery(conn, run_id)` returns the summary for the API (`webui-spec.md` §5.1). Counting excluded files reads the file type `readdir` already returned, so it adds no round trip on a network share.
*   **Progress Reporting:** during a scan the engine reports, on a fixed interval, the *instantaneous* rate over the most recent window — both files/sec and MB/s — with an ETA derived from that recent rate rather than a cumulative average. The distinction is operational, not cosmetic: a cumulative average decays continuously while a run is healthy, which makes a saturated link look like a failing one. Reporting bytes alongside files is what separates the two cases — a RAW-heavy stretch runs at a few files/sec and a JPEG stretch at tens of files/sec while both saturate the same network link, and only the MB/s figure shows that.

*   **Run Summary:** every Index ends with one line giving the total recorded and a per-status breakdown, plus warnings for files that produced no perceptual hash (they index and move normally but cannot participate in similarity matching (§9.3)) and for files dated from mtime rather than EXIF (the only files a timezone change can move between folders). Without it, a scan where hundreds of files failed would look identical to a clean one.

*   **Per-File Warning Attribution:** library warnings raised while reading a file are captured and re-logged naming that file. Worker processes do not inherit the log handler under `forkserver`/`spawn`, so without this they would be dropped entirely. Note that PIL's `"Truncated File Read"` reaches the log through `TiffImagePlugin`'s EXIF parser, which catches the underlying `OSError` and downgrades it to a warning — it means the EXIF block is malformed, **not** that pixel data is missing, and such files still produce correct SHA-1 and perceptual hashes.

*   **Audit Trail:** The `runs` + `operations` tables (§6) together give a full history of every invocation and every per-file outcome within it — this is what "show previous run information" is built on, independent of the frontend.
*   **Timestamp Contract:** application events, including run start/end and operation
    history, are recorded as timezone-aware UTC instants. Every catalog timestamp the
    engine writes carries its offset, pinned by `every_catalog_timestamp_carries_its_offset`;
    a naive timestamp is never simply relabelled `Z`. Photo capture dates retain
    their recorded wall-clock value and any known offset;
    an absent offset remains unknown, not assumed UTC. Capture-date folder placement
    follows that recorded calendar date, independent of the browser timezone. UI
    presentation is specified in `webui-spec.md` §10.
*   **Real-time Feedback:** the planned web drawer shows aggregate progress and elapsed
    runtime, and the discovery counts recorded above. Display aggregates rather than a live line per file (`webui-spec.md` §4.1). Required support includes
    phase/scoped totals and classified outcomes, including unchanged-file skips;
    operation statuses alone do not supply a reliable percentage. Keep full per-file
    audit records while allowing the UI to refresh summaries about once per second.
    Runtime uses the run's recorded start/end, surviving browser reconnects. This
    complete progress contract is not implemented; no per-second database writes or
    active-worker/queue telemetry are required merely to refresh the display.

## 5. Technical Infrastructure
### 5.1. Deployment (Docker)
*   **Environment:** Containerized for consistency across dev/prod environments. `gosu`-based entrypoint maps the container process to the host user via `PUID`/`PGID`. It gives that user all of `/appdata` (the engine's own small tree) but only the top level of `/data/dest`. Files and folders already in the destination keep their owners, since walking a library-sized tree on every start is slow and rewrites the ownership of user data. It exits with an error if `/appdata` is not writable by the mapped user, and warns if `/data/dest` is not, since Index does not need it. The base image is pinned by digest and the Python dependencies to exact versions, so a rebuild reproduces the validated image.
*   **Required system packages:** `libimage-exiftool-perl` (or platform equivalent) **must** be installed in the image — ExifTool is a hard requirement (§3.3/§4.2), not an optional extra. If it is missing, the container still builds and starts, but every engine invocation exits immediately with a fatal error rather than running degraded.
*   **Recommended: a proper subreaper as PID 1** (e.g. `tini`/`dumb-init`), general Docker hygiene — each worker process spawns and manages its own ExifTool child process, and while it's cleaned up on normal worker shutdown, a subreaper ensures nothing is ever left orphaned regardless of how a process exits.
*   **Volume Mapping:** `/data/source` (source photos), `/data/dest` (organized output), `/appdata` (SQLite DB + logs), all host-mapped.
    Catalog backups go to a separate `/backups` mount configured at deployment,
    holding multiple database snapshots, not photos (§4.1). Its underlying storage is
    chosen through Docker, not application settings; no fallback to `/appdata` or to
    the container's own layer is permitted. The underlying backup and application-data
    directories must be distinct and non-overlapping (neither contains the other).
    Every backup attempt checks this, including one directory reached by two paths,
    and records a detected overlap as a failed backup. Two separate network mounts of
    one export look like different storage and are not detected, which is why the
    host-directory requirement stays documented. Separate physical disks are not required.
*   **Database:** **SQLite**, opened in WAL mode with a 5-second busy timeout for safe concurrent access between the writer thread and any read-only inspection. **Two synchronous levels, deliberately.** The scan path runs `synchronous=NORMAL`: it survives process death — `SIGKILL`, OOM-kill, a `docker stop` timing out — but not a power cut, and it is ~4.4x faster when committing scan results a hundred rows at a time. The Move/Copy loop opens its connection at `FULL` instead, because it commits `status = Processing` with `dest_path` *before* unlinking a source and reconciliation finds interrupted work by that marker alone; losing it to a power cut leaves a successfully delivered photo recorded `Failed`. `FULL` costs 1.42x on that path, where several fsyncs per file are already being paid, so the guarantee is bought where it matters and declined where it is expensive. The audit rows that loop writes are fsynced with it. **Every run then settles at `FULL`** (`finish_run`), and in WAL mode that one commit fsyncs the whole WAL, so the scan path's `NORMAL` commits become durable too once the run settles. That costs one fsync per run, not per batch; a run killed before settling keeps the `NORMAL` exposure for its last batch (`TODO.md` claim 12). Backup attempts record their outcome at `FULL` as well.

    **Startup reconciliation commits at `FULL` too** (`TODO.md` claim 13): its evidence and attention records are conclusions from observations that may not be repeatable — storage disappears and files are replaced between runs — so losing one would discard the only record that an outcome could not be established.

## 6. Data Schema (SQLite)

The three transfer tables below — current state, runs, and the audit log — each have a distinct role (the design note at the end of §6.5 says why state and history are separate). The identity, lineage, cache and backup records are defined in §6.5.

### 6.1. `photos` — current state, one row per source file
| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key, autoincrement. This is what `--file-ids` targets. |
| `source_path` | Text | Original file path. **Unique** — the re-scan upsert logic (§4.2) depends on this constraint. |
| `dest_path` | Text | Target path (including auto-generated suffixes) |
| `sha1_hash` | Text | Exact content hash |
| `phash` | Text | Perceptual hash. `"not_supported"` if the required optional library isn't installed for that format; `"error"` if hashing was attempted but failed (e.g. corrupt file). |
| `collision_group` | Integer | Reserved for fuzzy-match clustering (§9.3). Not populated yet. |
| `is_master` | Boolean | Reserved for collision resolution. Not populated yet, and its future is genuinely open: the similarity review keeps the user's chosen primary as client state (§9.3), which needs no column — but lineage and EXIF history need *persisted* provenance (§9.8), which may. Decide when one of those is built, not before. |
| `status` | String | `Pending`, `Processing`, `Completed`, `Failed`, `Duplicate`, `Removed_Duplicate`, `Copied`, `Found_At_Destination` (source gone, exact content observed on the destination; §4.2). Constrained by `CHECK`; `NULL` permitted, since a row can exist before its scan result lands. |
| `metadata_json` | JSON | Full captured metadata (camera, ISO, aperture, shutter, etc. — whatever the source/method exposed), always including a `date_taken` key. |
| `has_name_collision` | Boolean | Whether the destination filename had to be suffixed (`_1`, `_2`, ...) to avoid overwriting an existing file. |
| `file_size` | Integer | Size in bytes as of the scan that wrote this row. With `file_mtime`, this is what lets a re-index skip an unchanged file without reading it (§4.2). NULL means "unknown" and forces a full re-read. |
| `file_mtime` | Real | Filesystem modification time as of the scan that wrote this row. Compared with a tolerance rather than for exact equality, since filesystems differ in timestamp resolution. |

### 6.2. `runs` — one row per engine invocation
| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key, autoincrement |
| `mode` | Text | `INDEX`, `MOVE`, or `COPY` |
| `source_path` / `dest_path` | Text | As passed to this invocation |
| `file_ids_filter` | Text | Self-describing JSON object naming which mechanism scoped the run — `{"file_ids": [101, 102]}` or `{"source_subdir": "sd_card/day1"}` — or NULL for a full directory scan. Despite its name it holds either mechanism. |
| `started_at` / `ended_at` | Text | ISO timestamps, UTC with offset (§4.3). `ended_at` is set when the run settles itself and stays NULL for `Interrupted`, whose moment of death is unknown |
| `status` | Text | The run's lifecycle, not whether its work succeeded (`webui-spec.md` §5.5). Active: `Preparing` (accepted; reconciling earlier work before any requested file work), `Running`, `Cancelling` (cancel received; the current file is finishing). Terminal: `Completed`, `Cancelled` (cancellation stopped work that remained), `Failed` (a job-level error prevented normal completion), `Interrupted` (died without settling). `ns_db.RUN_TRANSITIONS` is the only way between them: terminal states are final, `Preparing` never ends `Completed`, and `Cancelling` may, because a job that finished before its cancellation took effect reports what actually happened |
| `reconciled_by_run_id` | Integer | For an `Interrupted` run, the run whose startup found it dead. That run's `started_at` is when the death was noticed, not when it happened |

### 6.3. `operations` — append-only audit log, one row per file per run
| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key, autoincrement |
| `run_id` | Integer | FK to `runs.id` |
| `photo_id` | Integer | FK to `photos.id`. NULL for a failure that belongs to the run rather than a catalogued photo, such as a folder that could not be read. |
| `original_filename` | Text | The file's name at time of processing |
| `source_path` / `dest_path` | Text | As of this specific operation |
| `status` | Text | The outcome of this specific attempt — same value set as `photos.status`, plus `Cancelled` (the run reached the photo and stopped; the photo stays `Pending`) and `Skipped` (the run reached a selected photo and deliberately did nothing — a duplicate whose original carries its content — with the reason, naming that original, in `error_message`) |
| `error_message` | Text | The real exception text on failure, e.g. `"OSError: [Errno 30] Read-only file system: ..."` — not just a generic failure flag |
| `has_name_collision` | Boolean | As of this specific operation |
| `timestamp` | Text | ISO timestamp |
| `sha1_hash` | Text | The photo's content hash, read from its catalog row when the operation is recorded; NULL when the file could not be read. `photo_id` is valid only inside one catalog, while the hash names the same content in any catalog — so a photo's history, including its duplicates, can be matched up again after a rebuild. |

### 6.4. Indexes

All seven are created on every startup with `CREATE INDEX IF NOT EXISTS`, so a dropped index heals on the next run rather than requiring intervention.

| Index | Columns | Why it is required |
| :--- | :--- | :--- |
| `idx_photos_sha1` | `sha1_hash` | The per-file duplicate check runs once for **every** file scanned; unindexed it degrades to a full scan of a table growing with every file — quadratic over library size. |
| `idx_photos_status` | `status` | The Pending sweep and duplicate cleanup both filter on it. |
| `idx_photos_source_stat` | `source_path, file_size, file_mtime` | Covers the unchanged-file comparison (§4.2) so the lookup does not pay a row fetch per file. |
| `idx_photos_phash` | `phash` | Similarity review (§9.3) groups by perceptual hash on every match-gallery view; unindexed that is a full scan per view. |
| `idx_operations_run` | `run_id` | Backs the per-job history view. |
| `idx_operations_photo` | `photo_id` | Backs the per-photo history panel. `operations` is append-only and grows with files × runs, so this is the difference between a lookup and scanning the whole audit log. |
| `idx_operations_sha1` | `sha1_hash` | "Everything that ever happened to this content" — across its duplicates, and across catalog rebuilds where `photo_id` does not survive. |

**The catalog preserves history, not just derived metadata.** Engine-owned `ns_db.py`
initializes schema version 7 and refuses incompatible catalogs before processing.
No migration exists: preserve an older catalog and use a fresh one. Index cannot
reconstruct settings, past edits, or deleted-file lineage. Never describe deleting a
user catalog as routine repair.

*   Connections enforce foreign keys and bounded lock waits; shared transactions roll
    back on failure, and a settings save must match the revision it read.
*   Settings are `workers`, `exts` and `backup_retention`. Each run stores its
    effective configuration in `run_configs` — defaults, then saved settings, then CLI
    overrides — and later settings changes never alter it.
*   A source returning after a completed Move or duplicate removal receives a new
    identity; operation links keep the previous identity and its original evidence.
*   Not yet implemented: content-version transitions (nothing modifies content yet)
    and revision enforcement across a whole transfer.


**Status vocabularies are enforced, not merely documented.** Each of the three `status` columns carries a `CHECK` constraint listing exactly the values above (`photos.status` also permits `NULL`, since a row can exist before its scan result lands). The constraint text is generated from the same Python tuples the engine uses — `PHOTO_STATUSES`, `RUN_STATUSES`, `OPERATION_STATUSES` in `ns_db.py` — so the database and the code cannot drift apart.

This exists because the failure mode is silent. SQLite accepts any string in a bare `TEXT` column, and a misspelled status in a `WHERE` clause matches zero rows rather than raising: a typo in the duplicate-cleanup anchor check would simply stop removing duplicate sources, and a typo in the `Processing` marker would make crash recovery blind to a file interrupted mid-move. Nothing would error and nothing would be logged.

It matters most for the web UI, which adds a second codebase reading and writing these columns without importing the engine's constants. A web layer that writes `'copied'` or filters on `'Complete'` fails loudly at write time instead of quietly disagreeing with the engine about what the catalog contains. Anything writing to this database — including ad-hoc `sqlite3` sessions — is held to the same vocabulary.

### 6.5. Legacy transfer tables and shared schema

This block is the authoritative definition, and is meant to be executed as
written — as a fixture, or to diff a real catalog against. **Statement order is
part of what it promises:** indexes come last, after every table they reference
exists, because an `operations` index ahead of the `operations` table fails with
`no such table`. That is the order the engine itself uses — tables first,
indexes after.

```sql
-- photos: CURRENT STATE only, one row per source_path (UNIQUE constraint
-- enforces this). Continuously overwritten in place on every re-scan --
-- this is what keeps "what's still Pending" queries fast, and is the
-- table --file-ids targets by primary key.
CREATE TABLE photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT UNIQUE,
    dest_path TEXT,
    sha1_hash TEXT,
    phash TEXT,
    collision_group INTEGER,      -- reserved for fuzzy clustering (9.3)
    is_master BOOLEAN DEFAULT 0,  -- reserved; likely unnecessary, see 9.3
    status TEXT,                  -- Pending, Processing, Completed, Failed,
                                  -- Duplicate, Removed_Duplicate, Copied,
                                  -- Found_At_Destination
    metadata_json TEXT,           -- full captured EXIF/metadata, not just date
    has_name_collision BOOLEAN DEFAULT 0,
    file_size INTEGER,            -- size/mtime as of the scan that wrote this
    file_mtime REAL,              -- row; the unchanged-file skip compares
                                  -- against these instead of re-reading
    CHECK (status IS NULL OR status IN ('Pending', 'Processing', 'Completed',
           'Copied', 'Failed', 'Duplicate', 'Removed_Duplicate', 'Found_At_Destination'))
);
-- Thumbnails and width/height belong to content, not to one copy of it: they
-- live in thumbnail_cache and contents below, so photos carries neither.

-- runs: one row per engine invocation (Index, Move, or Copy). This is what
-- "previous run information" is built from -- no separate run-history table.
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    source_path TEXT,
    dest_path TEXT,
    file_ids_filter TEXT,   -- Self-describing JSON object naming which
                            -- targeting mechanism scoped the run:
                            --   {"file_ids": [101, 102]}
                            --   {"source_subdir": "sd_card/day1"}
                            -- NULL for a full directory scan. Always the
                            -- object form; the column name predates
                            -- --source-subdir and is kept as-is.
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,   -- lifecycle; see 6.2 and ns_db.RUN_TRANSITIONS
    -- The run whose startup found this one dead. ended_at stays NULL then.
    reconciled_by_run_id INTEGER REFERENCES runs(id),
    CHECK (status IN ('Preparing', 'Running', 'Cancelling', 'Completed',
                      'Cancelled', 'Failed', 'Interrupted'))
);

-- operations: the audit LOG. Append-only -- one row per file per run, so the
-- same file can appear multiple times across different attempts without
-- losing history the way overwriting a column on `photos` would.
CREATE TABLE operations (
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
    reconciles_operation_id INTEGER REFERENCES operations(id),
                            -- set only on a recovery record, naming the
                            -- operation it repairs. This is what keeps
                            -- requested work and recovery of earlier work
                            -- separable (4.2); a run's own output is the
                            -- rows where it is NULL.
    sha1_hash TEXT,         -- the photo's content hash, read when the row is
                            -- written; NULL if the file could not be read.
                            -- photo_id is valid in one catalog only; this
                            -- links the same content across rebuilds (10).
    -- Same vocabulary as photos.status, plus Cancelled (reached but never
    -- started; the photo stays Pending) and Skipped (reached and deliberately
    -- left alone -- a duplicate whose original carries its content -- with the
    -- reason, naming that original, in error_message).
    CHECK (status IN ('Pending', 'Processing', 'Completed', 'Copied', 'Failed',
           'Duplicate', 'Removed_Duplicate', 'Found_At_Destination', 'Cancelled', 'Skipped')),
    FOREIGN KEY(run_id) REFERENCES runs(id),
    FOREIGN KEY(photo_id) REFERENCES photos(id)
);

CREATE INDEX idx_photos_sha1 ON photos(sha1_hash);
CREATE INDEX idx_photos_status ON photos(status);
CREATE INDEX idx_photos_source_stat ON photos(source_path, file_size, file_mtime);
CREATE INDEX idx_photos_phash ON photos(phash);
CREATE INDEX idx_operations_run ON operations(run_id);
CREATE INDEX idx_operations_photo ON operations(photo_id);
CREATE INDEX idx_operations_sha1 ON operations(sha1_hash);
```

**Identity and lineage records.** Listed before the next block because everything
there references `files`.

```sql
-- Stable identity, independent of path or hash. A rename, Move or metadata edit
-- preserves file_id; deletion retains the row so history survives.
CREATE TABLE files (
    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_run_id INTEGER NOT NULL REFERENCES runs(id),
    created_at TEXT NOT NULL
);

-- Immutable creation provenance, separate from mutable current state. A Copy
-- child points at its source's origin; an uncatalogued destination the engine
-- found rather than created has kind 'observed_destination' and a NULL origin,
-- because inventing a source snapshot for it would be a fabrication.
CREATE TABLE file_origins (
    file_id INTEGER PRIMARY KEY REFERENCES files(file_id),
    origin_file_id INTEGER REFERENCES files(file_id),
    kind TEXT NOT NULL CHECK(kind IN ('indexed','copy','observed_destination'))
);

-- Current recorded state. Presence and location are deliberately separate from
-- the last operation's result: a file may be known present and still have an
-- unresolved outcome against it.
CREATE TABLE file_states (
    file_id INTEGER PRIMARY KEY REFERENCES files(file_id),
    current_path TEXT NOT NULL,
    location_role TEXT NOT NULL CHECK(location_role IN ('source','destination')),
    presence_state TEXT NOT NULL CHECK(presence_state IN ('present','removed','missing')),
    sha1_hash TEXT, revision INTEGER NOT NULL DEFAULT 0
);
-- Two live files at one destination path is a database error, not a lineage bug
-- discovered later.
CREATE UNIQUE INDEX idx_present_destination ON file_states(current_path)
    WHERE location_role='destination' AND presence_state='present';

-- Binds a legacy photos row to its current identity. Rebinds when a consumed
-- source returns, which is a new arrival rather than a new version.
CREATE TABLE photo_files (
    photo_id INTEGER PRIMARY KEY REFERENCES photos(id),
    file_id INTEGER NOT NULL UNIQUE REFERENCES files(file_id),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0)
);

-- Immutable original Index evidence, one per source identity INCLUDING
-- duplicates. Later scans never overwrite it; unknown values stay NULL rather
-- than zero or epoch.
CREATE TABLE source_snapshots (
    file_id INTEGER PRIMARY KEY REFERENCES files(file_id),
    run_id INTEGER NOT NULL REFERENCES runs(id), source_path TEXT NOT NULL,
    sha1_hash TEXT, file_size INTEGER, file_mtime REAL, birthtime REAL,
    metadata_json TEXT NOT NULL, observed_at TEXT NOT NULL,
    error_message TEXT
);

-- Append-only: what each later scan saw, kept apart from the original snapshot
-- so a subsequent read is never presented as original evidence.
CREATE TABLE file_observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(file_id),
    run_id INTEGER NOT NULL REFERENCES runs(id), source_path TEXT NOT NULL,
    sha1_hash TEXT, file_size INTEGER, file_mtime REAL, birthtime REAL,
    metadata_json TEXT NOT NULL, observed_at TEXT NOT NULL,
    error_message TEXT
);

-- Participants in one operation, by role. Connects copies and duplicate
-- removals without merging their histories.
CREATE TABLE operation_files (
    operation_id INTEGER NOT NULL REFERENCES operations(id),
    file_id INTEGER NOT NULL REFERENCES files(file_id),
    role TEXT NOT NULL CHECK(role IN ('source','destination','retained_copy')),
    PRIMARY KEY(operation_id,file_id,role)
);

-- Frozen at job start: defaults, then saved settings, then CLI overrides. A
-- later settings change cannot alter a run that already began.
CREATE TABLE run_configs (
    run_id INTEGER PRIMARY KEY REFERENCES runs(id),
    effective_config_json TEXT NOT NULL
);

-- One request id binds to one run. Repeating it returns that run; reusing it
-- with different input is a conflict, not a second execution.
CREATE TABLE job_requests (
    request_id TEXT PRIMARY KEY,
    run_id INTEGER NOT NULL UNIQUE REFERENCES runs(id),
    submitted_request_json TEXT NOT NULL
);

CREATE INDEX idx_observations_file ON file_observations(file_id,observation_id);
CREATE INDEX idx_lineage_file ON operation_files(file_id,operation_id);
```

**Recovery, content, cache, discovery and backup records.** The first five are
written by recovery (4.2), `contents` and `thumbnail_cache` by the scan,
`run_discovery` by a full Index (4.3), and the backup records by catalog backups
(4.1); `file_changes` and `content_similarity` are defined but not yet written.
Statement order matters here too:
`contents` precedes everything referencing it, `operation_events` precedes
`attention_issues`, and both `operation_evidence` and `attention_issues` precede
the link table joining them.

```sql
-- Shared content identity. Similarity and thumbnails both key on content rather
-- than on a file, so identical copies are compared and rendered once.
CREATE TABLE contents (
    content_id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash_algorithm TEXT NOT NULL, digest TEXT NOT NULL,
    phash TEXT, phash_state TEXT, width INTEGER, height INTEGER,
    UNIQUE(hash_algorithm, digest)
);

-- Append-only step outcomes. An operation carrying an 'intent' event and no
-- terminal event is what recovery recognises as interrupted (4.2).
CREATE TABLE operation_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id INTEGER NOT NULL REFERENCES operations(id),
    timestamp TEXT NOT NULL, step TEXT NOT NULL, outcome TEXT NOT NULL,
    detail_json TEXT
);

-- What recovery OBSERVED, kept separate from what the engine DID. An
-- unreadable location is not an absent one, and neither is a mutation.
CREATE TABLE operation_evidence (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id INTEGER NOT NULL REFERENCES operations(id),
    file_id INTEGER REFERENCES files(file_id),
    observed_at TEXT NOT NULL,
    location_role TEXT NOT NULL CHECK(location_role IN ('source','destination','partial')),
    observed_path TEXT NOT NULL, observation_kind TEXT NOT NULL,
    observed_content_id INTEGER REFERENCES contents(content_id),
    result TEXT NOT NULL CHECK(result IN ('present','absent','unreadable','match','mismatch')),
    details_json TEXT
);

-- Deliberately mutable: an issue is resolved by evidence, never deleted.
CREATE TABLE attention_issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id INTEGER NOT NULL REFERENCES operations(id),
    file_id INTEGER REFERENCES files(file_id),
    category TEXT NOT NULL, summary TEXT NOT NULL, opened_at TEXT NOT NULL,
    resolved_at TEXT, resolution_event_id INTEGER REFERENCES operation_events(event_id)
);

CREATE TABLE attention_evidence (
    issue_id INTEGER NOT NULL REFERENCES attention_issues(issue_id),
    evidence_id INTEGER NOT NULL REFERENCES operation_evidence(evidence_id),
    PRIMARY KEY(issue_id, evidence_id)
);

-- file_changes and content_similarity: defined, not yet written. thumbnail_cache
-- is written by the scan and the backup records by catalog backups (4.1).
CREATE TABLE file_changes (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES operation_events(event_id),
    file_id INTEGER NOT NULL REFERENCES files(file_id),
    before_content_id INTEGER REFERENCES contents(content_id),
    after_content_id INTEGER REFERENCES contents(content_id),
    before_path TEXT, after_path TEXT,
    before_values_json TEXT, after_values_json TEXT
);

-- One row per unordered pair; the CHECK is what prevents a reversed duplicate.
CREATE TABLE content_similarity (
    low_content_id INTEGER NOT NULL REFERENCES contents(content_id),
    high_content_id INTEGER NOT NULL REFERENCES contents(content_id),
    distance INTEGER NOT NULL, computed_at TEXT NOT NULL,
    PRIMARY KEY(low_content_id, high_content_id),
    CHECK(low_content_id < high_content_id)
);

-- Cache state, not lineage: generation never modifies the photo. Keyed on
-- (content_id, size) because a photo has a grid thumbnail and may also have a
-- larger detail preview, managed independently: previews are generated lazily
-- and can be cleared without touching the grid. `bytes` makes a per-size total
-- a SUM rather than a walk of the cache tree.
CREATE TABLE thumbnail_cache (
    content_id INTEGER NOT NULL REFERENCES contents(content_id),
    size INTEGER NOT NULL CHECK(size > 0),
    cache_filename TEXT, bytes INTEGER,
    availability TEXT NOT NULL CHECK(availability IN ('present','absent','failed')),
    attempted_file_id INTEGER REFERENCES files(file_id), observed_path TEXT,
    failure_category TEXT, failure_detail TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY(content_id, size)
);
CREATE INDEX idx_thumbnail_size ON thumbnail_cache(size, availability);

-- What a full Index walk found, by file type (webui-spec 5.1).
-- Measured counts only: a scoped run walks nothing and has no row. Excluded files
-- are untouched and are not failures; any unreadable folder or entry makes the
-- counts partial.
CREATE TABLE run_discovery (
    run_id INTEGER PRIMARY KEY REFERENCES runs(id),
    files_found INTEGER NOT NULL, eligible INTEGER NOT NULL, excluded INTEGER NOT NULL,
    excluded_by_extension_json TEXT NOT NULL, unreadable INTEGER NOT NULL,
    CHECK(files_found = eligible + excluded)
);

-- An attempt is history; an artifact's availability is current observed state.
-- outcome is NULL only while an attempt runs; one found NULL under the engine
-- lock was interrupted.
CREATE TABLE backup_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_kind TEXT NOT NULL CHECK(trigger_kind IN ('manual','post_job','pre_action')),
    related_run_id INTEGER REFERENCES runs(id),
    started_at TEXT NOT NULL, ended_at TEXT,
    outcome TEXT CHECK(outcome IN ('succeeded','failed','interrupted')),
    error_category TEXT, error_detail TEXT
);

-- 'pruned': retention removed the file. 'missing': gone for a reason the
-- application did not record. 'unknown': backup storage could not be reached.
CREATE TABLE backup_artifacts (
    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES backup_attempts(attempt_id),
    relative_filename TEXT NOT NULL, size INTEGER NOT NULL,
    compression_format TEXT, created_at TEXT NOT NULL,
    availability TEXT NOT NULL CHECK(availability IN ('present','missing','unknown','pruned')),
    last_checked_at TEXT, pruned_at TEXT
);

CREATE INDEX idx_evidence_operation ON operation_evidence(operation_id,evidence_id);
CREATE INDEX idx_events_operation ON operation_events(operation_id,event_id);
CREATE INDEX idx_open_attention ON attention_issues(file_id) WHERE resolved_at IS NULL;
```

**Immutability is enforced by triggers, not convention.** `operation_events`,
`operation_evidence`, `file_changes` and `attention_evidence` reject `UPDATE` and
`DELETE` alongside the version 2 tables. `attention_issues` is deliberately
excluded — resolving an issue must update it — as are `thumbnail_cache`,
`content_similarity` and `backup_artifacts`, whose availability is current state
rather than history.

The implemented settings table belongs in the same database as the catalog and history,
so one consistent database backup includes all persistent application state.
Explicit initialization is available before Index. Settings saves use narrowly scoped API writes through shared database code (`webui-spec.md` §6.1). The shared layer creates:

```sql
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY CHECK(key IN ('workers','exts','backup_retention')),
    value_json TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    updated_at TEXT NOT NULL
);
```

**No `retry_count` column.** There is no retry subsystem — re-running the
operation is how a failed file is retried (§4.1).

**Settings write ownership (shared layer implemented; API pending):** the engine owns the schema
and photo state/history; the web UI manages settings through scoped API writes using
shared Python database and validation code. SQLite serializes short transactions;
use bounded waits and report failed saves without changing active job configuration.
Settings saves must remain available during processing, separate from the job-long
file-operation lock. Engine-owned initialization routines support creation before
Index. The browser has no direct database access. The shared layer uses atomic revision checks and bounded writer waits; API integration
remains implementation work.

**Design note — why separate state from history:** `photos` answers "what's the current state of this file?" — a single `error_message` column there could only ever hold the *most recent* attempt's outcome, and couldn't show that a file failed twice with different errors before eventually succeeding, or answer "show me everything that happened in run #47." Splitting current-state (`photos`) from historical audit log (`operations`, joined to `runs` for run-level context) answers both without overloading one table with two different jobs.

## 7. Non-Functional Requirements
*   **Concurrency (within a run):** `ProcessPoolExecutor` parallelizes hashing/metadata-resolution across CPU cores; sized to `os.cpu_count()` or overridden via `--workers`.
*   **Single-Instance Guarantee (across runs):** At most one engine process may run at a time, enforced by the OS-level lock in §4.1 — this is what makes the "Thread Safety" guarantee below hold once the web UI can trigger the engine from several places. Without it, two processes (each thread-safe internally) could race at the filesystem and database level, for example both resolving the same free destination name, or both reconciling the same interrupted row. The lock makes the "two processes at once" precondition impossible rather than trying to make each race safe.
*   **Thread Safety:** Index results are written by one dedicated consumer thread; scoped settings writes may use separate connections with SQLite serializing transactions; all other work happens in separate processes that communicate results back through an in-memory queue, never by opening the database themselves.
*   **Durability:** The engine can recover from both a graceful interruption and a hard crash — orphaned partial files are cleaned up, interrupted `Processing` file-records are reconciled to their correct state, and run-records left in an active state are marked `Interrupted`, all on the next startup.
*   **Safety:** No file is deleted from source until a byte-for-byte verified copy exists at the destination. This holds for both direct moves and duplicate-source cleanup, and is never bypassed by cancellation — a cancelled run simply stops starting new work, it never skips verification on work already in flight.
*   **Nothing at the destination changes on the engine's own initiative.** Every modification or removal of an existing file under `--dest` is the direct result of the user explicitly requesting that specific change. This has two layers, and both matter:
    *   **Automatic operations only add.** Index, Copy and Move never modify or remove a file that already exists at the destination. A bug in those paths can at worst leave a redundant file, never destroy one — which is why `--copy` is trivially safe and why a failed move leaves the source intact.
    *   **User-initiated changes are recorded.** Curation (§9) does modify the destination: a rename records both the old and new path; a superseded file is deleted, with an operation recording its path, size, hash and the reason. Deletion is never a side effect — it follows an explicit per-file choice, and a bulk selection must state its count and be confirmed first. By the time curation happens the sources are typically gone, so a destination file may be the only copy in existence: the guarantee here is a complete record of what was removed and why, not the ability to undo it. A user who wants the stronger guarantee keeps the source and mounts it `:ro`.

## 8. Known Limitations and Deferred Work

Deliberate deferrals, each recorded with the condition that should bring it back. None is a content-safety issue: the guarantee in §7 — nothing deleted without a verified, durable, distinct copy — holds in every case below. They are bounded by measurement or by scale that this project has not reached.

*   **A stalled worker has no deadline.** Cancellation is checked between files, and between batches during a scan, but a worker blocked indefinitely (an unresponsive network mount, a native decoder wedged on a malformed file) stalls the run with no timeout: `future.result()` waits forever, and shutting the pool down waits for its workers. The escape is `docker stop`, which escalates to `SIGKILL`; the kernel releases the lock and the next run reconciles. The unbounded *wait* is confined to the scan phase, where `future.result()` and pool shutdown both wait on workers with no deadline. A blocking filesystem call can stall either phase: single-threading governs concurrency, not whether a syscall returns, so a hung mount can halt a copy or a delete just as readily. The safety position is unchanged either way — a stall during Move leaves the source in place, and `docker stop` releases the lock. **Revisit when web-UI job management exists**, where a hung job blocks the UI rather than one terminal. A real fix needs process-tree cleanup, not merely a timeout on the result: a deadline that leaves the child running has bounded the wait without bounding the work.

*   **The unchanged-file check loads the whole settled catalog.** `partition_unchanged()` builds a map of every settled row's size and mtime before comparing the run's candidates, so its cost scales with catalog size rather than with selection size; targeting five files still reads every settled row. Irrelevant at tens of thousands of rows. **Revisit past roughly 500,000 rows, or when a small web-UI selection measures slow against a large catalog** — the fix is a bounded fetch or a temporary selection table, and the source-stat caching must survive it.

*   **Batches complete before more work is submitted.** Results are consumed in submission order, so a slow RAW file can leave workers idle at a batch tail. Measured Index throughput on the maintainer's library was network-bound (73–82 MB/s over 1 GbE), which is the actual ceiling there, so a rolling window would buy nothing today. **Revisit when source and destination are both on fast local storage.** Any rewrite must keep what the batching provides: a bound on catalog memory, and the cancellation checkpoint between batches.

*   **Collision chains re-hash from the start — measured, and currently free.** When several distinct photos resolve to one date folder and filename, each new arrival walks the numeric-suffix chain from the beginning, hashing every occupied candidate to check whether it already holds this photo's content. A chain of *n* distinct files costs about *n(n−1)/2* file reads, against the destination rather than the source.

    Measured on a 29,086-file library: every filename in it is unique, and no file has ever needed a numeric suffix. The longest possible chain is therefore 1, and the loop never takes a second step. The quadratic cost is real in principle and exactly zero here, so no cache is justified — one would add a correctness risk to buy nothing.

    **Revisit when an import reuses filenames**, which is normal for camera-numbered files (`IMG_0001.jpg` from several cards) and unusual for the export-style naming measured here, where a unique photo ID is embedded in each name. The check is one query: the most frequently repeated filename in the catalog bounds the longest possible chain. Any cache added then must not replace the live verification that authorises a deletion.

*   **Several catalogs sharing one destination is unsupported.** See §4.1. Documented rather than coordinated, because one installation has one `--base`.


## 9. Destination Curation

Everything above describes getting files *in*. This section describes acting on
what is already there, and it is a different activity with a different safety
story.

**The automatic operations only ever add.** Index, Copy and Move never modify or
remove a file that already exists under `--dest` (§7). Every capability in this
section changes that on the user's explicit instruction for a specific file —
never on the engine's own initiative, and never as a side effect of something
else the user asked for.

**None of this is implemented.** Each subsection below names what the engine
would need, so the gap is visible rather than implied. The corresponding user
interface is specified in `webui-spec.md` §7.

### 9.1. Destination Inventory

The destination is normally the engine's exclusively. Deduplication happens at
Index time by SHA-1 — among files with identical content one row is `Pending`
and the rest are `Duplicate`, and only `Pending` rows are ever written — so a
destination the engine owns is meant to hold one copy of each distinct content.
That is the invariant the engine is built to keep, not something it proves: a
selection or delivery bug can break it, and so can anything outside the engine
that writes to the destination.

A read-only inventory pass records each destination file's current SHA-1 and
location; the catalog then groups by hash to show what is redundant. The same
query shape serves near-duplicates by grouping on `phash` instead — one view,
two columns.

**This is the only thing that can answer "is my destination still intact?"**
Index walks `--source` and never inspects `--dest`, which is why a photo whose
destination file was deleted outside the engine keeps reporting `Skipped —
already copied` (`webui-spec.md` §5.3). Until this exists, that question has no
honest answer and the UI should not imply otherwise.

**Not implemented.** Needs: a destination walk, and a decision about whether its
results live in `photos` or a table of their own.

### 9.2. Re-processing a Disordered Destination

When a destination has been reorganized or polluted from outside, the supported
repair needs no new engine capability: point `--source` at the old destination,
`--dest` at a fresh location, and run `--move`. Index deduplicates by content,
only anchors are written, and duplicate cleanup removes the redundant copies
from what is now the source.

Three costs have to be surfaced before offering it:

*   **Space.** The pre-flight check (§4.2) requires free space at the new
    destination for the whole pending payload — every distinct file — plus a
    500 MB margin, before anything is copied. Deleting from the old destination
    frees space only on *its* filesystem, so when the two are on different
    filesystems the new destination needs room for the entire de-duplicated
    library. Even on one filesystem, the check asks for the full amount up front.
*   **Photo IDs and run history do not survive it.** See §10.
*   **Files dated from modification time depend on that time surviving.** A photo
    with no usable EXIF date is filed under its mtime (§2). **The engine
    preserves mtime when it copies**, to the nanosecond (`TODO.md` claim 7), so re-indexing a destination the engine wrote files those
    photos in the same place again, provided nothing touched them in between and
    the timezone is the same. Two things break that: a tool that rewrote or
    re-copied the old destination without preserving times, which leaves the date
    of that operation as the new mtime; and a different `TZ`, which can move a
    file across a year boundary. Files carrying a real EXIF date are unaffected.
    The count is directly available as `date_source = 'file_mtime'` in
    `metadata_json`.

The inventory (§9.1) detects differences without modifying photos. When a mismatch is found, direct the user to this fresh-destination workflow; it logs new processing but cannot reconstruct external changes or recover missing pixels.

### 9.3. Similarity: Perceptual Pairs

pHash is computed and stored for every file already (§4.2), including RAW. What
does not exist is anything that compares them.

**The comparison must be precomputed, not computed per view.** The user-facing
control is a match-percentage slider (`webui-spec.md` §7), and a slider that
recomputes Hamming distances across the catalog on every movement is not a
slider. The engine should compute pairs below the *loosest* threshold the UI
offers, once, during Index, and store them; the slider then filters a table
rather than scanning one.

**This is what `collision_group` was reserved for** (§6.1). `is_master` is a
separate question and still open: the similarity review holds the user's chosen
primary as client state, which needs no column, because the engine has no basis
for picking a winner among visually similar files and must not appear to. But
persisted provenance for lineage and EXIF history (§9.8) might use it. Nothing
should populate it on the engine's own initiative either way.

**A photo with no usable pHash cannot participate.** Those are already counted
and warned about in the run summary (§4.3).

**Required comparison scope:** compare newly indexed photos against all catalogued
photos with usable perceptual hashes, including delivered photos. Backfill existing
catalogues when matching is introduced. When a hash changes, invalidate its old
relationships and recompute them. Stored pairs must cover the full offered slider
range. Missing hashes mean matching is unavailable, not that a photo is unique.

Results are measured against the selected reference photo; similarity is not
transitive. Historical records remain available for lineage but must not appear as
actionable files without an available copy. Width and height are already captured
during Index on `contents`, from the same decode that makes the thumbnail, and are
NULL when unavailable.

**Not implemented.** Needs: pair storage, initial backfill, incremental refresh,
and the comparison pass during Index.

### 9.4. Renaming a Delivered File

When duplicates are removed, the surviving copy keeps its own filename — which
may be the least descriptive name in its group. A camera-style name can survive
while the duplicate removed against it carried the name a person actually chose.

*   **The data already exists.** Every source path in a group is recorded and
    kept after a move or duplicate removal: `photos.source_path` on the
    `Duplicate`/`Removed_Duplicate` rows, and `operations.source_path` for every
    attempt, grouped by `sha1_hash`. No new capture is needed — provided the
    catalog is kept, since it is the only record of those names once the sources
    are gone (§10).
*   **User-chosen, never automatic.** Which name is more meaningful is a
    judgement; the UI offers the group's names as candidates and the user picks.
*   **Keep the file's real extension.** Use the chosen name's stem with the
    delivered file's actual extension, so a rename never mislabels a format.
*   **It must be no-overwrite** — link-then-unlink, or a no-replace rename — with
    the same `_N` suffix rule on a collision (§4.2); it must update
    `photos.dest_path`; and it must record an operation carrying both the old and
    new path, so a photo's history still leads to where it is now.

The date folder and actual extension remain unchanged. Preview the collision-resolved
name and report the actual resulting name after execution. Update current references
from related exact-duplicate rows to the renamed copy; historical operations retain
the paths true at their time. A missing file or content mismatch stops the operation
and invokes the destination-mismatch guidance in `webui-spec.md` §7.6.

Record both paths for lineage and manual correction. There is no user-facing undo;
a later rename is a new action validated against the current state.

**Not implemented.** Needs: the rename operation and its audit row.

### 9.5. Superseding a Delivered File

Choosing between files that *differ* — a JPEG versus the RAW it came from, a
thumbnail versus its original — means one file leaves the library.

**The rule: a superseded file is deleted, and the deletion is recorded.** There is no quarantine area. The user asked for that file to go;
the engine removes it and writes an operation recording what was there.

**Why not a quarantine instead?** A `.superseded/` area holding removed files,
emptied only by a separate explicit act, is the obvious alternative, and the
argument for it is real: a careless decision should be recoverable. It is
rejected on two grounds. **Quarantine does not buy reversibility where it
matters** — it defers a deletion the user already chose, and the person who
empties it carelessly is the same person. **And the
protection it offers is available upstream, with no engine complexity**: a user
worried about losing destination files can keep the source and mount it `:ro`,
which protects the pixels themselves rather than a copy of them.

**So the record carries more than any other operation**, because it is the only
record that will outlive the thing it describes: path, filename, `sha1_hash`,
`phash`, dimensions, file size, and the full EXIF as of deletion. Enough to
identify the file by content anywhere a copy might still exist — an old drive,
an unmoved source — rather than by a name that no longer resolves.

**Say plainly what this costs.** By the time curation happens the sources are
typically gone, so the destination copy may be the only copy in existence: this
capability can destroy the last copy of a photograph. That is why it requires
explicit per-file consent, and why a bulk selection must state its count and be
confirmed before acting (`webui-spec.md` §7). We cannot recover pixels; we can
refuse to remove them quietly.

**Recorded source information is not proof of a surviving copy.** A `Copied` row
records that the engine left a source in place at that time; it does not establish
that the file still exists. Only claim an available matching copy after checking it.
Each deletion requires an irreversible-deletion warning, even when a catalog backup
exists. Keep the extended record accessible in history and remove deleted files
from actionable lists. Record per-file failures. Stop on a detected destination
mismatch and present the repair guidance in `webui-spec.md` §7.6.

**Not implemented.** Needs: the first engine path that removes a file under
`--dest`, and the extended deletion record above (dimensions come from `contents`).

### 9.6. Writing Metadata Into Files

Correcting or merging EXIF — persisting a good copy's date onto the survivor, or
filling in a date a file never had. This is the only capability that mutates
file *contents*, and the scope boundary in `project-spec.md` §1 is what makes it
eventually unavoidable: a consuming gallery reads EXIF from the file, so a
correction that lives only in this catalog is a correction the gallery never
sees.

**Write changes back to the metadata source.** Embedded metadata is updated inside
the delivered photo. Manually entered values also go into that photo. Retained
source originals are not edited. Unsupported writes fail explicitly rather than
silently creating a sidecar or storing the correction only in the catalog.

**Verify all requested fields before replacement (planned).** Apply a photo's
requested metadata changes to a temporary working copy and read back every requested
field, including explicit removals, against the validated intended values. Replace
the original only after all requested fields and required file-integrity checks pass.
If a field fails writing or verification, discard the failed working copy, leave
the original unchanged and log the per-photo failure with field details. Never
publish a subset of the requested field changes. Other photos in a batch may succeed.
Failures during subsequent publication/refiling still require the recovery and
accurate partial-outcome reporting below; temporary-copy validation is not a claim
that all filesystem and database changes form a single atomic transaction.

Before staging each metadata edit, check destination space for the working output
and recovery material. Stage and finish one photo at a time in a batch; do not stage
the entire selection. Insufficient space leaves the original unchanged and records
required/available space for the UI. Handle space exhaustion during writing as well
as pre-check failure; preserve material needed for incomplete recovery. This is
planned functionality, with user-facing behavior in `webui-spec.md` §7.5.

For planned bulk metadata edits, graceful cancellation completes the current photo's
write/verification/refiling or records its failure, then starts no further photo.
Keep successful edits and leave unstarted files unchanged. Record per-photo outcomes
and batch membership, preserving full lineage for manual correction. No automatic
rollback of completed photos or resumption of the remaining batch is permitted.

Preserve the provenance of metadata values so future sidecar support can distinguish
embedded values from companion-file values. Dates inferred from filenames or file
attributes are reference information, not embedded EXIF. Sidecar reading, writing,
publication, precedence and synchronization remain future options, not prerequisites
for implementing embedded edits.

An edit and any required refile form one user action: preserve before/after values,
paths and content identities; update current catalog references; do not report success
with corrected metadata at an incorrect location. Failure handling must restore the
prior state where possible and report any incomplete recovery. This is write-failure
handling, not a user-facing undo feature.

**Not implemented.** Needs: the embedded write and verification path, coordinated
refiling, provenance and change records, and failure recovery.

### 9.7. The destination contract

**Every file under `--dest` sits in the folder its own metadata implies.**

This extends the invariant in §7 rather than restating it. §7 says the engine
changes nothing at the destination *on its own initiative*. This says that
whatever the engine **is** asked to change must leave the destination
internally consistent afterwards. §7 governs what the engine does unbidden;
this governs the results of what it is told to do.

Two obligations follow, and between them they cover every destination-writing
operation in §9:

*   **An operation that changes a file's metadata must also place the file
    correctly, in the same action.** Correcting an EXIF date, copying metadata
    from a similar photo, applying one date across a batch — each changes the
    folder the file belongs in, and leaving it where it was would make the tree
    disagree with the data it was built from.
*   **An operation that moves or renames must leave the property true.** A
    rename does not change the date, so the folder stays correct by
    construction (§9.4). A refile moves the file *because* the date changed,
    which is the contract being honoured rather than an exception to it.

**The destination is the only writable surface.** Source files are read and
catalogued, never altered — which is exactly why `--source` can be mounted
read-only and why Index needs no write access at all. Every editing capability
in §9 is therefore available **only for photos already delivered**, and the
engine already holds the test: the delivered-status set, `Completed` or
`Copied`.

*The consequence is worth stating plainly rather than leaving to be
discovered:* **correcting metadata requires organizing first.** A photo that
has only been indexed must be Moved or Copied before its EXIF or filename can
be touched. It lands under its wrong date, then refiles when corrected. That
churn is the price of the guarantee that the user's original library is never
written to, and it is the same reasoning that defers choosing a filename at
move time (§9.4).

**The contract is absolute — there is no opt-out setting.** No supported path
leaves a file in a folder its own metadata denies. The worry an opt-out would
answer — losing track of a file after an edit — is met instead by the
operations log, which records both the old and the new path for every move.

**That makes the operations log load-bearing for a user need, not merely an
audit trail**, and it raises the stakes on §10: discarding history in a catalog
rebuild would cost the user their only means of finding where their files went,
on top of losing the audit record.

**The workflow order falls out of this contract rather than being a
convention.** Index → Copy or Move → cleanup, in that order, because if only
delivered files can be modified then no cleanup *can* precede delivery. The
alternative — letting a user edit between Index and Move — means recording
intent rather than performing it, which needs a queue that persists across
crashes, resolves two edits to one file, and reconciles when a source changes
before the move. That is a subsystem, and it earns nothing: everything it would
defer can simply be done after delivery. A user who wants to curate before
committing to source deletion should `--copy`, curate, then deal with the
originals themselves — same order, non-destructive.

*A superseded file is outside this contract because it is outside the library:*
§9.5 deletes it and records the deletion. The contract governs the library, not
what has been removed from it.

### 9.8. Capabilities the web interface needs

Metadata edits whose resulting hash matches another catalogued file must preserve
both files and their distinct lineage, recording the new duplicate relationship
without automatically deleting either file. Duplicate cleanup requires a separate
confirmed action; see `webui-spec.md` §7.5.

Thumbnail cache lifecycle must follow content identity: after an embedded metadata
edit, reuse an existing entry for the resulting hash or generate a new thumbnail.
Remove obsolete entries only when no current catalogued file needs their hash;
historical lineage does not retain thumbnails. Include orphan cleanup after
interruption. See `webui-spec.md` §4.2.1. The scan writes one 320px grid thumbnail
per content identity, and after every scan that completes cleanly, with thumbnails
enabled, the engine removes each cache entry (file first, then record) whose content no catalogued photo
holds in any status, keeping the `contents` identity it was keyed on. Cache files the
catalog never recorded are left alone, because the cache survives a catalog rebuild
on purpose. Orphan cleanup after an interrupted *edit* waits for edits to exist.

§9.1–§9.6 record the engine capabilities the curation workflows require. The web
workflows need the five below as well. None of them is visible as engine work from
the UI side — each looks like a screen until you ask what it reads from.

| Capability | Needed by | Why it cannot be supported today |
| :--- | :--- | :--- |
| **Refiling after a date change** | Any metadata correction, single or bulk | This is what makes §9.7 enforceable. Within one destination it is an **atomic rename**, not a Copy-Verify-Delete: no bytes move and there is nothing to verify. The engine already computes a file's correct folder, creates date folders durably, and resolves name collisions — what is new is the destination-to-destination move and an operation recording both paths |
| **Field-level before/after for metadata edits** | Full lineage and informed manual correction | Preserve the original indexed information and each change, linking old/new identities when content hashes change. No user-facing undo; see §10 |
| **A batch identity** | Bulk metadata apply | So an edit and the refile it triggers read as one action rather than two unrelated ones. `runs.run_id` is the precedent for exactly this grouping |
| **Pre-action catalog backup** | Before a confirmed rename, EXIF edit or destination deletion | The engine half of backups is built (§4.1): post-job and manual snapshots, retention, availability. The `pre_action` trigger exists in the schema and `ns_db.backup_catalog` accepts it, but nothing calls it until the curation actions it guards exist. It must stop the action when it fails (`webui-spec.md` §9) |
| **Serving a file for download** | Log export; retrieving a backup | **API work rather than engine work**, recorded here because it is the same gap twice and worth building once |

**Two of these want a schema change**: field-level before/after and a batch
identity.

## 10. Full Lineage and File Identity

**Reimport after deletion:** a newly imported file receives a new lineage and
original Index snapshot even when its hash matches a previously deleted file.
Retain the deleted record and link the two as matching content; do not revive the
deleted identity or erase its deletion event. A historical match alone must not
classify the new import as already delivered or authorize duplicate-source deletion;
those decisions require a current eligible copy and the normal verification checks.

**Identity across content changes:** each logical file retains a stable lineage
identity independent of its current path and content hash. For every tool action
that changes content, record the before/after hashes linked to that same lineage
and its original Index hash. Preserve the full chain rather than replacing the old
hash. Separate source copies with identical hashes retain distinct lineages; a
matching hash identifies shared content, not permission to merge their histories.
Reusing a deleted file's path must not attach the replacement file to its history.

**The identity schema is implemented.** `files` holds the stable identity,
`file_origins` its immutable creation provenance, `file_states` its current path and
presence, and `source_snapshots` the original Index evidence that later scans never
overwrite (§6.5). Content-version transitions — the before/after hashes of an edit —
remain unimplemented, because nothing yet modifies a photo's content.

**Deletion retains lineage.** Preserve the original source snapshot, last recorded
file state and complete recorded action history, including per-field before/after
values and locations. Do not cascade-delete history or invalidate references used
by photo info screens and logs. Mark the file deleted and exclude it from actionable
library results while retaining historical lookup. These records support manual
reconstruction of recorded metadata and naming/location history, not image pixels.

**Original filesystem snapshot:** preserve each source file's original
Index path, size and modification time, including every duplicate independently.
Capture genuine filesystem creation time when available; otherwise record it as
unknown, never substitute Unix ctime. This immutable snapshot is separate from
current stat values used for change detection and must survive rescans and edits.
When a usable capture date is absent or removed, use the originating source
snapshot's modification year for `Undated/<year>`, not the time of an EXIF edit or
destination-file creation. Use the same recorded value for preview and actual filing.
Full stat snapshots after every Copy/Move are not required for this fallback; live
safety checks and operation lineage remain required. **`source_snapshots` implements
this** (§6.5): one immutable row per source identity, written at first Index and never
overwritten, with later reads appended to `file_observations` instead. `photos.file_mtime`
is a separate, mutable value refreshed on rescan for change detection, and is not the
fallback source — using it would reintroduce exactly the drift this snapshot prevents.
The scan reads the snapshot value and files from it: the two agree on a first Index,
which is why filing from the mutable value looks correct until a re-index of a touched
file silently moves that photo to a different year folder.

**Required behavior:** each destination file must remain traceable to its original
source Index information: filename, path, captured metadata, hashes and file
attributes. Preserve every copy, move, rename, EXIF update and deletion, including
before/after values and locations as applicable. Changed names or content hashes
must not sever the chain or overwrite original indexed evidence. Bulk actions need
both a common identity and individual file outcomes.

**Enforced and verified, not merely required.** Complete lineage is reconstructable
for every catalogued file in every settled status — `Pending`, `Copied`, `Duplicate`,
`Completed`, `Failed` and `Removed_Duplicate` — comprising its original Index
snapshot, current state, creation origin, and every operation it took part in. This
is `TODO.md` claim 11, enforced by
`every_catalogued_file_assembles_complete_lineage`. That test drives two catalogs,
because no single one holds every status at rest: a run ending in Move leaves
`Completed`/`Failed`/`Removed_Duplicate`, one ending in a targeted Copy leaves
`Pending`/`Copied`/`Duplicate`. It asserts the required set is covered, so a **new**
status that nothing verifies fails the test rather than passing unnoticed.

**An unreadable source is included.** A file the engine cannot read is catalogued
`Failed` with no hash and the real `PermissionError` recorded, and still assembles a
full history. It is the row most likely to be dropped and the one a user most needs
explained.

**One honest exception.** A destination the engine *found* rather than created has no
source snapshot, because no Index ever saw it. It is recorded as
`observed_destination` with a NULL origin rather than given a fabricated one, and the
guarantee reads "traces to an Index snapshot **or** is recorded as observed with
unknown origin" — not "everything traces to an Index".

Measured against a real-library catalog of 971 identities: every identity traced or
explicitly observed, zero dangling origins, zero foreign-key violations, and a full
history assembled in 0.02–0.08 ms, covered by `idx_lineage_file` and
`idx_events_operation`. Reading a history correctly is a separate concern — a view
keyed on `photos.id` alone drops the pre-reimport half of a file's past; see
`webui-spec.md` §6.3.

**Recovery provenance is required for truthful job reporting.** Distinguish a
record written while reconciling earlier interrupted work from one describing the
current request. Preserve the relationship to the interrupted action/run when known
and to the run that performed recovery. The representation is
`operations.reconciles_operation_id` (§4.2): a recovery row names the operation it
repairs and belongs to the run that performed it, so the API never parses free-text
messages to tell recovery from requested work. Failures with
NULL photo IDs remain run-level issues rather than failed-photo counts. All records
associated with a photo must be accessible from its info page as well as global Logs
(`webui-spec.md` §4.2 and §5.5); the engine records the links, and presenting them is
API and UI work.

History supports manual corrections, not undo operations or a rewind of the library.
A user consults prior values and makes a new explicit edit or rename against the
current state. Records cannot recreate deleted pixels. This is a required capability,
not a claim that current mutable photo rows already preserve all that evidence.

**History is keyed by file identity, not by `photos.id`.** Operations reach files
through `operation_files`, so a history follows `file_id` across renames, moves,
reimports and edits; reading it by `photos.id` alone drops the pre-reimport half of a
file's past (`webui-spec.md` §6.3). The Error Center and the Operations Audit Log read
history the same way.

**A catalog rebuild still discards history.** `photos` is derived and an Index
recreates it, but `runs`, `operations` and the lineage records are the only record of
what the engine did, and nothing recomputes them. After a `--move`, a
`Removed_Duplicate` row is the only evidence a file ever existed. That is why catalog
backups exist (§4.1) and why deleting a user catalog is never routine repair.

**Rejected alternatives:** hash-only identity merges distinct copies and breaks on
metadata edits; path-only identity breaks on renames and path reuse. Stable per-file
lineage with linked content hashes is used instead, including records for failures
without a hash. Catalog, settings and history share one database so one backup holds
all of it; a second history database is not the design.


### Destination lineage implementation contract

Successful transfer outcomes update destination identity and participant links in the
same transaction as the legacy outcome log. A new successful Move retains source A;
Copy creates B with A's original source as its origin. Copy children do not get a
fabricated source Index snapshot. Reusing recorded B preserves B and links it as the
retained copy; verified removal retires A without merging IDs. Each original source,
including duplicates, remains reachable through operation participants.

`file_origins` records immutable creation provenance; `file_states` records current
location/presence. A newly observed, previously unrecorded retained destination has
unknown creation origin, with its verified reuse linked to the source operation.
Hashes and paths do not substitute for file IDs. Fresh publication at a formerly
recorded but absent destination preserves the old identity as missing.

Interrupted/failed transfers do not receive fabricated successful lineage; recovery
records durable intent, evidence, attention issues and recovery links instead (§4.2).
Recovery must preserve an incomplete Move when both copies
remain and must not automatically delete the source; a new explicitly requested Move
may verify and remove it. Recovery outcomes belong separately from new job work.
