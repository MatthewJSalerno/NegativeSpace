"""Selection-file ownership across API processes and a surviving engine child.

Run in Docker with unittest discovery; all files belong to generated fixtures.
"""
import contextlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from fastapi.testclient import TestClient

from engine import ns_db
from webui.app import create_app
from webui.jobs import JobRunner
from webui_api_test import ApiCase, make_photo


class SelectionOwnership(ApiCase):
    def test_restart_preserves_selection_before_child_reads_it(self):
        self.create_catalog()
        make_photo(self.cfg.source / 'sample.jpg', 'selection-ownership')
        self.wait_for(self.start(mode='index'))
        chosen = self.client.get('/api/v1/photos/ids').json()['ids']
        fixture = Path(__file__).with_name('selection_engine_fixture.py')
        script = '''
import json, sys
from pathlib import Path
from webui.config import Config
from webui.jobs import JobRunner
root = Path(sys.argv[1])
cfg = Config(base=root/'appdata', source=root/'src', dest=Path(sys.argv[4]),
             cache=root/'cache', backups=root/'backups', engine=Path(sys.argv[2]))
print(JobRunner(cfg).start(**json.loads(sys.argv[3])), flush=True)
'''
        for kill_parent in (False, True):
            with self.subTest(kill_parent=kill_parent):
                ready = self.cfg.base / 'selection-fixture-ready.json'
                release = self.cfg.base / 'selection-fixture-release'
                ready.unlink(missing_ok=True)
                release.unlink(missing_ok=True)
                body = {'mode': 'copy', 'file_ids': chosen, 'request_id': f'ownership-{kill_parent}'}
                child_pid = None
                with open(self.root / 'api-worker.log', 'w+') as output:
                    worker = subprocess.Popen([sys.executable, '-c', script, str(self.root),
                                               str(fixture), json.dumps(body), str(self.cfg.dest)], stdout=output, stderr=output)
                    try:
                        deadline = time.monotonic() + 10
                        while not ready.exists():
                            self.assertIsNone(worker.poll(), 'API worker exited before its child was ready')
                            self.assertLess(time.monotonic(), deadline, 'child did not reach the pause')
                            time.sleep(.02)
                        # The marker can be observed before its JSON write finishes.
                        while child_pid is None:
                            try:
                                child_pid = json.loads(ready.read_text())['pid']
                            except json.JSONDecodeError:
                                self.assertLess(time.monotonic(), deadline)
                                time.sleep(.02)
                        selection = self.cfg.base / 'selections' / f'{body["request_id"]}.ids'
                        before = selection.read_bytes()
                        if kill_parent:
                            worker.kill()
                            worker.wait(timeout=5)
                        with TestClient(create_app(self.cfg)) as restarted:
                            self.assertTrue(selection.exists(), 'API startup removed a live selection')
                            self.assertEqual(selection.read_bytes(), before)
                            blocked = restarted.post('/api/v1/jobs/start', json=body)
                            self.assertEqual((blocked.status_code, blocked.json()['error']),
                                             (409, 'job_already_running'))
                            release.touch()
                            deadline = time.monotonic() + 15
                            while True:
                                record = restarted.get(f'/api/v1/job-requests/{body["request_id"]}').json()
                                if record['state'] == 'accepted':
                                    break
                                self.assertLess(time.monotonic(), deadline, 'surviving child was not accepted')
                                time.sleep(.05)
                            run = self.wait_for(record['run']['id'])
                            self.assertEqual(run['status'], 'Completed')
                            replay = restarted.post('/api/v1/jobs/start', json=body)
                            self.assertEqual(replay.status_code, 202, replay.text)
                            self.assertEqual(replay.json()['id'], run['id'])
                        if not kill_parent:
                            self.assertEqual(worker.wait(timeout=5), 0)
                        deadline = time.monotonic() + 5
                        while True:
                            with self.app_jobs()._selection_lease() as lease:
                                finished = lease is not None
                            if finished:
                                break
                            self.assertLess(time.monotonic(), deadline, 'child retained the selection lock')
                            time.sleep(.02)
                        child_pid = None
                        JobRunner(self.cfg)
                        self.assertFalse(selection.exists(), 'abandoned input was not reclaimed after child exit')
                        self.assertEqual(len(self.client.get('/api/v1/runs').json()['runs']),
                                         2 + int(kill_parent))
                    finally:
                        release.touch()
                        if worker.poll() is None:
                            worker.terminate()
                            worker.wait(timeout=5)
                        if child_pid is not None:
                            with contextlib.suppress(ProcessLookupError):
                                os.kill(child_pid, signal.SIGTERM)

    def test_next_start_reclaims_input_after_writer_dies_before_spawn(self):
        self.create_catalog()
        make_photo(self.cfg.source / 'sample.jpg', 'abandoned-selection')
        self.wait_for(self.start(mode='index'))
        chosen = self.client.get('/api/v1/photos/ids').json()['ids']
        body = {'mode': 'copy', 'file_ids': chosen, 'request_id': 'abandoned-start'}
        script = '''
import json, sys, time
from pathlib import Path
from engine import ns_db
from webui.config import Config
from webui.jobs import JobRunner
base = Path(sys.argv[1])
runner = JobRunner(Config(base=base))
with runner._selection_lease():
    ns_db.write_selection_file(base/'selections', 'abandoned-start', json.loads(sys.argv[2]))
    print('published', flush=True)
    time.sleep(30)
'''
        with open(self.root / 'writer.log', 'w+') as output:
            worker = subprocess.Popen([sys.executable, '-c', script, str(self.cfg.base), json.dumps(chosen)],
                                      stdout=output, stderr=output)
            try:
                deadline = time.monotonic() + 10
                while True:
                    output.seek(0)
                    if 'published' in output.read():
                        break
                    self.assertIsNone(worker.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.02)
                path = self.cfg.base / 'selections' / 'abandoned-start.ids'
                with TestClient(create_app(self.cfg)) as restarted:
                    self.assertTrue(path.exists())
                    worker.kill()
                    worker.wait(timeout=5)
                    response = restarted.post('/api/v1/jobs/start', json=body)
                    self.assertEqual(response.status_code, 202, response.text)
                    self.assertEqual(self.wait_for(response.json()['id'])['status'], 'Completed')
                    self.assertEqual(restarted.post('/api/v1/jobs/start', json=body).json()['id'],
                                     response.json()['id'])
                    self.assertFalse(path.exists())
                    self.assertEqual(len(restarted.get('/api/v1/runs').json()['runs']), 2)
            finally:
                if worker.poll() is None:
                    worker.kill()
                    worker.wait(timeout=5)

    def test_startup_reclaims_only_abandoned_selection_names(self):
        self.create_catalog()
        folder = self.cfg.base / 'selections'
        final = ns_db.write_selection_file(folder, 'abandoned', [1])
        temporary = folder / '.interrupted.ids.tmp'
        temporary.write_bytes(b'partial write')
        unrelated = folder / 'notes.ids.keep'
        unrelated.write_text('leave this alone')
        directory = folder / 'directory.ids'
        directory.mkdir()
        link = folder / 'link.ids'
        link.symlink_to(unrelated)
        JobRunner(self.cfg)
        self.assertFalse(final.exists())
        self.assertFalse(temporary.exists())
        self.assertEqual(unrelated.read_text(), 'leave this alone')
        self.assertTrue(directory.is_dir())
        self.assertTrue(link.is_symlink())
