"""Low-detail evidence never changes hashes or removes potential matches."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image
import imagehash

from engine import fileinfo, ns_db, ns_similarity


class HashEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'generated.png'

    def test_exact_hash_input_is_measured_with_one_decode(self):
        pixels = np.random.default_rng(42).integers(0, 256, (80, 120, 3), dtype=np.uint8)
        Image.fromarray(pixels).save(self.path)
        with Image.open(self.path) as photo:
            small = photo.convert('L').resize((32, 32), Image.Resampling.LANCZOS)
        expected_hash = str(imagehash.phash(small))
        gy, gx = np.gradient(np.asarray(small, dtype=float))
        measures = {}
        with mock.patch.object(fileinfo.deps.Image, 'open', wraps=Image.open) as opened:
            actual = fileinfo.compute_phash(str(self.path), measures=measures)
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(actual, expected_hash)
        self.assertAlmostEqual(measures['mean_brightness'], np.asarray(small).mean())
        self.assertAlmostEqual(measures['mean_gradient'], np.hypot(gx, gy).mean())

    def test_raw_measures_use_the_same_single_demosaic(self):
        pixels = np.random.default_rng(43).integers(0, 256, (80, 120, 3), dtype=np.uint8)
        raw = mock.MagicMock()
        raw.__enter__.return_value.postprocess.return_value = pixels
        measures = {}
        with mock.patch.object(fileinfo.deps.rawpy, 'imread', return_value=raw) as read:
            actual = fileinfo.compute_phash(str(self.path.with_suffix('.cr2')), measures=measures)
        self.assertEqual(actual, str(imagehash.phash(Image.fromarray(pixels))))
        self.assertEqual(read.call_count, 1)
        self.assertEqual(raw.__enter__.return_value.postprocess.call_count, 1)
        self.assertGreater(measures['mean_brightness'], 10)

    def test_decode_failure_does_not_leave_stale_measures(self):
        self.path.write_bytes(b'not an image')
        measures = {'mean_brightness': 1, 'mean_gradient': 0}
        self.assertEqual(fileinfo.compute_phash(str(self.path), measures=measures), 'error')
        self.assertEqual(measures, {})

    def test_strict_boundaries_and_unknown_measurements(self):
        for brightness, gradient, expected in ((9.99, 20, True), (100, 1.99, True),
                (10, 2, False), (150, 20, False), (None, None, False),
                (None, 1, True), (9, None, True)):
            with self.subTest(brightness=brightness, gradient=gradient):
                self.assertEqual(ns_similarity.is_low_detail(brightness, gradient), expected)

    def test_dark_and_bright_flat_photos_both_qualify(self):
        for brightness in (0, 9, 200, 255):
            Image.new('RGB', (80, 120), (brightness,)*3).save(self.path)
            measures = {}
            fileinfo.compute_phash(str(self.path), measures=measures)
            self.assertTrue(ns_similarity.is_low_detail(**measures))

    def test_content_identity_retains_evidence_when_later_scan_knows_less(self):
        db = Path(self.temp.name) / 'catalog.db'
        ns_db.initialize(db)
        conn = ns_db.connect(db)
        self.addCleanup(conn.close)
        with ns_db.transaction(conn):
            original = ns_db.content_for_digest(conn, digest='generated', phash='0000000000000000',
                phash_state='ok', mean_brightness=4.5, mean_gradient=3.5)
            again = ns_db.content_for_digest(conn, digest='generated')
        self.assertEqual(original, again)
        self.assertEqual(conn.execute('SELECT mean_brightness,mean_gradient FROM contents').fetchone(), (4.5, 3.5))


import webui_api_test as fixtures


class MatchEvidenceTests(fixtures.ApiCase):
    photo = fixtures.MatchingTests.photo
    refresh = fixtures.MatchingTests.refresh

    def setUp(self):
        super().setUp()
        self.create_catalog()
        self.conn = ns_db.connect(self.cfg.db_path)
        self.addCleanup(self.conn.close)
        self.run = ns_db.create_run(self.conn, mode='INDEX', source='/source', destination='/destination')[0]
        self.a = self.photo('night', 'a', '0000000000000000')
        self.b = self.photo('day', 'b', '0000000000000001')
        self.c = self.photo('ordinary', 'c', '0000000000000003')
        with ns_db.transaction(self.conn):
            self.conn.execute('UPDATE contents SET mean_brightness=100,mean_gradient=20')
            self.conn.execute("UPDATE contents SET mean_brightness=5 WHERE digest='a'")
        self.refresh()

    def test_either_photo_marks_match_without_changing_counts_or_groups(self):
        before = self.client.get('/api/v1/photos?view=similar&group_sets=true').json()
        counts = self.client.get(f'/api/v1/similar/{self.a}/counts').json()
        result = self.client.get(f'/api/v1/similar/{self.a}').json()
        self.assertEqual(result['total'], 2)
        self.assertTrue(result['reference']['low_detail'])
        self.assertTrue(all(p['low_detail_match'] for p in result['items']))
        self.assertTrue(all(not p['low_detail'] for p in result['items']))
        other = self.client.get(f'/api/v1/similar/{self.b}').json()
        self.assertEqual({p['id']: p['low_detail_match'] for p in other['items']}, {self.a:True, self.c:False})
        for first, second, expected in ((self.a,self.b,True),(self.b,self.a,True),(self.b,self.c,False)):
            pair=self.client.get(f'/api/v1/similar/{first}/pair/{second}').json()
            self.assertEqual(pair['low_detail_match'],expected)
        with ns_db.transaction(self.conn):
            self.conn.execute('UPDATE contents SET mean_brightness=100')
        self.assertEqual(self.client.get('/api/v1/photos?view=similar&group_sets=true').json(), before)
        self.assertEqual(self.client.get(f'/api/v1/similar/{self.a}/counts').json(), counts)
        self.assertFalse(self.client.get(f'/api/v1/similar/{self.a}').json()['items'][0]['low_detail_match'])

    def test_stats_counts_current_catalog_photos_not_history_or_duplicates(self):
        with ns_db.transaction(self.conn):
            ns_db.content_for_digest(self.conn,digest='historical',phash='0000000000000000',
                phash_state='ok',mean_brightness=1,mean_gradient=0)
        self.photo('source', 'source', '0000000000000000',status='Pending')
        self.photo('duplicate', 'a', '0000000000000000',status='Duplicate')
        self.photo('failed', 'failed', None,status='Failed')
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE contents SET mean_brightness=1,mean_gradient=0 WHERE digest IN ('source','failed')")
        result=self.client.get('/api/v1/stats')
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['health']['low_detail_photos'],2)

    def test_unknown_measurements_and_failed_hash_do_not_claim_low_detail(self):
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE contents SET mean_brightness=NULL,mean_gradient=NULL WHERE digest='a'")
        self.assertFalse(self.client.get(f'/api/v1/similar/{self.a}').json()['reference']['low_detail'])
        with ns_db.transaction(self.conn):
            self.conn.execute("UPDATE contents SET mean_brightness=1,phash_state='error' WHERE digest='a'")
        self.assertEqual(self.client.get('/api/v1/stats').json()['health']['low_detail_photos'],0)


from tools import make_scenarios
import metadata_index_test


class IndexEvidenceTests(unittest.TestCase):
    setUp = metadata_index_test.IndexTests.setUp
    run_engine = metadata_index_test.IndexTests.run_engine
    conn = metadata_index_test.IndexTests.conn

    def test_generated_night_scenarios_survive_index_copy_and_share_one_hash_input(self):
        paths=list(make_scenarios.low_detail_scenarios(self.root/'source/night'))
        self.run_engine('--copy')
        conn=self.conn()
        hashes={}
        for path, description in paths:
            row=conn.execute('SELECT p.status,c.phash,c.mean_brightness,c.mean_gradient FROM photos p '
                "JOIN contents c ON c.digest=p.sha1_hash AND c.hash_algorithm='sha1' WHERE source_path=?",(str(path),)).fetchone()
            self.assertEqual(row[0], 'Copied', description)
            measures={}
            self.assertEqual(row[1],fileinfo.compute_phash(str(path),measures=measures))
            self.assertEqual(row[2:],(measures['mean_brightness'],measures['mean_gradient']))
            self.assertTrue(ns_similarity.is_low_detail(*row[2:]))
            hashes[path.stem]=row[1]
        self.assertEqual(hashes['scn-low-detail-moon'],hashes['scn-low-detail-moon-brighter'])
        # This unrelated scene has the same coarse silhouette: a note, not a hidden match.
        self.assertEqual(hashes['scn-low-detail-moon'],hashes['scn-low-detail-lamp'])
        self.assertGreater((int(hashes['scn-low-detail-moon'],16)^int(hashes['scn-low-detail-city'],16)).bit_count(),6)
