# Changelog

What changed in each version, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/): 1.0.0 will be the first release; until then
the middle number goes up with each feature. Before 1.0.0 a new catalog format is
**refused, not migrated**: a version that changes it means a fresh catalog (see
[TODO.md](TODO.md#before-the-first-release)).

## [Unreleased]

- Thumbnail cleanup counts only bytes actually removed and reports engine-launch failures
  with a specific error and next step.

- Settings › Performance shows the thumbnail cache by kind and manages it: **Free up
  previews** removes detail previews, which are recreated when a photo is opened again;
  **Repair grid thumbnails** and **Rebuild all grid thumbnails** run as jobs, followed in
  the panel and the job bar. Stats' Catalog health links to it with **Manage thumbnails**.
- A thumbnail rebuild no longer stops partway when the catalog holds files the Index
  could not read; those have no content to make a thumbnail from and are left out.
- Settings shows its save result beside **Save settings**, so saving no longer moves the
  buttons.

- Enlarged photos reuse the two-pane Inspector, with a large preview beside the
  information, Metadata and Similar photos tabs, plus resizing and photo navigation.

- Give metadata its own Settings tab and setup step, keeping required choices and
  saved preferences. Simplify explanations across gallery, metadata, similarity,
  recovery and job screens, with clearer paragraph/list formatting and shared dialog
  spacing. Keep failure evidence and safety consequences visible.

- Retry incomplete photo/XMP imports from photo information, Logs or a selection.
  Confirmation preserves the original Copy/Move mode; changed catalog state requires
  a fresh preview, and files are verified before reuse or source removal. Failure details
  distinguish source and destination paths and show recorded delivery status per file.
- Setup requires a shared-XMP association choice. Settings exposes association and
  write defaults, explains metadata priority, and shows that processing changes apply
  to future jobs while the current job keeps its accepted settings.
- Metadata-reader warnings, including unrecognized MakerNotes, remain informational
  and no longer block unchanged Copy/Move. Reader errors and unresolved sidecars still
  require attention. Reindex refreshes earlier warning-only holds.
- Rename No capture date to No usable capture date and explain its distinction from
  source files needing attention. Consolidate repeated date errors and recognize usable
  XMP dates when EXIF has no Date taken.

- Source views suspend Library-only filters and their pin highlights. Returning to
  Library or Needs review restores the tab's previous choices, including unpinned
  filters; explicit links remain exact and Clear all filters forgets the saved choices.

- Rename File issues to Files needing verification and expose the same filter,
  counts and pins in Library and Needs review. Source import failures remain under
  Not organized → Needs attention.

- Log exports sit beside the page heading, separate from aligned search/date filters.
  Small-image settings and preview zoom/rotation no longer move the controls below
  them. Comparison headings align at enlarged text sizes; shared inline controls and
  the address-removal confirmation reuse consistent spacing.

- Filter summaries no longer shift their trees; folder Copy/Move controls explain when
  unavailable. Metadata date copying sits beside the donor date; missing primary dates
  link to recorded alternatives. Completion dialogs reuse the shared action footer,
  and lineage avoids repeating jobs already represented by file steps.

- Metadata editing is a text link beside Date taken on the primary source tab, including
  empty or missing dates, so the action is found where the date is read.

- Date-change previews offer a numbered filename for occupied photo names, keeping
  existing files untouched and requiring a new preview if that target changes.
  Metadata job summaries count saved photos, skips and failures from the journal.
- Explicit date clearing blanks both date inputs and restores the draft if unchecked.
  Empty source folders keep normal tree alignment; expanded comparison tags no longer
  push the candidate strip down in side-by-side layouts.

- No capture date hides the year panel. Inspect photo distinguishes immediate inspection
  from Review later. Comparison refresh aligns with the threshold control; Keep
  sits beneath the reference preview instead of beside the filter.

- Unpinning a filter now turns it off and refreshes the gallery and counts while
  retaining other active filters. Unfiltered galleries use the sidebar total; filtered
  results show one matching/whole-place count, with set and focused-view totals retained.

- The Inspector separates Metadata from Photo information, folds technical details,
  and keeps a filing-date summary with an editing shortcut. Gallery clicks return to
  Photo information; previous/next retains the active tab, and explicit tab links restore.

- Expanded recorded source tags now compare against primary, including differences-only
  and field filtering, with explicit empty and missing values.

- Date editing adds a calendar picker that preserves recorded time and timezone,
  and explains why a missing XMP date can still be explicitly cleared. Metadata tabs
  reserve sidecar-version and copy-date controls so switching sources stays stable.

- Library photos now offer Edit Date taken and Copy Date taken to primary from their
  recorded metadata sources. A draft/preview shows the write target, date and resulting
  location; one confirmation saves and refiles through the verified engine job.
  XMP clears are explicit, untouched metadata/source files stay unchanged, and unsupported
  writer values refuse without changing primary. Broader metadata editing is deferred.

- Inspector refreshes keep one instance of each section and photo action row,
  preventing duplicate controls after review or job updates.

- Not organized owns Source folders and Needs attention navigation, separating source
  import problems from Library review. Needs attention shows a count on every screen.
  Folder browsing lives only in Source folders; leaving it clears that restriction.
  Gallery Filters retains dates and file types.

- Not organized marks source metadata issues as Needs attention and explains the
  affected sidecar path and external correction/reindex steps in Photo information.
  Index summary excludes recorded metadata holds from photos ready to organize.

- Photo information now separates XMP Sidecar, Embedded XMP and EXIF into read-only
  tabs, identifies the applied Primary source, and compares alternative values with
  it. Empty values remain distinct from missing fields; retained sidecar versions
  and captured source tags remain inspectable. Date controls are limited to the workflow above.
- Metadata comparison treats matching plain text and a single XMP default-language
  entry as equal. Unreadable sidecars retain their explanations even without an
  archived version, and malformed retained sidecars no longer crash the source tab.

- Look into filters can be pinned while browsing other filters. Clear all filters now
  sits beside Look into and clears search and folder/date/type restrictions as well.
- Decorative date-scrubber ticks fill large gaps without changing year positions.

- Inspector tab labels and widths remain stable while the next photo’s details load.

- Clicking a gallery photo opens Photo information, even if the previous photo
  showed Similar photos.

- Review later is available with its count in both Library and Needs review, using
  the same pin rules and retaining the filter when switching between these places.

### Navigation notifications

- Finished jobs appear in a shared notification bell with persistent per-job read status,
  scrollable results and links to photos, failures and Logs. Active progress and safety
  decisions remain visible. Selection/action counts reserve space to prevent button shifts.
- Catalog schema 28 combines notification receipts and metadata provenance; older development catalogs require a
  fresh catalog. Metadata editing UI is not part of this navigation change.

- Match the engine’s edited-source consent field when checking web job identity,
  preventing accepted Index/Copy/Move requests from falsely reporting a conflict.

- Qualified embedded JPEG edits now publish through recorded recovery steps, update
  retained content/cache identity and metadata history, and refile changed dates.
  Reindex preserves edited Library state; exact-result duplicates are reported without
  automatic deletion. Sources stay unless a later Move explicitly confirms edited-source cleanup.

- Full Index recognizes externally removed Copied originals after verifying their Library copies, updates Move eligibility, and exposes unverified copies through File issues.

- Show uncertain file outcomes in photo information, Logs and the Library review inbox; verify recorded files with Check it now without moving or deleting photos.

### Added
- One-job consent for Move after embedded edits, with a read-only source-cleanup preview,
  verified original/retained hashes and image history, exact sidecar archives, pre-action
  backup, durable deletion evidence and explicit retry. Unconfirmed originals remain
  while other files proceed. The future web confirmation is documented, not built.
- Qualify explicit common-field removal in JPEG EXIF, including linked date/GPS tags,
  exact preservation of existing EXIF header values, verified absence and date refiling.
  The metadata CLI accepts independent `remove_fields`; no primary switches silently.
  Document and enforce the agreed JPEG/XMP release boundaries for unsupported formats
  and EXIF value representations.
- Reapply supported source/pre-edit metadata as a new verified engine operation, with
  historical provenance, XMP field removals that preserve absence, and verified image
  history across embedded edits. Unsupported representations refuse without partial
  changes; exact photo restoration and metadata UI remain outside this workflow.
- Compose supported metadata fields from a retained base version with explicit donor or
  typed overrides, complete value/provenance previews and verified saves to the established
  primary. Missing fields stay unchanged; explicit blanks remain empty. Engine-only.
- Apply confirmed incoming XMP and Return choices through the metadata engine CLI, with
  effective-value/location previews, verified pre-action backups, exact alternative
  retention and explicit interruption recovery. Metadata and Rejects location remain
  independent choices. Copy/Move separately verifies any later source cleanup.
- Multiple-sidecar first imports: full-filename or explicit primary selection, exact
  retention of every alternative, distinct arrival history for identical packets, and
  verified shared-source cleanup. Partial Move jobs retain recorded ownership; interrupted
  alternative cleanup requires explicit retry. Unresolved metadata choices remain at source.
- Photo-only imports now file using captured embedded-XMP/EXIF priority after verified
  delivery. The metadata CLI can switch an existing Library photo to embedded EXIF or
  embedded XMP without rewriting either source, preserving inactive sidecars and recording
  any date move with recovery history. Automatic read priority does not change write defaults.
- Verified embedded JPEG working copies with unchanged originals, metadata read-back,
  image/ICC preservation checks, bounded tools and staging-failure cleanup. Embedded
  XMP supports common fields; EXIF refuses values it cannot represent. The journaled
  publisher now connects Library replacement and content/cache updates; additional formats
  remain unqualified.
- Verified XMP editing through a bounded JSON engine CLI: explicit common-field changes,
  field copying with donor provenance, deliberate retained-XMP activation, batch backups,
  date refiling and interruption recovery. XMP sidecar saves leave photo bytes unchanged;
  web editing controls remain unfinished.
- Common-field XMP plans and preservation-aware packet construction, with linked GPS,
  multilingual text, exact decimal ratings and independent ExifTool checks. Verified XMP
  execution is connected; broader embedded writers remain pending; no UI changes.
- Incoming duplicate XMP preservation, deliberate version/location choices, stale-target
  protection and verified source cleanup with retry. Existing metadata and Rejects
  locations are preserved by default; confirmed activation/Return now uses the metadata CLI. Schema 26 requires
  a fresh development catalog and records metadata-observation progress.
- Resolved single-sidecar Copy/Move imports now file by the selected metadata date,
  establish primary/ownership only after pair verification, include XMP in space checks,
  and resume interrupted transfers through explicit same-mode CLI jobs. Empty/partial
  dates use the original Undated year; forced reindex preserves delivered names/dates.
  Broader import activation, non-JPEG embedded editing and web retry remain pending.
- Sidecar-aware Rename, Reject and Return for recorded photo/XMP pairs: verify both
  new files before retiring either old name, preserve full-filename sidecars, recover
  interrupted cleanup, and reuse the recorded target on explicit retry. Check it now
  verifies the whole pair without moving or removing files. Broader incoming metadata
  choices remain guarded; resolved single-sidecar imports are now connected.
- Internal verified photo/XMP pair transfer with full-filename sidecars, shared-owner
  cleanup checks, durable recovery evidence and explicit retry. Generated failure/crash
  tests cover the deletion gates. Normal single-sidecar jobs and destination pair relocation
  are connected; unresolved/duplicate metadata cases remain held.
- Read-only Date taken/Orientation edit plans with field-scoped changes, linked EXIF date
  components, minimal first-XMP construction and catalog-bound filing previews. Verified
  qualified JPEG publication and XMP history/recovery are connected; additional formats and editing UI remain pending.
- Saved metadata ownership and primary-source decisions with version-bound previews,
  stale-confirmation refusal, request replay safety and backup coverage (schema 25).
  XMP preferences are frozen per job; saved choices survive re-index and default changes.
  Decision UI/API and broader activation remain pending; resolved single-sidecar jobs are connected.
- Hold unresolved photo/XMP pairs during Copy/Move and duplicate cleanup; other
  photos proceed and held pairs receive a specific explanation.
- Read-only Index metadata observations: qualified embedded EXIF/XMP and retained
  sidecars, proposed source priority, unchanged-photo reuse and sidecar-only re-index
  detection. Index preserves established imports; activation happens after verified
  pair delivery. Immutable observations and decisions require schema 26 (fresh catalog).
- Internal EXIF/XMP comparison adapter for qualified capture dates, camera fields and
  orientation, retaining original evidence and empty/partial values. Generated JPEG/TIFF
  compatibility tests pass; the adapter itself does not edit or transfer files.
- An isolated generated-JPEG content-hash experiment with metadata-invariance tests
  and measured timings; it does not change import or duplicate cleanup.
- Supported XMP date, orientation and rating validation, with independent generated
  ExifTool compatibility checks. Invalid values remain attention-only; originals are preserved.
- Compressed original XMP storage with immutable arrivals and verified catalog backups.
  Index retention and resolved single-sidecar transfers are connected.
- A generated XMP compression benchmark and oversized-sidecar refusal before content reads.
- Internal bounded XMP reader and photo-association planner, with generated parsing,
  filesystem-safety and ownership tests. Index captures evidence; resolved imports
  establish ownership after verified delivery.
- Internal metadata provenance resolver preserving separate embedded/XMP snapshots,
  explicit empty values and field origins. Resolved single-sidecar import is connected;
  source tabs and broader import decisions remain planned in the UI handoff.
- Needs review for small images and review-later notes, with destination-only actions,
  first-run preferences, suspicious-date limits and shared appearance controls.
- Allowed-address management in setup and Settings, independent of catalog replacement,
  with protected deployment recovery and confirmation before removing the current address.
- A no-progress reminder with Keep waiting and explicit cancellation of photo workers.

### Changed
- Look into filters replace unpinned filters when clicked; separate pin controls retain
  filters across choices and browser refreshes. Clear filters removes pins too, and
  filter counts reflect the results of the next choice. Small images and Review later
  remain exclusive with an explicit unpin explanation.
- Subtle guide ticks fill the date scrubber between year labels without changing date
  positions or navigation.
- A date scrubber down the gallery's right edge: the years, sized by their photos; point
  for the month, click or drag to go there.
- **Source folders**, under Not organized: the source's folder tree beside the photos,
  showing what is waiting or everything still in the source, with Copy and Move for the
  folder chosen, so the originals of copied photos can be moved off folder by folder.
- A new page frame, after Immich's: a sidebar on every page with the places, each
  counting everything it holds; **Look into**, which now holds the filters that were a
  row of chips (Has similar photos, Suspicious dates, No capture date, Small images,
  Review later); Logs, Stats and the version. The search, Jobs, a Dark mode switch and
  Settings are in the top bar. Types, Folders and Dates moved from the left panel into a
  **Filters** button beside Sort, each with its Show all at the top. Ticking photos turns
  the top bar into the selection bar: the count, Show only selected and the actions
  together, then the search. In a narrow window the sidebar opens from a ☰ Menu button.
- Consistent Library/review filters, stable navigation and filter guidance, compact
  completed-job/source summaries, and clear source-versus-Library matching scope.
- Identical related sets appear once. Photo Review links to the complete match browser without a partial thumbnail list,
  failed-file details appear in the Inspector, and grouping uses shared checkbox alignment.
- Page queries load once after the initial job state and refresh when jobs finish.

### Fixed
- Finishing a filtered review queue returns to the gallery with a completion message;
  previews that no longer match the gallery close instead of showing resolved photos.
- Unsafe cross-origin requests/framing, untrusted request hosts, symlink paths and
  temporary-file writes; new catalog and backup files use owner-only permissions.
- Mixed Library/Rejects selection refusal at engine acceptance, acknowledged banner
  dismissal, generated-fixture identity guards and stale documentation/test contracts.


## [0.16.1] - 2026-10-06

### Changed
- Internal reorganisation, no change on screen: the API's catalog reads split by area
  (`gallery`, `outcomes`, `oplog`, `catalog_backups`, `lineage`, `stats`); the Library and
  first-run screens out of `App.tsx` (`LibraryPage.tsx`, `FirstRun.tsx`); 28 restating
  rules at the end of `styles.css` folded into the rules they restate (every element's
  computed style compared before and after); browser tests in `tests/browser/`, the
  library builders in `tools/`.

## [0.16.0] - 2026-10-06

### Added
- Apply confirmed incoming XMP and Return choices through the metadata engine CLI, with
  effective-value/location previews, verified pre-action backups, exact alternative
  retention and explicit interruption recovery. Metadata and Rejects location remain
  independent choices. Copy/Move separately verifies any later source cleanup.
- The Dates panel has an order button beside its heading (**↓ Newest**, **↑ Oldest**, or
  **↕ Date** when sorted otherwise) that sets the gallery's date order; the Sort menu
  follows it, and it follows the Sort menu.

## [0.15.1] - 2026-10-06

### Changed
- The engine is a package, `engine/`, run as `python3 -m engine` (was `ns-engine.py`), and
  its single 6,000-line file is split by area: scanning, Copy and Move, Rename/Reject/Return,
  reconciliation, the copy-verify-delete steps, catalog writes, file reading, thumbnails,
  maintenance jobs, backups and the command line. `ns_db.py` and the `ns_similarity`
  modules moved into it. No behaviour changed.

### Fixed
- After a catalog was replaced, finished-job banners vanished as each job ended: the
  browser remembered a dismissal from the old catalog's higher job numbers. The catalog's
  record of what was dismissed now wins.
- A job's photos and the finished banner could describe two different jobs (a Reject's
  photos, then a Return of them). The banner now names its job ("Return to library #8
  finished"), and a job started from a job's photos takes the view with it when it ends.

## [0.15.0] - 2026-10-06

### Changed
- Actions on ticked photos are in a selection bar at the top, which shows only what applies
  to them, each with its count: Copy, Move, Reject, Return to library. The **Actions** menu
  is now **Jobs**, with the jobs for the whole library (Index; Copy and Move of one
  folder or all), on the Library page only.
- A selection holds library photos or photos in Rejects, never both: the other place's tick
  boxes are disabled while anything is selected, and Select all says what it left out.
  A selection in Rejects offers Return to library first; its Move warns that the copies in
  Rejects become the only ones.
- After a job you stay where you were, and nothing stays selected. The finished banner's
  **Show these photos** opens the job's photos (from any page), where search, dates,
  types and folders narrow them; **Back to results** restores your filters.
- A job that ran to its end is never called failed: with some files failed it "finished
  with failures" (an Index that found most files unchanged included), with every file
  failed it "finished, nothing succeeded", and only a job an error ended "stopped by an
  error". Each job in Logs offers **Show these photos in the library**.
- A review holds only the photos its action takes, and counts the rest: "3 selected
  photos are left out: Reject takes only photos already organized."

### Added
- Apply confirmed incoming XMP and Return choices through the metadata engine CLI, with
  effective-value/location previews, verified pre-action backups, exact alternative
  retention and explicit interruption recovery. Metadata and Rejects location remain
  independent choices. Copy/Move separately verifies any later source cleanup.
- README: a security section (there is no sign-in yet), a recovery guide
  ([docs/recovery.md](docs/recovery.md)) and the GPL-3.0 license.
- A user guide with screenshots ([docs/user-guide.md](docs/user-guide.md)), and screenshots
  in the README.

## [0.14.2] - 2026-10-05

### Fixed
- Actions offers Reject or Return to library by what is selected, not by the view: the
  photos a Reject just moved can be returned from the job's own view, and a mixed
  selection offers both, each with its own count.

## [0.14.1] - 2026-10-05

### Fixed
- Reject, Return to library and Rename: a disk error after a file has moved no longer
  records "nothing was changed"; the next job verifies both locations and settles it.
  Recovery checks a file's type and checksum before believing it moved.
- Selections: a restarting server no longer deletes a selection an engine has not read
  yet; a failed selection write cleans up only its own file, so the same request can be
  retried; failures to start come back as clear errors.
- The photo panel's position lookup no longer stops at 1,000 selected photos.

## [0.14.0] - 2026-10-04

### Changed
- No limit on how many photos a selection holds (it was 1,000). Selections reach the engine
  in a validated file, and each job records the photos it was given; a photo's lineage
  lists the jobs it was selected for. **New catalog format.**

## [0.13.0] - 2026-10-02

### Changed
- Settings in four tabs (Appearance, Files, Backups, Performance), with one Save; the first
  start walks through the same four groups as steps, explained for a first-time user.

## [0.12.0] - 2026-10-02

### Added
- Apply confirmed incoming XMP and Return choices through the metadata engine CLI, with
  effective-value/location previews, verified pre-action backups, exact alternative
  retention and explicit interruption recovery. Metadata and Rejects location remain
  independent choices. Copy/Move separately verifies any later source cleanup.
- Rejects on Stats (what it holds, what has been emptied), and a reminder on every page
  once Rejects passes a size or age limit set in Settings. **New catalog format.**

### Changed
- The Reject question names the photo and says it can be brought back until Rejects is
  emptied.

## [0.11.0] - 2026-10-02

### Removed
- The pair judgments in similarity review; Reject and Keep replace them. **New catalog
  format.**

## [0.10.0] - 2026-10-02

### Added
- Apply confirmed incoming XMP and Return choices through the metadata engine CLI, with
  effective-value/location previews, verified pre-action backups, exact alternative
  retention and explicit interruption recovery. Metadata and Rejects location remain
  independent choices. Copy/Move separately verifies any later source cleanup.
- Reject from Similar photos and from the side-by-side comparison; **Keep this one, reject
  the rest**.
- A clear button in every search box.

## [0.9.0] - 2026-10-01

### Added
- Apply confirmed incoming XMP and Return choices through the metadata engine CLI, with
  effective-value/location previews, verified pre-action backups, exact alternative
  retention and explicit interruption recovery. Metadata and Rejects location remain
  independent choices. Copy/Move separately verifies any later source cleanup.
- Reject and Return to library: turned-down photos move to `rejects/`, never deleted, and
  identical copies stay out of the library. **New catalog format.**

### Changed
- Faster gallery and similarity queries for large libraries.

## [0.8.0] - 2026-10-01

### Changed
- Organized photos go to `library/` inside the destination, leaving room for `rejects/`
  beside it. **New destination layout.**
