"""Conservative changing-packing adapter for the unchanged R13 soil law.

Area is fixed. Dry mass, dry heat capacity, total water and common-datum
enthalpy are extensive per square metre. Packing is a supplied reduced
kinematic hypothesis, NOT ice-lens mechanics, a 9% phase-density expansion,
or a complete mechanical/gravitational energy model. Mechanical heating or
cooling is an explicit signed port. No water is silently expelled or invented.
"""
from copy import deepcopy
from fractions import Fraction as F
import math

from work.generator_upgrade_r13 import soil


MATERIAL = {'material_id', 'phase', 'grain_density_kg_m3', 'dry_mass_kg_m2', 'evidence'}
TARGET = {'layer', 'material', 'water_m', 'enthalpy_j_m2', 'dry_heat_capacity_j_m2_k', 'head_guess_m'}
LAW = {'reference_specific_volume_m3_kg', 'reference_water_m3_kg', 'reference_ice_m3_kg',
       'water_volume_response', 'ice_volume_response', 'relaxation_time_s',
       'min_porosity', 'max_porosity', 'reference_porosity', 'reference_ksat_m_s',
       'reference_alpha_per_m', 'ksat_porosity_exponent', 'alpha_porosity_exponent',
       'mechanical_energy_per_bulk_volume_j_m3', 'evidence', 'source_status'}


def _exact(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('exact '+label+' fields required')


def _q(value, label, *, positive=False, nonnegative=False):
    if value is None:
        raise soil.UnknownInput(label+' is UNKNOWN')
    # Both 8192-bit integers, their signs and separator fit within 5000 characters.
    if type(value) not in (int, float, str, F) or isinstance(value, bool) or isinstance(value, str) and len(value) > 5000:
        raise ValueError('bounded represented '+label+' required')
    try:
        answer = F(value)
        represented = float(answer)
    except (ValueError, OverflowError, ZeroDivisionError) as exc:
        raise ValueError('finite '+label+' required') from exc
    if max(answer.numerator.bit_length(), answer.denominator.bit_length()) > 8192 or not math.isfinite(represented):
        raise ValueError('bounded finite '+label+' required')
    if positive and answer <= 0 or nonnegative and answer < 0:
        raise ValueError('positive/nonnegative '+label+' required')
    return answer


def _roundoff(a, b, label):
    """64 ULP of represented volume/capacity, not a physical packing tolerance."""
    scale = max(abs(float(a)), abs(float(b)))
    allowance = F(64*math.ulp(scale))
    if abs(a-b) > allowance:
        raise ValueError(label+' does not close within 64 represented ULP')
    return a-b


def _material(value):
    _exact(value, MATERIAL, 'material')
    for key in ('material_id', 'phase', 'evidence'):
        soil._text(value[key], key)
    return (_q(value['dry_mass_kg_m2'], 'dry material mass', positive=True),
            _q(value['grain_density_kg_m3'], 'grain density', positive=True))


def layer_stocks(model, state, materials):
    """Exact represented extensive stocks in the original top-to-bottom order."""
    soil._model(model)
    soil._read_state(model, state)
    if type(materials) is not list or len(materials) != len(model['layers']):
        raise ValueError('one explicit material for every hydraulic layer required')
    rows = []
    for i, (layer, material) in enumerate(zip(model['layers'], materials)):
        mass, density = _material(material)
        dz, phi = F(layer['thickness_m']), F(layer['theta_s'])
        if not 0 < phi < 1:
            raise ValueError('changing packing requires positive dry solid and subunit porosity')
        _roundoff(mass/density, (1-phi)*dz, 'dry solid geometry')
        rows.append({'layer': deepcopy(layer), 'material': deepcopy(material),
            'water_m': str(F(state['total_water'][i])*dz),
            'enthalpy_j_m2': str(F(state['enthalpy_j_m2'][i])),
            'dry_heat_capacity_j_m2_k': str(F(layer['dry_heat_capacity_j_m3_k'])*dz),
            'head_guess_m': state['head_m'][i]})
    return rows


def _vg_inverse(layer, deficit):
    """Inverse VG using its complementary pore deficit near saturation."""
    span = F(layer['theta_s'])-F(layer['theta_r'])
    if not 0 < deficit < span:
        raise ValueError('strictly unsaturated above-residual target required')
    # Choose the small operand: neither 1-Se at saturation nor Se at the dry
    # end should disappear merely because its complement rounds to one.
    logse = math.log1p(-float(deficit/span)) if deficit < span/2 else math.log(float((span-deficit)/span))
    m = 1-1/layer['vg_n']
    h = -math.expm1(-logse/m)**(1/layer['vg_n'])/layer['vg_alpha_per_m']
    if not math.isfinite(h) or h >= 0:
        raise ValueError('unrepresentable inverse retention target')
    return h


def _invert(model, layer, water, energy, guess, controls):
    """Bounded scalar enthalpy solve with the exact selected R13 phase law."""
    dz, phi, residual = F(layer['thickness_m']), F(layer['theta_s']), F(layer['theta_r'])
    theta = water/dz
    if theta > phi:
        raise ValueError('pore-volume overflow needs an explicit water/enthalpy export port')
    if theta <= residual:
        raise ValueError('at/below-residual remap needs an explicit redistribution port')
    saturated = theta == phi
    guess = float(_q(guess, 'pressure seed'))
    if saturated and guess < 0:
        raise ValueError('saturated stock needs an explicit nonnegative unvalidated pressure seed')
    tm = model['constants']['melting_temperature_k']
    single = {**model, 'layers': [layer]}
    cache = {}
    def evaluate(offset):
        if offset in cache:
            return cache[offset]
        if len(cache) >= controls['max_nonlinear_evaluations']:
            raise ValueError('remap enthalpy inversion evaluation budget exhausted')
        if saturated:
            head = guess
        else:
            deficit = phi-theta
            if model.get('freezing_model', soil.DALL_AMICO) == soil.PAINTER_KARRA and offset < 0:
                c = model['constants']
                cold_head = model['clapeyron_beta']*c['latent_heat_j_kg']*offset/(c['gravity_m_s2']*tm)
                cold_theta = F(soil._vg(layer, cold_head)[0])
                if theta > cold_theta:
                    # Eq18--19 at fixed TOTAL stock, expressed without losing
                    # a microscopic unsaturated deficit to phi-A cancellation.
                    deficit = phi*deficit/(cold_theta+deficit)
            head = _vg_inverse(layer, deficit)
        if not controls['min_head_m'] < head < controls['max_head_m']:
            raise ValueError('remapped head outside declared numerical bounds')
        props = soil._properties(single, [head], [tm+offset], temperature_offset=[offset])
        value = (F(props['energy'][0])-energy, head, props)
        cache[offset] = value
        return value
    lower = math.nextafter(controls['min_temperature_k']-tm, math.inf)
    upper = math.nextafter(controls['max_temperature_k']-tm, -math.inf)
    if saturated and guess > 0 and model.get('freezing_model', soil.DALL_AMICO) == soil.DALL_AMICO:
        lower = max(lower, 0.)  # The default law explicitly excludes frozen +pressure.
    low = evaluate(lower); high = evaluate(upper)
    if low[0] > 0 or high[0] < 0:
        raise ValueError('target enthalpy outside admitted temperature/phase bounds')
    best_offset, best = (lower, low) if abs(low[0]) < abs(high[0]) else (upper, high)
    # Allocate the existing whole-column allowances across all target layers.
    eatol = min(F(controls['nonlinear_energy_atol_j_m2']),
                F(controls['energy_atol_j_m2'])/(4*controls['max_steps']))/len(model['layers'])
    def accurate():
        temperature_allowance = .01*(controls['temperature_atol_k']+controls['relative_tolerance']*abs(best_offset))
        head_allowance = .01*(controls['head_atol_m']+controls['relative_tolerance']*abs(best[1]))
        return (abs(best[0]) <= eatol and upper-lower <= temperature_allowance
                and abs(high[1]-low[1]) <= head_allowance)
    while not accurate():
        middle = lower+(upper-lower)/2
        if middle == lower or middle == upper:
            raise ValueError('enthalpy inverse reached its representational floor')
        value = evaluate(middle)
        if abs(value[0]) < abs(best[0]):
            best_offset, best = middle, value
        if value[0] < 0:
            lower, low = middle, value
        else:
            upper, high = middle, value
    represented_water = F(best[2]['theta'][0])*dz
    if abs(represented_water-water) > F(controls['water_atol_m'])/len(model['layers']):
        raise ValueError('water inverse representation exceeds declared allowance')
    return best[1], best_offset, saturated, len(cache)


def rebuild(base_model, targets, controls, *, elapsed_seconds, mechanical_energy_j_m2=None):
    """Repack carried targets and invert W,E; never consumes forcing or time.

    Changed saturated heads are ONLY caller-provided numerical seeds. The next
    actual R13 solve must resolve them before current-pressure/drainage claims.
    Liquid and ice need not separately survive phase re-equilibration; their
    total water and the common-datum enthalpy do survive, plus booked work.
    """
    soil._model(base_model)
    if type(targets) is not list or not 1 <= len(targets) <= 128:
        raise ValueError('one to128 explicit target layers required')
    _q(elapsed_seconds, 'unchanged elapsed time', nonnegative=True)
    mechanical = [0]*len(targets) if mechanical_energy_j_m2 is None else mechanical_energy_j_m2
    if type(mechanical) is not list or len(mechanical) != len(targets):
        raise ValueError('one explicit mechanical energy port per target required')
    model = deepcopy(base_model); model['layers'] = []
    materials, quantities, layer_ledgers = [], [], []
    for target, work in zip(targets, mechanical):
        _exact(target, TARGET, 'remap target')
        layer = deepcopy(target['layer']); material = deepcopy(target['material'])
        mass, density = _material(material)
        phi = _q(layer['theta_s'], 'target porosity', positive=True)
        if phi >= 1:
            raise ValueError('target packing requires positive dry solid fraction')
        depth = mass/density/(1-phi)
        represented_depth = float(depth)
        if not math.isfinite(represented_depth) or represented_depth <= 0:
            raise ValueError('positive represented target thickness required; no layer clipping')
        capacity = _q(target['dry_heat_capacity_j_m2_k'], 'carried dry heat capacity', positive=True)
        layer['thickness_m'] = represented_depth
        layer['dry_heat_capacity_j_m3_k'] = float(capacity/F(represented_depth))
        geometry_error = _roundoff(F(represented_depth)*(1-phi), mass/density, 'target solid geometry')
        capacity_error = _roundoff(F(layer['dry_heat_capacity_j_m3_k'])*F(represented_depth), capacity, 'dry heat capacity')
        water = _q(target['water_m'], 'carried total water', nonnegative=True)
        energy = _q(target['enthalpy_j_m2'], 'carried enthalpy')
        work = _q(work, 'mechanical energy port')
        model['layers'].append(layer); materials.append(material)
        quantities.append((water, energy, work, capacity, target['head_guess_m']))
        layer_ledgers.append({'layer_id': layer['layer_id'], 'dry_mass_kg_m2': str(mass),
            'solid_volume_residual_m': str(geometry_error), 'dry_capacity_residual_j_m2_k': str(capacity_error),
            'thickness_m_exact': str(depth), 'thickness_m_represented': represented_depth,
            'mechanical_energy_j_m2': str(work)})
    soil._model(model); soil._controls(controls, model)
    heads, offsets, unresolved = [], [], []
    for layer, values, ledger in zip(model['layers'], quantities, layer_ledgers):
        water, energy, work, capacity, guess = values
        head, offset, saturated, count = _invert(model, layer, water, energy+work, guess, controls)
        heads.append(head); offsets.append(offset)
        if saturated:
            unresolved.append(layer['layer_id'])
        ledger.update(inverse_evaluations=count, pressure_is_unvalidated_seed=saturated)
    tm = model['constants']['melting_temperature_k']
    state = soil.initial_state(model, heads, [tm+x for x in offsets],
                               temperature_offset_k=offsets, elapsed_seconds=float(_q(elapsed_seconds, 'elapsed')))
    initial_water = sum((x[0] for x in quantities), F())
    initial_energy = sum((x[1] for x in quantities), F())
    work = sum((x[2] for x in quantities), F())
    final_water = sum((F(w)*F(layer['thickness_m']) for w, layer in zip(state['total_water'], model['layers'])), F())
    final_energy = sum((F(x) for x in state['enthalpy_j_m2']), F())
    water_error, energy_error = final_water-initial_water, final_energy-initial_energy-work
    if abs(water_error) > F(controls['water_atol_m']) or abs(energy_error) > F(controls['energy_atol_j_m2']):
        raise ValueError('whole-column remap conservation allowance exceeded')
    ledger = {'initial_target_water_m': str(initial_water), 'final_water_m': str(final_water),
        'water_residual_m': str(water_error), 'initial_target_enthalpy_j_m2': str(initial_energy),
        'mechanical_energy_j_m2': str(work), 'final_enthalpy_j_m2': str(final_energy),
        'energy_residual_j_m2': str(energy_error),
        'dry_mass_kg_m2': str(sum((_q(x['dry_mass_kg_m2'], 'mass') for x in materials), F())),
        'dry_capacity_residual_j_m2_k': str(sum((F(x['dry_capacity_residual_j_m2_k']) for x in layer_ledgers), F())),
        'pressure_requires_resolution': bool(unresolved), 'unvalidated_pressure_layer_ids': unresolved,
        'elapsed_seconds_before': float(_q(elapsed_seconds, 'elapsed')), 'elapsed_seconds_after': state['elapsed_seconds'],
        'layers': layer_ledgers, 'geometry_roundoff_policy': '64_ULP_REPRESENTED_SOLID_VOLUME_AND_DRY_CAPACITY',
        'scope': 'FIXED_AREA_CONSERVATIVE_REPACKING_WITH_EXPLICIT_MECHANICAL_ENERGY_PORT'}
    return {'model': model, 'soil': state, 'materials': materials, 'ledger': ledger}


def deform(column, laws, duration_s, controls):
    """Explicit relaxed moisture/ice-specific-volume hypothesis, not mechanics."""
    if type(column) is not dict or not {'area_m2', 'base_elevation_m', 'model', 'soil', 'materials'} <= set(column):
        raise ValueError('bound column geometry/soil/material records required')
    _q(column['area_m2'], 'fixed column area', positive=True)
    _q(column['base_elevation_m'], 'base elevation')
    dt = _q(duration_s, 'deformation interval', nonnegative=True)
    if type(laws) is not dict:
        raise soil.UnknownInput('explicit per-material deformation laws required')
    stocks = layer_stocks(column['model'], column['soil'], column['materials'])
    targets, ports, diagnostics = deepcopy(stocks), [], []
    for i, (old, target) in enumerate(zip(stocks, targets)):
        mid = old['material']['material_id']
        if mid not in laws or laws[mid] is None:
            raise soil.UnknownInput('deformation law UNKNOWN for '+mid)
        law = laws[mid]; _exact(law, LAW, 'deformation law'); soil._evidence(law)
        values = {key: _q(law[key], key) for key in LAW-{'evidence', 'source_status'}}
        mass, density = _material(old['material'])
        dz = F(old['layer']['thickness_m'])
        water, ice = F(old['water_m'])/mass, F(column['soil']['ice_water'][i])*dz/mass
        vref, tau = values['reference_specific_volume_m3_kg'], values['relaxation_time_s']
        minimum, maximum, phiref = (values[k] for k in ('min_porosity', 'max_porosity', 'reference_porosity'))
        if (vref <= 0 or tau <= 0 or not 0 < minimum <= phiref <= maximum < 1
                or values['reference_water_m3_kg'] < 0 or values['reference_ice_m3_kg'] < 0
                or values['reference_ksat_m_s'] < 0 or values['reference_alpha_per_m'] <= 0):
            raise ValueError('invalid admitted deformation/reference domain')
        _roundoff(vref*(1-phiref), 1/density, 'reference specific-volume/porosity law')
        target_v = vref+values['water_volume_response']*(water-values['reference_water_m3_kg'])+values['ice_volume_response']*(ice-values['reference_ice_m3_kg'])
        if target_v <= 0 or not minimum <= 1-1/(density*target_v) <= maximum:
            raise ValueError('specific-volume target outside admitted porosity; no clipping')
        relaxation = F(-math.expm1(-float(dt/tau)))
        new_v = dz/mass+relaxation*(target_v-dz/mass)
        phi = 1-1/(density*new_v)
        if not minimum <= phi <= maximum:
            raise ValueError('relaxed packing outside admitted porosity')
        new_depth = mass*new_v
        layer = target['layer']; layer['theta_s'] = float(phi)
        # Residual pore-water volume per dry mass is transported, not recreated
        # by reusing an old volumetric residual after the layer thickness changes.
        layer['theta_r'] = float(F(old['layer']['theta_r'])*dz/new_depth)
        layer['saturated_conductivity_m_s'] = float(values['reference_ksat_m_s'])*float(phi/phiref)**float(values['ksat_porosity_exponent'])
        layer['vg_alpha_per_m'] = float(values['reference_alpha_per_m'])*float(phi/phiref)**float(values['alpha_porosity_exponent'])
        # The changed hydraulic coefficients carry the supplied hypothesis's
        # evidence/status, never an implied calibration inherited from a parent.
        layer['evidence'] = law['evidence']; layer['source_status'] = law['source_status']
        port = values['mechanical_energy_per_bulk_volume_j_m3']*(new_depth-dz)
        ports.append(str(port))
        diagnostics.append({'layer_id': layer['layer_id'], 'material_id': mid,
            'old_specific_volume_m3_kg': str(dz/mass), 'target_specific_volume_m3_kg': str(target_v),
            'relaxation_fraction': float(relaxation), 'new_specific_volume_m3_kg': str(new_v),
            'bulk_depth_change_m': str(new_depth-dz), 'mechanical_energy_j_m2': str(port),
            'law': deepcopy(law)})
    rebuilt = rebuild(column['model'], targets, controls, elapsed_seconds=column['soil']['elapsed_seconds'], mechanical_energy_j_m2=ports)
    changed = deepcopy(column)
    for key in ('model', 'soil', 'materials'):
        changed[key] = rebuilt[key]
    return {'status': 'MODELLED', 'column': changed, 'ledger': rebuilt['ledger'], 'deformation': diagnostics,
        'scope': 'SUPPLIED_RELAXED_KINEMATIC_PACKING_EQUAL_PHASE_DENSITY; NOT_ICE_LENS_OR_FULL_MECHANICS'}
