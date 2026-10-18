"""Read-only, selection-bound snapshots for a Move confirmation.

The token is a stale-state guard, not authentication. The engine checks it while
holding its lock, before scanning or transferring. Files are verified separately
by metadata_source_cleanup immediately before any source removal.
"""
import hashlib
import json
from pathlib import Path

from engine import ns_db, targeting


def snapshot(conn, *, source, destination, photo_ids=None, source_subdir=None):
    root = Path(source).resolve()
    folder = (root / source_subdir).resolve() if source_subdir else root
    if not folder.is_relative_to(root):
        raise ValueError('The folder must be inside the source.')
    clause, params = targeting._path_prefix_clause(folder)
    if photo_ids is not None:
        photo_ids = ns_db.normalize_selection(photo_ids)
        clause += ' AND id IN (SELECT value FROM json_each(?))'
        params.append(json.dumps(photo_ids))
    rows = conn.execute('SELECT id,source_path,dest_path,status,sha1_hash FROM photos WHERE 1=1'
                        + clause + ' ORDER BY id', params).fetchall()
    ids = [row[0] for row in rows]
    if photo_ids is not None and ids != photo_ids:
        raise ValueError('Some selected photos are no longer in this source. Review the selection again.')
    # One indexed event query per batch, never one metadata query per photo.
    saved = {}
    for row in conn.execute("SELECT o.photo_id,e.event_id,e.detail_json FROM operations o "
            "JOIN operation_events e ON e.operation_id=o.id WHERE e.step='metadata_saved' "
            "AND o.photo_id IN (SELECT value FROM json_each(?)) ORDER BY e.event_id", (json.dumps(ids),)):
        saved[row[0]] = (row[1], bool(json.loads(row[2]).get('content_changed')))
    pending = {row[0] for row in conn.execute(
        "SELECT DISTINCT o.photo_id FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.photo_id IN (SELECT value FROM json_each(?)) AND e.step='intent' "
        "AND json_extract(e.detail_json,'$.kind')='metadata_source_cleanup' "
        "AND NOT EXISTS(SELECT 1 FROM operation_events f WHERE f.operation_id=o.id AND f.step='source_cleanup_complete')",
        (json.dumps(ids),))}
    consolidated = {row[0] for row in conn.execute(
        "SELECT DISTINCT o.photo_id FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.photo_id IN (SELECT value FROM json_each(?)) AND e.step='metadata_consolidated'",
        (json.dumps(ids),))}
    digest = hashlib.sha256()
    digest.update(json.dumps([str(root), str(Path(destination).resolve())]).encode())
    affected = []
    for row in rows:
        event, changed = saved.get(row[0], (None, False))
        digest.update(json.dumps([*row, event, changed, row[0] in pending], ensure_ascii=True).encode())
        if changed and (row[3] in ('Copied', 'Rejected_Copied', 'Failed') or row[0] in pending or (row[3]=='Duplicate' and row[0] in consolidated)):
            affected.append({'photo_id':row[0], 'source':str(Path(row[1]).relative_to(root)),
                             'filename':Path(row[2] or row[1]).name, 'in_rejects':row[3] in ns_db.IN_REJECTS_STATUSES})
    return {'file_ids':ids, 'token':digest.hexdigest(), 'edited_originals':affected,
            'rejected_originals':sum(row[3]=='Rejected_Copied' for row in rows)}


def check(conn, token, **scope):
    result = snapshot(conn, **scope)
    if result['token'] != token:
        raise ValueError('The Move selection changed. Nothing was moved. Review and confirm it again.')
    return result
