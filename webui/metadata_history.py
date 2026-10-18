"""Read-only history of explicit import choices and their verified application.

Saved decisions are not file operations. Keep them out of job outcomes/exports,
while exposing the same bounded history in Logs and photo lineage.
"""
import json

from . import catalog, metadata_view


_SCOPE = """WITH RECURSIVE related_photos AS (
 SELECT id FROM photos WHERE id=:photo OR (:photo IS NOT NULL AND sha1_hash IS NOT NULL
 AND sha1_hash!='' AND sha1_hash=(SELECT sha1_hash FROM photos WHERE id=:photo))
), related_files(file_id) AS (
 SELECT file_id FROM photo_files WHERE photo_id IN (SELECT id FROM related_photos)
 UNION SELECT f.file_id FROM file_origins f JOIN related_files t ON f.origin_file_id=t.file_id
) """


# Older verified receipts have owners but no association revision. Reconstruct only
# from that job's frozen decision high-water mark, never today's latest choice.
_ASSOCIATION_REVISIONS = """SELECT COALESCE(json_extract(v.value,'$.association_revision'),
 (SELECT MAX(d.decision_id) FROM metadata_decisions d WHERE d.kind='association'
  AND d.scope='[' || json_quote(json_extract(e.detail_json,'$.source_root')) || ', ' || json_quote(json_extract(v.value,'$.path')) || ']'
  AND d.decision_id <= (SELECT json_extract(effective_config_json,'$.metadata_decision_highwater')
                       FROM run_configs WHERE run_id=o.run_id)))
 FROM json_each(e.detail_json,'$.versions') v"""
_OWNERS_MATCH = """EXISTS (SELECT 1 FROM json_each(e.detail_json,'$.versions') v
 WHERE json_extract(used.value_json,'$.root')=json_extract(e.detail_json,'$.source_root')
 AND json_extract(used.value_json,'$.sidecar')=json_extract(v.value,'$.path')
 AND (SELECT COUNT(*) FROM json_each(used.value_json,'$.owners'))=(SELECT COUNT(*) FROM json_each(v.value,'$.owners'))
 AND NOT EXISTS (SELECT 1 FROM json_each(used.value_json,'$.owners') owner
                 WHERE NOT EXISTS (SELECT 1 FROM json_each(v.value,'$.owners') actual
                                   WHERE actual.key=owner.key AND actual.value=owner.value)))"""
_USED = ("json_extract(used.request_json,'$.kind')=used.kind AND "
         "(used.decision_id=json_extract(e.detail_json,'$.primary_revision') OR (used.decision_id IN ("
         + _ASSOCIATION_REVISIONS + ") AND " + _OWNERS_MATCH + "))")


def list_history(db_path, *, photo=None, runs=None, statuses=None, q=None, since=None,
                 until=None, page=1, page_size=20):
    if page < 1 or not 1 <= page_size <= 100:
        raise ValueError('Invalid metadata history page')
    params = {'photo':photo, 'since':since, 'until':until,
              'query': '%' + (q or '').replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%',
              'limit':page_size, 'offset':(page-1)*page_size}
    saved = ["json_extract(d.request_json,'$.kind')=d.kind", "d.kind IN ('association','primary')"]
    applied = ["e.step='metadata_activated'", "e.outcome='completed'",
        "EXISTS (SELECT 1 FROM metadata_decisions used WHERE " + _USED + ")"]
    if photo is not None:
        saved.append("""(m.file_id IN (SELECT file_id FROM related_files) OR
          (d.kind='association' AND EXISTS (
            SELECT 1 FROM json_each(m.report_json,'$.sidecars') side,
            json_each(COALESCE(json_extract(side.value,'$.all_candidates'),json_extract(side.value,'$.candidates'))) candidate
            JOIN source_snapshots snap ON snap.source_path=rtrim(capture_run.source_path,'/') || '/' || candidate.value
            WHERE json_extract(side.value,'$.path')=json_extract(d.value_json,'$.sidecar')
              AND snap.file_id IN (SELECT file_id FROM related_files))))""")
        applied.append("o.id IN (SELECT id FROM operations WHERE photo_id IN (SELECT id FROM related_photos) "
                       "UNION SELECT operation_id FROM operation_files WHERE file_id IN (SELECT file_id FROM related_files))")
    if runs or statuses:
        saved.append('0')  # A saved choice has neither a job nor a file outcome.
    for label, values, column in [('run',runs,'o.run_id'),('status',statuses,catalog._OP_STATUS)]:
        if values:
            names=[]
            for i,value in enumerate(values):
                key=f'{label}{i}'; params[key]=value; names.append(':'+key)
            applied.append(f"{column} IN ({','.join(names)})")
    if since:
        saved.append('d.created_at>=:since'); applied.append('e.timestamp>=:since')
    if until:
        saved.append('d.created_at<:until'); applied.append('e.timestamp<:until')
    if q:
        saved.append("(m.source_relative_path LIKE :query ESCAPE '\\' OR d.value_json LIKE :query ESCAPE '\\')")
        applied.append("(o.source_path LIKE :query ESCAPE '\\' OR o.dest_path LIKE :query ESCAPE '\\' OR e.detail_json LIKE :query ESCAPE '\\')")
    sql = _SCOPE + """, history AS (
 SELECT 'choice:' || d.decision_id AS id,d.decision_id AS ordinal,'saved' AS stage,
 d.kind,d.created_at AS timestamp,m.source_relative_path AS filename,pf.photo_id,
 NULL AS run_id,NULL AS mode,d.value_json AS detail,d.decision_id AS revision
 FROM metadata_decisions d JOIN metadata_captures m ON m.capture_id=d.capture_id
 JOIN runs capture_run ON capture_run.id=m.run_id LEFT JOIN photo_files pf ON pf.file_id=m.file_id
 WHERE """ + ' AND '.join(saved) + """
 UNION ALL
 SELECT 'applied:' || e.event_id,e.event_id,'applied','primary',e.timestamp,
 o.source_path,o.photo_id,o.run_id,r.mode,e.detail_json,json_extract(e.detail_json,'$.primary_revision')
 FROM operation_events e JOIN operations o ON o.id=e.operation_id JOIN runs r ON r.id=o.run_id
 WHERE """ + ' AND '.join(applied) + ') '
    with catalog.connect(db_path) as conn:
        conn.execute('BEGIN')
        total=conn.execute(sql+'SELECT COUNT(*) FROM history',params).fetchone()[0]
        rows=conn.execute(sql+'SELECT * FROM history ORDER BY timestamp DESC,stage,ordinal DESC LIMIT :limit OFFSET :offset',params).fetchall()
        details=[json.loads(row['detail']) for row in rows]
        event_ids=[int(row['id'].split(':')[1]) for row in rows if row['stage']=='applied']
        applied_choices={}
        if event_ids:
            for event_id,revision in conn.execute(
                    "SELECT e.event_id,used.decision_id FROM operation_events e "
                    "JOIN operations o ON o.id=e.operation_id JOIN metadata_decisions used ON " + _USED +
                    f" WHERE e.event_id IN ({','.join('?' for _ in event_ids)}) ORDER BY used.decision_id",event_ids):
                applied_choices.setdefault('applied:'+str(event_id),[]).append(revision)
    items=[]
    for row,detail in zip(rows,details):
        used=applied_choices.get(row['id'],[])
        primary=detail.get('primary_id')
        owners=sorted(detail.get('owners',{}))
        items.append(dict(id=row['id'],stage=row['stage'],kind=row['kind'],timestamp=row['timestamp'],
            filename=catalog._basename(row['filename']),photo_id=row['photo_id'],run_id=row['run_id'],mode=row['mode'],
            revision=row['revision'] if row['stage']=='saved' or row['revision'] in used else None,
            applied_choices=used,primary=primary,sidecar=detail.get('sidecar'),owners=owners,
            date_taken=detail.get('resolution',{}).get('proposed_effective',{}).get('date_taken')))
    return dict(items=items,total=total,page=page,page_size=page_size)


def compare_choice(db_path, photo_id, revision):
    """Compare captured choice evidence with the photo's currently recorded primary.

    Neither source files nor archived blobs are read. Bind the requested photo to
    the choice's captured file or shared-sidecar candidates before exposing values.
    """
    with catalog.connect(db_path) as conn:
        conn.execute('BEGIN')
        row = conn.execute(_SCOPE + """
            SELECT d.kind,d.value_json,d.created_at,m.report_json
            FROM metadata_decisions d JOIN metadata_captures m ON m.capture_id=d.capture_id
            JOIN runs r ON r.id=m.run_id
            WHERE d.decision_id=:revision AND d.kind IN ('association','primary')
            AND json_extract(d.request_json,'$.kind')=d.kind
            AND (m.file_id IN (SELECT file_id FROM related_files) OR
                (d.kind='association' AND EXISTS (
                    SELECT 1 FROM json_each(m.report_json,'$.sidecars') side,
                    json_each(COALESCE(json_extract(side.value,'$.all_candidates'),
                                       json_extract(side.value,'$.candidates'))) candidate
                    JOIN source_snapshots snap ON snap.source_path=rtrim(r.source_path,'/') || '/' || candidate.value
                    WHERE json_extract(side.value,'$.path')=json_extract(d.value_json,'$.sidecar')
                    AND snap.file_id IN (SELECT file_id FROM related_files))))
            """, {'photo':photo_id,'revision':revision}).fetchone()
        if not row:
            return None
        view = metadata_view.inspect_connection(conn, photo_id)
        if view is None:
            return None
        decision, report = json.loads(row['value_json']), json.loads(row['report_json'])
        source_id = ('sidecar:' + decision['sidecar'] if row['kind']=='association'
                     else decision.get('primary_id'))
        source = report.get('sources', {}).get(source_id)
        observed = next((s for s in report.get('sidecars', [])
                         if 'sidecar:'+s['path']==source_id), {})
        primary = next((s for s in view['sources'] if s['id']==view['primary_id']), None)
        related = {r[0] for r in conn.execute(_SCOPE + 'SELECT file_id FROM related_files', {'photo':photo_id})}
        photo = conn.execute('SELECT source_path,dest_path FROM photos WHERE id=?', (photo_id,)).fetchone()
        owners = decision.get('owners', {})
        return dict(photo_id=photo_id, filename=catalog._basename(photo['dest_path'] or photo['source_path']),
                    revision=revision, saved_at=row['created_at'],
                    owners=sorted(owners), assigned_to_photo=(bool(related.intersection(owners.values()))
                        if row['kind']=='association' else None),
                    historical=dict(label=source_id.removeprefix('sidecar:') if source_id else 'Unknown source',
                        fields=source.get('fields', {}) if source else {}, available=source is not None,
                        sha256=observed.get('sha256')),
                    primary=primary, notice=view['notice'], issues=view['issues'])
