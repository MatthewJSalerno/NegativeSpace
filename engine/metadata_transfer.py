"""Durable photo/XMP pair transfer, with optional normal-job metadata activation.

Callers must hold the engine lock and supply the resolved filing destination. The
normal job bridge activates resolved first imports and retains every alternative.
Unresolved versions and incoming activation stay held. Recovery observes; retry is explicit.
"""
import hashlib
import json
import os
from pathlib import Path

from engine import durable, fileinfo, metadata_decisions, metadata_import, ns_db, reconcile, xmp, xmp_store
from engine.ns_db import PhotoStatus

KIND = 'metadata_pair_transfer'


class PairRefused(ValueError):
    """The pair needs a decision or repair; never overwrite or infer ownership."""


def _idle_full(conn):
    if conn.in_transaction or conn.execute('PRAGMA synchronous').fetchone()[0] != 2:
        raise RuntimeError('Pair transfers require an idle FULL connection and the engine lock')


def _path(root, path):
    root, path = Path(root), Path(path)
    if not root.is_absolute() or not path.is_absolute() or '..' in path.parts or not path.is_relative_to(root):
        raise PairRefused('Transfer path is outside its configured root')
    fileinfo.require_plain_path(root)
    fileinfo.require_plain_path(path)
    return path


def _xmp_digest(path):
    captured = xmp.read_sidecar(path.parent, path.name, source_id='transfer')
    if captured.state != 'valid':
        raise PairRefused(f'XMP could not be verified: {captured.code}')
    return hashlib.sha256(captured.original_bytes).hexdigest()


def _photo_matches(path, digest):
    state = reconcile._recovery_observe(path)
    if state == 'absent':
        return False
    result, _ = reconcile._recovery_verify(path, digest)
    if result != 'match':
        raise PairRefused(f'Photo verification failed ({result})')
    return True


def _sidecar_matches(path, digest):
    if reconcile._recovery_observe(path) == 'absent':
        return False
    if _xmp_digest(path) != digest:
        raise PairRefused('Destination XMP differs; preserve both versions and resolve the metadata choice')
    return True


def resolve_destination(target, photo_sha1, xmp_sha256):
    """Suffix actual photo-name collisions; never silently bypass an orphan XMP."""
    target = Path(target)
    candidate, counter = target, 1
    while True:
        state = reconcile._recovery_observe(candidate)
        sidecar = Path(str(candidate)+'.xmp')
        if state == 'absent':
            if os.path.lexists(sidecar):
                raise PairRefused('Destination XMP exists but its photo is missing; resolve the destination pair before retrying')
            return candidate, False
        verification, _ = reconcile._recovery_verify(candidate,photo_sha1)
        if verification == 'match':
            _sidecar_matches(sidecar,xmp_sha256)
            return candidate, True
        if verification != 'mismatch':
            raise PairRefused(f'The destination photo could not be inspected ({verification})')
        candidate = target.parent / f'{target.stem}_{counter}{target.suffix}'
        counter += 1


def _binding(conn, pid, manifest):
    row = conn.execute('SELECT source_path,dest_path,sha1_hash FROM photos WHERE id=?',(pid,)).fetchone()
    if not row or tuple(row) != (manifest['photo_source'],manifest['photo_destination'],manifest['sha1_hash']):
        raise PairRefused('The catalog photo has changed since this transfer; review its history before retrying')


def _manifest(conn, operation_id):
    row = conn.execute("SELECT o.photo_id,o.status,e.detail_json FROM operations o JOIN operation_events e "
                       "ON e.operation_id=o.id WHERE o.id=? AND e.step='intent' ORDER BY e.event_id LIMIT 1",
                       (operation_id,)).fetchone()
    if row is None:
        raise PairRefused('Unknown transfer operation')
    detail = json.loads(row[2])
    if detail.get('kind') != KIND:
        raise PairRefused('Not a photo/XMP pair operation')
    return row[0], row[1], detail['expected']


def _begin(conn, *, run_id, photo_id, manifest, reconciles=None):
    with ns_db.transaction(conn):
        op = ns_db.begin_operation(conn, run_id=run_id, photo_id=photo_id,
            source_path=manifest['photo_source'], dest_path=manifest['photo_destination'],
            kind=KIND, expected=manifest, reconciles=reconciles)
        conn.execute('UPDATE operations SET sha1_hash=? WHERE id=?',(manifest['sha1_hash'],op))
        conn.execute('UPDATE photos SET status=?,dest_path=? WHERE id=?',
                     (PhotoStatus.PROCESSING, manifest['photo_destination'], photo_id))
    return op


def prepare(conn, *, run_id, photo_id, capture_id, destination, move=False, activate=False):
    """Bind a selected photo/XMP pair and retained alternatives before any file write.

    Normal jobs request activation, recomputed from captured evidence and frozen
    choices. Internal callers can transfer without it. Duplicate decisions stay held.
    """
    _idle_full(conn)
    activation = metadata_import.plan(conn,photo_id,run_id) if activate else None
    if activate and (not activation or activation['destination']!=destination or activation['capture_id']!=capture_id):
        raise PairRefused('The filing plan changed; recompute it before transfer')
    file_id, relative, report, root = metadata_decisions._capture(conn, capture_id)
    row = conn.execute('SELECT p.source_path,p.sha1_hash,p.status,pf.file_id FROM photos p '
                       'JOIN photo_files pf ON pf.photo_id=p.id WHERE p.id=?', (photo_id,)).fetchone()
    run = conn.execute('SELECT source_path,dest_path,mode FROM runs WHERE id=?', (run_id,)).fetchone()
    if not row or not run or row[3] != file_id or run[0] != root:
        raise PairRefused('Photo, capture and transfer run do not have the same source identity')
    if row[2] not in (PhotoStatus.PENDING, PhotoStatus.COPIED) or run[2] != ('MOVE' if move else 'COPY'):
        raise PairRefused('Expected an eligible photo and matching Copy/Move run')
    if report['issues'] and not activation:
        raise PairRefused('Resolve source metadata issues before transferring the pair')
    sidecars = [s for s in report['sidecars'] if s['state'] == 'associated' and relative in s['candidates']]
    if activation:
        sidecar = next(side for side in sidecars if side['path']==activation['sidecar'])
    else:
        if len(sidecars) != 1:
            raise PairRefused('Multiple-sidecar transfer requires a resolved activation plan')
        sidecar = sidecars[0]
    config = json.loads(conn.execute('SELECT effective_config_json FROM run_configs WHERE run_id=?',(run_id,)).fetchone()[0])
    highwater = config.get('metadata_decision_highwater',0)
    saved = metadata_decisions.current(conn,'association',
        metadata_decisions.association_scope(root,sidecar['path']),highwater=highwater)
    if saved and (saved['value']['owners'].get(relative) != file_id or
                  sorted(saved['value']['owners']) != sorted(sidecar['candidates'])):
        raise PairRefused('Ownership evidence differs from the job choice; refresh the capture first')
    primary = metadata_decisions.current(conn,'primary',str(file_id),highwater=highwater)
    if not activate and primary and (primary['value']['primary_id'] != 'sidecar:'+sidecar['path'] or
                    primary['capture_id'] != capture_id):
        raise PairRefused('The established primary needs activation handling before this pair can transfer')
    source = _path(root, row[0]); target = _path(run[1], destination)
    if target == Path(run[1]) or not target.is_relative_to(Path(run[1])/'library'):
        raise PairRefused('The initial pair transfer must target a Library photo')
    if Path(root).is_relative_to(Path(run[1])) or Path(run[1]).is_relative_to(Path(root)):
        raise PairRefused('Source and destination folders must not overlap')
    side_source = _path(root, str(Path(root)/xmp.relative_path(sidecar['path'])))
    side_target = _path(run[1], str(target)+'.xmp')
    version = metadata_decisions._retained(conn, capture_id, sidecar['path'], sidecar['sha256'])
    original = xmp_store.original_bytes(conn, version)
    if hashlib.sha256(original).hexdigest() != sidecar['sha256']:
        raise PairRefused('Retained XMP does not match the capture')
    source_identity = durable._file_identity(source)
    side_identity = durable._file_identity(side_source)
    if not _photo_matches(source,row[1]) or _xmp_digest(side_source) != sidecar['sha256']:
        raise PairRefused('The source pair does not match the recorded evidence; reindex before transferring')
    if source_identity != durable._file_identity(source) or side_identity != durable._file_identity(side_source):
        raise PairRefused('Source pair changed during verification')
    target, photo_exists = resolve_destination(target,row[1],sidecar['sha256'])
    side_target = _path(run[1],str(target)+'.xmp')
    if activate and photo_exists and not os.path.lexists(side_target):
        raise PairRefused('The destination already has this photo without XMP; its metadata choice must be resolved before adding a sidecar')
    if move and ns_db.paths_needing_attention(conn,[str(target)]):
        raise PairRefused('The destination photo has an unresolved file issue; verify it before source removal')
    for a,b in ((source,target),(side_source,side_target)):
        if b.exists() and os.path.samefile(a,b):
            raise PairRefused('Source and destination identify the same underlying file')
    owners = {}
    for relative_owner in sidecar['candidates']:
        owner = str(_path(root,str(Path(root)/xmp.relative_path(relative_owner))))
        binding = conn.execute('SELECT pf.file_id,p.sha1_hash FROM photos p JOIN photo_files pf ON pf.photo_id=p.id '
                               'WHERE p.source_path=? ORDER BY p.id DESC LIMIT 1',(owner,)).fetchone()
        owners[owner] = {'file_id':binding[0],'sha1_hash':binding[1]} if binding else None
    manifest = dict(photo_source=str(source),photo_destination=str(target),sidecar_source=str(side_source),
        sidecar_destination=str(side_target),source_root=root,destination_root=run[1],
        sha1_hash=row[1],xmp_sha256=sidecar['sha256'],version_id=version,capture_id=capture_id,
        owners=owners,source_identity=source_identity,sidecar_identity=side_identity,move=bool(move),
        created=not photo_exists,file_id=file_id)
    if activation:
        manifest['activation'] = activation
        manifest['versions'] = _freeze_versions(conn,manifest,activation['versions'])
    return _begin(conn,run_id=run_id,photo_id=photo_id,manifest=manifest)


def _freeze_versions(conn, manifest, versions):
    """Bind every original and owner before intent; no unverified archive authorizes cleanup."""
    result=[]
    for version in versions:
        path=_path(manifest['source_root'],str(Path(manifest['source_root'])/xmp.relative_path(version['path'])))
        identity=durable._file_identity(path)
        _verify_blob(conn,version)
        if _xmp_digest(path)!=version['sha256'] or durable._file_identity(path)!=identity:
            raise PairRefused('An associated sidecar changed; reindex before importing')
        owners={}
        for relative,file_id in version['owners'].items():
            owner=str(_path(manifest['source_root'],str(Path(manifest['source_root'])/xmp.relative_path(relative))))
            row=conn.execute('SELECT p.sha1_hash FROM photos p JOIN photo_files pf ON pf.photo_id=p.id '
                            'WHERE pf.file_id=? AND p.source_path=?',(file_id,owner)).fetchone()
            if row is None:
                raise PairRefused('An associated sidecar owner no longer matches the catalog')
            owners[owner]=dict(file_id=file_id,sha1_hash=row[0])
        result.append(dict(version,source=str(path),identity=list(identity),owners=owners))
    return result


def _verify_blob(conn, version):
    if hashlib.sha256(xmp_store.original_bytes(conn,version['version_id'])).hexdigest()!=version['sha256']:
        raise PairRefused('An archived sidecar original failed verification')


def _alternatives(manifest):
    return [v for v in manifest.get('versions',[]) if v['source']!=manifest['sidecar_source']]


def _alternative_manifest(manifest, version):
    return dict(manifest,sidecar_source=version['source'],xmp_sha256=version['sha256'],
                version_id=version['version_id'],sidecar_identity=version['identity'],owners=version['owners'])


def _verify_alternative_sources(conn, op, manifest):
    for version in _alternatives(manifest):
        _verify_blob(conn,version)
        path=_path(manifest['source_root'],version['source'])
        if os.path.lexists(path):
            _verify_alternative_source(path,version)
        elif not manifest['move'] or not _had_verified_pair(conn,op):
            raise PairRefused('An alternative source is missing without verified preservation evidence')


def _verify_alternative_source(path, version):
    identity=tuple(version['identity'])
    if (durable._file_identity(path)!=identity or _xmp_digest(path)!=version['sha256']
            or durable._file_identity(path)!=identity):
        raise PairRefused('An alternative sidecar changed; its source was preserved')


def _cleanup_alternatives(conn, manifest):
    notes=[]
    for version in _alternatives(manifest):
        reason=_shared_cleanup_reason(conn,_alternative_manifest(manifest,version))
        if reason:
            notes.append(reason)
            continue
        path=_path(manifest['source_root'],version['source'])
        _verify_blob(conn,version)
        if os.path.lexists(path):
            _verify_alternative_source(path,version)
            path.unlink()
        # A retry repeats the barrier even if the previous unlink already happened.
        durable._fsync_directory(path.parent)
    return notes


def _paths(manifest):
    return tuple(_path(manifest['source_root'] if key.endswith('source') else manifest['destination_root'], manifest[key])
                 for key in ('photo_source','photo_destination','sidecar_source','sidecar_destination'))


def _verified(conn, op, manifest):
    """Both published members durable; commit evidence BEFORE allowing either deletion."""
    _, photo, _, sidecar = _paths(manifest)
    if not _photo_matches(photo,manifest['sha1_hash']) or not _sidecar_matches(sidecar,manifest['xmp_sha256']):
        raise PairRefused('The destination pair is incomplete')
    for path in (photo,sidecar):
        durable._fsync_file(path)
        durable._fsync_directory(path.parent)
        durable._fsync_chain_to_root(path.parent)
    for version in manifest.get('versions',[]):
        _verify_blob(conn,version)
    with ns_db.transaction(conn):
        ns_db.record_evidence(conn,operation_id=op,location_role='destination',observed_path=str(photo),
            observation_kind='sha1',result='match',details={'sha1_hash':manifest['sha1_hash'],
            'pair_verified':True,'sidecar':str(sidecar),'xmp_sha256':manifest['xmp_sha256']})


def _had_verified_pair(conn, op):
    return any(json.loads(row[0] or '{}').get('pair_verified') for row in conn.execute(
        'SELECT details_json FROM operation_evidence WHERE operation_id=?', (op,)))


def _shared_cleanup_reason(conn, manifest):
    """Every other owner must be absent AND have a verified destination-pair receipt.

    Absence alone is never evidence that an externally removed photo was delivered.
    Unindexed/unselected siblings therefore retain the shared source XMP.
    """
    for owner in manifest['owners']:
        if reconcile._recovery_observe(Path(owner)) != 'absent':
            return 'Shared source XMP retained: an associated source photo still needs it.'
        if owner == manifest['photo_source']:
            continue
        if not manifest['owners'][owner]:
            return 'Shared source XMP retained: an associated photo has no catalog identity.'
        from engine import metadata_source_cleanup
        if metadata_source_cleanup.preserved_owner(conn,source=owner,
                source_file_id=manifest['owners'][owner]['file_id'],owner_sha1=manifest['owners'][owner]['sha1_hash'],
                sidecar=manifest['sidecar_source'],sidecar_sha256=manifest['xmp_sha256'],
                destination_root=manifest['destination_root']):
            continue
        receipts = conn.execute("SELECT e.detail_json FROM operations o JOIN operation_events e ON e.operation_id=o.id "
            "WHERE o.source_path=? AND e.step='pair_complete' AND o.status IN (?,?) ORDER BY o.id DESC",
            (owner,PhotoStatus.COMPLETED,PhotoStatus.COPIED)).fetchall()
        verified = False
        for (raw,) in receipts:
            prior = json.loads(raw)
            versions=prior.get('versions',[dict(sha256=prior['xmp_sha256'],source=prior['sidecar_source'],version_id=prior['version_id'])])
            archived=next((v for v in versions if v['sha256']==manifest['xmp_sha256']
                           and v['source']==manifest['sidecar_source']),None)
            if (not archived or prior['file_id'] != manifest['owners'][owner]['file_id']
                    or prior['sha1_hash'] != manifest['owners'][owner]['sha1_hash']):
                continue
            _, photo, _, sidecar = _paths(prior)
            _verify_blob(conn,archived)
            if _photo_matches(photo,prior['sha1_hash']) and _sidecar_matches(sidecar,prior['xmp_sha256']):
                verified = True
                break
        if not verified:
            return 'Shared source XMP retained: another associated photo has no verified destination pair.'
    return None


def _settle(conn, op, manifest, *, completed, error=None, source_removed=False, sidecar_note=None, recovery_run_id=None, failure_context=None, delivery=None):
    pid,_,_ = _manifest(conn,op)
    run_id = conn.execute('SELECT run_id FROM operations WHERE id=?',(op,)).fetchone()[0]
    status = (PhotoStatus.COMPLETED if source_removed else PhotoStatus.COPIED) if completed else PhotoStatus.FAILED
    with ns_db.transaction(conn):
        if completed:
            ns_db.record_delivery(conn,operation_id=op,photo_id=pid,run_id=run_id,
                destination=manifest['photo_destination'],source_removed=source_removed,
                created=manifest['created'],sha1_hash=manifest['sha1_hash'])
        elif reconcile._recovery_observe(Path(manifest['photo_source'])) == 'absent':
            # A cleanup/catalog failure may follow source removal. Record observed
            # absence, without inventing a successful pair or losing its lineage.
            ns_db.record_evidence(conn,operation_id=op,location_role='source',
                observed_path=manifest['photo_source'],observation_kind='stat',result='absent')
            conn.execute("UPDATE file_states SET presence_state='missing',revision=revision+1 "
                         "WHERE file_id=? AND location_role='source'",(manifest['file_id'],))
        # An incomplete pair never enters Library merely because its photo arrived.
        conn.execute('UPDATE photos SET status=? WHERE id=?',(status,pid))
        event = ns_db.settle_operation(conn,op,status=status,step='pair_complete' if completed else 'pair_incomplete',
            outcome='completed' if completed else 'needs_attention',error_message=error or sidecar_note,
            detail=dict(manifest, failure_context=failure_context, delivery=delivery) if failure_context or delivery else manifest)
        if completed and manifest.get('activation'):
            metadata_import.activate(conn,op,pid,manifest['activation'])
        if completed:
            # Resolve only this explicit retry chain, never unrelated file issues.
            prior = conn.execute('SELECT reconciles_operation_id FROM operations WHERE id=?',(op,)).fetchone()[0]
            while prior is not None:
                for (issue,) in conn.execute("SELECT issue_id FROM attention_issues WHERE operation_id=? "
                        "AND category='metadata_pair_incomplete' AND resolved_at IS NULL",(prior,)).fetchall():
                    ns_db.resolve_attention_issue(conn,issue,event_id=event)
                prior = conn.execute('SELECT reconciles_operation_id FROM operations WHERE id=?',(prior,)).fetchone()[0]
        if not completed:
            ns_db.open_attention_issue(conn,operation_id=op,category='metadata_pair_incomplete',
                summary=error,file_id=conn.execute('SELECT file_id FROM photo_files WHERE photo_id=?',(pid,)).fetchone()[0])
        if recovery_run_id is not None:
            recovery = ns_db.begin_operation(conn,run_id=recovery_run_id,photo_id=pid,
                source_path=manifest['photo_source'],dest_path=manifest['photo_destination'],
                kind='metadata_pair_recovery',expected=manifest,reconciles=op)
            conn.execute('UPDATE operations SET sha1_hash=? WHERE id=?',(manifest['sha1_hash'],recovery))
            conn.execute("INSERT OR IGNORE INTO operation_files(operation_id,file_id,role) "
                         "SELECT ?,file_id,role FROM operation_files WHERE operation_id=? AND role<>'source'",(recovery,op))
            ns_db.settle_operation(conn,recovery,status=status,step='pair_recovery',outcome='recorded',
                                  error_message=error or sidecar_note,detail={'recovered_operation_id':op})
    return {'operation_id':op,'completed':completed,'status':status,'error':error,'sidecar_note':sidecar_note}


def execute(conn, operation_id):
    """Publish/verify both members, then Move cleanup. Owns its FULL transactions.

    Exceptions leave recorded recovery intent. Ordinary failures settle with a precise
    reason. Completed replay is a read of the receipt, never another file mutation.
    """
    _idle_full(conn)
    pid, status, m = _manifest(conn,operation_id)
    if status in (PhotoStatus.COPIED,PhotoStatus.COMPLETED):
        return {'operation_id':operation_id,'completed':True,'status':status,'replayed':True}
    if status != PhotoStatus.PROCESSING:
        raise PairRefused('Start an explicit retry of the incomplete pair')
    _binding(conn,pid,m)
    previous_root = durable._destination_root
    durable._destination_root = Path(m['destination_root'])
    durable._verified_directories.clear()
    delivery = {'photo':'unknown', 'xmp':'unknown'}
    failure_context = dict(stage='Checking pair paths', paths=[])
    try:
        src,dst,xsrc,xdst = _paths(m)
        failure_context = dict(stage='Checking destination pair', paths=[str(dst),str(xdst)])
        if os.path.lexists(xdst) and not os.path.lexists(dst):
            raise PairRefused('Destination XMP exists but its photo is missing; resolve the destination pair')
        # Read-back of retained metadata is also required on a resumed operation.
        failure_context = dict(stage='Verifying archived XMP', paths=[])
        if hashlib.sha256(xmp_store.original_bytes(conn,m['version_id'])).hexdigest() != m['xmp_sha256']:
            raise PairRefused('The archived XMP version is not verified')
        failure_context = dict(stage='Verifying alternative XMP sources', paths=[v['source'] for v in _alternatives(m)])
        _verify_alternative_sources(conn,operation_id,m)
        for source,target,digest,is_xmp in ((src,dst,m['sha1_hash'],False),(xsrc,xdst,m['xmp_sha256'],True)):
            key = 'xmp' if is_xmp else 'photo'
            member = 'XMP' if is_xmp else 'photo'
            failure_context = dict(stage=f'Checking source {member}', paths=[str(source)])
            present = reconcile._recovery_observe(source) != 'absent'
            matches = _sidecar_matches if is_xmp else _photo_matches
            if present:
                identity = m['sidecar_identity'] if is_xmp else m['source_identity']
                if list(durable._file_identity(source)) != list(identity) or not matches(source,digest):
                    raise PairRefused('Source no longer matches the pair being transferred')
            elif not m['move'] or not _had_verified_pair(conn,operation_id):
                raise PairRefused('A source is missing without a durable verified-pair receipt')
            delivery[key] = 'incomplete'
            failure_context = dict(stage=f'Checking destination {member}', paths=[str(target)])
            if not matches(target,digest):
                if not present:
                    raise PairRefused('Both source and destination for a pair member are missing')
                failure_context = dict(stage=f'Transferring {member}', paths=[str(source),str(target)])
                ok, reason = durable.copy_verify_delete(str(source),str(target),delete_source=False)
                if not ok:
                    raise PairRefused(reason)
            delivery[key] = 'verified'
        failure_context = dict(stage='Verifying destination pair', paths=[str(dst),str(xdst)])
        # A final verification failure must not retain an earlier green observation.
        delivery = {'photo':'unknown', 'xmp':'unknown'}
        _verified(conn,operation_id,m)
        delivery = {'photo':'verified', 'xmp':'verified'}
        notes = []
        if _alternatives(m):
            notes.append(f"{len(_alternatives(m))} alternative XMP original(s) preserved in lineage; the selected primary is unchanged.")
        if m['move']:
            failure_context = dict(stage='Removing verified source photo', paths=[str(src)])
            if src.exists():
                durable._remove_verified_source(src,dst,tuple(m['source_identity']),'Remove verified photo source')
            # Repeat after a prior unlink whose directory sync failed.
            durable._fsync_directory(src.parent)
            failure_context = dict(stage='Checking shared XMP ownership', paths=[str(xsrc)])
            note = _shared_cleanup_reason(conn,m)
            if note:notes.append(note)
            if note is None:
                failure_context = dict(stage='Removing verified source XMP', paths=[str(xsrc)])
                if xsrc.exists():
                    durable._remove_verified_source(xsrc,xdst,tuple(m['sidecar_identity']),'Remove verified XMP source')
                durable._fsync_directory(xsrc.parent)
            failure_context = dict(stage='Cleaning up alternative XMP sources', paths=[v['source'] for v in _alternatives(m)])
            notes.extend(_cleanup_alternatives(conn,m))
        failure_context = dict(stage='Recording completed transfer', paths=[])
        return _settle(conn,operation_id,m,completed=True,source_removed=m['move'],sidecar_note=' '.join(dict.fromkeys(notes)) or None)
    except Exception as exc:
        return _settle(conn,operation_id,m,completed=False, failure_context=failure_context, delivery=delivery,
            error=f"Photo/XMP transfer incomplete while {failure_context['stage'].lower()}: {type(exc).__name__}: {exc}. Published files were preserved; review the pair before retrying.")
    finally:
        durable._destination_root = previous_root
        durable._verified_directories.clear()


def retry(conn, operation_id, *, run_id):
    """New intent for an explicit retry; keeps failed outcomes and their lineage."""
    _idle_full(conn)
    pid,status,m = _manifest(conn,operation_id)
    if status != PhotoStatus.FAILED:
        raise PairRefused('Only a settled incomplete pair can be retried')
    run = conn.execute('SELECT source_path,dest_path,mode FROM runs WHERE id=?',(run_id,)).fetchone()
    if not run or tuple(run) != (m['source_root'],m['destination_root'],'MOVE' if m['move'] else 'COPY'):
        raise PairRefused('Retry must use the same roots and operation mode')
    latest = conn.execute('SELECT MAX(o.id) FROM operations o JOIN operation_events e ON e.operation_id=o.id '
        "WHERE o.photo_id=? AND e.step='intent' AND json_extract(e.detail_json,'$.kind')=?",(pid,KIND)).fetchone()[0]
    if latest != operation_id:
        raise PairRefused('This pair already has a newer operation')
    _binding(conn,pid,m)
    new = _begin(conn,run_id=run_id,photo_id=pid,manifest=m,reconciles=operation_id)
    if _had_verified_pair(conn,operation_id):
        # Re-establish the bytes and durability; never copy a trust flag unchecked.
        _verified(conn,new,m)
    return new


def recover(conn, operation_id, *, run_id=None):
    """Observe a killed pair operation. Never deletes, publishes, or guesses success."""
    _idle_full(conn)
    _,status,m = _manifest(conn,operation_id)
    if status != PhotoStatus.PROCESSING:
        raise PairRefused('Only an unsettled pair needs recovery')
    previous_root = durable._destination_root
    durable._destination_root = Path(m['destination_root'])
    durable._verified_directories.clear()
    delivery = {'photo':'unknown', 'xmp':'unknown'}
    try:
        src,dst,xsrc,xdst = _paths(m)
        _verify_alternative_sources(conn,operation_id,m)
        photo = _photo_matches(dst,m['sha1_hash'])
        delivery['photo'] = 'verified' if photo else 'incomplete'
        sidecar = _sidecar_matches(xdst,m['xmp_sha256'])
        delivery['xmp'] = 'verified' if sidecar else 'incomplete'
        sources = [reconcile._recovery_observe(p) for p in (src,xsrc)]
        if photo and sidecar and ((not m['move'] and sources == ['present','present']) or
                                 (m['move'] and sources[0] == 'absent' and _had_verified_pair(conn,operation_id))):
            if m['move'] and sources[1] != 'absent' and _shared_cleanup_reason(conn,m) is None:
                raise PairRefused('The pair arrived but source XMP cleanup is unfinished; retry the Move')
            if m['move']:
                for version in _alternatives(m):
                    path=_path(m['source_root'],version['source'])
                    if os.path.lexists(path):
                        if _shared_cleanup_reason(conn,_alternative_manifest(m,version)) is None:
                            raise PairRefused('Alternative preservation is verified but source cleanup is unfinished; retry the Move')
                    else:
                        durable._fsync_directory(path.parent)
            delivery = {'photo':'unknown', 'xmp':'unknown'}
            _verified(conn,operation_id,m)
            delivery = {'photo':'verified', 'xmp':'verified'}
            if m['move']:
                durable._fsync_directory(src.parent)
                if sources[1] == 'absent':
                    durable._fsync_directory(xsrc.parent)
            return _settle(conn,operation_id,m,completed=True,source_removed=m['move'],
                           sidecar_note='Recovered by verifying both destination files; recovery changed no files.',recovery_run_id=run_id)
        raise PairRefused(f'Destination photo verified: {photo}; destination XMP verified: {sidecar}; '
                          f'source photo: {sources[0]}; source XMP: {sources[1]}. Retry after resolving the cause')
    except Exception as exc:
        return _settle(conn,operation_id,m,completed=False,error=f'Interrupted photo/XMP transfer: {exc}',recovery_run_id=run_id,delivery=delivery)

    finally:
        durable._destination_root = previous_root
        durable._verified_directories.clear()
