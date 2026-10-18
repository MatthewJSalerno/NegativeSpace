"""Orientation-only previews over the verified metadata engine; no image re-encoding."""
import json
from pathlib import PurePosixPath

from engine import metadata_command, ns_db, xmp
from . import catalog, metadata_dates, photo_orientation


def validate_edits(edits):
    metadata_command.validate({'edits': edits}, 'apply')
    if len(json.dumps(edits).encode()) > xmp.MAX_BYTES:
        raise ValueError('This rotation request is too large. Select fewer photos.')
    for edit in edits:
        if set(edit) != {'photo_id','capture_id','changes','token'} or set(edit['changes']) != {'orientation'}:
            raise ValueError('Rotation changes Orientation only.')
        photo_orientation.turned(edit['changes']['orientation'], 0)


def preview(cfg, body):
    if not isinstance(body, dict) or set(body) != {'rotations'} or not isinstance(body['rotations'], list) or not body['rotations']:
        raise ValueError('Choose photos and their viewing rotations.')
    if len(json.dumps(body).encode()) > xmp.MAX_BYTES:
        raise ValueError('This rotation request is too large. Select fewer photos.')
    seen = set()
    for item in body['rotations']:
        if not isinstance(item, dict) or set(item) != {'photo_id','turns'}:
            raise ValueError('Send photo identities and quarter turns only.')
        pid = item['photo_id']
        if type(pid) is not int or not 1 <= pid <= 2**63-1 or pid in seen:
            raise ValueError('Choose each valid photo once.')
        photo_orientation.turned(1, item['turns'])
        seen.add(pid)
    results = []
    for item in body['rotations']:
        pid, turns = item['photo_id'], item['turns']
        with catalog.connect(cfg.db_path) as conn:
            row = conn.execute('SELECT source_path,dest_path,status FROM photos WHERE id=?', (pid,)).fetchone()
            name = PurePosixPath((row[1] or row[0]) if row else f'Photo {pid}').name
            _, current = photo_orientation.state(conn, pid)
        try:
            if row is None:
                raise ValueError('This photo is no longer in the catalog.')
            if row[2] not in catalog.DELIVERED:
                raise ValueError('Save rotation is available for organized Library photos only.')
            ctx = metadata_dates.context(cfg, pid)
            if ctx['target']['kind'] != 'sidecar_xmp' and PurePosixPath(ctx['current_path']).suffix.lower() not in ('.jpg','.jpeg','.jpe','.jfif'):
                raise ValueError('Embedded rotation is supported for qualified JPEGs only. Choose an XMP primary deliberately before editing this format.')
            edit = dict(photo_id=pid, capture_id=ctx['capture_id'], changes={'orientation': photo_orientation.turned(current, turns)})
            plan = metadata_command.previews(cfg.db_path, cfg.dest, {'edits':[edit]})['previews'][0]
            # Reconcile the display observation with the engine's bound snapshot;
            # a concurrent edit must not turn a new orientation using old evidence.
            expected = plan['before']['proposed_effective'].get('orientation', 1)
            if expected != current:
                raise ns_db.RevisionConflict('Orientation changed or could not be established. Reload the photo before rotating.')
            results.append(dict(photo_id=pid, filename=name, turns=turns, before=current,
                after=edit['changes']['orientation'], target=plan['target'], no_change=turns == 0,
                duplicate=metadata_dates.duplicate_summary(plan),
                edit={**edit, 'token':plan['token']}, error=None))
        except (ValueError, TypeError, OSError, ns_db.RevisionConflict) as exc:
            message = str(exc)
            if 'Embedded writing is qualified for JPEG only' in message or 'Embedded RAW editing' in message:
                message = 'This primary metadata source cannot be edited safely here. Embedded rotation is limited to qualified JPEGs; the primary source has not changed.'
            results.append(dict(photo_id=pid, filename=name, turns=turns, error=message))
    return {'items':results}
