"""Generated Move-after-edit cleanup: consent, preservation and interrupted retries."""
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import metadata_photo_save_test
from engine import (durable, metadata_command, metadata_save, metadata_source_cleanup as cleanup,
                    ns_db, runtime, xmp_store)


class SourceCleanup(unittest.TestCase):
    setUp=metadata_photo_save_test.PhotoSaves.setUp
    run_engine=metadata_photo_save_test.PhotoSaves.run_engine
    conn=metadata_photo_save_test.PhotoSaves.conn
    setup_catalog=metadata_photo_save_test.PhotoSaves.setup_catalog
    preview=metadata_photo_save_test.PhotoSaves.preview
    prepare=metadata_photo_save_test.PhotoSaves.prepare
    execute=metadata_photo_save_test.PhotoSaves.execute
    current=metadata_photo_save_test.PhotoSaves.current

    def edited(self, *, sidecar=False):
        self.setup_catalog(sidecar=sidecar)
        self.execute(self.prepare({'date_taken':'2001-02-03T04:05:06'}))
        self.retained=Path(self.current()[1])
        self.retained_bytes=self.retained.read_bytes()

    def move_run(self, *, consent=True):
        run,_=ns_db.create_run(self.c,mode='MOVE',source=str(self.root/'source'),destination=str(self.root/'dest'),
            request_id='cleanup-'+str(self.c.execute('SELECT COUNT(*) FROM runs').fetchone()[0]),
            submitted={'confirm_edited_sources':consent})
        return run

    def authorize(self,run):
        cleanup.authorize_run(self.c,run,db_path=self.db,backups_dir=self.root/'backups',base_dir=self.root/'base')

    def clean(self,run):
        return cleanup.transfer(self.c,photo_id=self.pid,run_id=run,source_root=self.root/'source',destination_root=self.root/'dest')

    def test_preview_and_confirmation_are_separate_and_job_scoped(self):
        self.edited()
        result=cleanup.preview_batch(self.db,photo_ids=[self.pid],source_root=self.root/'source',destination_root=self.root/'dest')
        self.assertTrue(result['photos'][0]['eligible'],result)
        self.assertFalse(result['exact_original_photo_retained'])
        run=self.move_run(consent=False)
        with self.assertRaisesRegex(ValueError,'explicitly confirmed'):self.authorize(run)
        with self.assertRaises(ValueError):self.clean(run)
        self.assertEqual(self.photo.read_bytes(),self.original)
        accepted=self.move_run();self.authorize(accepted)
        with self.assertRaises(ValueError):self.clean(run)
        self.assertEqual(self.clean(accepted)['status'],'Completed')
        self.assertFalse(self.photo.exists())
        self.assertEqual(self.retained.read_bytes(),self.retained_bytes)
        self.assertEqual(self.c.execute('SELECT status FROM photos WHERE id=?',(self.pid,)).fetchone()[0],'Completed')
        self.assertEqual(self.c.execute('SELECT sha1_hash FROM source_snapshots').fetchone()[0],hashlib.sha1(self.original).hexdigest())
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM operation_files f JOIN operation_events e ON e.operation_id=f.operation_id WHERE e.step='source_cleanup_complete' AND f.role='retained_copy'").fetchone()[0],1)

    def test_backup_failure_preserves_source(self):
        self.edited();run=self.move_run()
        with mock.patch.object(ns_db,'backup_catalog',return_value={'outcome':'failed'}):
            with self.assertRaisesRegex(ValueError,'backup failed'):self.authorize(run)
        with self.assertRaises(ValueError):self.clean(run)
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_changed_source_or_destination_refuses(self):
        for target in ('source','destination'):
            with self.subTest(target=target):
                # This test reuses the same successful setup, restoring each modified file.
                if target=='source':self.edited()
                path=self.photo if target=='source' else self.retained
                before=path.read_bytes();path.write_bytes(before+b'changed')
                run=self.move_run();self.authorize(run)
                with self.assertRaises(ValueError):self.clean(run)
                self.assertTrue(self.photo.exists())
                path.write_bytes(before)

    def test_unrecorded_sidecar_preserves_source(self):
        self.edited();Path(str(self.photo)+'.xmp').write_text('unknown')
        run=self.move_run();self.authorize(run)
        with self.assertRaisesRegex(ValueError,'unrecorded sidecar'):self.clean(run)
        self.assertTrue(self.photo.exists())

    def test_missing_image_history_refuses_even_with_catalog_identity(self):
        self.edited();run=self.move_run();self.authorize(run)
        with mock.patch.object(cleanup.metadata_reproduce,'_image_chain',side_effect=ValueError('No verified history')):
            with self.assertRaisesRegex(ValueError,'history'):self.clean(run)
        self.assertTrue(self.photo.exists())

    def test_symlink_and_wrong_root_refuse(self):
        self.edited();run=self.move_run();self.authorize(run)
        self.photo.rename(self.photo.with_suffix('.saved'))
        self.photo.symlink_to(self.photo.with_suffix('.saved'))
        with self.assertRaises((ValueError,OSError)):self.clean(run)
        self.assertTrue(self.photo.is_symlink())
        with self.assertRaises((ValueError,OSError)):
            cleanup.transfer(self.c,photo_id=self.pid,run_id=run,source_root=self.root/'dest',destination_root=self.root/'dest')

    def test_fsync_failure_does_not_delete_and_observation_does_not_retry(self):
        self.edited();run=self.move_run();self.authorize(run)
        with mock.patch.object(cleanup,'_durable',side_effect=OSError('fixture disk failure')):
            result=self.clean(run)
        self.assertEqual(result['status'],'Failed',result)
        op=cleanup._pending(self.c,self.pid)[0]
        observed=cleanup.execute(self.c,op,source_root=self.root/'source',destination_root=self.root/'dest',observe=True)
        self.assertFalse(observed['resolved']);self.assertTrue(self.photo.exists())
        other=self.move_run(consent=False)
        with self.assertRaises(ValueError):self.clean(other)
        retry=self.move_run();self.authorize(retry)
        self.assertEqual(self.clean(retry)['status'],'Completed')
        self.assertFalse(self.photo.exists())
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM attention_issues WHERE resolved_at IS NULL').fetchone()[0],0)

    def test_interruption_after_unlink_is_observed_without_another_deletion(self):
        self.edited();run=self.move_run();self.authorize(run)
        original=durable._remove_verified_source
        def crash(*args,**kwargs):
            original(*args,**kwargs)
            raise KeyboardInterrupt('fixture stop after unlink')
        with mock.patch.object(durable,'_remove_verified_source',side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):self.clean(run)
        self.assertFalse(self.photo.exists())
        op=cleanup._pending(self.c,self.pid)[0]
        with mock.patch.object(durable,'_remove_verified_source') as remove:
            result=cleanup.execute(self.c,op,source_root=self.root/'source',destination_root=self.root/'dest',observe=True)
        remove.assert_not_called();self.assertTrue(result['resolved'],result)
        self.assertEqual(self.retained.read_bytes(),self.retained_bytes)

    def test_replacement_source_on_retry_is_preserved(self):
        self.edited();run=self.move_run();self.authorize(run)
        with mock.patch.object(cleanup,'_durable',side_effect=OSError('fixture disk failure')):self.clean(run)
        self.photo.rename(self.photo.with_suffix('.old'));self.photo.write_bytes(self.original)
        retry=self.move_run();self.authorize(retry)
        result=self.clean(retry)
        self.assertEqual(result['status'],'Failed');self.assertIn('source changed',result['error'])
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_exact_sidecar_archive_verified_before_pair_cleanup(self):
        self.edited(sidecar=True);run=self.move_run();self.authorize(run)
        before=self.sidecar.read_bytes()
        with mock.patch.object(xmp_store,'original_bytes',side_effect=ValueError('fixture corrupt archive')):
            with self.assertRaisesRegex(ValueError,'corrupt archive'):self.clean(run)
        self.assertTrue(self.photo.exists());self.assertEqual(self.sidecar.read_bytes(),before)
        result=self.clean(run)
        self.assertTrue(result['resolved'],result)
        self.assertFalse(self.photo.exists());self.assertFalse(self.sidecar.exists())
        self.assertEqual(self.retained.read_bytes(),self.retained_bytes)

    def test_cli_move_confirms_once_replay_refuses_and_copy_never_consumes(self):
        self.edited()
        self.c.execute("UPDATE runs SET status='Completed'");self.c.commit()
        args=[sys.executable,'-m','engine','--base',str(self.root/'base'),'--source',str(self.root/'source'),
              '--dest',str(self.root/'dest'),'--cache',str(self.root/'cache'),'--backups',str(self.root/'backups')]
        preview=subprocess.run(args+['--metadata','source-cleanup-preview'],input=json.dumps({'photo_ids':[self.pid]}),text=True,capture_output=True)
        self.assertEqual(preview.returncode,0,preview.stdout+preview.stderr)
        self.assertTrue(json.loads(preview.stdout)['photos'][0]['eligible'])
        refused=subprocess.run(args+['--copy','--confirm-edited-sources','--request-id','wrong-mode'],capture_output=True,text=True)
        self.assertNotEqual(refused.returncode,0);self.assertTrue(self.photo.exists())
        self.run_engine('--move');self.assertTrue(self.photo.exists())
        command=args+['--move','--confirm-edited-sources','--request-id','confirmed-move','--workers','1']
        moved=subprocess.run(command,text=True,capture_output=True)
        self.assertEqual(moved.returncode,0,moved.stdout+moved.stderr)
        self.assertFalse(self.photo.exists(),moved.stdout+moved.stderr)
        self.assertEqual(self.retained.read_bytes(),self.retained_bytes)
        replay=subprocess.run(command,text=True,capture_output=True)
        self.assertEqual(replay.returncode,4,replay.stdout+replay.stderr)
        changed=subprocess.run([s for s in command if s!='--confirm-edited-sources'],text=True,capture_output=True)
        self.assertNotEqual(changed.returncode,0)

    def test_multiple_edited_photos_and_normal_photo_use_one_job_confirmation(self):
        from PIL import Image
        self.edited()
        second=self.root/'source/second.jpg'
        Image.new('RGB',(36,24),(80,50,20)).save(second)
        self.c.execute("UPDATE runs SET status='Completed'");self.c.commit()
        self.run_engine('--copy')
        second_id,second_capture=self.c.execute('SELECT p.id,MAX(m.capture_id) FROM photos p JOIN photo_files f ON f.photo_id=p.id '
            'JOIN metadata_captures m ON m.file_id=f.file_id WHERE p.source_path=?',(str(second),)).fetchone()
        from engine import metadata_edits
        plan=metadata_edits.preview_catalog(self.db,photo_id=second_id,capture_id=second_capture,
            changes={'date_taken':'2002-03-04T05:06:07'},destination_root=self.root/'dest')
        run,_=ns_db.create_run(self.c,mode='METADATA',source=str(self.root/'source'),destination=str(self.root/'dest'))
        op=metadata_save.prepare(self.c,run_id=run,preview=plan,db_path=self.db,backups_dir=self.root/'backups',
            base_dir=self.root/'base',cache_root=self.root/'cache')
        self.execute(op)
        ordinary=self.root/'source/ordinary.jpg'
        Image.new('RGB',(44,22),(5,60,90)).save(ordinary)
        self.c.execute("UPDATE runs SET status='Completed'");self.c.commit()
        self.run_engine('--move','--confirm-edited-sources','--request-id','one-batch')
        self.assertFalse(self.photo.exists());self.assertFalse(second.exists());self.assertFalse(ordinary.exists())
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM operation_events WHERE step='source_cleanup_authorized'").fetchone()[0],1)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM operation_events WHERE step='source_cleanup_complete'").fetchone()[0],2)
        self.assertEqual(self.retained.read_bytes(),self.retained_bytes)

    def test_shared_sidecar_stays_with_unconsumed_owner(self):
        from PIL import Image
        from engine import metadata_decisions
        # A stem sidecar belongs to both different files. Import under an explicit setting.
        self.sidecar.rename(self.root/'source/photo.xmp')
        self.sidecar=self.root/'source/photo.xmp'
        other=self.root/'source/photo.png';Image.new('RGB',(12,12),(80,70,60)).save(other)
        self.run_engine()
        self.c=self.conn();self.db=next((self.root/'base/db').glob('*.db'))
        ns_db.save_settings(self.c,{'xmp_association':'all'},expected_revisions={'xmp_association':0})
        self.run_engine('--copy')
        self.pid,self.dest,self.sha=self.c.execute('SELECT id,dest_path,sha1_hash FROM photos WHERE source_path=?',(str(self.photo),)).fetchone()
        self.capture=self.c.execute('SELECT MAX(m.capture_id) FROM metadata_captures m JOIN photo_files p ON p.file_id=m.file_id WHERE p.photo_id=?',(self.pid,)).fetchone()[0]
        choice={'capture_id':self.capture,'primary_id':'exif'}
        proposal=metadata_decisions.preview(self.db,'primary',choice)
        metadata_decisions.confirm(self.db,kind='primary',selection=choice,token=proposal['token'],request_id='fixture-shared-primary')
        self.execute(self.prepare({'date_taken':'2001-02-03T04:05:06'}))
        run=self.move_run();self.authorize(run)
        result=self.clean(run)
        self.assertTrue(result['resolved'],result)
        self.assertFalse(self.photo.exists());self.assertTrue(other.exists());self.assertTrue(self.sidecar.exists())
        self.assertTrue(result['notes'])
        self.c.execute("UPDATE runs SET status='Completed'");self.c.commit()
        self.run_engine('--move')
        self.assertFalse(other.exists());self.assertFalse(self.sidecar.exists())

    def test_cancel_before_deletion_preserves_source(self):
        self.edited();run=self.move_run();self.authorize(run)
        runtime.cancel_requested.set()
        result=self.clean(run)
        self.assertEqual(result['status'],'Failed');self.assertTrue(self.photo.exists())
        runtime.cancel_requested.clear()

    def test_unconfirmed_move_still_moves_other_photos(self):
        from PIL import Image
        self.edited();ordinary=self.root/'source/ordinary.jpg'
        Image.new('RGB',(20,24),(10,70,90)).save(ordinary)
        self.c.execute("UPDATE runs SET status='Completed'");self.c.commit()
        self.run_engine('--move')
        self.assertTrue(self.photo.exists());self.assertFalse(ordinary.exists())
        self.assertEqual(self.retained.read_bytes(),self.retained_bytes)

    def test_rename_only_needs_no_edited_source_consent(self):
        # No separate, unapplied primary-source decision: this is only a filename change.
        self.sidecar.unlink();self.run_engine('--copy')
        self.c=self.conn();self.pid=self.c.execute('SELECT id FROM photos').fetchone()[0]
        self.run_engine('--rename',str(self.pid),'--name','renamed.jpg','--request-id','rename-only')
        current=Path(self.current()[1]);before=current.read_bytes()
        output=self.run_engine('--move')
        self.assertFalse(self.photo.exists(),output);self.assertEqual(current.read_bytes(),before)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM operation_events WHERE step='source_cleanup_authorized'").fetchone()[0],0)

    def test_cli_retry_finishes_sidecar_after_source_photo_was_removed(self):
        from PIL import Image
        self.edited(sidecar=True);run=self.move_run();self.authorize(run)
        original_unlink=Path.unlink
        def interrupted(path,*args,**kwargs):
            if path==self.sidecar:raise KeyboardInterrupt('fixture interruption before XMP removal')
            return original_unlink(path,*args,**kwargs)
        with mock.patch.object(Path,'unlink',interrupted):
            with self.assertRaises(KeyboardInterrupt):self.clean(run)
        self.assertFalse(self.photo.exists());self.assertTrue(self.sidecar.exists())
        other=self.root/'source/other.jpg';Image.new('RGB',(10,12),(4,8,12)).save(other)
        self.c.execute("UPDATE runs SET status='Completed'");self.c.commit()
        self.run_engine('--move','--confirm-edited-sources','--request-id','retry-missing-photo')
        self.assertFalse(self.sidecar.exists())
        self.assertEqual(self.retained.read_bytes(),self.retained_bytes)
        self.assertEqual(self.c.execute('SELECT status FROM photos WHERE id=?',(self.pid,)).fetchone()[0],'Completed')

    def test_rejected_edited_copy_stays_rejected_during_source_cleanup(self):
        self.edited()
        self.c.execute("UPDATE runs SET status='Completed'");self.c.commit()
        self.run_engine('--reject','--file-ids',str(self.pid),'--request-id','reject-edited')
        kept=Path(self.current()[1]);before=kept.read_bytes()
        self.run_engine('--move','--file-ids',str(self.pid),'--confirm-edited-sources','--request-id','move-rejected')
        self.assertFalse(self.photo.exists());self.assertEqual(kept.read_bytes(),before)
        self.assertEqual(self.c.execute('SELECT status FROM photos WHERE id=?',(self.pid,)).fetchone()[0],'Rejected')

    def test_preview_request_validation(self):
        for request in ({'photo_ids':[]},{'photo_ids':[True]},{'photo_ids':[1,1]},{'photo_ids':[1],'confirm':True}):
            with self.assertRaises(ValueError):metadata_command.validate(request,'source-cleanup-preview')


if __name__=='__main__':unittest.main()
