"""Reference sets: grouped-gallery collapse and a set's direct members, with no writes."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import webui_api_test as fixtures
from engine import ns_db


class ReferenceSetsTests(fixtures.ApiCase):
    photo = fixtures.MatchingTests.photo
    refresh = fixtures.MatchingTests.refresh

    def setUp(self):
        super().setUp()
        self.create_catalog()
        self.conn = ns_db.connect(self.cfg.db_path)
        self.run = ns_db.create_run(self.conn, mode='INDEX', source='/source', destination='/destination')[0]
        self.a = self.photo('A', 'a', '0000000000000000')
        self.b = self.photo('B', 'b', '000000000000003f')
        self.c = self.photo('C', 'c', '0000000000000fff')
        self.d = self.photo('D', 'd', '000000000003ffff')
        self.refresh()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_identical_sets_collapse_before_paging_and_selection(self):
        # A/B and B/A/C are different despite overlapping; equal-hash A2
        # has exactly A's neighborhood, not merely the same match count.
        equal = self.photo('A-lookalike', 'e', '0000000000000000')
        self.refresh()
        before = list(self.conn.iterdump())
        query = '/api/v1/photos?view=similar&match_min=90&group_sets=true&sort=name'
        result = self.client.get(query).json()
        self.assertEqual(result['total'], 4)
        self.assertEqual(result['matches']['similar'], 5, 'view button counts photos, not sets')
        two_members = self.client.get(query+'&q=A').json()
        self.assertEqual(two_members['total'], 1)
        self.assertEqual(two_members['matches']['similar'], 2)
        self.assertEqual({p['id'] for p in result['items']}, {self.a,self.b,self.c,self.d})
        self.assertEqual(self.client.get(query+'&page_size=1&page=2').json()['items'][0]['id'], self.b)
        selected = self.client.get('/api/v1/photos/ids?view=similar&match_min=90&group_sets=true').json()
        self.assertEqual(set(selected['ids']), {self.a,self.b,self.c,self.d})
        filtered = self.client.get(query+'&q=A-lookalike').json()
        self.assertEqual([p['id'] for p in filtered['items']], [equal])
        self.assertEqual(filtered['items'][0]['similar_count'], 2)
        position = self.client.post('/api/v1/photos/position',json={
            'view':'similar','sort':'name','match_min':90,'group_sets':True,'photo_id':self.b}).json()
        self.assertEqual(position['position'],1)
        self.assertEqual(list(self.conn.iterdump()), before)

    def test_different_hashes_with_identical_members_and_threshold_split(self):
        # At 75% A/B/C share the same closed neighborhood when D is absent.
        self.conn.execute("UPDATE photos SET status='Pending' WHERE id=?", (self.d,))
        self.conn.commit()
        self.refresh()
        base='/api/v1/photos?view=similar&group_sets=true&match_min='
        broad=self.client.get(base+'75').json()
        self.assertEqual([p['id'] for p in broad['items']], [self.a])
        self.assertEqual(broad['items'][0]['similar_count'], 2)
        narrow=self.client.get(base+'90').json()
        self.assertEqual(narrow['total'], 3)
        self.assertEqual(self.client.get(base+'100').json()['total'], 0)

    def test_set_gallery_pages_selects_and_positions_only_direct_members(self):
        endpoint=f'/api/v1/photos?view=similar&match_min=90&set_reference={self.a}&sort=name'
        result=self.client.get(endpoint).json()
        self.assertEqual({r['id'] for r in result['items']},{self.a,self.b})
        self.assertEqual(result['total'],2)
        self.assertEqual(len(self.client.get(endpoint+'&page_size=1&page=2').json()['items']),1)
        selected=self.client.get(f'/api/v1/photos/ids?view=similar&match_min=90&set_reference={self.a}').json()
        self.assertEqual(set(selected['ids']),{self.a,self.b})
        position=self.client.post('/api/v1/photos/position',json={'view':'similar','sort':'name',
            'match_min':90,'set_reference':self.a,'photo_id':self.a}).json()
        self.assertEqual(position['next_id'],self.b)
        self.assertIsNone(self.client.post('/api/v1/photos/position',json={'view':'similar','sort':'name',
            'match_min':90,'set_reference':self.a,'photo_id':self.c}).json()['position'])
        self.assertEqual(self.client.get(endpoint.replace(f'set_reference={self.a}','set_reference=-1')).status_code,422)

    def test_set_gallery_keeps_reference_when_no_candidates_meet_threshold(self):
        base=f'/api/v1/photos?view=all&match_min=100&set_reference={self.a}&sort=matches'
        response=self.client.get(base)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([p['id'] for p in response.json()['items']],[self.a])
        position=self.client.post('/api/v1/photos/position',json={'view':'all','sort':'matches',
            'match_min':100,'set_reference':self.a,'photo_id':self.a})
        self.assertEqual(position.status_code,200,position.text)
        self.assertEqual(position.json()['position'],0)
