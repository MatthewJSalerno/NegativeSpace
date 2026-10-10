"""Photo-only and resolved photo/XMP imports: filing plans and verified activation receipts.

Normal jobs use this boundary for embedded read priority and resolved first imports;
incoming alternatives use metadata_incoming. Every associated sidecar is retained;
no activation precedes verification.
"""
import contextlib
import hashlib
from datetime import datetime
import json
import os
from pathlib import Path

from engine import constants, metadata_capture, metadata_decisions, metadata_edits, metadata_save, ns_db


def plan(conn, photo_id, run_id):
    """Read-only plan from captured evidence and the job's frozen decisions."""
    row = conn.execute('SELECT p.source_path,p.dest_path,p.sha1_hash,p.status,p.metadata_json,pf.file_id '
        'FROM photos p JOIN photo_files pf ON pf.photo_id=p.id WHERE p.id=?',(photo_id,)).fetchone()
    active = metadata_save.active(conn, photo_id)
    if active and active.get('content_changed'):
        raise ValueError(metadata_decisions.transfer_hold(conn, photo_id))
    if conn.execute("SELECT 1 FROM operations o JOIN operation_events e ON e.operation_id=o.id "
            "WHERE o.photo_id=? AND e.step='intent' AND json_extract(e.detail_json,'$.kind')=? "
            "AND NOT EXISTS(SELECT 1 FROM operation_events done WHERE done.operation_id=o.id "
            "AND done.step='metadata_edit_finished')", (photo_id,metadata_save.KIND)).fetchone():
        raise ValueError('Finish or discard the recorded metadata operation before Copy or Move; its source is preserved')
    capture = conn.execute('SELECT capture_id FROM metadata_captures WHERE file_id=? ORDER BY capture_id DESC LIMIT 1',
                           (row[5],)).fetchone() if row else None
    if not capture:
        return None
    file_id, relative, report, root = metadata_decisions._capture(conn,capture[0])
    sidecars = [s for s in report['sidecars'] if s['state']!='ignored'
                and (s['state']!='associated' or relative in s['candidates'])]
    if not sidecars:
        return photo_plan(conn, photo_id, run_id, row, capture[0], report)
    config_row = conn.execute('SELECT effective_config_json FROM run_configs WHERE run_id=?',(run_id,)).fetchone()
    if not config_row:
        raise ValueError('Photo/XMP import requires the job settings snapshot')
    config = json.loads(config_row[0])
    highwater = config.get('metadata_decision_highwater',0)
    primary = metadata_decisions.current(conn,'primary',str(file_id),highwater=highwater)
    blocking = [issue for issue in report['issues']
                if issue.get('source')!='sidecars' or issue.get('code')!='metadata_choice_needed']
    if blocking or any(side['state']!='associated' for side in sidecars):
        raise ValueError('Metadata choice or repair needed. The photo and sidecars remain at source; resolve the source metadata and reindex. Decision screens are not built yet.')
    if row[3] not in ('Pending','Copied'):
        raise ValueError('Incoming metadata for an existing or rejected photo needs a separate decision. The source pair remains untouched.')
    versions = []
    for side in sidecars:
        owners,_ = metadata_decisions._owners(conn,root,side,highwater=highwater)
        if owners.get(relative)!=file_id or sorted(owners)!=sorted(side['candidates']):
            raise ValueError('Resolve sidecar ownership before importing this photo')
        version = metadata_decisions._retained(conn,capture[0],side['path'],side['sha256'])
        versions.append(dict(path=side['path'],version_id=version,sha256=side['sha256'],owners=owners))
    selected = primary['value']['primary_id'] if primary else None
    if selected and selected.startswith('sidecar:'):
        side = next((side for side in sidecars if 'sidecar:'+side['path']==selected),None)
        if side is None:
            raise ValueError('The saved primary sidecar is not among the associated sidecars')
    else:
        candidates = [side for side in sidecars if Path(side['path']).stem==Path(relative).name] or sidecars
        if len({side['sha256'] for side in candidates})!=1:
            raise ValueError('Several sidecar versions need a primary choice; all originals remain at source')
        side = min(candidates,key=lambda item:item['path'])
    chosen_version = next(item for item in versions if item['path']==side['path'])
    owners,version = chosen_version['owners'],chosen_version['version_id']
    sources = report['sources']
    if primary:
        previous = conn.execute('SELECT catalog_sha1,report_json FROM metadata_captures WHERE capture_id=?',
                                (primary['capture_id'],)).fetchone()
        if previous[0]!=row[2]:
            raise ValueError('The saved primary belongs to different photo content; resolve the metadata choice first')
        earlier = json.loads(previous[1])
        selected = primary['value']['primary_id']
        if earlier['sources'].get(selected)!=sources.get(selected):
            raise ValueError('The selected primary has changed. Its earlier version is preserved; choose metadata before importing.')
        if selected.startswith('sidecar:') and selected!='sidecar:'+side['path']:
            raise ValueError('The saved primary sidecar is not the incoming sidecar')
        resolution = metadata_capture.resolve(sources,list(sources),primary_id=selected)
    else:
        selected = 'sidecar:'+side['path']
        resolution = metadata_capture.resolve(sources,[selected]+[key for key in ('embedded_xmp','exif') if key in sources])
    # No duplicate import may overwrite the survivor's metadata or return a reject.
    delivered = constants.sql_values(constants.ANCHOR_DELIVERED_STATUSES + ns_db.REJECTED_STATUSES)
    if conn.execute(f'SELECT 1 FROM photos WHERE sha1_hash=? AND id<>? AND status IN ({delivered}) LIMIT 1',
                    (row[2],photo_id)).fetchone():
        raise ValueError('This content is already organized. Incoming XMP is preserved at source until its metadata choice is implemented.')
    original = conn.execute('SELECT file_mtime FROM source_snapshots WHERE file_id=?',(file_id,)).fetchone()
    if not original or original[0] is None:
        raise ValueError('The original file date is unavailable; cannot safely plan Undated filing')
    original_date = datetime.fromtimestamp(original[0])
    fields = resolution['proposed_effective']
    folder = metadata_edits._folder(fields,original_date.year)
    dest_root = conn.execute('SELECT dest_path FROM runs WHERE id=?',(run_id,)).fetchone()[0]
    destination = Path(dest_root)/folder/Path(row[0]).name
    # Copy -> Move and reimports keep the actual delivered name, including Rename.
    receipt = conn.execute("SELECT e.detail_json,f.current_path FROM operation_events e "
        "JOIN operations o ON o.id=e.operation_id JOIN operation_files of ON of.operation_id=o.id "
        "JOIN file_states f ON f.file_id=of.file_id WHERE o.photo_id=? AND e.step='pair_complete' "
        "AND of.role='destination' AND f.location_role='destination' AND f.presence_state='present' "
        "ORDER BY e.event_id DESC LIMIT 1",(photo_id,)).fetchone()
    if receipt:
        old = json.loads(receipt[0])
        imported=conn.execute("SELECT e.detail_json FROM operations o JOIN operation_events e ON e.operation_id=o.id "
            "WHERE o.photo_id=? AND e.step='metadata_activated' ORDER BY e.event_id DESC LIMIT 1",(photo_id,)).fetchone()
        if imported:
            prior=json.loads(imported[0])
            prior_versions=prior.get('versions',[dict(path=prior['sidecar'],sha256=prior['sha256'])])
            if {(v['path'],v['sha256']) for v in versions}!={(v['path'],v['sha256']) for v in prior_versions}:
                raise ValueError('New or changed sidecar versions beside an organized source need incoming metadata review; existing files remain unchanged')
        if old.get('activation') and old['activation']['primary_id'] != selected:
            raise ValueError('Apply the confirmed primary switch through the metadata operation before importing again. The existing pair stays unchanged.')
        if old['xmp_sha256']!=side['sha256'] or not Path(receipt[1]).is_relative_to(Path(dest_root)/'library'):
            raise ValueError('The delivered pair has different metadata or is outside Library. Preserve it and resolve the incoming choice.')
        destination = Path(receipt[1])
    elif row[3]=='Copied':
        raise ValueError('The existing photo has no recorded XMP pair. Its metadata choice must be resolved before importing a sidecar.')
    metadata = json.loads(row[4] or '{}')
    if 'Undated' in folder.parts:
        metadata['date_taken'] = original_date.isoformat()
        metadata['date_source'] = constants.DATE_SOURCE_MTIME
    else:
        metadata['date_taken'] = fields['date_taken']
        metadata['date_source'] = 'exif' if resolution['field_sources'].get('date_taken')=='exif' else 'xmp'
    return {'capture_id':capture[0],'file_id':file_id,'primary_id':selected,
            'resolution':resolution,'metadata':metadata,'destination':str(destination),
            'sidecar':side['path'],'version_id':version,'sha256':side['sha256'],
            'owners':owners,'versions':versions,'source_root':root,'primary_revision':primary['revision'] if primary else 0}


def activate(conn, operation_id, photo_id, activation):
    """Within verified completion's FULL transaction; never modifies a source file."""
    conn.execute('UPDATE photos SET metadata_json=? WHERE id=?',
                 (json.dumps(activation['metadata'],ensure_ascii=False),photo_id))
    ns_db.record_event(conn,operation_id=operation_id,step='metadata_activated',outcome='completed',detail=activation)
    # Establish the initial source and ownership once. Settings changes and reindex
    # never silently replace them. Explicit choices remain their own immutable rows.
    primary_value = {'file_id':activation['file_id'],'primary_id':activation['primary_id'],
        'capture_id':activation['capture_id'],'resolution':activation['resolution'],
        'filing_applied':True,'established_by_operation':operation_id}
    choices = [('primary',str(activation['file_id']),primary_value)]
    versions = activation.get('versions',[dict(path=activation['sidecar'],owners=activation['owners'],
        version_id=activation['version_id'],sha256=activation['sha256'])])
    for version in versions:
        owner_value = dict(owners=version['owners'],sidecar=version['path'],root=activation['source_root'],
            version_id=version['version_id'],sha256=version['sha256'])
        choices.append(('association',metadata_decisions.association_scope(activation['source_root'],version['path']),owner_value))
    for kind,scope,value in choices:
        if metadata_decisions.current(conn,kind,scope) is None:
            conn.execute('INSERT INTO metadata_decisions(kind,scope,capture_id,request_id,request_json,value_json,created_at) '
                'VALUES(?,?,?,?,?,?,?)',(kind,scope,activation['capture_id'],f'import:{operation_id}:{kind}:{hashlib.sha256(scope.encode()).hexdigest()}',
                json.dumps({'operation_id':operation_id}),json.dumps(value,ensure_ascii=False),ns_db.utc_now()))


def retry_operation(conn, photo_id, run_id):
    """Only a matching explicit Copy/Move job can resume its recorded incomplete pair."""
    row = conn.execute("SELECT o.id,o.status,e.detail_json FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.photo_id=? AND e.step='intent' AND json_extract(e.detail_json,'$.kind')='metadata_pair_transfer' "
        "ORDER BY o.id DESC LIMIT 1",(photo_id,)).fetchone()
    if not row or row[1]!='Failed':
        return None
    m = json.loads(row[2])['expected']
    current = conn.execute('SELECT source_path,sha1_hash,status FROM photos WHERE id=?',(photo_id,)).fetchone()
    run = conn.execute('SELECT source_path,dest_path,mode FROM runs WHERE id=?',(run_id,)).fetchone()
    if current[2] not in ('Pending','Failed'):
        raise ValueError('This photo changed state after the incomplete pair; review its recorded operation before retrying')
    if tuple(current[:2])!=(m['photo_source'],m['sha1_hash']) or tuple(run)!=(m['source_root'],m['destination_root'],'MOVE' if m['move'] else 'COPY'):
        raise ValueError('The incomplete photo/XMP pair must be retried with its recorded source, destination and Copy/Move mode.')
    return row[0],m


def restore_delivered(conn, photo_id):
    """Reindex observes source metadata; it never replaces an established import.

    A force scan can project the legacy source filename/date again. Restore only a
    same-content recorded pair's current destination identity, never infer delivery
    from a source or from an unverified file found on disk. No external rescan here.
    """
    edited = metadata_save.active(conn, photo_id)
    if edited and (edited.get('content_changed') or conn.execute('SELECT sha1_hash FROM photos WHERE id=?', (photo_id,)).fetchone()[0] == edited['sha1_hash']):
        retained = conn.execute('SELECT current_path,presence_state,sha1_hash FROM file_states WHERE file_id=?',
                                (edited['retained_id'],)).fetchone()
        if retained and retained[1] == 'present' and retained[2] == edited['sha1_hash']:
            current = conn.execute('SELECT status FROM photos WHERE id=?', (photo_id,)).fetchone()[0]
            status = ('Rejected_Copied' if Path(retained[0]).is_relative_to(Path(edited['destination_root'])/'rejects')
                      else 'Copied') if current in ('Pending','Copied','Rejected_Copied') or (edited.get('content_changed') and current=='Duplicate') else current
            with contextlib.nullcontext() if conn.in_transaction else ns_db.transaction(conn):
                conn.execute('UPDATE photos SET metadata_json=?,dest_path=?,status=? WHERE id=?',
                    (json.dumps(edited['metadata']), retained[0], status, photo_id))
                if edited.get('content_changed'):
                    conn.execute('UPDATE photos SET sha1_hash=?,file_size=?,file_mtime=?,phash=? WHERE id=?',
                        (edited['sha1_hash'],edited['file_size'],edited['file_mtime'],edited['phash'],photo_id))
        return
    photo = conn.execute('SELECT sha1_hash,status FROM photos WHERE id=?',(photo_id,)).fetchone()
    if not photo or photo[1] not in ('Pending','Copied','Rejected_Copied'):
        return
    row = conn.execute("SELECT e.detail_json,f.current_path FROM operation_events e "
        "JOIN operations o ON o.id=e.operation_id JOIN operation_files of ON of.operation_id=o.id "
        "JOIN file_states f ON f.file_id=of.file_id WHERE o.photo_id=? AND e.step='pair_complete' "
        "AND of.role='destination' AND f.location_role='destination' AND f.presence_state='present' "
        "ORDER BY e.event_id DESC LIMIT 1",(photo_id,)).fetchone()
    if not row:
        imported=photo_receipt(conn,photo_id)
        if imported and imported[0]['sha1_hash']==photo[0]:
            receipt,path=imported
            role='rejects' if Path(path).is_relative_to(Path(receipt['destination_root'])/'rejects') else 'library'
            with contextlib.nullcontext() if conn.in_transaction else ns_db.transaction(conn):
                conn.execute('UPDATE photos SET metadata_json=?,dest_path=?,status=? WHERE id=?',
                    (json.dumps(receipt['metadata']),path,'Rejected_Copied' if role=='rejects' else photo[1],photo_id))
        return
    receipt = json.loads(row[0])
    activation = receipt.get('activation')
    if not activation or receipt['sha1_hash']!=photo[0]:
        return
    path = Path(row[1]); root = Path(receipt['destination_root'])
    if path.is_relative_to(root/'library'):
        status = 'Copied'
    elif path.is_relative_to(root/'rejects'):
        status = 'Rejected_Copied'
    else:
        return
    with contextlib.nullcontext() if conn.in_transaction else ns_db.transaction(conn):
        conn.execute('UPDATE photos SET metadata_json=?,dest_path=?,status=? WHERE id=?',
            (json.dumps(activation['metadata'],ensure_ascii=False),str(path),status,photo_id))


def photo_plan(conn, photo_id, run_id, row, capture_id, report):
    """Frozen read precedence for a first photo-only import; no bytes or primary change."""
    if row[3] not in ('Pending','Copied') or Path(row[0]).suffix.lower() not in ns_db.SUPPORTED_EXTENSIONS:
        return None
    if report['issues']:
        for issue in report['issues']:
            if issue.get('code')=='read_error' and isinstance(issue.get('errno'),int):
                raise OSError(issue['errno'],os.strerror(issue['errno']))
        raise ValueError('Embedded metadata needs attention before its priority can be applied; preserve the source and reindex after correction')
    frozen=conn.execute('SELECT effective_config_json FROM run_configs WHERE run_id=?',(run_id,)).fetchone()
    if not frozen:
        raise ValueError('Metadata priority requires the job settings snapshot')
    config=json.loads(frozen[0])
    primary=metadata_decisions.current(conn,'primary',str(row[5]),highwater=config.get('metadata_decision_highwater',0))
    chosen=primary['value']['primary_id'] if primary else None
    if chosen and chosen not in report['sources']:
        raise ValueError('The selected embedded source is unavailable; its primary was not changed')
    if primary:
        old=conn.execute('SELECT catalog_sha1,report_json FROM metadata_captures WHERE capture_id=?',(primary['capture_id'],)).fetchone()
        if old[0]!=row[2] or json.loads(old[1])['sources'].get(chosen)!=report['sources'].get(chosen):
            raise ValueError('The selected embedded source changed; review its primary before importing')
    root=conn.execute('SELECT dest_path FROM runs WHERE id=?',(run_id,)).fetchone()[0]
    recorded=photo_receipt(conn,photo_id)
    active=metadata_save.active(conn,photo_id)
    if row[3]=='Copied' and active and active['sha1_hash']==row[2] and active['primary_id']==chosen:
        retained=conn.execute("SELECT current_path FROM file_states WHERE file_id=? AND presence_state='present'",(active['retained_id'],)).fetchone()
        if not retained or not Path(retained[0]).is_relative_to(Path(root)/'library'):
            raise ValueError('Restore the recorded Library destination before Copy or Move')
        return dict(active,destination=retained[0],photo_only=True,capture_id=capture_id)
    if row[3]=='Copied' and not recorded:
        return None
    if recorded and recorded[0]['sha1_hash']==row[2]:
        # Keep verified names even when force Index resets transfer eligibility.
        previous,path=recorded
        if previous['primary_id']!=chosen:
            raise ValueError('Apply the confirmed primary switch before Copy or Move; the existing photo is unchanged')
        if Path(path).is_relative_to(Path(root)/'library'):
            return dict(previous,destination=path,photo_only=True)
        # A newly configured destination gets a new verified copy; do not follow
        # an old delivery receipt outside this job's destination root.
    order=[key for key in ('embedded_xmp','exif') if key in report['sources']]
    resolution=metadata_capture.resolve(report['sources'],order,primary_id=chosen)
    original=conn.execute('SELECT file_mtime FROM source_snapshots WHERE file_id=?',(row[5],)).fetchone()
    original_date=datetime.fromtimestamp(original[0])
    folder=metadata_edits._folder(resolution['proposed_effective'],original_date.year)
    metadata=json.loads(row[4] or '{}')
    date=resolution['proposed_effective'].get('date_taken','')
    metadata.update(date_taken=date if len(date)>=10 else original_date.isoformat(),
        date_source=('exif' if resolution['field_sources'].get('date_taken')=='exif' else 'xmp') if len(date)>=10 else constants.DATE_SOURCE_MTIME)
    return dict(photo_only=True,capture_id=capture_id,file_id=row[5],primary_id=chosen,
        resolution=resolution,sources=report['sources'],metadata=metadata,sha1_hash=row[2],
        destination_root=root,destination=str(Path(root)/folder/Path(row[0]).name),
        primary_revision=primary['revision'] if primary else 0)


def photo_receipt(conn, photo_id):
    row=conn.execute("SELECT e.detail_json,f.current_path FROM operation_events e "
        "JOIN operations o ON o.id=e.operation_id JOIN operation_files of ON of.operation_id=o.id "
        "JOIN file_states f ON f.file_id=of.file_id WHERE o.photo_id=? AND e.step='photo_metadata_activated' "
        "AND of.role IN ('destination','retained_copy') AND f.location_role='destination' "
        "AND f.presence_state='present' ORDER BY e.event_id DESC LIMIT 1",(photo_id,)).fetchone()
    return (json.loads(row[0]),row[1]) if row else None


def activate_photo(conn, operation_id, photo_id, activation, verified_sha1):
    """Called only with verified delivery, inside its FULL outcome transaction."""
    if verified_sha1!=activation['sha1_hash']:
        ns_db.open_attention_issue(conn,operation_id=operation_id,category='unestablished_outcome',
            summary='Photo bytes changed since the metadata capture. The delivered file is preserved; metadata priority was not activated.')
        return
    conn.execute('UPDATE photos SET metadata_json=? WHERE id=?',(json.dumps(activation['metadata']),photo_id))
    ns_db.record_event(conn,operation_id=operation_id,step='photo_metadata_activated',outcome='verified',detail=activation)
