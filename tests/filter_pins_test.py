"""Pin-aware sidebar counts use generated photos and never change gallery membership."""
import unittest
import uuid
from engine import ns_db
import webui_api_test


class FilterPins(webui_api_test.ApiCase):
    def setUp(self):
        super().setUp()
        webui_api_test.make_photo(self.cfg.source / 'dated.jpg', 'dated', exif={36867: '2218:01:01 12:00:00'})
        webui_api_test.make_photo(self.cfg.source / 'undated.jpg', 'undated')
        self.create_catalog()
        self.wait_for(self.start(mode='index'))
        self.copied = self.wait_for(self.start(mode='copy'))['id']

    def photos(self, **params):
        response = self.client.get('/api/v1/photos', params={'view': 'organized', **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_counts_follow_replacement_or_pinned_intersection_without_changing_results(self):
        old = self.photos(undated=True)
        switch = self.photos(undated=True, filter_pins='')
        pinned = self.photos(undated=True, filter_pins='undated')
        self.assertEqual(old['chips']['suspicious'], 0)
        self.assertEqual(switch['chips']['suspicious'], 1)
        self.assertEqual(pinned['chips']['suspicious'], 0)
        for result in (switch, pinned):
            self.assertEqual(result['items'], old['items'])
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['chips']['undated'], 1)
        matching = self.photos(suspicious=True, filter_pins='')
        self.assertEqual(matching['total'], switch['chips']['suspicious'])
        self.assertEqual(self.photos(undated=True, q='undated', filter_pins='')['chips']['suspicious'], 0)
        # Job views use the same pin intersections without losing their historical scope.
        response = self.client.get('/api/v1/photos', params={'view': 'job', 'run': self.copied,
            'undated': True, 'filter_pins': 'undated'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['chips']['suspicious'], 0)


    def test_library_reminder_counts_match_inbox_and_refresh_after_done(self):
        self.assertEqual(self.photos(filter_pins='')['reasons']['later'], 0)
        photo = next(p for p in self.photos()['items'] if p['filename'] == 'undated.jpg')
        pid = photo['id']
        def answer(action):
            detail = self.client.get(f'/api/v1/photos/{pid}/review').json()
            response = self.client.post(f'/api/v1/photos/{pid}/review', json={
                'photo_id': pid, 'sha1': detail['sha1'], 'revision': detail['revision'],
                'reason': 'later', 'action': action, 'note': '', 'request_id': uuid.uuid4().hex})
            self.assertEqual(response.status_code, 200, response.text)
        answer('later')
        for view in ('organized', 'review'):
            listing = self.photos(view=view, filter_pins='')
            self.assertEqual(listing['reasons']['later'], 1)
            filtered = self.photos(view=view, reason='later', filter_pins='later')
            self.assertEqual([p['id'] for p in filtered['items']], [pid])
            self.assertEqual(filtered['reasons']['later'], 1)
            self.assertEqual(self.photos(view=view, q='dated', filter_pins='')['reasons']['later'], 1)
            self.assertEqual(self.photos(view=view, q='absent', filter_pins='')['reasons']['later'], 0)
            self.assertEqual(self.photos(view=view, reason='later', filter_pins='later')['chips']['suspicious'], 0)
        answer('done')
        self.assertEqual(self.photos(filter_pins='')['reasons']['later'], 0)
        self.assertEqual(self.photos(reason='later', filter_pins='')['total'], 0)

    def test_verification_counts_follow_pins_in_library_and_review(self):
        pid = next(p['id'] for p in self.photos()['items'] if p['filename'] == 'undated.jpg')
        with ns_db.connect(self.cfg.db_path) as c:
            op = c.execute("SELECT id FROM operations WHERE photo_id=? ORDER BY id DESC LIMIT 1", (pid,)).fetchone()[0]
            fid = c.execute("SELECT file_id FROM photo_files WHERE photo_id=?", (pid,)).fetchone()[0]
            c.execute("INSERT INTO attention_issues(operation_id,file_id,category,summary,opened_at) VALUES(?,?,'unestablished_outcome','Generated issue','2026-01-01')", (op,fid))
            c.commit()
        self.assertEqual(self.client.get('/api/v1/photos/places').json()['look_into']['issues'], 1)
        for view in ('organized', 'review'):
            self.assertEqual(self.photos(view=view, suspicious=True, filter_pins='')['reasons']['issues'], 1)
            self.assertEqual(self.photos(view=view, suspicious=True, filter_pins='suspicious')['reasons']['issues'], 0)
            current = self.photos(view=view, reason='issues', filter_pins='issues')
            self.assertEqual([p['id'] for p in current['items']], [pid])
            self.assertEqual(current['chips']['suspicious'], 0)
            self.assertEqual(current['reasons']['issues'], 1)

    def test_bad_or_exclusive_pins_are_refused(self):
        for pins in ('unknown', 'small,later', 'small,issues', 'later,issues', 'attention,small', 'attention,issues', "similar'); SELECT 1;--"):
            response = self.client.get('/api/v1/photos', params={'filter_pins': pins})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.photos(filter_pins='later')['total'], 2)


if __name__ == '__main__': unittest.main()
