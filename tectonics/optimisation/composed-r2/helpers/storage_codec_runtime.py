"""WP10 bounded, byte-exact codecs and opt-in two-worker pipelines.

Policy is immutable and scientific identities remain in storage.py. Admission
bounds Python/NumPy working buffers; it is not measured RSS. A pinned static-arena
backend enables zstd and reusable dictionaries within the codec allowance.
Without it those optional candidates fall back to raw. Historical Blosc2 zstd
remains readable under its historical, separately identified allowance.

Only an enabled rule changes what a store writes. No policy, a disabled rule and
a class the policy does not list all take the store's own pre-WP10 encode, byte
for byte: uniform, packed palette, run length and, where the store is configured
for it, historical Blosc2 zstd. Blosc2 has no native workspace bound, so its
encode is admitted under the whole codec allowance, exactly as its decode is.
Policy keys are '<record_schema>/<column>': compact columns of different records
share names (node.kind is a hot partition column and a cold ledger column).

Booking. Codec work inside a caller reservation that already funds one whole
codec allowance (an ArrayStore put stage or read scope, an interval writer's
chunk encode or candidate decode) is booked on a codec ledger only, never on the
run budget a second time. A put stage and an interval candidate use the store's
own ledger (shared with the stage's preparation workers); every read scope has a
ledger of its own, because each read scope reserves its own codec allowance and
must not wait on a concurrent put's reservations. Work outside such a
reservation is booked on the store's ledger and on the run budget.

Known limits, kept (no limit is raised):
- The legacy encode needs 65536 + 48 n bytes for an n-byte chunk (the palette
  scan). With the default codec_workspace_bytes (8,388,608 B) that admits
  n <= 173,397 B. A larger chunk with no policy, a disabled rule or an unlisted
  class is written raw, where the pre-WP10 encode wrote uniform, palette, run
  length or Blosc2. Every production writer uses 65,536-byte chunks;
  storage_profile('compact') (262,144 B) is the only profile above the bound.
- Compression(use_dict=True) is not encoded with Blosc2: its per-frame
  dictionary build peaks at 9-12 MB, above the codec allowance. It is written
  as live WP10 wrote it (uniform, palette or run length, else raw) and the
  fallback is counted. No production writer sets use_dict.
"""
from __future__ import annotations

from collections import deque
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import re
import struct
import threading
import traceback
from types import SimpleNamespace

import numpy as np

from codec_tradeoff import TRADEOFF_FIELDS, time_gate_passes


POLICY_SCHEMA = 'atlas.codec-policy.v1'
_SHA = re.compile('[0-9a-f]{64}\\Z')
_STATE_LOCK = threading.Lock()
_LOCAL = threading.local()
_NATIVE_GAP = 'Blosc2 exposes no supported native codec workspace upper-bound API'
_DICTIONARY_GAP = 'Blosc2 exposes no reusable external trained-dictionary API'
# Measured 9.1-11.8 MB peak working-set growth for one Blosc2 use_dict encode of a
# 64-173 KiB chunk: above the whole codec allowance, so it is never admitted.
_USE_DICT_GAP = ('Blosc2 per-frame dictionary encode exceeds codec_workspace_bytes; '
                 'written without Blosc2, as live WP10 wrote it')
_DELTA_ZSTD_LABEL = re.compile(r'delta-zstd-v1:(none|byte|bit):([0-9])\Z')
_DELTA_ZSTD_HEADER = struct.Struct('<4sBBQ')
_DELTA_ZSTD_MAX_BYTES = 65536
# '<record_schema>/<column>': the schema has no '/' or whitespace; the column is
# the rest. Plain ArrayStore snapshot arrays use the store schema (see below).
_POLICY_KEY = re.compile(r'[^/\x00-\x20\x7f]+/[^\x00-\x1f\x7f]+\Z')


@dataclass(frozen=True, slots=True)
class CodecRule:
    codec: str = 'raw'
    enabled: bool = False
    level: int = 1
    shuffle: str = 'byte'
    evidence: tuple = ()
    dictionary_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class CodecPolicy:
    default: CodecRule
    arrays: tuple
    parallel_workers: int = 1
    prefetch: bool = False

    def for_array(self, name):
        if name == '__wp10_dictionary__':
            return CodecRule()
        return next((rule for key, rule in self.arrays if key == name), self.default)


def _finite(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(name + ' must be a finite nonnegative number')
    return value


def _rule(value, *, experimental=False):
    if isinstance(value, CodecRule):
        value = dict(codec=value.codec, enabled=value.enabled, level=value.level,
                     shuffle=value.shuffle, evidence=dict(value.evidence) or None,
                     dictionary_sha256=value.dictionary_sha256)
    if type(value) is not dict or set(value) - {'codec', 'enabled', 'level', 'shuffle', 'evidence', 'dictionary_sha256'}:
        raise ValueError('invalid codec rule fields')
    codec, enabled = value.get('codec', 'raw'), value.get('enabled', False)
    level, shuffle = value.get('level', 1), value.get('shuffle', 'byte')
    if codec not in ('raw', 'palette', 'delta-v1', 'delta-zstd-v1', 'zstd', 'trained-zstd-v1'):
        raise ValueError('unsupported codec policy')
    if type(enabled) is not bool or type(level) is not int or not 0 <= level <= 9:
        raise ValueError('invalid enabled/level policy')
    if shuffle not in ('none', 'byte', 'bit'):
        raise ValueError('unsupported shuffle')
    dictionary = value.get('dictionary_sha256')
    if dictionary is not None and (codec != 'trained-zstd-v1' or type(dictionary) is not str
                                   or not _SHA.fullmatch(dictionary)):
        raise ValueError('invalid trained dictionary policy identity')
    if enabled and codec == 'trained-zstd-v1' and dictionary is None and not experimental:
        raise ValueError('enabled trained policy requires explicit dictionary identity')
    evidence = value.get('evidence')
    if enabled and not experimental:
        required = {'report_sha256', 'scope', 'compression_ratio', 'added_decode_fraction',
                    'cold_saving_bytes', 'baseline_total_seconds', 'candidate_total_seconds'}
        if type(evidence) is not dict or set(evidence) not in (required, required | TRADEOFF_FIELDS):
            raise ValueError('enabled codec requires complete real-class adoption evidence')
        if type(evidence['report_sha256']) is not str or not _SHA.fullmatch(evidence['report_sha256']):
            raise ValueError('invalid adoption evidence SHA-256')
        if evidence['scope'] != 'real':
            raise ValueError('synthetic experiments cannot enable production codecs')
        ratio = _finite(evidence['compression_ratio'], 'compression ratio')
        fraction = _finite(evidence['added_decode_fraction'], 'decode fraction')
        saving = evidence['cold_saving_bytes']
        if (ratio > .8 or fraction > .05 or type(saving) is not int or saving < 42949673
                or not time_gate_passes(codec, level, shuffle, evidence)):
            raise ValueError('codec fails the per-class adoption gates')
    elif evidence is not None and type(evidence) is not dict:
        raise ValueError('evidence must be a mapping or null')
    # Retain only scalar, immutable evidence; irrelevant nested data is refused.
    if evidence and any(type(v) not in (str, int, float, bool) for v in evidence.values()):
        raise ValueError('adoption evidence must contain scalar values')
    return CodecRule(codec, enabled, level, shuffle, tuple(sorted((evidence or {}).items())), dictionary)


def normalise_policy(value):
    if isinstance(value, CodecPolicy):
        value = dict(schema=POLICY_SCHEMA, default=value.default,
                     arrays=dict(value.arrays), parallel_workers=value.parallel_workers,
                     prefetch=value.prefetch)
    if type(value) is not dict or set(value) != {'schema', 'default', 'arrays', 'parallel_workers', 'prefetch'}:
        raise ValueError('invalid codec policy fields')
    if value['schema'] != POLICY_SCHEMA or type(value['arrays']) is not dict:
        raise ValueError('invalid codec policy schema/arrays')
    workers, prefetch = value['parallel_workers'], value['prefetch']
    if type(workers) is not int or workers not in (1, 2) or type(prefetch) is not bool:
        raise ValueError('codec workers must be 1 or 2; prefetch must be bool')
    if len(value['arrays']) > 4096:
        raise ValueError('codec policy exceeds array-class limit')
    arrays = []
    for name, rule in sorted(value['arrays'].items()):
        if type(name) is not str or not name or len(name) > 256:
            raise ValueError('invalid codec array name')
        if not _POLICY_KEY.fullmatch(name):
            # Refused, not mapped: a bare column name would select hot and cold
            # columns of different records alike, and choosing one is a guess.
            raise ValueError('codec policy array keys must be <record_schema>/<column>; '
                             'a bare column name is ambiguous across record schemas')
        arrays.append((name, _rule(rule)))
    return CodecPolicy(_rule(value['default']), tuple(arrays), workers, prefetch)


def read_policy(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate codec policy key')
            result[key] = value
        return result
    with open(path, 'rb') as source:
        raw = source.read(262145)
    if len(raw) > 262144:
        raise ValueError('codec policy exceeds 256 KiB')
    return normalise_policy(json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite policy'))))


def capability_status(backend=None):
    return {'new_zstd': {'available': backend is not None, 'reason': None if backend else _NATIVE_GAP},
            'trained_dictionary': {'available': backend is not None, 'reason': None if backend else _DICTIONARY_GAP},
            'legacy_zstd_decode': {'available': True, 'native_workspace_bound': None}}


def validate_backend(backend):
    """Only the hash-bound static-arena implementation is production configurable."""
    from storage_zstd_backend import ZstdBackend
    if type(backend) is not ZstdBackend:
        raise ValueError('pinned WP10 native backend required')
    return backend


def _error(store, message):
    cls = getattr(type(store), '_codec_store_error', ValueError)
    return cls(message)


def _types(store, dt, count):
    dt = np.dtype(dt)
    if (dt.kind not in 'biuf' or dt.itemsize not in (1, 2, 4, 8) or dt.fields
            or dt.str != dt.newbyteorder('<').str or type(count) is not int or count <= 0
            or count * dt.itemsize > store.limits.chunk_bytes):
        raise _error(store, 'invalid bounded codec dtype/count')
    return dt


def workspace_bound(raw_nbytes, dt, rule, *, backend=None):
    rule = _rule(rule, experimental=True)
    if type(raw_nbytes) is not int or raw_nbytes <= 0:
        raise ValueError('positive raw byte count required')
    dt = np.dtype(dt)
    if rule.enabled and rule.codec == 'delta-zstd-v1':
        if (backend is None or dt.kind not in 'iu' or raw_nbytes <= dt.itemsize
                or raw_nbytes > _DELTA_ZSTD_MAX_BYTES):
            return 4096
        native_rule = CodecRule('zstd', True, rule.level, rule.shuffle)
        bound = backend.encode_workspace_bound(raw_nbytes-dt.itemsize,
                                                np.dtype(f'<u{dt.itemsize}'), native_rule)
        if type(bound) is not int or bound <= 0:
            raise ValueError('backend must supply a positive exact workspace bound')
        # Native bound includes its delta input, frame output/copy, arena and
        # stack. Original bytes, difference ndarray and wrapped frame can all
        # coexist; their arrays and bounded Python bookkeeping are additional.
        return bound + 3 * raw_nbytes + 65536
    if rule.enabled and rule.codec in ('zstd', 'trained-zstd-v1') and backend is not None:
        bound = backend.encode_workspace_bound(raw_nbytes, np.dtype(dt), rule)
        if type(bound) is not int or bound <= 0:
            raise ValueError('backend must supply a positive exact workspace bound')
        return bound
    if not rule.enabled or rule.codec in ('raw', 'zstd', 'trained-zstd-v1'):
        return 4096
    return 65536 + raw_nbytes * (64 if rule.codec == 'delta-v1' else 48)


def _state(store):
    state = getattr(store, '_codec_state', None)
    if state is None:
        with _STATE_LOCK:
            state = getattr(store, '_codec_state', None)
            if state is None:
                from atlas_tectonics.resources import WorkBudget
                state = SimpleNamespace(budget=WorkBudget(store.limits.codec_workspace_bytes),
                                        lock=threading.Lock(), fallbacks={})
                store._codec_state = state
    return state


def _budget(store):
    from atlas_tectonics.resources import select_budget
    return select_budget(getattr(store, '_budget', getattr(getattr(store, 'scope', None), 'run_budget', None)))


def _cover(store):
    """This thread's innermost covering ledger for store, or None when uncovered."""
    for key, ledger in reversed(getattr(_LOCAL, 'covered', ())):
        if key == id(store):
            return ledger
    return None


@contextmanager
def _covered(store, ledger=True):
    """Codec work inside a caller reservation that funds one whole codec allowance.

    ledger=True books it on the store's own codec ledger; a WorkBudget books it
    on that ledger (a read scope's own); False or None leaves it uncovered, so it
    is booked on the store's ledger and on the run budget.
    """
    previous = getattr(_LOCAL, 'covered', ())
    if ledger is True:
        ledger = _state(store).budget
    if ledger is not None and ledger is not False:
        _LOCAL.covered = previous + ((id(store), ledger),)
    try:
        yield
    finally:
        _LOCAL.covered = previous


def caller_funded(store):
    """For a writer that has already reserved codec_workspace_bytes on its run budget.

    The interval writer reserves codec_workspace_bytes + 32 chunks around each
    put_chunk encode and verification decode, and codec_workspace_bytes + 8
    chunks around each candidate chunk decode. Inside, WP10 books on the
    candidate's codec ledger only (capped at codec_workspace_bytes), so the run
    budget carries exactly the writer's own reservation, as before WP10.
    """
    return _covered(store, True)


@contextmanager
def _reserve(store, size):
    from atlas_tectonics.resources import reserve_budgets
    state = _state(store)
    ledger = _cover(store)
    budgets = (ledger,) if ledger is not None else (state.budget, _budget(store))
    with reserve_budgets(size, *budgets, category='codec-work'):
        yield


def _fallback(store, reason):
    state = _state(store)
    with state.lock:
        state.fallbacks[reason] = state.fallbacks.get(reason, 0) + 1


def _palette_cannot_win(raw, dt):
    """Exact: True only when a packed palette can never be chosen for this chunk.

    A 1-byte integer chunk with more than 16 distinct values needs 8-bit
    indices, so its palette is 3 + n + count bytes: longer than the count raw
    bytes it would have to undercut strictly. np.bincount counts the distinct
    byte values exactly, and for u1/i1 those are the distinct values. Wider or
    boolean dtypes always take the full palette attempt.
    """
    if dt.itemsize != 1 or dt.kind not in 'iu':
        return False
    return int(np.count_nonzero(np.bincount(np.frombuffer(raw, dtype='u1'), minlength=256))) > 16


def _without_palette(original_encode, compression, proxy, raw, dt):
    """original_encode's exact result for a chunk whose palette provably loses.

    The legacy encode starts from raw and then tries palette, run length and
    Blosc2 in that order, each kept only when strictly smaller. Its palette
    switch also gates run length, so the run-length step is repeated here with
    the legacy arithmetic. With palette off, the legacy call returns uniform or
    the smaller of raw and Blosc2, and counts the encode once, as before.
    """
    config = proxy.compression
    plain = SimpleNamespace(_blosc=proxy._blosc, _stats=proxy._stats, compression=compression(
        codec=config.codec, level=config.level, shuffle=config.shuffle, palette=False,
        categorical=config.categorical, use_dict=config.use_dict))
    first = original_encode(plain, raw, dt)
    if first[0] == 'uniform':
        return first
    array = np.frombuffer(raw, dtype=dt)
    starts = np.concatenate(([0], np.flatnonzero(array[1:] != array[:-1]) + 1))
    size = 4 + starts.size * (4 + dt.itemsize)
    # Run length must undercut raw; Blosc2 then wins only when strictly smaller.
    if size >= len(raw) or (first[0] != 'raw' and len(first[1]) < size):
        return first
    runs = np.empty(starts.size, dtype=[('count', '<u4'), ('value', dt)])
    runs['count'] = np.diff(np.append(starts, array.size))
    runs['value'] = array[starts]
    return 'rle-v1', struct.pack('<I', starts.size) + runs.tobytes()


def _categorical(raw, dt):
    width = dt.itemsize
    words = np.frombuffer(raw, dtype=f'<u{width}')
    if np.all(words == words[0]):
        return 'uniform', raw[:width]
    best = ('raw', raw)
    if dt.kind not in 'biu':
        return best
    array = np.frombuffer(raw, dtype=dt)
    # Same choice without the sort when the palette provably cannot be smaller.
    values, inverse = (((), None) if _palette_cannot_win(raw, dt) else
                       np.unique(array, return_inverse=True))
    n = len(values)
    if 1 < n <= 256:
        bits = next(b for b in (1, 2, 4, 8) if n <= 1 << b)
        indices = inverse.astype('u1')
        packed = np.zeros((indices.size * bits + 7) // 8, dtype='u1')
        per_byte = 8 // bits
        for lane in range(per_byte):
            part = indices[lane::per_byte]
            packed[:part.size] |= part << (lane * bits)
        payload = struct.pack('<HB', n, bits) + values.tobytes() + packed.tobytes()
        if len(payload) < len(best[1]):
            best = ('palette-packed-v1', payload)
    starts = np.concatenate(([0], np.flatnonzero(array[1:] != array[:-1]) + 1))
    if 4 + starts.size * (4 + width) < len(best[1]):
        runs = np.empty(starts.size, dtype=[('count', '<u4'), ('value', dt)])
        runs['count'] = np.diff(np.append(starts, array.size))
        runs['value'] = array[starts]
        best = ('rle-v1', struct.pack('<I', starts.size) + runs.tobytes())
    return best


def _encode_delta_zstd(store, raw, dt, rule, backend):
    """Called under the combined delta/native workspace reservation."""
    words = differences = delta = payload = prefix = result = None
    try:
        unsigned = np.dtype(f'<u{dt.itemsize}')
        words = np.frombuffer(raw, dtype=unsigned)
        differences = np.empty(words.size-1, dtype=unsigned)
        np.subtract(words[1:], words[:-1], out=differences)
        delta = differences.tobytes()
        native_rule = CodecRule('zstd', True, rule.level, rule.shuffle)
        label, payload = backend.encode(delta, unsigned, native_rule)
        if label == 'raw':
            return 'raw', raw
        expected = f'wp10-zstd-v1:{rule.shuffle}:{rule.level}:-'
        if (label != expected or type(payload) is not bytes
                or len(payload) > len(delta)+4096):
            raise _error(store, 'delta-zstd backend returned an invalid plain-zstd frame')
        prefix = (_DELTA_ZSTD_HEADER.pack(b'ADZ1', dt.itemsize, 0, words.size)
                  + raw[:dt.itemsize])
        result = prefix + payload
        if len(result) >= len(raw):
            return 'raw', raw
        return f'delta-zstd-v1:{rule.shuffle}:{rule.level}', result
    except BaseException as failure:
        # A completed backend/NumPy frame can retain our temporary input via
        # its traceback. Clear locals while preserving the diagnostic frames.
        traceback.clear_frames(failure.__traceback__)
        raise
    finally:
        words = differences = delta = payload = prefix = result = None


def _decode_delta_zstd(store, codec, payload, dt, count, backend):
    match = _DELTA_ZSTD_LABEL.fullmatch(codec)
    cut = _DELTA_ZSTD_HEADER.size + dt.itemsize
    if (match is None or dt.kind not in 'iu' or count < 2
            or count*dt.itemsize > _DELTA_ZSTD_MAX_BYTES or len(payload) <= cut):
        raise _error(store, 'invalid delta-zstd type/header before allocation')
    magic, width, flags, declared = _DELTA_ZSTD_HEADER.unpack_from(payload)
    if magic != b'ADZ1' or width != dt.itemsize or flags != 0 or declared != count:
        raise _error(store, 'invalid delta-zstd dimensions before allocation')
    if backend is None:
        raise _error(store, 'delta-zstd requires its bounded native backend')
    shuffle, level = match.groups()
    native_label = f'wp10-zstd-v1:{shuffle}:{level}:-'
    unsigned = np.dtype(f'<u{dt.itemsize}')
    nbytes = count*dt.itemsize
    # The bytes-only native API needs a detached frame. Its allocation is
    # admitted before slicing. The wrapper header has already been validated.
    copy_need = 65536 + len(payload)
    frame = delta = output = result = None
    with _reserve(store, copy_need):
        try:
            frame = payload[cut:]
            native_need = backend.inspect_decode(native_label, frame, unsigned, count-1)
            if type(native_need) is not int or native_need <= 0:
                raise _error(store, 'invalid delta-zstd native workspace bound')
            need = native_need + 3*nbytes + 65536
            if copy_need + need > store.limits.codec_workspace_bytes:
                raise _error(store, 'delta-zstd decoder exceeds combined codec_workspace_bytes')
            with _reserve(store, need):
                try:
                    delta = backend.decode(native_label, frame, unsigned, count-1)
                    if type(delta) is not bytes or len(delta) != nbytes-dt.itemsize:
                        raise _error(store, 'delta-zstd decoded delta length/type mismatch')
                    output = np.empty(count, dtype=unsigned)
                    output[0] = np.frombuffer(payload, dtype=unsigned,
                                              offset=_DELTA_ZSTD_HEADER.size, count=1)[0]
                    np.cumsum(np.frombuffer(delta, dtype=unsigned), dtype=unsigned, out=output[1:])
                    np.add(output[1:], output[0], out=output[1:])
                    result = output.tobytes()
                    return result
                except BaseException as failure:
                    traceback.clear_frames(failure.__traceback__)
                    raise
                finally:
                    delta = output = result = None
        except BaseException as failure:
            traceback.clear_frames(failure.__traceback__)
            raise
        finally:
            frame = None


def encode_candidate(store, raw, dt, rule):
    """Explicit experiment API; does not enable a store policy or mutate compression."""
    if type(raw) is not bytes:
        raise _error(store, 'codec input must be immutable bytes')
    dt = _types(store, dt, len(raw) // np.dtype(dt).itemsize)
    if len(raw) % dt.itemsize:
        raise _error(store, 'unaligned codec input')
    rule = _rule(rule, experimental=True)
    backend = getattr(store, '_codec_backend', None)
    if rule.enabled and rule.codec == 'delta-zstd-v1':
        reason = None
        if dt.kind not in 'iu':
            reason = 'delta-zstd-v1 requires fixed-width integer dtype'
        elif len(raw) > _DELTA_ZSTD_MAX_BYTES:
            reason = 'delta-zstd-v1 supports chunks up to 64 KiB'
        elif backend is None:
            reason = 'delta-zstd-v1 requires its bounded native backend'
        if reason is not None or len(raw) <= dt.itemsize:
            if reason is not None:
                _fallback(store, reason)
            rule = CodecRule()
    native = rule.enabled and rule.codec in ('zstd', 'trained-zstd-v1') and backend is not None
    if rule.codec == 'trained-zstd-v1' and rule.enabled and backend is None:
        _fallback(store, _DICTIONARY_GAP)
    if rule.codec == 'zstd' and rule.enabled and backend is None:
        _fallback(store, _NATIVE_GAP)
    need = workspace_bound(len(raw), dt, rule, backend=backend)
    if need > store.limits.codec_workspace_bytes:
        _fallback(store, 'candidate exceeds codec_workspace_bytes')
        rule, need, native = CodecRule(), 4096, False
    with _reserve(store, need):
        if rule.enabled and rule.codec == 'delta-zstd-v1':
            return _encode_delta_zstd(store, raw, dt, rule, backend)
        if native:
            label, payload = backend.encode(raw, dt, rule)
            if (type(label) is not str or len(label) > 128 or type(payload) is not bytes
                    or len(payload) > store.limits.chunk_bytes + 4096
                    or (label != 'raw' and not backend.owns_label(label))):
                raise _error(store, 'bounded backend returned invalid label/payload')
            return label, payload
        if not rule.enabled or rule.codec in ('raw', 'zstd', 'trained-zstd-v1'):
            return 'raw', raw
        if rule.codec == 'palette':
            return _categorical(raw, dt)
        if dt.kind not in 'iu':
            _fallback(store, 'delta-v1 requires fixed-width integer dtype')
            return 'raw', raw
        # Modular differences operate on the bit pattern, including signed limits.
        words = np.frombuffer(raw, dtype=f'<u{dt.itemsize}')
        if len(words) < 2:
            return 'raw', raw
        delta = np.subtract(words[1:], words[:-1], dtype=words.dtype).tobytes()
        inner, data = _categorical(delta, words.dtype)
        kind = {'raw': 0, 'uniform': 1, 'palette-packed-v1': 2, 'rle-v1': 3}[inner]
        payload = struct.pack('<4sBBQ', b'ADL1', dt.itemsize, kind, len(words)) + raw[:dt.itemsize] + data
        return ('delta-v1', payload) if len(payload) < len(raw) else ('raw', raw)


def _old_decode(store):
    function = getattr(type(store), '_codec_original_decode', None)
    if function is None:
        from atlas_tectonics.storage import ArrayStore
        function = ArrayStore._codec_original_decode
    return function


def decode_candidate(store, codec, payload, dt, count):
    dt = _types(store, dt, count)
    if type(codec) is not str or len(codec) > 128 or type(payload) is not bytes:
        raise _error(store, 'invalid codec label/payload type')
    nbytes = count * dt.itemsize
    if len(payload) > store.limits.chunk_bytes + 4096:
        raise _error(store, 'oversized encoded payload')
    backend = getattr(store, '_codec_backend', None)
    if codec.startswith('delta-zstd-v1'):
        return _decode_delta_zstd(store, codec, payload, dt, count, backend)
    if backend is not None and backend.owns_label(codec):
        # inspect_decode may parse bounded headers and resolve a retained
        # dictionary, but must not allocate the native decoder/output yet.
        need = backend.inspect_decode(codec, payload, dt, count)
        if type(need) is not int or need <= 0 or need > store.limits.codec_workspace_bytes:
            raise _error(store, 'bounded backend decoder exceeds codec_workspace_bytes')
        with _reserve(store, need):
            raw = backend.decode(codec, payload, dt, count)
            if type(raw) is not bytes or len(raw) != nbytes:
                raise _error(store, 'bounded backend decoded length/type mismatch')
            return raw
    if codec.startswith('trained-zstd-v1') or codec.startswith('wp10-zstd'):
        raise _error(store, 'unsupported bounded codec: dictionary/native workspace capability unavailable')
    legacy_native = codec.split(':', 1)[0] in ('blosc2-zstd-none', 'blosc2-zstd-byte', 'blosc2-zstd-bit')
    if legacy_native:
        # Preserve historical readers, but reject declared expansion before native allocation.
        if len(payload) < 32:
            raise _error(store, 'truncated compressed chunk')
        import blosc2
        declared, compressed, block = blosc2.get_cbuffer_sizes(payload)
        if declared != nbytes or compressed != len(payload) or not 0 < block <= nbytes:
            raise _error(store, 'invalid compressed size before allocation')
    if codec == 'delta-v1':
        if dt.kind not in 'iu' or len(payload) < 14 + dt.itemsize:
            raise _error(store, 'invalid delta type/header')
        magic, width, kind, declared = struct.unpack_from('<4sBBQ', payload)
        if magic != b'ADL1' or width != dt.itemsize or declared != count or count < 2 or kind not in range(4):
            raise _error(store, 'invalid delta dimensions before allocation')
    need = (store.limits.codec_workspace_bytes if legacy_native else
            4096 if codec == 'raw' else 65536 + 16 * nbytes)
    if need > store.limits.codec_workspace_bytes:
        raise _error(store, 'decoder exceeds codec_workspace_bytes before allocation')
    with _reserve(store, need):
        if codec != 'delta-v1':
            return _old_decode(store)(store, codec, payload, dt, count)
        unsigned = np.dtype(f'<u{dt.itemsize}')
        base = np.frombuffer(payload, dtype=unsigned, offset=14, count=1)[0]
        inner = ('raw', 'uniform', 'palette-packed-v1', 'rle-v1')[kind]
        data = payload[14+dt.itemsize:]
        delta = _old_decode(store)(store, inner, data, unsigned, count-1)
        output = np.empty(count, dtype=unsigned)
        output[0] = base
        np.cumsum(np.frombuffer(delta, dtype=unsigned), dtype=unsigned, out=output[1:])
        np.add(output[1:], base, out=output[1:])
        return output.tobytes()


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError('codec work cancelled')


@contextmanager
def _ordered_map(store, function, items, *, workers, retained_per_task, cancel=None):
    """At most two submitted tasks. Cancel and join before releasing buffers."""
    if type(workers) is not int or workers not in (1, 2):
        raise _error(store, 'at most two codec workers are supported')
    # Workers share the owner's ledger (and its funding); uncovered owners stay
    # uncovered in their workers.
    owner_ledger = _cover(store)
    with _reserve(store, workers * retained_per_task):
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='atlas-codec')
        pending = deque()
        iterator = iter(items)
        def run(item):
            _check_cancel(cancel)
            with _covered(store, owner_ledger):
                result = function(item)
            _check_cancel(cancel)
            return result
        def ordered():
            try:
                while len(pending) < workers:
                    item = next(iterator)
                    pending.append(executor.submit(run, item))
            except StopIteration:
                pass
            while pending:
                _check_cancel(cancel)
                future = pending.popleft()
                result = future.result()
                _check_cancel(cancel)
                yield result
                del result, future
                try:
                    item = next(iterator)
                except StopIteration:
                    continue
                pending.append(executor.submit(run, item))
        try:
            yield ordered()
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
            pending.clear()


def _policy_name(store, name):
    """The policy key for a stream name.

    The segment writer already passes '<record_schema>/<column>'. A plain
    ArrayStore snapshot array has no record schema; it is qualified with the
    store's own schema (atlas.array-store.v1), set on the transformed class.
    """
    schema = getattr(type(store), '_codec_key_schema', None)
    if schema is None or name is None or name == '__wp10_dictionary__':
        return name
    return f'{schema}/{name}'


@contextmanager
def prepare_chunks(store, pieces, dt, name, cancel=None):
    policy = store._codec_policy
    rule = policy.for_array(_policy_name(store, name))
    def prepare(piece):
        raw = np.asarray(piece, dtype=dt, order='C').tobytes()
        encoded = store._encode(raw, dt, array_name=name)
        if decode_candidate(store, *encoded, dt, len(raw)//dt.itemsize) != raw:
            raise _error(store, 'parallel encoder changed typed bytes')
        return piece, (raw, *encoded)
    if not rule.enabled:
        # A disabled or unlisted class takes the legacy encode, whose historical
        # Blosc2 admission needs the whole codec allowance: prepare serially.
        def serial():
            for piece in pieces:
                _check_cancel(cancel)
                yield prepare(piece)
        yield serial()
        return
    retained = 4 * store.limits.chunk_bytes + 65536
    need = workspace_bound(store.limits.chunk_bytes, dt, rule,
                           backend=getattr(store, '_codec_backend', None))
    workers = min(policy.parallel_workers, max(1, store.limits.codec_workspace_bytes // (retained + need)))
    if rule.enabled and rule.codec == 'delta-zstd-v1':
        # Combined decode inspection has a second, frame-dependent reservation.
        # Until both phases have per-frame admission, keep its preparation to
        # one slot; this also avoids overlapping verification with another job.
        workers = 1
    with _ordered_map(store, prepare, pieces, workers=workers,
                      retained_per_task=retained, cancel=cancel) as results:
        yield results


@contextmanager
def decode_many(store, records, *, workers=1, cancel=None):
    """Ordered independent decode experiments; no SQLite access from workers."""
    if type(workers) is not int or workers not in (1, 2):
        raise _error(store, 'at most two codec workers are supported')
    retained = 3 * store.limits.chunk_bytes + 65536
    decode_need = 65536 + 16 * store.limits.chunk_bytes
    workers = min(workers, max(1, store.limits.codec_workspace_bytes // (retained + decode_need)))
    with _ordered_map(store, lambda record: decode_candidate(store, *record), records,
                      workers=workers, retained_per_task=retained, cancel=cancel) as results:
        yield results


def install_storage(namespace):
    """Bind only the transformed module's class, never a frozen/live module."""
    cls = namespace['ArrayStore']
    original_encode, original_decode = cls._encode, cls._decode
    original_workspace, original_iter = cls._workspace, cls._iter_chunks
    error, compression = namespace['StoreError'], namespace['Compression']
    cls._codec_store_error = error
    cls._codec_original_decode = staticmethod(original_decode)
    # Plain-store snapshot arrays are keyed '<store schema>/<array name>'.
    cls._codec_key_schema = namespace['_SCHEMA']

    def configure(self, policy):
        frozen = normalise_policy(policy)
        with self._preparing, self._lock:
            self._live()
            if hasattr(self, '_codec_policy'):
                raise error('codec policy is immutable after configuration')
            self._codec_policy = frozen

    def configure_backend(self, backend):
        backend = validate_backend(backend)
        with self._preparing, self._lock:
            self._live()
            if hasattr(self, '_codec_backend'):
                raise error('codec backend is immutable after configuration')
            self._codec_backend = backend

    @contextmanager
    def workspace(self, count, budget=None, *, category='store-work'):
        # Both reservations include one whole codec_workspace_bytes. A put stage
        # (one per store instance) books on the store's ledger, which its
        # preparation workers share. Each read scope books on a ledger of its
        # own: a read during a put, or a put's check of an existing chunk, is
        # funded by its own reservation and never waits on the stage's.
        if category == 'store-stage':
            ledger = True
        elif category == 'store-read':
            from atlas_tectonics.resources import WorkBudget
            ledger = WorkBudget(self.limits.codec_workspace_bytes)
        else:
            ledger = False
        with original_workspace(self, count, budget, category=category):
            with _covered(self, ledger):
                yield

    def encode(self, raw, dt, *, array_name=None):
        if array_name == '__wp10_dictionary__':
            return encode_candidate(self, raw, dt, CodecRule())
        policy = getattr(self, '_codec_policy', None)
        if policy is not None:
            if not isinstance(policy, CodecPolicy):
                raise error('normalised immutable codec policy required')
            rule = policy.for_array(_policy_name(self, array_name))
            if rule.enabled:
                with _state(self).lock:
                    self._stats['encodes'] = self._stats.get('encodes', 0) + 1
                return encode_candidate(self, raw, dt, rule)
        # No policy, a disabled rule or an unlisted class: the legacy encode,
        # uniform/palette/RLE and the store's own Blosc2 zstd, byte for byte,
        # without racing on shared compression.
        dt = _types(self, dt, len(raw)//np.dtype(dt).itemsize)
        config = self.compression
        need = 65536 + 48 * len(raw)
        if need > self.limits.codec_workspace_bytes:
            # Known limit, kept: n > 173,397 B at the default 8 MiB allowance.
            return encode_candidate(self, raw, dt, CodecRule())
        if config.codec == 'zstd' and config.use_dict:
            # Its real peak exceeds the allowance: written as live WP10 wrote it.
            _fallback(self, _USE_DICT_GAP)
            config = compression(codec='raw', palette=config.palette,
                                 categorical=config.categorical)
        blosc = None
        if config.codec == 'zstd':
            # No native workspace bound: the whole codec allowance, as for its
            # historical decode (and as the interval writer books around it).
            blosc, need = getattr(self, '_blosc', None), self.limits.codec_workspace_bytes
            if blosc is None:
                raise error('historical Blosc2 encode requires the store blosc2 module')
        proxy = SimpleNamespace(compression=config, _blosc=blosc, _stats=self._stats)
        with _reserve(self, need):
            if config.palette and config.categorical == 'auto' and _palette_cannot_win(raw, dt):
                return _without_palette(original_encode, compression, proxy, raw, dt)
            return original_encode(proxy, raw, dt)

    def parallel_enabled(self):
        policy = getattr(self, '_codec_policy', None)
        return policy is not None and policy.parallel_workers == 2

    def iterator(self, invocation, array_name, *, budget):
        policy = getattr(self, '_codec_policy', None)
        if policy is None or not policy.prefetch:
            yield from original_iter(self, invocation, array_name, budget=budget)
            return
        with self._read_scope(budget=budget):
            manifest = self._manifest(invocation)
            if manifest is None:
                raise KeyError(invocation)
            chunks = len(manifest['arrays'][array_name]['chunks'])
            # A historical/native decoder may require the whole codec allowance.
            # Optional prefetch must not turn a valid serial read into a refusal.
            labels_bounded_for_slots = {'raw', 'uniform', 'palette8',
                                       'palette-packed-v1', 'rle-v1', 'delta-v1'}
            def serial_label(key):
                row = self._db.execute('SELECT codec FROM chunks WHERE id=?', (key,)).fetchone()
                return row is None or row[0] not in labels_bounded_for_slots
            serial_only = any(serial_label(key) for key in manifest['arrays'][array_name]['chunks'])
            aggregate = (policy.parallel_workers * (2*self.limits.chunk_bytes+65536)
                         + 65536 + 16*self.limits.chunk_bytes)
            serial_only = serial_only or aggregate > self.limits.codec_workspace_bytes
        if serial_only:
            yield from original_iter(self, invocation, array_name, budget=budget)
            return
        # read_chunk owns the store lock for each complete SQLite read. Prefetch
        # overlaps downstream consumption; standalone decode_many does parallel
        # pure decoding without exposing SQLite to concurrent unlocked calls.
        with self._preparing:
            with _ordered_map(self, lambda i: self.read_chunk(invocation, array_name, i, budget=budget),
                              range(chunks), workers=policy.parallel_workers,
                              retained_per_task=2*self.limits.chunk_bytes+65536) as results:
                yield from results

    def statistics(self):
        state = _state(self)
        with state.lock:
            fallbacks = dict(state.fallbacks)
        return dict(workspace=state.budget.statistics(), fallbacks=fallbacks,
                    capabilities=capability_status(getattr(self, '_codec_backend', None)))

    cls.configure_codec_policy = configure
    cls.configure_codec_backend = configure_backend
    cls._workspace = workspace
    cls._encode = encode
    cls._decode = decode_candidate
    cls._codec_parallel_enabled = parallel_enabled
    cls._codec_prepare = prepare_chunks
    cls._iter_chunks = iterator
    cls.codec_statistics = statistics
    namespace.update(CodecRule=CodecRule, CodecPolicy=CodecPolicy, normalise_codec_policy=normalise_policy)
