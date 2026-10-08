"""Reading a file: dates and metadata (ExifTool, then Pillow), SHA-1 and pHash."""

import contextlib
import hashlib
import os
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

from engine.ns_db import RAW_EXTENSIONS
from engine import constants, deps, durable, runtime


# --- Dates ---
def parse_exif_date(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(str(value)[:19], '%Y:%m:%d %H:%M:%S')
    except (ValueError, TypeError):
        return None


# --- Persistent Per-Worker ExifTool Process ---
# ProcessPoolExecutor spawns separate OS processes, so a single shared
# ExifTool instance can't be passed between them. Instead, each worker
# process gets its OWN persistent ExifTool subprocess, started once (via
# ProcessPoolExecutor's `initializer=`) and reused for every file that
# worker handles — this is what actually delivers the performance win:
# avoiding a fresh subprocess spawn per FILE, not per worker. Verified via
# direct timing: a repeat query against an already-running instance took
# ~2.6ms vs ~24ms+ for one paying process-spawn overhead — roughly a 10x
# difference that compounds across a large library.
_worker_exiftool: Optional["deps.pyexiftool.ExifToolHelper"] = None

# Consecutive ExifTool failures in this worker. The self-healing respawn below
# is worth doing for a one-off bad file, but repeating it forever is not: if
# ExifTool is broken in this process rather than confused by one image, every
# subsequent file pays a terminate-and-respawn: measured at 4.75 seconds PER
# FILE with the CPU almost idle (112% of 2400% available). After this many consecutive failures the worker stops trying and
# falls through to the PIL path, which is the documented fallback anyway.
_worker_exiftool_failures = 0
MAX_CONSECUTIVE_EXIFTOOL_FAILURES = 3


def _init_worker_process(exiftool_supported: bool, log_dir: Optional[str] = None):
    """
    ProcessPoolExecutor initializer — runs once when each worker process
    starts, before it's given any files. Sets up this worker's logging and
    its persistent ExifTool instance, and registers cleanup so the ExifTool
    subprocess doesn't outlive its parent worker.

    Logging is configured explicitly here rather than relying on the worker
    inheriting the parent's handlers, because that inheritance only happens
    under the `fork` start method. Verified directly: a forked worker sees
    the parent's handlers and its records reach organizer.log, but a spawned
    worker has ZERO handlers, so every logger call falls through to
    logging.lastResort — printed bare to stderr, never written to the log
    file at all. That is the default on macOS (since 3.8) and Windows, and
    CPython is moving Linux off plain `fork` as well, so worker-side
    diagnostics would silently disappear from the log exactly where they are
    hardest to reproduce.
    """
    global _worker_exiftool
    if log_dir:
        runtime.configure_logging(Path(log_dir))
    if not exiftool_supported:
        return
    try:
        _worker_exiftool = deps.pyexiftool.ExifToolHelper(
            common_args=[]  # deliberately override PyExifTool's default
                             # ["-G", "-n"] (grouped tag names + raw numeric
                             # values) to match the flat-key, human-readable
                             # output the rest of this module already parses
                             # (extract_date_from_metadata expects a bare
                             # "DateTimeOriginal" key, not "EXIF:DateTimeOriginal"),
                             # and so metadata_json's shape doesn't silently
                             # change for anything already reading it.
        )
    except Exception:
        _worker_exiftool = None
    import atexit
    atexit.register(_shutdown_worker_exiftool)


def _shutdown_worker_exiftool():
    """Terminates this worker's persistent ExifTool subprocess on normal exit."""
    global _worker_exiftool
    if _worker_exiftool is not None:
        try:
            # Bounded: ProcessPoolExecutor's shutdown waits for every worker,
            # and this runs via atexit in each of them, so an ExifTool process
            # that will not exit stalls the whole run's teardown. PyExifTool's
            # default is a 30 s wait per instance.
            _worker_exiftool.terminate(timeout=5)
        except Exception:
            pass
        _worker_exiftool = None


def get_full_exif_via_exiftool(file_path: Path) -> Optional[dict]:
    """
    Returns the COMPLETE tag set ExifTool can extract for this file, as a
    dict, or None if ExifTool isn't available / fails / returns nothing.
    This is deliberately the full tag set rather than a curated subset,
    storing everything now means EXIF inspection/editing doesn't
    need to re-scan the whole library later to get fields nobody thought to
    whitelist today.

    Uses this worker process's persistent ExifTool instance (see
    _init_worker_process) instead of spawning a subprocess per file.
    """
    global _worker_exiftool, _worker_exiftool_failures
    if _worker_exiftool is None:
        return None
    try:
        result = _worker_exiftool.get_metadata([str(file_path)])
        if result and isinstance(result, list):
            _worker_exiftool_failures = 0   # consecutive, not cumulative
            return result[0]
    except Exception as e:
        _worker_exiftool_failures += 1

        # WARNING, not DEBUG. This path costs a process teardown and respawn
        # per file; a run that silently spends seconds per file on it looks
        # like a mysteriously slow scan with a clean log.
        runtime.logger.warning(
            f"ExifTool extraction failed for {file_path.name} "
            f"(failure {_worker_exiftool_failures} of {MAX_CONSECUTIVE_EXIFTOOL_FAILURES} "
            f"before this worker gives up on it): {e}"
        )

        try:
            # Bounded. PyExifTool's terminate() waits up to 30s by default,
            # which is indistinguishable from a hang when it happens per file.
            try:
                _worker_exiftool.terminate(timeout=5)
            except TypeError:
                _worker_exiftool.terminate()
        except Exception:
            pass

        if _worker_exiftool_failures >= MAX_CONSECUTIVE_EXIFTOOL_FAILURES:
            # Broken in this process, not confused by one file. Stop paying the
            # respawn on every remaining file and use the PIL fallback.
            runtime.logger.error(
                f"ExifTool has failed {_worker_exiftool_failures} times consecutively in this "
                f"worker — disabling it here and falling back to PIL for metadata. Dates and "
                f"camera details will still be read where PIL can supply them, but the full tag "
                f"set will be missing and RAW files cannot be read at all."
            )
            _worker_exiftool = None
            return None

        try:
            _worker_exiftool = deps.pyexiftool.ExifToolHelper(common_args=[])
        except Exception as spawn_error:
            runtime.logger.error(f"Could not restart ExifTool in this worker: {spawn_error}")
            _worker_exiftool = None
    return None


def get_exif_via_pil(file_path: Path) -> Optional[dict]:
    """
    Per-file fallback for when ExifTool is running but yields nothing usable
    for this particular file. Converts PIL's raw numeric-tag-id EXIF dict into
    a named-tag dict using PIL's own tag name table, so the stored JSON is
    human-readable either way this function is reached. Only works for formats
    PIL can open (not RAW).

    img.getexif() returns only the top-level "0th" IFD (Make, Model and
    similar); it does NOT expand the "Exif" sub-IFD at tag 0x8769 /
    "ExifOffset", which is where DateTimeOriginal, ISO, FNumber and
    ExposureTime actually live. That sub-IFD must be fetched explicitly via
    get_ifd(0x8769), or date resolution and camera-settings capture fail here
    even when the file carries the data, and the date falls back to mtime.
    """
    if not deps.PIL_SUPPORTED:
        return None
    try:
        from PIL.ExifTags import TAGS
        with deps.Image.open(file_path) as img:
            exif_data = img.getexif()
            if not exif_data:
                return None
            result = {TAGS.get(tag, str(tag)): str(value) for tag, value in exif_data.items()}
            try:
                exif_ifd = exif_data.get_ifd(0x8769)  # the "Exif" sub-IFD
                if exif_ifd:
                    result.update({TAGS.get(tag, str(tag)): str(value) for tag, value in exif_ifd.items()})
            except Exception:
                pass
            return result if result else None
    except Exception as e:
        runtime.logger.debug(f"PIL EXIF read failed on {file_path.name}: {e}")
        return None


def extract_date_from_metadata(metadata: dict) -> Optional[datetime]:
    """The capture date, which is `DateTimeOriginal` and nothing else.

    `CreateDate` and `DateTime` are deliberately NOT accepted. They are real
    dates but they are not the moment the photograph was taken: CreateDate is
    when this file was created (a re-export, a conversion, a download) and
    DateTime is when it was last modified. Promoting either files a photo in
    the dated tree under a date nobody vouched for, which is exactly the
    guess-indistinguishable-from-a-fact problem Undated/ exists to prevent.

    They stay in `metadata` and reach the catalog as review evidence — the
    Undated screen shows them as clues, clearly labelled, so a user can decide
    whether a date is meaningful (webui-spec.md 3.1). Retaining and promoting
    are different things.
    """
    if "DateTimeOriginal" in metadata:
        return parse_exif_date(metadata["DateTimeOriginal"])
    return None


def get_metadata_and_date(file_path: Path, original_mtime: Optional[float] = None) -> tuple:
    """
    Metadata Extraction Fallback Chain (see the package docstring for the full
    rationale): ExifTool -> PIL -> file mtime. Returns (datetime, metadata
    dict) together, both sourced from one underlying capture rather than two
    separate passes.

    ExifTool is a hard requirement for the engine to start at all (see module
    docstring), so the PIL/mtime steps do not cover for it being missing —
    that cannot happen. They are a defensive per-FILE fallback for the
    narrower case where
    ExifTool is genuinely running but fails on one specific file (corrupted
    data, an unusual format edge case) — the persistent process itself
    already self-heals from that in get_full_exif_via_exiftool(); this is
    the next layer down if a file just doesn't yield usable metadata at all.
    """
    def _mtime_fallback(meta: dict) -> tuple:
        # `original_mtime` is the modification time recorded in this file's
        # immutable source_snapshots row, taken at its FIRST Index. It is what
        # the Undated/<year> bucket must be built from (engine-spec.md 10):
        # photos.file_mtime is refreshed on every rescan for change detection,
        # so filing from it lets a photo drift between year folders whenever
        # anything touches the file. The two agree on a first Index, which is
        # precisely why the drift is invisible until a re-index.
        #
        # None means this file has no snapshot yet — a genuinely new source, or
        # one whose previous identity was consumed by a Move — and the live
        # mtime IS the original for the identity about to be created.
        meta["date_source"] = constants.DATE_SOURCE_MTIME
        stamp = original_mtime if original_mtime is not None else os.path.getmtime(file_path)
        return datetime.fromtimestamp(stamp), meta

    metadata = get_full_exif_via_exiftool(file_path)
    if metadata:
        dt = extract_date_from_metadata(metadata)
        if dt:
            metadata["date_source"] = constants.DATE_SOURCE_EXIF
            return dt, metadata
        # ExifTool ran but found no usable date tag — still keep whatever
        # metadata it did find, just fall through for the date itself.
        return _mtime_fallback(metadata)

    metadata = get_exif_via_pil(file_path)
    if metadata:
        dt = extract_date_from_metadata(metadata)
        if dt:
            metadata["date_source"] = constants.DATE_SOURCE_EXIF
            return dt, metadata
        return _mtime_fallback(metadata)

    # Neither source found anything at all.
    return _mtime_fallback({})


def compute_sha1(file_path: str) -> str:
    def _hash():
        h = hashlib.sha1()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(constants.SHA1_CHUNK_SIZE), b''):
                h.update(chunk)
        return h.hexdigest()
    return durable.retry_io_operation(f"SHA1 Hash {file_path}", _hash)


@contextlib.contextmanager
def warnings_attributed_to(file_path: str):
    """
    Captures library warnings raised while reading one file and re-logs them
    naming that file.

    Two problems this solves:

    1. The warnings arrive with no indication of WHICH file produced them — on
       a 29,000-file library that is an alarm with no address.

    2. The wording is actively misleading. PIL's "Truncated File Read" is
       raised by ImageFile._safe_read as an OSError, then caught and
       downgraded to a warning by TiffImagePlugin's EXIF IFD parser
       (ImageFileDirectory_v2.load). It therefore means "the EXIF metadata
       block is malformed", NOT "the image is truncated" — the parser
       returns early and the pixel data decodes normally. Files that emit
       this warning still produce a correct SHA-1 and a correct pHash; the
       only loss is EXIF tags after the bad one, which can push a photo onto
       its mtime for dating. Saying "metadata warning" keeps that straight.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield
    for w in caught:
        runtime.logger.warning(f"{w.category.__name__} metadata warning for {file_path}: {w.message}")


def compute_phash(file_path: str) -> str:
    if not deps.IMAGEHASH_SUPPORTED:
        return "not_supported"

    ext = Path(file_path).suffix.lower()

    # RAW-family formats need rawpy to decode at all — PIL can't open
    # them. Demosaic at half_size for speed, since a perceptual hash only
    # needs a coarse visual fingerprint, not full resolution.
    if ext in RAW_EXTENSIONS:
        if not (deps.RAWPY_SUPPORTED and deps.PIL_SUPPORTED):
            return "not_supported"
        try:
            with warnings_attributed_to(file_path):
                with deps.rawpy.imread(file_path) as raw:
                    rgb = raw.postprocess(
                        use_camera_wb=True, half_size=True, no_auto_bright=True, output_bps=8
                    )
                img = deps.Image.fromarray(rgb)
                return str(deps.imagehash.phash(img))
        except Exception as e:
            runtime.logger.debug(f"rawpy pHash failed for {file_path}: {e}")
            return "error"

    if not deps.PIL_SUPPORTED:
        return "not_supported"
    try:
        with warnings_attributed_to(file_path):
            with deps.Image.open(file_path) as img:
                return str(deps.imagehash.phash(img))
    except Exception as e:
        runtime.logger.debug(f"PIL pHash failed for {file_path}: {e}")
        return "error"


def image_decode_error(file_path: str) -> Optional[str]:
    """Check pixels after a missing pHash, independently of hashing or cache writes.

    A successful pHash already establishes decodability; this fallback is only for
    its error/not-supported path. RAW must use the sensor decoder, not its preview.
    """
    try:
        if not deps.PIL_SUPPORTED:
            return "Pillow is not installed"
        with warnings_attributed_to(file_path):
            if Path(file_path).suffix.lower() in RAW_EXTENSIONS:
                if not deps.RAWPY_SUPPORTED:
                    return "rawpy is not installed; RAW decoding is unavailable"
                with deps.rawpy.imread(file_path) as raw:
                    raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True, output_bps=8)
            else:
                with deps.Image.open(file_path) as img:
                    img.load()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None
