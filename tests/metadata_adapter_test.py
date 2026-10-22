"""Generated captures and actual ExifTool writes; no library or catalog changes."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from PIL import Image
from engine import metadata_adapter, metadata_capture, xmp
from engine.metadata import MetadataSource


def sidecar(properties=''):
    raw = (f'<rdf:RDF xmlns:rdf="{xmp.RDF}"><rdf:Description rdf:about="" '
           f'xmlns:exif="{xmp.EXIF}" xmlns:tiff="{xmp.TIFF}" xmlns:xmp="{xmp.XAP}" '
           f'xmlns:dc="{xmp.DC}">{properties}</rdf:Description></rdf:RDF>').encode()
    result = xmp.parse_bytes(raw, source_id='sidecar')
    if result.state != 'valid':
        raise AssertionError(result.code)
    return result.source


class AdapterTests(unittest.TestCase):
    def test_same_date_orientation_and_camera_do_not_create_false_differences(self):
        embedded = metadata_adapter.from_embedded({
            'ExifIFD:DateTimeOriginal': '2020:02:29 12:34:56',
            'ExifIFD:SubSecTimeOriginal': '0070', 'ExifIFD:OffsetTimeOriginal': '+00:00',
            'IFD0:Orientation': 6, 'IFD0:Make': 'Generated', 'IFD0:Model': 'Camera'}, source_id='photo')
        original = sidecar('<exif:DateTimeOriginal>2020-02-29T12:34:56.0070Z</exif:DateTimeOriginal>'
                           '<tiff:Orientation>06</tiff:Orientation><tiff:Make>Generated</tiff:Make>'
                           '<tiff:Model>Camera</tiff:Model>')
        normalized = metadata_adapter.for_comparison(original)
        result = metadata_capture.resolve({'photo': {'fields': embedded.fields}, 'sidecar': {'fields': normalized.fields}}, ['sidecar', 'photo'])
        self.assertEqual(embedded.fields, normalized.fields)
        self.assertEqual(result['field_sources']['date_taken'], 'sidecar')
        self.assertEqual(original.fields['orientation'], '06')
        self.assertEqual(normalized.original_bytes, original.original_bytes)
        self.assertEqual(normalized.tags, original.tags)

    def test_whole_capture_and_unknown_tags_are_preserved_and_detached(self):
        tags = {'IFD0:Make': '  Camera  ', 'MakerNotes:Custom': ['unknown'],
                'IFD1:Orientation': 8, 'XMP-tiff:Orientation': 3}
        result = metadata_adapter.from_embedded(tags, source_id='photo')
        self.assertEqual(result.fields, {'camera_make': '  Camera  '})
        self.assertEqual(result.tags, tags)
        result.tags['MakerNotes:Custom'].append('local')
        self.assertEqual(tags['MakerNotes:Custom'], ['unknown'])

    def test_flat_or_print_converted_metadata_is_not_guessed(self):
        for tags in ({'DateTimeOriginal': '2020:01:02 03:04:05'},
                     {'IFD0:Orientation': 'Rotate 90 CW'}, {'IFD0:Make': 123}):
            with self.subTest(tags=tags), self.assertRaises(ValueError):
                metadata_adapter.from_embedded(tags, source_id='photo')

    def test_other_dates_never_become_capture_dates(self):
        tags = {'ExifIFD:CreateDate': '2020:01:01 00:00:00',
                'IFD0:ModifyDate': '2020:01:02 00:00:00',
                'File:FileModifyDate': '2020:01:03 00:00:00',
                'MakerNotes:DateTimeOriginal': '2020:01:04 00:00:00',
                'XMP-exif:DateTimeOriginal': '2020:01:05 00:00:00'}
        self.assertEqual(metadata_adapter.from_embedded(tags, source_id='photo').fields, {})

    def test_empty_and_partial_primary_dates_do_not_revive_embedded_date(self):
        embedded = metadata_adapter.from_embedded({'ExifIFD:DateTimeOriginal': '2020:01:02 03:04:05'}, source_id='photo')
        for value in ('', '1999', '1999-04', '0000', '2218-01-01'):
            with self.subTest(value=value):
                chosen = metadata_adapter.for_comparison(sidecar(f'<exif:DateTimeOriginal>{value}</exif:DateTimeOriginal>'))
                result = metadata_capture.resolve({'photo': {'fields': embedded.fields}, 'sidecar': {'fields': chosen.fields}}, ['sidecar', 'photo'])
                self.assertEqual(result['proposed_effective']['date_taken'], value)
                self.assertEqual(result['field_sources']['date_taken'], 'sidecar')
        absent = metadata_adapter.for_comparison(sidecar())
        self.assertEqual(metadata_capture.resolve({'photo': {'fields': embedded.fields}, 'sidecar': {'fields': absent.fields}}, ['sidecar', 'photo'])['proposed_effective'], embedded.fields)

    def test_no_timezone_or_fraction_is_invented_or_borrowed(self):
        embedded = metadata_adapter.from_embedded({'ExifIFD:DateTimeOriginal': '2020:01:02 03:04:05',
                                                  'ExifIFD:OffsetTimeOriginal': '+03:00',
                                                  'ExifIFD:SubSecTimeOriginal': '125'}, source_id='photo')
        chosen = metadata_adapter.for_comparison(sidecar('<exif:DateTimeOriginal>2020-01-02T03:04:05</exif:DateTimeOriginal>'))
        result = metadata_capture.resolve({'photo': {'fields': embedded.fields}, 'sidecar': {'fields': chosen.fields}}, ['sidecar', 'photo'])
        self.assertEqual(result['proposed_effective']['date_taken'], '2020-01-02T03:04:05')
        self.assertNotEqual(embedded.fields['date_taken'], chosen.fields['date_taken'])
        plain = metadata_adapter.from_embedded({'ExifIFD:DateTimeOriginal': '2020:01:02 03:04:05'}, source_id='plain')
        self.assertEqual(plain.fields['date_taken'], '2020-01-02T03:04:05')

    def test_recorded_date_precision_and_wall_clock_remain_distinct(self):
        values = ('2020-01-02', '2020-01-02T03:04', '2020-01-02T03:04:00',
                  '2020-01-02T03:04:00.0', '2020-01-02T03:04:00-00:00',
                  '2020-01-02T03:04:00+00:00', '2020-01-02T04:04:00+01:00')
        for value in values:
            self.assertEqual(metadata_adapter.for_comparison(sidecar(
                f'<exif:DateTimeOriginal>{value}</exif:DateTimeOriginal>')).fields['date_taken'], value)

    def test_invalid_or_dangling_date_components_refuse_the_view(self):
        bad = [ {'ExifIFD:SubSecTimeOriginal': '123'}, {'ExifIFD:OffsetTimeOriginal': '+01:00'} ]
        for value in ('2021:02:29 00:00:00', '0000:00:00 00:00:00', '2020:01:01 24:00:00', None):
            bad.append({'ExifIFD:DateTimeOriginal': value})
        for key, value in (('ExifIFD:SubSecTimeOriginal', 123), ('ExifIFD:SubSecTimeOriginal', ''),
                           ('ExifIFD:SubSecTimeOriginal', '12x'), ('ExifIFD:OffsetTimeOriginal', '+24:00'),
                           ('ExifIFD:OffsetTimeOriginal', '+01:60'), ('ExifIFD:OffsetTimeOriginal', '')):
            bad.append({'ExifIFD:DateTimeOriginal': '2020:01:01 00:00:00', key: value})
        for tags in bad:
            with self.subTest(tags=tags), self.assertRaises(ValueError):
                metadata_adapter.from_embedded(tags, source_id='photo')

    def test_orientation_rejects_booleans_numbers_outside_range_and_blanks_stay_blank(self):
        for value in (False, True, 0, 9, 6.0, None, ' ', '6.0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                metadata_adapter.from_embedded({'IFD0:Orientation': value}, source_id='photo')
        self.assertEqual(metadata_adapter.from_embedded({'IFD0:Orientation': ''}, source_id='photo').fields, {'orientation': ''})

    def test_rating_normalization_is_exact_and_zero_is_not_missing(self):
        for value, expected in (('+00.00', '0'), ('-0', '0'), ('-1.00', '-1'), ('4.500', '4.5'),
                                ('4.999999999999999999999999999999', '4.999999999999999999999999999999')):
            self.assertEqual(metadata_adapter.for_comparison(sidecar(f'<xmp:Rating>{value}</xmp:Rating>')).fields['rating'], expected)
        for value in (True, 4.5, 'NaN', '5.000000000000000000000000000001'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                metadata_adapter.for_comparison(MetadataSource('photo', 'embedded', {}, {'rating': value}))

    def test_arrays_localized_values_and_explicit_empty_shapes_are_not_flattened(self):
        source = sidecar('<dc:subject><rdf:Bag><rdf:li>b</rdf:li><rdf:li>a</rdf:li></rdf:Bag></dc:subject>'
                         '<dc:description><rdf:Alt><rdf:li xml:lang="fr">Texte</rdf:li>'
                         '<rdf:li xml:lang="x-default"></rdf:li></rdf:Alt></dc:description>')
        result = metadata_adapter.for_comparison(source)
        self.assertEqual(result.fields, source.fields)
        result.fields['keywords'].append('new')
        self.assertEqual(source.fields['keywords'], ['b', 'a'])

    def test_invalid_source_bindings_and_non_json_values_are_refused(self):
        for source in (MetadataSource('', 'embedded', {}, {}), MetadataSource('s', 'other', {}, {}),
                       MetadataSource('s', 'xmp', {}, {}), MetadataSource('s', 'embedded', {}, {}, b'bytes'),
                       MetadataSource('s', 'embedded', {'tag': float('nan')}, {})):
            with self.subTest(source=source), self.assertRaises(ValueError):
                metadata_adapter.for_comparison(source)

    def test_real_exiftool_generated_jpeg_and_tiff_agree_with_xmp(self):
        # JSONQ avoids turning textual camera names or fractional seconds into numbers.
        with tempfile.TemporaryDirectory() as directory:
            for suffix in ('jpg', 'tiff'):
                with self.subTest(suffix=suffix):
                    path = Path(directory) / ('generated.' + suffix)
                    Image.new('RGB', (32, 24), (10, 20, 30)).save(path)
                    subprocess.run(['exiftool', '-overwrite_original', '-EXIF:Make=123', '-EXIF:Model=007',
                        '-EXIF:DateTimeOriginal=2020:02:29 12:34:56', '-EXIF:SubSecTimeOriginal=0070',
                        '-EXIF:OffsetTimeOriginal=-05:00', '-EXIF:Orientation#=6', str(path)],
                        check=True, capture_output=True)
                    before = path.read_bytes()
                    captured = subprocess.run(['exiftool', '-j', '-G1', '-n', '-api', 'StructFormat=JSONQ', str(path)],
                                              check=True, capture_output=True)
                    tags = json.loads(captured.stdout)[0]
                    self.assertNotIn('ExifTool:Error', tags)
                    self.assertNotIn('ExifTool:Warning', tags)
                    embedded = metadata_adapter.from_embedded(tags, source_id='photo')
                    chosen = metadata_adapter.for_comparison(sidecar(
                        '<exif:DateTimeOriginal>2020-02-29T12:34:56.0070-05:00</exif:DateTimeOriginal>'
                        '<tiff:Orientation>6</tiff:Orientation><tiff:Make>123</tiff:Make><tiff:Model>007</tiff:Model>'))
                    self.assertEqual(embedded.fields, chosen.fields)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(tags['ExifIFD:DateTimeOriginal'], '2020:02:29 12:34:56')
