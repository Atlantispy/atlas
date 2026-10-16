"""r2 refuter: original vs G-PY r2 mul/div on sparse jets: 'is J.zero' pattern, identity sharing, pickle bytes.

Usage: python -B fuzz_identity.py ORIG_ROOT CAND_FILE [cases] [seed]
"""
import importlib.util
import pickle
import random
import sys
from decimal import Decimal as D

ROOT, FILE = sys.argv[1], sys.argv[2]
CASES = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
SEED = int(sys.argv[4]) if len(sys.argv) > 4 else 3
sys.path.insert(0, ROOT)
from atlas_tectonics import integration_moving_face_moments as MF  # noqa: E402

spec = importlib.util.spec_from_file_location('atlas_tectonics._gpy_refuter_r2b', FILE)
NEW = importlib.util.module_from_spec(spec)
spec.loader.exec_module(NEW)
N = MF.ORDER + 1
ZEROS = [(D(0), D(0)), (D('-0'), D(0)), (D(0), D('-0')), (D('0E+5'), D('0E-3'))]


def coef(rng, J):
    r = rng.random()
    if r < 0.45:
        return J.zero if rng.random() < 0.5 else rng.choice(ZEROS)
    if r < 0.6:
        z = rng.choice([D(0), D('-0')])
        x = D(rng.randint(1, 999)).scaleb(rng.randint(-5, 5))
        return (z, x) if rng.random() < 0.5 else (-x, z)
    x = D(rng.randint(-999, 999)).scaleb(rng.randint(-5, 5))
    y = x if rng.random() < 0.3 else D(rng.randint(-999, 999)).scaleb(rng.randint(-5, 5))
    return (min(x, y), max(x, y))


def shape(r, J):
    """identity structure: which coefficients are J.zero, which Decimal objects repeat."""
    ids = {}
    return ([p is J.zero for p in r], [ids.setdefault(id(x), len(ids)) for p in r for x in p])


rng = random.Random(SEED)
bad = 0
for case in range(CASES):
    Jo, Jn = MF._Jets(), NEW._Jets()
    shared = rng.random() < 0.5
    a = tuple(coef(rng, Jo) for _ in range(N))
    b = tuple(coef(rng, Jo) for _ in range(N))
    if rng.random() < 0.3:
        b = ((D(2), D(3)),) + b[1:]
    if shared:  # the candidate J shares the same zero object, so J.zero coefficients are J.zero in both
        Jn.zero = Jo.zero
        Jn.z = Jo.z
    for op in ('mul', 'div'):
        out = []
        for J in (Jo, Jn):
            try:
                r = getattr(J, op)(a, b)
                out.append(('ok', pickle.dumps(r, 4), shape(r, J)))
            except Exception as e:  # noqa: BLE001
                out.append(('raise', type(e).__name__, str(e)))
        if out[0] != out[1]:
            bad += 1
            if bad <= 3:
                print('DIFF', op, shared, out[0][0], out[1][0], out[0][2:] if out[0][0] == 'ok' else out[0],
                      out[1][2:] if out[1][0] == 'ok' else out[1])
print('cases', CASES, 'differing', bad)
