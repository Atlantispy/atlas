"""Capture real wall_set calls (inputs and results) for contract_planes.py (T/ps, P1 r4).

Runs ab_pressure.py unchanged (its admission and the arms given) with
integration_pressure_walls.wall_set wrapped in THIS process only, once the runtime is
installed. Each parent wall_set call whose selected regions carry a non-empty
_physical_planes is written, up to MAX of them, as OUT/wall-<n>.json: the call's
inputs and its result in the module's own exact tagged encoding (what the workers
receive), the budget limits it ran under, and its parent wall time. Calls are counted
either way (OUT/capture.json). Nothing on disk is changed except OUT.
Usage: capture_walls.py OUT MAX -- <ab_pressure.py arguments>
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ab_pressure  # noqa: E402
import rc1_env  # noqa: E402


def main():
    out, limit = Path(sys.argv[1]), int(sys.argv[2])
    if sys.argv[3] != '--':
        raise SystemExit(__doc__)
    out.mkdir(parents=True, exist_ok=False)
    counts = dict(calls=0, with_planes=0, written=0, plane_pairs=[])
    install = rc1_env.install

    def installed(runtime):
        install(runtime)
        from atlas_tectonics import integration_pressure_walls as W
        original = W.wall_set

        def wall_set(rays, profiles, selected, native_box, reservoirs, pose, args):
            begun = time.perf_counter()
            result = original(rays, profiles, selected, native_box, reservoirs, pose, args)
            seconds = time.perf_counter()-begun
            counts['calls'] += 1
            pairs = sum(len(region.get('_physical_planes') or ()) for region in selected)
            if pairs:
                counts['with_planes'] += 1
                counts['plane_pairs'].append(pairs)
                if counts['written'] < limit:
                    budget = args['budget']
                    stats = budget.statistics()
                    record = dict(
                        call=W._enc((tuple(rays), profiles, list(selected), native_box, tuple(reservoirs), pose)),
                        args=W._enc({k: v for k, v in args.items() if k != 'budget'}),
                        budget_type=type(budget).__name__, budget_statistics=repr(stats),
                        result=W._enc(result), seconds=seconds, plane_pairs=pairs,
                        types=sorted({type(region.get('_physical_planes')).__name__ for region in selected}))
                    (out/('wall-%d.json' % counts['written'])).write_bytes(W.canonical(record))
                    counts['written'] += 1
            return result
        W.wall_set = wall_set
    rc1_env.install = installed
    sys.argv = ['ab_pressure.py']+sys.argv[4:]
    try:
        ab_pressure.main()
    finally:
        (out/'capture.json').write_text(json.dumps(counts), encoding='utf8')
        print('CAPTURE', json.dumps({k: v for k, v in counts.items() if k != 'plane_pairs'}),
              'pairs per call', counts['plane_pairs'][:20], flush=True)


if __name__ == '__main__':
    main()
