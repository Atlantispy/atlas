"""Fresh private routed package; synthetic native-schema partitions only.

The frozen runtime-integration-r1 package is copied to a short temporary
directory, then the native partition transforms, the six routing transforms
and the endpoint-scheduler transforms are applied there; the frozen routing
modules sit beside them as frozen_* for ordinary-path parity. Only RealWorker
starts one actual one-shot worker (seed-0 parent required). No historical
endpoint, store or solve is used. Historical test fixtures and helper texts
are read-only drivers.
"""
import ast
from collections import deque
import contextlib
from copy import deepcopy
from fractions import Fraction as Q
import gc
import gzip
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock
import weakref

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NATIVE = HERE.parents[1]/'runtime-integration-r1'/'runtime-src'/'atlas_tectonics'
HISTORICAL = HERE.parents[3]/'heat-repair-20261007'
HEAT_TESTS = HISTORICAL/'source'/'tectonics'/'tests'
SHORT = HERE.parents[4]/'_t'/'w1c'
sys.path[:0] = [str(HERE), str(ROOT), str(ROOT/'endpoint-checkpoints')]

import partition_native_patch as P
import partition_routing_patch as RP
import partition_routing_transform as RT
import patch_endpoint_scheduler as SC

temporary = None
ROUTED = tuple(RT.BASES)


def setUpModule():
    global temporary, D, RV, ALE, DP, SEL, AUTO, CVP, CVB, REUSE, TRACE, RES, T, PT, SIP, SO
    global FROZEN_RV, FROZEN_ALE, FROZEN_DP, FIRST, SECOND, TURNING
    if any(n == 'atlas_tectonics' or n.startswith('atlas_tectonics.') for n in sys.modules):
        raise RuntimeError('fresh process required; never patch a loaded production package')
    SHORT.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix='rr-', dir=SHORT)
    package = Path(temporary.name)/'atlas_tectonics'
    shutil.copytree(NATIVE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    def write(name, text):
        (package/(name+'.py')).write_text(text, encoding='utf8', newline='\n')
    def read(name):
        return (NATIVE/(name+'.py')).read_text(encoding='utf8')
    write('integration_differential_geometry', P.transform(read('integration_differential_geometry')))
    write('integration_differential_coupling', P.transform_coupling(read('integration_differential_coupling')))
    for name in ROUTED:
        write(name, RT.transform(name, read(name)))
        write('frozen_'+name, read(name))
    write('integration_component_volume_auto',
          SC.transform_auto(RT.transform('integration_component_volume_auto', read('integration_component_volume_auto'))))
    write('integration_parallel_rolling', SC.transform_rolling(read('integration_parallel_rolling')))
    sys.path[:0] = [temporary.name]
    sys.path.append(str(HEAT_TESTS))
    module = lambda name: importlib.import_module('atlas_tectonics.'+name)
    D, RV, ALE = module('integration_differential_geometry'), module('integration_routing_views'), module('integration_differential_ale')
    DP, SEL, AUTO = module('integration_parallel_dispatch'), module('integration_parallel_selection'), module('integration_component_volume_auto')
    CVP, TRACE, RES = module('integration_component_volume_parallel'), module('integration_differential_trace'), module('resources')
    CVB, REUSE = module('integration_component_volume_batch'), module('reuse')
    FROZEN_RV, FROZEN_ALE = module('frozen_integration_routing_views'), module('frozen_integration_differential_ale')
    FROZEN_DP = module('frozen_integration_parallel_dispatch')
    T = importlib.import_module('test_partition_tables')
    # That fixture module puts the frozen runtime first; worker children inherit
    # sys.path, so the routed copy must stay the first atlas_tectonics root.
    sys.path[:] = [p for p in sys.path if p != str(T.RUNTIME)]
    PT, SIP = importlib.import_module('partition_tables'), importlib.import_module('spatial_indexed_patch')
    SO = importlib.import_module('test_integration_differential_surface_ownership')
    identity = importlib.import_module('test_integration_differential_exchange_identity')
    FIRST, SECOND, TURNING = identity.FIRST, identity.SECOND, identity.TURNING
    if (not Path(D.__file__).resolve().is_relative_to(Path(temporary.name).resolve())
            or sys.path[0] != temporary.name):
        raise RuntimeError('routed package was not the one imported or inherited')


def tearDownModule():
    if temporary is not None:
        assert Path(temporary.name).resolve().parent == SHORT.resolve()
        temporary.cleanup()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def source_operands(body, budget):
    """Restore-protocol controls, not assertions of real physical provenance."""
    funding = SimpleNamespace(funding_id=body['funding_id'], _resource=budget,
                              descriptor=lambda: {'source': body['source']})
    collar = SimpleNamespace(plan_id=body['collar_plan_id'], _budget=budget)
    geometry = D._issue(D.DifferentialInterval, {'fixture': 'typed restore protocol only'}, budget)
    body.update(scope='physical-interval', current_geometry_id=None, interval_id=geometry.interval_id)
    return funding, collar, geometry


def derived_control():
    """The actual helper chain's control text, compact edits only (no execution)."""
    helper = (HISTORICAL/'private_heat_original_continuation_r1.py').read_text(encoding='utf8')
    namespace = {}
    keep = [n for n in ast.parse(helper).body if (isinstance(n, ast.Assign) and any(
        getattr(t, 'id', None) == '_EDITS' for t in n.targets)) or (isinstance(n, ast.FunctionDef) and n.name == '_replace_exact')]
    exec(compile(ast.Module(keep, []), 'helper-edits', 'exec'), namespace)
    control = (HEAT_TESTS/'i04_differential_continuation_control.py').read_text(encoding='utf8')
    return RT.continuation_control_source(namespace['_replace_exact'](control, namespace['_EDITS']))


def function_from(source, name, namespace):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module([node], []), name, 'exec'), namespace)
    return namespace[name]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.budget = T.WorkBudget(128 << 20)
        self.body, self.supports = T.tiny_partition(self.budget)
        self.folder = None

    def tearDown(self):
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())
        if self.folder is not None:
            self.folder.cleanup()

    def prepared(self):
        operands = source_operands(self.body, self.budget)
        view = T.opened(self.body, self.supports, self.budget)[0]
        part = D.DifferentialPartition.from_compact(view, *operands, budget=self.budget)
        legacy = D.DifferentialPartition.restore(dict(partition_id=D._record_hash(self.body), **self.body,
            supports=self.supports), *operands, budget=self.budget)
        return part, legacy, view

    def artifacts(self):
        self.folder = tempfile.TemporaryDirectory(prefix='cap-', dir=SHORT)
        return mock.patch.dict(os.environ, {'ATLAS_FOCUSED_ARTIFACT_DIR': self.folder.name})


class RoutingRows(Fixture):
    def test_compact_rows_match_legacy_views_and_retain_handles_not_native_supports(self):
        part, legacy, view = self.prepared()
        expected = {}
        with RV.RoutingArena(self.budget) as arena:
            rows = RV.SupportRoutingRows(legacy.supports, self.budget, arena)
            for support in legacy.supports:
                expected[support.support_id] = deepcopy(rows.project(support))
        refs, got = [], {}
        with RV.RoutingArena(self.budget) as arena:
            rows = RV.SupportRoutingRows(part.supports, self.budget, arena)
            for support in part.supports:
                refs.append(weakref.ref(support))
                got[support.support_id] = rows.project(support)
            del support
            gc.collect()
            self.assertTrue(all(ref() is None for ref in refs))
            self.assertEqual(set(rows._handles), set(expected))
            for key, handle in rows._handles.items():
                self.assertIs(type(handle), RP.CompactSupport)
                self.assertEqual(handle.support_id, key)
                self.assertIs(handle._ref._view, view)
            for key, row in got.items():
                old = expected[key]
                self.assertEqual(list(row), list(old))
                self.assertEqual({k: v for k, v in row.items() if k != 'constraints'},
                                 {k: v for k, v in old.items() if k != 'constraints'})
                self.assertEqual(list(row['constraints']), list(old['constraints']))
                for name, ref in row['constraints'].items():
                    self.assertIs(type(ref), PT.NodeRef)
                    self.assertEqual(view.legacy_record(ref).value, old['constraints'][name])
            first, second = (got[view.support_id(i)]['constraints']['carried:edge'] for i in (0, 1))
            self.assertEqual(first.index, second.index)   # one shared DAG definition
            self.assertEqual(rows._views.stats['projected_supports'], 3)

    def test_failure_diagnostics_are_prepaid_cached_two_operand_and_arena_scoped(self):
        part, legacy, view = self.prepared()
        keys = [view.support_id(i) for i in range(view.support_count)]
        native = {s.support_id: s for s in legacy.supports}
        with RV.RoutingArena(self.budget) as arena:
            rows = RV.SupportRoutingRows(part.supports, self.budget, arena)
            for support in part.supports:
                rows.project(support)
            del support
            with self.budget.reserve(self.budget.available_bytes, category='test-filled-ledger'):
                with mock.patch.object(RES, '_admit_budgets', side_effect=AssertionError('late diagnostic admission')):
                    first = rows[keys[0]]
                    self.assertIs(rows[keys[0]], first)
                    second = rows[keys[1]]
                    with self.assertRaisesRegex(RuntimeError, 'more than two'):
                        rows[keys[2]]
            for key, payload in ((keys[0], first), (keys[1], second)):
                self.assertIs(type(payload), RV._OwnedPayload)
                self.assertEqual(payload, native[key].record())
                self.assertEqual(D._encoded(dict(payload)), native[key]._json)
                self.assertEqual(list(payload), list(native[key].record()))
        with self.assertRaisesRegex(RuntimeError, 'no longer live'):
            rows[keys[0]]
        del first, second

    def failed(self, part, keys, measure):
        try:
            with RV.RoutingArena(self.budget) as arena:
                rows = RV.SupportRoutingRows(part.supports, self.budget, arena)
                for support in part.supports:
                    rows.project(support)
                del support
                with mock.patch.object(RES, '_admit_budgets', side_effect=AssertionError('late diagnostic admission')):
                    error = ALE._unmet_measure_error(measure, rows, self.budget)
                raise error
        except D.V.VolumeError as error:
            return error

    def test_unmet_measure_payloads_hold_arena_charges_until_error_and_payload_die(self):
        part, legacy, view = self.prepared()
        keys = [view.support_id(i) for i in range(view.support_count)]
        records = {s.support_id: s.record() for s in legacy.supports}
        baseline = self.budget.reserved_bytes
        face = dict(kind='component-angular-face', support_id=keys[0], other_support_id=keys[1],
                    met=False, logical_cell_id='component', leaves=1)
        wall = dict(kind='component-fixed-voxel-face', support_id=keys[2], logical_cell_id='component',
                    axis=0, end=1, moment_polynomials=[], max_widths=['0', '0'], max_width_m3='0',
                    max_leaves=1, leaves=1, met=False)
        arena = ('routing-diagnostic-metadata', 'routing-diagnostic-graphs', 'routing-diagnostic-decoder',
                 'routing-view-owner', 'routing-view-retained')
        def held():
            categories = self.budget.statistics()['categories']
            return {name: categories.get(name, 0) for name in arena}
        for measure in (face, wall):
            with self.subTest(kind=measure['kind']):
                error = self.failed(part, keys, measure)
                self.assertFalse(hasattr(error, 'diagnostic_capture_failure'))
                payload = error.physical_measure_failure
                self.assertIs(type(payload), RV._OwnedPayload)
                decoded = json.loads(json.dumps(payload, sort_keys=True))
                operands = [k for k in (measure['support_id'], measure.get('other_support_id')) if k is not None]
                self.assertEqual([canonical(r) for r in decoded['supports']], [canonical(records[k]) for k in operands])
                if measure is wall:
                    self.assertEqual(error.component_moment_failure['support'], records[keys[2]])
                    self.assertIs(error.component_moment_failure['support'], payload['supports'][0])
                charged = held()
                self.assertTrue(all(charged.values()))
                # The traceback's routing rows (and their compact handles) may
                # go; the arena's prepaid capacity stays with the payload.
                del error
                gc.collect()
                self.assertEqual(held(), charged)
                del payload, decoded
                gc.collect()
                self.assertEqual(self.budget.reserved_bytes, baseline)
                self.assertFalse(any(held().values()))

    def test_secondary_capture_failure_does_not_replace_the_primary_refusal(self):
        part, legacy, view = self.prepared()
        keys = [view.support_id(i) for i in range(view.support_count)]
        measure = dict(kind='component-angular-face', support_id=keys[0], met=False, logical_cell_id='c', leaves=1)
        with mock.patch.object(RP, '_prepaid_decode', side_effect=MemoryError('synthetic decoder failure')):
            error = self.failed(part, keys, measure)
        self.assertIs(type(error), D.V.VolumeError)
        self.assertIn('declared width/leaf bound', str(error))
        self.assertFalse(error.diagnostic_capture_failure['complete'])
        self.assertEqual(error.diagnostic_capture_failure['exception_type'], 'MemoryError')
        del error


class RoutingParity(Fixture):
    def compact_definitions(self, definitions):
        body, supports = T.tiny_partition(self.budget)
        supports[0]['constraints'] = dict(supports[0]['constraints'], **definitions)
        ids = [D._record_hash(s) for s in supports]
        body['support_ids'] = ids
        for contact, ident in zip(body['native_contacts'][0]['contacts'], ids, strict=True):
            contact['support_id'] = ident
        return T.opened(body, supports, self.budget)[0]

    def outcome(self, cases, measures):
        ownership, streams = SO.route(cases, measures)
        return canonical(dict(ownership=ownership, faces=streams.faces, exchanges=streams.exchanges, calls=measures.calls))

    def test_production_surface_routing_is_identical_with_compact_definitions(self):
        trench = SO.scene()
        left = SO.scene(key='left', chart='shared', path=('fan', 0), tilt=(0, 1, 0), authority=False)
        right = SO.scene(key='right', chart='shared', path=('fan', 1), tilt=(0, 1, 0), authority=False, exterior=True)
        turning = SO.scene(points=TURNING, kind='ridge', stock_id='birth')
        trench_name, pair_name = trench['part']['constraints'][0][0], left['part']['constraints'][0][0]
        names = [name for name, _ in turning['part']['constraints']]
        scenarios = (
            ([trench], lambda: SO.Measures(walls={('component', 1, 1): (SO.ZERO, FIRST)},
                                           faces={('component', trench_name): (SO.ZERO, FIRST)})),
            ([left, right], lambda: SO.Measures(faces={('left', pair_name): (SECOND, FIRST)})),
            ([turning], lambda: SO.Measures(faces={('component', n): (v, SO.ZERO) for n, v in zip(names, (FIRST, SECOND), strict=True)})))
        for cases, measures in scenarios:
            with self.subTest(cases=[c['part']['logical_cell_id'] for c in cases]):
                expected = self.outcome(cases, measures())
                with mock.patch.object(SO, 'ALE', FROZEN_ALE):
                    self.assertEqual(self.outcome(cases, measures()), expected)
                view = self.compact_definitions({n: d for c in cases for n, d in c['row']['constraints'].items()})
                compact = [dict(c, row=dict(c['row'], constraints={n: view.constraint(0, n) for n in c['row']['constraints']}))
                           for c in cases]
                self.assertTrue(all(type(v) is PT.NodeRef for c in compact for v in c['row']['constraints'].values()))
                self.assertEqual(self.outcome(compact, measures()), expected)
                self.assertTrue(any(json.loads(expected).values()))
                del view, compact

    def test_ordinary_native_path_has_identical_results_and_ledger(self):
        prepare = T.WorkBudget(128 << 20)
        body, supports = T.tiny_partition(prepare)
        operands = source_operands(body, prepare)
        legacy = D.DifferentialPartition.restore(dict(partition_id=D._record_hash(body), **body, supports=supports),
                                                 *operands, budget=prepare)
        def run(views, dispatch, natives):
            budget, log = T.WorkBudget(64 << 20), []
            keys = [s.support_id for s in natives]
            with views.RoutingArena(budget) as arena:
                rows = views.SupportRoutingRows(natives, budget, arena)
                log.append(budget.statistics())
                projected = [rows.project(s) for s in natives]
                log.append(budget.statistics())
                error = ALE._unmet_measure_error(dict(kind='component-angular-face', support_id=keys[0],
                    other_support_id=keys[1], met=False, logical_cell_id='c', leaves=1), rows, budget)
                log.append(budget.statistics())
                payload = canonical(error.physical_measure_failure)
            log.append(budget.statistics())
            requests = [dispatch._request(s, 'k', 'n', {'other_support': natives[0]}, Q(0), 8) for s in natives]
            requests += [dispatch._wall_request(s, 'k', 0, {'end': 1}, Q(0), 8) for s in natives]
            requests += [dispatch.transport(s) for s in natives]
            session = dispatch.BatchParallelSession(budget=budget, max_width_m3=Q(0), max_leaves=8, wall=True)
            bound = session._bind_jobs([(s, 'k%d' % i, 0, {'end': 1}) for i, s in enumerate(natives)])
            log.append(budget.statistics())
            del session
            return projected, payload, requests, (bound[0], bound[1], dict(bound[2])), log
        self.assertEqual(run(RV, DP, list(legacy.supports)), run(FROZEN_RV, FROZEN_DP, list(legacy.supports)))
        del legacy, operands
        gc.collect()
        self.assertEqual(prepare.reserved_bytes, 0)


class DispatchTransport(Fixture):
    def handles(self):
        part, legacy, view = self.prepared()
        return part, legacy, view, [RP.retain_support(s) for s in part.supports], list(legacy.supports)

    def test_transport_requests_and_input_bytes_equal_the_native_route(self):
        part, legacy, view, handles, natives = self.handles()
        for handle, native in zip(handles, natives, strict=True):
            raw = native._json
            limit = RV._decoded_json_capacity(raw)+65536+4*len(raw)
            self.assertEqual(handle.encoded_size, len(raw))
            for maximum in (len(raw), len(raw)-1):
                for storage in (4*limit, 4*limit+3, 4*limit-1):
                    with mock.patch.multiple(DP, MAX_INPUT=maximum, PARENT_STORAGE=storage), \
                            mock.patch.multiple(FROZEN_DP, MAX_INPUT=maximum, PARENT_STORAGE=storage):
                        expected = FROZEN_DP.transport(native)
                        self.assertEqual(DP.transport(handle), expected)
                        self.assertEqual(DP.transport(native), expected)
                        self.assertEqual(expected is None, maximum < len(raw) or storage < 4*limit)
            pair, old = {'other_support': handles[1]}, {'other_support': natives[1]}
            self.assertEqual(DP._request(handle, 'k', 'n', pair, Q(0), 8), FROZEN_DP._request(native, 'k', 'n', old, Q(0), 8))
            self.assertEqual(DP._wall_request(handle, 'k', 1, {'end': 0}, Q(0), 8),
                             FROZEN_DP._wall_request(native, 'k', 1, {'end': 0}, Q(0), 8))
            self.assertEqual(CVP.request_for(handle, 'k', 'end', 1., Q(0), 8), CVP.request_for(native, 'k', 'end', 1., Q(0), 8))
        for kind in ('wall', 'interface', 'endpoint'):
            with self.subTest(kind=kind):
                def bind(items, dispatch, budget):
                    if kind == 'endpoint':
                        session = CVP.ComponentParallelSession(budget=budget, max_width_m3=Q(0), max_leaves=8)
                        jobs = [(s, 'k%d' % i, 'end', {}) for i, s in enumerate(items)]
                    else:
                        session = dispatch.BatchParallelSession(budget=budget, max_width_m3=Q(0), max_leaves=8,
                                                                wall=kind == 'wall')
                        jobs = [(s, 'k%d' % i, 0, {'end': 1}) if kind == 'wall' else
                                (s, 'k%d' % i, 'n', {'other_support': items[(i+1) % len(items)]}) for i, s in enumerate(items)]
                    return session, session._bind_jobs(jobs)
                before = self.budget.reserved_bytes
                session, (requests, tokens, inputs) = bind(handles, DP, self.budget)
                old_session, (old_requests, old_tokens, old_inputs) = bind(natives, FROZEN_DP if kind != 'endpoint' else DP,
                                                                           T.WorkBudget(64 << 20))
                self.assertEqual((requests, tokens), (old_requests, old_tokens))
                self.assertIs(type(inputs), RP.InputMap)
                self.assertEqual(dict(inputs), dict(old_inputs))
                self.assertTrue(all(hashlib.sha256(raw).hexdigest() == key for key, raw in inputs.items()))
                self.assertGreaterEqual(self.budget.reserved_bytes-before, sum(4096+len(raw) for raw in inputs.values()))
                scratch = T.WorkBudget(16 << 20)
                for key, raw in inputs.items():
                    self.assertEqual(DP._support(raw, key, scratch)._json, raw)   # the worker's own decode
                if kind == 'wall':
                    self.assertEqual(DP._inventory(inputs), FROZEN_DP._inventory(old_inputs))
                del inputs, session, old_session
                gc.collect()
                self.assertEqual(self.budget.reserved_bytes, before)

    def test_oversize_batch_is_refused_before_any_copy_and_admission_refusal_does_not_revoke(self):
        part, legacy, view, handles, natives = self.handles()
        session = DP.BatchParallelSession(budget=self.budget, max_width_m3=Q(0), max_leaves=8, wall=True)
        jobs = [(handles[0], 'a', 0, {'end': 1}), (handles[1], 'b', 0, {'end': 1})]
        streamed, original = [], PT.CompactPartition._iter
        def counting(view, node):
            streamed.append(node)
            yield from original(view, node)
        before = self.budget.reserved_bytes
        with mock.patch.object(DP, 'MAX_BATCH_INPUT', handles[0].encoded_size+handles[1].encoded_size-1), \
                mock.patch.object(PT.CompactPartition, '_iter', counting):
            with self.assertRaisesRegex(ValueError, 'batch exceeds the optional transport envelope'):
                session._bind_jobs(jobs)
        self.assertIn(handles[0]._ref.index, streamed)
        self.assertNotIn(handles[1]._ref.index, streamed)
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)
        session.owner = SimpleNamespace(condition=threading.Condition(), state='ACTIVE', revoke=mock.Mock())
        with self.budget.reserve(self.budget.available_bytes-1024, category='test-filled-ledger'):
            self.assertIsNone(session.launch(jobs[:1], timeout=10))
        session.owner.revoke.assert_not_called()
        self.assertIsNotNone(session.last_error)
        self.assertEqual(session.batches, [])
        session.owner = None
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)

    def test_screen_materialises_the_same_native_operands(self):
        part, legacy, view, handles, natives = self.handles()
        session = DP.InterfaceParallelSession(budget=self.budget, context=None, max_width_m3=Q(0), max_leaves=8)
        key = self.supports[0]['components'][0]['logical_cell_id']
        results = []
        for name in ('carried:edge', 'normal', 'plane'):
            request = DP._request(natives[0], key, name, {}, Q(0), 8)
            with self.subTest(name=name):
                results.append(session._screen(handles[0], None, request, scratch_bytes=8 << 20, scratch_units=8192))
                self.assertEqual(results[-1], session._screen(natives[0], None, request, scratch_bytes=8 << 20,
                                                              scratch_units=8192))
        self.assertIn('decided', results)   # an exact screen actually ran on the materialised operand


class Schedulers(Fixture):
    class Schedule:
        def __init__(self):
            self.stopped, self.offers, self.stops, self.consumed = None, [], [], 0

        def hungry(self):
            return True

        def offer(self, job, seconds, label):
            self.offers.append(job)

        def _stop(self, reason, detail):
            self.stops.append((reason, detail))
            self.stopped = reason

        def checkpoint_consumed(self):
            self.consumed += 1

        def unlisted(self):
            self.stops.append(('unlisted', None))

    def controller(self):
        result = object.__new__(AUTO.AutomaticEndpoints)
        result.__dict__.update(schedule=self.Schedule(), closed=False, order=deque(), left=0, jobs=None, total=0,
                               checkpoint_hits=0, label=None, started=None, _mark=None)
        return result

    def test_endpoint_lookahead_offers_handles_serial_off_and_checkpoint_hits(self):
        part, legacy, view = self.prepared()
        for compact, native in zip(part.supports, legacy.supports, strict=True):
            row = native.record()
            controller = self.controller()
            AUTO.bind_support(controller, compact, row)
            offered = [job[0] for job in controller.schedule.offers]
            self.assertTrue(offered and all(type(s) is RP.CompactSupport and s.support_id == native.support_id
                                            for s in offered))
            plain = self.controller()
            AUTO.bind_support(plain, native, row)
            self.assertTrue(all(job[0] is native for job in plain.schedule.offers))
            self.assertEqual([job[1:] for job in plain.schedule.offers], [job[1:] for job in controller.schedule.offers])
            # A completed-query checkpoint hit consumes the offered compact query in order.
            key, endpoint, _ = controller.order[0]
            queries = SimpleNamespace(measure=lambda *args, **kwargs: 'restored')
            result = AUTO.measure_endpoint(queries, controller, key, endpoint=endpoint, positive_witness=True,
                                           _checkpoint=SimpleNamespace(last_completed=('query', True)))
            self.assertEqual((result, controller.checkpoint_hits, controller.schedule.consumed), ('restored', 1, 1))
            self.assertNotEqual(controller.order[0][:2] if controller.order else None, (key, endpoint))
            # Serial/off: no controller, nothing offered or retained.
            AUTO.bind_support(None, compact, row)
            self.assertIsNone(AUTO.open_automatic_endpoints(SimpleNamespace(policy=SimpleNamespace(mode='off')), Q(0)))
        foreign = T.WorkBudget(64 << 20)
        other = T.opened(*T.tiny_partition(foreign), foreign)[0]
        support = next(iter(part.supports))
        object.__setattr__(support, '_compact_ref', other.support(0))
        controller = self.controller()
        AUTO.bind_support(controller, support, support.record())
        self.assertEqual(controller.schedule.offers, [])
        self.assertEqual(controller.schedule.stops[0][0], 'endpoint lookahead error')
        del support, other, controller
        gc.collect()
        self.assertEqual(foreign.reserved_bytes, 0)

    def test_rolling_facts_retain_handles_once_per_node_and_keep_the_ordinary_path(self):
        part, legacy, view = self.prepared()
        rolling = object.__new__(SEL._Rolling)
        rolling.identities, rolling.cached = {}, 2
        first = P.materialise_support(view, 0)
        found = rolling._facts(first)
        self.assertIs(type(found[0]), RP.CompactSupport)
        self.assertEqual(found[1], view.support_id(0))
        self.assertIs(rolling._facts(P.materialise_support(view, 0)), found)
        self.assertEqual(rolling._weight(first), DP.transport(first))
        rolling._facts(P.materialise_support(view, 1))
        self.assertEqual(len(rolling.identities), 2)
        rolling._facts(P.materialise_support(view, 2))
        self.assertEqual(len(rolling.identities), 1)
        natives = list(legacy.supports)
        plain = rolling._facts(natives[0])
        self.assertIs(plain[0], natives[0])
        self.assertIs(rolling.identities[id(natives[0])], plain)
        handle = found[0]
        self.assertIs(rolling._facts(handle)[0], handle)
        del found, plain, handle, first, rolling
        session = DP.BatchParallelSession(budget=self.budget, max_width_m3=Q(0), max_leaves=8, wall=True)
        a = session._support_facts(P.materialise_support(view, 0))
        self.assertEqual(session._support_facts(P.materialise_support(view, 0)), a)
        self.assertEqual(a, FROZEN_DP.BatchParallelSession(budget=T.WorkBudget(1 << 20), max_width_m3=Q(0),
            max_leaves=8, wall=True)._support_facts(natives[0]))
        self.assertEqual(len(session._facts), 1)


class TraceAndCapture(Fixture):
    def test_trace_selected_fields_handles_and_contact_failure_payload(self):
        part, legacy, view = self.prepared()
        record = legacy.record()
        selected = P.partition_fields(part, RT.TRACE_FIELDS)
        self.assertEqual(selected.value, {k: record[k] for k in RT.TRACE_FIELDS if k in record})
        geometry = dict(interval_id=record['interval_id'], parent_network_id=record['network_id'],
                        start_time_s=record['start_time_s'], end_time_s=record['end_time_s'])
        for endpoint in ('start', 'end'):
            self.assertEqual(TRACE._partition_endpoint(selected.value, geometry, static=False, endpoint=endpoint,
                network_id=record['network_id']), TRACE._partition_endpoint(record, geometry, static=False,
                endpoint=endpoint, network_id=record['network_id']))
        supports = {s.support_id: TRACE._retain_support(s) for s in part.supports}
        self.assertTrue(all(type(h) is RP.CompactSupport for h in supports.values()))
        self.assertTrue(all(TRACE._retain_support(s) is s for s in legacy.supports))
        # The routed contact statements, executed with the module's own names.
        construct = next(n for n in ast.walk(ast.parse(Path(TRACE.__file__).read_text(encoding='utf8')))
                         if isinstance(n, ast.FunctionDef) and n.name == '_construct')
        branch = next(n for n in ast.walk(construct) if isinstance(n, ast.If) and ast.unparse(n.test) == 'type(support) is _CompactSupport')
        snippet = ast.parse('def contact(support):\n    pass\n    return support, source\n')
        snippet.body[0].body[0] = branch
        namespace = dict(vars(TRACE))
        exec(compile(ast.fix_missing_locations(snippet), 'contact', 'exec'), namespace)
        natives = {s.support_id: s for s in legacy.supports}
        key = view.support_id(1)
        unchanged = self.budget.reserved_bytes
        self.assertEqual(namespace['contact'](natives[key]), (natives[key], natives[key].record()))
        self.assertEqual(self.budget.reserved_bytes, unchanged)
        native, source = namespace['contact'](supports[key])
        self.assertIs(type(native), D.DifferentialSupport)
        self.assertEqual((native._json, source), (natives[key]._json, natives[key].record()))
        error = D.V.VolumeError('synthetic contact refusal')
        error.component_moment_failure = dict(support=source, measure=None, exception_type='VolumeError')
        del native   # its own issue lease is not part of the failure payload
        gc.collect()
        charged = self.budget.reserved_bytes
        del source
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, charged)
        # The continuation's own wrapper writes the same diagnostic file.
        current_trace = function_from(derived_control(), '_current_trace', dict(
            T=SimpleNamespace(PreparedDifferentialTrace=mock.Mock(side_effect=error)), os=os, Path=Path, json=json))
        with self.artifacts():
            with self.assertRaises(D.V.VolumeError):
                current_trace(4)
            written = (Path(self.folder.name)/'continuation-component-moment-failure-04.json').read_text(encoding='utf8')
        legacy_failure = dict(support=natives[key].record(), measure=None, exception_type='VolumeError')
        self.assertEqual(written, json.dumps(legacy_failure, sort_keys=True, indent=2, allow_nan=False)+'\n')
        current_trace = None
        del error
        gc.collect()
        self.assertLess(self.budget.reserved_bytes, charged)

    def capture_function(self):
        joined = (HEAT_TESTS/'i04_differential_joined_control.py').read_text(encoding='utf8')
        module = ModuleType('i04_differential_joined_control')
        module.json = json
        function_from(joined, '_retain_failure', module.__dict__)
        return module, function_from(derived_control(), '_retain_trace_inputs', dict(os=os, Path=Path))

    def test_streamed_capture_equals_legacy_and_never_expands_the_partition_first(self):
        part, legacy, view = self.prepared()
        module, retain = self.capture_function()
        volume_map = SimpleNamespace(_record=b'{"cells":[1,2]}', record=lambda: {'cells': [1, 2], 'volume_map_id': 'm'*64})
        arguments = dict(plate_ids=['plate:A', 'plate:B'], endpoint='current', open_side='z0',
                         max_moment_width=['0x1', '0xde0b6b3a7640000'], max_volume_width=['0x0', '0x1'], max_leaves=64)
        output = io.StringIO()
        with self.artifacts(), mock.patch.dict(sys.modules, {'i04_differential_joined_control': module}), \
                contextlib.redirect_stdout(output):
            retain(1, legacy, volume_map, arguments, self.budget)
            with mock.patch.object(P, 'materialise_support', side_effect=AssertionError('whole support expansion')), \
                    mock.patch.object(PT.CompactPartition, 'legacy_record', side_effect=AssertionError('whole export')):
                retain(2, part, volume_map, arguments, self.budget)
            files = [Path(self.folder.name)/('continuation-trace-inputs-%02d.json.gz' % n) for n in (1, 2)]
            old, new = (gzip.decompress(f.read_bytes()) for f in files)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(new, old)
        self.assertEqual(json.loads(new)['supports'], [s.record() for s in legacy.supports])

    def test_capture_failures_are_diagnostic_and_interruptions_propagate(self):
        part, legacy, view = self.prepared()
        volume_map = SimpleNamespace(_record=b'{}', record=lambda: {'volume_map_id': 'm'*64})
        original = PT.CompactPartition.iter_legacy_json
        def failing(kind):
            def iterate(instance, ref=None):
                if ref is not None and ref.index == instance.support(1).index:
                    yield b'['
                    raise kind('synthetic mid-stream failure')
                yield from original(instance, ref)
            return iterate
        def capture(number, partition=part, budget=self.budget):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                RP.retain_compact_trace(number, partition, volume_map, {}, budget, name='x', scope='s')
            return output.getvalue()
        with self.artifacts():
            folder = Path(self.folder.name)
            (folder/'x-03.json.gz').write_bytes(b'kept')
            self.assertIn('FileExistsError', capture(3))
            self.assertEqual((folder/'x-03.json.gz').read_bytes(), b'kept')
            with mock.patch.object(PT.CompactPartition, 'iter_legacy_json', failing(RuntimeError)):
                self.assertIn('synthetic mid-stream failure', capture(4))
            with mock.patch.object(PT.CompactPartition, 'iter_legacy_json', failing(KeyboardInterrupt)):
                with self.assertRaises(KeyboardInterrupt):
                    capture(5)
            with self.budget.reserve(self.budget.available_bytes-1024, category='test-filled-ledger'):
                self.assertIn('MemoryLimitError', capture(6))
            self.assertIn('VolumeError', capture(7, partition=SimpleNamespace(_compact=view)))
            self.assertIn('same-budget', capture(8, partition=legacy))
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ['x-03.json.gz'])
            gc.collect()

    def test_continuation_reads_selected_fields_in_the_original_order(self):
        part, legacy, view = self.prepared()
        calls, record = [], legacy.record()
        current = SimpleNamespace(record=lambda: calls.append('current') or {'geo': 1})
        prior = SimpleNamespace(record=lambda: calls.append('prior') or {'end_time_s': record['end_time_s']})
        material = SimpleNamespace(_snapshot=object(), record=lambda: calls.append('material') or {'support_id': 's'})
        proxy = SimpleNamespace(record=lambda: calls.append('partition') or record)
        selected = P.partition_fields
        def counted(partition, fields):
            calls.append('partition')
            return selected(partition, fields)
        self.assertFalse(RP.compact_continuation_state(proxy, material))
        self.assertTrue(RP.compact_continuation_state(part, material))
        with mock.patch.object(P, 'partition_fields', counted), \
                mock.patch.object(PT.CompactPartition, 'legacy_record', side_effect=AssertionError('whole export')):
            geo, part_fields, accepted, state, owner = RP.continuation_records(current, part, prior, material)
        self.assertEqual(calls, ['current', 'partition', 'prior', 'material'])
        self.assertEqual(part_fields, {k: record[k] for k in RP.CONTINUATION_FIELDS})
        self.assertEqual((geo, accepted, state), ({'geo': 1}, {'end_time_s': record['end_time_s']}, {'support_id': 's'}))
        calls.clear()
        self.assertEqual(RP.continuation_records(current, proxy, prior, material)[:4],
                         ({'geo': 1}, record, {'end_time_s': record['end_time_s']}, {'support_id': 's'}))
        self.assertEqual(calls, ['current', 'partition', 'prior', 'material'])
        indexed = SimpleNamespace(_snapshot=object.__new__(SIP.IndexedSpatialSnapshot))
        self.assertTrue(RP.compact_continuation_state(proxy, indexed))
        with mock.patch.object(SIP, 'logical_record', return_value={'support_id': 'indexed'}) as logical:
            self.assertEqual(RP.continuation_records(current, proxy, prior, indexed)[3], {'support_id': 'indexed'})
        logical.assert_called_once_with(indexed)
        del owner


SEEDED = os.environ.get('PYTHONHASHSEED') == '0' and sys.flags.hash_randomization == 0


@unittest.skipUnless(SEEDED, 'actual seed-0 parent required by the worker binding')
class RealWorker(unittest.TestCase):
    """One actual one-shot endpoint worker fed from a compact handle.

    Parent and child execution identities import every package module, so the
    frozen runtime's cold-heat helpers (I/ram and the historical root) are put
    LAST on the path for this test only; the routed package stays first.
    Importing that chain runs private_heat_gmp_resources_r1's module-level
    sys.path.insert(0, <historical source/tectonics/src>); children inherit
    sys.path, so this test removes that entry before any launch (reported to
    the composer, which must do the same for real workers).
    """
    def setUp(self):
        self.saved = list(sys.path)
        sys.path.extend([str(HERE.parents[1]/'runtime-integration-r1'/'ram'), str(HISTORICAL)])

    def tearDown(self):
        sys.path[:] = self.saved

    def assert_routed_path(self):
        historical = (HISTORICAL/'source'/'tectonics'/'src').resolve()
        sys.path[:] = [p for p in sys.path if not p or Path(p).resolve() != historical]
        self.assertEqual(sys.path[0], temporary.name)
        self.assertFalse([p for p in sys.path if p and (Path(p).resolve() == historical or 'native-composed' in p)])
        self.assertTrue(all(Path(m.__file__).resolve().is_relative_to(Path(temporary.name).resolve())
                            for n, m in list(sys.modules.items()) if n.startswith('atlas_tectonics') and
                            getattr(m, '__file__', None)))

    def test_endpoint_batch_ships_exact_compact_inputs_and_adopts_the_serial_bytes(self):
        resource = T.WorkBudget(2 << 30, max_predicate_work_units=1 << 38)
        body, supports = T.tiny_partition(resource)
        box = D.V.CartesianCell((2, 2, 2), (3, 3, 3), budget=resource)
        layer = D.V.RadialLayer(10, 0, 9, budget=resource)
        support = deepcopy(supports[0])
        support.update(interval_id=None, current_geometry_id=T.ident('geometry'), voxel=box.record(),
            radial_layer=layer.record(), constraints={}, material_angular_velocity_rad_s=[T.q(0)]*3,
            start_time_s=T.q(0), end_time_s=T.q(0), duration_s=T.q(0))
        support['components'][0]['constraints'] = []
        body['support_ids'] = [D._record_hash(support)]
        view = T.opened(body, [support], resource)[0]
        key = support['components'][0]['logical_cell_id']
        del box, layer, supports
        def serial(native, claim=None):
            with CVB.ComponentVolumeQueries(native, budget=resource) as volumes:
                return [volumes.measure(key, endpoint=endpoint, max_width_m3=0, max_leaves=8, positive_witness=True,
                                        _funded=claim)._json for endpoint in ('start', 'end')]
        native = P.materialise_support(view, 0)
        handle = RP.retain_support(native)
        expected = serial(native)
        baseline = resource.reserved_bytes
        with REUSE.ExecutionContext('reference') as context:
            self.assert_routed_path()
            session = CVP.ComponentParallelSession(budget=resource, max_width_m3=Q(0), max_leaves=8, timeout_seconds=120)
            try:
                self.assertTrue(session.open(lambda: context), session.last_error)
                batch = session.launch([(handle, key, endpoint, {}) for endpoint in ('start', 'end')], timeout=60)
                self.assertIsNotNone(batch, session.last_error)
                self.assertIs(type(batch['inputs']), RP.InputMap)
                self.assertEqual(dict(batch['inputs']), {native.support_id: native._json})
                self.assertEqual(serial(native, session.claim), expected)
                self.assertEqual(session.stats['declined'], 0, session.last_error)
                self.assertEqual(session.stats['adopted']+session.stats['decided'], 2, session.stats)
                self.assertEqual(session.batches, [])
                self.assertFalse(Path(batch['path']).exists())
            finally:
                session.close()
                self.assertIsNone(resource._revoker)
                self.assertFalse(session.busy())
        del batch, session, context
        gc.collect()
        self.assertEqual(resource.reserved_bytes, baseline)
        del handle, native, view
        gc.collect()
        self.assertEqual(resource.reserved_bytes, 0, resource.statistics())


if __name__ == '__main__':
    unittest.main(verbosity=2)
