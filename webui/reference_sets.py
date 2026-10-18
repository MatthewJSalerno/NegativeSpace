"""A reference set's members: the reference and every destination photo that directly
matches it, for the gallery's set view (Show this set in gallery, Review this set).
Read-only; no transitive traversal, clustering or cached group membership.
"""
from engine.ns_similarity_cache import AVAILABLE, VALID


def _membership(ids):
    slots = ','.join('?' for _ in ids)
    # Resolve canonical roots only within the requested byte identities. Then
    # group destinations only for hashes adjacent to those roots. Unrelated
    # catalog rows need neither canonical grouping nor repeated materialization.
    root_available = AVAILABLE.replace('available AS', 'root_available AS').replace(
        'WHERE p.status', 'WHERE p.sha1_hash IN (SELECT sha1_hash FROM requested) AND p.status')
    available = AVAILABLE.replace('WHERE p.status',
        'WHERE lower(c.phash) IN (SELECT phash FROM near) AND p.status')
    return f"""WITH requested AS (SELECT id,sha1_hash FROM photos WHERE id IN ({slots})),
      {root_available}, roots AS (
      SELECT * FROM root_available WHERE id IN (SELECT id FROM requested) AND {VALID}),
      near AS (
        SELECT id AS reference_id,phash,0 AS distance FROM roots
        UNION ALL SELECT r.id,s.high_hash,s.distance FROM roots r
          JOIN content_similarity s ON s.low_hash=r.phash AND s.distance<=?
        UNION ALL SELECT r.id,s.low_hash,s.distance FROM roots r
          JOIN content_similarity s ON s.high_hash=r.phash AND s.distance<=?),
      {available}, members AS (SELECT n.reference_id,a.id,a.phash,n.distance FROM near n
        JOIN available a ON a.phash=n.phash WHERE a.phash_state='ok') """
