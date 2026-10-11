"""Base + explicit override composition through generated catalogs and verified saves."""
import json
import unittest
from unittest import mock

import metadata_save_test
import metadata_photo_save_test
from engine import metadata_command, metadata_edits, metadata_save, ns_db, xmp_store


class Composition(unittest.TestCase):
    setUp = metadata_save_test.SavedEdits.setUp
    run_engine = metadata_save_test.SavedEdits.run_engine
    conn = metadata_save_test.SavedEdits.conn
    setup_catalog = metadata_save_test.SavedEdits.setup_catalog
    preview = metadata_save_test.SavedEdits.preview
    prepare = metadata_save_test.SavedEdits.prepare
    command = metadata_save_test.SavedEdits.command
    retain_alternative = metadata_save_test.SavedEdits.retain_alternative

    def captured(self, source='exif'):
        return {'photo_id':self.pid, 'capture_id':self.capture, 'source_id':source}

    def compose(self, base=None, changes=None, copy_fields=None):
        return metadata_edits.preview_copy(self.db, photo_id=self.pid, capture_id=self.capture,
            base=base or self.captured(), changes=changes or {}, copy_fields=copy_fields or {},
            destination_root=self.root/'dest')

    def test_base_override_and_typed_fields_save_complete_provenance(self):
        self.setup_catalog()
        version, original = self.retain_alternative('2010-02-03T04:05:06+02:00')
        base = {'photo_id':self.pid, 'version_id':version}
        plan = self.compose(base, {'title':'Chosen title'}, {'date_taken':self.captured()})
        fields = plan['composition']['fields']
        self.assertEqual(fields['title']['origin'], 'typed')
        self.assertEqual(fields['date_taken']['origin'], 'override')
        self.assertEqual(fields['rating']['origin'], 'unchanged')
        self.assertEqual(plan['primary_before'], plan['primary_after'])
        self.assertEqual(plan['changes']['date_taken'], '1999-01-02T03:04:05')
        op = self.prepare({}, preview=plan)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        saved = metadata_save.active(self.c, self.pid)
        self.assertEqual(saved['composition'], plan['composition'])
        self.assertEqual(saved['resolution']['proposed_effective']['title'], {'x-default':'Chosen title'})
        self.assertEqual(xmp_store.original_bytes(self.c, version), original)
        self.assertEqual(self.photo.read_bytes(), self.photo_bytes)

    def test_base_alone_keeps_offset_and_refiles_by_recorded_day(self):
        self.setup_catalog()
        version, _ = self.retain_alternative('2010-02-03T00:05:06+14:00')
        plan = self.compose({'photo_id':self.pid, 'version_id':version})
        self.assertEqual(plan['composition']['fields']['date_taken']['origin'], 'base')
        self.assertEqual(plan['filing']['proposed'], 'library/2010/02/03/photo.jpg')
        op = self.prepare({}, preview=plan)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        self.assertEqual(metadata_save.active(self.c, self.pid)['resolution']['proposed_effective']['date_taken'],
                         '2010-02-03T00:05:06+14:00')

    def test_missing_base_fields_stay_unchanged_and_are_identified(self):
        self.setup_catalog()
        op = self.prepare({'title':'Already present', 'keywords':['keep']})
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        plan = self.compose()
        self.assertIn('title', plan['composition']['base_absent_fields'])
        self.assertNotIn('title', plan['changes'])
        self.assertEqual(plan['composition']['fields']['title']['value'], {'x-default':'Already present'})
        self.assertEqual(plan['composition']['fields']['title']['origin'], 'unchanged')

    def test_explicit_empty_base_date_suppresses_fallback_and_files_undated(self):
        self.setup_catalog()
        version, _ = self.retain_alternative('')
        plan = self.compose({'photo_id':self.pid, 'version_id':version})
        self.assertEqual(plan['after']['proposed_effective']['date_taken'], '')
        self.assertTrue(plan['filing']['proposed'].startswith('library/Undated/'))
        op = self.prepare({}, preview=plan)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        self.assertEqual(metadata_save.active(self.c, self.pid)['resolution']['proposed_effective']['date_taken'], '')

    def test_typed_clear_overrides_base_date(self):
        self.setup_catalog()
        plan = self.compose(changes={'date_taken':''})
        self.assertEqual(plan['composition']['fields']['date_taken']['origin'], 'typed')
        self.assertIsNone(plan['composition']['fields']['date_taken']['donor'])
        self.assertEqual(plan['after']['proposed_effective']['date_taken'], '')

    def test_missing_explicit_override_refuses_without_fallback(self):
        self.setup_catalog()
        with self.assertRaisesRegex(ValueError, 'absent'):
            self.compose(copy_fields={'title':self.captured()})
        self.assertEqual(self.xdest.read_bytes(), self.original)

    def test_ambiguous_typed_and_donor_override_refuses(self):
        self.setup_catalog()
        with self.assertRaisesRegex(ValueError, 'both'):
            self.compose(changes={'date_taken':''}, copy_fields={'date_taken':self.captured()})

    def test_unknown_base_version_and_invalid_selector_refuse(self):
        self.setup_catalog()
        for base in ({'photo_id':self.pid,'version_id':999999},
                     {'photo_id':self.pid,'capture_id':self.capture,'source_id':'missing'},
                     {'photo_id':True,'version_id':1}, {'photo_id':self.pid,'path':'anything'}):
            with self.subTest(base=base), self.assertRaises(ValueError):
                self.compose(base)

    def test_noop_composition_keeps_exact_bytes_and_version_count(self):
        self.setup_catalog()
        version = self.c.execute('SELECT version_id FROM xmp_versions').fetchone()[0]
        plan = self.compose({'photo_id':self.pid,'version_id':version})
        before = self.c.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0]
        op = self.prepare({}, preview=plan)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'no_change')
        self.assertEqual(self.xdest.read_bytes(), self.original)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0], before)

    def test_tampered_provenance_cannot_be_prepared(self):
        self.setup_catalog()
        plan = self.compose(changes={'title':'Chosen'})
        plan['composition']['fields']['title']['origin'] = 'base'
        with self.assertRaises(ns_db.RevisionConflict):
            self.prepare({}, preview=plan)
        self.assertEqual(self.xdest.read_bytes(), self.original)

    def test_base_bytes_reverify_before_preparation(self):
        self.setup_catalog()
        version, _ = self.retain_alternative('2010-02-03T04:05:06')
        plan = self.compose({'photo_id':self.pid,'version_id':version})
        with mock.patch.object(xmp_store, 'original_bytes', side_effect=ValueError('corrupt archive')):
            with self.assertRaisesRegex(ValueError, 'corrupt archive'):
                self.prepare({}, preview=plan)
        self.assertEqual(self.xdest.read_bytes(), self.original)

    def test_cli_composition_preview_apply_and_replay(self):
        self.setup_catalog()
        request = {'edits':[{'photo_id':self.pid,'capture_id':self.capture,'base':self.captured(),
                            'changes':{'title':'CLI composition'},'copy_fields':{}}]}
        result = self.command('preview', request)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        request['edits'][0]['token'] = json.loads(result.stdout)['previews'][0]['token']
        result = self.command('apply', request, 'compose-fields')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        saved = metadata_save.active(self.c, self.pid)
        self.assertEqual(saved['composition']['base'], self.captured())
        self.assertEqual(saved['resolution']['proposed_effective']['title'], {'x-default':'CLI composition'})
        result = self.command('apply', request, 'compose-fields')
        from engine.constants import EXIT_REQUEST_ALREADY_ACCEPTED
        self.assertEqual(result.returncode, EXIT_REQUEST_ALREADY_ACCEPTED, result.stdout+result.stderr)

    def test_null_base_is_not_a_composition_request(self):
        request = {'edits':[{'photo_id':1,'capture_id':1,'base':None,'changes':{},'copy_fields':{}}]}
        with self.assertRaises(ValueError):
            metadata_command.validate(request, 'preview')

    def test_logical_fields_and_unknown_target_properties_are_preserved(self):
        gps = {'latitude':'12,30N','longitude':'45,15W','altitude':'125/2','altitude_ref':'1'}
        original_fields = {'date_taken':'2005-03-04T05:06:07','title':{'en':'Hello','fr':'Bonjour'},
                           'keywords':['one','two'],'gps':gps,'rating':'3.5','creators':['A','B']}
        packet = metadata_edits.first_sidecar(original_fields)
        packet = packet.replace(b'</rdf:Description>', b'<keep:Value xmlns:keep="urn:fixture">untouched</keep:Value></rdf:Description>')
        self.sidecar.write_bytes(packet)
        self.setup_catalog()
        version = self.c.execute('SELECT version_id FROM xmp_versions').fetchone()[0]
        plan = self.compose({'photo_id':self.pid,'version_id':version}, copy_fields={'date_taken':self.captured()})
        self.assertEqual(plan['changes']['gps'], gps)
        self.assertEqual(plan['changes']['title'], original_fields['title'])
        self.assertEqual(plan['composition']['fields']['gps']['origin'], 'base')
        op = self.prepare({}, preview=plan)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        saved = metadata_save.active(self.c, self.pid)
        self.assertEqual(saved['sources'][saved['primary_id']]['fields']['gps'], gps)
        destination = self.root/'dest/library/1999/01/02/photo.jpg.xmp'
        self.assertIn(b'untouched', destination.read_bytes())
        self.assertEqual(xmp_store.original_bytes(self.c, version), packet)

    def test_composition_writes_established_embedded_primary(self):
        metadata_photo_save_test.PhotoSaves.setup_catalog(self, primary='exif')
        plan = self.compose(self.captured('embedded_xmp'), {'title':'Embedded result'})
        self.assertEqual(plan['primary_after'], 'exif')
        self.assertEqual(plan['changes']['date_taken'], '2004-02-03T04:05:06')
        op = self.prepare({}, preview=plan)
        self.assertEqual(metadata_save.execute(self.c, op)['outcome'], 'completed')
        saved = metadata_save.active(self.c, self.pid)
        self.assertEqual(saved['primary_id'], 'exif')
        self.assertEqual(saved['composition'], plan['composition'])
        self.assertEqual(self.photo.read_bytes(), self.original)
        self.assertEqual(saved['resolution']['proposed_effective']['title'], {'x-default':'Embedded result'})
