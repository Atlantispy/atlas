"""Owned structured interval assessment with exact fast Decimal80 conversion.

Same r1 certificate, screen and declared precision ladder. Expected exhaustion
or exact incompatibility returns an owned status rather than leaking traceback
lifetimes into rank fallback. Successful result is numerically identical.
Conversion scratch is derived before MPFR endpoint export; no giant Decimal
integer is needed under clamp=0. Other contexts retain the original route.
Not a complete reconstruction, native method or allocator/RSS proof.
"""
from decimal import localcontext, ROUND_HALF_EVEN
import sys
from time import perf_counter

from atlas_tectonics._private import private_heat_certification_kernel_r1 as K
from atlas_tectonics._private.integration.heat import certification_resources as INVENTORY
from atlas_tectonics._private import private_heat_decimal_sparse_core_r1 as P
from atlas_tectonics._private.integration.heat import rational_decimal_kernel as DECIMAL
from atlas_tectonics._private.integration.heat import low_ledger_inventory as L

G = K.G
Unresolved = K.Unresolved
ExactIncompatibility = K.ExactIncompatibility
PRECISIONS = K.PRECISIONS



def _round_bounds(bounds, cancelled, *, _return_exact=False):
    lo, hi = bounds
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_HALF_EVEN
        exact_lo = G.mpq(lo)
        a = DECIMAL.dec(exact_lo, context=context, cancelled=cancelled)
    if hi is lo and cancelled is None:
        exact_hi, b = exact_lo, a
    else:
        with localcontext() as context:
            context.prec = 80
            context.rounding = ROUND_HALF_EVEN
            exact_hi = exact_lo if hi is lo else G.mpq(hi)
            b = DECIMAL.dec(exact_hi, context=context, cancelled=cancelled)
    if a != b or (a.is_zero() and a.is_signed() != b.is_signed()):
        raise Unresolved('Enclosure crosses a Decimal80 rounding boundary')
    return (a, (exact_lo, exact_hi)) if _return_exact else a


def _export_plan(bounds, dual, proof, R, cancelled, *, retain_decimal=True):
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_HALF_EVEN
        if context.clamp:
            return INVENTORY.export_plan(bounds, dual, proof, G, R, cancelled, retain_decimal=retain_decimal)
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
            slot = ar.slot(shape)
            retained += slot
            scratch += 8*slot
            largest_bits = max(largest_bits, shape.numerator, shape.denominator)
            count += 1
    for value in proof.values():
        if type(value) is G.mpfr:
            shape = INVENTORY.endpoint_shape(value, G, ar)
            retained += ar.slot(shape)
            largest_bits = max(largest_bits, shape.numerator, shape.denominator)
    converter_bits = (5*largest_bits+4*positive_tiny+512)
    # pow10, product, quotient/remainder, num_digits and comparison temporaries
    # plus endpoint getters are sequential; reserve their simultaneous slots.
    scratch += 48*R.native_slot_allowance(R.RationalShape(converter_bits, converter_bits))
    retained += INVENTORY.D.CONTAINER_UNIT*(8*len(bounds)+4*len(dual)+64)
    if retain_decimal:
        retained += len(bounds)*INVENTORY.D.decimal_slot(80)
    elif bounds:
        scratch += 2*INVENTORY.D.decimal_slot(80)
    return INVENTORY.Plan('exact-dyadic-export-and-fast-rounding', (
        ('retained_values_and_output_containers', retained),
        ('simultaneous_export_decimal_copies', scratch),
        ('scalar_export_workspace', R.native_workspace_allowance(converter_bits, 64))),
        (('endpoint_values', count), ('largest_export_bits', largest_bits),
         ('converter_scalar_bits', converter_bits)))

def _attempt(matrix, rhs, keys, base_keys, signed_tau, conversion, physical, *,
             precision, largest_owned_bytes, budget, cancelled, audit, resource_evidence, keys_unique=False,
             private_output=False, retain_decimal=True):
    """One isolated frame; normal refusal cannot retain prior numerical locals."""
    from atlas_tectonics._private.integration.heat import gmp_resources as R
    plan = INVENTORY.interval_plan(len(matrix), len(rhs), precision, largest_owned_bytes, R)
    work = R.OwnedWorkspace(budget, plan.total, category='heat-functional-interval-'+str(precision),
                            cancelled=cancelled)
    work.__enter__()
    dual = ar = proof = bounds = rounded = result = export = exact_bounds = None
    reason = None
    try:
        try:
            dual, ar, proof = K.solve_enclosure(matrix, rhs, precision=precision,
                                                cancelled=cancelled, evidence=audit)
            bounds = K.physical_bounds(matrix, dual, keys, base_keys, signed_tau, conversion, ar,
                                       _keys_unique=keys_unique)
            for key, value in physical.items():
                ar.check('exact-singleton-moment-refinement')
                bounds[key] = value, value
            export = _export_plan(bounds, () if private_output else dual, proof, R, cancelled,
                                  retain_decimal=retain_decimal)
            if private_output and cancelled is not None:
                # The private fit exports no dual endpoints. Preserve their
                # existing cancellation opportunities without sizing copies.
                for _ in range(2*len(dual)):
                    INVENTORY.check(cancelled)
            # All prior MPFR values remain live. Exact export, int/Decimal
            # scratch and retained values are an ADDITION, not a replacement.
            work.resize_before_allocation_or_after_drop(plan.total+export.total)
            def exact_pair(value):
                INVENTORY.check(cancelled)
                return tuple(map(G.mpq, value))
            rounded = {} if retain_decimal else None
            # A standalone caller's callback can observe the original two export stages.
            exact_bounds = None if not private_output and cancelled is not None else {}
            for key, value in bounds.items():
                INVENTORY.check(cancelled)
                if exact_bounds is None:
                    rounded[key] = _round_bounds(value, cancelled)
                elif rounded is None:
                    exact_bounds[key] = _round_bounds(value, cancelled, _return_exact=True)[1]
                else:
                    rounded[key], exact_bounds[key] = _round_bounds(value, cancelled, _return_exact=True)
            proof['exact_singleton_observation_coefficients'] = len(physical)
            if exact_bounds is None:
                exact_bounds = {key: exact_pair(bound) for key, bound in bounds.items()}
            elif cancelled is not None:
                export_checks = len(bounds) + (len(dual) if private_output else 0)
                for _ in range(export_checks):
                    INVENTORY.check(cancelled)
            result = dict(keys=list(bounds), bounds=exact_bounds)
            if retain_decimal:
                result['decimal80'] = rounded
            result.update(precision_bits=precision, proof=proof)
            if not private_output:
                result['dual_bounds'] = [exact_pair(bound) for bound in dual]
        except Unresolved as error:
            reason = str(error)
        # The loop target otherwise keeps the last MPFR enclosure through
        # an ordinary precision retry or the successful reservation shrink.
        value = None
        if reason is not None:
            # Expected refusal is NOT exposed as an exception object. The except
            # suite has cleared error/traceback, and all surviving return locals
            # are dropped before a successful close releases their reservation.
            dual = ar = proof = bounds = rounded = result = export = exact_bounds = None
            work.__exit__(None, None, None)
            resource_evidence.append(dict(precision_bits=precision, admitted_bytes=plan.total,
                status='REFUSED_AND_DROPPED_BEFORE_NEXT_ATTEMPT'))
            return None, reason
        # Result retains only exact endpoints, Decimal values, proof scalars and
        # small containers. Drop MPFR dual/physical arrays and Arithmetic contexts
        # before shrinking. result still owns proof/rounded and is funded below.
        dual = ar = proof = bounds = rounded = exact_bounds = None
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
                      precisions=PRECISIONS, cancelled=None, evidence=None, resource_evidence=None,
                      _sizing=None, _keys_unique=False, _private_output=False):
    """Owned same-weight interval certificate; borrow result only while live.

    Inputs must be immutable during the call and already owned exact GMP/int
    operands. Default precision ladder is unchanged; explicitly supplied ladders
    retain the original API semantics, not an implicit precision relaxation.
    Source-bound metadata sizes precede exact screen, interval and export work.
    """
    K._require_gmp()
    INVENTORY.check(cancelled)
    from atlas_tectonics._private.integration.heat import gmp_resources as R
    metadata, largest = (_sizing if _sizing is not None else
        INVENTORY.metadata_bytes(matrix, rhs, conversion, signed_tau, G, cancelled))
    work = R.OwnedWorkspace(budget, metadata, category='heat-functional-screen-and-metadata', cancelled=cancelled)
    work.__enter__()
    try:
        # No copied key set, source audit or exact coefficient until admitted.
        screen, support = INVENTORY.screen_plan(matrix, rhs, conversion, signed_tau, G, R, cancelled,
                                                _with_support=True)
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
            forced = K.forced_coefficients(matrix, rhs, cancelled=cancelled, evidence=audit['singleton_moments'],
                                           _support=support)
        except K.InconsistentConstraints as error:
            incompatibility = str(error)
        finally:
            for witness in audit['singleton_moments'].get('witnesses', []):
                for name in ('coefficient', 'target', 'forced_value'):
                    witness[name] = K.qhex(witness[name])
            audit['singleton_moments']['scalar_encoding'] = 'canonical signed-hex rational pairs'
        if incompatibility is not None:
            return P.OwnedSolve(dict(status='EXACT_INCOMPATIBLE', reason=incompatibility, result=None), work)
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
        INVENTORY.check(cancelled)
        column = K.nought_column(matrix)
        if column is not None:
            # A nought column of M: singular at every precision, so all rungs go (ladder-unresolved.md :37).
            audit['attempts'].append(dict(status='UNRESOLVED', proof='nought-column', column=column))
            precisions = ()
        for precision in precisions:
            INVENTORY.check(cancelled)
            attempt = dict(precision_bits=precision)
            began = perf_counter()
            audit['attempts'].append(attempt)
            owner, reason = _attempt(matrix, rhs, keys, base_keys, signed_tau, conversion, physical,
                precision=precision, largest_owned_bytes=largest, budget=budget,
                cancelled=cancelled, audit=audit, resource_evidence=resources['attempts'], keys_unique=True,
                private_output=_private_output, retain_decimal=not _private_output)
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


