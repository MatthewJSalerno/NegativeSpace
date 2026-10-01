# Similarity validation checkpoint

The expected library may exceed 200,000 pictures. Use at least 250,000 synthetic
photo records for scale validation, then verify with a representative real catalog.
The current implementation is a validation baseline, not yet a responsive browsing
implementation at that scale.

## What is implemented

- Incremental, resumable visual-hash comparisons in SQLite during Index, covering
  the 75–100% review range.
- Destination-only visual review in the gallery Inspector after Copy or Move,
  cumulative 75/80/85/90/95/100% counts and paged reference matches. A gallery
  **Has similar photos** filter uses the 75% floor. Exact-copy information remains
  in photo details, history and Stats.
- Side-by-side generated previews with linked zoom and position controls.
- Same/related/unrelated judgments stored against pairs of content identities.
- Coverage, comparison timing, query timing, and judgment-count diagnostics.
- A synthetic fixture generator, interactive quality report, and catalog benchmark:
  `tools/validate-similarity.py`. Commands are in `tests/README.md`.

The engine computes pHashes from original source files, independently of cached
thumbnails. Raster inputs are opened directly; RAW inputs are decoded by rawpy
with `half_size=True`. The perceptual-hash algorithm reduces the decoded image
to a compact visual fingerprint. The review dialog displays generated previews;
its zoom is not original-resolution inspection.

## Recorded synthetic scale result

Historical baseline before destination-only review and the 75% comparison floor: one development-host run with
250,000 source photo records, seeded clusters of five
hashes (0–4 bit flips from each seed), and seven query samples per threshold.
This uses a temporary local Docker catalog. It excludes file discovery, source
I/O, image decoding and thumbnail generation from comparison timings. It does
not establish real-library or network-storage performance. The benchmark now creates
delivered records and checks that every record is eligible; rerun it to measure the
current destination scope. The figures below are the earlier baseline.

| Measurement | Result |
| --- | ---: |
| Initial hash comparisons | 6.694 s |
| Unchanged comparison pass | 0.476 s |
| One new hash comparison pass | 0.502 s |
| Stored distinct-hash pairs | 459,001 |
| Logical catalog size | 312,328,192 bytes |
| Whole-process peak RSS, including fixture generation | 181,148 KiB |

| Threshold | Queue query median | Reference query median |
| --- | ---: | ---: |
| 90% | 5.795 s | 6.204 s |
| 95% | 5.042 s | 6.214 s |
| 100% | 4.153 s | 6.153 s |

**Open performance issue:** browsing queries repeat catalog-wide availability,
representative and count work. These timings are too slow for interactive review
at the target scale. Profile and reduce that repeated work before deciding whether
DuckDB would improve a specific query. Moving the SHA-1/pHash mapping alone would
not remove the work shown here. No DuckDB comparison has been measured.

## Quality and correctness

For 16 deterministic geometric originals and their resized, recompressed,
brightness-adjusted and cropped variants, the 90% threshold returned 48 of 64
known-positive pairs. All 16 crops fell below the threshold. Of 17 intentionally
unrelated pairs, the flat-color pair was a false positive, including at 100%.
These fixtures expose limitations; they are not an accuracy estimate for photos.
Candidate retrieval agreed with exhaustive Hamming-distance comparison.

The checkpoint passed 63 API tests, 43 database tests, the engine phase-progress
regression, the Similar-page browser workflow, the generated-report browser check,
frontend/container builds, and specification checks. The full engine suite passed
before the validation additions; only its affected progress regression was rerun
after the progress fix. Two genuine-RAW fixture tests were unavailable in that
earlier full run.

Schema version 14 includes saved judgments. Older catalogs remain refused under
the existing no-migration policy. That synthetic checkpoint did not modify or
measure a real photo library.

## Destination-only review validation

The destination scope change passed all 64 API tests, the browser workflow from
Index's empty review through Copy to destination comparisons, both container builds,
and specification checks. API cases cover delivered statuses, source-only direct
links, projected destinations, and missing or changed destination copies while the
source remains present. Existing judgments survive loss of destination availability.
A 1,000-record delivered synthetic catalog smoke check verified nonempty benchmark
scope at all thresholds. This is not a replacement for the 250,000-record scale run.

## Maintainer validation — 2026-09-29

Reported against the validation branch after the destination and UI updates:

| Check | Reported result |
| --- | --- |
| Index and Copy | Completed without errors |
| Destination files | Present |
| Similar threshold filtering | Adjusts results as expected |
| Page refresh | Selection remained |

These are manual functional results, not measurements of match accuracy or query
performance. These checks preceded the 75% floor. Destination-query performance at
250,000 records remains unvalidated.

## 75% floor — single-catalog check

The chosen floor is 75% (up to 16 differing hash bits). Association can help a user
investigate dates, events, or other metadata; matches do not prove shared metadata
and never authorize edits or deletion. No 75/80/85 threshold benchmark sweep was run.

A separate SQLite snapshot of the completed validation catalog was prepared for
schema 15. Existing hashes were reused without reading photos. One complete 75%
comparison pass and one queue query produced these measurements:

| Measurement | Result |
| --- | ---: |
| Distinct usable hashes | 20,357 |
| Destination content identities | 26,057 |
| Comparison pass, including pair writes | 0.283 s |
| Stored distinct-hash pairs, old 90% range | 2,142 |
| Stored distinct-hash pairs, 75% range | 53,169 |
| Pair table and indexes, old range | 303,104 bytes |
| Pair table and indexes, 75% range | 7,409,664 bytes |
| Single 75% queue query | 1,286.53 ms |
| Destination representatives with matches at 75% | 25,456 |

This is a single warm-host observation, not a capacity or accuracy claim. Query
cost remains relevant even when hash calculation is fast. The vectorized comparison
uses bounded chunks and linear hash memory, but initial calculation and worst-case
pair storage can grow quadratically with distinct hashes. A 200,000+ photo library
still requires separate scale validation.

The schema-14 preparation tool preserves all non-derived tables in a separate file;
startup never upgrades a catalog automatically. Correctness checks cover distances
through the floor, rejection below it, chunk boundaries, interrupted work, source
catalog preservation and review/history retention. The API suite and focused Similar
browser workflow passed, including setting 75% and retaining it after refresh.

## Next validation

- Run the documented tests on this branch. Index and Copy a sample catalog, then
  inspect the destination photos on the Similar page. An Index-only catalog shows
  the Copy/Move guidance instead of source comparisons.
- Check match quality against varied real photographs, especially crops, RAW/JPEG
  pairs, rotations, edits, and images with little detail.
- Profile queue and reference queries at 250,000 records; measure again after each
  optimization and retain the same fixtures for comparison.
- Keep judgments separate from any future file actions. They do not authorize
  deletion or metadata edits.

## Gallery and Inspector integration — 2026-09-29

Similarity review now starts with an ordinary gallery photo. Its Inspector shows
six cumulative counts from one aggregate request; choosing a count loads at most
12 direct matches at a time in the information pane. The standalone Similar
navigation/page is replaced by **Has similar photos**, with old bookmarks redirected.
Gallery selection, search and date/type/folder behavior remain separate from match
browsing. The reference, threshold and match page survive URL navigation and reload.

One read-only query sample against a local backup of the prepared catalog measured:

| Measurement | Result |
| --- | ---: |
| Destination gallery photos | 26,057 |
| Gallery photos with matches at 75%+ | 25,456 |
| Normal gallery query, including view counts | 0.465 s |
| Has similar photos query, including view counts | 0.788 s |
| All six counts for one reference | 0.493 s |

These are individual server-side samples, excluding thumbnails, network and browser
rendering; no full threshold benchmark or 200,000-photo capacity claim is made.
Membership uses indexed set lookups: joining grouped hash lists twice caused a
catalog-wide scan per pair and was rejected during validation. No new hashing,
comparison backfill, photo transfer or catalog migration is required for this UI.

Validation: 68 API tests passed, including cumulative boundary counts, direct rather
than transitive matching, destination availability, exact-content collapsing and
agreement among gallery/selection/sidebar queries. The dedicated browser workflow
covers generated Index/Copy, Inspector paging, side-by-side saved judgments,
selection preservation, URL restoration, failures/retries and narrow dialogs.

The existing full gallery browser scenario and shared UI checks also passed,
including Index/Copy, selection, metadata, lineage, dialogs, keyboard focus,
request retries, theme contrast and narrow reflow. Both image builds and the
specification/API/schema checks passed.

## Tabbed Inspector and sample sharing — 2026-09-29

Photo information and Similar photos now occupy separate Inspector tabs, with a
shared preview and divider. The match tab remembers its threshold across reference
navigation (resetting the match page), uses a responsive thumbnail grid, and scrolls
independently so the reference stays visible. Initial information browsing avoids
match requests. URL state includes the tab and restores hidden matching context.
An expanded workspace for EXIF and cleanup actions remains explicitly unbuilt.

A separate sample-only instance was indexed and copied with its source read-only:
4,745 destination photos, 110 duplicate records, 3,179 destination representatives
with visual matches, and three intentional invalid/unreadable scenario fixtures.
It has its own catalog, destination, cache, backups and network. No real-library
catalog was copied into it. The Compose recipe is `docker/compose.sample.yml`.

The full gallery browser workflow and shared control checks passed with the new
tabs. Dedicated matching checks cover keyboard tab navigation, remembered threshold,
URL restoration, match paging, side-by-side judgments, retries and narrow dialogs.

## Branch status — 2026-09-30

Current scope on `feat/similarity-validation`:

- **Built:** original-file pHashes, resumable comparison through the 75% floor,
  destination-only review after Index → Copy/Move, exact-content collapsing,
  cumulative Inspector counts and paged direct matches. There is no separate
  Similar navigation or identical-byte mode in visual review.
- **Built:** expanded comparison workspace, temporary independent rotation/zoom,
  linked zoom/position, reference emphasis and promotion, file/format/dimension/
  size comparison, EXIF differences, sticky comparison headings, rotation-aware
  displayed dimensions, and saved pair judgments with reviewed/unreviewed filters.
  The two-preview frame grows to fit its controls. Recorded dimensions stay unchanged.
- **Built:** gallery match-count sorting at six chosen percentages, URL restoration,
  selection retention, a visible **Most matches first** shortcut, compact preview
  badges and consistent gallery summary/card styling. A similar-gallery card opens
  the Inspector's matching tab at that gallery percentage. Explicit tab changes
  remain available and survive previous/next and reload.
- **Built:** shared text/link styling and documented design rules in
  `docs/ui-design.md`, linked from `AGENTS.md`; empty zero/zero coverage notices
  suppressed; below-90% review guidance; Stats chart containment; an isolated
  sample-sharing Compose recipe with read-only input and separate writable data.
- **Built:** schema-16 SQLite count cache and explicit schema-14/15 preparation,
  with atomic invalidation/publication and correct live-query fallback. Counts are
  derived state in the existing catalog; a second DuckDB database is not required.

Pending work is tracked in [TODO.md](../TODO.md): actionable missing-hash repair and
comparison resume, EXIF copy/edit, deletion with explicit targets/results/history,
verified saved-orientation writes and a single end-of-review decision, deferred
review queues and workspace restoration, rotated-match retrieval, and representative
large-library validation. Reference, metadata donor, keeper and action target remain
separate roles. No edit/delete/save-rotation controls promise unimplemented actions.
Manual preview rotation never changes retrieval or hash scores.

The sample library is **not representative of the maintainer's full library**.
Neither its results nor synthetic SQL timings establish match quality, dense-pair
storage, NFS performance, initial/incremental hashing/comparison capacity, or browser
behavior for 200,000+ photos. Full-library and long-session validation remain pending.

### Count-cache cost: bounded synthetic query check

One generated catalog contained 250,000 delivered content identities, 50,000 visual
hash buckets of five photos, and 49,999 prepared neighbor relationships. Relationships
were supplied for query testing, not discovered by an exhaustive matching pass.
No photographs or NFS source were read. Reproduce with
`python3 tools/benchmark-similarity-counts.py` using the app dependencies.
Single warm-host measurements:

| Measurement | Result |
| --- | ---: |
| Build all six counts | 1.296 s |
| Count/state table pages, measured with SQLite dbstat | 5,025,792 bytes (4.79 MiB) |
| Gallery sorted by match count, including view counts | 0.121 s |
| Similar gallery sorted newest first | 0.265 s |
| Photo position in match ordering | 0.227 s |
| 1,000 explicitly selected photos, match ordered | 0.028 s |

This count storage excludes the existing catalog/pair tables, temporary aggregation
memory and WAL. Storage grows linearly with representatives and integer widths; a
rebuild also uses a write transaction, temporary working space and WAL writes.
An unchanged job skips rebuilding. Dirty caches use slower live queries until an
uncancelled engine job publishes new counts. These figures are a query/cache check,
not an end-to-end capacity benchmark or a comparison against DuckDB.

### Validation and sample handoff

Database suite: 46 tests passed. API suite: 73 tests ran successfully, with four
intentional skips. The focused history-settle durability regression passed.
Both image builds, the similarity browser workflow, the complete gallery/shared-UI
browser workflow, and specification-reference/whitespace checks passed. Rendered
checks included desktop and narrow layouts, compact match badges, comparison
headings, keyboard/focus behavior, theme contrast and the Stats Dates chart.
These are functional/regression checks, not a full engine-suite or capacity claim.

For this development sample, the maintainer chose a **fresh catalog rebuild**;
no upgraded catalog was installed. The updated sample instance starts with empty
appdata, ready for Create catalog → save settings → Index → Copy. The existing
sample source and destination mounts are retained. Rebuilding requires new settings
and creates new catalog history/judgments; transfer destinations already present are
handled by normal engine verification. No further migration/history work is planned
for this sample. General release migration policy remains a separate TODO item.


## Matching recovery and comparison restoration — 2026-09-30

This branch remains focused on similarity matching. Missing-hash recovery now reads
verified destination originals, including after the source is gone; a separate
comparison-only action resumes stored hashes. The recovery dialog names affected
photos and reasons, offers scoped actions, reports jobs and cancellation, and keeps
its results open after a warning clears. Unsupported decoder formats remain an
explicit limitation; missing, changed or unreadable files need the stated correction
before retry. Catalog schema remains 16 and no migration is required.

The open comparison is bookmarked in the gallery URL: original Inspector context,
promoted reference, candidate, threshold, page, review filter, pane tab, divider share,
linked zoom and the current pair's temporary rotation/zoom/position. Restoring fetches
fresh data; it does not replay judgments or modify files. Closing clears the bookmark.
Other candidate transforms are session-only; deferred review queues remain pending.

EXIF copy/edit, saved orientation writes and file deletion are a separate workstream,
recorded as planning items in TODO.md. They are not prerequisites for these matching
features. Representative 200,000+ library and long-session validation remain pending.

Validation: the API suite ran 76 tests successfully (four intentional skips), and
five focused recovery safety tests passed. Recovery browser checks covered real
repairs against generated destination files, scoped retry, unsupported formats,
comparison resume, busy-job gating, failed status requests and narrow reflow. The
full gallery/shared-UI browser workflow passed. Comparison checks covered restored
rotation/zoom/position, review filters and tabs, and reference promotion across
refresh. Explicit gallery checkbox selection remains session-only and is not part
of the comparison bookmark. Both images built and specification/whitespace checks
passed. Rendered recovery and comparison screens were inspected at desktop and
narrow sizes. These are functional checks, not large-library capacity validation.

The sample instance was updated with its existing schema-16 catalog and mounts
preserved; no Index, Copy or recovery job was started as part of deployment.
An optional grouped gallery remains a pending idea in TODO.md. Suspicious-date
review was subsequently implemented as described below.

## Suspicious-date review — 2026-09-30

Added the Suspicious dates gallery view, Inspector reason/source and comparison
Date review row. The rule flags recorded years before 1800 or more than one year
ahead of the current UTC year; the upper bound is evaluated by SQLite at query
time. It covers the recorded gallery date, including file-time fallbacks, without
changing metadata, file placement or schema. Malformed raw EXIF, conflicting tags,
configurable bounds and dismissals remain future work.

The 76-test API suite and targeted policy/API test passed. Generated browser checks
covered filtering, refresh, Inspector and comparison warnings and narrow layouts;
the shared gallery/UI workflow also passed. Desktop and narrow screenshots were
inspected. Builds and spec-reference/whitespace checks passed. Sample deployment
preserved the existing catalog and mounts. No Index or transfer was started.
Large-library performance remains unmeasured for this additional view count.

## Reference sets and recovery failure details — 2026-09-30

Built optional reference-set cards in the similarity gallery, explicit overlap
exploration and session-only Show together. Each reference remains a tile; identical
sets are not collapsed. Filters/counts/selection retain their per-photo meaning.
An A–B–C chain stays reference-relative: expanding B from A adds C once, marked as
indirect, and comparison uses B. No further connected photos are automatically added.
Members and related references are paged; at most six related references can be
included. Returning from comparison preserves the exploration; closing, reloading
or changing percentage clears expansion choices. Stale requests are rejected with
retry/reset. Incomplete coverage links to recovery. No photo or group writes.

Recovery failures previously incremented counters without file-level operation
entries. New failed attempts now record the photo/path, category and actionable
reason in Logs, with raw IO error detail when available. Inspector reports recorded
visual-processing issues. Decode failure is not proof of a non-image, and missing
EXIF alone is not evidence of damage. Files/delivery status remain intact; missing
hashes already exclude photos from matching. Historical failures are not backfilled.
The broader import issue summary and external-review filter remain in TODO.md.

Validation: 76 API tests, three focused reference-set tests and five recovery safety
tests passed. The reference-set browser workflow passed (chain expansion, indirect
comparison, session reset, threshold changes, dense same-hash paging, expansion cap,
request failure/retry, narrow modal ownership and per-file failure logs). Recovery
and full gallery/shared-UI browser workflows passed. A shared Stats test teardown
race was fixed by waiting for its in-flight intercepted request before closing the
page; no application Stats change was needed. Desktop/narrow screenshots were
inspected. Both images built, 41 API routes matched their documentation, and spec
reference/whitespace checks passed.

A synthetic query check reused 250,000 identities, five-photo equal-hash buckets
and 49,999 prepared neighbor relationships. Opened-set queries with zero, one and
six related references took 2.146, 2.177 and 2.209 seconds respectively on one warm
host run, returning at most 12 photos. Reproduce with
`tools/benchmark-reference-sets.py`. This is sparse prepared-query evidence, not
hash-generation, dense-group, whole-library or browser-session capacity validation.
No real photo files were read by the benchmark. Further query optimization remains
possible; do not describe reference-set queries as constant-time or fully validated
for dense 200,000+ libraries.

The idle sample instance was updated with both images, retaining the schema-16
catalog and mounts. Source read-only was verified. No Index, Copy, Move or repair
was started on the sample as part of deployment. The separate private instance was
untouched. The current review entry point is
[similarity-handoff.md](similarity-handoff.md); the existing local handoff's opening
section now supersedes its historical branch state.

## Grouping defaults and targeted recovery follow-up

- Grouping starts enabled; Has similar photos initially orders Most matches first.
  Browser preferences remember grouping and explicit per-view sort choices. Explicit
  URL order, including Newest first, survives reload without overwriting preferences.
- Review matching status replaces the generic resolution promise. Bulk generation
  skips recorded failures; explicit per-file recheck remains available after the
  stated external correction. Unsupported formats keep their explanation without
  a futile retry. Stored comparisons can still be resumed independently.
- Passed: 76 API tests as the application user (no skips), seven recovery guard
  tests, reference-set/default-preference and recovery browser workflows, TypeScript
  checking, both image builds, 41 API route contracts, and specification checks.
  Desktop and narrow rendered layouts were inspected using generated fixtures.
- The idle sample instance was updated while preserving its catalog and mounts;
  health, the updated recovery report, and read-only source mount were verified.
  No real-library recovery, transfer, EXIF edit, deletion, or catalog migration ran.

The subsequent 90% gallery default and remembered threshold update passed the
extended reference-set browser workflow: fresh default, explicit user change,
reload, reopening without URL state, and URL override without preference changes.
TypeScript/build and specification checks passed; the sample web container was
updated. Identical reference-set collapsing remains discussion, not implementation.

## Identical-set gallery validation

The grouped gallery collapses exact closed neighborhoods at the selected percentage
before pagination. It keeps partial overlaps separate, selects a stable filtered
representative, and preserves explicit photo selections. Sidebar photo counts remain
available so hidden members can still be reached by filters.

Five reference-set API tests passed, including full membership equality across
different visual hashes, equal-hash buckets, threshold splits, filtered references,
paging/position/selection consistency and no catalog writes. All 76 general API
tests passed. The generated browser fixture displays five distinct sets rather
than 130 reference tiles; 126 equal-hash members appear under one gallery tile.
Grouping toggle, exploration, selection retention and narrow layout checks passed.

The existing sparse synthetic 250,000-photo fixture returned 60 representatives
from 50,000 distinct sets in 1.738 seconds for the full grouped-gallery request.
This measures prepared relationships and existing count-cache reads, not dense
real-library capacity, decoding or hash generation. No new persisted cache or
schema migration was added.

The full similarity-review browser workflow also passed after updating its fixture
expectations for grouped versus per-photo navigation and remembered sort URLs, and
waiting for pan state to reach the URL before testing reload. TypeScript, image
builds, 41 API route contracts, specification checks and whitespace checks passed.
The idle sample instance was updated with its catalog and mounts preserved. The
grouped endpoint responded successfully and the source remains read-only.

## Review actions validation

Implemented Copy review link with clipboard-success and manual-copy fallback,
previous/next grouped-gallery set navigation, and temporary paged browsing of a
set's direct members. No matching engine or schema changes were required; backend
work is confined to read-only catalog filtering through set_reference.

Passed: 76 general API tests, seven reference-set tests, reference-set/actions and
full similarity-review browser workflows, TypeScript/image builds, 41 API route
contracts, specification and whitespace checks. Browser checks cover copied-link
restoration with rotation, LAN clipboard fallback, neighboring sets, preservation
of selection, a 126-member gallery across pages, and narrow review reflow. Rendered
desktop/narrow layouts were inspected. The API retains a usable reference even when
no candidates meet the threshold. All test photo operations used disposable fixtures.

The idle sample instance was updated with its catalog/mounts preserved. Health,
the read-only member-gallery endpoint, and read-only source mounting were checked.
No real-library copy, move, repair, EXIF editing or deletion was performed.

## Maintainer manual review — 2026-10-01

The maintainer reports all steps validated for defaults/preferences, identical and
partially overlapping sets, filtering/counts, comparison, saved judgments and
restoration, and selection. Previous/next set and Show this set in gallery also work.
After receiving the detailed instructions, the maintainer confirmed all Copy review
link steps validated.
The maintainer reports recovery/logging passes: logs now explain what failed and
why. Desktop zoom/reflow also passes: the screen scales to 200% and windows adapt.
This completes the agreed manual functional checklist. Automated results above
remain separate evidence. Representative 200,000+ photo capacity, dense matching
and long-session performance remain outstanding; this sign-off does not establish
those limits or authorize a merge.

Future discussion requested: presenting selected photos in the gallery. The existing
Show only selected command already provides a temporary selection gallery; discuss
discoverability and desired behavior with grouped sets before adding/changing UI.
