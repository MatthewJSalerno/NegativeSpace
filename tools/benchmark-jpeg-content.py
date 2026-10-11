#!/usr/bin/env python3
"""Generated, local JPEG fingerprint experiment. JSON output; no library/catalog access.

Uses temporary generated files, checks actual bytes remain unchanged, and reports
warm local read timings separately from correctness. Not an Index/NFS benchmark.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import random
import statistics
import sys
import tempfile
import time
import tracemalloc

import PIL
from PIL import Image, ImageCms

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import jpeg_content_hash as jpeg


def encode(image, **options):
    out = io.BytesIO()
    image.save(out, 'JPEG', quality=90, **options)
    return out.getvalue()


def whole_hash(path, algorithm):
    digest = hashlib.new(algorithm)
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(jpeg.CHUNK_SIZE), b''):
            digest.update(chunk)
    return digest.hexdigest()


def median_ms(action, repeats):
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        action()
        samples.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(samples), 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error('--repeats must be 1–100')
    rows = []
    with tempfile.TemporaryDirectory(prefix='jpeg-generated-') as directory:
        root = Path(directory)
        for width, height in ((640, 480), (1920, 1080), (4000, 3000)):
            img = Image.frombytes('RGB', (width, height), random.Random(42).randbytes(width * height * 3))
            for progressive in (False, True):
                raw = encode(img, progressive=progressive)
                path = root / 'generated.custom'
                path.write_bytes(raw)
                before = path.stat()
                original = whole_hash(path, 'sha256')
                first = jpeg.hash_file(path)
                row = {'width': width, 'height': height, 'progressive': progressive,
                       'file_bytes': len(raw), 'scans': first.scans,
                       'whole_sha1_median_ms': median_ms(lambda: whole_hash(path, 'sha1'), args.repeats),
                       'whole_sha256_median_ms': median_ms(lambda: whole_hash(path, 'sha256'), args.repeats),
                       'jpeg_hash_median_ms': median_ms(lambda: jpeg.hash_file(path), args.repeats)}
                tracemalloc.start()
                verified = jpeg.hash_file(path)
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                row['hash_python_peak_bytes'] = peak
                if (first != verified or whole_hash(path, 'sha256') != original
                        or path.stat().st_mtime_ns != before.st_mtime_ns):
                    raise AssertionError('Hashing changed a fixture or was unstable')
                rows.append(row)
        # Check metadata independence as part of the benchmark, not only timings.
        small = Image.frombytes('RGB', (96, 64), random.Random(7).randbytes(96 * 64 * 3))
        original = encode(small)
        exif = Image.Exif()
        exif[274] = 6
        exif[306] = '2004:01:02 03:04:05'
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        variants = {'exif': encode(small, exif=exif), 'icc': encode(small, icc_profile=profile),
                    'density': encode(small, dpi=(300, 300))}
        stable = {}
        for name, raw in variants.items():
            stable[name] = (raw != original and jpeg.hash_bytes(raw).image_sha256 ==
                            jpeg.hash_bytes(original).image_sha256)
            if not stable[name]:
                raise AssertionError(f'Metadata changed image fingerprint: {name}')
    print(json.dumps({'profile': jpeg.PROFILE, 'pillow': PIL.__version__, 'repeats': args.repeats,
                      'generated_only': True, 'metadata_checks': stable, 'measurements': rows}, indent=2))


if __name__ == '__main__':
    main()
