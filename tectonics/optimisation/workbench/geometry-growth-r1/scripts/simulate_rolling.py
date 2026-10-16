"""PROJECTION: interval-2 interface wall hours for a parent plus W rolling-batch workers.

A simplified model of RC1's rolling schedule (integration_parallel_rolling.py docstring;
policy defaults in integration_parallel_selection.py): the parent walks the jobs in router
order; whenever a worker is free it takes the next unclaimed contiguous batch, cut at
`batch_seconds` of cost (at most twice that, at most `batch_jobs` jobs), starting at the
first position where the parent would arrive no earlier than the worker would finish,
within `horizon` jobs of the parent. A worker's batch takes startup + contention*cost and
its result is handed over with `transfer`; the parent adopts a batch on reaching it,
waiting if it is not finished. Costs are the measured CPU seconds per query (taken as
perfectly known, which flatters the schedule; the real one learns them). The full job list
is the 1-in-10 support sample with each sampled support's jobs repeated `scale` times in
place (the same ratio estimator as project_interfaces.py), so support 880-like clusters are
kept contiguous. Not modelled: estimate errors, the schedule's pay/stop verdicts,
parent slowdown while workers run, memory gates.
Usage: simulate_rolling.py --sample GLOB --deep GLOB --total-jobs N [--workers 0,2,4,6]
       [--contention 1.0,1.3] [--batch-seconds 20]
"""
import argparse
import glob
import json
from collections import OrderedDict


def load(pattern):
    rows = {}
    for path in sorted(glob.glob(pattern)):
        for line in open(path, encoding='utf8'):
            r = json.loads(line)
            if r.get('kind') == 'interface':
                rows[(r['support_index'], r['cell'], r.get('other'), r['constraint_name'])] = r
    return rows


def jobs_in_order(sample, deep, scale):
    by_support = OrderedDict()
    for key in sorted(sample, key=lambda k: (k[0], k[1], k[2] or '', k[3])):
        r = sample[key]
        cost = r['cpu_s'] if r['status'] == 'met' else deep[key]['cpu_s']
        by_support.setdefault(key[0], []).append(cost)
    whole, carry = [], 0.0
    for costs in by_support.values():
        carry += scale
        copies = int(carry)
        carry -= copies
        for _ in range(copies):
            whole.extend(costs)
    return whole


def simulate(costs, workers, *, contention, startup=3.0, transfer=0.4, batch_seconds=20.0,
             batch_jobs=512, horizon=4096):
    n = len(costs)
    prefix = [0.0]
    for c in costs:
        prefix.append(prefix[-1]+c)
    claimed = [None]*n           # finish time of the batch holding the job
    free = [0.0]*workers         # when each worker is next free
    parent, position, batches = 0.0, 0, 0
    while position < n:
        # Hand out batches to every worker free by the parent's current time.
        for w in range(workers):
            if free[w] > parent:
                continue
            # First unclaimed start where the parent arrives no earlier than this batch finishes.
            start, arrive = position, parent
            limit = min(n, position+horizon)
            while start < limit:
                if claimed[start] is not None:
                    start += 1
                    continue
                end, cost = start, 0.0
                while end < limit and claimed[end] is None and end-start < batch_jobs and cost < batch_seconds:
                    cost += costs[end]
                    end += 1
                finish = parent+startup+contention*cost+transfer
                if arrive >= finish:
                    for j in range(start, end):
                        claimed[j] = finish
                    free[w] = finish
                    batches += 1
                    break
                arrive += costs[start]   # the parent would run this job itself
                start += 1
            else:
                continue
        # The parent runs or adopts the next job.
        if claimed[position] is None:
            parent += costs[position]
        else:
            parent = max(parent, claimed[position])
        position += 1
    return parent, batches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', required=True)
    ap.add_argument('--deep', required=True)
    ap.add_argument('--total-jobs', type=int, required=True)
    ap.add_argument('--workers', default='0,2,4,6')
    ap.add_argument('--contention', default='1.0,1.3')
    ap.add_argument('--batch-seconds', type=float, default=20.0)
    args = ap.parse_args()
    sample, deep = load(args.sample), load(args.deep)
    scale = args.total_jobs/len(sample)
    costs = jobs_in_order(sample, deep, scale)
    out = dict(jobs=len(costs), serial_hours=round(sum(costs)/3600, 2), largest_job_s=round(max(costs), 1),
               scale=round(scale, 3), runs=[])
    for contention in (float(x) for x in args.contention.split(',')):
        for workers in (int(x) for x in args.workers.split(',')):
            wall, batches = simulate(costs, workers, contention=contention, batch_seconds=args.batch_seconds)
            out['runs'].append(dict(workers=workers, contention=contention, wall_hours=round(wall/3600, 2),
                                    speedup=round(sum(costs)/wall, 2), batches=batches))
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
