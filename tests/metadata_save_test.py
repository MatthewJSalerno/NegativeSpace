"""Generated catalog + actual XMP publications, with interruption/failure injection."""
import hashlib
import json
import os
import subprocess
import sys
import errno
from pathlib import Path
import unittest
import zstandard
from unittest import mock

import metadata_index_test
from engine import (constants, durable, metadata_decisions, metadata_edits, metadata_relocate, metadata_save,
                    ns_db, relocate, runtime, xmp, xmp_store)


class SavedEdits(unittest.TestCase):
    setUp = metadata_index_test.IndexTests.setUp
    run_engine = metadata_index_test.IndexTests.run_engine
    conn = metadata_index_test.IndexTests.conn

    def setup_catalog(self, *, sidecar=True):
        runtime.cancel_requested.clear()
        self.addCleanup(runtime.cancel_requested.clear)
        if not sidecar:
            self.sidecar.unlink()
        self.run_engine('--copy')
        self.c = self.conn()
        self.db = next((self.root/'base/db').glob('*.db'))
        self.pid = self.c.execute('SELECT id FROM photos').fetchone()[0]
        self.capture = self.c.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        self.dest = Path(self.c.execute('SELECT dest_path FROM photos').fetchone()[0])
        self.xdest = Path(str(self.dest)+'.xmp')
        self.photo_bytes = self.dest.read_bytes()
        self.original = self.xdest.read_bytes() if self.xdest.exists() else None
        if not sidecar:
            ns_db.save_settings(self.c, {'metadata_write_non_raw':'xmp'}, expected_revisions={'metadata_write_non_raw':0})

    def preview(self, changes):
        return metadata_edits.preview_catalog(self.db, photo_id=self.pid, capture_id=self.capture,
            changes=changes, destination_root=self.root/'dest')

    def prepare(self, changes, *, preview=None):
        preview = preview or self.preview(changes)
        self.run, _ = ns_db.create_run(self.c, mode='METADATA', source=str(self.root/'source'),
            destination=str(self.root/'dest'), submitted=preview)
        return metadata_save.prepare(self.c, run_id=self.run, preview=preview, db_path=self.db,
            backups_dir=self.root/'backups', base_dir=self.root/'base')

    def fields(self, path=None):
        packet = (path or self.xdest).read_bytes()
        return xmp.parse_bytes(packet, source_id='verify').source.fields

    def test_edit_keeps_photo_source_and_unrequested_fields_and_exact_original(self):
        self.setup_catalog()
        op = self.prepare({'title':'New title', 'keywords':['one','two']})
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        self.assertEqual(self.fields()['date_taken'], '2005-03-04T05:06:07')
        self.assertEqual(self.fields()['title'], {'x-default':'New title'})
        self.assertEqual(self.fields()['keywords'], ['one','two'])
        file_id = self.c.execute('SELECT file_id FROM photo_files WHERE photo_id=?', (self.pid,)).fetchone()[0]
        current = metadata_decisions.current(self.c, 'primary', str(file_id))
        self.assertEqual(current['value']['resolution']['proposed_effective']['title'], {'x-default':'New title'})
        self.assertEqual(self.dest.read_bytes(), self.photo_bytes)
        self.assertEqual(self.sidecar.read_bytes(), self.original)
        m = metadata_save._manifest(self.c, op)[3]
        self.assertEqual(xmp_store.original_bytes(self.c, m['old_version']), self.original)
        self.assertFalse(Path(m['previous']).exists())
        self.assertFalse(Path(m['staged']).exists())
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'already_finished')
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM operation_events WHERE operation_id=? AND step='metadata_saved'", (op,)).fetchone()[0], 1)

    def test_first_xmp_has_only_requested_fields_and_second_edit_uses_it(self):
        self.setup_catalog(sidecar=False)
        op = self.prepare({'title':'Only title'})
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        self.assertEqual(self.fields(), {'title':{'x-default':'Only title'}})
        second = self.prepare({'rating':'3'})
        self.assertEqual(metadata_save.execute(self.c, second)['outcome'], 'completed')
        self.assertEqual(self.fields(), {'title':{'x-default':'Only title'}, 'rating':'3'})
        self.assertEqual(self.dest.read_bytes(), self.photo_bytes)

    def test_same_values_write_no_versions_and_do_not_touch_file(self):
        self.setup_catalog()
        before = self.xdest.stat()
        count = self.c.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0]
        op = self.prepare({'date_taken':'2005-03-04T05:06:07'})
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'no_change')
        self.assertEqual(self.xdest.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0], count)

    def test_date_edit_moves_verified_pair_and_second_edit_preserves_current_location(self):
        self.setup_catalog()
        op = self.prepare({'date_taken':'2012-06-07T00:30:00+14:00'})
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        new = self.root/'dest/library/2012/06/07/photo.jpg'
        self.assertEqual(new.read_bytes(), self.photo_bytes)
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.xdest.exists())
        self.assertEqual(self.c.execute('SELECT dest_path FROM photos').fetchone()[0], str(new))
        self.assertEqual(metadata_relocate.current(self.c, new)['sha256'], hashlib.sha256(Path(str(new)+'.xmp').read_bytes()).hexdigest())
        self.assertEqual(self.preview({'title':'Later'})['filing']['current'], 'library/2012/06/07/photo.jpg')
        self.run_engine('--force-rehash')
        self.assertEqual(self.c.execute('SELECT dest_path FROM photos').fetchone()[0], str(new))
        self.assertEqual(json.loads(self.c.execute('SELECT metadata_json FROM photos').fetchone()[0])['date_taken'], '2012-06-07T00:30:00+14:00')

    def test_clear_date_suppresses_fallback_and_moves_to_original_year(self):
        self.setup_catalog()
        op = self.prepare({'date_taken':''})
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        new = Path(self.c.execute('SELECT dest_path FROM photos').fetchone()[0])
        self.assertIn('Undated', new.parts)
        self.assertEqual(self.fields(Path(str(new)+'.xmp'))['date_taken'], '')
        self.assertEqual(self.preview({'title':'Later'})['before']['proposed_effective']['date_taken'], '')

    def test_crash_after_publication_before_catalog_retries_once(self):
        self.setup_catalog()
        op = self.prepare({'title':'Survives'})
        with mock.patch.object(metadata_save, '_record_saved', side_effect=SystemExit('power loss')):
            with self.assertRaises(SystemExit):
                metadata_save.execute(self.c, op)
        published = self.xdest.read_bytes()
        result = metadata_save.check(self.c, op, destination_root=self.root/'dest')
        self.assertFalse(result['resolved'])
        self.assertEqual(self.xdest.read_bytes(), published)
        with self.assertRaises(ValueError):
            metadata_save.abandon(self.c, op)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        self.assertEqual(self.xdest.read_bytes(), published)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM attention_issues WHERE resolved_at IS NULL').fetchone()[0], 0)

    def test_interruption_between_old_retirement_and_new_publication(self):
        self.setup_catalog()
        op = self.prepare({'title':'Resume'})
        real = relocate._rename_noreplace
        def stop(old, new):
            if new == str(self.xdest):
                raise SystemExit('interrupted')
            return real(old, new)
        with mock.patch.object(relocate, '_rename_noreplace', side_effect=stop):
            with self.assertRaises(SystemExit):
                metadata_save.execute(self.c, op)
        self.assertFalse(self.xdest.exists())
        with self.assertRaises(ValueError):
            metadata_save.abandon(self.c, op)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        self.assertEqual(self.fields()['title'], {'x-default':'Resume'})

    def test_refile_failure_keeps_saved_metadata_then_retry_moves_only(self):
        self.setup_catalog()
        op = self.prepare({'date_taken':'2015-02-03'})
        with mock.patch.object(metadata_relocate, 'perform', side_effect=OSError('destination offline')):
            result = metadata_save.execute(self.c, op)
        self.assertTrue(result['metadata_saved'])
        self.assertEqual(self.fields()['date_taken'], '2015-02-03')
        self.assertTrue(self.dest.exists())
        with mock.patch.object(metadata_save, '_publish', side_effect=AssertionError('must not rewrite')):
            self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        self.assertTrue((self.root/'dest/library/2015/02/03/photo.jpg').exists())

    def test_partial_pair_refile_retry_preserves_both_members(self):
        self.setup_catalog()
        op = self.prepare({'date_taken':'2015-02-03'})
        real = metadata_relocate._publish
        def stop(old, new, digest, is_xmp, **kw):
            if not is_xmp:
                raise OSError('photo publication offline')
            return real(old, new, digest, is_xmp, **kw)
        with mock.patch.object(metadata_relocate, '_publish', side_effect=stop):
            self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'failed')
        self.assertTrue(self.dest.exists())
        self.assertTrue(self.xdest.exists())
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        self.assertFalse(self.dest.exists())

    def test_failed_backup_blocks_all_publication_and_can_abandon(self):
        self.setup_catalog()
        with mock.patch.object(ns_db, 'backup_catalog', return_value={'outcome':'failed'}):
            op = self.prepare({'title':'Blocked'})
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'failed')
        self.assertEqual(self.xdest.read_bytes(), self.original)
        self.assertEqual(metadata_save.abandon(self.c, op)['outcome'], 'abandoned')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM attention_issues WHERE resolved_at IS NULL').fetchone()[0], 0)

    def test_unchanged_original_after_write_failure_can_abandon_and_keeps_review_reason(self):
        self.setup_catalog()
        op = self.prepare({'title':'No space'})
        with mock.patch.object(metadata_save, '_stage', side_effect=OSError('disk full')):
            self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'failed')
        self.assertEqual(metadata_save.abandon(self.c, op)['outcome'], 'abandoned')
        self.assertEqual(self.xdest.read_bytes(), self.original)

    def test_changed_sidecar_after_preview_is_refused_without_overwrite(self):
        self.setup_catalog()
        p = self.preview({'title':'Blocked'})
        different = metadata_index_test.packet('2001')
        self.xdest.write_bytes(different)
        with self.assertRaises(ValueError):
            self.prepare({}, preview=p)
        self.assertEqual(self.xdest.read_bytes(), different)

    def test_orphan_and_symlink_paths_are_refused(self):
        self.setup_catalog(sidecar=False)
        self.xdest.write_bytes(metadata_index_test.packet())
        with self.assertRaises((ValueError,OSError)):
            self.prepare({'title':'Blocked'})
        self.xdest.unlink()
        self.xdest.symlink_to(self.sidecar)
        with self.assertRaises((ValueError,OSError)):
            self.prepare({'title':'Blocked'})

    def test_new_destination_collision_after_save_keeps_both_and_retry_does_not_rewrite(self):
        self.setup_catalog()
        op = self.prepare({'date_taken':'2015-02-03'})
        target = self.root/'dest/library/2015/02/03/photo.jpg'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'foreign occupant')
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'failed')
        self.assertEqual(target.read_bytes(), b'foreign occupant')
        self.assertEqual(self.fields()['date_taken'], '2015-02-03')
        target.unlink()
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')

    def test_frozen_settings_and_request_replay(self):
        self.setup_catalog(sidecar=False)
        p = self.preview({'title':'Frozen'})
        op = self.prepare({}, preview=p)
        ns_db.save_settings(self.c, {'metadata_write_non_raw':'embedded'}, expected_revisions={'metadata_write_non_raw':1})
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        replay = metadata_save.prepare(self.c, run_id=self.run, preview=p, db_path=self.db,
            backups_dir=self.root/'backups', base_dir=self.root/'base')
        self.assertEqual(replay, op)
        p['changes']['title'] = {'x-default':'Different'}
        with self.assertRaises(ns_db.RequestConflict):
            metadata_save.prepare(self.c, run_id=self.run, preview=p, db_path=self.db,
                backups_dir=self.root/'backups', base_dir=self.root/'base')

    def test_edited_pair_still_follows_reject_and_return(self):
        self.setup_catalog()
        op = self.prepare({'title':'Kept'})
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        data = self.xdest.read_bytes()
        self.run_engine('--reject', '--file-ids', str(self.pid))
        rejected = Path(self.c.execute('SELECT dest_path FROM photos').fetchone()[0])
        self.assertEqual(Path(str(rejected)+'.xmp').read_bytes(), data)
        self.run_engine('--return-to-library', '--file-ids', str(self.pid))
        returned = Path(self.c.execute('SELECT dest_path FROM photos').fetchone()[0])
        self.assertEqual(Path(str(returned)+'.xmp').read_bytes(), data)


    def command(self, action, payload, request_id=None):
        args = [sys.executable, '-m', 'engine', '--metadata', action,
                '--source', str(self.root/'source'), '--dest', str(self.root/'dest'),
                '--base', str(self.root/'base'), '--cache', str(self.root/'cache'),
                '--backups', str(self.root/'backups')]
        if request_id:
            args += ['--request-id', request_id]
        return subprocess.run(args, input=json.dumps(payload), text=True, capture_output=True, timeout=90)

    def test_cli_preview_save_replay_and_conflicting_request(self):
        self.setup_catalog()
        request = {'edits':[{'photo_id':self.pid, 'capture_id':self.capture, 'changes':{'title':'CLI saved'}}]}
        preview = self.command('preview', request)
        self.assertEqual(preview.returncode, 0, preview.stdout+preview.stderr)
        plan = json.loads(preview.stdout)['previews'][0]
        request['edits'][0]['token'] = plan['token']
        applied = self.command('apply', request, 'metadata-save-test')
        self.assertEqual(applied.returncode, 0, applied.stdout+applied.stderr)
        self.assertEqual(json.loads(applied.stdout)['outcomes'][0]['outcome'], 'completed')
        self.assertEqual(self.fields()['title'], {'x-default':'CLI saved'})
        self.assertEqual(self.command('apply', request, 'metadata-save-test').returncode, constants.EXIT_REQUEST_ALREADY_ACCEPTED)
        request['edits'][0]['changes']['title'] = 'Different'
        self.assertEqual(self.command('apply', request, 'metadata-save-test').returncode, constants.EXIT_REQUEST_CONFLICT)

    def test_cli_refuses_stale_token_and_keeps_original(self):
        self.setup_catalog()
        result = self.command('apply', {'edits':[{'photo_id':self.pid,'capture_id':self.capture,
            'changes':{'title':'Stale'}, 'token':'0'*64}]}, 'stale-token')
        self.assertEqual(result.returncode, 1, result.stdout+result.stderr)
        self.assertIn('preview changed', json.loads(result.stdout)['outcomes'][0]['error'])
        self.assertEqual(self.xdest.read_bytes(), self.original)

    def test_cli_retry_finishes_recorded_edit_without_new_metadata_version(self):
        self.setup_catalog()
        op = self.prepare({'title':'Retried'})
        with mock.patch.object(metadata_save, '_stage', side_effect=OSError('temporary failure')):
            metadata_save.execute(self.c, op)
        count = self.c.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0]
        result = self.command('retry', {'operation_ids':[op]}, 'retry-save')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(self.fields()['title'], {'x-default':'Retried'})
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0], count)

    def test_explicit_retry_can_repair_failed_backup_before_writing(self):
        self.setup_catalog()
        with mock.patch.object(ns_db, 'backup_catalog', return_value={'outcome':'failed'}):
            op = self.prepare({'title':'After backup repair'})
        result = self.command('retry', {'operation_ids':[op]}, 'retry-backup')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(self.fields()['title'], {'x-default':'After backup repair'})

    def test_cli_discard_requires_verified_unchanged_original(self):
        self.setup_catalog()
        op = self.prepare({'title':'Discarded'})
        result = self.command('discard', {'operation_ids':[op]}, 'discard-save')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(self.xdest.read_bytes(), self.original)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'already_finished')

    def test_storage_failure_signals_stop_batch_and_records_reason(self):
        self.setup_catalog()
        op = self.prepare({'title':'Full'})
        with mock.patch.object(metadata_save, '_stage', side_effect=OSError(errno.ENOSPC, 'disk full')):
            result = metadata_save.execute(self.c, op)
        self.assertTrue(result['stop_batch'])
        attempts = self.c.execute("SELECT detail_json FROM operation_events WHERE operation_id=? AND step='metadata_attempt_failed'", (op,)).fetchall()
        self.assertIn('disk full', json.loads(attempts[0][0])['error'])
        self.assertEqual(self.xdest.read_bytes(), self.original)

    def test_original_versions_survive_verified_backup_restore(self):
        self.setup_catalog()
        op = self.prepare({'title':'In backup'})
        metadata_save.execute(self.c, op)
        result = ns_db.backup_catalog(self.db, self.root/'backups', self.root/'base', trigger='manual')
        self.assertEqual(result['outcome'], 'succeeded')
        restored = self.root/'restored.db'
        restored.write_bytes(zstandard.ZstdDecompressor().decompress((self.root/'backups'/result['filename']).read_bytes()))
        checked = ns_db.connect(restored)
        self.addCleanup(checked.close)
        self.assertEqual(xmp_store.verify_blobs(checked), 2)
        old = metadata_save._manifest(checked, op)[3]['old_version']
        self.assertEqual(xmp_store.original_bytes(checked, old), self.original)
        self.assertEqual(metadata_save.active(checked, self.pid)['sources'], metadata_save.active(self.c, self.pid)['sources'])


    def test_explicit_copy_of_embedded_date_keeps_xmp_primary_and_records_donor(self):
        self.setup_catalog()
        copied = {'date_taken':{'photo_id':self.pid,'capture_id':self.capture,'source_id':'exif'}}
        preview = metadata_edits.preview_copy(self.db, photo_id=self.pid, capture_id=self.capture,
            changes={'title':'Keep this title'}, copy_fields=copied, destination_root=self.root/'dest')
        self.assertEqual(preview['target']['kind'], 'sidecar_xmp')
        self.assertEqual(preview['changes']['date_taken'], '1999-01-02T03:04:05')
        op = self.prepare({}, preview=preview)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        saved = metadata_save.active(self.c, self.pid)
        self.assertEqual(saved['composition']['donors']['date_taken']['source_id'], 'exif')
        self.assertEqual(saved['sources'][saved['primary_id']]['fields']['title'], {'x-default':'Keep this title'})
        self.assertEqual(self.photo.read_bytes(), self.photo_bytes)

    def test_copying_retained_version_requires_ownership_and_preserves_it(self):
        self.setup_catalog()
        version = self.c.execute('SELECT version_id FROM xmp_versions').fetchone()[0]
        copied = {'date_taken':{'photo_id':self.pid,'version_id':version}}
        preview = metadata_edits.preview_copy(self.db, photo_id=self.pid, capture_id=self.capture,
            changes={'title':'Another'}, copy_fields=copied, destination_root=self.root/'dest')
        op = self.prepare({}, preview=preview)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        self.assertEqual(xmp_store.original_bytes(self.c, version), self.original)
        copied['date_taken']['version_id'] = 999999
        with self.assertRaises(ValueError):
            metadata_edits.preview_copy(self.db, photo_id=self.pid, capture_id=self.capture,
                changes={}, copy_fields=copied, destination_root=self.root/'dest')

    def test_absent_donor_field_never_means_clear(self):
        self.setup_catalog()
        with self.assertRaises(ValueError):
            metadata_edits.preview_copy(self.db, photo_id=self.pid, capture_id=self.capture,
                changes={}, copy_fields={'title':{'photo_id':self.pid,'capture_id':self.capture,'source_id':'exif'}},
                destination_root=self.root/'dest')
        self.assertEqual(self.xdest.read_bytes(), self.original)

    def test_cli_copies_explicit_fields_without_changing_primary(self):
        self.setup_catalog()
        request = {'edits':[{'photo_id':self.pid,'capture_id':self.capture,'changes':{},
            'copy_fields':{'date_taken':{'photo_id':self.pid,'capture_id':self.capture,'source_id':'exif'}}}]}
        result = self.command('preview', request)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        request['edits'][0]['token'] = json.loads(result.stdout)['previews'][0]['token']
        result = self.command('apply', request, 'copy-metadata-field')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        saved = metadata_save.active(self.c, self.pid)
        self.assertTrue(saved['primary_id'].startswith('sidecar:'))
        self.assertEqual(saved['resolution']['proposed_effective']['date_taken'], '1999-01-02T03:04:05')


    def retain_alternative(self, date):
        run, _ = ns_db.create_run(self.c, mode='INDEX', source=str(self.root/'source'), destination=str(self.root/'dest'))
        file_id = self.c.execute('SELECT file_id FROM photo_files WHERE photo_id=?', (self.pid,)).fetchone()[0]
        data = metadata_index_test.packet(date)
        with ns_db.transaction(self.c):
            receipt = xmp_store.retain_capture(self.c, data=data, run_id=run,
                source_relative_path='archive/photo.jpg.xmp', file_ids=[file_id], role='owner', basis='confirmed')
        return receipt['version_id'], data

    def test_deliberate_primary_activation_preserves_both_versions_and_refiles(self):
        self.setup_catalog()
        version, data = self.retain_alternative('2010-11-12')
        preview = metadata_edits.preview_primary(self.db, photo_id=self.pid, capture_id=self.capture,
            version_id=version, destination_root=self.root/'dest')
        op = self.prepare({}, preview=preview)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        new = Path(self.c.execute('SELECT dest_path FROM photos').fetchone()[0])
        self.assertEqual(new.relative_to(self.root/'dest').as_posix(), 'library/2010/11/12/photo.jpg')
        self.assertEqual(Path(str(new)+'.xmp').read_bytes(), data)
        self.assertEqual(self.sidecar.read_bytes(), self.original)
        self.assertEqual(new.read_bytes(), self.photo_bytes)
        self.assertEqual(self.preview({'title':'Next edit'})['primary_before'], 'sidecar:version:'+str(version))

    def test_primary_activation_can_add_sidecar_to_photo_only_library(self):
        self.setup_catalog(sidecar=False)
        version, data = self.retain_alternative('2010-11-12')
        preview = metadata_edits.preview_primary(self.db, photo_id=self.pid, capture_id=self.capture,
            version_id=version, destination_root=self.root/'dest')
        op = self.prepare({}, preview=preview)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        saved = metadata_save.active(self.c, self.pid)
        self.assertEqual(saved['version_id'], version)
        self.assertEqual(xmp_store.original_bytes(self.c, version), data)

    def test_primary_activation_token_refuses_unowned_version(self):
        self.setup_catalog()
        with self.assertRaises(ValueError):
            metadata_edits.preview_primary(self.db, photo_id=self.pid, capture_id=self.capture,
                version_id=999999, destination_root=self.root/'dest')

    def test_cli_can_deliberately_choose_primary(self):
        self.setup_catalog()
        version, data = self.retain_alternative('2010-11-12')
        request = {'edits':[{'photo_id':self.pid,'capture_id':self.capture,'version_id':version}]}
        result = self.command('preview', request)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        request['edits'][0]['token'] = json.loads(result.stdout)['previews'][0]['token']
        result = self.command('apply', request, 'activate-version')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        new = Path(self.c.execute('SELECT dest_path FROM photos').fetchone()[0])
        self.assertEqual(Path(str(new)+'.xmp').read_bytes(), data)


    def test_partial_stage_can_be_retried_or_discarded_only_with_its_recorded_inode(self):
        self.setup_catalog()
        op = self.prepare({'title':'Partial write'})
        m = metadata_save._manifest(self.c, op)[3]
        stage = Path(m['staged'])
        fd = os.open(stage, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            info = os.fstat(stream.fileno())
            with ns_db.transaction(self.c):
                ns_db.record_event(self.c, operation_id=op, step='metadata_stage_created', outcome='created',
                    detail={'identity':[info.st_dev,info.st_ino]})
            stream.write(b'<partial')
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        self.assertFalse(stage.exists())
        self.assertEqual(self.fields()['title'], {'x-default':'Partial write'})

    def test_discard_removes_own_incomplete_stage_but_not_unrecorded_file(self):
        self.setup_catalog()
        op = self.prepare({'title':'Discard incomplete'})
        m = metadata_save._manifest(self.c, op)[3]
        stage = Path(m['staged'])
        stage.write_bytes(b'<partial')
        with self.assertRaises(ValueError):
            metadata_save.abandon(self.c, op)
        self.assertTrue(stage.exists())
        info = stage.stat()
        with ns_db.transaction(self.c):
            ns_db.record_event(self.c, operation_id=op, step='metadata_stage_created', outcome='created',
                detail={'identity':[info.st_dev,info.st_ino]})
        self.assertEqual(metadata_save.abandon(self.c, op)['outcome'], 'abandoned')
        self.assertFalse(stage.exists())
        self.assertEqual(self.xdest.read_bytes(), self.original)


    def test_corrupt_publication_never_records_success_or_removes_original(self):
        self.setup_catalog()
        op = self.prepare({'title':'Verify me'})
        real = metadata_save._publish
        def corrupt(*args):
            real(*args)
            self.xdest.write_bytes(metadata_index_test.packet('2000'))
        with mock.patch.object(metadata_save, '_publish', side_effect=corrupt):
            result = metadata_save.execute(self.c, op)
        self.assertEqual(result['outcome'], 'failed')
        self.assertFalse(result['metadata_saved'])
        self.assertIsNone(metadata_save.active(self.c, self.pid))
        self.assertEqual(Path(metadata_save._manifest(self.c, op)[3]['previous']).read_bytes(), self.original)

    def test_edit_preserves_sidecar_read_write_permissions(self):
        self.setup_catalog()
        self.xdest.chmod(0o640)
        op = self.prepare({'title':'Keep mode'})
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        self.assertEqual(self.xdest.stat().st_mode & 0o777, 0o640)

    def test_batch_prepares_all_edits_before_one_pre_action_backup(self):
        self.setup_catalog()
        other = self.root/'source/other.jpg'
        metadata_index_test.Image.new('RGB', (32,24), (20,30,40)).save(other)
        Path(str(other)+'.xmp').write_bytes(metadata_index_test.packet())
        self.run_engine('--copy')
        rows = self.c.execute('SELECT p.id,MAX(m.capture_id) FROM photos p JOIN photo_files pf ON pf.photo_id=p.id '
            'JOIN metadata_captures m ON m.file_id=pf.file_id GROUP BY p.id ORDER BY p.id').fetchall()
        self.assertEqual(len(rows), 2)
        request = {'edits':[{'photo_id':pid,'capture_id':capture,'changes':{'title':'Batch title'}} for pid,capture in rows]}
        result = self.command('preview', request)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        for edit, plan in zip(request['edits'], json.loads(result.stdout)['previews']):
            edit['token'] = plan['token']
        result = self.command('apply', request, 'batch-save')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual([o['outcome'] for o in report['outcomes']], ['completed','completed'])
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM backup_attempts WHERE related_run_id=? AND trigger_kind='pre_action'",
            (report['run_id'],)).fetchone()[0], 1)
        for pid,_ in rows:
            active = metadata_save.active(self.c, pid)
            self.assertEqual(active['sources'][active['primary_id']]['fields']['title'], {'x-default':'Batch title'})


if __name__ == '__main__':
    unittest.main()
