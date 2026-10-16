"""PROJECTION (not a measurement): endpoint-pass wall time under rolling one-shot batches.

Replays the measured per-query wall seconds of a serial endpoint pass, in router order (shard
files in support order), through a simple event model of the rolling schedule:
- the parent walks the queries in order and runs every query no batch holds;
- a free worker takes the next J unassigned queries that the parent will not reach before the
  batch is expected to finish (start-up S + contention K x expected cost, transfer T paid by the
  parent per launch), looking at most H queries ahead of the parent;
- the planner knows only the running mean cost of the queries the parent has run (no oracle);
- a batched query the parent reaches before its batch finishes is waited for;
- a batch whose expected saving is below S + T is not launched (benefit_ratio 1.0).
Policy constants are RC1's defaults (startup 3.0 s, transfer 0.4 s, contention 1.3).
Usage: project_endpoint_batches.py "<shard glob>" [W,J,H ...]
"""
import glob
import json
import sys

S, T, K = 3.0, 0.4, 1.3


def load(pattern):
    rows = []
    for path in sorted(glob.glob(pattern)):
        for line in open(path, encoding='utf8'):
            r = json.loads(line)
            if not r.get('done') and 'job_counts' not in r:
                rows.append((r['support_index'], len(rows), r['wall_s']))
    rows.sort()
    return [r[2] for r in rows]


FREE = -1.0      # owner[] value of a query no batch holds


def simulate(costs, workers, limit, horizon):
    n = len(costs)
    owner = [FREE] * n               # expected finish of the batch holding the query
    free = [0.0] * workers           # when each worker is next free
    now, p, ran, total_ran = 0.0, 0, 0, 0.0
    batches = jobs = 0
    waited = 0.0
    nxt = 0                          # batches are cut in order: first position not yet offered to one
    while p < n:
        if ran >= 16:
            mean = total_ran / ran   # the planner's only estimate: the parent's own running mean
            for w in range(workers):
                if free[w] > now:
                    continue
                # A batch of `limit` queries is ready at `ready`; it starts at the first position at
                # or after `nxt` that the parent (running every free query at the mean) reaches later.
                ready = now + T + S + K * mean * limit
                arrival, start = now, None
                for i in range(p, min(n, p + horizon)):
                    if i >= nxt and owner[i] == FREE and arrival >= ready:
                        start = i
                        break
                    if owner[i] == FREE:
                        arrival += mean
                if start is None:
                    break                # the lookahead is too short to hide a batch
                stop = min(n, start + limit, p + horizon)
                members = [j for j in range(start, stop) if owner[j] == FREE]
                if mean * len(members) < S + T:
                    break                # benefit_ratio 1.0: the batch must save its overhead
                finish = now + T + S + K * sum(costs[j] for j in members)
                now += T                 # the parent pays the transfer of each launch
                for j in members:
                    owner[j] = finish
                free[w] = finish
                nxt = stop
                batches += 1
                jobs += len(members)
        if owner[p] == FREE:
            now += costs[p]
            ran += 1
            total_ran += costs[p]
        elif owner[p] > now:
            waited += owner[p] - now
            now = owner[p]
        p += 1
    return now, batches, jobs, waited


costs = load(sys.argv[1])
print('queries %d serial %.1f s' % (len(costs), sum(costs)))
grid = [tuple(map(int, a.split(','))) for a in sys.argv[2:]] or [
    (2, 32, 64), (2, 512, 4096), (4, 512, 4096), (6, 512, 4096), (6, 1024, 8192), (6, 2048, 16384)]
for w, j, h in grid:
    wall, batches, jobs, waited = simulate(costs, w, j, h)
    print('workers %d jobs/batch %5d horizon %5d: wall %6.1f s (%.2fx)  batches %4d  batched %5d  waited %5.1f s'
          % (w, j, h, wall, sum(costs) / wall, batches, jobs, waited))
