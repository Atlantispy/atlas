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

Item 21: the same seam also advances an ordinary fresh-lineage
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
from atlas_tectonics._private.runtime_checks import Checks


PRESSURE_MAX_LEAVES = CURRENT_TRACE_MAX_LEAVES = 2**19
MAX_PARTITION_COMPONENTS = 65536
OWN_MONITORING_TOOL = (3, 'private-original-heat-control')
# The fresh runner's lineage record (run_fresh_interval writes it after its sealed-lineage gate).
LINEAGE_SCHEMA = 'atlas.fresh-interval-lineage.v1'
FRESH_JOINED = 'atlas_tectonics._private.private_heat_original_joined_r8'


class PreparedIntervalRefused(ValueError):
    pass


class P26ReceivingCapture:
    SCHEMA = 'atlas.plan26.live-receiving-preimages.r1'
    SNAPSHOTS = ('native_inventory', 'native_driving', 'initial_mechanics',
                 'native_source_audit', 'collar_inventory', 'heat_call')
    FLOWS = ('native_flow', 'collar_flow')
    RECORDS = ('native_stage', 'source_flow')

    @staticmethod
    def _json(value):
        import json
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('ascii')

    @classmethod
    def _hash(cls, value):
        import hashlib
        return hashlib.sha256(cls._json(value)).hexdigest()

    @staticmethod
    def _require(ok, message):
        if not ok:
            raise ValueError('Plan26 receiving capture: ' + message)

    @classmethod
    def _snapshot(cls, snapshot):
        import hashlib
        import json
        import math
        # The selected snapshot's storage is immutable bytes. No array copy or
        # cached result identity supplies an operand to the recomputation.
        cls._require(isinstance(snapshot._metadata, bytes), 'snapshot metadata is not immutable bytes')
        metadata = json.loads(snapshot._metadata)
        cls._require(cls._json(metadata) == snapshot._metadata, 'snapshot metadata is not canonical')
        arrays = {}
        for name, shape, raw in snapshot._fields:
            cls._require(type(name) is str and name not in arrays and isinstance(raw, bytes), 'snapshot field storage differs')
            cls._require(all(type(n) is int and n >= 0 for n in shape) and len(raw) == math.prod(shape)*8, 'snapshot binary64 size differs')
            arrays[name] = dict(shape=list(shape), sha256=hashlib.sha256(raw).hexdigest())
        identity = cls._hash(dict(metadata=metadata, arrays=arrays))
        cls._require(identity == snapshot.result_id, 'snapshot original identity differs')
        return dict(recipe='regional-snapshot-v1', identity=identity,
                    metadata=metadata, arrays=arrays)

    MAX_FLOW_FIELDS = 4096

    @classmethod
    def _ordinary(cls, path, *, directory=False):
        import stat
        for item in (path, *path.parents):
            entry=item.lstat()
            cls._require(not stat.S_ISLNK(entry.st_mode) and not getattr(entry,'st_file_attributes',0)&0x400, 'linked/reparsed output path')
        cls._require(path.is_dir() if directory else path.is_file(), 'ordinary output required')

    @classmethod
    def _output(cls, output_directory):
        from pathlib import Path
        output=Path(output_directory)
        cls._require(output.is_absolute(),'absolute owned output directory required')
        cls._ordinary(output,directory=True)
        output=output.resolve(strict=True)
        destination=output/'receiving-preimages'
        cls._require(not any(child.name.casefold()=='receiving-preimages' for child in output.iterdir()),'receiving sidecar destination must be absent')
        cls._require(len(str(destination))+8<=260, "receiving directory exceeds MAX_PATH margin")
        for role in cls.FLOWS:
            cls._require(len(str(destination/role/"000000.bin"))+8<=260, "flow sidecar exceeds MAX_PATH margin")
        destination.mkdir()
        cls._ordinary(destination,directory=True)
        return output,destination

    @classmethod
    def _flow(cls, flow, role, output, destination, limits):
        import hashlib
        import json
        import os
        cls._require(role in cls.FLOWS,'unknown flow role')
        cls._require(isinstance(flow._metadata,bytes),'flow metadata is not immutable bytes')
        metadata=json.loads(flow._metadata)
        cls._require(cls._json(metadata)==flow._metadata,'flow metadata is not canonical')
        cls._require(len(flow._arrays)<=cls.MAX_FLOW_FIELDS,'flow field limit exceeded')
        buffers=[]
        for name,value in sorted(flow._arrays.items()):
            view=memoryview(value)
            cls._require(view.readonly and view.c_contiguous and view.itemsize==8 and view.format in ('d','<d','=d'),'flow field is not immutable contiguous binary64')
            buffers.append((name,list(view.shape),view.cast('B')))
        cls._require(all(raw.nbytes<=limits['max_array_bytes'] for _,_,raw in buffers),'flow field exceeds selected max_array_bytes before write')
        folder=destination/role
        folder.mkdir()
        cls._ordinary(folder,directory=True)
        digest=hashlib.sha256(flow._metadata)
        arrays={}
        for index,(name,shape,raw) in enumerate(buffers):
            path=folder/('%06d.bin'%index)
            cls._ordinary(folder,directory=True)
            cls._require(len(str(path))+8<=260,'flow sidecar exceeds MAX_PATH margin')
            cls._require(not path.exists(),'flow sidecar must be absent')
            field_hash=hashlib.sha256();size=0
            digest.update(cls._json([name,shape]))
            with path.open('xb') as stream:
                for offset in range(0,raw.nbytes,65536):
                    block=raw[offset:offset+65536]
                    cls._require(stream.write(block)==len(block),'short flow sidecar write')
                    digest.update(block);field_hash.update(block);size+=len(block)
                stream.flush();os.fsync(stream.fileno())
                opened=os.fstat(stream.fileno())
            cls._ordinary(path)
            observed=path.stat()
            cls._require((opened.st_dev,opened.st_ino,opened.st_size)==(observed.st_dev,observed.st_ino,observed.st_size) and size==raw.nbytes,'flow sidecar changed during write')
            arrays[name]=dict(shape=shape,dtype='<f8',sha256=field_hash.hexdigest(),nbytes=size,file=path.relative_to(output).as_posix())
        identity=digest.hexdigest()
        cls._require(identity==flow.result_id==flow.flow_id,'flow original identity differs')
        return dict(recipe='regional-flow-byte-concatenation-v1',identity=identity,metadata=metadata,arrays=arrays)

    @classmethod
    def capture(cls, result, *, output_directory, limits):
        cls._require(type(limits) is dict and all(type(limits.get(k)) is int and limits[k]>0 for k in ('max_array_bytes','max_store_bytes')),'actual selected StoreLimits mapping required')
        heat = result.exterior._heat
        call = heat._call
        cls._require(type(call._origin_objects) is tuple and len(call._origin_objects) == 4, 'actual owner origins missing')
        owner, step, mesh, _origin = call._origin_objects
        source, native = step.source, step.source.source_stage
        cls._require(step._owner is owner and source._owner is owner._collar and result.collar.source_stage is native, 'completed result is not the original source stage')
        snapshots = {
            'native_inventory': cls._snapshot(native.inventory),
            'native_driving': cls._snapshot(native.driving),
            'initial_mechanics': cls._snapshot(native.initial_mechanics),
            'native_source_audit': cls._snapshot(native.source_audit),
            'collar_inventory': cls._snapshot(source.inventory),
            'heat_call': cls._snapshot(call._snapshot),
        }
        cls._require(sum(memoryview(v).nbytes for flow in (native.flow,source.flow) for v in flow._arrays.values())<=limits['max_store_bytes'],'flow sidecar aggregate exceeds selected max_store_bytes before write')
        output,destination=cls._output(output_directory)
        flows = {'native_flow': cls._flow(native.flow,'native_flow',output,destination,limits), 'collar_flow': cls._flow(source.flow,'collar_flow',output,destination,limits)}
        native_record = {name: value['identity'] for name, value in (
            ('inventory', snapshots['native_inventory']), ('driving', snapshots['native_driving']),
            ('initial_mechanics', snapshots['initial_mechanics']), ('flow', flows['native_flow']),
            ('source_audit', snapshots['native_source_audit']))}
        cls._require(cls._hash(native_record) == native.result_id, 'native donor stage identity differs')
        source_record = source.record()
        cls._require(source_record['source_stage_id'] == native.result_id and
            source_record['inventory_id'] == snapshots['collar_inventory']['identity'] and
            source_record['flow_id'] == flows['collar_flow']['identity'] and
            cls._hash(source_record) == source.result_id, 'collar source flow identity differs')
        meta = snapshots['heat_call']['metadata']
        signature = meta['native_origin_signature']
        cls._require(signature['source_inventory_id'] == snapshots['collar_inventory']['identity'] and
            signature['native_source_inventory_id'] == snapshots['native_inventory']['identity'] and
            signature['source_stage_id'] == source.result_id and signature['owner_id'] == owner.owner_id and
            signature['graph_id'] == step.graph.geometry_id and signature['thermal_mesh_id'] == mesh.geometry_id,
            'actual call source signature differs')
        cls._require(call.call_id == snapshots['heat_call']['identity'], 'call alias differs')
        return dict(schema=cls.SCHEMA, snapshots=snapshots, flows=flows,
            records=dict(native_stage=dict(identity=native.result_id, preimage=native_record),
                         source_flow=dict(identity=source.result_id, preimage=source_record)))

    @classmethod
    def certification(cls, solution, *, output_directory, limits, bounds_chunks):
        import hashlib
        import os
        from pathlib import Path
        proposal = solution.proposal
        faces = proposal.native_faces
        cls._require(faces._stage is proposal.source_flow_stage and
            faces._collar is proposal._owner._collar, 'native face evidence is from another source')
        # Stream the issuer's original immutable bytes. Decoding here would
        # create an unowned full copy retained by the caller's run record.
        native_raw = faces._json
        cls._require(type(native_raw) is bytes, 'native measure original immutable bytes required')
        native_id = hashlib.sha256(native_raw).hexdigest()
        solution_record = solution.record()
        cls._require(native_id == faces.measure_id == solution_record['native_measure_id'],
                     'native measure original identity differs')
        cls._require(type(limits) is dict and type(limits.get('max_store_bytes')) is int and limits['max_store_bytes']>0,
                     'actual selected store limit required')
        cls._require(len(native_raw) <= min(limits['max_store_bytes'], 64 << 20),
                     'native measure exceeds selected store or 64MiB structured receiving limit')
        budget = faces._resource
        cls._require(solution.bounds._resource is budget, 'certification operands have different budgets')
        output=Path(output_directory)
        cls._require(output.is_absolute(),'absolute owned output directory required')
        cls._ordinary(output,directory=True)
        output=output.resolve(strict=True)
        folder=output/'receiving-certification'
        paths={name:folder/filename for name,filename in (
            ('bounds','bounds.json'),('native_measure','native-measure.json'))}
        cls._require(all(len(str(path))+8<=259 for path in paths.values()),'certification path exceeds MAX_PATH margin')
        cls._require(not any(child.name.casefold()=='receiving-certification' for child in output.iterdir()),
                     'certification sidecar destination must be absent')
        # Existing record codecs use 64KiB fixed workspace/header slack.
        # Payloads stay borrowed: unbuffered writes and memoryview slices make
        # no full native JSON copy, and compact chunks retain their own owner.
        with budget.reserve(65536, category='plan26-certification-sidecar'):
            folder.mkdir();cls._ordinary(folder,directory=True)
            captured={}
            for role,chunks,expected in (
                    ('native_measure',(memoryview(native_raw),),native_id),
                    ('bounds',bounds_chunks,solution_record['bounds_id'])):
                path=paths[role];digest=hashlib.sha256();size=0
                with path.open('xb', buffering=0) as stream:
                    for chunk in chunks:
                        cls._require(isinstance(chunk,(bytes,memoryview)),'selected canonical byte iterator required')
                        view=memoryview(chunk)
                        cls._require(view.ndim==1 and view.itemsize==1 and view.c_contiguous,
                                     'canonical one-dimensional byte chunks required')
                        for offset in range(0,view.nbytes,65536):
                            block=view[offset:offset+65536]
                            cls._require(size+len(block)<=limits['max_store_bytes'],'certification sidecar exceeds selected max_store_bytes')
                            cls._require(stream.write(block)==len(block),'short certification sidecar write')
                            digest.update(block);size+=len(block)
                    stream.flush();os.fsync(stream.fileno());opened=os.fstat(stream.fileno())
                cls._ordinary(path)
                observed=path.stat()
                cls._require((opened.st_dev,opened.st_ino,opened.st_size)==(observed.st_dev,observed.st_ino,observed.st_size),
                             'certification sidecar changed during write')
                identity=digest.hexdigest()
                cls._require(identity==expected,'original '+role+' preimage differs')
                captured[role]=dict(identity=identity,preimage_file=dict(
                    file=path.relative_to(output).as_posix(),sha256=identity,nbytes=size))
            cls._require(captured['bounds']['identity']==solution.bounds.bounds_id,'original bounds preimage differs')
        return dict(schema='atlas.plan26.live-certification-preimages.r2', **captured)

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
        from atlas_tectonics._private.interface_worker_selection import policy_from_selection
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
    from atlas_tectonics._private import heat_interval_r9_spec as D
    from atlas_tectonics._private import private_heat_geometry_observer_r1 as geometry_observer
    from atlas_tectonics._private import private_heat_original_continuation_r1 as continuation
    from atlas_tectonics._private import private_heat_joined_consumer_r6 as J
    from atlas_tectonics._private import private_heat_process_meter_r1 as METER
    from atlas_tectonics._private import initial_workload as IW
    from atlas_tectonics._private import workflow_transfer as W
    from atlas_tectonics._private import dev_stage_timing as TIMING
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
        from atlas_tectonics._private import private_heat_original_joined_r6 as joined
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
    from atlas_tectonics._private.compact_restart_patch import require_capture_route
    require_capture_route(workflow._store)
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
    test = Checks()
    if ordinary:
        # Items 11 and 11 M: one schema with the fresh first interval, through its _stages and _ticks.
        from atlas_tectonics._private.fresh_interval_driver import _stages, _ticks
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
    record['heat_workers_strict'] = J.I.F.FUNCTIONS.PARALLEL.strict()     # a value other than unset, '' or 1 refuses
    # The fresh driver's admission sets the same count (fresh_interval_driver._admission).
    J.I.F.FUNCTIONS.PARALLEL.configure(workers=8)

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
                from atlas_tectonics._private.compact_restart_patch import inspect_compact_preadvance
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
            from atlas_tectonics._private.live_spatial_patch import record_access as _p26_record_access, reference as _p26_record_reference
            from atlas_tectonics._private.spatial_indexed_patch import iter_logical_json as _p26_bounds_chunks
            with _p26_record_access(solution.bounds) as _p26_bounds_record:
                record['receiving_certification'] = P26ReceivingCapture.certification(solution,
                    output_directory=artifacts, limits=asdict(workflow._store.limits),
                    bounds_chunks=_p26_bounds_chunks(_p26_record_reference(_p26_bounds_record)))

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
            record['receiving_preimages'] = P26ReceivingCapture.capture(result,
                output_directory=artifacts, limits=asdict(workflow._store.limits))

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
