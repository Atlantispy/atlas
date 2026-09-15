"""Versioned prescribed-rate erosion arithmetic successor, not a new law.

Only the inherited interval integrator is replaced in a private function-global
copy. Native input validation, finite layers, scheduled deposition, material/time
accounts and 8192-bit persistent guards remain. Combined mass rate and PARTIAL
requested transfer are each represented once in binary64, with exact applied
stock splits. A bounded unrounded-law shadow carries contact-time effects into
later layers; contact-branch disagreement fails rather than clipping.
"""
from dataclasses import replace
from fractions import Fraction as F
import hashlib
import math
from types import FunctionType

from . import provenance

SCHEMA = 'diadem.layered-landscape-represented-transfer.r14'
PERSISTENT_BITS = 8192
SCRATCH_BITS = 6*PERSISTENT_BITS


def _scratch(value):
    """Bound arithmetic references; this does not expand persistent quantities."""
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > SCRATCH_BITS:
        raise ValueError('erosion exact-reference scratch arithmetic budget exceeded')
    return value


def _reference(value):
    """Keep huge scratch references out of persistent integer/string budgets."""
    value = _scratch(value)
    nb, db = value.numerator.bit_length(), value.denominator.bit_length()
    if max(nb, db) <= PERSISTENT_BITS:
        return str(value)
    numerator = abs(value.numerator).to_bytes(max(1, (nb+7)//8), 'big')
    denominator = value.denominator.to_bytes(max(1, (db+7)//8), 'big')
    raw = (b'-' if value < 0 else b'+')+len(numerator).to_bytes(4, 'big')+numerator+denominator
    return {'representation': 'BOUNDED_EXACT_SCRATCH_REFERENCE_DIGEST',
            'numerator_bits': nb, 'denominator_bits': db,
            'sha256': hashlib.sha256(raw).hexdigest()}


def _upper(value):
    """A finite dyadic upward enclosure, including positive subnormal errors."""
    value = _scratch(value)
    if value < 0:
        raise ValueError('nonnegative error enclosure required')
    if not value:
        return F()
    try:
        rounded = float(value)
    except OverflowError as error:
        raise ValueError('erosion error bound exceeds finite representation') from error
    if not math.isfinite(rounded):
        raise ValueError('erosion error bound exceeds finite representation')
    if F(rounded) < value:
        rounded = math.nextafter(rounded, math.inf)
    if not math.isfinite(rounded) or rounded <= 0:
        raise ValueError('erosion positive error enclosure unrepresentable')
    return F(rounded)


def _error(value):
    return {'represented_minus_reference': _reference(value),
            'absolute_upper_bound': str(_upper(abs(value)))}


def _represented(value, label):
    value = _scratch(value)
    if value <= 0:
        raise ValueError(label+': positive reference required')
    try:
        rounded = float(value)
    except OverflowError as error:
        raise ValueError(label+': binary64 overflow') from error
    if not math.isfinite(rounded) or rounded <= 0:
        raise ValueError(label+': positive branch lost or nonfinite binary64 result')
    represented = F(rounded)
    difference = _scratch(represented-value)
    if abs(difference) > F(math.ulp(rounded))/2:
        raise ValueError(label+': nearest-binary64 half-ULP envelope exceeded')
    return represented, difference


def _branch(request, stock):
    return (request > stock)-(request < stock)


def _metadata(layer):
    return (layer.material_id, layer.grain_density_kg_m3, layer.porosity, layer.phase, layer.evidence)


def _advance(native, state, forcings, laws, duration_years, depositions=()):
    """Internal explicit native binding; useful for arithmetic-only regressions."""
    if native.MAX_EXACT_BITS != PERSISTENT_BITS:
        raise ValueError('native persistent arithmetic envelope differs')
    records, shadows, prior_actual = [], {}, {}

    def interval(column_id, column, begin, end, rates):
        if column_id not in shadows:
            shadow = [(layer, layer.mass_kg) for layer in column.layers]
        else:
            previous = prior_actual[column_id]
            if column.layers[:len(previous.layers)] != previous.layers:
                raise ValueError('unexpected native transition between prescribed deposition intervals')
            # The unchanged outer driver appends each supplied timed pulse.
            shadow = shadows[column_id]+[(layer, layer.mass_kg) for layer in column.layers[len(previous.layers):]]
        clock = reference_clock = begin
        parcels = []
        active = zero_rate = exhausted = F()
        while clock < end:
            if not column.layers:
                if shadow:
                    raise ValueError('represented/reference finite-stock exhaustion differs')
                exhausted += end-clock
                reference_clock = end
                break
            if not shadow or _metadata(column.exposed) != _metadata(shadow[-1][0]):
                raise ValueError('represented/reference exposed material differs')
            layer = column.exposed
            reference_stock = shadow[-1][1]
            erosion_rate = rates[(layer.material_id, layer.phase)]
            if not erosion_rate:
                zero_rate += end-clock
                reference_clock = end
                break
            factors = (erosion_rate, column.area_m2, layer.grain_density_kg_m3, 1-layer.porosity)
            theory_rate = F(1)
            for factor in factors:
                theory_rate = _scratch(theory_rate*factor)
            rate, rate_error = _represented(theory_rate, 'combined erosion mass rate')
            rate = native._quantity(rate, 'represented erosion mass rate', positive=True)
            remaining, reference_remaining = end-clock, end-reference_clock
            if reference_remaining <= 0:
                raise ValueError('represented/reference positive interval branch differs')
            requested = _scratch(rate*remaining)
            reference_request = _scratch(theory_rate*reference_remaining)
            branch = _branch(requested, layer.mass_kg)
            if branch != _branch(reference_request, reference_stock):
                raise ValueError('erosion rounding/contact-time propagation changes a contact branch')
            # No unused far-future contact division is performed for partials.
            if branch >= 0:
                used = native._quantity(layer.mass_kg/rate, 'layer-contact time', positive=True)
                reference_used = _scratch(reference_stock/theory_rate)
                removed, reference_removed = layer.mass_kg, reference_stock
                transfer_error = F()
                kind = 'FULL_CONTACT_EXACT_APPLIED_STOCK'
            else:
                used, reference_used = remaining, reference_remaining
                removed, transfer_error = _represented(requested, 'partial erosion transfer')
                if not 0 < removed < layer.mass_kg:
                    raise ValueError('rounded partial transfer loses a positive branch or crosses a contact')
                reference_removed = reference_request
                kind = 'PARTIAL_BINARY64_REQUEST_EXACT_APPLIED_SPLIT'
            removed = native._quantity(removed, 'removed mass', positive=True)
            after, removal = column.strip_mass(removed)
            if removal['unmet_mass_kg'] or removal['mass_residual_kg'] or len(removal['removed_layers']) != 1:
                raise ArithmeticError('finite contact removal contract failed')
            next_clock = native._quantity(clock+used, 'erosion event time')
            reference_end = _scratch(reference_clock+reference_used)
            if next_clock > end or reference_end > end:
                raise ValueError('erosion contact exceeds interval; no clipping')
            rate_component = _scratch(abs(rate_error)*used)
            transfer_component = abs(transfer_error)
            # This includes all upstream contact-clock shifts, and previous
            # partial-stock errors retained across timed deposition boundaries.
            time_component = _scratch(theory_rate*abs(used-reference_used))
            bound = native._quantity(_upper(_scratch(rate_component+transfer_component+time_component)),
                                     'local mass representation error bound')
            actual_error = _scratch(removed-reference_removed)
            if abs(actual_error) > bound:
                raise ArithmeticError('propagated original-law transfer error escaped enclosure')
            records.append({'column_id': column_id, 'material_id': layer.material_id,
                'source_layer_index': len(column.layers)-1, 'kind': kind,
                'start_year': str(clock), 'end_year': str(next_clock),
                'reference_start_year': _reference(reference_clock), 'reference_end_year': _reference(reference_end),
                'original_rate_factors': {key: str(value) for key, value in zip(
                    ('erosion_m_year', 'area_m2', 'grain_density_kg_m3', 'solid_fraction'), factors)},
                'represented_mass_rate_kg_year': str(rate), 'rate_error_kg_year': _error(rate_error),
                'represented_rate_requested_mass_kg': _reference(_scratch(rate*used)),
                'applied_mass_kg': str(removed), 'reference_applied_mass_kg': _reference(reference_removed),
                'partial_transfer_error_kg': _error(transfer_error),
                'propagated_contact_clock_shift_year': _error(_scratch(next_clock-reference_end)),
                'mass_rate_error_component_bound_kg': str(_upper(rate_component)),
                'partial_transfer_error_component_bound_kg': str(_upper(transfer_component)),
                'contact_time_propagation_component_bound_kg': str(_upper(time_component)),
                'original_law_transfer_error_kg': _error(actual_error),
                'mass_representation_error_bound_kg': str(bound),
                'original_and_represented_contact_branch_agree': True})
            if len(records) > native.MAX_TOTAL_LAYERS*(len(depositions)+1):
                raise ValueError('bounded erosion interval record inventory exceeded')
            if branch >= 0:
                shadow.pop()
            else:
                remaining_shadow = _scratch(reference_stock-reference_removed)
                if remaining_shadow <= 0:
                    raise ValueError('original-law partial layer lost positive retained stock')
                shadow[-1] = (shadow[-1][0], remaining_shadow)
            parcels.append(native.ErodedParcel(column_id, clock, next_clock, removal['removed_layers'][0]))
            active += used
            column, clock, reference_clock = after, next_clock, reference_end
        if active+zero_rate+exhausted != end-begin:
            raise ArithmeticError('erosion interval time budget failed to close')
        shadows[column_id], prior_actual[column_id] = shadow, column
        return column, parcels, (active, zero_rate, exhausted)

    globals_copy = dict(native.advance.__globals__, _evolve_interval=interval)
    inherited = FunctionType(native.advance.__code__, globals_copy, 'r14_inherited_advance',
                             native.advance.__defaults__, native.advance.__closure__)
    inherited.__kwdefaults__ = native.advance.__kwdefaults__
    result = inherited(state, forcings, laws, duration_years, depositions)
    total = native._quantity(sum((F(row['mass_representation_error_bound_kg']) for row in records), F()),
                             'aggregate mass representation error bound')
    receipt = dict(result.receipt, schema=SCHEMA,
        contact_solver='R14 represented combined mass rate and partial transfer; exact applied full contacts; bounded unrounded-law shadow/contact-branch gate',
        numerical_representation=records, local_mass_representation_error_bound_kg=str(total),
        representation_bound_scope='Sum of per-transfer absolute error enclosures against the unrounded prescribed-law call, including propagated contact-time/stock effects. Bounds each final-stock or exported-material L1 error separately. Not a global nonlinear landscape or empirical error bound.',
        persistent_arithmetic_bits=PERSISTENT_BITS, scratch_reference_arithmetic_bits=SCRATCH_BITS,
        retained_outer_algorithm='Unchanged native validation, forcing law, deposition ordering, finite types and exact accounts; private globals composition only',
        retained_landscape_source=str(native.__file__),
        retained_landscape_sha256=hashlib.sha256(provenance.checked(native.__file__)).hexdigest())
    return replace(result, receipt=receipt)


def advance(state, forcings, laws, duration_years, depositions=()):
    """Public same-native-types interface; no predecessor module is modified."""
    _, tt = provenance.backend()
    tt.verify()
    result = _advance(tt.landscape, state, forcings, laws, duration_years, depositions)
    provenance.verify_backend()
    return result
