#!/usr/bin/env python3
"""Builds a sample library of deliberate scenarios, for showing and testing what the
engine and the web interface do: duplicates and near-duplicates, dates the engine must
file, names that collide, files that must fail, and a round of changes between runs
that gives a photo's lineage something to show.

    build   Hard-links every photo in a seed folder into OUT/library, then adds the
            scenarios beside them. Run again as the seed folder grows: it replaces its
            own earlier output, and refuses any other non-empty folder.
    change  One round of every kind of change, applied to a built library (and, with
            --dest, to the destination a Copy filled): run it after an Index and a
            Copy, then Index and Copy again.

The seed folder is never written to. Hard links share the original's bytes AND its
inode, so a file edited in place would change the seed too: every file this script
alters is written as a new file and renamed over the old path, which breaks the link
first. Both commands finish by proving it: "seed: N file(s), untouched".

Without --seed-dir the photos are generated, so it runs anywhere with nothing to
download. OUT/manifest.json lists every file made, its scenario, and what the app
should show for it. --seed makes a run reproducible.

Run in the app image, which has Pillow, pillow-heif and ExifTool. Hard links need the
seed and OUT on one filesystem AND one mount, so mount their common parent once:

    mkdir -p /storage/linked-samples        # before the first run: docker would make it root's
    docker run --rm --user "$(id -u):$(id -g)" --entrypoint python3 \\
      -v /storage:/storage -v "$PWD":/app -w /app negativespace \\
      tests/make_scenarios.py build --seed-dir /storage/sample --out /storage/linked-samples/demo
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ns_db import RASTER_EXTENSIONS, RAW_EXTENSIONS, SUPPORTED_EXTENSIONS  # noqa: E402

from PIL import Image, ImageDraw, ImageFile  # noqa: E402

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


# --- Safety -----------------------------------------------------------------------

def snapshot(root: Path) -> dict:
    """Every seed file's size, mtime and inode: what a write through a link would change."""
    out = {}
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns, st.st_ino)
    return out


ALTERED = set()                   # inodes of every file this run wrote or rewrote


def check_untouched(root: Path, before: dict):
    """The promise, proved: nothing this run wrote shares an inode with a seed file, so
    no write reached the seed through a link. The seed folder may also be changing under
    another program (a download filling it): that is reported, never mistaken for ours."""
    after = snapshot(root)
    seed_inodes = {v[2] for v in after.values()} | {v[2] for v in before.values()}
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
    ALTERED.add(dest.stat().st_ino)


def replace_with(path: Path, write):
    """Writes a new file with `write(tmp)` and renames it over `path`: a hard-linked
    `path` loses its link instead of changing the file it shared bytes with."""
    tmp = path.with_name(f".{path.name}.tmp")
    write(tmp)
    os.replace(tmp, path)
    ALTERED.add(path.stat().st_ino)


def exiftool(path: Path, *args):
    """ExifTool on a file this script made. -overwrite_original writes a new file and
    renames it into place, so it could not write through a link either."""
    subprocess.run(["exiftool", "-q", "-q", "-overwrite_original", *args, str(path)], check=True)
    ALTERED.add(path.stat().st_ino)


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


def seed_photos(seed: Path) -> list:
    return sorted(p for p in seed.rglob("*")
                  if p.is_file() and not p.is_symlink() and p.suffix.lower() in SUPPORTED_EXTENSIONS)


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
        entry.update(extra)
        self.files.append(entry)

    def save(self, **meta):
        (self.out / "manifest.json").write_text(json.dumps(
            {**meta, "files": self.files, "changes": self.changes}, indent=2, ensure_ascii=False) + "\n")


def prepare_out(out: Path, replace: bool):
    if not out.parent.is_dir():
        sys.exit(f"FATAL: {out.parent} does not exist. Create it first (mkdir), so it is yours and not root's.")
    if out.exists() and any(out.iterdir()):
        if not (out / MARKER).is_file():
            sys.exit(f"FATAL: {out} is not empty and was not made by this script; nothing was changed.")
        if not replace:
            sys.exit(f"FATAL: {out} holds an earlier build. Pass --replace to rebuild it.")
        shutil.rmtree(out / LIBRARY, ignore_errors=True)
        (out / "manifest.json").unlink(missing_ok=True)
    out.mkdir(exist_ok=True)
    (out / MARKER).write_text("Made by tests/make_scenarios.py; replaced by build --replace.\n")


def build(args):
    rng = random.Random(args.seed)
    out = Path(args.out).resolve()
    seed = Path(args.seed_dir).resolve() if args.seed_dir else None
    if seed and (out.is_relative_to(seed) or seed.is_relative_to(out)):
        sys.exit("FATAL: the output and the seed folder must not contain one another.")
    prepare_out(out, args.replace)
    before = snapshot(seed) if seed else None
    lib = out / LIBRARY
    m = Manifest(out)

    # 1. Originals: every seed photo, hard-linked, in its own folder layout.
    originals = []
    if seed:
        for src in seed_photos(seed):
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
    m.add(edge / "truncated.jpg", "edge_truncated", "Indexed from its intact EXIF; its picture is cut short")
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

    # At the destination, when given: a copy deleted, one altered, and a stranger.
    if args.dest:
        dest_root = Path(args.dest).resolve()
        copies = sorted(p for p in dest_root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)
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
    c = sub.add_parser("change", help="one round of every kind of change, between runs")
    c.add_argument("--out", required=True, help="the folder build made")
    c.add_argument("--dest", help="the destination a Copy filled, for destination changes")
    c.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    (build if args.command == "build" else change)(args)


if __name__ == "__main__":
    main()
