#!/usr/bin/env python3
"""
End-to-end smoke tests for ns-engine.py.

Run this INSIDE the container (or anywhere ExifTool, Pillow, imagehash and
rawpy are installed) — it drives the real engine as a subprocess against real
image files, rather than importing it and stubbing things out. The exceptions
are a few content-safety tests that import the engine in-process to inject a
fault BETWEEN two steps of one function (after verification, before the
source is deleted) — a window a subprocess offers no way to act inside.

    docker build -t negativespace .
    docker run --rm -v "$PWD":/app -w /app negativespace python3 tests/engine_smoke_test.py

    # or directly, if deps are installed locally:
    python3 tests/engine_smoke_test.py

Options:
    --engine PATH   path to ns-engine.py (default: alongside this file's parent)
    --keep          leave the workspace on disk for inspection
    --filter NAME   run only tests whose name contains NAME
    -v              show engine stdout for each run

Environment:
    NS_TEST_RAW_DIR  Folder of genuine RAW files (any extension in the engine's
                     RAW_EXTENSIONS — .dng/.cr2/.cr3/.nef/.arw/.raf and the rest) to
                     exercise the rawpy decode path for real. That path cannot
                     be covered with synthetic fixtures — LibRaw rejects
                     fabricated files — so the test skips unless you point this
                     at real camera output. Worth doing at least once: it is
                     the only part of the engine no synthetic test can reach.

Exit code is non-zero if any test fails.
"""

import argparse
import contextlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ENGINE = None
WORKSPACE = None
VERBOSE = False
RESULTS = []


# ----------------------------------------------------------------- utilities

class Fail(AssertionError):
    pass


def check(condition, message):
    if not condition:
        raise Fail(message)


def engine_output(proc):
    """Everything the engine printed. Logging goes to stdout (configure_logging
    attaches a StreamHandler on sys.stdout), but read both streams so a test
    asserting on a log line cannot quietly pass or fail on the wrong one."""
    return (proc.stdout or "") + (proc.stderr or "")


def test(fn):
    """Registers a test function. Name doubles as the label."""
    RESULTS.append(fn)
    return fn


def run_engine(case, *args, expect_rc=0, timeout=300):
    """Runs the engine against a case directory. Returns CompletedProcess."""
    # Each case gets its OWN cache. The default is the shared /cache mount, and
    # make_photo() produces byte-identical files for a given seed — so without
    # this, one case's thumbnail would be reused as another's cache hit and any
    # assertion about what a run generated would depend on test order.
    cmd = [sys.executable, str(ENGINE),
           "--source", str(case / "src"),
           "--dest", str(case / "dest"),
           "--base", str(case / "appdata"),
           "--cache", str(case / "cache"),
           "--backups", str(case / "backups")] + [str(a) for a in args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        # Surface what the engine managed to print before it stalled. Without
        # this a hang reports only the command line — which is what happened in
        # CI, leaving a 300-second timeout with nothing to diagnose it from.
        # The last lines before the stall say which phase it died in.
        raw = e.stdout or b""
        partial = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
        tail = "\n".join(f"      | {l}" for l in partial.splitlines()[-25:])
        raise Fail(
            f"engine did not finish within {timeout}s — a HANG, not a slow run.\n"
            f"    args: {' '.join(str(a) for a in args) or '(index)'}\n"
            f"    last output before it stalled:\n{tail or '      | (nothing captured)'}"
        )
    if VERBOSE:
        print("\n".join("      | " + l for l in proc.stdout.splitlines()))
    if expect_rc is not None and proc.returncode != expect_rc:
        raise Fail(f"engine exited {proc.returncode}, expected {expect_rc}\n"
                   f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")
    return proc


def spawn_engine(case, *args):
    """Starts the engine without waiting, for signal/kill tests."""
    cmd = [sys.executable, str(ENGINE),
           "--source", str(case / "src"),
           "--dest", str(case / "dest"),
           "--base", str(case / "appdata"),
           "--cache", str(case / "cache"),
           "--backups", str(case / "backups")] + [str(a) for a in args]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def db(case):
    conn = sqlite3.connect(case / "appdata" / "db" / "ns_sqlite.db")
    conn.row_factory = sqlite3.Row
    return conn


def rows(case, sql, params=()):
    conn = db(case)
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def status_of(case, name):
    r = rows(case, "SELECT status FROM photos WHERE source_path LIKE ?", (f"%/{name}",))
    return r[0]["status"] if r else None


def dest_files(case):
    d = case / "dest"
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()) if d.exists() else []


def src_files(case):
    s = case / "src"
    return sorted(p.relative_to(s).as_posix() for p in s.rglob("*") if p.is_file())


def new_case(name):
    case = WORKSPACE / name
    (case / "src").mkdir(parents=True)
    (case / "appdata").mkdir(parents=True)
    # Its own backup storage, like its own cache: a shared /backups would let
    # one case's retention prune another's backups.
    (case / "backups").mkdir(parents=True)
    return case


def wait_for_move_to_start(case, timeout=60):
    """
    Blocks until the engine has actually begun writing to the destination.
    Signalling after a fixed sleep is a race — on a fast machine the whole move
    finishes first and the test silently stops exercising anything.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = case / "dest"
        if d.exists() and any(p.is_file() for p in d.rglob("*")):
            return True
        time.sleep(0.05)
    return False


def make_photo(path: Path, content_seed: str, date="2024:02:14 09:30:00", size=(64, 48),
               noise=False):
    """
    Writes a real JPEG with real EXIF. Pixel content is derived from the seed so
    that distinct seeds produce genuinely different bytes (different SHA-1),
    and an identical seed produces an identical file.
    """
    import hashlib
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    # md5, not hash(): str hashing is randomized per process, so hash() would
    # not be reproducible across runs and two seeds could collide mod 256 in
    # all three channels. Painting md5 bytes into the top row guarantees that
    # distinct seeds differ in actual pixel data, while an identical seed
    # reproduces byte-identical output (which the duplicate and idempotency
    # tests both depend on).
    if noise:
        # Incompressible content, so the file on disk is genuinely large and a
        # move takes long enough to interrupt. Random rather than seeded: these
        # callers need distinct files, not reproducible ones.
        img = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    else:
        digest = hashlib.md5(content_seed.encode()).digest()
        img = Image.new("RGB", size, (digest[0], digest[1], digest[2]))
        for x in range(min(len(digest), size[0])):
            img.putpixel((x, 0), (digest[x], digest[(x + 1) % 16], digest[(x + 2) % 16]))
    img.save(path, "JPEG", quality=95)
    if date:
        subprocess.run(
            ["exiftool", "-overwrite_original", f"-DateTimeOriginal={date}",
             f"-CreateDate={date}", str(path)],
            capture_output=True, check=True,
        )


# --------------------------------------------------------------------- tests

@test
def index_excludes_hidden_and_appledouble():
    """Index: skips hidden files, AppleDouble sidecars and hidden trees."""
    case = new_case("index_hidden")
    make_photo(case / "src" / "IMG_0001.jpg", "a")
    make_photo(case / "src" / "sub" / "IMG_0002.JPG", "b")
    make_photo(case / "src" / "._IMG_0001.jpg", "appledouble")
    make_photo(case / "src" / ".Trashes" / "IMG_0003.jpg", "trash")
    (case / "src" / ".DS_Store").write_bytes(b"junk")

    run_engine(case)
    indexed = sorted(Path(r["source_path"]).name for r in rows(case, "SELECT source_path FROM photos"))
    check(indexed == ["IMG_0001.jpg", "IMG_0002.JPG"],
          f"expected only the two real photos, got {indexed}")
    check(not (case / "dest").exists(),
          "a bare Index created the destination tree; it must not write there")


@test
def an_index_alone_deletes_nothing():
    """
    Index classifies duplicates; it never removes one. Deletion lives inside
    the move/copy phase, which a bare Index does not enter at all — this pins
    that guarantee rather than leaving it implied by the Move tests.
    """
    case = new_case("index_keeps_duplicates")
    make_photo(case / "src" / "original.jpg", "SAME")
    make_photo(case / "src" / "nested" / "copy.jpg", "SAME")
    make_photo(case / "src" / "other.jpg", "DIFFERENT")
    before = src_files(case)

    run_engine(case)
    # A second Index acts on the classification the first one wrote, which is
    # where a cleanup pass would be tempting to run.
    run_engine(case)

    check(src_files(case) == before,
          f"an Index removed source files: {before} -> {src_files(case)}")
    check(not (case / "dest").exists(), "an Index wrote to the destination")

    statuses = sorted(r["status"] for r in rows(case, "SELECT status FROM photos"))
    check(statuses == ["Duplicate", "Pending", "Pending"],
          f"expected one duplicate classified and nothing removed, got {statuses}")

    removals = rows(case, "SELECT COUNT(*) c FROM photos WHERE status = 'Removed_Duplicate'")[0]["c"]
    check(removals == 0, "an Index marked a row Removed_Duplicate")
    op_statuses = {r["status"] for r in rows(case, "SELECT DISTINCT status FROM operations")}
    check("Removed_Duplicate" not in op_statuses,
          f"an Index recorded a removal operation: {sorted(op_statuses)}")

    modes = [r["mode"] for r in rows(case, "SELECT mode FROM runs ORDER BY id")]
    check(modes == ["INDEX", "INDEX"], f"expected two INDEX runs, got {modes}")


@test
def exts_accepts_bare_and_dotted():
    """--exts: 'jpg' and '.jpg' behave identically."""
    case = new_case("exts")
    make_photo(case / "src" / "a.jpg", "a")
    make_photo(case / "src" / "b.png", "b", date=None)

    run_engine(case, "--exts", "jpg")
    bare = {Path(r["source_path"]).name for r in rows(case, "SELECT source_path FROM photos")}
    check(bare == {"a.jpg"}, f"--exts jpg matched {bare or 'nothing'}; expected just a.jpg")

    case2 = new_case("exts_dotted")
    make_photo(case2 / "src" / "a.jpg", "a")
    make_photo(case2 / "src" / "b.png", "b", date=None)
    run_engine(case2, "--exts", ".jpg")
    dotted = {Path(r["source_path"]).name for r in rows(case2, "SELECT source_path FROM photos")}
    check(dotted == bare, f"dotted form gave {dotted}, bare form gave {bare}")


@test
def move_preserves_distinct_photos_sharing_a_filename():
    """Move: two different photos named alike both survive (the data-loss regression)."""
    case = new_case("collision")
    make_photo(case / "src" / "cardA" / "IMG_0001.jpg", "PHOTO-A")
    make_photo(case / "src" / "cardB" / "IMG_0001.jpg", "PHOTO-B")

    run_engine(case)
    run_engine(case, "--move")

    out = dest_files(case)
    check(len(out) == 2, f"expected BOTH photos at the destination, found {out}")
    check(any(f.endswith("IMG_0001.jpg") for f in out) and any("_1" in f for f in out),
          f"expected a suffixed second copy, got {out}")

    hashes = {r["sha1_hash"] for r in rows(case, "SELECT sha1_hash FROM photos")}
    check(len(hashes) == 2, "the two photos should have distinct hashes")
    check(src_files(case) == [], f"--move should have emptied source, left {src_files(case)}")
    collisions = rows(case, "SELECT COUNT(*) c FROM photos WHERE has_name_collision = 1")[0]["c"]
    check(collisions == 1, f"expected exactly one row flagged has_name_collision, got {collisions}")


@test
def exact_duplicate_removed_only_with_verified_copy():
    """Move: an exact duplicate is flagged and its source removed once a verified copy exists."""
    case = new_case("dupes")
    make_photo(case / "src" / "original.jpg", "SAME")
    make_photo(case / "src" / "nested" / "copy.jpg", "SAME")

    run_engine(case)
    statuses = {Path(r["source_path"]).name: r["status"]
                for r in rows(case, "SELECT source_path, status FROM photos")}
    check(sorted(statuses.values()) == ["Duplicate", "Pending"],
          f"expected one Pending anchor and one Duplicate, got {statuses}")

    run_engine(case, "--move")
    final = {Path(r["source_path"]).name: r["status"]
             for r in rows(case, "SELECT source_path, status FROM photos")}
    check("Removed_Duplicate" in final.values(), f"duplicate not cleaned up: {final}")
    check(len(dest_files(case)) == 1, f"only one physical copy should remain: {dest_files(case)}")
    check(src_files(case) == [], f"source should be empty, left {src_files(case)}")

    # Every row — the surviving copy AND each duplicate — must point at a file
    # that actually exists. A duplicate keeps the destination projected for it
    # at Index time under its own filename, which is never written; left
    # uncorrected the record describes a phantom, which is useless exactly when
    # it matters: "this was a duplicate, so where did its content end up?"
    for r in rows(case, "SELECT source_path, status, dest_path FROM photos"):
        check(r["dest_path"] and Path(r["dest_path"]).exists(),
              f"{Path(r['source_path']).name} ({r['status']}) points at a file that does not "
              f"exist: {r['dest_path']}")

    # ...and every member of the group is reachable from its sha1.
    group = rows(case, "SELECT sha1_hash, COUNT(*) n FROM photos GROUP BY sha1_hash")
    check(len(group) == 1 and group[0]["n"] == 2,
          f"both copies should share one sha1 group, got {group}")


@test
def duplicate_cleanup_rechecks_live_content():
    """Stale hashes or an unreadable destination must not authorize deletion."""
    for scenario in ("destination_changed", "source_changed", "destination_unreadable"):
        case = new_case("dupe_verify_" + scenario)
        make_photo(case / "src" / "first.jpg", "SAME")
        make_photo(case / "src" / "second.jpg", "SAME")
        run_engine(case)
        anchor = rows(case, "SELECT * FROM photos WHERE status = 'Pending'")[0]
        duplicate = rows(case, "SELECT * FROM photos WHERE status = 'Duplicate'")[0]
        run_engine(case, "--move", "--file-ids", anchor["id"])
        source = Path(duplicate["source_path"])
        destination = Path(anchor["dest_path"])

        if scenario == "destination_unreadable":
            destination.unlink()
            destination.mkdir()  # Exists, but hashing it raises IsADirectoryError.
        else:
            changed = source if scenario == "source_changed" else destination
            before = changed.stat()
            content = changed.read_bytes()
            changed.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
            # Preserve the stat cache deliberately: deletion must check live
            # source bytes even when Index regards the file as unchanged.
            os.utime(changed, ns=(before.st_atime_ns, before.st_mtime_ns))

        expected_source = source.read_bytes()
        run_engine(case, "--move", "--file-ids", duplicate["id"])
        check(source.exists(), f"{scenario}: deleted an unverified duplicate")
        check(source.read_bytes() == expected_source, f"{scenario}: modified the source")
        check(status_of(case, source.name) == "Duplicate",
              f"{scenario}: duplicate should remain available for retry")
        failures = rows(case, "SELECT error_message FROM operations "
                        "WHERE run_id = (SELECT MAX(id) FROM runs) AND status = 'Failed'")
        check(len(failures) == 1 and "Duplicate verification failed" in failures[0]["error_message"],
              f"{scenario}: verification failure missing from audit log: {failures}")


@test
def copy_is_non_destructive_and_idempotent():
    """Copy: sources untouched, and repeated Index+Copy cycles do not multiply files."""
    case = new_case("copy_idem")
    make_photo(case / "src" / "photo.jpg", "X")

    for cycle in (1, 2, 3):
        run_engine(case)
        run_engine(case, "--copy")
        out = dest_files(case)
        check(out == ["2024/02/14/photo.jpg"],
              f"cycle {cycle}: expected exactly one copy, got {out}")
        check(src_files(case) == ["photo.jpg"],
              f"cycle {cycle}: --copy must never touch the source")

    check(status_of(case, "photo.jpg") == "Copied",
          f"expected status Copied, got {status_of(case, 'photo.jpg')}")


@test
def file_ids_targeting_is_scoped():
    """--file-ids: only the selected file moves; duplicate cleanup stays in scope."""
    case = new_case("file_ids")
    make_photo(case / "src" / "wanted.jpg", "WANTED")
    make_photo(case / "src" / "untouched.jpg", "UNTOUCHED")
    # an exact-duplicate pair entirely outside the selection
    make_photo(case / "src" / "other1.jpg", "OTHERDUP")
    make_photo(case / "src" / "other2.jpg", "OTHERDUP")

    run_engine(case)
    wanted_id = rows(case, "SELECT id FROM photos WHERE source_path LIKE '%/wanted.jpg'")[0]["id"]
    run_engine(case, "--move", "--file-ids", str(wanted_id))

    remaining = src_files(case)
    check("wanted.jpg" not in remaining, "the targeted file should have moved")
    check("untouched.jpg" in remaining, "an untargeted file was moved")
    dup_left = [f for f in remaining if f.startswith("other")]
    check(len(dup_left) == 2,
          f"duplicate cleanup escaped the selection and deleted out-of-scope sources: {remaining}")


@test
def source_subdir_targeting_is_scoped():
    """--source-subdir: scopes to a folder without enumerating ids."""
    case = new_case("subdir")
    make_photo(case / "src" / "day1" / "a.jpg", "A")
    make_photo(case / "src" / "day1" / "b.jpg", "B")
    make_photo(case / "src" / "day2" / "c.jpg", "C")
    # a sibling whose name shares the prefix — must NOT be swept in
    make_photo(case / "src" / "day1extra" / "d.jpg", "D")

    run_engine(case)
    run_engine(case, "--move", "--source-subdir", "day1")

    remaining = src_files(case)
    check(sorted(remaining) == ["day1extra/d.jpg", "day2/c.jpg"],
          f"subdir targeting moved the wrong set; source still holds {remaining}")


@test
def source_subdir_with_wildcard_chars_is_literal():
    """--source-subdir: '_' and '%' in a folder name are literal, not LIKE wildcards."""
    case = new_case("subdirglob")
    # The prefix match runs through SQL LIKE, where '_' means "any single
    # character" and '%' means "any sequence". Unescaped, targeting My_Photos
    # would also sweep in MyXPhotos — copying files the user never selected,
    # or under --move deleting their sources. Folder names with underscores
    # are ordinary, and the web UI lets users pick arbitrary folders.
    make_photo(case / "src" / "My_Photos" / "a.jpg", "A")
    make_photo(case / "src" / "My_Photos" / "nested" / "b.jpg", "B")
    make_photo(case / "src" / "MyXPhotos" / "c.jpg", "C")
    make_photo(case / "src" / "100%Done" / "d.jpg", "D")
    make_photo(case / "src" / "100XDone" / "e.jpg", "E")

    run_engine(case)
    run_engine(case, "--move", "--source-subdir", "My_Photos")

    remaining = sorted(src_files(case))
    check(remaining == ["100%Done/d.jpg", "100XDone/e.jpg", "MyXPhotos/c.jpg"],
          f"'_' was treated as a LIKE wildcard; source still holds {remaining}")

    run_engine(case, "--move", "--source-subdir", "100%Done")

    remaining = sorted(src_files(case))
    check(remaining == ["100XDone/e.jpg", "MyXPhotos/c.jpg"],
          f"'%' was treated as a LIKE wildcard; source still holds {remaining}")


@test
def targeted_runs_skip_unchanged_files():
    """--source-subdir / --file-ids honour the unchanged-file skip, not just full scans."""
    case = new_case("targetskip")
    make_photo(case / "src" / "day1" / "a.jpg", "A")
    make_photo(case / "src" / "day1" / "b.jpg", "B")
    make_photo(case / "src" / "day2" / "c.jpg", "C")

    run_engine(case)  # full index; everything now has size+mtime recorded

    # A scoped re-run must not re-read files the catalog already matches.
    # partition_unchanged() used to be applied only to the full-scan branch,
    # so targeted runs re-hashed and re-decoded every file — the expensive
    # path, on exactly the runs the web UI issues.
    out = engine_output(run_engine(case, "--source-subdir", "day1"))
    check("Skipping 2 unchanged file(s)" in out,
          f"scoped re-run did not skip unchanged files; log said:\n{out}")

    # Touching one file must bring exactly that file back into the scan.
    target = case / "src" / "day1" / "a.jpg"
    os.utime(target, (time.time() + 10, time.time() + 10))
    out = engine_output(run_engine(case, "--source-subdir", "day1"))
    check("Skipping 1 unchanged file(s)" in out,
          f"a changed file was not re-scanned; log said:\n{out}")

    # --force-rehash still overrides the skip.
    out = engine_output(run_engine(case, "--source-subdir", "day1", "--force-rehash"))
    check("Skipping" not in out and "force-rehash" in out,
          f"--force-rehash did not bypass the skip; log said:\n{out}")


@test
def targeting_nothing_says_why():
    """A scoped run against an un-indexed catalog explains itself instead of quietly succeeding."""
    case = new_case("emptytarget")
    make_photo(case / "src" / "day1" / "a.jpg", "A")

    # No Index has ever run, so the catalog is empty. Both targeted modes read
    # the catalog rather than the filesystem, so they match nothing — and the
    # run would otherwise report "completed successfully (0 files)", which is
    # indistinguishable from having had nothing to do.
    out = engine_output(run_engine(case, "--copy", "--source-subdir", "day1"))
    check("No indexed files found" in out,
          f"a scoped copy against an empty catalog did not explain itself; log said:\n{out}")
    check("Run an Index over this source first" in out,
          f"the warning did not say how to fix it; log said:\n{out}")

    out = engine_output(run_engine(case, "--copy", "--file-ids", "1,2,3"))
    check("IDs exist only for files a previous Index recorded" in out,
          f"an unresolvable --file-ids selection did not explain itself; log said:\n{out}")

    # And once indexed, the same scoped command finds its file.
    run_engine(case)
    out = engine_output(run_engine(case, "--copy", "--source-subdir", "day1"))
    check("No indexed files found" not in out,
          f"scoped copy still reported an empty target after indexing; log said:\n{out}")
    check((case / "dest").exists(), "scoped copy produced no destination tree after indexing")


@test
def stale_selection_records_a_specific_failure():
    """A targeted file deleted outside the engine is recorded as Failed with a real reason."""
    case = new_case("stale")
    make_photo(case / "src" / "vanishing.jpg", "V")
    make_photo(case / "src" / "staying.jpg", "S")

    run_engine(case)
    ids = {Path(r["source_path"]).name: r["id"]
           for r in rows(case, "SELECT id, source_path FROM photos")}
    (case / "src" / "vanishing.jpg").unlink()

    # Must be a TARGETED run. A full directory scan never *discovers* a deleted
    # file, so it is simply not processed and keeps its previous status — that
    # is correct. The stale-selection case this checks is specific to
    # --file-ids / --source-subdir, per docs/engine-spec.md 4.2.
    run_engine(case, "--file-ids", f"{ids['vanishing.jpg']},{ids['staying.jpg']}")

    check(status_of(case, "vanishing.jpg") == "Failed",
          f"expected Failed, got {status_of(case, 'vanishing.jpg')}")
    msg = rows(case, "SELECT error_message FROM operations WHERE source_path LIKE '%vanishing%' "
                     "AND error_message IS NOT NULL ORDER BY id DESC LIMIT 1")
    check(msg and "Source file changed" in msg[0]["error_message"],
          f"expected the specific 'Source file changed' reason, got {msg}")
    check(status_of(case, "staying.jpg") == "Pending",
          "one bad file must not derail the rest of the scan")


@test
def unreadable_file_does_not_abort_the_scan():
    """A permission-denied file fails alone; the rest of the library still indexes."""
    if os.geteuid() == 0:
        raise Fail("SKIP: running as root, permission checks are bypassed")
    case = new_case("unreadable")
    for i in range(4):
        make_photo(case / "src" / f"ok{i}.jpg", f"ok{i}")
    bad = case / "src" / "bad.jpg"
    make_photo(bad, "bad")
    bad.chmod(0o000)
    try:
        run_engine(case)
        indexed = rows(case, "SELECT status FROM photos")
        check(len(indexed) == 5, f"expected all 5 files recorded, got {len(indexed)}")
        check(status_of(case, "bad.jpg") == "Failed", "unreadable file should be Failed")
        # Match on the FILENAME, not a substring of the full path: the
        # workspace prefix "ns-smoke-" itself contains "ok", so `"ok" in
        # source_path` matched every row — including bad.jpg — and asserted
        # the deliberately-unreadable file should be Pending.
        oks = [r for r in rows(case, "SELECT source_path, status FROM photos")
               if Path(r["source_path"]).name.startswith("ok")]
        check(len(oks) == 4, f"expected 4 readable files, matched {len(oks)}")
        check(all(r["status"] == "Pending" for r in oks),
              f"readable files should still be indexed normally: "
              f"{[(Path(r['source_path']).name, r['status']) for r in oks]}")
    finally:
        bad.chmod(0o644)


@test
def single_instance_lock_rejects_a_second_run():
    """Two engines against one --base cannot run concurrently."""
    import fcntl
    case = new_case("lock")
    make_photo(case / "src" / "a.jpg", "a")

    # Hold the engine's own lock file directly rather than racing a second
    # process — deterministic, with no dependence on how long a scan takes.
    lock_path = case / "appdata" / "engine.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        blocked = run_engine(case, expect_rc=1)
        combined = blocked.stdout + blocked.stderr
        check("already running" in combined,
              f"second run should refuse with a clear message; got:\n{combined}")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    # ...and succeeds once the lock is released.
    run_engine(case)


@test
def sigterm_during_move_cancels_cleanly():
    """SIGTERM mid-move: in-flight file finishes, remainder logged Cancelled, run marked Cancelled."""
    case = new_case("cancel")
    for i in range(120):
        make_photo(case / "src" / f"p{i:03d}.jpg", f"p{i}", size=(500, 400), noise=True)

    run_engine(case)
    proc = spawn_engine(case, "--move")
    check(wait_for_move_to_start(case), "move never started")
    proc.send_signal(signal.SIGTERM)
    # communicate, not wait: the engine logs to a pipe, and a full pipe would
    # block it forever against a wait() that never reads.
    output, _ = proc.communicate(timeout=180)

    run_row = rows(case, "SELECT status FROM runs ORDER BY id DESC LIMIT 1")[0]
    if run_row["status"] == "Completed":
        # The move outran the signal on this machine. Reporting that honestly
        # beats failing, but it does mean cancellation went untested here.
        raise Fail("SKIP: move completed before SIGTERM landed — raise the file "
                   "count or size in this test to exercise cancellation")
    check(run_row["status"] == "Cancelled", f"run should be Cancelled, got {run_row['status']}")
    # The watcher is what makes Cancelling visible while the current file
    # finishes; the in-process test proves the watcher, this proves main()
    # actually starts it.
    check("is Cancelling." in output, "the run never recorded Cancelling before it settled")
    cancelled = rows(case, "SELECT COUNT(*) c FROM operations WHERE status = 'Cancelled'")[0]["c"]
    check(cancelled > 0, "expected some files logged as Cancelled")
    stuck = rows(case, "SELECT COUNT(*) c FROM photos WHERE status = 'Processing'")[0]["c"]
    check(stuck == 0, "no row should be left mid-flight after a clean cancellation")

    # Every source file must still be accounted for: either moved, or still present.
    for r in rows(case, "SELECT source_path, dest_path, status FROM photos"):
        if r["status"] in ("Completed",):
            check(Path(r["dest_path"]).exists(), f"Completed but missing at dest: {r['dest_path']}")
            check(not Path(r["source_path"]).exists(), f"Completed but source remains: {r['source_path']}")
        elif r["status"] == "Pending":
            check(Path(r["source_path"]).exists(), f"Pending but source gone: {r['source_path']}")


@test
def sigkill_during_move_is_reconciled_and_loses_nothing():
    """SIGKILL mid-move: next run reconciles state, and no photo is lost."""
    case = new_case("crash")
    count = 120
    for i in range(count):
        make_photo(case / "src" / f"p{i:03d}.jpg", f"p{i}", size=(500, 400), noise=True)

    run_engine(case)
    before = {r["sha1_hash"] for r in rows(case, "SELECT sha1_hash FROM photos")}

    proc = spawn_engine(case, "--move")
    check(wait_for_move_to_start(case), "move never started")
    proc.kill()
    proc.wait(timeout=60)

    if len(dest_files(case)) == count:
        raise Fail("SKIP: move completed before SIGKILL landed — raise the file "
                   "count or size in this test to exercise crash recovery")

    # No photo may be absent from BOTH sides at any point after a hard kill.
    missing = []
    for r in rows(case, "SELECT source_path, dest_path, status FROM photos"):
        src_there = Path(r["source_path"]).exists()
        dst_there = r["dest_path"] and Path(r["dest_path"]).exists()
        # Partials carry a unique suffix after ".organizing.partial", so match
        # by prefix; an exact-name check would silently find nothing.
        partial = r["dest_path"] and any(
            Path(r["dest_path"]).parent.glob(Path(r["dest_path"]).name + ".organizing.partial*"))
        if not (src_there or dst_there or partial):
            missing.append(r["source_path"])
    check(not missing, f"photos vanished from both source and destination after SIGKILL: {missing[:5]}")

    # The next invocation must reconcile the interrupted state.
    run_engine(case)
    stuck = rows(case, "SELECT COUNT(*) c FROM photos WHERE status = 'Processing'")[0]["c"]
    check(stuck == 0, "reconciliation left rows stuck in Processing")
    killed = rows(case, "SELECT ended_at, reconciled_by_run_id FROM runs WHERE status = 'Interrupted'")
    check(len(killed) == 1, f"the killed run should have been marked Interrupted, got {len(killed)}")
    reconciler = rows(case, "SELECT MAX(id) m FROM runs")[0]["m"]
    check(killed[0] == {"ended_at": None, "reconciled_by_run_id": reconciler},
          f"an Interrupted run must name its reconciler and claim no end time: {killed[0]}")
    leftover = list((case / "dest").rglob("*.organizing.partial*"))
    check(not leftover, f"orphaned partial files were not cleaned up: {leftover}")

    # Finish the job; everything must end up at the destination exactly once.
    run_engine(case, "--move")
    after = {r["sha1_hash"] for r in rows(case, "SELECT sha1_hash FROM photos")}
    check(before == after, "the set of known photo hashes changed across the crash")
    finished = len(dest_files(case))
    check(finished == count, f"expected {count} files at the destination, found {finished}")
    check(src_files(case) == [], f"source should be empty after completing the move: {src_files(case)}")


@test
def phash_is_computed_for_real_images():
    """pHash: a real perceptual hash is stored, not 'not_supported' or 'error'."""
    case = new_case("phash")
    make_photo(case / "src" / "a.jpg", "phash-a")
    make_photo(case / "src" / "b.jpg", "phash-b")
    run_engine(case)

    hashes = {Path(r["source_path"]).name: r["phash"]
              for r in rows(case, "SELECT source_path, phash FROM photos")}
    for name, ph in hashes.items():
        check(ph not in ("not_supported", "error", None, ""),
              f"{name}: pHash not computed ({ph!r}) — is imagehash installed?")
        check(len(ph) >= 8 and all(c in "0123456789abcdef" for c in ph.lower()),
              f"{name}: pHash does not look like a hex hash: {ph!r}")


@test
def raw_extension_routes_to_rawpy_and_fails_gracefully():
    """
    RAW: a .dng the decoder cannot read is recorded as 'error' and the file is
    still indexed — it must not raise, and must not silently fall through to
    PIL (which cannot decode RAW sensor data at all).
    """
    case = new_case("raw_route")
    make_photo(case / "src" / "normal.jpg", "normal")
    # A TIFF named .dng. LibRaw rejects it, which is exactly the failure this
    # checks: the engine should degrade to 'error' for that one file, not die.
    from PIL import Image
    import numpy as np
    arr = (np.random.rand(48, 64, 3) * 255).astype("uint8")
    Image.fromarray(arr).save(case / "src" / "broken.dng", "TIFF")

    run_engine(case)

    statuses = {Path(r["source_path"]).name: (r["status"], r["phash"])
                for r in rows(case, "SELECT source_path, status, phash FROM photos")}
    check("broken.dng" in statuses, f"the .dng was not indexed at all: {statuses}")
    status, phash = statuses["broken.dng"]
    check(status == "Pending", f"an undecodable RAW should still index, got status {status}")
    check(phash == "error",
          f"expected phash 'error' for an undecodable RAW, got {phash!r} — "
          f"'not_supported' means rawpy is missing; a real hash means it wrongly used PIL")
    check(statuses["normal.jpg"][1] not in ("error", "not_supported"),
          "the normal JPEG alongside it should still hash correctly")


@test
def real_raw_files_decode_when_supplied():
    """
    RAW decode: opt-in. Set NS_TEST_RAW_DIR to a folder of genuine RAW files
    (.cr2/.nef/.arw/.dng/.raf) to exercise the rawpy decode path for real —
    it cannot be synthesized, LibRaw rejects fabricated files.
    """
    raw_dir = os.environ.get("NS_TEST_RAW_DIR")
    if not raw_dir or not Path(raw_dir).is_dir():
        raise Fail("SKIP: set NS_TEST_RAW_DIR to a folder of real RAW files to run this")
    # Kept in step with RAW_EXTENSIONS in ns-engine.py. A filter narrower than
    # the engine's advertised set silently skips the very fixtures it is given
    # — .cr3 was missing here, so a Canon fixture would have looked like "no
    # RAW files found" rather than a decode failure.
    sources = [p for p in Path(raw_dir).iterdir()
               if p.suffix.lower() in {".raw", ".dng", ".cr2", ".cr3", ".crw", ".nef", ".nrw",
                                       ".arw", ".srf", ".sr2", ".raf", ".orf", ".rw2", ".pef",
                                       ".ptx", ".srw", ".erf", ".3fr", ".fff", ".iiq", ".mos",
                                       ".mrw", ".x3f"}]
    if not sources:
        raise Fail(f"SKIP: no RAW files found in {raw_dir}")

    case = new_case("raw_real")
    for p in sources[:5]:
        shutil.copy2(p, case / "src" / p.name)
    run_engine(case)

    for r in rows(case, "SELECT source_path, status, phash, metadata_json FROM photos"):
        name = Path(r["source_path"]).name
        check(r["phash"] not in ("error", "not_supported", None, ""),
              f"{name}: RAW pHash failed ({r['phash']!r})")
        check(r["status"] == "Pending", f"{name}: expected Pending, got {r['status']}")
        check(r["metadata_json"] and "date_taken" in r["metadata_json"],
              f"{name}: no metadata captured from the RAW file")


# 2019-06-15 12:00:00 UTC. Deliberately mid-year and mid-day: a photo filed by
# mtime is bucketed in local time, so a timestamp near midnight or New Year
# would let the container's timezone decide the folder and make these tests
# depend on where they run.
_UNDATED_MTIME = 1560600000
_UNDATED_YEAR = "2019"
# A second stamp in a DIFFERENT year, for touching a file after its first Index.
_TOUCHED_MTIME = 1690000000
_TOUCHED_YEAR = "2023"


@test
def a_photo_with_no_exif_date_lands_under_undated():
    """
    A photo the engine could not date goes to `Undated/<year>/`, not into the
    real date tree.

    Filing it by modification time puts a date on it that nobody vouched for —
    for an export that is the download date, which is how photos from the 2000s
    ended up in 2024/ and 2025/ folders on a real run. `Undated/` keeps those
    files out of the dated library and gathers them where they can be reviewed;
    the year subdivides the folder so it stays navigable at ~8% of a library,
    without the tree ever claiming to know when the photograph was taken.
    """
    case = new_case("undated_lands")
    make_photo(case / "src" / "nodate.jpg", "NO-EXIF-DATE", date=None)
    os.utime(case / "src" / "nodate.jpg", (_UNDATED_MTIME, _UNDATED_MTIME))
    run_engine(case)
    run_engine(case, "--move")

    landed = dest_files(case)
    check(landed == [f"Undated/{_UNDATED_YEAR}/nodate.jpg"],
          f"expected the undated photo under Undated/{_UNDATED_YEAR}/, destination holds {landed}")


@test
def a_photo_with_only_createdate_is_undated():
    """
    `CreateDate` is when this FILE was created — a re-export, a conversion, a
    download — not when the photograph was taken. Filing by it puts a date into
    the dated tree that nobody vouched for.

    This test exists because the fixture builder writes `DateTimeOriginal` and
    `CreateDate` together, so every other date test here passes whether or not
    the CreateDate fallback is present. Only a file carrying CreateDate alone
    can tell the difference.
    """
    case = new_case("createdate_only")
    photo = case / "src" / "createonly.jpg"
    make_photo(photo, "CREATE-ONLY", date=None)
    subprocess.run(["exiftool", "-overwrite_original",
                    "-CreateDate=2024:02:14 09:30:00", str(photo)],
                   capture_output=True, check=True)
    # After exiftool, which rewrites the file and so moves its mtime.
    os.utime(photo, (_UNDATED_MTIME, _UNDATED_MTIME))
    run_engine(case)

    r = rows(case, "SELECT dest_path, metadata_json FROM photos")[0]
    meta = json.loads(r["metadata_json"])
    check(meta.get("date_source") == "file_mtime",
          f"a photo carrying only CreateDate has no capture date, so it must fall "
          f"back to mtime; date_source was {meta.get('date_source')!r}")
    check(f"Undated/{_UNDATED_YEAR}" in r["dest_path"],
          f"expected Undated/{_UNDATED_YEAR}, projected {r['dest_path']!r}")
    # Retained as evidence, not promoted — the Undated screen shows it as a clue.
    check("CreateDate" in meta,
          "CreateDate must still reach the catalog as review evidence")


@test
def the_undated_year_is_pinned_to_the_original_index_mtime():
    """
    An undated photo is filed by the mtime recorded at its FIRST Index, not by
    whatever its mtime happens to be now.

    `photos.file_mtime` is refreshed on every rescan for change detection, so
    filing from it lets a photo drift between year folders whenever anything
    touches the file. The immutable value lives in `source_snapshots`.

    BOTH assertions below are required, because either alone passes for the
    wrong reason: if the second Index had skipped the file as unchanged,
    dest_path would be identical and the test would prove nothing. file_mtime
    moving is what shows the file was genuinely re-read.
    """
    case = new_case("undated_pinned")
    photo = case / "src" / "nodate.jpg"
    make_photo(photo, "PINNED", date=None)
    os.utime(photo, (_UNDATED_MTIME, _UNDATED_MTIME))
    run_engine(case)

    first = rows(case, "SELECT dest_path FROM photos")[0]["dest_path"]
    check(f"Undated/{_UNDATED_YEAR}" in first,
          f"first Index projected {first!r}, expected Undated/{_UNDATED_YEAR}")

    # Touch it into a different year. An mtime change is precisely what defeats
    # the unchanged-file skip, so this file is re-read rather than skipped.
    os.utime(photo, (_TOUCHED_MTIME, _TOUCHED_MTIME))
    run_engine(case)

    r = rows(case, "SELECT dest_path, file_mtime FROM photos")[0]
    check(abs(r["file_mtime"] - _TOUCHED_MTIME) < 1e-6,
          f"the file was not actually re-read (file_mtime {r['file_mtime']}), so the "
          f"year assertion below would pass without proving anything")
    check(f"Undated/{_UNDATED_YEAR}" in r["dest_path"],
          f"the Undated year drifted to {r['dest_path']!r} after the file was touched; "
          f"it must stay pinned to the original Index mtime, Undated/{_UNDATED_YEAR}")
    check(f"Undated/{_TOUCHED_YEAR}" not in r["dest_path"],
          f"filed under the touched year {_TOUCHED_YEAR} instead of the original")


@test
def a_dated_photo_still_lands_in_the_date_tree():
    """Undated filing must not disturb photos that carry a real EXIF date."""
    case = new_case("undated_dated_unaffected")
    make_photo(case / "src" / "dated.jpg", "HAS-EXIF", date="2024:02:14 09:30:00")
    os.utime(case / "src" / "dated.jpg", (_UNDATED_MTIME, _UNDATED_MTIME))
    run_engine(case)
    run_engine(case, "--move")

    landed = dest_files(case)
    check(landed == ["2024/02/14/dated.jpg"],
          f"a dated photo must ignore its mtime and use its EXIF date; destination holds {landed}")


@test
def the_undated_projection_matches_where_the_file_lands():
    """
    The destination recorded at Index must agree with where Move actually puts
    the file.

    `dest_path` is written at Index as a projection and recomputed immediately
    before the write. If only one of those two sites learned about `Undated/`,
    the catalog would advertise a location the file never occupies — and the
    staging screen, which projects from the catalog, would show the wrong
    folder for every undated photo.
    """
    case = new_case("undated_projection")
    make_photo(case / "src" / "nodate.jpg", "PROJECTION", date=None)
    os.utime(case / "src" / "nodate.jpg", (_UNDATED_MTIME, _UNDATED_MTIME))
    run_engine(case)

    projected = rows(case, "SELECT dest_path FROM photos")[0]["dest_path"]
    check(f"Undated/{_UNDATED_YEAR}" in projected,
          f"Index projected {projected!r}, which is not under Undated/{_UNDATED_YEAR}")

    run_engine(case, "--move")
    landed = dest_files(case)
    check(landed and projected.endswith(landed[0]),
          f"projection {projected!r} disagrees with where the file landed: {landed}")


@test
def date_source_records_where_the_date_came_from():
    """
    Every photo records whether its date came from EXIF or the file's mtime.

    This is the difference between a date that is timezone-proof and one that
    is not: EXIF timestamps carry no zone and are used exactly as the camera
    wrote them, while an mtime is interpreted in the container's timezone — so
    a file modified late in the evening can land in the next day's folder under
    a different TZ. Recording the source per photo is what lets the count be
    reported per run, and what the inspector reads to tell a user their
    date came from the filesystem rather than the camera.
    """
    case = new_case("datesource")
    make_photo(case / "src" / "with_exif.jpg", "e", date="2019:07:04 21:30:00")
    make_photo(case / "src" / "no_exif.jpg", "n", date=None)

    run_engine(case)

    found = {}
    for r in rows(case, "SELECT source_path, metadata_json, dest_path FROM photos"):
        found[Path(r["source_path"]).name] = (
            json.loads(r["metadata_json"]).get("date_source"), r["dest_path"]
        )

    check(found.get("with_exif.jpg", (None,))[0] == "exif",
          f"EXIF-dated photo should record date_source 'exif', got {found.get('with_exif.jpg')}")
    check(found.get("no_exif.jpg", (None,))[0] == "file_mtime",
          f"photo without an EXIF date should record 'file_mtime', got {found.get('no_exif.jpg')}")

    # The EXIF date is used verbatim, so its folder is fixed regardless of
    # the timezone this runs under.
    check("2019/07/04" in found["with_exif.jpg"][1],
          f"EXIF date should bucket to 2019/07/04 in any timezone, got {found['with_exif.jpg'][1]}")


@test
def schema_has_the_indexes_the_hot_queries_need():
    """Schema: the indexes the duplicate and status queries depend on exist and are used."""
    case = new_case("schema")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case)

    conn = db(case)
    try:
        idx = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx%'")}
        check({"idx_photos_sha1", "idx_photos_status", "idx_operations_run"} <= idx,
              f"missing expected indexes, found {idx}")
        plan = " ".join(str(x) for x in conn.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM photos WHERE sha1_hash = ?", ("x",)).fetchall())
        check("SCAN" not in plan.upper() or "INDEX" in plan.upper(),
              f"sha1 lookup is still a table scan: {plan}")
    finally:
        conn.close()


@test
def status_columns_are_constrained():
    """Schema: every status column rejects a value outside its vocabulary."""
    case = new_case("statuscheck")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case)

    # The valid statuses used to exist only as scattered string literals with
    # nothing constraining the column, so a typo matched zero rows instead of
    # raising — silent in exactly the places it matters (crash recovery, the
    # duplicate-cleanup anchor check). The web API adds a second codebase writing
    # this column, so the database has to enforce the vocabulary itself.
    conn = db(case)
    try:
        # 'Skipped' is an operation outcome, never a photo state.
        conn.execute("INSERT INTO operations (run_id, status, timestamp) VALUES (1, 'Skipped', 't')")

        for sql, params, label in (
            ("INSERT INTO photos (source_path, status) VALUES ('/typo.jpg', ?)",
             ("Complete",), "photos.status"),
            ("INSERT INTO runs (mode, started_at, status) VALUES ('INDEX', 't', ?)",
             ("Runnin",), "runs.status"),
            ("INSERT INTO operations (run_id, status, timestamp) VALUES (1, ?, 't')",
             ("copied",), "operations.status"),
        ):
            try:
                conn.execute(sql, params)
                raise Fail(f"{label} accepted a value outside its vocabulary")
            except sqlite3.IntegrityError:
                pass

        # A legal value still goes in, so the constraint is not simply
        # rejecting everything.
        conn.execute("INSERT INTO photos (source_path, status) VALUES ('/ok.jpg', 'Pending')")
        # NULL stays legal on photos: a row can exist before its scan result
        # lands.
        conn.execute("INSERT INTO photos (source_path, status) VALUES ('/null.jpg', NULL)")
    finally:
        conn.rollback()
        conn.close()


@test
def batched_scan_records_every_file():
    """Batched commits: a scan larger than one batch still persists every row."""
    case = new_case("batching")
    count = 250   # > DB_COMMIT_BATCH_SIZE
    for i in range(count):
        make_photo(case / "src" / f"f{i:03d}.jpg", f"f{i}")
    run_engine(case)
    got = rows(case, "SELECT COUNT(*) c FROM photos")[0]["c"]
    check(got == count, f"expected {count} rows after a multi-batch scan, got {got}")
    ops = rows(case, "SELECT COUNT(*) c FROM operations")[0]["c"]
    check(ops >= count, f"expected an audit row per file, got {ops}")


# ------------------------------------------------------------ content safety
#
# Each test below covers a path that could delete the only copy of a photo,
# or overwrite an unrelated file, while reporting success. The first three
# drive the engine as a subprocess like the rest of the suite. The last three
# import it in-process: the windows they cover sit BETWEEN two statements of
# one function — after verification, before the source is deleted — and a
# subprocess offers no way to act inside them.

def _run_fixture_move(engine, args, db_path, destination, run_id):
    """Fault-injection calls still need a real parent run with FK checks enabled."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO runs(id,mode,started_at,status) VALUES(?, 'MOVE', 'test', 'Running')", (run_id,))
    return engine._run_move_or_copy(args, db_path, destination, run_id)


def _load_engine():
    """Imports ns-engine.py in-process, for the fault-injection tests below."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ns_engine_under_test", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # With no handler configured, engine warnings reach Python's last-resort
    # stderr handler and interleave with the test report. These tests assert
    # on return values and files, never on log text.
    import logging
    module.logger.addHandler(logging.NullHandler())
    module.logger.propagate = False
    return module


def _last_run_failures(case):
    return rows(case, "SELECT error_message FROM operations "
                      "WHERE status = 'Failed' AND run_id = (SELECT MAX(id) FROM runs)")


@test
def overlapping_roots_are_refused():
    """Source and destination that are one folder, nested, or aliased by symlink are refused up front."""
    # The case that destroys data: a library already in YYYY/MM/DD layout,
    # moved onto itself. Every file's computed destination IS its own path,
    # the already-present check hashes the file against itself and matches,
    # and --move deletes the only copy — with exit 0 and a Completed run.
    case = new_case("overlap_same")
    photo = case / "src" / "2024" / "02" / "14" / "IMG_0001.jpg"
    make_photo(photo, "only-copy")
    out = engine_output(run_engine(case, "--move", "--dest", case / "src", expect_rc=1))
    check(photo.exists(),
          "the only copy of a photo was deleted when source and destination were one folder")
    check("overlap" in out.lower(), f"the refusal did not say why; log said:\n{out}")

    for label, src, dst in (
        ("dest_inside_source", "src", "src/organized"),
        ("source_inside_dest", "dest/inbox", "dest"),
        ("dest_symlinked_to_source", "src", "link-to-src"),
    ):
        case = new_case("overlap_" + label)
        make_photo(case / src / "IMG_0002.jpg", label)
        if label == "dest_symlinked_to_source":
            (case / "link-to-src").symlink_to(case / "src", target_is_directory=True)
        before = sorted(p.relative_to(case).as_posix() for p in case.rglob("*.jpg"))
        run_engine(case, "--move", "--source", case / src, "--dest", case / dst, expect_rc=1)
        after = sorted(p.relative_to(case).as_posix() for p in case.rglob("*.jpg"))
        check(before == after, f"{label}: files changed despite overlapping roots: {before} -> {after}")


@test
def a_source_is_never_deleted_as_its_own_copy():
    """If the 'verified copy' is the source file itself, the source is kept and the refusal recorded."""
    # Startup refusal only sees overlap a path comparison can detect. A second
    # mount of the same storage is invisible to that, and still produces a
    # destination "copy" that is really the source. A hard link reproduces
    # the shape exactly — two names, one file — without bind mounts in CI.

    # 1. The move loop's already-present branch.
    case = new_case("alias_present")
    src = case / "src" / "a.jpg"
    make_photo(src, "alias")
    run_engine(case)
    dest = Path(rows(case, "SELECT dest_path FROM photos")[0]["dest_path"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.link(src, dest)
    run_engine(case, "--move")
    check(src.exists(), "the already-present branch deleted a source whose 'copy' was the same file")
    failures = _last_run_failures(case)
    check(failures and "same file" in failures[0]["error_message"],
          f"the refusal was not recorded as a failed operation: {failures}")

    # 2. Duplicate cleanup.
    case = new_case("alias_duplicate")
    make_photo(case / "src" / "a.jpg", "twin")
    make_photo(case / "src" / "b.jpg", "twin")
    run_engine(case)
    anchor = rows(case, "SELECT id FROM photos WHERE status = 'Pending'")[0]["id"]
    duplicate = rows(case, "SELECT id, source_path FROM photos WHERE status = 'Duplicate'")[0]
    run_engine(case, "--move", "--file-ids", anchor)
    delivered = Path(rows(case, "SELECT dest_path FROM photos WHERE id = ?", (anchor,))[0]["dest_path"])
    dup_src = Path(duplicate["source_path"])
    delivered.unlink()
    os.link(dup_src, delivered)  # the delivered "copy" is now the duplicate's own file
    run_engine(case, "--move", "--file-ids", duplicate["id"])
    check(dup_src.exists(), "duplicate cleanup deleted a source whose 'copy' was the same file")
    failures = _last_run_failures(case)
    check(failures and "same file" in failures[0]["error_message"],
          f"the refusal was not recorded as a failed operation: {failures}")


@test
def a_planted_partial_is_never_followed_or_overwritten():
    """Staging never writes through a file or symlink already sitting at a predictable partial name."""
    case = new_case("partial_planted")
    make_photo(case / "src" / "a.jpg", "payload")
    run_engine(case)
    dest = Path(rows(case, "SELECT dest_path FROM photos")[0]["dest_path"])
    victim = dest.parent / "unrelated.jpg"
    make_photo(victim, "victim")
    original = victim.read_bytes()
    Path(str(dest) + ".organizing.partial").symlink_to(victim)
    run_engine(case, "--copy")
    check(victim.read_bytes() == original,
          "the copy wrote through a planted partial-name symlink into an unrelated file")
    check(dest.is_file() and not dest.is_symlink()
          and dest.read_bytes() == (case / "src" / "a.jpg").read_bytes(),
          "the copy itself did not land intact")


@test
def publish_falls_back_only_when_hardlinks_are_unsupported():
    """A link failure other than 'not supported' fails the publish instead of falling back to rename()."""
    import errno
    engine = _load_engine()
    case = new_case("publish_fallback")
    real_link = os.link

    def failing_link(code):
        def link(*args, **kwargs):
            raise OSError(code, os.strerror(code))
        return link

    try:
        # An I/O error says nothing about hard-link support. Falling back would
        # trade a no-overwrite primitive for rename(), which replaces silently.
        partial, dest = case / "eio.partial", case / "eio.jpg"
        partial.write_bytes(b"staged")
        os.link = failing_link(errno.EIO)
        try:
            engine._finalize_partial(partial, dest)
            raise Fail("an EIO from os.link was treated as 'hard links unsupported'")
        except OSError:
            pass
        check(not dest.exists(), "the publish fell back to rename() after an unrelated link error")

        # Genuinely unsupported (EPERM, as on FAT/exFAT): the fallback still publishes...
        partial, dest = case / "eperm.partial", case / "eperm.jpg"
        partial.write_bytes(b"staged")
        os.link = failing_link(errno.EPERM)
        engine._finalize_partial(partial, dest)
        check(dest.read_bytes() == b"staged", "the no-hard-link fallback no longer publishes")

        # ...and still refuses to replace an existing file.
        partial, dest = case / "taken.partial", case / "taken.jpg"
        partial.write_bytes(b"staged")
        dest.write_bytes(b"already here")
        try:
            engine._finalize_partial(partial, dest)
            raise Fail("the no-hard-link fallback replaced an existing destination file")
        except engine.DestinationExistsError:
            pass
        check(dest.read_bytes() == b"already here", "an existing destination file was overwritten")
    finally:
        os.link = real_link


@test
def a_source_edited_after_verification_is_kept():
    """A source that changes between verification and deletion is kept, and the move reports failure."""
    engine = _load_engine()
    case = new_case("edited_mid_move")
    src = case / "src" / "a.jpg"
    make_photo(src, "before")
    dest = case / "dest" / "a.jpg"
    real_finalize = engine._finalize_partial

    def finalize_then_edit(partial, final):
        real_finalize(partial, final)
        with open(src, "ab") as f:
            f.write(b"edited after verification")

    engine._finalize_partial = finalize_then_edit
    ok, message = engine.copy_verify_delete(str(src), str(dest), delete_source=True)
    check(src.exists(), "a source edited after verification was deleted, taking its new content with it")
    check(src.read_bytes().endswith(b"edited after verification"),
          "the source's new content was not preserved")
    check(not ok and message, f"the move reported success although the source changed: {ok!r} {message!r}")


@test
def durability_barriers_precede_source_deletion():
    """The copy's bytes and its directory entry are fsynced before the source is deleted."""
    # Verification reads the copy back, but that read can be served entirely
    # from page cache. On a network source the delete is committed by the
    # server immediately, so a local power loss before the copy reaches disk
    # would leave no copy anywhere. Only an fsync ordering closes that.
    engine = _load_engine()
    case = new_case("durability")
    src = case / "src" / "a.jpg"
    make_photo(src, "durable")
    dest = case / "dest" / "a.jpg"
    events = []
    real_fsync, real_unlink = os.fsync, Path.unlink

    def recording_fsync(fd):
        events.append(("fsync", os.path.realpath(os.readlink(f"/proc/self/fd/{fd}"))))
        return real_fsync(fd)

    def recording_unlink(self, *args, **kwargs):
        events.append(("unlink", os.path.realpath(self)))
        return real_unlink(self, *args, **kwargs)

    source_real = os.path.realpath(src)
    os.fsync, Path.unlink = recording_fsync, recording_unlink
    try:
        ok, message = engine.copy_verify_delete(str(src), str(dest), delete_source=True)
    finally:
        os.fsync, Path.unlink = real_fsync, real_unlink
    check(ok, f"the move itself failed: {message}")

    deleted_at = next((i for i, e in enumerate(events) if e == ("unlink", source_real)), None)
    check(deleted_at is not None, f"the source was never deleted: {events}")
    before = events[:deleted_at]
    dest_real = os.path.realpath(dest)
    data_synced = any(
        kind == "fsync" and (path == dest_real
                             or os.path.basename(path).startswith(dest.name + ".organizing.partial"))
        for kind, path in before)
    check(data_synced, f"the copy's bytes were not fsynced before the source was deleted: {events}")
    check(("fsync", os.path.realpath(dest.parent)) in before,
          f"the destination directory was not fsynced before the source was deleted: {events}")


# ------------------------------------------------------- selection and plan
#
# A run must act on exactly what it was asked to act on, and a photo's
# classification must follow the catalog as it is now, not as it was when a
# file was last read.

@test
def source_subdir_is_case_sensitive():
    """--source-subdir: 'Album' does not also select 'album' on case-sensitive storage."""
    # SQLite's LIKE ignores ASCII case, so escaping wildcards fixed only half
    # of the prefix match: Album and album were still treated as one folder.
    case = new_case("subdircase")
    make_photo(case / "src" / "Album" / "a.jpg", "A")
    make_photo(case / "src" / "album" / "b.jpg", "B")
    run_engine(case)
    run_engine(case, "--move", "--source-subdir", "Album")
    check(src_files(case) == ["album/b.jpg"],
          f"selecting 'Album' also moved files from 'album': source holds {src_files(case)}")


@test
def full_runs_stay_inside_the_source_root():
    """Without targeting, Move acts only on rows under this run's --source, not the whole catalog."""
    # One --base can hold rows from several source roots. A full run swept
    # every Pending row in the catalog, so moving root B also moved root A's
    # photos — and duplicate cleanup reached into root A too.
    case = new_case("two_roots")
    make_photo(case / "src" / "a.jpg", "ROOT-A")
    make_photo(case / "src" / "a_twin.jpg", "ROOT-A")
    make_photo(case / "srcB" / "b.jpg", "ROOT-B")
    run_engine(case)
    run_engine(case, "--move", "--source", case / "srcB")
    check(src_files(case) == ["a.jpg", "a_twin.jpg"],
          f"a move of root B acted on root A: root A now holds {src_files(case)}")
    check(not (case / "srcB" / "b.jpg").exists(), "root B's own photo was not moved")


@test
def destination_follows_the_current_dest():
    """A destination given at Move/Copy time wins over the one the file was indexed against."""
    # The unchanged-file skip reuses a file's catalog row, which carried a
    # destination computed against the --dest current at Index time. Copying
    # to a new destination wrote into the OLD one, after checking free space
    # on the new one.
    case = new_case("dest_changed")
    make_photo(case / "src" / "a.jpg", "A")
    run_engine(case)
    run_engine(case, "--copy", "--dest", case / "dest2")
    check(dest_files(case) == [], f"the copy wrote into the Index-time destination: {dest_files(case)}")
    check((case / "dest2" / "2024" / "02" / "14" / "a.jpg").is_file(),
          "the copy did not land in the destination given to this run")


@test
def copy_then_move_completes_the_move():
    """--copy, then --move of the same unchanged file, deletes the source against the existing copy."""
    # The unchanged-file skip froze the row at Copied, and --move acted only
    # on Pending rows, so a verified copy could never be followed by a move.
    case = new_case("copy_then_move")
    make_photo(case / "src" / "a.jpg", "A")
    run_engine(case, "--copy")
    run_engine(case, "--move")
    check(src_files(case) == [], f"the move left the source behind after a copy: {src_files(case)}")
    check(status_of(case, "a.jpg") == "Completed",
          f"expected Completed, got {status_of(case, 'a.jpg')}")
    check(dest_files(case) == ["2024/02/14/a.jpg"],
          f"expected the one existing copy, not a second: {dest_files(case)}")


@test
def a_duplicate_selected_alone_gets_an_outcome():
    """Selecting only a duplicate records why nothing was written, instead of succeeding silently."""
    # Duplicates are never written — their original carries the content — so a
    # selection holding only the duplicate did nothing, exited 0 and recorded
    # no operation at all. The web UI would have shown that job as a success.
    case = new_case("dup_alone")
    make_photo(case / "src" / "a.jpg", "TWIN")
    make_photo(case / "src" / "b.jpg", "TWIN")
    run_engine(case)
    anchor = rows(case, "SELECT id FROM photos WHERE status = 'Pending'")[0]["id"]
    dup = rows(case, "SELECT id FROM photos WHERE status = 'Duplicate'")[0]["id"]
    for mode in ("--copy", "--move"):
        run_engine(case, mode, "--file-ids", dup)
        outcome = rows(case, "SELECT status, error_message FROM operations "
                             "WHERE photo_id = ? AND run_id = (SELECT MAX(id) FROM runs)", (dup,))
        check([o["status"] for o in outcome] == ["Skipped"],
              f"{mode}: expected one Skipped outcome for the duplicate, got {outcome}")
        check(f"#{anchor}" in (outcome[0]["error_message"] or ""),
              f"{mode}: the outcome did not name the original it duplicates: {outcome}")
    check(len(src_files(case)) == 2 and dest_files(case) == [],
          "a duplicate-only selection moved or copied something")


@test
def an_edited_original_frees_its_duplicate():
    """When a duplicate's original changes content, the duplicate is delivered in its own right."""
    # The unchanged-file skip left the twin frozen as Duplicate while its
    # original's content changed underneath it. The twin then had no original
    # anywhere, so it was never delivered — only warned about.
    case = new_case("edited_anchor")
    make_photo(case / "src" / "a.jpg", "TWIN")
    make_photo(case / "src" / "b.jpg", "TWIN")
    run_engine(case)
    anchor = Path(rows(case, "SELECT source_path FROM photos WHERE status = 'Pending'")[0]["source_path"])
    time.sleep(1.1)  # a visibly different mtime at any filesystem's resolution
    make_photo(anchor, "EDITED")
    run_engine(case, "--move")
    check(src_files(case) == [], f"a photo was left behind in the source: {src_files(case)}")
    check(len(dest_files(case)) == 2, f"expected both distinct photos delivered, got {dest_files(case)}")


@test
def duplicate_removal_keeps_the_copy_that_verified():
    """After duplicate cleanup, the row points at the copy that actually matched, not an arbitrary one."""
    # Cleanup verified the second of two recorded copies and stored it; the
    # repoint step that followed then overwrote it with the first delivered
    # row it found — the stale one.
    case = new_case("repoint_verified")
    make_photo(case / "src" / "a.jpg", "TWIN")
    make_photo(case / "src" / "b.jpg", "TWIN")
    run_engine(case)
    anchor = rows(case, "SELECT * FROM photos WHERE status = 'Pending'")[0]
    dup = rows(case, "SELECT * FROM photos WHERE status = 'Duplicate'")[0]
    run_engine(case, "--move", "--file-ids", anchor["id"])
    stale = Path(rows(case, "SELECT dest_path FROM photos WHERE id = ?", (anchor["id"],))[0]["dest_path"])
    good = stale.parent / "second-copy.jpg"
    shutil.copyfile(dup["source_path"], good)
    conn = db(case)
    try:
        # A second delivered copy of the same content, recorded after the
        # anchor, so a "first delivered row" lookup lands on the anchor's copy.
        conn.execute("INSERT INTO photos (source_path, dest_path, sha1_hash, status) "
                     "VALUES (?, ?, ?, 'Completed')", ("/elsewhere/second.jpg", str(good), dup["sha1_hash"]))
        conn.commit()
    finally:
        conn.close()
    stale.write_bytes(stale.read_bytes() + b"now stale")
    run_engine(case, "--move", "--file-ids", dup["id"])
    check(not Path(dup["source_path"]).exists(), "the duplicate was not removed against the matching copy")
    final = rows(case, "SELECT status, dest_path FROM photos WHERE id = ?", (dup["id"],))[0]
    check(final["status"] == "Removed_Duplicate" and final["dest_path"] == str(good),
          f"the row should name the copy that verified ({good}), got {final}")


@test
def operations_carry_the_content_hash():
    """Every audit row for a hashed file records that hash, so history can outlive a catalog rebuild."""
    case = new_case("op_hash")
    make_photo(case / "src" / "a.jpg", "A")
    run_engine(case, "--move")
    photo = rows(case, "SELECT id, sha1_hash FROM photos")[0]
    ops = rows(case, "SELECT status, sha1_hash FROM operations WHERE photo_id = ?", (photo["id"],))
    check(len(ops) >= 2, f"expected a scan and a move operation, got {ops}")
    check(all(o["sha1_hash"] == photo["sha1_hash"] for o in ops),
          f"operations did not record the file's content hash: {ops}")
    indexes = {r["name"] for r in rows(case, "SELECT name FROM sqlite_master WHERE type = 'index'")}
    check("idx_operations_sha1" in indexes, f"content-history lookups are unindexed: {indexes}")


@test
def transfer_lines_name_the_source_path():
    """Per-file transfer lines identify a file by its path under the source, not only its name."""
    # One filename can exist in dozens of folders; a bare name does not say
    # which file was copied.
    case = new_case("log_relpath")
    make_photo(case / "src" / "trip" / "IMG_0001.jpg", "A")
    out = engine_output(run_engine(case, "--copy"))
    check("trip/IMG_0001.jpg ->" in out, f"the transfer line did not name the path under the source:\n{out}")


# ------------------------------------------------------- truthful outcomes
#
# Every selected file, every failure and every interruption must leave a
# durable record, and a run must not report success it did not achieve.

@test
def a_lost_catalog_write_fails_the_run():
    """If scan results cannot be recorded, the run fails and no file is moved or copied."""
    # The writer logged a rejected row and carried on, so a run whose catalog
    # writes were refused still reported Completed, exited 0 — and then moved
    # or copied files against a catalog it had failed to update.
    case = new_case("writer_failure")
    make_photo(case / "src" / "one.jpg", "ONE")
    run_engine(case)
    conn = db(case)
    try:
        conn.execute("CREATE TRIGGER reject BEFORE INSERT ON photos "
                     "BEGIN SELECT RAISE(ABORT, 'injected'); END;")
        conn.commit()
    finally:
        conn.close()
    make_photo(case / "src" / "two.jpg", "TWO")
    out = engine_output(run_engine(case, "--copy", expect_rc=1))
    run = rows(case, "SELECT status FROM runs ORDER BY id DESC LIMIT 1")[0]
    check(run["status"] == "Failed", f"the run should be Failed, got {run['status']}")
    check(dest_files(case) == [],
          f"files were copied although the catalog could not be updated: {dest_files(case)}")
    check("could not be recorded" in out, f"the failure was not explained:\n{out}")


@test
def an_unreadable_folder_is_recorded_not_just_logged():
    """A folder the scan cannot read becomes a recorded failure for the run, not only a log line."""
    if os.geteuid() == 0:
        raise Fail("SKIP: running as root, permission checks are bypassed")
    case = new_case("unreadable_dir")
    make_photo(case / "src" / "ok.jpg", "OK")
    locked = case / "src" / "locked"
    make_photo(locked / "inside.jpg", "INSIDE")
    locked.chmod(0o000)
    try:
        run_engine(case)
    finally:
        locked.chmod(0o755)
    failures = rows(case, "SELECT photo_id, source_path, error_message FROM operations "
                          "WHERE status = 'Failed'")
    check(any(f["photo_id"] is None and f["source_path"].endswith("/src/locked") for f in failures),
          f"the unreadable folder left no recorded failure: {failures}")


@test
def a_vanished_original_frees_its_duplicate():
    """A full Index notices a catalogued file that is gone and stops treating it as an original."""
    # A photo deleted outside the engine kept its row Pending forever, because
    # a full Index only updates the files it finds. That row went on standing
    # as the original of its duplicate group, so the duplicate was never
    # delivered — exactly what a misplaced, later-deleted test copy did to a
    # real library.
    case = new_case("vanished_anchor")
    make_photo(case / "src" / "a.jpg", "TWIN")
    make_photo(case / "src" / "b.jpg", "TWIN")
    run_engine(case)
    anchor = rows(case, "SELECT id, source_path FROM photos WHERE status = 'Pending'")[0]
    Path(anchor["source_path"]).unlink()
    run_engine(case, "--move")
    check(src_files(case) == [], f"the surviving duplicate was not delivered: {src_files(case)}")
    check(len(dest_files(case)) == 1, f"expected the one photo delivered, got {dest_files(case)}")
    gone = rows(case, "SELECT status FROM photos WHERE id = ?", (anchor["id"],))[0]
    check(gone["status"] == "Failed", f"the vanished file's row should be Failed, got {gone['status']}")


@test
def an_index_that_finds_nothing_does_not_condemn_the_catalog():
    """
    A full Index that discovers no files must not conclude every catalogued
    file is gone.

    mark_vanished_sources ran unconditionally right after discovery, so an
    Index over a mount point that exists but is empty — which is exactly what
    an unmounted share looks like — marked every Pending/Duplicate row under
    that root Failed, warned about that, and only afterwards printed the
    message naming the source mount. Failed rows leave their duplicate group,
    so a copy in another archive is silently promoted to anchor meanwhile.

    Refusing is the safe direction: rows keep the state they already held, and
    the refusal is RECORDED as a run-level operation rather than only logged,
    because the Error Center reads operations and cannot see a log line.

    Note the sibling test above deletes one file of two, so discovery still
    finds one and this guard leaves that case alone — the guard turns on
    finding *nothing*, not on finding less.
    """
    case = new_case("empty_root_sweep")
    make_photo(case / "src" / "a.jpg", "one")
    make_photo(case / "src" / "b.jpg", "two")
    run_engine(case)
    before = {r["id"]: r["status"] for r in rows(case, "SELECT id, status FROM photos")}
    check(sorted(before.values()) == ["Pending", "Pending"],
          f"expected two Pending rows before the empty run, got {before}")

    # The directory survives; only its contents go. An unmounted share leaves
    # precisely this shape behind.
    for leftover in (case / "src").iterdir():
        leftover.unlink()
    check(src_files(case) == [], "the source should be empty for this run")

    run_engine(case)

    after = {r["id"]: r["status"] for r in rows(case, "SELECT id, status FROM photos")}
    check(after == before,
          f"an Index that found nothing changed catalogued rows: {before} -> {after}")

    refused = rows(case, "SELECT error_message FROM operations "
                         "WHERE status = 'Failed' AND photo_id IS NULL "
                         "AND run_id = (SELECT MAX(id) FROM runs)")
    check(refused, "the refused sweep was not recorded as a run-level operation")


@test
def cancelling_stops_duplicate_cleanup():
    """Cancel during duplicate cleanup lets the current file finish and leaves the rest untouched."""
    engine = _load_engine()
    case = new_case("cancel_cleanup")
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        make_photo(case / "src" / name, "TRIPLET")
    run_engine(case)
    anchor = rows(case, "SELECT id FROM photos WHERE status = 'Pending'")[0]["id"]
    run_engine(case, "--move", "--file-ids", anchor)
    real_remove = engine._remove_verified_source

    def remove_then_cancel(*args, **kwargs):
        real_remove(*args, **kwargs)
        engine.cancel_requested.set()

    engine._remove_verified_source = remove_then_cancel
    args = argparse.Namespace(move=True, copy=False, source=str(case / "src"),
                              source_subdir=None, file_ids=None)
    outcome = _run_fixture_move(engine, args, case / "appdata" / "db" / "ns_sqlite.db",
                                       case / "dest", 999)
    check(outcome == "Cancelled", f"cleanup ignored the cancellation and returned {outcome}")
    check(len(src_files(case)) == 1,
          f"expected one duplicate kept after cancelling, source holds {src_files(case)}")
    cancelled = rows(case, "SELECT COUNT(*) AS c FROM operations "
                           "WHERE run_id = 999 AND status = 'Cancelled'")[0]["c"]
    check(cancelled == 1, f"the unstarted duplicate was not recorded as Cancelled ({cancelled})")


@test
def cancelling_the_primary_loop_still_accounts_for_duplicates():
    """
    Every photo in a selection gets an outcome, including when the cancellation
    lands in the FIRST phase rather than the second.

    A Move or Copy runs two passes over one selection: the primaries, then the
    duplicates whose content those primaries carry. Cancelling in the primary
    loop records `Cancelled` for the primaries it never reached — and then the
    same `was_cancelled` flag skips the duplicate pass entirely, so the
    duplicates in scope are never visited and nothing is written about them at
    all. Not `Cancelled`, not anything.

    `cancelling_stops_duplicate_cleanup` covers the other branch, where the
    cancellation arrives DURING the duplicate pass and each remaining duplicate
    is correctly recorded. That passing test is why this hole looked covered.

    Nothing is at risk here — no file is deleted and no source is lost. What
    breaks is the promise the code states in its own comment: that a selection
    holding duplicates cannot finish having recorded nothing about them. The web UI
    derives a job's verdict from these rows, so a missing row is a photo the UI
    cannot account for.
    """
    def cancel_after_first_primary(mode):
        engine = _load_engine()
        case = new_case(f"cancel_primary_{mode}")
        # Two contents inside the folder this run is scoped to, so the
        # selection holds two primaries and one duplicate. The fourth file
        # sits outside that folder — catalogued but never selected — which is
        # what proves the reconciliation honours the run's scope instead of
        # sweeping the whole catalog into an outcome nobody asked for.
        make_photo(case / "src" / "in" / "a.jpg", "CONTENT-ONE")
        make_photo(case / "src" / "in" / "b.jpg", "CONTENT-ONE")
        make_photo(case / "src" / "in" / "c.jpg", "CONTENT-TWO")
        make_photo(case / "src" / "out" / "d.jpg", "CONTENT-THREE")
        run_engine(case)

        catalog = rows(case, "SELECT id, source_path, status FROM photos")
        selected = [r["id"] for r in catalog if "/in/" in r["source_path"]]
        unselected = [r["id"] for r in catalog if "/out/" in r["source_path"]]
        duplicates = [r["id"] for r in catalog
                      if r["status"] == "Duplicate" and "/in/" in r["source_path"]]
        check(len(selected) == 3 and len(unselected) == 1 and len(duplicates) == 1,
              f"{mode}: fixture wrong — selected={selected}, unselected={unselected}, "
              f"duplicates={duplicates}")

        real_copy = engine.copy_verify_delete

        def copy_then_cancel(*a, **kw):
            result = real_copy(*a, **kw)
            engine.cancel_requested.set()
            return result

        engine.copy_verify_delete = copy_then_cancel
        args = argparse.Namespace(move=(mode == "move"), copy=(mode == "copy"),
                                  source=str(case / "src"), source_subdir="in", file_ids=None)
        try:
            outcome = _run_fixture_move(engine,
                args, case / "appdata" / "db" / "ns_sqlite.db", case / "dest",
                _IN_PROCESS_RUN_ID)
        finally:
            engine.copy_verify_delete = real_copy
            # Module-level Event on a freshly imported module: clear it anyway,
            # so a leak can never hand a later in-process test a cancelled run.
            engine.cancel_requested.clear()

        check(outcome == "Cancelled", f"{mode}: expected Cancelled, got {outcome}")

        # Not DISTINCT: counting repeats is the point of the second check
        # below, and DISTINCT would hide exactly what it looks for.
        logged = [r["photo_id"] for r in rows(
            case, "SELECT photo_id FROM operations WHERE run_id = ? AND photo_id IS NOT NULL",
            (_IN_PROCESS_RUN_ID,))]
        recorded = set(logged)

        missing = [i for i in selected if i not in recorded]
        check(not missing,
              f"{mode}: {len(missing)} selected photo(s) finished the run with no recorded "
              f"outcome at all (ids {missing}); duplicates={duplicates}, recorded={sorted(recorded)}")

        # Reconciling must not invent outcomes for photos the run never
        # selected. The net is bound by the same predicate as the loops, and
        # this is what holds it to that.
        strays = sorted(i for i in recorded if i not in selected)
        check(not strays,
              f"{mode}: recorded an outcome for {len(strays)} photo(s) outside this run's scope "
              f"(ids {strays}); the selection was {selected}, outside it {unselected}")

        # One outcome per photo per run. A net that re-recorded what a loop had
        # already logged would leave the UI two contradictory answers for one
        # photo and no way to tell which happened.
        doubled = sorted({i for i in logged if logged.count(i) > 1})
        check(not doubled,
              f"{mode}: {len(doubled)} photo(s) ended a single run with more than one outcome "
              f"(ids {doubled})")

        # The point is accounting, not destruction: nothing may be deleted by a
        # run that was cancelled before it reached the duplicate pass. Move
        # transfers exactly one primary before cancelling; Copy deletes nothing
        # at all, so three of the four files survive either way.
        check(len(src_files(case)) >= 3,
              f"{mode}: a cancelled run removed more sources than it should: {src_files(case)}")

    cancel_after_first_primary("move")
    cancel_after_first_primary("copy")


@test
def cancelling_accounts_for_a_file_an_earlier_run_delivered():
    """
    A --copy selection holding a file an EARLIER run already delivered still
    records an outcome for it when this run is cancelled.

    Nothing is copied for such a file — its content is already at the
    destination — so the run reports it as `Skipped`, naming where it went.
    That reporting sits inside the same `not was_cancelled` gate as the
    duplicate pass, so a cancellation during the primary transfers drops it
    too, and a photo the user explicitly selected ends the job with no row at
    all. `a_second_copy_of_a_delivered_photo_records_the_outcome` covers the
    same selection when the run is allowed to finish.

    Two pending primaries, deliberately. The cancellation flag is only read at
    the TOP of a loop iteration, so with a single primary the loop copies it,
    sets the event, and exits without ever re-entering — the flag stays false,
    the blocks below run normally, and the defect this covers never fires.
    """
    engine = _load_engine()
    case = new_case("cancel_delivered")
    make_photo(case / "src" / "a.jpg", "DELIVERED-ONE")
    make_photo(case / "src" / "b.jpg", "DELIVERED-ONE")   # duplicate of a
    make_photo(case / "src" / "c.jpg", "PENDING-TWO")
    make_photo(case / "src" / "e.jpg", "PENDING-THREE")
    run_engine(case)

    anchor = rows(case, "SELECT id FROM photos WHERE status = 'Pending' ORDER BY id")[0]["id"]
    run_engine(case, "--copy", "--file-ids", anchor)
    delivered = rows(case, "SELECT id FROM photos WHERE status = 'Copied'")
    check(len(delivered) == 1, f"setup: expected one delivered photo, got {delivered}")

    real_copy = engine.copy_verify_delete

    def copy_then_cancel(*a, **kw):
        result = real_copy(*a, **kw)
        engine.cancel_requested.set()
        return result

    engine.copy_verify_delete = copy_then_cancel
    args = argparse.Namespace(move=False, copy=True, source=str(case / "src"),
                              source_subdir=None, file_ids=None)
    try:
        outcome = _run_fixture_move(engine,
            args, case / "appdata" / "db" / "ns_sqlite.db", case / "dest",
            _IN_PROCESS_RUN_ID)
    finally:
        engine.copy_verify_delete = real_copy
        engine.cancel_requested.clear()

    check(outcome == "Cancelled", f"expected Cancelled, got {outcome}")

    # Full scope, so every catalogued photo was selected: the delivered file,
    # its duplicate, and the two primaries.
    everything = [r["id"] for r in rows(case, "SELECT id FROM photos")]
    recorded = {r["photo_id"] for r in rows(
        case, "SELECT DISTINCT photo_id FROM operations "
              "WHERE run_id = ? AND photo_id IS NOT NULL",
        (_IN_PROCESS_RUN_ID,))}
    missing = [i for i in everything if i not in recorded]
    check(not missing,
          f"{len(missing)} selected photo(s) ended the cancelled run with no outcome "
          f"(ids {missing}); the already-delivered file and its duplicate are the ones "
          f"the skipped blocks would have recorded")


@test
def an_interrupted_delete_is_recovered_on_the_next_run():
    """A crash between deleting a source and recording it is reconciled truthfully by the next run."""
    # The copy path marks a row Processing before touching the filesystem, but
    # the already-present path and duplicate cleanup deleted first and
    # recorded after. A crash in between left the source gone and the row
    # claiming otherwise, with no operation saying what had happened.
    engine = _load_engine()
    real_remove = engine._remove_verified_source

    def remove_then_die(*args, **kwargs):
        real_remove(*args, **kwargs)
        raise KeyboardInterrupt("simulated crash after the source was deleted")

    def crash_during_move(case):
        engine._remove_verified_source = remove_then_die
        args = argparse.Namespace(move=True, copy=False, source=str(case / "src"),
                                  source_subdir=None, file_ids=None)
        try:
            _run_fixture_move(engine, args, case / "appdata" / "db" / "ns_sqlite.db", case / "dest", 999)
            raise Fail("the simulated crash did not happen")
        except KeyboardInterrupt:
            pass
        finally:
            engine._remove_verified_source = real_remove

    # 1. Already present: a --copy delivered the file, so --move only deletes.
    case = new_case("crash_after_unlink")
    make_photo(case / "src" / "a.jpg", "A")
    run_engine(case, "--copy")
    crash_during_move(case)
    run_engine(case)
    check(status_of(case, "a.jpg") == "Completed",
          f"expected Completed after recovery, got {status_of(case, 'a.jpg')}")
    recovered = rows(case, "SELECT error_message FROM operations WHERE status = 'Completed' "
                           "AND run_id = (SELECT MAX(id) FROM runs)")
    check(recovered and "interrupted" in (recovered[0]["error_message"] or ""),
          f"the recovery was not recorded by the run that performed it: {recovered}")

    # 2. Duplicate cleanup.
    case = new_case("crash_after_dup_unlink")
    make_photo(case / "src" / "a.jpg", "TWIN")
    make_photo(case / "src" / "b.jpg", "TWIN")
    run_engine(case)
    anchor = rows(case, "SELECT id FROM photos WHERE status = 'Pending'")[0]["id"]
    dup = rows(case, "SELECT id FROM photos WHERE status = 'Duplicate'")[0]["id"]
    run_engine(case, "--move", "--file-ids", anchor)
    crash_during_move(case)
    run_engine(case)
    final = rows(case, "SELECT status FROM photos WHERE id = ?", (dup,))[0]["status"]
    check(final == "Removed_Duplicate", f"expected Removed_Duplicate after recovery, got {final}")


@test
def an_interrupted_move_leaving_both_copies_keeps_the_source():
    """
    A crash AFTER the destination is published but BEFORE the source is deleted
    leaves two copies of one photo. Recovery must establish that, keep the
    source, record the published destination as its own identity, and mark the
    original Move incomplete — never claim it succeeded and never delete.

    The interruption has to be a BaseException: copy_verify_delete catches
    Exception and turns it into a recorded Failed with the source kept, which
    is a clean refusal rather than an interrupted run. Only an uncatchable
    interruption leaves the row Processing, which is the state recovery exists
    to settle.
    """
    engine = _load_engine()
    real_remove = engine._remove_verified_source

    def die_after_publish(*args, **kwargs):
        raise KeyboardInterrupt("simulated crash after publication, before source removal")

    case = new_case("interrupted_move_both_copies")
    src = case / "src" / "a.jpg"
    make_photo(src, "BOTHCOPIES")
    run_engine(case)

    engine._remove_verified_source = die_after_publish
    args = argparse.Namespace(move=True, copy=False, source=str(case / "src"),
                              source_subdir=None, file_ids=None)
    try:
        _run_fixture_move(engine, args, case / "appdata" / "db" / "ns_sqlite.db",
                          case / "dest", 999)
        raise Fail("the simulated crash did not happen")
    except KeyboardInterrupt:
        pass
    finally:
        engine._remove_verified_source = real_remove

    check(src.exists(), "premise: the source must survive a crash before removal")
    check(len(dest_files(case)) == 1, "premise: the destination must have been published")
    check(status_of(case, "a.jpg") == "Processing", "premise: the row must be left Processing")

    run_engine(case)

    check(src.exists(), "recovery deleted a source it was never asked to delete")
    check(len(dest_files(case)) == 1, "recovery removed the published destination")

    incomplete = rows(case, "SELECT operation_id FROM operation_events "
                            "WHERE step='move' AND outcome='incomplete'")
    check(incomplete, "the interrupted Move was not recorded as incomplete")

    dest_id = rows(case, "SELECT file_id FROM file_states "
                         "WHERE location_role='destination' AND presence_state='present'")
    src_id = rows(case, "SELECT file_id FROM file_states "
                        "WHERE location_role='source' AND presence_state='present'")
    check(len(dest_id) == 1 and len(src_id) == 1,
          f"both copies must hold distinct identities, got dest={dest_id} src={src_id}")
    check(dest_id[0]["file_id"] != src_id[0]["file_id"],
          "the published destination was merged into the source identity")

    # Recovery observes; it does not publish. Superseding a recorded identity
    # for bytes nothing replaced mints a duplicate and falsely marks the real
    # one gone - invisible to a check that only counts PRESENT rows.
    superseded = rows(case, "SELECT file_id FROM file_states WHERE presence_state='missing'")
    check(not superseded,
          f"recovery superseded an identity for a file nothing replaced: {superseded}")
    per_path = rows(case, "SELECT current_path, COUNT(*) n FROM file_states "
                          "WHERE location_role='destination' GROUP BY current_path HAVING n > 1")
    check(not per_path, f"more than one destination identity for one path: {per_path}")

    evidence = rows(case, "SELECT location_role, result FROM operation_evidence "
                          "WHERE operation_id = ?", (incomplete[0]["operation_id"],))
    seen = {(e["location_role"], e["result"]) for e in evidence}
    check(("source", "present") in seen and ("destination", "present") in seen,
          f"recovery did not record what it observed at both locations: {seen}")


@test
def recovery_that_cannot_establish_an_outcome_opens_an_attention_issue():
    """
    Source gone and destination gone is genuinely ambiguous: the engine cannot
    tell a completed Move whose output was later removed from a delete that
    happened without one. It must say so rather than guess, and it must not
    silently reset the row as though nothing had been attempted.
    """
    engine = _load_engine()
    real_remove = engine._remove_verified_source

    def remove_then_die(*a, **kw):
        real_remove(*a, **kw)
        raise KeyboardInterrupt("simulated crash after the source was deleted")

    case = new_case("recovery_inconclusive")
    make_photo(case / "src" / "a.jpg", "AMBIGUOUS")
    run_engine(case, "--copy")

    engine._remove_verified_source = remove_then_die
    args = argparse.Namespace(move=True, copy=False, source=str(case / "src"),
                              source_subdir=None, file_ids=None)
    try:
        _run_fixture_move(engine, args, case / "appdata" / "db" / "ns_sqlite.db",
                          case / "dest", 999)
        raise Fail("the simulated crash did not happen")
    except KeyboardInterrupt:
        pass
    finally:
        engine._remove_verified_source = real_remove

    for delivered in (case / "dest").rglob("*.jpg"):
        delivered.unlink()
    check(not (case / "src" / "a.jpg").exists(), "premise: the source was removed")
    check(dest_files(case) == [], "premise: the destination was removed externally")

    run_engine(case)

    issues = rows(case, "SELECT issue_id, category, summary, resolved_at FROM attention_issues "
                        "WHERE resolved_at IS NULL")
    check(issues, "an unestablished outcome opened no attention issue")
    check(rows(case, "SELECT 1 FROM attention_evidence WHERE issue_id = ?",
               (issues[0]["issue_id"],)),
          "the attention issue carries no evidence")
    check(status_of(case, "a.jpg") != "Pending",
          "an unestablished outcome was reset to Pending as though nothing had happened")

    # The engine deleted this source itself. Blaming an outside change is false,
    # hides the interrupted operation, and sends the user to the wrong remedy
    # ("re-index") for a file no re-index can recover.
    blamed = [r["error_message"] for r in
              rows(case, "SELECT error_message FROM operations WHERE photo_id IS NOT NULL")
              if "outside NegativeSpace" in (r["error_message"] or "")]
    check(not blamed, f"the engine's own deletion was reported as an outside change: {blamed}")


def _assert_lineage_complete(case, label):
    """Every structural guarantee a history view depends on, for one catalog."""
    def one(sql, params=()):
        return rows(case, sql, params)[0]["n"]

    check(one("SELECT COUNT(*) n FROM photos p WHERE NOT EXISTS("
              "  SELECT 1 FROM photo_files pf WHERE pf.photo_id=p.id)") == 0,
          f"[{label}] a photo row resolves to no identity")
    check(one("SELECT COUNT(*) n FROM files f WHERE NOT EXISTS("
              "  SELECT 1 FROM file_states s WHERE s.file_id=f.file_id)") == 0,
          f"[{label}] an identity has no current state")
    check(one("SELECT COUNT(*) n FROM files f WHERE NOT EXISTS("
              "  SELECT 1 FROM file_origins o WHERE o.file_id=f.file_id)") == 0,
          f"[{label}] an identity has no origin record")
    check(one("SELECT COUNT(*) n FROM files f WHERE NOT EXISTS("
              "  SELECT 1 FROM operation_files of WHERE of.file_id=f.file_id)") == 0,
          f"[{label}] an identity participates in no operation, so it has no history")
    check(one("SELECT COUNT(*) n FROM file_origins o WHERE o.origin_file_id IS NOT NULL "
              "  AND NOT EXISTS(SELECT 1 FROM files f WHERE f.file_id=o.origin_file_id)") == 0,
          f"[{label}] an origin points at an identity that does not exist")
    check(one("SELECT COUNT(*) n FROM operation_events e WHERE NOT EXISTS("
              "  SELECT 1 FROM operations o WHERE o.id=e.operation_id)") == 0,
          f"[{label}] an event hangs off no operation")
    # Traces to an Index snapshot, or is explicitly recorded as something the
    # engine observed rather than created. Nothing else is permitted.
    check(one("""SELECT COUNT(*) n FROM files f
                  WHERE NOT EXISTS(SELECT 1 FROM source_snapshots s WHERE s.file_id=f.file_id)
                    AND NOT EXISTS(SELECT 1 FROM file_origins o
                                     JOIN source_snapshots s2 ON s2.file_id=o.origin_file_id
                                    WHERE o.file_id=f.file_id)
                    AND COALESCE((SELECT kind FROM file_origins WHERE file_id=f.file_id),'')
                        <> 'observed_destination'""") == 0,
          f"[{label}] an identity traces to neither an Index snapshot nor a recorded observation")
    check(not rows(case, "PRAGMA foreign_key_check"), f"[{label}] broken lineage reference")

    seen = set()
    for row in rows(case, "SELECT DISTINCT status FROM photos"):
        seen.add(row["status"])
        missing = rows(case, """SELECT p.id FROM photos p JOIN photo_files pf ON pf.photo_id=p.id
                                 WHERE p.status = ?
                                   AND NOT EXISTS(SELECT 1 FROM operation_files of
                                                   WHERE of.file_id=pf.file_id)""", (row["status"],))
        check(not missing, f"[{label}] photos with status {row['status']} assemble no history: {missing}")
    return seen


@test
def every_catalogued_file_assembles_complete_lineage():
    """
    Lineage must be assemblable for EVERY catalogued file in EVERY status it can
    reach - not only the ones that succeeded.

    webui-spec.md 6.3 promises a photo's full history, and that promise is only
    as good as the weakest row in the catalog. Two catalogs are driven here
    because one cannot hold every status at rest: a run ending in Move leaves
    Completed/Failed/Removed_Duplicate, while a run ending in a targeted Copy
    leaves Pending/Copied/Duplicate. Between them every status the engine can
    settle on is checked, including the unreadable source - the row most likely
    to be dropped and the one a user most needs explained.

    The one honest exception is a destination the engine found rather than
    created: no Index ever saw it, so it has no source snapshot and is recorded
    as observed_destination rather than given a fabricated origin.
    """
    covered = set()

    # 1. Delivered: Completed, Failed (unreadable), Removed_Duplicate.
    case = new_case("lineage_delivered")
    make_photo(case / "src" / "a.jpg", "LIN-A")
    make_photo(case / "src" / "b.jpg", "LIN-B")
    make_photo(case / "src" / "dup.jpg", "LIN-A")          # exact duplicate of a.jpg
    unreadable = case / "src" / "unreadable.jpg"
    make_photo(unreadable, "LIN-UNREADABLE")
    os.chmod(unreadable, 0o000)                             # local disk: chmod is honoured
    try:
        run_engine(case)
        run_engine(case, "--copy")
        run_engine(case, "--move")
    finally:
        # Guarded: if a future change makes this file deliverable it will be
        # gone, and an unguarded chmod would fail in cleanup rather than on an
        # assertion - hiding the real result behind a confusing error.
        if unreadable.exists():
            os.chmod(unreadable, 0o644)

    covered |= _assert_lineage_complete(case, "delivered")

    bad = rows(case, "SELECT id, status, sha1_hash FROM photos WHERE source_path LIKE '%unreadable.jpg'")
    check(bad, "the unreadable source was not catalogued at all")
    check(bad[0]["status"] == "Failed",
          f"an unreadable source should be Failed, got {bad[0]['status']}")
    check(not bad[0]["sha1_hash"],
          "an unreadable source recorded a hash it could not have computed")
    fid = rows(case, "SELECT file_id FROM photo_files WHERE photo_id = ?", (bad[0]["id"],))
    check(fid, "the unreadable source has no identity")
    check(rows(case, "SELECT 1 FROM operation_files WHERE file_id = ?", (fid[0]["file_id"],)),
          "the unreadable source has an identity but no recorded history")
    check(rows(case, """SELECT 1 FROM operations o JOIN photos p ON p.id=o.photo_id
                         WHERE p.id = ? AND o.error_message LIKE '%Permission denied%'""",
               (bad[0]["id"],)),
          "the unreadable source records no reason a user could act on")

    # 2. At rest: Pending, Copied, Duplicate - statuses a Move would consume.
    rest = new_case("lineage_at_rest")
    make_photo(rest / "src" / "c.jpg", "LIN-C")
    make_photo(rest / "src" / "d.jpg", "LIN-D")
    make_photo(rest / "src" / "e.jpg", "LIN-C")            # duplicate of c.jpg
    run_engine(rest)
    keep = rows(rest, "SELECT id FROM photos WHERE status = 'Pending' ORDER BY id LIMIT 1")
    run_engine(rest, "--copy", "--file-ids", keep[0]["id"])
    covered |= _assert_lineage_complete(rest, "at rest")

    required = {"Pending", "Copied", "Duplicate", "Completed", "Failed", "Removed_Duplicate"}
    check(required <= covered,
          f"lineage was not verified for every settled status; missing {sorted(required - covered)}")


@test
def invalid_input_exits_non_zero():
    """A missing or non-directory --source, or a non-positive --workers, is an error — not a quiet success."""
    case = new_case("bad_input")
    make_photo(case / "src" / "a.jpg", "A")
    run_engine(case, "--source", case / "does-not-exist", expect_rc=1)
    run_engine(case, "--source", case / "src" / "a.jpg", expect_rc=1)
    run_engine(case, "--workers", "0", expect_rc=2)
    run_engine(case, "--workers", "-3", expect_rc=2)


@test
def an_empty_test_filter_fails():
    """The suite refuses a --filter matching no test instead of passing vacuously."""
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--engine", str(ENGINE),
                           "--filter", "no_test_has_this_name"],
                          capture_output=True, text=True, timeout=120)
    check(proc.returncode != 0, f"a filter matching nothing reported success:\n{proc.stdout}")


@test
def the_mtime_fallback_says_files_are_not_changed():
    """The note about undated photos says plainly that only folder placement uses the mtime."""
    # "Filed by modification time" read to a real user as if the engine were
    # rewriting dates. It never modifies a file; the mtime only picks the
    # YYYY/MM/DD folder.
    case = new_case("mtime_wording")
    make_photo(case / "src" / "a.jpg", "A", date=None)
    out = engine_output(run_engine(case))
    check("files themselves are not changed" in out, f"the undated-photo note was ambiguous:\n{out}")


# ------------------------------------------------------ operational hygiene

@test
def exiftool_shutdown_is_bounded():
    """
    Each worker terminates its ExifTool at exit, and ProcessPoolExecutor waits
    for every worker, so the wait must be short. PyExifTool's keyword is
    `timeout`; any other raises TypeError, and falling back to the default
    quietly restores a 30 s wait per worker.
    """
    import inspect
    import exiftool
    check("timeout" in inspect.signature(exiftool.ExifTool.terminate).parameters,
          "the installed PyExifTool's terminate() no longer takes `timeout`")
    engine = _load_engine()
    waits = []

    class RecordingExifTool:
        def terminate(self, timeout=30, _del=False):  # PyExifTool's signature
            waits.append(timeout)

    engine._worker_exiftool = RecordingExifTool()
    engine._shutdown_worker_exiftool()
    check(waits == [5], f"ExifTool shutdown waited {waits} seconds, expected [5]")


@test
def a_large_log_is_rotated_at_startup():
    case = new_case("log_rotation")
    make_photo(case / "src" / "a.jpg", "a")
    logs = case / "appdata" / "logs"
    logs.mkdir(parents=True)
    log = logs / "organizer.log"

    log.write_text("earlier run\n")
    run_engine(case)
    check(not (logs / "organizer.log.1").exists(), "a small log was rotated")
    check(log.read_text().startswith("earlier run\n"), "a small log was not appended to")

    # Grow it past the limit. Sparse, so this costs no disk.
    limit = getattr(_load_engine(), "LOG_ROTATE_BYTES", 50 * 1024 * 1024)
    with open(log, "r+b") as f:
        f.truncate(limit + 1)
    run_engine(case)
    rotated = logs / "organizer.log.1"
    check(rotated.exists() and rotated.stat().st_size > limit,
          f"the oversized log was not rotated: {sorted(p.name for p in logs.iterdir())}")
    check(log.exists() and log.stat().st_size < 1024 * 1024
          and "finished with status" in log.read_text(),
          "the new log does not hold this run")


# ----------------------------------------------------------- preflight space

@test
def delivered_files_do_not_inflate_the_space_estimate():
    """
    Copy-then-Move writes nothing: the content is already at the destination,
    so the move only deletes sources. Budgeting for those bytes aborts the
    documented Copy→Move workflow on a destination with ample room for what
    the run will actually write.
    """
    case = new_case("preflight_delivered")
    # Incompressible and genuinely large: with KB-sized fixtures the reported
    # figure rounds to 0.00 MB whether or not the estimate is fixed, and the
    # assertion below would pass without measuring anything.
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        make_photo(case / "src" / name, name, size=(900, 600), noise=True)
    payload = sum(p.stat().st_size for p in (case / "src").rglob("*.jpg"))
    check(payload > 1024 * 1024,
          f"fixture payload is only {payload:,} bytes; too small for this test to mean anything")

    run_engine(case)
    run_engine(case, "--copy")

    out = engine_output(run_engine(case, "--move"))
    line = next((l for l in out.splitlines() if "items (" in l), "(no pre-flight line logged)")
    check("(0.00 MB)" in line,
          f"the move budgeted for files already at the destination: {line.strip()}")
    check("already at the destination" in out,
          "the log does not explain which files were left out of the estimate")

    # The move itself must still happen — the estimate is the only change.
    check(src_files(case) == [], f"the move left sources behind: {src_files(case)}")
    check(len(dest_files(case)) == 3, f"expected all three photos delivered: {dest_files(case)}")


@test
def a_space_shortfall_is_recorded_not_just_logged():
    """
    A pre-flight abort is a run-level failure and must leave a row: the Error
    Center reads `operations`, so a shortfall that only logs is invisible
    there, and the run reports Failed with nothing saying why.
    """
    engine = _load_engine()
    case = new_case("preflight_shortfall")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case)

    class TinyVolume:
        total, used, free = 1 << 30, 1 << 30, 4096

    original = engine.shutil.disk_usage
    engine.shutil.disk_usage = lambda _path: TinyVolume()
    try:
        args = argparse.Namespace(move=False, copy=True, source=str(case / "src"),
                                  source_subdir=None, file_ids=None)
        outcome = _run_fixture_move(engine, args, case / "appdata" / "db" / "ns_sqlite.db",
                                           case / "dest", 999)
    finally:
        engine.shutil.disk_usage = original

    check(outcome == "Failed", f"a destination with 4 KB free returned {outcome}")
    check(dest_files(case) == [], f"files were written despite the shortfall: {dest_files(case)}")

    recorded = rows(case, "SELECT source_path, error_message FROM operations "
                          "WHERE run_id = 999 AND status = 'Failed' AND photo_id IS NULL")
    check(len(recorded) == 1, f"the shortfall left no run-level failure record: {recorded}")
    message = recorded[0]["error_message"] or ""
    check("space" in message.lower() and "GB" in message,
          f"the record does not say how much space was needed or free: {message}")


# ------------------------------------------------------ directory durability

@test
def new_date_folders_are_made_durable_before_a_source_is_deleted():
    """
    fsync on a file does not persist its directory entry — hence the parent
    fsync at publish — and the same holds for every folder created on the way
    to it. Without syncing those ancestors, the first photo of a new day can
    be durable inside a day folder whose own entry in the month folder never
    reached disk: the copy unreachable after a power loss, the source already
    deleted.
    """
    engine = _load_engine()
    case = new_case("durable_chain")
    make_photo(case / "src" / "a.jpg", "a")
    dest = case / "dest" / "2026" / "02" / "14" / "a.jpg"
    # What a run sets before copying anything. It bounds the chain that has to
    # be persisted; without it a direct call can only persist the immediate
    # entry, since it has no way to know where the destination begins.
    engine._destination_root = case / "dest"

    synced = []
    real_sync = engine._fsync_directory

    def recording_sync(directory):
        synced.append(str(directory))
        return real_sync(directory)

    engine._fsync_directory = recording_sync
    try:
        ok, err = engine.copy_verify_delete(str(case / "src" / "a.jpg"), str(dest),
                                            delete_source=True)
    finally:
        engine._fsync_directory = real_sync

    check(ok, f"the move failed: {err}")
    for required in (case / "dest", case / "dest" / "2026", case / "dest" / "2026" / "02",
                     case / "dest" / "2026" / "02" / "14"):
        check(str(required) in synced,
              f"{required} was never fsynced, so its entry may not survive a power loss; "
              f"synced: {synced}")


@test
def the_documented_recovery_redelivers_a_removed_destination_file():
    """
    The `Skipped` reason and webui-spec 5.3 tell the user to re-index with
    --force-rehash and copy again when a destination file has gone missing.

    That advice replaced worse advice — a plain re-index, which inspects
    nothing at the destination and skips unchanged sources — so it has to be
    true rather than merely plausible. Both halves are asserted here: a plain
    Index leaves the row settled and delivers nothing, while --force-rehash
    re-reads the source, resets the row, and lets the next Copy restore the
    file.
    """
    case = new_case("documented_recovery")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case)
    run_engine(case, "--copy")
    check(status_of(case, "a.jpg") == "Copied", "the photo was not delivered")
    check(len(dest_files(case)) == 1, f"expected one delivered file, got {dest_files(case)}")

    for path in (case / "dest").rglob("*"):
        if path.is_file():
            path.unlink()
    check(dest_files(case) == [], "the destination file was not removed by the test itself")

    # A plain Index walks the source and skips a file whose row is settled, so
    # it cannot notice — and must not claim to notice — a missing destination.
    run_engine(case)
    check(status_of(case, "a.jpg") == "Copied",
          "a plain re-Index reset the row; the advice against relying on it is now stale")
    run_engine(case, "--copy")
    check(dest_files(case) == [], f"a plain re-Index re-delivered the file: {dest_files(case)}")

    # The documented repair.
    run_engine(case, "--force-rehash")
    check(status_of(case, "a.jpg") == "Pending",
          "--force-rehash did not reset the delivered row, so the documented repair cannot work")
    run_engine(case, "--copy")
    check(status_of(case, "a.jpg") == "Copied", "the re-copy did not complete")
    check(len(dest_files(case)) == 1, f"the file was not re-delivered: {dest_files(case)}")


@test
def the_durability_chain_never_reaches_above_the_destination():
    """
    The chain walk stops at --dest.

    A destination outside the root is not hypothetical: _destination_for falls
    back to the catalog's stored path when a row has no usable recorded date,
    and that stored path was computed against whatever --dest was current when
    the row was written — the very case that function exists to handle. If the
    walk cannot find its root it must not climb toward /, fsyncing directories
    the engine has no business touching: outside the destination a sync can
    fail on permissions and refuse a legitimate move, or quietly persist
    directories belonging to someone else.
    """
    engine = _load_engine()
    case = new_case("chain_bounds")
    make_photo(case / "src" / "a.jpg", "a")
    outside = case / "elsewhere" / "2026" / "02" / "14"
    # The file is deliberately NOT under this root.
    engine._destination_root = case / "dest"

    synced = []
    real_sync = engine._fsync_directory

    def recording_sync(directory):
        synced.append(str(directory))
        return real_sync(directory)

    engine._fsync_directory = recording_sync
    try:
        ok, err = engine.copy_verify_delete(str(case / "src" / "a.jpg"),
                                            str(outside / "a.jpg"), delete_source=True)
    finally:
        engine._fsync_directory = real_sync

    check(ok, f"the move failed: {err}")
    stray = [d for d in synced if not d.startswith(str(case / "elsewhere"))]
    check(not stray, f"directories outside the destination were fsynced: {stray}")


@test
def a_failed_ancestor_sync_is_retried_not_forgotten():
    """
    A refused barrier must stay refused until it succeeds.

    _mkdir_durable creates the whole date chain before syncing it, so a failed
    ancestor sync leaves those directories on disk. If a later move reads their
    existence as proof of durability it deletes that file's source with the
    barrier still unestablished — the guarantee lapses one file after the
    failure instead of holding. Directory existence is not durability: a
    directory exists the moment mkdir returns, which is before its entry is
    durable in its parent.
    """
    import errno
    import stat as stat_module
    engine = _load_engine()
    case = new_case("ancestor_retry")
    make_photo(case / "src" / "a.jpg", "a")
    make_photo(case / "src" / "b.jpg", "b")
    dest_root = case / "dest"
    dest_root.mkdir(parents=True)
    day = dest_root / "2026" / "02" / "14"
    root_stat = os.stat(dest_root)
    real_fsync = engine.os.fsync
    root_sync_fails = True

    def fsync_with_failing_root(fd):
        # Only the destination root's own sync fails; every deeper directory
        # and every file syncs normally, which is what leaves the chain half
        # established.
        info = os.fstat(fd)
        if root_sync_fails and stat_module.S_ISDIR(info.st_mode) \
                and os.path.samestat(info, root_stat):
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_fsync(fd)

    def move(name, module):
        module._destination_root = dest_root
        return module.copy_verify_delete(str(case / "src" / name), str(day / name),
                                         delete_source=True)

    engine.os.fsync = fsync_with_failing_root
    try:
        ok, err = move("a.jpg", engine)
        check(not ok, "the first move ignored a failing destination-root sync")

        ok, err = move("b.jpg", engine)
        check(not ok, f"a second file into the same folder was moved although the destination "
                      f"root's barrier had failed: {err}")

        ok, err = move("a.jpg", engine)
        check(not ok, f"retrying the first file ignored the still-failing barrier: {err}")

        # A restart must re-establish the chain rather than trust the
        # directories the failed attempt left behind.
        ok, err = move("b.jpg", _load_engine())
        check(not ok, f"a restarted engine trusted directories left by a failed barrier: {err}")

        check(sorted(src_files(case)) == ["a.jpg", "b.jpg"],
              f"a source was deleted while a required barrier was still failing: {src_files(case)}")

        # Once the barrier succeeds the move proceeds normally.
        root_sync_fails = False
        ok, err = move("a.jpg", engine)
        check(ok, f"the move still failed after the barrier succeeded: {err}")
        check(src_files(case) == ["b.jpg"],
              f"the delivered file's source was not removed: {src_files(case)}")
    finally:
        engine.os.fsync = real_fsync


def _failing_root_fsync(root_stat, real_fsync):
    """
    An fsync that fails ONLY for the destination root directory.

    Every deeper directory and every file syncs normally, so the chain is left
    half established exactly where the walk is supposed to notice — a failure
    at the top, with everything below it already durable.
    """
    import errno
    import stat as stat_module

    def fsync(fd):
        info = os.fstat(fd)
        if stat_module.S_ISDIR(info.st_mode) and os.path.samestat(info, root_stat):
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_fsync(fd)
    return fsync


# _run_move_or_copy is handed a run id directly, and no matching row is ever
# inserted into `runs`. Anything asserting on the operations this run records
# must therefore scope to THIS id — _last_run_failures filters on
# MAX(id) FROM runs, which is the Index run, and would find nothing.
_IN_PROCESS_RUN_ID = 999


def _move_in_process(engine, case):
    """
    Runs the move loop inside this process, since os.fsync injection cannot
    cross a subprocess boundary. _run_move_or_copy sets _destination_root and
    clears the verified-directory set itself, so the cache starts cold exactly
    as it would in a real run.
    """
    args = argparse.Namespace(move=True, copy=False, source=str(case / "src"),
                              source_subdir=None, file_ids=None)
    return _run_fixture_move(engine, args, case / "appdata" / "db" / "ns_sqlite.db",
                                    case / "dest", _IN_PROCESS_RUN_ID)


@test
def the_already_present_deletion_establishes_the_ancestor_barrier():
    """
    A source deleted against a copy an EARLIER run delivered must still have
    the destination chain persisted first.

    _mkdir_durable had a single caller — copy_verify_delete — so only a file
    the run copied itself got the entries above it persisted. This path
    deletes against a copy that already existed, reaching
    _remove_verified_source directly, which syncs the copy and the directory
    holding it and nothing above that.

    An earlier run's mkdir is not evidence. A directory exists the moment
    mkdir returns, which is before its entry is durable in its parent — which
    is exactly why _run_move_or_copy clears the verified set at the start of
    every run.
    """
    case = new_case("present_barrier")
    src = case / "src" / "a.jpg"
    make_photo(src, "present")
    run_engine(case)
    dest = Path(rows(case, "SELECT dest_path FROM photos")[0]["dest_path"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)  # identical bytes, separate file — not a hard link

    engine = _load_engine()
    real_fsync = engine.os.fsync
    engine.os.fsync = _failing_root_fsync(os.stat(case / "dest"), real_fsync)
    try:
        _move_in_process(engine, case)
    finally:
        engine.os.fsync = real_fsync

    check(src.exists(),
          "the already-present branch deleted a source although the destination root's "
          "barrier was failing")
    # The refusal must be RECORDED, not merely logged — the Error Center reads
    # operations, and a warning in the log is invisible to it.
    refusals = rows(case, "SELECT error_message FROM operations "
                          "WHERE status = 'Failed' AND run_id = ?", (_IN_PROCESS_RUN_ID,))
    check(refusals and "Source kept" in (refusals[0]["error_message"] or ""),
          f"the refusal was not recorded as a failed operation: {refusals}")


@test
def duplicate_cleanup_establishes_the_ancestor_barrier():
    """
    Duplicate cleanup deletes a duplicate's source against the anchor's
    delivered copy — which this run may not have written either.

    Separate from the already-present case above because it is a separate
    caller of _remove_verified_source, and the defect was that each caller
    established the barrier for itself or not at all. A test per caller says
    which one regressed.
    """
    case = new_case("dup_barrier")
    make_photo(case / "src" / "a.jpg", "twin")
    make_photo(case / "src" / "b.jpg", "twin")
    run_engine(case)
    anchor = rows(case, "SELECT id FROM photos WHERE status = 'Pending'")[0]["id"]
    duplicate = rows(case, "SELECT id, source_path FROM photos WHERE status = 'Duplicate'")[0]
    run_engine(case, "--move", "--file-ids", anchor)
    dup_src = Path(duplicate["source_path"])

    engine = _load_engine()
    real_fsync = engine.os.fsync
    engine.os.fsync = _failing_root_fsync(os.stat(case / "dest"), real_fsync)
    try:
        _move_in_process(engine, case)
    finally:
        engine.os.fsync = real_fsync

    check(dup_src.exists(),
          "duplicate cleanup deleted a source although the destination root's barrier "
          "was failing")
    final = rows(case, "SELECT status FROM photos WHERE id = ?", (duplicate["id"],))[0]["status"]
    check(final == "Duplicate",
          f"the duplicate row did not return to Duplicate after the refusal, got {final}")


@test
def directory_sync_errors_are_tolerated_only_when_unsupported():
    """
    EINVAL/ENOTSUP report directory fsync as ABSENT, not as a failure to
    persist, so a move proceeds on filesystems that lack it. A real error
    means durability could not be established, and the source must be kept.
    """
    import errno
    import stat as stat_module
    engine = _load_engine()
    real_fsync = engine.os.fsync

    def move_with_directory_sync_error(code, label):
        case = new_case(f"dir_sync_{label}")
        make_photo(case / "src" / "a.jpg", "a")

        def failing_fsync(fd):
            # Files still sync normally; only directory syncs report the error.
            if stat_module.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(code, os.strerror(code))
            return real_fsync(fd)

        engine.os.fsync = failing_fsync
        try:
            result = engine.copy_verify_delete(str(case / "src" / "a.jpg"),
                                               str(case / "dest" / "a.jpg"), delete_source=True)
        finally:
            engine.os.fsync = real_fsync
        return result, case

    (ok, err), case = move_with_directory_sync_error(errno.EINVAL, "unsupported")
    check(ok, f"a filesystem without directory fsync refused the move: {err}")
    check(src_files(case) == [], "the source was kept although the sync was merely unsupported")

    (ok, err), case = move_with_directory_sync_error(errno.EIO, "failing")
    check(not ok, "a failing directory sync still deleted the source")
    check(src_files(case) == ["a.jpg"], f"the source was not kept: {src_files(case)}")
    check("durable" in (err or "").lower(), f"the refusal does not name durability: {err}")


@test
def an_unsupported_directory_fsync_is_reported_once_per_run():
    """
    A filesystem that cannot fsync directories gives a weaker power-loss
    guarantee, and the user should hear that from the run rather than infer it
    from the spec.

    EINVAL/ENOTSUP are tolerated by design — the operation is absent rather
    than failed — so the move proceeds and, until now, nothing said anything at
    all. On exFAT or an odd network mount that silence was the whole problem.

    Once per RUN, not once per process: the flag resets with the other per-run
    durability bookkeeping, so a second run on the same loaded engine says it
    again. And not once per directory, which on a real library would be a line
    per date folder — hence two photos in different date folders below.
    """
    import errno
    import logging
    import stat as stat_module

    engine = _load_engine()
    real_fsync = engine.os.fsync

    def unsupported_dir_fsync(fd):
        # Files still sync normally; only directory syncs report the error,
        # which is what a filesystem lacking the operation actually looks like.
        if stat_module.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))
        return real_fsync(fd)

    said = []

    class Capture(logging.Handler):
        def emit(self, record):
            said.append(record.getMessage())

    handler = Capture()
    engine.logger.addHandler(handler)

    def move_one(name, date):
        case = new_case(name)
        make_photo(case / "src" / "a.jpg", f"{name}-a", date=date)
        make_photo(case / "src" / "b.jpg", f"{name}-b", date="2019:07:02 11:00:00")
        run_engine(case)
        engine.os.fsync = unsupported_dir_fsync
        try:
            _move_in_process(engine, case)
        finally:
            engine.os.fsync = real_fsync
        return case

    try:
        case = move_one("fsync_signal_a", "2021:03:04 08:00:00")
        first = [m for m in said if "cannot fsync directories" in m]
        check(len(first) == 1,
              f"expected exactly one unsupported-fsync report per run, got {len(first)}: {first}")
        check(str(case / "dest") in first[0],
              f"the report does not name the path it could not sync: {first[0]}")
        # Tolerated means tolerated: the move still completes.
        check(src_files(case) == [], f"the move was refused, not tolerated: {src_files(case)}")

        move_one("fsync_signal_b", "2022:05:06 08:00:00")
        both = [m for m in said if "cannot fsync directories" in m]
        check(len(both) == 2,
              f"a second run stayed silent — the flag is per process, not per run: {both}")
    finally:
        engine.logger.removeHandler(handler)


@test
def the_move_loop_commits_at_full_synchronous():
    """
    The move/copy loop runs at synchronous=FULL; the scan path stays NORMAL.

    Every delete commits status=Processing with dest_path BEFORE unlinking, and
    reconciliation finds interrupted work by exactly that marker. Under NORMAL
    in WAL a commit is not fsynced, so a power cut can take the marker while
    the unlink — which IS fsynced — survives. A probe built that state
    directly: the next Index then recorded a successfully migrated photo as
    Failed, because its source was gone and nothing said why. That is a wrong
    row about a delivered file, not merely missing history.

    Scoped rather than global. FULL measured 1.42x on this path (+1.9ms per
    photo) against the ~4.4x quoted for the scan path, which batches commits
    and writes no markers — so db_writer_worker keeps NORMAL and only this one
    connection pays. The move loop opens exactly one.

    The audit rows come along for free: log_operation commits immediately in
    this loop, on this same connection.
    """
    engine = _load_engine()
    case = new_case("audit_sync")
    make_photo(case / "src" / "a.jpg", "a")
    make_photo(case / "src" / "b.jpg", "b")
    run_engine(case)
    db_file = str(case / "appdata" / "db" / "ns_sqlite.db")

    def level(conn):
        # PRAGMA synchronous reports 1 for NORMAL, 2 for FULL.
        return conn.execute("PRAGMA synchronous").fetchone()[0]

    default_conn = engine.get_db_connection(db_file)
    try:
        check(level(default_conn) == 1,
              f"the default connection should stay NORMAL, got {level(default_conn)}")
    finally:
        default_conn.close()

    full_conn = engine.get_db_connection(db_file, synchronous="FULL")
    try:
        check(level(full_conn) == 2,
              f"an explicitly FULL connection is not FULL, got {level(full_conn)}")
    finally:
        full_conn.close()

    # Asking for it is not enough; the move loop has to actually do it.
    seen = []
    real_get = engine.get_db_connection

    def recording(path, *a, **kw):
        conn = real_get(path, *a, **kw)
        seen.append(conn.execute("PRAGMA synchronous").fetchone()[0])
        return conn

    engine.get_db_connection = recording
    try:
        _move_in_process(engine, case)
    finally:
        engine.get_db_connection = real_get

    check(2 in seen,
          f"the move loop opened no FULL connection; levels seen were {seen}")
    check(src_files(case) == [], f"the move did not complete: {src_files(case)}")


@test
def a_photo_this_run_delivered_is_not_also_reported_skipped():
    """
    The already-copied outcome reports what EARLIER runs delivered. The query
    runs after the copy loop, when the rows it just wrote are already
    `Copied`, so it must exclude what this run itself recorded — otherwise
    every delivered photo ends its own job with two contradictory outcomes.
    """
    case = new_case("copy_no_double_outcome")
    make_photo(case / "src" / "a.jpg", "a")
    make_photo(case / "src" / "b.jpg", "b")
    make_photo(case / "src" / "dup.jpg", "a")  # same content as a.jpg
    run_engine(case)
    run_engine(case, "--copy")

    ops = rows(case, "SELECT photo_id, status FROM operations "
                     "WHERE run_id = (SELECT MAX(id) FROM runs)")
    by_photo = {}
    for op in ops:
        by_photo.setdefault(op["photo_id"], []).append(op["status"])
    doubled = {photo: statuses for photo, statuses in by_photo.items() if len(statuses) > 1}
    check(not doubled, f"photos recorded with two outcomes in one run: {doubled}")
    check(sorted(op["status"] for op in ops) == ["Copied", "Copied", "Skipped"],
          f"expected two deliveries and one skipped duplicate, got "
          f"{sorted(op['status'] for op in ops)}")


@test
def a_second_copy_of_a_delivered_photo_records_the_outcome():
    """
    Selecting an already-copied photo for Copy again must end with a recorded
    outcome, as §5.3 requires of every selected photo. It reports what the
    catalog holds — an earlier run's result — not a fresh verification.
    """
    case = new_case("recopy_outcome")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case)
    run_engine(case, "--copy")
    photo_id = rows(case, "SELECT id FROM photos")[0]["id"]

    run_engine(case, "--copy", "--file-ids", photo_id)
    ops = rows(case, "SELECT status, error_message, dest_path, photo_id FROM operations "
                     "WHERE run_id = (SELECT MAX(id) FROM runs)")
    check(len(ops) == 1, f"expected exactly one recorded outcome, got {ops}")
    check(ops[0]["status"] == "Skipped", f"expected a Skipped outcome, got {ops[0]['status']}")
    check(ops[0]["photo_id"] == photo_id, "the outcome is not attached to the selected photo")
    message = (ops[0]["error_message"] or "").lower()
    check("already" in message and "earlier run" in message,
          f"the reason does not say this is a recorded prior result: {ops[0]['error_message']}")
    check(ops[0]["dest_path"] and Path(ops[0]["dest_path"]).exists(),
          f"the outcome does not point at the delivered file: {ops[0]['dest_path']}")
    check(status_of(case, "a.jpg") == "Copied", "the photo's own status was changed")
    check(len(dest_files(case)) == 1, f"a second copy was written: {dest_files(case)}")


# ---------------------------------------------------------------------- main

@test
def foundation_original_snapshots_include_duplicates_and_survive_rescan():
    case = new_case("foundation_originals")
    a = case / "src" / "a.jpg"
    b = case / "src" / "b.jpg"
    make_photo(a, "SAME")
    shutil.copyfile(a, b)
    os.utime(a, (1000000000, 1000000000))
    os.utime(b, (1100000000, 1100000000))
    run_engine(case)
    original = rows(case, "SELECT file_id,source_path,file_mtime,sha1_hash FROM source_snapshots ORDER BY file_id")
    check(len(original) == 2, "duplicate source lacks its own snapshot")
    check({r["file_mtime"] for r in original} == {1000000000,1100000000}, "source-specific timestamps lost")
    os.utime(a, (1200000000,1200000000))
    run_engine(case, "--force-rehash")
    check(rows(case, "SELECT file_id,source_path,file_mtime,sha1_hash FROM source_snapshots ORDER BY file_id") == original,
          "rescan overwrote original evidence")
    check(len(rows(case, "SELECT * FROM file_observations")) == 4, "later scan evidence missing")
    check(not rows(case, "PRAGMA foreign_key_check"), "broken lineage reference")


@test
def foundation_reimport_after_move_keeps_old_lineage():
    case = new_case("foundation_reimport")
    a = case / "src" / "a.jpg"
    make_photo(a, "REIMPORT")
    run_engine(case, "--move")
    before = rows(case, "SELECT * FROM source_snapshots")[0]
    delivered = Path(rows(case, "SELECT dest_path FROM photos")[0]["dest_path"])
    shutil.copy2(delivered, a)
    run_engine(case)  # same path, bytes and mtime must not be stat-skipped
    after = rows(case, "SELECT * FROM source_snapshots ORDER BY file_id")
    check(len(after) == 2 and after[0] == before, "reimport lost or reused moved identity")
    check(len(rows(case, "SELECT * FROM operation_files WHERE file_id=?", (before["file_id"],))) >= 2,
          "old scan/move history link lost")
    run_engine(case, "--move")
    check(not a.exists() and len(dest_files(case)) == 1, "repeat Move created duplicate destination or left source")


@test
def foundation_settings_are_frozen_in_actual_engine_runs():
    import ns_db
    case = new_case("foundation_settings")
    path = case / "appdata" / "db" / "ns_sqlite.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    ns_db.initialize(path)
    conn = ns_db.connect(path)
    try:
        ns_db.save_settings(conn, {"workers": 1, "exts": ["jpg"]}, expected_revisions={"workers":0,"exts":0})
    finally:
        conn.close()
    make_photo(case / "src" / "a.jpg", "SETTINGS")
    run_engine(case)
    cfg = json.loads(rows(case, "SELECT effective_config_json FROM run_configs")[0]["effective_config_json"])
    check(cfg["workers"] == 1 and cfg["exts"] == [".jpg"], "engine did not use persisted settings")
    run_engine(case, "--workers", "2")
    configs = rows(case, "SELECT effective_config_json FROM run_configs ORDER BY run_id")
    check(json.loads(configs[0]["effective_config_json"]) == cfg, "old config changed")
    check(json.loads(configs[1]["effective_config_json"])["workers"] == 2, "explicit override ignored")


@test
def destination_lineage_copy_then_move_preserves_both_identities():
    case = new_case("lineage_copy_move")
    make_photo(case / "src" / "a.jpg", "LINEAGE")
    run_engine(case, "--copy")
    states = rows(case, "SELECT * FROM file_states ORDER BY file_id")
    check(len(states) == 2, "Copy must have distinct source and destination")
    a, b = states
    check(a['location_role'] == 'source' and b['location_role'] == 'destination', "incorrect Copy locations")
    check(rows(case, "SELECT origin_file_id FROM file_origins WHERE file_id=?", (b['file_id'],))[0]['origin_file_id'] == a['file_id'], "Copy origin missing")
    check(len(rows(case, "SELECT * FROM source_snapshots")) == 1, "Copy fabricated an Index snapshot")
    run_engine(case, "--move")
    states = rows(case, "SELECT * FROM file_states ORDER BY file_id")
    check(len(states) == 2 and states[0]['presence_state'] == 'removed' and states[1]['presence_state'] == 'present', "Copy→Move merged identities")
    check(rows(case, "SELECT * FROM operation_files WHERE file_id=? AND role='retained_copy'", (b['file_id'],)), "retained destination is not linked")
    check(not rows(case, "PRAGMA foreign_key_check"), "broken lineage reference")


@test
def destination_lineage_move_and_duplicate_share_retained_identity():
    case = new_case("lineage_duplicates")
    make_photo(case / "src" / "a.jpg", "LINEAGE-DUP")
    shutil.copy2(case / "src" / "a.jpg", case / "src" / "b.jpg")
    run_engine(case, "--move")
    states = rows(case, "SELECT * FROM file_states ORDER BY file_id")
    check(len(states) == 2, "Move must not invent a Copy identity")
    retained = [r for r in states if r['location_role'] == 'destination' and r['presence_state'] == 'present']
    check(len(retained) == 1 and sum(r['presence_state'] == 'removed' for r in states) == 1, "duplicate source state incorrect")
    links = rows(case, "SELECT role FROM operation_files WHERE file_id=?", (retained[0]['file_id'],))
    check({'destination','retained_copy'} <= {r['role'] for r in links}, "Move and duplicate removal must link same retained identity")
    check(len(rows(case, "SELECT * FROM source_snapshots")) == 2, "duplicate origin was lost")


# --------------------------------------------------------------- thumbnails

# The grid size webui-spec.md 4.2.1 promises and the web UI is built against.
# Hardcoded rather than imported from the engine on purpose: a test that read
# the number out of the engine would follow a regression instead of catching it.
GRID_THUMBNAIL_SIZE = 320

RAW_SUFFIXES = ('.dng', '.cr2', '.cr3', '.nef', '.arw', '.raf', '.orf', '.rw2', '.pef', '.srw')


def cached_thumbnails(case):
    """Every JPEG currently sitting in this case's thumbnail cache."""
    root = case / "cache" / "thumbnails"
    return sorted(root.rglob("*.jpg")) if root.exists() else []


@test
def index_generates_a_grid_thumbnail_for_every_photo():
    """Index writes one JPEG per content, at the documented size and layout."""
    from PIL import Image
    case = new_case("thumbgen")
    make_photo(case / "src" / "one.jpg", "one", size=(800, 600))
    make_photo(case / "src" / "two.jpg", "two", size=(640, 900))
    run_engine(case)

    cached = cached_thumbnails(case)
    check(len(cached) == 2, f"expected 2 cached thumbnails, found {len(cached)}")
    for p in cached:
        with Image.open(p) as img:
            check(max(img.size) == GRID_THUMBNAIL_SIZE,
                  f"thumbnail longest edge is {max(img.size)}, expected {GRID_THUMBNAIL_SIZE}")
        # Fanned out by the hash's first two characters, so no directory ends up
        # holding tens of thousands of flat entries.
        check(p.parent.name == p.stem[:2],
              f"thumbnail is not fanned out by hash prefix: {p.parent.name}/ holds {p.name}")

    entries = rows(case, "SELECT size,availability,cache_filename,bytes FROM thumbnail_cache")
    check(len(entries) == 2, f"expected 2 thumbnail_cache rows, got {len(entries)}")
    for e in entries:
        check(e["availability"] == "present", f"expected a present entry, got {e['availability']}")
        check(e["size"] == GRID_THUMBNAIL_SIZE, f"entry recorded size {e['size']}")
        check(e["bytes"] and e["bytes"] > 0,
              "bytes must be recorded — per-size cache totals are a SUM of this column")
        # Relative, because /cache is a mount whose path is not guaranteed
        # stable across containers.
        check(not Path(e["cache_filename"]).is_absolute(),
              f"cache_filename must be relative to the cache root, got {e['cache_filename']}")
        check((case / "cache" / e["cache_filename"]).is_file(),
              f"catalog names a thumbnail that is not on disk: {e['cache_filename']}")

    # Dimensions describe the CONTENT, and are the source photo's, not the
    # thumbnail's — draft() decodes at a reduced scale, so reading them after
    # the fact would record 320x240 for every photo in the library.
    sizes = {(c["width"], c["height"]) for c in rows(case, "SELECT width,height FROM contents")}
    check(sizes == {(800, 600), (640, 900)},
          f"contents recorded the wrong source dimensions: {sorted(sizes)}")


@test
def a_rotated_photo_gets_an_upright_thumbnail():
    """
    EXIF orientation is a tag, not pixels. PIL's Image.open() ignores it while
    browsers and viewers apply it, so a thumbnail generated without transposing
    sits a quarter turn against the photo it represents — 20.1% of one real
    library. Every other assertion in this file passes on a sideways thumbnail:
    the dimensions, byte count and row accounting are all still correct.
    """
    from PIL import Image
    case = new_case("thumbrotate")
    photo = case / "src" / "portrait.jpg"
    # Stored landscape, tagged to display portrait — the common camera layout.
    make_photo(photo, "rot", size=(400, 200))
    subprocess.run(["exiftool", "-overwrite_original", "-Orientation#=6", str(photo)],
                   capture_output=True, check=True)
    run_engine(case)

    cached = cached_thumbnails(case)
    check(len(cached) == 1, f"expected 1 thumbnail, found {len(cached)}")
    with Image.open(cached[0]) as img:
        check(img.size[1] > img.size[0],
              f"a photo stored 400x200 with orientation=6 displays portrait, but its "
              f"thumbnail is {img.size[0]}x{img.size[1]} — the tag was not applied")

    # Dimensions describe the photograph, not the buffer it is stored in. A
    # gallery sorting or filtering by resolution reads these.
    dims = rows(case, "SELECT width, height FROM contents")[0]
    check((dims["width"], dims["height"]) == (200, 400),
          f"contents recorded {dims['width']}x{dims['height']}, expected the "
          f"displayed 200x400 rather than the stored 400x200")


@test
def byte_identical_duplicates_share_one_thumbnail():
    """Keying on content, not path, is what makes duplicates free to render."""
    case = new_case("thumbdup")
    (case / "src" / "sub").mkdir(parents=True)
    make_photo(case / "src" / "orig.jpg", "same")
    shutil.copy2(case / "src" / "orig.jpg", case / "src" / "sub" / "copy.jpg")
    run_engine(case)

    cached = cached_thumbnails(case)
    check(len(cached) == 1,
          f"two byte-identical photos generated {len(cached)} thumbnails; expected them to share one")
    check(len(rows(case, "SELECT 1 FROM contents")) == 1,
          "byte-identical copies must resolve to a single content identity")
    check(len(rows(case, "SELECT 1 FROM thumbnail_cache")) == 1,
          "one content must hold one cache entry per size, not one per file")
    check(len(rows(case, "SELECT 1 FROM photos")) == 2,
          "both copies must still be catalogued as separate photos")


@test
def an_undecodable_photo_records_a_thumbnail_failure_without_failing_the_index():
    """A thumbnail is disposable cache: losing one must not cost a catalog row."""
    case = new_case("thumbbroken")
    make_photo(case / "src" / "good.jpg", "good")
    # A supported extension whose bytes are not an image at all.
    (case / "src" / "broken.jpg").write_bytes(b"not a jpeg at all")
    run_engine(case)  # expect_rc=0: the Index must still succeed

    failed = rows(case, "SELECT failure_category,failure_detail,cache_filename FROM thumbnail_cache "
                        "WHERE availability='failed'")
    check(len(failed) == 1, f"expected 1 failed thumbnail entry, got {len(failed)}")
    check(failed[0]["failure_category"] == "decode_failed",
          f"expected decode_failed, got {failed[0]['failure_category']}")
    # The UI shows this text in the placeholder; an unexplained blank tile is
    # the failure mode this column exists to prevent.
    check(failed[0]["failure_detail"], "a failed thumbnail must carry a reason the UI can show")
    check(failed[0]["cache_filename"] is None, "a failed thumbnail must not name a cache file")

    check(len(rows(case, "SELECT 1 FROM thumbnail_cache WHERE availability='present'")) == 1,
          "the readable photo's thumbnail must still have been generated")
    check(status_of(case, "broken.jpg") is not None,
          "a file whose thumbnail failed must still be catalogued")


@test
def no_thumbnails_skips_generation_but_still_indexes():
    """The flag turns off the cache, not the Index."""
    case = new_case("thumboff")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case, "--no-thumbnails")

    check(cached_thumbnails(case) == [], "--no-thumbnails still wrote to the cache")
    check(rows(case, "SELECT 1 FROM thumbnail_cache") == [],
          "--no-thumbnails still recorded cache entries")
    check(status_of(case, "a.jpg") == "Pending", "--no-thumbnails must not affect cataloguing")
    # Content identity is not thumbnail state, and must be recorded either way.
    check(len(rows(case, "SELECT 1 FROM contents")) == 1,
          "content identity must be recorded even when thumbnails are off")


@test
def an_existing_thumbnail_is_reused_rather_than_regenerated():
    """The cache-hit path is what makes re-indexing a large library cheap."""
    case = new_case("thumbreuse")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case)
    cached = cached_thumbnails(case)
    check(len(cached) == 1, f"expected 1 thumbnail, found {len(cached)}")
    before = cached[0].stat().st_mtime_ns

    # --force-rehash re-reads the file itself, so reaching the generator is
    # guaranteed; only the cache hit can prevent a rewrite.
    run_engine(case, "--force-rehash")
    check(cached_thumbnails(case)[0].stat().st_mtime_ns == before,
          "a re-index rewrote an existing thumbnail instead of reusing it")


@test
def an_unwritable_cache_does_not_fail_the_index():
    """Thumbnails are reproducible; a bad /cache mount must not stop cataloguing."""
    if os.geteuid() == 0:
        raise Fail("SKIP: running as root, which ignores directory permissions")
    case = new_case("thumbro")
    make_photo(case / "src" / "a.jpg", "a")
    (case / "cache").mkdir()
    (case / "cache").chmod(0o500)
    try:
        out = engine_output(run_engine(case))
        check("not writable" in out,
              f"expected a cache-not-writable warning; last output:\n{out[-800:]}")
        check(status_of(case, "a.jpg") == "Pending",
              "an unwritable cache must not change the Index outcome")
    finally:
        (case / "cache").chmod(0o700)


@test
def raw_files_produce_thumbnails_through_rawpy():
    """
    The RAW path cannot be covered synthetically — LibRaw rejects fabricated
    files — so this runs only against real camera output. It exercises whichever
    branch the files call for: an embedded preview large enough to use, or a
    demosaic when there is none.
    """
    raw_dir = os.environ.get("NS_TEST_RAW_DIR")
    if not raw_dir:
        raise Fail("SKIP: set NS_TEST_RAW_DIR to a folder of real RAW files")
    sources = [p for p in sorted(Path(raw_dir).iterdir())
               if p.is_file() and p.suffix.lower() in RAW_SUFFIXES][:3]
    if not sources:
        raise Fail(f"SKIP: no RAW files with a known extension in NS_TEST_RAW_DIR")

    from PIL import Image
    case = new_case("thumbraw")
    # Copied under generic names: a failure message must never carry a filename
    # from the maintainer's library.
    for i, p in enumerate(sources):
        shutil.copy2(p, case / "src" / f"raw_{i}{p.suffix.lower()}")
    run_engine(case)

    entries = rows(case, "SELECT availability,failure_category,cache_filename FROM thumbnail_cache")
    check(len(entries) == len(sources),
          f"expected {len(sources)} thumbnail entries, got {len(entries)}")
    for e in entries:
        check(e["availability"] == "present",
              f"a RAW thumbnail failed: {e['failure_category']}")
        with Image.open(case / "cache" / e["cache_filename"]) as img:
            check(max(img.size) == GRID_THUMBNAIL_SIZE,
                  f"RAW thumbnail longest edge is {max(img.size)}, expected {GRID_THUMBNAIL_SIZE}")


# ------------------------------------------------------------ request IDs

EXIT_REQUEST_CONFLICT = 3
EXIT_REQUEST_ALREADY_ACCEPTED = 4


@test
def a_repeated_request_id_starts_nothing():
    """
    Duplicate delivery of one submission must not execute twice. The replay
    answers with the run the first delivery created and does no file work —
    proven by a photo added between the two deliveries staying unindexed,
    which a replay that quietly rescanned would have catalogued.
    """
    case = new_case("request_replay")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case, "--request-id", "req-1")
    make_photo(case / "src" / "b.jpg", "b")

    proc = run_engine(case, "--request-id", "req-1", expect_rc=EXIT_REQUEST_ALREADY_ACCEPTED)

    runs = rows(case, "SELECT id FROM runs")
    check(len(runs) == 1, f"a replayed request created another run: {len(runs)} runs")
    indexed = sorted(Path(r["source_path"]).name for r in rows(case, "SELECT source_path FROM photos"))
    check(indexed == ["a.jpg"], f"a replayed request did file work: indexed {indexed}")
    bound = rows(case, "SELECT request_id, run_id FROM job_requests")
    check(bound == [{"request_id": "req-1", "run_id": runs[0]["id"]}],
          f"request not bound to the run it created: {bound}")
    check(f"run #{runs[0]['id']}" in engine_output(proc),
          "the replay did not name the run the request already created")


@test
def a_reused_request_id_with_different_input_is_refused():
    """
    An ID reused for a different submission is a conflict, not a replay and
    not a new run. The Move case is the one that matters: accepted as a
    replay, it would report the earlier Index as though the Move had run;
    accepted as new, it would execute under an ID bound to other work. The
    --force-rehash case pins that flags outside the settings store are part
    of what a request means.
    """
    case = new_case("request_conflict")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case, "--request-id", "req-1")
    before = src_files(case)

    proc = run_engine(case, "--move", "--request-id", "req-1", expect_rc=EXIT_REQUEST_CONFLICT)
    check("different submission" in engine_output(proc), "the conflict was not reported as one")
    check(src_files(case) == before, f"a conflicting request moved files: {src_files(case)}")
    check(not (case / "dest").exists(), "a conflicting request wrote to the destination")

    run_engine(case, "--force-rehash", "--request-id", "req-1", expect_rc=EXIT_REQUEST_CONFLICT)

    runs = rows(case, "SELECT mode FROM runs")
    check(runs == [{"mode": "INDEX"}], f"a conflicting request created a run: {runs}")


@test
def a_replayed_interrupted_request_is_reported_not_rerun():
    """
    The lost-response case: a request's run was killed, and the same request
    arrives again. It must not restart — resubmission is always explicit — and
    it must not claim the run is still going. Settling the dead run belongs to
    the next run that does real work, so the replay leaves the row alone.
    """
    case = new_case("request_interrupted")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case, "--request-id", "req-1")
    # The state an uncatchable kill leaves: the run row never finalized.
    conn = db(case)
    conn.execute("UPDATE runs SET status = 'Running', ended_at = NULL")
    conn.commit()
    conn.close()

    proc = run_engine(case, "--request-id", "req-1", expect_rc=EXIT_REQUEST_ALREADY_ACCEPTED)
    check("did not finish" in engine_output(proc),
          "a replay of a dead run did not say it was interrupted")
    check(rows(case, "SELECT status FROM runs") == [{"status": "Running"}],
          "the replay settled the dead run itself instead of leaving it to reconciliation")

    run_engine(case)
    statuses = [r["status"] for r in rows(case, "SELECT status FROM runs ORDER BY id")]
    check(statuses == ["Interrupted", "Completed"],
          f"the next real run did not reconcile the interrupted one: {statuses}")


# ------------------------------------------------------------ run lifecycle

def _run_main_in_process(case, move_or_copy_result, *extra):
    """Drives main() in-process with the transfer phase replaced by a stand-in
    that finishes its work and THEN receives a cancel — the window a subprocess
    cannot hit on purpose, between the last file and the run settling. The
    source is empty, so the scan's pool never starts a worker."""
    engine = _load_engine()

    def finished_then_cancelled(*_):
        engine.cancel_requested.set()
        return move_or_copy_result

    engine._run_move_or_copy = finished_then_cancelled
    saved = sys.argv
    sys.argv = ["ns-engine.py", "--source", str(case / "src"), "--dest", str(case / "dest"),
                "--base", str(case / "appdata"), "--cache", str(case / "cache"),
                "--backups", str(case / "backups"), *extra]
    try:
        engine.main()
        return 0
    except SystemExit as exc:
        return exc.code or 0
    finally:
        sys.argv = saved
        # main() registered these; the harness's own Ctrl-C must work again.
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.default_int_handler)


@test
def a_cancel_during_the_scan_ends_cancelled():
    """
    The scan phase settles its own cancellation. Pinned because a blanket
    end-of-run relabel used to claim this job, and removing it must not leave
    a cancelled scan reading Completed.
    """
    case = new_case("scan_cancel")
    total = 240
    for i in range(total):
        make_photo(case / "src" / f"IMG_{i:04d}.jpg", f"scan-{i}", date=None)
    proc = spawn_engine(case, "--workers", "1")
    deadline = time.time() + 60
    db_file = case / "appdata" / "db" / "ns_sqlite.db"
    while time.time() < deadline:
        try:
            if db_file.exists() and rows(case, "SELECT COUNT(*) c FROM photos")[0]["c"] > 0:
                break
        except sqlite3.OperationalError:
            pass  # schema not created yet
        time.sleep(0.05)
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=180)

    indexed = rows(case, "SELECT COUNT(*) c FROM photos")[0]["c"]
    if indexed == total:
        raise Fail("SKIP: the scan finished before SIGTERM landed — raise the file count")
    status = rows(case, "SELECT status FROM runs")[0]["status"]
    check((proc.returncode, status) == (0, "Cancelled"),
          f"a scan cancelled after {indexed} of {total} files ended {status}, exit {proc.returncode}")


@test
def a_cancel_after_the_work_finished_does_not_relabel_the_outcome():
    """
    A cancel landing after the last file does not make the job Cancelled: the
    user sees what actually happened (webui-spec 4.1). Worse, a job-level
    failure relabelled Cancelled exits 0 and disappears as an error.
    """
    case = new_case("late_cancel_completed")
    rc = _run_main_in_process(case, "Completed", "--copy")
    statuses = [r["status"] for r in rows(case, "SELECT status FROM runs")]
    check((rc, statuses) == (0, ["Completed"]),
          f"a job that finished before the cancel landed was recorded {statuses}, exit {rc}")

    case = new_case("late_cancel_failed")
    rc = _run_main_in_process(case, "Failed", "--copy")
    statuses = [r["status"] for r in rows(case, "SELECT status FROM runs")]
    check((rc, statuses) == (1, ["Failed"]),
          f"a failed job hit by a late cancel was recorded {statuses}, exit {rc}")


@test
def a_cancel_is_recorded_as_cancelling_before_the_run_settles():
    """
    Cancelling is visible while the current file finishes, so the UI can say the
    request was accepted without claiming it took effect. Written by a watcher
    thread, since a signal handler may interrupt the main thread mid-transaction.
    """
    case = new_case("cancelling_state")
    engine = _load_engine()
    db_path = case / "appdata" / "ns.db"
    engine.init_database(str(db_path))
    run_id, _ = engine.start_run(str(db_path), "MOVE", "/s", "/d", None)
    with contextlib.closing(engine.get_db_connection(str(db_path))) as conn:
        engine.ns_db.transition_run(conn, run_id, "Running")
    watcher = threading.Thread(target=engine.watch_for_cancellation, args=(str(db_path), run_id))
    watcher.start()
    engine.cancel_requested.set()
    watcher.join(timeout=10)
    check(not watcher.is_alive(), "the cancellation watcher did not finish")
    status = lambda: sqlite3.connect(db_path).execute("SELECT status FROM runs").fetchone()[0]
    check(status() == "Cancelling", f"a received cancel was recorded as {status()}")
    engine.finish_run(str(db_path), run_id, "Cancelled")
    check(status() == "Cancelled", f"a cancelling run settled as {status()}")


@test
def every_catalog_timestamp_carries_its_offset():
    """
    Application event times are timezone-aware UTC (engine-spec 4.3). One row
    mixing a zoned start with a naive end cannot give a duration — Python
    refuses to subtract them, and read as the same zone they are off by the
    host's UTC offset. Covers each writer: run start and finish, and an
    operation settled after its intent. An Interrupted run has no end time to
    check; see sigkill_during_move_is_reconciled_and_loses_nothing.
    """
    from datetime import datetime
    case = new_case("utc_timestamps")
    make_photo(case / "src" / "a.jpg", "a")
    make_photo(case / "src" / "dupe.jpg", "a")
    run_engine(case)
    run_engine(case, "--move")

    stamps = [("runs.started_at", r["started_at"]) for r in rows(case, "SELECT started_at FROM runs")]
    stamps += [("runs.ended_at", r["ended_at"]) for r in rows(case, "SELECT ended_at FROM runs")]
    stamps += [("operations.timestamp", r["timestamp"])
               for r in rows(case, "SELECT timestamp FROM operations")]
    naive = [(col, v) for col, v in stamps if v is None or datetime.fromisoformat(v).tzinfo is None]
    check(not naive, f"timestamps without an offset: {naive}")


# ------------------------------------------------------------ catalog backups

def backups_of(case):
    return rows(case, "SELECT t.trigger_kind, t.related_run_id, t.outcome, t.error_category, "
                      "a.relative_filename, a.availability FROM backup_attempts t "
                      "LEFT JOIN backup_artifacts a USING(attempt_id) ORDER BY t.attempt_id")


def backup_files(case):
    return sorted(p.name for p in (case / "backups").iterdir())


@test
def a_job_that_records_changes_is_backed_up_after_it_settles():
    """
    One verified, self-contained snapshot after the job, holding the run's
    final status. Self-contained means no -wal/-shm beside it: the manual
    restore instructions forbid companion files travelling with a backup.
    An unchanged re-Index records nothing and so gets no backup.
    """
    case = new_case("backup_post_job")
    make_photo(case / "src" / "a.jpg", "a")
    make_photo(case / "src" / "b.jpg", "b")
    run_engine(case)

    got = backups_of(case)
    check(len(got) == 1 and got[0]["trigger_kind"] == "post_job" and got[0]["related_run_id"] == 1
          and got[0]["outcome"] == "succeeded" and got[0]["availability"] == "present",
          f"expected one successful post-job backup of run 1, got {got}")
    check(backup_files(case) == [got[0]["relative_filename"]],
          f"backup storage holds more than the one backup: {backup_files(case)}")

    snap = sqlite3.connect(case / "backups" / got[0]["relative_filename"])
    try:
        check(snap.execute("PRAGMA journal_mode").fetchone()[0] == "delete",
              "the backup is still in WAL mode and would grow companions when opened")
        check(snap.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 2,
              "the backup does not hold the catalogued photos")
        check(snap.execute("SELECT status FROM runs WHERE id = 1").fetchone()[0] == "Completed",
              "the backup was taken before the run settled")
        # Taken while its own attempt was in flight; the copy must not come back
        # from a restore looking like an interrupted backup.
        check(snap.execute("SELECT outcome FROM backup_attempts").fetchone()[0] == "succeeded",
              "a restored backup would record its own attempt as unfinished")
    finally:
        snap.close()

    run_engine(case)
    check(len(backups_of(case)) == 1, "an Index that recorded nothing was backed up")

    # A repeated Copy records only Skipped rows. Backing that up would let
    # no-op runs push meaningful backups out of retention.
    run_engine(case, "--copy")
    check(len(backups_of(case)) == 2, "a Copy that delivered files was not backed up")
    run_engine(case, "--copy")
    check(len(backups_of(case)) == 2, "a repeated Copy that changed nothing was backed up")


@test
def backup_storage_problems_are_recorded_and_never_fail_the_job():
    """
    Missing storage and storage overlapping the catalog both fail the backup,
    recorded with a reason. Neither falls back to another location, and
    neither changes the job's result.
    """
    case = new_case("backup_storage_missing")
    make_photo(case / "src" / "a.jpg", "a")
    (case / "backups").rmdir()
    run_engine(case)
    check(rows(case, "SELECT status FROM runs")[0]["status"] == "Completed",
          "a failed backup changed the job's result")
    got = backups_of(case)
    check([(g["outcome"], g["error_category"]) for g in got] == [("failed", "storage_unavailable")],
          f"missing backup storage was not recorded as such: {got}")
    check(not (case / "backups").exists(), "the engine created backup storage it was not given")

    case = new_case("backup_storage_overlap")
    make_photo(case / "src" / "a.jpg", "a")
    inside = case / "appdata" / "backups"
    inside.mkdir()
    run_engine(case, "--backups", inside)
    got = backups_of(case)
    check([(g["outcome"], g["error_category"]) for g in got] == [("failed", "storage_overlaps_appdata")],
          f"backup storage inside the catalog's folder was not refused: {got}")
    check(list(inside.iterdir()) == [], "a backup was written inside the thing it backs up")


@test
def an_unmounted_container_backups_folder_is_refused():
    """
    The image creates /backups as a mount point. Left unmounted, backups would
    land in the container's own layer and disappear with it, which is the
    silent fallback the spec forbids, so the attempt fails and says why.
    """
    if not Path("/backups").is_dir() or os.path.ismount("/backups"):
        raise Fail("SKIP: needs the image's own unmounted /backups; run inside the container")
    case = new_case("backup_not_mounted")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case, "--backups", "/backups")
    got = backups_of(case)
    check([(g["outcome"], g["error_category"]) for g in got] == [("failed", "storage_not_mounted")],
          f"an unmounted /backups was used anyway: {got}")
    check(not any(Path("/backups").glob("ns-catalog-*")), "a backup was written to the container layer")


@test
def backup_now_is_manual_and_refused_while_a_job_holds_the_lock():
    """
    --backup-now writes one manual backup and exits 0; a failure exits 1. It
    takes the engine lock, so it is refused while a job runs and records
    nothing, rather than snapshotting a catalog halfway through a job.
    """
    import fcntl
    case = new_case("backup_now")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case, "--no-thumbnails")
    run_engine(case, "--backup-now")
    check([g["trigger_kind"] for g in backups_of(case)] == ["post_job", "manual"],
          f"expected a post-job then a manual backup, got {backups_of(case)}")

    with open(case / "appdata" / "engine.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_engine(case, "--backup-now", expect_rc=1)
    check(len(backups_of(case)) == 2, "a backup was attempted while another process held the lock")

    shutil.rmtree(case / "backups")
    run_engine(case, "--backup-now", expect_rc=1)
    check(backups_of(case)[-1]["error_category"] == "storage_unavailable",
          "a failed manual backup did not record why")


@test
def retention_prunes_only_automatic_backups_and_only_after_a_success():
    """
    With a limit of 2, the third automatic backup removes the oldest one: its
    file goes, and its record stays, marked pruned rather than missing. The
    manual backup is untouched however many automatic ones follow.
    """
    import ns_db
    case = new_case("backup_retention")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case)
    conn = ns_db.connect(case / "appdata" / "db" / "ns_sqlite.db")
    ns_db.save_settings(conn, {"backup_retention": 2}, expected_revisions={"backup_retention": 0})
    conn.close()
    run_engine(case, "--backup-now")
    for i in range(3):
        make_photo(case / "src" / f"new{i}.jpg", f"new{i}")
        run_engine(case)

    got = backups_of(case)
    states = [(g["trigger_kind"], g["availability"]) for g in got]
    check(states == [("post_job", "pruned"), ("manual", "present"), ("post_job", "pruned"),
                     ("post_job", "present"), ("post_job", "present")],
          f"retention kept the wrong backups: {states}")
    present = sorted(g["relative_filename"] for g in got if g["availability"] == "present")
    check(backup_files(case) == present, f"files on disk {backup_files(case)} != recorded {present}")


@test
def an_interrupted_backup_is_settled_by_the_next_run():
    """
    A backup killed partway leaves an attempt with no outcome and a partial
    file. Under the lock nothing can still be writing it, so the next run
    records it interrupted, removes the partial, and does not retry it.
    """
    case = new_case("backup_interrupted")
    make_photo(case / "src" / "a.jpg", "a")
    run_engine(case)
    conn = db(case)
    conn.execute("INSERT INTO backup_attempts(trigger_kind, related_run_id, started_at) "
                 "VALUES ('post_job', 1, '2026-01-01T00:00:00+00:00')")
    conn.commit()
    conn.close()
    partial = case / "backups" / "ns-catalog-20260101T000000Z-000002-post_job.db.partial"
    partial.write_bytes(b"torn")

    run_engine(case)
    got = backups_of(case)
    check(got[1]["outcome"] == "interrupted", f"the unfinished attempt was recorded {got[1]['outcome']}")
    check(not partial.exists(), "the partial backup file was left behind")
    check(len(got) == 2, "the interrupted backup was retried automatically")


def main():
    global ENGINE, WORKSPACE, VERBOSE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", default=str(Path(__file__).resolve().parent.parent / "ns-engine.py"))
    ap.add_argument("--keep", action="store_true", help="leave the workspace on disk")
    ap.add_argument("--filter", default="", help="only run tests whose name contains this")
    ap.add_argument("-v", "--verbose", action="store_true", help="show engine output")
    args = ap.parse_args()

    ENGINE = Path(args.engine).resolve()
    VERBOSE = args.verbose
    if not ENGINE.exists():
        print(f"engine not found: {ENGINE}", file=sys.stderr)
        return 2

    for tool, hint in (("exiftool", "apt install libimage-exiftool-perl"),):
        if not shutil.which(tool):
            print(f"required tool '{tool}' not on PATH ({hint})", file=sys.stderr)
            return 2
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("Pillow is required to generate test images (pip install Pillow)", file=sys.stderr)
        return 2

    WORKSPACE = Path(tempfile.mkdtemp(prefix="ns-smoke-"))
    print(f"engine    : {ENGINE}")
    print(f"workspace : {WORKSPACE}\n")

    selected = [t for t in RESULTS if args.filter in t.__name__]
    if not selected:
        # A typo'd filter used to print "0 passed, 0 failed" and exit 0 —
        # indistinguishable from success to anything reading the exit code.
        print(f"no test name contains {args.filter!r}", file=sys.stderr)
        shutil.rmtree(WORKSPACE, ignore_errors=True)
        return 2
    passed = failed = skipped = 0
    failures = []

    for fn in selected:
        label = fn.__name__.replace("_", " ")
        print(f"  {label} ... ", end="", flush=True)
        started = time.time()
        try:
            fn()
        except Fail as e:
            if str(e).startswith("SKIP:"):
                skipped += 1
                print(f"SKIP ({str(e)[6:]})")
                continue
            failed += 1
            failures.append((fn.__name__, str(e)))
            print(f"FAIL  ({time.time()-started:.1f}s)")
        except Exception as e:
            failed += 1
            failures.append((fn.__name__, f"{type(e).__name__}: {e}"))
            print(f"ERROR ({time.time()-started:.1f}s)")
        else:
            passed += 1
            print(f"ok    ({time.time()-started:.1f}s)")

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    if failures:
        print("\nfailures:")
        for name, msg in failures:
            print(f"\n  {name}:")
            for line in msg.splitlines():
                print(f"    {line}")

    if args.keep or failures:
        print(f"\nworkspace kept for inspection: {WORKSPACE}")
    else:
        shutil.rmtree(WORKSPACE, ignore_errors=True)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
