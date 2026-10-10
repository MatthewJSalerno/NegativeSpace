"""Verified embedded-primary activation. Metadata bytes and alternatives stay intact."""
from datetime import datetime
import json
from pathlib import Path

from engine import constants, metadata_photo_save, metadata_save, ns_db


def execute(conn, op, pid, m):
    photo=metadata_photo_save._catalog_photo(conn,pid,op,m)
    preview=m['preview'];chosen=preview['primary_activation']['primary_id']
    saved=metadata_save._event(conn,op,'metadata_saved')
    if not saved:
        metadata_photo_save._verify(m,photo,m['sha1'])
        if preview['primary_before']==chosen and not preview['filing']['change']:
            return metadata_save._finish(conn,op,'no_change')
        metadata=json.loads(conn.execute('SELECT metadata_json FROM photos WHERE id=?',(pid,)).fetchone()[0] or '{}')
        fields=preview['after']['proposed_effective'];date=fields.get('date_taken','')
        if len(date)>=10:
            metadata.update(date_taken=date,date_source='exif' if chosen=='exif' else 'xmp')
        else:
            mtime=conn.execute('SELECT file_mtime FROM source_snapshots WHERE file_id=?',(m['file_id'],)).fetchone()[0]
            metadata.update(date_taken=datetime.fromtimestamp(mtime).isoformat(),date_source=constants.DATE_SOURCE_MTIME)
        receipt=dict(sources=preview['sources_before'],primary_id=chosen,resolution=preview['after'],metadata=metadata,
            sha1_hash=m['sha1'],destination_root=m['root'],file_id=m['file_id'],retained_id=m['retained_id'],
            differences=preview['differences'],primary_only=True)
        previous=metadata_save.active(conn,pid)
        if previous and previous.get('content_changed'):
            receipt.update({key:previous[key] for key in ('content_changed','file_size','file_mtime','phash','width','height')})
        with ns_db.transaction(conn):
            value=dict(file_id=m['file_id'],primary_id=chosen,capture_id=preview['binding']['capture_id'],
                resolution=preview['after'],filing_operation_id=op,established_by_operation=op)
            revision=conn.execute('INSERT INTO metadata_decisions(kind,scope,capture_id,request_id,request_json,value_json,created_at) '
                "VALUES('primary',?,?,?,?,?,?)",(str(m['file_id']),preview['binding']['capture_id'],f'metadata:{op}:primary',
                json.dumps({'operation_id':op}),json.dumps(value),ns_db.utc_now())).lastrowid
            receipt['primary_revision']=revision
            ns_db.advance_revision(conn,pid,metadata_photo_save._revision(conn,op,m))
            conn.execute('UPDATE photos SET metadata_json=? WHERE id=?',(json.dumps(metadata),pid))
            ns_db.record_event(conn,operation_id=op,step='metadata_saved',outcome='verified',detail=receipt)
            ns_db.record_evidence(conn,operation_id=op,file_id=m['retained_id'],location_role='destination',
                observed_path=str(photo),observation_kind='sha1',result='match',details={'sha1':m['sha1'],'metadata_bytes_unchanged':True})
            if m['sidecar_receipt']:
                side=m['sidecar_receipt']
                ns_db.record_event(conn,operation_id=op,step='pair_complete',outcome='verified',
                    detail=dict(receipt,xmp_sha256=side['sha256'],version_id=side['version_id']))
    metadata_photo_save._refile(conn,op,pid,m,{'after_sha1':m['sha1']})
    photo=metadata_photo_save._catalog_photo(conn,pid,op,m)
    metadata_photo_save._verify(m,photo,m['sha1'])
    return metadata_save._finish(conn,op)


def check(conn, op, pid, m):
    photo=metadata_photo_save._catalog_photo(conn,pid,op,m)
    candidates={str(photo),m['proposed']}
    found=[path for path in candidates if metadata_photo_save._hash(m,path)==m['sha1']]
    if not found:
        raise ValueError('The recorded photo is missing or changed; restore storage access before retrying the primary switch')
    for path in found:metadata_photo_save._sidecar(m,path)
    saved=bool(metadata_save._event(conn,op,'metadata_saved'))
    message=('Primary choice is recorded; retry its remaining date move.' if saved else
             'Photo metadata is unchanged; retry the primary switch or discard the request.')
    metadata_save._failure(conn,op,m,message)
    return {'resolved':False,'message':message}
