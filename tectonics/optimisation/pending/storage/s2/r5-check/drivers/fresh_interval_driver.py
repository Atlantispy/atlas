"""Route (1) fresh start: interval 1 of a new lineage on a compact store.

The actual r9 interval-1 flow (heat-repair-20261007/probe_heat_original_connected_r9.py,
run(), lines 153-240), split at the root so that the independent fresh-process
reader runs between the root interval and interval 1 (Step 9(a)):

- create_root (run A): funded fixture -> initial partition and metrics -> spatial
  owner -> Workflow.create on the compact store (sequence 0). The root does not
  depend on the initial pressure/force check, so that check is not computed here.
- advance_first_interval (run B): the same deterministic admission, then the
  initial pressure/force check, whose prepared control opens the sealed root
  (CollarWorkflow.open compares every root field with this admission, including
  the live spatial owner's definition and initial state) and advances interval 1
  through the composed joined helper with its completed-query owner. The
  runner's ``finish`` callback runs inside that control, while the workflow is
  open (successor checks, bounded pre-seal checks, seal).

Every physical input, control, work ceiling and tolerance is r9's: the literals
below are checked against r9's source by test_fresh_interval_driver. The
observer, selector gate and compact-aware coverage gate are the current
composition's (prepared_interval_driver), as for the migrated lineage. Nothing
here seals, promotes or reads back; the runner owns the store protocol.
"""
import json
import os
import unittest
from contextlib import contextmanager
from dataclasses import asdict
from fractions import Fraction as Q
from hashlib import sha256
from types import SimpleNamespace

# r9's admission and work ceilings, verbatim (probe_heat_original_connected_r9.py run()).
FIXTURE = {'pressure_space': 'q1-p0', 'material_quadrature': True}
MEASUREMENT_CACHE = {'chunk_bytes': 65536, 'max_array_bytes': 1 << 20, 'max_store_bytes': 128 << 20}
MEASUREMENT_CODEC = 'raw'
INITIAL_PARTITION = {'max_components': 4096}
INITIAL_METRICS = {'physical_volume_error_m3': Q(32000), 'thermal_volume_error_m3': Q(32000),
                   'max_leaves': 2**30, 'max_witness_refinements': 32}
CREATED_TRACERS = ('tracer:accumulated_strain_ii',)
PRESSURE_FORCE = {'pressure_max_leaves': 2**19, 'initial_trace_max_leaves': 2**19}
PARALLEL = {'mode': 'auto', 'workers': 2}


class FreshIntervalRefused(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise FreshIntervalRefused(message)


def _seed_pinned():
    # RC1 iterates sets in places (exact_start_zero), so work units and the
    # records carrying them differ between processes unless the hash seed is
    # fixed. Production pins 0; runs A and B must both start with it.
    import sys
    _require(sys.flags.hash_randomization == 0 and os.environ.get('PYTHONHASHSEED') == '0',
             'fresh-start runs require an interpreter started with PYTHONHASHSEED=0')


# The fields of run A's published root that run B's re-derived admission must reproduce.
ROOT_IDENTITY = ('workflow_id', 'root_key', 'kind', 'sequence', 'root_metadata_sha256',
                 'execution_provenance', 'preparation_ids')


def preparation_ids(case, owner):
    """The plan and owner identities a fresh reader rebuilds and must compare."""
    collar = case['collar']
    return {'owner': case['owner'].owner_id, 'spatial_owner': owner.owner_id, 'native': collar._native.plan_id,
            'collar': collar.plan_id, 'map': collar._map.volume_map_id, 'funding': case['funding'].funding_id}


def admission(m, *, budget, artifacts, phase, measurements=None):
    """r9's deterministic admission with r9's execution contexts and measurement cache open.

    A plain function returning the context manager, not a decorated one: the loaded-source
    fence compares each module-level function's loaded code with the pinned source, and a
    decorated function's loaded code is the decorator's wrapper.

    ``measurements`` (item 7, coordinator approval 16 Oct 2026) observes only: when given, it
    is called once, right after the initial metrics (the store's only use), with the
    measurement store's own statistics() and the initial bounds. The producer runner records
    the snapshot count and the initial component queries the bounds carry, which give its cache
    hits and misses; the independent reader never passes it. The store's path and contents
    are this function's alone: a seeded store is the runner's copy, made before this
    admission begins.
    """
    return contextmanager(_admission)(m, budget=budget, artifacts=artifacts, phase=phase, measurements=measurements)


def _admission(m, *, budget, artifacts, phase, measurements=None):
    phase('begin-fresh-native-admission')
    with m.ExecutionContext('reference') as reference_execution, \
            m.ExecutionContext('scipy') as heat_execution, \
            m.ArrayStore(artifacts/'initial-measurements.sqlite', m.StoreLimits(**MEASUREMENT_CACHE),
                         m.Compression(codec=MEASUREMENT_CODEC), budget=budget) as cache, \
            m.radial_differential_fixture(budget=budget, **FIXTURE) as case:
        current, partition = m.spatial.initial_partition(case, **INITIAL_PARTITION)
        phase('initial-physical-and-thermal-metrics')
        bounds, mesh = m.spatial.initial_metrics(case, partition, **INITIAL_METRICS, measure_policy=m.D.POLICY,
            measurement_store=cache, measurement_context=reference_execution)
        if measurements is not None:
            measurements(cache.statistics(), bounds)
        with m.spatial.initial_spatial_owner(case, partition, bounds, mesh, created_tracers=CREATED_TRACERS,
                measure_policy=m.D.POLICY, heat_method=m.J.METHOD) as owner:
            yield SimpleNamespace(case=case, current=current, partition=partition, owner=owner,
                                  reference_execution=reference_execution, heat_execution=heat_execution)
        reference_execution.verify_boundary()
        heat_execution.verify_boundary()


def published_root(workflow, store, a):
    """The root identity a fresh reader must reproduce (recorded by run A)."""
    root = json.loads(workflow._root)
    metadata = store.metadata(root['key'])
    _require(metadata == root, 'published fresh root differs from its stored metadata')
    return {'workflow_id': workflow.workflow_id, 'root_key': root['key'], 'kind': root['kind'],
            'sequence': root['sequence'], 'inspect': workflow.inspect(), 'producer_pid': os.getpid(),
            'root_metadata_sha256': sha256(json.dumps(root, sort_keys=True, separators=(',', ':'),
                                                      allow_nan=False).encode()).hexdigest(),
            'store_limits': asdict(store.limits), 'store_compression': asdict(store.compression),
            'execution_provenance': a.heat_execution.provenance,
            'preparation_ids': preparation_ids(a.case, a.owner)}


def create_root(m, *, open_store, budget, artifacts, phase, finish_root, measurements=None):
    """Run A: admit and create the sequence-0 root on a fresh compact store; nothing advances.

    RC1 derives a fresh root's workflow ID from the collar plan, the funding and
    the exterior owner (CollarWorkflow._identity and _exterior_inputs), so the
    store's catalog is created under that ID, by ``open_store(workflow_id)``,
    before the root exists, and the created root must carry it.
    ``finish_root(workflow, store, root)`` is the runner's protocol (durable
    runner record, then the Step 9(a) seal), called with the workflow open.
    ``measurements``: see admission.
    """
    _seed_pinned()
    with admission(m, budget=budget, artifacts=artifacts, phase=phase, measurements=measurements) as a:
        collar, funding = a.case['collar'], a.case['funding']
        workflow_id = m.Workflow._identity(collar, funding,
                                           m.Workflow._exterior_inputs(a.owner, collar, funding, budget))
        phase('create-fresh-root')
        with open_store(workflow_id) as store, m.Workflow.create(store, collar, a.case['owner'], funding,
                budget=budget, exterior_owner=a.owner, differential_partition=a.partition,
                current_geometry=a.current) as workflow:
            _require(workflow.workflow_id == workflow_id and workflow.inspect()['intervals'] == 0,
                     'a fresh root must be sequence zero under the admission workflow ID')
            return finish_root(workflow, store, published_root(workflow, store, a))


def reopen_root(m, *, store, expected_root, budget, artifacts, phase, measurements=None):
    """Run B up to the advance (stop-before-advance smoke): the same admission, then the adopted root.

    CollarWorkflow.open compares every root field with this admission; every
    ROOT_IDENTITY field of the reopened root must equal run A's. Nothing advances,
    no pressure or force check runs and nothing is written. ``measurements``: see admission.
    """
    _seed_pinned()
    with admission(m, budget=budget, artifacts=artifacts, phase=phase, measurements=measurements) as a:
        phase('reopen-adopted-fresh-root')
        with m.Workflow.open(store, expected_root['workflow_id'], a.case['collar'], a.case['owner'],
                             a.case['funding'], budget=budget, exterior_owner=a.owner) as workflow:
            before = workflow.inspect()
            _require(before['intervals'] == 0 and workflow._head['kind'] == 'root',
                     'run B must open the adopted sequence-0 fresh root')
            found = published_root(workflow, store, a)
            differing = [name for name in ROOT_IDENTITY if found[name] != expected_root[name]]
            _require(not differing, 'run B re-derived admission differs from run A sealed root: '
                     + ', '.join(differing))
            return {**{name: found[name] for name in ROOT_IDENTITY}, 'inspect': before}


def advance_first_interval(m, *, store, expected_root, budget, artifacts, phase, guard, record, save,
                           query_checkpoints, finish, measurements=None):
    """Run B: the same admission, then open the sealed root and advance interval 1 once.

    ``expected_root`` is run A's published root record. Run B re-derives the
    admission, and refuses before advancing unless CollarWorkflow.open accepts
    it against the stored root and every ROOT_IDENTITY field of the reopened
    root equals run A's. ``query_checkpoints(execution)`` returns the
    completed-query owner bound to the heat execution context;
    ``finish(workflow, before=, after=, parent=, root_bytes=)`` is the runner's
    post-advance protocol, called with the workflow still open; ``parent`` (the
    head metadata) and ``root_bytes`` are captured before the advance, so the
    runner's successor checks compare against state the advance could not touch.
    ``measurements``: see admission.
    """
    from compact_restart_patch import require_capture_route
    require_capture_route(store)
    _seed_pinned()
    stages = _stages(m)
    record['observed_stages'] = [name for _, name in stages]
    with admission(m, budget=budget, artifacts=artifacts, phase=phase, measurements=measurements) as a, \
            m.geometry_observer.observe(guard, stages, _ticks(m), joined=m.joined,
                                        geometry=m.G.enclose_differential_ale), \
            m.threadpool_limits(1), query_checkpoints(a.heat_execution) as checkpoints:
        record['selector_gate_before_advance'] = m.prepared_interval_driver.selector_gate(m.PF)
        save()
        test = unittest.TestCase()

        def prepared(driver, pressure, datum, **extra):
            phase('prepare-actual-force-selected-interval')
            with m.Workflow.open(store, expected_root['workflow_id'], a.case['collar'], a.case['owner'],
                                 a.case['funding'], budget=budget, exterior_owner=a.owner) as workflow:
                before = workflow.inspect()
                _require(before['intervals'] == 0 and workflow._head['kind'] == 'root',
                         'run B must open the sealed sequence-0 fresh root')
                found = published_root(workflow, store, a)
                differing = [name for name in ROOT_IDENTITY if found[name] != expected_root[name]]
                _require(not differing, 'run B re-derived admission differs from run A sealed root: '
                         + ', '.join(differing))
                record['root_reproduced'] = {name: found[name] for name in ROOT_IDENTITY}
                parent, root_bytes = dict(workflow._head), workflow._root
                report, restored = m.joined._advance_current_interval(test, a.case, workflow,
                    current=a.current, parent=a.partition, owner=a.owner, driver=driver, pressure=pressure,
                    datum=datum, network=a.case['source'][0].network, force_control=m.ACTUATED_CONTROL,
                    heat_execution=a.heat_execution, absolute_heat_residual_target=m.D.TARGET,
                    cancel=m.D._Cancel(guard.check),
                    before_advance=_before_advance(m, a, guard, artifacts, record, save, phase),
                    completed_observer=_completed(m, a, workflow, record, phase),
                    endpoint_checkpoints=checkpoints,
                    ale_parallel=m.InterfaceParallelPolicy(**PARALLEL,
                        profile_path=str(artifacts/'parallel-profile.json')),
                    **m.D.ADVANCE_OPTIONS, **extra)
                record['joined_global_and_created_tracer_controls'] = report
                m.joined._check_reopened(test, workflow, restored)
                del restored
                after = workflow.inspect()
                _require(after['intervals'] == 1 and after['funding_id'] == before['funding_id'] and
                         after['head'] != before['head'] and workflow._root == root_bytes,
                         'interval 1 did not advance exactly once')
                save()
                return finish(workflow, before=before, after=after, parent=parent, root_bytes=root_bytes)

        return m.check_initial_pressure_force(test, a.case, a.current, a.partition, a.owner.initial_state,
            force_control=m.ACTUATED_CONTROL, **PRESSURE_FORCE, prepared_control=prepared)


def _stages(m):
    return [(m.G.enclose_differential_ale, 'actual-differential-geometry'),
            (m.J.forward, 'actual-composed-heat-forward'), (m.J.I.F.LOW.solve, 'heat-low-predictor'),
            (m.J.I.F.FUNCTIONS.reconstruct, 'heat-certified-polygon-reconstruction'),
            (m.J.I.F.FINISH.finish, 'heat-conservative-finish'), (m.J.I.N.project, 'heat-native-projection'),
            *_commit_stages(m)]


def _commit_stages(m):
    # Item 11 (coordinator, 16 Oct 2026; calls named by the pressure-stage thread): r9's IV1 log has
    # no marker between the projection's start and the committed endpoint (278.9 s). These calls run
    # once per interval, in this order, inside that window, so each later phase splits it. Observation
    # only: one phase write at each call's start, before any of its work. _r3_after_heat_checkpoint
    # exists only in a runtime built with the R3 heat-token transform; the run records the names observed.
    stages = [(m.J.I.HEAT_LEDGER.package_result, 'heat-result-packaging'),
              (m.J.CAS.save, 'heat-checkpoint-save')]
    if callable(getattr(m.Workflow, '_r3_after_heat_checkpoint', None)):
        stages.append((m.Workflow._r3_after_heat_checkpoint, 'heat-checkpoint-r3-checks'))
    return stages + [(m.J.finish, 'heat-exterior-finish'), (m.Workflow._publish, 'endpoint-store-publish')]


def _ticks(m):
    return [(m.G.component_volume_bounds, 'component_volume_queries'),
            (m.J.I.F.FUNCTIONS._face, 'heat_faces'),
            (m.J.I.F.FUNCTIONS.PARALLEL.completed, 'heat_faces_collected')]


def _before_advance(m, a, guard, artifacts, record, save, phase):
    budget = a.case['budget']

    def before_advance(source, end_bounds, end_mesh, solution):
        for label, operand in (('closed graph', solution.graph), ('end bounds', end_bounds)):
            _require(getattr(operand, '_json', None) is not None,
                     'pre-advance coverage gate needs the legacy '+label+' record')
        if getattr(end_mesh, 'is_compact', False):
            from compact_restart_patch import inspect_compact_preadvance
            coverage = inspect_compact_preadvance(m.D.physical_control, end_mesh, solution.graph,
                end_bounds, m.J.R, budget, guard.check, artifacts, record, save)
        else:
            coverage = m.D.physical_control.inspect_preadvance(end_mesh, solution.graph,
                end_bounds, m.J.R, budget, guard.check, artifacts, record, save)
        duration = source.source_stage.source_audit.descriptor()['duration_s']
        _require(duration == m.ACTUATED_CONTROL.duration(a.case), 'Original force-selected duration changed')
        record['preheat_gate'] = {'cells': coverage['cells'], 'faces': coverage['faces'], 'duration_s': duration,
            'coverage': coverage, 'absolute_residual_target': m.D.TARGET}
        phase('current-physical-coverage-confirmed-before-advance')
    return before_advance


def _completed(m, a, workflow, record, phase):
    def completed(result):
        store = workflow._store
        root_key = json.loads(workflow._root)['key']
        audit = result.collar.source_stage.source_audit
        record['completed_endpoint'] = {'workflow_id': workflow.workflow_id, 'root_key': root_key,
            'root_metadata': store.metadata(root_key), 'head_key': workflow._head['key'],
            'producer_pid': os.getpid(), 'store_limits': asdict(store.limits),
            'store_compression': asdict(store.compression),
            'collar_result_id': result.state.result_id, 'native_result_id': result.state.native_state.result_id,
            'exterior_state_id': result.exterior.state.state_id, 'source_audit_id': audit.result_id,
            'joined_heat_id': result.exterior._heat.result_id,
            'array_records': {'collar': m.D.snapshots(result.state.fields),
                'native': m.D.snapshots(result.state.native_state),
                'exterior': m.D.snapshots(result.exterior.state._snapshot), 'source_audit': m.D.snapshots(audit),
                'full_collar': m.D.arrays(result.state.arrays()),
                'spatial_audit': m.D.arrays(result.exterior.audit_arrays())},
            'preparation_ids': preparation_ids(a.case, a.owner),
            'execution_provenance': a.heat_execution.provenance, 'sequence': workflow._head.get('sequence')}
        temperatures = result.exterior._heat._result.array('temperature_k')
        record['public_temperature_k'] = {'minimum': float(temperatures.min()),
            'maximum': float(temperatures.max()), 'count': int(temperatures.size),
            'array_sha256': sha256(temperatures.tobytes()).hexdigest()}
        phase('actual-heat-endpoint-committed')
    return completed
