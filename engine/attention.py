"""Explicit, read-only checks of uncertain operations; catalog repairs require evidence."""
import contextlib
import json
from pathlib import Path

from engine import jobs, ns_db, reconcile, relocate, runtime, store
from engine.ns_db import PhotoStatus, RunStatus


def predicate():
    return ("p.id IN (SELECT ao.photo_id FROM attention_issues ai JOIN operations ao ON ao.id=ai.operation_id "
            "WHERE ai.category='unestablished_outcome' AND ai.resolved_at IS NULL)")


def for_operations(conn, ids):
    if not ids:
        return {}
    result = {}
    for row in conn.execute("SELECT issue_id,operation_id,summary,opened_at FROM attention_issues "
                            "WHERE resolved_at IS NULL AND category='unestablished_outcome' "
                            "AND operation_id IN (SELECT value FROM json_each(?)) ORDER BY issue_id", (json.dumps(ids),)):
        issue = dict(zip(('issue_id','operation_id','summary','opened_at'), row))
        issue['evidence'] = [dict(zip(('location','path','kind','result','observed_at','details'), e)) for e in conn.execute(
            "SELECT e.location_role,e.observed_path,e.observation_kind,e.result,e.observed_at,e.details_json "
            "FROM operation_evidence e WHERE e.operation_id=? OR e.evidence_id IN "
            "(SELECT evidence_id FROM attention_evidence WHERE issue_id=?) ORDER BY e.evidence_id DESC LIMIT 20",
            (issue['operation_id'],issue['issue_id']))]
        result.setdefault(issue['operation_id'], []).append(issue)
    return result


def for_photo(conn, photo_id):
    ids = [r[0] for r in conn.execute("SELECT DISTINCT o.id FROM operations o JOIN attention_issues a ON a.operation_id=o.id WHERE o.photo_id=? AND a.resolved_at IS NULL",(photo_id,))]
    return [i for group in for_operations(conn,ids).values() for i in group]


def _signature(path):
    state = reconcile._recovery_observe(path)
    if state != 'present':
        return state
    s = path.lstat()
    return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)


def check_issue(db_path, source_root, dest_root, run_id, issue_id):
    """Observe only the recorded pair. Never finish a filesystem mutation or dismiss doubt.

    A new operation preserves the original failed outcome. Evidence, any catalog repair,
    and issue resolution commit together at FULL under the caller's engine lock.
    """
    with contextlib.closing(store.get_db_connection(str(db_path), synchronous='FULL')) as c:
        row = c.execute("SELECT a.operation_id,a.file_id,o.photo_id,o.source_path,o.dest_path,a.resolved_at "
                        "FROM attention_issues a JOIN operations o ON o.id=a.operation_id "
                        "WHERE a.issue_id=? AND a.category='unestablished_outcome'",(issue_id,)).fetchone()
        if not row:
            raise ValueError('This file issue no longer exists. Reload the photo.')
        original, file_id, pid, old, new, resolved = row
        if resolved:
            return {'resolved':True,'message':'This issue was already verified.'}
        intent = c.execute("SELECT detail_json,timestamp FROM operation_events WHERE operation_id=? AND step='intent' ORDER BY event_id LIMIT 1",(original,)).fetchone()
        detail = json.loads(intent[0]) if intent and intent[0] else {}
        expected = detail.get('expected') or {}
        kind = detail.get('kind')
        photo = c.execute('SELECT sha1_hash,source_path,dest_path,status FROM photos WHERE id=?',(pid,)).fetchone()
        # Transfers may omit a digest in intent. Use the immutable scan observation
        # that existed then, never a later mutable photo-row hash as historical proof.
        observed = c.execute("SELECT f.sha1_hash FROM file_observations f JOIN operation_files of ON of.file_id=f.file_id "
            "WHERE of.operation_id=? AND of.role='source' AND f.source_path=? AND f.observed_at<=? "
            "ORDER BY f.observation_id DESC LIMIT 1",(original,old,intent[1] if intent else '')).fetchone()
        sha = expected.get('sha1_hash') or (observed[0] if observed else None)
        relocation = kind in relocate._RELOCATION_NOUNS
        problem = None
        evidence = []
        states, signatures = {}, {}
        roots = {'source':Path(dest_root if relocation else source_root).absolute(), 'destination':Path(dest_root).absolute()}
        paths = {'source':Path(old) if old else None,'destination':Path(new) if new else None}
        if not photo or not sha or photo[0] != sha:
            problem = 'The catalog content has changed or has no recorded checksum. Review the file history before taking further action.'
        elif kind not in ('copy','move','move_already_present','duplicate_removal',*relocate._RELOCATION_NOUNS):
            problem = 'This operation has no supported transfer intent. Review its recorded evidence outside the app.'
        elif (photo[2] not in (old,new) if relocation else (photo[1] != old or photo[2] != new)):
            problem = 'The catalog paths have changed since this operation. Review the current file history.'
        if not problem:
            for role,path in paths.items():
                root=roots[role]
                if (path is None or not path.is_absolute() or not root.is_dir()
                        or not path.absolute().is_relative_to(root)
                        or not path.resolve().is_relative_to(root.resolve())):
                    problem = 'A recorded path is outside the configured folders, or its storage is unavailable. Restore the original mounts before checking again.'
                    break
        if not problem:
            try:
                for role,path in paths.items():
                    signatures[role] = _signature(path)
                    state = reconcile._recovery_observe(path)
                    if state == 'present':
                        state, observed = reconcile._recovery_verify(path,sha,cancelled=runtime.cancel_requested.is_set)
                        evidence.append((role,str(path),'sha1',state if state in ('match','mismatch') else 'unreadable',observed))
                    else:
                        evidence.append((role,str(path),'stat',state if state == 'absent' else 'unreadable',{'state':state}))
                    states[role] = state
                if any(_signature(path) != signatures[role] for role,path in paths.items()):
                    problem = 'A file changed during the check. Wait for other file activity to finish, then check again.'
            except OSError as exc:
                problem = f'The files could not be checked: {exc}. Restore access before checking again.'
        if runtime.cancel_requested.is_set():
            return {'resolved':False,'message':'Check cancelled. The issue remains open.'}
        source, dest = states.get('source'), states.get('destination')
        if not relocation and source == dest == 'match' and signatures['source'][:2] == signatures['destination'][:2]:
            problem = 'Both paths identify the same underlying file. Use separate source and destination storage before checking again.'
        retained = c.execute("SELECT sha1_hash FROM file_states WHERE current_path=? AND location_role='destination' AND presence_state='present'",(new,)).fetchone()
        if not problem and retained and retained[0] != sha:
            problem = 'The destination identity has changed in the catalog. Review the file history before taking further action.' 
        if not problem and expected.get('rejected') and dest != 'match':
            problem = 'The rejected destination copy is not verified. Restore that file or its storage before checking again.'
        verified = not problem and ((source == 'match' and dest == 'absent') or
                    (dest == 'match' and source in (('absent',) if relocation else ('absent','match'))))
        if relocation and verified:
            binding=c.execute('SELECT current_path,sha1_hash FROM file_states WHERE file_id=?',(expected.get('file_id'),)).fetchone()
            if not binding or binding[0] not in (old,new) or binding[1] != sha:
                verified=False
                problem='The recorded file identity has changed. Review the current file history before taking further action.'
        message = problem or (('Verified the file at its destination.' if dest == 'match' else
            'Verified the original file; the operation did not complete. You can start it again explicitly.') if verified else
            f'Could not confirm the outcome: original location {source}, destination {dest}. Check both locations and restore the expected file or storage outside the app, then check again. Nothing was moved or deleted.')
        with ns_db.transaction(c):
            op=ns_db.begin_operation(c,run_id=run_id,photo_id=pid,source_path=old,dest_path=new,
                                    kind='attention_check',reconciles=original,expected={'issue_id':issue_id,'sha1_hash':sha})
            for role,path,observation,result,details in evidence:
                eid=ns_db.record_evidence(c,operation_id=op,location_role=role,observed_path=path,
                    observation_kind=observation,result=result,details=details)
                c.execute('INSERT INTO attention_evidence VALUES(?,?)',(issue_id,eid))
            if verified:
                if relocation:
                    retained=new if dest == 'match' else old
                    if dest == 'match':
                        relocate._record_relocation(c,op,old,new,expected['file_id'],step='recovery',
                            operation_status=expected.get('operation_status','Renamed'),
                            photo_id=pid if kind != 'rename' else None,status_after=expected.get('status_after'))
                    c.execute("UPDATE file_states SET current_path=?,presence_state='present',revision=revision+1 WHERE file_id=?",(retained,expected['file_id']))
                elif dest == 'match':
                    ns_db.record_delivery(c,operation_id=op,photo_id=pid,run_id=run_id,destination=new,
                                         source_removed=source=='absent',created=False,sha1_hash=sha)
                    final=PhotoStatus.FOUND_AT_DESTINATION if source=='absent' else PhotoStatus.COPIED
                    if kind=='duplicate_removal' and source=='match':
                        final=PhotoStatus.DUPLICATE
                    if expected.get('rejected'):
                        final=PhotoStatus.REJECTED if source=='absent' else PhotoStatus.REJECTED_COPIED
                    c.execute('UPDATE photos SET status=? WHERE id=?',(final,pid))
                else:
                    final=PhotoStatus.DUPLICATE if kind=='duplicate_removal' else PhotoStatus.PENDING
                    if expected.get('rejected'):
                        final=PhotoStatus.REJECTED_COPIED
                    c.execute('UPDATE photos SET status=? WHERE id=?',(final,pid))
                    c.execute("UPDATE file_states SET presence_state='present',revision=revision+1 WHERE file_id=(SELECT file_id FROM photo_files WHERE photo_id=?) AND location_role='source'",(pid,))
            event=ns_db.settle_operation(c,op,status='Skipped' if verified else PhotoStatus.FAILED,
                step='recovery',outcome='verified' if verified else 'unestablished',error_message=message)
            if verified:
                ns_db.resolve_attention_issue(c,issue_id,event_id=event)
            else:
                c.execute('UPDATE attention_issues SET summary=? WHERE issue_id=?',(message,issue_id))
        return {'resolved':bool(verified),'message':message}


def run_check(args, db_path, lock_fd):
    def body(run_id, config):
        runtime.run_progress.start('checking_destination',1)
        answer=check_issue(db_path,Path(args.source),Path(args.dest),run_id,args.check_issue)
        runtime.run_progress.add('ok' if answer['resolved'] else 'failed')
        runtime.logger.info(answer['message'])
        return RunStatus.CANCELLED if runtime.cancel_requested.is_set() else RunStatus.COMPLETED
    return jobs.run_maintenance_job(args,db_path,lock_fd,mode='CHECK',label='File issue check',
        submitted={'issue_id':args.check_issue,'source':str(Path(args.source).resolve()),'dest':str(Path(args.dest).resolve())},
        defaults={},overrides={},reconcile_files=False,body=body)
