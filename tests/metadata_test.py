"""Shared JSON validation used by metadata readers and edit planning."""
import unittest

from engine import metadata


class MetadataTests(unittest.TestCase):
    def test_json_values_are_preserved_and_detached(self):
        original = {'blank':'', 'missing':None, 'zero':0, 'flag':False,
                    'keywords':['one', 'two'], 'localized':{'fr':'Texte'}}
        result = metadata._json_copy(original)
        self.assertEqual(result, original)
        result['keywords'].append('new')
        result['localized']['fr'] = 'changed'
        self.assertEqual(original['keywords'], ['one', 'two'])
        self.assertEqual(original['localized']['fr'], 'Texte')

    def test_non_json_metadata_is_refused_without_lossy_conversion(self):
        for value in (float('nan'), float('inf'), b'bytes', ('tuple',), {1:'numeric key'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                metadata._json_copy({'value':value})
