"""Read-only destination folder previews; no file reads, reservations or run creation."""
import hashlib
import json
from pathlib import Path

from engine import constants, destinations, metadata_import, move_confirmation, ns_db

PAGE_SIZE = 20


def snapshot(conn, *, source, destination, photo_ids=None, source_subdir=None):
    scope = move_confirmation.snapshot(conn, source=source, destination=destination,
                                      photo_ids=photo_ids, source_subdir=source_subdir)
    ids = json.dumps(scope['file_ids'])
    rows = conn.execute("SELECT p.id,p.source_path,p.dest_path,p.status,p.sha1_hash,p.metadata_json,"
        "(SELECT MAX(m.capture_id) FROM photo_files pf JOIN metadata_captures m ON m.file_id=pf.file_id WHERE pf.photo_id=p.id) "
        "FROM photos p WHERE p.id IN (SELECT value FROM json_each(?)) ORDER BY p.id", (ids,)).fetchall()
    config = {**ns_db.METADATA_DEFAULTS, **{k:json.loads(v) for k,v in conn.execute('SELECT key,value_json FROM settings')}}
    config['metadata_decision_highwater'] = conn.execute('SELECT COALESCE(MAX(decision_id),0) FROM metadata_decisions').fetchone()[0]
    # Matching rows outside this source can affect duplicate delivery. Include their
    # recorded paths/statuses without walking another source or the destination.
    anchors = conn.execute("SELECT id,source_path,dest_path,status,sha1_hash FROM photos WHERE sha1_hash IN "
        "(SELECT sha1_hash FROM photos WHERE id IN (SELECT value FROM json_each(?))) ORDER BY id", (ids,)).fetchall()
    token = hashlib.sha256(json.dumps([scope['token'],[list(x) for x in rows],
        [list(x) for x in anchors],config],sort_keys=True).encode()).hexdigest()
    return scope, rows, anchors, config, token


def check(conn, token, **scope):
    result = snapshot(conn, **scope)
    if result[4] != token:
        raise ValueError('The destination preview changed. Nothing was transferred. Refresh the preview and confirm again.')
    return result


def preview(conn, *, source, destination, mode, photo_ids=None, source_subdir=None,
            token=None, page=1, folder=None, file_page=1):
    if mode not in ('copy','move'):
        raise ValueError('Choose Copy or Move.')
    if any(type(x) is not int or x < 1 for x in (page,file_page)) or (folder is not None and not isinstance(folder,str)):
        raise ValueError('Choose a valid preview page or folder.')
    base, rows, anchors, config, current = snapshot(conn, source=source, destination=destination,
        photo_ids=photo_ids, source_subdir=source_subdir)
    if token is not None and token != current:
        raise ns_db.RevisionConflict('The destination preview changed. Refresh the preview and confirm again.')
    root = Path(destination).resolve()
    source = Path(source).resolve()
    groups = {}
    unplanned = []
    by_hash = {}
    for row in anchors:
        if row[3] in constants.ANCHOR_DELIVERED_STATUSES + ns_db.IN_REJECTS_STATUSES:
            by_hash.setdefault(row[4], row[2])
    edited = {p['photo_id'] for p in base['edited_originals']}
    planned_by_hash = {}
    # Project representatives before their duplicates, regardless of insertion order.
    for pid, src, dst, status, sha, metadata, capture in sorted(rows,key=lambda r:r[3]=='Duplicate'):
        item = dict(photo_id=pid, filename=Path(src).name, source=str(Path(src).relative_to(source)))
        reason = None
        note = 'New delivery'
        if pid in edited:
            if mode == 'copy': reason = 'Already organized; the source stays in place.'
            else: note = 'Already at destination; source removal follows your Include/Leave choice.'
        elif status == 'Duplicate':
            dst = by_hash.get(sha) or planned_by_hash.get(sha)
            if not dst: reason = 'Identical content has no delivered photo in this scope.'
            note = 'Identical copy; source stays in place.' if mode=='copy' else 'Identical source removed only after destination verification.'
        elif status not in ns_db.TRANSFER_ELIGIBLE[mode]:
            reason = 'Needs attention; no delivery is proposed.' if status=='Failed' else 'No transfer needed in this mode.'
        elif status in ns_db.IN_REJECTS_STATUSES:
            note = 'Retained in Rejects; source removed only after verification.'
        else:
            try:
                plan = metadata_import.plan(conn,pid,None,config=config,destination_root=str(root))
                dst = plan['destination'] if plan else destinations._destination_for(root,src,metadata,dst)
                if status=='Copied': note = 'Already at destination; source removed only after verification.'
                if plan and not plan.get('photo_only'): note += ' With its XMP sidecar.'
            except (ValueError,ns_db.RevisionConflict,OSError) as exc:
                reason = str(exc)
        if not reason:
            path = Path(dst) if dst else None
            if path is None or not path.is_absolute() or not path.is_relative_to(root) or '..' in path.parts:
                reason = 'No destination inside the configured destination is recorded. Run Index again.'
            else:
                name = str(path.parent.relative_to(root))
                item['note'] = note
                groups.setdefault(name,[]).append(item)
                if status != 'Duplicate': planned_by_hash.setdefault(sha,str(path))
        if reason:
            item['note'] = reason
            unplanned.append(item)
    names = sorted(groups)
    if folder is not None:
        if folder not in groups: raise ValueError('This destination folder is not in the preview.')
        items = groups[folder]
        return dict(token=current,folder=folder,total=len(items),page=file_page,
                    items=items[(file_page-1)*PAGE_SIZE:file_page*PAGE_SIZE])
    return dict(file_ids=base['file_ids'],token=current,mode=mode,total=len(rows),
        planned=sum(len(v) for v in groups.values()),group_total=len(names),page=page,page_size=PAGE_SIZE,
        groups=[dict(path=n,total=len(groups[n]),items=groups[n][:PAGE_SIZE])
                for n in names[(page-1)*PAGE_SIZE:page*PAGE_SIZE]],
        unplanned_total=len(unplanned),unplanned=unplanned[(file_page-1)*PAGE_SIZE:file_page*PAGE_SIZE])
