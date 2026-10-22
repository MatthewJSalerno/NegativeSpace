"""Combined refinement counts use generated photos and never change gallery membership."""
import unittest
import uuid
from engine import ns_db
import webui_api_test


class SidebarRefinements(webui_api_test.ApiCase):
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

    def test_counts_follow_combined_filters_without_changing_results(self):
        undated = self.photos(undated=True)
        self.assertEqual(undated['chips']['suspicious'], 0)
        self.assertEqual(undated['chips']['undated'], 1)
        self.assertEqual(undated['total'], 1)
        self.assertEqual(self.photos(undated=True, suspicious=True)['total'], 0)
        self.assertEqual(self.photos(suspicious=True)['total'], 1)
        self.assertEqual(self.photos(undated=True, q='undated')['chips']['suspicious'], 0)
        response = self.client.get('/api/v1/photos', params={'view': 'job', 'run': self.copied, 'undated': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['chips']['suspicious'], 0)

    def test_library_reminder_counts_match_inbox_and_refresh_after_done(self):
        self.assertEqual(self.photos()['reasons']['later'], 0)
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
            listing = self.photos(view=view)
            self.assertEqual(listing['reasons']['later'], 1)
            filtered = self.photos(view=view, reason='later')
            self.assertEqual([p['id'] for p in filtered['items']], [pid])
            self.assertEqual(filtered['reasons']['later'], 1)
            self.assertEqual(self.photos(view=view, q='dated')['reasons']['later'], 1)
            self.assertEqual(self.photos(view=view, q='absent')['reasons']['later'], 0)
            self.assertEqual(self.photos(view=view, reason='later')['chips']['suspicious'], 0)
        answer('done')
        self.assertEqual(self.photos()['reasons']['later'], 0)
        self.assertEqual(self.photos(reason='later')['total'], 0)

    def test_verification_counts_follow_other_filters_in_library_and_review(self):
        pid = next(p['id'] for p in self.photos()['items'] if p['filename'] == 'undated.jpg')
        with ns_db.connect(self.cfg.db_path) as c:
            op = c.execute("SELECT id FROM operations WHERE photo_id=? ORDER BY id DESC LIMIT 1", (pid,)).fetchone()[0]
            fid = c.execute("SELECT file_id FROM photo_files WHERE photo_id=?", (pid,)).fetchone()[0]
            c.execute("INSERT INTO attention_issues(operation_id,file_id,category,summary,opened_at) VALUES(?,?,'unestablished_outcome','Generated issue','2026-01-01')", (op,fid))
            c.commit()
        self.assertEqual(self.photos()['reasons']['issues'], 1)
        for view in ('organized', 'review'):
            self.assertEqual(self.photos(view=view)['reasons']['issues'], 1)
            self.assertEqual(self.photos(view=view, suspicious=True)['reasons']['issues'], 0)
            current = self.photos(view=view, reason='issues')
            self.assertEqual([p['id'] for p in current['items']], [pid])
            self.assertEqual(current['chips']['suspicious'], 0)
            self.assertEqual(current['reasons']['issues'], 1)

    def test_overlapping_reasons_count_photos_once_and_replace_only_the_reason(self):
        setting = self.client.get('/api/v1/settings').json()['small_image_min']
        saved = self.client.put('/api/v1/settings', json={'values':{'small_image_min':800},
            'revisions':{'small_image_min':setting['revision']}})
        self.assertEqual(saved.status_code, 200, saved.text)
        pid = next(p['id'] for p in self.photos()['items'] if p['filename'] == 'undated.jpg')
        for action in ('later', 'done', 'later'):
            detail = self.client.get(f'/api/v1/photos/{pid}/review').json()
            response = self.client.post(f'/api/v1/photos/{pid}/review', json={
                'photo_id':pid, 'sha1':detail['sha1'], 'revision':detail['revision'],
                'reason':'later', 'action':action, 'note':'', 'request_id':uuid.uuid4().hex})
            self.assertEqual(response.status_code, 200, response.text)
        with ns_db.connect(self.cfg.db_path) as c:
            op = c.execute('SELECT id FROM operations WHERE photo_id=? ORDER BY id DESC LIMIT 1', (pid,)).fetchone()[0]
            fid = c.execute('SELECT file_id FROM photo_files WHERE photo_id=?', (pid,)).fetchone()[0]
            c.execute("INSERT INTO attention_issues(operation_id,file_id,category,summary,opened_at) "
                      "VALUES(?,?,'unestablished_outcome','Generated issue','2026-01-01')", (op,fid))
            c.commit()
        for view in ('organized', 'review', 'similar'):
            for reason in ('all', 'small', 'later', 'issues'):
                with self.subTest(view=view, reason=reason):
                    listing = self.photos(view=view, reason=reason)
                    self.assertEqual(listing['reasons'], {'all':2, 'small':2, 'later':1, 'issues':1})
                    self.assertEqual(listing['chips']['small'], 2)
                    if reason in ('later', 'issues'):
                        self.assertEqual([p['id'] for p in listing['items']], [pid])
                    filtered = self.photos(view=view, reason=reason, suspicious=True, types='jpg')
                    self.assertEqual(filtered['reasons'], {'all':1, 'small':1, 'later':0, 'issues':0})
                    self.assertEqual(filtered['total'], 0 if reason in ('later', 'issues') else 1)
                    self.assertEqual(self.photos(view=view, reason=reason, q='absent')['reasons'],
                                     {'all':0, 'small':0, 'later':0, 'issues':0})
        self.assertEqual(self.photos(view='job', run=self.copied)['reasons'], {'later':1})

    def test_bad_filters_are_refused_and_place_totals_do_not_follow_filters(self):
        for params in ({'reason': 'unknown'}, {'reason': "small'); SELECT 1;--"},
                       {'size_below': 0}, {'size_below': -1}, {'size_below': 100001},
                       {'size_below': '1 OR 1=1'}):
            response = self.client.get('/api/v1/photos', params=params)
            self.assertIn(response.status_code, (400, 422))
        whole = self.client.get('/api/v1/photos/places').json()
        self.photos(undated=True, suspicious=True)
        self.assertEqual(self.client.get('/api/v1/photos/places').json(), whole)



if __name__ == '__main__': unittest.main()
