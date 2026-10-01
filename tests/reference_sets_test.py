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
