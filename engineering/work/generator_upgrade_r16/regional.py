"""Construct a supplied regional geology snapshot and use its actual erosion laws.

Construction events define a snapshot, not an inferred tectonic history. There
is no automatic map warp, plate velocity, hydraulic property or erosion default.
"""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import math
from pathlib import Path
import time

from work.generator_upgrade_r13 import year as contract
from work.generator_upgrade_r14 import terrain
from . import provenance as p
from .columns import build_columns

SCHEMA = 'diadem.regional-construction-recipe.r16'
FRAME = {'world_id', 'snapshot_id', 'spatial_frame_id', 'vertical_reference'}


def _owner_source(source):
    contract.exact(source, ('path', 'sha256'), 'regional owner source')
    path = Path(source['path'])
    if not path.is_absolute():
        raise ValueError('absolute owner contract path required')
    with path.open('rb') as stream:
        raw = stream.read(262145)
    if len(raw) > 262144 or hashlib.sha256(raw).hexdigest() != source['sha256']:
        raise ValueError('owner contract changed or exceeds budget; no repin')


def _signed(value):
    if type(value) not in (int, float, str) or isinstance(value, str) and len(value) > 5000:
        raise ValueError('bounded explicit physical quantity required')
    result = F(value)
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > 8192:
        raise ValueError('regional quantity exceeds exact arithmetic budget')
    return result


def _plain(value):
    if isinstance(value, F):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {key: _plain(v) for key, v in value.items()}
    return value


def build(recipe):
    """Generate finite stratigraphy, displaced surfaces and exposed materials."""
    started = time.perf_counter()
    contract.plain(recipe)
    recipe = deepcopy(recipe)
    contract.exact(recipe, ('schema', 'context', 'source_status', 'evidence',
                           'owner_source', 'supports', 'events'), 'regional construction')
    if recipe['schema'] != SCHEMA or len(p.encoded(recipe)) > 2**20:
        raise ValueError('bounded R16 construction recipe required')
    contract.exact(recipe['context'], FRAME, 'regional construction frame')
    for value in (*recipe['context'].values(), recipe['evidence']):
        contract.text(value)
        if value in {'UNKNOWN', 'CONFLICT', 'INCOMPLETE'}:
            raise ValueError('unresolved regional context')
    if recipe['source_status'] not in {'WORKING NON-CANON', 'SYNTHETIC TEST'}:
        raise ValueError('explicit working/synthetic regional scenario required')
    _owner_source(recipe['owner_source'])
    binding = p.identity()
    _, native = p.backend()
    supports = recipe['supports']
    if type(supports) is not dict or not 1 <= len(supports) <= 32:
        raise ValueError('one to 32 explicit regional supports required')
    initial = {}
    for key, row in supports.items():
        contract.text(key)
        contract.exact(row, ('xy_m', 'area_m2', 'basal_elevation_m'), 'regional support')
        if type(row['xy_m']) is not list or len(row['xy_m']) != 2:
            raise ValueError('explicit regional XY coordinates required')
        for v in row['xy_m']:
            if not math.isfinite(float(_signed(v))):
                raise ValueError('finite representable regional coordinates required')
        initial[key] = native.Column(_signed(row['area_m2']), _signed(row['basal_elevation_m']),
                                     (), recipe['source_status'])
    current, construction = build_columns(initial, recipe['events'])
    state = native.LandscapeState(tuple(sorted(current.items())))
    stratigraphy = {}
    for key, column in current.items():
        bottom = column.basal_elevation_m
        rows = []
        for layer in column.layers:
            top = bottom+layer.bulk_volume_m3/column.area_m2
            rows.append({'material_id': layer.material_id, 'phase': layer.phase,
                'bottom_m': str(bottom), 'top_m': str(top), 'mass_kg': str(layer.mass_kg),
                'grain_density_kg_m3': str(layer.grain_density_kg_m3),
                'porosity': str(layer.porosity), 'evidence': layer.evidence})
            bottom = top
        stratigraphy[key] = {'bottom_to_top': rows, 'surface_m': str(column.surface_m),
            'exposed_material': None if column.exposed is None else column.exposed.material_id,
            'finite_stock_exhausted': not rows}
    science = {'schema': 'diadem.regional-geology-snapshot.r16',
        'status': 'CONSTRUCTED_PRESCRIBED_REGIONAL_SNAPSHOT', 'source_status': recipe['source_status'],
        'context': recipe['context'], 'supports': supports, 'owner_source': recipe['owner_source'],
        'recipe_sha256': p.sha(recipe), 'source_sha256': p.sha(binding),
        'state': state.as_dict(), 'stratigraphy': stratigraphy, 'construction': construction,
        'plate_motion_inferred': False, 'isostasy_solved': False, 'geology_calibrated': False,
        'production_authorised': False, 'whole_diadem_year_verified': False, 'canon_changed': False}
    p.verify(binding)
    return {'scientific': science, 'execution': {'identity': binding, 'scientific_sha256': p.sha(science),
            'elapsed_wall_seconds': time.perf_counter()-started}}


def terrain_step(snapshot, forcing):
    """One existing bounded R14 trial on the generated geology, not a year run.

The caller owns chronological/adaptive coupling. Here the prescribed runoff
volume and duration are explicit. Changed geology affects native exposure,
erodibility, drainage slopes, exported material and deposited sediment.
"""
    binding = snapshot['execution']['identity']
    p.verify(binding)
    science = snapshot['scientific']
    if snapshot['execution']['scientific_sha256'] != p.sha(science):
        raise ValueError('regional state/receipt changed after construction')
    if science['source_sha256'] != p.sha(binding):
        raise ValueError('regional result/source binding differs')
    _owner_source(science['owner_source'])
    contract.plain(forcing)
    contract.exact(forcing, ('duration_years', 'local_runoff_m3', 'connectors',
        'erosion_laws', 'sediment_laws', 'controls', 'evidence', 'source_status'), 'regional terrain forcing')
    if forcing['source_status'] != science['source_status']:
        raise ValueError('regional forcing/scenario status differs')
    _, native = p.backend()
    state = native.LandscapeState.from_dict(science['state'])
    connectors = []
    for row in forcing['connectors']:
        edge = native.Connector(**row)
        if edge.receiver_id is not None:
            a, b = (science['supports'][key]['xy_m'] for key in (edge.source_id, edge.receiver_id))
            distance = math.hypot(float(_signed(a[0])-_signed(b[0])), float(_signed(a[1])-_signed(b[1])))
            if not distance > 0 or not math.isclose(float(edge.length_m), distance, rel_tol=1e-12):
                raise ValueError('connector length differs from construction support coordinates')
        connectors.append(edge)
    laws = []
    for row in forcing['erosion_laws']:
        properties = []
        for name in ('k_per_year', 'reference_runoff_m_year'):
            if row[name]['status'] != science['source_status']:
                raise ValueError('erosion law cannot promote a different input status')
            properties.append(native.PhysicalProperty(**row[name]))
        laws.append(native.ErosionLaw(row['material_id'], row['phase'], *properties))
    result = terrain.trial(state, forcing['local_runoff_m3'], tuple(connectors), laws,
        [native.SedimentLaw(**row) for row in forcing['sediment_laws']],
        duration_years=forcing['duration_years'], controls=native.TrialControls(**forcing['controls']),
        evidence_id=forcing['evidence'])
    p.verify(binding)
    return {'state': result.state.as_dict(), 'receipt': _plain(result.receipt),
            'input_recipe_sha256': science['recipe_sha256'], 'forcing_sha256': p.sha(forcing),
            'source_status': science['source_status'],
            'native_receipt_status_scope': 'retained R14 implementation label; input/scenario status is stated separately',
            'whole_diadem_year_verified': False}
