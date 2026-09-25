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

## Spec and schema checks — `tools/`

Not tests of the engine, but CI gates on them and they exit non-zero on failure:

```bash
python3 tools/check-specs.py          # cross-references resolve, fences balance, tables are whole
docker run --rm -v "$PWD":/app -w /app negativespace python3 tools/check-schema-drift.py
                                      # engine-spec 6.5 matches what the engine creates
```
