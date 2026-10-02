"""Synthetic query fixtures have known memberships and never need image files."""
import importlib.util
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/benchmark-synthetic-queries.py'
spec = importlib.util.spec_from_file_location('synthetic_queries', SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class SyntheticQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, profile):
        directory = self.root / profile
        manifest = benchmark.build_fixture(directory, 100, profile)
        return directory / 'catalog.sqlite', manifest

    def test_known_membership_and_identical_group_collapse(self):
        for profile, groups, members, edges in [('sparse',20,5,0), ('equal',1,100,0), ('dense',2,64,2646)]:
            with self.subTest(profile=profile):
                db, manifest = self.fixture(profile)
                self.assertEqual(manifest['prepared_edges'], edges)
                self.assertEqual(benchmark.query(db,'gallery',90)['total'],100)
                self.assertEqual(benchmark.query(db,'grouped',90)['total'],groups)
                self.assertEqual(benchmark.query(db,'members',90)['total'],members)
                self.assertEqual(benchmark.query(db,'related',90)['total'],members)
                self.assertEqual(benchmark.fingerprint(db),manifest['database_sha256'])

    def test_mixed_excludes_unavailable_and_failed_hashes(self):
        db, _ = self.fixture('mixed')
        expected = {i for i in range(1,101) if i%11 and i%29 and i%37}
        result = benchmark.catalog.list_photos(db,view='similar',match_min=90,page_size=200)
        self.assertEqual({p['id'] for p in result['items']},expected)
        self.assertGreater(benchmark.query(db,'filtered',90)['total'],0)

    def test_high_threshold_and_edge_guard(self):
        db, _ = self.fixture('dense')
        self.assertEqual(benchmark.query(db,'related',100)['total'],1)
        self.assertEqual(benchmark.query(db,'gallery',100)['total'],0)
        with self.assertRaisesRegex(ValueError,'exceeding'):
            benchmark.build_fixture(self.root/'bounded',100,'dense',max_edges=10)
        self.assertFalse((self.root/'bounded/catalog.sqlite').exists())

    def run_cli(self, *args):
        return subprocess.run([sys.executable,str(SCRIPT),*map(str,args)],capture_output=True,text=True,timeout=30)

    def test_cli_repeat_reuse_and_reject_modified_fixture(self):
        first = self.root/'first'
        result = self.run_cli('--output',first,'--photos',100,'--repeats',2,'--warmups',0)
        self.assertEqual(result.returncode,0,result.stderr)
        report = json.loads((first/'report.json').read_text())
        self.assertTrue(report['database_unchanged'])
        self.assertEqual(len(report['results']),len(benchmark.SCENARIOS))
        for row in report['results']:
            self.assertEqual(row['outcome'],'ok')
            self.assertEqual(row['warm_samples'],2)
            self.assertIsNone(row['p95_ms'])
        comparison = benchmark.compare_reports(report,report)
        self.assertEqual(comparison['candidate_over_baseline'][0]['p50_ms_ratio'],1)
        changed = copy.deepcopy(report)
        changed['results'][0]['samples'][0]['result_sha256'] = 'different'
        with self.assertRaisesRegex(ValueError,'Query results changed'):
            benchmark.compare_reports(report,changed)
        changed = copy.deepcopy(report)
        changed['fixture']['database_sha256'] = 'different'
        with self.assertRaisesRegex(ValueError,'fixture fingerprint'):
            benchmark.compare_reports(report,changed)
        fixture = first/'fixture'
        result = self.run_cli('--output',self.root/'reuse','--fixture',fixture,'--scenarios','grouped','--repeats',1)
        self.assertEqual(result.returncode,0,result.stderr)
        result = self.run_cli('--output',self.root/'compared','--fixture',fixture,
                              '--baseline',first/'report.json','--repeats',2,'--warmups',0)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('comparison',json.loads((self.root/'compared/report.json').read_text()))
        result = self.run_cli('--output',first,'--photos',100)
        self.assertNotEqual(result.returncode,0)
        with sqlite3.connect(fixture/'catalog.sqlite') as conn:
            conn.execute('UPDATE photos SET file_size=42 WHERE id=1')
        result = self.run_cli('--output',self.root/'rejected','--fixture',fixture)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('unchanged synthetic fixture',result.stderr)
        conn.close()
        self.assertFalse(benchmark.fixture_unchanged(fixture/'catalog.sqlite',report['fixture']))

    def test_timeout_preserves_failed_report(self):
        output = self.root/'deadline'
        result = self.run_cli('--output',output,'--photos',100,'--scenarios','grouped','--timeout',0.000001)
        self.assertEqual(result.returncode,1,result.stderr)
        report = json.loads((output/'report.json').read_text())
        self.assertEqual(report['results'][0]['error'],'worker_timeout')
        self.assertTrue(report['database_unchanged'])

    def test_worker_rejects_writes(self):
        db, manifest = self.fixture('sparse')
        def attempted_write(path, *_):
            conn = benchmark.ns_db.connect(path)
            try:
                conn.execute('UPDATE photos SET file_size=42 WHERE id=1')
            finally:
                conn.close()
        pipe = mock.Mock()
        original = benchmark.ns_db.connect
        # worker normally runs in a disposable child; restore its factory patch
        # here because this test exercises it synchronously.
        try:
            with mock.patch.object(benchmark,'query',side_effect=attempted_write):
                benchmark.worker(pipe,db,'gallery',90,0,1)
        finally:
            benchmark.ns_db.connect = original
        self.assertIn('readonly',pipe.send.call_args.args[0]['error'])
        self.assertTrue(benchmark.fixture_unchanged(db,manifest))

    def test_statement_profiler_uses_unchanged_fixture(self):
        db, manifest = self.fixture('sparse')
        output = self.root/'profile.json'
        result = subprocess.run([sys.executable,str(ROOT/'tools/profile-synthetic-queries.py'),
            '--fixture',str(db.parent),'--output',str(output)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        report = json.loads(output.read_text())
        self.assertTrue(report['database_unchanged'])
        self.assertEqual(len(report['workloads']),4)
        for workload in report['workloads'].values():
            self.assertTrue(workload['statements'])
            self.assertTrue(all(s['plan'] for s in workload['statements']))
        self.assertTrue(benchmark.fixture_unchanged(db,manifest))


if __name__ == '__main__':
    unittest.main()
