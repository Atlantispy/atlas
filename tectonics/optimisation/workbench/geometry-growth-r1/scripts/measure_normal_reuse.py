"""Measure exact-input repetition of moving-face _normal / _rotated / _clip calls (test-only wrappers).

Runs the selected saved interface queries under the given runtime and reports,
per function: calls, CPU, distinct inputs within each query, and the CPU that
exact per-query reuse could remove (repeat count x first-call cost).
"""
import gzip
import json
import sys
import time
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402


def main():
    supports_path, selection_path, width_num, width_den, runtime = sys.argv[1:6]
    rc1_env.install(runtime)
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_moving_face_moments as TM
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    width = W._decode([width_num, width_den])
    stats = defaultdict(lambda: dict(calls=0, cpu=0.0, keys=defaultdict(Counter), first={}))
    state = dict(query=None, depth=Counter())

    def wrap(name, fn, keyer):
        def wrapped(*args, **kwargs):
            key = sha256(keyer(*args).encode()).hexdigest()
            outer = state['depth'][name] == 0
            state['depth'][name] += 1
            t = time.process_time()
            try:
                return fn(*args, **kwargs)
            finally:
                state['depth'][name] -= 1
                if outer:
                    dt = time.process_time() - t
                    s = stats[name]
                    s['calls'] += 1
                    s['cpu'] += dt
                    s['keys'][state['query']][key] += 1
                    s['first'].setdefault((state['query'], key), dt)
        return wrapped

    TM._normal = wrap('normal', TM._normal, lambda c, bounds, J, arena: repr((json.dumps(c, sort_keys=True, default=str), bounds, type(J.I).__name__)))
    TM._rotated = wrap('rotated', TM._rotated, lambda v, w, bounds, J, arena: repr((v, w, bounds, type(J.I).__name__)))
    selection = [json.loads(l) for l in open(selection_path, encoding='utf8') if l.strip()]
    wanted = {}
    for s in selection:
        wanted.setdefault(s['support_index'], []).append(s)
    total = 0.0
    with gzip.open(supports_path, 'rt', encoding='utf8') as f:
        f.readline()
        for index, line in enumerate(f):
            if index not in wanted:
                continue
            record = json.loads(line)
            support = G._issue(G.DifferentialSupport, record, budget)
            cells = {p['logical_cell_id'][:16]: p['logical_cell_id'] for p in record['components']}
            for s in wanted[index]:
                state['query'] = (index, s['cell'], s['constraint_name'])
                pair = {} if not s.get('other') else dict(other_support=support, other_logical_cell_id=cells[s['other']])
                t = time.process_time()
                G.enclose_component_interface(support, cells[s['cell']], s['constraint_name'],
                    max_width_m3=width, max_leaves=524288, budget=budget, **pair)
                total += time.process_time() - t
    out = dict(total_query_cpu=round(total, 2))
    for name, s in stats.items():
        reusable = sum((n - 1) * s['first'][(q, k)] for q, c in s['keys'].items() for k, n in c.items())
        out[name] = dict(calls=s['calls'], cpu=round(s['cpu'], 2),
                         distinct=sum(len(c) for c in s['keys'].values()), reusable_cpu=round(reusable, 2))
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
