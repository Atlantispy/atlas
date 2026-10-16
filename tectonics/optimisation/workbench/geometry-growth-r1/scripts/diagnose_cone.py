"""Diagnostic only (float, NOT a certificate): cone interior LP for one saved query at its end time.

Poses every literal with RC1 at the endpoint (level 48), converts the exact
centres to float, and solves max s s.t. s_i n_i.x >= s, |x|_inf <= 1 (homogeneous
cone) and the same with the voxel box. Reports s*, the active literals and the
angular structure (azimuths about z of each plane normal). Read-only.
"""
import gzip
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402

path, want_index, prefix = sys.argv[1], int(sys.argv[2]), sys.argv[3]
rc1_env.install()
import numpy as np  # noqa: E402
from scipy.optimize import linprog  # noqa: E402
from atlas_tectonics import integration_differential_geometry as G  # noqa: E402
from atlas_tectonics import integration_volume as V  # noqa: E402
from atlas_tectonics import integration_wall_measures as W  # noqa: E402
from atlas_tectonics.resources import WorkBudget  # noqa: E402

budget = WorkBudget(1 << 30, max_predicate_work_units=1 << 44)
with gzip.open(path, 'rt', encoding='utf8') as f:
    f.readline()
    for index, line in enumerate(f):
        if index == want_index:
            s = json.loads(line)
            break
comp = next(c for c in s['components'] if c['logical_cell_id'].startswith(prefix))
T = W._decode(s['duration_s'])
rows, names = [], []
with G.B._Arena(budget) as arena:
    for name, sign in comp['constraints']:
        normal, error, offset = G._constraint_pose(s['constraints'][name], T, T, 48, arena)
        n = np.array([float(q) for q in normal]) * sign
        rows.append((n / np.linalg.norm(n), float(error), float(offset) * sign))
        names.append(name)
cell = V.CartesianCell.from_record(s['voxel'], budget=budget)
verts = np.array([[float(q) for q in p] for p in cell._vertices()])
lo, hi = verts.min(axis=0), verts.max(axis=0)
A = np.array([[-r[0][0], -r[0][1], -r[0][2], 1.0] for r in rows])
b = np.array([-r[2] for r in rows])
for label, bounds in (('cone in unit box', [(-1, 1)] * 3), ('cone in voxel', list(zip(lo, hi)))):
    res = linprog(c=[0, 0, 0, -1], A_ub=A, b_ub=b, bounds=bounds + [(None, 1)], method='highs')
    x = res.x[:3] if res.status == 0 else None
    print(label, 'status', res.status, 's* = %.3e' % (-res.fun if res.status == 0 else float('nan')))
    if x is not None:
        slack = [float(r[0] @ x - r[2]) for r in rows]
        print('   x', np.round(x, 6), 'active:', [names[i][:48] for i, v in enumerate(slack) if v < 1e-9 + -res.fun])
for name, r in zip(names, rows):
    az = math.degrees(math.atan2(r[0][1], r[0][0]))
    print('  %-62s n=%s az=%.9f err=%.1e off=%.3e' % (name[:62], np.round(r[0], 6), az, r[1], r[2]))
print('voxel lo', lo, 'hi', hi)
