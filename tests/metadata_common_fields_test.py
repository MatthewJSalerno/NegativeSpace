"""Common-field plans, hostile inputs and independent ExifTool interoperability."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from engine import metadata_adapter, metadata_capture, metadata_edits, metadata_gps, metadata_writer, xmp
from engine.metadata import MetadataSource


class CommonFields(unittest.TestCase):
    def values(self):
        return {'date_taken':'2001-02-03T04:05:06.007+02:00','orientation':6,
                'title':{'x-default':'Title & < >','fr':'Été'}, 'caption':{'x-default':'Line 1\nLine 2'},
                'keywords':['second','first','été','semi;colon'],'creators':['One','Two'],
                'rights':{'x-default':'© Generated'},'rating':'4.5',
                'gps':{'latitude':'12,30N','longitude':'45,15W','altitude':'125/2','altitude_ref':'1'}}

    def fields(self,packet):
        parsed=xmp.parse_bytes(packet,source_id='fixture')
        self.assertEqual(parsed.state,'valid',parsed.code)
        return metadata_adapter.for_comparison(parsed.source).fields

    def test_common_fields_roundtrip_without_fallback(self):
        changes=self.values()
        packet=metadata_edits.first_sidecar(changes)
        self.assertEqual(self.fields(packet),changes)
        self.assertNotIn('camera_make',self.fields(packet))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.xmp';path.write_bytes(packet)
            tags=json.loads(subprocess.check_output(['exiftool','-j','-n','-G1',str(path)]))[0]
            self.assertNotIn('ExifTool:Warning',tags)
            self.assertEqual(tags['XMP-dc:Title'],'Title & < >')
            self.assertEqual(tags['XMP-dc:Title-fr'],'Été')
            self.assertEqual(tags['XMP-dc:Subject'],changes['keywords'])
            self.assertEqual(tags['XMP-dc:Creator'],changes['creators'])
            self.assertEqual(tags['XMP-dc:Rights'],'© Generated')
            self.assertEqual(tags['XMP-xmp:Rating'],4.5)
            self.assertEqual(tags['XMP-exif:GPSLatitude'],12.5)
            self.assertEqual(tags['XMP-exif:GPSLongitude'],-45.25)
            self.assertEqual(tags['XMP-exif:GPSAltitude'],62.5)
            self.assertEqual(tags['XMP-exif:GPSAltitudeRef'],1)

    def test_writer_preserves_unknowns_languages_and_array_order(self):
        original=metadata_edits.first_sidecar(self.values())
        after=metadata_writer.sidecar_bytes(original,{'keywords':['new','new','a&b']})
        fields=self.fields(after)
        expected=self.values();expected['keywords']=['new','new','a&b']
        self.assertEqual(fields,expected)
        self.assertEqual(metadata_writer.sidecar_bytes(after,{'keywords':['new','new','a&b']}),after)

    def test_arrays_and_localized_text_clear_explicitly(self):
        original=metadata_edits.first_sidecar(self.values())
        changes={'keywords':[],'creators':[],'title':'','caption':{},'rights':{'fr':''},'gps':{},'rating':''}
        after=self.fields(metadata_writer.sidecar_bytes(original,changes))
        self.assertEqual(after['title'],{'x-default':''})
        for key in changes:
            if key!='title':self.assertEqual(after[key],changes[key])
        self.assertEqual(after['date_taken'],self.values()['date_taken'])

    def test_namespace_prefix_collision_does_not_break_arrays(self):
        original=(f'<r:RDF xmlns:r="{xmp.RDF}" xmlns:rdf="urn:generated:other">'
                  '<r:Description r:about=""><rdf:note>keep</rdf:note></r:Description></r:RDF>').encode()
        after=metadata_writer.sidecar_bytes(original,{'title':{'fr':'Été'},'keywords':['a','b']})
        self.assertEqual(self.fields(after),{'title':{'fr':'Été'},'keywords':['a','b']})
        self.assertIn('{urn:generated:other}note',xmp.parse_bytes(after,source_id='check').tags['properties'])

    def test_invalid_types_and_xml_characters_are_refused_together(self):
        for bad in ({'title':42},{'caption':{'fr':False}},{'keywords':[1]}, {'creators':'flattened'},
                    {'rating':float('nan')},{'rights':{'':'no language'}},{'title':'nul\x00'},
                    {'caption':{'en" bad':'test'}},{'gps':{'latitude':'12,30N'}},
                    {'gps':{'latitude':'90,0.01N','longitude':'0,0E'}},
                    {'gps':{'latitude':'1,60N','longitude':'0,0E'}},
                    {'gps':{'latitude':'0,0N','longitude':'180,1E'}},
                    {'gps':{'latitude':'0,0N','longitude':'0,0E','altitude':'1/0','altitude_ref':'0'}},
                    {'gps':{'latitude':'0,0N','longitude':'0,0E','altitude':'1'}},
                    {'gps':{'latitude':12.5,'longitude':'0,0E'}},
                    {'gps':{'latitude':'0,0N','longitude':'0,0E','altitude':'-1','altitude_ref':'1'}}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):metadata_edits.first_sidecar(bad)

    def test_partial_recorded_gps_never_borrows_another_sources_longitude(self):
        packet=(f'<rdf:RDF xmlns:rdf="{xmp.RDF}" xmlns:exif="{xmp.EXIF}"><rdf:Description rdf:about="">'
                '<exif:GPSLatitude>12,30N</exif:GPSLatitude></rdf:Description></rdf:RDF>').encode()
        fields=self.fields(packet)
        source={'sidecar':{'kind':'sidecar_xmp','fields':fields},
                'exif':{'kind':'embedded_exif','fields':{'gps':{'latitude':'0,0N','longitude':'0,0E'}}}}
        result=metadata_capture.resolve(source,list(source),primary_id='sidecar')
        self.assertEqual(result['proposed_effective']['gps'],{'latitude':'12,30N'})
        with self.assertRaises(ValueError):metadata_edits.first_sidecar(fields)

    def test_precise_coordinates_and_boundaries_do_not_round_through_float(self):
        text=metadata_gps.coordinate('-12.123456789012345678901234567890','latitude')
        self.assertEqual(text,'12,7.407407340740740734074074073400S')
        for latitude,longitude in [('90,0N','180,0E'),('90,0S','180,0W'),('12,30,45.123N','45,15,0W')]:
            changes={'gps':{'latitude':latitude,'longitude':longitude}}
            self.assertEqual(self.fields(metadata_edits.first_sidecar(changes)),changes)

    def test_embedded_xmp_capture_retains_common_fields_separately(self):
        values={'XMP-dc:Title':'Title','XMP-dc:Title-fr':'Été','XMP-dc:Subject':['two','one'],
                'XMP-exif:GPSLatitude':'12.5','XMP-exif:GPSLongitude':'-45.25',
                'XMP-exif:GPSAltitude':'62.5','XMP-exif:GPSAltitudeRef':'1'}
        result=metadata_capture.interpret(values)
        self.assertEqual(result['issues'],[])
        fields=result['sources']['embedded_xmp']['fields']
        self.assertEqual(fields['title'],{'x-default':'Title','fr':'Été'})
        self.assertEqual(fields['gps'],{'latitude':'12,30.0N','longitude':'45,15.00W','altitude':'62.5','altitude_ref':'1'})
        self.assertEqual(result['tags'],values)

    def test_readonly_plan_common_fields_does_not_change_date_or_filing(self):
        source={'exif':{'kind':'embedded_exif','fields':{'date_taken':'2001-02-03'}}}
        result=metadata_edits.plan(source,primary_id=None,changes={'title':'New','keywords':['one']},
              settings={},photo_name='photo.cr2',original_year=2000,current_relative_path='library/2001/02/03/photo.cr2')
        self.assertFalse(result['filing']['change'])
        self.assertEqual(result['target_fields_after'],{'title':{'x-default':'New'},'keywords':['one']})
        self.assertEqual(result['after']['proposed_effective']['date_taken'],'2001-02-03')

    def test_qualified_exif_common_fields_and_gps_remain_a_separate_source(self):
        result=metadata_capture.interpret({'IFD0:XPTitle':'Original','IFD0:ImageDescription':'Caption',
            'IFD0:Artist':'Artist','IFD0:Copyright':'Rights','IFD0:Rating':'4','IFD0:XPKeywords':'two;one',
            'GPS:GPSLatitude':'12.5','GPS:GPSLatitudeRef':'S',
            'GPS:GPSLongitude':'45.25','GPS:GPSLongitudeRef':'E',
            'XMP-dc:Title':'Preferred'})
        self.assertEqual(result['issues'],[])
        fields=result['sources']['exif']['fields']
        self.assertEqual(fields['title'],'Original')
        self.assertEqual(fields['caption'],'Caption')
        self.assertEqual(fields['creators'],['Artist'])
        self.assertEqual(fields['keywords'],['two','one'])
        self.assertEqual(fields['gps'],{'latitude':'12,30.0S','longitude':'45,15.00E'})
        self.assertEqual(result['sources']['embedded_xmp']['fields']['title'],'Preferred')

    def test_incomplete_exif_gps_is_not_made_valid_by_an_xmp_reference(self):
        result=metadata_capture.interpret({'GPS:GPSLatitude':'12.5','XMP-exif:GPSLatitude':'12.5'})
        self.assertTrue(any(issue['source']=='exif' for issue in result['issues']))
        self.assertNotIn('exif',result['sources'])

    def test_invalid_gps_reference_type_is_an_issue_not_an_index_crash(self):
        result=metadata_capture.interpret({'GPS:GPSLatitude':'12.5','GPS:GPSLatitudeRef':True})
        self.assertEqual(result['issues'],[{'source':'exif','code':'invalid_gps_reference'}])
