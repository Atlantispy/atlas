"""Shared primitives for GMP-resident twins of exact Fraction kernels.

A twin computes the same rationals as its reference function on gmpy2 mpq values ("natives") and returns
the same Python objects: new canonical Fractions over Python ints, or the reference's own input objects
where the reference returns those. It makes the reference's reservations with the same amounts and
categories, in the same order, and adds only the native surcharge below, so it can refuse earlier than the
reference, never later. Natives never leave a twin.

This module is the single source for that boundary:
  available()          the gmpy2 backend is selected (exact_arithmetic), else every twin declines
  native(v)            int or Fraction -> mpq (callers have checked the exact type)
  fraction(q)          canonical mpq -> a NEW canonical Fraction of Python ints, without a second gcd
  bits(q)              integration_volume._bits of the Fraction q equals (admission width)
  lease(...)           integration_volume._work's reservation, then the GMP route's 2**27-bit ceiling
  Retained             surcharge of natives kept across the steps of one operation (NATIVE_RETAINED)
  dyadic_outward(...)  native outward rounding to a dyadic grid, as integration_pressure_coupling does
The block bounds, the ceiling and _settle are integration_exact_gmp's, imported only on the gmpy2 route, so
the Python route never imports gmpy2 or the native modules.
"""
from contextlib import ExitStack, contextmanager
from fractions import Fraction as Q

from . import exact_arithmetic as X
from . import integration_volume as V
from .integration_volume_bounds import NATIVE_RETAINED

_library = X.library()
if _library is not None:
    from . import integration_exact_gmp as _G
    mpq = _library.mpq
    _numer, _denom = _library.numer, _library.denom
    CEILING_BITS = _G.CEILING_BITS
    _settle = _G._settle
# Fraction's own constructor for a reduced pair with a positive denominator (Python 3.12); mpq is canonical
# in the same sense, so the pair needs no second gcd. Without it, Fraction(int, int) reduces again.
_from_coprime = getattr(Q, '_from_coprime_ints', None)


def available():
    return _library is not None


def native(v):
    if type(v) is Q:
        return mpq(v.numerator, v.denominator)
    return mpq(v)


def fraction(q):
    n, d = int(_numer(q)), int(_denom(q))
    if _from_coprime is not None:
        return _from_coprime(n, d)
    return Q(n, d)


def bits(q):
    return max(1, _numer(q).bit_length()+_denom(q).bit_length())


def exact(v):
    return type(v) is int or type(v) is Q


def triple(v):
    return type(v) is tuple and len(v) == 3 and exact(v[0]) and exact(v[1]) and exact(v[2])


@contextmanager
def lease(width, count, budget, *, pairs=0):
    """integration_volume._work(values, budget, pairs=pairs) for `count` values whose _bits sum to `width`
    (taken from the reference-typed objects: an int n counts n.bit_length(), its mpq would count one more),
    without its Fraction copy of the values; then the ceiling inside the reservation, as
    integration_exact_gmp._work. Any width over the ceiling reserves more than 16 GiB, so a budget within the
    project's limits refuses it first."""
    with V.select_budget(budget).reserve(65536+128*width+256*count+256*pairs, category='i03-physical-volume'):
        if width > CEILING_BITS:
            raise V.VolumeError('exact operands exceed the GMP route ceiling of 2**27 bits in one step; '
                                'use ATLAS_EXACT_ARITHMETIC=python')
        yield


class Retained:
    """Natives one operation keeps across its steps, on bounded blocks, charged under NATIVE_RETAINED.

    settle(values, held) runs integration_exact_gmp._settle on `values` (a value whose blocks exceed the
    bound is rebuilt from its integers; the numbers are unchanged) and returns them with their surcharge over
    the reference allowance. The reservation is the running maximum of held + that surcharge: it only grows
    and is released when the operation ends (the with-block), after the reference's own leases.
    """
    __slots__ = ('_budget', '_stack', 'charged')

    def __init__(self, budget):
        self._budget = V.select_budget(budget)
        self._stack = ExitStack()
        self.charged = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._stack.__exit__(*exc)

    def settle(self, values, held=0):
        values, (_, _, extra) = _settle(values)
        need = held+extra
        if need > self.charged:
            self._stack.enter_context(self._budget.reserve(need-self.charged, category=NATIVE_RETAINED))
            self.charged = need
        return values, extra


def dyadic_outward(lo, hi, denominator):
    """Natives (lo, hi) rounded outward to multiples of 1/denominator (a positive int): the same floor and
    ceiling of the scaled numerators as integration_pressure_coupling._dyadic_outward, as natives."""
    floor = _numer(lo)*denominator//_denom(lo)
    ceiling = -((-_numer(hi)*denominator)//_denom(hi))
    return mpq(floor, denominator), mpq(ceiling, denominator)
