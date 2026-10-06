"""Read-only recovery guards with disposable destination files."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import fileinfo, maintenance, ns_db, ns_similarity_recovery, runtime


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.dest = self.root/'dest'; self.dest.mkdir()
        self.path = self.dest/'test.jpg'; self.path.write_bytes(b'test original')
        self.digest = hashlib.sha1(self.path.read_bytes()).hexdigest()
        self.db = self.root/'catalog.db'; ns_db.initialize(self.db)
        self.conn = ns_db.connect(self.db)
        self.run = ns_db.create_run(self.conn,mode='SIMILARITY',source=None,destination=None)[0]
        with ns_db.transaction(self.conn):
            self.photo = self.conn.execute("INSERT INTO photos(source_path,dest_path,status,sha1_hash) VALUES('/missing-source',?,'Copied',?)",(str(self.path),self.digest)).lastrowid
            ns_db.content_for_digest(self.conn,digest=self.digest,phash_state='error')
            file_id = self.conn.execute("INSERT INTO files(created_run_id,created_at) VALUES(?,'test')",(self.run,)).lastrowid
            self.conn.execute("INSERT INTO file_states(file_id,current_path,location_role,presence_state,sha1_hash) VALUES(?,?,'destination','present',?)",(file_id,str(self.path),self.digest))
        runtime.cancel_requested.clear()
        runtime.run_progress.bind(str(self.db),self.run)

    def tearDown(self):
        runtime.cancel_requested.clear()
        self.conn.close()
        self.temp.cleanup()

    def state(self):
        return self.conn.execute('SELECT phash,phash_state FROM contents').fetchone()

    def repair(self):
        return maintenance.repair_similarity(self.db,self.dest,'missing',self.photo)

    def test_cancel_during_decode_publishes_no_partial_hash(self):
        def decode(_):
            runtime.cancel_requested.set()
            return '0000000000000000'
        with patch.object(fileinfo,'compute_phash',side_effect=decode):
            self.assertEqual(self.repair(),'Cancelled')
        self.assertEqual(self.state(),(None,'error'))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM similarity_hashes').fetchone(),(0,))
        runtime.cancel_requested.clear()
        with patch.object(fileinfo,'compute_phash',return_value='0000000000000000'):
            self.assertEqual(self.repair(),'Completed')
        self.assertEqual(self.state(),('0000000000000000','ok'))

    def test_bytes_changed_during_decode_never_receive_old_content_hash(self):
        def decode(_):
            self.path.write_bytes(b'new external bytes')
            return '0000000000000000'
        with patch.object(fileinfo,'compute_phash',side_effect=decode):
            self.repair()
        self.assertEqual(self.state(),(None,'repair_changed'))
        self.assertEqual(self.path.read_bytes(),b'new external bytes')

    def test_unreadable_and_decode_failures_have_distinct_reasons(self):
        with patch.object(fileinfo,'compute_sha1',side_effect=PermissionError):
            self.repair()
        self.assertEqual(self.state(),(None,'repair_unreadable'))
        with patch.object(fileinfo,'compute_phash',return_value='error'):
            self.repair()
        self.assertEqual(self.state(),(None,'repair_decode'))
        reasons = [r[0] for r in self.conn.execute('SELECT error_message FROM operations ORDER BY id')]
        self.assertEqual(len(reasons),2)
        self.assertIn('[repair_unreadable]',reasons[0])
        self.assertIn('[repair_decode]',reasons[1])
        self.assertIn('external viewer',reasons[1])
        self.assertEqual(self.conn.execute('SELECT status FROM photos WHERE id=?',(self.photo,)).fetchone(),('Copied',))

    def test_destination_boundary_and_unsupported_format_do_not_read_file(self):
        with patch.object(fileinfo,'compute_sha1') as read:
            maintenance.repair_similarity(self.db,self.root/'another-dest','missing',self.photo)
            read.assert_not_called()
        self.assertEqual(self.state(),(None,'repair_outside'))
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE contents SET phash_state='not_supported'")
        with patch.object(fileinfo,'compute_sha1') as read:
            self.repair()
            read.assert_not_called()
        item = ns_similarity_recovery.describe(ns_similarity_recovery.rows(self.conn)[0])
        self.assertEqual((item['reason'],item['retryable']),('unsupported',False))

    def test_bulk_generation_skips_known_failures_but_explicit_recheck_works(self):
        with patch.object(fileinfo, 'compute_phash', return_value='0000000000000000') as decode:
            maintenance.repair_similarity(self.db, self.dest, 'missing')
            decode.assert_not_called()
            self.repair()
            decode.assert_called_once()
        self.assertEqual(self.state(), ('0000000000000000', 'ok'))

    def test_missing_hash_report_and_generation_agree(self):
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE contents SET phash_state=NULL")
        report = ns_similarity_recovery.report(self.conn)
        self.conn.rollback()
        self.assertEqual(report['generatable'], 1)
        self.assertEqual(report['items'][0]['action'], 'generate')
        with patch.object(fileinfo, 'compute_phash', return_value='0000000000000000') as decode:
            maintenance.repair_similarity(self.db, self.dest, 'missing')
            decode.assert_called_once()
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE contents SET phash=NULL,phash_state='repair_decode'")
        report = ns_similarity_recovery.report(self.conn)
        self.conn.rollback()
        self.assertEqual(report['generatable'], 0)
        self.assertEqual(report['items'][0]['action'], 'recheck')

    def test_source_only_photo_is_excluded(self):
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE photos SET status='Pending'")
        with patch.object(fileinfo,'compute_sha1') as read:
            self.repair()
            read.assert_not_called()
        self.assertEqual(ns_similarity_recovery.rows(self.conn),[])


if __name__ == '__main__':
    unittest.main()
