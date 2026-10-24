# Tests

Everything here is for developing NegativeSpace; running the engine needs none of it.
## Index summary checks

`review_test.py` checks summary membership across pages, IDs, facets and photo
navigation, invalid scopes, and immutable per-job file-type accounting.
`metadata_view_test.py` covers held versus ready transfer counts and cleared holds.
The existing review browser driver covers summary links, empty results, Back/Forward
and the file-type disclosure; the default driver checks Copy all confirmation counts.
These run in the existing Python/browser CI jobs. Maintainer checks are recorded in
[manual validation](../docs/manual-validation.md#index-summary-actions).

## Manual validation instructions

Use [Manual validation](../docs/manual-validation.md) for the pending queue, all browser
walkthroughs, accepted results and [handover rules](../docs/manual-validation.md#maintainer-validation-rules).
Keep manual steps there; this README documents automated suites, fixtures and commands.

## CI coverage

CI coverage is split between two workflows:

- **Every pull request and push to `main`**: `.github/workflows/engine-tests.yml`
  first classifies the complete Git diff and tests that classification and the required
  merge gate. Documentation-only changes run the spec cross-reference, schema-drift
  and API-spec checks; they skip the application test groups.
- **Code, mixed, unknown-path changes and manual Engine tests runs**: run every
  Python unit suite (`tests/*_test.py`), engine smoke, the three shell suites, all
  `tools/check-*.py`, synthetic similarity validation, container CPU/timezone/CLI
  checks, and the PR/main browser drivers listed below. `ci_scope_test.py` runs
  in the small Git-equipped CI test image; application suites use the app image.
  `sidebar_refinements_test.py` and `notifications_test.py` use `PYTHONPATH=/app/tests:/app`.
  RAW smoke tests require the optional read-only public samples locally; GitHub has
  no such samples and reports those two skips.
- **Nightly at 05:37 UTC and manual Extended browser tests runs**:
  `.github/workflows/extended-browser-tests.yml` runs the ten extended drivers below.
  They do not add runtime to the PR gate. The nightly schedule starts once the
  workflow is on the default branch. After merge, use Actions → Extended browser
  tests → Run workflow to select a branch for a manual run.

“PR / main / manual” below means the full application path, not documentation-only
changes. All browser entries below are in `tests/browser/`, use `webui_browser_test.sh`, and
build isolated catalogs from generated photos. Set `DRIVER` to the filename; the
fixture flags are required where shown. Each browser job builds the app, web and browser-test images.
CI sets `PLAYWRIGHT_IMAGE` to the browser-test image, installing the matching
Playwright package once per job. Standalone harness runs still install it unless
you supply a prebuilt `PLAYWRIGHT_IMAGE`; catalogs and containers remain isolated.

| Browser driver | CI schedule | Additional environment |
| --- | --- | --- |
| `access_browser_drive.py` | PR / main / manual | — |
| `appearance_browser_drive.py` | PR / main / manual | — |
| `backup_browser_drive.py` | PR / main / manual | `BACKUP_FIXTURE=1` |
| `attention_browser_drive.py` | PR / main / manual | `SIMILARITY_RECOVERY_FIXTURE=1` |
| `copied_source_browser_drive.py` | PR / main / manual | — |
| `sidebar_refinements_browser_drive.py` | PR / main / manual | — |
| `fresh_start_browser_drive.py` | PR / main / manual | — |
| `gallery_position_browser_drive.py` | PR / main / manual | — |
| `import_choices_browser_drive.py` | PR / main / manual | `IMPORT_CHOICES_FIXTURE=1` |
| `metadata_dates_browser_drive.py` | PR / main / manual | `METADATA_VIEW_FIXTURE=1` |
| `metadata_settings_browser_drive.py` | PR / main / manual | `METADATA_SETTINGS_FIXTURE=1` |
| `pair_retry_browser_drive.py` | PR / main / manual | `PAIR_RETRY_FIXTURE=1` |
| `transfer_preview_browser_drive.py` | PR / main / manual | — |
| `move_confirmation_browser_drive.py` | PR / main / manual | `MOVE_CONFIRMATION_FIXTURE=1` |
| `metadata_sources_browser_drive.py` | PR / main / manual | `METADATA_VIEW_FIXTURE=1` |
| `notifications_browser_drive.py` | PR / main / manual | — |
| `preview_refresh_browser_drive.py` | PR / main / manual | — |
| `reject_similar_browser_drive.py` | PR / main / manual | — |
| `rejects_browser_drive.py` | PR / main / manual | — |
| `request_freshness_browser_drive.py` | PR / main / manual | — |
| `review_browser_drive.py` | PR / main / manual | — |
| `similar_browser_drive.py` | PR / main / manual | — |
| `lineage_browser_drive.py` | PR / main / manual | — |
| `same_name_browser_drive.py` | PR / main / manual | — |
| `low_detail_browser_drive.py` | PR / main / manual | `LOW_DETAIL_FIXTURE=1` |
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


The documentation-only allowlist is `README.md`, `CHANGELOG.md`, `TODO.md`,
`AGENTS.md`, `CLAUDE.md`, `tests/README.md`, Markdown under `docs/`, and PNG/JPEG/GIF/
WebP/SVG images under `docs/images/`. Everything else requires the full suite,
including tests, tools, workflows, dependencies, Dockerfiles and unknown Markdown
paths. Missing Git history, an empty diff or a non-fast-forward push also requires
full validation. Pull requests compare against their merge base; pushes compare
all changes between the previous and new commit. Renames include both old and new
paths, and the classifier has no changed-file count limit.

The full application path runs four independent jobs: engine smoke tests, metadata
tests, other Python/contract tests, and browser tests. Each has a 30-minute budget;
individual test timeouts and assertions are unchanged. Documentation checks run
separately for both paths. The existing required check, **Smoke suite (in container)**,
is the final gate. Classification and documentation checks must pass. All four
application groups must pass for full validation, or be intentionally skipped for
verified documentation-only changes. Failure, cancellation, missing classification
or an unexpected skip blocks the gate. Keep this final gate required in branch
protection; requiring the application groups alone would not verify documentation.
New suites must be added to the appropriate group. Superseded runs on the same PR
are cancelled; main and manual runs are independent. The ten nightly/manual drivers
keep their existing schedule.

Run the routing and gate regressions in Docker (generated Git repositories only):

```bash
docker build -f docker/ci-test.Dockerfile -t negativespace-ci-routing .
docker run --rm -v "$PWD":/app:ro -w /app negativespace-ci-routing \
  -m unittest discover -s tests -p ci_scope_test.py -v
```

Before the application suites ran in parallel, successful GitHub run `38505467509` took 26m15s: engine smoke
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

## Same-name card validation

`same_name_browser_drive.py` covers whole-result labels, page boundaries, filtered
results, arrival-rename hovers, both themes and 200% text reflow. It also checks
review-link alignment with mixed EXIF/file dates and wrapped status badges. The API suite's
`SameNameCards` cases also check exact copies, missing hashes, Unicode folders,
explicit selections and failed-versus-successful transfer history.

Manual steps and recorded results: [Same-name cards](../docs/manual-validation.md#same-name-cards).

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
| `date_settings_browser_drive.py` | | Setup year choice and optional Files disclosures/error focus, settings validation/persistence, immediate filter and Inspector updates |
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
Help checks require icon-only activation when an information icon is present, preserve
pointer access to open help, and verify keyboard focus, click and Escape dismissal.
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
The shared confirmation checks cover matching text and button order, Cancel not saving
the comparison preference, bulk confirmation after reviewing the selection, and the
last-photo warning even when the comparison preference is enabled.
It also checks the single large reference preview, its heading and accent border,
no repeated reference thumbnail in the matches pane, and no Keeping label before
an explicit Keep choice, across wide/stacked layouts and forced colors.

Manual steps and recorded results: [Reference and keeper labels](../docs/manual-validation.md#reference-and-keeper).

`DRIVER=rejects_browser_drive.py sh tests/browser/webui_browser_test.sh` checks Rejects: one
photo rejected from the Inspector (asked first by name, starting on Cancel), a selection
reviewed before rejecting, the Rejects view with what it holds and How to empty Rejects,
the shared bulk confirmation (Cancel preserves selection), Cancel/Escape focus restoration,
and the dialog in light/dark mode and 200% text reflow. It also covers Return to library,
the selection bar for photos in Rejects (Return first, and a Move that
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
The generated A–B–C–D chain checks grouped collapse, a set's direct members,
thresholds, paging, positioning, destination-only eligibility and no DB writes.
Run the browser harness with `DRIVER=reference_sets_browser_drive.py` and
`SIMILARITY_RECOVERY_FIXTURE=1`, specifying the built `IMAGE` and `WEB_IMAGE`.
It uses only the harness's disposable generated catalog. Checks include grouping, the
explanation of sets and its accurate diagram membership; icon hover (not label hover),
keyboard focus, the ⓘ button, Escape and scrollable viewport bounds at 200% text; set review, selection
preservation, a dense set's members paged in the gallery, and per-file recovery failure
details in Logs.

`python3 tools/benchmark-reference-sets.py` measures a set's member gallery against
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

Manual steps and recorded results: [Source preparation](../docs/manual-validation.md#source-preparation).

### Similarity catalog setup

Manual steps and recorded results: [Similarity catalog setup](../docs/manual-validation.md#similarity-setup).

### After Index and Copy

Manual steps and recorded results: [Similarity browsing after Index and Copy](../docs/manual-validation.md#similarity-browsing).

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

Manual steps and recorded results: [Similarity comparison and shared demo](../docs/manual-validation.md#similarity-comparison).

The generated-catalog browser check is `DRIVER=similar_browser_drive.py sh
tests/browser/webui_browser_test.sh` (set `IMAGE`/`WEB_IMAGE` to the builds under test).
Manual steps and recorded results: [Historical comparison scope](../docs/manual-validation.md#comparison-historical-scope).

### Manual Copy review link check

Manual steps and recorded results: [Copy review link](../docs/manual-validation.md#copy-review-link).

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
| `look-alikes/` | an original rotated in its pixels (not found, by design), cropped, black-and-white, colour-graded, watermarked; the original stored turned with an orientation tag (`scn-turned-tagged-…`); and, with a portrait RAW in the seed, a camera's JPEG of it stored unrotated with the RAW's orientation tag (`scn-raw-twin-<RAW name>.jpg`) |
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
choice, Copy, independent Small images/Bookmark decisions, refused-save retry,
Previous/Next, confirmed Reject, persistence after reload and Index, Settings links,
selection preservation, combined chips and narrow workspace reflow. The default browser
driver exercises choosing Off during first run. Both are in CI.

The browser harness accepts `NS_TEST_OUTPUT_ROOT`, `NS_TEST_DESTINATION_ROOT` and
`NS_TEST_KEEP=1` for an isolated retained fixture; create the parent folders first.
Use your own image tags through `IMAGE` and `WEB_IMAGE`.

Manual steps and recorded results: [Small-image review](../docs/manual-validation.md#size-review).

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

Manual steps and recorded results: [Review workspace](../docs/manual-validation.md#review-workspace).

### Library-only review and job wording

The review API suite covers refusal of review writes outside active Library states,
reminders leaving the inbox when photos leave Library, retained history, and failed
sources excluded from photo/date statistics. Browser review and Rejects flows check
that source/rejected inspectors have no review/similarity actions. Shared browser checks
cover Job #ID · Action status, failure rechecks and the existing transfer workflows.

Run `DRIVER=source_scope_browser_drive.py` through the browser harness for generated
empty/text files with image extensions: separate ready/failure counts, saved review
links refused, failures excluded from Library/date filters, and Stats scope checks.

Manual steps and recorded results: [Review controls by location](../docs/manual-validation.md#location-review).

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

Manual steps and recorded results: [Alignment and filter persistence](../docs/manual-validation.md#alignment).

Automated source-filter checks passed: sidebar refinements, file-attention recovery, and
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

Review queue completion: remove the final bookmark with its Inspector
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

Manual steps and recorded results: [Notification bell and selection stability](../docs/manual-validation.md#notifications).

## Sidebar refinements and Bookmarks

Run `sidebar_refinements_test.py` inside the app image with `PYTHONPATH=/app/tests:/app`.
It checks intersecting counts, unchanged gallery membership, search scope, source warnings
and invalid inputs. `review_test.py` also checks preset validation, exact request replay,
Keep it history, independent size browsing and stable Bookmark ordering across pages.

`DRIVER=sidebar_refinements_browser_drive.py` uses the normal generated browser harness.
It checks combining refinements, exact navigation and Back, source scopes, selection,
Bookmark creation/completion, stable card widths when changing bookmark order,
delayed Inspector tabs, independent size browsing, keyboard
access, both themes and enlarged text. Existing review, attention, layout and similarity
drivers exercise the same controls in their complete workflows. Both suites and this
driver run in PR CI; extended navigation/layout/set drivers retain nightly/manual coverage.

Manual steps and results: [pending validation](../docs/manual-validation.md#pending-checks).
The historical pin walkthrough remains an acceptance record for the replaced design.

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

These tests cover `metadata_captures` and the snapshot's metadata-capture watermark.
Index records proposals only; activation, source tabs and sidecar transfer are covered
by their own suites below.
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
orphans and tentative primary precedence. The `metadata_test.py` tests cover shared lossless JSON validation. Parser and adapter
integration assertions exercise the production `metadata_capture.resolve` path. These suites do not establish XMP catalog durability or transfer
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

`xmp_store_test.py` covers compressed/raw
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
Decisions carry their own backup watermark. The decision UI is covered by the
first-import XMP choice checks. Index tests assert that a resolved pair uses captured
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
is required for this engine-only primitive; the web retry workflow has its own checks (R1–R3).

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
Asymmetric generated photos check embedded-orientation rehashing, new SHA-1/content/save
receipt agreement, unchanged visual identity after embedded date edits, unavailable
hashing without stale reuse, comparison refresh on Apply/Retry, and recoverable comparison
failure. Original source bytes and historical content hashes remain unchanged.
Reindex both completed and unfinished edits; exercise Reject/Return, detached duplicate
sources, confirmed exact-result consolidation and refusal without confirmation.
The duplicate suite also checks refreshed orientation hashes through consolidation,
including the surviving photo and immutable original-content history. Run all metadata,
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

Manual steps and recorded results: [Move after an embedded edit](../docs/manual-validation.md#edited-source-move).

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

Manual steps and recorded results: [Initial metadata editor acceptance](../docs/manual-validation.md#metadata-initial-acceptance).

### Read-only metadata source viewer

`metadata_view_test.py` checks capture-only versus verified primary, pending choices,
reindex after activation, source separation, explicit empties, unknown/oversized IDs,
content mismatch and unchanged catalog contents. Run with the standard Docker unittest
command. `METADATA_VIEW_FIXTURE=1 DRIVER=metadata_sources_browser_drive.py` uses the
browser harness's generated three-source photo to check real Index/Copy captures,
conflicting dates, Primary identity, comparison, field search, keyboard navigation,
light/dark reflow and failed-read retry. Both checks run in CI. The metadata test fixture
never reads the demo library. Date-copy/edit acceptance passed; primary-change controls
have their own acceptance (Test 10).

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

Manual steps and recorded results: [Metadata scenario viewer](../docs/manual-validation.md#metadata-viewer-cases).

Local validation: 61 photos indexed, 44 copied, 17 left at source with metadata holds.
The manifest browser check passed and all 61 metadata responses stayed unchanged.
The 12 source-view API tests passed. Screenshots inspected in light and dark/narrow
layouts. Maintainer acceptance is complete; date editing was accepted separately.

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

Manual steps and recorded results: [Original date-editor walkthrough](../docs/manual-validation.md#date-walkthrough).

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
selector accessibility at desktop and narrow widths.

Manual steps and recorded results: [Calendar and sidecar-version layout](../docs/manual-validation.md#date-picker-layout).

Recorded-tag comparison checks cover the union of both sources, changed/equal tags,
empty versus missing, reordered object keys, differences-only and search, comparison
off, and a source with no tags of its own. Desktop/narrow screenshots cover the expanded table.

### Inspector Metadata tab: final manual validation

Manual steps and recorded results: [Inspector Metadata tab](../docs/manual-validation.md#metadata-tabs).

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

Manual steps and recorded results: [Full demo and metadata scenario walkthrough](../docs/manual-validation.md#combined-library).

### Source and destination navigation validation

Manual steps and recorded results: [Source and destination navigation](../docs/manual-validation.md#source-navigation).

Source/destination navigation checks passed locally: frontend build; generated-fixture
filter-pin, source-scope, general UI and reference-set browser workflows; 475 spec
references and diff whitespace checks. Live read-only checks and inspected screenshots
cover desktop/narrow source navigation, attention counts and Library date filters.
The grouping test uses the Similar photos destination and combines refinements; its
old folder-popup expectations were replaced with the current source-only contract.
No engine change or catalog reset was needed for those navigation checks. Final editor
acceptance passed; GitHub checks remain a separate merge gate.

### Filter pin and gallery count follow-up

`sidebar_refinements_browser_drive.py` covers pinning two filters and unpinning each one:
active states, URL restrictions, chip counts and gallery rows update, and refresh keeps
both off. Removing an unapplied pin preserves an explicit job link. The unfiltered
place total appears in the sidebar, without another total above the gallery or in its
pager. Filtered results show matching and whole-place counts; set, selection and job
scopes retain their own totals. `layout_stability_browser_drive.py` checks unchanged
control positions as the count summary appears/disappears at desktop and narrow widths.
`review_browser_drive.py` retains zero/one-result and reminder-clearing coverage.

Manual steps and recorded results: [Filter pin and gallery count follow-up](../docs/manual-validation.md#pin-count-followup).

Automated follow-up validation: generated-photo filter-pin, layout-stability, review,
reference-set, gallery-position, source-scope and full browser workflows all pass.
The refinement fixture uses a date boundary that excludes some photos, so clearing filters must
actually broaden results. Desktop/narrow light/dark screenshots inspected; build and
specification checks pass. Maintainer acceptance passed (Test 1).


### Completed date-editor branch acceptance after review-control cleanup

Manual steps and recorded results: [Date-editor branch and follow-ups](../docs/manual-validation.md#date-editor).

Automated review-control cleanup checks: frontend build; nine generated Docker browser
workflows (sidebar refinements, layout stability, similarity comparison, Reject/Keep, review,
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

Manual steps and recorded results: [Incomplete photo/XMP transfer retry](../docs/manual-validation.md#pair-retry).

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

Manual steps and recorded results: [Metadata setup and Settings](../docs/manual-validation.md#metadata-settings).

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

Manual steps and recorded results: [Informational metadata warnings](../docs/manual-validation.md#reader-warnings).

## Date information versus source attention

Validation: all 16 metadata-view tests passed in Docker (0.537 seconds), including
repeated date diagnostics retaining every affected path. The metadata-source,
layout-stability and full web-interface browser drivers passed. Desktop and narrow
screenshots were inspected. App/web builds and specification/API/schema checks passed.

Manual steps and recorded results: [Date information and source attention](../docs/manual-validation.md#date-source-attention).

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

Manual steps and recorded results: [Settings grouping and message readability](../docs/manual-validation.md#readability).

## Expanded photo Inspector validation

The expanded view reuses the Inspector rather than a separate photo/details layout.
Automated checks passed in Docker: production frontend build/typecheck, all three
contract checks, the full web browser workflow (including shared UI checks), Similar
photos and metadata date editing. Coverage includes side-by-side geometry, tab and
photo navigation, resize/reflow, nested lineage/date dialogs and focus restoration.
Rendered desktop and narrow screenshots were inspected. No engine behavior changes.

Manual steps and recorded results: [Expanded photo Inspector](../docs/manual-validation.md#expanded-inspector).

## XMP import-choice validation

Automated: `metadata_choices_test.py` runs in the app image with unittest discovery.
It covers HTTP/engine binding, read-only preview, ownership/version saving, exact replay,
stale/conflicting requests, malformed input, active-job refusal and verified Copy.
`IMPORT_CHOICES_FIXTURE=1 DRIVER=import_choices_browser_drive.py` uses the browser harness
for cancellation, selection, comparison, responsive draft retention and real import.
Both run in PR/main CI. Generated fixtures are built by
`tests/browser/import_choices_fixture.py`; they do not use personal photos.

Automated results: production app/web builds, 140 focused API/metadata regressions,
the final 50-test import/decision run (including eight new choice tests), the real browser
workflow and all three
contract checks passed. Browser screenshots were inspected at desktop and narrow widths.
These checks do not replace maintainer acceptance or the full pre-push CI run.

Manual steps and recorded results: [XMP import choices and history](../docs/manual-validation.md#xmp-choices).

Automated coverage for this history includes paging, photo/search/date/job/status
filters, literal search escaping, shared candidates, request replay, revision retention,
unchanged operation counts, and rendering in Logs/lineage before and after real Copy
using generated fixtures. Existing manual Test 1 acceptance remains valid.

Automated comparison validation: 13 import-choice/history tests and 16 metadata-view
regressions passed. Generated browser workflows passed for import-choice comparisons
(including no active primary, excluded candidates, difference filtering, keyboard focus,
light/dark mode and resizing), existing source tabs and date editing/copying. App/web
builds and API/schema/spec checks passed. Historical values remain unchanged after a
later source-sidecar edit and Index; unrelated photo/choice IDs are refused. No UI
acceptance is inferred from these checks. The maintainer subsequently passed Test 5,
with a discoverability note for Metadata choices in Logs.

Manual steps and recorded results: [Saved-choice metadata comparison](../docs/manual-validation.md#choice-comparison).

Portrait-fit automated checks passed for portrait/landscape sizing, wide-layout detail
scrolling, divider resizing, reference labels and narrow reflow. The standard browser
suite passed on rerun; its first attempt stopped at page restoration before opening any
Inspector (the preceding build also passed). No pagination test or app behavior was
changed. Live demo portrait sizing was inspected before/after, with files unchanged.

Manual steps and recorded results: [Portrait sizing, choice visibility and inline rotation](../docs/manual-validation.md#portrait-and-rotation).

Automated `rotations_test.py` uses generated files for all eight orientations, mirrored
transforms, embedded pixel preservation, XMP-only writes, request replay, stale previews,
source/rejected refusals and malformed requests. Run in Docker like metadata_dates_test.py.
The generated import-choice browser workflow also exercises rotation confirmation,
preview refresh, reset, candidate navigation, exit/discard and responsive layout.


Visibility/rotation automation passed: 35 focused rotation/import/date tests, 90 existing
metadata planning/publication/viewer tests, the generated import/rotation browser workflow,
the similarity browser regression, and the standard browser workflow. API/schema/spec
contracts and production builds passed. This is targeted validation, not the full
pre-push suite. Maintainer Tests 7a/7b and 8a–8g passed.

Manual steps and recorded results: [Rotation history follow-up](../docs/manual-validation.md#rotation-history).

Rotation action-label follow-up: 123 rotation/date/API checks and the generated
browser workflow passed; API/schema/spec contracts and production builds passed.

Maintainer validation: **8d, 8e, 8f and 8g passed**. No repeat of those checks is
needed. The maintainer subsequently confirmed **8c passed** as well: the existing unsaved-turn navigation behavior works. A smaller prompt remains a separate UI-polish proposal; this pass does not claim that redesign was implemented.


Manual steps and recorded results: [Edits that create identical photos](../docs/manual-validation.md#edit-duplicates).

Generated automation: `metadata_duplicates_test.py` covers exact-result confirmation,
Rejects and primary conflicts, active/inactive sidecars, changed survivors, new matches
after preview, interrupted unlink/retry, reindex/Copy, later consented Move, job-gallery
membership and both histories after another edit. It runs in CI using the standard
unittest command. The `IMPORT_CHOICES_FIXTURE=1` browser driver covers rotation/date
confirmation, Cancel, survivor navigation, preserved sources and Logs. These checks do
not certify automatic cleanup of duplicates left by earlier releases. Production
image-content matching remains deferred.

Exact-result validation (2026-10-17): the 14 new duplicate cases passed within the
69-test duplicate/relocation/source-cleanup run (85.768s). The preceding metadata
regression run passed 224 tests (199.099s); the final Move/API/rotation run passed
122 (125.108s). These runs overlap; counts are not a unique-test total. The full
engine smoke runner passed 154, failed 0, skipped 0, including both public RAW
checks. Generated browser validation passed existing XMP choices, rotations and
reflow plus exact-result rotation/date confirmations, cancellation, preserved
sources, survivor navigation and Logs. App/web builds, API/schema/spec checks and
`git diff --check` passed. Maintainer confirmed all of Test 9 (9a–9d) passed; this is not a claim
that every suite in the repository was rerun or that the proposed compact exit-prompt redesign is implemented.


### Organized-photo primary source — Test 10 (10a–10e passed)

Manual steps and recorded results: [Changing an organized photo’s primary source](../docs/manual-validation.md#primary-source).

Automated coverage: `metadata_primary_ui_test.py` (8 tests) exercises real jobs,
all three sources, refiling, preserved bytes, request replay, stale settings, invalid
requests, eligibility, collisions, imported/saved sidecar reuse and refusal of
unassigned candidate XMP. The existing primary/save/view suites passed 67 additional
checks. The new browser driver passed Cancel/focus, three-source switches, file bytes,
source preservation, primary refresh, Logs, narrow reflow and 200% text scaling.
The final reindex regression and viewer checks passed together (24 tests).
API/schema/spec checks and image builds passed. The full engine smoke was not repeated
for this focused UI batch; its preceding branch run passed 154 tests, including RAW.

CI runs the Python suite and the generated browser workflow:

```sh
docker run --rm -v "$PWD":/app -w /app negativespace python3 -m unittest discover -s tests -p metadata_primary_ui_test.py -v
METADATA_VIEW_FIXTURE=1 DRIVER=metadata_primary_browser_drive.py sh tests/browser/webui_browser_test.sh
```

PR validation follow-up: final local metadata regressions passed 145 tests (149.846s),
plus API/schema/spec checks. CI caught a motion-photo test that expected refusal only
at Apply; it now checks both early preview refusal and the independent Apply gate,
with unchanged source/video assertions and no new metadata-save event. All four motion
tests passed (11.167s). CI also caught focus loss after discarding comparison turns:
discard no longer refreshes unchanged catalog results, so it does not remove the focused
opener. The unchanged strict similarity browser checks passed after that fix, as did
the generated import/rotation/consolidation browser workflow and web build.

The next CI browser pass exposed a stale thumbnail interception URL and a grid
refresh regression: healthy images reloaded after unrelated jobs. The driver now
intercepts grid URLs with revision parameters; its bounded-retry and healthy-image
assertions remain unchanged. Grid URLs use each photo's catalog revision, fetched
in one batch per page. A rotation regression checks that saving changes that
revision. Rotation/API checks passed 112 tests (108.797s), all three contract tools
passed, and both preview-refresh and import/rotation browser workflows passed.


### Low-detail matches

`low_detail_test.py` checks strict measurement boundaries, one decode for raster/RAW,
unchanged hashes, shared content persistence, real Index/Copy scenarios, match flags,
unchanged counts/grouping and Catalog health scope. Recovery and embedded-save suites
also verify that measurements follow verified bytes, including interrupted saves.
`low_detail_browser_drive.py` uses `LOW_DETAIL_FIXTURE=1` for generated moon, lamp,
city and flat scenes, checking match notes, scores, counts, Stats and 200% text scale.
Both run in PR CI; use the Docker commands and browser harness above.

Manual steps and recorded results: [Low-detail matches](../docs/manual-validation.md#low-detail).

### Sidebar and Stats cleanup validation

Automated coverage runs in the existing CI suites: `webui_api_test.py` verifies distinct
photo counts for saved metadata edits, failed refiles, no-op/failed writes, filtered Logs
and exports, and configured year bounds. `ui_browser_checks.py` verifies long year
ranges, separate suspicious-year counts, empty year slots, keyboard links and narrow
reflow. `sidebar_refinements_browser_drive.py` checks aligned row/count/pin columns and the
zero versus incompatible-count explanations, including full filter labels beside large
counts in normal and selected states. `fresh_start_browser_drive.py` holds back the
live feed to check immediate accepted-job display, stale snapshots and delayed start
responses after completion. It also checks HTTP recovery of a silent active feed,
progress and completion, stale HTTP replies, no idle polling, and the Index summary
waiting for completion; `metadata_settings_browser_drive.py`
checks the RAW sidecar-only statement. These browser checks use generated fixtures.

Maintainer checks for this batch use [Tests U1–U4](../docs/manual-validation.md#sidebar-stats).


### Shared Reject confirmation validation

The Rejects, comparison rejection, photo review, main-page, Move confirmation and
submission browser drivers passed in Docker. The first new focus assertion was
corrected to check restoration before resizing changes the underlying photo pane;
the final Rejects rerun passed. Existing coverage remains intact. The web build,
spec/schema/API checks and user-document link checks passed. Rendered questions were
inspected in dark/light mode and at narrow width with 200% text sizing.

Maintainer acceptance passed: [RC1–RC3, all steps](../docs/manual-validation.md#shared-reject).
Publication validation completed in Docker: 157 engine smoke tests (no skips, including
both public RAW checks), 575 metadata tests, 301 contract tests and 16 CI-routing tests
passed. All 38 browser workflows have passing results. The initial reference-set browser
run timed out waiting for the help window to scroll to the top; its unchanged isolated
rerun passed. No assertion was removed or weakened. All three tools/check-*.py checks
passed, along with 206 local documentation links/images and 117 linked anchors.
GitHub checks remain the final merge gate; maintainer approval has been given.

## Photo naming and compact rotation exit

CI runs `rename_ui_test.py` for verified photo/XMP renames, unchanged sources, request
replay, invalid inputs, collision races and filter/list/position agreement.
`photo_names_browser_drive.py` covers lazy alternative names, explicit rename,
Has other names without card/pagination shifts, both Rename entry points, enlarged-text
layout and compact rotation save/discard/refusal. Generated wide and tall image responses
check whole-photo fitting and aspect ratio after each turn in split and enlarged previews.
The Python suite also checks Rename outcome counts, no-op/failure/recovery separation,
and names from exact duplicates whose source was removed.
Existing import-choice and comparison drivers retain multi-photo exit coverage.
Run these with the standard Docker suite/browser harness instructions above.
Maintainer checks and acceptance: [NR1–NR3](../docs/manual-validation.md#photo-names-and-rotation-exits).

Initial batch Docker validation covered 51 Python suites (900 tests after the naming
additions), 157 engine smoke tests including both public RAW checks, all 40 browser
harness drivers and 11 supporting checks including all three `tools/check-*.py` tools.
The isolated metadata-scenario acceptance tool is read-only and separate from those
harness drivers; no reader/editor behavior changed in this batch.

Follow-up Docker validation passed 138 Python tests (naming, date editing and API),
seven affected browser workflows, the web build, all three specification/schema checks,
and 129 local documentation references including 99 anchors. The existing demo Rename
jobs now report their recorded successes without rerunning them. All manual follow-ups passed; acceptance is
recorded in the validation document.

On a generated 250,000-photo catalog with 2,500 different source names, the new
Has other names page query took a median 8.55s using per-comparison `Path.stem`
objects and 4.20s using equivalent string parsing (three runs each). Ordinary
browsing was 1.24s in the latter run. Query plans used status, SHA-1 and operation
photo-ID indexes. This optional history filter remains heavier than ordinary browsing;
these shared-host measurements are not a latency guarantee.

## Lineage timeline

`lineage_browser_drive.py` builds real generated histories for a simple Copy, five
identical files in one Index, five later arrivals in separate Indexes, and repeated
Reject/Return jobs. It checks grouped discovery paths, file-specific log links,
unchanged re-Index behavior, long-history collapse, sticky summary/Now, scroll cues,
keyboard dismissal/focus restoration, and narrow/200% text reflow. It runs in PR CI.
The API suite checks first-Index identity, recorded places after Reject/Return and
unchanged historical operation paths. The metadata consolidation suite retains
both original fingerprints through later edits. Browser regressions verify that
current hashes cannot rewrite discovery lanes, and that different sources join
only at the edit that made them identical. Failure details and a refused retry
remain accessible. The existing default and metadata-choice
browser drivers retain their lineage navigation and metadata-history checks.
Maintainer steps are in [manual validation](../docs/manual-validation.md#lineage-timeline).


### Catalog backup status

`webui_api_test.py` covers completed-run backup activity after API restart, interrupted
attempts, failure/retry without repeating file work, prompt busy refusals without a
queue, and reuse/invalidation of idle backup counts. The browser harness with
`BACKUP_FIXTURE=1 DRIVER=backup_browser_drive.py` runs real jobs and snapshots, holding
or failing only a generated fixture's backup. It checks Library/Logs/Stats progress,
disabled actions, failure notices, repeated retry, interrupted snapshots and successful
clearance. The fixture control lives only in the harness's disposable appdata.
Manual steps are in [manual-validation.md](../docs/manual-validation.md#catalog-backup-status).

### Date review and clearing history

`review_test.py` covers date confirmation, stale/replayed requests, independent
Bookmarks and size reminders, transactional clearing history, setting changes and
calendar rollover. `metadata_save_test.py` and `metadata_photo_save_test.py` cover
confirmation after verified XMP/JPEG date saves, interrupted-save recovery and
preservation across re-indexing. `sidebar_refinements_test.py` checks the date reason
and its counts. These suites run in the regular Python/metadata CI jobs.

The regular CI driver `suspicious_dates_browser_drive.py` also checks the date-review
queue, **This date is correct**, keyboard activation at 200% text, empty-queue cleanup,
and confirmed dates remaining in the factual Odd dates filter. Maintainer steps and
acceptance are recorded only in [manual validation](../docs/manual-validation.md#date-review-and-clearing-history).

Date-edit follow-up: `metadata_dates_test.py` covers advisory year boundaries,
verified job values, later edits and CSV/JSON exports; `rotations_test.py` checks
that an intent alone never claims a saved date. `metadata_dates_browser_drive.py`
covers the yellow confirmation warning, an enabled Save, and job Before/After details.
See [DR5](../docs/manual-validation.md#test-dr5--date-confirmation-warning-and-job-details)
for the only additional maintainer checks after DR1–DR4 acceptance.


### Bulk review answers

`review_test.py` covers shared-action eligibility, source/Rejects exclusion, content
and revision guards, independent concerns, bookmark notes, partial results, replay,
engine-lock refusal and transaction rollback. It runs in regular Python CI.
`bulk_review_browser_drive.py` runs in regular browser CI with generated photos: selection
bar, count confirmation, Cancel/Escape, 200% text, partial results, lost-response retry
and Keep history. Use `DRIVER=bulk_review_browser_drive.py` with the standard harness.
Manual checks and acceptance live in [manual validation](../docs/manual-validation.md#bulk-review-answers).

## Destination folder previews

`transfer_preview_test.py` covers actual date/Undated paths, source scoping, duplicate
and Rejects treatment, paged results, read-only previews, API/engine stale-state
checks, idempotent submission and XMP-primary filing against verified delivery.
`transfer_preview_browser_drive.py` checks shared confirmation placement, bounded
filename lists, Cancel/Escape/focus, enlarged text, stale refresh and confirmed Copy.
Both run in regular CI. Maintainer steps and acceptance live in
[manual validation](../docs/manual-validation.md).

Destination-folder preview maintainer checks: [TP1–TP3](../docs/manual-validation.md#destination-folder-preview).
