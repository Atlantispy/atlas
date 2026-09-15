"""Read-only delivery adapter; source assertions are not calibrated parameters."""
from . import provenance
from copy import deepcopy


def species(bundle):
    pins = bundle.identity['external_reference_sources']
    expected = provenance.external_sources()
    if pins != expected:
        raise ValueError('owner/reference binding changed')
    manifest = bundle.storage.decoded(provenance.checked(
        provenance.SPECIES_MANIFEST, provenance.SPECIES_MANIFEST_SHA256))
    documents = {}
    for row in manifest['files']:
        if row['relative_path'].endswith('.json'):
            documents[row['relative_path']] = bundle.storage.decoded(
                provenance.checked(row['path'], pins[row['path']]))
    return {'manifest_sha256': provenance.SPECIES_MANIFEST_SHA256,
        'entry_sha256': manifest['entry_point']['sha256'],
        'source_bindings': {row['relative_path']: {'path': row['path'], 'sha256': row['sha256']}
                            for row in manifest['files']},
        'documents': documents,
        'scope': 'Owner factual sidecars and scoped decisions; no implicit numerical compilation or canon promotion.'}


def geography(bundle):
    pins = bundle.identity['external_reference_sources']
    path = provenance.GEO_CONTRACT
    if pins.get(str(path)) != provenance.GEO_CONTRACT_SHA256:
        raise ValueError('exact GEO decision not bound')
    contract = bundle.storage.decoded(provenance.checked(path, pins[str(path)]))
    sources = {str(path): pins[str(path)]}
    for row in contract['artifacts']:
        actual = provenance.plain_path(row['path'])
        if pins.get(str(actual)) != row['sha256']:
            raise ValueError('GEO slice binding differs')
        provenance.checked(actual, row['sha256']); sources[str(actual)] = row['sha256']
    delta = bundle.storage.decoded(provenance.checked(provenance.GEO_DELTAS, provenance.GEO_DELTAS_SHA256))
    sources[str(provenance.GEO_DELTAS)] = provenance.GEO_DELTAS_SHA256
    for row in delta['artifacts']+delta['source_returns']:
        actual = provenance.plain_path(row['path'])
        if pins.get(str(actual)) != row['sha256']:
            raise ValueError('GEO resolving delta not bound')
        provenance.checked(actual, row['sha256']); sources[str(actual)] = row['sha256']
        if 'evidence_path' in row:
            actual = provenance.plain_path(row['evidence_path'])
            if pins.get(str(actual)) != row['evidence_sha256']:
                raise ValueError('GEO supporting evidence not bound')
            provenance.checked(actual, row['evidence_sha256']); sources[str(actual)] = row['evidence_sha256']
    effective = deepcopy(contract['unresolved'])
    for row in effective:
        if row['field'] == 'compatible_political_parent_and_policy':
            row['status'] = 'INCOMPLETE'
    return {'contract': contract, 'owner_deltas': delta, 'source_bindings': sources,
        'effective_unresolved': effective, 'requested_owner_returns_complete': True,
        'effective_interpretation': {
            'physical': {'selected_branch': 'PHYS-R11-RETAINED-COMPOSITE-G0',
                'working_xy': 'x east/y south km, NW corner, cell centres, explicit metre conversion',
                'working_z': 'unshifted metres positive up; D31_STILLKLINGE_G0_RETAINED_Z',
                'accepted_cross_frame_join': None, 'water_family_vertical_offsets': None,
                'original_reference_columns_automatically_rebound': False},
            'political': {'owner_return': 'COMPLETE_INTERPRETATION_WITH_INPUT_GAPS',
                'legacy_use': 'SOURCE_QUALIFIED_JOINS_REGRESSION_CONDITIONAL_ASSESSMENT_ONLY',
                'new_world_legacy_source_policy': 'REJECTED_CONTROL_DO_NOT_SEED',
                'inherited_political_fields_also_excluded': ['Stage3', 'Stage4', 'Stage5B'],
                'formation_order': 'OWNER_NEUTRAL_PHYSICAL_DISTRICTS_THEN_FROZEN_WHOLE_DISTRICT_ASSIGNMENT',
                'accepted_new_world_political_producer': None},
            'note': 'Only resolved pending owner interpretations superseded; original contract and unresolved physical evidence retained.'},
        'scope': 'Actual available-input and field-level blocker decision; not accepted world geometry or production authorisation.'}
