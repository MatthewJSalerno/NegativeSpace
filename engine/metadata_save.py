"""Verified sidecar edit execution under the engine lock.

A job binds its confirmed preview before mutation. Original and replacement XMP
are archived first; publication uses no-replace renames, never an in-place writer.
Retry resumes the same intent. Observation and abandonment never publish metadata.
Qualified JPEG edits use the journaled embedded publisher; other formats refuse.
"""
import copy
import errno
from datetime import datetime
import hashlib
import json
import os
import stat
from pathlib import Path
import uuid

from engine import review_history
from engine import (constants, durable, metadata_edits, metadata_incoming_apply, metadata_relocate,
                    metadata_transfer, metadata_writer, metadata_photo_save, ns_db, relocate, runtime,
                    xmp_store)
from engine.ns_db import PhotoStatus

KIND = 'metadata_edit'


def active(conn, photo_id):
    """Last verified edit, independent of newer observations of an unchanged source."""
    row = conn.execute("SELECT e.detail_json FROM operations o JOIN operation_events e "
        "ON e.operation_id=o.id WHERE o.photo_id=? AND e.step='metadata_saved' "
        "ORDER BY e.event_id DESC LIMIT 1", (photo_id,)).fetchone()
    return json.loads(row[0] or '{}') if row else None


def _event(conn, op, step):
    row = conn.execute('SELECT detail_json FROM operation_events WHERE operation_id=? AND step=? '
                       'ORDER BY event_id DESC LIMIT 1', (op, step)).fetchone()
    return json.loads(row[0] or '{}') if row else None


def _manifest(conn, op):
    row = conn.execute("SELECT o.photo_id,o.run_id,o.status,e.detail_json FROM operations o "
        "JOIN operation_events e ON e.operation_id=o.id WHERE o.id=? AND e.step='intent' "
        "ORDER BY e.event_id LIMIT 1", (op,)).fetchone()
    if not row or json.loads(row[3]).get('kind') != KIND:
        raise ValueError('Unknown metadata edit operation')
    return row[0], row[1], row[2], json.loads(row[3])['expected']


def _paths(m):
    return {key: metadata_transfer._path(m['root'], m[key])
            for key in ('photo', 'sidecar', 'staged', 'previous', 'proposed')}


def _photo(conn, pid, m, *, saved=False):
    row = conn.execute('SELECT p.dest_path,p.sha1_hash,p.status,pf.revision FROM photos p '
        'JOIN photo_files pf ON pf.photo_id=p.id WHERE p.id=?', (pid,)).fetchone()
    if (not row or row[0] not in (m['photo'], m['proposed']) or row[1] != m['sha1']
            or row[2] != m['status'] or row[3] != m['revision'] + int(saved)):
        raise ns_db.RevisionConflict('The photo changed after this metadata edit was prepared')
    return Path(row[0])


def _hash(path):
    return metadata_transfer._xmp_digest(path) if os.path.lexists(path) else None


def _verify_photo(path, m):
    if not metadata_transfer._photo_matches(path, m['sha1']):
        raise ValueError('The organized photo is missing; no metadata was published')


def prepare(conn, *, run_id, preview, db_path, backups_dir, base_dir, defer_backup=False, cache_root=None):
    """Bind a confirmed preview to one photo in a metadata job, including its backup.

    Caller owns the engine lock. Replaying a run/photo with different input refuses;
    identical replay returns its original operation and never starts another edit.
    Job request-ID replay is handled by ns_db.create_run, before this boundary.
    """
    metadata_transfer._idle_full(conn)
    binding = preview['binding']
    pid = binding['photo_id']
    old = conn.execute("SELECT o.id,e.detail_json FROM operations o JOIN operation_events e "
        "ON e.operation_id=o.id WHERE o.run_id=? AND o.photo_id=? AND e.step='intent' "
        "AND json_extract(e.detail_json,'$.kind')=?", (run_id, pid, KIND)).fetchone()
    if old:
        if json.loads(old[1])['expected']['preview'] != preview:
            raise ns_db.RequestConflict('This job already accepted different edits for this photo')
        return old[0]
    config = conn.execute('SELECT r.dest_path,r.mode,c.effective_config_json FROM runs r '
        'JOIN run_configs c ON c.run_id=r.id WHERE r.id=?', (run_id,)).fetchone()
    if not config or config[0] != binding['destination_root'] or config[1] != 'METADATA':
        raise ValueError('Expected a metadata job with the configured destination')
    frozen = json.loads(config[2])
    args = dict(photo_id=pid, capture_id=binding['capture_id'], destination_root=binding['destination_root'], settings=frozen)
    if 'reproduction' in preview:
        from engine import metadata_reproduce
        fresh = metadata_reproduce.preview(db_path, reproduce=preview['reproduction']['selection'], **args)
    elif 'incoming_choice' in preview:
        fresh = metadata_incoming_apply.preview(db_path, incoming_decision_id=preview['incoming_choice']['decision_id'], **args)
    elif 'primary_activation' in preview:
        fresh = metadata_edits.preview_embedded_primary(db_path, primary_id=preview['primary_activation']['primary_id'], **args)
    elif 'activation' in preview:
        fresh = metadata_edits.preview_primary(db_path, version_id=preview['activation']['version_id'], **args)
    elif 'composition' in preview:
        fresh = metadata_edits.preview_copy(db_path, changes=preview['composition']['changes'],
            copy_fields=preview['composition']['copy_fields'], base=preview['composition'].get('base'), **args)
    else:
        fresh = metadata_edits.preview_catalog(db_path, changes=preview['changes'], remove_fields=preview.get('remove_fields', ()), **args)
    if 'exact_output' in preview:
        from engine import metadata_duplicates
        fresh = metadata_duplicates.preview(db_path, fresh)
    if fresh != preview:
        raise ns_db.RevisionConflict('Metadata preview changed; review it again before saving')
    photo = metadata_transfer._path(binding['destination_root'],
        str(Path(binding['destination_root']) / preview['filing']['current']))
    if ns_db.paths_needing_attention(conn, [str(photo)]):
        raise ValueError('Resolve the existing file issue before starting another metadata edit')
    if conn.execute("SELECT 1 FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.photo_id=? AND e.step='intent' AND json_extract(e.detail_json,'$.kind')=? "
        "AND NOT EXISTS(SELECT 1 FROM operation_events done WHERE done.operation_id=o.id "
        "AND done.step='metadata_edit_finished')", (pid, KIND)).fetchone():
        raise ValueError('Finish or abandon the earlier metadata edit before starting another')
    _verify_photo(photo, {'sha1': binding['sha1']})
    recorded = metadata_relocate.current(conn, photo)
    if preview.get('incoming_keep') or preview['target']['kind'] != 'sidecar_xmp':
        op = metadata_photo_save.prepare(conn, run_id=run_id, preview=preview, photo=photo,
            recorded=recorded, cache_root=cache_root)
        if not defer_backup:
            authorize_batch(conn, [op], db_path=db_path, backups_dir=backups_dir, base_dir=base_dir, run_id=run_id)
        return op
    if 'activation' in preview:
        before = xmp_store.original_bytes(conn, recorded['version_id']) if recorded else None
        if recorded and _hash(Path(str(photo)+'.xmp')) != recorded['sha256']:
            raise ValueError('The current sidecar differs from its recorded version')
        replacement = xmp_store.original_bytes(conn, preview['activation']['version_id'])
    elif preview['target']['create']:
        if recorded or os.path.lexists(str(photo) + '.xmp'):
            raise ValueError('An XMP already exists; resolve its ownership before creating metadata')
        before = None
        replacement = metadata_edits.first_sidecar(preview['changes'])
    else:
        if not recorded:
            raise ValueError('The primary sidecar has no verified destination receipt')
        before = xmp_store.original_bytes(conn, recorded['version_id'])
        if _hash(Path(str(photo) + '.xmp')) != recorded['sha256']:
            raise ValueError('The primary sidecar differs from its recorded version')
        replacement = metadata_writer.sidecar_bytes(before, preview['changes'], remove_fields=preview.get('remove_fields', ()))
    proposed = metadata_transfer._path(binding['destination_root'],
        str(Path(binding['destination_root']) / preview['filing']['proposed']))
    if proposed != photo and (os.path.lexists(proposed) or os.path.lexists(str(proposed) + '.xmp')):
        raise ValueError('The proposed date location is occupied; no metadata was changed')
    retained = conn.execute("SELECT file_id FROM file_states WHERE current_path=? "
        "AND location_role='destination' AND presence_state='present'", (str(photo),)).fetchone()
    if not retained:
        raise ValueError('The organized photo has no retained file identity')
    nonce = uuid.uuid4().hex
    m = dict(preview=preview, root=binding['destination_root'], photo=str(photo),
        sidecar=str(photo)+'.xmp', staged=str(photo.parent / ('.ns-edit-'+nonce+'.new.xmp')),
        previous=str(photo.parent / ('.ns-edit-'+nonce+'.old.xmp')), proposed=str(proposed),
        sha1=binding['sha1'], mode=stat.S_IMODE((Path(str(photo)+'.xmp') if recorded else photo).stat().st_mode) & 0o666, old_sha256=hashlib.sha256(before).hexdigest() if before else None,
        sha256=hashlib.sha256(replacement).hexdigest(), file_id=binding['file_id'],
        retained_id=retained[0], revision=binding['file_revision'],
        status=conn.execute('SELECT status FROM photos WHERE id=?', (pid,)).fetchone()[0],
        old_version=recorded['version_id'] if recorded else None,
        no_change='incoming_choice' not in preview and before == replacement and ('activation' not in preview or (
            preview['primary_before'] is not None
            and preview['sources_before'][preview['primary_before']]['kind']=='sidecar_xmp'
            and preview['before']['proposed_effective']==preview['after']['proposed_effective'])))
    with ns_db.transaction(conn):
        op = ns_db.begin_operation(conn, run_id=run_id, photo_id=pid, source_path=str(photo),
            dest_path=str(proposed), kind=KIND, expected=m)
        conn.execute("INSERT OR IGNORE INTO operation_files VALUES(?,?,'destination')", (op, retained[0]))
        if m['no_change']:
            ns_db.settle_operation(conn, op, status='Skipped', step='metadata_edit_finished', outcome='no_change')
            return op
        version = xmp_store.retain_capture(conn, data=replacement, run_id=run_id,
            source_relative_path=f'edits/{op}/after.xmp', file_ids=[binding['file_id'], retained[0]]
            if binding['file_id'] != retained[0] else [retained[0]], role='owner', basis='confirmed')
        ns_db.record_event(conn, operation_id=op, step='metadata_edit_version', outcome='retained', detail=version)
    if not defer_backup:
        authorize_batch(conn, [op], db_path=db_path, backups_dir=backups_dir, base_dir=base_dir, run_id=run_id)
    return op


def authorize_batch(conn, operations, *, db_path, backups_dir, base_dir, run_id):
    """One verified pre-action backup covers all prepared versions in a batch."""
    metadata_transfer._idle_full(conn)
    pending = []
    for op in operations:
        _, original_run, _, m = _manifest(conn, op)
        if original_run != run_id:
            raise ValueError('A preparation batch cannot mix jobs')
        if _event(conn, op, 'metadata_edit_finished') is None and _event(conn, op, 'metadata_backup_verified') is None:
            pending.append((op, m))
    if not pending:
        return True
    backup = ns_db.backup_catalog(db_path, backups_dir, base_dir, trigger='pre_action', related_run_id=run_id)
    if backup['outcome'] != 'succeeded':
        for op, m in pending:
            _failure(conn, op, m, 'Catalog backup failed; no metadata was published', stop_batch=True)
        return False
    with ns_db.transaction(conn):
        for op, _ in pending:
            ns_db.record_event(conn, operation_id=op, step='metadata_backup_verified', outcome='verified',
                               detail={'attempt_id':backup.get('attempt_id')})
    return True


def _owned_stage(conn, op, path):
    recorded = _event(conn, op, 'metadata_stage_created')
    if recorded is None or not os.path.lexists(path):
        return False
    info = path.lstat()
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and [info.st_dev, info.st_ino] == recorded['identity'])


def _stage(conn, op, path, data, digest):
    if os.path.lexists(path):
        try:
            if _hash(path) == digest:
                durable._fsync_file(path)
                return
        except ValueError:
            pass
        if not _owned_stage(conn, op, path):
            raise ValueError('The recorded staging file does not match this edit')
        fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        recorded = _event(conn, op, 'metadata_stage_created')
        if info.st_nlink != 1 or [info.st_dev, info.st_ino] != recorded['identity']:
            os.close(fd)
            raise ValueError('The staging file changed while resuming the edit')
        os.ftruncate(fd, 0)
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            with ns_db.transaction(conn):
                ns_db.record_event(conn, operation_id=op, step='metadata_stage_created', outcome='created',
                    detail={'identity':[info.st_dev, info.st_ino]})
        except BaseException:
            os.close(fd)
            raise
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if _hash(path) != digest:
        raise ValueError('The staged XMP failed read-back verification')
    durable._fsync_directory(path.parent)


def _publish(conn, op, m, data):
    p = _paths(m)
    _verify_photo(p['photo'], m)
    live = _hash(p['sidecar'])
    if live == m['sha256']:
        return
    if live != m['old_sha256'] and live is not None:
        raise ValueError('The sidecar path contains different metadata; nothing was overwritten')
    _stage(conn, op, p['staged'], data, m['sha256'])
    os.chmod(p['staged'], m['mode'], follow_symlinks=False)
    durable._fsync_file(p['staged'])
    if m['old_sha256'] is not None:
        prior = _hash(p['previous'])
        if prior is None:
            if live != m['old_sha256']:
                raise ValueError('The original sidecar is missing. Retry cannot verify how it was removed')
            relocate._rename_noreplace(str(p['sidecar']), str(p['previous']))
            durable._fsync_directory(p['sidecar'].parent)
        elif prior != m['old_sha256']:
            raise ValueError('The retained previous file does not match this edit')
        elif live == m['old_sha256']:
            # A no-replace hard-link fallback can be interrupted before unlink.
            if not os.path.samefile(p['sidecar'], p['previous']):
                raise ValueError('Two different files occupy the old metadata names')
            p['sidecar'].unlink()
            durable._fsync_directory(p['sidecar'].parent)
    if os.path.lexists(p['sidecar']):
        raise ValueError('The sidecar name became occupied; nothing was overwritten')
    _verify_photo(p['photo'], m)
    relocate._rename_noreplace(str(p['staged']), str(p['sidecar']))


def _verify_saved(photo, m):
    metadata_transfer._path(m['root'], photo)
    metadata_transfer._path(m['root'], str(photo)+'.xmp')
    _verify_photo(photo, m)
    if _hash(Path(str(photo)+'.xmp')) != m['sha256']:
        raise ValueError('The edited photo/XMP pair did not verify')
    for path in (photo, Path(str(photo)+'.xmp')):
        durable._fsync_file(path)
        durable._fsync_directory(path.parent)


def _record_saved(conn, op, pid, m):
    if _event(conn, op, 'metadata_saved'):
        return
    preview = m['preview']
    sources = copy.deepcopy(preview['sources_before'])
    target = preview['target']['source_id']
    if target == metadata_edits.NEW_SIDECAR:
        target = 'sidecar:destination'
    sources[target] = {'kind': 'sidecar_xmp', 'fields': preview['target_fields_after']}
    resolution = copy.deepcopy(preview['after'])
    resolution['priority'] = [target if x == metadata_edits.NEW_SIDECAR else x for x in resolution['priority']]
    resolution['proposed_primary'] = target
    resolution['field_sources'] = {k: target if v == metadata_edits.NEW_SIDECAR else v
                                    for k, v in resolution['field_sources'].items()}
    metadata = json.loads(conn.execute('SELECT metadata_json FROM photos WHERE id=?', (pid,)).fetchone()[0] or '{}')
    if 'date_taken' in preview['changes'] or 'date_taken' in preview.get('remove_fields', ()):
        date = resolution['proposed_effective'].get('date_taken', '')
        if len(date) >= 10:
            metadata.update(date_taken=date, date_source='xmp')
        else:
            mtime = conn.execute('SELECT file_mtime FROM source_snapshots WHERE file_id=?', (m['file_id'],)).fetchone()[0]
            metadata.update(date_taken=datetime.fromtimestamp(mtime).isoformat(), date_source=constants.DATE_SOURCE_MTIME)
    version = _event(conn, op, 'metadata_edit_version')['version_id']
    receipt = dict(sources=sources, primary_id=target, resolution=resolution, metadata=metadata,
                   sha1_hash=m['sha1'], xmp_sha256=m['sha256'], version_id=version,
                   destination_root=m['root'], file_id=m['file_id'], retained_id=m['retained_id'],
                   differences=preview['differences'], composition=preview.get('composition'), reproduction=preview.get('reproduction'), primary_revision=preview['binding']['primary_revision'])
    previous = active(conn, pid)
    if previous and previous.get('content_changed'):
        receipt.update({key:previous[key] for key in ('content_changed','file_size','file_mtime','phash','width','height')})
    with ns_db.transaction(conn):
        value = {'file_id':m['file_id'],'primary_id':target,'capture_id':preview['binding']['capture_id'],
                 'resolution':resolution,'filing_operation_id':op,'filing_requested':preview['filing'],
                 'established_by_operation':op}
        decision = conn.execute('INSERT INTO metadata_decisions(kind,scope,capture_id,request_id,request_json,value_json,created_at) '
            "VALUES('primary',?,?,?,?,?,?)", (str(m['file_id']), preview['binding']['capture_id'],
            f'metadata:{op}:primary', json.dumps({'operation_id':op}), json.dumps(value), ns_db.utc_now())).lastrowid
        receipt['primary_revision'] = decision
        ns_db.advance_revision(conn, pid, m['revision'])
        review_history.record_saved_date(conn, pid, op, preview, metadata, m['sha1'])
        conn.execute('UPDATE photos SET metadata_json=? WHERE id=?', (json.dumps(metadata), pid))
        ns_db.record_evidence(conn, operation_id=op, location_role='destination', observed_path=m['sidecar'],
            observation_kind='sha256', result='match', details={'sha256': m['sha256'], 'photo_sha1': m['sha1']})
        ns_db.record_event(conn, operation_id=op, step='metadata_saved', outcome='verified', detail=receipt)
        ns_db.record_event(conn, operation_id=op, step='pair_complete', outcome='verified', detail=receipt)


def _refile(conn, op, pid, m):
    if m['photo'] == m['proposed'] or _event(conn, op, 'metadata_refiled'):
        return
    expected = _event(conn, op, 'metadata_refile_intent')
    if expected is None:
        p = _paths(m)
        if os.path.lexists(p['proposed']) or os.path.lexists(str(p['proposed'])+'.xmp'):
            raise ValueError('Metadata saved; the new date location is occupied. Resolve it and retry the move only')
        expected = dict(old_path=m['photo'], new_path=m['proposed'], sha1_hash=m['sha1'], file_id=m['retained_id'],
            sidecar=dict(old=m['sidecar'], new=m['proposed']+'.xmp', sha256=m['sha256'],
                root=m['root'], version_id=_event(conn, op, 'metadata_edit_version')['version_id'],
                photo_identity=durable._file_identity(p['photo']), identity=durable._file_identity(p['sidecar']),
                wanted=m['proposed'], retry_of=op))
        with ns_db.transaction(conn):
            ns_db.record_event(conn, operation_id=op, step='metadata_refile_intent', outcome='recorded', detail=expected)
    metadata_relocate.perform(conn, op, expected)
    with ns_db.transaction(conn):
        relocate._record_relocation(conn, op, m['photo'], m['proposed'], m['retained_id'],
            step='metadata_refiled', operation_status=PhotoStatus.PROCESSING)


def _cleanup(conn, op, m):
    p = _paths(m)
    for key, digest in (('previous', m['old_sha256']), ('staged', m['sha256'])):
        if os.path.lexists(p[key]):
            if not (key == 'staged' and _owned_stage(conn, op, p[key])) and (digest is None or _hash(p[key]) != digest):
                raise ValueError('The edit temporary file differs; it was left untouched')
            p[key].unlink()
        # Repeat the durability barrier even after an earlier unlink succeeded.
        durable._fsync_directory(p[key].parent)


def _finish(conn, op, outcome='completed'):
    with ns_db.transaction(conn):
        if outcome == 'completed':
            metadata_incoming_apply.record_applied(conn, op)
        event = ns_db.settle_operation(conn, op, status='Completed' if outcome == 'completed' else 'Skipped',
            step='metadata_edit_finished', outcome=outcome, detail={'outcome': outcome})
        for (issue,) in conn.execute('SELECT issue_id FROM attention_issues WHERE operation_id=? AND resolved_at IS NULL', (op,)).fetchall():
            ns_db.resolve_attention_issue(conn, issue, event_id=event)
    return {'operation_id': op, 'outcome': outcome}


def _failure(conn, op, m, message, *, stop_batch=False):
    with ns_db.transaction(conn):
        ns_db.record_event(conn, operation_id=op, step='metadata_attempt_failed', outcome='failed',
                           detail={'error': message, 'stop_batch': stop_batch})
        conn.execute('UPDATE operations SET status=?,error_message=? WHERE id=?', ('Failed', message, op))
        issue = conn.execute('SELECT issue_id FROM attention_issues WHERE operation_id=? AND resolved_at IS NULL', (op,)).fetchone()
        if issue:
            conn.execute('UPDATE attention_issues SET summary=? WHERE issue_id=?', (message, issue[0]))
        else:
            ns_db.open_attention_issue(conn, operation_id=op, file_id=m['retained_id'],
                                      category='unestablished_outcome', summary=message)
    return {'operation_id': op, 'outcome': 'failed', 'error': message,
            'metadata_saved': bool(_event(conn, op, 'metadata_saved')), 'stop_batch': stop_batch}


def execute(conn, op):
    """Execute or explicitly retry an accepted edit; settings are never re-read."""
    metadata_transfer._idle_full(conn)
    pid, _, _, m = _manifest(conn, op)
    done = _event(conn, op, 'metadata_edit_finished')
    if done is not None:
        previous = conn.execute("SELECT outcome FROM operation_events WHERE operation_id=? AND step='metadata_edit_finished' "
                                "ORDER BY event_id DESC LIMIT 1", (op,)).fetchone()[0]
        return {'operation_id': op, 'outcome': 'no_change' if previous == 'no_change' else 'already_finished',
                'previous_outcome': previous}
    try:
        if runtime.cancel_requested.is_set():
            raise ValueError('Metadata edit paused by cancellation; retry or verify before abandoning it')
        if _event(conn, op, 'metadata_backup_verified') is None:
            raise ValueError('No verified pre-edit catalog backup; no metadata was published')
        metadata_incoming_apply.verify_versions(conn, m)
        if m.get('embedded'):
            return metadata_photo_save.execute(conn, op, pid, m)
        _paths(m)
        saved = bool(_event(conn, op, 'metadata_saved'))
        _photo(conn, pid, m, saved=saved)
        version = _event(conn, op, 'metadata_edit_version')['version_id']
        replacement = xmp_store.original_bytes(conn, version)
        if hashlib.sha256(replacement).hexdigest() != m['sha256']:
            raise ValueError('The retained replacement does not match the edit intent')
        if not saved:
            _publish(conn, op, m, replacement)
            _verify_saved(Path(m['photo']), m)
            _record_saved(conn, op, pid, m)
        _refile(conn, op, pid, m)
        photo = _photo(conn, pid, m, saved=True)
        _verify_saved(photo, m)
        _cleanup(conn, op, m)
        return _finish(conn, op)
    except Exception as exc:
        return _failure(conn, op, m, f'{type(exc).__name__}: {exc}', stop_batch=isinstance(exc, OSError)
                        and exc.errno in (errno.ENOSPC, errno.EDQUOT, errno.EROFS, errno.EIO, errno.ENODEV))


def check(conn, op, *, destination_root):
    """Observe an interrupted edit. No publication, relocation or file cleanup."""
    metadata_transfer._idle_full(conn)
    pid, _, _, m = _manifest(conn, op)
    if str(destination_root) != m['root']:
        raise ValueError('Restore the recorded destination mount before checking this edit')
    if _event(conn, op, 'metadata_edit_finished') is not None:
        return {'resolved': True, 'message': 'This metadata edit is already settled.'}
    try:
        if m.get('embedded'):
            return metadata_photo_save.check(conn, op, pid, m)
        p = _paths(m)
        saved = bool(_event(conn, op, 'metadata_saved'))
        photo = _photo(conn, pid, m, saved=saved)
        _verify_photo(photo, m)
        if not saved and _hash(p['sidecar']) == m['old_sha256'] and not os.path.lexists(p['previous']):
            message = 'The original metadata is verified unchanged. Retry the edit or explicitly discard the requested edit.'
        elif not saved and _hash(p['sidecar']) == m['sha256']:
            message = 'The edited XMP is present. Retry the recorded edit to verify and finish its catalog history.'
        else:
            message = 'The metadata edit or its date move is incomplete. Retry the recorded edit after restoring storage access.'
    except Exception as exc:
        message = f'The metadata edit could not be verified: {exc}'
    _failure(conn, op, m, message)
    return {'resolved': False, 'message': message}


def abandon(conn, op):
    """Explicitly discard a request only when the original pair is unchanged."""
    metadata_transfer._idle_full(conn)
    pid, _, _, m = _manifest(conn, op)
    if _event(conn, op, 'metadata_edit_finished') is not None:
        return {'operation_id': op, 'outcome': 'already_finished'}
    if m.get('embedded'):
        return metadata_photo_save.abandon(conn, op, pid, m)
    if _event(conn, op, 'metadata_saved'):
        raise ValueError('Metadata was saved and verified. Finish moving the files and removing the previous versions before starting another edit')
    p = _paths(m)
    _photo(conn, pid, m)
    _verify_photo(p['photo'], m)
    if _hash(p['sidecar']) != m['old_sha256'] or os.path.lexists(p['previous']):
        raise ValueError('The original is not verified unchanged; recover the edit before proceeding')
    _cleanup(conn, op, m)
    return _finish(conn, op, 'abandoned')


def retry_backup(conn, op, *, db_path, backups_dir, base_dir):
    """Explicit retry may repair a failed pre-action backup, before any publication."""
    metadata_transfer._idle_full(conn)
    pid, run_id, _, m = _manifest(conn, op)
    if _event(conn, op, 'metadata_edit_finished') is not None or _event(conn, op, 'metadata_backup_verified') is not None:
        return
    if m.get('embedded'):
        metadata_photo_save.unchanged(conn, op, pid, m)
    else:
        p = _paths(m)
        _photo(conn, pid, m)
        _verify_photo(p['photo'], m)
        if _hash(p['sidecar']) != m['old_sha256'] or os.path.lexists(p['previous']):
            raise ValueError('The original changed before a backup verified; no edit may start')
    backup = ns_db.backup_catalog(db_path, backups_dir, base_dir, trigger='pre_action', related_run_id=run_id)
    if backup['outcome'] != 'succeeded':
        raise ValueError('The pre-edit catalog backup still cannot be verified')
    with ns_db.transaction(conn):
        ns_db.record_event(conn, operation_id=op, step='metadata_backup_verified', outcome='verified',
                           detail={'attempt_id':backup.get('attempt_id')})
