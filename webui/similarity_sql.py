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
MATCHED_IDS = f"""WITH {AVAILABLE},
 hashes AS (SELECT phash,COUNT(*) AS n FROM available WHERE {VALID} GROUP BY phash),
 matched_hashes AS (
   SELECT phash FROM hashes WHERE n>1
   UNION SELECT low_hash FROM content_similarity WHERE distance<={ns_similarity.MAX_DISTANCE}
     AND low_hash IN (SELECT phash FROM hashes) AND high_hash IN (SELECT phash FROM hashes)
   UNION SELECT high_hash FROM content_similarity WHERE distance<={ns_similarity.MAX_DISTANCE}
     AND low_hash IN (SELECT phash FROM hashes) AND high_hash IN (SELECT phash FROM hashes)
 ) SELECT id FROM available WHERE {VALID} AND phash IN (SELECT phash FROM matched_hashes)"""
