"""Bounded, pure scientific reference kernels; never production authorisation.

Flat lists are row-major; +x is east, +y is north. All volumes are solid
particle volumes, not porous bulk volume. See CONSTRUCTIVE_METHODS.md for the
published laws, the explicitly engineered closures and their limitations.
"""
from collections import deque
import math
import sys

MAX_CELLS = 16_384
GLACIAL_LAW = "seddik2009_quadratic_normal"
AEOLIAN_LAW = "delorme2020_quadratic_saturated"


class ConstructiveError(ValueError):
    """Invalid, unsupported or numerically unrepresentable reference input."""


def _number(value, name, *, minimum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ConstructiveError(f"{name}: expected a finite real number")
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise ConstructiveError(f"{name}: unrepresentable number") from exc
    if not math.isfinite(value) or (positive and value <= 0):
        raise ConstructiveError(f"{name}: invalid finite range")
    if minimum is not None and value < minimum:
        raise ConstructiveError(f"{name}: below {minimum}")
    return value


def _finite(value, name):
    if not math.isfinite(value):
        raise ConstructiveError(f"{name}: arithmetic overflow")
    return value


def _mul(*values):
    result = _finite(math.prod(values), "product")
    if result == 0 and all(v != 0 for v in values):
        raise ConstructiveError("positive product underflows binary64")
    return result


def _div(numerator, denominator):
    result = _finite(numerator / denominator, "quotient")
    if numerator != 0 and result == 0:
        raise ConstructiveError("nonzero quotient underflows binary64")
    return result


def _sum(values):
    try:
        return _finite(math.fsum(values), "sum")
    except OverflowError as exc:
        raise ConstructiveError("sum overflow") from exc


def _grid(rows, cols, cell_size_m):
    if (type(rows) is not int or type(cols) is not int or rows < 1 or cols < 1
            or rows * cols > MAX_CELLS):
        raise ConstructiveError(f"grid must contain 1..{MAX_CELLS} cells")
    dx = _number(cell_size_m, "cell_size_m", positive=True)
    return rows * cols, dx, _mul(dx, dx)


def _values(values, n, name, *, minimum=None):
    if not isinstance(values, list) or len(values) != n:
        raise ConstructiveError(f"{name}: expected a list of {n} values")
    return [_number(v, name, minimum=minimum) for v in values]


def _mask(values, n, name):
    if not isinstance(values, list) or len(values) != n or any(type(v) is not bool for v in values):
        raise ConstructiveError(f"{name}: expected {n} literal booleans")
    return values.copy()


def _porosity(value, name):
    value = _number(value, name, minimum=0)
    if value >= 1:
        raise ConstructiveError(f"{name}: must be less than 1")
    return value


def _label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ConstructiveError("source_label: explicit scenario/source description required")
    return value


def _neighbours(i, rows, cols, diagonal=True):
    r, c = divmod(i, cols)
    for dr, dc in ((-1, 0), (0, -1), (0, 1), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1)):
        if not diagonal and dr and dc:
            continue
        if 0 <= r + dr < rows and 0 <= c + dc < cols:
            yield (r + dr) * cols + c + dc


def _receivers(values, rows, cols):
    n = rows * cols
    if not isinstance(values, list) or len(values) != n:
        raise ConstructiveError("receivers: wrong length")
    indegree = [0] * n
    for i, receiver in enumerate(values):
        if type(receiver) is not int or receiver < -1 or receiver >= n:
            raise ConstructiveError("receiver must be a cell index or -1 exterior")
        if receiver == -1:
            r, c = divmod(i, cols)
            if r not in (0, rows - 1) and c not in (0, cols - 1):
                raise ConstructiveError("interior cell cannot export directly")
        else:
            if receiver not in _neighbours(i, rows, cols):
                raise ConstructiveError("receiver must be an adjacent distinct cell")
            indegree[receiver] += 1
    queue = deque(i for i, degree in enumerate(indegree) if degree == 0)
    order = []
    while queue:
        i = queue.popleft()
        order.append(i)
        receiver = values[i]
        if receiver >= 0:
            indegree[receiver] -= 1
            if indegree[receiver] == 0:
                queue.append(receiver)
    if len(order) != n:
        raise ConstructiveError("receiver graph contains a cycle")
    return values.copy(), order


def _thickness(volume, area, porosity):
    if volume < 0:
        raise ConstructiveError("negative material volume")
    return _div(volume, _mul(area, 1 - porosity))


def _ledger(external, eroded, deposited, exported, n):
    residual = _sum([external, eroded, -deposited, -exported])
    # Numerical accumulation allowance, not a scientific calibration tolerance.
    allowance = 1e-12 + 512 * sys.float_info.epsilon * max(1, n) * max(external, eroded, deposited, exported)
    if abs(residual) > allowance:
        raise ConstructiveError("solid-volume balance failed")
    return {"external_supply_solid_m3": external, "eroded_solid_m3": eroded,
            "deposited_solid_m3": deposited, "exported_solid_m3": exported,
            "balance_residual_solid_m3": residual, "roundoff_allowance_solid_m3": allowance}


def _result(method, source_label, bedrock_erosion, mobile_erosion, deposition, ledger, **extra):
    return {"method": method, "source_label": _label(source_label),
            "status": "BOUNDED_REFERENCE_ONLY", "physical_validation_passed": False,
            "production_authorized": False, "full_landform_family_implemented": False,
            "bedrock_erosion_m": bedrock_erosion, "mobile_erosion_m": mobile_erosion,
            "deposition_m": deposition,
            "net_surface_change_m": [_finite(d - b - m, "net thickness") for b, m, d in zip(bedrock_erosion, mobile_erosion, deposition)],
            "ledger": ledger, **extra}


def _raised_surface(base, deposition):
    surface = [_finite(z + d, "surface") for z, d in zip(base, deposition)]
    if any(d > 0 and new == old for old, d, new in zip(base, deposition, surface)):
        raise ConstructiveError("deposit is below the elevation's binary64 resolution")
    return surface


def _lowered_surface(base, erosion):
    surface = [_finite(z - e, "eroded bed") for z, e in zip(base, erosion)]
    if any(e > 0 and new == old for old, e, new in zip(base, erosion, surface)):
        raise ConstructiveError("erosion is below the elevation's binary64 resolution")
    return surface


def volcanic_emplacement(base_elevation_m, *, rows, cols, cell_size_m,
                         vent_cells, footprint, thickness_weights,
                         supplied_solid_m3, deposit_porosity, source_label):
    """Volume-normalise a supplied mapped shape; NOT a volcanic shape generator.

    Every four-connected footprint component must contain an explicitly supplied
    vent. Thickness weights are relative m (uniform area); zero outside footprint.
    The complete supplied solid volume is assigned to this declared footprint.
    """
    n, dx, area = _grid(rows, cols, cell_size_m)
    base = _values(base_elevation_m, n, "base_elevation_m")
    mask = _mask(footprint, n, "footprint")
    weights = _values(thickness_weights, n, "thickness_weights", minimum=0)
    volume = _number(supplied_solid_m3, "supplied_solid_m3", minimum=0)
    porosity = _porosity(deposit_porosity, "deposit_porosity")
    if (not isinstance(vent_cells, list) or any(type(i) is not int or not 0 <= i < n for i in vent_cells)
            or len(set(vent_cells)) != len(vent_cells)):
        raise ConstructiveError("vent_cells: unique valid explicit cells required")
    if any(not mask[i] for i in vent_cells) or any(w and not m for w, m in zip(weights, mask)):
        raise ConstructiveError("vent/weight lies outside authorised footprint")
    reached = set(vent_cells)
    queue = deque(vent_cells)
    while queue:
        i = queue.popleft()
        for j in _neighbours(i, rows, cols, diagonal=False):
            if mask[j] and j not in reached:
                reached.add(j)
                queue.append(j)
    if reached != {i for i, present in enumerate(mask) if present}:
        raise ConstructiveError("footprint component has no supplied vent")
    peak = max(weights)
    if volume > 0 and peak == 0:
        raise ConstructiveError("positive emplacement needs a nonzero supplied shape")
    scaled = [w / peak for w in weights] if peak else [0.0] * n
    denominator = _sum(scaled)
    volumes = [_mul(volume, w / denominator) if volume and w else 0.0 for w in scaled]
    deposition = [_thickness(v, area, porosity) for v in volumes]
    ledger = _ledger(volume, 0.0, _sum(volumes), 0.0, n)
    return _result("mapped_volume_normalised_emplacement", source_label, [0.0] * n,
                   [0.0] * n, deposition, ledger,
                   surface_elevation_m=_raised_surface(base, deposition),
                   vent_cells=vent_cells.copy(), footprint=mask,
                   deposited_solid_m3_by_cell=volumes,
                   basal_area_m2=_mul(sum(mask), area),
                   height_above_local_base_m=max(deposition))


def _gaussian_interval(left, right, mean, scale):
    a = _finite((left - mean) / scale, "Gaussian support")
    b = _finite((right - mean) / scale, "Gaussian support")
    # erfc avoids cancellation in one-sided tails; extreme tails may underflow.
    if a >= 0:
        return 0.5 * (math.erfc(a) - math.erfc(b))
    if b <= 0:
        return 0.5 * (math.erfc(-b) - math.erfc(-a))
    return 0.5 * (math.erf(b) - math.erf(a))


def tephra_fallout(base_elevation_m, *, rows, cols, cell_size_m, origin_x_m,
                   origin_y_m, footprint, vent_x_m, vent_y_m, wind_x_m_s,
                   wind_y_m_s, fall_time_s, diffusivity_m2_s,
                   supplied_solid_m3, deposit_porosity, source_label):
    """Constant-wind, constant-D, single prescribed fall-time Gaussian fallout.

    Gaussian mean=vent+wind*t; variance=2*D*t per axis. Exact rectangle
    integrals, not centre samples. Masked/outside-grid mass is exported; it is
    NEVER squeezed back onto the permitted footprint. Flat receiving-plane
    approximation; base heights only receive the deposit, not alter fall time.
    """
    n, dx, area = _grid(rows, cols, cell_size_m)
    base = _values(base_elevation_m, n, "base_elevation_m")
    mask = _mask(footprint, n, "footprint")
    ox = _number(origin_x_m, "origin_x_m")
    oy = _number(origin_y_m, "origin_y_m")
    vx = _number(vent_x_m, "vent_x_m")
    vy = _number(vent_y_m, "vent_y_m")
    wx = _number(wind_x_m_s, "wind_x_m_s")
    wy = _number(wind_y_m_s, "wind_y_m_s")
    time = _number(fall_time_s, "fall_time_s", positive=True)
    diffusion = _number(diffusivity_m2_s, "diffusivity_m2_s", positive=True)
    volume = _number(supplied_solid_m3, "supplied_solid_m3", minimum=0)
    porosity = _porosity(deposit_porosity, "deposit_porosity")
    mean_x, mean_y = _finite(vx + _mul(wx, time), "mean x"), _finite(vy + _mul(wy, time), "mean y")
    scale = math.sqrt(_mul(4.0, diffusion, time))
    xedges = [_finite(ox + i * dx, "grid edge") for i in range(cols + 1)]
    yedges = [_finite(oy + i * dx, "grid edge") for i in range(rows + 1)]
    if any(b <= a for edges in (xedges, yedges) for a, b in zip(edges, edges[1:])):
        raise ConstructiveError("cell edges are not representably distinct")
    px = [_gaussian_interval(a, b, mean_x, scale) for a, b in zip(xedges, xedges[1:])]
    py = [_gaussian_interval(a, b, mean_y, scale) for a, b in zip(yedges, yedges[1:])]
    fractions = [px[i % cols] * py[i // cols] if mask[i] else 0.0 for i in range(n)]
    retained = _sum(fractions)
    if retained > 1 + 64 * sys.float_info.epsilon:
        raise ConstructiveError("Gaussian integral exceeds normalisation")
    volumes = [volume * f for f in fractions]
    deposited = _sum(volumes)
    exported = max(0.0, volume - deposited)
    deposition = [_thickness(v, area, porosity) for v in volumes]
    return _result("bonadonna2005_constant_fickian_fallout_subset", source_label,
                   [0.0] * n, [0.0] * n, deposition,
                   _ledger(volume, 0.0, deposited, exported, n),
                   surface_elevation_m=_raised_surface(base, deposition),
                   deposited_solid_m3_by_cell=volumes, retained_probability=retained,
                   gaussian_mean_m=[mean_x, mean_y], gaussian_axis_variance_m2=_mul(2, diffusion, time),
                   omitted_tail_or_mask_solid_m3=exported,
                   receiving_plane_approximation="flat; topography does not alter prescribed fall time")


def glacial_erosion(bed_elevation_m, *, rows, cols, cell_size_m, ice_extent,
                    warm_bed, sliding_speed_m_per_yr, bed_gradient,
                    erosion_constant_yr_per_m, duration_yr, erodible_thickness_m,
                    receivers, deposit_fraction, bedrock_porosity, deposit_porosity,
                    law, source_label):
    """Prescribed-ice erosion and prescribed acyclic solid routing.

    E_normal=C*u_b**2. Frozen-gradient vertical rate=E_normal*sqrt(1+s**2).
    Capture fractions are explicit scenario closures, NOT a published till law.
    """
    if law != GLACIAL_LAW:
        raise ConstructiveError("unsupported glacial erosion law")
    n, dx, area = _grid(rows, cols, cell_size_m)
    base = _values(bed_elevation_m, n, "bed_elevation_m")
    ice = _mask(ice_extent, n, "ice_extent")
    warm = _mask(warm_bed, n, "warm_bed")
    speed = _values(sliding_speed_m_per_yr, n, "sliding_speed_m_per_yr", minimum=0)
    slope = _values(bed_gradient, n, "bed_gradient", minimum=0)
    available = _values(erodible_thickness_m, n, "erodible_thickness_m", minimum=0)
    fractions = _values(deposit_fraction, n, "deposit_fraction", minimum=0)
    if any(f > 1 for f in fractions):
        raise ConstructiveError("deposit fractions must lie in [0,1]")
    if any(not i and (w or u != 0) for i, w, u in zip(ice, warm, speed)):
        raise ConstructiveError("warm/sliding forcing outside supplied ice extent")
    coefficient = _number(erosion_constant_yr_per_m, "erosion_constant_yr_per_m", minimum=0)
    time = _number(duration_yr, "duration_yr", minimum=0)
    rock_p = _porosity(bedrock_porosity, "bedrock_porosity")
    deposit_p = _porosity(deposit_porosity, "deposit_porosity")
    rec, order = _receivers(receivers, rows, cols)
    normal_rate = [_mul(coefficient, u, u) if i and w else 0.0 for i, w, u in zip(ice, warm, speed)]
    erosion = [min(a, _mul(e, time, math.hypot(1, s))) for a, e, s in zip(available, normal_rate, slope)]
    sources = [_mul(e, area, 1 - rock_p) for e in erosion]
    load = sources.copy()
    deposited = [0.0] * n
    exported = []
    outgoing = [0.0] * n
    for i in order:
        deposited[i] = load[i] * fractions[i]
        outgoing[i] = load[i] - deposited[i]
        if rec[i] == -1:
            exported.append(outgoing[i])
        else:
            load[rec[i]] = _finite(load[rec[i]] + outgoing[i], "routed glacial load")
    thickness = [_thickness(v, area, deposit_p) for v in deposited]
    return _result(GLACIAL_LAW, source_label, erosion, [0.0] * n, thickness,
                   _ledger(0.0, _sum(sources), _sum(deposited), _sum(exported), n),
                   eroded_solid_m3_by_cell=sources, deposited_solid_m3_by_cell=deposited,
                   outgoing_solid_m3_by_cell=outgoing, normal_erosion_rate_m_per_yr=normal_rate,
                   bed_elevation_m=_lowered_surface(base, erosion),
                   capped_cells=[i for i, (e, a) in enumerate(zip(erosion, available)) if e > 0 and e == a],
                   transport_closure="prescribed capture fractions on supplied acyclic paths; no ice dynamics")


def aeolian_transport(mobile_thickness_m, *, rows, cols, cell_size_m, receivers,
                      friction_velocity_east_m_s, friction_velocity_north_m_s,
                      threshold_m_s, grain_diameter_m, grain_density_kg_m3,
                      air_density_kg_m3, gravity_m_s2, porosity, duration_s,
                      external_supply_solid_m3, law, source_label):
    """Delorme Eq2 capacity with supply-limited entrainment and excess deposition.

    Supplied wind paths must be adjacent, acyclic and within45deg of transport
    direction. Capacity is instantaneous saturation, NOT a dune-instability law.
    Width=cell area/path length. External supply is material already entering
    each control volume; zero wind deposits it without eroding existing sand.
    """
    if law != AEOLIAN_LAW:
        raise ConstructiveError("unsupported aeolian law")
    n, dx, area = _grid(rows, cols, cell_size_m)
    mobile = _values(mobile_thickness_m, n, "mobile_thickness_m", minimum=0)
    ux = _values(friction_velocity_east_m_s, n, "friction_velocity_east_m_s")
    uy = _values(friction_velocity_north_m_s, n, "friction_velocity_north_m_s")
    threshold = _values(threshold_m_s, n, "threshold_m_s", minimum=0)
    external = _values(external_supply_solid_m3, n, "external_supply_solid_m3", minimum=0)
    diameter = _number(grain_diameter_m, "grain_diameter_m", positive=True)
    rho_g = _number(grain_density_kg_m3, "grain_density_kg_m3", positive=True)
    rho_a = _number(air_density_kg_m3, "air_density_kg_m3", positive=True)
    gravity = _number(gravity_m_s2, "gravity_m_s2", positive=True)
    if rho_a >= rho_g:
        raise ConstructiveError("aeolian reference requires air density below grain density")
    p = _porosity(porosity, "porosity")
    time = _number(duration_s, "duration_s", minimum=0)
    rec, order = _receivers(receivers, rows, cols)
    coefficient = _mul(25.0, _div(rho_a, rho_g), math.sqrt(_div(diameter, gravity)))
    capacity, flux = [0.0] * n, [0.0] * n
    for i in range(n):
        speed = _finite(math.hypot(ux[i], uy[i]), "friction speed")
        row, col = divmod(i, cols)
        length = dx
        if speed > threshold[i]:
            if rec[i] >= 0:
                rr, cc = divmod(rec[i], cols)
                length = _mul(dx, math.hypot(rr - row, cc - col))
                alignment = ((cc - col) * (ux[i] / speed) + (rr - row) * (uy[i] / speed)) / (length / dx)
                if alignment < math.sqrt(0.5) - 1e-12:
                    raise ConstructiveError("receiver contradicts supplied wind direction")
            elif not ((col == 0 and ux[i] < 0) or (col == cols - 1 and ux[i] > 0)
                      or (row == 0 and uy[i] < 0) or (row == rows - 1 and uy[i] > 0)):
                raise ConstructiveError("export wind does not leave domain")
            # Difference of squares is factored to avoid avoidable cancellation.
            flux[i] = _mul(coefficient, speed - threshold[i], speed + threshold[i])
            capacity[i] = _mul(flux[i], _div(area, length), time)
    initial = [_mul(h, area, 1 - p) for h in mobile]
    load = external.copy()
    eroded, deposited, outgoing = [0.0] * n, [0.0] * n, [0.0] * n
    exported = []
    for i in order:
        if load[i] > capacity[i]:
            deposited[i] = load[i] - capacity[i]
            outgoing[i] = capacity[i]
        else:
            eroded[i] = min(initial[i], capacity[i] - load[i])
            outgoing[i] = _finite(load[i] + eroded[i], "aeolian outgoing")
        if rec[i] == -1:
            exported.append(outgoing[i])
        else:
            load[rec[i]] = _finite(load[rec[i]] + outgoing[i], "aeolian incoming")
    erosion_h = [_thickness(v, area, p) for v in eroded]
    deposit_h = [_thickness(v, area, p) for v in deposited]
    final = [_thickness(_sum([old, -e, d]), area, p) for old, e, d in zip(initial, eroded, deposited)]
    return _result(AEOLIAN_LAW, source_label, [0.0] * n, erosion_h, deposit_h,
                   _ledger(_sum(external), _sum(eroded), _sum(deposited), _sum(exported), n),
                   mobile_thickness_m=final, eroded_solid_m3_by_cell=eroded,
                   deposited_solid_m3_by_cell=deposited, outgoing_solid_m3_by_cell=outgoing,
                   saturated_flux_solid_m2_s=flux,
                   transport_closure="instantaneous local saturation; prescribed paths; no fetch-length/dune feedback")


def frost_creep(surface_elevation_m, mobile_thickness_m, *, rows, cols,
                cell_size_m, receivers, cumulative_normal_heave_m,
                active_layer_m, outlet_gradient, porosity, source_label):
    """Potential straight-normal-heave/vertical-settlement, one-hop remapping.

    Surface displacement=h_normal*tan(slope); horizontal displacement is its
    projection. Active-layer plug motion is an ENGINEERING closure. Require
    displacement<=one link; no subcycling or long-run morphology is inferred.
    """
    n, dx, area = _grid(rows, cols, cell_size_m)
    surface = _values(surface_elevation_m, n, "surface_elevation_m")
    mobile = _values(mobile_thickness_m, n, "mobile_thickness_m", minimum=0)
    heave = _values(cumulative_normal_heave_m, n, "cumulative_normal_heave_m", minimum=0)
    active = _values(active_layer_m, n, "active_layer_m", minimum=0)
    outlet = _values(outlet_gradient, n, "outlet_gradient", minimum=0)
    if any(a > h for a, h in zip(active, mobile)):
        raise ConstructiveError("active layer exceeds available mobile thickness")
    p = _porosity(porosity, "porosity")
    rec, unused_order = _receivers(receivers, rows, cols)
    displaced, fraction, moved = [0.0] * n, [0.0] * n, [0.0] * n
    for i in range(n):
        length = dx
        if rec[i] >= 0:
            r, c = divmod(i, cols)
            rr, cc = divmod(rec[i], cols)
            length = _mul(dx, math.hypot(rr - r, cc - c))
            slope = _finite((surface[i] - surface[rec[i]]) / length, "creep gradient")
            if slope < 0:
                raise ConstructiveError("frost-creep receiver must not be uphill")
        else:
            slope = outlet[i]
        displaced[i] = _mul(heave[i], slope)
        horizontal = _div(displaced[i], math.hypot(1, slope))
        fraction[i] = _div(horizontal, length)
        if fraction[i] > 1:
            raise ConstructiveError("frost-creep displacement exceeds one cell; subdivide forcing")
        moved[i] = _mul(active[i], area, 1 - p, fraction[i])
    deposited, exported = [0.0] * n, []
    for i, receiver in enumerate(rec):
        if receiver == -1:
            exported.append(moved[i])
        else:
            deposited[receiver] = _finite(deposited[receiver] + moved[i], "creep deposit")
    erosion_h = [_thickness(v, area, p) for v in moved]
    deposit_h = [_thickness(v, area, p) for v in deposited]
    final = [_finite(h - e + d, "mobile thickness") for h, e, d in zip(mobile, erosion_h, deposit_h)]
    if any(h < 0 for h in final):
        raise ConstructiveError("negative mobile inventory")
    return _result("li2018_potential_frost_creep_with_plug_remap", source_label,
                   [0.0] * n, erosion_h, deposit_h,
                   _ledger(0.0, _sum(moved), _sum(deposited), _sum(exported), n),
                   mobile_thickness_m=final, eroded_solid_m3_by_cell=moved,
                   deposited_solid_m3_by_cell=deposited,
                   potential_surface_displacement_m=displaced, one_hop_fraction=fraction,
                   transport_closure="potential heave kinematics; prescribed active-layer plug; no sorting/gelifluction")


def mixing_fixture():
    """Small synthetic calls for orchestration; returned values are not canon.

    A source-to-deposit glacial call and sourced fallout feed the aeolian mobile
    inventory. Porosity and particle phase are held fixed; no other ledger is
    silently consumed. Parent orchestration can independently recheck transfer.
    """
    n = 6
    glacier = glacial_erosion([4., 3., 2., 3., 2., 1.], rows=2, cols=3,
        cell_size_m=10., ice_extent=[True, True, False, False, False, False],
        warm_bed=[True, True, False, False, False, False],
        sliding_speed_m_per_yr=[2., 3., 0., 0., 0., 0.], bed_gradient=[0.] * n,
        erosion_constant_yr_per_m=1e-4, duration_yr=10., erodible_thickness_m=[1.] * n,
        receivers=[1, 2, -1, 4, 5, -1], deposit_fraction=[0., 0., .75, 0., 0., 0.],
        bedrock_porosity=0., deposit_porosity=.4, law=GLACIAL_LAW,
        source_label="SYNTHETIC: prescribed moving ice, Seddik coefficient; uncalibrated deposition closure")
    tephra = tephra_fallout(glacier["bed_elevation_m"], rows=2, cols=3,
        cell_size_m=10., origin_x_m=0., origin_y_m=0., footprint=[True] * n,
        vent_x_m=5., vent_y_m=5., wind_x_m_s=.1, wind_y_m_s=0., fall_time_s=10.,
        diffusivity_m2_s=2., supplied_solid_m3=1., deposit_porosity=.4,
        source_label="SYNTHETIC: Fickian single-source fallout; no real eruption")
    supplied = [a + b for a, b in zip(glacier["deposition_m"], tephra["deposition_m"])]
    wind = aeolian_transport(supplied, rows=2, cols=3, cell_size_m=10.,
        receivers=[1, 2, -1, 4, 5, -1], friction_velocity_east_m_s=[.6] * n,
        friction_velocity_north_m_s=[0.] * n, threshold_m_s=[.39] * n,
        grain_diameter_m=.00045, grain_density_kg_m3=2650., air_density_kg_m3=1.2,
        gravity_m_s2=9.81, porosity=.4, duration_s=100.,
        external_supply_solid_m3=[0.] * n, law=AEOLIAN_LAW,
        source_label="SYNTHETIC: common particle phase and porosity for interface test only")
    return {"status": "SYNTHETIC_INTERFACE_FIXTURE_ONLY", "glacial": glacier,
            "tephra": tephra, "aeolian": wind,
            "aeolian_initial_mobile_thickness_m": supplied,
            "physical_validation_passed": False, "production_authorized": False}
