# JPEG image-content fingerprint experiment

Status: **generated-fixture prototype, not engine integration or deletion approval**.
`tools/jpeg_content_hash.py` is imported only by its tests and benchmark. No catalog
column, Index behavior, duplicate cleanup, photo editing or UI behavior is changed.

## Question and result

Can a second fingerprint distinguish unchanged encoded image content from changed
metadata? **Yes for the tested JPEG subset.** Twenty generated-fixture tests pass,
including actual ExifTool edits of baseline and progressive JPEGs. EXIF dates and
orientation, XMP caption/keywords, comments, assigned ICC profiles, JFIF density and
JFIF thumbnails can change while the encoded-image fingerprint stays stable.
Whole-file hashes and the separately reported metadata fingerprint detect those edits.

Changing the image, dimensions, crop, stored rotation, quality, subsampling, coding
headers or quantization/Huffman tables changes the fingerprint. A targeted experiment
changed only a quantization table: the compressed scan bytes stayed identical, but
Pillow decoded different pixels and the prototype correctly returned a different hash.
Hashing only the scan bytes would have missed that difference.

Metadata instructions remain distinct from image-data changes: the orientation fixture
has unchanged stored pixels but a different displayed orientation. The ICC fixtures
preserve exact assigned profile bytes separately and do not perform pixel conversion.
Testing assigned profiles does not demonstrate a production profile-restore workflow.

## Fingerprint definition and limits

Profile `jpeg-encoded-v1-experiment` uses SHA-256 with a versioned domain prefix.
This is an experimental identifier, not a change to existing whole-file SHA-1 identities.
It includes SOI/EOI, frame/scan headers, quantization and Huffman segments, restart
intervals/markers and all entropy-coded scans. It handles byte stuffing, marker padding,
and metadata between progressive scans. The stream is read in bounded buffers without
decoding, rewriting or recompressing the image.

Recognized EXIF/XMP APP1, ICC APP2 and comments are excluded from the image fingerprint
and hashed separately, in order. JFIF density and thumbnails are excluded, but JFIF's
presence is retained as decoding context. All Adobe APP14 bytes are retained, especially
its encoding/color-transform indicator. Assigning a profile is not the same operation
as changing the coding's color interpretation. Therefore stripping all APP blocks or
using a scan-only checksum is not this algorithm.

The prototype supports single-frame 8-bit grayscale/three-component Huffman baseline
and progressive JPEG framing. It refuses unknown APP blocks (including Photoshop/IPTC
resources not yet parsed), MPF/multiple-image and unfamiliar HDR-related layouts, CMYK,
arithmetic/lossless/other frame types, incomplete ICC segment sequences, trailing data,
truncation and basic structural failures. No fallback fingerprint is returned on refusal.
The tested extension-independent path reads a JPEG with a custom suffix successfully;
non-JPEG content fails regardless of the filename.

**This is not a full JPEG validator.** Marker/header framing checks do not verify every
entropy code, table reference, scan progression or the contents of EXIF/XMP/ICC payloads.
The tests independently decode valid fixtures with Pillow and read edited metadata with
ExifTool. Deliberately altered coding fixtures also test byte coverage without claiming
all alterations produce decodable images. Recognizing an APP signature is not validating
or preserving every embedded metadata object for reconstruction.

It is conservative encoded-content matching, not normalized pixel equality. A generated
optimized-Huffman JPEG decoded to exactly the same pixel bytes as its ordinary encoding
but produced a different fingerprint. Different table layouts, JFIF/Adobe context or
other coding variations may also miss a match. They must not be normalized casually to
increase deduplication. RAW/JPEG pairs and cross-format equality are outside scope.

## Measured cost

Generated deterministic RGB noise, quality 90, one fixture per size/encoding. Seven
warm local-read repetitions, Docker app image with Pillow 12.3.0. Times are medians;
fixture generation, ExifTool, decoding, catalog queries and network storage are excluded.
Whole-file reference hashes and the prototype each independently read the same file.
These are incremental standalone costs, not an integrated Index benchmark or a claim
about a real library's throughput.

| Dimensions | Encoding | File bytes | Whole SHA-1 ms | Whole SHA-256 ms | JPEG fingerprint ms |
| --- | --- | ---: | ---: | ---: | ---: |
| 640 × 480 | Baseline | 276,064 | 0.111 | 0.116 | 0.474 |
| 640 × 480 | Progressive | 251,668 | 0.101 | 0.106 | 0.738 |
| 1920 × 1080 | Baseline | 1,862,264 | 0.728 | 0.766 | 2.964 |
| 1920 × 1080 | Progressive | 1,698,105 | 0.664 | 0.698 | 5.358 |
| 4000 × 3000 | Baseline | 10,763,092 | 4.191 | 4.400 | 17.271 |
| 4000 × 3000 | Progressive | 9,814,040 | 3.811 | 4.007 | 30.287 |

Peak traced Python allocation during a separate hash pass was 198,237–198,361 bytes
(about 194 KiB). It excludes the fixture-generation allocations, process RSS, native
libraries and filesystem cache. Bounded-read tests additionally reject unbounded reads;
this is not a whole-engine memory measurement. All benchmark files had unchanged bytes
and modification times after hashing. Existing files are not rewritten by the tool.

## Reproduce and regression coverage

Run in an app image with this checkout mounted; substitute your own image tag:

```sh
docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app:ro -w /app \
  negativespace python3 -m unittest discover -s tests -p jpeg_content_hash_test.py -v

docker run --rm -e PUID=$(id -u) -e PGID=$(id -g) -v "$PWD":/app:ro -w /app \
  negativespace python3 tools/benchmark-jpeg-content.py --repeats 7
```

Both use generated temporary fixtures only. ExifTool is required, not silently skipped.
The tests cover metadata invariance, changed image/encoding data, progressive later
scans, restart/stuffed bytes across tiny buffer boundaries, multi-segment ICC framing,
unknown markers, truncated files, changed-during-read refusal, leaf symlink refusal and
read-only custom-extension files. The file wrapper is an experiment, not the engine's
complete directory-containment or source-deletion gate.

Two in-memory mutations verified the assertions: omitting quantization tables caused
the table-only change test to fail; incorrectly including metadata caused ten ExifTool
edit cases to fail. No production or prototype source was changed by these mutations.

## Before integration

- Define supported formats/markers explicitly and independently validate decoding and
  all preservation requirements. Never silently ignore unknown image-bearing extensions.
- Preserve complete metadata alternatives, including required profile data; build the
  primary/base-plus-field-override preview and verified write workflow.
- Persist a fingerprint profile/version and explicit unsupported/failure state. A hash
  is a candidate lookup key; verify equality before destructive operations.
- Measure integrated Index cost and format coverage with authorized sample fixtures;
  avoid redundant file reads if measurements justify sharing the existing read pass.
- Prove interruption/recovery and lineage before enabling consolidation. This experiment
  does not establish that a previous photo or metadata state can already be reproduced.

References: [JPEG/JFIF specification](https://www.w3.org/Graphics/JPEG/jfif3.pdf),
[ExifTool JPEG markers](https://exiftool.org/TagNames/JPEG.html),
[ExifTool MPF data](https://www.exiftool.org/TagNames/MPF.html),
and [ICC profile embedding](https://archive.color.org/files/technotes/ICC-Technote-ProfileEmbedding.pdf).
