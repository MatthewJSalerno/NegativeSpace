"""Which photos a run acts on: --file-ids, a selection file or --source-subdir."""

import argparse
import contextlib
import os
from pathlib import Path
from typing import List

from engine import constants, runtime, store


def _path_prefix_clause(root: Path) -> tuple:
    """
    Builds the (sql_fragment, params) matching a directory and everything
    beneath it, compared as literal, case-sensitive text.

    A range comparison rather than LIKE. LIKE reads '_' and '%' as wildcards,
    so "My_Photos" matched "MyXPhotos"; and it ignores ASCII case, so "Album"
    matched "album" — two different folders on a case-sensitive filesystem.
    Under --move either one deletes sources outside the selection.

    Under TEXT's default BINARY collation, every path beneath `root/` sorts at
    or after `root/` and strictly before `root0`, because '0' is the character
    immediately after '/'. The half-open range is therefore exact, needs no
    escaping, and can use the index on source_path. (Paths are POSIX here: the
    engine already depends on fcntl.)
    """
    root_str = str(root)
    return (
        " AND (source_path = ? OR (source_path >= ? AND source_path < ?))",
        [root_str, root_str + "/", root_str + "0"],
    )


def _log_selection(args):
    """How many photos a run was asked to act on: the count, never the ids, which can
    be hundreds of thousands and are recorded with the run (run_selections)."""
    runtime.logger.info(f"Targeted photos: {len(args.file_ids):,} selected"
                f"{' (from a selection file)' if args.file_ids_from else ''}.")


def _targeting_predicate(args) -> tuple:
    """
    Returns (sql_fragment, params) narrowing a `photos` query to whatever this
    run was scoped to — a --file-ids list, a --source-subdir prefix, or the
    whole library — and always to this run's own --source root. The fragment
    is written to be appended after an existing WHERE clause.

    Single source of truth deliberately: the Pending sweep, duplicate cleanup
    and the repoint must agree on what "this run" covers. The root bound
    matters because one catalog can hold rows from several source roots; an
    unbounded full run acted on every Pending row in the catalog, so moving
    one root also moved another's photos.
    """
    root = Path(args.source).resolve()
    if args.source_subdir:
        # Validated in main() to lie under --source, so it is the tighter bound.
        return _path_prefix_clause((root / args.source_subdir).resolve())
    clause, params = _path_prefix_clause(root)
    if args.file_ids:
        # The run's own record of its selection: no limit on how many ids it holds.
        return clause + " AND id IN (SELECT photo_id FROM run_selections WHERE run_id = ?)", params + [args.run_id]
    return clause, params


def _release_selection_lease():
    """The API hands this engine its selection lock (NS_SELECTION_LEASE_FD), so a
    restarting server cannot delete a selection the engine has not read yet. Once
    read, the lock is let go: held until the process exits, it refused the next
    selected job in the moments after this one had already finished."""
    fd = os.environ.pop("NS_SELECTION_LEASE_FD", None)
    if fd is not None:
        with contextlib.suppress(ValueError, OSError):
            os.close(int(fd))


def parse_file_ids(value: str) -> List[int]:
    try:
        return [int(x.strip()) for x in value.split(',') if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f"--file-ids must be a comma-separated list of integers, got: {value}")


def _query_source_subdir(db_path: str, subdir_filter_path: Path) -> List[str]:
    """
    Looks up already-cataloged `photos.source_path` values falling under
    `subdir_filter_path` (the exact directory itself, or recursively below
    it). Rows whose source a prior --move already consumed on purpose are
    excluded (SOURCE_CONSUMED_STATUSES); everything else is returned even if
    the file is missing from disk, so process_file_task can record it as
    Failed with a real reason instead of it silently vanishing from the run.
    Used by the scan phase for scoped Index, Move and Copy runs. The later
    transfer phase uses the same path scope and filters by the selected mode's
    ns_db.TRANSFER_ELIGIBLE statuses.
    """
    conn = store.get_db_connection(db_path)
    placeholders = ','.join('?' * len(constants.SOURCE_CONSUMED_STATUSES))
    # Same case-sensitive path range the Move/Copy targeting path uses, so a
    # scoped scan and the action that follows it agree about which
    # files "this subdirectory" means.
    prefix_sql, prefix_params = _path_prefix_clause(subdir_filter_path)
    rows = conn.execute(
        f"SELECT source_path FROM photos WHERE 1=1{prefix_sql} "
        f"AND status NOT IN ({placeholders})",
        (*prefix_params, *constants.SOURCE_CONSUMED_STATUSES)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]
