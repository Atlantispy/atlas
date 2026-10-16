"""Staged exact heat certificates, no experiment/control imports.

Numerical extraction of the already-tested exact rank, fraction-free functional,
directed interval and singleton-moment kernels. Same original constraints,
canonical witness, declared precision ladder and conservative refusals.
This file is outside the native package and is NOT native resource admission.
The caller still owes prospective limb/MPFR/container and retained-result funding.
Selected GMP is required only for method calls; Python-backend import is safe.
"""
from collections.abc import Sequence
from concurrent.futures import CancelledError
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from operator import index
from time import perf_counter

from atlas_tectonics.exact_arithmetic import library

G = library()  # Process-constant selected library; never imports a new backend.
PRIME = (1 << 61)-1
PRECISIONS = (320, 640, 1280, 2560)


def _require_gmp():
    if G is None:
        raise RuntimeError('Certified composed heat requires the selected sealed GMP backend')


def qhex(q):
    _require_gmp()
    q = G.mpq(q)
    return [q.numerator.digits(16), q.denominator.digits(16)]


def _rank_q(value):
    if isinstance(value, G.mpq):
        return value
    return G.mpq(index(value.numerator), index(value.denominator))


def _reduce_reference(matrix, target, *, cancelled=None, evidence=None):
    """Return exact reduced matrix/target or a verified incompatibility witness.

    Compatible output includes `independent_columns`, `matrix`, `target` and
    `column_coordinates` (C, shaped rank x original-column-count). Rank zero
    has empty reduced rows/target; callers must use the exact zero correction,
    not call a nonsingular interval solver. Evidence contains JSON-safe counts.
    Original observation row order is preserved in the reduced matrix.
    """
    _require_gmp()
    began = perf_counter()
    audit = {} if evidence is None else evidence
    audit.update(status='RUNNING', algorithm='primitive-rectangular-Bareiss-plus-integer-original-column-certificate',
        gram_constructed=False, row_lcm_max_bits=0, initial_integer_max_bits=0,
        peak_integer_bits=0, integer_updates=0, exact_divisions=0,
        verified_dependent_columns=0, native_workbudget_admitted=False,
        certificate_integer_products=0, certificate_scale_max_bits=0,
        target_scale_bits=0, certificate_rational_accumulator_operations=0)

    def check(phase, row=None, column=None):
        audit.update(phase=phase, row=row, column=column)
        if cancelled is not None and cancelled():
            raise CancelledError('Observation rank reduction cancelled at '+phase)

    def bits(value):
        return abs(value).bit_length()

    try:
        check('input')
        m, n = len(matrix), len(target)
        if not m or not n or any(len(row) != n for row in matrix):
            raise ValueError('Nonempty rectangular observations and matching target required')
        original, rows, original_primitive = [], [], []
        right = [_rank_q(value) for value in target]
        for i, row in enumerate(matrix):
            check('denominator-row', i)
            values, denominator = [], G.mpz(1)
            for j, value in enumerate(row):
                check('denominator-element', i, j)
                value = _rank_q(value)
                values.append(value)
                denominator = G.lcm(denominator, value.denominator)
            original.append(values)
            audit['row_lcm_max_bits'] = max(audit['row_lcm_max_bits'], bits(denominator))
            integers, content = [], G.mpz(0)
            for j, value in enumerate(values):
                check('integer-element', i, j)
                integer = value.numerator*(denominator//value.denominator)
                integers.append(integer)
                content = G.gcd(content, integer)
            if content > 1:
                for j, value in enumerate(integers):
                    check('primitive-element', i, j)
                    integers[j] = value//content
            original_primitive.append(tuple(integers))
            rows.append(integers)
            audit['initial_integer_max_bits'] = max(audit['initial_integer_max_bits'], max(map(bits, integers)))
        audit['peak_integer_bits'] = audit['initial_integer_max_bits']
        pivots, previous = [], G.mpz(1)
        for column in range(n):
            rank = len(pivots)
            check('pivot', rank, column)
            found = next((i for i in range(rank, m) if rows[i][column]), None)
            if found is None:
                continue
            rows[rank], rows[found] = rows[found], rows[rank]
            pivot = rows[rank][column]
            for i in range(rank+1, m):
                check('elimination-row', i, column)
                coefficient = rows[i][column]
                for j in range(column+1, n):
                    check('elimination-element', i, j)
                    numerator = pivot*rows[i][j]-coefficient*rows[rank][j]
                    audit['peak_integer_bits'] = max(audit['peak_integer_bits'], bits(numerator))
                    if previous != 1:
                        quotient, remainder = divmod(numerator, previous)
                        if remainder:
                            raise ArithmeticError('Rectangular Bareiss division was not exact')
                        audit['exact_divisions'] += 1
                    else:
                        quotient = numerator
                    rows[i][j] = quotient
                    audit['integer_updates'] += 1
                rows[i][column] = G.mpz(0)
            pivots.append(column)
            previous = pivot
            if len(pivots) == m:
                break
        rank = len(pivots)
        if any(any(row) for row in rows[rank:]):
            raise ArithmeticError('Nonzero row below claimed exact observation rank')
        audit.update(rank=rank, observations=m, polynomial_columns=n, independent_columns=pivots[:])
        coordinates = [[G.mpq(int(column == pivot)) for column in range(n)] for pivot in pivots]
        independent = set(pivots)
        target_denominator, target_integer = G.mpz(1), []
        if rank < n:
            for j, value in enumerate(right):
                check('target-denominator', column=j)
                target_denominator = G.lcm(target_denominator, value.denominator)
            audit['target_scale_bits'] = bits(target_denominator)
            for j, value in enumerate(right):
                check('target-integer', column=j)
                target_integer.append(value.numerator*(target_denominator//value.denominator))
        for column in range(n):
            if column in independent:
                continue
            check('dependency-back-substitution', column=column)
            weights = [G.mpq(0)]*rank
            for i in range(rank-1, -1, -1):
                check('dependency-row', i, column)
                value = G.mpq(rows[i][column])
                for j in range(i+1, rank):
                    check('dependency-element', i, column)
                    value -= rows[i][pivots[j]]*weights[j]
                weights[i] = value/rows[i][pivots[i]]
            coefficient_denominator = G.mpz(1)
            for j, value in enumerate(weights):
                check('coefficient-denominator', j, column)
                coefficient_denominator = G.lcm(coefficient_denominator, value.denominator)
            integer_weights = []
            for j, value in enumerate(weights):
                check('coefficient-integer', j, column)
                integer_weights.append(value.numerator*(coefficient_denominator//value.denominator))
            audit['certificate_scale_max_bits'] = max(audit['certificate_scale_max_bits'],
                                                       bits(coefficient_denominator))
            for i, row in enumerate(original_primitive):
                check('original-integer-column-certificate', i, column)
                value = G.mpz(0)
                for j, pivot in enumerate(pivots):
                    check('original-integer-column-element', i, column)
                    value += row[pivot]*integer_weights[j]
                    audit['certificate_integer_products'] += 1
                if value != row[column]*coefficient_denominator:
                    raise ArithmeticError('Column dependency failed original exact integer observations')
            audit['verified_dependent_columns'] += 1
            residual_integer = target_integer[column]*coefficient_denominator
            for j, pivot in enumerate(pivots):
                check('target-integer-certificate', j, column)
                residual_integer -= target_integer[pivot]*integer_weights[j]
                audit['certificate_integer_products'] += 1
            residual = G.mpq(residual_integer, target_denominator*coefficient_denominator)
            if residual:
                witness = [G.mpq(0)]*n
                witness[column] = G.mpq(1)
                for pivot, value in zip(pivots, weights, strict=True):
                    witness[pivot] = -value
                audit.update(status='EXACT_INCOMPATIBLE', incompatible_column=column,
                    null_witness_verified=True, target_witness_numerator_bits=bits(residual.numerator),
                    target_witness_denominator_bits=bits(residual.denominator))
                return dict(compatible=False, rank=rank, independent_columns=pivots,
                            null_witness=witness, target_witness=residual, evidence=audit)
            for i, value in enumerate(weights):
                coordinates[i][column] = value
        check('complete')
        audit.update(status='EXACT_COMPATIBLE', original_column_identities_exact=True,
                     all_target_dependencies_exact=True, minimum_norm_weights_unchanged=True)
        return dict(compatible=True, rank=rank, independent_columns=pivots,
                    matrix=[[row[j] for j in pivots] for row in original],
                    target=[right[j] for j in pivots], column_coordinates=coordinates, evidence=audit)
    except CancelledError:
        audit['status'] = 'CANCELLED'
        raise
    finally:
        audit['seconds'] = perf_counter()-began


def reduce_observations(matrix, target, *, cancelled=None, evidence=None):
    _require_gmp()
    began = perf_counter()
    audit = {} if evidence is None else evidence
    audit.update(status='RUNNING', algorithm='modular-minor-square-Bareiss-integer-backsub',
                 gram_constructed=False, native_workbudget_admitted=False,
                 modular_prime=PRIME, modular_rank_is_only_lower_bound=True,
                 exact_divisions=0, integer_updates=0, peak_integer_bits=0,
                 certificate_integer_products=0, fallback_used=False)

    def check(phase, row=None, column=None):
        audit.update(phase=phase, row=row, column=column)
        if cancelled is not None and cancelled():
            raise CancelledError('Modular observation reduction cancelled at '+phase)

    def exact_divide(numerator, denominator):
        quotient, remainder = divmod(numerator, denominator)
        audit['exact_divisions'] += 1
        if remainder:
            raise ArithmeticError('Selected-minor integer division not exact')
        return quotient

    def fallback(reason):
        audit.update(fallback_used=True, fallback_reason=reason)
        details = {}
        result = _reduce_reference(matrix, target, cancelled=cancelled, evidence=details)
        audit.update(status=details['status'], fallback_evidence=details, rank=result['rank'],
                     independent_columns=result['independent_columns'])
        result['evidence'] = audit
        return result

    try:
        check('input')
        m, n = len(matrix), len(target)
        if not m or not n or any(len(row) != n for row in matrix):
            raise ValueError('Nonempty rectangular observations and matching target required')
        original, primitive = [], []
        right = list(map(_rank_q, target))
        for i, row in enumerate(matrix):
            check('denominator-row', i)
            values, denominator = list(map(_rank_q, row)), G.mpz(1)
            for j, value in enumerate(values):
                check('denominator-element', i, j)
                denominator = G.lcm(denominator, value.denominator)
            integers, content = [], G.mpz(0)
            for j, value in enumerate(values):
                check('primitive-element', i, j)
                integer = value.numerator*(denominator//value.denominator)
                integers.append(integer)
                content = G.gcd(content, integer)
            if content > 1:
                integers = [value//content for value in integers]
            original.append(values)
            primitive.append(integers)
            audit['peak_integer_bits'] = max(audit['peak_integer_bits'],
                                             max(value.bit_length() for value in integers))
        modular = []
        for i, row in enumerate(primitive):
            check('modular-conversion', i)
            modular.append([int(value % PRIME) for value in row])
        row_ids, pivots = list(range(m)), []
        for column in range(n):
            rank = len(pivots)
            check('modular-pivot', rank, column)
            found = next((i for i in range(rank, m) if modular[i][column]), None)
            if found is None:
                continue
            modular[rank], modular[found] = modular[found], modular[rank]
            row_ids[rank], row_ids[found] = row_ids[found], row_ids[rank]
            inverse = pow(modular[rank][column], -1, PRIME)
            for i in range(rank+1, m):
                coefficient = modular[i][column]*inverse % PRIME
                if coefficient:
                    for j in range(column+1, n):
                        check('modular-element', i, j)
                        modular[i][j] = (modular[i][j]-coefficient*modular[rank][j]) % PRIME
                modular[i][column] = 0
            pivots.append(column)
            if len(pivots) == m:
                break
        rank = len(pivots)
        selected = row_ids[:rank]
        dependent = [j for j in range(n) if j not in pivots]
        audit.update(rank=rank, observations=m, polynomial_columns=n,
                     independent_columns=pivots[:], selected_rows=selected,
                     modular_minor_nonzero=True, exact_elimination_rows=rank)
        coordinates = [[G.mpq(int(j == pivot)) for j in range(n)] for pivot in pivots]
        # At full column rank no compatibility constraints remain. Nonzero
        # modular determinant already proves exact rank, with no huge solve.
        if dependent:
            order = pivots+dependent
            rows = [[primitive[i][j] for j in order] for i in selected]
            previous = G.mpz(1)
            for k in range(max(0, rank-1)):
                check('square-pivot', k, k)
                pivot = rows[k][k]
                if not pivot:
                    return fallback('unexpected zero pivot in modularly nonsingular minor')
                for i in range(k+1, rank):
                    coefficient = rows[i][k]
                    for j in range(k+1, n):
                        check('elimination-element', i, j)
                        value = pivot*rows[i][j]-coefficient*rows[k][j]
                        audit['peak_integer_bits'] = max(audit['peak_integer_bits'], value.bit_length())
                        rows[i][j] = value if previous == 1 else exact_divide(value, previous)
                        audit['integer_updates'] += 1
                    rows[i][k] = G.mpz(0)
                previous = pivot
            determinant = rows[-1][rank-1] if rank else G.mpz(1)
            if not determinant:
                return fallback('unexpected singular selected minor')
            target_denominator = G.mpz(1)
            for j, value in enumerate(right):
                check('target-denominator', column=j)
                target_denominator = G.lcm(target_denominator, value.denominator)
            target_integer = [value.numerator*(target_denominator//value.denominator) for value in right]
            residuals = []
            for dependent_index, column in enumerate(dependent):
                numerators = [G.mpz(0)]*rank
                for i in range(rank-1, -1, -1):
                    check('integer-backsub-row', i, column)
                    value = determinant*rows[i][rank+dependent_index]
                    for j in range(i+1, rank):
                        check('integer-backsub-element', i, column)
                        value -= rows[i][j]*numerators[j]
                    numerators[i] = exact_divide(value, rows[i][i])
                # Remove a common factor once, not a rational gcd at every sum.
                common = determinant
                for i, value in enumerate(numerators):
                    check('dependency-content', i, column)
                    common = G.gcd(common, value)
                denominator = determinant//common
                numerators = [value//common for value in numerators]
                for i, row in enumerate(primitive):
                    value = G.mpz(0)
                    for j, pivot in enumerate(pivots):
                        check('original-integer-column-element', i, column)
                        value += row[pivot]*numerators[j]
                        audit['certificate_integer_products'] += 1
                    if value != row[column]*denominator:
                        return fallback('modular lower rank failed all-original-row column certificate')
                if any(value and pivot > column for value, pivot in zip(numerators, pivots, strict=True)):
                    return fallback('unlucky prime changed canonical independent-column order')
                residual_integer = target_integer[column]*denominator
                for j, pivot in enumerate(pivots):
                    check('target-integer-certificate', j, column)
                    residual_integer -= target_integer[pivot]*numerators[j]
                weights = [G.mpq(value, denominator) for value in numerators]
                residual = G.mpq(residual_integer, target_denominator*denominator)
                residuals.append(residual)
                for i, value in enumerate(weights):
                    coordinates[i][column] = value
            # Every original column is now certified. Examine target relations
            # in r2 order so its normalised incompatibility witness is preserved.
            for column, residual in zip(dependent, residuals, strict=True):
                check('target-final-certificate', column=column)
                if residual:
                    witness = [G.mpq(0)]*n
                    witness[column] = G.mpq(1)
                    for i, pivot in enumerate(pivots):
                        witness[pivot] = -coordinates[i][column]
                    audit.update(status='EXACT_INCOMPATIBLE', incompatible_column=column,
                                 null_witness_verified=True, original_column_identities_exact=True)
                    return dict(compatible=False, rank=rank, independent_columns=pivots,
                                null_witness=witness, target_witness=residual, evidence=audit)
        check('complete')
        audit.update(status='EXACT_COMPATIBLE', original_column_identities_exact=True,
                     all_target_dependencies_exact=True, minimum_norm_weights_unchanged=True)
        return dict(compatible=True, rank=rank, independent_columns=pivots,
                    matrix=[[row[j] for j in pivots] for row in original],
                    target=[right[j] for j in pivots], column_coordinates=coordinates, evidence=audit)
    except CancelledError:
        audit['status'] = 'CANCELLED'
        raise
    finally:
        audit['seconds'] = perf_counter()-began


def _functional_q(value):
    if isinstance(value, G.mpq):
        return value
    if hasattr(value, 'numerator') and hasattr(value, 'denominator'):
        return G.mpq(int(value.numerator), int(value.denominator))
    return G.mpq(value)


def functional_solve(matrix, rhs, *, cancelled=None, evidence=None):
    """Return exact GMP rationals, retaining the original free-variables-zero rule.

    ``cancelled()`` may raise or return true. A supplied evidence dict reports
    the current scalar phase, rank and measured integer-bit maxima; it is also
    populated on cancellation/incompatibility. The supplied evidence retains the rank; no unbounded global rank log is kept.
    """
    _require_gmp()
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
                q = _functional_q(element)
                rationals.append(q)
                denominator = G.lcm(denominator, q.denominator)
            original.append(rationals[:-1])
            right.append(rationals[-1])
            audit['row_lcm_max_bits'] = max(audit['row_lcm_max_bits'], bits(denominator))
            integers, content = [], G.mpz(0)
            for j, q in enumerate(rationals):
                check('integer-element', i, j)
                integer = q.numerator*(denominator//q.denominator)
                integers.append(integer)
                content = G.gcd(content, integer)
            if content > 1:
                for j, integer in enumerate(integers):
                    check('primitive-row-element', i, j)
                    integers[j] = integer//content
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
                    numerator = pivot*rows[i][j]-coefficient*rows[rank][j]
                    audit['peak_integer_bits'] = max(audit['peak_integer_bits'], bits(numerator))
                    if previous != 1:
                        check('exact-division-element', i, j)
                        quotient, remainder = divmod(numerator, previous)
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
        answer = [G.mpq(0)]*size
        for i, column in reversed(list(enumerate(pivots))):
            check('back-substitution-row', i, column)
            value = G.mpq(rows[i][-1])
            for j in range(column+1, size):
                check('back-substitution-element', i, j)
                value -= rows[i][j]*answer[j]
            answer[column] = value/rows[i][column]
        for i, (row, target) in enumerate(zip(original, right, strict=True)):
            check('original-residual-row', i)
            value = G.mpq(0)
            for j, (a, b) in enumerate(zip(row, answer, strict=True)):
                check('original-residual-element', i, j)
                value += a*b
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


class InconsistentConstraints(ValueError):
    """A literal exact moment constraint contradicts feasibility."""


def _moment_q(value):
    try:
        return G.mpq(value)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError) as error:
        raise ValueError('Finite exact-rational observation/target values required') from error


def forced_coefficients(matrix, target, *, cancelled=None, evidence=None):
    """Return {observation row index: exact GMP rational} from singleton columns.

    This is a necessary-constraint screen, not a rank or feasibility proof.
    Multiple supported rows in a column yield no inference, even for t[j]=0.
    Evidence retains exact witnesses; its caller owns persistent encoding.
    """
    def check():
        if cancelled is not None and cancelled():
            raise CancelledError('Structural moment screen cancelled')

    _require_gmp()
    check()
    if (not isinstance(matrix, Sequence) or isinstance(matrix, (str, bytes)) or not matrix
            or not isinstance(target, Sequence) or isinstance(target, (str, bytes)) or not target):
        raise ValueError('Nonempty rectangular observations and target required')
    n = len(target)
    if any(not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != n for row in matrix):
        raise ValueError('Every observation row must match the target width')
    rhs = []
    for value in target:
        check()
        rhs.append(_moment_q(value))
    support, coefficients = [None]*n, [G.mpq(0)]*n
    for i, row in enumerate(matrix):
        check()
        for j, value in enumerate(row):
            check()
            value = _moment_q(value)
            if value:
                if support[j] is None:
                    support[j], coefficients[j] = i, value
                else:
                    support[j] = -1  # Two or more nonzero rows; no inference.
    audit = {} if evidence is None else evidence
    audit.update(method='exact-singleton-column-necessary-constraints', observation_rows=len(matrix),
                 polynomial_columns=n, rank_or_feasibility_certified=False,
                 coefficient_scope='observation coefficient before base jump and conversion',
                 zero_columns=[], witnesses=[], status='CHECKING')
    forced = {}
    for j, i in enumerate(support):
        check()
        if i is None:
            audit['zero_columns'].append(j)
            if rhs[j]:
                audit.update(status='INCONSISTENT_ZERO_COLUMN', conflicting_column=j)
                raise InconsistentConstraints('Zero observation column '+str(j)+' has a nonzero target')
        elif i >= 0:
            value = rhs[j]/coefficients[j]
            audit['witnesses'].append(dict(column=j, observation_index=i, coefficient=coefficients[j],
                                            target=rhs[j], forced_value=value))
            if i in forced and forced[i] != value:
                audit.update(status='INCONSISTENT_SINGLETON_WITNESSES', conflicting_observation_index=i)
                raise InconsistentConstraints('Singleton columns force conflicting coefficients for observation '+str(i))
            forced[i] = value
    check()
    audit.update(status='NECESSARY_FORCED_COEFFICIENTS_PROVED', forced_observation_count=len(forced))
    return forced




class Unresolved(ArithmeticError):
    """No certificate obtained; this does not establish singularity/error."""


def decimal80(q):
    q = G.mpq(q)
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_HALF_EVEN
        return Decimal(int(q.numerator))/Decimal(int(q.denominator))


def round_bounds(bounds):
    """Correctly round only if EVERY real in the closed enclosure agrees."""
    lo, hi = bounds
    if lo > hi or not G.is_finite(lo) or not G.is_finite(hi):
        raise ValueError('Finite ordered enclosure required')
    a, b = decimal80(G.mpq(lo)), decimal80(G.mpq(hi))
    # Signed zero is conservatively distinguished; no tiny-value zero rule.
    if a != b or (a.is_zero() and a.is_signed() != b.is_signed()):
        raise Unresolved('Enclosure crosses a Decimal80 rounding boundary')
    return a


# H3: compiled interval dot batches (private_heat_compiled_dot_r1, pinned below).
_H3_NAME = 'private_heat_compiled_dot_r1'
_H3_SHA256 = '62c100cff79742d4254d291b40c529794b857894e1fd2d41e1aa28db8699682a'
_H3 = []


def _h3_module():
    """The pinned compiled module, or None (the original Python route) if it cannot load.

    The helper beside this kernel is read once, hashed, and exactly those bytes run.
    """
    if not _H3:
        import sys as _sys
        import types as _types
        from hashlib import sha256 as _sha256
        from pathlib import Path as _Path
        path = _Path(__file__).resolve().parent/(_H3_NAME+'.py')
        try:
            data = path.read_bytes()
        except OSError as error:
            _H3.append((None, 'unavailable: %s' % error))
            return None
        if _sha256(data).hexdigest() != _H3_SHA256:
            raise RuntimeError('compiled interval dot helper beside this kernel is not the pinned file')
        seal = (str(path), _H3_SHA256)
        module = _sys.modules.get(_H3_NAME)
        if module is not None:
            if getattr(module, '_H3_SEAL', None) != seal:
                raise RuntimeError('another compiled interval dot module is already loaded')
        else:
            module = _types.ModuleType(_H3_NAME)
            module.__file__ = str(path)
            _sys.modules[_H3_NAME] = module
            try:
                exec(compile(data, str(path), 'exec'), module.__dict__)
            except Exception as error:  # ImportError: not the reviewed build; or it cannot be built
                del _sys.modules[_H3_NAME]
                _H3.append((None, 'unavailable: %s: %s' % (type(error).__name__, error)))
                return None
            module._H3_SEAL = seal
        _H3.append((module, 'compiled'))
    return _H3[0][0]


def h3_status():
    module = _h3_module()
    return dict(route=_H3[0][1], pinned_sha256=_H3_SHA256,
                build=None if module is None else module.build_info())


def _h3_plain(ar):
    """A plain Arithmetic: not a subclass, no instance-level replacement of a method used."""
    return type(ar) is Arithmetic and not any(name in ar.__dict__ for name in ('check', 'point', 'dot', 'mul', 'add'))


def _h3_batch(ar, x_rows, y_rows, gram=False):
    """[[ar.dot(x, y) for y in y_rows] for x in x_rows] compiled, or None to run the original."""
    if not _h3_plain(ar):
        return None
    if not x_rows or not y_rows or not len(x_rows[0]):
        return None  # r1 makes no check() call for an empty dot
    module = _h3_module()
    if module is None:
        return None
    ar.check('interval-product')
    try:
        return module.pair_dots(x_rows, y_rows, ar.down, ar.up, gram=gram,
                                check=lambda: ar.check('interval-product'))
    except module.Unavailable:
        return None


class Arithmetic:
    """Explicit contexts prevent dependence on or changes to global precision."""
    def __init__(self, precision, cancelled=None, evidence=None):
        _require_gmp()
        options = dict(precision=precision, trap_underflow=True, trap_overflow=True,
                       trap_invalid=True, trap_divzero=True, trap_erange=True)
        self.down = G.context(**options, round=G.RoundDown)
        self.up = G.context(**options, round=G.RoundUp)
        self.near = G.context(**options, round=G.RoundToNearest)
        self.cancelled, self.evidence = cancelled, evidence
        with self.near:
            self.zero, self.one = G.mpfr(0), G.mpfr(1)

    def check(self, phase):
        if self.evidence is not None:
            self.evidence['phase'] = phase
        if self.cancelled is not None and self.cancelled():
            raise CancelledError('Interval functional cancelled at '+phase)

    def point(self, q):
        self.check('directed-input')
        with self.down:
            lo = G.mpfr(q)
        with self.up:
            hi = G.mpfr(q)
        if not G.is_finite(lo) or not G.is_finite(hi):
            raise Unresolved('Nonfinite interval input')
        return lo, hi

    def add(self, a, b):
        self.check('interval-add')
        return self.down.add(a[0], b[0]), self.up.add(a[1], b[1])

    def sub(self, a, b):
        self.check('interval-subtract')
        return self.down.sub(a[0], b[1]), self.up.sub(a[1], b[0])

    def mul(self, a, b):
        self.check('interval-product')
        return (min(self.down.mul(x, y) for x in a for y in b),
                max(self.up.mul(x, y) for x in a for y in b))

    def dot(self, a, b):
        if type(self) is not Arithmetic or 'mul' in self.__dict__ or 'add' in self.__dict__:
            value = (self.zero, self.zero)
            for x, y in zip(a, b, strict=True):
                value = self.add(value, self.mul(x, y))
            return value
        # H2: mul() then add() of each pair fused, with the same checks, contexts,
        # products, comparisons and accumulation order (min/max written out).
        check, dmul, umul, dadd, uadd = self.check, self.down.mul, self.up.mul, self.down.add, self.up.add
        lo = hi = self.zero
        for x, y in zip(a, b, strict=True):
            if type(x) is not tuple or type(y) is not tuple or len(x) != 2 or len(y) != 2:
                lo, hi = self.add((lo, hi), self.mul(x, y))
                continue
            x0, x1 = x
            y0, y1 = y
            check('interval-product')
            plo = dmul(x0, y0)
            t = dmul(x0, y1)
            if t < plo:
                plo = t
            t = dmul(x1, y0)
            if t < plo:
                plo = t
            t = dmul(x1, y1)
            if t < plo:
                plo = t
            phi = umul(x0, y0)
            t = umul(x0, y1)
            if t > phi:
                phi = t
            t = umul(x1, y0)
            if t > phi:
                phi = t
            t = umul(x1, y1)
            if t > phi:
                phi = t
            check('interval-add')
            lo, hi = dadd(lo, plo), uadd(hi, phi)
        return lo, hi

    def absmax(self, value):
        return max(self.up.abs(value[0]), self.up.abs(value[1]))

    def midpoint(self, bounds):
        return self.near.div(self.near.add(*bounds), 2)


def approximate_inverse(a, arithmetic):
    """Untrusted point proposal; only the subsequent interval proof admits it."""
    ar, n = arithmetic, len(a)
    rows = [[ar.midpoint(v) for v in row]+[ar.one if i == j else ar.zero for j in range(n)]
            for i, row in enumerate(a)]
    for j in range(n):
        ar.check('approximate-inverse-pivot')
        index = max(range(j, n), key=lambda i: ar.near.abs(rows[i][j]))
        if not rows[index][j]:
            raise Unresolved('Rounded proposal has zero pivot; no rank conclusion')
        rows[j], rows[index] = rows[index], rows[j]
        pivot = rows[j][j]
        rows[j] = [ar.near.div(v, pivot) for v in rows[j]]
        for i in range(n):
            ar.check('approximate-inverse-row')
            if i != j:
                value = rows[i][j]
                rows[i] = [ar.near.sub(x, ar.near.mul(value, y))
                           for x, y in zip(rows[i], rows[j], strict=True)]
    return [row[n:] for row in rows]


def solve_enclosure(matrix, rhs, *, precision, cancelled=None, evidence=None):
    """Return bounds on the exact full-rank Gram dual; no exact Gram created."""
    ar = Arithmetic(precision, cancelled, evidence)
    n = len(rhs)
    if not n or not matrix or any(len(row) != n for row in matrix):
        raise ValueError('Nonempty rectangular observations and matching target required')
    m = [[ar.point(q) for q in row] for row in matrix]
    b = [ar.point(q) for q in rhs]
    columns = list(zip(*m, strict=True))
    a = _h3_batch(ar, columns, columns, gram=True)
    if a is None:
        a = [[ar.dot(x, y) for y in columns] for x in columns]
    else:
        ar.check('interval-add')
    r = approximate_inverse(a, ar)
    ri = [[(v, v) for v in row] for row in r]
    xhat = []
    for row in r:
        value = ar.zero
        for v, bound in zip(row, b, strict=True):
            value = ar.near.add(value, ar.near.mul(v, ar.midpoint(bound)))
        xhat.append(value)
    a_columns = list(zip(*a, strict=True))
    rho = ar.zero
    for i, row in enumerate(ri):
        total = ar.zero
        dots = _h3_batch(ar, [row], a_columns)
        dots = None if dots is None else dots[0]
        for j, column in enumerate(a_columns):
            eye = ar.one if i == j else ar.zero
            item = ar.sub((eye, eye), ar.dot(row, column) if dots is None else dots[j])
            total = ar.up.add(total, ar.absmax(item))
        rho = max(rho, total)
    if not G.is_finite(rho) or rho >= ar.one:
        raise Unresolved('Inverse defect norm is not certified below one')
    dots = _h3_batch(ar, a, [[(x, x) for x in xhat]])
    if dots is None:
        residual = [ar.sub(v, ar.dot(row, [(x, x) for x in xhat]))
                    for row, v in zip(a, b, strict=True)]
    else:
        residual = [ar.sub(v, dot[0]) for dot, v in zip(dots, b, strict=True)]
    dots = _h3_batch(ar, ri, [residual])
    if dots is None:
        eta = max(ar.absmax(ar.dot(row, residual)) for row in ri)
    else:
        ar.check('interval-add')
        eta = max(ar.absmax(dot[0]) for dot in dots)
    radius = ar.up.div(eta, ar.down.sub(ar.one, rho))
    if not G.is_finite(radius):
        raise Unresolved('Nonfinite proved error radius')
    bounds = [(ar.down.sub(x, radius), ar.up.add(x, radius)) for x in xhat]
    ar.check('dual-certified')
    return bounds, ar, dict(precision_bits=precision, rank=n,
                            inverse_defect_upper=rho, dual_radius_upper=radius)


def physical_bounds(matrix, dual, keys, base_keys, signed_tau, conversion, ar):
    if len(keys) != len(matrix) or len(conversion) != len(keys) or len(set(keys)) != len(keys):
        raise ValueError('Unique matching observation identities and conversions required')
    if len(base_keys) != 2 or base_keys[0] == base_keys[1]:
        raise ValueError('Distinct owner/base keys required')
    rows = dots = None
    if _h3_plain(ar) and _h3_module() is not None:
        try:
            rows = [[ar.point(q) for q in row] for row in matrix]
        except CancelledError:
            raise  # observed at a conversion, as r1's first check is one
        except Exception:
            # r1 interleaves these conversions with its dots: any other exception reruns
            # r1's own interleaved expression below, so the first exception is r1's.
            rows = None
    if rows is not None:
        dots = _h3_batch(ar, rows, [dual])
    if dots is None:
        result = {key: ar.dot([ar.point(q) for q in row], dual)
                  for key, row in zip(keys, matrix, strict=True)}
    else:
        ar.check('interval-add')
        result = {key: dot[0] for key, dot in zip(keys, dots, strict=True)}
    tau = ar.point(signed_tau)
    zero = (ar.zero, ar.zero)
    result[base_keys[0]] = ar.add(result.get(base_keys[0], zero), tau)
    result[base_keys[1]] = ar.sub(result.get(base_keys[1], zero), tau)
    factors = dict(zip(keys, conversion, strict=True))
    for key in base_keys:
        if key[0] not in ('cell', 'wall'):
            raise ValueError('Base jump must use declared temperature observations')
        factors.setdefault(key, G.mpq(1))
    return {key: ar.mul(bound, ar.point(factors[key])) for key, bound in result.items()}




class ExactIncompatibility(ArithmeticError):
    """An exact necessary moment constraint proves infeasibility."""


def certified_weights(matrix, rhs, keys, base_keys, signed_tau, conversion, *,
                      precisions=PRECISIONS, cancelled=None, evidence=None):
    """Enclose unchanged exact weights, refining only algebraically fixed ones."""
    _require_gmp()
    audit = {} if evidence is None else evidence
    audit['attempts'] = []
    audit['singleton_moments'] = {}
    try:
        forced = forced_coefficients(matrix, rhs, cancelled=cancelled,
                                       evidence=audit['singleton_moments'])
    except InconsistentConstraints as error:
        raise ExactIncompatibility(str(error)) from error
    finally:
        for witness in audit['singleton_moments'].get('witnesses', []):
            for name in ('coefficient', 'target', 'forced_value'):
                witness[name] = qhex(witness[name])
        audit['singleton_moments']['scalar_encoding'] = 'canonical signed-hex rational pairs'
    if len(keys) != len(matrix) or len(conversion) != len(keys) or len(set(keys)) != len(keys):
        raise ValueError('Unique matching observation identities and conversions required')
    if len(base_keys) != 2 or base_keys[0] == base_keys[1]:
        raise ValueError('Distinct owner/base keys required')
    signed_tau = G.mpq(signed_tau)
    conversion = [G.mpq(value) for value in conversion]
    physical = {}
    for index, value in forced.items():
        key = keys[index]
        jump = signed_tau if key == base_keys[0] else -signed_tau if key == base_keys[1] else G.mpq(0)
        physical[key] = (value+jump)*conversion[index]
    for precision in precisions:
        attempt = dict(precision_bits=precision)
        began = perf_counter()
        audit['attempts'].append(attempt)
        try:
            dual, ar, proof = solve_enclosure(matrix, rhs, precision=precision,
                                                cancelled=cancelled, evidence=audit)
            bounds = physical_bounds(matrix, dual, keys, base_keys, signed_tau, conversion, ar)
            for key, value in physical.items():
                ar.check('exact-singleton-moment-refinement')
                if not bounds[key][0] <= value <= bounds[key][1]:
                    raise ArithmeticError('Proved singleton moment conflicts with the certified enclosure')
                bounds[key] = value, value
            rounded = {key: round_bounds(value) for key, value in bounds.items()}
            attempt.update(status='CERTIFIED', seconds=perf_counter()-began)
            proof['exact_singleton_observation_coefficients'] = len(forced)
            return dict(keys=list(bounds), bounds={key: tuple(map(G.mpq, bound))
                                                   for key, bound in bounds.items()},
                        decimal80=rounded, precision_bits=precision, proof=proof,
                        dual_bounds=[tuple(map(G.mpq, bound)) for bound in dual])
        except Unresolved as error:
            attempt.update(status='UNRESOLVED', reason=str(error), seconds=perf_counter()-began)
    raise Unresolved('All declared certification precisions exhausted; exact route/refusal required')

