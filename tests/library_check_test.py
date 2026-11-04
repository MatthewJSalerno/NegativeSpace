"""Check library through the web API (webui-spec 7.6): the job, the sidebar status, a
check's findings and export, and the Library check review reason. Generated photos."""

import csv
import io
import os
from pathlib import Path

import unittest

from engine import ns_db
from webui_api_test import ApiCase, make_photo


class LibraryCheck(ApiCase):
    def setUp(self):
        super().setUp()
        self.create_catalog()
        for name in ("one", "two"):
            make_photo(self.cfg.source / f"{name}.jpg", name, exif={36867: "2001:02:03 04:05:06"})
        self.wait_for(self.start(mode="index"))
        self.wait_for(self.start(mode="copy"))
        with ns_db.connect(self.cfg.db_path) as conn:
            self.placed = {Path(s).stem: (i, Path(d)) for i, s, d in conn.execute("SELECT id, source_path, dest_path FROM photos")}

    def check(self, depth="quick", **extra):
        response = self.client.post("/api/v1/jobs/check-library", json={"depth": depth, **extra})
        self.assertEqual(response.status_code, 202, response.text)
        return self.wait_for(response.json()["id"])

    def status(self):
        return self.client.get("/api/v1/library-check").json()

    def test_a_clean_check_reads_as_all_as_recorded_and_finished(self):
        before = self.status()
        self.assertIsNotNone(before["source"])
        self.assertIsNone(before["latest"])
        self.assertIsNone(before["result"])
        run = self.check()
        self.assertEqual((run["mode"], run["status"], run["outcome"]["verdict"]), ("CHECK", "Completed", "success"))
        self.assertEqual((run["library_check"]["depth"], run["library_check"]["tone"], run["library_check"]["intact"]),
                         ("quick", "plain", 2))
        after = self.status()
        self.assertEqual(after["latest"]["run_id"], run["id"])
        self.assertEqual(after["result"]["run_id"], run["id"])

    def test_a_missing_photo_is_a_review_reason_until_a_later_check_finds_it(self):
        pid, path = self.placed["one"]
        data = path.read_bytes()
        path.unlink()
        os.unlink(self.cfg.source / "one.jpg")        # no copy anywhere: lost
        run = self.check("thorough")
        self.assertEqual(run["library_check"]["depth"], "full")
        page = self.client.get(f"/api/v1/library-check/{run['id']}").json()
        self.assertEqual((page["tone"], page["lost"], page["total"]), ("bad", 1, 1))
        self.assertEqual([(f["photo_id"], f["finding"], f["tone"]) for f in page["findings"]], [(pid, "missing", "bad")])
        listed = self.client.get("/api/v1/photos", params={"view": "review", "reason": "library"}).json()
        self.assertEqual([p["id"] for p in listed["items"]], [pid])
        self.assertEqual(listed["reasons"]["library"], 1)
        reasons = self.client.get(f"/api/v1/photos/{pid}/review").json()["reasons"]
        self.assertEqual([(r["reason"], r["tone"], r["run_id"]) for r in reasons], [("library", "bad", run["id"])])

        exported = self.client.get(f"/api/v1/library-check/{run['id']}/export", params={"format": "csv"})
        self.assertEqual(exported.status_code, 200)
        self.assertIn("attachment", exported.headers["content-disposition"])
        rows = list(csv.DictReader(io.StringIO(exported.text)))
        self.assertEqual([(r["finding"], r["photo_id"], r["relative"]) for r in rows],
                         [("missing", str(pid), os.path.relpath(path, ns_db.library_root(self.cfg.dest.resolve())))])
        self.assertEqual(self.client.get(f"/api/v1/library-check/{run['id']}/export", params={"format": "json"}).json()[0]["tone"], "bad")

        path.write_bytes(data)
        os.utime(path, (self.mtime_of("one"),) * 2)
        self.check()
        self.assertEqual(self.client.get("/api/v1/photos", params={"view": "review", "reason": "library"}).json()["items"], [])

    def mtime_of(self, stem):
        with ns_db.connect(self.cfg.db_path) as conn:
            return conn.execute("SELECT file_mtime FROM photos WHERE id=?", (self.placed[stem][0],)).fetchone()[0]

    def test_a_library_that_is_not_there_is_not_checked_and_the_last_result_stands(self):
        first = self.check()
        library = ns_db.library_root(self.cfg.dest.resolve())
        library.rename(library.with_name("unplugged"))
        response = self.client.post("/api/v1/jobs/check-library", json={"depth": "quick"})
        self.assertEqual(response.status_code, 202, response.text)
        stopped = self.wait_for(response.json()["id"])
        self.assertEqual((stopped["status"], stopped["library_check"]["stopped"]), ("Failed", "library_missing"))
        status = self.status()
        self.assertEqual((status["latest"]["run_id"], status["result"]["run_id"]), (stopped["id"], first["id"]))
        self.assertEqual(self.client.get(f"/api/v1/library-check/{stopped['id']}").json()["total"], 0)

    def test_requests_are_validated_and_replayed(self):
        self.assertEqual(self.client.post("/api/v1/jobs/check-library", json={"depth": "full"}).status_code, 400)
        self.assertEqual(self.client.post("/api/v1/jobs/check-library", json={"depth": "quick", "extra": 1}).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/library-check/999").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/library-check/999/export").status_code, 404)
        run = self.check(request_id="check-once")
        again = self.client.post("/api/v1/jobs/check-library", json={"depth": "quick", "request_id": "check-once"})
        self.assertEqual(again.json()["id"], run["id"])
        conflict = self.client.post("/api/v1/jobs/check-library", json={"depth": "thorough", "request_id": "check-once"})
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(self.client.get(f"/api/v1/library-check/{run['id']}/export", params={"format": "xml"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
