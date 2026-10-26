"""Generated end-to-end embedded saves and interrupted publication recovery."""
import hashlib
import json
from types import SimpleNamespace
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from PIL import Image, ImageDraw

import metadata_index_test
from engine import review
from engine import (constants, durable, fileinfo, metadata_command, metadata_decisions, metadata_edits, metadata_photo_save,
                    metadata_save, ns_db, ns_similarity, ns_similarity_cache, relocate, runtime, thumbnails)


class PhotoSaves(unittest.TestCase):
    setUp=metadata_index_test.IndexTests.setUp
    run_engine=metadata_index_test.IndexTests.run_engine
    conn=metadata_index_test.IndexTests.conn

    def setup_catalog(self, *, primary='exif', sidecar=False):
        runtime.cancel_requested.clear()
        self.addCleanup(runtime.cancel_requested.clear)
        if not sidecar:self.sidecar.unlink()
        self.run_engine('--copy')
        self.c=self.conn();self.db=next((self.root/'base/db').glob('*.db'))
        self.pid,self.dest,self.sha=self.c.execute('SELECT id,dest_path,sha1_hash FROM photos').fetchone()
        self.dest=Path(self.dest);self.original=self.dest.read_bytes()
        self.capture=self.c.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        choice={'capture_id':self.capture,'primary_id':primary}
        preview=metadata_decisions.preview(self.db,'primary',choice)
        metadata_decisions.confirm(self.db,kind='primary',selection=choice,token=preview['token'],request_id='fixture-primary')

    def preview(self,changes):
        return metadata_edits.preview_catalog(self.db,photo_id=self.pid,capture_id=self.capture,
            changes=changes,destination_root=self.root/'dest')

    def prepare(self,changes):
        preview=self.preview(changes)
        run,_=ns_db.create_run(self.c,mode='METADATA',source=str(self.root/'source'),destination=str(self.root/'dest'),submitted=preview)
        return metadata_save.prepare(self.c,run_id=run,preview=preview,db_path=self.db,
            backups_dir=self.root/'backups',base_dir=self.root/'base',cache_root=self.root/'cache')

    def execute(self,op):
        result=metadata_save.execute(self.c,op)
        self.assertEqual(result['outcome'],'completed',result)
        return result

    def current(self):
        row=self.c.execute('SELECT sha1_hash,dest_path,metadata_json,file_size,file_mtime FROM photos WHERE id=?',(self.pid,)).fetchone()
        return row[:2]+(json.loads(row[2]),)+row[3:]

    def test_save_updates_content_history_cache_and_keeps_source(self):
        self.setup_catalog()
        phash=self.c.execute('SELECT phash FROM photos').fetchone()[0]
        op=self.prepare({'orientation':6,'title':'Fixture edit'})
        self.execute(op)
        sha,path,metadata,size,mtime=self.current()
        self.assertNotEqual(sha,self.sha)
        self.assertEqual(hashlib.sha1(Path(path).read_bytes()).hexdigest(),sha)
        self.assertEqual(self.photo.read_bytes(),self.original)
        self.assertEqual(size,Path(path).stat().st_size)
        self.assertEqual(self.c.execute('SELECT phash FROM photos').fetchone()[0],phash)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM file_changes').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT sha1_hash FROM source_snapshots').fetchone()[0],self.sha)
        self.assertEqual(self.c.execute('SELECT width,height FROM contents WHERE digest=?',(sha,)).fetchone(),(32,48))
        measures={}
        fileinfo.compute_phash(path, measures=measures)
        self.assertEqual(self.c.execute('SELECT mean_brightness,mean_gradient FROM contents WHERE digest=?',(sha,)).fetchone(),
                         (measures['mean_brightness'],measures['mean_gradient']))
        self.assertTrue(thumbnails.thumbnail_cache_path(self.root/'cache',sha).exists())
        self.assertEqual(thumbnails.preview_for_photo(self.db,self.root/'cache',self.pid)['availability'],'present')
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'already_finished')

    def patterned_photo(self):
        # Preserve the fixture's metadata while making rotations visibly different.
        with Image.open(self.photo) as original:
            exif, xmp = original.getexif(), original.info.get('xmp', b'')
        image = Image.new('RGB', (300, 200), (30, 60, 90))
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 140, 90), fill=(240, 220, 40))
        draw.ellipse((180, 110, 280, 190), fill=(200, 30, 30))
        draw.line((0, 199, 299, 120), fill='white', width=9)
        image.save(self.photo, quality=92, exif=exif, xmp=xmp)

    def assert_saved_hash(self, op):
        sha, path, *_ = self.current()
        measures={}
        actual = fileinfo.compute_phash(path, measures=measures)
        self.assertEqual(self.c.execute(
            "SELECT mean_brightness,mean_gradient FROM contents WHERE digest=?",(sha,)).fetchone(),
            (measures["mean_brightness"],measures["mean_gradient"]))
        self.assertTrue(ns_similarity.usable(actual))
        self.assertEqual(self.c.execute('SELECT phash FROM photos WHERE id=?', (self.pid,)).fetchone()[0], actual)
        self.assertEqual(self.c.execute('SELECT phash,phash_state FROM contents WHERE digest=?', (sha,)).fetchone(), (actual, 'ok'))
        self.assertEqual(metadata_save._event(self.c, op, 'metadata_saved')['phash'], actual)
        self.assertEqual(self.photo.read_bytes(), self.original)
        return actual

    def test_orientation_save_rehashes_photo_content_and_history(self):
        self.patterned_photo(); self.setup_catalog()
        before = fileinfo.compute_phash(str(self.dest))
        ns_similarity_cache.refresh(self.c)
        self.assertEqual(self.c.execute('SELECT dirty FROM similarity_count_state').fetchone()[0], 0)
        op = self.prepare({'orientation': 6})
        self.execute(op)
        after = self.assert_saved_hash(op)
        self.assertNotEqual(after, before)
        self.assertEqual(self.c.execute('SELECT phash FROM contents WHERE digest=?', (self.sha,)).fetchone()[0], before)
        self.assertEqual(self.c.execute('SELECT dirty FROM similarity_count_state').fetchone()[0], 1)
        self.assertEqual(ns_similarity_cache.live_comparison_state(self.c), {'unavailable': 0, 'pending': 1})
        self.run_engine('--force-rehash')
        self.assertEqual(self.assert_saved_hash(op), after)

    def test_interrupted_orientation_save_rehashes_on_retry_without_rewriting(self):
        self.patterned_photo(); self.setup_catalog()
        before = fileinfo.compute_phash(str(self.dest))
        op = self.prepare({'orientation': 6})
        with mock.patch.object(metadata_photo_save, '_record_saved', side_effect=SystemExit('fixture interruption')):
            with self.assertRaises(SystemExit): metadata_save.execute(self.c, op)
        edited = self.dest.read_bytes()
        self.assertNotEqual(fileinfo.compute_phash(str(self.dest)), before)
        with mock.patch.object(metadata_photo_save.metadata_embedded, 'stage', side_effect=AssertionError('must not rewrite')):
            self.execute(op)
        self.assertNotEqual(self.assert_saved_hash(op), before)
        self.assertEqual(self.dest.read_bytes(), edited)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM file_changes').fetchone()[0], 1)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'already_finished')

    def test_embedded_date_edits_rehash_without_changing_visual_identity(self):
        self.patterned_photo(); self.setup_catalog(primary='embedded_xmp')
        before = fileinfo.compute_phash(str(self.dest))
        op = self.prepare({'date_taken': '2015-06-07T01:02:03'})
        with mock.patch.object(fileinfo, 'compute_phash', wraps=fileinfo.compute_phash) as hashing:
            self.execute(op)
        self.assertIn(mock.call(str(self.dest), measures=mock.ANY), hashing.call_args_list)
        self.assertNotEqual(self.current()[0], self.sha)
        self.assertEqual(self.assert_saved_hash(op), before)

    def test_hash_failure_never_reuses_old_visual_identity(self):
        self.patterned_photo(); self.setup_catalog()
        op = self.prepare({'orientation': 6})
        with mock.patch.object(fileinfo, 'compute_phash', return_value='error'):
            self.execute(op)
        sha = self.current()[0]
        self.assertEqual(self.c.execute('SELECT phash FROM photos WHERE id=?', (self.pid,)).fetchone()[0], 'error')
        self.assertEqual(self.c.execute('SELECT phash_state FROM contents WHERE digest=?', (sha,)).fetchone()[0], 'error')
        self.assertEqual(ns_similarity_cache.live_comparison_state(self.c), {'unavailable': 1, 'pending': 0})
        self.assertEqual(self.photo.read_bytes(), self.original)

    def test_cli_apply_and_retry_finish_new_hash_comparisons(self):
        self.patterned_photo(); self.setup_catalog()
        args = [sys.executable, '-m', 'engine', '--base', str(self.root/'base'),
                '--dest', str(self.root/'dest'), '--cache', str(self.root/'cache'),
                '--backups', str(self.root/'backups')]
        edit = {'photo_id': self.pid, 'capture_id': self.capture, 'changes': {'orientation': 6}}
        edit['token'] = metadata_command.previews(self.db, self.root/'dest', {'edits': [edit]})['previews'][0]['token']
        for action in ('apply', 'retry'):
            with self.subTest(action=action):
                if action == 'apply':
                    request = {'edits': [edit]}
                else:
                    op = self.prepare({'orientation': 8})
                    with mock.patch.object(metadata_photo_save, '_record_saved', side_effect=SystemExit('fixture interruption')):
                        with self.assertRaises(SystemExit): metadata_save.execute(self.c, op)
                    request = {'operation_ids': [op]}
                result = subprocess.run(args + ['--metadata', action, '--request-id', 'hash-' + action], input=json.dumps(request),
                                        text=True, capture_output=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                outcome = json.loads(result.stdout)['outcomes'][0]
                self.assertEqual(outcome['outcome'], 'completed', outcome)
                actual = self.assert_saved_hash(outcome['operation_id'])
                self.assertIsNotNone(self.c.execute('SELECT 1 FROM similarity_hashes WHERE phash=?', (actual,)).fetchone())
                self.assertEqual(ns_similarity_cache.live_comparison_state(self.c), {'unavailable': 0, 'pending': 0})
                self.assertEqual(self.c.execute('SELECT dirty FROM similarity_count_state').fetchone()[0], 0)

    def test_matching_failure_is_retryable_and_known_hash_needs_no_comparison(self):
        self.patterned_photo(); self.setup_catalog()
        op = self.prepare({'orientation': 6}); self.execute(op)
        with mock.patch.object(ns_similarity, 'refresh', side_effect=OSError('fixture comparison failure')) as refresh:
            metadata_command._refresh_matching(self.c, [(op, self.pid), (op, self.pid)])
        refresh.assert_called_once()
        self.assert_saved_hash(op)
        self.assertEqual(ns_similarity_cache.live_comparison_state(self.c)['pending'], 1)
        with mock.patch.object(ns_similarity, 'refresh', wraps=ns_similarity.refresh) as refresh:
            metadata_command._refresh_matching(self.c, [(op, self.pid), (op, self.pid)])
        refresh.assert_called_once()
        self.assertEqual(ns_similarity_cache.live_comparison_state(self.c)['pending'], 0)
        date_op = self.prepare({'date_taken': '2015-06-07T01:02:03'}); self.execute(date_op)
        with mock.patch.object(ns_similarity, 'refresh') as refresh:
            metadata_command._refresh_matching(self.c, [(date_op, self.pid)])
        refresh.assert_not_called()
        self.assertEqual(self.assert_saved_hash(date_op), self.assert_saved_hash(op))

    def test_two_edits_and_force_index_preserve_retained_identity(self):
        self.setup_catalog()
        self.execute(self.prepare({'title':'First'}))
        self.assertEqual(self.preview({'title':'Second'})['before']['proposed_effective']['title'],{'x-default':'First'})
        self.execute(self.prepare({'title':'Second'}))
        before=self.current()
        self.run_engine('--force-rehash')
        self.assertEqual(self.current(),before)
        self.capture=self.c.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        self.assertEqual(self.preview({'title':'Third'})['before']['proposed_effective']['title'],{'x-default':'Second'})
        captured=self.c.execute('SELECT catalog_sha1 FROM metadata_captures ORDER BY capture_id DESC LIMIT 1').fetchone()[0]
        self.assertEqual(captured,self.sha)
        self.assertTrue(all(path!=str(self.photo) for path,*_ in thumbnails.catalogued_copies(self.c,before[0])))

    def test_date_change_refiles_and_keeps_recorded_offset(self):
        self.setup_catalog()
        self.execute(self.prepare({'date_taken':'2015-06-07T00:01:02+14:00'}))
        sha,path,metadata,*_=self.current()
        self.assertIn('/2015/06/07/',path)
        self.assertFalse(self.dest.exists())
        self.assertEqual(metadata['date_taken'],'2015-06-07T00:01:02+14:00')
        self.assertEqual(self.photo.read_bytes(),self.original)
        self.assertEqual(self.preview({'orientation':8})['filing']['current'],Path(path).relative_to(self.root/'dest').as_posix())

    def test_embedded_xmp_clear_date_refiles_to_undated_without_fallback(self):
        self.setup_catalog(primary='embedded_xmp')
        self.execute(self.prepare({'date_taken':'','keywords':['one','two']}))
        self.assertIn('/Undated/',self.current()[1])
        self.assertEqual(self.preview({'title':'Next'})['before']['proposed_effective']['date_taken'],'')

    def test_existing_inactive_sidecar_travels_unchanged(self):
        self.setup_catalog(sidecar=True)
        original=Path(str(self.dest)+'.xmp').read_bytes()
        self.execute(self.prepare({'date_taken':'2015-06-07T01:02:03'}))
        self.assertEqual(Path(self.current()[1]+'.xmp').read_bytes(),original)
        self.assertFalse(Path(str(self.dest)+'.xmp').exists())

    def test_noop_has_no_content_change_and_keeps_original_inode(self):
        self.setup_catalog()
        before=self.dest.stat()
        op=self.prepare({'date_taken':'1999-01-02T03:04:05'})
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'no_change')
        self.assertEqual(self.dest.stat().st_ino,before.st_ino)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM file_changes').fetchone()[0],0)

    def test_interrupt_after_old_retirement_retries_without_rewriting(self):
        self.setup_catalog();op=self.prepare({'title':'Next'})
        rename=relocate._rename_noreplace
        def fail_new(old,new):
            if old.endswith('.new.jpg'):raise SystemExit('fixture interruption')
            return rename(old,new)
        with mock.patch.object(relocate,'_rename_noreplace',side_effect=fail_new):
            with self.assertRaises(SystemExit):metadata_save.execute(self.c,op)
        m=metadata_save._manifest(self.c,op)[3]
        self.assertEqual(Path(m['previous']).read_bytes(),self.original)
        self.assertFalse(self.dest.exists())
        self.execute(op)
        self.assertFalse(Path(m['previous']).exists())

    def test_interrupt_after_publication_finishes_catalog_once(self):
        self.setup_catalog();op=self.prepare({'title':'Next'})
        with mock.patch.object(metadata_photo_save,'_record_saved',side_effect=SystemExit('fixture crash')):
            with self.assertRaises(SystemExit):metadata_save.execute(self.c,op)
        self.assertNotEqual(self.dest.read_bytes(),self.original)
        self.assertEqual(self.current()[0],self.sha)
        result=metadata_save.check(self.c,op,destination_root=self.root/'dest')
        self.assertFalse(result['resolved'])
        self.execute(op)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM file_changes').fetchone()[0],1)

    def test_failed_refile_saves_metadata_then_retry_only_moves(self):
        self.setup_catalog();op=self.prepare({'date_taken':'2015-06-07T01:02:03'})
        with mock.patch.object(metadata_photo_save,'_refile',side_effect=OSError(5,'fixture move failed')):
            result=metadata_save.execute(self.c,op)
        self.assertTrue(result['metadata_saved'])
        edited=self.dest.read_bytes()
        with mock.patch.object(metadata_photo_save.metadata_embedded,'stage',side_effect=AssertionError('must not rewrite')):
            self.execute(op)
        self.assertEqual(Path(self.current()[1]).read_bytes(),edited)

    def test_unexpected_live_file_is_never_overwritten(self):
        self.setup_catalog();op=self.prepare({'title':'Next'})
        self.dest.write_bytes(b'external file')
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'failed')
        self.assertEqual(self.dest.read_bytes(),b'external file')
        self.assertEqual(self.current()[0],self.sha)

    def test_failed_verification_keeps_recovery_original_and_catalog(self):
        self.setup_catalog();op=self.prepare({'title':'Next'})
        with mock.patch.object(metadata_photo_save,'_verify',side_effect=ValueError('fixture verification failure')):
            result=metadata_save.execute(self.c,op)
        self.assertFalse(result['metadata_saved'])
        m=metadata_save._manifest(self.c,op)[3]
        self.assertEqual(Path(m['previous']).read_bytes(),self.original)
        self.assertEqual(self.current()[0],self.sha)
        self.execute(op)

    def test_discard_only_before_publication(self):
        self.setup_catalog();op=self.prepare({'title':'Next'})
        self.assertEqual(metadata_save.abandon(self.c,op)['outcome'],'abandoned')
        self.assertEqual(self.dest.read_bytes(),self.original)
        op=self.prepare({'title':'Next'})
        with mock.patch.object(metadata_photo_save,'_record_saved',side_effect=SystemExit):
            with self.assertRaises(SystemExit):metadata_save.execute(self.c,op)
        with self.assertRaises(ValueError):metadata_save.abandon(self.c,op)

    def test_index_during_unfinished_edit_preserves_retry_binding(self):
        self.setup_catalog();op=self.prepare({'title':'Next'})
        with mock.patch.object(metadata_photo_save,'_record_saved',side_effect=SystemExit):
            with self.assertRaises(SystemExit):metadata_save.execute(self.c,op)
        before=self.current()
        self.run_engine('--force-rehash')
        self.assertEqual(self.current(),before)
        self.execute(op)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM file_changes').fetchone()[0],1)

    def test_index_after_saved_edit_before_refile_preserves_retry(self):
        self.setup_catalog();op=self.prepare({'date_taken':'2015-06-07T01:02:03'})
        with mock.patch.object(metadata_photo_save,'_refile',side_effect=OSError(5,'fixture failure')):
            self.assertTrue(metadata_save.execute(self.c,op)['metadata_saved'])
        before=self.current()
        self.run_engine('--force-rehash')
        self.assertEqual(self.current(),before)
        self.execute(op)
        self.assertIn('/2015/06/07/',self.current()[1])

    def test_duplicate_source_is_detached_held_and_can_organize_separately(self):
        self.setup_catalog()
        duplicate=self.photo.with_name('duplicate.jpg');duplicate.write_bytes(self.original)
        self.run_engine('--copy')
        self.capture=self.c.execute('SELECT MAX(capture_id) FROM metadata_captures WHERE file_id=(SELECT file_id FROM photo_files WHERE photo_id=?)',(self.pid,)).fetchone()[0]
        alias=self.c.execute('SELECT id FROM photos WHERE source_path=?',(str(duplicate),)).fetchone()[0]
        self.assertEqual(self.c.execute('SELECT status FROM photos WHERE id=?',(alias,)).fetchone()[0],'Duplicate')
        self.execute(self.prepare({'title':'Edited original'}))
        edited=self.current()
        self.assertEqual(self.c.execute('SELECT status,dest_path FROM photos WHERE id=?',(alias,)).fetchone(),('Pending',None))
        # The released copy is an earlier version: held until answered, then its own photo.
        self.run_engine('--copy')
        self.assertEqual(self.c.execute('SELECT status FROM photos WHERE id=?',(alias,)).fetchone()[0],'Pending')
        self.c.execute("UPDATE photo_versions SET answer='keep_separate' WHERE photo_id=?",(alias,));self.c.commit()
        self.run_engine('--copy')
        self.assertEqual(self.current(),edited)
        other=self.c.execute('SELECT status,dest_path,sha1_hash FROM photos WHERE id=?',(alias,)).fetchone()
        self.assertEqual(other[0],'Copied')
        self.assertNotEqual(other[1],edited[1]);self.assertEqual(other[2],self.sha)
        self.assertEqual(Path(other[1]).read_bytes(),self.original)

    def test_new_duplicate_during_interruption_does_not_keep_old_content_pointer(self):
        self.setup_catalog();op=self.prepare({'title':'Next'})
        with mock.patch.object(metadata_photo_save,'_record_saved',side_effect=SystemExit):
            with self.assertRaises(SystemExit):metadata_save.execute(self.c,op)
        duplicate=self.photo.with_name('duplicate.jpg');duplicate.write_bytes(self.original)
        self.run_engine('--force-rehash')
        self.execute(op)
        row=self.c.execute('SELECT status,dest_path FROM photos WHERE source_path=?',(str(duplicate),)).fetchone()
        self.assertEqual(row,('Pending',None))

    def test_exact_result_duplicate_requires_confirmation_and_preserves_originals(self):
        self.setup_catalog()
        from engine import metadata_embedded
        other=self.root/'dest/library/equal.jpg'
        metadata_embedded.stage(self.root/'dest',self.dest.relative_to(self.root/'dest').as_posix(),
            'library/equal.jpg',expected_sha1=self.sha,kind='embedded_exif',changes={'title':'Same'})
        digest=hashlib.sha1(other.read_bytes()).hexdigest()
        self.c.execute("INSERT INTO photos(source_path,dest_path,sha1_hash,status) VALUES(?,?,?,'Copied')",('generated-other',str(other),digest))
        self.c.commit()
        result=metadata_save.execute(self.c,self.prepare({'title':'Same'}))
        self.assertEqual(result['outcome'],'failed',result)
        self.assertIn('Preview and confirm',result['error'])
        self.assertEqual(self.dest.read_bytes(),self.original)
        self.assertEqual(hashlib.sha1(other.read_bytes()).hexdigest(),digest)
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_reject_return_and_index_keep_edited_bytes(self):
        self.setup_catalog();self.execute(self.prepare({'title':'Next'}))
        digest=self.current()[0]
        for kind in ('reject','return'):
            run=ns_db.create_run(self.c,mode=kind.upper(),source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
            runtime.run_progress.bind(str(self.db),run)
            relocate.relocate_in_destination(self.db,self.root/'dest',self.root/'backups',self.root/'base',run,
                SimpleNamespace(source=str(self.root/'source'),source_subdir=None,file_ids=None),kind=='return')
            self.run_engine('--force-rehash')
            self.assertEqual(self.current()[0],digest)
            path=Path(self.current()[1])
            self.assertTrue(path.is_relative_to(self.root/'dest'/('rejects' if kind=='reject' else 'library')))
            self.assertEqual(hashlib.sha1(path.read_bytes()).hexdigest(),digest)

    def test_date_directory_barrier_failure_retains_recovery_and_retries(self):
        self.setup_catalog();op=self.prepare({'date_taken':'2015-06-07T01:02:03'})
        sync=durable._fsync_directory
        library=self.root/'dest/library'
        def fail_new_year(path):
            if Path(path)==library and (library/'2015').exists():
                raise OSError(5,'fixture ancestor barrier failure')
            return sync(path)
        with mock.patch.object(durable,'_fsync_directory',side_effect=fail_new_year):
            result=metadata_save.execute(self.c,op)
        self.assertTrue(result['metadata_saved'])
        self.assertEqual(result['outcome'],'failed')
        m=metadata_save._manifest(self.c,op)[3]
        self.assertEqual(Path(m['previous']).read_bytes(),self.original)
        with mock.patch.object(durable,'_fsync_directory',wraps=sync) as barrier:
            self.execute(op)
        self.assertIn(library,[Path(call.args[0]) for call in barrier.call_args_list])
        self.assertFalse(Path(m['previous']).exists())

    def test_saved_check_detects_missing_or_changed_published_photo(self):
        self.setup_catalog();op=self.prepare({'title':'Next'})
        with mock.patch.object(metadata_photo_save,'_cleanup',side_effect=OSError(5,'fixture cleanup failure')):
            self.assertTrue(metadata_save.execute(self.c,op)['metadata_saved'])
        self.dest.write_bytes(b'externally changed')
        result=metadata_save.check(self.c,op,destination_root=self.root/'dest')
        self.assertFalse(result['resolved'])
        self.assertIn('missing or changed',result['message'])
        self.assertEqual(self.dest.read_bytes(),b'externally changed')

    def test_cli_preview_apply_request_replay_and_move_preserves_source(self):
        self.setup_catalog()
        args=[sys.executable,'-m','engine','--base',str(self.root/'base'),'--dest',str(self.root/'dest'),
              '--cache',str(self.root/'cache'),'--backups',str(self.root/'backups')]
        edit={'photo_id':self.pid,'capture_id':self.capture,'changes':{'title':'Via CLI'}}
        preview=subprocess.run(args+['--metadata','preview'],input=json.dumps({'edits':[edit]}),text=True,capture_output=True)
        self.assertEqual(preview.returncode,0,preview.stderr)
        edit['token']=json.loads(preview.stdout)['previews'][0]['token']
        apply_args=args+['--metadata','apply','--request-id','fixture-edit']
        result=subprocess.run(apply_args,input=json.dumps({'edits':[edit]}),text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertEqual(json.loads(result.stdout)['outcomes'][0]['outcome'],'completed')
        replay=subprocess.run(apply_args,input=json.dumps({'edits':[edit]}),text=True,capture_output=True)
        self.assertEqual(replay.returncode,constants.EXIT_REQUEST_ALREADY_ACCEPTED)
        edited=self.current()
        self.run_engine('--move')
        self.assertEqual(self.photo.read_bytes(),self.original)
        self.assertEqual(self.current(),edited)


    def test_saved_suspicious_date_is_confirmed_only_after_verified_save(self):
        self.setup_catalog()
        op = self.prepare({'date_taken':'2399-06-07T12:34:56'})
        self.assertFalse(review.details(self.c, self.pid)['date_confirmed'])
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        detail = review.details(self.c, self.pid)
        self.assertTrue(detail['date_confirmed'])
        self.assertIsNotNone(detail['date_warning'])
        self.assertNotIn('date', [r['reason'] for r in detail['reasons']])
        self.assertEqual(detail['history'][0]['action'], 'date_saved')
        self.assertEqual(detail['history'][0]['date_taken'], '2399-06-07T12:34:56')
        self.assertGreater(detail['history'][0]['run_id'], 0)
        metadata_save.execute(self.c, op)
        self.assertEqual(len(review.details(self.c, self.pid)['history']), len(detail['history']))
        self.run_engine('--force-rehash')
        self.assertTrue(review.details(self.c, self.pid)['date_confirmed'])
        self.assertEqual(len(review.details(self.c, self.pid)['history']), len(detail['history']))


    def test_interrupted_date_save_confirms_only_when_recorded_on_retry(self):
        self.setup_catalog()
        op = self.prepare({'date_taken':'2398-06-07T12:34:56'})
        with mock.patch.object(metadata_photo_save, '_record_saved', side_effect=SystemExit('fixture interruption')):
            with self.assertRaises(SystemExit):
                metadata_save.execute(self.c, op)
        self.assertFalse(review.details(self.c, self.pid)['date_confirmed'])
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        detail = review.details(self.c, self.pid)
        self.assertTrue(detail['date_confirmed'])
        self.assertEqual([e['action'] for e in detail['history']], ['date_saved'])
        metadata_save.execute(self.c, op)
        self.assertEqual(review.details(self.c, self.pid)['history'], detail['history'])


if __name__=='__main__':unittest.main()
