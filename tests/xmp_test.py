"""Generated XML and isolated files only; no catalog, sample or library access."""
import errno
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from engine import metadata_capture, xmp, xmp_association


def packet(properties='', attributes='', *, prefix='exif'):
    return (f'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            f'<rdf:RDF xmlns:rdf="{xmp.RDF}"><rdf:Description rdf:about="" '
            f'xmlns:{prefix}="{xmp.EXIF}" xmlns:dc="{xmp.DC}" xmlns:tiff="{xmp.TIFF}" '
            f'xmlns:xmp="{xmp.XAP}" xmlns:crs="{xmp.CRS}" xmlns:custom="urn:generated" '
            f'{attributes}>{properties}</rdf:Description></rdf:RDF></x:xmpmeta>').encode()


def parsed(properties='', attributes=''):
    return xmp.parse_bytes(packet(properties, attributes), source_id='generated')


class ReaderTests(unittest.TestCase):
    def test_scalar_attributes_elements_and_changed_namespace_prefix(self):
        raw = packet('<changed:DateTimeOriginal>2004-01-02T03:04:05+02:00</changed:DateTimeOriginal>',
                     'tiff:Make="Generated" xmp:Rating="0"', prefix='changed')
        result = xmp.parse_bytes(raw, source_id='s')
        self.assertEqual(result.state, 'valid')
        self.assertEqual(result.source.fields, {'date_taken': '2004-01-02T03:04:05+02:00',
                                               'camera_make': 'Generated', 'rating': '0'})
        self.assertEqual(result.original_bytes, raw)

    def test_empty_is_not_absent_through_resolver(self):
        result = parsed('<exif:DateTimeOriginal/>', 'tiff:Model=""')
        resolved = metadata_capture.resolve({
            'exif': {'fields': {'date_taken': '1999', 'camera_make': 'Camera', 'camera_model': 'Model'}},
            'generated': {'fields': result.source.fields}}, ['generated', 'exif'])
        self.assertEqual(resolved['proposed_effective'], {'date_taken': '', 'camera_model': '', 'camera_make': 'Camera'})
        self.assertEqual(resolved['field_sources']['date_taken'], 'generated')
        self.assertNotIn('camera_make', result.source.fields)
        self.assertEqual(result.source.original_bytes, result.original_bytes)

    def test_arrays_localized_and_empty_containers(self):
        result = parsed('''<dc:subject><rdf:Bag><rdf:li>one</rdf:li><rdf:li>two</rdf:li></rdf:Bag></dc:subject>
          <dc:creator><rdf:Seq><rdf:li>First</rdf:li><rdf:li>Second</rdf:li></rdf:Seq></dc:creator>
          <dc:description><rdf:Alt><rdf:li xml:lang="x-default"></rdf:li>
          <rdf:li xml:lang="fr">Légende</rdf:li></rdf:Alt></dc:description>
          <dc:rights><rdf:Alt/></dc:rights>''')
        self.assertEqual(result.state, 'valid')
        self.assertEqual(result.source.fields, {'keywords': ['one', 'two'], 'creators': ['First', 'Second'],
                                               'caption': {'x-default': '', 'fr': 'Légende'}, 'rights': {}})
        self.assertEqual(parsed('<dc:subject><rdf:Bag/></dc:subject>').source.fields['keywords'], [])

    def test_unknown_namespaces_structures_and_repeated_tags_are_preserved(self):
        result = parsed('''<custom:DateTimeOriginal>do not use</custom:DateTimeOriginal>
          <custom:data rdf:parseType="Resource"><custom:value>α &amp; β</custom:value></custom:data>
          <custom:data custom:flag="yes"/>''')
        self.assertEqual(result.state, 'valid')
        self.assertEqual(result.source.fields, {})
        values = result.tags['properties']['{urn:generated}data']
        self.assertEqual(len(values), 2)
        self.assertEqual(values[0]['children'][0]['text'], 'α & β')
        self.assertEqual(values[1]['attributes']['{urn:generated}flag'], 'yes')

    def test_original_encodings_comments_padding_and_processing_instructions(self):
        text = packet('<dc:title>雪</dc:title>').decode()
        for encoding in ('utf-8', 'utf-16'):
            raw = (f'<?xml version="1.0" encoding="{encoding}"?>\n'
                   '<?xpacket begin=""?>\n<!-- retained -->\n' + text + '\n<?xpacket end="w"?>   ').encode(encoding)
            result = xmp.parse_bytes(raw, source_id='s')
            self.assertEqual(result.state, 'valid')
            self.assertEqual(result.original_bytes, raw)
            self.assertEqual(result.source.fields['title'], '雪')

    def test_dtd_and_external_entities_refused_without_io(self):
        attacks = [b'<!DOCTYPE a [<!ENTITY e "expanded">]><a>&e;</a>',
                   b'<!DOCTYPE a SYSTEM "file:///not-readable"><a/>',
                   b'<!DOCTYPE a [<!ENTITY e SYSTEM "http://invalid.example/entity">]><a>&e;</a>']
        with mock.patch.object(xmp.os, 'open', side_effect=AssertionError('Parser attempted file access')):
            for raw in attacks:
                for encoding in ('utf-8', 'utf-16'):
                    data = raw if encoding == 'utf-8' else raw.decode().encode(encoding)
                    result = xmp.parse_bytes(data, source_id='s')
                    self.assertEqual((result.state, result.code), ('needs_attention', 'unsafe_xml'))
                    self.assertIsNone(result.source)

    def test_limits_hold_without_truncating_or_claiming_junk(self):
        with mock.patch.object(xmp, 'MAX_BYTES', 5):
            result = parsed()
            self.assertEqual(result.code, 'size_limit')
            self.assertIsNone(result.original_bytes)
        for constant, value in [('MAX_DEPTH', 3), ('MAX_NODES', 3), ('MAX_ATTRIBUTES', 1)]:
            with mock.patch.object(xmp, constant, value):
                result = parsed('<dc:title>test</dc:title>', 'tiff:Make="Camera"')
                self.assertEqual((result.state, result.code), ('needs_attention', 'xml_limit'))
                self.assertIsNotNone(result.original_bytes)

    def test_malformed_unknown_and_unrelated_inputs_have_distinct_results(self):
        for data in (b'<x:xmpmeta', b'not XML at all', b'\x01\x02'):
            result = xmp.parse_bytes(data, source_id='s')
            self.assertEqual(result.state, 'needs_attention')
            self.assertIsNone(result.source)
        for data in (b'', b'\xff\xd8\xfffake', b'PK\x03\x04fake', b'<unrelated/>'):
            self.assertEqual(xmp.parse_bytes(data, source_id='s').state, 'not_xmp')

    def test_embedded_rdf_in_unknown_wrapper_is_held_not_discarded(self):
        raw = b'<unexpected>' + packet() + b'</unexpected>'
        result = xmp.parse_bytes(raw, source_id='s')
        self.assertEqual((result.state, result.code), ('needs_attention', 'unsupported_packet'))
        self.assertEqual(result.original_bytes, raw)

    def test_unqualified_or_rdf_properties_cannot_masquerade_as_xmp(self):
        for body in ('<Rating>5</Rating>', '<rdf:li>anything</rdf:li>'):
            self.assertEqual(parsed(body).state, 'needs_attention')

    def test_repeated_mapped_fields_and_unsupported_structures_hold(self):
        for body in ('<xmp:Rating>1</xmp:Rating><xmp:Rating>2</xmp:Rating>',
                     '<exif:DateTimeOriginal rdf:resource="urn:date"/>',
                     '<dc:description><rdf:Alt><rdf:li xml:lang="en">a</rdf:li>'
                     '<rdf:li xml:lang="en">b</rdf:li></rdf:Alt></dc:description>',
                     '<dc:creator><rdf:Bag><rdf:li>A</rdf:li></rdf:Bag></dc:creator>'):
            with self.subTest(body=body):
                result = parsed(body)
                self.assertEqual(result.state, 'needs_attention')
                self.assertIsNone(result.source)
                self.assertIsNotNone(result.tags['xml'])
                self.assertEqual(result.original_bytes, packet(body))
        self.assertEqual(parsed('<xmp:Rating>1</xmp:Rating>', 'xmp:Rating="1"').code, 'repeated_field')

    def test_separate_descriptions_and_direct_rdf_root(self):
        data = (f'<rdf:RDF xmlns:rdf="{xmp.RDF}" xmlns:xmp="{xmp.XAP}" xmlns:tiff="{xmp.TIFF}">'
                '<rdf:Description rdf:about="" xmp:Rating="1"/>'
                '<rdf:Description rdf:about="" tiff:Make="Camera"/></rdf:RDF>').encode()
        self.assertEqual(xmp.parse_bytes(data, source_id='s').source.fields,
                         {'rating': '1', 'camera_make': 'Camera'})
        self.assertEqual(xmp.parse_bytes(data.replace(b'about=""', b'about="other"'), source_id='s').code,
                         'unsupported_subject')

    def test_owner_names_are_literals_not_paths(self):
        self.assertEqual(parsed(attributes='crs:RawFileName="photo.CR2"').owner_name, 'photo.CR2')
        for owner in ('../photo.CR2', '/photo.CR2', 'dir/photo.CR2', 'dir\\photo.CR2', ''):
            result = parsed(attributes=f'crs:RawFileName="{owner}"')
            self.assertEqual((result.state, result.code), ('needs_attention', 'invalid_owner'))
        self.assertEqual(parsed('<crs:RawFileName>a</crs:RawFileName>',
                                'crs:RawFileName="b"').code, 'repeated_owner')

    def test_create_date_and_lookalike_namespace_never_supply_capture_date(self):
        result = parsed('<xmp:CreateDate>2020-01-01</xmp:CreateDate><custom:DateTimeOriginal>2000</custom:DateTimeOriginal>')
        self.assertNotIn('date_taken', result.source.fields)
        self.assertEqual(len(result.tags['properties']), 2)


class ValueValidationTests(unittest.TestCase):
    def test_dates_preserve_precision_timezone_and_suspicious_but_possible_years(self):
        for value in ('0000', '0001-01-01', '1999', '2004-02', '2000-02-29',
                      '2218-09-22', '2004-01-02T03:04', '2004-01-02T03:04Z',
                      '2004-01-02T03:04:05', '2004-01-02T03:04:05.123456789',
                      '2004-01-02T03:04:05+05:30', '2004-01-02T03:04:05-03:30'):
            with self.subTest(value=value):
                result = parsed(f'<exif:DateTimeOriginal>{value}</exif:DateTimeOriginal>')
                self.assertEqual((result.state, result.code), ('valid', 'parsed'))
                self.assertEqual(result.source.fields['date_taken'], value)

    def test_impossible_or_unsupported_dates_hold_original_without_fallback(self):
        for value in ('not a date', '2001-02-29', '1900-02-29', '2004-04-31',
                      '2004-00-01', '2004-13', '2004-01-00', '2004-01-32',
                      '2004-01-02T24:00', '2004-01-02T12:60', '2004-01-02T12:00:60',
                      '2004-01-02T12:00+24:00', '2004-01-02T12:00+01:60',
                      '2004-01-02T12:00:00.', '2004-01-02T12:00+0200',
                      '2004:01:02 12:00:00', '2004-01-02Z', '2004-1-2', ' 2004',
                      '2004-01-02T12:00:00Zjunk', '２００４'):
            with self.subTest(value=value):
                raw = packet(f'<exif:DateTimeOriginal>{value}</exif:DateTimeOriginal>',
                             'tiff:Make="Retained camera"')
                result = xmp.parse_bytes(raw, source_id='s')
                self.assertEqual((result.state, result.code), ('needs_attention', 'invalid_date_taken'))
                self.assertIsNone(result.source)
                self.assertEqual(result.original_bytes, raw)
                self.assertIn('{'+xmp.TIFF+'}Make', result.tags['properties'])

    def test_orientation_valid_integer_forms_and_invalid_values(self):
        for value in ('1', '2', '3', '4', '5', '6', '7', '8', '+06', '0001', ''):
            with self.subTest(value=value):
                result = parsed(attributes=f'tiff:Orientation="{value}"')
                self.assertEqual(result.state, 'valid')
                self.assertEqual(result.source.fields['orientation'], value)
        for value in ('0', '9', '-1', '1.0', '1e0', 'normal', '１', ' 1', '1 ', '9'*5000):
            with self.subTest(value=value[:40]):
                result = parsed(attributes=f'tiff:Orientation="{value}"')
                self.assertEqual((result.state, result.code), ('needs_attention', 'invalid_orientation'))
                self.assertIsNone(result.source)

    def test_rating_is_decimal_range_not_integer_stars_or_float_rounding(self):
        for value in ('-1', '-1.0', '0', '-0', '+0', '.5', '2.5', '5', '05.000', ''):
            with self.subTest(value=value):
                result = parsed(attributes=f'xmp:Rating="{value}"')
                self.assertEqual(result.state, 'valid')
                self.assertEqual(result.source.fields['rating'], value)
        for value in ('-2', '-.5', '5.0000000000000000000000000000001',
                      '-1.000000000000000000000000000001', '6', 'NaN', 'Infinity',
                      '1e0', '1.', '.', 'five', ' 1', '１', '9'*5000):
            with self.subTest(value=value[:40]):
                result = parsed(attributes=f'xmp:Rating="{value}"')
                self.assertEqual((result.state, result.code), ('needs_attention', 'invalid_rating'))
                self.assertIsNone(result.source)

    def test_explicit_blanks_clear_typed_fields_and_unknown_values_stay_uninterpreted(self):
        result = parsed('<exif:DateTimeOriginal/><tiff:Orientation/><xmp:Rating/>'
                        '<custom:Rating>5000</custom:Rating><custom:date>invalid</custom:date>')
        resolved = metadata_capture.resolve({
            'exif': {'fields': {'date_taken': '2004', 'orientation': 6, 'rating': 5}},
            'generated': {'fields': result.source.fields}}, ['generated', 'exif'])
        self.assertEqual(resolved['proposed_effective'], {'date_taken': '', 'orientation': '', 'rating': ''})
        self.assertEqual(len(result.tags['properties']), 5)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = packet('<dc:title>Generated</dc:title>')
        (self.root / 'photo.xmp').write_bytes(self.data)

    def read(self, name='photo.xmp'):
        return xmp.read_sidecar(self.root, name, source_id='file')

    def test_regular_nested_unicode_and_spaces_untouched(self):
        folder = self.root / '雪 folder'
        folder.mkdir()
        path = folder / 'multi.part.CR2.XMP'
        path.write_bytes(self.data)
        before = path.stat()
        result = self.read('雪 folder/multi.part.CR2.XMP')
        self.assertEqual(result.state, 'valid')
        self.assertEqual(result.original_bytes, self.data)
        self.assertEqual(path.read_bytes(), self.data)
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_exiftool_generated_sidecar_interoperates_with_resolver(self):
        path = self.root / 'written.xmp'
        command = ['exiftool', '-XMP-exif:DateTimeOriginal=2004:01:02 03:04:05+02:00',
                   '-XMP-dc:Description=Generated caption', '-XMP-dc:Subject=one',
                   '-XMP-dc:Subject+=two', '-XMP-xmp:Rating=0', str(path)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = self.read('written.xmp')
        self.assertEqual((result.state, result.code), ('valid', 'parsed'))
        self.assertEqual(result.source.fields['date_taken'], '2004-01-02T03:04:05+02:00')
        self.assertEqual(result.source.fields['caption'], {'x-default': 'Generated caption'})
        self.assertEqual(result.source.fields['keywords'], ['one', 'two'])
        self.assertEqual(result.source.fields['rating'], '0')
        self.assertEqual(result.original_bytes, path.read_bytes())

    def exiftool(self, *arguments):
        completed = subprocess.run(['exiftool', *arguments], capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout

    def test_independent_exiftool_reads_generated_packets_without_changing_originals(self):
        # ExifTool is an independent reader, not a complete XMP-conformance oracle.
        for encoding in ('utf-8', 'utf-16'):
            for rating in ('-1', '0', '2.5', '5'):
                with self.subTest(encoding=encoding, rating=rating):
                    text = packet('<exif:DateTimeOriginal>2004-02-29T23:59:58.123+05:30</exif:DateTimeOriginal>'
                                  '<dc:subject><rdf:Bag><rdf:li>雪</rdf:li><rdf:li>two</rdf:li></rdf:Bag></dc:subject>'
                                  '<dc:description><rdf:Alt><rdf:li xml:lang="x-default">A &amp; B</rdf:li></rdf:Alt></dc:description>',
                                  f'tiff:Orientation="6" tiff:Make="Camera" xmp:Rating="{rating}"').decode()
                    raw = (f'<?xml version="1.0" encoding="{encoding}"?>' + text).encode(encoding)
                    path = self.root / 'independent.xmp'
                    path.write_bytes(raw)
                    own = self.read(path.name)
                    self.assertEqual(own.state, 'valid')
                    other = json.loads(self.exiftool('-j', '-G1', '-n', '-XMP:all', '-Warning', '-Error', str(path)))[0]
                    self.assertFalse(any(key.endswith((':Warning', ':Error')) for key in other), other)
                    self.assertEqual(other['XMP-tiff:Orientation'], int(own.source.fields['orientation']))
                    self.assertEqual(other['XMP-xmp:Rating'], float(own.source.fields['rating']))
                    self.assertEqual(other['XMP-tiff:Make'], own.source.fields['camera_make'])
                    self.assertEqual(other['XMP-dc:Subject'], own.source.fields['keywords'])
                    self.assertEqual(other['XMP-dc:Description'], own.source.fields['caption']['x-default'])
                    self.assertEqual(other['XMP-exif:DateTimeOriginal'], '2004:02:29 23:59:58.123+05:30')
                    self.assertEqual(path.read_bytes(), raw)
                    self.assertEqual(own.original_bytes, raw)

    def test_exiftool_written_orientation_and_rating_matrix_is_supported(self):
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                path = self.root / f'generated-{orientation}.xmp'
                rating = ('-1', '0', '2.5', '5')[(orientation - 1) % 4]
                self.exiftool(f'-XMP-tiff:Orientation#={orientation}', f'-XMP-xmp:Rating={rating}',
                              '-XMP-exif:DateTimeOriginal=2000:02:29 12:30:45',
                              '-XMP-dc:Title=Generated title', str(path))
                result = self.read(path.name)
                self.assertEqual(result.state, 'valid')
                self.assertEqual(result.source.fields['orientation'], str(orientation))
                self.assertEqual(result.source.fields['rating'], rating)
                self.assertEqual(result.source.fields['date_taken'], '2000-02-29T12:30:45')
                self.assertEqual(result.source.fields['title'], {'x-default': 'Generated title'})

    def test_traversal_absolute_and_non_xmp_names_refused(self):
        for name in ('../a.xmp', '/a.xmp', 'a/../photo.xmp', './photo.xmp', 'a//b.xmp',
                     'a\\b.xmp', 'a\x00.xmp', 'photo.jpg'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.read(name)

    def test_symlinks_leaf_parent_and_root_refused(self):
        (self.root / 'link.xmp').symlink_to(self.root / 'photo.xmp')
        (self.root / 'folder').symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.read('link.xmp').state, 'needs_attention')
        self.assertEqual(self.read('folder/photo.xmp').state, 'needs_attention')
        result = xmp.read_sidecar(self.root / 'folder', 'photo.xmp', source_id='s')
        self.assertEqual(result.state, 'needs_attention')

    def test_fifo_directory_missing_and_permission_errors_hold(self):
        os.mkfifo(self.root / 'pipe.xmp')
        (self.root / 'dir.xmp').mkdir()
        for name in ('pipe.xmp', 'dir.xmp', 'absent.xmp'):
            self.assertEqual(self.read(name).state, 'needs_attention')
        with mock.patch.object(xmp.os, 'open', side_effect=PermissionError(errno.EACCES, 'denied')):
            result = self.read()
            self.assertEqual(result.code, 'read_error')
            self.assertIn('denied', result.detail)
            self.assertIsNone(result.original_bytes)

    def test_changed_content_or_replaced_name_is_not_archived(self):
        actual_read = os.read
        changed = False
        def read_then_change(fd, count):
            nonlocal changed
            data = actual_read(fd, count)
            if not changed:
                changed = True
                (self.root / 'photo.xmp').write_bytes(self.data + b' ')
            return data
        with mock.patch.object(xmp.os, 'read', side_effect=read_then_change):
            result = self.read()
        self.assertEqual(result.code, 'changed_during_read')
        self.assertIsNone(result.original_bytes)
        (self.root / 'photo.xmp').write_bytes(self.data)
        changed = False
        def read_then_replace(fd, count):
            nonlocal changed
            data = actual_read(fd, count)
            if not changed:
                changed = True
                (self.root / 'replacement').write_bytes(self.data)
                os.replace(self.root / 'replacement', self.root / 'photo.xmp')
            return data
        with mock.patch.object(xmp.os, 'read', side_effect=read_then_replace):
            self.assertEqual(self.read().code, 'changed_during_read')

    def test_parent_replaced_during_read_is_held(self):
        folder = self.root / 'folder'
        folder.mkdir()
        (folder / 'photo.xmp').write_bytes(self.data)
        actual_read = os.read
        changed = False
        def read_then_replace_parent(fd, count):
            nonlocal changed
            data = actual_read(fd, count)
            if not changed:
                changed = True
                folder.rename(self.root / 'old-folder')
                folder.mkdir()
                (folder / 'photo.xmp').write_bytes(self.data)
            return data
        with mock.patch.object(xmp.os, 'read', side_effect=read_then_replace_parent):
            result = self.read('folder/photo.xmp')
        self.assertEqual(result.code, 'changed_during_read')
        self.assertIsNone(result.original_bytes)

    def test_five_gibibyte_sidecar_is_refused_before_reading_any_bytes(self):
        path = self.root / 'huge.xmp'
        with path.open('wb') as stream:
            stream.truncate(5 * 1024 ** 3)  # Sparse generated file; no huge allocation.
        before = path.stat()
        with mock.patch.object(xmp.os, 'read', side_effect=AssertionError('Oversized file was read')):
            result = self.read('huge.xmp')
        self.assertEqual((result.state, result.code), ('needs_attention', 'size_limit'))
        self.assertIsNone(result.original_bytes)
        self.assertIsNone(result.source)
        self.assertEqual(path.stat().st_size, before.st_size)
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_large_or_growing_input_is_never_partially_captured(self):
        with mock.patch.object(xmp, 'MAX_BYTES', 4):
            result = self.read()
            self.assertEqual(result.code, 'size_limit')
            self.assertIsNone(result.original_bytes)
        with mock.patch.object(xmp, 'MAX_BYTES', len(self.data)), \
                mock.patch.object(xmp.os, 'read', return_value=b'x' * (len(self.data) + 1)):
            result = self.read()
            self.assertEqual(result.code, 'size_limit')
            self.assertIsNone(result.original_bytes)


class AssociationTests(unittest.TestCase):
    def setUp(self):
        self.inventory = xmp_association.PhotoInventory(['photo.CR2', 'photo.jpg', 'other/photo.jpg'])
        self.good = parsed()

    def test_full_filename_wins_for_every_policy(self):
        for policy in xmp_association.POLICIES:
            result = self.inventory.associate('photo.CR2.xmp', self.good, policy=policy)
            self.assertEqual((result.state, result.photos, result.basis),
                             ('associated', ('photo.CR2',), 'full_name'))

    def test_short_name_policy_matrix(self):
        expected = {'ask': ('needs_choice', ('photo.CR2', 'photo.jpg')),
                    'raw_only': ('associated', ('photo.CR2',)),
                    'non_raw_only': ('associated', ('photo.jpg',)),
                    'all': ('associated', ('photo.CR2', 'photo.jpg'))}
        for policy, (state, photos) in expected.items():
            result = self.inventory.associate('photo.xmp', self.good, policy=policy)
            self.assertEqual((result.state, result.photos), (state, photos))

    def test_raw_or_nonraw_ambiguity_is_not_resolved_arbitrarily(self):
        for paths, policy in [(['a.CR2', 'a.DNG', 'a.jpg'], 'raw_only'),
                              (['a.CR2', 'a.jpg', 'a.png'], 'non_raw_only'),
                              (['a.jpg', 'a.png'], 'raw_only')]:
            inv = xmp_association.PhotoInventory(paths)
            self.assertEqual(inv.associate('a.xmp', self.good, policy=policy).state, 'needs_choice')

    def test_single_candidate_and_directory_boundaries(self):
        result = self.inventory.associate('other/photo.XMP', self.good, policy='raw_only')
        self.assertEqual(result.photos, ('other/photo.jpg',))
        self.assertEqual(result.state, 'associated')
        self.assertEqual(self.inventory.associate('missing/photo.xmp', self.good, policy='all').state, 'orphan')

    def test_declared_owner_precedes_policy_but_cannot_escape_name_binding(self):
        owner = parsed(attributes='crs:RawFileName="photo.CR2"')
        result = self.inventory.associate('photo.xmp', owner, policy='non_raw_only')
        self.assertEqual(result.photos, ('photo.CR2',))
        self.assertEqual(result.basis, 'declared_owner')
        self.assertEqual(self.inventory.associate('photo.jpg.xmp', owner, policy='all').reason, 'owner_conflict')
        missing = parsed(attributes='crs:RawFileName="absent.CR2"')
        self.assertEqual(self.inventory.associate('photo.xmp', missing, policy='all').state, 'needs_choice')

    def test_invalid_sidecar_holds_all_candidates_but_non_xmp_does_not(self):
        bad = xmp.parse_bytes(b'<broken', source_id='s')
        result = self.inventory.associate('photo.xmp', bad, policy='raw_only')
        self.assertEqual((result.state, result.photos), ('needs_attention', ('photo.CR2', 'photo.jpg')))
        junk = xmp.parse_bytes(b'', source_id='s')
        self.assertEqual(self.inventory.associate('photo.xmp', junk, policy='ask').state, 'ignored')

    def test_both_names_keep_all_associations_but_prefer_full_for_new_photo(self):
        short = self.inventory.associate('photo.xmp', self.good, policy='all')
        full = self.inventory.associate('photo.CR2.xmp', self.good, policy='ask')
        self.assertEqual(xmp_association.primary_candidates([short, full]),
                         {'photo.CR2': ('photo.CR2.xmp',), 'photo.jpg': ('photo.xmp',)})
        self.assertEqual(short.photos, ('photo.CR2', 'photo.jpg'))
        unresolved = self.inventory.associate('photo.xmp', self.good, policy='ask')
        self.assertNotIn('photo.CR2', xmp_association.primary_candidates([unresolved, full]))

    def test_multiple_full_names_are_not_chosen_by_order(self):
        a = self.inventory.associate('photo.CR2.xmp', self.good, policy='all')
        b = self.inventory.associate('photo.CR2.XMP', self.good, policy='all')
        self.assertEqual(xmp_association.primary_candidates([a, b]),
                         xmp_association.primary_candidates([b, a]))
        self.assertEqual(len(xmp_association.primary_candidates([a, b])['photo.CR2']), 2)

    def test_orphan_is_reconsidered_and_case_is_not_conflated(self):
        empty = xmp_association.PhotoInventory([])
        self.assertEqual(empty.associate('photo.xmp', self.good, policy='ask').state, 'orphan')
        inv = xmp_association.PhotoInventory(['photo.CR2', 'Photo.jpg', '雪.multi.part.jpg'])
        self.assertEqual(inv.associate('photo.xmp', self.good, policy='ask').photos, ('photo.CR2',))
        self.assertEqual(inv.associate('雪.multi.part.xmp', self.good, policy='all').photos,
                         ('雪.multi.part.jpg',))

    def test_inventory_and_policy_validation(self):
        for paths in (['../a.jpg'], ['a.jpg', 'a.jpg'], ['a.txt']):
            with self.assertRaises(ValueError):
                xmp_association.PhotoInventory(paths)
        with self.assertRaises(ValueError):
            self.inventory.associate('photo.xmp', self.good, policy='guess')
        with self.assertRaises(ValueError):
            self.inventory.associate('../photo.xmp', self.good, policy='ask')
