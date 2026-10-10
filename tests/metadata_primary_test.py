"""Generated photo-only priority and embedded-primary activation/recovery checks."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import metadata_index_test
import metadata_import_test
from engine import metadata_decisions, metadata_edits, metadata_photo_save, metadata_save, ns_db, runtime, store


class Primary(unittest.TestCase):
    setUp=metadata_index_test.IndexTests.setUp
    run_engine=metadata_index_test.IndexTests.run_engine
    conn=metadata_index_test.IndexTests.conn
    job=metadata_import_test.Imports.job

    def setup_catalog(self,sidecar=True):
        runtime.cancel_requested.clear();self.addCleanup(runtime.cancel_requested.clear)
        if not sidecar:self.sidecar.unlink()
        self.original=self.photo.read_bytes()
        self.run_engine('--copy');self.c=self.conn();self.db=next((self.root/'base/db').glob('*.db'))
        self.pid,self.path=self.c.execute('SELECT id,dest_path FROM photos').fetchone()
        self.capture=self.c.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]

    def state(self):
        row=self.c.execute('SELECT dest_path,status,metadata_json,sha1_hash FROM photos WHERE id=?',(self.pid,)).fetchone()
        return row[:2]+(json.loads(row[2]),row[3])

    def prepare(self,primary):
        preview=metadata_edits.preview_embedded_primary(self.db,photo_id=self.pid,capture_id=self.capture,
            primary_id=primary,destination_root=self.root/'dest')
        run=ns_db.create_run(self.c,mode='METADATA',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
        return metadata_save.prepare(self.c,run_id=run,preview=preview,db_path=self.db,
            backups_dir=self.root/'backups',base_dir=self.root/'base')

    def apply(self,primary):
        result=metadata_save.execute(self.c,self.prepare(primary))
        self.assertEqual(result['outcome'],'completed',result)

    def test_photo_only_copy_uses_embedded_xmp_without_rewriting(self):
        self.setup_catalog(False)
        state=self.state();self.assertIn('/2004/02/03/',state[0]);self.assertEqual(state[2]['date_source'],'xmp')
        self.assertEqual(Path(state[0]).read_bytes(),self.original)
        self.assertEqual(self.photo.read_bytes(),self.original)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM metadata_decisions WHERE kind='primary'").fetchone()[0],0)
        self.run_engine('--force-rehash');self.assertEqual(self.state()[0],state[0]);self.assertEqual(self.state()[2:],state[2:])
        output=self.run_engine('--move');self.assertFalse(self.photo.exists(),output);self.assertEqual(self.state()[0],state[0])

    def test_explicit_exif_choice_controls_first_photo_only_import(self):
        self.sidecar.unlink();self.run_engine();self.db=next((self.root/'base/db').glob('*.db'));self.c=self.conn()
        self.pid=self.c.execute('SELECT id FROM photos').fetchone()[0]
        self.capture=self.c.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        choice={'capture_id':self.capture,'primary_id':'exif'}
        preview=metadata_decisions.preview(self.db,'primary',choice)
        metadata_decisions.confirm(self.db,kind='primary',selection=choice,token=preview['token'],request_id='choose-exif')
        self.run_engine('--copy');self.assertEqual(self.state()[1],'Copied');self.assertTrue(Path(self.state()[0]).is_file());self.assertIn('/1999/01/02/',self.state()[0]);self.assertEqual(self.state()[2]['date_source'],'exif')

    def test_empty_and_partial_embedded_xmp_do_not_fall_back(self):
        for date in ('','2001','2001-02'):
            with self.subTest(date=date):
                if date!='':self.setUp()
                packet=self.root/'packet.xmp';packet.write_bytes(b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'+metadata_index_test.packet(date)+b'<?xpacket end="w"?>')
                subprocess.run(['exiftool','-overwrite_original','-XMP<='+str(packet),str(self.photo)],check=True,capture_output=True)
                self.setup_catalog(False)
                self.assertIn('/Undated/',self.state()[0]);self.assertEqual(self.state()[2]['date_source'],'file_mtime')

    def test_switch_from_sidecar_to_exif_keeps_both_files_and_history(self):
        self.setup_catalog();old=self.path;side=Path(old+'.xmp').read_bytes()
        self.apply('exif');state=self.state()
        self.assertIn('/1999/01/02/',state[0]);self.assertFalse(Path(old).exists())
        self.assertEqual(Path(state[0]).read_bytes(),self.original);self.assertEqual(Path(state[0]+'.xmp').read_bytes(),side)
        self.assertEqual(metadata_save.active(self.c,self.pid)['primary_id'],'exif')
        self.assertEqual(metadata_save.active(self.c,self.pid)['sources']['sidecar:photo.jpg.xmp']['fields']['date_taken'],'2005-03-04T05:06:07')
        self.run_engine('--force-rehash');self.assertEqual(self.state(),state)
        self.capture=self.c.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        edit=metadata_edits.preview_catalog(self.db,photo_id=self.pid,capture_id=self.capture,changes={'title':'Next'},destination_root=self.root/'dest')
        self.assertEqual(edit['target']['kind'],'embedded_exif')

    def test_switch_to_embedded_xmp_without_sidecar_and_move_preserves_choice(self):
        self.setup_catalog(False);self.apply('exif');self.apply('embedded_xmp')
        state=self.state();self.assertIn('/2004/02/03/',state[0]);self.assertEqual(Path(state[0]).read_bytes(),self.original)
        output=self.run_engine('--move');self.assertFalse(self.photo.exists(),output);self.assertEqual(self.state()[0],state[0])
        self.assertEqual(metadata_save.active(self.c,self.pid)['primary_id'],'embedded_xmp')

    def test_saved_choice_survives_failed_refile_and_index_then_retries(self):
        self.setup_catalog();op=self.prepare('exif')
        with mock.patch.object(metadata_photo_save,'_refile',side_effect=OSError(5,'fixture move failure')):
            self.assertTrue(metadata_save.execute(self.c,op)['metadata_saved'])
        self.assertEqual(Path(self.path).read_bytes(),self.original)
        self.run_engine('--force-rehash')
        self.assertFalse(metadata_save.check(self.c,op,destination_root=self.root/'dest')['resolved'])
        before=self.state();output=self.run_engine('--move')
        self.assertTrue(self.photo.exists(),output);self.assertEqual(self.state(),before)
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'completed')
        self.assertIn('/1999/01/02/',self.state()[0]);self.assertEqual(Path(self.state()[0]).read_bytes(),self.original)

    def test_switch_noop_and_discard_do_not_rewrite(self):
        self.setup_catalog();self.apply('exif');path=Path(self.state()[0]);inode=path.stat().st_ino
        self.assertEqual(metadata_save.execute(self.c,self.prepare('exif'))['outcome'],'no_change')
        op=self.prepare('embedded_xmp');self.assertEqual(metadata_save.abandon(self.c,op)['outcome'],'abandoned')
        self.assertEqual(path.stat().st_ino,inode)

    def test_collision_refuses_before_primary_change(self):
        self.setup_catalog();before=self.state();collision=self.root/'dest/library/1999/01/02/photo.jpg.xmp'
        collision.parent.mkdir(parents=True);collision.write_bytes(b'occupied')
        with self.assertRaises(ValueError):self.prepare('exif')
        self.assertEqual(self.state(),before);self.assertEqual(collision.read_bytes(),b'occupied')

    def test_failed_photo_copy_does_not_activate_priority(self):
        self.sidecar.unlink();self.run_engine()
        with mock.patch.object(metadata_import_test.durable,'copy_verify_delete',return_value=(False,'fixture failure')):
            self.job()
        self.c=self.conn()
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM operation_events WHERE step='photo_metadata_activated'").fetchone()[0],0)

    def test_import_recovery_uses_frozen_priority(self):
        self.sidecar.unlink();self.run_engine()
        opened=[];connect=store.get_db_connection
        def connect_tracked(*args,**kwargs):
            conn=connect(*args,**kwargs);opened.append(conn);return conn
        with mock.patch.object(store,'get_db_connection',side_effect=connect_tracked), mock.patch.object(store,'log_operation',side_effect=SystemExit('fixture catalog interruption')):
            try:
                with self.assertRaises(SystemExit):self.job(True)
            finally:
                for conn in opened:conn.close()
        self.assertFalse(self.photo.exists())
        self.run_engine('--confirm-source-empty');self.c=self.conn();self.pid=self.c.execute('SELECT id FROM photos').fetchone()[0]
        self.assertEqual(self.state()[2]['date_taken'],'2004-02-03T04:05:06')
        self.assertGreater(self.c.execute("SELECT COUNT(*) FROM operation_events WHERE step='photo_metadata_activated'").fetchone()[0],0)

    def test_saved_but_unapplied_choice_still_previews_actual_date_move(self):
        self.setup_catalog()
        selection={'capture_id':self.capture,'primary_id':'exif'}
        decision=metadata_decisions.preview(self.db,'primary',selection)
        metadata_decisions.confirm(self.db,kind='primary',selection=selection,token=decision['token'],request_id='pending-exif')
        preview=metadata_edits.preview_embedded_primary(self.db,photo_id=self.pid,capture_id=self.capture,
            primary_id='exif',destination_root=self.root/'dest')
        self.assertEqual(preview['primary_before'],'sidecar:photo.jpg.xmp')
        self.assertTrue(preview['filing']['change'])
        self.apply('exif');self.assertIn('/1999/01/02/',self.state()[0])

    def test_new_destination_does_not_reuse_old_delivery_path(self):
        self.setup_catalog(False);old=self.state()[0]
        other=self.root/'other-dest';other.mkdir()
        self.run_engine('--copy','--force-rehash','--dest',str(other))
        self.assertTrue(Path(self.state()[0]).is_relative_to(other))
        self.assertEqual(Path(old).read_bytes(),self.original)
        self.assertEqual(Path(self.state()[0]).read_bytes(),self.original)

    def test_move_after_embedded_switch_keeps_inactive_sidecar(self):
        self.setup_catalog();self.apply('exif');state=self.state()
        side=Path(state[0]+'.xmp').read_bytes()
        output=self.run_engine('--move')
        self.assertFalse(self.photo.exists(),output);self.assertFalse(self.sidecar.exists(),output)
        self.assertEqual(self.state()[0],state[0])
        self.assertEqual(Path(state[0]+'.xmp').read_bytes(),side)
        self.assertEqual(metadata_save.active(self.c,self.pid)['primary_id'],'exif')

    def test_switch_after_embedded_edit_keeps_new_content_identity_on_index(self):
        self.setup_catalog(False);self.apply('embedded_xmp')
        preview=metadata_edits.preview_catalog(self.db,photo_id=self.pid,capture_id=self.capture,
            changes={'title':'Saved title'},destination_root=self.root/'dest')
        run=ns_db.create_run(self.c,mode='METADATA',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
        op=metadata_save.prepare(self.c,run_id=run,preview=preview,db_path=self.db,
            backups_dir=self.root/'backups',base_dir=self.root/'base')
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'completed')
        edited=Path(self.state()[0]).read_bytes();self.assertNotEqual(edited,self.original)
        self.apply('exif');state=self.state()
        self.run_engine('--force-rehash');self.assertEqual(self.state(),state)
        self.assertEqual(Path(state[0]).read_bytes(),edited)
        self.assertEqual(self.photo.read_bytes(),self.original)
        self.assertTrue(metadata_save.active(self.c,self.pid)['content_changed'])

    def test_cli_primary_switch_and_request_replay(self):
        self.setup_catalog()
        args=[sys.executable,'-m','engine','--base',str(self.root/'base'),'--dest',str(self.root/'dest'),'--backups',str(self.root/'backups')]
        edit={'photo_id':self.pid,'capture_id':self.capture,'primary_id':'exif'}
        result=subprocess.run(args+['--metadata','preview'],input=json.dumps({'edits':[edit]}),text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr);edit['token']=json.loads(result.stdout)['previews'][0]['token']
        result=subprocess.run(args+['--metadata','apply','--request-id','switch-exif'],input=json.dumps({'edits':[edit]}),text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout);self.assertIn('/1999/01/02/',self.state()[0])
        again=subprocess.run(args+['--metadata','apply','--request-id','switch-exif'],input=json.dumps({'edits':[edit]}),text=True,capture_output=True)
        self.assertNotEqual(again.returncode,0)


if __name__=='__main__':unittest.main()
