#!/usr/bin/env python3
"""Bounded 250,000-row count-cache query check; synthetic prepared edges only.

Run with the app dependencies. Writes a temporary SQLite catalog, reads no photos,
and does not benchmark hash generation, exhaustive comparisons or real-library
capacity. Prepared relationships intentionally do not represent all possible pairs.
"""
from pathlib import Path
import tempfile,time,json,sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import ns_db
from webui import catalog
n=250000
with tempfile.TemporaryDirectory(prefix='ns-match-sort-scale-') as tmp:
    db=Path(tmp)/'catalog.sqlite';ns_db.initialize(db);c=ns_db.connect(db)
    run=ns_db.create_run(c,mode='COPY',source='/synthetic',destination='/destination')[0]
    t=time.perf_counter()
    with ns_db.transaction(c):
        c.executemany("INSERT INTO photos(id,source_path,dest_path,status,sha1_hash,file_size) VALUES(?,?,?,'Found_At_Destination',?,1000)",((i+1,f'/synthetic/{i}.jpg',f'/destination/{i}.jpg',f'{i:040x}') for i in range(n)))
        c.executemany("INSERT INTO contents(hash_algorithm,digest,phash,phash_state,width,height) VALUES('sha1',?,?,'ok',640,480)",((f'{i:040x}',f'{i//5:016x}') for i in range(n)))
        c.executemany('INSERT INTO files(file_id,created_run_id,created_at) VALUES(?,?,?)',((i+1,run,'test') for i in range(n)))
        c.executemany("INSERT INTO file_states(file_id,current_path,location_role,presence_state,sha1_hash) VALUES(?,?,'destination','present',?)",((i+1,f'/destination/{i}.jpg',f'{i:040x}') for i in range(n)))
        c.executemany('INSERT INTO similarity_hashes VALUES(?)',((f'{i:016x}',) for i in range(n//5)))
        c.executemany('INSERT INTO content_similarity VALUES(?,?,?)',((f'{i:016x}',f'{i+1:016x}',(i^(i+1)).bit_count()) for i in range(n//5-1)))
    from engine import ns_similarity_cache
    tcache=time.perf_counter(); ns_similarity_cache.refresh(c)
    print(json.dumps({'cache_seconds':round(time.perf_counter()-tcache,3), 'cache_bytes':c.execute("SELECT SUM(pgsize) FROM dbstat WHERE name IN ('similarity_count_cache','similarity_count_state')").fetchone()[0]}),flush=True)
    c.close()
    print(json.dumps({'photos':n,'fixture_and_cache_seconds':round(time.perf_counter()-t,2)}),flush=True)
    for sort in ('matches','newest'):
        t=time.perf_counter();result=catalog.list_photos(db,view='similar',sort=sort,match_min=75)
        assert result['total']==n
        print(json.dumps({'sort':sort,'query_seconds':round(time.perf_counter()-t,3),'first_count':result['items'][0]['similar_count']}),flush=True)
    t=time.perf_counter();pos=catalog.photo_position(db,photo_id=100000,view='similar',sort='matches',match_min=75)
    print(json.dumps({'position_seconds':round(time.perf_counter()-t,3),'found':pos['position'] is not None}),flush=True)
    t=time.perf_counter(); selection=catalog.photos_by_ids(db,list(range(1,1001)),sort='matches',match_min=75)
    assert selection['total']==1000
    print(json.dumps({'selection_seconds':round(time.perf_counter()-t,3)}),flush=True)
