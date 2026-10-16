"""Generated partial imports: confirmed UI/API retries use the real engine."""
import contextlib
from pathlib import Path
from unittest import mock

import metadata_index_test
import webui_api_test
from engine import durable, metadata_transfer, ns_db, pair_retry
from webui import catalog, outcomes


class PairRetry(webui_api_test.ApiCase):
    def setUp(self):
        super().setUp()
        self.create_catalog()
        self.photo=self.cfg.source/'pair.jpg'
        self.sidecar=self.cfg.source/'pair.jpg.xmp'
        webui_api_test.make_photo(self.photo,'pair')
        self.sidecar.write_bytes(metadata_index_test.packet())
        self.before=[p.read_bytes() for p in (self.photo,self.sidecar)]
        self.wait_for(self.start(mode='index'))
        with catalog.connect(self.cfg.db_path) as c:
            self.pid,self.capture=c.execute('SELECT p.id,MAX(m.capture_id) FROM photos p JOIN photo_files pf '
                'ON pf.photo_id=p.id JOIN metadata_captures m USING(file_id)').fetchone()
        self.dest=self.cfg.dest/'library/2005/03/04/pair.jpg'

    def fail_pair(self,move=False,member="xmp"):
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            c.execute('PRAGMA synchronous=FULL')
            run,_=ns_db.create_run(c,mode='MOVE' if move else 'COPY',source=str(self.cfg.source),destination=str(self.cfg.dest))
            op=metadata_transfer.prepare(c,run_id=run,photo_id=self.pid,capture_id=self.capture,destination=str(self.dest),move=move,activate=True)
            actual=durable.copy_verify_delete
            def fail(source,target,**kw):
                return (False,'generated XMP publication failure' if member == 'xmp' else 'generated photo publication failure') if source.endswith('.xmp') == (member == 'xmp') else actual(source,target,**kw)
            with mock.patch.object(durable,'copy_verify_delete',side_effect=fail):
                result=metadata_transfer.execute(c,op)
            self.assertFalse(result['completed'],result)
            ns_db.transition_run(c,run,'Failed')
        return op

    def preview(self):
        response=self.client.post('/api/v1/pair-retries/preview',json={'file_ids':[self.pid]})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def request(self):
        return {**self.preview()['groups'][0],'request_id':'pair-retry'}

    def retry(self,body):
        response=self.client.post('/api/v1/pair-retries/start',json=body)
        self.assertEqual(response.status_code,202,response.text)
        return response.json()['id']

    def test_copy_preview_cancel_retry_and_exact_request_replay(self):
        self.fail_pair()
        inode=self.dest.stat().st_ino
        preview=self.preview()
        self.assertEqual(preview['items'][0]['mode'],'copy')
        self.assertEqual(preview['items'][0]['delivery'],dict(photo='verified',xmp='incomplete'))
        self.assertEqual(preview['items'][0]['failure_context'],dict(stage='Transferring XMP', paths=[str(self.sidecar),str(self.dest)+'.xmp']))
        self.assertIn('generated XMP publication failure',preview['items'][0]['summary'])
        self.assertEqual([p.read_bytes() for p in (self.photo,self.sidecar)],self.before)
        issues=self.client.get(f'/api/v1/photos/{self.pid}/issues').json()['items']
        self.assertEqual(issues[0]['category'],'metadata_pair_incomplete')
        selection=self.client.post('/api/v1/photos/selection',json={'ids':[self.pid]}).json()
        self.assertEqual(selection['pair_retries'],1)
        body=self.request();run=self.retry(body);self.wait_for(run)
        self.assertEqual(self.dest.stat().st_ino,inode)
        self.assertEqual([p.read_bytes() for p in (self.dest,Path(str(self.dest)+'.xmp'))],self.before)
        self.assertEqual([p.read_bytes() for p in (self.photo,self.sidecar)],self.before)
        self.assertEqual(self.preview(),{'items':[],'groups':[]})
        self.assertEqual(self.client.post('/api/v1/photos/selection',json={'ids':[self.pid]}).json()['pair_retries'],0)
        self.assertEqual(self.retry(body),run)
        self.assertEqual(self.client.post('/api/v1/pair-retries/start',json={**body,'mode':'move'}).status_code,409)

    def test_move_retries_original_mode_and_removes_only_verified_sources(self):
        self.fail_pair(True)
        body=self.request()
        self.assertEqual(body['mode'],'move')
        self.assertEqual(self.client.post('/api/v1/pair-retries/start',json={**body,'mode':'copy'}).status_code,409)
        self.wait_for(self.retry(body))
        self.assertFalse(self.photo.exists());self.assertFalse(self.sidecar.exists())
        self.assertEqual([p.read_bytes() for p in (self.dest,Path(str(self.dest)+'.xmp'))],self.before)

    def test_changed_live_destination_keeps_sources_and_issue_open(self):
        self.fail_pair(True);body=self.request()
        self.dest.write_bytes(b'changed destination')
        self.wait_for(self.retry(body))
        self.assertEqual([p.read_bytes() for p in (self.photo,self.sidecar)],self.before)
        self.assertEqual(self.dest.read_bytes(),b'changed destination')
        self.assertTrue(self.preview()['items'])
        self.assertNotEqual(self.preview()['groups'][0]['token'],body['token'])

    def test_catalog_change_after_preview_refuses_and_roots_are_bound(self):
        self.fail_pair();body=self.request()
        with catalog.connect(self.cfg.db_path) as c:
            wrong=pair_retry.preview(c,source=self.cfg.source,destination=self.cfg.dest/'other',photo_ids=[self.pid])
            self.assertIn('original job',wrong[0]['blocked'])
            with self.assertRaises(ValueError):
                pair_retry.check(c,body['token'],source=self.cfg.source,destination=self.cfg.dest/'other',photo_ids=[self.pid],mode='copy')
            c.execute("UPDATE photos SET sha1_hash=? WHERE id=?",('0'*40,self.pid));c.commit()
        self.assertEqual(self.client.post('/api/v1/pair-retries/start',json=body).status_code,409)
        self.assertTrue(self.preview()['items'][0]['blocked']);self.assertFalse(self.preview()['groups'])
        self.assertEqual([p.read_bytes() for p in (self.photo,self.sidecar)],self.before)

    def test_engine_rechecks_after_api_preflight(self):
        self.fail_pair();body=self.request();runner=self.app_jobs();launch=runner._launch
        def changed(*args,**kwargs):
            with catalog.connect(self.cfg.db_path) as c:
                c.execute("UPDATE photos SET sha1_hash=? WHERE id=?",('0'*40,self.pid));c.commit()
            return launch(*args,**kwargs)
        with mock.patch.object(runner,'_launch',side_effect=changed):
            response=self.client.post('/api/v1/pair-retries/start',json=body)
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual([p.read_bytes() for p in (self.photo,self.sidecar)],self.before)
        with catalog.connect(self.cfg.db_path) as c:
            self.assertIsNone(c.execute('SELECT 1 FROM job_requests WHERE request_id=?',(body['request_id'],)).fetchone())

    def test_invalid_requests_and_engine_lock_leave_files_untouched(self):
        self.fail_pair();body=self.request()
        for change in ({'mode':'reject'},{'token':'bad'},{'file_ids':[]},{'file_ids':[True]},
                       {'file_ids':[999999]},{'request_id':'../escape'},{'file_ids':None},{'request_id':None}):
            with self.subTest(change=change):
                response=self.client.post('/api/v1/pair-retries/start',json={**body,**change})
                self.assertIn(response.status_code,(400,409),response.text)
        with self.engine_lock_held():
            self.assertEqual(self.client.post('/api/v1/pair-retries/start',json=body).status_code,409)
        self.assertEqual([p.read_bytes() for p in (self.photo,self.sidecar)],self.before)

    def test_safety_answer_keeps_pair_guard_and_refuses_copy_for_original_move(self):
        self.fail_pair(True);body=self.request()
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            run,_=ns_db.create_run(c,mode='MOVE',source=str(self.cfg.source),destination=str(self.cfg.dest),
                selection=[self.pid],submitted={'pair_retry_token':body['token']},request_id='safety-retry')
        runner=self.app_jobs()
        with mock.patch.object(outcomes,'safety_questions',return_value=['network_destination']),mock.patch.object(runner,'_launch',return_value=987) as launch:
            self.assertTrue(outcomes.get_run(self.cfg.db_path,run)['same_mode_retry'])
            self.assertEqual(runner.answer(run,'network_destination','confirm_move','confirmed-retry'),987)
            self.assertIn('--pair-retry-token',launch.call_args.args[0])
            self.assertIn(body['token'],launch.call_args.args[0])
            # The public answer route is exercised by the browser safety suite; verify the
            # runner directly here so an alternate mode cannot bypass the pair manifest.
            from webui.jobs import JobRefused
            with self.assertRaises(JobRefused) as refused:
                runner.answer(run,'network_destination','copy','copy-retry')
            self.assertEqual(refused.exception.status,409)

    def test_mixed_selection_separates_original_modes_and_excludes_ordinary_photos(self):
        self.fail_pair();copy_id=self.pid
        second=self.cfg.source/'second.jpg'
        webui_api_test.make_photo(second,'second')
        Path(str(second)+'.xmp').write_bytes(metadata_index_test.packet())
        webui_api_test.make_photo(self.cfg.source/'ordinary.jpg','ordinary')
        self.wait_for(self.start(mode='index'))
        with catalog.connect(self.cfg.db_path) as c:
            self.pid,self.capture=c.execute('SELECT p.id,MAX(m.capture_id) FROM photos p JOIN photo_files pf '
                'ON pf.photo_id=p.id JOIN metadata_captures m USING(file_id) WHERE p.source_path=?',(str(second),)).fetchone()
            ordinary=c.execute("SELECT id FROM photos WHERE source_path=?",(str(self.cfg.source/'ordinary.jpg'),)).fetchone()[0]
        self.dest=self.dest.with_name('second.jpg')
        self.fail_pair(True)
        ids=[copy_id,self.pid,ordinary]
        result=self.client.post('/api/v1/pair-retries/preview',json={'file_ids':ids}).json()
        self.assertEqual([(g['mode'],g['file_ids']) for g in result['groups']],[('copy',[copy_id]),('move',[self.pid])])
        self.assertEqual(self.client.post('/api/v1/photos/selection',json={'ids':ids}).json()['pair_retries'],2)
        for body in ({'file_ids':[]},{'file_ids':[True]},{'file_ids':'1'},{'source':'../other'}):
            self.assertEqual(self.client.post('/api/v1/pair-retries/preview',json=body).status_code,400)

    def test_photo_failure_names_photo_not_xmp(self):
        self.fail_pair(member='photo')
        item=self.preview()['items'][0]
        self.assertEqual(item['failure_context'],dict(stage='Transferring photo', paths=[str(self.photo),str(self.dest)]))
        self.assertEqual(item['delivery'],dict(photo='incomplete',xmp='unknown'))
        self.assertFalse(self.dest.exists())
        self.assertEqual([p.read_bytes() for p in (self.photo,self.sidecar)],self.before)

    def test_older_failure_does_not_guess_from_summary(self):
        settle=metadata_transfer._settle
        def older_record(*args, **kwargs):
            kwargs.pop('failure_context',None)
            kwargs.pop('delivery',None)
            return settle(*args, **kwargs)
        # Generate an older-shaped event at creation; history is immutable.
        with mock.patch.object(metadata_transfer,'_settle',side_effect=older_record):
            self.fail_pair()
        item=self.preview()['items'][0]
        self.assertIn('XMP publication',item['summary'])
        self.assertIsNone(item['failure_context'])
        self.assertEqual(item['delivery'],dict(photo='unknown',xmp='unknown'))
        self.assertTrue(self.preview()['groups'])

    def test_move_cleanup_failure_names_source_photo(self):
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            c.execute('PRAGMA synchronous=FULL')
            run,_=ns_db.create_run(c,mode='MOVE',source=str(self.cfg.source),destination=str(self.cfg.dest))
            op=metadata_transfer.prepare(c,run_id=run,photo_id=self.pid,capture_id=self.capture,destination=str(self.dest),move=True,activate=True)
            with mock.patch.object(durable,'_remove_verified_source',side_effect=PermissionError('generated source cleanup denied')):
                result=metadata_transfer.execute(c,op)
            self.assertFalse(result['completed'])
            ns_db.transition_run(c,run,'Failed')
        self.assertEqual(self.preview()['items'][0]['failure_context'],dict(stage='Removing verified source photo',paths=[str(self.photo)]))
        self.assertEqual(self.preview()['items'][0]['delivery'],dict(photo='verified',xmp='verified'))
        self.assertEqual([p.read_bytes() for p in (self.photo,self.sidecar)],self.before)
        self.assertEqual([p.read_bytes() for p in (self.dest,Path(str(self.dest)+'.xmp'))],self.before)

    def test_final_pair_verification_failure_does_not_reuse_green_results(self):
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            c.execute('PRAGMA synchronous=FULL')
            run,_=ns_db.create_run(c,mode='COPY',source=str(self.cfg.source),destination=str(self.cfg.dest))
            op=metadata_transfer.prepare(c,run_id=run,photo_id=self.pid,capture_id=self.capture,destination=str(self.dest),move=False,activate=True)
            with mock.patch.object(metadata_transfer,'_verified',side_effect=OSError('generated verification failure')):
                self.assertFalse(metadata_transfer.execute(c,op)['completed'])
            ns_db.transition_run(c,run,'Failed')
        self.assertEqual(self.preview()['items'][0]['delivery'],dict(photo='unknown',xmp='unknown'))
        self.assertEqual([p.read_bytes() for p in (self.photo,self.sidecar)],self.before)

    def test_read_only_recovery_records_partial_delivery(self):
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            c.execute('PRAGMA synchronous=FULL')
            run,_=ns_db.create_run(c,mode='COPY',source=str(self.cfg.source),destination=str(self.cfg.dest))
            op=metadata_transfer.prepare(c,run_id=run,photo_id=self.pid,capture_id=self.capture,destination=str(self.dest),move=False,activate=True)
            actual=durable.copy_verify_delete
            def interrupted(source,target,**kwargs):
                if source.endswith('.xmp'):
                    raise KeyboardInterrupt('generated interruption before XMP publication')
                return actual(source,target,**kwargs)
            with mock.patch.object(durable,'copy_verify_delete',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):
                metadata_transfer.execute(c,op)
            self.assertFalse(metadata_transfer.recover(c,op)['completed'])
            ns_db.transition_run(c,run,'Failed')
        self.assertEqual(self.preview()['items'][0]['delivery'],dict(photo='verified',xmp='incomplete'))
        self.assertEqual([p.read_bytes() for p in (self.photo,self.sidecar)],self.before)
        self.assertFalse(Path(str(self.dest)+'.xmp').exists())
