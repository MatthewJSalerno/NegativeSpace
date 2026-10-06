"""Read-only, paged reference sets over recorded destination relationships.

Only explicitly selected one-hop references are expanded. No transitive traversal,
clustering, cached group membership or photo writes.
"""
from . import catalog, gallery
from engine.ns_similarity_cache import AVAILABLE, VALID, match_distance, comparison_state

MAX_RELATED = 6


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


def browse(db, reference_id, *, threshold=90, include=(), page=1, related_page=1, page_size=12):
    distance = match_distance(threshold)
    ids = list(dict.fromkeys(include))
    if (type(reference_id) is not int or reference_id < 1 or reference_id > 2**63-1
            or any(type(i) is not int or not 1 <= i <= 2**63-1 for i in ids)
            or len(include) > MAX_RELATED or reference_id in ids):
        raise ValueError('Choose at most six distinct related references with positive photo IDs.')
    if page < 1 or related_page < 1 or not 1 <= page_size <= 24:
        raise ValueError('Pages must be positive and page_size between 1 and 24.')
    root_sql = _membership([reference_id])
    root_params = (reference_id,distance,distance)
    all_ids = [reference_id,*ids]
    sql = _membership(all_ids)
    params = (*all_ids,distance,distance)
    with catalog.connect(db) as conn:
        conn.execute('BEGIN')
        root = conn.execute(root_sql+'SELECT * FROM roots',root_params).fetchone()
        if root is None:
            raise ValueError('This reference needs an available destination copy and usable visual hash. Reopen the set after resolving matching issues.')
        valid_selected = {r[0] for r in conn.execute(root_sql+
            'SELECT id FROM members WHERE id IN ('+(','.join('?' for _ in ids) or 'NULL')+')',
            (*root_params,*ids))}
        if valid_selected != set(ids):
            raise ValueError('A selected set no longer directly matches this reference at this percentage. Remove it or reopen the set.')
        state = comparison_state(conn)
        total = conn.execute(sql+'SELECT COUNT(DISTINCT id) FROM members',params).fetchone()[0]
        related_total = conn.execute(root_sql+'SELECT COUNT(*) FROM members WHERE id!=?',(*root_params,reference_id)).fetchone()[0]
        page = min(page,max(1,(total+page_size-1)//page_size))
        related_page = min(related_page,max(1,(related_total+page_size-1)//page_size))
        # Membership and sorting happen before pagination; exact contents have one
        # canonical destination representative. Only page-sized metadata is read.
        member_rows = conn.execute(sql+'''SELECT id,GROUP_CONCAT(reference_id) AS refs,
          MIN(CASE WHEN reference_id=? THEN distance END) AS root_distance FROM members GROUP BY id
          ORDER BY (id=?) DESC,MIN(distance),id LIMIT ? OFFSET ?''',
          (*params,reference_id,reference_id,page_size,(page-1)*page_size)).fetchall()
        member_ids = [r['id'] for r in member_rows]
        related_ids = [r[0] for r in conn.execute(root_sql+'''SELECT id FROM members WHERE id!=?
          ORDER BY distance,id LIMIT ? OFFSET ?''',(*root_params,reference_id,page_size,(related_page-1)*page_size))]
        lookup_ids = list(dict.fromkeys([*all_ids,*member_ids,*related_ids]))
        lookup = {r['id']:dict(r) for r in conn.execute(f'''SELECT {gallery._LIST_COLUMNS}
          FROM photos p WHERE p.id IN ({','.join('?' for _ in lookup_ids)})''',lookup_ids)}
        def photo(i):
            return {k:v for k,v in lookup[i].items() if k!='sha1_hash'}
        sizes = dict(conn.execute(sql+'SELECT reference_id,COUNT(*) FROM members GROUP BY reference_id',params).fetchall())
        references=[{**photo(i),'total':sizes[i]} for i in all_ids]
        items=[]
        for row in member_rows:
            memberships=sorted(int(i) for i in row['refs'].split(','))
            score=row['root_distance']
            items.append({**photo(row['id']),'references':memberships,
                          'direct':reference_id in memberships,
                          'score':round((64-score)*100/64,2) if score is not None else None})
        related=[]
        if related_ids:
            related_sql=_membership([reference_id,*related_ids])
            related_params=(reference_id,*related_ids,distance,distance)
            counts=conn.execute(related_sql+'''SELECT reference_id,COUNT(*) AS total,
              SUM(id NOT IN (SELECT id FROM members WHERE reference_id=?)) AS additional
              FROM members WHERE reference_id!=? GROUP BY reference_id''',
              (*related_params,reference_id,reference_id)).fetchall()
            by_id={r['reference_id']:r for r in counts}
            related=[{**photo(i),'total':by_id[i]['total'],'additional':by_id[i]['additional']} for i in related_ids]
    return {'reference':photo(reference_id),'references':references,'items':items,'total':total,
            'page':page,'page_size':page_size,'related':related,'related_total':related_total,
            'related_page':related_page,'threshold':threshold,'state':state,'max_related':MAX_RELATED}
