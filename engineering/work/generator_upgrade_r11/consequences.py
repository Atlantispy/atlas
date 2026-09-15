"""Separate bounded scenario records; never a larger single JSON envelope.

The in-memory compatibility result is unchanged. Persistent manifests replace
only existing packed records with content references. Whole-result hashes stream
the original canonical JSON, retaining the historical checksum meaning without
allocating or accepting an oversized individual scientific unit.
"""
from copy import deepcopy
import hashlib
import json
from . import snapshot as s

SCHEMA = 'diadem.partitioned-consequences.r11'
RESULT_SCHEMA = 'diadem.seasonal-consequences-result.r11'
CHECKPOINT_SCHEMA = 'diadem.seasonal-consequences-checkpoint.r11'
MAX_SCENARIOS = 128
REF_FIELDS = ('scientific_sha256', 'record_sha256', 'byte_length')


def _stream_digest(value):
    result = hashlib.sha256()
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False)
    for chunk in encoder.iterencode(value):
        result.update(chunk.encode())
    return result.hexdigest()


def _record(record, codec):
    # Both the compressed record and decoded science retain their own bounds.
    raw = s.encoded(record)
    codec.unpack(record)
    return {'scientific_sha256': s.digest(record['sha256']),
        'record_sha256': hashlib.sha256(raw).hexdigest(),
        'byte_length': record['byte_length']}


def _state(state, codec, units):
    s.exact(state, ('completed_scenarios', 'parent_result_sha256', 'results'), 'scenario state')
    rows = state['results']; count = state['completed_scenarios']
    if type(rows) is not dict or type(count) is not int or not 0 <= count <= MAX_SCENARIOS or count != len(rows):
        raise ValueError('bounded exact scenario cursor and inventory required')
    if any(type(key) is not str for key in rows):
        raise ValueError('string scenario identities required')
    s.digest(state['parent_result_sha256'])
    refs = {}
    for key, record in sorted(rows.items()):
        s.text(key)
        refs[key] = _retain(record, codec, units)
    metadata = {'completed_scenarios': count, 'parent_result_sha256': state['parent_result_sha256'], 'results': refs}
    s.encoded(metadata)
    return metadata


def _retain(record, codec, units):
    ref = _record(record, codec); key = ref['scientific_sha256']
    if key in units and units[key] != record:
        raise ValueError('one exact packed record per scientific content address required')
    units[key] = deepcopy(record)
    return ref


def state_digest(state, codec):
    """Historical canonical state SHA, after per-unit and metadata validation."""
    _state(state, codec, {})
    return _stream_digest(state)


def split(value, codec):
    """Return a bounded manifest and separately bounded unchanged packed units."""
    if type(value) is not dict:
        raise ValueError('scenario result or checkpoint object required')
    schema = value.get('schema')
    if schema not in (RESULT_SCHEMA, CHECKPOINT_SCHEMA):
        raise ValueError('exact R11 consequence result/checkpoint schema required')
    kind = 'result' if schema == RESULT_SCHEMA else 'checkpoint'
    if kind == 'checkpoint':
        s.exact(value, ('schema', 'recipe_sha256', 'source_sha256', 'state_sha256', 'state'), 'R11 checkpoint')
    s.digest(value.get('source_sha256')); s.digest(value.get('recipe_sha256'))
    units = {}; state = _state(value.get('state'), codec, units)
    if kind == 'checkpoint' and value['state_sha256'] != _stream_digest(value['state']):
        raise ValueError('R11 checkpoint state digest differs')
    metadata = {key: item for key, item in value.items() if key not in ('state', 'biological_owner_inputs')}
    # Validate before copying; metadata may not hide a second giant payload.
    envelope = s.plain(metadata)
    s.encoded(envelope)
    envelope = deepcopy(envelope); envelope['state'] = state
    if 'biological_owner_inputs' in value:
        record = value['biological_owner_inputs']
        envelope['biological_owner_inputs'] = None if record is None else _retain(record, codec, units)
    manifest = {'schema': SCHEMA, 'kind': kind, 'envelope': envelope,
        'unit_sha256s': sorted(units), 'envelope_sha256': s.sha(envelope)}
    s.encoded(manifest)
    return manifest, units


def join(manifest, units, codec):
    """Validate complete reference inventory and reconstruct an independent copy."""
    s.exact(manifest, ('schema', 'kind', 'envelope', 'unit_sha256s', 'envelope_sha256'), 'partitioned consequence manifest')
    s.encoded(manifest)
    if manifest['schema'] != SCHEMA or manifest['kind'] not in ('result', 'checkpoint'):
        raise ValueError('exact partitioned consequence manifest schema/kind required')
    envelope = manifest['envelope']; ids = manifest['unit_sha256s']
    if type(ids) is not list or any(type(key) is not str for key in ids) or ids != sorted(set(ids)) or len(ids) > MAX_SCENARIOS+1:
        raise ValueError('bounded unique scientific unit inventory required')
    for key in ids:
        s.digest(key)
    if type(units) is not dict or set(units) != set(ids):
        raise ValueError('exact scientific unit inventory required; missing/orphan records refused')
    if s.sha(envelope) != manifest['envelope_sha256']:
        raise ValueError('consequence manifest envelope digest differs')
    if type(envelope) is not dict or envelope.get('schema') != (RESULT_SCHEMA if manifest['kind'] == 'result' else CHECKPOINT_SCHEMA):
        raise ValueError('consequence envelope schema/kind differs')
    used = set()
    def resolve(ref):
        s.exact(ref, REF_FIELDS, 'consequence unit reference')
        key = s.digest(ref['scientific_sha256'])
        s.digest(ref['record_sha256'])
        if type(ref['byte_length']) is not int or not 1 <= ref['byte_length'] <= s.MAX_BYTES:
            raise ValueError('bounded explicit scientific unit reference size required')
        if key not in units or _record(units[key], codec) != ref:
            raise ValueError('scientific unit reference, record digest or size differs')
        used.add(key)
        return deepcopy(units[key])
    value = deepcopy(envelope)
    state = value.get('state')
    s.exact(state, ('completed_scenarios', 'parent_result_sha256', 'results'), 'scenario state')
    if type(state['results']) is not dict:
        raise ValueError('exact scenario result inventory required')
    state['results'] = {key: resolve(ref) for key, ref in state['results'].items()}
    if value.get('biological_owner_inputs') is not None:
        value['biological_owner_inputs'] = resolve(value['biological_owner_inputs'])
    if used != set(ids):
        raise ValueError('unreferenced scientific unit refused')
    # Re-derive every reference, including cursor/count and checkpoint digest.
    expected, _ = split(value, codec)
    if expected != manifest:
        raise ValueError('partitioned consequence manifest differs from reconstructed value')
    return value


def clone(value, codec):
    """Validate/copy without treating an aggregate as one scientific unit."""
    manifest, units = split(value, codec)
    return join(manifest, units, codec)


def digest(value, codec):
    """Original whole-value canonical SHA; no monolithic byte allocation."""
    split(value, codec)
    return _stream_digest(value)
