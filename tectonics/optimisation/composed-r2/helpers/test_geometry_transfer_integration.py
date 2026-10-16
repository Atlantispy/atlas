"""Actual partition restore across a narrow, explicitly synthetic old parent.

The native/collar, funding and evolved spatial objects use their actual tiny
constructors/validators. Archived execution descriptors and geometry are
SYNTHETIC TEST INPUTS, not a historical-reader or scientific acceptance receipt.
No physical solve, initial_state, funding debit, workflow or real store is used.
Only the temporary successor package is patched, before any runtime import.
"""
from copy import deepcopy
from fractions import Fraction as Q
import gc
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import geometry_transfer as G
import native_transfer as N
import spatial_transfer as S
import test_native_transfer as TN
import test_spatial_transfer as TS


HERE = Path(__file__).resolve().parent
_temporary = None
_old_path = None


def setUpModule():
    global _temporary, _old_path, D, C, WorkBudget, VolumeError, MemoryLimitError
    if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
        raise RuntimeError('clean process required; no loaded runtime replacement')
    _temporary = tempfile.TemporaryDirectory(prefix='geometry-transfer-fixture-', dir=HERE)
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(TN.BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, patch in (('regional_execution.py', N.retained_snapshot_source),
                        ('integration_spatial_owner.py', S.spatial_owner_source),
                        ('integration_differential_geometry.py', G.transform)):
        path = package/name
        path.write_text(patch(path.read_text(encoding='utf-8')), encoding='utf-8')
    integration = HERE.parent/'runtime-integration-r1'
    _old_path = list(sys.path)
    sys.path[:0] = [str(Path(_temporary.name)), str(integration/'ram'), str(integration/'helpers'),
                   str(TN.HEAT_TESTS.parents[2]), str(TN.HEAT_TESTS)]
    D = importlib.import_module('atlas_tectonics.integration_differential_geometry')
    C = importlib.import_module('atlas_tectonics.regional_collar3d')
    resources = importlib.import_module('atlas_tectonics.resources')
    WorkBudget, MemoryLimitError = resources.WorkBudget, resources.MemoryLimitError
    VolumeError = importlib.import_module('atlas_tectonics.integration_volume').VolumeError
    # Reuse only existing fixture builders, not their suite or module setup.
    # These assignments populate test-helper globals, never runtime identities.
    TS.F = importlib.import_module('test_i04_regional_owner')
    TS.C = C
    TS.P = importlib.import_module('atlas_tectonics.integration_spatial_owner')
    TS.Snapshot = importlib.import_module('atlas_tectonics.regional_execution').RegionalMechanicalSnapshot
    TS.WorkBudget = WorkBudget
    TS.Registry = importlib.import_module('atlas_tectonics.integration_regional_inventory').ComponentRegistry
    TS.enc = importlib.import_module('atlas_tectonics.integration_mimetic_heat')._enc
    TS.TectonicsError = importlib.import_module('atlas_tectonics._validation').TectonicsError


def tearDownModule():
    if _old_path is not None:
        sys.path[:] = _old_path
    if _temporary is not None:
        assert Path(_temporary.name).resolve().parent == HERE
        _temporary.cleanup()


def synthetic_geometry_and_partition(*, spatial, collar, native_transfer, budget):
    """Issue tiny geometry-shaped test operands, not geometrical proof.

    The partition is deliberately historical: its collar ID stays the old ID.
    Supporting payload bytes, IDs, source and funding must survive restoration.
    ``_issue`` here is a fixture issuer, not an acceptance authority.
    """
    evidence = native_transfer.record()
    endpoint = spatial.state.record()
    body = dict(schema=D.SCHEMA, method='coaxial-physical-ownership-fan-v1', geometry_only=True,
        fixture='SYNTHETIC ARCHIVED GEOMETRY; NOT SCIENTIFIC ACCEPTANCE',
        start_time_s=TS.enc(12), end_time_s=TS.enc(Q(25, 2)),
        parent_network_id='7'*64, endpoint_network_id='8'*64,
        trajectory_id=endpoint['trajectory_id'], prior_trajectory_id='9'*64,
        start_support_id='0'*64, end_support_id=endpoint['support_id'])
    geometry = D._issue(D.DifferentialInterval, body, budget)
    supports = [dict(schema='fixture.synthetic-differential-support.v1',
        fixture='NOT A GEOMETRICAL CERTIFICATE', source=spatial.funding.descriptor()['source'],
        funding_id=spatial.funding.funding_id, source_key=list(key),
        stable_original_support_payload=dict(index=index, exact_fraction=TS.enc(Q(index+1, 7))))
        for index, key in enumerate(collar._registry.source_keys)]
    partition = dict(schema='atlas.differential-partition.v1', scope='physical-interval',
        source=spatial.funding.descriptor()['source'], funding_id=spatial.funding.funding_id,
        collar_plan_id=evidence['input']['historical_plan_graph']['collar']['plan_id'],
        interval_id=geometry.interval_id, parent_network_id=body['parent_network_id'],
        endpoint_network_id=body['endpoint_network_id'], trajectory_id=body['trajectory_id'],
        start_time_s=body['start_time_s'], end_time_s=body['end_time_s'],
        support_ids=[D._record_hash(row) for row in supports])
    return geometry, dict(partition_id=D._record_hash(partition), **partition, supports=supports)


def rehash_partition(record):
    record['partition_id'] = D._record_hash({k: v for k, v in record.items()
                                           if k not in ('partition_id', 'supports')})
    return record


class GeometryTransferIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TS.SpatialTransferTests.setUpClass()
        cls.budget = TS.SpatialTransferTests.budget

    @classmethod
    def tearDownClass(cls):
        TS.SpatialTransferTests.tearDownClass()
        # Closed plans can still own geometry/registry references: release the
        # test owners before asserting the complete shared ledger is empty.
        TS.SpatialTransferTests.collar = TS.SpatialTransferTests.native = None
        TS.SpatialTransferTests.old = TS.SpatialTransferTests.current = None
        gc.collect()
        if cls.budget.reserved_bytes:
            raise AssertionError(cls.budget.statistics())

    def setUp(self):
        self.fixture = TS.SpatialTransferTests('test_old_root_restore_remains_strict')
        self.fixture.setUp()
        self.collar = self.fixture.collar
        with S.admit_migrated_spatial_owner(**self.fixture.args) as lease:
            self.spatial = lease.adopt()
        self.geometry, self.descriptor = synthetic_geometry_and_partition(
            spatial=self.spatial, collar=self.collar, native_transfer=self.fixture.native_owned,
            budget=self.budget)
        gc.collect()
        self.baseline = self.budget.reserved_bytes

    def tearDown(self):
        self.spatial.owner.close()
        self.spatial = self.geometry = self.descriptor = self.collar = None
        gc.collect()
        self.fixture.tearDown()
        self.fixture = None

    def bind(self, **changes):
        arguments = dict(native_transfer=self.fixture.native_owned,
            partition_descriptor=self.descriptor, geometry=self.geometry,
            funding=self.spatial.funding, collar=self.collar, budget=self.budget)
        return G.bind_parent_geometry(**dict(arguments, **changes))

    def restore(self, binding=None, **changes):
        arguments = dict(record=self.descriptor, funding=self.spatial.funding,
            collar=self.collar, geometry=self.geometry, budget=self.budget,
            _runtime_transfer=binding)
        return D.DifferentialPartition.restore(**dict(arguments, **changes))

    def test_actual_restore_retains_original_parent_ids_and_support_bytes(self):
        original = deepcopy(self.descriptor)
        binding = self.bind()
        restored = self.restore(binding)
        self.assertIs(type(restored), D.DifferentialPartition)
        self.assertEqual(restored.descriptor(), original)
        body = {k: v for k, v in original.items() if k not in ('partition_id', 'supports')}
        self.assertEqual(restored._json, D._encoded(body))
        self.assertEqual(restored.partition_id, original['partition_id'])
        self.assertEqual([support._json for support in restored.supports],
                         [D._encoded(row) for row in original['supports']])
        self.assertEqual([support.support_id for support in restored.supports], original['support_ids'])
        self.assertNotEqual(original['collar_plan_id'], self.collar.plan_id)
        native_record = self.fixture.native_owned.record()
        self.assertNotEqual(native_record['input']['historical_plan_graph']['native']['plan_id'],
                            self.collar._native.plan_id)
        self.assertEqual(self.spatial.funding.descriptor(), self.fixture.args['funding_record'])
        self.assertEqual(binding.record()['native_transfer_id'], self.fixture.native_owned.transfer_id)
        self.assertFalse(binding.record()['scientific_acceptance'])
        self.assertEqual(self.collar._native.statistics()['accepted_intervals'], 0)
        self.assertEqual(self.budget.statistics()['categories'].get('geometry-transfer-binding-scratch', 0), 0)
        del restored, binding
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_unbound_or_wrong_exact_parent_restore_is_refused(self):
        with self.assertRaises(VolumeError):
            self.restore()
        binding = self.bind()
        changes = []
        for name, value in (('source', dict(self.descriptor['source'], fixture='another-source')),
                            ('funding_id', '0'*64), ('collar_plan_id', '1'*64),
                            ('end_time_s', TS.enc(13)), ('interval_id', '2'*64),
                            ('trajectory_id', '3'*64), ('endpoint_network_id', '4'*64)):
            record = rehash_partition(dict(deepcopy(self.descriptor), **{name: value}))
            changes.append(record)
        record = deepcopy(self.descriptor)
        record['supports'][0]['stable_original_support_payload']['index'] += 1
        changes.append(record)
        record = deepcopy(self.descriptor)
        record['partition_id'] = '5'*64
        changes.append(record)
        for record in changes:
            with self.subTest(record=record['partition_id']):
                with self.assertRaises(VolumeError):
                    self.restore(binding, record=record)
        del binding

    def test_binding_refuses_rehashed_source_funding_clock_plan_and_partition(self):
        for name, value in (('source', dict(self.descriptor['source'], fixture='another-source')),
                            ('funding_id', '0'*64), ('collar_plan_id', '1'*64),
                            ('end_time_s', TS.enc(13)), ('interval_id', '2'*64),
                            ('trajectory_id', '3'*64), ('endpoint_network_id', '4'*64),
                            ('scope', 'initial-current')):
            changed = rehash_partition(dict(deepcopy(self.descriptor), **{name: value}))
            with self.subTest(field=name):
                with self.assertRaises(G.GeometryTransferRefused):
                    self.bind(partition_descriptor=changed)
        changed = deepcopy(self.descriptor)
        changed['supports'][0]['stable_original_support_payload']['index'] += 1
        with self.assertRaises(G.GeometryTransferRefused):
            self.bind(partition_descriptor=changed)
        with self.assertRaises(G.GeometryTransferRefused):
            self.bind(partition_descriptor=dict(self.descriptor, partition_id='0'*64))
        # Rehash BOTH geometry and partition at a different time. The current
        # migrated native/collar time is still 12.5 and must independently bind.
        moved = D._issue(D.DifferentialInterval, dict(self.geometry.record(), end_time_s=TS.enc(13)), self.budget)
        changed = rehash_partition(dict(self.descriptor, interval_id=moved.interval_id, end_time_s=TS.enc(13)))
        with self.assertRaises(G.GeometryTransferRefused):
            self.bind(geometry=moved, partition_descriptor=changed)
        del moved

    def test_binding_requires_actual_native_transfer_actual_plan_and_shared_owners(self):
        with self.assertRaises(G.GeometryTransferRefused):
            self.bind(native_transfer=object())
        # Deliberately inconsistent provenance in a NEGATIVE fixture only;
        # actual native/collar execution identities and states are untouched.
        bad = self.fixture.native_owned.record()
        bad['current_collar']['fields']['time_s'] = 99.
        bad_transfer = N.OwnedMigratedNativeCollar(self.fixture.native_owned.state, N._json(bad))
        with self.assertRaises(G.GeometryTransferRefused):
            self.bind(native_transfer=bad_transfer)
        del bad_transfer
        with self.assertRaises(G.GeometryTransferRefused):
            self.bind(budget=WorkBudget(1 << 20))
        # A genuinely prepared different plan (no component registry), not a
        # mutation or substitute identity on the actually executing plan.
        other = C.PreparedRegionalCollar3D(self.collar._native, self.collar._map, ((0, 0),)*3,
            budget=self.budget, mechanics_scope='complete-grid')
        self.assertNotEqual(other.plan_id, self.collar.plan_id)
        try:
            with self.assertRaises(G.GeometryTransferRefused):
                self.bind(collar=other)
        finally:
            other.close()
        del other
        binding = self.bind()
        with S.admit_migrated_spatial_owner(**self.fixture.args) as lease:
            separate = lease.adopt()
        self.assertEqual(separate.funding.funding_id, self.spatial.funding.funding_id)
        try:
            with self.assertRaises(VolumeError):
                self.restore(binding, funding=separate.funding)
            with self.assertRaises(VolumeError):
                self.restore(binding, budget=WorkBudget(1 << 20))
        finally:
            separate.owner.close()
        del separate, binding

    def test_retained_binding_is_immutable_and_escaped_record_retains_exact_charge(self):
        binding = self.bind()
        expected = len(binding._record)+4096
        self.assertEqual(self.budget.reserved_bytes-self.baseline, expected)
        with self.assertRaises(G.GeometryTransferRefused):
            binding._funding = None
        escaped = binding._record
        del binding
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes-self.baseline, expected)
        self.assertEqual(self.budget.statistics()['categories'].get('geometry-transfer-binding-scratch', 0), 0)
        del escaped
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_held_binding_error_retains_scratch_until_its_frame_is_released(self):
        held = None
        try:
            self.bind(partition_descriptor=dict(self.descriptor, partition_id='0'*64))
        except G.GeometryTransferRefused as error:
            held = error
        self.assertIsNotNone(held)
        gc.collect()
        self.assertGreater(self.budget.statistics()['categories'].get('geometry-transfer-binding-scratch', 0), 0)
        self.assertGreaterEqual(self.budget.statistics()['categories'].get('geometry-transfer-parent-scratch', 0),
            G._json_decode_bytes(self.spatial.funding._snapshot._metadata)
            +G._json_decode_bytes(self.geometry._json))
        held = None
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_budget_pressure_and_source_transform_fail_closed(self):
        with self.budget.reserve(self.budget.available_bytes-1024, category='fixture-pressure'):
            with self.assertRaises(MemoryLimitError):
                self.bind()
        source = (TN.BASE/'integration_differential_geometry.py').read_text(encoding='utf-8')
        with self.assertRaises(G.GeometryTransferRefused):
            G.transform(G.transform(source))

    def test_decode_plan_and_field_work_is_admitted_before_use_and_not_retained(self):
        native = self.fixture.native_owned
        required = G._binding_scratch_bytes(native, self.collar)
        self.assertGreaterEqual(required, G._json_decode_bytes(native._record)
                                +G._plan_graph_scratch_bytes(self.collar))
        self.assertGreater(G._fields_scratch_bytes(self.collar, native.state),
                           max(native.state.fields.nbytes, native.state.native_state.nbytes))
        # Refusal is before native provenance decoding, not after construction
        # of an uncharged Python graph. No plan/context/state is monkeypatched.
        with self.budget.reserve(self.budget.available_bytes-required+1, category='fixture-pressure'):
            with mock.patch.object(N.OwnedMigratedNativeCollar, 'record',
                                   side_effect=AssertionError('unadmitted native JSON decode')) as decode:
                with self.assertRaises(MemoryLimitError):
                    self.bind()
                decode.assert_not_called()
        binding = self.bind()
        body = {k: v for k, v in self.descriptor.items() if k not in ('partition_id', 'supports')}
        required = G._matches_scratch_bytes(binding, body, self.collar)
        with self.budget.reserve(self.budget.available_bytes-required+1, category='fixture-pressure'):
            with mock.patch.object(N.OwnedMigratedNativeCollar, 'record',
                                   side_effect=AssertionError('unadmitted matching JSON decode')) as decode:
                with self.assertRaises(MemoryLimitError):
                    binding.matches(body, funding=self.spatial.funding, collar=self.collar, budget=self.budget)
                decode.assert_not_called()
        self.assertTrue(binding.matches(body, funding=self.spatial.funding, collar=self.collar, budget=self.budget))
        stats = self.budget.statistics()
        for category in ('binding', 'match', 'contract', 'fields', 'parent'):
            name = 'geometry-transfer-'+category+'-scratch'
            self.assertGreater(stats['category_peaks'][name], 0, name)
            self.assertEqual(stats['categories'].get(name, 0), 0, name)
        self.assertEqual(self.budget.reserved_bytes-self.baseline, len(binding._record)+4096)
        del binding
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_json_decode_capacity_counts_objects_not_punctuation_inside_strings(self):
        # A long textual annotation does not become an enormous object budget.
        plain = N._json(dict(value='x'*10000))
        punctuation = N._json(dict(value=','*10000))
        self.assertEqual(len(plain), len(punctuation))
        self.assertEqual(G._json_decode_bytes(plain), G._json_decode_bytes(punctuation))
        self.assertLess(G._json_decode_bytes(plain), 9*len(plain))
        # Escaped quotes/backslashes must not move punctuation outside a string.
        escaped = N._json({'a': 'a\\\",:[{b', 'b': ['z', 1]})
        decoded = __import__('json').loads(escaped)
        def retained_size(value):
            size = sys.getsizeof(value)
            if isinstance(value, dict):
                size += sum(retained_size(k)+retained_size(v) for k, v in value.items())
            elif isinstance(value, list):
                size += sum(retained_size(v) for v in value)
            return size
        self.assertGreater(G._json_decode_bytes(escaped), retained_size(decoded))

    def test_held_actual_field_validation_failure_retains_its_array_reservation(self):
        original = self.fixture.native_owned.state
        arrays = {name: original.native_state.array(name) for name in original.native_state.array_names}
        arrays['tracer:accumulated_strain_ii'] = arrays['tracer:accumulated_strain_ii'].copy()
        arrays['tracer:accumulated_strain_ii'].flat[0] = -1.
        invalid_native = TS.Snapshot(original.native_state.descriptor(), arrays)
        invalid = C.RegionalCollarState(original.fields, invalid_native)
        held = None
        try:
            G._validate_fields(self.collar, invalid, self.budget)
        except TS.TectonicsError as error:
            held = error
        self.assertIsNotNone(held)
        gc.collect()
        self.assertEqual(self.budget.statistics()['categories'].get('geometry-transfer-fields-scratch', 0),
                         G._fields_scratch_bytes(self.collar, invalid))
        held = None
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)


if __name__ == '__main__':
    unittest.main(verbosity=2)
