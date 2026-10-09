# Generated XMP storage measurements

## Scope and reproduction

`tools/benchmark-xmp-storage.py` generates RDF/XML, validates it with the reader,
compares raw storage with Zstandard levels 1, 3, 6 and 10, and proves every byte round
trip. Run in the app image with the checkout mounted, substituting your own image tag:

```sh
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app:ro -w /app \
  negativespace python3 tools/benchmark-xmp-storage.py --repeats 7
```

The deterministic corpus covers small captions, keyword arrays, adjustment history,
large repeated text, large high-entropy text and a minimal RDF packet: 345 arrivals,
146 unique originals, 3,793,895 original bytes after deduplication. These are generated
profiles, not a representative census of a real library. The prototype SQLite table
holds only codec/payload; parsed metadata, indexes and production lineage add overhead.
No filesystem/share latency or photo decoding claim is made.

## Results

Measured with python-zstandard 0.25.0. Compression/restore columns are medians across
seven passes over all unique versions; SQLite write/read are single local observations,
not reliable latency predictions. Raw is kept when a frame would be larger.

| Level | Stored payload bytes | Compress ms | Restore ms | SQLite bytes | SQLite write/read ms | Whole SQLite backup bytes (Zstd 10) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw | 3,793,895 | 0.007 | 0.003 | 3,866,624 | 8.749 / 0.503 | 1,484,364 |
| 1 | 1,524,702 | 2.042 | 1.657 | 1,548,288 | 4.723 / 0.192 | 1,456,322 |
| 3 | 1,524,698 | 2.138 | 1.655 | 1,548,288 | 4.195 / 0.216 | 1,456,095 |
| 6 | 1,522,997 | 5.026 | 1.675 | 1,548,288 | 3.898 / 0.158 | 1,457,443 |
| 10 | 1,523,502 | 13.639 | 1.681 | 1,544,192 | 4.588 / 0.163 | 1,458,505 |

## Decision and limits

Use level 1, with a per-original raw fallback when compression is not smaller. It
saved about 60% of payload bytes here; level 3 saved only four further bytes, while
higher levels cost more for little additional saving. All compressed configurations
kept the minimal original raw. There is no user-facing compression setting or fixed
minimum-size threshold to fit this corpus, and no external dictionary dependency.

The additional reduction in an already-compressed backup was small (about 1.9% for
level 1); the primary benefit is working-catalog size. The production codec also checks
size/hash, verifies newly compressed representations, and verifies retained originals
at backup time. Those additional checks and parsed metadata costs are not in the codec
benchmark timings. Large-catalog backup time with many unique XMP versions remains to
be measured; no 200k/500k XMP capacity claim follows from this experiment.

Schema 23 storage and backup tests cover byte restoration, deduplicated content with
independent arrivals, rollback/replay, corrupted payload refusal and oversized frame
headers. Live Index/Copy/Move XMP integration remains unbuilt.
