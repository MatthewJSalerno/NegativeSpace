"""Disposable, transactionally invalidated similarity counts in the catalog."""
import ns_db
import ns_similarity

DELIVERED = ns_db.sql_values((ns_db.PhotoStatus.COMPLETED, ns_db.PhotoStatus.COPIED,
                              ns_db.PhotoStatus.FOUND_AT_DESTINATION))
VALID = "phash_state='ok' AND length(phash)=16 AND phash NOT GLOB '*[^0-9a-f]*'"

# One representative per byte identity. Keep this scope small: counting/filtering
# does not need filenames, EXIF JSON or a window over every photo's metadata.
AVAILABLE = f"""available AS (
 SELECT MIN(p.id) AS id,c.content_id,lower(c.phash) AS phash,c.phash_state
 FROM photos p JOIN contents c ON c.digest=p.sha1_hash AND c.hash_algorithm='sha1'
 WHERE p.status IN ({DELIVERED}) AND EXISTS (
   SELECT 1 FROM file_states fs WHERE fs.presence_state='present'
   AND fs.sha1_hash=p.sha1_hash AND fs.current_path=p.dest_path)
 GROUP BY c.content_id
)"""

# Evaluated once as an IN subquery, not as a catalog scan for each gallery row.
# Keep membership as IN sets: joining the grouped hashes CTE twice can make SQLite
# scan that entire CTE for every stored pair (observed on the validation catalog).
def match_distance(minimum):
    if type(minimum) is not int or not ns_similarity.MIN_SCORE <= minimum <= 100:
        raise ValueError('match_min must be a whole percentage between 75 and 100')
    return (100 - minimum) * 64 // 100


def _live_matched_ids(minimum=75, available=AVAILABLE):
    distance = match_distance(minimum)
    return f"""WITH {available},
 hashes AS (SELECT phash,COUNT(*) AS n FROM available WHERE {VALID} GROUP BY phash),
 matched_hashes AS (
   SELECT phash FROM hashes WHERE n>1
   UNION SELECT low_hash FROM content_similarity WHERE distance<={distance}
     AND low_hash IN (SELECT phash FROM hashes) AND high_hash IN (SELECT phash FROM hashes)
   UNION SELECT high_hash FROM content_similarity WHERE distance<={distance}
     AND low_hash IN (SELECT phash FROM hashes) AND high_hash IN (SELECT phash FROM hashes)
 ) SELECT id FROM available WHERE {VALID} AND phash IN (SELECT phash FROM matched_hashes)"""


def _live_counts_cte(minimum=75, ids=None, available=AVAILABLE):
    """Weight hash relationships by current destination content membership.

    Identical visual hashes need only bucket sizes, never a cross product of photos.
    Counts ignore gallery filters, just like the Inspector's direct-match counts.
    """
    distance = match_distance(minimum)
    # Restrict only the returned references, never the counted neighbors. This also
    # bounds the selection's outer join while retaining unavailable selected files.
    selected = ""
    if ids is not None:
        if any(type(i) is not int or i < 1 for i in ids):
            raise ValueError('ids must contain positive photo ids')
        selected = " AND p.id IN (" + (','.join(str(i) for i in ids) or 'NULL') + ")"
    return f"""{available},
    hashes AS MATERIALIZED (SELECT phash,COUNT(*) AS n FROM available WHERE {VALID} GROUP BY phash),
    edges AS (
      SELECT low_hash AS a,high_hash AS b FROM content_similarity WHERE distance<={distance}
        AND low_hash IN (SELECT phash FROM hashes) AND high_hash IN (SELECT phash FROM hashes)
      UNION ALL
      SELECT high_hash,low_hash FROM content_similarity WHERE distance<={distance}
        AND low_hash IN (SELECT phash FROM hashes) AND high_hash IN (SELECT phash FROM hashes)),
    totals AS (SELECT a,SUM(h.n) AS n FROM edges JOIN hashes h ON h.phash=b GROUP BY a),
    match_counts AS (SELECT p.id,h.n-1+COALESCE(t.n,0) AS similar_count FROM available p
      JOIN hashes h ON h.phash=p.phash LEFT JOIN totals t ON t.a=p.phash WHERE p.phash_state='ok'{selected})"""


def live_comparison_state(conn):
    row = conn.execute(f"""WITH {AVAILABLE} SELECT
      COALESCE(SUM(NOT ({VALID}) OR phash IS NULL OR phash_state IS NULL),0) AS unavailable,
      COALESCE(SUM(CASE WHEN {VALID} AND NOT EXISTS
        (SELECT 1 FROM similarity_hashes h WHERE h.phash=available.phash) THEN 1 ELSE 0 END),0) AS pending
      FROM available""").fetchone()
    return dict(zip(('unavailable','pending'), row))


THRESHOLDS = (75, 80, 85, 90, 95, 100)
CACHE_VALID = "EXISTS (SELECT 1 FROM similarity_count_state WHERE id=1 AND dirty=0)"
COUNT_COLUMNS = tuple(f"count_{t}" for t in THRESHOLDS)
DDL = (
    "CREATE TABLE similarity_count_state (id INTEGER PRIMARY KEY CHECK(id=1), dirty INTEGER NOT NULL CHECK(dirty IN (0,1)), unavailable INTEGER NOT NULL DEFAULT 0, pending INTEGER NOT NULL DEFAULT 0)",
    "INSERT INTO similarity_count_state(id,dirty) VALUES(1,1)",
    "CREATE TABLE similarity_count_cache (photo_id INTEGER PRIMARY KEY," +
        ','.join(f"{column} INTEGER NOT NULL CHECK({column}>=0)" for column in COUNT_COLUMNS) + ")",
)
# Every dependency invalidates in the same transaction, including raw SQL updates,
# deleted files, changed representatives, changed hashes and interrupted jobs.
for _table, _columns in (
    ('photos', ('id','status','sha1_hash','dest_path')),
    ('contents', ('content_id','hash_algorithm','digest','phash','phash_state')),
    ('file_states', ('current_path','presence_state','sha1_hash')),
    ('content_similarity', ('low_hash','high_hash','distance')),
    ('similarity_hashes', ('phash',)),
):
    for _event in ('INSERT','DELETE','UPDATE'):
        _when = ' WHEN ' + ' OR '.join(f'OLD.{c} IS NOT NEW.{c}' for c in _columns) if _event == 'UPDATE' else ''
        DDL += (f"CREATE TRIGGER invalidate_similarity_counts_{_table}_{_event.lower()} AFTER {_event} ON {_table}{_when} "
                "BEGIN UPDATE similarity_count_state SET dirty=1 WHERE id=1 AND dirty=0; END",)


def _uncached_available():
    return AVAILABLE.replace('WHERE p.status', f'WHERE NOT ({CACHE_VALID}) AND p.status')


def matched_ids(minimum=75):
    if minimum not in THRESHOLDS:
        return _live_matched_ids(minimum)
    match_distance(minimum)
    return (f"SELECT photo_id FROM similarity_count_cache WHERE {CACHE_VALID} AND count_{minimum}>0 "
            "UNION ALL SELECT id FROM (" + _live_matched_ids(minimum, _uncached_available()) + ")")


def match_counts_cte(minimum=75, ids=None):
    if minimum not in THRESHOLDS:
        return _live_counts_cte(minimum, ids)
    live = _live_counts_cte(minimum, ids, _uncached_available()).replace('match_counts AS (', 'live_counts AS (')
    selected = '' if ids is None else ' AND photo_id IN (' + (','.join(str(i) for i in ids) or 'NULL') + ')'
    return live + f""", match_counts AS (
      SELECT id,similar_count FROM live_counts UNION ALL
      SELECT photo_id AS id,count_{minimum} AS similar_count FROM similarity_count_cache
      WHERE {CACHE_VALID}{selected})"""


def comparison_state(conn):
    row = conn.execute('SELECT unavailable,pending FROM similarity_count_state WHERE id=1 AND dirty=0').fetchone()
    return dict(zip(('unavailable','pending'), row)) if row is not None else live_comparison_state(conn)


def refresh(conn, *, cancelled=lambda: False):
    """Publish all six counts atomically. A failed/cancelled build leaves live reads.

    Engine and explicit preparation tool only. No photo reads, API writes, or new
    comparisons. IMMEDIATE serializes publication with all dependency mutations;
    WAL readers retain a coherent earlier snapshot while the replacement is built.
    """
    if conn.in_transaction:
        raise ValueError('Count refresh requires its own transaction')
    conn.execute('BEGIN IMMEDIATE')
    try:
        row = conn.execute('SELECT dirty FROM similarity_count_state WHERE id=1').fetchone()
        if row is not None and not row[0]:
            conn.rollback()
            return True
        if cancelled():
            conn.rollback()
            return False
        conn.set_progress_handler(lambda: int(cancelled()), 10000)
        # A distance histogram weighted by destination hash membership supplies
        # all six cumulative counts in one aggregation, including zero-distance.
        sums = ','.join(f'SUM(CASE WHEN distance<={match_distance(t)} THEN h.n ELSE 0 END) AS count_{t}' for t in THRESHOLDS)
        values = ','.join(f'h.n-1+COALESCE(t.count_{t},0)' for t in THRESHOLDS)
        conn.execute('DELETE FROM similarity_count_cache')
        conn.execute(f"""WITH {AVAILABLE},
          hashes AS MATERIALIZED (SELECT phash,COUNT(*) AS n FROM available WHERE {VALID} GROUP BY phash),
          edges AS (
            SELECT low_hash AS a,high_hash AS b,distance FROM content_similarity
              WHERE low_hash IN (SELECT phash FROM hashes) AND high_hash IN (SELECT phash FROM hashes)
            UNION ALL
            SELECT high_hash,low_hash,distance FROM content_similarity
              WHERE low_hash IN (SELECT phash FROM hashes) AND high_hash IN (SELECT phash FROM hashes)),
          totals AS (SELECT a,{sums} FROM edges JOIN hashes h ON h.phash=b GROUP BY a)
          INSERT INTO similarity_count_cache SELECT p.id,{values} FROM available p
          JOIN hashes h ON h.phash=p.phash LEFT JOIN totals t ON t.a=p.phash WHERE p.phash_state='ok'""")
        state = live_comparison_state(conn)
        conn.execute('INSERT INTO similarity_count_state VALUES(1,0,?,?) ON CONFLICT(id) DO UPDATE SET dirty=0,unavailable=excluded.unavailable,pending=excluded.pending',
                     (state['unavailable'], state['pending']))
        conn.set_progress_handler(None, 0)
        if cancelled():
            conn.rollback()
            return False
        conn.commit()
        return True
    except BaseException:
        conn.set_progress_handler(None, 0)
        conn.rollback()
        if cancelled():
            return False
        raise
    finally:
        conn.set_progress_handler(None, 0)
