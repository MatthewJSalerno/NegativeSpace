"""Audit regression checks with synthetic catalog records and synchronized workers."""
import concurrent.futures
import json
import threading
import unittest
import earlier_versions_test
from unittest import mock

from webui_api_test import ApiCase
from engine import ns_db, review, review_batch, metadata_import, transfer_preview
from webui import catalog, gallery


class Audit043Tests(ApiCase):
    def setUp(self):
        super().setUp()
        self.create_catalog()
        with ns_db.connect(self.cfg.db_path) as c:
            for pid in (1,2):
                c.execute("INSERT INTO photos(id,source_path,status,sha1_hash,metadata_json) VALUES(?,?,'Copied',?,?)",
                    (pid,str(self.cfg.source/f'audit-{pid}.jpg'),f'{pid:040x}',json.dumps({'date_taken':'2020-01-01','date_source':'exif'})))
            c.commit()

    def bookmark(self,pid,preset=None):
        body=dict(photo_id=pid,sha1=f'{pid:040x}',revision=0,reason='later',action='later',note='Remember',request_id=f'bookmark-{pid}')
        if preset:body['bookmark_reason']=preset
        review.decide(self.cfg.db_path,body)
        with ns_db.connect(self.cfg.db_path) as c: revision=review.details(c,pid)['revision']
        return dict(body,revision=revision,action='keep',request_id=f'keep-{pid}')

    def test_slow_preview_does_not_report_engine_busy(self):
        runner=self.app_jobs();entered=threading.Event();release=threading.Event()
        def slow(*a,**kw):
            entered.set();release.wait(5);return dict(file_ids=[],token='a'*64,mode='move',total=0,groups={},unplanned=[])
        with concurrent.futures.ThreadPoolExecutor() as pool, mock.patch.object(transfer_preview,'preview',side_effect=slow):
            future=pool.submit(runner.preview_transfer,{'mode':'move'})
            try:
                self.assertTrue(entered.wait(2))
                self.assertFalse(runner.engine_busy(),'Read-only preview must not report an active engine')
            finally:release.set();future.result()

    def test_job_start_is_not_blocked_by_read_only_preview(self):
        runner=self.app_jobs();entered=threading.Event();release=threading.Event()
        def slow(*a,**kw):
            entered.set();release.wait(5);return dict(file_ids=[],token='a'*64,mode='move',total=0,groups={},unplanned=[])
        with concurrent.futures.ThreadPoolExecutor() as pool, mock.patch.object(transfer_preview,'preview',side_effect=slow), mock.patch.object(runner,'_launch',return_value=73):
            pending=pool.submit(runner.preview_transfer,{'mode':'move'})
            try:
                self.assertTrue(entered.wait(2))
                start=pool.submit(runner.start,'index')
                self.assertEqual(start.result(timeout=0.5),73)
            finally:release.set();pending.result()

    def test_preview_pages_reuse_plan_with_token_only(self):
        runner=self.app_jobs()
        with mock.patch.object(metadata_import,'plan',wraps=metadata_import.plan) as plan:
            first=runner.preview_transfer({'mode':'move'})
            self.assertEqual(plan.call_count,2)
            second=runner.preview_transfer({'mode':'move','token':first['token'],'page':2})
            folder=runner.preview_transfer({'mode':'move','token':first['token'],'folder':first['groups'][0]['path'],'file_page':2})
            self.assertEqual(plan.call_count,2,'Paging must reuse the computed metadata plan')
            self.assertEqual(second['file_ids'],first['file_ids'])
            self.assertEqual(folder['token'],first['token'])

    def test_invalid_keep_item_is_skipped_without_losing_valid_answer(self):
        good=self.bookmark(1,'keep');bad=self.bookmark(2,'ask')
        result=review_batch.decide(self.cfg.db_path,{'items':[good,bad]})
        self.assertEqual(result['saved'],[1])
        self.assertEqual([v['photo_id'] for v in result['skipped']],[2])
        self.assertIn('keep-decision',result['skipped'][0]['message'])
        self.assertEqual(review_batch.decide(self.cfg.db_path,{'items':[good,bad]}),result)

    def test_missing_bookmark_reason_sorts_as_displayed_date(self):
        self.bookmark(1,'compare');self.bookmark(2)
        with catalog.connect(self.cfg.db_path) as c:
            self.assertEqual(review.details(c,2)['reasons'][0]['bookmark_reason'],'date')
        page=gallery.photos_by_ids(self.cfg.db_path,[1,2],sort='bookmark')
        self.assertEqual([p['id'] for p in page['items']],[2,1])

    def test_selection_paging_does_not_calculate_unused_review_actions(self):
        with mock.patch.object(review_batch,'counts',wraps=review_batch.counts) as counts:
            response=self.client.post('/api/v1/photos/selection',json={'ids':[1,2],'page':2,'page_size':1})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(counts.call_count,0)
        self.assertNotIn('review_actions',response.json())

    def test_shared_shorter_side_policy_drives_review_and_size_browsing(self):
        from engine import review_history
        with ns_db.connect(self.cfg.db_path) as c:
            ns_db.save_settings(c,{'small_image_min':800},expected_revisions={'small_image_min':0})
            c.execute("INSERT INTO contents(hash_algorithm,digest,width,height) VALUES('sha1',?,640,480)",(f'{1:040x}',));c.commit()
        with mock.patch.object(review_history,'shorter_side_sql',create=True,side_effect=lambda alias='c', minimum='800': f'({minimum} IS NOT NULL AND 0)'):
            result=gallery.list_photos(self.cfg.db_path,view='organized',size_below=800)
            self.assertEqual(result['total'],0)
            self.assertEqual(result['chips']['small'],0)
            with ns_db.connect(self.cfg.db_path) as c:
                self.assertEqual(review_batch.counts(c,[1])['small'],0)

    def test_preview_basis_uses_only_complete_coverage_of_requested_scope(self):
        with ns_db.connect(self.cfg.db_path) as c:
            for source, status, ended, scope in ((str(self.cfg.source),'Completed','2026-01-01T12:00:00Z',None),
                    (str(self.cfg.source),'Failed','2026-01-02T12:00:00Z',json.dumps({'source_subdir':'trip'})),
                    (str(self.root/'other'),'Completed','2026-01-03T12:00:00Z',None),
                    (str(self.cfg.source),'Running',None,None)):
                c.execute("INSERT INTO runs(mode,status,source_path,started_at,ended_at,file_ids_filter) VALUES('INDEX',?,?,'2026-01-01T00:00:00Z',?,?)",(status,source,ended,scope))
            c.commit()
        result=self.app_jobs().preview_transfer({'mode':'copy'})
        self.assertEqual(result['index_basis'],{'indexed_at':'2026-01-01T12:00:00Z','source_subdir':None})
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("INSERT INTO runs(mode,status,source_path,started_at,ended_at,file_ids_filter) VALUES('INDEX','Completed',?,'start','2026-01-04T12:00:00Z',?)",(str(self.cfg.source),json.dumps({'source_subdir':'trip'})))
            c.commit()
        folder=self.app_jobs().preview_transfer({'mode':'copy','source_subdir':'trip/child'})
        self.assertEqual(folder['index_basis'],{'indexed_at':'2026-01-04T12:00:00Z','source_subdir':'trip/child'})
        sibling=self.app_jobs().preview_transfer({'mode':'copy','source_subdir':'trip-other'})
        self.assertEqual(sibling['index_basis']['indexed_at'],'2026-01-01T12:00:00Z')

    def test_expired_or_wrong_mode_cached_plan_requires_refresh(self):
        runner=self.app_jobs();first=runner.preview_transfer({'mode':'move'})
        from webui import transfer_plans, jobs
        with self.assertRaises(jobs.JobRefused) as raised:
            runner.preview_transfer({'mode':'copy','token':first['token']})
        self.assertEqual(raised.exception.status,409)
        with mock.patch.object(transfer_plans,'LIFETIME_SECONDS',0),self.assertRaises(jobs.JobRefused):
            runner.preview_transfer({'mode':'move','token':first['token']})

    def test_review_counts_opt_in_keeps_full_selection_eligibility(self):
        self.bookmark(1,'keep');self.bookmark(2,'ask')
        response=self.client.post('/api/v1/photos/selection',json={'ids':[1,2],'page_size':1,'include_review_actions':True})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['review_actions']['done'],2)
        self.assertEqual(response.json()['review_actions']['keep'],1)
        self.assertEqual(len(response.json()['items']),1)

    def test_preview_basis_unknown_without_complete_coverage(self):
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("INSERT INTO runs(mode,status,source_path,started_at,ended_at,file_ids_filter) VALUES('INDEX','Completed',?,'start','2026-01-04T12:00:00Z',?)",(str(self.cfg.source),json.dumps({'source_subdir':'trip'})))
            c.execute("INSERT INTO runs(mode,status,source_path,started_at,ended_at,file_ids_filter) VALUES('INDEX','Completed',?,'start','2026-01-05T12:00:00Z',?)",(str(self.cfg.source),json.dumps([1,2])))
            c.commit()
        runner=self.app_jobs()
        self.assertIsNone(runner.preview_transfer({'mode':'copy'})['index_basis']['indexed_at'])
        self.assertIsNone(runner.preview_transfer({'mode':'move','source_subdir':'other'})['index_basis']['indexed_at'])

    def test_preview_basis_normalizes_folder_like_transfer_scope(self):
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("INSERT INTO runs(mode,status,source_path,started_at,ended_at,file_ids_filter) VALUES('INDEX','Completed',?,'start','2026-01-04T12:00:00Z',?)",(str(self.cfg.source),json.dumps({'source_subdir':'trip'})))
            c.commit()
        basis=self.app_jobs().preview_transfer({'mode':'copy','source_subdir':'./trip/child/'})['index_basis']
        self.assertEqual(basis,dict(indexed_at='2026-01-04T12:00:00Z',source_subdir='trip/child'))


class VersionAnswerPreviewTests(unittest.TestCase):
    def check_answer(self, answer, cached):
        f=earlier_versions_test.EarlierVersions()
        f.setUp()
        try:
            if cached:
                response=f.client.post('/api/v1/jobs/transfer-preview',json={'mode':'copy','file_ids':[f.alias]})
                self.assertEqual(response.status_code,200,response.text)
                plan=response.json()
            else:
                with ns_db.connect(f.cfg.db_path) as c:
                    plan=transfer_preview.preview(c,source=f.cfg.source,destination=f.cfg.dest,mode='copy',photo_ids=[f.alias])
            self.assertEqual(f.answer(f.alias,answer,'preview-answer').status_code,200)
            if cached:
                page=f.client.post('/api/v1/jobs/transfer-preview',json={'mode':'copy','token':plan['token'],'page':1})
                self.assertEqual(page.status_code,409,page.text)
            confirmed=f.client.post('/api/v1/jobs/start',json={'mode':'copy','file_ids':plan['file_ids'],'transfer_preview_token':plan['token'],'request_id':'confirm-after-answer'})
            if confirmed.status_code == 202: f.wait_for(confirmed.json()['id'])
            self.assertEqual(confirmed.status_code,409,confirmed.text)
            self.assertEqual(confirmed.json()['error'],'transfer_preview_changed')
        finally:
            f.tearDown()

    def test_not_kept_invalidates_uncached_confirmation(self):self.check_answer('not_kept',False)
    def test_keep_separate_invalidates_uncached_confirmation(self):self.check_answer('keep_separate',False)
    def test_not_kept_invalidates_cached_page_and_confirmation(self):self.check_answer('not_kept',True)
    def test_keep_separate_invalidates_cached_page_and_confirmation(self):self.check_answer('keep_separate',True)
