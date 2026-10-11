"""Experimental encoded-JPEG fingerprint, generated-fixture research only.

Not imported by the engine. A fingerprint is a candidate lookup key, never proof
of full JPEG validity, metadata recoverability or permission to delete a file.
Do not normalize/re-encode pixels. Keep coding tables, frame/scan headers, restart
markers, JFIF interpretation and Adobe encoding information in the content hash.
"""
import hashlib
import io
import os
from pathlib import Path
import stat
from dataclasses import dataclass

PROFILE = 'jpeg-encoded-v1-experiment'
CHUNK_SIZE = 65536
MAX_MARKERS = 100000
MAX_SCANS = 4096
EXIF = b'Exif\0\0'
XMP = b'http://ns.adobe.com/xap/1.0/\0'
EXTENDED_XMP = b'http://ns.adobe.com/xmp/extension/\0'
ICC = b'ICC_PROFILE\0'


class UnsupportedJPEG(ValueError):
    """No fingerprint is returned for unsupported, incomplete or unstable input."""


@dataclass(frozen=True)
class Fingerprint:
    profile: str
    image_sha256: str
    metadata_sha256: str
    width: int
    height: int
    scans: int
    metadata_segments: int
    bytes_read: int


class _Reader:
    def __init__(self, stream):
        self.stream = stream
        self.bytes_read = 0

    def exact(self, size):
        data = self.stream.read(size)
        self.bytes_read += len(data)
        if len(data) != size:
            raise UnsupportedJPEG('truncated_segment')
        return data

    def marker(self):
        if self.exact(1) != b'\xff':
            raise UnsupportedJPEG('expected_marker')
        code = self.exact(1)[0]
        # Marker padding carries no image information; cap abusive padding runs.
        padding = 0
        while code == 0xff:
            padding += 1
            if padding > CHUNK_SIZE:
                raise UnsupportedJPEG('excessive_marker_padding')
            code = self.exact(1)[0]
        if code == 0:
            raise UnsupportedJPEG('stuffed_byte_outside_scan')
        return code

    def entropy(self, digest):
        """Stream stuffed bytes/restart markers; return the next structural marker.

        BufferedReader.peek avoids a Python loop over every entropy byte. The only
        per-byte work is at FF boundaries; no whole image is retained in memory.
        """
        while True:
            block = self.stream.peek(CHUNK_SIZE)[:CHUNK_SIZE]
            if not block:
                raise UnsupportedJPEG('missing_end_of_image')
            boundary = block.find(b'\xff')
            if boundary < 0:
                digest.update(self.exact(len(block)))
                continue
            if boundary:
                digest.update(self.exact(boundary))
            self.exact(1)
            code = self.exact(1)[0]
            if code == 0:
                digest.update(b'\xff\x00')
                continue
            padding = 0
            while code == 0xff:
                padding += 1
                if padding > CHUNK_SIZE:
                    raise UnsupportedJPEG('excessive_marker_padding')
                code = self.exact(1)[0]
            if code == 0:
                raise UnsupportedJPEG('invalid_entropy_padding')
            if 0xd0 <= code <= 0xd7:
                digest.update(bytes((0xff, code)))
                continue
            return code


def hash_stream(stream):
    """Hash one bounded-buffer, single-frame 8-bit Huffman JPEG stream.

    Caller supplies a BufferedReader; read-only input need not have a JPEG suffix.
    This checks framing and a conservative marker subset, not entropy correctness.
    A separate decoder/validation gate is required before any future consolidation.
    """
    reader = _Reader(stream)
    if reader.exact(2) != b'\xff\xd8':
        raise UnsupportedJPEG('not_jpeg')
    image = hashlib.sha256(PROFILE.encode() + b'\0\xff\xd8')
    metadata = hashlib.sha256(PROFILE.encode() + b'\0metadata\0')
    frame = None
    scans = metadata_segments = 0
    quantization = huffman = False
    icc_parts = set()
    icc_total = None
    jfif_seen = adobe_seen = False
    pending = None
    for _ in range(MAX_MARKERS):
        code = reader.marker() if pending is None else pending
        pending = None
        if code == 0xd9:
            if frame is None or not scans:
                raise UnsupportedJPEG('missing_frame_or_scan')
            if icc_total is not None and icc_parts != set(range(1, icc_total + 1)):
                raise UnsupportedJPEG('incomplete_icc_profile')
            if stream.read(1):
                raise UnsupportedJPEG('trailing_data_or_additional_image')
            image.update(b'\xff\xd9')
            return Fingerprint(PROFILE, image.hexdigest(), metadata.hexdigest(),
                               frame[1], frame[2], scans, metadata_segments, reader.bytes_read)
        if code not in (0xc0, 0xc2, 0xc4, 0xdb, 0xdd, 0xda, 0xfe, *range(0xe0, 0xf0)):
            raise UnsupportedJPEG(f'unsupported_marker_{code:02x}')
        length_bytes = reader.exact(2)
        length = int.from_bytes(length_bytes, 'big')
        if length < 2:
            raise UnsupportedJPEG('invalid_segment_length')
        payload = reader.exact(length - 2)
        segment = bytes((0xff, code)) + length_bytes + payload
        ancillary = False
        if code == 0xe0:
            if (jfif_seen or not payload.startswith(b'JFIF\0') or len(payload) < 14
                    or payload[5] != 1 or payload[6] > 2
                    or len(payload) != 14 + 3 * payload[12] * payload[13]):
                raise UnsupportedJPEG('unsupported_app0')
            jfif_seen = True
            # JFIF implies color interpretation. Density and its thumbnail don't
            # define the main image, but the presence of JFIF cannot be discarded.
            image.update(b'\xff\xe0JFIF\0')
            ancillary = True
        elif code == 0xe1:
            if not payload.startswith((EXIF, XMP, EXTENDED_XMP)):
                raise UnsupportedJPEG('unsupported_app1')
            ancillary = True
        elif code == 0xe2:
            if not payload.startswith(ICC) or len(payload) < 14:
                raise UnsupportedJPEG('unsupported_app2')
            part, total = payload[12:14]
            if not 1 <= part <= total or part in icc_parts or icc_total not in (None, total):
                raise UnsupportedJPEG('invalid_icc_sequence')
            icc_total = total
            icc_parts.add(part)
            ancillary = True
        elif code == 0xee:
            if adobe_seen or len(payload) != 12 or not payload.startswith(b'Adobe'):
                raise UnsupportedJPEG('unsupported_adobe_segment')
            adobe_seen = True
            # Preserve all APP14 bytes conservatively, especially ColorTransform.
        elif 0xe0 <= code <= 0xef:
            raise UnsupportedJPEG(f'unsupported_app_{code - 0xe0}')
        elif code == 0xfe:
            ancillary = True
        elif code in (0xc0, 0xc2):
            if frame is not None or len(payload) < 6 or payload[0] != 8:
                raise UnsupportedJPEG('unsupported_frame')
            height = int.from_bytes(payload[1:3], 'big')
            width = int.from_bytes(payload[3:5], 'big')
            count = payload[5]
            if not width or not height or count not in (1, 3) or len(payload) != 6 + 3 * count:
                raise UnsupportedJPEG('unsupported_frame')
            ids = payload[6::3]
            if len(set(ids)) != count:
                raise UnsupportedJPEG('duplicate_components')
            frame = (code, width, height, ids)
        elif code == 0xdb:
            if not payload:
                raise UnsupportedJPEG('empty_quantization_table')
            quantization = True
        elif code == 0xc4:
            if not payload:
                raise UnsupportedJPEG('empty_huffman_table')
            huffman = True
        elif code == 0xdd and len(payload) != 2:
            raise UnsupportedJPEG('invalid_restart_interval')
        elif code == 0xda:
            if frame is None or not quantization or not huffman or not payload:
                raise UnsupportedJPEG('scan_without_required_headers')
            count = payload[0]
            if count == 0 or len(payload) != 4 + 2 * count:
                raise UnsupportedJPEG('invalid_scan_header')
            ids = payload[1:1 + 2 * count:2]
            if len(set(ids)) != count or not set(ids) <= set(frame[3]):
                raise UnsupportedJPEG('invalid_scan_components')
            scans += 1
            if scans > MAX_SCANS:
                raise UnsupportedJPEG('scan_limit')
        if ancillary:
            metadata.update(segment)
            metadata_segments += 1
        else:
            image.update(segment)
        if code == 0xda:
            pending = reader.entropy(image)
    raise UnsupportedJPEG('marker_limit')


def hash_bytes(data, *, buffer_size=CHUNK_SIZE):
    with io.BufferedReader(io.BytesIO(data), buffer_size=buffer_size) as stream:
        return hash_stream(stream)


def hash_file(path: Path):
    """Experimental read-only regular-file wrapper; no source/deletion authorization."""
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb', buffering=CHUNK_SIZE) as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise UnsupportedJPEG('not_regular')
        result = hash_stream(stream)
        after = os.fstat(stream.fileno())
        named = os.stat(path, follow_symlinks=False)
        def signature(info):
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
        if signature(before) != signature(after) or signature(after) != signature(named):
            raise UnsupportedJPEG('changed_during_read')
        return result
