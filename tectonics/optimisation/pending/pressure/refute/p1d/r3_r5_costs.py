"""Refuter p1d, r5 check: real memory of the transport against its booking, and the reopen drop.

On a subset of the real small case (ps/cap1/wall-*.json, as r1_transport_gate.py):
1. parent: tracemalloc peak of _shared_inputs (the tagged _enc tree, canonical text and
   chunks are built there, before the gate, and nothing books them) and what it retains;
2. worker: tracemalloc peak and retained bytes of _open_ledger (reserve + _decode_shared)
   against the decoded bound it books;
3. reopen (r5 b): after `ledger = shared = None; gc.collect()` with the ExitStack hold still
   open, every decoded CartesianCell is gone (the hold keeps only the old ledger);
4. the r5 gate's headroom: per child_bytes, the raw range the gate admits although the
   decoded bound plus the measured per-wall compute peak (35,722,864 bytes: ab2 r2 worker
   peak_child_ledger; sm7 shows 111,151,468 = 75,428,604 decoded + the same) exceeds it.
Memory only, no timing. Reads only. Usage: r3_r5_costs.py <frozen:folder> <capture dir>
"""
import gc
import json
import sys
import tracemalloc
from contextlib import ExitStack
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
sys.path.insert(0, str(T/'ps'/'scripts'))
import rc1_env  # noqa: E402

PER_WALL = 35722864


def main():
    rc1_env.install(sys.argv[1])
    capture = Path(sys.argv[2])
    from atlas_tectonics import integration_pressure_walls as W
    from atlas_tectonics import integration_parallel_dispatch as D
    from atlas_tectonics import resources as RS
    from atlas_tectonics.integration_volume import CartesianCell
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
        del record
    gc.collect()
    # 1. parent
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    tracemalloc.reset_peak()
    inputs, ids, size, decoded = W._shared_inputs(walls, regions, profiles, native_box, reservoirs, args)
    now, peak = tracemalloc.get_traced_memory()
    print('raw %d decoded_bound %d (%.2f x raw)' % (size, decoded, decoded/size))
    print('1 parent _shared_inputs: transient peak %d (%.2f x raw, %.2f x bound), retained %d (%.2f x raw)'
          % (peak-base, (peak-base)/size, (peak-base)/decoded, now-base, (now-base)/size), flush=True)
    # 2. worker
    gc.collect()
    cells_before = sum(type(o) is CartesianCell for o in gc.get_objects())
    base = tracemalloc.get_traced_memory()[0]
    tracemalloc.reset_peak()
    holds = ExitStack()
    child = 512 << 20
    ledger, shared = W._open_ledger(lambda: RS.WorkBudget(child, max_predicate_work_units=1 << 44),
                                    holds, inputs, ids, decoded)
    now, peak = tracemalloc.get_traced_memory()
    print('2 worker _open_ledger: booked %d (ledger reserved %d), real peak %d (%.2f of booked), retained %d (%.2f of booked)'
          % (decoded, ledger.reserved_bytes, peak-base, (peak-base)/decoded, now-base, (now-base)/decoded), flush=True)
    under = peak-base > ledger.reserved_bytes
    # 3. reopen drop with the hold still open
    def count():
        return sum(type(o) is CartesianCell for o in gc.get_objects())
    gc.collect()
    with_copy = count()
    held = ledger.reserved_bytes
    ledger = shared = None
    gc.collect()
    left = count()
    after = tracemalloc.get_traced_memory()[0]
    print('3 reopen drop: live CartesianCells before open %d, with the decoded copy %d, after drop %d; hold still open %s; traced after drop %d (of %d retained)'
          % (cells_before, with_copy, left, held == decoded, after-base, now-base), flush=True)
    holds.close()
    tracemalloc.stop()
    # 4. gate headroom (the real ratio of this subset)
    ratio = (decoded-65536-4*size)/size
    share = D.PARENT_STORAGE//4
    for child_bytes in (128 << 20, 256 << 20, 512 << 20):
        admitted = [n for n in range(4096, share+1, 4096)
                    if W._transport_fits(n, int(ratio*n)+65536+4*n, child_bytes)]
        starved = [n for n in admitted if int(ratio*n)+65536+4*n+PER_WALL > child_bytes]
        print('4 child_bytes %4d MiB: gate admits raw <= %.2f MB; decoded+per-wall > child for raw in %s'
              % (child_bytes >> 20, max(admitted)/1e6,
                 '(%.2f, %.2f] MB' % (min(starved)/1e6-0.004, max(starved)/1e6) if starved else 'none'), flush=True)
    print('UNDER-BOOKED' if under else 'booking covers the real decode peak', 'decoded cells freed' if left == cells_before < with_copy else 'CELLS RETAINED')


if __name__ == '__main__':
    main()
