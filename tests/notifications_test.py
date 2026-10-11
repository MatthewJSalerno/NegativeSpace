"""Notification pagination and additive catalog read receipts, with generated jobs only."""
import concurrent.futures
import unittest
from unittest import mock
from engine import ns_db
from webui import notifications
import webui_api_test


class Notifications(webui_api_test.ApiCase):
    def setUp(self):
        super().setUp()
        self.create_catalog()

    def run_record(self, status='Completed'):
        with ns_db.connect(self.cfg.db_path) as conn:
            run, _ = ns_db.create_run(conn, mode='INDEX', source=str(self.cfg.source), destination=str(self.cfg.dest))
            if status != 'Preparing':
                ns_db.transition_run(conn, run, 'Running')
                if status != 'Running': ns_db.transition_run(conn, run, status)
            return run

    def test_finished_only_and_individual_read_receipts(self):
        first, second = self.run_record(), self.run_record('Failed')
        self.run_record('Running')
        self.assertEqual(self.client.get('/api/v1/notifications/unread').json(), {'unread': 2})
        rows = self.client.get('/api/v1/notifications').json()['items']
        self.assertEqual([row['run']['id'] for row in rows], [second, first])
        before = self.client.get(f'/api/v1/runs/{second}').json()
        result = self.client.put('/api/v1/notifications/read', json={'run_ids': [second]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get('/api/v1/notifications/unread').json()['unread'], 1)
        self.assertEqual(self.client.get(f'/api/v1/runs/{second}').json(), before)
        self.assertEqual(self.client.get('/api/v1/ui-state').json(), {'dismissed_run': None})
        rows = self.client.get('/api/v1/notifications').json()['items']
        self.assertEqual([row['read'] for row in rows], [True, False])

    def test_atomic_refusal_and_strict_input(self):
        valid, active = self.run_record(), self.run_record('Running')
        for body in ({}, {'run_ids': []}, {'run_ids': [True]}, {'run_ids': ['1']},
                     {'run_ids': [-1]}, {'run_ids': [valid, 2**63]}, {'run_ids': [valid, 99999]}, {'run_ids': [valid, active]},
                     {'run_ids': [valid] * 101}, {'run_ids': [valid], 'extra': 1}):
            response = self.client.put('/api/v1/notifications/read', json=body)
            self.assertEqual(response.status_code, 400, (body, response.text))
            self.assertEqual(self.client.get('/api/v1/notifications/unread').json()['unread'], 1)

    def test_pagination_does_not_acknowledge_unseen_jobs(self):
        ids = [self.run_record() for _ in range(23)]
        page = self.client.get('/api/v1/notifications').json()
        self.assertEqual(len(page['items']), 20)
        seen = [item['run']['id'] for item in page['items']]
        self.client.put('/api/v1/notifications/read', json={'run_ids': seen})
        self.assertEqual(self.client.get('/api/v1/notifications/unread').json()['unread'], 3)
        more = self.client.get('/api/v1/notifications', params={'before': page['next_before']}).json()
        self.assertEqual([item['run']['id'] for item in more['items']], list(reversed(ids[:3])))
        self.assertIsNone(more['next_before'])
        for query in ('?limit=0', '?limit=51', '?before=0', '?before=9223372036854775808'):
            self.assertEqual(self.client.get('/api/v1/notifications'+query).status_code, 422)

    def test_concurrent_tabs_are_additive_and_replay_is_idempotent(self):
        ids = [self.run_record() for _ in range(3)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda ids: notifications.mark_read(self.cfg.db_path, {'run_ids': ids}), [ids[:2], ids[1:]]))
        notifications.mark_read(self.cfg.db_path, {'run_ids': ids})
        self.assertEqual(notifications.unread_count(self.cfg.db_path), 0)
        with ns_db.connect(self.cfg.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ui_state WHERE key LIKE 'read_notification:%'").fetchone()[0], 3)
        self.run_record()
        self.assertEqual(notifications.unread_count(self.cfg.db_path), 1)

    def test_badge_does_not_derive_detailed_outcomes(self):
        self.run_record()
        with mock.patch('webui.outcomes._run_dict', side_effect=AssertionError('badge read derived details')):
            self.assertEqual(self.client.get('/api/v1/notifications/unread').json()['unread'], 1)


if __name__ == '__main__': unittest.main()
