"""Incoming XMP alternatives and deliberate choices, independent of any screen.

Catalog evidence never authorizes removal by itself. Transfer callers must verify
the retained photo and original sidecars live before consuming an incoming source.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re

from engine import durable, fileinfo, metadata_decisions, metadata_incoming_apply, metadata_transfer, ns_db, reconcile, xmp_store


def _json(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False)


def _target(conn, photo_id):
    if type(photo_id) is not int or not 1 <= photo_id <= 2**63-1:
        raise ValueError('Invalid retained photo identity')
    row=conn.execute('SELECT p.sha1_hash,p.dest_path,p.status,pf.file_id,pf.revision,f.file_id,f.revision '
        'FROM photos p JOIN photo_files pf ON pf.photo_id=p.id JOIN file_states f ON f.current_path=p.dest_path '
        "AND f.location_role='destination' AND f.presence_state='present' WHERE p.id=?",(photo_id,)).fetchone()
    if not row or row[2] not in ('Copied','Completed','Found_At_Destination','Rejected','Rejected_Copied'):
        raise ValueError('Choose an organized photo with a retained destination identity')
    primary=metadata_decisions.current(conn,'primary',str(row[3]))
    pair=conn.execute("SELECT e.detail_json FROM operation_events e JOIN operation_files f ON f.operation_id=e.operation_id "
        "WHERE f.file_id=? AND e.step='pair_complete' ORDER BY e.event_id DESC LIMIT 1",(row[5],)).fetchone()
    return {'photo_id':photo_id,'sha1':row[0],'path':row[1],'status':row[2],
        'source_file_id':row[3],'photo_revision':row[4],'file_id':row[5],'file_revision':row[6],
        'primary':primary,'pair':json.loads(pair[0]) if pair else None}


def _versions(conn, capture_id, *, highwater=None):
    file_id,relative,report,root=metadata_decisions._capture(conn,capture_id)
    if any(i.get('source')!='sidecars' or i.get('code')!='metadata_choice_needed' for i in report['issues']):
        raise ValueError('Resolve incoming metadata capture or ownership issues first')
    result=[]
    for side in report['sidecars']:
        if side['state']=='ignored' or (side['state']=='associated' and relative not in side['candidates']):
            continue
        owners,_=metadata_decisions._owners(conn,root,side,highwater=highwater)
        if side['state']!='associated' or owners.get(relative)!=file_id:
            raise ValueError('Resolve incoming sidecar ownership first')
        version=metadata_decisions._retained(conn,capture_id,side['path'],side['sha256'])
        arrival=conn.execute('SELECT a.arrival_id FROM xmp_arrivals a JOIN metadata_captures m ON m.run_id=a.run_id '
            'WHERE m.capture_id=? AND a.version_id=? AND a.source_relative_path=?',
            (capture_id,version,side['path'])).fetchone()[0]
        result.append({'version_id':version,'arrival_id':arrival,'path':side['path'],
            'sha256':side['sha256'],'owners':owners})
    if not result:
        raise ValueError('The incoming capture has no associated valid XMP')
    return file_id,root,report,result


def alternatives(conn, retained_file_id):
    """Metadata/lineage only: no BLOB decompression on ordinary reads."""
    values=[]
    for raw, in conn.execute("SELECT value_json FROM metadata_decisions WHERE kind='incoming' "
                            'AND scope=? ORDER BY decision_id',(str(retained_file_id),)):
        values.append(json.loads(raw))
    return values


def _proposal(conn, selection):
    if not isinstance(selection,dict) or set(selection)!={'capture_id','photo_id','primary','version_id','location'}:
        raise ValueError('Expected an incoming metadata and location choice')
    if selection['primary'] not in ('keep_current','use_incoming') or selection['location'] not in ('keep','library'):
        raise ValueError('Invalid metadata or location choice')
    file_id,root,report,versions=_versions(conn,selection['capture_id'])
    target=_target(conn,selection['photo_id'])
    digest=conn.execute('SELECT catalog_sha1 FROM metadata_captures WHERE capture_id=?',(selection['capture_id'],)).fetchone()[0]
    if digest!=target['sha1']:
        raise ValueError('Incoming metadata belongs to different photo content')
    version_id=selection['version_id']
    if selection['primary']=='keep_current':
        if version_id is not None:
            raise ValueError('Keeping current metadata does not select a new primary version')
    elif type(version_id) is not int or version_id not in {v['version_id'] for v in versions}:
        raise ValueError('Choose a retained version from this incoming photo')
    known={v['version_id'] for decision in alternatives(conn,target['file_id']) for v in decision['versions']}
    # A later edit/primary switch must not hide previously imported alternatives.
    for raw, in conn.execute("SELECT e.detail_json FROM operation_events e JOIN operation_files f ON f.operation_id=e.operation_id "
            "WHERE f.file_id=? AND e.step='pair_complete'",(target['file_id'],)):
        receipt=json.loads(raw)
        known.add(receipt['version_id'])
        known.update(v['version_id'] for v in receipt.get('versions',[]))
    novel=[v['version_id'] for v in versions if v['version_id'] not in known]
    current_primary = (target['primary'] or {}).get('value',{}).get('primary_id','')
    changes_primary=selection['primary']=='use_incoming' and (
        not target['pair'] or target['pair']['version_id']!=version_id
        or not current_primary.startswith('sidecar:'))
    returns=selection['location']=='library' and target['status'].startswith('Rejected')
    value={'incoming_file_id':file_id,'source_root':root,'capture_id':selection['capture_id'],
        'retained_file_id':target['file_id'],'photo_id':target['photo_id'],'versions':versions,
        'target_binding':{key:target[key] for key in ('sha1','path','status','photo_revision','file_revision','primary')},
        'primary':selection['primary'],'version_id':version_id,'location':selection['location'],
        'needs_review':bool(novel and target['pair'] and selection['primary']=='keep_current'),
        'activation_required':changes_primary or returns,'applied':False}
    result={'selection':selection,'target':target,'after':value,'known_version_ids':sorted(known),
        'novel_version_ids':sorted(set(novel)),
        'confirmation_required':bool((novel and not target['pair']) or changes_primary or returns)}
    result['token']=hashlib.sha256(_json(result).encode()).hexdigest()
    return result


def preview(db_path, *, capture_id, photo_id, primary='keep_current', version_id=None, location='keep'):
    """Offer metadata and location together; never return Rejects implicitly."""
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        ns_db.require_schema(conn);conn.execute('BEGIN')
        return _proposal(conn,dict(capture_id=capture_id,photo_id=photo_id,primary=primary,
            version_id=version_id,location=location))


def _record(conn, proposal, request_id, payload):
    # Read back every original BEFORE the FULL commit that records preservation.
    # The source cleanup path must repeat this proof when it uses the decision.
    for version in proposal['after']['versions']:
        if hashlib.sha256(xmp_store.original_bytes(conn,version['version_id'])).hexdigest()!=version['sha256']:
            raise ValueError('The retained incoming XMP original is not verified')
    value=proposal['after']
    decision=conn.execute('INSERT INTO metadata_decisions(kind,scope,capture_id,request_id,request_json,value_json,created_at) '
        "VALUES('incoming',?,?,?,?,?,?)",(str(value['retained_file_id']),value['capture_id'],request_id,
        payload,_json(value),ns_db.utc_now())).lastrowid
    return {'revision':decision,'value':value}


def confirm(db_path, *, selection, token, request_id):
    """Save a deliberate, version-bound decision, not an unverified file action."""
    if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',request_id):
        raise ValueError('Invalid metadata request ID')
    if not isinstance(token,str) or not re.fullmatch(r'[0-9a-f]{64}',token):
        raise ValueError('Invalid preview token')
    payload=_json({'selection':selection,'token':token})
    with contextlib.closing(ns_db.connect(db_path,synchronous='FULL')) as conn:
        ns_db.require_schema(conn)
        with ns_db.transaction(conn):
            previous=conn.execute('SELECT decision_id,request_json,value_json FROM metadata_decisions WHERE request_id=?',
                                  (request_id,)).fetchone()
            if previous:
                if previous[1]!=payload:
                    raise ns_db.RequestConflict('The request ID belongs to another metadata decision')
                return {'revision':previous[0],'value':json.loads(previous[2])}
            if conn.execute("SELECT 1 FROM runs WHERE status IN ('Preparing','Running','Cancelling') LIMIT 1").fetchone():
                raise ns_db.RevisionConflict('Finish or recover the active job before deciding')
            proposal=_proposal(conn,selection)
            if proposal['token']!=token:
                raise ns_db.RevisionConflict('The photo or metadata changed; preview the choice again')
            return _record(conn,proposal,request_id,payload)


def preserve(conn, *, capture_id, photo_id, run_id):
    """At a job boundary: retain alternatives, or require a deliberate choice.

    Returns a bound record for later verification, never permission to unlink. A
    settings snapshot limits which explicit decisions this job may use.
    """
    if conn.in_transaction or conn.execute('PRAGMA synchronous').fetchone()[0]!=2:
        raise RuntimeError('Incoming preservation needs an idle FULL connection and engine lock')
    settings=conn.execute('SELECT effective_config_json FROM run_configs WHERE run_id=?',(run_id,)).fetchone()
    if settings is None:
        raise ValueError('Missing job settings snapshot')
    highwater=json.loads(settings[0]).get('metadata_decision_highwater',0)
    proposal=_proposal(conn,dict(capture_id=capture_id,photo_id=photo_id,primary='keep_current',version_id=None,location='keep'))
    with ns_db.transaction(conn):
        previous=conn.execute("SELECT decision_id,value_json FROM metadata_decisions WHERE kind='incoming' "
            'AND scope=? AND capture_id=? AND decision_id<=? ORDER BY decision_id DESC LIMIT 1',
            (str(proposal['target']['file_id']),capture_id,highwater)).fetchone()
        if previous:
            value=metadata_incoming_apply.applied_value(conn, previous[0], json.loads(previous[1]))
            if value.get('target_binding')!=proposal['after']['target_binding']:
                raise ns_db.RevisionConflict('The retained photo changed after this choice; preview it again')
            if value['activation_required']:
                raise ValueError('Apply the confirmed primary/location choice before consuming this incoming pair')
            for version in value['versions']:xmp_store.original_bytes(conn,version['version_id'])
            return {'revision':previous[0],'value':value}
        if proposal['confirmation_required']:
            raise ValueError('Incoming XMP needs a metadata choice. Keep the current primary or explicitly select the incoming version; the source pair remains untouched.')
        request_id=f"incoming:{run_id}:{capture_id}:{photo_id}"
        existing=conn.execute('SELECT decision_id,value_json FROM metadata_decisions WHERE request_id=?',(request_id,)).fetchone()
        if existing:
            return {'revision':existing[0],'value':json.loads(existing[1])}
        return _record(conn,proposal,request_id,_json({'run_id':run_id,'token':proposal['token']}))


KIND = 'metadata_incoming_transfer'


def _manifest(conn, operation_id):
    row=conn.execute("SELECT o.status,e.detail_json FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.id=? AND e.step='intent'",(operation_id,)).fetchone()
    if not row or json.loads(row[1]).get('kind')!=KIND:
        raise ValueError('Unknown incoming metadata operation')
    return row[0],json.loads(row[1])['expected']


def _proof(conn, operation_id):
    return conn.execute("SELECT 1 FROM operation_evidence WHERE operation_id=? "
        "AND json_extract(details_json,'$.incoming_verified')=1",(operation_id,)).fetchone() is not None


def _verify_retained(conn, m):
    target=metadata_transfer._path(m['dest_root'],m['destination'])
    row=conn.execute('SELECT current_path,sha1_hash,presence_state FROM file_states WHERE file_id=?',
                     (m['retained_file_id'],)).fetchone()
    if not row or tuple(row)!=(str(target),m['sha1'],'present'):
        raise ValueError('The retained photo identity changed; resolve the incoming operation first')
    if not metadata_transfer._photo_matches(target,m['sha1']):
        raise ValueError('The retained photo is missing')
    durable._fsync_file(target);durable._fsync_directory(target.parent)
    side=Path(str(target)+'.xmp')
    if m['active_pair']:
        metadata_transfer._path(m['dest_root'],str(side))
        if not metadata_transfer._sidecar_matches(side,m['active_pair']['xmp_sha256']):
            raise ValueError('The retained primary sidecar is missing')
        durable._fsync_file(side);durable._fsync_directory(side.parent)
    elif os.path.lexists(side):
        raise ValueError('The retained photo has an unrecorded sidecar; resolve its ownership first')
    for version in m['versions']:
        data=xmp_store.original_bytes(conn,version['version_id'])
        if hashlib.sha256(data).hexdigest()!=version['sha256']:
            raise ValueError('Incoming metadata archival verification failed')


def _shared(conn, m, version):
    """Unknown/shared owners keep the source sidecar; absence alone is no proof."""
    for relative,identity in version['owners'].items():
        source=metadata_transfer._path(m['source_root'],str(Path(m['source_root'])/relative))
        if os.path.lexists(source):
            return True
        if identity==m['incoming_file_id']:
            continue
        receipts=conn.execute("SELECT e.detail_json,o.id FROM operations o JOIN operation_events e ON e.operation_id=o.id "
            "JOIN operation_files f ON f.operation_id=o.id WHERE f.file_id=? AND f.role='source' "
            "AND e.step IN ('pair_complete','incoming_complete','source_cleanup_complete') ORDER BY e.event_id DESC",(identity,)).fetchall()
        verified=False
        for raw,op in receipts:
            prior=json.loads(raw)
            versions=prior.get('versions',[{'version_id':prior.get('version_id')}])
            if version['version_id'] not in {v['version_id'] for v in versions}:
                continue
            paths=conn.execute("SELECT s.current_path,s.sha1_hash FROM operation_files f JOIN file_states s ON s.file_id=f.file_id "
                "WHERE f.operation_id=? AND f.role IN ('destination','retained_copy') AND s.location_role='destination' "
                "AND s.presence_state='present'",(op,)).fetchall()
            if any(metadata_transfer._photo_matches(metadata_transfer._path(m['dest_root'],path),digest) for path,digest in paths):
                verified=True;break
        if not verified:return True
    return False


def _finish(conn,op,m,*,complete,error=None,recovery_run_id=None):
    if complete:
        if m.get('same_photo'):
            status=('Rejected' if m['status_before'].startswith('Rejected') else 'Completed') if m['move'] else m['status_before']
        else:
            status='Removed_Duplicate' if m['move'] else 'Duplicate'
    else:
        status=m['status_before']
    operation_status=('Skipped' if not m['move'] else status) if complete else 'Failed'
    if complete and not m['move']:
        error='Duplicate photo already organized; incoming XMP originals preserved in lineage. Source files were kept.'
    with ns_db.transaction(conn):
        if complete:
            ns_db.record_delivery(conn,operation_id=op,photo_id=m['photo_id'],run_id=m['run_id'],
                destination=m['destination'],source_removed=m['move'],created=False,sha1_hash=m['sha1'])
        conn.execute('UPDATE photos SET status=?,dest_path=? WHERE id=?',(status,m['destination'],m['photo_id']))
        if complete:
            conn.execute('UPDATE photos SET sha1_hash=? WHERE id=?',(m['sha1'],m['photo_id']))
        event=ns_db.settle_operation(conn,op,status=operation_status,
            step='incoming_complete' if complete else 'incoming_incomplete',outcome='preserved' if complete else 'needs_attention',
            error_message=error,detail=m)
        if complete:
            if m.get('same_photo'):
                # This verified source receipt advances the anchor's own revision.
                # Preserve its new binding without treating unrelated later edits as safe.
                target = _target(conn, m['photo_id'])
                ns_db.record_event(conn, operation_id=op, step='incoming_binding_verified', outcome='verified',
                    detail={'decision_id':m['decision_id'], 'target_binding':metadata_incoming_apply._binding(target)})
            for issue, in conn.execute("SELECT a.issue_id FROM attention_issues a JOIN operations o ON o.id=a.operation_id "
                "WHERE o.photo_id=? AND a.category='metadata_incoming_incomplete' AND a.resolved_at IS NULL",(m['photo_id'],)).fetchall():
                ns_db.resolve_attention_issue(conn,issue,event_id=event)
        else:
            ns_db.open_attention_issue(conn,operation_id=op,category='metadata_incoming_incomplete',
                summary=error,file_id=m['incoming_file_id'])
        if recovery_run_id is not None:
            check=ns_db.begin_operation(conn,run_id=recovery_run_id,photo_id=m['photo_id'],source_path=m['source'],
                dest_path=m['destination'],kind='incoming_metadata_recovery',expected={'operation_id':op},reconciles=op)
            ns_db.settle_operation(conn,check,status=operation_status,step='recovery',outcome='recorded',error_message=error)
    return {'status':operation_status,'complete':complete,'error':error}


def execute(conn, operation_id, *, recover=False, recovery_run_id=None):
    """Consume duplicate sources only after exact photo and archived-XMP verification.

    Recovery observes and records. Only an explicit new Copy/Move may resume cleanup.
    The caller holds the engine lock. No active metadata or survivor location changes.
    """
    metadata_transfer._idle_full(conn)
    status,m=_manifest(conn,operation_id)
    if status!='Processing':
        raise ValueError('Incoming operation is already settled')
    try:
        _verify_retained(conn,m)
        source=metadata_transfer._path(m['source_root'],m['source'])
        if source.exists():
            if list(durable._file_identity(source))!=m['source_identity'] or not metadata_transfer._photo_matches(source,m['sha1']):
                raise ValueError('The incoming photo changed')
        elif not m['move'] or not _proof(conn,operation_id):
            raise ValueError('The source is absent without verified incoming preservation evidence')
        for version in m['versions']:
            path=metadata_transfer._path(m['source_root'],str(Path(m['source_root'])/version['path']))
            if path.exists():
                if list(durable._file_identity(path))!=version['identity'] or metadata_transfer._xmp_digest(path)!=version['sha256']:
                    raise ValueError('The incoming sidecar changed')
            elif not m['move'] or not _proof(conn,operation_id):
                raise ValueError('The incoming sidecar is absent without preservation evidence')
        with ns_db.transaction(conn):
            ns_db.record_evidence(conn,operation_id=operation_id,location_role='destination',observed_path=m['destination'],
                observation_kind='sha1',result='match',details={'incoming_verified':True,'decision_id':m['decision_id']})
        if m['move']:
            if recover:
                if source.exists() or any(os.path.lexists(Path(m['source_root'])/v['path']) and not _shared(conn,m,v) for v in m['versions']):
                    raise ValueError('Preservation is verified; repeat Move to finish source cleanup')
            else:
                if source.exists():
                    durable._remove_verified_source(source,Path(m['destination']),tuple(m['source_identity']),'Remove verified duplicate photo')
                durable._fsync_directory(source.parent)
                for version in m['versions']:
                    path=metadata_transfer._path(m['source_root'],str(Path(m['source_root'])/version['path']))
                    if _shared(conn,m,version):continue
                    # Recheck exact retained bytes and the live source immediately
                    # before retiring its name; a parsed snapshot is not a backup.
                    xmp_store.original_bytes(conn,version['version_id'])
                    if path.exists():
                        if list(durable._file_identity(path))!=version['identity'] or metadata_transfer._xmp_digest(path)!=version['sha256']:
                            raise ValueError('Source XMP changed before cleanup')
                        path.unlink()
                    durable._fsync_directory(path.parent)
            durable._fsync_directory(source.parent)
        return _finish(conn,operation_id,m,complete=True,recovery_run_id=recovery_run_id)
    except Exception as exc:
        return _finish(conn,operation_id,m,complete=False,error=f'Incoming metadata transfer incomplete: {exc}',recovery_run_id=recovery_run_id)


def transfer(conn, *, photo_id, run_id, destination_root, move):
    """Normal-job bridge. None means this row has no incoming-XMP work."""
    metadata_transfer._idle_full(conn)
    row=conn.execute('SELECT p.source_path,p.sha1_hash,p.status,pf.file_id,(SELECT MAX(capture_id) FROM metadata_captures WHERE file_id=pf.file_id) '
        'FROM photos p JOIN photo_files pf ON pf.photo_id=p.id WHERE p.id=?',(photo_id,)).fetchone()
    if not row or not row[4]:return None
    previous=conn.execute("SELECT o.id,o.status,e.detail_json FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.photo_id=? AND e.step='intent' AND json_extract(e.detail_json,'$.kind')=? ORDER BY o.id DESC LIMIT 1",(photo_id,KIND)).fetchone()
    if not previous or previous[1]!='Failed':
        report=json.loads(conn.execute('SELECT report_json FROM metadata_captures WHERE capture_id=?',(row[4],)).fetchone()[0])
        if not any(s['state']!='ignored' for s in report['sidecars']):return None
    run=conn.execute('SELECT source_path,dest_path,mode FROM runs WHERE id=?',(run_id,)).fetchone()
    if not run or not run[0] or not run[1]:
        raise ValueError('Incoming metadata requires recorded source and destination roots')
    if Path(run[0]).is_relative_to(Path(run[1])) or Path(run[1]).is_relative_to(Path(run[0])):
        raise ValueError('Source and destination folders must not overlap')
    if tuple(run[1:])!=(str(destination_root),'MOVE' if move else 'COPY'):
        raise ValueError('Incoming job roots or mode disagree')
    if previous and previous[1]=='Failed':
        m=json.loads(previous[2])['expected']
        if row[3]!=m['incoming_file_id'] or row[1] not in (None,'',m['sha1']):
            raise ValueError('The incoming photo binding changed; review the recorded operation')
        if (row[0],run[0],run[1],move)!=(m['source'],m['source_root'],m['dest_root'],m['move']):
            raise ValueError('Retry the incoming operation with its recorded roots and mode')
        m['run_id']=run_id
        prior=previous[0]
    else:
        anchors=conn.execute("SELECT id FROM photos WHERE sha1_hash=? AND status IN ('Copied','Completed','Found_At_Destination','Rejected','Rejected_Copied') "
            'AND dest_path IS NOT NULL ORDER BY id',(row[1],)).fetchall()
        other_anchors=[pid for pid, in anchors if pid!=photo_id]
        own_choice=conn.execute("SELECT 1 FROM metadata_decisions WHERE kind='incoming' AND capture_id=? "
            "AND json_extract(value_json,'$.photo_id')=? LIMIT 1",(row[4],photo_id)).fetchone()
        anchors=other_anchors or ([photo_id] if own_choice and any(pid==photo_id for pid, in anchors) else [])
        if not anchors:return None
        target=_target(conn,anchors[0])
        metadata_transfer._path(str(destination_root),target['path'])
        if conn.execute("SELECT 1 FROM operations o JOIN operation_events e ON e.operation_id=o.id "
                "WHERE o.photo_id=? AND e.step='intent' AND json_extract(e.detail_json,'$.kind')='metadata_edit' "
                "AND NOT EXISTS(SELECT 1 FROM operation_events f WHERE f.operation_id=o.id AND f.step='metadata_edit_finished')",
                (target['photo_id'],)).fetchone():
            raise ValueError('Finish the recorded metadata operation before consuming this incoming pair')
        decision=preserve(conn,capture_id=row[4],photo_id=target['photo_id'],run_id=run_id)
        versions=decision['value']['versions']
        for v in versions:
            path=metadata_transfer._path(run[0],str(Path(run[0])/v['path']))
            v['identity']=list(durable._file_identity(path))
        m={'same_photo':photo_id==target['photo_id'],'photo_id':photo_id,'incoming_file_id':row[3],'run_id':run_id,'source':row[0],
            'destination':target['path'],'retained_file_id':target['file_id'],'sha1':row[1],
            'source_root':run[0],'dest_root':run[1],'move':move,'status_before':row[2],
            'source_identity':list(durable._file_identity(row[0])),
            'versions':versions,'active_pair':target['pair'],'decision_id':decision['revision']}
        prior=None
    blocking=conn.execute("SELECT 1 FROM attention_issues a JOIN operations o ON o.id=a.operation_id WHERE a.resolved_at IS NULL "
        "AND o.dest_path=? AND (a.category<>'metadata_incoming_incomplete' OR o.photo_id<>?) LIMIT 1",(m['destination'],photo_id)).fetchone()
    if blocking:raise ValueError('The retained photo has an unresolved file issue')
    with ns_db.transaction(conn):
        op=ns_db.begin_operation(conn,run_id=run_id,photo_id=photo_id,source_path=m['source'],dest_path=m['destination'],
            kind=KIND,expected=m,reconciles=prior)
        conn.execute("UPDATE photos SET status='Processing',dest_path=? WHERE id=?",(m['destination'],photo_id))
        if prior and _proof(conn,prior):
            # This is only previous evidence; execute re-verifies all retained bytes.
            ns_db.record_evidence(conn,operation_id=op,location_role='destination',observed_path=m['destination'],
                observation_kind='sha1',result='match',details={'incoming_verified':True,'retry_of':prior})
    return execute(conn,op)
