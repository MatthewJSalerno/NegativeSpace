"""Original-source labels for names shared by different photos in a result."""

from collections import Counter, defaultdict
import json
from pathlib import PurePosixPath


def _folders(paths):
    """Shortest unique suffix per folder; linear in the number of path components."""
    parts = {path: PurePosixPath(path).parts for path in paths}
    counts = Counter(tail[-n:] for tail in parts.values() for n in range(1, len(tail) + 1))
    result = {}
    for path, tail in parts.items():
        for n in range(1, len(tail) + 1):
            if counts[tail[-n:]] == 1:
                result[path] = ('…/' + '/'.join(tail[-n:])) if n < len(tail) else path
                break
        else:
            result[path] = path
    return result


def describe(conn, rows, scope, params, filename_sql):
    """Read names in the complete scope, never just this page. All lookups are batched.

    scope/filename_sql are server-built SQL; names, IDs and filter values are bound.
    Source paths are catalog records, not filesystem reads. Duplicate content does not
    create a clash, even in an explicit selection containing its extra source rows.
    """
    if not rows:
        return {}
    ids = json.dumps([r['id'] for r in rows])
    names = json.dumps(sorted({r['filename'] for r in rows}))
    peers = conn.execute(f"""SELECT p.id, p.sha1_hash, p.source_path,
        {filename_sql} AS filename FROM photos p WHERE ({scope})
        AND {filename_sql} IN (SELECT value FROM json_each(?))""", (*params, names)).fetchall()
    groups = defaultdict(list)
    for peer in peers:
        groups[peer['filename']].append(peer)
    labels = {}
    for name, group in groups.items():
        identities = {('hash', p['sha1_hash']) if p['sha1_hash'] else ('id', p['id']) for p in group}
        if len(identities) > 1:
            labels[name] = _folders({str(PurePosixPath(p['source_path']).parent) for p in group if p['source_path']})
    origins = conn.execute("""SELECT p.id, p.source_path, d.source_path AS copy_path
        FROM photos p LEFT JOIN photos d ON d.sha1_hash=p.sha1_hash AND p.sha1_hash!='' AND d.id!=p.id
        WHERE p.id IN (SELECT value FROM json_each(?)) ORDER BY p.id, d.id""", (ids,)).fetchall()
    paths = defaultdict(list)
    seen = defaultdict(set)
    for row in origins:
        for path in (row['source_path'], row['copy_path']):
            if path and path not in seen[row['id']]:
                paths[row['id']].append(path)
                seen[row['id']].add(path)
    # A suffix in a name alone proves nothing. Successful import history does,
    # including paired photo/XMP imports which do not set has_name_collision.
    renamed = {r[0] for r in conn.execute(f"""SELECT DISTINCT p.id
        FROM photos p JOIN operations o ON o.photo_id=p.id JOIN runs r ON r.id=o.run_id
        WHERE p.id IN (SELECT value FROM json_each(?))
          AND o.source_path=p.source_path AND o.status IN ('Copied','Completed')
          AND basename(o.dest_path)={filename_sql}
          AND basename(o.source_path)!=basename(o.dest_path)
          AND (r.mode IN ('COPY','MOVE') OR EXISTS
            (SELECT 1 FROM operation_events e WHERE e.operation_id=o.id AND e.step='pair_complete'))""", (ids,))}
    return {r['id']: {
        'clashes': r['filename'] in labels,
        'folder': labels.get(r['filename'], {}).get(str(PurePosixPath(paths[r['id']][0]).parent)) if paths[r['id']] else None,
        'original_paths': paths[r['id']],
        'renamed_on_arrival': r['id'] in renamed,
    } for r in rows}
