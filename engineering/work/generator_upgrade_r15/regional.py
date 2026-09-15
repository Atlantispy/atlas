"""Snapshot input connection, not a plate simulator or a geology calibration.

Continuous geological priors remain evidence. Only explicitly supplied physical
columns and metre-valued base elevations enter the numerical ground model.
Sampling is bilinear at declared support points, not conservative area remapping.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import zipfile

import numpy as np

from work.generator_upgrade_r14 import pipeline, transport
from work.generator_upgrade_r13 import year as contract

SCHEMA = 'diadem.regional-ground-inputs.r15'
STATUSES = {'WORKING NON-CANON', 'SYNTHETIC TEST'}
MAX_SOURCE_BYTES = 512 * 1024**2
MAX_ARRAY_BYTES = 128 * 1024**2
MAX_TOTAL_ARRAY_BYTES = 512 * 1024**2
_SOURCE = Path(__file__).read_bytes()
if sys._getframe().f_code != compile(_SOURCE, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed regional adapter differs from current source')
_SOURCE_SHA = hashlib.sha256(_SOURCE).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('explicit finite regional number required')
    return float(value)


def label(value):
    contract.text(value)
    if value in {'UNKNOWN', 'INCOMPLETE', 'CONFLICT'}:
        raise ValueError('unresolved regional identity or evidence')


def sample(array, grid, registration, xy_m):
    """Use first-SAMPLE coordinates; nodes and cell centres are not conflated."""
    contract.exact(grid, ('frame_id', 'unit', 'sample_location', 'first_sample_m',
                          'step_m'), 'regional grid')
    label(grid['frame_id'])
    if grid['unit'] != 'm' or grid['sample_location'] not in ('cell_centres', 'nodes'):
        raise ValueError('explicit metre-valued node/cell-centre grid required')
    contract.exact(registration, ('source_frame_id', 'target_frame_id',
        'target_to_source_affine', 'evidence', 'source_status'), 'regional registration')
    for key in ('source_frame_id', 'target_frame_id', 'evidence'):
        label(registration[key])
    if registration['source_frame_id'] != grid['frame_id']:
        raise ValueError('registration does not describe the source grid')
    if registration['source_status'] not in STATUSES:
        raise ValueError('registration is unresolved')
    affine = np.asarray(registration['target_to_source_affine'])
    if affine.shape != (2, 3) or affine.dtype.kind not in 'fi' or not np.isfinite(affine).all():
        raise ValueError('finite 2 by 3 affine in metres required')
    if not math.isfinite(float(np.linalg.det(affine[:, :2]))) or np.linalg.det(affine[:, :2]) == 0:
        raise ValueError('non-singular registration required')
    if len(xy_m) != 2 or len(grid['first_sample_m']) != 2 or len(grid['step_m']) != 2:
        raise ValueError('explicit XY coordinate pairs required')
    x, y = [finite(v) for v in xy_m]
    x0, y0 = [finite(v) for v in grid['first_sample_m']]
    dx, dy = [finite(v) for v in grid['step_m']]
    if dx == 0 or dy == 0:
        raise ValueError('nonzero signed grid spacing required')
    a = np.asarray(array)
    if a.ndim != 2 or min(a.shape) < 1 or a.dtype.kind not in 'fi':
        raise ValueError('numeric two-dimensional regional field required')
    sx, sy = affine @ [x, y, 1.]
    col, row = (sx-x0)/dx, (sy-y0)/dy
    if not (0 <= row <= a.shape[0]-1 and 0 <= col <= a.shape[1]-1):
        raise ValueError('support outside sampled source coverage; no edge extension')
    r0, c0 = math.floor(row), math.floor(col)
    r1, c1 = min(r0+1, a.shape[0]-1), min(c0+1, a.shape[1]-1)
    ry, cx = row-r0, col-c0
    terms = []
    for r, c, w in ((r0, c0, (1-ry)*(1-cx)), (r0, c1, (1-ry)*cx),
                    (r1, c0, ry*(1-cx)), (r1, c1, ry*cx)):
        if w:
            value = float(a[r, c])
            if not math.isfinite(value):
                raise ValueError('regional support intersects UNKNOWN source coverage')
            terms.append(w*value)
    return finite(math.fsum(terms))


def _checked_array(stream):
    version = np.lib.format.read_magic(stream)
    readers = {(1, 0): np.lib.format.read_array_header_1_0,
               (2, 0): np.lib.format.read_array_header_2_0}
    if version not in readers:
        raise ValueError('supported NPY numeric header required')
    shape, _, dtype = readers[version](stream)
    if (len(shape) != 2 or min(shape) < 1 or dtype.kind not in 'fi'
            or math.prod(shape)*dtype.itemsize > MAX_ARRAY_BYTES):
        raise ValueError('regional decoded array exceeds shape/type/byte budget')
    stream.seek(0)
    return np.load(stream, allow_pickle=False)


def read_field(record):
    """Hash the exact bytes decoded; no historical script or pickle execution."""
    contract.exact(record, ('path', 'sha256', 'array_key', 'grid', 'registration',
                            'unit', 'role', 'reference', 'evidence', 'source_status'), 'regional field')
    label(record['evidence'])
    if record['source_status'] not in STATUSES:
        raise ValueError('regional field is unresolved')
    path = Path(record['path'])
    if not path.is_absolute() or path.suffix.lower() not in ('.npy', '.npz'):
        raise ValueError('explicit absolute NPY/NPZ field path required')
    # A bounded read also catches a file that grows after its size was inspected.
    with path.open('rb') as stream:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError('regional source file exceeds byte budget')
        raw = stream.read(MAX_SOURCE_BYTES+1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError('regional source file exceeds byte budget')
    if hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise ValueError('regional source changed; no automatic repin')
    if path.suffix.lower() == '.npz':
        with zipfile.ZipFile(io.BytesIO(raw)) as loaded:
            if not isinstance(record['array_key'], str):
                raise ValueError('explicit NPZ array key required')
            name = record['array_key']+'.npy'
            if loaded.namelist().count(name) != 1 or loaded.getinfo(name).file_size > MAX_ARRAY_BYTES+16384:
                raise ValueError('unique bounded NPZ member required')
            with loaded.open(name) as member:
                array = _checked_array(member)
    else:
        if record['array_key'] is not None:
            raise ValueError('NPY input cannot select an archive key')
        array = _checked_array(io.BytesIO(raw))
    return array


def prepare(template, packet):
    """Build a normal R14 recipe, binding source decisions into its cache identity.

The caller supplies complete initial physical columns, laws, connectors and
forcing. No profile is inferred from a dominant-affinity/structural-block code.
The template's cells are replaced together, never remapped onto a resumed state.
"""
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _SOURCE_SHA:
        raise ValueError('regional adapter changed since import; no automatic repin')
    contract.plain(packet)
    contract.exact(packet, ('schema', 'context', 'source_status', 'evidence',
                            'fields', 'columns'), 'regional packet')
    if packet['schema'] != SCHEMA or packet['source_status'] not in STATUSES:
        raise ValueError('known, explicitly status-labelled R15 regional packet required')
    label(packet['evidence'])
    if packet['context'] != template['context']:
        raise ValueError('regional world/snapshot/frame/calendar differs from target recipe')
    if packet['source_status'] != template['source_status']:
        raise ValueError('regional/template source status differs')
    if (type(packet['columns']) is not dict or not 1 <= len(packet['columns']) <= 32
            or set(packet['columns']) != set(template['cells'])):
        raise ValueError('one explicit assignment per bounded target column required')
    if type(packet['fields']) is not dict or not 1 <= len(packet['fields']) <= 64 or 'base' not in packet['fields']:
        raise ValueError('explicit regional base field required')
    base = packet['fields']['base']
    if base['role'] != 'physical_base_elevation' or base['unit'] != 'm':
        raise ValueError('physical base elevation in metres required, not an accommodation prior')
    # The base is in the context vertical reference: relief/displacement must
    # already be resolved by its owner; no mm/year-to-height conversion occurs.
    fields = {}
    for key, row in packet['fields'].items():
        label(key); label(row['unit'])
        contract.exact(row['reference'], ('world_id', 'snapshot_id', 'vertical_reference'), 'field reference')
        for name in ('world_id', 'snapshot_id'):
            label(row['reference'][name])
        if row['reference']['world_id'] != packet['context']['world_id']:
            raise ValueError('regional field belongs to another world')
        if key == 'base':
            label(row['reference']['vertical_reference'])
            if any(row['reference'][name] != packet['context'][name] for name in row['reference']):
                raise ValueError('base elevation snapshot/vertical reference differs')
        if key != 'base' and row['role'] != 'continuous_constraint_prior':
            raise ValueError('only continuous priors may accompany the physical base')
        if row['registration']['target_frame_id'] != packet['context']['spatial_frame_id']:
            raise ValueError('regional registration target differs from recipe frame')
        if row['source_status'] != packet['source_status'] or row['registration']['source_status'] != packet['source_status']:
            raise ValueError('regional source/registration status differs; no promotion')
        fields[key] = read_field(row)
        if sum(a.nbytes for a in fields.values()) > MAX_TOTAL_ARRAY_BYTES:
            raise ValueError('regional field collection exceeds byte budget')
    result = deepcopy(template)
    samples = {}
    densities = {}
    for key, row in packet['columns'].items():
        contract.exact(row, ('xy_m', 'physical_column', 'assignment_evidence',
                            'source_status'), 'regional column assignment')
        label(row['assignment_evidence'])
        if row['source_status'] != packet['source_status']:
            raise ValueError('regional column assignment status differs')
        cell = deepcopy(row['physical_column'])
        contract.exact(cell, pipeline.CELL-{'base_elevation_m'}, 'initial regional physical column')
        if cell['soil']['elapsed_seconds'] != 0:
            raise ValueError('regional initialisation cannot overwrite continuing seasonal state')
        samples[key] = {name: sample(fields[name], record['grid'], record['registration'], row['xy_m'])
                        for name, record in packet['fields'].items()}
        cell['base_elevation_m'] = samples[key]['base']
        for material in cell['materials']:
            identity = material['material_id']
            density = Fraction(material['grain_density_kg_m3'])
            if densities.setdefault(identity, density) != density:
                raise ValueError('one material identity cannot have conflicting grain densities')
        result['cells'][key] = cell
    # Supplied graph lengths must refer to the same registered support points.
    for edge in result['connectors']:
        if edge['receiver_id'] is not None:
            a, b = (packet['columns'][edge[k]]['xy_m'] for k in ('source_id', 'receiver_id'))
            distance = math.dist(a, b)
            if not distance > 0 or not math.isclose(float(edge['length_m']), distance, rel_tol=1e-12, abs_tol=0):
                raise ValueError('connector length differs from regional support geometry')
    receipt = {'schema': SCHEMA, 'packet_sha256': digest(packet), 'adapter_sha256': _SOURCE_SHA,
               'sampled_constraints': samples, 'source_status': packet['source_status'],
               'scope': 'POINT_SUPPORTED_PRESCRIBED_SNAPSHOT_INPUTS',
               'plate_kinematics_modelled': False, 'geology_calibrated': False,
               'production_authorised': False, 'canon_changed': False}
    # Actual unchanged consumer checks finite material support and route geometry.
    receipt['initial_routes'] = transport.routes(result['cells'], result['connectors'],
                                                seconds_per_year=result['seconds_per_year'])
    result['evidence'] = template['evidence']+'; regional-inputs-sha256='+digest(receipt)
    pipeline.validate(result)
    return result, receipt


def run(template, packet, **options):
    """Use the existing ground driver, including its cache/checkpoint controls."""
    recipe, receipt = prepare(template, packet)
    return {'regional_inputs': receipt, 'ground': pipeline.run(recipe, **options)}
