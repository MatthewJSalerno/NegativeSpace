"""Generated EXIF removal qualification and executable format/representation limits."""
import hashlib
import json
import subprocess
import unittest
from unittest import mock

import metadata_embedded_test
import metadata_save_test
import metadata_photo_save_test
from engine import metadata_adapter, metadata_edits, metadata_embedded, metadata_save


class WriterLimits(unittest.TestCase):
    setUp = metadata_embedded_test.EmbeddedWriter.setUp
    stage = metadata_embedded_test.EmbeddedWriter.stage
    read = metadata_embedded_test.EmbeddedWriter.read

    def add(self, *tags):
        subprocess.run(['exiftool','-overwrite_original',*tags,str(self.photo)],check=True,capture_output=True)
        self.original = self.photo.read_bytes()
        self.sha = hashlib.sha1(self.original).hexdigest()

    def test_remove_date_removes_fraction_and_offset_together(self):
        self.add('-ExifIFD:SubSecTimeOriginal=123','-ExifIFD:OffsetTimeOriginal=+02:00')
        self.stage({},remove_fields=['date_taken'])
        tags = self.read()
        for key in ('DateTimeOriginal','SubSecTimeOriginal','OffsetTimeOriginal'):
            self.assertNotIn('ExifIFD:'+key,tags)
        self.assertEqual(tags['IFD0:Make'],'Fixture camera')
        self.assertEqual(tags['IFD0:Orientation'],1)
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_removing_last_date_preserves_nondefault_exif_header_values(self):
        self.add('-ExifIFD:ColorSpace#=1','-ExifIFD:ExifVersion=0230')
        self.stage({},remove_fields=['date_taken'])
        tags = self.read()
        self.assertEqual(tags['ExifIFD:ColorSpace'],1)
        self.assertEqual(str(tags['ExifIFD:ExifVersion']),'0230')
        self.assertNotIn('ExifIFD:DateTimeOriginal',tags)
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_remove_text_lists_rating_and_orientation_preserves_unrequested_data(self):
        self.add('-IFD0:XPTitle=雪','-IFD0:ImageDescription=Caption','-IFD0:Copyright=Rights',
                 '-IFD0:Artist=Creator','-IFD0:XPKeywords=one;two','-IFD0:Rating=4')
        self.stage({},remove_fields=['title','caption','rights','creators','keywords','rating','orientation'])
        tags = self.read()
        for key in ('XPTitle','ImageDescription','Copyright','Artist','XPKeywords','Rating','Orientation'):
            self.assertNotIn('IFD0:'+key,tags)
        self.assertEqual(tags['IFD0:Make'],'Fixture camera')
        self.assertEqual(tags['ExifIFD:DateTimeOriginal'],'2001:02:03 04:05:06')
        self.assertEqual(tags['File:Comment'],'Keep this comment')
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_remove_location_removes_coordinate_references_and_altitude_together(self):
        self.add('-GPS:GPSLatitude#=12.5','-GPS:GPSLatitudeRef=N',
                 '-GPS:GPSLongitude#=45.25','-GPS:GPSLongitudeRef=W',
                 '-GPS:GPSAltitude#=62.5','-GPS:GPSAltitudeRef#=1', '-GPS:GPSMapDatum=WGS-84')
        self.stage({},remove_fields=['gps'])
        tags = self.read()
        for key in metadata_adapter.GPS_KEYS:
            self.assertNotIn(key,tags)
        self.assertEqual(tags['GPS:GPSMapDatum'],'WGS-84')
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_removal_and_value_change_share_one_verified_working_copy(self):
        self.stage({'title':'New title'},remove_fields=['date_taken','orientation'])
        self.assertEqual(self.read()['IFD0:XPTitle'],'New title')
        self.assertNotIn('ExifIFD:DateTimeOriginal',self.read())
        self.assertNotIn('IFD0:Orientation',self.read())

    def test_removing_missing_fields_is_byte_exact_noop(self):
        result = self.stage({},remove_fields=['title','gps'])
        self.assertTrue(result['no_change'])
        self.assertEqual((self.root/'staged.jpg').read_bytes(),self.original)

    def test_removed_values_must_actually_disappear_at_readback(self):
        original = metadata_embedded._command
        def drop_removals(args, *rest, **kwargs):
            if any(arg.startswith('-json=') for arg in args):
                args = [arg for arg in args if arg != '-IFD0:Orientation=']
            return original(args,*rest,**kwargs)
        with mock.patch.object(metadata_embedded,'_command',side_effect=drop_removals):
            with self.assertRaisesRegex(ValueError,'removals failed'):
                self.stage({},remove_fields=['orientation'])
        self.assertFalse((self.root/'staged.jpg').exists())
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_remove_only_current_source_leaves_embedded_xmp_untouched(self):
        self.add('-XMP-tiff:Orientation#=8','-XMP-exif:DateTimeOriginal=2020:01:02 03:04:05')
        self.stage({},remove_fields=['date_taken','orientation'])
        self.assertEqual(self.read()['XMP-tiff:Orientation'],8)
        self.assertEqual(self.read()['XMP-exif:DateTimeOriginal'],'2020:01:02 03:04:05')
        self.assertNotIn('IFD0:Orientation',self.read())

    def test_empty_exif_values_are_not_silently_converted_to_absence(self):
        for changes in ({'date_taken':''},{'title':''},{'keywords':[]},{'creators':[]},{'gps':{}},{'rating':''}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.stage(changes)
        self.assertEqual(self.photo.read_bytes(),self.original)
        self.assertFalse((self.root/'staged.jpg').exists())

    def test_non_jpeg_embedded_plans_refuse_but_sidecar_plans_work(self):
        source = {'exif':{'kind':'embedded_exif','fields':{'date_taken':'2000-01-02T03:04:05'}}}
        for extension in ('tif','tiff','heic','png','cr2','dng'):
            name = 'photo.'+extension
            args = dict(settings={},photo_name=name,original_year=2000,
                        current_relative_path='library/2000/01/02/'+name)
            with self.subTest(extension=extension),self.assertRaises(ValueError):
                metadata_edits.plan(source,primary_id='exif',changes={'title':'Edit'},**args)
            result = metadata_edits.plan(source,primary_id=None,changes={'title':'Sidecar'},
                **{**args,'settings':{'metadata_write_raw':'xmp','metadata_write_non_raw':'xmp'}})
            self.assertEqual(result['target']['kind'],'sidecar_xmp')


class RemovalJobs(unittest.TestCase):
    setUp = metadata_photo_save_test.PhotoSaves.setUp
    run_engine = metadata_photo_save_test.PhotoSaves.run_engine
    conn = metadata_photo_save_test.PhotoSaves.conn
    setup_catalog = metadata_photo_save_test.PhotoSaves.setup_catalog
    command = metadata_save_test.SavedEdits.command

    def test_cli_date_removal_refiles_updates_history_and_keeps_source(self):
        self.setup_catalog()
        request = {'edits':[{'photo_id':self.pid,'capture_id':self.capture,
                            'changes':{},'remove_fields':['date_taken']}]}
        result = self.command('preview',request)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        preview = json.loads(result.stdout)['previews'][0]
        self.assertNotIn('date_taken',preview['after']['proposed_effective'])
        self.assertTrue(preview['filing']['proposed'].startswith('library/Undated/'))
        request['edits'][0]['token'] = preview['token']
        result = self.command('apply',request,'remove-exif-date')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        saved = metadata_save.active(self.c,self.pid)
        self.assertNotIn('date_taken',saved['resolution']['proposed_effective'])
        self.assertEqual(saved['differences'][0]['operation'],'remove')
        self.assertFalse(saved['differences'][0]['after_present'])
        self.assertEqual(self.photo.read_bytes(),self.original)
        from engine import constants
        self.assertEqual(saved['metadata']['date_source'],constants.DATE_SOURCE_MTIME)

    def test_same_field_cannot_be_both_written_and_removed(self):
        self.setup_catalog()
        result = self.command('preview', {'edits':[{'photo_id':self.pid,'capture_id':self.capture,
            'changes':{'date_taken':'2010-01-02T03:04:05'},'remove_fields':['date_taken']}]})
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.dest.read_bytes(),self.original)

    def test_removal_request_with_invalid_changes_fails_validation(self):
        from engine import metadata_command
        for value in (None, [], 'date_taken'):
            request = {'edits':[{'photo_id':1,'capture_id':1,'changes':value,'remove_fields':['date_taken']}]}
            with self.subTest(value=value),self.assertRaises(ValueError):
                metadata_command.validate(request,'preview')
