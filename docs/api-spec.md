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
    never presented as UTC (`webui-spec.md` §10). File times (`file_created`,
    `file_modified`) are epoch seconds.

## 2. Catalog

### `GET /api/v1/status`

The first screen's state. It never creates anything.

    {"state": "missing" | "ok" | "incompatible" | "error", "detail": "<reason or null>",
     "photos": 1160, "indexed": true,
     "application_data": "/appdata", "catalog_backups": "/backups",
     "active_job": <Run or null, as in GET /jobs/active>}

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
| `page`, `page_size` | page from 1; 1 to 240 photos | 1, 60 |

    {"items": [{"id": 12, "status": "Pending", "file_size": 3012443,
                "date_taken": "2023-06-05T21:20:00", "date_source": "exif" | "file_mtime",
                "filename": "IMG_0001.jpg", "duplicates": 1}, ...],
     "page": 1, "page_size": 60, "total": 1160,
     "counts": {"all": 1160, "organized": 0, "unorganized": 1160, "undated": 1160}}

`counts` apply the search and the `undated` filter to each view. `counts.undated` is how
many photos in this view and search have no capture date, whether or not the filter is
on, for the filter's label. The date sorts put undatable rows last.

### `GET /api/v1/photos/timeline`

Photos per calendar month for the same `view`, `q` and `undated`, newest month first:

    {"months": [{"month": "2023-06", "count": 68}, ...], "undated": 0}

`undated` here counts rows with no date at all. A month's first photo in a date sort
sits after every photo sorted before it, which is how the screen jumps to a month's
page.

### `GET /api/v1/photos/{id}/inspect`

The Inspector's details. `404 unknown_photo` for an id the catalog does not hold.

    {"id", "status", "filename", "source_path", "dest_path",
     "dest_path_is_projection": true,     // not delivered: where it would go
     "has_collision_rename", "file_size", "width", "height",
     "file_created": null,                // epoch seconds; many storages record none
     "file_modified": 1686000000.0,       // as the first scan observed it
     "date_taken", "date_source", "date_offset",
     "exif_dates": [{"field": "taken" | "digitized" | "modified",
                     "value": "2021:05:01 10:00:00", "offset": "+02:00" | null}],
     "camera", "iso", "aperture", "shutter", "sha1", "phash",
     "duplicates": [{"id", "status", "source_path", "dest_path", "file_size"}],
     "thumbnail": {"availability": "present" | "failed" | "pending",
                   "failure_category", "failure_detail"}}

`exif_dates` lists only the dates EXIF holds, each with the offset tag that pairs with
it (`OffsetTimeOriginal`, `OffsetTimeDigitized`, `OffsetTime`).

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
| `engine_start_timeout` | 500 | The engine recorded no run in time |

## 8. Designed, not built

These are designed in `webui-spec.md` and will be described here when they exist:

*   `GET /api/v1/runs/{id}/operations`: a run's operation history, for logs and
    reconnect replay (`webui-spec.md` §4.1, §5.2).
*   `GET /api/v1/operations?status=Failed`: the Error Center (`webui-spec.md` §5.3).
*   `GET /api/v1/stats/duplicates`: the Dashboard's duplicate-space figures and
    coverage (`webui-spec.md` §5.9).
*   Logs, backups (list and download), and the curation actions: rename, destination
    check, thumbnail cache controls, and later metadata editing, all of which the
    engine already supports or is specified to (`engine-spec.md` §9).
