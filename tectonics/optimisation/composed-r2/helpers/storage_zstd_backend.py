"""Private WP10 codec: pinned native zstd, fixed arenas, exact typed bytes.

The storage owner must reserve the returned aggregate bound BEFORE encode or
decode. Dictionary bytes are immutable, validated at construction, and retained
under a shared-budget reservation owned by this backend for its lifetime; no
resolver performs hidden reads and source owners may release their own lease.
Training transforms are called under the separate offline-training reservation.
The 512 KiB stack allowance must be checked against the pinned compiler build's
stack-usage output. It is a conservative allowance, not a measured RSS figure.
"""
from __future__ import annotations

import ctypes as C
import hashlib
from pathlib import Path
import re
from types import MappingProxyType

import numpy as np


MAX_CHUNK_BYTES = 65536
MAX_DICTIONARY_BYTES = 65536
MAX_DICTIONARIES = 64
MAX_RETAINED_DICTIONARY_BYTES = 4 * 1024 * 1024
DICTIONARY_BOOKKEEPING_BYTES = 4096
DICTIONARY_ENTRY_BYTES = 512
MAX_WORKSPACE_BYTES = 8 * 1024 * 1024
STACK_ALLOWANCE_BYTES = 512 * 1024
PYTHON_ALLOWANCE_BYTES = 4096
_FILTERS = {'none': 0, 'byte': 1, 'bit': 2}
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_LABEL = re.compile(r'wp10-zstd-v1:(none|byte|bit):([0-9]):(-|[0-9a-f]{64})\Z')


def _pointer(data):
    """Reference immutable bytes without copying their content."""
    return C.cast(C.c_char_p(data), C.c_void_p) if data is not None else None


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for part in iter(lambda: source.read(65536), b''):
            digest.update(part)
    return digest.hexdigest()


class _DictionaryOwner:
    """The retained mapping and its lease have exactly one lifetime.

    No explicit close can invalidate an active backend. A constructor exception
    can retain this owner through its traceback; its lease then stays charged
    until that traceback is discarded. No dictionary is copied before admission.
    """
    __slots__ = ('_data', 'mapping', '_lease')

    def __init__(self, source, budget):
        self._data = {}
        self.mapping = MappingProxyType(self._data)
        self._lease = None
        if type(source) not in (dict, MappingProxyType):
            raise ValueError('dictionaries must be an explicit bounded mapping')
        count = len(source)
        if count > MAX_DICTIONARIES:
            raise ValueError('at most 64 retained dictionaries are supported')
        if not count:
            return
        from atlas_tectonics.resources import WorkBudget
        if not isinstance(budget, WorkBudget):
            raise ValueError('nonempty dictionaries require a shared dictionary_budget')

        def size(key, value):
            if (type(key) is not str or not _SHA.fullmatch(key) or type(value) is not bytes
                    or not 256 <= len(value) <= MAX_DICTIONARY_BYTES
                    or hashlib.sha256(value).hexdigest() != key):
                raise ValueError('invalid retained dictionary bytes/hash')
            return len(value)

        total = 0
        for key, value in source.items():
            total += size(key, value)
            if total > MAX_RETAINED_DICTIONARY_BYTES:
                raise ValueError('retained dictionary payload exceeds 4 MiB')
        charge = total + DICTIONARY_BOOKKEEPING_BYTES + count * DICTIONARY_ENTRY_BYTES
        lease = budget.reserve(charge, category='codec-dictionary-retained')
        lease.__enter__()
        self._lease = lease
        actual = 0
        for key, value in source.items():
            actual += size(key, value)
            if len(self._data) >= count or actual > total:
                raise ValueError('dictionary source changed during retention')
            self._data[key] = value
        if len(self._data) != count or actual != total:
            raise ValueError('dictionary source changed during retention')

    def __del__(self):
        # Clear the owned references before returning their charge. A mapping
        # proxy accidentally retained by inspection then sees an empty mapping.
        data = getattr(self, '_data', None)
        if data is not None:
            data.clear()
        lease = getattr(self, '_lease', None)
        self._lease = None
        if lease is not None:
            lease.__exit__(None, None, None)


class ZstdBackend:
    """A backend instance bound to one pinned DLL and retained dictionary set.

    `dictionary_sha256` supplies the default for trained rules. A rule's explicit
    `dictionary_sha256` takes precedence. Class/field permission is checked by
    the storage owner before choosing the rule; a hash is content identity only.
    """

    def __setattr__(self, name, value):
        if getattr(self, '_frozen', False):
            raise AttributeError('codec backend configuration is immutable')
        object.__setattr__(self, name, value)

    def __delattr__(self, name):
        if getattr(self, '_frozen', False):
            raise AttributeError('codec backend configuration is immutable')
        object.__delattr__(self, name)

    @property
    def _dictionaries(self):
        return self._dictionary_owner.mapping

    def __init__(self, library_path, *, expected_sha256, dictionaries=None,
                 dictionary_sha256=None, dictionary_budget=None,
                 max_workspace_bytes=MAX_WORKSPACE_BYTES,
                 max_chunk_bytes=MAX_CHUNK_BYTES):
        if (type(expected_sha256) is not str or not _SHA.fullmatch(expected_sha256)):
            raise ValueError('a pinned native library SHA-256 is required')
        if (type(max_workspace_bytes) is not int or
                not 0 < max_workspace_bytes <= MAX_WORKSPACE_BYTES or
                type(max_chunk_bytes) is not int or not 0 < max_chunk_bytes <= MAX_CHUNK_BYTES):
            raise ValueError('invalid native codec bounds')
        library_path = Path(library_path).resolve(strict=True)
        if _file_sha256(library_path) != expected_sha256:
            raise ValueError('native codec library SHA-256 mismatch')
        self._dictionary_owner = _DictionaryOwner({} if dictionaries is None else dictionaries,
                                                  dictionary_budget)
        if dictionary_sha256 is not None and dictionary_sha256 not in self._dictionaries:
            raise ValueError('default trained dictionary is not retained')
        self.dictionary_sha256 = dictionary_sha256
        self.max_workspace_bytes = max_workspace_bytes
        self.max_chunk_bytes = max_chunk_bytes
        self.library_sha256 = expected_sha256
        self.library_path = library_path
        self._lib = C.CDLL(str(library_path))
        self._bind()
        if self._lib.wp10_zstd_abi_version() != 1 or self._lib.wp10_zstd_library_version() != 10507:
            raise ValueError('unsupported native codec ABI/zstd version')
        self._frozen = True

    def _bind(self):
        p, z, u, i = C.c_void_p, C.c_size_t, C.c_uint, C.c_int
        pz, pp = C.POINTER(z), C.POINTER(p)
        definitions = {
            'wp10_zstd_abi_version': ([], u),
            'wp10_zstd_library_version': ([], u),
            'wp10_zstd_status_name': ([i], C.c_char_p),
            'wp10_zstd_plan_encode': ([z, u, u, i, p, z, pz, pz], i),
            'wp10_zstd_inspect_decode': ([p, z, z, u, u, p, z, pz], i),
            'wp10_zstd_encode': ([p, z, p, z, u, u, i, p, z, pp, pz], i),
            'wp10_zstd_decode': ([p, z, p, z, z, u, u, p, z, pp, pz], i),
            'wp10_zstd_transform': ([p, p, z, u, u, u], i),
        }
        for name, (arguments, result) in definitions.items():
            function = getattr(self._lib, name)
            function.argtypes, function.restype = arguments, result

    def _check(self, status):
        if status:
            message = self._lib.wp10_zstd_status_name(status).decode('ascii', errors='replace')
            raise ValueError('bounded zstd: ' + message)

    def _dtype(self, dt, nbytes):
        dt = np.dtype(dt)
        if (type(nbytes) is not int or not 0 < nbytes <= self.max_chunk_bytes or
                dt.kind not in 'biuf' or dt.itemsize not in (1, 2, 4, 8) or dt.fields
                or dt.str != dt.newbyteorder('<').str or nbytes % dt.itemsize):
            raise ValueError('invalid bounded codec dtype/byte length')
        return dt

    def _dictionary(self, sha):
        if sha is None:
            return None
        if type(sha) is not str or not _SHA.fullmatch(sha):
            raise ValueError('invalid trained dictionary SHA-256')
        value = self._dictionaries.get(sha)
        if value is None:
            raise ValueError('required trained dictionary is not retained')
        # No file read or native allocation occurs. Immutable content is checked
        # again at the decode boundary rather than trusting a numeric zstd ID.
        if hashlib.sha256(value).hexdigest() != sha:
            raise ValueError('trained dictionary content SHA-256 mismatch')
        return value

    def _encode_rule(self, rule):
        codec = getattr(rule, 'codec', None)
        level, shuffle = getattr(rule, 'level', None), getattr(rule, 'shuffle', None)
        if (codec not in ('zstd', 'trained-zstd-v1') or type(level) is not int
                or not 0 <= level <= 9 or shuffle not in _FILTERS):
            raise ValueError('invalid native codec rule')
        sha = getattr(rule, 'dictionary_sha256', None)
        if codec == 'trained-zstd-v1':
            sha = sha or self.dictionary_sha256
            if sha is None:
                raise ValueError('trained codec requires a retained dictionary')
        elif sha is not None:
            raise ValueError('plain zstd rule cannot name a trained dictionary')
        return level, shuffle, sha, self._dictionary(sha)

    def _aggregate(self, arena_n, input_n, result_n, dictionary):
        # The arena includes native context/dictionary and shuffle/output buffers.
        # Input bytes, the retained source dictionary, and the Python result copy
        # can coexist with it. Alignment and small Python objects are also charged.
        value = (arena_n + 7 + input_n + result_n + len(dictionary or b'')
                 + STACK_ALLOWANCE_BYTES + PYTHON_ALLOWANCE_BYTES)
        if value > self.max_workspace_bytes:
            raise ValueError('native codec exceeds aggregate workspace allowance')
        return value

    def _encode_plan(self, nbytes, dt, rule):
        dt = self._dtype(dt, nbytes)
        level, shuffle, sha, dictionary = self._encode_rule(rule)
        arena_n, output_cap = C.c_size_t(), C.c_size_t()
        self._check(self._lib.wp10_zstd_plan_encode(nbytes, dt.itemsize,
            _FILTERS[shuffle], level, _pointer(dictionary), len(dictionary or b''),
            C.byref(arena_n), C.byref(output_cap)))
        bound = self._aggregate(arena_n.value, nbytes, output_cap.value, dictionary)
        return dt, level, shuffle, sha, dictionary, arena_n.value, output_cap.value, bound

    def encode_workspace_bound(self, nbytes, dt, rule):
        return self._encode_plan(nbytes, dt, rule)[-1]

    @staticmethod
    def _allocate_arena(nbytes):
        allocation = C.create_string_buffer(nbytes + 7)
        try:
            pointer = (C.addressof(allocation) + 7) & ~7
            return allocation, pointer
        finally:
            # On a failure, a retained traceback must not retain an uncharged
            # arena. On success the returned tuple owns the allocation.
            del allocation

    def encode(self, raw, dt, rule):
        if type(raw) is not bytes:
            raise ValueError('native codec input must be immutable bytes')
        dt, level, shuffle, sha, dictionary, arena_n, output_cap, _ = self._encode_plan(len(raw), dt, rule)
        allocation, arena = self._allocate_arena(arena_n)
        payload = None
        try:
            output, output_n = C.c_void_p(), C.c_size_t()
            self._check(self._lib.wp10_zstd_encode(arena, arena_n, _pointer(raw), len(raw),
                dt.itemsize, _FILTERS[shuffle], level, _pointer(dictionary), len(dictionary or b''),
                C.byref(output), C.byref(output_n)))
            if not output.value or not 0 < output_n.value <= output_cap:
                raise ValueError('native encoder returned invalid output')
            if output_n.value >= len(raw):
                return 'raw', raw
            payload = C.string_at(output, output_n.value)
            return f'wp10-zstd-v1:{shuffle}:{level}:{sha or "-"}', payload
        finally:
            # Native errors and later Python errors may escape with traceback
            # frames retained. Release arena/copy references before the caller
            # returns the corresponding workspace charge.
            del allocation, payload

    @staticmethod
    def owns_label(label):
        return type(label) is str and label.startswith('wp10-zstd-v1:')

    def _decode_plan(self, label, payload, dt, count):
        match = _LABEL.fullmatch(label) if type(label) is str else None
        if not match or type(payload) is not bytes or not 0 < len(payload) <= self.max_chunk_bytes + 4096:
            raise ValueError('invalid native codec label/payload')
        if type(count) is not int or count <= 0:
            raise ValueError('invalid native codec element count')
        dt = self._dtype(dt, count * np.dtype(dt).itemsize)
        shuffle, _level, sha = match.groups()
        dictionary = self._dictionary(None if sha == '-' else sha)
        arena_n = C.c_size_t()
        self._check(self._lib.wp10_zstd_inspect_decode(_pointer(payload), len(payload),
            count * dt.itemsize, dt.itemsize, _FILTERS[shuffle], _pointer(dictionary),
            len(dictionary or b''), C.byref(arena_n)))
        bound = self._aggregate(arena_n.value, len(payload), count * dt.itemsize, dictionary)
        return dt, shuffle, dictionary, arena_n.value, bound

    def inspect_decode(self, label, payload, dt, count):
        """Validate bounded header, single-frame extent and dictionary identity.

        This never allocates a decoder, its arena, or an output buffer. Native
        dictionary tables and frame checksum are validated during reserved decode.
        """
        return self._decode_plan(label, payload, dt, count)[-1]

    def decode(self, label, payload, dt, count):
        dt, shuffle, dictionary, arena_n, _ = self._decode_plan(label, payload, dt, count)
        allocation, arena = self._allocate_arena(arena_n)
        result = None
        try:
            output, output_n = C.c_void_p(), C.c_size_t()
            self._check(self._lib.wp10_zstd_decode(arena, arena_n, _pointer(payload), len(payload),
                count * dt.itemsize, dt.itemsize, _FILTERS[shuffle], _pointer(dictionary),
                len(dictionary or b''), C.byref(output), C.byref(output_n)))
            if not output.value or output_n.value != count * dt.itemsize:
                raise ValueError('native decoder returned invalid output')
            result = C.string_at(output, output_n.value)
            return result
        finally:
            del allocation, result

    def transform_for_training(self, raw, dt, shuffle):
        """Apply the production filter under the owner's training reservation."""
        if type(raw) is not bytes or shuffle not in _FILTERS:
            raise ValueError('invalid training transform')
        dt = self._dtype(dt, len(raw))
        if shuffle == 'none':
            return raw
        self._aggregate(len(raw), len(raw), len(raw), None)
        allocation, arena = self._allocate_arena(len(raw))
        result = None
        try:
            self._check(self._lib.wp10_zstd_transform(_pointer(raw), arena, len(raw),
                dt.itemsize, _FILTERS[shuffle], 0))
            result = C.string_at(arena, len(raw))
            return result
        finally:
            del allocation, result
