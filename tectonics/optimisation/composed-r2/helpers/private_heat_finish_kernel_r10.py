"""Fixed FINISH with completed-conversion custody before numerical stages.

Frozen FINISH7 mathematics, exact values, source checks and observer events are
unchanged. The conversion producer returns its COMPLETE needed graph before
LIFE.compact admits that graph and retires conversion/metadata scratch. Caller
inputs retain their pre-existing external custody. No supplied producer or
saved-result callback is accepted; this remains private accounted ownership,
not a whole-case fit, allocator/RSS theorem or native production admission.

R10 is R9 on finish issue owned r4, which declares its two encodings as a single
step of a metered call, and on stage lifetime r3. Nothing else differs.
"""
from concurrent.futures import CancelledError
from hashlib import sha256
import math
from pathlib import Path
from time import perf_counter
import sys

import private_heat_finish_kernel_r3 as K
import private_heat_correction_owned_r1 as C
import private_heat_closed_owned_r4 as Q
import private_heat_finish_issue_owned_r4 as I
import private_heat_stage_lifetime_r3 as LIFE

A, PUBLIC = K.A, K.PUBLIC
METHOD = I.METHOD  # Numerical issuer unchanged; sources bind this accounting successor.
EndpointTraceUnavailable = K.EndpointTraceUnavailable
PrivateNumericalResult = K.PrivateNumericalResult
_q = A.rational
_SOURCES = dict(K._SOURCES)
for _module in (C, Q, I, LIFE):
    for _path, _pin in _module._SOURCES.items():
        if _path in _SOURCES and _SOURCES[_path] != _pin:
            raise ValueError('Conflicting fixed FINISH dependency')
        _SOURCES[_path] = _pin
_SOURCES[str(Path(__file__).resolve())] = sha256(Path(__file__).read_bytes()).hexdigest()


def _convert_values(old, capacity, dt, source, normalized_boundary, face_ids,
                    low, high, bindings, target_value, check):
    """The unchanged conversion producer; omitted locals die on this return."""
    started = perf_counter()
    def walk(values):
        return K._walk(values, check)
    try:
        target = _q(target_value)
        if target <= 0 or not math.isfinite(PUBLIC.public_float(target)):
            raise ValueError('Nonpositive or nonfinite absolute residual target')
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('An independently supplied positive finite absolute residual target is required') from error
    for name, predictor in walk((('low', low), ('high', high))):
        if _q(predictor['evidence']['absolute_target_decimal']) != target:
            raise ValueError(name+' predictor target differs from independently supplied absolute residual target')
    cap, previous, physical_source = [[_q(float(v)) for v in walk(values)]
                                      for values in (capacity, old, source)]
    n = len(cap)
    if not n or len(previous) != n or len(physical_source) != n or any(c <= 0 for c in walk(cap)):
        raise ValueError('Complete original stocks, positive capacities and source arrays required')
    timestep = _q(float(dt))
    if timestep <= 0:
        raise ValueError('A positive timestep is required')
    source_energy = [timestep*p for p in walk(physical_source)]
    load = [e+s for e, s in walk(zip(previous, source_energy, strict=True))]
    low_energy = [_q(e) for e in walk(low['energy'])]
    if len(low_energy) != n:
        raise ValueError('One low predictor stock per original cell is required')
    low_faces, low_pair_defect = K._face_fluxes(low, n, check)
    high_faces, high_pair_defect = K._face_fluxes(high, n, check)
    face_ids = list(walk(face_ids))
    if len(face_ids) != len(low_faces) or len(set(face_ids)) != len(face_ids) or any(
            not isinstance(fid, str) or not fid for fid in walk(face_ids)):
        raise ValueError('One unique supplied physical identifier per face required')
    boundary = dict(normalized_boundary)
    if not set(boundary).issubset(face_ids):
        raise ValueError('Boundary refers to an unknown physical face')
    fixed, prescribed = {}, {}
    for f, fid in walk(enumerate(face_ids)):
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
    for f, energy in walk(prescribed.items()):
        loaded[low_faces[f][0]] -= energy
    hull = [e/c for e, c in walk(zip(loaded, cap, strict=True))]+list(fixed.values())
    bounds = min(hull), max(hull)
    return dict(started=started, target=target, cap=cap, previous=previous,
        source_energy=source_energy, load=load, low_energy=low_energy,
        low_faces=low_faces, high_faces=high_faces, low_pair_defect=low_pair_defect,
        high_pair_defect=high_pair_defect, face_ids=face_ids, fixed=fixed,
        prescribed=prescribed, bounds=bounds, bindings=bindings)


def _converted_inputs(old, capacity, dt, source, normalized_boundary, face_ids,
                      low, high, source_bindings, target_value, budget, check):
    """Own input planning and conversion until their complete producer returns."""
    operands = dict(old=old, capacity=capacity, dt=dt, source=source,
        normalized_boundary=normalized_boundary, face_ids=face_ids, low=low, high=high,
        absolute_residual_target=target_value)
    initial = K.INVENTORY.admit('inputs', operands, source_bindings=_SOURCES,
        additional_bindings=source_bindings, budget=budget, cancel=check)
    import private_heat_gmp_resources_r1 as resources
    try:
        work = resources.OwnedWorkspace(budget, initial.value.inventory.total(),
            category='heat-finish-inputs-private', cancelled=check)
        work.__enter__()
    except BaseException:
        initial.__exit__(*sys.exc_info())
        raise
    work.stack.enter_context(initial)
    try:
        bindings = dict(_SOURCES)
        for path, digest in (source_bindings or {}).items():
            if path in bindings and bindings[path] != digest:
                raise ValueError('Finisher source binding conflicts with fixed implementation')
            bindings[path] = digest
        value = _convert_values(old, capacity, dt, source, normalized_boundary,
            face_ids, low, high, bindings, target_value, check)
        return K.OWNERS.OwnedSolve(value, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


def _orchestration_bytes(face_count, source_bindings):
    """Fixed later metadata/owner references, never rational-width estimates.

    256 KiB baseline; 128 container units for three stage inventories, stability,
    result/diagnostic dictionaries, owner/stack frames and iterators; one unit
    per face for the temporary permitted-face set; eight units per source entry
    for binding/owner references; eight bytes per source character for metadata
    and diagnostic string generations. Numerical graphs have separate owners.
    """
    incoming = source_bindings if isinstance(source_bindings, dict) else {}
    maps = (_SOURCES, incoming)
    paths = sum(len(values) for values in maps)
    text = sum(len(path)+len(digest) for values in maps for path, digest in values.items()
               if isinstance(path, str) and isinstance(digest, str))
    return 262144+1024*(128+face_count+8*paths)+8*text


def _run(work, budget, converted, check, observe):
    started = converted['started']
    (target, cap, previous, source_energy, load, low_energy, low_faces, high_faces,
     low_pair_defect, high_pair_defect, face_ids, fixed, prescribed, bounds, bindings) = (
        converted[key] for key in ('target', 'cap', 'previous', 'source_energy', 'load',
            'low_energy', 'low_faces', 'high_faces', 'low_pair_defect', 'high_pair_defect',
            'face_ids', 'fixed', 'prescribed', 'bounds', 'bindings'))
    def walk(values):
        return K._walk(values, check)
    def retain(owner, stage):
        retained = work.stack.enter_context(owner)
        if observe is not None:
            observe('finish-'+stage+'-workspace-admitted')
        return retained
    correction_owner = retain(C.correct(low_energy, cap, low_faces, high_faces,
        bounds, set(fixed), budget=budget, cancelled=check), 'correction')
    corrected, faces, alphas, correction = correction_owner.value
    ar = correction_owner._workspace.arithmetic
    residual = Q._residual(ar, low_energy, low_faces, load)
    if not Q._equal_arrays(ar, Q._residual(ar, corrected, faces, load), residual):
        raise ArithmeticError('Physical correction changed the exact low ledger')
    ar.settle((correction_owner.value, residual))
    closed = not fixed and not any(source_energy) and not any(prescribed.values())
    stability = dict(kind='loaded-temperature-convex-hull', closed_source_free=closed,
        high_spatial_coercivity_claimed=False, spatial_accuracy_separately_required=True)
    guard, closed_owner = None, None
    if closed:
        closed_owner = retain(Q.closed_guard(previous, cap, low_energy, corrected, low_faces, faces,
            bounds, budget=budget, cancelled=check), 'closed_guard')
        guard = closed_owner.value
        corrected, faces = guard['exact_energy'], guard['physical_faces']
        stability.update(kind='loaded-bounds-and-closed-stock-quadratic-decay',
                         scalar=guard['theta'], certificate=guard['certificate'])
    issue_owner = retain(I.issue(previous, cap, corrected, faces, face_ids, source_energy,
        residual, target, fixed, prescribed, bindings, check, budget=budget), 'issue')
    result = issue_owner.value
    # Comparisons here inspect only exact alpha 0..1, and prior existing face
    # equality. Their conservative cross-products are explicitly admitted.
    limited = 0
    for alpha, lo, hi in walk(zip(alphas, low_faces, high_faces, strict=True)):
        if ar.less(alpha, 1) and not ar.equal(lo[2], hi[2]):
            limited += 1
    ar.settle()
    check()
    stages = [dict(stage='correction', **correction_owner.inventory)]
    if closed_owner is not None:
        stages.append(dict(stage='closed_guard', **closed_owner.inventory))
    if hasattr(issue_owner, 'inventory'):
        stages.append(dict(stage='issue', **issue_owner.inventory))
    return result, dict(seconds=perf_counter()-started, phase='post-predictor-finish-only',
        predictor_solves_performed=0, low_pair_defect=low_pair_defect, high_pair_defect=high_pair_defect,
        limited_nonzero_faces=limited, stability=stability, correction=correction,
        closed_guard_selection=guard['selection'] if guard else None,
        production_resource_admitted=False, paired_global_identity=True,
        production_acceptance=False, endpoint_face_trace_available=False,
        source_binding_scope='Caller-supplied predictor/geometry bindings plus finisher and result dependencies; no geometry inference',
        resource_route='FIXED_EXACT_OPERATION_LIVE_ARRAY_POLICY_NOT_NATIVE_OR_RSS',
        stage_inventories=stages, retained_owner_required=True,
        debug_record_views='New caller-owned allocations; not an unbounded borrowed-view allowance')


def finish(old, capacity, dt, source, normalized_boundary, face_ids, low, high,
           source_bindings, absolute_residual_target, cancelled=None, *, budget, observe=None):
    """Same fixed FINISH API; input and output borrows require their owners."""
    def check():
        if cancelled is not None and cancelled():
            raise CancelledError('Private conservative heat finish cancelled')
        return False
    check()
    import private_heat_gmp_resources_r1 as resources
    amount = _orchestration_bytes(len(face_ids), source_bindings)
    work = resources.OwnedWorkspace(budget, amount,
        category='heat-finish-orchestration-private', cancelled=check)
    work.__enter__()
    try:
        raw = work.stack.enter_context(_converted_inputs(old, capacity, dt, source,
            normalized_boundary, face_ids, low, high, source_bindings,
            absolute_residual_target, budget, check))
        # The complete conversion frame has gone before any release credit.
        # No converted value is borrowed by this frame before full transfer.
        converted = work.stack.enter_context(LIFE.compact(raw, budget=budget,
            cancelled=check, category='heat-completed-finish-inputs'))
        raw = None  # its closed handle may remain on the stack, never its graph
        # External callers keep their own input custody; drop OUR aliases.
        old = capacity = dt = source = normalized_boundary = face_ids = None
        low = high = source_bindings = absolute_residual_target = None
        result = _run(work, budget, converted.value, check, observe)
        result[1].update(input_conversion_custody=converted.retention,
            input_conversion_producer_workspace_released=True,
            orchestration_accounted_bytes=amount)
        return K.OWNERS.OwnedSolve(result, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise

