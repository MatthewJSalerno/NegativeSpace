"""Generated earlier-state reproduction through the real metadata writers."""
import json
import subprocess
from pathlib import Path
import unittest
from unittest import mock

import metadata_save_test
import metadata_photo_save_test
from engine import metadata_edits, metadata_reproduce, metadata_save, metadata_writer, ns_db, xmp


class Reproduction(unittest.TestCase):
    setUp = metadata_save_test.SavedEdits.setUp
    run_engine = metadata_save_test.SavedEdits.run_engine
    conn = metadata_save_test.SavedEdits.conn
    setup_catalog = metadata_save_test.SavedEdits.setup_catalog
    preview = metadata_save_test.SavedEdits.preview
    prepare = metadata_save_test.SavedEdits.prepare
    command = metadata_save_test.SavedEdits.command

    def reproduce(self, selection=None):
        return metadata_reproduce.preview(self.db, photo_id=self.pid, capture_id=self.capture,
            reproduce=selection or {'capture_id':self.capture}, destination_root=self.root/'dest')

    def save(self, changes=None, preview=None):
        op = self.prepare(changes or {}, preview=preview)
        result = metadata_save.execute(self.c, op)
        self.assertEqual(result['outcome'], 'completed', result)
        return op

    def test_source_state_removes_later_fields_without_touching_image_or_history(self):
        self.setup_catalog()
        earlier = self.save({'title':'Later title','keywords':['later'],'orientation':6})
        plan = self.reproduce()
        self.assertEqual(plan['remove_fields'], ['keywords','orientation','title'])
        self.assertFalse(plan['reproduction']['fields']['title']['present'])
        self.assertFalse(plan['reproduction']['exact_photo_bytes'])
        self.assertEqual(plan['primary_after'], plan['primary_before'])
        op = self.save(preview=plan)
        self.assertNotEqual(op, earlier)
        saved = metadata_save.active(self.c, self.pid)
        self.assertNotIn('title', saved['resolution']['proposed_effective'])
        self.assertNotIn('orientation', saved['resolution']['proposed_effective'])
        self.assertEqual(saved['reproduction'], plan['reproduction'])
        self.assertEqual(self.dest.read_bytes(), self.photo_bytes)
        self.assertEqual(self.photo.read_bytes(), self.photo_bytes)
        self.assertEqual(metadata_save._event(self.c, earlier, 'metadata_saved')['sources'][plan['primary_before']]['fields']['title'], {'x-default':'Later title'})
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM operation_events WHERE step='metadata_saved'").fetchone()[0], 2)

    def test_pre_edit_empty_date_is_preserved_and_refiles_undated(self):
        self.setup_catalog()
        self.save({'date_taken':'','title':'Earlier'})
        earlier = self.save({'date_taken':'2013-04-05T00:00:00+14:00','title':'Later'})
        plan = self.reproduce({'before_operation_id':earlier})
        self.assertTrue(plan['reproduction']['fields']['date_taken']['present'])
        self.assertEqual(plan['changes']['date_taken'], '')
        self.assertTrue(plan['filing']['proposed'].startswith('library/Undated/'))
        self.save(preview=plan)
        saved = metadata_save.active(self.c, self.pid)
        self.assertEqual(saved['resolution']['proposed_effective']['date_taken'], '')
        self.assertEqual(saved['resolution']['proposed_effective']['title'], {'x-default':'Earlier'})

    def test_pre_edit_state_before_first_xmp_keeps_new_primary_deliberate(self):
        self.setup_catalog(sidecar=False)
        earlier = self.save({'title':'Added in first sidecar'})
        plan = self.reproduce({'before_operation_id':earlier})
        self.assertTrue(plan['primary_after'].startswith('sidecar:'))
        self.assertEqual(plan['changes']['date_taken'], '2004-02-03T04:05:06')
        self.save(preview=plan)
        self.assertNotIn('title', metadata_save.active(self.c,self.pid)['resolution']['proposed_effective'])

    def test_reproduction_works_after_source_removed(self):
        self.setup_catalog()
        self.save({'title':'Added'})
        self.photo.unlink(); self.sidecar.unlink()
        self.save(preview=self.reproduce())
        self.assertEqual(self.dest.read_bytes(), self.photo_bytes)
        self.assertNotIn('title', metadata_save.active(self.c,self.pid)['resolution']['proposed_effective'])

    def test_current_photo_missing_refuses_before_publication(self):
        self.setup_catalog()
        self.save({'title':'Added'})
        plan = self.reproduce()
        self.dest.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.prepare({}, preview=plan)
        self.assertIn(b'Added', self.xdest.read_bytes())

    def test_capture_and_operation_must_belong_to_photo(self):
        self.setup_catalog()
        for selection in ({'capture_id':999999}, {'before_operation_id':999999}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.reproduce(selection)
        with mock.patch.object(metadata_save, '_manifest', return_value=(self.pid+1,1,'Completed',{})):
            with self.assertRaisesRegex(ValueError, 'belong'):
                self.reproduce({'before_operation_id':1})

    def test_unfinished_and_discarded_operations_are_not_saved_versions(self):
        self.setup_catalog()
        op = self.prepare({'title':'Not saved'})
        with self.assertRaisesRegex(ValueError, 'completed'):
            self.reproduce({'before_operation_id':op})
        metadata_save.abandon(self.c, op)
        with self.assertRaisesRegex(ValueError, 'completed'):
            self.reproduce({'before_operation_id':op})

    def test_stale_preview_cannot_replace_a_newer_edit(self):
        self.setup_catalog()
        self.save({'title':'First'})
        plan = self.reproduce()
        self.save({'title':'Second'})
        with self.assertRaises(ns_db.RevisionConflict):
            self.prepare({}, preview=plan)
        self.assertIn(b'Second', self.xdest.read_bytes())

    def test_retry_does_not_repeat_saved_reproduction(self):
        self.setup_catalog()
        self.save({'title':'Added'})
        plan = self.reproduce()
        op = self.prepare({}, preview=plan)
        with mock.patch.object(metadata_save, '_refile', side_effect=OSError('fixture interruption')):
            result = metadata_save.execute(self.c,op)
        self.assertEqual(result['outcome'], 'failed')
        self.assertTrue(result['metadata_saved'])
        before = self.xdest.read_bytes()
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'], 'completed')
        self.assertEqual(self.xdest.read_bytes(), before)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM operation_events WHERE operation_id=? AND step='metadata_saved'", (op,)).fetchone()[0],1)
        self.assertEqual(metadata_save.active(self.c,self.pid)['reproduction'], plan['reproduction'])

    def test_noop_keeps_original_bytes_and_records_intent(self):
        self.setup_catalog()
        plan = self.reproduce()
        op = self.prepare({}, preview=plan)
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'], 'no_change')
        self.assertEqual(self.xdest.read_bytes(), self.original)
        self.assertEqual(metadata_save._manifest(self.c,op)[3]['preview']['reproduction'], plan['reproduction'])

    def test_completed_noop_has_a_valid_pre_edit_state(self):
        self.setup_catalog()
        op = self.prepare({'date_taken':'2005-03-04T05:06:07'})
        self.assertEqual(metadata_save.execute(self.c,op)['outcome'],'no_change')
        self.save({'title':'Later'})
        plan = self.reproduce({'before_operation_id':op})
        self.assertIn('title',plan['remove_fields'])
        self.save(preview=plan)
        self.assertNotIn('title',metadata_save.active(self.c,self.pid)['resolution']['proposed_effective'])

    def test_cli_reproduction_is_previewed_confirmed_and_replay_safe(self):
        self.setup_catalog()
        self.save({'title':'Later'})
        # Fixture-created jobs do not run the jobs wrapper's completion step.
        self.c.execute("UPDATE runs SET status='Completed'"); self.c.commit()
        request = {'edits':[{'photo_id':self.pid,'capture_id':self.capture,'reproduce':{'capture_id':self.capture}}]}
        result = self.command('preview',request)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        request['edits'][0]['token'] = json.loads(result.stdout)['previews'][0]['token']
        result = self.command('apply',request,'reproduce-state')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertNotIn('title', metadata_save.active(self.c,self.pid)['resolution']['proposed_effective'])
        from engine.constants import EXIT_REQUEST_ALREADY_ACCEPTED
        self.assertEqual(self.command('apply',request,'reproduce-state').returncode,EXIT_REQUEST_ALREADY_ACCEPTED)

    def test_verified_embedded_history_connects_old_observation_to_current_image(self):
        metadata_photo_save_test.PhotoSaves.setup_catalog(self, primary='exif')
        first = self.save({'date_taken':'2011-02-03T04:05:06'})
        second = self.save({'date_taken':'2012-02-03T04:05:06'})
        # Source read priority included embedded XMP. Reproduce the explicit EXIF
        # primary's pre-edit state instead, as an independent deliberate choice.
        plan = self.reproduce({'before_operation_id':first})
        self.assertEqual(plan['reproduction']['verified_image_operations'], [first,second])
        self.assertEqual(plan['changes']['date_taken'], '1999-01-02T03:04:05')
        self.save(preview=plan)
        self.assertEqual(self.photo.read_bytes(),self.original)
        self.assertEqual(metadata_save.active(self.c,self.pid)['resolution']['proposed_effective']['date_taken'], '1999-01-02T03:04:05')

    def test_embedded_xmp_reproduction_removes_later_title(self):
        metadata_photo_save_test.PhotoSaves.setup_catalog(self, primary='embedded_xmp')
        first = self.save({'title':'Later'})
        plan = self.reproduce({'before_operation_id':first})
        self.assertEqual(plan['remove_fields'], ['title'])
        self.save(preview=plan)
        self.assertNotIn('title',metadata_save.active(self.c,self.pid)['resolution']['proposed_effective'])
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_exif_reproduction_removes_later_title(self):
        metadata_photo_save_test.PhotoSaves.setup_catalog(self, primary='exif')
        first = self.save({'title':'Later'})
        plan = self.reproduce({'before_operation_id':first})
        self.assertEqual(plan['remove_fields'], ['title'])
        self.save(preview=plan)
        self.assertNotIn('title',metadata_save.active(self.c,self.pid)['resolution']['proposed_effective'])
        self.assertEqual(self.photo.read_bytes(),self.original)

    def test_missing_image_history_never_uses_photo_identity_alone(self):
        self.setup_catalog()
        with self.assertRaisesRegex(ValueError, 'unchanged-image'):
            metadata_reproduce._image_chain(self.c,self.pid,'0'*40,'1'*40)

    def test_reproduction_requires_image_proof_before_accepting_historical_values(self):
        self.setup_catalog()
        original = metadata_reproduce._historical
        def unrelated(*args):
            _, resolution, origin = original(*args)
            return '0'*40, resolution, origin
        with mock.patch.object(metadata_reproduce,'_historical',side_effect=unrelated):
            with self.assertRaisesRegex(ValueError,'unchanged-image'):
                self.reproduce()
        self.assertEqual(self.dest.read_bytes(),self.photo_bytes)
        self.assertEqual(self.xdest.read_bytes(),self.original)

    def test_selector_rejects_paths_foreign_shapes_and_boolean_ids(self):
        for selection in ({}, {'capture_id':True}, {'capture_id':0}, {'path':'photo'},
                          {'capture_id':1,'before_operation_id':2}, {'before_operation_id':'1'}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                metadata_reproduce.validate_selection(selection)


    def test_absent_historical_date_removes_tag_and_updates_filing(self):
        subprocess.run(['exiftool','-overwrite_original','-EXIF:DateTimeOriginal=',
                        '-XMP-exif:DateTimeOriginal=',str(self.photo)],check=True,capture_output=True)
        self.sidecar.write_bytes(metadata_edits.first_sidecar({'title':'Original title'}))
        self.setup_catalog()
        self.save({'date_taken':'2012-02-03T04:05:06'})
        plan = self.reproduce()
        self.assertEqual(plan['remove_fields'], ['date_taken'])
        self.assertFalse(plan['reproduction']['fields']['date_taken']['present'])
        self.assertTrue(plan['filing']['proposed'].startswith('library/Undated/'))
        self.save(preview=plan)
        saved = metadata_save.active(self.c,self.pid)
        self.assertNotIn('date_taken',saved['resolution']['proposed_effective'])
        from engine import constants
        self.assertEqual(saved['metadata']['date_source'],constants.DATE_SOURCE_MTIME)
        path = Path(self.c.execute('SELECT dest_path FROM photos WHERE id=?',(self.pid,)).fetchone()[0])
        self.assertNotIn('date_taken',xmp.parse_bytes(Path(str(path)+'.xmp').read_bytes(),source_id='check').source.fields)

    def test_fallback_cannot_silently_refill_historical_absence(self):
        self.setup_catalog()
        state = metadata_edits._catalog_state(self.db,photo_id=self.pid,capture_id=self.capture,
                                             destination_root=self.root/'dest')
        state[0]['exif']['fields']['title'] = 'A value absent from historical state'
        with mock.patch.object(metadata_edits,'_catalog_state',return_value=state):
            with self.assertRaisesRegex(ValueError,'fallback'):
                self.reproduce()
        self.assertEqual(self.xdest.read_bytes(),self.original)

    def test_preview_provenance_is_bound_not_caller_editable(self):
        self.setup_catalog()
        self.save({'title':'Added'})
        plan = self.reproduce()
        plan['reproduction']['historical_photo_sha1'] = '0'*40
        with self.assertRaises(ns_db.RevisionConflict):
            self.prepare({},preview=plan)
        self.assertIn(b'Added',self.xdest.read_bytes())


class Removals(unittest.TestCase):
    def test_removal_only_preserves_unknown_properties_and_absence(self):
        original = metadata_edits.first_sidecar({'title':'Later','orientation':6})
        original = original.replace(b'</rdf:Description>',b'<u:Note xmlns:u="urn:fixture">keep</u:Note></rdf:Description>')
        result = metadata_writer.sidecar_bytes(original,{},remove_fields=['title','orientation'])
        self.assertEqual(xmp.parse_bytes(result,source_id='test').source.fields,{})
        self.assertIn(b'keep',result)

    def test_missing_removal_is_byte_exact_noop(self):
        original = metadata_edits.first_sidecar({'title':'Keep'})
        self.assertEqual(metadata_writer.sidecar_bytes(original,{},remove_fields=['orientation']),original)

    def test_conflicting_or_unknown_removals_refuse(self):
        original = metadata_edits.first_sidecar({'title':'Keep'})
        for removes in (['title'], ['title','title'], ['not_a_field'], 'title'):
            with self.subTest(removes=removes), self.assertRaises(ValueError):
                metadata_writer.sidecar_bytes(original,{'title':'Later'},remove_fields=removes)

    def test_gps_removal_drops_the_whole_linked_group(self):
        original = metadata_edits.first_sidecar({'title':'Keep',
            'gps':{'latitude':'12,30N','longitude':'45,15W','altitude':'125/2','altitude_ref':'1'}})
        result = metadata_writer.sidecar_bytes(original,{},remove_fields=['gps'])
        parsed = xmp.parse_bytes(result,source_id='check')
        self.assertEqual(parsed.source.fields,{'title':{'x-default':'Keep'}})
        self.assertFalse(set(parsed.tags['properties']) & set(xmp.GPS_TAGS))
