"""PROJECTED wall time of the rolling initial-query pass, from adm1's per-query leaves (serial order).

Model: query seconds = A + B*leaves, fitted to adm1's 1,002.5 CPU-s; one-shot batch overhead 3.4 s;
W workers; contiguous batches of size N; at most K batches launched and not yet fully claimed;
the parent claims in order (adoption cost ignored) and a batch's members are adopted only after
its worker exits. Usage: python -B -I simulate.py adm1-queries.json
"""
import json
import sys

rows = json.load(open(sys.argv[1]))
A = 0.05
B = (1002.5-A*len(rows))/sum(r['leaves'] for r in rows)
cost = [A+B*r['leaves'] for r in rows]
OVER = 3.4


def run(W, N, K):
    batches = [cost[i:i+N] for i in range(0, len(cost), N)]
    done = [None]*len(batches)
    free = [0.0]*W            # worker free times
    parent = 0.0              # parent's clock: when it has claimed through batch j-1
    # Event simulation: launch batch j when a worker is free and j < claimed+K.
    t_claimed = []
    for j in range(len(batches)):
        # earliest the K-window allows launching j: when batch j-K is fully claimed
        window = t_claimed[j-K] if j-K >= 0 else 0.0
        w = min(range(W), key=free.__getitem__)
        start = max(free[w], window)
        finish = start+OVER+sum(batches[j])
        free[w] = finish
        done[j] = finish
        parent = max(parent, finish)   # claims in order: waits for batch j
        t_claimed.append(parent)
    return parent


for W in (1, 2, 4, 6):
    print(W, {N: {K: round(run(W, N, K)) for K in (W, 2*W, 3*W)} for N in (8, 12, 16, 24, 32)})
print('serial CPU', round(sum(cost), 1), 'B ms/leaf', round(1000*B, 3))
