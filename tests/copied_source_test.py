"""A full Index observes externally removed originals without doing a Move."""
import contextlib
from pathlib import Path
from unittest.mock import patch

from engine import ns_db, runtime, scan, reconcile
from webui_api_test import ApiCase, make_photo


class CopiedSourceTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.create_catalog()
        self.source = self.cfg.source / 'sample.jpg'
        self.other = self.cfg.source / 'still-present.jpg'
        make_photo(self.source, 'removed original')
        make_photo(self.other, 'still here')
        self.wait_for(self.start(mode='index'))
        self.wait_for(self.start(mode='copy'))
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            self.pid, dest = c.execute('SELECT id,dest_path FROM photos WHERE source_path=?', (str(self.source),)).fetchone()
        self.dest = Path(dest)
        self.original = self.source.read_bytes()
        runtime.cancel_requested.clear()

    def tearDown(self):
        runtime.cancel_requested.clear()
        super().tearDown()

    def status(self):
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            return c.execute('SELECT status FROM photos WHERE id=?', (self.pid,)).fetchone()[0]

    def observe(self, **kwargs):
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            run = ns_db.create_run(c, mode='INDEX', source=str(self.cfg.source), destination=str(self.cfg.dest))[0]
        scan.mark_vanished_sources(str(self.cfg.db_path), run, self.cfg.source,
            [str(self.other)], dest_root=self.cfg.dest, check_copied=True, **kwargs)

    def test_index_records_observation_once_and_updates_move_count(self):
        self.source.unlink()
        result = self.wait_for(self.start(mode='index'))
        self.assertEqual(result['outcome']['failed'], 0)
        self.assertEqual(self.status(), 'Found_At_Destination')
        self.assertEqual(self.dest.read_bytes(), self.original)
        self.assertEqual(self.client.get('/api/v1/status').json()['eligible']['move'], 1)
        self.assertEqual(self.client.get('/api/v1/photos?view=organized').json()['total'], 2)
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            self.assertEqual(c.execute('SELECT presence_state FROM file_states JOIN photo_files USING(file_id) WHERE photo_id=?', (self.pid,)).fetchone()[0], 'missing')
            events = c.execute("SELECT status,error_message FROM operations WHERE photo_id=? AND status='Found_At_Destination'", (self.pid,)).fetchall()
            self.assertEqual(len(events), 1)
            self.assertIn('outside NegativeSpace', events[0][1])
            self.assertFalse(c.execute("SELECT 1 FROM operations WHERE status='Completed'").fetchone())
        self.wait_for(self.start(mode='index'))
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM operations WHERE photo_id=? AND status='Found_At_Destination'", (self.pid,)).fetchone()[0], 1)

    def test_empty_source_requires_confirmation_even_when_all_photos_were_copied(self):
        self.source.unlink(); self.other.unlink()
        result = self.wait_for(self.start(mode='index'))
        self.assertEqual(result['questions'], ['source_empty'])
        self.assertEqual(self.status(), 'Copied')
        response = self.client.post(f"/api/v1/runs/{result['id']}/answer", json={'question':'source_empty','answer':'confirm_empty'})
        self.assertEqual(response.status_code, 202, response.text)
        self.wait_for(response.json()['id'])
        self.assertEqual(self.status(), 'Found_At_Destination')
        self.assertEqual(self.client.get('/api/v1/status').json()['eligible']['move'], 0)

    def test_changed_copy_opens_one_actionable_issue_and_can_be_verified_after_restoring(self):
        self.source.unlink(); self.dest.write_bytes(b'changed')
        result = self.wait_for(self.start(mode='index'))
        self.assertEqual(result['outcome']['failed'], 1)
        self.assertEqual(self.status(), 'Copied')
        issues = self.client.get(f'/api/v1/photos/{self.pid}/issues').json()['items']
        self.assertEqual(len(issues), 1)
        self.assertIn('mismatch', issues[0]['summary'])
        self.wait_for(self.start(mode='index'))
        self.assertEqual(len(self.client.get(f'/api/v1/photos/{self.pid}/issues').json()['items']), 1)
        self.dest.write_bytes(self.original)
        response = self.client.post('/api/v1/issues/check', json={'issue_id':issues[0]['issue_id']})
        self.assertEqual(response.status_code, 202, response.text)
        self.wait_for(response.json()['id'])
        self.assertEqual(self.status(), 'Found_At_Destination')
        self.assertEqual(self.client.get(f'/api/v1/photos/{self.pid}/issues').json()['items'], [])
        self.assertFalse(self.source.exists())

    def test_missing_copy_and_symlink_are_not_treated_as_verified(self):
        self.source.unlink(); self.dest.unlink()
        self.observe()
        self.assertEqual(self.status(), 'Copied')
        self.assertTrue(self.client.get(f'/api/v1/photos/{self.pid}/issues').json()['items'])
        # A separate fresh photo tests a symlink without an earlier issue short-circuit.
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            c.execute('DELETE FROM attention_issues'); c.commit()
        self.dest.symlink_to(self.other)
        self.observe()
        self.assertEqual(self.status(), 'Copied')
        self.assertTrue(self.dest.is_symlink())

    def test_unreadable_original_and_cancelled_verification_leave_status_unchanged(self):
        with patch.object(scan.os, 'stat', side_effect=PermissionError):
            self.assertFalse(scan._source_missing(str(self.source)))
        self.source.unlink()
        def cancel(*args, **kwargs):
            runtime.cancel_requested.set()
            return 'cancelled', {}
        with patch.object(reconcile, '_recovery_verify', side_effect=cancel):
            self.observe()
        self.assertEqual(self.status(), 'Copied')
        self.assertEqual(self.client.get(f'/api/v1/photos/{self.pid}/issues').json()['items'], [])

    def test_original_reappearing_during_check_is_not_recorded_missing(self):
        self.source.unlink()
        verify = reconcile._recovery_verify
        def restore(*args, **kwargs):
            result = verify(*args, **kwargs)
            self.source.write_bytes(self.original)
            return result
        with patch.object(reconcile, '_recovery_verify', side_effect=restore):
            self.observe()
        self.assertEqual(self.status(), 'Copied')
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_existing_original_is_not_rehashed_and_recorded_renamed_destination_is_used(self):
        with patch.object(reconcile, '_recovery_verify', side_effect=AssertionError('unnecessary read')):
            self.observe()
        self.source.unlink()
        renamed = self.dest.with_name('chosen-name.jpg')
        self.dest.rename(renamed)
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            c.execute('UPDATE file_states SET current_path=? WHERE current_path=?', (str(renamed), str(self.dest)))
            c.execute('UPDATE photos SET dest_path=? WHERE id=?', (str(renamed), self.pid)); c.commit()
        self.observe()
        self.assertEqual(self.status(), 'Found_At_Destination')
        self.assertEqual(renamed.read_bytes(), self.original)

    def test_outside_destination_is_not_read(self):
        self.source.unlink()
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            c.execute('UPDATE photos SET dest_path=? WHERE id=?', (str(self.other), self.pid)); c.commit()
        with patch.object(reconcile, '_recovery_verify', side_effect=AssertionError('outside read')):
            self.observe()
        self.assertEqual(self.status(), 'Copied')

    def test_duplicate_savings_survive_observed_delivery_and_removed_duplicates_stop_counting(self):
        twin = self.cfg.source / 'duplicate.jpg'
        twin.write_bytes(self.original)
        self.wait_for(self.start(mode='index'))
        before = self.client.get('/api/v1/stats').json()['duplicates']
        self.assertEqual(before['copies_not_written'], 1)
        self.assertGreater(before['move_would_free'], 0)
        self.source.unlink()
        self.wait_for(self.start(mode='index'))
        after = self.client.get('/api/v1/stats').json()['duplicates']
        self.assertEqual(after['copies_not_written'], 1)
        self.assertEqual(after['saved_at_destination'], before['saved_at_destination'])
        twin.unlink()
        self.wait_for(self.start(mode='index'))
        self.assertEqual(self.client.get('/api/v1/stats').json()['duplicates']['move_would_free'], 0)

    def test_catalog_failure_rolls_back_observation_and_leaves_copy_intact(self):
        self.source.unlink()
        with patch.object(ns_db, 'settle_operation', side_effect=RuntimeError('injected catalog failure')):
            with self.assertRaises(RuntimeError):
                self.observe()
        self.assertEqual(self.status(), 'Copied')
        self.assertEqual(self.dest.read_bytes(), self.original)
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as c:
            self.assertEqual(c.execute('SELECT presence_state FROM file_states JOIN photo_files USING(file_id) WHERE photo_id=?', (self.pid,)).fetchone()[0], 'present')
