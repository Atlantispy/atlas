"""Minimal reproducers: inputs/states where ORIGINAL and H1a+H1c differ.

All need deliberately hostile values or instance-level patching; none is produced
by the reviewed callers. Each case prints the original and transformed outcome
plus (peak_bits, operations, lease, resize log).
"""
from common import G, OLD, NEW, make, outcome, state
import private_heat_interval_inventory_r1 as I


def show(title, fn):
    rows = []
    for m in (OLD, NEW):
        a, w = make(m)
        r = outcome(lambda: fn(a))
        rows.append((r, state(a, w)))
    same = rows[0] == rows[1]
    print('%-52s %s' % (title, 'SAME' if same else 'DIFFERENT'))
    if not same:
        print('   original   :', rows[0])
        print('   transformed:', rows[1])
    return same


# 1. A type whose metaclass makes it compare equal to int. The original checks
#    `type(value) in (int, mpz)` (tuple containment uses ==); H1c uses `is`.
class EqualsInt(type):
    def __eq__(cls, other):
        return other is int or type.__eq__(cls, other)

    __hash__ = type.__hash__


class IntLike(metaclass=EqualsInt):
    def bit_length(self):
        return 300

    def __add__(self, other):
        return 'sum computed'

    def __mpq__(self):
        return G.mpq(7, 1)


show('1a rational(add, IntLike(), 1)', lambda a: a.rational('add', IntLike(), 1))
show('1b q(IntLike())', lambda a: a.q(IntLike()))
show('1c imul(IntLike(), 1) [unchanged method, control]', lambda a: a.imul(IntLike(), 1))


# 2. Instance-level override of _shape: the route guard inspects only type(self).
def patched_shape(a):
    a._shape = lambda value: I.Shape(500, 1, True)
    return a.q(G.mpz(3))


show('2  instance attribute _shape, then q(mpz(3))', patched_shape)


# 3. Instance R rebound/removed after warm-up: H1a skips R on a cache hit and H1c
#    never reads R in rational().
def drop_r_reserve(a):
    a.reserve(8)
    a.R = None
    return a.reserve(8)


def drop_r_rational(a):
    del a.R
    return a.rational('add', 1, 1)


show('3a a.R = None, reserve(same peak)', drop_r_reserve)
show('3b del a.R, rational(add, 1, 1)', drop_r_rational)


# 4. A (broken) subclass that passes the class-level guard: staticmethod(base _shape)
#    resolves to the base function on the class but not on the instance.
def static_shape(m):
    class Static(m.Arithmetic):
        _shape = staticmethod(m.Arithmetic._shape)
    a, w = make(m, Static)
    r = outcome(lambda: a.rational('multiply', G.mpq(1, 3), 2))
    return r, state(a, w)


rows = [static_shape(m) for m in (OLD, NEW)]
print('%-52s %s' % ('4  subclass _shape = staticmethod(base _shape)', 'SAME' if rows[0] == rows[1] else 'DIFFERENT'))
if rows[0] != rows[1]:
    print('   original   :', rows[0])
    print('   transformed:', rows[1])


# 5. A gmp namespace without mpz: the original reads G.mpz even for an int operand.
class NoMpz:
    mpq = G.mpq


def no_mpz(a):
    a.G = NoMpz()
    return a.q(5)


show('5  arena.G lacks mpz, q(5)', no_mpz)
