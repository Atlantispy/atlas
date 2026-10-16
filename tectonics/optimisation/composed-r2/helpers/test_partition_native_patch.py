"""Fresh private native package, synthetic sources, tiny exact operand tests."""
import ast
from copy import deepcopy
import gc
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import partition_native_patch as P


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]/'runtime-integration-r1'/'runtime-src'/'atlas_tectonics'
temporary = None


def setUpModule():
    global temporary, D, T, R
    if any(n == 'atlas_tectonics' or n.startswith('atlas_tectonics.') for n in sys.modules):
        raise RuntimeError('fresh process required; never patch a loaded production package')
    temporary = tempfile.TemporaryDirectory(prefix='pn-', dir=HERE.parents[4])
    package = Path(temporary.name)/'atlas_tectonics'
    shutil.copytree(BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    source = (BASE/'integration_differential_geometry.py').read_text(encoding='utf8')
    (package/'integration_differential_geometry.py').write_text(P.transform(source), encoding='utf8')
    source = (BASE/'integration_differential_coupling.py').read_text(encoding='utf8')
    (package/'integration_differential_coupling.py').write_text(P.transform_coupling(source), encoding='utf8')
    sys.path.insert(0, temporary.name)
    D = importlib.import_module('atlas_tectonics.integration_differential_geometry')
    T = importlib.import_module('test_partition_tables')
    R = importlib.import_module('atlas_tectonics.integration_spatial_reservoir')


def tearDownModule():
    if temporary is not None:
        assert Path(temporary.name).resolve().parent == HERE.parents[4]
        temporary.cleanup()


def source_operands(body, budget, *, initial=False):
    """Restore-protocol controls, not assertions of real physical provenance."""
    funding = SimpleNamespace(funding_id=body['funding_id'], _resource=budget,
                              descriptor=lambda: {'source': body['source']})
    collar = SimpleNamespace(plan_id=body['collar_plan_id'], _budget=budget)
    geometry = D._issue(D.CurrentGeometry if initial else D.DifferentialInterval,
                        {'fixture': 'typed restore protocol only'}, budget)
    body['scope'] = 'initial-current' if initial else 'physical-interval'
    body['current_geometry_id'] = geometry.geometry_id if initial else None
    if not initial:
        body['interval_id'] = geometry.interval_id
    return funding, collar, geometry


def prepared(body, supports, budget, operands):
    view, metadata, arrays = T.opened(body, supports, budget)
    part = D.DifferentialPartition.from_compact(view, *operands, budget=budget)
    legacy = D.DifferentialPartition.restore(dict(partition_id=D._record_hash(body), **body, supports=supports),
                                            *operands, budget=budget)
    del metadata, arrays
    return part, legacy, view


class NativePartitionTests(unittest.TestCase):
    def setUp(self):
        self.budget = T.WorkBudget(128 << 20)
        self.body, self.supports = T.tiny_partition(self.budget)

    def tearDown(self):
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_actual_native_type_source_gates_and_lazy_exact_supports(self):
        for initial in (False, True):
            body = deepcopy(self.body)
            operands = source_operands(body, self.budget, initial=initial)
            part, legacy, view = prepared(body, self.supports, self.budget, operands)
            self.assertIs(type(part), D.DifferentialPartition)
            self.assertEqual(part.partition_id, legacy.partition_id)
            self.assertIs(part.compact_view(), view)
            self.assertIsNone(legacy.compact_view())
            self.assertEqual(part.legacy_record().value, legacy.record())
            with self.assertRaises(D.V.VolumeError):
                part.record()
            with self.assertRaises(D.V.VolumeError):
                part.descriptor()
            self.assertEqual(len(part.supports), len(legacy.supports))
            for compact, old in zip(part.supports, legacy.supports):
                self.assertIs(type(compact), D.DifferentialSupport)
                self.assertEqual(compact._json, old._json)
                self.assertEqual(compact.support_id, old.support_id)
                self.assertIs(compact._compact_ref._view, view)
            with self.assertRaises(TypeError):
                part.supports[:]
            bad_funding = SimpleNamespace(funding_id='f'*64, _resource=self.budget, descriptor=operands[0].descriptor)
            with self.assertRaises(D.V.VolumeError):
                D.DifferentialPartition.from_compact(view, bad_funding, operands[1], operands[2], budget=self.budget)
            wrong_geometry = D._issue(D.CurrentGeometry if initial else D.DifferentialInterval,
                                      {'fixture': 'different'}, self.budget)
            with self.assertRaises(D.V.VolumeError):
                D.DifferentialPartition.from_compact(view, operands[0], operands[1], wrong_geometry, budget=self.budget)
            other = T.WorkBudget(128 << 20)
            with self.assertRaises(D.V.VolumeError):
                D.DifferentialPartition.from_compact(view, *operands, budget=other)
            self.assertEqual(other.reserved_bytes, 0)

    def test_selected_header_rows_do_not_expand_partition_or_constraint_charts(self):
        operands = source_operands(self.body, self.budget)
        part, legacy, view = prepared(self.body, self.supports, self.budget, operands)
        original = T.P.CompactPartition.legacy_record
        def selected_only(instance, ref=None):
            if ref is None or ref.index in (view.root().index, view.root().field('source_regions').index):
                raise AssertionError('whole partition/regions export forbidden')
            return original(instance, ref)
        with patch.object(T.P.CompactPartition, 'legacy_record', selected_only):
            header = P.partition_fields(part, ('source', 'funding_id', 'end_time_s'))
            self.assertEqual(header.value, {k: self.body[k] for k in ('source', 'funding_id', 'end_time_s')})
            rows = list(P.partition_rows(part, 'source_regions', fields=('plate_id', 'radial_layer', 'radial_band')))
            self.assertEqual(rows[0].value, {k: self.body['source_regions'][0][k]
                                          for k in ('plate_id', 'radial_layer', 'radial_band')})
        self.assertEqual(P.partition_fields(legacy, ()).value, self.body)

    def test_real_native_exact_component_query_parity(self):
        body = deepcopy(self.body)
        operands = source_operands(body, self.budget, initial=True)
        box = D.V.CartesianCell((2, 2, 2), (3, 3, 3), budget=self.budget)
        layer = D.V.RadialLayer(10, 0, 9, budget=self.budget)
        support = deepcopy(self.supports[0])
        support.update(interval_id=None, current_geometry_id=operands[2].geometry_id,
            voxel=box.record(), radial_layer=layer.record(), constraints={},
            material_angular_velocity_rad_s=[T.q(0)]*3, start_time_s=T.q(0), end_time_s=T.q(0), duration_s=T.q(0))
        support['components'][0]['constraints'] = []
        body['support_ids'] = [D._record_hash(support)]
        part, legacy, view = prepared(body, [support], self.budget, operands)
        key = support['components'][0]['logical_cell_id']
        for endpoint in ('start', 'end'):
            kwargs = dict(endpoint=endpoint, max_width_m3=0, max_leaves=8, positive_witness=True, budget=self.budget)
            old = D.component_volume_bounds(legacy.supports[0], key, **kwargs)
            compact = D.component_volume_bounds(part.supports[0], key, **kwargs)
            self.assertEqual(compact._json, old._json)
            self.assertTrue(compact.record()['met'])

    def test_native_continuation_builds_identical_new_chart_arguments_without_parent_expansion(self):
        body, supports = deepcopy(self.body), deepcopy(self.supports)
        # A carried material chart cannot include fixed spatial exclusions.
        for support in supports:
            support['components'][0]['constraints'] = [['carried:edge', 1], ['normal', -1]]
        body['support_ids'] = [D._record_hash(s) for s in supports]
        operands = source_operands(body, self.budget)
        part, legacy, view = prepared(body, supports, self.budget, operands)
        finite = R.PreparedFiniteStocks(T.ident('registry'), [dict(stock_id='sink', kind='sink',
            lineage={'fixture': 'finite restore control'}, volume_m3=T.q(1), exact={'mass': T.q(1)})],
            field_names=('mass',), nonnegative_fields=('mass',), budget=self.budget)
        try:
            step = dict(parent_network_id=body['endpoint_network_id'], prior_trajectory_id=body['trajectory_id'],
                start_time_s=body['end_time_s'], end_time_s=T.q(2), duration_s=T.q(1),
                plate_angular_velocity_rad_s={'plate:A': [T.q(0)]*3}, boundary_paths=[])
            interval = D._issue(D.DifferentialInterval, step, self.budget)
            captures = []
            def capture(funding, sphere, geometry, collar, original, regions, **kwargs):
                captures.append((D._encoded(regions), kwargs['grid_lines'], kwargs['max_components']))
                result = D._issue(D.DifferentialPartition, dict(body, fixture_result='assembly intercepted'), self.budget)
                object.__setattr__(result, '_supports', ())
                return result
            with patch.object(D, '_assemble_partition', capture):
                old = D.prepare_interval_partition(legacy, interval, operands[0], object(), operands[1],
                    finite_stock_state=finite.initial(), max_components=1000, budget=self.budget)
                new = D.prepare_interval_partition(part, interval, operands[0], object(), operands[1],
                    finite_stock_state=finite.initial(), max_components=1000, budget=self.budget)
                self.assertEqual(old._json, new._json)
                self.assertEqual(captures[0], captures[1])
                self.assertEqual(len(captures), 2)
        finally:
            finite.close()

    def test_native_restore_and_numerical_function_asts_unchanged(self):
        original = (BASE/'integration_differential_geometry.py').read_text(encoding='utf8')
        candidate = P.transform(original)
        def functions(source):
            return {node.name: ast.dump(node, include_attributes=False) for node in ast.walk(ast.parse(source))
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        a, b = functions(original), functions(candidate)
        for name in ('_assemble_partition', 'component_volume_bounds', '_component_volume_bounds_decoded',
                     'prepare_current_geometry', 'current_geometry_from_interval', '_constraint_pose', '_issue'):
            self.assertEqual(a[name], b[name], name)
        original_cls = next(n for n in ast.parse(original).body if isinstance(n, ast.ClassDef) and n.name == 'DifferentialPartition')
        candidate_cls = next(n for n in ast.parse(candidate).body if isinstance(n, ast.ClassDef) and n.name == 'DifferentialPartition')
        restore = lambda cls: next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'restore')
        self.assertEqual(ast.dump(restore(original_cls)), ast.dump(restore(candidate_cls)))
        with self.assertRaises(ValueError):
            P.transform(original+'\n')
        with self.assertRaises(ValueError):
            P.transform_coupling('unreviewed')

    def test_owned_header_survives_native_wrapper_release(self):
        operands = source_operands(self.body, self.budget)
        part, legacy, view = prepared(self.body, self.supports, self.budget, operands)
        header = P.partition_fields(part, ('source',))
        del part, legacy, view, operands
        gc.collect()
        self.assertGreater(self.budget.reserved_bytes, 0)
        self.assertEqual(header.value['source'], self.body['source'])


if __name__ == '__main__':
    unittest.main()
