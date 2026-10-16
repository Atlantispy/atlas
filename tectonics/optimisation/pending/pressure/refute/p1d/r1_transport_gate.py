"""Refuter p1d, reproducer 1: the r3 transport gate refuses the real small case.

r2 gated the shared wall inputs on their RAW size: size <= PARENT_STORAGE//4 (16 MiB).
r3 (kept in r4) gates on the decoded bound: decoded <= PARENT_STORAGE//4, where
decoded = _decoded_json_capacity(raw)+65536+4*len(raw). For the module's tagged
encoding the capacity counter alone is several times len(raw), so the gate now
caps raw at roughly 1.5-2 MB, below the real small case (ab2/full/report.json:
input_bytes 2921506 on the parallel arm).

This script rebuilds a SUBSET of the real small case's shared inputs from the
captured wall_set calls (ps/cap1/wall-*.json: the regions of 6 real walls, sides
removed, de-duplicated; their rays and poses), runs the candidate's own
_shared_inputs on it and evaluates the r2 and r4 transport gates. Capacity is
additive over regions, so if the subset is refused, the whole stage is refused.
Reads only; writes nothing. Usage: r1_transport_gate.py <frozen:folder> <capture dir> <ab2 report>
"""
import json
import sys
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
sys.path.insert(0, str(T/'ps'/'scripts'))
import rc1_env  # noqa: E402


def main():
    rc1_env.install(sys.argv[1])
    capture, report = Path(sys.argv[2]), Path(sys.argv[3])
    from atlas_tectonics import integration_pressure_walls as W
    from atlas_tectonics import integration_parallel_dispatch as D
    from atlas_tectonics import resources as RS
    from atlas_tectonics.integration_routing_views import _decoded_json_capacity
    budget = RS.WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    regions, seen, walls = [], set(), []
    profiles = native_box = reservoirs = args = None
    for path in sorted(capture.glob('wall-*.json'), key=lambda p: int(p.stem.split('-')[1])):
        record = json.loads(path.read_bytes())
        rays, profiles, selected, native_box, reservoirs, pose = W._dec(record['call'], budget)
        args = dict(W._dec(record['args'], budget), budget=budget)
        sides = {}
        for region in selected:
            plain = {k: v for k, v in region.items() if k != 'side'}
            if region['side'] is not None:
                sides[region['side']] = region['plate_id']
            key = W.canonical(W._enc(plain))
            if key not in seen:
                seen.add(key)
                regions.append(plain)
        walls.append((sides.get(0), sides.get(1), rays, pose, None))
    inputs, ids, size, decoded = W._shared_inputs(walls, regions, profiles, native_box, reservoirs, args)
    raw = b''.join(inputs[i] for i in ids)
    capacity = _decoded_json_capacity(raw)
    share = D.PARENT_STORAGE//4
    r2_gate = size <= share and size <= D.MAX_BATCH_INPUT
    r4_gate = decoded <= share and size <= D.MAX_BATCH_INPUT
    print('subset: walls %d regions %d raw %d capacity %d (%.2f x raw) decoded_bound %d share %d'
          % (len(walls), len(regions), size, capacity, capacity/size, decoded, share))
    print('subset gate: r2 %s   r3/r4 %s' % ('PASS' if r2_gate else 'REFUSE', 'PASS' if r4_gate else 'REFUSE'))
    # The recorded real small-case stage, scaled with the subset's own measured ratio.
    data = json.loads(report.read_text(encoding='utf8'))
    recorded = sorted({arm['walls']['input_bytes'] for arm in data['arms']
                       if arm.get('walls', {}).get('input_bytes')})
    for full in recorded:
        estimate = int(capacity/size*full)+65536+4*full
        print('recorded small-case input_bytes %d (r2 route %s): r2 gate %s; r3/r4 decoded ~%d -> %s'
              % (full, [a['walls']['route'] for a in data['arms'] if a['walls'].get('input_bytes') == full],
                 'PASS' if full <= share else 'REFUSE', estimate, 'PASS' if estimate <= share else 'REFUSE'))
    largest = max(n for n in range(0, share, 4096) if int(capacity/size*n)+65536+4*n <= share)
    print('largest raw input the r3/r4 gate admits at this ratio: ~%d bytes' % largest)
    verdict = (not r4_gate) and r2_gate
    print('REPRODUCED: r3/r4 transport gate refuses inputs r2 admitted' if verdict else 'NOT REPRODUCED')


if __name__ == '__main__':
    main()
