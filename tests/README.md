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
