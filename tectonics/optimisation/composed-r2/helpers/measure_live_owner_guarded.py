"""Guarded Step 8 representative run: the genuine W4 owner in ONE process.

Construction, advance, heat, finish, compact publication, numeric commit and
seal run under the pinned continuation guardian (kill-on-close Windows job,
unchanged 12 GiB tree RSS and 1 GiB free-memory floor), with the unchanged
16 GiB logical budget, 256 MiB retained scope and 256 MiB builder child
asserted in-process. While every live structure is still held, the committed
interval is re-read the way a continuing workflow does (fresh catalog open,
record open with identity proofs, heat checkpoint open, numeric read-back).
A release ladder then drops one structure family at a time and records what
each release returns, so each structure is seen at its real overlap.

Every arm runs one shared composition per exact compact source set (same
bytes and same paths: the heat issuer binds module paths and upper-case
constants of its compact dependencies into each heat call's metadata).
--route old and --set MODULE.CONSTANT=INT choose test-only Step 8 switches
(SWITCHES), set before that identity capture so it records them honestly:
arms with equal captured switches must be equal in every identity, record and
array; arms that differ in a captured switch may differ only in heat-derived
identifiers, while graph, transport and every array stay equal. The
publication bound (spatial_record_recipes, outside the captured set) leaves
every identity equal, so v2 publication is a fully same-input comparison.

Start gate: Step 8 capacity tests use an explicit, recorded setting (Michael,
15 October 2026): the previous test's measured peak plus the 1 GiB floor and
a stated margin, starting at 4 GiB. The 10 GiB gate for real interval runs is
unchanged and not used here. This is not IV2 and not a full CollarWorkflow
publication; the receipt states that scope.
"""
import argparse
import gc
import json
import os
import subprocess
import sys
import time
import traceback
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
R = HERE.parent
T = HERE.parents[4]
H = HERE.parents[3]/'heat-repair-20261007'
PYTHON = T/'.r44-env/Scripts/python.exe'
GUARDS = {'rss_bytes': 12 << 30, 'free_floor_bytes': 1 << 30, 'logical_budget_bytes': 16 << 30,
          'retained_scope_bytes': 256 << 20, 'builder_child_bytes': 256 << 20,
          'real_interval_start_gate_bytes': 10 << 30}
STEP8_TEST_START_GATE = 4 << 30
MAX_SECONDS = 1800
STORE_PREFIXES = ('catalog', 'interval-', 'native.arrays')
# Test-only Step 8 switches, each a module constant read at run time. They are
# set before the heat issuer captures its loaded identity, so that identity
# records them; spatial_record_recipes is outside the captured set.
SWITCHES = {'live_composite.ENABLED': lambda value: value in (0, 1),
            'live_spatial_patch.EARLY_RELEASE': lambda value: value in (0, 1),
            'live_spatial_patch.STREAM_CELLS': lambda value: value in (0, 1),
            'live_mesh_patch.EARLY_RELEASE': lambda value: value in (0, 1),
            'spatial_record_recipes.SMALL_IMPORT_BYTES': lambda value: value > 0}
OLD_ROUTE = {'live_composite.ENABLED': 0, 'live_spatial_patch.EARLY_RELEASE': 0,
             'live_spatial_patch.STREAM_CELLS': 0, 'live_mesh_patch.EARLY_RELEASE': 0,
             'spatial_record_recipes.SMALL_IMPORT_BYTES': 1 << 62}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def tree_hashes(root):
    root = Path(root)
    return {str(p.relative_to(root)).replace('\\', '/'): file_hash(p)
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=repr)+'\n', encoding='utf8')
    os.replace(temporary, path)


def store_disk(output):
    """Bytes of the store files (and any sidecars) this run writes."""
    return sum(p.stat().st_size for p in Path(output).iterdir()
               if p.is_file() and p.name.startswith(STORE_PREFIXES))


def parse_settings(route, pairs):
    """Route shorthand plus explicit module constants, applied before capture."""
    settings = dict(OLD_ROUTE) if route == 'old' else {}
    for pair in pairs:
        name, _, raw = pair.partition('=')
        require(name in SWITCHES and raw.lstrip('-').isdigit(), 'unknown or malformed switch: '+pair)
        value = int(raw)
        require(SWITCHES[name](value), 'switch value out of range: '+pair)
        settings[name] = value
    return dict(sorted(settings.items()))


def layout_for(sources):
    """One shared composition per exact compact source set.

    The heat issuer binds module paths into its loaded identity, so arms that
    share source bytes must also share paths to be same-input. The layout is
    written once per source digest and its tree hashes are recorded; every
    later arm verifies those hashes before use. Copies exceed the Windows
    260-character limit under the long output path, hence the short folder.
    """
    import measure_live_owner as M
    layouts = R/'L'
    layouts.mkdir(exist_ok=True)
    key = sha256(json.dumps(sources, sort_keys=True).encode('utf8')).hexdigest()[:8]
    layout_dir, manifest = layouts/key, layouts/(key+'.json')
    if manifest.exists():
        saved = json.loads(manifest.read_text(encoding='utf8'))
        require(tree_hashes(layout_dir) == saved['layout_hashes'], 'shared composition layout changed')
        return saved
    require(not layout_dir.exists(), 'incomplete shared layout without its manifest: '+str(layout_dir))
    layout_dir.mkdir()
    root, helpers, ram, report = M.layout(str(layout_dir), True)
    longest = max(len(str(p)) for p in layout_dir.rglob('*'))
    require(longest < 260, 'composition layout path exceeds the Windows path limit')
    saved = {'layout_dir': str(layout_dir), 'layout_longest_path_chars': longest,
             'paths': {'root': str(root), 'helpers': str(helpers), 'ram': str(ram),
                       'tests': str(H/'source/tectonics/tests')},
             'layout_hashes': tree_hashes(layout_dir), 'composition': report, 'c_source_sha256': sources}
    write_json(manifest, saved)
    return saved


def launch(output, *, settings, start_gate, basis, compose_only=False):
    import psutil
    sys.path[:0] = [str(HERE), str(R), str(R.parent/'runtime-integration-r1/runtime-src')]
    import measure_live_capacity as CAP
    import measure_live_owner as M
    require(Path(sys.executable).resolve() == PYTHON.resolve(), 'task .r44-env interpreter required')
    sources = {p.name: file_hash(p) for p in sorted(HERE.glob('*.py'))}
    shared = layout_for(sources)
    if compose_only:
        print(json.dumps({'stage': 'composed', 'layout_dir': shared['layout_dir'],
                          'longest_path_chars': shared['layout_longest_path_chars']}), flush=True)
        return 0
    output = Path(output).resolve()
    require(output.parent == (R/'probes/step8').resolve() and output.name.startswith('owner-guarded'),
            'output must be a new owner-guarded-* directory directly in R/probes/step8')
    require(not output.exists(), 'exclusive new output directory required')
    require(type(start_gate) is int and start_gate >= 4 << 30, 'Step 8 test start gate starts at 4 GiB')
    available = psutil.virtual_memory().available
    require(available >= start_gate, 'Step 8 test start gate refused: available '+str(available))
    output.mkdir()
    guard_dir = output/'guard'
    guard_dir.mkdir()
    for name, raw in CAP.guard_files().items():
        (guard_dir/name).write_bytes(raw)
    label = ','.join(name+'='+str(value) for name, value in settings.items()) or 'step8-defaults'
    prepare = {'schema': 'atlas.step8.owner-guarded-prepare.v2', 'settings': settings, 'label': label,
        'guards': GUARDS,
        'start_gate': {'bytes': start_gate, 'basis': basis,
                       'authority': 'Michael, 15 October 2026: Step 8 capacity tests only; previous measured '
                                    'peak + 1 GiB floor + stated margin, starting at 4 GiB',
                       'real_interval_gate_bytes_unchanged': GUARDS['real_interval_start_gate_bytes']},
        'available_bytes_at_launch': available,
        'paths': shared['paths'], 'layout_dir': shared['layout_dir'],
        'layout_longest_path_chars': shared['layout_longest_path_chars'],
        'layout_hashes': shared['layout_hashes'], 'composition': shared['composition'],
        'c_source_sha256': sources,
        'fixture': {'path': str(M.FIXTURE), 'sha256': M.FIXTURE_SHA},
        'guard_sha256': {p.name: file_hash(p) for p in sorted(guard_dir.iterdir())},
        'max_seconds': MAX_SECONDS}
    write_json(output/'prepare.json', prepare)
    command = [str(PYTHON), '-B', str(guard_dir/'private_heat_continuation_guard_r3.py'),
               '--launch', '--output', str(output/'owner.json'), '--',
               str(PYTHON), '-B', str(Path(__file__).resolve()), '--workload', str(output)]
    environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    environment.update(PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
                       TMP=str(T/'_t'), TEMP=str(T/'_t'))
    print(json.dumps({'stage': 'guarded-launch', 'output': str(output), 'label': label,
                      'start_gate_bytes': start_gate, 'available_bytes': available}), flush=True)
    return subprocess.run(command, cwd=output, env=environment, timeout=MAX_SECONDS+120, check=False).returncode


def fixtures(budget_bytes):
    """measure_live_owner.fixtures (hash-checked), with the unchanged 16 GiB
    logical guard budget; the fixture reads BUDGET_BYTES when it is called."""
    import measure_live_owner as M
    namespace = M.fixtures()
    namespace['BUDGET_BYTES'] = budget_bytes
    return namespace


def digest_arrays(arrays):
    return {name: {'dtype': a.dtype.str, 'shape': list(a.shape), 'bytes': a.nbytes,
                   'sha256': sha256(a.tobytes(order='C')).hexdigest()} for name, a in sorted(arrays.items())}


def workload(output):
    output = Path(output).resolve()
    plan = json.loads((output/'prepare.json').read_text(encoding='utf8'))
    require(tree_hashes(plan['layout_dir']) == plan['layout_hashes'], 'composition layout changed after launch')
    require({p.name: file_hash(p) for p in sorted(HERE.glob('*.py'))} == plan['c_source_sha256'],
            'compact source changed after launch')
    paths = plan['paths']
    sys.path[:0] = [paths['root'], paths['helpers'], paths['ram'], paths['tests'], str(HERE), str(R)]
    sys.path.insert(0, str(output/'guard'))
    from private_heat_continuation_guard_r3 import ENV, ContinuationGuard
    record = {'schema': 'atlas.step8.owner-guarded-result.v2', 'status': 'RUNNING',
              'settings': plan['settings'], 'label': plan['label'],
              'scientific_status': 'W4 genuine owner fixture; not IV2, not a full CollarWorkflow publication',
              'guards': GUARDS, 'start_gate': plan['start_gate']}
    result_path = output/'owner.json'
    def save():
        write_json(result_path, record)
    save()
    guard = ContinuationGuard(result_path, record, save)
    try:
        _run(output, plan, record, guard, ENV)
        record['status'] = 'PASS'
    except BaseException as error:
        record['status'] = 'FAILED'
        record['failure'] = {'type': type(error).__name__, 'message': str(error),
                             'traceback': ''.join(traceback.format_exception(error))}
        raise
    finally:
        save()
        try:
            record['guard_close'] = guard.close()
        finally:
            save()
    return 0


def _loaded_heat_reports():
    """Heat meter reports, only from modules the run itself loaded."""
    reports = {}
    meter = sys.modules.get('private_heat_process_meter_r1')
    parallel = sys.modules.get('private_heat_functionals_parallel_r1')
    for label, module, names in (('meter', meter, ('returned', 'last_report')),
                                 ('parallel', parallel, ('report',))):
        if module is None:
            reports[label] = 'not loaded by this run'
            continue
        for name in names:
            try:
                reports[label+'.'+name] = getattr(module, name)()
            except (AttributeError, LookupError, RuntimeError, TypeError, ValueError) as error:
                reports[label+'.'+name+'.error'] = repr(error)
    return json.loads(json.dumps(reports, default=repr))


def _stream_file(value, path):
    """Write an opened record's exact canonical bytes; return (bytes, sha256)."""
    digest, length = sha256(), 0
    with Path(path).open('wb') as output, value.iter_json() as blocks:
        for block in blocks:
            with block:
                output.write(block.value)
                digest.update(block.value)
                length += len(block.value)
    return {'bytes': length, 'sha256': digest.hexdigest()}


def _apply_settings(settings):
    """Set the test-only switches before the heat issuer captures identity.

    The issuer captures every upper-case constant of its compact dependencies
    (live_composite and live_spatial_patch among them) when it is imported and
    binds that loaded identity into each heat call's metadata, so a switch set
    here is recorded honestly: heat-derived provenance IDs differ between arms
    with different captured switches, and the comparison names every differing
    field. spatial_record_recipes is outside the captured set.
    """
    import importlib
    require('private_heat_native_issuer_r13' not in sys.modules, 'switches must be set before identity capture')
    applied = {}
    for name, value in settings.items():
        require(name in SWITCHES and SWITCHES[name](value), 'unknown switch '+name)
        module_name, constant = name.split('.')
        module = importlib.import_module(module_name)
        current = getattr(module, constant)
        require(type(current) in (bool, int), 'switch target is not a plain constant: '+name)
        setattr(module, constant, bool(value) if type(current) is bool else value)
        applied[name] = getattr(module, constant)
    require('private_heat_native_issuer_r13' not in sys.modules, 'a switch module loaded the heat issuer')
    return applied


def _run(output, plan, record, guard, env_name):
    record['applied_settings'] = _apply_settings(plan['settings'])
    import live_composite as LC
    import spatial_record_recipes as RECIPES
    record['route_settings'] = {'live_composite_enabled': LC.ENABLED,
                                'small_import_bytes': RECIPES.SMALL_IMPORT_BYTES,
                                'max_import_bytes': RECIPES.MAX_IMPORT_BYTES}

    import live_memory_probe as PROBE
    import live_spatial_patch as LIVE
    import measure_live_owner as M
    import private_heat_joined_consumer_r6 as J
    import private_heat_native_issuer_r13 as I
    import private_heat_snapshot_store_r4 as HEAT_STORE
    import record_tables as RT
    import spatial_indexed_patch as SIP
    import spatial_records_patch as RECORDS
    import test_i04_spatial_workflow as FLOW
    from atlas_tectonics.storage import ArrayStore
    from content_cache import create_retained_scope
    from interval_store_set import IntervalStoreSet
    from threadpoolctl import threadpool_limits

    record['loaded_identity'] = I._LOADED_IMPLEMENTATION.descriptor()
    require(RT.MAX_BUILD_BYTES == GUARDS['builder_child_bytes'], 'builder child limit differs')
    record['module_files'] = {name: sys.modules[name].__file__ for name in
        ('live_composite', 'spatial_record_recipes', 'spatial_records_patch', 'record_tables',
         'live_spatial_patch', 'private_heat_native_issuer_r13', 'private_heat_joined_consumer_r6')}
    job = PROBE.JobPeak(output/'guard', env_name)
    started = time.perf_counter()
    fixture = fixtures(GUARDS['logical_budget_bytes'])
    gc_was_enabled = gc.isenabled()
    with threadpool_limits(1), fixture['actual_spatial_fixture']() as case:
        budget, collar, funding = (case[k] for k in ('budget', 'collar', 'funding'))
        require(budget.max_bytes == GUARDS['logical_budget_bytes'], 'logical budget differs')
        guard.budget = budget
        initial_mesh = FLOW.thermal_mesh(case, case['wall'], 'start')
        with FLOW.PreparedSpatialOwner(funding, collar, case['bounds'], initial_mesh,
                method='implicit-upwind', max_projection_errors=FLOW.allowances(case),
                budget=budget, heat_method=J.METHOD) as owner:
            scope = create_retained_scope(budget, process_epoch='step8-owner-guarded')
            require(scope.retained_budget.max_bytes == GUARDS['retained_scope_bytes'], 'retained scope differs')
            owner._record_scope = scope
            probe = PROBE.Probe(budget=budget, scope=scope, guard=guard, job=job, started=started)
            record['checkpoints'] = probe.rows
            def stage(name, **sizes):
                probe.stage(name, store_disk_bytes=store_disk(output), **sizes)
            parent = collar.initial_state_from_funding(funding, case['owner'])
            route_ns = SimpleNamespace(exterior_state=owner.initial_state,
                source_flow_stage=lambda duration, _parent=parent, **kw: collar.source_flow_stage(_parent, duration, **kw))
            stores = IntervalStoreSet.create_migration(str(output/'catalog.json'), workflow_id='a'*64, scope=scope)
            candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
            numeric = ArrayStore(output/'native.arrays.sqlite', candidate.limits, budget=budget)
            stage('fixture-ready')
            gc.disable()
            measured = time.perf_counter()
            stage('measured-start')
            with LIVE.construction(scope, budget=budget):
                source, bounds, wall = fixture['next_interval'](case, route_ns)
                stage('fresh-bounds')
                mesh = M.endpoint_mesh(case, wall, scope, True)
                stage('fresh-mesh')
                graph = owner.close_graph(owner.initial_state, source, bounds)
                stage('closed-graph', graph_payload=type(graph._json).__name__)
                step = owner.transport(owner.initial_state, source, graph)
                stage('transport-solve', finite_proposal=step.finite_proposal is not None)
                transport = collar.transport_from_spatial(source, step.result, graph,
                    method=owner.descriptor()['method'], finite_proposal=step.finite_proposal)
                stage('collar-transport')
                boundary_owner = RT.Scratch(budget, 65536+1024*mesh._compact.face_count)
                boundary = {}
                for index in range(mesh._compact.face_count):
                    face = mesh.face(index)
                    if len(face.value['owners']) == 1:
                        boundary[face.value['face_id']] = ('power', 0.)
                del face, index
                with I.ExecutionContext('scipy') as execution:
                    heat = owner.heat(step, mesh, boundary=boundary, execution=execution,
                        absolute_residual_target='1e-24', checkpoint_store=candidate)
                    stage('heat-solve-and-checkpoint')
                    record['heat_reports'] = _loaded_heat_reports()
                    adopted = collar.heat_from_spatial(transport, heat, mesh)
                    stage('heat-adopted')
                    native = collar.endpoint_from_transport(transport, adopted)
                    stage('native-endpoint')
                    exterior = owner.finish(step, mesh, heat, native)
                    stage('joined-finish', exchange_payload=type(exterior._record).__name__)
                del execution
                stage('execution-closed')
                saved = SIP.indexed_record(exterior.state)
                state_row = {key: value for key, value in saved.value.items() if key != 'thermal_mesh'}
                exchange = exterior.record()
                children = [exchange.without(('spatial_graph', 'transport', 'joined_heat'))]
                children.extend(exchange.field(key) for key in ('spatial_graph', 'transport', 'joined_heat'))
                rows = dict(zip(('exchange', 'graph', 'transport', 'heat'), children, strict=True), state=state_row)
                stage('publication-views')
                refs = RECORDS.publish_records(candidate, rows, budget=budget,
                    source_producer={'measurement': 'step8-owner-guarded', 'source_fixture_sha256': M.FIXTURE_SHA})
                stage('compact-record-publication')
                payload = mesh._compact.storage_payload()
                metadata, mesh_arrays = payload.value
                numeric.put('d'*64, mesh_arrays, metadata)
                stage('mesh-numeric-put')
                arrays = {}
                for prefix, values in (('spatial', exterior.state.arrays()), ('transport', step.result.arrays()),
                        ('native', native.state.native_state), ('collar', native.state.fields), ('heat', heat)):
                    if type(values) is not dict:
                        values = {name: values.array(name) for name in values.array_names}
                    arrays.update({prefix+':'+name: value for name, value in values.items()})
                committed_digests = digest_arrays(arrays)
                numeric.put('e'*64, arrays, {'schema': 'atlas.step8.measured-component-commit.v1', 'records': refs})
                stage('component-numeric-put')
                del arrays, values, payload, metadata, mesh_arrays
                stores.promote(candidate.seal(RECORDS.primary_segment(refs)),
                               expected_catalog_digest=stores.catalog_digest)
                stage('seal-promote')
            record['measured_seconds'] = time.perf_counter()-measured
            # Re-read the committed interval while every live structure is
            # still held, as a continuing workflow does; the IV1 high-water
            # was this re-read, not the advance itself.
            with rows['heat'].export(max_logical_bytes=1 << 20, max_owned_bytes=16 << 20) as held:
                heat_row = json.loads(json.dumps(held.value))
            del held
            reread_started = time.perf_counter()
            reader = IntervalStoreSet.open_catalog(output/'catalog.json', scope=scope)
            with RECORDS.open_records(reader, refs, budget=budget) as opened:
                stage('reread-records-open', kinds=sorted(opened))
                held_heat = HEAT_STORE.open(reader, heat_row['checkpoint'], expected_result_id=heat_row['result_id'],
                    bindings=heat_row['checkpoint']['metadata']['bindings'], scope=scope)
                stage('reread-heat-open')
                committed = numeric.get('e'*64)
                stage('reread-numeric-get')
                record['committed_arrays'] = digest_arrays(committed)
                record['committed_arrays_lossless'] = record['committed_arrays'] == committed_digests
                del committed
                held_heat.value.close()
                held_heat.close()
                record['reread_seconds'] = time.perf_counter()-reread_started
                # Committed records, streamed after the timed re-read, for a
                # field-level comparison between arms.
                (output/'records').mkdir()
                record['reread_record_files'] = {kind: _stream_file(value, output/'records'/(kind+'.json'))
                                                 for kind, value in sorted(opened.items())}
                for value in opened.values():
                    value.close()
            del held_heat, opened, value
            reader.close()
            del reader
            stage('reread-released')
            require(all(record['reread_record_files'][kind] == {'bytes': ref['bytes'], 'sha256': ref['sha256']}
                        for kind, ref in refs.items()), 'committed record bytes differ from their descriptors')
            require(record['committed_arrays_lossless'], 'committed numeric arrays differ from memory')
            record['identities'] = {'state': exterior.state.state_id, 'exchange': exterior.result_id,
                'graph': graph.geometry_id, 'transport': step.result.result_id, 'heat': heat.result_id,
                'heat_row_result_id': heat_row['result_id'], 'mesh': mesh.geometry_id}
            record['logical_records'] = {kind: {'bytes': ref['bytes'], 'sha256': ref['sha256']}
                                         for kind, ref in refs.items()}
            record['descriptors'] = {kind: {'v2': RECIPES.is_v2(ref)} for kind, ref in refs.items()}
            record['numeric_arrays'] = digest_arrays({name: value for prefix, values in
                (('spatial', exterior.state.arrays()), ('transport', step.result.arrays()))
                for name, value in ((prefix+':'+key, item) for key, item in values.items())})
            record['heat_arrays'] = digest_arrays({name: heat.array(name) for name in heat.array_names})
            record['native_arrays'] = digest_arrays({name: native.state.native_state.array(name)
                                                     for name in native.state.native_state.array_names})
            record['counts'] = {'native_cells': list(collar._native.cells), 'collar_cells': list(collar.cells),
                                'thermal_cells': mesh._compact.cell_count, 'thermal_faces': mesh._compact.face_count}
            stage('outputs-recorded')
            # Release ladder: each drop returns that family's exclusive share
            # at this overlap; backing shared with a later holder drops with it.
            for item in reversed(children):
                item.close()
            exchange.close()
            del children, exchange, rows, state_row, saved, item, heat_row
            stage('release-publication-views')
            del exterior, native, adopted
            stage('release-exterior-native')
            del transport
            stage('release-collar-transport')
            del step
            stage('release-transport-step')
            del graph
            stage('release-graph')
            del heat
            stage('release-heat')
            del mesh, boundary, boundary_owner
            stage('release-mesh')
            del bounds, source, wall
            stage('release-bounds-source')
            numeric.close()
            candidate.close()
            stores.close()
            del numeric, candidate, stores, route_ns, parent
            stage('release-stores')
            owner._record_scope = None
            if gc_was_enabled:
                gc.enable()
            # No collect is used as an ownership repair: released owners must
            # retire through ordinary reference lifetime before scope close.
            scope.close()
            record['retained_after_close_bytes'] = scope.retained_budget.reserved_bytes
            require(record['retained_after_close_bytes'] == 0, 'measurement scope leaked retained ownership')
            record['ledger_after_close'] = {k: v for k, v in budget.statistics().items()
                                            if k in ('reserved_bytes', 'peak_reserved_bytes', 'refusals')}
            record['store_disk_bytes'] = {p.name: p.stat().st_size for p in output.iterdir()
                                          if p.is_file() and p.name.startswith(STORE_PREFIXES)}
            record['cleanup'] = 'PASS'
        del initial_mesh


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--launch', type=Path)
    group.add_argument('--workload', type=Path)
    group.add_argument('--compose-only', action='store_true',
                       help='write or verify the shared composition layout and exit')
    parser.add_argument('--route', choices=('new', 'old'), default='new',
                        help='old = every Step 8 switch off (OLD_ROUTE); new = module defaults')
    parser.add_argument('--set', action='append', default=[], metavar='MODULE.CONSTANT=INT',
                        help='one test-only switch from SWITCHES; repeatable')
    parser.add_argument('--start-gate-bytes', type=int, default=STEP8_TEST_START_GATE)
    parser.add_argument('--start-gate-basis', default='4 GiB starting value (Michael, 15 Oct). Previous guarded '
                        'W4 genuine-owner peak: whole job tree 1,090,707,456 B RSS (parent 279,531,520 B plus six '
                        'heat functional workers) + 1 GiB floor = 2.09 GiB; margin 1.9 GiB')
    args = parser.parse_args()
    if args.workload:
        return workload(args.workload)
    return launch(args.launch, settings=parse_settings(args.route, args.set), start_gate=args.start_gate_bytes,
                  basis=args.start_gate_basis, compose_only=args.compose_only)


if __name__ == '__main__':
    raise SystemExit(main())
