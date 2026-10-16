"""Same-input old-route versus new-route parity and cost for the Step 8 repacks.

Runs the genuine W4 owner path (as C/measure_live_owner.owner_run does) in a
fresh child process under the test-only live-memory composition, untouched:
the heat issuer captures the implementation of record_tables, live_composite
and the other compact modules and refuses any changed function, so nothing is
patched while the scientific stages run.

Afterwards, on the live holders the run produced:
- each composite (graph over bounds, finite proposal if any, exchange over
  graph/transport/proposal) is rebuilt into the exact dict it was issued from
  (its packed native fields plus its borrowed children) and issued by BOTH
  routes: the old import pack and the new composition. Identities must be
  equal to each other and to the holder's own identity.
- the publication rows are published by the original v1 code (pre-edit copy
  in before-src, hash-verified) into a separate scratch store and by the new
  code into the measured candidate. Every kind's identity must be equal.
A temporary builder hook records each route's builder-ledger peak and is
removed before anything else runs. Recorded per route: elapsed seconds (no
tracemalloc), builder peak, retained-scope delta, and for publication the
store growth on disk.
Usage:  python -B probe_repack_parity.py OUTDIR [--small BYTES]
--small lowers only the reference-publication policy bound so genuine rows of
this small fixture take the v2 route; store limits and guards are unchanged.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
T = R.parents[3]
H = R.parents[2]/'heat-repair-20261007'
BEFORE = HERE/'before-src'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_before(name, module_name):
    path = BEFORE/name
    recorded = json.loads((HERE/'baseline-hashes-takeover.json').read_text(encoding='utf8'))
    if sha(path) != recorded['compact-geometry-r1/'+name]['sha256']:
        raise ValueError('pre-edit copy differs from the takeover hash: '+name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def store_bytes(directory):
    return sum(p.stat().st_size for p in Path(directory).rglob('*') if p.is_file())


class BuilderHook:
    """Temporary record of each _Builder's own ledger peak; always removed."""

    def __init__(self, record_tables):
        self.module, self.rows = record_tables, []
        self.original = record_tables._Builder.finish

    def __enter__(self):
        original, rows = self.original, self.rows
        def finish(builder, root, record_schema):
            result = original(builder, root, record_schema)
            stats = builder.work_budget.statistics()
            rows.append({'record_schema': record_schema, 'builder_peak_bytes': stats['peak_reserved_bytes'],
                         'nodes': len(builder.nodes), 'tokens': len(builder.tokens),
                         'token_bytes': sum(map(len, builder.tokens)), 'integers': len(builder.integers),
                         'emitted_bytes': builder.length})
            return result
        self.module._Builder.finish = finish
        return self

    def __exit__(self, *_):
        self.module._Builder.finish = self.original
        return False


def child(paths, outdir, small):
    sys.path[:0] = [*paths, str(C), str(R)]
    import gc
    from types import SimpleNamespace

    import live_composite as LC
    import live_spatial_patch as LIVE
    import measure_live_owner as M
    import private_heat_joined_consumer_r6 as J
    import private_heat_native_issuer_r13 as I
    import psutil
    import record_tables as RT
    import spatial_indexed_patch as SIP
    import spatial_record_recipes as RECIPES
    import spatial_records_patch as RECORDS
    import test_i04_spatial_workflow as FLOW
    from content_cache import create_retained_scope
    from interval_store_set import IntervalStoreSet
    from record_views import _ObjectRecordRef
    from threadpoolctl import threadpool_limits

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    if small is not None:
        RECIPES.SMALL_IMPORT_BYTES = small
    old_records = load_before('spatial_records_patch.py', 'spatial_records_patch_s0')
    process = psutil.Process()
    seams = []

    def measure(scope, label, run):
        with BuilderHook(RT) as hook:
            retained0 = scope.stats().retained_bytes
            rss0 = process.memory_info().rss
            started = time.perf_counter()
            value = run()
            elapsed = time.perf_counter()-started
            row = {'route': label, 'seconds': elapsed,
                   'retained_delta_bytes': scope.stats().retained_bytes-retained0,
                   'rss_delta_bytes': process.memory_info().rss-rss0, 'builders': list(hook.rows)}
        row['builder_peak_bytes'] = max([b['builder_peak_bytes'] for b in row['builders']], default=0)
        return value, row

    def issued_input(live):
        """The exact dict a LiveRecord was composed from: native fields plus borrows."""
        ref = live._ref
        if type(ref) is not _ObjectRecordRef:
            raise AssertionError('expected a composed holder payload')
        base, _, _, _, _, overrides = ref._owner.value
        with base.export(max_logical_bytes=64 << 20, max_owned_bytes=512 << 20) as held:
            native = dict(held.value)
        value = dict(native)
        for key, child in overrides.items():
            value[key] = child.borrow() if type(child) is not _ObjectRecordRef else child
        return value

    def compare_composite(scope, name, live, record_schema, check):
        value = issued_input(live)
        expected = live.identity()
        old, old_row = measure(scope, 'old-import', lambda: RT.RecordCodec().pack_record(
            value, record_schema=record_schema, scope=scope, check=check))
        old_identity = old.identity()
        old.close()
        del old
        new, new_row = measure(scope, 'new-compose', lambda: LC.compose_record(
            value, record_schema=record_schema, scope=scope, check=check))
        new_identity = new.identity()
        new.close()
        del new
        equal = old_identity == new_identity == expected
        seams.append({'seam': 'compose', 'holder': name, 'record_schema': record_schema,
            'logical_bytes': old_identity.canonical_bytes, 'identity_equal': equal,
            'holder_identity_sha256': expected.sha256, 'borrowed_keys': sorted(k for k, v in value.items()
            if hasattr(v, '_view')), 'old': old_row, 'new': new_row})
        if not equal:
            raise AssertionError('composite identity differs from imported pack: '+name)

    fixture = M.fixtures()
    with threadpool_limits(1), fixture['actual_spatial_fixture']() as case:
        budget, collar, funding = (case[k] for k in ('budget', 'collar', 'funding'))
        initial_mesh = FLOW.thermal_mesh(case, case['wall'], 'start')
        with FLOW.PreparedSpatialOwner(funding, collar, case['bounds'], initial_mesh,
                method='implicit-upwind', max_projection_errors=FLOW.allowances(case),
                budget=budget, heat_method=J.METHOD) as owner:
            scope = create_retained_scope(budget, process_epoch='step8-repack-parity')
            owner._record_scope = scope
            parent = collar.initial_state_from_funding(funding, case['owner'])
            route = SimpleNamespace(exterior_state=owner.initial_state,
                source_flow_stage=lambda duration, _parent=parent, **kw: collar.source_flow_stage(_parent, duration, **kw))
            stores = IntervalStoreSet.create_migration(str(outdir/'catalog.json'), workflow_id='a'*64, scope=scope)
            candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
            old_dir = outdir/'old-route-store'
            old_dir.mkdir()
            old_stores = IntervalStoreSet.create_migration(str(old_dir/'catalog.json'), workflow_id='f'*64, scope=scope)
            old_candidate = old_stores.begin_interval(None, producer_identity='e'*64, runtime_identity='d'*64)
            with LIVE.construction(scope, budget=budget):
                source, bounds, wall = fixture['next_interval'](case, route)
                mesh = M.endpoint_mesh(case, wall, scope, True)
                graph = owner.close_graph(owner.initial_state, source, bounds)
                step = owner.transport(owner.initial_state, source, graph)
                transport = collar.transport_from_spatial(source, step.result, graph,
                    method=owner.descriptor()['method'], finite_proposal=step.finite_proposal)
                boundary = {}
                for index in range(mesh._compact.face_count):
                    face = mesh.face(index)
                    if len(face.value['owners']) == 1:
                        boundary[face.value['face_id']] = ('power', 0.)
                del face
                with I.ExecutionContext('scipy') as execution:
                    heat = owner.heat(step, mesh, boundary=boundary, execution=execution,
                        absolute_residual_target='1e-24', checkpoint_store=candidate)
                    adopted = collar.heat_from_spatial(transport, heat, mesh)
                    native = collar.endpoint_from_transport(transport, adopted)
                    exterior = owner.finish(step, mesh, heat, native)
                # The scientific stages are complete; comparisons start here.
                check = lambda: LIVE.check_cancel(None)
                holders = [('graph', graph._json), ('exchange', exterior._record)]
                if step.finite_proposal is not None:
                    holders.insert(1, ('finite-proposal', step.finite_proposal._encoded))
                for name, live in holders:
                    if LC.is_live(live):
                        # Each holder's own recorded schema, as issued.
                        compare_composite(scope, name, live, live._schema, check)
                    else:
                        seams.append({'seam': 'compose', 'holder': name, 'composed': False})
                saved = SIP.indexed_record(exterior.state)
                rows_state = {key: value for key, value in saved.value.items() if key != 'thermal_mesh'}
                exchange = exterior.record()
                children = [exchange.without(('spatial_graph', 'transport', 'joined_heat'))]
                children.extend(exchange.field(key) for key in ('spatial_graph', 'transport', 'joined_heat'))
                rows = dict(zip(('exchange', 'graph', 'transport', 'heat'), children, strict=True), state=rows_state)
                producer = {'measurement': 'step8-repack-parity', 'source_fixture_sha256': M.FIXTURE_SHA}
                size0 = store_bytes(old_dir)
                old_refs, old_row = measure(scope, 'old-v1-bundle', lambda: old_records.publish_records(
                    old_candidate, rows, budget=budget, source_producer=producer))
                old_row['store_growth_bytes'] = store_bytes(old_dir)-size0
                size1 = store_bytes(outdir)-store_bytes(old_dir)
                new_refs, new_row = measure(scope, 'new-records', lambda: RECORDS.publish_records(
                    candidate, rows, budget=budget, source_producer=producer))
                new_row['store_growth_bytes'] = store_bytes(outdir)-store_bytes(old_dir)-size1
                identities = {kind: (old_refs[kind]['bytes'], old_refs[kind]['sha256']) ==
                              (new_refs[kind]['bytes'], new_refs[kind]['sha256']) for kind in rows}
                seams.append({'seam': 'publish', 'kinds': sorted(rows), 'identity_equal': identities,
                    'v2_kinds': sorted(k for k, v in new_refs.items() if RECIPES.is_v2(v)),
                    'logical_bytes': {k: v['bytes'] for k, v in new_refs.items()}, 'old': old_row, 'new': new_row})
                if not all(identities.values()):
                    raise AssertionError('publication identity differs between routes: '+repr(identities))
                for item in reversed(children):
                    item.close()
                exchange.close()
            result = {'schema': 'atlas.step8.repack-parity.v2', 'small_import_bytes': RECIPES.SMALL_IMPORT_BYTES,
                'fixture_sha256': M.FIXTURE_SHA, 'seams': seams,
                'identities': {'state': exterior.state.state_id, 'exchange': exterior.result_id,
                               'graph': graph.geometry_id, 'transport': step.result.result_id,
                               'heat': heat.result_id},
                'source_sha256': {name: sha(C/name) for name in ('live_composite.py', 'spatial_record_recipes.py',
                    'spatial_records_patch.py', 'exchange_record_patch.py', 'live_spatial_patch.py',
                    'live_finite_patch.py', 'record_tables.py', 'record_views.py')},
                'old_route_source_sha256': sha(BEFORE/'spatial_records_patch.py')}
            (outdir/'parity.json').write_text(json.dumps(result, indent=1, sort_keys=True), encoding='utf8')
            old_candidate.close()
            old_stores.close()
            candidate.close()
            stores.close()
            # The loop variable `live` still names the last composed holder.
            del rows, children, exchange, rows_state, saved, exterior, native, adopted, heat, step, holders
            del live, name, check
            del graph, mesh, bounds, source, wall, transport, boundary, route, parent
            owner._record_scope = None
            gc.collect()
            leftovers = live_charges(scope)
            result['cleanup'] = {'live_charges': leftovers,
                'store_bytes_after_close': {'new_route_candidate_dir': store_bytes(outdir)-store_bytes(old_dir),
                                            'old_route_dir': store_bytes(old_dir)}}
            (outdir/'parity.json').write_text(json.dumps(result, indent=1, sort_keys=True), encoding='utf8')
            if not leftovers:
                scope.close()
        del initial_mesh
    print(json.dumps({'done': str(outdir/'parity.json'), 'seams': len(seams)}), flush=True)


def live_charges(scope):
    """Purpose, size and holder types of every charge still open at cleanup."""
    import gc
    rows = []
    with scope._charges_lock:
        charges = [c for c in scope._charges.values() if c is not scope._base and c.context is not None]
    for charge in charges:
        allocation = None if charge.allocation is None else charge.allocation()
        row = {'purpose': charge.spec.purpose, 'bytes': charge.spec.total_bytes, 'state': charge.state}
        if allocation is not None:
            row['value_type'] = type(allocation.value).__name__
            holders = list(allocation.holders)
            row['holders'] = len(holders)
            referrers = []
            for holder in holders[:3]:
                for ref in gc.get_referrers(holder)[:6]:
                    referrers.append(type(ref).__name__ + (':' + ','.join(sorted(k for k in ref if type(k) is str)[:6])
                                                          if type(ref) is dict else ''))
            row['holder_referrers'] = referrers
        rows.append(row)
    return rows


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        small = None if sys.argv[4] == 'none' else int(sys.argv[4])
        child(json.loads(sys.argv[2]), sys.argv[3], small)
        return
    outdir = Path(sys.argv[1]).absolute()
    small = int(sys.argv[sys.argv.index('--small')+1]) if '--small' in sys.argv else None
    outdir.mkdir(parents=True, exist_ok=False)
    sys.path[:0] = [str(C), str(R), str(R.parent/'runtime-integration-r1/runtime-src')]
    import measure_live_owner as M
    with tempfile.TemporaryDirectory(prefix='step8-parity-', dir=T/'_t') as directory:
        root, helpers, ram, report = M.layout(directory, True)
        paths = [str(root), str(helpers), str(ram), str(H/'source/tectonics/tests')]
        (outdir/'composition.json').write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf8')
        environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
        environment.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1',
                           TMP=str(T/'_t'), TEMP=str(T/'_t'))
        subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--child', json.dumps(paths),
                        str(outdir), 'none' if small is None else str(small)],
                       cwd=directory, env=environment, check=True, timeout=1200)


if __name__ == '__main__':
    main()
