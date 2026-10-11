"""Journaled publication of verified embedded JPEG edits under the engine lock.

The old photo survives until new bytes, content identity and any refile verify.
A retry follows recorded hashes and names, never repeats a confirmed metadata write.
"""
import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import uuid

from engine import (constants, durable, metadata_capture, metadata_embedded, metadata_relocate,
                    metadata_save, metadata_transfer, ns_db, relocate, thumbnails)


def _hash(m, path):
    path = metadata_transfer._path(m['root'], str(path))
    if not os.path.lexists(path):
        return None
    with metadata_capture.open_source(m['root'], path.relative_to(m['root']).as_posix()) as (fd, _):
        with os.fdopen(os.dup(fd), 'rb') as stream:
            return hashlib.file_digest(stream, 'sha1').hexdigest()


def _sidecar(m, photo):
    path = metadata_transfer._path(m['root'], str(photo)+'.xmp')
    recorded = m['sidecar_receipt']
    if recorded:
        if not metadata_transfer._sidecar_matches(path, recorded['sha256']):
            raise ValueError('The recorded sidecar is missing; restore it before retrying')
    elif os.path.lexists(path):
        raise ValueError('An unrecorded sidecar occupies the photo name; no file was overwritten')


def prepare(conn, *, run_id, preview, photo, recorded, cache_root=None):
    binding = preview['binding']
    if 'primary_activation' not in preview and not preview.get('incoming_keep') and photo.suffix.lower() not in ('.jpg','.jpeg','.jpe','.jfif'):
        raise ValueError('Embedded publication is qualified for JPEG only; the primary was not changed')
    proposed = metadata_transfer._path(binding['destination_root'],
        str(Path(binding['destination_root']) / preview['filing']['proposed']))
    if proposed != photo and (os.path.lexists(proposed) or os.path.lexists(str(proposed)+'.xmp')):
        raise ValueError('The proposed date location is occupied; no metadata was changed')
    retained = conn.execute("SELECT file_id FROM file_states WHERE current_path=? "
        "AND location_role='destination' AND presence_state='present'", (str(photo),)).fetchone()
    if not retained:
        raise ValueError('The Library photo has no retained file identity')
    aliases = conn.execute('SELECT p.id,p.status,p.sha1_hash,pf.revision FROM photos p '
        'JOIN photo_files pf ON pf.photo_id=p.id WHERE p.dest_path=? AND p.id<>?',
        (str(photo),binding['photo_id'])).fetchall()
    if any(row[1] not in ('Duplicate','Removed_Duplicate') or row[2]!=binding['sha1'] for row in aliases):
        raise ValueError('Multiple organized records share this destination; resolve their identity before editing')
    nonce = uuid.uuid4().hex
    m = dict(embedded=True, primary_only='primary_activation' in preview, preview=preview, root=binding['destination_root'], photo=str(photo),
        sidecar=str(photo)+'.xmp', sidecar_receipt=recorded,
        staged=str(photo.parent/('.ns-edit-'+nonce+'.new.jpg')),
        previous=str(photo.parent/('.ns-edit-'+nonce+'.old.jpg')), proposed=str(proposed),
        sha1=binding['sha1'], file_id=binding['file_id'], retained_id=retained[0],
        revision=binding['file_revision'], aliases=[list(row) for row in aliases],
        status=conn.execute('SELECT status FROM photos WHERE id=?',(binding['photo_id'],)).fetchone()[0],
        cache_root=str(cache_root) if cache_root else None)
    _sidecar(m, photo)
    with ns_db.transaction(conn):
        op = ns_db.begin_operation(conn, run_id=run_id, photo_id=binding['photo_id'],
            source_path=str(photo), dest_path=str(proposed), kind=metadata_save.KIND, expected=m)
        conn.execute("INSERT OR IGNORE INTO operation_files VALUES(?,?,'destination')", (op,retained[0]))
    return op


def protect_scan(conn, photo_id):
    """An Index may observe source bytes without replacing an unfinished edit's row."""
    if photo_id is None:
        return None
    row=conn.execute("SELECT o.id FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.photo_id=? AND e.step='intent' AND json_extract(e.detail_json,'$.expected.embedded')=1 "
        "AND NOT EXISTS(SELECT 1 FROM operation_events done WHERE done.operation_id=o.id "
        "AND done.step='metadata_edit_finished') ORDER BY o.id DESC LIMIT 1",(photo_id,)).fetchone()
    if not row:return None
    cursor=conn.execute('SELECT * FROM photos WHERE id=?',(photo_id,))
    return row[0],dict(zip([column[0] for column in cursor.description],cursor.fetchone()))


def restore_scan(conn, protected):
    op, row=protected
    pid=row['id']
    columns=[key for key in row if key!='id']
    conn.execute('UPDATE photos SET '+','.join(key+'=?' for key in columns)+' WHERE id=?',
        tuple(row[key] for key in columns)+(pid,))
    revision=conn.execute('SELECT revision FROM photo_files WHERE photo_id=?',(pid,)).fetchone()[0]
    ns_db.record_event(conn,operation_id=op,step='metadata_source_observed',outcome='unchanged_library',
        detail={'revision':revision,'saved':bool(metadata_save._event(conn,op,'metadata_saved'))})


def _revision(conn, op, m):
    observed=metadata_save._event(conn,op,'metadata_source_observed')
    saved=bool(metadata_save._event(conn,op,'metadata_saved'))
    return (observed['revision']+int(saved and not observed['saved']) if observed
            else m['revision']+int(saved))


def _catalog_photo(conn, pid, op, m):
    saved = metadata_save._event(conn, op, 'metadata_saved')
    digest = saved['sha1_hash'] if saved else m['sha1']
    row = conn.execute('SELECT p.dest_path,p.sha1_hash,p.status,pf.revision FROM photos p '
        'JOIN photo_files pf ON pf.photo_id=p.id WHERE p.id=?',(pid,)).fetchone()
    if (not row or row[0] not in (m['photo'],m['proposed']) or row[1]!=digest
            or row[2]!=m['status'] or row[3]!=_revision(conn,op,m)):
        raise ns_db.RevisionConflict('The photo changed after this edit was prepared')
    return Path(row[0])


def _staged(conn, op, m):
    receipt = metadata_save._event(conn, op, 'embedded_staged')
    if receipt:
        return receipt
    if _hash(m,m['photo']) != m['sha1'] or os.path.lexists(m['previous']):
        raise ValueError('The original is not unchanged; no new working copy may be made')
    if os.path.lexists(m['staged']):
        # An interruption before the verified receipt committed cannot authorize
        # publishing or deleting the unrecorded output. Original stays untouched.
        raise ValueError('An unverified staging file remains. Preserve or remove that staging file, then retry; the original is unchanged')
    def record(result):
        with ns_db.transaction(conn):
            ns_db.record_event(conn,operation_id=op,step='embedded_staged',outcome='verified',detail=result)
    result = metadata_embedded.stage(m['root'], Path(m['photo']).relative_to(m['root']).as_posix(),
        Path(m['staged']).relative_to(m['root']).as_posix(), expected_sha1=m['sha1'],
        kind=m['preview']['target']['kind'], changes=m['preview']['changes'],
        **({'remove_fields':m['preview']['remove_fields']} if m['preview'].get('remove_fields') else {}))
    record(result)
    return result


def _publish(conn, op, m, output):
    new_hash = output['after_sha1']
    live = _hash(m,m['photo'])
    previous = _hash(m,m['previous'])
    if live == new_hash and previous == m['sha1']:
        return
    if live not in (None,m['sha1']) or previous not in (None,m['sha1']):
        raise ValueError('An edit path contains unexpected bytes; nothing was overwritten')
    if _hash(m,m['staged']) != new_hash:
        raise ValueError('The verified working copy is missing or changed; preserve the original and repair staging')
    _sidecar(m,m['photo'])
    if previous is None:
        if live != m['sha1']:
            raise ValueError('The original is missing; publication cannot proceed')
        relocate._rename_noreplace(m['photo'],m['previous'])
        durable._fsync_directory(Path(m['photo']).parent)
    elif live == m['sha1']:
        if not os.path.samefile(m['photo'],m['previous']):
            raise ValueError('The old and live names identify different files')
        Path(m['photo']).unlink()
        durable._fsync_directory(Path(m['photo']).parent)
    relocate._rename_noreplace(m['staged'],m['photo'])


def _verify(m, photo, digest):
    if _hash(m,photo)!=digest:
        raise ValueError('The published JPEG does not match its verified edit')
    _sidecar(m,photo)
    durable._fsync_file(photo)
    durable._fsync_directory(Path(photo).parent)
    durable._fsync_chain_to_root(Path(photo).parent)


def _record_saved(conn, op, pid, m, output):
    if metadata_save._event(conn,op,'metadata_saved'):
        return
    preview=m['preview']; target=preview['target']['source_id']
    sources=copy.deepcopy(preview['sources_before'])
    sources[target]={'kind':preview['target']['kind'],'fields':preview['target_fields_after']}
    metadata=json.loads(conn.execute('SELECT metadata_json FROM photos WHERE id=?',(pid,)).fetchone()[0] or '{}')
    # Replace qualified/legacy extracted tags with current verified evidence. The
    # immutable source observation and file_changes retain all previous values.
    metadata = {key:metadata[key] for key in ('date_taken','date_source') if key in metadata}
    metadata.update(output['tags_after'])
    if 'date_taken' in preview['changes'] or 'date_taken' in preview.get('remove_fields', ()):
        date=preview['after']['proposed_effective'].get('date_taken','')
        if len(date)>=10:
            metadata.update(date_taken=date,date_source='exif' if target=='exif' else 'xmp')
        else:
            mtime=conn.execute('SELECT file_mtime FROM source_snapshots WHERE file_id=?',(m['file_id'],)).fetchone()[0]
            metadata.update(date_taken=datetime.fromtimestamp(mtime).isoformat(),date_source=constants.DATE_SOURCE_MTIME)
    info=Path(m['photo']).stat()
    phash=conn.execute('SELECT phash FROM photos WHERE id=?',(pid,)).fetchone()[0]
    # JPEG hashing uses stored pixels, which the writer verified unchanged.
    width,height=output['width'],output['height']
    exif=metadata_capture.interpret(output['tags_after'])['sources'].get('exif',{})
    if exif.get('fields',{}).get('orientation') in (5,6,7,8):width,height=height,width
    receipt=dict(sources=sources,primary_id=target,resolution=preview['after'],metadata=metadata,
        sha1_hash=output['after_sha1'], destination_root=m['root'],file_id=m['file_id'],retained_id=m['retained_id'],
        differences=preview['differences'],composition=preview.get('composition'),reproduction=preview.get('reproduction'),embedded=True,content_changed=True,
        file_size=info.st_size,file_mtime=info.st_mtime,phash=phash,width=width,height=height)
    duplicates=[row[0] for row in conn.execute('SELECT id FROM photos WHERE sha1_hash=? AND id<>? '
        "AND status IN ('Copied','Completed','Found_At_Destination','Rejected','Rejected_Copied')",
        (output['after_sha1'],pid))]
    receipt['exact_duplicate_photo_ids']=duplicates
    # A later Index may observe additional identical sources while this edit is
    # unfinished. Detach every verified old-content pointer under the engine lock,
    # not just those present at preview time. New source observations may advance
    # their revisions without changing this byte-identity relationship.
    aliases=conn.execute('SELECT p.id,p.status,p.sha1_hash,pf.revision FROM photos p '
        'JOIN photo_files pf ON pf.photo_id=p.id WHERE p.id<>? AND (p.dest_path=? OR '
        "(p.sha1_hash=? AND p.status='Duplicate' AND NOT EXISTS(SELECT 1 FROM photos anchor "
        "WHERE anchor.id<>? AND anchor.sha1_hash=? AND anchor.status IN "
        "('Copied','Completed','Found_At_Destination','Rejected','Rejected_Copied'))))",
        (pid,m['photo'],m['sha1'],pid,m['sha1'])).fetchall()
    if any(row[1] not in ('Duplicate','Removed_Duplicate') or row[2]!=m['sha1'] for row in aliases):
        raise ns_db.RevisionConflict('Another organized record shares the edited destination; preserve both histories')
    receipt['detached_duplicate_photo_ids']=[row[0] for row in aliases]
    with ns_db.transaction(conn):
        value=dict(file_id=m['file_id'],primary_id=target,capture_id=preview['binding']['capture_id'],
            resolution=preview['after'],filing_operation_id=op,filing_requested=preview['filing'],established_by_operation=op)
        decision=conn.execute('INSERT INTO metadata_decisions(kind,scope,capture_id,request_id,request_json,value_json,created_at) '
            "VALUES('primary',?,?,?,?,?,?)",(str(m['file_id']),preview['binding']['capture_id'],f'metadata:{op}:primary',
            json.dumps({'operation_id':op}),json.dumps(value),ns_db.utc_now())).lastrowid
        receipt['primary_revision']=decision
        ns_db.advance_revision(conn,pid,_revision(conn,op,m))
        before=ns_db.content_for_digest(conn,digest=m['sha1'])
        after=ns_db.content_for_digest(conn,digest=output['after_sha1'],phash=phash,
            phash_state='ok' if phash not in (None,'','error','not_supported') else 'error',width=width,height=height)
        conn.execute('UPDATE photos SET sha1_hash=?,metadata_json=?,file_size=?,file_mtime=? WHERE id=?',
            (output['after_sha1'],json.dumps(metadata),info.st_size,info.st_mtime,pid))
        conn.execute('UPDATE file_states SET sha1_hash=?,revision=revision+1 WHERE file_id=?',
            (output['after_sha1'],m['retained_id']))
        # Old duplicate pointers no longer prove equality to this edited file.
        # Keep source and history; leave eligible originals available to organize.
        for alias,status,digest,revision in aliases:
            row=conn.execute('SELECT dest_path,sha1_hash,status FROM photos WHERE id=?',(alias,)).fetchone()
            if not row or tuple(row[1:]) != (digest,status):
                raise ns_db.RevisionConflict('A duplicate relationship changed during this edit')
            ns_db.advance_revision(conn,alias,revision)
            conn.execute('UPDATE photos SET dest_path=NULL,status=? WHERE id=?',
                ('Pending' if status=='Duplicate' else status,alias))
        event=ns_db.record_event(conn,operation_id=op,step='metadata_saved',outcome='verified',detail=receipt)
        conn.execute('INSERT INTO file_changes(event_id,file_id,before_content_id,after_content_id,before_path,after_path,'
            'before_values_json,after_values_json) VALUES(?,?,?,?,?,?,?,?)',
            (event,m['retained_id'],before,after,m['photo'],m['photo'],json.dumps(output['tags_before']),json.dumps(output['tags_after'])))
        ns_db.record_evidence(conn,operation_id=op,file_id=m['retained_id'],location_role='destination',
            observed_path=m['photo'],observation_kind='sha1',result='match',
            details={'before_sha1':m['sha1'],'after_sha1':output['after_sha1'],'exact_duplicate_photo_ids':duplicates})
        if m['sidecar_receipt']:
            side=m['sidecar_receipt']
            ns_db.record_event(conn,operation_id=op,step='pair_complete',outcome='verified',
                detail=dict(receipt,xmp_sha256=side['sha256'],version_id=side['version_id']))


def _refile(conn, op, pid, m, output):
    if m['photo']==m['proposed'] or metadata_save._event(conn,op,'metadata_refiled'):
        return
    expected=metadata_save._event(conn,op,'metadata_refile_intent')
    if expected is None:
        if os.path.lexists(m['proposed']) or os.path.lexists(m['proposed']+'.xmp'):
            raise ValueError('Metadata saved; the date location is occupied. Resolve it and retry the move only')
        expected=dict(old_path=m['photo'],new_path=m['proposed'],sha1_hash=output['after_sha1'],
                      file_id=m['retained_id'],photo_identity=durable._file_identity(m['photo']))
        if m['sidecar_receipt']:
            side=m['sidecar_receipt']
            expected['sidecar']=dict(side,old=m['sidecar'],new=m['proposed']+'.xmp',root=m['root'],
                photo_identity=durable._file_identity(m['photo']),identity=durable._file_identity(m['sidecar']),
                wanted=m['proposed'],retry_of=op)
        with ns_db.transaction(conn):
            ns_db.record_event(conn,operation_id=op,step='metadata_refile_intent',outcome='recorded',detail=expected)
    if 'sidecar' in expected:
        metadata_relocate.perform(conn,op,expected)
    else:
        durable._mkdir_durable(Path(m['proposed']).parent)
        if os.path.lexists(m['proposed']):
            if (durable._file_identity(m['proposed'])!=tuple(expected['photo_identity'])
                    or _hash(m,m['proposed'])!=output['after_sha1']):
                raise ValueError('The recorded date target contains different bytes')
            if os.path.lexists(m['photo']):
                if not os.path.samefile(m['photo'],m['proposed']):
                    raise ValueError('Two files occupy the recorded date paths; preserve both')
                Path(m['photo']).unlink()
        else:
            _verify(m,m['photo'],output['after_sha1'])
            relocate._rename_noreplace(m['photo'],m['proposed'])
        _verify(m,m['proposed'],output['after_sha1'])
        durable._fsync_directory(Path(m['photo']).parent)
    with ns_db.transaction(conn):
        relocate._record_relocation(conn,op,m['photo'],m['proposed'],m['retained_id'],
            step='metadata_refiled',operation_status='Processing')


def _cleanup(m, output):
    for path,digest in ((m['previous'],m['sha1']),(m['staged'],output['after_sha1'])):
        if os.path.lexists(path):
            if _hash(m,path)!=digest:
                raise ValueError('Recovery bytes differ; preserve them and resolve the file issue')
            Path(path).unlink()
        durable._fsync_directory(Path(path).parent)


def execute(conn, op, pid, m):
    previous_root=durable._destination_root
    durable._destination_root=Path(m['root'])
    durable._verified_directories.clear()
    try:
        if m['preview'].get('incoming_keep'):
            from engine import metadata_incoming_apply
            return metadata_incoming_apply.execute_keep(conn,op,pid,m)
        if m.get('primary_only'):
            from engine import metadata_primary
            return metadata_primary.execute(conn,op,pid,m)
        return _execute(conn,op,pid,m)
    finally:
        durable._destination_root=previous_root
        durable._verified_directories.clear()


def _execute(conn, op, pid, m):
    _catalog_photo(conn,pid,op,m)
    output=_staged(conn,op,m)
    if output['no_change']:
        _verify(m,m['photo'],m['sha1'])
        _cleanup(m,output)
        return metadata_save._finish(conn,op,'no_change')
    if not metadata_save._event(conn,op,'metadata_saved'):
        _publish(conn,op,m,output)
        _verify(m,m['photo'],output['after_sha1'])
        _record_saved(conn,op,pid,m,output)
    _refile(conn,op,pid,m,output)
    photo=_catalog_photo(conn,pid,op,m)
    _verify(m,photo,output['after_sha1'])
    if m.get('cache_root'):
        result=thumbnails.generate_thumbnail(photo,output['after_sha1'],m['cache_root'])
        with ns_db.transaction(conn):
            cid=ns_db.content_for_digest(conn,digest=output['after_sha1'])
            ns_db.record_thumbnail(conn,content_id=cid,size=constants.THUMBNAIL_SIZE,availability=result.availability,
                cache_filename=result.cache_filename,bytes_on_disk=result.bytes,attempted_file_id=m['retained_id'],
                observed_path=str(photo),failure_category=result.failure_category,failure_detail=result.failure_detail)
    _cleanup(m,output)
    result=metadata_save._finish(conn,op)
    result['exact_duplicate_photo_ids']=metadata_save._event(conn,op,'metadata_saved')['exact_duplicate_photo_ids']
    return result


def unchanged(conn, op, pid, m):
    _catalog_photo(conn,pid,op,m)
    if metadata_save._event(conn,op,'metadata_saved') or metadata_save._event(conn,op,'metadata_refile_intent') or _hash(m,m['photo'])!=m['sha1'] or os.path.lexists(m['previous']):
        raise ValueError('The original is not unchanged; retry the recorded edit to finish instead')
    _sidecar(m,m['photo'])


def abandon(conn, op, pid, m):
    unchanged(conn,op,pid,m)
    output=metadata_save._event(conn,op,'embedded_staged')
    if output:
        _cleanup(m,output)
    elif os.path.lexists(m['staged']):
        raise ValueError('Unverified staging remains; preserve or remove it before discarding this edit')
    return metadata_save._finish(conn,op,'abandoned')


def check(conn, op, pid, m):
    if m['preview'].get('incoming_keep'):
        from engine import metadata_incoming_apply
        return metadata_incoming_apply.check_keep(conn,op,pid,m)
    if m.get('primary_only'):
        from engine import metadata_primary
        return metadata_primary.check(conn,op,pid,m)
    photo=_catalog_photo(conn,pid,op,m)
    output=metadata_save._event(conn,op,'embedded_staged')
    if metadata_save._event(conn,op,'metadata_saved'):
        candidates={str(photo),m['proposed']}
        verified=[path for path in candidates if _hash(m,path)==output['after_sha1']]
        if not verified:
            raise ValueError('Saved metadata is recorded, but its JPEG is missing or changed; preserve the recovery files and repair storage before retrying')
        for path in verified:_sidecar(m,path)
        message='The saved JPEG verifies. Retry to finish its recorded move or recovery-file cleanup.'
    elif _hash(m,photo)==m['sha1'] and not os.path.lexists(m['previous']):
        message='The original is unchanged. Retry the edit or discard the requested edit.'
    elif output and _hash(m,photo)==output['after_sha1']:
        message='The edited photo is present. Retry to verify it and finish its catalog history.'
    else:
        message='Publication is incomplete. Preserve the recorded recovery files and retry after fixing storage access.'
    metadata_save._failure(conn,op,m,message)
    return {'resolved':False,'message':message}
