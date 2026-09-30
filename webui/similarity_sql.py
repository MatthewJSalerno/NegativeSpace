"""Shared destination membership for the gallery and per-photo match counts."""
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


def matched_ids(minimum=75):
    distance = match_distance(minimum)
    return f"""WITH {AVAILABLE},
 hashes AS (SELECT phash,COUNT(*) AS n FROM available WHERE {VALID} GROUP BY phash),
 matched_hashes AS (
   SELECT phash FROM hashes WHERE n>1
   UNION SELECT low_hash FROM content_similarity WHERE distance<={distance}
     AND low_hash IN (SELECT phash FROM hashes) AND high_hash IN (SELECT phash FROM hashes)
   UNION SELECT high_hash FROM content_similarity WHERE distance<={distance}
     AND low_hash IN (SELECT phash FROM hashes) AND high_hash IN (SELECT phash FROM hashes)
 ) SELECT id FROM available WHERE {VALID} AND phash IN (SELECT phash FROM matched_hashes)"""


def match_counts_cte(minimum=75, ids=None):
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
    return f"""{AVAILABLE},
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


def comparison_state(conn):
    row = conn.execute(f"""WITH {AVAILABLE} SELECT
      COALESCE(SUM(NOT ({VALID}) OR phash IS NULL OR phash_state IS NULL),0) AS unavailable,
      COALESCE(SUM(CASE WHEN {VALID} AND NOT EXISTS
        (SELECT 1 FROM similarity_hashes h WHERE h.phash=available.phash) THEN 1 ELSE 0 END),0) AS pending
      FROM available""").fetchone()
    return dict(row)
