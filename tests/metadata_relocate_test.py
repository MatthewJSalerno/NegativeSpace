"""Generated photo/XMP relocation and interruption checks; run in Docker."""
import errno
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import metadata_transfer_test
from engine import attention, durable, metadata_relocate, ns_db, reconcile, relocate, runtime
from engine.ns_db import PhotoStatus, RunStatus


class Relocations(unittest.TestCase):
    setUp = metadata_transfer_test.Pairs.setUp
    run_engine = metadata_transfer_test.Pairs.run_engine
    conn = metadata_transfer_test.Pairs.conn
    index = metadata_transfer_test.Pairs.index
    run_id = metadata_transfer_test.Pairs.run_id
    prepare = metadata_transfer_test.Pairs.prepare
    result = metadata_transfer_test.Pairs.result

    def deliver(self):
        self.index()
        self.result(self.prepare())
        self.db = next((self.root/'base/db').glob('*.db'))
        self.old = self.dest
        self.new = self.dest.with_name('renamed.jpg')
        self.photo_bytes = self.photo.read_bytes()
        self.xmp_bytes = self.sidecar.read_bytes()
        runtime.cancel_requested.clear()

    def invoke(self, kind='rename', name='renamed'):
        run = ns_db.create_run(self.c, mode=kind.upper(), source=str(self.root/'source'),
                               destination=str(self.root/'dest'))[0]
        runtime.run_progress.bind(str(self.db), run)
        args = (self.db, self.root/'dest', self.root/'backups', self.root/'base', run)
        if kind == 'rename':
            return relocate.rename_delivered_file(*args, self.pid, name)
        return relocate.relocate_in_destination(*args, SimpleNamespace(
            source=str(self.root/'source'), source_subdir=None, file_ids=None), kind=='return')

    def location(self):
        return Path(self.c.execute('SELECT dest_path FROM photos WHERE id=?',(self.pid,)).fetchone()[0])

    def pair(self, path):
        self.assertEqual(path.read_bytes(), self.photo_bytes)
        self.assertEqual(Path(str(path)+'.xmp').read_bytes(), self.xmp_bytes)

    def last_op(self):
        return self.c.execute("SELECT MAX(o.id) FROM operations o JOIN operation_events e ON e.operation_id=o.id "
            "WHERE e.step='intent' AND json_type(e.detail_json,'$.expected.sidecar')='object'").fetchone()[0]

    def recovery(self):
        reconcile.reconcile_interrupted_state(self.db, self.run_id())

    def test_rename_reject_return_preserve_both_files_identity_and_sources(self):
        self.deliver()
        inode=self.old.stat().st_ino
        with mock.patch.object(durable, '_stage_copy', side_effect=AssertionError('unnecessary copy')):
            for kind in ('rename','reject','return'):
                before=self.location()
                self.assertEqual(self.invoke(kind), RunStatus.COMPLETED)
                after=self.location()
                self.assertNotEqual(before, after)
                self.pair(after)
                self.assertFalse(before.exists())
                self.assertFalse(Path(str(before)+'.xmp').exists())
                self.assertEqual(after.stat().st_ino, inode)
        self.assertEqual(self.c.execute('SELECT status FROM photos WHERE id=?',(self.pid,)).fetchone()[0], PhotoStatus.COPIED)
        self.assertEqual(self.photo.read_bytes(), self.photo_bytes)
        self.assertEqual(self.sidecar.read_bytes(), self.xmp_bytes)

    def test_photo_collision_suffixes_both_names(self):
        self.deliver(); self.new.write_bytes(b'occupied')
        self.assertEqual(self.invoke(), RunStatus.COMPLETED)
        self.assertEqual(self.new.read_bytes(), b'occupied')
        self.assertEqual(self.location().name, 'renamed_1.jpg')
        self.pair(self.location())

    def test_orphan_xmp_is_not_overwritten_or_suffixed_around(self):
        self.deliver(); Path(str(self.new)+'.xmp').write_bytes(b'occupied')
        self.assertEqual(self.invoke(), RunStatus.FAILED)
        self.pair(self.old); self.assertFalse(self.new.exists())
        self.assertEqual(Path(str(self.new)+'.xmp').read_bytes(), b'occupied')

    def test_missing_registered_sidecar_refuses_photo_only_move(self):
        self.deliver(); Path(str(self.old)+'.xmp').unlink()
        self.assertEqual(self.invoke(), RunStatus.FAILED)
        self.assertTrue(self.old.exists()); self.assertFalse(self.new.exists())

    def fail_second(self, crash=False):
        actual=metadata_relocate._publish
        def publish(old,new,digest,is_xmp,**kwargs):
            if not is_xmp:
                raise SystemExit('generated crash') if crash else OSError('generated disk failure')
            return actual(old,new,digest,is_xmp,**kwargs)
        with mock.patch.object(metadata_relocate,'_publish',side_effect=publish):
            if crash:
                with self.assertRaises(SystemExit): self.invoke()
            else:
                self.assertEqual(self.invoke(), RunStatus.FAILED)

    def test_partial_publication_retry_reuses_names_and_resolves_issue(self):
        self.deliver(); self.fail_second()
        self.pair(self.old); self.assertFalse(self.new.exists())
        self.assertTrue(Path(str(self.new)+'.xmp').exists())
        self.assertEqual(self.location(), self.old)
        self.recovery()
        self.assertEqual(self.location(), self.old)
        self.assertEqual(self.invoke(), RunStatus.COMPLETED)
        self.assertEqual(self.location(), self.new); self.pair(self.new)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM attention_issues WHERE resolved_at IS NULL').fetchone()[0],0)
        self.assertFalse(self.new.with_name('renamed_1.jpg').exists())

    def test_crash_after_one_publication_never_recovers_photo_only(self):
        self.deliver(); self.fail_second(crash=True); self.recovery()
        self.pair(self.old); self.assertEqual(self.location(), self.old)
        self.assertEqual(self.invoke(), RunStatus.COMPLETED)
        self.pair(self.new)

    def test_retry_different_name_or_action_refuses(self):
        self.deliver(); self.fail_second()
        self.assertEqual(self.invoke(name='other'), RunStatus.FAILED)
        self.invoke('reject')
        self.pair(self.old); self.assertEqual(self.location(), self.old)
        self.assertFalse((self.root/'dest/rejects').exists())

    def test_crash_before_cleanup_recovers_only_after_pair_verification(self):
        self.deliver()
        with mock.patch.object(metadata_relocate,'_cleanup',side_effect=SystemExit), self.assertRaises(SystemExit):
            self.invoke()
        self.pair(self.old); self.pair(self.new)
        self.recovery()
        self.assertFalse(self.old.exists()); self.assertFalse(Path(str(self.old)+'.xmp').exists())
        self.assertEqual(self.location(), self.new); self.pair(self.new)

    def test_check_it_now_does_not_remove_old_names(self):
        self.deliver()
        with mock.patch.object(metadata_relocate,'_cleanup',side_effect=OSError('generated cleanup failure')):
            self.assertEqual(self.invoke(), RunStatus.FAILED)
        issue=self.c.execute('SELECT issue_id FROM attention_issues WHERE resolved_at IS NULL').fetchone()[0]
        result=attention.check_issue(self.db,self.root/'source',self.root/'dest',self.run_id(),issue)
        self.assertFalse(result['resolved']); self.pair(self.old); self.pair(self.new)
        self.assertEqual(self.invoke(), RunStatus.COMPLETED)
        self.assertEqual(self.location(),self.new); self.assertFalse(self.old.exists())

    def test_missing_new_sidecar_never_authorizes_old_photo_cleanup(self):
        self.deliver()
        with mock.patch.object(metadata_relocate,'_cleanup',side_effect=SystemExit), self.assertRaises(SystemExit):
            self.invoke()
        Path(str(self.new)+'.xmp').unlink()
        self.recovery()
        self.pair(self.old); self.assertEqual(self.location(),self.old)
        self.assertTrue(self.c.execute('SELECT 1 FROM attention_issues WHERE resolved_at IS NULL').fetchone())

    def test_crash_between_old_name_removals_recovers_both_new_files(self):
        self.deliver()
        def cleanup(expected):
            self.old.unlink()
            raise SystemExit('generated crash')
        with mock.patch.object(metadata_relocate,'_cleanup',side_effect=cleanup), self.assertRaises(SystemExit):
            self.invoke()
        self.recovery(); self.pair(self.new)
        self.assertFalse(Path(str(self.old)+'.xmp').exists()); self.assertEqual(self.location(),self.new)

    def test_hardlink_unsupported_falls_back_to_verified_copy(self):
        self.deliver()
        with mock.patch.object(metadata_relocate.os,'link',side_effect=OSError(errno.EXDEV,'generated cross-device')):
            self.assertEqual(self.invoke(),RunStatus.COMPLETED)
        self.pair(self.new); self.assertFalse(self.old.exists())

    def test_new_xmp_sync_failure_keeps_original_pair(self):
        self.deliver(); actual=durable._fsync_file
        def sync(path):
            if str(path)==str(self.new)+'.xmp': raise OSError('generated fsync failure')
            return actual(path)
        with mock.patch.object(durable,'_fsync_file',side_effect=sync):
            self.assertEqual(self.invoke(),RunStatus.FAILED)
        self.pair(self.old); self.assertEqual(self.location(),self.old)

    def test_evidence_commit_failure_prevents_old_name_cleanup(self):
        self.deliver()
        with mock.patch.object(ns_db,'record_evidence',side_effect=RuntimeError('generated catalog failure')):
            with self.assertRaises(RuntimeError):self.invoke()
        self.pair(self.old); self.pair(self.new)
        self.assertEqual(self.location(),self.old)

    def test_direct_retry_closes_earlier_intent_before_later_reject(self):
        self.deliver(); self.fail_second()
        original=self.last_op()
        self.assertEqual(self.invoke(),RunStatus.COMPLETED)
        self.assertEqual(ns_db.unsettled_operations(self.c,self.pid),[])
        self.assertEqual(self.c.execute('SELECT status FROM operations WHERE id=?',(original,)).fetchone()[0],PhotoStatus.FAILED)
        self.assertEqual(self.invoke('reject'),RunStatus.COMPLETED)
        after=self.location(); self.recovery()
        self.assertEqual(self.location(),after); self.pair(after)
        self.assertEqual(self.c.execute('SELECT status FROM photos WHERE id=?',(self.pid,)).fetchone()[0],PhotoStatus.REJECTED_COPIED)

    def test_old_directory_sync_is_retried_after_both_unlinks(self):
        self.deliver(); actual=durable._fsync_directory
        self.new=self.root/'dest/rejects'/self.old.relative_to(self.root/'dest/library')
        def sync(path):
            if path==self.old.parent and not Path(str(self.old)+'.xmp').exists():
                raise OSError('generated old directory sync failure')
            return actual(path)
        with mock.patch.object(durable,'_fsync_directory',side_effect=sync):
            self.assertEqual(self.invoke('reject'),RunStatus.FAILED)
            self.recovery()
        self.assertEqual(self.location(),self.old)
        issue=self.c.execute('SELECT issue_id FROM attention_issues WHERE resolved_at IS NULL').fetchone()[0]
        result=attention.check_issue(self.db,self.root/'source',self.root/'dest',self.run_id(),issue)
        self.assertTrue(result['resolved'],result); self.pair(self.new)
        self.assertEqual(self.location(),self.new)

    def test_readonly_check_preserves_failed_outcome_when_pair_is_complete(self):
        self.deliver(); actual=metadata_relocate._cleanup
        def cleanup(expected):
            actual(expected)
            raise OSError('generated failure after cleanup')
        with mock.patch.object(metadata_relocate,'_cleanup',side_effect=cleanup):
            self.assertEqual(self.invoke(),RunStatus.FAILED)
        original=self.last_op()
        issue=self.c.execute('SELECT issue_id FROM attention_issues WHERE resolved_at IS NULL').fetchone()[0]
        result=attention.check_issue(self.db,self.root/'source',self.root/'dest',self.run_id(),issue)
        self.assertTrue(result['resolved'],result)
        self.assertEqual(self.c.execute('SELECT status FROM operations WHERE id=?',(original,)).fetchone()[0],PhotoStatus.FAILED)
        self.assertEqual(ns_db.unsettled_operations(self.c,self.pid),[])
        self.assertEqual(self.location(),self.new)

    def test_cancelled_check_keeps_issue_and_paths(self):
        self.deliver(); self.fail_second()
        issue=self.c.execute('SELECT issue_id FROM attention_issues WHERE resolved_at IS NULL').fetchone()[0]
        runtime.cancel_requested.set()
        try:
            result=attention.check_issue(self.db,self.root/'source',self.root/'dest',self.run_id(),issue)
        finally:
            runtime.cancel_requested.clear()
        self.assertFalse(result['resolved']); self.assertIn('cancel',result['message'])
        self.pair(self.old); self.assertEqual(self.location(),self.old)

    def test_unrecorded_sidecar_ownership_is_refused(self):
        original_xmp=self.sidecar.read_bytes(); self.sidecar.unlink()
        self.index(); self.run_engine('--copy')
        self.db=next((self.root/'base/db').glob('*.db'))
        old=self.location(); Path(str(old)+'.xmp').write_bytes(original_xmp)
        before=old.read_bytes()
        self.assertEqual(self.invoke(),RunStatus.FAILED)
        self.assertEqual(old.read_bytes(),before)
        self.assertEqual(Path(str(old)+'.xmp').read_bytes(),original_xmp)
        self.assertFalse(old.with_name('renamed.jpg').exists())

    def test_check_retries_old_directory_barrier_across_reject_folders(self):
        self.deliver(); actual=metadata_relocate._cleanup
        def cleanup(expected):
            actual(expected)
            raise OSError('generated failure after cleanup')
        with mock.patch.object(metadata_relocate,'_cleanup',side_effect=cleanup):
            self.assertEqual(self.invoke('reject'),RunStatus.FAILED)
        issue=self.c.execute('SELECT issue_id FROM attention_issues WHERE resolved_at IS NULL').fetchone()[0]
        actual_sync=durable._fsync_directory
        def sync(path):
            if path==self.old.parent: raise OSError('generated old parent sync failure')
            return actual_sync(path)
        with mock.patch.object(durable,'_fsync_directory',side_effect=sync):
            result=attention.check_issue(self.db,self.root/'source',self.root/'dest',self.run_id(),issue)
        self.assertFalse(result['resolved']); self.assertEqual(self.location(),self.old)
        result=attention.check_issue(self.db,self.root/'source',self.root/'dest',self.run_id(),issue)
        self.assertTrue(result['resolved']); self.pair(self.location())

    def test_stale_photo_does_not_repair_current_catalog(self):
        self.deliver(); self.fail_second()
        with ns_db.transaction(self.c):
            self.c.execute('UPDATE photos SET sha1_hash=? WHERE id=?',('changed',self.pid))
        self.recovery()
        self.pair(self.old); self.assertEqual(self.location(),self.old)
        self.assertEqual(self.c.execute('SELECT sha1_hash FROM photos WHERE id=?',(self.pid,)).fetchone()[0],'changed')

    def test_symlinked_sidecar_is_never_followed(self):
        self.deliver(); side=Path(str(self.old)+'.xmp'); side.unlink(); side.symlink_to(self.sidecar)
        self.assertEqual(self.invoke(),RunStatus.FAILED)
        self.assertFalse(self.new.exists()); self.assertTrue(side.is_symlink())
        self.assertEqual(self.sidecar.read_bytes(),self.xmp_bytes)

    def test_changed_sidecar_retains_original_locations(self):
        self.deliver(); changed=self.xmp_bytes.replace(b'2005',b'2006')
        Path(str(self.old)+'.xmp').write_bytes(changed)
        self.assertEqual(self.invoke(),RunStatus.FAILED)
        self.assertEqual(self.location(),self.old)
        self.assertEqual(Path(str(self.old)+'.xmp').read_bytes(),changed)
        self.assertFalse(self.new.exists())

    def test_reject_and_return_crashes_recover_status_with_both_files(self):
        self.deliver()
        for kind,status in (('reject',PhotoStatus.REJECTED_COPIED),('return',PhotoStatus.COPIED)):
            before=self.location()
            with mock.patch.object(metadata_relocate,'_cleanup',side_effect=SystemExit), self.assertRaises(SystemExit):
                self.invoke(kind)
            self.recovery()
            self.assertNotEqual(self.location(),before); self.pair(self.location())
            self.assertFalse(before.exists()); self.assertFalse(Path(str(before)+'.xmp').exists())
            self.assertEqual(self.c.execute('SELECT status FROM photos WHERE id=?',(self.pid,)).fetchone()[0],status)

    def test_fallback_cannot_overwrite_racing_destination(self):
        self.deliver(); actual=durable._stage_copy
        def stage(source,destination):
            partial=actual(source,destination)
            destination.write_bytes(b'new occupant')
            return partial
        with mock.patch.object(metadata_relocate.os,'link',side_effect=OSError(errno.EXDEV,'generated cross-device')), \
                mock.patch.object(durable,'_stage_copy',side_effect=stage):
            self.assertEqual(self.invoke(),RunStatus.FAILED)
        self.pair(self.old); self.assertEqual(Path(str(self.new)+'.xmp').read_bytes(),b'new occupant')
        self.assertEqual(list(self.new.parent.glob('*.partial*')),[])

    def test_same_name_is_noop(self):
        self.deliver(); before=self.c.execute('SELECT COUNT(*) FROM operations').fetchone()[0]
        self.assertEqual(self.invoke(name='photo'),RunStatus.COMPLETED)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM operations').fetchone()[0],before)
        self.pair(self.old)


if __name__ == '__main__': unittest.main()
