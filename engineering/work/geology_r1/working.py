"""Pinned unified actual-Diadem coverage, using finite bounded native calls."""
from copy import deepcopy
import io as streams
import json
from pathlib import Path
import zipfile

import numpy as np

from work.generator_upgrade_r16 import regional
from work.generator_upgrade_r17 import working as previous, region
from . import fields, io, geology, model, programme, provenance as p

INPUT = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-5/02_Working_Files/Physical_Inputs_R18/DIADEM_COVERAGE_INPUTS_R1.json')
INPUT_SHA = '71190b940979aa5acb2e1bbd3cc74ce7d71f94154b492e6b979e543a430c8e12'
CONTRACT_SHA = 'b4a695624b2251b6728f5ada63e7dad7a690600d1b5ad8d2ad922b7149088b2c'


def _read(path, sha, size=None):
    return io.read_bound(path, sha, size, limit=32*1024**2)


def inputs():
    spec = json.loads(_read(INPUT, INPUT_SHA))
    if (spec['schema'] != 'diadem.physical.coverage-input-contract.r18' or
            spec['owner_decision'] != 'READY FOR AUTHORISED INTEGRATION' or
            spec['source_status'] != 'WORKING NON-CANON' or
            spec['selection']['scale_only_control'] is not False or
            spec['selection']['role'] != 'CAUSAL' or spec['owner_contract']['sha256'] != CONTRACT_SHA):
        raise ValueError('bound owner-authorised causal R18 working scenario required')
    owner = spec['owner_contract']
    _read(owner['path'], owner['sha256'], owner['size_bytes'])
    root = Path(spec['source_root']).resolve()
    sources = {}
    for name, record in spec['sources'].items():
        path = (root/record['relative_path']).resolve()
        # The unit catalogue is explicitly one level above the causal branch.
        if not path.is_relative_to(root.parent):
            raise ValueError('source outside the exact declared stage4 package')
        sources[name] = json.loads(_read(path, record['sha256'], record['size_bytes'])) if name != 'validity_masks' else None
    entries = sources['manifest']['files']
    registry = sources['registry']['field_records']
    selected = []
    if len(set(spec['field_inputs'])) != len(spec['field_inputs']):
        raise ValueError('unique selected field identities required')
    for name in spec['field_inputs']:
        matches = [record for record in registry if record['field_id'] == name]
        if len(matches) != 1:
            raise ValueError('one declared registry source per required field')
        record = matches[0]
        path = (root/record['path']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('field path outside bound causal branch')
        manifest = [row for row in entries if row['path'] == record['path']]
        if len(manifest) != 1:
            raise ValueError('field lacks a unique bound native causal manifest record')
        sha = manifest[0]['sha256']
        units = record['units']
        expected = ('km_conceptual_prior' if name == 'basin_fill_thickness_prior_km' else
                    '0_to_1_relative_affinity' if name.startswith('affinity_') else None)
        if expected is not None and units != expected:
            raise ValueError('source field units differ from owner role')
        if expected is None and not units.startswith('0_to_1'):
            raise ValueError('dimensionless owner support/modifier required')
        selected.append({'field_id': name, 'root': 'causal', 'relative_path': record['path'],
                         'sha256': sha, 'size_bytes': manifest[0]['bytes'], 'units': units})
    if len(selected) != spec['source_resolution']['required_field_count']:
        raise ValueError('incomplete owner source field inventory')
    validity = spec['sources']['validity_masks']
    bound_mask = [row for row in entries if row['path'] == validity['relative_path']]
    if len(bound_mask) != 1 or (bound_mask[0]['sha256'], bound_mask[0]['bytes']) != (validity['sha256'], validity['size_bytes']):
        raise ValueError('validity differs from native causal manifest')
    spec['resolved_field_inputs'] = selected
    spec['unit_catalogue'] = {row['unit_id']: row for row in sources['units']['units']}
    prototypes = {row['material_id'] for row in spec['materials']}
    if len(prototypes) != 27 or prototypes | {'SV-01'} != set(spec['unit_catalogue']):
        raise ValueError('all 27 rock units plus distinct SV-01 role required')
    return spec


def materials(spec):
    return {row['material_id']: {'grain_density_kg_m3': str(row['grain_density_kg_m3']),
        'porosity': str(row['porosity']), 'k_per_year': str(row['k_per_year']),
        'phase': spec['material_defaults']['phase']} for row in spec['materials']}


def _reader_spec(spec):
    return {'frame': spec['frame'], 'selection': spec['selection'],
        'roots': {'causal': spec['source_root']}, 'validity': {
            **spec['sources']['validity_masks'], 'root': 'causal',
            'array_key': spec['source_resolution']['validity_array']}}


def packet(spec):
    context = {name: spec['context'][name] for name in regional.FRAME}
    bridge = {'frame': spec['frame'], 'context': context, 'id': spec['id'],
        'source_status': spec['source_status'], 'roots': {'causal': spec['source_root']},
        'owner_contract': spec['owner_contract'], 'field_inputs': spec['resolved_field_inputs'],
        'sources': {'manifest': {**spec['sources']['manifest'], 'root': 'causal'}}}
    result = previous.packet(bridge)
    # Reuse numerical metadata conversion, not the predecessor's northern label.
    for record in result['fields'].values():
        record['evidence'] = record['evidence'].replace('northern Diadem', 'unified Diadem')
        record['registration']['evidence'] = record['registration']['evidence'].replace('northern Diadem', 'unified Diadem')
    result['evidence'] = result['evidence'].replace('northern Diadem', 'unified Diadem')
    return result


def _build(spec, supports, alternative, mask, prepared_fields, plan, prepared_plan):
    if len(supports) > geology.batch_limit(plan):
        raise ValueError('support count exceeds conservative native event budget; use smaller batches')
    previous._check_supports(_reader_spec(spec), supports, mask)
    source_packet = packet(spec)
    sampled = prepared_fields._sample_authenticated(supports)
    mix = 'harmonic' if alternative == 'HARMONIC_COMPOSITE_K' else 'arithmetic'
    resolved, palette = geology.interpret(sampled['samples'], supports, prepared_plan, materials(spec), k_mixing=mix)
    if alternative != 'DEFAULT':
        source_packet['context']['snapshot_id'] += '/'+alternative
    result = model.build(source_packet, supports, sampled, resolved, palette, spec['erosion']['reference_runoff_m_year'])
    science = result['scientific']; details = science['regional_input']
    details.update({'owner_input': {'path': str(INPUT), 'sha256': INPUT_SHA},
        'owner_programme': plan, 'alternative': alternative,
        'prototype_properties': materials(spec), 'unit_catalogue': deepcopy(spec['unit_catalogue']),
        'retained_source_status': deepcopy(spec['retained_source_status']),
        'source_register': deepcopy(spec['sources']), 'validity': deepcopy(_reader_spec(spec)['validity']),
        'vertical_zero': spec['context']['vertical_zero'],
        'applicability': {'selected_region': deepcopy(spec['selection']),
            'requested_adjoining_diagnostic_collar_cells': 1, 'crop_is_physical_boundary': False,
            'unified_including_north': True, 'full_terrain_or_year_run': False}})
    result['execution']['scientific_sha256'] = p.sha(science)
    return result


def _mask(spec):
    row = _reader_spec(spec)['validity']
    raw = _read(previous._path(_reader_spec(spec), row), row['sha256'], row['size_bytes'])
    name = row['array_key']+'.npy'
    with zipfile.ZipFile(streams.BytesIO(raw)) as archive:
        if archive.namelist().count(name) != 1 or archive.getinfo(name).file_size > 2*1024**2:
            raise ValueError('unique bounded authoritative validity member required')
        member = streams.BytesIO(archive.read(name))
    version = np.lib.format.read_magic(member)
    if version not in ((1, 0), (2, 0)):
        raise ValueError('supported NPY validity header required')
    shape, _, dtype = (np.lib.format.read_array_header_1_0(member) if version == (1, 0)
                       else np.lib.format.read_array_header_2_0(member))
    if (list(shape) != spec['frame']['array_shape'] or dtype.kind not in 'bui'
            or dtype.itemsize > 8 or np.prod(shape, dtype=object)*8 > fields.MAX_TOTAL_ARRAY_BYTES):
        raise ValueError('authoritative mask shape/type differs or exceeds byte budget')
    member.seek(0)
    mask = np.load(member, allow_pickle=False)
    if not np.isin(mask, [0, 1]).all():
        raise ValueError('validity mask is not Boolean; no inferred validity')
    return io.immutable_array(mask.astype(np.float64))


def _bindings(spec):
    """Every owner, manifest, selected record and mask is bound, not mtime-keyed."""
    root = Path(spec['source_root']).resolve()
    rows = [(str(INPUT), INPUT_SHA, None, 32*1024**2)]
    owner = spec['owner_contract']
    rows.append((owner['path'], owner['sha256'], owner['size_bytes'], 32*1024**2))
    for record in spec['sources'].values():
        rows.append((str((root/record['relative_path']).resolve()), record['sha256'],
                     record['size_bytes'], 32*1024**2))
    for record in spec['resolved_field_inputs']:
        rows.append((str((root/record['relative_path']).resolve()), record['sha256'],
                     record['size_bytes'], io.MAX_SOURCE_BYTES))
    return tuple(dict.fromkeys(rows))


def _verify_bindings(bindings):
    for path, sha, size, limit in bindings:
        io.verify_bound(path, sha, size, limit=limit)


def validate_sources():
    """Authenticate owner and numeric source bytes without allocating arrays."""
    _verify_bindings(_bindings(inputs()))


class Prepared:
    """One worker/invocation's immutable inputs, not shared persistent state."""
    __slots__ = ('__spec', '__mask', '__fields', '__plans', '__bindings', '__closed')

    def __init__(self):
        spec = inputs()
        self.__spec = json.dumps(spec, allow_nan=False)
        self.__bindings = _bindings(spec)
        self.__mask = _mask(spec)
        source_packet = packet(spec)
        self.__fields = fields.Prepared(source_packet['fields'],
            source_packet['context']['spatial_frame_id'], spec['source_status'],
            max_total_bytes=fields.MAX_TOTAL_ARRAY_BYTES-self.__mask.nbytes)
        self.__plans, self.__closed = {}, False
        self.verify_sources()

    @property
    def nbytes(self):
        self._open()
        return self.__fields.nbytes+self.__mask.nbytes

    def _open(self):
        if self.__closed:
            raise ValueError('prepared geological inputs are closed')

    def verify_sources(self):
        self._open()
        if _bindings(json.loads(self.__spec)) != self.__bindings:
            raise ValueError('prepared geological source paths changed; no substitution')
        _verify_bindings(self.__bindings)

    def build(self, supports, alternative='DEFAULT'):
        self._open()
        self.verify_sources()
        spec = json.loads(self.__spec)
        # programme.build rejects anything outside the exact named alternatives.
        # JSON text prevents a returned metadata mutation reaching later calls.
        if alternative not in self.__plans:
            plan = programme.build(spec, alternative)
            self.__plans[alternative] = (json.dumps(plan, allow_nan=False), geology.prepare(plan))
        encoded_plan, prepared_plan = self.__plans[alternative]
        result = _build(spec, deepcopy(supports), alternative, self.__mask, self.__fields,
                        json.loads(encoded_plan), prepared_plan)
        self.verify_sources()
        return result

    def close(self):
        if self.__closed:
            return
        try:
            self.verify_sources()
        finally:
            self.__fields.close()
            self.__mask = None
            self.__plans.clear()
            self.__closed = True

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, kind, error, traceback):
        try:
            self.close()
        except BaseException as cleanup:
            if error is None:
                raise
            error.geology_input_cleanup_errors = [str(cleanup)]


def build(supports, alternative='DEFAULT'):
    with Prepared() as prepared:
        return prepared.build(supports, alternative)


def case_supports(spec):
    cases = spec['verification_cases']
    coordinates = {(row[1], row[2]) for row in cases['maxima']} | {(row[3], row[4]) for row in cases['transitions']}
    if len(coordinates) != cases['expected_distinct_native_points']:
        raise ValueError('owner case coordinate coverage differs')
    frame = spec['frame']; x0, y0 = frame['first_centre_m']; dx, dy = frame['step_m']
    return {f'r{r}_c{c}': {'xy_m': [x0+c*dx, y0+r*dy], 'area_m2': frame['native_area_m2']}
            for r, c in sorted(coordinates)}


def batches(spec, batch_size=None, alternative='DEFAULT'):
    limit = geology.batch_limit(programme.build(spec, alternative))
    size = limit if batch_size is None else batch_size
    if type(size) is not int or not 1 <= size <= limit:
        raise ValueError('batch size must respect the native event budget')
    return previous.batches(spec, size)


def iter_cases():
    spec = inputs()
    size = geology.batch_limit(programme.build(spec)); points = list(case_supports(spec).items())
    with Prepared() as prepared:
        for start in range(0, len(points), size):
            yield prepared.build(dict(points[start:start+size]))


def iter_region(batch_size=None):
    """Lazy full-public geological coverage; batches are not catchments.

No DEM, hydrology, terrain/year evolution or source acceptance is performed.
Decoded arrays and compiled plans are reused under fresh before/after guards.
"""
    spec = inputs()
    with Prepared() as prepared:
        for supports in batches(spec, batch_size):
            yield prepared.build(supports)
