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
            return c.execute('SELECT version_of,change_id,answer FROM photo_versions WHERE photo_id=?', (pid,)).fetchone()

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
