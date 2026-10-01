#!/usr/bin/env python3
"""Attribute synthetic Inspector/set queries to SQL execution and fetch time.

Requires an unchanged fixture from benchmark-synthetic-queries.py. Profiling adds
overhead; use the benchmark runner, not this tool, for A/B latency comparisons.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sqlite3
import time
from unittest import mock

spec = importlib.util.spec_from_file_location('benchmark', Path(__file__).with_name('benchmark-synthetic-queries.py'))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class TimedCursor(sqlite3.Cursor):
    record = None

    def timed(self, method, *args):
        start = time.perf_counter()
        try:
            return method(*args)
        finally:
            if self.record is not None:
                self.record['elapsed_ms'] += (time.perf_counter()-start)*1000

    def fetchone(self):
        return self.timed(super().fetchone)

    def fetchall(self):
        return self.timed(super().fetchall)

    def fetchmany(self, *args):
        return self.timed(super().fetchmany, *args)

    def __next__(self):
        return self.timed(super().__next__)


class TimedConnection(sqlite3.Connection):
    records = None

    def execute(self, sql, parameters=()):
        cursor = self.cursor(factory=TimedCursor)
        if sql.lstrip().upper().startswith(('SELECT', 'WITH')):
            plan = list(super().execute('EXPLAIN QUERY PLAN '+sql, parameters))
            cursor.record = {'sql':sql, 'plan':[r[3] for r in plan], 'elapsed_ms':0}
            self.records.append(cursor.record)
        cursor.timed(cursor.execute, sql, parameters)
        return cursor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New JSON report')
    args = parser.parse_args()
    manifest = json.loads((args.fixture/'manifest.json').read_text())
    db = args.fixture/'catalog.sqlite'
    if manifest.get('kind') != 'negativespace-synthetic-query-v1' or not benchmark.fixture_unchanged(db,manifest):
        raise ValueError('Expected an unchanged generated fixture')
    original_connect = sqlite3.connect
    original_db_connect = benchmark.ns_db.connect
    def connect(*a, **kw):
        return original_connect(*a, **kw, factory=TimedConnection)
    def readonly(*a, **kw):
        conn = original_db_connect(*a, **kw)
        conn.execute('PRAGMA query_only=ON')
        return conn
    workloads = {
        'inspector_counts':lambda:benchmark.matching.counts(db,1),
        'inspector_candidates':lambda:benchmark.matching.matches(db,1,threshold=90,page_size=12),
        'related_root':lambda:benchmark.reference_sets.browse(db,1,threshold=90,page_size=12),
        'related_expansion':lambda:benchmark.reference_sets.browse(db,1,threshold=90,include=[2],page_size=12),
    }
    with args.output.open('x') as output:
        report = {'fixture':manifest,'workloads':{}}
        with mock.patch.object(sqlite3,'connect',connect), mock.patch.object(benchmark.ns_db,'connect',readonly):
            for name, action in workloads.items():
                TimedConnection.records = []
                start = time.perf_counter()
                action()
                elapsed = (time.perf_counter()-start)*1000
                report['workloads'][name] = {'elapsed_ms':elapsed,'statements':TimedConnection.records}
                print(json.dumps({'workload':name,'elapsed_ms':elapsed}),flush=True)
        report['database_unchanged'] = benchmark.fixture_unchanged(db,manifest)
        json.dump(report,output,indent=2)
        output.write('\n')
    return int(not report['database_unchanged'])


if __name__ == '__main__':
    raise SystemExit(main())
