"""Fixed closed quadratic guard with actual-factor and current-state ownership.

The predicate and precision/fallback policy are the frozen arithmetic helper's.
Only lifetime accounting changes. No source/reservoir entropy rule is added.
Native scratch for the caller, directed attempts and exact fallback is a
maximum over sequential calls, not a sum. All simultaneously retained factors,
endpoint proofs, scalar slots, containers and history stay additive.

R5 is R4 with exact endpoint reuse in the guard. The theta 0 and theta 1
certificates are computed in full first; the scalar search and the result
certificate reuse them for an equal exact theta instead of recomputing them.
A reused certificate is accepted only for the exact theta it was computed at
and only when the state it certified equals the result's freshly computed
state, value by value; otherwise the guard refuses. Values, the selection
history and all three returned certificates are unchanged.
"""
from concurrent.futures import CancelledError
from hashlib import sha256
from pathlib import Path
import sys

import private_heat_correction_owned_r1 as C
import private_heat_finish_arithmetic_r1 as A
import private_heat_finish_entry_owned_r2 as E

_SOURCES = dict(E._SOURCES)
_SOURCES[str(Path(__file__).resolve())] = sha256(Path(__file__).read_bytes()).hexdigest()


def _proof_numbers(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _proof_numbers(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _proof_numbers(item)
    elif type(value) is A.exact_library().mpq:
        yield value


def _quadratic_workspace(resources, peak_bits, endpoint_n, endpoint_d, precision):
    """Max of sequential native work, with no credit for live object storage.

    Factor construction has returned from every fixed operation before A runs.
    A reconstructs the same factors, executes directed attempts, then optional
    exact fallback: these native operations never overlap. Its MPFR contexts,
    factors and earlier proof endpoints can overlap, so their separate slots
    and factor-copy allowances MUST NOT be removed by this calculation.
    """
    existing = resources.native_workspace_allowance(8*peak_bits, 64)
    directed = resources.native_workspace_allowance(
        max(8*peak_bits, endpoint_n+endpoint_d+precision), 64)
    fallback = resources.native_workspace_allowance(8*65536, 12)
    maximum = max(existing, directed, fallback)
    return dict(existing=existing, directed=directed, fallback=fallback,
                maximum=maximum, additional=maximum-existing)


def _quadratic(ar, old, new, cap):
    """Fund unchanged A call from ACTUAL factors, not recursive virtual widths.

    For nonzero q with N/D part bits, 2**(N-D-1)<=abs(q)<2**(N-D+1).
    A directed p-bit point is bounded by exponent N-D+2 and dyadic quantum
    N-D-p-2. Multiplication adds quantum/exponent bounds; each rounded product
    adds one upper-exponent bit. Addition retains the smaller quantum and
    increases the upper exponent by one. Thus endpoint export depends on the
    actual ratio exponents, not the enormous common denominator of q.
    """
    mark = len(ar.arrays)
    factors = ar.array(len(old))
    maximum_exp, minimum_quantum, total_exp = None, None, None
    precision = 2560
    for i, (a, b, c) in enumerate(zip(old, new, cap, strict=True)):
        triple = (ar.op('subtract', b, a), ar.op('add', b, a),
                  ar.op('divide', ar.G.mpq(1), ar.op('multiply', ar.G.mpq(2), c)))
        ar.put(factors, i, triple)
        upper, quantum, zero = 0, 0, False
        for q in triple:
            s = ar.shape(q)
            zero = zero or not q
            exponent = s.numerator_bits-s.denominator_bits
            upper += exponent+2
            quantum += exponent-precision-2
        if zero:
            continue
        upper += 2  # the two rounded interval products
        maximum_exp = upper if maximum_exp is None else max(maximum_exp, upper)
        minimum_quantum = quantum if minimum_quantum is None else min(minimum_quantum, quantum)
        total_exp = upper+1 if total_exp is None else max(total_exp, upper)+1
    if total_exp is None:
        endpoint_n, endpoint_d = 1, 1
    else:
        endpoint_d = max(1, 1-minimum_quantum)
        endpoint_n = max(1, total_exp+endpoint_d+1)
    endpoint = ar.R.RationalShape(endpoint_n, endpoint_d)
    endpoint_slot = ar.R.native_slot_allowance(endpoint)
    factor_bytes = sum(ar.arrays[factors[0]][1])
    # A creates its own factors, four attempts and endpoint proofs. Fund copies
    # plus current MPFR/context/conversion work and the exact 65536-bit fallback
    # before entering it. Original operation workspace already protects actual
    # factor construction. All constants are the reviewed native policy.
    scratch = _quadratic_workspace(ar.R, ar.peak_bits, endpoint_n, endpoint_d, precision)
    extra = (2*factor_bytes + 48*endpoint_slot + 1024*(128+8*len(old))
             + scratch['additional']
             + 32*ar.R.native_slot_allowance(ar.R.RationalShape(65536, 65536)))
    ar.containers += extra
    ar.reserve(ar.peak_bits)
    result = A.quadratic_nonincrease(old, new, cap, cancelled=ar.check)
    # Only this successful return establishes that A's producer frame and
    # native work are gone. Retain the full maximum envelope until proofs have
    # been inspected and copied; getter scratch is admitted separately by E.
    # An escaping A frame never reaches the release credit below.
    # Result GMP endpoints are no larger than the prospective export slots.
    # Copy references into a charged array BEFORE releasing transient funding.
    proof = list(_proof_numbers(result))
    for q in proof:
        s = ar.shape(q)
        if max(s.numerator_bits, s.denominator_bits) > max(endpoint_n, endpoint_d, 65536):
            raise ArithmeticError('Quadratic endpoint inventory certificate failed')
    del factors, triple
    # Factor array belongs only to the completed A call; returned proof does
    # not borrow it. Keep result references in scalar/proof allowance here.
    ar.drop_to(mark)
    ar.copy(proof)
    ar.containers -= extra
    ar.reserve(ar.peak_bits)
    return result


def _residual(ar, energy, faces, load):
    values = ar.array(len(energy))
    for i, (a, b) in enumerate(zip(energy, load, strict=True)):
        ar.put(values, i, ar.op('subtract', a, b))
    for i, j, q in faces:
        ar.put(values, i, ar.op('add', values[1][i], q))
        if j is not None:
            ar.put(values, j, ar.op('subtract', values[1][j], q))
    return values[1]


def _equal_arrays(ar, first, second):
    return all(ar.equal(a, b) for a, b in zip(first, second, strict=True))


def _reused_certificate(ar, theta, reused, energies, faces):
    """Return a copy of an endpoint certificate only for its own exact state.

    A certificate is a deterministic function of the guard's owned inputs and
    the exact theta. It is reused only for the theta it was computed at, and
    only when the energies and face transfers it certified equal the freshly
    computed result state exactly; anything else is stale and refused. The
    shallow copy keeps the endpoint certificate unchanged when the result
    certificate gains its stock-conservation entry.
    """
    tested, tested_energies, tested_faces, certificate = reused
    if type(tested) is not type(theta) or tested != theta:
        raise ArithmeticError('Stale closed-guard certificate: computed at another theta')
    if len(tested_energies) != len(energies) or len(tested_faces) != len(faces):
        raise ArithmeticError('Stale closed-guard certificate: certified state has another shape')
    if not _equal_arrays(ar, tested_energies, energies):
        raise ArithmeticError('Stale closed-guard certificate: certified energies differ')
    return dict(certificate)
    for before, after in zip(tested_faces, faces, strict=True):
        ar.check()
        if before[:2] != after[:2] or not ar.equal(before[2], after[2]):
            raise ArithmeticError('Stale closed-guard certificate: certified face transfers differ')
    return dict(certificate)


def _guard(ar, old, cap, low, candidate, low_faces, candidate_faces, bounds):
    G = ar.G
    for lo, hi in zip(low_faces, candidate_faces, strict=True):
        ar.check()
        if lo[:2] != hi[:2]:
            raise ValueError('Physical face owner/order mismatch')
        if lo[1] is None and (lo[2] or hi[2]):
            raise ValueError('Closed guard requires zero exterior transfers')
    residual = _residual(ar, low, low_faces, old)
    if not _equal_arrays(ar, _residual(ar, candidate, candidate_faces, old), residual):
        raise ValueError('The supplied high/FCT endpoint must preserve the low physical-face ledger residual')
    difference, dq = ar.array(len(low)), ar.array(len(low_faces))
    for i, (e, f) in enumerate(zip(low, candidate, strict=True)):
        ar.put(difference, i, ar.op('subtract', f, e))
    for f, (lo, hi) in enumerate(zip(low_faces, candidate_faces, strict=True)):
        ar.put(dq, f, ar.op('subtract', hi[2], lo[2]))
    old_stock, cap_float = [ar.public(e) for e in old], [ar.public(c) for c in cap]
    old_temperature = [e/c for e, c in zip(old_stock, cap_float, strict=True)]
    old_public = ar.copy([G.mpq(e) for e in old_stock])[1]
    old_t = ar.array(len(cap))
    for i, (c, t) in enumerate(zip(cap, old_temperature, strict=True)):
        ar.put(old_t, i, ar.op('multiply', c, G.mpq(t)))

    def state(theta):
        energies, faces = ar.array(len(low)), ar.array(len(low_faces))
        for i, (e, d) in enumerate(zip(low, difference[1], strict=True)):
            ar.put(energies, i, ar.op('add', e, ar.op('multiply', theta, d)))
        for f, (lo, change) in enumerate(zip(low_faces, dq[1], strict=True)):
            ar.put(faces, f, (lo[0], lo[1], ar.op('add', lo[2], ar.op('multiply', theta, change))))
        stocks = [ar.public(e) for e in energies[1]]
        temperatures = [e/c for e, c in zip(stocks, cap_float, strict=True)]
        return energies[1], faces[1], stocks, temperatures

    def certificate(theta, states=None):
        energies, faces, stocks, temperatures = state(theta)
        if states is not None:
            states[theta] = (theta, energies, faces)
        exact_sign = _quadratic(ar, old, energies, cap)
        public_energy = ar.copy([G.mpq(e) for e in stocks])[1]
        public_sign = _quadratic(ar, old_public, public_energy, cap)
        t_energy = ar.array(len(cap))
        for i, (c, t) in enumerate(zip(cap, temperatures, strict=True)):
            ar.put(t_energy, i, ar.op('multiply', c, G.mpq(t)))
        public_t_sign = _quadratic(ar, old_t[1], t_energy[1], cap)
        bound_check = ar.bounds(energies, cap, bounds)
        flags = dict(exact_supply=exact_sign['nonincrease'], public_stock_supply=public_sign['nonincrease'],
            public_temperature_supply=public_t_sign['nonincrease'], exact_bounds=bound_check['exact_pass'],
            public_bounds=bound_check['actual_public_pass'])
        return dict(schema='atlas.closed-quadratic-sign-certificate.r2', passed=all(flags.values()), flags=flags,
            exact_h_change_certificate=exact_sign, public_stock_h_change_certificate=public_sign,
            public_temperature_h_change_certificate=public_t_sign, exact_source_work=G.mpq(0),
            public_source_work=G.mpq(0), reservoir_work=G.mpq(0),
            quadratic_expansion_equivalence='algebraic: direct exact energy difference equals the unmaterialised a*theta^2+b*theta+c',
            exact_change_values_available_only_within_materialised_fallback_certificates=True)

    states, zero, one = {}, G.mpq(0), G.mpq(1)
    low_check, full_check = certificate(zero, states), certificate(one, states)
    issued = {zero: (*states[zero], low_check), one: (*states[one], full_check)}
    del states
    # Each bool is the passed flag of a certificate computed directly at that
    # exact theta, so only a directly tested state replaces the lower endpoint.
    known = {zero: low_check['passed'], one: full_check['passed']}
    def admissible(theta):
        if theta in known:
            return known[theta]
        mark = len(ar.arrays)
        cert = certificate(theta)
        passed = cert['passed']
        del cert
        ar.drop_to(mark)
        known[theta] = passed
        return passed
    try:
        theta, selection = A.feasible_scalar(admissible)
    except ValueError as error:
        raise A.SupplyGuardRefused(str(error), dict(low=low_check, full=full_check,
            quadratic_evidence='sign enclosures; global exact a,b,c not materialised',
            physical_ledger_residual=residual)) from error
    reused = issued.get(theta)
    checked = certificate(theta) if reused is None else None
    energies, faces, _, _ = state(theta)
    if reused is not None:
        checked = _reused_certificate(ar, theta, reused, energies, faces)
    del issued, reused
    if not checked['passed'] or not _equal_arrays(ar, _residual(ar, energies, faces, old), residual):
        raise ArithmeticError('Closed guard changed the exact low ledger or failed its certificate')
    checked['stock_conservation_certificate'] = dict(schema='atlas.closed-paired-ledger-identity.r1',
        exact_cell_ledger_unchanged=True, face_owner_order_unchanged=True,
        one_shared_opposite_transfer_per_interior_face=True, exterior_transfers_exactly_zero=True,
        identity='sum_i(dE_i) = -sum_f(exterior dq_f) = 0; interior dq cancels by incidence',
        exact_total_stock_change=G.mpq(0), route='EXACT_PER_CELL_LEDGER_AND_SHARED_FACE_IDENTITY',
        global_corrected_stock_sum_materialised=False)
    return dict(exact_energy=energies, physical_faces=faces, theta=theta, certificate=checked,
        selection=selection, low_endpoint_certificate=low_check, full_endpoint_certificate=full_check)


def closed_guard(old, capacity, low, candidate, low_faces, candidate_faces, bounds, *, budget, cancelled=None):
    def check():
        if cancelled is not None and cancelled():
            raise CancelledError('Fixed closed quadratic guard cancelled')
        return False
    G = A.exact_library()
    import private_heat_gmp_resources_r1 as R
    if not old or any(len(a) != len(old) for a in (capacity, low, candidate)):
        raise ValueError('Matching original cell arrays required')
    for values in (old, capacity, low, candidate, bounds, (q for _, _, q in low_faces), (q for _, _, q in candidate_faces)):
        for q in values:
            check()
            if type(q) is not G.mpq:
                raise TypeError('Exact owned GMP input arrays required')
    work = R.OwnedWorkspace(budget, 65536, category='heat-closed-quadratic-incremental', cancelled=check)
    work.__enter__()
    owner = C._OwnerWorkspace(work)
    try:
        ar = E.Arithmetic(work, G, R, len(old), len(low_faces), 1, check)
        owner.arithmetic = ar
        for path, pin in _SOURCES.items():
            if sha256(Path(path).read_bytes()).hexdigest() != pin:
                raise ValueError('Closed guard source changed')
        result = _guard(ar, old, capacity, low, candidate, low_faces, candidate_faces, bounds)
        ar.settle(result)
        return C.CorrectionOwner(result, owner)
    except BaseException:
        owner.__exit__(*sys.exc_info())
        raise
