"""Selected species parameters connected to retained numerical operators.

The register is a source-bound selection, never a conversion of natural-history
prose into coefficients. Native kernels are injected by the protected loader.
"""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = 'diadem.species-parameter-register.r22'
KNOWN = {'CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST'}
STATUSES = KNOWN | {'UNKNOWN', 'CONFLICT', 'INCOMPLETE', 'Review-only', 'Provisional'}
CONTEXT = ('life_stage', 'cohort_id', 'scope_id', 'support_id', 'snapshot_id',
    'physical_scenario_id', 'time_basis', 'calendar_id', 'phase_id',
    'within_period_aggregation', 'joint_scenario_id', 'natural_or_managed',
    'counting_unit', 'native_measure_unit')
PLANT_UNITS = {
    'plant.net_light_use_efficiency': 'kg C/J',
    'plant.carbon_fraction_dry_matter': '1',
    'plant.turnover_rate': '1/s', 'plant.litter_fast_fraction': '1',
    'plant.temperature_response': 'K,1',
    **{'plant.nutrient_ratio.'+n: 'kg '+n+'/kg C' for n in ('N', 'P', 'K')},
    **{'plant.uptake_rate.'+n: '1/s' for n in ('N', 'P', 'K')},
}
SPATIAL_UNITS = {'habitat.suitability_minimum': '1',
    'occupancy.logit_intercept': '1', 'occupancy.logit_slope': '1 per unit habitat_support',
    'occupancy.conditional_occupied_fraction': '1'}


def _plain(value):
    if isinstance(value, F): return str(value)
    if type(value) in (tuple, list): return [_plain(v) for v in value]
    if type(value) is dict: return {k: _plain(v) for k, v in value.items()}
    return value


def digest(value):
    return hashlib.sha256(json.dumps(_plain(value), sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(name+': bounded explicit text required')
    return value


def _q(value, *, signed=False):
    if type(value) not in (str, int, float, F) or (type(value) is float and not math.isfinite(value)):
        raise ValueError('finite rational quantity required, not bool')
    if type(value) is str and (len(value) > 256 or re.fullmatch(r'[+-]?(?:\d+(?:/\d+)?|\d+\.\d*|\.\d+)', value) is None):
        raise ValueError('bounded decimal or rational spelling required')
    try: q = F(value)
    except (ValueError, ZeroDivisionError, OverflowError) as exc: raise ValueError('invalid quantity') from exc
    if max(q.numerator.bit_length(), q.denominator.bit_length()) > 4096 or (q < 0 and not signed):
        raise ValueError('quantity outside supported bounds')
    return q


def _context(context):
    if type(context) is not dict: raise ValueError('explicit biological context required')
    for key in CONTEXT: _text(context.get(key), 'context '+key)
    if context['native_measure_unit'] not in ('m', 'm2', 'm3'):
        raise ValueError('native linear, area or volume support required')
    if context['natural_or_managed'] not in ('NATURAL', 'MANAGED'):
        raise ValueError('explicit natural or managed context required')
    start, duration = _q(context.get('start_seconds')), _q(context.get('duration_seconds'))
    if duration <= 0: raise ValueError('positive explicitly sized phase required')
    units = context.get('time_units_seconds')
    if type(units) is not dict or any(k not in ('day', 'year') or _q(v) <= 0 for k, v in units.items()):
        raise ValueError('explicit source calendar conversions required; no Earth default')
    return start, duration


def _checked(path, expected):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or not path.is_file() or path.stat().st_size > 8*1024*1024:
        raise ValueError('bounded absolute regular source required')
    for parent in (path, *path.parents):
        stat = parent.lstat()
        if parent.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
            raise ValueError('linked source refused')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected: raise ValueError('source changed; no repin: '+str(path))
    return raw


def load_register(path, expected_sha256):
    """Read exactly the requested register and its explicitly declared bindings."""
    document = json.loads(_checked(path, expected_sha256))
    for ref in document.get('source_bindings', []): _checked(ref['path'], ref['sha256'])
    return Registry(document, register_sha256=expected_sha256)


def bind_application(owner_document, organism_id, context, *, application_ref):
    """Join owner biology to one evidenced, replaceable geographic application.

    Owner rows may constrain only biological context. Their supplied constraints
    must match; the application fills absent support/calendar/scenario fields.
    Original context and exact source labels remain in every resulting record.
    This is an execution binding, not a new owner decision or parameter selection.
    """
    _context(context); _text(organism_id, 'organism')
    if owner_document.get('schema') != SCHEMA: raise ValueError('owner numerical register schema differs')
    document = deepcopy(owner_document)
    bindings = {r['path']: r['sha256'] for r in document.get('source_bindings', [])}
    if bindings.get(application_ref.get('path')) not in (None, application_ref.get('sha256')):
        raise ValueError('application source binding conflict')
    if application_ref.get('path') not in bindings:
        document.setdefault('source_bindings', []).append({'path': application_ref['path'], 'sha256': application_ref['sha256']})
    rows = []
    for source in owner_document.get('records', []):
        if source.get('organism_id') != organism_id: continue
        owner_context = source.get('context')
        if type(owner_context) is not dict: raise ValueError('explicit owner applicability context required')
        if any(key not in context or context[key] != value for key, value in owner_context.items()):
            continue
        row = deepcopy(source)
        row['owner_context'] = deepcopy(owner_context)
        row['context'] = deepcopy(context)
        row['source_refs'] = [*row['source_refs'], deepcopy(application_ref)]
        rows.append(row)
    document['records'] = rows
    document['owner_register_sha256'] = digest(owner_document)
    document['application_binding'] = {'organism_id': organism_id, 'context': deepcopy(context), 'source_ref': deepcopy(application_ref)}
    return Registry(document)


class Registry:
    """Validated pure consumer; caller verifies source bytes or uses load_register."""
    def __init__(self, document, *, register_sha256=None):
        if type(document) is not dict or document.get('schema') != SCHEMA:
            raise ValueError('R22 numerical selection register required')
        self.document = deepcopy(document)
        self.register_sha256 = register_sha256 or digest(document)
        if re.fullmatch('[0-9a-f]{64}', self.register_sha256) is None: raise ValueError('register SHA256 required')
        self.scope = document.get('scope')
        if self.scope not in ('WORKING NON-CANON', 'SYNTHETIC TEST'): raise ValueError('explicit register scope required')
        self.bindings = {}
        for ref in document.get('source_bindings', []):
            path, sha = _text(ref.get('path'), 'source path'), ref.get('sha256')
            if type(sha) is not str or re.fullmatch('[0-9a-f]{64}', sha) is None: raise ValueError('source SHA256 required')
            if path in self.bindings: raise ValueError('duplicate source binding')
            self.bindings[path] = sha
        rows = document.get('records')
        if type(rows) is not list or len(rows) > 10000: raise ValueError('bounded field register required')
        self.records, seen, selected = [], set(), set()
        for r in rows:
            for key in ('record_id', 'organism_id', 'field_id', 'evidence'): _text(r.get(key), key)
            if r['record_id'] in seen: raise ValueError('duplicate record identity')
            seen.add(r['record_id'])
            if r.get('source_status') not in STATUSES: raise ValueError('exact field source status required')
            if r['source_status'] == 'SYNTHETIC TEST' and self.scope != 'SYNTHETIC TEST':
                raise ValueError('test coefficients cannot enter the actual register')
            if r.get('kind') not in ('PLANT', 'ANIMAL', 'SPECIAL'): raise ValueError('explicit organism kind required')
            _context(r.get('context'))
            if r.get('model_use') not in ('SELECTED_FOR_R22', 'CONSTRAINT_ONLY', 'UNKNOWN'):
                raise ValueError('explicit numerical selection state required')
            refs = r.get('source_refs')
            if type(refs) is not list or not refs: raise ValueError('each field needs source evidence')
            for ref in refs + ([r['use_decision_ref']] if r.get('use_decision_ref') else []):
                if self.bindings.get(ref.get('path')) != ref.get('sha256'): raise ValueError('unbound field source')
                _text(ref.get('locator'), 'source locator'); _text(ref.get('raw_source_status'), 'raw source status')
            if r['model_use'] == 'SELECTED_FOR_R22':
                if r['source_status'] not in KNOWN or r.get('value') is None or not r.get('use_decision_ref'):
                    raise ValueError('selected field needs known value and bound selection decision')
                key = (r['organism_id'], digest(r['context']), r['field_id'])
                if key in selected: raise ValueError('ambiguous multiple selected field values')
                selected.add(key)
                if r['organism_id'] in ('HS14', 'HS19') or r['kind'] == 'SPECIAL':
                    raise ValueError('special identity requires its separate event or absent-wild register')
            if r.get('value') is None and (not r.get('unresolved_owner') or not r.get('required_action')):
                raise ValueError('unknown field needs owner and resolving action')
            self.records.append(deepcopy(r))

    def profile(self, organism_id, context):
        _text(organism_id, 'organism'); _context(context)
        return Profile(self, organism_id, context)


class Profile:
    def __init__(self, registry, organism_id, context):
        self.registry, self.organism_id, self.context = registry, organism_id, deepcopy(context)
        self.records = [r for r in registry.records if r['organism_id'] == organism_id and r['context'] == context]
        kinds = {r['kind'] for r in self.records}
        if len(kinds) > 1: raise ValueError('organism kind conflict')
        self.kind = next(iter(kinds), None)
        self.used, self.gaps = {}, {}

    def get(self, field, unit, *, structured=False, signed=False):
        rows = [r for r in self.records if r['field_id'] == field and r['model_use'] == 'SELECTED_FOR_R22']
        if not rows:
            originals = [r for r in self.records if r['field_id'] == field]
            self.gaps[field] = {'status': 'CONFLICT' if any(r['source_status'] == 'CONFLICT' for r in originals) else 'UNKNOWN',
                'records': deepcopy(originals), 'reason': 'No selected compatible numerical field'}
            return None
        r = rows[0]; value = deepcopy(r['value']); actual = r.get('unit')
        scale = F(1)
        if actual != unit:
            if unit.endswith('/s') and type(actual) is str:
                base = unit[:-2]
                period = next((p for p in ('day', 'year') if actual == base+'/'+p), None)
                if period is None or period not in self.context['time_units_seconds']:
                    raise ValueError(field+': explicit matching source time unit required')
                scale = 1/_q(self.context['time_units_seconds'][period])
            else: raise ValueError(field+': unit does not match native operator')
        if structured:
            if actual != unit: raise ValueError('structured laws cannot be scaled generically')
        else: value = _q(value, signed=signed)*scale
        self.used[field] = {'record_id': r['record_id'], 'source_status': r['source_status'],
            'source_refs': deepcopy(r['source_refs']), 'use_decision_ref': deepcopy(r['use_decision_ref']),
            'input_unit': actual, 'operator_unit': unit, 'scale': str(scale)}
        return value

    def text(self, field, allowed):
        value = self.get(field, 'text', structured=True)
        if value is not None and value not in allowed: raise ValueError(field+': unsupported executable meaning')
        return value

    def receipt(self):
        return {'organism_id': self.organism_id, 'context': deepcopy(self.context),
            'register_sha256': self.registry.register_sha256, 'consumed_fields': deepcopy(self.used),
            'unresolved_fields': deepcopy(self.gaps), 'scope': self.registry.scope}

    def status(self):
        values = {r['source_status'] for r in self.records if r['record_id'] in {v['record_id'] for v in self.used.values()}}
        return 'SYNTHETIC TEST' if 'SYNTHETIC TEST' in values else 'WORKING NON-CANON'


def compile_plant_law(ecosystem, registry, organism_id, context):
    p = registry.profile(organism_id, context)
    if p.kind not in ('PLANT', None): raise ValueError('plant production cannot be applied to animal')
    if context['native_measure_unit'] != 'm2': raise ValueError('retained ecosystem requires native area, not projected volume')
    values = {field: p.get(field, unit, structured=field == 'plant.temperature_response') for field, unit in PLANT_UNITS.items()}
    curve = values['plant.temperature_response']
    if curve is not None:
        if type(curve) is not dict or set(curve) != {'law', 'knots'} or curve['law'] != 'PIECEWISE_LINEAR_NO_EXTRAPOLATION':
            raise ValueError('explicit supported temperature law required')
        curve = tuple(tuple(_q(v) for v in row) for row in curve['knots'])
    law = ecosystem.PlantLaw(law_id=organism_id+':'+context['joint_scenario_id'],
        net_light_use_efficiency_kg_c_j=values['plant.net_light_use_efficiency'],
        nutrient_kg_per_kg_c=tuple((n, values['plant.nutrient_ratio.'+n]) for n in ('N', 'P', 'K')),
        uptake_rate_per_s=tuple((n, values['plant.uptake_rate.'+n]) for n in ('N', 'P', 'K')),
        carbon_fraction_dry_matter=values['plant.carbon_fraction_dry_matter'],
        turnover_per_s=values['plant.turnover_rate'], litter_fast_fraction=values['plant.litter_fast_fraction'],
        temperature_curve_k=curve, evidence='Selected register '+registry.register_sha256, source_status=p.status())
    return {'status': 'UNKNOWN' if p.gaps else 'SELECTED_NUMERICAL_LAW', 'law': law, 'receipt': p.receipt()}


def run_plant_year(ecosystem, organic, fertility, registry, organism_id, context, *,
        initial_state, organic_law, nutrient_context, calendar, events, numerics,
        geometry_sha256, source_binding_sha256, evidence, stop_after=None, resume=None):
    compiled = compile_plant_law(ecosystem, registry, organism_id, context)
    if initial_state.organic_state.support_id != context['support_id'] or calendar.calendar_id != context['calendar_id']:
        raise ValueError('biological register does not match actual support/calendar')
    if sum(calendar.month_durations_seconds, F()) != _q(context['duration_seconds']) or _q(context['start_seconds']) != 0:
        raise ValueError('plant-law applicability must cover this complete native year')
    if 'day' in context['time_units_seconds'] and _q(context['time_units_seconds']['day']) != calendar.day_seconds:
        raise ValueError('source day conversion differs from actual calendar')
    if 'year' in context['time_units_seconds'] and _q(context['time_units_seconds']['year']) != sum(calendar.month_durations_seconds, F()):
        raise ValueError('source year conversion differs from actual calendar')
    result = ecosystem.run_year(organic, fertility, initial_state, compiled['law'], organic_law,
        nutrient_context, calendar, events, numerics=numerics, geometry_sha256=geometry_sha256,
        source_binding_sha256=digest({'physics': source_binding_sha256, 'biology': compiled['receipt']}),
        scenario_id=context['physical_scenario_id'], evidence=evidence,
        source_status=compiled['law'].source_status, stop_after=stop_after, resume=resume)
    return {'schema': 'diadem.species-growth.r22', 'status': result['status'],
        'biology': compiled['receipt'], 'result': result,
        'limits': 'Finite native C/N/P/K growth and turnover; reproduction and population are separate.'}


def _stock_context(p):
    c = p.context
    return {'species_id': p.organism_id, 'counting_unit': c['counting_unit'], 'life_stage': c['life_stage'],
        'spatial_scope_id': c['scope_id'], 'time_basis': c['time_basis'], 'snapshot_id': c['snapshot_id'],
        'joint_scenario_id': c['joint_scenario_id'], 'supplier': 'SPECIES — Coordination, Integration & QA',
        'evidence': 'Selected register '+p.registry.register_sha256, 'source_status': p.status()}


def run_density(stock, registry, organism_id, context, *, cells, basis):
    """Each disjoint native cell has its own exact selected support context."""
    p = registry.profile(organism_id, context)
    if basis not in stock.DENSITY_BASES: raise ValueError('explicit density basis required')
    rows, receipts, ids = [], [], set()
    for cell in cells:
        c = deepcopy(context); c['support_id'] = cell['cell_id']
        q = registry.profile(organism_id, c)
        if cell['cell_id'] in ids: raise ValueError('duplicate native cell')
        ids.add(cell['cell_id'])
        density = q.get('density.value', context['counting_unit']+'/'+context['native_measure_unit'])
        selected_basis = q.text('density.basis', tuple(stock.DENSITY_BASES))
        if selected_basis is None: density = None
        elif selected_basis != basis: raise ValueError('density basis differs from selected source semantics')
        habitat = q.get('habitat.habitat_fraction', '1')
        occupied = q.get('density.occupied_fraction', '1')
        if cell['measure']['unit'] != context['native_measure_unit']: raise ValueError('native cell dimension mismatch')
        rows.append({'cell_id': cell['cell_id'], 'eligible': cell['eligible'], 'measure': cell['measure'],
            'habitat_fraction': habitat, 'occupied_fraction': occupied,
            'density': {'value': density, 'denominator_unit': context['native_measure_unit'], 'basis': basis},
            'evidence': cell['evidence'], 'source_status': cell['source_status']})
        receipts.append(q.receipt())
    native_context = _stock_context(p)
    if registry.scope == 'SYNTHETIC TEST': native_context['source_status'] = 'SYNTHETIC TEST'
    result = stock.declared_density({'schema': 'diadem.declared-density-input.r9', 'context': native_context, 'cells': rows})
    return {'schema': 'diadem.species-density.r22', 'status': result['status'], 'biology': receipts, 'result': result}


def run_stock(stock, registry, organism_id, context, *, cells):
    p = registry.profile(organism_id, context)
    total = p.get('stock.total_expected_entities', context['counting_unit'])
    rows, receipts = [], [p.receipt()]
    for cell in cells or []:
        c = deepcopy(context); c['support_id'] = cell['cell_id']
        q = registry.profile(organism_id, c)
        rows.append({'cell_id': cell['cell_id'], 'eligible': cell['eligible'],
            'weight': q.get('stock.allocation_weight', '1 relative weight'),
            'capacity_expected_entities': q.get('stock.capacity_expected_entities', context['counting_unit']),
            'occupied_measure': cell.get('occupied_measure'), 'evidence': cell['evidence'], 'source_status': cell['source_status']})
        receipts.append(q.receipt())
    result = stock.allocate_stock({'schema': 'diadem.prescribed-stock-input.r9', 'context': _stock_context(p),
        'total_expected_entities': total, 'cells': None if cells is None else rows})
    return {'schema': 'diadem.species-stock.r22', 'status': result['status'], 'biology': receipts, 'result': result}


def compile_spatial_rule(spatial, registry, organism_id, context, *, travel_unit):
    p = registry.profile(organism_id, context)
    if context['native_measure_unit'] != 'm2': raise ValueError('retained range graph requires actual area support')
    values = {f: p.get(f, u, signed=f.startswith('occupancy.logit')) for f, u in SPATIAL_UNITS.items()}
    density = p.get('density.value', context['counting_unit']+'/m2')
    density_basis = p.text('density.basis', ('PER_OCCUPIED_MEASURE',))
    mode = p.text('movement.mode', ('NONMOVING', 'SEASONAL_MOVEMENT'))
    budget = p.get('movement.budget', travel_unit)
    if density_basis is None: density = None
    rule = spatial.SpeciesRule(organism_id, values['habitat.suitability_minimum'],
        values['occupancy.logit_intercept'], values['occupancy.logit_slope'],
        values['occupancy.conditional_occupied_fraction'], density, budget, travel_unit,
        mode or 'UNKNOWN', 'Selected register '+registry.register_sha256, p.status())
    return {'rule': rule, 'status': 'UNKNOWN' if p.gaps else 'SELECTED_NUMERICAL_RULE', 'receipt': p.receipt()}


def recruitment_flux(registry, organism_id, context):
    """Integrate explicitly supplied successful recruitment; never infer fecundity."""
    p = registry.profile(organism_id, context)
    law = p.text('recruitment.law', ('PRESCRIBED_SUCCESSFUL_RECRUITMENT_FLUX',))
    rate = p.get('recruitment.rate', context['counting_unit']+'/s')
    amount = None if law is None or rate is None else rate*_q(context['duration_seconds'])
    return {'schema': 'diadem.species-recruitment-flux.r22', 'status': 'UNKNOWN' if amount is None else 'MODELLED_PRESCRIBED_FLUX',
        'successful_recruits': None if amount is None else str(amount), 'counting_unit': context['counting_unit'],
        'biology': p.receipt(), 'limits': 'Supplied successful recruits only; no births, survival, mortality or stock update inferred.'}


def run_range(spatial, registry, organism_id, context, *, cells, edges, origins, travel_unit):
    compiled = compile_spatial_rule(spatial, registry, organism_id, context, travel_unit=travel_unit)
    result = spatial.evaluate_range(cells, edges, origins, compiled['rule'], season_id=context['phase_id'])
    return {'schema': 'diadem.species-range.r22', 'status': result['status'],
        'biology': compiled['receipt'], 'result': result,
        'limits': 'Declared occupancy and accessibility; no reproduction, demographic change or stock-total substitution.'}


def run_movement(spatial, registry, organism_id, context, destination_context, *,
        cells, edges, origins, requests, receiving_capacity, destination_cells,
        destination_edges, destination_origins, travel_unit, declared_departure_stock=None):
    """Route one compatible cohort using retained finite-stock corridor accounts."""
    _context(context); _context(destination_context)
    for key in CONTEXT:
        if key not in ('phase_id', 'time_basis', 'within_period_aggregation') and context[key] != destination_context[key]:
            raise ValueError('movement must retain the same biological cohort and physical support: '+key)
    if context['time_units_seconds'] != destination_context['time_units_seconds']:
        raise ValueError('movement source calendar changed')
    if _q(destination_context['start_seconds']) < _q(context['start_seconds'])+_q(context['duration_seconds']):
        raise ValueError('movement phases overlap or run backwards')
    source = compile_spatial_rule(spatial, registry, organism_id, context, travel_unit=travel_unit)
    destination = compile_spatial_rule(spatial, registry, organism_id, destination_context, travel_unit=travel_unit)
    result = spatial.route_movements(cells, edges, origins, source['rule'], requests,
        season_id=context['phase_id'], receiving_capacity=receiving_capacity,
        evidence='Selected register '+registry.register_sha256, source_status=source['rule'].source_status,
        destination_cells=destination_cells, destination_edges=destination_edges,
        destination_origins=destination_origins, destination_rule=destination['rule'],
        destination_season_id=destination_context['phase_id'], declared_departure_stock=declared_departure_stock)
    return {'schema': 'diadem.species-movement.r22', 'status': result['status'],
        'biology': {'source': source['receipt'], 'destination': destination['receipt']}, 'result': result,
        'limits': 'Finite same-cohort movement; shared capacities require an external partition; no births or new stock.'}


def residence_exposure(registry, organism_id, context):
    """One source-selected cohort's residence integral, not movement or population."""
    p = registry.profile(organism_id, context)
    total = p.get('residence.scoped_cohort_entities', context['counting_unit'])
    fraction = p.get('residence.fraction', '1')
    if fraction is not None and fraction > 1: raise ValueError('residence fraction exceeds one')
    amount = None if total is None or fraction is None else total*fraction*_q(context['duration_seconds'])
    return {'schema': 'diadem.species-residence.r22', 'status': 'UNKNOWN' if amount is None else 'MODELLED_PRESCRIBED_RESIDENCE',
        'entity_seconds': None if amount is None else str(amount), 'counting_unit': context['counting_unit'],
        'biology': p.receipt(), 'limits': 'One explicit cohort and phase; no occupancy, stock transfer or whole-year census inferred.'}
