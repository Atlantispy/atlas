"""Exact GMP rational to current-context Decimal, without huge Decimal ints.

Fast contract: finite integer numerator/denominator, ROUND_HALF_EVEN, clamp=0.
Other rounding/clamp contexts and zero denominator explicitly use the original
Decimal(integer)/Decimal(integer) operation. No global context change occurs.

Proof: locate e with 10**e <= abs(n/d) < 10**(e+1) by exact comparisons.
The rounding quantum is t=max(e-prec+1,Etiny). Compute the exact truncation
q=floor(abs(n/d)/10**(t-2)) and its remainder. If nonzero, q+0.1 lies in the
same open guard interval as the original value: HALF_EVEN thresholds lie at
integer multiples of 50 guard units, so its side/tie and retained parity are
unchanged. The extra digit is sticky, NOT an approximation accepted as exact.
For zero remainder the decimal is exact. Remove its trailing zeros only while
the exponent is negative: integer/integer division has preferred exponent0.
Context.create_decimal then rounds a bounded coefficient, including exponent
limits, signals and traps. The substituted value has the same tiny/normal and
inexact status. Native GMP scalar calls remain non-interruptible.
"""
from concurrent.futures import CancelledError
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from operator import index

import gmpy2 as G


def _check(cancelled):
    if cancelled is not None and cancelled():
        raise CancelledError('Exact rational Decimal conversion cancelled')


def _integer(value):
    return value if isinstance(value, G.mpz) else G.mpz(index(value))


def _compare_power(numerator, denominator, exponent, cancelled):
    _check(cancelled)
    power = G.mpz(10)**abs(exponent)
    _check(cancelled)
    return G.cmp(numerator, denominator*power) if exponent >= 0 else G.cmp(numerator*power, denominator)


def dec(value, *, context=None, cancelled=None, evidence=None):
    """Same numeric value, Decimal tuple and flags as integer/integer division.

``context=None`` uses (and signals into) the current context, like the frozen
``dec``. Explicit contexts are never installed globally. Cancellation occurs
between exact scalar operations. Evidence is optional caller-owned metadata.
"""
    _check(cancelled)
    context = getcontext() if context is None else context
    numerator, denominator = _integer(value.numerator), _integer(value.denominator)
    if context.rounding != ROUND_HALF_EVEN or context.clamp != 0 or not denominator:
        if evidence is not None:
            evidence.update(route='ORIGINAL_DECIMAL_INTEGER_DIVISION_FALLBACK',
                reason='Unsupported rounding/clamp context or zero denominator')
        _check(cancelled)
        return context.divide(Decimal(int(numerator)), Decimal(int(denominator)))
    sign = int((numerator < 0) != (denominator < 0))
    if not numerator:
        if evidence is not None:
            evidence.update(route='EXACT_ZERO', bounded_coefficient_digits=1)
        return context.create_decimal(Decimal((sign, (0,), 0)))
    numerator, denominator = abs(numerator), abs(denominator)
    exponent = numerator.num_digits(10)-denominator.num_digits(10)
    while _compare_power(numerator, denominator, exponent, cancelled) < 0:
        exponent -= 1
    while _compare_power(numerator, denominator, exponent+1, cancelled) >= 0:
        exponent += 1
    quantum = max(exponent-context.prec+1, context.Etiny())
    work_exponent = quantum-2
    _check(cancelled)
    scale = G.mpz(10)**abs(work_exponent)
    _check(cancelled)
    if work_exponent >= 0:
        quotient, remainder = divmod(numerator, denominator*scale)
    else:
        quotient, remainder = divmod(numerator*scale, denominator)
    _check(cancelled)
    if remainder:
        quotient = 10*quotient+1
        work_exponent -= 1
    else:
        while work_exponent < 0 and quotient and not quotient % 10:
            _check(cancelled)
            quotient //= 10
            work_exponent += 1
    digits = quotient.digits(10)
    if len(digits) > context.prec+3:
        raise ArithmeticError('Exact coefficient bound unexpectedly exceeded')
    if evidence is not None:
        evidence.update(route='EXACT_GMP_GUARD_STICKY', adjusted_exponent=exponent,
            rounding_quantum=quantum, bounded_coefficient_digits=len(digits),
            exact_guard_remainder_zero=not bool(remainder))
    _check(cancelled)
    exact_surrogate = Decimal((sign, tuple(ord(c)-48 for c in digits), work_exponent))
    return context.create_decimal(exact_surrogate)
