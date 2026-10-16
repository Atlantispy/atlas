"""Does a real wall return the worker ledger to its baseline? (P1 r5 refuter note 4: reopen frequency.)

The worker reopens (decodes the shared inputs again) only when ledger.reserved_bytes differs from
the baseline after a wall. On captured real wall_set calls (capture_walls.py, small case), one
ledger across all walls as in the worker: print reserved bytes before/after each wall.
Usage: reopen_probe.py <candidate frozen:folder> CAPTURE
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402


def main():
    rc1_env.install(sys.argv[1])
    from atlas_tectonics import integration_pressure_walls as W
    from atlas_tectonics import resources as RS
    walls = sorted(Path(sys.argv[2]).glob('wall-*.json'), key=lambda p: int(p.stem.split('-')[1]))
    ledger = RS.WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    calls = []
    for path in walls:
        record = json.loads(path.read_bytes())
        calls.append((W._dec(record['call'], ledger), W._dec(record['args'], ledger)))
    reopen = 0
    for path, (call, args) in zip(walls, calls, strict=True):
        before = ledger.reserved_bytes
        W.wall_set(*call, dict(args, budget=ledger))
        after = ledger.reserved_bytes
        reopen += after != before
        print(path.name, 'reserved before', before, 'after', after, 'REOPEN' if after != before else 'same', flush=True)
    print('walls', len(walls), 'reopens', reopen, flush=True)


if __name__ == '__main__':
    main()
