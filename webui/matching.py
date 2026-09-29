"""Paged, read-only matching over precomputed visual-hash relationships."""
import math
import time
from pathlib import Path

import ns_db
import ns_similarity
from . import catalog

# Availability is recorded evidence, not a fresh filesystem verification. Destructive
# curation is deliberately absent; its future preview must verify files independently.
_BASE = f"""raw AS (
 SELECT {catalog._LIST_COLUMNS}, c.content_id, lower(c.phash) AS phash,
        c.phash_state, c.width, c.height,
        ROW_NUMBER() OVER (PARTITION BY c.content_id ORDER BY
            CASE WHEN p.status='Duplicate' THEN 1 ELSE 0 END, p.id) AS representative
 FROM photos p JOIN contents c ON c.digest=p.sha1_hash AND c.hash_algorithm='sha1'
 WHERE p.status IN ({ns_db.sql_values(catalog.VIEWS['all'] + (ns_db.PhotoStatus.DUPLICATE,))})
 AND EXISTS (SELECT 1 FROM file_states fs WHERE fs.presence_state='present'
     AND fs.sha1_hash=p.sha1_hash AND (fs.current_path=p.source_path
         OR (p.status!='Duplicate' AND fs.current_path=p.dest_path)))
)"""
_VALID = "phash_state='ok' AND length(phash)=16 AND phash NOT GLOB '*[^0-9a-f]*'"


def _scope(mode):
    return _BASE + (", available AS (SELECT * FROM raw WHERE representative=1)" if mode == 'similar'
                    else ", available AS (SELECT * FROM raw)")


def _check(mode, threshold, sort, page, page_size):
    if mode not in ('similar', 'exact') or sort not in ('matches','newest','oldest','name','largest'):
        raise ValueError('Unknown matching mode or sort')
    if not math.isfinite(threshold) or not 90 <= threshold <= 100:
        raise ValueError('Visual match must be between 90 and 100')
    if page < 1 or not 1 <= page_size <= 60:
        raise ValueError('page must be positive and page_size between 1 and 60')


def _state(conn):
    row = conn.execute(f"""WITH {_scope('similar')}
      SELECT COUNT(*) AS photos,
        COALESCE(SUM(NOT ({_VALID}) OR phash IS NULL OR phash_state IS NULL),0) AS unavailable,
        COALESCE(SUM(CASE WHEN {_VALID} AND NOT EXISTS
          (SELECT 1 FROM similarity_hashes h WHERE h.phash=available.phash) THEN 1 ELSE 0 END),0) AS pending
      FROM available""").fetchone()
    return dict(row)


def _item(row):
    return {key: row[key] for key in ('id','filename','file_size','date_taken','status','width','height')}


def queue(db: Path, *, mode='similar', threshold=90., sort='matches', q='', page=1, page_size=30):
    started = time.perf_counter()
    _check(mode, threshold, sort, page, page_size)
    distance = int(math.floor((100-threshold)*64/100 + 1e-9))
    scope = _scope(mode)
    if mode == 'similar':
        counted = f""", hashes AS (SELECT phash,COUNT(*) AS n FROM available WHERE {_VALID} GROUP BY phash),
          edges AS (SELECT low_hash AS a,high_hash AS b FROM content_similarity WHERE distance<=:distance
                    UNION ALL SELECT high_hash,low_hash FROM content_similarity WHERE distance<=:distance),
          counts AS (SELECT a,SUM(h.n) AS n FROM edges JOIN hashes h ON h.phash=b GROUP BY a),
          counted AS (SELECT p.*,h.n-1+COALESCE(c.n,0) AS matches FROM available p
                      JOIN hashes h ON h.phash=p.phash LEFT JOIN counts c ON c.a=p.phash WHERE p.phash_state='ok')"""
    else:
        counted = ", counted AS (SELECT *,COUNT(*) OVER (PARTITION BY content_id)-1 AS matches FROM available)"
    like = '%' + q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
    params = {'distance': distance, 'q': like, 'limit':page_size, 'offset':(page-1)*page_size}
    where = " FROM counted p WHERE matches>0 AND filename LIKE :q ESCAPE '\\'"
    order = {'matches':'matches DESC,p.id', 'newest':'(date_taken IS NULL),date_taken DESC,p.id DESC',
             'oldest':'(date_taken IS NULL),date_taken,p.id','name':'filename COLLATE NOCASE,p.id',
             'largest':'file_size DESC,p.id'}[sort]
    with catalog.connect(db) as conn:
        conn.execute('BEGIN')
        state = _state(conn)
        total = conn.execute('WITH '+scope+counted+' SELECT COUNT(*)'+where, params).fetchone()[0]
        rows = conn.execute('WITH '+scope+counted+' SELECT *'+where+' ORDER BY '+order+' LIMIT :limit OFFSET :offset',params).fetchall()
    return {'items':[{**_item(r),'matches':r['matches']} for r in rows], 'total':total,
            'page':page,'page_size':page_size,'state':state, 'query_ms': round((time.perf_counter()-started)*1000, 2)}


class ReviewChanged(ValueError):
    pass


def _pair(conn, reference_id, candidate_id):
    rows = conn.execute('WITH '+_BASE+' SELECT * FROM raw WHERE id IN (?,?)',
                        (reference_id, candidate_id)).fetchall()
    by_id = {r['id']: r for r in rows}
    if reference_id == candidate_id or reference_id not in by_id or candidate_id not in by_id:
        raise ReviewChanged('Both photos must still have recorded available copies. Refresh the comparison.')
    return by_id[reference_id], by_id[candidate_id]


def review(db: Path, reference_id: int, candidate_id: int, *, save=None):
    """Human labels describe an unordered pair of byte identities, never file paths.

    The submitted digests bind feedback to the content actually reviewed. Labels
    survive moves and renames; changed content never inherits the old judgment.
    """
    if save is not None and save.get('verdict') not in ('same', 'related', 'unrelated', None):
        raise ValueError('Unknown review verdict')
    with catalog.connect(db) as conn:
        if save is not None:
            conn.execute('PRAGMA synchronous=FULL')
        conn.execute('BEGIN IMMEDIATE' if save is not None else 'BEGIN')
        a, b = _pair(conn, reference_id, candidate_id)
        low, high = sorted((a['content_id'], b['content_id']))
        if save is not None:
            if (save.get('reference_sha1'), save.get('candidate_sha1')) != (a['sha1_hash'], b['sha1_hash']):
                raise ReviewChanged('The photo content changed. Refresh and review the current photos.')
            if low == high:
                raise ValueError('These photos already have identical bytes; a visual judgment is unnecessary.')
            if save['verdict'] is None:
                conn.execute('DELETE FROM similarity_reviews WHERE low_content_id=? AND high_content_id=?', (low, high))
            else:
                conn.execute('''INSERT INTO similarity_reviews VALUES(?,?,?,?)
                    ON CONFLICT(low_content_id,high_content_id) DO UPDATE SET verdict=excluded.verdict, updated_at=excluded.updated_at''',
                    (low, high, save['verdict'], ns_db.utc_now()))
            conn.commit()
        feedback = conn.execute('SELECT verdict,updated_at FROM similarity_reviews WHERE low_content_id=? AND high_content_id=?', (low, high)).fetchone()
        distance = ((int(a['phash'],16) ^ int(b['phash'],16)).bit_count()
                    if all(r['phash_state']=='ok' and ns_similarity.usable(r['phash']) for r in (a,b)) else None)
        return {'reference': {**_item(a), 'sha1':a['sha1_hash']}, 'candidate': {**_item(b), 'sha1':b['sha1_hash']},
                'exact': low == high, 'distance':distance,
                'score': round((64-distance)*100/64,2) if distance is not None else None,
                'feedback':dict(feedback) if feedback else None}


def diagnostics(db: Path):
    started = time.perf_counter()
    with catalog.connect(db) as conn:
        conn.execute('BEGIN')
        state = _state(conn)
        hashes = conn.execute("SELECT COUNT(DISTINCT phash) FROM (SELECT lower(phash) AS phash,phash_state FROM contents) WHERE " + _VALID).fetchone()[0]
        pairs = conn.execute('SELECT COUNT(*) FROM content_similarity').fetchone()[0]
        reviews = dict(conn.execute('SELECT verdict,COUNT(*) FROM similarity_reviews GROUP BY verdict').fetchall())
        progress = conn.execute("""SELECT run_id,started_at,updated_at,
            MAX(0,(julianday(updated_at)-julianday(started_at))*86400) AS elapsed_seconds
            FROM run_progress WHERE phase='matching' ORDER BY run_id DESC LIMIT 1""").fetchone()
    return {'state':state, 'distinct_hashes':hashes, 'stored_pairs':pairs, 'reviews':reviews,
            'last_comparison':dict(progress) if progress else None,
            'query_ms':round((time.perf_counter()-started)*1000,2)}


def matches(db: Path, photo_id: int, *, mode='similar', threshold=90., page=1, page_size=30):
    _check(mode, threshold, 'matches', page, page_size)
    distance = int(math.floor((100-threshold)*64/100 + 1e-9))
    with catalog.connect(db) as conn:
        conn.execute('BEGIN')
        state = _state(conn)
        # A direct Inspector link may name an exact duplicate, so resolve the
        # reference from raw, even when the similar queue collapses equal content.
        reference = conn.execute('WITH '+_BASE+' SELECT * FROM raw WHERE id=?',(photo_id,)).fetchone()
        if reference is None:
            return {'reference':None,'items':[],'total':0,'page':page,'page_size':page_size,'state':state,'availability':'not_available'}
        if mode=='similar' and not conn.execute(f'WITH {_BASE} SELECT 1 FROM raw WHERE id=? AND {_VALID}',(photo_id,)).fetchone():
            return {'reference':_item(reference),'items':[],'total':0,'page':page,'page_size':page_size,'state':state,'availability':'hash_unavailable'}
        scope = _scope(mode)
        if mode=='exact':
            scored = ", scored AS (SELECT *,0 AS distance FROM available WHERE content_id=:content AND id!=:id)"
        else:
            scored = """, near AS (SELECT :hash AS phash,0 AS distance UNION ALL
              SELECT high_hash,distance FROM content_similarity WHERE low_hash=:hash AND distance<=:distance UNION ALL
              SELECT low_hash,distance FROM content_similarity WHERE high_hash=:hash AND distance<=:distance),
              scored AS (SELECT a.*,n.distance FROM available a JOIN near n ON n.phash=a.phash
                         WHERE a.content_id!=:content AND a.phash_state='ok')"""
        params={'content':reference['content_id'],'hash':reference['phash'],'id':photo_id,'distance':distance,
                'limit':page_size,'offset':(page-1)*page_size}
        stats=conn.execute('WITH '+scope+scored+' SELECT COUNT(*),MAX(width*height) FROM scored',params).fetchone()
        rows=conn.execute('WITH '+scope+scored+' SELECT * FROM scored ORDER BY distance,id LIMIT :limit OFFSET :offset',params).fetchall()
        largest=max(reference['width']*reference['height'] if reference['width'] and reference['height'] else 0,stats[1] or 0) or None
    return {'reference':_item(reference),'items':[{**_item(r),'score':round((64-r['distance'])*100/64,2)} for r in rows],
            'total':stats[0],'page':page,'page_size':page_size,'state':state,'availability':'available','largest_pixels':largest}
