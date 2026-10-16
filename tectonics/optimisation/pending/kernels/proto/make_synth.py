"""Synthetic certification inputs in the capture format (small fixture; no shared input).

Usage: python -B make_synth.py <out dir> <solves> [seed]
Writes 0-NNNNN.pkl pairs: ('solve', matrix, rhs, precision) then
('physical', matrix, keys, base_keys, signed_tau, conversion), as capture/sitecustomize.py does.
Shapes, signs, zeros and denominators vary; a few systems are rank-deficient or
ill-conditioned so the Unresolved paths are exercised as well.
"""
import os
import pickle
import random
import sys
from fractions import Fraction

OUT, COUNT = sys.argv[1], int(sys.argv[2])
rng = random.Random(int(sys.argv[3]) if len(sys.argv) > 3 else 20261016)
PRECISIONS = (320, 640, 1280, 2560)
os.makedirs(OUT, exist_ok=True)


def value():
    kind = rng.random()
    if kind < 0.08:
        return Fraction(0)
    if kind < 0.2:
        return Fraction(rng.randint(-3, 3))
    return Fraction(rng.randint(-10**12, 10**12), rng.randint(1, 10**9))*Fraction(10)**rng.randint(-8, 8)


number = 0
for case in range(COUNT):
    n = rng.randint(1, 9)
    m = n+rng.randint(0, 12)
    matrix = [[value() for _ in range(n)] for _ in range(m)]
    if case % 17 == 5:  # rank-deficient: a repeated column
        for row in matrix:
            row[-1] = row[0]
    if case % 23 == 7:  # nearly dependent
        for row in matrix:
            row[-1] = row[0]+Fraction(1, 10**60)*rng.randint(1, 5)
    rhs = [value() for _ in range(n)]
    precision = PRECISIONS[case % len(PRECISIONS)]
    p = rng.randint(1, 6)
    keys = [('cell', i) for i in range(p)]
    base_keys = (('cell', 0), ('wall', 1)) if case % 3 else (('wall', 7), ('cell', 1))
    physical = [[value() for _ in range(n)] for _ in range(p)]
    conversion = [Fraction(rng.randint(1, 50), rng.randint(1, 7)) for _ in range(p)]
    signed_tau = value()
    for payload in (('solve', matrix, rhs, precision),
                    ('physical', physical, keys, base_keys, signed_tau, conversion)):
        with open(os.path.join(OUT, '0-%05d.pkl' % number), 'wb') as fh:
            pickle.dump(payload, fh, protocol=5)
        number += 1
print('wrote', number, 'files to', OUT)
