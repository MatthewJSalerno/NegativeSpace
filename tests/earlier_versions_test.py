"""Earlier versions of edited Library photos are held, never organized silently.

Generated photos only; a real date edit through the API rewrites the Library file, so the
untouched original becomes an earlier version (engine-spec 10, "Earlier versions: the
agreed behaviour").
"""
import shutil
from pathlib import Path

import webui_api_test
from webui import catalog


class EarlierVersions(webui_api_test.ApiCase):
    def setUp(self):
        super().setUp()
        self.create_catalog()
        webui_api_test.make_photo(self.cfg.source/'edited.jpg', 'edited', exif={36867:'2000:01:02 03:04:05'})
        # Byte-identical to edited.jpg before the edit: a Duplicate the edit will release.
        (self.cfg.source/'backup').mkdir()
        shutil.copyfile(self.cfg.source/'edited.jpg', self.cfg.source/'backup'/'edited.jpg')
        self.wait_for(self.start(mode='index'))
        self.wait_for(self.start(mode='copy'))
        self.pid = self.photo_id('edited.jpg')
        self.alias = self.photo_id('backup/edited.jpg')
        self.original = (self.cfg.source/'edited.jpg').read_bytes()
        self.edit_date(self.pid, '2001-02-03T04:05:06')

    def photo_id(self, relative):
        with catalog.connect(self.cfg.db_path) as c:
            row = c.execute('SELECT id FROM photos WHERE source_path=?', (str(self.cfg.source/relative),)).fetchone()
        self.assertIsNotNone(row, relative)
        return row[0]

    def row(self, pid):
        with catalog.connect(self.cfg.db_path) as c:
            return c.execute('SELECT status,dest_path,sha1_hash FROM photos WHERE id=?', (pid,)).fetchone()

    def version(self, pid):
        with catalog.connect(self.cfg.db_path) as c:
            return c.execute('SELECT version_of,change_id,(SELECT answer FROM photo_version_answers a WHERE a.photo_id=pv.photo_id '
                             'ORDER BY answer_id DESC LIMIT 1) FROM photo_versions pv WHERE photo_id=?', (pid,)).fetchone()

    def edit_date(self, pid, value):
        context = self.client.get(f'/api/v1/photos/{pid}/date-edit').json()
        self.assertEqual(context['target']['kind'], 'embedded_exif', context)
        planned = self.client.post(f'/api/v1/photos/{pid}/date-preview', json={
            'capture_id': context['capture_id'], 'value': value}).json()
        response = self.client.post(f'/api/v1/photos/{pid}/date-save', json={
            'edit': planned['edit'], 'token': planned['token'], 'request_id': f'edit-{pid}'})
        self.assertEqual(response.status_code, 202, response.text)
        self.wait_for(response.json()['id'])

    def test_a_source_copy_released_by_an_edit_is_held_as_an_earlier_version(self):
        status, dest, _ = self.row(self.alias)
        self.assertEqual(status, 'Pending', 'the edit releases the identical source copy')
        version_of, change_id, answer = self.version(self.alias)
        self.assertEqual((version_of, answer), (self.pid, None))
        self.assertIsNotNone(change_id)
        self.wait_for(self.start(mode='copy'))
        self.assertEqual(self.row(self.alias)[0], 'Pending', 'Copy must not organize an unanswered earlier version')

    def test_an_original_arriving_later_is_held_and_never_deleted_by_move(self):
        (self.cfg.source/'later').mkdir()
        (self.cfg.source/'later'/'found.jpg').write_bytes(self.original)
        self.wait_for(self.start(mode='index'))
        found = self.photo_id('later/found.jpg')
        version_of, _, answer = self.version(found)
        self.assertEqual((version_of, answer), (self.pid, None))
        self.wait_for(self.start(mode='move', file_ids=[found]))
        self.assertTrue((self.cfg.source/'later'/'found.jpg').exists(), 'Move must never remove an earlier version')
        # Identical to the released copy, so Index files it as that copy's Duplicate.
        self.assertIn(self.row(found)[0], ('Pending', 'Duplicate'))

    def test_the_edited_photos_own_source_is_not_its_own_earlier_version(self):
        self.wait_for(self.start(mode='index'))
        self.assertIsNone(self.version(self.pid))

    def versions(self, pid):
        response = self.client.get(f'/api/v1/photos/{pid}/versions')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def answer(self, pid, answer, request_id, revision=None):
        if revision is None:
            revision = self.versions(pid)['revision']
        return self.client.post(f'/api/v1/photos/{pid}/versions/answer', json={
            'photo_id': pid, 'answer': answer, 'revision': revision, 'request_id': request_id})

    def attention_ids(self):
        listed = self.client.get('/api/v1/photos', params={'view': 'unorganized', 'reason': 'attention'}).json()
        return {item['id'] for item in listed['items']}

    def test_the_full_recorded_change_list_and_both_links_are_shown(self):
        earlier = self.versions(self.alias)['earlier_version']
        self.assertEqual(earlier['version_of']['id'], self.pid)
        self.assertEqual(earlier['version_of']['location'], 'Library')
        self.assertEqual((earlier['state'], earlier['answerable'], earlier['same_picture']), ('waiting', True, True))
        self.assertEqual(len(earlier['changes']), 1)
        change = earlier['changes'][0]
        self.assertIn(dict(source='exif', field='date_taken', before='2000-01-02T03:04:05', after='2001-02-03T04:05:06'),
                      change['fields'])
        self.assertEqual(change['tags'], [], 'DateTimeOriginal is translated, so not repeated by tag name')
        library = self.versions(self.pid)
        self.assertIsNone(library['earlier_version'])
        self.assertEqual([(v['id'], v['state']) for v in library['earlier_versions']], [(self.alias, 'waiting')])
        card = self.client.get(f'/api/v1/photos/{self.pid}/inspect').json()['version']
        self.assertEqual((card['earlier_versions'], card['waiting']), (1, 1))

    def test_waiting_is_needs_attention_and_not_kept_is_held_quietly(self):
        self.assertIn(self.alias, self.attention_ids())
        status = self.client.get('/api/v1/status').json()
        self.assertEqual((status['eligible']['copy'], status['held']), (0, 1))
        response = self.answer(self.alias, 'not_kept', 'not-kept')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['earlier_version']['state'], 'not_kept')
        self.assertNotIn(self.alias, self.attention_ids())
        status = self.client.get('/api/v1/status').json()
        self.assertEqual((status['eligible']['copy'], status['held']), (0, 0), 'out of the waiting count, still not copied')
        self.wait_for(self.start(mode='copy'))
        self.assertEqual(self.row(self.alias)[0], 'Pending')
        self.assertTrue((self.cfg.source/'backup'/'edited.jpg').exists())

    def test_keep_it_after_all_organizes_it_as_its_own_photo(self):
        self.assertEqual(self.answer(self.alias, 'not_kept', 'first').status_code, 200)
        self.assertEqual(self.answer(self.alias, 'keep_separate', 'after-all').status_code, 200)
        self.wait_for(self.start(mode='copy'))
        status, dest, sha1 = self.row(self.alias)
        self.assertEqual(status, 'Copied')
        self.assertEqual(Path(dest).read_bytes(), self.original)
        self.assertIn('/2000/', dest, 'filed by its own metadata, the date before the fix')
        history = self.versions(self.alias)['earlier_version']['answers']
        self.assertEqual([a['answer'] for a in history], ['not_kept', 'keep_separate'])

    def test_answers_are_guarded_and_replayable(self):
        first = self.answer(self.alias, 'not_kept', 'replay')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.answer(self.alias, 'not_kept', 'replay', revision=0).json(), first.json())
        self.assertEqual(self.answer(self.alias, 'keep_separate', 'stale', revision=0).status_code, 409)
        self.assertEqual(self.answer(self.alias, 'not_kept', 'again').status_code, 409, 'already the answer')
        self.assertEqual(self.answer(self.pid, 'not_kept', 'library').status_code, 409, 'not an earlier version')

    def test_each_lineage_names_and_links_the_other_photo(self):
        earlier = self.client.get(f'/api/v1/photos/{self.alias}/lineage').json()['versions']
        self.assertEqual((earlier['version_of']['id'], earlier['version_of']['state']), (self.pid, 'waiting'))
        self.assertEqual(earlier['earlier_versions'], [])
        library = self.client.get(f'/api/v1/photos/{self.pid}/lineage').json()
        self.assertIsNone(library['versions']['version_of'])
        self.assertEqual([v['id'] for v in library['versions']['earlier_versions']], [self.alias])
        self.assertNotIn(self.alias, library['photos'], 'a version link, never a merged history')

    def test_an_answer_covers_every_identical_copy(self):
        (self.cfg.source/'later').mkdir()
        (self.cfg.source/'later'/'found.jpg').write_bytes(self.original)
        self.wait_for(self.start(mode='index'))
        found = self.photo_id('later/found.jpg')
        self.assertEqual(self.answer(self.alias, 'not_kept', 'both').status_code, 200)
        self.assertEqual(self.versions(found)['earlier_version']['state'], 'not_kept')
