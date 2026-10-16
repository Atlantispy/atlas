"""Transfer a completed private exact result to its own accounted lifetime.

All input objects are covered by the old owner while inspected. The new charge
is admitted before the old work is released. This is intentionally recursive
without deduplication: aliases cost more, never less. No numeric copy or JSON
conversion is made. Use after the producing numerical frame has returned and
before exposing borrowed references; callbacks retaining temporaries forbid it.
"""
from decimal import Decimal
from fractions import Fraction
import sys

import private_heat_certification_resources_r1 as I
import private_heat_decimal_sparse_core_r1 as P


def transfer(owner, *, budget, cancelled=None, category='heat-retained-functional-row'):
    from atlas_tectonics.exact_arithmetic import library
    import private_heat_gmp_resources_r1 as R
    G = library()
    if G is None:
        raise RuntimeError('Selected GMP backend required')
    work = R.OwnedWorkspace(budget, 262144, category=category, cancelled=cancelled)
    work.__enter__()
    try:
        total = 262144
        def visit(value, depth=0):
            nonlocal total
            I.check(cancelled)
            if depth > 64:
                raise ValueError('Unexpected retained result nesting')
            total = I.size(total+I.D.CONTAINER_UNIT+sys.getsizeof(value))
            if type(value) in (dict, list, tuple):
                if type(value) is dict:
                    for key, item in value.items():
                        visit(key, depth+1)
                        visit(item, depth+1)
                else:
                    for item in value:
                        visit(item, depth+1)
            elif type(value) in (G.mpq, Fraction):
                total = I.size(total+R.native_slot_allowance(R.RationalShape(
                    max(1, value.numerator.bit_length()), value.denominator.bit_length())))
            elif type(value) not in (str, int, bool, float, Decimal, type(None)):
                raise TypeError('Unsupported retained result object '+type(value).__name__)
        value = owner.value
        visit(value)
        work.resize_before_allocation_or_after_drop(total)
        # The complete producing frame is gone. The only escaped graph is
        # value, now independently funded BEFORE releasing its old owner.
        owner.close()
        return P.OwnedSolve(value, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise
