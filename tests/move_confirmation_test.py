"""Generated API-to-engine Move consent; no user photos or mocked file operations."""
import contextlib
from pathlib import Path
import uuid
from unittest import mock

import webui_api_test
from engine import ns_db
from webui import catalog, outcomes


class MoveConfirmation(webui_api_test.ApiCase):
    def setUp(self):
        super().setUp()
        self.create_catalog()
        webui_api_test.make_photo(self.cfg.source/'edited.jpg', 'edited', exif={36867:'2000:01:02 03:04:05'})
        webui_api_test.make_photo(self.cfg.source/'plain.jpg', 'plain', exif={36867:'2000:01:02 03:04:05'})
        self.wait_for(self.start(mode='index'))
        self.wait_for(self.start(mode='copy'))
        with catalog.connect(self.cfg.db_path) as c:
            self.ids = {Path(row[1]).name:row[0] for row in c.execute('SELECT id,source_path FROM photos')}
        self.pid = self.ids['edited.jpg']
        context = self.client.get(f'/api/v1/photos/{self.pid}/date-edit').json()
        self.assertEqual(context['target']['kind'], 'embedded_exif', context)
        planned = self.client.post(f'/api/v1/photos/{self.pid}/date-preview',json={
            'capture_id':context['capture_id'], 'value':'2001-02-03T04:05:06'}).json()
        response = self.client.post(f'/api/v1/photos/{self.pid}/date-save',json={
            'edit':planned['edit'], 'token':planned['token'], 'request_id':'fixture-edit'})
        self.assertEqual(response.status_code,202,response.text)
        self.wait_for(response.json()['id'])
        with catalog.connect(self.cfg.db_path) as c:
            self.retained = Path(c.execute('SELECT dest_path FROM photos WHERE id=?',(self.pid,)).fetchone()[0])
        self.original = (self.cfg.source/'edited.jpg').read_bytes()
        self.saved = self.retained.read_bytes()
        self.assertNotEqual(self.original,self.saved)

    def preview(self, **scope):
        response=self.client.post('/api/v1/jobs/move-preview',json=scope)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def request(self, preview, include, request_id=None):
        return dict(mode='move',file_ids=preview['file_ids'],move_preview_token=preview['token'],
                    confirm_edited_sources=include,request_id=request_id or uuid.uuid4().hex)

    def test_leave_moves_other_photos_and_new_job_does_not_inherit_consent(self):
        preview=self.preview()
        self.assertEqual([p['photo_id'] for p in preview['edited_originals']],[self.pid])
        self.wait_for(self.start(**self.request(preview,False)))
        self.assertEqual((self.cfg.source/'edited.jpg').read_bytes(),self.original)
        self.assertFalse((self.cfg.source/'plain.jpg').exists())
        self.assertEqual(self.retained.read_bytes(),self.saved)
        self.wait_for(self.start(mode='move',file_ids=[self.pid]))
        self.assertTrue((self.cfg.source/'edited.jpg').exists())

    def test_include_removes_original_retains_edited_bytes_history_and_replays(self):
        body=self.request(self.preview(),True,'confirmed-move')
        run=self.start(**body);self.wait_for(run)
        self.assertFalse((self.cfg.source/'edited.jpg').exists())
        self.assertFalse((self.cfg.source/'plain.jpg').exists())
        self.assertEqual(self.retained.read_bytes(),self.saved)
        with catalog.connect(self.cfg.db_path) as c:
            self.assertGreater(c.execute('SELECT COUNT(*) FROM source_snapshots').fetchone()[0],0)
        self.assertEqual(self.start(**body),run)
        body['confirm_edited_sources']=False
        self.assertEqual(self.client.post('/api/v1/jobs/start',json=body).status_code,409)

    def test_stale_scope_and_invalid_consent_refuse_without_removing_files(self):
        preview=self.preview()
        for change in ({'file_ids':[self.pid]}, {'mode':'copy'}, {'confirm_edited_sources':'yes'},
                       {'move_preview_token':None}, {'request_id':None}):
            with self.subTest(change=change):
                result=self.client.post('/api/v1/jobs/start',json={**self.request(preview,True),**change})
                self.assertIn(result.status_code,(400,409),result.text)
        with catalog.connect(self.cfg.db_path) as c:
            c.execute('UPDATE photos SET sha1_hash=? WHERE id=?',('0'*40,self.pid));c.commit()
        response=self.client.post('/api/v1/jobs/start',json=self.request(preview,True))
        self.assertEqual((response.status_code,response.json()['error']),(409,'move_preview_changed'))
        self.assertEqual((self.cfg.source/'edited.jpg').read_bytes(),self.original)

    def test_engine_rechecks_snapshot_after_api_preflight(self):
        body=self.request(self.preview(),True)
        runner=self.app_jobs(); launch=runner._launch
        def changed(*args,**kwargs):
            with catalog.connect(self.cfg.db_path) as c:
                c.execute('UPDATE photos SET dest_path=dest_path || ? WHERE id=?',('.changed',self.pid));c.commit()
            return launch(*args,**kwargs)
        with mock.patch.object(runner,'_launch',side_effect=changed):
            response=self.client.post('/api/v1/jobs/start',json=body)
        self.assertEqual(response.status_code,409,response.text)
        self.assertTrue((self.cfg.source/'edited.jpg').exists())
        self.assertTrue((self.cfg.source/'plain.jpg').exists())
        with catalog.connect(self.cfg.db_path) as c:
            self.assertIsNone(c.execute('SELECT 1 FROM job_requests WHERE request_id=?',(body['request_id'],)).fetchone())

    def test_changed_file_fails_live_verification_even_with_unchanged_catalog(self):
        body=self.request(self.preview(file_ids=[self.pid]),True)
        self.retained.write_bytes(self.saved+b'changed externally')
        self.wait_for(self.start(**body))
        self.assertEqual((self.cfg.source/'edited.jpg').read_bytes(),self.original)
        self.assertEqual(self.retained.read_bytes(),self.saved+b'changed externally')

    def test_folder_and_source_boundaries_are_literal(self):
        self.assertEqual(self.preview(source_subdir='empty')['file_ids'],[])
        for folder in ('../outside','/outside'):
            self.assertEqual(self.client.post('/api/v1/jobs/move-preview',json={'source_subdir':folder}).status_code,400)
        (self.cfg.source/'escape').symlink_to(self.cfg.dest,target_is_directory=True)
        self.assertEqual(self.client.post('/api/v1/jobs/move-preview',json={'source_subdir':'escape'}).status_code,400)
        for scope in ({'file_ids':[True]}, {'file_ids':[self.pid],'source_subdir':'empty'}, {'file_ids':[999999]}):
            self.assertEqual(self.client.post('/api/v1/jobs/move-preview',json=scope).status_code,400)
        with self.engine_lock_held():
            self.assertEqual(self.client.post('/api/v1/jobs/move-preview',json={}).status_code,409)

    def test_previewed_all_move_preserves_rejects_location(self):
        self.wait_for(self.start(mode='reject',file_ids=[self.pid]))
        preview=self.preview()
        self.assertEqual(preview['rejected_originals'],1)
        self.assertTrue(preview['edited_originals'][0]['in_rejects'])
        self.wait_for(self.start(**self.request(preview,True)))
        self.assertFalse((self.cfg.source/'edited.jpg').exists())
        with catalog.connect(self.cfg.db_path) as c:
            row=c.execute('SELECT status,dest_path FROM photos WHERE id=?',(self.pid,)).fetchone()
        self.assertIn('Rejected',row[0]); self.assertIn('/rejects/',row[1])
        self.assertEqual(Path(row[1]).read_bytes(),self.saved)

    def test_safety_answers_carry_consent_only_with_the_same_move_selection(self):
        preview=self.preview()
        submitted={'confirm_edited_sources':True,'move_preview_token':preview['token']}
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            run,_=ns_db.create_run(c,mode='MOVE',source=str(self.cfg.source.resolve()),
                destination=str(self.cfg.dest.resolve()),selection=preview['file_ids'],submitted=submitted,request_id='fixture-safety')
        runner=self.app_jobs()
        for answer,expected in (('confirm_move',True),('copy',False)):
            with self.subTest(answer=answer), mock.patch.object(outcomes,'safety_questions',return_value=['network_destination']), mock.patch.object(runner,'_launch',return_value=987) as launch:
                self.assertEqual(runner.answer(run,'network_destination',answer,'answer-'+answer),987)
                flags,request_id,ids=launch.call_args.args
                self.assertEqual(ids,preview['file_ids'])
                self.assertEqual('--confirm-edited-sources' in flags,expected)
                self.assertIn('--move-preview-token',flags)

    def test_pending_cleanup_is_still_shown_after_the_photo_source_was_removed(self):
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            run,_=ns_db.create_run(c,mode='MOVE',source=str(self.cfg.source),destination=str(self.cfg.dest))
            ns_db.begin_operation(c,run_id=run,photo_id=self.pid,source_path=str(self.cfg.source/'edited.jpg'),
                                    dest_path=str(self.retained),kind='metadata_source_cleanup')
            c.execute("UPDATE photos SET status='Completed' WHERE id=?",(self.pid,));c.commit()
        self.assertEqual([row['photo_id'] for row in self.preview()['edited_originals']],[self.pid])

    def test_copy_instead_of_mixed_move_keeps_scope_but_never_deletes_sources(self):
        self.wait_for(self.start(mode='reject',file_ids=[self.pid]))
        preview=self.preview()
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            run,_=ns_db.create_run(c,mode='MOVE',source=str(self.cfg.source),destination=str(self.cfg.dest),
                selection=preview['file_ids'],request_id='network-question',submitted={
                    'confirm_edited_sources':True,'move_preview_token':preview['token']})
        with mock.patch.object(outcomes,'safety_questions',return_value=['network_destination']):
            response=self.client.post(f'/api/v1/runs/{run}/answer',json={
                'question':'network_destination','answer':'copy','request_id':'copy-alternative'})
        self.assertEqual(response.status_code,202,response.text)
        copy_id=response.json()['id']; self.wait_for(copy_id)
        self.assertTrue((self.cfg.source/'edited.jpg').exists())
        self.assertTrue((self.cfg.source/'plain.jpg').exists())
        with catalog.connect(self.cfg.db_path) as c:
            self.assertEqual([r[0] for r in c.execute('SELECT photo_id FROM run_selections WHERE run_id=? ORDER BY photo_id',(copy_id,))],preview['file_ids'])
        record=outcomes.request_record(self.cfg.db_path,'copy-alternative')['request']
        self.assertEqual(record['mode'],'COPY')
        self.assertFalse(record['submitted']['confirm_edited_sources'])
        self.assertEqual(record['submitted']['move_preview_token'],preview['token'])
        # Re-answer after the question is no longer current replays the accepted Copy.
        again=self.client.post(f'/api/v1/runs/{run}/answer',json={
            'question':'network_destination','answer':'copy','request_id':'copy-alternative'})
        self.assertEqual(again.status_code,202,again.text)
        self.assertEqual(again.json()['id'],copy_id)
