"""Material-attached, explicitly supplied roots through native R14 ground changes.

This is a no-growth kinematic contract, not a new crop/root biological law.
Supplied uniform support bands carry integrated uptake weight with material.
Top erosion retires root weight; transported sediment never establishes roots.
The caller explicitly selects noncompensating demand after loss. R13 remains
the only water/enthalpy solver and R14 keeps every existing numerical gate.
"""
from copy import deepcopy
from fractions import Fraction as F
import math
import time
from types import FunctionType, SimpleNamespace

from work.generator_upgrade_r13 import soil, audit as native_audit
from work.generator_upgrade_r14 import pipeline as ground, remap, transport
from work.generator_runtime_r12.store import Store
from . import provenance as p

SCHEMA = 'diadem.rooted-changing-ground-recipe.r22'
ROOT_SCHEMA = 'diadem.material-attached-root-state.r22'
ROOT_FIELDS = {'kinematics', 'demand_policy', 'coordinate', 'vertical_reference',
               'bands', 'layer_accessibility', 'evidence', 'source_status'}
BAND_FIELDS = {'band_id', 'start_m', 'end_m', 'weight', 'distribution'}
POLICY = 'NO_COMPENSATION_FIXED_ORIGINAL_WEIGHTS'


def _q(value, name, *, positive=False, nonnegative=False):
    return remap._q(value, name, positive=positive, nonnegative=nonnegative)


def _geometry(cell):
    """Exact represented absolute support, ordered hydraulic top to bottom."""
    top = _q(cell['base_elevation_m'], 'base elevation') + sum(
        (F(layer['thickness_m']) for layer in cell['model']['layers']), F())
    result = {}
    for layer, material in zip(cell['model']['layers'], cell['materials']):
        low = top-F(layer['thickness_m'])
        result[layer['layer_id']] = (low, top, material)
        top = low
    return result


def _weights(state):
    result = {}
    for row in state['segments']:
        result[row['layer_id']] = result.get(row['layer_id'], F())+F(row['weight'])
    return result


def initialise(cell, supplied, vertical_reference):
    """Convert supplied depth/absolute bands once; never reanchor after change."""
    ground.contracts.exact(supplied, ROOT_FIELDS, 'moving root support')
    soil._evidence(supplied)
    if (supplied['kinematics'] != 'MATERIAL_ATTACHED_NO_GROWTH'
            or supplied['demand_policy'] != POLICY):
        raise ValueError('explicit material-attached no-growth and noncompensating root policy required')
    if supplied['vertical_reference'] != vertical_reference:
        raise ValueError('root and ground vertical references differ')
    if supplied['coordinate'] not in ('DEPTH_BELOW_INITIAL_SURFACE_M', 'ABSOLUTE_ELEVATION_M'):
        raise ValueError('explicit initial depth or absolute root coordinate required')
    geom = _geometry(cell)
    access = supplied['layer_accessibility']
    if type(access) is not dict or set(access) != set(geom) or any(
            x not in ('ACCESSIBLE', 'EXCLUDED') for x in access.values()):
        raise ValueError('complete explicit root layer accessibility required')
    bands = supplied['bands']
    if type(bands) is not list or not 1 <= len(bands) <= 128:
        raise ValueError('one to 128 supplied root support bands required')
    top = max(hi for lo, hi, material in geom.values())
    bottom = min(lo for lo, hi, material in geom.values())
    segments, seen, intervals, original = [], set(), [], F()
    for band in bands:
        ground.contracts.exact(band, BAND_FIELDS, 'root support band')
        soil._text(band['band_id'], 'root band identity')
        if band['band_id'] in seen or band['distribution'] != 'UNIFORM_WITHIN_SUPPLIED_BAND':
            raise ValueError('unique root bands with explicitly supplied uniform distribution required')
        seen.add(band['band_id'])
        a, b = (_q(band[k], 'root band endpoint') for k in ('start_m', 'end_m'))
        weight = _q(band['weight'], 'integrated root weight', positive=True)
        if a >= b:
            raise ValueError('positive ordered root band extent required')
        if supplied['coordinate'] == 'DEPTH_BELOW_INITIAL_SURFACE_M':
            if a < 0:
                raise ValueError('nonnegative root depth required')
            low, high = top-b, top-a
        else:
            low, high = a, b
        if low < bottom or high > top:
            raise ValueError('root band outside supplied initial soil geometry')
        if any(min(high, h) > max(low, l) for l, h in intervals):
            raise ValueError('overlapping root bands would duplicate supplied support')
        intervals.append((low, high)); original += weight
        for identity, (lo, hi, material) in geom.items():
            lower, upper = max(lo, low), min(hi, high)
            if upper <= lower:
                continue
            if access[identity] != 'ACCESSIBLE':
                raise ValueError('root support intersects an explicitly excluded stratum')
            segments.append({'band_id': band['band_id'], 'layer_id': identity,
                'lower_material_fraction': str((lower-lo)/(hi-lo)),
                'upper_material_fraction': str((upper-lo)/(hi-lo)),
                'weight': str(weight*(upper-lower)/(high-low))})
    state = {'schema': ROOT_SCHEMA, 'kinematics': supplied['kinematics'],
        'demand_policy': POLICY, 'original_weight': str(original), 'lost_weight': '0',
        'segments': segments, 'layer_accessibility': deepcopy(access),
        'evidence': supplied['evidence'], 'source_status': supplied['source_status']}
    _check_state(cell, state)
    return state


def _check_state(cell, state):
    if (state['schema'] != ROOT_SCHEMA or state['kinematics'] != 'MATERIAL_ATTACHED_NO_GROWTH'
            or state['demand_policy'] != POLICY):
        raise ValueError('supported versioned root state required')
    soil._evidence(state)
    geom = _geometry(cell); access = state['layer_accessibility']
    if set(access) != set(geom) or any(x not in ('ACCESSIBLE', 'EXCLUDED', 'EXCLUDED_NEW_DEPOSIT') for x in access.values()):
        raise ValueError('root state accessibility differs from current layers')
    original = _q(state['original_weight'], 'original root weight', positive=True)
    lost = _q(state['lost_weight'], 'lost root weight', nonnegative=True)
    retained = F(); slots = set()
    for row in state['segments']:
        identity = row['layer_id']; slot = (row['band_id'], identity)
        if identity not in geom or access[identity] != 'ACCESSIBLE' or slot in slots:
            raise ValueError('root state has duplicate or excluded current support')
        slots.add(slot)
        low, high = (F(row[k]) for k in ('lower_material_fraction', 'upper_material_fraction'))
        if not 0 <= low < high <= 1:
            raise ValueError('root segment outside retained material')
        retained += _q(row['weight'], 'retained root weight', positive=True)
    if retained+lost != original:
        raise ValueError('exact original = retained + retired root account failed')


def move_roots(before, after, *, operation):
    """Carry root coordinates in a layer's material, clipping top erosion only."""
    if operation not in ('DEFORMATION', 'TRANSPORT'):
        raise ValueError('explicit supported root geometry operation required')
    state = before['root_state']; _check_state(before, state)
    if F(before['area_m2']) != F(after['area_m2']) or F(before['base_elevation_m']) != F(after['base_elevation_m']):
        raise ValueError('root remap requires fixed area and basal datum')
    old, new = _geometry(before), _geometry(after)
    if operation == 'DEFORMATION' and list(old) != list(new):
        raise ValueError('deformation changed root material identities')
    retained_fraction = {}
    for identity, (_, _, material) in old.items():
        if identity not in new:
            retained_fraction[identity] = F()
            continue
        target = new[identity][2]
        if any(material[k] != target[k] for k in ('material_id', 'phase')) or F(material['grain_density_kg_m3']) != F(target['grain_density_kg_m3']):
            raise ValueError('retained root material identity changed')
        fraction = F(target['dry_mass_kg_m2'])/F(material['dry_mass_kg_m2'])
        if not 0 < fraction <= 1 or operation == 'DEFORMATION' and fraction != 1:
            raise ValueError('material growth cannot invent roots; explicit geometry adapter required')
        retained_fraction[identity] = fraction
    segments, lost = [], F()
    for row in state['segments']:
        fraction = retained_fraction[row['layer_id']]
        low, high = F(row['lower_material_fraction']), F(row['upper_material_fraction'])
        kept = max(F(), min(high, fraction)-low)
        weight = F(row['weight'])*kept/(high-low)
        lost += F(row['weight'])-weight
        if weight:
            segments.append({**row, 'lower_material_fraction': str(low/fraction),
                'upper_material_fraction': str(min(high, fraction)/fraction), 'weight': str(weight)})
    output = {**deepcopy(state), 'segments': segments,
        'lost_weight': str(F(state['lost_weight'])+lost),
        'layer_accessibility': {identity: state['layer_accessibility'].get(identity, 'EXCLUDED_NEW_DEPOSIT') for identity in new}}
    _check_state(after, output)
    return output, {'operation': operation, 'initial_root_sha256': p.sha(state),
        'final_root_sha256': p.sha(output), 'retired_weight': str(lost),
        'root_weight_residual': '0', 'new_root_weight': '0',
        'scope': 'KINEMATIC_INTEGRATED_UPTAKE_WEIGHT; no root biomass, regrowth or transported-root establishment claim'}


def mapped_forcing(cell, forcing, duration_s, backend=soil, *, remapped=False):
    """Compile current layers to actual native Feddes inputs once, after remap."""
    state = cell['root_state']; _check_state(cell, state)
    result = deepcopy(forcing); result['duration_s'] = duration_s
    if 'surface_evaporation' in result and result['surface_evaporation'] is not None:
        boundary = result['surface_evaporation']
        applicability = boundary.get('applicability')
        if applicability is not None:
            donor = cell['model']['layers'][0]['layer_id']
            if remapped and applicability.get('kind') == 'EXPOSED_UNFROZEN_NONSALINE_SOIL':
                # The supplied exposed/wetted fractions and applicability refer
                # to this column's current surface. Only its geometry-derived
                # donor identity changes; no evaporation-area factor is added.
                applicability['donor_layer_id'] = donor
            elif applicability.get('donor_layer_id') != donor:
                raise ValueError('supplied evaporation donor differs from initial actual surface')
    if 'root_withdrawal_m_s' in result or 'weights' in result.get('uptake', {}):
        raise ValueError('moving roots require supplied potential/Feddes law without stale layer weights')
    if not {'potential_root_demand_m_s', 'uptake'} <= set(result):
        raise ValueError('explicit potential demand and supported native uptake law required')
    potential = _q(result['potential_root_demand_m_s'], 'potential root demand', nonnegative=True)
    per_layer = _weights(state); retained = sum(per_layer.values(), F())
    original = F(state['original_weight']); supported = potential*retained/original
    if retained:
        result['potential_root_demand_m_s'] = float(supported)
        result['uptake']['weights'] = [float(per_layer.get(layer['layer_id'], F())/retained) for layer in cell['model']['layers']]
    else:
        # Native law requires unit weights even for zero demand. The explicitly
        # zero direct-vector route avoids fabricating a surviving root location.
        result.pop('uptake'); result.pop('potential_root_demand_m_s')
        result['root_withdrawal_m_s'] = [0.]*len(cell['model']['layers'])
    backend._event(result, len(cell['model']['layers']))
    return result, {'original_potential_root_demand_m_s': str(potential),
        'supported_potential_root_demand_m_s': str(supported),
        'unsupported_due_to_retired_roots_m_s': str(potential-supported),
        'retained_root_weight': str(retained), 'retired_root_weight': state['lost_weight'],
        'demand_policy': POLICY, 'current_layer_weights': {k: str(v) for k, v in per_layer.items()}}


def _backend(value):
    if value is None or value is soil:
        return soil, native_audit.event
    from . import evaporation
    if value is not evaporation:
        raise ValueError('only source-bound native R13 or R22 evaporation soil backends supported')
    return evaporation, evaporation.audit_event


def validate(spec, *, soil_backend=None):
    backend, _ = _backend(soil_backend)
    ground.contracts.plain(spec)
    ground.contracts.exact(spec, ground.FIELDS | {'roots', 'root_controls'}, 'rooted ground recipe')
    if spec['schema'] != SCHEMA or len(p.encoded(spec)) > ground.p.parent.shared.LIMIT:
        raise ValueError('versioned R22 rooted ground recipe required')
    def synthetic(value):
        if isinstance(value, dict):
            return value.get('source_status') == 'SYNTHETIC TEST' or value.get('status') == 'SYNTHETIC TEST' or any(synthetic(v) for v in value.values())
        return isinstance(value, list) and any(synthetic(v) for v in value)
    if spec['source_status'] == 'WORKING NON-CANON' and synthetic(spec):
        raise ValueError('synthetic root/evaporation inputs cannot be promoted to working-world inputs')
    ground.contracts.exact(spec['root_controls'], {'weight_atol', 'position_atol_m'}, 'root comparison controls')
    for value in spec['root_controls'].values():
        _q(value, 'root comparison allowance', positive=True)
    if type(spec['roots']) is not dict or set(spec['roots']) != set(spec['cells']):
        raise ValueError('one explicit root support per ground cell required')
    cells = deepcopy(spec['cells'])
    for key, cell in cells.items():
        cell['root_state'] = initialise(cell, spec['roots'][key], spec['context']['vertical_reference'])
    # R14 still validates every original ground control and material contract.
    # Its root-free projection is used only for structural validation; actual
    # forcing is separately validated and executed with remapped nonzero roots.
    projection = {k: deepcopy(v) for k, v in spec.items() if k in ground.FIELDS}
    projection['schema'] = ground.SCHEMA
    for event in projection['events']:
        for key, forcing in event['forcing'].items():
            mapped_forcing(cells[key], forcing, event['duration_s'], backend)
            forcing.pop('uptake', None); forcing.pop('potential_root_demand_m_s', None)
            forcing.pop('surface_evaporation', None)
            forcing['root_withdrawal_m_s'] = [0.]*len(cells[key]['model']['layers'])
    ground.validate(projection)
    return cells


def _clone(function, **replacements):
    namespace = dict(function.__globals__); namespace.update(replacements)
    return FunctionType(function.__code__, namespace, function.__name__, function.__defaults__, function.__closure__)


def _audit_interval(before, after, row, controls, audit, backend):
    _clone(ground.audit_interval, soil_audit=SimpleNamespace(event=audit))(before, after, row, controls)
    for key, cell in after.items():
        moved = row['deformation'][key]['column']
        expected, ledger = move_roots(before[key], moved, operation='DEFORMATION')
        if moved['root_state'] != expected or row['root_mapping'][key]['deformation'] != ledger:
            raise ValueError('deformation root state/receipt differs')
        carried = row['transport']['cells'][key]
        expected, ledger = move_roots(moved, carried, operation='TRANSPORT')
        if cell['root_state'] != expected or carried['root_state'] != expected or row['root_mapping'][key]['transport'] != ledger:
            raise ValueError('transport root state/receipt differs')
        solved = row['soil_steps'][key]
        forcing, demand = mapped_forcing(carried, solved['supplied_forcing'], row['duration_s'], backend, remapped=True)
        if solved['forcing'] != forcing or solved['root_demand'] != demand:
            raise ValueError('actual soil uptake differs from supplied demand and changed root support')
    return ground.audit_budget(before, after, [row], controls)


def _trial(spec, cells, event, dt, backend, audit):
    initial = deepcopy(cells); moved, deformation, root_mapping, work = {}, {}, {}, []
    for key, cell in cells.items():
        answer = remap.deform(cell, spec['deformation_laws'], dt, spec['soil_controls'])
        answer['column']['root_state'], root_ledger = move_roots(cell, answer['column'], operation='DEFORMATION')
        moved[key] = answer['column']; deformation[key] = answer
        root_mapping[key] = {'deformation': root_ledger}
        work.append(float(F(answer['ledger']['mechanical_energy_j_m2'])*F(cell['area_m2'])))
    carried = transport.step(moved, spec['connectors'], spec['erosion_laws'], spec['sediment_laws'],
        spec['deposition_templates'], duration_s=dt, seconds_per_year=spec['seconds_per_year'],
        controls=spec['terrain_controls'], soil_controls=spec['soil_controls'], evidence=event['evidence'])
    for key, cell in carried['cells'].items():
        cell['root_state'], ledger = move_roots(moved[key], cell, operation='TRANSPORT')
        root_mapping[key]['transport'] = ledger
    following = deepcopy(carried['cells']); solved = {}; inputs, outputs, input_energy, output_energy = [], [], [], []
    for key, cell in following.items():
        forcing, demand = mapped_forcing(cell, event['forcing'][key], dt, backend, remapped=True)
        result = backend.advance(cell['model'], cell['soil'], forcing, spec['soil_controls'])
        if result['status'] == 'UNKNOWN':
            raise soil.UnknownInput(result['reason'])
        if result['status'] != 'MODELLED':
            raise ground.StepFailure('rooted coupled soil '+key+': '+str(result['reason']))
        audit(cell['model'], forcing, result, spec['soil_controls'])
        a = float(F(cell['area_m2'])); led = result['ledger']; c = cell['model']['constants']
        rain_h = c['water_density_kg_m3']*(c['latent_heat_j_kg']+c['water_heat_capacity_j_kg_k']*(forcing['surface_water_temperature_k']-c['melting_temperature_k']))
        evap = led.get('surface_evaporation_m', 0.)
        evap_h = led.get('surface_evaporation_enthalpy_j_m2', 0.)
        evap_latent = led.get('surface_evaporation_latent_heat_j_m2', 0.)
        runoff_energy = led.get('surface_runoff_enthalpy_j_m2', led['surface_input_m']*rain_h-led['face_advective_energy_j_m2'][0])
        cell['surface_water_m3'] = str(F(cell['surface_water_m3'])+F(a)*F(led['surface_runoff_m']))
        cell['surface_enthalpy_j'] = str(F(cell['surface_enthalpy_j'])+F(a)*F(runoff_energy))
        cell['soil'] = result['final_state']
        inputs.append(a*(led['surface_input_m']+led['bottom_upward_m']))
        outputs.append(a*(led['root_withdrawal_m']+led['bottom_downward_m']+evap))
        # R22 net conductive top face already subtracts latent evaporation.
        # Recover gross supplied heat here before booking the explicit export.
        input_energy.append(a*(led['surface_input_m']*rain_h+led['face_conductive_energy_j_m2'][0]+evap_latent))
        output_energy.append(a*(led['root_enthalpy_j_m2']+led['face_advective_energy_j_m2'][-1]+led['face_conductive_energy_j_m2'][-1]+evap_h+evap_latent))
        solved[key] = {'model': cell['model'], 'forcing': forcing, 'result': result,
            'supplied_forcing': deepcopy(event['forcing'][key]), 'root_demand': demand}
    row = ground.plain({'duration_s': dt, 'initial_cells_sha256': p.sha(initial),
        'final_cells_sha256': p.sha(following), 'final_cells': deepcopy(following),
        'deformation': deformation, 'transport': carried, 'root_mapping': root_mapping, 'soil_steps': solved,
        'water_input_m3': math.fsum(inputs), 'water_output_m3': math.fsum(outputs)+float(F(carried['ledger']['runoff_export_m3']))+float(F(carried['ledger']['sediment_water_export_m3'])),
        'energy_input_j': math.fsum(input_energy)+math.fsum(work),
        'energy_output_j': math.fsum(output_energy)+float(F(carried['ledger']['runoff_export_enthalpy_j']))+float(F(carried['ledger']['sediment_enthalpy_export_j'])),
        'mechanical_energy_j': math.fsum(work), 'routes_before': carried['routes_before'], 'routes_after': carried['routes_after']})
    row['accounts'] = _audit_interval(initial, following, row, spec['coupling_controls'], audit, backend)
    return following, row


def _positions(cell):
    geom = _geometry(cell); result = {}
    for row in cell['root_state']['segments']:
        low, high, _ = geom[row['layer_id']]; width = high-low
        result[row['band_id'], row['layer_id']] = (float(F(row['weight'])),
            float(low+width*F(row['lower_material_fraction'])), float(low+width*F(row['upper_material_fraction'])))
    return result


def _compare(spec, baseline, full, half, full_rows, half_rows):
    _, ratios = ground.compare(spec, baseline, full, half, full_rows, half_rows)
    relative = ground.number(spec['coupling_controls']['relative_tolerance'])
    wa = ground.number(spec['root_controls']['weight_atol']); pa = ground.number(spec['root_controls']['position_atol_m'])
    for key in full:
        aa, bb = _positions(full[key]), _positions(half[key])
        for slot in set(aa) | set(bb):
            a, b = aa.get(slot), bb.get(slot)
            aw, bw = 0. if a is None else a[0], 0. if b is None else b[0]
            ratios[key+'/root_weight/'+str(slot)] = abs(aw-bw)/(wa+relative*max(aw, bw))
            if a is not None and b is not None:
                # Absolute datum magnitude does not loosen a support-position gate.
                scale = max(a[2]-a[1], b[2]-b[1])
                ratios[key+'/root_position/'+str(slot)] = max(abs(a[1]-b[1]), abs(a[2]-b[2]))/(pa+relative*scale)
    return max(ratios.values(), default=0.), ratios


def advance_event(spec, cells, event, *, soil_backend=None):
    backend, audit = _backend(soil_backend)
    def trial(s, c, e, dt):
        return _trial(s, c, e, dt, backend, audit)
    return _clone(ground.advance_event, _trial=trial, compare=_compare)(spec, cells, event)


def audit_event(row, controls, *, soil_backend=None):
    backend, audit = _backend(soil_backend)
    def interval(before, after, step, c):
        return _audit_interval(before, after, step, c, audit, backend)
    return _clone(ground.audit_event, audit_interval=interval)(row, controls)


def run(spec, *, soil_backend=None, stop_after=None, resume=None, store=None):
    """Full recipe execution with versioned source-bound event checkpoints."""
    started = time.perf_counter(); spec = deepcopy(spec)
    initial = validate(spec, soil_backend=soil_backend)
    backend, _ = _backend(soil_backend)
    binding = p.identity(moving_ground=True); source_sha = p.sha(binding)
    recipe_sha = p.sha({'recipe': spec, 'soil_backend': backend.__name__})
    if store is not None and (type(store) is not Store or store.namespace != source_sha):
        raise ValueError('exact R22 source-bound ground Store required')
    count = len(spec['events']) if stop_after is None else stop_after
    if type(count) is not int or not 0 <= count <= len(spec['events']):
        raise ValueError('bounded complete-event root cursor required')
    current, rows, reused = deepcopy(initial), [], 0
    def certificate(index, before, row):
        return (p.sha({'source': source_sha, 'recipe': recipe_sha, 'index': index, 'initial': p.sha(before)}),
            {'schema': 'diadem.verified-rooted-ground-event.r22', 'row_sha256': p.sha(row)})
    if resume is not None:
        ground.contracts.exact(resume, {'schema', 'source_sha256', 'recipe_sha256', 'state_sha256', 'state'}, 'rooted ground checkpoint')
        if (resume['schema'] != 'diadem.rooted-ground-checkpoint.r22' or resume['source_sha256'] != source_sha
                or resume['recipe_sha256'] != recipe_sha or resume['state_sha256'] != p.sha(resume['state'])):
            raise ValueError('rooted checkpoint source/recipe/state differs')
        saved = resume['state']
        ground.contracts.exact(saved, {'completed_events', 'continuing_state', 'accepted_events'}, 'rooted checkpoint state')
        if type(saved['completed_events']) is not int or not 0 <= saved['completed_events'] <= count or len(saved['accepted_events']) != saved['completed_events']:
            raise ValueError('rooted checkpoint event inventory/cursor differs')
        if store is None:
            if run(spec, soil_backend=soil_backend, stop_after=saved['completed_events'])['scientific']['checkpoint'] != resume:
                raise ValueError('rooted checkpoint differs from scientific replay')
        else:
            for i, row in enumerate(saved['accepted_events']):
                key, value = certificate(i, current, row)
                if row['initial_cells'] != current or row['event_id'] != spec['events'][i]['event_id'] or store.get(key) != value:
                    raise ValueError('rooted event has no matching source-bound certificate')
                audit_event(row, spec['coupling_controls'], soil_backend=soil_backend)
                current = deepcopy(row['final_cells'])
            if current != saved['continuing_state']:
                raise ValueError('rooted cached endpoint differs')
            reused = saved['completed_events']
        current, rows = deepcopy(saved['continuing_state']), deepcopy(saved['accepted_events'])
    status, reason, warnings = None, None, []
    if spec['source_status'] == 'UNKNOWN':
        status, reason = 'UNKNOWN', 'rooted ground scenario evidence is UNKNOWN'
    for i in range(len(rows), count):
        if status is not None:
            break
        try:
            if spec['events'][i]['source_status'] == 'UNKNOWN':
                raise soil.UnknownInput('rooted ground event evidence is UNKNOWN')
            following, row = advance_event(spec, current, spec['events'][i], soil_backend=soil_backend)
            audit_event(row, spec['coupling_controls'], soil_backend=soil_backend)
            ground.audit_budget(initial, following, [s for r in [*rows, row] for s in r['steps']], spec['coupling_controls'])
            p.verify(binding)
        except soil.UnknownInput as error:
            status, reason = 'UNKNOWN', str(error); break
        except (ValueError, ArithmeticError) as error:
            status, reason = 'NUMERICAL_FAILURE', str(error); break
        if store is not None:
            key, value = certificate(i, current, row); store.put(key, value)
            if store.get(key) != value:
                warnings.append('Rooted event lacks reusable certificate: '+row['event_id'])
        current = following; rows.append(row)
    accounts = ground.audit_budget(initial, current, [s for r in rows for s in r['steps']], spec['coupling_controls'])
    saved = {'completed_events': len(rows), 'continuing_state': current, 'accepted_events': rows}
    cp = {'schema': 'diadem.rooted-ground-checkpoint.r22', 'source_sha256': source_sha,
        'recipe_sha256': recipe_sha, 'state_sha256': p.sha(saved), 'state': saved}
    complete = status is None and len(rows) == len(spec['events'])
    p.verify(binding)
    return {'scientific': {'schema': 'diadem.rooted-changing-ground.r22',
        'status': status or ('MODELLED_ROOTED_GROUND_FEEDBACK' if complete else 'STOPPED'),
        'source_status': spec['source_status'], 'source_sha256': source_sha, 'recipe_sha256': recipe_sha,
        'context': spec['context'], 'completed_events': len(rows), 'events': rows, 'accounts': accounts,
        'final_cells': current if complete else None, 'checkpoint': cp, 'reason': reason,
        'whole_diadem_year_verified': False, 'production_authorised': False, 'canon_changed': False},
        'execution': {'identity': binding, 'elapsed_wall_seconds': time.perf_counter()-started,
            'reused_events': reused, 'cache_warnings': warnings, 'cache_stats': None if store is None else store.stats}}
