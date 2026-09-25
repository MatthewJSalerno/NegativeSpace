"""The web API against a real engine and a real catalog (webui-spec 5-6).

Jobs run the actual ns-engine.py as a child process, as they do in production, so
these tests cover the request-to-run handshake, the lock, cancellation and the
derived outcome together rather than each against a stub.

    docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app -w /app \\
      negativespace python3 -m unittest discover -s tests -p webui_api_test.py -v
"""
import contextlib
import fcntl
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

import ns_db  # noqa: E402
from webui.app import create_app  # noqa: E402
from webui.config import Config  # noqa: E402


def make_photo(path: Path, seed: str, size=(64, 48), mtime=None):
    """A small, valid JPEG whose pixels depend on `seed`; the same seed gives the
    same bytes, so two calls make an exact duplicate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    value = sum(seed.encode()) % 256
    Image.new("RGB", size, (value, 255 - value, (value * 7) % 256)).save(path, "JPEG", quality=90)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class ApiCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ns-webui-"))
        for name in ("src", "dest", "appdata", "cache", "backups", "static"):
            (self.root / name).mkdir()
        self.cfg = Config(base=self.root / "appdata", source=self.root / "src", dest=self.root / "dest",
                          cache=self.root / "cache", backups=self.root / "backups",
                          static=self.root / "static")
        self.client = TestClient(create_app(self.cfg))

    def tearDown(self):
        self.client.close()
        shutil.rmtree(self.root, ignore_errors=True)

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
        mov = self.client.post("/api/v1/settings/validate-extension", json={"extension": "MOV"}).json()
        self.assertFalse(mov["supported"])
        self.assertTrue(mov["warning"])


class JobsAndCatalog(ApiCase):
    def index_library(self):
        make_photo(self.cfg.source / "trip" / "IMG_0001.jpg", "a", mtime=1_600_000_000)
        make_photo(self.cfg.source / "trip" / "Beach Sunset.jpg", "a", mtime=1_600_000_000)
        make_photo(self.cfg.source / "IMG_0002.jpg", "b", mtime=1_700_000_000)
        self.create_catalog()
        return self.wait_for(self.start(mode="index"))

    def test_an_index_through_the_api_reports_a_derived_outcome_and_fills_the_gallery(self):
        run = self.index_library()
        self.assertEqual((run["mode"], run["status"], run["outcome"]["verdict"]), ("INDEX", "Completed", "success"))
        self.assertEqual(run["outcome"]["counts"], {"indexed": 2, "duplicates": 1})

        page = self.client.get("/api/v1/photos").json()
        self.assertEqual((page["total"], page["counts"]["organized"], page["counts"]["unorganized"]), (2, 0, 2))
        self.assertEqual([i["date_taken"][:4] for i in page["items"]], ["2023", "2020"], "not newest first")
        self.assertEqual(sorted(i["duplicates"] for i in page["items"]), [0, 1])

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
        self.assertTrue(detail["dest_path_is_projection"])
        self.assertEqual(self.client.get("/api/v1/photos/999999/inspect").status_code, 404)

    def test_a_copy_through_the_api_counts_the_requested_work_only(self):
        self.index_library()
        run = self.wait_for(self.start(mode="copy"))
        self.assertEqual(run["outcome"]["verdict"], "success")
        self.assertEqual(run["outcome"]["counts"], {"Copied": 2, "Skipped": 1},
                         "the Copy's scan was counted as its work")
        organized = self.client.get("/api/v1/photos", params={"view": "organized"}).json()
        self.assertEqual(organized["total"], 2)
        again = self.wait_for(self.start(mode="copy"))
        self.assertEqual(again["outcome"]["verdict"], "no_change")

    def test_one_job_at_a_time_and_the_lock_decides(self):
        self.index_library()
        with self.engine_lock_held():
            busy = self.client.post("/api/v1/jobs/start", json={"mode": "index"})
            self.assertEqual((busy.status_code, busy.json()["error"]), (409, "job_already_running"))
            active = self.client.get("/api/v1/jobs/active").json()["active"]
            self.assertTrue(active and active["unrecorded"], f"a held lock was not shown as a job: {active}")

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
                            ({"mode": "move", "file_ids": list(range(1, 1002))}, "selection_too_large")):
            response = self.client.post("/api/v1/jobs/start", json=body)
            self.assertEqual((response.status_code, response.json()["error"]), (400, error), body)
        with contextlib.closing(sqlite3.connect(self.cfg.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1,
                             "a refused request started an engine")

    def test_the_job_stream_sends_the_current_state_on_connect(self):
        self.index_library()
        with self.client.websocket_connect("/api/v1/ws/jobs") as ws:
            state = ws.receive_json()
        self.assertIsNone(state["active"])
        self.assertEqual(state["last"]["mode"], "INDEX")


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
        self.assertEqual(self.run_with("MOVE", [scan, ("transferring", 3, {"Failed": 3})])["verdict"], "failed",
                         "a Completed run where every file failed read as success")
        self.assertEqual(self.run_with("COPY", [scan, ("transferring", 3, {"Copied": 2, "Failed": 1})])["verdict"],
                         "partial")
        self.assertEqual(self.run_with("COPY", [scan, ("transferring", 3, {"Skipped": 3})])["verdict"], "no_change")
        self.assertEqual(self.run_with("INDEX", [("scanning", 10, {"unchanged": 10})])["verdict"], "no_change")
        cancelled = self.run_with("MOVE", [scan, ("transferring", 3, {"Completed": 1, "Cancelled": 2})],
                                  status=ns_db.RunStatus.CANCELLED)
        self.assertEqual((cancelled["verdict"], cancelled["succeeded"], cancelled["cancelled"]), ("cancelled", 1, 2))


class ServingTheApp(ApiCase):
    def test_client_routes_load_the_app_and_unknown_api_paths_stay_404(self):
        (self.cfg.static / "index.html").write_text("<html>app</html>")
        (self.cfg.static / "assets").mkdir()
        client = TestClient(create_app(self.cfg))
        self.assertEqual(client.get("/gallery/42").text, "<html>app</html>")
        self.assertEqual(client.get("/api/v1/nothing-here").status_code, 404)
        self.assertEqual(client.get("/../../etc/passwd").text, "<html>app</html>")
        client.close()


if __name__ == "__main__":
    unittest.main()
