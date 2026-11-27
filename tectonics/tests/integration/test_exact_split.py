"""One split in place of two mirror clips (wave 5-6 unit T-4).

`_outside_holes` used to clip each part by the negated plane and then by the plane. It now calls `K._split` once.
In both kernels, over the clip test's generated solids (boxes cut by random planes, and named cuts through a vertex,
an edge, a face, or missing on either side) used as holes, the new partition must equal the two-clip partition
rebuilt here: the same parts (faces, vertex order, admission rows), volumes, arena work units, retained bytes and a
peak reservation no larger. Either half must stay intact when the other is dropped first (shared crossing points).
"""
from fractions import Fraction as Q
import gc
import random
import unittest

from atlas_tectonics._exact_runtime import BACKEND
from atlas_tectonics.integration import resources as R
from atlas_tectonics.integration.geometry import volume as V, volume_bounds as B


def described(result):
    if not result:
        return ('empty',)
    if not hasattr(result, 'info'):
        return ('poly', tuple(result))
    return ('poly', tuple(result), result.points, tuple(sorted(result.info.items())),
            result.bits, result.quarters, result.extra, result.unpaid)


def negated(K, plane):
    return K._plane(tuple(-v for v in getattr(plane, 'source', plane)))


def two_clips(K, poly, holes, arena):
    """`_outside_holes` as it was before T-4."""
    parts = [poly]
    for hole_planes in holes:
        remaining = []
        for part in parts:
            inside = part
            for plane in hole_planes:
                outside = K._clip(inside, negated(K, plane), arena)
                if outside:
                    remaining.append(outside)
                inside = K._clip(inside, plane, arena)
                if not inside:
                    break
        parts = remaining
        if not parts:
            break
    return parts


def run(K, cell, holes, partition):
    budget = R.WorkBudget(1 << 36)
    with B._Arena(budget) as arena:
        try:
            poly = K._owned_box(cell, arena)
            parts = partition(K, poly, [[K._plane(p) for p in hole] for hole in holes], arena)
            outcome = [described(p) for p in parts], [K._volume(p, arena) for p in parts]
        except Exception as error:
            outcome = ('refused', type(error).__name__, str(error))
        return outcome, arena.work_units, budget.reserved_bytes, budget.peak_reserved_bytes


def cases(rng, count=200):
    unit = V.CartesianCell((-1, -1, -1), (1, 1, 1))
    named = [[(Q(1), Q(1), Q(1), Q(3))], [(Q(1), Q(1), Q(0), Q(0))], [(Q(1), Q(1), Q(0), Q(2))],
             [(Q(1), Q(0), Q(0), Q(0)), (Q(0), Q(1), Q(0), Q(0))], [(Q(1), Q(0), Q(0), Q(1))],
             [(Q(1), Q(2), Q(3), Q(7))], [(Q(1), Q(2), Q(3), Q(-7))], [(Q(0), Q(0), Q(0), Q(1))],
             [(Q(0), Q(0), Q(0), Q(-1))], [(Q(0), Q(0), Q(0), Q(0))],
             [(Q(1), Q(1), Q(1), Q(-1)), (Q(-1), Q(0), Q(0), Q(1)), (Q(0), Q(-1), Q(0), Q(1)),
              (Q(0), Q(0), Q(-1), Q(1)), (Q(1), Q(1), Q(1), Q(-2)), (Q(1), Q(0), Q(0), Q(-1, 2))]]
    yield unit, named
    for hole in named:
        yield unit, [hole]
    for _ in range(count):
        lo = tuple(Q(rng.randint(-9, 0), rng.randint(1, 4)) for _ in range(3))
        cell = V.CartesianCell(lo, tuple(x+Q(rng.randint(1, 9), rng.randint(1, 4)) for x in lo))
        yield cell, [[tuple(Q(rng.randint(-6, 6), rng.randint(1, 5)) for _ in range(4))
                      for _ in range(rng.randint(1, 6))] for _ in range(rng.randint(1, 3))]


def kernels():
    yield 'python', B._python
    if BACKEND == 'gmpy2':
        from atlas_tectonics.integration.geometry import exact_gmp
        yield 'gmp', exact_gmp


class SplitTests(unittest.TestCase):
    def test_split_equals_two_clips(self):
        for name, K in kernels():
            for n, (cell, holes) in enumerate(cases(random.Random(20261127))):
                with self.subTest(kernel=name, case=n):
                    old = run(K, cell, holes, two_clips)
                    new = run(K, cell, holes, lambda K, *a: B._outside_holes(*a, K))
                    self.assertEqual(new[:3], old[:3])
                    self.assertLessEqual(new[3], old[3])

    def test_either_half_survives_the_other(self):
        cell = V.CartesianCell((-1, -1, -1), (1, 1, 1))
        plane = (Q(1), Q(2), Q(3), Q(1, 2))
        for name, K in kernels():
            for keep in (0, 1):
                with self.subTest(kernel=name, keep=keep), B._Arena(R.WorkBudget(1 << 36)) as arena:
                    halves = list(K._split(K._owned_box(cell, arena), K._plane(plane), arena))
                    expected = described(halves[keep])
                    del halves[1-keep]
                    gc.collect()
                    self.assertEqual(described(halves[0]), expected)
                    self.assertGreater(K._volume(halves[0], arena), 0)


if __name__ == '__main__':
    unittest.main()
