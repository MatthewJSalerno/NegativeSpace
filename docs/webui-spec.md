# Functional & Technical Design Specification: NegativeSpace Web Interface

The shared visual and interaction contract is defined in [UI design standard](ui-design.md).
Appearance uses shared spacing, type and surface tokens with locally served Inter.
Settings starts with Appearance, an immediate, browser-local Cool neutral / Warm neutral preference;
both palettes follow the system light/dark setting, independently of saved engine settings.
It covers controls, keyboard focus, dialogs, help, form validation and loading/retry states.
Desktop browsers are the required target; mobile support is optional. Existing narrow-layout
behavior is documented as implemented, not as a mobile support requirement.

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
|  [ Gallery / Grid ]  [ Split Inspector ]  [ Logs ]  [ Stats ]  [ Settings ]     |
+-----------------------------------------------------------------------------------+
| HTTP REST / WebSockets
+-----------------------------------------------------------------------------------+
|                                 FastAPI Backend                                   |
|  [ Job Control ] ---> [ Engine Subprocess Execution ] ---> [ Log Parser Engine ]|
+-----------------------------------------------------------------------------------+
| SQLite (WAL) / Subprocess
+-----------------------------------------------------------------------------------+
|                                   Engine Core                                     |
|   (ns-engine.py --workers N --exts ex1,ex2 --file-ids-from selection-file   |
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
   python3 ns-engine.py --move --file-ids-from selection-file --request-id request-id
     (or --copy; the API writes the validated selection file)
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
scoped to a specific selection via `--file-ids-from`.

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
  dates show, scrolled to or not), **Unselect all on screen** and **Unselect all**; the two
  on-screen items only while the view holds more photos than the screen shows, counted again
  whenever the gallery changes size (the photo panel opening or closing). Select all takes
  every photo the view shows, however many (`GET /photos/ids`); an item that would do nothing says why.
  Keep the total selected count visible and repeat it in bulk-action previews, including
  metadata edits and rejects.
* **One place per selection** (decided 2026-10-06): a selection holds library photos or
  photos in Rejects, never both, so every action on it has one meaning. The first photo
  ticked sets the place; while anything is selected, the other place's tick boxes are
  disabled, saying "Photos in Rejects can't be selected with library photos. Clear the
  selection first." (or the reverse). Select all and a Shift-click range take the
  selection's place (with nothing selected, the library's if the view shows any) and say
  how many they left out. A selection in Rejects offers **Return to library** first, then
  **Move**, which deletes the rejected photos' originals from the source once each copy in
  Rejects is verified; its review and hover text say so, and that the copies in Rejects
  become the only ones. *Why disabled, not cleared:* a selection built across pages is
  never lost to one stray tick. *Why keep Move for Rejects:* a source that ends empty
  should not need deleting in two places; the warning makes the consequence plain.
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
* **Copy or Move a single selected photo confirms in a dialog**, preserving the
  gallery and Dates/Folders panel instead of switching into selection review.
* **Copy, Move, Reject or Return of multiple selected photos is reviewed first, never confirmed over the photos.** It shows
  every selected photo, whatever hides them, with a bar pinned above them: **"Review before
  copying** · 23 of 25 selected photos will be copied. Untick any you don't want." (one
  count pair, said once; Keep this one, reject the rest reads **"Keeping IMG_0410.jpg** ·
  7 of 9 look-alikes will be moved to Rejects. Untick any you want to keep."), what the
  action does, **Copy these 23 photos** (or Move, Reject, Return) and **Cancel**. The
  similarity view's grouping, threshold and match counts do not follow into a review. The photos can be scrolled, opened and unticked; the button's count
  follows the ticks, and an unticked photo stays on screen. **Why not a dialog:** one
  over the photos hid them and stopped the scrolling the review needs. **Cancel**
  returns to the view it came from, and so does committing. Copy all and Move all still
  confirm in a dialog: there is no selection to review.
* **After a job, stay where you were** (decided 2026-10-06). Starting a job clears the
  selection and leaves the gallery where it was. The finished banner of a job that acted
  on photos (Copy, Move, Reject, Return to library, Rename) offers **Show these photos**,
  on every page, and so does each such job in Logs (**Show these photos in the library**,
  beside Retry): the gallery then shows the photos that job recorded, wherever they are
  now, library or Rejects (`view=job&run=<id>`, in the address). Its line reads "The 400
  photos in Copy #3 · 398 of 400 files copied · 2 skipped · Back to results" ("their status
  updates when the job ends" while it runs), and each photo's badge shows where it stands.
  It opens with no search, dates, types or folders, so none of the job's photos is hidden
  by a filter left on; then every filter narrows it ("Showing 37 of 400 photos"), and
  Select all, ticking and the selection bar work as anywhere. **Back to results** restores
  the filters it opened over; a view button leaves it with the filters as they are. With
  nothing ticked, the selection bar is hidden. *Why not land on the job's photos:* it
  took you from where you were after every job, with the page's controls greyed out,
  while most jobs need no follow-up. *Why not a tab or chip for the job:* the banner and
  Logs already lead there.
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
  (**“Showing 412 of 1,160 photos · only June 2023, 2019 · Select these 412 · Show all
  dates”**; **Select these**
  selects what the filter shows, as Select all in this view does. The boxes themselves only filter: unchecking a month to look
  elsewhere must never change the selection). The tree's own counts ignore it, so an
  unticked month keeps its number. On a
  narrow screen the panel opens from a **Browse** button.
* **Browse by Folders or Dates:** under Types, **Browse by [Folders | Dates]** chooses the
  tree below it; **Folders** is the default, and the choice is remembered per browser (a
  filter in the address for the other tree shows that one). The **Folders** tree is the
  **source's** folders, built from catalogued paths (`GET /api/v1/photos/folders`), with
  counts for the current view, search, dates and types, and the same **Show only** boxes: a
  ticked folder takes its subfolders, which show ticked and cannot be unticked on their
  own; a folder with only some subfolders ticked shows a dash. A chain of folders each
  holding one folder and no photos is one row (**"Camera / Nikon D750"**); the photos
  directly in the source folder are a last row, **Files in the source folder**. Folders
  combine with dates and types and are named in the filter line (**"Showing 318 of 3,366
  photos · only Family scans · Select these 318 · Show all folders"**). *Why the source
  tree, not the destination's:* the destination is `YYYY/MM/DD` and `Undated/<year>`, which
  the Dates tree already shows; the source's folders are what the user knows, every photo
  has one (a moved photo under the folder it came from), and they are what a job can act
  on. The left panel's edge can be dragged, or moved with the arrow keys, since folder
  paths can be wide; a name wider than the panel ends in "…", whole on hover.
* **A folder's Copy or Move:** with exactly one folder shown, **Jobs ▾ → Copy ▸ / Move ▸
  → this folder: Family scans (318)** takes that folder and its subfolders, however many
  photos: the engine is given the folder (`--source-subdir`), not a list of photos. The count
  is what the job would take, whatever the view. Otherwise the item stays in the menu, disabled, and says why: **"Show one folder
  to act on it."** with several ticked, **"Show a folder in the Folders tree to act on
  it."** with none, and the files directly in the source folder, which are no folder of
  their own, are selected instead. It is confirmed as Copy all and Move all are, and a
  Retry preserves that folder scope (§5.3).
* **Types:** above Dates, folded by default to one line that names any type checked (a
  type filter in the address opens it; open or folded is remembered per browser): the
  file types the library holds (by extension), with counts
  for the current view, search and dates, and the same **Show only** boxes; none checked,
  the default, shows every type. A checked type stays listed at 0 so it can be unchecked.
  Types and dates combine, and the filter line names both (**"Showing 42 of 1,160 photos
  · only 2019, HEIC · Select these 42 · Show all dates · Show all types"**). **All
  photos** clears them too.
* **The view buttons count what the filters find; the filter line names the library.**
  With a search, dates, types, folders or No capture date on, each view's number is how
  many photos that view would show under them, so the number on a button always matches
  what clicking it shows, and the line above the gallery gives the library's size:
  **"Showing 9 of 1,160 photos · only 2022, 2023"**. **Why not the whole library on the
  buttons:** a search for one name still read "Rejects (1)" or "Organized (1,160)", and a
  view opened from that number then looked empty or wrong (maintainer, 2026-10-01).
  The Stats page's formats open the Library filtered to that type. Going to a date the filter hides
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
In-app links and browser Back/Forward apply the destination URL even on the same
screen. The Library link resets browsing filters and closes the Inspector; within
the mounted Library it keeps the explicit selection but exits selection-only or
transfer-review mode. History restores the recorded page and photo, not an exact
scroll pixel position or a transient review. Logs links replace the log's filters
and expand the single linked job. Recording local control or scroll changes in the
address does not itself count as navigation or reset the current selection.

**No capture date** is a quick filter beside the views, with its count. It shows the
photos whose EXIF has no date taken, which are filed under Undated by their file's
modification date, counted in the current view. It combines with the view and the
search; the views' counts ignore it, as they ignore every filter, and the filter line says
how many are shown. Each view button keeps its width whatever its count, with room for
**(999,999)** in even-width digits, so switching views never moves them. Every tile
preserves the search text, including **No capture date** and **All photos**.
**All photos** clears No capture date and the date, type and folder filters, but
retains the search; it is not shown as chosen while a filter or search narrows the
gallery. The other views keep the filters, to narrow within a view.

**Planned: views named by where a photo is** (decided 2026-10-05). Today's views
(All photos, Not yet organized, Organized, Has similar photos, Suspicious dates, Rejects)
mix places with ways of looking, and **All photos** mixes the source and the library, so
a user cannot tell what is where. They become four places:

| View | Holds | Replaces |
| --- | --- | --- |
| **Library** (the default) | Photos in the destination's `library/` | Organized |
| **To organize** | Photos in the source not yet in the library | Not yet organized |
| **Rejects** | Photos in `rejects/` | Rejects (unchanged) |
| **Needs review** | Photos waiting on a decision (§7.9), including source photos that failed and held small images | (new) |

A copied photo belongs to the Library; its untouched original in the source is not
counted again. **All photos** goes: it only ever meant everything mixed together.
**Has similar photos**, **Suspicious dates** and **No capture date** stop being views and
become filters within a place ("Library · has similar photos"), as No capture date
already is. *Why:* the view buttons then answer one question, where is it, and drop from
six to four. *Still to settle when building:* how the filters are offered, and what the
first visit shows before anything is in the library (To organize).

**Main-page browsing:** default to newest first by recorded photo date, clearly
distinguishing filesystem fallback dates from capture dates; offer size sorting.
Search matches current and original filenames, including names of related removed
duplicates, without merging their histories. Folder paths are not filename-search
matches. Distinguish not-yet-organized and organized photos; when a search has matches
in the other view, show its count and a link rather than implying no matches exist.
* **No selection size limit** (decided 2026-10-04): a selection can hold every photo in the
  catalog. The API passes it to the engine in a validated file (`engine-spec.md` §4.1), never
  on the command line, whose length is limited; the engine records it with the job, so each
  photo's lineage shows the jobs it was chosen for. The bounds are the catalog (never more
  ids than photos) and a 16 MB request, about 1.5 million ids. *Why not a higher fixed
  limit:* every limit needs messages and a way around it, and the catalog's size is already
  the natural bound.
* **Folder selection:** users can select a source folder (recursive) and scope the operation to everything currently indexed under it. This maps directly to the engine's `--source-subdir <path>` flag (`engine-spec.md` §4.1). Symlinks are excluded automatically, inherited from the original Index that populated the catalog (a symlink was never indexed as a row in the first place). If a folder hasn't been indexed yet (zero matching rows), show *"No indexed files found under this folder — run an Index first."*
* **Actions on a selection:** the selection bar's **Copy (n)…** and **Move (n)…** (§4.1); on a
  folder, Jobs' **this folder (n)**, from the Folders tree (above).
* **Targeted Execution:** Individual selections reach the engine as a selection file (`--file-ids-from`, its ids recorded with the job); folder selections use `--source-subdir <path>`. These are mutually exclusive targeting mechanisms in a single job — pick one per submission. IDs (not raw file paths) were chosen for the individual case specifically because a database primary key is unambiguous and doesn't depend on path strings staying identical between when the frontend fetched the catalog and when the operation actually runs — and it keeps one targeting implementation rather than a parallel web-only code path, which is what makes the engine directly runnable for debugging and development (see §1).

---

## 3. Dedicated Settings Management (`/settings`)

A dedicated Settings view provides central management of engine parameters, persisted
in the same SQLite database as catalog/history and passed to engine instances on
startup. Settings must work before the first Index: initialize tables and defaults
without scanning or touching photos. Saving validates and persists values; startup
must not reset saved preferences. The browser uses the API, never SQLite directly.
One consistent database backup includes settings and lineage. The settings writer
boundary is defined in §6.1; no second database is required.

**Settings are in four groups:** **Appearance** (the palette), **Files** (file types;
the Rejects reminder, §7.8; with Needs review, the small-image size, §7.9; with the
editor, where edits are saved, §7.5), **Backups** (how many to keep, the list, Back up now, how to
restore) and **Performance** (worker processes; the thumbnail cache, §4.2.1, not yet on screen). In Settings they are tabs with one **Save
settings** for all of them, so switching tabs loses nothing; a tab with unsaved changes
shows a dot, and a save with an error on another tab opens that tab at the field.

**First run shows the settings as the page itself**, before the library exists, and
says prominently that these are starting values, changeable at any time from the gear
icon in Settings. Without that, a user can take the screen for the only chance to set
them. It steps through the same four groups ("Step 2 of 4 Files", **Back**, **Next**),
one per page so each fits without scrolling; Next checks only that step, and nothing is
saved until **Save and continue** on the last. Saving lands in the Library, where **Index
your library** waits, whatever page an earlier session left in the address bar. After
first run, Settings opens as a window over the current view.

**Startup without a usable catalog:** distinguish a missing database from access
errors and from an invalid or corrupt database. Do not silently replace an existing
database or interpret a storage error as a fresh installation. If no database is
found, show **“No catalog found. If this is your first time using NegativeSpace,
create a catalog to get started. If you’ve used it before, check the folders below,
or recover your catalog from a backup.”** Offer **Create new catalog** explicitly;
only after that choice initialize the database and defaults, without running Index.
Verify application storage is accessible and writable before creation, and never
overwrite a database that appears between the check and confirmation.

In startup diagnostics and recovery guidance, show where the catalog (`/appdata`) and its
backups (`/backups`) are looked for, and say what those are: **paths inside the container,
not on the user's computer**, each a folder the user chose at setup (`APPDATA_DIR` and
`BACKUP_DIR` in `docker/.env` with the included compose file, or `docker run -v`), to be
checked for naming the same folders as before and being reachable. *Why:* a bare
`/appdata` sent an inexperienced user searching their disk for it. Their host locations
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

**Undated photos are a Needs review reason** (decided 2026-10-05, §7.9), not a tab of
their own: "No capture date", with **Use this date** and **Choose another**, the photo
carrying on under `Undated/` meanwhile. Its filters split photos with other date clues
but no usable capture date, photos with other metadata but no usable date fields, and
photos with no readable metadata. Classification uses embedded metadata rather than
engine-added bookkeeping fields. Each note **suggests** a date with where it came from,
never applied without the user:

* **from the name** (`IMG_20190704_153012.jpg`, `2019-07-04 Beach.jpg`), often exact;
* **from the folder** (`Summer 2019/`, `2019/07 July/`), usually a year or month;
* **from a look-alike** that has a capture date (§7.4), such as the original a copy was
  downloaded from;
* **by hand, in bulk:** a batch set to one date keeps each photo's own time of day (§7.5).

Answers within the reason are made in bulk, a batch at a time, through the editor. Show original paths/names and clearly label
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

**A failure count says why on hover.** Hovering (or focusing) a finished job's result
lists why its files failed, each reason with its count, the file paths removed so reasons
group (**"Why they failed: Permission denied: 2"**); the Logs page's job lines do
the same, and a Failed photo's badge in the gallery gives its own latest reason.

**A Move that could only copy says so, without stopping to ask.** When a Move cannot
delete an original (a read-only source, a permission), the engine records the verified
copy it made (`engine-spec.md` §4.2) and the screens name it **Copied only**, in the
warning colour: never Moved, never Failed. The result reads **"Move finished, originals
kept · 0 of 4,836 files moved · 4,836 copied only: the original could not be removed"**,
and its hover gives the reasons (**"Why originals were kept: Read-only file system:
4,836"**). The log has a **Copied only** status with its own filter, a hint that the copy
is at the destination, and **Move the n copied-only photos again** to finish the job once
the source can be written. The gallery badge reads **Copied only**, with the reason
on hover; the Inspector's history and the lineage tree say **original kept**. *Why not
ask on the first failure:* nothing is lost either way, and a question nobody is there to
answer would stall an overnight job; a clear account afterwards serves better.

A finished job's banner explains its skips, grouped by the reason each photo recorded,
for example **"5 skipped (3 copied by an earlier job, 2 duplicates: the same content is
copied once)"**. The API groups them from the engine's reason text (`webui/catalog.py`).

**Which build is running** shows at the top right, beside Settings, on every page and on
the first-run and catalog-problem screens: **"v0.1.0 · main · 2c4728f"**, the release in
`VERSION` and the branch and commit the image was built from, so a report names the
exact code. `VERSION` is raised with each merged change that alters behaviour.

Actions are in two places (decided 2026-10-05), the pattern of Google Photos, Apple Photos
and Gmail, so that no menu has to adapt to what is selected:

* **The selection bar**, in the sticky top bar while photos are selected: "4 photos
  selected", then only the actions that apply to them, each with its count:
  **Copy (n)…** and **Move (n)…** by the engine's rule (`ns_db.TRANSFER_ELIGIBLE`),
  **Reject (n)…** for photos in the library, **Return to library (n)…** for photos in
  Rejects (§7.8). A selection is one place (§2): library photos get Copy, Move and Reject;
  photos in Rejects get Return to library first, then a Move that warns what it deletes.
  Then Show only selected (or Back to results) and Clear. An action that
  takes none of them is absent, not disabled; each asks first, through the same review.
  While a job runs the actions wait, saying why.
* **Jobs ▾**, after **Library** on the Library page only: the library-wide jobs,
  **Index**, and **Copy ▸** / **Move ▸** of **this folder** (the one folder the Folders tree
  shows) and **all (n)**. *Why "Jobs":* it holds exactly the jobs, and pairs with Logs,
  which lists them; "Organize" sat over the Organized view and would clash with To
  organize, and "Actions" would overlap the selection bar. Logs and Stats have no menu; Logs offers
  **Run an Index** where a failure needs it.
* *Why the top bar, not a floating bottom bar:* the selection count is already read there,
  the bar stays in view, and a bottom bar would cover the last row of photos.
The toolbar's second row holds the views,
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
Its maximum width reserves the filters' chosen width, both resize handles and at
least 420px for the photo listing. The Inspector keeps at least 320px. Restored
widths are bounded to the current layout, and resizing the browser or filters
recalculates the limit. If a desktop window cannot fit those minimums, the layout
overflows horizontally instead of crushing the controls.
Inside the Inspector, a visible grip between the preview and the file details resizes
their share of space: vertically when details are below, horizontally when beside.
Drag it or focus it and use the corresponding arrow keys (5 percentage points per
press); Home/End select the 20%/75% limits. The preview share is remembered in the
browser independently of the overall Inspector width.

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
    `Cancelled`, `Found_At_Destination`, `Rejected` (in Rejects), `Rejected_Copied` (in
    Rejects, original kept) and `Returned` (returned to the library).
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
  Restarting the app container starts the web API; it does not resubmit Index,
  Copy or Move. The API shows recorded job state, and the engine reconciles pending
  operations when a subsequent job runs. If the container's startup command has
  been overridden to run the CLI directly, restarting reruns that command; do not
  present such a restart as a recovery-only action.
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
  **View job history**, **Check again**, and **Retry same request** without claiming
  it failed. That explicit retry preserves the request ID and original payload;
  it cannot submit a second job for the same accepted request.
  Association is by request ID, never by timing or mode: the API passes each
  submission's ID to the engine as `--request-id`, and the engine records it with
  the run before any file work (`engine-spec.md` §4.1). A `job_requests` row for the
  ID identifies the job. No row means acceptance is still unknown: even a free lock
  cannot prove a delayed HTTP request will not subsequently arrive. Duplicate
  delivery of one ID never runs twice. The browser keeps the pending request in
  session storage across reloads and resumes lookup, never automatic resubmission.
  New submissions in that tab are blocked while unresolved; other tabs have their
  own IDs. A submission-status notice (also inside a busy confirmation dialog)
  links to the exact recovered run rather than assuming the newest job is its own.
* **Lost response after confirming a photo action:** use **“Checking job status…”**
  for rename, EXIF edit, reject and return as well. Look up the recorded job/action,
  including completed actions, and display its recorded outcome with **View job log**.
  This is a status/history lookup, not a new inspection of files to infer whether
  changes were applied. Show recorded per-file outcomes for partial completion.
  If the submitted action cannot be identified, state that its status is unknown
  and offer job history. Never automatically repeat the action. Request association
  must cover curation actions as well as Index, Copy and Move.

### 4.2 Split-Screen Photo Inspector Panel

Opening a photo from Logs locates its page and reveals its highlighted gallery card.
During in-app navigation, photo links reuse this tab's most recent Library filters and ordering. A photo outside
that scope offers **Show in gallery**, a temporary single-photo view with **Back to
results**; the original filters and explicit selection are preserved. Inspector
previous/next follows the active ordering, including page boundaries, and scrolls
only when the target card is offscreen. Clicking a gallery card does not reposition
the gallery, and later manual scrolling is not forced back to the Inspector photo.
Position lookups return rank and neighbors without downloading earlier pages.
Failed lookups offer a retry while leaving the Inspector open.

History's **Open in the log** and **View lineage tree** actions share text size and
alignment, retaining their link and button semantics respectively.
Clicking an image opens a right-side 50% detail panel. **Photo information** is the
default tab outside Has similar photos; opening a gallery card in that view selects
**Similar photos**, which holds the matching controls and thumbnails (§7.4).
Both tabs share the reference preview and its resize divider. The active tab and
chosen match threshold remain selected when navigating to another photo.

**The file's modification time** is the time the file carried when the first Index read
it, not a date the photo was scanned; its label says so on hover (**"As recorded when
NegativeSpace first indexed this file"**). For a photo with no EXIF date taken, one short
line says what it is used for: **"* Files it under Undated: no EXIF date taken."**

**History in the panel, lineage in its own window.** A **History (n)** section under
**File** shows the latest three events as a small timeline, with two links: **Open in the
log** and **View lineage tree**; each event also opens the tree. **Why not every event in
the panel:** it crowded the photo's details; the full record is one click away.

**The lineage tree** (`GET /photos/{id}/lineage`, §6.3) is a window of its own: one node
per file (the source, each copy made from it, each exact duplicate), each with its
presence and the steps that happened to it. Each step appears once, on the file it
produced (a copy's **Copied here** on the copy), else on the file it acted on. A
duplicate's path opens that photo; a step's job opens the log on that job for this photo;
a failed step opens to its recorded reason and **Retry this photo**; hovering or focusing
a path shows its size, content fingerprint and whether it matches, and when it was
recorded. Escape closes the window only, not the panel behind it.

**Show all metadata.** The Index records every tag ExifTool reads (Pillow's when ExifTool
finds nothing), not a curated subset; the Inspector's fields are a few of them. A folded
**Show all metadata (n tags)** inside **Photo EXIF information**, under the fields it
extends, lists every one by name, with a
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

**A photo emptied from Rejects keeps its info screen and lineage.** It leaves every
view (§7.8), but its info screen stays reachable from log links and its lineage:
**Rejected; since emptied from Rejects**, the last recorded metadata and location
(labelled historical), original source Index information, and the full recorded
sequence of actions and before/after values. Emptying must not cascade away these
records or break history links. There is nothing to return, so no Return or edit
controls. The records allow its metadata and naming/location history to be
reconstructed manually; they do not recreate the photo's pixels.

**The photo info screen is the complete recorded history for that file.** Clearly
separate **Current metadata**, **Original source metadata at Index**, and **History**.
The original view includes the preserved source filename/path and filesystem
snapshot as well as captured metadata; later edits or rescans must not overwrite it.
History shows every recorded change across jobs: Copy, Move, rename, metadata edits,
refiling, rejects and returns, plus failed attempts and reconciliation outcomes. Each entry
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

**Content already catalogued is a duplicate.** A file arriving with content the catalog
already holds, another archive's copy or a file put back after a Move, is a duplicate of
that photo and a branch of its lineage tree; the photo keeps its own history and status.
**Content the user rejected stays out of the library:** an identical file arriving later
is a duplicate of the rejected photo, even after Rejects was emptied (§7.8), with its own
Index information and history; it is never labelled a restoration.

**Every photo info panel provides a History / View logs action.** It opens all
recorded operations associated with that photo across runs, not just its latest
status or most recent job. Include the original source Index information, copies,
moves, renames, metadata edits, rejects, returns, failures and recovery records where
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

When a job finishes, the mounted Inspector refreshes its photo details and recent
history without closing or resetting a healthy preview. The gallery retries failed
grid images once per completed-job refresh; healthy images are retained. A persistent
miss keeps its reason placeholder without continuous retries. Retrying an image
request does not rebuild a genuinely missing cache file.

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
* **Not yet on screen** (the engine side is built): the panel below, and API routes to
  start a rebuild or free previews. Today `--rebuild-thumbnails` and `--clear-previews` run
  only from the command line. **It goes in Settings › Performance** (decided 2026-10-05),
  beside the worker setting, as backups sit in Settings › Backups: thumbnails exist to make
  browsing fast, and clearing or rebuilding them is occasional housekeeping. Stats'
  Catalog health keeps the sizes and links to it (**Manage thumbnails**).
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
EXIF edits, Reject and Return to library when the destination cannot be accessed or
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

**Index file-type accounting** *(recorded by the engine; not yet on screen)*: show a summary such as **“15,000
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
and covers that job and every earlier one. The Logs page has the Library's top row
without **Jobs**, whose jobs belong with the photos; the page links never move. The
active filters are named in one line with one reset (**"Showing: job #3 · Failed ·
“photo-00” · Clear all filters"**). An open job's entries load in batches of 100 as the
list scrolls, and the job's header line, with its collapse arrow, stays at the top
meanwhile. **Statuses are checkboxes, one or many:** every one ticked, the way the log opens
on its own, means no status filter; a link from a message (**View failures**) ticks only
what it names. Each has its count and an **only** link to narrow to it in one click;
**All statuses** ticks every one again, and the last ticked box cannot be unticked, since a
log of no statuses shows nothing. *Why not buttons:* a row of toggle buttons grew crowded
and did not say whether it meant one status or several. The Inspector's
**Open in the log**, under History, opens the log for that photo. Each failure carries a plain hint drawn from its
recorded reason, and **Retry**, inside the job it belongs to, runs the same mode again over the photos behind
that job's shown failures, however many, and says what it did beside the button. A Move's
retry takes its copied-only photos too, so nothing is left out; a selection's retry leaves
out rows settling earlier jobs' work, so it names only photos the selection held.

A searchable table logging every operation performed by the engine:
* **Columns:** Timestamp, Mode (`MOVE`/`COPY`), Source Path, Destination Path, Status (`Completed`, `Copied`, `Removed_Duplicate`, `Found_At_Destination`, `Failed`), and System Error Message.
* **Controls:** Filter by photo lineage, date, status, run, or free-text search;
  CSV/JSON export. The photo info page opens this view scoped to the selected
  photo's full history, with access to the surrounding run.

**Filtering by run is what two other screens link into**, so it is a first-class filter rather than a search convenience: the failure banner links here scoped to the most recent run, and the Dashboard's coverage message (§5.9) links here scoped to *every run since the last complete scan*. The filter therefore accepts a set of run ids, not only one.

### 5.5 Job Outcome Is Derived, Not Read From `runs.status`

**`runs.status` describes the run's lifecycle, not whether the work succeeded.** A run that reaches the end of its file loop is recorded `Completed` even if every single file in it failed. That is accurate for what the column means — the process ran to completion rather than crashing, being cancelled, or aborting on a pre-flight check — but it is the wrong thing to put in front of a user on its own.

**Safety questions keep their original job scope.** The finished-job banner on
Library and Logs shows the latest job's unresolved empty-source or network-Move
question. Empty source offers retry after reconnecting, an explicit confirmation
that the source really is empty, or Leave unchanged. Network storage recommends
Copy instead, offers Move anyway with an explicit confirmation that the share uses
synchronous durable writes, or Leave unchanged. Action dialogs repeat the original
selection/folder/whole-source scope; the server reconstructs it from that run, not
the current gallery filters. Leave unchanged starts nothing and dismisses the
banner without claiming the issue was resolved. A new ordinary job never inherits
these permissions. Old questions cannot be answered after another job has started.

For example, a `--copy` whose every source file is unreadable fails every file and still reports:

```
Run #2 finished with status: Completed
```

Surfacing that verbatim would show a green **Completed** for a job where nothing succeeded, and the user would have to open the Error Center to discover their entire operation did nothing.

**The API derives outcomes from classified operations, not just `runs.status`.**
Present three separate groups, each linked to its detailed logs:

* **Requested work:** outcomes for the current job's requested photos. Copy/Move
  includes prerequisite scan failures that prevented delivery, in both the failed
  count and requested total. Successful scans do not also count as successful transfers.
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
| failed > 0, and something succeeded, was skipped or needed nothing (an Index's unchanged files) | **finished with failures** — surface the failed count and link the Error Center |
| a Move with copied-only photos, failed = 0 | originals kept (warning) — the copied-only count and its reasons, never a success or a failure |
| failed > 0 and nothing else | **finished, nothing succeeded** (red) — the job ran to its end, so never "failed" |
| no changes, no failures or scan issues, and run completed | neutral completion with prominent counts and skip reasons; not an error |
| `runs.status` is `Cancelled` / `Interrupted` / `Failed` | that status wins (`Failed` reads **stopped by an error**: the job did not finish); still show counts for what was done before it ended. `Interrupted` has no end time; show its duration as unavailable (§4.1) |

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

* **A selection travels in a file, never on the command line** (§2). The API names it from the request ID alone (already limited to letters, digits, `_` and `-`), never from anything the client sends as a path, and writes it under application data in a folder only the application's user can open (`0700`, the file `0600`): created fresh, never through a link, flushed to disk and renamed into place whole. The engine reads only a plain file, under a size cap, written for its own request, whose count and checksum match, every line one id, ascending, no repeats; and refuses the whole job, recording nothing, if any photo is no longer catalogued in this source. The checksum catches a cut-off or damaged file; it is no defence against someone who can write application data, who could change the catalog beside it anyway. The file is removed once the engine has recorded the selection with the run.

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
EXIF-edit, reject and return actions. Show **“Photo changes are unavailable while a job
is running.”** Browsing, photo history and settings remain available; settings
changes apply only to future jobs (§3). Reject conflicting submissions at the API
as well, including races between tabs, rather than queuing them. When the active
operation ends, controls become available again; nothing starts automatically.
The user must initiate and confirm a new action against current state. Curation jobs
(rename, reject, return to library) take the same lock as any other job.

Only one engine process may run at a time — see `engine-spec.md` §4.1/§7 for the engine-level guarantee (an OS-level `flock`, held for the whole process lifetime, released automatically even on a hard `SIGKILL`). This is enforced in two layers, not one:

* **Fast pre-check (FastAPI):** Before spawning the engine, `POST /api/v1/jobs/start` probes the engine's own lock: a non-blocking `flock` on `<base>/engine.lock`. If the lock is held, an engine is running, and it returns `409 Conflict` immediately — no subprocess is spawned, and the response includes the newest active run's (`Preparing`, `Running` or `Cancelling`) `id`, `mode`, and `started_at` so the frontend can show *"A Move operation is already in progress (started 2 minutes ago) — wait for it to finish or cancel it."* The Rescan/Move/Copy buttons should all be disabled client-side whenever a job is known to be active, so this 409 is a backstop for races (e.g. two tabs), not the primary UX.

  The pre-check must not decide from an active `runs.status` alone. A row orphaned by a crash stays active until the next engine run reconciles it, so a pre-check that trusted the table would refuse to start that very run: every job blocked, permanently, by a process that no longer exists. If the probe *acquires* the lock, any active rows are stale, and the engine about to be spawned marks them `Interrupted` during its own startup. Two requests can still race between the probe's release and the engine's own acquisition. The engine's lock decides, and the losing engine exits non-zero with its FATAL message, which the API reports as a 409.
* **Authoritative guarantee (engine):** The `flock` in `engine-spec.md` §4.1 is what actually prevents data corruption if the fast check above is ever wrong or stale — see the FastAPI-restart case below. Even if FastAPI's own bookkeeping says "nothing running" incorrectly, a second engine process attempting to start will still be refused by the lock and exit cleanly with a logged error, never silently racing a real in-progress run.

Before run acceptance, a child may still be waiting to read its selection, without
holding the engine lock yet. Selection publication and cleanup therefore use a
separate inherited OS lock (`api-spec.md` §5), which the child lets go of once it has
read its selection. API startup preserves these inputs while a submitting process or an
unread child holds that lock. Once all holders release it,
startup or the next selected submission can reclaim abandoned inputs. No age or
unrecorded-run assumption establishes abandonment, and same-ID retry remains safe.

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

**Built on the Stats page** (`GET /api/v1/stats`, reached from an icon beside Settings):
these three figures, the coverage line, duplicates by top-level folder of the source (for a
library fed as archives in their own folders, how much each archive duplicated), and the
rest of the library in figures (formats,
cameras, resolution, dates, activity, catalog health), each leading to the photos or log
entries behind it. Figures that need unbuilt features say so rather than guess. The
tiles across the top are Photos, Organized, No capture date, Duplicate copies, Failed
attempts, Last backup and, two columns wide, Rejects (§7.8). **A share never rounds to all or nothing:** 100% means every
photo and 0% none, so 4,681 of 4,684 reads 99.9%, not 100%.
Camera and lens identifiers are displayed and grouped as text, including numeric
metadata values; missing or empty identifiers are omitted without altering stored metadata.
The Dates chart stays within its panel: long year ranges scroll horizontally, with
readable year labels and keyboard-accessible year links. The complete counts remain
available under **As a table**.

**Planned: the Dates chart stays readable whatever the dates** (decided 2026-10-05). A few
impossible years (year 1, a camera clock set to 2218) currently squash the chart: the
first screenful shows only stray early years with bars too short to see, and the real
spread of the library is scrolled out of sight.

* **Its own full-width row** below the tiles, instead of one of the three panels, so many
  years fit side by side.
* **Suspicious years are set apart, not plotted:** years the Suspicious dates view flags
  (before 1800, or more than a year ahead) are counted in one labelled bar at each end,
  "before 1800: 3", "future: 6", linking to that view, so they neither stretch the axis
  nor hide the real years.
* **Every year between the earliest and latest real year is shown,** an empty year as an
  empty slot, so gaps read as gaps; the bars scale to the busiest real year.
* Year links, keyboard access and **As a table** stay as they are.


"How much space are my duplicates wasting?" is a headline figure for the Stats page, and the catalog already answers it without any engine change. Deduplication acts on two different volumes, though, and conflating them produces a number that is wrong in whichever direction the user's mode does not apply:

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
Index information and distinct histories for identical copies and emptied rejects, all
in the one catalog database. The Error Center and photo history read it through
`operation_files` (§6.3); `photos` rows and hash-only joins do not carry that contract.

The practical consequence for the UI: rebuilding loses recorded history and settings even when the library has only been Indexed or Copied. After Move, original source information may no longer be recoverable from files either. Do not describe a rebuild as lossless or use the presence of `Removed_Duplicate` rows as the only warning criterion. Offer a backup first (`--backup-now`, §9) — a plain file copy of a WAL database is not a consistent backup — and treat a JSON export of `runs` and `operations` as the format for reading history outside the app or carrying it across a schema change, not as a substitute for the database backup.

**Status values are enforced by the database, not by convention.** Each `status` column carries a `CHECK` constraint listing exactly its vocabulary, generated from the same tuples the engine uses. An API write of `'copied'` or a filter on `'Complete'` fails loudly at write time rather than silently disagreeing with the engine — a mismatch whose only symptom would otherwise be photos that never appear. Treat the constraint as the contract and do not hardcode a parallel list; read it from the engine's constants or from `sqlite_master` if the API needs to enumerate.

**The API layer must use engine-owned schema initialization and validation.**
`ns_db.py` stamps schema version 20 and refuses incompatible catalogs. Settings saves
use its scoped revision-checked functions; the browser never accesses SQLite.
Preserve an incompatible catalog and explain the version mismatch. Index cannot
repair a schema mismatch or reconstruct lost history; do not suggest deleting a
user catalog. An older version requires a fresh development catalog without discarding
the old one (`engine-spec.md` §6.5).


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

**The implemented API is specified in [`api-spec.md`](./api-spec.md)**: catalog status and creation, settings, the gallery listing, timeline and date filter, selection by id and Select all, photo details, lineage, thumbnails and previews, starting and cancelling jobs, runs and their derived outcome, the live job feed, the log, catalog backups, and what the interface remembers. CI keeps it in step with the routes in `webui/app.py`. What follows are endpoints designed here and not built yet; each moves to `api-spec.md` when it is.

The run history and the Error Center's failures are built: `GET /api/v1/operations` with
`run` and `status` filters (`api-spec.md` §5a).

**Built as the `duplicates` part of `GET /api/v1/stats`** (`api-spec.md` §5c), which backs
the Stats page (§5.9). Three separate figures, each naming the volume it applies to: what
Move could still reclaim from the source (`move_would_free`), what past Moves already
reclaimed from it (`freed_by_moves`), and what was never written to the destination in
either mode (`saved_at_destination`, counted only once the original is delivered). They
overlap by design, a moved duplicate appears in both of the last two, so they are returned
separately and never totalled. `coverage` says how current they are, by these rules:

**Completing is not the same as covering.** An Index whose source was detached finds nothing, correctly refuses to condemn the catalog, records a run-level `Failed` operation — and still ends `Completed`, `mode = 'INDEX'`, untargeted. It satisfies every criterion above except the one that matters, having established no new coverage at all. An Index that could not read part of the tree has the same shape. Such a run must not establish fresh coverage, including when it repeats an unresolved empty-source question.

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

`photo_id IS NULL AND status = 'Failed'` is precisely the run-level failure shape already written by the empty-scan refusal and by an unreadable folder (§5.3), and every refused run records it even when the attention issue already exists. No new column is required; `idx_operations_run` backs the lookup.

**Return the excluded runs, not just the date.** Suppressing a scan silently would trade a wrong date for a missing one. Alongside `last_indexed_at`, report how many Index runs since then failed to establish coverage, and the run ids the UI needs to link into Logs (§5.4):

* `coverage.established_by_run` — the run the date came from, or `null`
* `coverage.scans_with_issues_since` — count of untargeted Index runs after it that recorded a run-level failure. Deliberately **Index runs only**: a failed Move says nothing about scan coverage, and the failure banner already covers that case. Conflating them would make a delivery problem read as a staleness problem.
* `coverage.run_ids_since` — every run after that date, whatever its mode, since the user clicking through wants to see the whole gap rather than only its failures.

**Extension scope counts too.** An Index run with a narrowed `--exts` scans the full tree, succeeds completely at a smaller job, and records no failure, having examined only some file types. Its effective extension set is recorded in `run_configs` (`engine-spec.md` §6.5), so the API can see it: an Index whose effective extensions omit a supported type does not advance the coverage date, and is listed in `run_ids_since` like any other later run.

`GET /api/v1/photos?status=Failed` remains available for filtering the catalog, but it is not the Error Center's data source: it misses any failure whose photo is not currently `Failed`. "Retrying" is selecting the associated photo IDs and calling `POST /api/v1/jobs/start` again with the same mode — no separate retry endpoint, per the design note in §5.3.

---

### 6.3 Reading a photo's history across identity changes

**A history view keyed on `photos.id` alone will silently drop the older half of a
photo's past.** It is the single most likely way a correct catalog gets presented
incorrectly.

`photos` holds one row per source file, and a path is unique only among files still in the
source. Identity lives in `files`, bound to the photo row through `photo_files`, which never
rebinds. A file put back at a path whose source a Move or duplicate removal consumed is a
**new photo row with a new identity**, a duplicate of the photo it matches; the consumed row
keeps its immutable `source_snapshots` row, its observations and every `operation_files` link.

A history keyed on `photos.id` alone still misses part of a photo's past: the copies made
from it and its duplicates live under other rows. **So gather the photo's whole lineage**:

1. Resolve the photo's identity through `photo_files`.
2. Walk `file_origins` from it: the reverse lookup reaches everything created from it.
3. Add every photo row with the same content (its exact duplicates, however they arrived),
   and their identities and descendants in turn.
4. Union the `operation_files` links and `operations.photo_id` of all of them, ordered by
   `operations.id`.

`GET /photos/{id}/lineage` and the log's `photo=` filter both read this set.

**Keep distinct files distinct.** A duplicate is a different file, however alike: the
lineage tree shows each file as its own branch with its own steps, and every log entry
names the file it concerns, so a duplicate's arrival never reads as something that
happened to the original file itself. Label each file with its original Index time.

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
destination check, renaming a delivered file, similarity review, Reject and Return
are built; metadata writing is planned. The application never permanently deletes
destination photos. This
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
* **Navigation preserves your place.** Following a link into Inspector matches or
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
lacks, gets a filter. Similarity uses the gallery filter and Inspector because review
begins with a particular photo. Renaming is planned in the photo panel (§7.3; undated photos are a Needs review reason, §3.1),
with their eventual placement separate from the current gallery matching workflow.
A "failed operations" screen is Logs filtered to failures and introduces no action
Logs lacks.

### 7.2 Exact duplicates and similar photos are different things

The UI must not blur them:

* **Exact (SHA-1).** Byte-for-byte identical. Available as soon as an Index has
  run, with no new engine work.
* **Similar (perceptual).** Visually alike but different bytes — the same
  photograph as RAW and JPEG, or full-size and thumbnail. Requires the pair
  table in `engine-spec.md` §9.3, populated during Index.

The gallery Inspector reviews visually similar, different-content photos. It has no
exact-copy mode: Copy and Move already avoid writing exact duplicates to the
destination. Exact-copy counts and recorded outcomes remain in photo details,
history and Stats. Visual review includes destination photos only. The workflow is
**Index → Copy or Move → review and curate destination photos**. Reject and Keep
are built (§7.8); EXIF editing remains planned. Before delivery, the Inspector explains the Copy or
Move step. Old `/similar` bookmarks redirect into the gallery; an existing reference
opens its Inspector matches. There is no exact-copy matching dropdown.

**Every photo's info box states its exact-duplicate count. Delivered photos show
cumulative visual-match counts and inline results** scoped to them.

**The count must say whether they have been dealt with.** On a catalog that has
only been indexed, the duplicates are flagged but still on disk; a bare number
reads as "handled" when nothing has been. After successful duplicate removal, those copies are history. Copies left by a
Copy operation or failed cleanup may still remain in source. Show recorded outcomes
per copy rather than treating every duplicate as removed merely because a Move ran.

### 7.3 Renaming, and the names a photo arrived with

When duplicates collapse to one file, the survivor may carry the least useful
name in its group — a camera-style serial name can survive while the copy
removed against it carried the descriptive name a person actually chose. The
name held the information. This is a presentation problem, not an engine one:
the alternatives are already catalogued on the `Duplicate`/`Removed_Duplicate`
rows and on every `operations` row, groupable by `sha1_hash`.

**In the photo panel, not a tab** (decided 2026-10-05). Identical copies are the same
photo, so no choice of name can be wrong and nothing asks: the first-indexed name stays
until the user changes it.

* The panel lists **Also arrived as**: every other name and folder the group carried,
  each with **Use this name** (the breadcrumbs of `ui-design.md`, "Validation and
  feedback"), and **Rename…** to type one.
* A Library filter, **Has other names**, finds the photos whose group holds a different
  filename stem, sorted most duplicates first, for working through them.
* *Why not a Needs review note per group:* a large library holds thousands, and none is a
  problem. *Why not pick the "best" name automatically:* rules such as "a typed name beats
  a camera number" fail often enough to annoy; the user decides.

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

### 7.4 Similar photos in the gallery

**Built:** the ordinary gallery has a **Has similar photos** view alongside its
existing view controls. It contains destination photos with at least one recorded
visual match at the selected gallery percentage (90% by default), with the gallery's
existing search, date, type, folder and selection behavior. The top navigation has
no Similar button. **Most matches first** in the sort dropdown orders qualifying
match counts highest first, with ascending photo ID as the tie-breaker, before
pagination. The gallery summary also exposes a **Most matches first** shortcut.
**Matches at or above** offers 75/80/85/90/95/100% in that summary
whenever this view is active; the percentage also applies to date/name/size sorts.
Cards show compact count badges over the preview; their tooltip includes the percentage.
All views use the same card geometry and summary row. Long filter descriptions
use shared help while filter actions stay visible. Counts cover direct matches across the entire
destination library, including outside the gallery's filters, matching the Inspector
scope. Equal visual hashes count, exact byte copies are represented once, and the
reference itself is excluded. No new image comparisons run when controls change.

The URL saves `match_min` separately from Inspector `match`, alongside `sort=matches`.
Changes reset gallery paging to one but retain explicit selection; sidebar counts,
Select all and photo positioning use the same membership. Show only selected keeps
all selected files even without qualifying matches, with the percentage disabled;
known counts sort first, then zero and unavailable counts. The initial sort is Most matches first. Remember explicit sort choices per view
in browser storage; restore them on return. Explicit URL sorts take precedence. Clicking a gallery card carries the gallery
percentage into its matches and opens the Similar photos tab. Later Inspector
threshold changes remain local; previous/next retains that Inspector choice.
Photos without qualifying recorded matches are omitted. A coverage note appears
when destination hashes are unavailable or comparisons unfinished; absence from this
view does not establish uniqueness. Counts, sort and coverage are read in one snapshot.

The Inspector's **Similar photos** tab shows cumulative potential-match counts at **75%, 80%, 85%, 90%,
95% and 100%** in the Inspector. “85%+” means all matches at or above 85%; these are
not independent buckets. Selecting a count displays 12 candidates at a time inside
the information pane, ordered by similarity, with dimensions and side-by-side review.
The open photo stays the reference; threshold/page changes leave the main gallery
and explicit checkbox selection intact. Matches can lie outside the gallery's current
filters. Closing the match list leaves the counts visible. Outside the similarity gallery, first entering the tab
selects 90%; subsequent photo navigation keeps the tab and threshold, resets match
paging to one. Information-only
browsing loads no match data. Left/Right and Home/End on the tab controls move between
tabs; they do not navigate photos.
The URL records `photo`, `tab`, `match` (threshold) and `match_page` alongside gallery filters,
so reload and Back/Forward restore the Inspector's match context. Legacy `/similar`
bookmarks redirect here. Each byte identity is represented once.
Queue, references and saved-review endpoints require a delivered status and a
recorded present file at that photo's destination with matching SHA-1. Source-only
photos, projected destinations and missing destination copies are excluded, even
when their source remains available.
Equal visual hashes of
different byte identities remain visual matches, including at 100%.
The review also supports finding related photographs and clues about dates, events,
and other metadata. Association does not prove shared metadata or authorize copying
it; users must inspect the evidence. Metadata editing remains future work.
Availability is recorded evidence, not a fresh filesystem check. Missing hashes
and pending comparisons are explicit, and Index resumes unfinished comparisons.
**Built:** Review matching status opens a paged list of affected destination
photos with reasons and direct photo links. Generate missing hashes processes only files without recorded failures. Known
failures explain external corrections and offer an explicit per-file recheck
after the fix; bulk generation skips them. Resume comparisons handles stored hashes.
The engine verifies destination content before/after decoding; it does not depend
on a source still existing, and does not edit photos. Unsupported formats explain
the limitation. Missing/unreadable/changed files explain the required correction
before retry. Busy jobs disable starting recovery; progress, cancellation, request
failure retry and refreshed remaining counts are available. Successful recovery
keeps its results dialog open even when the originating warning disappears.
An ordinary Index may skip unchanged files and is not a general hash repair.
URL state preserves filters, reference and pages on reload or browser navigation.
Metadata donor/target selection and EXIF writes remain planned. The current review
offers explicit Reject and Keep actions (§7.8); browsing alone changes no files.

**Expanded review:** each match offers **Review side by side**, opening the
workspace with the Inspector's reference, threshold and candidate page. Two large
previews have independent rotation, zoom and horizontal/vertical position controls;
optional linked zoom/position keeps rotation independent. Reset view restores the
individual preview. Viewing transforms follow the photo while browsing candidates
and reset on close. Zoom magnifies generated previews (up to 1024 pixels), not
original-resolution pixels. Dimensions, file sizes and exact-content status are
shown. Hash percentages are not confidence estimates, including at 100%.
The comparison area expands to fit both previews and all their controls/details,
including dimensions, file sizes and linked zoom. It has no inner vertical scroll.
If needed, the whole review window scrolls, with the shared More above/below cues;
the candidate strip follows the comparison in normal flow.
The reference preview has an accent border and a plain bold **Reference photo** heading;
the candidate remains neutral. This marks the comparison reference, not a file
chosen to keep or a metadata donor.

**Use as reference** on the candidate loads that photo's direct matches at the
current threshold, resetting to page one. Keep the previous
reference displayed as the candidate (it may lie outside the new first page).
Rotate/zoom state follows each photo.
Move keyboard focus to the new reference and disable promotion while the pair needs
refresh after an error. Promotion does not select a keeper,
metadata donor or action targets. The gallery's reference and selection are
unchanged: Back to gallery returns to the original Inspector and entry page after
exploring another reference, keeping the chosen threshold.

Candidates are paged, with previous/next candidate navigation across pages. A
resizable information panel compares recorded metadata in aligned columns; users
can inspect all tags, search fields, or show only differences. Missing values,
file-modification fallback dates and unknown timezone offsets are labelled.
**File and image properties** comes first: format, extension, pixel dimensions,
megapixels, file size and aspect ratio. Recorded file type takes precedence over
the extension; an extension-only fallback is labelled. Differences use the exact
values, not rounded display strings; file sizes include exact bytes. Unknown
dimensions never become zero megapixels or a fabricated ratio. No format or size
is labelled an automatic winner. **Capture information** follows, and the optional
**All recorded metadata** table retains field search. Differences only applies to
all sections; field search applies only to the full metadata table.
Each table's Field, Reference and Candidate headings stay visible while scrolling
its rows, including when narrow layouts scroll the review window as a whole.
Dimensions beneath previews follow temporary rotation (width and height swap at
90°/270°) and are labelled Displayed when rotated. Recorded dimensions in the
information pane, megapixels and file size remain unchanged by viewing transforms.
The status line counts the look-alikes at the chosen threshold, and each candidate
thumbnail shows its similarity. Metadata, candidate and pair failures expose retry
rather than invented empty data.

Back to gallery retains the chosen threshold and page. Gallery selection remains
unchanged. The validated `review` URL state restores the current reference,
candidate, threshold, candidate page, divider share, linked zoom and current-pair
viewing transforms across reload. Other candidates' transforms last only in the open
session. Restoring fetches fresh photo state. Invalid state is ignored; missing
photos expose errors; pages clamp to the remaining results. Back/Escape clears the
workspace bookmark and returns focus to the opener or a surviving match control.
Deferred queues remain future work.
Guidance beside the threshold controls explains that results below 90% are more
likely to be unrelated: compare photos side by side before using them as clues for
dates or other details. The comparison dialog repeats this for pairs scoring below
90%; the actual pair score, not the chosen list threshold, controls that reminder.
Deciding between the photos is **Reject…** or **Keep this one, reject the rest**
(§7.8). *Why no same / related / unrelated labels:* a label that changes no file,
match or action is a note nobody acts on (maintainer's decision).
The expandable **Validation and performance** panel shows distinct usable hashes,
stored pairs, incomplete/unavailable counts, the most recently
reported comparison-phase elapsed time. Missing timing is
shown as not recorded; reported phase time is not a dedicated CPU benchmark.

Hash precomputation covers the full catalog; review results include only destination
photos. Precomputation needs an initial backfill and refresh when perceptual hashes change (`engine-spec.md` §9.3).
Find Similar results are measured against the selected reference, not chained through
other matches. Missing hashes are labelled unavailable rather than unique; historical
records remain accessible without being offered as actionable missing files. The
stored comparisons must support every offered threshold. Dimensions are captured during
Index; unreadable dimensions display as unknown.

**Planned metadata workstream:** donor and target selection and EXIF copy/edit extend
the built comparison workspace. Reject and Keep are implemented (§7.8). Browsing
alone never selects action targets or clears the gallery's explicit selection.
Future metadata target selection must be
distinct from opening a reference or choosing a threshold; changing the offered
match set must not leave hidden action targets armed.

**Reference, metadata donor and keepers are separate choices.** The reference
anchors comparisons. A donor supplies only explicitly selected metadata fields;
one or more keepers are photographs the user intends to retain. A smaller export
may have the correct metadata while a larger original is worth keeping, so a single
"primary" must not control both verbs. No role is inferred from the last photo
clicked, resolution or file size. Each designation is explicit and visibly labelled.
A user can choose another donor or keeper after comparison; the original reference
has no implicit protection from a later explicit Reject selection. Reject
previews must exclude explicit keepers; metadata previews identify the donor, chosen
fields and target photographs separately.

**Selecting photos never rejects them directly.** Rejecting a selection opens the
review in §2, with its count, the photos to keep or untick, and an explicit action
to move the selected files to Rejects. Keep this one, reject the rest uses the same
review (§7.8). The application never permanently deletes destination photos.

**Rejects preserves the file until the user empties it outside the app.** See
`engine-spec.md` §9.5 for the safety rationale. Return to library is available while
the rejected file remains. Historical paths and a prior Copy do not prove another
copy survives; only claim one is available after checking it. Catalog backups
cannot recover pixels. Emptied rejects retain their history, leave actionable lists,
and remain recognizable by content. Detected destination mismatches follow §7.6.

### 7.5 Editing metadata

**Planned, not implemented.** This section specifies the shared editor and its
write behavior. Temporary comparison rotation is implemented separately below.

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
**Editable metadata is organizational fields only: text, numbers and dates** (decided
2026-10-01), where the writer and format support them. Lists (keywords), GPS and other
structured values are read-only, labelled "Can't be edited here yet". *Why not every
writable tag:* tools built for detailed metadata, such as Immich, already cover that, and
a wrong-but-valid structured value (latitude and longitude swapped) passes any check.
Filesystem stat, structural image properties and computed catalog fields are never
editable. Do not confuse ExifTool writability with permission to edit derived properties. Keep capture date/time and its
optional timezone offset distinct, consistent with §10.

**An edit can create an exact duplicate.** If the edited file's resulting content
hash matches another catalogued photo, update the exact-duplicate relationship and
show it in the result with a link to review the matching photos. Preserve both files
and their individual lineage; do not automatically delete, merge away a file's
history, or trigger duplicate cleanup as part of a metadata edit. Rejecting an
unwanted destination copy is a separate explicit action with its own review and
confirmation (§7.8). A catalog hash match never authorizes source deletion without
the engine's live verification.

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
* **Write through the chosen method:** planned edits update the delivered photo
  or its XMP sidecar according to the format's setting (`engine-spec.md` §9.6).
  RAW defaults to XMP; other formats default to in-file edits. Unsupported writes
  fail clearly, with no silent switch of method or catalog-only correction.
* **Preview unsupported writes:** before confirmation, identify selected photos
  that cannot store the requested fields through the chosen method, with counts and per-photo reasons
  (for example, **“18 photos can be updated · 2 cannot store the selected field.”**).
  Leave those unsupported photos unchanged and make the actionable subset explicit
  before the user confirms. Do not silently apply only part of the requested field
  set to an unsupported photo. Do not silently substitute a sidecar, an in-file
  write or a catalog-only edit for the chosen method. This is a photo organizer;
  supporting arbitrary image formats is outside scope. Existing read/index support
  does not imply write support, and this
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

**Built comparison-only rotation:** the expanded review workspace lets users rotate the
reference preview and each candidate independently, in 90° steps, with a reset and
visible temporary-orientation state. It must compose with zoom/pan and never carry
one candidate's rotation onto a different photo. These viewing controls
do not write files, edit EXIF, regenerate hashes or recalculate match scores.
They help assess returned candidates; retrieval of rotated photos missed by the
current matcher is a separate concern. The expanded workspace (§7.4) is the
side-by-side review surface.

**Future end-of-review save** (confirmed 2026-10-05): after a verified orientation-write
path exists, offer one decision for remaining rotation changes when the user finishes
reviewing, not on individual Rotate clicks: turning to look stays free, and nothing is
saved by accident. Show affected photos and their final orientations,
with choices to save selected changes, discard viewing changes, or return to review.
Track photos across candidate navigation and reference promotion; do not assume the
currently displayed pair is the only pair rotated. Define consistent exit handling
for Back, Escape and dialog close before shipping. Resetting to the original
orientation leaves no rotation change to save. General EXIF edits open the shared
editor rather than being entered in the comparison table. None of this save flow is
implemented; closing today's workspace discards its viewing transforms.

**Where a photo can be turned** (decided 2026-10-05): in the comparison, in the photo
panel (the same one question when the panel closes or moves to another photo with turns
unsaved), and for a selection through the selection bar's **Rotate…**, which shows the photos
turned and asks before saving, as Copy's review does. **No turn control on gallery
thumbnails:** a card is for picking, a stray click would add a photo to the save
question, and the panel and the selection bar already cover one photo and many (Google Photos and
Apple Photos place rotation the same way).

**Future saved rotation is an EXIF edit, never a pixel edit.** The Inspector and bulk edit will offer
**Rotate left**, **Rotate right** and **Rotate 180°**. Each changes only the EXIF
`Orientation` tag, which viewers and galleries apply when displaying the photo.
The pixel data is never decoded and re-saved: re-encoding a JPEG loses quality on
every save, and a rotation that changed pixels would be a different photograph.
An in-file orientation write goes through the same confirmed edit as any other field: the pre-action backup,
a working copy, read-back verification of the tag, the expected-rendering rule for
pHash above, and a new content identity linked to the old one in lineage, since the
file's bytes change. The grid thumbnail and detail preview follow the new content;
both already honour `Orientation`. A rotated copy is no longer byte-identical to its
former duplicates, and history shows that. The tag goes where the photo's edits are saved (`engine-spec.md` §9.6: in the file, or the
XMP sidecar that RAW formats use by default, which leaves the photo's bytes and identity
unchanged). Where neither can take `Orientation` safely, the control is unavailable with
that reason. It never falls back to re-encoding, to the other storage method, or to a
catalog-only rotation a gallery would not see. Both write paths remain unbuilt.

**A changed date refiles the photo** to the folder its new date implies,
automatically and with no setting to disable it. Correcting the date *is* the
decision; moving the file is only that decision applied consistently, so a
prompt would ask the user to confirm the same choice twice. It is not a guess —
the correct folder is computed, not judged. And sorting photos into date folders
is what this tool does: if its own output disagrees with the metadata it used to
build that output, the product contradicts itself. Finding the file afterwards
is the log's job, since a refile records both old and new path. Editing and refiling
are one confirmed action with no second prompt, and the form warns in advance that a
date change may move the photo. **If the refile fails, the edit stands** (decided
2026-10-01): the result says the date was saved but the photo could not be moved, with
the reason, where it still is, and **Try the move again**, which repeats only the move;
the photo shows "needs moving" in the Inspector and the log until resolved.

**Correction is manual; there are no undo operations.** History shows original
indexed information and all subsequent changes, including per-file previous values
for bulk edits. The user consults that evidence and explicitly makes a new edit or
rename against the current state. Later actions may have reused a name or changed
placement, so reversing an old operation is not a supported recovery mechanism.
Preserve full lineage across hash and path changes; see `engine-spec.md` §10.

**Decided details (2026-10-01), for the screens above:**

* **Single photo:** an organized photo's Inspector offers **Edit EXIF**, opening the editor
  as a workspace (§7.7). The form lists date taken, orientation (↺ ↻, as in comparison),
  camera and lens first, and **Show all EXIF data** for the rest. Columns: field, current
  value, new value; an empty new value means unchanged, a changed row is highlighted with
  **Reset**, and **Clear** is separate. Read-only tags say why on hover.
* **Dates are never invented:** the user types the full date and time; with no date at
  all, the time is still required (no midnight or noon convention). The offset is
  optional and never added. Input and the file's ability to store each field are checked
  before Save, with the error beside the field.
* **Donor to targets:** any photo can be pinned with **Use as donor**; targets are gathered
  by any means (similar matches, a folder, a date, a search, ticks, mixed across views),
  and any target can become the donor. A selection is trusted whatever view it came from.
  Each field applies as **Fill empty only** (the default) or **Replace existing**; one
  confirmation for the whole operation, only when something is replaced, naming fields
  and counts. Never one prompt per photo.
* **One date for many photos keeps each photo's own time of day by default,** so their
  order survives (scans stay in scanning order), with the reason stated under the field;
  **Use one time for all** applies one time instead. Times are never spaced out
  automatically.
* **Shift date and time:** **Shift by…**, or **I know when one of these was taken** (the
  app derives the difference from one photo). Time-zone tags are never added or changed;
  the screen says the amount is the user's responsibility. The preview flags photos
  landing in the future.
* **Displayed details say where they came from, lightly** (decided 2026-10-05): one source
  line per block of details, such as "Details from: XMP sidecar · file's EXIF" above the
  photo panel's details or the comparison table, not a label on every field. A value that
  came from the sidecar rather than the file carries a small **XMP** tag; the value it
  replaced stays in the photo's history. A date that is a file's modification time is
  always marked so (§3.1), and suggestions always name their source ("from the filename").
* **Where edits are saved** (decided 2026-10-02, `engine-spec.md` §9.6): Settings › Files
  sets it for RAW formats (default **XMP sidecar**) and other formats (default **In the
  file**). RAW photos are therefore editable out of the box, through their sidecars.
  Editing inside a RAW file is opt-in: with it off, choosing it offers **Review and turn on
  RAW editing…**, the consent step with its warnings, returning to the editable form.
* **A sidecar that could belong to several photos** waits in Needs review (§7.9): "IMG_0001.xmp
  could belong to IMG_0001.jpg or IMG_0001.dng. Which one?" Until answered, neither the note
  nor those photos are copied, moved or edited.
* **An unedited original arriving later** (its bytes match an edited photo's earlier
  SHA-1) is not organized again: it goes to Needs review (§7.9) as "old version of a photo
  you fixed", with **Don't keep it** and **Keep it as its own photo**.
* **Export sidecars:** when Index finds `.json` files paired with photos, its result says
  how many, that they often hold dates the photos lack and that a Move leaves them behind,
  and links README guidance naming tools that write them into photos before indexing.

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

### 7.7 Workspaces

**The frame is built** (`ui/Workspace.tsx`, design in `ui-design.md` "Workspaces"), with
the comparison workspace (§7.4) as its first user; the other tasks are planned (decided
2026-10-01). The Library is for finding photos; a **workspace** is for working on them. Deep tasks (comparison, EXIF editing, donor to targets, bulk edits,
reviewing Needs review) open in a full-window view without the filter pane and gallery,
with its own address so reload and links work. The Inspector stays the quick look
beside the gallery.

* **One frame:** a header (**Back to gallery**, the wording used across the app, the task and what it works on, **‹ n of
  N ›**, the main action), the task's content, and a footer status line for unsaved
  changes, errors and progress. Each task changes only the content.
* **Back to gallery** restores the exact Library state: filters, scroll and selection.
  Leaving with unsaved changes asks first (§7.5).
* **The comparison workspace** (§7.4) runs in the frame: its address, Back to gallery,
  focus return and candidate stepping are the frame's. A single-photo edit will be the
  same workspace with one column. Esc goes back and ← → step, stopping at the ends.
* **What ‹ › steps through** (decided 2026-10-05): whatever the workspace was opened
  from, named in the header so the next step is never a surprise. The comparison steps
  through the starting photo's look-alikes ("Candidate 1 of 5"); Needs review one by one
  through the notes of the list it came from, in that list's filter and order; the editor
  through the gallery's current order and filters, the selection ("3 of 24 selected") or
  the Needs review list, whichever it was opened from. *Why not always the gallery:*
  editing a selection would wander off into photos that were not selected.
* Follows `ui-design.md`; the frame's patterns are added there when built. Visual options
  are chosen from a mockup first.

### 7.8 Rejects

Engine side `engine-spec.md` §9.5. **Reject** moves organized photos to `dest/rejects/`;
the application never deletes a photo, and the user empties Rejects on the host. A photo
identical to a reject is kept out of the library: a Copy skips it and a Move removes its
source against the copy in Rejects (or puts it there, when Rejects was emptied).

*   **Where:** the selection bar's **Reject (n)…**, reviewed first as for Copy and Move, and
    **Reject…** in the Inspector for one photo. `n` counts only the selected photos in the
    library, and the button is absent when there are none. Each asks first, starting
    on Cancel: "Reject IMG_0412.jpg?" (or "Reject 12 photos?") and "It moves to the Rejects
    folder and leaves your library. You can bring it back any time until you manually
    empty Rejects." No folder reject: select the folder's photos instead.
*   **The Rejects view** (`view=rejects`): rejected photos leave every other view and
    count. Normal cards with a Rejected badge (when, on hover). Above them: "Rejects
    holds 12 photos · 22 KB · oldest rejected Oct 1, 2026" and **How to empty Rejects**,
    which expands in the page. A photo the user deleted from the folder leaves the view at
    once.
*   **Reject and Return follow the selection, not the view** (decided 2026-10-05): the
    selection bar offers **Reject (n)…** for selected photos in the library, **Return to
    library (n)…** for selected photos in Rejects (a selection never holds both, §2), so the
    photos a Reject just moved can be returned from the job's own view. Return never
    appears when library photos are selected. In the Inspector, **Return to library…** for a photo in
    Rejects. *Why not by view:* after a Reject the screen shows the job's photos, not the
    Rejects view.

*   **From Similar photos:** each look-alike has its own **Reject…**. Above them the photo
    open in the panel stands out as **Keeping** (green outline, a check, a large picture)
    with **Keep IMG_0410.jpg, reject the other 7…**: every look-alike at the chosen
    percentage, reviewed like the selection bar's Reject, the kept photo first as a full-size card
    with no tick box, whatever the sort or page.
*   **Side by side:** a **Reject…** under each photo, so it is clear which one goes. The
    first reject in a comparison asks, with **Don't ask again while comparing** (until the
    comparison closes); a reject that would leave none of the compared photos in the
    library always asks ("None of these photos would be left in the library", **Reject it
    too**). Rejecting the look-alike shows the next one ("Rejected IMG_0412.jpg · next
    look-alike shown" with **Return it to the library**); rejecting the photo you started
    from closes the comparison with the same note. One reject at a time: the button reads
    "Rejecting…" meanwhile. No keyboard shortcut. Beside the threshold, **Keep
    copy-of-001.jpg, reject the other 128…** opens the same review as in Similar photos,
    keeping the photo on the left; to keep the other one, **Use as reference** first. The
    candidate strip stays for moving between look-alikes, with no Reject of its own.

**Not built yet:** a photo only similar to a reject goes to Needs review (§7.9) and is
never rejected automatically. With the reject still in Rejects, the two open side by side
in full, with **Keep the old one instead** beside Reject it too and Keep it; with the
reject emptied, its stored thumbnail and details stand in for it.

**Rejects' size stays in view without noise:**

*   **Stats** has a Rejects tile (§5.9): "340 photos", "1.2 GB using now · oldest rejected
    3 months ago" and, once anything has gone from Rejects, "Emptied so far: 1,200 photos ·
    4.8 GB". Empty, it reads "Empty" with what has been emptied. It opens the Rejects view.
    Emptied counts every rejected photo whose file is gone, recorded by a job or not yet.
*   **A reminder line** under the header on every page, **only past a limit**: Rejects
    holding at least a size (default 1 GB) or a photo in it for at least a number of days
    (default 30). "Rejects holds 1.4 GB, including photos rejected more than 30 days ago ·
    How to empty Rejects · Open Rejects" (Open Rejects is left out in the Rejects view). No
    Dismiss: it goes once Rejects is under both limits, checked again when the window
    regains focus, since emptying happens in a file manager.
*   **Settings › Rejects reminder:** each limit has its own on/off box and value (size in
    GB, age in days); off is saved as null.

### 7.9 Needs review

**Planned** (decided 2026-10-01). **Needs review** lists photos waiting for a
decision. Each carries a **note**: a reason, the job that raised it, when, and optionally a
related photo, opened side by side in comparison. **Notes are for decisions only**, not a
general tagging system: personal labels (people, albums) belong to gallery applications.

* **Each reason brings its own actions,** e.g. old version of a photo you fixed: Don't keep
  it · Keep it as its own photo; looks like a reject: Reject it too · Keep it · Keep the old one instead; suspicious
  date: Edit date · It's correct; couldn't be read: Recheck after fixing · Leave it;
  review later: Done. A new kind of review is a new reason, not a new screen.
* **Where it lives** (decided 2026-10-05): a Library view, **Needs review (n)**, beside the
  others, so its count is always in sight; each note's reason and buttons show on the
  photo's card and in the Inspector. **Review one by one** opens the workspace (§7.7),
  which steps through the notes with ‹ ›, each note's photos side by side with its
  buttons. *Why not a page of its own:* finding notes then works like the rest of the
  Library (filters, selection, bulk answers), and working through them reuses the
  workspace built for such tasks.
* **Filter by reason; bulk within one reason** (preview and one confirmation). A mixed
  selection offers only shared actions.
* **A note exists only when a person must decide.** Facts the catalog can compute (every
  similar pair) stay live queries, so the list cannot grow into a copy of the library.
* **A resolved note leaves the list;** the decision goes into the photo's history. **A note
  that stops being true clears itself** (decided 2026-10-05): a corrected date, a file
  that now reads, a reject returned to the library. The next job or the screen notices,
  and the photo's history records the note and why it went ("cleared: the date was
  corrected in job #52"), as the engine's needs-attention issues clear only on evidence.
  *Why not make the user dismiss it:* answering something that is no longer a problem is
  busywork, and nothing is lost.
* **Review later** (decided 2026-10-05): the one note a user sets. **Review later** sits
  beside **Reject…** in the photo panel, with an optional short note ("check the date");
  **Done** clears it. Not in the selection bar: it is a photo-by-photo bookmark, and it holds
  nothing. It stays a plain "come back to this": no names, colours or lists, which
  would make it the general tagging that belongs to gallery applications.
* **Whether a photo waits depends on its note** (decided 2026-10-05). A note that holds
  its photo keeps it from Copy, Move and edits until answered; the others let it carry
  on as normal and ask afterwards:

  | Note | While it waits |
  | --- | --- |
  | Which photo is this sidecar for? (§7.5) | Held: the sidecar and every photo it could belong to |
  | Old version of a photo you fixed | Held: not organized into the library |
  | Looks like a reject (§7.8) | Carries on: filed as normal; rejecting it later moves it to Rejects |
  | Suspicious date | Carries on: filed by the date it has; fixing the date refiles it |
  | Couldn't be read | Nothing to hold: the file failed and stays where it is |
  | Small image | Held: not organized into the library |
  | Couldn't confirm what happened (an attention issue from recovery) | Held: its copy authorizes no removal of a duplicate's original until checked; **Check it now** runs a destination check of the file, whose verified result clears it |
  | No capture date (§3.1) | Carries on: stays filed under `Undated/` until dated |
  | Review later (set by the user) | Carries on |

  *Why not hold everything:* a look-alike of a reject may not be one, and holding it would
  leave a gap in the library until answered. *Why not carry everything on:* filing an
  unfixed old version beside its fix, or giving a photo another's sidecar, is the wrong
  thing to do and harder to undo than to wait.
* **Small images** (decided 2026-10-05): a photo whose shorter side is under a size set in
  Settings › Files gets a note, "Small image: 640 × 480", with **Keep in library** and
  **Reject**, and waits outside the library until answered, so thumbnails, web downloads
  and screenshots never reach the library or a gallery app pointed at it. A larger
  look-alike already in the library is shown beside it, the strongest sign of a junk
  copy. The size is a setting and can be switched off, since a library of small images
  would otherwise hold everything; Index reports how many it held ("312 small images are
  waiting for your decision"). *Why a note, not a view of its own:* filtering, bulk
  answers and side-by-side review come with Needs review, and the view buttons are
  already many. *Still to settle when building:* the default size (a shorter side of
  800 pixels was suggested) and whether the setting starts on.
* **A held photo always says so:** the job's result counts them ("3 photos waiting for
  your answer"), and the gallery and Inspector show **Waiting for your answer** on each.

## 8. Explicitly Out of Scope

What NegativeSpace deliberately does not do (decided 2026-10-05). **Never** is outside what
the tool is for; **Not yet** is planned or possible later. The README's "What it doesn't
do" is the short form of this table: **change both together** whenever a scope decision
changes, and move a row out once it is built.

| Not done | | Why |
| --- | --- | --- |
| Back up your photos | Never | Backup tools do it better; NegativeSpace backs up only its catalog (§9) |
| Delete photos, beyond Move removing originals after a verified copy | Never | Rejects is emptied by the user; the app never deletes a photo |
| Write to the source, except Move removing originals | Never | The library stays read-only for everything else |
| Edit pixels (crop, filters, re-saving) | Never | Rotation is metadata only (§7.5); editing belongs to photo editors |
| Albums, people, faces, keywords for browsing | Never | Gallery applications such as Immich do this; NegativeSpace organizes files for them, and Needs review notes are for decisions only (§7.9) |
| Several users with their own accounts | Never | A single person's tool; one password is planned (§11) |
| Run in the cloud, or sync between machines | Never | It works on mounted folders |
| Published container images | Never | Users build the images from a clone, so what runs is the code they can read (decided 2026-10-05) |
| Videos and other non-photo files | Not yet | Deferred until photo organizing is complete; until then they are left untouched |
| Edit dates and other metadata | Not yet | Planned: the editor (§7.5), with XMP sidecars for RAW (`engine-spec.md` §9.6) |
| Mobile and touch | Not yet | Built for desktop browsers; phones are not tested |
| Mac and Windows hosts | Not yet | Tested on Linux only |

The engine-side capabilities these workflows depend on are specified in `engine-spec.md`
§9; this document covers what the user sees and does.

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
| Before a confirmed rename, Reject or Return; also before metadata edits when implemented | One automatic backup per user action, including a bulk selection; refiling is part of the edit, not another trigger |
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
offer **Retry backup**: its own line in the finished-job banner. Do not describe
completed file work as failed merely because its backup failed.

**Where backups live:** in Settings, not on a page of their own; the top row is full, and
Stats shows the backup state. While catalog changes are not in any backup, every page shows
one line under the top row, **"N changes are not in any backup yet · Back up now"**, until a
backup succeeds.

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

## Suspicious dates

The **Suspicious dates** gallery view flags the recorded gallery date when its year
is before 1800 or more than one year ahead of the current UTC year. This is a
conservative review heuristic, not proof of an error. It includes EXIF-derived dates
and file-modification fallbacks, with their source identified in the Inspector and
comparison pane. Missing dates remain covered by No capture date; raw malformed or
conflicting EXIF tags are outside this first policy. Never infer an offset or replace
a recorded value. Legitimate historical material may still be flagged.

Use existing gallery controls, card geometry, selection, pagination and URL state
(`view=suspicious`). Counts, sidebar filters and Select all use the same membership.
Explain the policy beside results. The Inspector shows the reason, recorded value,
source and a link to the affected view. Similar photos offer clues, not automatic
corrections. The comparison Capture information table includes a Date review row
when either photo is flagged. State clearly that date editing is not yet available.
No schema changes, reindex or file writes are needed; the upper bound advances with
the server's UTC year when the catalog is read.

### Reference-based grouping

**Built:** Group similar photos defaults on and adds reference-set counts and actions in
Has similar photos. Identical closed neighborhoods appear once, represented by the
lowest canonical photo ID satisfying active filters. Membership uses the entire
destination library at the chosen threshold; equal counts alone do not merge sets.
Collapse precedes sorting and pagination. Totals count sets; selection takes only
representative photos. Explicit selections remain unchanged. Members include direct
matches from the entire destination catalog. Review this set opens direct-match
comparison. Explore related sets offers direct-match references with overlap and
additional-member counts. Show together unions at most six chosen related sets,
shows each byte identity once, and preserves membership/provenance. Indirect photos
compare through a supporting reference. Both member lists are paged and coverage
limitations remain visible. Expanded sets are session-only and reset on reload/closing;
threshold changes clear expansions. No transitive traversal. See [the design contract](ui-design.md#reference-based-sets).

Hash recovery now records per-file failures in Logs, with photo/path, category and
external correction guidance. Inspector shows recorded visual-processing problems.
Failures do not change delivered status or delete files. Missing EXIF alone does not
establish damage. A broader import-completion issue summary remains pending.

Grouping defaults on; the browser remembers the grouping toggle and each view’s
explicit sort choice. Set membership and chosen expansions remain temporary.

The gallery similarity percentage defaults to 90% and remembers explicit user
changes in browser storage (`ns.matchMin`). An explicit `match_min` URL value wins
without overwriting that preference. Gallery and reference-set threshold controls
update the preference; Inspector/comparison thresholds remain local to their review.
The 75% floor remains available. Identical-set collapsing is implemented for the grouped gallery.

### Review links and set navigation

Copy review link serializes the current comparison directly, including reference,
candidate, threshold, current-pair viewing transforms and linked
zoom. It does not depend on a pending URL update. Report
success only after the clipboard write succeeds. If clipboard access is unavailable
or rejected (including local-network HTTP), expose a labelled, selectable read-only
link for manual copy. Recipients need access to the same instance and catalog.

Previous set / Next set in review follows the grouped gallery's percentage, filters
and sort, anchored on the entry reference even after Use as reference. Disable
unavailable boundaries and loading navigation; request failures offer Retry set
navigation. Entering another set starts a fresh comparison with temporary viewing
transforms reset.
Navigation is offered only from the grouped gallery, not an expanded union or a
set-member scope whose ordering has a different meaning.

Show this set in gallery is available from comparison and each reference in set
exploration. It shows the reference and direct members at that set's percentage as
ordinary, individually selectable cards, with server paging and normal sort controls.
This temporary scope bypasses the saved gallery filters and does not auto-select,
expand or clear the existing selection. Filters are disabled while it is open;
Back to results restores the previous gallery filters/page. Reload leaves this
session-only scope. Browsing is not limited in members. No EXIF edit, deletion, image
processing or persisted group is implied.

## 11. Access and Sign-in

**Today there is no sign-in** (decided 2026-10-05): anyone who can reach the web port can
use every action, Move included. The README says so and tells users to keep the app on
their own network, behind a VPN or an authenticating reverse proxy, never exposed to the
internet.

**Planned before the first release: one password** (decided 2026-10-05). NegativeSpace is
a single-person tool, so one password, not user accounts.

* **First start generates it.** The app creates a random password and prints it once to
  the container output (`docker compose logs app`), in a block that is easy to find,
  saying where it came from and that it should be changed. Only a hash of it is stored.
* **Sign in, then change it.** Until signed in, the page shows only the sign-in form.
  Settings offers **Change password**, asking for the current one.
* **Every route needs it,** the job feed included; the API refuses without a valid session.
* **Still to settle when building:** the hash (an established one such as scrypt or
  Argon2, chosen by measurement and named); where it is kept (application data, and
  whether catalog backups include it); session length and cookie settings; how a
  forgotten password is reset (a command run inside the container is the likely route,
  since whoever can run it already controls the files); and whether a reverse proxy's
  sign-in can stand in for it.

