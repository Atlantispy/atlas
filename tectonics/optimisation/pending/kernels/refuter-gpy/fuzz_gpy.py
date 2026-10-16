"""Refuter fuzz: original vs G-PY moving-face _Jets.mul/div on the same inputs.

Usage: python -B fuzz_gpy.py ORIG_ROOT CAND_FILE [cases] [seed]
Compares per call: every endpoint's Decimal.as_tuple(), exception type + str, lo/hi context
flags and the thread-local context flags. Contexts vary (prec, Emin/Emax, traps); the thread
context's InvalidOperation trap varies too.
"""
import decimal
import importlib.util
import random
import sys
from decimal import Context, Decimal as D, ROUND_FLOOR, ROUND_CEILING

ROOT, FILE = sys.argv[1], sys.argv[2]
CASES = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
SEED = int(sys.argv[4]) if len(sys.argv) > 4 else 1
sys.path.insert(0, ROOT)
from atlas_tectonics import integration_moving_face_moments as MF  # noqa: E402

spec = importlib.util.spec_from_file_location('atlas_tectonics._gpy_refuter_cand', FILE)
NEW = importlib.util.module_from_spec(spec)
spec.loader.exec_module(NEW)
assert NEW._Jets is not MF._Jets and hasattr(NEW, '_gpy_mul') and not hasattr(MF, '_gpy_mul')
assert NEW._Intervals is MF._Intervals
ORDER = MF.ORDER
SIGNALS = [decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow, decimal.Underflow,
           decimal.Subnormal, decimal.Inexact, decimal.Rounded, decimal.Clamped]


def rand_dec(rng, emax):
    r = rng.random()
    if r < 0.05:
        return D(rng.choice(['0', '-0', '0E+3', '-0E-7', '0.00']))
    if r < 0.12:
        return D(rng.choice(['1', '1.0', '1.00', '-1', '-1.0', '2', '2.000', '0.5', '0.50']))
    digits = rng.choice([1, 2, 5, 20, 80, 85])
    coeff = rng.randint(1, 10**digits)
    if rng.random() < 0.2:
        coeff *= 10**rng.randint(1, 5)  # trailing zeros
    exp = rng.randint(-30, 30) if rng.random() < 0.9 else rng.choice([rng.randint(-emax-120, -emax+60), rng.randint(emax-90, emax)])
    return D((rng.random() < 0.5, tuple(map(int, str(coeff))), exp))


def coefficient(rng, emax):
    r = rng.random()
    if r < 0.12:
        return rng.choice([(D(0), D(0)), (D('-0'), D(0)), (D(0), D('-0')), (D('-0'), D('-0')), (D('0E+5'), D('0E-3'))])
    x = rand_dec(rng, emax)
    if r < 0.30:
        return (x, x) if rng.random() < 0.5 else (x, x.normalize(Context(prec=200, Emax=10**8, Emin=-10**8, traps=[])) if x.is_finite() else x)
    if r < 0.45:
        z = D(rng.choice(['0', '-0', '0E+2', '-0E-4']))
        return (z, x.copy_abs()) if rng.random() < 0.5 else (x.copy_abs().copy_negate(), z)
    y = rand_dec(rng, emax)
    lo, hi = sorted((x, y))
    if r < 0.52:
        return (hi, lo)  # improper
    return (lo, hi)


def jet(rng, emax):
    return tuple(coefficient(rng, emax) for _ in range(ORDER + 1))


def snap(J):
    return (tuple(sorted(s.__name__ for s in SIGNALS if J.I.lo.flags[s])),
            tuple(sorted(s.__name__ for s in SIGNALS if J.I.hi.flags[s])),
            tuple(sorted(s.__name__ for s in SIGNALS if decimal.getcontext().flags[s])))


def run(J, op, a, b):
    decimal.getcontext().clear_flags()
    try:
        out = getattr(J, op)(a, b)
        res = ('ok', tuple((p[0].as_tuple(), p[1].as_tuple()) for p in out))
    except Exception as e:  # noqa: BLE001
        res = ('raise', type(e).__name__, str(e))
    return res, snap(J)


def make(module, params):
    J = module._Jets()
    if params is not None:
        J.I.lo = Context(rounding=ROUND_FLOOR, **params)
        J.I.hi = Context(rounding=ROUND_CEILING, **params)
    return J


def main():
    rng = random.Random(SEED)
    stats = dict(cases=0, raises=0, bad=0)
    examples = []
    for case in range(CASES):
        if rng.random() < 0.4:
            params, emax = None, 999999
        else:
            emax = rng.choice([20, 60, 999999])
            params = dict(prec=rng.choice([3, 8, 30, 80]), Emax=emax, Emin=-emax,
                          traps=[s for s in SIGNALS if rng.random() < 0.12])
        thread_trap = rng.random() < 0.5
        decimal.getcontext().traps[decimal.InvalidOperation] = thread_trap
        a, b = jet(rng, emax), jet(rng, emax)
        for op in ('mul', 'div'):
            if op == 'div' and rng.random() < 0.7:
                lead = rng.choice([(D(3), D(5)), (D('-7'), D('-0.5')), (D('0.1'), D('0.10')), (D(2), D(1)),
                                   (D('1E-15'), D('1E+15'))])
                b2 = (lead,) + b[1:]
            else:
                b2 = b
            Jo, Jn = make(MF, params), make(NEW, params)
            ro, rn = run(Jo, op, a, b2), run(Jn, op, a, b2)
            stats['cases'] += 1
            stats['raises'] += ro[0][0] == 'raise'
            if ro != rn:
                stats['bad'] += 1
                if len(examples) < 3:
                    examples.append(dict(op=op, params=params, thread_trap=thread_trap, a=a, b=b2, old=ro, new=rn))
            # chain once with the old result (exponents as produced in use)
            if ro[0][0] == 'ok' and op == 'mul':
                c = Jo.mul(a, b2) if False else tuple((D(p[0]), D(p[1])) for p in ro[0][1])
                for x, y in ((c, a), (a, c)):
                    Jo, Jn = make(MF, params), make(NEW, params)
                    r1, r2 = run(Jo, 'mul', x, y), run(Jn, 'mul', x, y)
                    stats['cases'] += 1
                    if r1 != r2:
                        stats['bad'] += 1
                        if len(examples) < 3:
                            examples.append(dict(op='mul-chain', params=params, a=x, b=y, old=r1, new=r2))
    decimal.getcontext().traps[decimal.InvalidOperation] = True
    print(stats)
    for e in examples:
        print('EXAMPLE', e['op'], e.get('params'), e.get('thread_trap'))
        print('  old', repr(e['old'])[:600])
        print('  new', repr(e['new'])[:600])
    return 1 if stats['bad'] else 0


sys.exit(main())
