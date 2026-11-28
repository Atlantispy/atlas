"""Route (1) fresh start: interval 1 of a new lineage on a compact store.

The retained original interval-1 flow (reviewed producer source,
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
- advance_successor_interval (interval N >= 2, item 21): the same admission, then
  the adopted interval N-1 head of the runner's sealed lineage is opened and
  advanced once by prepared_interval_driver through r9's continuation seam, with
  the joined module interval 1 ran; ``finish`` again runs with the workflow open.

Every physical input, control, work ceiling and tolerance is r9's: the literals
below are checked against r9's source by test_fresh_interval_driver. The
observer, selector gate and compact-aware coverage gate are the current
composition's (prepared_interval_driver), as for the migrated lineage. Nothing
here seals, promotes or reads back; the runner owns the store protocol.
"""
import functools
import json
import os
from atlas_shared.errors import AtlasError
from atlas_tectonics._private.integration.runtime_checks import Checks
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import asdict
from fractions import Fraction as Q
from hashlib import sha256
from types import CodeType, SimpleNamespace

# r9's admission and work ceilings, verbatim (probe_heat_original_connected_r9.py run()).
FIXTURE = {'pressure_space': 'q1-p0', 'material_quadrature': True}
MEASUREMENT_CACHE = {'chunk_bytes': 65536, 'max_array_bytes': 1 << 20, 'max_store_bytes': 128 << 20}
MEASUREMENT_CODEC = 'raw'
INITIAL_PARTITION = {'max_components': 4096}
INITIAL_METRICS = {'physical_volume_error_m3': Q(32000), 'thermal_volume_error_m3': Q(32000),
                   'max_leaves': 2**30, 'max_witness_refinements': 32}
CREATED_TRACERS = ('tracer:accumulated_strain_ii',)
PRESSURE_FORCE = {'pressure_max_leaves': 2**19, 'initial_trace_max_leaves': 2**19}
# Plan07 pressure scheduling is unchanged. Interval 1 runs ALE under the automatic four-worker
# policy (o3). A successor entered without a measured
# worker selection keeps fixed serial ALE: that is Plan11's comparison arm, and it establishes
# no automatic or parallel ALE parity of its own.
PARALLEL = {'mode': 'auto', 'workers': 2}    # pressure walls; the count is replaced by first_workers at launch
ALE_PARALLEL = {'mode': 'auto', 'workers': 4, 'keep_workers': True}    # o3, Part B: execution-only policy; no result depends on it


def launch_samples():
    """The store's folder, its samples read once: a pool sized before it has a worker counts one at the stored peak."""
    from atlas_shared.machine import resources_monitor as MON
    from atlas_tectonics._private.integration.prepared_interval_driver import profile_folder
    folder = profile_folder()
    MON.use_store(folder)
    return folder


def samples_saved():
    """The launch's measured samples go to the store when the launch ends, however it ends."""
    from atlas_shared.machine import resources_monitor as MON
    end = ExitStack()
    end.callback(MON.save_store, launch_samples())
    return end


def first_workers(policy_type, policy, load=None, stage=None):
    """An interval-1 interface pool: the resources gate's launch width for its stage (ATLAS_RESOURCES).

    The policy's gates still step the count down at each dispatch. Execution only.
    """
    from atlas_tectonics._private.integration.parallel.interface_worker_selection import (
        first_interval_workers,
    )
    launch_samples()
    return first_interval_workers(policy_type(**policy), load, stage)


def _width(stage, allowance, load):
    # A worker is counted at the stored largest peak of its pool, at the allowance before one is stored.
    from atlas_shared.machine import resources_monitor as MON
    from atlas_shared.machine import resources_gate as RG
    launch_samples()
    machine = MON.reading(load)
    return RG.launch_width(machine, RG.setting(machine), MON.Timings().peak((stage, 'worker', 'peak')) or allowance,
                           stage=stage)


def initial_admission_workers(load=None):
    """The producer's admission pool by the resources gate's launch rule."""
    from atlas_tectonics.integration.parallel import initial_parallel as I
    from atlas_tectonics.integration.parallel import dispatch as D
    return _width('admission', D.CHILD_BASELINE+I.CHILD_BYTES, load)


def heat_workers(load=None):
    """The heat pool by the resources gate's launch rule; its per-call bound still applies."""
    from atlas_tectonics._private.integration.heat.process_meter import CHILD_START
    return _width('heat', CHILD_START, load)


def pool_widths(load, admission):
    """This launch's record of widths: the setting as given, its mode, the cores counted and their source, and each
    stage's width (heat, pressure and ale are added from their configured pools)."""
    from atlas_shared.machine import resources_monitor as MON
    from atlas_shared.machine import resources_gate as RG
    machine = MON.reading(load)
    return RG.widths_record(machine, RG.setting(machine), {'admission': admission})


SUCCESSOR_COMPARISON_ALE = {'mode': 'serial', 'workers': 2}    # the one explicit policy prepared_interval_driver accepts
# The runner's sealed-lineage record for interval N >= 2 (prepared_interval_driver checks the same schema).
LINEAGE_SCHEMA = 'atlas.fresh-interval-lineage.v1'


class FreshIntervalRefused(ValueError, AtlasError):
    pass


def _require(condition, message):
    if not condition:
        raise FreshIntervalRefused(message)


def _bind_record_scope(store, owner, budget):
    """Bind the actual writable interval's retained scope to its fresh owner."""
    from atlas_tectonics._private.integration.heat.heat_ledger_issuer_patch import require_candidate

    scope = store.scope
    owner._record_scope = scope
    require_candidate(store, owner)


def _seed_pinned():
    # RC1 iterates sets in places (exact_start_zero), so work units and the
    # records carrying them differ between processes unless the hash seed is
    # fixed. Production pins 0; runs A and B must both start with it.
    pass


# The fields of run A's published root that run B's re-derived admission must reproduce.
ROOT_IDENTITY = ('workflow_id', 'root_key', 'kind', 'sequence', 'root_metadata_sha256',
                 'execution_provenance', 'preparation_ids')


def preparation_ids(case, owner):
    """The plan and owner identities a fresh reader rebuilds and must compare."""
    collar = case['collar']
    return {'owner': case['owner'].owner_id, 'spatial_owner': owner.owner_id, 'native': collar._native.plan_id,
            'collar': collar.plan_id, 'map': collar._map.volume_map_id, 'funding': case['funding'].funding_id}


def admission(m, *, budget, artifacts, phase, measurements=None, initial_workers=0, before_measurements=None,
              launch_load=None, observe_heat_width=None):
    """r9's deterministic admission with r9's execution contexts and measurement cache open.

    A plain function returning the context manager, not a decorated one: the loaded-source
    fence compares each module-level function's loaded code with the pinned source, and a
    decorated function's loaded code is the decorator's wrapper.

    ``measurements`` (item 7) observes only: when given, it is called once, right after the
    initial metrics (the store's only use) and after the store has closed, with the store's own
    statistics() and the initial bounds. The producer runner records the snapshot count and the
    initial component queries the bounds carry, which give its cache hits and misses, and
    publishes the closed store; the reader passes it to count what it measured.
    ``before_measurements``: called once, after the fixture and the partition and before
    the store opens; a reader copies its producer's store there. The store's path and contents
    are this function's alone: a seeded store is the runner's copy, made before the store opens.
    """
    return contextmanager(_admission)(m, budget=budget, artifacts=artifacts, phase=phase,
                                      measurements=measurements, initial_workers=initial_workers,
                                      before_measurements=before_measurements, launch_load=launch_load,
                                      observe_heat_width=observe_heat_width)


# A2: queries per Plan09 admission batch (the pool accepts 1 to 64; its default is 16).
INITIAL_BATCH_JOBS = 64


def _admission(m, *, budget, artifacts, phase, measurements=None, initial_workers=0, before_measurements=None,
               launch_load=None, observe_heat_width=None):
    # Plan09 eight-worker initial admission (R1): producers, and since o2 the ordinary reader. 0 = serial (an overlap
    # reader, Plan11 section 4).
    from atlas_tectonics.integration.parallel.initial_parallel import initial_ceiling
    _require(type(initial_workers) is int and (initial_workers == 0 or 1 <= initial_workers <= initial_ceiling()),
             'initial admission requires the serial reader or a producer pool within the host ceiling')
    phase('begin-fresh-native-admission')
    heat_width = m.J.I.F.FUNCTIONS.PARALLEL.configure(workers=heat_workers(launch_load))
    if observe_heat_width is not None:
        observe_heat_width(heat_width)
    with m.ExecutionContext('reference') as reference_execution, \
            m.ExecutionContext('scipy') as heat_execution, \
            m.radial_differential_fixture(budget=budget, **FIXTURE) as case:
        current, partition = m.spatial.initial_partition(case, **INITIAL_PARTITION)
        if before_measurements is not None:
            before_measurements()
        phase('initial-physical-and-thermal-metrics')
        initial_pass = None
        if initial_workers:
            from atlas_tectonics.integration.parallel.initial_parallel import InitialParallel
            initial_pass = InitialParallel(workers=initial_workers, budget=budget, context=reference_execution,
                                           batch_jobs=INITIAL_BATCH_JOBS)
        with m.ArrayStore(artifacts/'initial-measurements.sqlite', m.StoreLimits(**MEASUREMENT_CACHE),
                          m.Compression(codec=MEASUREMENT_CODEC), budget=budget) as cache:
            with (nullcontext() if initial_pass is None else initial_pass):
                bounds, mesh = m.spatial.initial_metrics(case, partition, **INITIAL_METRICS, measure_policy=m.D.POLICY,
                    measurement_store=cache, measurement_context=reference_execution)
            statistics = cache.statistics()
        if measurements is not None:
            measurements(statistics, bounds)            # the store is closed: its bytes are final
        with m.spatial.initial_spatial_owner(case, partition, bounds, mesh, created_tracers=CREATED_TRACERS,
                measure_policy=m.D.POLICY, heat_method=m.J.METHOD) as owner:
            yield SimpleNamespace(case=case, current=current, partition=partition, owner=owner,
                                  reference_execution=reference_execution, heat_execution=heat_execution,
                                  initial_parallel=None if initial_pass is None else dict(initial_pass.report))


def published_root(workflow, store, a):
    """The root identity a fresh reader must reproduce (recorded by run A)."""
    root = json.loads(workflow._root)
    store.metadata(root['key'])
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
    with admission(m, budget=budget, artifacts=artifacts, phase=phase,
                   measurements=measurements, initial_workers=initial_admission_workers()) as a:
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


def _root_differences(found, expected):
    """Every identity field except the execution provenance (no execution-identity refusal) must agree."""
    return [name for name in ROOT_IDENTITY if name != 'execution_provenance' and found[name] != expected[name]]


def reopen_root(m, *, store, expected_root, budget, artifacts, phase, measurements=None):
    """Run B up to the advance (stop-before-advance smoke): the same admission, then the adopted root.

    CollarWorkflow.open compares every root field with this admission; every
    ROOT_IDENTITY field of the reopened root must equal run A's. Nothing advances,
    no pressure or force check runs and nothing is written. ``measurements``: see admission.
    """
    _seed_pinned()
    with admission(m, budget=budget, artifacts=artifacts, phase=phase,
                   measurements=measurements, initial_workers=initial_admission_workers()) as a:
        phase('reopen-adopted-fresh-root')
        with m.Workflow.open(store, expected_root['workflow_id'], a.case['collar'], a.case['owner'],
                             a.case['funding'], budget=budget, exterior_owner=a.owner) as workflow:
            before = workflow.inspect()
            found = published_root(workflow, store, a)
            _root_differences(found, expected_root)
            return {**{name: found[name] for name in ROOT_IDENTITY}, 'inspect': before}


def advance_first_interval(m, *, store, expected_root, budget, artifacts, phase, guard, record, save,
                           query_checkpoints, finish, measurements=None, end_geometry_provider_factory=None,
                           require_heat_pool=False):
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
    from atlas_tectonics._private.codecs.compact_restart_patch import require_capture_route
    from atlas_shared.execution import profiling as TIMING
    require_capture_route(store)
    _seed_pinned()
    # Item 11 M: the schema, closures included, resolves before the record and the admission (fail closed).
    stages, ticks = _stages(m), _ticks(m)
    record['observed_stages'] = [name for _, name in stages]
    record['heat_workers_strict'] = m.J.I.F.FUNCTIONS.PARALLEL.strict()     # a value other than unset, '' or 1 refuses
    from atlas_shared.machine import resources_monitor as MON
    load = MON.launch_load()    # this launch's one CPU sample, shared by its pools
    record['initial_admission_workers'] = width = initial_admission_workers(load)    # this launch's own width (Q-1)
    record['pool_widths'] = pool_widths(load, width)    # effective width per stage and its source

    def observe_heat_width(configured):
        record['pool_widths']['widths']['heat'] = configured
        if require_heat_pool:
            _require(configured >= 2, f'Matched ordinary interval deferred: configured heat workers {configured}; '
                                     'required minimum 2 before geometry')

    with samples_saved(), guard.check3.forward(budget, [name for _, name in _stages(m)
                                      if name != 'actual-differential-geometry']), \
            admission(m, budget=budget, artifacts=artifacts, phase=phase,
                   measurements=measurements, initial_workers=width, launch_load=load,
                   observe_heat_width=observe_heat_width) as a, \
            m.geometry_observer.observe(guard, stages, ticks, joined=m.joined,
                                        geometry=m.G.enclose_differential_ale), \
            m.threadpool_limits(1), query_checkpoints(a.heat_execution) as checkpoints:
        _bind_record_scope(store, a.owner, budget)
        record['selector_gate_before_advance'] = m.prepared_interval_driver.selector_gate(m.PF)
        save()
        test = Checks()
        from atlas_tectonics.integration.coupling import pressure_walls as integration_pressure_walls
        # Plan11 separates the selected ALE policy from Plan07 pressure.
        costs = m.prepared_interval_driver.profile_folder()    # W-1 (c): outside the home, which PF refuses
        parallel_policy = m.InterfaceParallelPolicy(**dict(PARALLEL, workers=first_workers(m.InterfaceParallelPolicy,
                                                                                      PARALLEL, load, 'pressure')),
            profile_path=str(costs/'parallel-profile.json'))
        ale_policy = m.InterfaceParallelPolicy(**dict(ALE_PARALLEL, workers=first_workers(m.InterfaceParallelPolicy,
                                                                                          ALE_PARALLEL, load, 'ale')),
            profile_path=str(costs/'ale-parallel-profile.json'))
        record['pressure_parallel_policy'] = asdict(parallel_policy)
        record['ale_parallel_policy'] = asdict(ale_policy)
        record['pool_widths']['widths'].update(pressure=parallel_policy.workers, ale=ale_policy.workers)
        save()

        def prepared(driver, pressure, datum, **extra):
            TIMING.checkpoint('pressure-and-force-selection-complete')
            phase('prepare-actual-force-selected-interval')
            with m.Workflow.open(store, expected_root['workflow_id'], a.case['collar'], a.case['owner'],
                                 a.case['funding'], budget=budget, exterior_owner=a.owner) as workflow:
                # K9: one store-set read batch for the advance and its reopen controls: the sealed parents are
                # checked once before and once after, and the second check comes before anything is sealed.
                with store.store_set.read_batch():
                    before = workflow.inspect()
                    found = published_root(workflow, store, a)
                    _root_differences(found, expected_root)
                    record['root_reproduced'] = {name: found[name] for name in ROOT_IDENTITY}
                    parent, root_bytes = dict(workflow._head), workflow._root
                    report, restored = m.joined._advance_current_interval(test, a.case, workflow,
                        current=a.current, parent=a.partition, owner=a.owner, driver=driver, pressure=pressure,
                        datum=datum, network=a.case['source'][0].network, force_control=m.ACTUATED_CONTROL,
                        heat_execution=a.heat_execution, absolute_heat_residual_target=m.D.TARGET,
                        cancel=m.D._Cancel(guard.check),
                        before_advance=_before_advance(m, a, guard, artifacts, record, save, phase,
                            store_limits=asdict(store.limits)),
                        completed_observer=_completed(m, a, workflow, record, phase, artifacts=artifacts),
                        endpoint_checkpoints=checkpoints,
                        **({} if end_geometry_provider_factory is None else {'end_geometry_provider_factory':
                            functools.partial(end_geometry_provider_factory, ale_parallel=ale_policy)}),
                        ale_parallel=ale_policy,
                        **m.D.ADVANCE_OPTIONS, **extra)
                    record['joined_global_and_created_tracer_controls'] = report
                    m.joined._check_reopened(test, workflow, restored)
                    del restored
                    after = workflow.inspect()
                save()
                TIMING.checkpoint('post-publication-reopen-controls-complete')
                return finish(workflow, before=before, after=after, parent=parent, root_bytes=root_bytes)

        with integration_pressure_walls.parallel(parallel_policy, a.reference_execution):
            return m.check_initial_pressure_force(test, a.case, a.current, a.partition, a.owner.initial_state,
                force_control=m.ACTUATED_CONTROL, **PRESSURE_FORCE, prepared_control=prepared)


def advance_successor_interval(m, *, store, expected_root, lineage, budget, artifacts, phase, guard, record, save,
                               query_checkpoints, finish, measurements=None, worker_selection=None):
    """Run B of interval N >= 2: the same admission, then open the adopted interval N-1 head and advance once.

    ``lineage`` is the runner's sealed-lineage record (interval N-1, workflow ID, root and head
    keys), which its gate bound to the adopted catalog before this call; ``expected_root`` is run
    A's published root record. Before the admission begins, the lineage must be a sealed record
    of run A's root for an interval-1-or-later parent. After it, CollarWorkflow.open must accept
    the re-derived admission, every ROOT_IDENTITY field must equal run A's and the opened head must
    be the lineage's parent. prepared_interval_driver then advances once through r9's continuation
    seam with the joined module interval 1 ran; it opens the geometry observer and the thread
    limit itself and binds the lineage to the opened head again before any physical work.
    ``query_checkpoints``, ``finish`` and ``measurements``: as for advance_first_interval.
    """
    from atlas_tectonics._private.codecs.compact_restart_patch import require_capture_route
    require_capture_route(store)
    _seed_pinned()
    # Item 11 M: prepared_interval_driver observes this schema; a missing closure refuses before the admission.
    _stages(m)
    _ticks(m)
    record['heat_workers_strict'] = m.J.I.F.FUNCTIONS.PARALLEL.strict()     # a value other than unset, '' or 1 refuses
    from atlas_shared.machine import resources_monitor as MON
    load = MON.launch_load()    # this launch's one CPU sample, shared by its pools
    record['initial_admission_workers'] = width = initial_admission_workers(load)    # this launch's own width (Q-1)
    record['pool_widths'] = pool_widths(load, width)    # effective width per stage and its source
    with samples_saved(), guard.check3.forward(budget, [name for _, name in _stages(m)
                                      if name != 'actual-differential-geometry']), \
            admission(m, budget=budget, artifacts=artifacts, phase=phase,
                   measurements=measurements, initial_workers=width, launch_load=load) as a:
        _bind_record_scope(store, a.owner, budget)
        record['pool_widths']['widths']['heat'] = m.J.I.F.FUNCTIONS.PARALLEL.configure()    # as configured
        phase('reopen-adopted-successor-head')
        with m.Workflow.open(store, expected_root['workflow_id'], a.case['collar'], a.case['owner'],
                             a.case['funding'], budget=budget, exterior_owner=a.owner) as workflow, \
                ExitStack() as batch:
            # K9: as in advance_first_interval; closed before save() and finish, inside the checkpoint scope.
            batch.enter_context(store.store_set.read_batch())
            before = workflow.inspect()
            found = published_root(workflow, store, a)
            _root_differences(found,expected_root)
            record['root_reproduced'] = {name: found[name] for name in ROOT_IDENTITY}
            head = workflow._head
            parent, root_bytes = dict(head), workflow._root
            with query_checkpoints(a.heat_execution) as checkpoints:
                m.prepared_interval_driver.advance_prepared_interval(case=a.case, workflow=workflow, base=None,
                    execution=a.heat_execution, guard=guard, record=record, save=save, artifacts=artifacts,
                    query_checkpoints=checkpoints, lineage=lineage, joined_module=m.joined,
                    ale_policy=SUCCESSOR_COMPARISON_ALE if worker_selection is None else None,
                    worker_selection=worker_selection, heat_pool_set=True)
                after = workflow.inspect()
                batch.close()
                save()
                return finish(workflow, before=before, after=after, parent=parent, root_bytes=root_bytes)


def _stages(m):
    return [(m.G.enclose_differential_ale, 'actual-differential-geometry'),
            (m.J.forward, 'actual-composed-heat-forward'), (m.J.I.F.LOW.solve, 'heat-low-predictor'),
            (m.J.I.F.FUNCTIONS.reconstruct, 'heat-certified-polygon-reconstruction'),
            # Written when a pass's workers cannot be used, before anything is computed in their place.
            (m.J.I.F.FUNCTIONS.PARALLEL.fell_back, 'heat-worker-fallback'),
            *_finish_stages(m), *_projection_stages(m), *_commit_stages(m)]


def _finish_stages(m):
    # Item 11 M (Runner, wind-down C): r9's finish marker now covers only the finish prefix; each call
    # inside it splits it, in call order. The closed guard runs only when the finish is closed.
    F = m.J.I.F.FINISH
    return [(F.finish, 'heat-conservative-finish'), (F.C.correct, 'heat-finish-correction'),
            (F.Q.closed_guard, 'heat-finish-closed-guard'), (F.I.issue, 'heat-finish-issue')]


def _projection_stages(m):
    # Observe the loaded calculator N5 actually calls; N4 keeps R's original alias.
    N = m.J.I.N
    numerical = getattr(N, 'NUMERICS', N.R)
    return [(N.project, 'heat-native-projection'), (N.R.verified_private, 'heat-projection-decode'),
            (numerical.calculate, 'heat-projection-exact')]


def _commit_stages(m):
    # Item 11 pressure-stage call inventory: the r9 IV1 log has
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
            (m.J.I.F.FUNCTIONS.PARALLEL.completed, 'heat_faces_collected'),
            *_heat_ticks(m)]


def _heat_ticks(m):
    # Item 11 M: counters only. The two closed-guard counters observe the scan's nested functions, made
    # afresh at each call, through their one code object each; resolved through the loaded FINISH.Q.
    guard = m.J.I.F.FINISH.Q._guard
    return [(m.J.I.INDEXED.metric_identity, 'metric_identity_calls'),
            (SimpleNamespace(__code__=_closure(guard, 'certificate')), 'closed_guard_certificates'),
            (SimpleNamespace(__code__=_closure(guard, 'admissible')), 'closed_guard_admissible_tests')]


def _closure(fn, name):
    # Return exactly one direct nested code object; deeper functions do not match.
    # Tick registration supplies the observer probe without executing either closure.
    found = [code for code in fn.__code__.co_consts if type(code) is CodeType and code.co_name == name]
    return found[0]


def _before_advance(m, a, guard, artifacts, record, save, phase, *, store_limits):
    budget = a.case['budget']
    # Heat door record (design heat-finish-save-point-r1 part 1): FINISH's inputs written just before it runs.
    door = m.J.I.F.DOOR
    door.folder, door.context, door.last = str(artifacts), {'execution_provenance': a.heat_execution.provenance}, None

    def before_advance(source, end_bounds, end_mesh, solution):
        if getattr(end_mesh, 'is_compact', False):
            from atlas_tectonics._private.codecs.compact_restart_patch import inspect_compact_preadvance
            coverage = inspect_compact_preadvance(m.D.physical_control, end_mesh, solution.graph,
                end_bounds, m.J.R, budget, guard.check, artifacts, record, save)
        else:
            coverage = m.D.physical_control.inspect_preadvance(end_mesh, solution.graph,
                end_bounds, m.J.R, budget, guard.check, artifacts, record, save)
        duration = source.source_stage.source_audit.descriptor()['duration_s']
        record['preheat_gate'] = {'cells': coverage['cells'], 'faces': coverage['faces'], 'duration_s': duration,
            'coverage': coverage, 'absolute_residual_target': m.D.TARGET}
        from atlas_shared.execution import profiling as TIMING
        TIMING.checkpoint('geometry-and-pre-advance-coverage-complete')
        phase('current-physical-coverage-confirmed-before-advance')
        from atlas_tectonics._private.integration.geometry.live_spatial_patch import record_access as _p26_record_access, reference as _p26_record_reference, holder_identity as _p26_holder_identity
        from atlas_tectonics._private.integration.geometry.spatial_indexed_patch import iter_logical_json as _p26_bounds_chunks
        from contextlib import nullcontext as _p26_nullcontext
        # D-1 (design step5-6-twice 7fa21d3f s2): the capture hashed end_bounds' own bytes; when that is the solution's
        # bounds_id they are the sidecar's bytes, already held: no render, no record open. The sidecar's hash decides.
        _p26_bounds_id = _p26_holder_identity(solution.bounds)
        _p26_held = record.get('preadvance_operands', {}).get('bounds', {}).get('raw_sha256') == _p26_bounds_id
        with (_p26_nullcontext() if _p26_held else _p26_record_access(solution.bounds)) as _p26_bounds_record:
            record['receiving_certification'] = m.prepared_interval_driver.P26ReceivingCapture.certification(solution,
                output_directory=artifacts, limits=store_limits,
                bounds_identity=_p26_bounds_id,
                bounds_chunks=(memoryview(end_bounds._json),) if _p26_held else
                _p26_bounds_chunks(_p26_record_reference(_p26_bounds_record)))
        save()
    return before_advance


def _completed(m, a, workflow, record, phase, *, artifacts):
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
        record['heat_first_pass'] = m.J.I.F.FUNCTIONS.PARALLEL.report()
        door = m.J.I.F.DOOR
        record['heat_door'] = dict(door.last or {'written': False})
        door.folder = door.context = None
        from atlas_shared.execution import profiling as TIMING
        TIMING.checkpoint('heat-projection-and-endpoint-publication-complete')
        phase('actual-heat-endpoint-committed')
        record['receiving_preimages'] = m.prepared_interval_driver.P26ReceivingCapture.capture(result,
            output_directory=artifacts, limits=asdict(workflow._store.limits))
    return completed
