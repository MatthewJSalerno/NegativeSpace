"""Reference sets: direct membership, explicit overlap expansion and no writes."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import webui_api_test as fixtures
import ns_db


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

    def get(self, root=None, query=''):
        response=self.client.get(f'/api/v1/similar/{root or self.a}/sets?threshold=90{query}')
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_chain_expands_only_explicit_direct_reference(self):
        before=list(self.conn.iterdump())
        root=self.get()
        self.assertEqual({p['id'] for p in root['items']},{self.a,self.b})
        self.assertEqual([(p['id'],p['additional']) for p in root['related']],[(self.b,1)])
        other=self.get(self.b)
        self.assertEqual({p['id'] for p in other['items']},{self.a,self.b,self.c})
        self.assertEqual(next(p['additional'] for p in other['related'] if p['id']==self.a),0)
        combined=self.get(query=f'&include={self.b}')
        self.assertEqual({p['id'] for p in combined['items']},{self.a,self.b,self.c})
        self.assertEqual(combined['total'],3)
        indirect=next(p for p in combined['items'] if p['id']==self.c)
        self.assertFalse(indirect['direct'])
        self.assertIsNone(indirect['score'])
        self.assertEqual(indirect['references'],[self.b])
        self.assertNotIn(self.d,[p['id'] for p in combined['items']])
        self.assertEqual(list(self.conn.iterdump()),before)

    def test_paging_thresholds_and_stale_requests(self):
        response=self.get(query=f'&include={self.b}&page_size=1&page=99&related_page=99')
        self.assertEqual((response['total'],response['page'],len(response['items'])),(3,3,1))
        self.assertEqual(response['related_page'],1)
        high=self.client.get(f'/api/v1/similar/{self.a}/sets?threshold=95').json()
        self.assertEqual(high['total'],1)
        self.assertEqual(high['related_total'],0)
        for suffix in (f'&include={self.c}',f'&include={self.a}','&include=-1','&include=99999', '&include=1'*7):
            self.assertEqual(self.client.get(f'/api/v1/similar/{self.a}/sets?threshold=90{suffix}').status_code,400)
        for query in ('threshold=74','threshold=101','page=0','page_size=25'):
            self.assertEqual(self.client.get(f'/api/v1/similar/{self.a}/sets?{query}').status_code,422)
        self.conn.execute("UPDATE file_states SET presence_state='missing' WHERE current_path='/destination/B.jpg'")
        self.conn.commit()
        self.assertEqual(self.get()['total'],1)
        self.assertEqual(self.client.get(f'/api/v1/similar/{self.a}/sets?threshold=90&include={self.b}').status_code,400)

    def test_exact_content_dedup_and_equal_hash_membership(self):
        duplicate=self.photo('A-copy','a','0000000000000000')
        equal=self.photo('A-lookalike','e','0000000000000000')
        source=self.photo('source-only','s','0000000000000000',status='Pending')
        broken=self.photo('no-hash','h',None)
        response=self.get()
        ids=[p['id'] for p in response['items']]
        self.assertIn(equal,ids)
        self.assertNotIn(duplicate,ids)
        self.assertNotIn(source,ids)
        self.assertNotIn(broken,ids)
        self.assertEqual(response['state']['unavailable'],1)
        self.assertEqual(self.client.get(f'/api/v1/similar/{source}/sets').status_code,400)
        self.assertEqual(self.client.get(f'/api/v1/similar/{broken}/sets').status_code,400)

    def test_identical_sets_collapse_before_paging_and_selection(self):
        # A/B and B/A/C are different despite overlapping; equal-hash A2
        # has exactly A's neighborhood, not merely the same match count.
        equal = self.photo('A-lookalike', 'e', '0000000000000000')
        self.refresh()
        before = list(self.conn.iterdump())
        query = '/api/v1/photos?view=similar&match_min=90&group_sets=true&sort=name'
        result = self.client.get(query).json()
        self.assertEqual(result['total'], 4)
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
