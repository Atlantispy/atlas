"""Targeted differential probes where the shipped tests do not look.

ORIGINAL vs H1a (MID) vs H1a+H1c (NEW), comparing results, exception type/message,
peak_bits (value and type), operations, lease, full resize log, and side-effect logs
(cancel-callback calls, operation __eq__ calls).
"""
import random
import sys
from enum import IntEnum

from common import G, OLD, MID, NEW, Work, outcome, state

MODS = (OLD, MID, NEW)
FAIL = []


def check(tag, results):
    if not all(r == results[0] for r in results[1:]):
        FAIL.append(tag)
        if len(FAIL) <= 10:
            print('DIFF', tag)
            for name, r in zip(('old', 'mid', 'new'), results):
                print('  ', name, r)


def big(v):
    """A distinct int object with the same value (defeats the small-int cache)."""
    return int(str(v))


# A. Equal-but-distinct ints for peak/slots/containers, externally set peak_bits.
def scenario_identity(rng, m):
    w = Work()
    a = m.Arithmetic(w, G, scalar_slots=big(5000), container_bytes=big(1 << 20), initial_bits=big(300))
    trace = []
    for _ in range(300):
        k = rng.random()
        if k < 0.3:
            bits = rng.choice((a.peak_bits, big(a.peak_bits), a.peak_bits+1, big(a.peak_bits-1), 1, 0, -5))
            trace.append(outcome(lambda: a.reserve(bits)))
        elif k < 0.4:
            a.slots = big(a.slots)
            trace.append(outcome(lambda: a.reserve(a.peak_bits)))
        elif k < 0.5:
            a.containers = big(a.containers)
            trace.append(outcome(lambda: a.reserve(a.peak_bits)))
        elif k < 0.6:
            a.peak_bits = rng.choice((big(a.peak_bits), max(1, a.peak_bits-rng.randint(0, 50)), a.peak_bits+7))
            trace.append(outcome(lambda: a.reserve(rng_bits[0])))
        elif k < 0.65:
            a.peak_bits = rng.choice((G.mpz(a.peak_bits), True, 3.0))
            trace.append(outcome(lambda: a.reserve(1)))
            a.peak_bits = 300
            trace.append(outcome(lambda: a.reserve(1)))
        elif k < 0.7:
            a.slots = rng.choice((True, -64, -100, G.mpz(70), 0))
            trace.append(outcome(lambda: a.reserve(a.peak_bits)))
            trace.append(outcome(lambda: a.reserve(a.peak_bits)))
            a.slots = 5000
            trace.append(outcome(lambda: a.reserve(a.peak_bits)))
        elif k < 0.8:
            w.lease.count = rng.randint(0, w.lease.count)
            trace.append(outcome(lambda: a.reserve(a.peak_bits)))
        else:
            x = rng.choice((G.mpq(rng.getrandbits(400)+1, rng.getrandbits(300)+1), G.mpz(-rng.getrandbits(200)),
                            -rng.getrandbits(90), G.mpq(-1, 1 << rng.randint(0, 99)), 0, G.mpz(0), G.mpq(0)))
            y = rng.choice((G.mpq(3, 7), 1, G.mpz(-1), G.mpq(-(1 << 300), 3), 5))
            for op in ('add', 'subtract', 'multiply', 'divide'):
                trace.append(outcome(lambda: a.rational(op, x, y)))
            trace.append(outcome(lambda: a.q(x)))
        trace.append(state(a, w))
    return trace


rng_bits = [1]


# B. sys.maxsize boundary and 2**27-bit route ceiling, then cache reuse.
def scenario_bounds(m):
    out = []
    w = Work(limit=1 << 70)
    a = m.Arithmetic(w, G, scalar_slots=10, container_bytes=10, initial_bits=8)
    slot = m.Arithmetic.__dict__  # noqa: F841 - keep module referenced
    base = a.workspace.lease.count - a.containers
    for delta in (-1, 0, 1):
        a.containers = sys.maxsize - base + delta
        out.append(outcome(lambda: a.reserve(a.peak_bits)))
        out.append(outcome(lambda: a.reserve(a.peak_bits)))
        out.append(state(a, w))
    a.containers = 10
    for bits in (1 << 24, (1 << 24)+1, 1 << 24, (1 << 24)-1):
        out.append(outcome(lambda: a.reserve(bits)))
        out.append(state(a, w))
    return out


# C. Budget refusal on resize, then retry with the SAME int object (cache stored before resize).
def scenario_refusal(m):
    out = []
    w = Work(limit=300000)
    a = m.Arithmetic(w, G, scalar_slots=77, container_bytes=999, initial_bits=8)
    huge = 1 << 12
    for _ in range(3):
        out.append(outcome(lambda: a.reserve(huge)))
        out.append(state(a, w))
    w.limit = 1 << 42
    out.append(outcome(lambda: a.reserve(huge)))
    out.append(state(a, w))
    w.lease.count = 0
    out.append(outcome(lambda: a.reserve(1)))
    out.append(state(a, w))
    return out


# D. Re-entrant cancel callback and resize hook that mutate the arena mid-reserve.
def scenario_reentrant(rng, m):
    out, calls = [], []
    box = {}

    def cancel():
        calls.append('c')
        a = box.get('a')
        if a is not None and box.get('mutate'):
            box['mutate'] = False
            k = rng_local.random()
            if k < 0.33:
                a.slots += 3
            elif k < 0.66:
                a.containers += 4096
            else:
                a.peak_bits = a.peak_bits+11
                a.reserve(a.peak_bits+5)          # nested call
        return False

    class HookWork(Work):
        def resize_before_allocation_or_after_drop(self, count):
            super().resize_before_allocation_or_after_drop(count)
            if box.get('hook'):
                box['hook'] = False
                box['a'].slots += 1
                box['a'].reserve(box['a'].peak_bits)

    rng_local = random.Random(rng.random())
    w = HookWork()
    a = m.Arithmetic(w, G, scalar_slots=77, container_bytes=999, initial_bits=8, cancelled=cancel)
    box['a'] = a
    for _ in range(200):
        k = rng_local.random()
        if k < 0.3:
            box['mutate'] = True
        elif k < 0.45:
            box['hook'] = True
        x = rng_local.choice((G.mpq(rng_local.getrandbits(200)+1, 3), 7, G.mpz(rng_local.getrandbits(150))))
        op = rng_local.choice(('add', 'subtract', 'multiply', 'divide'))
        out.append(outcome(lambda: a.rational(op, x, G.mpq(5, 9))))
        out.append(outcome(lambda: a.q(x)))
        out.append(outcome(lambda: a.reserve(rng_local.randint(1, a.peak_bits+3))))
        out.append((state(a, w), a.slots, a.containers, len(calls)))
    return out


# E. Stateful / odd-equality operation objects; record every __eq__ call.
class CountingStr(str):
    log = None

    def __eq__(self, other):
        CountingStr.log.append(('eq', str(self), other))
        return str.__eq__(self, other)

    __hash__ = str.__hash__


class Flip:
    """Equal to 'add' on the first comparison against 'add', then to 'multiply'."""
    def __init__(self, log):
        self.log, self.n = log, 0

    def __eq__(self, other):
        self.n += 1
        self.log.append(('flip', other, self.n))
        return other == ('add' if self.n <= 1 else 'multiply')

    __hash__ = object.__hash__


class Raiser:
    def __init__(self, log, after):
        self.log, self.after, self.n = log, after, 0

    def __eq__(self, other):
        self.n += 1
        self.log.append(('raiser', other, self.n))
        if self.n > self.after:
            raise LookupError('eq #%d' % self.n)
        return False

    __hash__ = object.__hash__


def scenario_operations(m):
    out = []
    a, w = Work(), None
    a = m.Arithmetic(Work(), G, scalar_slots=77, container_bytes=999, initial_bits=8)
    for name in ('add', 'subtract', 'multiply', 'divide', 'pow', 'Add'):
        log = []
        CountingStr.log = log
        out.append((name, outcome(lambda: a.rational(CountingStr(name), G.mpq(1, 3), G.mpq(-2, 5))), tuple(log)))
    for after in range(0, 8):
        log = []
        out.append(('raiser', after, outcome(lambda: a.rational(Raiser(log, after), G.mpq(1, 3), 2)), tuple(log)))
    log = []
    out.append(('flip', outcome(lambda: a.rational(Flip(log), G.mpq(1, 3), G.mpq(4, 3))), tuple(log)))
    out.append((a.peak_bits, a.operations, a.workspace.lease.count, tuple(a.workspace.log)))
    return out


# F. Exception-order matrix: bad left/right operand types, bad operation, pending cancellation.
def scenario_order(m):
    out = []
    flag = [False]
    goods = (G.mpq(1, 3), 5, G.mpz(-7), G.mpq(0))
    bads = (True, 1.5, None, G.mpfr(2), IntEnum('E', 'X').X, 'x')
    for cancelled in (False, True):
        for left in goods+bads:
            for right in goods+bads:
                for op in ('add', 'divide', 'bogus', None):
                    a = m.Arithmetic(Work(), G, scalar_slots=77, container_bytes=999, initial_bits=8,
                                     cancelled=lambda: flag[0])
                    flag[0] = cancelled
                    out.append(outcome(lambda: a.rational(op, left, right)))
                    out.append(outcome(lambda: a.q(left)))
                    flag[0] = False
                    out.append((a.peak_bits, a.operations, a.workspace.lease.count, tuple(a.workspace.log)))
    return out


# G. Subclasses: overriding _integer only, overriding reserve, rank-like iadd/ratio, property _shape.
def subclasses(m):
    class OverInt(m.Arithmetic):
        def _integer(self, value):
            return super()._integer(value)+3

    class OverReserve(m.Arithmetic):
        def reserve(self, bits):
            self.seen = getattr(self, 'seen', [])+[bits]
            return super().reserve(bits)

    class Rank(m.Arithmetic):
        def iadd(self, a, b):
            self.reserve(max(self._integer(a), self._integer(b))+1)
            self.operations += 1
            return a+b

        def ratio(self, numerator, denominator):
            self.reserve(max(self._integer(numerator), self._integer(denominator)))
            self.operations += 1
            return self.G.mpq(numerator, denominator)
    return OverInt, OverReserve, Rank


def scenario_subclasses(rng, m):
    out = []
    for cls in subclasses(m):
        w = Work()
        a = cls(w, G, scalar_slots=77, container_bytes=999, initial_bits=8)
        for _ in range(60):
            x = rng.choice((G.mpq(rng.getrandbits(300), rng.getrandbits(200)+1), G.mpz(rng.getrandbits(250)),
                            rng.getrandbits(100), 0))
            y = rng.choice((G.mpq(-3, 11), 9, G.mpz(rng.getrandbits(80)+1)))
            op = rng.choice(('add', 'subtract', 'multiply', 'divide', 'nope'))
            out.append(outcome(lambda: a.rational(op, x, y)))
            out.append(outcome(lambda: a.q(x)))
            if cls.__name__ == 'Rank':
                out.append(outcome(lambda: a.iadd(G.mpz(rng.getrandbits(120)), 5)))
                out.append(outcome(lambda: a.ratio(G.mpz(rng.getrandbits(120)), 7)))
            out.append((state(a, w), getattr(a, 'seen', None)))
    return out


def main():
    for seed in range(40):
        check(('identity', seed), [scenario_identity(random.Random(seed), m) for m in MODS])
        check(('reentrant', seed), [scenario_reentrant(random.Random(1000+seed), m) for m in MODS])
        check(('subclasses', seed), [scenario_subclasses(random.Random(2000+seed), m) for m in MODS])
    check('bounds', [scenario_bounds(m) for m in MODS])
    check('refusal', [scenario_refusal(m) for m in MODS])
    check('operations', [scenario_operations(m) for m in MODS])
    check('order', [scenario_order(m) for m in MODS])
    print('failures:', len(FAIL), FAIL[:20])


if __name__ == '__main__':
    main()
