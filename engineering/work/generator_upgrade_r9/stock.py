"""Owner-permitted dimensional density and no-redistribution prescribed stock.

Inputs are explicit joint scenarios, not measured biology, resource capacity or
new individuals. The caller binds actual disjoint geometry and census scope.
"""
from fractions import Fraction as F
import re

from . import spatial

CONTEXT = ('species_id', 'counting_unit', 'life_stage', 'spatial_scope_id',
           'time_basis', 'snapshot_id', 'joint_scenario_id', 'supplier', 'evidence', 'source_status')
UNITS = {'m': (1, F(1)), 'km': (1, F(1000)),
         'm2': (2, F(1)), 'km2': (2, F(1000000)),
         'm3': (3, F(1)), 'km3': (3, F(1000000000))}
BASE_UNITS = {1: 'm', 2: 'm2', 3: 'm3'}
DENSITY_BASES = frozenset(('PER_OCCUPIED_MEASURE', 'PER_HABITAT_MEASURE', 'PER_WHOLE_CELL_MEASURE'))


def _fields(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(name + ': exact fields required')
    return value


def _number(value, name, *, maximum=F(10**18), nullable=True):
    if type(value) is str:
        if not value or len(value) > 256 or not re.fullmatch(r'[+\-]?(?:\d+(?:/\d+)?|\d+\.\d*|\.\d+)', value):
            raise ValueError(name + ': bounded rational/decimal string required; no exponent expansion')
        try: value = F(value)
        except (ValueError, ZeroDivisionError) as exc: raise ValueError(name + ': invalid fraction') from exc
    return spatial._q(value, name, maximum=maximum, nullable=nullable)


def _context(value):
    _fields(value, CONTEXT, 'joint scenario context')
    for key in CONTEXT: spatial._text(value[key], key)
    spatial._source(value['evidence'], value['source_status'])
    return value


def _eligibility(value):
    if value is not None and type(value) is not bool:
        raise ValueError('eligibility must be explicit True/False/UNKNOWN')
    return value


def _measure(value, name, *, optional=False):
    if value is None and optional: return None
    _fields(value, ('value', 'unit'), name)
    if type(value['unit']) is not str or value['unit'] not in UNITS:
        raise ValueError(name + ': explicit supported physical unit required')
    count = _number(value['value'], name)
    dimension, scale = UNITS[value['unit']]
    return {'value': count, 'input_unit': value['unit'], 'dimension': dimension,
            'si_value': None if count is None else count*scale, 'si_unit': BASE_UNITS[dimension]}


def _cells(value, keys, name, *, optional=False):
    if value is None and optional: return None
    if type(value) is not list or len(value) > 4096:
        raise ValueError(name + ': bounded explicit cell list required')
    seen = set()
    for row in value:
        _fields(row, keys, name)
        spatial._text(row['cell_id'], 'cell identity')
        if row['cell_id'] in seen: raise ValueError('duplicate physical cell identity')
        seen.add(row['cell_id']); _eligibility(row['eligible'])
        spatial._source(row['evidence'], row['source_status'])
    return sorted(value, key=lambda r: r['cell_id'])


def _bound(spec):
    # Numeric spellings are retained as supplied; object key and cell-list order
    # do not alter the semantic source fingerprint used by this kernel.
    copied = dict(spec)
    if spec['cells'] is not None: copied['cells'] = sorted(spec['cells'], key=lambda r: r['cell_id'])
    return spatial._digest(copied)


def declared_density(spec):
    """Expected entities from one dimensional, joint occupancy/density scenario.

    A supplied whole-cell density already contains occupancy weighting, so f/h
    are not multiplied into it again. No Bernoulli cell-presence claim is made.
    """
    _fields(spec, ('schema', 'context', 'cells'), 'declared density input')
    if spec['schema'] != 'diadem.declared-density-input.r9': raise ValueError('density schema differs')
    context = _context(spec['context'])
    cells = _cells(spec['cells'], ('cell_id', 'eligible', 'measure', 'habitat_fraction',
                    'occupied_fraction', 'density', 'evidence', 'source_status'), 'density cell')
    rows = {}; subtotal = F(); incomplete = context['source_status'] not in spatial.KNOWN
    for row in cells:
        measure = _measure(row['measure'], 'physical measure')
        habitat = _number(row['habitat_fraction'], 'habitat fraction', maximum=F(1))
        occupied = _number(row['occupied_fraction'], 'occupied fraction', maximum=F(1))
        density = _fields(row['density'], ('value', 'denominator_unit', 'basis'), 'density')
        amount = _number(density['value'], 'conditional density')
        unit = density['denominator_unit']; basis = density['basis']
        if type(unit) is not str or unit not in UNITS or type(basis) is not str or basis not in DENSITY_BASES:
            raise ValueError('explicit density denominator unit/basis required')
        if UNITS[unit][0] != measure['dimension']:
            raise ValueError('density dimension differs from actual physical measure; no 2-D to 3-D conversion')
        known = context['source_status'] in spatial.KNOWN and row['source_status'] in spatial.KNOWN
        available_measure = measure['si_value'] if known else None
        habitat_measure = None if available_measure is None or habitat is None else available_measure*habitat
        occupied_measure = None if habitat_measure is None or occupied is None else habitat_measure*occupied
        denominator = {'PER_WHOLE_CELL_MEASURE': available_measure, 'PER_HABITAT_MEASURE': habitat_measure,
                       'PER_OCCUPIED_MEASURE': occupied_measure}[basis]
        converted_density = None if not known or amount is None else amount/UNITS[unit][1]
        if known and row['eligible'] is False:
            count = F(); status = 'EXCLUDED'
        elif not known or row['eligible'] is None or denominator is None or converted_density is None:
            count = None; status = 'UNKNOWN'; incomplete = True
        else:
            count = denominator*converted_density; status = 'MODELLED'; subtotal += count
            if count > 0 and (habitat == 0 or occupied == 0 or habitat_measure == 0 or occupied_measure == 0):
                raise ValueError('positive density count contradicts an explicitly zero habitat/occupied measure')
        rows[row['cell_id']] = {'status': status, 'eligible': row['eligible'],
            'physical_measure': spatial.quantity(available_measure), 'measure_unit': measure['si_unit'],
            'habitat_measure': spatial.quantity(habitat_measure), 'occupied_measure': spatial.quantity(occupied_measure),
            'density_basis': basis, 'density_per_si_unit': spatial.quantity(converted_density),
            'density_denominator_measure': spatial.quantity(denominator), 'expected_entities': spatial.quantity(count),
            'occupancy_probability': None, 'observed_entities': None,
            'evidence': row['evidence'], 'source_status': row['source_status']}
    return {'schema': 'diadem.declared-density-result.r9', 'status': 'UNKNOWN' if incomplete else 'MODELLED',
        'context': spatial.plain(context), 'inputs_sha256': _bound(spec), 'cells': rows,
        'total_expected_entities': spatial.quantity(None if incomplete else subtotal),
        'known_subtotal_expected_entities': spatial.quantity(subtotal),
        'scope': 'one explicit joint conditional density scenario; no marginal-expectation multiplication, occupancy probability, food capacity, identity register or active bonds'}


def allocate_stock(spec):
    """Conserve scoped stock; normalise all declared weights exactly once.

    Excluded/capped/unresolved shares stay unplaced and never inflate another
    cell's share. Committed zero is an accounting action, not biological absence.
    """
    _fields(spec, ('schema', 'context', 'total_expected_entities', 'cells'), 'prescribed stock input')
    if spec['schema'] != 'diadem.prescribed-stock-input.r9': raise ValueError('stock schema differs')
    context = _context(spec['context'])
    total = _number(spec['total_expected_entities'], 'scoped prescribed total')
    cells = _cells(spec['cells'], ('cell_id', 'eligible', 'weight', 'capacity_expected_entities',
                    'occupied_measure', 'evidence', 'source_status'), 'stock cell', optional=True)
    parsed = []
    for row in cells or []:
        parsed.append((row, _number(row['weight'], 'allocation weight'),
                       _number(row['capacity_expected_entities'], 'finite allocation cap'),
                       _measure(row['occupied_measure'], 'occupied physical measure', optional=True)))
    trusted_total = total if context['source_status'] in spatial.KNOWN else None
    incomplete_weights = any(w is None or row['source_status'] not in spatial.KNOWN for row, w, cap, measure in parsed)
    weights = None if incomplete_weights else sum((w for row, w, cap, measure in parsed), F())
    global_reason = ('scoped total/source is UNKNOWN' if trusted_total is None else
                     'admissible geography missing; stock remains unplaced' if cells is None else
                     'required weight/source UNKNOWN; known subset is not renormalised' if incomplete_weights else
                     'no positive declared weights' if not weights else None)
    rows = {}; placed = F(); has_unknown = trusted_total is None or cells is None or incomplete_weights; conflict = False
    for row, weight, cap, measure in parsed:
        nominal = None if global_reason is not None else trusted_total*weight/weights
        allocation = None; committed = F(); status = 'UNKNOWN'; reason = global_reason
        if global_reason == 'no positive declared weights':
            nominal = F(); allocation = F(); status = 'ZERO_WEIGHT'
        elif nominal is not None:
            if nominal == 0:
                allocation = F(); status = 'ZERO_WEIGHT'; reason = 'zero nominal stock share'
            elif row['eligible'] is False:
                allocation = F(); status = 'EXCLUDED'; reason = 'declared inaccessible/inadmissible share retained unplaced'
            elif row['eligible'] is None or cap is None:
                has_unknown = True; reason = 'eligibility or finite cap UNKNOWN; this share remains uncommitted'
            else:
                allocation = min(nominal, cap)
                if allocation and measure is not None and measure['si_value'] == 0:
                    allocation = None; conflict = True; status = 'CONFLICT'
                    reason = 'positive stock cannot occupy an explicitly zero occupied measure'
                else:
                    committed = allocation; placed += committed
                    status = 'CAPPED' if committed < nominal else 'ALLOCATED'
                    reason = 'capped remainder retained unplaced' if committed < nominal else 'declared share allocated without redistribution'
        measure_known = context['source_status'] in spatial.KNOWN and row['source_status'] in spatial.KNOWN
        implied = None
        if measure_known and allocation is not None and measure is not None and measure['si_value'] not in (None, 0):
            implied = allocation/measure['si_value']
        rows[row['cell_id']] = {'status': status, 'eligible': row['eligible'],
            'nominal_share_expected_entities': spatial.quantity(nominal),
            'allocation_expected_entities': spatial.quantity(allocation),
            'committed_expected_entities': spatial.quantity(committed),
            'unplaced_share_expected_entities': spatial.quantity(None if nominal is None else nominal-committed),
            'occupied_measure': spatial.quantity(None if measure is None or not measure_known else measure['si_value']),
            'measure_unit': None if measure is None else measure['si_unit'],
            'implied_density_per_si_unit': spatial.quantity(implied), 'observed_entities': None,
            'reason': reason, 'evidence': row['evidence'], 'source_status': row['source_status']}
    unplaced = None if trusted_total is None else trusted_total-placed
    if trusted_total is not None and (placed < 0 or unplaced < 0 or placed+unplaced != trusted_total):
        raise ArithmeticError('exact stock conservation failed')
    status = ('CONFLICT' if conflict else 'UNKNOWN' if has_unknown else
              'MODELLED_ALLOCATION_COMPLETE' if unplaced == 0 else 'MODELLED_PARTLY_UNPLACED')
    return {'schema': 'diadem.prescribed-stock-result.r9', 'status': status,
        'context': spatial.plain(context), 'inputs_sha256': _bound(spec), 'cells': rows,
        'total_expected_entities': spatial.quantity(trusted_total), 'placed_expected_entities': spatial.quantity(placed),
        'unplaced_expected_entities': spatial.quantity(unplaced),
        'conservation_residual_expected_entities': spatial.quantity(None if trusted_total is None else F()),
        'normalisation_weight': spatial.quantity(weights), 'reason': global_reason,
        'policy': 'NORMALISE_ALL_DECLARED_WEIGHTS_ONCE; EXCLUDED_CAPPED_OR_UNKNOWN_SHARES_STAY_UNPLACED',
        'scope': 'scoped modelled stock allocation and conditional implied density; not observed occurrence, support-derived population, carrying capacity, food mass or active bonds'}
