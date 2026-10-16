"""Endpoint worker parity (WP18 part 1): RC1's endpoint pass with the automatic endpoint route.

Drives the endpoint loop of integration_differential_ale._enclose exactly:
- one shared predicate-mode budget, the selected supports issued on it as a tuple (the
  non-compact DifferentialPartition.supports);
- S.open_automatic(policy=InterfaceParallelPolicy(workers=N, mode, ...)) and
  E.open_automatic_endpoints(automatic, max_volume_error_m3), as the ALE does;
- RoutingArena + SupportRoutingRows; controller.prepare(supports); per support in order:
  rows.project, E.bind_support, ComponentVolumeQueries, and per component and endpoint
  E.measure_endpoint(..., positive_witness=True, _funded=controller.claim, _checkpoint=None),
  each record read through rows.measure_record as the ALE's retain() does;
- then controller close, automatic close and finish.
Nothing is patched (workers load the runtime's own code). Every issued record (measure_id,
canonical sha, met) is written in router order; comparing these lists across modes and worker
counts is the parity: adopted results must be byte-identical. PYTHONHASHSEED=0 required.
Usage: endpoint_parity.py --runtime test:<folder> --supports S --stream-width NUM DEN
       --workers N [--mode auto|serial] [--minimum-seconds S] [--shard k --shards n] --output OUT.json
"""
import argparse
import gzip
import json
import sys
import threading
import time
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402


class Sampler:
    """Read-only: every 10 ms, how many of the endpoint session's batches are still running;
    every 50 ms, this process's child processes: count, largest single RSS and their total RSS
    (the measured worker peak that later memory bookings should use)."""

    def __init__(self, controller, interval=0.01):
        import psutil
        self.controller, self.interval, self.me = controller, interval, psutil.Process()
        self.peak_live, self.samples, self.workers = 0, 0, set()
        self.peak_children = self.peak_child_mib = self.peak_children_mib = 0
        self.halt = threading.Event()
        self.thread = threading.Thread(target=self.run, name='endpoint-sampler', daemon=True)
        self.thread.start()

    def run(self):
        tick = 0
        while not self.halt.wait(self.interval):
            tick += 1
            if tick % 5 == 0:
                try:
                    rss = [c.memory_info().rss for c in self.me.children(recursive=True)]
                except Exception:
                    rss = None
                if rss:
                    self.peak_children = max(self.peak_children, len(rss))
                    self.peak_child_mib = max(self.peak_child_mib, round(max(rss)/2**20))
                    self.peak_children_mib = max(self.peak_children_mib, round(sum(rss)/2**20))
            session = getattr(self.controller, 'session', None)
            batches = getattr(session, 'batches', None)
            if batches is None:
                continue
            self.samples += 1
            self.peak_live = max(self.peak_live, sum(not b['child'].done.is_set() for b in list(batches)))
            self.workers.add(getattr(session, 'workers', None))

    def stop(self):
        self.halt.set()
        self.thread.join()
        return dict(peak_live=self.peak_live, samples=self.samples, session_workers=sorted(self.workers, key=str),
                    peak_child_processes=self.peak_children, peak_single_child_rss_mib=self.peak_child_mib,
                    peak_children_rss_mib=self.peak_children_mib)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runtime', required=True)
    ap.add_argument('--supports', required=True, help='supports JSONL.gz (header line first)')
    ap.add_argument('--stream-width', nargs=2, required=True, help='the ALE max_stream_error_m3 (open_automatic)')
    ap.add_argument('--workers', type=int, required=True)
    ap.add_argument('--mode', default='auto', choices=('auto', 'serial', 'off'))
    ap.add_argument('--minimum-seconds', type=float, default=None,
                    help='policy minimum_seconds (lower it so a short test window engages workers)')
    ap.add_argument('--shard', type=int, default=0)
    ap.add_argument('--shards', type=int, default=1)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    out = Path(args.output)
    if out.exists():
        raise SystemExit('output exists')
    rc1_env.install(args.runtime)
    # The same import roots as parallel_parity.py: ram and the heat-repair test fixtures, because
    # the execution identity imports every package module.
    sys.path.append(str(HERE.parents[1] / 'composed-r1' / 'ram'))
    sys.path.append(str(HERE.parents[4] / 'heat-repair-20261007' / 'source' / 'tectonics' / 'tests'))
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_parallel_selection as S
    from atlas_tectonics import integration_component_volume_auto as E
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.integration_component_volume_batch import ComponentVolumeQueries
    from atlas_tectonics.integration_routing_views import RoutingArena, SupportRoutingRows
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import require_strict_execution
    require_strict_execution()
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    stream_width = W._decode(args.stream_width)
    selected = []
    with gzip.open(args.supports, 'rt', encoding='utf8') as f:
        header = json.loads(f.readline())
        for index, line in enumerate(f):
            if index % args.shards == args.shard:
                support = G._issue(G.DifferentialSupport, json.loads(line), budget)
                if support.support_id != header['support_ids'][index]:
                    raise SystemExit('support identity differs from the partition list')
                selected.append(support)
    supports = tuple(selected)
    del selected
    width, max_leaves = W._decode(header['max_volume_error_m3']), header['max_leaves']
    policy_kwargs = dict(mode=args.mode, workers=args.workers)
    if args.minimum_seconds is not None:
        policy_kwargs['minimum_seconds'] = args.minimum_seconds
    policy = S.InterfaceParallelPolicy(**policy_kwargs)
    records, error = [], None
    automatic = S.open_automatic(budget=budget, max_width_m3=stream_width, max_leaves=max_leaves, policy=policy)
    controller = E.open_automatic_endpoints(automatic, width)
    sampler = Sampler(controller)
    t0, c0 = time.perf_counter(), time.process_time()
    try:
        with RoutingArena(budget) as arena:
            rows = SupportRoutingRows(supports, budget, arena)
            if controller is not None:
                controller.prepare(supports)
            for support in supports:
                row = rows.project(support)
                E.bind_support(controller, support, row)
                with ComponentVolumeQueries(support, budget=budget) as volumes:
                    for part in row['components']:
                        key = part['logical_cell_id']
                        for endpoint in ('start', 'end'):
                            if endpoint == 'start' and part['parent_cell_id'] is None:
                                continue
                            measure = E.measure_endpoint(volumes, controller, key, endpoint=endpoint,
                                max_width_m3=width, max_leaves=max_leaves, positive_witness=True,
                                _funded=None if controller is None else controller.claim, _checkpoint=None)
                            record = rows.measure_record(measure)
                            records.append([measure.measure_id, sha256(G._encoded(record)).hexdigest(),
                                            record.get('met')])
                            del measure, record
            if controller is not None:
                controller.close()
    except Exception as exc:
        import traceback
        error = '%s: %s' % (type(exc).__name__, str(exc)[:500])
        print(''.join(traceback.format_exception(exc))[-3000:], file=sys.stderr)
    finally:
        try:
            if controller is not None:
                controller.close()
        finally:
            try:
                if automatic.session is not None:
                    automatic.session.close()
            finally:
                try:
                    automatic.close()
                finally:
                    automatic.finish()
    wall, cpu = time.perf_counter()-t0, time.process_time()-c0
    concurrency = sampler.stop()
    decision = S.last_decision()
    summary = {k: decision[k] for k in ('mode', 'reason', 'detail', 'batch_workers', 'endpoint_batches', 'gates')
               if isinstance(decision, dict) and k in decision}
    import psutil
    info = psutil.Process().memory_info()
    report = dict(workers_policy=args.workers, mode=args.mode, minimum_seconds=args.minimum_seconds,
                  supports=len(supports), records=len(records), wall_s=round(wall, 2), parent_cpu_s=round(cpu, 2),
                  error=error, records_sha256=sha256(json.dumps(records).encode()).hexdigest(),
                  concurrency=concurrency, parent_peak_working_set_mib=round(info.peak_wset/2**20),
                  decision=summary, record_list=records, package_digest=rc1_env.package_digest())
    out.write_text(json.dumps(report, default=str), encoding='utf8')
    print(json.dumps({k: report[k] for k in ('workers_policy', 'mode', 'supports', 'records', 'wall_s',
                                             'parent_cpu_s', 'error', 'records_sha256', 'concurrency',
                                             'parent_peak_working_set_mib')}))
    batches = (summary.get('endpoint_batches') or {})
    print(json.dumps(dict(route=batches.get('route'), reason=batches.get('reason'), started=batches.get('started'),
                          jobs=batches.get('jobs'), adopted=batches.get('adopted'), declined=batches.get('declined'),
                          workers=batches.get('workers'), lookahead_supports=batches.get('lookahead_supports'),
                          peak_child_rss=batches.get('peak_child_rss'), peak_child_ledger=batches.get('peak_child_ledger'))))


if __name__ == '__main__':
    main()
