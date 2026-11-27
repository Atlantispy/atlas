"""Exactly the installed Fraction float conversion, without redundant gcd.

CPython Fraction.__float__ computes int(numerator)/int(denominator), not two
float conversions. Integer true division rounds the exact ratio to binary64,
including subnormals and ties. Canonical GMP rationals already have coprime
integer parts and a positive denominator: rebuilding a Fraction first only
repeats gcd. No MPFR context, approximate intermediate or rounding-mode change.
Nonpositive denominators retain the original Fraction normalisation/refusal.
Storage for the two Python integer copies remains a caller-owned obligation.
"""
from fractions import Fraction


def public_float(value):
    numerator, denominator = int(value.numerator), int(value.denominator)
    if denominator <= 0:
        return float(Fraction(numerator, denominator))
    return numerator / denominator
