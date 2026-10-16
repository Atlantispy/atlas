"""G-PY r2: object identity and pickle bytes of mul results vs the unchanged module (refuter RISK, 16 Oct).

Usage: python -B -I check_gpy_identity.py <runtime root (final-f2)> <transformed file> [cases]
For each case, both modules' plain _Jets (same _Intervals, same zero object) multiply the same jets
(mixtures of the jet's zero object, equal-but-distinct zeros, signed zeros, points and intervals).
Compared: for each coefficient whether it IS J.zero, and pickle.dumps of the whole result.
"""
import importlib.util
import pickle
import random
import sys
from decimal import Decimal
from fractions import Fraction

ROOT, FILE = sys.argv[1], sys.argv[2]
CASES = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
sys.path.insert(0, ROOT)
from atlas_tectonics import integration_moving_face_moments as MF  # noqa: E402

spec = importlib.util.spec_from_file_location('atlas_tectonics._gpy_identity', FILE)
NEW = importlib.util.module_from_spec(spec)
spec.loader.exec_module(NEW)
assert NEW._Jets is not MF._Jets and hasattr(NEW, '_gpy_mul') and NEW._Intervals is MF._Intervals
ORDER = MF.ORDER
rng = random.Random(7)


def make(J):
    ivs = J.I

    def coefficient(r):
        if r < 0.35:
            return J.zero
        if r < 0.45:
            return (Decimal(0), Decimal(0))
        if r < 0.5:
            return (Decimal('-0'), Decimal('0.0'))
        if r < 0.65:
            return ivs.point(Fraction(rng.randint(-50, 50), 2**rng.randint(0, 6)))
        q = Fraction(rng.randint(-10**6, 10**6), rng.randint(1, 10**3))
        p = ivs.point(q)
        return (p[0], ivs.hi.add(p[1], Decimal(rng.randint(0, 3))))
    return tuple(coefficient(rng.random()) for _ in range(ORDER+1))


def jets(mod):
    J = mod._Jets(mod._Intervals())
    return J


J0 = jets(MF)
J1 = jets(NEW)
# Same zero object and the same interval algebra in both, so results are comparable by identity.
J1.I, J1.zero, J1.z = J0.I, J0.zero, J0.z
stats = dict(cases=0, gpy_route=0, zero_coefficients=0, bad=0)
for _ in range(CASES):
    a, b = make(J0), make(J0)
    try:
        r0 = J0.mul(a, b)
    except Exception as e:  # noqa: BLE001
        r0 = ('raise', type(e).__name__, str(e))
    try:
        r1 = J1.mul(a, b)
    except Exception as e:  # noqa: BLE001
        r1 = ('raise', type(e).__name__, str(e))
    stats['cases'] += 1
    stats['gpy_route'] += NEW._gpy_mul(J1, a, b) is not None
    if r0 and r0[0] == 'raise' or r1 and r1[0] == 'raise':
        stats['bad'] += r0 != r1
        continue
    same_ids = [c is J0.zero for c in r0] == [c is J0.zero for c in r1]
    stats['zero_coefficients'] += sum(c is J0.zero for c in r0)
    stats['bad'] += not (same_ids and r0 == r1 and pickle.dumps(r0) == pickle.dumps(r1))
print(stats)
sys.exit(0 if stats['bad'] == 0 and stats['gpy_route'] > 0 and stats['zero_coefficients'] > 0 else 1)
