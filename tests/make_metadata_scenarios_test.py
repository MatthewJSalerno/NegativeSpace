"""tools/make_metadata_scenarios.py: every photo and sidecar holds exactly what the manifest
says was written, whether drawn or copied from a seed folder that must stay untouched, read back with ExifTool and a plain XML parser rather than the code the
scenarios exist to test, so the library can serve as ground truth.

    docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app -w /app \\
      negativespace python3 -m unittest discover -s tests -p make_metadata_scenarios_test.py -v
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "make_metadata_scenarios.py"
NS = {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "exif": "http://ns.adobe.com/exif/1.0/",
      "xmp": "http://ns.adobe.com/xap/1.0/", "dc": "http://purl.org/dc/elements/1.1/",
      "tiff": "http://ns.adobe.com/tiff/1.0/"}
# Where ExifTool reports each field the script writes, per source (-G1, -n).
TAGS = {
    "exif": {"date": "ExifIFD:DateTimeOriginal", "offset": "ExifIFD:OffsetTimeOriginal",
             "create_date": "ExifIFD:CreateDate", "make": "IFD0:Make", "model": "IFD0:Model",
             "orientation": "IFD0:Orientation", "caption": "IFD0:ImageDescription", "creators": "IFD0:Artist",
             "rights": "IFD0:Copyright", "gps": "GPS:GPSLatitude"},
    "embedded_xmp": {"date": "XMP-exif:DateTimeOriginal", "make": "XMP-tiff:Make", "model": "XMP-tiff:Model",
                     "orientation": "XMP-tiff:Orientation", "rating": "XMP-xmp:Rating", "title": "XMP-dc:Title",
                     "caption": "XMP-dc:Description", "keywords": "XMP-dc:Subject", "creators": "XMP-dc:Creator",
                     "rights": "XMP-dc:Rights", "gps": "XMP-exif:GPSLatitude"},
    "iptc": {"keywords": "IPTC:Keywords", "caption": "IPTC:Caption-Abstract"},
}


def digits(value) -> str:
    """A date compared by its digits: "2019:06:15 12:00:00" and "2019-06-15T12:00:00" agree."""
    return re.sub(r"\D", "", str(value))


def listed(value) -> list:
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def check_sources(test, lib: Path, manifest: dict):
    """Every value the manifest says was written to a photo's EXIF, embedded XMP or IPTC is
    there, read back with ExifTool, and a date written to EXIF alone is in no other source."""
    photos = [(c, p) for c in manifest["cases"] for p in c["photos"] if p.get("sources")]
    test.assertGreaterEqual(len(photos), 20)
    read = subprocess.run(["exiftool", "-j", "-G1", "-n", *[str(lib / p["path"]) for _, p in photos]],
                          capture_output=True, text=True, check=True)
    tags = {Path(entry["SourceFile"]).relative_to(lib).as_posix(): entry for entry in json.loads(read.stdout)}
    checked = 0
    for case, p in photos:
        found = tags[p["path"]]
        for source, values in p["sources"].items():
            for field, value in values.items():
                where = f"{p['path']} {source}.{field}"
                got = found.get(TAGS[source][field])
                test.assertIsNotNone(got, f"{where}: not written")
                if field in ("date", "create_date"):
                    test.assertEqual(digits(got), digits(value), where)
                elif field == "gps":
                    test.assertAlmostEqual(float(got), abs(value[0]), places=3, msg=where)
                elif field == "creators" and source == "exif":
                    test.assertEqual(str(got), "; ".join(value), where)
                elif field in ("keywords", "creators"):
                    test.assertEqual(listed(got), value, where)
                else:
                    test.assertEqual(str(got), str(value), where)
                checked += 1
        if set(p["sources"]) == {"exif"} and "date" in p["sources"]["exif"]:
            test.assertNotIn("XMP-exif:DateTimeOriginal", found, p["path"])
    test.assertEqual(checked, sum(len(v) for _, p in photos for v in p["sources"].values()))


class MakeMetadataScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="ns-metadata-scenarios-"))
        cls.out = cls.root / "metadata"
        done = subprocess.run([sys.executable, str(SCRIPT), "build", "--out", str(cls.out)],
                              capture_output=True, text=True)
        if done.returncode:
            raise AssertionError(f"build failed:\n{done.stderr[-3000:]}")
        cls.stdout = done.stdout
        cls.manifest = json.loads((cls.out / "manifest.json").read_text())
        cls.lib = cls.out / "library"

    @classmethod
    def tearDownClass(cls):
        if os.environ.get("NS_TEST_KEEP") == "1":
            return
        for p in cls.root.rglob("*"):
            if p.is_file() and not p.is_symlink():
                p.chmod(0o644)
        subprocess.run(["rm", "-rf", str(cls.root)], check=True)

    def cases(self, *groups):
        return [c for c in self.manifest["cases"] if not groups or c["group"] in groups]

    def test_every_group_is_built_and_every_file_exists(self):
        groups = {c["group"] for c in self.cases()}
        self.assertEqual(groups, {"agree", "conflict", "sidecar_names", "sidecar_broken", "real_world"})
        for c in self.cases():
            for item in c["photos"] + c["sidecars"] + c["others"]:
                self.assertTrue(os.path.lexists(self.lib / item["path"]), item["path"])
        self.assertRegex(self.stdout, r"made \d+ case\(s\)")

    def test_each_source_in_each_photo_holds_what_was_written(self):
        check_sources(self, self.lib, self.manifest)

    def test_conflicts_differ_and_agreements_agree(self):
        by = {c["case"]: c for c in self.cases()}
        three = by["date_three_way"]
        dates = {three["photos"][0]["sources"]["exif"]["date"][:4],
                 three["photos"][0]["sources"]["embedded_xmp"]["date"][:4],
                 three["sidecars"][0]["values"]["date"][:4]}
        self.assertEqual(len(dates), 3, "three sources, three dates")
        same = by["all_three_agree"]
        self.assertEqual({digits(same["photos"][0]["sources"]["exif"]["date"]),
                          digits(same["photos"][0]["sources"]["embedded_xmp"]["date"]),
                          digits(same["sidecars"][0]["values"]["date"])}.__len__(), 1)

    def test_valid_sidecars_carry_their_recorded_values(self):
        checked = 0
        for c in self.cases("agree", "conflict", "sidecar_names"):
            for s in c["sidecars"]:
                values = s["values"]
                root = ET.fromstring((self.lib / s["path"]).read_bytes())
                desc = root.find(".//rdf:Description", NS)
                self.assertIsNotNone(desc, s["path"])
                if "date" in values:
                    self.assertEqual(desc.findtext("exif:DateTimeOriginal", namespaces=NS), values["date"], s["path"])
                if "rating" in values:
                    self.assertEqual(desc.findtext("xmp:Rating", namespaces=NS), values["rating"], s["path"])
                if "keywords" in values:
                    self.assertEqual([li.text for li in desc.findall("dc:subject/rdf:Bag/rdf:li", NS)],
                                     values["keywords"], s["path"])
                if isinstance(values.get("title"), str) and values["title"]:
                    self.assertEqual(desc.findtext("dc:title/rdf:Alt/rdf:li", namespaces=NS), values["title"], s["path"])
                checked += 1
        self.assertGreater(checked, 20)

    def test_the_engine_today_is_recorded_for_every_xmp_sidecar(self):
        for c in self.cases():
            for s in c["sidecars"]:
                if s["path"].lower().endswith(".xmp"):
                    rel = str(Path(s["path"]).relative_to(c["folder"]))
                    self.assertIn(rel, c["engine_today"], s["path"])
                    self.assertTrue(c["engine_today"][rel]["state"], s["path"])
        broken = [e for c in self.cases("sidecar_broken") for e in c["engine_today"].values()]
        self.assertTrue(any(e["state"] != "valid" for e in broken))

    def test_a_seed_folder_lends_copies_with_their_metadata_replaced(self):
        # Seed JPEGs of distinct sizes, each with an EXIF date, title and keywords of its own,
        # and one turned (orientation 6) that must be passed over while others remain.
        seed = self.root / "seed"
        for i in range(90):
            path = seed / f"album-{i % 3}" / f"seed-{i:02d}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            exif = Image.Exif()
            exif.get_ifd(0x8769)[36867] = "2001:02:03 04:05:06"
            if i == 0:
                exif[0x0112] = 6
            Image.new("RGB", (300 + i, 200), (i * 2, 120, 200 - i)).save(path, "JPEG", exif=exif)
        subprocess.run(["exiftool", "-q", "-q", "-overwrite_original", "-XMP-dc:Title=Seed title",
                        "-XMP-dc:Subject=seed-keyword", "-IPTC:Keywords=seed-iptc", "-r", str(seed)], check=True)
        before = {str(p.relative_to(seed)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino)
                  for p in seed.rglob("*") if p.is_file()}
        out = self.root / "seeded"
        done = subprocess.run([sys.executable, str(SCRIPT), "build", "--out", str(out), "--seed-dir", str(seed)],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        self.assertIn("untouched by this run", done.stdout)
        after = {str(p.relative_to(seed)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino)
                 for p in seed.rglob("*") if p.is_file()}
        self.assertEqual(after, before, "the seed folder changed")

        manifest = json.loads((out / "manifest.json").read_text())
        lib = out / "library"
        photos = [p for c in manifest["cases"] for p in c["photos"]]
        self.assertTrue(photos and all("from" in p for p in photos), "every photo is a seed copy")
        self.assertEqual(len({p["from"] for p in photos}), len(photos), "each seed photo is used once")
        self.assertNotIn("album-0/seed-00.jpg", {p["from"] for p in photos}, "a turned photo is passed over")
        sizes = {(300 + i, 200) for i in range(90)}
        for p in photos:
            with Image.open(lib / p["path"]) as im:
                # Pixels kept: the seed's size (the case that turns them swaps it).
                self.assertIn(im.size if not p.get("pixels_rotated") else im.size[::-1], sizes, p["path"])
        # The seed's own metadata is gone wherever the case wrote nothing of that kind.
        bare = [p for p in photos if not p.get("sources")]
        read = subprocess.run(["exiftool", "-j", "-G1", *[str(lib / p["path"]) for p in bare]],
                              capture_output=True, text=True, check=True)
        for entry in json.loads(read.stdout):
            for tag in ("ExifIFD:DateTimeOriginal", "XMP-dc:Title", "XMP-dc:Subject", "IPTC:Keywords"):
                self.assertNotIn(tag, entry, f"{entry['SourceFile']} kept the seed's {tag}")
        check_sources(self, lib, manifest)

    def test_a_motion_photo_carries_its_video_last_as_recorded(self):
        tag = {"google_legacy": "File:EmbeddedVideo", "pixel": "Google:MotionPhotoVideo",
               "samsung": "Samsung:EmbeddedVideoFile"}
        motions = [p for c in self.cases("real_world") for p in c["photos"] if "embedded_video" in p]
        self.assertEqual({p["embedded_video"]["variant"] for p in motions}, set(tag))
        for p in motions:
            v = p["embedded_video"]
            video = subprocess.run(["exiftool", "-b", "-ee", f"-{tag[v['variant']]}", str(self.lib / p["path"])],
                                   capture_output=True, check=True).stdout
            self.assertEqual((len(video), hashlib.sha1(video).hexdigest()), (v["length"], v["sha1"]), p["path"])

    def test_it_refuses_a_folder_it_did_not_make(self):
        foreign = self.root / "foreign"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("not ours\n")
        done = subprocess.run([sys.executable, str(SCRIPT), "build", "--out", str(foreign)],
                              capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual((foreign / "keep.txt").read_text(), "not ours\n")


if __name__ == "__main__":
    unittest.main()
