# Project Design Specification: NegativeSpace

This is the entry point. It states what the project is for, where its boundaries
are, and what exists today. The detail lives in two component specifications:

*   **[engine-spec.md](./engine-spec.md)** — `ns-engine.py`: reading source
    files, hashing, metadata, placement, the Copy-Verify-Delete protocol, and the
    SQLite catalog it owns.
*   **[webui-spec.md](./webui-spec.md)** — the browser-facing half: job
    management, selection, settings, logs, inspection, and the curation
    workflows.

**These are organized by component, not by release phase.** Release phases were
tried and abandoned: a "Phase 3" fuzzy-matching document ended up holding engine
work that had to happen first alongside UI work that belonged with the rest of
the UI, and one of its open questions carried a deadline inside another phase.
A seam between *the thing that touches files* and *the thing a person clicks*
holds; a seam between release numbers did not.

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

Only a usable `DateTimeOriginal` places a photo in the date tree. Anything else
files under `Undated/<year>/`, the year taken from the source's modification time
as captured at its original Index; `CreateDate` and `DateTime` are kept as review
evidence but never place a file. See `engine-spec.md` §4.2.

**Five capabilities the web UI depends on do not exist yet**, each specified
with what it needs:

| Gap | Where | Blocks |
| :--- | :--- | :--- |
| Destination inventory pass | `engine-spec.md` §9.1 | Answering "is my destination intact?" |
| Precomputed perceptual pairs | `engine-spec.md` §9.3 | Similar-photo review and its slider |
| Rename a delivered file | `engine-spec.md` §9.4 | Recovering a better filename from a duplicate group |
| Delete under `--dest`, with an extended record | `engine-spec.md` §9.5 | Discarding redundant copies; needs `width`/`height` too |
| Writing embedded EXIF (sidecars remain a future option) | `engine-spec.md` §9.6 | Metadata corrections a gallery can actually see |

An audit of the documented web workflows against what the engine can actually
answer turned up eight more (`engine-spec.md` §9.8). Three are settled: grid
thumbnail generation, the settings store, and which date field filed a photo. Five
remain, plus the unfinished half of thumbnails:

| Gap | Blocks |
| :--- | :--- |
| Thumbnail remainder — 1024px preview, clear/rebuild, cleanup after an interrupted edit | The Inspector preview and cache management |
| Refiling after a date change | Any metadata correction; it is what makes the destination contract enforceable |
| Field-level before/after | Full lineage and informed manual corrections; no undo operations |
| A batch identity | Bulk apply reading as one action |
| Pre-action catalog backup | Curation actions; post-job and manual backups, retention and availability are built |
| Serving a file for download | Log export and backup retrieval — API work, not engine |

**The destination contract** — every file under `--dest` sits in the folder its
own metadata implies — is recorded in `engine-spec.md` §9.7. It is the
invariant every editing feature rests on, and the reason the workflow order is
Index → Copy or Move → cleanup rather than a matter of preference.

Two further items are tracked rather than scheduled: the durability claims
ledger in [TODO.md](../TODO.md), and the content-addressed history question in
`engine-spec.md` §10, which needs answering *before* the Error Center is built.

### The web interface — in design, not started

Specified in `webui-spec.md`, including the workflows that consume the five gaps
above. No code exists yet.


### Current database and lineage increment

The shared engine-owned catalog now validates schema version 5, stores immutable
source Index evidence and per-run settings, and records successful destination
lineage. New Copy identities retain source origin; new completed Moves retain their
identity; reuse of an existing destination preserves both identities and links the
source removal. See [database-foundation.md](./database-foundation.md).

Recovery records durable intent before every mutation and concludes from observed
evidence, opening an attention issue when an outcome cannot be established. Complete
lineage for every catalogued file in every settled status is enforced by test
(`TODO.md` claim 11). A caller-supplied request ID binds each submission to one run
(`--request-id`), and runs follow the approved lifecycle (Preparing, Running,
Cancelling, then Completed, Cancelled, Failed or Interrupted). Content-version history
remains pending. Older catalogs are preserved
and rejected; fresh development catalogs are required.
