"""Bounded JSON CLI for metadata previews, saves, explicit retries and abandonment.

This is the engine calling convention for a future editor, not a new web screen.
Mutating requests run under the normal engine lock and freeze settings once per job.
"""
import contextlib
import json
from pathlib import Path
import sys

from engine import backups, jobs, metadata_edits, metadata_incoming_apply, metadata_reproduce, metadata_save, ns_db, runtime, xmp
from engine.ns_db import RunStatus


def read_request(stream):
    raw = stream.read(xmp.MAX_BYTES + 1)
    if len(raw) > xmp.MAX_BYTES:
        raise ValueError('Metadata request exceeds the size limit')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Repeated metadata request key')
            value[key] = item
        return value
    request = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(request, dict):
        raise ValueError('Expected a metadata request object')
    return request


def _identity(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError('Expected a positive catalog identity')
    return value


def validate(request, action):
    if action == 'source-cleanup-preview':
        if set(request) != {'photo_ids'} or not isinstance(request['photo_ids'],list) or not request['photo_ids']:
            raise ValueError('Expected a nonempty photo_ids array')
        ids = [_identity(pid) for pid in request['photo_ids']]
    elif action in ('preview', 'apply'):
        if set(request) != {'edits'} or not isinstance(request['edits'], list) or not request['edits']:
            raise ValueError('Expected a nonempty edits array')
        ids = []
        for edit in request['edits']:
            keys = {'photo_id', 'capture_id', 'changes'} | ({'token'} if action == 'apply' else set())
            activation_keys = {'photo_id','capture_id','version_id'} | ({'token'} if action == 'apply' else set())
            incoming_keys = {'photo_id','capture_id','incoming_decision_id'} | ({'token'} if action=='apply' else set())
            reproduction_keys = {'photo_id','capture_id','reproduce'} | ({'token'} if action=='apply' else set())
            embedded_keys={'photo_id','capture_id','primary_id'} | ({'token'} if action=='apply' else set())
            if not isinstance(edit, dict) or set(edit) not in (keys, keys | {'remove_fields'}, keys | {'copy_fields'}, keys | {'copy_fields','base'}, activation_keys, embedded_keys, incoming_keys, reproduction_keys):
                raise ValueError('Unexpected metadata edit request fields')
            ids.append(_identity(edit['photo_id']))
            _identity(edit['capture_id'])
            if 'reproduce' in edit:
                metadata_reproduce.validate_selection(edit['reproduce'])
            elif 'incoming_decision_id' in edit:
                _identity(edit['incoming_decision_id'])
            elif 'primary_id' in edit:
                if edit['primary_id'] not in ('exif','embedded_xmp'):
                    raise ValueError('Choose an embedded metadata source')
            elif 'version_id' in edit:
                _identity(edit['version_id'])
            elif 'remove_fields' in edit:
                removed = metadata_edits._removals(edit['remove_fields'], edit['changes'])
                if edit['changes'] or not removed:
                    metadata_edits._changes(edit['changes'])
            elif 'base' in edit:
                if not isinstance(edit['base'], dict):
                    raise ValueError('Expected an explicit base metadata donor')
                if not isinstance(edit['changes'], dict):
                    raise ValueError('Expected explicit metadata overrides')
                if edit['changes']:
                    metadata_edits._changes(edit['changes'])
            elif 'copy_fields' not in edit or edit['changes']:
                metadata_edits._changes(edit['changes'])
            if action == 'apply' and (not isinstance(edit['token'], str) or len(edit['token']) != 64):
                raise ValueError('Expected the confirmed preview token')
    else:
        if set(request) != {'operation_ids'} or not isinstance(request['operation_ids'], list) or not request['operation_ids']:
            raise ValueError('Expected a nonempty operation_ids array')
        ids = [_identity(i) for i in request['operation_ids']]
    if len(ids) != len(set(ids)):
        raise ValueError('A metadata request cannot repeat the same photo or operation')


def _preview_function(edit):
    if 'reproduce' in edit:
        return metadata_reproduce.preview
    if 'incoming_decision_id' in edit:
        return metadata_incoming_apply.preview
    if 'primary_id' in edit:
        return metadata_edits.preview_embedded_primary
    if 'version_id' in edit:
        return metadata_edits.preview_primary
    return metadata_edits.preview_copy if 'copy_fields' in edit else metadata_edits.preview_catalog


def previews(db_path, root, request):
    validate(request, 'preview')
    return {'previews': [(_preview_function(edit))(db_path, destination_root=root, **edit)
                         for edit in request['edits']]}


def run(args, db_path, base_dir, lock_fd, request):
    """One accepted batch; no retries implicit in an HTTP/client request replay."""
    validate(request, args.metadata)
    root = Path(args.dest).resolve()
    args.file_ids = ([edit['photo_id'] for edit in request['edits']]
                     if args.metadata == 'apply' else None)

    def body(run_id, config):
        outcomes = []
        items = request.get('edits', request.get('operation_ids'))
        blocked = False
        with contextlib.closing(ns_db.connect(db_path, synchronous='FULL')) as conn:
            prepared = []
            # Bind every edit and retain its versions before the one pre-action
            # backup. No file publication happens during preparation.
            if args.metadata == 'apply':
                for item in items:
                    if runtime.cancel_requested.is_set():
                        outcomes.append({'photo_id':item['photo_id'], 'outcome':'not_started'})
                        continue
                    try:
                        values = {k:v for k,v in item.items() if k != 'token'}
                        preview = _preview_function(values)(db_path, destination_root=root, settings=config, **values)
                        if preview['token'] != item['token']:
                            raise ns_db.RevisionConflict('Metadata preview changed; review it again')
                        op = metadata_save.prepare(conn, run_id=run_id, preview=preview, db_path=db_path,
                            backups_dir=Path(args.backups), base_dir=base_dir, defer_backup=True, cache_root=Path(args.cache).resolve())
                        prepared.append((op, item['photo_id']))
                    except (ValueError, OSError, ns_db.RevisionConflict) as exc:
                        with ns_db.transaction(conn):
                            photo = conn.execute('SELECT dest_path FROM photos WHERE id=?', (item['photo_id'],)).fetchone()
                            refused = ns_db.begin_operation(conn, run_id=run_id, photo_id=item['photo_id'] if photo else None,
                                source_path=photo[0] if photo else None, dest_path=photo[0] if photo else None,
                                kind='metadata_refused', expected={'capture_id':item['capture_id']})
                            ns_db.settle_operation(conn, refused, status='Failed', step='metadata_refused', outcome='unchanged',
                                                   error_message=str(exc))
                        outcomes.append({'photo_id':item['photo_id'], 'outcome':'failed', 'error':str(exc)})
                if not runtime.cancel_requested.is_set():
                    metadata_save.authorize_batch(conn, [op for op,_ in prepared], db_path=db_path,
                        backups_dir=Path(args.backups), base_dir=base_dir, run_id=run_id)
            else:
                prepared = [(op, None) for op in items]
            for op, pid in prepared:
                if blocked or runtime.cancel_requested.is_set():
                    outcomes.append({'operation_id':op, 'photo_id':pid, 'outcome':'not_started'})
                    continue
                try:
                    if args.metadata == 'apply':
                        result = metadata_save.execute(conn, op)
                        result['photo_id'] = pid
                    else:
                        original_pid, _, _, manifest = metadata_save._manifest(conn, op)
                        if manifest['root'] != str(root):
                            raise ValueError('The edit belongs to a different destination; restore its original mount')
                        if args.metadata == 'retry':
                            metadata_save.retry_backup(conn, op, db_path=db_path,
                                backups_dir=Path(args.backups), base_dir=base_dir)
                            result = metadata_save.execute(conn, op)
                        else:
                            result = metadata_save.abandon(conn, op)
                        with ns_db.transaction(conn):
                            check = ns_db.begin_operation(conn, run_id=run_id, photo_id=original_pid,
                                source_path=manifest['photo'], dest_path=manifest['proposed'],
                                kind='metadata_'+args.metadata, reconciles=op, expected={'operation_id':op})
                            ns_db.settle_operation(conn, check, status='Failed' if result['outcome']=='failed' else 'Completed',
                                step='metadata_request', outcome=result['outcome'], detail=result,
                                error_message=result.get('error'))
                    outcomes.append(result)
                    blocked = bool(result.get('stop_batch'))
                except (ValueError, OSError, ns_db.RevisionConflict) as exc:
                    outcomes.append({'operation_id':op, 'outcome':'failed', 'error':str(exc)})
                    blocked = isinstance(exc, OSError)
        backups.backup_after_job(db_path, Path(args.backups), base_dir, run_id)
        print(json.dumps({'run_id':run_id, 'outcomes':outcomes}))
        if runtime.cancel_requested.is_set():
            return RunStatus.CANCELLED
        return RunStatus.FAILED if any(r['outcome']=='failed' for r in outcomes) else RunStatus.COMPLETED

    return jobs.run_maintenance_job(args, db_path, lock_fd, mode='METADATA', label='Metadata',
        submitted={'action':args.metadata, 'request':request, 'destination':str(root)},
        defaults={}, overrides={}, body=body, targeted=True, reconcile_files=False)
