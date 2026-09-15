"""Native R11 product contract for a separately scoped political result.

Loads only the pinned standalone snapshot validator, not the sealed R11 science
bundle. Exporting a compatible product does not install it as actual-world input.
"""
from copy import deepcopy
from . import _snapshot_contract as snapshot, owner, provenance as p


def product(result, *, expected_context):
    p.verify(result['execution'])
    science = result['scientific']
    if p.sha(science) != result['scientific_sha256']:
        raise ValueError('political scientific readback digest differs')
    if science.get('context', expected_context) != expected_context:
        raise ValueError('political export world/date/frame mismatch')
    if science.get('owner_binding', owner.binding()) != owner.binding():
        raise ValueError('political owner input binding changed')
    support = science.get('physical_freeze_sha256', p.sha(science['formation']))
    ports = {'political_districts': {'quantity': 'whole_unit_jurisdiction_and_typed_site_access_links',
        'unit': 'explicit_ID_relations_and_metre_GeoJSON', 'support_id': support,
        'temporal_support': expected_context['snapshot_id']}}
    if science['status'] != 'MODELLED':
        return snapshot.emission(expected_context, ports, {'political_districts': None}, status='UNKNOWN',
            evidence='R20 complete diagnostic retained separately; no usable map emitted',
            unresolved=[science['status']], source_status='SYNTHETIC TEST')
    return snapshot.emission(expected_context, ports, {'political_districts': deepcopy(science)},
        evidence='Bounded R20 numerical political reference. Nested access UNKNOWN is retained, '
                 'not a grant of travel permission or actual Diadem map acceptance.',
        source_status=science['source_status'])


def save(folder, stem, value):
    """Content-addressed, exclusive create and exact readback; never overwrite."""
    folder = folder.resolve()
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
        raise ValueError('political output readback differs')
    return path
