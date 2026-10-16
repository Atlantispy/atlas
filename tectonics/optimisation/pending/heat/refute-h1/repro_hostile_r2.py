"""r1 reproducers re-run against r2, plus residual hostile cases (6-9) found while reviewing r2."""
import types

from common_r2 import G, OLD, NEW, make, outcome, state
import private_heat_interval_inventory_r1 as I


def show(title, fn, cls_of=None):
    rows = []
    for m in (OLD, NEW):
        a, w = make(m, cls_of(m) if cls_of else None)
        r = outcome(lambda: fn(a))
        rows.append((r, state(a, w)))
    same = rows[0] == rows[1]
    print('%-60s %s' % (title, 'SAME' if same else 'DIFFERENT'))
    if not same:
        print('   original   :', rows[0])
        print('   transformed:', rows[1])


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


class NoMpz:
    mpq = G.mpq


def r_none(a):
    a.reserve(8)
    a.R = None
    return a.reserve(8)


def r_del(a):
    del a.R
    return a.rational('add', 1, 1)


def inst_shape(a):
    a._shape = lambda value: I.Shape(500, 1, True)
    return a.q(G.mpz(3))


def no_mpz(a):
    a.G = NoMpz()
    return a.q(5)


show('1a rational(add, IntLike(), 1)', lambda a: a.rational('add', IntLike(), 1))
show('1b q(IntLike())', lambda a: a.q(IntLike()))
show('2  instance attribute _shape, then q(mpz(3))', inst_shape)
show('3a a.R = None, reserve(same peak)', r_none)
show('3b del a.R, rational(add, 1, 1)', r_del)
show('4  subclass _shape = staticmethod(base _shape)', lambda a: a.rational('multiply', G.mpq(1, 3), 2),
     lambda m: type('Static', (m.Arithmetic,), {'_shape': staticmethod(m.Arithmetic._shape)}))
show('5  arena.G lacks mpz, q(5)', no_mpz)


# 6. Metaclass __eq__ that is True only on its FIRST call: the original evaluates the
#    `in (int, mpz)` test twice (_shape then _integer); r2 evaluates it once.
def first_only():
    class Once(type):
        calls = [0]

        def __eq__(cls, other):
            Once.calls[0] += 1
            return Once.calls[0] == 1
        __hash__ = type.__hash__

    class X(metaclass=Once):
        def bit_length(self):
            return 5

        def __add__(self, other):
            return 'sum computed'

        def __mpq__(self):
            return G.mpq(5, 1)
    return X()


show('6a rational(add, once-equal-to-int, 1)', lambda a: a.rational('add', first_only(), 1))
show('6b q(once-equal-to-int)', lambda a: a.q(first_only()))


# 7. arena.G replaced by a non-gmpy2 namespace whose rational type has denominator 0.
#    rational()'s inline guard checks R, not G; the original refuses in RationalShape.
class ZeroDen:
    numerator, denominator = 1, 0

    def __add__(self, other):
        return 'added'


class FakeG:
    mpz = G.mpz
    mpq = ZeroDen


def zero_den(a):
    a.G = FakeG()
    return a.rational('add', ZeroDen(), 1)


show('7  arena.G.mpq with denominator 0, rational(add)', zero_den)


# 8. A subclass whose _integer cannot be read (property raising). The original q/rational on
#    mpq operands never touches _integer; r2's guard reads it up front.
def bad_integer(m):
    class P(m.Arithmetic):
        @property
        def _integer(self):
            raise LookupError('no integer route here')
    return P


show('8a subclass _integer property raises, q(mpq(1,3))', lambda a: a.q(G.mpq(1, 3)), bad_integer)
show('8b same subclass, rational(add, mpq, mpq)', lambda a: a.rational('add', G.mpq(1, 3), G.mpq(2, 5)),
     bad_integer)


# 9. Attribute read order in reserve (H1a r2): slots/containers are read before the slot
#    allowance is computed, and slots before containers.
def del_both(a):
    del a.slots, a.containers
    return a.reserve(1)


def del_slots_bad_width(a):
    del a.slots
    return a.reserve(10.5)


show('9a del slots and containers, reserve(1)', del_both)
show('9b del slots, reserve(10.5)', del_slots_bad_width)
