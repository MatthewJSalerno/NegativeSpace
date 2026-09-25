"""Database foundation tests; synthetic catalogs only, no photo-library access.

Run: python3 -m unittest discover -s tests -p database_test.py -v
"""
import concurrent.futures
import json
import os
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

    def test_content_identity_is_shared_and_never_downgraded(self):
        with db.transaction(self.conn):
            first = db.content_for_digest(self.conn, digest='abc', phash='p', phash_state='ok',
                                          width=800, height=600)
            # The same bytes seen again are the same identity, not a second row —
            # which is what lets duplicates share one thumbnail.
            again = db.content_for_digest(self.conn, digest='abc')
        self.assertEqual(first, again)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM contents").fetchone()[0], 1)
        # A later scan that learned less (a thumbnail that failed, so no
        # dimensions) must not erase what an earlier one established.
        row = self.conn.execute("SELECT phash,width,height FROM contents WHERE content_id=?",
                                (first,)).fetchone()
        self.assertEqual(tuple(row), ('p', 800, 600))

    def test_content_identity_requires_a_transaction_and_a_digest(self):
        with self.assertRaises(RuntimeError):
            db.content_for_digest(self.conn, digest='abc')
        with db.transaction(self.conn):
            with self.assertRaises(ValueError):
                db.content_for_digest(self.conn, digest='')

    def test_thumbnail_state_is_current_not_history(self):
        with db.transaction(self.conn):
            content = db.content_for_digest(self.conn, digest='abc')
            db.record_thumbnail(self.conn, content_id=content, size=320, availability='failed',
                                failure_category='decode_failed',
                                failure_detail='Image could not be decoded')
            db.record_thumbnail(self.conn, content_id=content, size=320, availability='present',
                                cache_filename='thumbnails/ab/abc.jpg', bytes_on_disk=742)
        rows = self.conn.execute("SELECT availability,cache_filename,bytes,failure_category "
                                 "FROM thumbnail_cache").fetchall()
        # One row per (content, size): a successful regeneration clears the
        # unavailable state rather than accumulating a second entry.
        self.assertEqual(len(rows), 1)
        self.assertEqual(tuple(rows[0]), ('present', 'thumbnails/ab/abc.jpg', 742, None))

    def test_the_two_sizes_are_independent_entries(self):
        with db.transaction(self.conn):
            content = db.content_for_digest(self.conn, digest='abc')
            db.record_thumbnail(self.conn, content_id=content, size=320, availability='present',
                                cache_filename='thumbnails/ab/abc.jpg', bytes_on_disk=700)
            db.record_thumbnail(self.conn, content_id=content, size=1024, availability='present',
                                cache_filename='thumbnails/ab/abc-1024.jpg', bytes_on_disk=9000)
        # Clearing detail previews must not touch grid thumbnails, and the UI
        # reports each size separately — both need per-size totals by SUM.
        totals = dict(self.conn.execute("SELECT size,SUM(bytes) FROM thumbnail_cache GROUP BY size"))
        self.assertEqual(totals, {320: 700, 1024: 9000})

    def test_thumbnail_totals_are_per_size_and_present_only(self):
        with db.transaction(self.conn):
            a = db.content_for_digest(self.conn, digest='a')
            b = db.content_for_digest(self.conn, digest='b')
            c = db.content_for_digest(self.conn, digest='c')
            db.record_thumbnail(self.conn, content_id=a, size=320, availability='present',
                                cache_filename='t/a.jpg', bytes_on_disk=700)
            db.record_thumbnail(self.conn, content_id=b, size=320, availability='present',
                                cache_filename='t/b.jpg', bytes_on_disk=800)
            db.record_thumbnail(self.conn, content_id=a, size=1024, availability='present',
                                cache_filename='t/a-1024.jpg', bytes_on_disk=9000)
            # A failed entry names no cache file and carries no bytes. Counting it
            # would tell the user the gallery can render a photo it cannot.
            db.record_thumbnail(self.conn, content_id=c, size=320, availability='failed',
                                failure_category='decode_failed')
        self.assertEqual(db.thumbnail_cache_totals(self.conn),
                         [(320, 2, 1500), (1024, 1, 9000)])

    def test_thumbnail_totals_are_empty_when_nothing_is_cached(self):
        # The engine loops over this to log its summary, so an empty cache must yield
        # no rows rather than a single zero row.
        self.assertEqual(db.thumbnail_cache_totals(self.conn), [])

    def test_thumbnail_state_requires_a_transaction(self):
        with self.assertRaises(RuntimeError):
            db.record_thumbnail(self.conn, content_id=1, size=320, availability='present')

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

    def test_recovery_links_a_recorded_destination_instead_of_superseding_it(self):
        """Recovery observes; it does not publish.

        record_delivery treats created=True as proof that a previously recorded
        occupant is gone - correct for a genuine re-publication, wrong for
        recovery re-registering a file nothing replaced. Passing created=True
        there would mint a second identity for the same bytes and mark the real
        one missing.
        """
        photo, run = self.photo()
        with db.transaction(self.conn):
            first = self.delivery(photo, run, created=True, removed=False)
        # What recovery must do when a destination identity already exists.
        with db.transaction(self.conn):
            again = self.delivery(photo, run, created=False, removed=False)
        self.assertEqual(again, first, "recovery minted a second identity")
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM file_states WHERE presence_state='missing'")
                .fetchone()[0], 0, "recovery superseded a live identity")
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM file_states WHERE current_path=?",
                              ('/destination/a.jpg',)).fetchone()[0], 1)
        # And the failure mode it replaced, so the rule is pinned from both sides.
        with db.transaction(self.conn):
            superseding = self.delivery(photo, run, created=True, removed=False)
        self.assertNotEqual(superseding, first)
        self.assertEqual(
            self.conn.execute("SELECT presence_state FROM file_states WHERE file_id=?",
                              (first,)).fetchone()[0], 'missing')

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

    def run_row(self, run):
        return self.conn.execute("SELECT status,ended_at,reconciled_by_run_id FROM runs WHERE id=?",
                                 (run,)).fetchone()

    def test_run_lifecycle_follows_the_approved_transitions(self):
        run = self.run_record()
        self.assertEqual(self.run_row(run), ('Preparing', None, None))
        self.assertFalse(db.transition_run(self.conn, run, 'Completed'),
                         'a run that never started its work cannot end Completed')
        self.assertTrue(db.transition_run(self.conn, run, 'Running'))
        self.assertTrue(db.transition_run(self.conn, run, 'Cancelling'))
        self.assertIsNone(self.run_row(run)[1], 'an active state must not stamp an end time')
        # A job that finished before its cancellation took effect reports what happened.
        self.assertTrue(db.transition_run(self.conn, run, 'Completed'))
        status, ended, _ = self.run_row(run)
        self.assertEqual(status, 'Completed')
        self.assertIsNotNone(ended)
        for later in ('Cancelling', 'Running', 'Failed', 'Cancelled'):
            self.assertFalse(db.transition_run(self.conn, run, later), f'terminal run moved to {later}')
        self.assertEqual(self.run_row(run)[:2], ('Completed', ended))

    def test_interrupted_names_its_reconciler_and_claims_no_end_time(self):
        dead, reconciler = self.run_record(), self.run_record()
        with self.assertRaises(ValueError):
            db.transition_run(self.conn, dead, 'Interrupted')
        self.assertTrue(db.transition_run(self.conn, dead, 'Interrupted', reconciled_by=reconciler))
        self.assertEqual(self.run_row(dead), ('Interrupted', None, reconciler))

    def test_every_run_status_is_accepted_by_the_schema(self):
        self.assertEqual(set(db.RUN_STATUSES),
                         set(db.RUN_TRANSITIONS) | set().union(*db.RUN_TRANSITIONS.values()))
        for status in db.RUN_STATUSES:
            with db.transaction(self.conn):
                self.conn.execute("INSERT INTO runs(mode,started_at,status) VALUES('INDEX','t',?)", (status,))
        with self.assertRaises(sqlite3.IntegrityError), db.transaction(self.conn):
            self.conn.execute("INSERT INTO runs(mode,started_at,status) VALUES('INDEX','t','Crashed')")

    def backups(self):
        store = Path(self.tmp.name) / 'backups'
        store.mkdir(exist_ok=True)
        return store

    def test_backup_availability_separates_missing_from_unreachable(self):
        store = self.backups()
        first = db.backup_catalog(self.path, store, Path(self.tmp.name) / 'appdata', trigger='manual')
        second = db.backup_catalog(self.path, store, Path(self.tmp.name) / 'appdata', trigger='manual')
        self.assertEqual((first['outcome'], second['outcome']), ('succeeded', 'succeeded'))
        (store / first['filename']).unlink()
        self.assertTrue(db.refresh_backup_availability(self.conn, store))
        states = [r[0] for r in self.conn.execute("SELECT availability FROM backup_artifacts ORDER BY artifact_id")]
        self.assertEqual(states, ['missing', 'present'])
        # Storage that cannot be reached says nothing about individual files.
        self.assertFalse(db.refresh_backup_availability(self.conn, store / 'unmounted'))
        states = [r[0] for r in self.conn.execute("SELECT availability FROM backup_artifacts ORDER BY artifact_id")]
        self.assertEqual(states, ['unknown', 'unknown'])

    def test_lowering_retention_is_previewed_before_it_prunes(self):
        store = self.backups()
        for _ in range(3):
            db.backup_catalog(self.path, store, Path(self.tmp.name) / 'appdata', trigger='post_job')
        db.backup_catalog(self.path, store, Path(self.tmp.name) / 'appdata', trigger='manual')
        self.assertEqual(db.automatic_backups_beyond(self.conn, 1), 2, 'manual backups must not count')
        self.assertEqual(len(list(store.iterdir())), 4, 'previewing removed files')

    def test_backup_retention_setting_is_validated(self):
        for bad in (0, -1, '5', 2.0, True):
            with self.assertRaises(ValueError):
                db.save_settings(self.conn, {'backup_retention': bad}, expected_revisions={'backup_retention': 0})
        db.save_settings(self.conn, {'backup_retention': 5}, expected_revisions={'backup_retention': 0})
        self.assertEqual(db.backup_retention(self.conn), 5)

    def test_a_compressed_backup_that_does_not_restore_is_never_published(self):
        store = self.backups()
        real = db._file_digest
        db._file_digest = lambda path: b"not the snapshot"
        try:
            result = db.backup_catalog(self.path, store, Path(self.tmp.name) / 'appdata', trigger='manual')
        finally:
            db._file_digest = real
        self.assertEqual((result['outcome'], result['error_category']), ('failed', 'verification_failed'))
        self.assertEqual(list(store.iterdir()), [], 'an unverified or partial file was left behind')
        ok = db.backup_catalog(self.path, store, Path(self.tmp.name) / 'appdata', trigger='manual')
        self.assertEqual([p.name for p in store.iterdir()], [ok['filename']],
                         'the uncompressed snapshot was left beside the published backup')
        self.assertTrue(ok['filename'].endswith('.db.zst'))

    def test_unbacked_changes_count_only_real_changes_after_the_last_backup(self):
        store = self.backups()
        early = self.run_record()
        def op(run, status, when):
            with db.transaction(self.conn):
                self.conn.execute("INSERT INTO operations(run_id, status, timestamp) VALUES (?,?,?)",
                                  (run, status, when))
        op(early, 'Pending', '2026-01-01T00:00:00+00:00')
        self.assertEqual(db.unbacked_changes(self.conn), (1, None, [early]))
        db.backup_catalog(self.path, store, Path(self.tmp.name) / 'appdata', trigger='manual')
        self.assertEqual(db.unbacked_changes(self.conn)[0], 0, 'a record older than the backup counted')
        later = self.run_record()
        op(later, 'Skipped', '2099-01-01T00:00:00+00:00')
        op(later, 'Cancelled', '2099-01-01T00:00:00+00:00')
        self.assertEqual(db.unbacked_changes(self.conn)[0], 0, 'Skipped/Cancelled rows are not changes')
        op(later, 'Copied', '2099-01-01T00:00:00+00:00')
        count, since, runs = db.unbacked_changes(self.conn)
        self.assertEqual((count, runs), (1, [later]))
        self.assertIsNotNone(since)
        self.assertEqual(db.unbacked_changes(self.conn, exclude_run_id=later)[0], 0)

    def test_discovery_is_stored_per_run_and_found_is_eligible_plus_excluded(self):
        run = self.run_record()
        self.assertIsNone(db.read_discovery(self.conn, run), 'a run that walked nothing has no summary')
        db.record_discovery(self.conn, run, eligible=10, excluded_by_extension={'.mov': 3, '': 1}, unreadable=0)
        self.assertEqual(db.read_discovery(self.conn, run),
                         {'files_found': 14, 'eligible': 10, 'excluded': 4,
                          'excluded_by_extension': {'': 1, '.mov': 3}, 'unreadable': 0, 'partial': False})
        other = self.run_record()
        with self.assertRaises(sqlite3.IntegrityError), db.transaction(self.conn):
            self.conn.execute("INSERT INTO run_discovery VALUES (?,5,3,1,'{}',0)", (other,))

    def test_progress_is_one_row_per_phase_in_order_and_done_is_the_sum_of_counts(self):
        run = self.run_record()
        self.assertEqual(db.read_progress(self.conn, run), [], 'a run that started no work has no progress')
        with db.transaction(self.conn):
            db.write_progress(self.conn, run, phase='discovering', seq=1, total=None,
                              counts={'eligible': 7, 'excluded': 2}, started_at='t1')
            db.write_progress(self.conn, run, phase='scanning', seq=2, total=7,
                              counts={'unchanged': 4}, started_at='t2')
        with db.transaction(self.conn):
            db.write_progress(self.conn, run, phase='scanning', seq=2, total=7,
                              counts={'unchanged': 4, 'indexed': 3}, started_at='t2')
        got = [(p['phase'], p['total'], p['done'], p['counts'], p['started_at'])
               for p in db.read_progress(self.conn, run)]
        self.assertEqual(got, [('discovering', None, 9, {'eligible': 7, 'excluded': 2}, 't1'),
                               ('scanning', 7, 7, {'indexed': 3, 'unchanged': 4}, 't2')])
        with self.assertRaises(sqlite3.IntegrityError), db.transaction(self.conn):
            db.write_progress(self.conn, run, phase='sorting', seq=3, total=1, counts={}, started_at='t3')

    def test_destination_findings_group_unknown_files_and_name_photos_only_when_catalogued(self):
        run, (photo, _) = self.run_record(), self.photo()
        with db.transaction(self.conn):
            self.conn.execute("UPDATE photos SET sha1_hash = 'aaa' WHERE id = ?", (photo,))
            db.record_destination_findings(self.conn, run, [
                {'path': '/d/gone.jpg', 'kind': 'missing', 'photo_id': photo, 'expected_sha1': 'aaa'},
                {'path': '/d/x/copy.jpg', 'kind': 'unknown', 'observed_sha1': 'aaa'},
                {'path': '/d/x/one.jpg', 'kind': 'unknown', 'observed_sha1': 'bbb'},
                {'path': '/d/x/two.jpg', 'kind': 'unknown', 'observed_sha1': 'bbb'},
                {'path': '/d/x/alone.jpg', 'kind': 'unknown', 'observed_sha1': 'ccc'}])
        report = db.read_destination_check(self.conn, run)
        self.assertEqual([(f['path'], f['kind']) for f in report['findings']][:1], [('/d/gone.jpg', 'missing')])
        self.assertEqual(report['unknown_groups'],
                         [{'sha1': 'aaa', 'paths': ['/d/x/copy.jpg'], 'catalogued_photo_ids': [photo]},
                          {'sha1': 'bbb', 'paths': ['/d/x/one.jpg', '/d/x/two.jpg'], 'catalogued_photo_ids': []}])
        for bad in ({'path': '/d/a', 'kind': 'unknown', 'photo_id': photo},
                    {'path': '/d/b', 'kind': 'changed'}):
            with self.assertRaises(sqlite3.IntegrityError), db.transaction(self.conn):
                db.record_destination_findings(self.conn, run, [bad])

    def test_available_cpus_honours_a_container_quota_and_cpu_set(self):
        host = os.cpu_count() or 4
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            self.assertEqual(db.available_cpus(root)["quota"], None, "no cgroup files means no quota")
            (root / "cpu.max").write_text("max 100000\n")
            unlimited = db.available_cpus(root)
            self.assertEqual((unlimited["quota"], unlimited["available"] <= host), (None, True))
            (root / "cpu.max").write_text("200000 100000\n")
            two = db.available_cpus(root)
            if host > 2 and two["affinity"] > 2:
                self.assertEqual((two["available"], two["limited_by"]), (2, "cpu_quota"))
            (root / "cpu.max").write_text("50000 100000\n")
            self.assertEqual(db.available_cpus(root)["available"], 1, "half a CPU still runs one worker")
            (root / "cpu.max").unlink()
            (root / "cpu").mkdir()
            (root / "cpu" / "cpu.cfs_quota_us").write_text("150000\n")
            (root / "cpu" / "cpu.cfs_period_us").write_text("100000\n")
            v1 = db.available_cpus(root)
            self.assertEqual(v1["quota"], 1.5, "the cgroup v1 quota was not read")
            if host > 1 and v1["affinity"] > 1:
                self.assertEqual(v1["available"], 1, "a fractional quota must round down")
            (root / "cpu" / "cpu.cfs_quota_us").write_text("-1\n")
            self.assertIsNone(db.available_cpus(root)["quota"], "-1 means unlimited")

    def test_extension_support_names_what_the_engine_can_read(self):
        for ext in ('.jpg', 'JPG', 'png', '.CR3', '.dng', '.heic'):
            got = db.extension_support(ext)
            self.assertTrue(got['supported'], ext)
            self.assertIsNone(got['warning'], ext)
        mov = db.extension_support('mov')
        self.assertEqual((mov['extension'], mov['supported']), ('.mov', False))
        self.assertIn('Copy and Move would carry them into the destination', mov['warning'])
        self.assertEqual(db.SUPPORTED_EXTENSIONS, db.RASTER_EXTENSIONS | db.RAW_EXTENSIONS)

if __name__ == '__main__':unittest.main()
