"""Confirmed whole-file equality after embedded edits; never image-only matching.

Preview works on disposable copies. Execution rechecks the survivor and retains
metadata provenance before retiring the edited destination. Sources stay untouched.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from engine import (durable, metadata_capture, metadata_edits, metadata_embedded,
                    metadata_relocate, metadata_save, metadata_transfer, ns_db, xmp_store)

DELIVERED = ('Copied', 'Completed', 'Found_At_Destination', 'Rejected', 'Rejected_Copied')


def candidates(conn, pid, digest):
    return conn.execute("SELECT id,dest_path,status FROM photos WHERE sha1_hash=? AND id<>? "
        "AND status IN ('Copied','Completed','Found_At_Destination','Rejected','Rejected_Copied') "
        "ORDER BY CASE WHEN status LIKE 'Rejected%' THEN 1 ELSE 0 END,id", (digest,pid)).fetchall()


def _read_hash(root, path):
    path = metadata_transfer._path(root, path)
    with metadata_capture.open_source(root, path.relative_to(root).as_posix()) as (fd, info):
        with os.fdopen(os.dup(fd), 'rb') as stream:
            digest = hashlib.file_digest(stream, 'sha1').hexdigest()
        return digest, [info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns]


def _equal(root, first, second):
    with metadata_capture.open_source(root, Path(first).relative_to(root).as_posix()) as (a,_), \
         metadata_capture.open_source(root, Path(second).relative_to(root).as_posix()) as (b,_):
        while True:
            left,right = os.read(a,65536),os.read(b,65536)
            if left != right:return False
            if not left:return True


def _sidecar(conn, root, photo):
    side = metadata_relocate.current(conn, photo)
    if side:
        path = metadata_transfer._path(root, side['old'])
        data = xmp_store.original_bytes(conn, side['version_id'])
        if hashlib.sha256(data).hexdigest()!=side['sha256'] or not metadata_transfer._sidecar_matches(path,side['sha256']):
            raise ValueError('The matching photo sidecar changed or is missing. Restore it before editing.')
    return side


def _snapshot(conn, db_path, root, row):
    pid,path,status=row
    if status.startswith('Rejected'):
        raise ValueError(f'This edit matches {Path(path).name} in Rejects. No photo was changed. Review that rejected photo before choosing which version to keep.')
    if ns_db.paths_needing_attention(conn,[path]):
        raise ValueError('The matching photo has a file issue. Resolve it before consolidating.')
    if conn.execute("SELECT 1 FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.photo_id=? AND e.step='intent' AND json_extract(e.detail_json,'$.kind')='metadata_edit' "
        "AND NOT EXISTS(SELECT 1 FROM operation_events done WHERE done.operation_id=o.id AND done.step='metadata_edit_finished')",(pid,)).fetchone():
        raise ValueError('The matching photo has an unfinished metadata edit. Finish it before consolidating.')
    retained=conn.execute("SELECT file_id FROM file_states WHERE current_path=? AND presence_state='present' "
        "AND location_role='destination'",(path,)).fetchone()
    if not retained:raise ValueError('The matching photo has no verified retained identity. Nothing was changed.')
    capture=conn.execute('SELECT MAX(m.capture_id) FROM metadata_captures m JOIN photo_files pf ON pf.file_id=m.file_id WHERE pf.photo_id=?',(pid,)).fetchone()[0]
    active=metadata_save.active(conn,pid)
    if active and active.get('primary_revision'):
        capture=conn.execute('SELECT capture_id FROM metadata_decisions WHERE decision_id=?',(active['primary_revision'],)).fetchone()[0]
    sources,primary,_,relative,binding=metadata_edits._catalog_state(db_path,photo_id=pid,capture_id=capture,destination_root=root)
    fields=metadata_capture.resolve(sources,list(sources) if primary else [k for k in ('embedded_xmp','exif') if k in sources],primary_id=primary)['proposed_effective']
    digest,identity=_read_hash(root,path)
    if digest!=binding['sha1']:raise ValueError('The matching photo differs from its catalog hash. Nothing was changed.')
    return dict(photo_id=pid,filename=Path(path).name,path=relative,status=status,binding=binding,
                retained_id=retained[0],identity=identity,sidecar=_sidecar(conn,root,path),fields=fields)


def _comparable(fields):
    result=dict(fields)
    for key in ('title','caption','rights'):
        if isinstance(result.get(key),str):result[key]={'x-default':result[key]}
    return result


def preview(db_path, plan):
    """Bind the verified output digest and optional survivor to the confirmation token."""
    if plan['target']['kind']=='sidecar_xmp' or any(k in plan for k in ('primary_activation','incoming_keep')):
        return plan
    binding=plan['binding'];root=Path(binding['destination_root'])
    original=plan['filing']['current']
    with tempfile.TemporaryDirectory(prefix='ns-metadata-preview-') as scratch:
        scratch=Path(scratch)
        with metadata_capture.open_source(root,original) as (fd,_), (scratch/'input.jpg').open('xb') as out:
            with os.fdopen(os.dup(fd),'rb') as inp:shutil.copyfileobj(inp,out,65536)
        output=metadata_embedded.stage(scratch,'input.jpg','output.jpg',expected_sha1=binding['sha1'],
            kind=plan['target']['kind'],changes=plan['changes'],remove_fields=plan.get('remove_fields',()))
        duplicate=None
        with contextlib.closing(ns_db.connect(db_path)) as conn:
            rows=candidates(conn,binding['photo_id'],output['after_sha1'])
            if rows:
                duplicate=_snapshot(conn,db_path,root,rows[0])
                # A hash narrows the search; live byte equality establishes the match.
                with metadata_capture.open_source(root,duplicate['path']) as (fd,_), (scratch/'output.jpg').open('rb') as generated:
                    with os.fdopen(os.dup(fd),'rb') as existing:
                        while True:
                            a,b=generated.read(65536),existing.read(65536)
                            if a!=b:raise ValueError('Equal hashes did not establish identical files. Nothing was changed.')
                            if not a:break
                if _comparable(duplicate['fields'])!=_comparable(plan['after']['proposed_effective']):
                    raise ValueError(f"This edit matches {duplicate['filename']}, but its primary metadata differs. Compare the metadata and choose a primary before consolidating. Nothing was changed.")
        plan['exact_output']={'sha1':output['after_sha1'],'duplicate':duplicate}
        return metadata_edits._token(plan)


def guard(conn, db_path, op, pid, m, output):
    """Called before publication, including retries and callers without web previews."""
    expected=m['preview'].get('exact_output')
    if expected and output['after_sha1']!=expected['sha1']:
        raise ValueError('The generated edit differs from its confirmed preview. The original is unchanged.')
    rows=candidates(conn,pid,output['after_sha1'])
    duplicate=expected and expected['duplicate']
    if not duplicate:
        if rows:
            raise ValueError('This edit would duplicate another destination photo. Preview and confirm the surviving photo before saving. The original is unchanged.')
        return
    row=next((r for r in rows if r[0]==duplicate['photo_id']),None)
    if row is None or _snapshot(conn,db_path,Path(m['root']),row)!=duplicate:
        raise ValueError('The confirmed surviving photo changed. Preview again; no duplicate was removed.')
    compare=m['staged'] if os.path.lexists(m['staged']) else m['photo']
    if not _equal(Path(m['root']),compare,str(Path(m['root'])/duplicate['path'])):
        raise ValueError('The staged edit and surviving photo differ. Both photos were preserved.')


def _survivor(conn, m):
    keep=m['preview']['exact_output']['duplicate'];root=Path(m['root']);path=root/keep['path']
    row=conn.execute('SELECT dest_path,status,sha1_hash,pf.revision FROM photos p JOIN photo_files pf ON pf.photo_id=p.id WHERE p.id=?',(keep['photo_id'],)).fetchone()
    b=keep['binding']
    if not row or tuple(row)!=(str(path),keep['status'],b['sha1'],b['file_revision']):
        raise ns_db.RevisionConflict('The surviving photo changed. Both histories are preserved; restore the confirmed survivor before retrying.')
    primary=conn.execute("SELECT COALESCE(MAX(decision_id),0) FROM metadata_decisions WHERE kind='primary' AND scope=?",(str(b['file_id']),)).fetchone()[0]
    if primary!=b['primary_revision']:
        raise ns_db.RevisionConflict('The surviving primary choice changed. No duplicate was removed.')
    current=conn.execute("SELECT file_id FROM file_states WHERE current_path=? AND presence_state='present' AND location_role='destination'",(str(path),)).fetchone()
    if not current or current[0]!=keep['retained_id'] or _read_hash(root,path)!=(b['sha1'],keep['identity']):
        raise ValueError('The surviving file changed or is missing. No redundant file was removed.')
    if _sidecar(conn,root,path)!=keep['sidecar']:
        raise ValueError('The surviving sidecar changed. No redundant file was removed.')
    durable._fsync_file(path);durable._fsync_directory(path.parent)
    if keep['sidecar']:durable._fsync_file(Path(str(path)+'.xmp'))
    return keep,path


def _unlink_verified(root, path, digest, identity, algorithm):
    path=metadata_transfer._path(root,path)
    if not os.path.lexists(path):
        durable._fsync_directory(path.parent)
        return
    # A read-only capture deliberately rejects mutation during its context. Hold a
    # duplicate directory descriptor after validating the chain, then unlink by name
    # only after checking the file's digest and exact recorded identity through it.
    with metadata_capture.open_source(root,path.parent.relative_to(root).as_posix(),directory=True) as (parent,_):
        directory=os.dup(parent)
    try:
        fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
        try:
            info=os.fstat(fd)
            with os.fdopen(os.dup(fd),'rb') as stream:actual=hashlib.file_digest(stream,algorithm).hexdigest()
            current=os.stat(path.name,dir_fd=directory,follow_symlinks=False)
            observed=[info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns]
            metadata_transfer._path(root,path)
            named_parent=path.parent.stat();held_parent=os.fstat(directory)
            if actual!=digest or observed!=identity or [current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns]!=identity or (named_parent.st_dev,named_parent.st_ino)!=(held_parent.st_dev,held_parent.st_ino):
                raise ValueError('The redundant file changed before removal. It was preserved.')
            os.unlink(path.name,dir_fd=directory)
            os.fsync(directory)
        finally:os.close(fd)
    finally:os.close(directory)


def consolidate(conn, op, pid, m, output):
    """Journal preservation/equality first; replay only the recorded retirement."""
    keep,path=_survivor(conn,m);root=Path(m['root'])
    intent=metadata_save._event(conn,op,'metadata_consolidation_verified')
    if not intent:
        if not _equal(root,m['photo'],str(path)):
            raise ValueError('The edited file and surviving photo differ. Both were preserved.')
        side=m['sidecar_receipt']
        if _sidecar(conn,root,m['photo'])!=side:
            raise ValueError('The edited photo sidecar changed. Both photos were preserved.')
        side_identity=list(durable._file_identity(m['sidecar'])) if side else None
        run=conn.execute('SELECT run_id FROM operations WHERE id=?',(op,)).fetchone()[0]
        arrivals=conn.execute('SELECT DISTINCT a.arrival_id,a.version_id,a.source_relative_path FROM xmp_arrivals a '
            'JOIN xmp_arrival_files f USING(arrival_id) WHERE f.file_id IN (?,?) ORDER BY a.arrival_id',
            (m['file_id'],m['retained_id'])).fetchall()
        if side and side['version_id'] not in [r[1] for r in arrivals]:
            raise ValueError('The sidecar has no associated retained history. Both photos were preserved.')
        intent=dict(survivor=keep,photo_identity=list(durable._file_identity(m['photo'])),sidecar_identity=side_identity,
                    versions=[r[1] for r in arrivals],arrivals=[])
        with ns_db.transaction(conn):
            for arrival,version,original in arrivals:
                retained=xmp_store.retain_capture(conn,data=xmp_store.original_bytes(conn,version),run_id=run,
                    source_relative_path=f'metadata-consolidation/{op}/{arrival}/'+Path(original).name,
                    file_ids=[keep['binding']['file_id'],keep['retained_id']],role='candidate',basis='unresolved')
                intent['arrivals'].append(dict(original_arrival=arrival,retained_arrival=retained['arrival_id'],version_id=version))
            for fid,role in ((keep['binding']['file_id'],'retained_copy'),(keep['retained_id'],'retained_copy')):
                conn.execute('INSERT OR IGNORE INTO operation_files VALUES(?,?,?)',(op,fid,role))
            ns_db.record_event(conn,operation_id=op,step='metadata_consolidation_verified',outcome='verified',detail=intent)
    # Reverify preserved bytes and survivor on every retry, before either unlink.
    for version in intent['versions']:xmp_store.original_bytes(conn,version)
    _survivor(conn,m)
    if m['sidecar_receipt']:
        _unlink_verified(root,m['sidecar'],m['sidecar_receipt']['sha256'],intent['sidecar_identity'],'sha256')
    _survivor(conn,m)
    _unlink_verified(root,m['photo'],output['after_sha1'],intent['photo_identity'],'sha1')
    with ns_db.transaction(conn):
        if metadata_save._event(conn,op,'metadata_consolidated') is None:
            ns_db.advance_revision(conn,pid,conn.execute('SELECT revision FROM photo_files WHERE photo_id=?',(pid,)).fetchone()[0])
            conn.execute("UPDATE photos SET status=?,dest_path=? WHERE id=?",
                ('Removed_Duplicate' if m['status']=='Completed' else 'Duplicate',str(path),pid))
            conn.execute("UPDATE file_states SET presence_state='removed',revision=revision+1 WHERE file_id=?",(m['retained_id'],))
            ns_db.record_event(conn,operation_id=op,step='metadata_consolidated',outcome='verified',
                detail=dict(photo_id=pid,survivor_photo_id=keep['photo_id'],removed_path=m['photo'],retained_path=str(path),
                            sha1=output['after_sha1'],source_consumed=m['status']=='Completed',versions=intent['versions']))
    return keep
