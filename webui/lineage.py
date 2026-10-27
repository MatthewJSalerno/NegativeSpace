"""A photo's lineage (webui-spec 6.3): every file it has been, back to its source."""

from pathlib import Path
from typing import Optional

from . import catalog, operation_actions
from engine import earlier_versions
from engine.ns_db import REJECTED_STATUSES


# --- A photo's lineage (webui-spec 6.3) ----------------------------------------

def file_tree(photo_query):
    """Internal SQL only: retain both ancestries after confirmed consolidation."""
    return ("WITH RECURSIVE tree(file_id) AS (SELECT file_id FROM photo_files WHERE photo_id IN (" + photo_query + ") "
            "UNION SELECT o.file_id FROM file_origins o JOIN tree t ON o.origin_file_id=t.file_id "
            "UNION SELECT linked.file_id FROM tree t JOIN operation_files seed ON seed.file_id=t.file_id "
            "JOIN operation_files linked ON linked.operation_id=seed.operation_id "
            "WHERE EXISTS(SELECT 1 FROM operation_events e WHERE e.operation_id=seed.operation_id "
            "AND e.step='metadata_consolidation_verified')) ")


def photo_lineage(db_path: Path, photo_id: int) -> Optional[dict]:
    """Everything the catalog records about a photo's files, for the lineage tree: its
    source file and every file descended from it (file_origins), the same for each exact
    duplicate, and every operation that touched any of them with the role each file
    played. The engine proves this assembles for every file in every status (TODO.md
    claim 11); this only reads it."""
    with catalog.connect(db_path) as conn:
        photo = conn.execute("SELECT id, sha1_hash, status FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if photo is None:
            return None
        photos = [photo_id] + ([r[0] for r in conn.execute(
            "SELECT id FROM photos WHERE sha1_hash = ? AND id != ? ORDER BY id", (photo["sha1_hash"], photo_id))]
            if photo["sha1_hash"] else [])
        marks = ",".join("?" * len(photos))
        tree = file_tree(marks)
        files = [dict(r) for r in conn.execute(
            tree + "SELECT t.file_id, o.origin_file_id, o.kind AS origin_kind, s.current_path AS path, "
            "s.location_role AS role, s.presence_state AS presence, s.sha1_hash, snap.file_size, "
            "snap.source_path AS indexed_path, snap.sha1_hash AS indexed_sha1, f.created_at, f.created_run_id, pf.photo_id, ph.status AS photo_status "
            "FROM tree t JOIN files f ON f.file_id = t.file_id "
            "LEFT JOIN file_origins o ON o.file_id = t.file_id LEFT JOIN file_states s ON s.file_id = t.file_id "
            "LEFT JOIN source_snapshots snap ON snap.file_id = t.file_id "
            "LEFT JOIN photo_files pf ON pf.file_id = t.file_id LEFT JOIN photos ph ON ph.id = pf.photo_id "
            "ORDER BY t.file_id", photos)]
        links = conn.execute(
            tree + "SELECT of.operation_id, of.file_id, of.role FROM operation_files of JOIN tree t USING(file_id) "
            "ORDER BY of.operation_id", photos).fetchall()
        op_ids = sorted({r["operation_id"] for r in links})
        operations = [dict(r) for r in conn.execute(
            f"SELECT o.id, o.run_id, r.mode, {catalog._OP_STATUS} AS status, o.timestamp, o.error_message, o.photo_id, "
            "o.source_path, o.dest_path, (o.reconciles_operation_id IS NOT NULL) AS recovery "
            f"FROM operations o LEFT JOIN runs r ON r.id = o.run_id WHERE o.id IN ({','.join('?' * len(op_ids))}) "
            "ORDER BY o.id", op_ids)] if op_ids else []
        operation_actions.annotate(conn, operations)
        # Use the survivor's name at the join, not a name it may have acquired later.
        consolidated = [op["id"] for op in operations if op["consolidated_into"] is not None]
        retained_paths = {}
        for offset in range(0, len(consolidated), 500):
            batch = consolidated[offset:offset + 500]
            retained_paths.update(conn.execute(
                "SELECT operation_id,json_extract(detail_json,'$.retained_path') FROM operation_events "
                "WHERE step='metadata_consolidated' AND operation_id IN (" + ','.join('?' * len(batch)) + ")", batch))
        for op in operations:
            op["consolidated_path"] = retained_paths.get(op["id"])
        # Resolve places through the small set of participating photo IDs. Looking
        # up each path in photos would scan the whole catalog once per file.
        owner_ids = sorted(set(photos) | {op["photo_id"] for op in operations if op["photo_id"] is not None})
        places = {}
        for offset in range(0, len(owner_ids), 500):
            batch = owner_ids[offset:offset + 500]
            for path, status in conn.execute(
                    "SELECT dest_path, status FROM photos WHERE id IN (" + ",".join("?" * len(batch)) + ")", batch):
                if path and (path not in places or status in REJECTED_STATUSES):
                    # Duplicate rows can retain the same destination without carrying
                    # its owner's curation status. They must not hide a recorded Reject.
                    places[path] = "rejects" if status in REJECTED_STATUSES else "library"
        # The jobs this photo was chosen for by hand, whatever each then did with it.
        selected_by = [dict(r) for r in conn.execute(
            "SELECT r.id AS run_id, r.mode, r.status, r.started_at FROM run_selections s "
            "JOIN runs r ON r.id = s.run_id WHERE s.photo_id = ? ORDER BY r.id", (photo_id,))]
        # Version links name the other photo; each keeps its own history (engine-spec 10).
        linked = earlier_versions.details(conn, photo_id)
        earlier = linked["earlier_version"]
        versions = {"version_of": earlier and dict(earlier["version_of"], found_at=earlier["found_at"], state=earlier["state"]),
                    "earlier_versions": linked["earlier_versions"]}
    by_op = {}
    for r in links:
        by_op.setdefault(r["operation_id"], []).append({"file_id": r["file_id"], "role": r["role"]})
    size = next((f["file_size"] for f in files if f["file_size"] is not None), None)
    for f in files:
        f["place"] = "source" if f["role"] == "source" else places.get(f["path"])
        # A copy is byte-identical to its origin (verified when made), so it shares its size.
        f["file_size"] = f["file_size"] if f["file_size"] is not None else size
        f["matches"] = bool(photo["sha1_hash"]) and f["sha1_hash"] == photo["sha1_hash"]
    for op in operations:
        op["recovery"] = bool(op["recovery"])
        op["files"] = by_op.get(op["id"], [])
    return {"photo_id": photo_id, "sha1": photo["sha1_hash"], "photos": photos, "files": files, "operations": operations,
            "selected_by": selected_by, "versions": versions}
