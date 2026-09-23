"""Whole-column finite-plate thermal changes, without an age-by-depth field.

This is an integral of the W03 constant-property conduction solution. It supplies
temperature change only: density, compensation and vertical-support ownership
belong to the caller. No age, boundary temperature or mass inventory is changed.
"""
from __future__ import annotations

import math

import numpy as np

from ._validation import TectonicsError, frozen, input_shape, read_array
from .parameters import PlateCoolingParameters
from .plate_cooling import _cancel, _erfc_mean, _fourier_age, _IMAGE_LIMIT, _MODES
from .resources import elements, select_budget
from .stokes_execution import _factored_scale
from .thermal import _batch_count


def _deficit(fourier_age, erfc):
    """Mean of 1-theta, including the exactly hot initial column.

    At F<=1/16, integrating the retained image pairs gives five alternating
    unit intervals. For F>1/16 only odd eigenfunctions have nonzero column means;
    the first omitted n=11 term is below 1.4e-35 at the switch.
    """
    result = np.zeros_like(fourier_age)
    young = (fourier_age > 0) & (fourier_age <= _IMAGE_LIMIT)
    if np.any(young):
        scale = 2*np.sqrt(fourier_age[young])
        value = np.zeros_like(scale)
        for image in range(5):
            value += (-1)**image*_erfc_mean(image/scale, (image+1)/scale, erfc)
        result[young] = value
    old = fourier_age > _IMAGE_LIMIT
    if np.any(old):
        age = fourier_age[old]
        value = np.full_like(age, .5)
        for n in range(1, _MODES+1, 2):
            rate = n*n*math.pi**2
            with np.errstate(over='ignore'):
                value -= (4/rate)*np.exp(-rate*age)
        result[old] = value
    return result


def _mature_change(low, delta, temperature_span):
    """Positive cooling increment without subtracting two steady-state limits.

    Scale each exponential before multiplying by its small age increment. Refuse
    an unrepresentable leading mode rather than silently returning zero for an
    unequal pair of mature ages. Negligible higher modes may underflow normally.
    """
    result = np.zeros_like(low)
    for n in range(1, _MODES+1, 2):
        rate = n*n*math.pi**2
        with np.errstate(over='ignore', under='ignore'):
            decay = np.exp(-rate*low)
            increment = -np.expm1(-rate*delta)
        if n == 1 and np.any(decay == 0):
            raise TectonicsError('mature plate change has an unrepresentable leading transient')
        # Higher modes below representable range cannot affect a retained n=1
        # term; do not reject an otherwise resolved result merely for their tail.
        active = decay > 0
        if not np.any(active):
            continue
        with np.errstate(under='ignore'):
            if n == 1:
                scaled = _factored_scale(decay, (temperature_span, 4/rate), (),
                                         'mature plate temperature change')
            else:
                # All temperatures are nonnegative, so span*4/rate is finite.
                scaled = decay*(temperature_span*(4/rate))
            term = scaled*increment
        if n == 1 and np.any((term == 0) & (scaled != 0) & (increment != 0)):
            raise TectonicsError('mature plate temperature change underflows binary64 output')
        result += term
    return result


def plate_cooling_deficit_change(age_s, reference_age_s,
        parameters: PlateCoolingParameters, *, budget=None, batch_elements=8192,
        cancel=None):
    """Immutable broadcast mean(T_reference - T_current), in kelvin.

    Cooling is positive; a later reference age gives a negative change. Both
    ages use the same finite plate, fixed boundary temperatures and SI seconds.
    Equal ages and isothermal plates return exactly zero. The mature branch
    preserves tiny increments with expm1; young/mixed differences have the
    absolute accuracy of the underlying dimensionless deficit evaluation.

    Full input captures and output are admitted before allocation; scratch is
    bounded by batch_elements. No depth sampling or hidden geological age floor.
    """
    if type(parameters) is not PlateCoolingParameters:
        raise TectonicsError('explicit PlateCoolingParameters required')
    _cancel(cancel)
    batch = _batch_count(batch_elements)
    age_shape = input_shape(age_s, 'age_s')
    reference_shape = input_shape(reference_age_s, 'reference_age_s')
    try:
        shape = np.broadcast_shapes(age_shape, reference_shape)
    except ValueError as exc:
        raise TectonicsError('plate cooling ages cannot broadcast') from exc
    size = elements(shape)
    if not size:
        raise TectonicsError('nonempty plate cooling ages required')
    required = (32*(elements(age_shape)+elements(reference_shape))
                + 24*size + 512*min(batch, size) + 8192)
    with select_budget(budget).reserve(required, category='plate-integrals'):
        age = read_array(age_s, 'age_s', nonnegative=True)
        reference = read_array(reference_age_s, 'reference_age_s', nonnegative=True)
        if age.shape != age_shape or reference.shape != reference_shape:
            raise TectonicsError('plate cooling age shape changed during capture')
        output = np.zeros(shape)
        thermal = parameters.thermal
        span = thermal.mantle_temperature_k-thermal.surface_temperature_k
        if span == 0:
            return frozen(output)
        try:
            from scipy.special import erfc
        except ImportError as exc:
            raise TectonicsError('plate cooling requires the declared SciPy dependency') from exc
        with np.nditer([age, reference, output], flags=['external_loop', 'buffered'],
                op_flags=[['readonly'], ['readonly'], ['writeonly', 'no_broadcast']],
                order='C', buffersize=min(batch, size)) as iterator:
            for current, baseline, target in iterator:
                _cancel(cancel)
                target[:] = 0.
                different = current != baseline
                if not np.any(different):
                    continue
                a = current[different]; b = baseline[different]
                first = np.minimum(a, b); last = np.maximum(a, b)
                low = _fourier_age(first, parameters)
                high = _fourier_age(last, parameters)
                values = np.empty_like(low)
                mature = low > _IMAGE_LIMIT
                if np.any(mature):
                    # Subtract physical ages first: rounding two large scaled
                    # Fourier ages independently can erase an input increment.
                    delta = _fourier_age(last[mature]-first[mature], parameters)
                    values[mature] = _mature_change(low[mature], delta, span)
                other = ~mature
                if np.any(other):
                    change = _deficit(high[other], erfc)-_deficit(low[other], erfc)
                    values[other] = _factored_scale(change, (span,), (),
                                                   'plate temperature change')
                target[different] = np.where(a > b, values, -values)
        return frozen(output)
