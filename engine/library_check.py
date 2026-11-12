"""Check library (engine-spec 9.2, webui-spec 7.6): the library walk, what an unknown file
is from its content, where a missing photo's content still is, and the report the web UI
reads. Reads only; maintenance.check_destination runs it as a job."""

import collections
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from engine.ns_db import RAW_EXTENSIONS, RunStatus, SUPPORTED_EXTENSIONS
from engine import constants, durable, fileinfo, metadata_relocate, ns_db, ns_similarity, relocate

# Bytes read from the start of a file to name its format.
HEAD_BYTES = 16

# Leading bytes of each photo format, as the `file` command's magic database reads them
# (github.com/file/file, magic/Magdir: jpeg, images, riff, animation). ISO Media brands
# follow `ftyp` at offset 4. Panasonic RW2 and Canon CR3 have no entry there, so a RAW
# file is never judged by its signature alone: decoding decides.
_PREFIXES = ((b"\xff\xd8\xff", "jpeg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"GIF8", "gif"), (b"BM", "bmp"),
             (b"MM\x00\x2a", "tiff"), (b"II\x2a\x00", "tiff"), (b"FUJIFILMCCD-RAW", "raw"),
             (b"II\x1a\x00\x00\x00HEAPCCDR", "raw"), (b"\x00MRM", "raw"), (b"IIRO", "raw"), (b"IIRS", "raw"),
             (b"FOVb", "raw"))
_BRANDS = {b"mif1": "heif", b"msf1": "heif", b"heic": "heif", b"heix": "heif", b"hevc": "heif",
           b"avif": "avif", b"avis": "avif"}
FORMAT_NAMES = {"jpeg": "JPEG", "png": "PNG", "gif": "GIF", "bmp": "BMP", "webp": "WebP", "tiff": "TIFF",
                "heif": "HEIF", "avif": "AVIF", "raw": "camera RAW"}
_EXPECTED = {**{e: {"jpeg"} for e in (".jpg", ".jpeg", ".jpe", ".jfif")}, ".png": {"png"}, ".gif": {"gif"},
             ".bmp": {"bmp"}, ".webp": {"webp"}, ".tif": {"tiff"}, ".tiff": {"tiff"},
             **{e: {"heif", "avif"} for e in (".heic", ".heif", ".avif")}}
_RAW_FORMATS = {"tiff", "raw", "heif", None}

# Sidecars other programs leave beside a photo; counted on their photo, never warned about.
SIDECAR_EXTENSIONS = {".xmp", ".aae"}

# Other programs' housekeeping (decided 2026-11-02): counted in one line, never warned
# about. Microsoft documents desktop.ini as a hidden file that customises a folder
# (learn.microsoft.com, "How to Customize Folders with Desktop.ini"); the freedesktop
# Trash specification names "$topdir/.Trash-$uid" (specifications.freedesktop.org/trash).
# Any other name starting with a dot is hidden, which Index already skips.
_HOUSEKEEPING_FOLDERS = {"@eadir": "synology", "#recycle": "synology", "$recycle.bin": "windows"}
_HOUSEKEEPING_FILES = {".ds_store": "macos", "thumbs.db": "windows", "desktop.ini": "windows",
                       ".picasa.ini": "picasa"}


def file_format(head: bytes) -> Optional[str]:
    """The photo format a file's leading bytes show, or None."""
    for prefix, name in _PREFIXES:
        if head.startswith(prefix):
            return name
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[4:8] == b"ftyp":
        return _BRANDS.get(head[8:12])
    return None


def housekeeping(name: str, is_dir: bool) -> Optional[str]:
    """Which program's housekeeping an entry is, or None for an ordinary entry."""
    lower = name.lower()
    if is_dir and lower in _HOUSEKEEPING_FOLDERS:
        return _HOUSEKEEPING_FOLDERS[lower]
    if not is_dir and lower in _HOUSEKEEPING_FILES:
        return _HOUSEKEEPING_FILES[lower]
    if lower.startswith("._"):
        return "macos"
    if is_dir and lower.startswith(".trash-"):
        return "trash"
    return "hidden" if name.startswith(".") else None


def walk_library(root: Path, extensions: set, errors: list, on_directory=None):
    """Every file under `root`, sorted for the check: (photo-type paths, other paths,
    housekeeping counts by program, sidecar count). A housekeeping folder is counted
    file by file without being read; readdir's types mean no extra stat per entry."""
    photos, others = [], []
    counts = collections.Counter()
    sidecars = 0
    stack = [(str(root), None)]
    while stack:
        current, program = stack.pop()
        names, files = set(), []
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                        if not is_dir and not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError as exc:
                        errors.append((entry.path, f"{type(exc).__name__}: {exc}"))
                        continue
                    owner = program or housekeeping(entry.name, is_dir)
                    if is_dir:
                        stack.append((entry.path, owner))
                    elif owner:
                        counts[owner] += 1
                    else:
                        names.add(entry.name)
                        files.append(entry)
        except OSError as exc:
            errors.append((current, f"{type(exc).__name__}: {exc}"))
        stems = {os.path.splitext(n)[0] for n in names if os.path.splitext(n)[1].lower() not in SIDECAR_EXTENSIONS}
        for entry in files:
            base, ext = os.path.splitext(entry.name)
            ext = ext.lower()
            if ext in SIDECAR_EXTENSIONS and (base in names or base in stems):
                sidecars += 1
            elif ext in extensions:
                photos.append(entry.path)
            else:
                others.append(entry.path)
        if on_directory is not None:
            on_directory(len(photos), len(others))
    return photos, others, dict(counts), sidecars


def _read(path: str, whole: bool):
    """(leading bytes, sha1 or None) in one read of the file."""
    def read():
        fileinfo.require_plain_path(path)
        digest = hashlib.sha1()
        with open(path, "rb") as f:
            chunk = f.read(constants.SHA1_CHUNK_SIZE)
            head = chunk[:HEAD_BYTES]
            if not whole:
                return head, None
            while chunk:
                digest.update(chunk)
                chunk = f.read(constants.SHA1_CHUNK_SIZE)
        return head, digest.hexdigest()
    return durable.retry_io_operation(f"Read {path}", read)


def unknown_file(path: str, photo_type: bool) -> dict:
    """A file the catalog did not put in the library, named by its content. A photo type
    is read in full for its checksum and decoded; any other type only for its leading
    bytes, and in full only when those show a photo under the wrong name."""
    finding = {"path": path, "kind": "unknown", "outcome": "unknown"}
    ext = os.path.splitext(path)[1].lower()
    try:
        st = os.stat(path)
        finding.update(size=st.st_size, mtime=st.st_mtime)
        if st.st_size == 0:
            return dict(finding, file_kind="empty")
        head, sha1 = _read(path, photo_type)
        shown = file_format(head)
        if not photo_type:
            if shown is None:
                return dict(finding, file_kind="other_type" if ext else "unrecognised")
            head, sha1 = _read(path, True)
    except OSError as exc:
        return dict(finding, file_kind="unopenable", detail=unreadable_reason(exc))
    finding.update(observed_sha1=sha1, signature=shown)
    expected = _RAW_FORMATS if ext in RAW_EXTENSIONS else _EXPECTED.get(ext, set())
    if not photo_type or (shown is not None and shown not in expected):
        return dict(finding, file_kind="wrong_extension")
    if ext in SUPPORTED_EXTENSIONS and fileinfo.compute_phash(path) == "error":
        return dict(finding, file_kind="damaged", detail=fileinfo.image_decode_error(path))
    return dict(finding, file_kind="photo")


def look(path: str, recorded_phash: Optional[str]) -> Optional[str]:
    """Whether a changed file still looks like the photo it replaced (webui-spec 7.4's
    look-alike rule), or None when either picture cannot be compared."""
    if not ns_similarity.usable(recorded_phash):
        return None
    observed = fileinfo.compute_phash(path)
    if not ns_similarity.usable(observed):
        return None
    distance = bin(int(observed, 16) ^ int(recorded_phash, 16)).count("1")
    return "alike" if distance <= ns_similarity.MAX_DISTANCE else "different"


def gone_folder(path: str, library: Path, present: dict) -> Optional[str]:
    """The outermost folder of a missing file that is itself gone, below the library.
    `present` caches folder existence across the check."""
    gone = None
    folder = Path(path).parent
    while folder != library and library in folder.parents:
        key = str(folder)
        if key not in present:
            present[key] = folder.is_dir()
        if present[key]:
            break
        gone, folder = key, folder.parent
    return gone


def locate(conn, findings: list, rejects: Path, cancelled) -> None:
    """Where the content of each missing photo (and of a photo replaced by a different
    picture) still is: elsewhere in the library, in Rejects, or at a source path the
    catalog records for that content. Rejects is read only for files of a sought size."""
    wanted = {}
    for f in findings:
        # An unreadable photo's copy is named, so the user knows it is not lost (webui-spec 7.6).
        if f["kind"] in ("missing", "unreadable") or f.get("look") == "different":
            wanted.setdefault(f["expected_sha1"], []).append(f)
    if not wanted:
        return
    def found(sha1, where, path):
        for f in wanted.pop(sha1, []):
            f.update(found_in=where, found_path=path)
    for f in sorted((f for f in findings if f["kind"] == "unknown"), key=lambda f: f["path"]):
        if f.get("observed_sha1") in wanted:
            found(f["observed_sha1"], "library", f["path"])
    sizes = {}
    for sha1 in wanted:
        row = conn.execute("SELECT file_size FROM photos WHERE sha1_hash=? AND file_size IS NOT NULL LIMIT 1", (sha1,)).fetchone()
        if row:
            sizes.setdefault(row[0], set()).add(sha1)
    stack = [str(rejects)] if rejects.is_dir() else []
    while stack and wanted and not cancelled():
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in sorted(entries, key=lambda e: e.name):
                    if entry.name.startswith("."):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False) and wanted.keys() & sizes.get(entry.stat().st_size, set()):
                        sha1 = fileinfo.compute_sha1(entry.path)
                        if sha1 in wanted:
                            found(sha1, "rejects", entry.path)
        except OSError:
            continue
    for sha1 in list(wanted):
        if cancelled():
            return
        for (source,) in conn.execute("SELECT DISTINCT source_path FROM photos WHERE sha1_hash=? "
                                      "AND source_path IS NOT NULL ORDER BY id", (sha1,)):
            try:
                if os.path.isfile(source) and fileinfo.compute_sha1(source) == sha1:
                    found(sha1, "source", source)
                    break
            except OSError:
                continue


# What a check records for a rename the user made (webui-spec 7.6): shown in the
# photo's history and the check's Logs entry.
RENAME_NOTE = ("Renamed outside NegativeSpace: found by a library check, the same content, matched by its "
               "checksum, under a new name in the same folder.")


def renames(conn, findings: list) -> list:
    """Missing photos whose exact content is the one unknown file in their own folder
    under another name: renames the user made (engine-spec 9.2), as (missing finding,
    the file now holding it). A photo with a recorded sidecar is left to Repair, which
    moves the pair; content found more than once is ambiguous and left as findings."""
    holders = collections.Counter(f.get("observed_sha1") for f in findings if f["kind"] == "unknown")
    found = []
    for f in findings:
        if (f["kind"] == "missing" and f.get("found_in") == "library" and holders[f["expected_sha1"]] == 1
                and os.path.dirname(f["found_path"]) == os.path.dirname(f["path"])
                and metadata_relocate.current(conn, f["path"]) is None):
            found.append(f)
    return found


def record_renames(conn, run_id: int, found: list) -> int:
    """Records each rename as Rename would, in the caller's transaction: the photo and
    its file identity now name the new path, a Renamed operation of this check run
    holds both names, and the two findings it replaces are removed. No file is touched."""
    for f in found:
        old, new = f["path"], f["found_path"]
        file_id = (conn.execute("SELECT file_id FROM file_states WHERE current_path = ? AND location_role = "
                                "'destination' AND presence_state = 'present'", (old,)).fetchone() or [None])[0]
        op = ns_db.begin_operation(conn, run_id=run_id, photo_id=f["photo_id"], source_path=old, dest_path=new,
                                   kind="rename")
        relocate._record_rename(conn, op, old, new, file_id, detail={"found_by": "library_check", "matched": "sha1"})
        conn.execute("UPDATE operations SET error_message = ? WHERE id = ?", (RENAME_NOTE, op))
        conn.execute("DELETE FROM destination_findings WHERE run_id = ? AND path IN (?, ?)", (run_id, old, new))
    return len(found)


def start(conn, run_id: int, depth: str, library: Path) -> None:
    conn.execute("INSERT INTO library_checks(run_id, depth, library) VALUES (?, ?, ?)", (run_id, depth, str(library)))


def stop(conn, run_id: int, reason: str) -> None:
    conn.execute("UPDATE library_checks SET stopped=? WHERE run_id=?", (reason, run_id))


def add_count(conn, run_id: int, key: str, n: int) -> None:
    counts = json.loads(conn.execute("SELECT counts_json FROM library_checks WHERE run_id=?", (run_id,)).fetchone()[0])
    record_counts(conn, run_id, {**counts, key: counts.get(key, 0) + n})


def record_counts(conn, run_id: int, counts: dict) -> None:
    conn.execute("UPDATE library_checks SET counts_json=? WHERE run_id=?", (json.dumps(counts, sort_keys=True), run_id))


# --- The report the web UI reads -------------------------------------------------------

# How each finding reads, how serious it is, and what the user can do about it now
# (webui-spec 7.6). Tones: 'bad' is a photo lost or damaged, 'warn' something to fix or
# decide, 'quiet' only counted. A finding Repair fixes says what Repair does (engine/repair.py);
# the catalog-only answers are not built, so other advice names only what works today.
def unreadable_reason(exc: OSError) -> str:
    """Why a file can't be read, in plain words ("permission denied", "input/output
    error"), never the app's own path inside its container (webui-spec 7.6)."""
    return (exc.strerror or type(exc).__name__).lower()


def shown_path(path: Optional[str], library: Path) -> Optional[str]:
    """A path as the screens show it: relative to the library, or "Rejects/..." for one in
    Rejects, never the app's own path inside its container."""
    rejects = ns_db.rejects_root(library.parent)
    if path and Path(path).is_relative_to(library):
        return os.path.relpath(path, library)
    if path and Path(path).is_relative_to(rejects):
        return "Rejects/" + os.path.relpath(path, rejects)
    return path


def describe(f: dict, library: Path, catalogued: dict, moved_here: Optional[dict] = None) -> dict:
    moved_here = moved_here or {}
    rel = lambda p: shown_path(p, library)
    kind, file_kind, where = f["kind"], f.get("file_kind"), f.get("found_in")
    if kind == "missing" and where == "library" and os.path.dirname(f["found_path"]) == os.path.dirname(f["path"]):
        # A rename the check could not record: a delivered sidecar, or the content twice (renames).
        return {"finding": "moved", "tone": "warn", "what": f"Found under a new name in its own folder: {rel(f['found_path'])}.",
                "todo": "If it has an .xmp sidecar, rename that to match; if its content is in two files, keep one. "
                        "Then check the library again."}
    if kind == "missing" and where:
        what = {"library": f"Found at a different place in the Library: {rel(f['found_path'])}.",
                "rejects": f"Its file is in Rejects: {rel(f['found_path'])}.",
                "source": "Missing from the Library. A copy is still in the source."}[where]
        todo = {"library": "Repair moves it back to its date folder, keeping its name.",
                "rejects": "Repair moves it back from Rejects.",
                "source": "Repair copies it back from the source."}[where]
        return {"finding": "moved" if where == "library" else "missing", "tone": "warn", "what": what, "todo": todo}
    if kind == "missing":
        return {"finding": "missing", "tone": "bad",
                "what": "Missing from the Library, and no copy was found in the Library, Rejects or the source.",
                "todo": "If the original is still somewhere in your source, Index source finds it; then check the "
                        f"library again. If a backup has it, restore it to {rel(f['path'])}."}
    if kind == "changed" and f.get("look") == "different":
        return {"finding": "replaced", "tone": "warn" if where else "bad",
                "what": "A different picture is saved under this name. The photo NegativeSpace filed here is missing"
                        + (f"; a copy is {'in the source' if where == 'source' else 'at ' + rel(f['found_path'])}." if where else "."),
                "todo": "Restore the photo from a copy or backup, and keep the other picture under another name."}
    if kind == "changed":
        return {"finding": "changed", "tone": "warn",
                "what": "Changed by another program since NegativeSpace filed it"
                        + ("; it still looks like the same photo." if f.get("look") == "alike" else "."),
                "todo": "Nothing is lost if the change was intended. If not, restore the file from a backup."}
    if kind == "unreadable":
        copy = ("" if not where else " A copy is in the source, so the photo isn't lost." if where == "source"
                else f" A copy is at {rel(f['found_path'])}, so the photo isn't lost.")
        return {"finding": "unreadable", "tone": "bad", "what": f"Can't be read: {f.get('detail') or 'no reason given'}."
                + copy, "todo": "Check the file's permissions and the disk, then check the library again."}
    ext = os.path.splitext(f["path"])[1]
    if f["path"] in moved_here:
        source = moved_here[f["path"]]
        return {"finding": "moved_here", "tone": "quiet", "photo_id": source["photo_id"],
                "what": f"Photo #{source['photo_id']}, moved here from {rel(source['path'])}.", "todo": None}
    if f.get("observed_sha1") in catalogued:
        return {"finding": "extra_copy", "tone": "quiet", "photo_id": catalogued[f["observed_sha1"]],
                "what": f"An extra copy of photo #{catalogued[f['observed_sha1']]}.", "todo": None}
    return {
        "photo": {"finding": "unknown_photo", "tone": "warn",
                  "what": ("A photo" if ext.lower() in SUPPORTED_EXTENSIONS else f"A {ext.lower()} file")
                          + " NegativeSpace didn't put here.",
                  "todo": "To have NegativeSpace file it, move it into the source and Index it."},
        "wrong_extension": {"finding": "wrong_extension", "tone": "warn",
                            "what": f"Looks like a {FORMAT_NAMES.get(f.get('signature'), 'photo')} photo, but its name "
                                    + (f"doesn't end in a {FORMAT_NAMES.get(f.get('signature'), 'photo')} extension."
                                       if ext else "has no extension."),
                            "todo": "Rename it with the right extension."},
        "other_type": {"finding": "other_type", "tone": "quiet", "what": f"A {ext.lower()} file.", "todo": None},
        "unrecognised": {"finding": "unrecognised", "tone": "quiet", "what": "Unknown kind of file.", "todo": None},
        "empty": {"finding": "empty", "tone": "warn", "what": "Empty file, often a copy that didn't finish.",
                  "todo": "Delete it, or copy it again from where it came from."},
        "damaged": {"finding": "damaged", "tone": "warn", "what": "Damaged: can't be read as a photo.",
                    "todo": "Replace it from a backup, or delete it."},
        "unopenable": {"finding": "unopenable", "tone": "warn",
                       "what": f"NegativeSpace can't open it ({f.get('detail') or 'no reason given'}).",
                       "todo": "Check the file's permissions."},
    }[file_kind]


def _folders(findings: list, library: Path) -> list:
    """Whole missing folders, each one finding (webui-spec 7.6). A folder is moved when
    every photo in it was found again under one other folder with the same layout."""
    by_folder = collections.defaultdict(list)
    for f in findings:
        if f["kind"] == "missing" and f.get("gone_folder"):
            by_folder[f["gone_folder"]].append(f)
    groups = []
    for folder, members in sorted(by_folder.items()):
        targets = set()
        for f in members:
            inner = os.path.relpath(f["path"], folder)
            found = f.get("found_path") if f.get("found_in") == "library" else None
            targets.add(found[:-len(inner) - 1] if found and found.endswith(os.sep + inner) else None)
        moved_to = targets.pop() if len(targets) == 1 and None not in targets else None
        lost = sum(1 for f in members if not f.get("found_in"))
        groups.append({"folder": os.path.relpath(folder, library), "photos": len(members),
                       "moved_to": os.path.relpath(moved_to, library) if moved_to else None,
                       "tone": "bad" if lost else "warn", "lost": lost,
                       "paths": [f["path"] for f in members]})
    return groups


def latest(conn, *, completed=False):
    """The newest library check run, or the newest Completed one."""
    status = " AND r.status=?" if completed else ""
    return conn.execute("SELECT r.id FROM library_checks c JOIN runs r ON r.id=c.run_id "
                        f"WHERE 1{status} ORDER BY r.id DESC LIMIT 1",
                        (RunStatus.COMPLETED,) if completed else ()).fetchone()


def report(conn, run_id: int, *, findings=True) -> Optional[dict]:
    """One library check as the web UI shows it: the run, its counts and tone, whole
    folders, other programs' files, and (with `findings`) every finding described."""
    row = conn.execute("SELECT c.depth, c.stopped, c.counts_json, r.status, r.started_at, r.ended_at, c.library "
                       "FROM library_checks c JOIN runs r ON r.id=c.run_id WHERE c.run_id=?", (run_id,)).fetchone()
    if row is None:
        return None
    library = Path(row[6])
    rows = ns_db.read_destination_check(conn, run_id)["findings"]
    sha1s = {f["observed_sha1"] for f in rows if f["kind"] == "unknown" and f.get("observed_sha1")}
    catalogued = {}
    for sha1 in sha1s:
        hit = conn.execute(f"SELECT id FROM photos WHERE sha1_hash=? AND status IN "
                           f"({ns_db.sql_values(ns_db.DELIVERED_STATUSES)}) ORDER BY id LIMIT 1", (sha1,)).fetchone()
        if hit:
            catalogued[sha1] = hit[0]
    moved_here = {f["found_path"]: f for f in rows if f.get("found_in") == "library"}
    # The Repair job that fixed a finding: listed, marked, and no longer counted.
    settled = sorted({f["settled_by"] for f in rows if f.get("settled_by")})
    repaired = dict(conn.execute(f"SELECT id, run_id FROM operations WHERE id IN ({','.join('?' * len(settled))})",
                                 settled).fetchall()) if settled else {}
    groups = _folders(rows, library)
    grouped = {p for g in groups for p in g["paths"]}
    repaired_paths = {f["path"]: f.get("settled_by") for f in rows}
    described = []
    for f in rows:
        d = describe(f, library, catalogued, moved_here)
        described.append({**{k: f[k] for k in ("path", "kind", "photo_id", "size", "found_in", "found_path")},
                          "repaired_by": repaired.get(f["settled_by"]),
                          "relative": os.path.relpath(f["path"], library) if Path(f["path"]).is_relative_to(library) else f["path"],
                          "checksum": f.get("observed_sha1") or f.get("expected_sha1"),
                          "folder": next((g["folder"] for g in groups if f["path"] in g["paths"]), None), **d})
    # A moved photo's new file is the other half of its "moved" finding: exported, not
    # listed or counted again.
    loose = [d for d in described if d["path"] not in grouped and d["finding"] != "moved_here"]
    open_ = [d for d in described if not d["repaired_by"]]
    open_loose = [d for d in loose if not d["repaired_by"]]
    counts = json.loads(row[2])
    other_types = collections.Counter(os.path.splitext(d["path"])[1].lower() or "(none)"
                                      for d in described if d["finding"] in ("other_type", "unrecognised"))
    lost_photos = sum(1 for d in open_ if d["finding"] in ("missing", "replaced") and d["tone"] == "bad")
    damaged = sum(1 for d in open_ if d["finding"] == "unreadable")
    open_groups = [g for g in groups if not all(repaired_paths.get(p) for p in g["paths"])]
    attention = (sum(1 for d in open_loose if d["tone"] == "warn") + sum(1 for g in open_groups if g["tone"] == "warn"))
    progress = {p["phase"]: p for p in ns_db.read_progress(conn, run_id)}.get("checking_destination")
    result = {"run_id": run_id, "depth": row[0], "stopped": row[1], "status": row[3], "started_at": row[4],
              "ended_at": row[5], "intact": (progress or {}).get("counts", {}).get("ok", 0),
              "progress": {"done": progress["done"], "total": progress["total"]} if progress else None,
              "lost": lost_photos, "damaged": damaged, "attention": attention, "found": len(loose) + len(groups),
              "repaired": sum(1 for d in described if d["repaired_by"] and d["finding"] != "moved_here"),
              "tone": "bad" if lost_photos or damaged else "warn" if attention else "plain",
              "folders": [{k: v for k, v in g.items() if k != "paths"} for g in groups],
              "housekeeping": {k: v for k, v in counts.items() if k not in ("sidecars", "renamed")},
              "sidecars": counts.get("sidecars", 0), "other_types": dict(sorted(other_types.items())),
              "renamed": [{"photo_id": pid, "old": os.path.relpath(old, library), "new": os.path.relpath(new, library)}
                          for pid, old, new in conn.execute(
                              "SELECT photo_id, source_path, dest_path FROM operations WHERE run_id = ? AND status = ? "
                              "ORDER BY id", (run_id, ns_db.OPERATION_RENAMED))]}
    if findings:
        order = {"bad": 0, "warn": 1, "quiet": 2}
        result["findings"] = sorted(described, key=lambda d: (order[d["tone"]], d["relative"]))
    return result


def photo_reason(conn, photo_id: int) -> Optional[dict]:
    """The Library check reason for one photo (webui-spec 7.6): what the latest completed
    check found, while the photo is still where and what the check saw."""
    row = conn.execute(f"SELECT f.* FROM destination_findings f JOIN photos p ON p.id=f.photo_id "
                       f"WHERE f.run_id=({LATEST_COMPLETED_SQL}) AND f.photo_id=? AND f.path=p.dest_path "
                       f"AND f.expected_sha1 IS p.sha1_hash AND f.settled_by IS NULL", (photo_id,)).fetchone()
    if row is None:
        return None
    f = dict(zip([d[0] for d in conn.execute("SELECT * FROM destination_findings LIMIT 0").description], row))
    library = Path(conn.execute("SELECT library FROM library_checks WHERE run_id=?", (f["run_id"],)).fetchone()[0])
    return {"run_id": f["run_id"], **describe(f, library, {})}


LATEST_COMPLETED_SQL = (f"SELECT MAX(c.run_id) FROM library_checks c JOIN runs r ON r.id=c.run_id "
                        f"WHERE r.status='{RunStatus.COMPLETED}'")


def pending_sql() -> str:
    """Library photos the latest completed check found missing, changed or unreadable,
    still at the path and with the content it checked, and not repaired since; a later
    check, Repair or another change by NegativeSpace clears the reason."""
    return (f"p.status IN ({ns_db.sql_values(ns_db.DELIVERED_STATUSES)}) AND EXISTS (SELECT 1 FROM "
            f"destination_findings f WHERE f.run_id=({LATEST_COMPLETED_SQL}) AND f.photo_id=p.id "
            f"AND f.path=p.dest_path AND f.expected_sha1 IS p.sha1_hash AND f.settled_by IS NULL)")
