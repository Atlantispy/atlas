"""R-4 (X06), G3-1: the exact 3D clip finds its rows' largest and least while it makes the rows, in place of two
more passes. The previous `_clip` is rebuilt here from its text; on generated solids (a plane through a vertex, an
edge, a face, missing on either side, one tetrahedron, random boxes) and, if ATLAS_R4_CAPTURE names a capture folder
(calls.jsonl of capture_clip_solids.py), every captured clip, the new one gives the same result (faces, points,
admission rows and totals, or the same refusal), the same admissions in order and the same arena work units.
Mutants of the new lines must change an outcome.
  python -B -I test_exact_clip_r4.py <package parent folder>"""
from fractions import Fraction as Q
import json
import os
from pathlib import Path
import random
import sys
import types
import unittest

if __name__ == '__main__':
    sys.path.insert(0, sys.argv.pop(1))

from atlas_tectonics._exact_runtime import BACKEND  # noqa: E402
from atlas_tectonics.integration import resources as R  # noqa: E402
from atlas_tectonics.integration.geometry import volume as V, volume_bounds as B  # noqa: E402

OLD = '''\
        rows = {point: (num, den) for point, (num, den) in zip(points, _numerators(points, coeff))}
        if max(row[0] for row in rows.values()) <= 0:
            return (), poly
        if min(row[0] for row in rows.values()) >= 0:
            return poly, ()
'''
NEW = '''\
        rows, high, low = {}, 0, 0
        for point, (num, den) in zip(points, _numerators(points, coeff)):
            rows[point] = num, den
            if num > high:
                high = num
            elif num < low:
                low = num
        if high <= 0:
            return (), poly
        if low >= 0:
            return poly, ()
'''
MUTANTS = [
    ('largest never recorded', '                high = num\n', '                pass\n'),
    ('least never recorded', '                low = num\n', '                pass\n'),
    ('early returns on the wrong sign', '            return (), poly\n        if low >= 0:\n            return poly, ()',
     '            return poly, ()\n        if low >= 0:\n            return (), poly'),
]


def module(source, name, like):
    m = types.ModuleType('atlas_tectonics.integration.geometry._r4_' + name)
    m.__file__, m.__package__ = like.__file__, like.__package__
    sys.modules[m.__name__] = m
    exec(compile(source, name, 'exec'), m.__dict__)
    return m


def described(result):
    if not result:
        return ('empty',)
    ids = {id(p) for face in result for p in face}
    values = {p for face in result for p in face}
    return ('poly', tuple(result), result.points, tuple(sorted(result.info.items())),
            result.bits, result.quarters, result.extra, result.unpaid, len(ids) == len(values))


def trace(K, build):
    ledger, original = [], R._admit_budgets

    def recording(count, *budgets, category='work', _optional=False):
        ledger.append((count, category))
        return original(count, *budgets, category=category, _optional=_optional)
    R._admit_budgets = recording
    try:
        with B._Arena(R.WorkBudget(1 << 36)) as arena:
            try:
                steps = build(K, arena)
            except Exception as error:
                steps = [('refused', type(error).__name__, str(error))]
            return steps, ledger, arena.work_units
    finally:
        R._admit_budgets = original


def chain(cell, planes):
    def build(K, arena):
        poly, steps = K._owned_box(cell, arena), []
        for p in planes:
            poly = K._clip(poly, K._plane(p), arena)
            steps.append(described(poly))
            if not poly:
                break
            steps.append(K._volume(poly, arena))
        return steps
    return build


def generated(rng, count=300):
    unit = V.CartesianCell((-1, -1, -1), (1, 1, 1))
    named = [[(Q(1), Q(1), Q(1), Q(3))], [(Q(1), Q(1), Q(0), Q(0))], [(Q(1), Q(1), Q(0), Q(2))],
             [(Q(1), Q(0), Q(0), Q(0)), (Q(0), Q(1), Q(0), Q(0))], [(Q(1), Q(0), Q(0), Q(1))],
             [(Q(1), Q(2), Q(3), Q(7))], [(Q(1), Q(2), Q(3), Q(-7))],
             [(Q(1), Q(1), Q(1), Q(-1)), (Q(-1), Q(0), Q(0), Q(1)), (Q(0), Q(-1), Q(0), Q(1)),
              (Q(0), Q(0), Q(-1), Q(1)), (Q(1), Q(1), Q(1), Q(-2)), (Q(1), Q(0), Q(0), Q(-1, 2))]]
    cases = [chain(unit, planes) for planes in named]
    for _ in range(count):
        lo = tuple(Q(rng.randint(-9, 0), rng.randint(1, 4)) for _ in range(3))
        cell = V.CartesianCell(lo, tuple(x+Q(rng.randint(1, 9), rng.randint(1, 4)) for x in lo))
        planes = [tuple(Q(rng.randint(-6, 6), rng.randint(1, 5)) for _ in range(4)) for _ in range(rng.randint(1, 6))]
        cases.append(chain(cell, planes))
    return cases


def captured(folder):
    def rebuild(K, P):
        points = [tuple(K.mpq(c) for c in p) for p in P['points']]
        poly = K._Poly(tuple(tuple(points[i] for i in face) for face in P['faces']))
        poly.points, poly.info = tuple(points), {p: tuple(r) for p, r in zip(points, P['info'])}
        poly.bits, poly.quarters, poly.extra = (sum(r[k] for r in P['info']) for k in range(3))
        poly.unpaid = P['unpaid']
        return poly
    cases = []
    for line in (Path(folder)/'calls.jsonl').read_text(encoding='utf8').splitlines():
        c = json.loads(line)
        if c['f'] == 'clip':
            plane = tuple(int(t) if kind == 'int' else Q(t) for kind, t in c['plane'])
            cases.append(lambda K, arena, c=c, plane=plane: [described(K._clip(rebuild(K, c['poly']),
                                                                               K._plane(plane), arena))])
    return cases


def first_difference(old, new, cases):
    for n, build in enumerate(cases):
        a, b = trace(old, build), trace(new, build)
        if a != b or any(isinstance(s, tuple) and s[:1] == ('poly',) and not s[-1] for s in a[0]):
            return n
    return None


@unittest.skipUnless(BACKEND == 'gmpy2', 'the GMP twin is not the selected backend')
class R4Clip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from atlas_tectonics.integration.geometry import exact_gmp as X
        cls.X, cls.source = X, Path(X.__file__).read_text(encoding='utf8')
        cls.old = module(cls.source.replace(NEW, OLD), 'old', X)
        cls.cases = generated(random.Random(20261115))
        if os.environ.get('ATLAS_R4_CAPTURE'):
            cls.cases += captured(os.environ['ATLAS_R4_CAPTURE'])

    def test_new_equals_old(self):
        self.assertEqual(self.source.count(NEW), 1)
        self.assertIsNone(first_difference(self.old, self.X, self.cases))

    def test_mutants_change_an_outcome(self):
        for name, old, new in MUTANTS:
            with self.subTest(mutant=name):
                self.assertEqual(NEW.count(old), 1)
                mutant = module(self.source.replace(NEW, NEW.replace(old, new)), 'mutant', self.X)
                self.assertIsNotNone(first_difference(self.old, mutant, self.cases))


if __name__ == '__main__':
    unittest.main()
