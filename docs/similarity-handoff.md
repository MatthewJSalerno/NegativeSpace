# Similarity implementation handoff

This is the consolidated handoff for the work developed on
`feat/similarity-validation`. The maintainer completed the manual functional
checklist and authorized documentation cleanup, merge into `main`, and push.
Historical checkpoints are retained in [the validation record](similarity-validation.md).
The design contract is [ui-design.md](ui-design.md); reproducible checks are in
[tests/README.md](../tests/README.md).

## Current behavior

- Workflow: Index → Copy/Move → review destination photos. pHashes come from
  originals; thumbnails are for display. SQLite owns hashes, relationships and
  six-threshold count caching; no additional DuckDB mapping is used.
- Has similar photos defaults to **90%**, **Most matches first**, and grouping on.
  The floor remains 75%. Browser preferences remember explicit threshold, per-view
  sort and grouping choices. Explicit URL thresholds/sorts take precedence without
  replacing saved preferences. Percentages are visual similarity, not confidence;
  below 90% carries stronger review guidance.
- Identical closed neighborhoods (reference plus direct matches) appear once in
  the grouped gallery. Exact sorted hash-bucket membership establishes equality;
  equal counts and transitive relationships do not. The lowest canonical ID that
  satisfies filters represents the set, without implying a keeper or best image.
  Collapse precedes sorting/paging. Gallery totals count sets; sidebar and view
  counts remain photos so hidden members can still be found through filters.
- Partial overlaps remain separate. A–B and B–C do not establish A–C. Explore
  related sets offers explicit direct-reference choices and can combine up to six
  related sets, preserving membership and labelling indirect relationships. These
  expansions are temporary; closing/reloading or changing percentage resets them.
- The comparison workspace supports reference promotion, independent temporary
  rotation/zoom/position, optional linked zoom, file/image and EXIF differences,
  sticky field headings, and saved same/related/unrelated pair judgments. Preview
  dimensions follow viewing rotation; recorded dimensions and scores do not.
- Comparison bookmarks restore the current pair, threshold, review filter/tab,
  divider and viewing transforms without replaying writes. Copy review link uses
  current component state, with manual-copy fallback when clipboard access fails.
- Previous/next set follows grouped-gallery order and its entry reference, including
  after reference promotion. Boundaries/loading/saves disable navigation; failed
  position requests offer retry. Expanded unions have no gallery-set navigation.
- Show this set in gallery opens a temporary, server-paged view of the reference
  and direct members. It bypasses saved gallery filters and preserves explicit
  selection. Back to results restores gallery context; reload exits this scope.
  Browsing is not capped by the 1,000-photo selection limit, which still applies to
  selection. A usable reference remains visible even with no qualifying candidates.
- Suspicious dates flags recorded years before 1800 or more than one year beyond
  the current UTC year, including labelled file-date fallbacks. Dates are unchanged.

## Recovery and file handling

Review matching status replaces the blanket resolution promise. Generate missing
hashes skips recorded failures. Known failures retain per-file explanations and an
explicit recheck after the stated external correction; unsupported formats offer
no futile retry. Resume comparisons handles stored hashes independently. Recovery
verifies destination SHA-1 before/after decoding and writes detailed per-photo
failure logs without changing delivery status or photo bytes. Old jobs are not
backfilled. Missing EXIF or decoder support alone does not prove file corruption.

No EXIF editing, saved orientation writes, deletion, quarantine or persistent group
membership is implemented by this work. Review-later was since settled as decision
notes, not general tagging (`webui-spec.md` §7.9); Rejects replaces deletion
(`engine-spec.md` §9.5). Catalog schema is 16. The maintainer chose a fresh sample catalog;
additional migration/history-preservation work is outside this handoff.

## Implementation map

| Area | Entry points |
| --- | --- |
| Grouped membership | `webui/equivalent_sets.py`, `webui/catalog.py`; optional `group_sets` browse/position parameter |
| Set exploration | `webui/reference_sets.py`, `ReferenceSets.tsx`; GET `/api/v1/similar/{id}/sets` |
| Member gallery | `webui/catalog.py`, `App.tsx`; `set_reference` on photo list, IDs and position |
| Review actions | `ReviewActions.tsx`, `MatchReviewDialog.tsx`, `Inspector.tsx` |
| Recovery | `ns_similarity_recovery.py`, `ns-engine.py`, `SimilarityRecovery.tsx` |

The review-actions follow-up added only UI and read-only catalog queries; no new
engine commands or schema changes were needed for those actions. Detailed contracts
are in [api-spec.md](api-spec.md) and [webui-spec.md](webui-spec.md).

## Validation and sign-off

Recorded automated validation includes 76 general API tests, seven reference-set
tests, seven recovery guard tests, reference-set/actions, full comparison and
recovery browser workflows, TypeScript/image builds, 41 API route contracts, and
specification/whitespace checks. See the dated validation record for which checks
ran with each change. Generated fixtures exercise dense equal-hash buckets, paging,
request failures, selection preservation, clipboard fallback and narrow layouts.

The maintainer manually passed defaults/preferences, identical and overlapping
sets, filtering/counts, comparison, saved judgments/restoration, selection, all
three review actions, recovery/logging explanations and 200% desktop zoom/reflow.
There are no remaining checks in the agreed manual functional checklist.

The sparse prepared 250,000-photo fixture returned the grouped gallery in 1.738
seconds. This is not evidence of dense real-library, end-to-end comparison or
long-session capacity. The sample instance is not representative of that workload.

## Remaining work and operating boundaries

Track these separately in [TODO.md](../TODO.md): representative 200,000+ photo
capacity; rotation-aware retrieval; broader overlap relationships; import-completion
issue summary/external-review filter; warning-action audit; expanded date policies;
review-later/tagging and selected-gallery discoverability discussions. Show only
selected already exists; do not duplicate it without discussing the desired behavior.
EXIF editing, deletion and saved orientation remain separate workstreams.

The sample deployment preserves its catalog and mounts, with source read-only.
Use the existing ignored environment file with `docker/compose.sample.yml`, and
check for active jobs before updates. Do not reset live catalogs, run transfers to
validate UI behavior, or change the separate private instance. Keep personal paths,
filenames, machine details and raw library logs out of tracked documentation.
