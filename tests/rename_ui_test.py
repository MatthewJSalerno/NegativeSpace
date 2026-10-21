"""Naming UI boundary: real verified jobs, confirmation races and gallery scopes."""
from pathlib import Path
import time
import subprocess
import sys
import unittest
from engine import ns_db, relocate
from webui import catalog
import metadata_dates_test


class RenameTests(unittest.TestCase):
    setUp = metadata_dates_test.DateEditorTests.setUp
    run_engine = metadata_dates_test.DateEditorTests.run_engine
    conn = metadata_dates_test.DateEditorTests.conn
    setup_catalog = metadata_dates_test.DateEditorTests.setup_catalog
    client = metadata_dates_test.DateEditorTests.client

    def preview(self, client, name='A better name'):
        result = client.post(f'/api/v1/photos/{self.pid}/rename-preview', json={'name':name})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def save(self, client, name, plan, request='rename-ui'):
        body = dict(name=name, token=plan['token'], request_id=request)
        result = client.post(f'/api/v1/photos/{self.pid}/rename', json=body)
        self.assertEqual(result.status_code, 202, result.text)
        for _ in range(300):
            run = client.get(f"/api/v1/runs/{result.json()['id']}").json()
            if run['status'] not in ('Preparing','Running','Cancelling'):
                return run, body
            time.sleep(.05)
        self.fail('Rename did not finish')

    def test_rename_preserves_pair_source_and_history_and_replays(self):
        c = self.client(); old = self.dest; source = self.photo.read_bytes(); sidecar = self.xdest.read_bytes()
        plan = self.preview(c, 'Café trip.PNG')
        self.assertEqual(Path(plan['new_path']).name, 'Café trip.jpg')
        self.assertEqual(Path(plan['new_path']).parent, old.parent)
        run, body = self.save(c, 'Café trip.PNG', plan)
        self.assertEqual(run['status'], 'Completed', run)
        new = Path(plan['new_path'])
        self.assertEqual(new.read_bytes(), source)
        self.assertEqual(Path(str(new)+'.xmp').read_bytes(), sidecar)
        self.assertFalse(old.exists()); self.assertFalse(self.xdest.exists())
        self.assertEqual(self.photo.read_bytes(), source)
        self.assertEqual(self.sidecar.read_bytes(), sidecar)
        ops = c.get('/api/v1/operations', params={'run':run['id']}).json()['items']
        self.assertEqual(len(ops), 1, ops)
        self.assertEqual((ops[0]['status'],ops[0]['source_path'],ops[0]['dest_path']), ('Renamed',str(old),str(new)))
        replay = c.post(f'/api/v1/photos/{self.pid}/rename', json=body)
        self.assertEqual(replay.status_code, 202, replay.text)
        self.assertEqual(replay.json()['id'], run['id'])
        body['name'] = 'another'
        self.assertEqual(c.post(f'/api/v1/photos/{self.pid}/rename', json=body).status_code, 409)
        names = c.get(f'/api/v1/photos/{self.pid}/names').json()
        self.assertIn(old.stem, [x['name'] for x in names['candidates']])

    def test_collision_preview_and_stale_confirmation_preserve_every_file(self):
        c = self.client(); occupied = self.dest.with_name('taken.jpg'); occupied.write_bytes(b'other photo')
        plan = self.preview(c, 'taken')
        self.assertTrue(plan['collision'])
        Path(plan['new_path']).write_bytes(b'new arrival after preview')
        response = c.post(f'/api/v1/photos/{self.pid}/rename', json=dict(name='taken',token=plan['token'],request_id='stale'))
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(occupied.read_bytes(), b'other photo')
        self.assertEqual(self.dest.read_bytes(), self.photo_bytes)
        self.assertEqual(Path(plan['new_path']).read_bytes(), b'new arrival after preview')

    def test_engine_rechecks_token_after_api_acceptance(self):
        c = self.client(); plan = self.preview(c)
        # Use the engine directly to model a collision arriving after the API precheck.
        Path(plan['new_path']).write_bytes(b'late arrival')
        result = subprocess.run([sys.executable, '-m', 'engine', '--base', str(self.root/'base'), '--dest', str(self.root/'dest'), '--backups', str(self.root/'backups'), '--rename', str(self.pid), '--name', 'A better name', '--rename-preview-token', plan['token']], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout+result.stderr)
        self.assertEqual(self.dest.read_bytes(), self.photo_bytes)
        self.assertEqual(Path(plan['new_path']).read_bytes(), b'late arrival')

    def test_filename_starting_with_a_dash_is_data_not_an_engine_flag(self):
        c=self.client(); name='--move'
        plan=self.preview(c,name)
        run,body=self.save(c,name,plan,'dash-name')
        self.assertEqual(run['status'],'Completed',run)
        self.assertEqual(Path(plan['new_path']).name,'--move.jpg')
        self.assertEqual(self.photo.read_bytes(),self.photo_bytes)
        replay=c.post(f'/api/v1/photos/{self.pid}/rename',json=body)
        self.assertEqual(replay.status_code,202,replay.text)
        self.assertEqual(replay.json()['id'],run['id'])

    def test_no_change_and_invalid_names(self):
        c = self.client()
        self.assertTrue(self.preview(c, self.dest.name)['unchanged'])
        for name in ('', '../escape', '/absolute', '.hidden', 'x'*256, None, 1, ['name']):
            with self.subTest(name=name):
                result=c.post(f'/api/v1/photos/{self.pid}/rename-preview',json={'name':name})
                self.assertEqual(result.status_code,400,result.text)
        self.assertEqual(self.dest.read_bytes(),self.photo_bytes)

    def test_sources_rejects_and_missing_photos_have_no_controls(self):
        c=self.client()
        for status in ('Pending','Rejected','Failed'):
            with ns_db.connect(self.db) as conn:conn.execute('UPDATE photos SET status=? WHERE id=?',(status,self.pid))
            self.assertEqual(c.get(f'/api/v1/photos/{self.pid}/names').status_code,400)
            self.assertEqual(c.post(f'/api/v1/photos/{self.pid}/rename-preview',json={'name':'new'}).status_code,400)
        self.assertEqual(c.get('/api/v1/photos/9223372036854775807/names').status_code,400)

    def test_confirm_requires_token_and_request_id(self):
        c=self.client(); p=self.preview(c)
        for body in ({'name':'x'},dict(name='x',token='bad',request_id='x'),dict(name='x',token=p['token'],request_id=None),dict(name='x',token=p['token'],request_id='x',extra=True)):
            r=c.post(f'/api/v1/photos/{self.pid}/rename',json=body)
            self.assertEqual(r.status_code,400,r.text)

    def test_other_names_filter_agrees_with_ids_position_and_facets(self):
        c=self.client(); name='new-name';p=self.preview(c,name);self.save(c,name,p)
        params={'view':'organized','other_names':True,'sort':'duplicates'}
        listed=c.get('/api/v1/photos',params=params);self.assertEqual(listed.status_code,200,listed.text)
        self.assertEqual([x['id'] for x in listed.json()['items']],[self.pid])
        ids=c.get('/api/v1/photos/ids',params=params).json();self.assertEqual(ids['ids'],[self.pid])
        pos=c.post('/api/v1/photos/position',json={**params,'photo_id':self.pid}).json()
        self.assertEqual(pos['position'],0,pos)
        self.assertEqual(c.get('/api/v1/photos/types',params=params).json()['types'][0]['photos'],1)
        self.assertEqual(c.get('/api/v1/photos',params={**params,'q':'does-not-match'}).json()['total'],0)

    def test_filename_stem_matches_recorded_path_names(self):
        for name in ('photo.jpg', 'trip.2019.jpg', '.hidden', '..dots', 'name.',
                     'Café trip.PNG', 'a\\b.jpg', 'no-extension', 'a..jpg'):
            with self.subTest(name=name):
                path = '/generated/nested/' + name
                self.assertEqual(catalog._filename_stem(path), Path(path).stem)
        self.assertIsNone(catalog._filename_stem(None))

    def test_same_stem_in_different_folders_is_not_another_name(self):
        c=self.client()
        self.assertEqual(c.get('/api/v1/photos',params={'view':'organized','other_names':True}).json()['total'],0)
        self.assertEqual(c.get(f'/api/v1/photos/{self.pid}/names').json()['candidates'],[])

    def test_operations_only_alternative_and_same_stem(self):
        c=self.client()
        with ns_db.connect(self.db) as conn:
            conn.execute("INSERT INTO operations (run_id,photo_id,status,timestamp,source_path) SELECT run_id,photo_id,status,timestamp,? FROM operations WHERE photo_id=? LIMIT 1", ('/generated/old-label.jpg', self.pid))
        self.assertIn('old-label',[x['name'] for x in c.get(f'/api/v1/photos/{self.pid}/names').json()['candidates']])
        self.assertEqual(c.get('/api/v1/photos',params={'view':'organized','other_names':True}).json()['total'],1)


if __name__ == '__main__':
    unittest.main()
