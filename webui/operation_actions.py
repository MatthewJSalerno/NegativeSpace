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
        item['date_change'] = None
    ids = list(by_id)
    for offset in range(0, len(ids), 500):
        batch = ids[offset:offset + 500]
        rows = conn.execute(
            "SELECT i.operation_id, json_extract(i.detail_json, '$.expected.preview'), "
            "json_extract(saved.detail_json,'$.sources') FROM operation_events i "
            "LEFT JOIN operation_events saved ON saved.operation_id=i.operation_id "
            "AND saved.step='metadata_saved' AND saved.outcome='verified' "
            "WHERE i.operation_id IN (" + ','.join('?' * len(batch)) + ") "
            "AND i.step='intent' AND json_extract(i.detail_json, '$.kind')='metadata_edit'", batch)
        for operation_id, raw, saved in rows:
            preview = json.loads(raw) if raw else {}
            by_id[operation_id]['action'] = metadata_action(preview)
            fields = set(preview.get('changes') or {}) | set(preview.get('remove_fields') or [])
            if saved and 'date_taken' in fields:
                target = preview['target']
                before = preview.get('sources_before', {}).get(target['source_id'], {}).get('fields', {})
                sources = json.loads(saved)
                # Actual verified receipt, never today's photo or only a proposal.
                if target['source_id'] in sources:
                    after = sources[target['source_id']].get('fields', {})
                    by_id[operation_id]['date_change'] = dict(target=target['kind'],
                        before=dict(present='date_taken' in before, value=before.get('date_taken')),
                        after=dict(present='date_taken' in after, value=after.get('date_taken')))
        for operation_id, survivor in conn.execute(
                "SELECT operation_id,json_extract(detail_json,'$.survivor_photo_id') FROM operation_events "
                "WHERE operation_id IN (" + ','.join('?' * len(batch)) + ") AND step='metadata_consolidated'",batch):
            by_id[operation_id]['consolidated_into'] = survivor
    return items
