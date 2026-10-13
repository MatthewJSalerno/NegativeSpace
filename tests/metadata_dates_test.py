"""Date-only HTTP boundary with generated photos and the actual engine save path."""
import time
import subprocess
import unittest
from fastapi.testclient import TestClient
from engine import ns_db, xmp
from webui import app as webapp
from webui.config import Config
import metadata_save_test


class DateEditorTests(unittest.TestCase):
    setUp = metadata_save_test.SavedEdits.setUp
    run_engine = metadata_save_test.SavedEdits.run_engine
    conn = metadata_save_test.SavedEdits.conn
    setup_catalog = metadata_save_test.SavedEdits.setup_catalog

    def client(self, sidecar=True):
        self.setup_catalog(sidecar=sidecar)
        cfg=Config(base=self.root/'base',source=self.root/'source',dest=self.root/'dest',
                   cache=self.root/'cache',backups=self.root/'backups',allowed_hosts=('testserver',))
        client=TestClient(webapp.create_app(cfg));client.__enter__()
        self.addCleanup(client.__exit__,None,None,None)
        return client

    def plan(self,c,value=None,donor=None):
        body={'capture_id':self.capture, **({'donor_id':donor} if donor else {'value':value})}
        return c.post(f'/api/v1/photos/{self.pid}/date-preview',json=body)

    def save(self,c,p,request='date-test'):
        body={'edit':p['edit'],'token':p['token'],'request_id':request}
        result=c.post(f'/api/v1/photos/{self.pid}/date-save',json=body)
        self.assertEqual(result.status_code,202,result.text)
        run=result.json()
        for _ in range(300):
            run=c.get(f"/api/v1/runs/{run['id']}").json()
            if run['status'] not in ('Preparing','Running','Cancelling'):break
            time.sleep(.05)
        else:self.fail('Metadata job did not finish')
        return run,body

    def test_preview_save_refile_replay_and_unchanged_source(self):
        c=self.client();original=self.photo.read_bytes();sidecar=self.sidecar.read_bytes()
        ctx=c.get(f'/api/v1/photos/{self.pid}/date-edit').json()
        self.assertEqual(ctx['date']['value'],'2005-03-04T05:06:07')
        p=self.plan(c,'2012-06-07T00:30:00.123+14:00')
        self.assertEqual(p.status_code,200,p.text)
        p=p.json();self.assertTrue(p['filing']['change'])
        self.assertEqual(self.xdest.read_bytes(),sidecar)
        run,body=self.save(c,p)
        self.assertEqual(run['status'],'Completed',run)
        self.assertEqual((run['outcome']['verdict'],run['outcome']['succeeded'],run['outcome']['total']),('success',1,1))
        new=self.root/'dest'/p['filing']['proposed']
        self.assertEqual(new.read_bytes(),self.photo_bytes)
        self.assertEqual(self.photo.read_bytes(),original)
        self.assertEqual(self.sidecar.read_bytes(),sidecar)
        after=c.get(f'/api/v1/photos/{self.pid}/date-edit')
        self.assertEqual(after.status_code,200,after.text)
        self.assertEqual(after.json()['date']['value'],'2012-06-07T00:30:00.123+14:00')
        parsed=xmp.parse_bytes(new.with_name(new.name+'.xmp').read_bytes(),source_id='check')
        self.assertEqual(parsed.source.fields['date_taken'],'2012-06-07T00:30:00.123+14:00')
        replay=c.post(f'/api/v1/photos/{self.pid}/date-save',json=body)
        self.assertEqual(replay.status_code,202,replay.text)
        self.assertEqual(replay.json()['id'],run['id'])
        body['edit']['changes']['date_taken']='2013-01-01T00:00:00'
        self.assertEqual(c.post(f'/api/v1/photos/{self.pid}/date-save',json=body).status_code,409)

    def test_copy_captured_exif_date_keeps_primary_and_records_donor(self):
        c=self.client();p=self.plan(c,donor='exif')
        self.assertEqual(p.status_code,200,p.text)
        p=p.json();self.assertEqual(p['after'],'1999-01-02T03:04:05')
        self.assertEqual(p['target']['kind'],'sidecar_xmp')
        self.assertIn('copy_fields',p['edit'])
        run,_=self.save(c,p)
        self.assertEqual(run['status'],'Completed',run)
        self.assertEqual((run['outcome']['verdict'],run['outcome']['succeeded'],run['outcome']['total']),('success',1,1))

    def test_copy_preview_numbers_occupied_photo_and_preserves_both_pairs(self):
        c=self.client()
        first=self.plan(c,donor='exif').json()
        occupied=self.root/'dest'/first['filing']['proposed']
        occupied.parent.mkdir(parents=True,exist_ok=True)
        occupied.write_bytes(b'other photo')
        other_xmp=occupied.with_name(occupied.name+'.xmp')
        other_xmp.write_bytes(b'other sidecar')
        p=self.plan(c,donor='exif')
        self.assertEqual(p.status_code,200,p.text)
        p=p.json()
        self.assertTrue(p['filing']['collision_renamed'])
        self.assertEqual(p['filing']['proposed'],str(occupied.relative_to(self.root/'dest').with_name('photo_1.jpg')))
        run,_=self.save(c,p)
        self.assertEqual((run['status'],run['outcome']['succeeded'],run['outcome']['total']),('Completed',1,1))
        target=self.root/'dest'/p['filing']['proposed']
        self.assertEqual(target.read_bytes(),self.photo_bytes)
        parsed=xmp.parse_bytes(target.with_name(target.name+'.xmp').read_bytes(),source_id='check')
        self.assertEqual(parsed.source.fields['date_taken'],'1999-01-02T03:04:05')
        self.assertEqual(occupied.read_bytes(),b'other photo')
        self.assertEqual(other_xmp.read_bytes(),b'other sidecar')
        self.assertEqual(self.photo.read_bytes(),self.photo_bytes)
        self.assertEqual(self.sidecar.read_bytes(),self.original)

    def test_confirmed_target_becoming_occupied_requires_new_preview(self):
        c=self.client();p=self.plan(c,donor='exif').json()
        occupied=self.root/'dest'/p['filing']['proposed']
        occupied.parent.mkdir(parents=True,exist_ok=True);occupied.write_bytes(b'raced photo')
        run,_=self.save(c,p)
        self.assertEqual((run['status'],run['outcome']['failed'],run['outcome']['total']),('Failed',1,1))
        self.assertEqual(occupied.read_bytes(),b'raced photo')
        self.assertEqual(self.xdest.read_bytes(),self.original)
        self.assertFalse(occupied.with_name('photo_1.jpg').exists())

    def test_preview_refuses_orphan_sidecar_and_symlink(self):
        c=self.client();p=self.plan(c,donor='exif').json()
        wanted=self.root/'dest'/p['filing']['proposed']
        wanted.parent.mkdir(parents=True,exist_ok=True)
        orphan=wanted.with_name(wanted.name+'.xmp');orphan.write_bytes(b'unknown owner')
        refused=self.plan(c,donor='exif')
        self.assertEqual(refused.status_code,400,refused.text)
        self.assertIn('without its photo',refused.text)
        self.assertEqual(orphan.read_bytes(),b'unknown owner')
        orphan.unlink();wanted.symlink_to(self.photo)
        self.assertEqual(self.plan(c,donor='exif').status_code,400)
        self.assertEqual(self.xdest.read_bytes(),self.original)

    def test_unchanged_save_reports_one_skip_not_one_edit(self):
        c=self.client();p=self.plan(c,'2005-03-04T05:06:07').json()
        run,_=self.save(c,p)
        self.assertEqual((run['outcome']['verdict'],run['outcome']['succeeded'],run['outcome']['skipped'],run['outcome']['total']),('no_change',0,1,1))

    def test_clear_and_no_change(self):
        c=self.client();same=self.plan(c,'2005-03-04T05:06:07').json()
        self.assertTrue(same['no_change'])
        p=self.plan(c,'').json();self.assertIn('Undated',p['filing']['proposed'])
        run,_=self.save(c,p);self.assertEqual(run['status'],'Completed',run)

    def test_stale_preview_and_invalid_fields_never_write(self):
        c=self.client();p=self.plan(c,'2012-01-02T03:04:05').json()
        with ns_db.connect(self.db) as conn:
            ns_db.save_settings(conn,{'metadata_write_non_raw':'xmp'},expected_revisions={'metadata_write_non_raw':0})
        run,_=self.save(c,p);self.assertEqual(run['status'],'Failed',run)
        self.assertEqual((run['outcome']['failed'],run['outcome']['total']),(1,1))
        self.assertEqual(self.xdest.read_bytes(),self.original)
        self.assertEqual(self.plan(c,'2020-02-31T10:00:00').status_code,400)
        p['edit']['changes']={'rating':'5'}
        bad={'edit':p['edit'],'token':p['token'],'request_id':'rating-refused'}
        self.assertEqual(c.post(f'/api/v1/photos/{self.pid}/date-save',json=bad).status_code,400)
        self.assertEqual(self.xdest.read_bytes(),self.original)

    def test_first_sidecar_context_does_not_prefill_fallback_date(self):
        c=self.client(sidecar=False)
        ctx=c.get(f'/api/v1/photos/{self.pid}/date-edit').json()
        self.assertTrue(ctx['target']['create'])
        self.assertFalse(ctx['date']['present'])
        self.assertIsNone(ctx['date']['value'])
        p=self.plan(c,'2015-02-03T04:05:06').json()
        run,_=self.save(c,p);self.assertEqual(run['status'],'Completed',run)

    def test_source_and_cross_photo_donor_refused(self):
        c=self.client()
        p=self.plan(c,'2015-02-03T04:05:06').json()
        p['edit']['changes']={}
        p['edit']['copy_fields']={'date_taken':{'photo_id':self.pid+1,'capture_id':self.capture,'source_id':'exif'}}
        self.assertEqual(c.post(f'/api/v1/photos/{self.pid}/date-save',json={'edit':p['edit'],'token':p['token'],'request_id':'cross'}).status_code,400)
        with ns_db.connect(self.db) as conn:conn.execute("UPDATE photos SET status='Pending' WHERE id=?",(self.pid,))
        self.assertEqual(c.get(f'/api/v1/photos/{self.pid}/date-edit').status_code,409)
        self.assertEqual(self.plan(c,'2015-02-03T04:05:06').status_code,400)

    def test_embedded_exif_save_and_writer_limits(self):
        subprocess.run(["exiftool", "-overwrite_original", "-XMP:all=", str(self.photo)], check=True, capture_output=True)
        c=self.client(sidecar=False)
        with ns_db.connect(self.db) as conn:
            ns_db.save_settings(conn,{'metadata_write_non_raw':'embedded'},expected_revisions={'metadata_write_non_raw':1})
        ctx=c.get(f'/api/v1/photos/{self.pid}/date-edit').json()
        self.assertEqual(ctx['target']['kind'],'embedded_exif')
        self.assertFalse(ctx['can_clear'])
        self.assertEqual(self.plan(c,'').status_code,400)
        self.assertEqual(self.plan(c,'2011').status_code,400)
        value='2011-02-03T04:05:06.123+02:00'
        first=self.plan(c,value).json()
        occupied=self.root/'dest'/first['filing']['proposed']
        occupied.parent.mkdir(parents=True,exist_ok=True)
        occupied.write_bytes(b'other photo')
        p=self.plan(c,value)
        self.assertEqual(p.status_code,200,p.text)
        self.assertTrue(p.json()['filing']['collision_renamed'])
        run,_=self.save(c,p.json())
        self.assertEqual(occupied.read_bytes(),b'other photo')
        self.assertTrue((self.root/'dest'/p.json()['filing']['proposed']).is_file())
        self.assertEqual(run['status'],'Completed',run)
        self.assertEqual((run['outcome']['verdict'],run['outcome']['succeeded'],run['outcome']['total']),('success',1,1))
        ctx=c.get(f'/api/v1/photos/{self.pid}/date-edit')
        self.assertEqual(ctx.status_code,200,ctx.text)
        self.assertEqual(ctx.json()['date']['value'],'2011-02-03T04:05:06.123+02:00')
        self.assertEqual(self.photo.read_bytes(),self.photo_bytes)
