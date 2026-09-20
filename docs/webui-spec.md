# Functional & Technical Design Specification: NegativeSpace Web Interface

## 1. System Overview & Architecture

The NegativeSpace Web Interface provides a modern web UI for the containerized Python engine (`ns-engine.py`). It transforms the CLI engine into an interactive application supporting real-time operation monitoring, selective file processing, context-aware duplicate resolution, detailed metadata inspection, dedicated runtime settings management, extension validation, and audit logging.

**The web UI is the interface.** The engine's command-line flags are an *internal* calling convention between FastAPI and the engine — not a supported end-user surface. Users interact with NegativeSpace through the web UI; nothing in the user-facing documentation should direct them to invoke `ns-engine.py` by hand.

The flags are deliberately **not** hidden (no `argparse.SUPPRESS`), and the engine reference documentation stays in the repository. Anyone cloning the project to understand, debug, or extend it benefits from being able to run the engine directly, and hiding the flags would buy nothing — anyone who can execute the engine can read its source. The distinction is *documented for users* versus *available to developers*, not *present* versus *absent*.

```
+-----------------------------------------------------------------------------------+
|                                  React Frontend                                   |
|  [ Dashboard ]  [ Gallery / Grid ]  [ Split Inspector ]  [ Settings / Config ]    |
+-----------------------------------------------------------------------------------+
| HTTP REST / WebSockets
+-----------------------------------------------------------------------------------+
|                                 FastAPI Backend                                   |
|  [ Job Queue ]  --->  [ Engine Subprocess Execution ]  --->  [ Log Parser Engine ]|
+-----------------------------------------------------------------------------------+
| SQLite (WAL) / Subprocess
+-----------------------------------------------------------------------------------+
|                                   Engine Core                                     |
|   (ns-engine.py --workers N --exts ex1,ex2 --file-ids id1,id2               |
|                        --source-subdir path)                                      |
+-----------------------------------------------------------------------------------+
```


---

## 2. Core Operational Requirements & Workflows

### Operational Flow

```
1. User triggers an Index scan (full directory or, on a repeat visit,
   just a "Rescan" to pick up newly added files).
   -> FastAPI checks for an already-active job (409 if one exists, §5.7)
   -> FastAPI spawns: python3 ns-engine.py
   -> Engine scans the full source directory, hashes everything, flags
      duplicates, captures metadata, and populates SQLite.

2. Frontend queries the catalog (paginated/filterable) and renders it
   as a browsable, selectable grid (Gallery view).

3. User selects one or more files (or a folder, for large batches — see
   §2's Selective File Processing) and chooses an operation: Move or Copy.

4. Frontend POSTs the selection + operation to FastAPI
   (`POST /api/v1/jobs/start`, see §6.2).

5. FastAPI re-checks for an active job (409 if one exists), then spawns
   the engine, scoped one of two ways:
   python3 ns-engine.py --move --file-ids 101,102,105  (or --copy)
   python3 ns-engine.py --move --source-subdir sd_card/day1

6. Job progress streams back to the frontend via WebSocket, reusing the
   engine's own status transitions (Pending -> Processing ->
   Completed/Failed/Removed_Duplicate) rather than a separate progress
   protocol. Any client connecting or reconnecting first replays
   `GET /api/v1/runs/{run_id}/operations` before tailing live (§4.1).

7. Frontend updates the Gallery/Operations Drawer in real time as rows
   change status.
```

The full-directory Index (step 1) is the one operation that is *not*
selection-scoped — there's nothing to select from until the catalog
exists. Every operation after that can be either whole-directory or
scoped to a specific selection via `--file-ids`.

### Action Mode Selection
The UI allows switching between execution modes prior to triggering operations:
* **Move Mode (`--move`):** Transactional Copy-Verify-Delete. Deletes source files only after SHA-1 checksum verification succeeds at destination.

**No source file is ever deleted on the catalog's word alone.** All three places the engine removes a user file — the verified copy in Move, an already-delivered source it finds at the destination, and a duplicate source during cleanup — hash *both* files live at the moment of the decision. Stored hashes identify a candidate; they never authorize a deletion. A UI must not offer to relax this, and it needs no separate "verify before deleting" option, because there is no path that skips the check.

One consequence for display: after a Move, each `Duplicate` row's `dest_path` is repointed at the location recording its content, and that step reads no files by design. A duplicate's recorded destination therefore means *where its content is recorded*, not *confirmed present and matching*. Do not present it as verified — the guarantee lives at the moment of deletion, not in the column.
* **Copy Mode (`--copy`):** Non-destructive. Performs verified copy to destination while leaving source files untouched.

### Selective File Processing
Users can select individual files or multiple files across grid views to run targeted operations.
* **Multi-Select Controls:** Checkboxes on photo cards, Shift-click range selections, and "Select all on page."
* **Selection size limit:** Individual multi-select (including "Select all on page") is capped at a configurable maximum (default: 1,000 files) per job submission — this isn't an arbitrary UX restriction, it's because each selected file becomes an integer in the `--file-ids` command-line argument passed to the engine, and there's a real OS limit on total command-line length. Exceeding the cap shows a clear message (e.g. *"1,000 file limit for individual selection — try Folder Selection below for larger batches"*) rather than silently truncating the selection or attempting a job that might fail at spawn time.
* **Folder Selection (for large batches):** Instead of "select all matching current filter" against individual files, users can select a source folder (recursive) and scope the operation to everything currently indexed under it. This maps directly to the engine's `--source-subdir <path>` flag (`engine-spec.md` §4.1) rather than enumerating individual IDs, which sidesteps the command-line length limit entirely — there's no practical upper bound on how many files a folder selection can cover. Symlinks are excluded automatically, inherited from the original Index that populated the catalog (a symlink was never indexed as a row in the first place). If a folder hasn't been indexed yet (zero matching rows), show *"No indexed files found under this folder — run an Index first."*
* **Sticky Action Bar:** Appears when items (individual or folder) are selected, presenting **Move Selected** and **Copy Selected** actions.
* **Targeted Execution:** Individual selections use the `--file-ids <id1,id2>` flag; folder selections use `--source-subdir <path>`. These are mutually exclusive targeting mechanisms in a single job — pick one per submission. IDs (not raw file paths) were chosen for the individual case specifically because a database primary key is unambiguous and doesn't depend on path strings staying identical between when the frontend fetched the catalog and when the operation actually runs — and it keeps one targeting implementation rather than a parallel web-only code path, which is what makes the engine directly runnable for debugging and development (see §1).

---

## 3. Dedicated Settings Management (`/settings`)

A dedicated Settings view provides central management of engine parameters, persisted to SQLite and passed to engine instances on startup.

**Settings changes never affect an already-running operation.** Every engine invocation reads its configuration once, at spawn time, as CLI flags (`--workers`, `--exts`) — there's no live-reload path, by design (see `engine-spec.md` §4.1). Saving new settings in this panel only affects jobs started *after* the save. If a user wants a change applied to work that's currently in progress, they need to cancel the running job (§4.1's Cancel Job) and start it again — at which point the new settings apply from that fresh invocation. The Settings UI should make this explicit (e.g. a note near Save: *"Changes apply to new operations only — cancel and restart an in-progress job to apply immediately"*) rather than implying a change takes effect instantly everywhere.

```
+---------------------------------------------------------------------------------+
| SETTINGS & SYSTEM CONFIGURATION                                                 |
+---------------------------------------------------------------------------------+
| WORKER & PROCESS TUNING                                                         |
| Max Worker Processes (MAX_WORKER_PROCESSES):                                  |
| [ 8 ] (Auto-detected: 8 CPU cores. Controls concurrent hashing & I/O threads)   |
|                                                                                 |
| QUEUE & BACKPRESSURE MANAGEMENT                                                 |
| DB Queue Size (DB_QUEUE_SIZE):    1000 items   (read-only)                      |
| Maximum pending database write operations before backpressure. Fixed in the     |
| engine and not settable from here — see engine-spec.md §4.1.                    |
+---------------------------------------------------------------------------------+
| SUPPORTED FILE EXTENSIONS (SUPPORTED_EXTENSIONS)                             |
| Selected Formats:                                                               |
| [x] .jpg   [x] .jpeg   [x] .cr2   [x] .nef   [x] .arw   [x] .dng               |
| [x] .heic  [x] .png    [x] .tiff  [ ] .mp4   [ ] .mov                          |
|                                                                                 |
| Add Custom Extension:                                                           |
| [ .txt                  ]  [ + Add Extension ]                                  |
|                                                                                 |
| (!) WARNING: Custom extension '.txt' does not natively support EXIF metadata.    |
|     When no EXIF data is present, filesystem creation/modification date will     |
|     be used for organization.                                                   |
+---------------------------------------------------------------------------------+
|                                                   [ RESET ]  [ SAVE SETTINGS ]  |
+---------------------------------------------------------------------------------+
```


### 3.1 Undated Photos: `Undated/` or Modification Time

**Decided 2026-09-17. Implemented 2026-09-20.** A photo with no usable EXIF date goes to an `Undated/<year>/` folder rather than being filed under its modification time inside the date tree. This is **unconditional**: there is no setting, and modification-time filing into the date tree is no longer reachable by any configuration.

*An earlier draft of this line called modification-time filing "the alternative setting". No such setting was ever implemented, and the sentence described an option that did not exist — corrected 2026-09-20.*

The old behaviour is what the mock-up above still describes — *"filesystem creation/modification date will be used for organization"* — and it is wrong in two ways that only show up at scale. It files a photo under a date **nobody vouched for**, mixed in with photos whose dates came from the camera; and once filed, nothing marks it as a guess. Measured on a real library: **95 of 1,165 sampled files (8.2%) had no usable EXIF date**, and the run placed photos from the 2000s into `2024/` and `2025/` folders purely because their download timestamps were recent.

Two reasons this is the better default, both the maintainer's:

* **It stops undated files colliding with genuinely dated ones.** A date folder should mean "the camera said so."
* **A file you can find is a file you can fix.** The catalog keeps `source_path` and the original filename, and for these files that is frequently where the real date actually is — a folder named for an event, a filename carrying `20070415`. `Undated/` is where a person can go and work through them.

That second point makes `Undated/` a **review queue that needs no queue table**: the folder *is* the list, derivable by looking at it. It is the same shape the placement-drift problem wants, arrived at independently.

**Two sub-questions to settle when implementing, each with a recommendation rather than an open survey:**

1. **Flat, or subdivided? `Undated/YYYY/`, with the year fixed by the content rather than by walk order.** At ~8%, a consolidated library could put tens of thousands of files in one directory — navigable by a tool, tedious for a person, which defeats the "easy to find" half of the rationale. So subdivide by year: the mtime is a real fact about the *file* even when it is not a fact about the *photograph*, so it can organise the folder without the tree ever claiming it is the date taken.

   **Implemented 2026-09-20: the year is the placed file's own modification time.**

   *An earlier draft of this section specified the earliest usable `file_mtime` across every row sharing the content's `sha1_hash`, so that every copy computed the same year and walk order stopped deciding anything. That rule was dropped during implementation, and the reasoning is kept here because the argument for it was sound and lost to a consideration it had not weighed.*

   **Why it was dropped.** Two reasons, and the second is the one that settles it:

   *It is not computable where the projection is made.* `dest_path` is written during the scan by a `ProcessPoolExecutor` worker, which is a separate process with no database handle — and the `sha1_hash` group is not even fully known at that moment, since other members may not have been scanned yet. Honouring the group rule would have meant projecting one folder at Index and placing the file in a different one at Move, leaving the catalog advertising a location the file never occupies. The staging screen projects from the catalog, so it would have shown the wrong folder for every undated photo.

   *And the property it bought is worth less than it appeared.* Two byte-identical undated copies form a duplicate group, so **only one file is ever delivered** — the other is flagged `Duplicate` and removed from source or skipped. The choice of anchor therefore changes which *year folder* the single surviving file sits in, never what the library contains, and the other copy's name and path remain recoverable through lineage. `Undated/YYYY/` exists to keep the folder navigable, not to assert anything: every file in it is there precisely because **no date is trusted**, and each will be reviewed regardless. The year is a filing aid, not a claim.

   **Possible refinement, not implemented.** The earliest mtime in a group is a marginally better *lower bound* on a photograph's age — a file downloaded in 2005 and again in 2024 has two, and 2005 is nearer the truth. Worth revisiting only if the year subdivision ever does semantic work; it does not today, and the population it would affect (undated photos that also have duplicates whose mtimes straddle a year boundary) has never been measured.

   **The `file_mtime = 0.0` sentinel does not reach placement.** A failed `stat()` records `0.0` in `photos.file_mtime` — the column is not NULL in that case — but that column feeds the unchanged-file check, not the folder. The date used for placement comes from a separate `os.path.getmtime()` call in the metadata fallback, which raises on failure rather than yielding `0.0`. So a file cannot arrive in `Undated/1970/` by that route. *An earlier draft asked the folder to "tolerate loose files beside its year folders" for a case this path cannot produce; the two values were being read as one — corrected 2026-09-20.* A file whose mtime genuinely is the epoch would still land in `Undated/1970/`, which is correct: the year is a filing aid, and 1970 is what that file says.

2. **What does `date_taken` hold?** **Recommend leaving it exactly as today** — the mtime, marked `date_source = 'file_mtime'` — and changing only *placement*. That keeps the existing census query working (`date_source` already distinguishes them), keeps a value in hand for when a real date is recovered, and confines the change to one decision in the path builder rather than spreading through the metadata layer. One consequence worth stating plainly: a photo's **folder year and its own `date_taken` always agree**, because both derive from the same row's modification time. *An earlier draft said they could disagree, "because the folder reflects the group's earliest usable mtime" — that described the group rule dropped during implementation (see sub-question 1) and has been false since. Corrected 2026-09-20.* The folder answers "where do I go to find this content"; the row records what this particular file said; under the shipped rule those are the same fact, read twice.

**Consequence worth recording:** the undated-duplicate tiebreak is not a problem to solve. Two byte-identical copies with different mtimes still produce different `date_taken` values, so the arbitrary anchor — whichever the unsorted walk reaches first — still decides which `Undated/YYYY/` folder the content lands in. That is acceptable, and deliberately so: **only one file of a duplicate group is ever delivered**, the delivered bytes are identical whichever copy won, and every other copy's name, path and mtime stay recoverable through lineage. An mtime is a data point to record and show, never a basis for the engine to choose between identical files.

*This paragraph has twice been written around a rule that was not shipped.* One draft claimed the leak closed because there was "no date folder to choose" — false once the folder was subdivided by year. A later draft claimed the year was "derived from the content group rather than from the placed row" — false once the group rule was dropped (sub-question 1). Both were arguing for determinism that the delivery model makes unnecessary. Corrected 2026-09-20.

### 3.2 Extension EXIF Support Validation Subsystem
When a user attempts to add or select a custom extension in the settings panel or via API, the backend/UI validates it against a metadata-support registry:

1. **Standard EXIF Image Formats (Native Support):** `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.heic`, `.heif`, `.webp`, and RAW formats (`.cr2`, `.cr3`, `.nef`, `.arw`, `.dng`, `.rw2`, `.orf`, `.pef`).
2. **Non-EXIF Formats (Trigger Non-Blocking Warning):** Container formats or plain files (e.g., `.png`, `.bmp`, `.gif`, `.mp4`, `.mov`, `.mkv`, `.avi`, `.txt`).
3. **UI Warning UX:** Displays an inline warning badge: *"File type `.ext` does not support EXIF data. When no EXIF data is available, file creation/modification date will be used."*
4. **Validation Behavior:** The warning is **informative/non-blocking**. Users can still add non-EXIF file types; the backend flags `has_exif_support = false` in the config state so the engine falls back gracefully to filesystem timestamps (`mtime`/`ctime`).

---

## 4. UI Layouts & Component Specs

### 4.1 Real-Time Operations Drawer
When a job is active, a progress drawer expands at the bottom of the viewport.

```
+-----------------------------------------------------------------------------------+
| [X] Moving 3 Files...  | Progress: [========............] 66% (1 Remaining)       |
+-----------------------------------------------------------------------------------+
| CURRENT STEP: Verification & Checksum Comparison (Workers: 8 | Queue: 42/1000)   |
| LOGS:                                                                             |
| - [DONE] IMG_001.JPG -> /data/dest/2026/02/14/IMG_001.JPG (SHA1 Verified)         |
| - [IN PROGRESS] IMG_002.CR2 -> /data/dest/2026/02/14/IMG_002.CR2                   |
+-----------------------------------------------------------------------------------+
```

* **Metrics:** Active step, progress percentage, active worker count, current DB queue backpressure level, files completed vs. remaining.
* **Live Log Stream:** Direct source-to-destination mapping display with verification status.
* **Job Control:** Provides a **Cancel Job** button. Sends `SIGTERM` to the engine subprocess (§6.2 `jobs/{id}/cancel`). During the **Index/scan** phase the engine stops at the next batch boundary and skips the move/copy phase entirely (everything already indexed is kept, so re-running continues where it left off) — note the UI should not expect per-file `Cancelled` rows for a scan-phase cancellation, since no physical work was scoped out yet. During **Move/Copy**, the file currently being copy-verified finishes normally, then every remaining targeted file is logged to the `operations` audit table with status `Cancelled` (not silently dropped — visible in the run's history afterward) and duplicate-source cleanup for that run is skipped entirely.
* **WebSocket Reconnection & Replay:** On connecting (or reconnecting after a dropped connection or browser refresh — see §5.2), the frontend does **not** assume it saw every event live. It subscribes to the run's live WebSocket stream **first**, buffering events without displaying them. It then queries `GET /api/v1/runs/{run_id}/operations` (backed by `SELECT * FROM operations WHERE run_id = ? ORDER BY id`) to backfill the LOGS panel, merges the buffered events in, discarding any whose operation `id` the backfill already holds, and only then displays the live stream. The order matters: fetching history and then subscribing leaves a window in which an operation lands after the query but before the subscription, and is never shown. So every live event carries its `operations.id`, and ordering is by `id`, not `timestamp` — the single writer assigns ids in commit order, while two operations can share a timestamp. This is what makes "job continues unaffected by a browser refresh" (§5.2) actually true for the *displayed history*, not just the underlying job — without this replay step, a reconnecting client would see progress resume from wherever it currently is with an empty-looking log, even though the job had been running for a while.

### 4.2 Split-Screen Photo Inspector Panel
Clicking an image opens a right-side 50% detail panel.

```
+---------------------------------------------------------------------------------+
| PHOTO DETAIL INSPECTOR                                                      [X] |
+---------------------------------------------------------------------------------+
| [                    IMAGE PREVIEW                    ]                         |
+---------------------------------------------------------------------------------+
| FILE INFORMATION                                                                |
| Path at Destination:  /data/dest/2026/02/14/IMG_0001_1.JPG                      |
| Collision Status:     Renamed on target (Name collision resolved)               |
|                                                                                 |
| Path from Source:     /data/source/sd_card/IMG_0001-1234.JPG                     |
|                                                                                 |
| Timestamps:           Created: 2026-02-14 10:30:00 | Modified: 2026-02-14 10:30:00 |
+---------------------------------------------------------------------------------+
| EXIF & METADATA                                                                 |
| Date Taken: 2026:02:14 10:30:00  | Camera: Canon EOS R5                         |
| ISO: 100   Aperture: f/2.8      | Shutter: 1/1000s                             |
| SHA-1: a4b8c9d123...             | pHash: 1001101...                             |
+---------------------------------------------------------------------------------+
| DISCOVERED DUPLICATES (SOURCE & DESTINATION)                                    |
| * [SOURCE] /data/source/sd_card/IMG_0001-1234.JPG (Completed)                   |
| * [DEST]   /data/dest/2026/02/14/IMG_0001_1.JPG (Completed)                      |
+---------------------------------------------------------------------------------+
```


#### Inspector Data Display Matrix

| Field Category | Source Context View (`/data/source`) | Destination Context View (`/data/dest`) |
| :--- | :--- | :--- |
| **Media Preview** | Rendered preview (standard / RAW via `rawpy`) | Rendered preview |
| **Destination Path** | Target computed path | Assigned destination path (`Path at Destination`) |
| **Source Path** | Current source path | Original source path (`Path from Source`) |
| **Timestamps** | File Created & Modified dates | File Created & Modified dates |
| **EXIF & Hashes** | EXIF metadata, SHA-1, pHash | EXIF metadata, SHA-1, pHash |
| **Duplicates List** | Matching paths across **both** Source & Destination | Matching paths across **both** Source & Destination |

#### 4.2.1 Thumbnail Generation (Media Preview backing)

The Gallery grid and Inspector's "Media Preview" both need something to actually render — this requires new engine-side work, not just a frontend concern, since the engine is the only thing with RAW-decode capability (`rawpy`) already loaded.

* **Generation point:** During Index, alongside SHA1/pHash computation — reuses the image decode already happening for pHash rather than a second pass over the file (standard/HEIC formats via `PIL.Image`, RAW-family via `rawpy`).
* **Storage:** Small JPEG (longest edge ~256px), written to `/appdata/thumbnails/<sha1>.jpg`, keyed by hash so identical files (including cross-directory duplicates) share one thumbnail instead of generating redundant copies.
* **Schema:** New `thumbnail_path` column on `photos` (nullable) — see §6.1.
* **Failure handling:** A thumbnail generation failure (corrupt file, unsupported variant) must not fail the overall Index for that file — log and leave `thumbnail_path` NULL; the Gallery/Inspector show a placeholder icon for those rows instead of erroring.
* **Serving:** `GET /api/v1/photos/{id}/thumbnail` (§6.2) serves the file directly from `/appdata/thumbnails/`.

---

## 5. Safeguards, Operations & Error Handling

### 5.1 Pre-Flight Disk Space Protection
Before initiating any move or copy job, the system computes total payload size plus a 500 MB safety buffer. If destination disk space is insufficient, execution is blocked and a warning banner displays required vs. available space.

### 5.2 Job Persistence & Background Execution
Jobs run asynchronously in FastAPI. If a user closes or refreshes their browser, the job continues unaffected. Reopening the web UI re-establishes the WebSocket connection and replays the operations log for that run (§4.1's WebSocket Reconnection & Replay) to stream live progress with full history intact, not just progress from the reconnection point forward.

### 5.3 Error Center
If operations fail, an Error Banner highlights the failures, sourced directly from the `operations` log's `error_message` column (see §6.1) — the real exception text is persisted, not just a generic "failed" flag.

**Failures belong to attempts, not to a photo's current status.** Query `operations.status = 'Failed'`, joining the photo and run for context; do not filter on `photos.status`. The two deliberately disagree in at least one case: when duplicate cleanup cannot verify that a destination copy still matches the source, it leaves the photo `Duplicate` — correct, since the source is intact and still a duplicate — while recording a `Failed` operation explaining why the deletion did not happen. An Error Center filtering on `photos.status` would show that photo as an ordinary duplicate and never surface the failure, which is the invisibility the recorded operation exists to end.

Some failures have no photo at all. A folder the scan could not read is recorded as a `Failed` operation with `photo_id` NULL and the folder as `source_path` — the photos inside it were never examined, so there is no catalog row to attach to. Left-join `photos` (an inner join drops these), and present such a row as a folder the user needs to fix permissions on, not as a file.

**`Skipped` is an outcome, not a failure.** A run records `Skipped` for a selected photo it deliberately left alone — a duplicate whose original carries its content, or a photo an earlier run already delivered — with a reason naming what holds that content (`Duplicate of photo #N ...`, or `Already copied to <path> by an earlier run`). **The already-copied reason reports what the catalog records, not a fresh check:** that run read and verified nothing, so the UI must not present it as confirmation the destination file is still present and intact. **Do not offer a re-index as the way to find out.** Index walks `--source` and never inspects `--dest`; and since `Copied` is a settled status, the unchanged-file skip means a plain re-Index does not even re-read the source. The row stays `Copied`, the next Copy reports `Skipped` again, and the destination file is still missing — reproduced exactly that way during the final audit. What `--force-rehash` does is re-read sources and reset those rows to `Pending`, so a later Copy delivers the file again: a repair, not a check. The genuine answer to "is the destination still intact?" is the destination inventory (`engine-spec.md` §9.1), which reads the destination; until that exists, the UI should not imply the question can be answered. Show these as informational, grouped apart from failures, and link the named original: a user who selected only the duplicate needs to know which photo to select instead. They exist so that every photo in a selection ends the job with a recorded outcome; a job whose selection held only duplicates used to finish green with nothing recorded at all.

For that case specifically, the recorded `error_message` reads `Duplicate verification failed: ...`, and the underlying cause is worth distinguishing in the UI: a `ChecksumMismatch` means the two files' contents differ, while an `OSError` means one of them could not be read and the comparison never happened. Neither should be presented as "the destination is a verified backup", and neither should suggest deleting anything by hand.

```
+-----------------------------------------------------------------------------------+
| FAILED OPERATIONS (3 Items)                                                       |
+-----------------------------------------------------------------------------------+
| 1. IMG_0488.CR2                                                                    |
|    Source: /data/source/imports/IMG_0488.CR2                                      |
|    Error:  PermissionError: [Errno 13] Permission denied: '/data/dest/...'        |
|                                                                                   |
| 2. IMG_0912.JPG                                                                   |
|    Source: /data/source/corrupted/IMG_0912.JPG                                   |
|    Error:  ChecksumMismatch: SHA-1 verification failed                            |
|                                                                                   |
| 3. IMG_1050.JPG                                                                   |
|    Source: /data/source/sd_card/IMG_1050.JPG                                     |
|    Error:  Source file changed: no longer found at /data/source/sd_card/         |
|            IMG_1050.JPG. It may have been moved, renamed, or deleted outside      |
|            NegativeSpace since the last Index.                                       |
+-----------------------------------------------------------------------------------+
```

Users can view exact system error strings (e.g., `PermissionError`, `ChecksumMismatch`, `Source file changed`). The distinct wording on the third case (`engine-spec.md` §4.2) is intentional — it should read differently from a permissions/disk failure, since the fix is "run an Index" rather than "check destination permissions."

**No dedicated retry subsystem.** There is no "Retry Item" / "Retry All Failed" backend endpoint and no `retry_count` tracking. A failed file's `photos.status` is reset to `Pending` automatically the next time it's re-indexed (a plain re-scan, full or `--file-ids`-scoped), so retrying is just re-running the same operation — files that already succeeded are gone from `--source` and won't be touched again, so this is fast even for a large batch with only a few failures. The web UI's equivalent of "retry" is selecting the photos associated with failed attempts and re-issuing the same Move/Copy operation via `POST /api/v1/jobs/start` with their IDs in `file_ids` — no new endpoint required. Take those IDs from the failed `operations` rows rather than from `photos.status`, deduplicating when several attempts reference one photo, and do not require the photo's current status to be `Failed`: a duplicate-verification failure stays `Duplicate` and is retried by Move's duplicate cleanup on the next run. Retrying does not by itself fix a content mismatch or an unreadable file, so the UI should not promise that it will.

### 5.4 Operations Audit Log (`/logs`)
A searchable table logging every operation performed by the engine:
* **Columns:** Timestamp, Mode (`MOVE`/`COPY`), Source Path, Destination Path, Status (`Completed`, `Copied`, `Removed_Duplicate`, `Failed`), and System Error Message.
* **Controls:** Filter by date, status, run, or free-text search; CSV/JSON export.

**Filtering by run is what two other screens link into**, so it is a first-class filter rather than a search convenience: the failure banner links here scoped to the most recent run, and the Dashboard's coverage message (§5.9) links here scoped to *every run since the last complete scan*. The filter therefore accepts a set of run ids, not only one.

### 5.5 Job Outcome Is Derived, Not Read From `runs.status`

**`runs.status` describes the run's lifecycle, not whether the work succeeded.** A run that reaches the end of its file loop is recorded `Completed` even if every single file in it failed. That is accurate for what the column means — the process ran to completion rather than crashing, being cancelled, or aborting on a pre-flight check — but it is the wrong thing to put in front of a user on its own.

Observed in practice: a `--move` against a source mounted `:ro` fails every file (the copy succeeds, only the source deletion fails) and still reports:

```
Run #2 finished with status: Completed
```

Surfacing that verbatim would show a green **Completed** for a job where nothing succeeded, and the user would have to open the Error Center to discover their entire operation did nothing.

**The API therefore derives a job outcome from the `operations` rows rather than echoing `runs.status`:**

```sql
SELECT status, COUNT(*) FROM operations WHERE run_id = ? GROUP BY status;
```

The per-file truth is already recorded there — `Completed`, `Copied`, `Failed`, `Cancelled`, `Removed_Duplicate`, each with an `error_message` where applicable — so no engine change and no new status vocabulary is required. `runs.status` keeps its current meaning and remains the right thing to check for "is a job still running" (§5.7) and for crash reconciliation.

Job responses should carry both: the lifecycle status **and** the derived counts, so the UI can render *"Move finished — 0 of 23 succeeded, 23 failed"* rather than a bare word. Recommended presentation rules:

| condition | display |
|---|---|
| `runs.status` is `Running` | in progress, with live counts |
| succeeded > 0, failed = 0 | success |
| succeeded > 0, failed > 0 | partial success — surface the failed count and link the Error Center |
| succeeded = 0, failed > 0 | **failure**, regardless of `runs.status` being `Completed` |
| `runs.status` is `Cancelled` / `Crashed` / `Failed` | that status wins; still show counts for what was done before it ended |

Note the engine may write more `operations` rows than the job targeted — the scan phase logs a row per file and the move phase logs another, and a `--move` additionally logs `Removed_Duplicate` cleanup rows. Count against the operation the user asked for rather than assuming one row per file.

---

### 5.6 Engine Invocation as a Trust Boundary

Because the engine's flags are now assembled by FastAPI from HTTP request bodies rather than typed by someone with shell access, argument construction is a **security boundary**, not a convenience. Three rules follow:

* **Build the command as an argument list, never a shell string.** Use `subprocess.Popen([...])` / `subprocess.run([...])` without `shell=True`. Interpolating a user-supplied `source_subdir` into a shell command would be command injection reachable directly from an HTTP request — this is the single most damaging mistake available in this layer.
* **`--source-subdir` carries user-chosen input** from the folder picker and is the most exposed parameter. The engine already resolves it and rejects anything escaping `--source` via `..` — that check is load-bearing once the API constructs arguments, and must not be removed as a redundant-looking sanity check. FastAPI should validate independently rather than relying solely on the engine; defense in depth is the point, and the API can return a clean `400` instead of a failed job.
* **`--exts` is the subject of the validation feature in §3.2.** The engine normalizes the leading dot and casing but does not otherwise constrain the value, so the API owns deciding which extensions are acceptable. Scope is limited to the mounted source directory, so the risk is indexing unintended file types rather than reading outside the volume — but a user-facing field still needs a server-side allowlist, not just client-side checks.

Note also the `--file-ids` length ceiling described in §2: the 1,000-item selection cap is a real OS command-line limit, and enforcing it is the API's responsibility. Folder selections use `--source-subdir` precisely to sidestep it.

---

### 5.7 Single Active Job Enforcement

Only one engine process may run at a time — see `engine-spec.md` §4.1/§7 for the engine-level guarantee (an OS-level `flock`, held for the whole process lifetime, released automatically even on a hard `SIGKILL`). This is enforced in two layers, not one:

* **Fast pre-check (FastAPI):** Before spawning the engine, `POST /api/v1/jobs/start` probes the engine's own lock: a non-blocking `flock` on `<base>/engine.lock`. If the lock is held, an engine is running, and it returns `409 Conflict` immediately — no subprocess is spawned, and the response includes the newest `Running` run's `id`, `mode`, and `started_at` so the frontend can show *"A Move operation is already in progress (started 2 minutes ago) — wait for it to finish or cancel it."* The Rescan/Move/Copy/Settings-Save buttons should all be disabled client-side whenever a job is known to be active, so this 409 is a backstop for races (e.g. two tabs), not the primary UX.

  The pre-check must not decide from `runs.status = 'Running'` alone. A row orphaned by a crash stays `Running` until the next engine run reconciles it, so a pre-check that trusted the table would refuse to start that very run: every job blocked, permanently, by a process that no longer exists. If the probe *acquires* the lock, any `Running` rows are stale; settle them as in the restart case below before releasing the probe and spawning. Two requests can still race between the probe's release and the engine's own acquisition. The engine's lock decides, and the losing engine exits non-zero with its FATAL message, which the API reports as a 409.
* **Authoritative guarantee (engine):** The `flock` in `engine-spec.md` §4.1 is what actually prevents data corruption if the fast check above is ever wrong or stale — see the FastAPI-restart case below. Even if FastAPI's own bookkeeping says "nothing running" incorrectly, a second engine process attempting to start will still be refused by the lock and exit cleanly with a logged error, never silently racing a real in-progress run.

**FastAPI-restart edge case:** if FastAPI itself restarts (redeploy, crash) while a job is running, its in-memory job/WebSocket-subscriber state is lost, but the engine subprocess is *not* killed by its parent dying — it keeps running under the protection of its own lock. On startup, FastAPI should reconcile this by querying `runs` for any `status = 'Running'` row. Two cases:
1. **The engine process is genuinely still alive** (the common case) — FastAPI should treat this as an active job for UI purposes (allow reconnecting clients to replay/stream it per §4.1) without being able to directly re-attach to the subprocess's stdout; the `operations` log is what makes this possible without that direct attachment.
2. **The engine process crashed too, before its own next-run reconciliation ever got a chance to mark that row `Crashed`** (`engine-spec.md` §4.2) — this is a double-failure case (both the engine and FastAPI went down around the same time) that would otherwise leave a phantom `Running` row until someone happens to run the engine again. FastAPI can distinguish the two cases on its own startup by attempting a **non-blocking `flock` on the same lock file as a liveness probe** — if it succeeds (nothing holds the lock), no engine process owns any `Running` row. **While still holding the probe lock**, FastAPI records the IDs of the `Running` rows it found, marks exactly those `Crashed`, and only then releases the probe, rather than waiting for a future engine invocation to notice. Releasing first would let a new engine start in between and create its own `Running` row, which a blanket `UPDATE ... WHERE status = 'Running'` would then mark `Crashed` while it runs.

### 5.8 Index Is a Precondition for Move and Copy

Move and Copy act on the catalog, never on the filesystem directly. Both targeting mechanisms — `--file-ids` and `--source-subdir` — resolve rows a previous Index recorded; neither walks the source tree. A Move or Copy issued against a source that has never been indexed therefore matches zero rows and does nothing.

The engine reports this rather than hiding it: each targeting mode logs a warning naming the cause and the remedy when it matches nothing. But the engine can only explain the situation *after* the user has already waited for a job that was never going to do anything, and it deliberately does not treat an empty selection as an error — "nothing left to do" is the correct outcome for a re-run, and failing would break idempotency.

Preventing the situation is the UI's job:

* **The folder picker can only offer indexed folders.** Its tree should be built from `SELECT DISTINCT` over indexed `source_path` prefixes, not from a filesystem listing. A folder the user cannot select is a folder they cannot mis-target. This also matches what the user is choosing between — they are picking from photos the app knows about, not browsing a disk.
* **Move and Copy are disabled while the catalog is empty**, with the control labelled to say why (*"Run a Scan first — NegativeSpace acts on indexed photos"*) rather than being inert with no explanation. `SELECT COUNT(*) FROM photos` is sufficient to drive this.
* **A newly added source directory is not silently actionable.** A source the user has just configured has no rows until a Scan completes over it. The Settings flow that adds a source should offer to run that Scan immediately, so the common path never produces an un-indexed source.
* **Stale scope is surfaced, not assumed.** `--source-subdir` sees only rows as of the last Index over that path, so files added to a folder since then are invisible to a Move or Copy targeting it. Where the UI shows a folder's file count, it should show when that folder was last scanned alongside it, so a user comparing "1,318 photos" against what they see in their file manager can tell the difference between a bug and a stale index.

The general principle: the engine guarantees it will never act on something it has not catalogued, and says so when a selection resolves to nothing. The UI is responsible for making an empty selection hard to construct in the first place.

### 5.9 Duplicate Space: Reclaimable, Reclaimed, and Saved

"How much space are my duplicates wasting?" is a headline figure for the Dashboard, and the catalog already answers it without any engine change. Deduplication acts on two different volumes, though, and conflating them produces a number that is wrong in whichever direction the user's mode does not apply:

| Figure | Where | Realized by |
| :--- | :--- | :--- |
| **Reclaimable** — duplicate sources still on disk | Source | `--move` only |
| **Reclaimed** — duplicate sources already deleted | Source | Past `--move` runs |
| **Saved** — duplicate copies never written | Destination | `--move` *and* `--copy` |

**These are not addends.** A Move both deletes a duplicate source and declines to write it to the destination, so the same bytes appear under *Reclaimed* and under *Saved*. Summing them into one "total saved" double-counts every moved duplicate. Show them as separate figures, each labelled with the volume it refers to.

#### Reclaimable at the source

**The waste is every copy beyond the one that is kept, not the whole group.** Three copies of one photo waste two copies' worth of bytes; the third is the photo itself, which the user is keeping. Deduplication already encodes exactly that split: among rows sharing a `sha1_hash`, one is the anchor (`Pending`, or `Copied`/`Completed` once delivered) and every other is `Duplicate`. So the figure is a single aggregate over the rows that are *not* anchors:

```sql
SELECT COUNT(*)                  AS duplicate_files,
       COUNT(DISTINCT sha1_hash) AS duplicate_groups,
       COALESCE(SUM(file_size), 0) AS reclaimable_bytes
FROM photos WHERE status = 'Duplicate';
```

No `GROUP BY`, no "subtract one per group" arithmetic, and no risk of the off-by-one that counting whole groups invites. `idx_photos_status` backs it, so it stays a cheap query on a large catalog.

**Call it reclaimable, not wasted, and say what reclaims it.** A `Duplicate` row means the redundant source file is still on disk. Only `--move` deletes those (duplicate cleanup, after verifying a destination copy still matches live); `--copy` deliberately removes nothing and records `Skipped` for them, per §5.3. A Dashboard tile reading *"3,028 duplicate files across 1,510 photos — 6.4 GB reclaimable by Move"* is honest about both the number and the action that realizes it. Phrasing it as space the app will "save" invites the user to expect Copy to free it.

**Four things not to fold into the figure:**

* **`Removed_Duplicate` is already reclaimed**, not reclaimable. Those source files are gone, so they are the *Reclaimed* figure — history rather than an opportunity — and adding them here double-counts. They also count toward the destination saving below, which is a different volume, not a second helping of the same one.
* **No destination deletion is implied.** The engine never deletes anything under `--dest`. Redundancy that something outside the engine put there is reported by the destination inventory (`engine-spec.md` §9.1), not resolved by it. This figure covers source files the engine can remove; what deduplication saves at the destination is the separate figure below.
* **`Failed` rows are not duplicates.** A source that vanished outside NegativeSpace is marked `Failed` at the next full Index, which removes it from its duplicate group and lets a surviving copy be promoted to anchor. It therefore drops out of this figure automatically — correct, since deleting a file that no longer exists reclaims nothing.
* **Sizes are as of the last scan.** `file_size` is recorded by the Index that wrote the row (§6.1), so the total is as current as the catalog. Show it alongside the last scan time, as §5.8 asks of folder counts, so a stale figure reads as stale rather than as wrong — and see the coverage rule below, because "the last scan" must mean the last scan that actually established coverage.

**Coverage: show the last trustworthy date, and say what happened since.** *(Decided 2026-09-20, closing audit 011's F3.)* The date beside these figures is the most recent Index that completed **and recorded no run-level failure**. An Index that was refused or could not read part of the tree keeps its own date out of this figure — but it is not hidden either. The tile reads:

> *Last complete scan: 14 Feb, 10:30 — 2 later scans had issues.*

The second clause is a link into Logs (§5.4), scoped to every run since that scan, so the user can see exactly what is unaccounted for rather than taking the count on trust. When no Index has ever established coverage, say "not fully scanned" and link the same way; never show a reassuring date the runs do not support.

#### Space saved at the destination

The figures above are about the source tree, which is why only Move realizes them. **Deduplication's benefit to `--copy` is entirely at the destination:** a duplicate is never written there, so the destination holds one copy of each distinct photo instead of N. That saving is real in both modes, and it is the *only* one a Copy user gets.

A duplicate has saved destination space once its content has actually been delivered — that is, once some other row in its group is `Copied` or `Completed`:

```sql
SELECT COUNT(*)                      AS copies_not_written,
       COALESCE(SUM(d.file_size), 0) AS bytes_not_written
FROM photos d
WHERE d.status IN ('Duplicate', 'Removed_Duplicate')
  AND EXISTS (SELECT 1 FROM photos a
              WHERE a.sha1_hash = d.sha1_hash AND a.id != d.id
                AND a.status IN ('Copied', 'Completed'));
```

Both statuses count, because neither was ever written to the destination: a `Duplicate` still sits in the source, a `Removed_Duplicate` has been deleted from it, and in both cases the destination holds one copy rather than two. The `EXISTS` clause is what makes this *saved* rather than *savable* — a duplicate whose original has not been delivered yet has saved nothing so far, and belongs in the reclaimable figure instead.

What this is not: re-running a Copy does not write files it already delivered (§2's content-aware skip), but that is idempotency, not deduplication. Those rows are the anchors themselves, and the query excludes them by construction. Redundancy that something outside the engine put in the destination is a different question again, answered by the destination inventory (`engine-spec.md` §9.1), not here.

The Inspector's `duplicates` array (§6.2, `GET /api/v1/photos/{id}/inspect`) should carry each copy's `file_size` for the same reason, so a single photo's panel can show what removing its duplicates would reclaim.

---

## 6. Database Schema & API Specifications

### 6.1 SQLite Schema

**There is no in-place upgrade path and none should be added.** Migration code runs rarely, on real user data, along a path that is almost never exercised. When the schema changes, the catalog is deleted and rebuilt by an Index — every value in it is derived from the source files.

While the schema is still changing pre-release, that is a convention rather than an enforced rule: the engine does not stamp `PRAGMA user_version` and does not refuse a catalog written by older code, since a stamp nobody reliably bumps misleads rather than protects. Before the first release, a stamp and a startup refusal should be added together, against catalogs created fresh at that point. The API layer should not assume either exists today.

**Only `photos` is derived. `runs` and `operations` are not, and rebuilding discards them.** Every value in `photos` is recomputable by re-running an Index over the same sources — verified by rebuilding a ~29,000-file catalog from scratch and getting identical per-status counts. Nothing recomputes the audit log: it records what the engine *did*, and re-scanning the filesystem cannot reconstruct it. The sharpest case is `Removed_Duplicate`, where after a `--move` that row is the only evidence the file ever existed — its source was deleted by design and its content survives only under the anchor's name.

**How history should be keyed is still an open question, and this section is where it bites.** `operations.photo_id` hangs off `photos.id`, so a rebuild orphans every historical row — the alternatives (keying on `sha1_hash`, or moving `runs`/`operations` into a store that is never discarded) are set out in `engine-spec.md` §10 along with the three problems each has to answer. It is raised here because §5.3's Error Center and §5.4's audit log are both specified on these tables: **the question wants answering before that UI is built**, at which point it becomes a migration and a rework rather than a schema choice. It does not block writing the rest of this spec.

The practical consequence for the UI: rebuilding is cheap and safe for a catalog that has only been Indexed or Copied, and lossy for one that has been Moved against. Before offering a rebuild, check whether any `Removed_Duplicate` rows exist and say what will be lost. Offer a backup first — `sqlite3 <db> ".backup '<path>'"` is atomic under WAL where a file copy is not — and treat a JSON export of `runs` and `operations` as the format for reading history outside the app or carrying it across a schema change, not as a substitute for the database backup.

**Status values are enforced by the database, not by convention.** Each `status` column carries a `CHECK` constraint listing exactly its vocabulary, generated from the same tuples the engine uses. An API write of `'copied'` or a filter on `'Complete'` fails loudly at write time rather than silently disagreeing with the engine — a mismatch whose only symptom would otherwise be photos that never appear. Treat the constraint as the contract and do not hardcode a parallel list; read it from the engine's constants or from `sqlite_master` if the API needs to enumerate.

**The API layer should not create or alter the schema.** It opens a database the engine owns. There is no schema version to check against pre-release (see §6.1 above), so it cannot verify the shape it is about to query; it should fail clearly on the first query that does not match what it expects, rather than half-rendering a catalog it does not understand.

**What it must not tell the user is "run a Scan to rebuild the catalog" — that cannot repair a wrong schema.** All three tables are created with `CREATE TABLE IF NOT EXISTS`, and the engine has no `ALTER TABLE`, no `DROP`, and no shape check anywhere: an Index over an existing catalog with the wrong columns sees the tables already present and leaves them exactly as they are. The repair is to **delete the catalog file and then Index** — that is the whole of it, and it is cheap, since every value in `photos` is derived. *An earlier draft of this line prescribed the Scan; it would have sent a user round a loop that changes nothing — corrected 2026-09-20.* Once the engine stamps a version again, this becomes a startup check instead. Two writers disagreeing about schema on the same file is exactly what the single-instance lock exists to prevent.

Note the asymmetry this creates for the UI: deleting the catalog is cheap for Index state, but it discards the record of which files a previous Move already migrated. Where the UI offers a rebuild, it should say so.

**The authoritative schema definition lives in `engine-spec.md` §6.5**, executable
as written. It is not duplicated here: the engine owns the catalog, creates it,
and is the only writer, so a second copy in this document would be a copy that
drifts. What this section carries instead is what the reading layer must know in
order to consume it safely — the rules above, and the two below.

**The `settings` table is the API layer's own**, not the engine's. The engine
never reads it; the API persists UI-managed configuration there and passes the
values as CLI flags at spawn time (§3). Its definition is in `engine-spec.md`
§6.5 alongside the rest, so one file describes everything in the database file.

**`thumbnail_path` does not exist yet.** The Gallery and Inspector need it
(§4.2.1), and adding it is a schema change — a rebuilt catalog, not an `ALTER`
on a live database.


### 6.2 Key REST API Endpoints
POST /api/v1/settings/validate-extension

Validates whether a provided file extension supports EXIF metadata.

    Request Body:
    JSON

    {
      "extension": ".mp4"
    }

    Response:
    JSON

    {
      "extension": ".mp4",
      "supports_exif": false,
      "warning": "File type '.mp4' does not support EXIF data. When no EXIF data is available, file creation/modification date will be used."
    }

GET /api/v1/settings

Retrieves persisted system settings along with EXIF support status for each configured extension.

    Response:
    JSON

    {
      "max_worker_processes": 8,
      "supported_extensions": [
        { "ext": ".jpg", "supports_exif": true },
        { "ext": ".cr2", "supports_exif": true },
        { "ext": ".png", "supports_exif": false, "warning": "File type '.png' does not support EXIF data. When no EXIF data is available, file creation/modification date will be used." }
      ]
    }

PUT /api/v1/settings

Updates global engine settings.

    Body:
    JSON

    {
      "max_worker_processes": 8,
      "supported_extensions": [".jpg", ".cr2", ".png"]
    }

POST /api/v1/jobs/start

Starts an engine execution job, automatically injecting active configuration parameters from /settings if not explicitly overridden. `file_ids` and `source_subdir` are mutually exclusive — provide one or neither (a full directory scan), never both. Returns `409 Conflict` if another job is already running (§5.7) instead of spawning a doomed subprocess.

    Body (individual selection):
    JSON

    {
      "mode": "move",
      "file_ids": [101, 102, 105]
    }

    Body (folder selection):
    JSON

    {
      "mode": "move",
      "source_subdir": "sd_card/day1"
    }

    409 Response (another job already active):
    JSON

    {
      "error": "job_already_running",
      "active_run": { "id": 47, "mode": "MOVE", "started_at": "2026-02-14T10:28:03Z" }
    }

GET /api/v1/runs/{run_id}/operations

Returns the full `operations` history for a run (`SELECT * FROM operations WHERE run_id = ? ORDER BY id`). Used for the reconnect replay in §4.1/§5.2 — always called *after* subscribing to the run's live WebSocket stream, with live events buffered and deduplicated by `id`, and not just after a detected disconnect, so the log is complete regardless of when the client first connected.

GET /api/v1/runs/{run_id}

Returns a run with its **derived** outcome (§5.5). `status` is the engine's lifecycle value and `outcome` is computed from the `operations` rows — never render `status` alone, since a run where every file failed still reports `Completed`.

    Response:
    JSON

    {
      "id": 47,
      "mode": "MOVE",
      "status": "Completed",
      "started_at": "2026-02-14T10:28:03Z",
      "ended_at": "2026-02-14T10:31:11Z",
      "targeting": { "source_subdir": "sd_card/day1" },
      "outcome": {
        "verdict": "failed",
        "succeeded": 0,
        "failed": 23,
        "cancelled": 0,
        "removed_duplicates": 0,
        "summary": "0 of 23 succeeded"
      }
    }

`verdict` is one of `success`, `partial`, `failed`, `cancelled`, `crashed`, `running`, resolved by the rules in §5.5. `targeting` echoes the decoded `runs.file_ids_filter` object (§6.1) so the UI can show what the job was scoped to.

POST /api/v1/jobs/{id}/cancel

Sends SIGTERM to the engine subprocess for graceful job cancellation — the currently in-flight file finishes, every remaining targeted file is logged to `operations` with status `Cancelled`, and duplicate-source cleanup is skipped for that run.

GET /api/v1/photos/{id}/thumbnail

Serves the thumbnail JPEG for a photo (see §4.2.1), read from `/appdata/thumbnails/<sha1>.jpg` via the row's `thumbnail_path`. Returns a placeholder/404 if `thumbnail_path` is NULL.

GET /api/v1/photos/{id}/inspect

Returns inspector details for a specific photo.

    Response:
    JSON

    {
      "id": 502,
      "status": "Completed",
      "source_info": {
        "path": "/data/source/sd_card/IMG_0001-1234.JPG"
      },
      "destination_info": {
        "path": "/data/dest/2026/02/14/IMG_0001_1.JPG",
        "has_collision_rename": true
      },
      "timestamps": { 
        "created": "2026-02-14T10:30:00Z", 
        "modified": "2026-02-14T10:30:00Z" 
      },
      "exif": { 
        "date_taken": "2026-02-14T10:30:00Z", 
        "camera": "Canon EOS R5" 
      },
      "hashes": { 
        "sha1": "a4b8c9...", 
        "phash": "1001101..." 
      },
      "duplicates": [
        { "location_type": "source", "path": "/data/source/sd_card/IMG_0001-1234.JPG", "status": "Completed" },
        { "location_type": "destination", "path": "/data/dest/2026/02/14/IMG_0001_1.JPG", "status": "Completed" }
      ]
    }

GET /api/v1/operations?status=Failed

Fetches failed attempts for the Error Center (§5.3), filtering on `operations.status`. Returns the operation ID, photo ID (nullable), run ID, timestamp, source and destination paths, status, error message, and the associated photo's current status as a separate field — the two are not interchangeable, per §5.3. Left-join the photo so a missing row cannot hide a failure. Supports run and date filters with stable ordering for pagination.

GET /api/v1/stats/duplicates

Backs the Dashboard's duplicate-space tiles (§5.9). Three separate figures, each naming the volume it applies to: what Move could still reclaim from the source, what past Moves already reclaimed from it, and what was never written to the destination in either mode. They overlap by design — a moved duplicate appears in both `already_reclaimed` and `saved_at_destination` — so the API returns them separately and the UI must not total them. `last_indexed_at` is the most recent **full Index** covering the source roots the figures span — `mode = 'INDEX'` with no targeting filter — that both **completed** and **recorded no run-level failure**. Not simply the most recent completed run: a one-file targeted Copy is a completed run, and taking its timestamp would stamp the whole catalog as freshly scanned on the strength of a run that examined one photo.

**Completing is not the same as covering, which is what audit 011's F3 caught.** An Index whose source was detached finds nothing, correctly refuses to condemn the catalog, records a run-level `Failed` operation — and still ends `Completed`, `mode = 'INDEX'`, untargeted. It satisfies every criterion above except the one that matters, having established no new coverage at all. An Index that could not read part of the tree has the same shape. **The safeguard works and then misreports its own freshness**, which is the defect.

So a run advances the coverage date only if nothing under it recorded a failure belonging to the run rather than to a photo:

```sql
-- the coverage-establishing run
SELECT r.id, r.ended_at FROM runs r
WHERE r.mode = 'INDEX' AND r.file_ids_filter IS NULL
  AND r.status = 'Completed'
  AND NOT EXISTS (SELECT 1 FROM operations o
                  WHERE o.run_id = r.id AND o.photo_id IS NULL
                    AND o.status = 'Failed')
ORDER BY r.ended_at DESC LIMIT 1;
```

`photo_id IS NULL AND status = 'Failed'` is precisely the run-level failure shape already written by the empty-scan refusal and by an unreadable folder (§5.3), so **no engine change and no new column is required** — `idx_operations_run` backs the lookup.

**Return the excluded runs, not just the date.** Suppressing a scan silently would trade a wrong date for a missing one. Alongside `last_indexed_at`, report how many Index runs since then failed to establish coverage, and the run ids the UI needs to link into Logs (§5.4):

* `coverage.established_by_run` — the run the date came from, or `null`
* `coverage.scans_with_issues_since` — count of untargeted Index runs after it that recorded a run-level failure. Deliberately **Index runs only**: a failed Move says nothing about scan coverage, and the failure banner already covers that case. Conflating them would make a delivery problem read as a staleness problem.
* `coverage.run_ids_since` — every run after that date, whatever its mode, since the user clicking through wants to see the whole gap rather than only its failures.

**Accepted limitation: extension scope is not recorded.** An Index run with a narrowed `--exts` scans the full tree, succeeds completely at a smaller job, and records no failure — so it advances the coverage date while having examined only some file types. `runs` stores `mode`, `source_path`, `dest_path` and `file_ids_filter`, but not the effective extension set, so nothing downstream can detect this. F3 raised it; closing it needs an `exts` column on `runs`, which is deliberately deferred rather than overlooked. Until then the coverage date means "every supported type the run was configured to look at", not "every supported type".

    Response:
    JSON

    {
      "reclaimable_at_source": {
        "duplicate_files": 3028,
        "duplicate_groups": 1510,
        "bytes": 6871947673
      },
      "already_reclaimed_at_source": {
        "removed_duplicates": 12,
        "bytes": 41943040
      },
      "saved_at_destination": {
        "copies_not_written": 3040,
        "bytes": 6913890713
      },
      "last_indexed_at": "2026-02-14T10:30:00Z",
      "coverage": {
        "established_by_run": 47,
        "scans_with_issues_since": 2,
        "run_ids_since": [48, 49, 51]
      }
    }

`GET /api/v1/photos?status=Failed` remains available for filtering the catalog, but it is not the Error Center's data source: it misses any failure whose photo is not currently `Failed`. "Retrying" is selecting the associated photo IDs and calling `POST /api/v1/jobs/start` again with the same mode — no separate retry endpoint, per the design note in §5.3.

---

## 7. Destination Curation & Similar-Photo Review

Everything above is about getting files *in*. This section is about curating
what is already there — a different activity, with a different safety story.

**Every workflow here depends on engine capabilities that do not exist yet**
(`engine-spec.md` §9): the destination inventory, the perceptual pair table,
renaming a delivered file, deleting under `--dest`, and writing EXIF. This
section specifies what the user does; that one specifies what the engine must be
able to do first.

### 7.1 The shape every review screen shares

Building the second and third screen of this shape should be nearly free, so the
shape is stated once.

* **A review queue is framed as "photos that *have* X", never "photos that
  *need* X".** Leaving a row untouched records nothing and is not a pending
  action, and no badge implies a backlog. The engine does not know which choice
  is right and must not imply that it does.
* **Clicking a picture expands it** into a detail panel — larger image, detail
  box beside it — with the list still navigable behind.
* **Two controls on every list: a sort selector and a search box**, behaving
  identically wherever they appear. Each screen sets its own *default* sort;
  the options and the interaction are shared.
* **Actions take effect when confirmed.** No staged batches, no apply step, no
  pending-changes indicator. Each action is independently reversible from the
  `operations` row that recorded it. Bulk metadata apply (§7.5) is the one
  deliberate exception, because there the batch *is* the feature.
* **A failed action leaves its row in place with the reason attached, and the
  file untouched.** Failures are `operations` rows, which is what the Logs page
  (§5.4) reads when filtered to failures.
* **Edit controls sit with the value they edit** — beside displayed EXIF, beside
  a displayed filename or path — so the user never leaves to find the same field
  elsewhere.
* **Controls appear only on delivered photos.** A photo that has merely been
  indexed shows the same values with *no controls at all* — absent rather than
  greyed out, since a disabled button invites a hunt for the permission that
  would enable it when the real answer is "organize this photo first". The test
  is the engine's delivered-status set.
* **Navigation preserves your place.** Following a link into the Similar tab or
  a detail view and coming back returns the user where they were, not to the
  top. This is what makes "just check this one thing" cheap on a list of
  thousands rather than a punishment for curiosity.
* **Expand all and collapse all act on every level of nesting**, not merely the
  outermost. Half-collapsing a nested structure leaves the user clicking through
  the rest by hand, which is the state the control existed to avoid.

**Tab or filter?** A population that comes with its own job to do gets a tab; a
population that is merely a subset of an existing view, with no action that view
lacks, gets a filter. The Rename, Similar and Undated tabs each have a distinct
task — choose a better name, resolve a near-duplicate group, recover a missing
date — so each is a tab. A "failed operations" screen is *not* a tab: it is Logs
filtered to failures and introduces no action Logs lacks.

### 7.2 Exact duplicates and similar photos are different things

A match-mode control distinguishes them, and the UI must not blur them:

* **Exact (SHA-1).** Byte-for-byte identical. Available as soon as an Index has
  run, with no new engine work.
* **Similar (perceptual).** Visually alike but different bytes — the same
  photograph as RAW and JPEG, or full-size and thumbnail. Requires the pair
  table in `engine-spec.md` §9.3, which does not exist.

**Every photo's info box states its exact-duplicate count and carries a "find
similar photos" link** scoped to it.

**The count must say whether they have been dealt with.** On a catalog that has
only been indexed, the duplicates are flagged but still on disk; a bare number
reads as "handled" when nothing has been. After a Move they are gone from the
source and the count is history rather than a pending task. Say which.

### 7.3 The Rename tab

When duplicates collapse to one file, the survivor may carry the least useful
name in its group — a camera-style serial name can survive while the copy
removed against it carried the descriptive name a person actually chose. The
name held the information. This is a presentation problem, not an engine one:
the alternatives are already catalogued on the `Duplicate`/`Removed_Duplicate`
rows and on every `operations` row, groupable by `sha1_hash`.

* Lists delivered photos whose duplicate group holds a different filename stem.
* Default sort **most duplicates first**; also sortable by date taken, filename,
  destination folder, file size, and most recently moved.
* Each row shows a framed picture with the group's full paths and filenames
  beside or beneath it, whichever reads better at width.
* A **Rename destination file** control sits in the path list.

**Workflow.** Pick any filename from the group **or type one**. A typed name
validates live against the destination folder, so a collision is caught before
the control becomes available rather than after committing — note this is a
*filesystem* read, not a catalog query, since the catalog does not know about
files it never wrote. Confirm immediately. The write is no-overwrite with the
`_N` suffix rule, `photos.dest_path` is updated, and an `operations` row records
**both** old and new path — which is what makes undo simply the same write in
reverse.

**Choosing the name at move time is a different feature, and is deferred.** It
would decide the name as the file is written, but it is an engine change and it
asks for naming decisions before the library is organized.

### 7.4 The Similar tab

The same shape as the Rename tab, with four differences:

* **A match % slider at the top**, so the user sets what counts as similar.
* **Moving the slider clears the current selection, after warning that it
  will.** The division of labour is the point: *the slider filters what is
  offered; the selection is what is acted on.* Clearing on movement makes it
  impossible for an action to reach a photo the user has stopped looking at.
* **The photo with the most matches is listed first.**
* **Each member shows its dimensions, and the largest in the group is marked —
  as information only.** Nothing is pre-selected on that basis; we do not assume
  the user wants to keep the highest resolution.

**One explicit primary per group drives both actions.** The group has a single
designated primary, chosen deliberately rather than inferred from what was
clicked last, and that one designation serves both verbs: **copy EXIF** from the
primary onto the selected targets, and **discard** — keep the primary, delete
the selected targets. One concept, two actions, rather than two mental models.
No action is armed until a primary exists, and the primary is visually distinct
— a border and a label, not merely focus.

**The primary is swappable via "Make Primary".** Any photo in the group can be
promoted; the previous primary demotes back into the group. In practice you do
not know which photo should win until you have compared several, and a primary
fixed at the moment you opened the group would make an accident of navigation
feel like a decision. Its real consequence: **the photo you originally clicked
becomes deletable**, losing a protection nobody chose to give it.

**Select all exists, and is always guarded.** Deleting twenty-nine of thirty by
hand is not a workflow. But a select-all never acts directly — it raises a
cancellable confirmation that **states the number of files and names the
consequence**:

> *Delete 400 photos? This cannot be undone. If you do not have a backup of
> these photos, this will lead to data loss.*

The count carries the warning. "Are you sure?" is noise a user learns to
dismiss; "400 photos" is what stops someone who meant to select four.

**Discarding deletes.** It does not quarantine — see `engine-spec.md` §9.5 for
the reasoning and for the unusually complete record that deletion writes. Where
the catalog knows whether a source copy still survives, say so: that is what
lets the warning give a real number instead of a generic caution.

### 7.5 Editing metadata

**This is the feature that makes the engine modify a photo file.** Everything
else copies, verifies and deletes *sources*; nothing has ever altered content.

Three shapes of one operation, differing only in where the value comes from and
how many targets it lands on: a date the user types for a single photo with no
EXIF; a donor photo's metadata applied across a similar group; one correct date
applied to hundreds of scans that all carry a scanner's wrong date.

* **Single-photo mode is a plain form** — no columns, no donor selection, no
  comparison furniture. A photo with nothing to compare against must not be made
  to feel like it does. Comparison is what the screen does when there *is*
  something to compare; it is not the premise of editing.
* **Comparison mode** gives each photo a column with fields aligned in rows,
  differences and gaps marked. Each column also shows its preview, filename,
  current location, and recorded original names and paths — historical paths
  labelled as such, never implying a file still exists there.
* **Copy chosen fields from another column** via a checkbox per field with
  Select All, offering only the fields that donor actually holds. Clearing a
  field is a separate action from copying. Donor and targets must be visually
  distinct.
* **Bulk acts on the explicit selection only**, never on "everything currently
  visible".
* **A preview before committing** states the count plainly — *"apply to 47
  photos"* — and which fields change from what to what.

**Workflow.** Select, enter a value or pick a donor and fields, review the
preview, confirm. Then, before anything is written, **the catalog is backed up**
automatically — silent, fast, no confirmation asked. Each file is written
atomically, verified, and the per-file safety copy discarded.

**Verify means two checks:** read the written metadata back to confirm it took,
then decode the file and compare its perceptual hash against the one recorded at
Index. The decode succeeding proves the file still opens; the hash matching
proves the image survived. A pHash is invariant under metadata editing, so the
stored value stays valid as the before-value however many edits occur — which is
what makes this one decode rather than two.

**A changed date refiles the photo** to the folder its new date implies,
automatically and with no setting to disable it. Correcting the date *is* the
decision; moving the file is only that decision applied consistently, so a
prompt would ask the user to confirm the same choice twice. It is not a guess —
the correct folder is computed, not judged. And sorting photos into date folders
is what this tool does: if its own output disagrees with the metadata it used to
build that output, the product contradicts itself. Finding the file afterwards
is the log's job, since a refile records both old and new path.

**Recovery, since there is no undo stack.** A **narrow undo** of the last
operation is available only while *every* file in the batch still has it as its
most recent change — all-or-nothing, because a batch reversed for 299 of 300 is
a worse state than one not reversed. **Otherwise the log is the route**: it
reopens the operation with its files and their previous values, and restoring is
expressed as one more forward apply, per-file rather than one shared value. That
is what recovers the case where hundreds of photos each held a *different*
correct date before one apply flattened them.

### 7.6 Re-processing a disordered destination

When a destination has been reorganized or polluted from outside, the repair
needs no new engine capability — point the source at the old destination, the
destination at a fresh location, and run a Move (`engine-spec.md` §9.2).

**Three costs must be stated before offering it**, because each is invisible
until it bites:

* **Free space for the entire de-duplicated library**, up front. Deleting from
  the old destination frees space only on its own filesystem.
* **Photo IDs and run history do not survive it** (`engine-spec.md` §10).
* **Photos dated from modification time can move.** Show the count — directly
  available as `date_source = 'file_mtime'` — and the timezone in effect. Files
  carrying a real EXIF date are unaffected.

**Prefer reporting over re-processing on a library that is already organized.**
The destination inventory (`engine-spec.md` §9.1) costs nothing and moves
nothing.

## 8. Explicitly Out of Scope

* **The engine-side capabilities these workflows depend on** — the destination inventory, the perceptual pair table, destination deletion, and EXIF writing — are specified in `engine-spec.md` §9, not here. This document covers what the user sees and does; that one covers what the engine must be able to do first. None of them is implemented.
* **Multi-user auth/sessions** — not addressed in this spec. Add as a separate concern if the web UI needs to be exposed beyond a single trusted user on a local/private network.