"""Generated multiple-sidecar first imports, exact retention and cleanup gates."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock

from PIL import Image
import metadata_import_test
import metadata_index_test
import metadata_primary_test
from engine import durable, metadata_decisions, metadata_import, metadata_incoming, metadata_transfer, ns_db, xmp_store


class MultiImports(unittest.TestCase):
    setUp=metadata_index_test.IndexTests.setUp
    run_engine=metadata_index_test.IndexTests.run_engine
    conn=metadata_index_test.IndexTests.conn
    photo_row=metadata_import_test.Imports.photo_row
    job=metadata_import_test.Imports.job

    def alternatives(self, same=False):
        self.alt=self.root/'source/photo.xmp'
        self.alt.write_bytes(self.sidecar.read_bytes() if same else metadata_index_test.packet('2012-06-07T08:09:10'))
        self.original=self.photo.read_bytes();self.packet=self.sidecar.read_bytes();self.alternative=self.alt.read_bytes()

    def index(self):
        self.run_engine();self.c=self.conn();self.db=next((self.root/'base/db').glob('*.db'))
        self.pid=self.photo_row()[0]
        self.capture=self.c.execute("SELECT MAX(capture_id) FROM metadata_captures WHERE source_relative_path='photo.jpg'").fetchone()[0]

    def prepare(self, move=True):
        run=ns_db.create_run(self.c,mode='MOVE' if move else 'COPY',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
        plan=metadata_import.plan(self.c,self.pid,run)
        return metadata_transfer.prepare(self.c,run_id=run,photo_id=self.pid,capture_id=self.capture,
            destination=plan['destination'],move=move,activate=True)

    def receipt(self):
        row=self.conn().execute("SELECT detail_json FROM operation_events WHERE step='pair_complete' ORDER BY event_id DESC LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        return json.loads(row[0])

    def assert_preserved(self):
        receipt=self.receipt()
        originals={v['path']:xmp_store.original_bytes(self.conn(),v['version_id']) for v in receipt['versions']}
        self.assertEqual(originals,{'photo.jpg.xmp':self.packet,'photo.xmp':self.alternative})
        self.assertEqual(Path(self.photo_row()[1]).read_bytes(),self.original)
        self.assertEqual(Path(self.photo_row()[1]+'.xmp').read_bytes(),self.packet)
        self.assertEqual(receipt['activation']['primary_id'],'sidecar:photo.jpg.xmp')
        self.assertEqual(len(list((self.root/'dest').rglob('*.xmp'))),1)

    def test_copy_uses_full_name_and_retains_every_original_and_owner(self):
        self.alternatives();self.run_engine('--copy');self.assertEqual(self.photo_row()[2],'Copied')
        self.assertIn('/2005/03/04/',self.photo_row()[1]);self.assert_preserved()
        self.assertEqual(self.alt.read_bytes(),self.alternative);self.assertEqual(self.photo.read_bytes(),self.original)
        c=self.conn();self.assertEqual(c.execute("SELECT COUNT(*) FROM metadata_decisions WHERE kind='association'").fetchone()[0],2)
        self.assertIn('alternative XMP',c.execute("SELECT error_message FROM operations WHERE status='Copied'").fetchone()[0])

    def test_move_checks_every_blob_before_any_source_removal(self):
        self.alternatives();self.index();op=self.prepare();actual=durable._remove_verified_source
        def remove(*args,**kwargs):
            self.assertTrue(metadata_transfer._had_verified_pair(self.c,op))
            for version in metadata_transfer._manifest(self.c,op)[2]['versions']:
                self.assertEqual(hashlib.sha256(xmp_store.original_bytes(self.c,version['version_id'])).hexdigest(),version['sha256'])
            return actual(*args,**kwargs)
        with mock.patch.object(durable,'_remove_verified_source',side_effect=remove):
            self.assertTrue(metadata_transfer.execute(self.c,op)['completed'])
        self.assertFalse(self.photo.exists());self.assertFalse(self.sidecar.exists());self.assertFalse(self.alt.exists());self.assert_preserved()

    def test_identical_sidecars_share_blob_but_keep_both_arrivals(self):
        self.alternatives(True);self.run_engine('--move');self.assertEqual(self.photo_row()[2],'Completed');self.assert_preserved()
        c=self.conn();self.assertEqual(c.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0],1)
        self.assertEqual({r[0] for r in c.execute('SELECT source_relative_path FROM xmp_arrivals')},{'photo.jpg.xmp','photo.xmp'})

    def test_equally_specific_differing_versions_hold_until_confirmed(self):
        other=self.root/'source/photo.jpg.XMP';other.write_bytes(metadata_index_test.packet('2012-06-07'))
        self.run_engine('--move');self.assertEqual(self.photo_row()[2],'Pending');self.assertTrue(other.exists());self.assertTrue(self.photo.exists())
        self.index();choice=dict(capture_id=self.capture,primary_id='sidecar:photo.jpg.XMP')
        preview=metadata_decisions.preview(self.db,'primary',choice)
        metadata_decisions.confirm(self.db,kind='primary',selection=choice,token=preview['token'],request_id='choose-alternative')
        self.run_engine('--move');self.assertEqual(self.photo_row()[2],'Completed');self.assertIn('/2012/06/07/',self.photo_row()[1])
        self.assertFalse(other.exists());self.assertEqual(len(self.receipt()['versions']),2)

    def test_explicit_short_name_primary_overrides_default_full_name(self):
        self.alternatives();self.index();choice=dict(capture_id=self.capture,primary_id='sidecar:photo.xmp')
        preview=metadata_decisions.preview(self.db,'primary',choice)
        metadata_decisions.confirm(self.db,kind='primary',selection=choice,token=preview['token'],request_id='choose-short')
        self.run_engine('--copy');self.assertEqual(self.photo_row()[2],'Copied');self.assertIn('/2012/06/07/',self.photo_row()[1])
        self.assertEqual(Path(self.photo_row()[1]+'.xmp').read_bytes(),self.alternative)
        self.assertEqual(len(self.receipt()['versions']),2)

    def test_invalid_alternative_holds_full_name_pair(self):
        self.alternatives();self.alt.write_bytes(metadata_index_test.packet()[:-8])
        self.run_engine('--move');self.assertEqual(self.photo_row()[2],'Pending')
        self.assertTrue(self.photo.exists());self.assertTrue(self.alt.exists());self.assertFalse(list((self.root/'dest').rglob('*.jpg')))

    def shared(self):
        self.alternatives();self.other=self.root/'source/photo.png';Image.new('RGB',(40,30),(50,90,15)).save(self.other)
        self.index();ns_db.save_settings(self.c,{'xmp_association':'all'},expected_revisions={'xmp_association':0})
        self.index()

    def test_unknown_shared_ownership_holds_even_with_full_name(self):
        self.alternatives();Image.new('RGB',(40,30),(50,90,15)).save(self.root/'source/photo.png')
        self.run_engine('--move');self.assertEqual(self.photo_row()[2],'Pending');self.assertTrue(self.photo.exists())
        self.assertTrue(self.alt.exists())

    def test_partial_move_keeps_shared_alternative_until_last_owner(self):
        self.shared();self.run_engine('--move','--file-ids',str(self.pid))
        self.assertEqual(self.photo_row()[2],'Completed');self.assertTrue(self.alt.exists());self.assertTrue(self.other.exists())
        self.run_engine('--move');self.assertFalse(self.alt.exists());self.assertFalse(self.other.exists())
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM photos WHERE status='Completed'").fetchone()[0],2)
        self.assertEqual(len(list((self.root/'dest').rglob('*.xmp'))),2)

    def test_missing_shared_owner_without_receipt_keeps_alternative(self):
        self.shared();op=self.prepare();self.other.unlink()
        result=metadata_transfer.execute(self.c,op)
        self.assertTrue(result['completed']);self.assertTrue(self.alt.exists());self.assertIn('no verified',result['sidecar_note'])

    def test_changed_alternative_after_prepare_prevents_all_source_cleanup(self):
        self.alternatives();self.index();op=self.prepare();self.alt.write_bytes(metadata_index_test.packet('2020-01-02'))
        result=metadata_transfer.execute(self.c,op)
        self.assertFalse(result['completed']);self.assertTrue(self.photo.exists());self.assertTrue(self.sidecar.exists());self.assertTrue(self.alt.exists())

    def test_missing_alternative_without_proof_is_not_success(self):
        self.alternatives();self.index();op=self.prepare();self.alt.unlink()
        self.assertFalse(metadata_transfer.execute(self.c,op)['completed']);self.assertTrue(self.photo.exists())

    def test_corrupt_archived_alternative_prevents_source_deletion(self):
        self.alternatives();self.index();op=self.prepare()
        version=next(v['version_id'] for v in metadata_transfer._manifest(self.c,op)[2]['versions'] if v['path']=='photo.xmp')
        with ns_db.transaction(self.c):
            self.c.execute('DROP TRIGGER immutable_xmp_versions_UPDATE')
            self.c.execute("UPDATE xmp_versions SET sha256=? WHERE version_id=?",('0'*64,version))
        self.assertFalse(metadata_transfer.execute(self.c,op)['completed']);self.assertTrue(self.photo.exists());self.assertTrue(self.alt.exists())

    def test_failed_alternative_cleanup_recovers_without_implicit_deletion(self):
        self.alternatives();self.index();op=self.prepare()
        with mock.patch.object(metadata_transfer,'_cleanup_alternatives',side_effect=SystemExit('fixture interruption')):
            with self.assertRaises(SystemExit):metadata_transfer.execute(self.c,op)
        self.assertFalse(self.photo.exists());self.assertTrue(self.alt.exists())
        result=metadata_transfer.recover(self.c,op)
        self.assertFalse(result['completed']);self.assertTrue(self.alt.exists())
        run=ns_db.create_run(self.c,mode='MOVE',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
        retry=metadata_transfer.retry(self.c,op,run_id=run)
        self.assertTrue(metadata_transfer.execute(self.c,retry)['completed']);self.assertFalse(self.alt.exists());self.assert_preserved()

    def test_normal_move_retries_interrupted_alternative_cleanup(self):
        self.alternatives();self.index();op=self.prepare()
        with mock.patch.object(metadata_transfer,'_cleanup_alternatives',side_effect=SystemExit('fixture interruption')):
            with self.assertRaises(SystemExit):metadata_transfer.execute(self.c,op)
        self.run_engine('--move','--confirm-source-empty')
        self.assertEqual(self.photo_row()[2],'Completed');self.assertFalse(self.alt.exists());self.assert_preserved()
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM attention_issues WHERE resolved_at IS NULL').fetchone()[0],0)

    def test_startup_recovers_after_all_unlinks_before_final_catalog_receipt(self):
        self.alternatives();self.index();op=self.prepare()
        with mock.patch.object(metadata_transfer,'_settle',side_effect=SystemExit('fixture final receipt interruption')):
            with self.assertRaises(SystemExit):metadata_transfer.execute(self.c,op)
        self.assertFalse(self.photo.exists());self.assertFalse(self.alt.exists());self.assertFalse(self.sidecar.exists())
        self.run_engine('--confirm-source-empty')
        self.assertEqual(self.photo_row()[2],'Completed');self.assert_preserved()

    def test_retry_repeats_alternative_unlink_directory_barrier(self):
        self.alternatives();self.index();op=self.prepare();actual=durable._fsync_directory
        def fail(path):
            if path==self.alt.parent and not self.alt.exists():raise OSError('fixture alternative directory sync failure')
            return actual(path)
        with mock.patch.object(durable,'_fsync_directory',side_effect=fail):
            self.assertFalse(metadata_transfer.execute(self.c,op)['completed'])
        self.assertFalse(self.alt.exists())
        run=ns_db.create_run(self.c,mode='MOVE',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
        retry=metadata_transfer.retry(self.c,op,run_id=run)
        with mock.patch.object(durable,'_fsync_directory',wraps=actual) as sync:
            self.assertTrue(metadata_transfer.execute(self.c,retry)['completed'])
            self.assertIn(mock.call(self.alt.parent),sync.call_args_list)
        self.assert_preserved()

    def test_copy_then_move_reuses_primary_and_preserves_alternatives(self):
        self.alternatives();self.run_engine('--copy');path=self.photo_row()[1];inode=Path(path).stat().st_ino
        self.run_engine('--move');self.assertEqual(self.photo_row()[2],'Completed');self.assertEqual(self.photo_row()[1],path)
        self.assertEqual(Path(path).stat().st_ino,inode);self.assertFalse(self.alt.exists());self.assert_preserved()

    def test_later_changed_alternative_is_held_for_incoming_review(self):
        self.alternatives();self.run_engine('--copy');before=self.photo_row()
        self.alt.write_bytes(metadata_index_test.packet('2021-01-02'))
        self.run_engine('--move');self.assertEqual(self.photo_row()[1:],before[1:])
        self.assertTrue(self.photo.exists());self.assertTrue(self.alt.exists())

    def test_recorded_full_name_priority_survives_embedded_primary_switch(self):
        self.alternatives();self.index();self.run_engine('--copy')
        helper=metadata_primary_test.Primary()
        for key in ('root','db','c','pid','capture'):setattr(helper,key,getattr(self,key))
        helper.apply('exif');self.run_engine('--move')
        self.assertEqual(self.photo_row()[2],'Completed');self.assertIn('/1999/01/02/',self.photo_row()[1])
        self.assertFalse(self.alt.exists());self.assertFalse(self.photo.exists())
        self.assertEqual(Path(self.photo_row()[1]+'.xmp').read_bytes(),self.packet)

    def test_replacement_at_moved_owner_path_does_not_inherit_ownership(self):
        self.shared();self.run_engine('--move','--file-ids',str(self.pid))
        Image.new('RGB',(45,31),(180,10,20)).save(self.photo)
        self.run_engine('--move')
        self.assertTrue(self.photo.exists());self.assertTrue(self.other.exists());self.assertTrue(self.alt.exists())
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM photos WHERE status='Completed'").fetchone()[0],1)

    def test_incoming_known_alternative_is_not_reported_as_novel(self):
        self.alternatives();self.index();self.run_engine('--copy');retained=self.photo_row()[0]
        helper=metadata_primary_test.Primary()
        for key in ('root','db','c','pid','capture'):setattr(helper,key,getattr(self,key))
        helper.apply('exif')
        other=self.root/'source/arrival.jpg';other.write_bytes(self.original);Path(str(other)+'.xmp').write_bytes(self.alternative)
        self.run_engine();c=self.conn();capture=c.execute("SELECT MAX(capture_id) FROM metadata_captures WHERE source_relative_path='arrival.jpg'").fetchone()[0]
        preview=metadata_incoming.preview(next((self.root/'base/db').glob('*.db')),capture_id=capture,photo_id=retained)
        self.assertEqual(preview['novel_version_ids'],[]);self.assertFalse(preview['confirmation_required'])
        self.assertFalse(preview['after']['needs_review'])


if __name__=='__main__':unittest.main()
