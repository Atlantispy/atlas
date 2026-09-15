"""Admit original whole-plot hypotheses, never repair them into productive land.

Source pins and common frame/generation joins are checked by the integrating
reader. Geometry uses captured, unchanged R20 validation. Exact rational areas
refer to represented straight-line coordinates, not surveyed physical accuracy.
"""
from copy import deepcopy
from fractions import Fraction

from shapely.errors import GEOSException

from . import _native_geometry as g

SCHEMA = 'diadem.whole-plot-land-admission.r21'
FALLOW = 'FALLOW'
MAX_PLOTS, MAX_LAYERS, MAX_EXCLUSION_GEOMETRIES, MAX_COORDINATES = 256, 256, 4096, 100000
FORBIDDEN_ROLES = frozenset({'ROOTREACH_NO_CLEARANCE_PROXY', 'INCOMPLETE_MODELLED_NO_CLEARANCE_PROXY'})
UNRESOLVED = frozenset({'UNKNOWN', 'INCOMPLETE', 'CONFLICT', 'PENDING', 'NOT_ASSERTED'})
PLOT_FIELDS = {'id', 'geometry', 'crop_ids', 'management_permission', 'evidence', 'source_status', 'source_role'}
ADMISSION_FIELDS = {'scenario_id', 'source_status', 'evidence', 'land_complete',
                    'exclusions_complete', 'required_exclusion_rules', 'forbidden_source_roles'}


def _text(value, label):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError('bounded explicit '+label+' required')
    return value


def _names(values, label, limit=512):
    if type(values) is not list or len(values) > limit:
        raise ValueError('bounded explicit '+label+' list required')
    result = [_text(value, label) for value in values]
    if len(set(result)) != len(result):
        raise ValueError('duplicate '+label)
    return result


def _uncertain(value):
    # Combined editorial labels must not conceal unresolved data applicability.
    return any(part in UNRESOLVED for part in value.upper().replace('/', ' ').split())


def _forbidden(value, roles):
    return any(role.upper() in value.upper() for role in roles)


def _polygon(value, budget):
    shape = g._polygon(value, budget)
    if budget[0] > MAX_COORDINATES:
        raise ValueError('whole-plot reference coordinate budget exceeded')
    return shape


def _area(shape):
    def ring(coordinates):
        points = [(Fraction(x), Fraction(y)) for x, y in coordinates]
        return abs(sum((a[0]*b[1]-b[0]*a[1] for a, b in zip(points, points[1:])), Fraction(0)))/2
    if shape.is_empty:
        return Fraction(0)
    polygons = list(shape.geoms) if shape.geom_type == 'MultiPolygon' else [shape]
    total = sum((ring(polygon.exterior.coords)-sum((ring(hole.coords) for hole in polygon.interiors), Fraction(0))
                 for polygon in polygons), Fraction(0))
    if total <= 0 or max(total.numerator.bit_length(), total.denominator.bit_length()) > 8192:
        raise ValueError('positive represented polygon area exceeds exact-arithmetic envelope')
    return total


def prepare(plots, land_geometry, exclusions, *, admission):
    """Return plot eligibility and a no-double-area ledger without clipping.

An exclusion layer has ``geometries``: an explicit empty list is an evidenced
empty layer; None is unknown. Every required rule needs at least one resolved
layer. ``land_complete``/``exclusions_complete`` are explicit booleans or None.
PROHIBITED/DENIED management and forbidden provenance block cultivation. Unknown
or CONDITIONAL permission is incomplete, not an implicit grant. FALLOW is a
non-cultivation action, not proof that a blocked candidate is productive land.
"""
    try:
        return _prepare(plots, land_geometry, exclusions, admission)
    except (GEOSException, OverflowError) as exc:
        raise ValueError('whole-plot topology/area could not be certified without repair') from exc


def _prepare(plots, land_geometry, exclusions, admission):
    if type(admission) is not dict or set(admission) != ADMISSION_FIELDS:
        raise ValueError('complete declared land/exclusion/management admission required')
    for key in ('scenario_id', 'source_status', 'evidence'):
        _text(admission[key], key)
    for key in ('land_complete', 'exclusions_complete'):
        if admission[key] is not None and type(admission[key]) is not bool:
            raise ValueError('explicit boolean or unknown '+key+' required')
    required = set(_names(admission['required_exclusion_rules'], 'required exclusion rule', MAX_LAYERS))
    forbidden = FORBIDDEN_ROLES | set(_names(admission['forbidden_source_roles'], 'forbidden source role'))
    if type(plots) is not list or not 1 <= len(plots) <= MAX_PLOTS:
        raise ValueError('1..256 explicit proposed whole plots required')
    if type(exclusions) is not list or len(exclusions) > MAX_LAYERS:
        raise ValueError('explicit bounded exclusion-layer inventory required; unknown is not empty')
    budget, global_missing = [0], []
    if admission['land_complete'] is not True or land_geometry is None:
        global_missing.append('LAND_COVERAGE_INCOMPLETE')
    if admission['exclusions_complete'] is not True:
        global_missing.append('EXCLUSION_COVERAGE_INCOMPLETE')
    if _uncertain(admission['source_status']):
        global_missing.append('ADMISSION_SOURCE_STATUS_UNRESOLVED')
    global_forbidden = _forbidden(admission['source_status'], forbidden)
    land = None if land_geometry is None else _polygon(land_geometry, budget)
    identities, shapes, rows, areas = [], [], {}, {}
    for row in plots:
        if type(row) is not dict or set(row) != PLOT_FIELDS:
            raise ValueError('exact whole-plot fields required')
        for key in ('id', 'evidence', 'source_status', 'source_role'):
            _text(row[key], 'plot '+key)
        ident = row['id']
        if ident in rows:
            raise ValueError('duplicate proposed plot identity')
        crops = _names(row['crop_ids'], 'admitted crop')
        if FALLOW in crops:
            raise ValueError('FALLOW is reserved for the non-cultivation action')
        if row['management_permission'] not in ('ALLOWED', 'DENIED', 'PROHIBITED', 'CONDITIONAL', 'UNKNOWN', 'CONFLICT', None):
            raise ValueError('explicit typed management permission required')
        shape = _polygon(row['geometry'], budget)
        identities.append(ident); shapes.append(shape); rows[ident] = deepcopy(row); areas[ident] = _area(shape)
    ordered = sorted(zip(identities, shapes))
    identities, shapes = [row[0] for row in ordered], [row[1] for row in ordered]
    union = g.union_all(shapes)
    # Native positive-area overlap and exact topological union checks, no epsilon.
    union, _ = g._partition(identities, shapes, union)
    total = sum(areas.values(), Fraction(0)); union_area = _area(union)
    if total != union_area:
        raise ValueError('represented union area differs from exact disjoint original-plot stock')

    layer_ids, resolved_rules, exclusion_shapes, shape_layers, layers = set(), set(), [], [], []
    for layer in exclusions:
        if type(layer) is not dict or set(layer) != {'id', 'geometries', 'rule', 'evidence', 'source_status'}:
            raise ValueError('complete explicit exclusion-layer fields required')
        for key in ('id', 'rule', 'evidence', 'source_status'):
            _text(layer[key], 'exclusion '+key)
        if layer['id'] in layer_ids:
            raise ValueError('duplicate exclusion-layer identity')
        layer_ids.add(layer['id']); layers.append(deepcopy(layer))
        geometries = layer['geometries']
        if geometries is None or _uncertain(layer['source_status']) or _forbidden(layer['source_status'], forbidden):
            global_missing.append('EXCLUSION_LAYER_UNRESOLVED:'+layer['id'])
        else:
            resolved_rules.add(layer['rule'])
        if geometries is None:
            continue
        if type(geometries) is not list or len(exclusion_shapes)+len(geometries) > MAX_EXCLUSION_GEOMETRIES:
            raise ValueError('bounded explicit exclusion geometries required')
        for geometry in geometries:
            exclusion_shapes.append(_polygon(geometry, budget)); shape_layers.append(layer['id'])
    global_missing.extend('REQUIRED_EXCLUSION_RULE_UNRESOLVED:'+rule for rule in sorted(required-resolved_rules))
    tree = g.STRtree(exclusion_shapes) if exclusion_shapes else None
    result_rows, blocked, incomplete = [], [], []
    for ident, shape in zip(identities, shapes):
        row = rows[ident]
        reasons, missing, hits = [], list(global_missing), []
        if land is not None and not shape.difference(land).is_empty:
            reasons.append('OUTSIDE_DECLARED_LAND')
        if tree is not None:
            hits = sorted({shape_layers[int(i)] for i in tree.query(shape, predicate='intersects')
                           if g._has_area(shape.intersection(exclusion_shapes[int(i)]))})
        if hits:
            reasons.append('POSITIVE_AREA_EXCLUSION_INTERSECTION')
        forbidden_source = (global_forbidden or _forbidden(row['source_role'], forbidden)
                            or _forbidden(row['source_status'], forbidden))
        if forbidden_source:
            reasons.append('FORBIDDEN_SOURCE_CANNOT_ESTABLISH_PRODUCTIVE_PLOT')
        elif _uncertain(row['source_status']) or _uncertain(row['source_role']):
            missing.append('PLOT_SOURCE_APPLICABILITY_UNRESOLVED')
        if row['management_permission'] in ('PROHIBITED', 'DENIED'):
            reasons.append('MANAGEMENT_PROHIBITED')
        elif row['management_permission'] != 'ALLOWED':
            missing.append('MANAGEMENT_PERMISSION_UNRESOLVED')
        if reasons:
            status, allowed = 'BLOCKED', [FALLOW]
            blocked.append({'id': ident, 'reasons': reasons, 'exclusion_ids': hits})
        elif missing:
            status, allowed = 'INPUT_INCOMPLETE', None
        else:
            status, allowed = 'ADMITTED_HYPOTHESIS', sorted([FALLOW]+row['crop_ids'])
        if missing:
            incomplete.append({'id': ident, 'reasons': sorted(set(missing))})
        result_rows.append({**row, 'area_m2': g._measure(shape.area, 'plot area', positive=True),
            'area_m2_exact': str(areas[ident]), 'allowed_crop_ids': allowed, 'status': status,
            'blocked_reasons': reasons, 'exclusion_ids': hits, 'incomplete_reasons': sorted(set(missing)),
            'scenario_id': admission['scenario_id'], 'geometry_changed': False,
            'historical_farm_claim': False})
    class_areas = {status: sum((areas[row['id']] for row in result_rows if row['status'] == status), Fraction(0))
                  for status in ('BLOCKED', 'INPUT_INCOMPLETE', 'ADMITTED_HYPOTHESIS')}
    return {'schema': SCHEMA, 'status': 'INPUT_INCOMPLETE' if incomplete else 'PREPARED',
        'plots': result_rows, 'blocked': blocked, 'incomplete': incomplete,
        'admission': deepcopy(admission), 'land_geometry': deepcopy(land_geometry), 'exclusions': layers,
        'ledger': {'candidate_union': g._geojson(union), 'candidate_area_sum_m2_exact': str(total),
            'candidate_union_area_m2_exact': str(union_area), 'double_count_area_m2_exact': '0',
            'area_residual_m2_exact': str(total-union_area),
            'classification_area_m2_exact': {key: str(value) for key, value in class_areas.items()},
            'classification_residual_m2_exact': str(total-sum(class_areas.values(), Fraction(0))),
            'positive_area_plot_overlap': False, 'geometry_mutations': 0,
            'candidate_area_is_not_realised_cropland': True},
        'numerics': {**g.NUMERICS, 'area_ledger': 'EXACT_RATIONAL_SHOELACE_OF_REPRESENTED_COORDINATES',
                     'exclusion_test': 'POSITIVE_AREAL_INTERSECTION; NO_TOLERANCE_OR_CLIPPING',
                     'reference_limits': {'plots': MAX_PLOTS, 'exclusion_layers': MAX_LAYERS,
                                          'coordinates': MAX_COORDINATES}}}
