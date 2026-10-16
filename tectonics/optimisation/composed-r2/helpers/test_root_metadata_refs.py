"""Route (1) step 1: oversized root metadata through compact field records.

A workflow root at interval-1 size carries about 337 KB of admission
descriptors in its metadata (r9: funding 150,115 B, exterior_owner 94,901 B,
collar_plan 61,799 B, exterior_remainder 26,972 B), over the facade's 64 KiB
bounded-metadata limit. Those four named fields of a root row move into compact
records; the native manifest and its identity are rebuilt byte for byte.
Synthetic descriptors of the r9 sizes; no historical store is read.

Usage as a cold reader child: python -B test_root_metadata_refs.py --child CATALOG KEY EXPECTED.json
"""
import gc
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import traceback
import unittest
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPACT = HERE/'compact-geometry-r1'
RUNTIME = HERE.parent/'runtime-integration-r1'/'runtime-src'
sys.path[:0] = [str(COMPACT), str(RUNTIME), str(HERE)]

import compact_restart_store as CRS
import numpy as np
from atlas_tectonics import storage as N
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreConflict, StoreError
from compact_contracts import ROOT_METADATA_MAX, ContractError
from content_cache import create_retained_scope
from interval_store_set import LIMITS
from segment_store import SegmentBackend, canonical


def key(text):
    return sha256(text.encode()).hexdigest()


def descriptor(name, size):
    """A JSON descriptor of about ``size`` canonical bytes with floats, ints, strings and nesting."""
    rows, total, i = [], 0, 0
    while total < size:
        row = {'id': name+':'+str(i), 'value': i*0.125+1e-9*i, 'count': i, 'tags': ['a', str(i % 7)],
               'nested': {'x': -1.5*i, 'y': [i, i+1, None, True]}}
        total += len(json.dumps(row, separators=(',', ':')))
        rows.append(row)
        i += 1
    return {'schema': 'synthetic.'+name+'.v1', 'rows': rows}


def root_metadata(kind='root'):
    return {'schema': 'atlas.private.collar-workflow.r1', 'workflow_id': key('workflow'), 'key': key('root'),
            'kind': kind, 'sequence': 0, 'funding': descriptor('funding', 150_115),
            'exterior_owner': descriptor('exterior-owner', 94_901),
            'collar_plan': descriptor('collar-plan', 61_799),
            'exterior_remainder': descriptor('exterior-remainder', 26_972),
            'funding_id': key('funding'), 'state': {'small': [1, 2, 3]}, 'native_state_id': key('native'),
            'outer_material_boundary': 'paired space-time flux; carried finite exterior inventories',
            'source_status': 'WORKING NON-CANON', 'geometry_family': 'differential-plate-component-partition-v1'}


def arrays():
    return {'values': np.arange(9000, dtype='<i8'), 'weights': np.linspace(0, 1, 513, dtype='<f8')}


class RootMetadataReferenceTests(unittest.TestCase):
    def setUp(self):
        temporary_root = HERE.parents[3]/'_t'
        temporary_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='step9-rootmeta-', dir=temporary_root)
        self.root = Path(self.temp.name)
        self.budget = WorkBudget(768 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='step9-root-metadata')
        self.store = CRS.CompactRestartStore.create_migration(self.root/'catalog.json',
            workflow_id=key('workflow'), scope=self.scope, producer_identity=key('producer'),
            runtime_identity=key('runtime'))
        self.others = []

    def tearDown(self):
        for store in self.others:
            store.close()
        self.store.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        for path in self.root.rglob('*'):
            if path.is_file():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.temp.cleanup()

    def native_manifest(self, invocation, values, metadata):
        """The native ArrayStore manifest of the same put: the identity the facade must keep."""
        with ArrayStore(self.root/'native.sqlite', LIMITS, budget=self.budget) as native:
            native.put(invocation, values, metadata)
            with native._read_scope():
                return N._json(native._manifest(invocation))

    def bound(self, invocation):
        with self.store._read_scope(), self.store._segment(invocation) as view:
            return view._owner.value['representation_profile'], view._owner.value['metadata']

    def test_oversized_root_round_trips_with_the_native_manifest_identity(self):
        metadata = root_metadata()
        self.assertGreater(len(N._json(metadata)), 330_000)
        invocation = metadata['key']
        self.store.put(invocation, arrays(), metadata)
        profile, bound = self.bound(invocation)
        self.assertEqual(profile, CRS.EXTERNAL_PROFILE)
        self.assertEqual(set(bound['external']), CRS.EXTERNAL_FIELDS)
        self.assertLessEqual(len(canonical(bound)), ROOT_METADATA_MAX)
        self.assertEqual(self.store.metadata(invocation), N._parse(N._json(metadata)))
        rebuilt = N._json(self.store._manifest(invocation))
        self.assertEqual(rebuilt, self.native_manifest(invocation, arrays(), metadata))
        got = self.store.get(invocation)
        self.assertTrue(all(np.array_equal(got[k], v) for k, v in arrays().items()))
        del got

    def test_small_root_keeps_the_unchanged_v1_representation(self):
        metadata = {'kind': 'root', 'sequence': 0, 'funding': {'small': True}}
        self.store.put(key('small'), arrays(), metadata)
        profile, bound = self.bound(key('small'))
        self.assertEqual(profile, CRS.PROFILE)
        self.assertNotIn('external', bound)
        self.assertEqual(self.store.metadata(key('small')), metadata)

    def test_other_oversized_metadata_is_still_refused(self):
        before = self.store.candidate.local_statistics()
        for metadata in (root_metadata(kind='successor'), dict(root_metadata(), state={'big': 'x'*70_000}),
                         {'kind': 'root', 'other': 'x'*70_000}):
            with self.assertRaisesRegex(StoreError, 'compact record references required'):
                self.store.put(key('refused'), arrays(), metadata)
        self.assertEqual(self.store.candidate.local_statistics(), before)

    def test_idempotent_put_reuses_and_a_changed_root_conflicts(self):
        metadata = root_metadata()
        self.store.put(metadata['key'], arrays(), metadata)
        self.store.put(metadata['key'], arrays(), metadata)
        self.assertEqual(self.store.statistics()['operations']['reused_invocations'], 1)
        changed = root_metadata()
        changed['funding']['rows'][0]['value'] = 7.0
        with self.assertRaises(StoreConflict):
            self.store.put(metadata['key'], arrays(), changed)

    def test_a_changed_external_value_fails_the_manifest_identity(self):
        metadata = root_metadata()
        self.store.put(metadata['key'], arrays(), metadata)
        original = CRS.CompactRestartStore._external_field

        def altered(store, wire):
            value = original(store, wire)
            if value.get('schema') == 'synthetic.funding.v1':
                value['rows'][3]['count'] += 1
            return value
        CRS.CompactRestartStore._external_field = altered
        try:
            with self.assertRaisesRegex(ContractError, 'reconstructed native manifest identity differs'):
                self.store.metadata(metadata['key'])
        finally:
            CRS.CompactRestartStore._external_field = original

    def test_a_reader_without_the_v2_profile_refuses(self):
        metadata = root_metadata()
        self.store.put(metadata['key'], arrays(), metadata)
        saved = CRS.EXTERNAL_PROFILE
        CRS.EXTERNAL_PROFILE = 'atlas.restart-native-arrays.v2-unknown'
        try:
            with self.assertRaisesRegex(ContractError, 'restart snapshot binding differs'):
                self.store.metadata(metadata['key'])
        finally:
            CRS.EXTERNAL_PROFILE = saved

    def test_cancelled_root_put_leaves_no_snapshot_or_field_record(self):
        metadata = root_metadata()
        before = self.store.candidate.local_statistics()
        cancel = threading.Event()
        original = CRS.CompactRestartStore._publish_field
        calls = []

        def cancelling(store, candidate, value, token):
            calls.append(1)
            if len(calls) == 2:
                cancel.set()
            return original(store, candidate, value, token)
        CRS.CompactRestartStore._publish_field = cancelling
        try:
            with self.assertRaises(Exception) as caught:
                self.store.put(metadata['key'], arrays(), metadata, cancel=cancel)
        finally:
            CRS.CompactRestartStore._publish_field = original
        self.assertIn('cancel', str(caught.exception).lower())
        caught = None
        gc.collect()
        self.assertFalse(self.store.contains(metadata['key']))
        self.assertEqual(self.store.candidate.local_statistics()['manifests'], before['manifests'])

    def manifest_failure(self, invocation, segment=None):
        """The _manifest error when a refusal is raised while a child borrow of the view is live."""
        original_build, original_segment = CRS.CompactRestartStore._manifest_from_segment, CRS.CompactRestartStore._segment

        def refusing(store, name, view):
            held = view._owner.retain()   # still borrowed when the refusal is raised  # noqa: F841
            raise ContractError('synthetic chunk checksum refusal')
        CRS.CompactRestartStore._manifest_from_segment = refusing
        if segment is not None:
            CRS.CompactRestartStore._segment = segment
        try:
            with self.assertRaises(BaseException) as caught:
                with self.store._read_scope(), self.store._workspace(8 << 20):
                    self.store._manifest(invocation)
        finally:
            CRS.CompactRestartStore._manifest_from_segment = original_build
            CRS.CompactRestartStore._segment = original_segment
        error, chain = caught.exception, []
        while error is not None and len(chain) < 16:
            chain.append(error)
            error = error.__context__
        result = [(type(item).__name__, str(item)) for item in chain]
        for item in chain:
            traceback.clear_frames(item.__traceback__)
            item.__traceback__ = None
        return result

    def test_a_refusal_inside_a_segment_block_is_not_masked(self):
        """_segment closes the view only after success (16 Oct, storage chat's find)."""
        metadata = {'kind': 'root', 'sequence': 0}
        self.store.put(key('masked'), arrays(), metadata)
        self.assertEqual(self.manifest_failure(key('masked')),
                         [('ContractError', 'synthetic chunk checksum refusal')])

        @contextmanager
        def old_segment(store, invocation):  # the pre-fix body: close in ``finally``
            view = SegmentBackend().open(store.resolver, store._alias(invocation), scope=store.scope)
            try:
                yield view
            finally:
                view.close()
        masked = self.manifest_failure(key('masked'), segment=old_segment)
        self.assertEqual(masked[0], ('RuntimeError', 'owner has live child borrows'))
        self.assertEqual(masked[-1], ('ContractError', 'synthetic chunk checksum refusal'))

    def test_sealed_root_rebuilds_in_a_fresh_reader_process(self):
        metadata = root_metadata()
        invocation = metadata['key']
        self.store.put(invocation, arrays(), metadata)
        self.store.seal_and_promote(invocation)
        expected = self.root/'expected.json'
        expected.write_bytes(N._json(metadata))
        result = subprocess.run([sys.executable, '-B', str(Path(__file__)), '--child',
                                 str(self.root/'catalog.json'), invocation, str(expected)],
                                capture_output=True, text=True, timeout=300, check=False)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1])['status'], 'PASS')


def child(catalog, invocation, expected):
    budget = WorkBudget(512 << 20)
    scope = create_retained_scope(budget, process_epoch='step9-root-metadata-cold-reader')
    with CRS.CompactRestartStore.open_catalog(catalog, scope=scope) as store:
        assert store.readonly
        assert store.metadata(invocation) == N._parse(Path(expected).read_bytes())
        got = store.get(invocation)
        assert all(np.array_equal(got[k], v) for k, v in arrays().items())
        del got
    gc.collect()
    scope.close()
    assert budget.reserved_bytes == 0
    print(json.dumps({'status': 'PASS', 'final_reserved_bytes': budget.reserved_bytes}))


if __name__ == '__main__':
    if sys.argv[1:2] == ['--child']:
        child(*sys.argv[2:5])
    else:
        unittest.main()
