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
