"""Measure exact-input repetition of _rotation_boxes and _bernstein_range on saved interface queries.

Wraps the two RC1 functions (test-only module attribute wrappers) to record a hash
of each call's exact inputs and its own CPU time, then runs the selected queries
exactly as profile_interfaces.py does. Prints calls, distinct inputs and the CPU
share that exact reuse could remove (within a query, and within the process).
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


class QueryCap(Exception):
    pass


def main():
    supports_path, selection_path, width_num, width_den, cap = sys.argv[1:6]
    cap = float(cap)
    rc1_env.install()
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_volume_bounds as B
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    width = W._decode([width_num, width_den])
    stats = {name: dict(calls=0, cpu=0.0, per_query=defaultdict(Counter), global_=Counter(), first_cost={})
             for name in ('rotation', 'bernstein')}
    state = dict(query=None, depth=0)

    def wrap(name, fn):
        def wrapped(*args, **kwargs):
            key = sha256(repr(args[:4] if name == 'rotation' else args).encode()).hexdigest()
            outer = state['depth'] == 0
            state['depth'] += 1
            t = time.process_time()
            try:
                return fn(*args, **kwargs)
            finally:
                state['depth'] -= 1
                dt = time.process_time() - t
                s = stats[name]
                if outer or name == 'bernstein':
                    s['calls'] += 1
                    s['cpu'] += dt
                    s['per_query'][state['query']][key] += 1
                    s['global_'][key] += 1
                    s['first_cost'].setdefault(key, dt)
        return wrapped

    G._rotation_boxes = wrap('rotation', G._rotation_boxes)
    G._bernstein_range = wrap('bernstein', G._bernstein_range)
    original = B._Arena.work

    def capped(self, count):
        if state.get('active') and time.process_time() - state['cpu0'] > cap:
            raise QueryCap()
        return original(self, count)

    B._Arena.work = capped
    selection = [json.loads(l) for l in open(selection_path, encoding='utf8') if l.strip()]
    wanted = {}
    for s in selection:
        wanted.setdefault(s['support_index'], []).append(s)
    total_cpu = 0.0
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
                state.update(active=True, cpu0=time.process_time())
                try:
                    G.enclose_component_interface(support, cells[s['cell']], s['constraint_name'],
                        max_width_m3=width, max_leaves=524288, budget=budget, **pair)
                except QueryCap:
                    pass
                finally:
                    state['active'] = False
                    total_cpu += time.process_time() - state['cpu0']
    out = dict(total_query_cpu=round(total_cpu, 2))
    for name, s in stats.items():
        distinct_q = sum(len(c) for c in s['per_query'].values())
        repeated_q_cost = sum((n - 1) * s['first_cost'][k] for c in s['per_query'].values() for k, n in c.items())
        repeated_g_cost = sum((n - 1) * s['first_cost'][k] for k, n in s['global_'].items())
        out[name] = dict(calls=s['calls'], cpu=round(s['cpu'], 2), distinct_within_queries=distinct_q,
                         distinct_in_process=len(s['global_']),
                         reusable_cpu_within_query=round(repeated_q_cost, 2),
                         reusable_cpu_in_process=round(repeated_g_cost, 2))
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
