"""Completed-job notifications; reading a notice never resolves its underlying outcome."""
from engine import ns_db
from . import catalog, outcomes

_FINISHED = "r.status IN ('Completed','Cancelled','Failed','Interrupted')"
_KEY = "'read_notification:' || r.id"


def unread_count(db_path):
    with catalog.connect(db_path) as conn:
        return _unread(conn)


def _unread(conn):
    return conn.execute(f"SELECT COUNT(*) FROM runs r WHERE {_FINISHED} AND NOT EXISTS "
                        f"(SELECT 1 FROM ui_state u WHERE u.key={_KEY})").fetchone()[0]


def page(db_path, before=None, limit=20):
    # Derive detailed outcomes only when the user opens the panel, in bounded pages.
    with catalog.connect(db_path) as conn:
        where = _FINISHED + (" AND r.id < ?" if before is not None else "")
        params = ([before] if before is not None else []) + [limit + 1]
        rows = conn.execute(f"SELECT {outcomes._RUN_COLUMNS} FROM runs r WHERE {where} "
                            "ORDER BY r.id DESC LIMIT ?", params).fetchall()
        items = []
        for row in rows[:limit]:
            run = outcomes._run_dict(conn, row)
            read = conn.execute("SELECT 1 FROM ui_state WHERE key=?",
                                (f"read_notification:{run['id']}",)).fetchone() is not None
            items.append({"run": run, "read": read})
        return {"items": items, "next_before": rows[limit-1]['id'] if len(rows) > limit else None}


def mark_read(db_path, values):
    if not isinstance(values, dict) or set(values) != {'run_ids'}:
        raise ValueError('Provide run_ids for the notifications shown.')
    ids = values['run_ids']
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(type(i) is not int or not 1 <= i <= 2**63 - 1 for i in ids):
        raise ValueError('run_ids must contain 1 to 100 positive integer job IDs.')
    ids = sorted(set(ids))
    with catalog.connect(db_path) as conn:
        conn.row_factory = None
        with ns_db.transaction(conn):
            for run in ids:
                if not conn.execute(f"SELECT 1 FROM runs r WHERE r.id=? AND {_FINISHED}", (run,)).fetchone():
                    raise ValueError('Only recorded finished jobs can be marked read.')
            # Independent keys and conflict-ignore make concurrent browser acknowledgments additive.
            conn.executemany("INSERT INTO ui_state(key,value_json,updated_at) VALUES(?,'true',?) "
                             "ON CONFLICT(key) DO NOTHING",
                             [(f'read_notification:{run}', ns_db.utc_now()) for run in ids])
    return {'read_ids': ids}
