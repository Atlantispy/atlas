"""WP6 route parity on exact native validation bodies, without a physics run.

Fixture ownership/checkpoint boundaries are synthetic; the native mathematical
and provenance gates under test are not replaced. This is component evidence,
not IV2, migration, a fresh reader or scientific acceptance.
"""
import ast
from contextlib import contextmanager, nullcontext, ExitStack
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
import json
import gc
from pathlib import Path
import sys
from time import perf_counter
import textwrap
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[1]/'runtime-integration-r1'/'runtime-src'
HISTORICAL = HERE.parents[3]/'heat-repair-20261007'
sys.path.insert(0, str(RUNTIME))
from atlas_tectonics import integration_spatial_owner as O
from atlas_tectonics import integration_spatial_reservoir as F
from atlas_tectonics import integration_dual_measures as D
from atlas_tectonics import integration_regional_workflow as W
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from content_cache import create_retained_scope
from record_tables import RecordCodec
from record_views import LogicalExchange, RecordRef
import spatial_validation_patch as V


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def body_functions(source, namespace, names):
    result = dict(namespace, _SV=V)
    for name in names:
        matches = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name]
        if len(matches) != 1:
            raise AssertionError((name, len(matches)))
        node = matches[0]
        part = '\n'.join(source.splitlines()[node.lineno-1:node.end_lineno])
        exec(compile(textwrap.dedent(part), '<exact-validation-body:'+name+'>', 'exec'), result)
    return SimpleNamespace(**result)


@contextmanager
def compact(value, budget, *, exchange=False):
    scope = create_retained_scope(budget, process_epoch='wp6-validation-fixture')
    body = {k: v for k, v in value.items() if k not in ('state_id', 'result_id')} if exchange == 'overlay' else value
    record = RecordCodec().pack_record(body, record_schema='wp6.fixture.v1', scope=scope, check=lambda: None)
    if exchange == 'overlay':
        ref = LogicalExchange.from_body(record, state_id=value['state_id'], result_id=value['result_id'])
    else:
        ref = record.root()
    if exchange is True:
        public = LogicalExchange(record, ref.index)
        ref.close()
        ref = public
    try:
        yield ref
    finally:
        gc.collect()
        ref.close()
        record.close()
        # create_retained_scope is intentionally shared per WorkBudget. A
        # nested compact fixture must leave its sibling's backing alive.
        stats = scope.stats()
        if stats.retained_bytes == stats.purpose_bytes['retained:scope-control']:
            scope.close()


def outcome(call):
    try:
        return ('accepted', call())
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return ('refused', type(exc).__name__, str(exc))


def fixture(budget):
    enc = O._enc
    graph = dict(schema='graph.fixture', bounds_id='b'*64, cells=[
        dict(cell_id='cell-a', kind='exterior', index=0, start_volume_m3=enc(Fraction(1)), end_volume_m3=enc(Fraction(1))),
        dict(cell_id='cell-b', kind='collar', index=0, start_volume_m3=enc(Fraction(2)), end_volume_m3=enc(Fraction(2)))],
        transfers=[], support_ids=['a'*64], interval_id='i'*64,
        trajectory='fixture', start_support_id='a'*64, end_support_id='a'*64)
    policy = {name: enc(Fraction(0)) for name in D._LIMITS}
    stock = {D.B_NAME: [enc(Fraction(1)), enc(Fraction(2))]}
    transport = dict(geometry_id=digest(graph), state_id='p'*64, source_stage_id='q'*64,
        cell_ids=['cell-a', 'cell-b'], exact_input_stocks=deepcopy(stock), exact_stocks=deepcopy(stock),
        exact_projection_accounts={D.B_NAME: [enc(Fraction(0)), enc(Fraction(0))]},
        nonnegative_fields=[D.B_NAME])
    ta = {'stock': np.array([1., 2.])}
    transport['result_id'] = RegionalMechanicalSnapshot(transport, ta).result_id
    label, option = O.HEAT_METHODS['hybrid-mimetic']
    plan = dict(schema='atlas.mimetic-heat-plan.v1', positivity_method=option,
        geometry_id='m'*64, cells=2, faces=0, conductivity_w_m_k=[1., 1.])
    heat = dict(state_id=transport['result_id'], geometry_id='m'*64, plan_id=digest(plan))
    ha = {'energy': np.array([3., 4.])}
    audit = D.transport_audit(graph, transport, {'cell-a': Fraction(1), 'cell-b': Fraction(2)}, policy, budget=budget)
    exchange = dict(schema='atlas.spatial-exterior-advance.v1', owner_id='o'*64,
        parent_state_id='p'*64, collar_state_id='c'*64, spatial_graph=graph, spatial_graph_id=digest(graph),
        transport=transport, global_transport_id=transport['result_id'], joined_heat=heat,
        joined_heat_id=RegionalMechanicalSnapshot(heat, ha).result_id, joined_heat_plan=plan,
        dual_measure_audit=audit)
    state = SimpleNamespace(state_id='a'*64)
    exchange['result_id'] = digest(dict(state_id=state.state_id, exchange=exchange))
    exchange['state_id'] = state.state_id
    saved = dict(parent_state_id='p'*64, collar_state_id='c'*64, thermal_mesh_id='m'*64,
        thermal_mesh={'cells': [{}, {}], 'faces': []}, cells=[dict(cell_id='cell-a', exact={D.B_NAME: enc(Fraction(1))})],
        native_material_quadrature_m3=[enc(Fraction(2))])
    owner = SimpleNamespace(owner_id='o'*64, _budget=budget, _bound=lambda s: saved,
        _finite=None, _measure_policy=policy, _heat_label=label, _definition={'conductivity_w_m_k': 1.})
    owner._validate_heat_plan = MethodType(O.PreparedSpatialOwner._validate_heat_plan, owner)
    arrays = {'spatial-transport:'+k: v for k, v in ta.items()}
    arrays.update({'joined-heat:'+k: v for k, v in ha.items()})
    return owner, state, exchange, arrays, saved


def variants(exchange):
    """One valid exchange plus twelve independently corrupted exchanges."""
    yield 'valid', deepcopy(exchange)
    mutations = (
        ('owner', lambda e: e.update(owner_id='x'*64)),
        ('parent', lambda e: e.update(parent_state_id='x'*64)),
        ('collar', lambda e: e.update(collar_state_id='x'*64)),
        ('graph-id', lambda e: e.update(spatial_graph_id='x'*64)),
        ('graph-volume', lambda e: e['spatial_graph']['cells'][0].update(end_volume_m3=['0x2', '0x1'])),
        ('transport-id', lambda e: e.update(global_transport_id='x'*64)),
        ('heat-state', lambda e: e['joined_heat'].update(state_id='x'*64)),
        ('heat-geometry', lambda e: e['joined_heat'].update(geometry_id='x'*64)),
        ('heat-plan', lambda e: e['joined_heat_plan'].update(conductivity_w_m_k=[2., 1.])),
        ('result-id', lambda e: e.update(result_id='f'*64)),
        ('transport-stock', lambda e: e['transport']['exact_stocks'][D.B_NAME].__setitem__(0, ['0x2', '0x1'])),
        ('dual-audit', lambda e: e['dual_measure_audit'].update(input_l1_m3=['0x1', '0x1'])),
    )
    for name, mutate in mutations:
        value = deepcopy(exchange)
        mutate(value)
        yield name, value


class SpatialValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.originals = {name: Path(module.__file__).read_text(encoding='utf-8') for name, module in
                         [('owner', O), ('reservoir', F), ('measures', D), ('workflow', W)]}
        cls.measures = body_functions(V.measures_source(cls.originals['measures']), vars(D),
            ['_dual_audit_capacity', '_transport_audit', 'transport_audit'])
        cls.owner = body_functions(V.owner_source(cls.originals['owner']),
            dict(vars(O), transport_audit=cls.measures.transport_audit), ['_validate_heat_plan', 'validate_exchange'])
        cls.finite = body_functions(V.reservoir_source(cls.originals['reservoir']), vars(F),
                                   ['_finished_record', 'validate_saved'])
        cls.workflow = body_functions(V.workflow_source(cls.originals['workflow']), vars(W),
                                     ['_check_certification_records'])

    def test_source_anchors_compile_and_refuse_drift_or_double_application(self):
        for name in ('owner', 'reservoir', 'measures', 'workflow'):
            transform = getattr(V, name+'_source')
            original = self.originals[name]
            ast.parse(transform(original))
            with self.assertRaises(V.ContractError):
                transform(transform(original))
        with self.assertRaises(V.ContractError):
            V.owner_source(self.originals['owner'].replace("_hash(exchange['spatial_graph'])", 'changed_anchor'))
        for path, transform in [('private_heat_joined_consumer_r6.py', V.joined_source),
                                ('private_heat_restored_binding_r9.py', V.context_source)]:
            source = (HISTORICAL/path).read_text(encoding='utf-8')
            ast.parse(transform(source))
            with self.assertRaises(V.ContractError):
                transform(transform(source))

    def test_twelve_exchange_mutations_owner_and_dual_routes_all_input_types(self):
        budget = WorkBudget(128 << 20)
        owner, state, initial, arrays, saved = fixture(budget)
        coverage = 0
        for name, exchange in variants(initial):
            owner._validate_heat_plan = MethodType(O.PreparedSpatialOwner._validate_heat_plan, owner)
            expected = outcome(lambda: O.PreparedSpatialOwner.validate_exchange(owner, state, exchange, audit_arrays=arrays))
            owner._validate_heat_plan = MethodType(self.owner._validate_heat_plan, owner)
            if name == 'valid':
                self.assertEqual(expected, ('accepted', None))
            else:
                self.assertEqual(expected[0], 'refused', name)
            for kind in ('legacy', 'ref', 'exchange', 'overlay'):
                mode = 'overlay' if kind == 'overlay' else kind == 'exchange'
                with (nullcontext(exchange) if kind == 'legacy' else compact(exchange, budget, exchange=mode)) as value:
                    if kind != 'legacy':
                        from collections.abc import Mapping
                        self.assertNotIsInstance(value, Mapping)
                    actual = outcome(lambda: self.owner.validate_exchange(owner, state, value, audit_arrays=arrays))
                    self.assertEqual(actual, expected, (name, kind, 'owner'))
                    coverage += 1
            graph, result = exchange['spatial_graph'], exchange['transport']
            arguments = ({'cell-a': Fraction(1), 'cell-b': Fraction(2)}, owner._measure_policy)
            for route in ('transport_audit', '_transport_audit', '_dual_audit_capacity'):
                old = getattr(D, route)
                new = getattr(self.measures, route)
                def invoke(fn, g, r):
                    if route == 'transport_audit':
                        return fn(g, r, *arguments, budget=budget)
                    if route == '_dual_audit_capacity':
                        return fn(g, r, *arguments, budget)
                    return fn(g, r, *arguments)
                expected = outcome(lambda: invoke(old, graph, result))
                for kind in ('legacy', 'ref', 'exchange'):
                    with ExitStack() as stack:
                        g = graph if kind == 'legacy' else stack.enter_context(compact(graph, budget, exchange=kind == 'exchange'))
                        r = result if kind == 'legacy' else stack.enter_context(compact(result, budget))
                        self.assertEqual(outcome(lambda: invoke(new, g, r)), expected, (name, kind, route))
                        coverage += 1
            gc.collect()  # Paid refusal tracebacks are released, never credited early.
            scope = create_retained_scope(budget, process_epoch='wp6-validation-fixture')
            scope.close()
            self.assertEqual(budget.reserved_bytes, 0)
        print('WP6 owner/dual route comparisons:', coverage)

    def test_finite_saved_and_finished_record_twelve_mutations(self):
        budget = WorkBudget(128 << 20)
        owner, state, initial, arrays, saved = fixture(budget)
        parent = dict(state_id='f'*64, intervals=0, stocks=[], projection_accounts={})
        fake = SimpleNamespace(owner_id='f'*64, _budget=budget, _verify=lambda: None,
            _positive=(D.B_NAME,), _names=(D.B_NAME,), restore=lambda value: None,
            _check_fields=lambda value: None)
        for name, exchange in variants(initial):
            graph, transport = exchange['spatial_graph'], exchange['transport']
            proposal = dict(owner_id=fake.owner_id, graph=graph, parent=parent,
                transport_parent_id=exchange['parent_state_id'], source_stage_id='q'*64,
                stocks=deepcopy(initial['transport']['exact_input_stocks']))
            proposal['proposal_id'] = digest(proposal)
            if name == 'result-id':
                proposal['proposal_id'] = 'x'*64
            if name == 'owner':
                proposal['owner_id'] = 'x'*64
            expected_state = F.PreparedFiniteStocks._finished_record(fake,
                dict(proposal, graph=initial['spatial_graph'], transport_parent_id='p'*64), initial['transport'])
            state_record = dict(state_id=digest(expected_state), **expected_state)
            fake._finished_record = MethodType(F.PreparedFiniteStocks._finished_record, fake)
            expected = outcome(lambda: F.PreparedFiniteStocks.validate_saved(fake, state_record, proposal, transport))
            expected_finished = outcome(lambda: F.PreparedFiniteStocks._finished_record(fake, proposal, transport))
            for kind in ('legacy', 'ref', 'exchange'):
                with ExitStack() as stack:
                    p = proposal if kind == 'legacy' else stack.enter_context(compact(proposal, budget, exchange=kind == 'exchange'))
                    r = transport if kind == 'legacy' else stack.enter_context(compact(transport, budget))
                    fake._finished_record = MethodType(self.finite._finished_record, fake)
                    self.assertEqual(outcome(lambda: self.finite.validate_saved(fake, state_record, p, r)), expected, (name, kind))
                    self.assertEqual(outcome(lambda: self.finite._finished_record(fake, p, r)), expected_finished, (name, kind))
            self.assertEqual(budget.reserved_bytes, 0)

    def test_row_memory_is_bounded_at_three_point_eight_scale_no_graph_export(self):
        measurements = []
        for size in (1000, 3800):
            budget = WorkBudget(128 << 20)
            graph = dict(cells=[dict(cell_id=str(i).zfill(4), kind='exterior', start_volume_m3=['0x1', '0x1'],
                end_volume_m3=['0x1', '0x1'], payload='r'*256) for i in range(size)])
            with compact(graph, budget) as ref:
                baseline = budget.reserved_bytes
                high = baseline
                original_export = RecordRef.export
                def guarded_export(value, **kwargs):
                    self.assertNotEqual(value.index, ref.index, 'whole graph export attempted')
                    return original_export(value, **kwargs)
                started = perf_counter()
                with patch.object(RecordRef, 'export', guarded_export), V.access(ref) as view:
                    count = 0
                    for row in view['cells']:
                        high = max(high, budget.reserved_bytes)
                        count += 1
                        self.assertEqual(row['end_volume_m3'], ['0x1', '0x1'])
                    self.assertEqual(count, size)
                    del row
                self.assertLessEqual(high-baseline, V.ROW_BYTES)
                self.assertEqual(budget.reserved_bytes, baseline)
                measurements.append(dict(rows=size, row_peak_reserved_bytes=high-baseline,
                                         elapsed_seconds=perf_counter()-started))
            self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(measurements[0]['row_peak_reserved_bytes'], measurements[1]['row_peak_reserved_bytes'])
        print('WP6 row allocation measurements (not process RAM):', json.dumps(measurements))

    def test_oversized_small_field_and_transport_refuse_before_decode(self):
        budget = WorkBudget(256 << 20)
        # Sharing makes columns tiny while logical output is over the admitted
        # export size. The charge bound, not storage compression, is decisive.
        for field, limit in [('support_ids', V.SMALL_BYTES), ('transport', V.TRANSPORT_BYTES)]:
            value = {field: ['x'*1024]*(limit//1024+1)}
            with compact(value, budget) as ref, V.access(ref) as view:
                with self.assertRaisesRegex(ValueError, 'bound'):
                    view[field]
            self.assertEqual(budget.reserved_bytes, 0)

    def test_failed_traceback_and_retained_row_keep_their_decodes_paid(self):
        budget = WorkBudget(128 << 20)
        scope = create_retained_scope(budget, process_epoch='wp6-exception')
        packed = RecordCodec().pack_record({'transport': {'value': 'x'*256},
            'cells': [{'value': 'r'*256}]}, record_schema='wp6.failure', scope=scope, check=lambda: None)
        ref = packed.root()
        baseline = budget.reserved_bytes
        def fail():
            with V.access(ref) as value:
                decoded = value['transport']
                self.assertEqual(decoded['value'], 'x'*256)
                raise ValueError('held validation refusal')
        error = None
        try:
            fail()
        except ValueError as exc:
            error = exc
        gc.collect()
        self.assertGreater(scope.stats().purpose_bytes['retained:record-export'], 0)
        self.assertGreater(budget.reserved_bytes, baseline)
        with self.assertRaises(RuntimeError):
            ref.close()
        error.__traceback__ = None
        error = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        with V.access(ref) as value:
            retained = list(value['cells'])
        self.assertGreater(scope.stats().purpose_bytes['retained:record-export'], 0)
        self.assertEqual(retained[0]['value'], 'r'*256)
        retained.clear()
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        ref.close(); packed.close(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_representative_metadata_and_transport_fit_unchanged_export_caps(self):
        budget = WorkBudget(256 << 20)
        count = 7700
        support_ids = [format(i, '064x') for i in range(count)]
        pairs = [[hex((1 << 100)+i), hex(1 << 100)] for i in range(count)]
        names = ('material_quadrature_m3', 'enthalpy_j', 'component_mass_kg:0', 'tracer:x')
        transport = dict(cell_ids=support_ids, **{group: {name: pairs for name in names}
            for group in ('exact_input_stocks', 'exact_stocks', 'exact_projection_accounts')})
        logical_bytes = len(O._json(transport))
        self.assertGreater(logical_bytes, 6_000_000)
        self.assertLess(logical_bytes, 6_800_000)
        payload = dict(support_ids=support_ids, joined_heat_plan={'conductivity_w_m_k': [1.]*count},
                       transport=transport)
        with compact(payload, budget) as ref, V.access(ref) as value:
            self.assertEqual(value['support_ids'], support_ids)
            self.assertEqual(value['joined_heat_plan']['conductivity_w_m_k'], [1.]*count)
            transported = value['transport']
            self.assertEqual(transported, transport)
            self.assertEqual(V.SMALL_BYTES, 4 << 20)
            self.assertEqual(V.TRANSPORT_BYTES, 32 << 20)
            print('WP6 representative native transport export logical bytes:', logical_bytes)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_joined_heat_routes_twelve_mutations(self):
        source = (HISTORICAL/'private_heat_joined_consumer_r6.py').read_text(encoding='utf-8')
        issuer = (HISTORICAL/'private_heat_native_issuer_r12.py').read_text(encoding='utf-8')
        target = body_functions(issuer, dict(Decimal=Decimal, Fraction=Fraction, _q=O._q,
            _target_text=lambda value: str(value)), ['_validate_target_plan'])
        budget = WorkBudget(128 << 20)
        owner, state, initial, arrays, saved = fixture(budget)
        label = 'PRIVATE uniform-k composed physical-face heat; original transported caloric stocks'
        owner._heat_label = label
        def check_saved(reference, checkpoint, *, expected_result_id, arrays, budget, cancel):
            # This route's checkpoint boundary is synthetic. It checks exact
            # reference forwarding; actual ledger validation belongs to WP7.
            if reference != initial['joined_heat'] or expected_result_id != initial['joined_heat_id']:
                raise ValueError('checkpoint reference differs')
            return expected_result_id
        namespace = dict(_verify=lambda: None, LABEL=label, sha256=sha256, _json=O._json,
            I=SimpleNamespace(METHOD='wp6.method', _validate_target_plan=target._validate_target_plan),
            validate_saved=check_saved)
        legacy = body_functions(source, namespace, ['validate_plan', 'validate_saved_exchange'])
        indexed = body_functions(V.joined_source(source), namespace, ['validate_plan', 'validate_saved_exchange'])
        checkpoint = SimpleNamespace(value=SimpleNamespace(_call=SimpleNamespace(_origin_objects=(owner,))))
        initial_plan = dict(initial['joined_heat_plan'], schema='atlas.private.composed-heat-plan.r1',
            method_id='wp6.method', original_target={'kind': 'decimal-string', 'value': '1'},
            absolute_residual_target_decimal='1', absolute_residual_target=['0x1', '0x1'])
        for name, exchange in variants(initial):
            plan = dict(initial_plan, conductivity_w_m_k=exchange['joined_heat_plan']['conductivity_w_m_k'])
            header = dict(exchange['joined_heat'], plan_id=digest(initial_plan))
            expected_plan = outcome(lambda: legacy.validate_plan(owner, plan, header, saved['thermal_mesh']))
            expected_saved = outcome(lambda: legacy.validate_saved_exchange(owner, state, exchange, arrays, checkpoint))
            for kind in ('legacy', 'ref', 'exchange'):
                with ExitStack() as stack:
                    p = plan if kind == 'legacy' else stack.enter_context(compact(plan, budget, exchange=kind == 'exchange'))
                    h = header if kind == 'legacy' else stack.enter_context(compact(header, budget))
                    e = exchange if kind == 'legacy' else stack.enter_context(compact(exchange, budget, exchange=kind == 'exchange'))
                    self.assertEqual(outcome(lambda: indexed.validate_plan(owner, p, h, saved['thermal_mesh'])), expected_plan, (name, kind))
                    self.assertEqual(outcome(lambda: indexed.validate_saved_exchange(owner, state, e, arrays, checkpoint)), expected_saved, (name, kind))
            gc.collect()
            create_retained_scope(budget, process_epoch='wp6-validation-fixture').close()
            self.assertEqual(budget.reserved_bytes, 0)

    def test_certification_and_refresh_graph_routes_twelve_mutations(self):
        from atlas_tectonics import integration_regional_driving as drive
        budget = WorkBudget(128 << 20)
        owner, state, initial, arrays, saved = fixture(budget)
        common = {key: 'a'*64 for key in ('parent_state_id', 'spatial_state_id', 'finite_state_id',
            'source_flow_stage_id', 'source_audit_id', 'force_exchange_id', 'native_measure_id',
            'interval_id', 'partition_id', 'bounds_id')}
        graph = dict(initial['spatial_graph'], **common)
        force_record = dict(schema=drive.SCHEMA+'.result', native_result_id='a'*64, parent_state_id='a'*64,
            time_s=0, algebra_relative_residual=0, virtual_work_relative_residual=0, driving={'plate_ids': []})
        force = SimpleNamespace(result_id='a'*64, descriptor=lambda: force_record, array=lambda key: np.empty((0, 3)))
        interval = dict(start_time_s=['0x0', '0x1'], end_time_s=['0x1', '0x1'], plate_angular_velocity_rad_s={})
        source_audit = dict(initial_mechanics_id='a'*64, parent_state_id='a'*64, start_time_s=0)
        audit = dict(common, schema='atlas.differential-final-trace-audit.v1', native_result_id='a'*64,
            start_time_s=interval['start_time_s'], end_time_s=interval['end_time_s'],
            velocity_replaced=False, source_heat_reapplied=False, force_algebra_relative_residual=0,
            force_virtual_work_relative_residual=0, trace_account=dict(l2_error_squared_bounds=[['0x0', '0x1']]*2,
                work_error_squared_upper=['0x0', '0x1']), max_l2_error_squared=['0x0', '0x1'],
            max_work_error=['0x0', '0x1'], angular_velocity_rad_s={})
        iteration = dict(common, schema='atlas.differential-iteration.v1', native_state_id='a'*64,
                         parent_partition_id='a'*64, current_geometry_id='a'*64)
        iteration['iteration_id'] = digest(iteration)
        proposal = dict(common, schema='atlas.differential-force-proposal.v1', iteration_id=iteration['iteration_id'],
                        published=False, accepted_heat_state_advanced=False)
        proposal['proposal_id'] = digest(proposal)
        solution = dict(common, schema='atlas.differential-interval-solution.v1', proposal_id=proposal['proposal_id'],
            iteration_id=iteration['iteration_id'], published=False, trace_audit=audit,
            trace_audit_id=digest(audit), graph_id=digest(graph))
        solution['solution_id'] = digest(solution)
        records = dict(solution=solution, proposal=proposal, iteration=iteration, force=force_record, bindings={})
        self.assertEqual(outcome(lambda: W.CollarWorkflow._check_certification_records(
            records, force, graph, interval, {}, source_audit)), ('accepted', None))
        old_source = self.originals['workflow']
        new_source = V.workflow_source(old_source)
        def refresh_block(source, transformed):
            first = ("                            with _SV.access(exchange) as _validation_exchange:\n" if transformed
                     else "                            graph = exchange['spatial_graph']\n")
            start = source.index(first)
            stop = source.index('                            '+('    ' if transformed else '')+
                                'from .integration_differential_geometry import current_geometry_from_interval', start)
            return compile(textwrap.dedent(source[start:stop]), '<exact-refresh-graph-block>', 'exec')
        old_block, new_block = refresh_block(old_source, False), refresh_block(new_source, True)
        for name, exchange in variants(initial):
            candidate = dict(graph, cells=exchange['spatial_graph']['cells'])
            if name == 'graph-id':
                candidate['bounds_id'] = 'x'*64
            expected = outcome(lambda: W.CollarWorkflow._check_certification_records(
                records, force, candidate, interval, {}, source_audit))
            for kind in ('legacy', 'ref', 'exchange'):
                with ExitStack() as stack:
                    g = candidate if kind == 'legacy' else stack.enter_context(compact(candidate, budget, exchange=kind == 'exchange'))
                    self.assertEqual(outcome(lambda: self.workflow._check_certification_records(
                        records, force, g, interval, {}, source_audit)), expected, (name, kind))
                    e = exchange if kind == 'legacy' else stack.enter_context(compact(exchange, budget, exchange=kind == 'exchange'))
                    def invoke(block, value):
                        ns = dict(_SV=V, _hash=digest, exchange=value, saved=saved,
                            differential_interval=SimpleNamespace(interval_id=initial['spatial_graph']['interval_id']),
                            interval={k: initial['spatial_graph'][k] for k in ('trajectory', 'start_support_id', 'end_support_id')},
                            RegionalOwnerRefused=W.RegionalOwnerRefused)
                        exec(block, ns)
                        return ns['partition_binding']
                    self.assertEqual(outcome(lambda: invoke(new_block, e)), outcome(lambda: invoke(old_block, exchange)), (name, kind))
            gc.collect()
            create_retained_scope(budget, process_epoch='wp6-validation-fixture').close()
            self.assertEqual(budget.reserved_bytes, 0)

    def test_restored_context_twelve_mutations(self):
        """Exact r9 context body with synthetic already-authenticated objects.

        Snapshot authentication/source pins/ledger equations are WP7 boundary
        fixtures here. All _context provenance and numerical tests execute.
        """
        import math
        source = (HISTORICAL/'private_heat_restored_binding_r9.py').read_text(encoding='utf-8')
        issuer = (HISTORICAL/'private_heat_native_issuer_r12.py').read_text(encoding='utf-8')
        target = body_functions(issuer, dict(Decimal=Decimal, Fraction=Fraction, _q=O._q,
            _target_text=lambda value: str(value)), ['_validate_target_plan'])
        class Owner(SimpleNamespace):
            pass
        class Spatial(SimpleNamespace):
            pass
        class Collar(SimpleNamespace):
            pass
        class Mesh(SimpleNamespace):
            pass
        class Geometry(SimpleNamespace):
            pass
        budget = WorkBudget(128 << 20)
        native_owner, native_state, initial, arrays, saved = fixture(budget)
        graph = dict(initial['spatial_graph'], parent_state_id='n'*64, source_flow_stage_id='q'*64,
            start_time_s=['0x0', '0x1'], end_time_s=['0x1', '0x1'], funding_id='f'*64,
            grid_id='g'*64, trajectory_id='t'*64)
        thermal = dict(funding_id='f'*64, grid_id='g'*64, support_id=graph['end_support_id'],
            trajectory_id='t'*64, time_s=graph['end_time_s'],
            cells=[{'logical_cell_id': row['cell_id']} for row in graph['cells']])
        mesh_id = digest(thermal)
        mesh = Mesh(_resource=budget, geometry_id=mesh_id, _json=thermal)
        current = dict(parent_state_id='p'*64, intervals=1, time_s=1, thermal_mesh_id=mesh_id, thermal_mesh=thermal)
        parent = Spatial(state_id='p'*64, _budget=budget, _snapshot=SimpleNamespace(_metadata=dict(intervals=0, time_s=0)))
        state = Spatial(state_id='a'*64, _budget=budget, _snapshot=SimpleNamespace(_metadata=current))
        parent_collar = Collar(result_id='n'*64, fields=object(), native_state=SimpleNamespace(result_id='v'*64))
        collar = Collar(result_id='c'*64, fields=object(), native_state=object())
        audit_body = dict(schema='atlas.regional-evolution3d-source-audit.v1', parent_state_id='v'*64,
                          start_time_s=0, duration_s=1)
        audit = SimpleNamespace(result_id='d'*64, _metadata=audit_body)
        plan = dict(schema='atlas.private.composed-heat-plan.r1', method_id='method', geometry_id=mesh_id,
            conductivity_w_m_k=[1., 1.], original_target={'kind': 'decimal-string', 'value': '1'},
            absolute_residual_target_decimal='1', absolute_residual_target=['0x1', '0x1'], boundary={})
        transported = dict(initial['transport'], geometry_id=digest(graph), state_id=parent.state_id)
        snapshot = SimpleNamespace(result_id=transported['result_id'],
                                   _metadata={k: v for k, v in transported.items() if k != 'result_id'})
        initial.update(schema='atlas.private.spatial-composed-advance.r1', spatial_graph=graph,
            spatial_graph_id=digest(graph), transport=transported, source_audit_id=audit.result_id,
            source_flow_stage_id='q'*64, joined_heat_plan=plan,
            joined_heat=dict(initial['joined_heat'], duration_s=1, geometry_id=mesh_id, plan_id=digest(plan)))
        initial['result_id'] = digest(dict(state_id=state.state_id,
            exchange={k: v for k, v in initial.items() if k not in ('state_id', 'result_id')}))
        owner = Owner(_budget=budget, owner_id=initial['owner_id'], _finite=None,
            _heat_label='PRIVATE uniform-k composed physical-face heat; original transported caloric stocks',
            validate_parent=lambda *args: None, _funding=SimpleNamespace(funding_id='f'*64),
            _definition=dict(grid_id='g'*64, conductivity_w_m_k=1.))
        geometry = Geometry(_budget=budget, _encoded=O._json(thermal), _face_ids=[], _incidence=[])
        resources = SimpleNamespace(codec_for_value=lambda *a, **k: nullcontext(),
            decoded=lambda value, **k: nullcontext(SimpleNamespace(value=value)), stream_hash=lambda value, cancel: digest(value))
        namespace = dict(_verify=lambda *args: None, _snapshot=lambda *args: None, PreparedSpatialOwner=Owner,
            SpatialExteriorState=Spatial, RegionalCollarState=Collar, ExteriorMesh=Mesh, MimeticGeometry=Geometry,
            R=resources, EXCHANGE_SCHEMA=initial['schema'], math=math, sha256=sha256,
            I=SimpleNamespace(_q=O._q, Fraction=Fraction, METHOD='method',
                _validate_target_plan=target._validate_target_plan, _target_text=lambda v: v,
                _target_provenance=lambda v: {'kind': 'decimal-string', 'value': v}))
        legacy = body_functions(source, namespace, ['_context'])
        indexed = body_functions(V.context_source(source), namespace, ['_context'])
        def invoke(fn, exchange):
            with ExitStack() as stack:
                result = fn(owner, parent, parent_collar, state, collar, mesh, snapshot, audit,
                    exchange, None, '1', budget, None, SimpleNamespace(stack=stack), geometry=geometry)
                return tuple(V.identity(value, digest) for value in result[:-2])+(result[-1],)
        for name, exchange in variants(initial):
            expected = outcome(lambda: invoke(legacy._context, exchange))
            if name == 'valid':
                self.assertEqual(expected[0], 'accepted', expected)
            for kind in ('legacy', 'ref', 'exchange'):
                with (nullcontext(exchange) if kind == 'legacy' else compact(exchange, budget, exchange=kind == 'exchange')) as value:
                    self.assertEqual(outcome(lambda: invoke(indexed._context, value)), expected, (name, kind))
            gc.collect()
            create_retained_scope(budget, process_epoch='wp6-validation-fixture').close()
            self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
