"""A photo's lineage (webui-spec 6.3): every file it has been, back to its source."""

from pathlib import Path
from typing import Optional

from . import catalog


# --- A photo's lineage (webui-spec 6.3) ----------------------------------------

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
        tree = (f"WITH RECURSIVE tree(file_id) AS (SELECT file_id FROM photo_files WHERE photo_id IN ({marks}) "
                "UNION SELECT o.file_id FROM file_origins o JOIN tree t ON o.origin_file_id = t.file_id) ")
        files = [dict(r) for r in conn.execute(
            tree + "SELECT t.file_id, o.origin_file_id, o.kind AS origin_kind, s.current_path AS path, "
            "s.location_role AS role, s.presence_state AS presence, s.sha1_hash, snap.file_size, "
            "snap.source_path AS indexed_path, f.created_at, pf.photo_id, ph.status AS photo_status "
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
        # The jobs this photo was chosen for by hand, whatever each then did with it.
        selected_by = [dict(r) for r in conn.execute(
            "SELECT r.id AS run_id, r.mode, r.status, r.started_at FROM run_selections s "
            "JOIN runs r ON r.id = s.run_id WHERE s.photo_id = ? ORDER BY r.id", (photo_id,))]
    by_op = {}
    for r in links:
        by_op.setdefault(r["operation_id"], []).append({"file_id": r["file_id"], "role": r["role"]})
    size = next((f["file_size"] for f in files if f["file_size"] is not None), None)
    for f in files:
        # A copy is byte-identical to its origin (verified when made), so it shares its size.
        f["file_size"] = f["file_size"] if f["file_size"] is not None else size
        f["matches"] = bool(photo["sha1_hash"]) and f["sha1_hash"] == photo["sha1_hash"]
    for op in operations:
        op["recovery"] = bool(op["recovery"])
        op["files"] = by_op.get(op["id"], [])
    return {"photo_id": photo_id, "sha1": photo["sha1_hash"], "photos": photos, "files": files, "operations": operations,
            "selected_by": selected_by}
