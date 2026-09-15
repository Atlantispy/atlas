"""Neutral planar support topology; no political assignment or geometry repair.

Coordinates are explicit two-dimensional metres in an already aligned frame.
GEOS operates on their binary64 representation: 'exact topology' here means
empty/nonempty topological differences without a user-invented tolerance, not
arbitrary-precision Euclidean arithmetic. Reported areas/lengths are binary64.
"""
import math

from shapely import STRtree, normalize, union_all, __version__, geos_version_string
from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection, mapping, shape


PREPARED = 'diadem.neutral-planar-supports.r20'
DISSOLVED = 'diadem.neutral-grouped-supports.r20'
MAX_SUPPORTS, MAX_COORDINATES = 300000, 3000000
NUMERICS = {'engine': 'SHAPELY_GEOS', 'shapely_version': __version__,
    'geos_version': geos_version_string,
    'geometry_precision': 'BINARY64; EMPTY_TOPOLOGICAL_DIFFERENCES; NO_SNAP_REPAIR_OR_TOLERANCE',
    'area_length_reporting': 'BINARY64_METRES_AND_SQUARE_METRES; REPORTING_RESIDUALS_ARE_NOT_ACCEPTANCE_TOLERANCES'}


def _label(value):
    if type(value) is not str or not value.strip() or len(value) > 1024:
        raise ValueError('bounded nonblank support/group identity required')
    return value


def _plain(value):
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if type(value) is float and value == 0:
        return 0.0  # canonicalise signed zero; no geometric displacement
    return value


def _geojson(geometry):
    return _plain(mapping(normalize(geometry)))


def _measure(value, name, *, positive=False):
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(name+' cannot be represented as a finite positive/nonnegative measure')
    return value


def _polygon(data, budget):
    if type(data) is not dict or set(data) != {'type', 'coordinates'}:
        raise ValueError('bare Polygon/MultiPolygon GeoJSON with exact type/coordinates fields required')
    kind = data['type']
    if kind not in ('Polygon', 'MultiPolygon'):
        raise ValueError('areal Polygon/MultiPolygon required; lines/points are not supports')
    polygons = [data['coordinates']] if kind == 'Polygon' else data['coordinates']
    if type(polygons) not in (list, tuple) or not polygons:
        raise ValueError('empty polygon/multipolygon is not a support')
    for polygon in polygons:
        if type(polygon) not in (list, tuple) or not polygon:
            raise ValueError('explicit nonempty exterior/interior rings required')
        for ring in polygon:
            if type(ring) not in (list, tuple) or len(ring) < 4:
                raise ValueError('explicit closed ring with at least four coordinates required')
            budget[0] += len(ring)
            if budget[0] > MAX_COORDINATES:
                raise ValueError('planar support coordinate budget exceeded')
            for coordinate in ring:
                if type(coordinate) not in (list, tuple) or len(coordinate) != 2:
                    raise ValueError('explicit XY only; no silently discarded height/measure')
                for number in coordinate:
                    if type(number) not in (int, float):
                        raise ValueError('finite JSON coordinate number required')
                    try:
                        value = float(number)
                    except OverflowError as exc:
                        raise ValueError('coordinate exceeds binary64 range') from exc
                    if not math.isfinite(value) or (type(number) is int and value != number):
                        raise ValueError('coordinate is nonfinite or not exactly binary64-representable')
            if tuple(ring[0]) != tuple(ring[-1]):
                raise ValueError('ring must already be closed; no automatic geometry repair')
    result = shape(data)
    if result.is_empty or not result.is_valid:
        raise ValueError('invalid/empty polygon geometry; no repair or buffer permitted')
    _measure(result.area, 'polygon area', positive=True)
    _measure(result.length, 'polygon boundary length', positive=True)
    return normalize(result)


def _has_area(geometry):
    if geometry.is_empty:
        return False
    if geometry.geom_type in ('Polygon', 'MultiPolygon'):
        return True
    return any(_has_area(part) for part in geometry.geoms) if geometry.geom_type == 'GeometryCollection' else False


def _lines(geometry):
    """Discard point-only contacts, never misreport them as adjacency."""
    if geometry.is_empty:
        return GeometryCollection()
    if geometry.geom_type in ('LineString', 'LinearRing', 'MultiLineString'):
        _measure(geometry.length, 'shared boundary length', positive=True)
        return geometry
    if geometry.geom_type == 'GeometryCollection':
        pieces = [_lines(part) for part in geometry.geoms]
        pieces = [part for part in pieces if not part.is_empty]
        return union_all(pieces) if pieces else GeometryCollection()
    if geometry.geom_type in ('Point', 'MultiPoint'):
        return GeometryCollection()
    raise ArithmeticError('shared polygon boundary unexpectedly contains an areal geometry')


def _partition(identities, geometries, domain):
    tree = STRtree(geometries)
    edges = []
    for index, geometry in enumerate(geometries):
        for other in sorted(int(value) for value in tree.query(geometry, predicate='intersects') if int(value) > index):
            overlap = geometry.intersection(geometries[other])
            if _has_area(overlap):
                raise ValueError('overlapping support area: '+identities[index]+' / '+identities[other])
            shared = _lines(geometry.boundary.intersection(geometries[other].boundary))
            if not shared.is_empty:
                edges.append({'left': identities[index], 'right': identities[other],
                    'length_m': _measure(shared.length, 'shared boundary length', positive=True),
                    'geometry': _geojson(shared)})
    covered = union_all(geometries)
    if not covered.difference(domain).is_empty:
        raise ValueError('supports extend outside the declared domain')
    if not domain.difference(covered).is_empty:
        raise ValueError('supports leave a gap in the declared domain')
    if covered.is_empty or not covered.is_valid or covered.geom_type not in ('Polygon', 'MultiPolygon'):
        raise ValueError('covered polygon topology is invalid; no repair permitted')
    return covered, edges


def _prepare(supports, domain):
    if type(supports) is not list or not 1 <= len(supports) <= MAX_SUPPORTS:
        raise ValueError('bounded nonempty support list required')
    seen, rows, budget = set(), [], [0]
    declared = _polygon(domain, budget)
    for row in supports:
        if type(row) is not dict or set(row) != {'id', 'geometry'}:
            raise ValueError('support requires exactly id and geometry')
        identity = _label(row['id'])
        if identity in seen:
            raise ValueError('duplicate support identity')
        seen.add(identity)
        rows.append((identity, _polygon(row['geometry'], budget)))
    rows.sort(key=lambda row: row[0])
    identities = [row[0] for row in rows]
    geometries = [row[1] for row in rows]
    covered, edges = _partition(identities, geometries, declared)
    areas = [_measure(geometry.area, 'support area', positive=True) for geometry in geometries]
    total = math.fsum(areas)
    _measure(total, 'summed support area', positive=True)
    covered_area = _measure(covered.area, 'covered area', positive=True)
    report = {'schema': PREPARED, 'domain': _geojson(declared),
        'supports': [{'id': identity, 'geometry': _geojson(geometry), 'area_m2': area}
                     for (identity, geometry), area in zip(rows, areas)],
        'edges': edges, 'domain_boundary': _geojson(declared.boundary),
        'domain_area_m2': _measure(declared.area, 'domain area', positive=True),
        'covered_area_m2': covered_area, 'support_area_sum_m2': total,
        'area_reporting_residual_m2': total-covered_area,
        'coverage': {'outside_empty': True, 'gap_empty': True, 'positive_area_overlap': False},
        'numerics': dict(NUMERICS)}
    return report, declared, dict(rows)


def prepare(supports, domain):
    """Return canonical, source-neutral complete polygon support topology.

STRtree limits overlap/shared-boundary comparisons to spatial candidates.
Point-touching polygons are valid inputs but have NO positive-length edge.
Shapely normalisation only orders rings/vertices/parts; it does not snap or fix.
"""
    try:
        return _prepare(supports, domain)[0]
    except (GEOSException, OverflowError) as exc:
        raise ValueError('planar topology/measure could not be evaluated without repair') from exc


def _components(members, edges):
    adjacency = {identity: set() for identity in members}
    for edge in edges:
        if edge['left'] in adjacency and edge['right'] in adjacency:
            adjacency[edge['left']].add(edge['right'])
            adjacency[edge['right']].add(edge['left'])
    visited, answer = set(), []
    for seed in sorted(members):
        if seed in visited:
            continue
        pending = [seed]; found = set()
        while pending:
            identity = pending.pop()
            if identity in found:
                continue
            found.add(identity)
            pending.extend(adjacency[identity]-found)
        visited.update(found)
        answer.append(sorted(found))
    return answer


def dissolve(prepared, memberships):
    """Dissolve an explicit complete membership map; choose no assignments.

Prepared topology/metrics are rebuilt and checked, not trusted from supplied
receipt values. Disconnected groups remain explicitly flagged for the caller's
policy decision; a MultiPolygon support cannot hide its own disconnected parts.
"""
    try:
        if type(prepared) is not dict or prepared.get('schema') != PREPARED:
            raise ValueError('prepared neutral support report required')
        raw = []
        for row in prepared['supports']:
            if type(row) is not dict or set(row) != {'id', 'geometry', 'area_m2'}:
                raise ValueError('prepared support row changed')
            raw.append({'id': row['id'], 'geometry': row['geometry']})
        checked, domain, support_shapes = _prepare(raw, prepared['domain'])
        if checked != prepared:
            raise ValueError('prepared topology/metric report differs from its actual geometries')
        if type(memberships) is not dict or set(memberships) != set(support_shapes):
            raise ValueError('complete exactly-once support membership required')
        groups = {}
        for unit, group in sorted(memberships.items()):
            groups.setdefault(_label(group), []).append(unit)
        group_ids = sorted(groups)
        shapes = [normalize(union_all([support_shapes[unit] for unit in groups[group]])) for group in group_ids]
        covered, edges = _partition(group_ids, shapes, domain)
        shape_by_id = dict(zip(group_ids, shapes))
        external, internal, internal_by_group = {}, [], {}
        for edge in checked['edges']:
            left, right = memberships[edge['left']], memberships[edge['right']]
            if left == right:
                internal.append(edge)
                internal_by_group.setdefault(left, []).append(edge)
                if not _lines(shape(edge['geometry']).intersection(shape_by_id[left].boundary)).is_empty:
                    raise ArithmeticError('internal unit boundary remains on its dissolved group boundary')
            else:
                external.setdefault(tuple(sorted((left, right))), []).append(edge)
        actual_edges = {(row['left'], row['right']): row for row in edges}
        if set(external) != set(actual_edges):
            raise ArithmeticError('group adjacency differs from its positive-length unit boundaries')
        for pair, pieces in external.items():
            inherited = union_all([shape(row['geometry']) for row in pieces])
            if not inherited.symmetric_difference(shape(actual_edges[pair]['geometry'])).is_empty:
                raise ArithmeticError('dissolved group border differs from exact retained unit borders')
        rows, disconnected = [], []
        for group, geometry in zip(group_ids, shapes):
            components = _components(groups[group], internal_by_group.get(group, ()))
            count = len(geometry.geoms) if geometry.geom_type == 'MultiPolygon' else 1
            connected = len(components) == 1 and count == 1
            if not connected:
                disconnected.append(group)
            area = _measure(geometry.area, 'group area', positive=True)
            member_area = math.fsum(support_shapes[unit].area for unit in groups[group])
            rows.append({'id': group, 'members': groups[group], 'geometry': _geojson(geometry),
                'area_m2': area, 'member_area_sum_m2': member_area,
                'area_reporting_residual_m2': member_area-area,
                'positive_edge_components': components, 'polygon_component_count': count,
                'connected': connected})
        unit_perimeter = math.fsum(geometry.length for geometry in support_shapes.values())
        shared = math.fsum(edge['length_m'] for edge in checked['edges'])
        exterior = _measure(domain.length, 'domain boundary length', positive=True)
        return {'schema': DISSOLVED, 'domain': _geojson(domain), 'groups': rows, 'edges': edges,
            'domain_area_m2': checked['domain_area_m2'],
            'covered_area_m2': _measure(covered.area, 'dissolved covered area', positive=True),
            'group_area_sum_m2': math.fsum(row['area_m2'] for row in rows),
            'disconnected_groups': disconnected,
            'connectivity_status': 'DISCONNECTED_GROUPS_REQUIRE_CALLER_DECISION' if disconnected else 'ALL_GROUPS_POSITIVE_EDGE_CONNECTED',
            'boundary_ledger': {'absorbed_internal_unit_edges': internal,
                'absorbed_internal_length_m': math.fsum(edge['length_m'] for edge in internal),
                'retained_between_groups_length_m': math.fsum(edge['length_m'] for edge in edges),
                'domain_boundary_length_m': exterior, 'unit_boundary_length_sum_m': unit_perimeter,
                'perimeter_reporting_residual_m': math.fsum((unit_perimeter, -exterior, -2*shared)),
                'retained_boundary_topology_verified': True},
            'coverage': dict(checked['coverage']), 'numerics': dict(NUMERICS)}
    except (GEOSException, OverflowError) as exc:
        raise ValueError('dissolved topology/measure could not be evaluated without repair') from exc
