"""Owned structured interval assessment with exact fast Decimal80 conversion.

Same r1 certificate, screen and declared precision ladder. Expected exhaustion
or exact incompatibility returns an owned status rather than leaking traceback
lifetimes into rank fallback. Successful result is numerically identical.
Conversion scratch is derived before MPFR endpoint export; no giant Decimal
integer is needed under clamp=0. Other contexts retain the original route.
Not a complete reconstruction, native method or allocator/RSS proof.
"""
from decimal import localcontext, ROUND_HALF_EVEN
from hashlib import sha256
from pathlib import Path
import sys
from time import perf_counter

import private_heat_certification_kernel_r1 as K
import private_heat_certification_resources_r1 as INVENTORY
import private_heat_decimal_sparse_core_r1 as P
import private_heat_rational_decimal_kernel_r1 as DECIMAL
import private_heat_low_ledger_inventory_r1 as L

G = K.G
Unresolved = K.Unresolved
ExactIncompatibility = K.ExactIncompatibility
PRECISIONS = K.PRECISIONS



def _round_bounds(bounds, cancelled):
    lo, hi = bounds
    if lo > hi or not G.is_finite(lo) or not G.is_finite(hi):
        raise ValueError('Finite ordered enclosure required')
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_HALF_EVEN
        a = DECIMAL.dec(G.mpq(lo), context=context, cancelled=cancelled)
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_HALF_EVEN
        b = DECIMAL.dec(G.mpq(hi), context=context, cancelled=cancelled)
    if a != b or (a.is_zero() and a.is_signed() != b.is_signed()):
        raise Unresolved('Enclosure crosses a Decimal80 rounding boundary')
    return a


def _export_plan(bounds, dual, proof, R, cancelled):
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_HALF_EVEN
        if context.clamp:
            return INVENTORY.export_plan(bounds, dual, proof, G, R, cancelled)
        # |adjusted exponent| <= max(numerator bits, denominator bits)+1.
        # quantum=max(exponent-79,Etiny): a negative Etiny cannot increase
        # the magnitude beyond that bound; positive Etiny can and is included.
        positive_tiny = max(0, context.Etiny())
    ar = L.RationalGrowth(G, R, cancelled)
    retained = scratch = largest_bits = count = 1
    for pair in (*bounds.values(), *dual):
        for value in pair:
            INVENTORY.check(cancelled)
            shape = INVENTORY.endpoint_shape(value, G, ar)
            retained += ar.slot(shape)
            scratch += 8*ar.slot(shape)
            largest_bits = max(largest_bits, shape.numerator, shape.denominator)
            count += 1
    for value in proof.values():
        if type(value) is G.mpfr:
            shape = INVENTORY.endpoint_shape(value, G, ar)
            retained += ar.slot(shape)
            largest_bits = max(largest_bits, shape.numerator, shape.denominator)
    converter_bits = INVENTORY.size(5*largest_bits+4*positive_tiny+512)
    # pow10, product, quotient/remainder, num_digits and comparison temporaries
    # plus endpoint getters are sequential; reserve their simultaneous slots.
    scratch += 48*R.native_slot_allowance(R.RationalShape(converter_bits, converter_bits))
    retained += INVENTORY.D.CONTAINER_UNIT*(8*len(bounds)+4*len(dual)+64)+len(bounds)*INVENTORY.D.decimal_slot(80)
    return INVENTORY.Plan('exact-dyadic-export-and-fast-rounding', (
        ('retained_values_and_output_containers', INVENTORY.size(retained)),
        ('simultaneous_export_decimal_copies', INVENTORY.size(scratch)),
        ('scalar_export_workspace', R.native_workspace_allowance(converter_bits, 64))),
        (('endpoint_values', count), ('largest_export_bits', largest_bits),
         ('converter_scalar_bits', converter_bits)))

def _attempt(matrix, rhs, keys, base_keys, signed_tau, conversion, physical, *,
             precision, largest_owned_bytes, budget, cancelled, audit, resource_evidence):
    """One isolated frame; normal refusal cannot retain prior numerical locals."""
    import private_heat_gmp_resources_r1 as R
    plan = INVENTORY.interval_plan(len(matrix), len(rhs), precision, largest_owned_bytes, R)
    work = R.OwnedWorkspace(budget, plan.total, category='heat-functional-interval-'+str(precision),
                            cancelled=cancelled)
    work.__enter__()
    dual = ar = proof = bounds = rounded = result = export = None
    reason = None
    try:
        try:
            dual, ar, proof = K.solve_enclosure(matrix, rhs, precision=precision,
                                                cancelled=cancelled, evidence=audit)
            bounds = K.physical_bounds(matrix, dual, keys, base_keys, signed_tau, conversion, ar)
            for key, value in physical.items():
                ar.check('exact-singleton-moment-refinement')
                if not bounds[key][0] <= value <= bounds[key][1]:
                    raise ArithmeticError('Proved singleton moment conflicts with the certified enclosure')
                bounds[key] = value, value
            export = _export_plan(bounds, dual, proof, R, cancelled)
            # All prior MPFR values remain live. Exact export, int/Decimal
            # scratch and retained values are an ADDITION, not a replacement.
            work.resize_before_allocation_or_after_drop(plan.total+export.total)
            def checked_round(value):
                INVENTORY.check(cancelled)
                return _round_bounds(value, cancelled)
            def exact_pair(value):
                INVENTORY.check(cancelled)
                return tuple(map(G.mpq, value))
            rounded = {key: checked_round(value) for key, value in bounds.items()}
            proof['exact_singleton_observation_coefficients'] = len(physical)
            result = dict(keys=list(bounds), bounds={key: exact_pair(bound)
                                                     for key, bound in bounds.items()},
                          decimal80=rounded, precision_bits=precision, proof=proof,
                          dual_bounds=[exact_pair(bound) for bound in dual])
        except Unresolved as error:
            reason = str(error)
        if reason is not None:
            # Expected refusal is NOT exposed as an exception object. The except
            # suite has cleared error/traceback, and all surviving return locals
            # are dropped before a successful close releases their reservation.
            dual = ar = proof = bounds = rounded = result = export = None
            work.__exit__(None, None, None)
            resource_evidence.append(dict(precision_bits=precision, admitted_bytes=plan.total,
                status='REFUSED_AND_DROPPED_BEFORE_NEXT_ATTEMPT'))
            return None, reason
        # Result retains only exact endpoints, Decimal values, proof scalars and
        # small containers. Drop MPFR dual/physical arrays and Arithmetic contexts
        # before shrinking. result still owns proof/rounded and is funded below.
        dual = ar = proof = bounds = rounded = None
        retained = dict(export.components)['retained_values_and_output_containers']
        work.resize_before_allocation_or_after_drop(retained)
        resource_evidence.append(dict(precision_bits=precision, admitted_bytes=plan.total+export.total,
            retained_bytes=retained, export_largest_bits=dict(export.counts)['largest_export_bits'],
            status='CERTIFIED'))
        return P.OwnedSolve(result, work), None
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


def assess_weights(matrix, rhs, keys, base_keys, signed_tau, conversion, *, budget,
                      precisions=PRECISIONS, cancelled=None, evidence=None, resource_evidence=None):
    """Owned same-weight interval certificate; borrow result only while live.

    Inputs must be immutable during the call and already owned exact GMP/int
    operands. Default precision ladder is unchanged; explicitly supplied ladders
    retain the original API semantics, not an implicit precision relaxation.
    Source-bound metadata sizes precede exact screen, interval and export work.
    """
    K._require_gmp()
    INVENTORY.check(cancelled)
    if type(precisions) not in (list, tuple) or not precisions:
        raise ValueError('Finite explicit nonempty precision ladder required')
    import private_heat_gmp_resources_r1 as R
    metadata, largest = INVENTORY.metadata_bytes(matrix, rhs, conversion, signed_tau, G, cancelled)
    work = R.OwnedWorkspace(budget, metadata, category='heat-functional-screen-and-metadata', cancelled=cancelled)
    work.__enter__()
    try:
        INVENTORY.verify_sources(cancelled)
        if sha256(Path(DECIMAL.__file__).read_bytes()).hexdigest() != '1b6182c8a2b2dc8e7a051b8fd078b0cb58cec6f104f3b9587e2e4eab751f232f':
            raise ValueError('Reviewed exact Decimal converter changed')
        # No copied key set, source audit or exact coefficient until admitted.
        screen = INVENTORY.screen_plan(matrix, rhs, conversion, signed_tau, G, R, cancelled)
        # Explicit caller ladders may contain more entries than the default;
        # audit storage is proportional to that declared finite count.
        work.resize_before_allocation_or_after_drop(metadata+screen.total+INVENTORY.D.CONTAINER_UNIT*8*len(precisions))
        audit = {} if evidence is None else evidence
        resources = {} if resource_evidence is None else resource_evidence
        resources.update(metadata_bytes=metadata, exact_screen_bytes=screen.total, attempts=[],
            prospective_accounted_policy=True, allocator_or_rss_bound=False,
            exact_rank_or_fallback_admitted=False, whole_method_admission=False,
            previous_attempt_released_before_next=True)
        audit['attempts'] = []
        audit['singleton_moments'] = {}
        incompatibility = None
        forced = {}
        try:
            forced = K.forced_coefficients(matrix, rhs, cancelled=cancelled, evidence=audit['singleton_moments'])
        except K.InconsistentConstraints as error:
            incompatibility = str(error)
        finally:
            for witness in audit['singleton_moments'].get('witnesses', []):
                for name in ('coefficient', 'target', 'forced_value'):
                    witness[name] = K.qhex(witness[name])
            audit['singleton_moments']['scalar_encoding'] = 'canonical signed-hex rational pairs'
        if incompatibility is not None:
            return P.OwnedSolve(dict(status='EXACT_INCOMPATIBLE', reason=incompatibility, result=None), work)
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
        # Generated exact singleton values can be wider than the input. Getter
        # and conversion scratch for them is already in the screen envelope.
        largest = max(largest, *(sys.getsizeof(value) for value in physical.values())) if physical else largest
        for precision in precisions:
            INVENTORY.check(cancelled)
            attempt = dict(precision_bits=precision)
            began = perf_counter()
            audit['attempts'].append(attempt)
            owner, reason = _attempt(matrix, rhs, keys, base_keys, signed_tau, conversion, physical,
                precision=precision, largest_owned_bytes=largest, budget=budget,
                cancelled=cancelled, audit=audit, resource_evidence=resources['attempts'])
            if owner is not None:
                work.stack.enter_context(owner)
                attempt.update(status='CERTIFIED', seconds=perf_counter()-began)
                # Retain exact screen/audit ownership with the exported result;
                # this intentionally does not credit it as released early.
                return P.OwnedSolve(dict(status='CERTIFIED', result=owner.value, reason=None), work)
            attempt.update(status='UNRESOLVED', reason=reason, seconds=perf_counter()-began)
        return P.OwnedSolve(dict(status='UNRESOLVED', result=None,
            reason='All declared certification precisions exhausted; exact route/refusal required'), work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


