# Changelog

What changed in each version, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/): 1.0.0 will be the first release; until then
the middle number goes up with each feature. Before 1.0.0 a new catalog format is
**refused, not migrated**: a version that changes it means a fresh catalog (see
[TODO.md](TODO.md#before-the-first-release)).

## [Unreleased]

### Added
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
- Reject from Similar photos and from the side-by-side comparison; **Keep this one, reject
  the rest**.
- A clear button in every search box.

## [0.9.0] - 2026-10-01

### Added
- Reject and Return to library: turned-down photos move to `rejects/`, never deleted, and
  identical copies stay out of the library. **New catalog format.**

### Changed
- Faster gallery and similarity queries for large libraries.

## [0.8.0] - 2026-10-01

### Changed
- Organized photos go to `library/` inside the destination, leaving room for `rejects/`
  beside it. **New destination layout.**
