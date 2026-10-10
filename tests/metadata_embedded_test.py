"""Generated JPEG working-copy qualification; no source edits or UI dependencies."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import sys
import unittest
from unittest import mock

from PIL import Image

from engine import metadata_edits, metadata_embedded


class EmbeddedWriter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.photo = self.root / 'generated ü.jpg'
        # Nonuniform pixels detect accidental re-encoding and orientation changes.
        image = Image.new('RGB', (43,31))
        image.putdata([(i % 251, i*3 % 253, i*7 % 255) for i in range(43*31)])
        image.save(self.photo, quality=91)
        subprocess.run(['exiftool', '-overwrite_original', '-IFD0:Make=Fixture camera',
                        '-ExifIFD:DateTimeOriginal=2001:02:03 04:05:06',
                        '-IFD0:Orientation#=1', '-Comment=Keep this comment', str(self.photo)],
                       check=True, capture_output=True)
        self.original = self.photo.read_bytes()
        self.sha = hashlib.sha1(self.original).hexdigest()

    def stage(self, changes, kind='embedded_exif', **kwargs):
        return metadata_embedded.stage(self.root, self.photo.name, 'staged.jpg',
            expected_sha1=kwargs.pop('expected_sha1',self.sha), kind=kind, changes=changes, **kwargs)

    def read(self):
        return json.loads(subprocess.check_output(['exiftool','-j','-n','-G1',str(self.root/'staged.jpg')]))[0]

    def test_exif_date_and_orientation_change_only_staged_copy(self):
        result = self.stage({'date_taken':'2010-11-12T13:14:15.123+02:00', 'orientation':6})
        self.assertNotEqual(result['before_sha1'],result['after_sha1'])
        self.assertEqual(self.photo.read_bytes(),self.original)
        tags = self.read()
        self.assertEqual(tags['ExifIFD:DateTimeOriginal'],'2010:11:12 13:14:15')
        self.assertEqual(str(tags['ExifIFD:SubSecTimeOriginal']),'123')
        self.assertEqual(tags['ExifIFD:OffsetTimeOriginal'],'+02:00')
        self.assertEqual(tags['IFD0:Orientation'],6)
        self.assertEqual(tags['IFD0:Make'],'Fixture camera')
        self.assertEqual(tags['File:Comment'],'Keep this comment')

    def test_removed_date_companions_are_absent_not_empty(self):
        subprocess.run(['exiftool','-overwrite_original','-ExifIFD:SubSecTimeOriginal=123',
                        '-ExifIFD:OffsetTimeOriginal=+02:00',str(self.photo)],check=True,capture_output=True)
        self.sha=hashlib.sha1(self.photo.read_bytes()).hexdigest()
        self.stage({'date_taken':'2010-11-12T13:14:15'})
        tags=self.read()
        self.assertNotIn('ExifIFD:SubSecTimeOriginal',tags)
        self.assertNotIn('ExifIFD:OffsetTimeOriginal',tags)

    def test_first_exif_date_on_a_metadata_free_jpeg(self):
        Image.new('RGB',(16,8),(20,40,60)).save(self.photo)
        self.sha=hashlib.sha1(self.photo.read_bytes()).hexdigest()
        self.stage({'date_taken':'2010-11-12T13:14:15'})
        self.assertEqual(self.read()['ExifIFD:DateTimeOriginal'],'2010:11:12 13:14:15')

    def test_representable_exif_common_fields(self):
        self.stage({'title':'雪 & sky','caption':'Line 1\nLine 2','rights':'Copyright fixture',
                    'creators':['Fixture author'],'keywords':['two','雪'],'rating':'4'})
        tags = self.read()
        self.assertEqual(tags['IFD0:XPTitle'],'雪 & sky')
        self.assertEqual(tags['IFD0:XPKeywords'],'two;雪')
        self.assertEqual(tags['IFD0:Artist'],'Fixture author')
        self.assertEqual(tags['IFD0:Rating'],4)

    def test_all_common_xmp_fields_with_empty_date(self):
        changes={'date_taken':'','orientation':8,'title':{'x-default':'Title','fr':'Été'},
                 'caption':'Caption','keywords':['two','one','semi;colon'], 'creators':['One','Two'],
                 'rights':'© Fixture','rating':'4.5',
                 'gps':{'latitude':'12,30N','longitude':'45,15W','altitude':'125/2','altitude_ref':'1'}}
        self.stage(changes,kind='embedded_xmp')
        tags = self.read()
        self.assertEqual(tags['XMP-dc:Title-fr'],'Été')
        self.assertEqual(tags['XMP-exif:GPSLatitude'],12.5)
        self.assertEqual(tags['ExifIFD:DateTimeOriginal'],'2001:02:03 04:05:06')
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_xmp_preserves_unknown_packet_fields(self):
        packet=metadata_edits.first_sidecar({'title':'Previous','keywords':['keep']})
        packet=packet.replace(b'</rdf:Description>',b'<custom:note xmlns:custom="urn:fixture">Keep</custom:note></rdf:Description>')
        path=self.root/'original.xmp';path.write_bytes(packet)
        subprocess.run(['exiftool','-overwrite_original','-XMP<='+str(path),str(self.photo)],check=True,capture_output=True)
        self.sha=hashlib.sha1(self.photo.read_bytes()).hexdigest()
        self.stage({'title':'Next'},kind='embedded_xmp')
        actual=subprocess.check_output(['exiftool','-b','-XMP',str(self.root/'staged.jpg')])
        self.assertIn(b'<custom:note',actual)
        self.assertEqual(self.read()['XMP-dc:Subject'],'keep')

    def test_noop_keeps_exact_original_bytes(self):
        result=self.stage({'orientation':1})
        self.assertTrue(result['no_change'])
        self.assertEqual((self.root/'staged.jpg').read_bytes(),self.original)

    def test_progressive_jpeg_and_color_profile_are_preserved(self):
        from PIL import ImageCms
        profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        with Image.open(self.photo) as image:
            image.save(self.root/'progressive.jpg',quality=89,progressive=True,icc_profile=profile)
        self.photo=self.root/'progressive.jpg'
        self.sha=hashlib.sha1(self.photo.read_bytes()).hexdigest()
        self.stage({'title':'Changed'},kind='embedded_xmp')
        with Image.open(self.root/'staged.jpg') as staged:
            self.assertEqual(staged.info['icc_profile'],profile)
            self.assertTrue(staged.info['progressive'])

    def test_non_jpeg_bytes_and_extra_trailers_are_refused(self):
        for data in (b'not a jpeg', self.original+b'extra trailer',
                     self.original+self.original, self.original+b'extra\xff\xd9'):
            self.photo.write_bytes(data)
            self.sha=hashlib.sha1(data).hexdigest()
            with self.assertRaises(ValueError):self.stage({'orientation':6})
            self.assertFalse((self.root/'staged.jpg').exists())
            self.assertEqual(self.photo.read_bytes(),data)

    def test_option_like_values_stay_literal_and_do_not_inject_commands(self):
        self.stage({'title':'-all=','caption':'$(touch sentinel)\n-overwrite_original'})
        self.assertEqual(self.read()['IFD0:XPTitle'],'-all=')
        self.assertEqual(self.read()['IFD0:ImageDescription'],'$(touch sentinel)\n-overwrite_original')
        self.assertFalse((self.root/'sentinel').exists())

    def test_wrong_hash_or_existing_staging_name_refuses(self):
        with self.assertRaisesRegex(ValueError,'catalog hash'):
            self.stage({'orientation':6},expected_sha1='0'*40)
        self.assertFalse((self.root/'staged.jpg').exists())
        (self.root/'staged.jpg').write_bytes(b'occupied')
        with self.assertRaises(FileExistsError):self.stage({'orientation':6})
        self.assertEqual((self.root/'staged.jpg').read_bytes(),b'occupied')
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_parent_symlink_and_path_traversal_refuse(self):
        (self.root/'linked').symlink_to(self.root,target_is_directory=True)
        for staged in ('../outside.jpg','linked/staged.jpg', self.photo.name):
            with self.subTest(staged=staged),self.assertRaises((ValueError,OSError)):
                metadata_embedded.stage(self.root,self.photo.name,staged,expected_sha1=self.sha,
                                        kind='embedded_exif',changes={'orientation':6})
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_unrepresentable_exif_never_switches_to_xmp(self):
        for changes in ({'title':{'fr':'Été'}},{'caption':'雪'},{'creators':['one','two']},
                        {'rating':'4.5'},{'keywords':['semi;colon']},{'date_taken':'2001'},
                        {'gps':{'latitude':'12,30N','longitude':'45,15W'}}):
            with self.subTest(changes=changes),self.assertRaises(ValueError): self.stage(changes)
        self.assertEqual(self.photo.read_bytes(),self.original)
        self.assertFalse((self.root/'staged.jpg').exists())

    def test_tool_output_is_bounded_while_running(self):
        popen=subprocess.Popen
        def noisy(_args, **kwargs):
            return popen([sys.executable,'-c','import sys; sys.stdout.write("x"*1000000)'], **kwargs)
        with mock.patch.object(metadata_embedded.subprocess,'Popen',side_effect=noisy):
            with self.assertRaisesRegex(ValueError,'bounded size'):
                metadata_embedded._command([],self.root,limit=100)

    def test_stalled_tool_is_killed_at_deadline(self):
        popen=subprocess.Popen
        children=[]
        def stalled(_args, **kwargs):
            process=popen([sys.executable,'-c','import time; time.sleep(60)'], **kwargs)
            children.append(process)
            return process
        with mock.patch.object(metadata_embedded.subprocess,'Popen',side_effect=stalled), \
                mock.patch.object(metadata_embedded,'TOOL_TIMEOUT',0.05):
            with self.assertRaises(subprocess.TimeoutExpired):metadata_embedded._command([],self.root)
        self.assertIsNotNone(children[0].poll())

    def test_low_disk_space_leaves_original_and_no_stage(self):
        usage=metadata_embedded.shutil.disk_usage(self.root)
        with mock.patch.object(metadata_embedded.shutil,'disk_usage',return_value=usage._replace(free=1)):
            with self.assertRaises(OSError):self.stage({'orientation':6})
        self.assertEqual(self.photo.read_bytes(),self.original)
        self.assertFalse((self.root/'staged.jpg').exists())

    def test_failed_directory_sync_drops_only_our_stage(self):
        fsync=os.fsync
        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError(5,'fixture sync failure')
            return fsync(fd)
        with mock.patch.object(metadata_embedded.os,'fsync',side_effect=fail_directory):
            with self.assertRaises(OSError):self.stage({'orientation':6})
        self.assertFalse((self.root/'staged.jpg').exists())
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_source_changed_during_edit_refuses_and_drops_stage(self):
        command=metadata_embedded._command
        def changed(args, folder, **kwargs):
            result=command(args,folder,**kwargs)
            if '-overwrite_original' in args:self.photo.write_bytes(b'external change')
            return result
        with mock.patch.object(metadata_embedded,'_command',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'changed_during_read'):self.stage({'orientation':6})
        self.assertFalse((self.root/'staged.jpg').exists())
        self.assertEqual(self.photo.read_bytes(),b'external change')

    def test_file_permissions_are_preserved(self):
        self.photo.chmod(0o640)
        self.stage({'orientation':6})
        self.assertEqual(stat.S_IMODE((self.root/'staged.jpg').stat().st_mode),0o640)
        self.assertEqual(list(self.root.glob('.ns-embedded-*')),[])

    def test_tool_success_without_applying_change_is_refused(self):
        original=metadata_embedded._command
        def dropped(args, folder, **kwargs):
            if '-overwrite_original' in args:return b'1 image files updated'
            return original(args, folder, **kwargs)
        with mock.patch.object(metadata_embedded,'_command',side_effect=dropped):
            with self.assertRaisesRegex(ValueError,'read-back'):self.stage({'orientation':6})
        self.assertFalse((self.root/'staged.jpg').exists())
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_unrelated_tag_change_is_refused(self):
        original=metadata_embedded._command
        def extra(args, folder, **kwargs):
            if '-overwrite_original' in args:args=[*args[:-1],'-IFD0:Make=Unwanted',args[-1]]
            return original(args,folder,**kwargs)
        with mock.patch.object(metadata_embedded,'_command',side_effect=extra):
            with self.assertRaisesRegex(ValueError,'Unrelated metadata'):self.stage({'orientation':6})
        self.assertFalse((self.root/'staged.jpg').exists())
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_unrelated_jpeg_comment_change_is_refused(self):
        command=metadata_embedded._command
        def changed(args, folder, **kwargs):
            result=command(args,folder,**kwargs)
            if '-overwrite_original' in args:
                working=Path(args[-1])
                working.write_bytes(working.read_bytes().replace(b'Keep this comment',b'Edit this comment'))
            return result
        with mock.patch.object(metadata_embedded,'_command',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'protected image data'):self.stage({'orientation':6})
        self.assertFalse((self.root/'staged.jpg').exists())
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_image_reencoding_is_refused(self):
        original=metadata_embedded._command
        def damaged(args, folder, **kwargs):
            result=original(args,folder,**kwargs)
            if '-overwrite_original' in args:
                working=Path(args[-1]);data=bytearray(working.read_bytes())
                start=data.index(b'\xff\xdb')+5
                data[start] = 1 if data[start]!=1 else 2
                working.write_bytes(data)
            return result
        with mock.patch.object(metadata_embedded,'_command',side_effect=damaged):
            with self.assertRaises(ValueError):self.stage({'orientation':6})
        self.assertFalse((self.root/'staged.jpg').exists())
        self.assertEqual(self.photo.read_bytes(),self.original)


if __name__ == '__main__':unittest.main()
