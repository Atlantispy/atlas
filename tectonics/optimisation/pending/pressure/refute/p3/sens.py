"""Sensitivity of unit_ps.py's P3 section: its exact loop (same seed, same 20000 draws) against a mutant.

Usage: sens.py <mutant module path>. Prints the number of failing checks.
"""
import importlib.util
import random
import sys
from fractions import Fraction as Q
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
BASE = (T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
        /'composed-r2/src/atlas_tectonics/integration_pressure_coupling.py')
sys.path.insert(0, str(T/'ps'/'scripts'))
import rc1_env  # noqa: E402
import unit_ps as U  # noqa: E402

rc1_env.install('frozen:'+str(T/'ps'/'c'/'full'))


def load(name, path):
    spec = importlib.util.spec_from_file_location('atlas_tectonics.'+name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


O = load('ps_base_coupling', BASE)
C = load('ps_mutant_coupling', Path(sys.argv[1]))
U.check = lambda name, condition: None if condition else U.FAILS.append(name)
agree, value, rational = U.agree, U.value, U.rational
rng = random.Random(20261016)
for _ in range(20000):
    a = (value(rng), value(rng))
    b = (value(rng), value(rng))
    if rng.random() < 0.5:
        a = tuple(sorted(a))
    if rng.random() < 0.5:
        b = tuple(sorted(b))
    if rng.random() < 0.05:
        a = (a[0], a[0])
    agree('_mul', C._mul, O._mul, a, b)
    q = rng.choice((rng.randint(-5, 5), rational(rng)))
    agree('_scale', C._scale, O._scale, a, q)
    agree('_scale3', C._scale, O._scale, (value(rng), value(rng), value(rng)), q)
    agree('_dyadic', C._dyadic_outward, O._dyadic_outward, a, 1 << rng.randint(0, 200))
    z = rng.choice(((0, 0), (Q(0), Q(0)), (Q(0), 0), (Q(1), Q(0))))
    jet = ((a[0], a[0] if rng.random() < 0.5 else a[1]), z, rng.choice(((0, 0), (Q(0), Q(0)), z)))
    agree('_jet_is_constant', C._jet_is_constant, O._jet_is_constant, jet)
    jet = (tuple(sorted(a)), tuple(sorted(b)), tuple(sorted((value(rng), value(rng)))))
    agree('_jet_outward', C._jet_outward, O._jet_outward, jet)
for odd in ((), (Q(1),), (Q(1), Q(2), Q(3)), [Q(1), Q(2)], (1.5, Q(2)), ('x', 'y')):
    agree('_mul-odd', C._mul, O._mul, odd, (Q(1), Q(2)))
    agree('_scale-odd', C._scale, O._scale, odd, 3)
kinds = sorted({name.split('(')[0] for name in U.FAILS})
print('SENS %s unit_ps-P3 failures=%d kinds=%s' % (Path(sys.argv[1]).stem, len(U.FAILS), kinds), flush=True)
