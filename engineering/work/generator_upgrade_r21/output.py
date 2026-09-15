"""Separate common-snapshot product; never installs a synthetic world parent."""
from copy import deepcopy
from pathlib import Path
from . import _snapshot_contract as snapshot, owner, provenance as p


def product(result, *, expected_context):
    p.verify(result['execution'])
    science = result['scientific']
    if (p.sha(science) != result['scientific_sha256'] or science['context'] != expected_context
            or science['owner_binding'] != owner.binding()):
        raise ValueError('agriculture product/source/context readback differs')
    support = science['input_sha256']
    ports = {'agriculture': {'quantity': 'committed_cropland_timed_irrigation_crop_yield_local_food',
        'unit': 'explicit_m2_m3_kg_kcal_and_time_ledgers', 'support_id': support,
        'temporal_support': expected_context['snapshot_id']}}
    if science['status'] != 'MODELLED':
        return snapshot.emission(expected_context, ports, {'agriculture': None}, status='UNKNOWN',
            evidence='R21 bounded diagnostics retained; incomplete yield is not usable production',
            unresolved=[science['status']], source_status=science['source_status'])
    return snapshot.emission(expected_context, ports, {'agriculture': deepcopy(science)},
        evidence='R21 declared numerical agriculture, not actual farm placement or freight acceptance',
        source_status=science['source_status'])


def save(folder, stem, value):
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    raw = p.encoded(value)
    path = folder/(stem+'-'+p.sha(value)[:16]+'.json')
    try:
        with path.open('xb') as stream:
            stream.write(raw)
    except FileExistsError:
        if p.checked(path) != raw:
            raise ValueError('existing output differs; preserved without overwrite')
    if p.checked(path) != raw:
        raise ValueError('agriculture output readback differs')
    return path
