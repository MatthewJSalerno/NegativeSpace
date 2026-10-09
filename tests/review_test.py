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
        self.assertEqual(self.client.get('/api/v1/photos?view=review').json()['total'],0)
        self.enable()
        result=self.client.get('/api/v1/photos?view=review').json()
        self.assertEqual([p['id'] for p in result['items']],[1])
        self.assertEqual(result['reasons'],{'all':1,'small':1,'later':0})
        self.assertEqual(self.client.get('/api/v1/status').json()['eligible'],before)
        self.enable(None)
        self.assertEqual(self.client.get('/api/v1/photos?view=review').json()['total'],0)

    def test_reviewed_survives_rule_changes_and_does_not_clear_later(self):
        self.enable()
        body=self.decision(reason='later',action='later',note='Only surviving copy')
        self.assertEqual(self.send(body).status_code,200)
        reviewed=self.decision()
        response=self.send(reviewed)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([n['reason'] for n in response.json()['reasons']],['later'])
        self.enable(None); self.enable(1000)
        self.assertEqual(self.client.get('/api/v1/photos?view=review&reason=small').json()['total'],0)
        self.assertEqual(self.client.get('/api/v1/photos?view=review&reason=later').json()['total'],1)
        self.assertEqual(self.send(self.decision(reason='later',action='done')).status_code,200)
        self.assertEqual(self.client.get('/api/v1/photos?view=review').json()['total'],0)
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
                           ('undated','view=organized&undated=true'),('small','view=organized&reason=small'),('later','view=review&reason=later')):
            self.assertEqual(got['look_into'][name],self.client.get('/api/v1/photos?'+query).json()['total'],name)
        self.assertEqual(got['look_into']['suspicious'],1)
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
        self.assertEqual([r['reason'] for r in card['review']['reasons']],['small','later'])
        self.assertNotIn('history',card['review'])
        self.assertEqual(self.send(self.decision()).status_code,200)
        listing=self.client.get('/api/v1/photos?view=organized').json()
        card=next(p for p in listing['items'] if p['id']==1)
        self.assertEqual([r['reason'] for r in card['review']['reasons']],['later'])
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
        self.assertEqual(summary,dict(photos=2,ready=1,unfinished=0,duplicates=1,small=1,minimum=800,unknown_dimensions=0,suspicious=0,undated=1,failed=1,similar=None,last_index=None))
        self.assertEqual(self.client.get('/api/v1/photos?view=review').json()['total'],1)
        self.assertIsNone(self.client.get('/api/v1/photos?view=organized').json()['index_summary'])
        self.enable(None)
        summary=self.client.get('/api/v1/photos?view=unorganized').json()['index_summary']
        self.assertIsNone(summary['minimum'])

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
