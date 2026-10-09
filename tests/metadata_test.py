"""Provenance/precedence contract using generated metadata and sidecar bytes."""
import base64
import hashlib
import json
import unittest

from engine import metadata
from engine.metadata import MetadataSource


class MetadataTests(unittest.TestCase):
    def embedded(self, fields=None, tags=None):
        return MetadataSource('photo', 'embedded', tags or {}, fields or {})

    def sidecar(self, source_id='sidecar', fields=None, tags=None, data=b'<xmp>generated</xmp>'):
        return MetadataSource(source_id, 'xmp', tags or {}, fields or {}, data)

    def resolve(self, embedded, *versions, active='sidecar'):
        return metadata.resolve_sources(embedded, versions, active_xmp_id=active)

    def test_xmp_wins_per_field_and_embedded_fills_absent_fields(self):
        original = self.embedded({'date_taken':'1999-01-01', 'camera':'Camera', 'caption':'Birthday'})
        xmp = self.sidecar(fields={'date_taken':'2009-01-01', 'caption':'Family'})
        result = self.resolve(original, xmp)
        self.assertEqual(result['effective'], {'date_taken':'2009-01-01', 'camera':'Camera', 'caption':'Family'})
        self.assertEqual(result['field_sources'], {'date_taken':'sidecar', 'camera':'photo', 'caption':'sidecar'})
        self.assertEqual(result['effective_source_kind'], 'mixed')
        self.assertEqual(result['primary_source_id'], 'sidecar')
        self.assertEqual(result['sources']['photo']['fields']['caption'], 'Birthday')

    def test_missing_and_explicitly_empty_fields_remain_distinguishable(self):
        original = self.embedded({'caption':'Birthday', 'date_taken':'1999-01-01'})
        xmp = self.sidecar(fields={'caption':''})
        result = self.resolve(original, xmp)
        self.assertEqual(result['effective'], {'caption':'', 'date_taken':'1999-01-01'})
        self.assertNotIn('date_taken', result['sources']['sidecar']['fields'])

    def test_zero_false_whitespace_and_structures_are_preserved(self):
        fields = {'rating':0, 'flag':False, 'caption':' ', 'keywords':['one', 'two'],
                  'localized':{'x-default':'Caption', 'fr':'Texte'}}
        result = self.resolve(self.embedded({key:'old' for key in fields}), self.sidecar(fields=fields))
        self.assertEqual(result['effective'], fields)
        self.assertEqual(result['primary_source_id'], 'sidecar')

    def test_all_explicit_empty_shapes_win_over_embedded_values(self):
        for value in ('', None, [], {}):
            with self.subTest(value=value):
                original = self.embedded({'value':'old'})
                sidecar = self.sidecar(fields={'value':value})
                self.assertEqual(self.resolve(original, sidecar)['effective']['value'], value)
        result = self.resolve(self.embedded(), self.sidecar(fields={'caption':''}))
        self.assertIn('caption', result['effective'])
        self.assertEqual(result['effective']['caption'], '')

    def test_alternatives_are_preserved_but_never_merged_or_auto_selected(self):
        first = self.sidecar('first', {'date_taken':'2009-01-01'})
        second = self.sidecar('second', {'date_taken':'2010-01-01', 'rating':5})
        result = self.resolve(self.embedded({'camera':'Camera'}), first, second, active='first')
        self.assertEqual(result['effective'], {'camera':'Camera', 'date_taken':'2009-01-01'})
        self.assertEqual(result['sources']['second']['fields']['rating'], 5)
        self.assertIn('date_taken', result['different_fields'])
        result = self.resolve(self.embedded({'camera':'Camera'}), first, second, active=None)
        self.assertEqual(result['effective'], {'camera':'Camera'})
        self.assertEqual(result['primary_source_id'], 'photo')

    def test_uninterpreted_tags_and_exact_sidecar_bytes_round_trip(self):
        raw = b'<?xml version="1.0"?>\r\n<xmp custom="unchanged">  </xmp>\r\n'
        original = self.embedded(tags={'MakerNotes:PrivateField':{'data':[1,2]}})
        sidecar = self.sidecar(tags={'XMP-custom:PrivateField':'retain'}, data=raw)
        result = json.loads(json.dumps(self.resolve(original, sidecar)))
        self.assertEqual(base64.b64decode(result['sources']['sidecar']['original_base64']), raw)
        self.assertEqual(result['sources']['sidecar']['sha1'], hashlib.sha1(raw).hexdigest())
        self.assertEqual(result['sources']['photo']['tags'], original.tags)
        self.assertEqual(result['sources']['sidecar']['tags'], sidecar.tags)
        self.assertEqual(result['effective'], {})  # No guessed aliases from raw tags.
        self.assertIsNone(result['effective_source_kind'])

    def test_inputs_and_snapshots_are_not_mutated_through_effective_values(self):
        original = self.embedded({'keywords':['original']})
        sidecar = self.sidecar(fields={'keywords':['chosen']})
        result = self.resolve(original, sidecar)
        result['effective']['keywords'].append('edited')
        self.assertEqual(sidecar.fields['keywords'], ['chosen'])
        self.assertEqual(result['sources']['sidecar']['fields']['keywords'], ['chosen'])
        result['sources']['photo']['fields']['keywords'].append('local')
        self.assertEqual(original.fields['keywords'], ['original'])

    def test_value_and_presence_differences_are_exact_not_truthiness(self):
        result = self.resolve(self.embedded({'rating':False, 'same':['a']}), self.sidecar(fields={'rating':0, 'same':['a'], 'caption':None}))
        self.assertEqual(result['different_fields'], ['caption', 'rating'])

    def test_source_order_does_not_choose_the_active_version(self):
        a, b = self.sidecar('a', {'caption':'A'}), self.sidecar('b', {'caption':'B'})
        first = self.resolve(self.embedded(), a, b, active='b')
        second = self.resolve(self.embedded(), b, a, active='b')
        self.assertEqual(first, second)

    def test_invalid_source_bindings_are_refused(self):
        original, sidecar = self.embedded(), self.sidecar()
        for active in ('missing', 'photo'):
            with self.assertRaises(ValueError):
                self.resolve(original, sidecar, active=active)
        with self.assertRaises(ValueError):
            self.resolve(original, sidecar, sidecar)
        with self.assertRaises(ValueError):
            self.resolve(original, MetadataSource('sidecar', 'xmp', {}, {}))
        with self.assertRaises(ValueError):
            self.resolve(self.sidecar(), active=None)

    def test_non_json_metadata_is_refused_without_lossy_conversion(self):
        for value in (float('nan'), float('inf'), b'bytes', ('tuple',), {1:'numeric key'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.resolve(self.embedded(), self.sidecar(fields={'value':value}))
