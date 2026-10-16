"""End-to-end differential of the P3 coupling candidate vs base on the real integrators.

wall_integrals (duck-typed cells), _integrate_radial_shell and _integrate_radial_pressure on
small synthetic walls. Compares the exact result (types incl. Fraction internals), exception
type/message/notes, and every budget reservation (count, category, order) plus statistics().
"""
import importlib.util
import json
import sys
import time
from fractions import Fraction as Q
from pathlib import Path
from types import SimpleNamespace

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
BASE = (T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
        /'composed-r2/src/atlas_tectonics/integration_pressure_coupling.py')
sys.path.insert(0, str(T/'ps'/'scripts'))
import rc1_env  # noqa: E402

rc1_env.install('frozen:'+str(T/'ps'/'c'/'full'))
from atlas_tectonics import integration_pressure_coupling as C  # noqa: E402
from atlas_tectonics.resources import WorkBudget  # noqa: E402

spec = importlib.util.spec_from_file_location('atlas_tectonics.ps_base_coupling', BASE)
O = importlib.util.module_from_spec(spec)
spec.loader.exec_module(O)
assert hasattr(C, '_ZERO_PAIR') and not hasattr(O, '_ZERO_PAIR')


class Rec(WorkBudget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log = []

    def reserve(self, count, *, category='work'):
        self.log.append((count, category))
        return super().reserve(count, category=category)


def sig(x):
    if isinstance(x, Q):
        return (type(x).__name__, type(x._numerator).__name__, x._numerator, type(x._denominator).__name__, x._denominator)
    if isinstance(x, (tuple, list)):
        return (type(x).__name__, tuple(sig(v) for v in x))
    return (type(x).__name__, repr(x))


def run(fn):
    budget = Rec(1 << 40)
    start = time.perf_counter()
    try:
        result = ('ok', sig(fn(budget)))
    except Exception as error:  # noqa: BLE001
        result = ('raise', type(error).__name__, str(error), tuple(getattr(error, '__notes__', ())))
    stats = budget.statistics()
    return result, budget.log, json.dumps(stats, sort_keys=True, default=repr), time.perf_counter()-start


def box(lower, upper):
    lower, upper = tuple(map(Q, lower)), tuple(map(Q, upper))
    vertices = tuple((x, y, z) for x in (lower[0], upper[0]) for y in (lower[1], upper[1]) for z in (lower[2], upper[2]))
    eye = tuple(tuple(Q(int(i == j)) for j in range(3)) for i in range(3))
    return SimpleNamespace(vertices_m=vertices, basis=eye, origin_m=(Q(0),)*3, lower_m=lower, upper_m=upper)


R = []


def compare(name, make):
    a = run(lambda budget: make(C, budget))
    b = run(lambda budget: make(O, budget))
    ok = a[0] == b[0] and a[1] == b[1] and a[2] == b[2]
    R.append((name, ok))
    print('%-58s %s  %s  reservations=%d  cand %.2fs base %.2fs' % (
        name, 'SAME' if ok else 'DIFF', a[0][0] if a[0][0] == 'ok' else a[0][:3], len(a[1]), a[3], b[3]), flush=True)
    if not ok:
        print('   cand', str(a[0])[:600], '\n   base', str(b[0])[:600])
        print('   first log diff', next(((i, x, y) for i, (x, y) in enumerate(zip(a[1], b[1])) if x != y), None),
              len(a[1]), len(b[1]))


A, B = (1, 0, 0), (0, 0, 1)
P0 = ((Q(1), Q(5), Q(3000), Q(1000)), (Q(5), Q(10), Q(2500), Q(0)))
P1 = ((Q(1), Q(4), Q(3100), Q(900)), (Q(4), Q(10), Q(2600), Q(0)))
cells = [box((3, -Q(1, 2), 0), (4, Q(1, 2), 1)), box((3, -Q(1, 2), 1), (4, Q(1, 2), 2))]
side_cells = [box((3, 0, 0), (4, 1, 1)), box((3, -1, 1), (4, 0, 2))]   # coincident wall faces: side 0 / side 1
owned = box((3, -Q(1, 2), 0), (4, Q(1, 2), 2))

for width, leaves in ((Q(10**6), 64), (Q(10**5), 128), (Q(2*10**4), 400), (Q(1), 6)):
    compare('wall_integrals straddling w=%s L=%d' % (width, leaves), lambda M, budget, width=width, leaves=leaves:
            M.wall_integrals(A, B, [P0, P1], cells, [3050, 2900], owned, gravity=10, support_radius=1,
                             width=width, max_leaves=leaves, budget=budget))
for width, leaves in ((Q(10**5), 128), (Q(1), 6)):
    compare('wall_integrals side faces w=%s L=%d' % (width, leaves), lambda M, budget, width=width, leaves=leaves:
            M.wall_integrals(A, B, [P0, P1], side_cells, [3000, Q(5201, 2)], owned, gravity=Q(98, 10),
                             support_radius=Q(1, 2), width=width, max_leaves=leaves, budget=budget))
compare('wall_integrals oblique rays w=1e5', lambda M, budget:
        M.wall_integrals((1, 1, 0), (1, 0, 1), [P0, P1], [box((2, 1, 0), (3, 2, 1))], [2950], box((2, 1, 0), (3, 2, 1)),
                         gravity=10, support_radius=1, width=Q(10**5), max_leaves=128, budget=budget))

a3, b3 = tuple(map(Q, A)), tuple(map(Q, B))
poly = ((Q(3), Q(1, 2)), (Q(4), Q(1, 2)), (Q(4), Q(3, 2)), (Q(3), Q(3, 2)))
tri = ((Q(2), Q(0)), (Q(5), Q(0)), (Q(2), Q(3)))
for shape_name, shape in (('square', poly), ('triangle', tri)):
    for bottom, top in ((Q(7, 2), Q(4)), (Q(1), Q(10)), (Q(3), Q(9, 2))):
        for width, leaves in ((Q(1, 10), 64), (Q(1, 10**4), 256), (Q(1, 10**12), 8)):
            compare('_integrate_radial_shell %s [%s,%s] w=%s L=%d' % (shape_name, bottom, top, width, leaves),
                    lambda M, budget, shape=shape, bottom=bottom, top=top, width=width, leaves=leaves:
                    M._integrate_radial_shell(shape, a3, b3, bottom, top, Q(1), width=width, max_leaves=leaves, budget=budget))

profiles = tuple((*row, Q(1, 2)) for profile in (P0, P1) for row in profile)
donor_sets = ((), ((tri, Q(3), Q(9, 2), Q(-500)),), ((poly, Q(1), Q(4), Q(300)), (tri, Q(4), Q(10), Q(-7, 3))))
for k, donors in enumerate(donor_sets):
    for width, leaves in ((Q(10**4), 128), (Q(10), 400), (Q(1, 10**9), 8)):
        compare('_integrate_radial_pressure donors%d w=%s L=%d' % (k, width, leaves),
                lambda M, budget, donors=donors, width=width, leaves=leaves:
                M._integrate_radial_pressure(poly, a3, b3, profiles, donors, Q(1), Q(10), Q(10),
                                             width=width, max_leaves=leaves, budget=budget))

bad = [name for name, ok in R if not ok]
print('E2E', 'PASS' if not bad else 'FAIL %r' % bad, len(R), 'cases', flush=True)
