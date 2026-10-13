"""tools/make_scenarios.py against a seed folder it must never write to, and the real
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
import unicodedata
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "make_scenarios.py"
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
        if os.environ.get('NS_TEST_KEEP') == '1':
            return
        from tools import make_scenarios
        make_scenarios.unlock(self.root)
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

    def test_undated_photos_get_a_donors_camera_tags_and_the_donors_stay_out(self):
        plain = self.seed / "no-exif"
        plain.mkdir()
        for i in range(8):
            Image.new("RGB", (320, 240), (i * 30, 90, 160)).save(plain / f"plain-{i}.jpg", "JPEG")
        donors = self.seed / "donors"             # inside the seed, as downloaded
        donors.mkdir()
        for i in range(5):
            exif = Image.Exif()
            exif[0x010F], exif[0x0110], exif[0x0112] = "DonorCam", f"Model {i}", 6
            exif.get_ifd(0x8769)[36867] = "2004:05:06 07:08:09"
            Image.new("RGB", (8, 8), (200, 10, 10)).save(donors / f"donor-{i}.jpg", "JPEG", exif=exif)
        before = fingerprint(self.seed)
        done = run("build", "--seed-dir", str(self.seed), "--out", str(self.out), "--exif-donors", str(donors))
        self.assertIn("untouched by this run", done.stdout)
        self.assertEqual(fingerprint(self.seed), before, "a seed or donor file changed")
        files = self.manifest()["files"]
        self.assertFalse([f for f in files if f["scenario"] == "original" and "donors" in f["path"]],
                         "a donor folder inside the seed must not become originals")
        grafted = [f for f in files if "exif_from" in f]
        self.assertEqual(len(grafted), 6, "three in four of the 8 undated JPEGs")
        self.assertTrue(all("no-exif" in f["path"] for f in grafted), "a photo with its own date keeps it")
        tags = json.loads(subprocess.run(
            ["exiftool", "-j", "-Make", "-Orientation", "-ImageWidth", "-DateTimeOriginal",
             *[str(self.out / "library" / f["path"]) for f in grafted]], capture_output=True, text=True).stdout)
        for t in tags:
            self.assertEqual((t.get("Make"), t.get("ImageWidth"), t.get("DateTimeOriginal")),
                             ("DonorCam", 320, "2004:05:06 07:08:09"), t["SourceFile"])
            self.assertNotIn("Orientation", t, "a donor's rotation would turn the picture sideways")
        self.assertEqual(sum(f["scenario"] == "tiny_camera_file" for f in files), 5)

    def test_the_originals_are_links_and_every_scenario_is_made(self):
        run("build", "--seed-dir", str(self.seed), "--out", str(self.out))
        files = self.manifest()["files"]
        originals = [f for f in files if f["scenario"] == "original"]
        self.assertEqual(len(originals), 40)
        self.assertTrue(all(f["hard_link"] for f in originals))
        lib = self.out / "library"
        for f in files:
            path = lib / f["path"]
            if f["scenario"] == "edge_locked_folder":
                # Nothing inside can be looked at, by design: the folder itself is there, locked.
                self.assertEqual(path.parent.lstat().st_mode & 0o777, 0, f["path"])
                continue
            self.assertTrue(path.is_symlink() or path.exists(), f["path"])
        scenarios = {f["scenario"] for f in files}
        for wanted in ("exact_duplicate", "duplicate_without_exif", "resized_with_exif", "resized_without_exif",
                       "format_converted", "date_no_date", "date_with_offset", "date_conflicting", "orientation",
                       "name_same_name", "name_case_only", "edge_zero_bytes", "edge_truncated", "edge_symlink",
                       "same_picture_2024", "same_picture_1969", "nas_synology_thumbnail", "nas_qnap_thumbnail",
                       "nas_recycle_bin", "live_photo_still", "live_photo_video", "motion_photo", "date_in_name_only",
                       "clock_off_camera", "clock_off_phone", "day_boundary", "burst_same_second",
                       "look_alike_rotated_90", "look_alike_cropped", "large_image", "format_cmyk_jpeg",
                       "format_multi_page_tiff", "unicode_nfc", "unicode_nfd", "case_at_destination",
                       "edge_locked_folder"):
            self.assertIn(wanted, scenarios)
        # Every scenario file whose name is not itself the scenario can be found by a filename
        # search: its name starts scn- and is its own.
        exempt = {"original", "name_same_name", "name_names", "name_case_only", "date_in_name_only", "date_nowhere",
                  "unicode_nfc", "unicode_nfd", "case_at_destination", "nas_synology_thumbnail", "nas_qnap_thumbnail"}
        searchable = [Path(f["path"]).name for f in files if f["scenario"] not in exempt]
        self.assertEqual([n for n in searchable if "scn-" not in n], [])
        self.assertEqual(len({n.lower() for n in searchable}), len(searchable), "a name shared by two scenario files")
        # The two Unicode names look the same and are two names.
        nfc, nfd = (next(f["path"] for f in files if f["scenario"] == s) for s in ("unicode_nfc", "unicode_nfd"))
        self.assertNotEqual(nfc, nfd)
        self.assertEqual(unicodedata.normalize("NFC", nfd), nfc)
        # Each motion photo's video is found by ExifTool where its phone puts it, and is the
        # video the manifest records.
        tag = {"google_legacy": "File:EmbeddedVideo", "pixel": "Google:MotionPhotoVideo",
               "samsung": "Samsung:EmbeddedVideoFile"}
        motions = [f for f in files if f["scenario"] == "motion_photo"]
        self.assertEqual({f["variant"] for f in motions}, set(tag))
        for f in motions:
            video = subprocess.run(["exiftool", "-b", "-ee", f"-{tag[f['variant']]}", str(lib / f["path"])],
                                   capture_output=True, check=True).stdout
            self.assertEqual((len(video), hashlib.sha1(video).hexdigest()), (f["video_length"], f["video_sha1"]),
                             f["variant"])
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
        dest = Path(os.environ['NS_TEST_DESTINATION_ROOT']) / self.root.name if os.environ.get('NS_TEST_DESTINATION_ROOT') else work / 'dest'
        dest.mkdir(parents=True)
        for name in ("appdata", "cache", "backups"):
            (work / name).mkdir(parents=True)
        subprocess.run([sys.executable, "-m", "engine", "--source", str(self.out / "library"),
                        "--dest", str(dest), "--base", str(work / "appdata"), "--cache", str(work / "cache"),
                        "--backups", str(work / "backups")], capture_output=True, text=True, timeout=600, cwd=REPO)
        db = sqlite3.connect(work / "appdata" / "db" / "ns_sqlite.db")
        status = dict(db.execute("SELECT status, COUNT(*) FROM photos GROUP BY status").fetchall())
        files = self.manifest()["files"]
        self.assertGreaterEqual(status.get("Duplicate", 0), sum(f["scenario"] == "exact_duplicate" for f in files))
        paths = {Path(p).name for (p,) in db.execute("SELECT source_path FROM photos")}
        self.assertNotIn("scn-edge-symlink-to-a-photo.jpg", paths, "a symlink was followed")
        self.assertNotIn("scn-edge-with-sidecar.xmp", paths)
        failed = {Path(p).name for (p,) in db.execute(
            "SELECT source_path FROM operations WHERE status = 'Failed' AND source_path IS NOT NULL")}
        if os.geteuid() != 0:
            self.assertIn("scn-edge-unreadable.jpg", failed, "an unreadable file fails with a reason")
        # A photo's name with no image inside: logged as Failed, "Not an image", and left alone.
        reasons = dict(db.execute("SELECT source_path, error_message FROM operations WHERE status = 'Failed'"))
        for name in ("scn-edge-zero-bytes.jpg", "scn-edge-not-a-photo.jpg"):
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
        # What the engine does today with the harder cases (gaps are reported, not asserted).
        statuses = {Path(p).relative_to(self.out / "library").as_posix(): s
                    for p, s in db.execute("SELECT source_path, status FROM photos")}
        by = lambda scenario: [f["path"] for f in files if f["scenario"] == scenario]   # noqa: E731
        for path in by("nas_qnap_thumbnail") + by("live_photo_video"):
            self.assertNotIn(path, statuses, f"{path} should not be catalogued")
        for scenario in ("format_16_bit_png", "format_cmyk_jpeg", "format_multi_page_tiff", "format_animated_gif",
                         "format_progressive_jpeg", "unicode_nfc", "unicode_nfd", "case_at_destination", "motion_photo"):
            for path in by(scenario):
                self.assertEqual(statuses.get(path), "Pending", f"{scenario}: {path}")
        boundary = {Path(p).name: json.loads(m)["date_taken"] for p, m in db.execute(
            "SELECT source_path, metadata_json FROM photos WHERE source_path LIKE '%/day-boundary/%'")}
        self.assertTrue(boundary["scn-before-midnight-new-york.jpg"].startswith("2019-12-31"), "filed by its local date")
        if os.geteuid() != 0:
            self.assertFalse(by("edge_locked_folder")[0] in statuses, "a locked folder's photo cannot be read")
            scan_failed = db.execute("SELECT COUNT(*) FROM operations WHERE status = 'Failed' "
                                     "AND source_path LIKE '%locked-folder%'").fetchone()[0]
            self.assertGreaterEqual(scan_failed, 1, "a folder the Index cannot open is recorded, not skipped")

    def test_photos_a_move_took_or_the_user_rejected_come_back(self):
        run("build", "--seed-dir", str(self.seed), "--out", str(self.out))
        dest = self.root / "dest"
        (dest / "library" / "2019" / "06" / "15").mkdir(parents=True)
        (dest / "rejects").mkdir()
        # One copy whose original is gone from the source (a Move took it), one in Rejects.
        Image.new("RGB", (64, 48), (1, 2, 3)).save(dest / "library" / "2019" / "06" / "15" / "moved.jpg")
        Image.new("RGB", (64, 48), (9, 8, 7)).save(dest / "rejects" / "turned-down.jpg")
        before = fingerprint(dest)
        done = run("change", "--out", str(self.out), "--dest", str(dest))
        kinds = {c["kind"]: c for c in self.manifest()["changes"]}
        for kind, original in (("returned_after_move", "library/2019/06/15/moved.jpg"),
                               ("returned_after_reject", "rejects/turned-down.jpg")):
            self.assertIn(kind, kinds, done.stdout)
            back = self.out / "library" / kinds[kind]["path"]
            self.assertEqual(back.read_bytes(), (dest / original).read_bytes(), kind)
        after = fingerprint(dest)
        for name in ("library/2019/06/15/moved.jpg", "rejects/turned-down.jpg"):
            self.assertEqual(after[name], before[name], f"{name} at the destination must be left as it was")

class ScenarioIdentityTests(unittest.TestCase):
    """File identity includes its filesystem and must stay live until comparison."""
    def setUp(self):
        from tools import make_scenarios
        self.tool = make_scenarios
        self.root = Path(tempfile.mkdtemp(prefix='ns-identity-'))
        self.seed = self.root / 'seed'
        self.seed.mkdir()
        self.out = self.root / 'output'
        self.out.mkdir()
        self.source = self.seed / 'generated.jpg'
        self.source.write_bytes(b'generated seed')

    def tearDown(self):
        if hasattr(self.tool, 'release_altered'):
            self.tool.release_altered()
        else:
            self.tool.ALTERED.clear()
        if not os.environ.get('NS_TEST_KEEP'):
            shutil.rmtree(self.root)

    def test_different_devices_with_same_inode_are_not_shared_files(self):
        from unittest.mock import patch
        dest = self.out / 'copy.jpg'
        self.tool.fresh_copy(self.source, dest)
        st = dest.stat()
        # Simulate a different filesystem assigning the same inode number.
        before = {'other.jpg': (st.st_size, st.st_mtime_ns, st.st_ino, st.st_dev + 1)}
        with patch.object(self.tool, 'snapshot', return_value=before):
            self.tool.check_untouched(self.seed, before)

    def test_replaced_output_identity_cannot_be_recycled_before_the_check(self):
        dest = self.out / 'copy.jpg'
        self.tool.fresh_copy(self.source, dest)
        old = dest.stat()
        self.tool.replace_with(dest, lambda p: p.write_bytes(b'new generated output'))
        self.assertTrue(any((p.stat().st_dev, p.stat().st_ino) == (old.st_dev, old.st_ino)
                            for p in self.out.rglob('*') if p.is_file()),
                        'the old written inode was freed before seed comparison')
        self.tool.check_untouched(self.seed, self.tool.snapshot(self.seed))
        self.assertEqual(self.source.read_bytes(), b'generated seed')

    def test_real_write_through_seed_link_is_still_detected(self):
        before = self.tool.snapshot(self.seed)
        link = self.out / 'alias.jpg'
        os.link(self.source, link)
        link.write_bytes(b'deliberately bad write')
        if hasattr(self.tool, 'record_altered'):
            self.tool.record_altered(link)
        else:
            self.tool.ALTERED.add(link.stat().st_ino)
        with self.assertRaisesRegex(SystemExit, 'share an inode'):
            self.tool.check_untouched(self.seed, before)


if __name__ == "__main__":
    unittest.main()
