"""Connected owned exact physical-face fallback from already-owned observations.

The caller has selected the unchanged complete shell, exact basis/frame and
target, and owns that matrix plus the two exact base observation vectors. This
stage builds the original full Gram, calls the owned free-zero Bareiss solve,
forms physical weights in original order and checks every original polynomial
moment. It corresponds to FUNCTIONALS r1's exact-fallback branch; it does NOT
select a different route, rank policy, stencil or precision ladder.

Base vectors are supplied exact data, not arbitrary allocation callbacks.
Admission includes all generated Gram/scaled/physical scalar generations and
the copied certificate map, plus a separate nested exact-solve owner. All owners
remain live with the output. No native/RSS, whole-reconstruction, geometry,
support, observation creation or prior rectangular-rank admission is claimed.
"""
from hashlib import sha256
from pathlib import Path
import sys

import private_heat_certification_kernel_r1 as K
import private_heat_certification_resources_r1 as INVENTORY
import private_heat_exact_growth_r1 as GROWTH
import private_heat_exact_functional_kernel_r2 as SOLVE
import private_heat_decimal_sparse_core_r1 as P

G = K.G
FUNCTIONALS_SHA = 'a48f115e8018b9c2d831ce1442cba1060a22d0a5fdbc39b6c8165674a0b0ab56'


def exact_face(matrix, target, keys, base_keys, signed_tau, conversion, *,
               gradient, base_observations, budget, cancelled=None, evidence=None,
               resource_evidence=None):
    """Return owner of {'ordered_keys', 'bounds'}; all bounds are singletons.

    Use ONLY where the existing route has selected exact fallback. A returned
    row is not a complete polygon reconstruction or a global assembly promise.
    If base keys already occur in keys, exact vectors must match those rows.
    """
    K._require_gmp()
    INVENTORY.check(cancelled)
    if (type(matrix) not in (list, tuple) or not matrix or type(target) not in (list, tuple)
            or not target or any(type(row) not in (list, tuple) or len(row) != len(target) for row in matrix)):
        raise ValueError('Owned nonempty rectangular observations and target required')
    m, n = len(matrix), len(target)
    if (type(keys) not in (list, tuple) or len(keys) != m or type(base_keys) not in (list, tuple)
            or len(base_keys) != 2 or base_keys[0] == base_keys[1]
            or type(base_observations) not in (list, tuple) or len(base_observations) != 2
            or any(type(row) not in (list, tuple) or len(row) != n for row in base_observations)
            or type(gradient) not in (list, tuple) or len(gradient) != n
            or type(conversion) not in (list, tuple) or len(conversion) != m):
        raise ValueError('Matching keys, two base vectors, gradient and conversions required')
    largest = 1
    for rows in (matrix, base_observations, (target, gradient, conversion, (signed_tau,))):
        for row in rows:
            for value in row:
                INVENTORY.check(cancelled)
                if type(value) not in (int, G.mpq):
                    raise TypeError('Already owned int/GMP exact values required')
                largest = max(largest, sys.getsizeof(value))
    import private_heat_gmp_resources_r1 as R
    metadata = 262144+INVENTORY.D.CONTAINER_UNIT*(8*m*n+12*n*n+40*m+64*n+256)
    work = R.OwnedWorkspace(budget, metadata, category='heat-exact-face-fallback', cancelled=cancelled)
    work.__enter__()
    try:
        INVENTORY.verify_sources(cancelled)
        path = Path(__file__).resolve().parent/'private_heat_functionals_kernel_r1.py'
        if sha256(path.read_bytes()).hexdigest() != FUNCTIONALS_SHA:
            raise ValueError('Reviewed exact physical-face branch changed')
        arena = GROWTH.Arithmetic(work, G, scalar_slots=3*m*n+3*n*n+16*m+24*n+128,
            container_bytes=metadata, initial_bits=8*largest, cancelled=cancelled)
        if len(set(keys)) != m:
            raise ValueError('Unique exact observation keys required')
        certificate = dict(zip(keys, matrix, strict=True))
        for key, row in zip(base_keys, base_observations, strict=True):
            if key[0] not in ('cell', 'wall'):
                raise ValueError('Base jump must use declared temperature observations')
            if key in certificate and list(certificate[key]) != list(row):
                raise ValueError('Base observation disagrees with selected original row')
            certificate[key] = row
        left, right = base_observations
        for t, a, b, g in zip(target, left, right, gradient, strict=True):
            value = arena.rational('add', t,
                arena.rational('multiply', signed_tau, arena.rational('subtract', a, b)))
            if value != g:
                raise ArithmeticError('Exact target plus base jump does not restore the stated gradient')
        audit = {} if evidence is None else evidence
        audit.update(exact_gram_constructed=True, exact_fallback=True, exact={})
        gram = []
        for a in range(n):
            INVENTORY.check(cancelled)
            row = []
            for b in range(n):
                total = arena.q(0)
                for observation in matrix:
                    total = arena.rational('add', total,
                        arena.rational('multiply', observation[a], observation[b]))
                row.append(total)
            gram.append(row)
        solve_resources = {}
        solved = work.stack.enter_context(SOLVE.functional_solve(gram, target, budget=budget,
            cancelled=cancelled, evidence=audit['exact'], resource_evidence=solve_resources))
        dual = solved.value
        scaled = {}
        for key, values in zip(keys, matrix, strict=True):
            total = arena.q(0)
            for a, b in zip(values, dual, strict=True):
                total = arena.rational('add', total, arena.rational('multiply', a, b))
            scaled[key] = total
        scaled[base_keys[0]] = arena.rational('add', scaled.get(base_keys[0], G.mpq(0)), signed_tau)
        scaled[base_keys[1]] = arena.rational('subtract', scaled.get(base_keys[1], G.mpq(0)), signed_tau)
        for j in range(n):
            total = arena.q(0)
            for key, value in scaled.items():
                total = arena.rational('add', total,
                    arena.rational('multiply', value, certificate[key][j]))
            if total != gradient[j]:
                raise ArithmeticError('Exact fallback polynomial moment identity failed')
        factors = dict(zip(keys, conversion, strict=True))
        factors.update({key: factors.get(key, G.mpq(1)) for key in base_keys})
        physical = {key: arena.rational('multiply', value, factors[key]) for key, value in scaled.items()}
        audit.update(route='exact-fallback', rank=audit['exact']['rank'],
            moment_identity_kind='materialised-exact-rational-checks', exact_moment_checks=n)
        if resource_evidence is not None:
            resource_evidence.update(outer_admitted_bytes=work.lease.count, exact_solve=solve_resources,
                arithmetic_operations=arena.operations, largest_prospective_scalar_bits=arena.peak_bits,
                gram_and_physical_moment_checks_admitted=True, rectangular_rank_admitted=False,
                support_and_observation_creation_admitted=False, prospective_accounted_policy=True,
                allocator_or_rss_bound=False, whole_method_admission=False)
        INVENTORY.check(cancelled)
        return P.OwnedSolve(dict(ordered_keys=list(physical),
            bounds={key: (value, value) for key, value in physical.items()}), work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise
