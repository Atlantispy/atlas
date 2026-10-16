"""Matched Step 8 common-rigid owner construction/advance/commit measurement.

The fixture is genuine native W4 machinery on a bounded synthetic geometry.
This is not IV2, a full workflow publication, migration or cold restart. Large
diagnostic record exports happen after the measured region, never beside it.
"""
import ast
from dataclasses import fields
from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager, nullcontext
from fractions import Fraction as Q
from hashlib import sha256
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
R = HERE.parent
T = HERE.parents[4]
H = HERE.parents[3]/'heat-repair-20261007'
FIXTURE = R/'composed-checks/w4_owner_heat_child.py'
FIXTURE_SHA = '5a850e22790e23b25dbaa8ce99ead91e7eef264c9251d38110c8293f30ddfabb'
BUDGET_BYTES = 6 << 30


def layout(directory, live):
    import test_step7_bundle as B
    import test_live_composition as CURRENT
    def selected():
        _, inputs, external, ram, helpers, compact = B.compact_inputs()
        return B.B.construct_compact_successor(inputs, reference_root=H,
            reference_pins=B.B.REFERENCE_PINS, external=external, ram=ram,
            helpers=helpers, compact_helpers=compact, live_memory=live)
    prior = B.successor
    B.successor = selected
    try:
        result = (CURRENT if live else B).write_layout(directory)
        if not live:
            # The pre-Step8 collar cannot consume an indexed mesh at all.
            # Both modes share this explicit compatibility bridge; its memory
            # improvement is excluded from the measured difference.
            import live_collar_patch as COLLAR
            path = result[0]/'atlas_tectonics/regional_collar3d.py'
            path.write_text(COLLAR.collar_source(path.read_text(encoding='utf8')), encoding='utf8', newline='\n')
        return result
    finally:
        B.successor = prior


def fixtures():
    raw = FIXTURE.read_bytes()
    if sha256(raw).hexdigest() != FIXTURE_SHA:
        raise ValueError('authentic W4 fixture bytes changed')
    text, selected = raw.decode('utf8'), []
    nodes = ast.parse(text).body
    for name in ('funded_collar_fixture', 'actual_spatial_fixture', 'next_interval'):
        node = next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name)
        source = ast.get_source_segment(text, node)
        if name != 'next_interval':
            source = '@contextmanager\n'+source
        else:
            anchor = "return source, bounds, FLOW.thermal_mesh(case, wall, 'end'), wall"
            if source.count(anchor) != 1:
                raise ValueError('fixture endpoint mesh boundary changed')
            source = source.replace(anchor, 'return source, bounds, wall')
        selected.append(source)
    namespace = dict(contextmanager=contextmanager, Q=Q, BUDGET_BYTES=BUDGET_BYTES, json=json)
    exec(compile('\n\n'.join(selected), str(FIXTURE), 'exec'), namespace)
    return namespace


def digest_arrays(arrays):
    return {name: dict(dtype=array.dtype.str, shape=list(array.shape), bytes=array.nbytes,
                       sha256=sha256(array.tobytes(order='C')).hexdigest())
            for name, array in sorted(arrays.items())}


def endpoint_mesh(case, wall, scope, live):
    import test_i04_spatial_workflow as FLOW
    import mesh_tables as M
    from atlas_tectonics import integration_exterior_mesh as E
    if live:
        radius = Q(case['source'][0].network.sphere.radius_m)
        return E.build_exterior_mesh(case['funding'], case['source'][0], wall,
            grid_lines=case['grid_lines'], max_geometry_volume_error_m3=32*radius**3/3,
            max_leaves=64, budget=case['budget'], endpoint='end', compact_context={'scope': scope})
    native = FLOW.thermal_mesh(case, wall, 'end')
    record, blobs = native.record(), {}
    metadata, arrays = M.pack_mesh(record, support_writer=blobs.__setitem__, budget=case['budget'])
    view = M.CompactMesh(metadata, arrays, support_reader=lambda identity, size: blobs[identity],
        expected_geometry_id=native.geometry_id, budget=case['budget'])
    return E.ExteriorMesh.from_compact(view, budget=case['budget'])


def diagnostic_record(path, value):
    """Stream an owned logical record after measurement, retaining no copy."""
    from record_views import RecordRef
    from record_tables import canonical, RecordCodec
    if type(value) is dict and any(isinstance(child, RecordRef) for child in value.values()):
        scope = next(child.scope for child in value.values() if isinstance(child, RecordRef))
        packed = RecordCodec().pack_record(value, record_schema='atlas.step8.diagnostic.v1', scope=scope, check=lambda: None)
        with packed.root() as root:
            result = diagnostic_record(path, root)
        packed.close()
        return result
    if isinstance(value, RecordRef):
        identity = value.identity()
        with path.open('wb') as output, value.iter_json(max_chunk_bytes=65536) as parts:
            for part in parts:
                with part:
                    output.write(part.value)
        return dict(bytes=identity.canonical_bytes, sha256=identity.sha256)
    raw = canonical(value)
    path.write_bytes(raw)
    return dict(bytes=len(raw), sha256=sha256(raw).hexdigest())


def owner_run(paths, destination, live):
    sys.path[:0] = paths
    import psutil
    from threadpoolctl import threadpool_limits
    import test_i04_spatial_workflow as FLOW
    import private_heat_native_issuer_r13 as I
    import private_heat_joined_consumer_r6 as J
    import spatial_indexed_patch as SIP
    import spatial_records_patch as RECORDS
    import live_spatial_patch as LIVE
    from content_cache import create_retained_scope
    from interval_store_set import IntervalStoreSet
    from atlas_tectonics.storage import ArrayStore
    from compact_contracts import SegmentRef
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    process, checkpoints = psutil.Process(), []
    started = time.perf_counter()
    scope = budget = None
    def checkpoint(name):
        info = process.memory_info()
        stats = None if scope is None else scope.stats()
        row = dict(stage=name, elapsed_seconds=time.perf_counter()-started,
            rss_bytes=info.rss, private_bytes=getattr(info, 'private', None),
            process_peak_rss_bytes=getattr(info, 'peak_wset', None),
            logical_reserved_bytes=None if budget is None else budget.reserved_bytes,
            logical_peak_bytes=None if budget is None else budget.peak_reserved_bytes,
            retained=None if stats is None else {field.name: (dict(value) if isinstance(value := getattr(stats, field.name), Mapping) else value)
                                                for field in fields(stats)},
            disk_bytes=sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()))
        checkpoints.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != 'retained'}), flush=True)
    fixture = fixtures()
    checkpoint('setup-start')
    with threadpool_limits(1), fixture['actual_spatial_fixture']() as case:
        budget, collar, funding = (case[k] for k in ('budget', 'collar', 'funding'))
        initial_mesh = FLOW.thermal_mesh(case, case['wall'], 'start')
        with FLOW.PreparedSpatialOwner(funding, collar, case['bounds'], initial_mesh,
                method='implicit-upwind', max_projection_errors=FLOW.allowances(case),
                budget=budget, heat_method=J.METHOD) as owner:
            scope = create_retained_scope(budget, process_epoch='step8-owner-measurement')
            owner._record_scope = scope
            parent = collar.initial_state_from_funding(funding, case['owner'])
            route = SimpleNamespace(exterior_state=owner.initial_state,
                source_flow_stage=lambda duration, _parent=parent, **kw: collar.source_flow_stage(_parent, duration, **kw))
            stores = IntervalStoreSet.create_migration(str(destination/'catalog.json'),
                workflow_id='a'*64, scope=scope)
            candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
            numeric = ArrayStore(destination/'native.arrays.sqlite', candidate.limits, budget=budget)
            previous_gc = gc.isenabled()
            gc.disable()
            checkpoint('measured-start')
            with LIVE.construction(scope, budget=budget) if live else nullcontext():
                source, bounds, wall = fixture['next_interval'](case, route)
                checkpoint('fresh-bounds')
                mesh = endpoint_mesh(case, wall, scope, live)
                checkpoint('fresh-mesh')
                graph = owner.close_graph(owner.initial_state, source, bounds)
                checkpoint('closed-graph')
                step = owner.transport(owner.initial_state, source, graph)
                checkpoint('transport-solve')
                transport = collar.transport_from_spatial(source, step.result, graph,
                    method=owner.descriptor()['method'], finite_proposal=step.finite_proposal)
                from record_tables import Scratch
                boundary_owner = Scratch(budget, 65536+1024*mesh._compact.face_count)
                boundary = {}
                for index in range(mesh._compact.face_count):
                    face = mesh.face(index)
                    if len(face.value['owners']) == 1:
                        boundary[face.value['face_id']] = ('power', 0.)
                del face
                with I.ExecutionContext('scipy') as execution:
                    heat = owner.heat(step, mesh, boundary=boundary, execution=execution,
                        absolute_residual_target='1e-24', checkpoint_store=candidate)
                    checkpoint('heat-solve-and-checkpoint')
                    adopted = collar.heat_from_spatial(transport, heat, mesh)
                    native = collar.endpoint_from_transport(transport, adopted)
                    exterior = owner.finish(step, mesh, heat, native)
                checkpoint('joined-finish')
                saved = SIP.indexed_record(exterior.state)
                state = {key: value for key, value in saved.value.items() if key != 'thermal_mesh'}
                exchange = exterior.record()
                children = [exchange.without(('spatial_graph', 'transport', 'joined_heat'))]
                children.extend(exchange.field(key) for key in ('spatial_graph', 'transport', 'joined_heat'))
                rows = dict(zip(('exchange', 'graph', 'transport', 'heat'), children, strict=True), state=state)
                refs = RECORDS.publish_records(candidate, rows, budget=budget,
                    source_producer={'measurement': 'actual-W4-Step8', 'source_fixture_sha256': FIXTURE_SHA})
                checkpoint('compact-record-publication')
                payload = mesh._compact.storage_payload()
                metadata, mesh_arrays = payload.value
                numeric.put('d'*64, mesh_arrays, metadata)
                arrays = {}
                for prefix, values in (('spatial', exterior.state.arrays()), ('transport', step.result.arrays()),
                        ('native', native.state.native_state), ('collar', native.state.fields), ('heat', heat)):
                    if type(values) is not dict:
                        values = {name: values.array(name) for name in values.array_names}
                    arrays.update({prefix+':'+name: value for name, value in values.items()})
                numeric.put('e'*64, arrays, {'schema': 'atlas.step8.measured-component-commit.v1', 'records': refs})
                del arrays, values, payload, metadata, mesh_arrays
                root = SegmentRef.from_wire(refs['graph']['compact']['segment'])
                stores.promote(candidate.seal(root), expected_catalog_digest=stores.catalog_digest)
                checkpoint('numeric-commit-and-seal')
            measured_end = time.perf_counter()
            # Explicit diagnostic phase: copies/streams below are excluded from
            # the reported measured peak checkpoint and timed advance region.
            diagnostics = destination/'diagnostics'
            diagnostics.mkdir()
            logical = {name: diagnostic_record(diagnostics/(name+'.json'), value) for name, value in rows.items()}
            with heat._result._snapshot.ledger as ledger:
                logical['heat_ledger'] = diagnostic_record(diagnostics/'heat-ledger.json', ledger)
            with (diagnostics/'mesh.json').open('wb') as output:
                for part in mesh._compact.iter_legacy_json():
                    output.write(part)
            mesh_path = diagnostics/'mesh.json'
            logical['mesh'] = dict(bytes=mesh_path.stat().st_size, sha256=mesh.geometry_id)
            output = dict(status='PASS', live=live, source_fixture_sha256=FIXTURE_SHA,
                scope='authentic bounded common-rigid W4 construction, advance, compact records and numeric commit',
                full_workflow_publication=False, IV2=False, cold_restart=False, gc_disabled_during_measurement=True,
                admission_scope='bounded 6 GiB functional/performance fixture; not the full 12/1/10/16 GiB guard proof',
                baseline_shared_improvements=['current tuple-path heat package normalisation and guard repairs',
                                              'indexed collar consumer compatibility bridge'],
                measured_end_seconds=measured_end-started, checkpoints=checkpoints,
                counts=dict(native_cells=list(collar._native.cells), collar_cells=list(collar.cells),
                            thermal_cells=mesh._compact.cell_count, thermal_faces=mesh._compact.face_count),
                logical_records=logical, identities=dict(state=exterior.state.state_id, exchange=exterior.result_id,
                    graph=graph.geometry_id, transport=step.result.result_id, heat=heat.result_id),
                numeric_arrays=digest_arrays({name: value for prefix, values in
                    (('spatial', exterior.state.arrays()), ('transport', step.result.arrays()))
                    for name, value in ((prefix+':'+key, item) for key, item in values.items())}),
                heat_arrays=digest_arrays({name: heat.array(name) for name in heat.array_names}),
                native_arrays=digest_arrays({name: native.state.native_state.array(name)
                                            for name in native.state.native_state.array_names}),
                store_statistics=numeric.statistics(),
                source_hashes={name: sha256(Path(module.__file__).read_bytes()).hexdigest()
                    for name, module in (('issuer', I), ('joined', J), ('kernel', I.F), ('live_spatial', LIVE))})
            output['cleanup'] = 'pending'
            (destination/'result.json').write_text(json.dumps(output, indent=2, sort_keys=True), encoding='utf8')
            for child in children:
                child.close()
            exchange.close()
            del children, exchange, rows, state, saved
            numeric.close(); candidate.close(); stores.close()
            del exterior, native, adopted, heat, step, graph, mesh, bounds, source, wall, boundary, boundary_owner, transport
            del route, parent
            if previous_gc:
                gc.enable()
            # No collect is used as an ownership repair: released owners must
            # retire through ordinary reference lifetime before scope close.
            owner._record_scope = None
            scope.close()
            output['retained_after_close_bytes'] = scope.retained_budget.reserved_bytes
            if output['retained_after_close_bytes'] != 0:
                raise AssertionError('measurement scope leaked retained ownership')
            output['cleanup'] = 'PASS'
        del initial_mesh
    return output


def recover_diagnostics(destination):
    """Read completed commits after a diagnostic-only failure; never re-solve."""
    sys.path[:0] = [str(R.parent/'runtime-integration-r1/runtime-src'), str(R), str(H)]
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore
    from interval_store_set import IntervalStoreSet, LIMITS
    from content_cache import create_retained_scope
    import spatial_records_patch as RECORDS
    destination = Path(destination)
    budget = WorkBudget(BUDGET_BYTES)
    scope = create_retained_scope(budget, process_epoch='step8-measured-output-recovery')
    stores = IntervalStoreSet.open_catalog(destination/'catalog.json', scope=scope)
    numeric = ArrayStore(destination/'native.arrays.sqlite', LIMITS, budget=budget)
    refs = numeric.metadata('e'*64)['records']
    with RECORDS.open_records(stores, refs, budget=budget) as records:
        logical = {name: diagnostic_record(destination/'diagnostics'/(name+'.json'), value)
                   for name, value in records.items()}
        for value in records.values():
            value.close()
    del records, value
    import private_heat_snapshot_store_r4 as HEAT_STORE
    heat = json.loads((destination/'diagnostics/heat.json').read_text(encoding='utf8'))
    receipt = heat['checkpoint']
    held_heat = HEAT_STORE.open(stores, receipt, expected_result_id=heat['result_id'],
        bindings=receipt['metadata']['bindings'], scope=scope)
    with held_heat.value.ledger as ledger:
        logical['heat_ledger'] = diagnostic_record(destination/'diagnostics/heat-ledger.json', ledger)
    held_heat.value.close()
    held_heat.close()
    del held_heat
    arrays = digest_arrays(numeric.get('e'*64))
    mesh = numeric.metadata('d'*64)
    log = destination.with_suffix('.log').read_text(encoding='utf8')
    checkpoints = [json.loads(line) for line in log.splitlines() if line.startswith('{"stage":')]
    result = dict(status='MEASURED_STAGES_PASS_DIAGNOSTIC_RECOVERED', live=False,
        source_fixture_sha256=FIXTURE_SHA, checkpoints=checkpoints,
        measured_end_seconds=checkpoints[-1]['elapsed_seconds'],
        cleanup='unverified: original process stopped during post-measurement diagnostic export',
        gc_disabled_during_measurement=True, full_workflow_publication=False, IV2=False, cold_restart=False,
        admission_scope='bounded 6 GiB functional/performance fixture; not the full 12/1/10/16 GiB guard proof',
        baseline_shared_improvements=['current tuple-path heat package normalisation and guard repairs',
                                      'indexed collar consumer compatibility bridge'],
        logical_records=logical, mesh_metadata=mesh,
        numeric_arrays={name: value for name, value in arrays.items() if name.startswith(('spatial:', 'transport:'))},
        heat_arrays={name.removeprefix('heat:'): value for name, value in arrays.items() if name.startswith('heat:')},
        native_arrays={name.removeprefix('native:'): value for name, value in arrays.items() if name.startswith('native:')},
        all_committed_arrays=arrays,
        recovery='read-only canonical streams and array hashes from the completed sealed/numeric commits; no solve rerun')
    numeric.close(); stores.close()
    scope.close()
    result['diagnostic_recovery_retained_after_close_bytes'] = scope.retained_budget.reserved_bytes
    (destination/'result.json').write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf8')
    print(json.dumps({'recovered': str(destination/'result.json'), 'record_bytes': logical}), flush=True)


def compare_results(before, after, destination):
    """Compare committed tiny-fixture outputs, outside either measured run.

    Source-bound collar IDs differ between emitted layouts. Preserve raw hash
    differences and separately compare physical cells by their explicit index
    or stable exterior ID; never rewrite scientific records or source pins.
    """
    sys.path[:0] = [str(R.parent/'runtime-integration-r1/runtime-src'), str(R)]
    from atlas_tectonics.storage import ArrayStore
    from atlas_tectonics.resources import WorkBudget
    from interval_store_set import LIMITS
    pairs = []
    for path in (before, after):
        read = lambda name: json.loads((path/'diagnostics'/(name+'.json')).read_text(encoding='utf8'))
        result = json.loads((path/'result.json').read_text(encoding='utf8'))
        graph, transport, heat = (read(name) for name in ('graph', 'transport', 'heat-ledger'))
        def cell_key(row):
            return ('collar', row['index']) if row['kind'] == 'collar' else ('exterior', row['cell_id'])
        keys = {row['cell_id']: cell_key(row) for row in graph['cells']+graph['inactive_zero_measure_cells']}
        assert len(set(keys.values())) == len(keys)
        missing_ports = {value for field in ('original_face_intervals', 'selected_face_representatives')
            for row in graph[field] for key, value in row.items()
            if key in ('donor', 'receiver') and value is not None and value not in keys}
        # Recompute the unchanged native port identity formula, then demand an
        # exact hash match. These algebraic wall ports are intentionally absent
        # from the positive-volume graph cells after native closure.
        matched_ports = {}
        for row in graph['cells']:
            if row['kind'] != 'collar':
                continue
            for axis in range(3):
                for end in (0, 1):
                    for inward in (False, True):
                        value = dict(collar=row['cell_id'], axis=axis, end=end, inward=inward)
                        identity = sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                        if identity in missing_ports:
                            matched_ports[identity] = ('algebraic-port', row['index'], axis, end, inward)
        keys.update(matched_ports)
        with ArrayStore(path/'native.arrays.sqlite', LIMITS, budget=WorkBudget(1 << 30)) as store:
            arrays, mesh = store.get('e'*64), store.get('d'*64)
        ident = lambda index: mesh['id.bytes'][int(index)].tobytes().hex()
        heat_keys = {ident(row[0]): keys[ident(row[1])] for row in mesh['c.id']}
        order = dict(transport=[keys[value] for value in transport['cell_ids']],
                     heat=[heat_keys[value] for value in heat['cell_ids']])
        assert all(len(values) == len(set(values)) == 236 for values in order.values())
        pairs.append(dict(path=path, result=result, graph=graph, transport=transport, heat=heat,
                          arrays=arrays, mesh=mesh, heat_keys=heat_keys, keys=keys, order=order,
                          port_matches=len(matched_ports), port_requested=len(missing_ports)))
    a, b = pairs
    permutations = {kind: [b['order'][kind].index(key) for key in a['order'][kind]]
                    for kind in ('transport', 'heat')}
    array_checks = {}
    assert set(a['arrays']) == set(b['arrays'])
    for name, left in a['arrays'].items():
        right = b['arrays'][name]
        raw_equal = left.tobytes() == right.tobytes()
        kind = name.split(':', 1)[0]
        if kind in permutations:
            right = right[permutations[kind]]
        array_checks[name] = dict(raw_equal=raw_equal, mapped_equal=left.dtype == right.dtype and
            left.shape == right.shape and left.tobytes() == right.tobytes(), shape=list(left.shape))
    exact_transport = {}
    for name in ('exact_input_stocks', 'exact_stocks', 'binary_stock_projection_accounts', 'exact_projection_accounts'):
        left, right = a['transport'][name], b['transport'][name]
        if type(left) is dict and all(type(value) is list and len(value) == 236 for value in left.values()):
            right = {key: [values[index] for index in permutations['transport']] for key, values in right.items()}
        exact_transport[name] = left == right
    exact_heat = {}
    cell_fields = {'exact_cell_storage_residual_j', 'exact_corrected_enthalpy_j',
                   'exact_retained_solver_residual_j', 'exact_stock_projection_residual_j'}
    for name in a['heat']:
        if not name.startswith('exact_'):
            continue
        left, right = a['heat'][name], b['heat'][name]
        if name in cell_fields:
            assert len(left) == len(right) == 236
            right = [right[index] for index in permutations['heat']]
        exact_heat[name] = dict(equal=left == right,
            unequal_rows=sum(x != y for x, y in zip(left, right, strict=True)) if type(left) is list else None)
        if type(left) is list and left and type(left[0]) is list:
            values = lambda rows: [Q(int(row[0], 16), int(row[1], 16)) for row in rows]
            lq, rq = values(left), values(right)
            maximum = max((abs(x-y) for x, y in zip(lq, rq, strict=True)), default=Q(0))
            exact_heat[name].update(max_absolute_delta_j=float(maximum),
                max_absolute_delta_exact=[hex(maximum.numerator), hex(maximum.denominator)],
                binary64_values_equal=all(float(x) == float(y) for x, y in zip(lq, rq, strict=True)))
    skipped_cell_identity_fields = {'cell_id', 'physical_cell_id', 'start_geometry_instance_id', 'end_geometry_instance_id'}
    graph_checks = {}
    for field in ('cells', 'inactive_zero_measure_cells'):
        normalized = [{item['keys'][row['cell_id']]: {key: value for key, value in row.items()
                       if key not in skipped_cell_identity_fields} for row in item['graph'][field]} for item in pairs]
        graph_checks[field] = normalized[0] == normalized[1]
    for field in ('transfers', 'original_face_intervals', 'selected_face_representatives'):
        missing = [sorted({value for row in item['graph'][field] for key, value in row.items()
            if key in ('donor', 'receiver') and value is not None and value not in item['keys']}) for item in pairs]
        if any(missing):
            graph_checks[field] = dict(equal=None, unresolved_endpoint_ids=missing)
            continue
        normalized = []
        for item in pairs:
            rows = []
            for row in item['graph'][field]:
                values = {key: (item['keys'][value] if key in ('donor', 'receiver') and value is not None else value)
                          for key, value in row.items() if key != 'face_id'}
                rows.append(json.dumps(values, sort_keys=True))
            normalized.append(Counter(rows))
        graph_checks[field] = normalized[0] == normalized[1]
    def mesh_values(item):
        arrays = item['mesh']
        ident = lambda index: arrays['id.bytes'][int(index)].tobytes().hex()
        def integer(index):
            start, end = map(int, arrays['int.offset'][int(index):int(index)+2])
            return int(arrays['int.sign'][int(index)])*int.from_bytes(arrays['int.bytes'][start:end], 'little')
        def rational(index):
            if int(index) == (1 << 64)-1:
                return None
            return tuple(integer(value) for value in arrays['q.pair'][int(index)])
        cells = {item['heat_keys'][ident(row[0])]: tuple(map(rational, arrays['c.q'][index]))
                 for index, row in enumerate(arrays['c.id'])}
        faces = {}
        for index, face in enumerate(arrays['f.id']):
            owners = arrays['f.owner'][slice(*map(int, arrays['f.owner_offset'][index:index+2]))]
            vertices = arrays['f.vertex'][slice(*map(int, arrays['f.vertex_offset'][index:index+2]))]
            faces[ident(face)] = dict(quantities=tuple(map(rational, arrays['f.q'][index])),
                owners=tuple(item['heat_keys'][ident(arrays['c.id'][int(owner), 0])] for owner in owners),
                vertices=tuple(tuple(map(rational, vertex)) for vertex in vertices))
        return cells, faces
    (ac, af), (bc, bf) = map(mesh_values, pairs)
    mesh_checks = dict(cell_exact_quantities_equal=ac == bc, face_ids_equal=set(af) == set(bf),
        face_exact_quantities_equal=all(af[key]['quantities'] == bf[key]['quantities'] for key in af),
        ordered_face_vertices_equal=all(af[key]['vertices'] == bf[key]['vertices'] for key in af),
        ordered_face_owners_equal=all(af[key]['owners'] == bf[key]['owners'] for key in af),
        unordered_face_owners_equal=all(set(af[key]['owners']) == set(bf[key]['owners']) for key in af))
    checks = dict(arrays=array_checks, exact_transport=exact_transport, exact_heat=exact_heat, graph=graph_checks,
        mesh=mesh_checks, exact_native_port_hash_matches=[dict(requested=item['port_requested'], matched=item['port_matches']) for item in pairs])
    output = dict(schema='atlas.step8.owner-measurement-comparison.v1', before=str(before), after=str(after),
        input_sha256={str(path): sha256(path.read_bytes()).hexdigest() for base in (before, after)
            for path in [base/'result.json', base/'composition.json', base/'native.arrays.sqlite',
                         *sorted((base/'diagnostics').glob('*.json'))]},
        mapping='graph collar kind/index or stable exterior cell ID; heat mesh committed c.id logical-cell link',
        checks=checks, raw_logical_records_equal=False,
        limits=['Different emitted source identities change collar IDs and canonical ordering; complete record hashes differ.',
                'Exact heat residual ledger parity is not established: five exact row families differ after cell mapping.',
                'Native wall-port hashes are reconstructed only for diagnostic correspondence; original records and pins remain unchanged.',
                'Baseline measured stages passed; normal cleanup unverified after its diagnostic-only failure.',
                'The final fresh-mesh type/scope/ID guard-only addition is focused-tested, not timed in this candidate.',
                'This is a 236-cell component fixture, not IV2, full workflow publication or full OS admission proof.'])
    destination.write_text(json.dumps(output, indent=2, sort_keys=True), encoding='utf8')
    print(json.dumps(dict(comparison=str(destination), all_mapped_arrays_equal=all(
        row['mapped_equal'] for row in array_checks.values()), exact_transport=exact_transport,
        exact_heat={name: {key: value for key, value in row.items() if key != 'max_absolute_delta_exact'} for name, row in exact_heat.items()},
        mesh=mesh_checks, graph={name: (value if type(value) is bool else dict(equal=value['equal'],
            unresolved_endpoint_counts=[len(ids) for ids in value['unresolved_endpoint_ids']]))
            for name, value in graph_checks.items()})), flush=True)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--compare':
        compare_results(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
        return
    if len(sys.argv) > 1 and sys.argv[1] == '--recover':
        recover_diagnostics(sys.argv[2])
        return
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        result = owner_run(json.loads(sys.argv[2]), sys.argv[3], sys.argv[4] == 'after')
        Path(sys.argv[3], 'result.json').write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf8')
        return
    mode = sys.argv[1]
    if mode not in ('before', 'after'):
        raise ValueError('select exactly one matched child: before or after')
    destination = Path(sys.argv[2]).absolute()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='step8-owner-'+mode+'-', dir=T/'_t') as directory:
        root, helpers, ram, report = layout(directory, mode == 'after')
        paths = [str(root), str(helpers), str(ram), str(H/'source/tectonics/tests')]
        (destination/'composition.json').write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf8')
        environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
        environment.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1',
                           TMP=str(T/'_t'), TEMP=str(T/'_t'))
        subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--child', json.dumps(paths),
                        str(destination), mode], cwd=directory, env=environment, check=True, timeout=900)


if __name__ == '__main__':
    main()
