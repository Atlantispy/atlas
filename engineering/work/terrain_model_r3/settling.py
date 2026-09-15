"""Positive, closed-pool settling on a supplied heterogeneous nonporous bed.

Pure standard-library reference. Caller owns pool connectivity, mixing and
velocity applicability. No routing, imports, exports, erosion or authorisation.
"""
from __future__ import annotations

import math

MAX_CELLS = 4096
MAX_BRACKET_STEPS = 64
MAX_BISECTIONS = 128
VOLUME_ATOL_M3 = 1e-9
VOLUME_RTOL = 1e-12
HEIGHT_ATOL_M = 1e-9
HEIGHT_RTOL = 1e-11


class SettlingError(ValueError):
    pass


def _number(value, name, *, positive=False, signed=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SettlingError(name + ": finite numeric scalar required")
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise SettlingError(name + ": unrepresentable scalar") from exc
    if not math.isfinite(value) or (not signed and value < 0) or (positive and value <= 0):
        raise SettlingError(name + ": outside numerical domain")
    return value


def _sum(values, name="sum"):
    try:
        value = math.fsum(values)
    except (ValueError, OverflowError) as exc:
        raise SettlingError(name + ": unrepresentable sum") from exc
    return _number(value, name, signed=True)


def _product(a, b, name):
    value = a * b
    if not math.isfinite(value) or (a != 0 and b != 0 and value == 0):
        raise SettlingError(name + ": product overflow/underflow")
    return value


def _quotient(a, b, name):
    value = a / b
    if not math.isfinite(value) or (a != 0 and value == 0):
        raise SettlingError(name + ": quotient overflow/underflow")
    return value


def _volume_tolerance(*values):
    return VOLUME_ATOL_M3 + VOLUME_RTOL * max((abs(v) for v in values), default=0.)


def _check_volume(residual, *scale):
    if abs(residual) > _volume_tolerance(*scale):
        raise SettlingError("phase/geometric volume residual exceeds frozen tolerance")


def _stage(bed, area, volume):
    """Direct sorted area-depth inversion; no topographic filling or connectivity inference."""
    if volume == 0:
        return None, [0.] * len(bed), 0.
    ordered = sorted(range(len(bed)), key=lambda i: (bed[i], i))
    floor = bed[ordered[0]]
    position = 0
    level = floor
    active = []
    remaining = volume
    while position < len(ordered):
        while position < len(ordered) and bed[ordered[position]] == level:
            active.append(area[ordered[position]])
            position += 1
        wet_area = _sum(active, "wet area")
        if position == len(ordered):
            stage = _sum([level, _quotient(remaining, wet_area, "pool depth")], "stage")
            break
        next_level = bed[ordered[position]]
        rise = _sum([next_level, -level], "bed relief")
        capacity = _product(wet_area, rise, "capacity interval")
        if remaining <= capacity:
            stage = _sum([level, _quotient(remaining, wet_area, "pool depth")], "stage")
            break
        remaining = _sum([remaining, -capacity], "unallocated volume")
        level = next_level
    if stage <= floor:
        raise SettlingError("positive volume has no representable wet depth")
    depth = [max(0., _sum([stage, -z], "depth")) for z in bed]
    represented = _sum((_product(a, h, "cell mixture volume") for a, h in zip(area, depth)), "pool volume")
    if represented <= 0:
        raise SettlingError("positive volume has zero geometric wet area/volume")
    residual = _sum([represented, -volume], "geometry residual")
    _check_volume(residual, volume, represented)
    return stage, depth, residual


def _phase_allocation(amount, cells):
    """Well-mixed allocation with a disclosed, bounded rounding remainder."""
    if amount == 0:
        return [0.] * len(cells), 0.
    total = _sum(cells, "mixture volume")
    if total <= 0:
        raise SettlingError("positive phase in empty geometry")
    values = [_product(amount, _quotient(v, total, "cell volume fraction"), "cell phase") if v else 0.
              for v in cells]
    correction = _sum([amount, -_sum(values)], "phase allocation adjustment")
    if abs(correction) > 64 * math.ulp(amount):
        raise SettlingError("phase allocation needs more than rounding adjustment")
    index = max(range(len(cells)), key=lambda i: (cells[i], -i))
    values[index] = _sum([values[index], correction], "allocated phase")
    if min(values) < 0:
        raise SettlingError("negative allocated phase")
    _check_volume(_sum([_sum(values), -amount]), amount)
    return values, correction


def _depletion_function(log_ratio, water, suspension):
    # Internal +inf is only an upper bracket, never a returned state.
    a = water * log_ratio
    b = suspension * -math.expm1(-log_ratio)
    if not math.isfinite(a) or not math.isfinite(b):
        return math.inf
    try:
        return math.fsum((a, b))
    except OverflowError:
        return math.inf


def _settle_fixed_area(water, suspension, rate_area, elapsed):
    """Solve in r=-log(S1/S0), preserving small positive deposition via expm1."""
    target = _product(rate_area, elapsed, "settling volume-time target")
    lower_scale = _quotient(target, _sum([water, suspension]), "log depletion scale")
    cap = math.log(suspension) - math.log(math.ulp(0.))
    if cap <= 0:
        raise SettlingError("positive settling has no representable remaining suspension")
    high = min(cap, lower_scale * 2 if lower_scale <= cap / 2 else cap)
    bracket_steps = 0
    while _depletion_function(high, water, suspension) < target:
        if high == cap or bracket_steps >= MAX_BRACKET_STEPS:
            raise SettlingError("remaining suspension underflows or bracket budget exhausted")
        high = min(cap, high * 2)
        bracket_steps += 1
    low = 0.
    iterations = 0
    for iterations in range(1, MAX_BISECTIONS + 1):
        middle = low + (high - low) / 2
        if middle == low or middle == high:
            break
        if _depletion_function(middle, water, suspension) < target:
            low = middle
        else:
            high = middle
    else:
        raise SettlingError("positive scalar solve exhausted bisection budget")
    r = min((low, high), key=lambda x: abs(_depletion_function(x, water, suspension) - target))
    if r <= 0:
        raise SettlingError("positive settling change is below scalar resolution")
    deposited = _product(suspension, -math.expm1(-r), "deposited suspension")
    remaining = (suspension * math.exp(-r) if r < 500 else math.exp(math.log(suspension) - r))
    if not 0 < remaining <= suspension or deposited <= 0:
        raise SettlingError("remaining suspension or deposition is unrepresentable")
    phase_residual = _sum([remaining, deposited, -suspension], "scalar phase residual")
    _check_volume(phase_residual, deposited)
    equation_residual = _sum([_depletion_function(r, water, suspension), -target], "scalar equation residual")
    _check_volume(equation_residual, target)
    return remaining, deposited, equation_residual, iterations, bracket_steps


def _event_time(water, suspension, deposit, rate_area):
    remaining = _sum([suspension, -deposit], "event suspension")
    if not 0 < deposit < suspension or remaining <= 0:
        raise SettlingError("settling drying event is not finite")
    ratio = _quotient(deposit, suspension, "event depleted fraction")
    log_ratio = -math.log1p(-ratio) if ratio < 1 else math.log(suspension) - math.log(remaining)
    numerator = _sum([_product(water, log_ratio, "event logarithmic volume"), deposit])
    return _quotient(numerator, rate_area, "drying event time"), remaining


def settle_pool(bed_m, area_m2, liquid_m3, suspended_solid_m3, settling_m_year, elapsed_years,
                *, stop_at_first_drying_event=False):
    """Advance one already-identified closed, well-mixed, nonporous level pool.

    Input cell order is preserved. Connectivity and velocity applicability are
    caller declarations, not inferred here. A topology-aware caller should set
    stop_at_first_drying_event=True and check positive-depth connectivity before
    advancing the returned remaining_years. Default continuation requires that
    the supplied pool stays connected and mixed after all drying events.
    No input mutation or file I/O.
    """
    if not isinstance(bed_m, (list, tuple)) or not 1 <= len(bed_m) <= MAX_CELLS:
        raise SettlingError("requires 1..4096 supplied pool cells")
    if not isinstance(area_m2, (list, tuple)) or len(area_m2) != len(bed_m):
        raise SettlingError("bed/area shape mismatch")
    if type(stop_at_first_drying_event) is not bool:
        raise SettlingError("stop_at_first_drying_event: boolean required")
    bed = [_number(v, "bed", signed=True) for v in bed_m]
    area = [_number(v, "area", positive=True) for v in area_m2]
    water = _number(liquid_m3, "liquid volume")
    initial_s = _number(suspended_solid_m3, "suspended volume")
    velocity = _number(settling_m_year, "effective settling velocity")
    elapsed = _number(elapsed_years, "elapsed years")
    if water == 0 and initial_s > 0:
        raise SettlingError("dry suspension requires a separate emplacement transfer")
    initial_volume = _sum([water, initial_s], "initial mixture volume")
    stage, original_depth, initial_geometry = _stage(bed, area, initial_volume)
    groups = []
    for i in sorted((i for i, h in enumerate(original_depth) if h > 0), key=lambda i: (original_depth[i], i)):
        if not groups or groups[-1][0] != original_depth[i]:
            groups.append([original_depth[i], []])
        groups[-1][1].append(i)
    suffix_area = [0.] * (len(groups) + 1)
    for j in range(len(groups) - 1, -1, -1):
        suffix_area[j] = _sum([suffix_area[j + 1], *[area[i] for i in groups[j][1]]], "active wet area")
    suspension = initial_s
    rise = 0.
    time_left = elapsed
    event_records = []
    event_intervals = []
    stopped = False
    iterations = bracket_steps = 0
    equation_residuals = []
    if velocity > 0 and elapsed > 0 and initial_s > 0:
        if not groups or suffix_area[0] <= 0:
            raise SettlingError("positive suspension with no wet geometry")
        for j, (threshold, indices) in enumerate(groups):
            wet_area = suffix_area[j]
            rate_area = _product(velocity, wet_area, "settling velocity times area")
            event_deposit = _product(wet_area, _sum([threshold, -rise]), "drying event deposit")
            event = None
            if 0 < event_deposit < suspension:
                event = _event_time(water, suspension, event_deposit, rate_area)
            if event is not None and event[0] <= time_left:
                event_elapsed, suspension = event
                time_left = _sum([time_left, -event_elapsed], "remaining time")
                rise = threshold
                event_intervals.append(event_elapsed)
                event_records.append({"time_years": _sum(event_intervals, "event time"),
                    "dried_cells": indices.copy(), "wet_area_before_m2": wet_area,
                    "deposited_solid_m3": event_deposit})
                if stop_at_first_drying_event:
                    stopped = True
                    break
                if time_left == 0:
                    break
            else:
                suspension, deposit, residual, count, brackets = _settle_fixed_area(
                    water, suspension, rate_area, time_left)
                delta = _quotient(deposit, wet_area, "bed rise")
                rise = _sum([rise, delta], "cumulative bed rise")
                if rise >= threshold:
                    raise SettlingError("unresolved drying threshold at floating-point precision")
                equation_residuals.append(residual)
                iterations += count
                bracket_steps += brackets
                time_left = 0.
                break
        if time_left > 0 and not stopped:
            raise SettlingError("positive water lost all wet cells or event budget exhausted")
    # A zero-forcing interval still elapses; an event-limited interval stops
    # at its measured event, without a hidden subsequent partial update.
    elapsed_used = _sum(event_intervals, "elapsed event time") if stopped else elapsed
    remaining_time = time_left if stopped else 0.
    increments = [min(rise, h) for h in original_depth]
    deposits = [_product(a, h, "cell deposit") for a, h in zip(area, increments)]
    new_bed = [z if inc == 0 else stage if inc == old_depth else _sum([z, inc], "new bed")
               for z, inc, old_depth in zip(bed, increments, original_depth)]
    if any(d > 0 and new == old for d, new, old in zip(deposits, new_bed, bed)):
        raise SettlingError("positive deposition cannot be represented at the supplied vertical datum")
    depth = [0.] * len(bed) if stage is None else [max(0., _sum([stage, -z])) for z in new_bed]
    cells = [_product(a, h, "resulting cell mixture volume") for a, h in zip(area, depth)]
    remaining_volume = _sum([water, suspension])
    geometry = _sum([_sum(cells), -remaining_volume])
    total_deposit = _sum(deposits)
    solid_residual = _sum([suspension, total_deposit, -initial_s])
    represented_deposit = _sum(_product(a, _sum([new, -old]), "represented bed solid")
                               for a, old, new in zip(area, bed, new_bed))
    representation_residual = _sum([represented_deposit, -total_deposit])
    _check_volume(geometry, remaining_volume)
    _check_volume(solid_residual, total_deposit)
    _check_volume(representation_residual, total_deposit)
    recomputed_stage, _, _ = _stage(new_bed, area, remaining_volume)
    stage_residual = 0. if stage is None else _sum([recomputed_stage, -stage])
    if stage is not None and abs(stage_residual) > HEIGHT_ATOL_M + HEIGHT_RTOL * max(abs(stage), abs(recomputed_stage)):
        raise SettlingError("independent stage reconstruction contradicts closed-pool stage")
    liquid_cells, liquid_adjustment = _phase_allocation(water, cells)
    suspended_cells, suspension_adjustment = _phase_allocation(suspension, cells)
    liquid_residual = _sum([_sum(liquid_cells), -water])
    allocated_solid_residual = _sum([_sum(suspended_cells), total_deposit, -initial_s])
    _check_volume(liquid_residual, water)
    _check_volume(allocated_solid_residual, total_deposit)
    return {"status": "BOUNDED_CLOSED_POOL_REFERENCE", "bed_m": new_bed, "depth_m": depth,
        "stage_m": stage, "liquid_m3": water, "suspended_solid_m3": suspension,
        "deposited_solid_m3": deposits, "total_deposited_solid_m3": total_deposit,
        "liquid_by_cell_m3": liquid_cells, "suspended_by_cell_m3": suspended_cells,
        "events": len(event_records), "event_records": event_records,
        "elapsed_years": elapsed_used, "remaining_years": remaining_time,
        "stopped_at_drying_event": stopped,
        "completed_requested_interval": remaining_time == 0,
        "connected_pool_assumed": True, "wet_connectivity_checked": False,
        "initial_wet_cells": [i for i, h in enumerate(original_depth) if h > 0],
        "final_wet_cells": [i for i, h in enumerate(depth) if h > 0],
        "solver_iterations": iterations, "bracket_expansions": bracket_steps,
        "residuals": {"liquid_m3": liquid_residual, "solid_m3": solid_residual,
            "cell_allocated_solid_m3": allocated_solid_residual,
            "initial_geometric_volume_m3": initial_geometry, "final_geometric_volume_m3": geometry,
            "represented_bed_deposit_m3": representation_residual,
            "fixed_stage_m": stage_residual,
            "scalar_equation_m3": max(map(abs, equation_residuals), default=0.),
            "liquid_allocation_adjustment_m3": liquid_adjustment,
            "suspension_allocation_adjustment_m3": suspension_adjustment},
        "recomputed_stage_m": recomputed_stage, "external_liquid_export_m3": 0.,
        "external_solid_export_m3": 0., "no_pore_volume": True,
        "physical_validation_passed": False, "shoreline_transition_implemented": False,
        "production_authorised": False}
