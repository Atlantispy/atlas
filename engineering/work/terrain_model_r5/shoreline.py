"""Pure, event-free dry-link trial for the declared R4 shoreline closure.

Native cells own all area/material/storage; linear connectors own none. This
operator does not find pools, integrate their phases, advance time, or validate
a moving shoreline. The driver must stop at ownership events and check relief
again after all pool-bed changes. See SHORELINE_DESIGN.md for scientific limits.
"""
from dataclasses import is_dataclass, replace
import math

MAX_CELLS = 4096
MAX_RELIEF_FRACTION = 0.20
SOLID_ATOL = 1e-9
SOLID_RTOL = 1e-11
PHASE_ATOL = 1e-9
PHASE_RTOL = 1e-12
GEOMETRY_ATOL = 1e-9
GEOMETRY_RTOL = 1e-11


class ShorelineError(ValueError):
    """Invalid input or a trial requiring a smaller step/new ownership."""


def _number(value, name, minimum=None, positive=False):
    if type(value) not in (int, float):
        raise ShorelineError(name + ": finite numeric scalar required")
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise ShorelineError(name + ": unrepresentable scalar") from exc
    if not math.isfinite(value) or (minimum is not None and
            (value <= minimum if positive else value < minimum)):
        raise ShorelineError(name + ": outside finite supported range")
    return value


def _vector(values, n, name, minimum=None, positive=False, scalar=False):
    if scalar and type(values) in (int, float):
        values = (values,) * n
    if type(values) not in (tuple, list) or len(values) != n:
        raise ShorelineError(name + ": complete native field required")
    return tuple(_number(v, name, minimum, positive) for v in values)


def _sum(values, name="sum"):
    try:
        return _number(math.fsum(values), name)
    except OverflowError as exc:
        raise ShorelineError(name + ": sum exceeds finite range") from exc


def _product(*values, name):
    result = 1.
    for value in values:
        previous = result
        result = _number(result * value, name)
        if previous != 0 and value != 0 and result == 0:
            raise ShorelineError(name + ": positive transfer underflow")
    return result


def _ids(values, n, name):
    if type(values) not in (tuple, list) or len(values) > n or any(
            type(i) is not int or not 0 <= i < n for i in values):
        raise ShorelineError(name + ": bounded native cell IDs required")
    if len(set(values)) != len(values):
        raise ShorelineError(name + ": duplicate cell")
    return set(values)


def _state(state, *, allow_liquid_remainder=False):
    if not is_dataclass(state) or isinstance(state, type):
        raise ShorelineError("CaptureState-compatible dataclass required")
    try:
        shape = state.shape
        if type(shape) not in (tuple, list) or len(shape) != 2 or any(
                type(v) is not int or v < 1 for v in shape):
            raise ShorelineError("two positive native dimensions required")
        n = shape[0] * shape[1]
        if n > MAX_CELLS:
            raise ShorelineError("native cell envelope exceeded")
        area = _vector(state.cell_area_m2, n, "native area", 0, True)
        rock = _vector(state.bedrock_m, n, "bedrock")
        cover = _vector(state.bed_solid_m3, n, "bed solids", 0)
        water = _vector(state.liquid_m3, n, "liquid", 0)
        # All dynamic callers retain the default fail-closed guard. Only the
        # read-only network opts in and consumes these exact stores itself.
        import phase_storage
        residuals = phase_storage.liquid_remainders(water, getattr(state, 'liquid_remainder_m3', None))
        if any(residuals) and not allow_liquid_remainder:
            raise ShorelineError('nonzero liquid remainder requires exact shoreline transport')
        solids = _vector(state.suspended_solid_m3, n, "suspension", 0)
        rho_s = _number(state.solid_density_kg_m3, "solid density", 0, True)
        rho_w = _number(state.water_density_kg_m3, "liquid density", 0, True)
        if rho_s <= rho_w or any(w == 0 and s > 0 for w, s in zip(water, solids)):
            raise ShorelineError("negatively buoyant mineral grains and wet suspension required")
        bed = _vector(state.bed_m, n, "actual bed")
    except AttributeError as exc:
        raise ShorelineError("complete CaptureState-compatible fields required") from exc
    for i in range(n):
        h = _number(cover[i] / area[i], "nonporous cover thickness", 0)
        if cover[i] > 0 and h == 0:
            raise ShorelineError("cover thickness underflow")
        expected = _number(rock[i] + h, "nonporous actual bed")
        if bed[i] != expected:
            raise ShorelineError("bed property differs from nonporous native inventory")
    for field in (cover, water, solids):
        _sum(field)
    return n, tuple(shape), area, rock, cover, water, solids, bed


def check_relief(before_bed, final_bed, active_links):
    """Check original dry links, including receiving pool deposition.

    Link ownership must be the unchanged list returned by channel_trial. This
    numerical check cannot independently establish that list's completeness.
    """
    if type(before_bed) not in (list, tuple) or not 1 <= len(before_bed) <= MAX_CELLS:
        raise ShorelineError("bounded original bed field required")
    n = len(before_bed)
    before = _vector(before_bed, n, "original bed")
    final = _vector(final_bed, n, "final bed")
    if type(active_links) not in (list, tuple) or len(active_links) > n:
        raise ShorelineError("bounded original active-link inventory required")
    seen = set()
    rows = []
    for link in active_links:
        if type(link) is not dict or not {"source_cell", "receiver_cell", "old_drop_m"} <= set(link):
            raise ShorelineError("incomplete original active-link identity")
        i, j = link["source_cell"], link["receiver_cell"]
        if any(type(k) is not int or not 0 <= k < n for k in (i, j)) or i == j or i in seen:
            raise ShorelineError("invalid or duplicate original active link")
        seen.add(i)
        drop = _number(before[i] - before[j], "original relief", 0, True)
        if _number(link["old_drop_m"], "recorded original relief", 0, True) != drop:
            raise ShorelineError("original active-link relief identity changed")
        new_drop = _number(final[i] - final[j], "final relief")
        fraction = _number(max(0., (drop - new_drop) / drop), "relief fraction", 0)
        rows.append({"source_cell": i, "receiver_cell": j, "old_drop_m": drop,
                     "new_drop_m": new_drop, "consumed_fraction": fraction})
        if fraction > MAX_RELIEF_FRACTION:
            raise ShorelineError("channel timestep consumes relative link relief excessively; reduce dt")
    return {"status": "PASS", "maximum_fraction": max((v["consumed_fraction"] for v in rows), default=0.),
            "limit_fraction": MAX_RELIEF_FRACTION, "checked_links": rows}


def channel_trial(state, *, receivers, link_lengths_m, contributing_area_m2,
                  pool_owner, pool_stages_m, incipient_pool_cells, external_outlets,
                  runoff_m_year, sediment_k_per_year, rock_k_per_year,
                  cover_scale_m, settling_m_year, dt_years,
                  incoming_liquid_m3_year=None, incoming_solid_m3_year=None):
    """Evaluate one supplied event-free ownership state without phase routing.

    Coefficients may be scalars or native fields; inlet arrays are complete
    boundary-rate fields, not copies of local runoff. Pool IDs are nonnegative
    integers or nonempty strings; stages contain exactly the used IDs. Ports
    and pool-local runoff are disjoint returned transfers: credit each once.
    """
    n, shape, area, old_rock, old_cover, stored_w, stored_s, bed = _state(state)
    if type(receivers) not in (tuple, list) or len(receivers) != n or any(
            type(j) is not int or not -1 <= j < n for j in receivers):
        raise ShorelineError("complete strict-descent receiver field required")
    length = _vector(link_lengths_m, n, "link length", 0)
    upstream_area = _vector(contributing_area_m2, n, "contributing area", 0, True)
    outlets = _ids(external_outlets, n, "external outlets")
    incipient = _ids(incipient_pool_cells, n, "incipient pool cells")
    if type(pool_owner) not in (tuple, list) or len(pool_owner) != n:
        raise ShorelineError("complete pool ownership required")
    for owner in pool_owner:
        if owner is not None and not ((type(owner) is int and owner >= 0) or
                                      (type(owner) is str and bool(owner))):
            raise ShorelineError("invalid explicit pool identity")
    used = {p for p in pool_owner if p is not None}
    if type(pool_stages_m) is not dict or set(pool_stages_m) != used or any(
            not ((type(p) is int and p >= 0) or (type(p) is str and bool(p)))
            for p in pool_stages_m):
        raise ShorelineError("exact pool-stage identity inventory required")
    stages = {p: _number(v, "pool stage") for p, v in pool_stages_m.items()}
    runoff = _vector(runoff_m_year, n, "runoff", 0, scalar=True)
    ks = _vector(sediment_k_per_year, n, "sediment K", 0, scalar=True)
    kr = _vector(rock_k_per_year, n, "rock K", 0, scalar=True)
    hstar = _number(cover_scale_m, "cover scale", 0, True)
    velocity = _number(settling_m_year, "effective dry-channel settling", 0)
    dt = _number(dt_years, "dt", 0, True)
    inlet_w = _vector((0.,) * n if incoming_liquid_m3_year is None else incoming_liquid_m3_year,
                      n, "boundary liquid rate", 0)
    inlet_s = _vector((0.,) * n if incoming_solid_m3_year is None else incoming_solid_m3_year,
                      n, "boundary suspended-solid rate", 0)
    local_w = [_product(runoff[i], area[i], name="local runoff rate") for i in range(n)]
    water = [_sum((local_w[i], inlet_w[i])) if pool_owner[i] is None else inlet_w[i] for i in range(n)]
    incoming = list(inlet_s)
    active = []
    connectors = {}
    for i, j in enumerate(receivers):
        if upstream_area[i] < area[i]:
            raise ShorelineError("contributing area cannot be smaller than its native source area")
        if j < 0:
            if length[i] != 0:
                raise ShorelineError("terminal connector length must be zero")
        else:
            ri, ci = divmod(i, shape[1]); rj, cj = divmod(j, shape[1])
            if i == j or max(abs(ri-rj), abs(ci-cj)) != 1 or length[i] <= 0 or bed[i] <= bed[j]:
                raise ShorelineError("raw receiver must be an adjacent strict bed descent with positive length")
        owner = pool_owner[i]
        if i in outlets and (j != -1 or owner is not None):
            raise ShorelineError("external export and pool ownership must be disjoint terminals")
        if owner is None:
            if i in incipient or stored_w[i] != 0 or stored_s[i] != 0:
                raise ShorelineError("a dry source cannot own existing phases or an incipient pool flag")
        else:
            mixture = _sum((stored_w[i], stored_s[i]), "native mixture")
            depth = _number(mixture / area[i], "native mixture depth", 0)
            if mixture > 0 and depth == 0:
                raise ShorelineError("native mixture depth underflow")
            if i in incipient:
                if mixture != 0 or stages[owner] != bed[i]:
                    raise ShorelineError("incipient pool requires exact zero depth at its bed stage")
            elif mixture <= 0 or stages[owner] <= bed[i]:
                raise ShorelineError("pool ownership requires positive depth or an explicit incipient cell")
            expected_stage = _number(bed[i] + depth, "native geometric stage")
            tolerance = GEOMETRY_ATOL + GEOMETRY_RTOL * max(abs(expected_stage), abs(stages[owner]))
            if abs(expected_stage-stages[owner]) > tolerance:
                raise ShorelineError("pool stage conflicts with native W/S inventory")
        if owner is not None or j < 0:
            continue
        drop = _number(bed[i] - bed[j], "strict dry-link drop", 0, True)
        slope = _number(drop / length[i], "actual bed slope", 0, True)
        row = {"source_cell": i, "receiver_cell": j, "old_drop_m": drop,
               "link_length_m": length[i], "bed_slope": slope}
        active.append(row)

    # Discharge, not local runoff, decides whether a connector transports
    # anything. All structural checks above precede this strict-DAG pass.
    # It uses exactly the former downstream-addition order; only sediment
    # rates still need to be accumulated during the material pass below.
    order = sorted(range(n), key=lambda k: (-bed[k], k))
    for i in order:
        j = receivers[i]
        if pool_owner[i] is None and j >= 0 and pool_owner[j] is None:
            water[j] = _sum((water[j], water[i]), "aggregated liquid rate")
    for row in active:
        i, j = row["source_cell"], row["receiver_cell"]
        if pool_owner[j] is not None:
            eta = stages[pool_owner[j]]
            if not bed[i] >= eta >= bed[j]:
                raise ShorelineError("dry-to-pool ownership conflicts with bed/stage crossing")
            if water[i] == 0:
                # A resting zero-head margin has no transfer point or material
                # rates. Its original raw bed link remains in the relief guard.
                row["shoreline_transfer_status"] = "ZERO_FLOW_NO_TRANSFER_POINT"
                continue
            if eta == bed[i]:
                raise ShorelineError("zero-length dry connector: native wetting event requires pool ownership")
            drop, slope = row["old_drop_m"], row["bed_slope"]
            fraction = _number((bed[i]-eta) / drop, "dry connector fraction", 0, True)
            distance = _product(length[i], fraction, name="dry connector distance")
            connectors[i] = {"distance_from_source_m": distance, "fraction_from_source": fraction,
                             "stage_m": eta, "bed_slope": slope,
                             "source_area_m2": area[i], "connector_area_m2": 0.,
                             "connector_storage_m3": 0.}
            row["shoreline_connector"] = dict(connectors[i])

    rock, cover = list(old_rock), list(old_cover)
    rock_debits, cover_debits, deposits = [0.] * n, [0.] * n, [0.] * n
    outflux = [0.] * n
    ports, local_pool, exports = [], [], []
    pool_inflow = {p: [] for p in used}
    maximum_solid_liquid_ratio = 0.

    def port(source, recipient, qw, qs, kind):
        if qw == 0 and qs > 0:
            raise ShorelineError("suspended-solid port has no transporting liquid")
        if qw == 0 and qs == 0:
            return
        owner = pool_owner[recipient]
        row = {"source_cell": source, "recipient_cell": recipient, "pool_id": owner,
               "kind": kind, "liquid_m3_year": qw, "suspended_solid_m3_year": qs,
               "liquid_m3": _product(qw, dt, name="pool liquid transfer"),
               "suspended_solid_m3": _product(qs, dt, name="pool solid transfer")}
        if source in connectors and kind == "dry_channel_shoreline":
            row["shoreline_connector"] = dict(connectors[source])
        ports.append(row)
        pool_inflow[owner].append(qw)

    for i in order:
        j = receivers[i]
        owner = pool_owner[i]
        if owner is not None:
            local_pool.append({"source_cell": i, "pool_id": owner,
                               "liquid_m3_year": local_w[i],
                               "liquid_m3": _product(local_w[i], dt, name="pool-local runoff"),
                               "dry_channel_material_debit": False})
            pool_inflow[owner].append(local_w[i])
            port(i, i, inlet_w[i], inlet_s[i], "explicit_boundary_to_pool")
            continue
        if water[i] == 0:
            if incoming[i] > 0:
                raise ShorelineError("dry suspended supply needs a separate emplacement model")
            continue
        if i in outlets:
            exports.append({"source_cell": i,
                            "liquid_m3": _product(water[i], dt, name="external liquid export"),
                            "suspended_solid_m3": _product(incoming[i], dt, name="external solid export")})
            outflux[i] = incoming[i]
            continue
        if j < 0:
            raise ShorelineError("positive-flow dry pit requires an explicit incipient-pool ownership event")
        slope = _number((bed[i]-bed[j]) / length[i], "actual bed slope", 0, True)
        intensity = _product(math.sqrt(upstream_area[i]), slope, name="channel intensity")
        h = old_cover[i] / area[i]
        ratio = _number(h / hstar, "cover shielding ratio", 0)
        exposed = math.exp(-ratio)
        er = _product(kr[i], intensity, exposed, name="rock erosion rate")
        es = _product(ks[i], intensity, -math.expm1(-ratio), name="cover entrainment rate")
        generated = _product(area[i], _sum((er, es)), name="generated solid rate")
        numerator = _sum((incoming[i], generated), "available solid rate")
        settling_ratio = _number(_product(velocity, area[i], name="settling factor") / water[i],
                                 "settling/discharge ratio", 0)
        denominator = _number(1. + settling_ratio, "transport denominator", 0, True)
        qout = _number(numerator / denominator, "solid outflux", 0)
        if numerator > 0 and qout == 0:
            raise ShorelineError("positive solid outflux underflow")
        deposition = _number(_product(velocity, qout, name="settling numerator") / water[i],
                             "dry-cell deposition rate", 0)
        if velocity > 0 and qout > 0 and deposition == 0:
            raise ShorelineError("positive deposition rate underflow")
        rock_change = _product(er, dt, name="rock height debit")
        change = _product(deposition-es, area[i], dt, name="net bed-solid change")
        rock[i] = _number(old_rock[i] - rock_change, "trial bedrock")
        cover[i] = _number(old_cover[i] + change, "trial bed solids", 0)
        if rock_change > 0 and rock[i] == old_rock[i]:
            raise ShorelineError("rock height debit is not representable")
        if change != 0 and cover[i] == old_cover[i]:
            raise ShorelineError("net bed-solid change is not representable")
        rock_debits[i] = _product(er, area[i], dt, name="rock solid debit")
        cover_debits[i] = _product(es, area[i], dt, name="cover solid debit")
        deposits[i] = _product(deposition, area[i], dt, name="dry solid deposition")
        outflux[i] = qout
        ratio_out = _number(qout / water[i], "solid/liquid flux ratio", 0)
        maximum_solid_liquid_ratio = max(maximum_solid_liquid_ratio, ratio_out)
        if pool_owner[j] is not None:
            port(i, j, water[i], qout, "dry_channel_shoreline")
        else:
            incoming[j] = _sum((incoming[j], qout), "aggregated suspended rate")

    for i in incipient:
        if _sum(pool_inflow[pool_owner[i]], "incipient pool right-limit inflow") <= 0:
            raise ShorelineError("incipient pool has no actual positive right-limit liquid inflow")
    try:
        result = replace(state, bedrock_m=tuple(rock), bed_solid_m3=tuple(cover))
    except (ValueError, TypeError, OverflowError) as exc:
        raise ShorelineError("trial state cannot represent native inventory") from exc
    _, _, _, _, _, _, _, final_bed = _state(result)
    relief = check_relief(bed, final_bed, active)
    geometric_rock = _sum((_product(before-after, a, name="geometric rock debit")
                           for before, after, a in zip(old_rock, rock, area)), "geometric rock loss")
    mobile_change = _sum((after-before for before, after in zip(old_cover, cover)), "mobile stock change")
    pool_s = _sum((row["suspended_solid_m3"] for row in ports))
    pool_w = _sum((row["liquid_m3"] for row in ports))
    exported_s = _sum((row["suspended_solid_m3"] for row in exports))
    exported_w = _sum((row["liquid_m3"] for row in exports))
    imported_s = _sum((_product(q, dt, name="boundary solid input") for q in inlet_s))
    imported_w = _sum((_product(q, dt, name="boundary liquid input") for q in inlet_w))
    dry_runoff = _sum((_product(local_w[i], dt, name="dry-source runoff")
                       for i in range(n) if pool_owner[i] is None))
    pool_runoff = _sum((row["liquid_m3"] for row in local_pool))
    roundoff = _sum((_sum((_product(2., math.ulp(before), a, name="height roundoff"),
                           _product(2., math.ulp(after), a, name="height roundoff")))
                     for before, after, a in zip(old_rock, rock, area)))
    solid_residual = _sum((mobile_change, pool_s, exported_s, -imported_s, -geometric_rock))
    solid_tolerance = _number(SOLID_ATOL + SOLID_RTOL * max(abs(mobile_change), pool_s+exported_s,
                             imported_s, geometric_rock) + roundoff, "solid tolerance", 0, True)
    water_residual = _sum((pool_w, exported_w, -dry_runoff, -imported_w))
    water_tolerance = _number(PHASE_ATOL + PHASE_RTOL * max(pool_w+exported_w, dry_runoff+imported_w),
                             "liquid tolerance", 0, True)
    if abs(solid_residual) > solid_tolerance or abs(water_residual) > water_tolerance:
        raise ShorelineError("independent dry-link material/liquid budget does not close")
    return result, {
        "schema": "diadem.terrain.shoreline-dry-trial.v1", "status": "PASS_NUMERICAL_TRIAL_ONLY",
        "model": "mass-lumped native cells; zero-area zero-storage linear connectors",
        "dt_years": dt, "pool_ports": ports, "pool_local_runoff": local_pool,
        "pool_local_runoff_source_cells": [row["source_cell"] for row in local_pool],
        "incipient_pool_cells": sorted(incipient), "external_exports": exports,
        "active_links": active, "relief_check": relief,
        "water_discharge_m3_year": water, "sediment_outflux_m3_year": outflux,
        "rock_debit_solid_m3": rock_debits, "cover_debit_solid_m3": cover_debits,
        "dry_deposition_solid_m3": deposits, "rock_loss_solid_m3": geometric_rock,
        "rate_rock_loss_solid_m3": _sum(rock_debits), "mobile_change_m3": mobile_change,
        "pool_liquid_transfer_m3": pool_w, "pool_suspended_transfer_m3": pool_s,
        "external_liquid_export_m3": exported_w, "external_solid_export_m3": exported_s,
        "explicit_boundary_liquid_input_m3": imported_w, "explicit_boundary_solid_input_m3": imported_s,
        "dry_local_runoff_m3": dry_runoff, "pool_local_runoff_m3": pool_runoff,
        "solid_volume_residual_m3": solid_residual, "solid_volume_tolerance_m3": solid_tolerance,
        "liquid_volume_residual_m3": water_residual, "liquid_volume_tolerance_m3": water_tolerance,
        "height_subtraction_roundoff_bound_m3": roundoff,
        "maximum_solid_liquid_flux_ratio": maximum_solid_liquid_ratio,
        "persistent_phases_changed": False, "time_advanced": False,
        "post_pool_relief_check_required": True, "event_free_ownership_supplied_not_proven": True,
        "spatial_cut_cell_erosion": False, "hydraulics_solved": False,
        "physical_validation": "NOT_ESTABLISHED", "production_authorized": False,
    }
