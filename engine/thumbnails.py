"""Grid thumbnails, detail previews and the thumbnail rebuild job."""

import collections
import contextlib
import io
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from engine.ns_db import RunStatus, RAW_EXTENSIONS
from engine import constants, deps, fileinfo, ns_db, runtime, store


class ThumbnailWriteError(Exception):
    """The cache could not be written — distinct from the photo failing to decode.

    Both surface as OSError, and they mean opposite things to a user: one is a
    full or read-only /cache, the other is a damaged photo. The UI shows
    different placeholder text for each (webui-spec.md 4.2.1), so the engine has
    to tell them apart rather than recording a generic failure.
    """


def sweep_orphan_thumbnails(db_path: str, cache_root: Path) -> int:
    """Deletes cached thumbnails whose content no catalogued photo holds any more.

    Runs after a scan that completed cleanly, and never with thumbnails disabled:
    deleting from the cache is a cache write. Catalog-wide rather than scoped to the
    run, because an entry is orphaned by the catalog as a whole. The file goes first
    and the record second, so a file that cannot be removed keeps its record and is
    retried next time; a record never outlives its file the other way round. Files in
    the cache with no record at all are left alone: the cache survives a catalog
    rebuild on purpose, and a fresh catalog has not yet claimed what it will reuse.
    """
    with contextlib.closing(store.get_db_connection(db_path)) as conn:
        orphans = ns_db.orphaned_thumbnails(conn)
        removed = freed = 0
        for content_id, size, name in orphans:
            if name:
                path = Path(cache_root) / name
                try:
                    freed += path.stat().st_size
                    path.unlink()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    runtime.logger.warning(f"Could not remove an orphaned thumbnail ({exc}); it will be retried.")
                    continue
            ns_db.forget_thumbnail(conn, content_id, size)
            removed += 1
    if removed:
        size = f"{freed / 1e6:.1f} MB" if freed >= 1e6 else f"{freed / 1e3:.0f} KB"
        runtime.logger.info(f"Removed {removed:,} thumbnail(s) whose content no catalogued photo holds any "
                    f"more ({size}).")
    return removed


def thumbnail_cache_path(cache_root, sha1_hash: str, size: int = constants.THUMBNAIL_SIZE) -> Path:
    """
    Where one content's thumbnail lives: <cache>/thumbnails/<ab>/<sha1>.jpg.

    Fanned out by the hash's first two characters so no directory holds tens of
    thousands of flat entries, and keyed by content hash rather than catalog id
    or path — so byte-identical duplicates share one file, and the cache
    survives a catalog rebuild where row ids would not.

    The grid size keeps the bare `<sha1>.jpg` name the README documents; any
    other size is suffixed. Without that, the 320px grid thumbnail and the
    1024px detail preview — separate rows, since thumbnail_cache is keyed on
    (content_id, size) — would collide on a single filename.
    """
    name = f"{sha1_hash}.jpg" if size == constants.THUMBNAIL_SIZE else f"{sha1_hash}-{size}.jpg"
    return Path(cache_root) / constants.THUMBNAIL_DIR_NAME / sha1_hash[:2] / name


def _write_thumbnail(img, dest: Path, size: int) -> int:
    """Downscale and write one JPEG atomically; returns its size in bytes.

    Written under a temporary name and renamed into place, so a killed engine
    never leaves a truncated JPEG that a later run would find and reuse as a
    cache hit — the reuse check trusts existence, and a half-written file would
    be silently wrong forever.
    """
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    # The real decode happens here, not at open(): a truncated or damaged photo
    # raises from this call, which is why it sits OUTSIDE the write guard below.
    img.thumbnail((size, size), deps.Image.LANCZOS)
    tmp = dest.with_name(dest.name + constants.THUMBNAIL_PARTIAL_SUFFIX)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(tmp, "JPEG", quality=constants.THUMBNAIL_JPEG_QUALITY, optimize=True)
        os.replace(tmp, dest)
        return dest.stat().st_size
    except OSError as e:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise ThumbnailWriteError(str(e)) from e


def _raw_preview(raw, size: int):
    """
    The adaptive RAW rule: probe the embedded preview, use it when its longest
    edge is at least the target, otherwise demosaic.

    A camera's embedded preview is the cheap path — about 17.8ms against 268ms
    to demosaic — but a preview existing is not enough: it must be large enough,
    or upscaling it would look worse than a fresh render. Probing and failing
    costs about 0.4ms, 0.15% of a demosaic, so the probe is effectively free and
    the rule self-tunes to whatever library it meets instead of baking in a
    threshold. In one 300-file sample only 26% of RAWs carried a usable preview
    at 320px, split almost entirely by format — so both paths are live.
    """
    try:
        thumb = raw.extract_thumb()
    except Exception:
        thumb = None
    if thumb is not None:
        try:
            if thumb.format == deps.rawpy.ThumbFormat.JPEG:
                preview = deps.Image.open(io.BytesIO(thumb.data))
            else:
                preview = deps.Image.fromarray(thumb.data)
            if max(preview.size) >= size:
                # The embedded preview is stored unrotated, carrying its own
                # orientation tag — measured landscape on a Rotate 90 CW file.
                # The demosaic below needs NO such call: LibRaw applies the
                # sensor flip itself, so transposing that would turn it twice.
                # A quarter turn does not change the longest edge, so the
                # size check above is unaffected by where this sits.
                return deps.ImageOps.exif_transpose(preview)
        except Exception:
            pass  # Unreadable preview is not a failure; fall through and render one.
    # half_size halves each dimension during demosaic, which is far cheaper and
    # still far larger than any thumbnail target. compute_phash() does the same.
    rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True, output_bps=8)
    return deps.Image.fromarray(rgb)


def generate_thumbnail(file_path: Path, sha1_hash: str, cache_root: str,
                       size: int = constants.THUMBNAIL_SIZE, replace: bool = False) -> runtime.ThumbnailResult:
    """
    Produce the grid thumbnail for one file. READS the photo and NEVER raises.

    A thumbnail is disposable cache, so nothing here may fail an otherwise
    successful Index (webui-spec.md 4.2.1). Every failure comes back as a
    recorded category and detail, which the UI turns into placeholder text —
    "Photo file unavailable", "Image could not be decoded" — rather than a
    blank tile with no explanation. A generic decoder failure is NOT evidence
    of corruption and is not reported as such.
    """
    dest = thumbnail_cache_path(cache_root, sha1_hash, size)
    relative = str(dest.relative_to(Path(cache_root)))

    # A cache hit is the point of keying on content: exact duplicates, including
    # copies in unrelated directories, reuse one render instead of each doing
    # their own. This is also what makes a re-Index nearly free. A full rebuild
    # (`replace`) skips it on purpose: its point is to redo files that exist.
    try:
        if replace:
            raise FileNotFoundError
        existing = dest.stat()
        if existing.st_size > 0:
            return runtime.ThumbnailResult(availability="present", cache_filename=relative,
                                   bytes=existing.st_size, reused=True)
    except OSError:
        pass

    if not deps.PIL_SUPPORTED:
        return runtime.ThumbnailResult(availability="failed", failure_category="decoder_unavailable",
                               failure_detail="Pillow is not installed")

    width = height = None
    try:
        with fileinfo.warnings_attributed_to(str(file_path)):
            if file_path.suffix.lower() in RAW_EXTENSIONS:
                if not deps.RAWPY_SUPPORTED:
                    return runtime.ThumbnailResult(
                        availability="failed", failure_category="decoder_unavailable",
                        failure_detail="rawpy is not installed; RAW files cannot be decoded")
                with deps.rawpy.imread(str(file_path)) as raw:
                    # sizes.width/height are PRE-flip: a portrait shot reports
                    # landscape here, because they describe the sensor rather
                    # than the photograph. LibRaw flip 5 and 6 are the quarter
                    # turns, so swap for those to record the shape the photo is
                    # actually displayed at.
                    width, height = int(raw.sizes.width), int(raw.sizes.height)
                    if raw.sizes.flip in (5, 6):
                        width, height = height, width
                    written = _write_thumbnail(_raw_preview(raw, size), dest, size)
            else:
                with deps.Image.open(file_path) as img:
                    # Read the dimensions BEFORE draft(): draft() replaces the
                    # image with a reduced-scale decode, so img.size afterwards
                    # is the decode size, not the photograph's real dimensions —
                    # and these are recorded on `contents` as facts about the
                    # content.
                    width, height = img.size
                    # A portrait photo is very often stored landscape with an
                    # EXIF orientation tag telling the viewer to rotate it. The
                    # dimensions that describe the CONTENT are the ones it is
                    # displayed at, so swap them for the quarter-turn values —
                    # otherwise every rotated photo in the library is recorded
                    # with its width and height the wrong way round.
                    orientation = img.getexif().get(0x0112, 1)
                    if orientation in (5, 6, 7, 8):
                        width, height = height, width
                    # Decodes AT a reduced scale rather than decoding fully and
                    # throwing most of it away: 8.2ms against 13.5ms.
                    img.draft("RGB", (size, size))
                    # Image.open() does NOT apply the orientation tag, but
                    # browsers and viewers do. Without this the thumbnail is
                    # rotated a quarter turn against the photo it represents —
                    # measured at 20.1% of a real library. Applied after draft()
                    # so the reduced-scale decode is still what gets rotated.
                    written = _write_thumbnail(deps.ImageOps.exif_transpose(img), dest, size)
    except ThumbnailWriteError as e:
        return runtime.ThumbnailResult(availability="failed", failure_category="cache_write_failed",
                               failure_detail=f"Thumbnail cache could not be written: {e}",
                               width=width, height=height)
    except FileNotFoundError:
        return runtime.ThumbnailResult(availability="failed", failure_category="file_unavailable",
                               failure_detail="Photo file unavailable", width=width, height=height)
    except PermissionError:
        return runtime.ThumbnailResult(availability="failed", failure_category="permission_denied",
                               failure_detail="Permission denied reading photo",
                               width=width, height=height)
    except Exception as e:
        runtime.logger.debug(f"Thumbnail generation failed for {file_path}: {e}")
        return runtime.ThumbnailResult(availability="failed", failure_category="decode_failed",
                               failure_detail=f"Image could not be decoded ({type(e).__name__})",
                               width=width, height=height)

    return runtime.ThumbnailResult(availability="present", cache_filename=relative, bytes=written,
                           width=width, height=height)


def catalogued_copies(conn, sha1: str) -> list:
    """Every catalogued copy of one content that could supply its pixels, as
    (path, recorded size, recorded mtime, file_id): delivered destination copies
    first, then sources not yet consumed. Nothing is checked on disk here, so the
    list can be handed to a worker process; see pick_unchanged_copy."""
    copies = conn.execute(
        "SELECT p.source_path, p.dest_path, p.status, p.file_size, p.file_mtime, pf.file_id "
        "FROM photos p LEFT JOIN photo_files pf ON pf.photo_id = p.id WHERE p.sha1_hash = ?",
        (sha1,)).fetchall()
    return _order_copies(copies)


def _order_copies(copies) -> list:
    """(source, dest, status, size, mtime, file_id) rows -> catalogued_copies order."""
    ordered = [(dst, size, mtime, fid) for _, dst, status, size, mtime, fid in copies
               if status in constants.ANCHOR_DELIVERED_STATUSES and dst]
    ordered += [(src, size, mtime, fid) for src, _, status, size, mtime, fid in copies
                if src and status not in constants.SOURCE_CONSUMED_STATUSES]
    return ordered


def pick_unchanged_copy(candidates: list):
    """The first candidate still on disk with the size and modification time the
    catalog recorded, as (path, file_id); None when there is none. An edited or
    replaced file is never used: it would put other content's pixels under this
    content's key."""
    for path, size, mtime, fid in candidates:
        try:
            st = os.stat(path)
        except OSError:
            continue
        if size is not None and st.st_size == size and mtime is not None and abs(st.st_mtime - mtime) < 1e-6:
            return path, fid
    return None


def preview_for_photo(db_path: Path, cache_root: Path, photo_id: int) -> dict:
    """The 1024px detail preview for one catalogued photo, generated on first request.

    The web API calls this through `--preview` when a photo is opened, so every image
    decode and every non-settings catalog write stays in the engine. It takes no engine
    lock: it changes no photo file, only a disposable cache image and its cache row,
    written in one short transaction, so it works while a job is running.

    Content-keyed, like the grid thumbnail: identical copies share one preview. It is made
    from any catalogued copy of the content — a delivered destination copy first, then a
    source that still exists — and only from a file whose size and modification time still
    match what the catalog recorded, so an edited or replaced file never lends its pixels to
    another content's preview. Uncatalogued files are never used.

    Returns {'photo_id', 'availability' ('present'|'failed'|'unavailable'), 'cache_filename',
    'bytes', 'reused', 'failure_category', 'failure_detail'}; the cache filename is relative
    to the cache root.
    """
    def answer(availability, cache_filename=None, size=None, reused=False, category=None, detail=None):
        return {"photo_id": photo_id, "availability": availability, "cache_filename": cache_filename,
                "bytes": size, "reused": reused, "failure_category": category, "failure_detail": detail}

    if not Path(db_path).exists():
        return answer("unavailable", category="no_catalog", detail="There is no catalog yet.")
    with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
        ns_db.require_schema(conn)
        row = conn.execute("SELECT sha1_hash FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if row is None:
            return answer("unavailable", category="unknown_photo", detail="No catalogued photo has this id.")
        sha1 = row[0]
        if not sha1:
            return answer("unavailable", category="no_content",
                          detail="This photo could not be read when it was catalogued, so there is "
                                 "nothing to preview.")
        cached = conn.execute(
            "SELECT t.cache_filename, t.bytes FROM thumbnail_cache t JOIN contents c USING(content_id) "
            "WHERE c.digest = ? AND t.size = ? AND t.availability = 'present'", (sha1, constants.PREVIEW_SIZE)).fetchone()
        if cached and (Path(cache_root) / cached[0]).is_file():
            return answer("present", cached[0], cached[1], reused=True)

        chosen = pick_unchanged_copy(catalogued_copies(conn, sha1))

        if chosen is None:
            result = runtime.ThumbnailResult(availability="failed", failure_category="file_unavailable",
                                     failure_detail="Photo file unavailable: no catalogued copy of this "
                                                    "photo is present and unchanged.")
            observed, fid = None, None
        else:
            observed, fid = chosen
            result = generate_thumbnail(Path(observed), sha1, str(cache_root), size=constants.PREVIEW_SIZE)
        with ns_db.transaction(conn):
            content_id = ns_db.content_for_digest(conn, digest=sha1)
            ns_db.record_thumbnail(conn, content_id=content_id, size=constants.PREVIEW_SIZE,
                                   availability=result.availability,
                                   cache_filename=result.cache_filename, bytes_on_disk=result.bytes,
                                   attempted_file_id=fid, observed_path=observed,
                                   failure_category=result.failure_category,
                                   failure_detail=result.failure_detail)
    if result.availability == "present":
        runtime.logger.info(f"Detail preview for photo #{photo_id} generated from {observed}.")
        return answer("present", result.cache_filename, result.bytes, reused=bool(result.reused))
    runtime.logger.warning(f"Detail preview for photo #{photo_id} unavailable: {result.failure_detail}")
    return answer("failed", category=result.failure_category, detail=result.failure_detail)


def clear_previews(db_path: Path, cache_root: Path) -> dict:
    """Removes every recorded detail preview, leaving grid thumbnails alone.

    webui-spec 4.2.1 "Free up": previews are recreated on the next view, so nothing is
    lost. Takes no engine lock, for the same reason --preview takes none. Racing a
    --preview is harmless: the worst case is a record whose file has gone, and a
    preview request checks the file and regenerates it.

    Only recorded files are removed, so what is freed matches the total the page
    showed (thumbnail_cache_totals). As in sweep_orphan_thumbnails, the file goes
    before its record, and a file that cannot be removed keeps its record. The
    records are deleted together at the end: one transaction instead of one per file.

    Returns {'removed', 'bytes_freed', 'not_removed'}.
    """
    removed, freed, not_removed = [], 0, 0
    if not Path(db_path).exists():
        return {"removed": 0, "bytes_freed": 0, "not_removed": 0}
    with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
        ns_db.require_schema(conn)
        for content_id, name in ns_db.present_thumbnails(conn, constants.PREVIEW_SIZE):
            path = Path(cache_root) / name
            try:
                freed += path.stat().st_size
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                runtime.logger.warning(f"Could not remove a detail preview ({exc}); its record is kept.")
                not_removed += 1
                continue
            removed.append(content_id)
        with ns_db.transaction(conn):
            conn.executemany("DELETE FROM thumbnail_cache WHERE content_id = ? AND size = ?",
                             [(cid, constants.PREVIEW_SIZE) for cid in removed])
    runtime.logger.info(f"Cleared {len(removed):,} detail preview(s), {freed / 1e6:.1f} MB"
                + (f"; {not_removed:,} could not be removed." if not_removed else "."))
    return {"removed": len(removed), "bytes_freed": freed, "not_removed": not_removed}


def _rebuild_thumbnail_task(sha1: str, candidates: list, cache_root: str, replace: bool):
    """One content's grid thumbnail for the rebuild job, in a worker process.

    Returns (sha1, outcome, ThumbnailResult, observed_path, file_id). Outcomes:
    'made'; 'already' (scope `missing`, a thumbnail is on disk); 'kept' (scope `all`,
    nothing usable to regenerate from, or regeneration failed - the existing file was
    made from this same content, so it stays and stays recorded); 'failed'.
    """
    dest = thumbnail_cache_path(cache_root, sha1)
    try:
        on_disk = dest.stat().st_size
    except OSError:
        on_disk = 0
    existing = runtime.ThumbnailResult(availability="present", cache_filename=str(dest.relative_to(Path(cache_root))),
                               bytes=on_disk, reused=True)
    if on_disk and not replace:
        return sha1, "already", existing, None, None
    chosen = pick_unchanged_copy(candidates)
    if chosen is None:
        if on_disk:
            return sha1, "kept", existing, None, None
        return sha1, "failed", runtime.ThumbnailResult(
            availability="failed", failure_category="file_unavailable",
            failure_detail="Photo file unavailable: no catalogued copy of this photo is present "
                           "and unchanged."), None, None
    path, fid = chosen
    result = generate_thumbnail(Path(path), sha1, cache_root, replace=replace)
    if result.availability != "present" and on_disk:
        runtime.logger.warning(f"Could not regenerate the grid thumbnail from {path} ({result.failure_detail}); "
                       f"the existing one is kept.")
        return sha1, "kept", existing, path, fid
    return sha1, ("made" if result.availability == "present" else "failed"), result, path, fid


def rebuild_thumbnails(db_path: Path, cache_root: Path, scope: str,
                       worker_count: int, log_dir: Path) -> str:
    """The body of a Rebuild grid thumbnails job (webui-spec 4.2.1). Returns the run outcome.

    Scope `missing` makes only the grid thumbnails that are not on disk (including
    recorded failures, which are retried). Scope `all` regenerates every one. That is
    for thumbnails that exist but are wrong, and it replaces a thumbnail only when an
    unchanged catalogued copy can supply it. Every content any catalogued photo holds is
    covered, from a delivered destination copy or a source still present - which is
    what a re-Index cannot do: it skips unchanged files, and a moved photo has no source.

    Cache only: no photo is touched and no operation is recorded, so the job takes no
    backup. Progress is reported as counts, never as a time estimate: a RAW file costs
    18ms or 268ms depending on its embedded preview, which is unknown until it is opened.
    """
    replace = scope == "all"
    (cache_root / constants.THUMBNAIL_DIR_NAME).mkdir(parents=True, exist_ok=True)
    work = {}
    with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
        for sha1, *row in conn.execute(
                "SELECT p.sha1_hash, p.source_path, p.dest_path, p.status, p.file_size, p.file_mtime, "
                "pf.file_id FROM photos p LEFT JOIN photo_files pf ON pf.photo_id = p.id "
                "WHERE p.sha1_hash IS NOT NULL ORDER BY p.id"):
            work.setdefault(sha1, []).append(tuple(row))
        recorded = {d for (d,) in conn.execute(
            "SELECT c.digest FROM thumbnail_cache t JOIN contents c USING(content_id) "
            "WHERE t.size = ? AND t.availability = 'present'", (constants.THUMBNAIL_SIZE,))}
    total = len(work)
    runtime.logger.info(f"Rebuilding grid thumbnails ({'every one' if replace else 'missing ones only'}) "
                f"for {total:,} catalogued photo content(s).")
    counts = collections.Counter()
    runtime.run_progress.start("rebuilding_thumbnails", total)
    done, last_progress_at = 0, time.monotonic()
    batch_size = max(worker_count * 4, 16)
    items = list(work.items())
    outcome = RunStatus.COMPLETED
    with ProcessPoolExecutor(max_workers=worker_count, initializer=fileinfo._init_worker_process,
                             initargs=(False, str(log_dir))) as executor, \
            contextlib.closing(store.get_db_connection(str(db_path))) as conn:
        for start in range(0, total, batch_size):
            if runtime.cancel_requested.is_set():
                runtime.logger.warning(f"Cancellation requested - stopping the rebuild after {done:,} of {total:,}. "
                               f"Thumbnails already made are kept.")
                outcome = RunStatus.CANCELLED
                break
            futures = [executor.submit(_rebuild_thumbnail_task, sha1, _order_copies(copies),
                                       str(cache_root), replace)
                       for sha1, copies in items[start:start + batch_size]]
            results = [f.result() for f in futures]
            with ns_db.transaction(conn):
                for sha1, kind, result, observed, fid in results:
                    counts[kind] += 1
                    runtime.run_progress.add(kind)
                    if kind in ("already", "kept") and sha1 in recorded:
                        continue
                    ns_db.record_thumbnail(
                        conn, content_id=ns_db.content_for_digest(conn, digest=sha1), size=constants.THUMBNAIL_SIZE,
                        availability=result.availability, cache_filename=result.cache_filename,
                        bytes_on_disk=result.bytes, attempted_file_id=fid, observed_path=observed,
                        failure_category=result.failure_category, failure_detail=result.failure_detail)
                runtime.run_progress.write(conn)
            done += len(results)
            if time.monotonic() - last_progress_at >= constants.PROGRESS_INTERVAL_SECONDS:
                runtime.logger.info(f"Rebuilding grid thumbnails: {done:,} of {total:,}.")
                last_progress_at = time.monotonic()
    runtime.logger.info(f"Grid thumbnail rebuild: {done:,} of {total:,} checked - {counts['made']:,} made, "
                f"{counts['already']:,} already present, {counts['kept']:,} kept (no unchanged copy to "
                f"regenerate from, or regeneration failed), {counts['failed']:,} unavailable.")
    return outcome
