# Large-library performance validation

Workstream: `perf/large-library-validation`. The merged functional baseline is
`b6cc1b3`. The manual similarity checklist is complete; representative 200,000+
photo capacity remains unverified. This document defines the comparison plan;
it does not report new benchmark results or authorize a library transfer.

## Questions to answer

Measure three layers separately before optimizing:

1. Original-file processing: directory traversal, NFS reads, SHA-1, metadata,
   original-image decoding/pHash, and thumbnail generation where performed.
2. Similarity maintenance: initial comparisons at the existing 75% floor,
   unchanged reruns, incremental additions, and count-cache refresh/publication.
3. Browsing: grouped/ungrouped gallery, sorting, Inspector, related-set exploration,
   member gallery, thumbnails and sustained browser use.

A fast SQL query does not establish fast indexing. A fast local synthetic run does
not establish NFS performance. A 200,000-file library can also have very different
costs depending on unique contents, unique visual hashes and match density.

## Isolation and comparable inputs

Use a dedicated instance and separate writable catalog, destination, thumbnail
cache, backup and output directories on the intended storage volume. Bind the real
source read-only. Do not run Move, recovery or a transfer against the existing
sample/private instances. Index is sufficient for measuring input processing, but
destination gallery tests need real recorded destination copies. Plan disk capacity
before a test Copy; never fabricate destination availability for a real catalog.

Keep personal filenames, machine details, paths and raw logs in local untracked
artifacts only. Publish aggregate measurements and generated-fixture results.
Record hardware, filesystem/mount characteristics, container memory/CPU limits,
image digests, commit IDs and decoder dependencies privately so comparisons can
be reproduced. Keep them constant within an A/B comparison.

For read-query comparisons, give both revisions the same consistent SQLite backup,
created with the backup API rather than copying a live database file. Restore a
separate disposable copy per revision/run. For initial indexing/comparisons use
independent fresh catalogs; otherwise B can benefit from work already done by A.
Do not clear caches or delete matching data in a live catalog. Schema differences
require an explicit compatible fixture plan, not an ad hoc migration.

## Dataset ladder

Use fixed, nested samples at approximately 10k, 50k, 100k, 200k and 250k photos,
as available. Retain a private manifest/seed and exactly the same files for A and B.
Sample across folders, dates, formats and file sizes rather than taking the first
N directory entries. Include RAW/high-resolution files and burst/edited sequences
in realistic proportions. Track unsupported/failed files separately from success.

Record these aggregate properties for every dataset:

- File count and total input bytes; format and size distributions.
- Unique byte identities, usable unique visual hashes and failed-hash count.
- Same-hash bucket sizes and median/p95/maximum direct-match counts.
- Stored hash-pair rows, catalog/WAL/count-cache bytes and thumbnail-cache bytes.

Use two deliberately different synthetic stress cases: a large equal-hash bucket
and many distinct hashes that are close enough to match. The former exercises
bucket handling; the latter exercises pair growth and cannot be substituted by the
former. Prepared sparse edges are a query fixture, not a complete matching run.
Bound distinct-hash dense tests before approaching a full-library size: the number
of qualifying distinct-hash pairs can grow quadratically.

## Workload and measurement matrix

| Workload | Repeatable action | Record |
| --- | --- | --- |
| Initial processing | Fresh catalog, Index fixed read-only subset | Total/phase elapsed time, files/s, input bytes/s, failures, CPU, peak process/container RSS, disk/network IO |
| Initial comparisons | Fresh matching state in isolated synthetic catalog; separately observe real Index comparison phase | Comparison elapsed time, unique hashes, stored pairs, pair growth, cache-refresh time, peak RSS |
| Unchanged run | Repeat the same Index after settling | Elapsed time, reads and comparison work avoided, cache work |
| Incremental addition | Add a fixed disjoint 1% batch, then a 10% batch in separate restored baseline copies | Added bytes/identities/hashes, elapsed time, new pairs, cache time, failures |
| Destination preparation | One deliberate Copy to the dedicated destination | Transfer duration/throughput, destination bytes and errors; keep separate from query timing |
| Gallery | Grouped and ungrouped; match-count/date sort; first, middle and last page; search and representative filters | API and visible-page latency, returned/total counts, memory |
| Inspector/review | Low-, medium- and high-match references; candidate paging, reference promotion, previous/next set | API and visible-interaction latency, correctness, browser memory |
| Related/member galleries | One set, overlapping sets, up to six expansions, large member-set paging | Latency, unique member counts, server/browser memory |
| Sustained use | Fixed 30–60 minute sequence of browsing, threshold changes and comparisons | Latency trend, browser/container memory trend, errors and retained state |

Use 90% for normal review traffic. Include a separately labelled 75% browsing
stress case because it exposes the broadest recorded candidate set. Keep matching's
75% calculation floor fixed: this is not another 75/80/85 implementation-floor sweep.
Copy may trigger matching maintenance; report its phase work separately rather
than interpreting all Copy time as storage throughput.

## A/B procedure

1. Establish baseline A at `b6cc1b3` before any optimization. Record absolute behavior
   first: there is currently no measured performance improvement to claim.
2. Choose one concrete change for B, and keep dataset, limits, storage and dependencies
   unchanged. Different storage is its own experiment, not a code-speedup result.
3. Run the small dataset first. Confirm membership/counts, errors and output are
   correct before moving up the size ladder. Investigate unexplained errors or
   sharply growing resource use before increasing size.
4. Collect three independent fresh-catalog runs for expensive processing workloads
   where practical. Report individual results and their range; do not invent a p95
   from three samples.
5. For queries, record the first request after process restart separately, then at
   least 30 measured warm requests per scenario after warm-up. Report p50, p95 and
   maximum. Alternate A/B run order to reduce background-load and cache bias.
6. A restarted process is not a truly cold disk or NFS cache. Label it accurately.
   Do not drop host-wide caches on the working machine. Truly cold-storage trials
   need an isolated environment and explicit cache control.
7. Test idle browsing separately from browsing during a controlled job on the
   dedicated instance. Measure server request time and browser-visible completion
   separately so thumbnail reads and rendering are not hidden by a fast API result.
8. Compare both absolute times and B/A ratios, including failures, pair counts,
   disk growth and memory. A quicker run that omitted photos or matches fails.

Before running, choose and record memory, disk, pair-growth and elapsed-time stop
limits appropriate to the host. Container memory limits alone are not graceful
cancellation. A harness should monitor limits, request normal cancellation and
preserve aggregate progress/results. Such a harness is not implemented by this plan.
Never automatically retry a run killed by a limit.

## Provisional acceptance targets

Agree on these targets before calling a library size supported; they are proposed
planning targets, not established product guarantees:

- Normal warm gallery/Inspector API p95 at or below 2 seconds; grouped/related/member
  queries at or below 5 seconds on the agreed host and dataset.
- No dropped members, incorrect group collapse, stale selection or saved-judgment
  loss, even in the densest test sets.
- No sustained upward memory trend across repeated browser cycles, no swapping/OOM,
  and measured RAM/disk headroom against the chosen limits.
- Initial and incremental processing fit a maintainer-agreed time budget. Derive
  that budget from real input measurements rather than declaring an arbitrary
  photos-per-second requirement across RAW/JPEG and NFS/local storage.

If correctness passes but latency misses a target, record the supported scope and
bottleneck. Do not substitute the existing sample or sparse fixture for the failed
workload. Discuss DuckDB or another architecture only after profiling demonstrates
which operation dominates and what a proposed change would remove.

## Existing tools and missing automation

Run existing tools with app dependencies and isolated local output; commands and
fixture details are in [tests/README.md](../tests/README.md).

| Tool | Useful evidence | Limitation |
| --- | --- | --- |
| `tools/validate-similarity.py` | Generated known image pairs; synthetic initial/unchanged/incremental comparisons and query timings; JSON report | Synthetic distribution; fixture/decode setup outside comparison timings; process peak RSS includes setup; not an NFS benchmark |
| `tools/benchmark-similarity-counts.py` | 250k prepared-row count-cache, gallery, position and selection queries | Sparse prepared relationships; single timings rather than repeated percentiles |
| `tools/benchmark-reference-sets.py` | 250k prepared-row exploration and full grouped-gallery query | Sparse prepared relationships; no original reads or end-to-end matching capacity claim |
| Browser fixture drivers | Workflow correctness, paging, clipboard and reflow | Small generated catalog, not a sustained load generator |

Next implementation tasks on this branch:

- [ ] Add a repeatable read-only query runner with scenario seeds, warm-up, repeated
  timings and machine-readable aggregate results for identical catalog snapshots.
- [ ] Add sparse/equal-hash/dense-distinct-hash fixtures with explicit size/edge limits.
- [ ] Add monitored phase/resource collection and normal-cancellation stop limits
  for isolated processing runs; separate child-process memory from fixture setup.
- [ ] Add a reproducible long-session browser sequence and capture visible latency.
- [ ] Prepare private real-source manifests and storage/capacity plan; obtain the
  maintainer's chosen processing budget before starting large Index/Copy jobs.
- [ ] Run A/B at increasing sizes and publish sanitized aggregate findings.

Suggested aggregate result columns:

`revision, dataset_label, photos, unique_contents, unique_phashes, workload,
cache_condition, repetition, elapsed_ms, p50_ms, p95_ms, max_ms, peak_rss_bytes,
database_bytes, wal_bytes, count_cache_bytes, pair_rows, failures, outcome`

Leave inapplicable fields empty. Store raw private artifacts separately; use a
fresh output directory for each run so a failed attempt cannot overwrite evidence.
