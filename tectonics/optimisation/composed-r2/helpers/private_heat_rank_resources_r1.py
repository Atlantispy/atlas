"""Owned exact rank reduction with separately admitted reference fallback.

Same modular lower-bound minor, canonical column order, exact integer
certificates and normalised incompatibility witnesses as CERT r1. Every
variable-width GMP expression is admitted from actual operands. Fixed 61-bit
modular Python arithmetic is covered by the explicit scalar/container workset.
A fallback enters another owner BEFORE its arrays exist while outer modular
and primitive arrays remain funded. No geometry/support/whole-method claim.
"""
from concurrent.futures import CancelledError
import sys
from time import perf_counter

import private_heat_certification_kernel_r1 as K
import private_heat_certification_resources_r1 as INVENTORY
import private_heat_exact_growth_r1 as GROWTH
import private_heat_decimal_sparse_core_r1 as P

G, PRIME = K.G, K.PRIME


class _Arithmetic(GROWTH.Arithmetic):
    def iadd(self, a, b):
        self.reserve(max(self._integer(a), self._integer(b))+1)
        self.operations += 1
        return a+b

    def ratio(self, numerator, denominator):
        self.reserve(max(self._integer(numerator), self._integer(denominator)))
        self.operations += 1
        return self.G.mpq(numerator, denominator)


def _admit(matrix, target, *, budget, cancelled, evidence, resource_evidence,
           reference=False, verified=False):
    K._require_gmp()
    INVENTORY.check(cancelled)
    if (type(matrix) not in (list, tuple) or not matrix or type(target) not in (list, tuple)
            or not target or any(type(row) not in (list, tuple) or len(row) != len(target) for row in matrix)):
        raise ValueError('Nonempty rectangular observations and matching target required')
    m, n, largest = len(matrix), len(target), 1
    for row in matrix:
        for value in row:
            INVENTORY.check(cancelled)
            if type(value) not in (int, G.mpq):
                raise TypeError('Already owned int/GMP observation values required')
            largest = max(largest, sys.getsizeof(value))
    for value in target:
        if type(value) not in (int, G.mpq):
            raise TypeError('Already owned int/GMP target values required')
        largest = max(largest, sys.getsizeof(value))
    import private_heat_gmp_resources_r1 as R
    metadata = 262144+INVENTORY.D.CONTAINER_UNIT*(12*m*n+16*n*n+32*m+64*n+256)
    work = R.OwnedWorkspace(budget, metadata,
        category='heat-rank-reference-growth' if reference else 'heat-rank-modular-growth', cancelled=cancelled)
    work.__enter__()
    try:
        if not verified:
            INVENTORY.verify_sources(cancelled)
        arena = _Arithmetic(work, G, scalar_slots=6*m*n+5*n*n+24*m+48*n+128,
            container_bytes=metadata, initial_bits=max(128, 8*largest), cancelled=cancelled)
        arena.children = []
        result = (_reference(matrix, target, arena=arena, cancelled=cancelled, evidence=evidence)
                  if reference else _run(matrix, target, arena=arena, budget=budget,
                                        cancelled=cancelled, evidence=evidence))
        if resource_evidence is not None:
            resource_evidence.update(admitted_bytes=work.lease.count,
                arithmetic_operations=arena.operations, largest_prospective_scalar_bits=arena.peak_bits,
                reference_fallback_stages=arena.children, prospective_accounted_policy=True,
                allocator_or_rss_bound=False, support_or_basis_creation_admitted=False,
                whole_method_admission=False)
        return P.OwnedSolve(result, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


def reduce_observations(matrix, target, *, budget, cancelled=None, evidence=None, resource_evidence=None):
    """Return owner of the exact unchanged reduction/witness dictionary."""
    return _admit(matrix, target, budget=budget, cancelled=cancelled,
                  evidence=evidence, resource_evidence=resource_evidence)


def _reference(matrix, target, *, arena, cancelled=None, evidence=None):
    """Return exact reduced matrix/target or a verified incompatibility witness.

    Compatible output includes `independent_columns`, `matrix`, `target` and
    `column_coordinates` (C, shaped rank x original-column-count). Rank zero
    has empty reduced rows/target; callers must use the exact zero correction,
    not call a nonsingular interval solver. Evidence contains JSON-safe counts.
    Original observation row order is preserved in the reduced matrix.
    """
    K._require_gmp()
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
        right = [arena.q(value) for value in target]
        for i, row in enumerate(matrix):
            check('denominator-row', i)
            values, denominator = [], G.mpz(1)
            for j, value in enumerate(row):
                check('denominator-element', i, j)
                value = arena.q(value)
                values.append(value)
                denominator = arena.lcm(denominator, value.denominator)
            original.append(values)
            audit['row_lcm_max_bits'] = max(audit['row_lcm_max_bits'], bits(denominator))
            integers, content = [], G.mpz(0)
            for j, value in enumerate(values):
                check('integer-element', i, j)
                integer = arena.imul(value.numerator, arena.idiv(denominator, value.denominator))
                integers.append(integer)
                content = arena.gcd(content, integer)
            if content > 1:
                for j, value in enumerate(integers):
                    check('primitive-element', i, j)
                    integers[j] = arena.idiv(value, content)
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
                    numerator = arena.isub(arena.imul(pivot, rows[i][j]), arena.imul(coefficient, rows[rank][j]))
                    audit['peak_integer_bits'] = max(audit['peak_integer_bits'], bits(numerator))
                    if previous != 1:
                        quotient, remainder = arena.divmod(numerator, previous)
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
                target_denominator = arena.lcm(target_denominator, value.denominator)
            audit['target_scale_bits'] = bits(target_denominator)
            for j, value in enumerate(right):
                check('target-integer', column=j)
                target_integer.append(arena.imul(value.numerator, arena.idiv(target_denominator, value.denominator)))
        for column in range(n):
            if column in independent:
                continue
            check('dependency-back-substitution', column=column)
            weights = [G.mpq(0)]*rank
            for i in range(rank-1, -1, -1):
                check('dependency-row', i, column)
                value = arena.q(rows[i][column])
                for j in range(i+1, rank):
                    check('dependency-element', i, column)
                    value = arena.rational('subtract', value, arena.rational('multiply', rows[i][pivots[j]], weights[j]))
                weights[i] = arena.rational('divide', value, rows[i][pivots[i]])
            coefficient_denominator = G.mpz(1)
            for j, value in enumerate(weights):
                check('coefficient-denominator', j, column)
                coefficient_denominator = arena.lcm(coefficient_denominator, value.denominator)
            integer_weights = []
            for j, value in enumerate(weights):
                check('coefficient-integer', j, column)
                integer_weights.append(arena.imul(value.numerator, arena.idiv(coefficient_denominator, value.denominator)))
            audit['certificate_scale_max_bits'] = max(audit['certificate_scale_max_bits'],
                                                       bits(coefficient_denominator))
            for i, row in enumerate(original_primitive):
                check('original-integer-column-certificate', i, column)
                value = G.mpz(0)
                for j, pivot in enumerate(pivots):
                    check('original-integer-column-element', i, column)
                    value = arena.iadd(value, arena.imul(row[pivot], integer_weights[j]))
                    audit['certificate_integer_products'] += 1
                if value != arena.imul(row[column], coefficient_denominator):
                    raise ArithmeticError('Column dependency failed original exact integer observations')
            audit['verified_dependent_columns'] += 1
            residual_integer = arena.imul(target_integer[column], coefficient_denominator)
            for j, pivot in enumerate(pivots):
                check('target-integer-certificate', j, column)
                residual_integer = arena.isub(residual_integer, arena.imul(target_integer[pivot], integer_weights[j]))
                audit['certificate_integer_products'] += 1
            residual = arena.ratio(residual_integer, arena.imul(target_denominator, coefficient_denominator))
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


def _run(matrix, target, *, arena, budget, cancelled=None, evidence=None):
    K._require_gmp()
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
        quotient, remainder = arena.divmod(numerator, denominator)
        audit['exact_divisions'] += 1
        if remainder:
            raise ArithmeticError('Selected-minor integer division not exact')
        return quotient

    def fallback(reason):
        audit.update(fallback_used=True, fallback_reason=reason)
        details = {}
        child_resources = {}
        child = arena.workspace.stack.enter_context(_admit(matrix, target, budget=budget,
            cancelled=cancelled, evidence=details, resource_evidence=child_resources,
            reference=True, verified=True))
        arena.children.append(child_resources)
        result = child.value
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
        right = list(map(arena.q, target))
        for i, row in enumerate(matrix):
            check('denominator-row', i)
            values, denominator = list(map(arena.q, row)), G.mpz(1)
            for j, value in enumerate(values):
                check('denominator-element', i, j)
                denominator = arena.lcm(denominator, value.denominator)
            integers, content = [], G.mpz(0)
            for j, value in enumerate(values):
                check('primitive-element', i, j)
                integer = arena.imul(value.numerator, arena.idiv(denominator, value.denominator))
                integers.append(integer)
                content = arena.gcd(content, integer)
            if content > 1:
                integers = [arena.idiv(value, content) for value in integers]
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
                        value = arena.isub(arena.imul(pivot, rows[i][j]), arena.imul(coefficient, rows[k][j]))
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
                target_denominator = arena.lcm(target_denominator, value.denominator)
            target_integer = [arena.imul(value.numerator, arena.idiv(target_denominator, value.denominator)) for value in right]
            residuals = []
            for dependent_index, column in enumerate(dependent):
                numerators = [G.mpz(0)]*rank
                for i in range(rank-1, -1, -1):
                    check('integer-backsub-row', i, column)
                    value = arena.imul(determinant, rows[i][rank+dependent_index])
                    for j in range(i+1, rank):
                        check('integer-backsub-element', i, column)
                        value = arena.isub(value, arena.imul(rows[i][j], numerators[j]))
                    numerators[i] = exact_divide(value, rows[i][i])
                # Remove a common factor once, not a rational gcd at every sum.
                common = determinant
                for i, value in enumerate(numerators):
                    check('dependency-content', i, column)
                    common = arena.gcd(common, value)
                denominator = arena.idiv(determinant, common)
                numerators = [arena.idiv(value, common) for value in numerators]
                for i, row in enumerate(primitive):
                    value = G.mpz(0)
                    for j, pivot in enumerate(pivots):
                        check('original-integer-column-element', i, column)
                        value = arena.iadd(value, arena.imul(row[pivot], numerators[j]))
                        audit['certificate_integer_products'] += 1
                    if value != arena.imul(row[column], denominator):
                        return fallback('modular lower rank failed all-original-row column certificate')
                if any(value and pivot > column for value, pivot in zip(numerators, pivots, strict=True)):
                    return fallback('unlucky prime changed canonical independent-column order')
                residual_integer = arena.imul(target_integer[column], denominator)
                for j, pivot in enumerate(pivots):
                    check('target-integer-certificate', j, column)
                    residual_integer = arena.isub(residual_integer, arena.imul(target_integer[pivot], numerators[j]))
                weights = [arena.ratio(value, denominator) for value in numerators]
                residual = arena.ratio(residual_integer, arena.imul(target_denominator, denominator))
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

