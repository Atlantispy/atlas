"""Pinned actual-region owner inputs and the lazy geological producer entrypoint."""
from copy import deepcopy
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

import numpy as np

from . import northern, region, provenance as p

INPUT = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-5/02_Working_Files/Physical_Inputs_R17/DIADEM_REGIONAL_INPUTS_R1.json')
INPUT_SHA = '229af9d78dade312e107d0048abb2aacdaf59d9d2c506aaf4eee65dddd1f18ed'
CONTRACT_SHA = 'fe1ee0de609fd271d404fea68fb9923360828afd6579516d4165138cc1d6df56'


def _read(path, sha, size=None):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('absolute source path required')
    with path.open('rb') as stream:
        raw = stream.read(32*1024**2+1)
    if len(raw) > 32*1024**2 or (size is not None and len(raw) != size) or hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('R17 owner/source binding changed; no substitution or repin')
    return raw


def _path(spec, row):
    root = Path(spec['roots'][row['root']]).resolve()
    path = (root/row['relative_path']).resolve()
    if not path.is_relative_to(root):
        raise ValueError('source reference leaves declared owner root')
    return path


def inputs():
    spec = json.loads(_read(INPUT, INPUT_SHA))
    owner = spec['owner_contract']
    if (spec['schema'] != 'diadem.physical.regional-input-contract.r17' or
            spec['source_status'] != 'WORKING NON-CANON' or
            spec['selection']['scale_only_control'] is not False or owner['sha256'] != CONTRACT_SHA):
        raise ValueError('pinned causal northern owner scenario required')
    _read(owner['path'], owner['sha256'], owner['size_bytes'])
    for row in spec['sources'].values():
        _read(_path(spec, row), row['sha256'], row['size_bytes'])
    # Bind the branch-specific manifest and all selected array hashes as a unit.
    manifest = spec['sources']['manifest']
    records = json.loads(_read(_path(spec, manifest), manifest['sha256'], manifest['size_bytes']))['files']
    for row in [*spec['field_inputs'], spec['validity']]:
        matches = [entry for entry in records if entry['path'] == row['relative_path']]
        if len(matches) != 1 or matches[0]['sha256'] != row['sha256'] or matches[0]['bytes'] != row['size_bytes']:
            raise ValueError('selected numerical input differs from causal manifest')
    return spec


def packet(spec):
    """Translate metadata km to explicit metres, not an atlas/world registration."""
    frame = spec['frame']; context = deepcopy(spec['context'])
    evidence = spec['id']+' R1; northern Diadem owner working reconstruction'
    source_frame = context['spatial_frame_id']
    grid = {'frame_id': source_frame, 'unit': 'm', 'sample_location': 'cell_centres',
            'first_sample_m': frame['first_centre_m'], 'step_m': frame['step_m']}
    registration = {'source_frame_id': source_frame, 'target_frame_id': source_frame,
        'target_to_source_affine': [[1., 0., 0.], [0., 1., 0.]],
        'evidence': evidence+'; native km metadata expressed in metres; no historical warp or active DEM join',
        'source_status': spec['source_status']}
    fields = {}
    for row in spec['field_inputs']:
        fields[row['field_id']] = {'path': str(_path(spec, row)), 'sha256': row['sha256'],
            'array_key': None, 'grid': deepcopy(grid), 'registration': deepcopy(registration),
            'role': 'continuous_constraint_prior', 'unit': row['units'],
            'reference': {'world_id': 'Diadem', 'snapshot_id': 'C1R_A0_CAUSAL_RETAINED_PRIORS',
                          'vertical_reference': None},
            'evidence': evidence+'; retained independent, nonexclusive source field',
            'source_status': spec['source_status']}
    source = spec['sources']['manifest']
    return {'context': context, 'source_status': spec['source_status'], 'evidence': evidence,
        'owner_source': {key: spec['owner_contract'][key] for key in ('path', 'sha256')},
        'source_package': {'path': str(_path(spec, source)), 'sha256': source['sha256']}, 'fields': fields}


def _mask(spec):
    row = spec['validity']
    raw = _read(_path(spec, row), row['sha256'], row['size_bytes'])
    name = row['array_key']+'.npy'
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.namelist().count(name) != 1 or archive.getinfo(name).file_size > 2*1024**2:
            raise ValueError('unique bounded authoritative validity member required')
        member = io.BytesIO(archive.read(name))
    version = np.lib.format.read_magic(member)
    if version not in ((1, 0), (2, 0)):
        raise ValueError('supported NPY validity header required')
    shape, _, dtype = (np.lib.format.read_array_header_1_0(member) if version == (1, 0)
                       else np.lib.format.read_array_header_2_0(member))
    if list(shape) != spec['frame']['array_shape'] or dtype.kind not in 'bui' or dtype.itemsize > 8:
        raise ValueError('authoritative mask shape/type differs')
    member.seek(0)
    mask = np.load(member, allow_pickle=False)
    if not np.isin(mask, [0, 1]).all():
        raise ValueError('validity mask is not Boolean; no inferred validity')
    return mask.astype(np.float64)


def _check_supports(spec, supports, mask):
    selected = spec['selection']
    for support in supports.values():
        x, y = support['xy_m']
        col = (x-spec['frame']['first_centre_m'][0])/spec['frame']['step_m'][0]
        row = (y-spec['frame']['first_centre_m'][1])/spec['frame']['step_m'][1]
        # A requested one-cell adjoining collar uses the identical field rules.
        # This is a bounded diagnostic allowance, never a physical edge/wall.
        if not (selected['row_start']-1 <= row <= selected['row_stop'] and
                selected['column_start']-1 <= col <= selected['column_stop']):
            raise ValueError('support beyond selected region and adjoining one-cell collar; distinct regions require owner rules')
        if not (0 <= row <= mask.shape[0]-1 and 0 <= col <= mask.shape[1]-1):
            raise ValueError('support outside authoritative sampled extent; no extrapolation')
        # Check neighbours directly: averaging a tiny invalid weight could round
        # back to one. The mask never supplies relief or an exterior boundary.
        neighbours = [(r, c) for r in {math.floor(row), math.ceil(row)}
                      for c in {math.floor(col), math.ceil(col)}]
        if any(mask[r, c] != 1 for r, c in neighbours):
            raise ValueError('support intersects non-authoritative geology coverage')
        if support['area_m2'] != spec['frame']['native_area_m2']:
            raise ValueError('native regional prism area required; no finer-resolution claim')


def batches(spec, batch_size=32):
    frame, selected = spec['frame'], spec['selection']
    return region.support_batches({'first_sample_m': frame['first_centre_m'],
        'step_m': frame['step_m'], 'shape': frame['array_shape']},
        {'row_start': selected['row_start'], 'row_stop': selected['row_stop'],
         'col_start': selected['column_start'], 'col_stop': selected['column_stop']}, batch_size)


def probes(spec):
    return {row['case_id']: {'xy_m': row['xy_m'], 'area_m2': spec['frame']['native_area_m2']}
            for row in spec['real_source_probe_cases']}


def _build(spec, supports, alternative, mask):
    _check_supports(spec, supports, mask)
    result = northern.build(packet(spec), supports, alternative)
    science = result['scientific']
    science['regional_input']['owner_input'] = {'path': str(INPUT), 'sha256': INPUT_SHA}
    science['regional_input']['retained_source_status'] = deepcopy(spec['retained_source_status'])
    science['regional_input']['validity'] = deepcopy(spec['validity'])
    science['regional_input']['source_register'] = deepcopy(spec['sources'])
    science['regional_input']['applicability'] = {
        'selected_region': deepcopy(spec['selection']),
        'requested_adjoining_diagnostic_collar_cells': 1,
        'crop_is_physical_boundary': False}
    result['execution']['scientific_sha256'] = p.sha(science)
    return result


def build(supports=None, alternative=northern.DEFAULT):
    """Construct supplied regional supports; default is the four owner probes."""
    spec = inputs()
    return _build(spec, probes(spec) if supports is None else supports, alternative, _mask(spec))


def iter_region(batch_size=32):
    """Lazy whole-region geology producer; batches are NOT separate catchments.

No global hydrology/erosion is performed here. The caller consumes finite initial
geological states before assembling its connected terrain model and boundaries.
The native per-call material limits are preserved without limiting the region.
"""
    spec = inputs(); mask = _mask(spec)
    for supports in batches(spec, batch_size):
        yield _build(spec, supports, northern.DEFAULT, mask)
