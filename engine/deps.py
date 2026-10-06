"""The optional and required libraries, checked once at import."""

import multiprocessing as mp
import shutil




# --- Dependency Check ---
try:
    import imagehash
    IMAGEHASH_SUPPORTED = True
except ImportError:
    IMAGEHASH_SUPPORTED = False

try:
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    PIL_SUPPORTED = True
except ImportError:
    PIL_SUPPORTED = False

# rawpy decodes RAW-family files (.raw/.dng/.cr2/.nef/.arw/.raf) for the
# perceptual hash (docs/engine-spec.md 3.3). PIL cannot read real sensor data;
# without rawpy every such file would store "error" as its phash.
try:
    import rawpy
    RAWPY_SUPPORTED = True
except ImportError:
    RAWPY_SUPPORTED = False


# --- Dependency Check: ExifTool is a HARD requirement (the package docstring,
# engine/__init__.py, says why) — checked here, enforced with a clear fatal error in main(). Two
# things must both be true: the PyExifTool Python package is importable, AND
# the actual `exiftool` system binary is on PATH (the package is just a thin
# wrapper — it does nothing without the real binary installed).
try:
    import exiftool as pyexiftool
    PYEXIFTOOL_PACKAGE_AVAILABLE = True
except ImportError:
    PYEXIFTOOL_PACKAGE_AVAILABLE = False

EXIFTOOL_BINARY_AVAILABLE = shutil.which('exiftool') is not None
EXIFTOOL_SUPPORTED = PYEXIFTOOL_PACKAGE_AVAILABLE and EXIFTOOL_BINARY_AVAILABLE


def configure_multiprocessing_start_method() -> str:
    """
    Moves worker creation off plain fork(), and returns the method chosen.

    rawpy is built with OpenMP, and an OpenMP runtime that has already started
    its thread pool does not survive fork() — the child inherits the pool's
    state without its threads, and the next parallel region can deadlock. rawpy
    warns about this itself. It is a real hazard, not a lint: the RAW decode
    path runs inside these workers, so a large library with RAW files is
    exactly where it would bite, and a deadlock there looks like the scan
    simply stopping.

    forkserver is preferred over spawn: workers are forked from a small clean
    template process that never imported rawpy or touched OpenMP, so startup
    stays cheap while avoiding the unsafe fork. spawn is the fallback for
    platforms without forkserver (Windows), where it is the only safe option
    anyway.

    Note this is what makes per-worker logging setup load-bearing rather than
    belt-and-braces: neither method inherits the parent's handlers, so without
    the explicit configure_logging() in _init_worker_process every worker-side
    log line would vanish.
    """
    available = mp.get_all_start_methods()
    for method in ("forkserver", "spawn"):
        if method in available:
            mp.set_start_method(method, force=True)
            return method
    return mp.get_start_method()
