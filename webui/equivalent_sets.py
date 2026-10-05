"""Exact closed-neighborhood equality, without expanding equal-hash photo pairs."""
from ns_similarity_cache import AVAILABLE, VALID, match_distance


def representatives(minimum, filtered):
    # A valid visual-hash bucket is indivisible: every identity in it has the
    # same recorded neighbors. Exact sorted bucket lists therefore identify the
    # full photo set, including the reference. No probabilistic fingerprint or
    # transitive component is used. Filters choose references, never members.
    distance = match_distance(minimum)
    return f"""WITH {AVAILABLE},
    buckets AS MATERIALIZED (SELECT phash,COUNT(*) AS n FROM available WHERE {VALID} GROUP BY phash),
    neighbors AS (
      SELECT phash AS a,phash AS b FROM buckets
      UNION SELECT low_hash,high_hash FROM content_similarity WHERE distance<={distance}
        AND low_hash IN (SELECT phash FROM buckets) AND high_hash IN (SELECT phash FROM buckets)
      UNION SELECT high_hash,low_hash FROM content_similarity WHERE distance<={distance}
        AND low_hash IN (SELECT phash FROM buckets) AND high_hash IN (SELECT phash FROM buckets)),
    signatures AS MATERIALIZED (
      SELECT a,GROUP_CONCAT(b,',') AS members FROM (SELECT a,b FROM neighbors ORDER BY a,b) GROUP BY a),
    eligible AS (
      SELECT p.id,s.members FROM available a JOIN photos p ON p.id=a.id
      JOIN signatures s ON s.a=a.phash
      WHERE a.phash_state='ok' AND (instr(s.members,',')>0 OR
        (SELECT n FROM buckets WHERE phash=a.phash)>1) {filtered})
    SELECT MIN(id) FROM eligible GROUP BY members"""
