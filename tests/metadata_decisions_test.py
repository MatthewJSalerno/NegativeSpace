"""Generated metadata decisions: immutable choices, stale previews and safe holds."""
import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest import mock
from PIL import Image

import metadata_index_test
from engine import metadata_decisions, metadata_index, ns_db, transfer


class Decisions(unittest.TestCase):
    setUp = metadata_index_test.IndexTests.setUp
    run_engine = metadata_index_test.IndexTests.run_engine
    conn = metadata_index_test.IndexTests.conn
    latest = metadata_index_test.IndexTests.latest

    def index(self):
        self.run_engine()
        self.db = next((self.root/'base/db').glob('*.db'))
        self.c = self.conn()
        self.capture = self.c.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        self.file_id = self.c.execute('SELECT file_id FROM metadata_captures WHERE capture_id=?',(self.capture,)).fetchone()[0]

    def choose(self, kind='primary', selection=None, request_id='choice'):
        selection = selection or {'capture_id':self.capture,'primary_id':'sidecar:photo.jpg.xmp'}
        preview = metadata_decisions.preview(self.db,kind,selection)
        return metadata_decisions.confirm(self.db,kind=kind,selection=selection,token=preview['token'],request_id=request_id)

    def shared(self):
        self.sidecar.rename(self.root/'source/photo.xmp')
        Image.new('RGB',(40,30),(50,60,70)).save(self.root/'source/photo.png')
        self.index()
        self.capture,self.file_id = self.c.execute("SELECT capture_id,file_id FROM metadata_captures WHERE source_relative_path='photo.jpg'").fetchone()
        self.owners = dict(self.c.execute('SELECT source_relative_path,file_id FROM metadata_captures'))

    def test_primary_preview_presence_diff_and_no_filing_mutation(self):
        self.index()
        original = self.c.execute('SELECT metadata_json,dest_path,status FROM photos').fetchone()
        selection={'capture_id':self.capture,'primary_id':'exif'}
        preview=metadata_decisions.preview(self.db,'primary',selection)
        self.assertTrue(preview['filing_date_may_change'])
        self.assertEqual(preview['differences'][0]['after']['value'],'1999-01-02T03:04:05')
        saved=self.choose(selection=selection)
        self.assertEqual(saved['value']['resolution']['field_sources']['date_taken'],'exif')
        self.assertFalse(saved['value']['filing_applied'])
        self.assertEqual(self.c.execute('SELECT metadata_json,dest_path,status FROM photos').fetchone(),original)
        self.assertEqual(ns_db.unbacked_changes(self.c)[0],1)

    def test_blank_primary_is_not_filled_and_preview_does_not_save(self):
        self.sidecar.write_bytes(metadata_index_test.packet(''))
        self.index()
        preview=metadata_decisions.preview(self.db,'primary',{'capture_id':self.capture,'primary_id':'sidecar:photo.jpg.xmp'})
        self.assertEqual(preview['after']['resolution']['proposed_effective']['date_taken'],'')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM metadata_decisions').fetchone()[0],0)

    def test_request_replay_returns_original_even_after_a_later_choice(self):
        self.index()
        selection={'capture_id':self.capture,'primary_id':'sidecar:photo.jpg.xmp'}
        preview=metadata_decisions.preview(self.db,'primary',selection)
        args=dict(kind='primary',selection=selection,token=preview['token'],request_id='same')
        first=metadata_decisions.confirm(self.db,**args)
        second=self.choose(selection={'capture_id':self.capture,'primary_id':'exif'},request_id='second')
        self.assertEqual(metadata_decisions.confirm(self.db,**args),first)
        self.assertEqual(metadata_decisions.current(self.c,'primary',str(self.file_id))['revision'],second['revision'])
        with self.assertRaises(ns_db.RequestConflict):
            metadata_decisions.confirm(self.db,**dict(args,selection={'capture_id':self.capture,'primary_id':'exif'}))

    def test_stale_preview_cannot_overwrite_another_choice(self):
        self.index()
        selection={'capture_id':self.capture,'primary_id':'exif'}
        preview=metadata_decisions.preview(self.db,'primary',selection)
        self.choose()
        with self.assertRaises(ns_db.RevisionConflict):
            metadata_decisions.confirm(self.db,kind='primary',selection=selection,token=preview['token'],request_id='stale')
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM metadata_decisions WHERE kind='primary'").fetchone()[0],1)

    def test_reindex_keeps_primary_bound_to_original_version(self):
        self.index(); saved=self.choose()
        self.sidecar.write_bytes(metadata_index_test.packet('2015'))
        self.run_engine()
        current=metadata_decisions.current(self.c,'primary',str(self.file_id))
        self.assertEqual(current['value'],saved['value'])
        self.assertEqual(current['value']['resolution']['proposed_effective']['date_taken'],'2005-03-04T05:06:07')
        self.assertEqual(self.latest(self.c)[1]['resolution']['proposed_effective']['date_taken'],'2015')
        with self.assertRaises(ns_db.RevisionConflict):
            metadata_decisions.preview(self.db,'primary',{'capture_id':self.capture,'primary_id':'exif'})

    def test_changed_photo_identity_refuses_old_preview(self):
        self.index()
        with ns_db.transaction(self.c):
            self.c.execute("UPDATE photos SET sha1_hash=?",('a'*40,))
        with self.assertRaises(ns_db.RevisionConflict):
            self.choose()

    def test_shared_ownership_is_explicit_and_survives_default_changes(self):
        self.shared()
        with self.assertRaises(ValueError):
            self.choose(selection={'capture_id':self.capture,'primary_id':'sidecar:photo.xmp'})
        self.choose('association',{'capture_id':self.capture,'sidecar':'photo.xmp','owner_ids':[self.file_id]})
        ns_db.save_settings(self.c,{'xmp_association':'all'},expected_revisions={'xmp_association':0})
        self.run_engine()
        reports={p:json.loads(v) for p,v in self.c.execute('SELECT source_relative_path,report_json FROM metadata_captures ORDER BY capture_id')}
        self.assertEqual(reports['photo.jpg']['sidecars'][0]['candidates'],['photo.jpg'])
        self.assertEqual(reports['photo.jpg']['sidecars'][0]['all_candidates'],['photo.jpg','photo.png'])
        self.assertEqual(reports['photo.png']['resolution']['proposed_primary'],'exif')
        latest_id=self.c.execute("SELECT MAX(capture_id) FROM metadata_captures WHERE source_relative_path='photo.jpg'").fetchone()[0]
        self.choose('association',{'capture_id':latest_id,'sidecar':'photo.xmp','owner_ids':list(self.owners.values())},'both')
        self.run_engine()
        self.assertEqual(len(self.latest(self.c)[1]['sidecars'][0]['candidates']),2)

    def test_ownership_cannot_detach_an_existing_primary(self):
        self.shared()
        self.choose('association',{'capture_id':self.capture,'sidecar':'photo.xmp','owner_ids':[self.file_id]})
        self.choose(selection={'capture_id':self.capture,'primary_id':'sidecar:photo.xmp'},request_id='primary')
        with self.assertRaises(ValueError):
            self.choose('association',{'capture_id':self.capture,'sidecar':'photo.xmp','owner_ids':[self.owners['photo.png']]},'detach')

    def test_arbitrary_identity_and_invalid_sources_refused(self):
        self.index()
        for selection in (
            {'capture_id':self.capture,'sidecar':'../photo.jpg.xmp','owner_ids':[self.file_id]},
            {'capture_id':self.capture,'sidecar':'photo.jpg.xmp','owner_ids':[999999]},
            {'capture_id':self.capture,'sidecar':'photo.jpg.xmp','owner_ids':[True]},
            {'capture_id':self.capture,'sidecar':'photo.jpg.xmp','owner_ids':[]},
        ):
            with self.assertRaises(ValueError):
                metadata_decisions.preview(self.db,'association',selection)
        self.sidecar.write_bytes(metadata_index_test.packet()[:-10]); self.run_engine()
        capture=self.c.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        with self.assertRaises(ValueError):
            self.choose(selection={'capture_id':capture,'primary_id':'sidecar:photo.jpg.xmp'})
        # A deliberate valid embedded choice is still possible; transfer remains held.
        self.choose(selection={'capture_id':capture,'primary_id':'exif'})

    def test_settings_are_validated_and_frozen_for_running_job(self):
        self.shared()
        ns_db.save_settings(self.c,{'xmp_association':'all'},expected_revisions={'xmp_association':0})
        run=ns_db.create_run(self.c,mode='INDEX',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
        ns_db.save_settings(self.c,{'xmp_association':'ask'},expected_revisions={'xmp_association':1})
        config=json.loads(self.c.execute('SELECT effective_config_json FROM run_configs WHERE run_id=?',(run,)).fetchone()[0])
        self.assertEqual(config['xmp_association'],'all')
        self.assertEqual(config['metadata_write_raw'],'xmp')
        metadata_index.capture_index(self.db,run,self.root/'source',[str(self.photo)],worker_count=1,log_dir=str(self.root/'base'))
        self.assertEqual(self.latest(self.c)[1]['association_policy'],'all')
        self.assertEqual(self.latest(self.c)[1]['sidecars'][0]['state'],'associated')
        capture=self.c.execute('SELECT MAX(capture_id) FROM metadata_captures').fetchone()[0]
        with self.assertRaises(ns_db.RevisionConflict):
            self.choose(selection={'capture_id':capture,'primary_id':'exif'})
        for key,value in (('xmp_association','first'),('metadata_write_raw',True),('metadata_write_non_raw','auto')):
            with self.assertRaises(ValueError): ns_db.validate_settings({key:value})

    def test_decisions_are_immutable_and_backed_up(self):
        self.index(); self.choose()
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.execute('DELETE FROM metadata_decisions')
        self.c.rollback()
        ns_db.backup_catalog(self.db,self.root/'backups',self.root/'base',trigger='manual')
        self.assertEqual(ns_db.unbacked_changes(self.c)[0],0)
        self.assertEqual(self.c.execute('SELECT MAX(metadata_decision_highwater) FROM backup_attempts').fetchone()[0],2)

    def test_decision_during_backup_stays_unbacked_even_with_old_timestamp(self):
        self.index()
        actual=ns_db._compress_and_verify
        def during(raw,packed):
            with mock.patch.object(ns_db,'utc_now',return_value='2000-01-01T00:00:00+00:00'):
                self.choose()
            actual(raw,packed)
        with mock.patch.object(ns_db,'_compress_and_verify',side_effect=during):
            ns_db.backup_catalog(self.db,self.root/'backups',self.root/'base',trigger='manual')
        self.assertEqual(ns_db.unbacked_changes(self.c)[0],2)

    def test_copy_and_move_keep_pairs_and_duplicate_sources_but_copy_other_photos(self):
        # Ambiguous metadata stays held even on direct Copy without an earlier Index.
        self.sidecar.write_bytes(b'invalid XMP fixture')
        other=self.root/'source/other.jpg'; Image.new('RGB',(42,31),(70,80,90)).save(other)
        duplicate=self.root/'source/duplicate.jpg'; duplicate.write_bytes(self.photo.read_bytes())
        (self.root/'source/duplicate.jpg.xmp').write_bytes(b'invalid XMP fixture')
        before=self.photo.read_bytes()
        self.run_engine('--copy'); self.c=self.conn()
        statuses=dict(self.c.execute('SELECT source_path,status FROM photos'))
        self.assertEqual(statuses[str(other)],'Copied')
        self.assertIn(statuses[str(self.photo)],('Pending','Duplicate'))
        self.run_engine('--move')
        self.assertEqual(self.photo.read_bytes(),before)
        self.assertTrue(duplicate.exists())
        self.assertTrue(self.sidecar.exists())
        self.assertFalse(other.exists())
        reasons=[r[0] for r in self.c.execute("SELECT error_message FROM operations WHERE status='Skipped'")]
        self.assertTrue(any('Metadata choice or repair' in (reason or '') for reason in reasons))

    def test_sidecar_primary_freezes_shown_ownership_atomically(self):
        self.index()
        self.c.execute("CREATE TRIGGER refuse_primary BEFORE INSERT ON metadata_decisions WHEN NEW.kind='primary' "
                       "BEGIN SELECT RAISE(ABORT,'injected refusal'); END")
        self.c.commit()
        with self.assertRaises(sqlite3.IntegrityError): self.choose()
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM metadata_decisions').fetchone()[0],0)
        self.c.execute('DROP TRIGGER refuse_primary'); self.c.commit()
        self.choose()
        ownership=metadata_decisions.current(self.c,'association',metadata_decisions.association_scope(str(self.root/'source'),'photo.jpg.xmp'))
        self.assertEqual(ownership['value']['owners'],{'photo.jpg':self.file_id})

    def test_changed_other_candidate_invalidates_ownership_preview(self):
        self.shared()
        selection={'capture_id':self.capture,'sidecar':'photo.xmp','owner_ids':list(self.owners.values())}
        preview=metadata_decisions.preview(self.db,'association',selection)
        with ns_db.transaction(self.c):
            self.c.execute('UPDATE photos SET sha1_hash=? WHERE source_path=?',('b'*40,str(self.root/'source/photo.png')))
        with self.assertRaises(ns_db.RevisionConflict):
            metadata_decisions.confirm(self.db,kind='association',selection=selection,token=preview['token'],request_id='stale-owner')

    def test_held_pairs_do_not_inflate_space_estimate(self):
        self.sidecar.write_bytes(b'invalid XMP fixture')
        other=self.root/'source/other.jpg'; Image.new('RGB',(41,33),(20,90,100)).save(other)
        self.index()
        run=ns_db.create_run(self.c,mode='COPY',source=str(self.root/'source'),destination=str(self.root/'dest'))[0]
        args=SimpleNamespace(move=False,copy=True,source=str(self.root/'source'),source_subdir=None,file_ids=None)
        with mock.patch.object(transfer,'verify_sufficient_disk_space',return_value=(False,0,1)) as estimate:
            self.assertEqual(transfer._run_move_or_copy(args,self.db,self.root/'dest',run),'Failed')
        self.assertEqual(estimate.call_args.args[1],other.stat().st_size)
        self.assertTrue(self.photo.exists())

    def test_photo_not_chosen_as_sidecar_owner_can_proceed(self):
        self.shared()
        self.choose('association',{'capture_id':self.capture,'sidecar':'photo.xmp','owner_ids':[self.file_id]})
        self.run_engine('--copy')
        statuses=dict(self.c.execute('SELECT source_path,status FROM photos'))
        self.assertEqual(statuses[str(self.root/'source/photo.png')],'Copied')
        self.assertEqual(statuses[str(self.photo)],'Copied')
        self.assertTrue((self.root/'source/photo.xmp').is_file())

    def test_preview_token_cannot_be_used_for_a_different_primary(self):
        self.index()
        preview=metadata_decisions.preview(self.db,'primary',{'capture_id':self.capture,'primary_id':'exif'})
        with self.assertRaises(ns_db.RevisionConflict):
            metadata_decisions.confirm(self.db,kind='primary',selection={'capture_id':self.capture,'primary_id':'sidecar:photo.jpg.xmp'},
                token=preview['token'],request_id='swapped')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM metadata_decisions').fetchone()[0],0)
