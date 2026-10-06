"""The operations log and the Error Center (webui-spec 5.3): filtered, paged and exported."""

from pathlib import Path

from . import catalog, outcomes


# --- The operations log and the Error Center (webui-spec 5.3, 5.4) -----------

LOG_PAGE_MAX = 500


def _operations_where(*, runs=None, statuses=None, photo=None, q=None, since=None, until=None):
    """The WHERE clause for a log view. Every filter narrows; none is required.

    `photo` follows the photo's file identities, not only its photos.id: operations
    linked through operation_files to its source identity, or to a copy made from it,
    so a Move or a destination copy stays in its history (webui-spec 6.3). `since` and
    `until` are ISO instants; the engine stores timestamps as UTC ISO strings, which
    compare correctly as text once both sides carry an offset.
    """
    clauses, params = [], []
    if runs:
        clauses.append(f"o.run_id IN ({','.join('?' * len(runs))})")
        params += list(runs)
    if statuses:
        clauses.append(f"{catalog._OP_STATUS} IN ({','.join('?' * len(statuses))})")
        params += list(statuses)
    if photo is not None:
        # The photo, the files made from it, and its exact duplicates (other rows holding
        # the same content, including a file put back after a Move): the same set its
        # lineage tree shows, so the log and the tree tell one history.
        clauses.append("(o.photo_id = ? OR o.photo_id IN (SELECT d.id FROM photos d JOIN photos me "
                       "  ON me.id = ? AND me.sha1_hash IS NOT NULL AND me.sha1_hash != '' AND d.sha1_hash = me.sha1_hash)"
                       " OR o.id IN (SELECT of.operation_id FROM operation_files of WHERE of.file_id IN ("
                       "  SELECT pf.file_id FROM photo_files pf WHERE pf.photo_id = ?"
                       "  UNION SELECT fo.file_id FROM file_origins fo JOIN photo_files pf ON fo.origin_file_id = pf.file_id"
                       "  WHERE pf.photo_id = ?)))")
        params += [photo, photo, photo, photo]
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append("(o.source_path LIKE ? ESCAPE '\\' OR o.dest_path LIKE ? ESCAPE '\\' "
                       "OR o.error_message LIKE ? ESCAPE '\\')")
        params += [like, like, like]
    if since:
        clauses.append("o.timestamp >= ?")
        params.append(since)
    if until:
        clauses.append("o.timestamp < ?")
        params.append(until)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


_OP_COLUMNS = (f"o.id, o.run_id, r.mode, o.photo_id, o.timestamp, o.source_path, o.dest_path, {catalog._OP_STATUS} AS status, "
               "o.error_message, p.status AS photo_status, (o.reconciles_operation_id IS NOT NULL) AS recovery")
# Left joins: a failure with no photo (an unreadable folder) must never drop out
# of the Error Center (webui-spec 5.3).
_OP_FROM = "FROM operations o LEFT JOIN runs r ON r.id = o.run_id LEFT JOIN photos p ON p.id = o.photo_id"


def _op_dict(row) -> dict:
    item = dict(row)
    item["recovery"] = bool(item["recovery"])
    # A failure with no photo is about a folder or the run, not a file (webui-spec 5.3).
    item["run_level"] = item["photo_id"] is None
    return item


def list_operations(db_path: Path, *, page=1, page_size=100, **filters) -> dict:
    """One page of the log, newest first, with counts per status for the same filters
    minus the status filter, so the status buttons can show what each would find, and
    counts per job for all of them, so the log can list the jobs that match."""
    if page < 1 or not 1 <= page_size <= LOG_PAGE_MAX:
        raise ValueError(f"page must be at least 1 and page_size between 1 and {LOG_PAGE_MAX}")
    where, params = _operations_where(**filters)
    unfiltered_status = {k: v for k, v in filters.items() if k != "statuses"}
    count_where, count_params = _operations_where(**unfiltered_status)
    with catalog.connect(db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) {_OP_FROM}{where}", params).fetchone()[0]
        rows = conn.execute(f"SELECT {_OP_COLUMNS} {_OP_FROM}{where} ORDER BY o.id DESC LIMIT ? OFFSET ?",
                            params + [page_size, (page - 1) * page_size]).fetchall()
        counts = dict(conn.execute(f"SELECT {catalog._OP_STATUS}, COUNT(*) {_OP_FROM}{count_where} GROUP BY 1",
                                   count_params).fetchall())
        per_run = {str(run): n for run, n in conn.execute(
            f"SELECT o.run_id, COUNT(*) {_OP_FROM}{where} GROUP BY o.run_id", params)}
    return {"items": [_op_dict(r) for r in rows], "page": page, "page_size": page_size, "total": total,
            "status_counts": counts, "run_counts": per_run}


def iter_operations(db_path: Path, **filters):
    """Every matching operation, oldest first, for export."""
    where, params = _operations_where(**filters)
    with catalog.connect(db_path) as conn:
        for row in conn.execute(f"SELECT {_OP_COLUMNS} {_OP_FROM}{where} ORDER BY o.id", params):
            yield _op_dict(row)


def operation_photo_ids(db_path: Path, requested_only=False, **filters) -> list:
    """The distinct photos behind matching operations, for retrying failures: taken
    from the operations, never from photos.status, which can disagree with a failed
    attempt (webui-spec 5.3).
    `requested_only` leaves out rows settling an earlier job's interrupted work, so a
    retry of a selection names only photos that selection held."""
    where, params = _operations_where(**filters)
    where += (" AND" if where else " WHERE") + " o.photo_id IS NOT NULL"
    if requested_only:
        where += " AND o.reconciles_operation_id IS NULL"
    with catalog.connect(db_path) as conn:
        return [r[0] for r in conn.execute(
            f"SELECT DISTINCT o.photo_id {_OP_FROM}{where} ORDER BY o.photo_id", params)]


def list_runs(db_path: Path, limit=100) -> list:
    """The newest runs with their derived outcome, for choosing a job in the log."""
    with catalog.connect(db_path) as conn:
        return [outcomes._run_dict(conn, row) for row in conn.execute(
            f"SELECT {outcomes._RUN_COLUMNS} FROM runs ORDER BY id DESC LIMIT ?", (limit,))]
