#!/usr/bin/env python3
"""Builds a library of metadata scenarios: EXIF, XMP embedded in the photo, and XMP
sidecars beside it, agreeing, disagreeing and broken, for testing how metadata is read,
how conflicts between the sources are shown, and how sidecars find their photos.

    build   Makes OUT/library/<group>/<case>/..., one folder per case, and
            OUT/manifest.json. Run again with --replace to rebuild.

The groups:

    agree          one source, or several saying the same thing
    conflict       the sources disagree, field by field
    sidecar_names  photo.jpg.xmp, photo.xmp, both, case, shared names, declared owners, orphans
    sidecar_broken malformed, empty, binary, unrelated XML, invalid values, repeated
                   fields, over the size limit, unreadable, a symlink
    real_world     forms that real tools write and the engine may not read yet: an
                   rdf:about UUID, keywords as rdf:Seq, a date only in photoshop:DateCreated,
                   Lightroom's hierarchical keywords, UTF-16 and BOM sidecars, IPTC-only
                   keywords, a zeroed EXIF date, PNG with embedded XMP, a Google Takeout
                   .json sidecar, an orientation already applied to the pixels, and motion
                   photos (Google legacy, Pixel, Samsung) whose video a save must keep

The manifest is ground truth: for every photo, what this script wrote to each source
(`exif`, `embedded_xmp`, `iptc`), and for every sidecar, its name, the photo it was
written for and the values in it. It also records what the engine on this branch makes
of each sidecar today (`engine_today`: its read state and code, the fields it took and,
for an associated sidecar, whose it became), so a gap reads as a gap, not a pass. That
record is an observation of the current code, never an expectation of it.

With --seed-dir, each case's photo is a copy of one of the JPEGs in that folder, each
used once: its pixels are kept, its own EXIF, XMP and IPTC are wiped (its colour profile
stays) and the case's values are written in their place, so the manifest stays the whole
truth. Photos with a rotation tag are passed over while others remain, since wiping the
tag would leave them on their side. The seed folder is never written to, and the run ends
by proving it ("seed: N file(s), untouched"). Without --seed-dir, or once the seed's
JPEGs run out, the photos are drawn, each showing its case name. --seed makes a run
reproducible. Run it in the app image, which has Pillow and ExifTool:

    mkdir -p /photos/demos                  # before the first run: docker would make it root's
    docker run --rm --user "$(id -u):$(id -g)" --entrypoint python3 \\
      -v /photos:/photos -v "$PWD":/app -w /app negativespace \\
      tools/make_metadata_scenarios.py build --out /photos/demos/metadata [--seed-dir /photos/seed]
"""
import argparse
import hashlib
import json
from io import BytesIO
import random
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))
sys.path.insert(0, str(TOOLS))
import make_scenarios  # noqa: E402
from engine import xmp, xmp_association  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

LIBRARY = make_scenarios.LIBRARY
GROUPS = ("agree", "conflict", "sidecar_names", "sidecar_broken", "real_world")
NS = {
    "x": "adobe:ns:meta/", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "exif": "http://ns.adobe.com/exif/1.0/", "tiff": "http://ns.adobe.com/tiff/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/", "xmp": "http://ns.adobe.com/xap/1.0/",
    "crs": "http://ns.adobe.com/camera-raw-settings/1.0/", "photoshop": "http://ns.adobe.com/photoshop/1.0/",
    "lr": "http://ns.adobe.com/lightroom/1.0/",
}


# --- Writing the sources -----------------------------------------------------------

def photo(path: Path, label: str, rng: random.Random, size=(640, 480), fmt="JPEG"):
    """A plain picture showing its case, with no metadata at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, (rng.randrange(40, 200), rng.randrange(40, 200), rng.randrange(40, 200)))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, size[0], 40), fill=(0, 0, 0))
    d.text((12, 12), label, fill=(255, 255, 255))
    d.polygon([(size[0] // 2, 80), (size[0] // 2 - 60, 200), (size[0] // 2 + 60, 200)], fill=(255, 255, 255))
    img.save(path, fmt, **({"quality": 85} if fmt == "JPEG" else {}))
    make_scenarios.record_altered(path)


class Seeds:
    """The seed folder's JPEGs a run takes copies of, shuffled, each used once. Those with
    no rotation tag come first: wiping a tag would turn a photo that needs it sideways."""
    TRIED = 600   # candidates checked for rotation and readability; a run needs under 100

    def __init__(self, root, rng: random.Random):
        self.root, self.pool = root, []
        if root is None:
            return
        jpegs = [p for p in make_scenarios.seed_photos(root) if p.suffix.lower() in (".jpg", ".jpeg")]
        rng.shuffle(jpegs)
        jpegs = jpegs[: self.TRIED]
        turned = set()
        if jpegs:
            listed = subprocess.run(["exiftool", "-q", "-q", "-if", "$Orientation# and $Orientation# != 1",
                                     "-p", "$FilePath", "-@", "-"],
                                    input="\n".join(str(p) for p in jpegs), capture_output=True, text=True)
            turned = {line for line in listed.stdout.splitlines() if line}
        upright = [p for p in jpegs if str(p.resolve()) not in turned]
        # Taken from the end: upright photos first, the turned ones only once those run out.
        self.pool = [p for p in jpegs if str(p.resolve()) in turned][::-1] + upright[::-1]

    def take(self):
        """The next seed photo that opens, or None when there are none left."""
        while self.pool:
            src = self.pool.pop()
            if make_scenarios.opens(src):
                return src
        return None


def from_seed(src: Path, path: Path, fmt: str):
    """A copy of a seed photo at `path` with no EXIF, XMP or IPTC left (its colour profile
    kept): a new file, so the seed's bytes and links are never written through."""
    if fmt == "JPEG":
        make_scenarios.fresh_copy(src, path)
        make_scenarios.exiftool(path, "-all=", "--icc_profile:all")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.convert("RGB").save(path, fmt)
        make_scenarios.record_altered(path)


# What each field is called in EXIF and in embedded XMP, as ExifTool writes them.
EXIF_ARGS = {
    # Written as given (#=), so a camera's zeroed clock goes in as it would come out of one.
    "date": lambda v: [f"-EXIF:DateTimeOriginal#={v}"],
    "offset": lambda v: [f"-EXIF:OffsetTimeOriginal#={v}"],
    "create_date": lambda v: [f"-EXIF:CreateDate#={v}"],
    "make": lambda v: [f"-EXIF:Make={v}"],
    "model": lambda v: [f"-EXIF:Model={v}"],
    "orientation": lambda v: [f"-EXIF:Orientation#={v}"],
    "caption": lambda v: [f"-EXIF:ImageDescription={v}"],
    "creators": lambda v: [f"-EXIF:Artist={'; '.join(v)}"],
    "rights": lambda v: [f"-EXIF:Copyright={v}"],
    "gps": lambda v: [f"-EXIF:GPSLatitude={abs(v[0])}", f"-EXIF:GPSLatitudeRef={'N' if v[0] >= 0 else 'S'}",
                      f"-EXIF:GPSLongitude={abs(v[1])}", f"-EXIF:GPSLongitudeRef={'E' if v[1] >= 0 else 'W'}"],
}
XMP_ARGS = {
    "date": lambda v: [f"-XMP-exif:DateTimeOriginal={v}"],
    "make": lambda v: [f"-XMP-tiff:Make={v}"],
    "model": lambda v: [f"-XMP-tiff:Model={v}"],
    "orientation": lambda v: [f"-XMP-tiff:Orientation#={v}"],
    "rating": lambda v: [f"-XMP-xmp:Rating={v}"],
    "title": lambda v: [f"-XMP-dc:Title={v}"],
    "caption": lambda v: [f"-XMP-dc:Description={v}"],
    "keywords": lambda v: [f"-XMP-dc:Subject={k}" for k in v],
    "creators": lambda v: [f"-XMP-dc:Creator={c}" for c in v],
    "rights": lambda v: [f"-XMP-dc:Rights={v}"],
    "gps": lambda v: [f"-XMP-exif:GPSLatitude={v[0]}", f"-XMP-exif:GPSLongitude={v[1]}"],
}
IPTC_ARGS = {
    "keywords": lambda v: [f"-IPTC:Keywords={k}" for k in v],
    "caption": lambda v: [f"-IPTC:Caption-Abstract={v}"],
}


def embed(path: Path, exif=None, embedded_xmp=None, iptc=None):
    """Writes the given values into the photo, group by group, with nothing implied:
    ExifTool is told each group, so no value is mirrored into another. One call per
    group: given the same tag for two groups in one call, ExifTool keeps only one."""
    for values, table in ((exif, EXIF_ARGS), (embedded_xmp, XMP_ARGS), (iptc, IPTC_ARGS)):
        args = [arg for field, value in (values or {}).items() for arg in table[field](value)]
        if args:
            make_scenarios.exiftool(path, "-m", *args)


def xmp_coordinate(value: float, positive: str, negative: str) -> str:
    """48.8566 -> "48,51.396N": XMP's degrees,decimal-minutes form."""
    degrees = int(abs(value))
    minutes = round((abs(value) - degrees) * 60, 3)
    return f"{degrees},{minutes:g}{positive if value >= 0 else negative}"


def alt(tag: str, value) -> str:
    """A language alternative; a str is x-default, a dict names its languages, and ""
    is an explicitly empty property (the import contract's clearing value)."""
    if value == "":
        return f"<{tag}></{tag}>"
    langs = value if isinstance(value, dict) else {"x-default": value}
    items = "".join(f'<rdf:li xml:lang="{lang}">{text}</rdf:li>' for lang, text in langs.items())
    return f"<{tag}><rdf:Alt>{items}</rdf:Alt></{tag}>"


def packet(fields: dict, *, owner=None, about="", extra="", wrap=True, keywords_as="Bag") -> str:
    """An XMP sidecar in the forms the engine reads: exif:DateTimeOriginal, tiff:Make,
    Model and Orientation, xmp:Rating, dc:title, description, subject, creator and rights,
    exif GPS and crs:RawFileName. `extra` is appended verbatim inside rdf:Description."""
    props = []
    simple = {"date": "exif:DateTimeOriginal", "make": "tiff:Make", "model": "tiff:Model",
              "orientation": "tiff:Orientation", "rating": "xmp:Rating"}
    for field, tag in simple.items():
        if field in fields:
            props.append(f"<{tag}>{fields[field]}</{tag}>")
    for field, tag in (("title", "dc:title"), ("caption", "dc:description"), ("rights", "dc:rights")):
        if field in fields:
            props.append(alt(tag, fields[field]))
    if "keywords" in fields:
        props.append(f"<dc:subject><rdf:{keywords_as}>" + "".join(f"<rdf:li>{k}</rdf:li>" for k in fields["keywords"])
                     + f"</rdf:{keywords_as}></dc:subject>")
    if "creators" in fields:
        props.append("<dc:creator><rdf:Seq>" + "".join(f"<rdf:li>{c}</rdf:li>" for c in fields["creators"])
                     + "</rdf:Seq></dc:creator>")
    if "gps" in fields:
        lat, lon = fields["gps"]
        props.append(f"<exif:GPSLatitude>{xmp_coordinate(lat, 'N', 'S')}</exif:GPSLatitude>"
                     f"<exif:GPSLongitude>{xmp_coordinate(lon, 'E', 'W')}</exif:GPSLongitude>")
    if owner is not None:
        props.append(f"<crs:RawFileName>{owner}</crs:RawFileName>")
    declarations = " ".join(f'xmlns:{p}="{u}"' for p, u in NS.items() if p not in ("x", "rdf"))
    body = (f'<x:xmpmeta xmlns:x="{NS["x"]}">\n <rdf:RDF xmlns:rdf="{NS["rdf"]}">\n'
            f'  <rdf:Description rdf:about="{about}" {declarations}>\n   '
            + "\n   ".join(props + ([extra] if extra else []))
            + "\n  </rdf:Description>\n </rdf:RDF>\n</x:xmpmeta>\n")
    if wrap:
        return '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n' + body + '<?xpacket end="w"?>\n'
    return body


def as_gps(value):
    """The sidecar's GPS as written, in XMP's coordinate form, for the manifest."""
    return [xmp_coordinate(value[0], "N", "S"), xmp_coordinate(value[1], "E", "W")]


# --- The cases ---------------------------------------------------------------------

class Case:
    """One folder of files and what they hold."""
    def __init__(self, builder, group: str, name: str, why: str):
        self.b, self.group, self.name, self.why = builder, group, name, why
        self.folder = builder.lib / group / name
        self.photos, self.sidecars, self.others = [], [], []

    def photo(self, filename="photo.jpg", *, exif=None, embedded_xmp=None, iptc=None, fmt=None, rotate_pixels=False,
              motion=None):
        path = self.folder / filename
        fmt = fmt or ("PNG" if path.suffix.lower() == ".png" else "JPEG")
        src = self.b.seeds.take()
        if src is None:
            photo(path, f"{self.group}/{self.name}", self.b.rng, fmt=fmt)
        else:
            from_seed(src, path, fmt)
        if rotate_pixels:
            # Turned upright in the pixels already, as an editor that applies the tag does.
            with Image.open(path) as im:
                turned = im.rotate(-90, expand=True)
            turned.save(path, fmt)
        embed(path, exif, embedded_xmp, iptc)
        # A motion photo's video goes after everything else: it must stay last in the file.
        video = make_scenarios.motion_photo(path, motion) if motion else None
        sources = {k: v for k, v in (("exif", exif), ("embedded_xmp", embedded_xmp), ("iptc", iptc)) if v}
        self.photos.append({"path": path, "sources": sources, "pixels_rotated": rotate_pixels,
                            **({"embedded_video": {"variant": motion, "length": len(video),
                                                   "sha1": hashlib.sha1(video).hexdigest()}} if video else {}),
                            **({"from": str(src.relative_to(self.b.seeds.root))} if src else {})})
        return path

    def sidecar(self, filename, content, *, written_for=None, values=None):
        """Writes `content` (str as UTF-8, or bytes) to `filename` in the case folder."""
        path = self.folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        make_scenarios.record_altered(path)
        self.sidecars.append({"path": path, "written_for": written_for, "values": values})
        return path

    def xmp(self, filename, fields, *, written_for=None, **kw):
        values = {**fields, **({"gps": as_gps(fields["gps"])} if "gps" in fields else {})}
        if kw.get("owner") is not None:
            values["owner"] = kw["owner"]
        return self.sidecar(filename, packet(fields, **kw), written_for=written_for, values=values)


class Builder:
    def __init__(self, out: Path, rng: random.Random, seeds: Seeds):
        self.out, self.rng, self.seeds = out, rng, seeds
        self.lib = out / LIBRARY
        self.cases = []

    def case(self, group, name, why) -> Case:
        c = Case(self, group, name, why)
        self.cases.append(c)
        return c


# Values the cases share, so a conflict differs in one thing at a time.
CAMERA = {"make": "Canon", "model": "EOS 5D Mark IV"}
TAGS = ["beach", "family", "summer"]


def agree(b: Builder):
    c = b.case("agree", "exif_only", "Every value in EXIF; no XMP anywhere.")
    c.photo(exif={"date": "2019:06:15 12:00:00", **CAMERA, "caption": "At the beach", "creators": ["Ann Lee"],
                  "rights": "(c) Ann Lee", "gps": (43.2965, 5.3698)})
    c = b.case("agree", "embedded_xmp_only", "Values only in XMP inside the JPEG; no EXIF.")
    c.photo(embedded_xmp={"date": "2019-06-15T12:00:00", **CAMERA, "title": "Beach day", "keywords": TAGS,
                          "rating": "4", "creators": ["Ann Lee"], "rights": "(c) Ann Lee",
                          "gps": (43.2965, 5.3698)})
    c = b.case("agree", "sidecar_only", "Values only in photo.jpg.xmp; the JPEG carries none.")
    p = c.photo()
    c.xmp("photo.jpg.xmp", {"date": "2019-06-15T12:00:00", **CAMERA, "title": "Beach day", "keywords": TAGS,
                            "rating": "4", "gps": (43.2965, 5.3698)}, written_for=p.name)
    c = b.case("agree", "all_three_agree", "EXIF, embedded XMP and the sidecar say the same.")
    p = c.photo(exif={"date": "2019:06:15 12:00:00", **CAMERA},
                embedded_xmp={"date": "2019-06-15T12:00:00", **CAMERA, "title": "Beach day", "keywords": TAGS})
    c.xmp("photo.jpg.xmp", {"date": "2019-06-15T12:00:00", **CAMERA, "title": "Beach day", "keywords": TAGS},
          written_for=p.name)
    c = b.case("agree", "complementary", "No field in two places: EXIF has date and camera, the sidecar "
                                         "title, keywords and rating. Nothing conflicts; both are needed.")
    p = c.photo(exif={"date": "2019:06:15 12:00:00", **CAMERA})
    c.xmp("photo.jpg.xmp", {"title": "Beach day", "keywords": TAGS, "rating": "5"}, written_for=p.name)


def conflict(b: Builder):
    def pair(name, why, exif=None, embedded_xmp=None, side=None):
        c = b.case("conflict", name, why)
        p = c.photo(exif=exif, embedded_xmp=embedded_xmp)
        if side is not None:
            c.xmp("photo.jpg.xmp", side, written_for=p.name)
    pair("date_exif_vs_sidecar", "EXIF says 2019-06-15, the sidecar 2021-08-01.",
         exif={"date": "2019:06:15 12:00:00"}, side={"date": "2021-08-01T09:30:00"})
    pair("date_exif_vs_embedded_xmp", "Inside one file: EXIF 2019-06-15, embedded XMP 2020-05-01.",
         exif={"date": "2019:06:15 12:00:00"}, embedded_xmp={"date": "2020-05-01T10:00:00"})
    pair("date_embedded_vs_sidecar", "Embedded XMP 2020-05-01, the sidecar 2021-08-01; no EXIF date.",
         embedded_xmp={"date": "2020-05-01T10:00:00"}, side={"date": "2021-08-01T09:30:00"})
    pair("date_three_way", "Three dates: EXIF 2019, embedded XMP 2020, sidecar 2021.",
         exif={"date": "2019:06:15 12:00:00"}, embedded_xmp={"date": "2020-05-01T10:00:00"},
         side={"date": "2021-08-01T09:30:00"})
    pair("same_instant_different_text", "One moment written two ways: EXIF 12:00 at +02:00, the "
                                        "sidecar 10:00Z. Not a conflict in time; different in text.",
         exif={"date": "2019:06:15 12:00:00", "offset": "+02:00"}, side={"date": "2019-06-15T10:00:00Z"})
    pair("date_precision", "The sidecar knows only the month (2019-06); EXIF has the second.",
         exif={"date": "2019:06:15 12:00:00"}, side={"date": "2019-06"})
    pair("sidecar_clears_title", "The sidecar's dc:title is present and empty (a clearing value); the "
                                 "embedded XMP has a title and EXIF a description.",
         exif={"caption": "At the beach"}, embedded_xmp={"title": "Beach day"}, side={"title": ""})
    pair("keywords_differ", "Embedded keywords beach, family, summer; the sidecar holiday, sea.",
         embedded_xmp={"keywords": TAGS}, side={"keywords": ["holiday", "sea"]})
    pair("rating_differs", "Embedded rating 2, the sidecar 5.", embedded_xmp={"rating": "2"}, side={"rating": "5"})
    pair("orientation_differs", "EXIF orientation 6 (rotate 90 clockwise), the sidecar 1 (upright).",
         exif={"orientation": "6"}, side={"orientation": "1"})
    pair("gps_differs", "EXIF places it in Marseille, the sidecar in Paris.",
         exif={"gps": (43.2965, 5.3698)}, side={"gps": (48.8566, 2.3522)})
    pair("camera_exif_vs_embedded_xmp", "EXIF says Canon EOS 5D Mark IV, embedded XMP Nikon D750.",
         exif=CAMERA, embedded_xmp={"make": "Nikon", "model": "D750"})
    pair("caption_exif_vs_xmp", "EXIF ImageDescription and dc:description disagree.",
         exif={"caption": "Old caption from the camera"}, embedded_xmp={"caption": "Caption written later"})
    pair("title_languages", "Embedded title in x-default only; the sidecar's in x-default and de-DE, "
                            "with a different x-default.",
         embedded_xmp={"title": "Beach day"}, side={"title": {"x-default": "Day at the sea", "de-DE": "Strandtag"}})
    pair("creators_differ", "EXIF Artist is one name; the sidecar lists two creators in order.",
         exif={"creators": ["Ann Lee"]}, side={"creators": ["Ben Ortiz", "Ann Lee"]})


def sidecar_names(b: Builder, raws: list):
    fields = {"title": "From the sidecar", "rating": "3"}
    c = b.case("sidecar_names", "full_name", "photo.jpg.xmp: the photo's whole name.")
    p = c.photo()
    c.xmp("photo.jpg.xmp", fields, written_for=p.name)
    c = b.case("sidecar_names", "stem_name", "photo.xmp: the photo's name without its extension.")
    p = c.photo()
    c.xmp("photo.xmp", fields, written_for=p.name)
    c = b.case("sidecar_names", "both_names_disagree", "photo.xmp and photo.jpg.xmp both, saying different things.")
    p = c.photo()
    c.xmp("photo.xmp", {"title": "Stem version", "rating": "1"}, written_for=p.name)
    c.xmp("photo.jpg.xmp", {"title": "Full-name version", "rating": "5"}, written_for=p.name)
    c = b.case("sidecar_names", "uppercase_extension", "photo.XMP: the extension in capitals.")
    p = c.photo()
    c.xmp("photo.XMP", fields, written_for=p.name)
    c = b.case("sidecar_names", "stem_case_differs", "IMG_0001.JPG with img_0001.xmp: the names differ "
                                                     "only in letter case.")
    p = c.photo("IMG_0001.JPG")
    c.xmp("img_0001.xmp", fields, written_for=p.name)
    c = b.case("sidecar_names", "shared_stem", "pair.jpg and pair.png share pair.xmp: whose is it?")
    c.photo("pair.jpg")
    c.photo("pair.png")
    c.xmp("pair.xmp", fields, written_for=None)
    c = b.case("sidecar_names", "declared_owner", "pair.jpg and pair.png share pair.xmp, which names "
                                                  "pair.jpg in crs:RawFileName.")
    c.photo("pair.jpg")
    c.photo("pair.png")
    c.xmp("pair.xmp", fields, written_for="pair.jpg", owner="pair.jpg")
    c = b.case("sidecar_names", "owner_conflict", "pair.xmp names other.jpg, which is not here.")
    c.photo("pair.jpg")
    c.photo("pair.png")
    c.xmp("pair.xmp", fields, written_for=None, owner="other.jpg")
    c = b.case("sidecar_names", "orphan", "lonely.xmp, with no photo of that name.")
    c.photo("someone-else.jpg")
    c.xmp("lonely.xmp", fields, written_for=None)
    c = b.case("sidecar_names", "sidecar_in_subfolder", "photo.jpg here, its sidecar one folder down "
                                                        "(as some tools keep them).")
    p = c.photo()
    c.xmp("xmp/photo.jpg.xmp", fields, written_for=f"../{p.name}")
    if raws:
        raw = raws[0]
        c = b.case("sidecar_names", "raw_jpeg_pair", "A RAW and a JPEG of one shot with one stem sidecar, "
                                                     "as Lightroom leaves them.")
        dest = c.folder / f"IMG_0100{raw.suffix}"
        make_scenarios.fresh_copy(raw, dest)
        c.photos.append({"path": dest, "sources": {}, "pixels_rotated": False, "from_raw": raw.name})
        c.photo("IMG_0100.jpg")
        c.xmp("IMG_0100.xmp", {"rating": "4", "keywords": ["raw", "pair"]}, written_for=dest.name)


def sidecar_broken(b: Builder):
    def broken(name, why, content, filename="photo.jpg.xmp"):
        c = b.case("sidecar_broken", name, why)
        p = c.photo()
        return c, c.sidecar(filename, content, written_for=p.name)
    good = packet({"title": "Fine", "rating": "3"})
    broken("malformed_xml", "Cut off mid-element.", good[: len(good) // 2])
    broken("empty_file", "Zero bytes.", b"")
    jpeg = BytesIO()
    Image.new("RGB", (8, 8)).save(jpeg, "JPEG")
    broken("binary_named_xmp", "A JPEG's bytes under a .xmp name.", jpeg.getvalue())
    broken("unrelated_xml", "Well-formed XML that is not XMP (an SVG).",
           '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>\n')
    broken("invalid_date", "exif:DateTimeOriginal 2019-13-40.", packet({"date": "2019-13-40T10:00:00"}))
    broken("invalid_rating", "xmp:Rating 7 (the scale is -1 to 5).", packet({"rating": "7"}))
    broken("invalid_orientation", "tiff:Orientation 9 (1 to 8 exist).", packet({"orientation": "9"}))
    broken("repeated_title", "dc:title twice in one description.",
           packet({"title": "One"}, extra=alt("dc:title", "Two")))
    broken("over_size_limit", f"Valid XMP padded past the reader's {xmp.MAX_BYTES:,}-byte limit.",
           good.replace("</x:xmpmeta>", "<!-- " + "x" * (xmp.MAX_BYTES + 1024) + " -->\n</x:xmpmeta>"))
    c, path = broken("unreadable", "Valid, but nobody may read it (mode 000).", good)
    path.chmod(0)
    c = b.case("sidecar_broken", "symlink", "photo.jpg.xmp is a symlink to a valid sidecar elsewhere.")
    p = c.photo()
    target = c.sidecar("elsewhere/real.xmp", good, written_for=None, values={"title": "Fine", "rating": "3"})
    link = c.folder / "photo.jpg.xmp"
    link.symlink_to("elsewhere/real.xmp")
    c.sidecars.append({"path": link, "written_for": p.name, "values": None, "symlink_to": str(target.relative_to(c.folder))})


def real_world(b: Builder):
    def side(name, why, content, values=None, **photo):
        c = b.case("real_world", name, why)
        p = c.photo(**photo)
        c.sidecar("photo.jpg.xmp", content, written_for=p.name, values=values)
        return c
    side("about_uuid", "rdf:about=\"uuid:...\", as older Adobe tools wrote it.",
         packet({"title": "Old Adobe", "rating": "4"}, about="uuid:faf5bdd5-ba3d-11da-ad31-d33d75182f1b"),
         {"title": "Old Adobe", "rating": "4"})
    side("keywords_as_seq", "dc:subject as rdf:Seq instead of rdf:Bag, as some tools write it.",
         packet({"keywords": TAGS}, keywords_as="Seq"), {"keywords": TAGS})
    side("date_only_photoshop_datecreated", "The capture date only in photoshop:DateCreated and "
                                            "xmp:CreateDate, the way Apple Photos and others export it.",
         packet({}, extra="<photoshop:DateCreated>2018-03-04T08:00:00</photoshop:DateCreated>"
                          "<xmp:CreateDate>2018-03-04T08:00:00</xmp:CreateDate>"),
         {"photoshop:DateCreated": "2018-03-04T08:00:00", "xmp:CreateDate": "2018-03-04T08:00:00"})
    side("hierarchical_keywords", "Keywords only in Lightroom's lr:hierarchicalSubject.",
         packet({}, extra="<lr:hierarchicalSubject><rdf:Bag><rdf:li>Places|France|Marseille</rdf:li>"
                          "<rdf:li>People|Ann Lee</rdf:li></rdf:Bag></lr:hierarchicalSubject>"),
         {"lr:hierarchicalSubject": ["Places|France|Marseille", "People|Ann Lee"]})
    side("utf16_sidecar", "A valid sidecar encoded as UTF-16 with a byte-order mark.",
         packet({"title": "Sixteen bits", "rating": "2"}).replace('<?xpacket begin="﻿"', '<?xpacket begin=""')
         .encode("utf-16"), {"title": "Sixteen bits", "rating": "2"})
    side("utf8_bom_sidecar", "A valid sidecar with a UTF-8 byte-order mark before it.",
         b"\xef\xbb\xbf" + packet({"title": "With a BOM", "rating": "2"}, wrap=False).encode(),
         {"title": "With a BOM", "rating": "2"})
    side("title_without_x_default", "dc:title in en-US and fr-FR only, no x-default.",
         packet({"title": {"en-US": "Harbour", "fr-FR": "Port"}}), {"title": {"en-US": "Harbour", "fr-FR": "Port"}})
    side("rating_rejected", "xmp:Rating -1: Lightroom's rejected flag.", packet({"rating": "-1"}), {"rating": "-1"})
    side("unicode_keywords", "Keywords with accents, commas, a semicolon and an emoji.",
         packet({"keywords": ["Café de Flore", "Smith, Jane", "a;b", "🌊"]}),
         {"keywords": ["Café de Flore", "Smith, Jane", "a;b", "🌊"]})
    c = b.case("real_world", "iptc_only_keywords", "Keywords and caption only in legacy IPTC-IIM.")
    c.photo(iptc={"keywords": TAGS, "caption": "From IPTC"})
    c = b.case("real_world", "exif_date_zeroed", "EXIF DateTimeOriginal 0000:00:00 00:00:00, a camera's "
                                                 "unset clock; the sidecar has a real date.")
    p = c.photo(exif={"date": "0000:00:00 00:00:00"})
    c.xmp("photo.jpg.xmp", {"date": "2017-07-01T15:00:00"}, written_for=p.name)
    c = b.case("real_world", "exif_create_date_only", "No DateTimeOriginal; EXIF CreateDate only.")
    c.photo(exif={"create_date": "2016:12:24 18:00:00"})
    c = b.case("real_world", "png_embedded_xmp", "A PNG with XMP inside it (iTXt) and a sidecar that "
                                                 "disagrees.")
    p = c.photo("photo.png", embedded_xmp={"title": "Inside the PNG", "date": "2015-01-01T00:00:00"})
    c.xmp("photo.png.xmp", {"title": "In the sidecar", "date": "2016-01-01T00:00:00"}, written_for=p.name)
    c = b.case("real_world", "google_takeout_json", "A Google Takeout photo.jpg.json beside the photo, "
                                                    "its photoTakenTime a year off EXIF.")
    p = c.photo(exif={"date": "2019:06:15 12:00:00"})
    takeout = {"title": "photo.jpg", "description": "From Takeout",
               "photoTakenTime": {"timestamp": "1592222400", "formatted": "15 Jun 2020, 12:00:00 UTC"},
               "geoData": {"latitude": 48.8566, "longitude": 2.3522, "altitude": 0.0}}
    path = c.folder / "photo.jpg.json"
    path.write_text(json.dumps(takeout, indent=2) + "\n")
    make_scenarios.record_altered(path)
    c.others.append({"path": path, "kind": "google_takeout_json", "written_for": p.name, "values": takeout})
    # Motion photos: a JPEG with a video after the picture. A metadata write must keep the
    # video byte for byte (the manifest has its length and SHA-1): ExifTool's writes do, while
    # re-encoding the picture through an image library drops it.
    for variant, name in make_scenarios.MOTION_PHOTOS:
        c = b.case("real_world", f"motion_photo_{variant}", f"A {variant.replace('_', ' ')} motion photo with "
                   "metadata in it and a sidecar that disagrees: a save must keep its video.")
        p = c.photo(name, exif={"date": "2019:06:15 12:00:00"},
                    embedded_xmp={"title": "Moving picture", "keywords": ["motion"]}, motion=variant)
        c.xmp(f"{name}.xmp", {"title": "Sidecar title", "rating": "4"}, written_for=p.name)
    c = b.case("real_world", "orientation_already_applied", "The pixels are already turned upright, yet "
                                                            "EXIF still says orientation 6: shown as told, it "
                                                            "lies on its side.")
    c.photo(exif={"orientation": "6"}, rotate_pixels=True)


# --- What the engine makes of each sidecar today ----------------------------------

def engine_today(case: Case) -> dict:
    """The engine's own reader and association planner on this branch, run over the case
    folder as Index would see it. An observation, recorded in the manifest."""
    photos = sorted(str(p.relative_to(case.folder)) for p in case.folder.rglob("*")
                    if p.is_file() and not p.is_symlink() and p.suffix.lower() in make_scenarios.SUPPORTED_EXTENSIONS)
    inventory = xmp_association.PhotoInventory(photos)
    seen = {}
    for s in case.sidecars:
        rel = str(s["path"].relative_to(case.folder))
        if Path(rel).suffix.lower() != ".xmp":
            continue
        try:
            result = xmp.read_sidecar(case.folder, rel, source_id=rel)
        except (OSError, ValueError) as exc:          # the reader's own refusals (a symlink, a path)
            seen[rel] = {"state": "refused", "code": type(exc).__name__, "detail": str(exc)[:200]}
            continue
        entry = {"state": result.state, "code": result.code}
        if result.source is not None:
            entry["fields"] = sorted(result.source.fields)
        a = inventory.associate(rel, result, policy="ask")
        entry["association"] = {"state": a.state, "reason": a.reason, "photos": list(a.photos),
                                **({"basis": a.basis} if a.basis else {})}
        seen[rel] = entry
    return seen


# --- Build --------------------------------------------------------------------------

def build(args):
    rng = random.Random(args.seed)
    out = Path(args.out).resolve()
    seed = Path(args.seed_dir).resolve() if args.seed_dir else None
    if seed and not seed.is_dir():
        sys.exit(f"FATAL: --seed-dir is not a folder: {seed}")
    if seed and (out.is_relative_to(seed) or seed.is_relative_to(out)):
        sys.exit("FATAL: the output and the seed folder must not contain one another.")
    make_scenarios.prepare_out(out, args.replace)
    before = make_scenarios.snapshot(seed) if seed else None
    b = Builder(out, rng, Seeds(seed, rng))
    raws = sorted(Path(args.raw_dir).rglob("*")) if args.raw_dir else []
    raws = [p for p in raws if p.is_file() and p.suffix.lower() in make_scenarios.RAW_EXTENSIONS]
    agree(b)
    conflict(b)
    sidecar_names(b, raws)
    sidecar_broken(b)
    real_world(b)

    cases = []
    for c in b.cases:
        rel = lambda p: str(p.relative_to(out / LIBRARY))      # noqa: E731
        cases.append({
            "group": c.group, "case": c.name, "folder": rel(c.folder), "why": c.why,
            "photos": [{"path": rel(p["path"]), **{k: v for k, v in p.items() if k != "path" and v}} for p in c.photos],
            "sidecars": [{"path": rel(s["path"]), **{k: v for k, v in s.items() if k != "path" and v is not None}}
                         for s in c.sidecars],
            "others": [{"path": rel(o["path"]), **{k: v for k, v in o.items() if k != "path"}} for o in c.others],
            "engine_today": engine_today(c),
        })
    (out / "manifest.json").write_text(json.dumps(
        {"tool": "tools/make_metadata_scenarios.py", "seed": args.seed, "seed_dir": str(seed) if seed else None,
         "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cases": cases},
        indent=2, ensure_ascii=False) + "\n")
    counts = {g: sum(1 for c in cases if c["group"] == g) for g in GROUPS}
    sidecars = [e for c in cases for e in c["engine_today"].values()]
    read = sum(1 for e in sidecars if e["state"] == "valid")
    print(f"library: {out / LIBRARY}")
    print(f"made {len(cases)} case(s): " + ", ".join(f"{g} {n}" for g, n in counts.items()))
    print(f"engine today: {read} of {len(sidecars)} sidecar(s) read; the rest held, ignored or refused "
          "(manifest.json, engine_today)")
    if seed:
        copied = sum(1 for c in cases for p in c["photos"] if "from" in p)
        drawn = sum(len(c["photos"]) for c in cases) - copied - sum(1 for c in cases for p in c["photos"] if "from_raw" in p)
        print(f"photos: {copied} copied from the seed folder" + (f", {drawn} drawn (its JPEGs ran out)" if drawn else ""))
        make_scenarios.check_untouched(seed, before)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="make OUT/library with every metadata scenario, and OUT/manifest.json")
    b.add_argument("--out", required=True, help="an empty folder, or one this script made earlier")
    b.add_argument("--replace", action="store_true", help="rebuild over this script's earlier output")
    b.add_argument("--seed", type=int, default=1, help="random seed: the same seed makes the same pictures")
    b.add_argument("--seed-dir", help="folder of real photos: each case takes a copy of one JPEG, its metadata "
                                      "replaced; never written to (default: draw the photos)")
    b.add_argument("--raw-dir", help="folder of real RAW files: one is copied (never linked) for the RAW+JPEG case")
    args = parser.parse_args()
    try:
        build(args)
    finally:
        make_scenarios.release_altered()


if __name__ == "__main__":
    main()
