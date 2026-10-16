"""T: bounded replay of saved IV2 endpoint-volume queries under RC1.

Each query runs through the production route: one ComponentVolumeQueries owner
per support and integration_component_volume_auto.measure_endpoint with no
worker controller (serial), no completed-query store, positive_witness=True,
the production width and leaf ceiling. A per-query CPU cap is enforced by a
wrapper around RC1's own _component_volume_certificate (module attribute, not
a file edit); a capped query raises inside the leaf and is recorded as capped.

Per-query progress record (JSONL, one line per query, exclusive create):
support/component/endpoint identity, chart and path, literal count and
carried-depth, leaves evaluated, deepest pose level, leaf outcome counts
(zero / witnessed / undecided), root bounds, final lower/upper/witness/met,
work units, CPU and wall seconds, and the unmet stopping condition.
Inputs are read-only; no store is opened; nothing else is written.
"""
import argparse
import gzip
import json
import sys
import time
from fractions import Fraction as Q
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402


class QueryCap(Exception):
    pass


def iter_supports(path):
    """Supports from a JSONL file (header line, then one support per line)."""
    with gzip.open(path, 'rt', encoding='utf8') as f:
        header = json.loads(f.readline())
        for index, line in enumerate(f):
            yield header, index, json.loads(line)


def snapshot_depth(c):
    d = 0
    while c.get('kind') == 'snapshot-rotated':
        d += 1
        c = c['constraint']
    return d


def fnum(q):
    return float(q) if q is not None else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--supports', required=True, help='IV2 supports JSONL.gz from split_partition.py')
    ap.add_argument('--output', required=True)
    ap.add_argument('--cap-cpu', type=float, default=3.0)
    ap.add_argument('--shard', type=int, default=0)
    ap.add_argument('--shards', type=int, default=1)
    ap.add_argument('--every', type=int, default=1, help='take every k-th support of this shard')
    ap.add_argument('--only', default=None, help='file of "support_index,logical_cell_id,endpoint" lines')
    ap.add_argument('--max-queries', type=int, default=None)
    ap.add_argument('--profile', default=None, help='write cProfile stats here (single shard)')
    ap.add_argument('--runtime', default='rc1', help='rc1, r7 or test:<composition folder>')
    ap.add_argument('--route', choices=('batch', 'public'), default='batch',
                    help='batch: production ComponentVolumeQueries+measure_endpoint (RC1 only); '
                         'public: component_volume_bounds per query (both runtimes)')
    ap.add_argument('--ablate', default='', help='comma list: item15 (padded containment off), '
                    'item11 (cyclic split axis, as r7); test-only attribution switches')
    ap.add_argument('--progress', default=None, help='install G/geometry_progress.py writing this JSONL '
                    '(composition must carry the progress_hooks transform)')
    ap.add_argument('--progress-slow', type=float, default=30.0)
    ap.add_argument('--progress-heartbeat', type=float, default=120.0)
    args = ap.parse_args()
    # Production pins PYTHONHASHSEED=0; parity runs must match it (set order can move work units).
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0, as production does (work units follow set order)')
    if args.runtime == 'r7' and args.route != 'public':
        raise SystemExit('r7 has no batch route; use --route public')
    out = Path(args.output)
    if out.exists():
        raise SystemExit('output exists')
    only = None
    if args.only:
        only = set()
        for line in Path(args.only).read_text().split():
            i, cid, ep = line.split(',')
            only.add((int(i), cid[:16], ep))
    rc1_env.install(args.runtime)
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_wall_measures as W
    if args.route == 'batch':
        from atlas_tectonics import integration_component_volume_auto as E
        from atlas_tectonics.integration_component_volume_batch import ComponentVolumeQueries
    else:
        class ComponentVolumeQueries:
            """Public-route stand-in: one component_volume_bounds call per query."""
            def __init__(self, support, *, budget):
                self.support, self.budget = support, budget

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class E:
            @staticmethod
            def measure_endpoint(owner, controller, key, *, endpoint, max_width_m3, max_leaves,
                                 positive_witness, _funded, _checkpoint):
                return G.component_volume_bounds(owner.support, key, endpoint=endpoint,
                    max_width_m3=max_width_m3, max_leaves=max_leaves,
                    positive_witness=positive_witness, budget=owner.budget)
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    ablate = {a for a in args.ablate.split(',') if a}
    if 'item15' in ablate:
        G._padded_box_contained = lambda *a, **k: False
    if 'item11' in ablate:
        def _cyclic_axis(cell, arena, depth=None, _query=None, _original=G._component_longest_side):
            return _original(cell, arena) if depth is None else depth % 3
        G._component_longest_side = _cyclic_axis
    if ablate - {'item15', 'item11'}:
        raise SystemExit('unknown ablation')
    original = G._component_volume_certificate
    state = {}

    def leaf(layer, cell, literals, constraints, time_, level, arena, **kwargs):
        if time.process_time() - state['cpu0'] > state['cap']:
            raise QueryCap('per-query CPU cap')
        result = original(layer, cell, literals, constraints, time_, level, arena, **kwargs)
        bounds, point, mask, witness = result
        state['leaves'] += 1
        state['max_level'] = max(state['max_level'], level)
        if not bounds[1]:
            state['zero'] += 1
        elif witness:
            state['witnessed'] += 1
        else:
            state['undecided'] += 1
        if state['root'] is None:
            state['root'] = (bounds[0], bounds[1], witness)
        return result

    G._component_volume_certificate = leaf
    recorder = None
    if args.progress:
        sys.path.insert(0, str(HERE.parent))
        import geometry_progress
        recorder = geometry_progress.install(G, args.progress, slow_seconds=args.progress_slow,
                                             heartbeat_seconds=args.progress_heartbeat)
    profiler = None
    if args.profile:
        import cProfile
        profiler = cProfile.Profile()
    written = 0
    t_start = time.perf_counter()
    with out.open('x', encoding='utf8', newline='\n') as sink:
        for header, index, record in iter_supports(args.supports):
            if index % args.shards != args.shard or (index // args.shards) % args.every:
                continue
            width = W._decode(header['max_volume_error_m3'])
            max_leaves = header['max_leaves']
            support = G._issue(G.DifferentialSupport, record, budget)
            if support.support_id != header['support_ids'][index]:
                raise SystemExit('support identity differs from the rebuilt partition list')
            constraints = record['constraints']
            owner = None
            try:
                for part in record['components']:
                    for endpoint in ('start', 'end'):
                        if endpoint == 'start' and part['parent_cell_id'] is None:
                            continue
                        key = part['logical_cell_id']
                        if only is not None and (index, key[:16], endpoint) not in only:
                            continue
                        if owner is None:
                            owner = ComponentVolumeQueries(support, budget=budget)
                            owner.__enter__()
                        state.update(cpu0=time.process_time(), cap=args.cap_cpu, leaves=0, max_level=0,
                                     zero=0, witnessed=0, undecided=0, root=None)
                        wall0 = time.perf_counter()
                        status, result, error = 'met', None, None
                        if profiler is not None:
                            profiler.enable()
                        try:
                            measure = E.measure_endpoint(owner, None, key, endpoint=endpoint, max_width_m3=width,
                                max_leaves=max_leaves, positive_witness=True, _funded=None, _checkpoint=None)
                            result = measure.record()
                            del measure
                            if not result['met']:
                                status = 'unmet'
                        except QueryCap:
                            status = 'capped'
                        except Exception as exc:  # recorded, never hidden
                            status, error = 'error', '%s: %s' % (type(exc).__name__, str(exc)[:300])
                        finally:
                            if profiler is not None:
                                profiler.disable()
                        cpu = time.process_time() - state['cpu0']
                        wall = time.perf_counter() - wall0
                        if status in ('capped', 'error'):
                            owner.__exit__(None, None, None)
                            owner = None
                        lits = part['constraints']
                        row = dict(support_index=index, support_id=support.support_id[:16], full_cell=key,
                            voxel=record['voxel_index'], plate=record['plate_id'], kind=record['kind'],
                            chart=record['source_chart_id'][:16], path=part['partition_path'],
                            parent=part['parent_cell_id'] is not None, cell=key[:16], endpoint=endpoint,
                            literals=len(lits), max_snapshot_depth=max(snapshot_depth(constraints[n]) for n, _ in lits),
                            stored_constraints=len(constraints), status=status, cpu_s=round(cpu, 4), wall_s=round(wall, 4),
                            leaves=state['leaves'], max_level=state['max_level'], zero_leaves=state['zero'],
                            witnessed_leaves=state['witnessed'], undecided_leaves=state['undecided'])
                        if state['root'] is not None:
                            lo, hi, wit = state['root']
                            row['root'] = [fnum(lo), fnum(hi), fnum(wit)]
                        if result is not None:
                            lo, hi, wit = (W._decode(result[k]) for k in ('lower_m3', 'upper_m3', 'positive_witness_m3'))
                            row.update(lower=fnum(lo), upper=fnum(hi), witness=fnum(wit), upper_zero=hi == 0,
                                exact=[result['lower_m3'], result['upper_m3'], result['positive_witness_m3']],
                                full_cell=key,
                                result_leaves=result['leaves'], work_units=result['work_units'],
                                pose_levels=result.get('whole_voxel_pose_levels'),
                                measure_sha=sha256(G._encoded(result)).hexdigest()[:16])
                        else:
                            row['unmet_condition'] = ('no positive witness while upper > 0'
                                if state['undecided'] else 'width or other')
                        if error:
                            row['error'] = error
                        sink.write(json.dumps(row) + '\n')
                        sink.flush()
                        written += 1
                        if args.max_queries and written >= args.max_queries:
                            raise StopIteration
            except StopIteration:
                break
            finally:
                if owner is not None:
                    owner.__exit__(None, None, None)
        memory = {}
        try:
            import psutil
            info = psutil.Process().memory_info()
            memory = dict(peak_working_set_bytes=getattr(info, 'peak_wset', None),
                          peak_commit_bytes=getattr(info, 'peak_pagefile', None), rss_bytes=info.rss)
        except Exception as exc:  # diagnostic only
            memory = dict(error=repr(exc))
        sink.write(json.dumps(dict(done=True, queries=written, seconds=time.perf_counter() - t_start,
            runtime=args.runtime, route=args.route, cap_cpu=args.cap_cpu, ablate=sorted(ablate),
            package_digest=rc1_env.package_digest(), budget=budget.statistics(), process_memory=memory)) + '\n')
    if recorder is not None:
        geometry_progress.uninstall(G)
    if profiler is not None:
        profiler.dump_stats(args.profile)


if __name__ == '__main__':
    main()
