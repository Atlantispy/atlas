"""Unit tests r2 for H5a (transforms/h5a_prepare_reuse.py). r1 (test_h5a_prepare_reuse.py, log
evidence/test-h5a-r1.log) passed 9 of 10; its EmptyMesh test was wrong, not the patch: the real ``_prepare``
refuses an empty payload ('Distinct nonempty cell and face inventories required'), in r5 and r6 alike.

r2 reruns r1's TransformTests and ReuseDecision unchanged (imported from r1) and replaces EmptyMesh with:
1. EmptyRefusal: the empty payload is refused with the same error by r5 reconstruct, r6 reconstruct and r6
   prepare_shared, and nothing stays reserved.
2. CubeMesh: the REAL ``_prepare`` on one unit-cube cell with six exterior faces (two point-temperature, four
   outward-power):
   - r5 ``_prepare`` and r6 ``prepare_shared`` build equal prepared values;
   - r5 reconstruct, r6 with the shared copy (twice, as the forward does) and r6 without it give equal rows
     and evidence apart from 'seconds';
   - with the shared copy, 'heat-functional-geometry' is never booked; the copy is booked once under
     'heat-functional-geometry-shared'; without it r6 books 'heat-functional-geometry' as r5 does;
   - everything is released once the owners close.
Light: one cell, no face reconstruction (selected_faces=()), no W4 case run.
"""
import sys
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_h5a_prepare_reuse as T1  # noqa: E402

TransformTests = T1.TransformTests
ReuseDecision = T1.ReuseDecision
WorkBudget, load, call = T1.WorkBudget, T1.load, T1.call
FUN5, FUN6 = T1.FUN5, T1.FUN6
HALF = Fraction(1, 2)


def enc(value):
    value = Fraction(value)
    return [format(value.numerator, 'x') if value.numerator >= 0 else '-'+format(-value.numerator, 'x'),
            format(value.denominator, 'x')]


def cube():
    faces, incidence = [], []
    for axis in range(3):
        for side in (0, 1):
            fid = 'f%d%d' % (axis, side)
            centre = [HALF]*3
            centre[axis] = Fraction(side)
            normal = [0, 0, 0]
            normal[axis] = 1 if side else -1
            faces.append(dict(face_id=fid, owners=['c0'], centroid_m=[enc(v) for v in centre],
                              area_vector_m2=[enc(v) for v in normal]))
            incidence.append([fid, 1])
    cells = [dict(cell_id='c0', centroid_m=[enc(HALF)]*3, faces=incidence)]
    return dict(cells=cells, faces=faces), {'f00', 'f01'}, {'f10', 'f11', 'f20', 'f21'}


def booked(budget):
    stats = budget.statistics()
    return stats['reserved_bytes'], set(stats['category_peaks'])


class EmptyRefusal(unittest.TestCase):
    def test_same_refusal_and_nothing_held(self):
        old = load('private_heat_functionals_kernel_r5_h5a_r2e', FUN5)
        new = load('private_heat_functionals_kernel_r6_h5a_r2e', FUN6)
        budget = WorkBudget(1 << 34)
        payload = dict(cells=[], faces=[])
        messages = []
        for attempt in (lambda: old.reconstruct(payload, boundary_point_faces=set(), boundary_power_faces=set(),
                                                budget=budget, selected_faces=()),
                        lambda: new.reconstruct(payload, boundary_point_faces=set(), boundary_power_faces=set(),
                                                budget=budget, selected_faces=(), prepared_shared=None),
                        lambda: new.prepare_shared(payload, set(), set(), 1, budget=budget)):
            with self.assertRaises(ValueError) as caught:
                attempt()
            messages.append(str(caught.exception))
        self.assertEqual(messages, ['Distinct nonempty cell and face inventories required']*3)
        self.assertEqual(booked(budget)[0], 0)


class CubeMesh(unittest.TestCase):
    def setUp(self):
        self.old = load('private_heat_functionals_kernel_r5_h5a_r2c', FUN5)
        self.new = load('private_heat_functionals_kernel_r6_h5a_r2c', FUN6)
        self.payload, self.point, self.power = cube()

    def test_prepared_values_equal(self):
        budget = WorkBudget(1 << 34)
        reference = self.old._prepare(self.payload, self.point, self.power, 1, budget=budget, cancelled=None)
        shared = self.new.prepare_shared(self.payload, self.point, self.power, 1, budget=budget)
        try:
            self.assertEqual(shared.value, reference.value)
            self.assertEqual(len(shared.value['geometry']), 6)
            self.assertEqual(sum('beta' in g for g in shared.value['geometry'].values()), 4)
        finally:
            shared.close()
            reference.close()
        self.assertEqual(booked(budget)[0], 0)

    def test_rows_evidence_and_bookings(self):
        b5 = WorkBudget(1 << 34)
        reference = call(self.old_shim(), self.payload, self.point, self.power, 1, b5, None)
        held5, cats5 = booked(b5)
        self.assertEqual(held5, 0)
        self.assertTrue({'heat-functional-geometry', 'heat-functional-retained-rows'} <= cats5, cats5)
        self.assertNotIn('heat-functional-geometry-shared', cats5)

        b6 = WorkBudget(1 << 34)
        shared = self.new.prepare_shared(self.payload, self.point, self.power, 1, budget=b6)
        first = call(self.new, self.payload, self.point, self.power, 1, b6, shared)
        second = call(self.new, self.payload, set(self.point), set(self.power), 1, b6, shared)
        self.assertEqual(shared.uses, 2)
        shared.close()
        # The plain geometry booking never happens with the shared copy; everything else is r5's.
        self.assertEqual(booked(b6), (0, (cats5-{'heat-functional-geometry'}) | {'heat-functional-geometry-shared'}))

        b6p = WorkBudget(1 << 34)
        plain = call(self.new, self.payload, self.point, self.power, 1, b6p, None)
        self.assertEqual(booked(b6p), booked(b5))
        self.assertEqual(first, reference)
        self.assertEqual(second, reference)
        self.assertEqual(plain, reference)

    def old_shim(self):
        old = self.old
        return T1.types.SimpleNamespace(reconstruct=lambda *a, prepared_shared, **k: old.reconstruct(*a, **k))


if __name__ == '__main__':
    unittest.main()
