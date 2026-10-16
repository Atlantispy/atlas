"""Owned exact Bareiss functional solve with pre-operation limb growth.

The numerical function is a literal copy of CERT r1's functional_solve with
arithmetic expressions routed through exact, ordering-preserving admission
helpers. Same primitive rows, pivot search, rank/incompatibility decisions,
free-variable zero choice and original-system residual validation. Matrix
inputs already exist under caller ownership. Gram construction and observation
rank reduction are NOT covered by this owner. No native or RSS proof is made.
"""
from concurrent.futures import CancelledError
import sys
from time import perf_counter

import private_heat_certification_kernel_r1 as K
import private_heat_certification_resources_r1 as INVENTORY
import private_heat_exact_growth_r1 as GROWTH
import private_heat_decimal_sparse_core_r1 as P

G = K.G


def functional_solve(matrix, rhs, *, budget, cancelled=None, evidence=None, resource_evidence=None):
    """Return an owner of exact answer; no approximate or tolerance fallback."""
    K._require_gmp()
    INVENTORY.check(cancelled)
    if (type(matrix) not in (list, tuple) or type(rhs) not in (list, tuple)
            or len(matrix) != len(rhs) or any(type(row) not in (list, tuple) or len(row) != len(rhs) for row in matrix)):
        raise ValueError('A square exact matrix and matching right-hand side are required')
    n = len(rhs)
    # The only pass before admission inspects scalar types/reported owned sizes;
    # no rational parts or decoded matrix copies are allocated.
    largest = 1
    for row in matrix:
        for value in row:
            INVENTORY.check(cancelled)
            if type(value) not in (int, G.mpq):
                raise TypeError('Already owned int/GMP rational matrix required')
            largest = max(largest, sys.getsizeof(value))
    for value in rhs:
        if type(value) not in (int, G.mpq):
            raise TypeError('Already owned int/GMP rational right-hand side required')
        largest = max(largest, sys.getsizeof(value))
    import private_heat_gmp_resources_r1 as R
    metadata = 262144+INVENTORY.D.CONTAINER_UNIT*(8*n*n+32*n+128)
    work = R.OwnedWorkspace(budget, metadata, category='heat-exact-functional-growth', cancelled=cancelled)
    work.__enter__()
    try:
        INVENTORY.verify_sources(cancelled)
        # Original/right references; current integer matrix; primitive row and
        # conversion lists; answer; pivot bookkeeping and 64 scalar temporaries.
        # All slots conservatively charged as mpq, even integer-only storage.
        arena = GROWTH.Arithmetic(work, G, scalar_slots=3*n*n+12*n+64,
            container_bytes=metadata, initial_bits=8*largest, cancelled=cancelled)
        answer = _run(matrix, rhs, arena=arena, cancelled=cancelled, evidence=evidence)
        if resource_evidence is not None:
            resource_evidence.update(admitted_bytes=work.lease.count,
                arithmetic_operations=arena.operations, largest_prospective_scalar_bits=arena.peak_bits,
                prospective_accounted_policy=True, allocator_or_rss_bound=False,
                gram_construction_admitted=False, observation_rank_reduction_admitted=False,
                whole_method_admission=False)
        return P.OwnedSolve(answer, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


def _run(matrix, rhs, *, arena, cancelled=None, evidence=None):
    """Return exact GMP rationals, retaining the original free-variables-zero rule.

    ``cancelled()`` may raise or return true. A supplied evidence dict reports
    the current scalar phase, rank and measured integer-bit maxima; it is also
    populated on cancellation/incompatibility. The supplied evidence retains the rank; no unbounded global rank log is kept.
    """
    K._require_gmp()
    began = perf_counter()
    audit = {} if evidence is None else evidence
    audit.update(status='RUNNING', algorithm='row-primitive-pivoted-Bareiss',
                 row_lcm_max_bits=0, initial_integer_max_bits=0,
                 peak_integer_bits=0, integer_updates=0, exact_divisions=0,
                 native_workbudget_admitted=False)

    def check(phase, row=None, column=None):
        audit.update(phase=phase, row=row, column=column)
        if cancelled is not None and cancelled():
            raise CancelledError('Exact face-functional solve cancelled at '+phase)

    def bits(value):
        return abs(value).bit_length()

    try:
        check('input')
        size = len(rhs)
        if len(matrix) != size or any(len(row) != size for row in matrix):
            raise ValueError('A square exact matrix and matching right-hand side are required')
        original, right, rows = [], [], []
        for i, (row, value) in enumerate(zip(matrix, rhs, strict=True)):
            check('denominator-row', i)
            rationals = []
            denominator = G.mpz(1)
            for j, element in enumerate([*row, value]):
                check('denominator-element', i, j)
                q = arena.q(element)
                rationals.append(q)
                denominator = arena.lcm(denominator, q.denominator)
            original.append(rationals[:-1])
            right.append(rationals[-1])
            audit['row_lcm_max_bits'] = max(audit['row_lcm_max_bits'], bits(denominator))
            integers, content = [], G.mpz(0)
            for j, q in enumerate(rationals):
                check('integer-element', i, j)
                integer = arena.imul(q.numerator, arena.idiv(denominator, q.denominator))
                integers.append(integer)
                content = arena.gcd(content, integer)
            if content > 1:
                for j, integer in enumerate(integers):
                    check('primitive-row-element', i, j)
                    integers[j] = arena.idiv(integer, content)
            rows.append(integers)
            maximum = max(map(bits, integers), default=0)
            audit['initial_integer_max_bits'] = max(audit['initial_integer_max_bits'], maximum)
        audit['peak_integer_bits'] = audit['initial_integer_max_bits']
        pivots, previous = [], G.mpz(1)
        for column in range(size):
            rank = len(pivots)
            check('pivot', rank, column)
            found = None
            for i in range(rank, size):
                check('pivot-search-row', i, column)
                if rows[i][column]:
                    found = i
                    break
            if found is None:
                continue
            rows[rank], rows[found] = rows[found], rows[rank]
            pivot = rows[rank][column]
            for i in range(rank+1, size):
                check('elimination-row', i, column)
                coefficient = rows[i][column]
                # Even when coefficient is zero, the remaining row must be
                # scaled by pivot/previous. Skipping that row breaks Bareiss.
                for j in range(column+1, size+1):
                    check('elimination-element', i, j)
                    numerator = arena.isub(arena.imul(pivot, rows[i][j]), arena.imul(coefficient, rows[rank][j]))
                    audit['peak_integer_bits'] = max(audit['peak_integer_bits'], bits(numerator))
                    if previous != 1:
                        check('exact-division-element', i, j)
                        quotient, remainder = arena.divmod(numerator, previous)
                        if remainder:
                            raise ArithmeticError('Fraction-free elimination division was not exact')
                        audit['exact_divisions'] += 1
                    else:
                        quotient = numerator
                    rows[i][j] = quotient
                    audit['integer_updates'] += 1
                rows[i][column] = G.mpz(0)
            pivots.append(column)
            previous = pivot
        rank = len(pivots)
        inconsistent = False
        for i in range(rank, size):
            check('compatibility-row', i)
            if any(rows[i][j] for j in range(size)):
                raise ArithmeticError('Uneliminated coefficient remained below the exact rank')
            if rows[i][-1]:
                inconsistent = True
        audit.update(dimension=size, rank=rank, pivot_columns=pivots[:], consistent=not inconsistent)
        if inconsistent:
            audit['status'] = 'EXACT_INCOMPATIBLE'
            raise ValueError(f'Face functional not representable: rank {rank}/{size}; exact integer-reduced inconsistency is nonzero')
        answer = [arena.q(0)]*size
        for i, column in reversed(list(enumerate(pivots))):
            check('back-substitution-row', i, column)
            value = arena.q(rows[i][-1])
            for j in range(column+1, size):
                check('back-substitution-element', i, j)
                value = arena.rational('subtract', value, arena.rational('multiply', rows[i][j], answer[j]))
            answer[column] = arena.rational('divide', value, rows[i][column])
        for i, (row, target) in enumerate(zip(original, right, strict=True)):
            check('original-residual-row', i)
            value = arena.q(0)
            for j, (a, b) in enumerate(zip(row, answer, strict=True)):
                check('original-residual-element', i, j)
                value = arena.rational('add', value, arena.rational('multiply', a, b))
            if value != target:
                raise ArithmeticError('Exact answer failed the original rational system')
        check('complete')
        audit.update(status='EXACT_COMPATIBLE', original_residual_exact_zero=True,
            free_variables_exact_zero=all(not answer[j] for j in range(size) if j not in pivots),
            answer_max_numerator_bits=max((bits(q.numerator) for q in answer), default=0),
            answer_max_denominator_bits=max((bits(q.denominator) for q in answer), default=0))
        return answer
    except CancelledError:
        audit['status'] = 'CANCELLED'
        raise
    finally:
        audit['seconds'] = perf_counter()-began

