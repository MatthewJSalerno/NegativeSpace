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
