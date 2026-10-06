# Running the engine directly

Most people use NegativeSpace through its web interface, which runs this same engine for
them (see the [README](../README.md)). This page is for development, debugging and
scripting: the engine's modes and options as a command (`ns-engine.py`). Its full
behaviour is in [engine-spec.md](engine-spec.md), and every flag is listed by
`python3 ns-engine.py --help` and the module docstring at the top of `ns-engine.py`.

The commands use the `app` image, built from the repository root:

```bash
docker build -f docker/app.Dockerfile -t negativespace .
```

## Operations Summary

NegativeSpace has three mutually exclusive modes. `--move` and `--copy` cannot be combined — pick at most one:

| Mode | Flag | Source files | Destination |
| --- | --- | --- | --- |
| **Index** (default) | *(none)* | Untouched | Nothing written |
| **Move** | `--move` | Deleted after a verified copy lands at destination; confirmed exact duplicates are also removed from source | Files organized under `library/` into `YYYY/MM/DD`, or `Undated/<year>/` when the engine cannot date them |
| **Copy** | `--copy` | Never touched — fully non-destructive | Files organized under `library/` into `YYYY/MM/DD`, or `Undated/<year>/` when the engine cannot date them |

**Rejecting** a photo you do not want (a website download, a blurry shot) moves it from `library/` to the same folders under `rejects/` in the destination (`--reject` with `--file-ids`, `--file-ids-from` or `--source-subdir`; in the web interface, the selection bar's Reject or **Reject…** on a photo). NegativeSpace never deletes it: look through the Rejects view, use Return to library for any you want back, then empty `rejects/` yourself. Identical copies stay out of the library: Copy skips them and Move removes their sources only against the verified copy in Rejects.

The Destination column describes `/data/dest` only. Every mode begins with a scan, and the scan generates thumbnails into `/cache` (see the volume notes in the [README](../README.md#notes-and-details)) unless `--no-thumbnails` is passed — so "nothing written" above means nothing written *to the destination tree*, not that Index writes nothing at all.

## Index

Scan, extract metadata, hash every file (SHA1 + pHash), generate grid thumbnails, and catalog everything into SQLite — including flagging exact duplicates — without moving, copying, or deleting anything. Mount `/data/source` as read-only (`:ro`) for safety; Index never needs write access to it.

```bash
docker run --rm --stop-timeout 300 \
  -e PUID=$(id -u) -e PGID=$(id -g) \
  -v /path/to/your/photos:/data/source:ro \
  -v /path/to/organized:/data/dest \
  -v /path/to/appdata:/appdata \
  -v /path/to/backups:/backups \
  -v /path/to/cache:/cache \
  negativespace python3 ns-engine.py
```

Mounting `/cache` is optional — left unmounted, thumbnails live in the container's writable layer and are regenerated after the container is replaced. Two flags control this:

| Flag | Default | Effect |
| --- | --- | --- |
| `--cache` | `/cache` | Directory holding generated thumbnails. Written only by the scan phase. |
| `--no-thumbnails` | *(off)* | Skip generation entirely. Cataloguing is unchanged; the gallery shows placeholders until a later run generates them. |

A thumbnail is disposable cache and never decides whether a file is catalogued: an unreadable photo, a full disk or an unwritable `/cache` records the reason and lets the Index finish normally.

## Move (Copy-Verify-Delete)

Performs pre-flight disk space validation, copies files, verifies SHA1 checksums, and only then deletes originals from the source folder. Confirmed exact duplicates are also removed from source once a verified copy of their content exists at the destination. **Drop `:ro`** — this mode deletes from source, so the container needs write access to it.

```bash
docker run --rm --stop-timeout 300 \
  -e PUID=$(id -u) -e PGID=$(id -g) \
  -v /path/to/your/photos:/data/source \
  -v /path/to/organized:/data/dest \
  -v /path/to/appdata:/appdata \
  -v /path/to/backups:/backups \
  negativespace python3 ns-engine.py --move
```

## Copy (non-destructive)

Same verified Copy-Verify step as Move, but the source file is never deleted or modified — nothing is ever removed from source, including duplicates. Because of this, `/data/source` can safely **stay `:ro`** even in this mode, unlike `--move`.

```bash
docker run --rm --stop-timeout 300 \
  -e PUID=$(id -u) -e PGID=$(id -g) \
  -v /path/to/your/photos:/data/source:ro \
  -v /path/to/organized:/data/dest \
  -v /path/to/appdata:/appdata \
  -v /path/to/backups:/backups \
  negativespace python3 ns-engine.py --copy
```

> **Note:** `--move` against a read-only-mounted source will not corrupt anything: the copy succeeds and only the source deletion fails, so each photo is recorded `Copied`, its operation giving the reason the original was kept, and nothing is ever lost. Re-running is safe and does **not** accumulate duplicate copies: the engine recognizes that an identical copy already exists at the destination and skips rewriting it. Once the source is writable, `--move` finishes the job by deleting the originals. Use `--copy` for read-only sources instead — it is the same verified copy without the futile delete step.

---
