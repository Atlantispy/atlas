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
from pathlib import Path
import re
from types import MappingProxyType
from typing import cast

import numpy as np


MAX_CHUNK_BYTES = 65536
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
        count = len(source)
        if not count:
            return

        def size(key, value):
            return len(value)

        total = 0
        for key, value in source.items():
            total += size(key, value)
        charge = total + DICTIONARY_BOOKKEEPING_BYTES + count * DICTIONARY_ENTRY_BYTES
        lease = budget.reserve(charge, category='codec-dictionary-retained')
        lease.__enter__()
        self._lease = lease
        actual = 0
        for key, value in source.items():
            actual += size(key, value)
            self._data[key] = value

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
        object.__setattr__(self, name, value)

    def __delattr__(self, name):
        object.__delattr__(self, name)

    @property
    def _dictionaries(self):
        return self._dictionary_owner.mapping

    def __init__(self, library_path, *, expected_sha256, dictionaries=None,
                 dictionary_sha256=None, dictionary_budget=None,
                 max_workspace_bytes=MAX_WORKSPACE_BYTES,
                 max_chunk_bytes=MAX_CHUNK_BYTES):
        library_path = Path(library_path).resolve(strict=True)
        self._dictionary_owner = _DictionaryOwner({} if dictionaries is None else dictionaries,
                                                  dictionary_budget)
        self.dictionary_sha256 = dictionary_sha256
        self.max_workspace_bytes = max_workspace_bytes
        self.max_chunk_bytes = max_chunk_bytes
        self.library_sha256 = expected_sha256
        self.library_path = library_path
        self._lib = C.CDLL(str(library_path))
        self._bind()
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
        return dt

    def _dictionary(self, sha):
        if sha is None:
            return None
        value = self._dictionaries.get(sha)
        return value

    def _encode_rule(self, rule):
        codec = getattr(rule, 'codec', None)
        level, shuffle = getattr(rule, 'level', None), cast(str, getattr(rule, 'shuffle', None))
        sha =getattr(rule, 'dictionary_sha256', None)
        if codec == 'trained-zstd-v1':
            sha = sha or self.dictionary_sha256
        elif sha is not None:
            raise ValueError('plain zstd rule cannot name a trained dictionary')
        return level, shuffle, sha, self._dictionary(sha)

    def _aggregate(self, arena_n, input_n, result_n, dictionary):
        # The arena includes native context/dictionary and shuffle/output buffers.
        # Input bytes, the retained source dictionary, and the Python result copy
        # can coexist with it. Alignment and small Python objects are also charged.
        value = (arena_n + 7 + input_n + result_n + len(dictionary or b'')
                 + STACK_ALLOWANCE_BYTES + PYTHON_ALLOWANCE_BYTES)
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
        dt, level, shuffle, sha, dictionary, arena_n, output_cap, _ = self._encode_plan(len(raw), dt, rule)
        allocation, arena = self._allocate_arena(arena_n)
        payload = None
        try:
            output, output_n = C.c_void_p(), C.c_size_t()
            self._check(self._lib.wp10_zstd_encode(arena, arena_n, _pointer(raw), len(raw),
                dt.itemsize, _FILTERS[shuffle], level, _pointer(dictionary), len(dictionary or b''),
                C.byref(output), C.byref(output_n)))
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
        dt = self._dtype(dt, count * np.dtype(dt).itemsize)
        shuffle, _level, sha = cast('re.Match[str]', match).groups()
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
            result = C.string_at(output, output_n.value)
            return result
        finally:
            del allocation, result

    def transform_for_training(self, raw, dt, shuffle):
        """Apply the production filter under the owner's training reservation."""
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
