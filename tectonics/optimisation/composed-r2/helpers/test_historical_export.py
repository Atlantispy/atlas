"""Tiny real-ArrayStore export protocol tests; no historical DB or reader run.

The metadata is a fixture, not a scientific admission. Private commit tests
exercise filesystem publication only. Source transforms are checked against the
actual original r3/r4 reader helpers without importing/executing either reader.
"""
import ast
from concurrent.futures import CancelledError
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent / 'runtime-integration-r1'
HEAT = HERE.parents[2] / 'heat-repair-20261007'
sys.path[:0] = [str(RUNTIME / 'runtime-src'), str(RUNTIME / 'ram'),
               str(RUNTIME / 'helpers'), str(HEAT),
               str(HEAT / 'source' / 'tectonics' / 'tests')]

import numpy as np
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits, StoreError
import historical_export as E


class HistoricalExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.historical-export-', dir=HERE.parents[3])
        self.directory = Path(self.temp.name)
        self.budget = WorkBudget(64 << 20)
        self.limits = StoreLimits(chunk_bytes=128, max_array_bytes=1 << 20,
            max_store_bytes=8 << 20, max_manifest_bytes=65536,
            verified_cache_entries=32, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)
        self.store = ArrayStore(self.directory / 'fixture.sqlite', self.limits, budget=self.budget)
        self.root_key, self.head_key, self.heat_key = 'a'*64, 'b'*64, 'c'*64
        self.root = dict(key=self.root_key, workflow_id='d'*64, kind='root', sequence=0,
                         state={'fields': {'time_s': 0}})
        self.head = dict(key=self.head_key, workflow_id='d'*64, kind='successor', sequence=1,
            parent_key=self.root_key, parent_digest=sha256(E.canonical(self.root)).hexdigest(),
            state={'fields': {'time_s': 2}}, advance={'source_audit_id': 'e'*64})
        self.store.put(self.root_key, {'initial': np.arange(5, dtype=np.float64)},
                       self.root, budget=self.budget)
        # Six groups plus complete geometry/partition blobs in one snapshot.
        self.head_arrays = {prefix + ':carried': np.arange(index+20, dtype=np.float64)
            for index, prefix in enumerate(('collar', 'native', 'exterior-fv',
                'source-audit', 'full-collar', 'spatial-audit'))}
        self.head_arrays['geometry-record'] = np.frombuffer(b'complete geometry', dtype=np.uint8)
        self.head_arrays['partition-record'] = np.frombuffer(b'complete partition', dtype=np.uint8)
        self.store.put(self.head_key, self.head_arrays, self.head, budget=self.budget)
        self.store.put(self.heat_key, {'ledger': np.arange(31, dtype=np.float64)},
            {'schema': 'fixture.heat', 'origin': 'original', 'status': 'FAILED_PRODUCER'}, budget=self.budget)
        self.source = dict(workflow_id='d'*64, root_key=self.root_key, head_key=self.head_key,
            sequence=1, time_s=2, store_token=list(self.store.change_token()), database_sha256='f'*64)
        self.producer = dict(execution_identity='1'*64, execution_mode='strict',
            source_manifest_sha256='2'*64, native_source_digest=E.NATIVE_R7_DIGEST,
            status='FAILED', participating_source_pins={'original.py': '3'*64})
        self.adapter = dict(source_sha256='4'*64, source_manifest_sha256='5'*64)
        self.export_limits = E.ExportLimits(max_record_bytes=65536, max_capsule_bytes=1 << 20)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def stage(self, **changes):
        args = dict(source=self.source, producer=self.producer, adapter=self.adapter,
                    budget=self.budget, limits=self.export_limits)
        args.update(changes)
        return E._stage_protocol(self.directory, self.store, **args)

    def receipt(self):
        return dict(schema='fixture.reader-not-authority', status='protocol-only',
                    complete_fields={'root': self.root, 'head': self.head}, errors=[])

    def commit(self, staged, **changes):
        args = dict(final_check=lambda: None)
        args.update(changes)
        return E._commit_protocol(staged, self.receipt(), **args)

    def test_complete_catalogue_streams_exact_manifests_without_payload_copy(self):
        before = self.store.statistics()
        held_before = self.budget.reserved_bytes
        with patch.object(self.store, 'get', side_effect=AssertionError('whole payload forbidden')):
            staged = self.stage()
        for key in ('snapshots', 'unique_chunks', 'encoded_payload_bytes'):
            self.assertEqual(self.store.statistics()[key], before[key])
        self.assertEqual(list(self.store.change_token()), self.source['store_token'])
        self.assertEqual(staged.inventory['snapshots'], 3)
        self.assertEqual(staged.inventory['arrays'], 10)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(staged.path.read_bytes())
        result = self.commit(staged)
        self.assertFalse(staged.path.exists())
        path = Path(result['path'])
        raw = path.read_bytes()
        self.assertEqual(sha256(raw).hexdigest(), result['sha256'])
        capsule = json.loads(raw)
        self.assertEqual(capsule['schema'], E.SCHEMA)
        self.assertEqual(capsule['chain_metadata'], [self.root, self.head])
        self.assertEqual(capsule['source'], self.source)
        self.assertEqual(capsule['producer'], self.producer)
        self.assertEqual(capsule['validation_receipt']['record'], self.receipt())
        for key, manifest in capsule['snapshot_manifests'].items():
            self.assertEqual(manifest, self.store._manifest(key))
        self.assertEqual(capsule['snapshot_manifests'][self.head_key]['arrays'].keys(), self.head_arrays.keys())
        self.assertEqual(capsule['validation_receipt']['sha256'], sha256(E.canonical(self.receipt())).hexdigest())
        self.assertEqual(self.budget.reserved_bytes, held_before)

    def test_closed_reopen_keeps_complete_array_inventory(self):
        staged = self.stage()
        result = self.commit(staged)
        self.store.close()
        self.store = ArrayStore(self.directory / 'fixture.sqlite', self.limits, budget=self.budget)
        capsule = json.loads(Path(result['path']).read_bytes())
        for name, original in self.head_arrays.items():
            digest = sha256()
            for _, chunk in self.store.iter_chunks(self.head_key, name, budget=self.budget):
                digest.update(memoryview(chunk).cast('B'))
            self.assertEqual(digest.hexdigest(), sha256(memoryview(original).cast('B')).hexdigest())
        self.assertEqual(len(capsule['snapshot_manifests']), self.store.statistics()['snapshots'])

    def test_chunk_corruption_refuses_without_publication(self):
        self.store._db.execute('UPDATE chunks SET payload=? WHERE id=(SELECT id FROM chunks LIMIT 1)',
                               (b'corruption',))
        self.source['store_token'] = list(self.store.change_token())
        with self.assertRaises(StoreError):
            self.stage()
        self.assertEqual(list(self.directory.glob('*.capsule.json')), [])

    def test_manifest_corruption_refuses(self):
        self.store._db.execute('UPDATE snapshots SET body=? WHERE id=?', (b'{}', self.heat_key))
        self.source['store_token'] = list(self.store.change_token())
        with self.assertRaises(StoreError):
            self.stage()
        self.assertEqual(list(self.directory.glob('*.capsule.json')), [])

    def test_changed_checkpoint_and_chain_identities_refuse(self):
        for change in ({'store_token': [99, 99]}, {'root_key': '0'*64},
                       {'head_key': self.root_key}, {'sequence': 2}, {'time_s': 3},
                       {'workflow_id': '0'*64}):
            with self.subTest(change=change), self.assertRaises(E.HistoricalExportRefused):
                self.stage(source=dict(self.source, **change))

    def test_changed_source_modes_refuse(self):
        with self.assertRaises(E.HistoricalExportRefused):
            self.stage(producer=dict(self.producer, execution_mode='release'))
        with self.assertRaises(E.HistoricalExportRefused):
            self.stage(producer=dict(self.producer, source_manifest_sha256='loose hash'))
        with self.assertRaises(E.HistoricalExportRefused):
            self.stage(adapter=dict(self.adapter, source_sha256=''))

    def test_cancel_and_inventory_limits_leave_no_accepted_file(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(CancelledError):
            self.stage(cancel=cancel)
        for override in ({'max_snapshots': 1}, {'max_arrays': 2},
                         {'max_chunk_references': 1}, {'max_raw_bytes': 1},
                         {'max_capsule_bytes': 128}, {'max_record_bytes': 64}):
            with self.subTest(override=override), self.assertRaises(E.HistoricalExportRefused):
                self.stage(limits=E.ExportLimits(**override))
        self.assertEqual(list(self.directory.glob('*.capsule.json')), [])

    def test_staging_tamper_and_late_fence_failure_refuse(self):
        staged = self.stage()
        with staged.path.open('ab') as stream:
            stream.write(b'x')
        with self.assertRaises(E.HistoricalExportRefused):
            self.commit(staged)
        other = self.stage()
        calls = []
        def fence():
            calls.append(1)
            if len(calls) == 2:
                raise E.HistoricalExportRefused('terminal guard failed')
        with self.assertRaises(E.HistoricalExportRefused):
            self.commit(other, final_check=fence)
        self.assertEqual(len(calls), 2)
        self.assertEqual(list(self.directory.glob('*.capsule.json')), [])
        with self.assertRaises(E.HistoricalExportRefused):
            self.commit(other)  # interrupted append cannot be retried as fresh

    def test_publication_interruption_never_creates_complete_name(self):
        staged = self.stage()
        operation = 'rename' if E.os.name == 'nt' else 'link'
        with patch.object(E.os, operation, side_effect=OSError('simulated interruption')):
            with self.assertRaises(OSError):
                self.commit(staged)
        self.assertTrue(staged.path.exists())
        self.assertEqual(list(self.directory.glob('*.capsule.json')), [])

    def test_public_authenticated_export_is_fail_closed(self):
        sink = E.HistoricalExportStaging(self.directory, producer=self.producer,
            adapter=self.adapter, database_sha256=self.source['database_sha256'])
        for proof in ({}, {'science_pass': True}, {'receipt_sha256': 'a'*64}):
            with self.subTest(proof=proof), self.assertRaises(E.HistoricalExportRefused):
                sink.publish_authenticated(**proof)
        with self.assertRaises(E.HistoricalExportRefused):
            sink.capture(workflow=object(), store=self.store, expected={},
                         execution=object(), budget=self.budget)

    def test_original_reader_transform_preserves_all_default_code(self):
        for name in ('private_heat_recovery_consumer_r3.py', 'private_heat_recovery_consumer_r4.py'):
            path = HEAT / name
            before = path.read_bytes()
            source = before.decode('utf8')
            changed = E.transform_recovery_consumer(source)
            compile(changed, name, 'exec')
            tree, original = ast.parse(changed), ast.parse(source)
            function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'consume')
            self.assertEqual(function.args.kwonlyargs[-1].arg, '_historical_export')
            function.args.kwonlyargs.pop(); function.args.kw_defaults.pop()
            class RemoveHook(ast.NodeTransformer):
                def visit_If(self, node):
                    if isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) and node.test.left.id == '_historical_export':
                        return None
                    return self.generic_visit(node)
            RemoveHook().visit(tree)
            self.assertEqual(ast.dump(tree), ast.dump(original))
            self.assertLess(changed.index('_completed_interval(receipt, expected, workflow, evidence)',
                changed.index('def consume(')), changed.index('_historical_export.capture'))
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(E.HistoricalExportRefused):
                E.transform_recovery_consumer(changed)
            with self.assertRaises(E.HistoricalExportRefused):
                E.transform_recovery_consumer(source.replace('_completed_interval(receipt, expected, workflow, evidence)', 'omitted()'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
