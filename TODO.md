# TODO

Branch completion/validation details are in
[the consolidated handoff](docs/similarity-handoff.md) and
[validation record](docs/similarity-validation.md#current-status--2026-10-01).
The agreed manual functional checklist is complete; large-library capacity remains
a separately tracked validation item.
The current sample uses a fresh catalog rebuild by maintainer choice; further
migration/history work for that sample is out of scope.

## Completed similarity review and manual sign-off

- [x] Default to 90%, grouped identical sets and Most matches first. Remember
  threshold/grouping and per-view sort choices; explicit URLs override preferences.
- [x] Collapse exact full-membership sets before gallery pagination; retain partial
  overlaps, filtered representatives, set counts and explicit photo selection.
- [x] Copy review link with manual fallback, previous/next grouped-gallery set,
  and temporary paged browsing of a set's direct members.
- [x] Maintainer passed the complete manual checklist: preferences, grouping,
  filtering/counts, comparison, saved judgments/restoration, selection, all three
  review actions, recovery/logging explanations and 200% desktop zoom/reflow.
- [ ] Future discussion: selected-photo gallery discoverability and grouped-set
  behavior. Show only selected already exists; discuss before adding another control.
- [ ] Consider broader relationships between overlapping sets beyond the current
  explicit one-hop exploration. Do not infer transitive matches.

## Expanded destination review workspace

- [x] Expanded comparison workspace with independent temporary rotation, zoom and
  position; optional linked zoom; candidate paging; metadata comparison; saved
  pair judgments and server-filtered reviewed/unreviewed progress.
- [x] Plain Reference photo heading with an accent preview border and explicit
  candidate promotion. File/image properties appear above capture information;
  differences filtering covers all sections, column headings follow scrolling,
  and preview dimensions follow temporary rotation while recorded dimensions stay
  unchanged. See the [UI design contract](docs/ui-design.md#expanded-review-workspace).
- [x] Restore the open comparison after refresh/bookmark navigation: original Inspector
  context, promoted reference, candidate, threshold, candidate page, review filter,
  information/review tab, panel width and current-pair viewing adjustments. Close
  clears the workspace bookmark; missing/stale photos still require a fresh lookup.
- [ ] Deferred: discuss review-later queues alongside broader catalog tagging needs
  before implementing a dedicated marker. Saved pair judgments already survive reopening.
- [ ] Assess finding rotated matches that the current pHash search misses.
  Rotating a returned preview helps human comparison but does not change retrieval
  or scores. Keep this separate from viewing controls and saved orientation edits.
- [x] Gallery **Most matches first** sort and **Matches at or above** selector
  (75/80/85/90/95/100%). Cards show direct-match counts; sorting happens before
  pagination and ties use photo ID. Gallery filters narrow references, while counts
  include the full destination library. Zero-match photos are excluded at the chosen
  threshold; incomplete comparison coverage is shown separately. Opening a gallery
  card opens Similar photos at its gallery threshold. Sort/threshold survive reload and
  browser navigation; selection membership is preserved. No hashes are recalculated.
- [x] Six-threshold SQLite count cache in the catalog, with transactional invalidation,
  live fallback and atomic/cancellable engine refresh. No separate DuckDB database.
- [x] Visible **Most matches first** shortcut, consistent gallery summary/card geometry,
  compact match badges, shared active filter styling and supplemental filter help.
  Similar-gallery clicks open the matching tab; manual tab choices persist for
  previous/next and reload.
- [x] Add an isolated synthetic SQLite query runner with sparse, equal-hash, bounded
  distinct-hash dense and mixed-eligibility fixtures; repeated timings, worker
  deadlines and reusable fingerprinted inputs. A 250k sparse baseline completed
  all eight workloads with 30 warm samples each; Inspector counts + candidates
  (5.71 s p95) and related discovery + expansion (4.58 s p95) were the initial
  profiling targets. See [benchmark commands](tests/README.md#synthetic-catalog-query-benchmark).
- [x] Profile and narrow Inspector/reference-set SQLite queries: resolve requested
  identities directly, filter candidate hashes before ranking/metadata reads, and
  avoid grouping unrelated destination rows. Preserve canonical copies, overlap
  behavior, historical hash casing and exact API results. Same-fixture A/B checks
  passed at 250k (30 warm samples) and 500k sparse/bounded dense (three warm
  samples); measured results are in the performance plan. No DuckDB layer added.
- [ ] Follow the separate [large-library measurement plan](docs/large-library-performance.md)
  on `perf/large-library-validation`: query performance at 250k/500k, dense and
  overlapping sets, memory, invalidated caches and response times. Repeat A/B runs
  before claiming supported capacity. Original-file processing, initial/incremental
  hash comparison build costs and long-session browser work remain separate
  follow-ups; this branch does not benchmark filesystem latency. See [validation guidance](tests/README.md#web-interface-in-a-browser--webui_browser_testsh).
  The 75% floor is the chosen range; capacity validation is not a request to choose
  between 75/80/85% floors. A separate DuckDB hash mapping is not part of the current
  architecture; measure a concrete bottleneck before proposing another database.

## Date review and further gallery ideas

- [x] Suspicious dates: read-only gallery view, Inspector explanation and comparison
  date-review row. Flag recorded gallery-date years before 1800 or more than one
  year beyond the current UTC year, including labelled file-time fallbacks. Preserve
  all dates; legitimate historical dates remain review hints, not confirmed errors.
  Missing dates stay in No capture date. No schema change or reindex is required.
- [ ] Extend date review to malformed/raw EXIF fields, conflicting capture tags,
  configurable bounds and dismissing known-valid dates if users need these. Current
  flags inspect only the recorded gallery date. Date editing remains separate.
- [x] Implement the agreed optional reference-based sets in Has similar photos.
  Each reference retains all direct matches at the chosen percentage. With A–B
  and B–C but no A–C, A's set contains A/B and B's set contains B/A/C. Overlap is
  intentional; do not partition photos into disjoint groups or imply all members
  match each other. See the [agreed design](docs/ui-design.md#reference-based-sets).
  Add inline overlap notices, Review this set and Explore related sets. Users may
  explicitly choose related sets and Show together, deduplicating photos while
  retaining reference/membership context and identifying indirect relationships.
  Expansions are session-only; recompute sets/overlap when the percentage
  changes. No automatic recursive expansion, persisted group membership, tags,
  keeper decisions or photo writes. Pagination, filter/count/selection semantics
  are documented in the design standard. Identical-set collapsing is implemented in the grouped gallery.

## Separate workstream: photo changes

EXIF editing/copy, saved orientation writes and deletion are outside this similarity
matching branch. These planning items do not block hash recovery, comparison
restoration, match quality work or performance validation. No functional edit/delete
controls are promised in the current review UI.

- [ ] Add EXIF copy/edit and deletion with explicit target selection, previews and
  per-file history/results. Reference, metadata donor, keepers and action targets
  are distinct roles. Do not infer them from navigation or gallery checkboxes.
  Follow webui-spec §7.4 and §7.6 and the shared UI design contract.
- [ ] Add saved orientation edits separately from temporary viewing rotation.
  Offer one end-of-review decision for photos with a remaining rotation change,
  not a write or prompt on each Rotate click. Identify the affected reference and
  candidates by photo, preview their final orientations, and allow saving selected
  changes, discarding them, or returning to review. Keep changes attached to photo
  identities when candidates or the reference change; decide how leaving via Back,
  Escape or closing the window reaches the same decision. Build the verified EXIF
  Orientation write path first (webui-spec §7.6); do not show a save promise until it
  works. General EXIF editing belongs in the shared editor, reached from review.
## Actionable warning workflows

- [x] Missing-hash recovery and comparison resume: paged affected destination photos,
  generation for uncomputed hashes and explicit per-file rechecks after external
  fixes, with distinct unsupported-format, decode, read, missing-file and changed-file
  reasons, busy-job gating, progress/cancellation and refreshed outcomes.
  Bulk generation skips known failures. Review matching status makes no blanket
  repair promise. Recovery verifies destination SHA-1 before and after decoding
  and works when the source is gone. It changes only matching data. Changed/missing/unreadable files
  require the stated external correction before retry; unsupported formats remain
  a decoder limitation. Ordinary unchanged-file Index is not the recovery path.
- [ ] Add an import-completion summary and a catalog-wide external-review filter for
  files with failed visual processing. Distinguish corrupt/mislabeled data from missing
  decoder support and IO failures; absent EXIF is not proof of damage. Preserve files
  and delivery status. Existing missing-hash states already exclude them from matching.
  Recovery per-file logs and Inspector issue explanations are implemented; historical
  jobs have no backfilled details. Do not repeatedly retry unchanged bad files.
- [ ] Audit warnings throughout the app for a working action or direct route to the
  affected items. Track missing actions as unfinished features under the shared
  [validation and feedback contract](docs/ui-design.md#validation-and-feedback).

## Durability claims: stated vs enforced

Every durability claim resolves to either **enforced and tested** or **a documented limitation** — never something the prose asserts and the code only usually does. **A claim that cannot be enforced is raised with the maintainer before it is weakened:** weakening a guarantee is his decision, not an editorial fix. Until he decides, mark it **Unresolved** here with what fails and why.

| # | Claim | Stated in | Status |
| :--- | :--- | :--- | :--- |
| 1 | A source is deleted only after its copy's **bytes** are fsynced | `engine-spec.md` §4.2, §7 | **Enforced**, tested (`durability barriers precede source deletion`) |
| 2 | …and after the copy's **own directory entry** is fsynced | `engine-spec.md` §4.2 | **Enforced**, tested |
| 3 | …and after **every ancestor entry from `--dest` down**, retried until it succeeds | `engine-spec.md` §4.2 | **Enforced at the deletion gate**, for all three deletion callers, tested (`a failed ancestor sync is retried not forgotten`, `the already present deletion establishes the ancestor barrier`, `duplicate cleanup establishes the ancestor barrier`) |
| 4 | The chain walk never touches anything **above** `--dest` | this file | **Enforced**, tested (`the durability chain never reaches above the destination`) |
| 5 | The source is unchanged since it was verified | `engine-spec.md` §4.2 | **Enforced**, tested (`a source edited after verification is kept`) |
| 6 | The copy is a different file from the source | `engine-spec.md` §4.2 | **Enforced**, tested (`a source is never deleted as its own copy`) |
| 7 | `mtime` is preserved by a copy | `engine-spec.md` §9.2 | **Enforced**, tested (`a delivered copy keeps its source mtime exactly`) — to the nanosecond, for Copy and Move, with undated and dated photos |
| 8 | The documented repair for a destination file removed outside the engine — re-index with `--force-rehash`, then Copy — actually re-delivers it | `Skipped` reason string, `webui-spec.md` §5.3 | **Enforced**, tested (`the documented recovery redelivers a removed destination file`) |
| 9 | A filesystem that cannot fsync directories **says so at runtime**, rather than leaving the weaker guarantee to be inferred from this document | `engine-spec.md` §4.2 | **Enforced**, tested (`an unsupported directory fsync is reported once per run`). Once per run, naming the first such directory — once per directory would be a line per date folder. |
| 10 | The move/copy loop **commits its intent marker at `synchronous=FULL`**, so `status=Processing` with `dest_path` is fsynced before the source is unlinked | `get_db_connection`, `engine-spec.md` §5 | **Enforced**, tested (`the move loop commits at full synchronous`). Scoped to that one connection — the scan path keeps `NORMAL`; measured 1.42x on the move path (+1.9 ms/photo) against the ~4.4x `NORMAL` buys on the scan path. **The claim stops at the fsync:** whether a real power cut preserves it depends on the storage honouring it, which is untested (see the power-loss item below). **If the marker is lost anyway, the next run still records the truth**, tested (`a move whose catalog commits were lost is recorded as found`): a photo or duplicate whose source is gone and whose exact content is on the destination is recorded `Found_At_Destination` from that evidence, never `Failed` and never as an action it did not take. An entirely empty source folder is asked about rather than guessed at (`an empty source asks before anything is recorded`; engine-spec §4.2). |
| 11 | **Complete lineage is reconstructable for every catalogued file, in every settled status** — original Index snapshot, current state, creation origin, and every operation it took part in | `webui-spec.md` §6.3, `engine-spec.md` §10 | **Enforced**, tested (`every_catalogued_file_assembles_complete_lineage`). Two catalogs, because one cannot hold every status at rest: a run ending in Move leaves `Completed`/`Failed`/`Removed_Duplicate`, one ending in a targeted Copy leaves `Pending`/`Copied`/`Duplicate`. The test asserts the required set is covered, so a NEW status that nothing verifies fails it. The guard also rejects settled source removals still recorded as present and successful transfer intents with no destination participant. Interrupted-Move tests cover verified fresh delivery, reuse of an existing copy, duplicate removal, unverified destinations and atomic rollback of a failed lineage repair. **One documented exception:** a destination the engine found rather than created has no source snapshot, because no Index ever saw it; it is recorded as `observed_destination` with a NULL origin rather than given a fabricated one. Verified against a real-library catalog of 971 identities at 0.02–0.08 ms per history. |
| 12 | **A settled run's whole history is fsynced when it settles**, including scan results and audit rows the scan path committed at `NORMAL` | `finish_run`, `engine-spec.md` §5 | **Enforced**, tested (`a settled run fsyncs the history its scan committed at normal`). In WAL mode a `FULL` commit fsyncs the WAL file, which covers every earlier `NORMAL` commit in it: one history-settle fsync per run (a dirty count-cache rebuild adds its own commit). **Why not `FULL` on the scan path:** it pays the ~4.4x on every batch to protect rows a re-Index reproduces. Backup attempts record their outcome at `FULL` too. **Scope:** a run killed before it settles is not covered — its last `NORMAL` batch can be lost to a power cut, it is recorded `Interrupted`, and a re-Index reproduces the scan rows; a database writer that misses its 60 s shutdown deadline can commit after the settle. Like claim 10, the claim stops at the fsync. **If a power cut takes a run's scan rows anyway, the next Index re-creates them identically**, tested (`scan rows lost with their commits are recreated by the next index`). |
| 13 | Startup reconciliation commits at `synchronous=FULL` | `reconcile_interrupted_state` | **Enforced**, tested (`startup reconciliation commits at full synchronous`). Recovery records evidence and attention state — conclusions from observations that may not be repeatable, because storage disappears and files are replaced between runs. A lost repair would discard the only record that an outcome could not be established. It runs once per interrupted row at startup, so the cost is negligible. |
| 14 | A Move never deletes a source on the strength of an fsync a network share may acknowledge early | `--confirm-network-destination`, `engine-spec.md` §4.1 | **Enforced**, tested (`a move to a network share asks before anything is deleted`, `the destination filesystem is read from the mount table`). A client cannot see how a share is exported — an `async` NFS export acknowledges an `fsync` before the data is on disk — so the engine does not try to. It reads the destination's filesystem type from the mount table and, for a network filesystem, stops a Move before copying or deleting anything: a needs-attention issue recommends Copy (which never deletes, so it is the one way to guarantee no loss) and the user chooses Copy instead, Move anyway after confirming the share is exported `sync`, or neither. Copy is never stopped. **Residual, by the maintainer's decision:** a confirmed Move is only as durable as the share's honesty about `fsync`, and a mount table that cannot be read is treated as local. |

### Outstanding

- [ ] **Power-loss behaviour is reasoned about, not tested.** Every durability test asserts *which* fsyncs happen and in what order, not that a real power cut preserves the tree. The question splits in two. **Consequence** — "given this loss, does the engine do the right thing?" — is testable without hardware: construct the state a power cut leaves behind (for example, take a completed move and rewind the catalog behind it while the filesystem keeps what it did) and test what the next run concludes. Claims 10 and 12 now have such tests. Every future durability claim needs one too. **Mechanism** — "does `NORMAL` really lose that commit on this hardware?" — needs `dm-log-writes` or device-mapper `flakey` in a VM, or a statement that it is untested and why.

- [ ] **Re-audit these claims whenever the write path changes.** Defects in this path come from fixes to the path itself — a barrier added in one deletion caller and missing from another. A change to `copy_verify_delete`, `_mkdir_durable`, `_finalize_partial` or `_remove_verified_source` ends with this table re-checked rather than assumed.

## Before the first release

- [ ] **Decide on catalog migration.** `ns_db.py` stamps `catalog_schema.version` and refuses any catalog whose version it does not recognise. While every catalog is a development catalog, refusal plus a fresh Index is enough; that stops being acceptable once a user holds history that cannot be recreated.

## Other

Deferred performance and robustness work — a stalled worker having no deadline, the unchanged-file check loading every settled row, batch barriers at submission tails — lives in `engine-spec.md` §8 with the condition that should bring each one back. This file tracks claims that need enforcing; that section tracks work deliberately postponed.
