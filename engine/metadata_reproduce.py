"""Reapply a recorded common-field state as a new edit, never undo a job.

Historical evidence is immutable. The current primary remains the write target;
missing image content and unqualified metadata representations cannot be recreated.
"""
import contextlib
import hashlib
import json
from pathlib import Path

from engine import metadata_edits, metadata_save, ns_db


def validate_selection(selection):
    if not isinstance(selection, dict) or set(selection) not in ({'capture_id'}, {'before_operation_id'}):
        raise ValueError('Choose one source observation or one completed pre-edit state')
    identity = next(iter(selection.values()))
    if type(identity) is not int or not 1 <= identity <= 2**63-1:
        raise ValueError('Expected a positive historical metadata identity')


def _historical(conn, photo_id, file_id, selection):
    if 'capture_id' in selection:
        row = conn.execute('SELECT catalog_sha1,report_json FROM metadata_captures WHERE capture_id=? AND file_id=?',
                           (selection['capture_id'], file_id)).fetchone()
        if not row:
            raise ValueError('The source observation does not belong to this photo')
        report = json.loads(row[1])
        if report.get('issues') or 'resolution' not in report:
            raise ValueError('The source observation has unresolved metadata; no complete state can be reproduced')
        return row[0], report['resolution'], {'capture_id':selection['capture_id'], 'sources':report['sources']}
    op = selection['before_operation_id']
    owner, _, _, manifest = metadata_save._manifest(conn, op)
    done = conn.execute("SELECT outcome FROM operation_events WHERE operation_id=? AND step='metadata_edit_finished' "
                        "ORDER BY event_id DESC LIMIT 1", (op,)).fetchone()
    if owner != photo_id:
        raise ValueError('The earlier edit does not belong to this photo')
    if not done or done[0] not in ('completed', 'no_change'):
        raise ValueError('Choose a completed metadata edit; unfinished or discarded work is not a saved version')
    preview = manifest['preview']
    return manifest['sha1'], preview['before'], {
        'before_operation_id':op, 'binding':preview['binding'],
        'primary_id':preview['primary_before'], 'sources':preview['sources_before']}


def _image_chain(conn, photo_id, original, current):
    """Only verified embedded edits can connect different whole-photo hashes.

    Such writes prove encoded image/pixel preservation. Same-photo catalog identity
    alone, a perceptual match, or an external modification never supplies that proof.
    """
    if original == current:
        return []
    reachable = {original:[]}
    rows = conn.execute("SELECT o.id,i.detail_json,s.detail_json,w.detail_json FROM operations o "
        "JOIN operation_events i ON i.operation_id=o.id AND i.step='intent' "
        "JOIN operation_events s ON s.operation_id=o.id AND s.step='metadata_saved' AND s.outcome='verified' "
        "JOIN operation_events w ON w.operation_id=o.id AND w.step='embedded_staged' AND w.outcome='verified' "
        "WHERE o.photo_id=? ORDER BY s.event_id", (photo_id,))
    for op, intent, saved, staged in rows:
        intent, saved, staged = json.loads(intent), json.loads(saved), json.loads(staged)
        if intent.get('kind') != metadata_save.KIND:
            continue
        before, after = staged['before_sha1'], staged['after_sha1']
        if (before in reachable and intent['expected']['sha1'] == before
                and saved['sha1_hash'] == after):
            reachable[after] = reachable[before] + [op]
    if current not in reachable:
        raise ValueError('No verified unchanged-image history connects this state to the current photo')
    return reachable[current]


def preview(db_path, *, photo_id, capture_id, reproduce, destination_root, settings=None):
    """Preview complete supported values, absences, provenance and any date move."""
    validate_selection(reproduce)
    sources, primary, year, relative, binding = metadata_edits._catalog_state(db_path,
        photo_id=photo_id, capture_id=capture_id, destination_root=destination_root, settings=settings)
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        ns_db.require_schema(conn)
        conn.execute('BEGIN')
        digest, resolution, origin = _historical(conn, photo_id, binding['file_id'], reproduce)
        chain = _image_chain(conn, photo_id, digest, binding['sha1'])
    fields = resolution['proposed_effective']
    desired = {key:value for key,value in fields.items() if key in metadata_edits.EDITABLE}
    desired = metadata_edits._changes(desired) if desired else {}
    # The primary is normally established by import. When none exists, the normal
    # planner applies the frozen write preference; a new sidecar has no removals.
    target = sources.get(primary, {}).get('fields', {}) if primary else {}
    removals = sorted((set(target) & metadata_edits.EDITABLE) - set(desired))
    if not desired and not removals:
        raise ValueError('This state has no supported values to reapply or current primary fields to remove')
    result = metadata_edits.plan(sources, primary_id=primary, changes=desired, remove_fields=removals,
        settings=binding['settings'], photo_name=Path(relative).name, original_year=year,
        current_relative_path=relative)
    actual = {key:value for key,value in result['after']['proposed_effective'].items()
              if key in metadata_edits.EDITABLE}
    actual = metadata_edits._changes(actual) if actual else {}
    if actual != desired:
        raise ValueError('The current primary cannot reproduce this state without fallback values; choose a primary explicitly or copy individual fields')
    result['binding'] = binding
    result['reproduction'] = {
        'selection':dict(reproduce), 'scope':'supported_common_fields', 'exact_photo_bytes':False,
        'origin':origin, 'historical_photo_sha1':digest, 'verified_image_operations':chain,
        'snapshot_sha256':hashlib.sha256(json.dumps({'origin':origin,'resolution':resolution}, sort_keys=True).encode()).hexdigest(),
        'fields':{key:{'present':key in desired,'value':desired.get(key),
                       'historical_source':resolution['field_sources'].get(key)}
                  for key in sorted(metadata_edits.EDITABLE)},
        'unapplied_historical_fields':sorted(set(fields)-metadata_edits.EDITABLE)}
    return metadata_edits._token(result)
