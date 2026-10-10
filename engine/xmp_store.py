"""Catalog storage for retained XMP originals; no file publication or source cleanup.

Separate immutable content from arrivals and photo participants. Captures are parsed
again at this boundary; a caller-supplied MetadataSource cannot certify bytes as XMP.
Damaged captures may be retained for attention but never supply effective fields.
"""
import hashlib
import json

import zstandard

from engine import ns_db, xmp

# Generated XMP experiment: level 1 and 3 had nearly identical size, while higher
# levels cost more for little gain. Still store raw whenever compression is larger.
# See docs/xmp-storage-measurements.md; this is not a claim about every library.
COMPRESSION_LEVEL = 1
READER_VERSION = 2


class InvalidCapture(ValueError):
    """No complete, bounded metadata capture is available for retention."""


class InvalidBlob(ValueError):
    """Retained content cannot be reproduced exactly; do not publish it."""


def encode_original(data: bytes, *, level=COMPRESSION_LEVEL):
    """Binary storage primitive; retention separately enforces XMP classification."""
    if not isinstance(data, bytes) or not 0 < len(data) <= xmp.MAX_BYTES:
        raise InvalidCapture('Original metadata exceeds the size bound or is empty.')
    compressed = zstandard.ZstdCompressor(level=level, write_checksum=True).compress(data)
    codec, payload = ('zstd', compressed) if len(compressed) < len(data) else ('raw', data)
    digest = hashlib.sha256(data).hexdigest()
    # Prove the stored representation before it can join a committed arrival.
    if decode_original(codec, payload, len(data), digest) != data:
        raise InvalidBlob('Stored XMP did not round-trip.')
    return codec, payload, digest


def decode_original(codec, payload, original_size, digest):
    """Bounded single-frame decode; validate headers BEFORE allocating output."""
    if (type(original_size) is not int or not 0 < original_size <= xmp.MAX_BYTES
            or not isinstance(payload, bytes) or not 0 < len(payload) <= original_size
            or not isinstance(digest, str) or len(digest) != 64):
        raise InvalidBlob('Invalid XMP blob dimensions or digest.')
    try:
        if codec == 'raw':
            raw = payload
        elif codec == 'zstd':
            frame = zstandard.get_frame_parameters(payload)
            if (frame.content_size != original_size or frame.window_size > xmp.MAX_BYTES
                    or frame.dict_id or not frame.has_checksum):
                raise InvalidBlob('Unsupported or oversized XMP compression frame.')
            raw = zstandard.ZstdDecompressor().decompress(
                payload, max_output_size=original_size, allow_extra_data=False)
        else:
            raise InvalidBlob('Unknown XMP encoding.')
    except zstandard.ZstdError as exc:
        raise InvalidBlob('XMP decompression failed.') from exc
    if len(raw) != original_size or hashlib.sha256(raw).hexdigest() != digest:
        raise InvalidBlob('XMP content does not match its recorded size/hash.')
    return raw


def _blob_rows(conn, version_id=None):
    # Even a corrupt/tampered catalog must not return a multi-gigabyte payload to
    # Python before we can check it. SQLite length(BLOB) uses its stored length.
    sql = ('SELECT version_id,encoding,original_size,sha256,'
           'CASE WHEN original_size BETWEEN 1 AND ? AND length(payload) <= original_size '
           'THEN payload ELSE NULL END FROM xmp_versions')
    params = [xmp.MAX_BYTES]
    if version_id is not None:
        sql += ' WHERE version_id=?'
        params.append(version_id)
    return conn.execute(sql, params)


def original_bytes(conn, version_id):
    """Recover exact retained bytes, including damaged originals, without writing files.

    This does not approve a version for primary use; callers must check validation
    state and use the future verified activation/transfer workflow.
    """
    row = _blob_rows(conn, version_id).fetchone()
    if row is None:
        raise InvalidBlob('Unknown XMP version.')
    return decode_original(row[1], row[4], row[2], row[3])


def verify_blobs(conn):
    """Backup verification scans one bounded payload at a time, never all in memory."""
    count = 0
    for _, codec, size, digest, payload in _blob_rows(conn):
        decode_original(codec, payload, size, digest)
        count += 1
    return count


def retain_capture(conn, *, data, run_id, source_relative_path, file_ids,
                   role='candidate', basis='unresolved'):
    """Retain a captured sidecar in a caller-owned FULL transaction.

    Index binds tentative captures; it never activates a version. The caller binds
    run/path and participants from the full
    source inventory, not a request's claim. A same-run/path replay must match both
    bytes and participants. Settings/primary state are never changed by retention.
    An inner savepoint prevents orphan content if a caller catches a refused arrival.
    """
    if not conn.in_transaction or conn.execute('PRAGMA synchronous').fetchone()[0] != 2:
        raise RuntimeError('XMP retention requires a caller-owned FULL transaction.')
    path = xmp.relative_path(source_relative_path)
    if path.suffix.lower() != '.xmp':
        raise InvalidCapture('Expected a sidecar filename.')
    if (type(run_id) is not int or run_id <= 0 or not file_ids
            or any(type(i) is not int or i <= 0 for i in file_ids)
            or len(set(file_ids)) != len(file_ids)):
        raise InvalidCapture('Expected a run and unique photo file identities.')
    if (role, basis) not in {('candidate', 'unresolved'), ('owner', 'full_name'),
                             ('owner', 'declared_owner'), ('owner', 'single'),
                             ('owner', 'policy'), ('owner', 'confirmed')}:
        raise InvalidCapture('Invalid association evidence.')
    if not isinstance(data, bytes) or not 0 < len(data) <= xmp.MAX_BYTES:
        raise InvalidCapture('No complete bounded sidecar bytes to preserve.')
    capture = xmp.parse_bytes(data, source_id='capture')
    if capture.state == 'not_xmp' or capture.original_bytes is None:
        raise InvalidCapture(f'Sidecar is not retainable XMP: {capture.code}')
    if role == 'owner' and capture.state != 'valid':
        raise InvalidCapture('An unreadable sidecar cannot be a resolved metadata source.')
    digest = hashlib.sha256(data).hexdigest()
    participants = sorted((i, role, basis) for i in file_ids)
    conn.execute('SAVEPOINT retain_xmp')
    try:
        prior = conn.execute('SELECT a.arrival_id,a.version_id,v.sha256,v.validation_state '
                             'FROM xmp_arrivals a JOIN xmp_versions v USING(version_id) '
                             'WHERE a.run_id=? AND a.source_relative_path=?',
                             (run_id, source_relative_path)).fetchone()
        if prior:
            links = conn.execute('SELECT file_id,role,basis FROM xmp_arrival_files '
                                 'WHERE arrival_id=? ORDER BY file_id', (prior[0],)).fetchall()
            if prior[2] != digest or links != participants or original_bytes(conn, prior[1]) != data:
                raise InvalidCapture('This run/path already records a different capture or association.')
            result = {'arrival_id': prior[0], 'version_id': prior[1], 'state': prior[3], 'created': False}
        else:
            version = conn.execute('SELECT version_id,validation_state FROM xmp_versions WHERE sha256=?',
                                   (digest,)).fetchone()
            if version:
                if original_bytes(conn, version[0]) != data:
                    raise InvalidBlob('XMP content identity collision.')
                version_id, state = version
            else:
                codec, payload, _ = encode_original(data)
                fields = capture.source.fields if capture.source is not None else None
                state = capture.state
                version_id = conn.execute(
                    'INSERT INTO xmp_versions(sha256,encoding,original_size,payload,validation_state,'
                    'validation_code,reader_version,fields_json,tags_json) VALUES(?,?,?,?,?,?,?,?,?)',
                    (digest, codec, len(data), payload, state, capture.code, READER_VERSION,
                     json.dumps(fields, ensure_ascii=False, allow_nan=False) if fields is not None else None,
                     json.dumps(capture.tags, ensure_ascii=False, allow_nan=False))).lastrowid
            arrival_id = conn.execute(
                'INSERT INTO xmp_arrivals(version_id,run_id,source_relative_path,observed_at) VALUES(?,?,?,?)',
                (version_id, run_id, source_relative_path, ns_db.utc_now())).lastrowid
            conn.executemany('INSERT INTO xmp_arrival_files(arrival_id,file_id,role,basis) VALUES(?,?,?,?)',
                             [(arrival_id, *row) for row in participants])
            result = {'arrival_id': arrival_id, 'version_id': version_id, 'state': state, 'created': True}
        conn.execute('RELEASE retain_xmp')
        return result
    except BaseException:
        conn.execute('ROLLBACK TO retain_xmp')
        conn.execute('RELEASE retain_xmp')
        raise
