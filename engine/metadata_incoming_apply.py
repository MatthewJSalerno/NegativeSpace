"""Apply confirmed incoming metadata/location choices through journaled metadata jobs.

A choice is immutable. A separate verified receipt records its application; ordinary
Copy/Move still verifies the incoming sources before consuming any of them.
"""
import contextlib
import copy
import hashlib
import json
from pathlib import Path

from engine import (metadata_adapter, metadata_capture, metadata_edits, metadata_incoming,
                    metadata_photo_save, metadata_save, ns_db, relocate, xmp, xmp_store)


def _binding(target):
    return {key: target[key] for key in ('sha1', 'path', 'status', 'photo_revision', 'file_revision', 'primary')}


def _originals(conn, versions):
    for version in versions:
        if hashlib.sha256(xmp_store.original_bytes(conn, version['version_id'])).hexdigest() != version['sha256']:
            raise ValueError('An incoming XMP original failed archival verification')


def applied_value(conn, decision_id, value):
    """Return the recorded post-application binding; never rewrite a decision row."""
    row = conn.execute("SELECT detail_json FROM operation_events WHERE step='incoming_choice_applied' "
        "AND json_extract(detail_json,'$.decision_id')=? ORDER BY event_id DESC LIMIT 1", (decision_id,)).fetchone()
    value = copy.deepcopy(value)
    if row:
        receipt = json.loads(row[0])
        value.update(applied=True, activation_required=False, target_binding=receipt['target_binding'])
    binding = conn.execute("SELECT detail_json FROM operation_events WHERE step='incoming_binding_verified' "
        "AND json_extract(detail_json,'$.decision_id')=? ORDER BY event_id DESC LIMIT 1", (decision_id,)).fetchone()
    if binding:
        value['target_binding'] = json.loads(binding[0])['target_binding']
    return value


def preview(db_path, *, photo_id, capture_id, incoming_decision_id, destination_root, settings=None):
    """Preview one confirmed combination, with target capture and effective filing."""
    if type(incoming_decision_id) is not int or not 1 <= incoming_decision_id <= 2**63-1:
        raise ValueError('Invalid incoming decision identity')
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        ns_db.require_schema(conn)
        conn.execute('BEGIN')
        row = conn.execute("SELECT scope,capture_id,value_json FROM metadata_decisions WHERE decision_id=? AND kind='incoming'",
                           (incoming_decision_id,)).fetchone()
        if not row:
            raise ValueError('Choose a confirmed incoming metadata decision')
        value = json.loads(row[2])
        if value['photo_id'] != photo_id:
            raise ValueError('The incoming choice belongs to another photo')
        highwater = (settings or {}).get('metadata_decision_highwater')
        latest = conn.execute("SELECT MAX(decision_id) FROM metadata_decisions WHERE kind='incoming' AND scope=? "
            'AND capture_id=? AND (? IS NULL OR decision_id<=?)', (row[0], row[1], highwater, highwater)).fetchone()[0]
        if latest != incoming_decision_id:
            raise ns_db.RevisionConflict('The incoming choice was superseded or is newer than this job; preview the current choice')
        if applied_value(conn, incoming_decision_id, value)['applied']:
            raise ValueError('This incoming choice is already applied')
        target = metadata_incoming._target(conn, photo_id)
        if _binding(target) != value['target_binding'] or target['file_id'] != value['retained_file_id']:
            raise ns_db.RevisionConflict('The retained photo changed after this choice; preview and confirm it again')
        _, _, _, versions = metadata_incoming._versions(conn, value['capture_id'], highwater=highwater)
        if versions != value['versions']:
            raise ns_db.RevisionConflict('Incoming ownership or captured versions changed; confirm the current evidence')
        _originals(conn, value['versions'])
        status_after = (relocate._status_before_reject(conn, photo_id, target['status'])
                        if value['location'] == 'library' and target['status'].startswith('Rejected') else target['status'])
    sources, primary, year, relative, binding = metadata_edits._catalog_state(db_path,
        photo_id=photo_id, capture_id=capture_id, destination_root=destination_root, settings=settings,
        allow_primary_choice=True, allow_rejected=True)
    if Path(relative).parts[0] != ('rejects' if target['status'].startswith('Rejected') else 'library'):
        raise ValueError('The catalog location does not match the organized photo status')
    if value['primary'] == 'use_incoming':
        with contextlib.closing(ns_db.connect(db_path)) as conn:
            data = xmp_store.original_bytes(conn, value['version_id'])
        packet = xmp.parse_bytes(data, source_id='incoming')
        if packet.state != 'valid':
            raise ValueError('An unreadable XMP cannot become primary')
        fields = metadata_adapter.for_comparison(packet.source).fields
        result = metadata_edits._primary_preview(sources, primary, year, relative, binding,
                                                  value['version_id'], data, fields)
        result.pop('token')
    else:
        resolution = metadata_capture.resolve(sources, [k for k in ('embedded_xmp','exif') if k in sources], primary_id=primary)
        result = dict(version=1, mode='preview_only', applied=False, incoming_keep=True,
            changes={}, primary_before=primary, primary_after=primary, sources_before=sources,
            target={'kind':'unchanged', 'source_id':primary, 'create':False}, before=resolution, after=resolution,
            differences=[], binding=binding, filesystem_verification_pending=True,
            filing={'current':relative, 'proposed':relative, 'change':False, 'collision_check_pending':True})
    proposed = result['filing']['proposed']
    if target['status'].startswith('Rejected'):
        proposed = ((metadata_edits._folder(result['after']['proposed_effective'], year) / Path(relative).name).as_posix()
                    if value['location'] == 'library' else relative)
    result['filing'].update(proposed=proposed, change=relative != proposed)
    result['incoming_choice'] = dict(decision_id=incoming_decision_id, value=value, status_after=status_after,
                                     target_binding=_binding(target), retained_file_id=target['file_id'])
    return metadata_edits._token(result)


def execute_keep(conn, op, pid, m):
    """Keep metadata unchanged; optionally return the verified photo/pair."""
    photo = metadata_photo_save._catalog_photo(conn, pid, op, m)
    _originals(conn, m['preview']['incoming_choice']['value']['versions'])
    # A recorded relocation may have moved the files before its catalog commit.
    # The relocation helper validates its original immutable intent on retry.
    if not metadata_save._event(conn, op, 'metadata_refile_intent'):
        metadata_photo_save._verify(m, photo, m['sha1'])
    metadata_photo_save._refile(conn, op, pid, m, {'after_sha1':m['sha1']})
    photo = metadata_photo_save._catalog_photo(conn, pid, op, m)
    metadata_photo_save._verify(m, photo, m['sha1'])
    return metadata_save._finish(conn, op)


def check_keep(conn, op, pid, m):
    metadata_photo_save._catalog_photo(conn, pid, op, m)
    found = [path for path in {m['photo'],m['proposed']} if metadata_photo_save._hash(m,path) == m['sha1']]
    if not found:
        raise ValueError('The retained photo is missing or changed; restore storage access before retrying')
    for path in found:
        metadata_photo_save._sidecar(m,path)
    message = 'Incoming choice is not complete. Retry the recorded operation; discard is allowed only before relocation starts.'
    metadata_save._failure(conn,op,m,message)
    return {'resolved':False, 'message':message}


def record_applied(conn, op):
    """Inside completion's transaction, after live verification and durable refiling."""
    pid, _, _, m = metadata_save._manifest(conn,op)
    choice = m['preview'].get('incoming_choice')
    if choice is None:
        return
    _originals(conn,choice['value']['versions'])
    conn.execute('UPDATE photos SET status=? WHERE id=?', (choice['status_after'],pid))
    target = metadata_incoming._target(conn,pid)
    ns_db.record_event(conn,operation_id=op,step='incoming_choice_applied',outcome='verified',
        detail=dict(decision_id=choice['decision_id'],target_binding=_binding(target),
                    primary=choice['value']['primary'],location=choice['value']['location'],
                    retained_file_id=target['file_id'],versions=choice['value']['versions']))


def verify_versions(conn, m):
    choice = m['preview'].get('incoming_choice')
    if choice:
        _originals(conn, choice['value']['versions'])
