"""Finite seasonal vegetation C and elemental nutrient stocks.

R7 organic and fertility operators are injected from the caller's bound graph.
This is a prescribed, split-process initial-value experiment, not calibrated
species biology, a crop-yield model or an automatically updated soil geometry.
"""
from dataclasses import asdict, dataclass, is_dataclass, replace
from fractions import Fraction as F
import hashlib
import json
import math
import re

NUTRIENTS = ('N', 'P', 'K')
KNOWN = {'CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST'}
STATUSES = KNOWN | {'UNKNOWN', 'CONFLICT', 'INCOMPLETE'}
SCHEMA = 'diadem.seasonal-ecosystem.r11'
CHECKPOINT_SCHEMA = 'diadem.seasonal-ecosystem-checkpoint.r11'


def plain(value):
    if isinstance(value, F): return str(value)
    if is_dataclass(value): return plain(asdict(value))
    if type(value) is dict:
        if any(type(k) is not str for k in value): raise ValueError('string keys required')
        return {k: plain(v) for k, v in value.items()}
    if type(value) in (tuple, list): return [plain(v) for v in value]
    if value is None or type(value) in (str, int, bool): return value
    if type(value) is float and math.isfinite(value): return value
    raise ValueError('finite JSON values required')


def digest(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(name+' needs bounded explicit text')


def _status(value):
    if type(value) is not str or value not in STATUSES: raise ValueError('explicit source status required')


def _hash(value, name):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError(name+' requires lowercase SHA256')


def _q(value, name, *, optional=False, positive=False, unit=False):
    if value is None and optional: return None
    if type(value) not in (int, float, F) or (type(value) is float and not math.isfinite(value)):
        raise ValueError(name+' requires a finite quantity, not bool')
    value = F(value)
    if value < 0 or (positive and value == 0) or (unit and value > 1):
        raise ValueError(name+' outside physical bounds')
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > 8192:
        raise ValueError(name+' exceeds exact representation bound')
    return value


def _triplet(value, name, *, optional=False, positive=False):
    if type(value) is not tuple or len(value) != 3:
        raise ValueError(name+' requires explicit ordered N/P/K pairs')
    if any(type(row) is not tuple or len(row) != 2 for row in value) or tuple(row[0] for row in value) != NUTRIENTS:
        raise ValueError(name+' requires unique ordered N/P/K pairs')
    return tuple((n, _q(v, name+'.'+n, optional=optional, positive=positive)) for n, v in value)


@dataclass(frozen=True)
class Calendar:
    calendar_id: str
    month_durations_seconds: tuple
    day_seconds: F
    evidence: str

    def __post_init__(self):
        _text(self.calendar_id, 'calendar'); _text(self.evidence, 'calendar evidence')
        if type(self.month_durations_seconds) is not tuple or len(self.month_durations_seconds) != 12:
            raise ValueError('twelve explicit month durations required')
        months = tuple(_q(v, 'month duration', positive=True) for v in self.month_durations_seconds)
        day = _q(self.day_seconds, 'day duration', positive=True)
        if sum(months, F()) != 365*day: raise ValueError('calendar must contain 365 explicitly sized days')
        object.__setattr__(self, 'month_durations_seconds', months)
        object.__setattr__(self, 'day_seconds', day)


@dataclass(frozen=True)
class State:
    organic_state: object
    live_carbon_kg_m2: F | None
    live_nutrients_kg_m2: tuple
    reserve_nutrients_kg_m2: tuple
    labile_nutrients_kg_m2: tuple
    elapsed_seconds: F
    evidence: str
    source_status: str

    def __post_init__(self):
        object.__setattr__(self, 'live_carbon_kg_m2', _q(self.live_carbon_kg_m2, 'live C', optional=True))
        for name in ('live_nutrients_kg_m2', 'reserve_nutrients_kg_m2', 'labile_nutrients_kg_m2'):
            object.__setattr__(self, name, _triplet(getattr(self, name), name, optional=True))
        object.__setattr__(self, 'elapsed_seconds', _q(self.elapsed_seconds, 'ecosystem age'))
        _text(self.evidence, 'initial stock evidence'); _status(self.source_status)


@dataclass(frozen=True)
class PlantLaw:
    law_id: str
    net_light_use_efficiency_kg_c_j: F | None
    nutrient_kg_per_kg_c: tuple
    uptake_rate_per_s: tuple
    carbon_fraction_dry_matter: F | None
    turnover_per_s: F | None
    litter_fast_fraction: F | None
    temperature_curve_k: tuple | None
    evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.law_id, 'plant law'); _text(self.evidence, 'biological applicability evidence'); _status(self.source_status)
        for name in ('net_light_use_efficiency_kg_c_j', 'turnover_per_s'):
            object.__setattr__(self, name, _q(getattr(self, name), name, optional=True))
        object.__setattr__(self, 'carbon_fraction_dry_matter', _q(self.carbon_fraction_dry_matter, 'plant C fraction', optional=True, positive=True, unit=True))
        object.__setattr__(self, 'litter_fast_fraction', _q(self.litter_fast_fraction, 'fast litter fraction', optional=True, unit=True))
        object.__setattr__(self, 'nutrient_kg_per_kg_c', _triplet(self.nutrient_kg_per_kg_c, 'new-growth nutrient requirement', optional=True, positive=True))
        object.__setattr__(self, 'uptake_rate_per_s', _triplet(self.uptake_rate_per_s, 'plant nutrient uptake rate', optional=True))
        if self.carbon_fraction_dry_matter is not None and all(v is not None for _, v in self.nutrient_kg_per_kg_c):
            if self.carbon_fraction_dry_matter*(1+sum((v for _, v in self.nutrient_kg_per_kg_c), F())) > 1:
                raise ValueError('carbon and N/P/K exceed actual plant dry mass')
        if self.temperature_curve_k is not None:
            curve = self.temperature_curve_k
            if type(curve) is not tuple or not 2 <= len(curve) <= 128 or any(type(row) is not tuple or len(row) != 2 for row in curve):
                raise ValueError('explicit bounded temperature response pairs required')
            curve = tuple((_q(t, 'canopy temperature', positive=True), _q(y, 'temperature response', unit=True)) for t, y in curve)
            if any(a[0] >= b[0] for a, b in zip(curve, curve[1:])): raise ValueError('temperature knots must increase')
            object.__setattr__(self, 'temperature_curve_k', curve)


@dataclass(frozen=True)
class NutrientContext:
    chemistry: object
    laws: tuple
    sorbent_mass_kg_m2: F | None
    evidence: str
    source_status: str

    def __post_init__(self):
        if type(self.laws) is not tuple or len(self.laws) != 3: raise ValueError('three ordered native N/P/K laws required')
        object.__setattr__(self, 'sorbent_mass_kg_m2', _q(self.sorbent_mass_kg_m2, 'sorbent mass', optional=True))
        _text(self.evidence, 'nutrient mechanism evidence'); _status(self.source_status)


@dataclass(frozen=True)
class Event:
    event_id: str
    month_id: int
    layer_id: str
    support_id: str
    organic_forcing: object
    nutrient_exposures: tuple
    absorbed_par_j_m2: F | None
    canopy_temperature_k: F | None
    water_stress_fraction: F | None
    activity_fraction: F | None
    harvest_fraction: F | None
    water_state_id: str
    thermal_state_id: str
    phenology_evidence: str
    evidence: str
    source_status: str

    def __post_init__(self):
        for name in ('event_id', 'layer_id', 'support_id', 'water_state_id', 'thermal_state_id', 'phenology_evidence', 'evidence'):
            _text(getattr(self, name), name)
        if type(self.month_id) is not int or not 1 <= self.month_id <= 12: raise ValueError('month 1..12 required')
        if type(self.nutrient_exposures) is not tuple or len(self.nutrient_exposures) != 3:
            raise ValueError('three explicit ordered native N/P/K exposures required')
        object.__setattr__(self, 'absorbed_par_j_m2', _q(self.absorbed_par_j_m2, 'absorbed PAR energy', optional=True))
        object.__setattr__(self, 'canopy_temperature_k', _q(self.canopy_temperature_k, 'canopy temperature', optional=True, positive=True))
        for name in ('water_stress_fraction', 'activity_fraction', 'harvest_fraction'):
            object.__setattr__(self, name, _q(getattr(self, name), name, optional=True, unit=True))
        _status(self.source_status)


def state_to_record(organic, state):
    if type(state) is not State or type(state.organic_state) is not organic.OrganicState: raise ValueError('typed actual organic ecosystem state required')
    return plain({**asdict(state), 'organic_state': organic.state_to_record(state.organic_state)})


def _missing(state, law, context, event, source_status):
    missing = []
    for name, status in (('run', source_status), ('state', state.source_status), ('plant_law', law.source_status), ('nutrient_context', context.source_status), ('event', event.source_status)):
        if status not in KNOWN: missing.append(name+'.source_status:'+status)
    if state.live_carbon_kg_m2 is None: missing.append('state.live_carbon_kg_m2')
    for name in ('live_nutrients_kg_m2', 'reserve_nutrients_kg_m2', 'labile_nutrients_kg_m2'):
        missing += ['state.'+name+'.'+n for n, value in getattr(state, name) if value is None]
    for name in ('net_light_use_efficiency_kg_c_j', 'carbon_fraction_dry_matter', 'turnover_per_s', 'litter_fast_fraction', 'temperature_curve_k'):
        if getattr(law, name) is None: missing.append('plant_law.'+name)
    missing += ['plant_law.nutrient_kg_per_kg_c.'+n for n, value in law.nutrient_kg_per_kg_c if value is None]
    missing += ['plant_law.uptake_rate_per_s.'+n for n, value in law.uptake_rate_per_s if value is None]
    if context.sorbent_mass_kg_m2 is None: missing.append('nutrient_context.sorbent_mass_kg_m2')
    if context.chemistry is None: missing.append('nutrient_context.chemistry')
    missing += ['nutrient_context.laws.'+n for n, value in zip(NUTRIENTS, context.laws) if value is None]
    missing += ['event.nutrient_exposures.'+n for n, value in zip(NUTRIENTS, event.nutrient_exposures) if value is None]
    for name in ('absorbed_par_j_m2', 'canopy_temperature_k', 'water_stress_fraction', 'activity_fraction', 'harvest_fraction'):
        if getattr(event, name) is None: missing.append('event.'+name)
    return missing


def _temperature(curve, value):
    if not curve[0][0] <= value <= curve[-1][0]: return None
    if value == curve[-1][0]: return curve[-1][1]
    for (a, x), (b, y) in zip(curve, curve[1:]):
        if a <= value <= b: return x+(y-x)*(value-a)/(b-a)
    raise ArithmeticError('temperature interpolation failed')


def _inventory(organic, fertility, initial, law, organic_law, context, calendar, events, numerics):
    if type(initial) is not State or type(initial.organic_state) is not organic.OrganicState or type(organic_law) is not organic.OrganicLaw:
        raise ValueError('actual retained organic types required')
    if type(law) is not PlantLaw or type(context) is not NutrientContext or type(calendar) is not Calendar or type(numerics) is not organic.Numerics:
        raise ValueError('typed explicit ecosystem inputs required')
    if initial.live_carbon_kg_m2 is not None and law.carbon_fraction_dry_matter is not None and all(v is not None for _, v in initial.live_nutrients_kg_m2):
        if initial.live_carbon_kg_m2+sum((v for _, v in initial.live_nutrients_kg_m2), F()) > initial.live_carbon_kg_m2/law.carbon_fraction_dry_matter:
            raise ValueError('initial living C and N/P/K exceed explicit living dry mass')
    if context.chemistry is not None and type(context.chemistry) is not fertility.Chemistry: raise ValueError('actual retained chemistry required')
    for n, item in zip(NUTRIENTS, context.laws):
        if item is not None and (type(item) is not fertility.NutrientLaw or item.nutrient != n): raise ValueError('native law nutrient order differs')
    if type(events) is not tuple or not 12 <= len(events) <= 4096 or any(type(e) is not Event for e in events):
        raise ValueError('bounded complete-year event inventory required')
    ids = set(); last = 1; months = [F() for _ in range(12)]
    for e in events:
        if e.event_id in ids or e.month_id < last: raise ValueError('event identities/chronology differ')
        if (e.layer_id, e.support_id) != (initial.organic_state.layer_id, initial.organic_state.support_id): raise ValueError('actual layer/support mismatch')
        if type(e.organic_forcing) is not organic.OrganicForcing: raise ValueError('actual organic forcing required')
        dt = _q(e.organic_forcing.duration_seconds, 'event duration', positive=True)
        for exposure in e.nutrient_exposures:
            if exposure is None: continue
            if type(exposure) is not fertility.WaterExposure: raise ValueError('actual nutrient water exposure required')
            if exposure.duration_s != float(dt): raise ValueError('native nutrient duration differs from represented event duration')
            if e.organic_forcing.soil_temperature_k is not None and exposure.temperature_k != e.organic_forcing.soil_temperature_k:
                raise ValueError('soil temperature differs between carbon and nutrient producers')
            if e.organic_forcing.water_filled_pore_fraction is not None and exposure.wetness != e.organic_forcing.water_filled_pore_fraction:
                raise ValueError('soil wetness differs between carbon and nutrient producers')
        if e.organic_forcing.water_state_id != e.water_state_id: raise ValueError('water evidence join differs')
        ids.add(e.event_id); last = e.month_id; months[e.month_id-1] += dt
    if tuple(months) != calendar.month_durations_seconds: raise ValueError('events must cover each exact month')


def _totals(state):
    return {'C': state.live_carbon_kg_m2+state.organic_state.fast_carbon_kg_m2+state.organic_state.slow_carbon_kg_m2,
        **{n: dict(state.live_nutrients_kg_m2)[n]+dict(state.reserve_nutrients_kg_m2)[n]+dict(state.labile_nutrients_kg_m2)[n] for n in NUTRIENTS}}


def _step(organic, fertility, state, plant_law, organic_law, context, event, numerics):
    temp = _temperature(plant_law.temperature_curve_k, event.canopy_temperature_k)
    if temp is None: return {'status': 'OUTSIDE_REGIME', 'reason': 'canopy temperature outside explicit plant response law'}
    dt = event.organic_forcing.duration_seconds
    actual_c = organic.advance_layer(state.organic_state, (event.organic_forcing,), organic_law, numerics=numerics)
    if actual_c['status'] != 'MODELLED': return {'status': actual_c['status'], 'reason': actual_c['reason'], 'organic_producer': actual_c}
    if type(actual_c['state']) is not organic.OrganicState or actual_c['state'].elapsed_seconds != state.organic_state.elapsed_seconds+dt:
        raise ValueError('actual carbon producer changed its state identity or time')
    if (actual_c['state'].layer_id, actual_c['state'].support_id) != (event.layer_id, event.support_id): raise ValueError('carbon producer support differs')
    c_input = (event.organic_forcing.fast_litter_carbon_kg_m2_s+event.organic_forcing.slow_litter_carbon_kg_m2_s)*dt
    c_export = _q(actual_c['carbon']['exported_atmospheric_carbon_kg_m2'], 'carbon export')
    if state.organic_state.fast_carbon_kg_m2+state.organic_state.slow_carbon_kg_m2+c_input != actual_c['state'].fast_carbon_kg_m2+actual_c['state'].slow_carbon_kg_m2+c_export:
        raise ValueError('independent native carbon conservation failed')
    native = {}; reserves = {}; labile = {}; incoming = {}; leached = {}; residual = {}
    for n, law, exposure in zip(NUTRIENTS, context.laws, event.nutrient_exposures):
        r, l = dict(state.reserve_nutrients_kg_m2)[n], dict(state.labile_nutrients_kg_m2)[n]
        pool = fertility.NutrientPool(n, float(r), float(l), state.evidence)
        out = fertility.advance_nutrient(pool, law, (exposure,), sorbent_mass_kg_m2=float(context.sorbent_mass_kg_m2), chemistry=context.chemistry, support_id=event.support_id)
        if out.get('schema') != 'diadem.nutrient-reference.r7' or out.get('nutrient') != n or out.get('support_id') != event.support_id: raise ValueError('native nutrient identity differs')
        reserves[n] = _q(out['reserve_kg_m2'], 'native reserve'); labile[n] = _q(out['labile_kg_m2'], 'native labile')
        incoming[n] = _q(F(out['imported_kg_m2']), 'nutrient input'); leached[n] = _q(F(out['exported_kg_m2']), 'nutrient export')
        cast = r+l-F(pool.reserve_kg_m2)-F(pool.labile_kg_m2)
        residual[n] = F(out['numerical_residual_kg_m2'])+cast
        if r+l+incoming[n] != reserves[n]+labile[n]+leached[n]+residual[n]: raise ValueError('independent native nutrient conservation failed')
        allowance = F(1e-12)+F(1e-10)*(r+l+incoming[n])
        if abs(residual[n]) > allowance: raise ArithmeticError('nutrient numerical residual exceeds retained allowance')
        native[n] = {**out, 'input_cast_residual_kg_m2': cast}
    potential = (event.absorbed_par_j_m2*plant_law.net_light_use_efficiency_kg_c_j*temp*
                 event.water_stress_fraction*event.activity_fraction)
    # A prescribed absorbed-light input cannot establish vegetation from no plant.
    if state.live_carbon_kg_m2 == 0: potential = F()
    capacities = {}; uptake_capacity = {}
    for (n, ratio), law in zip(plant_law.nutrient_kg_per_kg_c, context.laws):
        exposure = dict(plant_law.uptake_rate_per_s)[n]*F(law.available_fraction)*dt
        represented = float(exposure)
        if not math.isfinite(represented) or represented > 1e6: raise ArithmeticError('nutrient uptake exceeds numerical regime')
        if exposure > 0 and represented == 0: raise ArithmeticError('positive nutrient uptake underflows; not zero uptake')
        uptake_capacity[n] = labile[n]*F(-math.expm1(-represented))
        capacities[n] = uptake_capacity[n]/ratio
    growth = min(potential, *capacities.values())
    uptake = {n: growth*ratio for n, ratio in plant_law.nutrient_kg_per_kg_c}
    exact_x = plant_law.turnover_per_s*dt
    x = float(exact_x)
    if not math.isfinite(x) or x > 1e6: raise ArithmeticError('plant turnover exceeds numerical regime')
    if exact_x > 0 and x == 0: raise ArithmeticError('positive plant turnover underflows; not zero turnover')
    lost_fraction = F(-math.expm1(-x))
    litter_c = state.live_carbon_kg_m2*lost_fraction
    litter_n = {n: stock*lost_fraction for n, stock in state.live_nutrients_kg_m2}
    live_c_before_harvest = state.live_carbon_kg_m2-litter_c+growth
    live_n_before_harvest = {n: stock-litter_n[n]+uptake[n] for n, stock in state.live_nutrients_kg_m2}
    harvest_c = live_c_before_harvest*event.harvest_fraction
    harvest_n = {n: stock*event.harvest_fraction for n, stock in live_n_before_harvest.items()}
    try:
        organic_after = replace(actual_c['state'],
            fast_carbon_kg_m2=actual_c['state'].fast_carbon_kg_m2+litter_c*plant_law.litter_fast_fraction,
            slow_carbon_kg_m2=actual_c['state'].slow_carbon_kg_m2+litter_c*(1-plant_law.litter_fast_fraction))
        final = State(organic_after, live_c_before_harvest-harvest_c,
            tuple((n, live_n_before_harvest[n]-harvest_n[n]) for n in NUTRIENTS),
            tuple((n, reserves[n]+litter_n[n]) for n in NUTRIENTS),
            tuple((n, labile[n]-uptake[n]) for n in NUTRIENTS), state.elapsed_seconds+dt, state.evidence, 'WORKING NON-CANON')
    except ValueError as exc:
        if 'exceeds' not in str(exc): raise
        raise ArithmeticError('updated ecosystem stock exceeds retained exact representation bound') from exc
    start_totals, end_totals = _totals(state), _totals(final)
    budget = {'C': {'initial': start_totals['C'], 'net_atmospheric_input': growth, 'external_litter_input': c_input,
        'final': end_totals['C'], 'heterotrophic_export': c_export, 'harvest_export': harvest_c, 'numerical_residual': F()}}
    if start_totals['C']+growth+c_input != end_totals['C']+c_export+harvest_c: raise ArithmeticError('whole ecosystem carbon does not close')
    for n in NUTRIENTS:
        if start_totals[n]+incoming[n] != end_totals[n]+leached[n]+harvest_n[n]+residual[n]: raise ArithmeticError('whole ecosystem elemental budget does not close')
        budget[n] = {'initial': start_totals[n], 'external_input': incoming[n], 'final': end_totals[n], 'water_export': leached[n], 'harvest_export': harvest_n[n], 'numerical_residual': residual[n]}
    return {'status': 'MODELLED', 'state': final, 'budgets_kg_m2': budget, 'organic_producer': actual_c,
        'nutrient_producers': native, 'potential_net_production_kg_c_m2': potential,
        'net_production_kg_c_m2': growth, 'unrealised_production_kg_c_m2': potential-growth,
        'limiting_nutrients': [n for n in NUTRIENTS if capacities[n] == growth and growth < potential],
        'temperature_response': temp, 'nutrient_uptake_kg_m2': uptake, 'litter_carbon_kg_m2': litter_c,
        'kinetic_nutrient_uptake_capacity_kg_m2': uptake_capacity,
        'litter_nutrients_kg_m2': litter_n, 'harvested_carbon_kg_m2': harvest_c,
        'harvested_nutrients_kg_m2': harvest_n, 'harvested_dry_matter_kg_m2': harvest_c/plant_law.carbon_fraction_dry_matter,
        'native_nutrient_duration_residual_s': F(float(dt))-dt,
        'soil_material_change': {'organic_dry_mass_change_kg_m2':
            (organic_after.fast_carbon_kg_m2+organic_after.slow_carbon_kg_m2-state.organic_state.fast_carbon_kg_m2-state.organic_state.slow_carbon_kg_m2)/organic_law.carbon_fraction_dry_matter,
            'mineral_mass_change_kg_m2': F(), 'physical_geometry_feedback': 'REQUIRES_CONSERVATIVE_GEOMETRY_WATER_REBIND'},
        'split_order': 'existing-pool carbon and nutrient exposure; old-plant turnover; endpoint nutrient-limited growth; endpoint litter return and harvest'}


def _checkpoint(organic, identity, state, rows, elapsed):
    data = {'schema': CHECKPOINT_SCHEMA, 'inputs_sha256': identity, 'completed_events': len(rows),
        'elapsed_seconds_in_year': str(elapsed), 'state': state_to_record(organic, state), 'accepted_prefix_sha256': digest(rows)}
    return {**data, 'checkpoint_sha256': digest(data)}


def _aggregate(rows):
    if not rows: return None
    output = {}
    for element in ('C',)+NUTRIENTS:
        first = rows[0]['budgets_kg_m2'][element]; last = rows[-1]['budgets_kg_m2'][element]
        output[element] = {'initial': first['initial'], 'final': last['final'],
            **{key: sum((row['budgets_kg_m2'][element][key] for row in rows), F()) for key in first if key not in {'initial', 'final'}}}
    return output


def run_year(organic, fertility, initial_state, plant_law, organic_law, nutrient_context, calendar, events, *,
             numerics, geometry_sha256, source_binding_sha256, scenario_id, evidence, source_status,
             stop_after=None, resume=None):
    """Persist actual carbon, finite nutrients and plant stocks through one year.

Missing coefficients/stocks stop the causal suffix. Resume independently replays
its accepted prefix; a rehashed forged state is not a valid continuation.
"""
    _hash(geometry_sha256, 'geometry'); _hash(source_binding_sha256, 'source binding')
    _text(scenario_id, 'scenario'); _text(evidence, 'experiment evidence'); _status(source_status)
    _inventory(organic, fertility, initial_state, plant_law, organic_law, nutrient_context, calendar, events, numerics)
    count = len(events)
    if stop_after is not None and (type(stop_after) is not int or not 0 <= stop_after <= count): raise ValueError('bounded integer stop cursor required')
    target = count if stop_after is None else stop_after
    inputs = {'initial_state': state_to_record(organic, initial_state), 'plant_law': plant_law, 'organic_law': organic_law,
        'nutrient_context': nutrient_context, 'calendar': calendar, 'events': events, 'numerics': numerics,
        'geometry_sha256': geometry_sha256, 'source_binding_sha256': source_binding_sha256,
        'scenario_id': scenario_id, 'evidence': evidence, 'source_status': source_status}
    identity = digest(inputs); resume_cursor = None
    if resume is not None:
        names = {'schema', 'inputs_sha256', 'completed_events', 'elapsed_seconds_in_year', 'state', 'accepted_prefix_sha256', 'checkpoint_sha256'}
        if type(resume) is not dict or set(resume) != names or resume['schema'] != CHECKPOINT_SCHEMA: raise ValueError('exact ecosystem checkpoint schema required')
        if resume['checkpoint_sha256'] != digest({k: v for k, v in resume.items() if k != 'checkpoint_sha256'}) or resume['inputs_sha256'] != identity:
            raise ValueError('ecosystem checkpoint/source inputs changed')
        resume_cursor = resume['completed_events']
        if type(resume_cursor) is not int or not 0 <= resume_cursor <= target: raise ValueError('checkpoint cursor exceeds continuation')
    state = initial_state; rows = []; elapsed = F(); halt = None; reason = None; missing = []; failed = None
    for index in range(target+1):
        if resume_cursor == index and _checkpoint(organic, identity, state, rows, elapsed) != resume:
            raise ValueError('ecosystem checkpoint does not reproduce actual accepted prefix/state')
        if index == target: break
        event = events[index]
        missing = _missing(state, plant_law, nutrient_context, event, source_status)
        if missing: halt = 'UNKNOWN'; reason = 'required biological or environmental input unresolved'; break
        try:
            result = _step(organic, fertility, state, plant_law, organic_law, nutrient_context, event, numerics)
        except (ArithmeticError, OverflowError) as exc:
            result = {'status': 'NUMERICAL_FAILURE', 'reason': str(exc)}
        if result['status'] != 'MODELLED':
            halt = result['status']; reason = result.get('reason'); failed = result; break
        row = {'event_id': event.event_id, 'month_id': event.month_id, 'layer_id': event.layer_id, 'support_id': event.support_id,
            'start_seconds_in_year': elapsed, 'duration_seconds': event.organic_forcing.duration_seconds,
            'initial_state': state_to_record(organic, state), 'water_state_id': event.water_state_id, 'thermal_state_id': event.thermal_state_id,
            **{k: v for k, v in result.items() if k != 'state'}, 'end_state': state_to_record(organic, result['state'])}
        rows.append(row); state = result['state']; elapsed += event.organic_forcing.duration_seconds
    if resume_cursor is not None and resume_cursor > len(rows): raise ValueError('checkpoint accepted prefix cannot be reproduced')
    complete = halt is None and len(rows) == count
    months = {}
    for month in range(1, 13):
        selected = [r for r in rows if r['month_id'] == month]
        expected = [e for e in events if e.month_id == month]
        done = len(selected) == len(expected)
        months[str(month)] = {'status': 'MODELLED' if done else halt or 'STOPPED',
            'budgets_kg_m2': _aggregate(selected) if done else None, 'completed_event_ids': [r['event_id'] for r in selected],
            'net_production_kg_c_m2': sum((r['net_production_kg_c_m2'] for r in selected), F()) if done else None,
            'end_state': selected[-1]['end_state'] if done else None}
    return plain({'schema': SCHEMA, 'status': halt or ('MODELLED_SEASONAL_ECOSYSTEM' if complete else 'STOPPED'),
        'source_status': 'WORKING NON-CANON', 'inputs_sha256': identity, 'inputs': inputs,
        'source_binding_sha256': source_binding_sha256, 'geometry_sha256': geometry_sha256, 'scenario_id': scenario_id,
        'completed_events': len(rows), 'completed_months': sum(m['status'] == 'MODELLED' for m in months.values()),
        'events': rows, 'unadvanced_event_ids': [e.event_id for e in events[len(rows):]], 'months': months,
        'annual_budgets_kg_m2': _aggregate(rows) if complete else None,
        'final_state': state_to_record(organic, state) if complete else None,
        'checkpoint': _checkpoint(organic, identity, state, rows, elapsed) if halt is None else None,
        'reason': reason, 'missing_inputs': missing, 'failed_producer': failed,
        'nutrient_feedback': 'APPLIED_FINITE_UPTAKE_AND_LITTER_RETURN_TO_NEXT_EVENT_RESERVES',
        'physical_geometry_feedback': 'REQUIRES_CONSERVATIVE_GEOMETRY_WATER_REBIND',
        'biology_status': 'EXPLICIT_PARAMETERISED_HYPOTHESIS_NOT_EMPIRICAL_SPECIES_CALIBRATION',
        'unmodelled': ['dynamic canopy cover', 'seed establishment and reproduction', 'gross photosynthesis and autotrophic respiration partition',
            'microbial stoichiometry and reactive nutrient speciation', 'automatic food or crop-yield conversion', 'automatic physical geometry/hydraulic feedback'],
        'scope': 'one fixed-support representative initial-value year; no steady-state reset, stock duplication, history or canon adoption'})


def reference_inputs(organic, fertility, actual_r10_unit, *, layer_id, initial_live_carbon_kg_m2,
                     initial_live_nutrients_kg_m2, initial_reserve_nutrients_kg_m2,
                     initial_labile_nutrients_kg_m2, plant_law, nutrient_context,
                     event_drivers, evidence):
    """Join an actual decoded R10 unit to separately supplied biological drivers.

No plant or nutrient coefficients/stock/concentration are inferred. Driver keys
must equal the actual ordered event inventory. Original R10 initial carbon
stocks are continued through the same representative year, not advanced twice.
"""
    _text(evidence, 'reference evidence')
    if type(actual_r10_unit) is not dict or type(event_drivers) is not dict: raise ValueError('actual unit and explicit event drivers required')
    water = actual_r10_unit.get('hydrology'); carbon = actual_r10_unit.get('carbon')
    if type(water) is not dict or water.get('schema') != 'diadem.seasonal-layered-water.r10' or water.get('completed_months') != 12:
        raise ValueError('completed actual R10 soil water required')
    if type(carbon) is not dict or carbon.get('water_product_sha256') != digest(water): raise ValueError('carbon and water producer joins differ')
    if layer_id not in carbon.get('layers', {}): raise ValueError('selected layer absent from actual carbon diagnostics')
    diagnostic = carbon['layers'][layer_id]['diagnostic']
    if diagnostic.get('schema') != 'diadem.seasonal-organic-carbon.r10' or diagnostic.get('status') != 'MODELLED_SEASONAL_CARBON_DIAGNOSTIC':
        raise ValueError('completed actual carbon diagnostic required')
    source = diagnostic['inputs']
    if diagnostic.get('inputs_sha256') != digest(source): raise ValueError('carbon input identity differs')
    if diagnostic['layer_id'] != layer_id or diagnostic['geometry_sha256'] != source['geometry_sha256']:
        raise ValueError('actual carbon layer/geometry differs')
    initial_organic = organic.state_from_record(source['initial_state'])
    initial = State(initial_organic, initial_live_carbon_kg_m2, initial_live_nutrients_kg_m2,
        initial_reserve_nutrients_kg_m2, initial_labile_nutrients_kg_m2, F(), evidence, 'SYNTHETIC TEST')
    law_values = dict(source['law'])
    for name in ('fast_to_slow_fraction', 'carbon_fraction_dry_matter'):
        if law_values[name] is not None: law_values[name] = F(law_values[name])
    for name in ('moisture_curve', 'redox_factors'): law_values[name] = tuple(tuple(row) for row in law_values[name])
    law_values['regimes'] = tuple(law_values['regimes'])
    organic_law = organic.OrganicLaw(**law_values)
    cv = source['calendar']
    calendar = Calendar(cv['calendar_id'], tuple(F(x) for x in cv['month_durations_seconds']), F(cv['day_seconds']), cv['evidence'])
    expected_ids = [row['event_id'] for row in source['events']]
    if set(event_drivers) != set(expected_ids) or len(expected_ids) != len(set(expected_ids)):
        raise ValueError('biological driver inventory must exactly cover actual carbon events')
    water_ids = [row['event_id'] for row in water['events']]
    if water_ids != expected_ids: raise ValueError('actual water/carbon event chronology differs')
    events = []
    fields = {'nutrient_exposures', 'absorbed_par_j_m2', 'canopy_temperature_k', 'water_stress_fraction',
              'activity_fraction', 'harvest_fraction', 'thermal_state_id', 'phenology_evidence', 'evidence', 'source_status'}
    for row in source['events']:
        driver = event_drivers[row['event_id']]
        if type(driver) is not dict or set(driver) != fields: raise ValueError('exact separately supplied biological driver fields required')
        forcing_values = dict(row['forcing'])
        for key in ('duration_seconds', 'fast_litter_carbon_kg_m2_s', 'slow_litter_carbon_kg_m2_s'):
            if forcing_values[key] is not None: forcing_values[key] = F(forcing_values[key])
        forcing = organic.OrganicForcing(**forcing_values)
        events.append(Event(row['event_id'], row['month_id'], row['layer_id'], row['support_id'],
            forcing, water_state_id=forcing.water_state_id, **driver))
    return {'initial_state': initial, 'plant_law': plant_law, 'organic_law': organic_law,
        'nutrient_context': nutrient_context, 'calendar': calendar, 'events': tuple(events),
        'numerics': organic.Numerics(**source['numerics']), 'geometry_sha256': source['geometry_sha256'],
        'reference_join': {'actual_r10_unit_sha256': digest(actual_r10_unit), 'water_product_sha256': digest(water),
            'carbon_diagnostic_sha256': digest(diagnostic), 'initial_pool_sha256': digest(source['initial_state']),
            'initial_pool_semantics': 'original representative-year start retained; no second carbon year',
            'new_biology_and_nutrient_inputs': 'EXPLICIT_SYNTHETIC_TEST_NOT_OWNER_CALIBRATION'}}


def reference_spec(organic, fertility, actual_r10_unit):
    """Complete SYNTHETIC TEST vegetation/nutrient case on one actual R10 unit.

The selected mineral layer supplies actual initial carbon and liquid event
budgets. Its inflow/outflow faces are counted once into a held-volume mixed
nutrient control volume. Native R7 upward/downward algebra represents aggregate
in/out exchange here, not a claimed direction-specific elemental observation.
"""
    evidence = ('SYNTHETIC TEST: explicit existing temperate-stand live biomass, net radiation conversion, N/P/K '
        'stocks and coefficients; not Diadem biology or calibrated vegetation. Native selected-layer R10 '
        'beginning liquid volume and integrated face exchanges are a held-volume well-mixed nutrient hypothesis; '
        'all incoming water has independently prescribed zero elemental concentration. R10 unfrozen soil and '
        'prescribed soil temperature remain conditional. Internal turnover replaces legacy external litter.')
    if type(actual_r10_unit) is not dict or type(actual_r10_unit.get('cell_id')) is not str: raise ValueError('actual R10 cell required')
    layer_id = actual_r10_unit['cell_id']+'-mineral'
    water = actual_r10_unit['hydrology']
    diagnostic = actual_r10_unit['carbon']['layers'][layer_id]['diagnostic']
    source_events = diagnostic['inputs']['events']
    layers = water['column']['layers']
    matching = [i for i, layer in enumerate(layers) if layer['layer_id'] == layer_id]
    if len(matching) != 1: raise ValueError('unique actual mineral layer required')
    index = matching[0]; layer = layers[index]
    plant_law = PlantLaw('SYNTHETIC_EXISTING_TEMPERATE_STAND', F(1,5000000000),
        (('N', F(1,25)), ('P', F(1,250)), ('K', F(1,50))),
        tuple((n, F(1,1000000)) for n in NUTRIENTS), F(2,5), F(1,63072000), F(3,4),
        ((F(250), F()), (F(27815,100), F()), (F(29315,100), F(1)), (F(30815,100), F(1)), (F(32315,100), F())), evidence, 'SYNTHETIC TEST')
    chemistry = fertility.Chemistry('SYNTHETIC_SELECTED_LAYER_CHEMISTRY', 6.5, .1, 'EXPLICIT_TEST_MATRIX', evidence)
    laws = tuple(fertility.NutrientLaw(n, rate, kd, 1., 283.15, 20000., 8.314462618,
        chemistry.chemistry_id, species, evidence) for n, rate, kd, species in
        (('N', 1e-8, 0., 'NITRATE_N'), ('P', 2e-9, .01, 'EXPLICIT_NET_LABILE_P'), ('K', 5e-9, .002, 'EXPLICIT_NET_LABILE_K')))
    context = NutrientContext(chemistry, laws, F(100), evidence, 'SYNTHETIC TEST')
    drivers = {}; joins = []
    if len(water['events']) != len(source_events): raise ValueError('water/carbon event counts differ')
    for wrow, crow in zip(water['events'], source_events):
        if wrow['event_id'] != crow['event_id'] or wrow['month_id'] != crow['month_id']: raise ValueError('water/carbon event order differs')
        dt = F(crow['forcing']['duration_seconds'])
        if F(wrow['duration_seconds']) != dt: raise ValueError('water/carbon event duration differs')
        ledger = wrow['solver_result']['ledger']
        down = tuple(F(v) for v in ledger['face_downward_m']); up = tuple(F(v) for v in ledger['face_upward_m'])
        if len(down) != len(layers)+1 or len(up) != len(down): raise ValueError('complete actual face inventory required')
        incoming = down[index]+up[index+1]; outgoing = down[index+1]+up[index]
        native_forcing = crow['forcing']; wetness = native_forcing['water_filled_pore_fraction']
        storage = F(wetness)*F(layer['theta_s'])*F(layer['thickness_m'])
        exposure = fertility.WaterExposure(float(dt), native_forcing['soil_temperature_k'], wetness,
            float(storage), float(outgoing/dt), float(incoming/dt), 0., evidence)
        potential = F(ledger['potential_et_m']); actual = F(ledger['actual_et_m'])
        if potential > 0:
            ratio = actual/potential
            if not 0 <= ratio <= 1: raise ValueError('actual transpiration ratio outside unit interval; no clipping')
            activity = F(1); stress = ratio; stress_meaning = 'ACTUAL_INTEGRATED_ROOT_UPTAKE_DIVIDED_BY_POTENTIAL_DEMAND'
        else:
            if actual != 0: raise ValueError('positive uptake without potential demand')
            activity = F(); stress = F(); stress_meaning = 'INACTIVE_ZERO_RESPONSE; WATER_ADEQUACY_RATIO_UNDEFINED'
        air_temperature = wrow['air_temperature_c']
        canopy = None if air_temperature is None else F(air_temperature)+F(27315,100)
        drivers[wrow['event_id']] = {'nutrient_exposures': (exposure,)*3,
            'absorbed_par_j_m2': F(50)*dt, 'canopy_temperature_k': canopy,
            'water_stress_fraction': stress, 'activity_fraction': activity,
            'harvest_fraction': F(1,20) if wrow is water['events'][-1] else F(),
            'thermal_state_id': native_forcing['climate_state_id'],
            'phenology_evidence': evidence+'; activity follows the explicit retained hydraulic stand demand, not species phenology',
            'evidence': evidence+'; 50 W/m2 absorbed PAR prescribed; canopy temperature equals event air as an explicit hypothesis',
            'source_status': 'SYNTHETIC TEST'}
        joins.append({'event_id': wrow['event_id'], 'layer_id': layer_id,
            'water_event_sha256': digest(wrow), 'carbon_forcing_sha256': digest(crow['forcing']),
            'start_liquid_storage_m': str(storage), 'gross_incoming_m': str(incoming), 'gross_outgoing_m': str(outgoing),
            'face_mapping': {'incoming': ['top_downward', 'bottom_upward'], 'outgoing': ['bottom_downward', 'top_upward']},
            'native_assay_mapping': 'upward = aggregate incoming; downward = aggregate outgoing; control-volume algebra only',
            'water_stress_meaning': stress_meaning})
    spec = reference_inputs(organic, fertility, actual_r10_unit, layer_id=layer_id,
        initial_live_carbon_kg_m2=F(2), initial_live_nutrients_kg_m2=(('N', F(2,25)), ('P', F(1,125)), ('K', F(1,25))),
        initial_reserve_nutrients_kg_m2=(('N', F(1,10)), ('P', F(1,100)), ('K', F(1,10))),
        initial_labile_nutrients_kg_m2=(('N', F(1,100)), ('P', F(1,500)), ('K', F(1,200))),
        plant_law=plant_law, nutrient_context=context, event_drivers=drivers, evidence=evidence)
    spec['events'] = tuple(replace(event, organic_forcing=replace(event.organic_forcing,
        fast_litter_carbon_kg_m2_s=F(), slow_litter_carbon_kg_m2_s=F(), litter_evidence=evidence,
        evidence=evidence, source_status='SYNTHETIC TEST')) for event in spec['events'])
    spec['reference_join'].update(selected_layer=layer_id, event_joins=joins,
        legacy_external_litter='EXPLICITLY_REPLACED_BY_MODELLED_PLANT_TURNOVER_NOT_ADDED_TWICE',
        hydraulic_feedback='ORIGINAL_R10_COLUMN_REMAINS_FIXED_UNFROZEN; NO_CHANGED_GEOMETRY_CLAIM')
    return spec
