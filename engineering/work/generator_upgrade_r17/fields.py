"""Bounded source-bound point samples; no physical assignment or conversion.

Exact duplicate source records share one read within this call only. R15 still
checks the bytes actually decoded and performs the declared bilinear sampling;
the source, grid, registration, units and status are returned without promotion.
"""
from copy import deepcopy
import json

from work.generator_upgrade_r15 import regional


SCHEMA = 'diadem.source-bound-field-samples.r17'


def sample_fields(records, supports, target_frame_id, source_status):
    """Sample 1..64 explicit fields at 1..32 supplied ``xy_m`` supports.

Support metadata other than ``xy_m`` is retained, not interpreted. The caller
owns area/base geometry, material rules, frame adoption and unit interpretation.
The decoded distinct-record collection retains R15's 512 MiB limit. No source
record or sampled result is cached across calls.
"""
    if type(records) is not dict or not 1 <= len(records) <= 64:
        raise ValueError('between 1 and 64 explicit field records required')
    if type(supports) is not dict or not 1 <= len(supports) <= 32:
        raise ValueError('between 1 and 32 explicit supports required')
    regional.label(target_frame_id)
    if type(source_status) is not str or source_status not in regional.STATUSES:
        raise ValueError('known explicit field collection source status required')
    regional.contract.plain(records)
    regional.contract.plain(supports)
    sources, points = deepcopy(records), deepcopy(supports)
    for identity, support in points.items():
        regional.label(identity)
        if type(support) is not dict or type(support.get('xy_m')) is not list or len(support['xy_m']) != 2:
            raise ValueError('explicit support xy_m pair required')
        for value in support['xy_m']:
            regional.finite(value)
    for identity, record in sources.items():
        regional.label(identity)
        regional.contract.exact(record, ('path', 'sha256', 'array_key', 'grid', 'registration',
            'unit', 'role', 'reference', 'evidence', 'source_status'), 'regional field')
        regional.contract.exact(record['registration'], ('source_frame_id', 'target_frame_id',
            'target_to_source_affine', 'evidence', 'source_status'), 'regional registration')
        regional.label(record['unit'])
        regional.label(record['role'])
        if record['registration']['target_frame_id'] != target_frame_id:
            raise ValueError('field registration target differs from supplied target frame')
        if record['source_status'] != source_status or record['registration']['source_status'] != source_status:
            raise ValueError('field/registration source status differs; no promotion')
    arrays, total_bytes = {}, 0
    samples = {identity: {} for identity in points}
    for identity, record in sources.items():
        # Key the complete supplied record, not its unauthenticated checksum.
        key = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if key not in arrays:
            array = regional.read_field(record)
            total_bytes += array.nbytes
            if total_bytes > regional.MAX_TOTAL_ARRAY_BYTES:
                raise ValueError('regional field collection exceeds byte budget')
            arrays[key] = array
        for support_id, support in points.items():
            samples[support_id][identity] = regional.sample(
                arrays[key], record['grid'], record['registration'], support['xy_m'])
    return {'schema': SCHEMA, 'target_frame_id': target_frame_id,
            'source_status': source_status, 'samples': samples,
            'sources': sources, 'supports': points,
            'scope': 'POINT_SAMPLES_NO_MATERIAL_ASSIGNMENT_OR_UNIT_CONVERSION'}
