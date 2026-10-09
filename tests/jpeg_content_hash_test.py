"""Generated JPEG experiment: not engine duplicate or restoration guarantees."""
import hashlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageCms, ImageOps
from tools import jpeg_content_hash as jpeg


def image_fixture(size=(96, 64), seed=42):
    return Image.frombytes('RGB', size, random.Random(seed).randbytes(size[0] * size[1] * 3))


def encoded(image=None, **options):
    output = io.BytesIO()
    (image if image is not None else image_fixture()).save(output, 'JPEG', quality=90, **options)
    return output.getvalue()


def segment(code, payload):
    return bytes((255, code)) + (len(payload) + 2).to_bytes(2, 'big') + payload


def inject(data, code, payload):
    return data[:2] + segment(code, payload) + data[2:]


def decoded(data):
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        return img.size, img.mode, img.tobytes()


def header(data, wanted):
    """Locate a generated fixture's pre-scan segment independently of the hasher."""
    offset = 2
    while offset < len(data):
        if data[offset] != 255:
            raise AssertionError('Bad fixture')
        code = data[offset + 1]
        length = int.from_bytes(data[offset + 2:offset + 4], 'big')
        if code == wanted:
            return offset, offset + 2 + length
        if code == 0xda:
            break
        offset += 2 + length
    raise AssertionError(f'Missing fixture marker {wanted:x}')


class JPEGHashTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = encoded()

    def digest(self, raw):
        return jpeg.hash_bytes(raw).image_sha256

    def exiftool(self, *args):
        result = subprocess.run(['exiftool', *args], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_real_exiftool_changes_only_metadata_for_baseline_and_progressive(self):
        for progressive in (False, True):
            for field, value in [('EXIF:DateTimeOriginal', '2004:02:29 12:34:56'),
                                 ('EXIF:Orientation#', '6'), ('XMP-dc:Description', '雪 & caption'),
                                 ('XMP-dc:Subject', 'keyword'), ('Comment', 'generated comment')]:
                with self.subTest(progressive=progressive, field=field):
                    raw = encoded(progressive=progressive)
                    path = self.root / 'generated.jpg'
                    path.write_bytes(raw)
                    self.exiftool('-overwrite_original', f'-{field}={value}', str(path))
                    changed = path.read_bytes()
                    self.assertNotEqual(hashlib.sha256(raw).digest(), hashlib.sha256(changed).digest())
                    self.assertEqual(decoded(raw), decoded(changed))
                    self.assertEqual(self.digest(raw), self.digest(changed))
                    self.assertNotEqual(jpeg.hash_bytes(raw).metadata_sha256,
                                        jpeg.hash_bytes(changed).metadata_sha256)
                    reported = json.loads(self.exiftool('-j', '-n', '-Warning', '-Error', str(path)))[0]
                    self.assertNotIn('Error', reported)
                    self.assertNotIn('Warning', reported)

    def test_exif_removal_leaves_content_hash_stable(self):
        path = self.root / 'exif.jpg'
        path.write_bytes(self.base)
        self.exiftool('-overwrite_original', '-EXIF:DateTimeOriginal=2004:01:02 03:04:05',
                      '-EXIF:Orientation#=8', str(path))
        with_exif = path.read_bytes()
        self.exiftool('-overwrite_original', '-EXIF:all=', str(path))
        without_exif = path.read_bytes()
        self.assertNotEqual(with_exif, without_exif)
        self.assertEqual(self.digest(with_exif), self.digest(without_exif))
        self.assertEqual(decoded(with_exif), decoded(without_exif))

    def test_orientation_changes_presentation_not_stored_pixels(self):
        exif = Image.Exif()
        exif[274] = 6
        rotated_instruction = encoded(exif=exif)
        self.assertEqual(self.digest(self.base), self.digest(rotated_instruction))
        with Image.open(io.BytesIO(rotated_instruction)) as img:
            self.assertEqual(ImageOps.exif_transpose(img).size, (64, 96))
        self.assertEqual(decoded(self.base), decoded(rotated_instruction))

    def test_actual_icc_profiles_can_change_without_changing_content_hash(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        altered = bytearray(profile)
        altered[64:68] = (1).to_bytes(4, 'big')  # ICC rendering intent, not pixel data.
        profiles = [profile, bytes(altered)]
        variants = [self.base]
        for raw_profile in profiles:
            ImageCms.ImageCmsProfile(io.BytesIO(raw_profile))  # Independent profile parsing.
            raw = encoded(icc_profile=raw_profile)
            with Image.open(io.BytesIO(raw)) as img:
                self.assertEqual(img.info['icc_profile'], raw_profile)
            self.assertEqual(decoded(raw), decoded(self.base))
            variants.append(raw)
        self.assertEqual(len({self.digest(raw) for raw in variants}), 1)
        self.assertEqual(len({jpeg.hash_bytes(raw).metadata_sha256 for raw in variants}), 3)

    def test_split_icc_sequence_and_missing_parts(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        halfway = len(profile) // 2
        data = inject(inject(self.base, 0xe2, jpeg.ICC + b'\x01\x02' + profile[:halfway]),
                      0xe2, jpeg.ICC + b'\x02\x02' + profile[halfway:])
        self.assertEqual(self.digest(data), self.digest(self.base))
        for part, total in ((0, 1), (2, 1), (1, 2)):
            with self.subTest(part=part, total=total), self.assertRaises(jpeg.UnsupportedJPEG):
                jpeg.hash_bytes(inject(self.base, 0xe2, jpeg.ICC + bytes((part, total)) + profile))
        repeated = inject(inject(self.base, 0xe2, jpeg.ICC + b'\x01\x01' + profile),
                          0xe2, jpeg.ICC + b'\x01\x01' + profile)
        with self.assertRaises(jpeg.UnsupportedJPEG):
            jpeg.hash_bytes(repeated)

    def test_dpi_and_embedded_thumbnail_are_not_main_image_data(self):
        for dpi in ((72, 72), (300, 300)):
            raw = encoded(dpi=dpi)
            self.assertEqual(self.digest(raw), self.digest(self.base))
        start, end = header(self.base, 0xe0)
        jfif = bytearray(self.base[start + 4:end])
        jfif[12:14] = b'\x01\x01'
        jfif.extend(b'\xff\x00\x00')
        raw = self.base[:start] + segment(0xe0, jfif) + self.base[end:]
        self.assertEqual(self.digest(raw), self.digest(self.base))
        self.assertEqual(decoded(raw), decoded(self.base))

    def test_changed_image_crop_quality_and_physical_rotation_change_hash(self):
        img = image_fixture()
        altered = img.copy()
        altered.paste((255, 0, 0), (0, 0, 32, 32))
        variants = [encoded(altered), encoded(img.crop((0, 0, 80, 64))),
                    encoded(img.transpose(Image.Transpose.ROTATE_90)), encoded(subsampling=0)]
        output = io.BytesIO()
        img.save(output, 'JPEG', quality=70)
        variants.append(output.getvalue())
        for raw in variants:
            self.assertNotEqual(self.digest(raw), self.digest(self.base))
            self.assertNotEqual(decoded(raw), decoded(self.base))

    def test_quantization_table_only_change_is_detected_and_changes_decoded_image(self):
        start, end = header(self.base, 0xdb)
        raw = bytearray(self.base)
        raw[start + 5] = min(255, raw[start + 5] * 2)
        self.assertNotEqual(raw[start:end], self.base[start:end])
        self.assertNotEqual(self.digest(raw), self.digest(self.base))
        self.assertNotEqual(decoded(raw), decoded(self.base))
        # The entropy-coded scan is unchanged: a scan-only hash would miss this.
        scan, _ = header(self.base, 0xda)
        self.assertEqual(raw[scan:], self.base[scan:])

    def test_frame_huffman_restart_and_adobe_encoding_bytes_are_included(self):
        for code, relative in ((0xc0, 8), (0xc4, 22)):
            start, end = header(self.base, code)
            raw = bytearray(self.base)
            self.assertLess(start + relative, end)
            raw[start + relative] ^= 1
            self.assertNotEqual(self.digest(raw), self.digest(self.base))
        for interval in (0, 1):
            raw = inject(self.base, 0xdd, interval.to_bytes(2, 'big'))
            self.assertNotEqual(self.digest(raw), self.digest(self.base))
        adobe = b'Adobe\x00\x64\x00\x00\x00\x00'
        one = inject(self.base, 0xee, adobe + b'\x00')
        two = inject(self.base, 0xee, adobe + b'\x01')
        self.assertNotEqual(self.digest(one), self.digest(two))

    def test_progressive_multiple_scans_and_metadata_between_scans(self):
        raw = encoded(progressive=True)
        self.assertGreater(jpeg.hash_bytes(raw).scans, 1)
        last_scan = raw.rfind(b'\xff\xda')
        inserted = raw[:last_scan] + segment(0xfe, b'between scans') + raw[last_scan:]
        self.assertEqual(self.digest(raw), self.digest(inserted))
        self.assertEqual(decoded(raw), decoded(inserted))
        # Later scan headers must contribute, not just the first scan.
        changed = bytearray(raw)
        changed[last_scan + 6] ^= 0x10  # Table selector; header remains framed.
        self.assertNotEqual(self.digest(raw), self.digest(changed))

    def test_restart_markers_and_stuffed_bytes_across_buffer_boundaries(self):
        raw = encoded(restart_marker_blocks=1)
        self.assertTrue(any(bytes((255, code)) in raw for code in range(0xd0, 0xd8)))
        self.assertIn(b'\xff\x00', raw)
        expected = self.digest(raw)
        for buffer_size in (1, 2, 3, 7, 16, 257):
            self.assertEqual(jpeg.hash_bytes(raw, buffer_size=buffer_size).image_sha256, expected)
        position = next(raw.index(bytes((255, code))) for code in range(0xd0, 0xd8)
                        if bytes((255, code)) in raw)
        changed = raw[:position + 1] + bytes((raw[position + 1] ^ 1,)) + raw[position + 2:]
        self.assertNotEqual(self.digest(changed), expected)

    def test_conservative_false_negative_when_coding_changes_without_pixel_change(self):
        ordinary = encoded()
        optimized = encoded(optimize=True)
        self.assertEqual(decoded(ordinary), decoded(optimized))
        self.assertNotEqual(self.digest(ordinary), self.digest(optimized))

    def test_custom_extension_uses_content_not_filename_and_file_is_untouched(self):
        path = self.root / 'generated.custom'
        path.write_bytes(self.base)
        path.chmod(0o444)
        before = path.stat()
        result = jpeg.hash_file(path)
        self.assertEqual(result.image_sha256, self.digest(self.base))
        self.assertEqual(result.bytes_read, len(self.base))
        self.assertEqual(path.read_bytes(), self.base)
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(path.stat().st_ctime_ns, before.st_ctime_ns)
        link = self.root / 'link.jpg'
        link.symlink_to(path)
        with self.assertRaises(OSError):
            jpeg.hash_file(link)

    def test_changed_during_read_is_refused(self):
        path = self.root / 'generated.jpg'
        path.write_bytes(self.base)
        original = jpeg.hash_stream
        def change(stream):
            result = original(stream)
            path.write_bytes(self.base + b'changed')
            return result
        with mock.patch.object(jpeg, 'hash_stream', side_effect=change), self.assertRaises(jpeg.UnsupportedJPEG):
            jpeg.hash_file(path)

    def test_unsupported_metadata_and_multiple_image_layouts_are_not_silently_ignored(self):
        cases = [(0xe1, b'unknown APP1'), (0xe2, b'MPF\0secondary image'),
                 (0xeb, b'JUMBF extra data'), (0xed, b'Photoshop 3.0\0unknown resource'),
                 (0xe0, b'JFXX\0extension')]
        for code, payload in cases:
            with self.subTest(code=code), self.assertRaises(jpeg.UnsupportedJPEG):
                jpeg.hash_bytes(inject(self.base, code, payload))
        for suffix in (b'junk', b'\0', self.base):
            with self.assertRaises(jpeg.UnsupportedJPEG):
                jpeg.hash_bytes(self.base + suffix)

    def test_malformed_truncated_non_jpeg_and_unsupported_frames_return_no_hash(self):
        png = io.BytesIO()
        image_fixture().save(png, 'PNG')
        cases = [b'', b'text', png.getvalue(), b'\xff\xd8\xff\xd9', self.base[:-1],
                 self.base[:-20], b'\xff\xd8\xff\xe1\x00\x01',
                 b'\xff\xd8\xff\xe1\xff\xffshort']
        frame, _ = header(self.base, 0xc0)
        arithmetic = self.base[:frame + 1] + b'\xc9' + self.base[frame + 2:]
        cases.append(arithmetic)
        for raw in cases:
            with self.subTest(size=len(raw)), self.assertRaises(jpeg.UnsupportedJPEG):
                jpeg.hash_bytes(raw)

    def test_marker_and_scan_safety_limits(self):
        with mock.patch.object(jpeg, 'MAX_MARKERS', 2), self.assertRaises(jpeg.UnsupportedJPEG):
            jpeg.hash_bytes(self.base)
        with mock.patch.object(jpeg, 'MAX_SCANS', 1), self.assertRaises(jpeg.UnsupportedJPEG):
            jpeg.hash_bytes(encoded(progressive=True))

    def test_grayscale_supported_and_cmyk_held_for_separate_validation(self):
        for progressive in (False, True):
            raw = encoded(image_fixture().convert('L'), progressive=progressive)
            self.assertEqual(jpeg.hash_bytes(raw).width, 96)
            self.assertEqual(self.digest(raw), self.digest(inject(raw, 0xfe, b'grayscale comment')))
            decoded(raw)
        with self.assertRaises(jpeg.UnsupportedJPEG):
            jpeg.hash_bytes(encoded(image_fixture().convert('CMYK')))

    def test_marker_like_bytes_inside_metadata_do_not_end_the_image(self):
        for code, payload in ((0xfe, b'\xff\xd9\xff\xda\xff\x00'),
                              (0xe1, jpeg.XMP + b'<generated>marker \xff\xd9</generated>')):
            raw = inject(self.base, code, payload)
            self.assertEqual(self.digest(raw), self.digest(self.base))

    def test_entropy_reads_are_bounded(self):
        class Bounded(io.BufferedReader):
            def read(self, size=-1):
                if size < 0 or size > jpeg.CHUNK_SIZE:
                    raise AssertionError('Unbounded read')
                return super().read(size)
        with Bounded(io.BytesIO(encoded(image_fixture((512, 512)))), buffer_size=127) as stream:
            jpeg.hash_stream(stream)


if __name__ == '__main__':
    unittest.main()
