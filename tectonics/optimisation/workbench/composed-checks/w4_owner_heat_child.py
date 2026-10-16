"""W4 check 2 child program: genuine composed owner-call heat, compact parity and cold restore.

test_w4_owner_heat.py runs it in a fresh process as ``python -B -c <bootstrap>
<this path> <json-arguments>`` (the runner's interpreter flags, without PYTHONPATH,
from a source-free working directory); the bootstrap compiles and executes this text in
the -c __main__ namespace. It is never imported: the composed runner's
RestartSources.check_imported() refuses any unbound workspace module, and a -c
program has no module file. Nothing under composed-r1 is written; every store
is new and lives in the run directory under T/_t/w4-owner-heat. The historical
database is never opened.

Fixture: the smallest GENUINE native/collar/spatial private-heat control in H,
private_heat_native_joined_fixture_r2 (funded_collar_fixture, actual_spatial_fixture,
prepared; 2x2x2 native, 4x4x4 collar, explicit 6 GiB logical ledger, target 1e-24),
reproduced here from its source because its module selects an old private clone.
A synthetic two-cell geometry cannot reach bind_owner_call: that seam requires
an actual PreparedSpatialOwner, SpatialOwnerTransport and ExteriorMesh.

Modes:
  legacy   A: ordinary owner (legacy initial mesh), ordinary root, one genuine
              CollarWorkflow.advance_spatial (legacy parent, legacy end mesh).
  indexed  B: same fixture; the owner is restored by from_saved with the initial
              mesh converted to the compact store (indexed root, stored compact);
              the workflow's parent collar state is re-issued with retained-owner
              snapshot bytes, as native_transfer issues the migrated collar state.
              B2: genuine advance_spatial (indexed parent, retained collar parent,
              legacy end mesh), published. B1: the SAME owner and transport stage
              heated again through PreparedSpatialOwner.heat with the end mesh as
              ExteriorMesh.from_compact (bind_owner_call compact branch).
  cold     C: fresh process; rebuild only the funded collar; open B's store
              (CollarWorkflow.open -> _refresh -> COLD.restore_checkpoint), then
              call COLD.restore_checkpoint explicitly (C1: indexed parent, legacy
              head) and with the head re-issued over a compact mesh (C2: M14 seam,
              compact _context branches).
"""
import gc
import importlib.util
import json
import os
import sys
import time
import traceback
from contextlib import ExitStack, contextmanager
from fractions import Fraction as Q
from pathlib import Path

import psutil

ARGS = json.loads(sys.argv[-1])
MODE = ARGS['mode']
WORKDIR = Path(ARGS['workdir'])
TARGET = '1e-24'                       # the fixture's independently fixed residual target
BUDGET_BYTES = 6 << 30                 # private_heat_native_joined_fixture_r2.LIMITS (logical ledger only)
RSS_GUARD = 3 << 30                    # cooperative child guard (fixture r2 used 4 GiB)
AVAILABLE_GUARD = 600 << 20            # stop before the machine runs short of memory
EXACT_KEYS = ('exact_corrected_enthalpy_j', 'exact_retained_solver_residual_j',
              'exact_stock_projection_residual_j', 'exact_cell_storage_residual_j',
              'exact_paired_face_energy_j', 'exact_source_energy_j', 'exact_outward_boundary_energy_j',
              'geometry_id', 'cell_ids', 'face_ids', 'state_id', 'plan_id', 'call_id')
STARTED = time.monotonic()
PROCESS = psutil.Process()
PHASES = []
RESULT = dict(schema='atlas.private.w4-owner-heat-child.r1', mode=MODE, pid=os.getpid(), phases=PHASES,
              status='STARTED', production_acceptance=False)
_guard = dict(next=0., stop=None)


def phase(name):
    memory = PROCESS.memory_info()
    row = dict(stage=name, seconds=round(time.monotonic()-STARTED, 3), rss_bytes=memory.rss,
               peak_wset_bytes=getattr(memory, 'peak_wset', None),
               available_bytes=psutil.virtual_memory().available)
    PHASES.append(row)
    print('W4PHASE '+json.dumps(row, sort_keys=True), flush=True)


def cancelled():
    """Cooperative memory guard passed to every cancellable composed call."""
    now = time.monotonic()
    if now >= _guard['next']:
        _guard['next'] = now+.25
        rss, available = PROCESS.memory_info().rss, psutil.virtual_memory().available
        if rss > RSS_GUARD or available < AVAILABLE_GUARD:
            _guard['stop'] = dict(rss_bytes=rss, available_bytes=available)
    return _guard['stop'] is not None


def save():
    RESULT['seconds'] = round(time.monotonic()-STARTED, 3)
    RESULT['peak_wset_bytes'] = getattr(PROCESS.memory_info(), 'peak_wset', None)
    RESULT['memory_guard_stop'] = _guard['stop']
    Path(ARGS['out']).write_text(json.dumps(RESULT, sort_keys=True), encoding='utf8')


class Streams:
    """Count starts of exact code objects with sys.monitoring; nothing is patched or wrapped."""

    def __init__(self, codes):
        self.codes, self.counts, self.tool = dict(codes), {name: 0 for name in codes}, None

    def __enter__(self):
        monitoring = sys.monitoring
        for tool in (3, 4, 5):
            if monitoring.get_tool(tool) is None:
                self.tool = tool
                break
        if self.tool is None:
            raise RuntimeError('no free sys.monitoring tool id')
        names = {code: name for name, code in self.codes.items()}
        monitoring.use_tool_id(self.tool, 'w4-owner-heat-stream-counter')

        def started(code, offset):
            self.counts[names[code]] += 1

        monitoring.register_callback(self.tool, monitoring.events.PY_START, started)
        for code in self.codes.values():
            monitoring.set_local_events(self.tool, code, monitoring.events.PY_START)
        return self

    def __exit__(self, *_):
        monitoring = sys.monitoring
        for code in self.codes.values():
            monitoring.set_local_events(self.tool, code, 0)
        monitoring.register_callback(self.tool, monitoring.events.PY_START, None)
        monitoring.free_tool_id(self.tool)


class Shim:
    """The assertion surface compare_spatial_records needs; raises on any difference."""

    def assertEqual(self, first, second, msg=None):  # noqa: N802 - unittest spelling
        if first != second:
            raise AssertionError(msg or 'logical spatial records differ')


def new_store(path, budget):
    """A dedicated raw store on the fixture's own WorkBudget (compact persistence requires it)."""
    import i02_workflow_fixtures as F2
    from atlas_tectonics.storage import ArrayStore, Compression
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return ArrayStore(path, F2.limits(), Compression(codec='raw'), budget=budget)


@contextmanager
def funded_collar_fixture():
    """private_heat_native_joined_fixture_r2.funded_collar_fixture, verbatim in meaning."""
    import test_integration_collar_geometry as G
    from atlas_tectonics.constitutive import BoussinesqMaterial
    from atlas_tectonics.regional_collar3d import PreparedRegionalCollar3D
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(BUDGET_BYTES)
    source = list(G.F.physical_source(budget))
    source[-1] = (-.5, 1., -2.)
    source = tuple(source)
    volume_map = G.F.physical_map(source, budget)
    material = BoussinesqMaterial('test:physical-density', 'synthetic-control',
                                  1.1, 1., .1, 0., 1., 0., 0., (1., 2.))
    with G.F.prepare(source[4], budget, material) as native, G.F.physical_owner(
            native, source, volume_map, budget) as owner:
        with PreparedRegionalCollar3D(native, volume_map, ((1, 1),)*3, budget=budget) as collar:
            funding = G.fund(source, owner, collar, budget)
            yield source, owner, collar, budget, funding


@contextmanager
def actual_spatial_fixture():
    """private_heat_native_joined_fixture_r2.actual_spatial_fixture, verbatim in meaning."""
    from threadpoolctl import threadpool_limits
    import test_integration_spatial_ale as ALE
    from test_regional_collar3d import native_driving
    from atlas_tectonics.regional_collar3d import RigidCollarMotion
    from atlas_tectonics.integration_collar_geometry import _partition
    with threadpool_limits(1), funded_collar_fixture() as (source, owner, collar, budget, funding):
        parent = collar.initial_state_from_funding(funding, owner)
        omega, dt = (0., 0., 1/64), Q(1, 64)
        wall = ALE.W.measure_walls(funding, source[0], collar,
            parent_state_id='initial-spatial-source', start_time_s=source[1].time_s,
            end_time_s=Q(source[1].time_s)+dt, angular_velocity_rad_s=omega,
            max_volume_error_m3=Q(1, 10000), max_leaves=256, budget=budget)
        motion = RigidCollarMotion(omega, 'test:actual prescribed common rigid motion')
        stage = collar.source_flow_stage(parent, float(dt), rigid_motion=motion, wall_measures=wall,
            **native_driving(collar.interior_velocity(motion)))
        boxes = collar.cell_geometries()
        base = boxes[0]
        radius = Q(source[0].network.sphere.radius_m)
        offset = tuple(sum(base.basis[k][j]*base.origin_m[k] for k in range(3)) for j in range(3))
        lines = tuple(tuple(sorted({-radius-offset[j], -offset[j], radius-offset[j],
            *(v for box in boxes for v in (box.lower_m[j], box.upper_m[j]))})) for j in range(3))
        bounds = ALE.A.enclose_spatial_ale(funding, source[0], collar, wall, stage, grid_lines=lines,
            max_volume_error_m3=32*radius**3, max_leaves=64, budget=budget)
        record = bounds.record()
        starts = {}
        for remainder in funding.exterior_remainder():
            key = [remainder['patch_id'], remainder['sublayer']]
            rows = [r for r in record['cells'] if r.get('source_key') == key]
            values = _partition([tuple(map(ALE.W._decode, r['start_volume_bounds_m3'])) for r in rows],
                                ALE.W._decode(remainder['stocks']['volume_m3']))
            starts.update((r['cell_id'], v) for r, v in zip(rows, values, strict=True))
        for row in record['cells']:
            if row['kind'] == 'collar':
                starts[row['cell_id']] = boxes[row['index']].volume_m3
        case = dict(source=source, owner=owner, collar=collar, budget=budget, funding=funding,
            parent=parent, wall=wall, stage=stage, bounds=bounds, starts=starts, graph=None,
            grid_lines=lines, boxes=boxes)
        del parent, wall, stage, bounds, starts, boxes, record, rows, values
        yield case


def next_interval(case, workflow):
    """test_i04_spatial_workflow.next_interval, reading the carried trajectory through the
    composed logical-record accessor (an indexed state has no expanded record())."""
    import spatial_indexed_patch as SIP
    import test_i04_spatial_workflow as FLOW
    from test_regional_collar3d import native_driving
    from atlas_tectonics import integration_spatial_ale as A
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.regional_collar3d import RigidCollarMotion
    dt, omega = Q(1, 64), (0., 0., 1/64)
    outer = workflow.exterior_state
    logical = SIP.logical_record(outer)
    prior = json.loads(json.dumps(logical['trajectory']['segments']))
    del logical
    wall = W.measure_walls(case['funding'], case['source'][0], case['collar'],
        parent_state_id=outer.state_id, start_time_s=outer.time_s, end_time_s=Q(outer.time_s)+dt,
        angular_velocity_rad_s=omega, prior_trajectory=prior,
        max_volume_error_m3=Q(1, 10000), max_leaves=256, budget=case['budget'])
    motion = RigidCollarMotion(omega, 'test:actual prescribed common rigid motion')
    source = workflow.source_flow_stage(float(dt), wall_measures=wall, rigid_motion=motion,
        **native_driving(case['collar'].interior_velocity(motion)))
    radius = Q(case['source'][0].network.sphere.radius_m)
    bounds = A.enclose_spatial_ale(case['funding'], case['source'][0], case['collar'], wall, source,
        grid_lines=case['grid_lines'], max_volume_error_m3=32*radius**3,
        max_leaves=64, budget=case['budget'])
    return source, bounds, FLOW.thermal_mesh(case, wall, 'end'), wall


def hexed(array):
    return dict(dtype=array.dtype.str, shape=list(array.shape), hex=array.tobytes(order='C').hex())


def snapshot_types(snapshot):
    return dict(snapshot=type(snapshot).__name__, metadata=type(snapshot._metadata).__name__)


def expected_consumer_sources():
    """Exactly what the composed cold binding demands of a committed heat reference."""
    import private_heat_restored_binding_ram_context_r1 as CTX
    return {name: CTX._PINS[name] for name in (
        'private_heat_native_issuer_r12.py', 'private_heat_checkpoint_consumer_r9.py',
        'private_heat_forward_kernel_r13.py', 'private_heat_grouped_account_r1.py',
        'private_heat_joined_consumer_r6.py')}


def summarise_heat(heat, label, seconds):
    import private_heat_joined_consumer_r6 as J
    call = heat._call
    owner, step, mesh, snapshot = call._origin_objects
    geometry = call._geometry
    reference = heat.reference()
    return dict(label=label, seconds=round(seconds, 3), type=type(heat).__name__,
        live_joined_heat=type(heat) is J.LiveJoinedHeat, result_id=heat.result_id, call_id=call.call_id,
        call_fixture=call._fixture, header=heat.header(), descriptor=heat.descriptor(),
        plan=heat.plan_descriptor(), reference=reference,
        consumer_sources_match_ram_pins=reference['consumer_sources'] == expected_consumer_sources(),
        call_meta=call._snapshot.descriptor(),
        call_arrays={name: hexed(call._snapshot.array(name)) for name in call._snapshot.array_names},
        arrays={name: hexed(heat.array(name)) for name in heat.array_names},
        mesh=dict(type=type(mesh).__name__, is_compact=mesh.is_compact, geometry_id=mesh.geometry_id),
        geometry=dict(type=type(geometry).__name__, encoded_is_none=geometry._encoded is None,
                      indexed=getattr(geometry, '_indexed', None) is not None, geometry_id=geometry.geometry_id,
                      cells=len(geometry._cells), faces=len(geometry._face_ids)),
        origin=dict(owner=type(owner).__name__, step=type(step).__name__, snapshot_is_result=snapshot is step.result._snapshot,
            result=snapshot_types(step.result._snapshot), parent=snapshot_types(step.parent._snapshot),
            source_inventory=snapshot_types(step.source.inventory),
            native_source_inventory=snapshot_types(step.source.source_stage.inventory),
            source_parent_native=snapshot_types(step.source.parent.native_state),
            source_parent_fields=snapshot_types(step.source.parent.fields)))


def worker_report():
    import private_heat_functionals_parallel_r1 as PAR
    report = PAR.report()
    return dict(workers=report['workers'], totals=report['totals'],
                calls=[{k: call.get(k) for k in ('faces', 'to_reconstruct', 'configured', 'workers', 'collected',
                                                 'in_caller', 'fallback', 'restarted', 'seconds')}
                       for call in report['calls']], fallbacks=report['fallbacks'])


def time_metric(geometry, repeats=5):
    import private_heat_indexed_runtime as INDEXED
    import mesh_tables as MT
    values = []
    for _ in range(repeats):
        started = time.perf_counter()
        identity = INDEXED.metric_identity(geometry)
        values.append(time.perf_counter()-started)
    view = getattr(geometry, '_indexed', None)
    if view is None:
        size = len(geometry._encoded)
    else:
        size = sum(len(part) for part in MT.CompactMesh.iter_legacy_json(view))
    return dict(indexed=view is not None, identity=identity, matches=identity == geometry.geometry_id,
                logical_json_bytes=size, seconds=[round(v, 6) for v in values],
                median_seconds=round(sorted(values)[len(values)//2], 6))


def time_indexed_identity(snapshot, repeats=3):
    """Full logical identity of an indexed spatial snapshot (streams its compact mesh)."""
    import spatial_indexed_patch as SIP
    import mesh_tables as MT
    values = []
    for _ in range(repeats):
        started = time.perf_counter()
        identity = SIP.snapshot_identity(snapshot)
        values.append(time.perf_counter()-started)
    return dict(matches=identity == snapshot.result_id, seconds=[round(v, 6) for v in values],
                median_seconds=round(sorted(values)[len(values)//2], 6),
                mesh_logical_json_bytes=sum(len(part) for part in MT.CompactMesh.iter_legacy_json(snapshot._mesh)))


def stream_codes():
    import private_heat_indexed_runtime as INDEXED
    import spatial_indexed_patch as SIP
    import mesh_tables as MT
    return dict(metric_identity=INDEXED.metric_identity.__code__,
                indexed_snapshot_identity=SIP._checked_identity.__code__,
                compact_iter_legacy_json=MT.CompactMesh.iter_legacy_json.__code__)


def retained_collar_state(collar, state, budget):
    """Re-issue the SAME collar state with retained-owner snapshot bytes, as native_transfer
    issues the migrated native/collar snapshots (regional_execution retained_owner)."""
    import native_transfer as NT
    from atlas_tectonics.regional_collar3d import RegionalCollarState
    from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
    native, fields = state.native_state, state.fields
    size = (native.nbytes+fields.nbytes+4096+
            1024*(len(native.array_names)+len(fields.array_names)))
    allocation = NT._Allocation(budget, size, category='w4-retained-collar-emulation')
    new_native = RegionalMechanicalSnapshot(native.descriptor(), {k: native.array(k) for k in native.array_names},
                                            retained_owner=allocation)
    new_fields = RegionalMechanicalSnapshot(fields.descriptor(), {k: fields.array(k) for k in fields.array_names},
                                            retained_owner=allocation)
    result = RegionalCollarState(new_fields, new_native)
    collar._native._fields(new_native)        # the checks native_transfer runs on its issue
    collar._fields(result)
    collar._exterior_bound(result, None)
    if (new_native.result_id != native.result_id or new_fields.result_id != fields.result_id or
            result.result_id != state.result_id):
        raise AssertionError('retained re-issue changed the collar identity')
    return result


def decoder_mechanism(retained, plain, budget):
    """Does the resources r4 decoder refuse retained-owner bytes where it IS reached?"""
    import private_heat_native_issuer_r12 as I
    import private_heat_restored_binding_ram_context_r1 as CTX
    out = {}
    for label, call in (('issuer_snapshot_identity', lambda s: I._snapshot_identity(s, budget)),
                        ('ram_context_snapshot', lambda s: CTX._snapshot(s, budget, None))):
        for kind, state in (('retained', retained), ('plain', plain)):
            try:
                value = call(state.native_state)
            except Exception as error:  # the refusal itself is the observation
                out[label+':'+kind] = 'refused: '+type(error).__name__+': '+str(error)[:200]
            else:
                out[label+':'+kind] = ('accepted' if value in (None, state.native_state.result_id)
                                       else 'accepted-different-identity')
    out['retained_metadata_type'] = type(retained.native_state._metadata).__name__
    return out


def refusal(error):
    """A refusal as data: type, message and the innermost frames (file:line function)."""
    frames = traceback.extract_tb(error.__traceback__)[-8:]
    return dict(error=type(error).__name__+': '+str(error)[:400],
                frames=['%s:%d %s' % (Path(f.filename).name, f.lineno, f.name) for f in frames])


_FROZEN_GATE = ("    if type(value).__module__ == 'private_heat_restored_binding_r9':\n"
                "        from private_heat_restored_binding_r9 import RestoredHeatBinding\n")
_DIAGNOSTIC_GATE = ("    if type(value).__module__ == 'private_heat_restored_binding_ram_context_r1':\n"
                    "        from private_heat_restored_binding_ram_context_r1 import RestoredHeatBinding\n")


def apply_diagnostic_fix():
    """IN-MEMORY DIAGNOSTIC ONLY, never a source change and never evidence for the frozen tree.

    Rebinds private_heat_joined_consumer_r6.validate_saved_exchange in this process
    from its own composed text with the one proposed two-line change, so the rest of
    the cold seam can be exercised after the frozen tree has refused at that gate.
    """
    import ast
    import private_heat_joined_consumer_r6 as J
    text = Path(J.__file__).read_text(encoding='utf8')
    if text.count(_FROZEN_GATE) != 1:
        raise AssertionError('frozen binding-module gate not found exactly once; no diagnostic applied')
    tree = ast.parse(text.replace(_FROZEN_GATE, _DIAGNOSTIC_GATE))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'validate_saved_exchange')
    before = J.validate_saved_exchange
    exec(compile(ast.Module(body=[node], type_ignores=[]),
                 J.__file__+' [W4 in-memory diagnostic]', 'exec'), vars(J))
    return dict(applied=J.validate_saved_exchange is not before,
                file_sha256_unchanged=J.source_bindings()['private_heat_joined_consumer_r6.py'] == J._SELF_SHA,
                change='validate_saved_exchange: binding-module gate private_heat_restored_binding_r9 -> '
                       'private_heat_restored_binding_ram_context_r1 (module test and import)')


def run_legacy(execution):
    import private_heat_joined_consumer_r6 as J
    import test_i04_spatial_workflow as FLOW
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    from atlas_tectonics.integration_spatial_owner import PreparedSpatialOwner
    phase('fixture-start')
    with actual_spatial_fixture() as case:
        phase('fixture-native-source-bootstrap-ale')
        budget, collar, funding = (case[k] for k in ('budget', 'collar', 'funding'))
        mesh0 = FLOW.thermal_mesh(case, case['wall'], 'start')
        allowances = FLOW.allowances(case)
        with PreparedSpatialOwner(funding, collar, case['bounds'], mesh0, method='implicit-upwind',
                max_projection_errors=allowances, budget=budget, heat_method=J.METHOD) as exterior:
            for name in ('stage', 'bounds', 'graph', 'parent', 'wall', 'starts', 'boxes'):
                case.pop(name)
            del mesh0
            phase('spatial-owner')
            with new_store(WORKDIR/'store'/'native-joined.sqlite', budget) as store, CollarWorkflow.create(
                    store, collar, case['owner'], funding, budget=budget, exterior_owner=exterior) as workflow:
                phase('workflow-root')
                RESULT['root'] = dict(workflow_id=workflow.workflow_id, initial_state_id=workflow.exterior_state.state_id,
                    initial=snapshot_types(workflow.exterior_state._snapshot),
                    compact_root=('compact_mesh' in store.metadata(json.loads(workflow._root)['key'])['exterior_state']))
                source, bounds, mesh, wall = next_interval(case, workflow)
                metric = mesh.record()
                boundary = {row['face_id']: ('power', 0.) for row in metric['faces'] if len(row['owners']) == 1}
                RESULT['setup'] = dict(native_cells=list(collar._native.cells), collar_cells=list(collar.cells),
                    thermal_cells=len(metric['cells']), physical_faces=len(metric['faces']),
                    boundary_faces=len(boundary), mesh_geometry_id=mesh.geometry_id,
                    collar_plan_id=collar.plan_id, funding_id=funding.funding_id, owner_id=exterior.owner_id,
                    source_flow_stage_id=source.result_id, bounds_id=bounds.bounds_id)
                del metric
                phase('interval-arguments')
                started = time.monotonic()
                result = workflow.advance_spatial(source, bounds, mesh, wall_measures=wall,
                    heat_boundary=boundary, heat_execution=execution,
                    absolute_heat_residual_target=TARGET, cancel=cancelled)
                elapsed = time.monotonic()-started
                phase('advance-spatial-published')
                heat = result.exterior._heat
                RESULT['heat'] = summarise_heat(heat, 'A legacy parent, plain collar, legacy end mesh', elapsed)
                RESULT['published'] = dict(workflow_id=workflow.workflow_id, head_key=workflow._head['key'],
                    exterior_state_id=result.exterior.state.state_id, collar_result_id=result.state.result_id,
                    joined_heat_id=heat.result_id)
                RESULT['metric_identity'] = time_metric(heat._call._geometry)
                RESULT['workers'] = worker_report()
                del result, heat
                gc.collect()
                phase('legacy-done')


def run_indexed(execution):
    import private_heat_joined_consumer_r6 as J
    import spatial_indexed_patch as SIP
    import spatial_workflow_patch as SWP
    import test_i04_spatial_workflow as FLOW
    from atlas_tectonics.integration_exterior_mesh import ExteriorMesh
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    from atlas_tectonics.integration_spatial_owner import PreparedSpatialOwner
    phase('fixture-start')
    with actual_spatial_fixture() as case:
        phase('fixture-native-source-bootstrap-ale')
        budget, collar, funding = (case[k] for k in ('budget', 'collar', 'funding'))
        mesh0 = FLOW.thermal_mesh(case, case['wall'], 'start')
        allowances = FLOW.allowances(case)
        with PreparedSpatialOwner(funding, collar, case['bounds'], mesh0, method='implicit-upwind',
                max_projection_errors=allowances, budget=budget, heat_method=J.METHOD) as ordinary:
            definition = ordinary.descriptor()
            initial_record = ordinary.initial_state.record()
            initial_arrays = {k: v.copy() for k, v in ordinary.initial_state.arrays().items()}
            ordinary_initial_id = ordinary.initial_state.state_id
        for name in ('stage', 'bounds', 'graph', 'parent', 'wall', 'starts', 'boxes'):
            case.pop(name)
        del mesh0
        phase('ordinary-owner-closed')
        with ExitStack() as stack:
            store = stack.enter_context(new_store(WORKDIR/'store'/'native-joined.sqlite', budget))
            producer = SWP.producer(collar)
            view0, _ = SWP.convert_mesh(store, initial_record['thermal_mesh'],
                expected_geometry_id=initial_record['thermal_mesh_id'], source_producer=producer, budget=budget)
            exterior = PreparedSpatialOwner.from_saved(funding, collar, definition,
                dict(initial_record, thermal_mesh=view0), initial_arrays, budget=budget)
            stack.callback(exterior.close)
            del initial_record, initial_arrays, view0
            if (type(exterior.initial_state._snapshot) is not SIP.IndexedSpatialSnapshot or
                    exterior.initial_state.state_id != ordinary_initial_id or
                    exterior.owner_id != definition['owner_id']):
                raise AssertionError('compact-restored owner is not the same logical indexed initial state')
            phase('indexed-owner')
            workflow = stack.enter_context(CollarWorkflow.create(store, collar, case['owner'], funding,
                budget=budget, exterior_owner=exterior))
            root = store.metadata(json.loads(workflow._root)['key'])
            parent_state = workflow.exterior_state
            RESULT['root'] = dict(workflow_id=workflow.workflow_id, initial_state_id=parent_state.state_id,
                initial=snapshot_types(parent_state._snapshot), compact_root='compact_mesh' in root['exterior_state'])
            plain = workflow.state
            retained = retained_collar_state(collar, plain, budget)
            workflow._state = retained          # as restore_migrated_root installs base._native.state
            if workflow.state is not retained or workflow.exterior_state is not parent_state:
                raise AssertionError('workflow re-restored its head; the retained parent is not in use')
            RESULT['retained_parent'] = dict(native=snapshot_types(retained.native_state),
                fields=snapshot_types(retained.fields), result_id=retained.result_id,
                plain_result_id=plain.result_id)
            phase('retained-collar-parent')
            source, bounds, mesh, wall = next_interval(case, workflow)
            if source.parent is not retained:
                raise AssertionError('source stage was not built from the retained parent collar state')
            metric = mesh.record()
            boundary = {row['face_id']: ('power', 0.) for row in metric['faces'] if len(row['owners']) == 1}
            RESULT['setup'] = dict(native_cells=list(collar._native.cells), collar_cells=list(collar.cells),
                thermal_cells=len(metric['cells']), physical_faces=len(metric['faces']),
                boundary_faces=len(boundary), mesh_geometry_id=mesh.geometry_id,
                collar_plan_id=collar.plan_id, funding_id=funding.funding_id, owner_id=exterior.owner_id,
                source_flow_stage_id=source.result_id, bounds_id=bounds.bounds_id)
            end_record = metric
            del metric
            phase('interval-arguments')
            # B2: the genuine full route with the post-migration parent types.
            started = time.monotonic()
            result = workflow.advance_spatial(source, bounds, mesh, wall_measures=wall,
                heat_boundary=boundary, heat_execution=execution,
                absolute_heat_residual_target=TARGET, cancel=cancelled)
            elapsed = time.monotonic()-started
            phase('advance-spatial-published')
            heat = result.exterior._heat
            RESULT['advance_heat'] = summarise_heat(heat, 'B2 indexed parent, retained collar parent, legacy end mesh',
                                                    elapsed)
            RESULT['published'] = dict(workflow_id=workflow.workflow_id, head_key=workflow._head['key'],
                exterior_state_id=result.exterior.state.state_id, collar_result_id=result.state.result_id,
                joined_heat_id=heat.result_id, store=str(WORKDIR/'store'/'native-joined.sqlite'),
                published_state=snapshot_types(result.exterior.state._snapshot))
            RESULT['metric_identity_legacy'] = time_metric(heat._call._geometry)
            # B1: the SAME owner and transport stage, end mesh as a compact store view.
            _, step, legacy_mesh, _ = heat._call._origin_objects
            scratch = stack.enter_context(new_store(WORKDIR/'scratch'/'compact-heat.sqlite', budget))
            view, _ = SWP.convert_mesh(scratch, end_record, expected_geometry_id=legacy_mesh.geometry_id,
                                       source_producer=producer, budget=budget)
            del end_record
            compact = ExteriorMesh.from_compact(view, budget=budget)
            del view
            refusals = {}
            try:
                compact.record()
            except Exception as error:
                refusals['compact_mesh_record'] = type(error).__name__+': '+str(error)[:160]
            else:
                refusals['compact_mesh_record'] = 'ACCEPTED'
            phase('compact-end-mesh')
            started = time.monotonic()
            with Streams(stream_codes()) as streams:
                compact_heat = exterior.heat(step, compact, boundary=boundary, execution=execution,
                    absolute_residual_target=TARGET, checkpoint_store=scratch, cancel=cancelled)
            elapsed = time.monotonic()-started
            phase('compact-owner-heat')
            summary = summarise_heat(compact_heat, 'B1 same step, compact end mesh', elapsed)
            summary['streams_during_owner_call'] = dict(streams.counts)
            summary['same_step_object_as_B2'] = compact_heat._call._origin_objects[1] is step
            summary['same_owner_object_as_B2'] = compact_heat._call._origin_objects[0] is heat._call._origin_objects[0]
            try:
                compact_heat._call._geometry.record()
            except Exception as error:
                refusals['indexed_metric_record'] = type(error).__name__+': '+str(error)[:160]
            else:
                refusals['indexed_metric_record'] = 'ACCEPTED'
            summary['whole_export_refusals'] = refusals
            RESULT['compact_heat'] = summary
            RESULT['metric_identity_indexed'] = time_metric(compact_heat._call._geometry)
            RESULT['indexed_parent_identity'] = time_indexed_identity(parent_state._snapshot)
            # B3: the same stage, LEGACY end mesh, through the owner seam directly and
            # counted: the real-run route (indexed parent) without monitoring geometry.
            scratch_legacy = stack.enter_context(new_store(WORKDIR/'scratch'/'legacy-heat.sqlite', budget))
            started = time.monotonic()
            with Streams(stream_codes()) as streams:
                again = exterior.heat(step, legacy_mesh, boundary=boundary, execution=execution,
                    absolute_residual_target=TARGET, checkpoint_store=scratch_legacy, cancel=cancelled)
            RESULT['legacy_mesh_owner_heat'] = dict(seconds=round(time.monotonic()-started, 3),
                result_id=again.result_id, call_id=again._call.call_id, streams=dict(streams.counts),
                arrays_equal_B2=sorted(again.array_names) == sorted(heat.array_names) and all(
                    again.array(k).tobytes() == heat.array(k).tobytes() for k in heat.array_names))
            phase('legacy-owner-heat-counted')
            RESULT['decoder_mechanism'] = decoder_mechanism(retained, plain, budget)
            RESULT['workers'] = worker_report()
            del again, compact_heat, compact, step, legacy_mesh, heat, result
            gc.collect()
            # The same-process reopen the runner performs next: _refresh -> COLD.restore_checkpoint
            # -> PreparedSpatialOwner.validate_exchange -> J.validate_saved_exchange.
            started = time.monotonic()
            try:
                inspected = workflow.inspect()
            except Exception as error:
                RESULT['same_process_cold'] = dict(status='REFUSED', seconds=round(time.monotonic()-started, 3),
                                                   **refusal(error))
                del error
                gc.collect()
                phase('same-process-cold-refused')
                RESULT['same_process_cold_diagnostic'] = apply_diagnostic_fix()
                started = time.monotonic()
                inspected = workflow.inspect()
                RESULT['same_process_cold_diagnostic'].update(status='PASSED_WITH_IN_MEMORY_DIAGNOSTIC')
                target = 'same_process_cold_diagnostic'
            else:
                RESULT['same_process_cold'] = dict(status='PASSED')
                target = 'same_process_cold'
            RESULT[target].update(seconds=round(time.monotonic()-started, 3),
                intervals=inspected.get('intervals'),
                restored_collar_parent_is_retained=workflow.state is retained,
                head_collar=snapshot_types(workflow.state.native_state),
                head_exterior=snapshot_types(workflow.exterior_state._snapshot))
            phase('same-process-cold')
            del retained, plain, parent_state
            gc.collect()


def run_cold(execution):
    import partition_workflow_patch as PW
    import private_heat_indexed_runtime as INDEXED
    import spatial_indexed_patch as SIP
    import spatial_workflow_patch as SWP
    from atlas_tectonics import integration_private_heat_cold as COLD
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    from threadpoolctl import threadpool_limits
    B = json.loads(Path(ARGS['b_result']).read_text(encoding='utf8'))['published']
    phase('collar-start')
    with threadpool_limits(1), funded_collar_fixture() as (_, owner, collar, budget, funding):
        phase('funded-collar')
        with ExitStack() as stack:
            store = stack.enter_context(new_store(Path(B['store']), budget))
            # The independent reader's reopen on the frozen tree: open -> _refresh ->
            # COLD.restore_checkpoint -> validate_exchange -> J.validate_saved_exchange.
            started = time.monotonic()
            try:
                workflow = CollarWorkflow.open(store, B['workflow_id'], collar, owner, funding, budget=budget)
            except Exception as error:
                RESULT['frozen_open'] = dict(status='REFUSED', seconds=round(time.monotonic()-started, 3),
                                             **refusal(error))
                del error
                gc.collect()
                phase('frozen-open-refused')
                RESULT['diagnostic_fix'] = apply_diagnostic_fix()
                started = time.monotonic()
                workflow = CollarWorkflow.open(store, B['workflow_id'], collar, owner, funding, budget=budget)
                RESULT['diagnostic_open'] = dict(status='PASSED_WITH_IN_MEMORY_DIAGNOSTIC',
                                                 seconds=round(time.monotonic()-started, 3))
            else:
                RESULT['frozen_open'] = dict(status='OPENED', seconds=round(time.monotonic()-started, 3))
            stack.enter_context(workflow)
            phase('open-refresh-cold')
            head = workflow._head
            parent = store.metadata(head['parent_key'])
            state, collar_state, audit = workflow.exterior_state, workflow.state, workflow.source_audit
            RESULT['opened'] = dict(head_key=head['key'], intervals=workflow.inspect()['intervals'],
                exterior_state_id=state.state_id, collar_result_id=collar_state.result_id,
                head=snapshot_types(state._snapshot), parent_kind=parent['kind'],
                parent_compact='compact_mesh' in parent['exterior_state'])
            payload = PW.workflow_arrays(store, head['key'], budget=budget)
            records = {k: v for k, v in payload.items() if k.startswith('spatial-record:')}
            audit_arrays = {k.removeprefix('spatial-audit:'): v for k, v in payload.items()
                            if k.startswith('spatial-audit:')}
            del payload
            with workflow._spatial_restore_records(head['exterior_state'], head['exterior_advance'], records,
                                                   budget, store=store) as (_, exchange):
                rows = {}
                heat_names = sorted(k.removeprefix('joined-heat:') for k in audit_arrays if k.startswith('joined-heat:'))
                arguments = dict(parent=parent, head=head, collar_state=collar_state, source_audit=audit,
                                 exchange=exchange, audit_arrays=audit_arrays)
                logical = state.record()
                scratch = stack.enter_context(new_store(WORKDIR/'scratch'/'indexed-head.sqlite', budget))
                view, _ = SWP.convert_mesh(scratch, logical['thermal_mesh'], expected_geometry_id=logical['thermal_mesh_id'],
                                           source_producer=SWP.producer(collar), budget=budget)
                indexed = workflow._exterior_owner.restore(dict(logical, thermal_mesh=view), state.arrays())
                del view
                if type(indexed._snapshot) is not SIP.IndexedSpatialSnapshot or indexed.state_id != state.state_id:
                    raise AssertionError('indexed head is not the same logical published state')
                INDEXED.compare_spatial_records(Shim(), indexed, logical)
                RESULT['indexed_head_logical_bytes_equal'] = True
                del logical
                for label, spatial_state in (('C1 indexed parent, legacy head', state),
                                             ('C2 indexed parent, indexed compact head (M14)', indexed)):
                    gc.collect()
                    before = budget.reserved_bytes
                    started = time.monotonic()
                    with Streams(stream_codes()) as streams:
                        with COLD.restore_checkpoint(workflow, spatial_state=spatial_state, **arguments) as checkpoint:
                            binding = checkpoint.value
                            seconds = round(time.monotonic()-started, 3)
                            binding.validate_for(workflow._exterior_owner, spatial_state, collar_state, exchange,
                                                 audit_arrays=audit_arrays)
                            context = binding._context
                            try:
                                workflow._exterior_owner.validate_exchange(spatial_state, exchange,
                                    audit_arrays=audit_arrays, composed_checkpoint=checkpoint,
                                    collar_state=collar_state)
                            except Exception as error:
                                exchange_check = dict(status='REFUSED', **refusal(error))
                                del error
                            else:
                                exchange_check = dict(status='PASSED')
                            exchange_check['in_memory_diagnostic_active'] = 'diagnostic_fix' in RESULT
                            rows[label] = dict(seconds=seconds, binding_type=type(binding).__name__,
                                validate_exchange=exchange_check,
                                binding_module=type(binding).__module__, result_id=binding.result_id,
                                fixture_only=binding.fixture_only, descriptor=binding.descriptor(),
                                arrays={name: hexed(binding.array(name)) for name in heat_names},
                                parent=snapshot_types(context[1]._snapshot), head=snapshot_types(context[3]._snapshot),
                                mesh_is_compact=context[5].is_compact,
                                geometry=dict(type=type(binding._geometry).__name__,
                                              encoded_is_none=binding._geometry._encoded is None))
                            del binding, context
                    rows[label]['streams'] = dict(streams.counts)
                    gc.collect()
                    rows[label]['reserved_before'] = before
                    rows[label]['reserved_after'] = budget.reserved_bytes
                    phase('cold-'+label.split()[0])
                RESULT['stored_audit_arrays'] = {k.removeprefix('joined-heat:'): hexed(v) for k, v in audit_arrays.items()
                                                 if k.startswith('joined-heat:')}
                RESULT['cold'] = rows
                del indexed
            del state, collar_state, audit, audit_arrays, records, exchange
            gc.collect()


def main():
    spec = importlib.util.spec_from_file_location('run_prepared_restart', ARGS['runner'])
    RUN = importlib.util.module_from_spec(spec)
    sys.modules['run_prepared_restart'] = RUN
    spec.loader.exec_module(RUN)
    profile = RUN.RestartProfile.read(Path(ARGS['profile']), ARGS['profile_sha'])
    sources = RUN.RestartSources(profile)
    RESULT['proof'] = sources.verify()
    RESULT['launch_environment'] = {name: os.environ.get(name) for name in sorted(RUN.LAUNCH_ENV)}
    RESULT['interpreter_flags'] = {name: getattr(sys.flags, name) for name in (
        'isolated', 'safe_path', 'ignore_environment', 'no_user_site', 'dont_write_bytecode', 'hash_randomization')}
    with sources.selected():
        sources.check_paths()
        RESULT['sys_path_head'] = sys.path[:1+len(sources.import_roots)]
        import private_heat_functionals_parallel_r1 as PAR
        from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
        require_strict_execution()
        PAR.configure(workers=ARGS['workers'])
        phase('selected')
        with ExecutionContext('scipy') as execution:
            RESULT['execution_provenance'] = dict(execution.provenance)
            dict(legacy=run_legacy, indexed=run_indexed, cold=run_cold)[MODE](execution)
        imported = sources.check_imported()
        sources.check_paths()
        atlas = sorted(n for n, m in tuple(sys.modules.items()) if (n == 'atlas_tectonics' or n.startswith('atlas_tectonics.'))
                       and not Path(m.__file__).resolve().is_relative_to(sources.native_root/'atlas_tectonics'))
        RESULT['imports'] = dict(bound_workspace_sources=len(imported), atlas_outside_native_root=atlas,
            outside_selected_roots=sorted(n for n in imported if not any(
                (sources.workspace/n).resolve().is_relative_to(root) for root in (sources.native_root, *sources.import_roots))))
    RESULT['proof_after'] = sources.verify()
    RESULT['status'] = 'PASS_CHILD_COMPLETED'


try:
    main()
except BaseException as error:
    RESULT['status'] = 'FAILED'
    RESULT['error'] = type(error).__name__+': '+str(error)[:2000]
    RESULT['traceback'] = traceback.format_exc()[-12000:]
    save()
    print('W4CHILD FAILED '+RESULT['error'], flush=True)
    sys.exit(1)
save()
print('W4CHILD '+RESULT['status'], flush=True)
