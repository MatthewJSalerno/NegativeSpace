#!/usr/bin/env python3
"""Prepare a separate schema-16 catalog from schema 14 or 15; never overwrite the source.

Only the derived similarity cache and schema marker change. Photos, run history,
lineage, settings, thumbnails and saved judgments are copied through SQLite backup.
Automatic startup upgrades remain disabled. Stop the app before using the result
as its catalog so no writes made after the snapshot are lost.
"""
import argparse
import contextlib
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ns_db
import ns_similarity
import ns_similarity_cache


def prepare(source, output, *, compare=False):
    source, output = Path(source).resolve(), Path(output).resolve()
    if ns_db.SCHEMA_VERSION != 16:
        raise ValueError('This tool prepares schema 16 only')
    # Exclusive creation protects both the original catalog and any previous result.
    with output.open('xb'):
        pass
    try:
        with contextlib.closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original, \
                contextlib.closing(sqlite3.connect(output)) as target:
            original.backup(target)
            version = target.execute('SELECT version FROM catalog_schema').fetchall()
            if version not in ([(14,)], [(15,)]):
                raise ValueError('Expected a schema-14 or schema-15 source catalog')
            target.execute('PRAGMA journal_mode=DELETE')
            target.execute('PRAGMA foreign_keys=ON')
            with target:
                if version == [(14,)]:
                    target.execute('DROP TABLE content_similarity')
                    target.execute('DELETE FROM similarity_hashes')
                target.execute('DROP TABLE catalog_schema')
                for statement in ns_db.FOUNDATION_DDL:
                    if statement.startswith(('CREATE TABLE content_similarity ',
                                             'CREATE INDEX idx_similarity_reverse ',
                                             'CREATE TABLE catalog_schema ',
                                             'INSERT INTO catalog_schema ')):
                        if version == [(14,)] or 'catalog_schema' in statement:
                            target.execute(statement)
                for statement in ns_similarity_cache.DDL:
                    target.execute(statement)
            ns_db.require_schema(target)
            started = time.perf_counter()
            if compare:
                ns_similarity.refresh(target)
            elapsed = time.perf_counter() - started
            ns_similarity_cache.refresh(target)
            if target.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise ValueError('Prepared catalog failed integrity check')
            if target.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('Prepared catalog failed foreign-key check')
            pairs = target.execute('SELECT COUNT(*) FROM content_similarity').fetchone()[0]
            hashes = target.execute('SELECT COUNT(*) FROM similarity_hashes').fetchone()[0]
        return {'schema':16, 'compared_hashes':hashes, 'stored_pairs':pairs,
                'comparison_seconds':round(elapsed, 3) if compare else None}
    except BaseException:
        # This invocation exclusively created the output; never remove input data.
        output.unlink(missing_ok=True)
        for suffix in ('-wal', '-shm', '-journal'):
            Path(str(output) + suffix).unlink(missing_ok=True)
        raise


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New file; refuses an existing path')
    parser.add_argument('--compare', action='store_true', help='Precompute the 75–100%% range from stored hashes')
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output, compare=args.compare), indent=2))


if __name__ == '__main__':
    main()
