# Changelog

What changed in each version, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/): 1.0.0 will be the first release; until then
the middle number goes up with each feature. Before 1.0.0 a new catalog format is
**refused, not migrated**: a version that changes it means a fresh catalog (see
[TODO.md](TODO.md#before-the-first-release)).

## [Unreleased]

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
