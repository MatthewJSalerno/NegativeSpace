"""Destination folder previews and accepted job scope, using generated files only."""
import json
import uuid
from pathlib import Path
from unittest import mock

import webui_api_test
import metadata_index_test
from engine import ns_db, transfer_preview
from webui import catalog


class TransferPreviewTests(webui_api_test.ApiCase):
    def setUp(self):
        super().setUp()
        self.create_catalog()

    def add(self, pid, name=None, date='2020-06-15T12:00:00', status='Pending', digest=None, folder='trip', mtime=False):
        src=self.cfg.source/folder/(name or f'preview-{pid}.jpg')
        dst=self.cfg.dest/'library'/'old'/src.name
        with catalog.connect(self.cfg.db_path) as c:
            c.execute('INSERT INTO photos(id,source_path,dest_path,status,sha1_hash,metadata_json) VALUES(?,?,?,?,?,?)',
                (pid,str(src),str(dst),status,digest or f'{pid:040x}',json.dumps(dict(date_taken=date,date_source='file_mtime' if mtime else 'exif'))))
            c.commit()
        return src

    def preview(self, **kw):
        response=self.client.post('/api/v1/jobs/transfer-preview',json={'mode':'copy',**kw})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_real_paths_counts_paging_no_writes_and_same_name_sources(self):
        for i in range(1,24): self.add(i,name='same.jpg',folder=f'trip/{i}')
        self.add(24,date='2022-01-01T00:00:00',mtime=True)
        with catalog.connect(self.cfg.db_path) as c: before=c.execute('SELECT COUNT(*) FROM runs').fetchone()[0]
        result=self.preview()
        self.assertEqual((result['total'],result['planned'],result['group_total']),(24,24,2))
        group=result['groups'][0]
        self.assertEqual((group['path'],group['total'],len(group['items'])),('library/2020/06/15',23,20))
        self.assertEqual(result['groups'][1]['path'],'library/Undated/2022')
        self.assertEqual(len({x['source'] for x in group['items']}),20)
        second=self.client.post('/api/v1/jobs/transfer-preview',json=dict(mode='copy',file_ids=result['file_ids'],token=result['token'],folder=group['path'],file_page=2)).json()
        self.assertEqual(len(second['items']),3)
        with catalog.connect(self.cfg.db_path) as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM runs').fetchone()[0],before)
        self.assertFalse((self.cfg.dest/'library').exists())

    def test_folders_paginate_and_unplanned_are_visible(self):
        for i in range(1,26): self.add(i,date=f'{2000+i}-01-02T00:00:00')
        self.add(26,status='Failed')
        self.add(27,status='Completed')
        first=self.preview();second=self.preview(page=2,token=first['token'])
        self.assertEqual((first['group_total'],len(first['groups']),len(second['groups'])),(25,20,5))
        self.assertEqual(first['unplanned_total'],2)
        self.assertEqual({x['photo_id'] for x in first['unplanned']},{26,27})

    def test_literal_scope_missing_ids_and_foreign_source(self):
        self.add(1,folder='trip_%');self.add(2,folder='trip_XX');self.add(3,folder='Trip_%')
        self.assertEqual(self.preview(source_subdir='trip_%')['file_ids'],[1])
        self.assertEqual(self.preview(source_subdir='empty')['total'],0)
        for body in ({'file_ids':[999]}, {'file_ids':[1],'source_subdir':'trip_%'}, {'source_subdir':'../elsewhere'}, {'page':True}, {'mode':'reject'}):
            response=self.client.post('/api/v1/jobs/transfer-preview',json={'mode':'copy',**body})
            self.assertEqual(response.status_code,400,response.text)
        with catalog.connect(self.cfg.db_path) as c:
            c.execute('UPDATE photos SET source_path=? WHERE id=3',(str(self.root/'another-source/photo.jpg'),));c.commit()
        self.assertEqual(self.preview()['file_ids'],[1,2])

    def test_duplicates_follow_representative_and_rejects_not_date_tree(self):
        self.add(1,status='Duplicate',digest='a'*40)
        self.add(2,digest='a'*40,date='2019-01-02T00:00:00')
        self.add(3,status='Rejected_Copied')
        reject=self.cfg.dest/'rejects/2018/02/03/kept-name.jpg'
        with catalog.connect(self.cfg.db_path) as c:
            c.execute('UPDATE photos SET dest_path=? WHERE id=3',(str(reject),));c.commit()
        result=self.preview(mode='move')
        self.assertEqual([(x['path'],x['total']) for x in result['groups']],[('library/2019/01/02',2),('rejects/2018/02/03',1)])
        self.assertIn('Identical',result['groups'][0]['items'][1]['note'])
        self.assertEqual(self.preview(file_ids=[1])['unplanned_total'],1)
        self.assertEqual(self.preview(file_ids=[3])['planned'],0)

    def test_changed_metadata_or_settings_refuse_old_token_and_wrong_scope(self):
        self.add(1);self.add(2)
        before=self.preview()
        with catalog.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET metadata_json=? WHERE id=1",(json.dumps(dict(date_taken='2021-01-02T00:00:00')),));c.commit()
        response=self.client.post('/api/v1/jobs/transfer-preview',json=dict(mode='copy',token=before['token']))
        self.assertEqual(response.status_code,409,response.text)
        response=self.client.post('/api/v1/jobs/start',json=dict(mode='copy',file_ids=before['file_ids'],transfer_preview_token=before['token'],request_id=uuid.uuid4().hex))
        self.assertEqual(response.status_code,409,response.text)
        fresh=self.preview()
        response=self.client.post('/api/v1/jobs/start',json=dict(mode='copy',file_ids=[1],transfer_preview_token=fresh['token'],request_id=uuid.uuid4().hex))
        self.assertEqual(response.status_code,409,response.text)

    def test_generated_copy_uses_preview_and_retry_is_same_job(self):
        webui_api_test.make_photo(self.cfg.source/'preview-real.jpg','preview',exif={36867:'2000:01:02 03:04:05'})
        self.wait_for(self.start(mode='index'))
        plan=self.preview()
        body=dict(mode='copy',file_ids=plan['file_ids'],transfer_preview_token=plan['token'],request_id='preview-copy')
        run=self.start(**body);self.wait_for(run)
        self.assertEqual(self.start(**body),run)
        self.assertTrue((self.cfg.source/'preview-real.jpg').exists())
        self.assertTrue((self.cfg.dest/plan['groups'][0]['path']/'preview-real.jpg').exists())

    def test_engine_rechecks_after_api_preflight(self):
        webui_api_test.make_photo(self.cfg.source/'preview-race.jpg','race',exif={36867:'2000:01:02 03:04:05'})
        self.wait_for(self.start(mode='index')); plan=self.preview()
        runner=self.app_jobs();launch=runner._launch
        def changed(*a,**kw):
            with catalog.connect(self.cfg.db_path) as c:
                c.execute("UPDATE photos SET metadata_json='{}'");c.commit()
            return launch(*a,**kw)
        with mock.patch.object(runner,'_launch',side_effect=changed):
            response=self.client.post('/api/v1/jobs/start',json=dict(mode='copy',file_ids=plan['file_ids'],transfer_preview_token=plan['token'],request_id='preview-race'))
        self.assertEqual(response.status_code,409,response.text)
        self.assertFalse((self.cfg.dest/'library').exists())

    def test_busy_preview_refused(self):
        self.add(1)
        with mock.patch.object(self.app_jobs(),'_probe_lock',return_value=True):
            self.assertEqual(self.client.post('/api/v1/jobs/transfer-preview',json={'mode':'copy'}).status_code,409)

    def test_xmp_filing_matches_delivery_and_sources_are_untouched(self):
        photo=self.cfg.source/'preview-sidecar.jpg'
        webui_api_test.make_photo(photo,'xmp',exif={36867:'2000:01:02 03:04:05'})
        side=photo.with_name(photo.name+'.xmp');side.write_bytes(metadata_index_test.packet('2005-03-04T05:06:07'))
        before=(photo.read_bytes(),side.read_bytes())
        self.wait_for(self.start(mode='index'))
        plan=self.preview()
        self.assertEqual(plan['groups'][0]['path'],'library/2005/03/04')
        self.assertIn('XMP sidecar',plan['groups'][0]['items'][0]['note'])
        run=self.start(mode='copy',file_ids=plan['file_ids'],transfer_preview_token=plan['token'],request_id='sidecar-copy')
        self.wait_for(run)
        self.assertTrue((self.cfg.dest/plan['groups'][0]['path']/photo.name).exists())
        self.assertTrue((self.cfg.dest/plan['groups'][0]['path']/side.name).exists())
        self.assertEqual((photo.read_bytes(),side.read_bytes()),before)
