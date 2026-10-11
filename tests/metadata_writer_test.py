"""Generated preservation-aware XMP edits and independent reader checks."""
import subprocess
import tempfile
from pathlib import Path
import unittest

import metadata_index_test
from engine import metadata_adapter, metadata_writer, xmp


class Writer(unittest.TestCase):
    def fields(self,data):
        return metadata_adapter.for_comparison(xmp.parse_bytes(data,source_id='check').source).fields

    def test_only_date_changes_unknown_nested_properties_and_comments_survive(self):
        extra='<custom:complex xmlns:custom="urn:generated:custom"><rdf:Bag><rdf:li xml:lang="fr">été &amp; neige</rdf:li></rdf:Bag></custom:complex><!-- preserved -->'
        before=metadata_index_test.packet(extra=extra)
        after=metadata_writer.sidecar_bytes(before,{'date_taken':'2010-02-03T04:05:06'})
        self.assertEqual(self.fields(after)['date_taken'],'2010-02-03T04:05:06')
        self.assertIn(b'<!-- preserved -->',after)
        a=xmp.parse_bytes(before,source_id='a');b=xmp.parse_bytes(after,source_id='b')
        self.assertEqual(a.tags['properties']['{urn:generated:custom}complex'],b.tags['properties']['{urn:generated:custom}complex'])

    def test_noop_keeps_exact_original_bytes(self):
        before=metadata_index_test.packet()
        self.assertEqual(metadata_writer.sidecar_bytes(before,{'date_taken':'2005-03-04T05:06:07'}),before)

    def test_blank_is_present_and_no_other_fields_are_added(self):
        after=metadata_writer.sidecar_bytes(metadata_index_test.packet(),{'date_taken':''})
        self.assertEqual(self.fields(after),{'date_taken':''})

    def test_attribute_form_and_namespace_prefix_conflict_are_safe(self):
        before=(f'<rdf:RDF xmlns:rdf="{xmp.RDF}" xmlns:e="{xmp.EXIF}" xmlns:exif="urn:generated:other">'
            '<rdf:Description rdf:about="" e:DateTimeOriginal="2001-01-01"><exif:note>untouched</exif:note></rdf:Description></rdf:RDF>').encode()
        after=metadata_writer.sidecar_bytes(before,{'date_taken':'2009-02'})
        self.assertEqual(self.fields(after),{'date_taken':'2009-02'})
        self.assertIn('{urn:generated:other}note',xmp.parse_bytes(after,source_id='check').tags['properties'])

    def test_utf16_original_and_nonascii_unknown_values_survive(self):
        before=('<?xml version="1.0" encoding="UTF-16"?>'+metadata_index_test.packet(extra='<tiff:Make>写真機</tiff:Make>').decode()).encode('utf-16')
        after=metadata_writer.sidecar_bytes(before,{'orientation':6})
        self.assertEqual(self.fields(after)['camera_make'],'写真機');self.assertEqual(self.fields(after)['orientation'],6)

    def test_invalid_and_unsafe_originals_are_refused(self):
        for data in (b'not xml',b'<!DOCTYPE x [<!ENTITY e "bad">]><x>&e;</x>',metadata_index_test.packet('not a date')):
            with self.assertRaises(ValueError):metadata_writer.sidecar_bytes(data,{'orientation':1})

    def test_exiftool_independently_reads_new_date_and_orientation(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'generated.xmp'
            path.write_bytes(metadata_writer.sidecar_bytes(metadata_index_test.packet(),{'date_taken':'2010-02-03T04:05:06+03:00','orientation':8}))
            tags=json.loads(subprocess.check_output(['exiftool','-j','-n','-G1',str(path)]))[0]
            self.assertEqual(tags['XMP-exif:DateTimeOriginal'],'2010:02:03 04:05:06+03:00')
            self.assertEqual(tags['XMP-tiff:Orientation'],8)
