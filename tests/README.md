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

For project validation, enable these two tests with the public RAW samples rather
than accepting the optional skips. The current decode test samples up to five files;
the thumbnail test samples three, so this is not exhaustive coverage of every supplied
RAW file. Keep the sample mount read-only.

The default real-photo source is the **whole demo library**, including its assorted
formats, EXIF samples, RAW files and generated edge cases. Use its manifest to check
expected behavior, and mount the source read-only. Use the NASA-only subset when a
check deliberately needs only ordinary photos; it is not the default validation set.

Flags: `--filter NAME` runs tests whose name contains NAME (a filter matching nothing
is an error), `--keep` leaves the workspace on disk, `-v` shows engine output, and
`--engine PATH` runs the suite against another copy of the engine (the folder holding its
`engine/` package) — the way to prove a test catches the defect it guards against. The
test file's docstring is the authoritative reference. Fault-injection tests load the
engine in-process as one namespace: `engine.X = f` replaces X in the module that defines
it, which every caller looks up.

The suite does **not** run under pytest: pytest mis-collects its `@test` registration
decorator and errors without running anything.

The `verified_recovery` tests interrupt real Moves around source deletion and check
fresh delivery, existing-copy reuse and duplicate cleanup. They verify destination
content before success, reject unreadable/non-file/changed candidates, check both
operations' destination participation, and inject a lineage-write failure to prove
the recovery transaction rolls back. Run this subset with `--filter verified_recovery`.

The `relocation_recovery` tests cover interrupted Rename, Reject and Return. They
refuse changed content, non-regular/unreadable files and missing intent hashes;
replace either path after hashing to check stability; verify success and repeated
recovery; and inject a directory-sync failure before old-link removal. They also
ensure an uncertain Return is not subsequently recorded as emptied Rejects. Run
this subset with `--filter relocation_recovery`. The `an_interrupted` tests also
cover relocations that stopped before the file moved.

The `relocation_failure` tests inject failures into actual Rename, Reject and Return
calls: each post-rename directory sync, native and hard-link primitives, old-link
removal, and ambiguous replies before/after a rename. They check that the original
intent survives and a subsequent Index repairs the catalog without another
relocation. Confirmed refusals, persistent recovery-sync failures, changed content
and attention-issue resolution are covered too. Run with `--filter relocation_failure`,
or `--filter relocation_` for both relocation subsets.

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
Jobs start the real engine (`python -m engine`) as a child process, as in production, so the
request-to-run handshake, the engine lock, cancellation and the derived outcome are
tested together:

```bash
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app -w /app \
  negativespace python3 -m unittest discover -s tests -p webui_api_test.py
```

To prove a test catches a defect in the API, copy the checkout, change the copy, and
mount the copy as `/app`: the API is imported in-process, so `--engine` cannot reach it.

## Selection ownership — `selection_ownership_test.py`

Cross-process submission and cleanup against generated fixtures. A fixture pauses
the real engine before it reads its selection; tests start another API instance,
kill the submitting API process, and verify the surviving child still accepts
exactly one job. They also cover an abandoned writer before spawn, same-ID retry,
and cleanup that preserves unrelated files and directories. CI runs this suite.

```bash
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app -w /app \
  negativespace python3 -m unittest discover -s tests -p selection_ownership_test.py -v
```

`selection_engine_fixture.py` is only a test wrapper; it resumes the real engine
after the test releases the pause. It is not an alternative production engine.

## Web interface in a browser — `webui_browser_test.sh`

Both containers as `docker/compose.yml` arranges them (`app`, and `web` proxying `/api`
to it), driven by headless Chromium (Playwright) against generated photos. It covers first run, settings, Scan, the gallery,
the Inspector, selection, Copy, search and the phone-width layout, and fails on any
browser console error. It starts a server container and a Playwright container, so it
runs on the host:

```bash
docker build -f docker/app.Dockerfile -t negativespace . && docker build -f docker/web.Dockerfile -t negativespace-web .
sh tests/browser/webui_browser_test.sh
```

`IMAGE=<tag>` and `WEB_IMAGE=<tag>` test other builds, and `SHOTS=<folder>` keeps
screenshots of the main screens for review by eye. The photos are generated, so the
screenshots show nothing from a real library. To prove it catches a frontend defect, change a copy
of the checkout, build that copy under another tag, and run with `IMAGE` set to it.

| Driver (`DRIVER=`) | Extra setting | Checks |
| :--- | :--- | :--- |
| `webui_browser_drive.py` (default) | | First run, Index, the gallery, Inspector, selection, Copy, Stats, Settings, backups, search, phone width; runs the shared UI checks |
| `ui_browser_drive.py` | | The shared UI checks alone |
| `appearance_browser_drive.py` | | Palettes, contrast, storage, narrow controls |
| `navigation_browser_drive.py` | | Links, Back/Forward, restoration |
| `gallery_position_browser_drive.py` | | Positioning a photo from Logs, hidden photos |
| `large_selection_browser_drive.py` | `SIMILARITY_RECOVERY_FIXTURE=1` | Show only selected and Inspector navigation across page boundaries with more than 1,000 selected photos |
| `preview_refresh_browser_drive.py` | | Inspector refresh after jobs, thumbnail retry |
| `transfer_outcome_browser_drive.py` | | Copy/Move with failed scans |
| `rejects_browser_drive.py` | | Reject, Rejects view, one place per selection, reminder, Stats tile |
| `similar_browser_drive.py` | | Similar photos and the comparison workspace |
| `reject_similar_browser_drive.py` | | Rejecting from Similar photos and side by side |
| `similarity_recovery_browser_drive.py` | `SIMILARITY_RECOVERY_FIXTURE=1` | Recovering missing visual hashes |
| `reference_sets_browser_drive.py` | `SIMILARITY_RECOVERY_FIXTURE=1` | Grouped sets, set review |
| `suspicious_dates_browser_drive.py` | `SIMILARITY_RECOVERY_FIXTURE=1` | Suspicious dates view and review |
| `submission_browser_drive.py` | `SUBMISSION_FIXTURE=1` | Request identity across lost responses and reloads |
| `safety_questions_browser_drive.py` | `NETWORK_FIXTURE=1` | Safety questions before a Move |

`SIMILARITY_RECOVERY_FIXTURE=1` mounts only the harness's disposable generated catalog;
`SUBMISSION_FIXTURE=1` delays Copy after acceptance (`submission_engine_fixture.py`);
`NETWORK_FIXTURE=1` reports the destination as a network share
(`network_engine_fixture.py`). Each still runs the real engine.

### Shared UI checks — `ui_browser_checks.py`

The default driver and `ui_browser_drive.py` run `ui_browser_checks.py` for shared control behavior: modal
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

### What each driver checks

`DRIVER=similar_browser_drive.py sh tests/browser/webui_browser_test.sh` checks the empty review after Index, then Copies
the isolated generated fixtures and checks cumulative Inspector counts, inline match
pagination, gallery selection preservation, side-by-side review,
reload/Back state, request failure retries, legacy bookmarks and narrow Inspector dialogs.
It also checks independent rotation and displayed dimensions, unchanged recorded
dimensions, reference promotion, file-format fallbacks, exact-byte differences,
missing dimensions, and sticky column headings in desktop and narrow layouts. The
workspace frame is checked there too: its header stays in view while the window scrolls,
← → step candidates from wherever the comparison opened, tabs keep their own arrow keys,
and Esc returns to the gallery with focus back on the opening control.

`SIMILARITY_RECOVERY_FIXTURE=1 DRIVER=similarity_recovery_browser_drive.py sh tests/browser/webui_browser_test.sh`
opts into mounting **only the harness's disposable generated catalog** to arrange
missing/unsupported hashes. It exercises warning-to-recovery navigation, disabled
busy actions, real repair and comparison-only jobs, refreshed results, failed-load
retry, unsupported-format limitations and narrow reflow. It never accesses a real
library. `similar_browser_drive.py` additionally checks comparison refresh with
rotation/zoom/position, filtered review/tab restoration, and malformed bookmarks.

`DRIVER=gallery_position_browser_drive.py sh tests/browser/webui_browser_test.sh` checks
Logs photo positioning, offscreen Inspector navigation, retained filters, explicit
hidden-photo display, retry, ordinary gallery clicks, manual scrolling and History
action alignment. Its fixtures are generated photos in isolated containers.

`DRIVER=reject_similar_browser_drive.py sh tests/browser/webui_browser_test.sh` checks rejecting
from Similar photos and side by side: Reject… per look-alike; in the comparison a Reject…
under each photo, asked once with Don't ask again, the next look-alike with Return it to
the library, a new comparison asking again, and the last photo always asked about; Keep
this one, reject the rest with the kept photo first, full size and never ticked.
It also checks the single large reference preview, its heading and accent border,
no repeated reference thumbnail in the matches pane, and no Keeping label before
an explicit Keep choice, across wide/stacked layouts and forced colors.

Manual check: open Similar photos, confirm the large preview is labelled **Reference
photo**, then choose **Keep reference, reject n matches…**. Only the resulting review
should label it **Keeping**; Cancel should return without rejecting anything.

`DRIVER=rejects_browser_drive.py sh tests/browser/webui_browser_test.sh` checks Rejects: one
photo rejected from the Inspector (asked first by name, starting on Cancel), a selection
reviewed before rejecting, the Rejects view with what it holds and How to empty Rejects,
Return to library, the selection bar for photos in Rejects (Return first, and a Move that
warns its copies in Rejects become the only ones), one place per selection (library
photos' tick boxes disabled while a photo in Rejects is selected), the view at a narrow width, the reminder past a size limit on every
page and switched off in Settings, and the Rejects tile on Stats.

`DRIVER=appearance_browser_drive.py SHOTS=/tmp/ns-shots sh tests/browser/webui_browser_test.sh`
checks both neutral palettes in light/dark modes, text and input contrast, local
preference persistence, cross-tab updates, blocked storage, and narrow controls.
It also checks that Appearance is first in Settings and that dialog scroll cues
appear and disappear at the corresponding scroll boundaries.
Create the screenshot directory before mounting it. These screenshots use only
generated test photos. The normal browser driver also captures each main screen.

`DRIVER=navigation_browser_drive.py` checks same-page log and Library links, Back/Forward, open-photo restoration,
continuous scrolling and preservation of selection when leaving a focused view.

`DRIVER=preview_refresh_browser_drive.py` checks open Inspector details/history after transfers, recovery from a temporary
grid 404, bounded retries of persistent misses, unchanged healthy image elements,
selection/scroll retention and the non-link job-result help control.

`DRIVER=submission_browser_drive.py` drops responses after actual acceptance, including a fast finished job followed by
another tab's job and a slow Copy with an open confirmation. It also drops a request
before delivery, reloads the page, and retries using the same persisted ID. The
fixture delays Copy after acceptance; it otherwise runs the real engine. API tests
cover concurrent replay, conflict, lookup after API restart, safety-answer replay,
invalid IDs and a simulated late acceptance race. The normal suite exercises all
ordinary submission call sites using the same manager.

`DRIVER=safety_questions_browser_drive.py` uses the real engine with only filesystem-type detection replaced, against the
harness's disposable photos. It checks explicit choices, cancellation, scope,
empty-source confirmation/reconnect and Copy versus Move confirmation. API cases
also test writable-source removal, selected/folder/whole-source targeting, stale
answers, changed roots, busy engine and unsupported input. No real network share
or maintainer data is needed; network durability itself is not tested.

`DRIVER=transfer_outcome_browser_drive.py` checks mixed and all-failed prerequisite scans for Copy and Move, including banner
counts and View failures links. It modifies only the harness's disposable photos.
The API suite also runs all four cases with a writable source to verify successful
Move alongside scan failures. Existing verdict cases cover cancellation, copied-only,
unchanged Index, repeated Copy and unrelated recovery.

## Similarity checks

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
Actual gallery/Inspector query timings provide the next validation step on a
representative destination catalog after Index and Copy or Move. An Index-only
catalog has no reviewable destination photos. Synthetic benchmarks create recorded destination copies
and assert that all requested photos are included in query measurements.

`python3 -m unittest discover -s tests -p similarity_recovery_test.py` checks
cancellation during decoding, concurrent byte changes, distinct read/decode failures,
destination boundaries, unsupported formats and source-only exclusion. The API suite
runs real Index/Copy/recovery, repairs with the source gone, verifies unchanged bytes,
checks busy/idempotent requests, and resumes comparisons without photo reads.

The database suite verifies the hash index against brute force and interrupted
comparison recovery; the API suite checks reference-only matches, hash changes,
availability, exact copies, thresholds and pagination.

Cache checks in the database/API suites cover all six thresholds and an uncached intermediate threshold,
missing destination files, representative changes, changed hashes/relationships,
rollback, old reader snapshots, cancelled publication and live fallback. Engine
settlement retains its FULL durability check. A cancelled cache build is not a
request to re-copy photos; subsequent reads remain correct using live aggregation.

### Suspicious-date checks

Run `python3 -m unittest discover -s tests -p suspicious_dates_test.py` with app
dependencies. It verifies boundary years, missing/fallback dates, paged membership,
selection IDs, browse endpoints and unchanged metadata. For the generated browser
fixture use `DRIVER=suspicious_dates_browser_drive.py SIMILARITY_RECOVERY_FIXTURE=1`
with `tests/browser/webui_browser_test.sh` and the built IMAGE/WEB_IMAGE. The opt-in catalog
mount contains only disposable generated data. Checks cover the view, reload,
Inspector reasons, comparison date review and narrow reflow.

### Reference-set checks

With app dependencies, run `python3 -m unittest discover -s tests -p reference_sets_test.py`.
The generated A–B–C–D chain checks direct membership, explicit unions, deduplication,
thresholds, stale selections, paging, destination-only eligibility and no DB writes.
Run the browser harness with `DRIVER=reference_sets_browser_drive.py` and
`SIMILARITY_RECOVERY_FIXTURE=1`, specifying the built `IMAGE` and `WEB_IMAGE`.
It uses only the harness's disposable generated catalog. Checks include grouping,
indirect comparison through the correct reference, selection preservation, session
reset, dense same-hash paging, expansion limits, failure retry, narrow modality and
per-file recovery failure details in Logs.

`python3 tools/benchmark-reference-sets.py` measures opened-set queries against
250,000 generated catalog identities with prepared sparse edges. It reads no photo
files and does not establish dense-set or end-to-end real-library capacity.

### Current similarity regression coverage

The maintainer has completed the manual functional checklist (recorded in
[the validation record](../docs/similarity-validation.md)). Representative
large-library capacity remains separate work.

Similarity defaults regression: the reference-set browser driver checks initial
Group similar photos / Most matches first, remembered grouping and per-view sort,
and explicit URL precedence. Recovery tests distinguish bulk generation of never
computed hashes from explicit rechecks after external fixes. Known failures must
not be retried by bulk generation; unsupported decoders offer no futile retry.

The defaults regression also checks the initial 90% gallery threshold, remembering
an explicit percentage, and URL threshold precedence without changing preferences.

Identical-set validation: reference_sets_test.py checks exact membership collapse,
partial overlaps, thresholds, filtered representatives, pagination and selection.
The reference-set browser driver expects five grouped tiles for the 130-photo
fixture, including one 126-member set, and verifies ungrouping restores photo cards.
tools/benchmark-reference-sets.py also measures a full grouped-gallery query on its
250,000-photo sparse prepared fixture; this is not dense-library capacity evidence.

The reference-set fixture also checks manual and successful clipboard paths,
copied comparison restoration including rotation, previous/next gallery sets,
selection preservation in the temporary set-member gallery, and paging a 126-photo
set. reference_sets_test.py verifies set_reference membership/paging/IDs/position
and rejects invalid IDs. Clipboard output is only a local generated-fixture link.

## Shell tests

These run on the host, not in the container, because the thing under test is a shell
script:

```bash
sh tests/sampler_test.sh                                   # the sampler never writes to the library
docker build -f docker/app.Dockerfile -t negativespace . && sh tests/entrypoint_test.sh   # the entrypoint's ownership handling
sh tests/shutdown_test.sh      # docker stop with a browser tab open: clean, and the app's shutdown runs
```

## Spec and schema checks — `tools/`

Not tests of the engine, but CI gates on them and they exit non-zero on failure:

```bash
python3 tools/check-specs.py          # cross-references resolve, fences balance, tables are whole
docker run --rm -v "$PWD":/app -w /app negativespace python3 tools/check-schema-drift.py
                                      # engine-spec 6.5 matches what the engine creates
docker run --rm -v "$PWD":/app -w /app negativespace python3 tools/check-api-spec.py
                                      # every API route is in api-spec.md, and nothing else is
```

## Manual validation

Steps the maintainer runs by hand in the browser, on an instance of their own. Record results as aggregate figures in the pull request (see `CLAUDE.md`).

### Choosing a source

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

### Similarity catalog setup

The validated sample uses a fresh catalog rebuilt by maintainer choice. With fresh
appdata, use **Create catalog → save settings → Index → Copy**,
then validate the gallery controls and Inspector. Keep the source read-only and the
existing sample destination. No upgrade step is required for this route.

### After Index and Copy

For manual validation after Copy, open a destination photo in the gallery and choose
**Similar photos** in the Inspector. Click a 75/80/85/90/95/100% count to browse
its matches in the thumbnail grid. Use
**Has similar photos** to narrow the gallery; the count buttons narrow only the
Inspector results. The gallery's separate **Matches at or above** selector changes
its membership, and **Most matches first** sorts counts highest first. Reload and
return from Logs to confirm the reference and threshold
remain.

Manual checks after Index/Copy: use Review matching status for any affected photos;
review the reason, run the appropriate action, and check the remaining count. In
comparison, rotate or zoom, choose a review filter, and refresh: the same comparison
should reopen. Back to gallery clears it. EXIF edits, saved orientation writes and
deletion belong to a separate workstream and do not block these checks.

Manual UI checks: switch All photos / Has similar photos / No capture date and
compare card geometry, summary placement and filter actions. At narrow desktop
widths, controls should wrap without clipping. Open a card from Has similar photos:
Similar photos should be selected at the gallery percentage. Switch to information,
use next/previous (retain that choice), then click another similar-gallery card
(reopen Similar photos). Reload preserves the explicit tab. Check the shortcut's
pressed state against Sort. Long filter descriptions remain in More information.

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
3. Browse candidates and switch pages: browsing never changes gallery checkboxes.
4. Resize the comparison/information divider and the browser window. Candidate
   browsing remains available; Back to gallery restores the Inspector context.
   Both previews' dimensions, sizes and linked-zoom controls fit their comparison
   area without an inner vertical scroll; the whole review window scrolls when
   needed. The information pane can scroll independently on desktop.
5. Choose **Use as reference** above a candidate. Its blue reference frame moves
   with the photo, its matches reload at the same threshold, and the previous
   reference appears beside it, on page one. Each photo's viewing rotation stays
   with it. Back to gallery returns to the originally opened photo.
   **Reference photo** is a plain heading, not a button; the blue preview border
   distinguishes it from the candidate. Promotion does not select a keeper or donor.

The generated-catalog browser check is `DRIVER=similar_browser_drive.py sh
tests/browser/webui_browser_test.sh` (set `IMAGE`/`WEB_IMAGE` to the builds under test).
Metadata writes and end-of-review orientation saving are tracked in
[TODO.md](../TODO.md#dates-and-metadata). These are not current
validation steps. The workspace compares, rejects and keeps one of a set; closing it
discards temporary rotation without a save prompt.

### Manual Copy review link check

1. Open a photo comparison using Review this set or Review side by side. Rotate a
   preview or adjust zoom so the restored state is easy to recognize.
2. Click Copy review link near the top of the comparison window. If Review link
   copied appears, proceed to step 3. If Copy this review link manually appears,
   click inside its text field, press Ctrl+A while the field is focused, then Ctrl+C
   (Command+A / Command+C on macOS). Local-network HTTP may require this fallback.
3. Open a new browser tab, paste into the address bar, and press Enter. Use a tab
   that can access the same sample instance; the link does not upload photographs.
4. Confirm the same reference/candidate, percentage and current pair rotation/zoom
   reopen.

Pass: either copy path gives a usable link that restores the current comparison.
The manual fallback is expected behavior when clipboard access is unavailable.

### Validating against real files — `make_sample_tree.sh`

Synthetic fixtures cannot stand in for a real library, but most checks do not need the
whole of one either. The sampler builds a small **hard-linked** sample: no extra disk
space, the originals' real bytes, mtime and EXIF, and one deliberate duplicate so
duplicate cleanup is exercised. Deleting from the sample never touches the library, so
it is safe to point `--move` at.

```bash
sh tools/make_sample_tree.sh [--no-raw | --all-types] <library> <sample> [every-Nth, default 25]
```

`--all-types` samples every file, not only photos — what the Index's file-type
accounting needs, since a photos-only sample excludes nothing. A sampled file shows a
link count of 2 (the duplicate 3); `du` reports the full size regardless, so link count
is the test that it is really linked.

### A library of scenarios — `make_scenarios.py`

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
  tools/make_scenarios.py build --seed-dir /photos/seed --out /photos/demos/demo \
    [--exif-donors /photos/seed/exiftool-samples] [--replace] [--seed N]
# Index and Copy with SOURCE_DIR=/photos/demos/demo/library, then:
docker run ... tools/make_scenarios.py change --out /photos/demos/demo [--dest <your DEST_DIR>]
# Index and Copy again: the lineage tree now has changes to show.
```

Its test, `make_scenarios_test.py`, runs in CI: a seed that must stay byte-identical, a
seed filling during a build, refusals, and the real engine's Index checked against the
manifest, including that an empty file and a text file named `.jpg` are logged as
**Not an image** and never filed.

## Large-library performance workstream

Representative capacity work is scoped in
[the measurement plan](../docs/large-library-performance.md) for isolated inputs,
query scenarios, comparable A/B runs and pending coverage.
Existing synthetic tools do not establish real NFS or dense-library capacity.


### Synthetic catalog query benchmark

No source images, Index, Copy or running app instance are needed. Use a local app
image with dependencies, mount the checkout read-only and give only generated
output its own writable mount. Substitute your built image tag for `negativespace`.

```sh
mkdir -p /tmp/ns-query-results
docker run --rm --user "$(id -u):$(id -g)" --memory 2g \
  --entrypoint python3 -v "$PWD":/app:ro \
  -v /tmp/ns-query-results:/output -w /app negativespace \
  tools/benchmark-synthetic-queries.py --output /output/small-sparse \
  --photos 1000 --profile sparse --repeats 3 --revision "$(git rev-parse HEAD)"
```

Then use a new output directory, `--photos 250000` and `--repeats 30` for warm
percentiles. Try `--profile equal`, `dense` and `mixed` separately; these are distinct
workloads, not interchangeable evidence. `--threshold 75` measures broader browsing
without recalculating hashes or pairs. See the [profile limitations and measurement
contract](../docs/large-library-performance.md#synthetic-query-runner).

For an A/B query comparison, mount the candidate checkout at `/app`, keep the same
image and resources, and replace generation arguments with:

```text
--output /output/candidate-sparse --fixture /output/baseline-sparse/fixture
--baseline /output/baseline-sparse/report.json
--repeats 30 --revision <candidate-commit-or-explicit-dirty-label>
```

`baseline-sparse` must be an earlier successful generated run. Both code revisions
must understand the same schema and expose the query helpers used by this runner.
If the baseline predates this script, supply the same runner separately and place
it under the baseline's `tools/` directory in a disposable checkout. Do not compare
runs with different fixture fingerprints or changed result fingerprints as a speedup.
The optional `--baseline` adds candidate/baseline latency ratios to the report and
returns nonzero if fixture, repeat settings, scenarios, thresholds or result
fingerprints differ, or either workload failed. A ratio below 1 means faster; it
is evidence for that run, not a statistically established improvement.
No schema migration is performed. A supplied revision label is recorded as supplied;
Git cleanliness is unknown when the container has no Git. Keep the host dirty state
and image identity in your local run notes.

Each output contains `report.json`; generated runs also contain `fixture/` with
`catalog.sqlite` and `manifest.json`. Existing outputs are never overwritten.
Failures/timeouts return nonzero and remain in the report. The default per-request
worker deadline is 30 seconds (`--timeout`, maximum 300); it includes startup for
the first request. Reports with fewer than 30 warm samples deliberately omit p95.

Harness correctness checks (inside the same app dependency environment):

```sh
python3 -m unittest discover -s tests -p synthetic_queries_test.py
```

These check known memberships and identical-group collapse, destination/hash
eligibility, high thresholds, edge limits, repeated results, fixture reuse,
modified-fixture rejection (including pending WAL changes), query-only enforcement,
A/B compatibility checks and timeout reporting.


To attribute the Inspector/set workload to individual SQL statements, use the same
container/mount setup with:

```text
tools/profile-synthetic-queries.py --fixture /output/baseline-sparse/fixture
--output /output/profile-baseline.json
```

The output file must be new. It includes `EXPLAIN QUERY PLAN` and execution/fetch
timing for each read statement. Plan collection adds overhead: use this to locate
expensive work, and use `benchmark-synthetic-queries.py` for A/B measurements.
For a short 500k trial use `--photos 500000 --scenarios inspector related --repeats 3`;
this deliberately produces no p95. Keep repeat settings identical for its candidate
run, and use a new output directory for every profile/revision.

## Needs review

`python3 -m unittest discover -s tests -p review_test.py -v` in the app image checks
opt-in size reminders, unchanged transfer eligibility, independent review reasons,
acknowledged decisions, idempotent retries, stale-tab refusal, content replacement,
filter/count/position agreement and backup accounting with generated catalogs.
API test fixtures accept `NS_TEST_DESTINATION_ROOT` for separate destination storage
and `NS_TEST_KEEP=1` to retain artifacts; `TMPDIR` sets the app-data fixture root.
The first-run Files step now requires an explicit small-image reminder choice.

`DRIVER=review_browser_drive.py sh tests/browser/webui_browser_test.sh` covers first-run
choice, Copy, independent Small images/Review later decisions, refused-save retry,
Previous/Next, confirmed Reject, persistence after reload and Index, Settings links,
selection preservation, combined chips and narrow workspace reflow. The default browser
driver exercises choosing Off during first run. Both are in CI.

The browser harness accepts `NS_TEST_OUTPUT_ROOT`, `NS_TEST_DESTINATION_ROOT` and
`NS_TEST_KEEP=1` for an isolated retained fixture; create the parent folders first.
Use your own image tags through `IMAGE` and `WEB_IMAGE`.

Manual review before merging: choose On and Off on separate fresh catalogs, review
mixed-size delivered photos, verify a useful small photo disappears only from Small
images after Mark reviewed, and verify unwanted photos follow the existing Reject
confirmation. Inspect the workspace and first-run Files at desktop zoom. This branch
uses schema 21 and requires a fresh development catalog; it does not migrate schema 20.

The review browser driver also covers first-step navigation, source Index summary,
Copy confirmation, Library review markers, focused inbox entry and return with search,
sort and checkbox selection intact. Review API tests distinguish source size facts
from destination reminders and check current Library reasons without event histories.

The Index summary can be closed and reopened from Not organized. The review browser
check covers close/show focus, dismissal after refresh and filtering, and automatic
reopening after a new Index finishes. Review API coverage verifies that Copy and an
unfinished Index do not change the completed-Index identity used for dismissal.

### Review UX batch

The review browser flow verifies one toggle row per location, Small images filtering
Library without navigation, active toggles clearing, and selection retained across
place changes. It checks closing stale previews, temporary Index-summary collapse,
Inspector action grouping, the dedicated review layout, and matching-clue comparison
with return to review. Shared controls and comparison Reject/Keep flows use their
existing browser drivers. No EXIF or file-deletion capability is added.

Manual batch check: switch Library → Not organized with a photo open; open a source
preview and close it to restore the summary; toggle each filter twice; open Review
photo… and check the reason, action row, compact viewing controls and comparison clues.
A successful Mark reviewed clears only the size reminder. Unreadable-only source
results should point to failures rather than offering an ineligible transfer.


### Library-only review and job wording

The review API suite covers refusal of review writes outside active Library states,
reminders leaving the inbox when photos leave Library, retained history, and failed
sources excluded from photo/date statistics. Browser review and Rejects flows check
that source/rejected inspectors have no review/similarity actions. Shared browser checks
cover Job #ID · Action status, failure rechecks and the existing transfer workflows.

Run `DRIVER=source_scope_browser_drive.py` through the browser harness for generated
empty/text files with image extensions: separate ready/failure counts, saved review
links refused, failures excluded from Library/date filters, and Stats scope checks.

Manual check after first-run setup: Index, open a source file (information only), Copy,
open a Library photo (review and similarity available), Reject it and check Return is
offered without review actions. Check Index-summary ready/failure counts and failure
links, Stats scope explanations, and the shared job labels in banners and Logs.
