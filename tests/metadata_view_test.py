"""Generated catalog tests for source identity, immutable reads and applied primary."""
import json
from engine import ns_db, xmp_store
from webui_api_test import ApiCase


class MetadataViewTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.create_catalog()
        with ns_db.connect(self.cfg.db_path, synchronous="FULL") as conn:
            self.run = ns_db.create_run(conn, mode='INDEX', source=str(self.cfg.source), destination=str(self.cfg.dest))[0]
            with ns_db.transaction(conn):
                self.pid = conn.execute("INSERT INTO photos(source_path,sha1_hash,status) VALUES(?,?,'Pending')",
                    (str(self.cfg.source/'generated.jpg'),'a'*40)).lastrowid
                self.fid = ns_db.record_source_observation(conn,photo_id=self.pid,run_id=self.run,
                    source_path=str(self.cfg.source/'generated.jpg'),sha1_hash='a'*40,file_size=10,
                    file_mtime=1,birthtime=None,metadata={},error=None)
                data = b'<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:exif="http://ns.adobe.com/exif/1.0/"><rdf:RDF><rdf:Description exif:DateTimeOriginal=""/></rdf:RDF></x:xmpmeta>'
                xmp_store.retain_capture(conn,data=data,run_id=self.run,source_relative_path='generated.jpg.xmp',file_ids=[self.fid])
                self.vid,self.sha = conn.execute('SELECT version_id,sha256 FROM xmp_versions').fetchone()
                self.sources = {'exif':{'kind':'embedded_exif','fields':{'date_taken':'2001-02-03T04:05:06','rating':0}},
                    'embedded_xmp':{'kind':'embedded_xmp','fields':{'title':'<script>alert(1)</script>'}},
                    'sidecar:generated.jpg.xmp':{'kind':'sidecar_xmp','fields':{'date_taken':''}}}
                self.report = dict(sources=self.sources,issues=[],sidecars=[{'path':'generated.jpg.xmp','sha256':self.sha}])
                self.capture = conn.execute('INSERT INTO metadata_captures(run_id,file_id,source_relative_path,catalog_sha1,embedded_json,report_json,observed_at) VALUES(?,?,?,?,?,?,?)',
                    (self.run,self.fid,'generated.jpg','a'*40,json.dumps({'tags':{'ExifIFD:DateTimeOriginal':'2001:02:03 04:05:06','XMP-dc:Title':'<script>alert(1)</script>'}}),json.dumps(self.report),ns_db.utc_now())).lastrowid

    def get(self):
        response = self.client.get(f'/api/v1/photos/{self.pid}/metadata')
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def activate(self, sources=None, primary='sidecar:generated.jpg.xmp', digest='a'*40):
        with ns_db.connect(self.cfg.db_path) as conn, ns_db.transaction(conn):
            op = ns_db.begin_operation(conn,run_id=self.run,photo_id=self.pid,source_path='generated.jpg',dest_path=None,kind='metadata_edit')
            ns_db.record_event(conn,operation_id=op,step='metadata_saved',outcome='verified',detail=dict(
                capture_id=self.capture, sources=sources or self.sources,primary_id=primary,
                sha1_hash=digest,version_id=self.vid))

    def test_capture_does_not_invent_primary_and_separates_embedded_sources(self):
        result=self.get()
        self.assertIsNone(result['primary_id'])
        self.assertFalse(result['applied'])
        exif=next(s for s in result['sources'] if s['id']=='exif')
        self.assertEqual(exif['fields']['rating'],0)
        self.assertNotIn('XMP-dc:Title',exif['tags'])
        self.assertEqual(next(s for s in result['sources'] if s['kind']=='sidecar_xmp')['fields']['date_taken'],'')

    def test_applied_primary_and_saved_values_win_without_writes(self):
        self.sources['exif']['fields']['date_taken']='2020-01-01T12:34:56'
        self.activate(primary='exif')
        with ns_db.connect(self.cfg.db_path, synchronous="FULL") as conn:
            before=''.join(conn.iterdump())
        result=self.get()
        self.assertEqual(result['primary_id'],'exif')
        self.assertEqual(result['sources'][0]['fields']['date_taken'],'2020-01-01T12:34:56')
        with ns_db.connect(self.cfg.db_path, synchronous="FULL") as conn:
            self.assertEqual(before,''.join(conn.iterdump()))
        self.assertNotIn('payload',str(result))
        self.assertNotIn('original_base64',str(result))

    def test_sidecar_primary_identifies_retained_version(self):
        self.activate()
        self.assertEqual(self.get()['primary_id'],f'xmp:{self.vid}')

    def test_pending_decision_is_not_primary(self):
        with ns_db.connect(self.cfg.db_path) as conn, ns_db.transaction(conn):
            conn.execute("INSERT INTO metadata_decisions(kind,scope,capture_id,request_id,request_json,value_json,created_at) VALUES('primary',?,?,?,'{}',?,?)",
                (str(self.fid),self.capture,'pending',json.dumps({'primary_id':'exif'}),ns_db.utc_now()))
        self.assertIsNone(self.get()['primary_id'])

    def test_content_mismatch_does_not_claim_current_primary(self):
        self.activate(digest='b'*40)
        result=self.get()
        self.assertIsNone(result['primary_id'])
        self.assertEqual(result['issues'][0]['code'],'content_changed')

    def test_missing_photo_and_oversized_identifiers(self):
        for ident in (0,-1,999999,2**63):
            self.assertEqual(self.client.get(f'/api/v1/photos/{ident}/metadata').status_code,404)

    def test_unreadable_capture_is_not_reported_as_empty(self):
        self.report['issues']=[{'source':'photo','code':'qualified_reader_failed'}]
        self.report['sources']={}
        with ns_db.connect(self.cfg.db_path) as conn:
            run=ns_db.create_run(conn, mode='INDEX',source=str(self.cfg.source),destination=str(self.cfg.dest))[0]
            conn.execute('INSERT INTO metadata_captures(run_id,file_id,source_relative_path,catalog_sha1,embedded_json,report_json,observed_at) VALUES(?,?,?,?,?,?,?)',
                (run,self.fid,'generated.jpg','a'*40,'{}',json.dumps(self.report),ns_db.utc_now()))
        self.assertEqual(self.get()['sources'][0]['issues'][0]['code'],'qualified_reader_failed')

    def test_later_index_does_not_replace_activated_snapshot(self):
        self.activate(primary='exif')
        with ns_db.connect(self.cfg.db_path) as conn:
            run=ns_db.create_run(conn,mode='INDEX',source=str(self.cfg.source),destination=str(self.cfg.dest))[0]
            self.report['sources']['exif']['fields']['date_taken']='2099-01-01T00:00:00'
            conn.execute('INSERT INTO metadata_captures(run_id,file_id,source_relative_path,catalog_sha1,embedded_json,report_json,observed_at) VALUES(?,?,?,?,?,?,?)',
                (run,self.fid,'generated.jpg','a'*40,'{}',json.dumps(self.report),ns_db.utc_now()))
        self.assertEqual(self.get()['sources'][0]['fields']['date_taken'],'2001-02-03T04:05:06')

    def test_verified_default_read_priority_has_primary_without_deliberate_choice(self):
        with ns_db.connect(self.cfg.db_path) as conn, ns_db.transaction(conn):
            op=ns_db.begin_operation(conn,run_id=self.run,photo_id=self.pid,source_path='generated.jpg',dest_path=None,kind='copy')
            ns_db.record_event(conn,operation_id=op,step='photo_metadata_activated',outcome='verified',detail=dict(
                capture_id=self.capture,sources=self.sources,primary_id=None,sha1_hash='a'*40,
                resolution={'proposed_primary':'exif'}))
        self.assertEqual(self.get()['primary_id'],'exif')

    def test_retained_sidecar_dates_use_canonical_comparison_without_blob_reads(self):
        data=b'<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:exif="http://ns.adobe.com/exif/1.0/"><rdf:RDF><rdf:Description exif:DateTimeOriginal="2020-01-02T03:04:05Z"/></rdf:RDF></x:xmpmeta>'
        with ns_db.connect(self.cfg.db_path,synchronous='FULL') as conn, ns_db.transaction(conn):
            xmp_store.retain_capture(conn,data=data,run_id=self.run,source_relative_path='alternative.xmp',file_ids=[self.fid])
        values=[s['fields'].get('date_taken') for s in self.get()['sources'] if s['kind']=='sidecar_xmp']
        self.assertIn('2020-01-02T03:04:05+00:00',values)

    def test_unretained_unreadable_sidecar_is_not_reported_as_missing(self):
        self.report['issues']=[{'source':'sidecar:broken.jpg.xmp','code':'read_error'}]
        self.report['sidecars'].append({'path':'broken.jpg.xmp','state':'needs_attention'})
        with ns_db.connect(self.cfg.db_path) as conn:
            run=ns_db.create_run(conn,mode='INDEX',source=str(self.cfg.source),destination=str(self.cfg.dest))[0]
            conn.execute('INSERT INTO metadata_captures(run_id,file_id,source_relative_path,catalog_sha1,embedded_json,report_json,observed_at) VALUES(?,?,?,?,?,?,?)',
                (run,self.fid,'generated.jpg','a'*40,'{}',json.dumps(self.report),ns_db.utc_now()))
        sources=self.get()['sources']
        unavailable=[s for s in sources if s['kind']=='sidecar_xmp' and not s['available']]
        self.assertEqual(len(unavailable),1)
        self.assertEqual(unavailable[0]['issues'][0]['code'],'read_error')
        self.assertTrue(any(s['kind']=='sidecar_xmp' and s['available'] for s in sources))

    def test_malformed_retained_sidecar_has_empty_tag_object_and_error(self):
        data=b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:'
        with ns_db.connect(self.cfg.db_path,synchronous='FULL') as conn, ns_db.transaction(conn):
            xmp_store.retain_capture(conn,data=data,run_id=self.run,source_relative_path='malformed.xmp',file_ids=[self.fid])
        broken=next(s for s in self.get()['sources'] if s['kind']=='sidecar_xmp' and not s['available'])
        self.assertEqual(broken['tags'],{})
        self.assertEqual(broken['fields'],{})
        self.assertEqual(broken['issues'][0]['code'],'malformed_xml')

    def test_source_attention_has_path_explanation_and_clears_on_reindex(self):
        def capture(report):
            with ns_db.connect(self.cfg.db_path) as conn:
                run=ns_db.create_run(conn,mode='INDEX',source=str(self.cfg.source),destination=str(self.cfg.dest))[0]
                conn.execute('INSERT INTO metadata_captures(run_id,file_id,source_relative_path,catalog_sha1,embedded_json,report_json,observed_at) VALUES(?,?,?,?,?,?,?)',
                    (run,self.fid,'generated.jpg','a'*40,'{}',json.dumps(report),ns_db.utc_now()))
        broken=dict(self.report,state='needs_attention',issues=[{'source':'sidecar:generated.jpg.xmp','code':'malformed_xml','detail':'unclosed token'}])
        capture(broken)
        page=self.client.get('/api/v1/photos?view=unorganized').json()
        note=next(p for p in page['items'] if p['id']==self.pid)['metadata_attention']
        self.assertEqual(note['issues'][0]['files'],['generated.jpg.xmp'])
        self.assertIn('malformed XML',note['issues'][0]['reason'])
        self.assertIn('Index again',note['action'])
        self.assertEqual(page['index_summary']['metadata_held'],1)
        self.assertEqual(page['index_summary']['ready'],0)
        detail=self.client.get(f'/api/v1/photos/{self.pid}/inspect').json()
        self.assertEqual(detail['metadata_attention'],note)
        capture(dict(self.report,state='captured',issues=[]))
        page=self.client.get('/api/v1/photos?view=unorganized').json()
        self.assertEqual(page['index_summary']['metadata_held'],0)
        self.assertEqual(page['index_summary']['ready'],1)
        self.assertIsNone(page['items'][0]['metadata_attention'])
        # Source observations never mark an organized photo as a held import.
        capture(broken)
        with ns_db.connect(self.cfg.db_path) as conn:
            conn.execute("UPDATE photos SET status='Copied' WHERE id=?",(self.pid,))
        self.assertIsNone(self.client.get(f'/api/v1/photos/{self.pid}/inspect').json()['metadata_attention'])
