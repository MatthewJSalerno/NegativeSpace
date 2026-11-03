"""Read: source coverage rules shared with the folder tree and transfer preview."""
import json
import posixpath

def coverage(conn, source: str):
    """When each part of this source was last read in full: the end of the latest Completed
    Index of the whole source, and of each folder an Index was scoped to. A cancelled,
    failed or interrupted Index, or one scoped to selected photos, may not have read a whole
    folder, so it does not count. Completed runs with run-level failures also leave
    prior coverage unchanged, even for readable siblings; individual photo failures
    do not mean traversal was incomplete."""
    whole, by_folder = None, {}
    for targeting, ended in conn.execute(
            "SELECT r.file_ids_filter, r.ended_at FROM runs r WHERE r.mode = 'INDEX' AND r.status = 'Completed' "
            "AND r.ended_at IS NOT NULL AND rtrim(r.source_path, '/') = ? "
            "AND NOT EXISTS (SELECT 1 FROM operations o WHERE o.run_id = r.id "
            "AND o.photo_id IS NULL AND o.status = 'Failed')", (source,)):
        scope = json.loads(targeting) if targeting else {}
        if not scope:
            whole = max(whole or ended, ended)
        elif "source_subdir" in scope:
            folder = scope["source_subdir"].strip("/")
            by_folder[folder] = max(by_folder.get(folder) or ended, ended)
    return whole, by_folder


def for_scope(conn, source, source_subdir=None):
    source_subdir = posixpath.normpath(source_subdir) if source_subdir else None
    whole, folders = coverage(conn, str(source).rstrip('/'))
    value = whole
    if source_subdir:
        for parent, ended in folders.items():
            if source_subdir == parent or source_subdir.startswith(parent + '/'):
                value = max(value or ended, ended)
    return dict(indexed_at=value, source_subdir=source_subdir)
