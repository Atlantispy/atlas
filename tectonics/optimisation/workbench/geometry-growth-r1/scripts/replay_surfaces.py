"""T, surfaces: bounded replay of saved fixed-wall and moving-interface queries.

Rebuilds the ALE router's own job lists from the saved supports, exactly as
integration_differential_ale._route_exterior_surfaces enumerates them:
  walls      every (component, axis, end) event of _exterior_wall_events whose
             'query' flag is set and that is not a coincident finite boundary
             owned by the angular pass (native-neighbour walls are skipped, as
             in the router; native contacts need the force stage and are NOT
             replayed here);
  interfaces every non-material literal grouped by (voxel, chart, plane
             identity): opposite-sign pairs once per pair, others unpaired.
Each query runs RC1's public enclose_component_wall / enclose_component_interface
(what partition_routing_patch.wall/interface call for native supports) at the
production stream width and leaf ceiling. A per-query CPU cap is enforced by a
wrapper around the arena's work admission (a test-only module attribute patch).
Streams supports one at a time (an index pass first). Read-only inputs; JSONL out.
"""
import argparse
import gzip
import json
import sys
import time
from hashlib import sha256
from itertools import product
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402


class QueryCap(Exception):
    pass


def _blank_digests(value):
    """The record with every 'source_sha256' value blanked (field-by-field parity under D-b)."""
    if isinstance(value, dict):
        return {k: (None if k == 'source_sha256' else _blank_digests(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_blank_digests(v) for v in value]
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--supports', required=True)
    ap.add_argument('--partition', required=True, help='gzip JSON holding "partition" (native cells, grid): '
                    'normally the small grid file from make_grid_file.py')
    ap.add_argument('--allow-full-partition', action='store_true',
                    help='single-process diagnostics only: allow a whole partition file (over 1 MB compressed)')
    ap.add_argument('--interval', required=True, help='gzip JSON holding "interval" (boundary paths, rays)')
    ap.add_argument('--stream-width', nargs=2, required=True, metavar=('NUM_HEX', 'DEN_HEX'))
    ap.add_argument('--output', required=True)
    ap.add_argument('--cap-cpu', type=float, default=5.0)
    ap.add_argument('--shard', type=int, default=0)
    ap.add_argument('--shards', type=int, default=1)
    ap.add_argument('--kinds', default='wall,interface')
    ap.add_argument('--runtime', default='rc1')
    ap.add_argument('--profile', default=None)
    ap.add_argument('--profile-each', default=None,
                    help='folder: one cProfile file per query (NNN-s<support>-<cell>.prof); with --profile, '
                         'that file is then the merge of the per-query files (one profiler is active at a time)')
    ap.add_argument('--max-queries', type=int, default=None)
    ap.add_argument('--only-cell', default=None, help='only jobs whose logical cell starts with this prefix')
    ap.add_argument('--only-name', default=None, help='only interface jobs on this constraint name')
    ap.add_argument('--count-only', action='store_true', help='enumerate jobs exactly; measure nothing')
    ap.add_argument('--only-list', default=None, help='JSONL of {support_index, cell, constraint_name|axis,end} to run')
    ap.add_argument('--only-cells-from', default=None,
                    help='replay JSONL(s, comma separated): run only jobs whose cell occurs there')
    ap.add_argument('--trace-work', action='store_true',
                    help='diagnostic: add every arena.work call (count, callers, arena) to each row')
    ap.add_argument('--trace-leaves', action='store_true',
                    help='diagnostic: add every moving-interface kernel leaf (t0, t1, level, widths, cpu) to each row')
    ap.add_argument('--progress', default=None, help='install G/geometry_progress.py writing this JSONL '
                    '(composition must carry the progress_hooks transform)')
    ap.add_argument('--progress-slow', type=float, default=30.0)
    ap.add_argument('--progress-heartbeat', type=float, default=120.0)
    args = ap.parse_args()
    # Production pins PYTHONHASHSEED=0. Interface work units depend on set iteration
    # order (exact_start_zero stops at its first proof), so parity needs the pin.
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0, as production does (work units follow set order)')
    only_cells = None
    if args.only_cells_from:
        only_cells = set()
        for path in args.only_cells_from.split(','):
            for line in open(path, encoding='utf8'):
                r = json.loads(line)
                if 'cell' in r:
                    only_cells.add(r['cell'])
    only_list = None
    only_pairs = None   # rows that carry an "other" key also pin the paired cell
    if args.only_list:
        only_list, only_pairs = set(), set()
        for line in open(args.only_list, encoding='utf8'):
            if line.strip():
                s = json.loads(line)
                job = (s['support_index'], s['cell'][:16], s.get('constraint_name') or (s.get('axis'), s.get('end')))
                if 'other' in s:
                    only_pairs.add((*job, s['other'][:16] if s['other'] else None))
                else:
                    only_list.add(job)
    out = Path(args.output)
    if out.exists():
        raise SystemExit('output exists')
    kinds = set(args.kinds.split(','))
    rc1_env.install(args.runtime)
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_differential_ale as A
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_volume_bounds as B
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    width = W._decode(args.stream_width)
    max_leaves = 524288
    # Memory rule (16 Oct): a whole interval partition costs about 4 GB per process to parse;
    # shards must read the grid file from make_grid_file.py instead.
    if Path(args.partition).stat().st_size > 1 << 20 and not args.allow_full_partition:
        raise SystemExit('compressed partition file over 1 MB: pass its grid file (scripts/make_grid_file.py)')
    partition = json.loads(gzip.decompress(Path(args.partition).read_bytes()))['partition']
    step = json.loads(gzip.decompress(Path(args.interval).read_bytes()))['interval']
    boundaries = A._physical_boundary_index(step)
    native = [V.CartesianCell.from_record(c, budget=budget) for c in partition['native_cells']]
    lines = tuple(tuple(map(W._decode, a)) for a in partition['grid_lines'])
    origin, basis = G._load_vec(partition['grid_origin_m']), tuple(map(G._load_vec, partition['grid_basis']))
    boxes = {at: V.CartesianCell(tuple(lines[j][at[j]] for j in range(3)), tuple(lines[j][at[j]+1] for j in range(3)),
                                 origin, basis, budget=budget)
             for at in product(*(range(len(a)-1) for a in lines))}
    native_at = {at: next((i for i, b in enumerate(native) if A._inside(box, b)), None) for at, box in boxes.items()}
    # Index pass: (voxel, shape) -> logical cell, as the endpoint loop builds component_keys.
    component_keys = {}
    with gzip.open(args.supports, 'rt', encoding='utf8') as f:
        f.readline()
        for line in f:
            r = json.loads(line)
            for part in r['components']:
                component_keys[tuple(r['voxel_index']), (r['source_chart_id'], tuple(part['partition_path']))] = \
                    part['logical_cell_id']
    state = {}
    original_work = B._Arena.work

    def capped_work(self, count):
        if state.get('active') and time.process_time() - state['cpu0'] > state['cap']:
            raise QueryCap('per-query CPU cap')
        if state.get('trace') is not None:
            frame, names = sys._getframe(1), []
            while frame is not None and len(names) < 4:
                names.append(frame.f_code.co_name)
                frame = frame.f_back
            state['trace'].append((count, '<'.join(names), id(self)))
        return original_work(self, count)

    B._Arena.work = capped_work
    if args.trace_leaves:
        # Diagnostic: every geometric-kernel leaf of a moving interface (the Taylor
        # route calls it once per time leaf): time interval, pose level, widths.
        original_leaf = G._moving_interface_leaf

        def traced_leaf(*a):
            t0, t1, level = a[9], a[10], a[11]
            result = original_leaf(*a)
            if state.get('leaves') is not None:
                state['leaves'].append((float(t0), float(t1), level,
                                        [float(hi - lo) for pair in result for lo, hi in [pair]],
                                        round(time.process_time() - state['cpu0'], 3)))
            return result
        G._moving_interface_leaf = traced_leaf
        # ... and every Taylor-route queue entry (its leaf values after the Taylor
        # intersection, and whether a certified event bracket was found).
        import heapq
        import types
        from atlas_tectonics import integration_moving_interface_moments as IM

        def traced_push(queue, entry):
            if state.get('leaves') is not None and len(entry) == 8:
                _, _, a, b, level, values, known, located = entry
                state['leaves'].append(('taylor', float(a), float(b), level,
                                        [float(hi - lo) for lo, hi in values], located is not None,
                                        len(known or ())))
            return heapq.heappush(queue, entry)
        IM.heapq = types.SimpleNamespace(heappush=traced_push, heappop=heapq.heappop)
        # ... and where each Taylor-route branch exit (_Branch) is raised.
        from collections import Counter as _Counter
        state['raises'] = _Counter()
        monitor = sys.monitoring

        def on_raise(code, offset, exception):
            if type(exception).__name__ == '_Branch':
                line = next((ln for start, end, ln in code.co_lines() if start <= offset < end), None)
                site = code.co_filename.rsplit('\\', 1)[-1] + ':' + str(line) + ':' + code.co_name
                state['raises'][site] += 1
                if code.co_name == 'inside' and len(state.setdefault('raise_details', [])) < 12:
                    frame = sys._getframe(1)
                    clip = frame.f_back
                    try:
                        poly = clip.f_locals.get('poly')
                        index = frame.f_locals.get('index')
                        v = frame.f_locals.get('v')
                        state['raise_details'].append(dict(
                            identity=repr(clip.f_locals.get('identity')), index=index, vertices=len(poly),
                            vertex_ids=sorted(map(repr, poly[index][2])) if poly and index is not None else None,
                            value=[float(v[0][0]), float(v[0][1])] if v is not None else None,
                            ids=[sorted(map(repr, p[2])) for p in poly]))
                    except Exception as exc:
                        state['raise_details'].append(dict(error=repr(exc)))
        monitor.use_tool_id(monitor.DEBUGGER_ID, 'replay-trace')
        monitor.register_callback(monitor.DEBUGGER_ID, monitor.events.RAISE, on_raise)
        monitor.set_events(monitor.DEBUGGER_ID, monitor.events.RAISE)
    recorder = None
    if args.progress:
        sys.path.insert(0, str(HERE.parent))
        import geometry_progress
        recorder = geometry_progress.install(G, args.progress, slow_seconds=args.progress_slow,
                                             heartbeat_seconds=args.progress_heartbeat)
    profiler = None
    each, each_files = None, []
    if args.profile_each:
        import cProfile
        each = Path(args.profile_each)
        each.mkdir(parents=True, exist_ok=False)
    elif args.profile:
        import cProfile
        profiler = cProfile.Profile()
    written = 0
    t0 = time.perf_counter()
    from collections import Counter
    counts = Counter()
    with out.open('x', encoding='utf8', newline='\n') as sink, gzip.open(args.supports, 'rt', encoding='utf8') as f:
        f.readline()
        for index, line in enumerate(f):
            if index % args.shards != args.shard:
                continue
            row = json.loads(line)
            support = G._issue(G.DifferentialSupport, row, budget)
            components = {p['logical_cell_id']: (support, row, p) for p in row['components']}
            jobs = []
            if 'wall' in kinds:
                for event in A._exterior_wall_events(components, component_keys, boxes, native_at, {}, boundaries):
                    if 'error' in event:
                        raise event['error']
                    if event['found'] and not (event['native'] or event['other'] is not None):
                        continue   # owned by the angular pass, measured there
                    if event['native'] or (event['other'] is not None and event['key'] > event['other']):
                        continue
                    jobs.append(('wall', event['key'], dict(axis=event['axis'], end=event['end']), None))
            if 'interface' in kinds:
                groups = {}
                for key, (_, r, part) in components.items():
                    omega = G._load_vec(r['material_angular_velocity_rad_s'])
                    for name, sign in part['constraints']:
                        constraint = r['constraints'][name]
                        if G._material_plane(constraint, omega):
                            continue
                        identity = G._interface_identity(constraint)
                        if identity is None:
                            raise ValueError('nonmaterial interface lacks plane authority')
                        groups.setdefault(identity[0], []).append((key, name, sign*identity[1]))
                for entries in groups.values():
                    handled = set()
                    for key, name, sign in entries:
                        opposites = [o for o, _, s in entries if s == -sign]
                        if opposites:
                            for other in opposites:
                                token = tuple(sorted((key, other)))
                                if token not in handled:
                                    handled.add(token)
                                    jobs.append(('interface', key, dict(constraint_name=name), other))
                            continue
                        jobs.append(('interface', key, dict(constraint_name=name), None))
            if args.count_only:
                for kind, key, where, other in jobs:
                    counts[(kind, 'paired' if other else 'single')] += 1
                continue
            for kind, key, where, other in jobs:
                if args.only_cell and not key.startswith(args.only_cell):
                    continue
                if args.only_name and where.get('constraint_name') != args.only_name:
                    continue
                if only_list is not None:
                    job = (index, key[:16], where.get('constraint_name') or (where.get('axis'), where.get('end')))
                    if job not in only_list and (*job, other[:16] if other else None) not in only_pairs:
                        continue
                if only_cells is not None and key[:16] not in only_cells:
                    continue
                state.update(active=True, cpu0=time.process_time(), cap=args.cap_cpu,
                             trace=[] if args.trace_work else None, leaves=[] if args.trace_leaves else None)
                wall0 = time.perf_counter()
                status, result, error = 'met', None, None
                if each is not None:
                    profiler = cProfile.Profile()
                if profiler is not None:
                    profiler.enable()
                try:
                    if kind == 'wall':
                        measure = G.enclose_component_wall(support, key, where['axis'], where['end'],
                            max_width_m3=width, max_leaves=max_leaves, budget=budget)
                    else:
                        pair = {} if other is None else dict(other_support=support, other_logical_cell_id=other)
                        measure = G.enclose_component_interface(support, key, where['constraint_name'],
                            max_width_m3=width, max_leaves=max_leaves, budget=budget, **pair)
                    result = measure.record()
                    del measure
                    if not result.get('met', True):
                        status = 'unmet'
                except QueryCap:
                    status = 'capped'
                except Exception as exc:
                    status, error = 'error', '%s: %s' % (type(exc).__name__, str(exc)[:300])
                finally:
                    state['active'] = False
                    if profiler is not None:
                        profiler.disable()
                rec = dict(kind=kind, support_index=index, cell=key[:16], other=other[:16] if other else None,
                           status=status, cpu_s=round(time.process_time()-state['cpu0'], 4),
                           wall_s=round(time.perf_counter()-wall0, 4), **{k: v for k, v in where.items()})
                if each is not None:
                    name = each / ('%03d-s%d-%s.prof' % (written, index, key[:16]))
                    profiler.dump_stats(str(name))
                    profiler = None
                    each_files.append(name)
                    rec['profile'] = name.name
                if result is not None:
                    rec.update(leaves=result.get('leaves'), work_units=result.get('work_units'), rule=result.get('rule'),
                               inward=result.get('inward_volume_bounds_m3'), outward=result.get('outward_volume_bounds_m3'),
                               measure_sha=sha256(G._encoded(result)).hexdigest()[:16],
                               measure_sha_nodigest=sha256(G._encoded(_blank_digests(result))).hexdigest()[:16])
                if error:
                    rec['error'] = error
                if state.get('trace') is not None:
                    rec['trace'] = state['trace']
                    state['trace'] = None
                if state.get('leaves') is not None:
                    rec['kernel_leaves'] = state['leaves']
                    state['leaves'] = None
                    rec['branch_raises'] = dict(state['raises'])
                    rec['branch_details'] = state.pop('raise_details', [])
                    state['raises'].clear()
                sink.write(json.dumps(rec) + '\n')
                sink.flush()
                written += 1
                if args.max_queries and written >= args.max_queries:
                    break
            if args.max_queries and written >= args.max_queries:
                break
        if args.count_only:
            sink.write(json.dumps(dict(job_counts={'%s/%s' % k: v for k, v in sorted(counts.items())})) + '\n')
        memory = {}
        try:
            import psutil
            info = psutil.Process().memory_info()
            # Windows: peak working set and peak pagefile (commit) of this process's lifetime.
            memory = dict(peak_working_set_bytes=getattr(info, 'peak_wset', None),
                          peak_commit_bytes=getattr(info, 'peak_pagefile', None), rss_bytes=info.rss)
        except Exception as exc:  # diagnostic only
            memory = dict(error=repr(exc))
        sink.write(json.dumps(dict(done=True, queries=written, seconds=time.perf_counter()-t0,
            runtime=args.runtime, cap_cpu=args.cap_cpu, package_digest=rc1_env.package_digest(),
            budget=budget.statistics(), process_memory=memory)) + '\n')
    if recorder is not None:
        geometry_progress.uninstall(G)
    if profiler is not None:
        profiler.dump_stats(args.profile)
    if each_files and args.profile:
        import pstats
        merged = pstats.Stats(str(each_files[0]))
        for name in each_files[1:]:
            merged.add(str(name))
        merged.dump_stats(args.profile)


if __name__ == '__main__':
    main()
