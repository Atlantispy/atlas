"""P2 refuter: base moving_wall_integrals per call vs candidate with one _held per wall.

Base = composed-r2 integration_spatial_pressure.py loaded beside the candidate package as
atlas_tectonics.ps_base_spatial (same package imports, so P3's coupling is shared and only P2
differs). For each synthetic wall x pose x width x max_leaves scenario it runs the serial
pattern (native box with density, then each reservoir box without), stopping at the first
exception, and compares every returned value exactly (type + numerator/denominator), every
leaf count, the exception type/args/notes, and the budget statistics (peak, category peaks,
refusals, final reserved). Then: tight budgets at the base peak and peak-1; a numpy value in
the region dicts; and the profiles hazard (held reused with other profiles).
Usage: p2_equiv.py <candidate frozen:folder> <base composed-r2 folder>
"""
import importlib.util
import sys
from fractions import Fraction as Q
from pathlib import Path

import numpy as np

sys.path.insert(0, 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/ps/scripts')
import rc1_env  # noqa: E402

FAILS, COUNTS = [], dict(scenarios=0, ok=0, refused=0, memory=0, calls=0)


def check(name, condition, detail=''):
    if not condition:
        FAILS.append(name)
        print('FAIL', name, detail, flush=True)


def same(x, y):
    if type(x) is not type(y):
        return False
    if type(x) in (tuple, list):
        return len(x) == len(y) and all(same(a, b) for a, b in zip(x, y))
    if type(x) is Q:
        return x.numerator == y.numerator and x.denominator == y.denominator
    if type(x) is dict:
        return list(x) == list(y) and all(same(x[k], y[k]) for k in x)
    return x == y


def main():
    candidate, base = sys.argv[1], Path(sys.argv[2])
    rc1_env.install(candidate)
    from atlas_tectonics import integration_spatial_pressure as P
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.integration_differential_pressure import _KernelPose
    spec = importlib.util.spec_from_file_location('atlas_tectonics.ps_base_spatial',
                                                  base/'src'/'atlas_tectonics'/'integration_spatial_pressure.py')
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    import inspect
    check('base has no _held', '_held' not in inspect.signature(B.moving_wall_integrals).parameters)
    check('candidate has _held', '_held' in inspect.signature(P.moving_wall_integrals).parameters)

    R, rc = Q(10), Q(5)
    I3 = ((Q(1), Q(0), Q(0)), (Q(0), Q(1), Q(0)), (Q(0), Q(0), Q(1)))

    def box(lo, hi, budget):
        return V.CartesianCell(tuple(map(Q, lo)), tuple(map(Q, hi)), budget=budget)

    def fixture(budget, density_ref=Q(3300), extra_key=False):
        cone = ((2, 1, -1), (1, 2, -1), (1, 2, 1), (2, 1, 1))
        cone = tuple(tuple(map(Q, p)) for p in cone)
        specs = [  # (lo, hi, density, side, cone, world_planes, radial)
            ((5, 1, -1), (6, 2, 1), Q(3300), None, (), (), (rc, R)),           # zero anomaly: skipped
            ((6, 2, -1), (7, 3, 1), Q(3310), None, (), (), (rc, R)),
            ((6, Q(1, 2), 0), (7, Q(3, 2), 1), Q(3290), None, (), (), (rc, R)),  # face on z=0
            ((Q(11, 2), 1, -2), (Q(13, 2), 2, -1), Q(3320), None, (), (), (rc, R)),  # off the wall
            ((5, Q(-1, 2), 0), (6, Q(1, 2), 1), Q(3305), None, (), (), (rc, R)),  # straddles y=0
            ((Q(11, 2), Q(1, 2), -1), (Q(15, 2), 3, 1), Q(3250), 0, cone, (), (Q(6), Q(8))),
            ((Q(11, 2), Q(1, 2), -1), (Q(15, 2), 3, 1), Q(3350), 1, (),
             ((Q(1), Q(0), Q(0), Q(7)), (Q(0), Q(1), Q(0), Q(5, 2), Q(1, 1000))), (Q(6), Q(9))),
        ]
        regions = []
        for lo, hi, rho, side, cn, wp, radial in specs:
            r = dict(cell=box(lo, hi, budget), cone=cn, world_planes=wp, _physical_planes=(),
                     radial=radial, density=rho, plate_id=None, side=side)
            if extra_key:
                r['np'] = np.array([1.0, 2.0])
            regions.append(r)
        native = box((5, Q(-1, 2), -2), (Q(15, 2), 3, 1), budget)
        reservoirs = (box((7, 0, -1), (8, 1, 1), budget), box((5, Q(5, 2), -1), (6, Q(7, 2), 1), budget),
                      box((6, 1, 2), (7, 2, 3), budget))
        profile = ((rc, R, density_ref, Q(0)),)
        return regions, native, reservoirs, (profile, profile)

    rot = ((Q(24, 25), Q(-7, 25), Q(0)), (Q(7, 25), Q(24, 25), Q(0)), (Q(0), Q(0), Q(1)))
    poses = dict(
        exact=lambda: _KernelPose(I3, Q(0)),
        exact_rotated=lambda: _KernelPose(rot, Q(0)),
        axis_z=lambda: _KernelPose(rot, Q(1, 10**4), history=(((0, 0, Q(1, 100)), 1),)),
        no_axis=lambda: _KernelPose(rot, Q(1, 10**4)),
        axis_x=lambda: _KernelPose(I3, Q(1, 10**6), history=(((Q(1, 100), 0, 0), 1),)),
    )
    walls = dict(z0=((1, 0, 0), (0, 1, 0)), z0narrow=((2, 1, 0), (1, 2, 0)), y0=((1, 0, 0), (0, 0, 1)),
                 slant=((3, 1, 1), (1, 3, -1)))

    def run(fn, held_mode, wall, pose, regions, native, reservoirs, profiles, width, leaves, budget):
        args = dict(gravity=Q(10), support_radius=rc, radius=R, width=width, max_leaves=leaves, budget=budget)
        held = {} if held_mode else None
        extra = (lambda: dict(_held=held)) if held_mode else (lambda: {})
        out = []
        try:
            out.append(('ok', fn(*wall, profiles, regions, native, pose, **args, **extra())))
            for b in reservoirs:
                out.append(('ok', fn(*wall, profiles, regions, b, pose, compute_density=False, **args, **extra())))
        except Exception as e:  # noqa: BLE001
            out.append(('raise', type(e).__name__, tuple(map(str, e.args)), tuple(getattr(e, '__notes__', ()))))
        stats = budget.statistics()
        return out, dict(peak=stats['peak_reserved_bytes'], cats=stats['category_peaks'],
                         refusals=stats['refusals'], reserved=stats['reserved_bytes'])

    def compare(tag, wall, pose_fn, width, leaves, max_bytes=2**40, extra_key=False):
        results = []
        for fn, mode in ((B.moving_wall_integrals, False), (P.moving_wall_integrals, True)):
            budget = WorkBudget(max_bytes)
            regions, native, reservoirs, profiles = fixture(budget, extra_key=extra_key)
            pose = pose_fn()
            results.append(run(fn, mode, wall, pose, regions, native, reservoirs, profiles, width, leaves, budget))
        (bo, bs), (co, cs) = results
        COUNTS['scenarios'] += 1
        COUNTS['calls'] += len(bo)
        kind = bo[-1][0] if bo[-1][0] == 'ok' else bo[-1][1]
        COUNTS['ok' if kind == 'ok' else ('memory' if kind == 'MemoryLimitError' else 'refused')] += 1
        check(tag+' outputs', same(bo, co), '\n base=%r\n cand=%r' % (bo[-1][:2], co[-1][:2]))
        check(tag+' stats', bs == cs, '\n base=%r\n cand=%r' % (bs, cs))
        return bo, bs

    import os
    smoke = bool(os.environ.get('P2_SMOKE'))
    peaks = []
    for wname, wall in (list(walls.items())[:1] if smoke else walls.items()):
        for pname, pose_fn in (list(poses.items())[:3] if smoke else poses.items()):
            for width in ((Q(10**9),) if smoke else (Q(10**12), Q(10**9), Q(10**7), Q(10**5))):
                for leaves in ((8,) if smoke else (8, 64)):
                    tag = '%s/%s/w=%s/L=%d' % (wname, pname, width, leaves)
                    bo, bs = compare(tag, wall, pose_fn, width, leaves)
                    if bo[-1][0] == 'ok' and width == Q(10**9):
                        peaks.append((tag, wall, pose_fn, width, leaves, bs['peak']))
                    print(tag, 'calls', len(bo), 'last', bo[-1][0] if bo[-1][0] == 'ok' else bo[-1][1:3],
                          'leaves', [o[1][2] for o in bo if o[0] == 'ok'], flush=True)
    # tight budgets: at the base peak both must succeed; at peak-1 both must fail at the same call
    for tag, wall, pose_fn, width, leaves, peak in peaks[:1 if smoke else 6]:
        for mb in (peak, peak-1, peak-65536):
            compare(tag+'/max_bytes=%d' % mb, wall, pose_fn, width, leaves, max_bytes=mb)
    # numpy value in every region dict: the held equality must not raise or refuse
    compare('numpy-key', walls['z0'], poses['axis_z'], Q(10**9), 64, extra_key=True)

    # profiles hazard: held filled with one profile density, reused with another
    budget = WorkBudget(2**40)
    regions, native, reservoirs, prof_a = fixture(budget, density_ref=Q(3300))
    _, _, _, prof_b = fixture(budget, density_ref=Q(3310))
    pose = poses['exact']()
    args = dict(gravity=Q(10), support_radius=rc, radius=R, width=Q(10**8), max_leaves=48, budget=budget)
    held = {}
    P.moving_wall_integrals(*walls['z0'], prof_a, regions, native, pose, _held=held, **args)
    try:
        cand = P.moving_wall_integrals(*walls['z0'], prof_b, regions, reservoirs[0], pose,
                                       compute_density=False, _held=held, **args)
    except Exception as e:  # noqa: BLE001
        cand = ('raise', type(e).__name__)
    fresh = B.moving_wall_integrals(*walls['z0'], prof_b, regions, reservoirs[0], pose, compute_density=False, **args)
    print('PROFILES HAZARD: held reused with other profiles -> candidate', 'refused' if cand[0] == 'raise' else
          ('equal' if same(cand, fresh) else 'DIFFERS silently'), '| removed[2] cand=%s base=%s' % (
              None if cand[0] == 'raise' else cand[1][2], fresh[1][2]))
    print('COUNTS', COUNTS)
    print('FAILS', len(FAILS))
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
