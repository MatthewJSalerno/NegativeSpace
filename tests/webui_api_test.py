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
        for name in ("src", "dest", "appdata", "cache", "backups"):
            (self.root / name).mkdir()
        self.cfg = Config(base=self.root / "appdata", source=self.root / "src", dest=self.root / "dest",
                          cache=self.root / "cache", backups=self.root / "backups")
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
        again = self.wait_for(self.start(mode="copy"))
        self.assertEqual(again["outcome"]["verdict"], "no_change")

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
        self.assertEqual(only_2023["counts"]["all"], 1, "the view counts must follow the date filter")
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
        self.assertEqual((ids["total"], ids["over_limit"]), (1, False))
        self.assertEqual(ids["ids"], [i["id"] for i in photos(date=["2020"])["items"]],
                         "Select all must take exactly the photos the filters show")

    def test_select_all_over_the_limit_is_refused_whole_not_cut_short(self):
        self.index_library()
        from webui import catalog
        over = catalog.photo_ids(self.cfg.db_path, limit=1)
        self.assertEqual((over["over_limit"], over["total"], over["ids"]), (True, 2, []))

    def test_the_selection_shows_photos_every_filter_hides_and_names_missing_ones(self):
        self.index_library()
        dated_2020 = self.client.get("/api/v1/photos", params={"date": "2020"}).json()["items"][0]["id"]
        shown = self.client.post("/api/v1/photos/selection",
                                 json={"ids": [dated_2020, 99999], "sort": "newest"}).json()
        self.assertEqual([i["id"] for i in shown["items"]], [dated_2020])
        self.assertEqual((shown["total"], shown["missing"]), (1, [99999]),
                         "a photo gone from the catalog must be named, not silently dropped")
        refused = self.client.post("/api/v1/photos/selection", json={"ids": list(range(1, 1002))})
        self.assertEqual(refused.status_code, 400)

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
        # used to see each other's hold on the start lock and show a job.
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
        self.assertEqual((retry["photo_ids"], retry["more_than_limit"]), ([op["photo_id"]], False))

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

    def test_a_photos_history_follows_it_through_a_move(self):
        make_photo(self.cfg.source / "a.jpg", "a")
        self.create_catalog()
        self.wait_for(self.start(mode="index"))
        photo = self.client.get("/api/v1/photos").json()["items"][0]["id"]
        self.wait_for(self.start(mode="move"))
        history = self.client.get("/api/v1/operations", params={"photo": photo}).json()
        self.assertEqual(sorted(i["status"] for i in history["items"]), ["Completed", "Pending"])

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
        self.assertEqual(self.run_with("MOVE", [scan, ("transferring", 3, {"Failed": 3})])["verdict"], "failed",
                         "a Completed run where every file failed read as success")
        self.assertEqual(self.run_with("COPY", [scan, ("transferring", 3, {"Copied": 2, "Failed": 1})])["verdict"],
                         "partial")
        self.assertEqual(self.run_with("COPY", [scan, ("transferring", 3, {"Skipped": 3})])["verdict"], "no_change")
        self.assertEqual(self.run_with("INDEX", [("scanning", 10, {"unchanged": 10})])["verdict"], "no_change")
        cancelled = self.run_with("MOVE", [scan, ("transferring", 3, {"Completed": 1, "Cancelled": 2})],
                                  status=ns_db.RunStatus.CANCELLED)
        self.assertEqual((cancelled["verdict"], cancelled["succeeded"], cancelled["cancelled"]), ("cancelled", 1, 2))


if __name__ == "__main__":
    unittest.main()
