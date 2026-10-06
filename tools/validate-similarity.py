#!/usr/bin/env python3
"""Generate known image pairs, a browsable report, and a synthetic catalog benchmark.

Run inside the app image. Writes only to a NEW output directory and temporary
catalogs. No real photo library is read. Scores are diagnostic, not pass/fail gates:
cropping and flat colors deliberately expose perceptual-hash limitations.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
import random
import resource
import statistics
import sys
import tempfile
import time

import imagehash
from PIL import Image, ImageDraw, ImageEnhance

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import ns_db
from engine import ns_similarity
from webui import matching


def make_image(seed):
    rng = random.Random(seed)
    image = Image.new('RGB', (640, 480), tuple(rng.randrange(256) for _ in range(3)))
    draw = ImageDraw.Draw(image)
    for _ in range(35):
        x, y = rng.randrange(570), rng.randrange(410)
        bounds = (x, y, x+rng.randrange(15, 70), y+rng.randrange(15, 70))
        color = tuple(rng.randrange(256) for _ in range(3))
        (draw.ellipse if rng.random() < .5 else draw.rectangle)(bounds, fill=color)
    return image


def fixtures(out, samples):
    images = out / 'images'
    images.mkdir()
    hashes, pairs = {}, []
    def save(image, name, **kwargs):
        image.save(images / name, **kwargs)
        with Image.open(images / name) as decoded:
            hashes[name] = int(str(imagehash.phash(decoded)), 16)
        return name
    originals = []
    for i in range(samples):
        image = make_image(i)
        original = save(image, f'original-{i:03d}.png')
        originals.append(original)
        variants = [
            ('resize', image.resize((160,120)), 'png', {}),
            ('recompress', image, 'jpg', {'quality':35}),
            ('brightness', ImageEnhance.Brightness(image).enhance(.65), 'png', {}),
            ('crop', image.crop((100,75,540,405)), 'png', {}),
        ]
        for kind, variant, ext, options in variants:
            name = save(variant, f'{kind}-{i:03d}.{ext}', **options)
            pairs.append({'reference':original, 'candidate':name, 'expected':'same', 'kind':kind})
    for i, name in enumerate(originals):
        pairs.append({'reference':name, 'candidate':originals[(i+1) % samples], 'expected':'unrelated', 'kind':'different-scene'})
    red = save(Image.new('RGB',(640,480),'red'), 'flat-red.png')
    blue = save(Image.new('RGB',(640,480),'blue'), 'flat-blue.png')
    pairs.append({'reference':red,'candidate':blue,'expected':'unrelated','kind':'flat-color'})
    for pair in pairs:
        distance = (hashes[pair['reference']] ^ hashes[pair['candidate']]).bit_count()
        pair.update(distance=distance, score=(64-distance)*100/64)
    # Validate candidate retrieval independently against all pairwise distances.
    index = ns_similarity.HashIndex()
    for value in set(hashes.values()):
        index.add(value)
    for value in set(hashes.values()):
        expected = {(other,(value ^ other).bit_count()) for other in hashes.values() if (value ^ other).bit_count() <= ns_similarity.MAX_DISTANCE}
        if set(index.near(value)) != expected:
            raise AssertionError('Candidate index disagrees with exhaustive comparison')
    return pairs


def benchmark(size):
    rng = random.Random(91)
    print(f'Building a synthetic catalog with {size:,} photos…', file=sys.stderr, flush=True)
    with tempfile.TemporaryDirectory(prefix='ns-matching-benchmark-') as tmp:
        path = Path(tmp) / 'catalog.sqlite'
        ns_db.initialize(path)
        conn = ns_db.connect(path)
        try:
            run = ns_db.create_run(conn, mode='INDEX', source='/synthetic', destination='/destination')[0]
            delivery_run = ns_db.create_run(conn, mode='COPY', source='/synthetic', destination='/destination')[0]
            with ns_db.transaction(conn):
                for i in range(size):
                    if i % 5 == 0:
                        base = rng.getrandbits(64)
                    value = base ^ sum(1 << bit for bit in rng.sample(range(64), i % 5))
                    digest = hashlib.sha1(str(i).encode()).hexdigest()
                    source = f'/synthetic/photo-{i:06d}.jpg'
                    photo = conn.execute("INSERT INTO photos(source_path,status,sha1_hash,file_size) VALUES(?,'Pending',?,1000)", (source,digest)).lastrowid
                    ns_db.record_source_observation(conn, photo_id=photo,run_id=run,source_path=source,sha1_hash=digest,
                        file_size=1000,file_mtime=100,birthtime=None,metadata={},error=None)
                    ns_db.content_for_digest(conn,digest=digest,phash=f'{value:016x}',phash_state='ok',width=640,height=480)
                    destination = f'/destination/photo-{i:06d}.jpg'
                    op = conn.execute("INSERT INTO operations(run_id,photo_id,status,timestamp) VALUES(?,?,'Copied','test')",
                                      (delivery_run, photo)).lastrowid
                    ns_db.link_operation(conn, op, photo)
                    ns_db.record_delivery(conn, operation_id=op, photo_id=photo, run_id=delivery_run,
                        destination=destination, source_removed=False, created=True, sha1_hash=digest)
                    conn.execute("UPDATE photos SET status='Copied',dest_path=? WHERE id=?", (destination, photo))
            started = time.perf_counter()
            print('Comparing hashes…', file=sys.stderr, flush=True)
            ns_similarity.refresh(conn)
            initial = time.perf_counter()-started
            started = time.perf_counter()
            ns_similarity.refresh(conn)
            unchanged = time.perf_counter()-started
            new_hash = rng.getrandbits(64)
            while conn.execute('SELECT 1 FROM contents WHERE phash=?', (f'{new_hash:016x}',)).fetchone():
                new_hash = rng.getrandbits(64)
            with ns_db.transaction(conn):
                ns_db.content_for_digest(conn,digest='incremental',phash=f'{new_hash:016x}',phash_state='ok')
            started = time.perf_counter()
            ns_similarity.refresh(conn)
            incremental = time.perf_counter()-started
            stored = conn.execute('SELECT COUNT(*) FROM content_similarity').fetchone()[0]
            logical_bytes = conn.execute('PRAGMA page_count').fetchone()[0]*conn.execute('PRAGMA page_size').fetchone()[0]
            timings = {}
            reference_timings = {}
            for threshold in (ns_similarity.MIN_SCORE,90,100):
                print(f'Measuring queue and reference queries at {threshold}%…', file=sys.stderr, flush=True)
                elapsed = []
                for _ in range(7):
                    start = time.perf_counter()
                    result = matching.queue(path, threshold=threshold)
                    assert result['state']['photos'] == size, 'benchmark must include all delivered photos'
                    elapsed.append((time.perf_counter()-start)*1000)
                timings[str(threshold)] = {'first_ms':round(elapsed[0],2), 'median_ms':round(statistics.median(elapsed),2),
                                          'max_ms':round(max(elapsed),2)}
                elapsed = []
                for _ in range(7):
                    start = time.perf_counter()
                    matching.matches(path, 1, threshold=threshold)
                    elapsed.append((time.perf_counter()-start)*1000)
                reference_timings[str(threshold)] = {'first_ms':round(elapsed[0],2),
                    'median_ms':round(statistics.median(elapsed),2), 'max_ms':round(max(elapsed),2)}
            return {'photos':size,'scope':'destination','distribution':'seeded clusters of five hashes, each 0–4 bit flips from its seed',
                    'initial_comparison_seconds':round(initial,3),'unchanged_comparison_seconds':round(unchanged,3),
                    'one_new_hash_seconds':round(incremental,3),'stored_pairs':stored,'catalog_logical_bytes':logical_bytes,
                    'queue_ms':timings, 'reference_ms':reference_timings,
                    'process_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory; refuses an existing directory')
    parser.add_argument('--samples', type=int, default=16)
    parser.add_argument('--benchmark-photos', type=int, default=10000)
    args = parser.parse_args()
    if not 2 <= args.samples <= 100 or not 10 <= args.benchmark_photos <= 500000:
        parser.error('Use 2–100 samples and 10–500000 benchmark photos')
    args.output.mkdir(parents=True, exist_ok=False)
    pairs = fixtures(args.output, args.samples)
    metrics = {}
    for threshold in (ns_similarity.MIN_SCORE,90,100):
        tp = sum(p['expected']=='same' and p['score']>=threshold for p in pairs)
        fp = sum(p['expected']=='unrelated' and p['score']>=threshold for p in pairs)
        fn = sum(p['expected']=='same' and p['score']<threshold for p in pairs)
        metrics[str(threshold)] = {'true_positives':tp,'false_positives':fp,'false_negatives':fn,
                                  'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn)}
    report = {'scope':'Synthetic geometric images only; not a real-library accuracy estimate.',
              'retrieval_matches_brute_force':True,'quality':metrics,'benchmark':benchmark(args.benchmark_photos),'pairs':pairs}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
    cards = ''.join(f'''<article data-score="{p['score']}" data-expected="{p['expected']}">
      <h2>{html.escape(p['kind'])} · expected {p['expected']} · {p['score']:.2f}% ({p['distance']} bits)</h2>
      <div class="pair"><img loading="lazy" src="images/{p['reference']}" alt="Reference {p['reference']}">
      <img loading="lazy" src="images/{p['candidate']}" alt="Candidate {p['candidate']}"></div><p class="result"></p></article>''' for p in pairs)
    (args.output / 'index.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1"><title>Similarity validation</title>
      <style>body{font:16px system-ui;margin:24px;background:#f5f6f8;color:#20242b}main{max-width:1100px;margin:auto}
      .pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pair img{width:100%;height:240px;object-fit:contain;background:#111}
      article{padding:16px;border:1px solid #aab;margin:16px 0}h2{font-size:18px}.miss{border:3px solid #b42318}
      pre{overflow:auto}label{display:block;margin:12px 0}@media(max-width:600px){.pair{grid-template-columns:1fr}}</style>
      <main><h1>Similarity validation</h1><p>Synthetic fixtures, not a real-library accuracy estimate. Crops expose missed matches;
      flat colors expose false positives. Hash similarity is not confidence.</p>
      <label>Minimum similarity <input id="threshold" type="range" min="75" max="100" value="90"> <output id="value">90%</output></label>
      <label><input id="errors" type="checkbox"> Show only missed matches and false positives</label>
      <p id="summary" role="status"></p><details><summary>Benchmark and threshold metrics</summary><pre>'''
      + html.escape(json.dumps({k:v for k,v in report.items() if k!='pairs'}, indent=2))+'</pre></details>'+cards+'''
      </main><script>function update(){const t=Number(document.querySelector('#threshold').value);let missed=0,falsePos=0;
      document.querySelector('#value').textContent=t+'%';document.querySelectorAll('article').forEach(a=>{
      const found=Number(a.dataset.score)>=t,expected=a.dataset.expected==='same',wrong=found!==expected;
      if(wrong){if(expected)missed++;else falsePos++;}a.classList.toggle('miss',wrong);
      a.hidden=document.querySelector('#errors').checked&&!wrong;
      a.querySelector('.result').textContent=(found?'Offered as a match':'Below threshold')+(wrong?' — disagrees with known relationship':'');});
      document.querySelector('#summary').textContent=missed+' missed matches · '+falsePos+' false positives';}
      document.querySelectorAll('input').forEach(i=>i.addEventListener('input',update));update();</script></html>''')
    print(json.dumps({k:v for k,v in report.items() if k!='pairs'}, indent=2))


if __name__ == '__main__':
    main()
