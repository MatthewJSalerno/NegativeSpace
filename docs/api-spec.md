# API Specification: NegativeSpace Web API

The HTTP and WebSocket interface between the browser and the engine, as implemented in
`webui/` (`app.py` routes, `catalog.py` reads, `jobs.py` job control). This document
is the reference for what exists. `webui-spec.md` designs the screens that use it;
`engine-spec.md` defines the catalog it reads. A route in code that this document does
not describe fails CI (`tools/check-api-spec.py`).

FastAPI also serves a generated schema at `/api/openapi.json` and an explorer at
`/api/docs`. They list the same routes but not the rules below.

## 1. Conventions

*   **Base path** `/api/v1`. In the two-container deployment (`docker/compose.yml`) the
    `web` container passes everything under `/api` to `app`, which listens on port 8000
    and is not published.
*   **JSON** in and out, except thumbnails (`image/jpeg`).
*   **One error shape**, for every refusal: `{"error": "<code>", "message": "<text for the
    user>"}`, sometimes with extra fields (§7). `400` is a bad request, `404` an unknown
    photo or run, `409` a conflict with the catalog's or a job's state, `503` a catalog
    too busy to answer, and `500` the engine failing unexpectedly.
*   **No usable catalog** makes every catalog-reading route answer `409` with
    `catalog_missing`, `catalog_incompatible` or `catalog_error`. `GET /status` reports
    the same state without failing.
*   **Ownership.** The API writes settings only, through `ns_db.save_settings`. Every
    other change is made by running the engine as a child process, from an argument list
    and never a shell string (`webui-spec.md` §5.6). The browser never touches SQLite.
*   **Times.** Application events (`started_at`, `ended_at`, `updated_at`) are UTC
    instants with an offset. Photo dates (`date_taken`, EXIF values) are the wall-clock
    time the camera recorded; they carry an offset only when EXIF recorded one, and are
    never presented as UTC (`webui-spec.md` §10). `file_modified` is epoch
    seconds.

## 2. Catalog

### `GET /api/v1/status`

The first screen's state. It never creates anything.

    {"state": "missing" | "ok" | "incompatible" | "error", "detail": "<reason or null>",
     "photos": 1160, "indexed": true, "eligible": {"copy": 0, "move": 1160}, "copied": 1160,
     "version": {"release": "0.1.0", "branch": "main" | null, "commit": "2c4728f" | null},
     "application_data": "/appdata", "catalog_backups": "/backups",
     "active_job": <Run or null, as in GET /jobs/active>}

`eligible` is how many photos a Copy all and a Move all would take, by the engine's own
rule (`ns_db.TRANSFER_ELIGIBLE`): Copy takes `Pending`; Move also takes `Copied`, deleting
each source against its verified copy. `copied` is how many of Move's are already copied.
Both count the whole catalog, whatever the gallery's view or search.

`version` is which build is running: the release in the repository's `VERSION` file,
and the branch and commit the image was built from (the `NS_BRANCH` and `NS_COMMIT`
build arguments; `null` when the build was not given them). Shown beside Settings.

The two paths are container paths, named in guidance; the API does not know the host's.

### `POST /api/v1/catalog`

Creates an empty catalog with default settings, without indexing. `201` with the status
object. It refuses to replace a catalog that exists, including one that appeared after
the user was shown there was none (`409 catalog_exists`), and checks that application
data is writable first (`409 appdata_not_writable`).

## 3. Settings

### `GET /api/v1/settings`

Each setting under the engine's own key, with the revision it was read at. A setting
never saved shows the engine's default, the value a job started now would use, at
revision 0.

    {"workers": {"value": 8, "revision": 0, "default": 8, "detected": 8, "host": 8,
                 "limited_by": null | "cpu_quota" | "cpu_set"},
     "exts": {"value": [".cr2", ".jpg"], "revision": 3, "default": [...],
              "support": [{"extension": ".cr2", "supported": true, "warning": null}, ...]},
     "backup_retention": {"value": 20, "revision": 0, "default": 20},
     "job_active": false}

`workers.detected` is the number of CPUs the container may use (`ns_db.available_cpus`):
the host's cores, reduced by a CPU set or a CPU quota. `limited_by` names which applies.

### `PUT /api/v1/settings`

Saves the settings that changed, each with the revision it was read at:

    {"values": {"workers": 4}, "revisions": {"workers": 0}}

`200` with the settings as in `GET`. If a revision moved since it was read, another tab
saved first: `409 settings_changed`, and nothing is written. An invalid value is
`400 invalid_settings`, and a catalog too busy to take the write is `503 catalog_busy`.
Saved values apply to jobs started afterwards, never to one already running.

### `POST /api/v1/settings/validate-extension`

    {"extension": "mov"}  ->  {"extension": ".mov", "supported": false, "warning": "..."}

Whether the engine reads the extension as a photo (`ns_db.extension_support`). An
unsupported one is never refused, only warned about (`webui-spec.md` §3.2).

### `GET /api/v1/ui-state`

What the interface remembers for its user, kept with the catalog rather than in the
browser, so clearing a browser's data or opening another does not bring it back:

    {"dismissed_run": 12}

`dismissed_run` is the newest job whose finished banner was dismissed; it covers that job
and every earlier one. A value that is not a recorded run id is `400 invalid_request`.
Not a setting: settings configure jobs and are copied into each run's configuration.

### `PUT /api/v1/ui-state`

Saves `{"dismissed_run": 12}` and returns the state as in `GET`.

## 4. Photos

### `GET /api/v1/photos`

One page of the gallery. It lists photographs, not every copy: a `Duplicate` or
`Removed_Duplicate` row is folded into its anchor's `duplicates` count.

| Parameter | Values | Default |
| :--- | :--- | :--- |
| `view` | `all`, `organized` (Completed, Copied, Found_At_Destination), `unorganized` (Pending, Processing, Failed) | `all` |
| `sort` | `newest`, `oldest`, `largest`, `smallest`, `name` | `newest` |
| `q` | filename search: current and original names, including removed duplicates' names; never folder names | none |
| `undated` | `true` for only photos with no EXIF date taken, the ones filed under Undated | `false` |
| `date` | repeatable: a year (`2023`), a month (`2023-06`) or `none` (no date at all); the date tree's "Show only". Several add up | none: every date |
| `type` | repeatable: a file extension, lower case, no dot (`jpg`, `heic`); the Types section's "Show only". Several add up | none: every type |
| `page`, `page_size` | page from 1; 1 to 240 photos | 1, 60 |

    {"items": [{"id": 12, "status": "Pending", "file_size": 3012443,
                "date_taken": "2023-06-05T21:20:00", "date_source": "exif" | "file_mtime",
                "filename": "IMG_0001.jpg", "duplicates": 1}, ...],
     "page": 1, "page_size": 60, "total": 1160,
     "counts": {"all": 1160, "organized": 0, "unorganized": 1160, "undated": 1160}}

`counts` apply the search, `date` and `type` to each view, but not `undated`, which has its
own count: turning No capture date on leaves All photos at its real number. `total` is
what this request shows, every filter applied. `counts.undated` is how
many photos in this view and search have no capture date, whether or not the filter is
on, for the filter's label. The date sorts put undatable rows last.

### `GET /api/v1/photos/timeline`

Photos per calendar month for the same `view`, `q`, `undated`, `date` and `type`, newest month first:

    {"months": [{"month": "2023-06", "count": 68}, ...], "undated": 0}

`undated` here counts rows with no date at all. A month's first photo in a date sort
sits after every photo sorted before it, which is how the screen jumps to a month's
page. The date tree asks without `date`, so an unticked month keeps its count; a jump
asks with it, to land on the right page of the filtered gallery.

### `GET /api/v1/photos/types`

Photos per file type for the Types section, most first, for the same `view`, `q`,
`undated` and `date`, but never `type`, so an unchecked type keeps its count. Only types
the catalog holds are listed:

    {"types": [{"type": "jpg", "photos": 2980}, {"type": "heic", "photos": 212}, ...]}

A type is the extension of the name the photo was indexed under, lower case.

### `GET /api/v1/photos/ids`

Every photo id the gallery shows for the same `view`, `q`, `undated`, `date` and `type`, across
all pages: **Select all**.

    {"ids": [3, 7, ...], "total": 412, "limit": 1000, "over_limit": false}

Over the 1,000-photo selection limit (the engine's `--file-ids`), `ids` is empty and
`over_limit` true: refused whole, never cut short, because a partial Select all would
act on only some of what was shown.

### `POST /api/v1/photos/selection`

The selected photos, whatever view, search or dates would hide them (Show only selected):

    {"ids": [3, 7, 99999], "sort": "newest", "page": 1, "page_size": 60}
    ->  {"items": [...as GET /photos...], "page": 1, "page_size": 60, "total": 2, "missing": [99999]}

It reads; it is a POST because 1,000 ids is too long for a URL. `missing` names ids no
longer in the catalog, so a selection is never silently shortened. More than 1,000 ids
is `400 invalid_request`.

### `GET /api/v1/photos/{id}/inspect`

The Inspector's details. `404 unknown_photo` for an id the catalog does not hold.

    {"id", "status", "filename", "source_path", "dest_path",
     "dest_path_is_projection": true,     // not delivered: where it would go
     "has_collision_rename", "file_size", "width", "height",
     "file_modified": 1686000000.0,       // as the first scan observed it
     "date_taken", "date_source", "date_offset",
     "exif_dates": [{"field": "taken" | "digitized" | "modified",
                     "value": "2021:05:01 10:00:00", "offset": "+02:00" | null}],
     "camera", "iso", "aperture", "shutter", "sha1", "phash",
     "duplicates": [{"id", "status", "source_path", "dest_path", "file_size"}],
     "metadata": [["Aperture", 2.8], ["DateTimeOriginal", "2021:05:01 10:00:00"], ...],
     "thumbnail": {"availability": "present" | "failed" | "pending",
                   "failure_category", "failure_detail"}}

`exif_dates` lists only the dates EXIF holds, each with the offset tag that pairs with
it (`OffsetTimeOriginal`, `OffsetTimeDigitized`, `OffsetTime`).

`metadata` is every tag the Index recorded, as `[name, value]` pairs sorted by name:
ExifTool's full set (or Pillow's when ExifTool found nothing for the file), not a curated
subset. The engine's own `date_taken` and `date_source` are left out; they are above.
Read from the catalog, so it shows the photo as last indexed.

### `GET /api/v1/photos/{id}/lineage`

Everything recorded about a photo's files, for the lineage tree (`webui-spec.md` §6.3):

    {"photo_id": 12, "sha1": "...", "photos": [12, 40],          // the photo, then its exact duplicates
     "files": [{"file_id", "origin_file_id", "origin_kind": "indexed" | "copy" | "observed_destination",
                "path", "role": "source" | "destination", "presence": "present" | "removed" | "missing",
                "sha1_hash", "matches": true, "file_size", "indexed_path", "created_at",
                "photo_id", "photo_status"}, ...],
     "operations": [{"id", "run_id", "mode", "status", "timestamp", "error_message", "photo_id",
                     "source_path", "dest_path", "recovery",
                     "files": [{"file_id", "role": "source" | "destination" | "retained_copy"}]}, ...]}

`files` holds the photo's source file and every file descended from it (a copy records
the file it came from; an indexed file records itself as its own origin), and the same
for each duplicate. `matches` says whether the file's recorded
content is the photo's. `operations` is every operation that touched any of them, oldest
first, with the role each file played. A copy's size is its origin's: it was verified
byte for byte when made. An unknown photo is `404 unknown_photo`.

### `GET /api/v1/photos/{id}/thumbnail`

`size=grid` (default) serves the 320px grid thumbnail from the cache. `size=preview`
serves the 1024px detail preview: the API runs `ns-engine.py --preview <id>`, which makes
it on first request and takes no engine lock, and serves the file it names. At most two
previews are made at once.

When there is no image, the answer is `404` with the recorded reason, for the
placeholder:

    {"availability": "pending" | "failed" | "absent" | "unavailable",
     "failure_category": "file_unavailable" | "permission_denied" | "decode_failed" |
                         "cache_write_failed" | "decoder_unavailable" | null,
     "failure_detail": "<text or null>"}

`pending` means not made yet, which is not a failure; `absent` means the engine recorded
the cached file as gone. A cache filename that would resolve
outside the cache root is never served.

## 5. Jobs

### `POST /api/v1/jobs/start`

    {"mode": "index" | "copy" | "move"}                        // the whole source
    {"mode": "move", "file_ids": [101, 102]}                   // selected photos
    {"mode": "copy", "source_subdir": "sd_card/day1"}          // a folder

`202` with the new run (§6).
*   **Validated before anything runs:** mode, one targeting at most, ids as positive
    integers (at most 1,000, the command-line limit; `400 selection_too_large` with
    `limit`), and a folder that stays inside the source. Everything else is
    `400 invalid_request`.
*   **Refusals:** a missing or unusable catalog is `409 catalog_*`, and Copy or Move
    on an empty catalog is `409 catalog_empty`.
*   **One job at a time:** while an engine holds its lock, `409 job_already_running`
    with `active_run: {id, mode, started_at}`. The lock decides, not the runs table. If
    two starts race, the losing engine's refusal is reported the same way.
*   **Learning the run id:** the engine is started with `--request-id` and the API
    waits (up to 30 s) until the engine records the run for that request. An engine that
    exits first is `409 engine_refused` with its own reason, or `500` for an unexpected
    exit. One that never records a run is `500 engine_start_timeout`.

### `POST /api/v1/jobs/{id}/cancel`

`202 {"id": 47, "cancel_requested": true}`: SIGTERM to the engine, which finishes the
file in hand and records the rest (`webui-spec.md` §4.1). Refusals:
*   `404 unknown_run` for an id with no run;
*   `409 not_running` when the job has already finished;
*   `409 not_cancellable` when the engine was started before the API last restarted, so
    this server holds no handle to signal. Stopping the container cancels such a job.

### `GET /api/v1/jobs/active`

    {"active": <Run or null>, "last": <Run or null>}

`last` is the newest run, finished or not. `active` has three special forms:
*   **An engine holds the lock but no run is recorded yet**, while it is starting or
    when one was run by hand: `{"id": null, "status": "Preparing", "unrecorded": true}`.
*   **A run is recorded active but no engine holds the lock**, so it died: it is
    presented with `presented_status: "Interrupted"` and `awaiting_reconciliation: true`.
    The API never writes that; the next engine run records it.
*   **`cancellable`** says whether this server can signal the engine.

### `GET /api/v1/runs/{id}`

One run (§6). `404 unknown_run`.

### `WS /api/v1/ws/jobs`

The live feed for the job drawer. On connect it sends `{"active", "last"}` exactly as in
`GET /jobs/active`, then sends it again whenever it changes, checked about once a second.
A reconnect therefore restores the current state immediately and never restarts a job.

### `GET /api/v1/runs`

The newest runs (`limit`, default 100, at most 500), each as in §6, for choosing a job
in the log: `{"runs": [<Run>, ...]}`.

## 5a. The log and the Error Center

The operations log (`webui-spec.md` §5.4). Filtered to failures, it is the Error
Center (`webui-spec.md` §5.3).

**Filters, shared by the three log routes:**

| Parameter | Meaning |
| :--- | :--- |
| `run` | A job id. Repeat it for several (`?run=4&run=5`): the Stats page links to every run since the last complete scan. |
| `status` | An operation status (repeatable), from the catalog's vocabulary; anything else is `400`. |
| `photo` | A photo's history. It follows the photo's file identities through `operation_files`, including a copy made from it, so a Move or Copy stays in it. |
| `q` | Text in the source path, destination path or recorded message. |
| `since`, `until` | ISO instants, from inclusive to exclusive. The screen converts local calendar days. |

### `GET /api/v1/operations`

One page, newest first (`page`, and `page_size` from 1 to 500, default 100):

    {"items": [{"id", "run_id", "mode", "photo_id", "timestamp", "source_path", "dest_path",
                "status", "error_message", "photo_status", "recovery", "run_level"}, ...],
     "page": 1, "page_size": 100, "total": 4,
     "status_counts": {"Pending": 2, "Copied": 1, "Failed": 1},
     "run_counts": {"1": 2, "2": 2}}

*   **Failures are attempts.** An operation's `status` is the attempt's outcome, and
    `photo_status` is the photo's status now. The two can disagree: a duplicate whose
    verification failed stays `Duplicate` (`webui-spec.md` §5.3).
*   **Photos are left-joined**, so a failure with no photo, such as an unreadable folder,
    is never dropped. `run_level` is true for such a row.
*   **`recovery`** marks a row that settles an earlier run's interrupted work.
*   **`status_counts`** applies every filter except `status`, so each status button can
    show what it would find.
*   **`run_counts`** applies every filter and counts matches per job, keyed by run id,
    so the log can list only the jobs that match and say how many entries each holds.

### `GET /api/v1/operations/export`

The whole filtered log, oldest first, streamed, as `format=csv` (default) or `json`, with
the columns of an item above.

### `GET /api/v1/operations/photo-ids`

`{"photo_ids": [...], "more_than_limit": false, "limit": 1000}`: the distinct photos behind
the filtered operations, for **Retry**, which starts the same mode again with these
`file_ids`. They come from the operations, never from `photos.status`, and rows with no
photo are left out. More than the job limit is reported, never cut silently.

## 5b. Catalog backups

The backup list, Back up now and downloads (`webui-spec.md` §9). The engine writes
every backup; the API starts `--backup-now` and reads what it recorded.

### `GET /api/v1/backups`

Every recorded attempt, newest first, including failed and interrupted ones:

    {"items": [{"attempt_id": 3, "trigger_kind": "manual" | "post_job" | "pre_action",
                "related_run_id": null, "started_at": "...", "ended_at": "...",
                "outcome": "succeeded" | "failed" | "interrupted" | null,
                "error_category": null, "error_detail": null,
                "relative_filename": "ns-catalog-....db.zst", "size": 20237312,
                "compression_format": "zstd" | null,
                "availability": "present" | "missing" | "unknown" | "pruned" | null}, ...],
     "storage": {"ok": true, "error_category": null, "error_detail": null},
     "retention": 20, "automatic_retained": 7, "present_count": 9, "present_bytes": 181000000,
     "last_success": "...", "unbacked": {"count": 0, "since": "...", "runs": []},
     "job_active": false}

`availability` is observed on each request without writing to the catalog: `unknown`
when `/backups` cannot be read, because storage trouble is not evidence that a file was
deleted, and `null` for an attempt that wrote no file. `storage` runs the checks a
backup runs first (missing, unmounted, overlapping `/appdata`, unwritable).
`automatic_retained` is what retention counts, so a client can say how many backups a
lower limit would remove. `unbacked` is `ns_db.unbacked_changes`.

### `POST /api/v1/backups`

Back up now. Waits for the engine, about a second for a large catalog, and returns the
attempt it recorded:

    {"attempt_id": 4, "trigger_kind": "manual", "started_at": "...", "outcome": "succeeded",
     "error_category": null, "error_detail": null, "relative_filename": "...", "size": 20237312}

A failed backup is still `200`: it is a recorded attempt with `outcome: "failed"` and
its category. Refused with `409 job_already_running` while an engine holds the lock,
and with `409 catalog_missing` (or another catalog state) when there is nothing to back up.

### `GET /api/v1/backups/{id}/download`

The file of a succeeded backup, as an attachment under its own name. A backup whose
file is gone, pruned or never written is `404 backup_unavailable`.

## 5c. Stats

### `GET /api/v1/stats`

Everything the Stats page shows, read from the catalog in one pass (`webui-spec.md` §5.9):

    {"library": {"photos", "bytes", "organized", "organized_bytes", "not_organized",
                 "formats": [{"format": "jpg", "photos", "bytes"}, ...],     // most space first
                 "cameras": [{"name", "photos"}, ...], "lenses": [...],       // top eight each
                 "megapixels": [{"band": "under 1 MP", "photos"}, ...], "under_1mp",
                 "orientation": {"landscape", "portrait", "square"}, "with_location"},
     "dates": {"per_year": [{"year", "photos"}, ...], "oldest", "newest",
               "busiest_day": {"day", "photos"} | null,
               "undated", "undated_no_date", "undated_unusable", "with_time_zone"},
     "duplicates": {"groups", "extra_copies", "bytes", "saved_at_destination", "copies_not_written",
                    "move_would_free", "freed_by_moves", "near_duplicates": null,
                    "coverage": {"last_complete_scan" | null, "established_by_run" | null,
                                 "scans_with_issues_since", "run_ids_since": [ids]}},
     "activity": {"jobs": {"INDEX": 3, ...}, "last_index", "copied", "moved",
                  "bytes_transferred", "bytes_per_second" | null,
                  "failures": {"not_an_image": 2, "permission": 1, ...}, "renames", "exif_edits": null},
     "health": {"last_backup", "backup_bytes", "backups", "unbacked_changes", "catalog_bytes",
                "thumbnail_cache": [{"size", "photos", "bytes"}, ...],
                "destination_check": {"at", "findings": {"missing": 1, ...}} | null}}

Counts cover the photos the gallery lists (duplicates are counted apart, in
`duplicates`). Dates count a date taken only; a photo filed by its file time is
`undated`, split into no date in its EXIF and an unusable one. `failures` counts failed
**attempts** by the start of the recorded reason, so one file failing in two jobs counts
twice, as the log lists it. Figures that need unbuilt features (`near_duplicates`,
`exif_edits`) are `null`, never a guess. The duplicate figures follow `webui-spec.md` §5.9:
`move_would_free` is Reclaimable, `freed_by_moves` Reclaimed, and `saved_at_destination`
counts only duplicates whose original is already `Copied` or `Completed`. `coverage`
follows `webui-spec.md` §6.2: `last_complete_scan` and `established_by_run` come from the
last untargeted Index that completed, recorded no run-level failure and scanned every
supported type; `scans_with_issues_since` counts the untargeted Index runs after it that
recorded one; `run_ids_since` lists every run after it, of any mode.

## 6. The run object and its outcome

    {"id": 47, "mode": "INDEX" | "COPY" | "MOVE" | "REBUILD" | "CHECK" | "RENAME",
     "status": "Preparing" | "Running" | "Cancelling" | "Completed" | "Cancelled" |
               "Failed" | "Interrupted",
     "started_at", "ended_at", "reconciled_by_run_id",
     "targeting": {"file_ids": [...]} | {"source_subdir": "..."} | null,
     "progress": [<phase>, ...],
     "outcome": <outcome>}

**`progress`** is the engine's `run_progress` (`engine-spec.md` §4.3): one entry per phase
the run entered, in order, with the last being the current one. Each entry is
`{"phase", "total" (null while unknown), "done", "counts", "started_at", "updated_at"}`,
and `done` is always the sum of `counts`.

**`outcome`** is derived from classified progress, never from `status` alone: a run
where every file failed still ends `Completed` (`webui-spec.md` §5.5).

    {"verdict": "success" | "partial" | "failed" | "no_change" | "cancelled" |
                "interrupted" | "running",
     "succeeded": 2, "failed": 0, "skipped": 1, "cancelled": 0,
     "run_level_issues": 0, "recovered_earlier_work": 0,
     "total": 3, "counts": {"Copied": 2, "Skipped": 1},
     "skip_reasons": {"duplicate": 1}}

*   **Requested work only.** `counts` covers the work the job was asked to do: the scan
    for an Index; the transfer phases for Copy and Move, whose scan is not their work.
    Recovery of earlier runs is `recovered_earlier_work`, and failures with no photo,
    such as an unreadable folder, are `run_level_issues`.
*   **Verdict:** an active status is `running`. A terminal Cancelled, Interrupted or
    Failed wins. Otherwise: successes with no failures or issues are `success`,
    successes with some are `partial`, failures or issues with no successes are
    `failed`, and nothing done is `no_change`.
*   **`skip_reasons`** groups the run's `Skipped` operations by the reason the engine
    recorded: `duplicate`, `duplicate_original_not_selected`, `already_copied`,
    `network_share_unconfirmed`, `source_looked_empty` or `other`. The API
    recognises the reason by how its text begins, and the engine's reason function
    notes the dependency.

## 7. Error codes

| Code | Status | Meaning |
| :--- | :--- | :--- |
| `invalid_request` | 400 | A malformed or disallowed request |
| `selection_too_large` | 400 | More than 1,000 ids; `limit` gives the cap |
| `invalid_settings` | 400 | A setting value the engine would reject |
| `unknown_photo`, `unknown_run` | 404 | No such photo or run |
| `catalog_missing`, `catalog_incompatible`, `catalog_error` | 409 | No usable catalog; nothing was changed |
| `catalog_exists`, `appdata_not_writable` | 409 | Creating a catalog was refused |
| `catalog_empty` | 409 | Copy or Move before anything was indexed |
| `job_already_running` | 409 | Another engine holds the lock; `active_run` names it |
| `engine_refused` | 409 | The engine refused to start; `message` is its reason |
| `not_running`, `not_cancellable` | 409 | Cancel refused (§5) |
| `settings_changed` | 409 | Another save came first; nothing was written |
| `catalog_busy` | 503 | The catalog could not take a settings write in time |
| `backup_unavailable` | 404 | The backup's file is not present to download |
| `engine_start_timeout` | 500 | The engine recorded no run in time |
| `backup_timeout` | 500 | Back up now did not finish in 10 minutes |

## 8. Designed, not built

These are designed in `webui-spec.md` and will be described here when they exist:

*   A live per-operation stream, for replaying a running job's individual events on
    reconnect (`webui-spec.md` §4.1, §5.2). `GET /operations?run=` covers the history;
    the drawer needs only the aggregate feed.
*   The curation actions: rename, the destination check (offered from a lineage
    tree's copy), thumbnail cache controls, and later metadata editing, all of which
    the engine already supports or is specified to (`engine-spec.md` §9).
