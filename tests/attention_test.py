"""Evidence-based recovery checks use isolated generated files and catalogs."""
import hashlib
import json
from unittest.mock import patch
from webui_api_test import ApiCase
from engine import ns_db, runtime
from engine import attention
from webui import outcomes, catalog


class AttentionTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.create_catalog()
        self.source = self.cfg.source / 'generated.jpg'
        self.dest = self.cfg.dest / 'library' / 'generated.jpg'
        self.dest.parent.mkdir(parents=True)
        self.source.write_bytes(b'generated fixture content')
        self.digest = hashlib.sha1(self.source.read_bytes()).hexdigest()
        with ns_db.connect(self.cfg.db_path) as c:
            self.original_run = ns_db.create_run(c, mode='MOVE', source=str(self.cfg.source), destination=str(self.cfg.dest))[0]
            self.check_run = ns_db.create_run(c, mode='CHECK', source=None, destination=None)[0]
            with ns_db.transaction(c):
                self.pid = c.execute('INSERT INTO photos(source_path,dest_path,sha1_hash,status) VALUES(?,?,?,?)',
                    (str(self.source), str(self.dest), self.digest, 'Failed')).lastrowid
                self.fid = ns_db.record_source_observation(c, photo_id=self.pid, run_id=self.original_run,
                    source_path=str(self.source), sha1_hash=self.digest, file_size=self.source.stat().st_size,
                    file_mtime=self.source.stat().st_mtime, birthtime=None, metadata={}, error=None)
                self.op = ns_db.begin_operation(c, run_id=self.original_run, photo_id=self.pid,
                    source_path=str(self.source), dest_path=str(self.dest), kind='move', expected={'sha1_hash':self.digest,'created':True})
                ns_db.settle_operation(c, self.op, status='Failed', step='recovery', outcome='unestablished')
                self.issue = ns_db.open_attention_issue(c, operation_id=self.op, file_id=self.fid,
                    category='unestablished_outcome', summary='Outcome could not be verified.')
        runtime.cancel_requested.clear()

    def check(self):
        return attention.check_issue(self.cfg.db_path, self.cfg.source, self.cfg.dest, self.check_run, self.issue)

    def report(self):
        with ns_db.connect(self.cfg.db_path) as c:
            return attention.for_photo(c, self.pid)

    def test_verified_delivery_resolves_without_deleting_source_or_rewriting_old_outcome(self):
        self.dest.write_bytes(self.source.read_bytes())
        before = self.source.read_bytes()
        result = self.check()
        self.assertTrue(result['resolved'], result)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.dest.read_bytes(), before)
        self.assertEqual(self.report(), [])
        with ns_db.connect(self.cfg.db_path) as c:
            self.assertEqual(c.execute('SELECT status FROM photos WHERE id=?',(self.pid,)).fetchone()[0], 'Copied')
            self.assertEqual(c.execute('SELECT status FROM operations WHERE id=?',(self.op,)).fetchone()[0], 'Failed')
            self.assertIsNotNone(c.execute('SELECT resolution_event_id FROM attention_issues').fetchone()[0])
            self.assertGreater(c.execute('SELECT COUNT(*) FROM operation_evidence').fetchone()[0], 0)

    def test_source_only_verified_is_retryable_but_not_automatically_copied(self):
        self.assertTrue(self.check()['resolved'])
        self.assertFalse(self.dest.exists())
        with ns_db.connect(self.cfg.db_path) as c:
            self.assertEqual(c.execute('SELECT status FROM photos').fetchone()[0], 'Pending')

    def test_mismatch_missing_both_symlink_and_cancellation_keep_issue(self):
        self.dest.write_bytes(b'different')
        self.assertFalse(self.check()['resolved'])
        self.dest.unlink(); self.source.unlink()
        self.assertFalse(self.check()['resolved'])
        self.source.write_bytes(b'generated fixture content')
        self.dest.symlink_to(self.source)
        self.assertFalse(self.check()['resolved'])
        self.dest.unlink(); self.dest.write_bytes(self.source.read_bytes())
        runtime.cancel_requested.set()
        self.assertFalse(self.check()['resolved'])
        runtime.cancel_requested.clear()
        self.assertEqual(len(self.report()), 1)

    def test_outside_destination_is_not_read(self):
        outside = self.root / 'outside.jpg'
        outside.write_bytes(self.source.read_bytes())
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute('UPDATE operations SET dest_path=? WHERE id=?',(str(outside),self.op)); c.commit()
        with patch('engine.reconcile._recovery_verify', side_effect=AssertionError('must not read')):
            self.assertFalse(self.check()['resolved'])

    def test_stale_content_cannot_repair_current_photo(self):
        self.dest.write_bytes(self.source.read_bytes())
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET sha1_hash=? WHERE id=?",('a'*40,self.pid)); c.commit()
        self.assertFalse(self.check()['resolved'])

    def test_api_exposes_issues_in_photo_and_logs_but_only_library_in_inbox(self):
        data = self.client.get(f'/api/v1/photos/{self.pid}/issues')
        self.assertEqual(data.status_code,200,data.text)
        self.assertEqual(data.json()['items'][0]['issue_id'],self.issue)
        self.assertEqual(self.client.get('/api/v1/photos?view=review&reason=issues').json()['total'],0)
        with ns_db.connect(self.cfg.db_path) as c:
            c.execute("UPDATE photos SET status='Copied' WHERE id=?",(self.pid,)); c.commit()
        self.assertEqual(self.client.get('/api/v1/photos?view=review&reason=issues').json()['total'],1)
        logs = self.client.get('/api/v1/operations').json()['items']
        self.assertEqual(next(o for o in logs if o['id']==self.op)['issues'][0]['issue_id'],self.issue)

    def test_check_api_validates_input_and_replays_request(self):
        self.dest.write_bytes(self.source.read_bytes())
        self.assertEqual(self.client.post('/api/v1/issues/check',json={'issue_id':True}).status_code,400)
        body={'issue_id':self.issue,'request_id':'check-fixture'}
        result=self.client.post('/api/v1/issues/check',json=body)
        self.assertEqual(result.status_code,202,result.text)
        self.wait_for(result.json()['id'])
        replay=self.client.post('/api/v1/issues/check',json=body)
        self.assertEqual(replay.status_code,202,replay.text)
        self.assertEqual(replay.json()['id'],result.json()['id'])
        self.assertEqual(self.report(),[])

    def test_verified_destination_without_source_records_observed_delivery(self):
        self.dest.write_bytes(self.source.read_bytes()); self.source.unlink()
        self.assertTrue(self.check()['resolved'])
        with ns_db.connect(self.cfg.db_path) as c:
            self.assertEqual(c.execute('SELECT status FROM photos').fetchone()[0],'Found_At_Destination')
        self.assertTrue(self.dest.exists())

    def relocation(self, kind='reject'):
        self.dest.write_bytes(self.source.read_bytes())
        old = self.dest
        new = self.cfg.dest / 'rejects' / 'generated.jpg'
        new.parent.mkdir(parents=True)
        with ns_db.connect(self.cfg.db_path) as c:
            with ns_db.transaction(c):
                c.execute("UPDATE photos SET status='Copied' WHERE id=?",(self.pid,))
                fid=ns_db.record_delivery(c,operation_id=self.op,photo_id=self.pid,run_id=self.original_run,
                    destination=str(old),source_removed=False,created=True,sha1_hash=self.digest)
                self.op=ns_db.begin_operation(c,run_id=self.original_run,photo_id=self.pid,
                    source_path=str(old),dest_path=str(new),kind=kind,expected={'sha1_hash':self.digest,'file_id':fid,
                    'status_before':'Copied','status_after':'Rejected_Copied','operation_status':'Rejected_Copied'})
                ns_db.settle_operation(c,self.op,status='Failed',step='recovery',outcome='unestablished')
                c.execute('UPDATE attention_issues SET file_id=?,operation_id=? WHERE issue_id=?',(fid,self.op,self.issue))
        return old,new

    def test_relocation_after_external_restoration_repairs_catalog_and_deletion_gate(self):
        old,new=self.relocation()
        old.rename(new)
        self.assertTrue(self.check()['resolved'])
        self.assertTrue(new.exists()); self.assertFalse(old.exists())
        with ns_db.connect(self.cfg.db_path) as c:
            self.assertEqual(c.execute('SELECT status,dest_path FROM photos').fetchone(),('Rejected_Copied',str(new)))
            self.assertEqual(ns_db.paths_needing_attention(c,[str(new)]),set())

    def test_relocation_two_names_is_never_completed_by_deleting_one(self):
        old,new=self.relocation()
        new.write_bytes(old.read_bytes())
        self.assertFalse(self.check()['resolved'])
        self.assertTrue(old.exists()); self.assertTrue(new.exists())
        with ns_db.connect(self.cfg.db_path) as c:
            self.assertEqual(ns_db.paths_needing_attention(c,[str(old)]),{str(old)})

    def test_failed_catalog_commit_does_not_clear_issue(self):
        self.dest.write_bytes(self.source.read_bytes())
        with patch('engine.ns_db.resolve_attention_issue',side_effect=RuntimeError('injected write failure')):
            with self.assertRaisesRegex(RuntimeError,'injected'):
                self.check()
        with ns_db.connect(self.cfg.db_path) as c:
            self.assertEqual(c.execute('SELECT status FROM photos').fetchone()[0],'Failed')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM operations').fetchone()[0],1)
        self.assertEqual(len(self.report()),1)
        self.assertTrue(self.source.exists()); self.assertTrue(self.dest.exists())

    def test_transfer_intent_without_hash_uses_immutable_observation(self):
        self.dest.write_bytes(self.source.read_bytes())
        with ns_db.connect(self.cfg.db_path) as c:
            with ns_db.transaction(c):
                op=ns_db.begin_operation(c,run_id=self.original_run,photo_id=self.pid,source_path=str(self.source),
                    dest_path=str(self.dest),kind='move',expected={'created':True})
                c.execute('UPDATE attention_issues SET operation_id=? WHERE issue_id=?',(op,self.issue))
        self.assertTrue(self.check()['resolved'])

    def test_same_underlying_file_and_changed_during_read_remain_unresolved(self):
        import os
        os.link(self.source,self.dest)
        self.assertFalse(self.check()['resolved'])
        self.dest.unlink();self.dest.write_bytes(self.source.read_bytes())
        from engine import reconcile
        verify=reconcile._recovery_verify
        def changing(path,expected,**kwargs):
            answer=verify(path,expected,**kwargs)
            if path==self.dest:
                self.source.write_bytes(b'replaced after verification')
            return answer
        with patch('engine.reconcile._recovery_verify',side_effect=changing):
            self.assertFalse(self.check()['resolved'])
        self.assertEqual(len(self.report()),1)

    def test_busy_engine_and_stale_issue_are_refused(self):
        with self.engine_lock_held():
            result=self.client.post('/api/v1/issues/check',json={'issue_id':self.issue,'request_id':'busy'})
        self.assertEqual(result.status_code,409,result.text)
        self.assertEqual(self.client.post('/api/v1/issues/check',json={'issue_id':999999}).status_code,409)
        self.assertEqual(self.client.post('/api/v1/issues/check',json={'issue_id':self.issue,'path':'/untrusted'}).status_code,400)

    def test_check_request_conflicts_are_not_replayed_as_another_issue(self):
        self.dest.write_bytes(self.source.read_bytes())
        first=self.client.post('/api/v1/issues/check',json={'issue_id':self.issue,'request_id':'same-check'})
        self.assertEqual(first.status_code,202,first.text)
        self.wait_for(first.json()['id'])
        conflict=self.client.post('/api/v1/issues/check',json={'issue_id':self.issue+1,'request_id':'same-check'})
        self.assertEqual(conflict.status_code,409,conflict.text)
        self.assertEqual(conflict.json()['error'],'request_conflict')

    def test_unsuccessful_check_is_not_reported_as_recovered(self):
        self.dest.write_bytes(b'different')
        self.assertFalse(self.check()['resolved'])
        with catalog.connect(self.cfg.db_path) as c:
            run = dict(c.execute('SELECT * FROM runs WHERE id=?', (self.check_run,)).fetchone())
            self.assertEqual(outcomes._outcome(c, run, [])['recovered_earlier_work'], 0)
        self.dest.write_bytes(self.source.read_bytes())
        self.assertTrue(self.check()['resolved'])
        with catalog.connect(self.cfg.db_path) as c:
            run = dict(c.execute('SELECT * FROM runs WHERE id=?', (self.check_run,)).fetchone())
            self.assertEqual(outcomes._outcome(c, run, [])['recovered_earlier_work'], 1)
