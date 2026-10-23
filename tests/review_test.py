"""Review decisions and composable gallery filters, with generated catalog records."""
import json
import uuid
from webui_api_test import ApiCase
from engine import ns_db

class ReviewTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.create_catalog()
        with ns_db.connect(self.cfg.db_path) as c:
            for i, (status, size, date) in enumerate([('Copied',(640,480),'0001-01-01'),('Completed',(2400,1600),'2020-01-01'),('Pending',(320,240),None)],1):
                digest=f'{i:040x}'
                c.execute("INSERT INTO photos(id,source_path,dest_path,status,sha1_hash,metadata_json,file_size) VALUES(?,?,?,?,?,?,?)",
                    (i,str(self.cfg.source/f'photo-{i}.jpg'),str(self.cfg.dest/f'library/photo-{i}.jpg'),status,digest,json.dumps({'date_taken':date,'date_source':'DateTimeOriginal' if date else 'file_mtime'}),100))
                c.execute("INSERT INTO contents(hash_algorithm,digest,width,height) VALUES('sha1',?,?,?)",(digest,*size))
            c.commit()

    def enable(self, value=800):
        s=self.client.get('/api/v1/settings').json()['small_image_min']
        response=self.client.put('/api/v1/settings',json={'values':{'small_image_min':value},'revisions':{'small_image_min':s['revision']}})
        self.assertEqual(response.status_code,200,response.text)

    def decision(self, pid=1, reason='small', action='reviewed', note=''):
        detail=self.client.get(f'/api/v1/photos/{pid}/review').json()
        return {'photo_id':pid,'sha1':detail['sha1'],'revision':detail['revision'],'reason':reason,'action':action,'note':note,'request_id':uuid.uuid4().hex}

    def send(self, body):
        return self.client.post(f"/api/v1/photos/{body['photo_id']}/review",json=body)

    def test_choice_is_not_assumed_and_small_images_never_change_transfer_eligibility(self):
        before=self.client.get('/api/v1/status').json()['eligible']
        self.assertEqual(self.client.get('/api/v1/photos?view=review').json()['total'],1)
        self.enable()
        result=self.client.get('/api/v1/photos?view=review').json()
        self.assertEqual([p['id'] for p in result['items']],[1])
        self.assertEqual(result['reasons'],{'all':1,'issues':0,'small':1,'later':0,'date':1})
        self.assertEqual(self.client.get('/api/v1/status').json()['eligible'],before)
        self.enable(None)
        self.assertEqual(self.client.get('/api/v1/photos?view=review').json()['total'],1)

    def test_reviewed_survives_rule_changes_and_does_not_clear_later(self):
        self.enable()
        body=self.decision(reason='later',action='later',note='Only surviving copy')
        self.assertEqual(self.send(body).status_code,200)
        reviewed=self.decision()
        response=self.send(reviewed)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([n['reason'] for n in response.json()['reasons']],['later','date'])
        self.enable(None); self.enable(1000)
        self.assertEqual(self.client.get('/api/v1/photos?view=review&reason=small').json()['total'],0)
        self.assertEqual(self.client.get('/api/v1/photos?view=review&reason=later').json()['total'],1)
        self.assertEqual(self.send(self.decision(reason='later',action='done')).status_code,200)
        self.assertEqual(self.client.get('/api/v1/photos?view=review').json()['total'],1)
        with ns_db.connect(self.cfg.db_path) as c:
            self.assertEqual(c.execute('SELECT status FROM photos WHERE id=1').fetchone()[0],'Copied')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM review_events').fetchone()[0],3)
            self.assertGreaterEqual(ns_db.unbacked_changes(c)[0],3)

    def test_request_replay_and_stale_tabs(self):
        self.enable()
        one=self.decision(); two=self.decision(reason='later',action='later')
        self.assertEqual(self.send(one).status_code,200)
        self.assertEqual(self.send(one).status_code,200)
        self.assertEqual(self.send(two).status_code,409)
        changed={**one,'note':'different'}
        self.assertEqual(self.send(changed).status_code,400)
        with ns_db.connect(self.cfg.db_path) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM review_events').fetchone()[0],1)

    def test_filters_counts_facets_ids_and_position_agree(self):
        self.enable()
        suffix='view=organized&suspicious=true'
        page=self.client.get('/api/v1/photos?'+suffix).json()
        self.assertEqual([p['id'] for p in page['items']],[1])
        self.assertEqual(self.client.get('/api/v1/photos/ids?'+suffix).json()['ids'],[1])
        position=self.client.post('/api/v1/photos/position',json={'photo_id':1,'view':'organized','suspicious':True}).json()
        self.assertEqual(position['position'],0)
        self.assertEqual(self.client.get('/api/v1/photos/types?'+suffix).json()['types'],[{'type':'jpg','photos':1}])
        self.assertEqual(self.client.get('/api/v1/photos?'+suffix+'&undated=true').json()['total'],0)
        self.assertEqual(self.client.get('/api/v1/photos?view=organized&q=photo-3').json()['elsewhere']['unorganized'],1)
        self.assertEqual(self.client.get('/api/v1/photos?view=review&reason=unknown').status_code,400)

    def test_sidebar_counts_match_what_each_link_opens(self):
        self.enable()
        got=self.client.get('/api/v1/photos/places').json()
        for name in ('unorganized','organized','review','rejects'):
            self.assertEqual(got['places'][name],self.client.get('/api/v1/photos?view='+name).json()['total'],name)
        for name,query in (('similar','view=organized&similar=true&match_min=90'),('suspicious','view=organized&suspicious=true'),
                           ('undated','view=organized&undated=true'),('small','view=organized&reason=small'),('later','view=review&reason=later'),('issues','view=organized&reason=issues')):
            listing=self.client.get('/api/v1/photos?view=organized').json()
            counts=listing['reasons'] if name in ('small','later','issues') else listing['chips']
            self.assertEqual(counts[name],self.client.get('/api/v1/photos?'+query).json()['total'],name)
        self.assertEqual(listing['chips']['suspicious'],1)
        self.assertEqual(got['places']['similar'],self.client.get('/api/v1/photos?view=similar&match_min=90').json()['total'])
        self.assertEqual(got['warnings']['attention'],self.client.get('/api/v1/photos?view=unorganized&reason=attention').json()['total'])
        self.assertNotIn('look_into',got)
        self.assertEqual(self.client.get('/api/v1/photos/places?match_min=50').status_code,422)

    def test_changed_content_is_not_silently_marked_reviewed(self):
        self.enable()
        body=self.decision()
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET sha1_hash=? WHERE id=1",('f'*40,));c.commit()
        self.assertEqual(self.send(body).status_code,409)

    def test_invalid_actions_and_oversized_notes_are_refused(self):
        self.enable()
        for changes in ({'reason':[]},{'action':'keep'},{'revision':True},{'note':'x'*501},{'sha1':'../outside'}):
            response=self.send({**self.decision(),**changes})
            self.assertEqual(response.status_code,400,response.text)

    def test_unavailable_photo_cannot_be_bookmarked(self):
        body=self.decision(reason='later', action='later')
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET status='Rejected_Emptied' WHERE id=1")
            c.commit()
        self.assertEqual(self.send(body).status_code,409)
        with ns_db.connect(self.cfg.db_path) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM review_events').fetchone()[0],0)

    def test_history_is_append_only(self):
        import sqlite3
        self.enable()
        self.assertEqual(self.send(self.decision()).status_code,200)
        with ns_db.connect(self.cfg.db_path) as c:
            for sql in ("DELETE FROM review_events", "UPDATE review_events SET note='changed'"):
                with self.assertRaises(sqlite3.IntegrityError):
                    c.execute(sql)

    def test_missing_and_out_of_range_photos_are_not_server_errors(self):
        for pid in (0,-1,99,2**64):
            self.assertEqual(self.client.get(f'/api/v1/photos/{pid}/review').status_code,404)

    def test_library_shows_only_current_review_reasons_and_excludes_rejects(self):
        self.enable()
        self.assertEqual(self.send(self.decision(reason='later',action='later',note='Check this')).status_code,200)
        listing=self.client.get('/api/v1/photos?view=organized').json()
        card=next(p for p in listing['items'] if p['id']==1)
        self.assertEqual([r['reason'] for r in card['review']['reasons']],['small','date','later'])
        self.assertNotIn('history',card['review'])
        self.assertEqual(self.send(self.decision()).status_code,200)
        listing=self.client.get('/api/v1/photos?view=organized').json()
        card=next(p for p in listing['items'] if p['id']==1)
        self.assertEqual([r['reason'] for r in card['review']['reasons']],['date','later'])
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET status='Rejected_Copied' WHERE id=1");c.commit()
        self.assertEqual([p['id'] for p in self.client.get('/api/v1/photos?view=organized').json()['items']],[2])

    def test_index_summary_is_information_not_a_review_reminder(self):
        self.enable()
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("INSERT INTO photos(source_path,status,sha1_hash) VALUES(?,?,?)",(str(self.cfg.source/'copy.jpg'),'Duplicate',f'{3:040x}'))
            c.execute("INSERT INTO photos(source_path,status) VALUES(?,'Failed')",(str(self.cfg.source/'broken.jpg'),))
            c.commit()
        summary=self.client.get('/api/v1/photos?view=unorganized&q=absent').json()['index_summary']
        self.assertEqual(summary,dict(photos=2,ready=1,metadata_held=0,unfinished=0,duplicates=1,small=1,minimum=800,unknown_dimensions=0,suspicious=0,undated=1,failed=1,similar=None,last_index=None,discovery=None))
        self.assertEqual(self.client.get('/api/v1/photos?view=review').json()['total'],1)
        self.assertIsNone(self.client.get('/api/v1/photos?view=organized').json()['index_summary'])
        self.enable(None)
        summary=self.client.get('/api/v1/photos?view=unorganized').json()['index_summary']
        self.assertIsNone(summary['minimum'])

    def test_summary_links_share_membership_across_pages_ids_facets_and_navigation(self):
        self.enable()
        with ns_db.connect(self.cfg.db_path) as c:
            for pid, status, digest in [(4,'Pending','unknown'), (5,'Processing','unfinished'), (6,'Failed','failed'),
                                        (7,'Duplicate',f'{3:040x}'), (8,'Duplicate',f'{3:040x}')]:
                c.execute("INSERT INTO photos(id,source_path,status,sha1_hash) VALUES(?,?,?,?)",
                          (pid,str(self.cfg.source/f'summary-{pid}.jpg'),status,digest))
            c.commit()
        scopes={'ready':[3,4], 'indexed':[3,4], 'identical':[3], 'unknown_dimensions':[4],
                'unfinished':[5], 'failed':[6], 'metadata_held':[]}
        for scope, ids in scopes.items():
            with self.subTest(scope=scope):
                query=f'view=unorganized&source_summary={scope}'
                page=self.client.get('/api/v1/photos?'+query).json()
                self.assertEqual(sorted(p['id'] for p in page['items']),ids)
                self.assertEqual(page['total'],len(ids))
                self.assertEqual(sorted(self.client.get('/api/v1/photos/ids?'+query).json()['ids']),ids)
                types=self.client.get('/api/v1/photos/types?'+query).json()['types']
                self.assertEqual(sum(t['photos'] for t in types),len(ids))
                timeline=self.client.get('/api/v1/photos/timeline?'+query).json()
                self.assertEqual(sum(t['count'] for t in timeline['months'])+timeline['undated'],len(ids))
                folders=self.client.get('/api/v1/photos/folders?'+query).json()
                self.assertEqual(folders['top_files']['photos'],len(ids))
                for pid in ids:
                    position=self.client.post('/api/v1/photos/position',json={
                        'photo_id':pid,'view':'unorganized','source_summary':scope,'page_size':1}).json()
                    result=self.client.get('/api/v1/photos?'+query+f"&page_size=1&page={position['page']}").json()
                    self.assertEqual([p['id'] for p in result['items']],[pid])
                self.assertEqual(self.client.get('/api/v1/photos?'+query+'&q=does-not-exist').json()['total'],0)
                self.assertEqual(self.client.get('/api/v1/photos?view=organized&source_summary='+scope).json()['total'],0)
        self.assertEqual(self.client.get('/api/v1/photos?view=unorganized').json()['index_summary']['duplicates'],2)
        # Facts links count Pending photos; unfinished/failed records do not leak in.
        self.assertEqual(self.client.get('/api/v1/photos?view=unorganized&source_summary=indexed&undated=true').json()['total'],2)
        self.assertEqual(self.client.get('/api/v1/photos?view=unorganized&source_summary=indexed&size_below=800').json()['total'],1)
        for endpoint in ('photos','photos/ids','photos/types','photos/timeline','photos/folders'):
            self.assertEqual(self.client.get('/api/v1/'+endpoint+'?source_summary=invalid').status_code,400)

    def test_discovery_breakdown_is_the_same_snapshot_in_summary_and_log(self):
        with ns_db.connect(self.cfg.db_path) as c:
            rid=c.execute("INSERT INTO runs(mode,status,started_at,ended_at) VALUES('INDEX','Completed','start','end')").lastrowid
            c.commit()
            ns_db.record_discovery(c,rid,eligible_by_extension={'.jpg':2,'.png':1},
                excluded_by_extension={'.cr2':2,'.xmp':3,'.mov':4,'.txt':5,'':6,'.json':7},unreadable=1)
            c.commit()
        expected=dict(files_found=30,eligible=3,photos={'.jpg':2,'.png':1},disabled_photos={'.cr2':2},
                      sidecars=3,videos=4,other=18,partial=True,unreadable=1)
        def summary():
            return self.client.get('/api/v1/photos?view=unorganized&q=absent').json()['index_summary']['discovery']
        self.assertEqual(summary(),expected)
        from webui import outcomes
        self.assertEqual(outcomes.get_run(self.cfg.db_path,rid)['discovery'],expected)
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET status='Copied' WHERE status='Pending'")
            c.commit()
        self.enable(None)
        self.assertEqual(summary(),expected,'Copy and Settings must not rewrite the recorded walk')
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("INSERT INTO runs(mode,status,started_at,ended_at) VALUES('INDEX','Completed','scoped','end')")
            c.commit()
        self.assertIsNone(summary(),'A scoped run must not inherit counts from an earlier full walk')

    def test_summary_dismissal_identity_follows_finished_index_only(self):
        def summary_index():
            return self.client.get('/api/v1/photos?view=unorganized').json()['index_summary']['last_index']
        with ns_db.connect(self.cfg.db_path) as c:
            first=c.execute("INSERT INTO runs(mode,status,started_at,ended_at) VALUES('INDEX','Completed','2026-01-01T00:00:00Z','2026-01-01T00:01:00Z')").lastrowid
            c.execute("INSERT INTO runs(mode,status,started_at,ended_at) VALUES('COPY','Completed','2026-01-02T00:00:00Z','2026-01-02T00:01:00Z')")
            pending=c.execute("INSERT INTO runs(mode,status,started_at) VALUES('INDEX','Running','2026-01-03T00:00:00Z')").lastrowid
            c.commit()
        self.assertEqual(summary_index(),dict(id=first,started_at='2026-01-01T00:00:00Z'))
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE runs SET status='Completed',ended_at='2026-01-03T00:01:00Z' WHERE id=?",(pending,));c.commit()
        self.assertEqual(summary_index(),dict(id=pending,started_at='2026-01-03T00:00:00Z'))

    def test_library_size_filter_matches_its_chip_and_keeps_location(self):
        self.enable()
        listing=self.client.get('/api/v1/photos?view=organized').json()
        self.assertEqual(listing['chips']['small'],1)
        filtered=self.client.get('/api/v1/photos?view=organized&reason=small').json()
        self.assertEqual([p['id'] for p in filtered['items']],[1])
        self.assertEqual(filtered['total'],listing['chips']['small'])
        self.assertEqual(self.send(self.decision()).status_code,200)
        self.assertEqual(self.client.get('/api/v1/photos?view=organized&reason=small').json()['total'],0)
        self.assertEqual(self.client.get('/api/v1/photos?view=organized').json()['total'],2)

    def test_review_decisions_refuse_every_non_library_state(self):
        for status in ('Pending', 'Processing', 'Failed', 'Rejected', 'Rejected_Copied', 'Rejected_Emptied', 'Duplicate', 'Removed_Duplicate'):
            with self.subTest(status=status):
                with ns_db.connect(self.cfg.db_path) as c:
                    c.execute("UPDATE photos SET status=? WHERE id=3", (status,)); c.commit()
                body=self.decision(3,reason='later',action='later')
                response=self.send(body)
                self.assertEqual(response.status_code,409,response.text)
                self.assertEqual(self.client.get('/api/v1/photos/3/review').json()['reasons'],[])
        with ns_db.connect(self.cfg.db_path) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM review_events').fetchone()[0],0)

    def test_bookmark_leaves_inbox_when_photo_leaves_library(self):
        self.enable()
        self.assertEqual(self.send(self.decision(reason='later',action='later')).status_code,200)
        for status in ('Rejected_Copied','Failed','Pending'):
            with self.subTest(status=status):
                with ns_db.connect(self.cfg.db_path) as c:
                    c.execute("UPDATE photos SET status=? WHERE id=1",(status,));c.commit()
                self.assertEqual(self.client.get('/api/v1/photos?view=review').json()['total'],0)
                detail=self.client.get('/api/v1/photos/1/review').json()
                self.assertEqual(detail['reasons'],[])
                self.assertEqual(len(detail['history']),1)

    def test_failed_sources_are_not_photo_date_facts(self):
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET status='Failed' WHERE id=3");c.commit()
        self.assertEqual(self.client.get('/api/v1/photos?view=unorganized&undated=true').json()['total'],0)
        stats=self.client.get('/api/v1/stats').json()
        self.assertEqual(stats['library']['failed_source'],1)
        self.assertEqual(stats['library']['photos'],2)
        self.assertEqual(stats['library']['organized'],2)


    def test_bookmark_presets_keep_history_and_request_replay(self):
        self.enable()
        body = self.decision(reason='later', action='later', note='Compare family copies')
        body['bookmark_reason'] = 'keep'
        self.assertEqual(self.send(body).status_code, 200)
        keep = self.decision(reason='later', action='keep')
        result = self.send(keep)
        self.assertEqual(result.status_code, 200, result.text)
        history = result.json()['history']
        self.assertEqual(history[0]['action'], 'keep')
        self.assertEqual(history[0]['note'], 'Compare family copies')
        self.assertEqual(history[0]['bookmark_reason'], 'keep')
        self.assertEqual([r['reason'] for r in result.json()['reasons']], ['small','date'])
        self.assertEqual(self.send(keep).json()['history'], history)
        self.assertEqual(self.client.get('/api/v1/photos?view=organized').json()['total'], 2)

    def test_bookmark_reason_and_note_limits(self):
        for preset, note in [('unknown', ''), ('date', 'x'*61), ([], '')]:
            body = self.decision(reason='later', action='later', note=note)
            body['bookmark_reason'] = preset
            self.assertEqual(self.send(body).status_code, 400)
        body = self.decision(reason='later', action='later', note='x'*60)
        body['bookmark_reason'] = 'ask'
        self.assertEqual(self.send(body).status_code, 200)
        self.assertEqual(self.send(self.decision(reason='later', action='keep')).status_code, 400)

    def test_size_facts_apply_to_source_and_rejects_without_review_actions(self):
        self.enable(None)
        source=self.client.get('/api/v1/photos?view=unorganized&size_below=500').json()
        self.assertEqual([p['id'] for p in source['items']],[3])
        self.assertEqual(source['reasons'],{})
        rejected_path = self.cfg.dest / 'rejects' / 'photo-1.jpg'
        rejected_path.parent.mkdir(parents=True, exist_ok=True)
        rejected_path.write_bytes(b'generated rejected fixture')
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET status='Rejected_Copied',dest_path=? WHERE id=1", (str(rejected_path),))
            c.commit()
        rejected=self.client.get('/api/v1/photos?view=rejects&size_below=500').json()
        self.assertEqual([p['id'] for p in rejected['items']],[1])
        self.assertEqual(self.client.get('/api/v1/photos/ids?view=rejects&size_below=500').json()['ids'],[1])
        self.assertEqual(self.client.get('/api/v1/photos?view=rejects&size_below=480').json()['total'],0)
        self.assertEqual(self.client.get('/api/v1/photos?view=review&size_below=500').json()['total'],0)

    def test_size_browsing_is_independent_and_agrees_across_queries(self):
        self.enable()
        self.assertEqual(self.send(self.decision()).status_code, 200)
        self.enable(None)
        self.assertEqual(self.client.get('/api/v1/photos?view=review&reason=small').json()['total'], 0)
        params = {'view':'organized', 'size_below':750}
        listing = self.client.get('/api/v1/photos', params=params).json()
        self.assertEqual([p['id'] for p in listing['items']], [1])
        self.assertEqual(self.client.get('/api/v1/photos/ids', params=params).json()['ids'], [1])
        self.assertEqual(sum(t['photos'] for t in self.client.get('/api/v1/photos/types', params=params).json()['types']), 1)
        self.assertEqual(sum(t['count'] for t in self.client.get('/api/v1/photos/timeline', params=params).json()['months']), 1)
        position = self.client.post('/api/v1/photos/position', json={**params,'photo_id':1,'sort':'newest'}).json()
        self.assertEqual(position['position'], 0)
        self.assertIsNone(position['next_id'])
        source = self.client.get('/api/v1/photos?view=unorganized&size_below=750').json()
        self.assertEqual([p['id'] for p in source['items']], [3])
        self.assertEqual(self.client.get('/api/v1/photos/folders', params={**params,'view':'source'}).status_code, 200)

    def test_bookmark_order_agrees_with_position_and_pages(self):
        for pid,preset in [(1,'ask'),(2,'date')]:
            body=self.decision(pid=pid, reason='later', action='later')
            body['bookmark_reason']=preset
            self.assertEqual(self.send(body).status_code,200)
        params={'view':'review','reason':'later','sort':'bookmark','page_size':1}
        first=self.client.get('/api/v1/photos',params=params).json()
        second=self.client.get('/api/v1/photos',params={**params,'page':2}).json()
        self.assertEqual(first['items'][0]['id'],2)
        self.assertEqual(second['items'][0]['id'],1)
        position=self.client.post('/api/v1/photos/position',json={**params,'photo_id':2}).json()
        self.assertEqual(position['next_id'],1)


    def date_answer(self):
        body = self.decision(reason='date', action='correct')
        body['date_taken'] = self.client.get('/api/v1/photos/1/review').json()['date_taken']
        return body

    def test_date_confirmation_clears_only_reminder_keeps_facts_and_replays(self):
        self.enable()
        self.assertEqual(self.send(self.decision(reason='later', action='later')).status_code, 200)
        before = self.client.get('/api/v1/photos/1').json()
        answer = self.date_answer()
        result = self.send(answer)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()['date_confirmed'])
        self.assertEqual([r['reason'] for r in result.json()['reasons']], ['small','later'])
        self.assertEqual(self.send(answer).json()['revision'], result.json()['revision'])
        self.assertEqual(self.client.get('/api/v1/photos?view=review&reason=date').json()['total'], 0)
        self.assertEqual(self.client.get('/api/v1/photos?view=organized&suspicious=true').json()['total'], 1)
        after = self.client.get('/api/v1/photos/1').json()
        for key in ('status','sha1_hash','date_taken','date_source','dest_path'):
            self.assertEqual(before.get(key), after.get(key), key)

    def test_confirmation_survives_rule_content_and_unrelated_metadata_changes(self):
        self.assertEqual(self.send(self.date_answer()).status_code, 200)
        with ns_db.connect(self.cfg.db_path) as c:
            ns_db.save_settings(c, {'suspicious_min_year':2000}, expected_revisions={'suspicious_min_year':0})
            c.execute("UPDATE photos SET sha1_hash=?,metadata_json=json_set(metadata_json,'$.orientation',6) WHERE id=1", ('e'*40,))
            c.commit()
        detail = self.client.get('/api/v1/photos/1/review').json()
        self.assertTrue(detail['date_confirmed'])
        self.assertNotIn('date', [r['reason'] for r in detail['reasons']])
        self.assertEqual(len(detail['history']), 1)

    def test_date_changed_outside_editor_requires_new_answer_even_if_changed_back(self):
        answer = self.date_answer()
        self.assertEqual(self.send(answer).status_code, 200)
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET metadata_json=json_set(metadata_json,'$.date_taken','0002-01-01') WHERE id=1")
            c.execute("UPDATE photos SET metadata_json=json_set(metadata_json,'$.date_taken','0001-01-01') WHERE id=1")
            c.commit()
        detail = self.client.get('/api/v1/photos/1/review').json()
        self.assertFalse(detail['date_confirmed'])
        self.assertIn('date', [r['reason'] for r in detail['reasons']])
        # Replaying the old request returns current state, never re-confirms it.
        self.assertFalse(self.send(answer).json()['date_confirmed'])

    def test_stale_date_answer_and_ineligible_locations_are_refused(self):
        body = self.date_answer()
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET metadata_json=json_set(metadata_json,'$.date_taken','0002-01-01') WHERE id=1")
            c.commit()
        self.assertEqual(self.send(body).status_code, 409)
        for status in ('Pending', 'Rejected_Copied', 'Failed'):
            with ns_db.connect(self.cfg.db_path) as c:
                c.execute('UPDATE photos SET status=? WHERE id=1', (status,)); c.commit()
            self.assertEqual(self.send(self.date_answer()).status_code, 409)
        with ns_db.connect(self.cfg.db_path) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM review_date_confirmations').fetchone()[0], 0)

    def test_date_confirmation_requires_exact_current_value(self):
        good = self.date_answer()
        for value in (None, [], '', '0002-01-01'):
            result = self.send({**good, 'date_taken':value})
            self.assertIn(result.status_code, (400,409), result.text)
        self.assertEqual(self.send({k:v for k,v in good.items() if k!='date_taken'}).status_code, 400)

    def test_automatic_date_clearing_is_atomic_once_and_reads_do_not_write(self):
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET metadata_json=json_set(metadata_json,'$.date_taken','2020-01-01') WHERE id=1")
            c.rollback()
            self.assertEqual(c.execute('SELECT COUNT(*) FROM review_events').fetchone()[0], 0)
            c.execute("UPDATE photos SET metadata_json=json_set(metadata_json,'$.date_taken','2020-01-01') WHERE id=1")
            c.commit()
            c.execute("UPDATE photos SET metadata_json=json_set(metadata_json,'$.date_taken','2020-01-01') WHERE id=1")
            c.commit()
        for _ in range(3):
            detail = self.client.get('/api/v1/photos/1/review').json()
            self.client.get('/api/v1/photos?view=review')
        self.assertEqual(len(detail['history']), 1)
        self.assertEqual(detail['history'][0]['cause'], 'date_changed')
        self.assertEqual(detail['history'][0]['action'], 'cleared')

    def test_size_setting_clears_once_and_can_raise_a_new_unanswered_concern(self):
        self.enable()
        self.assertEqual(self.send(self.decision(reason='later', action='later')).status_code,200)
        self.enable(400)
        self.enable(400)
        detail = self.client.get('/api/v1/photos/1/review').json()
        cleared = [e for e in detail['history'] if e['action']=='cleared']
        self.assertEqual([e['cause'] for e in cleared], ['size_rule_changed'])
        self.assertIn('later', [r['reason'] for r in detail['reasons']])
        self.enable(800)
        self.assertIn('small', [r['reason'] for r in self.client.get('/api/v1/photos/1/review').json()['reasons']])

    def test_dimension_change_records_clearing_for_pending_size_only(self):
        self.enable()
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE contents SET width=2400,height=1600 WHERE digest=?", (f'{1:040x}',)); c.commit()
            c.execute("UPDATE contents SET width=2400,height=1600 WHERE digest=?", (f'{1:040x}',)); c.commit()
        events = self.client.get('/api/v1/photos/1/review').json()['history']
        self.assertEqual([e['cause'] for e in events], ['dimensions_changed'])
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE contents SET width=640,height=480 WHERE digest=?", (f'{1:040x}',)); c.commit()
        self.assertEqual(self.send(self.decision()).status_code, 200)
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE contents SET width=2400,height=1600 WHERE digest=?", (f'{1:040x}',)); c.commit()
        self.assertEqual(len(self.client.get('/api/v1/photos/1/review').json()['history']), 2)

    def test_date_setting_records_why_only_unconfirmed_concerns_clear(self):
        with ns_db.connect(self.cfg.db_path) as c:
            ns_db.save_settings(c, {'suspicious_min_year':2000}, expected_revisions={'suspicious_min_year':0})
            ns_db.save_settings(c, {'suspicious_min_year':1}, expected_revisions={'suspicious_min_year':1})
        detail = self.client.get('/api/v1/photos/1/review').json()
        self.assertEqual([e['cause'] for e in detail['history']], ['date_rule_changed'])
        self.assertFalse(detail['date_confirmed'])


    def test_first_explicit_date_setting_uses_previous_default_for_history(self):
        with ns_db.connect(self.cfg.db_path) as c:
            ns_db.save_settings(c, {'suspicious_min_year':1}, expected_revisions={'suspicious_min_year':0})
        history = self.client.get('/api/v1/photos/1/review').json()['history']
        self.assertEqual([e['cause'] for e in history], ['date_rule_changed'])

    def test_new_content_without_dimensions_does_not_claim_size_resolved(self):
        self.enable()
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute('UPDATE photos SET sha1_hash=? WHERE id=1', ('d'*40,))
            ns_db.content_for_digest(c, digest='d'*40, width=640, height=480)
            c.commit()
        detail = self.client.get('/api/v1/photos/1/review').json()
        self.assertIn('small', [r['reason'] for r in detail['reasons']])
        self.assertEqual(detail['history'], [])


    def test_calendar_advance_records_clearing_once_at_next_job(self):
        with ns_db.connect(self.cfg.db_path) as c:
            year = int(c.execute("SELECT strftime('%Y','now')").fetchone()[0])
            c.execute("UPDATE photos SET metadata_json=json_set(metadata_json,'$.date_taken',?) WHERE id=2", (f'{year+1}-01-01',))
            c.execute('UPDATE review_calendar SET year=?', (year-1,)); c.commit()
            first,_ = ns_db.create_run(c, mode='INDEX', source=str(self.cfg.source), destination=str(self.cfg.dest))
            ns_db.create_run(c, mode='INDEX', source=str(self.cfg.source), destination=str(self.cfg.dest))
        history = self.client.get('/api/v1/photos/2/review').json()['history']
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['cause'], 'calendar_year_changed')
        self.assertEqual(history[0]['run_id'], first)


    def test_confirmed_date_changing_does_not_claim_an_unanswered_concern_cleared(self):
        self.assertEqual(self.send(self.date_answer()).status_code, 200)
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET metadata_json=json_set(metadata_json,'$.date_taken','2020-01-01') WHERE id=1")
            c.commit()
        detail = self.client.get('/api/v1/photos/1/review').json()
        self.assertFalse(detail['date_confirmed'])
        self.assertEqual(len(detail['history']), 1)
        self.assertEqual(detail['history'][0]['action'], 'correct')
