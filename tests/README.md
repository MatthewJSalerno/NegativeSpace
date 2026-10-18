# Tests

Everything here is for developing NegativeSpace; running the engine needs none of it.
## Manual validation instructions

- Number tests and letter their steps so results can refer to a specific check.
  Refer to these identifiers (for example Test 3a), never document line numbers.
- For every photo-specific check, supply a searchable filename verified in the current
  test catalog, its location (for example Library or Not organized), the expected
  starting state and the expected result. Add a date or other identifier if names repeat.
- A source path or a description such as "an EXIF-primary photo" is not sufficient.
  If the required fixture is absent, say so and arrange it before asking for validation.
- State when a Settings-only check needs no photo. List only remaining checks; preserve
  accepted results unless a relevant change requires a specific retest.
- Keep private sample filenames in the direct validation message or private handoff;
  tracked checklists use generated fixture names and aggregate results.

## CI coverage

CI coverage is split between two workflows:

- **Every pull request, push to `main`, and manual Engine tests run**:
  `.github/workflows/engine-tests.yml` runs all 45 Python unit suites
  (`tests/*_test.py`, except the separately invoked engine smoke suite), the engine
  smoke suite, the three shell suites, all `tools/check-*.py`, synthetic similarity
  validation, container CPU/timezone/CLI checks, and the browser drivers listed below.
  `filter_pins_test.py` and `notifications_test.py` use `PYTHONPATH=/app/tests:/app`.
  RAW smoke tests require the optional read-only public samples locally; GitHub has
  no such samples and reports those two skips.
- **Nightly at 05:37 UTC and manual Extended browser tests runs**:
  `.github/workflows/extended-browser-tests.yml` runs the ten extended drivers below.
  They do not add runtime to the PR gate. The nightly schedule starts once the
  workflow is on the default branch. After merge, use Actions → Extended browser
  tests → Run workflow to select a branch for a manual run.

All browser entries below are in `tests/browser/`, use `webui_browser_test.sh`, and
build isolated catalogs from generated photos. Set `DRIVER` to the filename; the
fixture flags are required where shown. Each browser job builds the app, web and browser-test images.
CI sets `PLAYWRIGHT_IMAGE` to the browser-test image, installing the matching
Playwright package once per job. Standalone harness runs still install it unless
you supply a prebuilt `PLAYWRIGHT_IMAGE`; catalogs and containers remain isolated.

| Browser driver | CI schedule | Additional environment |
| --- | --- | --- |
| `access_browser_drive.py` | PR / main / manual | — |
| `appearance_browser_drive.py` | PR / main / manual | — |
| `attention_browser_drive.py` | PR / main / manual | `SIMILARITY_RECOVERY_FIXTURE=1` |
| `copied_source_browser_drive.py` | PR / main / manual | — |
| `filter_pins_browser_drive.py` | PR / main / manual | — |
| `fresh_start_browser_drive.py` | PR / main / manual | — |
| `gallery_position_browser_drive.py` | PR / main / manual | — |
| `metadata_dates_browser_drive.py` | PR / main / manual | `METADATA_VIEW_FIXTURE=1` |
| `metadata_settings_browser_drive.py` | PR / main / manual | `METADATA_SETTINGS_FIXTURE=1` |
| `pair_retry_browser_drive.py` | PR / main / manual | `PAIR_RETRY_FIXTURE=1` |
| `move_confirmation_browser_drive.py` | PR / main / manual | `MOVE_CONFIRMATION_FIXTURE=1` |
| `metadata_sources_browser_drive.py` | PR / main / manual | `METADATA_VIEW_FIXTURE=1` |
| `notifications_browser_drive.py` | PR / main / manual | — |
| `preview_refresh_browser_drive.py` | PR / main / manual | — |
| `reject_similar_browser_drive.py` | PR / main / manual | — |
| `rejects_browser_drive.py` | PR / main / manual | — |
| `request_freshness_browser_drive.py` | PR / main / manual | — |
| `review_browser_drive.py` | PR / main / manual | — |
| `similar_browser_drive.py` | PR / main / manual | — |
| `source_scope_browser_drive.py` | PR / main / manual | — |
| `stalled_job_browser_drive.py` | PR / main / manual | `STALLED_FIXTURE=1` |
| `suspicious_dates_browser_drive.py` | PR / main / manual | `SIMILARITY_RECOVERY_FIXTURE=1` |
| `thumbnails_browser_drive.py` | PR / main / manual | — |
| `webui_browser_drive.py` | PR / main / manual | — |
| `navigation_browser_drive.py` | Nightly / manual | — |
| `layout_stability_browser_drive.py` | Nightly / manual | — |
| `date_settings_browser_drive.py` | Nightly / manual | — |
| `cross_location_browser_drive.py` | Nightly / manual | — |
| `transfer_outcome_browser_drive.py` | Nightly / manual | — |
| `large_selection_browser_drive.py` | Nightly / manual | `SIMILARITY_RECOVERY_FIXTURE=1` |
| `reference_sets_browser_drive.py` | Nightly / manual | `SIMILARITY_RECOVERY_FIXTURE=1` |
| `similarity_recovery_browser_drive.py` | Nightly / manual | `SIMILARITY_RECOVERY_FIXTURE=1` |
| `submission_browser_drive.py` | Nightly / manual | `SUBMISSION_FIXTURE=1` |
| `safety_questions_browser_drive.py` | Nightly / manual | `NETWORK_FIXTURE=1` |

`ui_browser_drive.py` is a developer shortcut for `ui_browser_checks.py`. The default
`webui_browser_drive.py` already calls those checks, so CI does not invoke the shortcut
again. `metadata_scenarios_browser_drive.py` is a read-only acceptance tool for an
indexed/copied scenario library and its manifest; it is run manually, outside CI.
Helpers and engine fixture wrappers are not standalone suites. Same-named tests
in different modules cover different contracts and remain in place.


PR/main CI runs four independent jobs: engine smoke tests, metadata tests,
other Python/contract tests, and browser tests. Each has a 30-minute budget;
individual test timeouts and assertions are unchanged. The existing required check,
**Smoke suite (in container)**, is now a final gate: every group must succeed,
including when another group fails, is skipped, or is cancelled. Do not require
only one of the four groups in branch protection. New suites must be added to the
appropriate group. Superseded runs on the same PR are cancelled; main and manual
runs are independent. The ten nightly/manual drivers keep their existing schedule.

Before this split, successful GitHub run `38505467509` took 26m15s: engine smoke
7m49s, browser/shell shutdown checks 5m28s, other checks 12m19s, and builds 36s
(step timestamps, rounded to seconds). Parallel jobs reduce elapsed waiting, not
the amount of test coverage. First parallel run `38590119552` passed every group
and the required gate in **12m26s** (first job start to final gate completion),
versus **26m15s** serial: about **53% less elapsed time**. Group durations were:

| Group | Duration |
| --- | --- |
| Engine smoke | 11m44s |
| Metadata | 12m19s |
| Other Python/contracts | 8m00s |
| Browser | 7m13s |
| Final gate | 4s |

Combined job time was 39m20s rather than 26m15s. Hosted runner speeds vary; this
is one measured comparison, not a guaranteed runtime or compute saving. Each group
builds its own images; browser dependencies are installed once per browser job.
No test commands or assertions were dropped. The Stats WAL-size race that failed
the previous main run is covered by a new API regression: the old implementation
fails deterministically, while the fixed implementation and browser check pass.
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
| `move_confirmation_browser_drive.py` | `MOVE_CONFIRMATION_FIXTURE=1` | All Move entry points, edited-original consent, stale preview, preserved bytes and verified removal |
| `stalled_job_browser_drive.py` | `STALLED_FIXTURE=1` | Real stalled generated decoder, no-progress reminder, Keep waiting, explicit cancellation and lock release |
| `request_freshness_browser_drive.py` | | One initial Stats/log/facet request, refresh after a real job, retained Stats border/spacing in both themes and desktop reflow |
| `appearance_browser_drive.py` | | Palettes, explicit/system modes, contrast, cross-tab storage, shared page tools and narrow controls |
| `date_settings_browser_drive.py` | | Setup year choice, settings validation/persistence, immediate filter and Inspector updates |
| `thumbnails_browser_drive.py` | | Settings › Performance thumbnail cache: sizes by kind, Free up, Repair as a job followed in the panel, the Stats link, reflow |
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

The entrypoint and shutdown harnesses run on the host to start and inspect Docker
containers. The sampler safety suite uses only generated fixtures and may run in the
app image (CI invokes its portable shell script on the runner):

```bash
docker run --rm --entrypoint sh -v "$PWD":/app:ro -w /app negativespace tests/sampler_test.sh
docker build -f docker/app.Dockerfile -t negativespace . && sh tests/entrypoint_test.sh   # the entrypoint's ownership handling
sh tests/shutdown_test.sh      # docker stop with a browser tab open: clean, and the app's shutdown runs
```

The entrypoint and shutdown harnesses accept `IMAGE`, `NS_TEST_OUTPUT_ROOT`,
`NS_TEST_DESTINATION_ROOT`, and `NS_TEST_KEEP=1`, as the browser harness does. Create
output/destination parent folders before running. The destination gets its own
subfolder; retaining fixtures still stops the shutdown test's containers and network.
Leave the variables unset for the usual temporary-fixture cleanup on CI.

## Spec and schema checks — `tools/`

Not tests of the engine, but CI gates on them and they exit non-zero on failure:

```bash
docker run --rm --entrypoint python3 -v "$PWD":/app:ro -w /app negativespace tools/check-specs.py
                                      # cross-references resolve, fences balance, tables are whole
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

Manual UI checks: switch All photos / Has similar photos / No usable capture date and
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
percentage. Search/date/type filters narrow references, not their counted
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
not an image, a sidecar, a symlink, an unreadable file, a deep folder). It also makes the
cases a real library on a NAS brings:

| Folder | Cases |
| :--- | :--- |
| `nas-share/` | Synology's `@eaDir/` thumbnails and `#recycle/` (no leading dot), QNAP's `.@__thumb/` |
| `live-photo/` | a Live Photo's HEIC and its `.MOV`; motion photos (a JPEG with its video after the picture) in Google Camera's older MVIMG form, the Pixel's Motion Photo 1.0 and Samsung's, each read by ExifTool as its phone wrote it (the videos are stand-ins) |
| `date-in-name/` | no EXIF, a file time in 2011, and a date only in the name (`IMG_20190615_…`, WhatsApp, Pixel, Samsung, a screenshot) |
| `clock-off-by-a-year/` | one trip from a camera a year early and a phone that was right |
| `day-boundary/`, `burst/` | 23:30 at +09:00 and at −05:00, midnight; five frames in one second, told apart only by sub-seconds |
| `look-alikes/` | an original rotated in its pixels, cropped, black-and-white, colour-graded, watermarked |
| `formats/` | 96 and 200 megapixels (past Pillow's decompression limits), 16-bit PNG, CMYK JPEG, multi-page TIFF, animated GIF, progressive JPEG |
| `unicode-names/`, `case-at-destination/` | one name in NFC and NFD; names differing only in case, one day, two folders |
| `edge/locked-folder/` | a folder the Index cannot open |

To find a scenario's file in the app, search its name: every scenario file whose name
is not itself the case starts `scn-` and a word for its scenario (`scn-burst-3.jpg`,
`scn-format-cmyk.jpg`, `scn-date-no-date-…`), and no two share a name. The exceptions
are the name cases themselves (collisions, case, Unicode, dates in names) and the NAS's
own thumbnail names, which sit in a folder named after the photo they show.

Where the app's answer is not decided yet, the manifest entry says so in
`open_question` (the NAS folders, a Live Photo's video, dates in names, sub-seconds,
crops and rotations, the 200-megapixel picture, normalized or case-insensitive
destinations). `change` then
applies one round of every kind of change (edited in place, touched, renamed, moved,
deleted, replaced, new duplicates, a new date taken, and with `--dest` a destination
copy deleted, altered and a stranger added, and two photos coming back to the source:
one whose original a Move removed and one in Rejects), which is what gives a photo's
lineage something to show. `OUT/manifest.json` lists every file, its scenario and what
the app should show for it. Without `--seed-dir` the photos are generated.

`--exif-donors` names a folder of camera files kept for their metadata, such as
[ExifTool's sample images](https://exiftool.org/sample_images.html): real tags from
hundreds of cameras on pictures shrunk to a few pixels. About three in four seed JPEGs
with no EXIF date get one donor's tags (camera, lens, exposure, dates, GPS, maker notes,
damaged ones included) on a fresh copy; the rest stay without, for No usable capture date. The
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
seed filling during a build, refusals, the photos that come back, and the real engine's
Index checked against the manifest, including that an empty file and a text file named
`.jpg` are logged as **Not an image** and never filed, that a folder it cannot open is
recorded, and that every format and name case above is indexed. Open questions are not
asserted.

### Metadata scenarios — `make_metadata_scenarios.py`

For testing metadata reading, conflicts and sidecar association against cases a real
library rarely holds all of. `build` makes `OUT/library/<group>/<case>/`, one folder per
case. With `--seed-dir`, each case's photo is a copy of one of that folder's JPEGs, each
used once: its pixels kept, its own EXIF, XMP and IPTC wiped (its colour profile kept) and
the case's values written instead, so the manifest stays the whole truth. Photos with a
rotation tag are passed over while others remain, since without the tag they would lie on
their side. The seed folder is never written to, and the run ends by proving it. Without
`--seed-dir`, or once its JPEGs run out, the photos are drawn, each showing its case name:

| Group | Cases |
| :--- | :--- |
| `agree` | values only in EXIF, only in embedded XMP, only in a sidecar; all three the same; sources that complement each other |
| `conflict` | the date in EXIF vs sidecar, EXIF vs embedded XMP, embedded vs sidecar, all three apart; one instant in two time zones; month-only precision; a sidecar clearing a title; keywords, rating, orientation, GPS, camera, caption, title languages and creators that differ |
| `sidecar_names` | `photo.jpg.xmp`, `photo.xmp`, both disagreeing, `.XMP`, a name differing only in letter case, two photos sharing one stem, a declared owner (`crs:RawFileName`), an owner that is not there, an orphan, a sidecar in a subfolder, and with `--raw-dir` a RAW and JPEG sharing one sidecar |
| `sidecar_broken` | malformed, empty, binary, unrelated XML, an invalid date, rating and orientation, a repeated field, over the reader's size limit, unreadable, a symlink |
| `real_world` | forms real tools write: `rdf:about` as a UUID, keywords as `rdf:Seq`, a date only in `photoshop:DateCreated`, Lightroom's hierarchical keywords, UTF-16 and UTF-8 BOM sidecars, titles without `x-default`, a rejected rating (-1), Unicode keywords, IPTC-only keywords, a zeroed EXIF date, `CreateDate` only, a PNG with embedded XMP, a Google Takeout `.json`, an orientation already applied to the pixels, and motion photos (Google's older MVIMG, the Pixel's, Samsung's) with metadata and a disagreeing sidecar, the video's length and SHA-1 in the manifest so a test can prove a save kept it |

Every file is named after its case, so the gallery's filename search finds it:
`md-exif-only.jpg`, `md-date-three-way.jpg` and its sidecar `md-date-three-way.jpg.xmp`,
`md-shared-stem.jpg`/`.png`/`.xmp`. Search `md-` plus the case name with dashes. Motion
photos keep their phone-style names with the token added
(`PXL_20190615_120000123_md-motion-photo-pixel.MP.jpg`). In the sidecar-name cases the
token is part of the names being compared, so what each case tests is unchanged.

`OUT/manifest.json` is ground truth: for each photo what was written to each source
(`exif`, `embedded_xmp`, `iptc`), for each sidecar its values and the photo it was written
for. It also records **`engine_today`**: what this branch's own XMP reader and association
planner make of each sidecar (state, code, fields taken, whose it became). That is an
observation, not an expectation, so a gap shows as a gap; the build's last line counts
the sidecars the reader took.

```bash
mkdir -p /photos/demos
docker run --rm --user "$(id -u):$(id -g)" --entrypoint python3 \
  -v /photos:/photos -v "$PWD":/app -w /app negativespace \
  tools/make_metadata_scenarios.py build --out /photos/demos/metadata \
    [--seed-dir /photos/seed] [--raw-dir /photos/raw] [--replace] [--seed N]
```

Its test, `make_metadata_scenarios_test.py`, runs in CI: every value in every source of
every photo is read back with ExifTool, every valid sidecar with a plain XML parser, so
the manifest can be trusted without trusting the code under test. A seeded build is
checked the same way, and also that the seed folder is byte-identical afterwards, that each
photo is a different seed photo's pixels, and that none keeps the seed's own date, title or
keywords.

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
It also checks separate filtered-log exports, aligned search/date fields, and a stable
small-image minimum/hint/footer while reminders toggle On/Off in light/dark and narrow
layouts. The similarity driver checks that zoom/rotation/reset leave preview details
and Keep controls stationary, with position sliders disabled at 1×. The access driver
checks spacing/reflow in its nested confirmation. Set `SHOTS` to inspect the reserved
spacing. This covers routine filter transitions,
not intentional expansion of jobs, errors, Inspectors or similarity tools.

### UI alignment validation

These are new spot-checks; previously accepted metadata tests do not need repeating.

1. **Logs**
   - **1a.** Open Logs. CSV/JSON belong beside the heading under **Export filtered log**;
     the search and From/To fields have aligned edges.
   - **1b.** Choose **Failed → only**, then **All statuses**. Filters and job-list controls
     stay in position after the results settle. Export still follows the chosen filters.
2. **Settings**
   - **2a.** Open Settings → Files. Toggle Small-image reminders On, Off, then On.
     The minimum stays visible, disabled while Off; the explanation and controls below
     do not jump. Close Settings without saving to retain the original setting.
   - **2b.** Check the file-type input/Add file type row and the Backups tab: buttons and
     supporting text align and wrap without stretched buttons. No backup is needed.
3. **Comparison**
   - **3a.** In Library → Has similar photos, open any matching photo (search
     `scn-orientation` in the demo scenarios), choose Similar photos, then Review side
     by side. Change the reference zoom from 1× to 2×: position sliders enable without
     moving dimensions or Keep. Rotate, then Reset view: the same rows stay in place.
   - **3b.** The minimum-similarity/Refresh controls stay separate from the photo's
     Keep and Reject actions. Rotation/zoom apply only to the preview.
4. **Reflow**
   - **4a.** Repeat the visual checks in light/dark mode and at 200% browser zoom or a
     narrower desktop window. Controls may wrap; labels/buttons should not overlap or
     clip. Reference/candidate headings and previews align when displayed side by side.

5. **Files needing verification**
   - **5a.** In Library, confirm the renamed filter has a count (including zero).
     Choose it, then switch to Needs review: the same organized files/count appear.
   - **5b.** Pin Files needing verification. Visit Not organized, Source folders, and
     Needs attention: the filter and pin highlight are inactive, with no destination
     filter restricting source results. Return to Library or Needs review: the filter
     and pin return. Repeat with an unpinned Small images filter; its choice also returns.
     A source-page refresh keeps that remembered choice. Clear all filters cancels it.
     Shared search/date filters retain their existing behavior. Source import failures
     remain under Not organized → Needs attention. Zero is valid; do not create a failure.

Maintainer accepted alignment checks 1a–4a, verification check 5a, and revised
source-navigation check 5b. Manual validation is complete for this batch.

Automated source-filter checks passed: filter pins, file-attention recovery, and
cross-location browser workflows, plus the frontend build and all three contract
checks. Generated fixtures cover source entry points, refresh, pinned/unpinned
restoration, clearing/forgetting preferences, and exact cross-location search links.

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

Manual: in Library, click No usable capture date then Suspicious dates; only the latter stays
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

### Move after an embedded edit

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
The web confirmation now uses a read-only catalog snapshot followed by one explicit
job choice. `move_confirmation_test.py` runs in the standard Docker unittest form and
is included in PR CI: Include/Leave, preserved bytes/history, stale scope, engine-lock
recheck, request replay, live-file refusal, literal folder boundaries, Rejects and
safety-answer consent. `MOVE_CONFIRMATION_FIXTURE=1
DRIVER=move_confirmation_browser_drive.py sh tests/browser/webui_browser_test.sh` is
also in PR CI. This opt-in makes **only the harness's generated source** writable;
ordinary browser tests keep their source read-only. It exercises the real editor and
Move jobs, choice/reset, list, desktop/200%/narrow layout and verified source removal.

Maintainer validation: **M1, M2a–c and M3a–b passed (2026-10-14).** The M2c
feedback requests a clearly visible Refresh Move preview button; it uses the shared
filled primary style. During M3a the source original was verified to retain its
2019 EXIF date and the Library copy its 2021 date. A false missing-EXIF-date message
and unclear source/destination Inspector context were reported and corrected;
The maintainer passed the remaining checks after these corrections. The API and
Move browser regressions cover these cases.
Use a disposable generated source with a writable
mount for Move, never the shared sample library. The metadata scenario builder supplies
these searchable names; the EXIF-only case must use embedded JPEG writes, not a forced
new XMP sidecar. Keep the ordinary JPEG/XMP setting off for this check.

1. **Test M1 — setup and the job-level choice.**
   a. Complete setup, create the catalog, Scan/Index and Copy the generated library.
      Existing deliberately broken-sidecar cases can remain at source.
   b. In Library, search **md-exif-only.jpg**. Open Metadata → primary EXIF → Edit
      metadata date. Change the date from 2019 to **2020-06-15T12:00:00**, preview and save.
   c. Jobs → Move → Move all: verify one affected original, its expandable source name,
      the exact-original-bytes warning and disabled Move until Include/Leave is chosen.
   d. Choose Include, cancel, reopen: neither choice should be remembered. Check at
      200% and a narrow window; Cancel/Move must remain reachable. Cancel afterward.
2. **Test M2 — scope and stale confirmation (before moving files).**
   a. Select **md-exif-only.jpg** and choose Move. Verify the same choice, then cancel.
      Select it together with **md-embedded-xmp-only.jpg**, enter the Move review,
      then Move these photos: the confirmation should still identify only the edited
      original. Cancel and clear the selection.
   b. Source folders → Still in source: select the **exif_only** folder. Move this
      folder must offer the same edited original. Cancel.
   c. Open Move all. In another tab, change **md-exif-only.jpg** to
      **2021-06-15T12:00:00** and finish saving. Submit the older Move confirmation:
      it must refuse without moving photos. Refresh Move preview must require the
      Include/Leave choice again. Cancel afterward.
3. **Test M3 — Leave, then Include.**
   a. Jobs → Move → Move all, choose Leave these originals at source, then Move.
      Ordinary eligible photos move; deliberately broken/held fixtures may remain.
      **md-exif-only.jpg** must remain under Source folders → Still in source, and
      its edited Library copy must retain the 2021 date. Opening the source entry
      displays a notice that the Inspector shows the Library copy; it must not
      falsely claim that this edited EXIF has no date taken.
   b. Start Move all again: choose Include and confirm once. That original is removed
      only after verification; its edited Library copy and metadata history remain.
      Source folders must no longer list it as still in source. Check the job's log.
      Do not interpret the fixture library's intentionally broken files as a new failure.


### Metadata engine delivery and later UI acceptance

The metadata engine has automated generated-fixture coverage, including verified saves,
date refiling, recovery and job-confirmed source cleanup. The engine-only delivery did
not include screens. The later source viewer and Date taken editor have now passed
maintainer acceptance, including all numbered follow-ups below. Broader source-choice,
and recovery controls remain separate work. Edited-source Move confirmation is now built
and passed the M1–M3 walkthroughs above; broader source-choice and recovery controls
remain separate work.

### Combined metadata and navigation schema

Schema 28 includes both metadata provenance and notification read receipts. The database
contract suite checks the combined tables and receipts, and verifies that schema-26/27
catalogs are refused without modification. The filter-pin API and recovery browser
suites cover File issues in the shared sidebar, including pin exclusivity, counts,
refresh and recovery. Local integration validation passed 195 database/API tests and
six browser workflows: main UI, filters, notifications, review, file-issue recovery and
externally removed copied originals. GitHub runs the complete combined suite before merge.

### First metadata editing UI acceptance — passed

The agreed first web editor changes only Date taken; broad metadata viewing does not
imply general field editing. The date editor is built and accepted; coverage includes:

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

Read-only viewing, date editing and save checks passed maintainer acceptance, including
the final presentation follow-ups below. Saved rotation and general composition remain
separate scope.

### Read-only metadata source viewer

`metadata_view_test.py` checks capture-only versus verified primary, pending choices,
reindex after activation, source separation, explicit empties, unknown/oversized IDs,
content mismatch and unchanged catalog contents. Run with the standard Docker unittest
command. `METADATA_VIEW_FIXTURE=1 DRIVER=metadata_sources_browser_drive.py` uses the
browser harness's generated three-source photo to check real Index/Copy captures,
conflicting dates, Primary identity, comparison, field search, keyboard navigation,
light/dark reflow and failed-read retry. Both checks run in CI. The metadata test fixture
never reads the demo library. Date-copy/edit acceptance passed; future primary-change
controls still require their own implementation and acceptance.

The merged metadata scenario generator also passed all six tests unchanged. A build
with a public RAW sample produced 57 cases and 61 photos; the branch reader reported
37 valid, 10 needs-attention and 3 not-XMP results across 50 XMP sidecars. These include
intentional invalid inputs. Use the manifest's written values as expectations, not its
`engine_today` observations. This checks the generator and records reader behavior;
it does not establish that the viewer handles every scenario correctly.

Local generated-fixture validation for this viewer: 10 source-view API tests and the
98-test existing API regression suite passed in Docker. The source-view browser check
and full shared-UI/main browser walkthrough passed; light/dark and narrow screenshots
were inspected. Spec checks passed (476 section references, 51 API routes). Maintainer
visual acceptance of the source viewer is complete, including the scenario follow-up
below; these results do not claim validation of future date-editing controls.

### Metadata scenario viewer acceptance

After Index and Copy of the metadata scenario library, run
`tests/browser/metadata_scenarios_browser_drive.py BASE_URL MANIFEST` inside the
Playwright image, mounting the generated manifest read-only. The instance's source
must be mounted at `/data/source`. This driver reads an existing test catalog; it does
not create one or start jobs. Optional `SHOTS` saves rendered screenshots.

It checks 20 source-date values against the manifest's written values, then exercises
all-source agreement, a three-way date conflict, explicit empty versus absent values,
missing and malformed sidecars, and light/dark narrow reflow. It verifies all metadata
responses remain unchanged. Unsupported reader cases are not treated as passing support
simply because they appear in `engine_today`.

For manual acceptance, use Source folders to locate these generated cases, open Photo
information, and scroll to Metadata sources:

| Case | What to verify |
| --- | --- |
| `conflict/date_three_way` | Primary sidecar date is 2021; embedded XMP is 2020; EXIF is 2019. Compare on either alternative tab, then filter to date. |
| `agree/all_three_agree` | Embedded XMP compared with primary has no differing fields. Default-language wrapping alone is not a difference. |
| `conflict/sidecar_clears_title` | Primary title is Empty; embedded XMP has Beach day. |
| `agree/complementary` | EXIF has a date; the sidecar does not. Comparison says Not recorded; it does not fill the sidecar with EXIF data. |
| `agree/exif_only` | EXIF is Primary; the sidecar tab reports no metadata recorded. |
| `sidecar_broken/malformed_xml` | Remains Not organized; the sidecar tab explains the read problem and links to photo logs without crashing. |

Local validation: 61 photos indexed, 44 copied, 17 left at source with metadata holds.
The manifest browser check passed and all 61 metadata responses stayed unchanged.
The 12 source-view API tests passed. Screenshots inspected in light and dark/narrow
layouts. Maintainer acceptance is complete; date-editing controls remain unbuilt.

Maintainer acceptance: source tabs, primary identity, agreeing/conflicting values,
comparison/filtering, empty/missing values and layouts passed. The broken-sidecar
follow-up also passed maintainer acceptance: a visible Not organized card marker,
source file path, explanation and correction/reindex instructions at the top of Photo
information. Reindex-clearing and organized-photo exclusion have API coverage; the
scenario browser checks the marker and notice.

Source-attention follow-up validation: 13 metadata-view API tests and 98 existing API
regressions passed. The full scenario viewer browser check passed, including the
Not organized marker, visible sidecar path, explanation and photo-log link. Metadata
responses remained unchanged. Specs passed (476 references, 51 routes). The source
warning was visually inspected; the maintainer accepted the broken-sidecar recheck.
Read-only metadata viewer manual validation is complete.

### Source attention filtering

`metadata_view_test.py` covers the Needs attention union of failed source files and
latest metadata holds, deduplication, clearing after reindex, pagination, selection
IDs, position, facets, search and pin-aware counts. Source holds never enter Library
or its Needs review inbox. The scenario browser checks the summary shortcut clears
an unrelated search, URL refresh, pin restoration, unavailable-place behavior and
Clear all filters. Maintainer acceptance of this filtering follow-up passed.

Local validation passed: 14 metadata-view/filter API tests, 4 filter-pin tests and
98 existing API regressions. The scenario browser passed with 20 manifest date
assertions and all 61 metadata responses unchanged; the new filter was inspected
in light/dark themes and narrow reflow. Specification checks passed (476 section
references, 51 API routes). This does not claim a large-catalog performance benchmark.


### Date editor automation and manual walkthrough

Run `tests/metadata_dates_test.py` in the app image with unittest discovery. It uses
generated photos and actual engine jobs for preview/save/refile, unchanged sources,
request replay, stale preview refusal, first-sidecar creation and qualified JPEG EXIF.
Run `METADATA_VIEW_FIXTURE=1 DRIVER=metadata_dates_browser_drive.py sh tests/browser/webui_browser_test.sh`
with your own image tags. The generated browser fixture covers invalid dates, draft
retention/discard, responsive reflow, lost acceptance lookup, repeat editing, explicit
clear and same-photo donor copying. Both checks run in CI.

For maintainer acceptance, use disposable destination copies:

1. Open a Library photo, Metadata → Edit Date taken (or Photo information → Edit date).
   Verify the target and its own recorded date. Change a date; Cancel → Keep editing
   must preserve the draft, while Discard must leave the file unchanged.
2. Preview a different date. Check before/after values and current/resulting paths.
   Save once; wait for Date saved, then verify the date, folder and refreshed metadata.
3. On a nonprimary source with Date taken, choose Copy Date taken to primary.
   Preview its date and confirm primary stays the same; Save and inspect the result.
4. On an XMP target, explicitly clear the date. Preview must say Undated. After Save,
   the primary date is Empty, rather than silently borrowing the embedded date.
5. Reopen the editor. An unchanged date/location disables Save. Invalid calendar dates
   cannot preview; a qualified EXIF target refuses empty/partial values without switching.
6. Check light/dark, keyboard access and resized/zoomed layout. A draft must survive reflow.

The viewer PR's source-failure browser regression also follows the summary's Needs
attention shortcut, rather than the superseded direct Logs link.

Local date-editor validation: 431 metadata tests (including seven date API cases),
98 existing API tests, the generated date-editor browser workflow and the full main
browser walkthrough passed. Browser
checks include Back/Keep editing, width changes while a draft is open, and acceptance
lost after job submission. Light/dark desktop and narrow preview screenshots were
inspected. Spec checks passed for 475 section references and 54 API routes. Manual
date-editor and read-only viewer acceptance subsequently passed; see the numbered record below.


### Motion-photo metadata save preservation

`metadata_motion_save_test.py` builds the metadata scenarios with generated photos and
uses the manifest's `embedded_video` length and SHA-1 as independent expectations.
All three variants (Google legacy, Pixel and Samsung) are copied into isolated catalogs.
Actual engine sidecar date saves and refiling must preserve each extracted video exactly;
ExifTool reads it with `-b -ee` and the variant's qualified video tag. Source files must
remain unchanged. A negative control re-encodes a disposable copy and demonstrates that
the video assertion detects the loss.

Embedded EXIF and embedded XMP attempts currently **refuse**, with `metadata_saved=false`
and unchanged destination bytes/path/video. This is the documented JPEG trailer boundary,
not evidence of successful embedded motion-photo editing. Qualification of that behavior
requires separate engine work; the tests retain the refusal and never bypass it.
Run in the app image with unittest discovery; the suite also runs in CI. All four
tests passed locally: three successful sidecar saves/refiles, six nonmutating embedded
refusals, and a video-loss negative control for each variant.

Builder update validation: the unchanged metadata builder suite passed all 8 tests and
the demo builder suite all 10 tests, including its Index assertions. A separate seeded
library contains 60 cases, 64 photos (63 seeded JPEGs and one public RAW copy), including
three motion photos. The builder verified that every seed file stayed unchanged. This
library now backs a fresh validation demo: 47 organized photos and 17 intentional
source metadata holds. Earlier demo photo IDs no longer apply. No date edits were saved
during that preparation; maintainer date-editor acceptance subsequently passed. Expanded RAW, DNG,
TIFF, HEIC and extended-XMP cases remain planned in the builder owner's workstream.

Inspector refresh regression: the review browser workflow dispatches repeated review
updates and asserts one review section and Photo actions row. The source-view workflow separately
refreshes the Metadata tab and asserts one metadata section.
Sibling sections use distinct keys so refreshing does not leave orphan controls.

Viewer PR follow-up validation: all workflow steps passed locally, including 745
unit/API cases across 37 suites, 17 browser workflows, and 154 engine smoke cases
with the public RAW samples (zero skipped). The scenario builders passed 10 demo
and 8 metadata cases. Spec checks passed 476 references, schema drift and 51 routes.
The read-only viewer remains maintainer-accepted; date-editor acceptance is separate.

Date-editor usability checks: the date browser workflow changes a calendar day while
retaining fractional seconds/offset, verifies that clearing the picker is not a saved
clear, and exercises an actual missing-date XMP primary with an EXIF fallback. The
source-view browser checks multiple versions, tab/filter/table geometry and hidden
selector accessibility at desktop and narrow widths. Maintainer checks: use the
calendar, confirm the full timestamp keeps its time/offset, and switch source tabs on
a photo with multiple sidecar versions without the fields shifting vertically.

Recorded-tag comparison checks cover the union of both sources, changed/equal tags,
empty versus missing, reordered object keys, differences-only and search, comparison
off, and a source with no tags of its own. Desktop/narrow screenshots cover the expanded table.

### Inspector Metadata tab: final manual validation

1. Open a Library photo. Photo information shows actions, warnings and basic file/date
   facts. Technical details starts collapsed; expand it to find hashes and file tags.
2. Open Metadata. The primary source is marked, source tabs and sidecar versions work,
   and Compare with primary / Show differences only apply to fields and expanded tags.
3. Return to Photo information and choose Edit date. Metadata becomes selected behind
   the editor. Choose a calendar day, check the preserved time/offset, then preview and
   cancel/discard. Repeat and Save once; confirm the displayed date and filing location
   refresh. Copy a date from another source and explicitly clear an XMP date separately.
4. Choose Metadata or Similar photos, then use previous/next: the selected tab stays
   open. Click another gallery photo: Photo information opens. Refresh a URL with
   tab=metadata: Metadata is restored.
5. Source photos and Rejects still offer read-only Metadata; source issues remain on
   File information. Neither offers date-edit controls. Similar photos remains available
   for Library and Rejects only.
6. Check light/dark modes, resized panels and desktop zoom; source tabs, controls and
   comparisons stay readable. Enlarging a photo retains compact information and its
   View metadata shortcut returns to the Metadata tab.

The metadata-source browser workflow covers tab/URL restoration, gallery-click reset and arrow-tab retention,
repeated refresh, collapsed technical details and tag comparisons. The date workflow
starts through the compact Edit date shortcut. General, filter-pin, review and similarity
browser workflows cover shared Inspector consumers. Final manual acceptance and GitHub
checks are required before merge; passing a frontend build alone is insufficient.

Local Inspector-tab validation passed: frontend build; metadata-source, metadata-date,
filter-pin, review, similarity, reject-from-similarity and general UI browser workflows
(seven workflows using generated fixtures); 475 spec references and 54 API routes.
Screenshots cover desktop/narrow layouts. These results do not replace maintainer
acceptance or the full GitHub checks on the eventual pushed editor commit.

### Full demo plus metadata scenarios: maintainer walkthrough

Use a fresh disposable catalog/destination with the full demo library and the metadata
scenario library mounted read-only under separate source subfolders. Keep the scenario
manifest alongside the deployment, outside Git. The full demo includes thousands of
photos plus intentional edge cases; the metadata builder adds focused source/date cases.
Source files, catalog photos and organized Library photos are different counts: sidecars,
exact duplicates and import holds mean they will not match. This walkthrough validates
real browsing and editing behavior; it is not a 200k/500k performance benchmark.

1. **Setup and Index.** Start from the base URL, create the catalog, finish setup and
   choose On or Off for small-image reminders. Run Index and wait for completion.
   Inspect Not organized and the summary; Library remains empty until Copy. Needs
   attention should explain intentional malformed/unreadable scenarios and link to logs.
2. **Copy.** Run Copy all photos and wait for completion. Use Copy for read-only test
   sources. Library should contain thousands of photos; duplicates are organized once,
   and unsafe/unreadable cases remain at source with explanations. Check notification
   details and Not organized → Needs attention; record unexpected failures by their
   generated case, rather than assuming every failure is expected.
3. **Browse at volume.** In Library, scroll through several loads, use the year scrubber,
   search, select/unselect photos, and try Look into filters and Clear all filters. Open
   photos with clicks and previous/next. Gallery clicks reset to Photo information;
   previous/next retains Metadata/Similar selection, including across page boundaries.
   Explicit metadata-tab URLs restore on reload.
4. **Find a metadata case.** Search Library by its unique `md-` case token,
   for example `md-date-three-way` or `md-exif-only`. Demo scenarios use `scn-`.
   These tokens remain searchable if a destination collision adds a numbered suffix.
   For source inspection, use Not organized → Source folders → Still in source.
   Confirm the case against the manifest. Never reuse photo IDs or a `case-ids.json`
   mapping from a previous catalog; regenerate mappings after Index if needed.

| Case folder inside metadata fixtures | Expected before editing |
| :--- | :--- |
| `conflict/date_three_way` | Sidecar primary date 2021-08-01 09:30:00; embedded XMP 2020-05-01 10:00:00; EXIF 2019-06-15 12:00:00. |
| `agree/complementary` | Sidecar primary has no date; date editor starts blank, while filing uses the EXIF date 2019-06-15. |
| `agree/sidecar_only` | Sidecar primary with date 2019-06-15 12:00:00; useful for explicit-clear testing. |
| `agree/exif_only` | EXIF primary; date 2019-06-15 12:00:00. |
| `agree/embedded_xmp_only` | Embedded XMP primary; date 2019-06-15 12:00:00. |
| `sidecar_broken/malformed_xml` | Remains in Not organized; metadata warning identifies its sidecar and gives external repair/reindex guidance. |

5. **Information and comparison.** On the three-way case, Photo information shows a
   short filing-date summary and its source. Technical details starts collapsed and
   exposes hashes/file tags when opened. Metadata shows the three captured sources,
   identifies Primary independently of the selected tab, and defaults to primary.
   Compare EXIF/embedded XMP against primary, then enable differences-only and search.
   Expand recorded tags: they follow both controls and distinguish Empty from Not
   recorded. Raw names/structures can differ across formats even for equivalent common
   fields. Clear the search and switch source tabs without controls shifting vertically.
6. **Cancel then save.** From Photo information choose Edit date; Metadata is selected
   behind the editor. Pick an unused calendar day, checking time/fraction/offset remain
   unchanged. Preview shows write target, old/new date and old/new destination. Cancel →
   Keep editing preserves the draft; Cancel → Discard leaves files/date unchanged.
   Repeat, Save once and wait for Date saved. Clear restrictive date filters if needed
   to find the refiled photo. Confirm date, destination, primary source, other fields and
   photo logs. A photo-name collision should offer a numbered filename in Preview,
   never overwrite. Save must use the confirmed filename; a changed target needs a new preview.
7. **Copy and clear.** On a nonprimary EXIF tab choose Copy Date taken to primary;
   preview/save and verify the sidecar stays primary and the donor is unchanged. On
   the sidecar-only case, explicitly clear Date taken; preview/save should show Undated
   and Empty. On the complementary case, the initial editor must be blank rather than
   prefilled from EXIF; its explicit-clear explanation describes suppressing fallback.
   Keep these tests separate so earlier edits do not invalidate later expectations.
8. **Other targets and guards.** Test a complete date change on EXIF-only and
   embedded-XMP-only cases. Invalid dates cannot proceed; EXIF partial/empty values
   are refused rather than changing primary. No-change previews cannot save. Source
   photos and Rejects have read-only Metadata, with no date-save controls. Source
   warnings remain on File information and Similar photos is absent there.
9. **Layout and accessibility.** Repeat tab switching and a comparison in light/dark
   mode, with a resized Inspector and 200% desktop zoom. Check labels, buttons, tables
   and scrolling. Keyboard arrows switch focused tabs without changing the photo.
   Enlarge a photo; View metadata returns to its Metadata tab. Similar-photo browsing
   and side-by-side comparison still work on the full demo's matching sets.

Report the step/case, expected versus actual result and screenshot for any issue.
These manual checks precede commit/push and GitHub validation of the final editor branch;
they do not establish support for every intentionally unsupported builder scenario.

### Source and destination navigation validation

- Needs attention is indented under Not organized beside Source folders, has a count
  including zero in Library, Logs and Stats, and opens all affected source files.
  It has no pin; choosing Not organized leaves attention filtering.
- Source folders owns the only folder tree. Select a folder and switch Waiting /
  Still in source: the folder stays selected. Choose Library, Needs review or Rejects:
  the source-folder restriction disappears, including from the URL.
- Filters contains file types and Dates in each gallery. Date checkboxes narrow results;
  the date scrubber jumps within them. No second folder selector remains.
- Refresh and browser Back restore source scope; old destination folder URLs cannot
  leave an invisible filter. Source scope controls must not cover folder rows at desktop
  size or narrow reflow. Checkbox photo selections remain independent of navigation.

Maintainer reports Create, Index and Copy passed on the combined demo/scenario library.
Metadata and navigation acceptance subsequently passed, including all follow-ups below.

Source/destination navigation checks passed locally: frontend build; generated-fixture
filter-pin, source-scope, general UI and reference-set browser workflows; 475 spec
references and diff whitespace checks. Live read-only checks and inspected screenshots
cover desktop/narrow source navigation, attention counts and Library date filters.
The grouping test now explicitly pins similarity before combining other filters; its
old folder-popup expectations were replaced with the current source-only contract.
No engine change or catalog reset was needed for those navigation checks. Final editor
acceptance passed; GitHub checks remain a separate merge gate.

### Filter pin and gallery count follow-up

`filter_pins_browser_drive.py` covers pinning two filters and unpinning each one:
active states, URL restrictions, chip counts and gallery rows update, and refresh keeps
both off. Removing an unapplied pin preserves an explicit job link. The unfiltered
place total appears in the sidebar, without another total above the gallery or in its
pager. Filtered results show matching and whole-place counts; set, selection and job
scopes retain their own totals. `layout_stability_browser_drive.py` checks unchanged
control positions as the count summary appears/disappears at desktop and narrow widths.
`review_browser_drive.py` retains zero/one-result and reminder-clearing coverage.

Manual acceptance: in Library, pin Has similar photos and Suspicious dates; unpin each
in turn and confirm the gallery/counts broaden, then refresh. Verify Library keeps its
sidebar total, and only filtered results show “Showing N of M photos” above the gallery.

Automated follow-up validation: generated-photo filter-pin, layout-stability, review,
reference-set, gallery-position, source-scope and full browser workflows all pass.
The pin fixture uses a date boundary that excludes some photos, so clearing pins must
actually broaden results. Desktop/narrow light/dark screenshots inspected; build and
specification checks pass. Maintainer acceptance passed (Test 1).


### Completed date-editor branch acceptance after review-control cleanup

**Acceptance complete (2026-10-13).** Tests 1–6 and follow-up checks 3b, 4f,
5a, 5c, 5d and 5e passed. No further manual checks are requested for this batch.
The numbered steps below remain as the regression checklist.

**Maintainer results (latest review):**

| Test | Status |
| :--- | :--- |
| 1 | Passed. |
| 2 | Passed, including comparison tags layout. |
| 3 | Passed, including folder layout/actions follow-up 3b. |
| 4 | Passed, including corrected job counts and lineage follow-up 4f. |
| 5 | Passed, including follow-ups 5a, 5c, 5d and 5e. |
| 6 | Passed. |

The searchable-fixture refresh passed both Docker builder suites (9 metadata tests
and 10 demo-scenario tests). It includes 60 metadata cases. The maintainer completed
the follow-up validation after the refresh. Do not reuse IDs from an older catalog.

The maintainer authorized the reported-fix batch after finishing the other tests.
The searchable scenario update requires freshly generated fixtures and a fresh catalog;
keep previous validation data separately. Do not run retry/edit jobs on the maintainer's
behalf. Earlier acceptance results remain recorded above.

Search by the filename tokens below in the refreshed scenario library. Dates are the
initial values, before editing. A collision can add a filename suffix, so searching
without the extension is useful. Clear Library filters before searching.

| Steps | Destination filename to search | Initial filing date | Metadata case |
| :--- | :--- | :--- | :--- |
| 3e, 4a–f, 5a–b | `md-date-three-way.jpg` | 2021-08-01 | Three sources; sidecar primary |
| 5c–d | `md-sidecar-only.jpg` | 2019-06-15 | Sidecar-only |
| 5e–f | `md-complementary.jpg` | 2019-06-15 | Sidecar missing date; EXIF fallback |
| 6a, 6c–e, 6g | `md-exif-only.jpg` | 2019-06-15 | EXIF-only |
| 6b | `md-embedded-xmp-only.jpg` | 2019-06-15 | Embedded-XMP-only |

Create, Index and Copy have passed maintainer validation. A fresh fixture catalog
needs its own Index and Copy before these checks; earlier viewer acceptance still stands. These checks cover the remaining
layout/navigation changes and date-save workflow. Automated checks do not replace
maintainer acceptance.

**All Tests 1–6 and the following comment follow-ups passed maintainer validation:**

- **Test 3b:** Selecting/unselecting folders keeps the tree in place. Copy/Move stay
  visible but disabled with guidance unless exactly one folder is chosen.
- **Test 4f:** Lineage omits repeated selection-job links already represented in the
  tree; jobs without a recorded file step remain in a collapsed disclosure.
- **Test 5a:** On an alternative source's Date taken row, Copy date to primary is a
  link beside the date. It opens the same preview/save workflow, never copies all fields.
- **Test 5c:** The primary date and Photo information shortcut read Edit metadata date.
  A repeated clear of an already-empty primary date in Undated previews No changes
  needed with Save disabled. An absent date and an explicit empty are still distinct.
- **Test 5d:** The Date saved dialog has one heading and a shared footer containing
  View job details and Close, with consistent spacing.
- **Test 5e:** A primary missing Date taken points to another source with a recorded
  date; its link opens that source for review. No value is copied automatically.
  An explicitly cleared primary date does not get this suggestion.

Two non-blocking discussion items were recorded with the final passes: whether folder
handling can happen behind the scenes (3b; behavior still to define), and whether
the existing photo-filtered Open in the log link could have a clearer label (4f).
It already shows associated operations across jobs; no new log filtering is needed. Neither
requires another validation pass now. Copying all metadata also remains a separate
post-validation discussion, not part of this batch.

#### Test 1 — Filters and totals

- **a.** Hard-refresh Library, then Clear all filters. The whole-library count should
  appear in the sidebar without being repeated above the gallery or beside pagination.
- **b.** Pin Has similar photos and Suspicious dates. Both should be active, with one
  “Showing N of M photos” summary reflecting their intersection.
- **c.** Unpin each in turn. Each filter should turn off, and the photos, counts and URL
  should update. Refresh; both should remain off.
- **d.** Choose Newest first or Oldest first, then No usable capture date. The year controls
  should disappear without making the gallery jump.
- **e.** Pin No usable capture date and enable another available filter. The year controls
  should remain hidden, including after refreshing.
- **f.** Unpin No usable capture date. The other filter should remain active, and the year
  controls should return while sorted by date. Clear all filters before Test 2.

#### Test 2 — Inspection and comparison

- **a.** Open a Library photo with a review reason. Its action row should read Inspect
  photo, Review later and Reject, with consistent button styling.
- **b.** Choose Inspect photo. It should open the existing review workspace. Return
  to the gallery afterward.
- **c.** Open a photo with matches, choose Similar photos, then Review side by side.
  Refresh comparison should be outlined and aligned with the Minimum similarity
  dropdown. Keep should be beneath the reference preview's controls and dimensions.
- **d.** Choose Keep. The existing rejection-review screen should identify the correct
  keeper and other photos. Cancel/back out without rejecting any photos.
- **e.** Reopen the comparison and choose Use as reference on a candidate. Keep should
  now name that photo. Refresh comparison should retain the current reference.
- **f.** Check these controls in both themes and at 200% desktop zoom. They should
  remain readable and reachable. The recorded-tags layout recheck has passed.

#### Test 3 — Navigation and metadata viewing

- **a.** Open Not organized → Needs attention. It should have a sidebar count and show
  the affected source files.
- **b.** Open Source folders and select a folder. Switch Waiting / Still in source:
  the selection should remain, and the scope controls must not overlap folder rows.
  Please check at the window size where you originally saw the overlap.
- **c.** Choose Library. The source-folder restriction should disappear from results
  and the URL. Types and Dates should remain available in Filters, with no folder tree.
- **d.** Click a gallery photo, choose Metadata, then use previous/next. The Metadata
  tab should stay selected. Clicking a different gallery card should instead select
  Photo information. Repeat with Similar photos.
- **e.** On `md-date-three-way.jpg` (three-source case), switch among
  XMP Sidecar, Embedded XMP and EXIF. Primary should remain clearly identified even
  when another source is selected. Find the case by its supplied destination
  filename and date; filenames alone may not be unique across the generated fixtures.
- **f.** Enable Compare with primary, differences-only and a field search. Expand
  recorded source tags in the Metadata tab: those controls should also apply there.
  Empty and Not recorded must remain distinct. The separate side-by-side layout recheck has passed.
- **g.** Repeat tab switching in light/dark mode and at 200% desktop zoom. Labels and
  controls should stay readable and stable.

#### Test 4 — Cancel and save a date

- **a.** On `md-date-three-way.jpg`, note the current primary, date, destination and
  another recorded field. Open Edit date and pick an unused calendar day. Any recorded
  time and timezone offset should remain unchanged.
- **b.** Preview. Confirm the primary write target, old/new date and old/new destination
  before saving. No file change should have happened yet.
- **c.** Choose Cancel → Keep editing. Your draft should remain. Then Cancel → Discard:
  the saved date and destination should be unchanged.
- **d.** Repeat the edit, preview and Save once. Wait for Date saved.
- **e.** Check Photo information and Metadata: date/path should match the preview;
  primary identity and unrelated fields should be unchanged. Clear any restrictive
  date filters if the photo leaves the current view.
- **f.** Open its log and confirm the date-edit operation is recorded. Refresh the
  page and confirm the saved date remains.

#### Test 5 — Copy and clear a date

- **a.** On `md-date-three-way.jpg`, select its nonprimary EXIF source tab.
  Choose Copy Date taken to primary. Preview must name the primary as the write target
  and show an available numbered filename if the proposed photo name is occupied.
- **b.** Save once. The primary date should match the chosen donor date; the donor
  and primary identity must remain unchanged.
- **c.** On `md-sidecar-only.jpg` (sidecar-only), open Edit date and explicitly
  clear Date taken. Preview should show the clear and an Undated destination.
- **d.** Save. Confirm Empty in the primary metadata and Undated in the destination.
- **e.** On `md-complementary.jpg` (complementary), the sidecar has no date
  while EXIF has one. Its editor should start blank, even if the filing date used EXIF.
- **f.** Explicitly clear that missing sidecar date, preview and save. This should
  suppress fallback and file the photo under Undated. Earlier edits can change a case's
  starting state; use an unmodified case or report that it is no longer suitable.

#### Test 6 — Other writers and guards

- **a.** On `md-exif-only.jpg` (EXIF-only), save a complete Date taken value. Confirm the resulting
  date/path and that EXIF remains primary.
- **b.** On `md-embedded-xmp-only.jpg` (embedded-XMP-only), do the same. Embedded XMP should remain primary.
- **c.** On `md-exif-only.jpg`, enter an invalid date, such as February 31. It should not proceed to saving.
- **d.** On `md-exif-only.jpg`, preview an unchanged date. Saving should be disabled with no changes needed.
- **e.** Search Library for `md-exif-only.jpg`, open Metadata, and confirm EXIF is marked
  Primary. Choose Edit Date taken, enter `2020` in the Date taken text field (not the
  calendar), and attempt Preview change if enabled. It must refuse the partial date
  with an explanation and must not switch primary. Cancel without saving.
- **f.** Open a source photo in Not organized and a photo in Rejects, if one is present.
  Their Metadata tabs should be read-only for date editing. Report Rejects as not
  exercised if empty; no need to reject a photo just for this check.
- **g.** On `md-exif-only.jpg`, repeat an edit/preview at 200% desktop zoom. All confirmation and cancel
  controls should remain reachable; cancel if you do not want another date change.

After acceptance: reconcile docs/backlog, commit and push this branch, require GitHub
checks to pass, then review and merge. The reported-fix batch also changes engine preview
name selection and API outcomes; metadata/API regressions supplement the browser checks.

Automated review-control cleanup checks: frontend build; nine generated Docker browser
workflows (filter pins, layout stability, similarity comparison, Reject/Keep, review,
cross-location, source scope, metadata sources and date editing); all three spec checkers
and whitespace checks pass. Comparison checks assert dropdown/refresh alignment and
reference-only Keep placement at desktop and narrow widths. Layout checks retain the
1px limit. A comparison-test mock cleanup race was corrected by waiting for in-flight
handlers before removing them; no assertions were removed or loosened. The year controls
leave an empty gutter so hiding them does not rewrap the gallery guidance.


Reported-fix regression results: all 439 metadata tests, 98 API tests and 5 notification
tests passed in Docker (317 s, 88 s and under 1 s respectively). Five generated browser
workflows passed: date editing (24 s), source scope/folder alignment (12 s), similarity
comparison (14 s), notifications (22 s), and layout stability (21 s). Tests verify
numbered-name saves for sidecar and embedded EXIF, preservation of occupied files and
source bytes, stale-target/orphan/symlink refusal, saved/failed/no-change counts, blank
explicit-clear inputs and draft restoration, stable candidate positioning when tags
expand, and aligned empty-folder rows at three widths. All three spec/schema checkers
and whitespace checks passed. These automated results supplement the maintainer acceptance recorded above.


Post-acceptance comment checks: all five generated Docker browser workflows passed
(date editing, metadata sources, source scope, layout stability and the full web UI).
The date flow verifies a second explicit clear cannot save or start another job; the
folder flow checks tree-relative geometry when choosing one, multiple or no folders.
Desktop/narrow rendering, completion-dialog screenshots, all three spec checks and
whitespace checks passed. Engine behavior was unchanged in this presentation batch.

CI follow-up: the request-freshness browser driver checks one gallery request and no
folder-tree request on the default gallery, then exactly one folder-tree request in
Source folders. The unchanged-feed and job-completion freshness assertions remain.


## Incomplete photo/XMP import retry

`pair_retry_test.py` runs in the standard Docker unittest form. It covers partial
Copy/Move publication, unchanged source bytes until verified success, destination
reuse, stale snapshots, the API/engine race, request replay, invalid/busy requests,
changed live files and same-mode safety answers. It runs in PR/main/manual CI.
`PAIR_RETRY_FIXTURE=1 DRIVER=pair_retry_browser_drive.py sh tests/browser/webui_browser_test.sh`
adds generated XMP pairs and injects one initial sidecar-publication failure per
mode. Only this fixture's generated source is writable; no real source is used.
The browser covers latest-failure notices with retained retry history in either response
order, photo-log links, Inspector/selection entry points, Cancel, Copy/Move confirmation,
verified completion, source preservation/removal and narrow/200% layouts. Artifacts
can be retained with the harness's normal `NS_TEST_KEEP` and `SHOTS` options.

Manual visual acceptance: **R1–R3 passed**, confirmed by the maintainer on 2026-10-15.
The steps below remain the regression checklist; S1–S3 also passed. To repeat,
use only the prepared generated-failure fixture.
Do not damage a real library to manufacture an error.

1. **R1 — Inspect and cancel.**
   a. In Not organized, search `photo-000.jpg` and open its information pane after
      the fixture's first Copy has failed publishing XMP.
   b. Confirm **Photo/XMP transfer incomplete** includes the recorded failure.
      Open **Retry photo/XMP transfers**. For the fresh generated XMP failure, expect
      **Transferring XMP**, a green destination photo labelled **Verified at destination**,
      and an amber destination XMP labelled **Delivery incomplete — file may be partial**.
      Source originals stay neutral. All four paths are visible; Source and Destination
      have headings and a divider. The explanation says destination paths are intended
      locations and results come from the last recorded job, not a fresh check.
      Older records without delivery evidence show amber unconfirmed results rather than
      invented success. Check the same Source/Destination separation in Photo information
      and Logs.
   c. Choose **Retry Copy**, then Cancel. Both source files and the failure remain.
      Check the dialog at normal size, 200% zoom and a narrow window.
2. **R2 — Retry Copy.**
   a. Select that photo in the gallery; the selection bar offers a separate retry
      count, while ordinary Copy/Move eligibility remains unchanged.
   b. Confirm Retry Copy. Follow the new job to completion; the photo enters Library
      and its pair issue disappears. Both originals remain in the generated source.
3. **R3 — Retry Move.**
   a. On `photo-001.jpg`, use the fixture's initial failed Move. The retry must say
      **Move**, explain removal after both destination files verify, and offer Cancel.
   b. Confirm Retry Move. The pair enters Library and both generated source files
      disappear only after verified completion. Earlier failure history stays in Logs.

This flow is for incomplete first imports, not date-edit/refiling or incoming-choice
recovery. Those retain their separate engine contracts and backlog entries.

## Metadata setup and Settings preferences

`METADATA_SETTINGS_FIXTURE=1 DRIVER=metadata_settings_browser_drive.py sh tests/browser/webui_browser_test.sh`
uses generated photos and pauses a real Copy immediately after its run configuration is
recorded. The browser saves new preferences while that job is held, then checks that
its recorded settings remain unchanged and a later job captures the saved values. The
catalog connection is read-only; its generated mount permits SQLite WAL shared-memory
bookkeeping. The fixture never touches a real library. All holds are bounded and released
in test cleanup.

Coverage includes required first-run choice, no save until the final step, explicit
Ask me persistence, defaults, unsupported RAW embedded writes, Reset, tab draft retention,
revision conflict refusal, live notices without control movement, and narrow/200% reflow.
This driver runs in PR/main/manual CI. Existing setup drivers choose Ask me while keeping
their original assertions. Engine snapshot rules also remain covered by
`metadata_decisions_test.py`; the Settings API is covered by `webui_api_test.py`.

Manual Settings acceptance **S1–S3 passed**; the later warning
classification check **W1** below also passed. R1–R3 and S1–S2 passed on
2026-10-15; no repeat of those tests is required for current-build acceptance. S1 feedback:
metadata questions now have their own Metadata setup step and Settings tab. The
six-step layout and message readability changes need separate acceptance below. For a future S1 regression run, use a separate fresh generated
catalog. Do not reset a working library.

1. **S1 — Setup choice and defaults.**
   a. In the fresh setup's Files step, choose small-image reminders On or Off and select
      Next. On the Metadata step, leave the shared-XMP choice empty. Next must identify the required choice and focus it.
   b. Choose Ask me. Confirm the visible source priority, explicit-empty rule, RAW XMP
      default, and JPEG-only embedded limit. Move Next then Back: your choice remains.
   c. Finish setup; open Settings → Metadata. The same choice and explanations remain.
2. **S2 — Settings drafts and running jobs.** Maintainer passed on 2026-10-15,
   confirming the saved-settings notice during a running job.
   a. Change the shared-XMP preference, switch tabs and return. The draft and unsaved
      dot remain. Reset restores the saved choice.
   b. With an Index or Copy running on generated photos, open Settings. The notice at
      the top says saved processing changes affect future jobs, not this one, on every tab.
   c. Save a preference while the job runs. The confirmation repeats the boundary.
      When the job completes, the notice changes in place without shifting controls or
      losing unsaved drafts. Appearance/review reminders still apply immediately.
3. **S3 — Scope and layout.** Maintainer passed; retained as a regression checklist.
   a. Save a different shared-XMP preference and reopen Settings to verify persistence.
      This does not switch a photo's existing primary or rewrite recorded ownership.
   b. Confirm unresolved files are described as source attention and the per-file choice
      limitation is explicit. Embedded RAW cannot be enabled from this screen.
   c. Check Files and the job notice at normal width, 200% zoom and a narrow window:
      labels, explanations and Save/Close remain reachable without horizontal overflow.

Per-file ownership/primary decisions, incoming alternative decisions and broader metadata
editing controls remain separate unfinished work; this batch does not claim they are built.

Automated Settings-batch validation: 34 targeted Settings/decision/date tests passed
in Docker. Seven generated browser workflows passed: metadata Settings, access,
date settings, fresh start, review, full web UI and layout stability. Setup/Settings
screenshots were inspected at desktop, narrow and the reduced CSS viewport equivalent
to 200% desktop zoom. The web build, workflow lint, spec/API/schema checks and whitespace
checks passed. This supplements the earlier retry checks; R1–R3 now have maintainer
acceptance; S1–S3 also passed.

R1 feedback follow-up: Source/Destination sections now share a divider in Inspector,
retry details, Logs and verification evidence. New transfer failures identify their
attempted step and paths; old records remain unchanged. All 53 retry/transfer/attention
tests and four generated browser workflows (retry, full UI, layout stability, attention)
passed. Builds and spec/API/schema checks passed; desktop/narrow screenshots inspected.
The maintainer subsequently accepted R1–R3 and S1–S3.

R1 delivery-status follow-up: per-member verification is recorded with settled failures
and read-only interruption recovery. Green is reserved for verified destination content;
partial/unconfirmed delivery is amber with text, never inferred from an intended path.
A new fixture cycle can prepare another generated failure while retaining earlier history.
The maintainer subsequently accepted this R1 follow-up with the full R tests.

Delivery-status validation: 39 retry/transfer engine/API tests passed, including photo
publication versus XMP failure, cleanup failure after verified delivery, older records,
final-verification refusal and read-only interruption recovery. The browser verifies
status text and colors, removal of stale green results for unknown history, both themes,
normal/narrow/200% reflow, and original Copy/Move retry semantics. Builds and all three
contract checks passed. Maintainer R1–R3 acceptance passed.

Recovery-notice cleanup: the generated browser check passed for both original modes,
latest-only failure display with reversed history order, photo-log links, resume wording,
and desktop/narrow/200% reflow. Screenshots were inspected in both themes. The web build,
spec/API/schema contracts and whitespace check passed. R acceptance stays complete.

## Informational metadata-reader warnings

`metadata_index_test.py`, `metadata_import_test.py` and `metadata_view_test.py` cover
reader warnings versus errors, refreshing legacy warning-only holds without rewriting
history, real generated unknown MakerNotes, exact-byte Copy/Move with and without XMP,
and broken sidecars remaining blocked. Notes remain available after verified transfer,
but are not attributed to different photo content after an edit.

Validation: 130 tests passed across capture, import, viewer, pair transfer, embedded
editing and metadata decisions (67.596 seconds in Docker). The metadata-source browser
driver passed informational notes, technical-detail disclosure and desktop/narrow/200%
reflow alongside its existing source/comparison checks. Screenshots were inspected.

Manual **W1 — Warning-only photo can be organized** (maintainer passed; retained as
a regression checklist):

a. Reindex an existing warning-only photo, then locate it in Not organized. A reader
   warning alone should no longer put it in Needs attention or prevent Copy.
b. Open Metadata: the MakerNotes explanation appears under Metadata notes; expand
   Technical details for the exact diagnostic.
c. Copy that photo. Confirm it reaches Library and still shows the note. An unrelated
   suspicious-date warning remains separate; no metadata values are repaired or edited.

R1–R3, S1–S3, D1 and W1 acceptance passed. No manual checks remain for this batch.


## Date information versus source attention

Validation: all 16 metadata-view tests passed in Docker (0.537 seconds), including
repeated date diagnostics retaining every affected path. The metadata-source,
layout-stability and full web-interface browser drivers passed. Desktop and narrow
screenshots were inspected. App/web builds and specification/API/schema checks passed.

Manual **D1 — Date information and source blockers** (maintainer passed all steps,
including D1.c; retained as a regression checklist):

a. Confirm the filter now reads **No usable capture date**. Select it and check the
   guidance explains that missing dates alone do not prevent Copy or Move.
b. Open a source photo with a date issue from **Needs attention**. Its File information
   pane should explain the specific issue once under **Needs attention before
   organizing**, identify the affected file and give the resolution. If it also appears
   under No usable capture date, that is the same photo with two applicable properties.
c. Open a photo with a usable XMP filing date but no EXIF Date taken. Its date should
   appear without an incorrect missing-EXIF warning. Automated coverage also checks
   this case; no need to manufacture a new fixture if none is in the current catalog.

R1–R3 and S1–S2 remain accepted; do not repeat them for this wording change.


## Photo/XMP retry branch closeout

Maintainer acceptance is complete: R1–R3, S1–S3, D1 and W1 passed. The dedicated
Metadata setup step/Settings tab and broader filter UX remain follow-up work.

Final local validation used generated fixtures, plus the read-only public RAW samples:

| Check | Result |
| --- | --- |
| All 45 Python unit suites | 817 tests passed; 534.8 seconds including suite startup |
| Full engine smoke run | 153 passed, one test-fixture failure, zero skipped; both RAW checks passed |
| Corrected detail-preview smoke check | One passed in 2.0 seconds; no skipped checks |
| Photo/XMP retry browser | Passed Copy/Move, cancellation, source safety and narrow/200% layout |
| Metadata Settings browser | Passed required choice, persistence/conflicts, frozen running jobs and layout |
| Date-message integration browsers | Metadata sources, layout stability and full web workflow passed |
| App/web builds and spec/API/schema checks | Passed |

The smoke failure assumed a particular filename would win duplicate retention. The
engine correctly retained the identical twin instead. The test now locates the actual
retained copy, additionally checks that exactly one catalogued destination remains and
both sources are gone, and preserves all cached-preview/content-change assertions.
The focused rerun passed; the full smoke suite was not rerun after that test-only fix.
GitHub CI is a separate pre-merge gate; these local results do not claim CI acceptance.


PR CI follow-up: the full engine smoke job passed after the duplicate-retention test
correction. Metadata and Python/contract jobs also passed. The appearance browser
caught an outdated global-first-section selector after the new Settings notice was
added. It now asserts that Appearance is selected and checks its visible tab panel;
all palette, contrast, persistence, scrolling and narrow-control assertions remain.
The corrected appearance driver passed locally in Docker. The next CI run must pass
all groups before merge.


## Metadata grouping and message readability validation

This batch moves Metadata to its own Settings tab and setup step (third of six).
It reviews explanations across setup/preferences, gallery/filter guidance, photo and
metadata information, date editing, similarity/sets, incomplete transfers, submission,
job results, Logs, backups, and engine/API refusal messages. Short, clear messages stay
as they are. Changes simplify repetitive prose, keep the specific cause and next step,
show multiple metadata issues as a list, and use shared paragraph/dialog spacing.
Recorded history, raw diagnostic evidence, error codes and file safety rules are not
rewritten. The standard is `docs/ui-design.md`, Writing messages.

Automated validation on generated fixtures (2026-10-16):

| Check | Result |
| --- | --- |
| Metadata viewer | 16 tests passed |
| Metadata save/recovery | 36 tests passed |
| Similarity recovery | 7 tests passed |
| Date editing API | 11 tests passed |
| Metadata decisions/frozen settings | 18 tests passed |
| Web API | 100 tests passed |
| API, schema and spec checks | All three passed |
| Frontend type-check and production build | Passed in Docker |
| Browser workflows | 16 passed; list below |

Browser drivers: `webui`, `access`, `fresh_start`, `date_settings`, `review`,
`metadata_settings`, `metadata_dates`, `metadata_sources`, `pair_retry`,
`similarity_recovery`, `similar`, `layout_stability`, `notifications`, `source_scope`,
`submission`, and `safety_questions` (each with the `_browser_drive.py` suffix and
its documented fixture flag). Final shared-dialog spacing was checked with a complete
rerun of these workflows. Rendered Settings, setup, retry and Logs were inspected,
including narrow/200% layouts. This is targeted validation, not a full engine smoke run.

**Manual acceptance passed (2026-10-16): Tests 1, 2, 3 and 4, all steps.** No manual
checks remain for this batch. The steps below are retained for future regression checks.
Use the existing review demo for Tests 1, 3 and 4 and a separate fresh-setup instance
for Test 2. Do not reset the existing library.
The prepared demo has `photo-000.jpg` in Library with XMP Date taken
`2005-03-04T05:06:07`; the filename and location were verified before requesting checks.

1. **Test 1 — Settings.**
   a. Open Settings. Expect Appearance, Files, Metadata, Backups, Performance and
      Access. Metadata controls no longer appear in Files.
   b. Open Metadata. Read the source priority, shared-sidecar choice and edit defaults.
      Confirm the text is understandable and clearly separated.
   c. Change a preference without saving, switch tabs and return. The draft remains
      and Metadata shows an unsaved dot. Use Reset to restore the saved settings.
2. **Test 2 — Fresh setup.**
   a. On the separate setup instance, choose Create new catalog and Next. Choose
      small-image reminders On or Off in Files, then Next.
   b. Expect Step 3 of 6 Metadata. Leave the required sidecar choice empty and select
      Next: the choice is identified and focused, with no advance.
   c. Choose Ask me, go Next then Back. Your choice remains. Finish setup if desired;
      no Index or Copy is needed for this check.
3. **Test 3 — Photo and job explanations.**
   a. In the existing demo's Library, search `photo-000.jpg`. Open Metadata, then
      Edit metadata date beside Date taken. Read the source/date/location guidance;
      cancel without saving. Check the Similar photos tab's explanation as well.
   b. Open Logs, choose Failed only and expand the latest Index job with failures.
      Check that the guidance explains why old failures remain and when retry helps.
      Open the notification bell's Details to confirm recorded causes remain readable.
4. **Test 4 — Formatting.**
   a. Repeat Settings → Metadata and the date dialog at 200% browser zoom and in
      dark mode. Text should wrap, paragraphs have clear gaps, and controls remain usable.
   b. In Logs, switch between All status and Failed only. The filter controls should
      stay in place despite the different explanation.

No destructive or file-editing acceptance actions are required for this readability batch.


## Expanded photo Inspector validation

The expanded view reuses the Inspector rather than a separate photo/details layout.
Automated checks passed in Docker: production frontend build/typecheck, all three
contract checks, the full web browser workflow (including shared UI checks), Similar
photos and metadata date editing. Coverage includes side-by-side geometry, tab and
photo navigation, resize/reflow, nested lineage/date dialogs and focus restoration.
Rendered desktop and narrow screenshots were inspected. No engine behavior changes.

**Manual acceptance complete:** the maintainer confirmed all posted steps, Test 1a
through Test 3b, passed. No manual checks remain for this batch. Use the existing demo; no reset, Index or Copy is needed.
`photo-000.jpg` was verified in Library, Copied, with XMP Date taken
`2005-03-04T05:06:07` and three recorded matches at 75% before requesting these checks.

1. **Test 1 — Two panes.**
   a. In Library, search `photo-000.jpg`, open its card, then click the large preview.
      Expect the photo on the left and information/Metadata/Similar photos on the
      right, without the gallery or another details section beneath the image.
   b. Switch all three tabs and drag the divider. Similar photos identifies the
      large image as Reference photo and keeps its matching controls on the right.
      Choose 75% to see the three recorded candidates for this generated photo.
   c. Press Escape. Expect the normal gallery Inspector with the last tab retained.
2. **Test 2 — Browse photos.**
   a. With `photo-000.jpg` still open, clear the filename search so the gallery has
      other photos. Choose Metadata and enlarge the preview again.
   b. Use Next photo, then Previous photo. The expanded view stays open, Metadata
      stays selected, and Previous returns to `photo-000.jpg`.
3. **Test 3 — Dialogs and reflow.**
   a. On `photo-000.jpg`, expanded Metadata → XMP Sidecar Primary, choose Edit metadata
      date, then Cancel without saving. Expect to return to expanded Metadata.
   b. Check the expanded view at 200% browser zoom and in dark mode. Panes may stack
      at narrow widths; text and controls remain reachable. Close returns to the gallery.
