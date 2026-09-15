"""Finite coastal shear erosion and transient, water-funded settling.

Water METHOD_R1 supplies the reduced laws; no wave momentum/current, calibre,
groundwater subsidy, chemical sorting or R14 steady-throughflow settling is
inferred. Stocks and applied pore/material transfers are exact. Constitutive
stress, exponential and transferable-amount precision is disclosed binary64.
"""
from dataclasses import replace
from fractions import Fraction as F
import math

from work.generator_upgrade_r16 import columns, regional
from work.generator_upgrade_r18 import composite
from . import substrate
from .state import Cell, density, plain, q, represented


MAX_EVENTS = 256
PHASES = {'bedrock', 'mobile_sediment'}
SCHEMA = 'diadem.finite-coastal-sediment-step.r19'


def _clone(cell, palette):
    if type(cell) is not Cell:
        raise ValueError('explicit R19 finite Cell required')
    result = Cell(cell.column, list(cell.pores), cell.free,
                  dict(cell.suspended), tuple(cell.momentum), cell.kind)
    result.validate(palette)
    if len(result.column.layers) > columns.MAX_LAYERS:
        raise ValueError('native coastal layer budget exceeded')
    for layer in result.column.layers:
        if layer.phase not in PHASES:
            raise ValueError('coastal erosion supports bedrock/mobile_sediment only')
        if layer.phase == 'bedrock' and palette[layer.material_id]['phase'] != 'bedrock':
            raise ValueError('native bedrock differs from original composite phase')
    for mid in {layer.material_id for layer in result.column.layers} | set(result.suspended):
        if palette[mid]['phase'] not in PHASES:
            raise ValueError('unsupported original coastal material phase')
    return result


def _commit(target, source):
    target.column, target.pores = source.column, source.pores
    target.free, target.suspended = source.free, source.suspended
    target.momentum = source.momentum


def _stock(cell, palette):
    masses = {}
    for layer in cell.column.layers:
        masses[layer.material_id] = q(masses.get(layer.material_id, F())+layer.mass_kg)
    for mid, mass in cell.suspended.items():
        masses[mid] = q(masses.get(mid, F())+mass)
    return q(cell.free+sum(cell.pores, F())), masses


def _closed(before, after, palette):
    a, b = _stock(before, palette), _stock(after, palette)
    if a[0] != b[0] or any(a[1].get(mid, F()) != b[1].get(mid, F())
                          for mid in set(a[1]) | set(b[1])):
        raise ArithmeticError('exact coastal bed/suspension/pore transaction does not close')


def _descriptor(mid, palette):
    descriptor = composite._validated(mid, palette)
    if descriptor['phase'] not in PHASES:
        raise ValueError('unsupported original coastal material phase')
    return descriptor


def erode_top(cell, palette, mass_kg):
    """Exact one-contact parcel transaction; no rate, dry/wet or dilute law.

The released water is the same fraction of ACTUAL layer pore liquid as the
removed mass, never full pore capacity inferred from porosity. Newly entrained
stationary material/liquid carries zero momentum; integrated momentum is kept.
An overdraw fails without mutation. ``evolve`` owns finite contact traversal.
"""
    work = _clone(cell, palette)
    mass = q(mass_kg, 'exposed erosion mass', nonnegative=True)
    if not mass:
        return {'operation': 'erode_top', 'mass_kg': '0', 'pore_liquid_released_m3': '0',
                'momentum_to_bed_m4_s': [0., 0.]}
    if not work.column.layers:
        raise ValueError('finite coastal bed is exhausted')
    layer = work.column.layers[-1]
    descriptor = _descriptor(layer.material_id, palette)
    if layer.phase == 'bedrock' and descriptor['phase'] != 'bedrock':
        raise ValueError('exposed bedrock differs from original composite phase')
    if mass > layer.mass_kg:
        raise ValueError('erosion crosses the exposed contact; split the transaction')
    fraction = q(mass/layer.mass_kg, 'exact eroded source fraction')
    released = q(work.pores[-1]*fraction, 'actual eroded pore liquid', nonnegative=True)
    grain = q(mass/layer.grain_density_kg_m3, 'eroded grain volume')
    bulk = q(grain/(1-layer.porosity), 'eroded bulk volume')
    layers = list(work.column.layers)
    if mass == layer.mass_kg:
        layers.pop(); work.pores.pop()
    else:
        layers[-1] = replace(layer, mass_kg=q(layer.mass_kg-mass))
        work.pores[-1] = q(work.pores[-1]-released)
    work.column = replace(work.column, layers=tuple(layers))
    work.free = q(work.free+released)
    work.suspended[layer.material_id] = q(work.suspended.get(layer.material_id, F())+mass)
    work.validate(palette)
    _closed(cell, work, palette)
    receipt = {'operation': 'erode_top', 'material_id': layer.material_id,
        'source_phase': layer.phase, 'mass_kg': mass, 'source_mass_fraction': fraction,
        'solid_volume_m3': grain, 'bulk_volume_m3': bulk,
        'pore_liquid_released_m3': released,
        'exhausted_contact': mass == layer.mass_kg,
        'eta_change_m': work.eta(palette)-cell.eta(palette),
        'momentum_to_bed_m4_s': [0., 0.],
        'momentum_rule': 'STATIONARY_ERODED_GRAINS_AND_PORES_ENTER_WITH_ZERO_MOMENTUM',
        'water_residual_m3': '0', 'material_residual_kg': '0', 'solid_residual_m3': '0'}
    _commit(cell, work)
    return plain(receipt)


def deposit(cell, palette, mid, mass_kg, porosity, evidence):
    """Exact saturated mobile deposition funded by suspension and free water.

This helper is deliberately independent of the dilute-dynamics restriction for
isolated pore oracles. Insufficient material or pore water rejects the whole
transaction; ``evolve`` may apply a common water-availability limit beforehand.
Only fully identical, saturated adjacent mobile parcels may coalesce.
"""
    work = _clone(cell, palette)
    descriptor = _descriptor(mid, palette)
    mass = q(mass_kg, 'deposited dry mass', nonnegative=True)
    phi = q(porosity, 'fresh mobile porosity', nonnegative=True)
    columns._text(evidence, 'mobile deposit evidence')
    if phi >= 1:
        raise ValueError('fresh mobile porosity must be below one')
    if not mass:
        return {'operation': 'deposit', 'material_id': mid, 'mass_kg': '0',
                'pore_liquid_debited_m3': '0', 'momentum_to_bed_m4_s': [0., 0.]}
    if mass > work.suspended.get(mid, F()):
        raise ValueError('deposit exceeds actual suspended material')
    rho = q(descriptor['grain_density_kg_m3'], positive=True)
    grain = q(mass/rho, 'deposited grain volume')
    bulk = q(grain/(1-phi), 'deposited bulk volume')
    pore = q(bulk-grain, 'new saturated pore liquid')
    if pore > work.free:
        raise ValueError('insufficient free liquid for saturated deposition')
    volume = work.volume(palette)
    _, native = regional.p.backend()
    layer = native.Layer(mid, mass, rho, phi, 'mobile_sediment', evidence)
    layers = list(work.column.layers)
    coalesced = False
    if layers:
        top = layers[-1]
        same = (top.material_id, top.grain_density_kg_m3, top.porosity, top.phase, top.evidence) == (
            layer.material_id, layer.grain_density_kg_m3, layer.porosity, layer.phase, layer.evidence)
        if same and work.pores[-1] == top.bulk_volume_m3*top.porosity:
            layers[-1] = replace(top, mass_kg=q(top.mass_kg+mass))
            work.pores[-1] = q(work.pores[-1]+pore)
            coalesced = True
    if not coalesced:
        if len(layers) >= columns.MAX_LAYERS:
            raise ValueError('native coastal layer budget exceeded; no unlike-layer merge')
        layers.append(layer); work.pores.append(pore)
    work.column = replace(work.column, layers=tuple(layers))
    work.free = q(work.free-pore)
    work.suspended[mid] = q(work.suspended[mid]-mass)
    if not work.suspended[mid]:
        del work.suspended[mid]
    remaining = work.volume(palette)
    if remaining != volume-bulk:
        raise ArithmeticError('settling mixture-volume/pore account differs')
    ratio = float(remaining/volume)
    old_momentum = tuple(work.momentum)
    work.momentum = tuple(value*ratio for value in old_momentum) if remaining else (0., 0.)
    work.validate(palette)
    _closed(cell, work, palette)
    if work.eta(palette) != cell.eta(palette):
        raise ArithmeticError('in-place saturated settling changed water level')
    receipt = {'operation': 'deposit', 'material_id': mid, 'mass_kg': mass,
        'solid_volume_m3': grain, 'bulk_volume_m3': bulk, 'porosity': phi,
        'pore_liquid_debited_m3': pore, 'coalesced_identical_saturated_mobile': coalesced,
        'eta_change_m': '0', 'momentum_to_bed_m4_s': [a-b for a, b in zip(old_momentum, work.momentum)],
        'momentum_rule': 'SETTLED_MIXTURE_VOLUME_CARRIES_DONOR_VELOCITY_TO_BED',
        'water_residual_m3': '0', 'material_residual_kg': '0', 'solid_residual_m3': '0'}
    _commit(cell, work)
    return plain(receipt)


def _parameter(value, name, *, positive=False):
    # Owner numerical parameters are declared decimal quantities; source stocks
    # and transferred amounts use q()/represented() instead of this convention.
    value = q(str(value) if type(value) is float else value, name,
              positive=positive, nonnegative=True)
    try:
        floating = float(value)
    except OverflowError as exc:
        raise ValueError(name+' exceeds constitutive binary64 range') from exc
    if not math.isfinite(floating) or (value and not floating):
        raise ValueError(name+' exceeds constitutive binary64 range')
    return value


def _vector(value, name):
    if type(value) not in (list, tuple) or len(value) != 2:
        raise ValueError('explicit two-component '+name+' required')
    try:
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
            raise ValueError('finite binary64 '+name+' required')
        return tuple(map(float, value))
    except OverflowError as exc:
        raise ValueError('finite binary64 '+name+' required') from exc


def _dilute(cell, palette, maximum):
    volume = cell.volume(palette)
    grains = q(volume-cell.free, 'suspended grain volume')
    if volume and grains/volume > maximum:
        raise ValueError('coastal suspended mixture is non-dilute; reduce time step or use another model')


def _response(cell, palette, drag, rho_water, wave, direction, points, critical):
    velocity = cell.velocity(palette)
    speed = math.hypot(*velocity)
    current = tuple(float(rho_water)*float(drag)*speed*v for v in velocity)
    if not all(math.isfinite(v) for v in current):
        raise ValueError('coastal current stress is not finite')
    values = []
    for index in range(points):
        oscillation = math.sqrt(2)*float(wave)*math.sin(2*math.pi*(index+.5)/points)
        stress = math.hypot(*(current[i]+oscillation*direction[i] for i in range(2)))
        value = max(stress/float(critical)-1., 0.)
        if not math.isfinite(value):
            raise ValueError('coastal excess-stress response is not finite')
        values.append(value)
    return math.fsum(values)/points, current


def evolve(cell, palette, dt_s, parameters, forcing):
    """Atomic erosion-then-settling step; caller owns hydraulic time refinement.

Stress is refreshed at each exposed contact. Settling uses one common current-
depth exponential over dt (a disclosed frozen-depth local integration), followed
by a common pore-water feasibility cap. No dry-cell seabed process is applied.
Wind/bottom-drag momentum is handled by the hydraulic solver, not repeated here.
"""
    work = _clone(cell, palette)
    duration = q(dt_s, 'coastal sediment duration', nonnegative=True)
    if type(parameters) is not dict or type(forcing) is not dict:
        raise ValueError('explicit owner sediment parameters and forcing required')
    rho_water = _parameter(parameters['water_density_kg_m3'], 'water density', positive=True)
    drag = _parameter(parameters['bottom_drag_coefficient'], 'bottom drag')
    settling = _parameter(parameters['sediment_settling_m_s'], 'settling speed')
    phi = _parameter(parameters['fresh_mobile_deposit_porosity'], 'fresh mobile porosity')
    if phi >= 1:
        raise ValueError('fresh mobile porosity must be below one')
    maximum = _parameter(parameters['dilute_suspended_solid_volume_fraction_max'], 'dilute limit', positive=True)
    if maximum > F('0.001'):
        raise ValueError('owner dilute-mixture applicability ceiling cannot be increased')
    phase_parameters = {}
    for phase, name in (('bedrock', 'bedrock'), ('mobile_sediment', 'mobile')):
        row = parameters[name]
        phase_parameters[phase] = (_parameter(row['coastal_beta_m_s'], phase+' beta'),
                                  _parameter(row['critical_shear_Pa'], phase+' critical stress', positive=True))
    if _parameter(parameters['mobile']['contrast'], 'mobile contrast') != 1:
        raise ValueError('owner mobile contrast is exactly one; no substituted material law')
    if set(forcing) != {'wind_stress_Pa', 'wave_rms_shear_Pa', 'wave_direction_xy', 'phase_points'}:
        raise ValueError('complete explicit wind/wave/phase forcing required')
    wind = _vector(forcing['wind_stress_Pa'], 'wind stress')
    direction = _vector(forcing['wave_direction_xy'], 'wave direction')
    wave = _parameter(forcing['wave_rms_shear_Pa'], 'wave RMS shear')
    norm = math.hypot(*direction)
    if not math.isfinite(norm):
        raise ValueError('wave direction norm is not finite')
    if wave and not norm:
        raise ValueError('positive wave stirring requires a nonzero direction')
    direction = tuple(v/norm for v in direction) if norm else (0., 0.)
    points = forcing['phase_points']
    if type(points) is not int or points not in (16, 32):
        raise ValueError('owner phase quadrature requires 16 or 32 points')
    _dilute(work, palette, maximum)
    events, eroded, deposited = [], {}, {}
    released = debited = F()
    remaining = duration
    momentum_to_bed = [0., 0.]
    initial_eta = work.eta(palette)
    initial_depth = work.depth(palette)
    wet_initially = bool(work.volume(palette))
    while remaining and work.volume(palette) and work.column.layers:
        if len(events) >= MAX_EVENTS:
            raise ValueError('native sediment event budget exceeded; reduce time step')
        layer = work.column.layers[-1]
        beta, critical = phase_parameters[layer.phase]
        contrast = substrate.bedrock_contrast(layer.material_id, palette) if layer.phase == 'bedrock' else F(1)
        response, current = _response(work, palette, drag, rho_water, wave, direction, points, critical)
        if not (beta and contrast and response):
            break
        # Exact products of the represented constitutive response and actual
        # native geometry; only the transferable amount is rounded below.
        rate = q(beta*contrast*F(response)*work.column.area_m2*
                 layer.grain_density_kg_m3*(1-layer.porosity), 'coastal erosion mass rate', positive=True)
        demand = q(rate*remaining, 'finite erosion demand', nonnegative=True)
        if demand >= layer.mass_kg:
            amount = layer.mass_kg
            used = q(amount/rate, 'time to finite material contact', positive=True)
            rounding = F()
        else:
            amount = min(layer.mass_kg, represented(demand))
            used = remaining
            rounding = amount-demand
        record = erode_top(work, palette, amount)
        record.update({'elapsed_s': str(used), 'remaining_before_s': str(remaining),
            'phase_mean_excess_stress': response, 'current_bed_stress_Pa': list(current),
            'coastal_contrast': str(contrast), 'transfer_representation_error_kg': str(rounding)})
        events.append(record)
        eroded[layer.material_id] = q(eroded.get(layer.material_id, F())+amount)
        released = q(released+F(record['pore_liquid_released_m3']))
        remaining = q(remaining-used, 'unused sediment time', nonnegative=True)
        _dilute(work, palette, maximum)

    proposed, theoretical, water_scale, settling_fraction = {}, {}, F(1), 0.
    erosion_exhausted = not work.column.layers
    settling_depth = work.depth(palette)
    if duration and settling and work.volume(palette) and work.suspended:
        exponent = float(_parameter(settling*duration/settling_depth,
                                    'settling exponent', positive=True))
        settling_fraction = -math.expm1(-exponent)
        for mid, mass in sorted(work.suspended.items()):
            if mass:
                theoretical[mid] = q(mass*F(settling_fraction), 'transient settling demand')
                proposed[mid] = min(mass, represented(theoretical[mid]))
        required = q(sum((mass/density(mid, palette)*phi/(1-phi)
                          for mid, mass in proposed.items()), F()), 'proposed saturated pore debit')
        if required > work.free:
            water_scale = q(work.free/required, 'common pore-water availability factor')
        for mid, demand in proposed.items():
            amount = q(demand*water_scale, 'water-limited settling mass', nonnegative=True)
            if not amount:
                continue
            if len(events) >= MAX_EVENTS:
                raise ValueError('native sediment event budget exceeded; reduce time step')
            record = deposit(work, palette, mid, amount, phi,
                'R19 Water METHOD_R1 transient saturated settling; '+work.column.source_status)
            record.update({'unlimited_constitutive_mass_kg': str(theoretical[mid]),
                'represented_stock_limited_mass_kg': str(demand),
                'transfer_representation_error_kg': str(demand-theoretical[mid]),
                'common_pore_water_availability_factor': str(water_scale)})
            events.append(record)
            deposited[mid] = amount
            debited = q(debited+F(record['pore_liquid_debited_m3']))
            momentum_to_bed = [a+b for a, b in zip(momentum_to_bed, record['momentum_to_bed_m4_s'])]
        _dilute(work, palette, maximum)
    work.validate(palette)
    _closed(cell, work, palette)
    receipt = {'schema': SCHEMA, 'duration_s': duration, 'kind': cell.kind,
        'wet_initially': wet_initially, 'dry_no_seabed_process': not wet_initially,
        'phase_points': points, 'wave_rms_shear_Pa': wave,
        'wave_unit_direction_xy': direction, 'wind_stress_Pa_owned_by_flow': wind,
        'wave_mean_momentum_added_m4_s': [0., 0.],
        'initial_depth_m': initial_depth, 'settling_start_depth_m': settling_depth,
        'initial_eta_m': initial_eta, 'final_eta_m': work.eta(palette),
        'eroded_mass_kg': eroded, 'deposited_mass_kg': deposited,
        'erosion_inactive_remaining_time_s': remaining,
        'finite_bed_exhausted_after_erosion': erosion_exhausted,
        'pore_liquid_released_m3': released, 'pore_liquid_debited_m3': debited,
        'momentum_to_bed_m4_s': momentum_to_bed, 'events': events,
        'settling_fraction_frozen_depth': settling_fraction,
        'settling_water_availability_factor': water_scale,
        'settling_scheme': 'TRANSIENT_FROZEN_CURRENT_DEPTH_EXPONENTIAL_WITH_COMMON_PORE_WATER_CAP',
        'constitutive_precision': 'BINARY64_PHASE_RESPONSE_EXPONENTIAL_AND_TRANSFER_AMOUNTS; EXACT_APPLIED_STOCKS_AND_CONTACTS',
        'transfer_scope': 'CONGRUENT_COMPOSITE_MASS_FRACTIONS_NO_SELECTIVE_SORTING',
        'time_integration_scope': 'EROSION_THEN_SETTLING_LOCAL_SPLIT; DRIVER_OWNS_REFINEMENT',
        'water_residual_m3': '0', 'material_residual_kg': '0', 'solid_residual_m3': '0'}
    _commit(cell, work)
    return plain(receipt)
