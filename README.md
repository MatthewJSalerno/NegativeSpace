# NegativeSpace

A backend engine for organizing large photo collections based on EXIF metadata, hash verification, and transactional file moves.

## Documentation

Specifications are organized by component, not by release phase:

| Document | Covers |
| --- | --- |
| [project-spec.md](docs/project-spec.md) | Scope boundary, architecture, and what exists today — start here |
| [engine-spec.md](docs/engine-spec.md) | `ns-engine.py`: hashing, metadata, placement, Copy-Verify-Delete, and the SQLite catalog it owns |
| [webui-spec.md](docs/webui-spec.md) | The browser-facing half: jobs, selection, settings, logs, inspection, curation |
| [TODO.md](TODO.md) | Durability claims that need enforcing, and work deliberately postponed |

## Docker Usage

> **Never mount source and destination to the same underlying folder, or place either folder inside the other.** Different container paths (`/data/source` and `/data/dest`) do not make the storage separate. Check the host folders or network-share mappings, including NFS. Overlapping locations can cause unintended processing or deletion of your photos. This configuration is unsupported. The engine refuses to start when it can see the overlap (the same folder, one inside the other, or one folder mounted at both paths) and never deletes a source that turns out to be the same file as its copy — but it cannot see every alias, such as two separate network mounts of one share.

### Build

```bash
docker build -t negativespace .
```

### Tests

The engine has an end-to-end smoke suite. It drives the real engine as a subprocess against real image files rather than importing it and stubbing things out, so it needs ExifTool, Pillow, imagehash and rawpy — which the image already has. **Run it in the container**, mounting your checkout over `/app` so it tests the code you have rather than the code baked into the image:

```bash
docker run --rm -v "$PWD":/app -w /app negativespace python3 tests/engine_smoke_test.py
```

A green run reports `N passed, 0 failed, 1 skipped`. The expected skip is the RAW decode path, which no synthetic fixture can reach — LibRaw rejects fabricated files — so it runs only when `NS_TEST_RAW_DIR` points at a folder of genuine camera output. Worth doing at least once.

There is a **second suite** covering the catalog's contracts — schema initialization, settings revisions, concurrent writers, transaction rollback and lineage invariants — which runs against synthetic catalogs and needs no image files:

```bash
docker run --rm -v "$PWD":/app -w /app negativespace python3 -m unittest discover -s tests -p database_test.py
```

CI runs both on every push.

**A catalog from an older schema is refused, not migrated.** The engine stamps a schema version and fails closed on one it does not recognise, rather than altering a database it may not understand. Preserve the old catalog and let a fresh one be created; everything in `photos` is derived from your source files and is rebuilt by an Index. `runs` and `operations` are not derived — see `/backups` below.

Useful flags: `--filter NAME` to run a subset, `--keep` to leave the workspace on disk, `-v` to show engine output. `tests/engine_smoke_test.py --help` and the file's module docstring are the authoritative reference.

### Operations Summary

NegativeSpace has three mutually exclusive modes. `--move` and `--copy` cannot be combined — pick at most one:

| Mode | Flag | Source files | Destination |
| --- | --- | --- | --- |
| **Index** (default) | *(none)* | Untouched | Nothing written |
| **Move** | `--move` | Deleted after a verified copy lands at destination; confirmed exact duplicates are also removed from source | Files organized into `YYYY/MM/DD`, or `Undated/<year>/` when the engine cannot date them |
| **Copy** | `--copy` | Never touched — fully non-destructive | Files organized into `YYYY/MM/DD`, or `Undated/<year>/` when the engine cannot date them |

### Run (Index — Default)

Scan, extract metadata, hash every file (SHA1 + pHash), and catalog everything into SQLite — including flagging exact duplicates — without moving, copying, or deleting anything. Mount `/data/source` as read-only (`:ro`) for safety; Index never needs write access to it.

```bash
docker run --rm \
  -e PUID=$(id -u) -e PGID=$(id -g) \
  -v /path/to/your/photos:/data/source:ro \
  -v /path/to/organized:/data/dest \
  -v /path/to/appdata:/appdata \
  negativespace
```

### Run (Move — Copy-Verify-Delete)

Performs pre-flight disk space validation, copies files, verifies SHA1 checksums, and only then deletes originals from the source folder. Confirmed exact duplicates are also removed from source once a verified copy of their content exists at the destination. **Drop `:ro`** — this mode deletes from source, so the container needs write access to it.

```bash
docker run --rm \
  -e PUID=$(id -u) -e PGID=$(id -g) \
  -v /path/to/your/photos:/data/source \
  -v /path/to/organized:/data/dest \
  -v /path/to/appdata:/appdata \
  negativespace python3 ns-engine.py --move
```

### Run (Copy — Non-Destructive)

Same verified Copy-Verify step as Move, but the source file is never deleted or modified — nothing is ever removed from source, including duplicates. Because of this, `/data/source` can safely **stay `:ro`** even in this mode, unlike `--move`.

```bash
docker run --rm \
  -e PUID=$(id -u) -e PGID=$(id -g) \
  -v /path/to/your/photos:/data/source:ro \
  -v /path/to/organized:/data/dest \
  -v /path/to/appdata:/appdata \
  negativespace python3 ns-engine.py --copy
```

> **Note:** `--move` against a read-only-mounted source will not corrupt anything, but every file will report `status='Failed'` — the copy succeeds and only the source deletion fails, so nothing is ever lost. Re-running is safe and does **not** accumulate duplicate copies: the engine recognizes that an identical copy already exists at the destination and skips rewriting it, failing only on the delete. Use `--copy` for read-only sources instead — it is the same verified copy without the futile delete step.

---

## Configuration & Notes

- **User Mapping:** `PUID`/`PGID` match the container process permissions to your host user, preventing root-owned output files. On start, the container gives that user ownership of all of `/appdata`, but only the top of `/data/dest`. Folders and files already in the destination keep their owners, so use the same `PUID`/`PGID` every time. The container refuses to start if `/appdata` is not writable by that user, and warns if `/data/dest` is not.
- **Timezone (`TZ`):** Controls which `Undated/<year>/` folder a photo lands in when it has **no usable EXIF date** and the engine falls back to the file's modification time. A container does **not** inherit your workstation's timezone — it runs UTC unless told otherwise — so a file modified at 21:00 local time is read as the *next* day. Pass your zone to avoid that:

  ```bash
  -e TZ=America/New_York
  ```

  Photos that *do* carry an EXIF date are unaffected: those timestamps have no timezone attached and are used exactly as the camera recorded them, which is almost always what you want. The engine logs the zone it resolved at startup (`Timezone: EDT (UTC-0400)`), so you can confirm the setting took effect rather than assuming it did.

  Because an undated photo is filed under `Undated/<year>/` (see below), the timezone changes its **folder** only when the mtime falls within a few hours of New Year. It still decides the day recorded as that photo's date in the catalog, which is what the 21:00 example above describes — so the setting is worth getting right either way.
- **Undated photos:** A photo the engine cannot date does **not** enter the date tree. It goes to `Undated/<year>/`, where the year comes from the file's modification time.

  This is deliberate. The modification time is a real fact about the *file* but not about the *photograph* — for an export it is the download date, which is how photos from the 2000s can end up looking like 2024 photographs. Filing them beside photos whose dates came from a camera makes a guess indistinguishable from a fact. Roughly **8%** of a real library has no usable EXIF date, so this is not a rare corner.

  `Undated/` is also where you go to fix them: the folder *is* the review list, and the catalog records each photo's original path and filename, which is frequently where the real date turns out to be.
- **Volume Layout:**
  - `/data/source`: Raw input directory containing photos.
  - `/data/dest`: Structured target directory organized by `YYYY/MM/DD`, with photos the engine could not date filed under `Undated/<year>/` instead.
  - `/appdata`: Dedicated application directory storing persistent data inside `/appdata/db` and log files inside `/appdata/logs`.
  - `/cache` *(optional)*: Thumbnail cache. **Index writes here** when thumbnail generation is enabled — it is the only engine operation that does; Move and Copy ignore it. It is kept separate from `/appdata` on purpose: everything in `/appdata` is irreplaceable and should be backed up, whereas every file here is reproducible from the photo it was generated from. Deleting it costs only the time to regenerate, and it should be **excluded** from backups rather than included. Mount it to keep thumbnails when the container is replaced; leave it unmounted and they live in the container's writable layer instead.

    Thumbnails live under `/cache/thumbnails/`, keyed by the photo's **content hash** rather than its catalog id or path, and fanned out by the hash's first two characters: `/cache/thumbnails/ab/abcdef….jpg`. The `thumbnails/` segment exists so a future cache of some other kind has an obvious place to go rather than being mixed in beside these. Byte-identical duplicates share a single thumbnail instead of generating one apiece, and the cache survives a catalog rebuild, since content hashes are stable where row ids are not.
  - `/backups`: Catalog backups for the web interface. **The engine never writes here** — this is unused when running the engine directly as documented above.

    **Kept separate from `/appdata` on purpose, and for the opposite reason to `/cache`.** A backup written inside the directory it is backing up dies with it, and losing `/appdata` is exactly the failure a backup exists to survive. Mount it on different storage from the catalog if you can.

    **Unlike `/cache`, these are not disposable.** `photos` can be rebuilt by re-running an Index, but `runs` and `operations` cannot — nothing recomputes what the engine *did*. After a `--move`, a `Removed_Duplicate` row is the only remaining evidence a file ever existed. So this directory holds the only copy of your library's history: include it in your own backups, and do not prune it the way you would a cache.
- **Persistence:** SQLite database (`ns_sqlite.db`) stores SHA1 checksums, perceptual hashes, and status to prevent re-processing across multiple runs. The storage engine is named in the file so a second store can sit beside it later without ambiguity.
- **Date & Metadata Resolution:** ExifTool is a **hard requirement** — the engine won't start without it (both the `exiftool` binary and the `PyExifTool` Python package). It runs as a persistent process per worker rather than spawning a subprocess per file, cutting ExifTool overhead roughly 30x. PIL and file-modification-time remain as defensive per-file fallbacks for the rare case ExifTool itself fails on one specific file — see `ns-engine.py`'s module docstring for the full breakdown.
- **Single-Instance Lock:** Only one engine process may run against a given `--base` (i.e., a given `/appdata` mount) at a time — enforced via an OS-level `flock` on `/appdata/engine.lock`.

  **`engine.lock` is always present, including when nothing is running — this is normal.** The file is not the lock; it is just something to hold a lock on. `flock` is a kernel-side lock keyed to an *open file descriptor*, so it disappears the moment the process's descriptors close and the leftover file means nothing on its own. That is the reason for choosing `flock` over a PID file or an "exists = busy" marker: those leave a stale marker after a hard kill and then need liveness probing and a manual override, each of which can either deadlock the tool or let two writers run at once. Here the kernel releases the lock on *every* exit path — clean exit, unhandled exception, `SIGKILL`, OOM-kill, power loss — so a force-stopped container never needs the file cleaned up by hand.

  The file's contents (`PID 1 — held since 2026-...`) are diagnostic only and describe whichever process held it last, not a current one. You can delete it safely while nothing is running, though there is no reason to; deleting it *during* a run is mildly unsafe, since a second process would create a new inode and lock that instead.

  **NFS caveat:** `flock` reliability is weaker over NFS depending on the server/client's `lockd`/`statd` setup — fine for local disk or a standard Docker volume backing `/appdata`, but worth a second look if that mount is ever NFS-backed instead. Note this applies to `/appdata` only: an NFS-mounted `/data/source` has no bearing on the lock.

  **A second, unrelated NFS caveat — this one for `/data/dest`.** A share exported `async` can acknowledge an `fsync` before the data has actually reached the server's disk. `--move` deletes a source only after fsyncing the copy, the copy's own directory entry, and every directory entry from `--dest` down to it — but those barriers are only as good as the server's honesty about them, and a server that lies about `fsync` makes the whole chain advisory. On such a share the power-loss guarantee is weaker than it appears, and **the engine cannot detect this**: a successful `fsync` return is all it ever sees. Local disk for `/data/dest` — the tested configuration — is unaffected, as is an NFS-mounted `/data/source`, since nothing is written there. If you do point `--dest` at an NFS share, export it `sync`.
- **One catalog per destination.** Because the lock is per `/appdata`, two containers using **different** `/appdata` mounts are not serialised against each other at all. Pointing them at one shared `/data/dest` is **unsupported**.

  Your photos are not at risk if you do it — a source is only ever deleted after the engine doing the deleting has verified, live, the copy it made itself. What you get instead is unexplained failures: crash recovery in one catalog can delete a partial file the other is still writing, both can pick the same free filename and one loses the race, and neither knows about the other's files, so the same photo can be delivered twice under different names. Each of those ends as a recorded failure or a redundant copy, never a lost original.

  Use one `/appdata` per destination. Several *sources* feeding one destination is fine — that's one catalog with several runs, which is exactly what it's built for.
- **If a run appears stuck.** Cancellation is checked between files, and between batches during a scan, so a worker blocked indefinitely — an unresponsive network mount, a native decoder wedged on a malformed file — can stall a scan with no deadline. The symptom is progress lines stopping while the container stays alive.

  `docker stop` is the remedy, and it is safe: it escalates to `SIGKILL`, the kernel releases the lock immediately, and the next run marks the interrupted run `Crashed` and settles any file left mid-operation. Nothing needs cleaning up by hand.

  The *unbounded wait* is specific to the scan, where the engine waits on worker processes with no deadline. A blocking filesystem call — a hung network mount, a disk that stops answering — can stall either phase, a copy or a delete included; being single-threaded governs how much runs at once, not whether a call ever returns. `docker stop` is the answer in both cases, and a stall during a Move leaves the source file where it is.
- **Supported Formats:** 36 extensions — 13 raster (`.jpg`, `.jpeg`, `.jpe`, `.jfif`, `.png`, `.gif`, `.bmp`, `.webp`, `.tif`, `.tiff`, `.heic`, `.heif`, `.avif`) and 23 RAW (`.raw`, `.dng`, `.cr2`, `.cr3`, `.crw`, `.nef`, `.nrw`, `.arw`, `.srf`, `.sr2`, `.raf`, `.orf`, `.rw2`, `.pef`, `.ptx`, `.srw`, `.erf`, `.3fr`, `.fff`, `.iiq`, `.mos`, `.mrw`, `.x3f`). RAW files are decoded via rawpy/LibRaw; the two sets are defined as `RASTER_EXTENSIONS` and `RAW_EXTENSIONS` in `ns-engine.py`, with the supported set derived as their union. Narrow a run with `--exts` (dots optional: `--exts jpg,cr2` and `--exts .jpg,.cr2` are equivalent).

  **The engine only ever operates on files it supports.** Anything else in `--source` — sidecars, videos, documents, previews, stray archives — is left exactly where it is, untouched and unrecorded. A `--move` therefore does not empty the source directory, and is not meant to: it moves what it can, and reviewing what remains is yours to do. Expect leftovers, and expect them to be the files this tool was never asked to handle.
