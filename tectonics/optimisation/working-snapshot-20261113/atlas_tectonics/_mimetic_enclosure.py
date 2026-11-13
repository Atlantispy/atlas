"""Exploratory certified Decimal80 gamma; exact Fraction fallback always kept.

Directed contexts enclose the exact raw-normal/common-volume formula. Return
only when both endpoints round to the same finite Decimal80 half-even value.
This changes neither neighbours, constant-field guards nor accepted equations.
The caller must separately retain those exact checks and source identity.

One object lives for one recovery row. Its input enclosures are reused at
96/192/384 digits; no persistent/global cache exists. ``admitted_bytes`` names
scratch already reserved by the caller, not a new or silently enlarged budget.
The helper retains caller-owned immutable Fraction references; its admission
covers interval storage and conversions, not those inputs or an exact fallback.
The original exact-work reservation must remain held through every fallback.

Reference inspected: https://docs.python.org/3/library/decimal.html
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
from decimal import (Decimal as D, Context, DecimalException, MAX_EMAX, MIN_EMIN,
                     ROUND_FLOOR, ROUND_CEILING, ROUND_HALF_EVEN, getcontext,
                     localcontext, InvalidOperation, DivisionByZero, Overflow)
from fractions import Fraction as Q
import hashlib
from pathlib import Path
from .resources import MemoryLimitError

_LOADED=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def assert_current():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=_LOADED:
        raise ValueError('certified gamma source changed during preparation')
    return _LOADED

_ZERO=D(0)
_TWO=D(2)
_LEVELS=(96,192,384)


def _cancel(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel,'is_set') else cancel()):
        raise CancelledError('certified gamma work cancelled')


def _q(value):
    if isinstance(value,Q) or type(value) is int:
        return Q(value)
    raise TypeError('exact Fraction or integer gamma input required')


def _dot_exact(a,b):
    return sum((x*y for x,y in zip(a,b)),Q(0))


def workspace_bytes(row,denominator,tangent=None,squared=None,delta=None):
    """Three-level scratch, optionally including one delta's conversion.

    For a row serving several known deltas, reserve the maximum returned
    value, not their sum. The original exact fallback remains separate.
    """
    scalars=[q for vector in row.values() for q in vector]+[denominator]
    if tangent is not None:
        scalars.extend(tangent)
        if squared is not None:
            scalars.append(squared)
    bits=max((max(abs(_q(q).numerator).bit_length(),_q(q).denominator.bit_length())
              for q in scalars),default=1)
    # Decimal endpoints at at most 384 digits, interval/container slots,
    # three retained precision levels and transient delta/product intervals.
    # Integer->Decimal conversion is exact before the directed division;
    # 2 bytes per input bit and 16 objects overcount its decimal coefficient.
    required=65536+3*2*1024*(3*len(row)+32)+16*(1024+2*bits)
    if delta is not None:
        delta_bits=max((max(abs(_q(q).numerator).bit_length(),_q(q).denominator.bit_length()) for q in delta),default=1)
        required+=16*(1024+2*delta_bits)
    return required


class _Uncertain(ArithmeticError):
    pass


class _Intervals:
    __slots__=('down','up')

    def __init__(self,precision):
        traps=[InvalidOperation,DivisionByZero,Overflow]
        self.down=Context(prec=precision,rounding=ROUND_FLOOR,Emin=MIN_EMIN,Emax=MAX_EMAX,clamp=0,traps=traps)
        self.up=Context(prec=precision,rounding=ROUND_CEILING,Emin=MIN_EMIN,Emax=MAX_EMAX,clamp=0,traps=traps)

    @staticmethod
    def checked(low,high):
        if not low.is_finite() or not high.is_finite() or low>high:
            raise _Uncertain('finite ordered interval required')
        return low,high

    def rational(self,q):
        # Decimal(integer) is exact; Context.divide supplies outward rounding.
        a,b=D(q.numerator),D(q.denominator)
        return self.checked(self.down.divide(a,b),self.up.divide(a,b))

    def add(self,a,b):
        return self.checked(self.down.add(a[0],b[0]),self.up.add(a[1],b[1]))

    def sub(self,a,b):
        return self.checked(self.down.subtract(a[0],b[1]),self.up.subtract(a[1],b[0]))

    def mul(self,a,b):
        # Monotone sign branches avoid eight products for usual signed rows.
        if a[0]>=0 and b[0]>=0:
            low,high=(a[0],b[0]),(a[1],b[1])
        elif a[1]<=0 and b[1]<=0:
            low,high=(a[1],b[1]),(a[0],b[0])
        elif a[0]>=0 and b[1]<=0:
            low,high=(a[1],b[0]),(a[0],b[1])
        elif a[1]<=0 and b[0]>=0:
            low,high=(a[0],b[1]),(a[1],b[0])
        else:
            pairs=((a[0],b[0]),(a[0],b[1]),(a[1],b[0]),(a[1],b[1]))
            return self.checked(min(self.down.multiply(x,y) for x,y in pairs),
                                max(self.up.multiply(x,y) for x,y in pairs))
        return self.checked(self.down.multiply(*low),self.up.multiply(*high))

    def positive_div(self,a,b):
        if b[0]<=0:
            raise _Uncertain('strictly positive divisor interval required')
        if a[0]>=0:
            low,high=(a[0],b[1]),(a[1],b[0])
        elif a[1]<=0:
            low,high=(a[0],b[0]),(a[1],b[1])
        else:
            low,high=(a[0],b[0]),(a[1],b[0])
        return self.checked(self.down.divide(*low),self.up.divide(*high))

    def absolute(self,a):
        if a[0]>=0:
            return a
        if a[1]<=0:
            return a[1].copy_negate(),a[0].copy_negate()
        return _ZERO,max(a[0].copy_negate(),a[1])

    def dot(self,a,b):
        total=(_ZERO,_ZERO)
        for x,y in zip(a,b):
            total=self.add(total,self.mul(x,y))
        return total


class CertifiedGammaRow:
    """Certified evaluation for one exact recovery row, not a geometry owner."""
    __slots__=('vectors','denominator','tangent','squared','cancel','target','levels','statistics',
               'admitted_bytes','required_row_bytes')

    def __init__(self,row,denominator,*,node,tangent=None,squared=None,admitted_bytes,cancel=None):
        assert_current()
        _cancel(cancel)
        needed=workspace_bytes(row,denominator,tangent,squared)
        if type(admitted_bytes) is not int or admitted_bytes<needed:
            raise MemoryLimitError('certified gamma scratch exceeds existing admitted allowance')
        self.admitted_bytes=admitted_bytes
        self.required_row_bytes=needed
        self.vectors=tuple(tuple(map(_q,vector)) for k,vector in row.items() if k!=node)
        if any(len(vector)!=3 for vector in self.vectors):
            raise ValueError('three-dimensional gamma vectors required')
        self.denominator=_q(denominator)
        if self.denominator<=0:
            raise ValueError('positive exact gamma common volume required')
        self.tangent=None if tangent is None else tuple(map(_q,tangent))
        if self.tangent is not None and len(self.tangent)!=3:
            raise ValueError('three-dimensional tangent normal required')
        self.squared=None if tangent is None else _dot_exact(self.tangent,self.tangent)
        if squared is not None and self.squared!=_q(squared):
            raise ValueError('supplied exact normal squared does not match its vector')
        if self.squared is not None and self.squared<=0:
            raise ValueError('positive exact normal squared required')
        self.cancel=cancel
        self.target=getcontext().copy()
        self.target.prec,self.target.rounding=80,ROUND_HALF_EVEN
        self.levels={}
        self.statistics=dict(calls=0,certified_96=0,certified_192=0,certified_384=0,exact_fallbacks=0)

    def _level(self,precision):
        if precision not in self.levels:
            _cancel(self.cancel)
            ops=_Intervals(precision)
            vectors=[]
            for vector in self.vectors:
                _cancel(self.cancel)
                vectors.append(tuple(ops.rational(q) for q in vector))
            denominator=ops.rational(self.denominator)
            tangent=None if self.tangent is None else tuple(ops.rational(q) for q in self.tangent)
            squared=None if self.squared is None else ops.rational(self.squared)
            self.levels[precision]=(ops,tuple(vectors),denominator,tangent,squared)
        return self.levels[precision]

    def _enclosure(self,delta,precision):
        ops,vectors,denominator,tangent,squared=self._level(precision)
        delta=tuple(ops.rational(q) for q in delta)
        if tangent is not None:
            factor=ops.positive_div(ops.dot(delta,tangent),squared)
            delta=tuple(ops.sub(value,ops.mul(factor,normal)) for value,normal in zip(delta,tangent))
        total=(_ZERO,_ZERO)
        for vector in vectors:
            _cancel(self.cancel)
            total=ops.add(total,ops.absolute(ops.dot(vector,delta)))
        return ops.positive_div(ops.mul((_TWO,_TWO),total),denominator)

    def exact(self,delta):
        """Unchanged Fraction formula; all uncertainty eventually arrives here."""
        _cancel(self.cancel)
        if self.tangent is not None:
            factor=_dot_exact(delta,self.tangent)/self.squared
            delta=tuple(value-factor*normal for value,normal in zip(delta,self.tangent))
        total=Q(0)
        for vector in self.vectors:
            _cancel(self.cancel)
            total+=abs(_dot_exact(vector,delta))
        mu=total/self.denominator
        with localcontext(self.target):
            return D(2*mu.numerator)/D(mu.denominator)

    def gamma(self,delta):
        _cancel(self.cancel)
        delta=tuple(map(_q,delta))
        if len(delta)!=3:
            raise ValueError('three-dimensional gamma delta required')
        delta_bits=max(max(abs(q.numerator).bit_length(),q.denominator.bit_length()) for q in delta)
        # The direction/coordinate difference can be wider than every row
        # scalar. Charge its exact integer conversion before constructing it.
        if self.required_row_bytes+16*(1024+2*delta_bits)>self.admitted_bytes:
            raise MemoryLimitError('certified gamma delta conversion exceeds existing admitted allowance')
        self.statistics['calls']+=1
        for precision in _LEVELS:
            _cancel(self.cancel)
            try:
                low,high=self._enclosure(delta,precision)
                low80,high80=self.target.plus(low),self.target.plus(high)
                if low80.is_finite() and high80.is_finite() and low80==high80:
                    self.statistics['certified_'+str(precision)]+=1
                    # Gamma is nonnegative; never expose a negative signed zero.
                    return _ZERO if not low80 else low80
            except (DecimalException,_Uncertain):
                # No approximate endpoint escapes. A context range/trap or
                # unresolved interval proceeds to a stronger level or exact Q.
                pass
        self.statistics['exact_fallbacks']+=1
        # Free interval enclosures before the original exact scratch is used.
        self.levels.clear()
        return self.exact(delta)
