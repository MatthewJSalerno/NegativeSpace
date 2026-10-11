"""Generated incoming-XMP choices, exact alternatives and source cleanup gates."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import metadata_index_test
from engine import durable, metadata_incoming, ns_db, runtime, transfer, xmp_store


class Incoming(unittest.TestCase):
    setUp=metadata_index_test.IndexTests.setUp
    run_engine=metadata_index_test.IndexTests.run_engine
    conn=metadata_index_test.IndexTests.conn

    def setup_arrival(self, *, current_xmp=True, identical=False, rejected=False):
        original=self.photo.read_bytes()
        if not current_xmp:self.sidecar.unlink()
        self.run_engine('--copy')
        self.target=self.conn().execute('SELECT id,dest_path FROM photos WHERE source_path=?',(str(self.photo),)).fetchone()
        if rejected:self.run_engine('--reject','--file-ids',str(self.target[0]))
        folder=self.root/'source/archive';folder.mkdir()
        self.incoming=folder/'new-name.jpg';self.incoming.write_bytes(original)
        self.note=Path(str(self.incoming)+'.xmp')
        self.note.write_bytes(metadata_index_test.packet() if identical else metadata_index_test.packet('2011-02-03T04:05:06'))
        self.run_engine()
        self.db=next((self.root/'base/db').glob('*.db'))
        self.pid,self.cap=self.conn().execute('SELECT p.id,MAX(m.capture_id) FROM photos p JOIN photo_files f ON f.photo_id=p.id '
            'JOIN metadata_captures m ON m.file_id=f.file_id WHERE p.source_path=?',(str(self.incoming),)).fetchone()

    def move(self):
        c=self.conn();run=ns_db.create_run(c,mode='MOVE',source=str(self.root/'source'),destination=str(self.root/'dest'),selection=[self.pid])[0]
        runtime.run_progress.bind(str(self.db),run);runtime.cancel_requested.clear()
        args=SimpleNamespace(move=True,copy=False,source=str(self.root/'source'),source_subdir=None,file_ids=[self.pid],run_id=run)
        return transfer._run_move_or_copy(args,self.db,self.root/'dest',run)

    def test_differing_incoming_xmp_is_retained_without_replacing_primary(self):
        self.setup_arrival();original=Path(self.target[1]+'.xmp').read_bytes();incoming=self.note.read_bytes()
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertFalse(self.incoming.exists());self.assertFalse(self.note.exists())
        self.assertEqual(Path(self.target[1]+'.xmp').read_bytes(),original)
        c=self.conn();value=json.loads(c.execute("SELECT value_json FROM metadata_decisions WHERE kind='incoming' ORDER BY decision_id DESC LIMIT 1").fetchone()[0])
        self.assertTrue(value['needs_review']);self.assertFalse(value['activation_required'])
        self.assertEqual(xmp_store.original_bytes(c,value['versions'][0]['version_id']),incoming)
        self.assertEqual(c.execute('SELECT status FROM photos WHERE id=?',(self.pid,)).fetchone()[0],'Removed_Duplicate')

    def test_identical_xmp_records_arrival_without_review_or_extra_blob(self):
        self.setup_arrival(identical=True);self.run_engine('--copy','--file-ids',str(self.pid))
        c=self.conn();self.assertEqual(c.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0],1)
        value=json.loads(c.execute("SELECT value_json FROM metadata_decisions WHERE kind='incoming' ORDER BY decision_id DESC LIMIT 1").fetchone()[0])
        self.assertFalse(value['needs_review']);self.assertTrue(self.incoming.exists());self.assertTrue(self.note.exists())

    def test_no_current_xmp_requires_choice_then_keep_current_allows_move(self):
        self.setup_arrival(current_xmp=False);self.run_engine('--move','--file-ids',str(self.pid))
        self.assertTrue(self.incoming.exists());self.assertTrue(self.note.exists())
        preview=metadata_incoming.preview(self.db,capture_id=self.cap,photo_id=self.target[0])
        self.assertTrue(preview['confirmation_required'])
        decision=metadata_incoming.confirm(self.db,selection=preview['selection'],token=preview['token'],request_id='keep-embedded')
        self.assertFalse(decision['value']['activation_required'])
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertFalse(self.incoming.exists());self.assertFalse(self.note.exists())
        self.assertFalse(Path(self.target[1]+'.xmp').exists())

    def test_rejected_photo_keeps_its_location_and_primary(self):
        self.setup_arrival(rejected=True)
        original=self.conn().execute('SELECT dest_path,status FROM photos WHERE id=?',(self.target[0],)).fetchone()
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertEqual(self.conn().execute('SELECT dest_path,status FROM photos WHERE id=?',(self.target[0],)).fetchone(),original)
        self.assertFalse(self.incoming.exists())

    def test_combined_rejected_choice_requires_activation_before_cleanup(self):
        self.setup_arrival(current_xmp=False,rejected=True)
        initial=metadata_incoming.preview(self.db,capture_id=self.cap,photo_id=self.target[0])
        version=initial['after']['versions'][0]['version_id']
        preview=metadata_incoming.preview(self.db,capture_id=self.cap,photo_id=self.target[0],primary='use_incoming',version_id=version,location='library')
        saved=metadata_incoming.confirm(self.db,selection=preview['selection'],token=preview['token'],request_id='choose-and-return')
        self.assertTrue(saved['value']['activation_required'])
        self.run_engine('--move','--file-ids',str(self.pid));self.assertTrue(self.incoming.exists())

    def test_stale_preview_and_request_conflict_are_refused(self):
        self.setup_arrival(current_xmp=False)
        preview=metadata_incoming.preview(self.db,capture_id=self.cap,photo_id=self.target[0])
        args=dict(selection=preview['selection'],token=preview['token'],request_id='one-request')
        saved=metadata_incoming.confirm(self.db,**args)
        self.assertEqual(metadata_incoming.confirm(self.db,**args),saved)
        with self.assertRaises(ns_db.RequestConflict):metadata_incoming.confirm(self.db,**{**args,'token':'0'*64})
        with self.assertRaises(ns_db.RevisionConflict):metadata_incoming.confirm(self.db,**{**args,'request_id':'different-request'})

    def test_corrupt_retained_photo_never_deletes_source_pair(self):
        self.setup_arrival();Path(self.target[1]).write_bytes(b'not the photo')
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertTrue(self.incoming.exists());self.assertTrue(self.note.exists())

    def test_corrupt_archived_xmp_prevents_cleanup(self):
        self.setup_arrival()
        with mock.patch.object(xmp_store,'original_bytes',side_effect=xmp_store.InvalidBlob('generated bad archive')):
            self.move()
        self.assertTrue(self.incoming.exists());self.assertTrue(self.note.exists())
        self.assertIn('generated bad archive',self.conn().execute('SELECT error_message FROM operations ORDER BY id DESC LIMIT 1').fetchone()[0])

    def test_failure_after_photo_unlink_retries_sidecar_cleanup(self):
        self.setup_arrival();actual=durable._fsync_directory
        def sync(path):
            if Path(path)==self.incoming.parent and not self.incoming.exists():raise OSError('generated source sync failure')
            return actual(path)
        with mock.patch.object(durable,'_fsync_directory',side_effect=sync):self.move()
        self.assertFalse(self.incoming.exists());self.assertTrue(self.note.exists())
        self.run_engine('--move','--file-ids',str(self.pid),'--confirm-source-empty')
        self.assertFalse(self.note.exists())
        self.assertEqual(self.conn().execute("SELECT COUNT(*) FROM attention_issues WHERE category='metadata_incoming_incomplete' AND resolved_at IS NULL").fetchone()[0],0)

    def test_source_sidecar_changed_before_transfer_is_kept(self):
        self.setup_arrival();self.note.write_bytes(metadata_index_test.packet('2020-01-01'))
        self.move();self.assertTrue(self.note.exists());self.assertTrue(self.incoming.exists())

    def test_copy_preserves_all_sources_and_linked_origins(self):
        self.setup_arrival();before=self.incoming.read_bytes(),self.note.read_bytes()
        self.run_engine('--copy','--file-ids',str(self.pid))
        self.assertEqual((self.incoming.read_bytes(),self.note.read_bytes()),before)
        c=self.conn();value=json.loads(c.execute("SELECT value_json FROM metadata_decisions WHERE kind='incoming'").fetchone()[0])
        self.assertEqual(value['versions'][0]['path'],'archive/new-name.jpg.xmp')
        self.assertNotEqual(value['incoming_file_id'],value['retained_file_id'])

    def test_saved_choice_does_not_authorize_a_changed_retained_target(self):
        self.setup_arrival(current_xmp=False)
        preview=metadata_incoming.preview(self.db,capture_id=self.cap,photo_id=self.target[0])
        metadata_incoming.confirm(self.db,selection=preview['selection'],token=preview['token'],request_id='before-change')
        conn=self.conn()
        conn.execute('UPDATE file_states SET revision=revision+1 WHERE file_id=?',(preview['target']['file_id'],))
        conn.commit()
        self.move()
        self.assertTrue(self.incoming.exists());self.assertTrue(self.note.exists())
        self.assertIn('changed after this choice',conn.execute('SELECT error_message FROM operations ORDER BY id DESC LIMIT 1').fetchone()[0])

    def test_copy_duplicate_counts_once_with_a_recorded_preservation_reason(self):
        self.setup_arrival()
        self.run_engine('--copy','--file-ids',str(self.pid))
        conn=self.conn();run=conn.execute('SELECT MAX(id) FROM runs').fetchone()[0]
        progress=next(p for p in ns_db.read_progress(conn,run) if p['phase']=='transferring')
        self.assertEqual(progress['total'],1)
        self.assertEqual(progress['done'],1)
        self.assertEqual(progress['counts'],{'Skipped':1})
        status,reason=conn.execute('SELECT status,error_message FROM operations WHERE run_id=? AND photo_id=?',(run,self.pid)).fetchone()
        self.assertEqual(status,'Skipped');self.assertIn('incoming XMP originals preserved',reason)
