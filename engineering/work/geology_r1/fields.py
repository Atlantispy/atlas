"""Scoped immutable decoded fields with fresh authentication on every use."""
from copy import deepcopy
import json

from work.generator_upgrade_r15 import regional
from . import io

SCHEMA = 'diadem.source-bound-field-samples.r17'
MAX_TOTAL_ARRAY_BYTES = regional.MAX_TOTAL_ARRAY_BYTES


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Prepared:
    """Complete records are keys; no unverified shared global or mtime cache."""
    __slots__ = ('__records', '__arrays', '__record_keys', '__target', '__status', '__closed', '__nbytes')

    def __init__(self, records, target_frame_id, source_status, *, max_total_bytes=MAX_TOTAL_ARRAY_BYTES):
        if type(records) is not dict or not 1 <= len(records) <= 64:
            raise ValueError('between 1 and 64 explicit field records required')
        regional.label(target_frame_id)
        if type(source_status) is not str or source_status not in regional.STATUSES:
            raise ValueError('known explicit field collection source status required')
        if type(max_total_bytes) is not int or not 0 <= max_total_bytes <= MAX_TOTAL_ARRAY_BYTES:
            raise ValueError('bounded aggregate array allowance required')
        regional.contract.plain(records)
        sources = deepcopy(records)
        arrays, keys, total = {}, {}, 0
        for identity, record in sources.items():
            regional.label(identity)
            regional.contract.exact(record, ('path', 'sha256', 'array_key', 'grid', 'registration',
                'unit', 'role', 'reference', 'evidence', 'source_status'), 'regional field')
            regional.contract.exact(record['registration'], ('source_frame_id', 'target_frame_id',
                'target_to_source_affine', 'evidence', 'source_status'), 'regional registration')
            regional.label(record['unit']); regional.label(record['role'])
            if record['registration']['target_frame_id'] != target_frame_id:
                raise ValueError('field registration target differs from supplied target frame')
            if record['source_status'] != source_status or record['registration']['source_status'] != source_status:
                raise ValueError('field/registration source status differs; no promotion')
            key = _encoded(record)
            if key not in arrays:
                array = io.read_field(record, max_array_bytes=min(io.MAX_ARRAY_BYTES, max_total_bytes-total))
                total += array.nbytes
                arrays[key] = io.immutable_array(array)
            keys[identity] = key
        self.__records = json.dumps(sources, allow_nan=False)
        self.__record_keys = tuple(keys.items())
        self.__arrays = tuple(arrays.items())
        self.__target, self.__status = target_frame_id, source_status
        self.__closed, self.__nbytes = False, total

    @property
    def nbytes(self):
        self._open()
        return self.__nbytes

    def _open(self):
        if self.__closed:
            raise ValueError('prepared field collection is closed')

    def verify_sources(self):
        self._open()
        seen = set()
        for record in json.loads(self.__records).values():
            source = record['path'], record['sha256']
            if source not in seen:
                io.verify_bound(*source)
                seen.add(source)

    def _sample_authenticated(self, supports):
        """Private use only inside a caller's complete before/after source guard."""
        self._open()
        if type(supports) is not dict or not 1 <= len(supports) <= 32:
            raise ValueError('between 1 and 32 explicit supports required')
        regional.contract.plain(supports)
        points, sources = deepcopy(supports), json.loads(self.__records)
        for identity, support in points.items():
            regional.label(identity)
            if type(support) is not dict or type(support.get('xy_m')) is not list or len(support['xy_m']) != 2:
                raise ValueError('explicit support xy_m pair required')
            for value in support['xy_m']:
                regional.finite(value)
        arrays, keys = dict(self.__arrays), dict(self.__record_keys)
        samples = {identity: {} for identity in points}
        for identity, record in sources.items():
            for support_id, support in points.items():
                samples[support_id][identity] = regional.sample(
                    arrays[keys[identity]], record['grid'], record['registration'], support['xy_m'])
        return {'schema': SCHEMA, 'target_frame_id': self.__target,
            'source_status': self.__status, 'samples': samples, 'sources': sources,
            'supports': points, 'scope': 'POINT_SAMPLES_NO_MATERIAL_ASSIGNMENT_OR_UNIT_CONVERSION'}

    def sample(self, supports):
        self.verify_sources()
        result = self._sample_authenticated(supports)
        self.verify_sources()
        return result

    def close(self):
        self.__arrays = ()
        self.__closed = True

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *exc):
        self.close()


def sample_fields(records, supports, target_frame_id, source_status):
    with Prepared(records, target_frame_id, source_status) as prepared:
        return prepared.sample(supports)
