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
benchmark timings. The production-schema measurement below includes these costs at 200,000 versions;
neither experiment is a full-library capacity prediction.

Schema 23 storage and backup tests cover byte restoration, deduplicated content with
independent arrivals, rollback/replay, corrupted payload refusal and oversized frame
headers. Index and resolved single-sidecar Copy/Move are connected; broader import decisions remain unfinished.


## Production-schema capacity measurement

Run `tools/benchmark-xmp-storage.py --catalog-versions 200000` in the app image.
This creates only generated metadata and logical file identities in the real schema,
retains each unique packet through `xmp_store.retain_capture`, and uses the real verified
catalog backup. It does not create photo files, scan shares, or benchmark gallery queries.
The packet profile is deliberately small: a distinct title, a date and two keywords.

One local Docker run on schema 26 measured:

| Measure | Result |
| --- | ---: |
| Unique retained and verified XMP versions | 200,000 |
| Original XML bytes | 94,288,890 |
| Compressed original BLOB bytes | 62,310,214 |
| Parsed fields and XML-structure JSON bytes | 494,666,670 |
| Checkpointed catalog bytes, including identities/indexes/arrivals | 885,190,656 |
| Retention time, FULL transactions of 1,000 versions | 20.83 s |
| Complete original-BLOB verification | 0.61 s |
| Verified catalog backup time | 5.04 s |
| Compressed backup bytes | 31,487,888 |

Parsed XML structure dominates compressed originals for these small packets. Compression
of original blobs alone does not control total catalog growth. One metadata edit batch now
prepares its versions before taking a single pre-action backup, avoiding a whole-catalog
snapshot per photo. These timings are single observations with warm local storage; real
packets, observation histories, photo rows, edits and slower backup storage add costs.
No compression setting or threshold was tuned to this fixture, and there is no 500,000-photo
capacity claim from a 200,000-version metadata-only measurement.
