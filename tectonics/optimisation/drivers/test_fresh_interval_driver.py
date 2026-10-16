"""Route (1) fresh driver: r9's literals and the run A / run B wiring.

No physics runs here. (1) Every admission, cache and work-ceiling literal in
fresh_interval_driver equals the corresponding argument in r9's run()
(probe_heat_original_connected_r9.py, read as source, never imported). (2) With
recording stand-ins for the composed modules, run A creates the sequence-0 root
with the admission's live objects and advances nothing, and run B opens that
root with the same objects, advances once through the joined helper with r9's
arguments and calls the runner's finish inside the open workflow.
"""
import ast
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fresh_interval_driver as F

R9 = HERE.parents[2]/'heat-repair-20261007'/'probe_heat_original_connected_r9.py'
# Item 11: the composition the next fresh IV1 runs, read as source, never imported.
COMPOSED = HERE/'composed-r2'
COMMIT_STAGES = ('heat-result-packaging', 'heat-checkpoint-save', 'heat-checkpoint-r3-checks',
                 'heat-exterior-finish', 'endpoint-store-publish')
# Item 11 M: markers at calls inside the finish and the projection, and three heat counters.
R9_TICKS = ('component_volume_queries', 'heat_faces', 'heat_faces_collected')
HEAT_TICKS = ('metric_identity_calls', 'closed_guard_certificates', 'closed_guard_admissible_tests')


def closed_guard_scan():
    """Stand-in for the closed guard's scan: the two nested functions its counters observe, by name."""
    def certificate(value):
        return value
    def admissible(value):
        return value
    return certificate, admissible


def evaluate(node):
    """Literal arguments of r9's calls: constants, tuples, Q(n), ** and <<."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(evaluate(item) for item in node.elts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Q':
        return Fraction(*(evaluate(arg) for arg in node.args))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        return evaluate(node.left)**evaluate(node.right)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.LShift):
        return evaluate(node.left) << evaluate(node.right)
    raise ValueError('not a literal: '+ast.dump(node))


def r9_calls(name):
    tree = ast.parse(R9.read_text(encoding='utf-8'))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', None)
            if called == name:
                found.append(node)
    return found


def literal_keywords(call, names):
    return {k.arg: evaluate(k.value) for k in call.keywords if k.arg in names}


class R9LiteralTests(unittest.TestCase):
    def one(self, name):
        calls = r9_calls(name)
        self.assertEqual(len(calls), 1, name)
        return calls[0]

    def test_admission_literals_equal_r9(self):
        self.assertEqual(literal_keywords(self.one('radial_differential_fixture'), F.FIXTURE), F.FIXTURE)
        self.assertEqual(literal_keywords(self.one('initial_partition'), F.INITIAL_PARTITION), F.INITIAL_PARTITION)
        self.assertEqual(literal_keywords(self.one('initial_metrics'), F.INITIAL_METRICS), F.INITIAL_METRICS)
        owner = literal_keywords(self.one('initial_spatial_owner'), {'created_tracers'})
        self.assertEqual(owner['created_tracers'], F.CREATED_TRACERS)

    def test_cache_pressure_and_parallel_literals_equal_r9(self):
        caches = [c for c in r9_calls('StoreLimits')
                  if literal_keywords(c, {'max_store_bytes'}).get('max_store_bytes') == 128 << 20]
        self.assertEqual(len(caches), 1)
        self.assertEqual(literal_keywords(caches[0], F.MEASUREMENT_CACHE), F.MEASUREMENT_CACHE)
        self.assertEqual(literal_keywords(self.one('Compression'), {'codec'}), {'codec': F.MEASUREMENT_CODEC})
        self.assertEqual(literal_keywords(self.one('check_initial_pressure_force'), F.PRESSURE_FORCE),
                         F.PRESSURE_FORCE)
        self.assertEqual(literal_keywords(self.one('InterfaceParallelPolicy'), F.PARALLEL), F.PARALLEL)


class LoadedSourceFenceTests(unittest.TestCase):
    """The runner and the fresh reader fence the loaded driver against its pinned bytes (smoke, 16 Oct)."""

    def test_the_real_fence_accepts_the_driver_as_loaded(self):
        import historical_admission as H
        H._loaded_source_fence(F, sha256(Path(F.__file__).read_bytes()).hexdigest(), lambda: None)

    def test_a_decorated_module_function_is_refused_which_is_why_admission_is_plain(self):
        import historical_admission as H
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'decorated_driver.py'
            path.write_bytes(b'from contextlib import contextmanager\n\n\n@contextmanager\ndef decorated():\n'
                             b'    yield\n')
            spec = importlib.util.spec_from_file_location('decorated_driver', path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with self.assertRaisesRegex(ValueError, 'loaded guarded function differs from pinned source: decorated'):
                H._loaded_source_fence(module, sha256(path.read_bytes()).hexdigest(), lambda: None)


class Recorder:
    def __init__(self):
        self.calls = []

    def add(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


def stand_ins(log, *, opened_kind='root', opened_intervals=0, after_intervals=1, identity='w'*64, r3_checks=True,
              guard_scan=closed_guard_scan):
    @contextmanager
    def cm(name, value=None, **kwargs):
        log.add(name, **kwargs)
        yield value
    class Context:
        def __init__(self, kind):
            self.provenance, self.kind = {'context': kind}, kind
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def verify_boundary(self):
            log.add('verify_boundary', self.kind)
    case = {'collar': SimpleNamespace(plan_id='collar', _native=SimpleNamespace(plan_id='native'),
                                      _map=SimpleNamespace(volume_map_id='map')),
            'owner': SimpleNamespace(owner_id='owner'), 'funding': SimpleNamespace(funding_id='funding'),
            'source': [SimpleNamespace(network='network')], 'budget': 'budget'}
    spatial_owner = SimpleNamespace(owner_id='spatial-owner', initial_state='initial-state')
    root = {'key': 'k'*64, 'kind': 'root', 'sequence': 0}

    class Workflow:
        def __init__(self, store, intervals, kind):
            self._store, self.workflow_id, self._intervals, self._open = store, 'w'*64, intervals, False
            self._root, self._head = json.dumps(root), {'kind': kind, 'key': 'h'*64, 'sequence': intervals}
            self._funding = 'funding'
        def __enter__(self):
            self._open = True
            return self
        def __exit__(self, *_):
            self._open = False
            return False
        def inspect(self):
            return {'intervals': self._intervals, 'head': self._head['key'], 'funding_id': self._funding}

        @classmethod
        def create(cls, *args, **kwargs):
            log.add('create', *args, **kwargs)
            return cls(args[0], 0, 'root')

        @classmethod
        def _exterior_inputs(cls, owner, collar, funding, budget):
            log.add('exterior_inputs', owner, collar, funding, budget)
            return {'owner_id': owner.owner_id}

        @classmethod
        def _identity(cls, collar, funding, exterior):
            log.add('identity', collar, funding, exterior)
            return identity

        @classmethod
        def open(cls, *args, **kwargs):
            log.add('open', *args, **kwargs)
            return cls(args[0], opened_intervals, opened_kind)

        def _publish(self, *args, **kwargs):
            raise AssertionError('observed only; the stand-in advance never publishes')

    if r3_checks:
        def _r3_after_heat_checkpoint(self, heat, mark):
            raise AssertionError('observed only')
        setattr(Workflow, '_r3_after_heat_checkpoint', _r3_after_heat_checkpoint)

    def advance(test, case_, workflow, **kwargs):
        log.add('advance', case_, workflow, **kwargs)
        workflow._intervals, workflow._head = after_intervals, {'kind': 'successor', 'key': 's'*64}
        return {'report': True}, 'restored'

    def pressure(test, case_, current, partition, state, **kwargs):
        log.add('pressure', current, partition, state, **{k: v for k, v in kwargs.items() if k != 'prepared_control'})
        return kwargs['prepared_control'](driver='driver', pressure='pressure', datum='datum')

    m = SimpleNamespace(
        ExecutionContext=Context, ArrayStore=lambda *a, **k: cm('cache', 'cache', path=str(a[0])),
        StoreLimits=lambda **k: ('limits', k), Compression=lambda **k: ('compression', k),
        radial_differential_fixture=lambda **k: cm('fixture', case, **k),
        spatial=SimpleNamespace(
            initial_partition=lambda c, **k: (log.add('initial_partition', **k), ('current', 'partition'))[1],
            initial_metrics=lambda c, p, **k: (log.add('initial_metrics', **k), ('bounds', 'mesh'))[1],
            initial_spatial_owner=lambda *a, **k: cm('initial_spatial_owner', spatial_owner, **k)),
        D=SimpleNamespace(POLICY='policy', TARGET='target', ADVANCE_OPTIONS={'ale_max_leaves': 2**19},
                          _Cancel=lambda check: ('cancel', check)),
        J=SimpleNamespace(METHOD='heat-method'), Workflow=Workflow,
        joined=SimpleNamespace(_advance_current_interval=advance,
                               _check_reopened=lambda t, w, r: log.add('check_reopened', r)),
        check_initial_pressure_force=pressure, ACTUATED_CONTROL='actuated',
        geometry_observer=SimpleNamespace(observe=lambda guard, stages, ticks, **k: cm('observe', stages=stages,
                                                                                       ticks=ticks)),
        threadpool_limits=lambda n: cm('threadpool_limits', n=n), PF='PF',
        prepared_interval_driver=SimpleNamespace(selector_gate=lambda pf: {'seed': '0'}),
        G=SimpleNamespace(enclose_differential_ale='geometry', component_volume_bounds='bounds-fn'),
        InterfaceParallelPolicy=lambda **k: ('parallel', k))
    m.J.forward, m.J.finish, m.J.CAS = 'forward', 'exterior-finish', SimpleNamespace(save='checkpoint-save')
    m.J.I = SimpleNamespace(F=SimpleNamespace(LOW=SimpleNamespace(solve='solve'),
        FUNCTIONS=SimpleNamespace(reconstruct='reconstruct', _face='face',
                                  PARALLEL=SimpleNamespace(completed='completed')),
        FINISH=SimpleNamespace(finish='finish', C=SimpleNamespace(correct='correct'),
                               Q=SimpleNamespace(closed_guard='closed-guard', _guard=guard_scan),
                               I=SimpleNamespace(issue='issue'))),
        N=SimpleNamespace(project='project', R=SimpleNamespace(verified_private='decode', calculate='exact')),
        HEAT_LEDGER=SimpleNamespace(package_result='package-result'),
        INDEXED=SimpleNamespace(metric_identity='metric-identity'))
    return m, case, spatial_owner


class Store:
    limits = SimpleNamespace()
    compression = SimpleNamespace()

    def metadata(self, key):
        return {'key': 'k'*64, 'kind': 'root', 'sequence': 0}


def lineage(**change):
    """Item 21: the runner's sealed-lineage record for an interval-1 parent of the stand-in root."""
    return dict({'schema': 'atlas.fresh-interval-lineage.v1', 'interval': 1, 'workflow_id': 'w'*64,
                 'root_key': 'k'*64, 'head_key': 'h'*64}, **change)


def advance_once(log, effect=None):
    """The prepared driver's stand-in: it advances the open workflow once, or applies ``effect``."""
    def advance_prepared_interval(**kwargs):
        workflow = kwargs['workflow']
        log.add('driver', **kwargs)
        assert workflow._open, 'the prepared driver runs with the workflow open'
        if effect is not None:
            return effect(workflow)
        workflow._intervals += 1
        workflow._head = {'kind': 'successor', 'key': 's'*64, 'sequence': workflow._intervals}
    return SimpleNamespace(advance_prepared_interval=advance_prepared_interval)


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.log = Recorder()
        self.phases = []
        F.asdict = lambda value: {}

    @contextmanager
    def open_store(self, workflow_id):
        self.log.add('open_store', workflow_id)
        yield Store()

    def finish_root(self, workflow, store, root):
        self.log.add('finish_root', workflow.inspect()['intervals'], root['root_key'])
        return root

    def create_root(self, m):
        return F.create_root(m, open_store=self.open_store, budget='budget', artifacts=Path('artifacts'),
                             phase=self.phases.append, finish_root=self.finish_root)

    def test_run_a_creates_the_root_with_the_admission_objects_and_advances_nothing(self):
        m, case, owner = stand_ins(self.log)
        root = self.create_root(m)
        (create,) = self.log.named('create')
        self.assertEqual(create[1][1:4], (case['collar'], case['owner'], case['funding']))
        self.assertEqual(create[2], {'budget': 'budget', 'exterior_owner': owner,
                                     'differential_partition': 'partition', 'current_geometry': 'current'})
        # The catalog is created under the admission's own workflow ID, before the root.
        self.assertEqual(self.log.named('identity')[0][1], (case['collar'], case['funding'],
                                                             {'owner_id': 'spatial-owner'}))
        names = [call[0] for call in self.log.calls]
        self.assertLess(names.index('open_store'), names.index('create'))
        self.assertEqual(self.log.named('open_store')[0][1], ('w'*64,))
        self.assertEqual(self.log.named('finish_root'), [('finish_root', (0, 'k'*64), {})])
        self.assertEqual(self.log.named('advance'), [])
        self.assertEqual(self.log.named('pressure'), [])
        self.assertEqual(root['sequence'], 0)
        self.assertEqual(root['preparation_ids']['spatial_owner'], 'spatial-owner')
        self.assertEqual(self.log.named('initial_partition')[0][2], F.INITIAL_PARTITION)
        self.assertIn('create-fresh-root', self.phases)

    def test_run_a_refuses_a_root_under_another_workflow_id(self):
        m, _, _ = stand_ins(self.log, identity='x'*64)
        with self.assertRaisesRegex(F.FreshIntervalRefused, 'admission workflow ID'):
            self.create_root(m)
        self.assertEqual(self.log.named('finish_root'), [])

    def run_b(self, change=None, **options):
        m, case, owner = stand_ins(self.log, **options)
        expected = self.create_root(m)
        if change is not None:
            expected = dict(expected, **change)
        self.log = Recorder()
        m, case, owner = stand_ins(self.log, **options)
        finished, record = [], {}
        # Kept before the call, so a test of a refusal can read what the driver recorded before it refused.
        self.record = record

        def finish(workflow, *, before, after, parent, root_bytes):
            finished.append((before['intervals'], after['intervals']))
            # Captured before the advance: the root head and the unchanged root bytes.
            self.assertEqual((parent['kind'], root_bytes), ('root', workflow._root))
            return 'finished'

        result = F.advance_first_interval(m, store=Store(), expected_root=expected, budget='budget',
            artifacts=Path('artifacts'), phase=self.phases.append, guard=SimpleNamespace(check='check'),
            record=record, save=lambda: None, query_checkpoints=lambda execution: self.checkpoints(execution),
            finish=finish)
        self.assertEqual(record['root_reproduced'], {name: expected[name] for name in F.ROOT_IDENTITY})
        return result, finished, case, owner

    @contextmanager
    def checkpoints(self, execution):
        self.log.add('checkpoints', execution.kind)
        yield 'checkpoint-owner'

    def test_run_b_opens_the_root_and_advances_once_with_r9_arguments(self):
        result, finished, case, owner = self.run_b()
        self.assertEqual(result, 'finished')
        self.assertEqual(finished, [(0, 1)])
        (opened,) = self.log.named('open')
        self.assertEqual(opened[1][1:5], ('w'*64, case['collar'], case['owner'], case['funding']))
        self.assertEqual(opened[2], {'budget': 'budget', 'exterior_owner': owner})
        (pressure,) = self.log.named('pressure')
        self.assertEqual({k: pressure[2][k] for k in F.PRESSURE_FORCE}, F.PRESSURE_FORCE)
        (advance,) = self.log.named('advance')
        kwargs = advance[2]
        self.assertEqual((kwargs['network'], kwargs['force_control'], kwargs['absolute_heat_residual_target']),
                         ('network', 'actuated', 'target'))
        self.assertEqual(kwargs['endpoint_checkpoints'], 'checkpoint-owner')
        self.assertEqual(kwargs['ale_max_leaves'], 2**19)
        self.assertEqual(kwargs['ale_parallel'][1]['mode'], 'auto')
        self.assertEqual(self.log.named('checkpoints')[0][1], ('scipy',))
        self.assertEqual(self.log.named('check_reopened')[0][1], ('restored',))

    def observed_stages(self):
        (observe,) = self.log.named('observe')
        stages = observe[2]['stages']
        # The six r9 stages keep their functions and order; each item 11 M marker follows the stage it splits.
        self.assertEqual(stages[:11], [('geometry', 'actual-differential-geometry'),
            ('forward', 'actual-composed-heat-forward'), ('solve', 'heat-low-predictor'),
            ('reconstruct', 'heat-certified-polygon-reconstruction'), ('finish', 'heat-conservative-finish'),
            ('correct', 'heat-finish-correction'), ('closed-guard', 'heat-finish-closed-guard'),
            ('issue', 'heat-finish-issue'), ('project', 'heat-native-projection'),
            ('decode', 'heat-projection-decode'), ('exact', 'heat-projection-exact')])
        self.assertEqual(self.record['observed_stages'], [name for _, name in stages])
        return {name: value for value, name in stages[11:]}

    def observed_ticks(self):
        (observe,) = self.log.named('observe')
        return observe[2]['ticks']

    def test_item11m_heat_counters_follow_the_r9_three(self):
        self.run_b()
        self.observed_stages()
        ticks = self.observed_ticks()
        self.assertEqual([name for _, name in ticks], list(R9_TICKS+HEAT_TICKS))
        self.assertEqual([value for value, _ in ticks[:4]], ['bounds-fn', 'face', 'completed', 'metric-identity'])
        # The scan makes its nested functions afresh at each call; the observer reads only their code object.
        certificate, admissible = closed_guard_scan()
        (certificates, _), (admissibles, _) = ticks[4:]
        self.assertEqual((sorted(vars(certificates)), sorted(vars(admissibles))), (['__code__'], ['__code__']))
        self.assertIs(certificates.__code__, certificate.__code__)
        self.assertIs(admissibles.__code__, admissible.__code__)

    def test_item11m_a_scan_without_one_direct_nested_function_refuses_before_the_admission(self):
        def without():
            return None

        def only_certificate():
            def certificate(value):
                return value
            return certificate

        def twice(flag):
            if flag:
                def certificate(value):
                    return 1
            else:
                def certificate(value):
                    return 2
            def admissible(value):
                return value
            return certificate, admissible

        def deeper():
            def outer():
                def certificate(value):
                    return value
                def admissible(value):
                    return value
                return certificate, admissible
            return outer

        for scan, missing in ((without, 'certificate'), (only_certificate, 'admissible'), (twice, 'certificate'),
                              (deeper, 'certificate')):
            with self.subTest(scan=scan.__name__):
                with self.assertRaisesRegex(F.FreshIntervalRefused, 'exactly one nested %s' % missing):
                    self.run_b(guard_scan=scan)
                # Refused before the admission: run B built no fixture and opened no observer.
                self.assertEqual((self.log.named('fixture'), self.log.named('observe')), ([], []))
                self.assertNotIn('observed_stages', self.record)

    def test_item11_the_projection_to_commit_window_is_split_in_call_order(self):
        self.run_b()
        stages = self.observed_stages()
        self.assertEqual(list(stages), list(COMMIT_STAGES))
        self.assertEqual([stages[name] for name in ('heat-result-packaging', 'heat-checkpoint-save',
                                                    'heat-exterior-finish')],
                         ['package-result', 'checkpoint-save', 'exterior-finish'])
        self.assertEqual(stages['heat-checkpoint-r3-checks'].__name__, '_r3_after_heat_checkpoint')
        self.assertEqual(stages['endpoint-store-publish'].__name__, '_publish')

    def test_item11_without_the_r3_transform_only_its_stage_is_absent_and_recorded(self):
        self.run_b(r3_checks=False)
        self.assertEqual(list(self.observed_stages()),
                         [name for name in COMMIT_STAGES if name != 'heat-checkpoint-r3-checks'])

    def test_run_b_refuses_a_non_root_head_and_a_double_advance(self):
        with self.assertRaisesRegex(F.FreshIntervalRefused, 'sealed sequence-0 fresh root'):
            self.run_b(opened_kind='successor')
        self.log = Recorder()
        with self.assertRaisesRegex(F.FreshIntervalRefused, 'exactly once'):
            self.run_b(after_intervals=2)

    def test_run_b_refuses_any_difference_from_run_a_root(self):
        for change in ({'root_metadata_sha256': '0'*64}, {'execution_provenance': {'context': 'other'}},
                       {'preparation_ids': {'owner': 'other'}}, {'sequence': 1}):
            self.log = Recorder()
            with self.assertRaisesRegex(F.FreshIntervalRefused, 'differs from run A sealed root: '+next(iter(change))):
                self.run_b(change=change)
            self.assertEqual(self.log.named('advance'), [])

    def test_smoke_reopens_the_adopted_root_and_stops_before_any_advance(self):
        m, _, _ = stand_ins(self.log)
        expected = self.create_root(m)
        self.log = Recorder()
        m, _, owner = stand_ins(self.log)
        found = F.reopen_root(m, store=Store(), expected_root=expected, budget='budget', artifacts=Path('artifacts'),
                              phase=self.phases.append)
        self.assertEqual({name: found[name] for name in F.ROOT_IDENTITY},
                         {name: expected[name] for name in F.ROOT_IDENTITY})
        self.assertEqual(found['inspect']['intervals'], 0)
        (opened,) = self.log.named('open')
        self.assertEqual(opened[2], {'budget': 'budget', 'exterior_owner': owner})
        self.assertEqual((self.log.named('pressure'), self.log.named('advance')), ([], []))
        self.assertIn('reopen-adopted-fresh-root', self.phases)
        self.log = Recorder()
        m, _, _ = stand_ins(self.log)
        with self.assertRaisesRegex(F.FreshIntervalRefused, 'differs from run A sealed root: sequence'):
            F.reopen_root(m, store=Store(), expected_root=dict(expected, sequence=1), budget='budget',
                          artifacts=Path('artifacts'), phase=self.phases.append)
        m, _, _ = stand_ins(Recorder(), opened_kind='successor')
        with self.assertRaisesRegex(F.FreshIntervalRefused, 'adopted sequence-0 fresh root'):
            F.reopen_root(m, store=Store(), expected_root=expected, budget='budget', artifacts=Path('a'),
                          phase=self.phases.append)

    def test_both_runs_refuse_an_unpinned_hash_seed(self):
        import os
        saved = os.environ.get('PYTHONHASHSEED')
        os.environ['PYTHONHASHSEED'] = '1'
        try:
            m, _, _ = stand_ins(self.log)
            with self.assertRaisesRegex(F.FreshIntervalRefused, 'PYTHONHASHSEED=0'):
                self.create_root(m)
            with self.assertRaisesRegex(F.FreshIntervalRefused, 'PYTHONHASHSEED=0'):
                F.advance_first_interval(m, store=Store(), expected_root={}, budget='budget', artifacts=Path('a'),
                    phase=self.phases.append, guard=None, record={}, save=None, query_checkpoints=None,
                    finish=None)
        finally:
            os.environ['PYTHONHASHSEED'] = saved if saved is not None else '0'
        self.assertEqual(self.log.calls, [])

    # Item 21: interval N >= 2 reopens the adopted interval N-1 head and advances it through the prepared driver.
    @contextmanager
    def active_checkpoints(self, execution):
        self.log.add('checkpoints', execution.kind)
        yield 'checkpoint-owner'
        self.log.add('checkpoints-closed')

    def run_successor(self, change=None, chain=None, effect=None, **options):
        m, _, _ = stand_ins(self.log)
        expected = self.create_root(m)
        if change is not None:
            expected = dict(expected, **change)
        self.log, self.phases = Recorder(), []
        m, case, owner = stand_ins(self.log, **{'opened_kind': 'successor', 'opened_intervals': 1, **options})
        m.prepared_interval_driver = advance_once(self.log, effect)
        self.chain = lineage() if chain is None else chain
        self.guard, self.record, self.finished = SimpleNamespace(check='check'), {}, []
        self.save = lambda: self.log.add('save')

        def finish(workflow, *, before, after, parent, root_bytes):
            self.log.add('finish')
            self.finished.append((workflow, before['intervals'], after['intervals']))
            # Captured before the advance: the adopted parent head and the unchanged root bytes.
            self.assertTrue(workflow._open)
            self.assertEqual((parent['kind'], parent['key'], root_bytes), ('successor', 'h'*64, workflow._root))
            return 'finished'
        result = F.advance_successor_interval(m, store=Store(), expected_root=expected, lineage=self.chain,
            budget='budget', artifacts=Path('artifacts'), phase=self.phases.append, guard=self.guard,
            record=self.record, save=self.save, query_checkpoints=self.active_checkpoints, finish=finish)
        return result, expected, m, case, owner

    def assertNothingAdvanced(self):
        self.assertEqual([self.log.named(name) for name in ('checkpoints', 'driver', 'finish')], [[], [], []])

    def test_successor_opens_the_lineage_head_and_advances_once_through_the_prepared_driver(self):
        result, expected, m, case, owner = self.run_successor()
        self.assertEqual(result, 'finished')
        ((workflow, parent_intervals, intervals),) = self.finished
        self.assertEqual((parent_intervals, intervals), (1, 2))
        (opened,) = self.log.named('open')
        self.assertEqual(opened[1][1:5], ('w'*64, case['collar'], case['owner'], case['funding']))
        self.assertEqual(opened[2], {'budget': 'budget', 'exterior_owner': owner})
        (driver,) = self.log.named('driver')
        kwargs = driver[2]
        self.assertEqual(set(kwargs), {'case', 'workflow', 'base', 'execution', 'guard', 'record', 'save',
                                       'artifacts', 'query_checkpoints', 'lineage', 'joined_module'})
        same = {'case': case, 'workflow': workflow, 'guard': self.guard, 'record': self.record, 'save': self.save,
                'lineage': self.chain, 'joined_module': m.joined}
        for name, value in same.items():
            self.assertIs(kwargs[name], value, name)
        self.assertIsNone(kwargs['base'])
        self.assertEqual((kwargs['execution'].kind, kwargs['artifacts'], kwargs['query_checkpoints']),
                         ('scipy', Path('artifacts'), 'checkpoint-owner'))
        # The completed-query owner is bound to the heat context and stays active through finish;
        # the record is saved between the advance and finish.
        self.assertEqual(self.log.named('checkpoints')[0][1], ('scipy',))
        names = [call[0] for call in self.log.calls]
        order = ('open', 'checkpoints', 'driver', 'save', 'finish', 'checkpoints-closed')
        self.assertEqual([name for name in names if name in order], list(order))
        self.assertLess(names.index('finish'), names.index('verify_boundary'))
        # The prepared driver owns the continuation pressure/force step, the observer and the thread limit.
        self.assertEqual([self.log.named(name) for name in ('pressure', 'advance', 'observe', 'threadpool_limits')],
                         [[], [], [], []])
        self.assertEqual(self.record['root_reproduced'], {name: expected[name] for name in F.ROOT_IDENTITY})
        self.assertIn('reopen-adopted-successor-head', self.phases)

    def test_successor_refuses_an_unsealed_or_foreign_lineage_before_any_admission(self):
        unsigned = {k: v for k, v in lineage().items() if k != 'schema'}
        for chain, message in ((['not', 'a', 'record'], 'sealed lineage record'),
                               (lineage(schema='atlas.fresh-interval-lineage.v0'), 'sealed lineage record'),
                               (unsigned, 'sealed lineage record'),
                               (lineage(interval=0), 'interval 1 or later'),
                               (lineage(interval=True), 'interval 1 or later'),
                               (lineage(interval=1.0), 'interval 1 or later'),
                               (lineage(interval='1'), 'interval 1 or later'),
                               (lineage(workflow_id='x'*64), "not of run A's root: workflow_id$"),
                               (lineage(root_key='x'*64), "not of run A's root: root_key$")):
            with self.subTest(chain=chain):
                with self.assertRaisesRegex(F.FreshIntervalRefused, message):
                    self.run_successor(chain=chain)
                # Nothing after run A's root ran: no admission, no phase.
                self.assertEqual((self.log.calls, self.phases), ([], []))

    def test_successor_refuses_a_head_other_than_the_lineage_parent(self):
        for options, chain, field in (({}, lineage(head_key='x'*64), 'head_key'),
                                      ({'opened_intervals': 2}, None, 'interval'),
                                      ({}, lineage(interval=2), 'interval'),
                                      ({'opened_kind': 'root'}, None, 'kind')):
            with self.subTest(field=field, options=options):
                with self.assertRaisesRegex(F.FreshIntervalRefused,
                                            'other than the sealed lineage parent: '+field+'$'):
                    self.run_successor(chain=chain, **options)
                self.assertNothingAdvanced()

    def test_successor_refuses_any_difference_from_run_a_root(self):
        for change in ({'root_metadata_sha256': '0'*64}, {'execution_provenance': {'context': 'other'}},
                       {'preparation_ids': {'owner': 'other'}}, {'sequence': 1}, {'kind': 'successor'}):
            with self.subTest(change=next(iter(change))):
                with self.assertRaisesRegex(F.FreshIntervalRefused,
                                            'differs from run A sealed root: '+next(iter(change))+'$'):
                    self.run_successor(change=change)
                self.assertNothingAdvanced()

    def test_successor_refuses_unless_the_driver_advanced_exactly_once(self):
        def successor(workflow, steps):
            workflow._intervals += steps
            workflow._head = {'kind': 'successor', 'key': 's'*64, 'sequence': workflow._intervals}

        def nothing(workflow):
            pass

        def twice(workflow):
            successor(workflow, 2)

        def root_changed(workflow):
            successor(workflow, 1)
            workflow._root = json.dumps({'key': 'x'*64, 'kind': 'root', 'sequence': 0})

        def head_unchanged(workflow):
            workflow._intervals += 1

        def funding_changed(workflow):
            successor(workflow, 1)
            workflow._funding = 'other-funding'
        for effect in (nothing, twice, root_changed, head_unchanged, funding_changed):
            with self.subTest(effect=effect.__name__):
                with self.assertRaisesRegex(F.FreshIntervalRefused, 'interval 2 did not advance exactly once'):
                    self.run_successor(effect=effect)
                self.assertEqual((len(self.log.named('driver')), self.log.named('finish')), (1, []))

    def test_successor_refuses_an_unpinned_hash_seed_before_reading_its_lineage(self):
        import os
        saved = os.environ.get('PYTHONHASHSEED')
        os.environ['PYTHONHASHSEED'] = '1'
        try:
            m, _, _ = stand_ins(self.log)
            with self.assertRaisesRegex(F.FreshIntervalRefused, 'PYTHONHASHSEED=0'):
                F.advance_successor_interval(m, store=Store(), expected_root={}, lineage=None, budget='budget',
                    artifacts=Path('a'), phase=self.phases.append, guard=None, record={}, save=None,
                    query_checkpoints=None, finish=None)
        finally:
            os.environ['PYTHONHASHSEED'] = saved if saved is not None else '0'
        self.assertEqual(self.log.calls, [])

    def test_the_lineage_schema_is_the_prepared_driver_schema(self):
        import prepared_interval_driver as P
        self.assertEqual((F.LINEAGE_SCHEMA, P.LINEAGE_SCHEMA), ('atlas.fresh-interval-lineage.v1',)*2)


def composed_tree(*parts):
    return ast.parse(COMPOSED.joinpath(*parts).read_text(encoding='utf-8'))


def calls(node, owner, attribute):
    """Line numbers of the calls ``<owner>.<attribute>(...)`` under ``node``."""
    return [n.lineno for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == attribute and ast.unparse(n.func.value) == owner]


def function(tree, name, owner=None):
    body = tree.body if owner is None else next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner).body
    return next(n for n in body if isinstance(n, ast.FunctionDef) and n.name == name)


def imports(tree):
    return {alias.asname or alias.name: alias.name for n in tree.body if isinstance(n, ast.Import)
            for alias in n.names}


class CommitStageSourceTests(unittest.TestCase):
    """Item 11: in composed-r2, each observed commit-window function is an undecorated function where
    _commit_stages reads it, and the spatial heat route calls each once, after the projection, in stage
    order. A stage on a function that never runs would leave the window unsplit after a real run."""

    def test_each_stage_is_a_plain_function_where_the_driver_reads_it(self):
        issuer = composed_tree('helpers', 'private_heat_native_issuer_r13.py')
        consumer = composed_tree('helpers', 'private_heat_joined_consumer_r6.py')
        self.assertEqual(imports(issuer)['HEAT_LEDGER'], 'heat_ledger_issuer_patch')
        self.assertEqual({k: imports(consumer)[k] for k in ('I', 'CAS')},
                         {'I': 'private_heat_native_issuer_r13', 'CAS': 'private_heat_checkpoint_consumer_r10'})
        workflow = ('src', 'atlas_tectonics', 'integration_regional_workflow.py')
        for parts, name, owner in ((('helpers', 'heat_ledger_issuer_patch.py'), 'package_result', None),
                                   (('helpers', 'private_heat_checkpoint_consumer_r10.py'), 'save', None),
                                   (('helpers', 'private_heat_joined_consumer_r6.py'), 'finish', None),
                                   (workflow, '_r3_after_heat_checkpoint', 'CollarWorkflow'),
                                   (workflow, '_publish', 'CollarWorkflow')):
            self.assertEqual(function(composed_tree(*parts), name, owner).decorator_list, [], name)

    def test_the_spatial_heat_route_calls_each_once_in_stage_order(self):
        issuer = composed_tree('helpers', 'private_heat_native_issuer_r13.py')
        self.assertEqual(len(calls(issuer, 'HEAT_LEDGER', 'package_result')), 1)
        verified = function(issuer, '_advance_verified')
        (project,), (package,) = calls(verified, 'N', 'project'), calls(verified, 'HEAT_LEDGER', 'package_result')
        self.assertLess(project, package)
        forward = function(composed_tree('helpers', 'private_heat_joined_consumer_r6.py'), 'forward')
        (advance,), (save,) = calls(forward, 'I', 'advance'), calls(forward, 'CAS', 'save')
        self.assertLess(advance, save)
        owner = composed_tree('src', 'atlas_tectonics', 'integration_spatial_owner.py')
        self.assertEqual(len(calls(function(owner, 'heat', 'PreparedSpatialOwner'), 'J', 'forward')), 1)
        self.assertEqual(len(calls(function(owner, 'finish', 'PreparedSpatialOwner'), 'J', 'finish')), 1)
        spatial = function(composed_tree('src', 'atlas_tectonics', 'integration_regional_workflow.py'),
                           'advance_spatial', 'CollarWorkflow')
        heat, finish = calls(spatial, 'self._exterior_owner', 'heat'), calls(spatial, 'self._exterior_owner', 'finish')
        (r3,), (publish,) = calls(spatial, 'self', '_r3_after_heat_checkpoint'), calls(spatial, 'self', '_publish')
        self.assertTrue(heat and finish)
        # The private-heat branch's checkpointed heat call is the first; the other branch's follows r3.
        self.assertLess(min(heat), r3)
        self.assertLess(r3, min(finish))
        self.assertLess(max(finish), publish)


class MeasurementHookTests(unittest.TestCase):
    """Item 7: each admission reports its open measurement store once; observation only."""

    def setUp(self):
        from unittest import mock
        patch = mock.patch.object(F, 'asdict', lambda value: {}, create=True)
        patch.start()
        self.addCleanup(patch.stop)

    def stand_ins(self, log, **options):
        m, _, _ = stand_ins(log, **options)
        statistics = {'snapshots': 3, 'operations': {'payload_reads': 0}}

        @contextmanager
        def cache(path, *args, **kwargs):
            log.add('cache', path=str(path))
            yield SimpleNamespace(statistics=lambda: (log.add('statistics'), dict(statistics))[1])
        m.ArrayStore = cache
        return m, statistics

    @contextmanager
    def open_store(self, workflow_id):
        yield Store()

    @contextmanager
    def checkpoints(self, execution):
        yield 'checkpoint-owner'

    def root(self, log, **kwargs):
        m, _ = self.stand_ins(log)
        return F.create_root(m, open_store=self.open_store, budget='budget', artifacts=Path('artifacts'),
                             phase=lambda name: None, finish_root=lambda workflow, store, root: root, **kwargs)

    def test_each_entry_reports_once_between_the_metrics_and_the_owner(self):
        expected = self.root(Recorder())
        common = {'budget': 'budget', 'artifacts': Path('artifacts'), 'phase': lambda name: None}
        entries = {
            'create_root': lambda m, hook: F.create_root(m, open_store=self.open_store,
                finish_root=lambda workflow, store, root: root, measurements=hook, **common),
            'reopen_root': lambda m, hook: F.reopen_root(m, store=Store(), expected_root=expected,
                measurements=hook, **common),
            'advance_first_interval': lambda m, hook: F.advance_first_interval(m, store=Store(),
                expected_root=expected, guard=SimpleNamespace(check='check'), record={}, save=lambda: None,
                query_checkpoints=self.checkpoints, finish=lambda workflow, **kwargs: 'finished',
                measurements=hook, **common)}
        for name, entry in entries.items():
            with self.subTest(entry=name):
                log, seen = Recorder(), []
                m, statistics = self.stand_ins(log)
                entry(m, lambda found, bounds: (log.add('hook'), seen.append((found, bounds))))
                self.assertEqual(seen, [(statistics, 'bounds')])
                names = [call[0] for call in log.calls]
                self.assertEqual((names.count('statistics'), names.count('hook')), (1, 1))
                self.assertLess(names.index('initial_metrics'), names.index('statistics'))
                self.assertLess(names.index('hook'), names.index('initial_spatial_owner'))
                self.assertEqual(log.named('cache')[0][2], {'path': str(Path('artifacts')/'initial-measurements.sqlite')})

    def test_the_successor_entry_reports_once_between_the_metrics_and_the_owner(self):
        expected = self.root(Recorder())
        log, seen = Recorder(), []
        m, statistics = self.stand_ins(log, opened_kind='successor', opened_intervals=1)
        m.prepared_interval_driver = advance_once(log)
        result = F.advance_successor_interval(m, store=Store(), expected_root=expected, lineage=lineage(),
            budget='budget', artifacts=Path('artifacts'), phase=lambda name: None,
            guard=SimpleNamespace(check='check'), record={}, save=lambda: None, query_checkpoints=self.checkpoints,
            finish=lambda workflow, **kwargs: 'finished',
            measurements=lambda found, bounds: (log.add('hook'), seen.append((found, bounds))))
        self.assertEqual((result, seen), ('finished', [(statistics, 'bounds')]))
        names = [call[0] for call in log.calls]
        self.assertEqual((names.count('statistics'), names.count('hook')), (1, 1))
        self.assertLess(names.index('initial_metrics'), names.index('statistics'))
        self.assertLess(names.index('hook'), names.index('initial_spatial_owner'))
        self.assertLess(names.index('initial_spatial_owner'), names.index('driver'))

    def test_without_a_hook_the_store_is_never_asked(self):
        log = Recorder()
        self.root(log)
        self.assertEqual(log.named('statistics'), [])

    def test_a_failing_hook_stops_the_admission_before_the_owner(self):
        log = Recorder()

        def hook(found, bounds):
            raise ValueError('hook refused')
        with self.assertRaisesRegex(ValueError, 'hook refused'):
            self.root(log, measurements=hook)
        self.assertEqual(log.named('initial_spatial_owner'), [])


if __name__ == '__main__':
    unittest.main()
