# Similarity branch review handoff

This is the current review entry point for `feat/similarity-validation`. Historical
local handoff sections describing matching as unimplemented or naming older active
branches are superseded. No merge or push is authorized by this work.

## Scope and established decisions

- Workflow: Index → Copy/Move → review destination photos. Sources remain read-only
  for validation. Do not reset a live catalog or run a transfer to test the UI.
- pHashes come from originals; thumbnails are for display. The chosen floor is 75%.
  Scores measure hash similarity, not confidence. Below 90% needs stronger caution.
- SQLite owns hashes, pair relationships and six-threshold count caching. There is
  no additional DuckDB mapping. Catalog schema remains 16 for this batch.
- EXIF editing/copy, saved rotation writes and deletion are separate workstreams.
  Review-later queues await a broader discussion of catalog tagging.
- The sample is not representative of the eventual 200,000+ library. Functional
  tests and prepared-query measurements do not establish full-library capacity.

## Built before this batch

Gallery match-count sorting and thresholds; Inspector match counts and paging;
side-by-side reference/candidate review, temporary rotation/zoom/position, reference
promotion, file/image and EXIF differences, sticky headings and saved pair judgments;
comparison URL restoration; destination missing-hash recovery and comparison resume;
suspicious-date review. The maintainer explicitly verified suspicious dates.
Dates/bytes are preserved. `TODO.md` and `docs/similarity-validation.md` track details.

## Reference sets in this batch

Group similar photos is a remembered gallery display choice. Identical sets now
collapse to one representative tile. A set contains the
reference and direct matches at the chosen percentage. A–B and B–C do not establish
A–C. A's set is A/B; B's is B/A/C. Gallery filters and sorting choose representatives, totals count sets, and
checkbox selection still selects individual references; set membership covers all destination photos.

Explore related sets offers direct-match references and reports additional members
outside the starting set. Show together unions at most six explicitly chosen related
sets, deduplicates byte identities and labels each photo's memberships. Indirect
photos compare through a supporting reference. Members and related references have
independent server pagination. No recursive graph traversal or saved groups/tags.
Selections survive visiting comparison and returning, but not closing/reloading;
changing percentage clears expansions. Errors offer Retry and Reset; stale includes
are rejected. At narrow widths exploration suppresses the covering Inspector modal.

Implementation: `webui/reference_sets.py`, `ReferenceSets.tsx`, gallery/App integration;
`GET /api/v1/similar/{id}/sets` in `docs/api-spec.md`. Review destination eligibility,
canonical content representatives, direct/indirect labels, page/count semantics,
request races and focus/modal transitions. Inspect the design contract in
`docs/ui-design.md` before changing behavior.

## Recovery reporting follow-up

The maintainer reported empty failure details in Similarity recovery logs. Failed
reads previously updated hash states/counters without per-file operation entries.
Failures now log the photo/path, category and actionable explanation; Inspector
shows recorded visual-processing issues. This does not change delivery status or
photo files. Decode failure may mean corrupt/mislabeled data or missing decoder
support; missing EXIF alone is not evidence of damage. Files without usable hashes
remain excluded from matching but visible in the ordinary catalog. Unsupported
formats explain the limitation; retries are explicit and appropriate only after
fixing the underlying cause. Old failure jobs are not backfilled.

A broader import-completion issue summary and catalog-wide external-review view
remain pending. Do not claim this batch implements automatic corruption detection,
quarantine, hide-all-bad-files behavior, external repairs or new persistent tags.

## Validation and remaining review

Validation passed: 76 API tests, three reference-set tests, five recovery safety
tests, reference-set/recovery/shared-gallery browser workflows, both image builds,
41 API route contracts and spec/whitespace checks. The sample deployment is updated
and source read-only was verified. See `docs/similarity-validation.md` for evidence
and the limits of the synthetic 250,000-row query measurement. Focused tests:
`tests/reference_sets_test.py`, `tests/reference_sets_browser_drive.py`,
`tests/similarity_recovery_test.py`, and recovery-log assertions in the API suite.
The browser uses disposable generated data with the explicit fixture mount; it must
run against rebuilt app/web images. Tests and commands are documented in tests/README.md.

Pending: broader graph intersections; dense real-library
performance and long sessions; deferred review/tagging; expanded date policies;
import issue summary; rotation-aware retrieval; separate EXIF/delete workstreams.

## Deployment and review boundaries

Use `docker/compose.sample.yml` with the existing ignored instance environment file
for the sample. Check that it is idle before updating both services; preserve its
catalog, source read-only setting and all mounts. Do not touch the separate private
instance. Never publish personal filenames, source paths, machine details or raw
real-library logs in tracked documents. Consult the final validation entry for what
was actually deployed and checked. No catalog migration, merge or push is implied.

## Grouping defaults and honest recovery follow-up

Has similar photos now defaults to grouped reference sets and Most matches first.
Explicit sort choices are stored separately per view in browser storage; grouping
is also remembered. URL sorts override defaults without replacing preferences.
Expanded set membership remains session-only; equivalent sets now collapse in the grouped gallery.

Review matching status replaces Resolve matching issues. Generate missing hashes
skips known failures in both the engine and UI count. Those failures retain their
reasons and an explicit Recheck file after external fix, except unsupported formats.
Resume comparisons still works independently. Recovery reports add `generatable`
and per-item `action`; the existing single-photo request is the explicit recheck.
No schema migration, EXIF write, deletion, or automatic retry loop was introduced.
The broader import summary/external-review filter remains unfinished.

Follow-up validation passed: 76 API tests without skips, seven recovery safety
tests, reference-set/default-preference and recovery browser workflows, TypeScript,
both image builds, API and specification checks. The sample is updated and healthy
with its source still read-only. See the final validation entry for this batch.

Similarity threshold follow-up: gallery defaults to 90%, remembers explicit changes
per browser, and honors explicit URL thresholds without overwriting preferences.
The 75% floor remains. Identical reference sets now collapse in the grouped gallery; partially
overlapping sets remain distinct.

## Identical-set gallery follow-up

Grouped browsing now uses exact sorted visual-hash bucket neighborhoods, including
self, to collapse identical full destination membership. Equal-hash buckets are
indivisible, so this avoids expanding photo-pair cross products. It compares full
signatures, not a probabilistic digest or match count. Missing hashes and unavailable
copies remain excluded by existing destination evidence. Queries read live state;
no schema migration, group persistence, or new cache is introduced.

The lowest canonical photo ID satisfying filters represents each set. List totals,
paging, IDs and positioning use grouped representatives; sidebar and library
view-button counts remain photos so filters can find other members. Explicit selection is never expanded or erased.
Ungrouping restores individual photos. Exploration still allows explicit direct
reference choices; this change collapses the main gallery, not saved groups.

New code: webui/equivalent_sets.py. APIs add optional group_sets to browsing and
position requests. Tests cover exact versus partial overlap, distinct hashes with
the same neighborhood, threshold splits, filtering, paging, selection and unchanged
catalog state. The generated browser fixture collapses 126 equal-hash photos to one
of five distinct gallery sets. Existing exploration and narrow layout still work.

Validation passed: five reference-set tests, all 76 general API tests, both
reference-set and full similarity-review browser workflows, TypeScript/image builds,
API/specification/whitespace checks, and the sparse 250,000-photo grouped query
measurement (1.738 seconds). The sample is deployed and healthy; source read-only
was verified. No actual library transfers or repair jobs ran.
