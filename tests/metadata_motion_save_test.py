"""Verified metadata saves must retain motion video, checked against the builder manifest."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from PIL import Image
from engine import metadata_save, ns_db

REPO = Path(__file__).resolve().parent.parent
VIDEO_TAGS = {'google_legacy':'File:EmbeddedVideo', 'pixel':'Google:MotionPhotoVideo',
              'samsung':'Samsung:EmbeddedVideoFile'}
DATE = '2022-07-08T09:10:11'


class MotionMetadataSaves(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='ns-motion-save-'))
        cls.scenarios = cls.root / 'scenarios'
        result = subprocess.run([sys.executable, str(REPO/'tools/make_metadata_scenarios.py'),
            'build', '--out', str(cls.scenarios)], capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        manifest = json.loads((cls.scenarios/'manifest.json').read_text())
        cls.photos = [(case, photo) for case in manifest['cases'] for photo in case['photos']
                      if 'embedded_video' in photo]
        if {p['embedded_video']['variant'] for _,p in cls.photos} != set(VIDEO_TAGS):
            raise AssertionError('The manifest must cover all three motion-photo variants')

    @classmethod
    def tearDownClass(cls):
        if os.environ.get('NS_TEST_KEEP') != '1':
            # Generated fixtures include deliberately unreadable files/folders.
            from tools import make_scenarios
            make_scenarios.unlock(cls.root)
            shutil.rmtree(cls.root)

    def assert_video(self, path, manifest):
        expected = manifest['embedded_video']
        extracted = subprocess.run(['exiftool','-b','-ee',
            '-'+VIDEO_TAGS[expected['variant']],str(path)],capture_output=True,check=True).stdout
        self.assertGreater(expected['length'], 0)
        self.assertEqual((len(extracted),hashlib.sha1(extracted).hexdigest()),
                         (expected['length'],expected['sha1']),str(path))

    def engine(self, root, *flags, payload=None, expected=0):
        result = subprocess.run([sys.executable,'-m','engine','--workers','1',
            '--source',str(root/'source'),'--dest',str(root/'dest'),'--base',str(root/'base'),
            '--cache',str(root/'cache'),'--backups',str(root/'backups'),*flags],
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,text=True,timeout=120)
        self.assertEqual(result.returncode,expected,result.stdout+'\n'+result.stderr)
        return result

    def apply(self, root, edit, request, *, refuse_trailer=False):
        preview=json.loads(self.engine(root,'--metadata','preview',payload={'edits':[edit]}).stdout)['previews'][0]
        result=self.engine(root,'--metadata','apply','--request-id',request,
                    payload={'edits':[{**edit,'token':preview['token']}]},expected=1 if refuse_trailer else 0)
        if refuse_trailer:
            outcome=json.loads(result.stdout)['outcomes'][0]
            self.assertEqual(outcome['outcome'],'failed')
            self.assertIn('JPEG trailer or additional image',outcome['error'])
            self.assertFalse(outcome['metadata_saved'])
        return preview

    def save_all(self, kind):
        root=self.root/kind
        for folder in ('source','dest','base','cache','backups'):
            (root/folder).mkdir(parents=True)
        for case, photo in self.photos:
            for item in [photo,*case['sidecars']]:
                source=self.scenarios/'library'/item['path']
                shutil.copy2(source,root/'source'/source.name)
        originals={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'source').iterdir()}
        self.engine(root,'--copy')
        db=next((root/'base/db').glob('*.db'))
        with contextlib.closing(ns_db.connect(db)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM photos WHERE status='Copied'").fetchone()[0],3)
            for _,photo in self.photos:
                with self.subTest(kind=kind,variant=photo['embedded_video']['variant']):
                    source=root/'source'/Path(photo['path']).name
                    self.assert_video(source,photo)
                    pid=conn.execute('SELECT id FROM photos WHERE source_path=?',(str(source),)).fetchone()[0]
                    capture=conn.execute('SELECT MAX(m.capture_id) FROM metadata_captures m JOIN photo_files pf '
                        'ON pf.file_id=m.file_id WHERE pf.photo_id=?',(pid,)).fetchone()[0]
                    if kind != 'sidecar_xmp':
                        self.apply(root,{'photo_id':pid,'capture_id':capture,
                            'primary_id':'exif' if kind=='embedded_exif' else 'embedded_xmp'},f'choose-{pid}')
                    before_path=Path(conn.execute('SELECT dest_path FROM photos WHERE id=?',(pid,)).fetchone()[0])
                    before_bytes=before_path.read_bytes()
                    preview=self.apply(root,{'photo_id':pid,'capture_id':capture,
                        'changes':{'date_taken':DATE}},f'save-{pid}',refuse_trailer=kind!='sidecar_xmp')
                    self.assertEqual(preview['target']['kind'],kind)
                    self.assertTrue(preview['filing']['change'])
                    receipt=metadata_save.active(conn,pid)
                    destination=Path(conn.execute('SELECT dest_path FROM photos WHERE id=?',(pid,)).fetchone()[0])
                    self.assert_video(destination,photo)
                    if kind=='sidecar_xmp':
                        self.assertEqual(receipt['sources'][receipt['primary_id']]['fields']['date_taken'],DATE)
                        self.assertEqual(destination,root/'dest'/preview['filing']['proposed'])
                        self.assertEqual(destination.read_bytes(),source.read_bytes())
                    else:
                        # The qualified JPEG writer deliberately rejects all trailers.
                        # Keep this refusal tested until motion preservation is qualified.
                        self.assertEqual(destination,before_path)
                        self.assertEqual(destination.read_bytes(),before_bytes)
                        self.assertNotEqual(receipt['sources'][receipt['primary_id']]['fields'].get('date_taken'),DATE)
                    self.assertTrue(all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in originals.items()))

    def test_sidecar_saves_keep_all_motion_videos(self):
        self.save_all('sidecar_xmp')

    def test_embedded_xmp_refuses_motion_trailers_without_changing_files(self):
        self.save_all('embedded_xmp')

    def test_embedded_exif_refuses_motion_trailers_without_changing_files(self):
        self.save_all('embedded_exif')

    def test_video_check_detects_a_reencoded_photo(self):
        for _,photo in self.photos:
            with self.subTest(variant=photo['embedded_video']['variant']):
                source=self.scenarios/'library'/photo['path']
                self.assert_video(source,photo)
                rewritten=self.root/('reencoded-'+source.name)
                with Image.open(source) as image:
                    image.convert('RGB').save(rewritten)
                with self.assertRaises(AssertionError):
                    self.assert_video(rewritten,photo)
