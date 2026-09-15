"""Bounded seasonal ground/transport/soil coupling on supplied column supports."""
from copy import deepcopy
from fractions import Fraction as F
import math
import time
from work.generator_upgrade_r13 import soil, audit as soil_audit, year as contracts
from work.generator_runtime_r12.store import Store
from . import provenance as p, remap, transport

SCHEMA = 'diadem.changing-ground-recipe.r14'
FIELDS = {'schema', 'scenario_id', 'context', 'source_status', 'evidence',
          'seconds_per_year', 'cells', 'connectors', 'erosion_laws', 'sediment_laws',
          'deposition_templates', 'deformation_laws', 'soil_controls',
          'terrain_controls', 'coupling_controls', 'events'}
CONTROLS = {'initial_step_s', 'min_step_s', 'max_step_s', 'max_attempts',
            'relative_tolerance', 'height_atol_m', 'water_atol_m3', 'energy_atol_j',
            'mass_atol_kg', 'head_integral_atol_m2', 'temperature_integral_atol_k_m',
            'budget_water_atol_m3', 'budget_energy_atol_j'}
CELL = {'area_m2', 'base_elevation_m', 'model', 'soil', 'materials',
        'surface_water_m3', 'surface_enthalpy_j', 'surface_residence_seconds'}


class StepFailure(ValueError):
    pass


def number(value):
    if type(value) not in (int, float, str):
        raise ValueError('explicit finite ground number required')
    out = float(F(value))
    if not math.isfinite(out):
        raise ValueError('finite ground number required')
    return out


def plain(value):
    if isinstance(value, F):
        return str(value)
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def validate(spec):
    contracts.plain(spec)
    contracts.exact(spec, FIELDS, 'ground recipe')
    if spec['schema'] != SCHEMA or len(p.encoded(spec)) > p.parent.shared.LIMIT:
        raise ValueError('bounded R14 ground recipe required')
    contracts.exact(spec['context'], contracts.FRAME, 'ground frame')
    for value in (*spec['context'].values(), spec['scenario_id'], spec['evidence']):
        contracts.text(value)
    if spec['scenario_id'] != spec['context']['scenario_id']:
        raise ValueError('ground scenario/frame differs')
    if spec['source_status'] not in ('SYNTHETIC TEST', 'WORKING NON-CANON', 'UNKNOWN'):
        raise ValueError('explicit ground source status required')
    def synthetic(value):
        if isinstance(value, dict):
            return (value.get('source_status') == 'SYNTHETIC TEST' or value.get('status') == 'SYNTHETIC TEST'
                    or any(synthetic(v) for v in value.values()))
        return isinstance(value, list) and any(synthetic(v) for v in value)
    if spec['source_status'] == 'WORKING NON-CANON' and synthetic(spec):
        raise ValueError('synthetic ground inputs cannot be promoted to a working-world recipe')
    if number(spec['seconds_per_year']) <= 0:
        raise ValueError('explicit positive seconds per model year required')
    c = spec['coupling_controls']
    contracts.exact(c, CONTROLS, 'ground coupling controls')
    for key in CONTROLS-{'max_attempts', 'relative_tolerance'}:
        if number(c[key]) <= 0:
            raise ValueError('positive coupling control required: '+key)
    if (type(c['max_attempts']) is not int or not 1 <= c['max_attempts'] <= 100000
            or not 0 <= number(c['relative_tolerance']) < 1
            or not number(c['min_step_s']) <= number(c['initial_step_s']) <= number(c['max_step_s'])):
        raise ValueError('bounded ordered ground numerical controls required')
    if type(spec['cells']) is not dict or not 1 <= len(spec['cells']) <= 32:
        raise ValueError('one to 32 named ground supports required')
    clocks = set()
    for key, cell in spec['cells'].items():
        contracts.text(key); contracts.exact(cell, CELL, 'ground cell')
        if number(cell['area_m2']) <= 0 or number(cell['surface_residence_seconds']) <= 0:
            raise ValueError('positive area and transit residence time required')
        number(cell['base_elevation_m'])
        if number(cell['surface_water_m3']) < 0:
            raise ValueError('nonnegative antecedent runoff required')
        number(cell['surface_enthalpy_j'])
        if number(cell['surface_water_m3']) == 0 and number(cell['surface_enthalpy_j']) != 0:
            raise ValueError('empty transit water cannot carry enthalpy')
        soil._model(cell['model']); soil._controls(spec['soil_controls'], cell['model'])
        soil._read_state(cell['model'], cell['soil'])
        remap.layer_stocks(cell['model'], cell['soil'], cell['materials'])
        clocks.add(cell['soil']['elapsed_seconds'])
    if len(clocks) != 1:
        raise ValueError('ground cell clocks must agree')
    if type(spec['events']) is not list or not 1 <= len(spec['events']) <= 8192:
        raise ValueError('bounded explicit seasonal event list required')
    names = set()
    for event in spec['events']:
        contracts.exact(event, ('event_id', 'duration_s', 'forcing', 'evidence', 'source_status'), 'ground event')
        contracts.text(event['event_id']); contracts.text(event['evidence'])
        if event['event_id'] in names or number(event['duration_s']) <= 0:
            raise ValueError('positive unique chronological ground events required')
        names.add(event['event_id'])
        if event['source_status'] not in ('SYNTHETIC TEST', 'WORKING NON-CANON', 'UNKNOWN'):
            raise ValueError('explicit ground event source status required')
        if set(event['forcing']) != set(spec['cells']):
            raise ValueError('one explicit soil forcing per ground cell required')
        for key, forcing in event['forcing'].items():
            if number(forcing['duration_s']) != number(event['duration_s']):
                raise ValueError('ground/core event duration differs')
            # Index-based roots must not jump onto a newly deposited layer.
            if ('uptake' in forcing or number(forcing.get('potential_root_demand_m_s', 0)) != 0
                    or any(number(v) != 0 for v in forcing.get('root_withdrawal_m_s', []))):
                raise ValueError('nonzero roots require a geometry-aware biological adapter')
            soil._event(forcing, len(spec['cells'][key]['model']['layers']))


def stocks(cells):
    """Independent extensive accounts, including the non-ponded transit store."""
    water, energy, masses = [], [], {}
    for cell in cells.values():
        area = number(cell['area_m2'])
        water.append(number(cell['surface_water_m3']))
        energy.append(number(cell['surface_enthalpy_j']))
        model, state = cell['model'], cell['soil']
        for i, (layer, material) in enumerate(zip(model['layers'], cell['materials'])):
            water.append(area*layer['thickness_m']*state['total_water'][i])
            energy.append(area*state['enthalpy_j_m2'][i])
            m = material['material_id']
            masses[m] = masses.get(m, F())+F(material['dry_mass_kg_m2'])*F(cell['area_m2'])
    return {'water_m3': math.fsum(water), 'enthalpy_j': math.fsum(energy),
            'material_kg': {key: float(value) for key, value in masses.items()}}


def _trial(spec, cells, event, dt):
    initial = deepcopy(cells); moved, deformation, work = {}, {}, []
    for key, cell in cells.items():
        answer = remap.deform(cell, spec['deformation_laws'], dt, spec['soil_controls'])
        moved[key] = answer['column']; deformation[key] = answer
        work.append(number(answer['ledger']['mechanical_energy_j_m2'])*number(cell['area_m2']))
    carried = transport.step(moved, spec['connectors'], spec['erosion_laws'],
        spec['sediment_laws'], spec['deposition_templates'], duration_s=dt,
        seconds_per_year=spec['seconds_per_year'], controls=spec['terrain_controls'],
        soil_controls=spec['soil_controls'], evidence=event['evidence'])
    following = deepcopy(carried['cells']); solved = {}; inputs, outputs = [], []
    input_energy, output_energy = [], []
    for key, cell in following.items():
        forcing = deepcopy(event['forcing'][key]); forcing['duration_s'] = dt
        if 'root_withdrawal_m_s' in forcing:
            forcing['root_withdrawal_m_s'] = [0.]*len(cell['model']['layers'])
        result = soil.advance(cell['model'], cell['soil'], forcing, spec['soil_controls'])
        if result['status'] == 'UNKNOWN':
            raise soil.UnknownInput(result['reason'])
        if result['status'] != 'MODELLED':
            raise StepFailure('coupled soil '+key+': '+str(result['reason']))
        soil_audit.event(cell['model'], forcing, result, spec['soil_controls'])
        a = number(cell['area_m2']); led = result['ledger']; c = cell['model']['constants']
        rho, latent, cw, tm = (c[k] for k in ('water_density_kg_m3', 'latent_heat_j_kg',
                                           'water_heat_capacity_j_kg_k', 'melting_temperature_k'))
        # Surface advective net = infiltrated rain enthalpy - exfiltrated enthalpy.
        rain_h = rho*(latent+cw*(forcing['surface_water_temperature_k']-tm))
        runoff_energy = led['surface_input_m']*rain_h-led['face_advective_energy_j_m2'][0]
        cell['surface_water_m3'] = str(F(cell['surface_water_m3'])+F(a)*F(led['surface_runoff_m']))
        cell['surface_enthalpy_j'] = str(F(cell['surface_enthalpy_j'])+F(a)*F(runoff_energy))
        cell['soil'] = result['final_state']
        inputs.append(a*(led['surface_input_m']+led['bottom_upward_m']))
        outputs.append(a*(led['root_withdrawal_m']+led['bottom_downward_m']))
        input_energy.append(a*(led['surface_input_m']*rain_h+led['face_conductive_energy_j_m2'][0]))
        output_energy.append(a*(led['root_enthalpy_j_m2']+led['face_advective_energy_j_m2'][-1]
                               +led['face_conductive_energy_j_m2'][-1]))
        solved[key] = {'model': cell['model'], 'forcing': forcing, 'result': result}
    row = {'duration_s': dt, 'initial_cells_sha256': p.sha(initial),
           'final_cells_sha256': p.sha(following), 'final_cells': deepcopy(following), 'deformation': deformation,
           'transport': carried, 'soil_steps': solved,
           'water_input_m3': math.fsum(inputs),
           'water_output_m3': math.fsum(outputs)+number(carried['ledger']['runoff_export_m3'])
                             +number(carried['ledger']['sediment_water_export_m3']),
           'energy_input_j': math.fsum(input_energy)+math.fsum(work),
           'energy_output_j': math.fsum(output_energy)+number(carried['ledger']['runoff_export_enthalpy_j'])
                            +number(carried['ledger']['sediment_enthalpy_export_j']),
           'mechanical_energy_j': math.fsum(work),
           'routes_before': carried['routes_before'], 'routes_after': carried['routes_after']}
    row = plain(row)
    row['accounts'] = audit_interval(initial, following, row, spec['coupling_controls'])
    return following, row


def audit_interval(before, after, row, controls):
    if p.sha(before) != row['initial_cells_sha256'] or p.sha(after) != row['final_cells_sha256']:
        raise ValueError('ground interval state binding differs')
    start, end = stocks(before), stocks(after)
    wr = end['water_m3']-start['water_m3']-row['water_input_m3']+row['water_output_m3']
    er = end['enthalpy_j']-start['enthalpy_j']-row['energy_input_j']+row['energy_output_j']
    if abs(wr) > number(controls['budget_water_atol_m3']) or abs(er) > number(controls['budget_energy_atol_j']):
        raise StepFailure('independent whole-ground water/enthalpy account failed')
    for key, cell in after.items():
        if abs(cell['soil']['elapsed_seconds']-before[key]['soil']['elapsed_seconds']-row['duration_s']) > 16*math.ulp(max(1., cell['soil']['elapsed_seconds'])):
            raise ValueError('ground calendar advanced more or less than once')
        s = row['soil_steps'][key]
        if (s['model'] != cell['model'] or s['result']['final_state'] != cell['soil']
                or s['result']['initial_state'] != row['transport']['cells'][key]['soil']):
            raise ValueError('final soil support differs from actual changed-geometry solve')
        soil_audit.event(s['model'], s['forcing'], s['result'], s['result']['numerics']['controls'])
    # Transport independently checks each exact finite material account; deformation
    # cannot create dry mass. Check the whole interval again using its export ports.
    exports = row['transport']['ledger']['material_export_kg']
    for material in sorted(set(start['material_kg']) | set(end['material_kg']) | set(exports)):
        residual = end['material_kg'].get(material, 0)-start['material_kg'].get(material, 0)+number(exports.get(material, 0))
        if abs(residual) > number(controls['mass_atol_kg']):
            raise StepFailure('whole-ground dry material balance failed: '+material)
    return {'water_residual_m3': wr, 'energy_residual_j': er,
            'scope': 'EXTENSIVE_ACCOUNTS_NOT_EMPIRICAL_OR_WHOLE_WORLD_VALIDATION'}


def _field_integral(a, b, field):
    """Piecewise-constant L1 difference at common basal-relative elevations."""
    def segments(cell):
        top = math.fsum(l['thickness_m'] for l in cell['model']['layers'])
        out = []
        if isinstance(field, tuple):
            values = [number(m['dry_mass_kg_m2'])/layer['thickness_m']
                      if (m['material_id'], m['phase']) == field else 0.
                      for layer, m in zip(cell['model']['layers'], cell['materials'])]
        elif field == 'porosity':
            values = [layer['theta_s'] for layer in cell['model']['layers']]
        else:
            values = cell['soil'][field]
        for layer, value in zip(cell['model']['layers'], values):
            low = top-layer['thickness_m']; out.append((low, top, value)); top = low
        return out
    aa, bb = segments(a), segments(b); error, scale = 0., 0.
    coverage_a, coverage_b = [0.]*len(aa), [0.]*len(bb)
    for i, (lo, hi, av) in enumerate(aa):
        for j, (low, high, bv) in enumerate(bb):
            width = max(0., min(hi, high)-max(lo, low))
            coverage_a[i] += width; coverage_b[j] += width
            error += width*abs(av-bv); scale += width*max(abs(av), abs(bv))
    for rows, coverage in ((aa, coverage_a), (bb, coverage_b)):
        for (lo, hi, v), covered in zip(rows, coverage):
            outside = max(0., hi-lo-covered)*abs(v); error += outside; scale += outside
    return error, scale


def compare(spec, baseline, full, half, full_rows, half_rows):
    c = spec['coupling_controls']; ratios = {}
    def add(key, a, b, allowance):
        ratios[key] = abs(a-b)/(number(c[allowance])+number(c['relative_tolerance'])*max(abs(a), abs(b)))
    for key, a in full.items():
        b, old = half[key], baseline[key]
        sa, sb, so = (stocks({key: v}) for v in (a, b, old))
        for field, allowance in (('water_m3', 'water_atol_m3'), ('enthalpy_j', 'energy_atol_j')):
            add(key+'/'+field, sa[field]-so[field], sb[field]-so[field], allowance)
        add(key+'/transit', number(a['surface_water_m3']), number(b['surface_water_m3']), 'water_atol_m3')
        height = lambda v: math.fsum(l['thickness_m'] for l in v['model']['layers'])
        add(key+'/height_change', height(a)-height(old), height(b)-height(old), 'height_atol_m')
        for m in sorted(set(sa['material_kg']) | set(sb['material_kg']) | set(so['material_kg'])):
            add(key+'/material/'+m, sa['material_kg'].get(m, 0)-so['material_kg'].get(m, 0),
                sb['material_kg'].get(m, 0)-so['material_kg'].get(m, 0), 'mass_atol_kg')
        for field, allowance in (('head_m', 'head_integral_atol_m2'),
                                 ('temperature_offset_k', 'temperature_integral_atol_k_m')):
            error, scale = _field_integral(a, b, field)
            ratios[key+'/'+field] = error/(number(c[allowance])+number(c['relative_tolerance'])*scale)
        for field in ('total_water', 'ice_water', 'porosity'):
            error, scale = _field_integral(a, b, field); area = number(a['area_m2'])
            ratios[key+'/'+field] = area*error/(number(c['water_atol_m3'])+number(c['relative_tolerance'])*area*scale)
        kinds = {(m['material_id'], m['phase']) for cell in (a, b) for m in cell['materials']}
        for kind in sorted(kinds):
            error, scale = _field_integral(a, b, kind); area = number(a['area_m2'])
            ratios[key+'/material_profile/'+str(kind)] = area*error/(number(c['mass_atol_kg'])+number(c['relative_tolerance'])*area*scale)
        if a['materials'][0]['material_id'] != b['materials'][0]['material_id']:
            ratios[key+'/exposed_material'] = 2.
    for field, allowance in (('water_input_m3', 'water_atol_m3'), ('water_output_m3', 'water_atol_m3'),
                             ('energy_input_j', 'energy_atol_j'), ('energy_output_j', 'energy_atol_j')):
        add(field, math.fsum(r[field] for r in full_rows), math.fsum(r[field] for r in half_rows), allowance)
    if full_rows[-1]['routes_after'] != half_rows[-1]['routes_after']:
        # Quantitative slopes differ normally; only a changed chosen receiver is
        # a discrete split mismatch, handled by a smaller coupled interval.
        def topology(rows):
            return sorted((r['cell_id'], r['receiver_id'], r['connector_id']) for r in rows['rows'])
        if topology(full_rows[-1]['routes_after']) != topology(half_rows[-1]['routes_after']):
            ratios['route_topology'] = 2.
    return max(ratios.values(), default=0.), ratios


def advance_event(spec, cells, event):
    c = spec['coupling_controls']; dt = number(c['initial_step_s']); elapsed = 0.
    duration = number(event['duration_s']); current = deepcopy(cells); rows, gates = [], []
    attempts = 0
    while elapsed < duration:
        attempts += 1
        if attempts > c['max_attempts']:
            raise StepFailure('ground coupled work budget exhausted')
        dt = min(dt, duration-elapsed)
        if dt <= 0 or elapsed+dt == elapsed:
            raise StepFailure('ground coupled time increment unrepresentable')
        try:
            full, frow = _trial(spec, current, event, dt)
            first, arow = _trial(spec, current, event, dt/2)
            second, brow = _trial(spec, first, event, dt/2)
            ratio, errors = compare(spec, current, full, second, [frow], [arow, brow])
        except soil.UnknownInput:
            raise
        except (ValueError, ArithmeticError) as exc:
            ratio, errors = math.inf, {'trial_failure': str(exc)}
        if ratio > 1:
            if dt/2 < number(c['min_step_s']):
                raise StepFailure('ground coupled acceptance failed: '+str(errors))
            dt /= 2
            continue
        current = second; rows.extend((arow, brow)); elapsed = duration if dt == duration-elapsed else elapsed+dt
        gates.append({'duration_s': dt, 'error_ratio': ratio, 'attempt': attempts})
        dt = min(number(c['max_step_s']), dt*min(2., .9/math.sqrt(max(ratio, 1e-30))))
    return current, {'event_id': event['event_id'], 'duration_s': duration,
                     'initial_cells': deepcopy(cells), 'final_cells': deepcopy(current),
                     'steps': rows, 'acceptance': gates, 'attempts': attempts}


def audit_event(row, controls):
    current = row['initial_cells']; covered = 0.
    for step in row['steps']:
        final = deepcopy(step['transport']['cells'])
        for key, solved in step['soil_steps'].items():
            # Transit after the soil solve is retained explicitly in the event
            # step; it must not be inferred from an unauthenticated endpoint.
            final[key] = deepcopy(step['final_cells'][key])
        audit_interval(current, final, step, controls)
        covered += step['duration_s']; current = final
    if current != row['final_cells'] or abs(covered-row['duration_s']) > 32*math.ulp(max(1., covered)):
        raise ValueError('ground event coverage/endpoint differs')
    audit_budget(row['initial_cells'], row['final_cells'], row['steps'], controls)
    return True


def audit_budget(before, after, rows, controls):
    start, end = stocks(before), stocks(after)
    wr = (end['water_m3']-start['water_m3']
          -math.fsum(r['water_input_m3']-r['water_output_m3'] for r in rows))
    er = (end['enthalpy_j']-start['enthalpy_j']
          -math.fsum(r['energy_input_j']-r['energy_output_j'] for r in rows))
    if abs(wr) > number(controls['budget_water_atol_m3']) or abs(er) > number(controls['budget_energy_atol_j']):
        raise StepFailure('cumulative ground water/enthalpy budget failed')
    representation = [F(r['transport']['ledger']['erosion_local_mass_representation_error_bound_kg']) for r in rows]
    if any(error < 0 for error in representation) or sum(representation, F()) > F(controls['mass_atol_kg']):
        raise StepFailure('cumulative ground erosion representation budget failed')
    materials = set(start['material_kg']) | set(end['material_kg'])
    for material in sorted(materials):
        exported = math.fsum(number(r['transport']['ledger']['material_export_kg'].get(material, 0)) for r in rows)
        if abs(end['material_kg'].get(material, 0)-start['material_kg'].get(material, 0)+exported) > number(controls['mass_atol_kg']):
            raise StepFailure('cumulative ground material budget failed')
    return {'water_residual_m3': wr, 'energy_residual_j': er,
            'erosion_local_mass_representation_error_bound_kg': str(sum(representation, F()))}


def run(spec, *, stop_after=None, resume=None, store=None, on_checkpoint=None):
    if on_checkpoint is not None and not callable(on_checkpoint):
        raise ValueError('callable ground checkpoint receiver required')
    started = time.perf_counter(); spec = deepcopy(spec); validate(spec)
    binding = p.identity(); source_sha, recipe_sha = p.sha(binding), p.sha(spec)
    if store is not None and (type(store) is not Store or store.namespace != source_sha):
        raise ValueError('exact source-bound ground Store required')
    count = len(spec['events']) if stop_after is None else stop_after
    if type(count) is not int or not 0 <= count <= len(spec['events']):
        raise ValueError('bounded complete-event ground cursor required')
    current = deepcopy(spec['cells']); rows = []; warnings = []; reused = 0
    def certificate(index, before, row):
        key = p.sha({'source': source_sha, 'recipe': recipe_sha, 'index': index, 'initial': p.sha(before)})
        return key, {'schema': 'diadem.verified-ground-event.r14', 'row_sha256': p.sha(row)}
    if resume is not None:
        contracts.exact(resume, ('schema', 'source_sha256', 'recipe_sha256', 'state_sha256', 'state'), 'ground checkpoint')
        if (resume['schema'] != 'diadem.ground-checkpoint.r14' or resume['source_sha256'] != source_sha
                or resume['recipe_sha256'] != recipe_sha or resume['state_sha256'] != p.sha(resume['state'])):
            raise ValueError('ground checkpoint source/recipe/state differs')
        saved = resume['state']; contracts.exact(saved, ('completed_events', 'continuing_state', 'accepted_events'), 'ground checkpoint state')
        if type(saved['completed_events']) is not int or not 0 <= saved['completed_events'] <= count:
            raise ValueError('ground checkpoint exceeds requested cursor')
        if store is None:
            if run(spec, stop_after=saved['completed_events'])['scientific']['checkpoint'] != resume:
                raise ValueError('ground checkpoint differs from scientific replay')
        else:
            if len(saved['accepted_events']) != saved['completed_events']:
                raise ValueError('ground checkpoint event inventory differs')
            for i, row in enumerate(saved['accepted_events']):
                if row['initial_cells'] != current or row['event_id'] != spec['events'][i]['event_id']:
                    raise ValueError('ground cached state/event lineage differs')
                key, value = certificate(i, current, row)
                if store.get(key) != value:
                    raise ValueError('ground event has no matching certificate; explicit no-cache replay required')
                audit_event(row, spec['coupling_controls']); current = deepcopy(row['final_cells'])
            if current != saved['continuing_state']:
                raise ValueError('ground cached endpoint differs')
            reused = saved['completed_events']
        current = deepcopy(saved['continuing_state']); rows = deepcopy(saved['accepted_events'])
    status, reason = None, None
    def snapshot():
        p.verify(binding)
        accounts = audit_budget(spec['cells'], current, [s for r in rows for s in r['steps']], spec['coupling_controls'])
        saved = {'completed_events': len(rows), 'continuing_state': current, 'accepted_events': rows}
        cp = {'schema': 'diadem.ground-checkpoint.r14', 'source_sha256': source_sha,
              'recipe_sha256': recipe_sha, 'state_sha256': p.sha(saved), 'state': saved}
        complete = status is None and len(rows) == len(spec['events'])
        out = {'scientific': {'schema': 'diadem.changing-ground.r14',
                'status': status or ('MODELLED_GROUND_FEEDBACK' if complete else 'STOPPED'),
                'source_status': spec['source_status'], 'source_sha256': source_sha, 'recipe_sha256': recipe_sha,
                'context': spec['context'], 'completed_events': len(rows), 'events': rows,
                'accounts': accounts,
                'final_cells': current if complete else None, 'checkpoint': cp, 'reason': reason,
                'whole_diadem_year_verified': False, 'production_authorised': False, 'canon_changed': False},
               'execution': {'identity': binding, 'elapsed_wall_seconds': time.perf_counter()-started,
                'reused_events': reused, 'cache_warnings': warnings, 'cache_stats': None if store is None else store.stats}}
        if on_checkpoint is not None:
            on_checkpoint(deepcopy(out))
        return out
    if spec['source_status'] == 'UNKNOWN':
        status, reason = 'UNKNOWN', 'ground scenario evidence is UNKNOWN'
    snapshot()
    for i in range(len(rows), count):
        event = spec['events'][i]
        if status:
            break
        try:
            if event['source_status'] == 'UNKNOWN':
                raise soil.UnknownInput('ground forcing evidence is UNKNOWN')
            following, row = advance_event(spec, current, event)
            audit_event(row, spec['coupling_controls']); p.verify(binding)
            audit_budget(spec['cells'], following, [s for r in [*rows, row] for s in r['steps']], spec['coupling_controls'])
        except soil.UnknownInput as exc:
            status, reason = 'UNKNOWN', str(exc); break
        except (ValueError, ArithmeticError) as exc:
            status, reason = 'NUMERICAL_FAILURE', str(exc); break
        if store is not None:
            key, value = certificate(i, current, row); store.put(key, value)
            if store.get(key) != value:
                warnings.append('Ground event saved without reusable certificate: '+event['event_id'])
        current = following; rows.append(row); snapshot()
    return snapshot()
