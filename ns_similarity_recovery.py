"""Destination-only missing-hash work and user-facing recovery classifications."""
from pathlib import Path
import ns_db
from ns_similarity_cache import AVAILABLE, comparison_state

REASONS = {
    'not_supported': ('unsupported', 'This format is not supported by the visual decoder. The file may still be a valid image; check it in an external viewer or install decoder support.', False),
    'repair_missing': ('missing', 'The destination file is missing. Restore it at its recorded location before retrying.', True),
    'repair_unreadable': ('unreadable', 'The destination file could not be read. Check its availability and read permissions before retrying.', True),
    'repair_changed': ('changed', 'The destination bytes differ from the catalog. Restore the catalogued file before retrying, or rebuild the catalog for the replacement; hash repair cannot reconcile replaced files.', True),
    'repair_outside': ('outside_destination', 'The recorded file is outside the configured destination. Correct the destination configuration before retrying.', True),
    'repair_decode': ('decode_failed', 'The file could not be decoded for visual matching. It may be damaged, mislabeled, or need another decoder. Check it in an external viewer and repair or replace it outside this app. It stays excluded from visual matching; retry only after the underlying issue is fixed.', True),
}


def affected_sql(photo_id=None):
    valid = "a.phash_state='ok' AND length(a.phash)=16 AND a.phash NOT GLOB '*[^0-9a-f]*'"
    selected = '' if photo_id is None else ' AND p.sha1_hash=(SELECT sha1_hash FROM photos WHERE id=?)'
    return f"""WITH {AVAILABLE} SELECT a.id,a.content_id,p.sha1_hash,p.dest_path,a.phash_state,
      CASE WHEN {valid} THEN 'pending' ELSE 'missing_hash' END AS kind
      FROM available a JOIN photos p ON p.id=a.id
      WHERE (NOT ({valid}) OR a.phash IS NULL OR a.phash_state IS NULL OR NOT EXISTS
        (SELECT 1 FROM similarity_hashes h WHERE h.phash=a.phash)){selected}"""


def rows(conn, photo_id=None):
    cursor = conn.execute("SELECT * FROM (" + affected_sql(photo_id) + ") WHERE kind='missing_hash' ORDER BY id", () if photo_id is None else (photo_id,))
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


REASONS['error'] = REASONS['repair_decode']
REASONS['failed'] = REASONS['repair_decode']


def describe(row):
    if row['kind'] == 'pending':
        category, message, retryable = 'pending', 'Visual hash is ready; its comparisons are unfinished.', False
    elif Path(row['dest_path']).suffix.lower() not in ns_db.SUPPORTED_EXTENSIONS:
        category, message, retryable = REASONS['not_supported']
    else:
        category, message, retryable = REASONS.get(row['phash_state'],
            ('missing_hash', 'No usable visual hash is recorded. Read the destination photo to retry hash generation.', True))
    return {'id':row['id'], 'filename':Path(row['dest_path']).name, 'kind':row['kind'],
            'reason':category, 'message':message, 'retryable':retryable}


def report(conn, *, page=1, page_size=30, photo_id=None):
    conn.execute('BEGIN')
    params = () if photo_id is None else (photo_id,)
    sql = affected_sql(photo_id)
    supported = ' OR '.join("lower(dest_path) LIKE '%" + ext + "'" for ext in sorted(ns_db.SUPPORTED_EXTENSIONS))
    total, retryable = conn.execute(f"""SELECT COUNT(*),COALESCE(SUM(kind='missing_hash'
      AND COALESCE(phash_state,'') != 'not_supported' AND ({supported})),0)
      FROM ({sql})""", params).fetchone()
    cursor = conn.execute(sql + ' ORDER BY a.id LIMIT ? OFFSET ?', (*params,page_size,(page-1)*page_size))
    names = [c[0] for c in cursor.description]
    items = [describe(dict(zip(names,row))) for row in cursor]
    return {'items':items, 'total':total, 'retryable':retryable, 'state':comparison_state(conn),
            'page':page, 'page_size':page_size}
