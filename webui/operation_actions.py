"""Action names from recorded metadata intent; operation outcomes stay unchanged."""
import json


def metadata_action(preview):
    if 'primary_activation' in preview or 'activation' in preview:
        return 'metadata_source'
    fields = set(preview.get('changes') or {}) | set(preview.get('remove_fields') or [])
    if fields == {'orientation'}:
        return 'rotation'
    if fields == {'date_taken'}:
        return 'date'
    return 'metadata'


def annotate(conn, items):
    """Read intents in bounded batches, without a query per photo or a full event scan."""
    by_id = {item['id']: item for item in items}
    for item in items:
        item['action'] = 'metadata' if item['mode'] == 'METADATA' else None
        item['consolidated_into'] = None
    ids = list(by_id)
    for offset in range(0, len(ids), 500):
        batch = ids[offset:offset + 500]
        rows = conn.execute(
            "SELECT operation_id, json_extract(detail_json, '$.expected.preview') "
            "FROM operation_events WHERE operation_id IN (" + ','.join('?' * len(batch)) + ") "
            "AND step='intent' AND json_extract(detail_json, '$.kind')='metadata_edit'", batch)
        for operation_id, raw in rows:
            preview = json.loads(raw) if raw else {}
            by_id[operation_id]['action'] = metadata_action(preview)
        for operation_id, survivor in conn.execute(
                "SELECT operation_id,json_extract(detail_json,'$.survivor_photo_id') FROM operation_events "
                "WHERE operation_id IN (" + ','.join('?' * len(batch)) + ") AND step='metadata_consolidated'",batch):
            by_id[operation_id]['consolidated_into'] = survivor
    return items
