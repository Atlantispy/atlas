"""Read-only micro-test: exact pose width against the number of accumulated trajectory steps.

Usage: python -B pose_width_steps.py RUNTIME_SRC OUT_JSON

Each interval appends one exact rotation step to every ray's symbolic history
(integration_differential_geometry.current_geometry_from_interval); the end
geometry of interval n is the ORIGINAL ray posed through n steps
(integration_wall_measures._pose_vector), and a boundary's representative pose
is the product of its step quaternions (integration_exterior_mesh._representative_pose).
This calls those unchanged runtime functions with 1..6 identical coaxial steps
(a representative plate rate and a 1 Myr binary64 interval) and records the widest
numerator/denominator bits, to test whether width grows linearly with the step
count (fixed construction depth) or geometrically (nesting).
Nothing is written except OUT_JSON.
"""
import json
import sys
from fractions import Fraction as Q
from pathlib import Path


def bits(values):
    return max(max(abs(v.numerator).bit_length(), v.denominator.bit_length()) for v in values)


def main():
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    out = Path(sys.argv[2])
    from atlas_tectonics import integration_exterior_mesh as E
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_volume_bounds as B
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(1 << 30)
    # A coaxial family: one common axis, a representative plate rate (rad/s).
    axis = (0.36, -0.48, 0.8)
    rate = 3.17e-15
    omega = tuple(Q(float(rate*a)) for a in axis)
    duration = Q(float(3.15576e13))
    ray = tuple(Q(float(v)) for v in (0.6, 0.0, 0.8))
    goal = Q(1, 2**52)
    rows = []
    with B._Arena(budget) as arena:
        for steps in range(1, 7):
            segments = [dict(angular_velocity_rad_s=[V._encoded(q) for q in omega],
                             start_time_s=V._encoded(Q(0)), end_time_s=V._encoded(duration))]*steps
            quaternion, error = E._representative_pose(segments, goal, arena)
            prior = ((omega, duration),)*(steps-1)
            posed = {}
            for level in (0, 24):
                vector, tail = W._pose_vector(ray, omega, duration, duration, level, arena, prior)
                posed[level] = bits(vector)
            rows.append(dict(steps=steps, quaternion_bits=bits(quaternion),
                             posed_ray_bits_level0=posed[0], posed_ray_bits_level24=posed[24],
                             pose_error_bound=float(error)))
            print(rows[-1], flush=True)
    for name in ('quaternion_bits', 'posed_ray_bits_level0', 'posed_ray_bits_level24'):
        values = [r[name] for r in rows]
        steps = [b-a for a, b in zip(values, values[1:])]
        print(name, 'per-step increments', steps, 'ratio last/first', round(values[-1]/values[0], 3))
    out.write_text(json.dumps(dict(omega_rad_s=[float(q) for q in omega], duration_s=float(duration),
                                   goal=str(goal), rows=rows), indent=1), encoding='utf8')


if __name__ == '__main__':
    main()
