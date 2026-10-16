"""M2 same-call control: verbatim r12 and compact r13 heat on ONE genuine call.

One genuine W4 owner/transport/mesh call is bound once. The verbatim r12
advance/_advance_verified (renamed advance_legacy_packaging, inserted before
the issuer's immutable implementation identity capture, exactly as
test_heat_ledger_issuer_patch does) and the compact r13 advance both run on
that same issued call, so cell/face ordering is identical by construction.
Required: complete canonical metadata bytes, result ID, every array and the
exact accounts equal. No identity guard is patched, no ID forged, no tolerance.

Two process phases (the issuer requires a fresh source-selected process):
  --prepare <dir> <live_memory 0|1>   compose the layout into <dir>
  --child <dir> <out.json>            run the control inside that layout

The composition differs from test_step7_bundle.write_layout only by the
inserted reference functions and, when the Step 8 helper inventory omits
live_composite.py (a pre-existing test_step7_bundle failure), by adding that
helper to the composed inventory for this control only.
"""
import ast
from contextlib import contextmanager
from fractions import Fraction as Q
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
T = HERE.parents[4]
H = HERE.parents[3]/'heat-repair-20261007'
LIVE_FIXTURE = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/'
                    'continuation-repair-20261013/optimisation-20261014/resumability-r1/composed-checks/w4_owner_heat_child.py')
FIXTURE = HERE.parent/'composed-checks/w4_owner_heat_child.py'
FIXTURE_SHA = '5a850e22790e23b25dbaa8ce99ead91e7eef264c9251d38110c8293f30ddfabb'
BUDGET_BYTES = 6 << 30
MARKER = '# Capture already imported dependencies ONCE, before a caller can request an\n'
EXACT_KEYS = ('exact_corrected_enthalpy_j', 'exact_retained_solver_residual_j',
              'exact_stock_projection_residual_j', 'exact_cell_storage_residual_j',
              'exact_paired_face_energy_j', 'exact_source_energy_j', 'exact_outward_boundary_energy_j',
              'independently_supplied_absolute_residual_target',
              'geometry_id', 'cell_ids', 'face_ids', 'state_id', 'plan_id', 'call_id')


def phase(name):
    print(name, flush=True)


def reference_functions(original):
    """Verbatim r12 advance/_advance_verified, renamed (test_heat_ledger_issuer_patch)."""
    tree = ast.parse(original)
    parts = []
    for name in ('advance', '_advance_verified'):
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        text = ast.get_source_segment(original, node)
        text = text.replace('_advance_verified', '_advance_legacy_packaging_verified')
        if name == 'advance':
            text = text.replace('def advance(', 'def advance_legacy_packaging(', 1)
        parts.append(text)
    return '\n\n'.join(parts)+'\n\n'


def prepare(directory, live_memory):
    sys.path[:0] = [str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'), str(HERE.parent),
                    str(HERE.parent/'endpoint-checkpoints'), str(HERE)]
    import private_heat_bundle as B
    import private_heat_indexed_runtime as P
    import test_private_heat_bundle_extended as OLD
    import test_step7_bundle as SB
    inventory_added = []
    prefix = 'unbound import in composed heat helpers: '
    for _ in range(32):
        _, inputs, external, ram, helpers, compact = SB.compact_inputs()
        try:
            helper_out, ram_out, report = B.construct_compact_successor(inputs, reference_root=H,
                reference_pins=B.REFERENCE_PINS, external=external, ram=ram, helpers=helpers,
                compact_helpers=compact, live_memory=live_memory)
            break
        except ValueError as error:
            # Only local compact helpers the Step 8 inventory omits are added,
            # and only to this control's composition; anything else refuses.
            text = str(error)
            name = text.rsplit(' imports ', 1)[-1]+'.py' if text.startswith(prefix) else None
            if name is None or not (HERE/name).is_file() or name in B.COMPACT_HELPERS:
                raise
            B.COMPACT_RUNTIME_HELPERS = B.COMPACT_RUNTIME_HELPERS+(name,)
            B.COMPACT_HELPERS = B.COMPACT_HELPERS+(name,)
            inventory_added.append(name)
    else:
        raise ValueError('composition inventory did not converge')
    names = [n for n in helper_out if Path(n).name == 'private_heat_native_issuer_r13.py']
    if len(names) != 1:
        raise ValueError('composed r13 issuer not found exactly once')
    issuer = helper_out[names[0]].decode()
    if issuer.count(MARKER) != 1:
        raise ValueError('reference declaration boundary changed')
    predecessor = P.issuer_source((H/'private_heat_native_issuer_r12.py').read_text(encoding='utf8'))
    composed_sha = sha256(issuer.encode()).hexdigest()
    issuer = issuer.replace(MARKER, reference_functions(predecessor)+MARKER)
    helper_out[names[0]] = issuer.encode()
    root, helper_dir, ram_dir = OLD.write_layout(directory, helper_out, ram_out)
    import spatial_transfer as TRANSFER
    import spatial_indexed_patch as INDEXED
    import exchange_record_patch as EXCHANGE
    import spatial_validation_patch as VALIDATION
    path = root/'atlas_tectonics/integration_spatial_owner.py'
    source = INDEXED.transform(TRANSFER.spatial_owner_source(path.read_text(encoding='utf8')))
    path.write_text(VALIDATION.owner_source(EXCHANGE.holder_source(source)), encoding='utf8', newline='\n')
    import heat_cold_patch as COLD
    import partition_workflow_transform as PARTITION
    import workflow_transfer as WORKFLOW
    path = root/'atlas_tectonics/integration_private_heat_cold.py'
    source = PARTITION.cold_source(WORKFLOW.private_heat_cold_source(path.read_text(encoding='utf8')))
    path.write_text(B.cold_binding_source(COLD.transform(source), report), encoding='utf8', newline='\n')
    paths = [str(root), str(helper_dir), str(ram_dir), str(H/'source/tectonics/tests')]
    info = dict(paths=paths, live_memory=live_memory, inventory_added_for_control=inventory_added,
                composed_r13_sha256_before_reference_insert=composed_sha,
                stages={k: v for k, v in report.items() if k == 'stages'} if isinstance(report, dict) else None)
    (Path(directory)/'control.json').write_text(json.dumps(info, indent=1, default=str), encoding='utf8')
    print(json.dumps(dict(prepared=str(directory), live_memory=live_memory,
                          inventory_added=inventory_added)), flush=True)


def first_difference(old, new, path=''):
    if type(old) is not type(new):
        return path or '<root>', 'type %s != %s' % (type(old).__name__, type(new).__name__)
    if isinstance(old, dict):
        for key in sorted(set(old) | set(new)):
            if key not in old or key not in new:
                return path+'/'+key, 'key only in '+('compact' if key in new else 'legacy')
            found = first_difference(old[key], new[key], path+'/'+key)
            if found:
                return found
        return None
    if isinstance(old, list):
        if len(old) != len(new):
            return path, 'length %d != %d' % (len(old), len(new))
        for at, (a, b) in enumerate(zip(old, new, strict=True)):
            found = first_difference(a, b, '%s[%d]' % (path, at))
            if found:
                return found
        return None
    return None if old == new else (path or '<root>', '%r != %r' % (str(old)[:120], str(new)[:120]))


def child(directory, out):
    info = json.loads((Path(directory)/'control.json').read_text(encoding='utf8'))
    sys.path[:0] = info['paths']
    raw = (FIXTURE if FIXTURE.is_file() else LIVE_FIXTURE).read_bytes()
    if sha256(raw).hexdigest() != FIXTURE_SHA:
        raise ValueError('original W4 fixture changed')
    text = raw.decode('utf8')
    tree = ast.parse(text)
    selected = []
    for name in ('funded_collar_fixture', 'actual_spatial_fixture'):
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        selected.append('@contextmanager\n'+ast.get_source_segment(text, node))
    fixtures = dict(contextmanager=contextmanager, Q=Q, BUDGET_BYTES=BUDGET_BYTES)
    exec(compile('\n\n'.join(selected), 'w4_owner_heat_child.py', 'exec'), fixtures)
    import psutil
    import private_heat_native_issuer_r13 as I
    import private_heat_joined_consumer_r6 as J
    import test_i04_spatial_workflow as FLOW
    import mesh_tables as MT
    from atlas_tectonics.integration_exterior_mesh import ExteriorMesh
    from content_cache import create_retained_scope
    from heat_ledger_tables import CompactHeatSnapshot
    from threadpoolctl import threadpool_limits
    process = psutil.Process()
    started = time.perf_counter()
    output = dict(schema='atlas.a3.same-call-heat-control.r1', live_memory=info['live_memory'],
                  inventory_added_for_control=info['inventory_added_for_control'])
    phase('actual source, funding and collar')
    with threadpool_limits(1), fixtures['actual_spatial_fixture']() as case:
        budget, collar, funding = (case[k] for k in ('budget', 'collar', 'funding'))
        initial_mesh = FLOW.thermal_mesh(case, case['wall'], 'start')
        with FLOW.PreparedSpatialOwner(funding, collar, case['bounds'], initial_mesh,
                method='implicit-upwind', max_projection_errors=FLOW.allowances(case), budget=budget,
                heat_method=J.METHOD) as owner:
            scope = create_retained_scope(budget, process_epoch='a3-same-call-control')
            owner._record_scope = scope
            parent = collar.initial_state_from_funding(funding, case['owner'])
            from types import SimpleNamespace
            route = SimpleNamespace(exterior_state=owner.initial_state,
                source_flow_stage=lambda duration, _parent=parent, **kw: collar.source_flow_stage(_parent, duration, **kw))
            phase('next genuine source, geometry and transport')
            source, bounds, mesh, wall = FLOW.next_interval(case, route)
            graph = owner.close_graph(owner.initial_state, source, bounds)
            step = owner.transport(owner.initial_state, source, graph)
            record = mesh.record()
            boundary = {row['face_id']: ('power', 0.) for row in record['faces'] if len(row['owners']) == 1}
            blobs = {}
            metadata, arrays = MT.pack_mesh(record, support_writer=blobs.__setitem__, budget=budget)
            view = MT.CompactMesh(metadata, arrays, support_reader=lambda identity, size: blobs[identity],
                expected_geometry_id=mesh.geometry_id, budget=budget)
            compact = ExteriorMesh.from_compact(view, budget=budget)
            del record, arrays, metadata
            with I.ExecutionContext('scipy') as execution:
                phase('one genuine owner call bind')
                call = I.bind_owner_call(owner, step, compact, boundary=boundary,
                    absolute_residual_target='1e-24', execution=execution)
                assert not call._fixture and call._origin_objects[0] is owner
                phase('verbatim r12 packaging on the issued call')
                t0 = time.perf_counter()
                old = I.advance_legacy_packaging(call)
                t1 = time.perf_counter()
                phase('compact r13 packaging on the same issued call')
                new = I.advance(call)
                t2 = time.perf_counter()
                assert type(new._snapshot) is CompactHeatSnapshot
                with new._snapshot.ledger as ledger, ledger.iter_json() as stream:
                    parts = []
                    for block in stream:
                        with block:
                            parts.append(block.value)
                compact_metadata = b''.join(parts)
                legacy_metadata = old._snapshot._metadata
                del parts
                names_equal = tuple(old.array_names) == tuple(new.array_names)
                arrays_equal = {name: old.array(name).tobytes() == new.array(name).tobytes()
                                for name in old.array_names}
                legacy_json, compact_json = json.loads(legacy_metadata), json.loads(compact_metadata)
                exact = {key: legacy_json.get(key) == compact_json.get(key) for key in EXACT_KEYS}
                difference = first_difference(legacy_json, compact_json)
                byte_offset = next((i for i, (a, b) in enumerate(zip(legacy_metadata, compact_metadata, strict=False))
                                    if a != b), None)
                checks = dict(result_id=old.result_id == new.result_id,
                    metadata_bytes=legacy_metadata == compact_metadata,
                    metadata_sha256=new._snapshot.metadata_identity.sha256 == sha256(legacy_metadata).hexdigest(),
                    metadata_length=new._snapshot.metadata_identity.canonical_bytes == len(legacy_metadata),
                    array_names=names_equal, arrays=all(arrays_equal.values()),
                    exact_accounts=all(exact.values()),
                    plan_descriptor=new.plan_descriptor() == json.loads(old._plan_definition),
                    snapshot_identity=I._snapshot_identity(new._snapshot, budget) == old.result_id)
                output.update(status='PASS' if all(checks.values()) else 'DIFFERS', checks=checks,
                    exact_account_equal=exact, arrays_equal=arrays_equal,
                    first_differing_field=None if difference is None else dict(path=difference[0], detail=difference[1]),
                    first_differing_metadata_byte=byte_offset,
                    legacy=dict(result_id=old.result_id, metadata_sha256=sha256(legacy_metadata).hexdigest(),
                                metadata_bytes=len(legacy_metadata), seconds=t1-t0),
                    compact=dict(result_id=new.result_id, metadata_sha256=new._snapshot.metadata_identity.sha256,
                                 metadata_bytes=new._snapshot.metadata_identity.canonical_bytes, seconds=t2-t1),
                    cell_count=view.cell_count, face_count=view.face_count,
                    actual_owner=type(owner).__name__, actual_transport=type(step).__name__,
                    genuine_forward_origin=legacy_json.get('genuine_forward_origin'),
                    issuer_sha256=sha256(Path(I.__file__).read_bytes()).hexdigest(),
                    numerical_kernel_sha256=sha256(Path(I.F.__file__).read_bytes()).hexdigest(),
                    arrays={name: sha256(new.array(name).tobytes()).hexdigest() for name in new.array_names},
                    source_fixture_sha256=FIXTURE_SHA)
                new._snapshot.close()
                del new, old, call, legacy_json, compact_json, legacy_metadata, compact_metadata
            del route, parent, step, source, bounds, graph, compact, view, mesh, wall
            scope.close()
        del initial_mesh
    memory = process.memory_info()
    output.update(elapsed_seconds=time.perf_counter()-started,
                  peak_working_set_bytes=getattr(memory, 'peak_wset', None))
    Path(out).write_text(json.dumps(output, indent=2, sort_keys=True), encoding='utf8')
    print(json.dumps(dict(status=output['status'], checks=output['checks'],
                          first_differing_field=output['first_differing_field'])), flush=True)


def main():
    if sys.argv[1] == '--prepare':
        prepare(Path(sys.argv[2]), sys.argv[3] == '1')
    elif sys.argv[1] == '--child':
        child(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit('usage: --prepare <dir> <0|1> | --child <dir> <out.json>')


if __name__ == '__main__':
    main()
