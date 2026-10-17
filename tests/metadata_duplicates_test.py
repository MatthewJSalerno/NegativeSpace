"""Generated exact-result consolidation, immutable origins and interruption checks."""
import hashlib
from pathlib import Path
import shutil
from unittest import mock
import unittest

from engine import metadata_command, metadata_decisions, metadata_edits, metadata_duplicates, metadata_embedded, metadata_photo_save, metadata_save, ns_db
import metadata_photo_save_test


class ExactEdits(unittest.TestCase):
    setUp=metadata_photo_save_test.PhotoSaves.setUp
    run_engine=metadata_photo_save_test.PhotoSaves.run_engine
    conn=metadata_photo_save_test.PhotoSaves.conn
    setup_catalog=metadata_photo_save_test.PhotoSaves.setup_catalog

    def pair(self, primary=True, sidecar=False, survivor_sidecar=False):
        self.setup_catalog(sidecar=sidecar)
        root=self.root/'dest'
        result=metadata_embedded.stage(root,self.dest.relative_to(root).as_posix(),'other.jpg',
            expected_sha1=self.sha,kind='embedded_exif',changes={'title':'Same'})
        self.other_source=self.photo.with_name('survivor.jpg')
        shutil.move(root/'other.jpg',self.other_source)
        if survivor_sidecar:
            shutil.copyfile(self.sidecar,Path(str(self.other_source)+'.xmp'))
        self.run_engine('--copy')
        self.other_id,path=self.c.execute('SELECT id,dest_path FROM photos WHERE source_path=?',(str(self.other_source),)).fetchone()
        self.other=Path(path);self.kept=self.other.read_bytes()
        self.digest=result['after_sha1']
        if primary:
            capture=self.c.execute('SELECT MAX(m.capture_id) FROM metadata_captures m JOIN photo_files pf ON pf.file_id=m.file_id WHERE pf.photo_id=?',(self.other_id,)).fetchone()[0]
            selection={'capture_id':capture,'primary_id':'exif'}
            p=metadata_decisions.preview(self.db,'primary',selection)
            metadata_decisions.confirm(self.db,kind='primary',selection=selection,token=p['token'],request_id='survivor-primary')
            plan=metadata_edits.preview_embedded_primary(self.db,photo_id=self.other_id,capture_id=capture,primary_id='exif',destination_root=root)
            run,_=ns_db.create_run(self.c,mode='METADATA',source=str(self.root/'source'),destination=str(root),submitted=plan)
            op=metadata_save.prepare(self.c,run_id=run,preview=plan,db_path=self.db,backups_dir=self.root/'backups',base_dir=self.root/'base')
            outcome=metadata_save.execute(self.c,op)
            self.assertEqual(outcome['outcome'],'completed',outcome)
        self.other=Path(self.c.execute('SELECT dest_path FROM photos WHERE id=?',(self.other_id,)).fetchone()[0])
        self.capture=self.c.execute('SELECT MAX(m.capture_id) FROM metadata_captures m JOIN photo_files pf ON pf.file_id=m.file_id WHERE pf.photo_id=?',(self.pid,)).fetchone()[0]

    def plan(self):
        return metadata_command.previews(self.db,self.root/'dest',{'edits':[dict(photo_id=self.pid,capture_id=self.capture,changes={'title':'Same'})]})['previews'][0]

    def prepare(self,plan=None):
        plan=plan or self.plan()
        run,_=ns_db.create_run(self.c,mode='METADATA',source=str(self.root/'source'),destination=str(self.root/'dest'),submitted=plan)
        return metadata_save.prepare(self.c,run_id=run,preview=plan,db_path=self.db,backups_dir=self.root/'backups',base_dir=self.root/'base')

    def assert_preserved(self):
        self.assertEqual(self.photo.read_bytes(),self.original)
        self.assertEqual(self.other.read_bytes(),self.kept)
        self.assertEqual(self.other_source.read_bytes(),self.kept)

    def test_confirmed_edit_keeps_existing_file_and_both_histories(self):
        self.pair();plan=self.plan()
        self.assertEqual(plan['exact_output']['duplicate']['photo_id'],self.other_id)
        self.assertEqual(self.dest.read_bytes(),self.original)
        op=self.prepare(plan);result=metadata_save.execute(self.c,op)
        self.assertEqual(result['outcome'],'completed',result)
        self.assertFalse(self.dest.exists());self.assert_preserved()
        self.assertEqual(self.c.execute('SELECT status,dest_path FROM photos WHERE id=?',(self.pid,)).fetchone(),('Duplicate',str(self.other)))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM file_changes').fetchone()[0],1)
        from webui import gallery
        run=self.c.execute('SELECT run_id FROM operations WHERE id=?',(op,)).fetchone()[0]
        clause,args=gallery._run_clause(run)
        visible=self.c.execute("SELECT p.id FROM photos p WHERE p.status='Copied'"+clause,args).fetchall()
        self.assertIn((self.other_id,),visible)
        self.assertTrue(metadata_save._event(self.c,op,'metadata_consolidated'))
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'already_finished')

    def test_unconfirmed_engine_caller_cannot_create_duplicate(self):
        self.pair()
        plan=metadata_photo_save_test.PhotoSaves.preview(self,{'title':'Same'})
        op=self.prepare(plan);result=metadata_save.execute(self.c,op)
        self.assertEqual(result['outcome'],'failed',result)
        self.assertEqual(self.dest.read_bytes(),self.original);self.assert_preserved()

    def test_rejected_survivor_refuses_before_any_edit(self):
        self.pair();self.c.execute("UPDATE photos SET status='Rejected' WHERE id=?",(self.other_id,));self.c.commit()
        with self.assertRaisesRegex(ValueError,'Rejects'):self.plan()
        self.assertEqual(self.dest.read_bytes(),self.original);self.assert_preserved()

    def test_changed_survivor_invalidates_confirmation(self):
        self.pair();plan=self.plan()
        self.other.write_bytes(self.kept+b'changed')
        with self.assertRaisesRegex(ValueError,'catalog hash'):self.prepare(plan)
        self.assertEqual(self.dest.read_bytes(),self.original)

    def test_removal_failure_is_retryable_without_repeating_edit(self):
        self.pair();op=self.prepare()
        with mock.patch.object(metadata_duplicates,'_unlink_verified',side_effect=PermissionError('generated refusal')):
            result=metadata_save.execute(self.c,op)
        self.assertEqual(result['outcome'],'failed',result)
        self.assertEqual(self.dest.read_bytes(),self.kept)
        self.assert_preserved()
        with mock.patch.object(metadata_embedded,'stage',side_effect=AssertionError('must not restage')):
            result=metadata_save.execute(self.c,op)
        self.assertEqual(result['outcome'],'completed',result)
        self.assertFalse(self.dest.exists());self.assert_preserved()

    def test_crash_after_unlink_replays_catalog_retirement(self):
        self.pair();op=self.prepare()
        original=metadata_duplicates._unlink_verified
        def interrupted(*args):
            original(*args)
            raise SystemExit('generated crash after removal')
        with mock.patch.object(metadata_duplicates,'_unlink_verified',side_effect=interrupted):
            with self.assertRaises(SystemExit):metadata_save.execute(self.c,op)
        self.assertFalse(self.dest.exists());self.assert_preserved()
        result=metadata_save.execute(self.c,op)
        self.assertEqual(result['outcome'],'completed',result)
        self.assert_preserved()

    def test_conflicting_primary_refuses_even_when_photo_bytes_would_match(self):
        self.pair(primary=False)
        with self.assertRaisesRegex(ValueError,'primary metadata differs'):self.plan()
        self.assertEqual(self.dest.read_bytes(),self.original);self.assert_preserved()

    def test_source_reindex_and_copy_do_not_recreate_consolidated_file(self):
        self.pair();op=self.prepare();self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'completed')
        self.run_engine('--force-rehash')
        self.assertEqual(self.c.execute('SELECT status,dest_path FROM photos WHERE id=?',(self.pid,)).fetchone(),('Duplicate',str(self.other)))
        self.run_engine('--copy')
        self.assertFalse(self.dest.exists());self.assert_preserved()

    def test_inactive_sidecar_is_retained_and_associated_with_survivor(self):
        from engine import xmp_store
        self.pair(sidecar=True)
        side=Path(str(self.dest)+'.xmp');before=side.read_bytes()
        op=self.prepare();result=metadata_save.execute(self.c,op)
        self.assertEqual(result['outcome'],'completed',result)
        self.assertFalse(side.exists());self.assert_preserved()
        receipt=metadata_save._event(self.c,op,'metadata_consolidated')
        self.assertTrue(any(xmp_store.original_bytes(self.c,v)==before for v in receipt['versions']))
        kept_file=self.c.execute('SELECT file_id FROM photo_files WHERE photo_id=?',(self.other_id,)).fetchone()[0]
        self.assertTrue(self.c.execute('SELECT 1 FROM xmp_arrival_files f JOIN xmp_arrivals a USING(arrival_id) WHERE f.file_id=?',(kept_file,)).fetchone())

    def test_later_survivor_edit_keeps_both_lineages_and_logs_connected(self):
        from webui import lineage,oplog
        self.pair();op=self.prepare();self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'completed')
        capture=self.c.execute('SELECT MAX(m.capture_id) FROM metadata_captures m JOIN photo_files pf ON pf.file_id=m.file_id WHERE pf.photo_id=?',(self.other_id,)).fetchone()[0]
        plan=metadata_command.previews(self.db,self.root/'dest',{'edits':[dict(photo_id=self.other_id,capture_id=capture,changes={'title':'Later'})]})['previews'][0]
        run,_=ns_db.create_run(self.c,mode='METADATA',source=str(self.root/'source'),destination=str(self.root/'dest'),submitted=plan)
        later=metadata_save.prepare(self.c,run_id=run,preview=plan,db_path=self.db,backups_dir=self.root/'backups',base_dir=self.root/'base')
        result=metadata_save.execute(self.c,later);self.assertEqual(result['outcome'],'completed',result)
        for pid in (self.pid,self.other_id):
            self.assertIn(op,[x['id'] for x in lineage.photo_lineage(self.db,pid)['operations']])
            self.assertIn(later,[x['id'] for x in lineage.photo_lineage(self.db,pid)['operations']])
            self.assertIn(op,[x['id'] for x in oplog.list_operations(self.db,photo=pid)['items']])
            self.assertIn(later,[x['id'] for x in oplog.list_operations(self.db,photo=pid)['items']])

    def test_new_duplicate_after_preview_stops_before_publication(self):
        self.setup_catalog()
        edit=dict(photo_id=self.pid,capture_id=self.capture,changes={'title':'Same'})
        plan=metadata_command.previews(self.db,self.root/'dest',{'edits':[edit]})['previews'][0]
        op=self.prepare(plan)
        other=self.root/'dest/library/later.jpg'
        output=metadata_embedded.stage(self.root/'dest',self.dest.relative_to(self.root/'dest').as_posix(),
            'library/later.jpg',expected_sha1=self.sha,kind='embedded_exif',changes={'title':'Same'})
        self.c.execute("INSERT INTO photos(source_path,dest_path,sha1_hash,status) VALUES(?,?,?,'Copied')",('generated-later',str(other),output['after_sha1']));self.c.commit()
        result=metadata_save.execute(self.c,op)
        self.assertEqual(result['outcome'],'failed',result)
        self.assertEqual(self.dest.read_bytes(),self.original)
        self.assertTrue(other.exists())

    def test_changed_survivor_after_interruption_prevents_cleanup(self):
        self.pair();op=self.prepare()
        with mock.patch.object(metadata_duplicates,'_unlink_verified',side_effect=PermissionError('generated refusal')):
            self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'failed')
        self.other.write_bytes(self.kept+b'changed')
        result=metadata_save.execute(self.c,op)
        self.assertEqual(result['outcome'],'failed',result)
        self.assertEqual(self.dest.read_bytes(),self.kept)
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_later_move_requires_consent_and_does_not_duplicate_survivor(self):
        self.pair();op=self.prepare();self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'completed')
        from engine import move_confirmation
        preview=move_confirmation.snapshot(self.c,source=self.root/'source',destination=self.root/'dest')
        self.assertIn(self.pid,[p['photo_id'] for p in preview['edited_originals']])
        self.run_engine('--move')
        self.assertTrue(self.photo.exists())
        self.run_engine('--move','--confirm-edited-sources','--request-id','consolidated-source-move')
        self.assertFalse(self.photo.exists())
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.other.read_bytes(),self.kept)
        self.assertEqual(self.c.execute('SELECT status FROM photos WHERE id=?',(self.pid,)).fetchone()[0],'Removed_Duplicate')

    def test_conflicting_active_sidecar_refuses_before_any_write(self):
        self.pair(primary=False,sidecar=True,survivor_sidecar=True)
        side=Path(str(self.other)+'.xmp');before=side.read_bytes()
        with self.assertRaisesRegex(ValueError,'primary metadata differs'):self.plan()
        self.assertEqual(side.read_bytes(),before)
        self.assertEqual(self.dest.read_bytes(),self.original)
        self.assert_preserved()
