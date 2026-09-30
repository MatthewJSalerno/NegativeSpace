# Tests

Everything here is for developing NegativeSpace; running the engine needs none of it.
CI runs all of it on every pull request and every push to `main`
(`.github/workflows/engine-tests.yml`).

Build the image first — the Python suites run inside it, because they need ExifTool,
Pillow, imagehash and rawpy:

```bash
docker build -f docker/app.Dockerfile -t negativespace .
```

## Engine smoke suite — `engine_smoke_test.py`

Drives the real engine as a subprocess against real image files rather than importing
it and stubbing things out; a few content-safety tests import it in-process to inject a
fault between two steps of one function. Mount your checkout over `/app` so it tests the
code you have rather than the code baked into the image:

```bash
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app -w /app \
  negativespace python3 tests/engine_smoke_test.py
```

A green run reports `N passed, 0 failed, 2 skipped`. The two skips are the RAW tests
(decoding and RAW thumbnails): LibRaw rejects fabricated files, so they run only when
`NS_TEST_RAW_DIR` points at a folder of genuine camera output, mounted into the
container:

```bash
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -e NS_TEST_RAW_DIR=/raw \
  -v /path/to/raw/files:/raw:ro -v "$PWD":/app -w /app \
  negativespace python3 tests/engine_smoke_test.py
```

Flags: `--filter NAME` runs tests whose name contains NAME (a filter matching nothing
is an error), `--keep` leaves the workspace on disk, `-v` shows engine output, and
`--engine PATH` runs the suite against another copy of `ns-engine.py` — the way to
prove a test catches the defect it guards against. The module docstring is the
authoritative reference.

The suite does **not** run under pytest: pytest mis-collects its `@test` registration
decorator and errors without running anything.

The `verified_recovery` tests interrupt real Moves around source deletion and check
fresh delivery, existing-copy reuse and duplicate cleanup. They verify destination
content before success, reject unreadable/non-file/changed candidates, check both
operations' destination participation, and inject a lineage-write failure to prove
the recovery transaction rolls back. Run this subset with `--filter verified_recovery`.

## Catalog contract suite — `database_test.py`

The catalog's contracts — schema initialization, settings revisions, concurrent
writers, transaction rollback, lineage invariants, backups — against synthetic
catalogs, with no image files:

```bash
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app -w /app \
  negativespace python3 -m unittest discover -s tests -p database_test.py
```

## Web API suite — `webui_api_test.py`

The FastAPI layer (`webui/`) through FastAPI's test client, against a real catalog.
Jobs start the real `ns-engine.py` as a child process, as in production, so the
request-to-run handshake, the engine lock, cancellation and the derived outcome are
tested together:

```bash
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app -w /app \
  negativespace python3 -m unittest discover -s tests -p webui_api_test.py
```

To prove a test catches a defect in the API, copy the checkout, change the copy, and
mount the copy as `/app`: the API is imported in-process, so `--engine` cannot reach it.

## Web interface in a browser — `webui_browser_test.sh`

`tools/validate-similarity.py` creates deterministic original/resize/recompression/
brightness/crop image pairs, unrelated scenes and a flat-color collision. Run it
inside the app image, with a writable output mount:

```bash
docker run --rm --user "$(id -u):$(id -g)" --entrypoint python3 \
  -v "$PWD":/app:ro -v /tmp:/output -w /app negativespace \
  tools/validate-similarity.py --output /output/ns-similarity-validation --benchmark-photos 10000
```

The output directory must be new. Open its `index.html` for a threshold slider,
side-by-side known pairs and an errors-only filter; `report.json` contains metrics.
The synthetic catalog benchmark measures initial/unchanged/incremental comparisons,
queue timings at three thresholds, logical database bytes and whole-process peak
RSS (KiB on Linux). Its clustered hashes and geometric fixtures are reproducible
diagnostics, not real-library quality or capacity claims. No real library is read.
The library may exceed 200,000 photos: use `--benchmark-photos 250000` for capacity
validation with headroom (the tool accepts up to 500,000). It measures both queue
and reference queries, seven times per threshold. Fixture creation and photo decode
are outside the comparison timings; whole-process peak RSS includes fixture setup.
Results describe the local temporary Docker catalog and its caches, not network
storage performance. Hash distribution and match density also affect scale.
Actual gallery/Inspector query timings and human judgments provide the next validation
step on a representative destination catalog after Index and Copy or Move. An
Index-only catalog has no reviewable destination photos. Side-by-side feedback
never modifies photos. Synthetic benchmarks create recorded destination copies
and assert that all requested photos are included in query measurements.

`DRIVER=similar_browser_drive.py sh tests/webui_browser_test.sh` checks the empty review after Index, then Copies
the isolated generated fixtures and checks cumulative Inspector counts, inline match
pagination, gallery selection preservation, side-by-side review and saved judgments,
reload/Back state, request failure retries, legacy bookmarks and narrow Inspector dialogs.
It also checks independent rotation and displayed dimensions, unchanged recorded
dimensions, reference promotion, file-format fallbacks, exact-byte differences,
missing dimensions, and sticky column headings in desktop and narrow layouts.

For manual validation after Copy, open a destination photo in the gallery and choose
**Similar photos** in the Inspector. Click a 75/80/85/90/95/100% count to browse
its matches in the thumbnail grid. Use
**Has similar photos** to narrow the gallery; the count buttons narrow only the
Inspector results. The gallery's separate **Matches at or above** selector changes
its membership, and **Most matches first** sorts counts highest first. Reload and
return from Logs to confirm the reference and threshold
remain. No new Index or Copy is needed after explicitly preparing a schema-16 catalog.
The database suite verifies the hash index against brute force and interrupted
comparison recovery; the API suite checks reference-only matches, hash changes,
availability, exact copies, thresholds and pagination.

`python3 -m unittest discover -s tests -p similarity_recovery_test.py` checks
cancellation during decoding, concurrent byte changes, distinct read/decode failures,
destination boundaries, unsupported formats and source-only exclusion. The API suite
runs real Index/Copy/recovery, repairs with the source gone, verifies unchanged bytes,
checks busy/idempotent requests, and resumes comparisons without photo reads.

`SIMILARITY_RECOVERY_FIXTURE=1 DRIVER=similarity_recovery_browser_drive.py sh tests/webui_browser_test.sh`
opts into mounting **only the harness's disposable generated catalog** to arrange
missing/unsupported hashes. It exercises warning-to-recovery navigation, disabled
busy actions, real repair and comparison-only jobs, refreshed results, failed-load
retry, unsupported-format limitations and narrow reflow. It never accesses a real
library. `similar_browser_drive.py` additionally checks comparison refresh with
rotation/zoom/position, filtered review/tab restoration, and malformed bookmarks.

Manual checks after Index/Copy: use Resolve matching issues for any affected photos;
review the reason, run the appropriate action, and check the remaining count. In
comparison, rotate or zoom, choose a review filter, and refresh: the same comparison
should reopen. Back to gallery clears it. EXIF edits, saved orientation writes and
deletion belong to a separate workstream and do not block these checks.

`DRIVER=gallery_position_browser_drive.py sh tests/webui_browser_test.sh` checks
Logs photo positioning, offscreen Inspector navigation, retained filters, explicit
hidden-photo display, retry, ordinary gallery clicks, manual scrolling and History
action alignment. Its fixtures are generated photos in isolated containers.

`DRIVER=appearance_browser_drive.py SHOTS=/tmp/ns-shots sh tests/webui_browser_test.sh`
checks both neutral palettes in light/dark modes, text and input contrast, local
preference persistence, cross-tab updates, blocked storage, and narrow controls.
It also checks that Appearance is first in Settings and that dialog scroll cues
appear and disappear at the corresponding scroll boundaries.
Create the screenshot directory before mounting it. These screenshots use only
generated test photos. The normal browser driver also captures each main screen.

Both containers as `docker/compose.yml` arranges them (`app`, and `web` proxying `/api`
to it), driven by headless Chromium (Playwright) against generated photos. It covers first run, settings, Scan, the gallery,
the Inspector, selection, Copy, search and the phone-width layout, and fails on any
browser console error. It starts a server container and a Playwright container, so it
runs on the host:

```bash
docker build -f docker/app.Dockerfile -t negativespace . && docker build -f docker/web.Dockerfile -t negativespace-web .
sh tests/webui_browser_test.sh
```

`IMAGE=<tag>` and `WEB_IMAGE=<tag>` test other builds, and `SHOTS=<folder>` keeps
screenshots of the main screens for review by eye. The photos are generated, so the
screenshots show nothing from a real library. To prove it catches a frontend defect, change a copy
of the checkout, build that copy under another tag, and run with `IMAGE` set to it.

## Shell tests

These run on the host, not in the container, because the thing under test is a shell
script:

```bash
sh tests/sampler_test.sh                                   # the sampler never writes to the library
docker build -f docker/app.Dockerfile -t negativespace . && sh tests/entrypoint_test.sh   # the entrypoint's ownership handling
sh tests/shutdown_test.sh      # docker stop with a browser tab open: clean, and the app's shutdown runs
```

## Validating against real files — `make_sample_tree.sh`

Synthetic fixtures cannot stand in for a real library, but most checks do not need the
whole of one either. The sampler builds a small **hard-linked** sample: no extra disk
space, the originals' real bytes, mtime and EXIF, and one deliberate duplicate so
duplicate cleanup is exercised. Deleting from the sample never touches the library, so
it is safe to point `--move` at.

```bash
sh tests/make_sample_tree.sh [--no-raw | --all-types] <library> <sample> [every-Nth, default 25]
```

`--all-types` samples every file, not only photos — what the Index's file-type
accounting needs, since a photos-only sample excludes nothing. A sampled file shows a
link count of 2 (the duplicate 3); `du` reports the full size regardless, so link count
is the test that it is really linked.

## A library of scenarios — `make_scenarios.py`

For showing the app to someone, or checking it against every awkward case, without
sharing a real library. `build` hard-links every photo from a seed folder into
`OUT/library` and adds scenarios beside them: exact duplicates, the same photo without
its EXIF, resized and format-converted copies, dates the engine must file (none, with a
time-zone offset, conflicting, invalid, future, 1958, and one picture dated both 2024 and
1969), names that collide at the
destination or are awkward, every EXIF orientation, and edge files (empty, truncated,
not an image, a sidecar, a symlink, an unreadable file, a deep folder). `change` then
applies one round of every kind of change (edited in place, touched, renamed, moved,
deleted, replaced, new duplicates, a new date taken, and with `--dest` a destination
copy deleted, altered and a stranger added), which is what gives a photo's lineage
something to show. `OUT/manifest.json` lists every file, its scenario and what the app
should show for it. Without `--seed-dir` the photos are generated.

`--exif-donors` names a folder of camera files kept for their metadata, such as
[ExifTool's sample images](https://exiftool.org/sample_images.html): real tags from
hundreds of cameras on pictures shrunk to a few pixels. About three in four seed JPEGs
with no EXIF date get one donor's tags (camera, lens, exposure, dates, GPS, maker notes,
damaged ones included) on a fresh copy; the rest stay without, for No capture date. The
donor's size, previews and rotation are left behind, since they would contradict the
pixels. A donor folder inside the seed is left out of the originals, and six donors join
the library as themselves, tiny images for sorting out by resolution. Measured on a seed
of 4,700 downloaded photos with EXIF stripped and 7,119 donors: 3,420 given tags, dated
photos up from 3% to 70%, 296 camera makes, 53 s for the whole build.

The seed folder is never written to: every file the script alters is written anew and
renamed into place, which breaks its link first, and each run ends by proving it
(`seed: N file(s), untouched by this run`). A seed folder that is still filling, say
from a download, is reported, not mistaken for a write. `build` refuses a non-empty
folder it did not make, and rebuilds its own only with `--replace`.

Hard links need the seed and `OUT` on one filesystem **and one mount**, so mount their
common parent once. Create `OUT`'s parent yourself first: Docker makes a missing mount
path owned by root.

```bash
mkdir -p /photos/demos
docker run --rm --user "$(id -u):$(id -g)" --entrypoint python3 \
  -v /photos:/photos -v "$PWD":/app -w /app negativespace \
  tests/make_scenarios.py build --seed-dir /photos/seed --out /photos/demos/demo \
    [--exif-donors /photos/seed/exiftool-samples] [--replace] [--seed N]
# Index and Copy with SOURCE_DIR=/photos/demos/demo/library, then:
docker run ... tests/make_scenarios.py change --out /photos/demos/demo [--dest <your DEST_DIR>]
# Index and Copy again: the lineage tree now has changes to show.
```

Its test, `make_scenarios_test.py`, runs in CI: a seed that must stay byte-identical, a
seed filling during a build, refusals, and the real engine's Index checked against the
manifest, including that an empty file and a text file named `.jpg` are logged as
**Not an image** and never filed.

## Spec and schema checks — `tools/`

Not tests of the engine, but CI gates on them and they exit non-zero on failure:

```bash
python3 tools/check-specs.py          # cross-references resolve, fences balance, tables are whole
docker run --rm -v "$PWD":/app -w /app negativespace python3 tools/check-schema-drift.py
                                      # engine-spec 6.5 matches what the engine creates
docker run --rm -v "$PWD":/app -w /app negativespace python3 tools/check-api-spec.py
                                      # every API route is in api-spec.md, and nothing else is
```

The browser harness also runs `ui_browser_checks.py` for shared control behavior: modal
focus, menus, field errors, help, theme contrast, failed-page retry and narrow layouts.
Selection checks preserve the toolbar height and navigation position while keeping
the selection actions' full-height click targets.
Single-photo Copy/Move confirms in a dialog without replacing the gallery or hiding
its sidebar; multiple-photo review remains covered by the full browser driver.
It also checks the Inspector's inner preview/details divider: pointer and keyboard
resizing, remembered proportions, and orientation changes in a wide desktop panel.
Outer-divider checks cover the gallery minimum, preserved filter width, oversized
saved Inspector widths, and recalculation after desktop window/filter resizing.
See `docs/ui-design.md` for the interaction contract and the manual accessibility checks
required before claiming WCAG conformance for the supported desktop experience.
Mobile support and real touch-device validation are optional; desktop zoom and reflow
remain in scope. Existing phone-emulation checks guard implemented behavior rather than
establishing a mobile release requirement.

Navigation (audit N8):
`DRIVER=navigation_browser_drive.py sh tests/webui_browser_test.sh`
checks same-page log and Library links, Back/Forward, open-photo restoration,
continuous scrolling and preservation of selection when leaving a focused view.

Preview refresh:
`DRIVER=preview_refresh_browser_drive.py sh tests/webui_browser_test.sh`
checks open Inspector details/history after transfers, recovery from a temporary
grid 404, bounded retries of persistent misses, unchanged healthy image elements,
selection/scroll retention and the non-link job-result help control.

Request identity (audit N7):
`SUBMISSION_FIXTURE=1 DRIVER=submission_browser_drive.py sh tests/webui_browser_test.sh`
drops responses after actual acceptance, including a fast finished job followed by
another tab's job and a slow Copy with an open confirmation. It also drops a request
before delivery, reloads the page, and retries using the same persisted ID. The
fixture delays Copy after acceptance; it otherwise runs the real engine. API tests
cover concurrent replay, conflict, lookup after API restart, safety-answer replay,
invalid IDs and a simulated late acceptance race. The normal suite exercises all
ordinary submission call sites using the same manager.

Safety questions (audit N6):
`NETWORK_FIXTURE=1 DRIVER=safety_questions_browser_drive.py sh tests/webui_browser_test.sh`
uses the real engine with only filesystem-type detection replaced, against the
harness's disposable photos. It checks explicit choices, cancellation, scope,
empty-source confirmation/reconnect and Copy versus Move confirmation. API cases
also test writable-source removal, selected/folder/whole-source targeting, stale
answers, changed roots, busy engine and unsupported input. No real network share
or maintainer data is needed; network durability itself is not tested.

For audit N4, `DRIVER=transfer_outcome_browser_drive.py sh tests/webui_browser_test.sh`
checks mixed and all-failed prerequisite scans for Copy and Move, including banner
counts and View failures links. It modifies only the harness's disposable photos.
The API suite also runs all four cases with a writable source to verify successful
Move alongside scan failures. Existing verdict cases cover cancellation, copied-only,
unchanged Index, repeated Copy and unrelated recovery.

### Preparing an existing similarity validation catalog

For this branch's current sample handoff, the maintainer chose to rebuild the
catalog. With fresh appdata, use **Create catalog → save settings → Index → Copy**,
then validate the gallery controls and Inspector. Keep the source read-only and the
existing sample destination. No upgrade step is required for this route.

Optional preservation route for an existing development catalog:

The current count cache uses schema 16 (the 75% floor was introduced in schema 15).
Automatic startup upgrades remain disabled. To preserve schema-14/15 history and
judgments, stop the app and run
`tools/prepare-similarity-catalog.py --source <old-catalog> --output <new-catalog>`
with the updated dependencies. Add `--compare` when preparing schema 14 to fill the
wider comparison range. Output must be a new file. The tool uses SQLite backup,
preserves schema-15 comparisons, builds all six gallery counts, and checks integrity
and foreign keys. Retain the original catalog and use the matching old app image
for rollback; never install a snapshot taken before later user writes. It reads
stored hashes, not photos. Other input schema versions are refused.

Cache checks in the database/API suites cover schema-14/15 preparation, unchanged
source/history/judgments, all six thresholds and an uncached intermediate threshold,
missing destination files, representative changes, changed hashes/relationships,
rollback, old reader snapshots, cancelled publication and live fallback. Engine
settlement retains its FULL durability check. A cancelled cache build is not a
request to re-copy photos; subsequent reads remain correct using live aggregation.

Manual UI checks: switch All photos / Has similar photos / No capture date and
compare card geometry, summary placement and filter actions. At narrow desktop
widths, controls should wrap without clipping. Open a card from Has similar photos:
Similar photos should be selected at the gallery percentage. Switch to information,
use next/previous (retain that choice), then click another similar-gallery card
(reopen Similar photos). Reload preserves the explicit tab. Check the shortcut's
pressed state against Sort. Long filter descriptions remain in More information.

### Choosing a source for manual validation

Use generated or sample photos for short checks and the shareable demo. Use a
representative real library over NFS for larger read/performance checks in a separate
private instance. Mount either source read-only and run **Index → Copy → destination
review**. Do not use Move against the real validation source. An indexed source alone
does not populate destination similarity review.

Give each instance its own catalog/appdata, cache, backups and writable destination;
keep the destination on the intended local storage volume with enough room for the
test. Before Copy, verify the running app's bind mounts with `docker inspect`: check
the host source behind `/data/dest` and confirm `/data/source` is read-only. Changing
an environment file alone does not remount an existing container. Recreate the app
after it is idle to apply mount changes; do not assume this migrates an existing
destination or updates recorded paths.

Keep host-specific paths, private filenames and raw reports in ignored local files.
The LAN demo should use only its sample source and separate destination. Share
aggregate timings and generated-fixture screenshots in tracked documentation.
The sampler below makes hard links; those are suitable for read-only input, not
isolated files for future in-place EXIF editing tests.

### Shareable sample instance

`docker/compose.sample.yml` runs a separate app, web server and Docker network.
Provide an environment file with `SAMPLE_SOURCE`, `SAMPLE_DEST`, `SAMPLE_APPDATA`,
`SAMPLE_CACHE` and `SAMPLE_BACKUPS` pointing to distinct, existing directories.
Use a sample source (for example, the scenario generator's `library`), and new
writable directories. The source is always mounted read-only. Set `PUID`/`PGID`
to the directory owner and choose the built `SAMPLE_APP_IMAGE`/`SAMPLE_WEB_IMAGE`.

The default bind is localhost port 8082. For LAN sharing set `SAMPLE_BIND=0.0.0.0`
and open `http://<host-LAN-address>:8082`; `SAMPLE_PORT` can change the port.
Only the web port is published. The sample app has access only to its sample mounts.

```bash
docker compose --env-file <sample-env-file> -f docker/compose.sample.yml up -d
```

Create the catalog, run Index and Copy in this new instance. Then open a photo:
From All photos, Photo information should appear first. Similar photos opens the counts and thumbnail
grid, initially at 90%. Resize the Inspector, switch tabs with the keyboard, and
move to the next photo: the tab/threshold should remain, with match paging reset.
Reload should restore the recorded tab and match page. The provided scenario set
contains intentional unreadable/invalid files; those are expected test outcomes.

Before opening a candidate, enter **Has similar photos**, click the visible
**Most matches first** shortcut (also available in Sort), and
change **Matches at or above**. Check card counts against the Inspector at that same
percentage. Search/date/type/folder filters narrow references, not their counted
matches. Zero-match photos disappear; explicit checkbox selection remains. Reload
and return from Logs: sort and gallery threshold persist. Opening a gallery card
opens Similar photos at the gallery threshold; later Inspector changes do not reorder
the gallery. Leaving Has similar photos resets its special sort to Newest first.
The API checks ranking before pagination, tie ordering, matching facet/selection
scope, exact-copy deduplication, threshold boundaries and partial coverage. Browser
checks exercise the controls, card counts, selection preservation and narrow reflow.

Open a candidate using **Review side by side** to enter the expanded workspace:

1. Rotate and zoom each preview separately; then enable linked zoom/position.
   Rotation stays independent. Switch candidates and return: viewing transforms
   follow their photo until the workspace closes. No file orientation is saved.
   At 90°/270°, dimensions beneath the preview swap width and height and read
   **Displayed**; at 180° they keep the original width/height order. Reset restores
   the original view. Zoom never changes these dimensions. The information pane
   retains recorded dimensions, megapixels and file size throughout.
2. In Information, check **File and image properties** above **Capture information**:
   format, extension, pixel dimensions, megapixels, file size and aspect ratio.
   Missing values and fallback dates remain labelled; a format inferred only from
   the filename says **extension only**. Differences are neutral, with no automatic
   winner based on format or size. Differences only applies to every section;
   All recorded tags adds the full metadata table, with search scoped to that table.
   Scroll each table: **Field / Reference / Candidate** stays visible while its rows
   scroll, including narrow reflow. The heading background should be opaque in both
   light and dark themes.
3. Record a pair judgment. Check Reviewed and Unreviewed, switch pages, then close
   and reopen: the saved judgment and progress survive. Browsing alone never saves
   a judgment or changes gallery checkboxes.
4. Resize the comparison/information divider and the browser window. Candidate
   browsing remains available; Back to gallery restores the Inspector context.
   Both previews' dimensions, sizes and linked-zoom controls fit their comparison
   area without an inner vertical scroll; the whole review window scrolls when
   needed. The information pane can scroll independently on desktop.
5. Choose **Use as reference** above a candidate. Its blue reference frame moves
   with the photo, its matches reload at the same threshold, and the previous
   reference appears beside it. Review status resets to All candidates on page
   one. Saved pair judgments and each photo's viewing rotation remain attached to
   the right photos. Back to gallery returns to the originally opened photo.
   **Reference photo** is a plain heading, not a button; the blue preview border
   distinguishes it from the candidate. Promotion does not select a keeper or donor.

The generated-catalog browser check is `DRIVER=similar_browser_drive.py sh
tests/webui_browser_test.sh` (set `IMAGE`/`WEB_IMAGE` to the builds under test).
Metadata writes, end-of-review orientation saving, deletion, deferred queues and workspace restoration across reload are tracked in
[TODO.md](../TODO.md#expanded-destination-review-workspace). These are not current
validation steps. The current workspace implements comparison and judgments, and
closing it discards temporary rotation without a save prompt.

### Suspicious-date checks

Run `python3 -m unittest discover -s tests -p suspicious_dates_test.py` with app
dependencies. It verifies boundary years, missing/fallback dates, paged membership,
selection IDs, browse endpoints and unchanged metadata. For the generated browser
fixture use `DRIVER=suspicious_dates_browser_drive.py SIMILARITY_RECOVERY_FIXTURE=1`
with `tests/webui_browser_test.sh` and the built IMAGE/WEB_IMAGE. The opt-in catalog
mount contains only disposable generated data. Checks cover the view, reload,
Inspector reasons, comparison date review and narrow reflow.
