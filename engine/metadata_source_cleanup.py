"""Job-confirmed retirement of sources whose organized copies have embedded edits.

This is not byte-identical duplicate cleanup. A verified image-preserving edit chain,
retained source metadata and explicit Move-job consent are all required. Recovery
only observes; a new confirmed Move must authorize any remaining deletion.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path

from engine import (durable, metadata_decisions, metadata_incoming, metadata_relocate,
                    metadata_reproduce, metadata_save, metadata_transfer, ns_db, runtime, xmp_store)

KIND = 'metadata_source_cleanup'
NOTICE = ('The organized copy has saved embedded edits. Its source original is preserved. '
          'To remove originals while keeping edited copies, start a new Move and choose to include '
          'these originals (CLI: --confirm-edited-sources). Metadata history is retained, '
          'but exact original photo bytes are not.')


def needed(conn, photo_id):
    saved = metadata_save.active(conn, photo_id)
    return bool(saved and saved.get('content_changed'))


def _pending(conn, photo_id):
    return conn.execute("SELECT o.id,e.detail_json FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.photo_id=? AND e.step='intent' AND json_extract(e.detail_json,'$.kind')=? "
        "AND NOT EXISTS(SELECT 1 FROM operation_events f WHERE f.operation_id=o.id AND f.step='source_cleanup_complete') "
        "ORDER BY o.id DESC LIMIT 1", (photo_id,KIND)).fetchone()


def _roots(source, dest):
    source, dest = Path(source).absolute(), Path(dest).absolute()
    metadata_transfer._path(str(source), str(source))
    metadata_transfer._path(str(dest), str(dest))
    if source.is_relative_to(dest) or dest.is_relative_to(source) or os.path.samefile(source,dest):
        raise ValueError('Source cleanup requires separate, non-overlapping roots')
    return str(source), str(dest)


def _identity(path):
    return list(durable._file_identity(path))


def _source_sides(m):
    source = Path(m['source'])
    names = {(source.name+'.xmp').casefold(), (source.stem+'.xmp').casefold()}
    with os.scandir(source.parent) as entries:
        return {str(Path(item.path)) for item in entries if item.name.casefold() in names}


def _event(conn, op, step):
    return metadata_save._event(conn,op,step)


def _proposal(conn, photo_id, source_root, dest_root):
    source_root, dest_root = _roots(source_root,dest_root)
    if _pending(conn,photo_id):
        raise ValueError('Source cleanup is unfinished; a confirmed Move can retry its recorded intent')
    if not needed(conn,photo_id):
        raise ValueError('This photo does not require edited-source confirmation')
    row = conn.execute('SELECT p.source_path,p.dest_path,p.sha1_hash,p.status,pf.file_id FROM photos p '
        'JOIN photo_files pf ON pf.photo_id=p.id WHERE p.id=?',(photo_id,)).fetchone()
    if not row or row[3] not in ('Copied','Rejected_Copied','Duplicate'):
        raise ValueError('Choose an edited organized copy whose source has not been consumed')
    if row[3]=='Duplicate' and not conn.execute("SELECT 1 FROM operations o JOIN operation_events e ON e.operation_id=o.id WHERE o.photo_id=? AND e.step='metadata_consolidated'",(photo_id,)).fetchone():
        raise ValueError('This duplicate has no confirmed metadata consolidation')
    source, dest, sha, status, file_id = row
    source = metadata_transfer._path(source_root,source)
    dest = metadata_transfer._path(dest_root,dest)
    if not (dest.is_relative_to(Path(dest_root)/'library') or dest.is_relative_to(Path(dest_root)/'rejects')):
        raise ValueError('The retained photo is outside Library and Rejects')
    capture = conn.execute('SELECT capture_id,catalog_sha1 FROM metadata_captures WHERE file_id=? '
                           'ORDER BY capture_id DESC LIMIT 1',(file_id,)).fetchone()
    if not capture:
        raise ValueError('The original source metadata has not been captured')
    _, relative, report, captured_root = metadata_decisions._capture(conn,capture[0],allow_edited=True)
    if captured_root != source_root or report['issues']:
        raise ValueError('Resolve the source metadata or root mismatch before source cleanup')
    chain = metadata_reproduce._image_chain(conn,photo_id,capture[1],sha)
    retained = conn.execute("SELECT file_id FROM file_states WHERE current_path=? AND sha1_hash=? "
        "AND location_role='destination' AND presence_state='present'",(str(dest),sha)).fetchone()
    if not retained:
        raise ValueError('The edited destination has no retained file identity')
    if conn.execute("SELECT 1 FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.photo_id=? AND e.step='intent' AND json_extract(e.detail_json,'$.kind')='metadata_edit' "
        "AND NOT EXISTS(SELECT 1 FROM operation_events f WHERE f.operation_id=o.id AND f.step='metadata_edit_finished')",
        (photo_id,)).fetchone():
        raise ValueError('Finish the metadata edit before removing its source')
    versions=[]
    for side in report['sidecars']:
        if side['state']=='ignored' or (side['state']=='associated' and relative not in side['candidates']):
            continue
        if side['state']!='associated':
            raise ValueError('Resolve source sidecar ownership before cleanup')
        owners,_=metadata_decisions._owners(conn,source_root,side)
        if owners.get(relative)!=file_id or sorted(owners)!=sorted(side['candidates']):
            raise ValueError('Source sidecar ownership changed')
        path=metadata_transfer._path(source_root,str(Path(source_root)/side['path']))
        versions.append(dict(path=side['path'],sha256=side['sha256'],owners=owners,
            version_id=metadata_decisions._retained(conn,capture[0],side['path'],side['sha256']),identity=_identity(path)))
    m=dict(photo_id=photo_id,source_root=source_root,dest_root=dest_root,source=str(source),destination=str(dest),
        source_sha1=capture[1],sha1=sha,source_identity=_identity(source),status_before=status,
        incoming_file_id=file_id,retained_id=retained[0],capture_id=capture[0],verified_image_operations=chain,
        versions=versions,sidecar=metadata_relocate.current(conn,dest),exact_original_photo_retained=False)
    _verify(conn,None,m)
    return m


def preview_batch(db_path, *, photo_ids, source_root, destination_root):
    """Read-only facts for one future job prompt; this never grants permission."""
    results=[]
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        ns_db.require_schema(conn)
        conn.execute('BEGIN')
        for pid in photo_ids:
            try:
                proposal=_proposal(conn,pid,source_root,destination_root)
                results.append(dict(photo_id=pid,eligible=True,source=proposal['source'],destination=proposal['destination'],
                    source_sha1=proposal['source_sha1'],retained_sha1=proposal['sha1'],
                    shared_sidecars=sum(len(v['owners'])>1 for v in proposal['versions'])))
            except (ValueError,OSError,ns_db.RevisionConflict) as exc:
                results.append(dict(photo_id=pid,eligible=False,reason=str(exc)))
    return dict(photos=results,confirmation_scope='one_move_job',exact_original_photo_retained=False,
        message=NOTICE)


def authorize_run(conn, run_id, *, db_path, backups_dir, base_dir):
    """Confirmation is request-bound, never inherited from Settings or another job."""
    metadata_transfer._idle_full(conn)
    row=conn.execute('SELECT r.mode,j.submitted_request_json FROM runs r JOIN job_requests j ON j.run_id=r.id '
                     'WHERE r.id=?',(run_id,)).fetchone()
    if not row or row[0]!='MOVE' or (json.loads(row[1]).get('submitted') or {}).get('confirm_edited_sources') is not True:
        raise ValueError('This Move job has not explicitly confirmed edited-source cleanup')
    backup=ns_db.backup_catalog(db_path,backups_dir,base_dir,trigger='pre_action',related_run_id=run_id)
    if backup['outcome']!='succeeded':
        raise ValueError('The pre-cleanup catalog backup failed; edited originals are preserved')
    with ns_db.transaction(conn):
        op=ns_db.begin_operation(conn,run_id=run_id,photo_id=None,source_path=None,dest_path=None,
            kind='metadata_source_cleanup_authorization',expected={'scope':'this_move_job','exact_original_photo_retained':False})
        ns_db.settle_operation(conn,op,status='Completed',step='source_cleanup_authorized',outcome='confirmed',
            detail={'backup_attempt_id':backup['attempt_id']})


def _authorized(conn,run_id):
    return bool(conn.execute("SELECT 1 FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.run_id=? AND e.step='source_cleanup_authorized' AND e.outcome='confirmed'",(run_id,)).fetchone())


def _verify(conn, op, m):
    _roots(m['source_root'],m['dest_root'])
    row=conn.execute('SELECT p.source_path,p.dest_path,p.sha1_hash,pf.file_id FROM photos p '
        'JOIN photo_files pf ON pf.photo_id=p.id WHERE p.id=?',(m['photo_id'],)).fetchone()
    if not row or tuple(row)!=(m['source'],m['destination'],m['sha1'],m['incoming_file_id']):
        raise ValueError('The photo changed since source cleanup was planned')
    if conn.execute("SELECT 1 FROM attention_issues a JOIN operations o ON o.id=a.operation_id "
        "WHERE a.resolved_at IS NULL AND (o.photo_id=? OR o.dest_path=?) AND o.id<>? LIMIT 1",
        (m['photo_id'],m['destination'],op or -1)).fetchone():
        raise ValueError('The photo has an unresolved file issue; keep its source')
    chain=metadata_reproduce._image_chain(conn,m['photo_id'],m['source_sha1'],m['sha1'])
    if chain!=m['verified_image_operations']:
        raise ValueError('The verified image history changed')
    dest=metadata_transfer._path(m['dest_root'],m['destination'])
    if not metadata_transfer._photo_matches(dest,m['sha1']):
        raise ValueError('The edited destination is missing')
    pair=metadata_relocate.current(conn,dest)
    if pair!=m['sidecar']:
        raise ValueError('The retained sidecar changed')
    if pair:
        data=xmp_store.original_bytes(conn,pair['version_id'])
        if hashlib.sha256(data).hexdigest()!=pair['sha256'] or not metadata_transfer._sidecar_matches(Path(pair['old']),pair['sha256']):
            raise ValueError('The retained destination XMP is not verified')
    source=metadata_transfer._path(m['source_root'],m['source'])
    proof=op is not None and _event(conn,op,'source_cleanup_verified') is not None
    if os.path.lexists(source):
        if _identity(source)!=m['source_identity'] or not metadata_transfer._photo_matches(source,m['source_sha1']) or _identity(source)!=m['source_identity']:
            raise ValueError('The original source changed; it has been preserved')
        if os.path.samefile(source,dest):
            raise ValueError('Source and retained photo are the same file')
    elif not proof:
        raise ValueError('The source is absent without recorded cleanup verification')
    known={str(Path(m['source_root'])/v['path']) for v in m['versions']}
    if _source_sides(m)-known:
        raise ValueError('An unrecorded sidecar is beside the source; reindex before cleanup')
    for v in m['versions']:
        if hashlib.sha256(xmp_store.original_bytes(conn,v['version_id'])).hexdigest()!=v['sha256']:
            raise ValueError('The exact original XMP archive is not verified')
        path=metadata_transfer._path(m['source_root'],str(Path(m['source_root'])/v['path']))
        if os.path.lexists(path):
            if _identity(path)!=v['identity'] or metadata_transfer._xmp_digest(path)!=v['sha256'] or _identity(path)!=v['identity']:
                raise ValueError('A source XMP changed; preserve the pair')
        elif not proof:
            raise ValueError('A source XMP is absent without cleanup verification')


def _durable(m):
    paths=[Path(m['destination'])]+([Path(m['sidecar']['old'])] if m['sidecar'] else [])
    for path in paths:
        durable._fsync_file(path)
        # Establish every directory entry even for standalone observation/retry.
        parent=path.parent
        while True:
            durable._fsync_directory(parent)
            if parent==Path(m['dest_root']):break
            parent=parent.parent


def _finish(conn, op, m, *, complete, error=None, notes=None):
    status=('Removed_Duplicate' if m['status_before']=='Duplicate' else 'Rejected' if m['status_before'].startswith('Rejected') else 'Completed')
    with ns_db.transaction(conn):
        if complete:
            run_id=conn.execute('SELECT run_id FROM operations WHERE id=?',(op,)).fetchone()[0]
            ns_db.record_delivery(conn,operation_id=op,photo_id=m['photo_id'],run_id=run_id,
                destination=m['destination'],source_removed=True,created=False,sha1_hash=m['sha1'])
            conn.execute('UPDATE photos SET status=? WHERE id=?',(status,m['photo_id']))
        event=ns_db.settle_operation(conn,op,status=status if complete else 'Failed',
            step='source_cleanup_complete' if complete else 'source_cleanup_incomplete',
            outcome='completed' if complete else 'needs_attention',error_message=error,
            detail={**m,'notes':notes or []})
        if complete:
            for issue, in conn.execute('SELECT issue_id FROM attention_issues WHERE operation_id=? AND resolved_at IS NULL',(op,)).fetchall():
                ns_db.resolve_attention_issue(conn,issue,event_id=event)
        else:
            ns_db.open_attention_issue(conn,operation_id=op,category='unestablished_outcome',
                summary=error,file_id=m['retained_id'])
    return dict(status=status if complete else 'Failed',resolved=complete,error=error,notes=notes or [])


def execute(conn,op,*,run_id=None,source_root,destination_root,observe=False):
    metadata_transfer._idle_full(conn)
    row=conn.execute("SELECT e.detail_json FROM operation_events e WHERE e.operation_id=? AND e.step='intent' ORDER BY event_id LIMIT 1",(op,)).fetchone()
    if not row or json.loads(row[0]).get('kind')!=KIND:raise ValueError('Unknown edited-source cleanup')
    m=json.loads(row[0])['expected']
    if (str(Path(source_root).absolute()),str(Path(destination_root).absolute()))!=(m['source_root'],m['dest_root']):
        raise ValueError('Restore the original source and destination mounts before cleanup')
    if _event(conn,op,'source_cleanup_complete') is not None:
        return dict(status='Skipped',resolved=True)
    if not observe:
        job=conn.execute('SELECT source_path,dest_path,mode FROM runs WHERE id=?',(run_id,)).fetchone()
        if not _authorized(conn,run_id) or not job or tuple(job)!=(m['source_root'],m['dest_root'],'MOVE'):
            raise ValueError('A confirmed Move with the original roots is required to resume source cleanup')
    try:
        _verify(conn,op,m)
        source=Path(m['source'])
        if observe:
            if os.path.lexists(source):
                raise ValueError('The source is preserved. Run a confirmed Move to finish cleanup')
            if any(os.path.lexists(Path(m['source_root'])/v['path']) and not metadata_incoming._shared(conn,m,v) for v in m['versions']):
                raise ValueError('The photo source was removed; a confirmed Move is needed to finish XMP cleanup')
            _durable(m)
            # A crash may have interrupted the post-unlink directory barrier.
            for parent in {source.parent, *(Path(m['source_root'],v['path']).parent for v in m['versions'])}:
                durable._fsync_directory(parent)
        else:
            if runtime.cancel_requested.is_set():
                raise ValueError('Cleanup cancelled before source deletion; source files were preserved')
            _durable(m)
            # Recheck after flushes, immediately before granting deletion proof.
            _verify(conn,op,m)
            with ns_db.transaction(conn):
                ns_db.record_event(conn,operation_id=op,step='source_cleanup_verified',outcome='verified',
                    detail={'run_id':run_id,'original_sha1':m['source_sha1'],'retained_sha1':m['sha1'],
                            'image_operations':m['verified_image_operations'],'exact_original_photo_retained':False})
            if os.path.lexists(source):
                durable._remove_verified_source(source,Path(m['destination']),tuple(m['source_identity']),
                                                'Remove confirmed source with verified edited Library copy')
            durable._fsync_directory(source.parent)
            for v in m['versions']:
                if metadata_incoming._shared(conn,m,v):continue
                path=metadata_transfer._path(m['source_root'],str(Path(m['source_root'])/v['path']))
                if os.path.lexists(path):
                    if _identity(path)!=v['identity'] or metadata_transfer._xmp_digest(path)!=v['sha256'] or _identity(path)!=v['identity']:
                        raise ValueError('Source XMP changed before cleanup; it was preserved')
                    path.unlink()
                durable._fsync_directory(path.parent)
        notes=['Shared source XMP retained for another owner' for v in m['versions']
               if os.path.lexists(Path(m['source_root'])/v['path'])]
        return _finish(conn,op,m,complete=True,notes=notes)
    except (ValueError,OSError,ns_db.RevisionConflict,durable.SourceRemovalRefused) as exc:
        return _finish(conn,op,m,complete=False,error=str(exc))


def transfer(conn,*,photo_id,run_id,source_root,destination_root):
    """Caller holds the engine lock; consent and backup belong to this Move only."""
    metadata_transfer._idle_full(conn)
    if not _authorized(conn,run_id):raise ValueError(NOTICE)
    previous=_pending(conn,photo_id)
    if previous:
        op=previous[0]
    else:
        m=_proposal(conn,photo_id,source_root,destination_root)
        with ns_db.transaction(conn):
            op=ns_db.begin_operation(conn,run_id=run_id,photo_id=photo_id,source_path=m['source'],
                dest_path=m['destination'],kind=KIND,expected=m)
            conn.execute('UPDATE operations SET sha1_hash=? WHERE id=?',(m['sha1'],op))
    result=execute(conn,op,run_id=run_id,source_root=source_root,destination_root=destination_root)
    if previous:
        with ns_db.transaction(conn):
            retry=ns_db.begin_operation(conn,run_id=run_id,photo_id=photo_id,source_path=None,dest_path=None,
                kind='metadata_source_cleanup_retry',reconciles=op)
            ns_db.settle_operation(conn,retry,status=result['status'],step='source_cleanup_retry',
                outcome='completed' if result['resolved'] else 'needs_attention',error_message=result.get('error'))
    return result


def preserved_owner(conn, *, source, source_file_id, owner_sha1, sidecar, sidecar_sha256, destination_root):
    """Proof for a later shared-sidecar owner, including post-cleanup Rename/edits.

    Exact original XMP remains archived. A completed source cleanup and its original
    file identity must match; current destination bytes and image history are verified.
    """
    rows=conn.execute("SELECT e.detail_json,s.current_path,s.sha1_hash FROM operations o "
        "JOIN operation_events e ON e.operation_id=o.id AND e.step='source_cleanup_complete' "
        "JOIN operation_files f ON f.operation_id=o.id AND f.role='retained_copy' "
        "JOIN file_states s ON s.file_id=f.file_id AND s.location_role='destination' AND s.presence_state='present' "
        "WHERE o.source_path=? ORDER BY e.event_id DESC",(source,)).fetchall()
    for raw,path,digest in rows:
        m=json.loads(raw)
        if m['incoming_file_id']!=source_file_id or m['dest_root']!=str(destination_root):
            continue
        version=next((v for v in m['versions'] if str(Path(m['source_root'])/v['path'])==sidecar
                      and v['sha256']==sidecar_sha256),None)
        if not version:continue
        if hashlib.sha256(xmp_store.original_bytes(conn,version['version_id'])).hexdigest()!=sidecar_sha256:
            raise ValueError('The shared XMP archive is not verified')
        metadata_reproduce._image_chain(conn,m['photo_id'],m['source_sha1'],owner_sha1)
        metadata_reproduce._image_chain(conn,m['photo_id'],m['source_sha1'],digest)
        retained=metadata_transfer._path(str(destination_root),path)
        if not metadata_transfer._photo_matches(retained,digest):continue
        pair=metadata_relocate.current(conn,retained)
        if pair and not metadata_transfer._sidecar_matches(Path(pair['old']),pair['sha256']):continue
        if ns_db.paths_needing_attention(conn,[str(retained)]):continue
        return True
    return False
