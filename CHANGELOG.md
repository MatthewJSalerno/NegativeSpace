# Changelog

What changed in each version, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/): 1.0.0 will be the first release; until then
the middle number goes up with each feature. Before 1.0.0 a new catalog format is
**refused, not migrated**: a version that changes it means a fresh catalog (see
[TODO.md](TODO.md#before-the-first-release)).

## [Unreleased]

## [0.15.0] - 2026-10-05

### Changed
- Actions on ticked photos are in a selection bar at the top, which shows only what applies
  to them, each with its count: Copy, Move, Reject, Return to library. The **Actions** menu
  is now **Organize**, with the jobs for the whole library (Index; Copy and Move of one
  folder or all), on the Library page only.

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
