"""Changed ownership boundaries plus an actual native CompactMesh writer smoke.

No solve or real CONTROL invocation. Run in the pinned Atlas interpreter through
the authorised queue. The smoke uses synthetic scientific inputs and actual
native packing/row/support/WorkBudget/accessor APIs.
"""
import gc
from fractions import Fraction
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

import numpy as np
import psutil

HERE = Path(__file__).resolve().parent
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
LAYOUT = T / 'hs/lf3'
ARTIFACTS = HERE / 'ownership-test-artifacts'


def load_candidate(layout=LAYOUT):
    with patch.dict(os.environ, {'ATLAS_HS_DIR': str(T / 'hs')}):
        spec = importlib.util.spec_from_file_location('plan05_r13_ownership', HERE / 'ab_heat_r13.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    control = (layout / 'control.json').read_bytes()
    assert hashlib.sha256(control).hexdigest() == module.CONTROL_PINS[layout.name]
    sys.path[:0] = json.loads(control)['paths']
    return module, module._bind_observer_runtime(layout)


def disposition():
    return {'operations': [], 'secondary_failures': []}


def snapshot(error):
    return error.args, dict(error.__dict__), error.__traceback__, error.__cause__, error.__context__


def shared_frame():
    """Two different exceptions with the exact same completed frame object."""
    slot = {}
    try:
        raise RuntimeError('protected CONTROL')
    except RuntimeError as caught:
        control = caught
    try:
        raise ValueError('observer failure')
    except ValueError as caught:
        observer = caught
    return control, observer, slot


class ReportingFailure:
    def append(self, value):
        raise OSError('injected disposition append failure')


class Ownership(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.r = load_candidate()
        import mesh_tables
        cls.native = mesh_tables
        ARTIFACTS.mkdir(exist_ok=True)

    def setUp(self):
        self.budget = self.r.WorkBudget(256 << 20)

    def categories(self):
        return self.budget.statistics()['categories']

    def make_owner(self):
        allocation = self.native._Allocation(self.budget, 32768)
        return self.native.OwnedRow({'nested': [{'marker': 'native payload'}]}, allocation)

    def release(self, identity):
        result = self.m.release_retained_owner(identity, aliases_released=True)
        self.assertTrue(result['released'])
        self.assertEqual(self.categories().get('observer-d02', 0), 0)
        return result

    def test_plain_dictionary_owner_and_separate_nested_copy(self):
        source = {'nested': [{'marker': 'original'}]}
        found = {}
        def operation(arena):
            arena.prepare_owners(1)
            copied = arena.copy_owner(lambda: source)
            self.assertIsNot(copied, source)
            self.assertIsNot(copied['nested'], source['nested'])
            self.assertIsNot(copied['nested'][0], source['nested'][0])
            found['identity'] = arena.retain()
            found['copy'] = copied
        self.m._run_observer_operation(self.r, self.budget, operation, (), disposition(), 'copy')
        self.assertGreater(self.categories()['observer-d02'], 0)
        source['nested'][0]['marker'] = 'changed'
        self.assertEqual(found['copy']['nested'][0]['marker'], 'original')
        identity = found['identity']
        found.clear()
        self.release(identity)

    def test_native_payload_alias_requires_explicit_release(self):
        escaped = {}
        def operation(arena):
            arena.prepare_owners(1)
            owner = arena.acquire(self.make_owner)
            escaped['owner_id'] = arena.retain()
            escaped['payload'] = owner.value
        self.m._run_observer_operation(self.r, self.budget, operation, (), disposition(), 'alias')
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        with self.assertRaises(self.m.ObserverCleanupError):
            self.m.release_retained_owner(escaped['owner_id'])
        identity = escaped['owner_id']
        escaped.clear()
        self.release(identity)
        self.assertEqual(self.categories()['compact-mesh-owned'], 0)

    def test_actual_shared_frames_and_independent_traceback_survive_exception_death(self):
        control, observer, slot = shared_frame()
        before = snapshot(control)
        control_frames = {id(t.tb_frame) for t in (control.__traceback__,)}
        observer_frames = {id(t.tb_frame) for t in (observer.__traceback__,)}
        self.assertTrue(control_frames & observer_frames)
        independent_tb = observer.__traceback__
        escaped = {}
        def operation(arena):
            arena.prepare_owners(1)
            owner = arena.acquire(self.make_owner)
            slot['payload'] = owner.value
            escaped['id'] = arena.retain()
            raise observer
        try:
            self.m._run_observer_operation(
                self.r, self.budget, operation, (), disposition(), 'shared', protected=control)
        except ValueError as failure:
            self.assertIs(failure, observer)
            self.assertIs(self.m.retained_owner(escaped['id']).failure, failure)
        self.assertEqual(snapshot(control), before)
        observer = None
        gc.collect()
        self.assertIsNotNone(independent_tb)
        self.assertEqual(slot['payload']['nested'][0]['marker'], 'native payload')
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        self.assertGreater(self.categories()['observer-d02'], 0)
        identity = escaped['id']
        slot.clear()
        independent_tb = control = before = operation = None
        self.release(identity)
        self.assertEqual(self.categories()['compact-mesh-owned'], 0)

    def test_capacity_refuses_before_native_allocation(self):
        called = []
        def operation(arena):
            arena.prepare_owners(0)
            arena.acquire(lambda: called.append(True))
        with self.assertRaises(self.m.ObserverCaptureError) as caught:
            self.m._run_observer_operation(self.r, self.budget, operation, (), disposition(), 'cap')
        identity = caught.exception.retained_owner_id
        self.assertFalse(called)
        caught = None
        self.release(identity)

    def test_registration_failure_after_insert_retains_committed_owner(self):
        def operation(arena):
            arena.prepare_owners(1)
            arena.acquire(self.make_owner)
        with patch.object(self.m._ObserverArena, '_after_owner_registered',
                          side_effect=MemoryError('after committed insertion')):
            with self.assertRaises(MemoryError) as caught:
                self.m._run_observer_operation(self.r, self.budget, operation, (), disposition(), 'insert')
        identity = caught.exception.retained_owner_id
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        self.assertEqual(self.m.retained_owner(identity).owner_count, 1)
        caught = None
        self.release(identity)

    def test_partial_native_factory_failure_retains_traceback_backing(self):
        def factory():
            owner = self.make_owner()
            payload = owner.value  # noqa: F841 -- intentional traceback payload
            raise MemoryError('partial native factory allocation')
        def operation(arena):
            arena.prepare_owners(1)
            arena.acquire(factory)
        with self.assertRaises(MemoryError) as caught:
            self.m._run_observer_operation(self.r, self.budget, operation, (), disposition(), 'partial')
        identity = caught.exception.retained_owner_id
        arena = self.m.retained_owner(identity)
        # assertRaises consumes the original traceback and clears its frames.
        # Its local backing must have a separately retained concrete owner.
        self.assertIsNone(caught.exception.__traceback__)
        self.assertIsNotNone(arena.failure_traceback)
        self.assertTrue(arena.failure_roots_complete)
        self.assertTrue(any(isinstance(roots.get('owner'), self.native.OwnedRow)
                            for roots in arena.failure_local_roots))
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        caught = arena = None
        self.release(identity)
        self.assertEqual(self.categories()['compact-mesh-owned'], 0)

    def test_failure_snapshot_storage_fault_keeps_original_graph_and_primary(self):
        primary = MemoryError('partial native allocation')
        probe = {'arena': None}
        def factory():
            owner = self.make_owner()  # noqa: F841 -- unfinished factory owns this local
            raise primary
        def operation(arena):
            arena.prepare_owners(1)
            # Positive snapshot insertion fails after its local dict exists.
            arena.failure_local_roots = ReportingFailure()
            arena.acquire(factory)
        try:
            self.m._run_observer_operation(self.r, self.budget, operation, (),
                disposition(), 'snapshot-storage', callback_probe=probe)
        except BaseException as caught:
            self.assertIs(caught, primary)
        else:
            self.fail('Primary allocation failure was lost')
        arena = probe['arena']
        identity = id(arena)
        self.assertFalse(arena.failure_roots_complete)
        self.assertIsNotNone(arena.failure_traceback)
        self.assertIsInstance(arena.failure_snapshot_error, OSError)
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        report = self.m._observe_callback_release(probe)
        self.assertTrue(report['retained_funding'])
        self.assertTrue(report['preserve_failure_frames_until_release'])
        # Detachment is safe because the concrete owner separately holds the
        # traceback. Destructive frame clearing is forbidden in this state.
        primary.__traceback__ = None
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        primary = arena = operation = factory = None
        self.release(identity)
        self.assertEqual(self.categories()['compact-mesh-owned'], 0)

    def test_native_payload_hash_empty_multidimensional_and_contiguous_contract(self):
        for shape in ((0,), (0, 3), (2, 0, 4)):
            self.assertEqual(self.m._array_payload_sha(np.empty(shape, dtype=np.uint64)),
                             hashlib.sha256(b'').hexdigest())
        values = np.arange(24, dtype=np.int64).reshape(2, 3, 4)
        self.assertEqual(self.m._array_payload_sha(values),
                         hashlib.sha256(values.tobytes(order='C')).hexdigest())
        with self.assertRaises(TypeError):
            self.m._array_payload_sha(values[:, :, ::2])

    def test_failure_snapshot_admission_refusal_retains_native_backing(self):
        self.budget = self.r.WorkBudget(128 << 10)
        probe = {'arena': None}
        def operation(arena):
            arena.prepare_owners(1)
            def factory():
                owner = self.make_owner()  # noqa: F841 -- retained by failure-frame owner
                arena.reserve(self.budget.max_bytes - self.budget.reserved_bytes)
                arena.reserve(1)
            arena.acquire(factory)
        try:
            self.m._run_observer_operation(self.r, self.budget, operation, (),
                disposition(), 'snapshot-admission', callback_probe=probe)
        except self.r.MemoryLimitError as caught:
            self.assertIs(caught, probe['arena'].failure)
            primary = caught
        else:
            self.fail('Native refusal was lost')
        arena = probe['arena']
        identity = id(arena)
        self.assertIsInstance(arena.failure_snapshot_error, self.r.MemoryLimitError)
        self.assertFalse(arena.failure_roots_complete)
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        self.assertTrue(self.m._observe_callback_release(probe)['retained_funding'])
        primary.__traceback__ = None
        primary = arena = operation = None
        self.release(identity)
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_module_exec_frame_falls_back_before_local_snapshot(self):
        primary = MemoryError('native allocation inside exec')
        probe = {'arena': None}
        namespace = {'make_owner': self.make_owner, 'primary': primary}
        def operation(arena):
            exec('owner = make_owner()\nraise primary', namespace)
        try:
            self.m._run_observer_operation(self.r, self.budget, operation, (),
                disposition(), 'module-exec', callback_probe=probe)
        except BaseException as caught:
            self.assertIs(caught, primary)
        else:
            self.fail('Primary exec failure was lost')
        arena = probe['arena']
        identity = id(arena)
        self.assertFalse(arena.failure_roots_complete)
        self.assertIn('module/exec', str(arena.failure_snapshot_error))
        self.assertIsNotNone(arena.failure_traceback)
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        report = self.m._observe_callback_release(probe)
        self.assertTrue(report['retained_funding'])
        self.assertTrue(report['preserve_failure_frames_until_release'])
        primary.__traceback__ = None
        namespace = primary = arena = operation = None
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        self.release(identity)
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_optimised_dynamic_locals_fall_back_before_independent_copy(self):
        primary = MemoryError('native allocation with dynamic locals')
        probe = {'arena': None}
        def operation(arena):
            owner = self.make_owner()
            # Bounded injection exceeds this ordinary function's lexical slots.
            locals().update({f'dynamic_{index}': index for index in range(64)})
            raise primary
        try:
            self.m._run_observer_operation(self.r, self.budget, operation, (),
                disposition(), 'dynamic-locals', callback_probe=probe)
        except BaseException as caught:
            self.assertIs(caught, primary)
        else:
            self.fail('Primary dynamic-locals failure was lost')
        arena = probe['arena']
        identity = id(arena)
        self.assertFalse(arena.failure_roots_complete)
        self.assertIn('dynamic locals', str(arena.failure_snapshot_error))
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        self.assertTrue(self.m._observe_callback_release(probe)['preserve_failure_frames_until_release'])
        primary.__traceback__ = None
        primary = arena = operation = None
        self.release(identity)
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_partial_copy_failure_retains_native_and_observer_funding(self):
        def operation(arena):
            arena.prepare_owners(1)
            arena.copy_owner(self.make_owner)
        with patch.object(self.m, '_canon_bytes', side_effect=MemoryError('encoder partial')):
            with self.assertRaises(MemoryError) as caught:
                self.m._run_observer_operation(self.r, self.budget, operation, (), disposition(), 'encode')
        identity = caught.exception.retained_owner_id
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        self.assertGreater(self.categories()['observer-d02'], 65536)
        caught = None
        self.release(identity)

    def test_declared_escape_inside_copy_window_keeps_native_owner(self):
        escaped = {}
        def registered(arena, owner):
            escaped['id'] = arena.retain()
            escaped['payload'] = owner.value
        def operation(arena):
            arena.prepare_owners(1)
            arena.copy_owner(self.make_owner)
        with patch.object(self.m._ObserverArena, '_after_owner_registered', registered):
            self.m._run_observer_operation(self.r, self.budget, operation, (), disposition(), 'window-alias')
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        self.assertEqual(escaped['payload']['nested'][0]['marker'], 'native payload')
        identity = escaped['id']
        escaped.clear()
        self.release(identity)
        self.assertEqual(self.categories()['compact-mesh-owned'], 0)

    def test_diagnostic_and_attribute_faults_preserve_exact_primary(self):
        for kind in (KeyboardInterrupt, self.r.MemoryLimitError):
            with self.subTest(kind=kind.__name__):
                primary = kind('primary')
                probe = {'arena': None}
                def operation(arena):
                    arena.prepare_owners(1)
                    arena.acquire(self.make_owner)
                    raise primary
                def reject_attributes(error, name, value):
                    raise MemoryError('optional attribute storage failed')
                with patch.object(self.m, '_failure_info', side_effect=MemoryError('diagnostic failed')):
                    if kind is self.r.MemoryLimitError:
                        with patch.object(kind, '__setattr__', reject_attributes):
                            try:
                                self.m._run_observer_operation(self.r, self.budget, operation, (),
                                    disposition(), 'diagnostic-fault', callback_probe=probe)
                            except BaseException as caught:
                                self.assertIs(caught, primary)
                            else:
                                self.fail('primary failure lost')
                    else:
                        try:
                            self.m._run_observer_operation(self.r, self.budget, operation, (),
                                disposition(), 'diagnostic-fault', callback_probe=probe)
                        except BaseException as caught:
                            self.assertIs(caught, primary)
                        else:
                            self.fail('primary failure lost')
                identity = id(probe['arena'])
                self.assertTrue(self.m._observe_callback_release(probe)['retained_funding'])
                self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
                primary = operation = None
                self.release(identity)

    def test_native_admission_refusal_classification_and_recovery(self):
        budget = self.r.WorkBudget(100)
        with self.assertRaises(self.r.MemoryLimitError) as caught:
            self.m._run_observer_operation(self.r, budget, lambda arena: None,
                                          (), disposition(), 'admission')
        identity = caught.exception.retained_owner_id
        self.assertEqual(budget.reserved_bytes, 0)
        caught = None
        self.m.release_retained_owner(identity, aliases_released=True)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_callback_keeps_native_values_until_finalisation(self):
        probe = {'arena': None}
        owner = self.make_owner()
        reference = weakref.ref(owner)
        self.m._run_observer_operation(self.r, self.budget, lambda arena, value: None,
            (owner,), disposition(), 'callback', callback_probe=probe)
        owner = None
        self.assertIsNotNone(reference())
        self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
        release = self.m._observe_callback_release(probe)
        self.assertTrue(release['released'])
        self.assertIsNone(reference())
        self.assertEqual(self.categories()['compact-mesh-owned'], 0)
        self.assertEqual(self.categories()['observer-d02'], 0)

    def test_cancellation_and_reporting_failure_preserve_primary(self):
        for error_type, args in ((KeyboardInterrupt, ()), (SystemExit, (7,)),
                                 (self.r.MemoryLimitError, ('native refusal',))):
            error = error_type(*args)
            with self.subTest(kind=type(error).__name__):
                probe = {'arena': None}
                record = {'operations': ReportingFailure(), 'secondary_failures': []}
                def operation(arena):
                    arena.prepare_owners(1)
                    arena.acquire(self.make_owner)
                    raise error
                caught = None
                try:
                    self.m._run_observer_operation(self.r, self.budget, operation, (),
                        record, 'cancel', callback_probe=probe)
                except BaseException as failure:
                    caught = failure
                self.assertIs(caught, error)
                if isinstance(caught, SystemExit):
                    self.assertEqual(caught.code, 7)
                identity = caught.retained_owner_id
                release = self.m._observe_callback_release(probe)
                self.assertTrue(release['explicit_release_required'])
                self.assertEqual(self.categories()['compact-mesh-owned'], 32768)
                caught = error = operation = None
                self.release(identity)

    def test_finalisation_failure_is_not_silent_success(self):
        probe = {'arena': None}
        self.m._run_observer_operation(self.r, self.budget, lambda arena: None, (),
                                      disposition(), 'finalise', callback_probe=probe)
        identity = id(probe['arena'])
        original = probe['arena'].pool.__exit__
        with patch.object(probe['arena'].pool, '__exit__', side_effect=OSError('release fault')):
            with self.assertRaises(OSError):
                self.m._observe_callback_release(probe)
        self.assertIsNotNone(probe['arena'])
        self.assertGreater(self.categories()['observer-d02'], 0)
        self.assertTrue(self.m._observe_callback_release(probe)['released'])
        self.assertEqual(self.categories()['observer-d02'], 0)
        self.assertIsNotNone(original)
        with self.assertRaises(KeyError):
            self.m.retained_owner(identity)

    def test_control_primary_survives_stop_and_report_failure(self):
        primary = ValueError('CONTROL primary')
        def invoke():
            raise primary
        def stop():
            raise OSError('stop failure')
        with patch.object(self.m, '_write_disposition', side_effect=OSError('write failure')):
            try:
                self.m._control_boundary(invoke, stop, disposition(), ARTIFACTS)
            except BaseException as caught:
                self.assertIs(caught, primary)
            else:
                self.fail('CONTROL exception was lost')
            with self.assertRaises(self.m.ObserverCleanupError):
                self.m._control_boundary(lambda: None, stop, disposition(), ARTIFACTS)

    def test_full_volume_actual_native_capture(self):
        import exterior_mesh_patch
        import heat_ledger_issuer_patch
        import live_spatial_patch
        from content_cache import create_retained_scope
        from atlas_tectonics.integration_volume import CartesianCell, RadialLayer
        n = int(os.environ.get('PLAN05_SMOKE_CELLS', '236'))
        f = int(os.environ.get('PLAN05_SMOKE_FACES', '832'))
        self.assertGreaterEqual(f, n)
        h = lambda value: hashlib.sha256(str(value).encode()).hexdigest()
        zero, one = ['0x0', '0x1'], ['0x1', '0x1']
        exact = Fraction.from_float(0.1)
        encode = lambda value: [hex(Fraction(value).numerator), hex(Fraction(value).denominator)]
        # Source-shaped physical support: the same native record constructors
        # used by integration_exterior_mesh.support_refs. Binary64-derived exact
        # fractions exercise long strings without claiming a measured worst case.
        layer = RadialLayer(Fraction(8) + exact, 1, 2, budget=self.budget).record()
        cone = [[one, zero, zero], [zero, one, zero], [encode(exact), zero, one]]
        layer_id, cone_id = self.native.digest(layer), self.native.digest(cone)
        supports = {'voxels': {}, 'radial_layers': {layer_id: layer}, 'cones': {cone_id: cone}}
        cell_ids, face_ids = [h(('cell', i)) for i in range(n)], [h(('face', i)) for i in range(f)]
        cells = []
        for i, cid in enumerate(cell_ids):
            voxel = CartesianCell((i, 0, 0), (i + 1, 1, 1),
                origin_m=(exact, exact, exact), budget=self.budget).record()
            voxel_id = self.native.digest(voxel)
            supports['voxels'][voxel_id] = voxel
            row = dict(cell_id=cid, logical_cell_id=h(('logical', i)),
                volume_m3=one, centroid_m=[encode(Fraction(i) + exact), encode(exact), encode(exact)],
                physical_volume_bounds_m3=[one, one], geometry_volume_max_deviation_m3=zero,
                faces=[], physical_support={'voxel_id': voxel_id})
            if i % 2:
                row.update(kind='exterior', source_key=[h('source-region'), 'synthetic-material'],
                           voxel_index=[i, 0, 0], radial_band=0, chart=0)
                row['physical_support'].update(radial_layer_id=layer_id, cone_id=cone_id)
            else:
                row.update(kind='collar', index=[i, 0, 0], physical_cell_id=voxel_id)
            cells.append(row)
        faces = []
        for j, fid in enumerate(face_ids):
            indices = [j % n]
            if n > 1 and j % 2:
                indices.append((j + 1) % n)
            for k, index in enumerate(indices):
                cells[index]['faces'].append([fid, 1 if k == 0 else -1])
            first = cells[indices[0]]
            row = dict(face_id=fid, kind='paired' if len(indices) == 2 else 'boundary',
                geometry_kind='synthetic-triangle', centroid_m=[encode(exact), zero, zero],
                area_vector_m2=[one, zero, zero], owners=[cell_ids[i] for i in indices],
                vertices_m=[[zero, zero, zero], [one, zero, zero], [zero, one, zero]],
                cartesian_support=[{'cell_id': first['cell_id'],
                    'physical_voxel_id': first['physical_support']['voxel_id'],
                    'axis': 0, 'end': 1, 'local_coordinate_m': encode(exact)}])
            if len(indices) == 1:
                row.update(boundary_role='synthetic-reservoir',
                           reservoir_cut={'cell_id': first['cell_id'], 'axis': 0, 'end': 1})
            faces.append(row)
        record = dict(schema=self.native.LEGACY, method=self.native.METHOD, funding_id=h('funding'),
            source={}, support_id=h('support'), trajectory_id=self.native.digest([]),
            trajectory_segments=[], endpoint='end', time_s=['1', '1'], grid_id=h('grid'),
            cells=cells, faces=faces, support_tables=supports,
            grid_lines=[[zero, one], [zero, one], [zero, one]])
        blobs = {}
        metadata, arrays = self.native.pack_mesh(record, support_writer=blobs.__setitem__,
                                                 budget=self.budget)
        view = self.native.CompactMesh(metadata, arrays, support_reader=lambda key, size: blobs[key],
            expected_geometry_id=metadata['geometry_id'], budget=self.budget)
        class SyntheticMesh:
            def physical_support(this, index):
                return exterior_mesh_patch.physical_support(this, index)
        mesh = SyntheticMesh()
        mesh._compact, mesh._resource = view, self.budget
        scope = create_retained_scope(self.budget, process_epoch='plan05-r13-synthetic')
        owner = SimpleNamespace(_budget=self.budget, _component_count=2, _record_scope=scope)
        logical_ids = [row['logical_cell_id'] for row in cells]
        graph_record = {'cells': [{'cell_id': cid, 'end_volume_m3': ['1', '1']} for cid in logical_ids]}
        transport_record = {'cell_ids': logical_ids, 'exact_stocks': {
            'enthalpy_j': [['2', '1'] for _ in cells],
            'component_mass_kg:0': [['1', '3'] for _ in cells],
            'component_mass_kg:1': [['2', '3'] for _ in cells]}}
        class SyntheticHolder:
            def __init__(this, value):
                this.value = value
                this._resource = this._budget = self.budget
                this._json = self.m._canon_bytes(value)
                this._snapshot = SimpleNamespace(_metadata=this._json)
            def record(this):
                return json.loads(this._json)
        graph, transport = SyntheticHolder(graph_record), SyntheticHolder(transport_record)
        graph.geometry_id = h('graph')
        transport.result_id = h('transport')
        step = SimpleNamespace(graph=graph, result=transport,
            source=SimpleNamespace(result_id=h('source')), parent=SimpleNamespace(state_id=h('parent')))
        class SyntheticCall:
            pass
        call = SyntheticCall()
        call._budget = self.budget
        call._origin_objects = (owner, step, mesh, None)
        call._snapshot = SimpleNamespace(_metadata=self.m._canon_bytes({
            'cell_ids': cell_ids, 'duration_s': 1.0, 'heat_capacity_j_kg_k': 1.0}))
        call._plan = self.m._canon_bytes({'boundary': {}, 'conductivity_w_m_k': [1.0] * n})
        call._execution = SimpleNamespace(provenance={'synthetic': True})
        call._bindings, call.call_id = {}, h('call')
        class SyntheticResult:
            array_names = self.m.ARRAY_NAMES
            result_id = h('advance')
            def array(this, name):
                return fields[name]
        fields = {name: np.ones(n, dtype=np.float64) for name in self.m.ARRAY_NAMES}
        result = SyntheticResult()
        state = {'legacy_result_id': h('legacy'), 'legacy_sha': h('metadata')}
        probe, report = {'arena': None}, disposition()
        # The scientific issuer entry point is not imported/called. Its two
        # accessor modules and same-scope validator are the actual native ones.
        issuer = SimpleNamespace(HEAT_LEDGER=heat_ledger_issuer_patch, LIVE_SPATIAL=live_spatial_patch)
        directory = Path(tempfile.mkdtemp(dir=ARTIFACTS, prefix=f'capture-{n}-{f}-'))
        process = psutil.Process()
        before_capture = process.memory_info()
        started = perf_counter()
        with patch.dict(sys.modules, {'private_heat_native_issuer_r13': issuer}):
            self.m._run_observer_operation(self.r, self.budget, self.m._capture_operation,
                (state, {}, directory, call, result, 0, LAYOUT,
                 LAYOUT / 'helpers/private_heat_native_issuer_r13.py'),
                report, 'advance', callback_probe=probe)
        capture_seconds = perf_counter() - started
        held_capture = process.memory_info()
        live = self.budget.statistics()
        capture = json.loads((directory / 'd02_correspondence_capture.json').read_text())
        self.assertEqual(len(capture['cells']), n)
        self.assertEqual(len(capture['faces']), f)
        self.assertEqual(len(capture['input_provenance']), n)
        self.assertEqual(capture['cells'][0]['native_cell'], cells[0])
        self.assertEqual(capture['faces'][0]['native_face'], faces[0])
        self.assertEqual(capture['input_provenance'][cell_ids[0]]['transport_exact_enthalpy_j'], ['2', '1'])
        self.assertEqual(capture['input_provenance'][cell_ids[0]]['transport_exact_component_masses_kg'],
                         [['1', '3'], ['2', '3']])
        if n > 1:
            self.assertEqual(capture['cells'][1]['resolved_support']['radial_layer'], layer)
            self.assertEqual(capture['cells'][1]['resolved_support']['original_cone'], cone)
            self.assertEqual(capture['cells'][1]['independent_key']['cone_id'], cone_id)
        grid_proof = capture['compact_mesh_identity']['grid_proof_arrays']
        for name, info in grid_proof.items():
            path = directory / info['file']
            self.assertEqual(self.m._file_sha(path), info['file_sha256'])
            decoded = np.load(path, allow_pickle=False)
            self.assertTrue(np.array_equal(decoded, view._arrays[name]))
            self.assertEqual(self.m._array_payload_sha(decoded), info['sha256'])
        self.assertEqual(probe['arena'].owner_count, 2 * n + f + 1)
        self.assertEqual(sum(x is not None for x in probe['arena'].native_owners), 0)
        release = self.m._observe_callback_release(probe)
        self.assertTrue(release['released'])
        self.assertEqual(self.categories()['observer-d02'], 0)
        receipt = {'synthetic': True, 'scientific_capture': False, 'cells': n, 'faces': f,
            'collar_cells': sum(row['kind'] == 'collar' for row in cells),
            'exterior_cells': sum(row['kind'] == 'exterior' for row in cells),
            'paired_faces': sum(len(row['owners']) == 2 for row in faces), 'components': 2,
            'support_kind': 'native-CartesianCell-RadialLayer-records-and-cone-preimage',
            'integer_size_basis': 'exact binary64 0.1; representative fixture, not worst-case bound',
            'native_acquisitions': 2 * n + f + 1, 'live_statistics': live,
            'release': release, 'writer_sha256': hashlib.sha256((HERE / 'ab_heat_r13.py').read_bytes()).hexdigest()}
        after_release = process.memory_info()
        receipt['resource_observation'] = {
            'capture_operation_seconds': capture_seconds,
            'rss_before_capture_bytes': before_capture.rss,
            'rss_while_callback_holds_values_bytes': held_capture.rss,
            'rss_after_release_bytes': after_release.rss,
            'whole_process_peak_wset_bytes': after_release.peak_wset,
            'measurement_scope': 'native process working set; includes fixture preparation and inspection; not a heap bound',
            'copied_support_json_bytes_with_repetitions': sum(
                len(self.m._canon_bytes(row['resolved_support'])) for row in capture['cells']),
            'artifact_sizes_bytes': {p.name: p.stat().st_size for p in directory.iterdir() if p.is_file()},
        }
        with (directory / 'accounting.json').open('x', encoding='utf8') as stream:
            json.dump(receipt, stream, indent=2)
        print('Native capture fixture retained at ' + str(directory), flush=True)
        scope.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
