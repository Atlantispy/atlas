"""Driver controls: source shape plus the actual driver over synthetic modules.

The functional scenarios run prepared_interval_driver.advance_prepared_interval
in a fresh interpreter with the REAL hook-free geometry observer (frozen I
helper bytes) and the real sys.monitoring slots. Native, joined, continuation
and heat modules are explicit stand-ins: no physics, store or acceptance. The
composed import-closure and real-owner checks belong to the composed wave.
"""
import ast
from dataclasses import dataclass
from hashlib import sha256
import gc
import importlib.util
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

        def inspect(self):
            return dict(head='head-key' if self.advanced else 'root-key', intervals=2 if self.advanced else 1,
                        funding_id='funding-id')

        @property
        def differential_interval(self):
            return types.SimpleNamespace(interval_id='interval-2' if self.advanced else 'interval-1')

        @property
        def _head(self):
            return dict(key='head-key', sequence=2, differential_geometry=dict(start_time_s=[hex(5), hex(1)],
                        end_time_s=[hex(11), hex(2)])) if self.advanced else dict(key='root-key', sequence=1)

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
    functions = types.SimpleNamespace(reconstruct=reconstruct, _face=face,
        PARALLEL=types.SimpleNamespace(completed=collected, report=lambda: dict(first='pass')))
    module('private_heat_joined_consumer_r6', forward=forward, R='resources',
        I=types.SimpleNamespace(F=types.SimpleNamespace(LOW=types.SimpleNamespace(solve=low_solve),
            FUNCTIONS=functions, FINISH=types.SimpleNamespace(finish=finish)),
            N=types.SimpleNamespace(project=project)))
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
    del state

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
        arguments['completed_observer'](result)
        return dict(report='synthetic'), dict(restored='synthetic')
    harness.advance = advance
    joined = types.ModuleType('private_heat_original_joined_r6')
    joined.HARNESS = harness
    parameter = '' if name == 'no-checkpoint-parameter' else 'endpoint_checkpoints=None,'
    exec(compile(JOINED.replace('ENDPOINT_PARAMETER', parameter), '<synthetic-joined>', 'exec'), joined.__dict__)
    sys.modules['private_heat_original_joined_r6'] = joined

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
    guard = Guard()
    guard.budget = budget
    try:
        with TIMING.collect(guard, directory, enabled=timing, record=record):
            P.advance_prepared_interval(case=case, workflow=workflow, base=base, execution=execution, guard=guard,
                record=record, save=lambda: json.dumps(record, default=repr), artifacts=Path(directory),
                query_checkpoints=query_checkpoints)
    except Exception as caught:
        error = dict(type=type(caught).__name__, message=str(caught))
    if name == 'foreign-tool':
        sys.monitoring.free_tool_id(0)
    summary = dict(error=error, seen=seen, phases=phases, tool3_after=sys.monitoring.get_tool(3),
        record=json.loads(json.dumps(record, default=repr)))
    if timing:
        summary['timing_report'] = REPORT.build_report(Path(directory)/TIMING.FILENAME)
    # Release every stand-in that could still own a charged buffer.
    for module_name in ('private_heat_original_joined_r6', 'private_heat_original_continuation_r1'):
        sys.modules.pop(module_name)
    case = base = workflow = query_checkpoints = record = result = harness = joined = None
    gc.collect()
    summary['reserved_after'] = budget.reserved_bytes
    print(json.dumps(summary, default=repr), flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--scenario':
        scenario_main(sys.argv[2], sys.argv[3])
    else:
        unittest.main(verbosity=2)
