"""Generated orientation edits, rendering, stale confirmations and boundary refusals."""
import io
import subprocess
import time
import unittest

from PIL import Image
from engine import ns_db, xmp
from webui import photo_orientation, operation_actions
import metadata_dates_test


class OrientationMath(unittest.TestCase):
    def test_every_orientation_and_turn_matches_displayed_pixel_rotation(self):
        raw = Image.new('RGB', (3, 2))
        raw.putdata([(n*30, n*20, n*10) for n in range(6)])
        for orientation in range(1, 9):
            displayed = photo_orientation.transform(raw, 1, orientation)
            for turns in range(4):
                wanted = displayed.rotate(-90*turns, expand=True)
                actual = photo_orientation.transform(raw, 1, photo_orientation.turned(orientation, turns))
                self.assertEqual(actual.size, wanted.size)
                self.assertEqual(actual.tobytes(), wanted.tobytes(), (orientation, turns))

    def test_replacing_embedded_orientation_handles_all_mirrored_cases(self):
        raw = Image.new('RGB', (3, 2));raw.putdata([(n*30,n*20,n*10) for n in range(6)])
        for embedded in range(1, 9):
            cached = photo_orientation.transform(raw, 1, embedded)
            for effective in range(1, 9):
                actual = photo_orientation.transform(cached, embedded, effective)
                expected = photo_orientation.transform(raw, 1, effective)
                self.assertEqual((actual.size,actual.tobytes()),(expected.size,expected.tobytes()),(embedded,effective))


class RotationWrites(unittest.TestCase):
    setUp = metadata_dates_test.DateEditorTests.setUp
    run_engine = metadata_dates_test.DateEditorTests.run_engine
    conn = metadata_dates_test.DateEditorTests.conn
    setup_catalog = metadata_dates_test.DateEditorTests.setup_catalog
    client = metadata_dates_test.DateEditorTests.client

    def plan(self, client, turns=1):
        answer = client.post('/api/v1/rotations/preview', json={'rotations':[{'photo_id':self.pid,'turns':turns}]})
        self.assertEqual(answer.status_code,200,answer.text)
        item=answer.json()['items'][0]
        self.assertIsNone(item['error'],item)
        return item

    def save(self, client, plan, rid='rotation-test'):
        body={'edits':[plan['edit']], 'request_id':rid}
        answer=client.post('/api/v1/rotations/save',json=body)
        self.assertEqual(answer.status_code,202,answer.text)
        for _ in range(400):
            run=client.get(f"/api/v1/runs/{answer.json()['id']}").json()
            if run['status'] not in ('Preparing','Running','Cancelling'):return run,body
            time.sleep(.05)
        self.fail('Rotation job timed out')

    def test_sidecar_save_preserves_photo_date_and_source_then_replays(self):
        c=self.client();before=self.dest.read_bytes();source=self.sidecar.read_bytes()
        revision_before=c.get('/api/v1/photos',params={'view':'organized'}).json()['items'][0]['thumbnail_revision']
        first=self.plan(c);self.assertEqual(first['after'],6)
        run,body=self.save(c,first)
        self.assertEqual(run['status'],'Completed',run)
        revision_after=c.get('/api/v1/photos',params={'view':'organized'}).json()['items'][0]['thumbnail_revision']
        self.assertGreater(revision_after,revision_before)
        log=c.get('/api/v1/operations',params={'run':run['id']}).json()['items']
        saved=[op for op in log if op['status']=='Completed']
        self.assertTrue(saved,log)
        self.assertTrue(all(op['action']=='rotation' for op in saved),log)
        lineage=c.get(f'/api/v1/photos/{self.pid}/lineage').json()['operations']
        for op in saved:
            self.assertEqual(next(row for row in lineage if row['id']==op['id'])['action'],'rotation')
        exported=c.get('/api/v1/operations/export',params={'run':run['id'],'format':'json'}).json()
        self.assertEqual([(op['id'],op['action']) for op in exported],
                         sorted((op['id'],op['action']) for op in log))
        self.assertEqual(self.dest.read_bytes(),before)
        self.assertEqual(self.sidecar.read_bytes(),source)
        fields=xmp.parse_bytes(self.xdest.read_bytes(),source_id='check').source.fields
        self.assertEqual(fields['orientation'],'6')
        self.assertEqual(fields['date_taken'],'2005-03-04T05:06:07')
        self.assertEqual(self.plan(c,3)['after'],1)
        replay=c.post('/api/v1/rotations/save',json=body)
        self.assertEqual(replay.status_code,202,replay.text)
        self.assertEqual(replay.json()['id'],run['id'])
        with ns_db.connect(self.db) as conn:self.assertEqual(photo_orientation.state(conn,self.pid),(1,6))
        # Render from the same shared cache path without changing any cache bytes.
        cached=self.root/'cached.jpg';Image.new('RGB',(120,80),'red').save(cached)
        original=cached.read_bytes()
        with ns_db.connect(self.db) as conn:result=photo_orientation.response(conn,self.pid,cached)
        self.assertEqual(Image.open(io.BytesIO(result.body)).size,(80,120))
        self.assertEqual(cached.read_bytes(),original)

    def test_first_sidecar_writes_only_orientation(self):
        c=self.client(sidecar=False);plan=self.plan(c)
        self.assertTrue(plan['target']['create'])
        run,_=self.save(c,plan);self.assertEqual(run['status'],'Completed',run)
        self.assertEqual(xmp.parse_bytes(self.xdest.read_bytes(),source_id='check').source.fields,{'orientation':'6'})
        self.assertEqual(self.dest.read_bytes(),self.photo_bytes)

    def test_embedded_jpeg_updates_tag_and_identity_without_pixel_changes(self):
        self.sidecar.unlink()
        subprocess.run(['exiftool','-overwrite_original','-XMP:all=',str(self.photo)],check=True,capture_output=True)
        # Fixture helper enables sidecars when absent; switch the deliberate setting back.
        c=self.client(sidecar=True)
        before=self.dest.read_bytes()
        with Image.open(self.dest) as image:pixels=image.tobytes()
        plan=self.plan(c);self.assertEqual(plan['target']['kind'],'embedded_exif')
        run,_=self.save(c,plan);self.assertEqual(run['status'],'Completed',run)
        with Image.open(self.dest) as image:
            self.assertEqual(image.getexif().get(274),6)
            self.assertEqual(image.tobytes(),pixels)
        self.assertNotEqual(self.dest.read_bytes(),before)
        self.assertEqual(self.photo.read_bytes(),before)
        with ns_db.connect(self.db) as conn:self.assertEqual(photo_orientation.state(conn,self.pid),(6,6))

    def test_rejects_and_source_are_not_editable_and_zero_turn_is_no_change(self):
        c=self.client();self.assertTrue(self.plan(c,0)['no_change'])
        for status in ('Pending','Rejected','Failed'):
            with ns_db.connect(self.db) as conn:conn.execute('UPDATE photos SET status=? WHERE id=?',(status,self.pid))
            p=c.post('/api/v1/rotations/preview',json={'rotations':[{'photo_id':self.pid,'turns':1}]}).json()
            self.assertIn('organized Library',p['items'][0]['error'])
        self.assertEqual(self.xdest.read_bytes(),self.original)

    def test_stale_preview_and_extra_fields_cannot_write(self):
        c=self.client();p=self.plan(c)
        with ns_db.connect(self.db) as conn:
            conn.execute('UPDATE photo_files SET revision=revision+1 WHERE photo_id=?',(self.pid,))
        run,_=self.save(c,p)
        self.assertEqual(run['status'],'Failed',run)
        self.assertEqual(self.xdest.read_bytes(),self.original)
        p['edit']['changes']['title']='not a rotation'
        r=c.post('/api/v1/rotations/save',json={'edits':[p['edit']],'request_id':'bad-fields'})
        self.assertEqual(r.status_code,400,r.text)

    def test_existing_embedded_turn_and_sidecar_rotation_compose(self):
        subprocess.run(['exiftool','-overwrite_original','-IFD0:Orientation#=6',str(self.photo)],check=True,capture_output=True)
        c=self.client();plan=self.plan(c)
        self.assertEqual((plan['before'],plan['after']),(6,3))
        run,_=self.save(c,plan);self.assertEqual(run['status'],'Completed',run)
        with ns_db.connect(self.db) as conn:self.assertEqual(photo_orientation.state(conn,self.pid),(6,3))

    def test_motion_trailer_refusal_preserves_original_without_primary_switch(self):
        self.sidecar.unlink()
        subprocess.run(['exiftool','-overwrite_original','-XMP:all=',str(self.photo)],check=True,capture_output=True)
        self.photo.write_bytes(self.photo.read_bytes()+b'generated video trailer')
        c=self.client();before=self.dest.read_bytes()
        answer=c.post('/api/v1/rotations/preview',json={'rotations':[{'photo_id':self.pid,'turns':1}]})
        self.assertEqual(answer.status_code,200,answer.text)
        self.assertIn('JPEG trailer',answer.json()['items'][0]['error'])
        self.assertNotIn('edit',answer.json()['items'][0])
        self.assertEqual(self.dest.read_bytes(),before)
        self.assertFalse(self.xdest.exists())

    def test_invalid_shapes_and_repeated_photos_are_refused(self):
        c=self.client()
        for rotations in ([],[{'photo_id':True,'turns':1}], [{'photo_id':self.pid,'turns':-1}],
                          [{'photo_id':self.pid,'turns':90}], [{'photo_id':self.pid,'turns':1,'path':'/outside'}],
                          [{'photo_id':self.pid,'turns':1}]*2):
            r=c.post('/api/v1/rotations/preview',json={'rotations':rotations})
            self.assertEqual(r.status_code,400,r.text)
        self.assertEqual(self.xdest.read_bytes(),self.original)


if __name__=='__main__':unittest.main()


class RecordedActionTests(unittest.TestCase):
    def test_metadata_actions_are_distinguished_without_confusing_mixed_edits(self):
        cases = [({'changes':{'orientation':6}}, 'rotation'),
                 ({'changes':{'date_taken':'2020-01-02'}}, 'date'),
                 ({'remove_fields':['date_taken']}, 'date'),
                 ({'changes':{'orientation':6,'date_taken':'2020-01-02'}}, 'metadata'),
                 ({'changes':{'orientation':6},'remove_fields':['title']}, 'metadata'),
                 ({'activation':{},'changes':{'orientation':6}}, 'metadata_source'),
                 ({'primary_activation':{},'changes':{}}, 'metadata_source'),
                 ({}, 'metadata')]
        for preview, expected in cases:
            with self.subTest(preview=preview):
                self.assertEqual(operation_actions.metadata_action(preview), expected)

    def test_old_metadata_and_transfer_rows_keep_distinct_fallbacks(self):
        import sqlite3
        with sqlite3.connect(':memory:') as conn:
            conn.execute('CREATE TABLE operation_events(operation_id,step,detail_json,outcome)')
            items=[{'id':1,'mode':'METADATA'},{'id':2,'mode':'MOVE'},{'id':3,'mode':'COPY'}]
            self.assertEqual([row['action'] for row in operation_actions.annotate(conn,items)],
                             ['metadata',None,None])


    def test_date_details_require_verified_save_not_intent_or_success_label(self):
        import json
        import sqlite3
        with sqlite3.connect(':memory:') as conn:
            conn.execute('CREATE TABLE operation_events(operation_id,step,detail_json,outcome)')
            preview={'changes':{'date_taken':'2399-01-01'},
                     'target':{'source_id':'exif','kind':'embedded_exif'},
                     'sources_before':{'exif':{'fields':{}}}}
            for i in (1,2,3):
                conn.execute('INSERT INTO operation_events VALUES(?,?,?,?)',
                    (i,'intent',json.dumps({'kind':'metadata_edit','expected':{'preview':preview}}),'planned'))
            # Even a failed relocation can have a verified metadata write. Conversely,
            # a completed/skipped label alone does not prove anything was written.
            receipt=json.dumps({'sources':{'exif':{'fields':{'date_taken':'2020-02-03T04:05:06'}}}})
            conn.execute('INSERT INTO operation_events VALUES(?,?,?,?)',(1,'metadata_saved',receipt,'verified'))
            conn.execute('INSERT INTO operation_events VALUES(?,?,?,?)',(2,'metadata_saved',receipt,'failed'))
            result=operation_actions.annotate(conn,[{'id':i,'mode':'METADATA','status':status}
                for i,status in ((1,'Failed'),(2,'Failed'),(3,'Completed'))])
            self.assertEqual(result[0]['date_change'],{'target':'embedded_exif',
                'before':{'present':False,'value':None},
                'after':{'present':True,'value':'2020-02-03T04:05:06'}})
            self.assertIsNone(result[1]['date_change'])
            self.assertIsNone(result[2]['date_change'])
