"""Field-scoped plans and independently read first-sidecar output; generated data only."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from PIL import Image
import metadata_index_test
from engine import metadata_edits, metadata_decisions, ns_db, xmp


class EditPlans(unittest.TestCase):
    def sources(self):
        return {'exif':{'kind':'embedded_exif','fields':{'date_taken':'1999-01-02T03:04:05.123+02:00',
                    'camera_make':'Fixture camera','orientation':1,'location':{'latitude':12.5,'longitude':45.0}}},
                'embedded_xmp':{'kind':'embedded_xmp','fields':{'title':'Original title','keywords':['one','two']}}}

    def plan(self, changes, **kwargs):
        args={'primary_id':None,'settings':{},'photo_name':'photo.cr2','original_year':2001,
              'current_relative_path':'library/1999/01/02/photo.cr2'}
        args.update(kwargs)
        return metadata_edits.plan(self.sources(),changes=changes,**args)

    def test_first_raw_date_edit_contains_only_requested_date(self):
        before=self.sources(); untouched=copy.deepcopy(before)
        result=metadata_edits.plan(before,primary_id=None,changes={'date_taken':'2005-03-04T05:06:07'},settings={},
                                  photo_name='photo.cr2',original_year=2001,current_relative_path='library/1999/01/02/photo.cr2')
        packet=base64.b64decode(result['new_sidecar_base64'])
        self.assertEqual(xmp.parse_bytes(packet,source_id='test').source.fields,{'date_taken':'2005-03-04T05:06:07'})
        self.assertEqual(result['after']['proposed_effective']['camera_make'],'Fixture camera')
        self.assertEqual(result['after']['proposed_effective']['location'],{'latitude':12.5,'longitude':45.0})
        self.assertEqual(result['after']['field_sources']['keywords'],'embedded_xmp')
        self.assertEqual(result['filing']['proposed'],'library/2005/03/04/photo.cr2')
        self.assertEqual(before,untouched)
        self.assertFalse(result['applied'])

    def test_existing_primary_wins_over_changed_format_default(self):
        sources=self.sources(); sources['sidecar:photo.jpg.xmp']={'kind':'sidecar_xmp','fields':{'title':'Keep me','rating':'4'}}
        before=copy.deepcopy(sources)
        result=metadata_edits.plan(sources,primary_id='sidecar:photo.jpg.xmp',changes={'date_taken':'2005'},
            settings={'metadata_write_non_raw':'embedded'},photo_name='photo.jpg',original_year=2001,
            current_relative_path='library/1999/01/02/photo.jpg')
        self.assertFalse(result['target']['create'])
        self.assertNotIn('new_sidecar_base64',result)
        self.assertEqual(result['target_fields_after'],{'title':'Keep me','rating':'4','date_taken':'2005'})
        self.assertEqual(sources,before)
        self.assertEqual(result['filing']['proposed'],'library/Undated/2001/photo.jpg')

    def test_blank_and_partial_xmp_dates_do_not_fall_back(self):
        for date in ('','2005','2005-03'):
            with self.subTest(date=date):
                result=self.plan({'date_taken':date})
                self.assertEqual(result['after']['proposed_effective']['date_taken'],date)
                self.assertEqual(result['filing']['proposed'],'library/Undated/2001/photo.cr2')
                self.assertEqual(xmp.parse_bytes(base64.b64decode(result['new_sidecar_base64']),source_id='test').source.fields['date_taken'],date)

    def test_full_calendar_date_has_a_folder_without_invented_time(self):
        result=self.plan({'date_taken':'2005-03-04'})
        self.assertEqual(result['after']['proposed_effective']['date_taken'],'2005-03-04')
        self.assertEqual(result['filing']['proposed'],'library/2005/03/04/photo.cr2')

    def test_offset_does_not_shift_filing_day(self):
        result=self.plan({'date_taken':'2005-03-04T00:01:00+14:00'})
        self.assertEqual(result['filing']['proposed'],'library/2005/03/04/photo.cr2')

    def test_orientation_edit_does_not_repair_or_move_an_unrelated_date(self):
        result=self.plan({'orientation':6},current_relative_path='library/1980/02/03/photo.cr2')
        self.assertFalse(result['filing']['change'])
        self.assertEqual(result['after']['proposed_effective']['date_taken'],'1999-01-02T03:04:05.123+02:00')
        self.assertEqual(xmp.parse_bytes(base64.b64decode(result['new_sidecar_base64']),source_id='test').source.fields,{'orientation':'6'})

    def test_exif_date_updates_or_removes_its_own_companions(self):
        result=self.plan({'date_taken':'2005-03-04T05:06:07'},primary_id='exif',photo_name='photo.jpg',
                         current_relative_path='library/1999/01/02/photo.jpg')
        operations={item['tag']:item for item in result['tag_edits']}
        self.assertEqual(operations['ExifIFD:DateTimeOriginal']['value'],'2005:03:04 05:06:07')
        self.assertEqual(operations['ExifIFD:SubSecTimeOriginal']['operation'],'remove')
        self.assertEqual(operations['ExifIFD:OffsetTimeOriginal']['operation'],'remove')
        self.assertEqual(len(operations),3)
        result=self.plan({'date_taken':'2005-03-04T05:06:07.456Z'},primary_id='exif',photo_name='photo.jpg',
                         current_relative_path='library/1999/01/02/photo.jpg')
        values={item['tag']:item['value'] for item in result['tag_edits']}
        self.assertEqual(values['ExifIFD:SubSecTimeOriginal'],'456')
        self.assertEqual(values['ExifIFD:OffsetTimeOriginal'],'+00:00')

    def test_embedded_xmp_primary_changes_no_exif_tags(self):
        result=self.plan({'date_taken':'2005-03'},primary_id='embedded_xmp',photo_name='photo.jpg',
                         current_relative_path='library/1999/01/02/photo.jpg')
        self.assertEqual(result['tag_edits'],[{'tag':'XMP-exif:DateTimeOriginal','operation':'set','value':'2005-03'}])
        self.assertEqual(result['target_fields_after']['title'],'Original title')

    def test_raw_embedded_and_unmapped_formats_are_refused(self):
        with self.assertRaises(ValueError): self.plan({'orientation':6},primary_id='exif')
        with self.assertRaises(ValueError): self.plan({'orientation':6},settings={'metadata_write_raw':'embedded'})
        with self.assertRaises(ValueError): self.plan({'orientation':6},photo_name='photo.custom',current_relative_path='library/photo.custom')
        with self.assertRaises(ValueError): self.plan({'orientation':6},photo_name='photo.heic',current_relative_path='library/photo.heic')

    def test_no_silent_field_drop_invalid_values_or_path_traversal(self):
        for changes in ({},{'unsupported':['new']},{'date_taken':'2005-02-31'},{'orientation':9},
                        {'date_taken':None},{'date_taken':'2005','camera_make':'wrong'}, {'orientation':True}):
            with self.subTest(changes=changes),self.assertRaises(ValueError): self.plan(changes)
        with self.assertRaises(ValueError): self.plan({'orientation':6},photo_name='../photo.cr2')
        with self.assertRaises(ValueError): self.plan({'date_taken':'2005'},original_year=None)
        with self.assertRaises(ValueError): self.plan({'date_taken':''},primary_id='exif',photo_name='photo.jpg',current_relative_path='library/photo.jpg')

    def test_existing_sidecar_requires_an_explicit_primary(self):
        sources=self.sources(); sources['sidecar:photo.cr2.xmp']={'kind':'sidecar_xmp','fields':{}}
        with self.assertRaises(ValueError):
            metadata_edits.plan(sources,primary_id=None,changes={'orientation':6},settings={},photo_name='photo.cr2',
                                original_year=2001,current_relative_path='library/photo.cr2')

    def test_output_is_detached_from_request_and_source_values(self):
        sources=self.sources(); changes={'date_taken':'2005'}
        result=metadata_edits.plan(sources,primary_id=None,changes=changes,settings={},photo_name='photo.cr2',
                                  original_year=2001,current_relative_path='library/photo.cr2')
        result['after']['proposed_effective']['keywords'].append('changed')
        result['changes']['date_taken']='2007'
        self.assertEqual(changes,{'date_taken':'2005'})
        self.assertEqual(sources['embedded_xmp']['fields']['keywords'],['one','two'])

    def test_generated_first_packet_is_read_independently_by_exiftool(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'photo.cr2.xmp'
            path.write_bytes(metadata_edits.first_sidecar({'date_taken':'2005-03-04T05:06:07.123+02:00','orientation':6}))
            output=json.loads(subprocess.run(['exiftool','-j','-G1','-n',str(path)],check=True,capture_output=True,text=True).stdout)[0]
            self.assertEqual(output['XMP-exif:DateTimeOriginal'],'2005:03:04 05:06:07.123+02:00')
            self.assertEqual(output['XMP-tiff:Orientation'],6)
            self.assertNotIn('XMP-tiff:Make',output)
            self.assertNotIn('XMP-dc:Subject',output)

    def test_exif_plan_round_trip_changes_only_requested_logical_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            original=Path(tmp)/'original.jpg'; staged=Path(tmp)/'staged.jpg'
            Image.new('RGB',(40,30),(20,40,60)).save(original)
            subprocess.run(['exiftool','-overwrite_original','-EXIF:DateTimeOriginal=1999:01:02 03:04:05',
                '-EXIF:SubSecTimeOriginal=123','-EXIF:OffsetTimeOriginal=+02:00','-IFD0:Make=Fixture camera',
                '-XMP-dc:Description=Unchanged caption','-GPSLatitude=12.5','-GPSLatitudeRef=N',
                '-GPSLongitude=45','-GPSLongitudeRef=E',str(original)],check=True,capture_output=True)
            original_hash=hashlib.sha256(original.read_bytes()).hexdigest(); staged.write_bytes(original.read_bytes())
            result=self.plan({'date_taken':'2005-03-04T05:06:07'},primary_id='exif',photo_name='staged.jpg',current_relative_path='library/staged.jpg')
            args=['-' + edit['tag'] + '=' + (str(edit['value']) if edit['operation']=='set' else '') for edit in result['tag_edits']]
            subprocess.run(['exiftool','-overwrite_original',*args,str(staged)],check=True,capture_output=True)
            output=json.loads(subprocess.run(['exiftool','-j','-G1','-n',str(staged)],check=True,capture_output=True,text=True).stdout)[0]
            self.assertEqual(output['ExifIFD:DateTimeOriginal'],'2005:03:04 05:06:07')
            self.assertNotIn('ExifIFD:SubSecTimeOriginal',output)
            self.assertNotIn('ExifIFD:OffsetTimeOriginal',output)
            self.assertEqual(output['IFD0:Make'],'Fixture camera')
            self.assertEqual(output['XMP-dc:Description'],'Unchanged caption')
            self.assertEqual(output['GPS:GPSLatitude'],12.5)
            self.assertEqual(output['GPS:GPSLongitude'],45)
            self.assertEqual(Image.open(original).tobytes(),Image.open(staged).tobytes())
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),original_hash)


class CatalogPreviews(unittest.TestCase):
    setUp = metadata_index_test.IndexTests.setUp
    run_engine = metadata_index_test.IndexTests.run_engine
    conn = metadata_index_test.IndexTests.conn

    def test_library_preview_is_read_only_bound_and_changes_with_preferences(self):
        self.sidecar.unlink()  # Generated fixture; no imported sidecar to block Copy.
        self.run_engine('--copy'); conn=self.conn(); db=next((self.root/'base/db').glob('*.db'))
        photo=conn.execute('SELECT id FROM photos').fetchone()[0]
        capture=conn.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        before=conn.execute('SELECT metadata_json,dest_path,status FROM photos').fetchone()
        digest=hashlib.sha256(Path(before[1]).read_bytes()).hexdigest()
        a=metadata_edits.preview_catalog(db,photo_id=photo,capture_id=capture,changes={'date_taken':'2005-03-04T05:06:07'},destination_root=self.root/'dest')
        ns_db.save_settings(conn,{'metadata_write_non_raw':'xmp'},expected_revisions={'metadata_write_non_raw':0})
        b=metadata_edits.preview_catalog(db,photo_id=photo,capture_id=capture,changes={'date_taken':'2005-03-04T05:06:07'},destination_root=self.root/'dest')
        self.assertNotEqual(a['token'],b['token'])
        self.assertEqual(b['target']['source_id'],'new_sidecar')
        self.assertEqual(b['filing']['proposed'],'library/2005/03/04/photo.jpg')
        self.assertEqual(conn.execute('SELECT metadata_json,dest_path,status FROM photos').fetchone(),before)
        self.assertEqual(hashlib.sha256(Path(before[1]).read_bytes()).hexdigest(),digest)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM metadata_decisions').fetchone()[0],0)
        self.assertTrue(b['filesystem_verification_pending'])

    def test_not_organized_and_wrong_destination_are_refused(self):
        self.sidecar.unlink(); self.run_engine(); conn=self.conn(); db=next((self.root/'base/db').glob('*.db'))
        photo=conn.execute('SELECT id FROM photos').fetchone()[0]
        capture=conn.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        with self.assertRaises(ValueError):
            metadata_edits.preview_catalog(db,photo_id=photo,capture_id=capture,changes={'orientation':6},destination_root=self.root/'dest')
        self.run_engine('--copy')
        with self.assertRaises(ValueError):
            metadata_edits.preview_catalog(db,photo_id=photo,capture_id=capture,changes={'orientation':6},destination_root=self.root/'source')

    def test_catalog_primary_overrides_settings_and_preserves_saved_version(self):
        self.sidecar.unlink(); self.run_engine('--copy'); conn=self.conn(); db=next((self.root/'base/db').glob('*.db'))
        photo=conn.execute('SELECT id FROM photos').fetchone()[0]
        capture=conn.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        selection={'capture_id':capture,'primary_id':'exif'}
        before=metadata_decisions.preview(db,'primary',selection)
        chosen=metadata_decisions.confirm(db,kind='primary',selection=selection,token=before['token'],request_id='embedded')
        ns_db.save_settings(conn,{'metadata_write_non_raw':'xmp'},expected_revisions={'metadata_write_non_raw':0})
        result=metadata_edits.preview_catalog(db,photo_id=photo,capture_id=capture,changes={'date_taken':'2005-03-04T05:06:07'},destination_root=self.root/'dest')
        self.assertEqual(result['primary_before'],'exif')
        self.assertEqual(result['target']['kind'],'embedded_exif')
        self.assertFalse(result['target']['create'])
        self.assertEqual(result['binding']['primary_revision'],chosen['revision'])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM metadata_decisions WHERE kind='primary'").fetchone()[0],1)
