"""Bounded Step 8 construction-copy parity and ownership controls."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from fractions import Fraction
import gc
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
R = HERE.parent
I = R.parent / 'runtime-integration-r1/runtime-src'
H = HERE.parents[3] / 'heat-repair-20261007'
sys.path[:0] = [str(I), str(R), str(H)]

from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import create_retained_scope
from heat_ledger_tables import CompactHeatSnapshot, own_field
import exchange_record_patch as EXCHANGE
import heat_ledger_issuer_patch as HEAT
import live_spatial_patch as LIVE
import private_heat_indexed_runtime as INDEXED
import spatial_validation_patch as VALIDATION


def sources():
    joined = INDEXED.joined_source((H / 'private_heat_joined_consumer_r6.py').read_text(),
                                  expected_sha256=EXCHANGE.JOINED_SHA)
    joined = VALIDATION.joined_source(HEAT.joined_source(EXCHANGE.producer_source(joined)))
    projection = HEAT.projection_source(INDEXED.projection_source(
        (H / 'private_heat_native_projection_r4.py').read_text()))
    issuer = HEAT.issuer_source(INDEXED.issuer_source(
        (H / 'private_heat_native_issuer_r12.py').read_text()))
    return joined, projection, issuer


def function(source, name, namespace):
    body = LIVE._function(source, name)
    result = dict(namespace)
    exec(compile(body, '<exact-live-function:'+name+'>', 'exec'), result)
    return result[name]


class SourceTests(unittest.TestCase):
    def test_exact_stages_compile_once_and_keep_account_checks(self):
        joined, projection, issuer = sources()
        for source, transform in ((joined, LIVE.joined_source),
                (projection, LIVE.projection_source), (issuer, LIVE.issuer_source)):
            changed = transform(source)
            compile(changed, '<live-spatial>', 'exec')
            with self.assertRaises(ValueError):
                transform(changed)
        changed = LIVE.joined_source(joined)
        self.assertIn('LIVE_SPATIAL.record_access(step.graph',
                      LIVE._function(changed, 'grouped_account'))
        old = ast.parse(LIVE._function(joined, 'grouped_account')).body[0]
        new = ast.parse(LIVE._function(changed, '_grouped_account_records')).body[0]
        # Two producer reads and one public-field allocation differ. All
        # original checks and the exact ACCOUNT.calculate call are retained.
        old.body = [node for node in old.body if not (isinstance(node, ast.Assign) and
            ast.unparse(node.targets[0]) in ('(graph, transported, metric)', 'prior'))]
        old.name, old.args = new.name, new.args
        old_public = next(node for node in ast.walk(old) if isinstance(node, ast.Assign) and
                          ast.unparse(node.targets[0]) == 'public')
        new_public = next(node for node in ast.walk(new) if isinstance(node, ast.Assign) and
                          ast.unparse(node.targets[0]) == 'public')
        old_public.value = new_public.value
        self.assertEqual(ast.dump(old), ast.dump(new))
        before = ast.parse(LIVE._function(issuer, '_advance_verified')).body[0]
        after = ast.parse(LIVE._function(LIVE.issuer_source(issuer), '_advance_verified')).body[0]
        for node in ast.walk(after):
            if hasattr(node, 'body') and isinstance(node.body, list):
                node.body[:] = [item for item in node.body if not isinstance(item, ast.Delete) or
                                ast.unparse(item) != 'del values']
        self.assertEqual(ast.dump(before), ast.dump(after))

    def test_projection_shares_only_already_owned_lists_with_exact_output(self):
        _, projection, _ = sources()
        encoder = lambda value: [hex(value.numerator), hex(value.denominator)]
        namespace = dict(_hex=encoder, A=SimpleNamespace(TRACE_STATUS='trace'),
            R=SimpleNamespace(stream_hash=lambda value, cancel: json.dumps(value)), LIVE_SPATIAL=LIVE)
        old = function(projection, '_encode', namespace)
        new = function(LIVE.projection_source(projection), '_encode', namespace)
        record = dict(result_id='r', method_id='m', enthalpy_j=[3., 4.], temperature_k=[2., 2.])
        exact = {name: [Fraction(1), Fraction(2)] for name in
                 ('new', 'retained', 'projection', 'public', 'canonical')}
        exact.update(target=Fraction(1, 10), source_total=Fraction(0), outward=Fraction(0), boundary={})
        geometry = SimpleNamespace(geometry_id='g', _face_ids=('f1', 'f2'))
        arrays = [[1., 2.], [2., 2.], [0., 0.]]
        args = record, exact, geometry, ['a', 'b'], arrays, 'state', .125, None
        expected, result = old(*args), new(*args)
        self.assertEqual(json.dumps(expected, sort_keys=True), json.dumps(result, sort_keys=True))
        for name, original in (('enthalpy_j', record['enthalpy_j']),
                              ('temperature_k', record['temperature_k']),
                              ('input_enthalpy_j', arrays[0]), ('input_capacity_j_k', arrays[1]),
                              ('input_source_w', arrays[2])):
            self.assertIs(result['arrays'][name], original)
            self.assertIsNot(expected['arrays'][name], original)
        integer = [1, 2]
        self.assertEqual(LIVE.float_list(integer), [1., 2.])
        self.assertTrue(all(type(x) is float for x in LIVE.float_list(integer)))


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='live-spatial')

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_float_iteration_retains_paid_backing_after_parent_release(self):
        raw = own_field(np.asarray([1., -0., 3.]).tobytes(), scope=self.scope)
        array = np.frombuffer(raw, dtype='f8').reshape(3)
        sequence = LIVE.float_sequence(array, scope=self.scope)
        iterator = iter(sequence)
        del raw, array, sequence
        self.assertGreater(self.scope.stats().retained_bytes, 65536)
        self.assertEqual(list(iterator), [1., -0., 3.])
        del iterator
        with self.assertRaises(ContractError):
            LIVE.float_sequence(np.asarray([1.]), scope=self.scope)
        unowned = np.frombuffer(b'\0' * 8, dtype='f8')
        with self.assertRaisesRegex(ContractError, 'paid backing'):
            LIVE.float_sequence(unowned, scope=self.scope)

    def test_tuple_path_normalisation_and_snapshot_identity_are_exact(self):
        metadata = {'cell_ids': ['cell'+str(i) for i in range(100)],
                    'caller': {'cell_ids': ['a', 'b'], 'policy': (('fixed', 1.),)},
                    'exact': [['0x1', '0x2']] * 30}
        expected = json.loads(json.dumps(metadata))
        changed = LIVE.normalise_containers(metadata, lambda: None)
        self.assertEqual(changed, expected)
        self.assertIs(changed['cell_ids'], metadata['cell_ids'])
        self.assertIs(changed['exact'], metadata['exact'])
        self.assertIs(changed['caller']['cell_ids'], metadata['caller']['cell_ids'])
        self.assertIsNot(changed['caller'], metadata['caller'])
        self.assertEqual(metadata['caller']['policy'], (('fixed', 1.),))
        self.assertEqual(LIVE.normalisation_capacity({'all': expected}, lambda: None), 0)
        fields = {'x': np.asarray([1., -0., 3.])}
        owner = SimpleNamespace(_budget=self.budget, _record_scope=self.scope)
        call = SimpleNamespace(_budget=self.budget, _record_scope=self.scope,
            _origin_objects=(owner,), _fixture=False, _geometry=SimpleNamespace(_indexed=None))
        before = CompactHeatSnapshot.from_components(expected, fields, scope=self.scope)
        after = HEAT.package_result(metadata, fields, call)
        self.assertEqual(after.result_id, before.result_id)
        self.assertEqual(after.metadata_identity, before.metadata_identity)
        self.assertEqual(after.array('x').tobytes(), before.array('x').tobytes())
        before.close(); after.close()
        del before, after, owner, call

    def test_normalisation_depth_and_cancellation_refuse_without_mutation(self):
        value = {'a': [1., 2.], 'tuple': ('a',)}
        original = deepcopy(value)
        def refuse():
            raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            LIVE.normalisation_capacity(value, refuse)
        with self.assertRaises(InterruptedError):
            LIVE.normalise_containers(value, refuse)
        self.assertEqual(value, original)
        for _ in range(130):
            value = [value]
        with self.assertRaisesRegex(ContractError, 'depth'):
            LIVE.normalisation_capacity(value, lambda: None)



class HeatPackageStoreTests(unittest.TestCase):
    def setUp(self):
        import test_segment_store as fixtures
        fixtures.SegmentStoreTests.setUp(self)

    def tearDown(self):
        import test_segment_store as fixtures
        fixtures.SegmentStoreTests.tearDown(self)

    def test_fresh_and_persisted_mesh_ids_keep_exact_identity_and_checkpoint(self):
        from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
        from compact_contracts import SegmentRef
        from compact_store import CompactMeshStoreV3
        import mesh_tables as M
        import private_heat_snapshot_store_r4 as S
        from test_mesh_v3 import fixture
        old, _, source, partition, _ = fixture(self.scope, self.candidate, count=1)
        fresh = M.CompactMesh(json.loads(old._metadata), dict(old._arrays),
            support_reader=old._reader, expected_geometry_id=old.geometry_id,
            budget=self.budget, scope=self.scope)
        adapter = CompactMeshStoreV3(self.candidate, scope=self.scope, support_source=source)
        mesh_ref = adapter.publish(old, producer='b'*64)
        persisted = adapter.open(mesh_ref, expected_geometry_id=old.geometry_id)
        data = dict(cell_ids=[fresh.cell_id(i) for i in range(fresh.cell_count)],
            face_ids=[fresh.face_id(i) for i in range(fresh.face_count)],
            caller_snapshot={'cell_ids': [fresh.cell_id(i) for i in range(fresh.cell_count)]},
            exact=['0x2', '0x4'])
        fields = {'a': np.asarray([-0., 1.])}
        expected = RegionalMechanicalSnapshot(data, fields)
        owner = SimpleNamespace(_budget=self.budget, _record_scope=self.scope)
        call = SimpleNamespace(_budget=self.budget, _record_scope=self.scope,
            _origin_objects=(owner,), _fixture=False, _geometry=SimpleNamespace(_indexed=fresh))
        with self.assertRaisesRegex(ContractError, 'identity order'):
            HEAT.package_result(dict(data, cell_ids=['0'*64]*fresh.cell_count), fields, call)
        call._geometry._indexed = SimpleNamespace(_segment=None)
        with self.assertRaisesRegex(ContractError, 'shared run budget'):
            HEAT.package_result(data, fields, call)
        # The retained-scope registry itself prohibits two scopes on one run
        # budget; a real foreign mesh is therefore also a foreign-budget mesh.
        other_budget = WorkBudget(128 << 20)
        foreign = M.CompactMesh(json.loads(old._metadata), dict(old._arrays),
            support_reader=old._reader, expected_geometry_id=old.geometry_id, budget=other_budget)
        call._geometry._indexed = foreign
        with self.assertRaisesRegex(ContractError, 'shared run budget'):
            HEAT.package_result(data, fields, call)
        del foreign
        call._geometry._indexed = None
        self.assertEqual(other_budget.reserved_bytes, 0)
        receipts = []
        for at, mesh in enumerate((fresh, persisted)):
            call._geometry._indexed = mesh
            snapshot = HEAT.package_result(data, fields, call)
            self.assertEqual(snapshot.result_id, expected.result_id)
            self.assertEqual(snapshot.mesh_binding is None, at == 0)
            bindings = {'source': str(at+1)*64}
            receipt = S.save(self.candidate, snapshot, bindings=bindings, scope=self.scope)
            self.assertEqual(receipt['metadata']['shared_mesh'] is None, at == 0)
            receipts.append((receipt, bindings))
            snapshot.close()
        # Explicitly requesting an unpersisted shared snapshot still refuses
        # storage. Packaging chooses an existing supported representation.
        invalid = CompactHeatSnapshot.from_components(data, fields, scope=self.scope, mesh=fresh)
        with self.assertRaisesRegex(ContractError, 'authenticated mesh segment'):
            S.save(self.candidate, invalid, bindings={'source': '3'*64}, scope=self.scope)
        invalid.close()
        persisted.close(); fresh.close()
        sealed = self.candidate.seal(SegmentRef.from_wire(receipts[-1][0]['metadata']['ledger']))
        self.stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
        reopened_mesh = CompactMeshStoreV3(self.stores, scope=self.scope, support_source=source).open(
            mesh_ref, expected_geometry_id=old.geometry_id)
        for at, (receipt, bindings) in enumerate(receipts):
            with S.open(self.stores, receipt, expected_result_id=expected.result_id,
                    bindings=bindings, scope=self.scope, mesh=reopened_mesh if at else None) as result:
                self.assertEqual(result.value.result_id, expected.result_id)
                self.assertEqual(result.value.array('a').tobytes(), fields['a'].tobytes())
                with result.value.field('cell_ids') as cells:
                    self.assertEqual(cells.value, data['cell_ids'])
                result.value.close()
        reopened_mesh.close(); source.close(); partition.close()
        del old, fresh, persisted, snapshot, invalid, call, owner, result, reopened_mesh


@contextmanager
def native_module(name, source):
    fullname = 'atlas_tectonics.'+name
    module = ModuleType(fullname)
    module.__package__ = 'atlas_tectonics'
    old = sys.modules.get(fullname)
    sys.modules[fullname] = module
    with tempfile.TemporaryDirectory(prefix='live-spatial-module-', dir=HERE.parents[4]/'_t') as temporary:
        module.__file__ = str(Path(temporary)/(name+'.py'))
        Path(module.__file__).write_text(source)
        try:
            exec(compile(source, module.__file__, 'exec'), module.__dict__)
            yield module
        finally:
            if old is None:
                del sys.modules[fullname]
            else:
                sys.modules[fullname] = old


def tiny_bounds():
    enc = lambda q: [hex(Fraction(q).numerator), hex(Fraction(q).denominator)]
    return dict(schema='atlas.source-bound-spatial-ale-bounds.v1',
        source={'name': 'explicit synthetic mathematical fixture'},
        cells=[dict(cell_id=key, kind='exterior', source_key=['test', at],
            start_volume_bounds_m3=[enc(start)]*2, end_volume_bounds_m3=[enc(end)]*2)
            for at, (key, start, end) in enumerate((('a', 2, 1), ('b', 1, 2)))],
        face_intervals=[dict(face_id='ab', donor='a', receiver='b',
                            volume_bounds_m3=[enc(1)]*2)],
        untouched_provenance={'padding': 'p'*10000, 'order': ['a', 'b']})


class FreshHolderTests(unittest.TestCase):
    setUp = OwnershipTests.setUp
    tearDown = OwnershipTests.tearDown
    def test_real_ale_holder_closure_and_transport_exact_without_graph_json(self):
        from atlas_tectonics import integration_spatial_ale as ordinary
        from atlas_tectonics import integration_spatial_transport as ordinary_transport
        from record_views import CompactRecord, RecordRef
        source = (I/'atlas_tectonics/integration_spatial_ale.py').read_text()
        transport = (I/'atlas_tectonics/integration_spatial_transport.py').read_text()
        transformed, transformed_transport = LIVE.ale_source(source), LIVE.transport_source(transport)
        for raw, transform in ((transformed, LIVE.ale_source), (transformed_transport, LIVE.transport_source)):
            with self.assertRaises(ValueError):
                transform(raw)
        for name in ('_circulation', '_project_native'):
            self.assertEqual(ast.dump(ast.parse(LIVE._function(source, name))),
                             ast.dump(ast.parse(LIVE._function(transformed, name))))
        for name in ('advance', '_transport_plan_capacity'):
            new_body = LIVE._function_any(transformed_transport, name).strip().replace(
                'not LIVE_FINITE.is_stocks(stocks, self._budget)', 'type(stocks) is not dict')
            new_body = new_body.replace('LIVE_TRANSPORT.make_snapshot(metadata, projected, self._budget, RegionalMechanicalSnapshot)',
                                       'RegionalMechanicalSnapshot(metadata, projected)')
            new_body = new_body.replace('LIVE_TRANSPORT.retain(result, 8192+3*_width(metadata)+sum(a.nbytes for a in projected.values()), self._budget, _retain)',
                                       '_retain(result, 8192+3*_width(metadata)+sum(a.nbytes for a in projected.values()), self._budget)')
            self.assertEqual(ast.dump(ast.parse(LIVE._function_any(transport, name).strip())),
                             ast.dump(ast.parse(new_body)))
        with native_module('_live_ale_fixture', transformed) as ale, native_module(
                '_live_transport_fixture', transformed_transport) as transported:
            before = ordinary._issue(ordinary.SpatialALEBounds, tiny_bounds(), self.budget)
            old_graph = ordinary.close_spatial_ale(before, {'a': Fraction(2), 'b': Fraction(1)}, budget=self.budget)
            with LIVE.construction(self.scope, budget=self.budget):
                bounds = ale._issue(ale.SpatialALEBounds, tiny_bounds(), self.budget)
            self.assertIs(type(bounds), ale.SpatialALEBounds)
            self.assertIs(type(bounds._json), CompactRecord)
            self.assertEqual(bounds.bounds_id, before.bounds_id)
            graph = ale.close_spatial_ale(bounds, {'a': Fraction(2), 'b': Fraction(1)}, budget=self.budget)
            self.assertIs(type(graph._json), CompactRecord)
            self.assertEqual(graph.geometry_id, old_graph.geometry_id)
            ref = graph.record()
            self.assertIs(type(ref), RecordRef)
            with ref.iter_json() as stream:
                actual = b''.join(block.value for block in stream)
            self.assertEqual(actual, old_graph._json)
            ref.close()
            fields = {'mass': [Fraction(4), Fraction(3)], 'signed': [Fraction(-2), Fraction(1)]}
            with ordinary_transport.PreparedSpatialTransport(old_graph.record(), budget=self.budget) as old:
                old_result = old.advance(fields, state_id='s', source_stage_id='source',
                    max_projection_errors={'mass': Fraction(1,100), 'signed': Fraction(1,100)},
                    nonnegative_fields=('mass',))
            with LIVE.record_access(graph, scope=self.scope) as working:
                with transported.PreparedSpatialTransport(working, budget=self.budget) as new:
                    self.assertIsNone(new._encoded)
                    new_result = new.advance(fields, state_id='s', source_stage_id='source',
                        max_projection_errors={'mass': Fraction(1,100), 'signed': Fraction(1,100)},
                        nonnegative_fields=('mass',))
            self.assertEqual(new_result.result_id, old_result.result_id)
            with new_result.record() as actual:
                with actual.export(max_logical_bytes=1 << 20, max_owned_bytes=4 << 20) as held:
                    self.assertEqual(held.value, old_result.record())
            with LIVE.transport_access(new_result, scope=self.scope) as actual:
                self.assertEqual(actual['cell_ids'], old_result.record()['cell_ids'])
                self.assertEqual(set(actual['exact_stocks']), set(fields))
                for name in fields:
                    column = actual['exact_stocks'][name]
                    self.assertIs(type(column), list)
                    self.assertTrue(all(type(pair) is list for pair in column))
                    self.assertEqual(column, old_result.record()['exact_stocks'][name])
                del column
            with self.assertRaisesRegex(ContractError, 'foreign retained scope'):
                with LIVE.transport_access(new_result, scope=None):
                    pass
            for name in old_result._snapshot.array_names:
                self.assertEqual(new_result._snapshot.array(name).tobytes(), old_result._snapshot.array(name).tobytes())
            del bounds, graph, before, old_graph, old_result, new_result, old, new, ref

    def test_compact_closure_failure_keeps_paid_traceback_until_released(self):
        source = LIVE.ale_source((I/'atlas_tectonics/integration_spatial_ale.py').read_text())
        with native_module('_live_ale_failure_fixture', source) as ale:
            with LIVE.construction(self.scope, budget=self.budget):
                bounds = ale._issue(ale.SpatialALEBounds, tiny_bounds(), self.budget)
            baseline = self.budget.reserved_bytes
            held = []
            try:
                ale.close_spatial_ale(bounds, {'a': Fraction(9), 'b': Fraction(1)}, budget=self.budget)
            except Exception as error:
                self.assertIn('outside its certified', str(error))
                held.append(error)
            else:
                self.fail('invalid original carried bound accepted')
            del bounds
            self.assertGreater(self.budget.reserved_bytes, baseline)
            held.clear()
            control = self.scope.stats().purpose_bytes['retained:scope-control']
            self.assertEqual(self.scope.stats().retained_bytes, control)
            self.assertEqual(self.budget.reserved_bytes, control)

    def test_nested_native_access_reuses_only_same_live_holder(self):
        from atlas_tectonics import integration_spatial_ale as ordinary
        bounds = ordinary._issue(ordinary.SpatialALEBounds, tiny_bounds(), self.budget)
        other = ordinary._issue(ordinary.SpatialALEBounds, tiny_bounds(), self.budget)
        with LIVE.record_access(bounds) as first:
            charged = self.budget.reserved_bytes
            with LIVE.record_access(bounds) as second:
                self.assertIs(second, first)
                self.assertEqual(self.budget.reserved_bytes, charged)
            with LIVE.record_access(other) as second:
                self.assertIsNot(second, first)
                self.assertGreater(self.budget.reserved_bytes, charged)
            first['schema'] = 'changed'
            with self.assertRaisesRegex(ContractError, 'working record changed'):
                with LIVE.record_access(bounds):
                    pass
        self.assertEqual(LIVE._LEGACY_READS.get(), ())
        del first, second, bounds, other

    def test_scope_foreign_owner_and_row_escape_stay_paid(self):
        source = LIVE.ale_source((I/'atlas_tectonics/integration_spatial_ale.py').read_text())
        with native_module('_live_ale_scope_fixture', source) as ale:
            with LIVE.construction(self.scope, budget=self.budget):
                bounds = ale._issue(ale.SpatialALEBounds, tiny_bounds(), self.budget)
            with self.assertRaises(ContractError):
                with LIVE.record_access(bounds, scope=None):
                    pass
            with self.assertRaises(ContractError):
                with LIVE.construction(self.scope, budget=WorkBudget(1 << 30)):
                    pass
            with LIVE.record_access(bounds, scope=self.scope) as working:
                row = next(iter(working['cells']))
            del bounds
            self.assertGreater(self.budget.reserved_bytes, 0)
            self.assertEqual(row['cell_id'], 'a')
            del row, working


if __name__ == '__main__':
    unittest.main()
