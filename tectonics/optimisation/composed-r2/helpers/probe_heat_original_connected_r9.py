"""Native-r7 first interval, pinned R8 science under the external job guard.

Select the new normal-open runtime, preserve the original physical declarations,
run actual geometry/transport/composed heat, and export the committed endpoint.
A separate fresh-process consumer must pass before joined recovery is claimed.
The 16 GiB ledger ceiling is NOT allocated RAM. Actual process-tree RSS and free
RAM are checked cooperatively; the logical and measured peaks remain separate.
"""
import argparse
from concurrent.futures import CancelledError
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from dataclasses import asdict
from fractions import Fraction as Q
import gc
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import monotonic
import traceback
import unittest

import psutil
import private_heat_original_coverage_r3 as physical_control

HERE = Path(__file__).resolve().parent
TARGET = '4.9171027966256209779674411407088268288935981282609672659484679021446505633744583E-40'
LOGICAL_BYTES, RSS_BYTES = 16 << 30, 12 << 30
FREE_FLOOR, START_AVAILABLE = 1 << 30, 13 << 30
POLICY = dict(initial_relative_error=Q(1, 1000), max_initial_width_m3=Q(32000),
    max_relative_material_error=Q(1, 100), max_l1_material_error_m3=Q(32),
    max_relative_rebase=Q(1, 1000), max_l1_rebase_m3=Q(1))
ADVANCE_OPTIONS = dict(orientation_max_leaves=2**19, native_directed_max_leaves=2**19,
    native_mask_max_leaves=2**19, ale_max_leaves=2**19, final_trace_max_leaves=2**19,
    thermal_max_leaves=2**19, thermal_witness_refinements=32)


def file_hash(path):
    with Path(path).open('rb') as stream:
        from hashlib import file_digest
        return file_digest(stream, 'sha256').hexdigest()


def snapshots(snapshot):
    return [dict(name=name, shape=list(shape), dtype='float64', sha256=sha256(raw).hexdigest())
            for name, shape, raw in snapshot._fields]


def arrays(values):
    return [dict(name=name, shape=list(value.shape), dtype=value.dtype.str,
                 sha256=sha256(value.tobytes(order='C')).hexdigest()) for name, value in values.items()]


class _Cancel:
    # The guard as the workflow's cancel value, in both forms native stages ask for:
    # called, or asked is_set(). Either way it runs the guard's own check.
    __slots__ = ('_check',)

    def __init__(self, check):
        self._check = check

    def __call__(self):
        return self._check()

    def is_set(self):
        return bool(self._check())




@contextmanager
def observe(guard, stages, ticks):
    """Local CPython events only: observe original calls, never replace them."""
    monitoring, tool = sys.monitoring, 3
    if monitoring.get_tool(tool) is not None:
        raise RuntimeError('Local monitoring slot already occupied')
    monitoring.use_tool_id(tool, 'private-original-heat-control')
    started = {fn.__code__: name for fn, name in stages}
    returned = {fn.__code__: name for fn, name in ticks}
    codes = set(started) | set(returned)
    def on_start(code, offset):
        guard.phase(started[code])
    def on_return(code, offset, value):
        name = returned[code]
        guard.counts[name] = guard.counts.get(name, 0)+1
        guard.check()
    try:
        monitoring.register_callback(tool, monitoring.events.PY_START, on_start)
        monitoring.register_callback(tool, monitoring.events.PY_RETURN, on_return)
        for code in codes:
            events = (monitoring.events.PY_START if code in started else 0)
            events |= (monitoring.events.PY_RETURN if code in returned else 0)
            monitoring.set_local_events(tool, code, events)
        yield
    finally:
        for code in codes:
            monitoring.set_local_events(tool, code, 0)
        monitoring.register_callback(tool, monitoring.events.PY_START, None)
        monitoring.register_callback(tool, monitoring.events.PY_RETURN, None)
        monitoring.free_tool_id(tool)


def imported_sources():
    found = {}
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.suffix == '.py' and path.is_relative_to(HERE):
                found[str(path.relative_to(HERE)).replace('\\', '/')] = file_hash(path)
    # Case data are physical inputs, not merely executable source.
    for path in sorted((HERE/'source/tectonics/cases').glob('*.json')):
        found[str(path.relative_to(HERE)).replace('\\', '/')] = file_hash(path)
    found[Path(__file__).name] = file_hash(__file__)
    parent_name = 'probe_heat_original_connected_r2.py'
    parent_pin = 'a3844caaa2467804f99318df8fac3e0e14c7f3bfc78b1a182dfe3624c80e72e8'
    if file_hash(HERE/parent_name) != parent_pin:
        raise ValueError('Preserved R2 driver changed during execution')
    found[parent_name] = parent_pin
    if file_hash(HERE/DRIVER_DERIVATION['base']) != DRIVER_DERIVATION['base_sha256']:
        raise ValueError('Preserved driver changed during derivative execution')
    found[DRIVER_DERIVATION['base']] = DRIVER_DERIVATION['base_sha256']
    return found


def run(record, artifacts, guard, save):
    # Import the real fresh reader before expensive work or publication.
    from probe_heat_original_reopen_r4 import consume as _reader
    if not callable(_reader):
        raise TypeError("Fresh reader is not callable")
    import private_heat_native_successor_r6 as S
    _, _, J, Workflow = S.modules()
    import private_heat_original_spatial_r1 as spatial
    import private_heat_original_joined_r5 as joined
    from i04_differential_fixture import radial_differential_fixture
    from i04_differential_modes import ACTUATED_CONTROL
    from test_i04_differential_force import check_initial_pressure_force
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
    from atlas_tectonics.integration_parallel_selection import InterfaceParallelPolicy
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics.integration_dual_geometry import cached_initial_component
    from threadpoolctl import threadpool_limits

    require_strict_execution()
    proof = S.verify()
    record.update(native_source_digest=proof['clone_source_digest'], native_source=proof,
                  fixture_derivations=dict(spatial=spatial.derivation(), joined=joined.derivation()),
                  consumer_sources=J.source_bindings(), participating_imported_helper_sources=imported_sources())
    save()
    guard.budget = budget = WorkBudget(LOGICAL_BYTES, max_predicate_work_units=1 << 44)
    limits = StoreLimits(chunk_bytes=65536, max_array_bytes=512 << 20, max_store_bytes=4 << 30,
        max_staging_bytes=1 << 30)
    compression = Compression(codec='raw')
    cache_limits = StoreLimits(chunk_bytes=65536, max_array_bytes=1 << 20, max_store_bytes=128 << 20)
    test = unittest.TestCase()
    stages = [(G.enclose_differential_ale, 'actual-differential-geometry'),
        (J.forward, 'actual-composed-heat-forward'), (J.I.F.LOW.solve, 'heat-low-predictor'),
        (J.I.F.FUNCTIONS.reconstruct, 'heat-certified-polygon-reconstruction'),
        (J.I.F.FINISH.finish, 'heat-conservative-finish'), (J.I.N.project, 'heat-native-projection')]
    ticks = [(cached_initial_component, 'initial_components'),
             (G.component_volume_bounds, 'component_volume_queries'),
             (J.I.F.FUNCTIONS._face, 'heat_faces'),
             (J.I.F.FUNCTIONS.PARALLEL.completed, 'heat_faces_collected')]
    record['initial_measurement_cache'] = dict(copied=False, native_hit_verification_unchanged=True,
        reason='retained cache carries the native-composed-r2 execution identity; no lookup here can hit it')
    record['json_view_policy'] = dict(policy=J.R.select_policy(), runtime_probe=dict(J.R.RUNTIME))
    from threadpoolctl import threadpool_info
    record['thread_pools'] = dict(openblas_num_threads=os.environ.get('OPENBLAS_NUM_THREADS'),
        pools=[dict(library=pool.get('internal_api'), threads=pool.get('num_threads'),
                    version=pool.get('version')) for pool in threadpool_info()])
    guard.phase('begin-original-native-admission')
    with observe(guard, stages, ticks), threadpool_limits(1), \
            ExecutionContext('reference') as reference_execution, ExecutionContext('scipy') as heat_execution, \
            ArrayStore(artifacts/'initial-measurements.sqlite', cache_limits, compression, budget=budget) as cache, \
            radial_differential_fixture(budget=budget, pressure_space='q1-p0', material_quadrature=True) as case:
        current, partition = spatial.initial_partition(case, max_components=4096)
        guard.phase('initial-physical-and-thermal-metrics')
        bounds, mesh = spatial.initial_metrics(case, partition, physical_volume_error_m3=Q(32000),
            thermal_volume_error_m3=Q(32000), max_leaves=2**30, max_witness_refinements=32,
            measure_policy=POLICY, measurement_store=cache, measurement_context=reference_execution)
        with spatial.initial_spatial_owner(case, partition, bounds, mesh,
                created_tracers=('tracer:accumulated_strain_ii',), measure_policy=POLICY,
                heat_method=J.METHOD) as owner:
            def prepared(driver, pressure, datum, **extra):
                guard.phase('prepare-actual-force-selected-interval')
                with ArrayStore(artifacts/'native-joined.sqlite', limits, compression, budget=budget) as store, \
                        Workflow.create(store, case['collar'], case['owner'], case['funding'], budget=budget,
                            exterior_owner=owner, differential_partition=partition, current_geometry=current) as workflow:
                    def before_advance(source, end_bounds, end_mesh, solution):
                        coverage = physical_control.inspect_preadvance(end_mesh, solution.graph,
                            end_bounds, J.R, budget, guard.check, artifacts, record, save)
                        count, faces = coverage['cells'], coverage['faces']
                        dt = source.source_stage.source_audit.descriptor()['duration_s']
                        if dt != ACTUATED_CONTROL.duration(case):
                            raise ValueError('Original force-selected duration changed')
                        record['preheat_gate'] = dict(cells=count, faces=faces, duration_s=dt, coverage=coverage,
                            absolute_residual_target=TARGET, uniform_conductivity_w_m_k=.1,
                            boundary='zero prescribed power on every declared boundary face',
                            geometry_scope='original coarse construction contract; not arbitrary-mesh accuracy')
                        guard.phase('current-physical-coverage-confirmed-before-advance')

                    def completed(result):
                        root_key = json.loads(workflow._root)['key']
                        audit = result.collar.source_stage.source_audit
                        record['completed_endpoint'] = dict(workflow_id=workflow.workflow_id,
                            root_key=root_key, root_metadata=store.metadata(root_key), head_key=workflow._head['key'],
                            producer_pid=os.getpid(), store_limits=asdict(limits), store_compression=asdict(compression),
                            collar_result_id=result.state.result_id, native_result_id=result.state.native_state.result_id,
                            exterior_state_id=result.exterior.state.state_id, source_audit_id=audit.result_id,
                            joined_heat_id=result.exterior._heat.result_id,
                            array_records=dict(collar=snapshots(result.state.fields), native=snapshots(result.state.native_state),
                                exterior=snapshots(result.exterior.state._snapshot), source_audit=snapshots(audit),
                                full_collar=arrays(result.state.arrays()), spatial_audit=arrays(result.exterior.audit_arrays())),
                            preparation_ids=dict(owner=case['owner'].owner_id, spatial_owner=owner.owner_id,
                                native=case['collar']._native.plan_id, collar=case['collar'].plan_id,
                                map=case['collar']._map.volume_map_id, funding=case['funding'].funding_id),
                            execution_provenance=heat_execution.provenance)
                        temperatures = result.exterior._heat._result.array('temperature_k')
                        record['public_temperature_k'] = dict(minimum=float(temperatures.min()), maximum=float(temperatures.max()),
                            count=int(temperatures.size), array_sha256=sha256(temperatures.tobytes()).hexdigest())
                        guard.phase('actual-heat-endpoint-committed')

                    report, restored = joined._advance_current_interval(test, case, workflow, current=current,
                        parent=partition, owner=owner, driver=driver, pressure=pressure, datum=datum,
                        network=case['source'][0].network, force_control=ACTUATED_CONTROL,
                        heat_execution=heat_execution, absolute_heat_residual_target=TARGET, cancel=_Cancel(guard.check),
                        before_advance=before_advance, completed_observer=completed,
                        ale_parallel=InterfaceParallelPolicy(mode='auto', workers=2,
                            profile_path=str(artifacts/'parallel-profile.json')), **ADVANCE_OPTIONS, **extra)
                    record['joined_global_and_created_tracer_controls'] = report
                    joined._check_reopened(test, workflow, restored)
                    save()
                    del restored
                return report
            check_initial_pressure_force(test, case, current, partition, owner.initial_state,
                force_control=ACTUATED_CONTROL, pressure_max_leaves=2**19,
                initial_trace_max_leaves=2**19, prepared_control=prepared)
        reference_execution.verify_boundary()
        heat_execution.verify_boundary()
    if S.verify() != proof:
        raise ValueError('Native source changed during the original workflow')
    for name, pin in record['participating_imported_helper_sources'].items():
        if file_hash(HERE/name) != pin:
            raise ValueError('Participating helper/input changed: '+name)
    record['participating_sources_unchanged'] = True
    record['database_sha256'] = file_hash(artifacts/'native-joined.sqlite')
    return budget






DRIVER_DERIVATION = {'base': 'probe_heat_original_connected_r1.py', 'base_sha256': 'eb968a3f7bfb9ee8b957a758a645a1e6e2f2b3982f73bae92d5439885f2e2b1c', 'derived_text_sha256': '872d91701d3b3e7aa672b1041a7ff75bfff1e3b8c6c32bd663e8d99025478a87', 'harness_parent': {'path': 'probe_heat_original_connected_r2.py', 'sha256': 'a3844caaa2467804f99318df8fac3e0e14c7f3bfc78b1a182dfe3624c80e72e8'}, 'changes': ['import-physical-control', 'derive-coverage-from-closed-material', 'explicit-historical-fingerprint', 'name-current-coverage', 'name-current-fixture-scope', 'retain-original-driver-source-pin', 'sequential-funded-coverage-production-facade', 'failure-capture-does-not-retain-active-caller', 'resources-r4-runtime-clone', 'resources-r4-joined-harness', 'cache-of-another-runtime-identity-not-copied-and-json-policy-recorded', 'retain-intermediate-driver-source-pin', 'record-thread-pools-at-start', 'memory-by-stage-table', 'memory-by-stage-sample', 'record-forward-memory-and-first-pass', 'cancel-value-callable-and-event', 'cancel-value-given-to-the-workflow', 'count-faces-collected-from-workers'], 'physical_inputs_or_tolerances_changed': False, 'historical855_count_gate': 'replaced with native-contract exact positive-material coverage; historical equality not claimed', 'successor': 'native-r7 exact co-moving pressure proof; externally guarded lifecycle'}

def main():
    from private_heat_continuation_support_r3 import execute_cli
    return execute_cli(run, __file__, schema='atlas.private.heat-original-connected.r1',
        success='PASS_FORWARD_PENDING_REOPEN', kind='first')


if __name__ == '__main__':
    raise SystemExit(main())
