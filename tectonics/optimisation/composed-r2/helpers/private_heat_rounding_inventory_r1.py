"""Source-derived exact scalar envelopes for fixed assembly A2 rounding.

This inventories the frozen guard/sticky converter AND A2's adjacent-Decimal
tie checks. It never converts a coefficient or changes a Decimal context.
Widths are mathematical bounds; the installed GMP/Python accounting policy
applied to them is not an allocator/RSS theorem. Singleton face intervals do
not execute the tie branch. Unknown aggregate equality receives no such credit.
"""
from dataclasses import dataclass
from decimal import getcontext
import struct
import sys


@dataclass(frozen=True)
class ConversionGrowth:
    rational_part_bits: int
    maximum_part_bits: int
    precision: int
    maximum_power_exponent: int
    power_bits: int
    maximum_product_bits: int
    surrogate_digits: int
    simultaneous_expression_bits: int
    tie_guard_part_bits: int
    tie_guard_maximum_part_bits: int
    tie_guard_expression_bits: int
    legacy_fallback: bool
    exact_scalar_expression_bits: int
    python_conversion_bytes: int


def conversion_growth(part_bits, maximum_part_bits, *, tie_part_bits=0,
                      tie_maximum_part_bits=0, precision=80, context=None):
    """Bound the fixed p-digit HALF_EVEN path, including inherited clamp.

    Let S bound nbits+dbits and M bound max(nbits,dbits), for positive integer
    parts. These may be upper bounds, not actual lengths. |floor(log10(n/d))|
    is at most M; powers used in digit discovery/scaling fit P=M+4(p+3) bits:
    10**|e| < 10*max(n,d), and scaling adds at most p+2 decimal places.
    Context.Emin<=0 implies Etiny<=1-p; clamping a tiny quantum cannot enlarge
    this bound. GMP's num_digits may overestimate by one; two extra discovery
    powers are covered. The source asserts quotient text <=p+3 digits.

    Max simultaneous converter scalars: S+2M+3P+2Q+4, Q=4(p+3). This includes
    getters/abs copies, power, scaled operand, divmod quotient/remainder and
    overlapping sticky updates. It dominates discovery S+M+2P as well.

    Tie branch: a finite p-digit centre/neighbour has coefficient <=C=4p bits
    and a decimal power <=P_t=M_t+4(p+4) bits. Its fraction is either (C,P_t)
    or (P_t+C,1), never two unrelated large parts. Unreduced rational addition
    of any two such shapes uses <=10P_t+6C+16 expression bits including inputs,
    cross-products and result. Since adjacent decimals share a power-of-ten
    lattice, their exact midpoint has total part width <=U=P_t+C+12. Add the
    previous loop midpoint still live during the next assignment: <=11P_t+7C+32.
    This also dominates Decimal->Fraction->GMP copies (<=7U, absorbed by the
    constant below) and midpoint division. Comparison with an input endpoint
    needs <=2S_t+3U (two cross-products, operands and retained centre).
    The extra 128 bits cover all bounded lattice/copy constants above.

    Nonzero singleton returns precede the tie branch. No zero/tie is guessed.
    clamp=1 still uses the original giant-Decimal fallback; retain its legacy
    funding rather than changing behaviour. A2 always sets HALF_EVEN and p80.
    """
    for name, value in (('part_bits', part_bits), ('maximum_part_bits', maximum_part_bits),
                        ('precision', precision)):
        if type(value) is not int or value <= 0:
            raise ValueError('Positive integer '+name+' required')
    if not maximum_part_bits <= part_bits <= 2*maximum_part_bits:
        raise ValueError('Compatible rational part-width envelopes required')
    if (type(tie_part_bits) is not int or type(tie_maximum_part_bits) is not int
            or tie_part_bits < 0 or tie_maximum_part_bits < 0
            or bool(tie_part_bits) != bool(tie_maximum_part_bits)
            or tie_part_bits and not tie_maximum_part_bits <= tie_part_bits <= 2*tie_maximum_part_bits):
        raise ValueError('Compatible nonnegative tie-branch widths required')
    context = getcontext() if context is None else context
    power = maximum_part_bits+4*(precision+3)
    expression = part_bits+2*maximum_part_bits+3*power+8*(precision+3)+4
    tie = 0
    if tie_part_bits:
        pt, coefficient = tie_maximum_part_bits+4*(precision+4), 4*precision
        u = pt+coefficient+12
        tie = max(11*pt+7*coefficient+160, 2*tie_part_bits+3*u+128)
    fallback = bool(context.clamp)
    exact = max(expression, tie, 8*(part_bits+1024) if fallback else 0)
    digits = precision+3
    pointer = struct.calcsize('P')
    # Two returned Decimals, current text/digit tuples/integers/surrogates,
    # neighbouring Decimal objects. Large exact Fraction/Python-int copies are
    # included in the exact scalar policy above, not p-digit object counts.
    python = 4096+16*512+4*(sys.getsizeof('')+digits)
    python += 4*(sys.getsizeof(())+pointer*digits)+4*digits*sys.getsizeof(0)
    if fallback:
        python = max(python, 16*512*max(1, (part_bits+1024+precision-1)//precision))
    if exact > sys.maxsize or python > sys.maxsize:
        raise OverflowError('Rounding inventory exceeds addressable storage')
    return ConversionGrowth(part_bits, maximum_part_bits, precision,
        maximum_part_bits+precision+2, power, maximum_part_bits+power,
        digits, expression, tie_part_bits, tie_maximum_part_bits, tie,
        fallback, exact, python)
