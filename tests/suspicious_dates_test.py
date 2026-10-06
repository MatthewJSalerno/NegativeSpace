"""Suspicious-date policy, shared browse membership and read-only inspection."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from webui_api_test import ApiCase
from engine import ns_db

class SuspiciousDates(ApiCase):
    def test_policy_and_browse_paths_preserve_metadata(self):
        self.create_catalog()
        year = datetime.now(timezone.utc).year
        values = [('0001-01-01', 'exif', True), ('2218-01-01', 'exif', True),
                  ('1799-12-31', 'file_mtime', True), ('1800-01-01', 'exif', False),
                  (f'{year+1}-12-31', 'exif', False), (f'{year+2}-01-01', 'exif', True),
                  (None, 'file_mtime', False), ('1900-01-01', 'exif', False)]
        with ns_db.connect(self.cfg.db_path) as conn:
            for i,(date,source,_) in enumerate(values):
                conn.execute("INSERT INTO photos(source_path,status,metadata_json) VALUES(?,'Pending',?)",
                             (str(self.cfg.source/f'{i}.jpg'),json.dumps({'date_taken':date,'date_source':source})))
            conn.commit()
            before = conn.execute('SELECT metadata_json FROM photos ORDER BY id').fetchall()
        result = self.client.get('/api/v1/photos?view=suspicious').json()
        expected = [i+1 for i,(_,_,bad) in enumerate(values) if bad]
        self.assertEqual(result['total'],len(expected))
        self.assertEqual(sorted(p['id'] for p in result['items']), expected)
        for i,(_,_,bad) in enumerate(values):
            detail = self.client.get(f'/api/v1/photos/{i+1}/inspect').json()
            self.assertEqual(bool(detail['date_warning']),bad)
        ids = self.client.get('/api/v1/photos/ids?view=suspicious').json()
        self.assertEqual(sorted(ids['ids']),expected)
        page = self.client.get('/api/v1/photos?view=suspicious&page_size=1&page=2').json()
        self.assertEqual(len(page['items']),1)
        narrowed = self.client.get('/api/v1/photos?view=suspicious&undated=true').json()
        self.assertEqual([p['id'] for p in narrowed['items']],[3])
        for endpoint in ('timeline','types','folders'):
            response = self.client.get(f'/api/v1/photos/{endpoint}?view=suspicious')
            self.assertEqual(response.status_code,200,response.text)
        with ns_db.connect(self.cfg.db_path) as conn:
            self.assertEqual(conn.execute('SELECT metadata_json FROM photos ORDER BY id').fetchall(),before)
