"""Read-only cProfile of ONE production heat advance on the genuine W4 call (236 cells, 832 faces).

Uses a layout prepared by compact-geometry-r1/step7_same_call_heat_control.py --prepare <dir> 1
(the production compact-successor heat route; kernel hashes checked against the Steps 8-9 chain)
and repeats that control's child set-up verbatim: the authentic W4 fixture producers selected
from w4_owner_heat_child.py (sha-pinned), the spatial owner, next genuine source/geometry/
transport, the compact mesh, one bound owner call. It then profiles I.advance(call) (r13) once.
Nothing is written outside --output-dir; the layout is only read. Requires PYTHONHASHSEED=0.
Usage: profile_w4_heat.py --layout DIR --output-dir NEW_SHORT_DIR [--no-profile]
"""
import argparse
import ast
import cProfile
from contextlib import contextmanager
from fractions import Fraction as Q
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

C = Path(__file__).resolve().parents[2] / 'compact-geometry-r1'
FIXTURE = C.parent / 'composed-checks' / 'w4_owner_heat_child.py'
FIXTURE_SHA = '5a850e22790e23b25dbaa8ce99ead91e7eef264c9251d38110c8293f30ddfabb'
BUDGET_BYTES = 6 << 30


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--layout', required=True)
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--no-profile', action='store_true')
    ap.add_argument('--serial-reconstruct', action='store_true',
                    help='harness-only: functionals_parallel_r1.workers -> 0 in THIS process, so kernel r5 '
                         'runs its unchanged in-process face loop (workers call the same _face) and '
                         'cProfile sees the per-face kernel; the result id must equal the parallel run')
    args = ap.parse_args()
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=False)
    info = json.loads((Path(args.layout) / 'control.json').read_text(encoding='utf8'))
    sys.path[:0] = info['paths']
    raw = FIXTURE.read_bytes()
    if sha256(raw).hexdigest() != FIXTURE_SHA:
        raise ValueError('original W4 fixture changed')
    text = raw.decode('utf8')
    tree = ast.parse(text)
    selected = []
    for name in ('funded_collar_fixture', 'actual_spatial_fixture'):
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        selected.append('@contextmanager\n' + ast.get_source_segment(text, node))
    fixtures = dict(contextmanager=contextmanager, Q=Q, BUDGET_BYTES=BUDGET_BYTES)
    exec(compile('\n\n'.join(selected), 'w4_owner_heat_child.py', 'exec'), fixtures)
    import psutil
    import private_heat_native_issuer_r13 as I
    import private_heat_joined_consumer_r6 as J
    import test_i04_spatial_workflow as FLOW
    import mesh_tables as MT
    from atlas_tectonics.integration_exterior_mesh import ExteriorMesh
    from content_cache import create_retained_scope
    from threadpoolctl import threadpool_limits
    from types import SimpleNamespace
    kernels = {name: sha256(Path(sys.modules[name].__file__).read_bytes()).hexdigest()[:8]
               for name in ('private_heat_native_issuer_r13', 'private_heat_joined_consumer_r6')}
    times = {}
    started = time.perf_counter()
    with threadpool_limits(1), fixtures['actual_spatial_fixture']() as case:
        budget, collar, funding = (case[k] for k in ('budget', 'collar', 'funding'))
        initial_mesh = FLOW.thermal_mesh(case, case['wall'], 'start')
        with FLOW.PreparedSpatialOwner(funding, collar, case['bounds'], initial_mesh,
                method='implicit-upwind', max_projection_errors=FLOW.allowances(case), budget=budget,
                heat_method=J.METHOD) as owner:
            scope = create_retained_scope(budget, process_epoch='geometry-heat-profile')
            owner._record_scope = scope
            parent = collar.initial_state_from_funding(funding, case['owner'])
            route = SimpleNamespace(exterior_state=owner.initial_state,
                source_flow_stage=lambda duration, _parent=parent, **kw: collar.source_flow_stage(_parent, duration, **kw))
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
            times['setup_s'] = time.perf_counter() - started
            with I.ExecutionContext('scipy') as execution:
                call = I.bind_owner_call(owner, step, compact, boundary=boundary,
                    absolute_residual_target='1e-24', execution=execution)
                kernels['forward'] = sha256(Path(I.F.__file__).read_bytes()).hexdigest()[:8]
                kernels['functions'] = sha256(Path(I.F.FUNCTIONS.__file__).read_bytes()).hexdigest()[:8]
                if args.serial_reconstruct:
                    import private_heat_functionals_parallel_r1 as PARALLEL
                    PARALLEL.workers = lambda *a, **k: 0
                profiler = None if args.no_profile else cProfile.Profile()
                t, c = time.perf_counter(), time.process_time()
                if profiler:
                    profiler.enable()
                result = I.advance(call)
                if profiler:
                    profiler.disable()
                    profiler.dump_stats(str(out / 'advance.prof'))
                times['advance_wall_s'], times['advance_cpu_s'] = time.perf_counter() - t, time.process_time() - c
                arrays = {name: sha256(result.array(name).tobytes()).hexdigest() for name in result.array_names}
                result_id = result.result_id
                result._snapshot.close()
                del result, call
            del route, parent, step, source, bounds, graph, compact, view, mesh, wall
            scope.close()
        del initial_mesh
    memory = psutil.Process().memory_info()
    report = dict(times=times, profiled=not args.no_profile, kernels=kernels, result_id=result_id,
                  arrays=arrays, peak_working_set_mib=round(memory.peak_wset / 2**20),
                  children_seen=len(psutil.Process().children(recursive=True)))
    (out / 'report.json').write_text(json.dumps(report, indent=1), encoding='utf8')
    print(json.dumps(dict(times=times, result_id=result_id, peak_mib=report['peak_working_set_mib'])))


if __name__ == '__main__':
    main()
