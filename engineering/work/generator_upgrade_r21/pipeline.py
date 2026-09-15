"""Declared land commitments -> timed finite irrigation -> crops -> local food.

The reduced root-zone oracle and current coupled-soil engine are explicitly
separate alternatives. This runner does not register actual Diadem farms.
"""
from copy import deepcopy
from fractions import Fraction as F
import time
from . import _snapshot_contract as snapshot, land, food, owner, provenance as p
from .quantities import exact, ident, q
from .cache import StageCache

SCHEMA = 'diadem.connected-agriculture.r21'
FIELDS = {'context', 'terrain_generation', 'source_status', 'evidence', 'engine',
          'land', 'plans', 'water', 'food'}


def _validate_stage(value, invocation):
    exact(value, ('input_sha256', 'result'), 'cached agriculture stage')
    if value['input_sha256'] != p.sha(invocation) or type(value['result']) is not dict:
        raise ValueError('cached agriculture invocation/result differs')
    snapshot.encoded(value)
    ident(value['result'].get('status'), 'stage status')


def _commit(prepared, plans):
    if prepared['status'] != 'PREPARED':
        return {'status': 'INPUT_INCOMPLETE', 'reasons': prepared['incomplete']}
    if type(plans) is not list or not 1 <= len(plans) <= 256:
        raise ValueError('1..256 explicit pre-season planted plans required')
    plots = {row['id']: row for row in prepared['plots']}
    seen, records, area = set(), [], F(0)
    for plan in plans:
        support = ident(plan['support_id'])
        if support in seen or support not in plots:
            raise ValueError('one fixed plan per original whole plot required')
        seen.add(support); plot = plots[support]
        if plot['status'] != 'ADMITTED_HYPOTHESIS':
            return {'status': 'INPUT_INCOMPLETE', 'reasons': ['planted plot blocked or unresolved: '+support]}
        value = q(plan['area_m2'], 'planted area', positive=True)
        if value != F(plot['area_m2_exact']):
            raise ValueError('planted area differs from exact admitted whole geometry')
        crop_ids = ({row['commodity_id'] for row in plan['segments'] if row['kind'] == 'CROP'}
                    if 'segments' in plan else {row['commodity_id'] for row in plan['crops']})
        if not crop_ids <= set(plot['allowed_crop_ids']):
            raise ValueError('crop is not admitted on its declared land support')
        records.append({'support_id': support, 'area_m2': str(value),
            'plan_sha256': p.sha(plan), 'geometry_sha256': p.sha(plot['geometry']),
            'crop_ids': sorted(crop_ids)})
        area += value
    return {'status': 'COMMITTED', 'plots': records, 'cultivated_area_m2': str(area),
        'policy': 'FIXED_PRESEASON_NO_INSEASON_DROUGHT_RESELECTION',
        'unplanted_plot_ids': sorted(set(plots)-seen), 'geometry_mutations': 0}


def run(scenario, *, cache=True, cache_root=None):
    start = time.perf_counter()
    scenario = deepcopy(snapshot.plain(scenario))
    snapshot.encoded(scenario); exact(scenario, FIELDS, 'agriculture scenario')
    context = snapshot.context(scenario['context'])
    ident(scenario['terrain_generation']); ident(scenario['evidence'])
    if scenario['source_status'] not in ('SYNTHETIC TEST', 'WORKING NON-CANON'):
        raise ValueError('explicit working scenario required; this runner cannot adopt canon')
    execution, owners = p.identity(), owner.binding()
    reporting = []
    binding = {'context': context, 'terrain_generation': scenario['terrain_generation'],
               'source_status': scenario['source_status'], 'owners': owners}

    def stage(name, invocation, producer):
        begun = time.perf_counter()
        store = StageCache(name, binding, cache_root) if cache else None
        def produce():
            return {'input_sha256': p.sha(invocation), 'result': producer()}
        validate = lambda value: _validate_stage(value, invocation)
        if store:
            wrapped, hit = store.reuse(invocation, produce, validate)
        else:
            wrapped, hit = produce(), False
            validate(wrapped)
        reporting.append({'stage': name, 'hit': hit, 'elapsed_seconds': time.perf_counter()-begun,
                          'stats': store.stats if store else {}, 'warnings': store.warnings if store else []})
        return wrapped['result']

    specification = scenario['land']
    exact(specification, ('plots', 'land_geometry', 'exclusions', 'admission'), 'land inputs')
    if specification['admission']['scenario_id'] != context['scenario_id']:
        raise ValueError('land/crop scenario mismatch')
    prepared = stage('land', specification, lambda: land.prepare(**specification))
    commitments = _commit(prepared, scenario['plans'])
    science = {'schema': SCHEMA, 'status': commitments['status'], 'context': context,
        'source_status': scenario['source_status'], 'evidence': scenario['evidence'],
        'engine': scenario['engine'], 'terrain_generation': scenario['terrain_generation'],
        'input_sha256': p.sha(scenario), 'owner_binding': owners, 'land': prepared,
        'commitments': commitments, 'production': None, 'food': None,
        'actual_diadem_registration': False, 'whole_diadem_year_verified': False,
        'canon_changed': False, 'transport_solved': False}
    if commitments['status'] == 'COMMITTED':
        if scenario['engine'] == 'REDUCED_ROOT_ZONE_REFERENCE':
            from . import reduced
            invocation = {'plans': scenario['plans'], 'water': scenario['water']}
            production = stage('reduced-season', invocation, lambda: reduced.run(**invocation))
        elif scenario['engine'] == 'COUPLED_SOIL':
            for plan in scenario['plans']:
                if plan['context'] != context or plan['terrain_generation'] != scenario['terrain_generation']:
                    raise ValueError('soil/crop world, date, frame or terrain generation differs')
            production = coupled(scenario, stage)
        else:
            raise ValueError('explicit supported agriculture engine required')
        science['production'] = production
        science['status'] = production['status']
        harvests = [row for result in production.get('crops', []) for row in result.get('harvests', [])]
        densities = {row['harvest_id']: str(F(row['edible_energy_kcal'])/F(row['quantity_kg']))
                     for row in harvests if F(row['quantity_kg']) > 0}
        # Zero-yield harvests have no incoming stock. They remain in crop output;
        # do not divide by zero or invent a nutritional composition.
        positive = [row for row in harvests if F(row['quantity_kg']) > 0]
        if science['status'] == 'MODELLED':
            args = dict(scenario['food'], harvests=positive, energy_by_harvest=densities)
            science['food'] = stage('food', args, lambda: food.account(**args))
            if science['food']['status'] != 'ACCOUNTED':
                science['status'] = 'INPUT_INCOMPLETE'
    p.verify(execution)
    if owner.binding() != owners:
        raise ValueError('agriculture owner source changed during execution')
    return {'scientific': science, 'scientific_sha256': p.sha(science), 'execution': execution,
            'reporting': reporting, 'elapsed_seconds': time.perf_counter()-start}


def coupled(scenario, stage):
    """Implemented below with the fixed-geometry physical/Water interfaces."""
    from . import coupled as adapter
    return adapter.run(scenario['plans'], scenario['water'], stage=stage)
