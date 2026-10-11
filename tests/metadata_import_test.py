"""Generated normal-job XMP activation, safety gates and retry integration."""
from datetime import datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from PIL import Image
import metadata_index_test
from engine import durable, metadata_decisions, metadata_import, metadata_transfer, ns_db, runtime, transfer


class Imports(unittest.TestCase):
    setUp = metadata_index_test.IndexTests.setUp
    run_engine = metadata_index_test.IndexTests.run_engine
    conn = metadata_index_test.IndexTests.conn

    def photo_row(self):
        return self.conn().execute('SELECT id,dest_path,status,metadata_json FROM photos WHERE source_path=?',
                                  (str(self.photo),)).fetchone()

    def job(self, move=False):
        c=self.conn(); db=next((self.root/'base/db').glob('*.db'))
        run=ns_db.create_run(c,mode='MOVE' if move else 'COPY',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
        runtime.run_progress.bind(str(db),run); runtime.cancel_requested.clear()
        args=SimpleNamespace(move=move,copy=not move,source=str(self.root/'source'),source_subdir=None,file_ids=None)
        return transfer._run_move_or_copy(args,db,self.root/'dest',run)

    def test_direct_copy_uses_xmp_filing_and_keeps_source_bytes(self):
        before=self.photo.read_bytes(); side=self.sidecar.read_bytes()
        self.run_engine('--copy'); row=self.photo_row()
        self.assertEqual(row[2],'Copied')
        self.assertEqual(Path(row[1]).relative_to(self.root/'dest').as_posix(),'library/2005/03/04/photo.jpg')
        self.assertEqual(Path(row[1]).read_bytes(),before)
        self.assertEqual(Path(row[1]+'.xmp').read_bytes(),side)
        self.assertEqual(self.photo.read_bytes(),before); self.assertEqual(self.sidecar.read_bytes(),side)
        meta=json.loads(row[3]); self.assertEqual(meta['date_source'],'xmp')
        self.assertEqual(meta['date_taken'],'2005-03-04T05:06:07')
        c=self.conn(); self.assertEqual(c.execute("SELECT COUNT(*) FROM metadata_decisions WHERE kind='primary'").fetchone()[0],1)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM operation_events WHERE step='metadata_activated'").fetchone()[0],1)

    def test_copy_then_move_reuses_pair_and_preserves_primary(self):
        self.run_engine('--copy'); first=self.photo_row(); inode=Path(first[1]).stat().st_ino
        self.run_engine('--move'); second=self.photo_row()
        self.assertEqual(second[2],'Completed'); self.assertEqual(second[1],first[1])
        self.assertEqual(Path(second[1]).stat().st_ino,inode)
        self.assertTrue(Path(second[1]+'.xmp').exists()); self.assertFalse(self.photo.exists()); self.assertFalse(self.sidecar.exists())
        self.assertEqual(self.conn().execute("SELECT COUNT(*) FROM metadata_decisions WHERE kind='primary'").fetchone()[0],1)

    def test_blank_and_partial_xmp_dates_use_original_undated_year(self):
        for date in ('','2001','2001-02'):
            with self.subTest(date=date):
                self.sidecar.write_bytes(metadata_index_test.packet(date))
                self.run_engine('--copy'); row=self.photo_row()
                year=datetime.fromtimestamp(self.photo.stat().st_mtime).year
                self.assertEqual(row[2],'Copied'); self.assertIn(f'/Undated/{year}/',row[1])
                self.assertEqual(json.loads(row[3])['date_source'],'file_mtime')
                # Each subcase needs its own photo identity, not a changed existing primary.
                if date!='2001-02':
                    self.setUp()

    def test_missing_xmp_date_uses_embedded_xmp_without_writing_fallback(self):
        data=metadata_index_test.packet().replace(b'<exif:DateTimeOriginal>2005-03-04T05:06:07</exif:DateTimeOriginal>',b'')
        self.sidecar.write_bytes(data); self.run_engine('--copy'); row=self.photo_row()
        self.assertEqual(row[2],'Copied'); self.assertIn('/2004/02/03/',row[1])
        self.assertEqual(Path(row[1]+'.xmp').read_bytes(),data)

    def test_explicit_exif_primary_uses_exif_and_still_preserves_xmp(self):
        self.run_engine(); c=self.conn(); db=next((self.root/'base/db').glob('*.db'))
        cap=c.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        choice={'capture_id':cap,'primary_id':'exif'}
        preview=metadata_decisions.preview(db,'primary',choice)
        metadata_decisions.confirm(db,kind='primary',selection=choice,token=preview['token'],request_id='exif-choice')
        self.run_engine('--copy'); row=self.photo_row()
        self.assertEqual(row[2],'Copied'); self.assertIn('/1999/01/02/',row[1]); self.assertTrue(Path(row[1]+'.xmp').exists())
        self.assertEqual(json.loads(row[3])['date_source'],'exif')

    def test_sidecar_failure_does_not_activate_and_explicit_job_retries(self):
        self.run_engine(); original=self.photo_row()[3]; actual=durable.copy_verify_delete
        def copy(src,dst,**kwargs):
            return (False,'generated XMP write failure') if str(src).endswith('.xmp') else actual(src,dst,**kwargs)
        with mock.patch.object(durable,'copy_verify_delete',side_effect=copy): self.job(True)
        self.assertEqual(self.photo_row()[2],'Failed'); self.assertEqual(self.photo_row()[3],original)
        self.assertTrue(self.photo.exists()); self.assertTrue(self.sidecar.exists())
        self.assertEqual(self.conn().execute('SELECT COUNT(*) FROM metadata_decisions').fetchone()[0],0)
        self.run_engine('--move'); row=self.photo_row()
        self.assertEqual(row[2],'Completed'); self.assertIn('/2005/03/04/',row[1])
        self.assertFalse(self.photo.exists()); self.assertFalse(self.sidecar.exists())
        self.assertEqual(self.conn().execute('SELECT COUNT(*) FROM attention_issues WHERE resolved_at IS NULL').fetchone()[0],0)

    def test_unreadable_sidecar_stays_at_source_with_its_photo(self):
        self.sidecar.write_bytes(b'not XMP'); self.run_engine('--move')
        self.assertTrue(self.photo.exists()); self.assertTrue(self.sidecar.exists())
        self.assertEqual(list((self.root/'dest').iterdir()),[])
        self.assertEqual(self.photo_row()[2],'Pending')

    def test_orphan_target_sidecar_is_not_adopted(self):
        target=self.root/'dest/library/2005/03/04/photo.jpg.xmp'; target.parent.mkdir(parents=True)
        target.write_bytes(self.sidecar.read_bytes()); self.run_engine('--move')
        self.assertEqual(self.photo_row()[2],'Pending'); self.assertTrue(self.photo.exists())
        self.assertFalse(Path(str(target)[:-4]).exists())

    def test_incoming_xmp_for_already_organized_photo_is_held(self):
        self.sidecar.unlink(); self.run_engine('--copy')
        self.sidecar.write_bytes(metadata_index_test.packet()); self.run_engine('--move')
        self.assertTrue(self.photo.exists()); self.assertTrue(self.sidecar.exists())
        self.assertEqual(self.photo_row()[2],'Copied')
        self.assertFalse(Path(self.photo_row()[1]+'.xmp').exists())

    def test_changed_sidecar_after_copy_cannot_replace_primary(self):
        self.run_engine('--copy'); row=self.photo_row(); original=Path(row[1]+'.xmp').read_bytes()
        self.sidecar.write_bytes(metadata_index_test.packet('2015-01-02')); self.run_engine('--move')
        self.assertTrue(self.photo.exists()); self.assertTrue(self.sidecar.exists())
        self.assertEqual(Path(row[1]+'.xmp').read_bytes(),original); self.assertEqual(self.photo_row()[2],'Copied')

    def test_space_estimate_counts_photo_and_sidecar(self):
        self.run_engine()
        with mock.patch.object(transfer,'verify_sufficient_disk_space',return_value=(False,0,1)) as estimate:
            self.job()
        self.assertEqual(estimate.call_args.args[1],self.photo.stat().st_size+self.sidecar.stat().st_size)
        self.assertEqual(list((self.root/'dest').iterdir()),[])

    def test_shared_sidecar_moves_each_owner_once(self):
        self.sidecar.rename(self.root/'source/photo.xmp'); self.sidecar=self.root/'source/photo.xmp'
        Image.new('RGB',(44,35),(110,20,40)).save(self.root/'source/photo.png')
        self.run_engine(); c=self.conn()
        ns_db.save_settings(c,{'xmp_association':'all'},expected_revisions={'xmp_association':0})
        self.run_engine('--move')
        self.assertEqual(c.execute("SELECT COUNT(*) FROM photos WHERE status='Completed'").fetchone()[0],2)
        self.assertFalse(self.sidecar.exists()); self.assertFalse(self.photo.exists())
        self.assertEqual(len(list((self.root/'dest').rglob('*.xmp'))),2)

    def test_offset_date_keeps_recorded_calendar_day(self):
        self.sidecar.write_bytes(metadata_index_test.packet('2005-03-04T00:01:00+14:00'))
        self.run_engine('--copy'); self.assertIn('/2005/03/04/',self.photo_row()[1])

    def test_retry_repeats_source_directory_barrier_after_unlink(self):
        self.run_engine(); actual=durable._fsync_directory
        def sync(path):
            if path==self.photo.parent and not self.photo.exists():
                raise OSError('generated source directory sync failure')
            return actual(path)
        with mock.patch.object(durable,'_fsync_directory',side_effect=sync):
            self.job(True)
            row=self.photo_row(); self.assertEqual(row[2],'Failed')
            # Calling the primitive models the confirmed retry without a new scan.
            c=self.conn(); op=c.execute("SELECT MAX(id) FROM operations WHERE status='Failed'").fetchone()[0]
            run=ns_db.create_run(c,mode='MOVE',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
            retry=metadata_transfer.retry(c,op,run_id=run)
            result=metadata_transfer.execute(c,retry)
            self.assertFalse(result['completed']); self.assertTrue(self.sidecar.exists())
        self.run_engine('--move','--confirm-source-empty')
        self.assertEqual(self.photo_row()[2],'Completed'); self.assertFalse(self.sidecar.exists())

    def test_changing_primary_after_import_does_not_refile_or_replace_it(self):
        self.run_engine('--copy'); original=self.photo_row(); db=next((self.root/'base/db').glob('*.db'))
        capture=self.conn().execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        choice={'capture_id':capture,'primary_id':'exif'}
        preview=metadata_decisions.preview(db,'primary',choice)
        metadata_decisions.confirm(db,kind='primary',selection=choice,token=preview['token'],request_id='change-primary')
        self.run_engine('--move')
        self.assertEqual(self.photo_row()[1:],original[1:]); self.assertTrue(self.photo.exists())

    def test_failed_retry_verification_does_not_leave_processing_in_finished_job(self):
        self.run_engine(); actual=durable._remove_verified_source
        with mock.patch.object(durable,'_remove_verified_source',side_effect=OSError('generated cleanup failure')):
            self.job(True)
        row=self.photo_row(); Path(row[1]+'.xmp').write_bytes(b'changed destination fixture')
        self.job(True)
        self.assertEqual(self.photo_row()[2],'Failed')
        self.assertEqual(self.conn().execute("SELECT COUNT(*) FROM operations WHERE status='Processing'").fetchone()[0],0)
        self.assertTrue(self.photo.exists()); self.assertTrue(self.sidecar.exists())

    def test_cancel_between_pairs_finishes_current_and_leaves_remaining(self):
        other=self.root/'source/zother.jpg'; Image.new('RGB',(46,35),(110,50,40)).save(other)
        Path(str(other)+'.xmp').write_bytes(metadata_index_test.packet())
        self.run_engine(); actual=metadata_transfer.execute
        def execute(*args):
            result=actual(*args); runtime.cancel_requested.set(); return result
        try:
            with mock.patch.object(metadata_transfer,'execute',side_effect=execute): self.job(True)
        finally:
            runtime.cancel_requested.clear()
        c=self.conn()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM photos WHERE status='Completed'").fetchone()[0],1)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM operations WHERE status='Cancelled'").fetchone()[0],1)
        self.assertEqual(len(list((self.root/'source').glob('*.jpg'))),1)
        self.assertEqual(len(list((self.root/'source').glob('*.xmp'))),1)

    def test_reindex_keeps_delivered_primary_date_and_filename(self):
        self.run_engine('--copy'); first=self.photo_row()
        self.run_engine('--rename',str(first[0]),'--name','renamed')
        original=self.photo_row()
        self.run_engine('--force-rehash')
        after=self.photo_row()
        self.assertEqual(after[1:3],original[1:3])
        self.assertEqual(json.loads(after[3])['date_taken'],'2005-03-04T05:06:07')

    def test_publication_failure_keeps_other_photos_running_and_reports_failure(self):
        other=self.root/'source/other.jpg'; Image.new('RGB',(46,36),(70,40,90)).save(other)
        self.run_engine(); actual=durable.copy_verify_delete
        def copy(src,dst,**kwargs):
            return (False,'generated sidecar failure') if str(src).endswith('.xmp') else actual(src,dst,**kwargs)
        with mock.patch.object(durable,'copy_verify_delete',side_effect=copy): self.job()
        self.assertEqual(self.photo_row()[2],'Failed')
        self.assertEqual(self.conn().execute('SELECT status FROM photos WHERE source_path=?',(str(other),)).fetchone()[0],'Copied')
        self.assertEqual(self.conn().execute("SELECT COUNT(*) FROM operations WHERE status='Failed'").fetchone()[0],1)

    def test_identical_existing_photo_without_sidecar_requires_choice(self):
        target=self.root/'dest/library/2005/03/04/photo.jpg'; target.parent.mkdir(parents=True)
        target.write_bytes(self.photo.read_bytes())
        self.run_engine('--move')
        self.assertEqual(self.photo_row()[2],'Pending'); self.assertTrue(self.photo.exists()); self.assertTrue(self.sidecar.exists())
        self.assertFalse(Path(str(target)+'.xmp').exists())

    def test_crash_after_source_photo_removal_retries_pair_after_confirmation(self):
        self.run_engine(); actual=durable._remove_verified_source
        def remove(src,*args):
            if str(src).endswith('.xmp'): raise SystemExit('generated interruption')
            return actual(src,*args)
        with mock.patch.object(durable,'_remove_verified_source',side_effect=remove), self.assertRaises(SystemExit): self.job(True)
        self.assertFalse(self.photo.exists()); self.assertTrue(self.sidecar.exists())
        self.run_engine('--move','--confirm-source-empty')
        row=self.photo_row(); self.assertEqual(row[2],'Completed')
        self.assertFalse(self.sidecar.exists()); self.assertTrue(Path(row[1]+'.xmp').exists())

    def test_reject_preserves_sidecar_and_move_cannot_return_it(self):
        self.run_engine('--copy'); pid=self.photo_row()[0]
        self.run_engine('--reject','--file-ids',str(pid)); old=self.photo_row()
        self.run_engine('--move'); self.assertEqual(self.photo_row()[2],'Rejected_Copied')
        self.assertEqual(self.photo_row()[1],old[1]); self.assertTrue(Path(old[1]+'.xmp').exists())
        self.assertTrue(self.photo.exists()); self.assertTrue(self.sidecar.exists())


if __name__ == '__main__': unittest.main()
