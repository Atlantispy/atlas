"""Worker-count parity: RC1's own surface router with automatic workers, records compared across counts.

Drives integration_differential_ale._route_exterior_surfaces exactly as _enclose does for its
wall and interface passes:
- one shared predicate-mode budget, and the selected supports issued on it;
- the router's own grid boxes, native lookup and boundary index;
- S.open_automatic(policy=InterfaceParallelPolicy(workers=N, ...)) for .session/.observer;
- the router's callbacks through the ALE module's own _compact_wall/_compact_interface with
  the same _funded claims;
- then session/automatic close and finish.
Every issued record (measure_id and canonical sha) and every stream entry the router adds
is written in router order, plus the selection's decision summary (workers started,
batches, adopted). Comparing these files across N (1, 2, 4, 6) is the parity: adopted
results must be byte-identical. PYTHONHASHSEED=0 required.
Usage: parallel_parity.py --runtime test:<folder> --supports S --partition GRID --interval I
       --stream-width NUM DEN --workers N [--minimum-seconds 1] [--support-list FILE|--shard k --shards n]
       --output OUT.json
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


def encode(x, depth=0):
    """Exact, deterministic stream encoding: integers and fractions in hex, containers recursively.

    repr() would print big rationals in decimal, which Python refuses past 4,300 digits (IV2's
    exact widths reach about 16k bits). The interpreter limit is left as it is.
    """
    from dataclasses import fields, is_dataclass
    from fractions import Fraction
    if depth > 64:
        raise ValueError('stream value nested too deeply')
    if x is None or isinstance(x, (bool, str, float)):
        return x
    if isinstance(x, Fraction):
        return ['Q', hex(x.numerator), hex(x.denominator)]
    if isinstance(x, int):
        return ['I', hex(x)]
    if isinstance(x, (tuple, list)):
        return [type(x).__name__, [encode(v, depth+1) for v in x]]
    if isinstance(x, dict):
        items = [[encode(k, depth+1), encode(v, depth+1)] for k, v in x.items()]
        return ['D', sorted(items, key=lambda kv: json.dumps(kv[0]))]
    if isinstance(x, (set, frozenset)):
        return ['S', sorted((encode(v, depth+1) for v in x), key=json.dumps)]
    if is_dataclass(x):
        return ['O', type(x).__name__, [[f.name, encode(getattr(x, f.name), depth+1)] for f in fields(x)]]
    if hasattr(x, '__dict__'):
        return ['O', type(x).__name__, [[k, encode(v, depth+1)] for k, v in sorted(vars(x).items())]]
    return ['R', type(x).__name__, repr(x)]


class Streams:
    def __init__(self):
        self.rows = []

    def add(self, *args, **kwargs):
        self.rows.append(['add', encode(args), encode(dict(kwargs))])

    def exchange(self, *args, **kwargs):
        self.rows.append(['exchange', encode(args), encode(dict(kwargs))])

    def keep(self, row):
        self.rows.append(['keep', encode(row)])


class Concurrency:
    """Read-only sampler of how many batch workers actually run at once.

    Every 10 ms it reads (never calls into or patches) each rolling controller's live session:
    the number of its batches whose worker has not finished, and the session's pool size. Every
    50 ms it also counts this process's direct child processes and their total working set.
    Patching the session instead would trip the strict execution context's callable check.
    """

    def __init__(self, observer, interval=0.01):
        import threading
        import psutil
        self.observer, self.interval, self.me = observer, interval, psutil.Process()
        self.controllers, self.peak_children, self.peak_children_mib = {}, 0, 0
        self.halt = threading.Event()
        self.thread = threading.Thread(target=self.run, name='parity-sampler', daemon=True)
        self.thread.start()

    def run(self):
        tick = 0
        while not self.halt.wait(self.interval):
            for name in ('wall_batches', 'interface_batches'):
                session = getattr(getattr(self.observer, name, None), 'session', None)
                batches = getattr(session, 'batches', None)
                if batches is None:
                    continue
                live = sum(not batch['child'].done.is_set() for batch in list(batches))
                row = self.controllers.setdefault(name, dict(peak_live=0, session_workers=set(), samples=0))
                row['samples'] += 1
                row['peak_live'] = max(row['peak_live'], live)
                row['session_workers'].add(getattr(session, 'workers', None))
            tick += 1
            if tick % 5 == 0:
                try:
                    children = self.me.children(recursive=True)
                    mib = sum(c.memory_info().rss for c in children) / 2**20
                except Exception:
                    continue
                self.peak_children = max(self.peak_children, len(children))
                self.peak_children_mib = max(self.peak_children_mib, round(mib))

    def stop(self):
        self.halt.set()
        self.thread.join()
        controllers = {k: dict(v, session_workers=sorted(v['session_workers'], key=str))
                       for k, v in self.controllers.items()}
        return dict(controllers=controllers, peak_child_processes=self.peak_children,
                    peak_children_rss_mib=self.peak_children_mib)


# The router's finite-boundary bookkeeping for unpaired moving interfaces needs the interval's
# actual finite stocks, which an offline replay does not hold. Only that block is removed, from
# RC1's own source at run time; every routing, observer, session and claim call stays RC1's.
BOUNDARY_START = "            if (key, name) in represented:\n                raise second\n            found = {b['boundary_id']"
BOUNDARY_END = "                boundary_exchanges.append((candidates[0], key, 'export', outward, ident, boundary['boundary_id'], plane))\n"


def router_without_boundary_bookkeeping(A):
    import inspect
    import textwrap
    source = textwrap.dedent(inspect.getsource(A._route_exterior_surfaces))
    start = source.index(BOUNDARY_START)
    end = source.index(BOUNDARY_END) + len(BOUNDARY_END)
    if source.count(BOUNDARY_START) != 1 or source.count(BOUNDARY_END) != 1:
        raise SystemExit('router boundary block anchors changed')
    source = source[:start] + "            continue  # harness: finite-boundary bookkeeping skipped\n" + source[end:]
    namespace = dict(vars(A))
    exec(compile(source, '<harness router>', 'exec'), namespace)
    return namespace['_route_exterior_surfaces']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runtime', required=True)
    ap.add_argument('--supports', required=True)
    ap.add_argument('--partition', required=True, help='grid file (make_grid_file.py)')
    ap.add_argument('--interval', required=True)
    ap.add_argument('--stream-width', nargs=2, required=True)
    ap.add_argument('--workers', type=int, required=True)
    ap.add_argument('--minimum-seconds', type=float, default=None,
                    help='policy minimum_seconds (lower it so short test windows engage workers)')
    ap.add_argument('--support-list', default=None, help='JSON list of support indices to route')
    ap.add_argument('--mode', default='auto', choices=('auto', 'serial', 'off'))
    ap.add_argument('--profile-store', default=None,
                    help='policy profile_path (a serial pass writes it; each auto arm gets its own copy)')
    ap.add_argument('--shard', type=int, default=0)
    ap.add_argument('--shards', type=int, default=1)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    out = Path(args.output)
    if out.exists():
        raise SystemExit('output exists')
    if Path(args.partition).stat().st_size > 1 << 20:
        raise SystemExit('pass the grid file, not a whole partition')
    rc1_env.install(args.runtime)
    # The route (1) runner's import roots (composed-r1/manifest.json layout): helpers (rc1_env),
    # ram and the heat-repair test fixtures; the execution identity imports every package module.
    sys.path.append(str(HERE.parents[1] / 'composed-r1' / 'ram'))
    sys.path.append(str(HERE.parents[4] / 'heat-repair-20261007' / 'source' / 'tectonics' / 'tests'))
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_differential_ale as A
    from atlas_tectonics import integration_parallel_selection as S
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import require_strict_execution
    require_strict_execution()
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    width = W._decode(args.stream_width)
    max_leaves = 524288
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
    wanted = set(json.loads(Path(args.support_list).read_text())) if args.support_list else None
    components, component_keys = {}, {}
    with gzip.open(args.supports, 'rt', encoding='utf8') as f:
        f.readline()
        for index, line in enumerate(f):
            if wanted is not None and index not in wanted:
                continue
            if wanted is None and index % args.shards != args.shard:
                continue
            row = json.loads(line)
            support = G._issue(G.DifferentialSupport, row, budget)
            for part in row['components']:
                components[part['logical_cell_id']] = (support, row, part)
                component_keys[tuple(row['voxel_index']), (row['source_chart_id'], tuple(part['partition_path']))] = \
                    part['logical_cell_id']
    policy_kwargs = dict(mode=args.mode, workers=args.workers)
    if args.minimum_seconds is not None:
        policy_kwargs['minimum_seconds'] = args.minimum_seconds
    if args.profile_store:
        policy_kwargs['profile_path'] = args.profile_store
    route = router_without_boundary_bookkeeping(A)
    policy = S.InterfaceParallelPolicy(**policy_kwargs)
    records, streams = [], Streams()

    def retain(measure):
        record = measure.record()
        records.append([measure.measure_id, sha256(G._encoded(record)).hexdigest(), record.get('met')])
        return measure.measure_id, record

    automatic = S.open_automatic(budget=budget, max_width_m3=width, max_leaves=max_leaves, policy=policy)
    session, observer = automatic.session, automatic.observer
    sampler = Concurrency(observer)
    t0, c0 = time.perf_counter(), time.process_time()
    error = None
    try:
        route(components, component_keys, boxes, native_at, {}, boundaries, {}, streams,
            wall=lambda support, key, axis, end: retain(A._compact_wall(support, key, axis, end,
                max_width_m3=width, max_leaves=max_leaves, budget=budget,
                _funded=getattr(getattr(observer, 'wall_batches', None), 'claim', None))),
            interface=lambda support, key, name, **pair: retain(A._compact_interface(support, key, name,
                max_width_m3=width, max_leaves=max_leaves, budget=budget,
                _funded=session.claim if session is not None and not getattr(session, 'closed', False)
                else getattr(getattr(observer, 'interface_batches', None), 'claim', None), **pair)),
            _parallel=session, _observer=observer)
    except Exception as exc:
        import traceback
        error = '%s: %s' % (type(exc).__name__, str(exc)[:500])
        print(''.join(traceback.format_exception(exc))[-3000:], file=sys.stderr)
    finally:
        try:
            if session is not None:
                session.close()
        finally:
            try:
                automatic.close()
            finally:
                automatic.finish()
    wall, cpu = time.perf_counter()-t0, time.process_time()-c0
    concurrency = sampler.stop()
    decision = S.last_decision()
    summary = {}
    if isinstance(decision, dict):
        for k in ('mode', 'reason', 'detail', 'batch_workers', 'rolling', 'plan',
                  'wall_parallel', 'interface_batches', 'endpoint_batches',
                  'gates', 'interface_route', 'profile'):
            if k in decision:
                summary[k] = decision[k]
    import psutil
    info = psutil.Process().memory_info()
    report = dict(workers_policy=args.workers, minimum_seconds=args.minimum_seconds, components=len(components),
                  records=len(records), streams=len(streams.rows), wall_s=round(wall, 2), parent_cpu_s=round(cpu, 2),
                  error=error, records_sha256=sha256(json.dumps(records).encode()).hexdigest(),
                  streams_sha256=sha256(json.dumps(streams.rows).encode()).hexdigest(),
                  concurrency=concurrency, parent_peak_working_set_mib=round(info.peak_wset/2**20),
                  decision=summary, record_list=records, package_digest=rc1_env.package_digest())
    out.write_text(json.dumps(report, default=str), encoding='utf8')
    print(json.dumps({k: report[k] for k in ('workers_policy', 'components', 'records', 'streams', 'wall_s',
                                             'parent_cpu_s', 'error', 'records_sha256', 'streams_sha256',
                                             'concurrency', 'parent_peak_working_set_mib')}))


if __name__ == '__main__':
    main()
