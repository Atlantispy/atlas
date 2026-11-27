"""Independent scalar birth-trajectory integration for the W06 Step-2 case.

No Atlas/production imports. A parcel is born at the moving ridge at tau, then
moves at its plate velocity until the requested time. Integrate the birth-time
preimage of each cell, rather than clipping production strips in spatial order.
Two-point Gauss integration gives exact first/second birth-time moments for this
affine family. No time samples, age bins or thermal approximations are involved.
"""
import math

import numpy as np


def _inputs(edges_m, elapsed_s, ridge_position_m, left_velocity_m_s,
            right_velocity_m_s, ridge_velocity_m_s):
    edges = np.asarray(edges_m, dtype=np.float64)
    values = tuple(map(float, (elapsed_s, ridge_position_m, left_velocity_m_s,
                              right_velocity_m_s, ridge_velocity_m_s)))
    if (edges.ndim != 1 or len(edges) < 2 or not np.isfinite(edges).all()
            or np.any(np.diff(edges) <= 0) or not all(map(math.isfinite, values))):
        raise ValueError('finite increasing edges and finite motion/time required')
    time, ridge, left, right, moving = values
    if time < 0 or not left <= 0 <= right or not left < moving < right:
        raise ValueError('nonnegative time and supported outward active motion required')
    return edges, time, ridge, left, right, moving


def parcel_position_m(birth_offset_s, elapsed_s, *, ridge_position_m,
                      ridge_velocity_m_s, plate_velocity_m_s):
    """Evaluate the two successive pieces of one parcel path in scalar form."""
    tau, time = float(birth_offset_s), float(elapsed_s)
    if not 0 <= tau <= time:
        raise ValueError('birth must be within the event and output time')
    at_birth = float(ridge_position_m) + float(ridge_velocity_m_s)*tau
    return at_birth + float(plate_velocity_m_s)*(time-tau)


def _birth_preimage(cell_left, cell_right, time, ridge, moving, plate):
    # x(t;tau) = x(t;0) + (v_r-u)*tau. Solve both scalar boundary
    # crossings, then restrict their birth times to the supplied onset interval.
    first_position = parcel_position_m(0., time, ridge_position_m=ridge,
        ridge_velocity_m_s=moving, plate_velocity_m_s=plate)
    derivative = moving-plate
    crossings = ((float(cell_left)-first_position)/derivative,
                 (float(cell_right)-first_position)/derivative)
    low = max(0., min(crossings))
    high = min(time, max(crossings))
    return (low, high) if high > low else None


def _preimages(edges, time, ridge, left, right, moving):
    for side, plate in enumerate((left, right)):
        rate = abs(moving-plate)
        for cell in range(len(edges)-1):
            interval = _birth_preimage(edges[cell], edges[cell+1], time,
                                       ridge, moving, plate)
            if interval is not None:
                yield side, cell, rate, interval


def reference_geometry(edges_m, elapsed_s, *, ridge_position_m,
                       left_velocity_m_s, right_velocity_m_s, ridge_velocity_m_s):
    """Return (side, cell, [occupied width, youngest age, oldest age])."""
    args = _inputs(edges_m, elapsed_s, ridge_position_m, left_velocity_m_s,
                   right_velocity_m_s, ridge_velocity_m_s)
    result = np.zeros((2, len(args[0])-1, 3), dtype=np.float64)
    for side, cell, rate, (low, high) in _preimages(*args):
        result[side, cell] = (rate*(high-low), args[1]-high, args[1]-low)
    return result


def reference_birth_moments(edges_m, elapsed_s, *, ridge_position_m,
                           left_velocity_m_s, right_velocity_m_s, ridge_velocity_m_s):
    """Width-integrated tau and tau**2, from independent birth-time quadrature.

    The times are offsets from the event epoch, not absolute timestamps. Empty
    intersections have zero moments; the geometry's positive width is validity.
    """
    args = _inputs(edges_m, elapsed_s, ridge_position_m, left_velocity_m_s,
                   right_velocity_m_s, ridge_velocity_m_s)
    result = np.zeros((2, len(args[0])-1, 2), dtype=np.float64)
    for side, cell, rate, (low, high) in _preimages(*args):
        middle = .5*low + .5*high
        half = .5*(high-low)
        nodes = (middle-half/math.sqrt(3.), middle+half/math.sqrt(3.))
        result[side, cell, 0] = rate*half*math.fsum(nodes)
        result[side, cell, 1] = rate*half*math.fsum(x*x for x in nodes)
    return result


def reference_accounts(edges_m, elapsed_s, phases, *, width_m,
                       ridge_position_m, left_velocity_m_s,
                       right_velocity_m_s, ridge_velocity_m_s):
    """Mass accounts integrated over births and boundary-crossing preimages.

    Columns: created, remaining feed, represented, left export, right export,
    balance residual. Exports are computed directly from trajectories beyond
    each boundary; they are never a leftover obtained by subtracting cell mass.
    """
    edges, time, ridge, left, right, moving = _inputs(
        edges_m, elapsed_s, ridge_position_m, left_velocity_m_s,
        right_velocity_m_s, ridge_velocity_m_s)
    width = float(width_m)
    if not math.isfinite(width) or width <= 0:
        raise ValueError('positive finite strike width required')
    regions = ((edges[0], edges[-1]), (-math.inf, edges[0]), (edges[-1], math.inf))
    region_widths = [[], [], []]
    created_widths = []
    for plate in (left, right):
        rate = abs(moving-plate)
        created_widths.append(rate*time)
        for index, (low, high) in enumerate(regions):
            interval = _birth_preimage(low, high, time, ridge, moving, plate)
            region_widths[index].append(0. if interval is None else rate*(interval[1]-interval[0]))
    lengths = (math.fsum(created_widths), *(math.fsum(x) for x in region_widths))
    result = np.empty((len(phases), 6), dtype=np.float64)
    for index, phase in enumerate(phases):
        density, thickness, stock = (float(phase[name]) for name in
                                     ('density_kg_m3', 'thickness_m', 'stock_kg'))
        factor = density*thickness*width
        created, represented, out_left, out_right = (factor*x for x in lengths)
        result[index] = (created, stock-created, represented, out_left, out_right,
                        math.fsum((created, -represented, -out_left, -out_right)))
    return result
