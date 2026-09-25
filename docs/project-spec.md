# Project Design Specification: NegativeSpace

This is the entry point. It states what the project is for, where its boundaries
are, and what exists today. The detail lives in two component specifications:

*   **[engine-spec.md](./engine-spec.md)** — `ns-engine.py`: reading source
    files, hashing, metadata, placement, the Copy-Verify-Delete protocol, and the
    SQLite catalog it owns.
*   **[webui-spec.md](./webui-spec.md)** — the browser-facing half: job
    management, selection, settings, logs, inspection, and the curation
    workflows.
*   **[api-spec.md](./api-spec.md)** — the web API as implemented: every route,
    its parameters, responses and errors, kept in step with the code by CI.

**These are organized by component, not by release phase.** Why not phases: a
phase document mixes engine work that must happen first with UI work that belongs
with the rest of the UI, and its open questions end up with deadlines inside other
phases. A seam between *the thing that touches files* and *the thing a person
clicks* stays stable; a seam between release numbers does not.

## 1. Project Overview

**Objective:** A web-based application that automates the organization of large,
complex photo collections.

**Core Problem:** Users struggle with redundant files, non-standardized directory
structures, and inconsistent metadata across multiple devices and exports.

**Scope boundary — this organizes a library, it does not present one.** The
deliverable is a structured, de-duplicated collection on disk, curated by its
owner and self-describing enough to stand alone: ready to be imported by a
multi-user gallery application such as Immich, which will organize, index and
display it by its own rules. Galleries, sharing, browsing for pleasure and
multi-user access are somebody else's job.

Two consequences follow, and both shape decisions in each component spec:

*   **The `YYYY/MM/DD` tree is for the human browsing the filesystem, not a
    contract with any consuming application.** A gallery app re-organizes on
    import; it reads paths and embedded metadata, not this project's directory
    conventions. So folder-layout questions are usability questions, not
    correctness ones.
*   **Metadata correctness is a deliverable.** The consuming application reads
    EXIF from the files themselves, never from this project's SQLite catalog —
    which holds catalog information, settings and irreplaceable operation history.
    Development catalogs may be disposable, but user history is not reconstructible
    from photo files. A date this project knows but the
    file does not is a date the gallery will get wrong. That is what eventually
    forces metadata corrections out of the catalog and into the files, or into
    sidecars beside them; see `engine-spec.md` §9.6.

## 2. Target Audience

**Photo-format scope:** this is a photo organizer, not a general-purpose image
manager. Do not expand format support solely to edit metadata in arbitrary image
formats. Where a selected photo cannot store requested embedded metadata, report
that limitation and leave it unchanged; no automatic sidecar or catalog-only edit
fallback. Existing indexing support is not a promise of metadata-write support.
This scope decision does not remove formats from the current engine.

*   **Primary:** Professional photographers and content creators managing
    thousands of assets.
*   **Secondary:** General users with large, unorganized mobile or camera
    backups.

Today there is exactly one user and nothing is published.

## 3. System Architecture (Polyglot Design)

Three layers, balancing heavy data processing against a usable interface.

### 3.1. The Frontend (User Experience)

*   **Technology:** Modern web framework (e.g. React, Vue, or Svelte).
*   **Function:** A dashboard for path configuration, catalog browsing with
    file-level selection, report viewing, and real-time progress over WebSockets.
    Talks only to the API layer, never to the engine or the database. See
    `webui-spec.md`.

### 3.2. The Web & API Layer (FastAPI)

*   **Role:** Command centre and communication bridge.
*   **Function:** Handles HTTP and WebSocket requests, spawns the engine as a
    child process (passing `--file-ids` or `--source-subdir` for selection-scoped
    operations), reads the catalog to report progress, and relays updates to the
    frontend. The only layer that talks to both the engine and the database.
*   **Communication:** WebSockets for live updates; `SIGTERM` to the engine
    subprocess for graceful cancellation.
*   **Trust boundary:** because engine flags are assembled from HTTP request
    bodies rather than typed by someone with shell access, argument construction
    is a security boundary — see `webui-spec.md` §5.6.

### 3.3. The Processing Engine (Python)

*   **Role:** The workhorse. Runs as a standalone CLI process; the API layer
    invokes it as a child process rather than replacing it.
*   **Function:** Filesystem crawling or targeted ID lookup, EXIF and
    full-metadata extraction, SHA-1 and pHash generation, and physical file
    manipulation under the Copy-Verify-Delete protocol.
*   **Interface:** The CLI flags are an *internal* calling convention between the
    API layer and the engine — deliberately documented and usable for debugging
    and development, but not an end-user surface. See `engine-spec.md`.

## 4. Component Status

### The engine — implemented, with known gaps

Delivered and validated against a real library. In place today:

*   Organization into `YYYY/MM/DD` from EXIF `DateTimeOriginal`, with undatable
    photos filed under `Undated/<year>/` rather than into the date tree.
*   SHA-1 and pHash generation and storage for every supported file.
*   Full metadata capture — camera, ISO, aperture, shutter speed, and whatever
    else the source format exposes.
*   Exact deduplication by SHA-1, including safe removal of duplicate sources.
*   Selection-scoped operations via `--file-ids` and `--source-subdir`.
*   Graceful cancellation, with every selected photo receiving a recorded
    outcome.
*   Crash-safe resume, including run-history reconciliation after a hard kill.
*   Standard images, HEIC, and RAW formats.
*   One 320px grid thumbnail per content identity, written during the scan and
    shared by byte-identical duplicates; see `webui-spec.md` §4.2.1.
*   A settings store in the catalog database, initializable without a scan, with
    revision-checked writes and a configuration snapshot per run.
*   Request IDs binding one submission to one run, and the run lifecycle
    Preparing / Running / Cancelling / Completed / Cancelled / Failed / Interrupted.
*   Verified, Zstandard-compressed catalog backups after every job that records
    changes and on demand, with retention and a startup warning for changes no
    backup holds.
*   Discovery accounting per full Index: files found, eligible and excluded by type.
*   Removal of thumbnails whose content no catalogued photo holds.

Only a usable `DateTimeOriginal` places a photo in the date tree. Anything else
files under `Undated/<year>/`, the year taken from the source's modification time
as captured at its original Index; `CreateDate` and `DateTime` are kept as review
evidence but never place a file. See `engine-spec.md` §4.2.

**Three capabilities the web UI depends on do not exist yet**, each specified
with what it needs:

| Gap | Where | Blocks |
| :--- | :--- | :--- |
| Precomputed perceptual pairs | `engine-spec.md` §9.3 | Similar-photo review and its slider |
| Delete under `--dest`, with an extended record | `engine-spec.md` §9.5 | Discarding redundant copies; needs `width`/`height` too |
| Writing embedded EXIF (sidecars remain a future option) | `engine-spec.md` §9.6 | Metadata corrections a gallery can actually see |

Further gaps between the documented web workflows and what the engine can answer
(`engine-spec.md` §9.8):

| Gap | Blocks |
| :--- | :--- |
| Thumbnail cleanup after an interrupted edit (waits on metadata editing) | Cache tidiness after an interrupted edit; nothing user-facing |
| Refiling after a date change | Any metadata correction; it is what makes the destination contract enforceable |
| Field-level before/after | Full lineage and informed manual corrections; no undo operations |
| A batch identity | Bulk apply reading as one action |
| Pre-action catalog backup for EXIF edits and deletion | Those actions; rename already takes one |
| Serving a file for download | Log export and backup retrieval — API work, not engine |

**The destination contract** — every file under `--dest` sits in the folder its
own metadata implies — is recorded in `engine-spec.md` §9.7. It is the
invariant every editing feature rests on, and the reason the workflow order is
Index → Copy or Move → cleanup rather than a matter of preference.

The durability claims ledger in [TODO.md](../TODO.md) is tracked rather than
scheduled.

### The web interface — core loop built

Specified in `webui-spec.md`. It runs as two containers (`docker/compose.yml`):
`web`, nginx serving the screens on port 8080 and passing `/api` through, and `app`,
the API with the engine it starts. **Why the API and engine share a container:** the
API runs the engine as a child process and both use the catalog's SQLite files and
the engine's lock file. Separating them would need the Docker socket or a job-relay
service. Built and tested:

*   **API** (`webui/`): the first-run catalog check and creation, settings, the gallery
    listing and search, photo details, thumbnails and detail previews, starting and
    cancelling jobs, and live job state over a WebSocket, with outcomes derived as
    `webui-spec.md` §5.5 requires (`tests/webui_api_test.py`).
*   **Screens** (`webui/frontend`, React + TypeScript):
    *   the first-run screens;
    *   settings as a window over the page;
    *   the gallery, with its views, sorts and search;
    *   paging for a large library: numbered pages, go-to, page size, and Jump to a month;
    *   selection across pages (shift-click, select-page);
    *   Scan, and Copy and Move of everything or of a selection, each confirmed;
    *   the job drawer, with live counts, elapsed time and Cancel;
    *   the split Inspector, with a movable divider and the 1024px preview. It shows
        the file's own details, including its created and modified dates, apart from
        the photo's EXIF information.

    `tests/webui_browser_test.sh` drives them in a real browser.

Specified but not yet on screen:
*   Logs, the Error Center, backups, and the Dashboard's duplicate-space figures.
*   Folder selection (`--source-subdir`).
*   The Move/Copy preview grouped by destination folder, and the downloadable plan.
*   A photo's full history.
*   The Rename, Similar and Undated tabs, and metadata editing.

### The catalog

One engine-owned SQLite database holds the catalog, settings and operation history,
at schema version 10; older catalogs are refused, never migrated. It stores immutable
source Index evidence and per-run settings, and records destination lineage: a Copy
creates a new identity tied to its source's origin, a completed Move keeps its
identity, and reuse of an existing destination keeps both identities and links the
source removal. Recovery records durable intent before every mutation and concludes
from observed evidence, opening an attention issue when an outcome cannot be
established. Complete lineage for every catalogued file in every settled status is
enforced by test (`TODO.md` claim 11). Content-version history is not yet built. See
`engine-spec.md` §6.5 and §10.
