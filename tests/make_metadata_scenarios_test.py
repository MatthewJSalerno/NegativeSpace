"""tools/make_metadata_scenarios.py: every photo and sidecar holds exactly what the manifest
says was written, read back with ExifTool and a plain XML parser rather than the code the
scenarios exist to test, so the library can serve as ground truth.

    docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app -w /app \\
      negativespace python3 -m unittest discover -s tests -p make_metadata_scenarios_test.py -v
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

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
        photos = [(c, p) for c in self.cases() for p in c["photos"] if p.get("sources")]
        self.assertGreaterEqual(len(photos), 20)
        read = subprocess.run(["exiftool", "-j", "-G1", "-n", *[str(self.lib / p["path"]) for _, p in photos]],
                              capture_output=True, text=True, check=True)
        tags = {Path(entry["SourceFile"]).relative_to(self.lib).as_posix(): entry for entry in json.loads(read.stdout)}
        checked = 0
        for case, p in photos:
            found = tags[p["path"]]
            for source, values in p["sources"].items():
                for field, value in values.items():
                    where = f"{p['path']} {source}.{field}"
                    got = found.get(TAGS[source][field])
                    self.assertIsNotNone(got, f"{where}: not written")
                    if field in ("date", "create_date"):
                        self.assertEqual(digits(got), digits(value), where)
                    elif field == "gps":
                        self.assertAlmostEqual(float(got), abs(value[0]), places=3, msg=where)
                    elif field == "creators" and source == "exif":
                        self.assertEqual(str(got), "; ".join(value), where)
                    elif field in ("keywords", "creators"):
                        self.assertEqual(listed(got), value, where)
                    else:
                        self.assertEqual(str(got), str(value), where)
                    checked += 1
            # Nothing leaks between sources: a date written to one source only is in no other.
            if set(p["sources"]) == {"exif"} and "date" in p["sources"]["exif"]:
                self.assertNotIn("XMP-exif:DateTimeOriginal", found, p["path"])
        self.assertEqual(checked, sum(len(v) for _, p in photos for v in p["sources"].values()))

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
