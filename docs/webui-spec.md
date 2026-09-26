# Functional & Technical Design Specification: NegativeSpace Web Interface

## 1. System Overview & Architecture

The NegativeSpace Web Interface provides a modern web UI for the containerized Python engine (`ns-engine.py`). It transforms the CLI engine into an interactive application supporting real-time operation monitoring, selective file processing, context-aware duplicate resolution, detailed metadata inspection, dedicated runtime settings management, extension validation, and audit logging.

**Deployment:** two containers (`docker/compose.yml`). `web` (nginx) serves the built
React screens and passes `/api`, including the WebSocket, to `app`, which runs FastAPI
and the engine it spawns. Only `web` publishes a port.

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
|  [ Job Control ] ---> [ Engine Subprocess Execution ] ---> [ Log Parser Engine ]|
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
   (`POST /api/v1/jobs/start`, see `api-spec.md` §5).

5. FastAPI re-checks for an active job (409 if one exists), then spawns
   the engine, scoped one of two ways:
   python3 ns-engine.py --move --file-ids 101,102,105  (or --copy)
   python3 ns-engine.py --move --source-subdir sd_card/day1

6. The frontend shows aggregate progress and elapsed runtime (§4.1), refreshed
   about once per second. Per-file outcomes remain available through Logs.
   Progress requires phase/scoped totals as well as recorded outcomes; statuses
   alone are insufficient. Log replay subscribes first, then backfills (§4.1).

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
* **Multi-Select Controls:** Checkboxes on photo cards, Shift-click range selections,
  and a **Select ▾** menu above the grid: **Select all on screen (n)** (the photos
  visible right now), **Select all in this view (n)** (every photo the view, search and
  dates show, scrolled to or not), **Unselect all on screen** and **Unselect all**. Select all is refused whole above the 1,000-photo
  limit, never cut short (`GET /photos/ids`); an item that would do nothing says why.
  Keep the total selected count visible and repeat it in bulk-action previews, including
  metadata edits and deletion.
* **Selection across views:** retain explicit photo selections when changing pages
  or filters. The top row, after **Logs**, shows the total and the number outside the
  displayed view, for example **“25 selected · 10 outside this view”**, with **Show
  only selected** and **Clear**; clearing while showing only the selection returns to
  the results. Show only selected temporarily shows only the selected
  photos, including those hidden by prior filters or pagination, and allows inspection
  and deselection; the photos shown are fixed on entry, so one unticked there stays on
  screen, unticked. **Back to results** restores the previous search, filters, sort
  order and page while retaining the updated selection. It does not permanently replace
  the browsing view. Bulk actions use the explicit selection and show its count in the
  preview, not just the photos visible on the current page.
* **Copy or Move selected is reviewed first, never confirmed over the photos.** It shows
  every selected photo, whatever hides them, with a bar pinned above them: **"Review the
  25 selected photos below"**, what the action does, **Copy these 25 photos** (or Move)
  and **Cancel**. The photos can be scrolled, opened and unticked; the button's count
  follows the ticks, and an unticked photo stays on screen. **Why not a dialog:** one
  over the photos hid them and stopped the scrolling the review needs. **Cancel**
  returns to the view it came from; committing keeps those photos on screen as **the
  photos in the job just started**, so their statuses can be watched, until **Back to
  results**. Copy all and Move all still confirm in a dialog: there is no selection to review.
* **Date tree:** a **Dates** panel left of the gallery lists years and their months with
  counts for the current view and search, every year unfolded to start, every month with
  a photo on screen highlighted as the gallery scrolls (photos, not pages: a month of a few
  photos rarely starts a page or a row) and kept in sight in the panel, in the order of
  the gallery's date sort (oldest first lists the oldest year and month first; No date
  stays last, as both date sorts place it). Clicking a name
  goes to the page it starts on
  (a sort that is not by date switches to Newest first and says so). The boxes, under a
  **Show only** header, narrow the gallery to the ticked years and months; none ticked,
  the default, shows every date. A year's box ticks its months and shows a dash when
  only some are ticked. The filter is in the address, named above the gallery
  (**“Showing only June 2023, 2019 · Select these 412 · Show all dates”**; **Select these**
  selects what the filter shows, as Select all in this view does, refused above the
  1,000-photo limit. The boxes themselves only filter: unchecking a month to look
  elsewhere must never change the selection), and applies to the view
  counts; the tree's own counts ignore it, so an unticked month keeps its number. On a
  narrow screen the panel opens from a **Dates** button. Going to a date the filter hides
  says so and offers the fixes as buttons that apply them and then go there: **“December
  2016 is outside the dates shown. Show December 2016 too · Show all dates”**.
* **Fixes are buttons, not instructions.** Where a message names an action the screen can
  take, the words are a button that takes it (**Run an Index** in a log hint), never
  "tick it" or "go to X and click Y". Actions outside the app, such as fixing a folder's
  permissions, stay as text.
* **Unavailable selected photos:** keep the item visible in Show only selected with
  its reason. Built so far: a selected photo gone from the catalog is named there
  (**“1 selected photo is no longer in the catalog · Remove from the selection”**,
  from `missing` in `POST /photos/selection`); the counts and the required removal
  below are not yet enforced. Show counts such as **“24 available · 1 unavailable”** and require
  removal of unavailable items before confirmation. Never silently drop them from
  the selection. Revalidate before execution using the stale-preview policy (§7.1).

**Move/Copy preview:** before confirmation, group projected destinations by folder
with counts and expandable file details. Offer a downloadable operation plan for
the full scope. Label it a plan, not a log: subsequent execution can fail or detect
changed state, and its actual outcomes belong in the job log. Apply the same
selection counts and stale-preview safeguards used by other confirmed actions.

**Scrolling a large library:** the gallery scrolls continuously. Near either end of
what is loaded, the next or previous page loads, keeping the photos on screen where they
are, so rows run on without a half-empty row at each page boundary. Pages remain the unit
the API serves and the address records: the pager and the address follow the page whose
photos are at the top of the screen, so a refresh or a shared link returns to it. The
pager jumps (first and last, numbered pages with gaps, **1 … 48 49 [50] 51 52 … 2,500**,
a go-to-page box), and 60, 120 or 240 photos load at a time (**Load 60 at a time**).
Selecting in bulk speaks of the screen and the view, not pages. **Why not separate pages any more:** they were chosen
because selection was defined per page; the selection is now an explicit list kept
across pages, and a page count that the grid's columns did not divide left gaps. The date
tree jumps to a year or month by the page it starts on (`GET /api/v1/photos/timeline`).
The page, page size, sort, view, search, dates and open photo live in the URL.

**No capture date** is a quick filter beside the views, with its count. It shows the
photos whose EXIF has no date taken, which are filed under Undated by their file's
modification date. It combines with the view and the search, but the views' counts
ignore it: turning it on leaves **All photos** at its real number, and the pager says how
many are shown. Each view button keeps its width whatever its count, with room for
**(999,999)** in even-width digits, so switching views never moves them. **All photos** means every
photo: choosing it also clears No capture date, the date tree's Show only and the search,
and it is not shown as chosen while any of them narrows the gallery. The other views keep
them, to narrow within a view.

**Main-page browsing:** default to newest first by recorded photo date, clearly
distinguishing filesystem fallback dates from capture dates; offer size sorting.
Search matches current and original filenames, including names of related removed
duplicates, without merging their histories. Folder paths are not filename-search
matches. Distinguish not-yet-organized and organized photos; when a search has matches
in the other view, show its count and a link rather than implying no matches exist.
* **Selection size limit:** Individual multi-select (including "Select all on page") is capped at a configurable maximum (default: 1,000 files) per job submission — this isn't an arbitrary UX restriction, it's because each selected file becomes an integer in the `--file-ids` command-line argument passed to the engine, and there's a real OS limit on total command-line length. Exceeding the cap shows a clear message (e.g. *"1,000 file limit for individual selection — try Folder Selection below for larger batches"*) rather than silently truncating the selection or attempting a job that might fail at spawn time.
* **Folder Selection (for large batches):** Instead of "select all matching current filter" against individual files, users can select a source folder (recursive) and scope the operation to everything currently indexed under it. This maps directly to the engine's `--source-subdir <path>` flag (`engine-spec.md` §4.1) rather than enumerating individual IDs, which sidesteps the command-line length limit entirely — there's no practical upper bound on how many files a folder selection can cover. Symlinks are excluded automatically, inherited from the original Index that populated the catalog (a symlink was never indexed as a row in the first place). If a folder hasn't been indexed yet (zero matching rows), show *"No indexed files found under this folder — run an Index first."*
* **Actions on a selection:** **Actions ▾ → Copy ▸ / Move ▸ → selected (n)** (§4.1).
* **Targeted Execution:** Individual selections use the `--file-ids <id1,id2>` flag; folder selections use `--source-subdir <path>`. These are mutually exclusive targeting mechanisms in a single job — pick one per submission. IDs (not raw file paths) were chosen for the individual case specifically because a database primary key is unambiguous and doesn't depend on path strings staying identical between when the frontend fetched the catalog and when the operation actually runs — and it keeps one targeting implementation rather than a parallel web-only code path, which is what makes the engine directly runnable for debugging and development (see §1).

---

## 3. Dedicated Settings Management (`/settings`)

A dedicated Settings view provides central management of engine parameters, persisted
in the same SQLite database as catalog/history and passed to engine instances on
startup. Settings must work before the first Index: initialize tables and defaults
without scanning or touching photos. Saving validates and persists values; startup
must not reset saved preferences. The browser uses the API, never SQLite directly.
One consistent database backup includes settings and lineage. The settings writer
boundary is defined in §6.1; no second database is required.

**First run shows the settings as the page itself**, before the library exists, and
says prominently that these are starting values, changeable at any time from the gear
icon in Settings. Without that, a user can take the screen for the only chance to set
them. After first run, Settings opens as a window over the current view.

**Startup without a usable catalog:** distinguish a missing database from access
errors and from an invalid or corrupt database. Do not silently replace an existing
database or interpret a storage error as a fresh installation. If no database is
found, show **“No catalog found. If this is your first time using NegativeSpace,
create a catalog to get started. If you’ve used it before, check your appdata mount
or recover your catalog from a backup.”** Offer **Create new catalog** explicitly;
only after that choice initialize the database and defaults, without running Index.
Verify application storage is accessible and writable before creation, and never
overwrite a database that appears between the check and confirmation.

In startup diagnostics and recovery guidance, show **Application data: `/appdata`**
and **Catalog backups: `/backups`**, labelled as container paths. Their host locations
are determined by the Docker mounts; do not claim the application knows those paths.
For read/write errors, show the specific reason and permissions/storage guidance.
For an invalid or corrupt database, explain the problem and point to backup recovery
guidance without automatically restoring or creating a replacement. When catalog
logs cannot be read, offer available application diagnostics rather than a broken
job-log link. This diagnostic path display does not add a backup destination setting.

**The worker count defaults to the CPUs the container may use**
(`ns_db.available_cpus`): the host's cores, reduced by a CPU set (`--cpuset-cpus`) or a
CPU quota (`--cpus`, rounded down, at least 1). Settings names which applies. A saved
value stays until changed, even if the container's limit changes later.

**Settings changes never affect an already-running operation.** Users may save
settings while a job is active; saved values apply only to jobs started after the
save. Each job retains its starting configuration, available in its job details.
Display a persistent notice in the job settings section, near Save:
**“Changes apply to future jobs. Active jobs will continue with their existing settings.”**
Repeat that clarification in the save confirmation when a job is active. Do not
require cancelling a job to save settings. Saves go through `ns_db.save_settings`,
which checks revisions and waits a bounded time for the writer (§6.1).

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
|     Without a usable capture date, files go to Undated/<year>, using mtime.      |
|     Other metadata remains available for manual review.                         |
+---------------------------------------------------------------------------------+
|                                                   [ RESET ]  [ SAVE SETTINGS ]  |
+---------------------------------------------------------------------------------+
```


### 3.1 Undated Photos and Capture-Date Evidence

A photo without a usable capture date (`DateTimeOriginal`) belongs under
`Undated/<year>/`, even if other metadata date fields exist. The year is its
filesystem modification year, not its creation year. Other dates are retained as
clues, not silently used as capture dates. `CreateDate` and `DateTime` are not
accepted as capture dates: both are real timestamps that describe the file rather
than the photograph.

The Undated view provides counts and filters for photos with other date clues but
no usable capture date, photos with other metadata but no usable date fields, and
photos with no readable metadata. Classification uses embedded metadata rather than
engine-added bookkeeping fields. Selecting a count opens the matching photos for
manual review in the shared editor. Show original paths/names and clearly label
capture, digitization and modification dates. Do not automatically promote a clue
to a capture date. Preserve original and subsequent placement decisions in lineage.


**Year subdivision is a filing aid, not a capture-date claim.** Use the placed
file's own modification year to keep Undated navigable. For byte-identical copies,
any anchor is acceptable; preserve the other copies' recorded names, paths and times
for review rather than selecting a winner from those attributes.

**Why not choose the earliest year across a duplicate group?** The group is not
complete when scan workers project paths, and identical bytes do not become more
trustworthy because one copy has an earlier mtime. The extra coordination does not
improve content selection. The user decides what date is meaningful from the evidence.

**Stable fallback date:** use the source modification time captured at its original
Index for `Undated/<year>`, including after capture-date removal. Preserve this
original snapshot per source copy, including duplicates; later rescans, edits and
transfers must not replace it. Show it as **Original source modification time (at
Index)**, not as a capture date. Genuine creation time, if available, remains a
separate historical clue.

**Why not file by creation time, or the earlier of the two:** a copy keeps its
modification time (NegativeSpace preserves it to the nanosecond) but gets a new
creation time. For most photos in a real library, which have been copied off a card,
between disks or from a backup, the creation time is the date of the last copy. Taking
the earlier of the two would help only a file edited after it arrived, and only on
disks that record creation times at all; NFS does not pass them on. The same photo
would then file differently depending on where it was indexed from. The snapshot lives in `source_snapshots` (`engine-spec.md`
§10) and the scan files from it; the mutable `photos.file_mtime` is refreshed for
change detection and is deliberately not the filing source.

The current catalog retains the mtime fallback in `date_taken`, labelled with
`date_source = 'file_mtime'`; the interface must not call it a capture date. If mtime
cannot be read, the read failure must remain visible rather than inventing a year.

### 3.2 Extension Support Validation
When a user adds or selects an extension in the settings panel or via the API, the
backend checks it with `ns_db.extension_support`, which knows exactly which formats the
engine reads as photos: the 13 raster and 23 RAW extensions in `engine-spec.md` §4.1.

1. **Supported:** no warning. Whether a particular file carries a capture date is a
   per-file matter, handled by the Undated review (§3.1), not by its extension.
2. **Not supported** (for example `.mov`, `.mp4`, `.xmp`, `.txt`): a non-blocking
   warning that such files are still catalogued, and that Copy and Move still carry
   them into the destination — usually under `Undated/<year>` by modification time —
   with no thumbnail and no similarity matching.
3. **Never blocking:** the user may keep the extension. Every engine run that selects
   one repeats the warning in its log, naming the extensions.

**Why not warn about PNG, GIF and BMP as "non-EXIF":** the engine reads them, and
ExifTool reads whatever metadata they carry; a warning keyed to the extension would be
wrong for every such file that does carry a date.

---

## 4. UI Layouts & Component Specs

### 4.1 Real-Time Operations Drawer
When a job is active, its progress shows at the top of the page, under the toolbar. When
it finishes, its result replaces it there as a banner until dismissed.

A finished job's banner explains its skips, grouped by the reason each photo recorded,
for example **"5 skipped (3 copied by an earlier job, 2 duplicates: the same content is
copied once)"**. The API groups them from the engine's reason text (`webui/catalog.py`).

The Library's actions live in one **Actions** menu, after **Library** in the page links:
**Index**, **Copy ▸** and **Move ▸**, the last two each offering **selected (n)** (the
photos selected in the Library) and **all (n)**. The toolbar's second row holds the views,
search and sort. Every item carries a one-line explanation, and one that cannot run
replaces it with why: a job is running, nothing is indexed, nothing is selected, or
nothing is left (**"Nothing to copy - every photo is copied or organized."**). The
**all** counts are the whole catalog's, by the engine's own rule
(`ns_db.TRANSFER_ELIGIBLE`), never the gallery's view or search: Copy takes photos not
yet copied, and Move also takes copied ones, deleting each source once its copy is
verified again, so after a full Copy, Copy all is empty and Move all is not. Its item
and confirmation say how many are already copied.
The divider between the gallery and the Inspector can be dragged or moved with the arrow
keys, and its position is remembered. When the Inspector is wide enough, the details sit
beside the photo instead of below it.

```
+-----------------------------------------------------------------------------------+
| Copying — 8,400 of 15,000 processed                 Elapsed: 00:12:34               |
| Progress: [================............] 56%                                       |
| 8,100 copied · 280 skipped · 20 failed                                             |
| [ View failures ]    [ View logs ]    [ Cancel Job ]                               |
+-----------------------------------------------------------------------------------+
```

* **Aggregate display:** refresh totals about once per second. Do not automatically
  scroll through a status line for every file. Full per-file outcomes remain recorded
  and accessible through **View logs**, **View failures**, and photo history.
* **Phase and counts:** during Index show files indexed, exact duplicates identified
  and files failed; during Copy show copied, skipped and failed; during Move show
  moved, duplicate sources removed, skipped and failed. Keep earlier-work recovery
  and run-level issues separate as defined in §5.5. Label duplicate counts as a subset
  where appropriate rather than adding them twice.
* **Progress bar:** measure processed items, including finished failed and skipped
  attempts, against a known total for the same phase and scope. Do not count scan
  and transfer records for the same photo twice, or include unrelated recovery.
  Stat-skipped unchanged files are counted as done (`unchanged`); raw operation-row
  counts would miss them. While a phase's total is unknown (the discovery walk), show
  activity and available counts with an indeterminate bar. Cancellation shows recorded outcomes and cancelled
  items without implying all work finished successfully.
* **Elapsed runtime:** measure from the job's recorded start, not from opening the
  browser or entering a phase. Update the display once per second; reconnecting or
  refreshing retains elapsed time. At completion, failure or cancellation freeze at
  the recorded final duration. A crash with no reliable end time must show duration
  as unavailable or approximate, not treat later reconciliation as the actual end.
  Timestamp storage and display follow §10.
* **Data contract:** the API reads `ns_db.read_progress(run_id)`, which the engine writes
  about once a second (`engine-spec.md` §4.3, table `run_progress`). It holds one entry
  per phase the run entered, in order, and the last is the current one. Each entry
  has `phase`, `total` (None while unknown: show an indeterminate bar), `done` (always
  the sum of the counts), and `counts` by outcome. Map phases and outcome keys to the
  labels above:
  * `scanning`: `indexed` plus `duplicates` is "files indexed", with duplicates as
    a subset; `unchanged` is "unchanged, not re-read".
  * `transferring`: `Copied`, `Completed` (moved), `Skipped`, `Failed`,
    `Cancelled`, `Found_At_Destination`.
  * `removing_duplicates`: `Removed_Duplicate`.

  The final entries stay as the job's summary. Active-worker counts, queue depth and
  fine-grained checksum steps are not required by this drawer and must not be
  invented from catalog statuses.

* **Job Control:** Provides a **Cancel Job** button. Sends `SIGTERM` to the engine subprocess (`POST /api/v1/jobs/{id}/cancel`, `api-spec.md` §5). During the **Index/scan** phase the engine stops at the next batch boundary and skips the move/copy phase entirely (everything already indexed is kept, so re-running continues where it left off) — note the UI should not expect per-file `Cancelled` rows for a scan-phase cancellation, since no physical work was scoped out yet. During **Move/Copy**, the file currently being copy-verified finishes normally, then every remaining targeted file is logged to the `operations` audit table with status `Cancelled` (not silently dropped — visible in the run's history afterward) and duplicate-source cleanup for that run is skipped entirely.
* **Cancellation feedback:** after the cancellation request is accepted, show
  **“Cancellation requested—waiting for the current work to stop safely.”** Keep
  progress and elapsed time visible and disable repeated Cancel clicks. The engine
  records `Cancelling` as soon as the signal arrives. That confirms the request
  arrived, not that work has stopped. Do not show
  **Cancelled** until the engine confirms that outcome; if the job completed before
  cancellation took effect, show its actual result. The final summary shows recorded
  completed, failed and remaining/cancelled counts where known, without inventing a
  remaining-photo count for an incomplete scan. Provide **View job log** both while
  cancellation is pending and in the final summary, opening Logs filtered to that
  job so the user can inspect what was done and any failures.
* **Delayed cancellation:** keep **“Cancellation is still pending. The job has not
  stopped yet.”** visible, with **View job log** and **How to force stop**. Keep
  conflicting actions blocked until termination is confirmed. Never escalate
  automatically. The help explains that stopping the application container also
  disconnects the web UI and can leave partially completed work requiring reconciliation.
  From the Docker host, `docker stop --timeout 30 <container-name>` requests shutdown
  and escalates to a forced kill after the timeout. For an explicit immediate forced
  stop, `docker kill <container-name>` sends SIGKILL. These are host instructions,
  not a browser-executed command. Confirm the container stopped before starting the
  web application again; do not promise an immediate stop if host storage is hung.
  Restarting a container reruns its configured startup command: the current CLI-only
  container may therefore start Index/Copy/Move again. Do not present restarting that
  container as a recovery-only action. The future web deployment must start the UI
  and reconcile/report interrupted work without resubmitting the job.
  Link **Backup history** and show the last successful backup time when known (or
  state none is available), as context rather than an instruction to restore it.
  Restoring an older catalog does not undo file changes and may discard recent lineage;
  ordinary interrupted-job recovery uses the current catalog. Docker behavior is
  documented in [Stop](https://docs.docker.com/reference/cli/docker/container/stop/)
  and [Kill](https://docs.docker.com/reference/cli/docker/container/kill/).
* **WebSocket Reconnection & Replay:** restore the aggregate snapshot and recorded
  start/end times on connection; a browser refresh does not restart the job or timer.
  For detailed operation history, subscribe to the run's live stream first and buffer
  events, then backfill through `GET /api/v1/runs/{run_id}/operations`. Merge and
  deduplicate by `operations.id`, ordering by ID rather than timestamp. This preserves
  complete history without forcing a fast-scrolling log into the progress drawer.
  Aggregate snapshots are separate from per-file events and do not pretend to have
  operation IDs; their transport and ordering still need a concrete API contract.

* **Browser disconnects do not cancel jobs.** Closing the tab or losing the network
  connection leaves the server-side job running. While disconnected, show
  **“Connection lost. The job may still be running. Reconnecting…”** rather than a
  failure verdict. On returning, restore the existing job's current progress or its
  final results if it has finished. Reopening the page never starts the job again.
  Cancellation requires the explicit **Cancel Job** action. If the container stopped,
  show the job as interrupted only once the interruption is confirmed, with links
  to its recorded outcomes and logs; a connection failure alone is not that evidence.
* **Connection loss after Start:** if the response is lost, show
  **“Connection lost. Checking job status…”** Disable repeat submission
  until the outcome is established. On reconnect, identify whether that request
  created a job, including jobs that already finished, and show its current status
  or results. Checking only for an active job is insufficient. Never automatically
  resend the Start request. If it is confirmed that no job started, re-enable Start
  for an explicit user submission; if the outcome remains unknown, say so and offer
  **View job history** and another status check without claiming it failed.
  Association is by request ID, never by timing or mode: the API passes each
  submission's ID to the engine as `--request-id`, and the engine records it with
  the run before any file work (`engine-spec.md` §4.1). A `job_requests` row for the
  ID identifies the job. No row while the engine lock is free means no job started.
  No row while the lock is held means the outcome is still unknown, because the
  engine may not have accepted the request yet. Duplicate delivery of one ID never
  runs twice.
* **Lost response after confirming a photo action:** use **“Checking job status…”**
  for rename, EXIF edit and deletion as well. Look up the recorded job/action,
  including completed actions, and display its recorded outcome with **View job log**.
  This is a status/history lookup, not a new inspection of files to infer whether
  changes were applied. Show recorded per-file outcomes for partial completion.
  If the submitted action cannot be identified, state that its status is unknown
  and offer job history. Never automatically repeat the action. Request association
  must cover curation actions as well as Index, Copy and Move.

### 4.2 Split-Screen Photo Inspector Panel
Clicking an image opens a right-side 50% detail panel.

**The file's modification time** is labelled **"As recorded when NegativeSpace first
indexed this file"**: the time the file carried when the first Index read it, not a date
the photo was scanned.

**Show all metadata.** The Index records every tag ExifTool reads (Pillow's when ExifTool
finds nothing), not a curated subset; the Inspector's fields are a few of them. A folded
**Show all metadata (n tags)** at the foot of the panel lists every one by name, with a
filter box; its header, with **Hide all metadata**, stays at the top of the panel while
the tags scroll. It is read from the catalog, so it shows the photo as last indexed, and costs
no file read.

**Label what comes from the photo's own metadata as such.** The Inspector groups the
EXIF dates (taken, digitized, modified), camera and exposure under **Photo EXIF
information**. Each date shows the offset EXIF recorded for it (`OffsetTimeOriginal`,
`OffsetTimeDigitized`, `OffsetTime`). If none has one, a single small note under the
heading says the camera recorded no time zone. If only some do, the others are marked
with an asterisk that the note explains. A time without a zone is never shown as UTC or
shifted.

**Clicking the preview enlarges it** over the blurred page, with the photo's details
below; Esc or the close button returns. It shows the 1024px preview, the largest image
the engine makes. The file's own date stays out
of that section: **File modified**, as the first scan observed it, sits under the file's
size. A photo whose EXIF has no capture date says so in the EXIF section, and its File
modified row notes that this date is what files it under Undated.

**Why no file creation date:** a copy is a new file with a new creation date, so for
an organized photo it is the day NegativeSpace copied it, and elsewhere usually the day
of the last copy or restore. That reads as a photo date and is not one. NFS does not
pass it on at all, so on a network library the row would always be empty. Only three
file times reach the engine over NFS: modification, which copies preserve and which is
shown; status change, which any rename, permission change or hard link resets; and
access, which reading the file resets.

**Deleted files retain their info screen and lineage.** Exclude deleted files from
the normal actionable library, but keep their info screens reachable from log links
and a **Deleted files** history filter. Show **Deleted**, the last recorded metadata
and location (labelled historical), original source Index information, and the full
recorded sequence of actions and before/after values. Deletion must not cascade away
these records or break existing history links. Do not offer edit or restore controls
for the deleted file. Preserve the information needed to reconstruct its recorded
metadata and naming/location history manually; this does not recreate photo pixels
or guarantee recovery of unrecorded external changes. Retained lineage does not
require retaining an orphaned thumbnail (§4.2.1).

**The photo info screen is the complete recorded history for that file.** Clearly
separate **Current metadata**, **Original source metadata at Index**, and **History**.
The original view includes the preserved source filename/path and filesystem
snapshot as well as captured metadata; later edits or rescans must not overwrite it.
History shows every recorded change across jobs: Copy, Move, rename, metadata edits,
refiling and deletion, plus failed attempts and reconciliation outcomes. Each entry
shows when it happened, its action and outcome, changed fields with before/after
values, old/new locations where applicable, and a link to its job/batch log.
Distinguish attempted changes from changes actually applied. Preserve navigation
through filename, path and content-hash changes. This is the tool's recorded lineage,
not a claim to reconstruct unobserved external edits; show unknown information as
unknown. Users can consult original values directly without piecing them together
from individual logs. No automatic undo or restore action is implied.

**Hash changes remain traceable to the original.** History links follow stable file
lineage, showing before/after hashes for content-changing actions and the original
Index hash. Neither a new hash nor a reused filename/path starts or merges history
implicitly. If the catalog identifies a different current file at a historical
path, show **“This historical path is now used by a different file.”** Link the
historical record and current file separately; do not redirect the old record to
the new occupant. Describe catalog knowledge as recorded, not live filesystem
verification. Distinct copies sharing a hash retain their own histories.

**Reimported content has a new history.** When a newly imported photo matches a
deleted record's hash, show **“Matches content from a previously deleted file”**
with a link to that historical record. Keep the new import's Index information and
subsequent actions separate from the old deletion history. Do not label the new
import as a restoration or imply a deleted copy is still available for deduplication.

**Every photo info panel provides a History / View logs action.** It opens all
recorded operations associated with that photo across runs, not just its latest
status or most recent job. Include the original source Index information, copies,
moves, renames, metadata edits, failures, deletions and recovery records where
applicable. Preserve access across changes to filename, path and content hash.
Each entry links to its run for context; related copies' histories are identifiable
as such rather than silently mixed with this file's own actions. Users can review
what happened and make manual corrections; there is no undo operation.

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

The Gallery grid and Inspector's "Media Preview" both need something to actually render. The engine generates it, since it is the only component with RAW decoding (`rawpy`) loaded.

**Status — grid generation is implemented.** The scan writes one 320px JPEG per
content identity, records it in `thumbnail_cache`, and reuses it for
byte-identical duplicates; `--no-thumbnails` turns it off and `--cache` relocates
it. The 1024px detail preview is generated on first view by `ns-engine.py --preview
<photo_id>` (`engine-spec.md` §4.1), and **Free up** is `ns-engine.py --clear-previews`;
the cache-size figures are `ns_db.thumbnail_cache_totals`, and the rebuild job is
`ns-engine.py --rebuild-thumbnails missing|all`. Still unbuilt: orphan cleanup after an
interrupted edit, which waits on metadata editing itself. Removing thumbnails whose content no catalogued
photo holds any more is implemented (`engine-spec.md` §9.8). One documented behavior is also not
met — recorded failure history is **not** retained across a successful
regeneration: `thumbnail_cache` holds current state per `(content_id, size)`, so
a later success clears the failure rather than preserving it. A permanently
undecodable file is therefore re-attempted on every scan.

* **Generation point:** During source Index, alongside SHA1/pHash computation. Reuse an
  existing cached thumbnail for the same content hash, including exact duplicates.

  **Raster** uses PIL with `draft()`, which decodes at a reduced scale rather than
  decoding fully and discarding the result: 8.2ms against 13.5ms.

  **RAW cannot be opened by PIL at all** and goes through rawpy. The rule is adaptive
  rather than tuned to any library:

  > Probe the embedded preview. If its longest edge is at least the target size, use it.
  > Otherwise generate one by demosaicing.

  A camera's embedded preview is the cheap path — 17.8ms with `draft()`, against 268ms
  to demosaic. But a preview existing is not enough: it must be large enough, or
  upscaling it would look worse than a fresh render. **Probing and failing costs 0.4ms**,
  0.15% of a demosaic, so the probe is effectively free and the rule self-tunes to
  whatever library it meets — 268ms per RAW where no preview is usable, 17.8ms where all
  are, without a threshold baked in for either case.

  *One observed distribution, offered as a data point rather than a model:* in the
  maintainer's library only 26% of a 300-file RAW sample carried a preview usable at
  320px, and that split almost entirely by format — CR2 100%, DNG 12%, with DNG previews
  clustering at 256x171. A library of other RAW formats could be anywhere in that range,
  which is precisely why the rule adapts instead of assuming.

  **Camera-rendered and engine-rendered thumbnails will not look identical.** An embedded
  preview carries the camera's white balance and picture style; a demosaic is a neutral
  render. Any library containing both paths will show both, and they may be visibly
  different side by side in a grid.

  **Why the demosaic does not enable auto-brightness.** It renders with camera white
  balance and no automatic exposure stretch, which lands roughly 30% darker than the
  camera's own preview on a normally exposed frame (measured: mean luminance 69.5 against
  the camera's 101.1, and 81.1 against 118.2). Enabling the stretch would close that gap
  on some frames — but it also brightens genuinely dark photographs into something the
  photograph is not. Measured on frames the camera itself renders at mean luminance 1.0,
  4.4 and 6.4, the stretch produces 43.3, 55.4 and 56.7: a visibly lit image where the
  camera shows black. A thumbnail that disagrees with the photograph is worse than one
  that is slightly dark, so faithfulness wins. A near-black thumbnail here is evidence of
  a near-black exposure, not of a generation fault.
* **Cache recovery:** on a missing preview, generate from an available source or
  destination copy associated with a catalog record. This supports cache clearing
  after Move removed the source. Do not generate for uncatalogued destination files.
  Missing cache entries alone are not evidence of destination modification.
* **Storage:** Small JPEG, **longest edge 320px**, written to `/cache/thumbnails/<ab>/<sha1>.jpg` — fanned out by the hash's first two characters so no directory holds tens of thousands of flat entries, and namespaced under `thumbnails/` so a later cache of another kind has an obvious home. Keyed by content hash, so identical files including cross-directory duplicates share one thumbnail.

  **Why 320px:** the rule of thumb is roughly twice the CSS size a thumbnail is displayed at, because a HiDPI screen renders two device pixels per CSS pixel. 320px stays sharp to about a 160px grid tile. Measured against the maintainer's library: 8.2ms and ~16KB per raster image, so a 150,000-image catalog costs about 3.3 minutes across 8 cores and 2.3GB of cache.

* **Two sizes, one generated lazily.** The grid thumbnail (320px) is generated during Index. The Inspector's Media Preview needs more resolution than a grid tile, so a **1024px** preview is generated on first view and cached thereafter. Generating both up front measured 14 minutes and 19GB for a 150,000-image catalog against 3.3 minutes and 2.3GB — most of which would be previews nobody opens. A preview that has not been generated yet is a pending state, not a failure.
* **Storage separation:** `/appdata` holds persistent application state (catalog, settings and logs), not disposable cache. Thumbnails under `/cache/thumbnails` are excluded from catalog backups and can be regenerated from available catalogued copies.
* **Metadata edits and cache cleanup:** after a successful embedded metadata change,
  use the resulting content hash as the thumbnail key. Reuse the thumbnail if that
  hash already has a cached entry; otherwise generate a new thumbnail from the edited
  file. Do not carry forward the old preview merely because image pixels may be
  unchanged. Remove the old hash's cached thumbnail once no current catalogued file
  references that hash; keep it if another unchanged copy still needs it. Historical
  lineage alone does not require retaining obsolete thumbnails. Clean up orphaned
  cache entries after interrupted operations as well, without removing shared entries
  still needed by current files. Preview-generation failure follows the failure
  reporting below and does not conceal a successful metadata edit. No manual cache
  clearing is required.
* **Schema:** `thumbnail_cache`, keyed on `content_id` — see `engine-spec.md` §6.5. Deliberately *not* a column on `photos`: a thumbnail belongs to content, not to one catalogued copy of it, which is what lets byte-identical duplicates share a single entry as the storage rule above requires.* **Failure handling:** Thumbnail failure must not fail an otherwise successful Index. Record the failure and show a placeholder with an explanation if generation fails or no readable catalogued copy is available. Thumbnails are disposable and excluded from application backups.
* **Explain unavailable previews:** the placeholder shows a concise reason when
  known, such as **“Photo file unavailable”**, **“Permission denied reading photo”**,
  **“Image could not be decoded”**, or **“Thumbnail cache could not be written”**.
  Provide details and a link to the associated log when available. Record the
  thumbnail attempt's failure category and diagnostic detail — the engine stores them
  in `thumbnail_cache` — and expose them through the API. Do not infer corruption from a generic decoder
  failure or infer thumbnail failure from a missing pHash. If the cause is unknown,
  say **“Preview unavailable; reason not recorded.”** A cache miss awaiting generation
  is a pending preview, not a diagnosed failure. Clear the current unavailable state
  after successful generation while retaining recorded failure history.
* **Cache size is shown per size, and the two are managed separately.** They have
  different economics and lumping them under one "clear cache" control would mislead:
  grid thumbnails are generated in bulk at Index and their loss blanks the gallery
  until a rebuild, while detail previews are generated one at a time on view and cost
  nothing to lose. Previews are also the ones that need visibility, because they grow
  silently as a user browses.

  > **Thumbnail cache — 3.5 GB**
  > Grid thumbnails · 2.3 GB · 29,048 photos
  > Detail previews · 1.2 GB · 10,412 photos opened
  >
  > **Free up 1.2 GB** — removes detail previews. They are recreated automatically the
  > next time you open a photo, so nothing is lost.
  > **Repair grid thumbnails** — makes the ones that are missing. Quick when little is missing.
  > **Rebuild all grid thumbnails** — regenerates every one from your photos. How long this takes
  > depends on the size of your library.

  Totals come from `SUM(bytes)` on `thumbnail_cache` grouped by `size`, not from walking
  the cache tree — which is why that table is keyed on `(content_id, size)` and records
  `bytes` (`engine-spec.md` §6.5).

* **Clearing previews needs no progress display.** Measured on local storage: 10,412
  files removed in 0.07s, 29,048 in 0.17s. Act, then report what was freed. Do not
  promise "instant" either — a `/cache` mounted on a network share turns each unlink
  into a round trip, and a result line reads correctly at any speed where a progress
  bar that never fills looks broken.

* **Rebuilding is a job, not a special case.** It gets a `runs` row, the drawer in §4.1,
  cancellation and a log entry, reusing the existing status transitions rather than a
  second progress protocol. It reports **counts** — files done of files total — which the
  drawer already provides.

  **Two scopes, the user picks.** *Repair* (`missing`) makes only thumbnails that are not
  on disk, retrying recorded failures; it is what a lost or partly cleared cache needs.
  *Rebuild all* (`all`) regenerates every one, for thumbnails that exist but are wrong.
  Both work from any catalogued copy, a delivered destination copy first, which a
  re-Index cannot do: it skips unchanged files, and a moved photo has no source left.
  *Rebuild all* replaces a thumbnail only when an unchanged copy can supply it and
  generation succeeds; otherwise the existing one, made from the same content, stays.
  Being cache only, the job records no operation and takes no backup. Measured on a
  ~1,200-photo sample over NFS with 8 workers: 9.2s to repair an entirely deleted grid,
  7.4s to rebuild all, 0.3s to repair a grid with nothing missing.

  **It must not display a time estimate.** A useful one is not computable in advance: a
  RAW file costs roughly 18ms if its embedded preview is large enough and roughly 268ms
  if it must be demosaiced, and which applies is unknown until the file is opened. A
  library's format mix therefore swings the total by an order of magnitude. Saying the
  duration depends on library size is honest; a number would not be. Deriving a running
  estimate from observed throughput, as Index does for its own progress, is *possible*
  but deliberately deferred — this is a rarely run repair operation and the estimate is
  well below a nice-to-have.

* **Serving:** `GET /api/v1/photos/{id}/thumbnail` (`api-spec.md` §4) serves the file directly from `/cache/thumbnails/`.

---

## 5. Safeguards, Operations & Error Handling

### 5.1 Pre-Flight Disk Space Protection
Before initiating any move or copy job, the system computes total payload size plus a 500 MB safety buffer. If destination disk space is insufficient, execution is blocked and a warning banner displays required vs. available space.

**Destination unavailable or not writable:** block Copy, Move, destination rename,
EXIF edits and destination deletion when the destination cannot be accessed or
written. Show **“Destination unavailable or not writable”**, the specific reason,
and guidance to check the Docker mount, storage connection or permissions. Never
silently select another destination. Index remains available when source and
application storage are accessible; catalog browsing and history remain available.
Unavailable photo previews follow the placeholder behavior in §4.2.1. An access
failure alone does not prove files were removed or changed outside the tool.
Recheck access when the user explicitly attempts an action again; do not queue or
automatically resume blocked work when storage returns. If access fails during an
action, preserve and report its recorded per-file outcomes rather than claiming
that no changes occurred.

**Index file-type accounting:** show a summary such as **“15,000
files found · 12,000 eligible by file type · 3,000 excluded by file type”**, with an
expandable excluded-count breakdown by extension (including files without an
extension). Eligibility uses the job's configured extension selection; it does not
guarantee a file can be decoded or its metadata read. Excluded files are untouched
and are not failures. Keep eligible-file processing outcomes separate from this
discovery summary; do not add excluded files to the failed-photo count or the
eligible-work progress denominator. Show only measured counts, scoped to the scan;
an interrupted or incomplete scan must label discovery counts as partial. The engine
records these per full Index (`engine-spec.md` §4.3, `ns_db.read_discovery`), and a
scoped run records none, so never infer them from catalog rows, which omit excluded
files.

**Empty source folder — ask, never guess.** When the source folder exists but holds no
supported files while the catalog holds photos from it, the engine changes nothing and
opens a needs-attention issue (`source_root_empty`, `engine-spec.md` §4.2): an
unplugged drive and a Move that took every photo look identical. Show it prominently,
not only in Logs:

> **The source folder is empty.** NegativeSpace holds N photos from it. Is the drive
> unplugged, or is the folder really empty?
> **[Check the connection and run again]** · **[It really is empty]**

**It really is empty** re-runs the job with the engine's confirmation
(`--confirm-source-empty`): photos whose exact content is on the destination are then
recorded **Found at destination**, and the rest as missing. Never offer a default or
pre-select an answer, and never answer on the user's behalf after a timeout.

**Move to a network share — warn, recommend Copy, ask.** When a Move's destination is a
network share, the engine stops before copying or deleting anything and opens a
needs-attention issue (`network_destination_unconfirmed`, `engine-spec.md` §4.1): a share
can report a copy saved before it is on the server's disk, and NegativeSpace cannot see
how the share is set up. Show it prominently when the Move is started:

> **Your destination is a network share.** A Move deletes each original once the share
> says the copy is saved, and some shares say so too early. **Copy is recommended:** it
> never deletes an original, so nothing can be lost.
> **[Copy instead (recommended)]** · **[Move anyway — this share is set to save
> immediately]** · **[Cancel]**

**Copy instead** starts a Copy of the same selection; **Move anyway** re-runs the Move with
`--confirm-network-destination`. Pre-select nothing and never answer on the user's behalf.
Copy to a network share is never interrupted by this question.

**Found at destination** (`Found_At_Destination`) means the photo's source is gone and
its exact content was observed on the destination, with no action taken by NegativeSpace
in that run — typically after a Move whose catalog records were lost to a power cut.
Present it as delivered, but label it as found rather than moved, and show its evidence
(source absent, destination content match) in the photo's history.

### 5.2 Job Persistence & Background Execution

**Unavailable source versus empty scan:** if the source cannot be accessed, show
**“Source unavailable. Check your Docker mount and storage connection.”** Include
the recorded reason and **View job log**. Treat this as a run-level scan problem,
not zero failed photos or a successful empty scan. A completed scan of a readable
source with no supported files, and no catalogued photos from it, shows **“0 supported
files found.”** If the catalog does hold photos from it, the engine asks instead (the
empty-source question in §5.1). Neither
outcome removes existing catalog history. Do not infer that a mount is healthy merely
because its container directory exists; if it appears readable but empty, report the
observed result without claiming the expected external storage was verified.

Jobs run asynchronously in FastAPI. If a user closes or refreshes their browser, the job continues unaffected. Reopening the web UI re-establishes the WebSocket connection and replays the operations log for that run (§4.1's WebSocket Reconnection & Replay) to stream live progress with full history intact, not just progress from the reconnection point forward.

### 5.3 Error Center
If operations fail, an Error Banner highlights the failures, sourced directly from the `operations` log's `error_message` column (see §6.1) — the real exception text is persisted, not just a generic "failed" flag.

**Failures belong to attempts, not to a photo's current status.** Query `operations.status = 'Failed'`, joining the photo and run for context; do not filter on `photos.status`. The two deliberately disagree in at least one case: when duplicate cleanup cannot verify that a destination copy still matches the source, it leaves the photo `Duplicate` — correct, since the source is intact and still a duplicate — while recording a `Failed` operation explaining why the deletion did not happen. An Error Center filtering on `photos.status` would show that photo as an ordinary duplicate and never surface the failure, which is the invisibility the recorded operation exists to end.

Some failures have no photo at all. A folder the scan could not read is recorded as a `Failed` operation with `photo_id` NULL and the folder as `source_path` — the photos inside it were never examined, so there is no catalog row to attach to. Left-join `photos` (an inner join drops these), and present such a row as a folder the user needs to fix permissions on, not as a file.

**`Skipped` is an outcome, not a failure.** A run records `Skipped` for a selected photo it deliberately left alone — a duplicate whose original carries its content, or a photo an earlier run already delivered — with a reason naming what holds that content (`Duplicate of photo #N ...`, or `Already copied to <path> by an earlier run`). **The already-copied reason reports what the catalog records, not a fresh check:** that run read and verified nothing, so the UI must not present it as confirmation the destination file is still present and intact. **Do not offer a re-index as the way to find out.** Index walks `--source` and never inspects `--dest`; and since `Copied` is a settled status, the unchanged-file skip means a plain re-Index does not even re-read the source. The row stays `Copied`, the next Copy reports `Skipped` again, and the destination file is still missing. What `--force-rehash` does is re-read sources and reset those rows to `Pending`, so a later Copy delivers the file again: a repair, not a check. The genuine answer to "is the destination still intact?" is the destination check (`ns-engine.py --check-destination`, `engine-spec.md` §9.1), which reads the destination: offer it here, and show the latest check's finding for the photo when there is one. Show these as informational, grouped apart from failures, and link the named original: a user who selected only the duplicate needs to know which photo to select instead. They exist so that every photo in a selection ends the job with a recorded outcome; a job whose selection held only duplicates used to finish green with nothing recorded at all.

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

**No dedicated retry subsystem.** There is no "Retry Item" / "Retry All Failed" backend endpoint and no `retry_count` tracking. A failed file's `photos.status` is reset to `Pending` automatically the next time it's re-indexed (a plain re-scan, full or `--file-ids`-scoped), so retrying means explicitly submitting a new operation. Successfully copied files remain in source; successfully moved files normally do not. Do not promise that rerunning requires no scanning or verification. The web UI's equivalent of "retry" is selecting the photos associated with failed attempts and re-issuing the same Move/Copy operation via `POST /api/v1/jobs/start` with their IDs in `file_ids` — no new endpoint required. Take those IDs from the failed `operations` rows rather than from `photos.status`, deduplicating when several attempts reference one photo, and do not require the photo's current status to be `Failed`: a duplicate-verification failure stays `Duplicate` and is retried by Move's duplicate cleanup on the next run. Retrying does not by itself fix a content mismatch or an unreadable file, so the UI should not promise that it will.

### 5.4 Operations Audit Log (`/logs`)
**Built** (`api-spec.md` §5a). The Library and Logs pages are switched from the toolbar. The
log is grouped by job, newest first: each job is one line (its summary and how many
entries match) until opened, and its entries page on their own. Filters apply inside
every job; while any is set, a job with nothing matching is left out. A finished
job's banner links to its log, opened on that job, and, when it failed, to **View failures**.
A dismissed banner stays dismissed on every page, in every browser, and after the
browser's data is cleared: the dismissal is kept with the catalog (`PUT /api/v1/ui-state`),
and covers that job and every earlier one. The Logs page has the Library's top row,
**Actions ▾** included, so the page links never move and whole-library actions start from
either page (Copy and Move selected are disabled there: selecting is the Library's). The
active filters are named in one line with one reset (**"Showing: job #3 · Failed ·
“photo-00” · Clear all filters"**). An open job's entries load in batches of 100 as the
list scrolls, and the job's header line, with its collapse arrow, stays at the top
meanwhile. Status counts keep their width, as the Library's view counts do. The Inspector's
**History** opens the log for that photo. Each failure carries a plain hint drawn from its
recorded reason, and **Retry**, inside the job it belongs to, runs the same mode again over the photos behind
that job's shown failures.

A searchable table logging every operation performed by the engine:
* **Columns:** Timestamp, Mode (`MOVE`/`COPY`), Source Path, Destination Path, Status (`Completed`, `Copied`, `Removed_Duplicate`, `Found_At_Destination`, `Failed`), and System Error Message.
* **Controls:** Filter by photo lineage, date, status, run, or free-text search;
  CSV/JSON export. The photo info page opens this view scoped to the selected
  photo's full history, with access to the surrounding run.

**Filtering by run is what two other screens link into**, so it is a first-class filter rather than a search convenience: the failure banner links here scoped to the most recent run, and the Dashboard's coverage message (§5.9) links here scoped to *every run since the last complete scan*. The filter therefore accepts a set of run ids, not only one.

### 5.5 Job Outcome Is Derived, Not Read From `runs.status`

**`runs.status` describes the run's lifecycle, not whether the work succeeded.** A run that reaches the end of its file loop is recorded `Completed` even if every single file in it failed. That is accurate for what the column means — the process ran to completion rather than crashing, being cancelled, or aborting on a pre-flight check — but it is the wrong thing to put in front of a user on its own.

For example, a `--move` against a source mounted `:ro` fails every file (the copy succeeds, only the source deletion fails) and still reports:

```
Run #2 finished with status: Completed
```

Surfacing that verbatim would show a green **Completed** for a job where nothing succeeded, and the user would have to open the Error Center to discover their entire operation did nothing.

**The API derives outcomes from classified operations, not just `runs.status`.**
Present three separate groups, each linked to its detailed logs:

* **Requested work:** outcomes for the current job's requested photos.
* **Earlier work reconciled:** recovery of interrupted operations from prior jobs.
  Do not credit these as files completed by the current request. Link the recovery
  record to the interrupted operation/run when known and to the run that performed
  reconciliation. Users can inspect it through Logs or the photo info page.
* **Run-level issues:** unreadable folders and other failures without an identified
  photo. An unreadable folder is one scan issue, not one failed photo; its unknown
  contents must not be converted into an invented file count. These issues remain
  visible even when every known requested photo succeeded.

The current aggregate below is diagnostic only: it cannot by itself distinguish
recovery from requested work or run-level issues from failed photos.

```sql
SELECT status, COUNT(*) FROM operations WHERE run_id = ? GROUP BY status;
```

The existing statuses and error messages remain useful, but recovery needs structured
provenance rather than interpretation of human-readable messages. **The engine now
provides it:** `operations.reconciles_operation_id` names the operation a recovery row
repairs, so a run's own requested work is the rows where that column is NULL. See
`engine-spec.md` §4.2. NULL-photo failures are already
identifiable as run-level issues. `runs.status` retains its lifecycle meaning.

Job responses should carry both: the lifecycle status **and** the derived counts, so the UI can render *"Move finished — 0 of 23 succeeded, 23 failed"* rather than a bare word. Recommended presentation rules:

| condition | display |
|---|---|
| `runs.status` is `Preparing` / `Running` | in progress, with live counts |
| `runs.status` is `Cancelling` | cancellation requested, still stopping (§4.1); keep counts live |
| succeeded > 0, failed = 0 | success |
| succeeded > 0, failed > 0 | partial success — surface the failed count and link the Error Center |
| succeeded = 0, failed > 0 | **failure**, regardless of `runs.status` being `Completed` |
| no changes, no failures or scan issues, and run completed | neutral completion with prominent counts and skip reasons; not an error |
| `runs.status` is `Cancelled` / `Interrupted` / `Failed` | that status wins; still show counts for what was done before it ended. `Interrupted` has no end time; show its duration as unavailable (§4.1) |

**No-change results lead with counts.** For example, **“0 of 120 files moved ·
120 skipped”**, followed by **“All 120 are already recorded as delivered to the
destination.”** For Copy, use **“0 of 120 files copied · 120 skipped.”** An unchanged
Index shows **“0 new · 0 changed · 120 unchanged”** using actual scan accounting.
Break down mixed skip reasons rather than attributing all skips to existing files.
Already-delivered counts describe catalog records, not fresh verification that
destination files exist or match (§5.3). Use the scoped counts for the requested
operation, excluding earlier-work reconciliation. Keep failures and scan issues
prominent; zero changes must not turn a problematic run into a clean no-change
result. Terminal cancellation, crash and failure take precedence over count-based
completion labels.

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

**No waiting queue for user operations.** While Index, Copy, Move or another
file-changing action is active, also disable photo selection and bulk-selection
controls, showing **“Selection is unavailable while a job is running.”** Browsing,
photo information and history remain accessible. After the job ends, refresh the
view before re-enabling selection. A selection already present in another tab must
be reviewed against refreshed file information before use; never automatically
submit it. These restrictions apply during Preparing and Cancelling as well.

While Index, Copy, Move or another
file-changing action is active, disable new processing jobs and photo rename,
EXIF-edit and deletion actions. Show **“Photo changes are unavailable while a job
is running.”** Browsing, photo history and settings remain available; settings
changes apply only to future jobs (§3). Reject conflicting submissions at the API
as well, including races between tabs, rather than queuing them. When the active
operation ends, controls become available again; nothing starts automatically.
The user must initiate and confirm a new action against current state. This extends
the existing processing lock requirement to planned curation operations; those
operations are not implemented yet.

Only one engine process may run at a time — see `engine-spec.md` §4.1/§7 for the engine-level guarantee (an OS-level `flock`, held for the whole process lifetime, released automatically even on a hard `SIGKILL`). This is enforced in two layers, not one:

* **Fast pre-check (FastAPI):** Before spawning the engine, `POST /api/v1/jobs/start` probes the engine's own lock: a non-blocking `flock` on `<base>/engine.lock`. If the lock is held, an engine is running, and it returns `409 Conflict` immediately — no subprocess is spawned, and the response includes the newest active run's (`Preparing`, `Running` or `Cancelling`) `id`, `mode`, and `started_at` so the frontend can show *"A Move operation is already in progress (started 2 minutes ago) — wait for it to finish or cancel it."* The Rescan/Move/Copy buttons should all be disabled client-side whenever a job is known to be active, so this 409 is a backstop for races (e.g. two tabs), not the primary UX.

  The pre-check must not decide from an active `runs.status` alone. A row orphaned by a crash stays active until the next engine run reconciles it, so a pre-check that trusted the table would refuse to start that very run: every job blocked, permanently, by a process that no longer exists. If the probe *acquires* the lock, any active rows are stale, and the engine about to be spawned marks them `Interrupted` during its own startup. Two requests can still race between the probe's release and the engine's own acquisition. The engine's lock decides, and the losing engine exits non-zero with its FATAL message, which the API reports as a 409.
* **Authoritative guarantee (engine):** The `flock` in `engine-spec.md` §4.1 is what actually prevents data corruption if the fast check above is ever wrong or stale — see the FastAPI-restart case below. Even if FastAPI's own bookkeeping says "nothing running" incorrectly, a second engine process attempting to start will still be refused by the lock and exit cleanly with a logged error, never silently racing a real in-progress run.

**FastAPI-restart edge case:** if FastAPI itself restarts (redeploy, crash) while a job is running, its in-memory job/WebSocket-subscriber state is lost, but the engine subprocess is *not* killed by its parent dying — it keeps running under the protection of its own lock. On startup, FastAPI finds such a job by querying `runs` for any row in an active state (`Preparing`, `Running`, `Cancelling`). Two cases:
1. **The engine process is genuinely still alive** (the common case) — FastAPI should treat this as an active job for UI purposes (allow reconnecting clients to replay/stream it per §4.1) without being able to directly re-attach to the subprocess's stdout; the `operations` log is what makes this possible without that direct attachment.
2. **The engine process died too, before a later engine run could mark that row `Interrupted`** (`engine-spec.md` §4.2) — a double failure that leaves an active row with nothing behind it. FastAPI tells the two cases apart with a **non-blocking `flock` on the same lock file as a liveness probe**: if the probe acquires it, no engine owns any active row. FastAPI then **presents** those rows as interrupted, awaiting reconciliation, with duration unavailable. It does not write them. The next engine run records them `Interrupted` and names itself as the run that found them.

   **Why the API does not mark them itself:** run lifecycle and history are engine-owned; the API's write scope is settings. An `Interrupted` row names the run that reconciled it, and the API is not a run. Settling the run record alone would also leave its files unsettled: rows still `Processing`, partials on disk, operations with intent and no outcome. Only engine startup reconciliation settles those, and it does both together.

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
* **No destination deletion is implied.** The engine never deletes anything under `--dest`. Redundancy that something outside the engine put there is reported by the destination check (`engine-spec.md` §9.1), not resolved by it. This figure covers source files the engine can remove; what deduplication saves at the destination is the separate figure below.
* **`Failed` rows are not duplicates.** A source that vanished outside NegativeSpace is marked `Failed` at the next full Index, which removes it from its duplicate group and lets a surviving copy be promoted to anchor. It therefore drops out of this figure automatically — correct, since deleting a file that no longer exists reclaims nothing.
* **Sizes are as of the last scan.** `file_size` is recorded by the Index that wrote the row (§6.1), so the total is as current as the catalog. Show it alongside the last scan time, as §5.8 asks of folder counts, so a stale figure reads as stale rather than as wrong — and see the coverage rule below, because "the last scan" must mean the last scan that actually established coverage.

**Coverage: show the last trustworthy date, and say what happened since.** The date beside these figures is the most recent Index that completed **and recorded no run-level failure**. An Index that was refused or could not read part of the tree keeps its own date out of this figure — but it is not hidden either. The tile reads:

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

The Inspector's `duplicates` array (`GET /api/v1/photos/{id}/inspect`, `api-spec.md` §4) carries each copy's `file_size` for the same reason, so a single photo's panel can show what removing its duplicates would reclaim.

---

## 6. Database Schema & API Specifications

### 6.1 SQLite Schema

**There is no in-place upgrade path and none should be added.** Migration code runs rarely, on real user data, along a path that is almost never exercised. During development, a schema change may require a fresh catalog. This is a development convention, not a lossless user recovery workflow: Index cannot recreate settings or operation history.

The engine validates its `catalog_schema` version on startup. The API must use the shared schema check and report incompatible catalogs clearly; no automatic migration is implemented.

**Only `photos` is derived. `runs` and `operations` are not, and rebuilding discards them.** Every value in `photos` is recomputable by re-running an Index over the same sources — verified by rebuilding a ~29,000-file catalog from scratch and getting identical per-status counts. Nothing recomputes the audit log: it records what the engine *did*, and re-scanning the filesystem cannot reconstruct it. The sharpest case is `Removed_Duplicate`, where after a `--move` that row is the only evidence the file ever existed — its source was deleted by design and its content survives only under the anchor's name.

**Lineage is keyed on stable per-file identity** (`engine-spec.md` §10), with original
Index information and distinct histories for identical copies and deleted files, all
in the one catalog database. The Error Center and photo history read it through
`operation_files` (§6.3); `photos` rows and hash-only joins do not carry that contract.

The practical consequence for the UI: rebuilding loses recorded history and settings even when the library has only been Indexed or Copied. After Move, original source information may no longer be recoverable from files either. Do not describe a rebuild as lossless or use the presence of `Removed_Duplicate` rows as the only warning criterion. Offer a backup first (`--backup-now`, §9) — a plain file copy of a WAL database is not a consistent backup — and treat a JSON export of `runs` and `operations` as the format for reading history outside the app or carrying it across a schema change, not as a substitute for the database backup.

**Status values are enforced by the database, not by convention.** Each `status` column carries a `CHECK` constraint listing exactly its vocabulary, generated from the same tuples the engine uses. An API write of `'copied'` or a filter on `'Complete'` fails loudly at write time rather than silently disagreeing with the engine — a mismatch whose only symptom would otherwise be photos that never appear. Treat the constraint as the contract and do not hardcode a parallel list; read it from the engine's constants or from `sqlite_master` if the API needs to enumerate.

**The API layer must use engine-owned schema initialization and validation.**
`ns_db.py` stamps schema version 11 and refuses incompatible catalogs. Settings saves
use its scoped revision-checked functions; the browser never accesses SQLite.
Preserve an incompatible catalog and explain the version mismatch. Index cannot
repair a schema mismatch or reconstruct lost history; do not suggest deleting a
user catalog. Development uses fresh catalogs until migration support is provided.


Note the asymmetry this creates for the UI: deleting the catalog is cheap for Index state, but it discards the record of which files a previous Move already migrated. Where the UI offers a rebuild, it should say so.

**The authoritative schema definition lives in `engine-spec.md` §6.5**, executable
as written. It is not duplicated here: the engine owns the catalog, creates it,
and writes photo state/history, so a second copy in this document would be a copy that
drifts. What this section carries instead is what the API layer must know in
order to consume it safely — the rules above, and the two below.

**Settings share the catalog database.** The engine's database definition owns the
schema (`engine-spec.md` §6.5); initialization must be callable without Index.
**Write ownership:** the engine owns the schema and photo state/history. The web UI
manages settings through the API, which writes settings using shared Python database
and validation code. The browser never accesses SQLite directly. API settings writes
do not authorize arbitrary photo-state or history updates. Initialization uses the
engine-owned schema routines without requiring Index; the API defines no competing
schema. The shared functions are in `ns_db.py`, and the API calls them (`webui/`).

Use short transactions with bounded lock waits and report save failure truthfully.
Settings can be saved during processing; each job retains its starting configuration.
Do not hold the processing lock for the duration of a settings save or queue settings
behind a whole job.

Thumbnails are not a column on `photos`: they belong to content and live in
`thumbnail_cache` (§4.2.1).


### 6.2 Key REST API Endpoints

**The implemented API is specified in [`api-spec.md`](./api-spec.md)**: catalog status and creation, settings, the gallery listing and timeline, photo details, thumbnails and previews, starting and cancelling jobs, runs and their derived outcome, and the live job feed. CI keeps it in step with the routes in `webui/app.py`. What follows are endpoints designed here and not built yet; each moves to `api-spec.md` when it is.

The run history and the Error Center's failures are built: `GET /api/v1/operations` with
`run` and `status` filters (`api-spec.md` §5a).

GET /api/v1/stats/duplicates

Backs the Dashboard's duplicate-space tiles (§5.9). Three separate figures, each naming the volume it applies to: what Move could still reclaim from the source, what past Moves already reclaimed from it, and what was never written to the destination in either mode. They overlap by design — a moved duplicate appears in both `already_reclaimed` and `saved_at_destination` — so the API returns them separately and the UI must not total them. `last_indexed_at` is the most recent **full Index** covering the source roots the figures span — `mode = 'INDEX'` with no targeting filter — that both **completed** and **recorded no run-level failure**. Not simply the most recent completed run: a one-file targeted Copy is a completed run, and taking its timestamp would stamp the whole catalog as freshly scanned on the strength of a run that examined one photo.

**Completing is not the same as covering.** An Index whose source was detached finds nothing, correctly refuses to condemn the catalog, records a run-level `Failed` operation — and still ends `Completed`, `mode = 'INDEX'`, untargeted. It satisfies every criterion above except the one that matters, having established no new coverage at all. An Index that could not read part of the tree has the same shape. **The safeguard works and then misreports its own freshness**, which is the defect.

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

**Extension scope counts too.** An Index run with a narrowed `--exts` scans the full tree, succeeds completely at a smaller job, and records no failure, having examined only some file types. Its effective extension set is recorded in `run_configs` (`engine-spec.md` §6.5), so the API can see it: an Index whose effective extensions omit a supported type does not advance the coverage date, and is listed in `run_ids_since` like any other later run.

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

### 6.3 Reading a photo's history across identity changes

**A history view keyed on `photos.id` alone will silently drop the older half of a
photo's past.** It is the single most likely way a correct catalog gets presented
incorrectly.

`photos` holds one row per source *path*. Identity lives in `files`, bound to the
photo row through `photo_files`. When a source returns after a completed Move or a
duplicate removal, that arrival is a **new identity** — same path, same bytes, new
`file_id` — and `photo_files` rebinds the photo row to it. The previous identity keeps
everything: its immutable `source_snapshots` row, its observations, and every
`operation_files` link it ever had. None of it is deleted. It is simply **no longer
reachable from `photos.id`**.

For example, identity 1 keeps its snapshot and three operations across three runs while
the photo row is bound to identity 971. A view joining
`photos → photo_files → operations` shows only the new arrival and presents a photo with
no history, which is false.

**So traverse identities, not photo rows.** For a given photo:

1. Resolve the current identity through `photo_files`.
2. Collect every identity sharing that `source_snapshots.source_path` — these are the
   successive arrivals at one location, each with its own snapshot and history.
3. Walk `file_origins` in both directions: `origin_file_id` reaches the source a delivered
   file descends from, and the reverse lookup reaches everything created from it.
4. Union the `operation_files` links of all of them, ordered by `operations.id`.

**Present them as distinct arrivals, never merged into one timeline.** Two identities at
one path are two different files that happened to occupy the same place; showing their
operations interleaved as a single photo's history asserts a continuity that did not
happen. Label each arrival with its original Index time.

**Separate requested work from recovery.** An operation with a non-NULL
`reconciles_operation_id` is a repair of earlier work, not something this run was asked
to do; counting it as the run's own output credits a job with work it never requested.
An operation may legitimately link a *new* arrival to an *older* delivery. For example,
a Move whose source is a fresh arrival can find the previous delivery already sitting at
the destination and record it as a `retained_copy`. That comes from the
ordinary transfer path, not from reconciliation — both produce such links, and neither is
an inheritance. The new arrival did not deliver that file, and the UI must not imply it
did. **Distinguish by role, not by which code path wrote it:** `destination` means this
operation produced the file, `retained_copy` means it found it already there.

Cost is not a concern: assembling a full history measured 0.08–0.6 ms per photo against
a 971-identity catalog, covered by `idx_lineage_file` and `idx_events_operation`.

## 7. Destination Curation & Similar-Photo Review

Everything above is about getting files *in*. This section is about curating
what is already there — a different activity, with a different safety story.

**These workflows depend on engine capabilities in `engine-spec.md` §9.** The
destination check and renaming a delivered file are built; the perceptual pair table,
deleting under `--dest`, and writing EXIF are not. This
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
  pending-changes indicator. Show consequences before confirmation. There are no
  undo operations; users consult history and make manual corrections as new actions.
  Bulk metadata apply (§7.5) previews an explicit selection as one action.
* **Revalidate the preview before execution.** If the relevant library state or
  proposed outcome has changed since preview, stop before applying the action and
  show **“The contents of the library have changed. Please refresh to see the most
  up-to-date information.”** Provide **Refresh** to reload the affected view. The
  user must review an updated preview and confirm again; refresh does not execute
  the old action. Do not silently apply a changed selection, target or collision
  filename. This also applies to changes made from another browser tab.
* **A failed action leaves its row in place with the reason attached.** Show what
  actually changed; do not promise that every failure left the file untouched.
  Failures are `operations` rows, available in Logs (§5.4) and photo history.
* **Bulk actions report per-photo outcomes.** For example, show **“97 renamed ·
  3 failed”**, with failed items opening their reasons and links to photo history.
  Keep successful changes; do not undo the successful portion of a batch.
  Offer **Review failed items** to prepare a new action containing only failed
  items, checked against their current state with a fresh preview and confirmation.
  This is a new user-confirmed action, not an automatic retry. If a photo was
  partially changed (such as EXIF saved but refiling failed), identify it explicitly
  within the failures, show completed and failed steps and its current location
  when known, and state any uncertainty. Do not present it as untouched or successful.
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
* **Refresh preserves browsing position whenever possible.** Retain the current
  view, search, filters, sort order, page or loaded scroll range, and visible-photo
  anchor with its scroll offset. This applies to manual refresh, reconnection,
  post-job refresh and stale-preview refresh. Restore by stable file identity where
  possible so a rename or reordered results do not unnecessarily send the user to
  the top. If that photo was deleted or no longer matches the view, use a nearby
  surviving result or the nearest valid position. Do not restore stale photo data
  or bypass selection revalidation merely to preserve position. Browser reload
  should restore saved view state when available; a new browser without that state
  cannot be assumed to know the previous position.
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
reads as "handled" when nothing has been. After successful duplicate removal, those copies are history. Copies left by a
Copy operation or failed cleanup may still remain in source. Show recorded outcomes
per copy rather than treating every duplicate as removed merely because a Move ran.

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
**both** old and new path for lineage. There is no undo control; a later correction
is a new rename checked against current files. Preview the resolved collision name,
report the actual result, preserve the real extension and date folder, and update
related current references without rewriting history. A missing or changed target
stops the operation and shows §7.6 guidance.

**Engine calls** (`engine-spec.md` §9.4): the candidate names come from
`ns-engine.py --rename-candidates <id>`; the live check of a typed name is
`--rename <id> --name <name> --dry-run`, which prints the resolved path, or the reason
there is none, and takes no lock; confirming runs `--rename <id> --name <name>` as a
job. Its outcome and the actual resulting name are its `Renamed` (or `Failed`) operation.

**Choosing the name at move time is a different feature, and is deferred.** It
would decide the name as the file is written, but it is an engine change and it
asks for naming decisions before the library is organized.

### 7.4 The Similar tab

Matching compares against the full catalog, including delivered photos; it needs an
initial backfill and refresh when perceptual hashes change (`engine-spec.md` §9.3).
Find Similar results are measured against the selected reference, not chained through
other matches. Missing hashes are labelled unavailable rather than unique; historical
records remain accessible without being offered as actionable missing files. The
stored comparisons must support the full slider range. Dimensions are captured during
Index; unreadable dimensions display as unknown.

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

> **Permanently delete these 400 files?** This cannot be undone. NegativeSpace
> cannot recover deleted files. History retains their original locations, but
> recovery is only possible if you still have the originals or another photo backup.

The count carries the warning. "Are you sure?" is noise a user learns to
dismiss; "400 photos" is what stops someone who meant to select four.

**Discarding deletes.** It does not quarantine — see `engine-spec.md` §9.5 for
the reasoning and the full record retained after deletion. Every user-requested
destination deletion carries the warning, not only Select All. Show recorded original
locations as historical information; a prior Copy does not prove the source survives.
Only claim another matching copy is available after checking it. Catalog backups
cannot recover pixels. Keep deleted entries in history, not actionable photo lists;
show each outcome and stop on detected destination mismatches (§7.6).

### 7.5 Editing metadata

**Leaving an editor with unsaved changes:** when in-app navigation or closing the
editor would discard changed input, ask **“Discard your unsaved changes?”** with
**Keep editing** and **Discard**. Keep editing preserves the input and stays in the
editor; Discard abandons only unsubmitted edits and continues the requested navigation.
Do not automatically save or queue an action. This prompt does not cancel an action
already submitted. For browser tab close or reload, use the browser's supported
unsaved-change warning where available; its wording and buttons are browser-controlled.

**Validation references:** define validation for each exposed editable field using
[CIPA's EXIF standard](https://www.cipa.jp/e/std/std-sec.html)
(DC-008-Translation-2026, Exif 3.1) and
[ExifTool's EXIF tag reference](https://exiftool.org/TagNames/EXIF.html).
Record the intended tag/group, permitted representation and values, and write support
for supported photo formats. Validate in the UI and again before writing in the
backend; translate friendly controls to the required metadata representation.
Editable metadata includes writable photo-descriptive EXIF fields supported by the
writer and format; filesystem stat, structural image properties and computed catalog
fields are read-only. Do not confuse ExifTool writability with permission to edit
derived properties. Keep capture date/time and its
optional timezone offset distinct, consistent with §10.

**An edit can create an exact duplicate.** If the edited file's resulting content
hash matches another catalogued photo, update the exact-duplicate relationship and
show it in the result with a link to review the matching photos. Preserve both files
and their individual lineage; do not automatically delete, merge away a file's
history, or trigger duplicate cleanup as part of a metadata edit. Any deletion is
a separate explicit action with its own preview and confirmation. A catalog hash
match does not replace live verification required before duplicate deletion.

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
* **Edits that change nothing:** preview counts such as **“20 selected · 12 will
  change · 8 already match”**, comparing the selected fields against current values.
  Leave matching files untouched; do not rewrite them or regenerate their thumbnails.
  If every selected photo already matches and no required refiling remains, show
  **“No changes needed”** without executing an edit or creating an edit backup.
  For a mixed selection, back up once before changing the actionable subset and
  report already-matching photos separately from changes and failures. Required
  refiling is still a change, even if the selected metadata values already match.
* **Mixed values are not edits:** shared fields with differing values show
  **“Multiple values”**, while comparison columns retain individual values. Fields
  left untouched retain each photo's existing value. Only explicitly changed fields
  are applied; **Clear this field** is a deliberate action, distinct from leaving
  the field untouched or copying a missing donor value.
* **A preview before committing** states the count plainly — *"apply to 47
  photos"* — and which fields change from what to what.
  Show an explicit warning before confirmation: **“Applying these fields to the
  selected 47 photos will overwrite any existing values in those fields. Other
  fields will remain unchanged.”** Name the fields being applied, use the actual
  selection count, and allow inspection of per-photo before/after values. For an
  explicit clear, say that existing values in the named fields will be removed.
  This warning applies to both typed values and fields copied from a donor photo.
* **Date fields carry a notice:** "Changing the date used to organize this photo
  may move it to another folder." Validate user-entered date/time format and calendar
  validity before allowing confirmation or writing to a file. Show errors beside
  the field and retain the user's input for correction. The API/engine must also
  validate submitted values before writing; UI validation alone is not sufficient.
  Reject invalid edits without changing metadata or moving the photo. This differs
  from indexing existing missing/unreadable capture dates, which uses the agreed
  `Undated/<year>` fallback. An explicit clear remains a separate valid action.
  Preview current and resulting locations. For
  bulk edits, show how many files move and allow inspection of destinations.
  Explicitly clearing the capture date follows the same workflow: warn that the
  capture date will be removed and show the resulting `Undated/<year>` path under
  the agreed fallback policy (§3.1). Other metadata dates do not silently replace
  the removed capture date for filing. Removal and any required refiling are part
  of the same confirmed action, with per-photo before/after values and locations
  retained in history.
* **Copying capture dates defaults to the full date/time field.** Copy the donor
  photo's recorded date and time, making it explicit in the preview that selected
  targets receive the same value. Offer **Copy date only** only where the metadata
  format and writer support the intended date-only change without inventing a time;
  precise supported behavior remains to be verified. If the field requires a time
  and cannot represent the requested date-only value, copy the donor's time as well
  and explain that before confirmation. Never substitute midnight as an unknown-time
  placeholder. Users may manually correct individual times afterward; batch history
  identifies all affected photos and their before/after values. Preserve known
  timezone information according to §10, without inventing an absent offset.
* **Write back to the metadata source:** today edits update embedded EXIF in the
  delivered photo, including manually entered values. Unsupported writes fail
  clearly. Sidecar support remains a future option; see `engine-spec.md` §9.6.
* **Preview unsupported writes:** before confirmation, identify selected photos
  that cannot store the requested embedded fields, with counts and per-photo reasons
  (for example, **“18 photos can be updated · 2 cannot store the selected field.”**).
  Leave those unsupported photos unchanged and make the actionable subset explicit
  before the user confirms. Do not silently apply only part of the requested field
  set to an unsupported photo. Do not create sidecars or substitute catalog-only
  edits. This is a photo organizer; supporting arbitrary image formats is outside
  scope. Existing read/index support does not imply embedded-write support, and this
  decision does not change the current engine's extension list. Runtime write failures
  still follow the per-photo failure reporting rules in §7.1.

**Workflow.** Select, enter a value or pick a donor and fields, review the
preview, confirm. Then, before anything is written, **the catalog is backed up**
automatically — silent, fast, no confirmation asked. Each file is written
to a temporary working copy. Verify every requested field, including removals, and
required file-integrity checks before replacing the original. A write/verification
failure leaves the original unchanged and logs the failed fields; do not apply only
the successful fields of that photo's edit. Other photos in the batch may succeed.
Retain recovery material until publication and required refiling have completed;
report any failure at those later stages accurately (§7.1).

**Logs link back to the photo.** An edit's log entry provides **View photo**, opening
the current photo info panel with its failure details/history and **Edit metadata**
when the delivered file is available and no conflicting job is active. Resolve the
photo through lineage even after name, path or hash changes. The user can correct
the input and submit a new previewed, confirmed edit; following the link never retries
the old action. For missing or deleted files, retain access to recorded information
and explain why editing is unavailable. Failures without an identified photo do not
offer a photo link.

**Temporary space for edits:** check available space on the destination filesystem
before creating each photo's working copy, accounting for temporary output and
recovery material required by the write strategy. If insufficient, leave the original
unchanged and show **“Photo could not be updated: insufficient space for a temporary
copy.”** Include required and available space, **View photo** and **View job log**.
Process batch working copies one photo at a time, completing its publication/refiling
and cleanup before staging the next, so space for a second copy of the entire batch
is not required. A pre-check cannot reserve free space: handle write-time exhaustion
through the same safe failure path, retaining any material needed for incomplete
recovery. Keep successful batch edits and report per-photo outcomes (§7.1).

**Cancelling bulk metadata edits:** after Cancel is accepted, finish the current
photo's write, verification and required refiling safely (or record its failure),
then stop before starting another photo. Retain completed edits; leave unstarted
photos unchanged. Show cancellation pending until the operation actually stops,
then summarize updated, failed and not-started/cancelled counts with **View job log**.
Preserve batch membership and each photo's before/after values, paths and lineage
so users can trace changes and make manual corrections. Do not automatically roll
back completed edits, restart the batch, or queue remaining work. History is evidence
for manual correction, not a guarantee that deleted photo content can be recovered.

**Verification:** read every requested metadata field back and decode the edited
working copy, recomputing pHash before replacing the original. Associate the result
with the resulting content identity and refresh similarity relationships. Rename,
Move and Copy of unchanged content reuse existing pHash values. Identify intentional
orientation changes from the requested, group-qualified tag and verified before/after
values. Verification must account for that expected rendering change, not demand
blind equality with the old pHash or disable integrity checks entirely. EXIF field
validity does not prove decoder behavior or pixel integrity; a matching pHash is
not proof of exact pixel equality. Define and test consistent decoding/orientation
rules for supported formats before implementing this verification path.

**Rotate is an EXIF edit, never a pixel edit.** The Inspector and bulk edit offer
**Rotate left**, **Rotate right** and **Rotate 180°**. Each changes only the EXIF
`Orientation` tag, which viewers and galleries apply when displaying the photo.
The pixel data is never decoded and re-saved: re-encoding a JPEG loses quality on
every save, and a rotation that changed pixels would be a different photograph.
It goes through the same confirmed edit as any other field: the pre-action backup,
a working copy, read-back verification of the tag, the expected-rendering rule for
pHash above, and a new content identity linked to the old one in lineage, since the
file's bytes change. The grid thumbnail and detail preview follow the new content;
both already honour `Orientation`. A rotated copy is no longer byte-identical to its
former duplicates, and history shows that. Where a format's `Orientation` cannot be
written safely, the control is unavailable with that reason. It never falls back to
re-encoding, a sidecar, or a catalog-only rotation a gallery would not see.

**A changed date refiles the photo** to the folder its new date implies,
automatically and with no setting to disable it. Correcting the date *is* the
decision; moving the file is only that decision applied consistently, so a
prompt would ask the user to confirm the same choice twice. It is not a guess —
the correct folder is computed, not judged. And sorting photos into date folders
is what this tool does: if its own output disagrees with the metadata it used to
build that output, the product contradicts itself. Finding the file afterwards
is the log's job, since a refile records both old and new path. Editing and refiling
are one confirmed action with no second prompt. Do not report success if metadata
changed but required placement failed; restore prior state where possible and show
any incomplete recovery.

**Correction is manual; there are no undo operations.** History shows original
indexed information and all subsequent changes, including per-file previous values
for bulk edits. The user consults that evidence and explicitly makes a new edit or
rename against the current state. Later actions may have reused a name or changed
placement, so reversing an old operation is not a supported recovery mechanism.
Preserve full lineage across hash and path changes; see `engine-spec.md` §10.

### 7.6 Re-processing a disordered destination

A read-only destination check may detect missing expected files, unrecorded files,
changed content, possible external moves/renames, or additional exact copies.
Describe these as differences from the catalog, not proof of user interference;
restoring an older database can also explain them. Cache loss is not such a mismatch.

Every destination-mismatch warning directs the user to the same repair workflow:

> **The destination differs from the catalog.** Mount the old destination as your
> source and a new, empty location as your destination. Run Index, then Copy or Move
> to create a newly organized collection with recorded operations.

New processing is logged; it neither reconstructs unrecorded external actions nor
recovers missing photos. Retain the existing catalog as evidence of earlier work.


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

The destination check (`engine-spec.md` §9.1) reads files without modifying them; when it detects a mismatch, present the fresh-destination workflow above.

## 8. Explicitly Out of Scope

* **The engine-side capabilities these workflows depend on** — the destination check, the perceptual pair table, destination deletion, and EXIF writing — are specified in `engine-spec.md` §9, not here. This document covers what the user sees and does; that one covers what the engine must be able to do first. The destination check and renaming are implemented.
* **Multi-user auth/sessions** — not addressed in this spec. Add as a separate concern if the web UI needs to be exposed beyond a single trusted user on a local/private network.

## 9. Catalog Backups

Settings provides **Back up now**, a backup list with timestamp, size and
manual/automatic trigger, and **Download** for keeping a copy outside application
storage. A backup is one consistent SQLite file containing catalog, lineage and
settings. Use a SQLite-supported snapshot, not an ordinary copy of a live WAL database.

**Say how each backup is compressed and how to open it.** A downloaded backup is only
useful if the user can decompress it without this application, perhaps on another
machine. The backup screen therefore carries a standing note naming the compression
format and the library that wrote it, **Zstandard** (https://facebook.github.io/zstd/),
with a link to that page: it is the project's own, and it lists the command-line tool
and the Windows archive managers that open `.zst` files. Each backup in the list shows its own format,
read from the `compression_format` recorded with that backup (`engine-spec.md` §6.5).
Do not use one global setting: backups written before compression existed, or before
a format change, stay in their original format, and the list must describe each file
as it actually is. The note gives the file extension, a one-line decompress command,
and where to get a tool, including for Windows, which ships none of these by default:

| Recorded format | Shown as | Decompress | Where to get a tool |
| :--- | :--- | :--- | :--- |
| none (NULL) | Not compressed: a plain SQLite database, `.db` | Nothing to do | — |
| `zstd` | Compressed with Zstandard, `.db.zst` | `zstd -d <file>` | https://facebook.github.io/zstd/ lists the tools. Linux: the `zstd` package (`apt install zstd`, `dnf install zstd`). macOS: `brew install zstd`. Windows: the `win64` zip from https://github.com/facebook/zstd/releases, or an archive manager the project page names (7-Zip with Zstandard, WinRAR) |

Link the note to the manual restoration steps below, and state that the decompressed
file is the catalog database itself, which can be placed as `ns_sqlite.db` without any
other conversion. Name the library in plain words ("compressed with Zstandard") and
keep the command copyable; do not require the user to know what a codec is. The
uncompressed row stays because backups written before compression existed are
uncompressed and must still be described. There is no compression setting: the
application uses the format chosen below and tells the user which one it used.

**Backup storage is configured through Docker before startup.** A dedicated volume
mount exposes the fixed container path `/backups`, containing multiple catalog
database snapshots, never photo backups. The deployer chooses the underlying storage
independently of `/appdata`. Settings provides backup history and downloads, not a
destination-path display or selector: the application only sees `/backups`. Report
missing or unwritable backup storage using the failure behavior below; do not silently
fall back to storing backups alongside the live database.

The backing directories for `/backups` and `/appdata` must be distinct and must not
contain one another. Different container path names alone do not satisfy this
requirement: two mounts can expose the same underlying directory. Validate this
separation at startup; a detected overlap is a backup configuration error, shown
with instructions to correct the Docker mounts. Do not write backups to an overlapping
location. Container checks have visibility limits, so deployment documentation must
also require non-overlapping host directories; a separate physical disk is optional.

**State prominently:** catalog backups preserve recorded file information, metadata
and operation history, not photos. They cannot recreate pixels or recover deleted
photos. Keep separate photo backups; a catalog backup does not make deletion reversible.

| Trigger | Behavior |
| :--- | :--- |
| Before a confirmed EXIF edit, rename or destination deletion | One automatic backup per user action, including a bulk selection; refiling is part of the edit, not another trigger |
| After Index, Copy or Move records changes | One backup after the job ends, including failed or cancelled jobs with recorded changes |
| Browsing, searching, comparing or thumbnail generation | No automatic backup |
| Edit preview finds no metadata changes or required refiling | No edit execution and no automatic edit backup |
| Back up now | A manual backup. Refused while a job runs, like every other action that writes to the catalog; disable it with the job-running reason (§5.7). A snapshot taken mid-job would record a catalog halfway through the job's changes, and the post-job backup captures the finished state anyway |

If a pre-action backup fails, stop the curation action before changing any files.
Show **“No files were changed because the catalog backup failed.”** Explain the
reason, such as insufficient space or an unwritable backup location, and offer
**Retry** and **Cancel**, with no option to continue without a backup. Retry must
attempt the backup again and revalidate the proposed file changes before proceeding.
If the preview has changed, require the user to review and confirm it again. Cancel
abandons the pending action without changing files.

If a post-job
backup fails, preserve the job's actual result, show a separate backup warning and
offer **Retry backup**. Do not describe completed file work as failed merely because
its backup failed.

**Missed backups after interruption:** on startup, reconcile and report the
interrupted job without restarting its file operations. If its required post-job
backup failed or never completed, report that separately and offer **Back up now**
in the warning. Do not automatically create or retry that backup on startup.
Explain that catalog changes since the last successful backup are not yet backed
up; if there is no successful backup, say so. The user may create a manual backup
or let the next normally required backup occur. A new backup captures the current
catalog, not a reconstruction of its state at interruption. A failed or incomplete
snapshot must not be offered as a usable backup. Subsequent successful backups can
resolve the outstanding warning without erasing the historical failure record. The engine supplies this: `ns_db.unbacked_changes` counts the catalog records no successful backup holds, excluding `Skipped` and `Cancelled` rows because they record that nothing was done, and names the runs they came from and the last successful backup's time. Every engine start logs the same warning when that count is above zero. The API reads the function for the Settings warning.

Keep the **latest 20 automatic backups by default**, configurable in Settings.
Prune the oldest only after a new backup succeeds. Manual backups remain until the
user removes them directly from the mounted backup storage. Backup deletion controls
are out of scope for the UI: users manage files directly, while the application
enforces the configured automatic-backup retention limit. Show count and storage usage; before applying a lower
limit, explain how many automatic backups will be removed.

**Missing backup files:** retain the historical record when a previously recorded
backup is no longer present in accessible backup storage. Show **“Backup file no
longer available”** and disable its download. This does not change the recorded
outcome of the original backup operation. If `/backups` itself cannot be accessed,
report the storage-access problem instead of claiming individual files were deleted.
An unavailable file must not be presented as an available recovery copy.

**Manual restoration only:** provide instructions, not an in-app restore action.
Stop the application container and preserve the current database and any associated
SQLite `-wal`/`-shm` files separately before replacement. Decompress the selected
backup if it is a `.db.zst` (`zstd -d <file>`), place its database at the application's expected database path and
filename under `/appdata`, and verify ownership and permissions. Do not leave old
SQLite companion files beside the restored database. Start the application after
replacement; restoring catalog records does not reverse photo changes or recreate
photos, and the restored catalog may differ from the current destination.

**Compression: Zstandard, level 10, with a frame checksum.** Chosen by measurement on
the maintainer's full-library catalog (524 MB), each result round-tripped byte for
byte, compression single-threaded:

| Codec | Size | Compress | Decompress | Compress memory |
| :--- | ---: | ---: | ---: | ---: |
| gzip -9 | 50.6 MB | 4.3 s | 0.51 s | 19 MB |
| lz4 -9 | 45.5 MB | 0.4 s | 0.26 s | 42 MB |
| bzip2 -9 | 29.0 MB | 21.1 s | 4.95 s | 19 MB |
| zstd -3 | 24.7 MB | 0.3 s | 0.11 s | 39 MB |
| **zstd -10** | **19.3 MB** | **1.2 s** | **0.10 s** | **91 MB** |
| zstd -19 | 16.6 MB | 47.2 s | 0.10 s | 216 MB |
| brotli -q 9 | 16.7 MB | 4.5 s | 0.20 s | 77 MB |
| xz -6 | 16.1 MB | 26.7 s | 0.49 s | 98 MB |
| brotli -q 11 | 14.1 MB | 195.9 s | 0.20 s | 188 MB |
| xz -9e | 13.7 MB | 70.0 s | 0.46 s | 677 MB |

The criterion is efficiency, not the smallest file, because compression runs after
every job that recorded changes while the engine lock is held. zstd -10 is 2.6x
smaller than gzip, 27x smaller than the catalog, and done in about a second; twenty
retained backups take about 390 MB instead of 10.5 GB. Levels 9 to 12 land within
0.5 MB of one another; level 13 switches strategy and took 4.9 s for a larger file.
**Why not a smaller format:** xz -6 saves 3.2 MB per backup for 22x the time, and xz
-9e, brotli -q 11 and zstd -19 save 3 to 6 MB for 47 to 196 s under the lock. **Why not
gzip, the format everything already opens:** 2.6x the size and 3.5x the time.
Zstandard's own tools are free on every platform and linked from the backup screen
above. The engine uses the `zstandard` Python package, pinned in `requirements.txt`
and bundling libzstd 1.5.7; any Zstandard tool decompresses the result.

## 10. Timestamp Display

* **Application history:** job, operation and backup timestamps represent instants
  stored as timezone-aware UTC. Display them in the user's local timezone with a
  clear timezone label. The engine writes every catalog timestamp with its offset
  (`engine-spec.md` §4.3). A value without one comes from an older development
  catalog and must not be presented as UTC.
* **Photo capture dates:** show the recorded wall-clock date/time and its offset when
  known. If no offset was recorded, indicate that the timezone is unknown; do not
  assume UTC or shift the capture date to the browser's timezone. The offset-free
  `date_taken` example illustrates an unknown timezone, not a UTC instant.
* **Folder placement:** use the photo's recorded capture calendar date, so changing
  the browser timezone does not move it across days, months or years. This does not
  change the separate modification-time fallback policy for Undated photos (§3.1).


### Destination history presentation contract

The photo information page follows file IDs and operation participants. A Copy
shows its source origin; a completed new Move shows the same file's location change.
A Move reusing an existing destination shows removal of the source and a link to the
retained destination, preserving both histories. The destination page can list all
contributing source snapshots, including removed duplicates. Unknown creation origin
for a previously unrecorded destination must be labelled unknown, not inferred from
matching bytes. Interrupted Move with both copies remaining is shown as **File
delivered; source not removed**, with the original incomplete operation and a link
to the log. An explicitly requested subsequent Move is separate work.

Current engine delivery relationships are implemented in the shared catalog layer;
interrupted-operation evidence is recorded by recovery (`engine-spec.md` §4.2). The
web presentation remains pending.
