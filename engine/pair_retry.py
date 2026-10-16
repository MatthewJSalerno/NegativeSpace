"""Catalog-only retry eligibility and stale-state guards for photo/XMP imports.

No file reads or repairs happen in previews. Normal Copy/Move performs the live
verification and publication under the engine lock after this guard is checked.
"""
import hashlib
import json
from pathlib import Path

from engine import ns_db


def items(conn, photo_ids=None):
    params = ()
    scope = ""
    if photo_ids is not None:
        scope = " AND o.photo_id IN (SELECT value FROM json_each(?))"
        params = (json.dumps(photo_ids),)
    rows = conn.execute("SELECT a.issue_id,o.id,o.photo_id,a.summary,e.detail_json,p.status,"
        "p.source_path,p.sha1_hash,o.status,"
        "(SELECT f.detail_json FROM operation_events f WHERE f.operation_id=o.id "
        "AND f.step='pair_incomplete' ORDER BY f.event_id DESC LIMIT 1) FROM attention_issues a "
        "JOIN operations o ON o.id=a.operation_id JOIN photos p ON p.id=o.photo_id "
        "JOIN operation_events e ON e.operation_id=o.id AND e.step='intent' "
        "WHERE a.category='metadata_pair_incomplete' AND a.resolved_at IS NULL "
        "AND json_extract(e.detail_json,'$.kind')='metadata_pair_transfer' "
        "AND o.id=(SELECT MAX(n.id) FROM operations n JOIN operation_events ne ON ne.operation_id=n.id "
        "WHERE n.photo_id=o.photo_id AND ne.step='intent' "
        "AND json_extract(ne.detail_json,'$.kind')='metadata_pair_transfer')" + scope + " ORDER BY o.photo_id", params)
    result = []
    for issue, operation, photo, summary, raw, status, source, digest, outcome, failed in rows:
        m = json.loads(raw)['expected']
        detail = json.loads(failed or '{}')
        delivery = detail.get('delivery') or {}
        delivery = {key:delivery.get(key) if delivery.get(key) in ('verified','incomplete') else 'unknown' for key in ('photo','xmp')}
        reason = None
        if outcome != 'Failed' or status not in ('Pending','Failed'):
            reason = 'The photo changed state after this transfer. Review its history before retrying.'
        elif (source,digest) != (m['photo_source'],m['sha1_hash']):
            reason = 'The catalogued source changed. Restore the recorded source or review its history.'
        result.append(dict(issue_id=issue, operation_id=operation, photo_id=photo,
            filename=Path(m['photo_source']).name, mode='move' if m['move'] else 'copy',
            summary=summary, delivery=delivery, failure_context=detail.get('failure_context'), blocked=reason, source=m['photo_source'],
            destination=m['photo_destination'], sidecar_source=m['sidecar_source'],
            sidecar_destination=m['sidecar_destination'], source_root=m['source_root'],
            destination_root=m['destination_root'], manifest=m))
    return result


def preview(conn, *, source, destination, photo_ids=None):
    selected = ns_db.normalize_selection(photo_ids) if photo_ids is not None else None
    result = items(conn, selected)
    roots = (str(Path(source).resolve()),str(Path(destination).resolve()))
    for row in result:
        if (row['source_root'],row['destination_root']) != roots:
            row['blocked'] = 'Restore the source and destination folders used by the original job before retrying.'
        row.pop('manifest')
        row.pop('source_root'); row.pop('destination_root')
    return result


def token(conn, *, source, destination, photo_ids, mode):
    if mode not in ('copy','move'):
        raise ValueError('Retry uses the original Copy or Move mode.')
    ids = ns_db.normalize_selection(photo_ids)
    rows = items(conn,ids)
    eligible = preview(conn,source=source,destination=destination,photo_ids=ids)
    if [r['photo_id'] for r in rows] != ids or any(r['blocked'] or r['mode'] != mode for r in eligible):
        raise ValueError('The selected photo/XMP transfers are no longer eligible for this retry. Refresh the list.')
    payload = [str(Path(source).resolve()),str(Path(destination).resolve()),mode,rows]
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=True).encode()).hexdigest()


def check(conn, expected, **scope):
    if token(conn, **scope) != expected:
        raise ValueError('The photo/XMP retry changed. Nothing was transferred. Refresh and confirm again.')
