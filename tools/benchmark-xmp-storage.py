#!/usr/bin/env python3
"""Generated XMP compression/SQLite BLOB experiment. No photo files or live catalog.

Run inside the app image; JSON goes to stdout. Temporary SQLite files are disposable.
Measures raw versus per-version Zstandard, plus already-compressed backup size.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import statistics
import sys
import tempfile
import time

import zstandard

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import xmp


def fixtures():
    rng = random.Random(734)
    samples = []
    def packet(text):
        return (f'<x:xmpmeta xmlns:x="{xmp.XMP_META}"><rdf:RDF xmlns:rdf="{xmp.RDF}">'
                f'<rdf:Description rdf:about="" xmlns:custom="urn:generated" xmlns:dc="{xmp.DC}">'
                f'{text}</rdf:Description></rdf:RDF></x:xmpmeta>').encode()
    for i in range(64):
        samples.append(('small', packet(f'<dc:description>Generated caption {i}</dc:description>')))
    for i in range(48):
        entries = ''.join(f'<rdf:li>keyword-{i}-{j}</rdf:li>' for j in range(160))
        samples.append(('keywords', packet('<dc:subject><rdf:Bag>' + entries + '</rdf:Bag></dc:subject>')))
    for i in range(24):
        entries = ''.join(f'<custom:step custom:id="{i}-{j}">generated adjustment {j}</custom:step>'
                          for j in range(800))
        samples.append(('history', packet('<custom:history>' + entries + '</custom:history>')))
    for i in range(8):
        # Large poorly-compressible text, legal XML, independent versions.
        text = base64.b64encode(rng.randbytes(180000)).decode()
        samples.append(('large_entropy', packet('<custom:data>' + text + '</custom:data>')))
        samples.append(('large_repeated', packet('<custom:data>' + ('generated data ' * 18000) + '</custom:data>')))
    samples.append(('minimal', f'<rdf:RDF xmlns:rdf="{xmp.RDF}"/>'.encode()))
    # One shared version can arrive repeatedly; timing/storage is per unique content.
    arrivals = samples + samples[:64] * 3
    unique = {hashlib.sha256(raw).hexdigest(): (profile, raw) for profile, raw in arrivals}
    return arrivals, list(unique.values())


def measure(samples, level, repeats):
    encode_times, decode_times = [], []
    packed = []
    for _ in range(repeats):
        compressor = zstandard.ZstdCompressor(level=level, write_checksum=True) if level else None
        start = time.perf_counter()
        packed = []
        for _, raw in samples:
            compressed = compressor.compress(raw) if compressor else raw
            use_zstd = len(compressed) < len(raw)
            packed.append(('zstd' if use_zstd else 'raw', compressed if use_zstd else raw))
        encode_times.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        for (_, raw), (codec, payload) in zip(samples, packed):
            restored = zstandard.ZstdDecompressor().decompress(payload, allow_extra_data=False) if codec == 'zstd' else payload
            assert restored == raw
        decode_times.append((time.perf_counter() - start) * 1000)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'blobs.db'
        conn = sqlite3.connect(path)
        conn.execute('CREATE TABLE blobs(id INTEGER PRIMARY KEY, codec TEXT, payload BLOB)')
        started = time.perf_counter()
        conn.executemany('INSERT INTO blobs(codec,payload) VALUES(?,?)', packed)
        conn.commit()
        write_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        assert sum(len(r[0]) for r in conn.execute('SELECT payload FROM blobs')) == sum(len(p) for _, p in packed)
        read_ms = (time.perf_counter() - started) * 1000
        conn.close()
        db = path.read_bytes()
    profile_sizes = {}
    for (profile, raw), (_, payload) in zip(samples, packed):
        row = profile_sizes.setdefault(profile, {'original_bytes': 0, 'stored_bytes': 0})
        row['original_bytes'] += len(raw)
        row['stored_bytes'] += len(payload)
    return {'level': level, 'stored_bytes': sum(len(p) for _, p in packed),
            'raw_versions': sum(codec == 'raw' for codec, _ in packed),
            'compress_median_ms': statistics.median(encode_times),
            'restore_median_ms': statistics.median(decode_times),
            'sqlite_write_ms': write_ms, 'sqlite_read_ms': read_ms,
            'sqlite_bytes': len(db),
            'backup_zstd10_bytes': len(zstandard.ZstdCompressor(level=10, write_checksum=True).compress(db)),
            'profiles': profile_sizes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=7)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    arrivals, samples = fixtures()
    for i, (_, raw) in enumerate(samples):
        result = xmp.parse_bytes(raw, source_id=str(i))
        if result.state != 'valid':
            raise RuntimeError(f'Generated fixture refused: {result.code}')
    result = {'generated': True, 'arrivals': len(arrivals), 'unique_versions': len(samples),
              'original_bytes': sum(len(raw) for _, raw in samples),
              'repeats': args.repeats, 'zstandard': zstandard.__version__,
              'scope': 'Prototype BLOB table only; excludes parsed metadata and production catalog overhead.',
              'results': [measure(samples, level, args.repeats) for level in (0, 1, 3, 6, 10)]}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
