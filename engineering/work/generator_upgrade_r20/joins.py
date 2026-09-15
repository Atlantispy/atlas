"""Read-only settlement and access joins; jurisdiction never implies permission."""
from copy import deepcopy
import math
from shapely.geometry import Point, shape
from shapely.strtree import STRtree
from . import provenance as p, inputs


def _binding(generation, expected_generation, context, expected_context):
    if not isinstance(generation, str) or not generation or generation != expected_generation:
        raise ValueError('exact political generation required; stale IDs cannot be joined')
    inputs.context(context); inputs.context(expected_context)
    if context != expected_context:
        raise ValueError('political world/date/frame mismatch')


def _hierarchy(value):
    fields = {'barony_id', 'county_id', 'duchy_id', 'surface_fill', 'haus'}
    if type(value) is not dict or set(value) != fields:
        raise ValueError('complete typed hierarchy required')
    if any(type(value[key]) is not str or not value[key].strip()
           for key in fields-{'haus'}):
        raise ValueError('resolved administrative and surface identities required')
    if (type(value['haus']) is not list or any(type(v) is not str or not v for v in value['haus'])
            or len(set(value['haus'])) != len(value['haus'])):
        raise ValueError('explicit unique Haus relationships required, including neutral empty list')


def sites(records, prepared, hierarchy, *, generation, expected_generation,
          context, expected_context):
    """Associate unchanged sites with complete unit memberships, never move them.

    Boundary sites receive a binding only when every touched support has the same
    full hierarchy; otherwise retain explicit ambiguity, not nearest-owner fill.
    The caller must provide compatible explicit metre coordinates and a validated
    complete support set. No accepted-world or settlement-selection claim follows.
    """
    _binding(generation, expected_generation, context, expected_context)
    units = prepared['supports']
    ids = [row['id'] for row in units]
    if set(hierarchy) != set(ids):
        raise ValueError('complete source-qualified unit hierarchy required')
    for value in hierarchy.values():
        _hierarchy(value)
    polygons = [shape(row['geometry']) for row in units]
    tree = STRtree(polygons)
    seen, result = set(), []
    for row in records:
        if type(row) is not dict or set(row) != {'id', 'xy_m', 'source_status'}:
            raise ValueError('exact site record required')
        ident, xy = row['id'], row['xy_m']
        if type(ident) is not str or not ident or ident in seen:
            raise ValueError('unique site identity required')
        if (type(xy) is not list or len(xy) != 2 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in xy)):
            raise ValueError('finite metre site point required')
        if type(row['source_status']) is not str or not row['source_status']:
            raise ValueError('site source status required')
        seen.add(ident)
        point = Point(xy)
        touched = sorted(ids[int(i)] for i in tree.query(point)
                         if polygons[int(i)].covers(point))
        values = {p.sha(hierarchy[ident]): hierarchy[ident] for ident in touched}
        status = 'ASSIGNED' if len(values) == 1 else 'BOUNDARY_AMBIGUOUS' if values else 'OUTSIDE_DOMAIN'
        result.append({**deepcopy(row), 'political_generation': generation, 'context': deepcopy(context),
            'support_ids': touched, 'political_binding': deepcopy(next(iter(values.values()))) if len(values) == 1 else None,
            'status': status})
    return sorted(result, key=lambda row: row['id'])


def access(records, site_bindings, *, generation, expected_generation,
           context, expected_context):
    """Keep finite physical travel and legal permission as independent claims."""
    _binding(generation, expected_generation, context, expected_context)
    sites_by_id = {row['id']: row for row in site_bindings}
    if len(sites_by_id) != len(site_bindings) or any(
            row['political_generation'] != generation or row.get('context') != context for row in site_bindings):
        raise ValueError('unique current-generation site bindings required')
    seen, result = set(), []
    for row in records:
        fields = {'id', 'from_site', 'to_site', 'physical_travel_seconds',
                  'permission', 'mode', 'season', 'evidence', 'source_status'}
        if type(row) is not dict or set(row) != fields:
            raise ValueError('exact access record required')
        ident = row['id']
        if type(ident) is not str or not ident or ident in seen:
            raise ValueError('unique access identity required')
        seen.add(ident)
        if row['from_site'] not in sites_by_id or row['to_site'] not in sites_by_id:
            raise ValueError('access endpoint must be an existing supplied site')
        seconds = row['physical_travel_seconds']
        if seconds is not None and (type(seconds) not in (int, float) or
                                     not math.isfinite(seconds) or seconds < 0):
            raise ValueError('finite nonnegative physical travel or unknown required')
        permission = row['permission']
        if permission not in ('ALLOWED', 'PROHIBITED', 'CONDITIONAL', 'UNKNOWN'):
            raise ValueError('explicit typed access permission required')
        if any(type(row[key]) is not str or not row[key] for key in ('mode', 'season', 'evidence', 'source_status')):
            raise ValueError('access mode, season, evidence and status required')
        endpoints_known = all(sites_by_id[row[key]]['status'] == 'ASSIGNED'
                              for key in ('from_site', 'to_site'))
        if endpoints_known:
            for key in ('from_site', 'to_site'):
                _hierarchy(sites_by_id[row[key]]['political_binding'])
        permitted = (permission == 'ALLOWED' and seconds is not None and endpoints_known)
        result.append({**deepcopy(row), 'political_generation': generation, 'context': deepcopy(context),
                       'permitted_travel_seconds': seconds if permitted else None,
                       'legal_status': permission, 'jurisdiction_resolved': endpoints_known,
                       'sovereignty_transfer': False})
    return sorted(result, key=lambda row: row['id'])
