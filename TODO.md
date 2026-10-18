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
- Rename and "Also arrived as" from the photo panel
- Copy/Move preview grouped by destination folder, and a downloadable plan
- "A job is already running" just after a job finishes
- Last-scanned time for each source folder
- Not organized filters: small images, identical copies, processing errors
- Not organized: sidecar and version decisions ("Which photo is this sidecar for?")
- Telling apart two different photos with the same name on their cards

**Review**
- Answer many photos at once within one reason
- Suspicious dates in the review queue, with "this date is correct"
- "Looks like a reject"
- "No capture date": suggested dates from the name, folder or a look-alike
- Record in history when a review reason clears itself
- Review history speed with many decisions

**Similar photos**
- Merge the two "Reject?" dialogs into one (decided)
- Remove Explore reference sets (decided)
- 💬 Selected-photo gallery discoverability and selecting photos inside grouped sets
- Overlapping sets beyond one step
- [x] Rotated matches: compare photos as displayed
- Large-library measurement (250,000 and 500,000 photos)
- 💬 Local AI image embeddings for look-alikes, crops included (the maintainer is reading up first)

**Metadata**
- Choose an organized photo's primary metadata source
- Notices for metadata choices, and their queue in Not organized
- Saved rotation (Rotate…)
- Notice for Google Takeout and Flickr export sidecars
- Motion-photo editing, qualified separately
- RAW, TIFF/HEIC and extended-XMP fixtures for the metadata scenario builder
- Malformed or conflicting capture dates in date review
- Deferred: bulk and cross-photo date editing
- 💬 Legacy IPTC precedence and additional RDF mappings
- 💬 Metadata-independent image hashing and content-based duplicate consolidation (deferred)
- 💬 Sidecars edited between Index and Copy or Move
- 💬 Similar photos and metadata together

**Checking and maintenance**
- Destination check on screen, then a broader inventory and repair
- Unbacked-changes line on every page, and Retry backup
- Index summary by file type
- Import summary, and a filter for files that could not be previewed
- Resolving files that cannot be read
- Stats: dates chart on its own row
- Every warning offers a way out
- Filter counts: distinguish zero, unavailable and incompatible
- Re-audit durability claims whenever a write path changes
- The `dest/raw-originals` folder
- Spacing and alignment pass; refresh the user-guide screenshots

**Before the first release**
- One sign-in password
- Decide on catalog migration
- Review every message the user sees
- Version 1.0.0 and the changelog
- State the minimum Linux and Docker versions
- Test power-loss behaviour on real hardware

**Later**
- Reports (checksum lists)
- Videos and other non-photo files

**💬 Waiting on the maintainer**
- Repairing a rearranged library without losing lineage
- Needs review: a separate place or a Library filter
- A SHA-1 content-history link
- Discovering filters across places
- Full-screen preview clutter; copying all metadata; source folders handled behind the scenes;
  "Open in the log" wording
- Visual check of where Clear all filters sits

## Uncertain file outcomes

- [x] Shared warning/evidence and Check it now in photo information and Logs; active
  Library issues also appear in Needs review → File issues. A read-only engine check
  resolves supported outcomes only with fresh verified evidence, preserving original
  history and the deletion gate while uncertainty remains.
- [ ] Broader destination inventory UI and external restoration guidance beyond the
  recorded operation pair remain separate from this scoped verification.
- [ ] **Discussion only; no development until the maintainer decides: repairing a
  rearranged library without losing lineage.** If files in `library/` are moved, renamed
  or deleted outside the app, the destination check (engine built, no UI) can report it
  but nothing repairs it in place. The documented repair (`engine-spec.md` §9.2) indexes
  the old library as a source into a fresh destination with a fresh catalog: photo IDs
  and run history do not carry over, and each photo's history restarts at its old library
  path. Reusing the same catalog does not work, because the catalog still records every
  photo as delivered at `/data/dest`, so the re-indexed files are treated as duplicates
  and nothing is written. The option to discuss is reorganizing in place: match each
  file to the catalog by content, put it back where it belongs, and record that as a
  step in its existing lineage. Until decided, `recovery.md` gets no entry for this case.

## Copy, then delete the originals yourself

- [x] Full Index detects externally missing originals of Copied Library photos, verifies
  their recorded destination, and records Found_At_Destination with source presence
  missing. Verified photos stay in Library and leave Move's eligible count. An empty
  source still requires confirmation; unverified copies enter File issues with Check
  it now. Repeat Index does not duplicate observations or retry an open file issue.
  Duplicate savings recognize observed deliveries; absent duplicate originals no longer
  contribute to Stats' “A Move would free.” No photo is moved or deleted by this check.

## Names

- [ ] "Also arrived as" in the photo panel: the other names and folders of identical
  copies, each with Use this name, plus Rename… and a Has other names filter; the engine's
  rename and candidate list already exist (`docs/webui-spec.md` §7.3).

## One screen per job

Found 2026-10-05 looking for screens that do the same job twice.

- [ ] **Merge the two "Reject?" dialogs into one** (decided 2026-10-05,
  `docs/ui-design.md`, "Rejecting while comparing"): the general confirmation
  (`Confirm.tsx`) and the comparison's own (`RejectConfirm.tsx`) become a single dialog,
  with "Don't ask again while comparing" and the last-photo warning appearing only where
  they apply. Every later reject question uses it.
- [ ] **Remove Explore reference sets** (decided 2026-10-05), leaving no trace: the window
  (`ReferenceSets.tsx`), the Explore related sets button on set cards, its API route
  (`/similar/{id}/sets`), its tests and its spec and API-spec text. The comparison covers it:
  ‹ › steps through a photo's look-alikes and **Use as reference** walks into a neighbouring
  set. Only the combined view of several overlapping sets goes; if it is ever missed, it
  returns as a section of the Similar photos tab, not a window.
- [x] Needs review decision layout: large photo, compact controls, one reason/action
  panel and a match-count link to the existing Similar photos tab. Remaining two-photo rejection
  proposals belong with the unbuilt "looks like a reject" reason below.

## Views

- [ ] Check Library/Jobs/Logs spacing and alignment in a future UI batch; preserve
  the reserved Jobs position so Logs does not shift when Jobs is unavailable.
- [ ] Refresh user-guide screenshots for the current setup and review workflows.
  The guide labels the existing screenshots as an earlier interface.

- [x] Empty review queues return to the filtered gallery with a completion message;
  closing review checks whether the open preview still belongs in the view.

- [x] Additional allowed addresses in setup and Settings, independent of catalog
  replacement; protected local/deployment recovery, revision checks and explicit
  confirmation before removing the current address.
- [x] Shared grouping-checkbox alignment, visible Inspector failure reasons, and
  a compact match-count link to the existing match browser, with browser Back
  returning to the same photo in review.

- [x] Fresh catalog setup replaces stale photo/log URLs with the base URL. Ordinary
  Index submission stays on its button without a transient global banner; uncertain
  requests retain recovery controls.
- [x] Undecodable source photos remain flagged in Not organized and are excluded from
  Copy/Move and Library matching. Missing EXIF/hash-only/cache-write failures do not
  block readable images. External repair plus Index reassesses failed sources.
- [ ] Discuss a SHA-1 content-history link, first comparing it with existing photo
  history/lineage to avoid redundant navigation. No pHash history link planned. A concrete
  use: since the hash is taken as displayed, a photo NegativeSpace rotates no longer looks
  like its unrotated original; content history is how a returning original is recognised.

- [x] Stable filter guidance and navigation: shared guidance sizing for Logs/gallery/
  review reasons; fixed Logs position when Jobs is absent; stable status shortcuts,
  filter summaries and action heights. Browser positions checked at desktop/reflow widths.
- [ ] Discuss whether Needs review remains a separate location or becomes a Library
  summary with reason filters. Keep navigation unchanged until decided; define the
  distinct-photo count and provide a visible Review later filter in any replacement.

- [x] Workflow order, Not organized guidance and Index summary; Library review markers
  open the photo’s reason in Needs review without changing selection, with a return
  to the entry Library context.
- [ ] Additional source-summary filters for small dimensions, identical copies and
  processing errors; date filters already work. Source similarity comparisons are
  not calculated and must not be presented as zero.

- [ ] **Same-named photos look identical on a card:** a card shows only the filename, so two
  different photos named alike (in different source folders) read as one photo in two
  places. Show the source folder on hover, or beside the name when the view holds both.

- [ ] **"A job is already running" just after a job finishes:** the engine keeps its lock
  while it takes the catalog backup that follows a settled run, so a start in that moment
  is refused with no running job shown. Say what is happening ("finishing the last job's
  catalog backup") and offer to start when it is done, or wait briefly before refusing.

- [x] Location views, overlapping Needs review inbox, combined filter chips, cross-location
  filename search and first-visit default (`webui-spec.md` §2).

## Needs review

- [x] Earliest expected year in setup and Settings; shared suspicious-date query policy
  updates counts, filtering and inspection without editing metadata. Schema 25 requires
  a fresh development catalog, following the existing no-migration policy.
- [x] Responsive Inspector waits behind already-open dialogs during resizing; Settings
  remains usable and retains focus until closed.
- [x] Explicit System/Light/Dark appearance preference and a shared Dark mode toggle
  across Library, Logs and Stats; shared page tools prevent header control drift.

- [x] Similarity grouping/control parity between Library and Needs review. Extra
  filters/search show every matching photo individually; clearing them restores the
  explicit grouping preference. Group representatives must belong to the inbox before
  collapsing; a reviewed representative cannot hide unreviewed members.

- [x] Inspector actions at the top, rejected-match disclosure above Library candidates,
  and bottom-aligned Review side by side labels across matching cards.
- [ ] Discuss cross-location filter discoverability: an active Suspicious dates filter
  can make Rejects appear empty after navigation. Filters currently persist; decide
  whether clearer feedback or per-place preferences would help before changing this.

- [x] UX consistency batch: one toggle row per place, in-place Small images filter,
  closed Inspector on place changes, contextual/collapsible source summary, grouped
  photo actions and the dedicated review layout. Date flags remain informational;
  persistent date acknowledgments remain unbuilt. Single-photo date editing is tracked below.

- [x] The in-tray for Small images and Review later (`docs/webui-spec.md` §7.9).
- [x] Library-only review decisions, source exclusion from similarity, backend eligibility, separate source
  failure facts, explicit Stats scopes and consistent Job #ID · Action status labels.
- [ ] Implement source-side sidecar/version import decisions in Not organized, separately
  from the Library inbox. The agreed contract is in `docs/xmp-metadata.md`; durable
  compressed-BLOB storage and engine import-decision/transfer-recovery primitives are built;
  their API/UI decision and recovery controls remain unfinished.
- [ ] Add the remaining Library reasons to the shared inbox/workspace: suspicious dates with acknowledgment;
  No capture date and sidecar/edit reasons with their respective workstreams.
- [ ] Bulk review answers within one reason. Individual Mark reviewed/Done and the
  existing bulk Reject workflow are built; general bulk acknowledgments are not.
- [ ] Record automatic reason clearing in review history. Current small-image
  eligibility is computed on read; explicit user decisions are recorded, but a
  setting/dimension change that removes eligibility does not append an event.
- [ ] Broader performance coverage with many accumulated review events. A 200k-photo
  generated catalog has been checked with an empty history; this does not model
  years of bookmarks and acknowledgments.

- [x] Manual cross-location matching: separate, paged Rejects matches in Library;
  Library matches for rejected references; location labels and confirmed Return or
  Reject actions. Keep-reference and gallery grouping remain Library-only. Review
  links retain candidate scope. Not organized and emptied rejects stay excluded.
- [ ] "Looks like a reject": a photo only similar to a reject (small pHash distance) is
  never rejected automatically; it waits in Needs review. With the reject still in
  Rejects: full side by side, Reject it too · Keep it · Keep the old one instead. With
  the reject emptied: its stored thumbnail and details (`docs/webui-spec.md` §7.8).
- [ ] "No capture date": suggested dates from the name, the folder or a dated look-alike,
  answered in bulk through the editor; the photo stays under `Undated/` meanwhile
  (`docs/webui-spec.md` §3.1).
- [x] "Review later": a button beside Reject… in the photo panel, with an optional short
  note; Done clears it (`docs/webui-spec.md` §7.9).
- [x] Small-image destination cleanup: user chooses on/off and minimum at first run;
  never blocks Copy/Move. Mark reviewed persists per photo/content and does not clear
  other reasons. Existing selection/Reject workflow; no bulk Keep or automatic unticking.
- [ ] "Which photo is this sidecar for?": a short-named XMP sidecar that could belong to
  several photos, held in Not organized until association is resolved
  (`docs/xmp-metadata.md`, `docs/engine-spec.md` §9.6).

## Similar photos

- [ ] Selected-photo gallery discoverability and grouped-set behavior. Show only
  selected already exists; discuss before adding another control.
- [ ] Broader relationships between overlapping sets beyond the current explicit
  one-hop exploration. Do not infer transitive matches.
- [x] Rotated matches assessed (`docs/engine-spec.md` §9.3): pHash is taken from the photo
  as displayed, which matches a portrait RAW to its own JPEG and copies stored turned with
  an orientation tag. Searching every rotation as well was measured and declined: on the
  demo library its new matches were two different, mostly black photos.
- [ ] Assess low-detail photos (mostly black or flat), which match unrelated photos at high
  percentages today: whether to mark them unreliable for matching. Discussion first.
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

These are completed capabilities, not additional open closeout tasks.

- [x] Pure metadata provenance resolver and qualified EXIF/embedded-XMP comparison:
  separate source snapshots, exact field origins, explicit empty-versus-absent rules,
  linked date/GPS components and retained unknown evidence. Legacy flat metadata is not
  used as qualified input; this is not full XMP conformance certification.
- [x] Bounded RDF/XML reader, complete-folder ownership planning, supported-value
  validation and independent generated ExifTool compatibility checks. Index captures
  proposed priority without activating a new primary or changing delivered files.
- [x] Exact XMP original BLOBs, Zstandard level 1 only when smaller, immutable
  versions/arrivals/participants, size/hash verification and catalog backup coverage.
  Parsed-data growth and backup costs were measured at 200,000 unique generated versions;
  see [xmp-storage-measurements.md](docs/xmp-storage-measurements.md). This metadata-only
  fixture is not a full-library capacity prediction.
- [x] Immutable ownership/primary decisions, version-bound previews, stale/replay refusal
  and backup coverage. Preferences and decision revisions freeze at job acceptance;
  later Settings changes do not affect the running job.
- [x] Resolved single-/multiple-sidecar first Copy/Move imports: primary/ownership and selected-date filing activate
  after pair verification. Shared-owner cleanup, collision/orphan refusal, space estimates,
  per-photo cancellation, explicit same-mode retry and read-only recovery are tested.
  Unresolved metadata choices remain at source with a specific explanation.
  Full-filename priority is applied without discarding alternatives; identical versions
  reuse a BLOB while retaining distinct arrivals. Shared ownership survives partial
  Move jobs, but a new file identity at an old source path cannot inherit that ownership.
  Every original must verify before source cleanup; incomplete cleanup requires explicit retry.
- [x] Photo-only imports apply embedded XMP before EXIF after verified delivery; automatic
  read priority does not establish an embedded write primary or override RAW-sidecar defaults.
  Explicit blank/partial dates stay Undated using the original file year. Reindex preserves
  established metadata/names; photo-only force Index retains delivery-repair eligibility.
- [x] Recorded photo/XMP pairs follow Rename, Reject and Return, verifying both new members
  before retiring old names. Recovery refuses photo-only success. Check it now observes
  without changing files; fault tests cover history, cancellation and durability barriers.
- [x] Incoming duplicate XMP alternatives and combined version/location choice records
  (schema 26). Keep current preserves primary/Rejects location. Copy keeps sources;
  Move cleanup verifies the retained photo, exact BLOB and shared ownership. Interrupted
  cleanup is retryable. Confirmed Use incoming/Return choices now apply through verified
  metadata jobs; sources remain untouched until a separate verified Copy/Move. Failed
  filing keeps saved metadata and requires explicit Retry; no implicit Return or undo.
- [x] Common-field plans and preservation-aware XMP saves: date, orientation, title/caption,
  keywords, rating, creators/rights and linked GPS. Unknown properties and exact originals
  survive; first XMP contains only requested fields. No fallback autofill or implicit
  primary change. True no-ops preserve bytes.
- [x] Bounded metadata JSON CLI with preview/apply/retry/discard, a job identity and
  per-photo outcomes, one verified pre-action backup per prepared batch, immutable
  before/after history and field donor provenance. Unchanged unsaved edits can be discarded;
  saved metadata survives failed refiling, with move-only retry. Unsafe shared storage
  stops new edits while preserving completed work. No job-level undo.
- [x] Deliberate Library XMP-version and embedded EXIF/XMP activation, with effective-value
  and date-filing preview. Embedded-source switching rewrites neither metadata source;
  inactive sidecars follow unchanged. Copy/Move holds unfinished metadata operations.
- [x] Qualified JPEG working-copy writer and durable publication/recovery: metadata
  read-back, protected encoded image/ICC bytes and decoded pixels, bounded tools,
  permissions and cleanup. Embedded XMP supports the common fields; EXIF refuses
  unrepresentable values. Source/retained content lineage, SHA/cache updates and date
  refiling are connected. Reindex preserves edited state and unfinished bindings;
  old duplicate pointers detach and exact-result duplicates are reported without deletion.
- [x] Generated JPEG content-fingerprint experiment: 20 tests plus warm-read measurements;
  see [jpeg-content-hash-experiment.md](docs/jpeg-content-hash-experiment.md).
  No production image-only hashing or duplicate consolidation is enabled.

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
  evidence and add an Index-result notice: affected count/list, sidecars are not imported,
  and a working Help route recommending dedicated export-preparation tools followed by
  reindexing. Verify any named-tool recommendations before publication. Do not parse/apply
  these sidecars or identify a provider from `.json` alone; label uncertain evidence as
  possible export metadata. Leave the files untouched and explain Move leaves them behind.
  This is informational, not a failed photo or Library review reason, and is separate
  from supported XMP handling. Detection and notice are both unimplemented.

### API/UI work — source viewer/date editor built; decisions pending

First UI scope agreed: show metadata broadly, edit/copy **Date taken only**. The
common-field engine remains intact. General metadata editors, whole-source composition,
cross-photo/bulk copying and date shifts are deferred controls, not prerequisites.
Saved orientation stays a separate action from temporary preview rotation.

- [x] Read-only source viewer in Photo information: separate XMP Sidecar / Embedded XMP / EXIF
  tabs, textual Primary badge and stable captured-field tables. Alternative tabs offer
  Compare with primary and Show differences only; distinguish Empty, Not recorded and
  unreadable/request failures. Follow `docs/ui-design.md` for the shared controls.
  Maintainer validation passed, including broken-sidecar source-attention guidance.
- [x] Source attention for processing failures and metadata holds, with a summary shortcut.
  Initial filtering acceptance passed. Updated navigation puts counted Needs attention
  beside Source folders under Not organized; only Source folders has a folder selector,
  and destination navigation clears its scope. Maintainer revalidation passed (Test 3).
- [x] Unpinning deactivates the filter and updates results/counts; unfiltered places
  use the sidebar total without repeating it in the gallery or pager. Filtered, grouped,
  selected and job/source scopes retain meaningful counts. Seven generated browser
  workflows pass, including filter reset and layout stability. Maintainer validation passed (Test 1).
- [x] Hide the year panel while No capture date is active (including pinned
  combinations), restoring it when cleared and sorted by date. No filing/filter change.
- [x] Rename the photo-opening action Inspect photo to distinguish it from Review
  later. Align Refresh comparison with Minimum similarity and place Keep below the
  reference preview’s details, separate from filtering. Maintainer validation passed (Test 2).
- [x] Expanding All recorded tags uses independent metadata scrolling on desktop,
  keeping candidate navigation in place; narrow layouts retain the outer scroll.
- [x] Maintainer passed acceptance Tests 1–6 and all follow-up checks (3b, 4f,
  5a, 5c–e) on 2026-10-13. No manual acceptance remains for this batch.
- [x] Empty source-folder rows use their own class, avoiding whole-screen empty-state
  styling; sibling label alignment is checked at desktop and narrow widths.
- [x] Explicitly clear Date taken blanks/disables visible date inputs. Unchecking
  restores the unsaved draft; preview and Save are still required.
- [x] Copy Date taken to primary: diagnosed a destination-name collision, not lost
  donor data. Preview now offers a numbered filename (maintainer-approved); Save
  revalidates it and preserves existing photos/sidecars. Race/orphan/symlink guards stay.
- [x] Metadata job outcomes derive saved/skipped/failed photo counts from journaled
  operations, including previous jobs without progress phases. Maintainer validation
  passed for the previous job and new copy-date workflow.
- [x] Separate Metadata inspector tab; compact file/date summary, Edit date shortcut,
  collapsed technical details, gallery-click reset and tab retention on previous/next.
- [x] Recorded-tag disclosure shares primary comparison, differences-only and field filtering.
- [x] Primary metadata Date taken row has an inline Edit date link, including missing/empty
  dates; alternate sources retain Copy Date taken to primary.
- [x] Date-editor usability: calendar day picker preserving recorded time/offset,
  explicit missing-XMP clear guidance, and stable version/action rows across source tabs.
- [x] First date editor: manual Date taken or Copy to primary from another source of
  the photo; complete date/companion handling, explicit clear, previewed target and
  before/after date/path, one Save/refile confirmation and verified failure recovery.
  Other fields remain read-only. Copying never activates the donor source.
  Maintainer validation of editing/saving passed; broad recovery/primary UI is separate.

- [x] One Move-job confirmation for edited-source originals: affected count/list,
  **Include these originals** or **Leave these originals at source**; explain that exact
  original photo bytes are not retained. Bind the displayed selection to the job.
  No per-photo prompts or permanent consent. All entry points use a frozen catalogued
  selection; the engine checks its snapshot under the lock before work, then verifies
  live files before deletion. Include/Leave is carried only along the same Move's
  safety-question chain; Copy instead retains scope without deletion consent.
  Automated API/browser coverage passed; **maintainer UI acceptance passed**
  (2026-10-14, tests/README.md, Move confirmation tests M1–M3), including the
  refresh-button and source/destination Inspector follow-ups.

- [x] Metadata setup/Settings preferences: explicit shared-sidecar choice at first run,
  RAW/non-RAW write defaults with qualified-writer limits, and shared read-priority
  guidance. Existing primary/ownership decisions remain unchanged. Automated validation
  covers persistence, revisions and frozen running-job settings; maintainer acceptance
  passed S1–S3 (tests/README.md). R1–R3 passed.
- [x] Separate informational metadata-reader warnings from import holds: unrecognized
  MakerNotes and other reader warnings preserve their diagnostics without blocking
  unchanged Copy/Move. Reader errors, unstable files and unresolved sidecars remain
  protected. Metadata viewer shows notes with readable explanations and technical detail.
  130 targeted tests and the metadata browser passed; maintainer W1 acceptance passed.
- [x] Clarify date filters versus source blockers: No usable capture date describes
  the filing date; Needs attention explains what prevents organizing. Show repeated
  date errors once, retain affected paths, and recognize usable XMP dates in the
  Inspector. Viewer tests and three browser workflows passed; maintainer D1 acceptance
  passed, including D1.c (XMP date without EXIF Date taken).
- [x] Metadata grouping (S1/S3 feedback): dedicated Metadata setup step and Settings
  tab, shared controls, required association choice and per-tab unsaved indicators.
  Specs and setup browser checks follow the six-step flow. Maintainer acceptance
  Tests 1–4 passed on 2026-10-16.
- [x] Message readability acceptance: project-wide pass covers Settings/setup, gallery,
  metadata, matching, recovery, job submission and logs. Keep specific causes and safety
  consequences, simplify prose and separate multiple issues. Validation and
  maintainer readability review are tracked in tests/README.md; follow `ui-design.md`,
  Writing messages. Targeted automated checks and maintainer Tests 1–4 passed
  on 2026-10-16.
- [ ] Deliberate per-file association/primary-choice controls, separate from viewing and
  copying, with effective-value/refiling previews. Settings defaults do not replace this
  workflow. The source viewer is tracked above, not a duplicate implementation task.
- [x] Prominent active-job Settings notice (`webui-spec.md` §3): shared live feed, stable
  geometry across active/idle/unknown states and tabs, no draft reload or separate poll.
  Generic future-jobs notice/save confirmation remain. Maintainer acceptance S2 passed on 2026-10-15.
- [x] Source metadata attention markers and photo-information explanations: affected
  source-relative sidecar paths, external correction/reindex guidance and job logs.
  Latest-capture holds count as attention, not ready-to-organize photos. No source
  photo is added to Library's Needs review. Broader decisions remain below.
- [ ] Metadata-choice job notices and linked Not organized queue; metadata-difference
  review for edited Library photos and combined metadata/location choices for rejected
  matches. Retained alternatives already have engine preservation notices/history.
- [x] Import-pair retry API/UI: eligible selection counts, recorded issue/file details,
  separate Copy/Move confirmation and original-mode recovery. Snapshot checks bind
  roots, catalog state and pair intent at acceptance; source deletion still requires
  verified pair evidence. Automated API/engine and browser checks cover retry/replay,
  stale/live changes, cancellation, selection and narrow/200% layouts. Maintainer
  visual acceptance passed on 2026-10-15 (tests/README.md, R1–R3). R1 feedback adds shared
  Source/Destination groups in information panes and recorded failed-step/file context;
  older records explicitly identify missing detail rather than guessing a failed file.
  R1 follow-up adds green verified/amber incomplete-or-unconfirmed destination results,
  with text labels and intended-path guidance; source originals remain neutral.
  Photo notices show the latest failure once and link to earlier attempts in Logs;
  confirmations say the retry resumes the original Copy/Move.
- [ ] Deferred broader composition/cross-photo and bulk date controls. Engine support
  exists for qualified common fields; exposing it is outside the first date UI. Preserve
  explicit donor/target roles and never choose primary implicitly (`webui-spec.md` §7.5).
- [ ] Saved orientation controls, separate from temporary viewing rotation: an
  end-of-review decision in comparison/photo panels and Rotate… for a selection,
  with no thumbnail control. Qualified engine Orientation writes are built;
  UI eligibility must respect format/writer limits.

### Deferred work and open discussions

- [ ] **Future discussion: Similar photos and metadata.** Revisit how similarity review
  and metadata workflows should work together, alongside the deferred cross-photo
  metadata controls above. Scope and behavior are undecided; discussion only.

- [ ] Extend date review to malformed/raw EXIF, conflicting capture tags and acknowledgment
  of known-valid dates if needed. Current flags use the recorded gallery date;
  the configurable earliest suspicious year is already built.
- [ ] **Deferred by maintainer:** production metadata-independent image hashing,
  broader fingerprint formats and image-content duplicate consolidation. Retain the
  tested JPEG experiment; complete metadata preservation/editing first.
- [ ] Broader destination inventory/diff/repair (**Check my destination**) remains a
  separate discussion. Ordinary per-operation collision/write verification is required.
- [ ] Revisit sidecars edited externally between Index and Copy/Move. For now the user
  reindexes after an external edit; existing verification/deletion gates still apply.
- [ ] Legacy IPTC precedence/mappings and additional RDF representations require decisions
  and fixtures. Preserving extracted evidence does not imply a qualified read/write mapping.

## Stats

- [x] The thumbnail cache panel in Settings › Performance (Free up previews, Repair grid
  thumbnails, Rebuild all), with API routes for the existing engine jobs, and a Manage
  thumbnails link from Stats (`docs/webui-spec.md` §4.2.1).
- [ ] The Dates chart on its own full-width row, with suspicious years set apart at each
  end, so a few impossible dates cannot squash it (`docs/webui-spec.md` §5.9).

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
- [ ] **Say what it runs on:** a minimum Linux and Docker version in the README, and that
  Mac and Windows are not tested.

- [ ] **One password for the web interface** (`docs/webui-spec.md` §11): generated on first
  start and printed to the container output, changeable in Settings. Until then the README
  tells users to keep the app off the internet.

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

## Navigation refinement

- [x] Rename File issues to Files needing verification and expose the same filter,
  counts and pins in Library and Needs review. Source import failures remain under
  Not organized → Needs attention.

- [x] UI alignment/stability pass: separate filtered-log exports from filters, align
  log input edges and shared inline controls, keep small-image settings and preview
  zoom/rotation controls stationary, and reuse the confirmation action-row spacing.
- [x] Maintainer visual acceptance: alignment/stability Tests 1a–4a and the renamed
  verification filter Test 5a passed.
- [x] Suspend Library-only filters and pin highlights in source views; remember the
  Library choices per tab and restore them on sidebar return, without overriding URLs.
- [x] Maintainer validated revised Test 5b: source navigation and restored filters.
- [ ] Filter-count UX follow-up: distinguish an actual zero from an unavailable count
  or incompatible filter; explain restrictions without misleading zero totals.

- [x] Replace the enlarged-photo layout with the shared two-pane Inspector: large
  preview beside information, Metadata and eligible Similar photos tabs; retain the
  resize divider, navigation and nested dialogs.
- [x] Maintainer validated the expanded two-pane photo view: all posted steps,
  Test 1a through Test 3b, passed (tests/README.md).

- [x] Phase 2 navigation (date scrubber and Source folders): maintainer accepted navigation.
- [x] Shared notification bell with catalog-backed per-job read state; ordinary completed
  jobs move out of banners, while active progress and actionable safety warnings remain.
- [x] Stable selection/action count widths based on catalog capacity, with no selection cap.
- [x] Automated validation: 155 notification/database/API tests; full browser workflow,
  notification persistence/retry/geometry, safety decisions, job-refresh requests and
  both Reject workflows passed. Shared light/dark and narrow-window screenshots inspected;
  spec/schema/API checks passed. No claim of full UI acceptance from automated checks.
- [x] Maintainer validated the bell options, new-job updates and stationary selection actions.
- [x] Maintainer validated the Details disclosure replacing notification hovers that covered links.
- [x] Final local checks: navigation, preview refresh, mixed/all-failed transfers and
  stalled-job cancellation passed; oversized notification IDs are rejected before SQLite,
  and old job-photo links follow subsequent Reject/Return operations. Contract checks passed.
- [x] Subtle date-scrubber ticks between year labels, preserving year positions and
  click targets; spacing follows photo counts, not equal time intervals.
- [x] Maintainer validated date-scrubber ticks.
- [x] Gallery-card clicks reset the Inspector to Photo information, including in Has
  similar photos. Explicit match links and Inspector previous/next keep their intended tab.
  Generated filter-pin and similarity browser suites passed, including tab restoration.
- [x] Maintainer validated the Inspector tab reset when clicking gallery photos.
- [x] Inspector tabs use gallery status while details load, preventing the single-tab
  flash during gallery clicks and Previous/Next navigation. Held-response browser
  checks verify both labels, selection and widths before details arrive; the full
  similarity browser flow passes. Maintainer confirmed the tabs look good.
- [x] Filter pins: click to replace unpinned Look into filters, pin to retain; pins survive
  refresh in the browser. Clear all filters removes pins. Small images/Review later stay
  exclusive, with an Unpin explanation. Existing gallery queries supply next-click counts.
- [x] Final automated validation: 116 API/review tests, focused pin browser flow, full
  browser/shared UI and review workflows, spec/API/schema checks and light/dark/narrow
  screenshot review passed. Clear action geometry and source-folder reset are covered.
- [x] Review later and its count are available in Library and Needs review; the same
  pin, replacement and reminder-exclusion rules apply in both. Validated with 20
  API/review tests and the generated-photo browser flow (zero/nonzero counts, filtering,
  navigation, refresh, pins and desktop reflow).
- [x] Maintainer validated Review later in Library and Needs review.
- [x] Maintainer validated filter pins.
- [x] Move Clear all filters beside Look into, reserve its space, and clear search,
  folder/date/type restrictions and saved pins while retaining place and selection.
- [ ] Maintainer visual check of the final Clear all filters placement.
- [x] Consolidate page-frame/date-scrubber/refinement into the gallery UX PR. Metadata
  is merged; combined schema 28 preserves metadata tables and notification receipts.
- [x] Validate the combined metadata/navigation integration locally: 195 database/API
  tests, six browser workflows, frontend build and spec/API/schema checks passed.
  File issues uses the sidebar and its pin rules; older schema-26/27 catalogs are
  refused without modification.
- [x] Combined GitHub checks passed (68 steps); PR #107 merged after #105. Superseded
  PRs #104/#106 closed. Main includes the full navigation and metadata engine stack.


- [x] Validation follow-up: stable folder/date/type filter summaries; persistent disabled
  folder actions when a single-folder operation is unavailable; inline Copy date to primary;
  Edit metadata date wording; absent-primary-date links to alternatives; shared completion
  footer; suppress duplicated lineage selection links while retaining unmatched jobs.
  Focused spot-checks passed: Tests 3b, 4f, 5a, 5c–e in tests/README.md.
- [ ] Post-validation discussion: whether/how to expose copying all metadata or a broader
  field selection. Date-only copying remains the current UI scope; no implementation yet.

- [ ] Future discussion (accepted Test 3b): could source-folder handling happen behind
  the scenes? Clarify the desired behavior before changing selection or action rules.
- [ ] Optional wording discussion (accepted Test 4f): Open in the log already opens
  the photo-filtered operations history across jobs, including linked file identities
  and exact duplicates. Consider a clearer label such as View all photo logs; no new
  filtering feature is needed and no wording change is approved yet.
