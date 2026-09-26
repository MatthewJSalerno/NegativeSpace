"""tests/make_scenarios.py against a seed folder it must never write to, and the real
engine's Index against what it builds, so the manifest's expectations are checked
rather than assumed.

    docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app -w /app \\
      negativespace python3 -m unittest discover -s tests -p make_scenarios_test.py -v
"""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tests" / "make_scenarios.py"
sys.path.insert(0, str(REPO))
from PIL import Image  # noqa: E402


def run(*args, check=True):
    done = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    if check and done.returncode:
        raise AssertionError(f"make_scenarios.py {args[0]} failed:\n{done.stderr[-2000:]}")
    return done


def fingerprint(root: Path) -> dict:
    """Bytes and times of every file: what a write through a hard link would change."""
    return {str(p.relative_to(root)): (hashlib.sha1(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def make_seed(folder: Path, n=40):
    for i in range(n):
        path = folder / f"album-{i % 3}" / f"seed-{i:02d}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        exif = Image.Exif()
        exif.get_ifd(0x8769)[36867] = f"20{10 + i % 10}:0{1 + i % 9}:15 12:00:00"
        Image.new("RGB", (320 + i, 240), (i * 5 % 256, 100, 200 - i)).save(path, "JPEG", exif=exif)
        os.utime(path, (1_500_000_000 + i, 1_500_000_000 + i))


class MakeScenarios(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ns-scenarios-"))
        self.seed = self.root / "seed"
        make_seed(self.seed)
        self.out = self.root / "demo"

    def tearDown(self):
        for p in self.root.rglob("*"):
            if p.is_file() and not p.is_symlink():
                p.chmod(0o644)
        shutil.rmtree(self.root, ignore_errors=True)

    def manifest(self):
        return json.loads((self.out / "manifest.json").read_text())

    def test_the_seed_is_never_written_to_by_a_build_or_a_change(self):
        before = fingerprint(self.seed)
        done = run("build", "--seed-dir", str(self.seed), "--out", str(self.out))
        self.assertIn("seed: 40 file(s), untouched by this run", done.stdout)
        done = run("change", "--out", str(self.out))
        self.assertIn("untouched", done.stdout)
        self.assertEqual(fingerprint(self.seed), before, "a seed photo changed through a hard link")
        # Every altered file broke its link first: none shares an inode with the seed.
        seed_inodes = {p.stat().st_ino for p in self.seed.rglob("*") if p.is_file()}
        edited = [c for c in self.manifest()["changes"] if c["kind"] in ("edited_in_place", "replaced", "touched_only")]
        for c in edited:
            self.assertNotIn((self.out / "library" / c["path"]).stat().st_ino, seed_inodes, c["kind"])

    def test_the_originals_are_links_and_every_scenario_is_made(self):
        run("build", "--seed-dir", str(self.seed), "--out", str(self.out))
        files = self.manifest()["files"]
        originals = [f for f in files if f["scenario"] == "original"]
        self.assertEqual(len(originals), 40)
        self.assertTrue(all(f["hard_link"] for f in originals))
        lib = self.out / "library"
        for f in files:
            path = lib / f["path"]
            self.assertTrue(path.is_symlink() or path.exists(), f["path"])
        scenarios = {f["scenario"] for f in files}
        for wanted in ("exact_duplicate", "duplicate_without_exif", "resized_with_exif", "resized_without_exif",
                       "format_converted", "date_no_date", "date_with_offset", "date_conflicting", "orientation",
                       "name_same_name", "name_case_only", "edge_zero_bytes", "edge_truncated", "edge_symlink",
                       "same_picture_2024", "same_picture_1969"):
            self.assertIn(wanted, scenarios)
        dups = [f for f in files if f["scenario"] == "exact_duplicate"]
        self.assertGreaterEqual(len(dups), 20)
        for d in dups:
            self.assertTrue(os.path.samefile(lib / d["path"], lib / d["from"]), "a duplicate is a second link")
        stripped = next(f for f in files if f["scenario"] == "duplicate_without_exif")
        tags = subprocess.run(["exiftool", "-s3", "-DateTimeOriginal", str(lib / stripped["path"])],
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(tags, "", "the no-EXIF duplicate still has a date taken")

    def test_a_seed_folder_filling_meanwhile_is_reported_not_mistaken_for_a_write(self):
        # A download adding photos during a build: the check must still pass, and say so.
        import threading, time
        def download():
            time.sleep(0.2)
            for i in range(5):
                Image.new("RGB", (50, 50)).save(self.seed / f"downloaded-{i}.jpg")
        t = threading.Thread(target=download)
        t.start()
        done = run("build", "--seed-dir", str(self.seed), "--out", str(self.out))
        t.join()
        self.assertIn("untouched by this run", done.stdout)
        if "appeared" in done.stdout:
            self.assertIn("another program", done.stdout)

    def test_it_replaces_only_its_own_output(self):
        self.out.mkdir()
        (self.out / "someone-elses.txt").write_text("keep me")
        refused = run("build", "--seed-dir", str(self.seed), "--out", str(self.out), check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual((self.out / "someone-elses.txt").read_text(), "keep me")
        other = self.root / "demo2"
        run("build", "--seed-dir", str(self.seed), "--out", str(other))
        again = run("build", "--seed-dir", str(self.seed), "--out", str(other), check=False)
        self.assertNotEqual(again.returncode, 0, "an earlier build is rebuilt only when asked")
        run("build", "--seed-dir", str(self.seed), "--out", str(other), "--replace")
        missing = run("build", "--out", str(self.root / "no-parent" / "demo"), check=False)
        self.assertNotEqual(missing.returncode, 0, "a missing parent is refused, never created")

    def test_the_engine_indexes_the_scenarios_as_the_manifest_says(self):
        run("build", "--out", str(self.out))                     # generated seeds: no folder needed
        work = self.root / "engine"
        for name in ("dest", "appdata", "cache", "backups"):
            (work / name).mkdir(parents=True)
        subprocess.run([sys.executable, str(REPO / "ns-engine.py"), "--source", str(self.out / "library"),
                        "--dest", str(work / "dest"), "--base", str(work / "appdata"), "--cache", str(work / "cache"),
                        "--backups", str(work / "backups")], capture_output=True, text=True, timeout=600)
        db = sqlite3.connect(work / "appdata" / "db" / "ns_sqlite.db")
        status = dict(db.execute("SELECT status, COUNT(*) FROM photos GROUP BY status").fetchall())
        files = self.manifest()["files"]
        self.assertGreaterEqual(status.get("Duplicate", 0), sum(f["scenario"] == "exact_duplicate" for f in files))
        paths = {Path(p).name for (p,) in db.execute("SELECT source_path FROM photos")}
        self.assertNotIn("symlink-to-a-photo.jpg", paths, "a symlink was followed")
        self.assertNotIn("with-sidecar.xmp", paths)
        failed = {Path(p).name for (p,) in db.execute(
            "SELECT source_path FROM operations WHERE status = 'Failed' AND source_path IS NOT NULL")}
        if os.geteuid() != 0:
            self.assertIn("unreadable.jpg", failed, "an unreadable file fails with a reason")
        # A photo's name with no image inside: logged as Failed, "Not an image", and left alone.
        reasons = dict(db.execute("SELECT source_path, error_message FROM operations WHERE status = 'Failed'"))
        for name in ("zero-bytes.jpg", "not-a-photo.jpg"):
            self.assertIn(name, failed, f"{name} must be logged as a bad file")
            self.assertTrue(next(r for p, r in reasons.items() if p.endswith(name)).startswith("Not an image"))
        undated = dict(db.execute(
            "SELECT basename, json_extract(metadata_json, '$.date_source') FROM "
            "(SELECT replace(source_path, rtrim(source_path, replace(source_path, '/', '')), '') AS basename, "
            " metadata_json FROM photos)").fetchall())
        no_date = next(Path(f["path"]).name for f in files if f["scenario"] == "date_no_date")
        self.assertEqual(undated.get(no_date), "file_mtime", "a photo with no date must be filed by file time")
        # One picture, two dates: two photos, filed 55 years apart, with the same perceptual hash.
        pair = {}
        for year in ("2024", "1969"):
            name = next(Path(f["path"]).name for f in files if f["scenario"] == f"same_picture_{year}")
            pair[year] = db.execute("SELECT json_extract(metadata_json, '$.date_taken'), phash FROM photos "
                                    "WHERE source_path LIKE ?",
                                    (f"%/{name}",)).fetchone()
            self.assertTrue(pair[year][0].startswith(year), f"{name} was filed {pair[year][0]}")
        self.assertEqual(pair["2024"][1], pair["1969"][1], "the same pixels should give the same pHash")


if __name__ == "__main__":
    unittest.main()
