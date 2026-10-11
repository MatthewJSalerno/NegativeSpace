"""Generated Index provenance integration, read safety and source-priority regressions."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image
import zstandard
from engine import fileinfo, metadata_capture, metadata_index, ns_db, runtime, xmp, xmp_store


def packet(date='2005-03-04T05:06:07', extra=''):
    return (f'<rdf:RDF xmlns:rdf="{xmp.RDF}" xmlns:exif="{xmp.EXIF}" xmlns:tiff="{xmp.TIFF}">'
            f'<rdf:Description rdf:about=""><exif:DateTimeOriginal>{date}</exif:DateTimeOriginal>'
            f'{extra}</rdf:Description></rdf:RDF>').encode()


class CaptureTests(unittest.TestCase):
    def test_qualified_instances_keep_conflicting_groups_separate(self):
        result = metadata_capture.interpret({'ExifIFD:DateTimeOriginal':'1999:01:02 03:04:05',
            'XMP-exif:Copy1:DateTimeOriginal':'2004:02:03 04:05:06',
            'MakerNotes:Copy2:DateTimeOriginal':'2010:01:01 00:00:00', 'IFD1:Orientation':'8'})
        self.assertEqual(result['issues'], [])
        self.assertEqual(result['sources']['exif']['fields'], {'date_taken':'1999-01-02T03:04:05'})
        self.assertEqual(result['sources']['embedded_xmp']['fields'], {'date_taken':'2004-02-03T04:05:06'})
        self.assertIn('MakerNotes:Copy2:DateTimeOriginal', result['tags'])

    def test_empty_embedded_keyword_literal_stays_empty(self):
        result=metadata_capture.interpret({'XMP-dc:Subject':''})
        self.assertEqual(result['sources']['embedded_xmp']['fields']['keywords'],'')

    def test_same_source_conflicts_are_not_collapsed(self):
        result = metadata_capture.interpret({'ExifIFD:DateTimeOriginal':'1999:01:02 03:04:05',
                                             'ExifIFD:Copy1:DateTimeOriginal':'2004:01:01 00:00:00'})
        self.assertEqual(result['issues'], [{'source':'exif','code':'ambiguous_embedded_exif'}])
        self.assertNotIn('exif', result['sources'])
        result = metadata_capture.interpret({'XMP-tiff:Orientation':'1','XMP-tiff:Copy1:Orientation':'6'})
        self.assertEqual(result['issues'][0]['code'], 'ambiguous_embedded_xmp')

    def test_empty_partial_and_explicit_choice_never_silently_fall_back(self):
        for value in ('', '2005', '2005-03'):
            sources = {'exif': {'fields':{'date_taken':'1999-01-01'}},
                       'embedded_xmp': {'fields':{'date_taken':'2004-01-01','camera_make':'Camera'}},
                       'sidecar': {'fields':{'date_taken':value}}}
            result = metadata_capture.resolve(sources, ['sidecar','embedded_xmp','exif'])
            self.assertEqual(result['proposed_effective'], {'date_taken':value,'camera_make':'Camera'})
            self.assertEqual(result['field_sources']['date_taken'], 'sidecar')
            explicit = metadata_capture.resolve(sources, ['sidecar','embedded_xmp','exif'], primary_id='exif')
            self.assertEqual(explicit['proposed_effective'], {'date_taken':'1999-01-01'})
            self.assertFalse(explicit['applied'])
        with self.assertRaises(ValueError):
            metadata_capture.resolve(sources, ['sidecar'], primary_id='missing')

    def test_descriptor_reader_refuses_symlink_leaf_parent_and_nonregular(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'real').mkdir(); (root/'real/photo.jpg').write_bytes(b'fixture')
            (root/'link').symlink_to(root/'real', target_is_directory=True)
            (root/'photo.jpg').symlink_to(root/'real/photo.jpg')
            os.mkfifo(root/'pipe.jpg')
            with mock.patch.object(fileinfo, '_worker_exiftool') as reader:
                for name in ('photo.jpg','link/photo.jpg','pipe.jpg'):
                    result = metadata_capture.capture_photo(root, name, 7, 0)
                    self.assertTrue(result['issues'])
                reader.get_metadata.assert_not_called()
            with self.assertRaises(ValueError):
                with metadata_capture.open_source(root, '../outside.jpg'):
                    pass

    def test_changing_photo_drops_the_unstable_capture(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); photo=root/'photo.jpg'; photo.write_bytes(b'fixture'); before=photo.stat()
            def changed(*args, **kwargs):
                photo.write_bytes(b'changed longer')
                return [{'IFD0:Make':'Camera'}]
            with mock.patch.object(fileinfo, '_worker_exiftool') as reader:
                reader.get_metadata.side_effect=changed
                result=metadata_capture.capture_photo(root,'photo.jpg',before.st_size,before.st_mtime)
            self.assertEqual(result['sources'], {})
            self.assertEqual(result['issues'][0]['code'], 'changed_during_read')

    def test_cached_capture_needs_identical_identity_and_force_bypasses_it(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); photo=root/'photo.jpg'; photo.write_bytes(b'fixture'); info=photo.stat()
            previous=dict(metadata_capture.interpret({'IFD0:Make':'Camera'}), signature=metadata_capture.signature(info))
            with mock.patch.object(fileinfo, '_worker_exiftool') as reader:
                self.assertEqual(metadata_capture.capture_photo(root,'photo.jpg',info.st_size,info.st_mtime,previous),previous)
                reader.get_metadata.assert_not_called()
                reader.get_metadata.return_value=[{'IFD0:Make':'Refreshed'}]
                forced=metadata_capture.capture_photo(root,'photo.jpg',info.st_size,info.st_mtime,previous,True)
                self.assertEqual(forced['sources']['exif']['fields']['camera_make'],'Refreshed')

    def test_unknown_and_localized_embedded_fields_keep_evidence(self):
        result=metadata_capture.interpret({'XMP-dc:Description':'Default','XMP-dc:Description-fr':'Français',
            'XMP-dc:Subject':['two','one'],'XMP-custom:Unknown':{'nested':'retained'}})
        self.assertEqual(result['sources']['embedded_xmp']['fields']['caption'], {'x-default':'Default','fr':'Français'})
        self.assertEqual(result['sources']['embedded_xmp']['fields']['keywords'], ['two','one'])
        self.assertEqual(result['tags']['XMP-custom:Unknown'], {'nested':'retained'})


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for name in ('source','dest','base','cache','backups'):
            (self.root/name).mkdir()
        self.photo=self.root/'source/photo.jpg'
        Image.new('RGB',(48,32),(10,20,30)).save(self.photo)
        subprocess.run(['exiftool','-overwrite_original','-EXIF:DateTimeOriginal=1999:01:02 03:04:05',
                        '-XMP-exif:DateTimeOriginal=2004:02:03 04:05:06',str(self.photo)],check=True,capture_output=True)
        self.sidecar=self.root/'source/photo.jpg.xmp'
        self.sidecar.write_bytes(packet())

    def run_engine(self,*args):
        proc=subprocess.run([sys.executable,'-m','engine','--source',str(self.root/'source'),
            '--dest',str(self.root/'dest'),'--base',str(self.root/'base'),'--cache',str(self.root/'cache'),
            '--backups',str(self.root/'backups'),'--workers','1',*args],capture_output=True,text=True,timeout=90)
        self.assertEqual(proc.returncode,0,proc.stdout+'\n'+proc.stderr)
        return proc.stdout+proc.stderr

    def conn(self):
        path=next((self.root/'base/db').glob('*.db'))
        conn=ns_db.connect(path,synchronous='FULL'); self.addCleanup(conn.close)
        return conn

    def latest(self,conn):
        row=conn.execute('SELECT embedded_json,report_json FROM metadata_captures ORDER BY capture_id DESC LIMIT 1').fetchone()
        self.assertIsNotNone(row)
        return json.loads(row[0]),json.loads(row[1])

    def test_actual_index_captures_three_sources_without_changing_filing_or_bytes(self):
        before=[p.read_bytes() for p in (self.photo,self.sidecar)]
        self.run_engine(); conn=self.conn(); embedded,report=self.latest(conn)
        self.assertEqual(report['state'],'captured')
        self.assertEqual(report['resolution']['proposed_effective']['date_taken'],'2005-03-04T05:06:07')
        self.assertEqual(report['resolution']['field_sources']['date_taken'],'sidecar:photo.jpg.xmp')
        self.assertEqual(embedded['sources']['exif']['fields']['date_taken'],'1999-01-02T03:04:05')
        self.assertEqual(embedded['sources']['embedded_xmp']['fields']['date_taken'],'2004-02-03T04:05:06')
        self.assertFalse(report['applied'])
        photo_meta,dest=conn.execute('SELECT metadata_json,dest_path FROM photos').fetchone()
        self.assertNotIn('2005',dest)
        self.assertNotIn('proposed_effective',json.loads(photo_meta))
        version=conn.execute('SELECT version_id FROM xmp_versions').fetchone()[0]
        self.assertEqual(xmp_store.original_bytes(conn,version),before[1])
        self.assertEqual([p.read_bytes() for p in (self.photo,self.sidecar)],before)
        self.assertEqual(list((self.root/'dest').iterdir()),[])
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM source_snapshots').fetchone()[0],1)

    def test_reindex_is_idempotent_but_sidecar_only_change_is_captured(self):
        self.run_engine(); conn=self.conn()
        before=conn.execute('SELECT COUNT(*) FROM metadata_captures').fetchone()[0]
        self.run_engine()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM metadata_captures').fetchone()[0],before)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM xmp_arrivals').fetchone()[0],1)
        self.sidecar.write_bytes(packet('2006'))
        self.run_engine()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM metadata_captures').fetchone()[0],before+1)
        self.assertEqual(self.latest(conn)[1]['resolution']['proposed_effective']['date_taken'],'2006')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0],2)

    def test_blank_sidecar_and_embedded_values_have_priority(self):
        self.sidecar.write_bytes(packet(''))
        self.run_engine(); conn=self.conn()
        self.assertEqual(self.latest(conn)[1]['resolution']['proposed_effective']['date_taken'],'')
        self.sidecar.unlink()  # Generated test fixture only.
        self.run_engine()
        self.assertEqual(self.latest(conn)[1]['resolution']['proposed_effective']['date_taken'],'2004-02-03T04:05:06')

    def test_ambiguous_sidecar_checks_sibling_outside_extension_filter(self):
        self.sidecar.rename(self.root/'source/photo.xmp')
        (self.root/'source/photo.cr2').write_bytes(b'unindexed generated candidate')
        self.run_engine('--exts','.jpg'); conn=self.conn(); report=self.latest(conn)[1]
        self.assertEqual(report['state'],'needs_attention')
        self.assertNotIn('resolution',report)
        self.assertEqual(report['sidecars'][0]['candidates'],['photo.cr2','photo.jpg'])
        self.assertEqual(report['sidecars'][0]['code'],'ambiguous_ownership')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0],1)

    def test_full_name_wins_but_alternate_sidecar_is_retained(self):
        (self.root/'source/photo.xmp').write_bytes(packet('2010'))
        self.run_engine();conn=self.conn(); report=self.latest(conn)[1]
        self.assertEqual(report['resolution']['proposed_effective']['date_taken'],'2005-03-04T05:06:07')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0],2)

    def test_damaged_sidecar_is_preserved_and_no_fallback_is_proposed(self):
        self.sidecar.write_bytes(packet()[:-10])
        original=self.sidecar.read_bytes()
        out=self.run_engine();conn=self.conn(); report=self.latest(conn)[1]
        self.assertEqual(report['state'],'needs_attention')
        self.assertNotIn('resolution',report)
        self.assertIn('Metadata capture needs attention',out)
        self.assertEqual(xmp_store.original_bytes(conn,conn.execute('SELECT version_id FROM xmp_versions').fetchone()[0]),original)

    def test_non_xmp_is_flagged_without_blocking_embedded_proposal(self):
        self.sidecar.write_bytes(b'')
        self.run_engine(); conn=self.conn(); report=self.latest(conn)[1]
        self.assertEqual(report['sidecars'][0]['state'],'ignored')
        self.assertEqual(report['resolution']['field_sources']['date_taken'],'embedded_xmp')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0],0)

    def test_sidecar_symlink_is_reported_and_target_is_never_read(self):
        self.sidecar.unlink()
        outside=self.root/'outside.xmp'; outside.write_bytes(packet('2012'))
        self.sidecar.symlink_to(outside)
        self.run_engine(); conn=self.conn(); report=self.latest(conn)[1]
        self.assertEqual(report['state'],'needs_attention')
        self.assertNotIn('resolution',report)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0],0)
        self.assertIn('detail',report['issues'][0])
        self.assertEqual(outside.read_bytes(),packet('2012'))

    def test_selected_index_still_sees_unselected_sibling_for_ownership(self):
        self.run_engine(); conn=self.conn()
        photo_id=conn.execute('SELECT id FROM photos').fetchone()[0]
        self.sidecar.rename(self.root/'source/photo.xmp')
        (self.root/'source/photo.cr2').write_bytes(b'generated, deliberately unindexed sibling')
        self.run_engine('--file-ids',str(photo_id))
        self.assertEqual(self.latest(conn)[1]['sidecars'][0]['code'],'ambiguous_ownership')

    def test_cancel_keeps_only_complete_observations_and_reindex_finishes_scope(self):
        second=self.root/'source/second.jpg'
        Image.new('RGB',(48,32),(40,50,60)).save(second)
        second_sidecar=self.root/'source/second.jpg.xmp'
        second_sidecar.write_bytes(packet())
        self.run_engine(); conn=self.conn()
        self.sidecar.write_bytes(packet('2011'))
        second_sidecar.write_bytes(packet('2012'))
        before=conn.execute('SELECT COUNT(*) FROM metadata_captures').fetchone()[0]
        run=ns_db.create_run(conn,mode='INDEX',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
        actual=metadata_index.retain
        def cancel_after_commit(*args, **kwargs):
            result=actual(*args, **kwargs)
            runtime.cancel_requested.set()
            return result
        try:
            with mock.patch.object(metadata_index,'retain',side_effect=cancel_after_commit):
                complete=metadata_index.capture_index(next((self.root/'base/db').glob('*.db')),run,
                    self.root/'source',[str(self.photo),str(second)],worker_count=1,log_dir=str(self.root/'base'))
            self.assertFalse(complete)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM metadata_captures').fetchone()[0],before+1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0],2)
            self.assertEqual(self.latest(conn)[1]['resolution']['proposed_effective']['date_taken'],'2011')
            # An already-cancelled phase must not retain the remaining capture.
            self.assertFalse(metadata_index.capture_index(next((self.root/'base/db').glob('*.db')),run,
                self.root/'source',[str(second)],worker_count=1,log_dir=str(self.root/'base')))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM metadata_captures').fetchone()[0],before+1)
        finally:
            runtime.cancel_requested.clear()
        self.run_engine()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM metadata_captures').fetchone()[0],before+2)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0],3)
        self.assertEqual(self.latest(conn)[1]['resolution']['proposed_effective']['date_taken'],'2012')

    def test_metadata_arriving_during_backup_remains_unbacked(self):
        self.run_engine(); conn=self.conn()
        run=ns_db.create_run(conn,mode='INDEX',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
        file_id=conn.execute('SELECT file_id FROM photo_files').fetchone()[0]
        actual=ns_db._compress_and_verify
        def during(raw,packed):
            with ns_db.transaction(conn):
                conn.execute('INSERT INTO metadata_captures(run_id,file_id,source_relative_path,embedded_json,report_json,observed_at) '
                             'VALUES(?,?,?,?,?,?)',(run,file_id,'photo.jpg','{}','{}','2000-01-01T00:00:00+00:00'))
            actual(raw,packed)
        with mock.patch.object(ns_db,'_compress_and_verify',side_effect=during):
            result=ns_db.backup_catalog(next((self.root/'base/db').glob('*.db')),self.root/'backups',self.root/'base',trigger='manual')
        self.assertEqual(result['outcome'],'succeeded')
        self.assertEqual(ns_db.unbacked_changes(conn)[0],1)
        self.assertEqual(ns_db.unbacked_changes(conn,exclude_run_id=run)[0],0)

    def test_copy_uses_captured_xmp_without_rewriting_observation(self):
        self.run_engine(); conn=self.conn(); photo_path=conn.execute('SELECT dest_path FROM photos').fetchone()[0]
        before=conn.execute('SELECT COUNT(*) FROM metadata_captures').fetchone()[0]
        self.run_engine('--copy')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM metadata_captures').fetchone()[0],before)
        self.assertFalse(Path(photo_path).exists())
        self.assertTrue(self.sidecar.is_file())
        self.assertFalse(Path(photo_path+'.xmp').exists())
        actual,status=conn.execute('SELECT dest_path,status FROM photos').fetchone()
        self.assertEqual(status,'Copied')
        self.assertIn('/2005/03/04/',actual)
        self.assertEqual(Path(actual+'.xmp').read_bytes(),self.sidecar.read_bytes())

    def test_backup_restores_observations_blobs_and_snapshot_watermark(self):
        self.run_engine(); conn=self.conn()
        self.assertEqual(ns_db.unbacked_changes(conn)[0],0)
        packed=next((self.root/'backups').glob('*.zst'))
        restored=self.root/'restored.db'
        restored.write_bytes(zstandard.ZstdDecompressor().decompress(packed.read_bytes()))
        other=ns_db.connect(restored);self.addCleanup(other.close)
        self.assertEqual(other.execute('SELECT COUNT(*) FROM metadata_captures').fetchone()[0],1)
        self.assertEqual(xmp_store.original_bytes(other,1),self.sidecar.read_bytes())
        self.assertEqual(ns_db.unbacked_changes(other)[0],0)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute('DELETE FROM metadata_captures')

    def test_captured_observation_failure_rolls_back_sidecar_arrival(self):
        self.run_engine(); conn=self.conn()
        run=ns_db.create_run(conn,mode='INDEX',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
        photo_id,file_id=conn.execute('SELECT photo_id,file_id FROM photo_files').fetchone()
        self.sidecar.write_bytes(packet('2011'))
        inventory,names=metadata_index._folder(self.root/'source','.')
        sidecars=metadata_index._sidecars(self.root/'source','photo.jpg',inventory,names)
        embedded=self.latest(conn)[0]; report=metadata_index.build_report('photo.jpg',embedded,sidecars)
        # A duplicate observation key refuses publication after BLOB retention begins.
        row=(photo_id,str(self.photo),file_id,'x',1,1,None,None)
        with ns_db.transaction(conn):
            conn.execute('INSERT INTO metadata_captures(run_id,file_id,source_relative_path,embedded_json,report_json,observed_at) '
                         'VALUES(?,?,?,?,?,?)',(run,file_id,'photo.jpg','{}','{}',ns_db.utc_now()))
        before=conn.execute('SELECT COUNT(*) FROM xmp_arrivals').fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            metadata_index.retain(conn,run_id=run,row=row,relative_photo='photo.jpg',embedded=embedded,report=report,
                                  sidecars=sidecars,source_ids={'photo.jpg':file_id})
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM xmp_arrivals').fetchone()[0],before)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0],1)
