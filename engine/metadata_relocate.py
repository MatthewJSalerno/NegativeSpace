"""Sidecar-aware Rename, Reject and Return, sharing the photo relocation history.

Publish both new names before retiring either old name. Startup can finish verified
old-name cleanup but never publishes a missing member; repeating the original action
explicitly resumes that publication. No metadata contents or source archives change.
"""
import contextlib
import errno
import hashlib
import json
import os
from pathlib import Path

from engine import durable, fileinfo, metadata_transfer, ns_db, reconcile, relocate, runtime, xmp_store
from engine.ns_db import PhotoStatus


class PairRelocationRefused(OSError):
    """A pair cannot move safely, with both old names preserved where possible."""


def current(conn, old):
    """Find the sidecar receipt through the retained photo identity, not its old name."""
    row = conn.execute("SELECT e.detail_json FROM file_states f JOIN operation_files of ON of.file_id=f.file_id "
        "JOIN operation_events e ON e.operation_id=of.operation_id "
        "WHERE f.current_path=? AND f.location_role='destination' AND f.presence_state='present' "
        "AND e.step='pair_complete' ORDER BY e.event_id DESC LIMIT 1",(str(old),)).fetchone()
    if row:
        receipt=json.loads(row[0])
        return {'old':str(old)+'.xmp','sha256':receipt['xmp_sha256'],'version_id':receipt['version_id']}
    if os.path.lexists(str(old)+'.xmp'):
        raise PairRelocationRefused('An unrecorded XMP exists beside this photo; resolve its ownership before relocating the photo. Nothing was moved.')
    return None


def pending(conn, old):
    row=conn.execute("SELECT o.id,e.detail_json FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.source_path=? AND e.step='intent' AND json_type(e.detail_json,'$.expected.sidecar')='object' "
        "AND EXISTS(SELECT 1 FROM attention_issues a WHERE a.operation_id=o.id AND a.resolved_at IS NULL) "
        "ORDER BY o.id DESC LIMIT 1",(str(old),)).fetchone()
    return (row[0],json.loads(row[1])) if row else None


def choose_target(conn, root, old, wanted, kind):
    """Reuse this action's unfinished target; never suffix around an orphan XMP."""
    sidecar=current(conn,old)
    previous=pending(conn,old)
    if previous:
        intent=previous[1]; expected=intent['expected']
        if intent['kind'] != kind or expected['sidecar'].get('wanted') != str(wanted):
            raise PairRelocationRefused('Finish the recorded photo/XMP relocation before requesting a different action or name.')
        return Path(expected['new_path'])
    candidate=Path(wanted);counter=1
    while candidate != Path(old) and os.path.lexists(candidate):
        candidate=Path(wanted).with_name(f'{Path(wanted).stem}_{counter}{Path(wanted).suffix}')
        counter+=1
    metadata_transfer._path(root,str(candidate))
    if candidate != Path(old) and os.path.lexists(str(candidate)+'.xmp'):
        raise PairRelocationRefused('An XMP already occupies the proposed destination without its photo. Resolve that destination pair before retrying.')
    if ns_db.paths_needing_attention(conn,[str(old)]):
        raise PairRelocationRefused('This photo has an unresolved file issue. Verify it before relocating the pair.')
    return candidate


def plan(conn, root, old, new, sha1, *, wanted):
    sidecar=current(conn,old)
    if sidecar is None:
        return None
    for path in (old,new,sidecar['old'],str(new)+'.xmp'):
        metadata_transfer._path(root,path)
    data=xmp_store.original_bytes(conn,sidecar['version_id'])
    if hashlib.sha256(data).hexdigest() != sidecar['sha256']:
        raise PairRelocationRefused('The archived XMP version is not verified')
    if not metadata_transfer._sidecar_matches(Path(sidecar['old']),sidecar['sha256']):
        raise PairRelocationRefused('The recorded XMP is missing. Restore it before relocating this photo.')
    if not metadata_transfer._photo_matches(Path(old),sha1):
        raise PairRelocationRefused('The recorded photo is missing')
    previous=pending(conn,old)
    if not previous and (os.path.lexists(new) or os.path.lexists(str(new)+'.xmp')):
        raise PairRelocationRefused('The proposed destination became occupied. Nothing was moved.')
    sidecar.update(new=str(new)+'.xmp',root=str(root),wanted=str(wanted),
                   photo_identity=durable._file_identity(old),identity=durable._file_identity(sidecar['old']),
                   retry_of=previous[0] if previous else None)
    return sidecar


def _members(expected):
    side=expected['sidecar']
    return ((Path(expected['old_path']),Path(expected['new_path']),expected['sha1_hash'],False,side['photo_identity']),
            (Path(side['old']),Path(side['new']),side['sha256'],True,side['identity']))


def _matches(path,digest,is_xmp):
    if runtime.cancel_requested.is_set():
        raise PairRelocationRefused('The pair check was cancelled; its outcome remains unconfirmed')
    return (metadata_transfer._sidecar_matches if is_xmp else metadata_transfer._photo_matches)(path,digest)


def _publish(old,new,digest,is_xmp,*,reusing):
    if os.path.lexists(new):
        if not reusing or not _matches(new,digest,is_xmp):
            raise PairRelocationRefused('The new name is occupied; no file was overwritten')
        return
    if not _matches(old,digest,is_xmp):
        raise PairRelocationRefused('A required old pair member is missing')
    try:
        os.link(old,new)
    except FileExistsError:
        raise
    except OSError as exc:
        if exc.errno not in (errno.EXDEV,errno.EPERM,errno.ENOTSUP,errno.EOPNOTSUPP,errno.EMLINK,errno.ENOSYS):
            raise
        # Keep old files on filesystems without hard links. Publication still uses
        # strict no-replace rename, never a check followed by an overwriting rename.
        partial=durable._stage_copy(old,new)
        try:
            if fileinfo.compute_sha1(str(partial)) != fileinfo.compute_sha1(str(old)):
                raise PairRelocationRefused('The staged pair member failed verification')
            relocate._rename_noreplace(str(partial),str(new))
        finally:
            with contextlib.suppress(OSError):partial.unlink()
    durable._fsync_file(new)
    durable._fsync_directory(new.parent)


def _verify_new(conn,op,expected):
    for _,new,digest,is_xmp,_ in _members(expected):
        if not _matches(new,digest,is_xmp):
            raise PairRelocationRefused('Both new files must verify before old-name cleanup')
        durable._fsync_file(new)
        durable._fsync_directory(new.parent)
        durable._fsync_chain_to_root(new.parent)
    with ns_db.transaction(conn):
        for _,new,digest,is_xmp,_ in _members(expected):
            ns_db.record_evidence(conn,operation_id=op,location_role='destination',observed_path=str(new),
                observation_kind='sha256' if is_xmp else 'sha1',result='match',details={'digest':digest,'pair_verified':True})


def _cleanup(expected):
    # Used only after _verify_new; this is destination old-name retirement, never
    # deletion of an import source. A hard-linked pair retains its inode at new.
    for old,new,digest,is_xmp,identity in _members(expected):
        if reconcile._recovery_observe(old) == 'absent':
            # A previous attempt may have unlinked and failed on this barrier.
            durable._fsync_directory(old.parent)
            continue
        if list(durable._file_identity(old)) != list(identity) or not _matches(old,digest,is_xmp):
            raise PairRelocationRefused('An old pair member is not the file that was verified; nothing further was removed')
        fileinfo.require_plain_path(old);fileinfo.require_plain_path(new)
        if not _matches(new,digest,is_xmp):
            raise PairRelocationRefused('The verified new pair member is no longer present')
        if os.path.samefile(old,new):
            old.unlink()
        else:
            durable._remove_verified_source(old,new,tuple(identity),'Remove verified old destination name')
        durable._fsync_directory(old.parent)


def perform(conn,op,expected):
    """Intent already committed by the caller; leave every failure recoverable."""
    previous_root=durable._destination_root
    durable._destination_root=Path(expected['sidecar']['root'])
    durable._verified_directories.clear()
    try:
        durable._mkdir_durable(Path(expected['new_path']).parent)
        for old,new,digest,is_xmp,_ in reversed(_members(expected)):
            for path in (old,new):metadata_transfer._path(expected['sidecar']['root'],str(path))
            _publish(old,new,digest,is_xmp,reusing=bool(expected['sidecar']['retry_of']))
        _verify_new(conn,op,expected)
        _cleanup(expected)
    finally:
        durable._destination_root=previous_root
        durable._verified_directories.clear()


def finish(conn,op,expected,kind,photo_id,*,recovery=False,reconciles=None):
    """In the caller's outcome transaction; current paths and history advance together."""
    event=relocate._record_relocation(conn,op,expected['old_path'],expected['new_path'],expected['file_id'],
        step='recovery' if recovery else kind,operation_status=expected.get('operation_status','Renamed'),
        photo_id=photo_id if kind!='rename' else None,status_after=expected.get('status_after'),
        detail={'sidecar':expected['sidecar'],'status_before':expected.get('status_before'),'recovered':recovery})
    prior=reconciles or op
    while prior:
        if prior != op and conn.execute(
                "SELECT 1 FROM operation_events WHERE operation_id=? AND step<>'intent'",(prior,)).fetchone() is None:
            ns_db.settle_operation(conn,prior,status=PhotoStatus.FAILED,step='recovery',
                outcome='continued_by_retry',detail={'completed_by_operation_id':op})
        for (issue,) in conn.execute("SELECT issue_id FROM attention_issues WHERE operation_id=? AND resolved_at IS NULL "
                                    "AND category='unestablished_outcome'",(prior,)).fetchall():
            ns_db.resolve_attention_issue(conn,issue,event_id=event)
        row=conn.execute("SELECT detail_json FROM operation_events WHERE operation_id=? AND step='intent' ORDER BY event_id LIMIT 1",(prior,)).fetchone()
        prior=(json.loads(row[0]).get('expected') or {}).get('sidecar',{}).get('retry_of') if row else None
    return event


def _intent(conn,op):
    row=conn.execute("SELECT o.photo_id,e.detail_json FROM operations o JOIN operation_events e ON e.operation_id=o.id "
                     "WHERE o.id=? AND e.step='intent' ORDER BY e.event_id LIMIT 1",(op,)).fetchone()
    detail=json.loads(row[1]);return row[0],detail['kind'],detail['expected']


def recover(conn,op,run_id,*,allow_cleanup=True,dest_root=None):
    """Verify both locations. Never publish a missing member in recovery/checks.

    Startup may finish verified old-name cleanup, as photo-only relocation recovery
    does. Check it now is read-only and leaves that cleanup for an explicit retry.
    """
    pid,kind,expected=_intent(conn,op);old=expected['old_path'];new=expected['new_path']
    evidence=[];message=None;complete=False;not_started=False
    root=expected['sidecar']['root']
    previous_root=durable._destination_root
    durable._destination_root=Path(root);durable._verified_directories.clear()
    try:
        if dest_root is not None and str(Path(dest_root))!=root:
            raise PairRelocationRefused('Restore the recorded destination mount before checking this pair')
        photo=conn.execute('SELECT dest_path,sha1_hash FROM photos WHERE id=?',(pid,)).fetchone()
        if not photo or photo[0] not in (old,new) or photo[1]!=expected['sha1_hash']:
            raise PairRelocationRefused('The catalog photo changed; review its history before retrying')
        binding=conn.execute('SELECT current_path,sha1_hash FROM file_states WHERE file_id=?',(expected['file_id'],)).fetchone()
        if not binding or binding[0] not in (old,new) or binding[1]!=expected['sha1_hash']:
            raise PairRelocationRefused('The catalog identity changed; review this pair before retrying')
        old_states=[];new_states=[]
        for before,after,digest,is_xmp,_ in _members(expected):
            for role,path,states in (('source',before,old_states),('destination',after,new_states)):
                metadata_transfer._path(root,str(path))
                state=reconcile._recovery_observe(path)
                if state=='present':state='match' if _matches(path,digest,is_xmp) else 'absent'
                states.append(state)
                evidence.append((role,str(path),state,digest,is_xmp))
        new_ok=new_states==['match','match'];old_ok=old_states==['match','match']
        if new_ok:
            if any(s not in ('match','absent') for s in old_states):
                raise PairRelocationRefused('An old pair path could not be verified')
            if not allow_cleanup and old_states!=['absent','absent']:
                raise PairRelocationRefused('Both new files are verified; repeat the original action to finish old-name cleanup')
            _verify_new(conn,op,expected)
            if allow_cleanup:
                _cleanup(expected)
            else:
                # A previous cleanup may have failed after unlink but before sync.
                # Check it now changes no directory entries, but proves durability.
                for before,_,_,_,_ in _members(expected):
                    durable._fsync_directory(before.parent)
            complete=True
            message='The photo and its XMP are verified at the new location.'
        elif old_ok and new_states==['absent','absent']:
            not_started=True
            message='The original photo and XMP are verified unchanged. The relocation did not happen; repeat the action when ready.'
        else:
            raise PairRelocationRefused('The photo/XMP relocation is incomplete. Restore destination access and repeat the same action to finish it; neither member is considered relocated alone')
    except Exception as exc:
        message=str(exc)
    finally:
        durable._destination_root=previous_root;durable._verified_directories.clear()
    with ns_db.transaction(conn):
        repair=ns_db.begin_operation(conn,run_id=run_id,photo_id=pid,source_path=old,dest_path=new,
            kind='pair_relocation_check',expected={'original_operation_id':op},reconciles=op)
        for role,path,state,digest,is_xmp in evidence:
            ns_db.record_evidence(conn,operation_id=repair,location_role=role,observed_path=path,
                observation_kind='sha256' if is_xmp else 'sha1',result=state if state in ('match','absent') else 'unreadable',
                details={'expected_digest':digest})
        if complete:
            finish(conn,op if allow_cleanup else repair,expected,kind,pid,recovery=True,
                   reconciles=None if allow_cleanup else op)
        else:
            event=ns_db.settle_operation(conn,op,status=PhotoStatus.FAILED,step='recovery',
                outcome='not_started' if not_started else 'unestablished',error_message=message)
            issues=conn.execute("SELECT issue_id FROM attention_issues WHERE operation_id=? AND resolved_at IS NULL AND category='unestablished_outcome'",(op,)).fetchall()
            if not_started:
                for (issue,) in issues:ns_db.resolve_attention_issue(conn,issue,event_id=event)
            elif issues:
                conn.execute('UPDATE attention_issues SET summary=? WHERE operation_id=? AND resolved_at IS NULL',(message,op))
            else:
                ns_db.open_attention_issue(conn,operation_id=op,file_id=expected['file_id'],category='unestablished_outcome',summary=message)
        conn.execute("INSERT OR IGNORE INTO operation_files(operation_id,file_id,role) SELECT ?,file_id,role FROM operation_files WHERE operation_id=? AND role<>'source'",(repair,op))
        ns_db.settle_operation(conn,repair,status=expected.get('operation_status','Renamed') if complete else PhotoStatus.FAILED,
            step='recovery',outcome='recorded',error_message=message)
    return {'resolved':complete or not_started,'message':message}
