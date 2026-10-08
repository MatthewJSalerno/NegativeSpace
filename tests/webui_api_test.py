"""The web API against a real engine and a real catalog (webui-spec 5-6).

Jobs run the actual engine (python -m engine) as a child process, as they do in production, so
these tests cover the request-to-run handshake, the lock, cancellation and the
derived outcome together rather than each against a stub.

    docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app -w /app \\
      negativespace python3 -m unittest discover -s tests -p webui_api_test.py -v
"""
import contextlib
import fcntl
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from engine import ns_db  # noqa: E402
from webui.app import create_app  # noqa: E402
from webui.config import ENGINE_CWD, Config  # noqa: E402


def make_photo(path: Path, seed: str, size=(64, 48), mtime=None, exif=None):
    """A small, valid JPEG whose pixels depend on `seed`; the same seed gives the
    same bytes, so two calls make an exact duplicate. `exif` maps tag ids to values;
    36867, 36868 and the offset tags 36881-36882 go in the Exif sub-IFD."""
    path.parent.mkdir(parents=True, exist_ok=True)
    value = sum(seed.encode()) % 256
    extra = {}
    if exif:
        e = Image.Exif()
        for tag, v in exif.items():
            (e.get_ifd(0x8769) if tag >= 0x8000 else e)[tag] = v
        extra["exif"] = e
    Image.new("RGB", size, (value, 255 - value, (value * 7) % 256)).save(path, "JPEG", quality=90, **extra)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class ApiCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ns-webui-"))
        destination = Path(os.environ['NS_TEST_DESTINATION_ROOT']) / self.root.name if os.environ.get('NS_TEST_DESTINATION_ROOT') else self.root / 'dest'
        destination.mkdir(parents=True)
        for name in ("src", "appdata", "cache", "backups"):
            (self.root / name).mkdir()
        self.cfg = Config(base=self.root / "appdata", source=self.root / "src", dest=destination,
                          cache=self.root / "cache", backups=self.root / "backups")
        self.client = TestClient(create_app(self.cfg))

    def tearDown(self):
        self.client.close()
        if os.environ.get('NS_TEST_KEEP') != '1':
            shutil.rmtree(self.root, ignore_errors=True)
            if self.cfg.dest.parent != self.root:
                shutil.rmtree(self.cfg.dest, ignore_errors=True)

    def create_catalog(self):
        self.assertEqual(self.client.post("/api/v1/catalog").status_code, 201)

    def wait_for(self, run_id, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = self.client.get(f"/api/v1/runs/{run_id}").json()
            if run["status"] not in ns_db.ACTIVE_RUN_STATUSES and not self.app_jobs().engine_busy():
                return run
            time.sleep(0.1)
        self.fail(f"run {run_id} did not finish")

    def app_jobs(self):
        return self.client.app.state.jobs

    def start(self, **body):
        response = self.client.post("/api/v1/jobs/start", json=body)
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["id"]

    @contextlib.contextmanager
    def engine_lock_held(self):
        with open(self.cfg.lock_path, "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield


class FirstRunAndSettings(ApiCase):
    def test_a_missing_catalog_is_reported_and_created_only_on_request(self):
        status = self.client.get("/api/v1/status").json()
        self.assertEqual((status["state"], status["application_data"]), ("missing", str(self.cfg.base)))
        self.assertFalse(self.cfg.db_path.exists(), "asking for status created a catalog")
        refused = self.client.post("/api/v1/jobs/start", json={"mode": "index"})
        self.assertEqual((refused.status_code, refused.json()["error"]), (409, "catalog_missing"))

        self.create_catalog()
        self.assertEqual(self.client.get("/api/v1/status").json()["state"], "ok")
        again = self.client.post("/api/v1/catalog")
        self.assertEqual((again.status_code, again.json()["error"]), (409, "catalog_exists"))
        empty = self.client.post("/api/v1/jobs/start", json={"mode": "move"})
        self.assertEqual((empty.status_code, empty.json()["error"]), (409, "catalog_empty"))

    def test_status_says_which_build_is_running(self):
        release = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
        os.environ.update(NS_BRANCH="feat/example", NS_COMMIT="abc1234")
        try:
            version = self.client.get("/api/v1/status").json()["version"]
        finally:
            del os.environ["NS_BRANCH"], os.environ["NS_COMMIT"]
        self.assertEqual(version, {"release": release, "branch": "feat/example", "commit": "abc1234"})
        self.assertEqual(self.client.get("/api/v1/status").json()["version"]["commit"], None,
                         "an image built without the commit says so, rather than inventing one")

    def test_an_incompatible_catalog_is_left_alone_and_explained(self):
        self.cfg.db_path.parent.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn:
            conn.execute("CREATE TABLE something_else (x)")
        before = self.cfg.db_path.read_bytes()
        status = self.client.get("/api/v1/status").json()
        self.assertEqual(status["state"], "incompatible")
        self.assertEqual(self.client.get("/api/v1/photos").status_code, 409)
        self.assertEqual(self.cfg.db_path.read_bytes(), before, "an incompatible catalog was modified")

    def test_settings_default_save_with_revisions_and_refuse_a_stale_write(self):
        self.create_catalog()
        got = self.client.get("/api/v1/settings").json()
        self.assertEqual(got["workers"]["revision"], 0)
        self.assertEqual(got["workers"]["value"], got["workers"]["detected"])
        self.assertIn(".jpg", got["exts"]["value"])

        saved = self.client.put("/api/v1/settings", json={"values": {"workers": 2}, "revisions": {"workers": 0}})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual((saved.json()["workers"]["value"], saved.json()["workers"]["revision"]), (2, 1))
        stale = self.client.put("/api/v1/settings", json={"values": {"workers": 3}, "revisions": {"workers": 0}})
        self.assertEqual((stale.status_code, stale.json()["error"]), (409, "settings_changed"))
        bad = self.client.put("/api/v1/settings", json={"values": {"workers": 0}, "revisions": {"workers": 1}})
        self.assertEqual(bad.status_code, 400)
        # The Rejects reminder's limits: on by default, null for off, never part of a job.
        self.assertEqual((got["rejects_reminder_bytes"]["value"], got["rejects_reminder_days"]["value"]),
                         (1_000_000_000, 30))
        off = self.client.put("/api/v1/settings", json={"values": {"rejects_reminder_days": None},
                                                        "revisions": {"rejects_reminder_days": 0}})
        self.assertEqual(off.status_code, 200, off.text)
        self.assertIsNone(off.json()["rejects_reminder_days"]["value"])
        self.assertEqual(self.client.get("/api/v1/status").json()["rejects"]["reminder"]["days_limit"], None)
        for bad_limit in (0, -1, 1.5, "1"):
            bad = self.client.put("/api/v1/settings", json={"values": {"rejects_reminder_bytes": bad_limit},
                                                            "revisions": {"rejects_reminder_bytes": 0}})
            self.assertEqual(bad.status_code, 400, bad_limit)
        make_photo(self.cfg.source / "reminder.jpg", "reminder")
        run = self.wait_for(self.start(mode="index"))
        with sqlite3.connect(self.cfg.db_path) as conn:
            config = json.loads(conn.execute("SELECT effective_config_json FROM run_configs WHERE run_id = ?",
                                             (run["id"],)).fetchone()[0])
        self.assertFalse({"rejects_reminder_bytes", "rejects_reminder_days"} & set(config),
                         "the reminder's limits reached a job's configuration")
        mov = self.client.post("/api/v1/settings/validate-extension", json={"extension": "MOV"}).json()
        self.assertFalse(mov["supported"])
        self.assertTrue(mov["warning"])


class RejectsReminder(ApiCase):
    def test_the_reminder_shows_past_either_limit_and_each_switches_off(self):
        from datetime import datetime, timedelta, timezone
        from webui import catalog
        self.create_catalog()
        now = datetime(2026, 10, 2, tzinfo=timezone.utc)
        def reminder(photos, size, days_old):
            summary = {"photos": photos, "bytes": size,
                       "oldest_rejected_at": (now - timedelta(days=days_old)).isoformat() if photos else None}
            with catalog.connect(self.cfg.db_path) as conn:
                r = catalog.rejects_reminder(conn, summary, now)
            return r["over_size"], r["over_age"]
        self.assertEqual(reminder(0, 0, 0), (False, False))
        self.assertEqual(reminder(3, 999_999_999, 29), (False, False))
        self.assertEqual(reminder(3, 1_000_000_000, 29), (True, False))
        self.assertEqual(reminder(3, 10, 30), (False, True))
        self.assertEqual(reminder(3, 2_000_000_000, 400), (True, True))
        self.client.put("/api/v1/settings", json={"values": {"rejects_reminder_bytes": None, "rejects_reminder_days": None},
                                                  "revisions": {"rejects_reminder_bytes": 0, "rejects_reminder_days": 0}})
        self.assertEqual(reminder(3, 2_000_000_000, 400), (False, False), "a limit switched off still reminds")


class RequestIdentity(ApiCase):
    def test_replay_and_lookup_keep_the_original_run_after_newer_work_and_restart(self):
        self.create_catalog()
        make_photo(self.cfg.source / 'sample.jpg', 'identity')
        body = {"mode":"index", "request_id":"browser-original"}
        original = self.wait_for(self.start(**body))
        newer = self.wait_for(self.start(mode="index", request_id="browser-other-tab"))
        self.assertNotEqual(original['id'], newer['id'])
        self.client.close()
        self.client = TestClient(create_app(self.cfg))
        lookup = self.client.get('/api/v1/job-requests/browser-original').json()
        self.assertEqual((lookup['state'], lookup['run']['id']), ('accepted', original['id']))
        with self.engine_lock_held(), patch('webui.jobs.subprocess.Popen') as spawn:
            replay = self.client.post('/api/v1/jobs/start', json=body)
            self.assertEqual((replay.status_code, replay.json()['id']), (202, original['id']))
            spawn.assert_not_called()
        conflict = self.client.post('/api/v1/jobs/start', json={**body, 'mode':'copy'})
        self.assertEqual((conflict.status_code, conflict.json()['error']), (409, 'request_conflict'))
        self.assertEqual(len(self.client.get('/api/v1/runs').json()['runs']), 2)

    def test_unknown_request_can_be_retried_with_same_id(self):
        self.create_catalog()
        make_photo(self.cfg.source / 'sample.jpg', 'retry')
        body = {'mode':'index', 'request_id':'not-yet-accepted'}
        self.assertEqual(self.client.get('/api/v1/job-requests/not-yet-accepted').json(), {'state':'unknown', 'run':None})
        with self.engine_lock_held():
            self.assertEqual(self.client.post('/api/v1/jobs/start', json=body).status_code, 409)
        run = self.wait_for(self.start(**body))
        self.assertEqual(self.client.get('/api/v1/job-requests/not-yet-accepted').json()['run']['id'], run['id'])

    def test_concurrent_same_request_accepts_one_run(self):
        from concurrent.futures import ThreadPoolExecutor
        self.create_catalog()
        make_photo(self.cfg.source / 'sample.jpg', 'concurrent')
        body = {'mode':'index', 'request_id':'same-delivery'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: self.client.post('/api/v1/jobs/start', json=body), range(2)))
        self.assertEqual([r.status_code for r in replies], [202, 202])
        self.assertEqual(replies[0].json()['id'], replies[1].json()['id'])
        self.wait_for(replies[0].json()['id'])
        self.assertEqual(len(self.client.get('/api/v1/runs').json()['runs']), 1)

    def test_invalid_request_ids_never_spawn(self):
        self.create_catalog()
        with patch('webui.jobs.subprocess.Popen') as spawn:
            for value in ('', 'space here', 'x'*129, [], 7, True):
                self.assertEqual(self.client.post('/api/v1/jobs/start', json={'mode':'index', 'request_id':value}).status_code, 400)
            spawn.assert_not_called()

    def test_conflicting_acceptance_between_lookup_and_launch_is_not_returned(self):
        from webui import outcomes
        self.create_catalog()
        make_photo(self.cfg.source / 'sample.jpg', 'late-acceptance')
        self.wait_for(self.start(mode='index', request_id='late-binding'))
        original = outcomes.request_record
        calls = []
        def appearing_record(*args):
            calls.append(1)
            return None if len(calls) == 1 else original(*args)
        # Simulate another acceptor winning between the initial check and spawn.
        with patch('webui.jobs.outcomes.request_record', side_effect=appearing_record), patch('webui.jobs.subprocess.Popen'):
            response = self.client.post('/api/v1/jobs/start', json={'mode':'copy', 'request_id':'late-binding'})
        self.assertEqual((response.status_code, response.json()['error']), (409, 'request_conflict'))
        self.assertGreaterEqual(len(calls), 2)


class SafetyQuestions(ApiCase):
    def answer(self, run, question, answer):
        body = {"question":question, "answer":answer, "request_id":f"answer-{run['id']}-{answer}"}
        response = self.client.post(f"/api/v1/runs/{run['id']}/answer", json=body)
        self.assertEqual(response.status_code, 202, response.text)
        result = self.wait_for(response.json()["id"])
        with patch('webui.jobs.subprocess.Popen') as spawn:
            replay = self.client.post(f"/api/v1/runs/{run['id']}/answer", json=body)
            self.assertEqual((replay.status_code, replay.json()['id']), (202, result['id']))
            spawn.assert_not_called()
        return result

    def test_empty_source_retry_and_explicit_confirmation(self):
        self.create_catalog()
        photo = self.cfg.source / "sample.jpg"
        make_photo(photo, "empty-question")
        self.wait_for(self.start(mode="index"))
        held = self.root / "held.jpg"
        photo.rename(held)
        refused = self.wait_for(self.start(mode="index"))
        self.assertEqual(refused["questions"], ["source_empty"])
        # Retry without reconnecting asks again, rather than silently confirming.
        again = self.answer(refused, "source_empty", "retry")
        self.assertEqual(again["questions"], ["source_empty"])
        held.rename(photo)
        restored = self.answer(again, "source_empty", "retry")
        self.assertEqual(restored["questions"], [])
        photo.rename(held)
        refused = self.wait_for(self.start(mode="index"))
        confirmed = self.answer(refused, "source_empty", "confirm_empty")
        self.assertEqual(confirmed["questions"], [])
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT status FROM photos").fetchone()[0], "Failed")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attention_issues WHERE resolved_at IS NULL").fetchone()[0], 0)
        self.assertTrue(held.is_file())

    def network_case(self, scope):
        # Real engine and filesystem actions; inject only network-type detection.
        wrapper = self.root / "network_engine.py"
        wrapper.write_text("import sys\n"
            f"sys.path.insert(0, {str(ENGINE_CWD)!r})\n"
            "from engine import cli, transfer\n"
            "transfer.filesystem_type=lambda path: 'nfs'\nif __name__ == '__main__': cli.main()\n")
        from dataclasses import replace
        self.client.close()
        self.cfg = replace(self.cfg, engine=wrapper)
        self.client = TestClient(create_app(self.cfg))
        self.create_catalog()
        chosen = self.cfg.source / "chosen" / "sample.jpg"
        other = self.cfg.source / "other.jpg"
        make_photo(chosen, "chosen")
        make_photo(other, "other")
        self.wait_for(self.start(mode="index"))
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            photo_id = conn.execute("SELECT id FROM photos WHERE source_path=?", (str(chosen),)).fetchone()[0]
        targeting = {"file_ids":[photo_id]} if scope == "ids" else {"source_subdir":"chosen"} if scope == "folder" else {}
        recorded = ({"selection": 1, "sha256": ns_db.selection_digest([photo_id])} if scope == "ids"
                    else targeting or None)
        refused = self.wait_for(self.start(mode="move", **targeting))
        self.assertEqual(refused["questions"], ["network_destination"])
        self.assertTrue(chosen.exists() and other.exists())
        self.assertEqual(list(self.cfg.dest.rglob('*.jpg')), [])
        copied = self.answer(refused, "network_destination", "copy")
        self.assertEqual(copied["mode"], "COPY")
        self.assertEqual(copied["targeting"], recorded)
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            self.assertEqual([r[0] for r in conn.execute("SELECT photo_id FROM run_selections WHERE run_id = ?",
                                                         (copied["id"],))], [photo_id] if scope == "ids" else [],
                             "the answer's job did not carry the original selection")
        self.assertTrue(chosen.exists() and other.exists())
        self.assertEqual(copied["questions"], [])
        # A new Move must ask again; permission is not global.
        refused = self.wait_for(self.start(mode="move", **targeting))
        self.assertEqual(refused["questions"], ["network_destination"])
        # Scope overrides, arbitrary flags and malformed answers cannot launch.
        answer_url = f"/api/v1/runs/{refused['id']}/answer"
        answer_body = {"question":"network_destination", "answer":"confirm_move"}
        with self.engine_lock_held():
            self.assertEqual(self.client.post(answer_url, json=answer_body).status_code, 409)
        runner = self.app_jobs()
        runner.cfg = replace(self.cfg, dest=self.root / "different-destination")
        try:
            response = self.client.post(answer_url, json=answer_body)
            self.assertEqual((response.status_code, response.json()["error"]), (409, "scope_changed"))
        finally:
            runner.cfg = self.cfg
        for body in ({"question":"network_destination", "answer":"confirm_move", "file_ids":[photo_id]},
                     {"question":[], "answer":"confirm_move"},
                     {"question":"network_destination", "answer":True}):
            self.assertEqual(self.client.post(f"/api/v1/runs/{refused['id']}/answer", json=body).status_code, 400)
        moved = self.answer(refused, "network_destination", "confirm_move")
        self.assertEqual(moved["targeting"], recorded)
        self.assertEqual(moved["outcome"]["verdict"], "success")
        self.assertFalse(chosen.exists())
        self.assertEqual(other.exists(), scope != "all")
        self.assertEqual(moved["questions"], [])
        self.assertEqual(self.client.post(f"/api/v1/runs/{refused['id']}/answer",
            json={"question":"network_destination", "answer":"confirm_move"}).status_code, 409)

    def test_network_answers_preserve_selected_ids(self):
        self.network_case("ids")

    def test_network_answers_preserve_folder_scope(self):
        self.network_case("folder")

    def test_network_answers_preserve_whole_source(self):
        self.network_case("all")

    def test_start_rejects_unsupported_confirmation_fields(self):
        self.create_catalog()
        with patch("webui.jobs.subprocess.Popen") as spawn:
            for key in ("confirm_source_empty", "confirm_network_destination", "unexpected"):
                self.assertEqual(self.client.post('/api/v1/jobs/start', json={"mode":"index", key:True}).status_code, 400)
            for run_id in (0, -1, 2**63):
                self.assertEqual(self.client.post(f'/api/v1/runs/{run_id}/answer',
                    json={"question":"source_empty", "answer":"confirm_empty"}).status_code, 400)
            spawn.assert_not_called()


class TransferScanFailures(ApiCase):
    def check_scan_failures(self, mode, all_failed):
        self.create_catalog()
        for name in ("first", "second"):
            make_photo(self.cfg.source / f"{name}.jpg", name)
        self.wait_for(self.start(mode="index"))
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM photos ORDER BY id")]
        (self.cfg.source / "first.jpg").write_text("not an image anymore")
        if all_failed:
            (self.cfg.source / "second.jpg").unlink()
        run = self.wait_for(self.start(mode=mode, file_ids=ids))
        outcome = run["outcome"]
        self.assertEqual((outcome["verdict"], outcome["succeeded"], outcome["failed"], outcome["total"]),
                         ("none_succeeded", 0, 2, 2) if all_failed else ("partial", 1, 1, 2))
        self.assertEqual(sum(outcome["failure_reasons"].values()), 2 if all_failed else 1)
        failures = self.client.get("/api/v1/operations", params={"run":run["id"], "status":"Failed"}).json()
        self.assertEqual(failures["total"], outcome["failed"])
        self.assertEqual(len(list(self.cfg.dest.rglob("*.jpg"))), 0 if all_failed else 1)

    def test_copy_mixed_prerequisite_failures(self):
        self.check_scan_failures("copy", False)

    def test_copy_all_prerequisite_failures(self):
        self.check_scan_failures("copy", True)

    def test_move_mixed_prerequisite_failures(self):
        self.check_scan_failures("move", False)

    def test_move_all_prerequisite_failures(self):
        self.check_scan_failures("move", True)


class JobsAndCatalog(ApiCase):
    def index_library(self):
        make_photo(self.cfg.source / "trip" / "IMG_0001.jpg", "a", mtime=1_600_000_000)
        make_photo(self.cfg.source / "trip" / "Beach Sunset.jpg", "a", mtime=1_600_000_000)
        make_photo(self.cfg.source / "IMG_0002.jpg", "b", mtime=1_700_000_000)
        self.create_catalog()
        return self.wait_for(self.start(mode="index"))

    def test_similarity_recovery_uses_destination_originals_and_resumes_comparisons(self):
        self.index_library()
        self.wait_for(self.start(mode='copy'))
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            photo, digest, dest, old_hash = conn.execute("SELECT p.id,p.sha1_hash,p.dest_path,c.phash FROM photos p JOIN contents c ON c.digest=p.sha1_hash WHERE p.status='Copied' ORDER BY p.id LIMIT 1").fetchone()
            before = Path(dest).read_bytes()
            with ns_db.transaction(conn):
                conn.execute("UPDATE contents SET phash=NULL,phash_state='error' WHERE digest=?", (digest,))
                conn.execute('DELETE FROM similarity_hashes')
                conn.execute('DELETE FROM content_similarity')
        # After Move, the original source may no longer exist. Recovery needs only dest.
        for source in self.cfg.source.rglob('*.jpg'):
            source.unlink()
        report = self.client.get(f'/api/v1/similar/recovery?photo_id={photo}').json()
        self.assertEqual((report['total'],report['retryable']), (1,1))
        self.assertEqual(report['items'][0]['reason'], 'decode_failed')
        body = {'scope':'missing','photo_id':photo,'request_id':'recover-one'}
        response = self.client.post('/api/v1/similar/recovery',json=body)
        self.assertEqual(response.status_code,202,response.text)
        run = self.wait_for(response.json()['id'])
        self.assertEqual((run['mode'],run['status']), ('SIMILARITY','Completed'))
        self.assertEqual(self.client.get('/api/v1/similar/recovery').json()['total'],0)
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            self.assertEqual(conn.execute('SELECT phash,phash_state FROM contents WHERE digest=?',(digest,)).fetchone(),(old_hash,'ok'))
            self.assertEqual(conn.execute('SELECT dirty FROM similarity_count_state').fetchone(),(0,))
        self.assertEqual(Path(dest).read_bytes(),before)
        self.assertEqual(self.client.post('/api/v1/similar/recovery',json=body).json()['id'],run['id'])
        self.assertEqual(self.client.post('/api/v1/similar/recovery',json={**body,'scope':'comparisons','photo_id':None}).status_code,409)

    def test_similarity_recovery_reports_changed_and_missing_destination_without_edits(self):
        self.index_library()
        self.wait_for(self.start(mode='copy'))
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            photos = conn.execute("SELECT id,sha1_hash,dest_path FROM photos WHERE status='Copied' ORDER BY id").fetchall()
            with ns_db.transaction(conn):
                conn.execute("UPDATE contents SET phash=NULL,phash_state=NULL")
        Path(photos[0][2]).write_bytes(b'changed destination')
        Path(photos[1][2]).unlink()
        result = self.client.post('/api/v1/similar/recovery',json={'scope':'missing'})
        self.assertEqual(result.status_code,202,result.text)
        run_id = result.json()['id']
        self.wait_for(run_id)
        failures = self.client.get(f'/api/v1/operations?run={run_id}&status=Failed').json()
        self.assertEqual(failures['total'],2)
        messages = ' '.join(op['error_message'] for op in failures['items'])
        self.assertIn('[repair_missing]',messages)
        self.assertIn('[repair_changed]',messages)
        self.assertTrue(all(op['photo_id'] and op['dest_path'] for op in failures['items']))
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            self.assertEqual({r[0] for r in conn.execute("SELECT status FROM photos WHERE id IN (?,?)", (photos[0][0],photos[1][0]))},{'Copied'})
        run = self.wait_for(result.json()['id'])
        self.assertEqual(run['outcome']['failed'],2)
        report = self.client.get('/api/v1/similar/recovery').json()
        self.assertEqual({item['reason'] for item in report['items']},{'changed','missing'})
        self.assertEqual(report['retryable'],2)
        self.assertEqual(report['generatable'],0)
        self.assertEqual({item['action'] for item in report['items']},{'recheck'})
        self.assertEqual(Path(photos[0][2]).read_bytes(),b'changed destination')
        self.assertFalse(Path(photos[1][2]).exists())
        for body in ({'scope':'bad'}, {'scope':'comparisons','photo_id':1}, {'scope':'missing','photo_id':True}, {'scope':'missing','extra':1}):
            self.assertEqual(self.client.post('/api/v1/similar/recovery',json=body).status_code,400)
        self.assertEqual(self.client.get('/api/v1/similar/recovery?page=0').status_code,422)
        with self.engine_lock_held():
            self.assertEqual(self.client.post('/api/v1/similar/recovery',json={'scope':'missing'}).status_code,409)

    def test_resume_similarity_comparisons_does_not_read_photos(self):
        self.index_library()
        self.wait_for(self.start(mode='copy'))
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            with ns_db.transaction(conn):
                conn.execute('DELETE FROM similarity_hashes')
                conn.execute('DELETE FROM content_similarity')
            before = conn.execute('SELECT phash,phash_state FROM contents').fetchall()
        for dest in self.cfg.dest.rglob('*.jpg'):
            dest.unlink()
        result = self.client.post('/api/v1/similar/recovery',json={'scope':'comparisons'})
        self.assertEqual(result.status_code,202,result.text)
        self.assertEqual(self.wait_for(result.json()['id'])['status'],'Completed')
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            self.assertEqual(conn.execute('SELECT phash,phash_state FROM contents').fetchall(),before)
        self.assertEqual(self.client.get('/api/v1/similar/recovery').json()['state']['pending'],0)

    def test_engine_publishes_count_cache_after_index_and_copy(self):
        self.index_library()
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            self.assertEqual(conn.execute('SELECT dirty FROM similarity_count_state').fetchone(), (0,))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM similarity_count_cache').fetchone(), (0,))
        run = self.wait_for(self.start(mode='copy'))
        self.assertEqual(run['status'], 'Completed')
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            self.assertEqual(conn.execute('SELECT dirty FROM similarity_count_state').fetchone(), (0,))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM similarity_count_cache').fetchone(), (2,))

    def test_an_index_through_the_api_reports_a_derived_outcome_and_fills_the_gallery(self):
        run = self.index_library()
        self.assertEqual((run["mode"], run["status"], run["outcome"]["verdict"]), ("INDEX", "Completed", "success"))
        self.assertEqual(run["outcome"]["counts"], {"indexed": 2, "duplicates": 1})

        page = self.client.get("/api/v1/photos").json()
        self.assertEqual((page["total"], page["counts"]["organized"], page["counts"]["unorganized"]), (2, 0, 2))
        self.assertEqual([i["date_taken"][:4] for i in page["items"]], ["2023", "2020"], "not newest first")
        self.assertEqual(sorted(i["duplicates"] for i in page["items"]), [0, 1])
        matching = self.client.get('/api/v1/similar').json()
        self.assertEqual(matching['state']['pending'], 0, 'Index did not complete its comparisons')
        self.assertEqual((matching['total'], matching['state']['photos']), (0, 0))
        diagnostics = self.client.get('/api/v1/similar/diagnostics').json()
        self.assertEqual(diagnostics['last_comparison']['run_id'], run['id'])
        self.assertGreaterEqual(diagnostics['last_comparison']['elapsed_seconds'], 0)
        self.assertEqual(self.client.get('/api/v1/similar?mode=exact').json()['total'], 0)

        timeline = self.client.get("/api/v1/photos/timeline").json()
        self.assertEqual(timeline, {"months": [{"month": "2023-11", "count": 1}, {"month": "2020-09", "count": 1}],
                                    "undated": 0}, "the per-month counts do not match the gallery")

        by_removed_name = self.client.get("/api/v1/photos", params={"q": "sunset"}).json()
        self.assertEqual(by_removed_name["total"], 1, "a duplicate's name did not find its photo")
        self.assertEqual(self.client.get("/api/v1/photos", params={"q": "trip"}).json()["total"], 0,
                         "a folder name matched as a filename")

        photo = page["items"][1]["id"]
        grid = self.client.get(f"/api/v1/photos/{photo}/thumbnail")
        self.assertEqual((grid.status_code, grid.headers["content-type"]), (200, "image/jpeg"))
        preview = self.client.get(f"/api/v1/photos/{photo}/thumbnail", params={"size": "preview"})
        self.assertEqual(preview.status_code, 200, preview.text)
        detail = self.client.get(f"/api/v1/photos/{photo}/inspect").json()
        self.assertEqual((detail["date_source"], len(detail["duplicates"])), ("file_mtime", 1))
        self.assertEqual(detail["file_modified"], 1_600_000_000, "the file's first-scan mtime was not reported")
        self.assertNotIn("file_created", detail, "a creation date is not shown: it is the date of the last copy")
        self.assertTrue(detail["dest_path_is_projection"])
        self.assertEqual(self.client.get("/api/v1/photos/999999/inspect").status_code, 404)

    def test_a_copy_through_the_api_counts_the_requested_work_only(self):
        self.index_library()
        run = self.wait_for(self.start(mode="copy"))
        self.assertEqual(run["outcome"]["verdict"], "success")
        self.assertEqual(run["outcome"]["counts"], {"Copied": 2, "Skipped": 1},
                         "the Copy's scan was counted as its work")
        self.assertEqual(run["outcome"]["skip_reasons"], {"duplicate": 1},
                         "the skipped duplicate's reason was not recognised; did the engine's wording change?")
        organized = self.client.get("/api/v1/photos", params={"view": "organized"}).json()
        self.assertEqual(organized["total"], 2)
        self.assertEqual(self.client.get("/api/v1/similar").json()["total"], 2)
        again = self.wait_for(self.start(mode="copy"))
        self.assertEqual(again["outcome"]["verdict"], "no_change")

    def test_a_rejected_photo_leaves_every_view_and_shows_in_rejects_until_emptied(self):
        from webui import catalog
        self.index_library()
        self.wait_for(self.start(mode="copy"))
        listed = self.client.get("/api/v1/photos", params={"view": "all"}).json()["items"]
        twin = next(p for p in listed if p["duplicates"])
        single = next(p for p in listed if not p["duplicates"])
        self.assertEqual(self.client.post("/api/v1/jobs/start", json={"mode": "reject"}).status_code, 400,
                         "a reject of everything was accepted")

        run = self.wait_for(self.start(mode="reject", file_ids=[twin["id"], single["id"]]))
        self.assertEqual((run["mode"], run["outcome"]["verdict"], run["outcome"]["counts"]),
                         ("REJECT", "success", {"Rejected": 2}))
        for view in ("all", "organized", "unorganized", "suspicious"):
            shown = [p["id"] for p in self.client.get("/api/v1/photos", params={"view": view}).json()["items"]]
            self.assertFalse({twin["id"], single["id"]} & set(shown), f"a rejected photo is still in {view}")
        rejects = self.client.get("/api/v1/photos", params={"view": "rejects"}).json()
        self.assertEqual(sorted(p["id"] for p in rejects["items"]), sorted([twin["id"], single["id"]]))
        self.assertTrue(all(p["rejected_at"] for p in rejects["items"]), "a reject's time is missing")
        self.assertEqual((rejects["rejects"]["photos"], rejects["rejects"]["bytes"] > 0), (2, True))
        detail = self.client.get(f"/api/v1/photos/{single['id']}/inspect").json()
        self.assertIn("/rejects/", detail["dest_path"])
        self.assertFalse(detail["dest_path_is_projection"])
        status = self.client.get("/api/v1/status").json()
        self.assertEqual((status["rejected_with_source"], status["eligible"]["move"]), (2, 2),
                         "a Move's count leaves out rejected photos whose sources it would remove")

        chosen = self.client.post("/api/v1/photos/selection",
                                  json={"ids": [p["id"] for p in listed], "page_size": 1}).json()
        self.assertEqual(chosen["actions"], {"copy": 0, "move": len(listed), "reject": len(listed) - 2, "return": 2},
                         "the selection bar would offer Reject or Return for photos it cannot take")
        takes = self.client.post("/api/v1/photos/selection", json={"ids": [p["id"] for p in listed], "page_size": 1,
                                                                    "action": "reject"}).json()["takes"]
        self.assertEqual(len(takes), len(listed) - 2, "a Reject's review would hold photos it skips")
        self.assertEqual(self.client.post("/api/v1/photos/selection", json={"ids": [1], "action": "delete"}).status_code, 400)
        in_rejects = sorted(p["id"] for p in rejects["items"])
        self.assertEqual(chosen["in_rejects"], in_rejects, "the selection does not say which photos are in Rejects")
        self.assertEqual(self.client.get("/api/v1/photos/ids", params={"view": "rejects"}).json()["in_rejects"], in_rejects,
                         "Select all cannot keep a selection to one place")
        searched = self.client.get("/api/v1/photos", params={"view": "rejects", "q": "IMG_0002"}).json()
        self.assertEqual((searched["matches"]["rejects"], searched["matches"]["all"], searched["matches"]["undated"]),
                         (1, 0, 1), "the view buttons' counts do not follow the search")

        again = self.wait_for(self.start(mode="copy"))
        self.assertEqual(again["outcome"]["skip_reasons"], {"already_rejected": 1},
                         "the Copy did not say the duplicate was already rejected")

        back = self.wait_for(self.start(mode="return", file_ids=[single["id"]]))
        self.assertEqual((back["mode"], back["outcome"]["counts"]), ("RETURN", {"Returned": 1}))
        organized = [p["id"] for p in self.client.get("/api/v1/photos", params={"view": "organized"}).json()["items"]]
        self.assertIn(single["id"], organized, "a returned photo did not come back to the library")

        # Emptied outside the app: gone from the view at once, before any job records it.
        old, catalog.REJECTS_LISTING_SECONDS = catalog.REJECTS_LISTING_SECONDS, 0
        try:
            emptied = self.client.get(f"/api/v1/photos/{twin['id']}/inspect").json()
            Path(emptied["dest_path"]).unlink()
            rejects = self.client.get("/api/v1/photos", params={"view": "rejects"}).json()
            self.assertEqual((rejects["total"], rejects["rejects"]["photos"]), (0, 0),
                             "a photo emptied from Rejects is still shown there")
            # Counted as emptied at once too, on Stats and in the status every page reads.
            for figures in (self.client.get("/api/v1/status").json()["rejects"],
                            self.client.get("/api/v1/stats").json()["rejects"]):
                self.assertEqual((figures["photos"], figures["emptied"]["photos"]), (0, 1))
                self.assertEqual(figures["emptied"]["bytes"], emptied["file_size"])
        finally:
            catalog.REJECTS_LISTING_SECONDS = old

    def test_a_photos_lineage_joins_its_files_copies_duplicates_and_operations(self):
        self.index_library()                  # IMG_0001 and "Beach Sunset" share content
        self.wait_for(self.start(mode="copy"))
        anchor = next(i for i in self.client.get("/api/v1/photos").json()["items"] if i["duplicates"])
        tree = self.client.get(f"/api/v1/photos/{anchor['id']}/lineage").json()
        self.assertEqual(len(tree["photos"]), 2, "the duplicate belongs in the tree")
        sources = [f for f in tree["files"] if f["origin_kind"] == "indexed"]
        copies = [f for f in tree["files"] if f["origin_kind"] == "copy"]
        self.assertEqual((len(sources), len(copies)), (2, 1))
        (copy,) = copies
        own = next(f for f in sources if f["photo_id"] == anchor["id"])
        self.assertEqual((copy["origin_file_id"], copy["role"], copy["presence"]), (own["file_id"], "destination", "present"))
        self.assertEqual(own["origin_file_id"], own["file_id"], "an indexed file is its own origin")
        self.assertTrue(all(f["matches"] for f in tree["files"]), "every file here holds the same content")
        copied = next(op for op in tree["operations"] if op["status"] == "Copied")
        self.assertEqual({(x["file_id"], x["role"]) for x in copied["files"]},
                         {(own["file_id"], "source"), (copy["file_id"], "destination")})
        self.assertEqual(self.client.get("/api/v1/photos/99999/lineage").status_code, 404)

    def test_repeated_empty_source_refusals_do_not_refresh_coverage(self):
        photo = self.cfg.source / "photo.jpg"
        make_photo(photo, "coverage")
        self.create_catalog()
        initial = self.wait_for(self.start(mode="index"))
        baseline = self.client.get("/api/v1/stats").json()["duplicates"]["coverage"]
        hidden = photo.with_suffix(".hold")
        photo.rename(hidden)
        refused = []
        for attempt in range(2):
            run = self.wait_for(self.start(mode="index"))
            refused.append(run["id"])
            with self.subTest(attempt=attempt):
                coverage = self.client.get("/api/v1/stats").json()["duplicates"]["coverage"]
                self.assertEqual(coverage["established_by_run"], initial["id"])
                self.assertEqual(coverage["last_complete_scan"], baseline["last_complete_scan"])
                self.assertEqual(coverage["scans_with_issues_since"], attempt + 1)
                self.assertEqual(coverage["run_ids_since"], refused)
                with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM operations WHERE run_id = ? "
                                                  "AND status = 'Failed' AND photo_id IS NULL",
                                                  (run["id"],)).fetchone()[0], 1)
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM attention_issues WHERE "
                                                  "category = 'source_root_empty' AND resolved_at IS NULL").fetchone()[0], 1)
                    self.assertEqual(conn.execute("SELECT status FROM photos").fetchone()[0], "Pending")
        hidden.rename(photo)
        restored = self.wait_for(self.start(mode="index"))
        coverage = self.client.get("/api/v1/stats").json()["duplicates"]["coverage"]
        self.assertEqual(coverage["established_by_run"], restored["id"])
        self.assertEqual((coverage["scans_with_issues_since"], coverage["run_ids_since"]), (0, []))
        with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attention_issues WHERE resolved_at IS NULL").fetchone()[0], 0)

    def test_photo_position_matches_gallery_sort_filters_and_selection(self):
        self.index_library()
        for sort in ("newest", "oldest", "largest", "smallest", "name"):
            for filters in ({}, {"q": "IMG"}, {"date": "2020"}, {"type": "jpg"},
                            {"folder": "."}, {"undated": True}, {"view": "organized"}):
                with self.subTest(sort=sort, filters=filters):
                    items = self.client.get("/api/v1/photos", params={"sort": sort, **filters}).json()["items"]
                    body_filters = { {"date": "dates", "type": "types", "folder": "folders"}.get(k, k):
                        [v] if k in ("date", "type", "folder") else v for k, v in filters.items() }
                    for index, photo in enumerate(items):
                        response = self.client.post("/api/v1/photos/position", json={
                            "photo_id": photo["id"], "sort": sort, "page_size": 1, **body_filters})
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(response.json(), {"position": index, "page": index + 1,
                            "previous_id": items[index - 1]["id"] if index else None,
                            "next_id": items[index + 1]["id"] if index + 1 < len(items) else None})
        ids = self.client.get("/api/v1/photos/ids").json()["ids"]
        hidden = self.client.post("/api/v1/photos/position", json={"photo_id": ids[0], "q": "no-match"})
        self.assertIsNone(hidden.json()["page"])
        selected = self.client.post("/api/v1/photos/position", json={"photo_id": ids[0], "ids": [ids[0]], "q": "no-match"})
        self.assertEqual(selected.json()["page"], 1)
        for body in ({"photo_id": True}, {"photo_id": ids[0], "page_size": 0},
                     {"photo_id": ids[0], "ids": [True]}, {"photo_id": ids[0], "ids": ["1"]},
                     {"photo_id": ids[0], "ids": [1.5]}, {"photo_id": ids[0], "ids": "1"}):
            self.assertEqual(self.client.post("/api/v1/photos/position", json=body).status_code, 422)
        for invalid in (0, -1):
            response = self.client.post("/api/v1/photos/position", json={"photo_id": ids[0], "ids": [invalid]})
            self.assertEqual((response.status_code, response.json()["error"]), (400, "invalid_request"))
        self.assertEqual(self.client.post("/api/v1/photos/position", json={"photo_id": ids[0], "sort": "invalid"}).status_code, 400)

    def test_photo_position_navigates_large_selections_across_pages(self):
        self.create_catalog()
        with sqlite3.connect(self.cfg.db_path) as conn:
            conn.executemany("INSERT INTO photos(id,source_path,status,file_size) VALUES(?,?,'Pending',?)",
                             [(i, str(self.cfg.source / f"photo-{i:04d}.jpg"), i)
                              for i in range(1, 2411)])
        chosen = list(range(1, 2411, 2))  # 1,205 selected photos, interleaved with unselected ones.
        missing = 2**63 - 1
        ids = list(reversed(chosen)) + [chosen[0], missing]
        for sort, ordered in (("name", chosen), ("largest", list(reversed(chosen)))):
            with self.subTest(sort=sort):
                pages = []
                for page in range(1, 22):
                    response = self.client.post("/api/v1/photos/selection", json={
                        "ids": ids, "sort": sort, "page": page, "page_size": 60})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["total"], len(chosen))
                    self.assertEqual(response.json()["missing"], [missing])
                    pages.extend(p["id"] for p in response.json()["items"])
                self.assertEqual(pages, ordered)
                # Both sides of page boundaries, the old cap, and the endpoints.
                for index in (0, 59, 60, 999, 1000, 1199, 1200, 1204):
                    response = self.client.post("/api/v1/photos/position", json={
                        "photo_id": ordered[index], "ids": ids, "sort": sort,
                        "page_size": 60, "view": "organized", "q": "no-match"})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json(), {
                        "position": index, "page": index // 60 + 1,
                        "previous_id": ordered[index - 1] if index else None,
                        "next_id": ordered[index + 1] if index + 1 < len(ordered) else None})
        for photo_id, selected in ((2, ids), (missing, ids), (chosen[0], [])):
            response = self.client.post("/api/v1/photos/position", json={"photo_id": photo_id, "ids": selected})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), dict.fromkeys(("position", "page", "previous_id", "next_id")))

    def test_stats_accept_numeric_camera_and_lens_metadata(self):
        self.index_library()
        for make, model, lens, camera, lens_name in (
            ("Example", 123, 50, "Example 123", "50"),
            (7, 0, 0, "7 0", "0"),
            (None, "Example", None, "Example", None),
        ):
            with self.subTest(make=make, model=model, lens=lens):
                with sqlite3.connect(self.cfg.db_path) as conn:
                    conn.execute("UPDATE photos SET metadata_json = json_set(metadata_json, "
                                 "'$.Make', ?, '$.Model', ?, '$.LensModel', ?)", (make, model, lens))
                response = self.client.get("/api/v1/stats")
                self.assertEqual(response.status_code, 200)
                library = response.json()["library"]
                self.assertEqual(library["cameras"], [{"name": camera, "photos": 2}])
                self.assertEqual(library["lenses"], [{"name": lens_name, "photos": 2}] if lens_name else [])

    def test_stats_count_the_library_its_dates_duplicates_and_work(self):
        self.index_library()                  # IMG_0001 + "Beach Sunset" (same content), IMG_0002
        before = self.client.get("/api/v1/stats").json()["duplicates"]
        self.assertEqual(before["saved_at_destination"], 0, "nothing is saved until the original is delivered")
        self.assertIsNotNone(before["coverage"]["last_complete_scan"])
        self.assertEqual((before["coverage"]["run_ids_since"], before["coverage"]["scans_with_issues_since"]), ([], 0))
        # A targeted Index covers only what it targeted: it never moves the coverage date.
        covering = before["coverage"]["established_by_run"]
        pid = self.client.get("/api/v1/photos").json()["items"][0]["id"]
        targeted = self.wait_for(self.start(mode="index", file_ids=[pid]))["id"]
        after = self.client.get("/api/v1/stats").json()["duplicates"]["coverage"]
        self.assertEqual((after["established_by_run"], after["run_ids_since"]), (covering, [targeted]))
        self.wait_for(self.start(mode="copy"))
        st = self.client.get("/api/v1/stats").json()
        lib = st["library"]
        self.assertEqual((lib["photos"], lib["organized"]), (2, 2), "two distinct photos, both copied")
        self.assertEqual(lib["formats"][0]["format"], "jpg")
        self.assertEqual(st["duplicates"]["extra_copies"], 1)
        self.assertEqual(st["duplicates"]["saved_at_destination"], st["duplicates"]["bytes"],
                         "once the original is copied, the duplicate was never written")
        self.assertGreater(st["duplicates"]["move_would_free"], 0, "the duplicate's source is still there")
        self.assertIsNone(st["duplicates"]["near_duplicates"], "not recorded yet: no figure is invented")
        self.assertEqual(sum(y["photos"] for y in st["dates"]["per_year"]) + st["dates"]["undated"], 2)
        self.assertEqual(st["activity"]["copied"], 2)
        self.assertGreater(st["activity"]["bytes_transferred"], 0)
        self.assertEqual(st["activity"]["failures"], {}, "nothing failed")
        self.assertIsNone(st["activity"]["exif_edits"])
        self.assertGreaterEqual(st["health"]["backups"], 1, "each job took a backup")
        self.assertGreater(st["health"]["catalog_bytes"], 0)

    def test_copy_all_and_move_all_are_counted_as_the_engine_selects_them(self):
        self.index_library()
        status = self.client.get("/api/v1/status").json()
        self.assertEqual((status["eligible"], status["copied"]), ({"copy": 2, "move": 2}, 0))
        self.wait_for(self.start(mode="copy"))
        # Searching narrows the gallery's counts, never these.
        self.client.get("/api/v1/photos", params={"q": "Beach"})
        status = self.client.get("/api/v1/status").json()
        self.assertEqual((status["eligible"], status["copied"]), ({"copy": 0, "move": 2}, 2),
                         "after a Copy, Move all still has every copied photo to finish")

    def test_the_date_tree_filters_and_select_all_takes_exactly_what_is_shown(self):
        self.index_library()                        # one photo dated 2020-09, one 2023-11
        photos = lambda **p: self.client.get("/api/v1/photos", params=p).json()
        self.assertEqual(photos()["total"], 2)
        only_2023 = photos(date=["2023"])
        self.assertEqual([i["date_taken"][:7] for i in only_2023["items"]], ["2023-11"])
        self.assertEqual((only_2023["counts"]["all"], only_2023["matches"]["all"]), (2, 1),
                         "the view buttons count the library; matches follow the filters")
        self.assertEqual(photos(date=["2020-09", "2023"])["total"], 2, "checked dates add up")
        self.assertEqual(photos(date=["none"])["total"], 0)
        self.assertEqual(self.client.get("/api/v1/photos", params={"date": "June"}).status_code, 400)
        # The tree's counts ignore the date filter, so an unticked month keeps its number;
        # the jump positions follow it.
        tree = self.client.get("/api/v1/photos/timeline").json()
        self.assertEqual([m["month"] for m in tree["months"]], ["2023-11", "2020-09"])
        jump = self.client.get("/api/v1/photos/timeline", params={"date": "2023"}).json()
        self.assertEqual([m["month"] for m in jump["months"]], ["2023-11"])

        ids = self.client.get("/api/v1/photos/ids", params={"date": "2020"}).json()
        self.assertEqual(ids["total"], 1)
        self.assertEqual(ids["ids"], [i["id"] for i in photos(date=["2020"])["items"]],
                         "Select all must take exactly the photos the filters show")

    def test_the_types_filter_lists_what_the_library_holds_and_narrows_like_dates(self):
        self.index_library()                                   # three .jpg, one a duplicate
        from PIL import Image
        Image.new("RGB", (40, 30), (1, 2, 3)).save(self.cfg.source / "scan.png", "PNG")
        self.wait_for(self.start(mode="index"))
        types = self.client.get("/api/v1/photos/types").json()["types"]
        self.assertEqual(types, [{"type": "jpg", "photos": 2}, {"type": "png", "photos": 1}],
                         "only the types the library holds, most first")
        only_png = self.client.get("/api/v1/photos", params={"type": "png"}).json()
        self.assertEqual([i["filename"] for i in only_png["items"]], ["scan.png"])
        self.assertEqual((only_png["counts"]["all"], only_png["matches"]["all"]), (3, 1),
                         "the view buttons count the library; matches follow the type filter")
        ids = self.client.get("/api/v1/photos/ids", params={"type": "jpg"}).json()
        self.assertEqual(ids["total"], 2, "Select all takes exactly the types shown")
        both = self.client.get("/api/v1/photos", params={"type": ["jpg", "png"], "date": "2023"}).json()
        self.assertEqual(both["total"], 1, "types and dates combine")
        self.assertEqual(self.client.get("/api/v1/photos", params={"type": ".jpg"}).status_code, 400)

    def test_the_folder_tree_counts_filters_and_moves_by_source_folder(self):
        # Folders a wildcard or a case-blind match would confuse, a chain to fold into one
        # row, and a file directly in the source folder.
        for rel, seed in [("Phone/2019/a.jpg", "a"), ("Phone/2019/b.jpg", "b"), ("Phone/2021/c.jpg", "c"),
                          ("Camera/Nikon/d.jpg", "d"), ("top.jpg", "top"), ("My_Photos/e.jpg", "e"),
                          ("MyXPhotos/f.jpg", "f"), ("album/g.jpg", "g"), ("Album/h.jpg", "h")]:
            make_photo(self.cfg.source / rel, seed)
        self.create_catalog()
        self.wait_for(self.start(mode="index"))
        tree = self.client.get("/api/v1/photos/folders").json()
        rows = {f["path"]: f for f in tree["folders"]}
        self.assertEqual([f["path"] for f in tree["folders"]],
                         ["Album", "album", "Camera/Nikon", "My_Photos", "MyXPhotos", "Phone"], "by name, any case")
        self.assertEqual(rows["Camera/Nikon"]["name"], "Camera / Nikon", "a chain of single folders is one row")
        self.assertEqual((rows["Phone"]["photos"], rows["Phone"]["eligible"]), (3, {"copy": 3, "move": 3}))
        self.assertEqual([(f["path"], f["photos"]) for f in rows["Phone"]["folders"]], [("Phone/2019", 2), ("Phone/2021", 1)])
        self.assertEqual((tree["top_files"]["photos"], tree["outside"]), (1, 0))

        def names(**params):
            return sorted(i["filename"] for i in self.client.get("/api/v1/photos", params=params).json()["items"])
        self.assertEqual(names(folder="My_Photos"), ["e.jpg"], "a literal folder, not a wildcard")
        self.assertEqual(names(folder="album"), ["g.jpg"], "a folder's letter case counts")
        self.assertEqual(names(folder=["Phone/2021", "Camera/Nikon"]), ["c.jpg", "d.jpg"], "several folders add up")
        self.assertEqual(names(folder="."), ["top.jpg"], "the files directly in the source folder")
        self.assertEqual(names(folder="Phone"), ["a.jpg", "b.jpg", "c.jpg"], "a folder takes its subfolders")
        self.assertEqual(self.client.get("/api/v1/photos/ids", params={"folder": "Phone"}).json()["total"], 3)
        self.assertEqual(self.client.get("/api/v1/photos/types", params={"folder": "Phone"}).json()["types"],
                         [{"type": "jpg", "photos": 3}])
        for bad in ("../elsewhere", "/data/source/Phone", ".."):
            self.assertEqual(self.client.get("/api/v1/photos", params={"folder": bad}).status_code, 400, bad)
        # Its counts follow a search.
        searched = self.client.get("/api/v1/photos/folders", params={"q": "a.jpg"})
        self.assertEqual(searched.status_code, 200, searched.text)
        self.assertEqual([(f["path"], f["photos"]) for f in searched.json()["folders"] if f["photos"]], [("Phone", 1)])
        # The tree ignores its own filter, and keeps a ticked folder listed at 0.
        kept = self.client.get("/api/v1/photos/folders", params={"folder": "Phone/2021", "type": "png"}).json()
        self.assertEqual([(f["path"], f["photos"]) for f in kept["folders"]], [("Phone", 0)])
        self.assertEqual([f["path"] for f in kept["folders"][0]["folders"]], ["Phone/2021"])

        # A folder's Move takes that folder only, however many photos it holds.
        self.wait_for(self.start(mode="move", source_subdir="Phone"))
        after = {f["path"]: f for f in self.client.get("/api/v1/photos/folders").json()["folders"]}
        self.assertEqual(after["Phone"]["eligible"], {"copy": 0, "move": 0})
        self.assertEqual(after["My_Photos"]["eligible"], {"copy": 1, "move": 1})
        statuses = {i["filename"]: i["status"] for i in self.client.get("/api/v1/photos", params={"page_size": 60}).json()["items"]}
        self.assertEqual({n for n, st in statuses.items() if st == "Completed"}, {"a.jpg", "b.jpg", "c.jpg"})

    def test_folder_jobs_preserve_literal_names_and_leave_siblings_untouched(self):
        cases = (("album ", "album"), (" album", "album"), (" ", "neighbor"),
                 ("outer / inner ", "outer / inner"), ("café_100% ", "café_100%"),
                 ("Album", "album"))
        fixtures = []
        for mode in ("copy", "move"):
            for number, (selected, sibling) in enumerate(cases):
                # Put leading/trailing spaces at the ends of the actual job argument,
                # too; a prefix would hide the leading-whitespace regression.
                target = selected if mode == "copy" else selected.replace("album", "collection").replace("Album", "Collection")
                other = sibling if mode == "copy" else sibling.replace("album", "collection")
                if number == 2:
                    target, other = (" ", "copy-neighbor") if mode == "copy" else ("  ", "move-neighbor")
                elif number not in (0, 1, 5):
                    target, other = mode + "/" + target, mode + "/" + other
                name = f"image-{mode}-{number}.jpg"
                path, neighbor = self.cfg.source / target / name, self.cfg.source / other / name
                make_photo(path, chr(33 + len(fixtures) * 2))
                make_photo(neighbor, chr(34 + len(fixtures) * 2))
                fixtures.append((mode, target, path, neighbor))
        self.create_catalog()
        self.wait_for(self.start(mode="index"))
        original = {p: p.read_bytes() for _, _, path, neighbor in fixtures for p in (path, neighbor)}
        removed = set()
        for mode, target, path, neighbor in fixtures:
            with self.subTest(mode=mode, folder=target):
                selected = self.client.get("/api/v1/photos", params={"folder": target}).json()
                self.assertEqual(selected["total"], 1)
                photo_id = selected["items"][0]["id"]
                run = self.wait_for(self.start(mode=mode, source_subdir=target))
                self.assertEqual(run["status"], "Completed")
                with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn:
                    touched = {row[0] for row in conn.execute(
                        "SELECT DISTINCT photo_id FROM operations WHERE run_id = ? AND photo_id IS NOT NULL",
                        (run["id"],))}
                    self.assertEqual(touched, {photo_id})
                    status, dest = conn.execute("SELECT status, dest_path FROM photos WHERE id = ?",
                                                (photo_id,)).fetchone()
                self.assertEqual(status, "Copied" if mode == "copy" else "Completed")
                self.assertEqual(Path(dest).read_bytes(), original[path])
                if mode == "move":
                    removed.add(path)
                for source, content in original.items():
                    if source in removed:
                        self.assertFalse(source.exists())
                    else:
                        self.assertEqual(source.read_bytes(), content)

    def test_the_folder_tree_counts_a_photo_it_could_not_read_under_any_filter(self):
        # An unreadable photo has no date, name or destination recorded, so a date or
        # search filter is NULL for it, not false: it must count as not shown, not fail.
        if os.geteuid() == 0:
            self.skipTest("root reads any file")
        make_photo(self.cfg.source / "Trip" / "ok.jpg", "ok")
        make_photo(self.cfg.source / "Trip" / "locked.jpg", "locked")
        (self.cfg.source / "Trip" / "locked.jpg").chmod(0)
        try:
            self.create_catalog()
            self.wait_for(self.start(mode="index"))
        finally:
            (self.cfg.source / "Trip" / "locked.jpg").chmod(0o644)
        for params in ({"date": "2023"}, {"q": "ok"}, {"undated": "true", "date": "2019"}):
            got = self.client.get("/api/v1/photos/folders", params=params)
            self.assertEqual(got.status_code, 200, f"{params}: {got.text}")

    def test_folder_counts_exclude_unclassified_photos_without_crashing(self):
        self.create_catalog()
        for relative in ("unknown.jpg", "Trip/Day/unknown.jpg"):
            with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn:
                conn.execute("DELETE FROM photos")
                conn.execute("INSERT INTO photos (source_path, status) VALUES (?, NULL)",
                             (str(self.cfg.source / relative),))
                conn.commit()
            for view in ("all", "organized", "unorganized"):
                for filters in ({}, {"q": "unknown"}, {"date": "2023"},
                                {"undated": "true"}, {"type": "jpg"},
                                {"q": "unknown", "date": "2023", "type": "jpg"}):
                    with self.subTest(relative=relative, view=view, filters=filters):
                        response = self.client.get("/api/v1/photos/folders",
                                                   params={"view": view, "folder": "Trip/Day", **filters})
                        self.assertEqual(response.status_code, 200)
                        tree = response.json()
                        self.assertEqual(tree["outside"], 0)
                        self.assertEqual(tree["top_files"],
                                         {"photos": 0, "eligible": {"copy": 0, "move": 0}})
                        folders = list(tree["folders"])
                        if "/" in relative:
                            self.assertTrue(folders, "the selected empty folder must remain listed")
                        while folders:
                            folder = folders.pop()
                            self.assertEqual(folder["photos"], 0)
                            self.assertEqual(folder["eligible"], {"copy": 0, "move": 0})
                            folders.extend(folder["folders"])

    def test_select_all_takes_every_photo_shown_with_no_limit(self):
        self.index_library()
        every = self.client.get("/api/v1/photos/ids").json()
        self.assertEqual((every["total"], len(every["ids"])), (2, 2))
        self.assertEqual(set(every), {"ids", "total", "in_rejects"}, "no limit fields remain")

    def test_the_selection_shows_photos_every_filter_hides_and_names_missing_ones(self):
        self.index_library()
        dated_2020 = self.client.get("/api/v1/photos", params={"date": "2020"}).json()["items"][0]["id"]
        shown = self.client.post("/api/v1/photos/selection",
                                 json={"ids": [dated_2020, 99999], "sort": "newest"}).json()
        self.assertEqual([i["id"] for i in shown["items"]], [dated_2020])
        self.assertEqual((shown["total"], shown["missing"]), (1, [99999]),
                         "a photo gone from the catalog must be named, not silently dropped")
        # No limit on how many: an unknown id is named, never refused or dropped.
        many = self.client.post("/api/v1/photos/selection", json={"ids": [dated_2020, *range(100_000, 102_000)]}).json()
        self.assertEqual((many["total"], len(many["missing"])), (1, 2_000))

    def test_exif_dates_keep_their_own_time_zones_and_the_undated_filter_finds_the_rest(self):
        make_photo(self.cfg.source / "dated.jpg", "dated", exif={
            36867: "2021:05:01 10:00:00", 36881: "+02:00",   # DateTimeOriginal, with its offset
            36868: "2021:05:01 10:00:05",                     # CreateDate, no offset
            306: "2021:05:02 11:00:00"})                      # ModifyDate, no offset
        make_photo(self.cfg.source / "undated.jpg", "undated", mtime=1_600_000_000)
        self.create_catalog()
        self.wait_for(self.start(mode="index"))
        page = self.client.get("/api/v1/photos").json()
        self.assertEqual((page["total"], page["counts"]["undated"]), (2, 1))
        only = self.client.get("/api/v1/photos", params={"undated": "true"}).json()
        self.assertEqual([i["filename"] for i in only["items"]], ["undated.jpg"])
        self.assertEqual((only["total"], only["counts"]["all"]), (1, 2),
                         "No capture date narrows what is shown, not the All photos count")
        self.assertEqual(self.client.get("/api/v1/photos/timeline", params={"undated": "true"}).json()["months"],
                         [{"month": "2020-09", "count": 1}])
        dated = next(i["id"] for i in page["items"] if i["filename"] == "dated.jpg")
        detail = self.client.get(f"/api/v1/photos/{dated}/inspect").json()
        self.assertEqual(detail["exif_dates"], [
            {"field": "taken", "value": "2021:05:01 10:00:00", "offset": "+02:00"},
            {"field": "digitized", "value": "2021:05:01 10:00:05", "offset": None},
            {"field": "modified", "value": "2021:05:02 11:00:00", "offset": None}])
        # Show all metadata: every tag the Index recorded, beyond the handful shown above.
        tags = dict(detail["metadata"])
        self.assertEqual((tags.get("DateTimeOriginal"), tags.get("OffsetTimeOriginal")),
                         ("2021:05:01 10:00:00", "+02:00"))
        self.assertIn("ImageWidth", tags, "the full ExifTool tag set, not only the curated fields")
        self.assertNotIn("date_source", tags, "the engine's own keys are not the photo's metadata")
        names = [k for k, _ in detail["metadata"]]
        self.assertEqual(names, sorted(names, key=str.lower))

    def test_one_job_at_a_time_and_the_lock_decides(self):
        self.index_library()
        with self.engine_lock_held():
            busy = self.client.post("/api/v1/jobs/start", json={"mode": "index"})
            self.assertEqual((busy.status_code, busy.json()["error"]), (409, "job_already_running"))
            active = self.client.get("/api/v1/jobs/active").json()["active"]
            self.assertTrue(active and active["unrecorded"], f"a held lock was not shown as a job: {active}")

    def test_overlapping_checks_never_report_a_job_that_is_not_running(self):
        # The page checks every second and on every refresh; two checks at once
        # must not take each other's hold on the start lock for a job.
        import threading
        self.create_catalog()
        self.cfg.lock_path.touch()
        runner, false_busy = self.app_jobs(), []
        def check():
            for _ in range(2000):
                if runner.engine_busy():
                    false_busy.append(1)
        threads = [threading.Thread(target=check) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(false_busy), 0, "an idle server reported a running job")
        with self.engine_lock_held():
            self.assertTrue(runner.engine_busy(), "a real engine's lock must still read as busy")

    def test_a_run_left_active_by_a_dead_engine_is_presented_interrupted_not_rewritten(self):
        self.index_library()
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            run_id, _ = ns_db.create_run(conn, mode="MOVE", source=str(self.cfg.source),
                                         destination=str(self.cfg.dest))
            ns_db.transition_run(conn, run_id, ns_db.RunStatus.RUNNING)
            conn.commit()
        active = self.client.get("/api/v1/jobs/active").json()["active"]
        self.assertEqual((active["id"], active["presented_status"]), (run_id, "Interrupted"))
        self.assertEqual(self.client.get(f"/api/v1/runs/{run_id}").json()["status"], "Running",
                         "the API rewrote a run's lifecycle, which only the engine may do")
        refused = self.client.post(f"/api/v1/jobs/{run_id}/cancel")
        self.assertEqual((refused.status_code, refused.json()["error"]), (409, "not_cancellable"))
        # The lock is free, so a new job starts, and its engine settles the dead run.
        self.wait_for(self.start(mode="index"))
        self.assertEqual(self.client.get(f"/api/v1/runs/{run_id}").json()["status"], "Interrupted")

    def test_cancel_stops_the_job_and_it_says_so(self):
        for i in range(150):
            make_photo(self.cfg.source / f"p{i:03d}.jpg", f"cancel-{i}", size=(800, 600))
        self.create_catalog()
        run_id = self.start(mode="index")
        self.assertEqual(self.client.post(f"/api/v1/jobs/{run_id}/cancel").status_code, 202)
        run = self.wait_for(run_id)
        self.assertEqual((run["status"], run["outcome"]["verdict"]), ("Cancelled", "cancelled"))

    def test_requests_that_would_mis_target_the_engine_are_refused_before_it_runs(self):
        self.index_library()
        for body, error in (({"mode": "delete"}, "invalid_request"),
                            ({"mode": "move", "file_ids": [1], "source_subdir": "trip"}, "invalid_request"),
                            ({"mode": "move", "source_subdir": "../elsewhere"}, "invalid_request"),
                            ({"mode": "move", "source_subdir": "/etc"}, "invalid_request"),
                            ({"mode": "move", "file_ids": ["1; rm -rf /"]}, "invalid_request"),
                            # No fixed limit, but never more photos than the catalog holds.
                            ({"mode": "move", "file_ids": list(range(1, 5))}, "invalid_request")):
            response = self.client.post("/api/v1/jobs/start", json=body)
            self.assertEqual((response.status_code, response.json()["error"]), (400, error), body)
        with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1,
                             "a refused request started an engine")

    def test_malformed_job_fields_are_refused_without_spawning(self):
        self.index_library()
        bodies = [{"mode": value} for value in ([], {}, None, True, 1, "unknown")]
        bodies += [{"mode": "copy", "file_ids": value} for value in
                   ([], {}, "1", [True], [1.5], [0], [-1], [2**63], [2**80])]
        bodies += [{"mode": "move", "source_subdir": value} for value in
                   ("", "\0", [], {}, "../outside", "/outside", " folder /../../outside")]
        with patch("webui.jobs.subprocess.Popen", side_effect=AssertionError("engine spawned")) as spawn:
            for body in bodies:
                with self.subTest(body=body):
                    response = self.client.post("/api/v1/jobs/start", json=body)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json()["error"], "invalid_request")
                    self.assertTrue(response.json()["message"])
            spawn.assert_not_called()
        with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_a_jobs_photos_are_a_view_that_every_filter_narrows(self):
        """webui-spec 2, after a job: view=job with run=<id> shows the photos that job
        recorded, wherever they are now, and search, the facets and Select all apply."""
        self.index_library()
        listed = self.client.get("/api/v1/photos", params={"page_size": 240}).json()["items"]
        self.assertGreater(len(listed), 1)
        chosen = [listed[0]["id"]]
        run = self.wait_for(self.start(mode="copy", file_ids=chosen))
        scope = {"view": "job", "run": run["id"]}
        shown = self.client.get("/api/v1/photos", params=scope).json()
        self.assertEqual(sorted(p["id"] for p in shown["items"]), sorted(chosen), "the job view shows other photos")
        self.assertEqual(shown["total"], len(chosen))
        self.assertEqual(shown["counts"]["all"], len(listed), "the view buttons count only the job's photos")
        self.assertEqual(sorted(self.client.get("/api/v1/photos/ids", params=scope).json()["ids"]), sorted(chosen))
        searched = self.client.get("/api/v1/photos", params={**scope, "q": listed[0]["filename"]}).json()
        self.assertEqual([p["id"] for p in searched["items"]], chosen, "search does not find the job's photo")
        other = self.client.get("/api/v1/photos", params={**scope, "q": listed[1]["filename"]}).json()
        self.assertEqual(other["total"], 0, "search inside a job finds photos outside it")
        self.assertEqual(other["counts"]["job"], len(chosen), "the job's own count follows the search")
        for facet in ("timeline", "types", "folders"):
            with self.subTest(facet=facet):
                self.assertEqual(self.client.get(f"/api/v1/photos/{facet}", params=scope).status_code, 200)
        types = self.client.get("/api/v1/photos/types", params=scope).json()["types"]
        self.assertEqual(sum(t["photos"] for t in types), len(chosen), "the Types counts are not the job's")
        found = self.client.post("/api/v1/photos/position", json={"photo_id": chosen[0], **scope}).json()
        self.assertIsNotNone(found["position"], "a job's photo cannot be located in its view")
        self.assertEqual(self.client.get("/api/v1/photos", params={"view": "job", "run": 0}).status_code, 422)

    def test_a_selection_reaches_the_engine_in_a_private_file_and_is_kept_with_the_job(self):
        import stat
        import subprocess
        self.index_library()
        chosen = self.client.get("/api/v1/photos/ids").json()["ids"]
        real, seen = subprocess.Popen, []
        def spy(argv, **kw):
            path = Path(argv[argv.index("--file-ids-from") + 1]) if "--file-ids-from" in argv else None
            seen.append({"argv": argv, "path": path, "data": path.read_bytes() if path else None,
                         "mode": stat.S_IMODE(path.stat().st_mode) if path else None,
                         "folder": stat.S_IMODE(path.parent.stat().st_mode) if path else None})
            return real(argv, **kw)
        with patch("webui.jobs.subprocess.Popen", side_effect=spy):
            run = self.wait_for(self.start(mode="copy", file_ids=list(reversed(chosen)), request_id="chosen-photos"))
        (call,) = seen
        self.assertNotIn("--file-ids", call["argv"], "photo ids on the command line")
        self.assertEqual(call["path"], self.cfg.base / "selections" / "chosen-photos.ids",
                         "the file is named by the request ID, under application data")
        self.assertEqual((call["mode"], call["folder"]), (0o600, 0o700), "the selection is not private")
        self.assertTrue(call["data"].startswith(b"NegativeSpace selection 1\nrequest chosen-photos\n"))
        self.assertFalse(call["path"].exists(), "the selection file outlived the start")
        self.assertEqual(run["targeting"], {"selection": len(chosen), "sha256": ns_db.selection_digest(sorted(chosen))})
        self.assertEqual(run["outcome"]["succeeded"], len(chosen))
        with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn:
            self.assertEqual([r[0] for r in conn.execute(
                "SELECT photo_id FROM run_selections WHERE run_id = ? ORDER BY photo_id", (run["id"],))], sorted(chosen))
        # Worked back from a photo: the jobs it was chosen for.
        lineage = self.client.get(f"/api/v1/photos/{chosen[0]}/lineage").json()
        self.assertEqual([(s["run_id"], s["mode"]) for s in lineage["selected_by"]], [(run["id"], "COPY")])
        # The same request again is the same job, not a second one.
        self.assertEqual(self.start(mode="copy", file_ids=chosen, request_id="chosen-photos"), run["id"])

    def test_selection_start_failures_can_retry_the_same_request_once(self):
        import errno
        import stat

        self.index_library()
        chosen = self.client.get('/api/v1/photos/ids').json()['ids']
        real_fsync = os.fsync

        def fail_directory_sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(errno.EIO, 'injected directory sync failure')
            return real_fsync(fd)

        for stage, status, code in (('publication', 503, 'selection_unavailable'),
                                    ('log_open', 500, 'engine_start_failed'),
                                    ('spawn', 500, 'engine_start_failed')):
            with self.subTest(stage=stage):
                body = {'mode': 'copy', 'file_ids': chosen, 'request_id': f'retry-{stage}'}
                before = len(self.client.get('/api/v1/runs').json()['runs'])
                with contextlib.ExitStack() as patches:
                    spawn = patches.enter_context(patch('webui.jobs.subprocess.Popen',
                        side_effect=OSError(errno.EACCES, 'injected spawn failure')))
                    if stage == 'publication':
                        patches.enter_context(patch('engine.ns_db.os.fsync', side_effect=fail_directory_sync))
                    elif stage == 'log_open':
                        patches.enter_context(patch('webui.jobs.open', create=True,
                            side_effect=OSError(errno.EACCES, 'injected log-open failure')))
                    response = self.client.post('/api/v1/jobs/start', json=body)
                    self.assertEqual((response.status_code, response.json()['error']), (status, code))
                    self.assertIn('message', response.json())
                    if stage != 'spawn':
                        spawn.assert_not_called()
                    else:
                        spawn.assert_called_once()
                self.assertEqual(list((self.cfg.base / 'selections').iterdir()), [])
                self.assertEqual(len(self.client.get('/api/v1/runs').json()['runs']), before)
                self.assertEqual(self.client.get(f'/api/v1/job-requests/{body["request_id"]}').json(),
                                 {'state': 'unknown', 'run': None})
                run = self.wait_for(self.start(**body))
                self.assertEqual(run['status'], 'Completed')
                self.assertEqual(self.start(**body), run['id'])
                self.assertEqual(len(self.client.get('/api/v1/runs').json()['runs']), before + 1)
                self.assertEqual(list((self.cfg.base / 'selections').iterdir()), [])
                with sqlite3.connect(self.cfg.db_path) as conn:
                    self.assertEqual([r[0] for r in conn.execute(
                        'SELECT photo_id FROM run_selections WHERE run_id=? ORDER BY photo_id', (run['id'],))],
                        sorted(chosen))

    def test_selection_start_refusal_keeps_an_active_input(self):
        self.index_library()
        chosen = self.client.get('/api/v1/photos/ids').json()['ids']
        path = ns_db.write_selection_file(self.cfg.base / 'selections', 'pending-selection', chosen)
        original = path.read_bytes()
        with self.app_jobs()._selection_lease(), patch('webui.jobs.subprocess.Popen') as spawn:
            response = self.client.post('/api/v1/jobs/start', json={
                'mode': 'copy', 'file_ids': chosen, 'request_id': 'pending-selection'})
            self.assertEqual((response.status_code, response.json()['error']), (409, 'job_already_running'))
            spawn.assert_not_called()
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((path.parent / '.pending-selection.ids.tmp').exists())

    def test_a_selected_job_can_start_the_moment_the_last_one_finished(self):
        """The engine holds the selection lock only until it has read its selection: held
        to process exit, it refused the next selected start just after a job settled."""
        self.index_library()
        chosen = self.client.get("/api/v1/photos/ids").json()["ids"]
        for attempt in range(3):
            run = self.wait_for(self.start(mode="copy", file_ids=chosen))
            self.assertEqual(run["status"], "Completed", attempt)

    def test_a_selection_naming_a_photo_not_catalogued_is_refused_whole(self):
        self.index_library()
        known = self.client.get("/api/v1/photos/ids").json()["ids"][0]
        for chosen in ([2**63 - 1], [known, 2**63 - 1]):
            response = self.client.post("/api/v1/jobs/start", json={"mode": "copy", "file_ids": chosen})
            self.assertEqual((response.status_code, response.json()["error"]), (409, "engine_refused"), chosen)
            message = response.json()["message"]
            self.assertEqual(message, f"1 of the {len(chosen)} selected photos are no longer catalogued in this source. "
                                      "Nothing was changed; choose the photos again.", "only the reason, for a person")
        with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1, "a refused selection recorded a run")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM run_selections").fetchone()[0], 0)
        self.assertEqual(list(self.cfg.dest.rglob("*.jpg")), [], "a refused selection touched a file")
        self.assertEqual(list((self.cfg.base / "selections").iterdir()), [], "a selection file was left behind")

    def test_the_job_stream_sends_the_current_state_on_connect(self):
        self.index_library()
        with self.client.websocket_connect("/api/v1/ws/jobs") as ws:
            state = ws.receive_json()
        self.assertIsNone(state["active"])
        self.assertEqual(state["last"]["mode"], "INDEX")


class LogAndErrorCenter(ApiCase):
    """webui-spec 5.3 / 5.4: the log with its filters, failures from the recorded
    attempts, retry ids from those attempts, and export."""

    def test_failures_are_found_from_attempts_retried_by_photo_and_exported(self):
        if os.geteuid() == 0:
            self.skipTest("root reads any file, so a permission failure cannot be made")
        make_photo(self.cfg.source / "good.jpg", "good")
        make_photo(self.cfg.source / "locked.jpg", "locked")
        self.create_catalog()
        index = self.wait_for(self.start(mode="index"))
        (self.cfg.source / "locked.jpg").chmod(0)
        try:
            copy = self.wait_for(self.start(mode="copy"))
        finally:
            (self.cfg.source / "locked.jpg").chmod(0o644)
        self.assertEqual(copy["outcome"]["verdict"], "partial")
        self.assertEqual(copy["outcome"]["failure_reasons"], {"Permission denied": 1},
                         "the reason, without the error number or the path, so reasons group")
        locked = next(i for i in self.client.get("/api/v1/photos").json()["items"] if i["filename"] == "locked.jpg")
        self.assertEqual((locked["status"], locked["failure"]), ("Failed", "Permission denied"))

        everything = self.client.get("/api/v1/operations").json()
        self.assertEqual(everything["status_counts"], {"Pending": 2, "Copied": 1, "Failed": 1},
                         "the log does not hold one scan row per photo and one outcome per transfer")
        self.assertEqual([op["id"] for op in everything["items"]],
                         sorted((op["id"] for op in everything["items"]), reverse=True), "not newest first")
        self.assertEqual(everything["run_counts"], {str(index["id"]): 2, str(copy["id"]): 2},
                         "the log groups entries by job")

        failed = self.client.get("/api/v1/operations", params={"run": copy["id"], "status": "Failed"}).json()
        self.assertEqual(failed["total"], 1)
        op = failed["items"][0]
        self.assertTrue(op["source_path"].endswith("locked.jpg") and not op["run_level"])
        self.assertIn("Permission", op["error_message"])
        self.assertEqual(failed["status_counts"], {"Copied": 1, "Failed": 1},
                         "status counts must ignore the status filter, so each button shows what it finds")
        self.assertEqual(self.client.get("/api/v1/operations", params={"status": "Failed"}).json()["run_counts"],
                         {str(copy["id"]): 1}, "job counts must apply every filter, so a job with no match is hidden")

        retry = self.client.get("/api/v1/operations/photo-ids", params={"run": copy["id"], "status": "Failed"}).json()
        self.assertEqual(retry, {"photo_ids": [op["photo_id"]]})

        history = self.client.get("/api/v1/operations", params={"photo": op["photo_id"]}).json()
        self.assertEqual(sorted(i["status"] for i in history["items"]), ["Failed", "Pending"],
                         "a photo's history must hold its scan and its failed attempt")
        self.assertEqual(self.client.get("/api/v1/operations", params={"q": "good.jpg"}).json()["total"], 2)
        self.assertEqual(self.client.get("/api/v1/operations", params={"status": "Nonsense"}).status_code, 400)

        csv_text = self.client.get("/api/v1/operations/export", params={"format": "csv", "status": "Failed"}).text
        self.assertEqual(csv_text.splitlines()[0].split(",")[:5], ["id", "timestamp", "run_id", "mode", "status"])
        self.assertEqual(len(csv_text.strip().splitlines()), 2, "the export does not honour the filters")
        exported = self.client.get("/api/v1/operations/export", params={"format": "json"}).json()
        self.assertEqual(len(exported), 4)
        self.assertEqual([r["id"] for r in exported], sorted(r["id"] for r in exported), "an export runs oldest first")

        runs = self.client.get("/api/v1/runs").json()["runs"]
        self.assertEqual([(r["mode"], r["outcome"]["verdict"]) for r in runs], [("COPY", "partial"), ("INDEX", "success")])

    def test_retry_takes_the_photos_behind_failed_attempts_not_their_status(self):
        # They differ for a duplicate whose verification failed: its attempt is Failed and
        # the photo stays Duplicate (webui-spec 5.3). Staged by recording such an attempt,
        # and a photo whose status reads Failed with no failed attempt behind it.
        make_photo(self.cfg.source / "a.jpg", "a")
        make_photo(self.cfg.source / "copy of a.jpg", "a")
        make_photo(self.cfg.source / "b.jpg", "b")
        self.create_catalog()
        self.wait_for(self.start(mode="index"))
        copy = self.wait_for(self.start(mode="copy"))
        with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn, conn:
            dup, dup_path = conn.execute("SELECT id, source_path FROM photos WHERE status = 'Duplicate'").fetchone()
            conn.execute("INSERT INTO operations (run_id, photo_id, source_path, status, error_message, timestamp) "
                         "VALUES (?, ?, ?, 'Failed', 'Duplicate verification failed: ChecksumMismatch', ?)",
                         (copy["id"], dup, dup_path, "2026-01-01T00:00:00+00:00"))
            other = conn.execute("SELECT id FROM photos WHERE status = 'Copied' LIMIT 1").fetchone()[0]
            conn.execute("UPDATE photos SET status = 'Failed' WHERE id = ?", (other,))
        ids = self.client.get("/api/v1/operations/photo-ids", params={"run": copy["id"], "status": "Failed"}).json()
        self.assertEqual(ids["photo_ids"], [dup], "Retry must follow the failed attempt, not photos.status")

    def test_a_photos_history_follows_it_through_a_move(self):
        make_photo(self.cfg.source / "a.jpg", "a")
        self.create_catalog()
        self.wait_for(self.start(mode="index"))
        photo = self.client.get("/api/v1/photos").json()["items"][0]["id"]
        self.wait_for(self.start(mode="move"))
        history = self.client.get("/api/v1/operations", params={"photo": photo}).json()
        self.assertEqual(sorted(i["status"] for i in history["items"]), ["Completed", "Pending"])

    def test_a_move_that_could_only_copy_says_so_everywhere(self):
        if os.geteuid() == 0:
            self.skipTest("root deletes from any folder, so a kept original cannot be made")
        make_photo(self.cfg.source / "a.jpg", "a")
        make_photo(self.cfg.source / "b.jpg", "b")
        self.create_catalog()
        self.wait_for(self.start(mode="index"))
        self.cfg.source.chmod(0o555)
        try:
            move = self.wait_for(self.start(mode="move"))
        finally:
            self.cfg.source.chmod(0o755)
        outcome = move["outcome"]
        self.assertEqual((outcome["verdict"], outcome["copied_only"], outcome["succeeded"], outcome["failed"]),
                         ("originals_kept", 2, 0, 0), "copied, not moved, and not failed")
        self.assertEqual(outcome["kept_reasons"], {"Permission denied": 2})
        self.assertEqual(outcome["failure_reasons"], {})
        items = self.client.get("/api/v1/photos").json()["items"]
        self.assertEqual({(i["status"], i["kept"]) for i in items}, {("Copied", "Permission denied")})

        log = self.client.get("/api/v1/operations", params={"run": move["id"]}).json()
        self.assertEqual(log["status_counts"], {"Copied_Only": 2}, "the log names it, derived from the recorded Copied")
        only = self.client.get("/api/v1/operations", params={"status": "Copied_Only"}).json()
        self.assertEqual(only["total"], 2)
        plain = self.client.get("/api/v1/operations", params={"status": "Copied"}).json()
        self.assertEqual(plain["total"], 0, "a plain Copied filter must not find a Move's kept originals")
        ids = self.client.get("/api/v1/operations/photo-ids",
                              params={"run": move["id"], "status": ["Failed", "Copied_Only"]}).json()
        self.assertEqual(sorted(ids["photo_ids"]), sorted(i["id"] for i in items), "the photos a Move again would take")
        # requested_only leaves out a row settling an earlier job's work, so a selection's
        # retry never names a photo the selection did not hold. Staged: one row made a recovery.
        with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn, conn:
            recovered, earlier = conn.execute(
                "SELECT o.id, (SELECT MIN(id) FROM operations WHERE photo_id = o.photo_id) FROM operations o "
                "WHERE o.run_id = ? ORDER BY o.id LIMIT 1", (move["id"],)).fetchone()
            conn.execute("UPDATE operations SET reconciles_operation_id = ? WHERE id = ?", (earlier, recovered))
        requested = self.client.get("/api/v1/operations/photo-ids",
                                    params={"run": move["id"], "status": ["Failed", "Copied_Only"],
                                            "requested_only": "true"}).json()
        self.assertEqual(len(requested["photo_ids"]), 1, "the recovery row's photo must be left out")
        with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn, conn:
            conn.execute("UPDATE operations SET reconciles_operation_id = NULL WHERE id = ?", (recovered,))

        finished = self.wait_for(self.start(mode="move", file_ids=ids["photo_ids"]))
        self.assertEqual((finished["outcome"]["verdict"], finished["outcome"]["copied_only"]), ("success", 0))
        self.assertEqual({i["status"] for i in self.client.get("/api/v1/photos").json()["items"]}, {"Completed"})

    def test_a_folder_that_could_not_be_read_is_a_run_level_failure(self):
        if os.geteuid() == 0:
            self.skipTest("root reads any folder")
        make_photo(self.cfg.source / "ok.jpg", "ok")
        make_photo(self.cfg.source / "sealed" / "inside.jpg", "inside")
        (self.cfg.source / "sealed").chmod(0)
        try:
            self.create_catalog()
            self.wait_for(self.start(mode="index"))
        finally:
            (self.cfg.source / "sealed").chmod(0o755)
        failed = self.client.get("/api/v1/operations", params={"status": "Failed"}).json()["items"]
        self.assertEqual([(f["run_level"], f["photo_id"]) for f in failed], [(True, None)],
                         "an unreadable folder must be one run-level failure, not a failed photo or nothing")


class InterfaceState(ApiCase):
    def test_a_dismissed_banner_is_kept_with_the_catalog(self):
        self.create_catalog()
        self.assertEqual(self.client.get("/api/v1/ui-state").json(), {"dismissed_run": None})
        run_id = self.wait_for(self.start(mode="index"))["id"]
        saved = self.client.put("/api/v1/ui-state", json={"dismissed_run": run_id})
        self.assertEqual(saved.json(), {"dismissed_run": run_id})
        self.assertEqual(self.client.get("/api/v1/ui-state").json(), {"dismissed_run": run_id},
                         "a dismissal must outlive the browser that made it")
        for bad in ({"dismissed_run": 999}, {"dismissed_run": "1"}, {"theme": "dark"}, {}):
            self.assertEqual(self.client.put("/api/v1/ui-state", json=bad).status_code, 400, bad)


class ArchivesOverTime(ApiCase):
    """The maintainer's use case: archives of the library, each in its own folder of the
    source, indexed days apart; a copy of a photo already catalogued is a duplicate of it
    and joins its lineage, even a file put back at its old path after a Move."""

    def photo_at(self, name):
        with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as db:
            return db.execute("SELECT id, status FROM photos WHERE source_path LIKE ? ORDER BY id DESC",
                              ("%/" + name,)).fetchone()

    def test_archives_indexed_apart_share_one_lineage_and_count_their_duplicates(self):
        A, B = self.cfg.source / "archive-2019", self.cfg.source / "archive-2021"
        for i in range(4):
            make_photo(A / f"IMG_{i}.jpg", f"photo-{i}", size=(60 + i, 40), mtime=1_560_000_000)
        self.create_catalog()
        self.wait_for(self.start(mode="index"))
        self.wait_for(self.start(mode="move"))
        # Days later, archive B: two photos A had, under other names, and one new.
        make_photo(B / "copy_of_0.jpg", "photo-0", size=(60, 40))
        make_photo(B / "DSC_1.jpg", "photo-1", size=(61, 40))
        make_photo(B / "new.jpg", "photo-new", size=(70, 40))
        # And one of A's photos put back where it was.
        make_photo(A / "IMG_2.jpg", "photo-2", size=(62, 40), mtime=1_560_000_000)
        self.wait_for(self.start(mode="index"))

        self.assertEqual(self.photo_at("copy_of_0.jpg")[1], "Duplicate")
        self.assertEqual(self.photo_at("IMG_2.jpg")[1], "Duplicate", "a file put back after a Move is a duplicate")
        original = self.photo_at("IMG_0.jpg")
        tree = self.client.get(f"/api/v1/photos/{original[0]}/lineage").json()
        self.assertEqual(len(tree["photos"]), 2, "the archive copy joins the original's lineage")
        moved_back = next(i for i in self.client.get("/api/v1/photos").json()["items"] if i["filename"] == "IMG_2.jpg")
        self.assertEqual(moved_back["status"], "Completed", "the moved photo stays organized")
        back_tree = self.client.get(f"/api/v1/photos/{moved_back['id']}/lineage").json()
        self.assertEqual(sorted(f["origin_kind"] for f in back_tree["files"]), ["indexed", "indexed"],
                         "the tree holds the moved photo and the returned file, both")
        history = self.client.get("/api/v1/operations", params={"photo": original[0]}).json()["items"]
        self.assertIn("Duplicate", [o["status"] for o in history], "the log history shows the duplicate, as the tree does")

        folders = {f["folder"]: f for f in self.client.get("/api/v1/stats").json()["duplicates"]["by_folder"]}
        self.assertEqual((folders["archive-2021"]["files"], folders["archive-2021"]["duplicates"]), (3, 2),
                         "the later archive carries the duplicates")
        self.assertEqual(folders["archive-2019"]["duplicates"], 1, "the file put back is a duplicate too")


class CatalogBackups(ApiCase):
    """webui-spec 9: the list, Back up now, and downloads."""

    def test_backup_now_is_listed_downloadable_and_restorable(self):
        import zstandard
        make_photo(self.cfg.source / "IMG_0001.jpg", "a")
        self.create_catalog()
        run_id = self.wait_for(self.start(mode="index"))["id"]
        listed = self.client.get("/api/v1/backups").json()
        self.assertTrue(listed["storage"]["ok"])
        (post_job,) = listed["items"]
        self.assertEqual((post_job["trigger_kind"], post_job["related_run_id"]), ("post_job", run_id))
        self.assertEqual(listed["unbacked"]["count"], 0, "the post-job backup holds the index")

        made = self.client.post("/api/v1/backups")
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual((made.json()["outcome"], made.json()["trigger_kind"]), ("succeeded", "manual"))
        listed = self.client.get("/api/v1/backups").json()
        manual = listed["items"][0]
        self.assertEqual((manual["trigger_kind"], manual["availability"], manual["compression_format"]),
                         ("manual", "present", "zstd"))
        self.assertEqual((listed["present_count"], listed["automatic_retained"]), (2, 1))
        self.assertEqual(listed["last_success"], manual["started_at"])

        got = self.client.get(f"/api/v1/backups/{manual['attempt_id']}/download")
        self.assertEqual(got.status_code, 200)
        self.assertIn(manual["relative_filename"], got.headers["content-disposition"])
        restored = self.root / "restored.db"
        restored.write_bytes(zstandard.ZstdDecompressor().decompress(got.content))
        with contextlib.closing(sqlite3.connect(restored)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0], 1)

        (self.cfg.backups / manual["relative_filename"]).unlink()
        gone = self.client.get("/api/v1/backups").json()["items"][0]
        self.assertEqual((gone["availability"], gone["outcome"]), ("missing", "succeeded"),
                         "a vanished file changed the recorded outcome")
        refused = self.client.get(f"/api/v1/backups/{manual['attempt_id']}/download")
        self.assertEqual((refused.status_code, refused.json()["error"]), (404, "backup_unavailable"))

    def test_unreachable_storage_is_reported_not_taken_for_deletion(self):
        self.create_catalog()
        self.assertEqual(self.client.post("/api/v1/backups").json()["outcome"], "succeeded")
        shutil.rmtree(self.cfg.backups)
        listed = self.client.get("/api/v1/backups").json()
        self.assertEqual((listed["storage"]["ok"], listed["storage"]["error_category"]),
                         (False, "storage_unavailable"))
        self.assertEqual(listed["items"][0]["availability"], "unknown")
        failed = self.client.post("/api/v1/backups")
        self.assertEqual(failed.status_code, 200)
        self.assertEqual((failed.json()["outcome"], failed.json()["error_category"]),
                         ("failed", "storage_unavailable"))
        self.assertEqual(self.client.get("/api/v1/backups").json()["items"][0]["outcome"], "failed")

    def test_back_up_now_is_refused_while_a_job_runs(self):
        self.create_catalog()
        with self.engine_lock_held():
            refused = self.client.post("/api/v1/backups")
            self.assertEqual((refused.status_code, refused.json()["error"]), (409, "job_already_running"))
        self.assertEqual(self.client.get("/api/v1/backups").json()["items"], [])

    def test_a_missing_catalog_has_nothing_to_back_up(self):
        refused = self.client.post("/api/v1/backups")
        self.assertEqual((refused.status_code, refused.json()["error"]), (409, "catalog_missing"))
        self.assertEqual(self.client.get("/api/v1/backups").status_code, 409)


class DerivedOutcome(ApiCase):
    """webui-spec 5.5: the verdict comes from classified outcomes, not runs.status."""

    def run_with(self, mode, phases, status=ns_db.RunStatus.COMPLETED):
        with contextlib.closing(ns_db.connect(self.cfg.db_path)) as conn:
            run_id, _ = ns_db.create_run(conn, mode=mode, source="/s", destination="/d")
            with ns_db.transaction(conn):
                for seq, (phase, total, counts) in enumerate(phases, 1):
                    ns_db.write_progress(conn, run_id, phase=phase, seq=seq, total=total, counts=counts,
                                         started_at="t")
            ns_db.transition_run(conn, run_id, ns_db.RunStatus.RUNNING)
            ns_db.transition_run(conn, run_id, status)
            conn.commit()
        return self.client.get(f"/api/v1/runs/{run_id}").json()["outcome"]

    def test_verdicts(self):
        self.create_catalog()
        scan = ("scanning", 3, {"unchanged": 3})
        self.assertEqual(self.run_with("MOVE", [scan, ("transferring", 3, {"Failed": 3})])["verdict"], "none_succeeded",
                         "a Completed run where every file failed read as success")
        self.assertEqual(self.run_with("INDEX", [("scanning", 10, {"unchanged": 7, "failed": 3})])["verdict"], "partial",
                         "an Index that checked every file and could not read three read as failed")
        self.assertEqual(self.run_with("COPY", [scan, ("transferring", 3, {"Skipped": 2, "Failed": 1})])["verdict"],
                         "partial", "skipped files with one failure read as nothing succeeded")
        self.assertEqual(self.run_with("COPY", [scan, ("transferring", 3, {"Copied": 1})],
                                       status=ns_db.RunStatus.FAILED)["verdict"], "stopped",
                         "a job an error stopped did not say so")
        self.assertEqual(self.run_with("COPY", [scan, ("transferring", 3, {"Copied": 2, "Failed": 1})])["verdict"],
                         "partial")
        self.assertEqual(self.run_with("COPY", [scan, ("transferring", 3, {"Skipped": 3})])["verdict"], "no_change")
        self.assertEqual(self.run_with("INDEX", [("scanning", 10, {"unchanged": 10})])["verdict"], "no_change")
        cancelled = self.run_with("MOVE", [scan, ("transferring", 3, {"Completed": 1, "Cancelled": 2})],
                                  status=ns_db.RunStatus.CANCELLED)
        self.assertEqual((cancelled["verdict"], cancelled["succeeded"], cancelled["cancelled"]), ("cancelled", 1, 2))


class MatchingTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.create_catalog()
        self.conn = ns_db.connect(self.cfg.db_path)
        self.run = ns_db.create_run(self.conn, mode='INDEX', source='/source', destination='/destination')[0]

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def photo(self, name, digest, phash, status='Copied', width=640):
        with ns_db.transaction(self.conn):
            path = f'/source/{name}.jpg'
            photo = self.conn.execute('INSERT INTO photos(source_path,status,sha1_hash,file_size) VALUES(?,?,?,10)',
                                      (path,status,digest)).lastrowid
            ns_db.record_source_observation(self.conn, photo_id=photo, run_id=self.run, source_path=path,
                sha1_hash=digest, file_size=10, file_mtime=100, birthtime=None, metadata={}, error=None)
            ns_db.content_for_digest(self.conn, digest=digest, phash=phash, phash_state='ok' if phash else 'failed', width=width, height=480)
            if status in ('Copied', 'Completed', 'Found_At_Destination'):
                destination = f'/destination/{name}.jpg'
                op = self.conn.execute('INSERT INTO operations(run_id,photo_id,status,timestamp) VALUES(?,?,?,?)',
                                       (self.run, photo, status, 'test')).lastrowid
                ns_db.link_operation(self.conn, op, photo)
                ns_db.record_delivery(self.conn, operation_id=op, photo_id=photo, run_id=self.run,
                    destination=destination, source_removed=status == 'Completed',
                    created=status != 'Found_At_Destination', sha1_hash=digest)
                self.conn.execute('UPDATE photos SET dest_path=? WHERE id=?', (destination, photo))
        return photo

    def refresh(self):
        from engine import ns_similarity
        self.assertTrue(ns_similarity.refresh(self.conn))

    def test_cross_location_matches_are_separate_and_ignore_emptied_rejects(self):
        from webui import catalog
        a = self.photo('library', 'a', '0000000000000000')
        b = self.photo('library-match', 'b', '0000000000000001')
        rejected = self.photo('rejected', 'r', '0000000000000003')
        source = self.photo('source', 's', '0000000000000000', status='Pending')
        self.refresh()
        destination = self.cfg.dest / 'rejects' / 'rejected.jpg'
        destination.parent.mkdir(parents=True, exist_ok=True)
        (self.cfg.dest / 'library').mkdir(exist_ok=True)
        destination.write_bytes(b'generated fixture')
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE photos SET status='Rejected_Copied',dest_path=? WHERE id=?", (str(destination), rejected))
            self.conn.execute("UPDATE file_states SET current_path=? WHERE current_path='/destination/rejected.jpg'", (str(destination),))
        def results(photo, scope='library'):
            response = self.client.get(f'/api/v1/similar/{photo}?scope={scope}')
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()
        self.assertEqual([p['id'] for p in results(a)['items']], [b])
        self.assertEqual([p['id'] for p in results(a, 'rejects')['items']], [rejected])
        self.assertEqual({p['id'] for p in results(rejected)['items']}, {a, b})
        for scope in ('library', 'rejects'):
            counts = self.client.get(f'/api/v1/similar/{a}/counts?scope={scope}').json()
            self.assertEqual(next(c['count'] for c in counts['counts'] if c['threshold']==90), 1)
            self.assertEqual(results(source, scope)['availability'], 'not_available')
        pair = self.client.get(f'/api/v1/similar/{a}/pair/{rejected}').json()
        self.assertEqual((pair['reference']['status'], pair['candidate']['status']), ('Copied', 'Rejected_Copied'))
        self.assertEqual(pair['score'], 96.88)
        self.assertEqual({p['id'] for p in self.client.get('/api/v1/photos?view=similar&match_min=90').json()['items']}, {a,b})
        # Invalid request scopes cannot become SQL. Both endpoints reject them.
        for suffix in ('', '/counts'):
            response = self.client.get(f'/api/v1/similar/{a}{suffix}', params={'scope': "rejects' OR 1=1--"})
            self.assertEqual(response.status_code, 400)
        # Emptying Rejects must exclude both candidates and references, even before
        # the engine records Rejected_Emptied. Its directory cache has the same TTL
        # as the Rejects gallery; clear it to represent the next listing.
        destination.unlink()
        catalog._rejects_listings.clear()
        self.assertEqual(results(a, 'rejects')['total'], 0)
        self.assertEqual(results(rejected)['availability'], 'not_available')
        self.assertEqual(self.client.get(f'/api/v1/similar/{a}/pair/{rejected}').status_code, 409)
        self.assertEqual(self.client.get(f'/api/v1/similar/{source}/pair/{a}').status_code, 409)

    def test_review_group_representative_stays_inside_inbox_before_collapse(self):
        a = self.photo('reviewed', 'a'*40, '0000000000000000')
        b = self.photo('needs-review', 'b'*40, '0000000000000000')
        c = self.photo('also-needs-review', 'c'*40, '0000000000000000')
        self.refresh()
        setting = self.client.get('/api/v1/settings').json()['small_image_min']
        self.assertEqual(self.client.put('/api/v1/settings', json={'values': {'small_image_min': 800},
            'revisions': {'small_image_min': setting['revision']}}).status_code, 200)
        def mark_reviewed(photo):
            detail = self.client.get(f'/api/v1/photos/{photo}/review').json()
            response = self.client.post(f'/api/v1/photos/{photo}/review', json={
                'photo_id': photo, 'sha1': detail['sha1'], 'revision': detail['revision'],
                'reason': 'small', 'action': 'reviewed', 'note': '', 'request_id': f'{photo:032x}'})
            self.assertEqual(response.status_code, 200, response.text)
        mark_reviewed(a)
        query = 'view=review&similar=true&group_sets=true&match_min=90'
        result = self.client.get('/api/v1/photos?'+query).json()
        self.assertEqual((result['total'], [p['id'] for p in result['items']]), (1, [b]))
        self.assertEqual(self.client.get('/api/v1/photos/ids?'+query).json()['ids'], [b])
        self.assertEqual(self.client.get('/api/v1/photos/timeline?'+query).json()['undated'], 1)
        self.assertEqual(self.client.get('/api/v1/photos/types?'+query).json()['types'], [{'type':'jpg','photos':1}])
        position = self.client.post('/api/v1/photos/position', json={'photo_id':b, 'view':'review',
            'similar':True, 'group_sets':True, 'match_min':90, 'sort':'matches','page_size':1}).json()
        self.assertEqual((position['position'], position['page'], position['next_id']), (0, 1, None))
        members = self.client.get(f'/api/v1/similar/{b}/sets?threshold=90').json()
        self.assertEqual({p['id'] for p in members['items']}, {a,b,c})
        library = self.client.get('/api/v1/photos?view=organized&similar=true&group_sets=true').json()
        self.assertEqual([p['id'] for p in library['items']], [a])
        mark_reviewed(b)
        self.assertEqual(self.client.get('/api/v1/photos/ids?'+query).json()['ids'], [c])
        mark_reviewed(c)
        self.assertEqual(self.client.get('/api/v1/photos?'+query).json()['total'], 0)

    def test_largest_lookalike_is_not_limited_to_the_first_page(self):
        reference=self.photo('reference','a'*40,'0000000000000000')
        for i in range(61):
            last=self.photo(f'match-{i}',f'{i+1:040x}','0000000000000000',width=640 if i<60 else 4000)
        self.refresh()
        result=self.client.get(f'/api/v1/similar/{reference}?page_size=30').json()
        self.assertEqual(result['total'],61)
        self.assertNotIn(last,[p['id'] for p in result['items']])
        self.assertEqual(result['largest_match']['id'],last)
        self.assertEqual(result['largest_match']['width'],4000)

    def test_cached_counts_equal_live_reads_and_invalidate_transactionally(self):
        from engine import ns_similarity_cache as cache
        a = self.photo('reference', 'a', '0000000000000000')
        self.photo('byte-copy', 'a', '0000000000000000')
        for d in (0, 3, 4, 6, 7, 9, 10, 12, 13, 16, 17):
            self.photo(f'distance-{d}', f'content-{d}', f'{(1 << d)-1:016x}')
        self.photo('unavailable', 'bad', None)
        self.refresh()
        def responses():
            return [self.client.get(f'/api/v1/photos?view=similar&sort=matches&match_min={t}').json()
                    for t in (*cache.THRESHOLDS, 76)]
        live = responses()
        self.assertTrue(cache.refresh(self.conn))
        self.assertEqual(responses(), live)
        self.assertEqual(self.conn.execute('SELECT dirty FROM similarity_count_state').fetchone(), (0,))
        # Unrelated metadata and a no-op membership update leave the cache usable.
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE photos SET file_size=20,status=status WHERE id=?", (a,))
        self.assertEqual(self.conn.execute('SELECT dirty FROM similarity_count_state').fetchone(), (0,))
        before = responses()
        # Rolled-back changes must not invalidate; existing readers keep a coherent snapshot.
        reader = ns_db.connect(self.cfg.db_path)
        reader.execute('BEGIN')
        self.assertEqual(reader.execute('SELECT dirty FROM similarity_count_state').fetchone(), (0,))
        self.conn.execute('BEGIN')
        self.conn.execute("UPDATE file_states SET presence_state='missing' WHERE current_path='/destination/distance-0.jpg'")
        self.assertEqual(self.conn.execute('SELECT dirty FROM similarity_count_state').fetchone(), (1,))
        self.conn.rollback()
        self.assertEqual(self.conn.execute('SELECT dirty FROM similarity_count_state').fetchone(), (0,))
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE file_states SET presence_state='missing' WHERE current_path='/destination/distance-0.jpg'")
        self.assertEqual(reader.execute('SELECT dirty FROM similarity_count_state').fetchone(), (0,))
        reader.close()
        dirty = responses()
        self.assertNotEqual(dirty, before)
        old_cache = self.conn.execute('SELECT * FROM similarity_count_cache').fetchall()
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            return calls >= 2
        self.assertFalse(cache.refresh(self.conn, cancelled=cancel))
        self.assertEqual(self.conn.execute('SELECT dirty FROM similarity_count_state').fetchone(), (1,))
        self.assertEqual(self.conn.execute('SELECT * FROM similarity_count_cache').fetchall(), old_cache)
        self.assertEqual(responses(), dirty)
        self.assertTrue(cache.refresh(self.conn))
        self.assertEqual(responses(), dirty)
        # Representative replacement, hash and pair changes must never serve old rows.
        for statement in (
            f"UPDATE photos SET status='Pending' WHERE id={a}",
            "UPDATE contents SET phash='ffffffffffffffff' WHERE digest='content-3'",
            "DELETE FROM content_similarity",
            "DELETE FROM similarity_hashes",
        ):
            with ns_db.transaction(self.conn):
                self.conn.execute(statement)
            self.assertEqual(self.conn.execute('SELECT dirty FROM similarity_count_state').fetchone(), (1,))
            current = responses()
            self.assertTrue(cache.refresh(self.conn))
            self.assertEqual(responses(), current)

    def test_inspector_counts_are_cumulative_direct_and_deduplicated(self):
        a = self.photo('reference', 'a', '0000000000000000')
        duplicate = self.photo('reference-copy', 'a', '0000000000000000')
        distances = (0, 3, 4, 6, 7, 9, 10, 12, 13, 16, 17)
        for d in distances:
            self.photo(f'distance-{d}', f'content-{d}', f'{(1 << d)-1:016x}')
        self.photo('source-only', 'source', '0000000000000000', status='Pending')
        self.refresh()
        counts = self.client.get(f'/api/v1/similar/{a}/counts').json()
        self.assertEqual(counts['availability'], 'available')
        self.assertEqual(counts['pending'], 0)
        self.assertEqual([c['count'] for c in counts['counts']], [10, 8, 6, 4, 2, 1])
        self.assertEqual(counts, self.client.get(f'/api/v1/similar/{duplicate}/counts').json())
        for c in counts['counts']:
            result = self.client.get(f'/api/v1/similar/{a}?threshold={c["threshold"]}').json()
            self.assertEqual(result['total'], c['count'])

    def test_count_availability_is_not_reported_as_zero_matches(self):
        source = self.photo('source', 'a', '0000000000000000', status='Pending')
        failed = self.photo('failed-hash', 'b', None)
        pending = self.photo('pending-comparison', 'c', '0000000000000001')
        self.assertEqual(self.client.get(f'/api/v1/similar/{source}/counts').json()['availability'], 'not_available')
        result = self.client.get(f'/api/v1/similar/{failed}/counts').json()
        self.assertEqual((result['availability'], result['counts']), ('hash_unavailable', []))
        self.assertEqual(self.client.get(f'/api/v1/similar/{pending}/counts').json()['pending'], 1)
        self.refresh()
        self.assertEqual(self.client.get(f'/api/v1/similar/{pending}/counts').json()['pending'], 0)
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE file_states SET presence_state='missing' WHERE sha1_hash='c'")
        self.assertEqual(self.client.get(f'/api/v1/similar/{pending}/counts').json()['availability'], 'not_available')

    def test_gallery_similarity_view_shares_scope_with_filters_and_selection(self):
        a = self.photo('first', 'a', '0000000000000000')
        self.photo('exact-copy', 'a', '0000000000000000')
        b = self.photo('at-floor', 'b', '000000000000ffff')
        self.photo('isolated', 'c', 'ffffffffffffffff')
        self.photo('source-only', 'd', '0000000000000000', status='Pending')
        self.photo('failed-hash', 'e', None)
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE photos SET source_path=? WHERE id=?", (str(self.cfg.source / 'trip/first.jpg'), a))
            self.conn.execute("UPDATE photos SET metadata_json=? WHERE id=?", ('{"date_taken":"2023-01-01","date_source":"exif"}', a))
        self.refresh()
        listing = self.client.get('/api/v1/photos?view=similar').json()
        self.assertEqual({r['id'] for r in listing['items']}, {a, b})
        self.assertEqual(listing['counts']['similar'], 2)
        self.assertEqual(self.client.get('/api/v1/photos/ids?view=similar').json()['ids'], [a, b])
        for filters in ('q=first', 'date=2023', 'folder=trip'):
            got = self.client.get('/api/v1/photos?view=similar&'+filters).json()
            self.assertEqual([r['id'] for r in got['items']], [a], filters)
            self.assertEqual(got['matches']['similar'], 1)
            self.assertEqual(self.client.get('/api/v1/photos/ids?view=similar&'+filters).json()['ids'], [a])
        self.assertEqual(self.client.get('/api/v1/photos?view=similar&type=png').json()['total'], 0)
        self.assertEqual(self.client.get('/api/v1/photos?view=similar&undated=true').json()['total'], 1)
        self.assertEqual(self.client.get('/api/v1/photos/timeline?view=similar').json(),
                         {'months': [{'month': '2023-01', 'count': 1}], 'undated': 1})
        self.assertEqual(self.client.get('/api/v1/photos/types?view=similar').json()['types'], [{'type':'jpg', 'photos':2}])
        self.assertEqual(self.client.get('/api/v1/photos/folders?view=similar').json()['folders'][0]['photos'], 1)
        position = self.client.post('/api/v1/photos/position', json={'photo_id':a,'view':'similar','sort':'newest','page_size':1}).json()
        self.assertEqual((position['position'], position['page'], position['next_id']), (0, 1, b))
        # A recorded missing candidate removes both ends of the only relationship.
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE file_states SET presence_state='missing' WHERE sha1_hash='b'")
        self.assertEqual(self.client.get('/api/v1/photos?view=similar').json()['total'], 0)

    def test_warm_cache_preserves_gallery_paging_filters_selection_and_position(self):
        self.test_gallery_ranks_by_direct_count_before_paging_and_preserves_filter_scope(warm=True)

    def test_gallery_ranks_by_direct_count_before_paging_and_preserves_filter_scope(self, warm=False):
        a = self.photo('reference', 'a', '0000000000000000')
        b = self.photo('near', 'b', '0000000000000007')
        c = self.photo('further', 'c', '00000000000001ff')
        twin = self.photo('same-visual', 'twin', '0000000000000000')
        duplicate = self.photo('same-bytes', 'a', '0000000000000000')
        source = self.photo('source-only', 'source', '0000000000000000', status='Pending')
        failed = self.photo('unavailable', 'failed', None)
        self.refresh()
        if warm:
            from engine import ns_similarity_cache
            self.assertTrue(ns_similarity_cache.refresh(self.conn))
        query = '/api/v1/photos?view=similar&sort=matches&match_min=90'
        result = self.client.get(query).json()
        # b links the other three; a/twin do not directly match c at this threshold.
        self.assertEqual([(p['id'], p['similar_count']) for p in result['items']], [(b,3), (a,2), (twin,2), (c,1)])
        self.assertEqual(result['similarity'], {'threshold':90, 'pending':0, 'unavailable':1})
        for i, photo in enumerate((b,a,twin,c)):
            page = self.client.get(query + f'&page_size=1&page={i+1}').json()
            self.assertEqual([p['id'] for p in page['items']], [photo])
            position = self.client.post('/api/v1/photos/position', json={
                'photo_id':photo, 'view':'similar', 'sort':'matches', 'match_min':90, 'page_size':1}).json()
            self.assertEqual((position['position'],position['page']), (i,i+1))
            self.assertEqual(position['next_id'], (b,a,twin,c)[i+1] if i < 3 else None)
        filtered = self.client.get(query + '&q=reference').json()
        self.assertEqual([(p['id'],p['similar_count']) for p in filtered['items']], [(a,2)])
        # Counts match the Inspector at every UI threshold, independent of gallery filters.
        for threshold in (75,80,85,90,95,100):
            listing = self.client.get(f'/api/v1/photos?view=similar&sort=matches&match_min={threshold}').json()
            for item in listing['items']:
                count = self.client.get(f'/api/v1/similar/{item["id"]}?threshold={threshold}').json()['total']
                self.assertEqual(item['similar_count'], count)
        at100 = self.client.get('/api/v1/photos?view=similar&match_min=100').json()
        self.assertEqual({p['id'] for p in at100['items']}, {a,twin})
        self.assertEqual(self.client.get('/api/v1/photos/ids?view=similar&match_min=100').json()['ids'], [a,twin])
        self.assertEqual(self.client.get('/api/v1/photos/types?view=similar&match_min=100').json()['types'], [{'type':'jpg','photos':2}])
        self.assertEqual(self.client.get('/api/v1/photos/timeline?view=similar&match_min=100').json()['undated'], 2)
        selected = self.client.post('/api/v1/photos/selection', json={
            'ids':[source,failed,a,b,c], 'sort':'matches', 'match_min':100}).json()
        self.assertEqual(selected['total'], 5, 'Selection must retain photos without qualifying matches')
        self.assertEqual(selected['items'][0]['id'], a)
        position = self.client.post('/api/v1/photos/position', json={
            'photo_id':a, 'ids':[source,failed,a,b,c], 'sort':'matches', 'match_min':100}).json()
        self.assertEqual(position['position'], 0)
        self.assertNotIn(duplicate, [p['id'] for p in result['items']])
        # Relationships are joined to current membership; stale hashes/files cannot rank.
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE file_states SET presence_state='missing' WHERE sha1_hash='twin'")
        self.assertEqual(self.client.get('/api/v1/photos?view=similar&match_min=100').json()['total'], 0)
        self.photo('pending-new', 'pending-new', '000000000000ffff')
        self.assertEqual(self.client.get(query).json()['similarity']['pending'], 1)
        for path in ('photos','photos/ids','photos/types','photos/timeline','photos/folders'):
            self.assertEqual(self.client.get(f'/api/v1/{path}?view=similar&match_min=74').status_code, 422)
        self.assertEqual(self.client.post('/api/v1/photos/selection', json={'ids':[a],'sort':'matches','match_min':'90'}).status_code, 400)
        self.assertEqual(self.client.get('/api/v1/photos?view=all&sort=matches').status_code, 400)
        self.assertEqual(self.client.post('/api/v1/photos/position', json={
            'photo_id':a,'view':'invalid','sort':'matches','ids':[a]}).status_code, 400)

    def test_a_pair_compares_two_delivered_photos_and_changes_nothing(self):
        a = self.photo('first', 'a', '0000000000000000')
        b = self.photo('second', 'b', 'ffffffffffffffff')
        before = self.conn.execute('SELECT id,source_path,status,sha1_hash FROM photos ORDER BY id').fetchall()
        pair = self.client.get(f'/api/v1/similar/{a}/pair/{b}').json()
        self.assertEqual((pair['distance'], pair['score'], pair['exact']), (64, 0, False))
        self.assertEqual((pair['reference']['id'], pair['candidate']['id']), (a, b))
        self.assertEqual((pair['reference']['sha1'], pair['candidate']['sha1']), ('a', 'b'))
        self.assertNotIn('feedback', pair)
        self.assertEqual(self.client.put(f'/api/v1/similar/{a}/pair/{b}', json={}).status_code, 405)
        self.assertEqual(before, self.conn.execute('SELECT id,source_path,status,sha1_hash FROM photos ORDER BY id').fetchall())

    def test_a_pair_needs_two_available_photos(self):
        a = self.photo('first', 'a', None)
        b = self.photo('duplicate', 'a', None)
        route = f'/api/v1/similar/{a}/pair/{b}'
        pair = self.client.get(route).json()
        self.assertTrue(pair['exact'])
        self.assertIsNone(pair['distance'])
        self.assertEqual(self.client.get(f'/api/v1/similar/{a}/pair/999999').status_code, 409)
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE file_states SET presence_state='missing' WHERE current_path='/destination/duplicate.jpg'")
        self.assertEqual(self.client.get(route).status_code, 409)

    def test_diagnostics_counts_hashes_and_pairs_without_inventing_a_timing(self):
        self.photo('first','a','FFFFFFFFFFFFFFFF')
        self.photo('second','b','fffffffffffffffe')
        self.photo('invalid','c','bad')
        before = self.client.get('/api/v1/similar/diagnostics').json()
        self.assertEqual(before['distinct_hashes'], 2)
        self.assertIsNone(before['last_comparison'])
        self.assertEqual(before['state']['pending'], 2)
        self.refresh()
        after = self.client.get('/api/v1/similar/diagnostics').json()
        self.assertEqual(after['stored_pairs'], 1)
        self.assertEqual(after['state']['pending'], 0)
        self.assertEqual(after['state']['unavailable'], 1)
        self.assertGreaterEqual(after['query_ms'], 0)

    def test_reference_matches_are_not_transitive_and_thresholds_are_exact(self):
        a = self.photo('reference', 'a', '0000000000000000')
        b = self.photo('near', 'b', '000000000000003f', width=1280)
        c = self.photo('chain-only', 'c', '0000000000000fff')
        self.refresh()
        result = self.client.get(f'/api/v1/similar/{a}').json()
        self.assertEqual([p['id'] for p in result['items']], [b])
        self.assertEqual(result['items'][0]['score'], 90.62)
        self.assertEqual(result['largest_pixels'], 1280*480)
        self.assertEqual(self.client.get(f'/api/v1/similar/{a}?threshold=91').json()['total'], 0)
        self.assertEqual(self.client.get(f'/api/v1/similar/{b}').json()['total'], 2)
        self.assertNotEqual(a, c)

    def test_equal_hashes_collapse_exact_content_but_exact_mode_keeps_copies(self):
        a = self.photo('original', 'a', 'FFFFFFFFFFFFFFFF')
        duplicate = self.photo('copy', 'a', 'ffffffffffffffff')
        b = self.photo('other-bytes', 'b', 'ffffffffffffffff')
        self.refresh()
        result = self.client.get('/api/v1/similar?threshold=100').json()
        self.assertEqual({p['id'] for p in result['items']}, {a,b})
        result = self.client.get(f'/api/v1/similar/{duplicate}?threshold=100').json()
        self.assertEqual([p['id'] for p in result['items']], [b])
        result = self.client.get(f'/api/v1/similar/{a}?mode=exact').json()
        self.assertEqual([p['id'] for p in result['items']], [duplicate])

    def test_changed_hash_missing_hash_and_missing_file_do_not_claim_matches(self):
        a = self.photo('first', 'a', '0000000000000000')
        b = self.photo('second', 'b', '0000000000000001')
        missing = self.photo('unreadable', 'missing', None)
        self.refresh()
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE contents SET phash='ffffffffffffffff' WHERE digest='b'")
        self.assertEqual(self.client.get(f'/api/v1/similar/{a}').json()['total'], 0)
        self.assertEqual(self.client.get('/api/v1/similar').json()['state'], {'photos':3,'unavailable':1,'pending':1})
        self.assertEqual(self.client.get(f'/api/v1/similar/{missing}').json()['availability'], 'hash_unavailable')
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE file_states SET presence_state='missing' WHERE sha1_hash='b'")
        self.assertEqual(self.client.get(f'/api/v1/similar/{b}').json()['availability'], 'not_available')

    def test_search_pagination_and_input_validation(self):
        for i in range(7):
            self.photo(f'item-{i}', str(i), '0000000000000000')
        self.refresh()
        first = self.client.get('/api/v1/similar?page_size=3').json()
        second = self.client.get('/api/v1/similar?page_size=3&page=2').json()
        self.assertEqual(first['total'], 7)
        self.assertEqual(len(first['items']), 3)
        self.assertTrue({p['id'] for p in first['items']}.isdisjoint(p['id'] for p in second['items']))
        self.assertEqual(self.client.get('/api/v1/similar?q=item-2').json()['total'], 1)
        self.assertEqual(self.client.get('/api/v1/similar?q=%25').json()['total'], 0)
        for query in ('threshold=74', 'threshold=101', 'threshold=nan', 'page=0', 'page_size=61'):
            self.assertEqual(self.client.get('/api/v1/similar?'+query).status_code, 422, query)
        for query in ('mode=other', 'sort=other'):
            self.assertEqual(self.client.get('/api/v1/similar?'+query).status_code, 400, query)

    def test_75_floor_includes_sixteen_bits_but_excludes_seventeen(self):
        a = self.photo('reference', 'a', '0000000000000000')
        edge = self.photo('at-floor', 'b', '000000000000ffff')
        self.photo('below-floor', 'c', '000000000001ffff')
        self.refresh()
        result = self.client.get(f'/api/v1/similar/{a}?threshold=75').json()
        self.assertEqual([(p['id'], p['score']) for p in result['items']], [(edge, 75.0)])
        self.assertEqual(self.client.get(f'/api/v1/similar/{a}?threshold=76').json()['total'], 0)
        self.assertIn(a, [p['id'] for p in self.client.get('/api/v1/similar?threshold=75').json()['items']])
        self.assertNotIn(a, [p['id'] for p in self.client.get('/api/v1/similar?threshold=76').json()['items']])

    def test_only_delivered_photos_can_be_matched_or_compared(self):
        delivered = [self.photo(status, status, '0000000000000000', status=status)
                     for status in ('Copied', 'Completed', 'Found_At_Destination')]
        source_only = [self.photo(status, 'Copied', '0000000000000000', status=status)
                       for status in ('Pending', 'Duplicate', 'Failed', 'Processing')]
        # Even a projected destination pointing at matching content is not delivery.
        with ns_db.transaction(self.conn):
            for photo in source_only:
                self.conn.execute("UPDATE photos SET dest_path='/destination/Copied.jpg' WHERE id=?", (photo,))
        self.refresh()
        queue = self.client.get('/api/v1/similar').json()
        self.assertEqual({p['id'] for p in queue['items']}, set(delivered))
        self.assertEqual(queue['state']['photos'], 3)
        for photo in source_only:
            for mode in ('similar', 'exact'):
                self.assertEqual(self.client.get(f'/api/v1/similar/{photo}?mode={mode}').json()['availability'], 'not_available')
            self.assertEqual(self.client.get(f'/api/v1/similar/{photo}/pair/{delivered[1]}').status_code, 409)

    def test_missing_or_changed_destination_never_falls_back_to_source(self):
        a = self.photo('first', 'a', '0000000000000000')
        b = self.photo('second', 'b', '0000000000000000')
        self.refresh()
        route = f'/api/v1/similar/{a}/pair/{b}'
        self.assertEqual(self.client.get(route).status_code, 200)
        for presence, digest in (('missing', 'b'), ('present', 'changed')):
            with ns_db.transaction(self.conn):
                self.conn.execute("UPDATE file_states SET presence_state=?,sha1_hash=? WHERE current_path='/destination/second.jpg'",
                                  (presence, digest))
            self.assertEqual(self.client.get('/api/v1/similar').json()['state']['photos'], 1)
            self.assertEqual(self.client.get(f'/api/v1/similar/{b}').json()['availability'], 'not_available')
            self.assertEqual(self.client.get(route).status_code, 409)
        self.assertEqual(self.conn.execute("SELECT presence_state FROM file_states WHERE current_path='/source/second.jpg'").fetchone()[0], 'present')


if __name__ == "__main__":
    unittest.main()
