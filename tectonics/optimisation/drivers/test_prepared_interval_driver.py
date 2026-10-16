"""Driver controls: source shape plus the actual driver over synthetic modules.

The functional scenarios run prepared_interval_driver.advance_prepared_interval
in a fresh interpreter with the REAL hook-free geometry observer (frozen I
helper bytes) and the real sys.monitoring slots. Native, joined, continuation
and heat modules are explicit stand-ins: no physics, store or acceptance. The
composed import-closure and real-owner checks belong to the composed wave.

Item 21 (16 Oct 2026): OrdinaryHeadScenarios run the same driver on an ordinary
fresh-lineage head (base None, the runner's sealed lineage, the joined r8 module);
the migrated scenarios above are unchanged.
"""
import ast
from dataclasses import dataclass
from hashlib import sha256
import gc
import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest

import run_prepared_restart as R

HERE = Path(__file__).resolve().parent
DRIVER = HERE/'prepared_interval_driver.py'
OBSERVER = HERE.parent/'runtime-integration-r1/helpers/private_heat_geometry_observer_r1.py'
OBSERVER_PIN = '3a6f2eadea7cf8168ab0b4517261f2d87d132f66486eeeebc930705f2a59f9d3'
SCENARIOS = ('success', 'compact-mesh', 'missing-state', 'duration', 'no-checkpoint-parameter', 'foreign-tool')
LINEAGE_SCHEMA = 'atlas.fresh-interval-lineage.v1'
SIX_STAGES = ['actual-differential-geometry', 'actual-composed-heat-forward', 'heat-low-predictor',
              'heat-certified-polygon-reconstruction', 'heat-conservative-finish', 'heat-native-projection']
COMMIT_STAGES = ['heat-result-packaging', 'heat-checkpoint-save', 'heat-checkpoint-r3-checks',
                 'heat-exterior-finish', 'endpoint-store-publish']
MIGRATED_TYPE = 'actual same-budget migrated head and active query checkpoint owner required'
ORDINARY_TYPE = 'actual same-budget ordinary head and active query checkpoint owner required'


class SourceShape(unittest.TestCase):
    def setUp(self):
        self.text = DRIVER.read_text(encoding='utf8')
        tree = ast.parse(self.text)
        self.function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and
                             n.name == 'advance_prepared_interval')

    def test_hook_free_observer_replaces_the_always_on_observer(self):
        imports = {(alias.name, alias.asname) for node in ast.walk(self.function) if isinstance(node, ast.Import)
                   for alias in node.names}
        self.assertIn(('private_heat_geometry_observer_r1', 'geometry_observer'), imports)
        withs = [n for n in self.function.body if isinstance(n, ast.With)]
        self.assertEqual(len(withs), 1)
        observe, limits = (item.context_expr for item in withs[0].items)
        self.assertEqual(ast.unparse(observe),
            'geometry_observer.observe(guard, stages, ticks, joined=joined, geometry=G.enclose_differential_ale)')
        self.assertEqual(ast.unparse(limits), 'threadpool_limits(1)')
        old = [n for n in ast.walk(self.function) if isinstance(n, ast.Attribute) and n.attr == 'observe' and
               isinstance(n.value, ast.Name) and n.value.id == 'D']
        self.assertEqual(old, [], 'the always-on observer keeps automatic geometry serial')
        body = [ast.unparse(statement) for statement in withs[0].body]
        self.assertEqual(body[0], "record['selector_gate_before_advance'] = selector_gate(PF)")
        self.assertTrue(body[-1].startswith('continuation.continuation_pressure_force('))

    def test_prechecks_precede_work_and_old_validator_absent(self):
        for check in ("'endpoint_checkpoints' in inspect.signature(joined._advance_current_interval)",
                      'type(case.get(\'state\')) is IW.InitialWorkloadState',
                      "json.loads(base._endpoint)['head']['advance']['duration_s']"):
            self.assertLess(self.text.index(check), self.text.index('record.update(original_target='))
        self.assertLess(self.text.index('record.update(original_target='), self.text.index('with geometry_observer.observe('))
        for absent in ('_validate_continuation', 'probe_heat_original_continue', "artifacts/'parallel-profile.json'"):
            self.assertNotIn(absent, self.text)
        self.assertIn('endpoint_checkpoints=query_checkpoints', self.text)

    def test_completed_records_preparation_ids_and_mesh_gate_refuses_first(self):
        completed = next(n for n in ast.walk(self.function) if isinstance(n, ast.FunctionDef) and n.name == 'completed')
        ids = next(k.value for n in ast.walk(completed) if isinstance(n, ast.Call)
                   for k in n.keywords if k.arg == 'preparation_ids')
        self.assertEqual({k.arg for k in ids.keywords}, {'owner', 'spatial_owner', 'native', 'collar', 'map', 'funding'})
        self.assertEqual(ast.unparse(next(k.value for k in ids.keywords if k.arg == 'spatial_owner')), 'owner.owner_id')
        gate = next(n for n in ast.walk(self.function) if isinstance(n, ast.FunctionDef) and n.name == 'before_advance')
        refusal = next(n for n in gate.body if isinstance(n, ast.For))
        coverage = next(n for n in ast.walk(gate) if isinstance(n, ast.Call) and
                        getattr(n.func, 'attr', None) == 'inspect_preadvance')
        self.assertLess(refusal.lineno, coverage.lineno)
        self.assertIn("'_json'", ast.unparse(refusal))

    def test_observer_input_is_the_frozen_reviewed_helper(self):
        self.assertEqual(sha256(OBSERVER.read_bytes()).hexdigest(), OBSERVER_PIN)


def run_scenario(name, *, seeded=True):
    env = {k: v for k, v in R.launch_environment().items() if seeded or k != 'PYTHONHASHSEED'}
    with tempfile.TemporaryDirectory(prefix='pd-', dir=HERE) as directory:
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--scenario', name, directory],
                                cwd=HERE, env=env, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise AssertionError(result.stdout[-3000:]+result.stderr[-6000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


class DriverScenarios(unittest.TestCase):
    def test_timing_records_completed_subsections_without_instrumenting_geometry(self):
        row = run_scenario('success-timing')
        self.assertIsNone(row['error'])
        self.assertFalse(row['seen']['inside_instrumented'])
        self.assertIsNone(row['tool3_after'])
        self.assertEqual(row['reserved_after'], 0)
        report = row['timing_report']
        self.assertEqual(report['status'], 'COMPLETE')
        self.assertEqual([stage['phase'] for stage in report['stages']['rows']], [
            'pressure-and-force-selection-complete',
            'geometry-and-pre-advance-coverage-complete',
            'heat-projection-and-endpoint-publication-complete',
            'post-publication-reopen-controls-complete',
            'interval-source-boundary-verification-complete',
            'timing-finalisation'])

    def test_success_releases_own_tool_only_inside_ale_compute(self):
        row = run_scenario('success')
        self.assertIsNone(row['error'])
        seen = row['seen']
        self.assertTrue(seen['tool_in_continuation'] == 'private-original-heat-control' and seen['outside_instrumented'])
        self.assertFalse(seen['inside_instrumented'])
        self.assertIsNone(seen['tool_inside'])
        self.assertTrue(seen['endpoint_checkpoints_forwarded'])
        self.assertEqual(seen['max_partition_components'], 65536)
        self.assertEqual(seen['ceilings'], [2**19, 2**19])
        # Beside the persistent query directory, not inside it or the attempt output.
        self.assertEqual(Path(seen['profile_path']).name, 'queries.parallel-profile.json')
        gate = row['record']['selector_gate_before_advance']
        self.assertEqual((gate['seed'], gate['monitoring_tools'], gate['instrumented_in_observer_scope']),
                         ('0', {'3': 'private-original-heat-control'}, True))
        ids = row['record']['completed_endpoint']['preparation_ids']
        self.assertEqual(ids, dict(owner='owner-id', spatial_owner='evolved-spatial-owner', native='native-plan',
                                   collar='collar-plan', map='volume-map', funding='funding-id'))
        self.assertEqual(row['record']['continuation']['interval_number'], 2)
        self.assertEqual(row['record']['preheat_gate']['duration_s'], row['record']['initial_workload_duration_s'])
        self.assertIn('actual-differential-geometry', row['phases'])
        self.assertIn('current-physical-coverage-confirmed-before-advance', row['phases'])
        self.assertIsNone(row['tool3_after'])
        self.assertTrue(seen['verified'])
        self.assertEqual(row['reserved_after'], 0)

    def test_compact_end_mesh_refuses_clearly_before_the_coverage_gate(self):
        row = run_scenario('compact-mesh')
        self.assertEqual(row['error']['type'], 'PreparedIntervalRefused')
        self.assertIn('legacy end mesh record', row['error']['message'])
        self.assertNotIn('inspected', row['seen'])
        self.assertFalse(row['seen']['inside_instrumented'])
        self.assertIsNone(row['tool3_after'])
        self.assertEqual(row['reserved_after'], 0)

    def test_prechecks_refuse_before_any_physical_work(self):
        for name, message in (('missing-state', "case['state'] must be the authenticated InitialWorkloadState"),
                              ('duration', 'differs from the authenticated first interval'),
                              ('no-checkpoint-parameter', 'explicit completed-query owner'),
                              ('foreign-tool', 'foreign instrumentation')):
            with self.subTest(name=name):
                row = run_scenario(name)
                self.assertEqual(row['error']['type'], 'PreparedIntervalRefused')
                self.assertIn(message, row['error']['message'])
                self.assertNotIn('continuation_called', row['seen'])
                self.assertNotIn('prepare-actual-force-selected-interval', row['phases'])
                self.assertEqual(row['reserved_after'], 0)
        row = run_scenario('success', seeded=False)
        self.assertIn('PYTHONHASHSEED=0', row['error']['message'])
        self.assertNotIn('continuation_called', row['seen'])
        self.assertIsNone(row['tool3_after'])


class OrdinarySourceShape(unittest.TestCase):
    """Item 21: the ordinary branch is additive; the migrated route's call shape is unchanged."""

    def setUp(self):
        self.text = DRIVER.read_text(encoding='utf8')
        tree = ast.parse(self.text)
        self.function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and
                             n.name == 'advance_prepared_interval')

    def test_lineage_schema_and_keyword_only_defaults_keep_the_restarter_bind(self):
        self.assertIn(f"LINEAGE_SCHEMA = '{LINEAGE_SCHEMA}'", self.text)
        arguments = self.function.args
        defaults = {a.arg: d for a, d in zip(arguments.kwonlyargs, arguments.kw_defaults)}
        for name in ('lineage', 'joined_module'):
            self.assertIsInstance(defaults[name], ast.Constant)
            self.assertIsNone(defaults[name].value)
        spec = importlib.util.spec_from_file_location('prepared_interval_driver_shape', DRIVER)
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
        # The nine names run_prepared_restart binds before any work (its driver check).
        inspect.signature(driver.advance_prepared_interval).bind(**{k: None for k in (
            'case', 'workflow', 'base', 'execution', 'guard', 'record', 'save', 'artifacts', 'query_checkpoints')})

    def test_r6_is_imported_only_on_the_migrated_route(self):
        r6 = [n for n in ast.walk(self.function) if isinstance(n, ast.Import) and
              any(alias.name == 'private_heat_original_joined_r6' for alias in n.names)]
        self.assertEqual(len(r6), 1)
        self.assertNotIn(r6[0], self.function.body, 'an ordinary fresh lineage must never import joined r6')
        self.assertIn('from fresh_interval_driver import _commit_stages', self.text)


class OrdinaryHeadScenarios(unittest.TestCase):
    """Item 21: an adopted ordinary head (interval 1) advances once, bound to the sealed lineage."""

    def assertRefusedBeforeWork(self, row):
        self.assertNotIn('continuation_called', row['seen'])
        self.assertNotIn('prepare-actual-force-selected-interval', row['phases'])
        self.assertNotIn('original_target', row['record'])
        self.assertNotIn('selector_gate_before_advance', row['record'])
        self.assertIsNone(row['tool3_after'])
        self.assertEqual(row['reserved_after'], 0)

    def test_ordinary_head_advances_once_with_r8_and_the_commit_stages(self):
        row = run_scenario('ordinary-success')
        self.assertIsNone(row['error'])
        seen, record = row['seen'], row['record']
        self.assertEqual(seen['joined_called'], 'private_heat_original_joined_r8')
        self.assertFalse(seen['r6_loaded'])
        self.assertEqual(seen['check_reopened'], dict(restored='synthetic'))
        self.assertEqual(seen['fd_commit_names'], COMMIT_STAGES)
        self.assertEqual(record['observed_stages'], SIX_STAGES+COMMIT_STAGES)
        window = ['heat-native-projection', *COMMIT_STAGES, 'actual-heat-endpoint-committed']
        self.assertEqual([phase for phase in row['phases'] if phase in window], window)
        self.assertEqual(record['lineage_gate'], dict(workflow_id='wf', root_key='root-key', root_kind='root',
            head_key='parent-key', kind='successor', sequence=1, lineage_schema=LINEAGE_SCHEMA,
            parent_advance_duration_s=record['initial_workload_duration_s']))
        self.assertEqual(record['preheat_gate']['duration_s'], record['initial_workload_duration_s'])
        self.assertEqual(record['completed_endpoint']['sequence'], 2)
        continuation = record['continuation']
        self.assertEqual((continuation['parent_head_key'], continuation['parent_interval_number'],
                          continuation['interval_number']), ('parent-key', 1, 2))
        self.assertEqual(Path(seen['profile_path']).name, 'queries.parallel-profile.json')
        self.assertTrue(seen['endpoint_checkpoints_forwarded'])
        self.assertTrue(seen['tool_in_continuation'] == 'private-original-heat-control' and seen['outside_instrumented'])
        self.assertFalse(seen['inside_instrumented'])
        self.assertIsNone(seen['tool_inside'])
        self.assertTrue(seen['verified'])
        self.assertIsNone(row['tool3_after'])
        self.assertEqual(row['reserved_after'], 0)

    def test_ordinary_timing_has_the_migrated_subsections(self):
        row = run_scenario('ordinary-success-timing')
        self.assertIsNone(row['error'])
        self.assertEqual(row['timing_report']['status'], 'COMPLETE')
        self.assertEqual([stage['phase'] for stage in row['timing_report']['stages']['rows']], [
            'pressure-and-force-selection-complete',
            'geometry-and-pre-advance-coverage-complete',
            'heat-projection-and-endpoint-publication-complete',
            'post-publication-reopen-controls-complete',
            'interval-source-boundary-verification-complete',
            'timing-finalisation'])

    def test_migrated_route_keeps_r6_and_its_six_stages(self):
        row = run_scenario('success')
        self.assertIsNone(row['error'])
        self.assertEqual(row['seen']['joined_called'], 'private_heat_original_joined_r6')
        self.assertNotIn('observed_stages', row['record'])
        self.assertNotIn('lineage_gate', row['record'])
        # The stand-in runs the commit window on both routes; only the ordinary route observes it.
        self.assertIn('heat-native-projection', row['phases'])
        self.assertEqual([phase for phase in row['phases'] if phase in COMMIT_STAGES], [])

    def test_route_inputs_are_exclusive(self):
        for name, message in (('migrated-lineage', MIGRATED_TYPE), ('migrated-joined-module', MIGRATED_TYPE),
                              ('ordinary-neither', MIGRATED_TYPE), ('ordinary-migration-set', ORDINARY_TYPE)):
            with self.subTest(name=name):
                row = run_scenario(name)
                self.assertEqual(row['error'], dict(type='TypeError', message=message))
                self.assertRefusedBeforeWork(row)

    def test_ordinary_owner_checks_refuse_before_any_physical_work(self):
        for name in ('ordinary-workflow-type', 'ordinary-workflow-budget', 'ordinary-checkpoint-type',
                     'ordinary-inactive-checkpoints', 'ordinary-checkpoint-budget', 'ordinary-checkpoint-context'):
            with self.subTest(name=name):
                row = run_scenario(name)
                self.assertEqual(row['error'], dict(type='TypeError', message=ORDINARY_TYPE))
                self.assertRefusedBeforeWork(row)

    def test_lineage_mismatch_refuses_before_any_physical_work(self):
        for name, message in (('ordinary-lineage-schema', "needs the runner's sealed lineage record"),
                              ('ordinary-root-head', 'interval 1 or later'),
                              ('ordinary-interval-type', 'interval 1 or later'),
                              ('ordinary-workflow-id', 'differs from the sealed lineage: workflow_id'),
                              ('ordinary-root-key', 'differs from the sealed lineage: root_key'),
                              ('ordinary-root-kind', 'differs from the sealed lineage: root_kind'),
                              ('ordinary-head-key', 'differs from the sealed lineage: head_key'),
                              ('ordinary-kind', 'differs from the sealed lineage: kind'),
                              ('ordinary-sequence', 'differs from the sealed lineage: sequence'),
                              # Equal but not the same type: the comparison is type-strict.
                              ('ordinary-sequence-float', 'differs from the sealed lineage: sequence')):
            with self.subTest(name=name):
                row = run_scenario(name)
                self.assertEqual(row['error']['type'], 'PreparedIntervalRefused')
                if message.startswith('differs'):
                    # Exactly the one tampered field is named.
                    self.assertTrue(row['error']['message'].endswith(message), row['error'])
                else:
                    self.assertIn(message, row['error']['message'])
                self.assertRefusedBeforeWork(row)

    def test_ordinary_prechecks_refuse_before_any_physical_work(self):
        for name, message in (('ordinary-frozen-state', 'never enters an ordinary fresh lineage'),
                              ('ordinary-joined-r6', 'joined r8 module'),
                              ('ordinary-joined-unregistered', 'joined r8 module'),
                              ('ordinary-duration', "differs from the adopted parent head's advance"),
                              ('ordinary-no-checkpoint-parameter', 'explicit completed-query owner')):
            with self.subTest(name=name):
                row = run_scenario(name)
                self.assertEqual(row['error']['type'], 'PreparedIntervalRefused')
                self.assertIn(message, row['error']['message'])
                self.assertRefusedBeforeWork(row)


class FakeBudget:
    def __init__(self):
        self.reserved_bytes = 0

    def reserve(self, size, *, category):
        budget = self

        class Lease:
            def __enter__(self):
                budget.reserved_bytes += size
                return self

            def __exit__(self, *_):
                budget.reserved_bytes -= size
        return Lease()

    def try_reserve(self, size, *, category):
        return self.reserve(size, category=category)  # Unlimited synthetic budget.


@dataclass(frozen=True)
class FakeLimits:
    chunk_bytes: int = 65536


JOINED = '''
import contextvars
from contextlib import contextmanager
_ALE_COMPUTE_CONTEXT = contextvars.ContextVar('joined_ale_compute_context', default=None)


@contextmanager
def ale_compute_context(factory):
    if not callable(factory) or _ALE_COMPUTE_CONTEXT.get() is not None:
        raise ValueError('One explicit non-nested ALE diagnostic context required')
    token = _ALE_COMPUTE_CONTEXT.set(factory)
    try:
        yield
    finally:
        _ALE_COMPUTE_CONTEXT.reset(token)


def derivation():
    return dict(schema='synthetic-joined', changes=['stand-in'])


def _advance_current_interval(test, case, workflow, *, current, parent, owner, driver, pressure, datum,
        network, prior_interval=None, force_control, heat_execution, absolute_heat_residual_target, cancel,
        before_advance=None, completed_observer=None, max_partition_components=8192,
        ENDPOINT_PARAMETER ale_parallel=None, **options):
    HARNESS.seen['joined_called'] = __name__
    return HARNESS.advance(dict(locals()), _ALE_COMPUTE_CONTEXT)


def _check_reopened(test, workflow, restored):
    HARNESS.seen['check_reopened'] = restored
'''


def scenario_main(name, directory):
    """Actual driver over explicit stand-ins; prints one JSON summary line."""
    import numpy as np
    import initial_workload as IW
    import native_transfer as N
    import workflow_transfer as W
    import dev_stage_timing as TIMING
    import dev_stage_timing_report as REPORT
    timing = name.endswith('-timing')
    if timing:
        name = name[:-len('-timing')]
    # Item 21: 'ordinary-*' advance an adopted ordinary head (interval 1) with base None.
    ordinary = name.startswith('ordinary-')
    seen, phases = {}, []
    budget = FakeBudget()

    def module(module_name, **values):
        result = types.ModuleType(module_name)
        result.__dict__.update(values)
        sys.modules[module_name] = result
        return result

    def seed_flag():
        return '0' if os.environ.get('PYTHONHASHSEED') == '0' and sys.flags.hash_randomization == 0 else 'random'

    def instrumented():
        monitoring = getattr(sys, 'monitoring', None)
        return (sys.gettrace() is not None or sys.getprofile() is not None or
                monitoring is not None and any(monitoring.get_tool(index) is not None for index in range(6)))

    def enclose_differential_ale():
        return 'ale'

    def component_volume_bounds():
        return 'bounds'

    class CollarWorkflow:
        advanced, workflow_id = False, 'wf'
        parent = dict(key='root-key', sequence=1)

        def inspect(self):
            return dict(head='head-key' if self.advanced else self.parent['key'], intervals=2 if self.advanced else 1,
                        funding_id='funding-id')

        @property
        def differential_interval(self):
            return types.SimpleNamespace(interval_id='interval-2' if self.advanced else 'interval-1')

        @property
        def _head(self):
            return dict(key='head-key', sequence=2, differential_geometry=dict(start_time_s=[hex(5), hex(1)],
                        end_time_s=[hex(11), hex(2)])) if self.advanced else dict(self.parent)

        def _r3_after_heat_checkpoint(self):
            pass

        def _publish(self):
            pass

    class EndpointCheckpoints:
        pass

    class InterfaceParallelPolicy:
        def __init__(self, **values):
            self.__dict__.update(values)

    atlas = module('atlas_tectonics', __path__=[])
    module('atlas_tectonics.integration_regional_workflow', CollarWorkflow=CollarWorkflow)
    module('atlas_tectonics.integration_parallel_selection', InterfaceParallelPolicy=InterfaceParallelPolicy)
    module('atlas_tectonics.integration_endpoint_checkpoints', EndpointCheckpoints=EndpointCheckpoints)
    atlas.integration_differential_geometry = G = module('atlas_tectonics.integration_differential_geometry',
        enclose_differential_ale=enclose_differential_ale, component_volume_bounds=component_volume_bounds)
    atlas.integration_parallel_profile = module('atlas_tectonics.integration_parallel_profile',
        seed_flag=seed_flag, instrumented=instrumented)
    assert sha256(OBSERVER.read_bytes()).hexdigest() == OBSERVER_PIN
    spec = importlib.util.spec_from_file_location('private_heat_geometry_observer_r1', OBSERVER)
    observer = importlib.util.module_from_spec(spec)
    sys.modules['private_heat_geometry_observer_r1'] = observer
    spec.loader.exec_module(observer)

    def forbidden_observe(*args, **kwargs):
        raise AssertionError('the always-on observer was used')

    def inspect_preadvance(mesh, graph, bounds, resources, budget_, cancel, artifacts, record, save):
        seen['inspected'] = True
        return dict(cells=8, faces=12)

    module('probe_heat_original_connected_r9', TARGET='target', ADVANCE_OPTIONS=dict(orientation_max_leaves=7),
        snapshots=lambda snapshot: [dict(name='a', shape=[1], dtype='float64', sha256='0'*64)],
        arrays=lambda values: [dict(name='a', shape=[1], dtype='<f8', sha256='0'*64)],
        _Cancel=lambda check: check, observe=forbidden_observe,
        physical_control=types.SimpleNamespace(inspect_preadvance=inspect_preadvance))

    def forward():
        pass

    def low_solve():
        pass

    def reconstruct():
        pass

    def face():
        pass

    def collected():
        pass

    def finish():
        pass

    def project():
        pass

    def package_result():
        pass

    def checkpoint_save():
        pass

    def exterior_finish():
        pass
    functions = types.SimpleNamespace(reconstruct=reconstruct, _face=face,
        PARALLEL=types.SimpleNamespace(completed=collected, report=lambda: dict(first='pass')))
    consumer = module('private_heat_joined_consumer_r6', forward=forward, R='resources', finish=exterior_finish,
        CAS=types.SimpleNamespace(save=checkpoint_save),
        I=types.SimpleNamespace(F=types.SimpleNamespace(LOW=types.SimpleNamespace(solve=low_solve),
            FUNCTIONS=functions, FINISH=types.SimpleNamespace(finish=finish)),
            N=types.SimpleNamespace(project=project),
            HEAT_LEDGER=types.SimpleNamespace(package_result=package_result)))
    module('private_heat_process_meter_r1', record=lambda budget_: dict(peak=1))

    full = dict(component_mass_kg=np.full((2, 3, 3, 3), 2.), enthalpy_j=np.arange(27, dtype='<f8').reshape(3, 3, 3)+1)
    inner = (slice(0, 2),)*3
    state = IW._build(full, slice_array=lambda n, v: v[(slice(None), *inner)] if n == 'component_mass_kg' else v[inner],
        shapes=dict(component_mass_kg=(2, 2, 2, 2), enthalpy_j=(2, 2, 2)), root_key='root-key',
        budget=budget, check=lambda: None)

    class Control:
        def duration(self, case):
            masses = np.sum(case['state'].native_state.array('component_mass_kg'), axis=0)
            return float(np.sum(case['state'].native_state.array('enthalpy_j')/masses))/100
    control = Control()
    module('i04_differential_modes', ACTUATED_CONTROL=control)
    first = control.duration(dict(state=state))

    query_checkpoints = EndpointCheckpoints()
    execution = types.SimpleNamespace(provenance=dict(execution_identity='e'*64, execution_mode='strict'),
                                      verify_boundary=lambda: seen.setdefault('verified', True))
    query_checkpoints._active, query_checkpoints.budget = True, budget
    query_checkpoints.context, query_checkpoints.directory = execution, Path(directory)/'queries'
    allocation = N._Allocation(budget, 4096, category='synthetic-base')
    base = object.__new__(W.MigratedWorkflowBase)
    duration = first*(1+2**-30) if name == 'duration' else first
    object.__setattr__(base, '_endpoint', N._RecordBytes(W.canonical(dict(head=dict(advance=dict(
        duration_s=duration)))), allocation))
    del allocation
    workflow = CollarWorkflow()
    workflow._migration, workflow._budget, workflow._root = base, budget, b'{"key":"root-key"}'
    workflow._store = types.SimpleNamespace(metadata=lambda key: dict(key=key), limits=FakeLimits(),
                                            compression=FakeLimits())
    spatial_owner = types.SimpleNamespace(owner_id='evolved-spatial-owner')
    case = dict(budget=budget, owner=types.SimpleNamespace(owner_id='owner-id'),
        collar=types.SimpleNamespace(_native=types.SimpleNamespace(plan_id='native-plan'), plan_id='collar-plan',
                                     _map=types.SimpleNamespace(volume_map_id='volume-map')),
        funding=types.SimpleNamespace(funding_id='funding-id'))
    if name != 'missing-state':
        case['state'] = state
    if ordinary and name != 'ordinary-frozen-state':
        # A fresh fixture state: the same workload, but not the frozen migrated type.
        case['state'] = types.SimpleNamespace(native_state=state.native_state)
    del state
    lineage = None
    if ordinary:
        head_duration = first*(1+2**-30) if name == 'ordinary-duration' else first
        workflow.parent = dict(key='parent-key', kind='root' if name == 'ordinary-kind' else 'successor',
                               sequence=1.0 if name == 'ordinary-sequence-float' else 1,
                               advance=dict(duration_s=head_duration))
        workflow._migration = base if name == 'ordinary-migration-set' else None
        workflow._root = json.dumps(dict(key='root-key', kind='migrated-root' if name == 'ordinary-root-kind' else
                                         'root'), separators=(',', ':')).encode()
        # One owner condition broken per scenario; each must refuse as a TypeError before any work.
        if name == 'ordinary-workflow-type':
            workflow.__class__ = type('ForeignWorkflow', (CollarWorkflow,), {})
        if name == 'ordinary-workflow-budget':
            workflow._budget = FakeBudget()
        if name == 'ordinary-checkpoint-type':
            query_checkpoints.__class__ = type('ForeignCheckpoints', (EndpointCheckpoints,), {})
        if name == 'ordinary-inactive-checkpoints':
            query_checkpoints._active = False
        if name == 'ordinary-checkpoint-budget':
            query_checkpoints.budget = FakeBudget()
        if name == 'ordinary-checkpoint-context':
            query_checkpoints.context = types.SimpleNamespace()
    if ordinary or name == 'migrated-lineage':
        lineage = dict(schema='atlas.fresh-interval-lineage.v0' if name == 'ordinary-lineage-schema' else LINEAGE_SCHEMA,
                       interval={'ordinary-root-head': 0, 'ordinary-interval-type': True,
                                 'ordinary-sequence': 2}.get(name, 1),
                       workflow_id='other-wf' if name == 'ordinary-workflow-id' else 'wf',
                       root_key='other-root' if name == 'ordinary-root-key' else 'root-key',
                       head_key='other-head' if name == 'ordinary-head-key' else 'parent-key')

    class Operand:
        def __init__(self, raw):
            self._json = raw
    audit = types.SimpleNamespace(result_id='audit', descriptor=lambda: dict(duration_s=first))
    result = types.SimpleNamespace(collar=types.SimpleNamespace(source_stage=types.SimpleNamespace(source_audit=audit)),
        state=types.SimpleNamespace(result_id='collar-result', native_state=types.SimpleNamespace(result_id='native'),
                                    fields='fields', arrays=lambda: {}),
        exterior=types.SimpleNamespace(state=types.SimpleNamespace(state_id='exterior', _snapshot='snapshot'),
            audit_arrays=lambda: {}, _heat=types.SimpleNamespace(result_id='heat', _result=types.SimpleNamespace(
                array=lambda key: np.array([1., 2.])))))

    class Harness:
        pass
    harness = Harness()
    harness.seen = seen

    def advance(arguments, context):
        seen['outside_instrumented'] = instrumented()
        with context.get()():
            seen['inside_instrumented'] = instrumented()
            seen['tool_inside'] = sys.monitoring.get_tool(3)
            G.enclose_differential_ale()
        seen.update(endpoint_checkpoints_forwarded=arguments.get('endpoint_checkpoints') is query_checkpoints,
                    profile_path=arguments['ale_parallel'].profile_path,
                    max_partition_components=arguments['max_partition_components'])
        mesh = Operand(None if name == 'compact-mesh' else b'{}')
        arguments['before_advance'](types.SimpleNamespace(source_stage=types.SimpleNamespace(source_audit=audit)),
                                    Operand(b'{}'), mesh, types.SimpleNamespace(graph=Operand(b'{}')))
        workflow.advanced = True
        # The commit window in item 11's stage order, run on both routes: projection,
        # packaging, checkpoint save, R3 checks, exterior finish, publication.
        project()
        package_result()
        checkpoint_save()
        workflow._r3_after_heat_checkpoint()
        exterior_finish()
        workflow._publish()
        arguments['completed_observer'](result)
        return dict(report='synthetic'), dict(restored='synthetic')
    harness.advance = advance
    # The ordinary route never has r6 registered, so a stray import of it would show.
    r8 = ordinary and name not in ('ordinary-joined-r6', 'ordinary-neither')
    joined_name = 'private_heat_original_joined_r8' if r8 else 'private_heat_original_joined_r6'
    joined = types.ModuleType(joined_name)
    joined.HARNESS = harness
    parameter = '' if name.endswith('no-checkpoint-parameter') else 'endpoint_checkpoints=None,'
    exec(compile(JOINED.replace('ENDPOINT_PARAMETER', parameter), '<synthetic-joined>', 'exec'), joined.__dict__)
    if name != 'ordinary-joined-unregistered':
        sys.modules[joined_name] = joined

    def continuation_pressure_force(test, case_, workflow_, second, *, force_control, pressure_max_leaves,
                                    current_trace_max_leaves):
        seen.update(continuation_called=True, ceilings=[pressure_max_leaves, current_trace_max_leaves],
                    tool_in_continuation=sys.monitoring.get_tool(3))
        return second('driver', 'pressure', 'datum', 'current', 'partition', 'prior', 'network', 'state',
                      'spatial', spatial_owner, dict(provenance='synthetic'))
    module('private_heat_original_continuation_r1', continuation_pressure_force=continuation_pressure_force,
           derivation=lambda: dict(schema='synthetic-continuation', changes=['stand-in']))

    class Guard:
        counts = {}

        def phase(self, phase):
            phases.append(phase)

        def check(self, force=False):
            return False
    if name == 'foreign-tool':
        sys.monitoring.use_tool_id(0, 'foreign-debugger')
    record, error = {}, None
    import prepared_interval_driver as P
    import fresh_interval_driver as FD
    guard = Guard()
    guard.budget = budget
    extra = {}
    if ordinary or name == 'migrated-joined-module':
        extra['joined_module'] = joined
    if lineage is not None and name != 'ordinary-neither':
        extra['lineage'] = lineage
    try:
        with TIMING.collect(guard, directory, enabled=timing, record=record):
            P.advance_prepared_interval(case=case, workflow=workflow, base=None if ordinary else base,
                execution=execution, guard=guard, record=record, save=lambda: json.dumps(record, default=repr),
                artifacts=Path(directory), query_checkpoints=query_checkpoints, **extra)
    except Exception as caught:
        error = dict(type=type(caught).__name__, message=str(caught))
    if name == 'foreign-tool':
        sys.monitoring.free_tool_id(0)
    seen['r6_loaded'] = 'private_heat_original_joined_r6' in sys.modules
    seen['fd_commit_names'] = [stage for _, stage in
                               FD._commit_stages(types.SimpleNamespace(J=consumer, Workflow=CollarWorkflow))]
    summary = dict(error=error, seen=seen, phases=phases, tool3_after=sys.monitoring.get_tool(3),
        record=json.loads(json.dumps(record, default=repr)))
    if timing:
        summary['timing_report'] = REPORT.build_report(Path(directory)/TIMING.FILENAME)
    # Release every stand-in that could still own a charged buffer.
    for module_name in ('private_heat_original_joined_r6', 'private_heat_original_joined_r8',
                        'private_heat_original_continuation_r1'):
        sys.modules.pop(module_name, None)
    case = base = workflow = query_checkpoints = record = result = harness = joined = extra = lineage = None
    gc.collect()
    summary['reserved_after'] = budget.reserved_bytes
    print(json.dumps(summary, default=repr), flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--scenario':
        scenario_main(sys.argv[2], sys.argv[3])
    else:
        unittest.main(verbosity=2)
