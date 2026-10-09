"""XMP content/arrival durability and backup tests using generated metadata only."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import zstandard

from engine import backups, ns_db, xmp, xmp_store


def packet(text='caption', padding=0):
    return (f'<x:xmpmeta xmlns:x="{xmp.XMP_META}"><rdf:RDF xmlns:rdf="{xmp.RDF}">'
            f'<rdf:Description rdf:about="" xmlns:dc="{xmp.DC}">'
            f'<dc:description>{text}</dc:description></rdf:Description></rdf:RDF>'
            f'</x:xmpmeta>' + (' ' * padding)).encode()


class CodecTests(unittest.TestCase):
    def test_compress_or_raw_preserves_exact_original(self):
        for raw in (b'x', packet('generated', 10000), packet('雪'), packet('different\r\nspacing')):
            codec, payload, digest = xmp_store.encode_original(raw)
            self.assertLessEqual(len(payload), len(raw))
            self.assertEqual(xmp_store.decode_original(codec, payload, len(raw), digest), raw)
        self.assertEqual(xmp_store.encode_original(b'x')[0], 'raw')
        self.assertEqual(xmp_store.encode_original(packet(padding=10000))[0], 'zstd')

    def test_corruption_and_unknown_encoding_are_refused(self):
        raw = packet(padding=1000)
        codec, payload, digest = xmp_store.encode_original(raw)
        for encoding, body, size, expected in [
                ('future', payload, len(raw), digest), ('raw', b'other', 5, digest),
                (codec, payload[:-1], len(raw), digest), (codec, payload, len(raw) + 1, digest),
                (codec, payload, len(raw), '0' * 64), (codec, payload, 0, digest),
                (codec, payload, xmp.MAX_BYTES + 1, digest), (codec, payload, True, digest)]:
            with self.subTest(encoding=encoding, size=size), self.assertRaises(xmp_store.InvalidBlob):
                xmp_store.decode_original(encoding, body, size, expected)

    def test_trailing_frames_and_unknown_sizes_are_refused(self):
        raw = packet(padding=1000)
        codec, payload, digest = xmp_store.encode_original(raw)
        unknown = zstandard.ZstdCompressor(write_content_size=False, write_checksum=True).compress(raw)
        no_checksum = zstandard.ZstdCompressor(write_checksum=False).compress(raw)
        for bad in (payload + payload, payload + b'junk', unknown, no_checksum):
            with self.assertRaises(xmp_store.InvalidBlob):
                xmp_store.decode_original('zstd', bad, len(raw), digest)

    def test_oversized_frame_is_refused_before_decompression(self):
        raw = b'a' * 4096
        frame = zstandard.ZstdCompressor(write_checksum=True).compress(raw)
        with mock.patch.object(xmp, 'MAX_BYTES', 2048), \
                mock.patch.object(zstandard, 'ZstdDecompressor', side_effect=AssertionError('Decoder called')):
            with self.assertRaises(xmp_store.InvalidBlob):
                xmp_store.decode_original('zstd', frame, 2048, hashlib.sha256(raw).hexdigest())


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'catalog.db'
        self.backup_dir = self.root / 'backups'
        self.backup_dir.mkdir()
        ns_db.initialize(self.path)
        self.conn = ns_db.connect(self.path, synchronous='FULL')
        self.addCleanup(self.conn.close)
        self.run_id = ns_db.create_run(self.conn, mode='INDEX', source='/generated', destination='/destination')[0]
        with ns_db.transaction(self.conn):
            self.file_id = self.conn.execute("INSERT INTO files(created_run_id,created_at) VALUES(?,?)",
                                            (self.run_id, ns_db.utc_now())).lastrowid
        self.data = packet('Generated caption', 1200)

    def retain(self, data=None, **kw):
        args = {'data': self.data if data is None else data, 'run_id': self.run_id,
                'source_relative_path': 'folder/photo.CR2.xmp', 'file_ids': [self.file_id],
                'role': 'owner', 'basis': 'full_name'}
        args.update(kw)
        return xmp_store.retain_capture(self.conn, **args)

    def test_invalid_typed_values_are_retained_only_for_attention(self):
        data = (f'<rdf:RDF xmlns:rdf="{xmp.RDF}" xmlns:tiff="{xmp.TIFF}">'
                '<rdf:Description rdf:about="" tiff:Orientation="9"/></rdf:RDF>').encode()
        with ns_db.transaction(self.conn):
            with self.assertRaises(xmp_store.InvalidCapture):
                self.retain(data)
            self.retain(data, role='candidate', basis='unresolved')
        version = self.conn.execute('SELECT version_id,validation_state,validation_code,fields_json,reader_version '
                                    'FROM xmp_versions').fetchone()
        self.assertEqual(tuple(version)[1:], ('needs_attention', 'invalid_orientation', None, 2))
        self.assertEqual(xmp_store.original_bytes(self.conn, version[0]), data)

    def backup(self):
        return ns_db.backup_catalog(self.path, self.backup_dir, self.root / 'appdata', trigger='manual')

    def restored_catalog(self, result):
        raw = zstandard.ZstdDecompressor().decompress((self.backup_dir / result['filename']).read_bytes())
        target = self.root / 'restored.db'
        target.write_bytes(raw)
        conn = ns_db.connect(target)
        self.addCleanup(conn.close)
        return conn

    def test_exact_blob_parsed_metadata_and_immutable_records(self):
        with ns_db.transaction(self.conn):
            saved = self.retain()
        self.assertEqual(xmp_store.original_bytes(self.conn, saved['version_id']), self.data)
        fields, size, codec, blobtype = self.conn.execute(
            'SELECT fields_json,original_size,encoding,typeof(payload) FROM xmp_versions').fetchone()
        self.assertEqual(json.loads(fields), {'caption': 'Generated caption'})
        self.assertEqual((size, codec, blobtype), (len(self.data), 'zstd', 'blob'))
        for table in ('xmp_versions', 'xmp_arrivals', 'xmp_arrival_files'):
            for command in (f'DELETE FROM {table}', f'UPDATE {table} SET rowid=rowid'):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(command)
                self.conn.rollback()

    def test_identical_content_keeps_separate_arrival_names_runs_and_links(self):
        with ns_db.transaction(self.conn):
            first = self.retain()
        run2 = ns_db.create_run(self.conn, mode='INDEX', source='/another-archive', destination='/destination')[0]
        with ns_db.transaction(self.conn):
            second = self.retain(run_id=run2, source_relative_path='renamed.xmp')
        self.assertEqual(first['version_id'], second['version_id'])
        self.assertNotEqual(first['arrival_id'], second['arrival_id'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0], 1)
        self.assertEqual(self.conn.execute('SELECT source_relative_path FROM xmp_arrivals ORDER BY arrival_id').fetchall(),
                         [('folder/photo.CR2.xmp',), ('renamed.xmp',)])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM xmp_arrival_files').fetchone()[0], 2)

    def test_shared_sidecar_has_two_photo_participants_without_copying_blob(self):
        with ns_db.transaction(self.conn):
            second_file = self.conn.execute('INSERT INTO files(created_run_id,created_at) VALUES(?,?)',
                                            (self.run_id, ns_db.utc_now())).lastrowid
            saved = self.retain(file_ids=[second_file, self.file_id], basis='policy')
        self.assertEqual(self.conn.execute('SELECT file_id FROM xmp_arrival_files ORDER BY file_id').fetchall(),
                         [(self.file_id,), (second_file,)])
        self.assertEqual(xmp_store.original_bytes(self.conn, saved['version_id']), self.data)

    def test_same_run_path_replay_is_idempotent_and_conflicting_payload_refused(self):
        with ns_db.transaction(self.conn):
            first = self.retain()
        before = list(self.conn.iterdump())
        with ns_db.transaction(self.conn):
            replay = self.retain()
            self.assertFalse(replay['created'])
            self.assertEqual(replay['arrival_id'], first['arrival_id'])
            for kw in ({'data': packet('other')}, {'role': 'candidate', 'basis': 'unresolved'}):
                with self.assertRaises(xmp_store.InvalidCapture):
                    self.retain(**kw)
        self.assertEqual(list(self.conn.iterdump()), before)

    def test_damaged_capture_is_preserved_but_cannot_supply_fields_or_ownership(self):
        raw = b'<x:xmpmeta interrupted'
        with ns_db.transaction(self.conn):
            with self.assertRaises(xmp_store.InvalidCapture):
                self.retain(raw)
            saved = self.retain(raw, role='candidate', basis='unresolved')
        self.assertEqual(saved['state'], 'needs_attention')
        self.assertEqual(xmp_store.original_bytes(self.conn, saved['version_id']), raw)
        self.assertIsNone(self.conn.execute('SELECT fields_json FROM xmp_versions').fetchone()[0])

    def test_empty_non_xmp_and_oversized_captures_never_enter_catalog(self):
        with ns_db.transaction(self.conn):
            for raw in (b'', b'\xff\xd8\xffjunk', b'<unrelated/>'):
                with self.assertRaises(xmp_store.InvalidCapture):
                    self.retain(raw, role='candidate', basis='unresolved')
            with mock.patch.object(xmp, 'MAX_BYTES', 20):
                with self.assertRaises(xmp_store.InvalidCapture):
                    self.retain(self.data)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0], 0)

    def test_storage_reparses_bytes_instead_of_trusting_metadata_object(self):
        forged = xmp.ReadResult('valid', 'parsed', b'fake')
        with ns_db.transaction(self.conn), self.assertRaises(xmp_store.InvalidCapture):
            self.retain(forged)

    def test_full_transaction_required_and_outer_rollback_leaves_nothing(self):
        with self.assertRaises(RuntimeError):
            self.retain()
        self.conn.execute('PRAGMA synchronous=NORMAL')
        with ns_db.transaction(self.conn), self.assertRaises(RuntimeError):
            self.retain()
        self.conn.execute('PRAGMA synchronous=FULL')
        with self.assertRaisesRegex(RuntimeError, 'injected failure'), ns_db.transaction(self.conn):
            self.retain()
            raise RuntimeError('injected failure')
        for table in ('xmp_versions', 'xmp_arrivals', 'xmp_arrival_files'):
            self.assertEqual(self.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)

    def test_failed_participant_insertion_rolls_back_inner_savepoint(self):
        with ns_db.transaction(self.conn):
            with self.assertRaises(sqlite3.IntegrityError):
                self.retain(file_ids=[self.file_id, 999999])
            self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM xmp_versions').fetchone()[0], 0)
            self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM xmp_arrivals').fetchone()[0], 0)
            self.retain()  # The caller may handle refusal without orphan content.

    def test_path_and_participant_input_validation(self):
        with ns_db.transaction(self.conn):
            for kw in ({'source_relative_path': '../escape.xmp'}, {'source_relative_path': 'photo.jpg'},
                       {'file_ids': []}, {'file_ids': [True]}, {'file_ids': [self.file_id, self.file_id]},
                       {'basis': 'unresolved'}, {'role': 'owner', 'basis': 'guess'}):
                with self.subTest(kw=kw), self.assertRaises(ValueError):
                    self.retain(**kw)

    def test_catalog_backup_restores_all_versions_and_arrival_lineage(self):
        with ns_db.transaction(self.conn):
            first = self.retain()
            second = self.retain(packet('second'), source_relative_path='other.xmp')
        result = self.backup()
        self.assertEqual(result['outcome'], 'succeeded', result)
        restored = self.restored_catalog(result)
        self.assertEqual(xmp_store.original_bytes(restored, first['version_id']), self.data)
        self.assertEqual(xmp_store.original_bytes(restored, second['version_id']), packet('second'))
        self.assertEqual(restored.execute('SELECT COUNT(*) FROM xmp_arrival_files').fetchone()[0], 2)
        self.assertEqual(ns_db.unbacked_changes(restored)[0], 0)

    def test_corrupt_blob_prevents_backup_publication(self):
        with ns_db.transaction(self.conn):
            self.retain()
        self.conn.execute('DROP TRIGGER immutable_xmp_versions_UPDATE')
        self.conn.execute("UPDATE xmp_versions SET sha256=?", ('0' * 64,))
        self.conn.commit()
        result = self.backup()
        self.assertEqual((result['outcome'], result['error_category']), ('failed', 'verification_failed'))
        self.assertFalse(list(self.backup_dir.glob('*.zst')))
        self.assertFalse(list(self.backup_dir.glob('*.partial')))

    def test_oversized_catalog_blob_is_not_materialized_into_python(self):
        self.conn.execute('PRAGMA ignore_check_constraints=ON')
        with ns_db.transaction(self.conn):
            saved = self.retain()
        self.conn.execute('DROP TRIGGER immutable_xmp_versions_UPDATE')
        self.conn.execute('UPDATE xmp_versions SET payload=zeroblob(?), original_size=?',
                          (xmp.MAX_BYTES + 1, xmp.MAX_BYTES + 1))
        self.conn.commit()
        row = xmp_store._blob_rows(self.conn, saved['version_id']).fetchone()
        self.assertIsNone(row[4])
        with self.assertRaises(xmp_store.InvalidBlob):
            xmp_store.original_bytes(self.conn, saved['version_id'])

    def test_parsed_metadata_queries_do_not_load_or_decompress_original(self):
        with ns_db.transaction(self.conn):
            self.retain()
        with mock.patch.object(xmp_store, 'decode_original', side_effect=AssertionError('Unexpected decode')):
            fields = json.loads(self.conn.execute('SELECT fields_json FROM xmp_versions').fetchone()[0])
            self.assertEqual(fields['caption'], 'Generated caption')

    def test_arrival_watermark_does_not_depend_on_timestamp_order(self):
        with ns_db.transaction(self.conn):
            self.retain()
        self.assertEqual(ns_db.unbacked_changes(self.conn)[0], 1)
        self.assertEqual(ns_db.unbacked_changes(self.conn, exclude_run_id=self.run_id)[0], 0)
        self.assertEqual(self.backup()['outcome'], 'succeeded')
        self.assertEqual(ns_db.unbacked_changes(self.conn)[0], 0)
        with mock.patch.object(ns_db, 'utc_now', return_value='2000-01-01T00:00:00+00:00'):
            with ns_db.transaction(self.conn):
                self.retain(source_relative_path='late-arrival.xmp')
        self.assertEqual(ns_db.unbacked_changes(self.conn)[0], 1)
        self.assertEqual(ns_db.unbacked_changes(self.conn)[2], [self.run_id])

    def test_arrival_during_backup_is_not_claimed_by_older_snapshot(self):
        with ns_db.transaction(self.conn):
            first = self.retain()
        actual_compress = ns_db._compress_and_verify
        def compress_with_arrival(raw, packed):
            with ns_db.transaction(self.conn):
                self.retain(source_relative_path='during-backup.xmp')
            actual_compress(raw, packed)
        with mock.patch.object(ns_db, '_compress_and_verify', side_effect=compress_with_arrival):
            result = self.backup()
        self.assertEqual(result['outcome'], 'succeeded')
        self.assertEqual(ns_db.unbacked_changes(self.conn)[0], 1)
        restored = self.restored_catalog(result)
        self.assertEqual(restored.execute('SELECT arrival_id FROM xmp_arrivals').fetchall(),
                         [(first['arrival_id'],)])
        self.assertEqual(ns_db.unbacked_changes(restored)[0], 0)

    def test_post_job_backup_covers_xmp_only_job(self):
        with ns_db.transaction(self.conn):
            self.retain()
        backups.backup_after_job(self.path, self.backup_dir, self.root / 'appdata', self.run_id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM backup_attempts WHERE outcome='succeeded'").fetchone()[0], 1)
        self.assertEqual(ns_db.unbacked_changes(self.conn)[0], 0)

    def test_backup_rejects_missing_new_tables(self):
        self.conn.execute('DROP TABLE xmp_arrival_files')
        self.conn.commit()
        with self.assertRaises(ns_db.SchemaError):
            ns_db.require_schema(self.conn)
