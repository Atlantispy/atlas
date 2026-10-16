"""Standalone staged conservative post-predictor kernel; NOT native admission.

The numerical body is extracted from private_heat_conservative_finish_r2 with
its decisions/targets/order intact. Dependencies are the standard library and
the adjacent standalone arithmetic module, which loads the already-selected
native exact library ONLY at invocation. No probe, solver, test or geometry
module is imported. Sources and the immutable numerical result are sealed;
no native plan/state/geometry/runtime origin is inferred from saved predictors.

The new public finish operation prospectively reserves stage-local derived
inventories and retains metadata/work owners with its sealed result and info.
The underlying arithmetic, predicates, 64-step selection and _issue writer
are unchanged. Counts/limb/container/codec policies are NOT allocator/RSS or
native origin guarantees. Debug record() views are new caller allocations.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter
import sys

import private_heat_finish_inventory_r1 as INVENTORY
import private_heat_decimal_sparse_core_r1 as OWNERS

import private_heat_finish_arithmetic_r1 as A

METHOD = 'private:standalone-conservative-physical-face-finish-r2'
SCHEMA = 'atlas.private.standalone-corrected-integrated-heat-result.r1'
TRACE_STATUS = 'UNAVAILABLE_NO_ENDPOINT_TRACE_RECONSTRUCTION'
INVENTORY_OBLIGATIONS = (
    'already-live low/high inputs, exact raw owner energies, source and boundary arrays',
    'pair projection, full candidate, signwise budgets, exact/public bound generations',
    'closed-only exact differences, MPFR contexts/enclosures and bounded exact fallback',
    'up to 66 scalar history entries and simultaneous endpoint/final certificates',
    'exact/public cell residuals, projection differences and exact exterior/global sums',
    'decimal integer components, encoder chunks, bytearray capacity and immutable copies',
    'caller input lifetimes, retained result bytes, exceptions/tracebacks and GMP caches/scratch',
)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


_LOADED = _sha(__file__)
_SOURCES = dict(A._SOURCES, **{str(Path(__file__).resolve()): _LOADED,
    str(Path(INVENTORY.__file__).resolve()): _sha(INVENTORY.__file__)})
_SOURCES.update(INVENTORY._SOURCES)
for _name in INVENTORY.PINS:
    _path = str((Path(__file__).resolve().parent/_name).resolve())
    _SOURCES[_path] = _sha(_path)
_CORE_SOURCES = dict(_SOURCES)
_q = A.rational


class EndpointTraceUnavailable(RuntimeError):
    pass


def _encode_rational(value):
    G = A.exact_library()
    return [G.mpz(value.numerator).digits(10), G.mpz(value.denominator).digits(10)]


def encoded(value):
    return _encoded(value, lambda: None)


@dataclass(frozen=True, slots=True)
class PrivateNumericalResult:
    """Sealed numerical ledger only. Constructor/record cannot create origins."""
    _sealed: bytes

    def __post_init__(self):
        if type(self._sealed) is not bytes:
            raise TypeError('Immutable sealed bytes required for a private numerical result')

    def record(self):
        record = json.loads(self._sealed)
        result_id = record.pop('result_id')
        if hashlib.sha256(encoded(record)).hexdigest() != result_id:
            raise ValueError('Private corrected result identity changed')
        if any(_sha(path) != digest for path, digest in record['sources'].items()):
            raise ValueError('Private corrected result source binding changed')
        record['result_id'] = result_id
        return record

    @property
    def result_id(self):
        return self.record()['result_id']

    def endpoint_face_temperature(self):
        self.record()
        raise EndpointTraceUnavailable('This result carries integrated face energies, not endpoint face temperatures; trace-required routes must refuse it')


def inventory_inputs(old, capacity, source, face_ids, low, high):
    """Counts of caller-owned inputs; no decoding, rational arithmetic or lease.

    This is the extraction seam for prospective native sizing, NOT a dynamic
    memory proof. Count aliases twice unless a native owner proves sharing.
    """
    return dict(cells=len(old), capacity_entries=len(capacity), source_entries=len(source),
        physical_face_ids=len(face_ids), low_stock_entries=len(low['energy']),
        high_stock_entries=len(high['energy']),
        low_raw_owner_entries=sum(len(row) for row in low['evidence']['raw_outward_energy_decimal']),
        high_raw_owner_entries=sum(len(row) for row in high['evidence']['raw_outward_energy_decimal']),
        native_workbudget_admitted=False, required_live_inventory=INVENTORY_OBLIGATIONS)


def _walk(values, check):
    for value in values:
        check()
        yield value


def _residual(energy, faces, load, check):
    values = [e-b for e, b in _walk(zip(energy, load, strict=True), check)]
    for i, j, amount in _walk(faces, check):
        values[i] += amount
        if j is not None:
            values[j] -= amount
    return values


def _face_fluxes(result, count, check):
    G = A.exact_library()
    evidence = result['evidence']
    target = _q(evidence['absolute_target_decimal'])
    faces, defect_max = [], G.mpq(0)
    for raw in _walk(evidence['raw_outward_energy_decimal'], check):
        if len(raw) not in (1, 2):
            raise ValueError('Expected one or two original face owners')
        if any(not 0 <= item[0] < count for item in raw):
            raise ValueError('Physical face owner outside the cell inventory')
        i, _, first = raw[0]
        first = _q(first)
        if len(raw) == 2:
            j, _, second = raw[1]
            second = _q(second)
            if i == j:
                raise ValueError('Physical face owners must differ')
            defect = abs(first+second)
            defect_max = max(defect_max, defect)
            if defect > target:
                raise ValueError('Independent face-owner pairing defect exceeds predictor target')
            amount = (first-second)/2
        else:
            j, amount = None, first
        faces.append((i, j, amount))
    return faces, defect_max


def _bounds(energy, capacity, bounds, check):
    exact = all(c*bounds[0] <= e <= c*bounds[1]
                for c, e in _walk(zip(capacity, energy, strict=True), check))
    stocks = [A.public_float(e) for e in _walk(energy, check)]
    temperatures = [e/A.public_float(c)
                    for e, c in _walk(zip(stocks, capacity, strict=True), check)]
    public = all(math.isfinite(t) and bounds[0] <= _q(t) <= bounds[1]
                 for t in _walk(temperatures, check))
    return dict(exact_pass=exact, actual_public_pass=public, enthalpy_j=stocks,
                temperature_k=temperatures)


def _correct(low, cap, low_faces, high_faces, bounds, permitted, check, *, admit):
    admit('full_correction', low=low, cap=cap, low_faces=low_faces, high_faces=high_faces,
          bounds=bounds, permitted=tuple(permitted))
    G = A.exact_library()
    if len(low_faces) != len(high_faces):
        raise ValueError('Low/high physical faces must match')
    exterior = {f for f, (_, j, _) in _walk(enumerate(low_faces), check) if j is None}
    if not set(permitted).issubset(exterior):
        raise ValueError('Only actual exterior reservoirs may be corrected')
    full, full_faces, full_alphas, corrections = low[:], [], [], []
    for f, ((i, j, lo), (hi, hj, high)) in _walk(enumerate(zip(low_faces, high_faces, strict=True)), check):
        if (i, j) != (hi, hj) or not 0 <= i < len(cap) or j is not None and (not 0 <= j < len(cap) or i == j):
            raise ValueError('Physical face owner/order mismatch')
        allowed = j is not None or f in permitted
        delta = lo-high if allowed else G.mpq(0)
        corrections.append((i, j, delta))
        full[i] += delta
        if j is not None:
            full[j] -= delta
        full_faces.append((i, j, lo-delta))
        full_alphas.append(G.mpq(1) if allowed else G.mpq(0))
    full_check = _bounds(full, cap, bounds, check)
    if full_check['exact_pass'] and full_check['actual_public_pass']:
        energy, faces, alphas = full, full_faces, full_alphas
        branch = 'COMPLETE_PHYSICAL_CORRECTION_ADMISSIBLE'
    else:
        admit('limited_correction', low=low, cap=cap, low_faces=low_faces, corrections=corrections, bounds=bounds)
        positive, negative = [G.mpq(0)]*len(cap), [G.mpq(0)]*len(cap)
        for i, j, delta in _walk(corrections, check):
            for owner, incoming in ((i, delta),) if j is None else ((i, delta), (j, -delta)):
                positive[owner] += max(G.mpq(0), incoming)
                negative[owner] += min(G.mpq(0), incoming)
        if not all(c*bounds[0] <= e <= c*bounds[1] for c, e in _walk(zip(cap, low, strict=True), check)):
            raise ValueError('Low state fails unchanged exact temperature bounds')
        up = [min(G.mpq(1), (c*bounds[1]-e)/p) if p else G.mpq(1)
              for c, e, p in _walk(zip(cap, low, positive, strict=True), check)]
        down = [min(G.mpq(1), (c*bounds[0]-e)/p) if p else G.mpq(1)
                for c, e, p in _walk(zip(cap, low, negative, strict=True), check)]
        energy, faces, alphas = low[:], [], []
        for (i, j, delta), (_, _, lo) in _walk(zip(corrections, low_faces, strict=True), check):
            alpha = up[i] if delta >= 0 else down[i]
            if j is not None:
                alpha = min(alpha, down[j] if delta >= 0 else up[j])
            if not 0 <= alpha <= 1:
                raise ArithmeticError('Invalid signwise correction scalar')
            energy[i] += alpha*delta
            if j is not None:
                energy[j] -= alpha*delta
            faces.append((i, j, lo-alpha*delta))
            alphas.append(alpha)
        branch = 'UNCHANGED_SIGNWISE_FCT_FALLBACK'
    final_check = _bounds(energy, cap, bounds, check)
    if not final_check['exact_pass'] or not final_check['actual_public_pass']:
        raise ValueError('Correction fails unchanged exact or actual public temperature bounds; no clipping or bound relaxation')
    zeros = [G.mpq(0)]*len(cap)
    if _residual(energy, faces, zeros, check) != _residual(low, low_faces, zeros, check):
        raise ArithmeticError('Physical correction changed the exact low ledger')
    if any(q != low_faces[f][2] for f, (_, j, q) in _walk(enumerate(faces), check) if j is None and f not in permitted):
        raise ArithmeticError('A fixed exterior transfer changed')
    evidence = dict(branch=branch, unchanged_bounds=bounds, full_candidate=full,
        full_candidate_check=full_check, final_check=final_check,
        exact_low_ledger_preserved=True, fixed_exterior_transfers_preserved=True,
        one_antisymmetric_transfer_per_physical_face=True,
        full_admission_preserves_all_permitted_high_face_transfers=all(
            faces[f][2] == high_faces[f][2] for f, (_, j, _) in _walk(enumerate(faces), check)
            if j is not None or f in permitted) if branch.startswith('COMPLETE') else None,
        no_change_to_reconstruction_or_exact_degree3_moments=True)
    return energy, faces, alphas, evidence


def _closed_guard(old, cap, low, candidate, low_faces, candidate_faces, bounds, check, *, admit):
    """Same exact/public <=0 tests and scalar search; bounded sign evidence.

    D=sum((new-old)*(new+old)/(2*C)) is algebraically H(new)-H(old).
    Public T uses energy=C*represented_T, so its predicate is exactly
    sum(C*(T_new**2-T_old**2)/2)<=0. Neither is a tolerance criterion.
    The prior a,b,c expansion is not materialised; its algebraic equivalence
    is explicit, rather than checked by constructing two giant exact sums.
    """
    admit('closed_guard', old=old, cap=cap, low=low, candidate=candidate,
          low_faces=low_faces, candidate_faces=candidate_faces, bounds=bounds)
    G = A.exact_library()
    for lo, hi in _walk(zip(low_faces, candidate_faces, strict=True), check):
        if lo[:2] != hi[:2]:
            raise ValueError('Physical face owner/order mismatch')
        if lo[1] is None and (lo[2] or hi[2]):
            raise ValueError('Closed guard requires zero exterior transfers')
    residual = _residual(low, low_faces, old, check)
    if _residual(candidate, candidate_faces, old, check) != residual:
        raise ValueError('The supplied high/FCT endpoint must preserve the low physical-face ledger residual')
    difference = [f-e for e, f in _walk(zip(low, candidate, strict=True), check)]
    dq = [hi[2]-lo[2] for lo, hi in _walk(zip(low_faces, candidate_faces, strict=True), check)]
    old_stock = [A.public_float(e) for e in _walk(old, check)]
    cap_float = [A.public_float(c) for c in _walk(cap, check)]
    old_temperature = [e/c for e, c in _walk(zip(old_stock, cap_float, strict=True), check)]
    old_public = [_q(e) for e in _walk(old_stock, check)]
    old_public_t_energy = [c*_q(t) for c, t in _walk(zip(cap, old_temperature, strict=True), check)]

    def state(theta):
        energies = [e+theta*d for e, d in _walk(zip(low, difference, strict=True), check)]
        faces = [(lo[0], lo[1], lo[2]+theta*change)
                 for lo, change in _walk(zip(low_faces, dq, strict=True), check)]
        stocks = [A.public_float(e) for e in _walk(energies, check)]
        temperatures = [e/c for e, c in _walk(zip(stocks, cap_float, strict=True), check)]
        return energies, faces, stocks, temperatures

    def certificate(theta):
        energies, _, stocks, temperatures = state(theta)
        exact_sign = A.quadratic_nonincrease(old, energies, cap, cancelled=check)
        public_sign = A.quadratic_nonincrease(old_public,
            [_q(e) for e in _walk(stocks, check)], cap, cancelled=check)
        public_t_sign = A.quadratic_nonincrease(old_public_t_energy,
            [c*_q(t) for c, t in _walk(zip(cap, temperatures, strict=True), check)],
            cap, cancelled=check)
        flags = dict(exact_supply=exact_sign['nonincrease'],
            public_stock_supply=public_sign['nonincrease'],
            public_temperature_supply=public_t_sign['nonincrease'],
            exact_bounds=all(c*bounds[0] <= e <= c*bounds[1] for c, e in _walk(zip(cap, energies, strict=True), check)),
            public_bounds=all(bounds[0] <= _q(t) <= bounds[1] for t in _walk(temperatures, check)))
        return dict(schema='atlas.closed-quadratic-sign-certificate.r2',
            passed=all(flags.values()), flags=flags,
            exact_h_change_certificate=exact_sign,
            public_stock_h_change_certificate=public_sign,
            public_temperature_h_change_certificate=public_t_sign,
            exact_source_work=G.mpq(0), public_source_work=G.mpq(0), reservoir_work=G.mpq(0),
            quadratic_expansion_equivalence='algebraic: direct exact energy difference equals the unmaterialised a*theta^2+b*theta+c',
            exact_change_values_available_only_within_materialised_fallback_certificates=True)

    low_check, full_check = certificate(G.mpq(0)), certificate(G.mpq(1))
    try:
        theta, selection = A.feasible_scalar(lambda t: certificate(t)['passed'])
    except ValueError as error:
        raise A.SupplyGuardRefused(str(error), dict(low=low_check, full=full_check,
            quadratic_evidence='sign enclosures; global exact a,b,c not materialised',
            physical_ledger_residual=residual)) from error
    checked = certificate(theta)
    energies, faces, _, _ = state(theta)
    if not checked['passed'] or _residual(energies, faces, old, check) != residual:
        raise ArithmeticError('Closed guard changed the exact low ledger or failed its certificate')
    # For every cell, the verified residual equality says dE_i+sum(dq_if)=0.
    # Every interior face is one shared amount with opposite owner signs;
    # its contributions cancel identically. Exterior amounts at both endpoints
    # are exactly zero, hence so are their interpolants. Thus sum(dE_i)=0
    # exactly, without constructing a global common denominator from the dE_i.
    conservation = dict(schema='atlas.closed-paired-ledger-identity.r1',
        exact_cell_ledger_unchanged=True, face_owner_order_unchanged=True,
        one_shared_opposite_transfer_per_interior_face=True,
        exterior_transfers_exactly_zero=True,
        identity='sum_i(dE_i) = -sum_f(exterior dq_f) = 0; interior dq cancels by incidence',
        exact_total_stock_change=G.mpq(0),
        route='EXACT_PER_CELL_LEDGER_AND_SHARED_FACE_IDENTITY',
        global_corrected_stock_sum_materialised=False)
    checked['stock_conservation_certificate'] = conservation
    return dict(exact_energy=energies, physical_faces=faces, theta=theta,
                certificate=checked, selection=selection,
                low_endpoint_certificate=low_check, full_endpoint_certificate=full_check)


def _encoded(record, check):
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False,
        default=_encode_rational)
    data = bytearray()
    for chunk in _walk(encoder.iterencode(record), check):
        data.extend(chunk.encode('utf-8'))
    check()
    return bytes(data)


def _issue(old, cap, new, faces, face_ids, source, retained, target, fixed, powers, bindings, check):
    """Adapter-r2's requested non-supply path, with cancellation in each pass."""
    G = A.exact_library()
    if not math.isfinite(A.public_float(target)) or target <= 0:
        raise ValueError('An independently supplied positive finite absolute residual target is required')
    if any(e <= 0 for e in _walk(new, check)):
        raise ValueError('Positive capacities and corrected enthalpies required')
    cap_public = [A.public_float(c) for c in _walk(cap, check)]
    if [_q(c) for c in _walk(cap_public, check)] != cap:
        raise ValueError('This caloric adapter requires the actual represented binary64 capacities')
    stocks = [A.public_float(e) for e in _walk(new, check)]
    temperatures = [e/c for e, c in _walk(zip(stocks, cap_public, strict=True), check)]
    exterior = {f for f, (_, j, _) in _walk(enumerate(faces), check) if j is None}
    if (not set(fixed).issubset(exterior) or not set(powers).issubset(exterior)
            or set(fixed) & set(powers) or any(t <= 0 for t in _walk(fixed.values(), check))):
        raise ValueError('Consistent positive Dirichlet or prescribed-energy exterior declarations required')
    for f in _walk(exterior-set(fixed), check):
        if faces[f][2] != powers.get(f, G.mpq(0)):
            raise ValueError('An exterior prescribed transfer changed or an undeclared face is non-insulated')
    loaded = [e+s for e, s in _walk(zip(old, source, strict=True), check)]
    for f in _walk(exterior-set(fixed), check):
        loaded[faces[f][0]] -= faces[f][2]
    hull = [e/c for e, c in _walk(zip(loaded, cap, strict=True), check)]+list(fixed.values())
    bounds = min(hull), max(hull)
    exact_bounds = all(c*bounds[0] <= e <= c*bounds[1] for c, e in _walk(zip(cap, new, strict=True), check))
    public_bounds = all(bounds[0] <= _q(t) <= bounds[1] for t in _walk(temperatures, check))
    if not exact_bounds or not public_bounds:
        raise ValueError('Corrected state leaves its declared loaded/prescribed/Dirichlet convex hull')
    load = [e+s for e, s in _walk(zip(old, source, strict=True), check)]
    exact_residual = _residual(new, faces, load, check)
    if exact_residual != retained:
        raise ValueError('Corrected result changed the declared exact per-cell ledger residual')
    residual_max = max(abs(r) for r in _walk(exact_residual, check))
    if residual_max > target:
        raise ValueError('Retained exact cell residual exceeds the independently supplied absolute residual target')
    public_stocks = [_q(p) for p in _walk(stocks, check)]
    public_residual = _residual(public_stocks, faces, load, check)
    stock_projection = [p-e for p, e in _walk(zip(public_stocks, new, strict=True), check)]
    if [r+p for r, p in _walk(zip(exact_residual, stock_projection, strict=True), check)] != public_residual:
        raise ArithmeticError('Stock projection audit does not reconcile')
    global_balance = A.paired_global_balance(public_stocks, load, faces, cancel=check)
    boundary_energy = global_balance['outward'] if exterior else 0
    source_total = sum(_walk(source, check))
    scale = max(sum(abs(e) for e in _walk(old, check)), sum(abs(e) for e in _walk(public_stocks, check)),
                abs(source_total), abs(boundary_energy))
    relative = abs(global_balance['total'])/scale
    if relative > G.mpq(1, 10**11):
        raise ValueError('Private booked-ledger global residual exceeds the existing 1e-11 energy gate')
    sources = dict(_CORE_SOURCES)
    for incoming in (_SOURCES, bindings):
        for path, digest in _walk(incoming.items(), check):
            key = str(Path(path).resolve())
            if key in sources and sources[key] != digest:
                raise ValueError('Input source binding conflicts with a core adapter/helper binding')
            sources[key] = digest
    for path, digest in _walk(sources.items(), check):
        if _sha(path) != digest:
            raise ValueError('Private adapter input source binding changed')
    record = dict(schema=SCHEMA, private_only=True, production_acceptance=False,
        production_issue_called=False, sources=sources,
        native_origin_bound=False, production_resource_admitted=False,
        method_id=METHOD, state_semantics='Authoritative extensive enthalpy and represented capacity; public T=stored E/C is a caloric point representative, not an exact continuum cell mean.',
        endpoint_face_trace_status=TRACE_STATUS,
        transfer_semantics='One exact step-integrated outward energy per supplied physical face; opposite owner receives its exact negative. Not an endpoint constitutive flux.',
        face_geometry_certified_by_adapter=False, face_ids=list(face_ids), physical_faces=faces,
        old_energy=old, capacity=cap, source_energy=source, corrected_energy_exact=new,
        enthalpy_j=stocks, temperature_k=temperatures,
        boundary_temperature={str(f): t for f, t in _walk(fixed.items(), check)},
        prescribed_boundary_energy={str(f): q for f, q in _walk(powers.items(), check)}, derived_loaded_bounds=bounds,
        exact_bounds_pass=exact_bounds, actual_public_bounds_pass=public_bounds,
        exact_cell_residual=exact_residual, stock_projection_residual=stock_projection,
        independently_supplied_absolute_residual_target=target,
        exact_cell_residual_max=residual_max, exact_cell_residual_target_pass=True,
        public_cell_residual=public_residual, projection_audit_reconciles_exactly=True,
        exact_global_source_energy=source_total, exact_global_outward_energy=boundary_energy,
        public_global_relative=float(relative), optional_supply=dict(status='NOT_REQUESTED_NOT_AN_ADMISSION_REQUIREMENT'),
        exact_public_global_residual=global_balance['total'],
        global_balance_evaluation='exact stock/source/exterior identity after all per-cell and projection checks')
    record['result_id'] = hashlib.sha256(_encoded(record, check)).hexdigest()
    return PrivateNumericalResult(_encoded(record, check))


def _finish(old, capacity, dt, source, normalized_boundary, face_ids, low, high,
            source_bindings, absolute_residual_target, cancelled=None, *, admit):
    """Finish already-solved predictors, returning (private result, diagnostics).

    ``low/high`` have sparse solver's ``energy`` and ``evidence`` fields;
    evidence supplies ordered raw owner energies and its absolute target.
    Both predictor targets must be exactly rational-equal to the independently
    supplied target; a saved looser/tighter run cannot silently be reused.
    ``face_ids`` must be in that SAME order, with normalised boundary entries
    ``id: ('temperature'|'power', binary64_value)``. No geometry or predictor
    solve is performed or inferred. The caller owns geometry/operand/solver
    provenance; source_bindings is retained and checked, not invented.

    Diagnostics omit reconstruction timings and native budget statistics that
    this function cannot know. Stored high energy is not substituted for the
    face-derived conservative full candidate, exactly as in composed-r4.
    """
    def check():
        if cancelled is not None and cancelled():
            raise CancelledError('Private conservative heat finish cancelled')

    started = perf_counter()
    check()
    if _sha(__file__) != _LOADED:
        raise ValueError('Finisher source changed since import')
    try:
        target = _q(absolute_residual_target)
        if target <= 0 or not math.isfinite(A.public_float(target)):
            raise ValueError('Nonpositive or nonfinite absolute residual target')
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('An independently supplied positive finite absolute residual target is required') from error
    for name, predictor in _walk((('low', low), ('high', high)), check):
        if _q(predictor['evidence']['absolute_target_decimal']) != target:
            raise ValueError(name+' predictor target differs from independently supplied absolute residual target')
    cap, previous, physical_source = [[_q(float(v)) for v in _walk(values, check)]
                                      for values in (capacity, old, source)]
    n = len(cap)
    if not n or len(previous) != n or len(physical_source) != n or any(c <= 0 for c in _walk(cap, check)):
        raise ValueError('Complete original stocks, positive capacities and source arrays required')
    timestep = _q(float(dt))
    if timestep <= 0:
        raise ValueError('A positive timestep is required')
    source_energy = [timestep*p for p in _walk(physical_source, check)]
    load = [e+s for e, s in _walk(zip(previous, source_energy, strict=True), check)]
    low_energy = [_q(e) for e in _walk(low['energy'], check)]
    if len(low_energy) != n:
        raise ValueError('One low predictor stock per original cell is required')
    low_faces, low_pair_defect = _face_fluxes(low, n, check)
    high_faces, high_pair_defect = _face_fluxes(high, n, check)
    face_ids = list(_walk(face_ids, check))
    if len(face_ids) != len(low_faces) or len(set(face_ids)) != len(face_ids) or any(
            not isinstance(fid, str) or not fid for fid in _walk(face_ids, check)):
        raise ValueError('One unique supplied physical identifier per face required')
    boundary = dict(normalized_boundary)
    if not set(boundary).issubset(face_ids):
        raise ValueError('Boundary refers to an unknown physical face')
    fixed, prescribed = {}, {}
    for f, fid in _walk(enumerate(face_ids), check):
        if fid not in boundary:
            continue
        kind, value = boundary[fid]
        if kind not in ('temperature', 'power'):
            raise ValueError('Boundary must already be normalised as temperature or power')
        if low_faces[f][1] is not None:
            raise ValueError('Boundary must name an actual exterior physical face')
        if kind == 'temperature':
            fixed[f] = _q(float(value))
        else:
            prescribed[f] = timestep*_q(float(value))
    loaded = load[:]
    for f, energy in _walk(prescribed.items(), check):
        loaded[low_faces[f][0]] -= energy
    hull = [e/c for e, c in _walk(zip(loaded, cap, strict=True), check)]+list(fixed.values())
    bounds = min(hull), max(hull)
    corrected, faces, alphas, correction = _correct(low_energy, cap, low_faces, high_faces, bounds, set(fixed), check, admit=admit)
    residual = _residual(low_energy, low_faces, load, check)
    if _residual(corrected, faces, load, check) != residual:
        raise ArithmeticError('Physical correction changed the exact low ledger')
    closed = not fixed and not any(source_energy) and not any(prescribed.values())
    stability = dict(kind='loaded-temperature-convex-hull', closed_source_free=closed,
        high_spatial_coercivity_claimed=False, spatial_accuracy_separately_required=True)
    guard = None
    if closed:
        guard = _closed_guard(previous, cap, low_energy, corrected, low_faces, faces, bounds, check, admit=admit)
        corrected, faces = guard['exact_energy'], guard['physical_faces']
        stability.update(kind='loaded-bounds-and-closed-stock-quadratic-decay',
                         scalar=guard['theta'], certificate=guard['certificate'])
    admit('issue', old=previous, cap=cap, new=corrected, faces=faces, face_ids=face_ids,
          source=source_energy, retained=residual, target=target, fixed=fixed, powers=prescribed,
          bindings=source_bindings or {})
    result = _issue(previous, cap, corrected, faces, face_ids, source_energy, residual,
                    target, fixed, prescribed, source_bindings or {}, check)
    limited = sum(alpha < 1 and lo[2] != hi[2] for alpha, lo, hi in
                  _walk(zip(alphas, low_faces, high_faces, strict=True), check))
    check()
    return result, dict(seconds=perf_counter()-started, phase='post-predictor-finish-only',
        predictor_solves_performed=0, low_pair_defect=low_pair_defect, high_pair_defect=high_pair_defect,
        limited_nonzero_faces=limited, stability=stability, correction=correction,
        closed_guard_selection=guard['selection'] if guard else None,
        production_resource_admitted=False, paired_global_identity=True,
        production_acceptance=False, endpoint_face_trace_available=False,
        source_binding_scope='Caller-supplied predictor/geometry bindings plus finisher and result dependencies; no geometry inference')



def finish(old, capacity, dt, source, normalized_boundary, face_ids, low, high,
           source_bindings, absolute_residual_target, cancelled=None, *, budget, observe=None):
    """Return OwnedSolve((sealed result, info)); keep live while borrowing.

    All stages reserve derived policy inventories BEFORE their operations.
    Geometry/predictor/import baseline and new debug record() views remain
    caller-owned. No native issue, whole-method or allocator/RSS claim.
    """
    def check():
        if cancelled is not None and cancelled():
            raise CancelledError('Private conservative heat finish cancelled')
        return False
    check()
    operands = dict(old=old, capacity=capacity, dt=dt, source=source,
        normalized_boundary=normalized_boundary, face_ids=face_ids, low=low, high=high,
        absolute_residual_target=absolute_residual_target)
    # Inspect both already-owned binding maps before allocating their merge.
    initial = INVENTORY.admit('inputs', operands, source_bindings=_SOURCES,
        additional_bindings=source_bindings, budget=budget, cancel=check)
    import private_heat_gmp_resources_r1 as resources
    try:
        workspace = resources.OwnedWorkspace(budget, initial.value.inventory.total(),
            category='heat-finish-inputs-private', cancelled=check)
        workspace.__enter__()
    except BaseException:
        initial.__exit__(*sys.exc_info())
        raise
    workspace.stack.enter_context(initial)
    bindings = None
    stages = []
    def admit(stage, **values):
        metadata = workspace.stack.enter_context(INVENTORY.admit(stage, values,
            source_bindings=bindings, budget=budget, cancel=check))
        plan = metadata.value
        if observe is not None:
            observe('finish-'+stage+'-inventory-ready')
        workspace.stack.enter_context(resources.OwnedWorkspace(budget, plan.inventory.total(),
            category='heat-finish-'+stage+'-private', cancelled=check))
        stages.append(dict(stage=stage, input_bytes=plan.inventory.input_bytes,
            work_bytes=plan.inventory.work_bytes, result_bytes=plan.inventory.result_bytes,
            codec_chars=plan.codec_chars, search_history_entries=plan.search_history_entries,
            simultaneous_certificates=plan.simultaneous_certificates))
        if observe is not None:
            observe('finish-'+stage+'-workspace-admitted')
    try:
        bindings = dict(_SOURCES)
        for path, digest in (source_bindings or {}).items():
            if path in bindings and bindings[path] != digest:
                raise ValueError('Finisher source binding conflicts with fixed implementation')
            bindings[path] = digest
        result, info = _finish(old, capacity, dt, source, normalized_boundary, face_ids, low, high,
            bindings, absolute_residual_target, cancelled=check, admit=admit)
        info.update(resource_route='DERIVED_STAGED_ACCOUNTED_POLICY_NOT_NATIVE_OR_RSS',
            stage_inventories=stages, retained_owner_required=True,
            debug_record_views='New caller-owned allocations; not an unbounded borrowed-view allowance')
        return OWNERS.OwnedSolve((result, info), workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise

