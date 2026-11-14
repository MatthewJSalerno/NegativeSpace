# TODO

Open work, open design questions and the durability claims ledger. Designs live in
`docs/`; features specified but not yet built are listed in
[project-spec.md](docs/project-spec.md) §4 ("Specified but not yet on screen").

Maintenance: update this backlog in the same change that implements and validates work.
Mark completed scope accurately, split partial engine/API/UI completion, and remove
duplicate open entries. Before every merge, reconcile component specs, this backlog,
validation notes and the private handoff against what is built and what remains pending.
Do not leave finished work unchecked or count it again.

## Punch list

Everything still open, one line each, to scan at a glance; the sections below hold the
details, and [project-spec.md](docs/project-spec.md) §4 the specified screens. Change
this list in the same change that adds or finishes an item. 💬 marks discussion only: no
development until the maintainer decides.

**Organizing**
- Audit 043 preview/review corrections, including the Copy/Move preview naming the Index it is based on, with Index source — built, A1 passed (`docs/manual-validation.md`, Audit 043 preview Index; `docs/webui-spec.md` §2)
- Earlier versions arriving again — exact copies built, EV1–EV3 passed; audit 045 fixes and long-list folding passed EV4–EV5; look-alike versions later (`docs/engine-spec.md` §10)
- Copy/Move preview grouped by destination folder — implemented; TP1–TP3 passed (`docs/manual-validation.md`, Destination folder preview; `docs/webui-spec.md` §2)
- Menu items show only their names; what the pointed item does shows in one line at the menu's foot (Jobs, Select); submenus open in place — built, MN1 passed (`docs/manual-validation.md`, Menu descriptions; `docs/ui-design.md`, Menus)
- 💬 Source-folder handling behind the scenes
- 💬 A content-history link from a photo to its earlier versions

**Review**
- "Looks like a reject" (decided)
- Undated-photo evidence and per-library back-test — decided, not built (`docs/webui-spec.md` §3.1)
- Review history speed with many decisions

**Similar photos**
- 💬 Selected-photo gallery discoverability and selecting photos inside grouped sets
- Large-library measurement (250,000 and 500,000 photos)
- 💬 Local AI image embeddings for look-alikes, crops included (the maintainer is reading up first)

**Metadata**
- Notices for metadata choices, and their queue in Not organized
- Metadata decisions for arrivals matching photos already in Library or Rejects
- Notice for Google Takeout and Flickr export sidecars
- Motion-photo editing, qualified separately
- RAW, TIFF/HEIC and extended-XMP fixtures for the metadata scenario builder
- Malformed or conflicting capture dates in date review
- Deferred: bulk and cross-photo date editing
- 💬 Legacy IPTC precedence and additional RDF mappings
- 💬 Photos arriving again in another form: a relationship layer with metadata-independent hashing (parked, `docs/webui-spec.md` §3.1)
- 💬 Sidecars edited between Index and Copy or Move
- 💬 Similar photos and metadata together
- 💬 Copying all metadata, or a wider choice of fields

**Checking and maintenance**
- Check library — built, CL1–CL2 passed (`docs/manual-validation.md`, Check library; `docs/webui-spec.md` §7.6)
- Renames the user made, recorded by the check — built, RN1 passed (`docs/manual-validation.md`, Renames recorded by the check; `docs/webui-spec.md` §7.6)
- Copied photos whose originals are still in the source: a note under Library, **Originals in source** with its count, opening Source folders › Still in source — built, OS1–OS2 passed (`docs/manual-validation.md`, Originals in source; `docs/ui-design.md`, Page frame)
- 💬 The user's own groupings of Library photos (a trip, an album) without breaking the date folders (`docs/webui-spec.md` §7.6)
- Repair: Move it back, back from Rejects and Copy it back — built, RP1 passed 2026-11-11 (`docs/manual-validation.md`, Repair; `docs/webui-spec.md` §7.6)
- Repair: Keep the new version and It's an edit of this photo — built, RP2 passed 2026-11-11 (`docs/manual-validation.md`, Repair; `docs/engine-spec.md` §9.2)
- A photo in the wrong folder: the finding states the date mismatch, and fixing the date in the date editor files it and clears the finding; while any finding is open, the Destination path says what the check saw there and Rename waits — built, RP3 passed 2026-11-11 (`docs/manual-validation.md`, Repair; `docs/webui-spec.md` §7.6)
- Repair of a photo with a delivered XMP sidecar (the pair moves together), the catalog-only answers (Stop warning about this among them), Add to catalog and Rebuild from the earlier version — decided, not built (`docs/engine-spec.md` §9.2, `docs/webui-spec.md` §7.6)
- A file or folder name holding a line break or another control character: Index leaves it out and lists it as Skipped, Check library lists one in the Library as Invalid name, Rename refuses one — built, LB1 passed 2026-11-12 (`docs/manual-validation.md`, Invalid names; `docs/engine-spec.md` §4.2)
- Import summary, and a filter for files that could not be previewed
- Skip unreadable files at Index, counted by kind — decided, not built (`docs/engine-spec.md` §4.1)
- Every warning offers a way out
- Re-audit durability claims whenever a write path changes

**Before the first release**
- Decide on catalog migration
- Review every message the user sees — message boxes standardised (plain note, neutral box, highlighted box), MB1 passed (`docs/ui-design.md`, Message boxes)
- Version 1.0.0 and the changelog
- Test power-loss behaviour on real hardware

**Later**
- Reports (checksum lists)
- Videos and other non-photo files

**💬 Waiting on the maintainer**
- Discovering filters across places
- Full-screen preview clutter; copying all metadata; source folders handled behind the scenes
- Visual check of where Clear all filters sits

## Uncertain file outcomes

- [ ] Repair's remaining fixes, Add to catalog and Rebuild from the earlier version: decided, not built; Check library and Repair's Move it back, back from Rejects, Copy it back, Keep the new version and It's an edit are built (`docs/engine-spec.md` §9.2, `docs/webui-spec.md` §7.6).
  `recovery.md` gets its entry when this is built.
## Views

- [x] Refresh user-guide screenshots for the current setup and review workflows (dark,
  1440 × 900, NASA demo set), including Notifications and Settings › Performance.

## Needs review

- [ ] Incoming-alternative decisions for already organized/rejected matches, with independent
  metadata/location choices. Durable BLOB storage and engine primitives are built;
  their decision UI remains unfinished. Import-pair retry is already built.
- [ ] Add No capture date and sidecar/edit reasons to the shared inbox with their respective workstreams.
- [ ] Bulk answers for future file-changing review reasons: not built (`docs/webui-spec.md` §7.9).
- [ ] Automatic history for future review reasons: not built (`docs/webui-spec.md` §7.9).
- [ ] Broader performance coverage with many accumulated review events. A 200k-photo
  generated catalog has been checked with an empty history; this does not model
  years of bookmarks and acknowledgments.

- [ ] "Looks like a reject": designed, not built (`docs/webui-spec.md` §7.8).
- [ ] 💬 Dates from other applications’ records: parked for discussion (`docs/webui-spec.md` §3.1).
- [ ] Undated-photo evidence, suggestions and per-library back-test: decided, not built (`docs/webui-spec.md` §3.1).

## Similar photos

- [ ] Selected-photo gallery discoverability and grouped-set behavior. Show only
  selected already exists; discuss before adding another control.
- [ ] Follow the [large-library measurement plan](docs/large-library-performance.md):
  query performance at 250k/500k, dense and overlapping sets, memory, invalidated caches
  and response times. Repeat A/B runs before claiming supported capacity. Original-file
  processing, comparison build costs and long-session browser work remain separate;
  filesystem latency is not benchmarked. The 75% floor is the chosen range. Measure a
  concrete bottleneck before proposing another database.
- [ ] **Discussion only; the maintainer is reading up first: local AI image embeddings.**
  pHash cannot match a cropped copy. A CLIP-style model run locally (OpenCLIP, SigLIP)
  turns each photo into a vector at Index; near vectors find look-alikes, crops and edits
  included, and text search comes with it. Costs: a model of roughly 150-600 MB in the
  image, a fraction of a second per photo on a CPU, and a vector index. It measures what a
  picture shows, not whether it is the same photo, so "duplicate" needs a strict threshold.
  Immich, which reads `library/`, already runs one for smart search and duplicate
  detection; the case for it here is catching look-alikes before files are organized.
  Cheaper ways to match crops were considered and not pursued: hashing fixed sub-regions
  (catches only crops near those sizes, adds wrong matches) and local feature matching
  such as ORB/SIFT (slow pairwise comparison, a new library).

## Dates and metadata

The editing priority is accurate dates and reliable organization, not a
general-purpose EXIF editor. Keep the existing common-field foundation and the agreed
release limits; do not expand format/tag coverage to close this workstream.

### Engine closeout: 7 of 7 complete, 0 feature tasks remaining

This is the authoritative countdown for the current metadata engine work. Keep the task
numbers fixed, report progress as **Task X of 7**, and disclose any scope change. Tests
and documentation belong to each task. Final regression/review, commit and push are
release gates, not additional feature tasks. API/UI work and deferred ideas below are
outside this countdown. The source viewer and single-photo date editor are built and passed manual acceptance.
The decision controls below remain pending.

| Task | Status | Remaining scope / completed boundary |
| --- | --- | --- |
| 1 of 7 | Complete | Photo-only embedded-XMP/EXIF read priority and deliberate Library embedded-source switching, with verified filing and immutable history. |
| 2 of 7 | Complete | Resolved multiple-sidecar first imports: full-name or explicit primary, exact alternative retention, ownership records and verified shared-source cleanup/recovery. Unresolved choices remain held. |
| 3 of 7 | Complete | Confirmed incoming **Use incoming** / **Return to Library** choices execute through verified metadata jobs. Independent metadata/location choices, exact alternatives, late-XMP imports, immutable applied receipts, backup/refiling/retry and separately verified source cleanup are tested. |
| 4 of 7 | Complete | Compose present supported fields from an immutable base with explicit donor/typed overrides, final-value and per-field provenance previews, unchanged primary target, verified XMP/JPEG saves and retained originals. Missing base fields stay unchanged; explicit empties remain empty. |
| 5 of 7 | Complete | Reapply supported source/pre-edit effective metadata through a new verified edit, preserving history and distinguishing absence from emptiness. XMP/JPEG EXIF removals, current-primary binding and unchanged-image history checks are tested; no exact photo-byte reconstruction or lost-image recovery promise. |
| 6 of 7 | Complete | Qualified mapped EXIF removals, preservation/read-back and explicit CLI removal. Agreed release: JPEG embedded writes and XMP sidecars; embedded TIFF/HEIC/RAW deferred. Unrepresentable EXIF values refuse without primary fallback. See the release writer matrix in the metadata contract. |
| 7 of 7 | Complete | Job-scoped Move consent, read-only affected-file preview, live original/retained hash and image-history proof, sidecar archives/shared owners, pre-action backup and durable cleanup/retry. Nineteen generated-fixture tests pass, including batch consent, unrelated normal transfers, Rename, Rejects and interruption between photo/XMP cleanup. No permanent deletion consent; web prompt remains separate. |

Closeout validation (2026-10-10): 409 metadata regression tests passed; the final
source-cleanup suite passed all 19 cases. The engine smoke suite passed 154 tests,
including both public RAW checks, with zero failures/skips. Specification references,
schema/API documentation and whitespace checks passed. The engine branch is committed
and merged through PR #105 after passing CI. PR #107 combined it with navigation
and schema 28; all 68 combined CI steps passed before merge.
The API/UI checklist below is separate.

PR #105 follow-up: corrected the web job-identity check to include the engine’s
edited-source consent field as false. This prevents accepted jobs from appearing
refused. Request replay and explicit CLI consent remain distinct; no cleanup consent
is granted by this correction. The original failing browser suite now passes, as do
117 API/source-cleanup tests and specification/API checks. The full GitHub run passed
and the fix is merged.

**The read-only viewer and first date editor have passed maintainer validation.**
Follow-up presentation spot-checks passed; future controls still need acceptance. Automated engine results do not establish
acceptance of the editing experience. As the remaining controls are built,
validate metadata-source selection, date edits and destination previews, save/recovery
feedback, and the one-job confirmation for removing edited originals. GitHub CI and code review remain separate merge checks.

For tasks 4–5, donor choice never changes the write target. Logical fields carry their
related tags together, with no invented or mixed components. See
[the metadata contract](docs/xmp-metadata.md) for the agreed behavior and limitations.

### Completed engine foundation

- [x] Generated JPEG content-fingerprint experiment: 20 tests plus warm-read measurements;
  see [jpeg-content-hash-experiment.md](docs/jpeg-content-hash-experiment.md).
  No production image-only hashing or image-content consolidation is enabled.

### Motion-photo and expanded-format qualification

- [ ] Qualify embedded motion-photo editing as a separate workstream (maintainer
  decision: retain the current refusal for this release). The current JPEG writer
  deliberately refuses trailers; sidecar saves preserve Google legacy, Pixel and
  Samsung video bytes. Regression tests assert both successful sidecar preservation
  and nonmutating embedded refusal. Do not relax the boundary solely because ExifTool
  can retain the video; verify the complete engine write/publication path first.
- [ ] Builder-owner planned fixtures: RAW EXIF versus sidecar, DNG embedded XMP,
  Lightroom RAW/JPEG metadata differences and ownership hints, case-varied RAW
  sidecar names, TIFF/HEIC embedded XMP, and extended JPEG XMP. These cases are not
  built or required to claim the currently bounded Date taken UI is implemented.
  Request builder changes from the maintainer; do not silently expand writer support.

### Export-service metadata guidance

- [ ] Detect recognized Google Photos/Takeout and Flickr export-sidecar naming/layout
  during Index; show counts and affected source files. Before Copy/Move, offer one
  selection-level choice: prepare externally first, import without export metadata,
  or skip affected photos while organizing the others. Readable photos are not failed.
  Import uses embedded metadata and supported XMP; export sidecars remain untouched,
  including during Move. Do not identify a provider from `.json` alone or guess photo
  associations; uncertain evidence is Possible export metadata.
- [ ] Provide minimal export-preparation guidance: external-tool links and a rough
  workflow only. Convert export metadata to XMP, prepare photos plus XMP in a clean
  source folder (or optionally remove old export sidecars externally after checking
  the conversion), then select the source and reindex before Copy/Move. Check links
  and advertised capabilities before publication. No in-app conversion/deletion,
  detailed tool tutorials or conversion-support workstream. See webui-spec §7.5.

### API/UI work — source viewer/date editor built; decisions pending

First UI scope agreed: show metadata broadly, edit/copy **Date taken only**. The
common-field engine remains intact. General metadata editors, whole-source composition,
cross-photo/bulk copying and date shifts are deferred controls, not prerequisites.
Saved orientation stays a separate action from temporary preview rotation.

- [ ] Metadata-choice job notices and linked Not organized queue; metadata-difference
  review for edited Library photos and combined metadata/location choices for rejected
  matches. Retained alternatives already have engine preservation notices/history.
- [ ] Deferred broader composition/cross-photo and bulk date controls. Engine support
  exists for qualified common fields; exposing it is outside the first date UI. Preserve
  explicit donor/target roles and never choose primary implicitly (`webui-spec.md` §7.5).

### Deferred work and open discussions

- [ ] **Future discussion: Similar photos and metadata.** Revisit how similarity review
  and metadata workflows should work together, alongside the deferred cross-photo
  metadata controls above. Scope and behavior are undecided; discussion only.

- [ ] Malformed/raw EXIF and conflicting capture-tag review — unbuilt; recorded-date acknowledgment is tracked above (`docs/webui-spec.md`, Suspicious dates).
- [ ] **Deferred by maintainer:** production metadata-independent image hashing,
  broader fingerprint formats and image-content duplicate consolidation. Retain the
  tested JPEG experiment; complete metadata preservation/editing first. Its intended use
  is the parked relationship layer (`docs/webui-spec.md` §3.1).
- [ ] Destination inventory and repair: **Check library** is built; **Repair** in place moves
  and copies photos back, and the rest is decided, not built (`docs/engine-spec.md` §9.2). Ordinary per-operation collision/write
  verification is required.
- [ ] Revisit sidecars edited externally between Index and Copy/Move. For now the user
  reindexes after an external edit; existing verification/deletion gates still apply.
- [ ] Legacy IPTC precedence/mappings and additional RDF representations require decisions
  and fixtures. Preserving extracted evidence does not imply a qualified read/write mapping.

## Warnings that need a way out

- [ ] An import-completion summary and a catalog-wide filter for files whose visual
  processing failed, distinguishing corrupt data from missing decoder support and IO
  failures; absent EXIF is not proof of damage. Do not retry unchanged bad files.
- [ ] Audit warnings throughout the app for a working action or a direct route to the
  affected items ([validation and feedback contract](docs/ui-design.md#validation-and-feedback)).

## Durability claims: stated vs enforced

Every durability claim resolves to either **enforced and tested** or **a documented limitation** — never something the prose asserts and the code only usually does. **A claim that cannot be enforced is raised with the maintainer before it is weakened:** weakening a guarantee is his decision, not an editorial fix. Until he decides, mark it **Unresolved** here with what fails and why.

| # | Claim | Stated in | Status |
| :--- | :--- | :--- | :--- |
| 1 | A source is deleted only after its copy's **bytes** are fsynced | `engine-spec.md` §4.2, §7 | **Enforced**, tested (`durability barriers precede source deletion`) |
| 2 | …and after the copy's **own directory entry** is fsynced | `engine-spec.md` §4.2 | **Enforced**, tested |
| 3 | …and after **every ancestor entry from `--dest` down**, retried until it succeeds | `engine-spec.md` §4.2 | **Enforced at the deletion gate**, for all source-deletion callers, tested (`a failed ancestor sync is retried not forgotten`, `the already present deletion establishes the ancestor barrier`, `duplicate cleanup establishes the ancestor barrier`) |
| 4 | The chain walk never touches anything **above** `--dest` | this file | **Enforced**, tested (`the durability chain never reaches above the destination`) |
| 5 | The source is unchanged since it was verified | `engine-spec.md` §4.2 | **Enforced**, tested (`a source edited after verification is kept`) |
| 6 | The copy is a different file from the source | `engine-spec.md` §4.2 | **Enforced**, tested (`a source is never deleted as its own copy`) |
| 7 | `mtime` is preserved by a copy | `engine-spec.md` §9.2 | **Enforced**, tested (`a delivered copy keeps its source mtime exactly`) — to the nanosecond, for Copy and Move, with undated and dated photos |
| 8 | The documented repair for a destination file removed outside the engine — re-index with `--force-rehash`, then Copy — actually re-delivers it | `Skipped` reason string, `webui-spec.md` §5.3 | **Enforced**, tested (`the documented recovery redelivers a removed destination file`) |
| 9 | A filesystem that cannot fsync directories **says so at runtime**, rather than leaving the weaker guarantee to be inferred from this document | `engine-spec.md` §4.2 | **Enforced**, tested (`an unsupported directory fsync is reported once per run`). Once per run, naming the first such directory — once per directory would be a line per date folder. |
| 10 | The move/copy loop **commits its intent at `synchronous=FULL`** before source unlink: ordinary transfers use `status=Processing` with `dest_path`; edited-source cleanup uses its own journal and verification while the photo stays organized | `get_db_connection`, `engine-spec.md` §5 | **Enforced**, tested (`the move loop commits at full synchronous`). Scoped to that one connection — the scan path keeps `NORMAL`; measured 1.42x on the move path (+1.9 ms/photo) against the ~4.4x `NORMAL` buys on the scan path. **The claim stops at the fsync:** whether a real power cut preserves it depends on the storage honouring it, which is untested (see the power-loss item below). **If the marker is lost anyway, the next run still records the truth**, tested (`a move whose catalog commits were lost is recorded as found`): a photo or duplicate whose source is gone and whose exact content is on the destination is recorded `Found_At_Destination` from that evidence, never `Failed` and never as an action it did not take. An entirely empty source folder is asked about rather than guessed at (`an empty source asks before anything is recorded`; engine-spec §4.2). |
| 11 | **Complete lineage is reconstructable for every catalogued file, in every settled status** — original Index snapshot, current state, creation origin, and every operation it took part in | `webui-spec.md` §6.3, `engine-spec.md` §10 | **Enforced**, tested (`every_catalogued_file_assembles_complete_lineage`). Four catalogs, because one cannot hold every status at rest: a run ending in Move leaves `Completed`/`Failed`/`Removed_Duplicate`; one ending in a targeted Copy leaves `Pending`/`Copied`/`Duplicate`; lost catalog commits leave `Found_At_Destination`; rejecting after a Move and after a Copy, then emptying Rejects, leaves `Rejected`/`Rejected_Copied`/`Rejected_Emptied`. The test asserts the required set is covered, so a NEW status that nothing verifies fails it. The guard also rejects settled source removals still recorded as present and successful transfer intents with no destination participant. Interrupted-Move tests cover verified fresh delivery, reuse of an existing copy, duplicate removal, unverified destinations and atomic rollback of a failed lineage repair. **One documented exception:** a destination the engine found rather than created has no source snapshot, because no Index ever saw it; it is recorded as `observed_destination` with a NULL origin rather than given a fabricated one. Verified against a real-library catalog of 971 identities at 0.02–0.08 ms per history. |
| 12 | **A settled run's whole history is fsynced when it settles**, including scan results and audit rows the scan path committed at `NORMAL` | `finish_run`, `engine-spec.md` §5 | **Enforced**, tested (`a settled run fsyncs the history its scan committed at normal`). In WAL mode a `FULL` commit fsyncs the WAL file, which covers every earlier `NORMAL` commit in it: one history-settle fsync per run (a dirty count-cache rebuild adds its own commit). **Why not `FULL` on the scan path:** it pays the ~4.4x on every batch to protect rows a re-Index reproduces. Backup attempts record their outcome at `FULL` too. **Scope:** a run killed before it settles is not covered — its last `NORMAL` batch can be lost to a power cut, it is recorded `Interrupted`, and a re-Index reproduces the scan rows; a database writer that misses its 60 s shutdown deadline can commit after the settle. Like claim 10, the claim stops at the fsync. **If a power cut takes a run's scan rows anyway, the next Index re-creates them identically**, tested (`scan rows lost with their commits are recreated by the next index`). |
| 13 | Startup reconciliation commits at `synchronous=FULL` | `reconcile_interrupted_state` | **Enforced**, tested (`startup reconciliation commits at full synchronous`). Recovery records evidence and attention state — conclusions from observations that may not be repeatable, because storage disappears and files are replaced between runs. A lost repair would discard the only record that an outcome could not be established. It runs once per interrupted row at startup, so the cost is negligible. |
| 14 | A Move never deletes a source on the strength of an fsync a network share may acknowledge early | `--confirm-network-destination`, `engine-spec.md` §4.1 | **Enforced**, tested (`a move to a network share asks before anything is deleted`, `the destination filesystem is read from the mount table`). A client cannot see how a share is exported — an `async` NFS export acknowledges an `fsync` before the data is on disk — so the engine does not try to. It reads the destination's filesystem type from the mount table and, for a network filesystem, stops a Move before copying or deleting anything: a needs-attention issue recommends Copy (which never deletes, so it is the one way to guarantee no loss) and the user chooses Copy instead, Move anyway after confirming the share is exported `sync`, or neither. Copy is never stopped. **Residual, by the maintainer's decision:** a confirmed Move is only as durable as the share's honesty about `fsync`, and a mount table that cannot be read is treated as local. |
| 15 | A destination file with an unresolved needs-attention issue never authorizes deleting a duplicate source | `ns_db.paths_needing_attention`, `engine-spec.md` §4.2 | **Enforced**, tested (`a_copy_needing_attention_never_authorizes_removing_a_duplicate`, and the database tests for the lookup). Move's duplicate cleanup drops such copies from its candidates before verifying bytes; with none left the source stays, recorded `Skipped` with the reason, and the next Move after the issue is resolved removes it. A matching SHA-1 alone is not enough, because recovery could not establish what is at that path. |
| 16 | Retained XMP originals round-trip exactly from an intact catalog or a backup containing them; corrupted payloads are never published as verified backups | `xmp_store`, `docs/xmp-metadata.md` | **Enforced for the storage primitive**, tested (`xmp_store_test.py`): bounded decode, size/hash checks, FULL transaction and rollback, backup restoration/refusal, arrival watermark including a concurrent arrival. Index retention and resolved first-import/transfer paths are connected; user restoration is not built; this is not a photo rollback or hardware-loss guarantee. |
| 17 | A recorded photo/XMP pair verifies and durably records both new members before source deletion or retiring old destination names; recovery never treats the photo alone as complete | `metadata_transfer`, `metadata_relocate`, `docs/xmp-metadata.md` | **Enforced for the internal transfer and recorded-pair relocation paths**, tested (`metadata_transfer_test.py`, `metadata_relocate_test.py`): publication failures keep originals; partial cleanup is observed/retried; missing members prevent completion; failed directory barriers are repeated; retry preserves history. Mutations removing the pair-evidence gate or the old-directory recovery sync fail the regression tests. Resolved first imports and confirmed incoming primary/Return choices are connected; decision screens remain unfinished; confirmed import-pair web retry is connected; XMP/qualified JPEG edits are connected. Hardware power loss and dishonest network fsync remain documented limitations. |
| 18 | A source whose organized photo has embedded edits is retired only under explicit consent for this Move job, with verified image history, current files, retained metadata and pre-action backup | `metadata_source_cleanup`, `docs/xmp-metadata.md` | **Enforced in the engine**, tested (`metadata_source_cleanup_test.py`): 19 generated cases cover consent/replay, live hashes, backup/fsync failure, shared XMP, changed/symlinked files, interruption/retry, Rename and Rejects. This deliberate exception retains an edited photo, not exact original photo bytes. Web confirmation is built and maintainer-validated; `move_confirmation_test.py` and its browser driver cover consent, stale scope and replay. |

### Outstanding

- [ ] **Power-loss behaviour is reasoned about, not tested.** Every durability test asserts *which* fsyncs happen and in what order, not that a real power cut preserves the tree. The question splits in two. **Consequence** — "given this loss, does the engine do the right thing?" — is testable without hardware: construct the state a power cut leaves behind (for example, take a completed move and rewind the catalog behind it while the filesystem keeps what it did) and test what the next run concludes. Claims 10 and 12 now have such tests. Every future durability claim needs one too. **Mechanism** — "does `NORMAL` really lose that commit on this hardware?" — needs `dm-log-writes` or device-mapper `flakey` in a VM, or a statement that it is untested and why.

- [ ] **Re-audit these claims whenever the write path changes.** Defects in this path come from fixes to the path itself — a barrier added in one deletion caller and missing from another. A change to `copy_verify_delete`, `_mkdir_durable`, `_finalize_partial` or `_remove_verified_source` ends with this table re-checked rather than assumed.

## Before the first release

- [ ] **Review every message the user sees**, once the screens are settled: a private
  document listing each message's text with where it appears and the scenario that shows
  it (screen, condition), drawn from the screens, the API's error messages and the
  engine's reasons that reach the page, so the maintainer can read them all in one place.

- [ ] **Version 1.0.0 and the changelog:** keep [CHANGELOG.md](CHANGELOG.md) current as each
  change merges; 1.0.0 is the first release ([Semantic Versioning](https://semver.org/)).

- [ ] **Decide on catalog migration.** `engine/ns_db.py` stamps `catalog_schema.version` and refuses any catalog whose version it does not recognise. While every catalog is a development catalog, refusal plus a fresh Index is enough; that stops being acceptable once a user holds history that cannot be recreated.

## Later

- [ ] **Reports**, not designed yet. A first candidate: a checksum list (`sha1sum` format)
  of the library, and of the source, so a user who copies and then deletes originals
  themselves can verify every copy with standard tools, independently of NegativeSpace.

## Other

Deferred performance work — the unchanged-file check loading every settled row and batch barriers at submission tails — lives in `engine-spec.md` §8 with the condition that should bring each one back. This file tracks claims that need enforcing; that section tracks work deliberately postponed.

Stalled read-only workers now support user-requested cancellation of decoder process
groups, with a no-progress reminder and Keep waiting. Kernel-blocked storage remains
an explicit limitation in engine-spec §8; automatic file skipping is not planned.
- [x] Removed the unused `metadata.resolve_sources`; retained shared JSON validation and moved adapter/parser integration coverage to the production resolver (`docs/xmp-metadata.md`).

## Navigation refinement

Completed entries below retain earlier validation results. References to pins, Review
later and remembered per-place filters are historical; the current sidebar/refinements
and Bookmark contract is in `docs/ui-design.md`, Page frame.

- [x] Automated validation: 155 notification/database/API tests; full browser workflow,
  notification persistence/retry/geometry, safety decisions, job-refresh requests and
  both Reject workflows passed. Shared light/dark and narrow-window screenshots inspected;
  spec/schema/API checks passed. No claim of full UI acceptance from automated checks.
- [x] Final local checks: navigation, preview refresh, mixed/all-failed transfers and
  stalled-job cancellation passed; oversized notification IDs are rejected before SQLite,
  and old job-photo links follow subsequent Reject/Return operations. Contract checks passed.
- [x] Final automated validation: 116 API/review tests, focused pin browser flow, full
  browser/shared UI and review workflows, spec/API/schema checks and light/dark/narrow
  screenshot review passed. Clear action geometry and source-folder reset are covered.
- [x] Consolidate page-frame/date-scrubber/refinement into the gallery UX PR. Metadata
  is merged; combined schema 28 preserves metadata tables and notification receipts.
- [x] Validate the combined metadata/navigation integration locally: 195 database/API
  tests, six browser workflows, frontend build and spec/API/schema checks passed.
  File issues uses the sidebar and its pin rules; older schema-26/27 catalogs are
  refused without modification.
- [x] Combined GitHub checks passed (68 steps); PR #107 merged after #105. Superseded
  PRs #104/#106 closed. Main includes the full navigation and metadata engine stack.

- [ ] Post-validation discussion: whether/how to expose copying all metadata or a broader
  field selection. Date-only copying remains the current UI scope; no implementation yet.

- [ ] Future discussion (accepted Test 3b): could source-folder handling happen behind
  the scenes? Clarify the desired behavior before changing selection or action rules.

- Guide screenshots for sidebar, Bookmarks and current workflows — refreshed from main with the NASA demo set (`docs/user-docs-standard.md`, Screenshots).

- Date-bookmark entry — built; reason/note and metadata precede editing, SB5a recheck passed (`docs/manual-validation.md`, Sidebar and Bookmarks).

## Additional ideas — discuss and approve before building

Append new assistant-suggested features here, after the existing backlog. Include a
concrete use case and keep each idea unapproved until the maintainer discusses and
approves it. Do not include these ideas in implementation batches without approval.
Detailed proposals belong in the relevant specs; entries here remain one-line pointers.

- 💬 Downloadable Copy/Move plan — possible use case: inspect or save a large proposed import in a spreadsheet; unapproved, discuss only after every other requirement is built (`docs/webui-spec.md` §2).

- 💬 Large transfer preview — discuss reducing a 114-page folder list to a useful summary with optional details; use case: understand a large import without paging through every folder; not approved (`docs/manual-validation.md`, Destination folder preview).
