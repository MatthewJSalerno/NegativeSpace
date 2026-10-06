#!/usr/bin/env python3
"""Synthetic catalog query benchmark. No photo reads or real catalog input.

Creates new output only. Reuse a generated fixture directory for comparable A/B
runs; database reads are query-only. Run with app dependencies (Linux app image).
"""
import argparse
import contextlib
import hashlib
import json
import math
import multiprocessing as mp
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import ns_db
from engine import ns_similarity_cache
from webui import gallery, matching, reference_sets

PROFILES = ('sparse', 'equal', 'dense', 'mixed')
SCENARIOS = ('gallery', 'grouped', 'last_page', 'filtered', 'inspector', 'related', 'members', 'position')


def fingerprint(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fixture_unchanged(db, manifest):
    # SQLite changes can live solely in WAL while the main file hash is unchanged.
    wal = Path(str(db) + '-wal')
    return (not wal.exists() or wal.stat().st_size == 0) and fingerprint(db) == manifest['database_sha256']


def worker_peak_rss():
    # Linux resets VmHWM at exec. ru_maxrss can retain pre-exec fork memory,
    # which would misattribute the parent's fixture-building footprint.
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmHWM:'):
            return int(line.split()[1]) * 1024
    raise RuntimeError('Linux /proc VmHWM is required for query-worker memory measurements')


def build_fixture(directory, photos, profile, seed=91, dense_photos=4096, max_edges=250000):
    started = time.perf_counter()
    directory.mkdir(parents=True, exist_ok=False)
    db = directory / 'catalog.sqlite'
    rng = random.Random(seed)
    dense_n = min(photos, dense_photos) if profile == 'dense' else 0
    groups = []
    hashes = []
    used = set()
    # Random prefixes separate planted groups. Stored edges are prepared query
    # fixtures, not a claim of exhaustive global pHash comparison completeness.
    remaining = photos
    while remaining:
        width = min(64 if len(hashes) < dense_n else 5, remaining)
        if profile == 'equal':
            width = remaining
        elif len(hashes) < dense_n:
            width = min(width, dense_n - len(hashes))
        prefix = rng.getrandbits(58) << 6
        while prefix in used:
            prefix = rng.getrandbits(58) << 6
        used.add(prefix)
        distinct = len(hashes) < dense_n
        group = [f'{prefix | j:016x}' if distinct else f'{prefix:016x}' for j in range(width)]
        hashes.extend(group)
        groups.append(sorted(set(group)))
        remaining -= width
    edge_count = sum(len(g)*(len(g)-1)//2 for g in groups)
    if edge_count > max_edges:
        raise ValueError(f'Fixture needs {edge_count} edges, exceeding --max-edges={max_edges}')
    ns_db.initialize(db)
    with contextlib.closing(ns_db.connect(db)) as conn:
        run = ns_db.create_run(conn, mode='COPY', source='/synthetic', destination='/destination')[0]
        with ns_db.transaction(conn):
            for i, phash in enumerate(hashes, 1):
                source_only = profile == 'mixed' and i % 11 == 0
                missing = profile == 'mixed' and i % 37 == 0
                bad_hash = profile == 'mixed' and i % 29 == 0
                extension = ('jpg', 'png', 'cr2', 'tif')[i % 4]
                source = f'/synthetic/folder-{i % 20}/photo-{i:07d}.{extension}'
                dest = f'/destination/photo-{i:07d}.{extension}'
                digest = f'{i:040x}'
                metadata = json.dumps({'date_taken':f'{2000+i%25}-01-{1+i%28:02d} 12:00:00', 'date_source':'exif'})
                conn.execute('INSERT INTO photos(id,source_path,dest_path,status,sha1_hash,file_size,metadata_json) VALUES(?,?,?,?,?,?,?)',
                    (i,source,None if source_only else dest,'Pending' if source_only else 'Copied',digest,1000+(i%1000)*1024,metadata))
                conn.execute("INSERT INTO contents(hash_algorithm,digest,phash,phash_state,width,height) VALUES('sha1',?,?,?,?,?)",
                    (digest,None if bad_hash else phash,'error' if bad_hash else 'ok',640+(i%4)*640,480+(i%4)*480))
                conn.execute("INSERT INTO files(file_id,created_run_id,created_at) VALUES(?,?,'fixture')",(i,run))
                conn.execute('INSERT INTO file_states(file_id,current_path,location_role,presence_state,sha1_hash) VALUES(?,?,?,?,?)',
                    (i,source if source_only else dest,'source' if source_only else 'destination','missing' if missing else 'present',digest))
            conn.executemany('INSERT INTO similarity_hashes VALUES(?)',((h,) for h in sorted(set(hashes))))
            conn.executemany('INSERT INTO content_similarity VALUES(?,?,?)',
                ((a,b,(int(a,16)^int(b,16)).bit_count()) for group in groups for j,a in enumerate(group) for b in group[j+1:]))
        cache_start = time.perf_counter()
        ns_similarity_cache.refresh(conn)
        cache_seconds = time.perf_counter()-cache_start
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    manifest = {'kind':'negativespace-synthetic-query-v1','profile':profile,'photos':photos,'seed':seed,
        'dense_photos':dense_n,'unique_hashes':len(set(hashes)),'prepared_edges':edge_count,
        'database_bytes':db.stat().st_size,'cache_build_seconds':cache_seconds,
        'fixture_seconds':time.perf_counter()-started,'database_sha256':fingerprint(db),
        'relationship_scope':'Prepared within planted groups only; no global comparison or image decoding.'}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def query(db, scenario, threshold):
    args = {'view':'similar','match_min':threshold,'sort':'matches','page_size':60}
    if scenario == 'gallery':
        return gallery.list_photos(db, **args)
    if scenario == 'grouped':
        return gallery.list_photos(db, **args, group_sets=True)
    if scenario == 'last_page':
        # Counts are part of the actual API workflow, and intentionally timed.
        first = gallery.list_photos(db, **args)
        return gallery.list_photos(db, **args, page=max(1,math.ceil(first['total']/60)))
    if scenario == 'filtered':
        return gallery.list_photos(db, **args, group_sets=True, types=['jpg'], dates=['2020'])
    if scenario == 'inspector':
        return {'counts':matching.counts(db,1),'matches':matching.matches(db,1,threshold=threshold,page_size=12)}
    if scenario == 'related':
        # Time discovery plus one expansion; at 100% a distinct-hash reference
        # may have no related references at all.
        first = reference_sets.browse(db,1,threshold=threshold,page_size=12)
        include = [first['related'][0]['id']] if first['related'] else []
        return reference_sets.browse(db,1,threshold=threshold,include=include,page_size=12)
    if scenario == 'members':
        return gallery.list_photos(db, **{**args,'view':'all'}, set_reference=1)
    if scenario == 'position':
        return gallery.photo_position(db,1,view='similar',sort='matches',match_min=threshold,group_sets=True)
    raise ValueError('Unknown scenario')


def worker(pipe, db, scenario, threshold, warmups, repeats):
    # Query functions all obtain connections through this factory. Guard against
    # accidental catalog mutations by future implementations of a query helper.
    original = ns_db.connect
    def readonly(path, *args, **kwargs):
        conn = original(path, *args, **kwargs)
        conn.execute('PRAGMA query_only=ON')
        return conn
    ns_db.connect = readonly
    try:
        for i in range(1+warmups+repeats):
            start = time.perf_counter()
            result = query(Path(db),scenario,threshold)
            elapsed = (time.perf_counter()-start)*1000
            digest = hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
            pipe.send({'phase':'first_in_worker' if i == 0 else 'warmup' if i <= warmups else 'warm',
                'elapsed_ms':elapsed,'result_sha256':digest,
                'total':result.get('total'),'returned':len(result.get('items',[])),
                'worker_peak_rss_bytes':worker_peak_rss()})
    except Exception as exc:
        pipe.send({'error':type(exc).__name__+': '+str(exc)})
    finally:
        pipe.close()


def measure(db, scenario, threshold, warmups, repeats, timeout):
    ctx = mp.get_context('spawn')
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=worker,args=(sender,str(db),scenario,threshold,warmups,repeats))
    process.start(); sender.close()
    samples = []
    failure = None
    try:
        for _ in range(1+warmups+repeats):
            if not receiver.poll(timeout):
                failure = 'worker_timeout'; break
            try:
                sample = receiver.recv()
            except EOFError:
                failure = 'worker_exited_without_result'; break
            if 'error' in sample:
                failure = sample['error']; break
            samples.append(sample)
            if len(samples) == 1 or len(samples) % 10 == 0:
                print(json.dumps({'event':'sample_progress','scenario':scenario,
                    'completed_samples':len(samples),'phase':sample['phase'],
                    'elapsed_ms':sample['elapsed_ms']}),flush=True)
    finally:
        if process.is_alive():
            process.join(1)
        if process.is_alive():
            process.terminate(); process.join(3)
        if process.is_alive():
            process.kill(); process.join()
        receiver.close()
    signatures = {s['result_sha256'] for s in samples}
    if len(signatures)>1:
        failure = 'inconsistent_results'
    warm = sorted(s['elapsed_ms'] for s in samples if s['phase']=='warm')
    return {'scenario':scenario,'threshold':threshold,'outcome':'failed' if failure else 'ok',
        'error':failure,'samples':samples,'warm_samples':len(warm),
        'p50_ms':warm[math.ceil(len(warm)*.5)-1] if warm else None,
        'p95_ms':warm[math.ceil(len(warm)*.95)-1] if len(warm)>=30 else None,
        'max_ms':max(warm) if warm else None}


def compare_reports(baseline, candidate):
    """Only compare equivalent successful workloads; ratios are candidate/base."""
    for key in ('warmups', 'repeats'):
        if baseline[key] != candidate[key]:
            raise ValueError(f'Comparison requires identical {key}')
    if baseline['fixture']['database_sha256'] != candidate['fixture']['database_sha256']:
        raise ValueError('Comparison requires the same fixture fingerprint')
    if not baseline.get('database_unchanged') or not candidate.get('database_unchanged'):
        raise ValueError('Comparison requires unchanged fixtures')
    def by_scenario(report):
        return {(r['scenario'],r['threshold']):r for r in report['results']}
    before, after = by_scenario(baseline), by_scenario(candidate)
    if before.keys() != after.keys():
        raise ValueError('Comparison requires identical scenarios and thresholds')
    ratios = []
    for key, row in after.items():
        old = before[key]
        if row['outcome'] != 'ok' or old['outcome'] != 'ok':
            raise ValueError('Cannot compare failed workloads as a speedup')
        old_signatures = {s['result_sha256'] for s in old['samples']}
        new_signatures = {s['result_sha256'] for s in row['samples']}
        if len(old_signatures) != 1 or old_signatures != new_signatures:
            raise ValueError(f'Query results changed for {key[0]}')
        ratios.append({'scenario':key[0],'threshold':key[1],**{
            metric+'_ratio':row[metric]/old[metric] if old[metric] and row[metric] is not None else None
            for metric in ('p50_ms','p95_ms','max_ms')}})
    return {'baseline_revision':baseline['revision'],'candidate_over_baseline':ratios}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='New result directory, never overwritten')
    parser.add_argument('--fixture',type=Path,help='Reuse a fixture directory produced by this tool')
    parser.add_argument('--baseline',type=Path,help='Prior report.json to compare; rejects changed inputs or results')
    parser.add_argument('--photos',type=int,default=250000)
    parser.add_argument('--profile',choices=PROFILES,default='sparse')
    parser.add_argument('--dense-photos',type=int,default=4096)
    parser.add_argument('--max-edges',type=int,default=250000)
    parser.add_argument('--seed',type=int,default=91)
    parser.add_argument('--revision',help='Code revision label when git is unavailable in the runtime')
    parser.add_argument('--threshold',type=int,choices=[75,80,85,90,95,100],default=90)
    parser.add_argument('--scenarios',nargs='+',choices=SCENARIOS,default=list(SCENARIOS))
    parser.add_argument('--warmups',type=int,default=1)
    parser.add_argument('--repeats',type=int,default=30)
    parser.add_argument('--timeout',type=float,default=30,help='Per-request worker deadline, including startup for first query')
    args = parser.parse_args()
    if not 100 <= args.photos <= 500000 or not 0 <= args.dense_photos <= 16384 or not 0 <= args.max_edges <= 1000000:
        parser.error('Use 100–500000 photos, 0–16384 dense photos and at most 1000000 edges')
    if not 0 <= args.warmups <= 10 or not 1 <= args.repeats <= 100 or not 0 < args.timeout <= 300:
        parser.error('Use 0–10 warmups, 1–100 repeats and a timeout of at most 300 seconds')
    args.output.mkdir(parents=True,exist_ok=False)
    fixture = args.fixture or args.output/'fixture'
    print(json.dumps({'event':'reuse_fixture' if args.fixture else 'build_fixture',
                      'photos':None if args.fixture else args.photos}),flush=True)
    manifest = json.loads((fixture/'manifest.json').read_text()) if args.fixture else build_fixture(
        fixture,args.photos,args.profile,args.seed,args.dense_photos,args.max_edges)
    db = fixture/'catalog.sqlite'
    if manifest.get('kind') != 'negativespace-synthetic-query-v1' or not fixture_unchanged(db,manifest):
        raise ValueError('Expected an unchanged synthetic fixture produced by this tool')
    try:
        revision = subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True).stdout.strip() or 'unknown'
        status = subprocess.run(['git','status','--porcelain'],capture_output=True,text=True)
        dirty = bool(status.stdout) if status.returncode == 0 else None
    except FileNotFoundError:
        revision, dirty = 'unknown', None
    report = {'revision':args.revision or revision,'working_tree_dirty':dirty,
        'runner_sha256':fingerprint(Path(__file__)),
        'python':sys.version.split()[0],'sqlite':sqlite3.sqlite_version,
        'memory_method':'Linux post-exec /proc/self/status VmHWM, sampled after query serialization',
        'fixture':manifest,'warmups':args.warmups,'repeats':args.repeats,
        'cache_note':'First request in new worker; OS/storage caches are not cold. Warm queries reopen connections.',
        'results':[]}
    report_path = args.output/'report.json'
    for scenario in args.scenarios:
        print(json.dumps({'event':'measure','scenario':scenario,'threshold':args.threshold}),flush=True)
        result = measure(db,scenario,args.threshold,args.warmups,args.repeats,args.timeout)
        report['results'].append(result)
        report_path.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k!='samples'}),flush=True)
    report['database_unchanged'] = fixture_unchanged(db,manifest)
    if args.baseline:
        try:
            report['comparison'] = compare_reports(json.loads(args.baseline.read_text()),report)
        except (ValueError, KeyError, OSError) as exc:
            report['comparison_error'] = str(exc)
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    return int(not report['database_unchanged'] or 'comparison_error' in report
               or any(r['outcome']!='ok' for r in report['results']))


if __name__ == '__main__':
    raise SystemExit(main())
