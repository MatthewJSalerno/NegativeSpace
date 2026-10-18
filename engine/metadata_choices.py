"""Source-only import choices; catalog evidence, never photo or sidecar writes."""
import contextlib
from datetime import datetime
import json
import re
from pathlib import Path

from engine import metadata_capture, metadata_decisions, metadata_edits, ns_db

CHOICE_CODES = frozenset({'ambiguous_ownership', 'owner_conflict', 'saved_owner_changed', 'metadata_choice_needed'})


def inspect(conn, photo_id, source_root):
    if type(photo_id) is not int or not 1 <= photo_id <= 2**63-1:
        raise ValueError('Choose a valid photo.')
    row = conn.execute('SELECT p.status,p.source_path,p.dest_path,pf.file_id FROM photos p '
        'JOIN photo_files pf ON pf.photo_id=p.id WHERE p.id=?', (photo_id,)).fetchone()
    if not row or row[0] != 'Pending':
        raise ValueError('Import choices are available only for photos still waiting in Not organized.')
    capture = conn.execute('SELECT MAX(capture_id) FROM metadata_captures WHERE file_id=?', (row[3],)).fetchone()[0]
    identity, relative, report, captured_root = metadata_decisions._capture(conn, capture)
    if Path(captured_root) != Path(source_root):
        raise ValueError('This evidence belongs to another source. Restore that source or run Index again.')
    if not any(i.get('code') in CHOICE_CODES for i in report['issues']):
        raise ValueError('This photo has no unresolved import choice.')
    blockers = [i for i in report['issues'] if i.get('code') not in CHOICE_CODES]
    sidecars = []
    for side in report['sidecars']:
        if 'sidecar:' + side['path'] not in report['sources']:
            continue
        candidates = metadata_decisions._candidate_ids(conn, captured_root, side.get('all_candidates', side['candidates']))
        saved = metadata_decisions.current(conn, 'association', metadata_decisions.association_scope(captured_root, side['path']))
        saved_valid = saved and all(candidates.get(path)==fid for path,fid in saved['value']['owners'].items())
        owners = saved['value']['owners'] if saved_valid else ({p:candidates[p] for p in side['candidates'] if p in candidates} if side['state']=='associated' else {})
        photos = []
        for path in side.get('all_candidates', side['candidates']):
            fid = candidates.get(path)
            candidate = conn.execute('SELECT p.id,p.status,p.dest_path FROM photos p JOIN photo_files pf '
                'ON pf.photo_id=p.id WHERE pf.file_id=?', (fid,)).fetchone() if fid else None
            photos.append(dict(path=path,file_id=fid,photo_id=candidate[0] if candidate else None,
                selectable=bool(candidate and candidate[1]=='Pending')))
        sidecars.append(dict(path=side['path'],fields=report['sources']['sidecar:'+side['path']]['fields'],
            needs_choice=side['state']=='needs_choice' and not saved_valid, saved=bool(saved_valid),
            can_choose=side['state']=='needs_choice',
            owner_ids=list(owners.values()),candidates=photos))
    primary = metadata_decisions.current(conn, 'primary', str(identity))
    sources = []
    for key, source in report['sources'].items():
        if key.startswith('sidecar:'):
            side = next((s for s in sidecars if s['path']==key[8:]), None)
            if not side or identity not in side['owner_ids']:
                continue
        sources.append(dict(id=key,label={'exif':'EXIF','embedded_xmp':'Embedded XMP'}.get(key,key[8:]),fields=source['fields']))
    return dict(photo_id=photo_id,capture_id=capture,filename=Path(relative).name,sidecars=sidecars,
        sources=sources,primary_id=primary['value']['primary_id'] if primary else None,
        needs_primary=any(i.get('code')=='metadata_choice_needed' for i in report['issues']), blockers=blockers)


def projected_destination(conn, photo_id, source_root, destination_root):
    """Catalog-only filing preview after saved first-import choices.

    Never activates metadata or reserves a filename. Copy/Move recaptures source
    evidence and verifies delivery; stale or incomplete choices keep the Index plan.
    """
    try:
        state = inspect(conn, photo_id, source_root)
        if state['blockers'] or any(s['needs_choice'] for s in state['sidecars']):
            return None
        if not state['primary_id'] and not any(s['saved'] for s in state['sidecars']):
            return None
        identity, relative, report, _ = metadata_decisions._capture(conn, state['capture_id'])
        sources = {s['id']: report['sources'][s['id']] for s in state['sources']}
        selected = state['primary_id']
        if selected:
            decision = metadata_decisions.current(conn, 'primary', str(identity))
            earlier = conn.execute('SELECT catalog_sha1,report_json FROM metadata_captures WHERE capture_id=?',
                                   (decision['capture_id'],)).fetchone()
            latest = conn.execute('SELECT catalog_sha1 FROM metadata_captures WHERE capture_id=?',
                                  (state['capture_id'],)).fetchone()
            if (selected not in sources or not earlier or earlier[0] != latest[0]
                    or json.loads(earlier[1])['sources'].get(selected) != sources[selected]):
                return None
            resolution = metadata_capture.resolve(sources, list(sources), primary_id=selected)
        else:
            sides = [s for s in report['sidecars'] if 'sidecar:' + s['path'] in sources]
            preferred = [s for s in sides if Path(s['path']).stem == Path(relative).name] or sides
            if len({s['sha256'] for s in preferred}) > 1:
                return None
            selected = 'sidecar:' + min(preferred, key=lambda s:s['path'])['path'] if preferred else None
            priority = ([selected] if selected else []) + [k for k in ('embedded_xmp','exif') if k in sources]
            resolution = metadata_capture.resolve(sources, priority)
        original = conn.execute('SELECT file_mtime FROM source_snapshots WHERE file_id=?', (identity,)).fetchone()
        if not original or original[0] is None:
            return None
        folder = metadata_edits._folder(resolution['proposed_effective'], datetime.fromtimestamp(original[0]).year)
        return str(Path(destination_root) / folder / Path(relative).name)
    except (ValueError, ns_db.RevisionConflict):
        # Old decisions are observations, not permission to project changed evidence.
        return None


def context(db_path, photo_id, source_root):
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        ns_db.require_schema(conn)
        conn.execute('BEGIN')
        return inspect(conn,photo_id,source_root)


def validate(conn, body, source_root):
    if not isinstance(body,dict) or set(body) != {'photo_id','kind','selection'}:
        raise ValueError('Choose the source photo and its import decision.')
    state = inspect(conn,body['photo_id'],source_root)
    if state['blockers']:
        raise ValueError('Repair the recorded source metadata problems and run Index before choosing metadata.')
    selection=body['selection']
    if not isinstance(selection,dict) or selection.get('capture_id') != state['capture_id']:
        raise ns_db.RevisionConflict('The recorded metadata changed. Reload the choices.')
    if body['kind']=='association':
        side=next((s for s in state['sidecars'] if s['path']==selection.get('sidecar')),None)
        if not side or not side['can_choose']:
            raise ValueError('Choose an unresolved sidecar association.')
        if any(not p['selectable'] for p in side['candidates']):
            raise ValueError('Every candidate must be indexed and still unorganized before resolving this association.')
    elif body['kind']=='primary':
        if not state['needs_primary'] or any(s['needs_choice'] for s in state['sidecars']):
            raise ValueError('Resolve sidecar ownership before choosing a primary version.')
        if selection.get('primary_id') not in {s['id'] for s in state['sources'] if s['id'].startswith('sidecar:')}:
            raise ValueError('Choose an owned, readable metadata source.')
    else:
        raise ValueError('Choose sidecar ownership or a primary metadata version.')
    return state


def preview(db_path, body, source_root):
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        ns_db.require_schema(conn)
        conn.execute('BEGIN')
        state=validate(conn,body,source_root)
        result=metadata_decisions._proposal(conn,body['kind'],body['selection'])
        # The engine token binds exact evidence/ownership. Do not expose root paths
        # or depend on client-provided effective fields in the confirmation.
        return dict(choice=body,token=result['token'],filename=state['filename'],
            owners=list(result['after'].get('owners',{})),differences=result.get('differences',[]),
            effective=result['after'].get('resolution',{}).get('proposed_effective'),
            primary_id=result['after'].get('primary_id'))


def confirm(db_path, body, source_root):
    """Called only under the engine lock. Replays precede current eligibility checks."""
    if not isinstance(body,dict) or set(body)!={'choice','token','request_id'}:
        raise ValueError('Supply the preview, token and request ID.')
    if not isinstance(body['request_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',body['request_id']):
        raise ValueError('Invalid request ID.')
    if not isinstance(body['token'],str) or not re.fullmatch(r'[0-9a-f]{64}',body['token']):
        raise ValueError('Invalid preview token.')
    choice=body['choice']
    if not isinstance(choice,dict) or set(choice)!={'photo_id','kind','selection'}:
        raise ValueError('Invalid import choice.')
    # Bind the HTTP photo and configured root on replay too. A replay must never
    # confirm a different photo merely because its caller reused a request ID.
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        ns_db.require_schema(conn)
        selection=choice['selection']
        if not isinstance(selection,dict) or type(selection.get('capture_id')) is not int or not 1 <= selection['capture_id'] <= 2**63-1:
            raise ValueError('Invalid import selection.')
        bound=conn.execute('SELECT pf.photo_id,r.source_path FROM metadata_captures m '
            'JOIN photo_files pf USING(file_id) JOIN runs r ON r.id=m.run_id WHERE m.capture_id=?',
            (selection.get('capture_id'),)).fetchone()
        if not bound or type(choice['photo_id']) is not int or bound[0]!=choice['photo_id'] or Path(bound[1])!=Path(source_root):
            raise ValueError('The choice must belong to this photo and source.')
        previous=conn.execute('SELECT 1 FROM metadata_decisions WHERE request_id=?',(body['request_id'],)).fetchone()
        if not previous:
            validate(conn,choice,source_root)
    result=metadata_decisions.confirm(db_path,kind=choice['kind'],selection=selection,
        token=body['token'],request_id=body['request_id'])
    return dict(revision=result['revision'],message='Choice saved. Copy or Move will apply it and verify the files. Source files are unchanged; this photo stays in Not organized until imported.')
