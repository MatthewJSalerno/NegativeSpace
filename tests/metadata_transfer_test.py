"""Generated pair transfer, crash/retry and source deletion gate checks (Docker)."""
import json
from pathlib import Path
import shutil
import unittest
from unittest import mock

from PIL import Image
import metadata_index_test
from engine import durable, metadata_transfer, ns_db, reconcile, xmp_store
from engine.ns_db import PhotoStatus


class Pairs(unittest.TestCase):
    setUp = metadata_index_test.IndexTests.setUp
    run_engine = metadata_index_test.IndexTests.run_engine
    conn = metadata_index_test.IndexTests.conn

    def index(self):
        self.run_engine()
        self.c = self.conn()
        self.pid,self.capture = self.c.execute('SELECT p.id,MAX(m.capture_id) FROM photos p JOIN photo_files pf '
            'ON pf.photo_id=p.id JOIN metadata_captures m USING(file_id) WHERE p.source_path=?',(str(self.photo),)).fetchone()
        self.dest = self.root/'dest/library/2005/03/04/photo.jpg'

    def run_id(self,move=False):
        return ns_db.create_run(self.c,mode='MOVE' if move else 'COPY',source=str(self.root/'source'),
                               destination=str(self.root/'dest'))[0]

    def prepare(self,move=False):
        return metadata_transfer.prepare(self.c,run_id=self.run_id(move),photo_id=self.pid,
            capture_id=self.capture,destination=str(self.dest),move=move)

    def result(self,op):
        result=metadata_transfer.execute(self.c,op)
        self.assertTrue(result['completed'],result)
        return result

    def test_copy_publishes_full_filename_sidecar_and_preserves_originals(self):
        self.index(); before=[p.read_bytes() for p in (self.photo,self.sidecar)]
        op=self.prepare();self.result(op)
        self.assertEqual([p.read_bytes() for p in (self.photo,self.sidecar)],before)
        self.assertEqual(self.dest.read_bytes(),before[0])
        self.assertEqual(Path(str(self.dest)+'.xmp').read_bytes(),before[1])
        receipt=json.loads(self.c.execute("SELECT detail_json FROM operation_events WHERE operation_id=? AND step='pair_complete'",(op,)).fetchone()[0])
        self.assertEqual(xmp_store.original_bytes(self.c,receipt['version_id']),before[1])
        self.assertEqual(self.c.execute('SELECT status FROM photos WHERE id=?',(self.pid,)).fetchone()[0],PhotoStatus.COPIED)

    def test_move_deletes_only_after_both_files_and_receipt_are_verified(self):
        self.index();op=self.prepare(True);actual=durable._remove_verified_source;seen=[]
        def remove(source,dest,identity,description):
            self.assertTrue(self.dest.is_file());self.assertTrue(Path(str(self.dest)+'.xmp').is_file())
            self.assertTrue(metadata_transfer._had_verified_pair(self.c,op))
            seen.append(source)
            return actual(source,dest,identity,description)
        with mock.patch.object(durable,'_remove_verified_source',side_effect=remove): self.result(op)
        self.assertEqual(seen,[self.photo,self.sidecar])
        self.assertFalse(self.photo.exists());self.assertFalse(self.sidecar.exists())

    def test_sidecar_failure_keeps_both_sources_and_retry_reuses_photo(self):
        self.index();op=self.prepare(True);actual=durable.copy_verify_delete
        def copy(source,dest,**kw):
            return (False,'generated disk-full failure') if source.endswith('.xmp') else actual(source,dest,**kw)
        with mock.patch.object(durable,'copy_verify_delete',side_effect=copy):
            failed=metadata_transfer.execute(self.c,op)
        self.assertFalse(failed['completed']);self.assertIn('disk-full',failed['error'])
        self.assertTrue(self.photo.exists());self.assertTrue(self.sidecar.exists());self.assertTrue(self.dest.exists())
        self.assertEqual(self.c.execute('SELECT status FROM photos WHERE id=?',(self.pid,)).fetchone()[0],PhotoStatus.FAILED)
        inode=self.dest.stat().st_ino
        retry=metadata_transfer.retry(self.c,op,run_id=self.run_id(True));self.result(retry)
        self.assertEqual(self.dest.stat().st_ino,inode)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM attention_issues WHERE resolved_at IS NULL AND category='metadata_pair_incomplete'").fetchone()[0],0)
        self.assertFalse(self.photo.exists());self.assertFalse(self.sidecar.exists())
        self.assertEqual(self.c.execute('SELECT status FROM operations WHERE id=?',(op,)).fetchone()[0],PhotoStatus.FAILED)

    def test_orphan_destination_xmp_requires_attention_without_writes(self):
        self.index();self.dest.parent.mkdir(parents=True)
        target=Path(str(self.dest)+'.xmp');target.write_bytes(self.sidecar.read_bytes())
        with self.assertRaisesRegex(metadata_transfer.PairRefused,'photo is missing'): self.prepare(True)
        self.assertFalse(self.dest.exists());self.assertTrue(self.photo.exists());self.assertTrue(self.sidecar.exists())

    def test_differing_destination_xmp_never_overwritten_or_source_removed(self):
        self.index();self.dest.parent.mkdir(parents=True)
        shutil.copyfile(self.photo,self.dest);target=Path(str(self.dest)+'.xmp')
        alternative=metadata_index_test.packet('2012');target.write_bytes(alternative)
        with self.assertRaisesRegex(metadata_transfer.PairRefused,'differs'): self.prepare(True)
        self.assertEqual(target.read_bytes(),alternative);self.assertTrue(self.photo.exists());self.assertTrue(self.sidecar.exists())

    def test_existing_identical_pair_is_reused(self):
        self.index();self.dest.parent.mkdir(parents=True)
        shutil.copyfile(self.photo,self.dest);shutil.copyfile(self.sidecar,str(self.dest)+'.xmp')
        with mock.patch.object(durable,'copy_verify_delete') as copy:
            op=self.prepare(True);self.result(op);copy.assert_not_called()

    def test_completed_replay_does_not_delete_new_source_files(self):
        self.index();op=self.prepare(True);self.result(op)
        self.photo.write_bytes(b'new unrelated file');self.sidecar.write_bytes(b'new unrelated sidecar')
        self.assertTrue(metadata_transfer.execute(self.c,op)['replayed'])
        self.assertEqual(self.photo.read_bytes(),b'new unrelated file');self.assertEqual(self.sidecar.read_bytes(),b'new unrelated sidecar')

    def test_failure_making_xmp_durable_prevents_all_deletions(self):
        self.index();op=self.prepare(True);actual=durable._fsync_file
        def sync(path):
            if str(path).endswith('.xmp'): raise OSError('generated fsync failure')
            return actual(path)
        with mock.patch.object(durable,'_fsync_file',side_effect=sync), mock.patch.object(durable,'_remove_verified_source') as remove:
            result=metadata_transfer.execute(self.c,op);remove.assert_not_called()
        self.assertFalse(result['completed']);self.assertTrue(self.photo.exists());self.assertTrue(self.sidecar.exists())

    def test_crash_after_photo_publish_recovery_never_claims_pair_complete(self):
        self.index();op=self.prepare(True);actual=durable.copy_verify_delete
        def crash(source,dest,**kw):
            if source.endswith('.xmp'): raise SystemExit('generated process kill')
            return actual(source,dest,**kw)
        with mock.patch.object(durable,'copy_verify_delete',side_effect=crash),self.assertRaises(SystemExit):
            metadata_transfer.execute(self.c,op)
        self.assertEqual(len(ns_db.unsettled_operations(self.c,self.pid)),1)
        result=metadata_transfer.recover(self.c,op)
        self.assertFalse(result['completed']);self.assertTrue(self.photo.exists());self.assertTrue(self.sidecar.exists())
        self.assertIn('destination XMP verified: False',result['error'])
        retry=metadata_transfer.retry(self.c,op,run_id=self.run_id(True));self.result(retry)

    def test_crash_after_photo_removal_can_finish_xmp_cleanup_explicitly(self):
        self.index();op=self.prepare(True);actual=durable._remove_verified_source
        def crash(source,*args):
            if source == self.sidecar: raise SystemExit('generated process kill')
            return actual(source,*args)
        with mock.patch.object(durable,'_remove_verified_source',side_effect=crash),self.assertRaises(SystemExit):
            metadata_transfer.execute(self.c,op)
        self.assertFalse(self.photo.exists());self.assertTrue(self.sidecar.exists())
        result=metadata_transfer.recover(self.c,op)
        self.assertFalse(result['completed']);self.assertIn('cleanup is unfinished',result['error'])
        self.assertEqual(self.c.execute('SELECT presence_state FROM file_states WHERE file_id=(SELECT file_id FROM photo_files WHERE photo_id=?)',(self.pid,)).fetchone()[0],'missing')
        retry=metadata_transfer.retry(self.c,op,run_id=self.run_id(True));self.result(retry)
        self.assertFalse(self.sidecar.exists())

    def test_crash_after_both_deletions_recovers_from_verified_pair(self):
        self.index();op=self.prepare(True)
        with mock.patch.object(metadata_transfer,'_settle',side_effect=SystemExit),self.assertRaises(SystemExit):
            metadata_transfer.execute(self.c,op)
        self.assertFalse(self.photo.exists());self.assertFalse(self.sidecar.exists())
        self.assertTrue(metadata_transfer.recover(self.c,op)['completed'])

    def test_pair_receipt_commit_failure_prevents_source_deletion(self):
        self.index();op=self.prepare(True)
        with mock.patch.object(ns_db,'record_evidence',side_effect=RuntimeError('generated catalog failure')):
            result=metadata_transfer.execute(self.c,op)
        self.assertFalse(result['completed']);self.assertTrue(self.photo.exists());self.assertTrue(self.sidecar.exists())

    def test_unrecorded_source_disappearance_never_authorizes_success(self):
        self.index();op=self.prepare(True);self.photo.unlink()
        result=metadata_transfer.execute(self.c,op)
        self.assertFalse(result['completed']);self.assertTrue(self.sidecar.exists());self.assertFalse(self.dest.exists())

    def test_symlinks_traversal_and_same_file_aliases_refused(self):
        self.index();self.dest.parent.mkdir(parents=True)
        for target in (self.root/'elsewhere.jpg',self.root/'dest/library/../escape.jpg'):
            with self.assertRaises(metadata_transfer.PairRefused):
                metadata_transfer.prepare(self.c,run_id=self.run_id(),photo_id=self.pid,capture_id=self.capture,destination=str(target))
        self.dest.symlink_to(self.photo)
        with self.assertRaises(OSError):self.prepare(True)
        self.dest.unlink();self.dest.hardlink_to(self.photo)
        with self.assertRaisesRegex(metadata_transfer.PairRefused,'same underlying'):self.prepare(True)
        self.assertTrue(self.photo.exists())

    def shared(self):
        self.sidecar.rename(self.root/'source/photo.xmp');self.sidecar=self.root/'source/photo.xmp'
        Image.new('RGB',(40,30),(90,20,40)).save(self.root/'source/photo.png')
        self.index()
        ns_db.save_settings(self.c,{'xmp_association':'all'},expected_revisions={'xmp_association':0})
        self.run_engine()
        self.capture=self.c.execute("SELECT MAX(capture_id) FROM metadata_captures WHERE source_relative_path='photo.jpg'").fetchone()[0]

    def test_partial_shared_move_keeps_xmp_then_last_owner_removes_it(self):
        self.shared();first=self.prepare(True)
        pid,cap=self.c.execute("SELECT p.id,MAX(m.capture_id) FROM photos p JOIN photo_files pf ON pf.photo_id=p.id "
            "JOIN metadata_captures m USING(file_id) WHERE p.source_path=?",(str(self.root/'source/photo.png'),)).fetchone()
        second_dest=self.dest.with_suffix('.png')
        second=metadata_transfer.prepare(self.c,run_id=self.run_id(True),photo_id=pid,capture_id=cap,destination=str(second_dest),move=True)
        first_result=self.result(first)
        self.assertIn('still needs it',first_result['sidecar_note']);self.assertTrue(self.sidecar.exists())
        self.result(second);self.assertFalse(self.sidecar.exists())
        self.assertEqual(Path(str(self.dest)+'.xmp').read_bytes(),Path(str(second_dest)+'.xmp').read_bytes())

    def test_missing_other_owner_without_receipt_keeps_shared_sidecar(self):
        self.shared();op=self.prepare(True);(self.root/'source/photo.png').unlink()
        result=self.result(op)
        self.assertIn('no verified destination pair',result['sidecar_note']);self.assertTrue(self.sidecar.exists())

    def test_ambiguous_or_damaged_sidecar_is_refused_without_writes(self):
        self.sidecar.write_bytes(metadata_index_test.packet()[:-10]);self.index()
        with self.assertRaisesRegex(metadata_transfer.PairRefused,'Resolve source metadata'):self.prepare(True)
        self.assertEqual(list((self.root/'dest').iterdir()),[])

    def test_new_retry_cannot_replay_an_older_failure(self):
        self.index();op=self.prepare()
        with mock.patch.object(durable,'copy_verify_delete',return_value=(False,'generated failure')):
            self.assertFalse(metadata_transfer.execute(self.c,op)['completed'])
        new=metadata_transfer.retry(self.c,op,run_id=self.run_id());self.result(new)
        with self.assertRaises(metadata_transfer.PairRefused):metadata_transfer.retry(self.c,op,run_id=self.run_id())



    def test_different_photo_name_collision_suffixes_both_members(self):
        self.index();self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(b'other photo bytes')
        op=self.prepare();self.result(op)
        self.assertEqual(self.dest.read_bytes(),b'other photo bytes')
        self.assertEqual(self.dest.with_name('photo_1.jpg').read_bytes(),self.photo.read_bytes())
        self.assertEqual(self.dest.with_name('photo_1.jpg.xmp').read_bytes(),self.sidecar.read_bytes())

    def test_startup_recovery_does_not_use_photo_only_success_rule(self):
        self.index();op=self.prepare(True);actual=durable.copy_verify_delete
        def crash(source,dest,**kw):
            if source.endswith('.xmp'):raise SystemExit()
            return actual(source,dest,**kw)
        with mock.patch.object(durable,'copy_verify_delete',side_effect=crash),self.assertRaises(SystemExit):
            metadata_transfer.execute(self.c,op)
        recovery_run=self.run_id(True)
        reconcile.reconcile_interrupted_state(next((self.root/'base/db').glob('*.db')),recovery_run)
        recovered=self.c.execute('SELECT sha1_hash,status FROM operations WHERE run_id=? AND reconciles_operation_id=?',(recovery_run,op)).fetchone()
        self.assertIsNotNone(recovered);self.assertEqual(recovered[1],PhotoStatus.FAILED)
        self.assertEqual(recovered[0],self.c.execute('SELECT sha1_hash FROM photos WHERE id=?',(self.pid,)).fetchone()[0])
        self.assertEqual(self.c.execute('SELECT status FROM photos WHERE id=?',(self.pid,)).fetchone()[0],PhotoStatus.FAILED)
        self.assertTrue(self.photo.exists());self.assertTrue(self.sidecar.exists())
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM operation_events WHERE operation_id=? AND step='pair_complete'",(op,)).fetchone()[0],0)

    def test_catalog_change_refuses_retry_without_changing_new_state(self):
        self.index();op=self.prepare()
        with mock.patch.object(durable,'copy_verify_delete',return_value=(False,'generated failure')):
            metadata_transfer.execute(self.c,op)
        with ns_db.transaction(self.c):self.c.execute('UPDATE photos SET sha1_hash=? WHERE id=?',('changed',self.pid))
        before=self.c.execute('SELECT status,dest_path,sha1_hash FROM photos WHERE id=?',(self.pid,)).fetchone()
        with self.assertRaisesRegex(metadata_transfer.PairRefused,'catalog photo has changed'):
            metadata_transfer.retry(self.c,op,run_id=self.run_id())
        self.assertEqual(self.c.execute('SELECT status,dest_path,sha1_hash FROM photos WHERE id=?',(self.pid,)).fetchone(),before)

    def test_partial_sidecar_publish_recovery_and_retry_keep_exact_bytes(self):
        self.index();op=self.prepare(True);actual=durable._finalize_partial
        def crash(partial,dest):
            actual(partial,dest)
            if str(dest).endswith('.xmp'):raise SystemExit()
        with mock.patch.object(durable,'_finalize_partial',side_effect=crash),self.assertRaises(SystemExit):
            metadata_transfer.execute(self.c,op)
        self.assertTrue(self.photo.exists());self.assertTrue(self.sidecar.exists())
        self.assertFalse(metadata_transfer.recover(self.c,op)['completed'])
        new=metadata_transfer.retry(self.c,op,run_id=self.run_id(True));self.result(new)
        self.assertFalse(self.photo.exists());self.assertFalse(self.sidecar.exists())

    def test_normal_synchronous_connection_cannot_start_transfer(self):
        self.index();self.c.execute('PRAGMA synchronous=NORMAL')
        with self.assertRaisesRegex(RuntimeError,'FULL connection'):self.prepare()
        self.assertFalse(self.dest.exists())



    def test_existing_primary_is_not_silently_replaced_by_pair_import(self):
        from engine import metadata_decisions
        self.index()
        selection={'capture_id':self.capture,'primary_id':'exif'}
        db=next((self.root/'base/db').glob('*.db'))
        preview=metadata_decisions.preview(db,'primary',selection)
        metadata_decisions.confirm(db,kind='primary',selection=selection,token=preview['token'],request_id='primary')
        with self.assertRaisesRegex(metadata_transfer.PairRefused,'established primary'):
            self.prepare(True)
        self.assertTrue(self.photo.exists());self.assertTrue(self.sidecar.exists());self.assertFalse(self.dest.exists())

    def test_corrupt_retained_version_prevents_publication_and_deletion(self):
        self.index();op=self.prepare(True)
        with mock.patch.object(xmp_store,'original_bytes',side_effect=xmp_store.InvalidBlob('generated corrupt archive')):
            result=metadata_transfer.execute(self.c,op)
        self.assertFalse(result['completed']);self.assertIn('corrupt archive',result['error'])
        self.assertTrue(self.photo.exists());self.assertTrue(self.sidecar.exists());self.assertFalse(self.dest.exists())

    def test_new_destination_occupant_after_prepare_is_never_overwritten(self):
        self.index();op=self.prepare(True);self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(b'new destination occupant')
        result=metadata_transfer.execute(self.c,op)
        self.assertFalse(result['completed']);self.assertEqual(self.dest.read_bytes(),b'new destination occupant')
        self.assertTrue(self.photo.exists());self.assertTrue(self.sidecar.exists())


if __name__ == '__main__': unittest.main()
