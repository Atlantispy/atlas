"""Connected owned interval/rank/exact face-functional route, unchanged maths.

Already-owned observations and their original two owner vectors are supplied;
no geometry callback may allocate outside these stages. Literal-zero, exact
rank and full original Gram fallback retain the predecessor's route/order.
Expected incompatibility is a structured owned result for complete-shell
expansion. Completed row/audit storage takes ownership before temporary leases
close. No geometry/support/native/whole-method admission is implied.
"""
import sys

import private_heat_certification_kernel_r1 as K
import private_heat_certification_kernel_r3 as CERT
import private_heat_certification_resources_r1 as I
import private_heat_exact_growth_r1 as E
import private_heat_rank_resources_r1 as RANK
import private_heat_exact_face_kernel_r1 as EXACT
import private_heat_decimal_sparse_core_r1 as P
import private_heat_owned_value_r1 as RETAIN

G = K.G


def functional_bounds(matrix, target, keys, base_keys, signed_tau, conversion, *,
                      gradient, base_observations, budget, cancelled=None,
                      certification_precisions=K.PRECISIONS):
    """Owner.value: status, row (or None), evidence, resource_evidence.

No escaped diagnostic callback is supported: callers inspect the resulting
owned audit. Precision default/order and physical coefficient semantics remain
unchanged. Explicit ladders allow the separately reviewed refinement workflow.
"""
    owner = _build(matrix, target, keys, base_keys, signed_tau, conversion,
        gradient=gradient, base_observations=base_observations, budget=budget,
        cancelled=cancelled, certification_precisions=certification_precisions)
    try:
        return RETAIN.transfer(owner, budget=budget, cancelled=cancelled)
    except BaseException:
        owner.__exit__(*sys.exc_info())
        raise


def _build(matrix, target, keys, base_keys, signed_tau, conversion, *, gradient,
           base_observations, budget, cancelled, certification_precisions):
    K._require_gmp()
    I.check(cancelled)
    metadata, largest = I.metadata_bytes(matrix, target, conversion, signed_tau, G, cancelled)
    m, n = len(matrix), len(target)
    if (len(keys) != m or len(set(keys)) != m or len(base_keys) != 2
            or base_keys[0] == base_keys[1] or len(gradient) != n
            or len(base_observations) != 2 or any(len(v) != n for v in base_observations)):
        raise ValueError('Original matching unique keys, gradient and two owner vectors required')
    for row in (*base_observations, gradient):
        values = row if type(row) in (list, tuple) else (row,)
        for value in values:
            if type(value) not in (int, G.mpq):
                raise TypeError('Already owned GMP/int actions required')
            largest = max(largest, sys.getsizeof(value))
    import private_heat_gmp_resources_r1 as R
    metadata += I.D.CONTAINER_UNIT*(8*m*n+32*m+64*n+256)
    work = R.OwnedWorkspace(budget, metadata, category='heat-functional-route', cancelled=cancelled)
    work.__enter__()
    try:
        I.verify_sources(cancelled)
        arena = E.Arithmetic(work, G, scalar_slots=4*m*n+24*m+32*n+128,
            container_bytes=metadata, initial_bits=8*largest, cancelled=cancelled)
        audit = dict(exact_gram_constructed=False, exact_fallback=False, interval={})
        resources = dict(interval=[], rank=None, exact=None, prospective_accounted_policy=True,
                         allocator_or_rss_bound=False, whole_reconstruction_admission=False)
        certificate = dict(zip(keys, matrix, strict=True))
        for key, vector in zip(base_keys, base_observations, strict=True):
            if key in certificate and list(certificate[key]) != list(vector):
                raise ValueError('Owner observation conflicts with original selected matrix')
        for t, a, b, g in zip(target, *base_observations, gradient, strict=True):
            if arena.rational('add', t, arena.rational('multiply', signed_tau,
                    arena.rational('subtract', a, b))) != g:
                raise ArithmeticError('Exact target plus base jump does not restore the stated gradient')

        def returned(status, row=None):
            return P.OwnedSolve(dict(status=status, row=row, evidence=audit, resource_evidence=resources), work)

        def interval(observations, action, name):
            detail = {}
            resources['interval'].append(detail)
            owner = work.stack.enter_context(CERT.assess_weights(observations, action, keys,
                base_keys, signed_tau, conversion, budget=budget, cancelled=cancelled,
                precisions=certification_precisions, evidence=audit[name], resource_evidence=detail))
            result = owner.value
            if result['status'] != 'CERTIFIED':
                audit[name+'_refusal'] = dict(type='ExactIncompatibility' if result['status'] == 'EXACT_INCOMPATIBLE' else 'Unresolved', reason=result['reason'])
            return result

        def interval_row(result, rank, kind, independent=None):
            proof = {}
            for key, value in result['proof'].items():
                I.check(cancelled)
                if isinstance(value, (G.mpfr, G.mpq)):
                    value = G.mpq(value)  # export was separately funded by CERT
                    shape = R.RationalShape(max(1, value.numerator.bit_length()), value.denominator.bit_length())
                    arena.containers += R.hex_buffers_allowance(shape, ascii_copies=2, utf8_copies=0)
                    arena.reserve(arena.peak_bits)
                    proof[key] = [value.numerator.digits(16), value.denominator.digits(16)]
                else:
                    proof[key] = value
            audit.update(route='interval' if kind == 'algebraic-nonsingular-Gram' else 'interval-reduced',
                rank=rank, interval_proof=proof, precision_bits=result['precision_bits'],
                interval_proof_scalar_encoding='exact signed-hex rational pairs; integer fields unchanged',
                moment_identity_kind=kind)
            if independent is not None:
                audit['independent_columns'] = independent
            return returned('CERTIFIED', dict(ordered_keys=result['keys'], bounds=result['bounds']))

        first = interval(matrix, target, 'interval')
        if first['status'] == 'EXACT_INCOMPATIBLE':
            audit.update(route='exact-incompatible', rank=None, exact_incompatibility='singleton-original-moment-constraint')
            return returned('EXACT_INCOMPATIBLE')
        if first['status'] == 'CERTIFIED':
            return interval_row(first['result'], n, 'algebraic-nonsingular-Gram')
        active = [j for j in range(n) if any(row[j] for row in matrix)]
        missing = [j for j in range(n) if j not in active]
        audit['literal_zero_columns'] = missing
        if any(target[j] for j in missing):
            audit.update(route='exact-incompatible', rank=None, exact_incompatibility='literal-zero-column-nonzero-target')
            return returned('EXACT_INCOMPATIBLE')
        if active and missing:
            audit['zero_column_interval'] = {}
            zero = interval([[row[j] for j in active] for row in matrix], [target[j] for j in active], 'zero_column_interval')
            if zero['status'] == 'CERTIFIED':
                return interval_row(zero['result'], len(active), 'literal-zero-original-columns-and-nonsingular-reduced-Gram', active)
            if zero['status'] == 'EXACT_INCOMPATIBLE':
                raise ArithmeticError('Literal-zero compatible restriction became exactly incompatible')
        audit['rank_reduction'], resources['rank'] = {}, {}
        reduced_owner = work.stack.enter_context(RANK.reduce_observations(matrix, target,
            budget=budget, cancelled=cancelled, evidence=audit['rank_reduction'], resource_evidence=resources['rank']))
        reduced = reduced_owner.value
        if not reduced['compatible']:
            audit.update(route='exact-incompatible', rank=reduced['rank'], exact_incompatibility='original-rectangular-null-witness')
            return returned('EXACT_INCOMPATIBLE')
        if reduced['rank'] == 0:
            scaled = {key: arena.q(0) for key in keys}
            scaled[base_keys[0]] = arena.rational('add', scaled.get(base_keys[0], arena.q(0)), signed_tau)
            scaled[base_keys[1]] = arena.rational('subtract', scaled.get(base_keys[1], arena.q(0)), signed_tau)
            factors = dict(zip(keys, conversion, strict=True))
            factors.update({key: factors.get(key, arena.q(1)) for key in base_keys})
            physical = {key: arena.rational('multiply', value, factors[key]) for key, value in scaled.items()}
            audit.update(route='exact-reduced-zero', rank=0, exact_moment_checks=n,
                         moment_identity_kind='exact-zero-correction-plus-verified-base-jump')
            return returned('CERTIFIED', dict(ordered_keys=list(physical), bounds={key: (v, v) for key, v in physical.items()}))
        if reduced['rank'] < n:
            audit['reduced_interval'] = {}
            smaller = interval(reduced['matrix'], reduced['target'], 'reduced_interval')
            if smaller['status'] == 'CERTIFIED':
                return interval_row(smaller['result'], reduced['rank'], 'exact-original-column-certificate-and-nonsingular-reduced-Gram')
            if smaller['status'] == 'EXACT_INCOMPATIBLE':
                raise ArithmeticError('Exact compatible rank reduction became incompatible')
        resources['exact'] = {}
        exact_owner = work.stack.enter_context(EXACT.exact_face(matrix, target, keys, base_keys,
            signed_tau, conversion, gradient=gradient, base_observations=base_observations,
            budget=budget, cancelled=cancelled, evidence=audit, resource_evidence=resources['exact']))
        return returned('CERTIFIED', exact_owner.value)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise
