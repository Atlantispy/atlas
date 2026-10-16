"""Raw trained-dictionary artefacts in ordinary immutable interval manifests.

These explicit helpers add no database/schema changes and install no backend.
Loading uses only existing manifest/chunk authentication and a paid owned copy.
"""
from hashlib import sha256
import math
import re

from atlas_tectonics import storage as native
from compact_contracts import ContractError, SnapshotLocator
from content_cache import ChargeSpec
from interval_catalog import canonical, check_cancel


ARRAY_NAME = '__wp10_dictionary__'
SCHEMA = 'atlas.codec-dictionary-artifact.v1'
REFERENCE_SCHEMA = 'atlas.codec-dictionary-reference.v1'
TRAINED_SCHEMA = 'atlas.trained-dictionary.v1'
MAX_DICTIONARY = 64 << 10
MAX_METADATA = 64 << 10
WORK_BYTES = 64 * MAX_METADATA + 2 * MAX_DICTIONARY + 65536
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_TRAINED_FIELDS = frozenset((
    'schema', 'sha256', 'array_class', 'dtype', 'shuffle', 'source_identity',
    'training_sample_sha256', 'transformed_sample_sha256', 'trainer_executable_sha256',
    'job_helper_sha256', 'training_sample_count', 'training_raw_bytes',
    'training_transformed_bytes', 'capacity_bytes', 'dictionary_bytes', 'limits',
    'metrics', 'status', 'production_enabled',
))


def _require(condition, reason):
    if not condition:
        raise ContractError(reason)


def _hash(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _provenance(metadata, *, nbytes):
    _require(type(metadata) is dict and len(metadata) == len(_TRAINED_FIELDS) and set(metadata) == _TRAINED_FIELDS,
             'unknown or incomplete trained dictionary provenance')
    _require(metadata['schema'] == TRAINED_SCHEMA and metadata['status'] == 'TRAINED_NOT_ADOPTED'
             and metadata['production_enabled'] is False, 'dictionary training status differs')
    _require(all(_hash(metadata[name]) for name in ('sha256', 'source_identity',
             'trainer_executable_sha256', 'job_helper_sha256')), 'dictionary provenance identity differs')
    _require(type(metadata['array_class']) is str and 0 < len(metadata['array_class']) <= 128
             and type(metadata['dtype']) is str and 0 < len(metadata['dtype']) <= 32
             and metadata['shuffle'] in ('none', 'byte', 'bit'), 'dictionary class/dtype/filter differs')
    dt = native._dtype(metadata['dtype'])
    _require(dt.str == metadata['dtype'], 'dictionary dtype must use canonical native spelling')
    count = metadata['training_sample_count']
    _require(_integer(count, 1, 256), 'training sample count exceeds bound')
    for name in ('training_sample_sha256', 'transformed_sample_sha256'):
        values = metadata[name]
        _require(type(values) is list and len(values) == count and all(_hash(v) for v in values),
                 'training sample identities differ')
    _require(all(_integer(metadata[name], count, min(1 << 20, count * 65536))
                 for name in ('training_raw_bytes', 'training_transformed_bytes')),
             'training corpus size exceeds bound')
    _require(_integer(metadata['capacity_bytes'], 256, MAX_DICTIONARY)
             and _integer(metadata['dictionary_bytes'], 8, metadata['capacity_bytes'])
             and metadata['dictionary_bytes'] == nbytes, 'trained dictionary byte bound differs')
    expected_limits = dict(process_memory_limit_bytes=128 << 20, job_memory_limit_bytes=128 << 20,
                           kill_on_close=True, breakaway=False, suspended_launch_owned=True)
    _require(metadata['limits'] == expected_limits, 'training job limits differ')
    metrics = metadata['metrics']
    _require(type(metrics) is dict and len(metrics) == 5 and set(metrics) == {'peak_job_memory_used_bytes',
        'peak_process_memory_used_bytes', 'elapsed_seconds', 'exit_code', 'dictionary_physical_bytes'},
        'training metrics are incomplete')
    _require(all(_integer(metrics[name], 0, 128 << 20) for name in
                 ('peak_job_memory_used_bytes', 'peak_process_memory_used_bytes'))
             and type(metrics['elapsed_seconds']) in (int, float)
             and math.isfinite(metrics['elapsed_seconds']) and 0 <= metrics['elapsed_seconds'] <= 32
             and type(metrics['exit_code']) is int and metrics['exit_code'] == 0
             and metrics['dictionary_physical_bytes'] == nbytes, 'training outcome evidence differs')
    _require(len(canonical(metadata)) <= MAX_METADATA - 2048, 'trained provenance exceeds manifest bound')


def _dictionary(data, provenance):
    _require(type(data) is bytes and 8 <= len(data) <= MAX_DICTIONARY
             and data[:4] == b'\x37\xa4\x30\xec' and int.from_bytes(data[4:8], 'little') != 0,
             'invalid bounded trained dictionary bytes')
    _provenance(provenance, nbytes=len(data))
    _require(sha256(data).hexdigest() == provenance['sha256'], 'dictionary content SHA-256 differs')


def _reference(reference):
    _require(type(reference) is dict and len(reference) == 4 and set(reference) ==
             {'schema', 'locator', 'metadata_sha256', 'dictionary_sha256'},
             'unknown dictionary reference fields')
    _require(reference['schema'] == REFERENCE_SCHEMA and _hash(reference['metadata_sha256'])
             and _hash(reference['dictionary_sha256']), 'invalid dictionary reference identity')
    return SnapshotLocator.from_wire(reference['locator'])


def publish_dictionary(candidate, trained_owner, *, cancel=None):
    """Publish one raw chunk plus bounded provenance into an unlisted interval.

    The storage runtime reserves ARRAY_NAME for raw encoding. No production
    codec is enabled here; reused ancestor chunks retain their original owner.
    """
    check_cancel(cancel)
    scope = candidate.scope
    with scope.reserve(ChargeSpec('codec-dictionary-publish', WORK_BYTES), cancel=cancel) as reservation:
        data = trained_owner.data
        _dictionary(data, trained_owner.metadata)
        # The snapshot owns a detached canonical provenance copy.
        provenance = native._parse(canonical(trained_owner.metadata))
        _dictionary(data, provenance)
        descriptor = canonical({'dtype': '|u1', 'count': len(data)})
        expected_chunk = native.ArrayStore._blob_id(None, descriptor, data)
        owner_interval, chunk = candidate.put_chunk(descriptor, data, cancel=cancel, array_name=ARRAY_NAME)
        _require(chunk == expected_chunk, 'raw dictionary typed content identity differs')
        metadata = dict(schema=SCHEMA, array_name=ARRAY_NAME, provenance=provenance,
                        chunk=dict(owner_interval=owner_interval, chunk_id=chunk,
                                   descriptor=dict(dtype='|u1', count=len(data))))
        raw_metadata = canonical(metadata)
        _require(len(raw_metadata) <= MAX_METADATA, 'dictionary metadata exceeds 64 KiB')
        metadata_sha = sha256(raw_metadata).hexdigest()
        snapshot = sha256(b'atlas.codec-dictionary-artifact.v1\0' + raw_metadata).hexdigest()
        locator = candidate.put_manifest(snapshot, metadata, cancel=cancel)
        check_cancel(cancel)
        # No returned bulk data depends on the temporary publication charge.
        _require(reservation is not None, 'dictionary publication reservation missing')
        return dict(schema=REFERENCE_SCHEMA, locator=locator.to_wire(),
                    metadata_sha256=metadata_sha, dictionary_sha256=provenance['sha256'])


class LoadedDictionary:
    """Independent paid bytes/provenance; native file handles need not stay open."""
    def __init__(self, owner):
        self._owner = owner

    @property
    def data(self):
        return self._owner.value[0]

    @property
    def metadata(self):
        return self._owner.value[1]

    @property
    def scope(self):
        return self._owner.scope

    def retain(self):
        return LoadedDictionary(self._owner.retain())

    def close(self):
        self._owner.close()

    def __enter__(self):
        _ = self._owner.value
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.close()


def load_dictionary(resolver, reference, *, expected_class, expected_dtype,
                    expected_shuffle, requester_interval=None, cancel=None):
    """Authenticate a dictionary before installing any optional codec backend.

    A candidate resolver omits requester_interval. A sealed IntervalStoreSet
    requires the caller's explicit requester interval, preserving closure rules.
    The result owns a byte copy so closing this load cannot invalidate a caller
    that explicitly retained a child owner.
    """
    check_cancel(cancel)
    locator = _reference(reference)
    scope = resolver.scope
    _require(locator.workflow_id == resolver.workflow_id, 'foreign dictionary workflow')
    _require(type(expected_class) is str and type(expected_dtype) is str
             and expected_shuffle in ('none', 'byte', 'bit'), 'explicit expected dictionary binding required')
    with scope.reserve(ChargeSpec('codec-dictionary-load', WORK_BYTES), cancel=cancel) as reservation:
        manifest_call = (lambda: resolver.resolve_manifest(locator, cancel=cancel)) if requester_interval is None else (
            lambda: resolver.resolve_manifest(requester_interval, locator, cancel=cancel))
        with manifest_call() as held_manifest:
            _require(len(held_manifest.value) <= MAX_METADATA+1024, 'dictionary manifest exceeds bounded parser input')
            manifest = native._parse(held_manifest.value)
            _require(manifest['invocation'] == locator.snapshot_key and manifest['arrays'] ==
                {'_carrier': {'dtype': '|u1', 'shape': [0], 'chunks': []}},
                'dictionary manifest shape differs')
            metadata = manifest['metadata']
            _require(type(metadata) is dict and set(metadata) == {'schema', 'array_name', 'provenance', 'chunk'}
                     and metadata['schema'] == SCHEMA and metadata['array_name'] == ARRAY_NAME,
                     'dictionary artifact schema differs')
            raw_metadata = canonical(metadata)
            _require(len(raw_metadata) <= MAX_METADATA and sha256(raw_metadata).hexdigest() == reference['metadata_sha256']
                     and sha256(b'atlas.codec-dictionary-artifact.v1\0' + raw_metadata).hexdigest() == locator.snapshot_key,
                     'dictionary metadata authentication differs')
            provenance, chunk = metadata['provenance'], metadata['chunk']
            _require(type(chunk) is dict and set(chunk) == {'owner_interval', 'chunk_id', 'descriptor'}
                     and _integer(chunk['owner_interval'], 0, locator.interval)
                     and _hash(chunk['chunk_id']) and type(chunk['descriptor']) is dict
                     and set(chunk['descriptor']) == {'dtype', 'count'}
                     and chunk['descriptor']['dtype'] == '|u1'
                     and _integer(chunk['descriptor']['count'], 8, MAX_DICTIONARY),
                     'dictionary chunk binding differs')
            _provenance(provenance, nbytes=chunk['descriptor']['count'])
            _require((provenance['array_class'], provenance['dtype'], provenance['shuffle']) ==
                     (expected_class, expected_dtype, expected_shuffle), 'dictionary class/dtype/shuffle mismatch')
            _require(provenance['sha256'] == reference['dictionary_sha256'], 'dictionary reference content differs')
            descriptor = canonical(chunk['descriptor'])
            args = (chunk['owner_interval'], chunk['chunk_id'], descriptor)
            chunk_call = (lambda: resolver.resolve_chunk(*args, cancel=cancel)) if requester_interval is None else (
                lambda: resolver.resolve_chunk(requester_interval, *args, cancel=cancel))
            with chunk_call() as held_chunk:
                _dictionary(held_chunk.value, provenance)
                _require(native.ArrayStore._blob_id(None, descriptor, held_chunk.value) == chunk['chunk_id'],
                         'dictionary typed identity differs')
                data = memoryview(held_chunk.value).tobytes()
            # provenance was freshly parsed under this reservation, independent
            # of held_manifest's raw bytes and underlying file owner.
        check_cancel(cancel)
        return LoadedDictionary(reservation.commit((data, provenance)))
