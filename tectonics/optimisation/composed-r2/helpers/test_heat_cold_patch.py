"""Exact r9 arithmetic/order parity and compact r10 consumer lifetimes.

The equations execute on independent Fraction arithmetic. Full native forward
and completed-workflow integration are the owning Step7 composition tests.
"""
import ast
from contextlib import ExitStack, contextmanager, nullcontext
from copy import deepcopy
from dataclasses import dataclass, field
from fractions import Fraction
from hashlib import sha256
import gc
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'runtime-integration-r1/runtime-src'))
sys.path.insert(0, str(HERE.parent))
from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope
from heat_ledger_tables import CompactHeatSnapshot
from record_tables import RecordCodec
import heat_cold_patch as H
import private_heat_checkpoint_consumer_r10 as C
import private_heat_restored_binding_r10 as B
import spatial_validation_patch as V

HISTORICAL = HERE.parents[3]/'heat-repair-20261007'


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def extract(source, name, namespace=None):
    matches = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(matches) != 1:
        raise AssertionError(name)
    code = ast.Module(body=[matches[0]], type_ignores=[])
    env = {} if namespace is None else dict(namespace)
    exec(compile(code, '<exact-body:'+name+'>', 'exec'), env)
    return env[name]


class Arithmetic:
    def __init__(self, *args):
        self.trace = []
        self.G = SimpleNamespace(mpq=Fraction)

    def decode(self, value):
        if type(value) in (tuple, list):
            result = Fraction(int(value[0], 0) if value[0].startswith(('0x', '-0x')) else int(value[0]),
                              int(value[1], 0) if value[1].startswith(('0x', '-0x')) else int(value[1]))
        else:
            result = Fraction(value)
        self.trace.append(('decode', result))
        return result

    def array(self, n):
        return (None, [None]*n)

    def decoded_array(self, values, count):
        if len(values) != count:
            raise ValueError('Complete original projection array required')
        return [self.decode(v) for v in values]

    def put(self, array, at, value):
        array[1][at] = value

    def op(self, op, a, b):
        self.trace.append((op, a, b))
        return {'add': lambda: a+b, 'subtract': lambda: a-b,
                'multiply': lambda: a*b, 'divide': lambda: a/b}[op]()

    def public(self, value):
        return float(value)

    def check(self):
        pass

    def equal(self, a, b):
        return a == b

    def less(self, a, b):
        return a < b

    def minimum(self, a, b):
        return min(a, b)

    def neg(self, a):
        return -a

    def total(self, values):
        total = Fraction(0)
        for value in values:
            total = self.op('add', total, value)
        return total

    def settle(self, values):
        pass


RESOURCES = SimpleNamespace(_ProjectionArithmetic=Arithmetic,
    codec_for_value=lambda *a, **k: nullcontext(),
    stream_hash=lambda value, cancel: digest(value), check=lambda cancel: None)


def fixture():
    pair = lambda n: [str(n), '1']
    meta = dict(exact_corrected_enthalpy_j=[pair(10), pair(20)],
        independently_supplied_absolute_residual_target=pair(1),
        exact_paired_face_energy_j=[pair(0), pair(0), pair(0)],
        exact_retained_solver_residual_j=[pair(0), pair(0)],
        exact_stock_projection_residual_j=[pair(0), pair(0)],
        exact_cell_storage_residual_j=[pair(0), pair(0)],
        exact_source_energy_j=pair(0), exact_outward_boundary_energy_j=pair(0),
        caller_snapshot=dict(cell_ids=['cell-a', 'cell-b'], native_origin_signature={'owner_id': 'o'*64}),
        cell_ids=['cell-a', 'cell-b'], face_ids=['left', 'between', 'right'])
    arrays = {name: np.array(value, dtype=np.float64) for name, value in dict(
        input_enthalpy_j=[10, 20], input_capacity_j_k=[1, 1], input_source_w=[0, 0],
        enthalpy_j=[10, 20], temperature_k=[10, 20]).items()}
    geometry = SimpleNamespace(_cells=[{}, {}], _face_ids=['left', 'between', 'right'],
                               _incidence=[[(0, 1)], [(0, 1), (1, -1)], [(1, 1)]])
    plan = dict(absolute_residual_target=pair(1), boundary={})
    return meta, arrays, geometry, plan


def run_equations(fn, ar, meta, geometry, arrays, plan):
    try:
        fn(ar, meta, geometry, arrays, plan, 1.)
        result = ('pass',)
    except (ValueError, TypeError, KeyError) as exc:
        result = (type(exc).__name__, str(exc))
    return result, ar.trace


class HeatConsumerTests(unittest.TestCase):
    def test_equations_exact_ast_trace_and_mutation_parity(self):
        original = (HISTORICAL/'private_heat_checkpoint_consumer_r9.py').read_text(encoding='utf8')
        old, new = extract(original, '_equations'), extract(C.transform(original), '_equations')
        meta, arrays, geometry, plan = fixture()
        mutations = [('valid', lambda m, a: None),
            ('stock', lambda m, a: m['exact_corrected_enthalpy_j'].__setitem__(0, ['11', '1'])),
            ('target', lambda m, a: m.update(independently_supplied_absolute_residual_target=['2', '1'])),
            ('face-count', lambda m, a: m['exact_paired_face_energy_j'].pop()),
            ('face', lambda m, a: m['exact_paired_face_energy_j'].__setitem__(0, ['1', '1'])),
            ('retained', lambda m, a: m['exact_retained_solver_residual_j'].__setitem__(0, ['1', '1'])),
            ('projection', lambda m, a: m['exact_stock_projection_residual_j'].__setitem__(0, ['1', '1'])),
            ('storage', lambda m, a: m['exact_cell_storage_residual_j'].__setitem__(0, ['1', '1'])),
            ('source', lambda m, a: m.update(exact_source_energy_j=['1', '1'])),
            ('boundary', lambda m, a: m.update(exact_outward_boundary_energy_j=['1', '1'])),
            ('float-stock', lambda m, a: a['enthalpy_j'].__setitem__(0, 11.)),
            ('temperature', lambda m, a: a['temperature_k'].__setitem__(0, 11.))]
        for name, mutate in mutations:
            with self.subTest(name=name):
                value, fields = deepcopy(meta), {k: v.copy() for k, v in arrays.items()}
                mutate(value, fields)
                expected = run_equations(old, Arithmetic(), value, geometry, fields, plan)
                budget = WorkBudget(384 << 20)
                scope = create_retained_scope(budget, process_epoch='wp7-equations')
                snapshot = CompactHeatSnapshot.from_components(value, fields, scope=scope)
                with H.ledger_access(snapshot, budget, None, RESOURCES) as view:
                    actual = run_equations(new, H.ledger_arithmetic(RESOURCES)(), view.value, geometry, fields, plan)
                self.assertEqual(actual, expected)
                self.assertEqual(actual[0][0], 'pass' if name == 'valid' else 'ValueError')
                snapshot.close()
                gc.collect()
                scope.close()
                self.assertEqual(budget.reserved_bytes, 0)

    def test_validate_preserves_original_fixture_source_and_native_refusal_gates(self):
        original = (HISTORICAL/'private_heat_checkpoint_consumer_r9.py').read_text(encoding='utf8')
        transformed = C.transform(original)
        meta, fields, geometry, plan = fixture()
        geometry.geometry_id = 'g'*64
        encoded_plan = json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()
        origin = dict(meta['caller_snapshot'], state_id='s'*64, duration_s=1.,
                      loaded_dependencies={'identity': 'd'*64})
        meta.update(schema='test.heat', method_id='test.method',
            fixed_forward_producer='private_heat_forward_kernel_r13.advance', call_id='c'*64,
            caller_snapshot=origin, state_id=origin['state_id'], duration_s=origin['duration_s'],
            plan_id=sha256(encoded_plan).hexdigest(), geometry_id=geometry.geometry_id,
            loaded_dependencies=origin['loaded_dependencies'], genuine_forward_origin=True,
            origin_binding_status='FORWARD_ACTUAL_OWNER_SNAPSHOT', native_issue_performed=False,
            native_resource_admitted=False, native_heat_dispatch_enabled=False,
            production_acceptance=False, whole_method_memory_inventory_certified=False,
            endpoint_face_trace_status='unavailable')
        names = tuple(sorted(fields))
        class Workspace:
            def __init__(self, *args, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        resources = SimpleNamespace(**vars(RESOURCES),
            decoded=lambda blob, **kwargs: nullcontext(SimpleNamespace(value=json.loads(blob))),
            A=SimpleNamespace(exact_library=lambda: None), O=SimpleNamespace(_OwnerWorkspace=Workspace))
        issuer = SimpleNamespace(SCHEMA='test.heat', METHOD='test.method', np=np,
            N=SimpleNamespace(A=SimpleNamespace(TRACE_STATUS='unavailable')),
            _verified_call=lambda call, cancel: nullcontext(SimpleNamespace(value=origin)),
            _verify_call=lambda call, cancel: None,
            F=SimpleNamespace(METER=SimpleNamespace(scope=lambda *a: nullcontext())))
        def identity(snapshot, budget, cancel):
            if isinstance(snapshot, CompactHeatSnapshot):
                return snapshot.verify_identity()
            return digest(dict(metadata=json.loads(snapshot._metadata), arrays={k: dict(
                shape=list(v.shape), sha256=sha256(memoryview(v).cast('B')).hexdigest()) for k, v in fields.items()}))
        issuer._snapshot_identity = identity
        namespace = dict(R=resources, I=issuer, _verify=lambda cancel: None, _FIELDS=names,
                         sha256=sha256, sys=sys, _HC=H)
        old = extract(original, '_validate', dict(namespace, _equations=extract(original, '_equations')))
        new = extract(transformed, '_validate', dict(namespace, _equations=extract(transformed, '_equations')))
        cases = [('valid', lambda m: None)]
        cases += [(name, lambda m, key=name: m.update({key: True})) for name in
            ('native_issue_performed', 'native_resource_admitted', 'native_heat_dispatch_enabled',
             'production_acceptance', 'whole_method_memory_inventory_certified')]
        cases += [(name, lambda m, key=name: m.update({key: 'changed'})) for name in
            ('schema', 'method_id', 'call_id', 'state_id', 'geometry_id', 'plan_id',
             'fixed_forward_producer', 'endpoint_face_trace_status', 'origin_binding_status')]
        cases += [('fixture', lambda m: m.update(genuine_forward_origin=False)),
                  ('origin', lambda m: m['caller_snapshot'].update(state_id='x'*64)),
                  ('face-order', lambda m: m['face_ids'].reverse()),
                  ('cell-order', lambda m: m['cell_ids'].reverse()),
                  ('duration', lambda m: m.update(duration_s=2.)),
                  ('runtime', lambda m: m.update(loaded_dependencies={'identity': 'x'*64}))]
        with patch.dict(sys.modules, {'private_heat_gmp_resources_r1': SimpleNamespace(OwnedWorkspace=Workspace)}):
            for name, change in cases:
                with self.subTest(name=name):
                    value = deepcopy(meta)
                    change(value)
                    budget = WorkBudget(384 << 20)
                    scope = create_retained_scope(budget, process_epoch='wp7-provenance')
                    snapshot = CompactHeatSnapshot.from_components(value, fields, scope=scope)
                    native = SimpleNamespace(_metadata=json.dumps(value).encode(), result_id=snapshot.result_id,
                                             array_names=names, array=lambda key: fields[key])
                    call = SimpleNamespace(_budget=budget, call_id='c'*64, _plan=encoded_plan, _geometry=geometry,
                        _fixture=False, _snapshot=SimpleNamespace(array=lambda key: fields['input_'+key]))
                    def outcome(fn, arg):
                        try:
                            fn(arg, call, expected_result_id=snapshot.result_id)
                            return ('pass',)
                        except (ValueError, TypeError) as exc:
                            return (type(exc).__name__, str(exc))
                    actual = outcome(new, snapshot)
                    self.assertEqual(outcome(old, native), actual)
                    self.assertEqual(actual[0], 'pass' if name == 'valid' else 'ValueError')
                    gc.collect()
                    snapshot.close()
                    scope.close()
                    self.assertEqual(budget.reserved_bytes, 0)

    def test_nested_origin_order_and_call_hash_are_exact(self):
        meta, fields, _, _ = fixture()
        budget = WorkBudget(384 << 20)
        scope = create_retained_scope(budget, process_epoch='wp7-origin')
        snapshot = CompactHeatSnapshot.from_components(meta, fields, scope=scope)
        with H.ledger_access(snapshot, budget, None, RESOURCES) as view:
            origin = view.value['caller_snapshot']
            self.assertEqual(origin, meta['caller_snapshot'])
            self.assertEqual(origin['cell_ids'], meta['cell_ids'])
            self.assertNotEqual(origin['cell_ids'], list(reversed(meta['cell_ids'])))
            self.assertEqual(set(origin['native_origin_signature']), {'owner_id'})
            self.assertEqual(H.call_identity(origin, fields, RESOURCES, None),
                H.call_identity(meta['caller_snapshot'], fields, RESOURCES, None))
        snapshot.close()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_escaped_row_and_held_exception_keep_funding(self):
        meta, fields, _, _ = fixture()
        budget = WorkBudget(384 << 20)
        scope = create_retained_scope(budget, process_epoch='wp7-owned-row')
        snapshot = CompactHeatSnapshot.from_components(meta, fields, scope=scope)
        with H.ledger_access(snapshot, budget, None, RESOURCES) as view:
            row = view.value['exact_corrected_enthalpy_j'][0]
        snapshot.close()
        self.assertEqual(row.value, ['10', '1'])
        self.assertGreater(scope.stats().retained_bytes, 4096)
        del row
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

        scope = create_retained_scope(budget, process_epoch='wp7-held-failure')
        snapshot = CompactHeatSnapshot.from_components(meta, fields, scope=scope)
        held = None
        try:
            with H.ledger_access(snapshot, budget, None, RESOURCES) as view:
                raise ValueError(view.value['exact_corrected_enthalpy_j'][0])
        except ValueError as exc:
            held = exc
        with self.assertRaisesRegex(RuntimeError, 'live child borrows'):
            snapshot.close()
        self.assertGreater(scope.stats().retained_bytes, 4096)
        held.__traceback__ = None
        held = view = None
        gc.collect()
        snapshot.close()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_endpoint_index_reads_one_compact_row_and_preserves_last_duplicate_rule(self):
        budget = WorkBudget(384 << 20)
        scope = create_retained_scope(budget, process_epoch='wp7-endpoint')
        rows = [{'cell_id': 'b', 'exact': {'enthalpy_j': ['2', '1']}},
                {'cell_id': 'a', 'exact': {'enthalpy_j': ['1', '1']}},
                {'cell_id': 'a', 'exact': {'enthalpy_j': ['3', '1']}}]
        record = RecordCodec().pack_record(rows, record_schema='test.cells', scope=scope, check=lambda: None)
        with record.root() as ref:
            lookup = H.endpoint_cells(V.rows(ref))
            actual = lookup['a']
            self.assertEqual(actual, rows[2])
            self.assertEqual(lookup['b'], rows[0])
        record.close()
        self.assertEqual(actual['exact']['enthalpy_j'], ['3', '1'])
        del actual, lookup
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_source_stages_and_recovery_index_rule(self):
        source = (HISTORICAL/'private_heat_restored_binding_r9.py').read_text(encoding='utf8')
        transformed = B.transform(source)
        self.assertIn('_HC.ledger_access(saved.value', transformed)
        self.assertIn('_HC.state_view(state._snapshot', transformed)
        with self.assertRaises(ValueError):
            B.transform(transformed)
        recovery = (HERE.parents[1]/'runtime-integration-r1/ram/private_heat_restored_binding_ram_recovery_r1.py').read_text(encoding='utf8')
        old = extract(recovery, '_collar_flat_index', {'np': np})
        new = extract(transformed, '_collar_flat_index', {'np': np})
        for index in (0, 7, [0, 1, 1], [1, 1, 1], -1, 8, [1, 2, 0], (0, 0, 0), True):
            def outcome(fn):
                try:
                    return ('pass', fn(index, (2, 2, 2)))
                except (ValueError, TypeError) as exc:
                    return (type(exc).__name__, str(exc))
            self.assertEqual(outcome(old), outcome(new))
        import workflow_transfer as W
        import partition_workflow_transform as P
        cold = (HERE.parents[1]/'runtime-integration-r1/runtime-src/atlas_tectonics/integration_private_heat_cold.py').read_text(encoding='utf8')
        result = H.transform(P.cold_source(W.private_heat_cold_source(cold)))
        self.assertIn('import private_heat_restored_binding_r10 as B', result)
        self.assertIn('with _SV.access(exchange)', result)
        self.assertNotIn('store.get(', result)
        with self.assertRaises(ValueError):
            H.transform(result)

    def test_actual_restored_binding_validate_for_compact_exchange(self):
        """Run the generated dataclass method; upstream context is a fixture.

        Exact compact exchange identity, actual-object boundary, stored heat
        snapshot identity and native audit-array gates execute unchanged.
        """
        from collections.abc import Mapping
        source = B.transform((HISTORICAL/'private_heat_restored_binding_r9.py').read_text(encoding='utf8'))
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'RestoredHeatBinding')
        budget = WorkBudget(384 << 20)
        scope = create_retained_scope(budget, process_epoch='wp7-validate-for')
        metadata, arrays, _, _ = fixture()
        snapshot = CompactHeatSnapshot.from_components(metadata, arrays, scope=scope)
        exchange = {'schema': 'test.exchange', 'result_id': 'e'*64, 'joined_heat_id': snapshot.result_id}
        record = RecordCodec().pack_record(exchange, record_schema='test.exchange', scope=scope, check=lambda: None)
        owner, parent, parent_collar, state, collar, mesh, audit, execution, target = [object() for _ in range(9)]
        transport_fields = {'stock': np.array([1., 2.])}
        transport = SimpleNamespace(array_names=('stock',), array=lambda key: transport_fields[key])
        calls = []
        def context(*args, **kwargs):
            calls.append(args)
        @contextmanager
        def workspace(budget, size, **kwargs):
            with budget.reserve(size, category='wp7-test-context'), ExitStack() as stack:
                yield SimpleNamespace(stack=stack)
        resources = SimpleNamespace(**vars(RESOURCES), workspace=workspace)
        namespace = dict(dataclass=dataclass, field=field, R=resources, _SV=V, np=np, json=json,
            C=SimpleNamespace(_FIELDS=tuple(sorted(arrays))), _context=context, _verify=lambda *a: None)
        namespace['_snapshot'] = extract(source, '_snapshot', dict(namespace, RegionalMechanicalSnapshot=object))
        namespace['_same_arrays'] = extract(source, '_same_arrays', namespace)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual-r10-restored-binding>', 'exec'), namespace)
        cls = namespace['RestoredHeatBinding']
        binding = object.__new__(cls)
        for key, value in dict(_snapshot=snapshot, _geometry=object(), _exchange_identity=digest(exchange),
            _plan=b'{}', fixture_only=False, _context=(owner, parent, parent_collar, state, collar, mesh,
                transport, audit, execution, target, budget)).items():
            object.__setattr__(binding, key, value)
        audits = dict(**{'spatial-transport:'+k: v for k, v in transport_fields.items()},
                      **{'joined-heat:'+k: v for k, v in arrays.items()})
        with record.root() as ref:
            self.assertNotIsInstance(ref, Mapping)
            binding.validate_for(owner, state, collar, ref, audit_arrays=audits)
            self.assertEqual(len(calls), 1)
            for wrong in ((object(), state, collar), (owner, object(), collar), (owner, state, object())):
                with self.assertRaisesRegex(ValueError, 'different actual owner/endpoint'):
                    binding.validate_for(*wrong, ref)
            changed_arrays = dict(audits)
            changed_arrays['joined-heat:enthalpy_j'] = np.array([11., 20.])
            with self.assertRaisesRegex(ValueError, 'audit arrays differ'):
                binding.validate_for(owner, state, collar, ref, audit_arrays=changed_arrays)
        changed = RecordCodec().pack_record(dict(exchange, joined_heat_id='x'*64),
            record_schema='test.exchange', scope=scope, check=lambda: None)
        with changed.root() as ref:
            with self.assertRaisesRegex(ValueError, 'committed exchange changed'):
                binding.validate_for(owner, state, collar, ref)
        record.close()
        changed.close()
        snapshot.close()
        del binding
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
