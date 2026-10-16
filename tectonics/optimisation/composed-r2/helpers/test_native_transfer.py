"""Tiny actual-native tests on a temporary, explicitly patched successor.

No real checkpoint, historical reader, store, funding call, simulation or
initial_state call. Historical descriptors here are synthetic fixture data;
only those descriptors receive a deliberately different execution string.
The actually executing temporary package reports its own real source identity.
"""
from copy import deepcopy
import gc
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

import native_transfer as N


HERE = Path(__file__).resolve().parent
BASE = HERE.parent/'runtime-integration-r1'/'runtime-src'/'atlas_tectonics'
HEAT_TESTS = HERE.parents[2]/'heat-repair-20261007'/'source'/'tectonics'/'tests'
_temporary = None


def _historical_fixture_in_original_runtime():
    """Separate-process actual producer; its runtime identity is never changed."""
    integration = HERE.parent/'runtime-integration-r1'
    sys.path[:0] = [str(BASE.parent), str(integration/'ram'), str(integration/'helpers'),
                   str(HEAT_TESTS.parents[2]), str(HEAT_TESTS)]
    fixture = importlib.import_module('test_i04_regional_owner')
    collar_module = importlib.import_module('atlas_tectonics.regional_collar3d')
    snapshot = importlib.import_module('atlas_tectonics.regional_execution').RegionalMechanicalSnapshot
    budget = importlib.import_module('atlas_tectonics.resources').WorkBudget(256 << 20)
    source = fixture.physical_source(budget)
    volume_map = fixture.physical_map(source, budget)
    with fixture.prepare(source[4], budget) as native:
        with collar_module.PreparedRegionalCollar3D(native, volume_map, ((0, 0),)*3,
                budget=budget, mechanics_scope='complete-grid') as collar:
            with budget.reserve(1 << 20, category='tiny-producer-fixture'):
                mass = np.full(native.cells, native._mass)
                arrays = dict(component_mass_kg=np.stack((mass*.75, mass*.25)),
                    enthalpy_j=mass*1.5*native._material.heat_capacity_j_kg_k,
                    material_quadrature_m3=mass/native._material.density_kg_m3,
                    **{'tracer:damage': mass*0., 'tracer:accumulated_strain_ii': mass*.375,
                       'tracer:source_kappa': mass*.75, 'tracer:radial_plastic_kappa': mass*.125,
                       'tracer:formation': mass*7.})
                state = snapshot(dict(schema='atlas.regional-evolution3d-state.v1',
                    plan_id=native.plan_id, frame_id=native._frame, vertical_datum=native._datum,
                    time_s=12.5, source='fixture:actual-original-build', parent_state_id='b'*64,
                    inventory='reference mass and sensible enthalpy m*cp*T',
                    histories='mass-weighted scalar fields; no elastic tensor or free-surface state'), arrays)
                collar_state = collar_module.RegionalCollarState(snapshot(dict(
                    schema='atlas.regional-collar-fields.v1', plan_id=collar.plan_id,
                    time_s=12.5, source_id='fixture:source-funding', parent_id='c'*64), arrays), state)
                # Producer really validates its own endpoint, without stepping it.
                native._fields(state)
                collar._fields(collar_state)
                print(json.dumps(dict(historical_graph=N.current_plan_graph(native, collar),
                    historical_native=state.descriptor(), historical_native_id=state.result_id,
                    historical_collar=collar_state.record(), arrays={k: v.tolist() for k, v in arrays.items()},
                    origin=dict(producer_receipt_sha256='d'*64, store_token_sha256='e'*64,
                                endpoint_lineage_sha256='f'*64)), allow_nan=False))


def setUpModule():
    global _temporary, F, C, Snapshot, WorkBudget, TectonicsError
    if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
        raise RuntimeError('run in a clean process; never replace a loaded native runtime')
    _temporary = tempfile.TemporaryDirectory(prefix='native-transfer-fixture-', dir=HERE)
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    target = package/'regional_execution.py'
    target.write_text(N.retained_snapshot_source(target.read_text(encoding='utf-8')), encoding='utf-8')
    integration = HERE.parent/'runtime-integration-r1'
    sys.path[:0] = [str(Path(_temporary.name)), str(integration/'ram'),
                   str(integration/'helpers'), str(HEAT_TESTS.parents[2]), str(HEAT_TESTS)]
    F = importlib.import_module('test_i04_regional_owner')
    C = importlib.import_module('atlas_tectonics.regional_collar3d')
    Snapshot = importlib.import_module('atlas_tectonics.regional_execution').RegionalMechanicalSnapshot
    WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
    TectonicsError = importlib.import_module('atlas_tectonics._validation').TectonicsError


def tearDownModule():
    if _temporary is not None:
        assert Path(_temporary.name).resolve().parent == HERE
        _temporary.cleanup()


def rehash_graph(graph):
    for name in ('native_transport', 'native_heat', 'collar_transport', 'collar_heat'):
        graph[name]['plan_id'] = N._hash(graph[name]['definition'])
    graph['native']['definition']['transport_plan_id'] = graph['native_transport']['plan_id']
    graph['native']['plan_id'] = N._hash(graph['native']['definition'])
    collar = graph['collar']['definition']
    collar['native_plan_id'] = graph['native']['plan_id']
    collar['transport_plan_id'] = graph['collar_transport']['plan_id']
    collar['heat_plan'] = deepcopy(graph['collar_heat']['definition'])
    graph['collar']['plan_id'] = N._hash(collar)


class NativeTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.budget = WorkBudget(256 << 20)
        cls.fixture_guard = cls.budget.reserve(1 << 20, category='tiny-transfer-fixture-inputs')
        cls.fixture_guard.__enter__()
        cls.source = F.physical_source(cls.budget)
        cls.volume_map = F.physical_map(cls.source, cls.budget)
        # Actual native plans, geometry map and collar. No owner constructor,
        # initial funding, old reader or initial_state path is invoked.
        cls.native = F.prepare(cls.source[4], cls.budget)
        cls.collar = C.PreparedRegionalCollar3D(cls.native, cls.volume_map,
            ((0, 0),)*3, budget=cls.budget, mechanics_scope='complete-grid')
        cls.current = N.current_plan_graph(cls.native, cls.collar)
        cls.old = deepcopy(cls.current)
        for name in N._NODES:
            if name != 'collar':
                cls.old[name]['definition']['execution'] = 'a'*64
        rehash_graph(cls.old)

    @classmethod
    def tearDownClass(cls):
        cls.collar.close()
        cls.native.close()
        cls.source = cls.volume_map = None
        cls.fixture_guard.__exit__(None, None, None)
        gc.collect()

    def setUp(self):
        gc.collect()
        self.baseline = self.budget.reserved_bytes
        mass = np.full(self.native.cells, self.native._mass)
        self.arrays = dict(component_mass_kg=np.stack((mass*.75, mass*.25)),
            enthalpy_j=mass*1.5*self.native._material.heat_capacity_j_kg_k,
            material_quadrature_m3=mass/self.native._material.density_kg_m3,
            **{'tracer:damage': mass*0., 'tracer:accumulated_strain_ii': mass*.375,
               'tracer:source_kappa': mass*.75, 'tracer:radial_plastic_kappa': mass*.125,
               'tracer:formation': mass*7.})
        self.native_meta = dict(schema='atlas.regional-evolution3d-state.v1',
            plan_id=self.old['native']['plan_id'], frame_id=self.native._frame,
            vertical_datum=self.native._datum, time_s=12.5, source='fixture:historical-source',
            parent_state_id='b'*64, inventory='reference mass and sensible enthalpy m*cp*T',
            histories='mass-weighted scalar fields; no elastic tensor or free-surface state')
        self.field_meta = dict(schema='atlas.regional-collar-fields.v1',
            plan_id=self.old['collar']['plan_id'], source_id='fixture:original-funding',
            parent_id='c'*64, time_s=12.5)
        self.rebind()

    def rebind(self):
        state = Snapshot(self.native_meta, self.arrays)
        collar = C.RegionalCollarState(Snapshot(self.field_meta, self.arrays), state)
        self.arguments = dict(native=self.native, collar=self.collar, historical_graph=deepcopy(self.old),
            historical_native=state.descriptor(), historical_native_id=state.result_id,
            native_arrays={k: state.array(k) for k in state.array_names},
            historical_collar=collar.record(), collar_arrays=collar.arrays(),
            origin=dict(producer_receipt_sha256='d'*64, store_token_sha256='e'*64,
                        endpoint_lineage_sha256='f'*64))

    def tearDown(self):
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_complete_graph_contract_and_no_blanket_removal(self):
        comparison = N.compare_scientific_contract(self.old, self.current)
        same = N.compare_scientific_contract(self.current, self.current)
        self.assertEqual(comparison['scientific_contract_id'], same['scientific_contract_id'])
        self.assertNotEqual(comparison['producer_execution'], comparison['reader_execution'])
        for name in N._NODES:
            changed = deepcopy(self.old)
            changed[name]['definition']['unrecognised_future_physics'] = False
            rehash_graph(changed)
            with self.subTest(node=name), self.assertRaises(N.TransferRefused):
                N.compare_scientific_contract(changed, self.current)
        for path in (('native', 'material', 'density_kg_m3'),
                     ('native', 'rheology', 'source'), ('collar', 'embedding', 'future')):
            changed = deepcopy(self.old)
            changed[path[0]]['definition'][path[1]][path[2]] = 'different'
            rehash_graph(changed)
            with self.subTest(path=path), self.assertRaises(N.TransferRefused):
                N.compare_scientific_contract(changed, self.current)
        changed = deepcopy(self.old)
        changed['native']['definition']['material']['execution'] = 'do-not-strip-this'
        rehash_graph(changed)
        with self.assertRaises(N.TransferRefused):
            N.compare_scientific_contract(changed, self.current)

    def test_actual_two_build_separate_process_transfer(self):
        process = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--fixture-producer'],
                                 check=True, capture_output=True, text=True, timeout=60)
        evidence = json.loads(process.stdout)
        arrays = {k: np.asarray(v, dtype=np.float64) for k, v in evidence.pop('arrays').items()}
        self.assertNotEqual(evidence['historical_graph']['native']['definition']['execution'],
                            self.current['native']['definition']['execution'])
        arguments = dict(evidence, native=self.native, collar=self.collar,
                         native_arrays=arrays, collar_arrays=arrays)
        with N.admit_migrated_native_collar(**arguments) as lease:
            owned = lease.adopt()
        result = owned.state
        record = owned.record()
        payload = result.fields.nbytes+result.native_state.nbytes+len(owned._record)
        count = len(result.fields.array_names)+len(result.native_state.array_names)
        dimensions = sum(result.fields.array(k).ndim+result.native_state.array(k).ndim
                         for k in result.fields.array_names)
        self.assertEqual(owned.retained_bytes, payload+4096+1024*count+256*dimensions)
        self.assertEqual(self.budget.reserved_bytes-self.baseline, owned.retained_bytes)
        self.assertEqual(self.budget.statistics()['categories'].get('native-collar-transfer-scratch', 0), 0)
        print(json.dumps(dict(tiny_transfer_measurement=dict(array_bytes=sum(
            result.fields.array(k).nbytes+result.native_state.array(k).nbytes for k in result.fields.array_names),
            snapshot_and_provenance_bytes=payload, retained_bytes=owned.retained_bytes))))
        self.assertEqual(record['input']['historical_plan_graph'], evidence['historical_graph'])
        self.assertEqual(record['input']['current_plan_graph'], self.current)
        self.assertEqual(record['input']['compatibility']['scientific_contract_id'],
                         N.compare_scientific_contract(self.current, self.current)['scientific_contract_id'])
        self.assertEqual(owned.state.native_state.array('tracer:radial_plastic_kappa').tobytes(),
                         arrays['tracer:radial_plastic_kappa'].tobytes())
        del owned, record, result

    def test_preserves_every_byte_time_history_and_dual_provenance(self):
        before = deepcopy(self.arguments['historical_collar'])
        execution_before = self.native._context.identity
        with N.admit_migrated_native_collar(**self.arguments) as lease:
            self.assertEqual(type(lease.state), C.RegionalCollarState)
            owned = lease.adopt()
            with self.assertRaises(N.TransferRefused):
                lease.adopt()
        result = owned.state
        record = owned.record()
        for name, original in self.arguments['native_arrays'].items():
            self.assertEqual(result.native_state.array(name).tobytes(), original.tobytes())
            self.assertEqual(result.fields.array(name).tobytes(), original.tobytes())
            self.assertFalse(result.native_state.array(name).flags.writeable)
        self.assertEqual(result.native_state.descriptor()['time_s'], 12.5)
        self.assertEqual(result.fields.descriptor()['time_s'], 12.5)
        self.assertEqual(result.native_state.descriptor()['parent_state_id'], self.arguments['historical_native_id'])
        self.assertEqual(result.fields.descriptor()['parent_id'], before['result_id'])
        self.assertNotEqual(result.result_id, before['result_id'])
        self.assertEqual(record['input']['historical_collar'], before)
        self.assertEqual(record['input']['historical_native']['parent_state_id'], 'b'*64)
        self.assertEqual(record['input']['historical_collar']['fields']['source_id'], 'fixture:original-funding')
        self.assertFalse(record['funding_debit_applied'])
        self.assertFalse(record['scientific_acceptance'])
        self.assertFalse(record['continuation_authorised'])
        self.assertEqual(execution_before, self.native._context.identity)
        self.assertEqual(self.native.statistics()['accepted_intervals'], 0)
        self.assertEqual(self.native.statistics()['mechanical_preparations'], 0)
        self.assertEqual(self.native.statistics()['heat']['advances'], 0)
        self.assertEqual(N.current_plan_graph(self.native, self.collar), self.current)
        self.assertEqual(hashlib.sha256(N._json(record)).hexdigest(), owned.transfer_id)
        del result, owned, record

    def test_ordinary_restore_remains_strict_and_ordinary_snapshot_ids_unchanged(self):
        with self.assertRaisesRegex(TectonicsError, 'another plan'):
            self.collar.restore(self.arguments['historical_collar'], self.arguments['collar_arrays'])
        ordinary = Snapshot(self.native_meta, self.arrays)
        allocation = N._Allocation(self.budget, 1 << 16)
        retained = Snapshot(self.native_meta, self.arrays, retained_owner=allocation)
        self.assertEqual(ordinary.result_id, retained.result_id)
        self.assertEqual(ordinary.descriptor(), retained.descriptor())
        self.assertEqual(ordinary.nbytes, retained.nbytes)
        for name in ordinary.array_names:
            self.assertEqual(ordinary.array(name).tobytes(), retained.array(name).tobytes())
        del allocation, retained, ordinary

    def test_escaped_array_and_metadata_buffer_keep_allocation_after_close(self):
        lease = N.admit_migrated_native_collar(**self.arguments)
        with self.assertRaises(N.TransferRefused):
            lease.state
        with lease:
            escaped = lease.state.native_state.array('enthalpy_j')[:, :, 1:]
            raw_metadata = lease.state.fields._metadata
        del lease
        gc.collect()
        self.assertGreater(self.budget.reserved_bytes, self.baseline)
        self.assertEqual(self.budget.statistics()['categories'].get('native-collar-transfer-scratch', 0), 0)
        self.assertFalse(escaped.flags.writeable)
        del escaped
        gc.collect()
        self.assertGreater(self.budget.reserved_bytes, self.baseline)
        del raw_metadata
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_held_exception_keeps_partial_copies_charged(self):
        self.arrays['tracer:accumulated_strain_ii'] *= -1
        self.rebind()  # Valid byte identity, physically invalid carried history.
        held = None
        try:
            N.admit_migrated_native_collar(**self.arguments)
        except TectonicsError as error:
            held = error
        self.assertIsNotNone(held)
        gc.collect()
        self.assertGreater(self.budget.reserved_bytes, self.baseline)
        self.assertGreater(self.budget.statistics()['categories'].get('native-collar-transfer-scratch', 0), 0)
        held = None
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_missing_history_dtype_byte_and_metadata_mutations_refused(self):
        cases = []
        for name in N._REQUIRED_ARRAYS:
            item = dict(self.arguments, native_arrays=dict(self.arguments['native_arrays']))
            del item['native_arrays'][name]
            cases.append(item)
        item = dict(self.arguments, native_arrays=dict(self.arguments['native_arrays']))
        item['native_arrays']['enthalpy_j'] = item['native_arrays']['enthalpy_j'].astype(np.float32)
        cases.append(item)
        item = dict(self.arguments, native_arrays=dict(self.arguments['native_arrays']))
        item['native_arrays']['enthalpy_j'] = item['native_arrays']['enthalpy_j'].copy()
        item['native_arrays']['enthalpy_j'].flat[0] += .01
        cases.append(item)
        item = dict(self.arguments, historical_native=dict(self.arguments['historical_native'], time_s=13.))
        cases.append(item)
        item = dict(self.arguments, historical_collar=dict(self.arguments['historical_collar'], exterior_heat={}))
        cases.append(item)
        item = dict(self.arguments, origin=dict(self.arguments['origin'], store_token_sha256='missing'))
        cases.append(item)
        for i, item in enumerate(cases):
            with self.subTest(case=i), self.assertRaises(N.TransferRefused):
                N.admit_migrated_native_collar(**item)

    def test_actual_native_equation_and_collar_interior_gates(self):
        for field, multiplier in (('component_mass_kg', .5), ('enthalpy_j', 10.),
                                  ('tracer:damage', 1.)):
            previous = self.arrays[field].copy()
            self.arrays[field] = (np.ones_like(previous) if field == 'tracer:damage' else previous*multiplier)
            self.rebind()
            with self.subTest(field=field), self.assertRaises(TectonicsError):
                N.admit_migrated_native_collar(**self.arguments)
            self.arrays[field] = previous
        self.rebind()
        item = dict(self.arguments, collar_arrays=dict(self.arguments['collar_arrays']))
        item['collar_arrays']['tracer:formation'] = self.arrays['tracer:formation']*2
        fields = Snapshot(self.field_meta, item['collar_arrays'])
        native = Snapshot(self.native_meta, self.arrays)
        item['historical_collar'] = C.RegionalCollarState(fields, native).record()
        with self.assertRaisesRegex(TectonicsError, 'interior state disagree'):
            N.admit_migrated_native_collar(**item)

    def test_graph_wrong_schema_id_edge_and_execution_refused(self):
        cases = []
        for name in N._NODES:
            graph = deepcopy(self.old)
            graph[name]['definition']['schema'] = 'unknown.v2'
            rehash_graph(graph)
            cases.append(graph)
        graph = deepcopy(self.old)
        graph['native']['definition']['transport_plan_id'] = 'b'*64
        graph['native']['plan_id'] = N._hash(graph['native']['definition'])
        graph['collar']['definition']['native_plan_id'] = graph['native']['plan_id']
        graph['collar']['plan_id'] = N._hash(graph['collar']['definition'])
        cases.append(graph)
        graph = deepcopy(self.old)
        graph['native_heat']['definition']['execution'] = 'b'*64
        rehash_graph(graph)
        cases.append(graph)
        for graph in cases:
            with self.assertRaises(N.TransferRefused):
                N.compare_scientific_contract(graph, self.current)

    def test_budget_refusal_before_snapshot_copy_and_patch_fail_closed(self):
        remaining = self.budget.available_bytes
        with self.budget.reserve(remaining-1024, category='fixture-memory-pressure'):
            from atlas_tectonics.resources import MemoryLimitError
            with self.assertRaises(MemoryLimitError):
                N.admit_migrated_native_collar(**self.arguments)
        with self.assertRaises(N.TransferRefused):
            N.retained_snapshot_source('an unrelated constructor')
        source = (BASE/'regional_execution.py').read_text(encoding='utf-8')
        with self.assertRaises(N.TransferRefused):
            N.retained_snapshot_source(N.retained_snapshot_source(source))


if __name__ == '__main__':
    if sys.argv[1:] == ['--fixture-producer']:
        _historical_fixture_in_original_runtime()
    else:
        unittest.main(verbosity=2)
