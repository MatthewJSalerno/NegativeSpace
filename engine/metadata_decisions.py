"""Catalog-only metadata decisions with version-bound previews and append-only history.

No file edits or filing activation. Preview/confirm is an engine boundary for
API/CLI callers; it never trusts submitted effective fields or photo ownership.
"""
import contextlib
import hashlib
import json
from pathlib import Path
import re

from engine import metadata_capture, metadata_save, ns_db, xmp


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def association_scope(root, sidecar):
    return _json([str(root), xmp.relative_path(sidecar).as_posix()])


def current(conn, kind, scope, *, highwater=None):
    sql = 'SELECT decision_id,capture_id,value_json FROM metadata_decisions WHERE kind=? AND scope=?'
    params = [kind, scope]
    if highwater is not None:
        sql += ' AND decision_id<=?'
        params.append(highwater)
    row = conn.execute(sql + ' ORDER BY decision_id DESC LIMIT 1', params).fetchone()
    return {'revision': row[0], 'capture_id': row[1], 'value': json.loads(row[2])} if row else None


def _capture(conn, capture_id, *, allow_edited=False):
    if type(capture_id) is not int or not 1 <= capture_id <= 2**63-1:
        raise ValueError('Invalid metadata capture identity')
    row = conn.execute('SELECT m.file_id,m.source_relative_path,m.catalog_sha1,m.report_json,r.source_path '
                       'FROM metadata_captures m JOIN runs r ON r.id=m.run_id WHERE m.capture_id=?',
                       (capture_id,)).fetchone()
    if row is None:
        raise ValueError('Unknown metadata capture')
    file_id, relative, digest, report, root = row
    latest = conn.execute('SELECT MAX(capture_id) FROM metadata_captures WHERE file_id=?', (file_id,)).fetchone()[0]
    live = conn.execute('SELECT p.sha1_hash FROM photos p JOIN photo_files pf ON pf.photo_id=p.id '
                        'WHERE pf.file_id=? AND p.source_path=?', (file_id, str(Path(root)/relative))).fetchone()
    verified_edit = False
    if allow_edited and live is not None and live[0] != digest:
        photo = conn.execute('SELECT photo_id FROM photo_files WHERE file_id=?',(file_id,)).fetchone()
        edited = metadata_save.active(conn, photo[0]) if photo else None
        observed = conn.execute('SELECT sha1_hash FROM file_observations WHERE file_id=? '
            'ORDER BY observation_id DESC LIMIT 1',(file_id,)).fetchone()
        verified_edit = bool(edited and edited.get('content_changed') and edited['sha1_hash']==live[0]
                             and observed and observed[0]==digest)
    if latest != capture_id or live is None or (live[0] != digest and not verified_edit):
        raise ns_db.RevisionConflict('Metadata evidence changed; preview the current capture.')
    return file_id, relative, json.loads(report), root


def _candidate_ids(conn, root, paths):
    result = {}
    for relative in paths:
        path = xmp.relative_path(relative)
        row = conn.execute('SELECT pf.file_id FROM photos p JOIN photo_files pf ON pf.photo_id=p.id '
                           'WHERE p.source_path=? ORDER BY p.id DESC LIMIT 1', (str(Path(root)/path),)).fetchone()
        if row:
            result[relative] = row[0]
    return result


def _candidate_evidence(conn, identities):
    evidence = {}
    for identity in sorted(set(identities)):
        row = conn.execute('SELECT p.sha1_hash,pf.revision, '
            '(SELECT MAX(capture_id) FROM metadata_captures WHERE file_id=pf.file_id) '
            'FROM photos p JOIN photo_files pf ON pf.photo_id=p.id WHERE pf.file_id=?', (identity,)).fetchone()
        evidence[str(identity)] = list(row) if row else None
    return evidence


def _observation(report, sidecar):
    found = next((s for s in report['sidecars'] if s['path'] == sidecar), None)
    if found is None or 'sidecar:' + sidecar not in report['sources']:
        raise ValueError('Choose a valid captured XMP sidecar')
    return found


def _retained(conn, capture_id, sidecar, digest):
    # Membership in an immutable report is not sufficient: prove the exact captured
    # version and its bound arrival were retained before allowing activation choices.
    row = conn.execute('SELECT v.version_id FROM metadata_captures m '
        'JOIN xmp_arrivals a ON a.run_id=m.run_id AND a.source_relative_path=? '
        'JOIN xmp_versions v USING(version_id) WHERE m.capture_id=? AND v.sha256=? '
        "AND v.validation_state='valid'", (sidecar, capture_id, digest)).fetchone()
    if row is None:
        raise ValueError('The captured sidecar is not retained as valid metadata')
    return row[0]


def _owners(conn, root, observation, *, highwater=None):
    saved = current(conn, 'association', association_scope(root, observation['path']), highwater=highwater)
    paths = set(observation.get('all_candidates', observation['candidates']))
    if saved:paths.update(saved['value']['owners'])
    candidates = _candidate_ids(conn, root, sorted(paths))
    if saved:
        owners = saved['value']['owners']
        if any(candidates.get(path) != identity for path, identity in owners.items()):
            raise ns_db.RevisionConflict('Saved sidecar ownership no longer matches the captured photos.')
        return owners, saved['revision']
    if observation['state'] != 'associated':
        raise ValueError('Resolve sidecar ownership before choosing it as primary')
    if any(path not in candidates for path in observation['candidates']):
        raise ValueError('Index the associated photos before confirming ownership')
    return {path:candidates[path] for path in observation['candidates']}, 0


def _proposal(conn, kind, selection):
    if not isinstance(selection, dict):
        raise ValueError('Expected a metadata choice')
    required = {'capture_id','sidecar','owner_ids'} if kind == 'association' else {'capture_id','primary_id'}
    if kind not in ('association','primary') or set(selection) != required:
        raise ValueError('Invalid metadata decision fields')
    file_id, relative, report, root = _capture(conn, selection['capture_id'])
    if any(i['source'] in ('photo','folder') for i in report['issues']):
        raise ValueError('Capture readable, stable photo evidence before deciding')
    dependencies = []
    if kind == 'association':
        sidecar = selection['sidecar']
        if not isinstance(sidecar,str):
            raise ValueError('Invalid sidecar name')
        observation = _observation(report, sidecar)
        version = _retained(conn, selection['capture_id'], sidecar, observation.get('sha256'))
        owners = selection['owner_ids']
        if (not isinstance(owners,list) or not owners or any(type(i) is not int or i < 1 for i in owners)
                or len(set(owners)) != len(owners)):
            raise ValueError('Choose unique captured photo identities')
        candidates = _candidate_ids(conn, root, observation.get('all_candidates', observation['candidates']))
        if not set(owners) <= set(candidates.values()):
            raise ValueError('Sidecar owners must be indexed candidates from this source')
        chosen = {path:identity for path,identity in candidates.items() if identity in owners}
        scope = association_scope(root, sidecar)
        value = {'owners': chosen, 'sidecar':sidecar, 'root':root, 'version_id':version,
                 'sha256':observation['sha256']}
        # Include all observed candidates so a newly indexed/replaced sibling makes
        # a previously presented choice stale rather than changing its meaning.
        dependencies.append(candidates)
        dependencies.append(_candidate_evidence(conn,candidates.values()))
        # Ownership cannot silently detach another photo's established primary.
        for identity in candidates.values():
            primary = current(conn,'primary',str(identity))
            dependencies.append(primary)
            if (identity not in owners and primary and primary['value']['primary_id'] == 'sidecar:' + sidecar):
                raise ValueError('Change that photo primary explicitly before removing its sidecar ownership')
    else:
        primary = selection['primary_id']
        if not isinstance(primary,str) or primary not in report['sources']:
            raise ValueError('Choose a valid source from this capture')
        if primary.startswith('sidecar:'):
            observation = _observation(report, primary[8:])
            version = _retained(conn, selection['capture_id'], primary[8:], observation.get('sha256'))
            owners, revision = _owners(conn, root, observation)
            if owners.get(relative) != file_id:
                raise ValueError('This photo does not own the selected sidecar')
            dependencies.append({'owners':owners,'revision':revision,'version_id':version,
                                 'evidence':_candidate_evidence(conn,owners.values())})
        elif primary not in ('exif','embedded_xmp'):
            raise ValueError('Unknown primary source kind')
        scope = str(file_id)
        resolution = metadata_capture.resolve(report['sources'], list(report['sources']), primary_id=primary)
        value = {'file_id':file_id, 'primary_id':primary, 'capture_id':selection['capture_id'],
                 'resolution':resolution, 'filing_applied':False}
    before = current(conn,kind,scope)
    result = {'kind':kind,'scope':scope,'selection':selection,'revision':before['revision'] if before else 0,
              'before':before['value'] if before else None,'after':value,'dependencies':dependencies}
    if kind == 'primary':
        old = before['value']['resolution'] if before else report.get('resolution', {})
        old_fields, new_fields = old.get('proposed_effective',{}), value['resolution']['proposed_effective']
        result['differences'] = [
            {'field':key, 'before':{'present':key in old_fields,'value':old_fields.get(key)},
             'after':{'present':key in new_fields,'value':new_fields.get(key)}}
            for key in sorted(old_fields.keys() | new_fields.keys())
            if _json([key in old_fields,old_fields.get(key)]) != _json([key in new_fields,new_fields.get(key)])]
        result['filing_date_may_change'] = any(d['field']=='date_taken' for d in result['differences'])
    result['token'] = hashlib.sha256(_json(result).encode()).hexdigest()
    return result


def preview(db_path, kind, selection):
    """Read-only, consistent preview; no mutation and no filesystem access."""
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        ns_db.require_schema(conn)
        conn.execute('BEGIN')
        return _proposal(conn, kind, selection)


def confirm(db_path, *, kind, selection, token, request_id):
    """Recompute and atomically save an explicit confirmation, never submitted values.

    Refuse while a job is active. BEGIN IMMEDIATE serializes this check against job
    acceptance and other decisions; no photo operation runs from this entry point.
    Exact request replay returns the original decision even after later changes.
    """
    if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',request_id):
        raise ValueError('Invalid decision request ID')
    if not isinstance(token,str) or not re.fullmatch(r'[0-9a-f]{64}',token):
        raise ValueError('Invalid preview token')
    payload = _json({'kind':kind,'selection':selection,'token':token})
    with contextlib.closing(ns_db.connect(db_path,synchronous='FULL')) as conn:
        ns_db.require_schema(conn)
        with ns_db.transaction(conn):
            prior = conn.execute('SELECT decision_id,request_json,value_json FROM metadata_decisions '
                                 'WHERE request_id=?',(request_id,)).fetchone()
            if prior:
                if prior[1] != payload:
                    raise ns_db.RequestConflict('Request ID already belongs to a different metadata decision')
                return {'revision':prior[0],'value':json.loads(prior[2])}
            if conn.execute("SELECT 1 FROM runs WHERE status IN ('Preparing','Running','Cancelling') LIMIT 1").fetchone():
                raise ns_db.RevisionConflict('Finish or recover the active job before confirming metadata choices.')
            proposal = _proposal(conn,kind,selection)
            if proposal['token'] != token:
                raise ns_db.RevisionConflict('The evidence or choice changed; preview again before confirming.')
            if kind == 'primary' and selection['primary_id'].startswith('sidecar:'):
                sidecar = selection['primary_id'][8:]
                _, _, report, root = _capture(conn, selection['capture_id'])
                observation = _observation(report, sidecar)
                owners, owner_revision = _owners(conn, root, observation)
                if owner_revision == 0:
                    # Confirming a sidecar primary also confirms the ownership shown
                    # in its preview. A later default change must not undo that choice.
                    ownership = _proposal(conn, 'association', {'capture_id':selection['capture_id'],
                        'sidecar':sidecar, 'owner_ids':sorted(owners.values())})
                    conn.execute('INSERT INTO metadata_decisions(kind,scope,capture_id,request_id,request_json,value_json,created_at) '
                        'VALUES(?,?,?,?,?,?,?)',('association',ownership['scope'],selection['capture_id'],
                            'association:' + request_id, payload, _json(ownership['after']), ns_db.utc_now()))
            cur = conn.execute('INSERT INTO metadata_decisions(kind,scope,capture_id,request_id,request_json,value_json,created_at) '
                'VALUES(?,?,?,?,?,?,?)',(kind,proposal['scope'],selection['capture_id'],request_id,payload,
                                       _json(proposal['after']),ns_db.utc_now()))
            return {'revision':cur.lastrowid,'value':proposal['after']}


def saved_association(conn, root, sidecar, association, source_ids, *, highwater):
    """Apply recorded ownership before a changed default, without validating new bytes.

    The reader must still validate each new sidecar version. Broken/missing bindings
    stay unresolved; existing ownership is not reassigned from filenames or settings.
    """
    saved = current(conn,'association',association_scope(root,sidecar),highwater=highwater)
    if saved is None or association.state in ('ignored','needs_attention'):
        return association
    from engine.xmp_association import Association
    owners = saved['value']['owners']
    if any(source_ids.get(path) != identity for path,identity in owners.items()):
        return Association(sidecar,'needs_choice',association.photos,'saved_owner_changed')
    return Association(sidecar,'associated',tuple(sorted(owners)),'resolved','confirmed')


def transfer_hold(conn, photo_id):
    """Safety gate for cases outside the normal resolved single-sidecar import bridge.

    Applies to primary delivery AND duplicate cleanup. Never turn a metadata question
    into a failed photo or delete the image half of a source pair.
    """
    from engine import earlier_versions
    earlier = earlier_versions.hold(conn, photo_id)
    if earlier:
        return earlier
    edited = metadata_save.active(conn, photo_id)
    if edited and edited.get('content_changed'):
        from engine import metadata_source_cleanup
        return metadata_source_cleanup.NOTICE
    row = conn.execute('SELECT m.report_json,m.source_relative_path FROM photo_files pf JOIN metadata_captures m '
        'ON m.file_id=pf.file_id WHERE pf.photo_id=? ORDER BY m.capture_id DESC LIMIT 1', (photo_id,)).fetchone()
    if row is None:
        return None
    report = json.loads(row[0])
    if any(issue['source'] == 'folder' for issue in report['issues']):
        return ('Source folder metadata could not be inventoried safely. The photo remains at source; '
                'check folder access and run Index again.')
    sidecars = [s for s in report['sidecars'] if s['state'] != 'ignored'
                and (s['state'] != 'associated' or row[1] in s['candidates'])]
    if sidecars:
        if any(s['state'] in ('needs_choice','needs_attention') for s in sidecars):
            return ('Metadata choice or repair needed. Photo and XMP remain at source. '
                    'Resolve XMP choices in Not organized. For unreadable metadata, repair the source file and run Index again.')
        return ('Photo and XMP remain at source: this incoming metadata or duplicate case needs a decision before transfer. '
                'The captured metadata and any saved choices are preserved.')
    primary = conn.execute("SELECT 1 FROM metadata_decisions d JOIN photo_files pf ON d.scope=CAST(pf.file_id AS TEXT) "
                           "WHERE d.kind='primary' AND pf.photo_id=? LIMIT 1",(photo_id,)).fetchone()
    if primary:
        return ('Apply the saved primary choice before organizing or removing this source.')
    return None
