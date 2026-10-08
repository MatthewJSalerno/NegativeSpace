# API Specification: NegativeSpace Web API

The HTTP and WebSocket interface between the browser and the engine, as implemented in
`webui/` (`app.py` routes; catalog reads in `catalog.py` and, by area, `gallery.py`,
`outcomes.py`, `oplog.py`, `catalog_backups.py`, `lineage.py` and `stats.py`; `jobs.py`
job control). This document is the reference for what exists. `webui-spec.md` designs the screens that use it;
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
*   **Ownership.** The API creates catalogs through the engine-owned initializer and
    writes settings and UI state through `ns_db.save_settings` and `ns_db.save_ui_state`.
    Photo state and history changes are made by running the engine as a child process,
    from an argument list and never a shell string (`webui-spec.md` §5.6).
    The browser never touches SQLite.
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
     "rejected_with_source": 0,
     "rejects": {"photos": 340, "bytes": 1200000000, "oldest_rejected_at": "<UTC instant or null>",
                 "emptied": {"photos": 1200, "bytes": 4800000000},
                 "reminder": {"over_size": true, "over_age": false,
                              "bytes_limit": 1000000000 | null, "days_limit": 30 | null}},
     "version": {"release": "0.1.0", "branch": "main" | null, "commit": "2c4728f" | null},
     "application_data": "/appdata", "catalog_backups": "/backups",
     "active_job": <Run or null, as in GET /jobs/active>}

`eligible` is how many photos a Copy all and a Move all would take, by the engine's own
rule (`ns_db.TRANSFER_ELIGIBLE`): Copy takes `Pending`; Move also takes `Copied`, deleting
each source against its verified copy, and `Rejected_Copied`, deleting it against its copy
in Rejects. `copied` and `rejected_with_source` are how many of Move's are each of those.
Both count the whole catalog, whatever the gallery's view or search.

`rejects` is what Rejects holds now and what has been emptied from it so far: every
rejected photo whose file is gone from `dest/rejects`, whether or not a job has recorded
it yet. `reminder` says whether Rejects is past either reminder limit
(`webui-spec.md` §7.8): `over_size` at `bytes_limit` or more, `over_age` when its oldest reject is
`days_limit` days old or more. Each limit is a setting; `null` switches it off. `rejects`
is `null` when the catalog cannot be read.

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
     "rejects_reminder_bytes": {"value": 1000000000 | null, "revision": 0, "default": 1000000000},
     "rejects_reminder_days": {"value": 30 | null, "revision": 0, "default": 30},
     "small_image_min": {"value": null, "revision": 0, "default": null},
     "suspicious_min_year": {"value": 1800, "revision": 0, "default": 1800},
     "job_active": false}

`workers.detected` is the number of CPUs the container may use (`ns_db.available_cpus`):
the host's cores, reduced by a CPU set or a CPU quota. `limited_by` names which applies.
The two `rejects_reminder_` settings are the web interface's own, never part of a job's
configuration: a positive whole number, or `null` for off.

### `PUT /api/v1/settings`

Saves the settings that changed, each with the revision it was read at:

    {"values": {"workers": 4}, "revisions": {"workers": 0}}

`200` with the settings as in `GET`. If a revision moved since it was read, another tab
saved first: `409 settings_changed`, and nothing is written. An invalid value is
`400 invalid_settings`, and a catalog too busy to take the write is `503 catalog_busy`.
Processing values apply to jobs started afterwards, never to one already running.
Review rules update subsequent browse and inspection requests immediately.

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
| `view` | `all`, `organized` (Completed, Copied, Found_At_Destination), `unorganized` (Pending, Processing, Failed), `similar` (destination photos with visual matches at `match_min` or higher), `suspicious` (recorded date outside review bounds), `rejects` (Rejected, Rejected_Copied, whose file is still in `dest/rejects`) | `all` |
| `sort` | `newest`, `oldest`, `largest`, `smallest`, `name`, `matches` (`view=similar` only) | `newest` |
| `match_min` | integer percentage 75–100, applies to similarity membership/counts | 75 |
| `q` | filename search: current and original names, including removed duplicates' names; never folder names | none |
| `undated` | `true` for only photos with no EXIF date taken, the ones filed under Undated | `false` |
| `date` | repeatable: a year (`2023`), a month (`2023-06`) or `none` (no date at all); the date tree's "Show only". Several add up | none: every date |
| `type` | repeatable: a file extension, lower case, no dot (`jpg`, `heic`); the Types section's "Show only". Several add up | none: every type |
| `folder` | repeatable: a folder relative to the source (`Phone/2019`), taking its subfolders, or `.` for the files directly in the source folder; the Folders tree's "Show only". Several add up. Matched as a literal path, never a wildcard or case-blind; a path outside the source is `400` | none: every folder |
| `page`, `page_size` | page from 1; 1 to 240 photos | 1, 60 |

    {"items": [{"id": 12, "status": "Pending", "file_size": 3012443,
                "date_taken": "2023-06-05T21:20:00", "date_source": "exif" | "file_mtime",
                "filename": "IMG_0001.jpg", "duplicates": 1,
                "failure": null | "Permission denied", "kept": null | "Read-only file system"}, ...],
     "page": 1, "page_size": 60, "total": 1160,
     "counts": {"all": 1160, "organized": 0, "unorganized": 1160, "undated": 1160},
     "matches": {"all": 1160, "organized": 0, "unorganized": 1160}}

For `view=rejects`, each item's `rejected_at` is when it went to Rejects, and the response
adds `rejects`, as in `GET /status` without `reminder`; other views
return `rejects: null`. A file deleted from `dest/rejects` leaves the view at once: the
API checks against a listing of the folder taken at most every few seconds, and looks up
any file the listing lacks.

`failure` is a `Failed` photo's latest failure reason, made readable as in a run's
`failure_reasons` (§6); `null` for any other status. `kept` is, for a `Copied` photo
whose latest delivery was a Move that could not delete the original, why (a run's
`kept_reasons`); otherwise `null`.

`counts` are each view's whole library, whatever the search, `date`, `type`, `folder` and
`undated` narrow the gallery to; `counts.undated` is how many photos in this view have no
capture date. `total` is what this request shows, every filter applied. `matches` counts
each view’s individual photos with every filter applied, even when `group_sets` makes
`total` count representative sets. `matches.undated` counts this view’s photos with no
capture date under the other filters: the view buttons show these (`webui-spec.md` §2),
and they offer another view when a search finds nothing in this one. The date sorts put undatable rows last.

For `view=similar`, each item includes `similar_count`, and the response includes
`similarity: {threshold, pending, unavailable}`. The coverage counts describe all
eligible destination content identities, not just the filtered page. Other views
return `similarity: null`. Match counts cover direct matches across the whole
available destination library, independent of gallery search/date/type/folder filters.
Zero-count references are omitted. `sort=matches` sorts descending count, ascending
photo ID before pagination; it is invalid with other views (400). Reads never
recompute pHashes or pair distances. Counts, items and coverage share one snapshot.

`match_min` also applies to `/photos/timeline`, `/photos/types`, `/photos/folders`,
`/photos/ids` and the JSON body of `/photos/position`, so facets, selection and
navigation agree. Invalid query/position percentages return 422.

### `GET /api/v1/photos/timeline`

Photos per calendar month for the same `view`, `q`, `undated`, `date`, `type` and `folder`, newest month first:

    {"months": [{"month": "2023-06", "count": 68}, ...], "undated": 0}

`undated` here counts rows with no date at all. A month's first photo in a date sort
sits after every photo sorted before it, which is how the screen jumps to a month's
page. The date tree asks without `date`, so an unticked month keeps its count; a jump
asks with it, to land on the right page of the filtered gallery.

### `GET /api/v1/photos/types`

Photos per file type for the Types section, most first, for the same `view`, `q`,
`undated`, `date` and `folder`, but never `type`, so an unchecked type keeps its count. Only types
the catalog holds are listed:

    {"types": [{"type": "jpg", "photos": 2980}, {"type": "heic", "photos": 212}, ...]}

A type is the extension of the name the photo was indexed under, lower case.

### `GET /api/v1/photos/folders`

The source's folders for the Folders tree, built from catalogued source paths, never a
disk listing, so every folder offered holds photos a job can act on:

    {"folders": [{"path": "Camera/Nikon D750", "name": "Camera / Nikon D750", "photos": 812,
                  "eligible": {"copy": 812, "move": 812}, "folders": [...]}, ...],
     "top_files": {"photos": 4, "eligible": {"copy": 4, "move": 4}}, "outside": 0}

*   **`photos`** counts a folder's photos, subfolders included, for the same `view`, `q`,
    `undated`, `date` and `type`; `folder` does not narrow it, so an unticked folder keeps
    its count. A folder named in `folder` stays listed at 0, so it can be unticked.
*   **`eligible`** is what a Copy or a Move of the folder would take (`--source-subdir`,
    `ns_db.TRANSFER_ELIGIBLE`), whatever the filters: Jobs' "this folder".
*   **`name`** folds a chain of folders, each holding one folder and no photos of its own,
    into one row: `"Camera / Nikon D750"`, with `path` the deepest folder.
*   **`top_files`** are the photos directly in the source folder, in no subfolder
    (`folder=.`). **`outside`** counts shown photos whose source path is outside the
    source folder, from a catalog shared with another source; they are not placed.
*   Folders are ordered by name, letter case ignored, then by exact name.

### `GET /api/v1/photos/ids`

Every photo id the gallery shows for the same `view`, `q`, `undated`, `date`, `type` and `folder`, across
all pages: **Select all**.

    {"ids": [3, 7, ...], "total": 412, "in_rejects": [7]}

All of them, however many: a selection has no fixed limit (`webui-spec.md` §2).
`in_rejects` names those in Rejects: a selection holds library photos or photos in Rejects,
never both, so Select all takes one place and says how many it left out.

**A job's photos.** `GET /photos`, `/photos/ids`, `/photos/timeline`, `/photos/types`,
`/photos/folders` and the body of `POST /photos/position` take `run=<job id>` (a positive
integer, else 422), which keeps the photos that job recorded an outcome for, and
`view=job`, which shows them wherever they are now, library or Rejects (copies a Move
removed are left out, as in every view). Every other filter narrows them. `GET /photos`
then also returns `counts.job`, the job's photos before any filter; the other `counts`
and `matches` keep counting the views, which leave the job.

### `POST /api/v1/photos/position`

Read-only lookup of one photo's zero-based position, one-based page and adjacent
IDs in the gallery's ordering. The JSON body requires positive integer `photo_id`;
optional fields are `view`, `sort`, `page_size` (1–240, default 60), `q`, `undated`,
`dates`, `types`, `folders` and `match_min`, with the same filter meanings as the gallery.
An optional `ids` list (positive integers, any number) scopes a selection instead
of the normal filters. POST keeps that selection out of URL length limits.

    {"photo_id": 7, "sort": "newest", "page_size": 60}
    -> {"position": 80, "page": 2, "previous_id": 8, "next_id": 6}

All four values are null if the photo is absent from that scope. A missing neighbor
is null at the first/last photo. Invalid body types and photo/page-size bounds
return 422. Invalid filter/sort values or nonpositive selection IDs return 400.
There is no selection-count cap; the web proxy's 16 MiB request-body limit still
applies. The server computes rank without returning preceding pages.

### `POST /api/v1/photos/selection`

The selected photos, whatever view, search or dates would hide them (Show only selected):

    {"ids": [3, 7, 99999], "sort": "newest", "page": 1, "page_size": 60}
    ->  {"items": [...as GET /photos...], "page": 1, "page_size": 60, "total": 2, "missing": [99999],
         "in_rejects": [], "actions": {"copy": 0, "move": 2, "reject": 2, "return": 0}}

It reads; it is a POST because a selection's ids are too long for a URL. `missing` names
ids no longer in the catalog, so a selection is never silently shortened. `in_rejects`
names those in Rejects, as for `/photos/ids` (Select all on a job's photos). With
`"action": "copy" | "move" | "reject" | "return"`, `takes` lists the selected photos that
action takes, for its review (any other action is 400). `actions` counts
what each action would take of the whole selection, for the selection bar: Copy and Move by
the engine's own rule (`ns_db.TRANSFER_ELIGIBLE`, as `eligible` in `GET /status`), Reject
(photos in the library) and Return to library (photos in Rejects).
`sort=matches` with optional integer `match_min` (default 75) orders an explicit
selection by library-wide counts without filtering out selected files. This also
works for `/photos/position` when `ids` is supplied. Items without an available
representative/usable hash have `similar_count: null` and sort after known zero
counts; ties use ascending ID. An invalid selection percentage returns 400.

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
                     "files": [{"file_id", "role": "source" | "destination" | "retained_copy"}]}, ...],
     "selected_by": [{"run_id", "mode", "status", "started_at"}, ...]}

`files` holds the photo's source file and every file descended from it (a copy records
the file it came from; an indexed file records itself as its own origin), and the same
for each duplicate. `matches` says whether the file's recorded
content is the photo's. `operations` is every operation that touched any of them, oldest
first, with the role each file played. `selected_by` is every job the photo was chosen for
in a selection (`run_selections`), whatever that job then did with it. A copy's size is
its origin's: it was verified byte for byte when made. An unknown photo is `404 unknown_photo`.

### `GET /api/v1/photos/{id}/thumbnail`

`size=grid` (default) serves the 320px grid thumbnail from the cache. `size=preview`
serves the 1024px detail preview: the API runs `python -m engine --preview <id>`, which makes
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
    {"mode": "reject" | "return", "file_ids": [101]}           // Reject, Return to library

Reject and Return to library need `file_ids` or `source_subdir`; without one, `400`.
`202` with the accepted run (§6). An optional `request_id` uses 1–128 ASCII
letters, digits, underscores or hyphens. The browser always supplies a random ID
saved before sending. Legacy callers omitting it receive a server-generated ID.
An accepted ID with the same normalized request returns its original run without
spawning, even during a different active job; different input returns
`409 request_conflict`. Acceptance is durable in the engine's `job_requests` table.
*   **Validated before anything runs:** mode, one targeting at most, ids as positive
    integers no greater than `2^63 - 1`, never more ids than the catalog holds photos (no
    other limit), and a folder that stays inside the source. Everything else is
    `400 invalid_request`. A request body is at most 16 MB (the web container's
    proxy), about 1.5 million ids.
*   **A selection reaches the engine in a file**, never on its command line: written under
    application data (`selections/<request_id>.ids`, the folder `0700`, the file `0600`),
    named by the request ID only, and removed once the engine has recorded it with the run
    or stopped (`engine-spec.md` §4.1). If any photo is no longer catalogued in this source
    the engine refuses the whole job, recording nothing: `409 engine_refused` with the
    reason.
    Failure to prepare the selection is `503 selection_unavailable`; this attempt
    starts no engine. Publication failure removes the temporary or final file only
    when it still identifies the file this attempt created, preserving pre-existing
    inputs. After successful cleanup, retry with the same request ID once the
    storage fault is corrected. Cleanup errors are reported rather than hidden.
    Publication and cleanup hold an exclusive OS lock on
    `selection-start.lock` under application data. The API passes that open
    descriptor to its engine child, so an API crash cannot release the child's
    protection before it reads the selection. The lock file is never unlinked;
    each holder closes its descriptor instead of explicitly unlocking the shared
    description. The child closes its descriptor as soon as it has read the selection
    (named to it in `NS_SELECTION_LEASE_FD`), so a finished job never refuses the next
    selected start.
    Startup skips cleanup while this lock is held. Startup and the next selected
    submission reclaim abandoned regular files owned by the API user only while
    holding the lock: `<request_id>.ids` and `.<request_id>.ids.tmp`, with valid
    request-ID spelling. Unrelated names, directories and symlinks are preserved.
    A selected submission that cannot acquire the lock returns
    `409 job_already_running`, including before the engine has recorded a run.
    An already accepted request still replays its existing run.
    Folder names preserve significant whitespace, including whitespace-only components;
    browsing and starting a folder job use the same literal names.
*   **Refusals:** a missing or unusable catalog is `409 catalog_*`, and Copy or Move
    on an empty catalog is `409 catalog_empty`.
*   **One job at a time:** while an engine holds its lock, `409 job_already_running`
    with `active_run: {id, mode, started_at}`. The lock decides, not the runs table. If
    two starts race, the losing engine's refusal is reported the same way.
*   **Learning the run id:** the engine is started with `--request-id` and the API
    waits (up to 30 s) until the engine records the run for that request. An engine that
    exits first is `409 engine_refused` with its own reason, or `500` for an unexpected
    exit. One that never records a run is `500 engine_start_timeout`.
    Failure to open the engine log or spawn the process is `500 engine_start_failed`;
    the selection is cleaned up and the same request ID can be retried after correcting
    the reported storage or process-permission error. These 5xx responses retain the
    browser's existing Check again / Retry same request workflow.

### `POST /api/v1/runs/{id}/answer`

Answer a safety question from the latest settled run. The body contains
`question`, `answer` and optionally `request_id`; scope overrides and other fields
return 400. Accepted answers support the same replay semantics as Start, including
replay after the original question has become stale.

| Question | Answers |
|---|---|
| `source_empty` | `retry` after reconnecting storage; `confirm_empty` after verifying it is really empty |
| `network_destination` | `copy` (recommended); `confirm_move` after explicitly confirming storage durability |

Returns 202 with the new run. The server restores the original mode and exact
photo-ID/folder/whole-source scope; `copy` changes only Move to Copy. The stored
source and destination roots must still match configuration. An active job, stale
or resolved question, or changed roots returns 409. Answering starts a new engine
run; the API does not resolve attention records itself. Explicit confirmations
carry through consecutive answers in the same retry chain, never through a new
ordinary Start. Leave unchanged is a client dismissal and starts nothing.

Run responses include `questions`, a list of `source_empty` and/or
`network_destination` for the latest settled run with a still-open refusal. Older
runs have an empty list. The job feed includes this field too. Ordinary job Start
accepts only mode, file_ids, source_subdir and request_id; unsupported fields, including direct
confirmation flags, return 400 rather than being silently ignored.

### `GET /api/v1/job-requests/{request_id}`

Returns `{"state":"accepted","run":{...}}` for that exact durable acceptance,
including completed jobs and jobs preceding newer submissions from other tabs.
Otherwise returns `{"state":"unknown","run":null}`. A missing row is not proof
that an in-flight request cannot still be accepted. No job is started by lookup.
Invalid request-ID syntax returns 400. Database read failures are errors, not an
unknown/no-job answer.

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
The client sends nothing; the feed ends as soon as the connection closes, including when
the server shuts down, so an open page never holds up `docker stop` or the shutdown that
cancels a running job (`tests/shutdown_test.sh`).

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
| `status` | An operation status (repeatable), from the catalog's vocabulary or `Copied_Only`; anything else is `400`. |
| `photo` | A photo's history: the photo, the files made from it (through `operation_files`, so a Move or Copy stays in it) and its exact duplicates, however they arrived; the same set as its lineage tree (`webui-spec.md` §6.3). |
| `q` | Text in the source path, destination path or recorded message. |
| `since`, `until` | ISO instants, from inclusive to exclusive. The screen converts local calendar days. |

### `GET /api/v1/operations`

One page, newest first (`page`, and `page_size` from 1 to 500, default 100):

    {"items": [{"id", "run_id", "mode", "photo_id", "timestamp", "source_path", "dest_path",
                "status", "error_message", "photo_status", "recovery", "run_level"}, ...],
     "page": 1, "page_size": 100, "total": 4,
     "status_counts": {"Pending": 2, "Copied": 1, "Failed": 1},
     "run_counts": {"1": 2, "2": 2}}

*   **`Copied_Only`** is derived, never stored: a Move's operation recorded `Copied` with
    a message starting "The original could not be removed" (`engine-spec.md` §4.2). The
    `status` column, `status_counts` and the `status` filter all use it, so `Copied`
    finds only real Copies.
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

`{"photo_ids": [...]}`: the distinct photos behind the filtered operations, all of them,
for **Retry**, which starts the same mode again with these `file_ids`. They come from the
operations, never from `photos.status`, and rows with no photo are left out.
`requested_only=true` also leaves out rows settling an earlier job's interrupted work
(`reconciles_operation_id`), so a retry of a selection names only photos it held.

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
     "small_image_min": {"value": null, "revision": 0, "default": null},
     "suspicious_min_year": {"value": 1800, "revision": 0, "default": 1800},
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

Recorded filenames are resolved within the configured backup directory. A symlink
escaping that root is unavailable (404), and the list reports it as missing.

The file of a succeeded backup, as an attachment under its own name. A backup whose
file is gone, pruned or never written is `404 backup_unavailable`.

## 5c. Stats

### `GET /api/v1/stats`

Everything the Stats page shows, read from the catalog in one pass (`webui-spec.md` §5.9).
The `library` photo totals/traits and `dates` cover Library and Not organized, excluding
Failed source records; `library.failed_source` counts these separately. Rejects totals
and activity failure-attempt counts have their own scopes:

    {"library": {"failed_source", "photos", "bytes", "organized", "organized_bytes", "not_organized",
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
                                 "scans_with_issues_since", "run_ids_since": [ids]},
                    "by_folder": [{"folder": "archive-2021", "files", "duplicates", "duplicate_bytes"}, ...]},
     "activity": {"jobs": {"INDEX": 3, ...}, "last_index", "copied", "moved",
                  "bytes_transferred", "bytes_per_second" | null,
                  "failures": {"not_an_image": 2, "permission": 1, ...}, "renames", "exif_edits": null},
     "health": {"last_backup", "backup_bytes", "backups", "unbacked_changes", "catalog_bytes",
                "thumbnail_cache": [{"size", "photos", "bytes"}, ...],
                "destination_check": {"at", "findings": {"missing": 1, ...}} | null},
     "rejects": {"photos", "bytes", "oldest_rejected_at", "emptied": {"photos", "bytes"}}}

Photo counts cover indexed/organized catalog entries except Failed sources and Rejects;
failed sources are counted in `library.failed_source`, and duplicates separately in
`duplicates`. Dates count a date taken only; a photo filed by its file time is
`undated`, split into no date in its EXIF and an unusable one. `failures` counts failed
**attempts** by the start of the recorded reason, so one file failing in two jobs counts
twice, as the log lists it. Figures that need unbuilt features (`near_duplicates`,
`exif_edits`) are `null`, never a guess. `rejects` is as in `GET /status`. The duplicate figures follow `webui-spec.md` §5.9:
`move_would_free` is Reclaimable, `freed_by_moves` Reclaimed, and `saved_at_destination`
counts only duplicates whose original is already `Copied` or `Completed`. `coverage`
follows `webui-spec.md` §6.2: `last_complete_scan` and `established_by_run` come from the
last untargeted Index that completed, recorded no run-level failure and scanned every
supported type; `scans_with_issues_since` counts the untargeted Index runs after it that
recorded one; `run_ids_since` lists every run after it, of any mode. `by_folder` counts, per top-level folder
of the source (`""` for files directly in it), every file catalogued there and how many
are duplicates of photos catalogued earlier, with their size: the copy indexed first is
the original, so a later archive carries the duplicates.

## 6. The run object and its outcome

    {"id": 47, "mode": "INDEX" | "COPY" | "MOVE" | "REBUILD" | "CHECK" | "RENAME" | "SIMILARITY",
     "status": "Preparing" | "Running" | "Cancelling" | "Completed" | "Cancelled" |
               "Failed" | "Interrupted",
     "started_at", "ended_at", "reconciled_by_run_id",
     "targeting": {"selection": 2, "sha256": "..."} | {"source_subdir": "..."} | null,
     "progress": [<phase>, ...],
     "outcome": <outcome>}

**`targeting`** for a selection is its size and the checksum of its ids, never the ids,
which can run to hundreds of thousands: they are recorded with the run in
`run_selections`, and each photo's lineage lists the jobs it was chosen for.

**`progress`** is the engine's `run_progress` (`engine-spec.md` §4.3): one entry per phase
the run entered, in order, with the last being the current one. Each entry is
`{"phase", "total" (null while unknown), "done", "counts", "started_at", "updated_at"}`,
and `done` is always the sum of `counts`.

**`outcome`** is derived from classified progress, never from `status` alone: a run
where every file failed still ends `Completed` (`webui-spec.md` §5.5).

    {"verdict": "success" | "partial" | "originals_kept" | "none_succeeded" | "no_change" |
                "stopped" | "cancelled" | "interrupted" | "running",
     "succeeded": 2, "failed": 0, "skipped": 1, "cancelled": 0, "copied_only": 0,
     "run_level_issues": 0, "recovered_earlier_work": 0,
     "total": 3, "counts": {"Copied": 2, "Skipped": 1},
     "skip_reasons": {"duplicate": 1},
     "failure_reasons": {"Permission denied": 1},
     "kept_reasons": {"Read-only file system": 4681}}

*   **Requested work only.** `counts` covers the work the job was asked to do: the scan
    for an Index; the transfer phases for Copy and Move plus prerequisite scan
    failures that prevented delivery. These scan failures contribute `failed` to
    `counts` and increase the requested total; successful or unchanged scans do not
    count again as transfers. An unfinished phase may still leave `total` unknown.
    Recovery of earlier runs is `recovered_earlier_work`, and failures with no photo,
    such as an unreadable folder, are `run_level_issues`.
*   **Verdict:** an active status is `running`. A terminal Cancelled, Interrupted or
    Failed wins (`cancelled`, `interrupted`, `stopped`: an error ended the job).
    Otherwise: a Move with copied-only photos and no failures or issues is
    `originals_kept`; successes with no failures or issues are `success`; failures or
    issues alongside successes, copied-only photos or skips (an Index's unchanged files)
    are `partial`; failures or issues with nothing else are `none_succeeded`; and nothing
    done is `no_change`. A job that ran to its end is never called failed.
*   **`copied_only`** is, for a Move, its photos copied but not moved because the
    original could not be deleted (the `Copied` count of a Move). They are not in
    `succeeded`, nor in `failed`; `kept_reasons` groups them by reason, made readable as
    `failure_reasons` are.
*   **`skip_reasons`** groups the run's `Skipped` operations by the reason the engine
    recorded: `duplicate`, `duplicate_original_not_selected`, `already_copied`,
    `network_share_unconfirmed`, `source_looked_empty` or `other`. The API
    recognises the reason by how its text begins, and the engine's reason function
    notes the dependency.
*   **`failure_reasons`** groups the run's `Failed` operations (recovery excluded) by
    their recorded reason made readable: the exception name, error number and quoted
    path are removed (`catalog.failure_reason`), so `OSError: [Errno 30] Read-only file
    system: '/data/source/a.jpg'` counts under `Read-only file system`.

Browser mutation requests and the job WebSocket must name the same public host
and port in `Origin` as in `Host`; explicit cross-site requests without an Origin
are also refused. HTTP mutations return 403 `cross_origin_request`; the WebSocket
is refused before acceptance (policy code 1008). Nonbrowser clients without these
headers remain supported. This is a browser boundary, not sign-in or a Host allowlist.
Reverse proxies must preserve the public Host, including a nondefault port.

## 7. Error codes

| Code | Status | Meaning |
| :--- | :--- | :--- |
| `cross_origin_request` | 403 | A foreign browser origin attempted a mutation |
| `invalid_request` | 400 | A malformed or disallowed request |
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
| `engine_start_failed` | 500 | The log could not be opened or the engine process could not be spawned |
| `selection_unavailable` | 503 | The selection input could not be prepared; this attempt started no engine |
| `backup_timeout` | 500 | Back up now did not finish in 10 minutes |

### `GET /api/v1/similar`

Read-only destination matching queue. Query: `mode=similar|exact` (default `similar`),
`threshold=75..100` (default 90), `sort=matches|newest|oldest|name|largest`,
`q` (literal filename substring), `page` (positive, default 1), `page_size`
(1–60, default 30). Unknown mode/sort returns 400; numeric validation errors return 422.

The Similar screen uses visual matching only. The API retains exact mode for
compatibility and diagnostic use; exact-copy details remain in the Inspector.

Returns `items`, `total`, `page`, `page_size`, `query_ms` (server query duration), and `state` with counts `photos`,
`unavailable` (no usable visual hash), and `pending` (awaiting comparison).
Each item contains `id`, `filename`, `file_size`, `date_taken`, `status`, `width`,
`height`, and `matches`. Only destination photos with matches appear. Eligibility
requires status `Copied`, `Completed` or `Found_At_Destination` and a recorded
present file at `dest_path` with matching SHA-1. Source-only photos and projected
destinations are excluded; `state` counts only eligible destination content. The
legacy exact mode uses the same destination eligibility;
visual mode collapses identical bytes to one representative, exact mode retains
available photo records. Exact mode ignores the visual threshold. File availability
is catalog evidence, not a live filesystem verification. Missing/incompatible catalogs
use the existing 409 errors.

### `GET /api/v1/similar/{id}`

Reference-based results with the same mode, threshold, and pagination parameters.
`scope=library|rejects` (default `library`) chooses candidate location; unknown scopes
return 400. References may be active Library photos or still-present rejected photos.
Rejected eligibility requires a present matching-digest destination file state and the
Rejects gallery's cached presence check. Emptied rejects and source-only photos are
excluded. Both scopes collapse byte-identical candidates independently. Library gallery
counts/groups and the queue remain Library-only; changing this scope does not affect them.
Returns `reference`, `items`, `total`, `page`, `page_size`, `state`, and
`availability` (`available`, `hash_unavailable`, or `not_available`). Unknown or
source-only or historical-only references return 200 with `reference: null`, empty items and
`not_available`. Each match has `score` (visual percentage rounded to two decimals,
100 for exact copies); filtering uses the unrounded Hamming distance. Available
results also include `largest_pixels` over the reference and all matching pages,
or null for unknown dimensions. Matches are relative to the reference, never
transitive. A direct link to another eligible destination copy resolves its content in visual mode.
Incomplete comparisons are reported through `state.pending`; no results with
pending work do not establish uniqueness.

### `GET /api/v1/similar/{id}/counts`

Cumulative direct-match counts for a Library or still-present rejected reference at thresholds
75, 80, 85, 90, 95 and 100. `scope=library|rejects` chooses candidates (default Library; invalid scope returns 400). Returns `availability` (`available`, `not_available`,
`hash_unavailable`), `counts: [{threshold, count}]`, and `pending` (number of
eligible destination content identities awaiting comparison). Unavailable references
return an empty counts array, not six misleading zero counts. Counts exclude the
reference byte identity and collapse exact copies; they include equal visual hashes
of different content. One aggregate over stored pairs supplies all thresholds.

The gallery's `view=similar` uses the same destination availability and content
representation rules, at `match_min` (75% by default). Search/date/type/folder filters narrow the
reference photos, not their potential matches. Timeline, type/folder counts, photo
positions and selection IDs use the same view predicate. Gallery `counts` and
`matches` include the `similar` key.

### `GET /api/v1/similar/diagnostics`

Returns `state` (as in the matching queue), `distinct_hashes` (usable visual hashes
across all content), `stored_pairs`, `query_ms`, and `last_comparison`. The latter is null if no matching
progress exists, otherwise `{run_id, started_at, updated_at, elapsed_seconds}`;
elapsed is the interval covered by the latest reported phase snapshot, not CPU time.
Equal hashes do not need stored pairs.

### `GET /api/v1/similar/recovery`

Paged affected destination identities: `page` (positive, default 1), `page_size`
(1–60, default 30), optional positive 64-bit `photo_id` for one content identity.
Returns `items: [{id,filename,kind,reason,message,retryable,action}]`, `total`, `retryable`
(the count in this scope), `generatable` (missing hashes without recorded failures), `page`, `page_size`, and global destination
`state: {unavailable,pending}`. `kind` is `missing_hash` or `pending`; reasons
separate unsupported formats, decoding/read errors, missing/changed/out-of-root
files and unperformed comparisons. Recorded destination availability is the scope;
physical verification happens in the recovery job. Source-only photos are excluded.

### `POST /api/v1/similar/recovery`

Body: `{scope: "missing" | "comparisons", photo_id?: integer, request_id?: string}`.
`photo_id` applies only to missing-hash recovery. Without it, `missing` generates
only hashes without a recorded failure; with it, the request explicitly rechecks
that photo after the stated external correction. Unsupported formats stay excluded.
Item `action` is `generate`, `recheck`, or null; `retryable` alone does not mean
the file belongs in bulk generation. Unknown options/invalid scopes
return 400. The response is 202 with the accepted `SIMILARITY` run. Engine locking,
409 busy refusal, durable request-ID replay/conflicts, job lookup and cancellation
use the existing job protocol. The UI uses the existing uncertain-submission tracker.
Missing-hash recovery reads verified destination originals, updates matching data,
then resumes unfinished stored-hash comparisons. Comparison-only recovery reads no
photos. Counts/progress and per-photo reasons show unsuccessful attempts; a settled
job is not a claim that all affected photos were repaired. Nothing edits or deletes
photo files, and interrupted filesystem mutations are not resumed by this job.

### `GET /api/v1/similar/{id}/pair/{other_id}`

Two photos for side by side: any two different eligible destination photos, in Library or still-present in Rejects. Each status identifies its location; source-only and emptied-reject pairs return 409. Below-threshold pairs are allowed. Returns `reference` and `candidate` (matching item
fields plus `sha1`), `exact` (same content identity), `distance` (0–64, null without
usable hashes) and `score` (hash percentage or null). Unknown, identical-ID or
unavailable photos return 409 `pair_changed`. It reads only; deciding between the two is
Reject or Keep this one, reject the rest for Library photos, or Return for a rejected photo (§5).

## 7a. Additional gallery browsing

### Suspicious-date browsing

Gallery browse endpoints accept `view=suspicious` with their existing filters.
Photo list/selection items and Inspector details expose nullable `date_warning`.
The view selects ordinary visible photos whose recorded `date_taken` year is before
1800 or greater than the current UTC year plus one. Null dates are not flagged.
Counts, IDs, positioning and sidebar endpoints share this predicate. This is a
read-time hint; neither metadata nor catalog schema changes.

### `GET /api/v1/similar/{id}/sets`

Read-only reference-set exploration. Parameters: integer `threshold` 75–100 (90 by
default), repeated `include` canonical reference IDs (at most six; each must directly
match the starting reference), `page`, `related_page` (positive, default 1), and
`page_size` (1–24, default 12). Missing/unusable/noncanonical references or stale
expansions return 400; parameter validation returns 422. Pages clamp to the last page.

Returns `reference`, chosen `references` with total member counts, deduplicated
`items` with `references` (membership IDs), `direct` relative to the starting
reference and nullable recorded `score`; `total`, `page`, `page_size`; `related`
with set totals and `additional` members outside the starting set, `related_total`,
`related_page`; `threshold`, `state: {pending, unavailable}`, and `max_related`.
Members include their own reference. Root-first ordering then minimum recorded
distance/ID is applied before paging; related references order by distance/ID.
Gallery filters do not constrain members. Identical SHA-1 identities are represented
once; equal visual hashes of different identities remain separate photos. Queries
use existing stored relationships in one snapshot, make no photo reads or writes,
and do not recalculate hashes or persist groups. Expansion is one hop, never recursive.

Identical membership in Explore related sets follows the gallery rule: exclude sets
identical to the starting set and show each remaining full-membership set once, before
related-set counting and pagination. Compare exact membership at the selected percentage,
not photo counts; a proper subset is still a distinct overlapping set. Choose the lowest
canonical photo ID among the starting reference's direct matches for each distinct set.
No other distinct sets produces an explicit empty message. Changing reference does not
choose a keeper or modify photos.

Inspector responses also include nullable `visual_issue` describing recorded missing
or failed visual hashing. Recovery failure operations use mode SIMILARITY/status
Failed with a photo ID, path and detailed `error_message`; the photo's delivered
status remains unchanged. Older jobs without these entries are not backfilled.

### Identical-set gallery browsing

The photo list, IDs, timeline, types and folders GET endpoints accept optional
`group_sets` (boolean, default false). The photo-position POST body accepts the same
boolean. It applies to `view=similar` or an explicit `similar=true`, including
`view=review`; explicit selection lists remain ungrouped. Representatives are selected
inside the requested view/inbox before collapsing, so reviewed photos outside the inbox
cannot hide remaining review members. The UI sends `group_sets=false` while additional
filters/search are active; the API retains filtered representative browsing.
Exact closed neighborhoods (reference plus all direct destination matches at
`match_min`) collapse before pagination and ordering. Lowest canonical ID among
references satisfying filters represents each identical set. Filtering never narrows
set membership. Different neighborhoods with equal counts stay separate.

List `total` and returned IDs/positions describe representatives; per-photo
`similar_count` still counts direct matches. `counts` remain uncollapsed library photo counts; filter-aware `matches`
supply the view buttons. Sidebar queries count representatives in their normal filter
scope. `matches` for other views retains normal photo-filter semantics. No photo,
EXIF, persisted group, or catalog schema is changed. Without `group_sets`, existing
API behavior is unchanged.

### Direct-set member gallery filter

GET /api/v1/photos, GET /api/v1/photos/ids and POST /api/v1/photos/position accept
optional `set_reference` (positive signed-64-bit photo ID). It intersects the normal
browse scope with that reference plus its recorded direct destination matches at
`match_min`. It excludes source-only/unavailable identities and does not recursively
expand related sets. The UI uses this filter without grouped collapse or saved
gallery filters for its temporary member scope. Pagination, sorting, photo positioning
and Select all operate on the resulting scope without a fixed selection limit. Unknown or unavailable references
produce an empty scope. This is a read-only catalog filter, not an engine command.

For `set_reference`, `view=all` also permits `sort=matches`, retaining a usable
reference with zero qualifying candidates. The member-gallery UI uses this scope;
it does not accidentally drop the reference through the Has similar photos filter.

### `GET /api/v1/photos/{photo_id}/review`

Returns current `reasons` (reason, label, message), location, content SHA-1,
`revision` and descending review `history`. Reasons currently implemented: `small`
and `later`. A missing photo returns 404 `unknown_photo`. This endpoint only reads.

### `POST /api/v1/photos/{photo_id}/review`

Body: `photo_id`, `sha1` (string or null), `revision` (nonnegative integer), `reason`,
`action`, `note` (up to 500 characters), `request_id` (1–128 alphanumeric, underscore
or hyphen characters). Actions: small/reviewed, later/later, later/done. The engine
records the decision under its lock; no photo files or selection are changed.
Returns the current review detail on success. Identical request replay is idempotent.
400 `invalid_request` rejects malformed input; 409 `review_changed` refuses stale
content/revision, photos outside Library, or conflicting request reuse; 409 `job_already_running` refuses a
busy engine; 503 `review_unavailable` means the result could not be confirmed, so
reload before retrying. Success is shown only after acknowledgement.

### Composable review browsing

Gallery listing, IDs, position, types, folders and timeline accept `similar` and
`suspicious` booleans and `reason` (all/small/later). These combine with existing
filters. `view=review` selects distinct active Library photos with an unresolved supported reason. Reminders on source/rejected files do not contribute. History remains readable; new decisions require a delivered active photo.
Listings include `chips` (similar/suspicious/undated/small), `reasons` and filename-only
`elsewhere` location counts. `reason=small` filters Library as well as the inbox, using
unacknowledged destination size reminders; it never restricts imports. Chip counts
apply the other current filters; the small count evaluates that reminder scope.
Review and organized/similar cards include compact location and current reason details
(`review: {location,reasons}`), without decision history. Full history remains in the
per-photo review endpoint. Unorganized listings include `index_summary` (null elsewhere):
`photos` (all remaining source records), `ready` (Pending), `unfinished` (Processing),
`duplicates` (extra Duplicate records sharing content with a remaining source
photo), `small`, `minimum` (null when disabled), `unknown_dimensions`, `suspicious`,
`undated`, `failed` and `similar` (null: source comparisons are uncalculated), plus
`last_index` (`{id, started_at}` for the latest Index with an end time, or null). This
identity scopes browser dismissal to that Index; other jobs do not reset it. The summary
is unfiltered and catalog-only, with no filesystem reads. Size/date facts exclude Failed/Processing rows and describe only Pending photos. Existing view names remain accepted
for old links. The UI offers organized (Library), unorganized (Not organized), rejects
and review, with similarity/date conditions as chips. Settings adds
`small_image_min`, a positive integer shorter-side minimum or null (disabled).

The matches response also supplies `largest_match` (photo details or null), selected
across the complete matching set rather than the current page. This is evidence for
small-image review, never an automatic selection or quality judgment.

The catalog setting `suspicious_min_year` accepts an integer from 1 to 9999 (default
1800). It uses the same revision-checked Settings API. A recorded year strictly below
it is suspicious; the future-year rule remains current UTC year + 1. The photo-list
response includes `date_min_year` so its policy text agrees with its query results.
Changing the setting changes browse/inspection results, never recorded metadata.

## 8. Designed, not built

These are designed in `webui-spec.md` and will be described here when they exist:

*   A live per-operation stream, for replaying a running job's individual events on
    reconnect (`webui-spec.md` §4.1, §5.2). `GET /operations?run=` covers the history;
    the drawer needs only the aggregate feed.
*   The curation actions: rename, the destination check (offered from a lineage
    tree's copy), thumbnail cache controls, and later metadata editing, all of which
    the engine already supports or is specified to (`engine-spec.md` §9).
