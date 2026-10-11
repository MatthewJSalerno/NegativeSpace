"""Confirmed incoming choices use verified metadata saves and existing relocations."""
import json
import subprocess
import sys
from pathlib import Path
import unittest
from unittest import mock

import metadata_index_test
import metadata_incoming_test
from engine import (constants, durable, metadata_command, metadata_incoming, metadata_incoming_apply,
                    metadata_relocate, metadata_save, ns_db, runtime, xmp_store)


class IncomingApplied(unittest.TestCase):
    setUp=metadata_index_test.IndexTests.setUp
    conn=metadata_index_test.IndexTests.conn
    run_engine=metadata_index_test.IndexTests.run_engine
    setup_arrival=metadata_incoming_test.Incoming.setup_arrival

    def choose(self, primary='use_incoming', location='keep'):
        start=metadata_incoming.preview(self.db,capture_id=self.cap,photo_id=self.target[0])
        version=start['after']['versions'][0]['version_id'] if primary=='use_incoming' else None
        choice=metadata_incoming.preview(self.db,capture_id=self.cap,photo_id=self.target[0],
            primary=primary,version_id=version,location=location)
        saved=metadata_incoming.confirm(self.db,selection=choice['selection'],token=choice['token'],
            request_id='choice-'+str(self.conn().execute('SELECT MAX(decision_id) FROM metadata_decisions').fetchone()[0]))
        self.decision=saved['revision']
        self.target_capture=self.conn().execute('SELECT MAX(capture_id) FROM metadata_captures WHERE file_id='
            '(SELECT file_id FROM photo_files WHERE photo_id=?)',(self.target[0],)).fetchone()[0]
        return self.preview()

    def preview(self):
        return metadata_incoming_apply.preview(self.db,photo_id=self.target[0],capture_id=self.target_capture,
            incoming_decision_id=self.decision,destination_root=self.root/'dest')

    def prepare(self, preview=None):
        self.c=self.conn();preview=preview or self.preview()
        self.run=ns_db.create_run(self.c,mode='METADATA',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
        runtime.cancel_requested.clear();self.addCleanup(runtime.cancel_requested.clear)
        return metadata_save.prepare(self.c,run_id=self.run,preview=preview,db_path=self.db,
            backups_dir=self.root/'backups',base_dir=self.root/'base')

    def apply(self, primary='use_incoming', location='keep'):
        preview=self.choose(primary,location)
        op=self.prepare(preview)
        result=metadata_save.execute(self.c,op)
        self.assertEqual(result['outcome'],'completed',result)
        self.c.execute("UPDATE runs SET status='Completed' WHERE id=?",(self.run,))
        self.c.commit()
        return op

    def current(self):
        return self.conn().execute('SELECT dest_path,status,metadata_json FROM photos WHERE id=?',(self.target[0],)).fetchone()

    def test_use_incoming_refiles_preserves_originals_and_only_later_move_cleans_source(self):
        self.setup_arrival();original=Path(self.target[1]+'.xmp').read_bytes();incoming=self.note.read_bytes()
        photo=self.incoming.read_bytes();op=self.apply()
        path,status,meta=self.current()
        self.assertIn('/library/2011/02/03/',path);self.assertEqual(status,'Copied')
        self.assertEqual(Path(path).read_bytes(),photo);self.assertEqual(Path(path+'.xmp').read_bytes(),incoming)
        self.assertTrue(self.incoming.exists());self.assertTrue(self.note.exists())
        m=metadata_save._manifest(self.c,op)[3]
        self.assertEqual(xmp_store.original_bytes(self.c,m['old_version']),original)
        self.assertEqual(json.loads(meta)['date_taken'],'2011-02-03T04:05:06')
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'already_finished')
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertFalse(self.incoming.exists());self.assertFalse(self.note.exists())
        self.assertEqual(self.current()[0],path)

    def test_all_rejected_combinations_preserve_location_independently(self):
        self.setup_arrival(current_xmp=False,rejected=True);before=self.current()
        self.apply('use_incoming','keep')
        path,status,_=self.current();self.assertEqual((path,status),before[:2])
        self.assertEqual(Path(path+'.xmp').read_bytes(),self.note.read_bytes())
        self.run_engine('--copy','--file-ids',str(self.pid))
        self.assertEqual(self.current()[:2],before[:2]);self.assertTrue(self.note.exists())

    def test_combined_use_and_return_moves_verified_pair_and_restores_copied_status(self):
        self.setup_arrival(current_xmp=False,rejected=True);old=self.current()[0]
        self.apply('use_incoming','library')
        path,status,_=self.current()
        self.assertIn('/library/2011/02/03/',path);self.assertEqual(status,'Copied')
        self.assertFalse(Path(old).exists());self.assertFalse(Path(old+'.xmp').exists())
        self.assertEqual(Path(path+'.xmp').read_bytes(),self.note.read_bytes())
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertFalse(self.incoming.exists());self.assertFalse(self.note.exists())

    def test_keep_and_return_does_not_create_sidecar_or_change_metadata(self):
        self.setup_arrival(current_xmp=False,rejected=True);old=self.current()
        self.apply('keep_current','library')
        path,status,meta=self.current()
        self.assertIn('/library/2004/02/03/',path);self.assertEqual(status,'Copied')
        self.assertEqual(meta,old[2]);self.assertFalse(Path(path+'.xmp').exists())
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertFalse(self.note.exists());self.assertFalse(self.incoming.exists())

    def test_keep_and_return_moves_existing_sidecar_unchanged(self):
        self.setup_arrival(rejected=True);before=Path(self.current()[0]+'.xmp').read_bytes()
        self.apply('keep_current','library')
        path,status,_=self.current();self.assertEqual(status,'Copied')
        self.assertEqual(Path(path+'.xmp').read_bytes(),before)
        self.assertIn('/library/2005/03/04/',path)

    def test_keep_and_stay_is_applied_without_primary_change_or_file_write(self):
        self.setup_arrival(current_xmp=False,rejected=True);before=self.current()
        self.apply('keep_current','keep')
        self.assertEqual(self.current(),before)
        self.assertFalse(Path(before[0]+'.xmp').exists())
        self.run_engine('--move','--file-ids',str(self.pid));self.assertFalse(self.note.exists())

    def test_empty_incoming_date_files_to_undated_without_filling_packet(self):
        self.setup_arrival();self.note.write_bytes(metadata_index_test.packet(''));self.run_engine()
        self.cap=self.conn().execute('SELECT MAX(capture_id) FROM metadata_captures WHERE file_id='
            '(SELECT file_id FROM photo_files WHERE photo_id=?)',(self.pid,)).fetchone()[0]
        self.apply();path=self.current()[0]
        self.assertIn('/library/Undated/',path)
        self.assertEqual(Path(path+'.xmp').read_bytes(),self.note.read_bytes())

    def test_newer_choice_invalidates_previous_choice(self):
        self.setup_arrival();self.choose();old=self.decision
        self.choose('keep_current');self.decision=old
        with self.assertRaises(ns_db.RevisionConflict):self.preview()

    def test_job_watermark_refuses_later_choice(self):
        self.setup_arrival();self.choose()
        with self.assertRaises(ns_db.RevisionConflict):
            metadata_incoming_apply.preview(self.db,photo_id=self.target[0],capture_id=self.target_capture,
                incoming_decision_id=self.decision,destination_root=self.root/'dest',settings={'metadata_decision_highwater':0})

    def test_changed_target_refuses_application_and_consumption(self):
        self.setup_arrival();self.choose();c=self.conn()
        c.execute('UPDATE photo_files SET revision=revision+1 WHERE photo_id=?',(self.target[0],));c.commit()
        with self.assertRaises(ns_db.RevisionConflict):self.preview()
        self.run_engine('--move','--file-ids',str(self.pid));self.assertTrue(self.incoming.exists())

    def test_occupied_return_target_refuses_before_changing_primary(self):
        self.setup_arrival(rejected=True);preview=self.choose(location='library');old=self.current()
        occupied=self.root/'dest'/preview['filing']['proposed'];occupied.parent.mkdir(parents=True);occupied.write_bytes(b'occupied')
        with self.assertRaises(ValueError):self.prepare(preview)
        self.assertEqual(self.current(),old);self.assertEqual(occupied.read_bytes(),b'occupied')

    def test_orphan_return_sidecar_refuses_before_publication(self):
        self.setup_arrival(rejected=True);preview=self.choose(location='library');old=self.current()
        occupied=Path(str(self.root/'dest'/preview['filing']['proposed'])+'.xmp')
        occupied.parent.mkdir(parents=True);occupied.write_bytes(b'leave alone')
        with self.assertRaises(ValueError):self.prepare(preview)
        self.assertEqual(self.current(),old);self.assertEqual(occupied.read_bytes(),b'leave alone')

    def test_failed_backup_never_applies_choice(self):
        self.setup_arrival();preview=self.choose();before=self.current()
        with mock.patch.object(ns_db,'backup_catalog',return_value={'outcome':'failed'}):op=self.prepare(preview)
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'failed')
        self.assertEqual(self.current(),before);self.assertTrue(self.incoming.exists())
        self.assertIsNone(metadata_save._event(self.c,op,'incoming_choice_applied'))

    def test_refile_failure_keeps_verified_edit_and_explicit_retry_finishes(self):
        self.setup_arrival(rejected=True);preview=self.choose(location='library');op=self.prepare(preview)
        with mock.patch.object(metadata_relocate,'perform',side_effect=OSError('generated move failure')):
            self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'failed')
        self.assertTrue(metadata_save._event(self.c,op,'metadata_saved'))
        self.assertIsNone(metadata_save._event(self.c,op,'incoming_choice_applied'))
        self.assertTrue(self.current()[1].startswith('Rejected'));self.assertTrue(self.incoming.exists())
        with self.assertRaises(ValueError):metadata_save.abandon(self.c,op)
        result=metadata_save.execute(self.c,op);self.assertEqual(result['outcome'],'completed',result)
        self.assertEqual(self.current()[1],'Copied')

    def test_return_only_retry_after_files_move_before_catalog_receipt(self):
        self.setup_arrival(rejected=True);preview=self.choose('keep_current','library');op=self.prepare(preview)
        from engine import relocate
        with mock.patch.object(relocate,'_record_relocation',side_effect=OSError('generated catalog interruption')):
            self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'failed')
        with self.assertRaises(ValueError):metadata_save.abandon(self.c,op)
        result=metadata_save.execute(self.c,op);self.assertEqual(result['outcome'],'completed',result)
        self.assertEqual(self.current()[1],'Copied')

    def test_discard_unchanged_choice_does_not_mark_it_applied(self):
        self.setup_arrival();preview=self.choose();op=self.prepare(preview);before=self.current()
        self.assertEqual(metadata_save.abandon(self.c,op)['outcome'],'abandoned')
        self.assertIsNone(metadata_save._event(self.c,op,'incoming_choice_applied'))
        self.assertEqual(self.current(),before)

    def test_cli_preview_apply_and_request_replay(self):
        self.setup_arrival();self.choose()
        request={'edits':[{'photo_id':self.target[0],'capture_id':self.target_capture,'incoming_decision_id':self.decision}]}
        args=[sys.executable,'-m','engine','--dest',str(self.root/'dest'),'--base',str(self.root/'base'),
            '--cache',str(self.root/'cache'),'--backups',str(self.root/'backups')]
        p=subprocess.run(args+['--metadata','preview'],input=json.dumps(request),capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        preview=json.loads(p.stdout)['previews'][0];request['edits'][0]['token']=preview['token']
        command=args+['--metadata','apply','--request-id','apply-incoming']
        for expected in (0, constants.EXIT_REQUEST_ALREADY_ACCEPTED):
            p=subprocess.run(command,input=json.dumps(request),capture_output=True,text=True)
            self.assertEqual(p.returncode,expected,p.stdout+p.stderr)
        self.assertEqual(self.conn().execute("SELECT COUNT(*) FROM operation_events WHERE step='incoming_choice_applied'").fetchone()[0],1)
        self.assertIn('/library/2011/02/03/',self.current()[0])

    def test_same_photo_late_xmp_choice_keeps_anchor_and_allows_later_move(self):
        self.sidecar.unlink();self.run_engine('--copy');self.db=next((self.root/'base/db').glob('*.db'))
        self.target=self.conn().execute('SELECT id,dest_path FROM photos').fetchone();self.pid=self.target[0]
        self.sidecar.write_bytes(metadata_index_test.packet('2014-01-02'));self.run_engine()
        self.cap=self.conn().execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        self.apply();self.assertEqual(self.current()[1],'Copied')
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertEqual(self.current()[1],'Completed');self.assertFalse(self.photo.exists());self.assertFalse(self.sidecar.exists())
        self.assertTrue(Path(self.current()[0]).exists())

    def test_failure_of_archived_alternative_blocks_application(self):
        self.setup_arrival();preview=self.choose()
        with mock.patch.object(xmp_store,'original_bytes',side_effect=ValueError('generated corrupt blob')):
            with self.assertRaises(ValueError):self.prepare(preview)
        self.assertTrue(self.incoming.exists());self.assertTrue(self.note.exists())

    def test_same_photo_copy_then_move_preserves_anchor_and_decision_binding(self):
        self.sidecar.unlink();self.run_engine('--copy');self.db=next((self.root/'base/db').glob('*.db'))
        self.target=self.conn().execute('SELECT id,dest_path FROM photos').fetchone();self.pid=self.target[0]
        self.sidecar.write_bytes(metadata_index_test.packet('2014-01-02'));self.run_engine()
        self.cap=self.conn().execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        self.apply()
        for _ in range(2):
            self.run_engine('--copy','--file-ids',str(self.pid))
            self.assertEqual(self.current()[1],'Copied');self.assertTrue(self.photo.exists())
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertEqual(self.current()[1],'Completed');self.assertFalse(self.photo.exists());self.assertFalse(self.sidecar.exists())

    def test_late_changed_sidecar_keep_current_then_move_archives_alternative(self):
        self.run_engine('--copy');self.db=next((self.root/'base/db').glob('*.db'))
        self.target=self.conn().execute('SELECT id,dest_path FROM photos').fetchone();self.pid=self.target[0]
        previous=Path(self.target[1]+'.xmp').read_bytes()
        self.sidecar.write_bytes(metadata_index_test.packet('2014-01-02'));self.run_engine()
        self.cap=self.conn().execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        self.apply('keep_current')
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertEqual(self.current()[1],'Completed');self.assertFalse(self.photo.exists());self.assertFalse(self.sidecar.exists())
        self.assertEqual(Path(self.current()[0]+'.xmp').read_bytes(),previous)

    def test_changed_destination_after_activation_cannot_authorize_source_cleanup(self):
        self.setup_arrival();self.apply();Path(self.current()[0]).write_bytes(b'changed photo')
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertTrue(self.incoming.exists());self.assertTrue(self.note.exists())

    def test_changed_source_sidecar_after_activation_stays_at_source(self):
        self.setup_arrival();self.apply();self.note.write_bytes(metadata_index_test.packet('2020-01-01'))
        metadata_incoming_test.Incoming.move(self)
        self.assertTrue(self.incoming.exists());self.assertTrue(self.note.exists())

    def test_identical_incoming_activation_preserves_photo_and_packet(self):
        self.setup_arrival(identical=True);before=self.current();photo=Path(before[0]).read_bytes()
        packet=Path(before[0]+'.xmp').read_bytes();op=self.apply()
        self.assertEqual(self.current()[:2],before[:2]);self.assertEqual(Path(before[0]).read_bytes(),photo)
        self.assertEqual(Path(before[0]+'.xmp').read_bytes(),packet)
        self.assertIsNotNone(metadata_save._event(self.c,op,'incoming_choice_applied'))

    def test_cancelled_choice_is_not_applied_and_can_be_discarded(self):
        self.setup_arrival();preview=self.choose();op=self.prepare(preview)
        runtime.cancel_requested.set()
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'failed')
        runtime.cancel_requested.clear()
        self.assertEqual(metadata_save.abandon(self.c,op)['outcome'],'abandoned')
        self.assertIsNone(metadata_save._event(self.c,op,'incoming_choice_applied'))

    def test_return_only_check_is_read_only_and_does_not_finish_cleanup(self):
        self.setup_arrival(rejected=True);preview=self.choose('keep_current','library');op=self.prepare(preview)
        before=self.current();self.assertFalse(metadata_save.check(self.c,op,destination_root=self.root/'dest')['resolved'])
        self.assertEqual(self.current(),before);self.assertIsNone(metadata_save._event(self.c,op,'incoming_choice_applied'))
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'completed')

    def test_symlink_target_is_refused_without_changing_referenced_file(self):
        self.setup_arrival();preview=self.choose();path=Path(self.current()[0]);outside=self.root/'outside.jpg'
        outside.write_bytes(path.read_bytes());path.unlink();path.symlink_to(outside)
        with self.assertRaises((ValueError,OSError)):self.prepare(preview)
        self.assertTrue(self.note.exists());self.assertEqual(outside.read_bytes(),self.incoming.read_bytes())

    def test_wrong_photo_or_capture_cannot_apply_an_incoming_decision(self):
        self.setup_arrival();self.choose()
        for pid,cap in ((self.pid,self.cap),(self.target[0],self.cap)):
            with self.assertRaises(ValueError):
                metadata_incoming_apply.preview(self.db,photo_id=pid,capture_id=cap,
                    incoming_decision_id=self.decision,destination_root=self.root/'dest')

    def test_new_primary_after_choice_requires_new_confirmation(self):
        self.setup_arrival();self.choose()
        c=self.conn();c.execute('UPDATE file_states SET revision=revision+1 WHERE file_id='
            "(SELECT file_id FROM file_states WHERE current_path=? AND location_role='destination')",(self.current()[0],));c.commit()
        with self.assertRaises(ns_db.RevisionConflict):self.preview()

    def test_incomplete_return_blocks_copy_move_until_retry(self):
        self.setup_arrival(rejected=True);preview=self.choose(location='library');op=self.prepare(preview)
        with mock.patch.object(metadata_relocate,'perform',side_effect=OSError('generated interruption')):
            self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'failed')
        self.c.execute("UPDATE runs SET status='Failed' WHERE id=?",(self.run,));self.c.commit()
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertTrue(self.note.exists());self.assertTrue(self.incoming.exists())
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'completed')
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertFalse(self.note.exists());self.assertFalse(self.incoming.exists())

    def test_reindexed_incoming_packet_invalidates_saved_choice(self):
        self.setup_arrival();self.choose()
        self.note.write_bytes(metadata_index_test.packet('2022-01-01'));self.run_engine()
        with self.assertRaises(ns_db.RevisionConflict):self.preview()

    def test_all_alternatives_reverify_before_publication(self):
        self.setup_arrival();extra=self.note.with_name('new-name.xmp')
        extra.write_bytes(metadata_index_test.packet('2019-01-01'));self.run_engine()
        self.cap=self.conn().execute('SELECT MAX(capture_id) FROM metadata_captures WHERE file_id='
            '(SELECT file_id FROM photo_files WHERE photo_id=?)',(self.pid,)).fetchone()[0]
        preview=self.choose();op=self.prepare(preview);before=self.current();old=Path(before[0]+'.xmp').read_bytes()
        selected=preview['activation']['version_id']
        alternative=next(v['version_id'] for v in preview['incoming_choice']['value']['versions'] if v['version_id']!=selected)
        original=xmp_store.original_bytes
        def damaged(conn, version_id):
            return b'corrupt' if version_id==alternative else original(conn,version_id)
        with mock.patch.object(xmp_store,'original_bytes',side_effect=damaged):
            result=metadata_save.execute(self.c,op)
        self.assertEqual(result['outcome'],'failed',result);self.assertEqual(self.current(),before)
        self.assertEqual(Path(before[0]+'.xmp').read_bytes(),old)
        self.assertTrue(self.incoming.exists());self.assertTrue(extra.exists())

    def test_return_restores_completed_status_for_consumed_source(self):
        self.setup_arrival(rejected=True)
        c=self.conn();c.execute("UPDATE photos SET status='Rejected' WHERE id=?",(self.target[0],));c.commit()
        self.apply('keep_current','library')
        self.assertEqual(self.current()[1],'Completed')

    def test_request_validation_rejects_extra_fields_and_noninteger_decision(self):
        for decision in (True,0,-1,'1'):
            with self.assertRaises(ValueError):
                metadata_command.validate({'edits':[dict(photo_id=1,capture_id=1,incoming_decision_id=decision)]},'preview')
        with self.assertRaises(ValueError):
            metadata_command.validate({'edits':[dict(photo_id=1,capture_id=1,incoming_decision_id=1,location='library')]},'preview')


    def test_identical_inactive_xmp_requires_explicit_primary_activation(self):
        from engine import metadata_edits
        self.setup_arrival(identical=True)
        capture=self.conn().execute('SELECT MAX(capture_id) FROM metadata_captures WHERE file_id='
            '(SELECT file_id FROM photo_files WHERE photo_id=?)',(self.target[0],)).fetchone()[0]
        switched=metadata_edits.preview_embedded_primary(self.db,photo_id=self.target[0],capture_id=capture,
            primary_id='exif',destination_root=self.root/'dest')
        op=self.prepare(switched)
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'completed')
        self.c.execute("UPDATE runs SET status='Completed' WHERE id=?",(self.run,));self.c.commit()
        preview=self.choose()
        self.assertTrue(preview['incoming_choice']['value']['activation_required'])
        self.run_engine('--move','--file-ids',str(self.pid))
        self.assertTrue(self.incoming.exists());self.assertTrue(self.note.exists())
        op=self.prepare()
        result=metadata_save.execute(self.c,op);self.assertEqual(result['outcome'],'completed',result)
        self.assertTrue(metadata_save.active(self.c,self.target[0])['primary_id'].startswith('sidecar:'))
