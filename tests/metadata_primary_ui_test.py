"""Primary-source API previews and real engine jobs on generated photos."""
import time
import unittest
from engine import ns_db, xmp_store
import metadata_index_test
import metadata_dates_test


class PrimaryUI(unittest.TestCase):
    setUp = metadata_dates_test.DateEditorTests.setUp
    run_engine = metadata_dates_test.DateEditorTests.run_engine
    conn = metadata_dates_test.DateEditorTests.conn
    setup_catalog = metadata_dates_test.DateEditorTests.setup_catalog
    client = metadata_dates_test.DateEditorTests.client

    def plan(self, client, source):
        view = client.get(f'/api/v1/photos/{self.pid}/metadata').json()
        return client.post(f'/api/v1/photos/{self.pid}/primary-preview', json={
            'source_id':source, 'capture_id':view['capture_id']})

    def save(self, client, plan, request_id):
        body = {'edit':plan['edit'], 'token':plan['token'], 'request_id':request_id}
        response = client.post(f'/api/v1/photos/{self.pid}/primary-save', json=body)
        self.assertEqual(response.status_code, 202, response.text)
        run = response.json()
        for _ in range(300):
            run = client.get(f"/api/v1/runs/{run['id']}").json()
            if run['status'] not in ('Preparing','Running','Cancelling'):
                return run, body
            time.sleep(.05)
        self.fail('Primary job did not finish')

    def test_switch_both_directions_refiles_and_preserves_sources(self):
        c = self.client()
        view = c.get(f'/api/v1/photos/{self.pid}/metadata').json()
        sidecar = view['primary_id']
        plan = self.plan(c, 'exif')
        self.assertEqual(plan.status_code, 200, plan.text)
        plan = plan.json()
        self.assertEqual(plan['before']['date_taken'], '2005-03-04T05:06:07')
        self.assertEqual(plan['after']['date_taken'], '1999-01-02T03:04:05')
        self.assertTrue(plan['filing']['change'])
        self.assertEqual(self.dest.read_bytes(), self.photo_bytes)
        self.assertEqual(self.xdest.read_bytes(), self.original)
        run, body = self.save(c, plan, 'primary-exif')
        self.assertEqual((run['status'], run['outcome']['succeeded']), ('Completed',1), run)
        new = self.root/'dest'/plan['filing']['proposed']
        self.assertEqual(new.read_bytes(), self.photo_bytes)
        self.assertEqual(new.with_name(new.name+'.xmp').read_bytes(), self.original)
        self.assertEqual(c.get(f'/api/v1/photos/{self.pid}/metadata').json()['primary_id'], 'exif')
        self.assertEqual(c.post(f'/api/v1/photos/{self.pid}/primary-save',json=body).json()['id'],run['id'])
        other = self.plan(c, 'embedded_xmp').json()
        self.assertEqual(self.save(c,other,'primary-embedded')[0]['status'],'Completed')
        back = self.plan(c, sidecar)
        self.assertEqual(back.status_code,200,back.text)
        self.assertEqual(self.save(c,back.json(),'primary-sidecar')[0]['status'],'Completed')
        self.assertEqual(c.get(f'/api/v1/photos/{self.pid}/metadata').json()['primary_id'],sidecar)
        self.assertEqual(self.photo.read_bytes(),self.photo_bytes)
        self.assertEqual(self.sidecar.read_bytes(),self.original)
        self.assertEqual(self.dest.read_bytes(),self.photo_bytes)

    def test_refuses_absent_same_source_bad_capture_and_other_edits(self):
        c = self.client()
        view = c.get(f'/api/v1/photos/{self.pid}/metadata').json()
        for source in (view['primary_id'], '../not-a-source', 'xmp:999999'):
            self.assertEqual(self.plan(c,source).status_code,400)
        self.assertEqual(c.post(f'/api/v1/photos/{self.pid}/primary-preview',json={
            'source_id':'exif','capture_id':True}).status_code,409)
        plan = self.plan(c,'exif').json()
        for edit in ({'photo_id':self.pid,'capture_id':self.capture,'changes':{'rating':'4'}},
                     {**plan['edit'],'photo_id':self.pid+1}, {**plan['edit'],'path':'/outside'}):
            self.assertEqual(c.post(f'/api/v1/photos/{self.pid}/primary-save',json={
                'edit':edit,'token':plan['token'],'request_id':'invalid-primary'}).status_code,400)
        self.assertEqual(self.xdest.read_bytes(),self.original)

    def test_stale_preview_does_not_change_primary_or_files(self):
        c = self.client(); plan = self.plan(c,'exif').json()
        with ns_db.connect(self.db) as conn:
            ns_db.save_settings(conn,{'metadata_write_non_raw':'xmp'},expected_revisions={'metadata_write_non_raw':0})
        run,_ = self.save(c,plan,'stale-primary')
        self.assertEqual(run['status'],'Failed',run)
        self.assertEqual(self.dest.read_bytes(),self.photo_bytes)
        self.assertEqual(self.xdest.read_bytes(),self.original)
        self.assertNotEqual(c.get(f'/api/v1/photos/{self.pid}/metadata').json()['primary_id'],'exif')

    def test_source_and_rejected_photos_refused(self):
        c = self.client()
        for status in ('Pending','Rejected_Copied'):
            with ns_db.connect(self.db) as conn:
                conn.execute('UPDATE photos SET status=? WHERE id=?',(status,self.pid))
            self.assertEqual(self.plan(c,'exif').status_code,400)
        self.assertEqual(self.xdest.read_bytes(),self.original)

    def test_collision_fails_without_overwriting_or_changing_primary(self):
        c = self.client(); plan = self.plan(c,'exif').json()
        occupied=self.root/'dest'/plan['filing']['proposed']
        occupied.parent.mkdir(parents=True,exist_ok=True);occupied.write_bytes(b'other file')
        run,_=self.save(c,plan,'collision-primary')
        self.assertEqual(run['status'],'Failed',run)
        self.assertEqual(occupied.read_bytes(),b'other file')
        self.assertEqual(self.dest.read_bytes(),self.photo_bytes)
        self.assertEqual(self.xdest.read_bytes(),self.original)
        self.assertNotEqual(c.get(f'/api/v1/photos/{self.pid}/metadata').json()['primary_id'],'exif')

    def test_candidate_only_sidecar_is_not_authorized_by_visibility(self):
        c=self.client()
        with ns_db.connect(self.db, synchronous='FULL') as conn:
            file_id=conn.execute('SELECT file_id FROM photo_files WHERE photo_id=?',(self.pid,)).fetchone()[0]
            run=ns_db.create_run(conn,mode='INDEX',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
            with ns_db.transaction(conn):
                retained=xmp_store.retain_capture(conn,data=metadata_index_test.packet('2018-01-02'),run_id=run,
                    source_relative_path='unassigned.xmp',file_ids=[file_id],role='candidate',basis='unresolved')
        refused=self.plan(c,'xmp:'+str(retained['version_id']))
        self.assertEqual(refused.status_code,400,refused.text)
        self.assertIn('no confirmed association',refused.text)
        self.assertEqual(self.xdest.read_bytes(),self.original)

    def test_saved_first_sidecar_can_become_primary_again(self):
        c=self.client(sidecar=False)
        date=metadata_dates_test.DateEditorTests.plan(self,c,'2017-03-04T05:06:07').json()
        run,_=metadata_dates_test.DateEditorTests.save(self,c,date)
        self.assertEqual(run['status'],'Completed',run)
        view=c.get(f'/api/v1/photos/{self.pid}/metadata').json()
        version=view['primary_id']
        self.assertEqual(self.save(c,self.plan(c,'exif').json(),'saved-side-exif')[0]['status'],'Completed')
        plan=self.plan(c,version)
        self.assertEqual(plan.status_code,200,plan.text)
        self.assertEqual(self.save(c,plan.json(),'saved-side-back')[0]['status'],'Completed')
        self.assertEqual(c.get(f'/api/v1/photos/{self.pid}/metadata').json()['primary_id'],version)

    def test_reindex_uses_latest_binding_but_keeps_verified_source_values(self):
        c=self.client()
        first=self.plan(c,'exif').json()
        self.assertEqual(self.save(c,first,'before-reindex')[0]['status'],'Completed')
        self.run_engine('--force-rehash')
        with ns_db.connect(self.db) as conn:
            latest=conn.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        view=c.get(f'/api/v1/photos/{self.pid}/metadata').json()
        self.assertEqual(view['capture_id'],latest)
        self.assertEqual(view['primary_id'],'exif')
        planned=self.plan(c,'embedded_xmp')
        self.assertEqual(planned.status_code,200,planned.text)
        self.assertEqual(planned.json()['before']['date_taken'],'1999-01-02T03:04:05')
        self.assertEqual(self.save(c,planned.json(),'after-reindex')[0]['status'],'Completed')
