# Similarity validation checkpoint

The expected library may exceed 200,000 pictures. Use at least 250,000 synthetic
photo records for scale validation, then verify with a representative real catalog.
The current implementation is a validation baseline, not yet a responsive browsing
implementation at that scale.

## What is implemented

- Incremental, resumable visual-hash comparisons in SQLite during Index.
- Visual match review, threshold filtering, and reference comparisons. Exact-copy
  information remains in photo details, history and Stats.
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

One development-host run with 250,000 photo records, seeded clusters of five
hashes (0–4 bit flips from each seed), and seven query samples per threshold.
This uses a temporary local Docker catalog. It excludes file discovery, source
I/O, image decoding and thumbnail generation from comparison timings. It does
not establish real-library or network-storage performance.

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
the existing no-migration policy. No real photo library was modified or measured.

## Next validation

- Run the documented tests on this branch and inspect the Similar page.
- Check match quality against varied real photographs, especially crops, RAW/JPEG
  pairs, rotations, edits, and images with little detail.
- Profile queue and reference queries at 250,000 records; measure again after each
  optimization and retain the same fixtures for comparison.
- Keep judgments separate from any future file actions. They do not authorize
  deletion or metadata edits.
