"""Source XMP choices through HTTP and the locked engine; generated files only."""
from pathlib import Path
import json
import unittest
from fastapi.testclient import TestClient
from PIL import Image
from engine import ns_db, metadata_edits
from webui import app as webapp
from webui.config import Config
import metadata_index_test


class ImportChoices(unittest.TestCase):
    setUp=metadata_index_test.IndexTests.setUp
    run_engine=metadata_index_test.IndexTests.run_engine
    conn=metadata_index_test.IndexTests.conn

    def setup_choice(self, versions=False):
        self.sidecar.rename(self.root/'source/photo.xmp')
        if versions:
            (self.root/'source/photo.XMP').write_bytes(metadata_index_test.packet('2012-06-07T08:09:10'))
        else:
            Image.new('RGB',(40,31),(80,50,90)).save(self.root/'source/photo.png')
        self.run_engine()
        self.c=self.conn()
        self.pid=self.c.execute('SELECT id FROM photos WHERE source_path=?',(str(self.photo),)).fetchone()[0]
        cfg=Config(base=self.root/'base',source=self.root/'source',dest=self.root/'dest',cache=self.root/'cache',
            backups=self.root/'backups',allowed_hosts=('testserver',))
        self.client=TestClient(webapp.create_app(cfg));self.client.__enter__()
        self.addCleanup(self.client.__exit__,None,None,None)
        self.url=f'/api/v1/photos/{self.pid}/import-choices'
        result=self.client.get(self.url);self.assertEqual(result.status_code,200,result.text)
        self.state=result.json()
        self.originals={p.name:p.read_bytes() for p in (self.root/'source').iterdir()}

    def choice(self,kind='association',**selection):
        return dict(photo_id=self.pid,kind=kind,selection=dict(capture_id=self.state['capture_id'],**selection))

    def preview(self,choice):
        result=self.client.post(self.url+'/preview',json=choice)
        self.assertEqual(result.status_code,200,result.text)
        return result.json()

    def save(self,preview,request='choice-test'):
        body=dict(choice=preview['choice'],token=preview['token'],request_id=request)
        result=self.client.post(self.url+'/confirm',json=body)
        self.assertEqual(result.status_code,200,result.text)
        return body,result.json()

    def test_shared_choice_preview_confirm_replay_and_copy(self):
        self.setup_choice()
        side=self.state['sidecars'][0]
        owner=next(p for p in side['candidates'] if p['path']=='photo.jpg')['file_id']
        preview=self.preview(self.choice(sidecar=side['path'],owner_ids=[owner]))
        self.assertEqual(preview['owners'],['photo.jpg'])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM metadata_decisions').fetchone()[0],0)
        body,saved=self.save(preview)
        self.assertEqual(self.client.post(self.url+'/confirm',json=body).json(),saved)
        self.assertFalse(self.client.get(self.url).json()['sidecars'][0]['needs_choice'])
        detail = self.client.get(f'/api/v1/photos/{self.pid}/inspect').json()
        self.assertEqual(detail['dest_path'], str(self.root/'dest/library/2005/03/04/photo.jpg'))
        self.assertEqual({p.name:p.read_bytes() for p in (self.root/'source').iterdir()},self.originals)
        self.run_engine('--copy')
        self.assertEqual(dict(self.c.execute('SELECT status,COUNT(*) FROM photos GROUP BY status')),{'Copied':2})
        self.assertEqual(len(list((self.root/'dest').rglob('*.xmp'))),1)
        self.assertEqual(self.client.get(self.url).status_code,400)
        self.assertEqual(self.client.post(self.url+'/confirm',json=body).json(),saved)
        self.assertEqual({p.name:p.read_bytes() for p in (self.root/'source').iterdir()},self.originals)

    def test_primary_version_changes_filing_only_on_copy(self):
        self.setup_choice(versions=True)
        self.assertTrue(self.state['needs_primary'])
        p=self.preview(self.choice('primary',primary_id='sidecar:photo.XMP'))
        self.assertEqual(p['effective']['date_taken'],'2012-06-07T08:09:10')
        before = self.client.get(f'/api/v1/photos/{self.pid}/inspect').json()['dest_path']
        catalog_before = tuple(self.c.execute('SELECT status,dest_path,metadata_json FROM photos WHERE id=?', (self.pid,)).fetchone())
        body,_=self.save(p)
        detail = self.client.get(f'/api/v1/photos/{self.pid}/inspect').json()
        self.assertEqual(detail['dest_path'], str(self.root/'dest/library/2012/06/07/photo.jpg'))
        self.assertNotEqual(detail['dest_path'], before)
        self.assertTrue(detail['dest_path_is_projection'])
        self.assertEqual(tuple(self.c.execute('SELECT status,dest_path,metadata_json FROM photos WHERE id=?', (self.pid,)).fetchone()), catalog_before)
        self.assertFalse(list((self.root/'dest').rglob('*.jpg')))
        self.run_engine('--copy')
        target=self.root/'dest/library/2012/06/07/photo.jpg'
        self.assertEqual(target.read_bytes(),self.originals['photo.jpg'])
        self.assertEqual(Path(str(target)+'.xmp').read_bytes(),self.originals['photo.XMP'])
        self.assertEqual({p.name:p.read_bytes() for p in (self.root/'source').iterdir()},self.originals)
        self.assertEqual(self.client.post(self.url+'/confirm',json=body).status_code,200)

    def test_verified_choice_import_allows_orientation_edit_without_rewriting_capture(self):
        self.setup_choice(versions=True)
        capture=self.state['capture_id']
        self.save(self.preview(self.choice('primary',primary_id='sidecar:photo.XMP')))
        before=self.c.execute('SELECT report_json FROM metadata_captures WHERE capture_id=?',(capture,)).fetchone()[0]
        self.run_engine('--copy')
        db=next((self.root/'base/db').glob('*.db'))
        current=self.client.get(f'/api/v1/photos/{self.pid}/date-edit').json()['capture_id']
        plan=metadata_edits.preview_catalog(db,photo_id=self.pid,capture_id=current,
            changes={'orientation':6},destination_root=self.root/'dest')
        self.assertEqual(plan['target']['source_id'],'sidecar:photo.XMP')
        self.assertEqual(plan['target_fields_after']['date_taken'],'2012-06-07T08:09:10')
        self.assertEqual(self.c.execute('SELECT report_json FROM metadata_captures WHERE capture_id=?',(capture,)).fetchone()[0],before)

    def test_stale_preview_and_different_request_reuse_refused(self):
        self.setup_choice(versions=True)
        first=self.preview(self.choice('primary',primary_id='sidecar:photo.XMP'))
        other=self.preview(self.choice('primary',primary_id='sidecar:photo.xmp'))
        body,_=self.save(other)
        result=self.client.post(self.url+'/confirm',json=dict(choice=first['choice'],token=first['token'],request_id='stale'))
        self.assertEqual(result.status_code,409,result.text)
        body['choice']=first['choice'];body['token']=first['token']
        self.assertEqual(self.client.post(self.url+'/confirm',json=body).status_code,409)

    def test_binding_and_untrusted_fields_refused(self):
        self.setup_choice()
        side=self.state['sidecars'][0];owners=[p['file_id'] for p in side['candidates']]
        choice=self.choice(sidecar=side['path'],owner_ids=owners)
        p=self.preview(choice)
        wrong={**choice,'photo_id':self.pid+999}
        self.assertEqual(self.client.post(self.url+'/preview',json=wrong).status_code,400)
        for selection in ({**choice['selection'],'sidecar':'../photo.xmp'},
                          {**choice['selection'],'owner_ids':[999999]},
                          {**choice['selection'],'owner_ids':[True]},
                          {**choice['selection'],'effective':{'date_taken':'2000'}}):
            response=self.client.post(self.url+'/preview',json={**choice,'selection':selection})
            self.assertEqual(response.status_code,400,response.text)
        for bad in (None,[],True,2**64):
            body=dict(choice={**choice,'selection':{'capture_id':bad}},token=p['token'],request_id='bad')
            self.assertEqual(self.client.post(self.url+'/confirm',json=body).status_code,400)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM metadata_decisions').fetchone()[0],0)

    def test_running_job_refuses_confirmation_without_mutation(self):
        self.setup_choice(versions=True)
        p=self.preview(self.choice('primary',primary_id='sidecar:photo.XMP'))
        ns_db.create_run(self.c,mode='INDEX',source=str(self.root/'source'),destination=str(self.root/'dest'))
        result=self.client.post(self.url+'/confirm',json=dict(choice=p['choice'],token=p['token'],request_id='busy'))
        self.assertEqual(result.status_code,409,result.text)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM metadata_decisions').fetchone()[0],0)

    def test_repair_is_not_bypassed_by_primary_choice(self):
        self.setup_choice(versions=True)
        (self.root/'source/photo.xmp').write_bytes(b'<broken')
        self.run_engine()
        # No unresolved readable choice remains: the repair path takes precedence.
        self.assertEqual(self.client.get(self.url).status_code,400)
        choice=self.choice('primary',primary_id='sidecar:photo.XMP')
        self.assertIn(self.client.post(self.url+'/preview',json=choice).status_code,(400,409))
        self.assertEqual((self.root/'source/photo.xmp').read_bytes(),b'<broken')

    def test_saved_ownership_can_be_revised_before_import(self):
        self.setup_choice()
        side=self.state['sidecars'][0]
        ids=[p['file_id'] for p in side['candidates']]
        self.save(self.preview(self.choice(sidecar=side['path'],owner_ids=ids[:1])))
        second=self.preview(self.choice(sidecar=side['path'],owner_ids=ids))
        self.save(second,'both')
        self.run_engine('--move')
        self.assertEqual(len(list((self.root/'dest').rglob('*.xmp'))),2)
        self.assertFalse(list((self.root/'source').iterdir()))
        self.assertEqual(dict(self.c.execute('SELECT status,COUNT(*) FROM photos GROUP BY status')),{'Completed':2})

    def test_explicit_empty_primary_does_not_revive_exif_date(self):
        self.setup_choice(versions=True)
        (self.root/'source/photo.XMP').write_bytes(metadata_index_test.packet(''))
        self.run_engine()
        self.state=self.client.get(self.url).json()
        p=self.preview(self.choice('primary',primary_id='sidecar:photo.XMP'))
        self.assertEqual(p['effective']['date_taken'],'')
        self.save(p)
        detail = self.client.get(f'/api/v1/photos/{self.pid}/inspect').json()
        self.assertIn('/Undated/', detail['dest_path'])
        self.run_engine('--copy')
        dest=self.c.execute('SELECT dest_path FROM photos WHERE id=?',(self.pid,)).fetchone()[0]
        self.assertIn('/Undated/',dest)
        self.assertEqual(Path(dest).read_bytes(),self.originals['photo.jpg'])
        revision=self.history(photo=self.pid)['items'][-1]['revision']
        comparison=self.client.get(f'/api/v1/photos/{self.pid}/metadata-choices/{revision}/comparison').json()
        self.assertEqual(comparison['historical']['fields']['date_taken'],'')
        self.assertNotIn('caption',comparison['historical']['fields'])

    def test_changed_capture_does_not_project_old_choice(self):
        self.setup_choice(versions=True)
        self.save(self.preview(self.choice('primary', primary_id='sidecar:photo.XMP')))
        (self.root/'source/photo.XMP').write_bytes(metadata_index_test.packet('2015-06-07T08:09:10'))
        self.run_engine()
        recorded = self.c.execute('SELECT dest_path FROM photos WHERE id=?', (self.pid,)).fetchone()[0]
        detail = self.client.get(f'/api/v1/photos/{self.pid}/inspect').json()
        self.assertEqual(detail['dest_path'], recorded)
        self.assertNotIn('/2012/06/07/', detail['dest_path'])

    def history(self, **params):
        response=self.client.get('/api/v1/metadata-history',params=params)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_history_saved_revised_replayed_and_applied_are_distinct(self):
        self.setup_choice(versions=True)
        operations=self.c.execute('SELECT COUNT(*) FROM operations').fetchone()[0]
        self.assertEqual(self.history(photo=self.pid)['total'],0)
        body,_=self.save(self.preview(self.choice('primary',primary_id='sidecar:photo.xmp')),'first')
        self.save(self.preview(self.choice('primary',primary_id='sidecar:photo.XMP')),'second')
        self.assertEqual(self.client.post(self.url+'/confirm',json=body).status_code,200)
        history=self.history(photo=self.pid)
        self.assertEqual(history['total'],2)  # No implicit ownership or replay duplicates.
        self.assertEqual([i['primary'] for i in history['items']],['sidecar:photo.XMP','sidecar:photo.xmp'])
        self.assertTrue(all(i['stage']=='saved' and i['run_id'] is None for i in history['items']))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM operations').fetchone()[0],operations)
        self.assertEqual(self.history(photo=self.pid,page_size=1)['items'],history['items'][:1])
        self.assertEqual(self.history(photo=self.pid,page_size=1,page=2)['items'],history['items'][1:])
        self.assertEqual(self.history(photo=self.pid,status='Failed')['total'],0)
        self.assertEqual(self.history(photo=999999)['total'],0)
        self.assertEqual(self.history(q="%' OR 1=1 --")['total'],0)
        self.assertEqual(self.history(since='2999-01-01')['total'],0)
        self.assertEqual(self.history(until='1900-01-01')['total'],0)
        self.run_engine('--copy')
        history=self.history(photo=self.pid)
        applied=[i for i in history['items'] if i['stage']=='applied']
        self.assertEqual(len(applied),1)
        self.assertEqual(applied[0]['primary'],'sidecar:photo.XMP')
        self.assertEqual(applied[0]['date_taken'],'2012-06-07T08:09:10')
        self.assertEqual(applied[0]['revision'],history['items'][1]['revision'])
        self.assertEqual(self.history(run=applied[0]['run_id'])['items'],applied)
        self.assertEqual(self.history(status='Copied')['items'],applied)
        self.assertEqual(self.history(q='photo.XMP')['total'],3)  # SQLite LIKE is case insensitive.
        self.assertEqual(self.client.get('/api/v1/metadata-history?page_size=101').status_code,422)
        self.assertEqual(self.client.get('/api/v1/metadata-history?status=madeup').status_code,400)

    def test_shared_history_includes_unselected_candidate_and_applies_to_owner(self):
        self.setup_choice()
        side=self.state['sidecars'][0]
        owner=next(p for p in side['candidates'] if p['path']=='photo.jpg')['file_id']
        other=next(p for p in side['candidates'] if p['path']=='photo.png')['photo_id']
        self.save(self.preview(self.choice(sidecar=side['path'],owner_ids=[owner])))
        for pid in (self.pid,other):
            history=self.history(photo=pid)
            self.assertEqual(history['total'],1)
            self.assertEqual(history['items'][0]['owners'],['photo.jpg'])
        self.run_engine('--copy')
        history=self.history(photo=self.pid)['items']
        self.assertEqual([i['stage'] for i in history],['applied','saved'])
        self.assertEqual(history[0]['applied_choices'],[history[1]['revision']])
        # Older receipts retain owners and the job's frozen settings; no migration.
        receipt=self.c.execute("SELECT operation_id,timestamp,detail_json FROM operation_events WHERE step='metadata_activated'").fetchone()
        detail=json.loads(receipt[2])
        for version in detail['versions']:
            version.pop('association_revision',None)
        # Append generated historical evidence; immutable real records stay untouched.
        event_id=self.c.execute("INSERT INTO operation_events(operation_id,timestamp,step,outcome,detail_json) "
            "VALUES(?,?,'metadata_activated','completed',?)",(receipt[0],receipt[1],json.dumps(detail))).lastrowid
        self.c.commit()
        restored=next(i for i in self.history(photo=self.pid)['items'] if i['id']==f'applied:{event_id}')
        self.assertEqual(restored['applied_choices'],[history[1]['revision']])
        # Conflicting ownership is not evidence that this choice was applied.
        for version in detail['versions']:
            version['owners']={}
        bad_id=self.c.execute("INSERT INTO operation_events(operation_id,timestamp,step,outcome,detail_json) "
            "VALUES(?,?,'metadata_activated','completed',?)",(receipt[0],receipt[1],json.dumps(detail))).lastrowid
        self.c.commit()
        self.assertNotIn(f'applied:{bad_id}',[i['id'] for i in self.history(photo=self.pid)['items']])
        self.assertEqual([i['stage'] for i in self.history(photo=other)['items']],['saved'])

    def test_compare_unselected_sidecar_uses_saved_capture_and_is_read_only(self):
        self.setup_choice()
        side=self.state['sidecars'][0]
        owner=next(p for p in side['candidates'] if p['path']=='photo.jpg')['file_id']
        other=next(p for p in side['candidates'] if p['path']=='photo.png')['photo_id']
        _,saved=self.save(self.preview(self.choice(sidecar=side['path'],owner_ids=[owner])))
        revision=saved['revision']
        url=f'/api/v1/photos/{other}/metadata-choices/{revision}/comparison'
        before=self.client.get(url)
        self.assertEqual(before.status_code,200,before.text)
        self.assertIsNone(before.json()['primary'])  # Pending choice is not activation.
        self.run_engine('--copy')
        result=self.client.get(url)
        self.assertEqual(result.status_code,200,result.text)
        comparison=result.json()
        self.assertFalse(comparison['assigned_to_photo'])
        self.assertEqual(comparison['owners'],['photo.jpg'])
        self.assertEqual(comparison['filename'],'photo.png')
        self.assertEqual(comparison['historical']['fields']['date_taken'],'2005-03-04T05:06:07')
        self.assertNotEqual(comparison['primary']['kind'],'sidecar_xmp')
        owner_result=self.client.get(f'/api/v1/photos/{self.pid}/metadata-choices/{revision}/comparison').json()
        self.assertTrue(owner_result['assigned_to_photo'])
        self.assertEqual(owner_result['primary']['kind'],'sidecar_xmp')
        # A later source change/capture cannot replace the bytes recorded for the choice.
        (self.root/'source/photo.xmp').write_bytes(metadata_index_test.packet('2020-01-02T03:04:05'))
        self.run_engine()
        files={str(p):p.read_bytes() for folder in ('source','dest') for p in (self.root/folder).rglob('*') if p.is_file()}
        counts={table:self.c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                for table in ('metadata_decisions','operations','operation_events','xmp_versions')}
        again=self.client.get(url).json()
        self.assertEqual(again['historical'],comparison['historical'])
        self.assertEqual({table:self.c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in counts},counts)
        self.assertEqual({str(p):p.read_bytes() for folder in ('source','dest') for p in (self.root/folder).rglob('*') if p.is_file()},files)
        self.assertEqual(self.client.get(f'/api/v1/photos/999999/metadata-choices/{revision}/comparison').status_code,404)
        self.assertEqual(self.client.get(f'/api/v1/photos/{other}/metadata-choices/999999/comparison').status_code,404)
        self.assertEqual(self.client.get(f'/api/v1/photos/{other}/metadata-choices/0/comparison').status_code,422)
        # A real but unrelated photo must not be accepted either.
        Image.new('RGB',(51,29),(1,22,93)).save(self.root/'source/unrelated.jpg')
        self.run_engine()
        unrelated=self.c.execute("SELECT id FROM photos WHERE source_path LIKE '%/unrelated.jpg'").fetchone()[0]
        self.assertEqual(self.client.get(f'/api/v1/photos/{unrelated}/metadata-choices/{revision}/comparison').status_code,404)

    def test_compare_primary_revisions_and_missing_fields(self):
        self.setup_choice(versions=True)
        _,first=self.save(self.preview(self.choice('primary',primary_id='sidecar:photo.xmp')),'first')
        self.save(self.preview(self.choice('primary',primary_id='sidecar:photo.XMP')),'second')
        self.run_engine('--copy')
        result=self.client.get(f"/api/v1/photos/{self.pid}/metadata-choices/{first['revision']}/comparison")
        self.assertEqual(result.status_code,200,result.text)
        data=result.json()
        self.assertEqual(data['historical']['fields']['date_taken'],'2005-03-04T05:06:07')
        self.assertEqual(data['primary']['fields']['date_taken'],'2012-06-07T08:09:10')
        self.assertNotIn('caption',data['historical']['fields'])
