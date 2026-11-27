"""Old route against new route on fixed operands, work_units compared (geometry speed plan)."""
from fractions import Fraction as Q
import math
import unittest
from unittest import mock

from atlas_tectonics.integration.geometry import cone_zero as CZ
from atlas_tectonics.integration.geometry import differential_geometry as DG
from atlas_tectonics.integration.geometry import moving_face_moments as MFM
from atlas_tectonics.integration.geometry import volume_bounds as B
from atlas_tectonics.integration.resources import WorkBudget


def _vec(*v):
    return DG._store_vec(tuple(Q(x) for x in v))


class ConeZeroCarry(unittest.TestCase):
    """G-B: ascending orders with a carry against fresh calls, on both arithmetic routes."""
    OPERANDS = [((Q(1), Q(-2, 3), Q(1, 2)), (Q(1, 3), Q(-1, 4), Q(1, 5)), (Q(2), Q(1), Q(-1, 7))),
                ((Q(3, 2), Q(0), Q(-1)), (Q(0), Q(9, 10), Q(1, 11)), (Q(1, 3), Q(-5), Q(2))),
                ((Q(1), Q(1), Q(1)), (Q(0), Q(0), Q(0)), (Q(1), Q(0), Q(0))),
                ((Q(1), Q(0), Q(0)), (Q(1), Q(1), Q(0)), (Q(0), Q(1), Q(0)))]

    def run_orders(self, carry):
        budget = WorkBudget(1 << 30)
        out = []
        with B._Arena(budget) as arena:
            for u, theta, g in self.OPERANDS:
                state = {} if carry else None
                out.append([CZ.projection_bounds(u, theta, g, arena, order=k, carry=state) for k in CZ.ORDERS])
            return out, arena.work_units, budget.peak_reserved_bytes

    def test_carry_equals_fresh_calls(self):
        for route in ('resident', 'python'):
            with self.subTest(route=route), mock.patch.object(
                    CZ.G.B, '_resident', (lambda: CZ.G.B) if route == 'python' else CZ.G.B._resident):
                old, new = self.run_orders(False), self.run_orders(True)
                self.assertEqual(new, old)
                self.assertGreater(old[1], 0)



def _old_bernstein_range_fraction(coefficients, a, b):
    """cb43e88's general route of _bernstein_range_fraction (four products per scale)."""
    degree = len(coefficients)-1
    power = tuple(DG._sum(DG._product(coefficients[k], (factor, factor))
        for k in range(j, degree+1)
        for factor in (Q(math.comb(k, j))*a**(k-j)*(b-a)**j,)) for j in range(degree+1))
    bernstein = tuple(DG._sum(DG._product(power[k], (factor, factor)) for k in range(j+1)
        for factor in (Q(math.comb(j, k), math.comb(degree, k)),)) for j in range(degree+1))
    return min(lo for lo, _ in bernstein), max(hi for _, hi in bernstein)


class BernsteinWeights(unittest.TestCase):
    """G-E: shared weights and two-product scaling against the old four-product route."""
    COEFFICIENTS = ((Q(1), Q(2)), (Q(-3, 2), Q(-1, 3)), (Q(-1, 5), Q(1, 7)), (Q(0), Q(0)), (Q(-1, 9), Q(1, 9)))

    def test_ranges_equal(self):
        for a, b in ((Q(0), Q(1, 2)), (Q(-1, 3), Q(2, 3)), (Q(1, 4), Q(1, 4))):
            with self.subTest(a=a, b=b):
                expected = (_old_bernstein_range_fraction(self.COEFFICIENTS, a, b) if a != b else
                            DG._sum(DG._product(c, (a**k, a**k)) for k, c in enumerate(self.COEFFICIENTS)))
                self.assertEqual(DG._bernstein_range_fraction(self.COEFFICIENTS, a, b), expected)
                self.assertEqual(DG._bernstein_range(self.COEFFICIENTS, a, b), expected)

    def test_rotation_routes_equal(self):
        vector = ((Q(1, 3), Q(1, 2)), (Q(-1), Q(-2, 3)), (Q(0), Q(1, 5)))
        omega = (Q(1, 7), Q(-1, 5), Q(1, 3))
        with B._Arena(WorkBudget(1 << 30)) as old, B._Arena(WorkBudget(1 << 30)) as new:
            for level in (0, 2):
                self.assertEqual(DG._rotation_boxes(vector, omega, Q(0), Q(1, 2), level, new),
                                 DG._rotation_boxes_fraction(vector, omega, Q(0), Q(1, 2), level, old))
            self.assertEqual(new.work_units, old.work_units)
            self.assertGreater(new.work_units, 0)


class PlaneIdentityMemo(unittest.TestCase):
    """G-D: one identity per fan edge across voxels against per-voxel identities."""

    def test_memo_equals_fresh(self):
        raw = {r: dict(direction=_vec(*d), angular_velocity_rad_s=_vec(0, 0, Q(1, 6)))
               for r, d in (('r0', (1, 0, 0)), ('r1', (0, 1, 0)), ('r2', (1, 1, 1)))}
        rays = {r: DG._ray_parts((DG._load_vec(v['direction']), DG._load_vec(v['angular_velocity_rad_s']),
                                  DG._history(()))) for r, v in raw.items()}
        fans = [('r0', 'r1', 'r2')]
        groups = {0: ('e0', 'e1', 'e2')}
        constraints = {'e%d' % i: dict(kind='moving-ray-edge', rays=[raw[fans[0][i]], raw[fans[0][(i+1) % 3]]])
                       for i in range(3)}
        constraints['x'] = dict(kind='fixed-plane', normal=_vec(0, 0, 1), offset=DG._qtext(Q(0)))
        fresh = DG._ordered_plane_identities(constraints, groups, fans, raw, rays)
        memo = {}
        for _ in range(3):
            self.assertEqual(DG._ordered_plane_identities(constraints, groups, fans, raw, rays, memo), fresh)
        self.assertEqual(len(memo), 3)
        other = dict(raw, r0=dict(raw['r0'], angular_velocity_rad_s=_vec(0, 0, Q(1, 5))))
        moved = {n: dict(c, rays=[other[r] for r in (fans[0][int(n[1])], fans[0][(int(n[1])+1) % 3])])
                 if n != 'x' else c for n, c in constraints.items()}
        moved_rays = dict(rays, r0=DG._ray_parts((DG._load_vec(other['r0']['direction']),
                          DG._load_vec(other['r0']['angular_velocity_rad_s']), ())))
        self.assertEqual(DG._ordered_plane_identities(moved, groups, fans, other, moved_rays, memo),
                         DG._ordered_plane_identities(moved, groups, fans, other, moved_rays))



def _old_gpy_walk(J, a, b):
    """cb43e88's full pair walk of _gpy_mul (after the classes)."""
    ka = [MFM._gpy_class(x) for x in a]
    kb = [MFM._gpy_class(y) for y in b]
    lm, hm, la, ha = J.I.lo.multiply, J.I.hi.multiply, J.I.lo.add, J.I.hi.add
    z0, z1 = J.zero
    result = []
    for k in range(MFM.ORDER+1):
        v0, v1, live = z0, z1, False
        for i in range(k+1):
            kx, ky = ka[i], kb[k-i]
            if kx[0] and ky[0]:
                p0, p1 = MFM._gpy_product(lm, hm, a[i], kx, b[k-i], ky)
                v0, v1, live = la(v0, p0), ha(v1, p1), True
        result.append((v0, v1) if live else J.zero)
    return tuple(result)


class OneCoefficientProduct(unittest.TestCase):
    """G-G J-2: the one-live-coefficient product against the full walk (and its start-at-0 mutant)."""

    def test_equal_to_full_walk(self):
        J = MFM._Jets()
        n = MFM.ORDER+1
        def jet(values):
            return tuple(J.zero if v is None else (J.I.point(v) if type(v) is not tuple else
                         (J.I.point(v[0])[0], J.I.point(v[1])[1])) for v in values)
        full = jet([Q(1, 3), (Q(-1, 7), Q(2, 9)), None, Q(-5, 11)]+[Q(k, 13) for k in range(4, n)])
        cases = []
        for i in (0, 1, 5, n-1):
            one = jet([None]*i+[(Q(-2, 3), Q(1, 5))]+[None]*(n-1-i))
            cases += [(one, full), (full, one), (one, one)]
        for a, b in cases:
            self.assertEqual(MFM._gpy_mul(J, a, b), _old_gpy_walk(J, a, b))
        self.assertEqual(MFM._gpy_mul(J, full, full), _old_gpy_walk(J, full, full))


class _Pose:
    def __init__(self, rotation, error):
        self._rotation, self._error = rotation, error

    def rotation(self):
        return self._rotation


class KeptBackBox(unittest.TestCase):
    """G-F: the kept back-box against a direct _back_box, equal cells for equal values."""

    def test_kept_equals_direct(self):
        from atlas_tectonics.integration.coupling import spatial_pressure as SP
        from atlas_tectonics.integration.geometry import volume as V
        budget = WorkBudget(1 << 30)
        rotation = ((Q(3, 5), Q(-4, 5), Q(0)), (Q(4, 5), Q(3, 5), Q(0)), (Q(0), Q(0), Q(1)))
        pose = _Pose(rotation, Q(1, 1000))
        cells = [V.CartesianCell((Q(0), Q(0), Q(0)), (Q(1), Q(2), Q(3)), budget=budget),
                 V.CartesianCell((Q(-1), Q(0), Q(1)), (Q(1), Q(1), Q(2)), (Q(1), Q(0), Q(0)), budget=budget)]
        twin = V.CartesianCell(cells[0].lower_m, cells[0].upper_m, budget=budget)
        calls = [(c, r, e, ax) for c in cells+[twin] for r in (Q(0), Q(10))
                 for e in (False, True) for ax in (None, (Q(0), Q(0), Q(1)))]
        kept = {}
        for _ in range(2):
            for c, r, e, ax in calls:
                self.assertEqual(SP._kept_back_box(kept, c, pose, r, budget, erode=e, axis=ax),
                                 SP._back_box(c, pose, r, budget, erode=e, axis=ax))
        self.assertEqual(len(kept), 16)
        self.assertEqual(SP._kept_back_box(None, cells[1], pose, Q(10), budget),
                         SP._back_box(cells[1], pose, Q(10), budget))


class IntervalTables(unittest.TestCase):
    """G-H: rotation results shared between jobs in one process against tables off (results and work_units)."""
    VECTOR = tuple((Q(x), Q(x)) for x in (Q(1, 3), Q(-1, 2), Q(2)))
    OMEGA = (Q(1, 7), Q(0), Q(1, 3))
    BOUNDS = (Q(0), Q(1, 2))

    def _jobs(self, cap, classes):
        records = []
        with mock.patch.object(DG, 'ROTATION_TABLE_CAP_BYTES', cap):
            DG._ROTATION_TABLE.clear()
            for name in classes:
                intervals = MFM._RationalIntervals() if name == 'rational' else MFM._Intervals()
                with B._Arena(WorkBudget(1 << 30)) as arena:
                    rotated = MFM._rotated(self.VECTOR, self.OMEGA, self.BOUNDS, MFM._Jets(intervals), arena)
                    boxes = DG._rotation_boxes(self.VECTOR, self.OMEGA, *self.BOUNDS, MFM.POSE_LEVEL, arena)
                    records.append((rotated, boxes, arena.work_units))
            table = DG._ROTATION_TABLE
            return records, (len(table.tables['a']), len(table.tables['b']))

    def test_tables_on_equal_tables_off(self):
        off, off_sizes = self._jobs(None, ['interval', 'rational', 'interval'])
        self.assertEqual(off_sizes, (0, 0))
        for order in (['interval', 'rational', 'interval'], ['rational', 'interval', 'rational']):
            on, sizes = self._jobs(1 << 30, order)
            self.assertEqual(sizes, (1, 2))
            for name, got, want in zip(order, on, self._jobs(None, order)[0], strict=True):
                self.assertEqual(got, want, name)
        self.assertGreater(off[0][2], 0)

    def test_cap_too_small_to_store_changes_nothing(self):
        off, _ = self._jobs(None, ['interval', 'rational'])
        tiny, sizes = self._jobs(1, ['interval', 'rational'])
        self.assertEqual(sizes, (0, 0))
        self.assertEqual(tiny, off)


if __name__ == '__main__':
    unittest.main()
