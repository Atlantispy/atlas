"""Profile a set of saved IV2 interface queries in one process (cProfile, bounded per query).

Each selected query (support index, logical cell prefix, constraint name, paired
cell prefix or None) runs RC1's enclose_component_interface exactly as
replay_surfaces.py does, with a CPU cap enforced through the arena's work
admission. Writes the cumulative profile and a JSONL of per-query outcomes.
"""
import cProfile
import gzip
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402


class QueryCap(Exception):
    pass


def main():
    supports_path, selection_path, width_num, width_den, out_prefix, cap = sys.argv[1:7]
    runtime = sys.argv[7] if len(sys.argv) > 7 else 'rc1'
    cap = float(cap)
    rc1_env.install(runtime)
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_volume_bounds as B
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    width = W._decode([width_num, width_den])
    selection = [json.loads(l) for l in open(selection_path, encoding='utf8') if l.strip()]
    wanted = {}
    for s in selection:
        wanted.setdefault(s['support_index'], []).append(s)
    state = {}
    original = B._Arena.work

    def capped(self, count):
        if state.get('active') and time.process_time() - state['cpu0'] > cap:
            raise QueryCap()
        return original(self, count)

    B._Arena.work = capped
    profiler = cProfile.Profile()
    rows = []
    with gzip.open(supports_path, 'rt', encoding='utf8') as f:
        f.readline()
        for index, line in enumerate(f):
            if index not in wanted:
                continue
            record = json.loads(line)
            support = G._issue(G.DifferentialSupport, record, budget)
            cells = {p['logical_cell_id'][:16]: p['logical_cell_id'] for p in record['components']}
            for s in wanted[index]:
                key = cells[s['cell']]
                pair = {} if not s.get('other') else dict(other_support=support, other_logical_cell_id=cells[s['other']])
                state.update(active=True, cpu0=time.process_time())
                status = 'met'
                profiler.enable()
                try:
                    measure = G.enclose_component_interface(support, key, s['constraint_name'],
                        max_width_m3=width, max_leaves=524288, budget=budget, **pair)
                    result = measure.record()
                except QueryCap:
                    status, result = 'capped', None
                finally:
                    profiler.disable()
                    state['active'] = False
                rows.append(dict(s, status=status, cpu_s=round(time.process_time()-state['cpu0'], 3),
                                 leaves=None if result is None else result.get('leaves')))
    profiler.dump_stats(out_prefix + '.prof')
    Path(out_prefix + '.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf8')
    print(json.dumps(rows, indent=0)[:3000])


if __name__ == '__main__':
    main()
