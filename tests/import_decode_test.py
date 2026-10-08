"""Pixel eligibility is independent of EXIF, hash calculation and cache output."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from engine import deps, fileinfo, runtime, scan
from engine.ns_db import PhotoStatus


class ImportDecodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.photo = Path(self.temp.name) / "photo.jpg"
        Image.new("RGB", (80, 60), "blue").save(self.photo)

    def test_readable_pixels_survive_hash_and_cache_failure(self):
        with patch.object(deps.imagehash, "phash", side_effect=RuntimeError("hash unavailable")), \
             patch.object(scan.thumbnails, "generate_thumbnail", return_value=runtime.ThumbnailResult(
                 availability="failed", failure_category="cache_write_failed", failure_detail="cache read-only")):
            result = scan.process_file_task(str(self.photo), "/data/dest", 1, self.temp.name)
        self.assertEqual(result.status, PhotoStatus.PENDING)
        self.assertEqual(result.phash, "error")
        self.assertEqual(result.thumbnail.failure_category, "cache_write_failed")
        self.assertEqual(result.metadata["date_source"], "file_mtime")

    def test_unavailable_hash_library_does_not_block_readable_pixels(self):
        with patch.object(deps, "IMAGEHASH_SUPPORTED", False):
            result = scan.process_file_task(str(self.photo), "/data/dest", 1)
        self.assertEqual(result.status, PhotoStatus.PENDING)
        self.assertEqual(result.phash, "not_supported")

    def test_good_hash_avoids_a_redundant_decode(self):
        with patch.object(fileinfo, "image_decode_error", side_effect=AssertionError("extra decode")):
            result = scan.process_file_task(str(self.photo), "/data/dest", 1)
        self.assertEqual(result.status, PhotoStatus.PENDING)

    def test_unavailable_decoder_is_actionable_without_claiming_non_image(self):
        with patch.object(deps, "PIL_SUPPORTED", False):
            result = scan.process_file_task(str(self.photo), "/data/dest", 1)
        self.assertEqual(result.status, PhotoStatus.FAILED)
        self.assertIn("Cannot decode image: Pillow is not installed", result.error_message)
        self.assertIn("Left in the source", result.error_message)
        self.assertNotIn("Not an image", result.error_message)
