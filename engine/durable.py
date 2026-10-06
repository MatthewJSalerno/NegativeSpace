"""Copy, verify, delete: the durable filesystem steps every file move relies on."""

import contextlib
import errno
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional, Callable, Any

from engine import constants, fileinfo, ns_db, runtime


# --- Resilient Network IO Wrapper ---
# Conditions that are a property of the path or the filesystem, not a hiccup.
# Retrying these cannot possibly succeed, and sleeping through the backoff
# first turns a fast, clear failure into a slow one: --move against a source
# mounted :ro raises EROFS on every delete, and the full 1s + 2s backoff per
# file would spend over eight hours on a 10,000-photo library to arrive at
# "nothing worked". Genuinely transient conditions
# (below, the reason this wrapper exists at all) still get the full backoff.
PERMANENT_IO_ERRNOS = frozenset({
    errno.EROFS,          # read-only filesystem — e.g. a :ro volume mount
    errno.EACCES,         # permission denied
    errno.EPERM,
    errno.ENOENT,         # the file is gone; waiting will not bring it back
    errno.EISDIR,
    errno.ENOTDIR,
    errno.ENOSPC,         # out of space — retrying the same write is futile
    errno.EXDEV,          # cross-device link
    errno.ENAMETOOLONG,
})



def retry_io_operation(action_description: str, func: Callable[..., Any], *args, **kwargs) -> Any:
    """Executes an IO function with exponential backoff to handle transient network share issues."""
    delay = constants.INITIAL_RETRY_DELAY
    for attempt in range(1, constants.MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except (OSError, PermissionError, IOError) as e:
            if getattr(e, "errno", None) in PERMANENT_IO_ERRNOS:
                runtime.logger.error(
                    f"IO operation cannot succeed [{action_description}]: {e}. "
                    f"Not retrying — this is a permanent condition, not a transient one."
                )
                raise
            if attempt == constants.MAX_RETRIES:
                runtime.logger.error(f"IO Operation failed after {constants.MAX_RETRIES} attempts [{action_description}]: {e}")
                raise e
            runtime.logger.warning(
                f"Transient IO error during [{action_description}]: {e}. "
                f"Retrying in {delay:.1f}s (Attempt {attempt}/{constants.MAX_RETRIES})..."
            )
            time.sleep(delay)
            delay *= 2.0


# --- Copy-Verify-Delete Core Protocol ---
class SourceRemovalRefused(Exception):
    """
    Raised when a source file must NOT be deleted even though its content
    matched. Deliberately not an OSError, so retry_io_operation() never
    retries it: "this is the same file" and "this changed" are not transient.
    """


def _file_identity(path) -> tuple:
    """(device, inode, size, mtime_ns) — enough to notice a file was replaced or edited."""
    st = os.stat(path)
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _fsync_file(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory(directory):
    """
    Makes a directory's entries durable, tolerating filesystems without
    directory fsync.

    EINVAL/ENOTSUP mean the operation is ABSENT rather than failed, so the move
    proceeds. But the power-loss guarantee is correspondingly weaker there, so
    the run says so rather than leaving a user on exFAT or an odd network mount
    to infer it from the spec.

    Reported once per RUN, naming the first directory that reported it. Once
    per directory would be a line per date folder, which is
    how a warning becomes noise and then becomes ignored.
    """
    global _unsupported_dir_fsync_reported
    fd = os.open(str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    except OSError as e:
        if e.errno in constants._DIR_FSYNC_UNSUPPORTED_ERRNOS:
            if not _unsupported_dir_fsync_reported:
                _unsupported_dir_fsync_reported = True
                runtime.logger.warning(
                    f"{directory} is on a filesystem that cannot fsync directories "
                    f"({errno.errorcode.get(e.errno, e.errno)}). Directory entries there are "
                    f"not made durable, so a power loss can lose a file that was written and "
                    f"verified — a weaker guarantee than --move gives elsewhere, and the "
                    f"reason it is tolerated rather than refused (engine-spec.md 4.2). "
                    f"Reported once per run."
                )
            return
        # Says what could not be established, rather than surfacing a bare
        # "[Errno 5] Input/output error" that a user cannot act on. The errno
        # is preserved for anything matching on it.
        raise OSError(e.errno, f"{directory} could not be made durable: "
                               f"{e.strerror or e}") from e
    finally:
        os.close(fd)


# The run's --dest, and the directories whose entry in their parent this
# process has already persisted. Both are per-run state: a fresh process has
# verified nothing, so it re-establishes every barrier rather than trusting
# directories that a failed attempt left behind. Nothing is written to the
# destination to track this — a restart re-deriving it gives the same
# guarantee without putting engine bookkeeping in the user's library.
_destination_root: Optional[Path] = None
_verified_directories: set = set()

# Whether this run has already said that the filesystem cannot fsync
# directories. Per-run for the same reason as the two above: each run should
# tell its own user about its own storage, so a long-lived process does not
# stay quiet for every run after the first.
_unsupported_dir_fsync_reported: bool = False


def _mkdir_durable(directory: Path):
    """
    Creates `directory` and persists the entry of every directory along the
    way, from the destination root down.

    fsync on a file does not persist the entry naming it in its parent — that
    is why publishing fsyncs the destination directory — and the same is true
    of each folder created on the way down. Syncing only the deepest one
    leaves the first photo of a new day durable inside a day folder whose own
    entry in the month folder never reached disk: after a power loss the copy
    is unreachable, and in --move the source is already gone.

    The walk itself is _fsync_chain_to_root, which is also called at the
    deletion gate — creating a directory is not the only moment the chain has
    to hold.
    """
    directory.mkdir(parents=True, exist_ok=True)
    _fsync_chain_to_root(directory)


def _fsync_chain_to_root(directory: Path):
    """
    Persists the entry of every directory from `directory` up to --dest,
    skipping any already known durable in this run.

    Separate from _mkdir_durable because a source is also deleted against a
    copy an EARLIER run delivered, and that run's mkdir is no evidence its
    entries reached disk. _remove_verified_source calls this at the single
    deletion gate, so a caller cannot establish the barrier for itself or
    forget to — which is precisely how it came to be missing on two of the
    three deletion paths.

    Existence is not durability. A directory exists the moment mkdir returns,
    which is before its entry is durable in its parent — so a failed sync that
    leaves its directories behind must not let the next file treat them as
    established. Each entry is therefore recorded as verified only when its
    fsync SUCCEEDS; a failure leaves it outstanding, and the next call — in
    this run or after a restart — tries again and refuses the move until it
    holds.

    Keyed on the child rather than the parent, because a parent that was
    verified when one month folder appeared is dirty again when the next one
    does. Costs one fsync per folder whose entry is not yet known durable:
    once per new date folder in a run, not once per file. A caller that has
    already established the chain pays nothing.
    """
    root = _destination_root
    if root is None:
        # No run context (a direct call): persist the immediate entry only.
        _fsync_directory(directory.parent)
        return

    chain = []
    probe = directory
    reached_root = False
    while probe.parent != probe:
        if probe == root:
            reached_root = True
            break
        chain.append(probe)
        probe = probe.parent

    if not reached_root:
        # This destination is not under the run's --dest. _destination_for
        # falls back to a row's stored path when it has no usable recorded
        # date, and that path was computed against whatever --dest was current
        # when the row was written. Persist the immediate entry and nothing
        # above it: walking on would fsync directories outside the destination
        # the engine was given, which can fail on permissions and refuse a
        # legitimate move, or quietly persist someone else's directories.
        _fsync_directory(directory.parent)
        return

    for child in reversed(chain):  # shallowest first: each entry in the parent that holds it
        if str(child) in _verified_directories:
            continue
        _fsync_directory(child.parent)
        _verified_directories.add(str(child))


def _remove_verified_source(source: Path, verified_copy: Path, source_identity: tuple,
                            description: str):
    """
    The ONLY place a user's source file is deleted.

    Every caller has already compared live hashes of the source and the copy.
    That is necessary and not sufficient, so this refuses the deletion unless
    three more things hold, and fails closed on any doubt:

    1. The copy is a DIFFERENT file. Two paths can name one file — one folder
       mounted at both source and destination, a bind mount, a hard link — and
       then the hash comparison compared the file with itself; deleting the
       "source" deletes the only copy. samefile() compares device and inode.
       It cannot see two separate network mounts of one export, which is why
       overlapping storage remains documented as unsupported, but it catches
       every alias the kernel can identify.
    2. The copy is DURABLE. Verification may have read it back from page
       cache. On a network source the server commits the delete as soon as
       the call returns, so a local power loss before the copy reached disk
       would leave no copy anywhere. The copy and its own directory entry are
       fsynced here, and so is every entry above it up to --dest
       (_fsync_chain_to_root).

       The chain is established HERE, at the gate, not left to the caller.
       Only one of the three callers copies the file itself and so passes
       through _mkdir_durable; the other two delete against a copy an earlier
       run delivered, and that run's mkdir proves nothing — a directory exists
       the moment mkdir returns, which is before its entry is durable in its
       parent. A caller that already established the chain pays nothing, since
       the verified set is consulted first.
    3. The source is still the file that was verified. An edit or replacement
       after its hash was taken means the copy holds OLD content, and
       deleting the source would destroy the new content.
    """
    try:
        same = os.path.samefile(source, verified_copy)
    except OSError as e:
        raise SourceRemovalRefused(
            f"could not confirm the copy is a separate file ({type(e).__name__}: {e})")
    if same:
        raise SourceRemovalRefused(
            f"it is the same file as the destination copy ({verified_copy}) — "
            f"source and destination storage overlap")
    try:
        _fsync_file(verified_copy)
        _fsync_directory(Path(verified_copy).parent)
        _fsync_chain_to_root(Path(verified_copy).parent)
    except OSError as e:
        raise SourceRemovalRefused(
            f"the destination copy could not be made durable ({type(e).__name__}: {e})")
    try:
        unchanged = _file_identity(source) == source_identity
    except OSError as e:
        raise SourceRemovalRefused(
            f"could not re-check the source before deleting it ({type(e).__name__}: {e})")
    if not unchanged:
        raise SourceRemovalRefused(
            "the source changed after it was verified, so its current content has no copy")
    retry_io_operation(description, source.unlink)


def _stage_copy(source: Path, dest: Path) -> Path:
    """
    Copies `source` into a NEW, uniquely named partial file beside `dest`,
    makes it durable, and returns its path.

    The name is created exclusively (O_EXCL) with a random suffix, and every
    write reopens it with O_NOFOLLOW, so staging never writes through a file
    or symlink already holding a predictable name. That matters because the
    engine's no-overwrite check — the publish in _finalize_partial — only
    runs AFTER staging.

    Mode and timestamps are copied as copy2 does, so the delivered file keeps
    the source's mtime; the fsync comes after, so data and metadata land
    together.
    """
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=f"{dest.name}{constants.PARTIAL_SUFFIX}.")
    os.close(fd)
    partial = Path(tmp)
    try:
        def _write():
            out = os.open(tmp, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
            with os.fdopen(out, "wb") as dst_f, open(source, "rb") as src_f:
                shutil.copyfileobj(src_f, dst_f, constants.SHA1_CHUNK_SIZE * 16)
        retry_io_operation(f"Copying {source.name}", _write)
        shutil.copystat(str(source), tmp)
        _fsync_file(tmp)
    except BaseException:
        with contextlib.suppress(OSError):
            partial.unlink()
        raise
    return partial


class DestinationExistsError(Exception):
    """
    Raised when the final destination name is already occupied at the moment
    the verified partial file is about to be published under it.

    Deliberately NOT an OSError subclass: retry_io_operation() catches
    OSError to ride out transient network-share hiccups, and retrying a
    name collision would just burn the backoff delays before failing
    anyway. This is a permanent condition for this filename, not a blip.
    """


def _finalize_partial(partial_dest: Path, dest: Path):
    """
    Publishes the verified partial file under its final name WITHOUT ever
    overwriting an existing file, then makes the new directory entry durable.

    Path.rename() cannot be used directly here: on POSIX it silently
    replaces an existing destination, so a same-named file already sitting
    at `dest` would be destroyed with no error raised and no record kept.
    os.link() is the no-overwrite alternative — it fails with
    FileExistsError rather than clobbering — and since the partial always
    lives in the same directory as its final name, it never crosses
    filesystems.

    Only a filesystem that genuinely cannot hard-link (FAT/exFAT, some
    network shares — see _NO_HARDLINK_ERRNOS) falls back to an existence
    check plus rename(). That fallback leaves a window in which a file
    appearing at `dest` from outside this engine would be replaced, so it is
    used for nothing else: any other link failure (an I/O error, a full
    disk) fails the publish rather than quietly weakening the guarantee.
    """
    try:
        os.link(str(partial_dest), str(dest))
    except FileExistsError:
        raise DestinationExistsError(f"Destination already exists, refusing to overwrite: {dest}")
    except OSError as e:
        if e.errno not in constants._NO_HARDLINK_ERRNOS:
            raise
        if dest.exists():
            raise DestinationExistsError(f"Destination already exists, refusing to overwrite: {dest}")
        partial_dest.rename(dest)
    else:
        partial_dest.unlink()
    _fsync_directory(dest.parent)



def copy_verify_delete(source_str: str, dest_str: str, delete_source: bool = True,
                       label: Optional[str] = None, verified_content: Optional[dict] = None) -> tuple:
    """
    Copies source to dest via a staged, verified, no-overwrite publish.

    Create the destination folder with every directory entry from --dest down
    made durable (_mkdir_durable); stage into a unique partial beside the
    destination and fsync it; verify its SHA-1 against the source's; publish
    it with a no-overwrite link and fsync the directory.
    delete_source=True (the --move behavior) then hands
    the source to _remove_verified_source(), which deletes it only if the
    copy is a separate, durable file and the source is unchanged since the
    copy began. delete_source=False (the --copy behavior) stops after
    publishing — non-destructive.

    Returns (success: bool, error_message: Optional[str]) — the message is
    None on success, and a human-readable description of what failed
    otherwise, so callers can persist the real reason to the operations
    log instead of just a bare pass/fail. `verified_content`, when supplied,
    receives the verified digest without requiring another read for lineage.
    """
    source = Path(source_str)
    dest = Path(dest_str)
    partial_dest = None

    try:
        _mkdir_durable(dest.parent)
        # Taken BEFORE the copy, so any edit from here on — during the copy,
        # during verification, after publishing — is visible at deletion time.
        source_identity = _file_identity(source)
        partial_dest = _stage_copy(source, dest)

        src_sha1 = fileinfo.compute_sha1(str(source))
        partial_sha1 = fileinfo.compute_sha1(str(partial_dest))

        if src_sha1 != partial_sha1:
            error_message = f"ChecksumMismatch: SHA1 verification failed for {source.name}"
            runtime.logger.error(error_message)
            partial_dest.unlink()
            return False, error_message

        if verified_content is not None:
            verified_content["sha1_hash"] = partial_sha1
        _finalize_partial(partial_dest, dest)
        partial_dest = None  # published: nothing left to clean up

        if delete_source:
            try:
                _remove_verified_source(source, dest, source_identity,
                                        f"Delete original {source.name}")
            except SourceRemovalRefused as e:
                error_message = f"Copied and verified, but the source was kept: {e}"
                runtime.logger.warning(f"{error_message} ({source_str})")
                return False, error_message
            except OSError as e:
                # The copy is published and verified; only deleting the original failed
                # (a read-only source, a permission). What happened is a Copy, and the
                # caller records it as one, with this reason, rather than as a failure
                # whose copy the catalog would not know about.
                error_message = f"{ns_db.ORIGINAL_KEPT}: {type(e).__name__}: {e}"
                runtime.logger.warning(f"Copied and verified, but {error_message} ({source_str})")
                if verified_content is not None:
                    verified_content["original_kept"] = True
                return False, error_message
            runtime.logger.info(f"Successfully migrated: {label or source.name} -> {dest}")
        else:
            runtime.logger.info(f"Successfully copied: {label or source.name} -> {dest} (source untouched)")
        return True, None
    except Exception as e:
        error_message = f"{type(e).__name__}: {e}"
        runtime.logger.error(f"Failed transactional copy for {source_str}: {error_message}")
        if partial_dest is not None:
            with contextlib.suppress(OSError):
                partial_dest.unlink()
        return False, error_message
