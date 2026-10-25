# Project Design Specification: NegativeSpace

This is the entry point. It states what the project is for, where its boundaries
are, and what exists today. The detail lives in two component specifications:

*   **[engine-spec.md](./engine-spec.md)** — the engine (`engine/`): reading source
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

Three consequences follow, and all shape decisions in each component spec:

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
*   **Every signal that could date a photo is worth recording.** Undated photos are
    the hardest part of organizing, and clues turn up while building unrelated
    features. When one does, it is added to the evidence design (`webui-spec.md`
    §3.1) as a candidate, in that design's shape, and is trusted only once the
    back-test measures it in each library. Nothing is tuned to one sample. Clues
    that need no metadata come first, since an undated photo often has none.

## 2. Target Audience

**Photo-format scope:** this is a photo organizer, not a general-purpose image
manager. Do not expand format support solely to edit metadata in arbitrary image
formats. Where a selected photo cannot store requested embedded metadata, report
that limitation and leave it unchanged; no silent fallback to another storage method
or to a catalog-only edit. Where edits go, in the file or an XMP sidecar, is a setting
(`engine-spec.md` §9.6). Existing indexing support is not a promise of metadata-write support.
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
    photos filed under `Undated/<year>/` rather than into the date tree, both inside
    `dest/library/`, the folder gallery applications import.
*   SHA-1 and pHash generation and storage for every supported file.
*   Full metadata capture — camera, ISO, aperture, shutter speed, and whatever
    else the source format exposes.
*   Exact deduplication by SHA-1, including safe removal of duplicate sources.
    Verified embedded edits can consolidate byte-identical results into an explicitly
    confirmed existing Library photo, preserving histories/XMP and refusing Rejects
    or primary-metadata conflicts. Source originals remain until a separately
    confirmed Move; image-only matching is not a deletion rule.
*   Rejects: turned-down photos move from `dest/library/` to `dest/rejects/` and can be
    returned; nothing is deleted, and identical copies stay out of the library
    (`engine-spec.md` §9.5).
*   Selection-scoped operations via `--file-ids` and `--source-subdir`.
*   Graceful cancellation, with every selected photo receiving a recorded
    outcome.
*   Crash-safe resume, including run-history reconciliation after a hard kill.
*   Standard images, HEIC, and RAW formats.
*   Undecodable source photos stay Failed in Not organized, with recorded decoder
    reasons; Copy/Move leave them at source and an Index after external repair
    reassesses them. Missing EXIF or cache/hash-only failures do not block readable images.
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
*   Full Index reconciles externally missing Copied originals against verified Library
    copies; uncertain copies use the shared file-issue recovery workflow.

Only a usable `DateTimeOriginal` places a photo in the date tree. Anything else
files under `Undated/<year>/`, the year taken from the source's modification time
as captured at its original Index; `CreateDate` and `DateTime` are kept as review
evidence but never place a file. See `engine-spec.md` §4.2.

Verified metadata writing is built for XMP sidecars and qualified JPEG embedded
metadata (`engine-spec.md` §9.6). The first web editor exposes Date taken only;
broader import decisions and recovery controls remain tracked in TODO.

The agreed XMP import/source-precedence contract and the metadata-source UI are
tracked in [xmp-metadata.md](xmp-metadata.md). Pure resolution, bounded sidecar reading
and ownership-planning helpers plus immutable compressed version/arrival storage are
built. Supported field-value validation and independent ExifTool compatibility tests
cover the reader; catalog backups verify and retain originals. Index now records qualified
EXIF/embedded-XMP and sidecar evidence with proposed priority. Schema 25 adds saved
explicit ownership/primary choices, stale-safe confirmation and frozen XMP preferences.
Resolved single-/multiple-sidecar first imports now use the selected source for filing through normal
Copy/Move, with verification before activation and source cleanup. Recorded pairs follow
Rename/Reject/Return. Reindex preserves established filing and names; unresolved ownership/primary choices remain held. Alternatives stay in exact
catalog storage and shared-source cleanup requires verified preservation. Incoming duplicate XMP can be preserved
without replacing current primary/location; deliberate Library XMP and embedded-source
activation are built. Photo-only filing now applies captured embedded-XMP/EXIF priority
after verified delivery without rewriting tags or changing write defaults. Common-field
XMP saves, minimal first-sidecar creation,
base-version composition with explicit field overrides, individual field copying,
verified history/recovery and date refiling are built behind a
bounded JSON engine CLI. Verified JPEG working copies support embedded XMP and
representable EXIF common fields, with journaled publication/recovery, content/cache
updates and date refiling. Supported source/pre-edit metadata can be reapplied as a new
verified operation with historical provenance and explicit XMP absence handling; this
does not restore exact photo bytes or implement whole-job undo.
Confirmed incoming XMP/Return choices use verified metadata
jobs; late sidecars beside an already Copied original use the same decision path. Other
embedded writer formats are explicitly deferred for this release; JPEG EXIF mapped-field
removal is qualified. Confirmed incomplete photo/XMP transfer retry and metadata
setup/Settings preferences are built and have passed maintainer validation; per-file
first-import ownership/version choices are built in Not organized → Needs attention;
organized-primary changes are available through a previewed Library action;
incoming-choice screens remain planned. Copy preserves source originals;
Move can remove originals whose retained photo was embedded-edited only with one explicit
confirmation for that job and verified image history, hashes, sidecars and a pre-action
backup. No exact-original-photo reconstruction is promised. Without that consent, those
sources stay while the remaining Move work proceeds; see the metadata contract.

Metadata field-level before/after history, a batch job identity and verified pre-action
catalog backups are built for the qualified engine editing paths. The Date taken editor
is built and validated; broader field-editing controls remain unfinished. The fixed engine closeout is tracked in
[TODO.md — Dates and metadata](../TODO.md#dates-and-metadata).

Further gaps between the documented web workflows and what the engine can answer
(`engine-spec.md` §9.8):

| Gap | Blocks |
| :--- | :--- |
| Thumbnail cleanup after an interrupted edit (waits on metadata editing) | Cache tidiness after an interrupted edit; nothing user-facing |
| Refiling for additional embedded formats | XMP and qualified JPEG date refiling are built; other formats remain unfinished |
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

*   **API** (`webui/`, `docs/api-spec.md`): the first-run catalog check and creation,
    settings, the gallery listing, search, and date, type and folder filters, the source's folders, selection by id and Select
    all, photo details with every recorded tag, a photo's lineage, thumbnails and
    detail previews, starting and cancelling jobs, live job state over a WebSocket
    with outcomes derived as `webui-spec.md` §5.5 requires, the log, library stats, catalog backups,
    what the interface remembers (a dismissed banner), and which build is running
    (`tests/webui_api_test.py`).
*   **Screens** (`webui/frontend`, React + TypeScript):
    *   the first-run screens, landing in Not organized to scan the source;
    *   settings as a window over the page, with catalog backups (list, Back up now,
        download);
    *   the page frame: a top bar with the filename search and the **Jobs** menu on the
        Library page (Index; Copy and Move for the one folder shown or all), and a sidebar
        on every page with the places and their counts, warning shortcuts, Logs, Stats
        and the build; the selection bar (Copy, Move, Reject or Return to library for the
        ticked photos, only what applies) takes the top bar while photos are ticked;
    *   the gallery, with its places, sorts and search, a **Filters** panel with
        **Types** (folded by default) and a **Dates** tree to narrow file types, years
        and months or jump to a date. **Source folders** and counted **Needs attention**
        are child links under Not organized; source-folder restrictions clear on leaving
        that view. The gallery has continuous scrolling whose page number follows; the
        **Rejects** view with what Rejects holds and how to empty it, its tile on Stats,
        and a reminder on every page once it passes a size or age limit set in Settings;
    *   selection across views (shift-click, the Select menu, Show only selected), one
        place per selection (library photos or photos in Rejects, never both), and Copy,
        Move, Reject and Return of a selection reviewed on screen before they run;
    *   the job drawer, with live counts, elapsed time and Cancel; after a job, the gallery
        stays where it was and the notification names the job ("Job #8 · Copy finished",
        never "failed" for a job that ran to its end) with **Show these photos**: the
        job's photos, wherever they are now, which search and the filters narrow;
    *   the split Inspector, with a movable divider, the 1024px preview, the file's own
        details apart from Metadata sources, Additional file information, the
        photo's recent history, its lineage tree in a window of its own, and **Reject…**
        or **Return to library…**; the same two panes serve the enlarged photo view;
    *   gallery cards that tell same-named photos apart by the shortest distinguishing
        part of their original folder;

    *   the **Stats** page: the library in figures (formats, cameras, resolution, dates,
        duplicate space with its coverage, activity, catalog health), each leading to
        the photos or log entries behind it.
    *   gallery **Has similar photos** and Inspector matching: visual review of
        destination photos after Copy or Move, separate Photo information/Metadata/Similar photos Inspector tabs, cumulative
        75/80/85/90/95/100% counts and a responsive, paged match grid. Index precomputes comparisons and resumes interrupted work.
        The expanded side-by-side workspace provides independent temporary rotation,
        linked zoom/position, candidate promotion to reference, file/image and metadata
        differences with scrolling column headings, and Reject or Keep this one, reject the rest.
        Preview dimensions follow viewing rotation; recorded dimensions stay unchanged.
        The validation panel shows coverage and timings. The similarity gallery can sort
        by direct match count at a chosen percentage, with card counts and consistent
        filters, selection and photo navigation. Reference sets show a reference photo's
        direct matches, with an explanation of how sets overlap. Group expansion never
        selects files for actions. Matches involving a mostly black or flat photo are
        marked, never hidden, and Stats counts those photos. Missing-hash recovery reads verified destination
        originals and logs per-file failures; comparison state restores after reload.
        Suspicious-date review flags recorded years without modifying them. The design
        is in [ui-design.md](ui-design.md) and `webui-spec.md` §7.

    `tests/browser/webui_browser_test.sh` drives them in a real browser.

*   **The log and the Error Center:** grouped by job, each job loading as it scrolls;
    filters by job, status, photo, text and date, named in one line with Clear all;
    failure hints with their fixes as buttons, and failure reasons on hover; a Move that
    could only copy shown as Copied only, never as failed; Retry; **Show these photos in
    the library** for each job that acted on photos; and CSV/JSON export.

Built review workflow: Library, Not organized and Rejects are location views; Needs review
is an overlapping inbox of organized Library photos. Refinements above the gallery combine without pins. Needs review narrows Library or
Similar photos by one reason; size browsing in Filters is independent of reminders.
Sidebar place links clear optional restrictions; Back restores prior state. Small-image
reminders are opt-in and never block transfers. Mark reviewed acknowledges only the
size concern. Bookmarks carry preset reasons and optional notes, sort by reason and
open existing review tools. Removal and Keep it decisions retain review history without
clearing unrelated concerns. Shared catalog-only answers also apply to a selection
within one reason, with a count confirmation and per-photo stale results. Automatic
date evidence remains separate planned work. The shared workspace preserves selection and normal Reject
confirmation. See `ui-design.md` for the navigation and Bookmark contract.

The read-only metadata source viewer is built: separate XMP Sidecar, Embedded XMP and
EXIF tabs, an applied Primary badge, retained versions, field comparison/filtering and
recorded-tag disclosure. Catalog reads do not activate sources or modify files.
Date taken editing/copying with a filing preview is built and validated, as are saved
rotations (inline on the large preview, or **Rotate…** for a selection) and **Use as
primary…** on a Library photo's other metadata sources. XMP ownership and competing
versions for first imports are resolved in Not organized → Needs attention, and
incomplete photo/XMP imports have **Retry**. A later Move
now offers one job-scoped Include/Leave confirmation for edited originals, with a bound
selection and engine recheck; maintainer acceptance of this confirmation passed
on 2026-10-14 (tests M1–M3).

Index summaries link to their exact source scopes and share a recorded file-type
breakdown with Logs. Photo information offers Rename and recorded alternative names;
the single-photo unsaved-rotation exit has a compact save/discard decision.
The shared job-status area stays busy through the final catalog backup. At idle,
unbacked changes and failed backups offer Back up now or Retry backup; no job queue.

Specified but not yet on screen:
*   A downloadable Copy/Move plan is deferred for discussion only after every other
    requirement is built (`webui-spec.md` §2); the grouped folder preview is implemented.
*   Check my library and Repair (`engine-spec.md` §9.2).
*   Undated-photo evidence with a per-library back-test (`webui-spec.md` §3.1). Date taken editing/copying
    with a filing preview is built and validated, as are saved rotations. Other fields
    remain read-only; broader engine capabilities do not imply a general-purpose web editor.
*   Additional Needs review reasons (`webui-spec.md` §7.9), including the similar-to-a-reject check
    (`webui-spec.md` §7.8);
    the export-sidecar notice at Index.
*   Videos and other non-photo formats are deliberately deferred until photo organizing
    is complete.

### The catalog

One engine-owned SQLite database holds the catalog, settings and operation history,
at schema version 32; an older catalog is refused, not upgraded (`engine-spec.md` §6.5).
It stores immutable
source Index evidence and per-run settings, and records destination lineage: a Copy
creates a new identity tied to its source's origin, a completed Move keeps its
identity, and reuse of an existing destination keeps both identities and links the
source removal. Recovery records durable intent before every mutation and concludes
from observed evidence, opening an attention issue when an outcome cannot be
established. Complete lineage for every catalogued file in every settled status is
enforced by test (`TODO.md` claim 11). Qualified JPEG edits record retained content-version
changes and metadata history; this does not promise restoration of exact earlier photo
bytes without a file backup. See
`engine-spec.md` §6.5 and §10.

Library-only review is enforced by the decision API as well as the Inspector. Source
failures remain import/log concerns with external correction; Rejects offers Return.
Index summary and Stats distinguish failed files from photo facts. Similarity explicitly
compares active organized Library photos by default, with rejected matches separate. Job headings share Job #ID · Action status.

Cross-location similarity is built: Library matches remain primary, with separately paged
matches in Rejects; a rejected photo can compare against Library photos. Location labels
and explicit Reject/Return actions follow current photo state. Source files and emptied
rejects remain excluded. Bookmark and Mark reviewed remain Library-only. Automatic
similar-to-reject inbox reminders and historical evidence for emptied rejects are pending.

Instance access configuration is separate from photo-processing settings: setup and
Settings › Access persist additional allowed hostnames/IPs in application data outside
the catalog. Catalog rebuild/restore never resets this policy. Local and deployment
addresses provide initial access/recovery; this does not add sign-in or configure DNS.
See `webui-spec.md` §11 for revision checks, current-address confirmation and live enforcement.


Uncertain-operation verification is built: the Inspector and Logs expose open issues
and recorded evidence in every location; active Library issues also enter Needs review.
Check it now performs a scoped read-only verification and atomic catalog repair without
moving or deleting photos. Broader destination inventory UI remains planned.
