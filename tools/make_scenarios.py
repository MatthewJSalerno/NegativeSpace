#!/usr/bin/env python3
"""Builds a sample library of deliberate scenarios, for showing and testing what the
engine and the web interface do: duplicates and near-duplicates, look-alikes, dates the
engine must file (in the name only, across midnight, a camera's clock a year off, a burst
in one second), names that collide or look alike, a NAS share's own folders, Live and
motion photos, formats and sizes that strain a reader, files and folders that must fail,
and a round of changes between runs that gives a photo's lineage something to show.

    build   Hard-links every photo in a seed folder into OUT/library, then adds the
            scenarios beside them. Run again as the seed folder grows: it replaces its
            own earlier output, and refuses any other non-empty folder.
    change  One round of every kind of change, applied to a built library (and, with
            --dest, to the destination a Copy filled, and from it: a photo a Move took and
            one the user rejected come back to the source): run it after an Index and a
            Copy, then Index and Copy again.

The seed folder is never written to. Hard links share the original's bytes AND its
inode, so a file edited in place would change the seed too: every file this script
alters is written as a new file and renamed over the old path, which breaks the link
first. Both commands finish by proving it: "seed: N file(s), untouched".

--exif-donors names a folder of camera files kept for their metadata, such as ExifTool's
sample images (https://exiftool.org/sample_images.html, whose pictures are shrunk to a few
pixels). About three in four seed JPEGs with no EXIF date get one donor's tags - camera,
lens, exposure, dates, GPS, maker notes - on a fresh copy; the rest stay without, for
No capture date. A donor folder inside the seed folder is left out of the originals, and
a few donors join the library as themselves: tiny images to sort out by resolution.

Without --seed-dir the photos are generated, so it runs anywhere with nothing to
download. OUT/manifest.json lists every file made, its scenario, and what the app
should show for it. --seed makes a run reproducible.

Run in the app image, which has Pillow, pillow-heif and ExifTool. Hard links need the
seed and OUT on one filesystem AND one mount, so mount their common parent once:

    mkdir -p /photos/demos                  # before the first run: docker would make it root's
    docker run --rm --user "$(id -u):$(id -g)" --entrypoint python3 \\
      -v /photos:/photos -v "$PWD":/app -w /app negativespace \\
      tools/make_scenarios.py build --seed-dir /photos/seed --out /photos/demos/demo \\
        [--exif-donors /photos/seed/exiftool-samples]
"""
import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
import tempfile
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine.ns_db import RASTER_EXTENSIONS, RAW_EXTENSIONS, SUPPORTED_EXTENSIONS  # noqa: E402

from PIL import Image, ImageDraw, ImageEnhance, ImageFile, ImageOps  # noqa: E402

# A seed folder may be filling while this runs: a photo caught half-downloaded is used
# as far as it goes rather than stopping the build.
ImageFile.LOAD_TRUNCATED_IMAGES = True

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF = True
except ImportError:                                    # pragma: no cover - the image has it
    HEIF = False

MARKER = ".ns-scenarios"          # in OUT: this folder is ours to replace
LIBRARY = "library"               # OUT/library is the source to index
EDITABLE = {".jpg", ".jpeg"}      # EXIF is rewritten on JPEG copies only
GENERATED = 60                    # photos made when there is no seed folder
# Stand-in videos: a container's opening box, enough for a file to identify as one.
QUICKTIME = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  "
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 1024


# --- Safety -----------------------------------------------------------------------

def snapshot(root: Path) -> dict:
    """Every seed file's size, mtime and inode: what a write through a link would change."""
    out = {}
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns, st.st_ino, st.st_dev)
    return out


# Keep written identities alive until the seed comparison. A replaced temporary
# file's inode can otherwise be reused immediately by an unrelated download.
# Hard links use no duplicate data blocks and avoid one open descriptor per file.
# Old versions occupy space only until the check finishes. Names have no photo
# extension, so an interrupted build cannot turn guard links into sample photos.
ALTERED = set()                   # (device, inode), never a bare inode number
_ALTERED_GUARDS = {}


def record_altered(path: Path):
    st = path.stat()
    identity = (st.st_dev, st.st_ino)
    if identity not in ALTERED:
        parent = path.parent
        if parent not in _ALTERED_GUARDS:
            _ALTERED_GUARDS[parent] = tempfile.TemporaryDirectory(prefix='.ns-write-guard-', dir=parent)
        hold = Path(_ALTERED_GUARDS[parent].name) / f'{st.st_dev}-{st.st_ino}'
        os.link(path, hold)
        ALTERED.add(identity)


def release_altered():
    for directory in _ALTERED_GUARDS.values():
        directory.cleanup()
    _ALTERED_GUARDS.clear()
    ALTERED.clear()


def check_untouched(root: Path, before: dict):
    """The promise, proved: nothing this run wrote shares an inode with a seed file, so
    no write reached the seed through a link. The seed folder may also be changing under
    another program (a download filling it): that is reported, never mistaken for ours."""
    after = snapshot(root)
    seed_inodes = {(v[3], v[2]) for v in after.values()} | {(v[3], v[2]) for v in before.values()}
    through = ALTERED & seed_inodes
    if through:
        sys.exit(f"FATAL: {len(through)} file(s) this run wrote share an inode with the seed folder")
    changed = sorted(k for k in before if k in after and after[k] != before[k])
    appeared, vanished = set(after) - set(before), set(before) - set(after)
    print(f"seed: {len(before)} file(s), untouched by this run")
    if changed or appeared or vanished:
        print(f"seed: meanwhile {len(appeared)} appeared, {len(vanished)} vanished and {len(changed)} changed "
              "through another program (a download?); rerun build --replace to take them in")


def fresh_copy(src: Path, dest: Path):
    """A new file with src's bytes and times: never a link, so it can be altered."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dest)
    record_altered(dest)


def replace_with(path: Path, write):
    """Writes a new file with `write(tmp)` and renames it over `path`: a hard-linked
    `path` loses its link instead of changing the file it shared bytes with."""
    tmp = path.with_name(f".{path.name}.tmp")
    write(tmp)
    os.replace(tmp, path)
    record_altered(path)


def exiftool(path: Path, *args):
    """ExifTool on a file this script made. -overwrite_original writes a new file and
    renames it into place, so it could not write through a link either."""
    subprocess.run(["exiftool", "-q", "-q", "-overwrite_original", *args, str(path)], check=True)
    record_altered(path)


# --- Seeds ------------------------------------------------------------------------

def generate_seeds(folder: Path, rng: random.Random) -> list:
    """Plain photos with EXIF dates, for a run with no seed folder."""
    folder.mkdir(parents=True, exist_ok=True)
    made = []
    for i in range(GENERATED):
        year, month = 2015 + i % 9, 1 + i % 12
        img = Image.new("RGB", (800, 600), (rng.randrange(256), rng.randrange(256), rng.randrange(256)))
        d = ImageDraw.Draw(img)
        for _ in range(12):
            x, y = rng.randrange(800), rng.randrange(600)
            d.ellipse((x, y, x + rng.randrange(40, 200), y + rng.randrange(40, 200)),
                      fill=(rng.randrange(256), rng.randrange(256), rng.randrange(256)))
        d.text((20, 20), f"generated {i:03d}", fill=(255, 255, 255))
        exif = Image.Exif()
        exif.get_ifd(0x8769)[36867] = f"{year}:{month:02d}:{1 + i % 28:02d} 10:{i % 60:02d}:00"
        exif[0x010F], exif[0x0110] = "NegativeSpace", "Generator"
        path = folder / f"{year}" / f"generated-{i:03d}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, "JPEG", quality=88, exif=exif)
        made.append(path)
    return made


def seed_photos(seed: Path, skip: Path = None) -> list:
    return sorted(p for p in seed.rglob("*")
                  if p.is_file() and not p.is_symlink() and p.suffix.lower() in SUPPORTED_EXTENSIONS
                  and not (skip and p.is_relative_to(skip)))


# Tags a donor's picture owns, not its camera: its size and embedded previews would
# contradict the pixels they land on, and its rotation would turn them sideways
# (orientation has its own scenario).
DONOR_SKIP = ("Orientation", "ExifImageWidth", "ExifImageHeight", "ImageWidth", "ImageHeight",
              "ThumbnailImage", "PreviewImage", "JpgFromRaw", "IFD1:all")
DONOR_SHARE = 0.75


def undated(paths: list) -> list:
    """Those of `paths` with no EXIF DateTimeOriginal, in one ExifTool pass."""
    if not paths:
        return []
    listed = subprocess.run(["exiftool", "-q", "-q", "-if", "$DateTimeOriginal", "-p", "$FilePath", "-@", "-"],
                            input="\n".join(str(p) for p in paths), capture_output=True, text=True)
    dated = {line for line in listed.stdout.splitlines() if line}
    return [p for p in paths if str(p.resolve()) not in dated]


def graft_exif(originals: list, donors: list, rng: random.Random, m) -> int:
    """Gives about DONOR_SHARE of the undated seed JPEGs one donor's tags each, on a fresh
    copy (the seed is untouched), in a single ExifTool process. Returns how many."""
    targets = [p for p in undated([p for p in originals if p.suffix.lower() in EDITABLE])]
    rng.shuffle(targets)
    targets = sorted(targets[:round(len(targets) * DONOR_SHARE)])
    if not targets or not donors:
        return 0
    order = rng.sample(donors, len(donors))
    args, paired, copied = [], {}, {}
    for i, path in enumerate(targets):
        donor = order[i % len(order)]
        fresh_copy(path, path)                    # breaks the hard link before any write
        copied[path] = path.stat().st_ino
        args += ["-tagsFromFile", str(donor), "-all:all", *[f"--{t}" for t in DONOR_SKIP],
                 "-overwrite_original", str(path), "-execute"]
        paired[str(path.relative_to(m.out / LIBRARY))] = donor.name
    # -common_args applies the quiet flags to every -execute'd command, not only the first:
    # many donors carry damaged maker notes, which is the point, and each would warn.
    subprocess.run(["exiftool", "-@", "-", "-common_args", "-q", "-q", "-m"], input="\n".join(args), text=True, check=True)
    # ExifTool writes a new file for each it changes; one whose donor's tags were too
    # damaged to write keeps the copy's inode, and is recorded as not given any.
    written = set()
    for path in targets:
        record_altered(path)
        if path.stat().st_ino != copied[path]:
            written.add(str(path.relative_to(m.out / LIBRARY)))
    for entry in m.files:
        if entry["path"] in paired:
            entry["hard_link"] = False
            if entry["path"] in written:
                entry.update(exif_from=paired[entry["path"]],
                             expect="indexed; its camera, dates and exposure come from a sample camera file")
    return len(written)


def opens(path: Path) -> bool:
    try:
        with Image.open(path) as im:
            im.size
        return path.suffix.lower() in RASTER_EXTENSIONS
    except Exception:
        return False


# --- Build ------------------------------------------------------------------------

class Manifest:
    def __init__(self, out: Path):
        self.out, self.files, self.changes = out, [], []

    def add(self, path: Path, scenario: str, expect: str, source: Path = None, **extra):
        entry = {"path": str(path.relative_to(self.out / LIBRARY)), "scenario": scenario, "expect": expect}
        if source is not None:
            entry["from"] = str(source.relative_to(self.out / LIBRARY)) if source.is_relative_to(self.out / LIBRARY) else source.name
        entry.update({k: v for k, v in extra.items() if v is not None})
        self.files.append(entry)

    def save(self, **meta):
        (self.out / "manifest.json").write_text(json.dumps(
            {**meta, "files": self.files, "changes": self.changes}, indent=2, ensure_ascii=False) + "\n")


def unlock(root: Path):
    """Gives back the permissions an earlier build took away (a locked folder, an
    unreadable file), so it can be replaced."""
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root, onerror=None):
        for d in dirnames:
            full = Path(dirpath) / d
            if not full.is_symlink():
                full.chmod(0o755)
        for f in filenames:
            full = Path(dirpath) / f
            if not full.is_symlink():
                full.chmod(0o644)


def prepare_out(out: Path, replace: bool):
    if not out.parent.is_dir():
        sys.exit(f"FATAL: {out.parent} does not exist. Create it first (mkdir), so it is yours and not root's.")
    if out.exists() and any(out.iterdir()):
        if not (out / MARKER).is_file():
            sys.exit(f"FATAL: {out} is not empty and was not made by this script; nothing was changed.")
        if not replace:
            sys.exit(f"FATAL: {out} holds an earlier build. Pass --replace to rebuild it.")
        unlock(out / LIBRARY)
        shutil.rmtree(out / LIBRARY, ignore_errors=True)
        (out / "manifest.json").unlink(missing_ok=True)
    out.mkdir(exist_ok=True)
    (out / MARKER).write_text("Made by tools/make_scenarios.py; replaced by build --replace.\n")


def build(args):
    rng = random.Random(args.seed)
    out = Path(args.out).resolve()
    seed = Path(args.seed_dir).resolve() if args.seed_dir else None
    if seed and (out.is_relative_to(seed) or seed.is_relative_to(out)):
        sys.exit("FATAL: the output and the seed folder must not contain one another.")
    donor_dir = Path(args.exif_donors).resolve() if args.exif_donors else None
    if donor_dir and not donor_dir.is_dir():
        sys.exit(f"FATAL: --exif-donors is not a folder: {donor_dir}")
    if donor_dir and (out.is_relative_to(donor_dir) or donor_dir.is_relative_to(out)):
        sys.exit("FATAL: the output and the donor folder must not contain one another.")
    donors = sorted(p for p in donor_dir.rglob("*") if p.is_file() and p.suffix.lower() in EDITABLE) if donor_dir else []
    prepare_out(out, args.replace)
    before = snapshot(seed) if seed else None
    lib = out / LIBRARY
    m = Manifest(out)

    # 1. Originals: every seed photo, hard-linked, in its own folder layout.
    originals = []
    if seed:
        for src in seed_photos(seed, skip=donor_dir):
            dest = lib / "originals" / src.relative_to(seed)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dest)
                linked = True
            except OSError:                   # another filesystem or mount: copy instead
                shutil.copy2(src, dest)
                linked = False
            originals.append(dest)
            m.add(dest, "original", "indexed", hard_link=linked)
    else:
        for src in generate_seeds(lib / "originals" / "generated", rng):
            originals.append(src)
            m.add(src, "original", "indexed", generated=True)
    if not originals:
        sys.exit("FATAL: the seed folder holds no photos.")
    grafted = graft_exif(originals, donors, rng, m) if donors else 0
    if donors:
        print(f"exif: {grafted} photo(s) given a sample camera file's tags, from {len(donors)} donor(s)")
        # A few donors as themselves: real camera metadata on a picture a few pixels wide.
        for donor in rng.sample(donors, min(6, len(donors))):
            dest = lib / "scenarios" / "tiny-camera-files" / donor.name
            fresh_copy(donor, dest)
            m.add(dest, "tiny_camera_file", "Indexed; a picture a few pixels wide with a real camera's tags")
    raster = [p for p in originals if opens(p)]
    jpegs = [p for p in raster if p.suffix.lower() in EDITABLE] or raster
    if not raster:
        sys.exit("FATAL: no seed photo can be opened, so no scenario can be derived from one.")
    pick = lambda pool, n: rng.sample(pool, min(n, len(pool)))
    sc = lib / "scenarios"

    # 2. Exact duplicates: second links under other names and folders.
    for i, src in enumerate(pick(originals, rng.randint(20, 40))):
        dest = sc / "duplicates" / f"album-{i % 4}" / f"copy of {src.name}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.link(src, dest)
        m.add(dest, "exact_duplicate", "Duplicate of its original (same content): copied once", src)

    # 3. The same photo with its metadata stripped: different bytes, same picture.
    for src in pick(jpegs, 4):
        dest = sc / "duplicate-no-exif" / src.name
        fresh_copy(src, dest)
        exiftool(dest, "-all=")
        m.add(dest, "duplicate_without_exif", "Indexed separately (different bytes); Undated by file time", src)

    # 4-5. Resized copies, with and without the original's EXIF.
    for keep, folder in ((True, "resized-with-exif"), (False, "resized-without-exif")):
        for src in pick(raster, 3):
            dest = sc / folder / f"{src.stem}-half.jpg"
            dest.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(src) as im:
                exif = im.info.get("exif") if keep else None
                small = im.convert("RGB").resize((max(1, im.width // 2), max(1, im.height // 2)))
                small.save(dest, "JPEG", quality=85, **({"exif": exif} if exif else {}))
            if keep and not exif and src.suffix.lower() in EDITABLE:
                exiftool(dest, "-tagsFromFile", str(src), "-all:all")
            m.add(dest, "resized_" + ("with" if keep else "without") + "_exif",
                  "Indexed separately; a near-duplicate of its original" + ("" if keep else "; Undated"), src)

    # 6. Converted to another format.
    targets = [("png", "PNG"), ("webp", "WEBP"), ("tiff", "TIFF")] + ([("heic", "HEIF")] if HEIF else [])
    for i, src in enumerate(pick(raster, 24)):
        ext, fmt = targets[i % len(targets)]
        if src.suffix.lower().lstrip(".") == ext:
            ext, fmt = targets[(i + 1) % len(targets)]
        dest = sc / "converted" / ext / f"{src.stem}.{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.convert("RGB").save(dest, fmt)
        if src.suffix.lower() in EDITABLE and ext in ("tiff", "webp", "png"):
            subprocess.run(["exiftool", "-q", "-q", "-overwrite_original", "-tagsFromFile", str(src),
                            "-DateTimeOriginal", "-CreateDate", "-Make", "-Model", str(dest)], check=False)
        m.add(dest, "format_converted", f"Indexed as .{ext}; a near-duplicate of its original", src)

    # 7. Dates the engine must file (JPEG copies, EXIF rewritten).
    dated = [
        ("no-date", ["-DateTimeOriginal=", "-CreateDate=", "-ModifyDate="], "Undated, filed by file time (2011)",
         {"mtime": 1_300_000_000}),
        ("with-offset", ["-DateTimeOriginal=2022:07:04 21:30:00", "-OffsetTimeOriginal=+09:00"],
         "Filed 2022/07; the Inspector shows the time with UTC+09:00", {}),
        ("conflicting", ["-DateTimeOriginal=2019:03:10 08:00:00", "-CreateDate=2021:11:20 18:00:00"],
         "Filed by DateTimeOriginal (2019/03); the Inspector shows both dates", {}),
        # "#=" writes the value raw, past ExifTool's own date check, which refuses it.
        ("invalid", ["-DateTimeOriginal#=0000:00:00 00:00:00"], "An unusable date: Undated by file time", {}),
        ("future", ["-DateTimeOriginal=2031:01:01 12:00:00"], "Filed as recorded (2031), a date to question", {}),
        ("old", ["-DateTimeOriginal=1958:05:17 14:00:00"], "Filed 1958/05", {}),
    ]
    for (name, tags, expect, extra), src in zip(dated, pick(jpegs, len(dated)) * 2):
        dest = sc / "dates" / f"{name}-{src.stem}.jpg"
        fresh_copy(src, dest)
        exiftool(dest, *tags)
        if "mtime" in extra:
            os.utime(dest, (extra["mtime"], extra["mtime"]))
        m.add(dest, f"date_{name.replace('-', '_')}", expect, src)

    # The same picture dated 55 years apart: only the EXIF differs, so two photos with
    # different bytes and the same pixels, filed in two years. Nothing pairs them yet;
    # the similarity review (engine-spec 9.3) is what should.
    for src in pick(jpegs, 1):
        for year, other in ((2024, 1969), (1969, 2024)):
            dest = sc / "dates" / f"same-picture-{year}-{src.stem}.jpg"
            fresh_copy(src, dest)
            exiftool(dest, f"-DateTimeOriginal={year}:06:15 12:00:00")
            m.add(dest, f"same_picture_{year}", f"Filed {year}/06; the same picture as the one filed {other}", src)

    # 8. Names: collisions at the destination, and awkward spellings.
    pool = pick(jpegs, 6)
    named = [("same-name/trip-a/IMG_0001.jpg", "Same name, different photo: the second at the destination gets _1"),
             ("same-name/trip-b/IMG_0001.jpg", "Same name, different photo: one of the pair is renamed on arrival"),
             ("names/UPPER CASE.JPG", "An upper-case extension, indexed like .jpg"),
             ("names/Été à la plage — 01.jpg", "Spaces, accents and a dash, kept intact"),
             ("names/" + "a-very-long-filename-" * 8 + ".jpg", "A 170-character name, kept intact"),
             ("names/Beach.jpg", "Two names that differ only in case, in one folder")]
    for (rel, expect), src in zip(named, pool * 2):
        dest = sc / rel
        fresh_copy(src, dest)
        exiftool(dest, f"-ImageDescription=scenario {rel}")       # distinct bytes: never a duplicate
        m.add(dest, "name_" + rel.split("/")[0].replace("-", "_"), expect, src)
    if pool:
        dest = sc / "names" / "beach.jpg"
        fresh_copy(pool[-1], dest)
        exiftool(dest, "-ImageDescription=lower-case twin")
        m.add(dest, "name_case_only", "Two names that differ only in case, in one folder", pool[-1])

    # 9. Every EXIF orientation, for Rotate.
    if jpegs:
        src = rng.choice(jpegs)
        for n in range(1, 9):
            dest = sc / "orientation" / f"orientation-{n}.jpg"
            fresh_copy(src, dest)
            exiftool(dest, f"-Orientation#={n}")
            m.add(dest, "orientation", f"EXIF Orientation {n}", src)

    # 10. Files that must fail or be left out, and awkward folders.
    edge = sc / "edge"
    edge.mkdir(parents=True, exist_ok=True)
    (edge / "zero-bytes.jpg").write_bytes(b"")
    m.add(edge / "zero-bytes.jpg", "edge_zero_bytes",
          "Failed: Not an image (the file is empty); in the log, never copied")
    body = rng.choice(jpegs).read_bytes()
    (edge / "truncated.jpg").write_bytes(body[: len(body) // 3])
    m.add(edge / "truncated.jpg", "edge_truncated", "Failed: its picture cannot be decoded; retained at source despite readable EXIF")
    (edge / "not-a-photo.jpg").write_text("This is text with a photo's extension.\n")
    m.add(edge / "not-a-photo.jpg", "edge_not_an_image",
          "Failed: Not an image (its content is text); in the log, never copied")
    side = rng.choice(jpegs)
    dest = edge / "with-sidecar.jpg"
    fresh_copy(side, dest)
    exiftool(dest, "-ImageDescription=has a sidecar")
    (edge / "with-sidecar.xmp").write_text('<x:xmpmeta xmlns:x="adobe:ns:meta/"/>\n')
    m.add(dest, "edge_sidecar", "Indexed; its .xmp sidecar is not a photo and is left out", side)
    tiny = edge / "tiny-64x48.jpg"
    with Image.open(rng.choice(raster)) as im:
        im.convert("RGB").resize((64, 48)).save(tiny, "JPEG")
    m.add(tiny, "edge_tiny", "Indexed: a low-resolution image")
    link = edge / "symlink-to-a-photo.jpg"
    link.symlink_to(os.path.relpath(originals[0], edge))
    m.add(link, "edge_symlink", "Left out: symlinks are not followed")
    locked = edge / "unreadable.jpg"
    fresh_copy(rng.choice(jpegs), locked)
    exiftool(locked, "-ImageDescription=unreadable")
    locked.chmod(0)
    m.add(locked, "edge_unreadable", "Failed: permission denied (the container's user cannot read it)")
    (sc / "empty-folder").mkdir(exist_ok=True)
    deep = sc / "deep" / "a" / "b" / "c" / "d" / "e" / "f" / "deep.jpg"
    fresh_copy(rng.choice(jpegs), deep)
    exiftool(deep, "-ImageDescription=deep")
    m.add(deep, "edge_deep_folder", "Indexed from seven folders down")

    # 11. A RAW beside a JPEG of the same name, when the seed has a RAW.
    raws = [p for p in originals if p.suffix.lower() in RAW_EXTENSIONS]
    if raws and jpegs:
        raw = rng.choice(raws)
        pair = sc / "raw-and-jpeg"
        pair.mkdir(parents=True, exist_ok=True)
        os.link(raw, pair / raw.name)
        m.add(pair / raw.name, "raw_pair", "The RAW, indexed", raw)
        dest = pair / f"{raw.stem}.jpg"
        fresh_copy(rng.choice(jpegs), dest)
        exiftool(dest, "-ImageDescription=raw pair")
        m.add(dest, "raw_pair", "A JPEG with the RAW's name: both indexed, distinct content")

    # 12. NAS system folders without a leading dot, as a source on a NAS share holds them.
    # Synology keeps thumbnails of every photo in @eaDir/<photo name>/ and deleted files in
    # #recycle/; QNAP's .@__thumb/ starts with a dot, which the Index already skips.
    nas = sc / "nas-share"
    for src in pick(jpegs, 2):
        photo = nas / "album" / src.name
        fresh_copy(src, photo)
        exiftool(photo, "-ImageDescription=on a NAS share")
        m.add(photo, "nas_photo", "Indexed: the photo itself", src)
        for size, name in ((1280, "SYNOPHOTO_THUMB_XL.jpg"), (320, "SYNOPHOTO_THUMB_M.jpg")):
            for folder, scenario in ((nas / "album" / "@eaDir" / src.name, "nas_synology_thumbnail"),
                                     (nas / "album" / ".@__thumb" / src.name, "nas_qnap_thumbnail")):
                dest = folder / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(src) as im:
                    im.convert("RGB").resize((max(1, im.width * size // max(im.size)),
                                              max(1, im.height * size // max(im.size)))).save(dest, "JPEG", quality=80)
                m.add(dest, scenario, "Left out: the NAS's own thumbnail of a photo, not a photo", src,
                      open_question="@eaDir has no leading dot, so the Index's dot rule does not cover it"
                      if scenario == "nas_synology_thumbnail" else None)
    for src in pick(jpegs, 1):
        dest = nas / "#recycle" / "album" / f"deleted-{src.name}"
        fresh_copy(src, dest)
        exiftool(dest, "-ImageDescription=in the recycle bin")
        m.add(dest, "nas_recycle_bin", "Left out: a file the user deleted on the NAS", src,
              open_question="#recycle has no leading dot; whether a recycle bin is ever a source is undecided")

    # 13. A Live Photo (a still and its video, one name) and a motion photo (the video inside
    # the JPEG). The videos are stand-ins: a container's opening bytes, not playable footage.
    live = sc / "live-photo"
    for src in pick(raster, 1):
        still = live / ("IMG_0001.HEIC" if HEIF else "IMG_0001.JPG")
        still.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.convert("RGB").save(still, "HEIF" if HEIF else "JPEG")
        subprocess.run(["exiftool", "-q", "-q", "-overwrite_original", "-DateTimeOriginal=2019:06:15 12:00:00",
                        str(still)], check=False)
        m.add(still, "live_photo_still", "Indexed: the still of a Live Photo", src)
        movie = live / "IMG_0001.MOV"
        movie.write_bytes(QUICKTIME + b"\0" * 2048)
        m.add(movie, "live_photo_video", "Its video: left in place unless .mov is among the chosen extensions",
              stand_in=True, open_question="a Move of the still leaves its video behind, unconnected")
    for src in pick(jpegs, 1):
        dest = live / "MVIMG_20190615_120000.jpg"
        fresh_copy(src, dest)
        exiftool(dest, "-XMP-GCamera:MicroVideo=1", "-XMP-GCamera:MicroVideoVersion=1",
                 f"-XMP-GCamera:MicroVideoOffset={len(MP4)}", "-XMP-GCamera:MicroVideoPresentationTimestampUs=0")
        with open(dest, "ab") as fh:           # the video after the picture, as Google's camera writes it
            fh.write(MP4)
        m.add(dest, "motion_photo", "Indexed as one photo; the video inside travels with it, bytes intact", src,
              stand_in=True)

    # 14. A date only in the name: no EXIF, a file time years off, names cameras and apps write.
    named_dates = [("IMG_20190615_120000.jpg", "2019-06-15"), ("IMG-20190615-WA0001.jpg", "2019-06-15"),
                   ("PXL_20190615_120000123.jpg", "2019-06-15"), ("20190615_120000.jpg", "2019-06-15"),
                   ("Screenshot_2019-06-15-12-00-00.png", "2019-06-15"), ("DSC_0001.JPG", None)]
    for (name, when), src in zip(named_dates, pick(jpegs, len(named_dates)) * 2):
        dest = sc / "date-in-name" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith(".png"):
            with Image.open(src) as im:
                im.convert("RGB").save(dest, "PNG")
            record_altered(dest)
        else:
            fresh_copy(src, dest)
            exiftool(dest, "-all=")
        os.utime(dest, (1_300_000_000, 1_300_000_000))
        m.add(dest, "date_in_name_only" if when else "date_nowhere",
              f"Undated, filed by file time (2011); its name says {when}" if when
              else "Undated, filed by file time (2011); nothing in its name is a date", src,
              name_date=when, open_question="the planned name-date suggestion (TODO.md, No capture date)"
              if when else None)

    # 15. A camera clock wrong for a whole trip: the camera a year early, the phone right.
    trip = sc / "clock-off-by-a-year"
    for i, src in enumerate(pick(jpegs, 5)):
        for device, year, make in (("camera", 2008, "Canon"), ("phone", 2009, "Apple")):
            dest = trip / device / f"{device}-{i + 1:02d}.jpg"
            fresh_copy(src, dest)
            exiftool(dest, f"-DateTimeOriginal={year}:07:04 1{i}:00:00", f"-Make={make}",
                     f"-ImageDescription={device} {i}")
            m.add(dest, "clock_off_camera" if device == "camera" else "clock_off_phone",
                  "Filed as recorded (2008/07): the camera's clock was a year early" if device == "camera"
                  else "Filed 2009/07: the same trip, from a phone with the right clock", src,
                  open_question="a batch correction for one device's photos" if device == "camera" else None)

    # 16. Time zones at midnight, and a burst inside one second.
    boundary = [("before-midnight-tokyo", "2019:12:31 23:30:00", "+09:00", "Filed 2019/12/31, its local date"),
                ("before-midnight-new-york", "2019:12:31 23:30:00", "-05:00",
                 "Filed 2019/12/31, its local date, though in UTC it is 2020-01-01"),
                ("midnight", "2020:01:01 00:00:00", "+00:00", "Filed 2020/01/01")]
    for (name, when, offset, expect), src in zip(boundary, pick(jpegs, len(boundary)) * 2):
        dest = sc / "day-boundary" / f"{name}.jpg"
        fresh_copy(src, dest)
        exiftool(dest, f"-DateTimeOriginal={when}", f"-OffsetTimeOriginal={offset}")
        m.add(dest, "day_boundary", expect, src)
    for src in pick(jpegs, 1):
        for i in range(5):
            # Named against their order in time: name order and time order disagree.
            dest = sc / "burst" / f"burst-{5 - i}.jpg"
            fresh_copy(src, dest)
            exiftool(dest, "-DateTimeOriginal=2018:05:20 15:42:07", f"-SubSecTimeOriginal={(i + 1) * 15:03d}",
                     f"-ImageDescription=burst {i}")
            m.add(dest, "burst_same_second", f"Frame {i + 1} of a burst in one second: ordered by its sub-seconds",
                  src, subsec=f"{(i + 1) * 15:03d}", open_question="whether sorting uses sub-seconds")

    # 17. Look-alikes the similarity search should pair with their original.
    looks = sc / "look-alikes"
    for src in pick(raster, 1):
        with Image.open(src) as im:
            base = im.convert("RGB")
        variants = {
            "rotated-90": base.rotate(-90, expand=True),
            "cropped": base.crop((base.width // 10, base.height // 10, base.width * 9 // 10, base.height * 9 // 10)),
            "black-and-white": ImageOps.grayscale(base).convert("RGB"),
            "colour-graded": ImageEnhance.Color(ImageEnhance.Brightness(base).enhance(1.15)).enhance(1.6),
        }
        marked = base.copy()
        ImageDraw.Draw(marked).text((marked.width // 20, marked.height * 9 // 10), "(c) Someone 2019", fill=(255, 255, 255))
        variants["watermarked"] = marked
        for name, img in variants.items():
            dest = looks / f"{src.stem}-{name}.jpg"
            dest.parent.mkdir(parents=True, exist_ok=True)
            img.save(dest, "JPEG", quality=88)
            record_altered(dest)
            m.add(dest, f"look_alike_{name.replace('-', '_')}", "Has similar photos pairs it with its original", src,
                  open_question={"rotated-90": "rotated matches are missed (TODO.md, Similar photos)",
                             "cropped": "whether a crop should be paired"}.get(name))

    # 18. Formats and sizes that strain a reader: past Pillow's decompression guard (warned
    # at 89.5 megapixels, refused at twice that), 16-bit, CMYK, multi-page, animated, progressive.
    odd = sc / "formats"
    odd.mkdir(parents=True, exist_ok=True)
    for name, size, expect in (("panorama-96mp.jpg", (12000, 8000), "Indexed; past Pillow's 89.5-megapixel warning"),
                               ("stitched-200mp.jpg", (20000, 10000),
                                "Past twice Pillow's limit: a thumbnail cannot be made the ordinary way")):
        img = Image.new("L", size, 90)
        ImageDraw.Draw(img).rectangle((size[0] // 3, size[1] // 3, size[0] // 2, size[1] // 2), fill=200)
        img.save(odd / name, "JPEG", quality=70)
        del img
        record_altered(odd / name)
        m.add(odd / name, "large_image", expect, megapixels=size[0] * size[1] // 1_000_000,
              open_question="how a picture over Pillow's limit is thumbnailed and hashed" if size[0] > 15000 else None)
    src = rng.choice(raster)
    with Image.open(src) as im:
        base = im.convert("RGB")
    small = base.resize((max(1, base.width // 2), max(1, base.height // 2)))
    small.convert("I;16").save(odd / "sixteen-bit.png", "PNG")
    m.add(odd / "sixteen-bit.png", "format_16_bit_png", "Indexed: a 16-bit greyscale PNG", src)
    small.convert("CMYK").save(odd / "cmyk.jpg", "JPEG", quality=88)
    m.add(odd / "cmyk.jpg", "format_cmyk_jpeg", "Indexed: a CMYK JPEG, as print workflows write", src)
    small.save(odd / "multi-page.tiff", "TIFF", save_all=True,
               append_images=[ImageOps.grayscale(small), small.rotate(180)])
    m.add(odd / "multi-page.tiff", "format_multi_page_tiff", "Indexed as one photo: the first of three pages", src)
    frames = [small.resize((160, 120)).rotate(a) for a in (0, 90, 180, 270)]
    frames[0].save(odd / "animated.gif", "GIF", save_all=True, append_images=frames[1:], duration=200, loop=0)
    m.add(odd / "animated.gif", "format_animated_gif", "Indexed as one photo: its first frame", src)
    small.save(odd / "progressive.jpg", "JPEG", quality=85, progressive=True)
    m.add(odd / "progressive.jpg", "format_progressive_jpeg", "Indexed: a progressive JPEG", src)
    for f in odd.iterdir():
        if f.is_file() and not f.name.startswith("."):
            record_altered(f)

    # 19. One name in its two Unicode forms: composed (NFC, as Linux and Windows usually
    # write) and decomposed (NFD, as macOS writes). They look the same; they are two names.
    for (form, name), src in zip((("NFC", unicodedata.normalize("NFC", "Café au lait.jpg")),
                                  ("NFD", unicodedata.normalize("NFD", "Café au lait.jpg"))), pick(jpegs, 2) * 2):
        dest = sc / "unicode-names" / name
        fresh_copy(src, dest)
        exiftool(dest, f"-ImageDescription=unicode {form}", "-DateTimeOriginal=2017:08:12 10:00:00")
        m.add(dest, "unicode_" + form.lower(), f"Indexed; its name is in {form}, and looks identical to the other",
              src, open_question="a destination or search that normalizes names would see one name twice")

    # 20. Names that differ only in case, from two folders, on one day: one destination
    # folder, where a case-insensitive filesystem (exFAT, SMB) sees one name twice.
    for (folder, name), src in zip((("camera", "IMG_0042.JPG"), ("phone", "img_0042.jpg")), pick(jpegs, 2) * 2):
        dest = sc / "case-at-destination" / folder / name
        fresh_copy(src, dest)
        exiftool(dest, "-DateTimeOriginal=2016:04:09 09:00:00", f"-ImageDescription=case {folder}")
        m.add(dest, "case_at_destination", "Filed 2016/04/09 beside a name differing only in case; "
              "on a case-insensitive destination the second must get _1", src)

    # 21. A folder the Index cannot open.
    # Written without record_altered: its guard would sit in the folder this then locks.
    # A plain copy and ExifTool's own rewrite are new files, never a link into the seed.
    locked = sc / "edge" / "locked-folder"
    inside = locked / "inside.jpg"
    locked.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rng.choice(jpegs), inside)
    subprocess.run(["exiftool", "-q", "-q", "-overwrite_original", "-ImageDescription=in a locked folder",
                    str(inside)], check=True)
    m.add(inside, "edge_locked_folder", "Not indexed: its folder cannot be opened, which is reported, not skipped silently",
          open_question="how the Index reports a folder it cannot open")
    locked.chmod(0)

    m.save(seed=args.seed, seed_dir=str(seed) if seed else None, built_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    counts = {}
    for f in m.files:
        counts[f["scenario"]] = counts.get(f["scenario"], 0) + 1
    print(f"library: {out / LIBRARY}")
    print(f"made {len(m.files)} file(s): " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if before is not None:
        check_untouched(seed, before)


# --- Change -----------------------------------------------------------------------

def change(args):
    """One round of every kind of change. Run it after an Index and a Copy, then Index
    and Copy again: each change is something the engine must notice and record."""
    rng = random.Random(args.seed + 1)
    out = Path(args.out).resolve()
    if not (out / MARKER).is_file():
        sys.exit(f"FATAL: {out} was not made by build; nothing was changed.")
    data = json.loads((out / "manifest.json").read_text())
    seed = Path(data["seed_dir"]) if data.get("seed_dir") else None
    before = snapshot(seed) if seed and seed.is_dir() else None
    lib = out / LIBRARY
    rnd = len({c["round"] for c in data["changes"]}) + 1
    used = {c["path"] for c in data["changes"]}
    candidates = [lib / f["path"] for f in data["files"]
                  if f["scenario"] == "original" and f["path"] not in used and (lib / f["path"]).is_file()
                  and opens(lib / f["path"])]
    if len(candidates) < 8:
        sys.exit("FATAL: too few unchanged originals left for another round; rebuild with build --replace.")
    rng.shuffle(candidates)
    log = []

    def record(kind, path, expect, **extra):
        log.append({"round": rnd, "kind": kind, "path": str(path.relative_to(lib)), "expect": expect, **extra})

    # Edited in place: same path, new content.
    p = candidates.pop()
    def edited(tmp, src=p):
        with Image.open(src) as im:
            img = im.convert("RGB")
            ImageDraw.Draw(img).rectangle((0, 0, img.width // 4, img.height // 4), fill=(255, 0, 0))
            # The temporary name ends .tmp, so the format is the original's, named.
            img.save(tmp, im.format or "JPEG", **({"exif": im.info["exif"]} if "exif" in im.info else {}))
    replace_with(p, edited)
    record("edited_in_place", p, "The next Index records new content at the same path")

    # Only its file time changed: the bytes are the same, so nothing is re-read as changed.
    p = candidates.pop()
    replace_with(p, lambda tmp, src=p: shutil.copy2(src, tmp))
    os.utime(p, (time.time(), time.time()))
    record("touched_only", p, "Same content with a new file time: recognised as unchanged")

    # Renamed in its folder, and moved to another folder.
    p = candidates.pop()
    new = p.with_name(f"renamed-{p.name}")
    os.rename(p, new)
    record("renamed", new, "The old path is gone and the new one is indexed; its content is already known",
           was=str(p.relative_to(lib)))
    p = candidates.pop()
    moved = lib / "scenarios" / "moved" / p.name
    moved.parent.mkdir(parents=True, exist_ok=True)
    os.rename(p, moved)
    record("moved", moved, "Moved within the source: the new path is indexed", was=str(p.relative_to(lib)))

    # Deleted from the source (after a Copy, its copy remains at the destination).
    p = candidates.pop()
    p.unlink()
    record("deleted", p, "Source gone; its destination copy is still recorded")

    # Replaced by a different photo at the same path.
    p, other = candidates.pop(), candidates.pop()
    replace_with(p, lambda tmp, src=other: shutil.copy2(src, tmp))
    record("replaced", p, "Same path, another photo's content: the next Index records the change",
           content_of=str(other.relative_to(lib)))

    # New duplicates of photos already copied.
    for i, src in enumerate(candidates[:3]):
        dest = lib / "scenarios" / "new-duplicates" / f"again-{i}-{src.name}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.link(src, dest)
        record("new_duplicate", dest, "A new exact duplicate of a photo already copied: skipped",
               of=str(src.relative_to(lib)))
    del candidates[:3]

    # Its EXIF date changed after it was filed.
    jp = [c for c in candidates if c.suffix.lower() in EDITABLE]
    if jp:
        p = jp[0]
        replace_with(p, lambda tmp, src=p: shutil.copy2(src, tmp))
        exiftool(p, "-DateTimeOriginal=2020:02:29 12:00:00")
        record("exif_date_changed", p, "A new date taken (2020/02/29): new content, filed by the new date")

    # Photos coming back to the source, from the destination: one whose original a Move
    # removed, and one the user rejected. Copies, so the destination is unchanged.
    kept = set()
    if args.dest:
        dest_root = Path(args.dest).resolve()
        in_source = {hashlib.sha1(p.read_bytes()).hexdigest() for p in lib.rglob("*")
                     if p.is_file() and not p.is_symlink() and os.access(p, os.R_OK)}
        library = sorted(p for p in (dest_root / "library").rglob("*")
                         if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)
        moved = [p for p in library if hashlib.sha1(p.read_bytes()).hexdigest() not in in_source]
        back = lib / "scenarios" / "came-back"
        if moved:
            src = rng.choice(moved)
            dest = back / f"after-move-{src.name}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            record_altered(dest)
            kept.add(src)
            log.append({"round": rnd, "kind": "returned_after_move", "path": str(dest.relative_to(lib)),
                        "expect": "Identical to a photo already moved into the library: a duplicate, not copied again",
                        "of": str(src.relative_to(dest_root))})
        else:
            print("returned: no library copy whose original a Move removed; run a Move first to include one.")
        rejected = sorted(p for p in (dest_root / "rejects").rglob("*")
                          if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)
        if rejected:
            src = rng.choice(rejected)
            dest = back / f"after-reject-{src.name}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            record_altered(dest)
            kept.add(src)
            log.append({"round": rnd, "kind": "returned_after_reject", "path": str(dest.relative_to(lib)),
                        "expect": "Identical to a photo you rejected: kept out, as already rejected",
                        "of": str(src.relative_to(dest_root))})
        else:
            print("returned: nothing in Rejects; reject a photo first to include one.")

    # At the destination, when given: a copy deleted, one altered, and a stranger; never a
    # copy that just came back to the source, whose original must stay as it was.
    if args.dest:
        dest_root = Path(args.dest).resolve()
        copies = sorted(p for p in dest_root.rglob("*")
                        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS and p not in kept)
        if len(copies) < 2:
            print("destination: fewer than two copies there; run a Copy first. Destination changes skipped.")
        else:
            gone, altered = rng.sample(copies, 2)
            gone.unlink()
            log.append({"round": rnd, "kind": "destination_deleted", "path": str(gone.relative_to(dest_root)),
                        "expect": "The destination check reports it missing", "at": "destination"})
            with open(altered, "ab") as fh:
                fh.write(b"\0altered")
            log.append({"round": rnd, "kind": "destination_altered", "path": str(altered.relative_to(dest_root)),
                        "expect": "The destination check reports it changed", "at": "destination"})
            stranger = dest_root / "not-from-negativespace" / "stranger.jpg"
            stranger.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(rng.choice(copies)) as im:
                im.convert("RGB").resize((200, 150)).save(stranger, "JPEG")
            log.append({"round": rnd, "kind": "destination_unknown", "path": str(stranger.relative_to(dest_root)),
                        "expect": "The destination check reports a file the catalog never made", "at": "destination"})

    data["changes"].extend(log)
    (out / "manifest.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"round {rnd}: " + ", ".join(c["kind"] for c in log))
    if before is not None:
        check_untouched(seed, before)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="make OUT/library from the seed folder, with every scenario")
    b.add_argument("--seed-dir", help="folder of real photos, hard-linked, never written to (default: generate)")
    b.add_argument("--out", required=True, help="an empty folder, or one this script made earlier")
    b.add_argument("--replace", action="store_true", help="rebuild over this script's earlier output")
    b.add_argument("--seed", type=int, default=1, help="random seed: the same seed makes the same choices")
    b.add_argument("--exif-donors", help="folder of camera files kept for their metadata (e.g. ExifTool's samples)")
    c = sub.add_parser("change", help="one round of every kind of change, between runs")
    c.add_argument("--out", required=True, help="the folder build made")
    c.add_argument("--dest", help="the destination a Copy filled, for destination changes")
    c.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    try:
        (build if args.command == "build" else change)(args)
    finally:
        release_altered()


if __name__ == "__main__":
    main()
