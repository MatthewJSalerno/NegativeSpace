"""Database foundation tests; synthetic catalogs only, no photo-library access.

Run: python3 -m unittest discover -s tests -p database_test.py -v
"""
import concurrent.futures
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ns_db as db


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'catalog.db'
        db.initialize(self.path)
        self.conn = db.connect(self.path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def run_record(self, conn=None, **kw):
        return db.create_run(conn or self.conn, mode='INDEX', source='/source',
                             destination='/destination', **kw)[0]

    def photo(self):
        run = self.run_record()
        with db.transaction(self.conn):
            photo = self.conn.execute("INSERT INTO photos(source_path,status) VALUES('/source/a.jpg','Pending')").lastrowid
            self.observe(photo, run)
        return photo, run

    def observe(self, photo, run, **kw):
        args = dict(photo_id=photo,run_id=run,source_path='/source/a.jpg',sha1_hash='synthetic',
                    file_size=10,file_mtime=100,birthtime=None,metadata={'DateTimeOriginal':'2001:01:01 00:00:00'},error=None)
        args.update(kw)
        return db.record_source_observation(self.conn, **args)

    def delivery(self, photo, run, *, created, removed, destination='/destination/a.jpg'):
        op = self.conn.execute("INSERT INTO operations(run_id,photo_id,source_path,status,timestamp) VALUES(?,?,?,'Copied','test')", (run,photo,'/source/a.jpg')).lastrowid
        db.link_operation(self.conn,op,photo)
        return db.record_delivery(self.conn,operation_id=op,photo_id=photo,run_id=run,
                                  destination=destination,source_removed=removed,
                                  created=created,sha1_hash='synthetic')

    def test_delivery_origin_reuse_and_rollback(self):
        photo,run = self.photo()
        source = self.conn.execute("SELECT file_id FROM photo_files").fetchone()[0]
        with db.transaction(self.conn):
            child = self.delivery(photo,run,created=True,removed=False)
        self.assertNotEqual(source,child)
        self.assertEqual(self.conn.execute("SELECT origin_file_id FROM file_origins WHERE file_id=?", (child,)).fetchone()[0],source)
        with self.assertRaises(RuntimeError):
            with db.transaction(self.conn):
                self.assertEqual(self.delivery(photo,run,created=False,removed=True),child)
                raise RuntimeError('outcome interrupted')
        self.assertEqual(self.conn.execute("SELECT presence_state FROM file_states WHERE file_id=?", (source,)).fetchone()[0],'present')
        with db.transaction(self.conn):
            self.assertEqual(self.delivery(photo,run,created=False,removed=True),child)
        self.assertEqual(self.conn.execute("SELECT presence_state FROM file_states WHERE file_id=?", (source,)).fetchone()[0],'removed')
        self.assertEqual(self.conn.execute("SELECT count(*) FROM source_snapshots").fetchone()[0],1)

    def test_unknown_destination_origin_and_replacement(self):
        photo,run = self.photo()
        with db.transaction(self.conn):
            old = self.delivery(photo,run,created=False,removed=False)
        self.assertEqual(self.conn.execute("SELECT origin_file_id,kind FROM file_origins WHERE file_id=?", (old,)).fetchone(),(None,'observed_destination'))
        with db.transaction(self.conn):
            new = self.delivery(photo,run,created=True,removed=False)
        self.assertNotEqual(old,new)
        self.assertEqual(self.conn.execute("SELECT presence_state FROM file_states WHERE file_id=?", (old,)).fetchone()[0],'missing')
        self.assertEqual(self.conn.execute("SELECT count(*) FROM file_states WHERE location_role='destination' AND presence_state='present'").fetchone()[0],1)

    def test_originals_immutable_and_later_observations_distinct(self):
        photo, run = self.photo()
        with db.transaction(self.conn):
            self.observe(photo, run, file_mtime=200, metadata={'changed':True})
        self.assertEqual(self.conn.execute('SELECT file_mtime FROM source_snapshots').fetchone()[0],100)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM file_observations').fetchone()[0],2)
        with self.assertRaises(sqlite3.IntegrityError), db.transaction(self.conn):
            self.conn.execute('UPDATE source_snapshots SET file_mtime=300')
        with self.assertRaises(sqlite3.IntegrityError), db.transaction(self.conn):
            self.conn.execute('DELETE FROM files')

    def test_consumed_source_reimport_has_new_identity_and_history(self):
        photo, run = self.photo()
        original = self.conn.execute('SELECT file_id FROM photo_files').fetchone()[0]
        with db.transaction(self.conn):
            op = self.conn.execute("INSERT INTO operations(run_id,photo_id,status,timestamp) VALUES(?,?,'Completed','t')",(run,photo)).lastrowid
            db.link_operation(self.conn,op,photo)
            replacement = self.observe(photo,run,prior_status='Completed')
        self.assertNotEqual(original,replacement)
        self.assertEqual(self.conn.execute('SELECT file_id FROM operation_files').fetchone()[0],original)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM source_snapshots').fetchone()[0],2)

    def test_initial_unknowns_remain_unknown(self):
        run=self.run_record()
        with db.transaction(self.conn):
            photo=self.conn.execute("INSERT INTO photos(source_path,status) VALUES('/source/a.jpg','Failed')").lastrowid
            self.observe(photo,run,file_size=None,file_mtime=None,metadata={},sha1_hash='',error='unreadable')
        with db.transaction(self.conn):self.observe(photo,run)
        self.assertEqual(self.conn.execute('SELECT file_mtime,sha1_hash FROM source_snapshots').fetchone(),(None,None))

    def test_stale_revision_rolls_back_outcome(self):
        photo,run=self.photo()
        with db.transaction(self.conn):db.advance_revision(self.conn,photo,0)
        with self.assertRaises(db.RevisionConflict), db.transaction(self.conn):
            self.conn.execute("INSERT INTO operations(run_id,photo_id,status,timestamp) VALUES(?,?,'Copied','t')",(run,photo))
            db.advance_revision(self.conn,photo,0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM operations').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT revision FROM photo_files').fetchone()[0],1)

    def test_atomic_history_and_state_visible_after_commit(self):
        photo,run=self.photo()
        reader=db.connect(self.path)
        try:
            with db.transaction(self.conn):
                self.conn.execute("UPDATE photos SET status='Copied' WHERE id=?",(photo,))
                op=self.conn.execute("INSERT INTO operations(run_id,photo_id,status,timestamp) VALUES(?,?,'Copied','t')",(run,photo)).lastrowid
                db.link_operation(self.conn,op,photo)
                db.advance_revision(self.conn,photo,0)
                self.assertEqual(reader.execute('SELECT status FROM photos').fetchone()[0],'Pending')
                self.assertEqual(reader.execute('SELECT count(*) FROM operations').fetchone()[0],0)
            self.assertEqual(reader.execute('SELECT status FROM photos').fetchone()[0],'Copied')
            self.assertEqual(reader.execute('SELECT count(*) FROM operation_files').fetchone()[0],1)
        finally:reader.close()

    def test_constraint_error_rolls_back_prior_state_update(self):
        photo,run=self.photo()
        with self.assertRaises(sqlite3.IntegrityError), db.transaction(self.conn):
            self.conn.execute("UPDATE photos SET status='Copied'")
            self.conn.execute("INSERT INTO operations(run_id,status,timestamp) VALUES(9999,'Copied','t')")
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(self.conn.execute('SELECT status FROM photos').fetchone()[0],'Pending')

    def test_settings_snapshot_not_changed_by_later_save(self):
        db.save_settings(self.conn,{'workers':2},expected_revisions={'workers':0})
        run=self.run_record(defaults={'workers':1},request_id='one')
        writer=db.connect(self.path)
        try:db.save_settings(writer,{'workers':4},expected_revisions={'workers':1})
        finally:writer.close()
        self.assertEqual(json.loads(self.conn.execute('SELECT effective_config_json FROM run_configs WHERE run_id=?',(run,)).fetchone()[0])['workers'],2)
        again,created=db.create_run(self.conn,mode='INDEX',source='/source',destination='/destination',defaults={'workers':99},request_id='one')
        self.assertEqual((again,created),(run,False))

    def test_settings_patch_is_all_or_nothing(self):
        db.save_settings(self.conn,{'workers':2},expected_revisions={'workers':0})
        with self.assertRaises(db.RevisionConflict):
            db.save_settings(self.conn,{'exts':['jpg'],'workers':3},expected_revisions={'exts':0,'workers':0})
        self.assertNotIn('exts',db.read_settings(self.conn))

    def test_writer_wait_is_bounded_and_connection_reusable(self):
        writer=db.connect(self.path,timeout=0.02)
        try:
            with db.transaction(self.conn):
                with self.assertRaises(sqlite3.OperationalError):
                    db.save_settings(writer,{'workers':3},expected_revisions={'workers':0})
            db.save_settings(writer,{'workers':3},expected_revisions={'workers':0})
        finally:writer.close()

    def test_racing_settings_saves_do_not_silently_overwrite(self):
        barrier=threading.Barrier(2)
        def worker(n):
            c=db.connect(self.path)
            try:
                barrier.wait(timeout=5)
                try:db.save_settings(c,{'workers':n},expected_revisions={'workers':0});return 'saved'
                except db.RevisionConflict:return 'conflict'
            finally:c.close()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(worker,[2,3])),['conflict','saved'])

    def test_racing_duplicate_requests_create_one_run(self):
        barrier=threading.Barrier(2)
        def worker(_):
            c=db.connect(self.path)
            try:
                barrier.wait(timeout=5)
                return db.create_run(c,mode='INDEX',source='/source',destination='/destination',request_id='same')
            finally:c.close()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(worker,[1,2]))
        self.assertEqual(len({r[0] for r in results}),1)
        self.assertEqual(sorted(r[1] for r in results),[False,True])
        with self.assertRaises(db.RequestConflict):self.run_record(request_id='same',overrides={'workers':4})

    def test_file_under_attention_is_excluded_from_keeper_candidates(self):
        """An unresolved outcome must not let a file authorize deleting anything."""
        photo, run = self.photo()
        with db.transaction(self.conn):
            child = self.delivery(photo, run, created=True, removed=False)
        self.assertEqual(db.keeper_candidates(self.conn, 'synthetic'), ['/destination/a.jpg'])
        with db.transaction(self.conn):
            op = self.conn.execute(
                "INSERT INTO operations(run_id,photo_id,status,timestamp) "
                "VALUES(?,?,'Failed','t')", (run, photo)).lastrowid
            db.open_attention_issue(self.conn, operation_id=op, file_id=child,
                                    category='unestablished_outcome',
                                    summary='recovery could not establish the outcome')
        self.assertEqual(db.keeper_candidates(self.conn, 'synthetic'), [])

    def test_resolving_an_issue_restores_the_candidate(self):
        photo, run = self.photo()
        with db.transaction(self.conn):
            child = self.delivery(photo, run, created=True, removed=False)
            op = self.conn.execute(
                "INSERT INTO operations(run_id,photo_id,status,timestamp) "
                "VALUES(?,?,'Failed','t')", (run, photo)).lastrowid
            issue = db.open_attention_issue(self.conn, operation_id=op, file_id=child,
                                            category='unestablished_outcome', summary='x')
        self.assertEqual(db.keeper_candidates(self.conn, 'synthetic'), [])
        with db.transaction(self.conn):
            db.resolve_attention_issue(self.conn, issue)
        self.assertEqual(db.keeper_candidates(self.conn, 'synthetic'), ['/destination/a.jpg'])

    def test_evidence_is_append_only_and_links_to_its_issue(self):
        photo, run = self.photo()
        with db.transaction(self.conn):
            op = self.conn.execute(
                "INSERT INTO operations(run_id,photo_id,status,timestamp) "
                "VALUES(?,?,'Failed','t')", (run, photo)).lastrowid
            ev = db.record_evidence(self.conn, operation_id=op, file_id=None,
                                    location_role='destination', observed_path='/destination/a.jpg',
                                    observation_kind='stat', result='absent')
            issue = db.open_attention_issue(self.conn, operation_id=op, file_id=None,
                                            category='unestablished_outcome', summary='y',
                                            evidence_ids=[ev])
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM attention_evidence WHERE issue_id=?",
                              (issue,)).fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError), db.transaction(self.conn):
            self.conn.execute("UPDATE operation_evidence SET result='present'")

    def test_no_implicit_creation_or_old_schema_conversion(self):
        missing=Path(self.tmp.name)/'missing.db'
        with self.assertRaises(sqlite3.OperationalError):db.connect(missing)
        self.assertFalse(missing.exists())
        old=Path(self.tmp.name)/'old.db'
        c=sqlite3.connect(old);c.execute('CREATE TABLE photos(id INTEGER)');c.commit();c.close()
        with self.assertRaises(db.SchemaError):db.initialize(old)
        c=sqlite3.connect(old)
        self.assertEqual(c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[('photos',)])
        c.close()

    def test_settings_validation_and_restart(self):
        for values in ({'workers':True},{'workers':0},{'exts':[]},{'unknown':1}):
            with self.assertRaises(ValueError):db.save_settings(self.conn,values,expected_revisions={k:0 for k in values})
        db.save_settings(self.conn,{'exts':['JPG','.jpg','png']},expected_revisions={'exts':0})
        db.initialize(self.path)
        self.assertEqual(db.read_settings(self.conn)['exts']['value'],['.jpg','.png'])

if __name__ == '__main__':unittest.main()
