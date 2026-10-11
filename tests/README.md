# Tests

Everything here is for developing NegativeSpace; running the engine needs none of it.
CI runs all of it on every pull request and every push to `main`
(`.github/workflows/engine-tests.yml`).

The CI job has a 45-minute limit for the combined serial browser, API, metadata
and engine suites. The previous 20-minute limit cancelled a run after 56 successful
steps, before the final recovery/review and smoke checks could finish. This is an
overall job budget; individual test timeouts and assertions remain unchanged.
The file-issue browser fixture fixes its review order by filename and waits for the
refreshed queue before using Previous. A resolution notice alone does not mean the
follow-up gallery request has finished.

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
browser console error. The main driver also checks response framing headers and refusal
to embed the app from a separate HTTP origin in an isolated fixture container. It starts a server container and a Playwright container, so it
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
| `stalled_job_browser_drive.py` | `STALLED_FIXTURE=1` | Real stalled generated decoder, no-progress reminder, Keep waiting, explicit cancellation and lock release |
| `request_freshness_browser_drive.py` | | One initial Stats/log/facet request, refresh after a real job, retained Stats border/spacing in both themes and desktop reflow |
| `appearance_browser_drive.py` | | Palettes, explicit/system modes, contrast, cross-tab storage, shared page tools and narrow controls |
| `date_settings_browser_drive.py` | | Setup year choice, settings validation/persistence, immediate filter and Inspector updates |
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
rotation/zoom/position, Inspector tab/threshold/page restoration, and malformed bookmarks.

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
invalid IDs and a simulated late acceptance race. Ordinary Index/Copy/Move must
record edited-source cleanup consent as false and replay without spawning; a CLI
Move with explicit consent must conflict with an ordinary web Move of the same ID. The normal suite exercises all
ordinary submission call sites using the same manager.

`DRIVER=safety_questions_browser_drive.py` uses the real engine with only filesystem-type detection replaced, against the
harness's disposable photos. It checks explicit choices, cancellation, scope,
empty-source confirmation/reconnect and Copy versus Move confirmation. API cases
also test writable-source removal, selected/folder/whole-source targeting, stale
answers, changed roots, busy engine and unsupported input. No real network share
or maintainer data is needed; network durability itself is not tested.

`DRIVER=transfer_outcome_browser_drive.py` checks mixed and all-failed prerequisite scans for Copy and Move, including notification
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
uses the current schema and requires a fresh development catalog; it does not migrate older catalogs.

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
photo… and check the reason, action row, compact viewing controls and the Similar photos count/link. Open all matches in the
existing Similar photos tab; browser Back must restore the same review photo and queue
position without changing gallery filters or checked photos.
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

### Cross-location similarity

`DRIVER=cross_location_browser_drive.py` uses the isolated browser harness and generated
photos. It checks separate Library/Rejects counts, paging backward across a boundary,
reference promotion, copied review links with both scopes, location labels, Return for
both reference and candidate (with confirmation), Library-only review decisions, and
light/dark/narrow rendering. `webui_api_test.py` covers both candidate scopes, source
exclusion, invalid scope rejection and emptied Rejects. Gallery grouping and Keep-reference
continue to count only active Library photos.

The reference-set browser driver also checks grouping/control parity in Needs review,
automatic individual-photo results under extra review/search/sidebar filters, URL and
preference restoration, and narrow reflow. The API suite checks that a reviewed group's
lowest ID cannot hide remaining inbox photos, including selection IDs and positioning.

Appearance/date settings validation: `suspicious_dates_test.py` checks the configurable
lower boundary (1999 versus 2000), rejected invalid values, revision conflicts, shared
browse/inspection membership and unchanged metadata. The date-settings browser driver
covers choosing the year during setup, changing it later without indexing, and dark-mode
settings at desktop/reflow widths. The appearance driver covers explicit overrides,
System changes, reload, cross-tab updates, blocked storage, and identical header tools
on Library, Logs and Stats. Backups links must open the Backups settings tab directly.

The date-settings driver also resizes an open Inspector behind Settings: Settings
remains on top, and the narrow Inspector becomes modal only after Settings closes.

Layout stability: run `DRIVER=layout_stability_browser_drive.py` through the browser
harness with the built `IMAGE`/`WEB_IMAGE`. Generated photos plus one invalid image
exercise real job failures. It measures filter, summary and pager positions before and
after settled status/reason changes (1px tolerance) at 1440, 1000 and 720px; checks the
Logs navigation position across Library, Logs and Stats; and verifies filtered counts.
Set `SHOTS` to inspect the reserved spacing. This covers routine filter transitions,
not intentional expansion of jobs, errors, Inspectors or similarity tools.

Fresh-start/source eligibility checks:

- `python3 -m unittest discover -s tests -p import_decode_test.py -v` in the app image
  checks readable pixels despite missing EXIF, hash failure or cache-write failure,
  actionable missing-decoder refusal, and no redundant decode after a good pHash.
- `engine_smoke_test.py --filter an_undecodable_photo --keep` verifies Index, Copy,
  Move, byte preservation and successful external repair/reindex, with/without cache.
  The RAW-routing and public RAW decode/thumbnail smoke checks cover the sensor path.
- Browser drivers `fresh_start_browser_drive.py` and `source_scope_browser_drive.py`
  cover stale-address replacement only for missing catalogs, stable pending Index
  submission, empty/text/truncated source failures, and no incomplete-matching warning
  caused by those failed sources. `submission_browser_drive.py` retains lost-response,
  reload and same-request recovery coverage; pending Library actions cannot resubmit.

### Waiting for a job in browser drivers

A terminal run record does not mean the engine has released its lock: the catalog
backup runs after settlement. Before starting another job or asserting a finished
notification, wait for both a terminal run status and `GET /api/v1/jobs/active` returning
`active: null`. Do not retry a refused start to hide an unexpected refusal.

`DRIVER=notifications_browser_drive.py` checks delayed and failed notification-read writes,
failed saves with retry, interrupted reload before acknowledgment, storage clearing after
acknowledgment, new-job unread counts, result links and selection geometry. It deliberately
holds the PUT instead of relying on timing; pagination and concurrent acknowledgments are
also covered by the API suite.

The source-scope browser check starts Copy from the Index summary and verifies that
completion replaces the photo facts with a compact failure notice, without reloading.
The failed-only notice retains the failure link and omits zero-valued photo statistics,
similarity guidance and Copy/Move controls.

Reference-set checks also verify exact membership deduplication in related sets before
pagination: identical sets disappear, equivalent alternatives collapse to one, and
proper subsets/overlaps remain distinct. The browser exercises a dense identical set
and the A–B–C chain independently.

The scenario-generator identity checks cover device/inode collisions, retaining old
output identities until seed comparison, and a real write through a generated seed
hard link that must still fail. Guard links retain replaced output versions until the
check completes; they contain no photo extension and are removed on normal/error exit.
Scenario tests accept the same separate destination root and artifact-retention settings
as API fixtures.

`stalled_engine_fixture.py` deliberately blocks one generated file and spawns a decoder
child. The API test checks completed results and source bytes survive cancellation, no
decoder keeps running, and re-Index completes. Browser time advances only the reminder
clock; the actual engine waits for the user's cancellation. No network mount is stalled.

Instance-access checks: `access_test.py` tests pre-catalog persistence, catalog
replacement/restart, concurrent revisions, input rejection, protected recovery,
current-address confirmation, live WebSocket revocation, origin checks and symlink/
corrupt/write-failure handling. `access_browser_drive.py` checks setup, saving,
conflicts, lockout confirmation, and desktop/narrow appearance with generated hosts.

Review queue completion: clear the final Review later reminder with its Inspector
open. The workspace and preview close, the filtered gallery shows zero photos and a
completion message, and the URL no longer points to that photo/review. With other
queue items remaining, Back closes only a preview that no longer matches the view;
a still-matching preview and checkbox selection remain intact.

## Notification bell and selection stability

Run `notifications_test.py` inside the app Docker image. It verifies per-job read state,
strict/atomic refusal (including IDs outside SQLite’s integer range), cursor pagination,
concurrent acknowledgments, idempotence and
badge queries that do not derive outcomes. Run `notifications_browser_drive.py` with the
standard browser harness: it checks failed/delayed saves, reload and navigation, new jobs,
result links, inline failure details without covering actions, count-width stability
across digit changes, dark/light and narrow reflow.
Existing job workflows use the shared `finished_notice` helper to inspect their result
through the bell. Safety questions remain in actionable banners independently of read state.

Manual: open the bell after Index/Copy; verify each job, result and links; close/reload
and confirm the unread count stays cleared. Run another job and check that it creates
one new unread notice. Select 1, 9, 10 and more photos: the adjacent actions should stay
in place. Opening the bell must not move the gallery. Check Logs/Stats and desktop zoom.

## Gallery filter pins

Run `filter_pins_test.py` inside the app image with `PYTHONPATH=/app/tests:/app` for
replacement-versus-intersection counts, unchanged gallery membership, search scope and
invalid/exclusive pins. `DRIVER=filter_pins_browser_drive.py` in the normal generated
browser harness covers replacement, pin persistence, exclusive reminders, exact job
links, retained selection, keyboard access and light/dark desktop reflow. It checks
Clear all filters in the sidebar, stable filter-row positions, and clearing Source
folders/search without changing place. It also
holds Inspector detail responses to check that gallery clicks and arrow navigation
keep both tab labels and widths stable while loading.

Manual: in Library, click No capture date then Suspicious dates; only the latter stays
active. Pin Small images and try those date filters again: Small images stays applied.
Review later should show its count immediately in Library, including zero. Filter by
it, switch to Needs review and back, and confirm the same reminder remains applied.
Refresh, then check the Small images/Review later restriction in both places and
its unpin explanation. Clear all filters, beside Look into, should remove saved pins,
search and folder/date/type restrictions without clearing photo selection or changing
place. The filter rows should stay still when that action appears or disappears. No Index or Copy
is needed when the demo is already populated. Open a photo, choose Similar photos,
then click a different gallery photo: Photo information should open. Check this in
Library and Has similar photos; reloading an explicit Similar photos tab should retain it.

## Uncertain-operation recovery

Run `python3 -m unittest discover -s tests -p attention_test.py -v` in the app image.
Generated fixtures cover verified and missing copies, mismatches, symlinks, paths outside
mounts, cancellation, stale catalog content, relocation ambiguity, atomic rollback,
API eligibility and request replay. Existing review and database suites remain relevant.

Run `SIMILARITY_RECOVERY_FIXTURE=1 DRIVER=attention_browser_drive.py sh tests/browser/webui_browser_test.sh`
with your own app/web image tags. The disposable catalog fixture exercises Inspector,
Logs, Library-only File issues filtering, unresolved and resolved checks, review queue
refresh, and desktop/narrow reflow. It does not touch a real catalog.


## Externally removed Copied originals

`copied_source_test.py` runs real Index/Copy jobs on generated photos and covers verified
observations, Move eligibility, duplicate savings, empty-source confirmation, actionable
verification failures, explicit recovery, renamed paths, cancellation, path bounds,
source reappearance and atomic catalog rollback. Run as a non-root deployment user:

```sh
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app:ro -w /app \
  negativespace python3 -m unittest discover -s tests -p copied_source_test.py -v
```

`DRIVER=copied_source_browser_drive.py sh tests/browser/webui_browser_test.sh` validates
the existing Library/Inspector/history presentation and refreshed Move eligibility
after removing an original from the harness's generated source.


## Metadata provenance foundation

Run the generated source-resolution tests in an app image with the checkout mounted
(the production image does not include tests). Substitute your own image tag:

```sh
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app:ro -w /app \
  negativespace python3 -m unittest discover -s tests -p metadata_test.py -v
```

The suite covers explicit XMP precedence, missing versus empty fields, source origins,
original-byte round trips, alternate versions, invalid bindings, typed differences and
mutation isolation. These are pure helper tests: they do not validate XML parsing,
catalog durability or Index (covered by the storage and Index suites below), nor
sidecar transfers, which have separate integration suites below.


## Embedded EXIF/XMP comparison adapter

Run `python3 -m unittest discover -s tests -p metadata_adapter_test.py -v` in the
same app Docker image with the checkout mounted read-only. Thirteen tests include real
ExifTool writes/reads of generated JPEG and TIFF files, qualified tag isolation,
unchanged original evidence, numeric-looking text, linked capture-date components,
unknown zones/precision, explicit blank/partial XMP precedence, invalid input refusal,
exact decimal normalization and detached arrays/localized values. ExifTool is required.

The existing flat Index capture is not an input. Index uses a separate qualified
observation phase; live organization and write operations have separate integration suites below.

## Index metadata observations

Run `python3 -m unittest discover -s tests -p metadata_index_test.py -v` in the same
Docker image with this checkout mounted read-only. Generated cases run actual Index,
re-index and Copy jobs: qualified EXIF/embedded-XMP/sidecar priority, blank/partial values,
unchanged filing/bytes, sidecar-only changes, repeat no-ops, full-name alternatives,
malformed and unsafe sidecars, sibling ambiguity outside selection/extension filters,
transaction rollback, cancellation between complete observations, re-index after cancellation,
immutable observations and backup restoration/concurrent arrivals.
The suite also checks descriptor safety, changed-photo refusal and cache/force behavior.

Schema 24 adds `metadata_captures` and the snapshot's metadata-capture watermark.
Older development catalogs are refused. The phase records proposals only; it does not
activate filing metadata, expose source tabs, or carry sidecars in Copy/Move.
Catalog-only explicit choices are covered by the decision suite below.

## XMP reader and association planning

The helpers are independent of live Index/transfer jobs. Run in the app image with the
checkout mounted, substituting your own image tag:

```sh
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app:ro -w /app \
  negativespace python3 -m unittest discover -s tests -p xmp_test.py -v
```

40 tests use generated XML and isolated temporary files, including a sidecar produced
by the bundled ExifTool. Coverage includes absent/empty values, qualified/unknown tags,
arrays/localized values, original encoding/bytes, DTD/entity refusal, resource ceilings,
malformed/unsupported content, traversal and symlinks, special files, permission failures,
file/directory changes during reads, full-name/shared ownership, policy ambiguity,
orphans and tentative primary precedence. The 11 `metadata_test.py` tests separately
cover resolution. These suites do not establish XMP catalog durability or transfer
safety: storage and normal single-sidecar transfers have separate suites below. No photo samples or running app are used.


The reader suite also validates partial/full dates, leap days, clock/offset bounds,
orientation 1–8 and decimal ratings (-1 or 0–5), without rewriting lexical values or
filling missing dates/time zones. Explicit blanks remain distinct from absent fields.
Invalid values cannot supply a usable source. Two independent compatibility tests use
ExifTool to read our generated UTF-8/UTF-16 packets and generate packets our reader
checks; they cover all eight orientations and four ratings, including a fractional one.
ExifTool must be available; these checks fail rather than silently skip without it.
They compare actual metadata and preserved bytes, not just successful process exits.
This is interoperability coverage, not a complete standards-conformance lint.


## XMP storage and catalog backup validation

Schema 26 requires a fresh generated catalog. `xmp_store_test.py` covers compressed/raw
round trips, unknown encodings, corrupt/oversized frames, separate arrivals over shared
content, immutable lineage, transaction/savepoint rollback, request-like replay binding,
bounded damaged/invalid-value originals (attention-only), metadata queries without decoding, backup round trips, corrupt
backup refusal, arrival watermarks and XMP-only post-job backups.

```sh
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app:ro -w /app \
  negativespace python3 -m unittest discover -s tests -p xmp_store_test.py -v
```

The reader suite now creates a sparse 5 GiB `.xmp` and proves its contents are never read
or changed. This uses negligible disk allocation and no real photo files. The codec
benchmark and its limitations are documented in `docs/xmp-storage-measurements.md`.
Run database/API and engine smoke regressions when changing these catalog/backup paths;
enable the public RAW samples for smoke validation. XMP decision and retry controls
are not available in the browser yet; normal CLI single-sidecar imports are covered below.


## Generated JPEG content fingerprint experiment

The standalone prototype is not used by Index or duplicate cleanup. Its 20 generated
fixture tests run in CI and need no demo/library access. Run in your own app image:

```sh
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app:ro -w /app \
  negativespace python3 -m unittest discover -s tests -p jpeg_content_hash_test.py -v

docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app:ro -w /app \
  negativespace python3 tools/benchmark-jpeg-content.py --repeats 7
```

The tests use real ExifTool edits and independent Pillow decoding, including baseline
and progressive JPEGs, orientation/profile changes, quantization-table-only changes,
restart markers, custom extensions and unsupported/truncated input. They do not prove
complete JPEG conformance, metadata restoration or safe consolidation. Measured results
and exact coverage are in [the experiment report](../docs/jpeg-content-hash-experiment.md).


## Saved metadata decisions

Run `python3 -m unittest discover -s tests -p metadata_decisions_test.py -v` in the app
Docker image with this checkout mounted read-only. Generated actual jobs cover explicit
ownership, frozen job settings, preserved primary versions, stale/tampered choices,
request replay/conflicts, active-job refusal, atomic rollback, immutable decisions,
backup watermarks and held photo/XMP pairs during direct Copy/Move and duplicate cleanup.
Schema 25 adds decisions and their backup watermark; use a fresh development catalog.
Decision UI/API remains pending. Index tests assert that a resolved pair uses captured
XMP filing, while unresolved/duplicate cases remain held.


## Field-scoped edit planning

Run `python3 -m unittest discover -s tests -p metadata_edits_test.py -v` in the same
Docker image with this checkout mounted read-only. Generated tests cover minimal first
XMP, untouched fallback fields, established primary precedence, blank/partial dates,
linked EXIF date components, no incidental refile on Orientation, invalid/unsupported
requests and catalog-bound read-only previews. ExifTool independently reads generated
XMP and applies planned date tags to a temporary JPEG; original bytes, camera/caption/GPS
and decoded pixels remain unchanged. No user files, existing demos or edit API are used.
This validates planning/interoperability, not safe production publication or recovery.


## Photo/XMP pair transfer primitive

Run `python3 -m unittest discover -s tests -p metadata_transfer_test.py -v` in the app
Docker image with this checkout mounted read-only. The generated catalog/photo fixtures
exercise real Copy/Move filesystem work through the internal engine primitive, source
preservation, shared-owner cleanup, identical/differing destination XMP, orphan detection,
paired filename suffixes, symlink/path refusal, FULL transaction enforcement, crash
boundaries, retry/replay and pair-aware startup recovery. Tests inject disk/fsync/catalog
failures and process-like interruptions; they do not alter a sample library or demo.

Normal CLI jobs support resolved first imports, including multiple sidecars; unresolved choices stay
held. Recorded-pair Rename/Reject/Return is tested separately. Pair issue/retry UI is not exposed.
Passing this suite does not establish the complete import/edit lifecycle or hardware
power-loss behavior. No new public flags or schema version accompany the primitive.

## Photo/XMP destination relocation

Run `python3 -m unittest discover -s tests -p metadata_relocate_test.py -v` in the app
Docker image with this checkout mounted read-only. Generated photos and XMP are delivered
using the internal pair primitive, then exercised through Rename, Reject and Return.
Checks cover exact bytes, retained photo identity, unchanged import sources, collision
suffixes, orphan/unrecorded/missing sidecars, symlinks, hard-link fallback, no overwrite,
publication/cleanup crashes, directory and catalog barriers, cancellation, stale catalog
state and retry history. Recovery never accepts a photo-only result. Check it now must
not remove either old name, and explicit retry must reuse the originally intended names.
Also run `metadata_transfer_test.py`, `attention_test.py`, `webui_api_test.py` and the full
engine smoke suite (including public RAW fixtures) when changing this lifecycle.
These simulated failures do not prove hardware power-loss behavior. No UI walkthrough
is required for this engine-only primitive; the web decision/retry workflow remains unbuilt.

## Normal single-sidecar import and activation

Run `python3 -m unittest discover -s tests -p metadata_import_test.py -v` in the app
Docker image. Generated jobs verify XMP date filing, explicit EXIF choice, missing versus
blank/partial dates, timezone calendar-day preservation, unchanged source/sidecar bytes,
Copy then Move, shared owners, collisions, existing-photo refusal, sidecar space estimates,
per-pair cancellation, source-directory durability, failed publication/retry and forced
reindex after Rename. Activation and initial decisions appear only after verified transfer.
This suite covers the single-sidecar import path. Resolved multiple-sidecar imports,
incoming metadata choices and metadata edits are implemented and covered by the dedicated
suites below; unresolved choices remain held. Web retry eligibility/counts and
source/decision controls still need a separate implementation and browser walkthrough
before those controls are released.

### Common-field construction and incoming XMP alternatives

Run these with the checkout mounted read-only in your own app Docker image:

```sh
python3 -m unittest discover -s tests -p metadata_common_fields_test.py -v
python3 -m unittest discover -s tests -p metadata_writer_test.py -v
python3 -m unittest discover -s tests -p metadata_incoming_test.py -v
```

Common-field tests use generated XMP and independent ExifTool reads for title, caption,
keywords, ordered creators, rights, ratings, date, orientation and linked GPS. They cover
explicit clears, partial GPS without fallback, decimal precision, invalid types/XML,
language alternatives and namespace-prefix conflicts. Writer tests preserve unknown
properties/comments and prove a no-op keeps the original bytes. These are construction
and preview tests, not proof of file edit execution or embedded RAW write support.

Incoming-version tests run real generated Index/Copy/Move jobs. They cover different and
identical versions, no-current-XMP choices, Rejects, separate activation requirements,
request replay, stale targets, corrupt retained photos/BLOBs, source changes, cleanup
failure/retry, preserved origin names and duplicate Copy counts. No demo or real-library
files are required. Run the metadata and XMP suites together with database/API and full
engine smoke regressions after changing these integration points. Public RAW fixtures
remain read-only and enable both RAW smoke checks.


## Verified XMP edits and primary activation

Run `python3 -m unittest discover -s tests -p metadata_save_test.py -v` in the app
image, with the checkout mounted read-only. Generated catalogs exercise actual CLI
preview/apply/retry/discard, request replay/conflicts, frozen settings, common-field
publication, field donor provenance, deliberate retained-XMP primary activation,
no-op timestamps, date/Undated pair refiling, Reject/Return, force reindex, exact originals
in restored backups, orphan/symlink refusal, collisions, storage failures, interrupted
publication, partial staging files, failed refiling and explicit abandonment guards.
These checks do not certify embedded photo writing or the future metadata UI.

The engine accepts a bounded JSON object on stdin. `--metadata preview` changes no files;
use the usual configured `--base` and `--dest`. For example:

```json
{"edits":[{"photo_id":1,"capture_id":1,"changes":{"title":"Example title"}}]}
```

The response contains `previews`, including each `token`, target and filing change.
For `--metadata apply --request-id UNIQUE_ID`, send the same edit entry with its confirmed
`token` added. IDs and token must come from that catalog; examples are shapes, not a
ready-made confirmation. A different primary or a changed capture/settings invalidates
the preview. The engine accepts XMP sidecars and qualified embedded JPEG targets; unsupported
formats or representations are refused without silently selecting another primary.

To remove mapped fields instead of writing empty values, provide `remove_fields`:

```json
{"edits":[{"photo_id":1,"capture_id":1,"changes":{},"remove_fields":["date_taken","orientation"]}]}
```

Preview and confirm with the same token flow. Independent fields may be supplied in
`changes`; a field cannot be both set and removed. Removing a date removes its linked
fraction/offset and previews refiling. Removal affects only the established primary;
XMP fallback remains visible in the preview. It is not a general metadata/privacy scrub.
`metadata_writer_limits_test.py` qualifies JPEG EXIF mapped-field removals, unrelated
header/property preservation, actual removal read-back, no-op behavior, CLI history and
refiling, refusal boundaries, and sidecar plans for non-JPEG formats. It runs in CI.
The agreed release limits are in `docs/xmp-metadata.md` → Release writer boundaries.

To copy explicit fields, add `copy_fields` and omit those fields from `changes`:

```json
{"edits":[{"photo_id":1,"capture_id":1,"changes":{},"copy_fields":{"date_taken":{"photo_id":2,"capture_id":2,"source_id":"exif"}}}]}
```

A donor may instead use `{"photo_id":2,"version_id":3}` for retained associated XMP.
An absent donor value is refused; an explicitly empty value is copied as empty. The
write target remains the selected photo's established primary.

To compose a base version with explicit overrides, add `base` using either donor shape:

```json
{"edits":[{"photo_id":1,"capture_id":1,"base":{"photo_id":2,"version_id":3},"changes":{"title":"Chosen title"},"copy_fields":{"date_taken":{"photo_id":2,"capture_id":2,"source_id":"exif"}}}]}
```

For the base without overrides, supply empty `changes` and `copy_fields` objects. Present
supported base fields are copied; absent fields stay unchanged, while explicit empties
clear the supported field. The preview lists absent base fields and each final value's
origin. Unknown base properties are not transplanted, and the established primary remains
the write target. Apply uses the same preview/token flow above.
`metadata_composition_test.py` exercises actual sidecar and embedded JPEG saves,
base/override/typed provenance, no-op preservation, explicit blanks/absence, linked fields,
unknown target-property preservation, invalid donors, stale provenance and request replay.
It runs in CI with the other metadata suites.

To reproduce this photo's supported source metadata, select its historical capture:

```json
{"edits":[{"photo_id":1,"capture_id":5,"reproduce":{"capture_id":1}}]}
```

The outer `capture_id` binds current edit evidence; the inner one selects the historical
observation. Alternatively use `"reproduce":{"before_operation_id":42}` for the state
before a completed metadata edit. Preview first, then add the token for Apply as above.
The request targets the current primary, retains history and records a new operation.
Preview distinguishes absent fields/removals from explicit blanks and includes filing.
The original source may be gone, but the organized image must still verify. Hash changes
require a verified image-preserving edit chain; this cannot recover missing pixels.
Unsupported value representations or fallback that would refill historical absences
refuse the complete request. Mapped-field removal is qualified for sidecars and embedded
JPEG EXIF/XMP.

`metadata_reproduce_test.py` covers real source/pre-edit reapplication, absent/blank dates,
linked-field removal, history/identity checks, missing sources versus missing destination
images, embedded history chains, stale previews, retries, no-op history and CLI replay.
Run it in the same Docker environment as the other metadata suites; it is also in CI.

A deliberate whole-XMP primary change is a different entry shape:

```json
{"edits":[{"photo_id":1,"capture_id":1,"version_id":3}]}
```

Preview it first, then add that preview token for Apply. The version must have a confirmed
association with the photo. The selected exact packet becomes primary only after verified
publication; earlier versions remain in lineage. This entry shape is Library-only;
confirmed incoming decisions use the separate shape below, including Rejects.

For `--metadata retry` or `--metadata discard`, with a new request ID:

```json
{"operation_ids":[123]}
```

Retry resumes the saved intent and frozen settings. Discard requires an unchanged original;
it cannot undo saved metadata or abandon a required date move. Both run under the engine
lock. All prepared edits in a batch are archived before one verified pre-action backup;
shared unsafe storage failures stop later publications while completed edits remain saved.
UI routes and non-JPEG embedded writers remain unfinished. Incoming choices use the
verified engine entry point described below.

For production metadata/backup costs without photos, run
`python3 tools/benchmark-xmp-storage.py --catalog-versions 200000` in the same image.
The command uses generated temporary data and prints aggregate JSON; measured scope and
results are in [xmp-storage-measurements.md](../docs/xmp-storage-measurements.md).


## Embedded JPEG working-copy verification

Run `python3 -m unittest discover -s tests -p metadata_embedded_test.py -v` inside the
app image with a read-only checkout. Fixtures are generated JPEGs; no real-photo source
or writable Library mount is required. The suite exercises real ExifTool writes,
independent read-back, baseline/progressive JPEGs, ICC bytes, EXIF date companions,
common fields, XMP unknown-property preservation, no-ops, permissions, path refusal,
storage failure and changed-input cleanup. Injected lying/corrupt writers must fail
verification without changing the original. Oversized output and stalled subprocesses
must be stopped. These tests qualify the staging helper, not Library publication,
content/cache updates, TIFF/RAW editing or the future UI. Also run the metadata suites
when changing the shared edit planner.


## Embedded JPEG publication and recovery

Run `python3 -m unittest discover -s tests -p metadata_photo_save_test.py -v` in the app
image with the checkout mounted read-only. Generated fixtures cover CLI preview/apply,
request replay, new content/cache identity, original source preservation, date/Undated
refiling, unchanged inactive sidecars, no-op inode preservation, discarded unsaved edits,
unexpected path bytes, failed verification, interrupted publication and move-only retry.
Reindex both completed and unfinished edits; exercise Reject/Return, detached duplicate
sources and exact-result duplicate reporting without consolidation. Run all metadata,
XMP, database/API/recovery suites and engine smoke checks after shared catalog changes.
Public RAW smoke tests validate ordinary RAW import, not embedded RAW editing.


## Photo-only priority and embedded-primary switching

Run `python3 -m unittest discover -s tests -p metadata_primary_test.py -v` in the app
image with a read-only checkout. Generated JPEGs carry conflicting EXIF, embedded XMP
and optional sidecars. Check default/explicit priority, blank/partial dates, unchanged
photo/sidecar bytes, source switching after editing, failed refiles and move-only retry,
Copy-to-Move, forced reindex, changing destination, collisions, interrupted activation
and CLI replay. No embedded RAW writing or UI is exercised.

An embedded-source switch has this entry shape (preview first, then add its token for Apply):

```json
{"edits":[{"photo_id":1,"capture_id":1,"primary_id":"exif"}]}
```

Use `embedded_xmp` for an existing embedded XMP source. Neither form rewrites tags.
Also run the existing API permission-failure/retry test and engine smoke recovery checks:
a failed metadata read must still be reported as a failed transfer with its actual reason.


## Multiple-sidecar first imports

Run `python3 -m unittest discover -s tests -p metadata_multi_import_test.py -v` inside
the app image with a read-only checkout. Generated fixtures cover full-name priority,
explicit alternate choices, equally specific conflicts, identical-content reuse with
separate arrivals, damaged packets, all-owner association, partial Moves across jobs,
replacement owner identities, corrupt BLOBs, changed/missing sources, interrupted cleanup,
directory-barrier retry, primary switches and known alternatives arriving again.

Assert exact original bytes and a retention notice, not just file counts. Only the selected
packet belongs beside the destination photo; alternatives remain in catalog lineage.
Pair evidence and every original must verify before any source deletion. Recovery must
leave unfinished cleanup for an explicit retry. Also run the existing metadata transfer,
Index/decision, incoming, database/API/XMP suites and engine smoke tests for shared-path changes.


## Apply incoming metadata and Return choices

Run `python3 -m unittest discover -s tests -p metadata_incoming_apply_test.py -q` inside
the app image with a read-only checkout. Generated fixtures cover all combinations of
Keep current/Use incoming and stay in Rejects/Return; new and existing sidecars; exact
original retention; late sidecars on an already Copied source; repeated Copy then Move;
stale decisions/captures/identities and frozen decision watermarks; occupied/orphan/symlink
targets; corrupt inactive archives; cancellation, backup failure, interrupted Return and
read-only checks. CLI tests cover request replay and invalid entry shapes.

First use `metadata_incoming.preview` and `metadata_incoming.confirm` to record the
combined choice. These are catalog helpers, not web routes. Then pass the confirmed
incoming decision identity, the **retained photo's** ID and its latest capture to the
existing `--metadata preview` JSON interface:

```json
{"edits":[{"photo_id":1,"capture_id":4,"incoming_decision_id":7}]}
```

For `--metadata apply`, add the returned token to that entry and supply a new job request
ID. Retry/Discard uses the usual operation-ID request. Application changes no incoming
source files; run Copy/Move separately when desired. Verify that the decision receipt
appears only after successful publication/filing, Rejects never returns implicitly,
photo bytes remain identical and all original XMP versions remain retrievable. Reuse
existing metadata-save, incoming-preservation, relocation and smoke checks for shared
paths. Save full logs locally and report totals/failures, not every passing test.

### Move after an embedded edit (engine only)

`metadata_source_cleanup_test.py` uses generated photos to check one-job consent,
source/destination and image-history verification, backup/fsync refusal, sidecar
archives/shared owners, request replay, changed-file refusal and interrupted retry.
It also checks that unconfirmed edited sources stay while other photos move, and
filename-only changes need no extra confirmation. Run it with the standard Docker
unittest command above; it is included in engine CI.

For engine integration, `--metadata source-cleanup-preview` reads
`{"photo_ids":[1,2]}` from stdin and reports affected files under the configured roots.
The preview changes nothing. A deliberate `--move --confirm-edited-sources
--request-id <new-id>` confirms edited-source removal for that job's normal selection;
Copy rejects the flag. Use generated fixtures, inspect retained bytes/history and
remaining source names, and verify that omitting the flag preserves edited originals.
The web confirmation remains a separate implementation; no manual UI validation is
required for this engine-only change.

### Metadata UI acceptance still pending

The metadata engine has automated generated-fixture coverage, including verified saves,
date refiling, recovery and job-confirmed source cleanup. **Full user validation remains
pending implementation of the metadata API and UI.** Command-line test reruns do not
replace that walkthrough. Validate source choice, editing previews, save/recovery feedback
and the Move confirmation through the eventual screens before claiming end-to-end UX
acceptance. No metadata screens were implemented as part of this engine delivery.

### Combined metadata and navigation schema

Schema 28 includes both metadata provenance and notification read receipts. The database
contract suite checks the combined tables and receipts, and verifies that schema-26/27
catalogs are refused without modification. The filter-pin API and recovery browser
suites cover File issues in the shared sidebar, including pin exclusivity, counts,
refresh and recovery. Local integration validation passed 195 database/API tests and
six browser workflows: main UI, filters, notifications, review, file-issue recovery and
externally removed copied originals. GitHub runs the complete combined suite before merge.

### First metadata UI acceptance — planned, not yet run

The agreed first web editor changes only Date taken; broad metadata viewing does not
imply general field editing. When the API/screens exist, validate:

- Separate sidecar XMP, embedded XMP and EXIF fixtures; mixed/conflicting sources and
  alternate versions. Primary remains visibly identified when another tab is selected.
- Compare with primary and differences-only show the two captured values; explicit
  Empty and absent Not recorded remain distinct. Read/request failures expose recovery.
- Viewing, tab changes and comparison do not change bytes, primary, paths or history.
- Date copying/manual edits preserve untouched fields and date companions, never
  prefill missing XMP from fallback values, and clearly preview clears and destinations.
- Unsupported writer values cannot save or trigger an automatic primary switch. Save
  uses one confirmation for the date and any refiling; failures retain actionable details.
- Keyboard tabs, focus, stable layout, both themes and desktop zoom follow shared checks.

This checklist is future acceptance work, not a claim of implemented controls or passing
browser tests. Saved rotation and general composition remain separate scope. Reconcile
this record with the specs, TODO and private handoff before the next merge.
