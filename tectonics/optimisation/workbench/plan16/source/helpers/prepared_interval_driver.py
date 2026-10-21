"""Advance one authenticated migrated head using the retained r9 physical case.

No initialisation, funding, runtime selection or checkpoint admission happens
here. The enclosing source-selected restarter owns those boundaries. This is
the actual r9 second() seam with its ordinary-root-specific reader removed:
the native migrated-root cold reader validates publication instead. Exact
completed-query storage is caller-owned and persists outside attempt outputs.

Observation uses the hook-free geometry observer: our own monitoring tool is
released only inside the joined ALE compute scope, so the unchanged native
selector may dispatch automatic geometry workers. Physics, controls, work
ceilings and the external guardian are unchanged. case['state'] must be the
authenticated frozen initial workload; the old sequence-zero continuation
validator is NOT used for this migrated non-zero cursor.

Item 21 (16 Oct 2026): the same seam also advances an ordinary fresh-lineage
head N-1 >= 1 (``base=None``, the runner's sealed ``lineage`` record and the
``joined_module`` interval 1 ran, joined r8). Before any physical work the
opened head must equal the lineage, and the fixture workload's duration must
equal the parent head's own advance. That route also observes item 11's
commit-window stages. The migrated route above is unchanged.
"""
from dataclasses import asdict
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


PRESSURE_MAX_LEAVES = CURRENT_TRACE_MAX_LEAVES = 2**19
MAX_PARTITION_COMPONENTS = 65536
OWN_MONITORING_TOOL = (3, 'private-original-heat-control')
# The fresh runner's lineage record (run_fresh_interval writes it after its sealed-lineage gate).
LINEAGE_SCHEMA = 'atlas.fresh-interval-lineage.v1'
FRESH_JOINED = 'private_heat_original_joined_r8'


class PreparedIntervalRefused(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise PreparedIntervalRefused(message)


def _note(record, key, read):
    # Diagnostic availability never substitutes for required acceptance.
    try:
        record[key] = json.loads(json.dumps(read(), allow_nan=False, default=repr))
    except Exception as error:
        record[key+'_unavailable'] = repr(error)


def selector_gate(PF):
    """Record what the unchanged native selector reads, inside our observer scope.

    Here only our own tool may be registered. The joined ALE compute scope
    releases exactly that tool, so the selector then sees no instrumentation.
    Any other hook, or a randomised interpreter, would keep geometry serial for
    the whole interval: refuse before the advance instead.
    """
    monitoring = sys.monitoring
    tools = {str(i): monitoring.get_tool(i) for i in range(6) if monitoring.get_tool(i) is not None}
    gate = dict(seed=PF.seed_flag(), instrumented_in_observer_scope=PF.instrumented(),
        monitoring_tools=tools, trace_hook=sys.gettrace() is not None,
        profile_hook=sys.getprofile() is not None,
        released_inside_joined_ale_compute=[str(OWN_MONITORING_TOOL[0])],
        expected_instrumented_inside_joined_ale_compute=False)
    _require(gate['seed'] == '0', 'automatic geometry requires an interpreter started with PYTHONHASHSEED=0')
    _require(tools == {str(OWN_MONITORING_TOOL[0]): OWN_MONITORING_TOOL[1]} and
             not gate['trace_hook'] and not gate['profile_hook'],
             'foreign instrumentation would keep automatic geometry serial')
    return gate


def selected_ale_policy(policy, *, ordinary, worker_selection=None):
    """Plan11 serial comparison seam; migrated/default scheduling stays unchanged."""
    if worker_selection is not None:
        _require(ordinary and policy is None,
                 'measured workers apply only to the ordinary successor route')
        from interface_worker_selection import policy_from_selection
        return policy_from_selection(worker_selection)
    if policy is None:
        return dict(mode='auto', workers=2)
    _require(ordinary and type(policy) is dict and
             set(policy) == {'mode', 'workers'} and
             policy['mode'] == 'serial' and type(policy['workers']) is int and
             policy['workers'] == 2,
             'an explicit ALE comparison policy is fixed serial for an ordinary fresh lineage only')
    return dict(policy)


def advance_prepared_interval(*, case, workflow, base, execution, guard, record,
                             save, artifacts, query_checkpoints, lineage=None, joined_module=None,
                             ale_policy=None, worker_selection=None):
    import probe_heat_original_connected_r9 as D
    import private_heat_geometry_observer_r1 as geometry_observer
    import private_heat_original_continuation_r1 as continuation
    import private_heat_joined_consumer_r6 as J
    import private_heat_process_meter_r1 as METER
    import initial_workload as IW
    import workflow_transfer as W
    import dev_stage_timing as TIMING
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    from atlas_tectonics.integration_parallel_selection import InterfaceParallelPolicy
    from atlas_tectonics.integration_endpoint_checkpoints import EndpointCheckpoints
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_parallel_profile as PF
    from i04_differential_modes import ACTUATED_CONTROL
    from threadpoolctl import threadpool_limits

    budget = case['budget']
    ordinary = base is None and lineage is not None
    selected_ale = selected_ale_policy(ale_policy, ordinary=ordinary, worker_selection=worker_selection)
    if not ordinary:
        import private_heat_original_joined_r6 as joined
        if (type(workflow) is not CollarWorkflow or type(base) is not W.MigratedWorkflowBase or
                workflow._migration is not base or workflow._budget is not budget or
                type(query_checkpoints) is not EndpointCheckpoints or
                not query_checkpoints._active or query_checkpoints.budget is not budget or
                query_checkpoints.context is not execution or
                lineage is not None or joined_module is not None):
            raise TypeError('actual same-budget migrated head and active query checkpoint owner required')
        # Fail before any physical work, never after hours of geometry.
        _require('endpoint_checkpoints' in inspect.signature(joined._advance_current_interval).parameters,
                 'composed joined helper with an explicit completed-query owner is required')
        _require(type(case.get('state')) is IW.InitialWorkloadState,
                 "case['state'] must be the authenticated InitialWorkloadState of the migrated root")
        scratch = W._decode_allocation(budget, base._endpoint)
        first_duration = json.loads(base._endpoint)['head']['advance']['duration_s']
        _ = scratch
        duration = ACTUATED_CONTROL.duration(case)
        _require(duration == first_duration,
                 'frozen initial workload duration differs from the authenticated first interval')
    else:
        if (type(workflow) is not CollarWorkflow or getattr(workflow, '_migration', None) is not None or
                workflow._budget is not budget or
                type(query_checkpoints) is not EndpointCheckpoints or
                not query_checkpoints._active or query_checkpoints.budget is not budget or
                query_checkpoints.context is not execution):
            raise TypeError('actual same-budget ordinary head and active query checkpoint owner required')
        # One joined code for the whole fresh lineage: the loaded module interval 1 ran.
        _require(joined_module is sys.modules.get(FRESH_JOINED) and
                 getattr(joined_module, '__name__', None) == FRESH_JOINED,
                 'an ordinary fresh lineage advances with the loaded joined r8 module interval 1 ran')
        joined = joined_module
        # Fail before any physical work, never after hours of geometry.
        _require('endpoint_checkpoints' in inspect.signature(joined._advance_current_interval).parameters,
                 'composed joined helper with an explicit completed-query owner is required')
        _require(type(case.get('state')) is not IW.InitialWorkloadState,
                 'a frozen migrated initial workload never enters an ordinary fresh lineage')
        # The runner bound the lineage to the adopted catalog; bind it to the opened head.
        _require(type(lineage) is dict and lineage.get('schema') == LINEAGE_SCHEMA,
                 "an ordinary successor needs the runner's sealed lineage record")
        interval = lineage.get('interval')
        _require(type(interval) is int and interval >= 1,
                 'a sealed lineage parent is interval 1 or later; '
                 'the root advances through the fresh first-interval driver')
        root_record, head = json.loads(workflow._root), workflow._head
        expected = dict(workflow_id=lineage.get('workflow_id'), root_key=lineage.get('root_key'),
                        root_kind='root', head_key=lineage.get('head_key'), kind='successor', sequence=interval)
        found = dict(workflow_id=workflow.workflow_id, root_key=root_record.get('key'),
                     root_kind=root_record.get('kind'), head_key=head.get('key'), kind=head.get('kind'),
                     sequence=head.get('sequence'))
        differing = [name for name in expected
                     if type(found[name]) is not type(expected[name]) or found[name] != expected[name]]
        _require(not differing, 'opened head differs from the sealed lineage: '+', '.join(differing))
        # Every fresh interval runs the same fixture workload (r9 continuation:
        # "Same frozen initial workload"); the parent's own advance recorded it.
        first_duration = head['advance']['duration_s']
        duration = ACTUATED_CONTROL.duration(case)
        _require(duration == first_duration,
                 "fixture initial workload duration differs from the adopted parent head's advance")
        record['lineage_gate'] = dict(found, lineage_schema=LINEAGE_SCHEMA, parent_advance_duration_s=first_duration)
    derivations = dict(joined=joined.derivation(), continuation=continuation.derivation())
    query_directory = Path(query_checkpoints.directory)
    # Bindings are keyed by code, seed, instrumentation and machine; a retry of
    # the same source reuses observations instead of relearning serially.
    profile_path = query_directory.parent/(query_directory.name+'.parallel-profile.json')
    before = workflow.inspect()
    root = workflow._root
    prior_id = workflow.differential_interval.interval_id
    record.update(original_target=D.TARGET, advance_options=dict(D.ADVANCE_OPTIONS),
        continuation_helper_work_ceilings=dict(pressure_max_leaves=PRESSURE_MAX_LEAVES,
            current_trace_max_leaves=CURRENT_TRACE_MAX_LEAVES,
            max_partition_components=MAX_PARTITION_COMPONENTS),
        fixture_derivations=derivations,
        parallel_policy=dict(mode='auto', workers=2, profile_path=str(profile_path)),
        ale_parallel_policy=dict(selected_ale, profile_path=str(profile_path)),
        interface_worker_selection=worker_selection,
        initial_workload_duration_s=duration,
        physical_inputs_changed=False, independent_process_reopen=False)
    save()
    test = unittest.TestCase()
    if ordinary:
        # Items 11 and 11 M: one schema with the fresh first interval, through its _stages and _ticks.
        from fresh_interval_driver import _stages, _ticks
        shared = SimpleNamespace(G=G, J=J, Workflow=CollarWorkflow)
        stages, ticks = _stages(shared), _ticks(shared)
        record['observed_stages'] = [name for _, name in stages]
    else:
        # The migrated route keeps r9's six stages and three ticks (unchanged by item 11).
        stages = [(G.enclose_differential_ale, 'actual-differential-geometry'),
            (J.forward, 'actual-composed-heat-forward'), (J.I.F.LOW.solve, 'heat-low-predictor'),
            (J.I.F.FUNCTIONS.reconstruct, 'heat-certified-polygon-reconstruction'),
            (J.I.F.FINISH.finish, 'heat-conservative-finish'), (J.I.N.project, 'heat-native-projection')]
        ticks = [(G.component_volume_bounds, 'component_volume_queries'),
                 (J.I.F.FUNCTIONS._face, 'heat_faces'),
                 (J.I.F.FUNCTIONS.PARALLEL.completed, 'heat_faces_collected')]

    def second(driver, pressure, datum, current, partition, prior_interval, network,
               state, spatial_state, owner, provenance, **extra):
        record['continuation_force'] = json.loads(json.dumps(provenance, default=repr))
        TIMING.checkpoint('pressure-and-force-selection-complete')
        guard.phase('prepare-actual-force-selected-interval')

        def before_advance(source, end_bounds, end_mesh, solution):
            # The retained coverage gate reads full legacy records; a compact
            # operand must refuse here, not inside its operand capture.
            for label, operand in (('closed graph', solution.graph), ('end bounds', end_bounds)):
                _require(getattr(operand, '_json', None) is not None,
                         'pre-advance coverage gate needs the legacy '+label+' record; '
                         'a compact operand is not composed into this gate')
            if getattr(end_mesh, 'is_compact', False):
                from compact_restart_patch import inspect_compact_preadvance
                coverage = inspect_compact_preadvance(D.physical_control, end_mesh, solution.graph,
                    end_bounds, J.R, budget, guard.check, artifacts, record, save)
            else:
                _require(getattr(end_mesh, '_json', None) is not None,
                    'pre-advance coverage gate needs the legacy end mesh record; '
                    'a compact operand is not composed into this gate')
                coverage = D.physical_control.inspect_preadvance(end_mesh, solution.graph,
                    end_bounds, J.R, budget, guard.check, artifacts, record, save)
            source_duration = source.source_stage.source_audit.descriptor()['duration_s']
            if source_duration != ACTUATED_CONTROL.duration(case):
                raise ValueError('Original force-selected duration changed')
            record['preheat_gate'] = dict(cells=coverage['cells'], faces=coverage['faces'],
                duration_s=source_duration, coverage=coverage, absolute_residual_target=D.TARGET,
                uniform_conductivity_w_m_k=.1,
                boundary='zero prescribed power on every declared boundary face',
                geometry_scope='original coarse construction contract; not arbitrary-mesh accuracy')
            TIMING.checkpoint('geometry-and-pre-advance-coverage-complete')
            guard.phase('current-physical-coverage-confirmed-before-advance')

        def completed(result):
            store = workflow._store
            root_key = json.loads(workflow._root)['key']
            audit = result.collar.source_stage.source_audit
            record['completed_endpoint'] = dict(workflow_id=workflow.workflow_id,
                root_key=root_key, root_metadata=store.metadata(root_key), head_key=workflow._head['key'],
                producer_pid=os.getpid(), store_limits=asdict(store.limits),
                store_compression=asdict(store.compression),
                collar_result_id=result.state.result_id, native_result_id=result.state.native_state.result_id,
                exterior_state_id=result.exterior.state.state_id, source_audit_id=audit.result_id,
                joined_heat_id=result.exterior._heat.result_id,
                array_records=dict(collar=D.snapshots(result.state.fields),
                    native=D.snapshots(result.state.native_state),
                    exterior=D.snapshots(result.exterior.state._snapshot), source_audit=D.snapshots(audit),
                    full_collar=D.arrays(result.state.arrays()), spatial_audit=D.arrays(result.exterior.audit_arrays())),
                # A fresh reader rebuilds these plans/owner and must compare them.
                preparation_ids=dict(owner=case['owner'].owner_id, spatial_owner=owner.owner_id,
                    native=case['collar']._native.plan_id, collar=case['collar'].plan_id,
                    map=case['collar']._map.volume_map_id, funding=case['funding'].funding_id),
                execution_provenance=execution.provenance, sequence=workflow._head.get('sequence'))
            temperatures = result.exterior._heat._result.array('temperature_k')
            record['public_temperature_k'] = dict(minimum=float(temperatures.min()),
                maximum=float(temperatures.max()), count=int(temperatures.size),
                array_sha256=sha256(temperatures.tobytes()).hexdigest())
            _note(record, 'heat_forward_memory', lambda: METER.record(budget))
            _note(record, 'heat_first_pass', lambda: J.I.F.FUNCTIONS.PARALLEL.report())
            TIMING.checkpoint('heat-projection-and-endpoint-publication-complete')
            guard.phase('actual-heat-endpoint-committed')

        options = dict(D.ADVANCE_OPTIONS)
        if 'predictor' in extra:
            options['predictor'] = extra['predictor']
        report, restored = joined._advance_current_interval(test, case, workflow, current=current,
            parent=partition, owner=owner, driver=driver, pressure=pressure, datum=datum,
            network=network, prior_interval=prior_interval, force_control=ACTUATED_CONTROL,
            heat_execution=execution, absolute_heat_residual_target=D.TARGET,
            max_partition_components=MAX_PARTITION_COMPONENTS,
            cancel=D._Cancel(guard.check), before_advance=before_advance, completed_observer=completed,
            endpoint_checkpoints=query_checkpoints,
            ale_parallel=InterfaceParallelPolicy(**selected_ale,
                profile_path=str(profile_path)), **options)
        record['joined_global_and_created_tracer_controls'] = report
        _note(record, 'heat_memory_through_post_publication_re_read', lambda: METER.record(budget))
        _note(record, 'observed_returns_at_the_end', lambda: dict(guard.counts))
        joined._check_reopened(test, workflow, restored)
        after = workflow.inspect()
        if (after['intervals'] != before['intervals']+1 or
                after['funding_id'] != before['funding_id'] or workflow._root != root or
                after['head'] == before['head']):
            raise ValueError('The workflow did not preserve root/funding and advance exactly once')
        geometry = workflow._head['differential_geometry']
        record['continuation'] = dict(parent_head_key=before['head'], parent_interval_id=prior_id,
            interval_id=workflow.differential_interval.interval_id,
            parent_interval_number=before['intervals'], interval_number=after['intervals'],
            parent_time_seconds=geometry['start_time_s'], time_seconds=geometry['end_time_s'],
            root_key=json.loads(root)['key'], funding_id=before['funding_id'])
        save()
        del restored
        TIMING.checkpoint('post-publication-reopen-controls-complete')
        return report

    # Geometry phase is explicit; component-return ticks pause only there.
    record['geometry_observation_scope'] = dict(
        own_monitoring='released only during joined ALE compute',
        component_return_counts='exclude joined ALE compute',
        cancellation='guard checks at scope boundaries; external guardian unchanged')
    with geometry_observer.observe(guard, stages, ticks, joined=joined,
            geometry=G.enclose_differential_ale), threadpool_limits(1):
        record['selector_gate_before_advance'] = selector_gate(PF)
        save()
        continuation.continuation_pressure_force(test, case, workflow, second,
            force_control=ACTUATED_CONTROL, pressure_max_leaves=PRESSURE_MAX_LEAVES,
            current_trace_max_leaves=CURRENT_TRACE_MAX_LEAVES)
    _require(dict(joined=joined.derivation(), continuation=continuation.derivation()) == derivations,
             'composed joined/continuation derivation changed during the interval')
    execution.verify_boundary()
    TIMING.checkpoint('interval-source-boundary-verification-complete')
