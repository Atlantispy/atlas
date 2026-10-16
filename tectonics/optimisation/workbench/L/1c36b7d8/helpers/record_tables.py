"""Generic exact JSON DAG columns. No domain admission, migration or fallback.

One traversal packs, interns and hashes the original canonical JSON. Scientific
JSON strings remain strings, including binary-encoded canonical hex spellings.
Optional parent seeding and locality permutation are deliberately disabled.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
import struct
from types import MappingProxyType

import numpy as np

from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError, LogicalIdentity, UINT64_MAX

SCHEMA = 'atlas.compact-record.v1'
PROFILE = 'atlas.legacy-json.v1'
MAX_ITEMS = 4_000_000
MAX_DEPTH = 128
MAX_INTEGER_BYTES = 1 << 20
MAX_TOKEN_BYTES = 256 << 20
MAX_BUILD_BYTES = 256 << 20
MAX_ROW_WORK_BYTES = 32 << 20
CHUNK = 65536
NULL, BOOL, INTEGER, FLOAT, TEXT, IDENT, HEX, ARRAY, OBJECT, RATIONAL = range(10)
_HEX = re.compile(r'-?0x(?:0|[1-9a-f][0-9a-f]*)\Z')


@dataclass(frozen=True, slots=True)
class StreamingRows:
    """Explicit JSON array input consumed once, one paid row at a time.

    The factory yields Owned values in the packer's scope. Successful rows are
    closed after packing; failed frames keep their row funding until released.
    Count is exact, and arbitrary iterables are never implicitly coerced.
    """
    count: int
    rows_factory: Callable[[], Iterator]

    def __post_init__(self):
        require(type(self.count) is int and 0 <= self.count <= MAX_ITEMS,
                'streaming row count exceeds bound')
        require(callable(self.rows_factory), 'streaming rows require a factory')


@dataclass(frozen=True, slots=True)
class _BuiltNode:
    """Opaque append result, usable only by its still-open originating builder."""
    token: object
    index: int
    identity: LogicalIdentity
    _owner: object


def require(ok, message):
    if not ok:
        raise ContractError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def narrow(maximum):
    require(type(maximum) is int and 0 <= maximum <= UINT64_MAX, 'reference overflow')
    return next(dtype for bound, dtype in ((255, 'u1'), (65535, '<u2'),
                ((1 << 32)-1, '<u4'), (UINT64_MAX, '<u8')) if maximum <= bound)


class Scratch:
    """Run-budget allocation retained by failure frames until their last release."""
    def __init__(self, budget, count):
        self._lease = budget.reserve(count, category='record-workspace')
        self._lease.__enter__()

    def __del__(self):
        lease = getattr(self, '_lease', None)
        if lease is not None:
            self._lease = None
            lease.__exit__(None, None, None)


class _Arena:
    def __init__(self, budget):
        self.budget, self.owners, self.free = budget, [], 0

    def hold(self, size):
        if size > self.free:
            count = max(CHUNK, size+1024)
            self.owners.append(Scratch(self.budget, count))
            self.free += count-1024
        self.free -= size


def string_parts(value, chunk=CHUNK):
    """ASCII JSON escaping without allocating the complete encoded token."""
    yield b'"'
    # At most 12 ASCII bytes per Unicode character, including surrogate pairs.
    for at in range(0, len(value), max(1, chunk//12)):
        yield json.dumps(value[at:at+max(1, chunk//12)], ensure_ascii=True)[1:-1].encode('ascii')
    yield b'"'


class _Builder:
    def __init__(self, scope, check):
        self.scope, self.check = scope, check
        # A mandatory child ledger, not another retained scope/revoker. It
        # bounds all simultaneously live builder tables, keys and row scratch.
        # Larger imports refuse; this component does not claim external spilling.
        self.work_budget = WorkBudget(MAX_BUILD_BYTES, parent=scope.run_budget)
        self.arena = _Arena(self.work_budget)
        self.arena.hold(8192)
        self.nodes, self.index = [], {}
        self.tokens, self.token_index = [], {}
        self.integers, self.integer_index = [], {}
        self.floats, self.float_index = [], {}
        self.ids, self.id_index = [], {}
        self.shapes, self.shape_index = [], {}
        self.pairs, self.pair_index = [], {}
        self.digest, self.length = sha256(), 0
        self._build_token = object()
        self._max_scalar_charge = 4096

    def scratch(self, size):
        require(size <= MAX_ROW_WORK_BYTES, 'record row workspace exceeds fixed 32 MiB import bound')
        return Scratch(self.work_budget, size)

    def emit(self, part):
        self.check()
        self.digest.update(part)
        self.length += len(part)
        require(self.length <= UINT64_MAX, 'logical byte count overflow')

    def token(self, value):
        found = self.token_index.get(value)
        if found is not None:
            return found
        require(len(value) <= MAX_TOKEN_BYTES, 'string exceeds token bound')
        # Keys remain input-owned during building; token bytes are newly owned.
        self.arena.hold(1024+32*len(value))
        raw = b''.join(string_parts(value))
        require(len(raw) <= MAX_TOKEN_BYTES, 'encoded string exceeds token bound')
        result = len(self.tokens)
        require(result < MAX_ITEMS, 'token pool exceeds count bound')
        self.token_index[value] = result
        self.tokens.append(raw)
        return result

    def integer(self, value):
        found = self.integer_index.get(value)
        if found is not None:
            return found
        count = (abs(value).bit_length()+7)//8
        require(count <= MAX_INTEGER_BYTES, 'individual binary magnitude exceeds 1 MiB')
        # Magnitudes are exact and sign is independent. Dyadics have no large body.
        dyadic = abs(value) > 0 and abs(value) & (abs(value)-1) == 0 and count > 8
        self.arena.hold(1024+(0 if dyadic else 4*count))
        row = (int(value < 0), int(dyadic), abs(value).bit_length()-1 if dyadic else 0,
               b'' if dyadic else abs(value).to_bytes(count, 'little'))
        result = len(self.integers)
        require(result < MAX_ITEMS, 'integer pool exceeds count bound')
        self.integer_index[value] = result
        self.integers.append(row)
        return result

    def add(self, value, depth=0):
        from record_views import RecordRef
        if type(value) is _BuiltNode:
            require(value.token is self._build_token and 0 <= value.index < len(self.nodes),
                    'foreign incremental record node')
            # One scalar is decoded at a time. Reserve its maximum once for
            # this complete stream, rather than opening a lease per leaf.
            held = self.scratch(self._max_scalar_charge)
            self._emit_node(value.index, depth)
            del held
            return value.index
        if isinstance(value, RecordRef):
            with value._view._read_batch():
                return self._add(value, depth)
        return self._add(value, depth)

    def _emit_node(self, index, depth):
        """Hash existing exact nodes without reconstructing a second DAG."""
        self.check()
        require(depth <= MAX_DEPTH, 'record nesting exceeds bound')
        kind, payload, shape, children, _, _ = self.nodes[index]
        if kind in (ARRAY, OBJECT, RATIONAL):
            object_kind = kind == OBJECT
            self.emit(b'{' if object_kind else b'[')
            if kind == RATIONAL:
                children = self.pairs[payload]
            for i, child in enumerate(children):
                if i:
                    self.emit(b',')
                if object_kind:
                    self.emit(self.tokens[self.shapes[shape][i]])
                    self.emit(b':')
                self._emit_node(child, depth+1)
            self.emit(b'}' if object_kind else b']')
            return
        if kind == NULL:
            self.emit(b'null')
        elif kind == BOOL:
            self.emit(b'true' if payload else b'false')
        elif kind == FLOAT:
            self.emit(canonical(struct.unpack('<d', self.floats[payload])[0]))
        elif kind == IDENT:
            self.emit(b'"'+self.ids[payload].hex().encode('ascii')+b'"')
        elif kind == TEXT:
            raw = self.tokens[payload]
            for at in range(0, len(raw), CHUNK):
                self.emit(raw[at:at+CHUNK])
        elif kind in (INTEGER, HEX):
            sign, dyadic, exponent, raw = self.integers[payload]
            number = (1 << exponent) if dyadic else int.from_bytes(raw, 'little')
            if sign:
                number = -number
            if kind == HEX:
                for part in string_parts(hex(number)):
                    self.emit(part)
            else:
                self.emit(canonical(number))
        else:
            raise ContractError('unknown incremental record node kind')

    def _add(self, value, depth=0):
        from record_views import RecordRef
        self.check()
        require(depth <= MAX_DEPTH, 'record nesting exceeds bound')
        is_ref = isinstance(value, RecordRef)
        if is_ref:
            require(value.scope is self.scope, 'foreign record scope')
            if value.kind == 'scalar':
                with value.scalar(max_owned_bytes=MAX_ROW_WORK_BYTES) as scalar:
                    return self.add(scalar.value, depth)
        children, shape, logical, scalar_charge = (), 0, 0, 0
        start = self.length
        if value is None:
            kind, payload = NULL, 0
            self.emit(b'null')
        elif type(value) is bool:
            kind, payload = BOOL, int(value)
            self.emit(b'true' if value else b'false')
        elif type(value) is int:
            hold = self.scratch(4096+16*((abs(value).bit_length()+7)//8))
            kind, payload = INTEGER, self.integer(value)
            # Preserve the process conversion limit. Refuse what legacy JSON refuses.
            try:
                raw = canonical(value)
            except ValueError as exc:
                raise ContractError('integer cannot use the unchanged legacy JSON profile') from exc
            self.emit(raw)
            scalar_charge = 4096+32*len(raw)
            del hold
        elif type(value) is float:
            require(math.isfinite(value), 'nonfinite JSON scalar')
            raw = struct.pack('<d', value)
            if raw not in self.float_index:
                self.arena.hold(256)
                self.float_index[raw] = len(self.floats)
                self.floats.append(raw)
            kind, payload = FLOAT, self.float_index[raw]
            self.emit(canonical(value))
        elif type(value) is str:
            if len(value) == 64 and all(c in '0123456789abcdef' for c in value):
                if value not in self.id_index:
                    self.arena.hold(256)
                    self.id_index[value] = len(self.ids)
                    self.ids.append(bytes.fromhex(value))
                kind, payload = IDENT, self.id_index[value]
                self.emit(b'"'+value.encode('ascii')+b'"')
            elif len(value) <= 2*MAX_INTEGER_BYTES+3 and _HEX.fullmatch(value) and value != '-0x0':
                hold = self.scratch(4096+8*len(value))
                number = int(value, 16)
                require(hex(number) == value, 'hex spelling parity failed')
                kind, payload = HEX, self.integer(number)
                for part in string_parts(value):
                    self.emit(part)
                del hold
            else:
                kind, payload = TEXT, self.token(value)
                for part in string_parts(value):
                    self.emit(part)
            scalar_charge = 4096+16*len(value)
        elif is_ref or type(value) in (list, dict, StreamingRows):
            count = value.size if is_ref else (value.count if type(value) is StreamingRows else len(value))
            require(count <= MAX_ITEMS, 'container count exceeds bound')
            hold = self.scratch(4096+128*count)
            object_kind = value.kind == 'object' if is_ref else type(value) is dict
            kind, payload = (OBJECT if object_kind else ARRAY), 0
            if object_kind:
                if is_ref:
                    keys_owner = value.keys(max_owned_bytes=MAX_ROW_WORK_BYTES)
                    keys = keys_owner.value
                else:
                    require(all(type(k) is str for k in value), 'object keys must be strings')
                    keys = sorted(value)
                key_refs = tuple(self.token(k) for k in keys)
                if key_refs not in self.shape_index:
                    self.arena.hold(512+64*len(keys))
                    self.shape_index[key_refs] = len(self.shapes)
                    self.shapes.append(key_refs)
                shape = self.shape_index[key_refs]
                self.emit(b'{')
                result = []
                for i, key in enumerate(keys):
                    if i:
                        self.emit(b',')
                    self.emit(self.tokens[key_refs[i]])
                    self.emit(b':')
                    if is_ref:
                        with value.field(key) as child:
                            result.append(self.add(child, depth+1))
                    else:
                        result.append(self.add(value[key], depth+1))
                children = tuple(result)
                self.emit(b'}')
                if is_ref:
                    del keys
                    keys_owner.close()
            else:
                self.emit(b'[')
                result = []
                if is_ref:
                    for i in range(count):
                        if i:
                            self.emit(b',')
                        with value.at(i) as child:
                            result.append(self.add(child, depth+1))
                elif type(value) is StreamingRows:
                    from content_cache import Owned
                    rows = iter(value.rows_factory())
                    for i, row in enumerate(rows):
                        require(isinstance(row, Owned) and row.scope is self.scope,
                                'streaming row must be owned in the same scope')
                        with row:
                            require(i < count, 'streaming row count exceeds declaration')
                            if i:
                                self.emit(b',')
                            result.append(self.add(row.value, depth+1))
                    require(len(result) == count, 'streaming row count below declaration')
                    closer = getattr(rows, 'close', None)
                    if closer is not None:
                        closer()
                elif type(value) is list:
                    for i, item in enumerate(value):
                        if i:
                            self.emit(b',')
                        result.append(self.add(item, depth+1))
                children = tuple(result)
                self.emit(b']')
                if len(children) == 2 and all(self.nodes[i][0] == HEX for i in children):
                    # Two string nodes retain lexical type. Denominators already
                    # share exact integer entries; no GCD, reduction or LCM.
                    if children not in self.pair_index:
                        self.arena.hold(256)
                        self.pair_index[children] = len(self.pairs)
                        self.pairs.append(children)
                    kind, payload = RATIONAL, self.pair_index[children]
                    children = ()
            del hold
        else:
            raise ContractError('unsupported JSON-domain type; no coercion')
        logical = self.length-start
        if type(value) is str:
            scalar_charge = 4096+16*logical
        self._max_scalar_charge = max(self._max_scalar_charge, scalar_charge)
        key = kind, payload, shape, children
        old = self.index.get(key)
        if old is not None:
            return old
        require(len(self.nodes) < MAX_ITEMS, 'node count exceeds bound')
        self.arena.hold(768+64*len(children))
        result = len(self.nodes)
        self.index[key] = result
        self.nodes.append((kind, payload, shape, children, logical, max(4096, scalar_charge)))
        return result

    def finish(self, root, record_schema):
        arrays = {}
        n, e = len(self.nodes), sum(len(r[3]) for r in self.nodes)
        require(e <= MAX_ITEMS*4, 'edge count exceeds bound')
        self.arena.hold(65536+160*n+32*e+sum(map(len, self.tokens)))
        def column(name, values, dtype):
            arrays[name] = np.asarray(values, dtype=dtype)
        refs = narrow(max(n, len(self.integers), len(self.tokens), len(self.floats),
                          len(self.ids), len(self.pairs), len(self.shapes)))
        column('node.kind', [r[0] for r in self.nodes], 'u1')
        column('node.payload', [r[1] for r in self.nodes], refs)
        column('node.shape', [r[2] for r in self.nodes], narrow(len(self.shapes)))
        column('node.length', [r[4] for r in self.nodes], '<u8')
        column('node.charge', [r[5] for r in self.nodes], '<u8')
        offsets, children = [0], []
        for row in self.nodes:
            children.extend(row[3]); offsets.append(len(children))
        column('node.offset', offsets, '<u8')
        column('edge.child', children, narrow(n))
        offsets, keys = [0], []
        for row in self.shapes:
            keys.extend(row); offsets.append(len(keys))
        column('shape.offset', offsets, '<u8')
        column('shape.key', keys, narrow(len(self.tokens)))
        for prefix, values in (('token', self.tokens), ('int', [v[3] for v in self.integers])):
            offsets, raw = [0], bytearray()
            for value in values:
                raw.extend(value); offsets.append(len(raw))
            column(prefix+'.offset', offsets, '<u8')
            arrays[prefix+'.bytes'] = np.frombuffer(raw, dtype='u1')
        column('int.sign', [v[0] for v in self.integers], 'u1')
        column('int.mode', [v[1] for v in self.integers], 'u1')
        column('int.exponent', [v[2] for v in self.integers], '<u8')
        arrays['float.value'] = np.frombuffer(b''.join(self.floats), dtype='<f8')
        arrays['id.bytes'] = np.frombuffer(b''.join(self.ids), dtype='u1')
        column('q.numerator', [v[0] for v in self.pairs], narrow(n))
        column('q.denominator', [v[1] for v in self.pairs], narrow(n))
        identity = LogicalIdentity(record_schema, self.digest.hexdigest(), self.length)
        metadata = dict(schema=SCHEMA, profile=PROFILE, features=[], root=root,
                        identity=identity.to_wire(), arrays={})
        for name, array in arrays.items():
            raw = memoryview(array).cast('B')
            metadata['arrays'][name] = dict(dtype=array.dtype.str, shape=list(array.shape),
                                           sha256=sha256(raw).hexdigest())
        raw_metadata = canonical(metadata)
        require(len(raw_metadata) <= 65536, 'record root metadata exceeds bound')
        return raw_metadata, arrays


class RecordCodec:
    def pack_record(self, value, *, record_schema, scope, check,
                    id_pool=None, shape_pool=None, profile=PROFILE):
        from record_views import CompactRecord
        require(profile == PROFILE, 'unknown canonicalisation profile')
        require(id_pool is None and shape_pool is None,
                'parent pool seeding disabled pending measured benefit gate')
        LogicalIdentity(record_schema, '0'*64, 0)
        builder = _Builder(scope, check)
        root = builder.add(value)
        metadata, arrays = builder.finish(root, record_schema)
        check()
        # The trusted builder already verified logical parity in the pack pass.
        return CompactRecord._from_built(metadata, arrays, scope=scope, check=check)

    def iter_logical_json(self, value_or_ref, *, scope, check):
        from record_views import CompactRecord, RecordRef
        if isinstance(value_or_ref, (CompactRecord, RecordRef)):
            require(value_or_ref.scope is scope, 'foreign record scope')
            check()
            return value_or_ref.iter_json()
        record = self.pack_record(value_or_ref, record_schema='atlas.json-value.v1',
                                  scope=scope, check=check)
        stream = record.iter_json()
        # Stream retains the original backing; record is released by GC.
        return stream

    def identity_hash(self, value_or_ref, *, record_schema, scope, check):
        from record_views import CompactRecord, RecordRef
        if isinstance(value_or_ref, (CompactRecord, RecordRef)):
            require(value_or_ref.scope is scope, 'foreign record scope')
            check()
            got = value_or_ref.identity()
            return LogicalIdentity(record_schema, got.sha256, got.canonical_bytes)
        record = self.pack_record(value_or_ref, record_schema=record_schema, scope=scope, check=check)
        result = record.identity()
        record.close()
        return result


class RecordBuilder:
    """Bounded incremental producer using the existing exact DAG wire format.

    Append consumes one caller-owned value. No source value or compatibility
    JSON is retained. Finalisation may reference append results; it reuses their
    packed nodes and only streams their exact spelling into the root digest.
    """
    def __init__(self, *, scope, check=lambda: None):
        from content_cache import RetainedScope
        require(type(scope) is RetainedScope and not scope._closed, 'open retained scope required')
        require(callable(check), 'callable builder check required')
        self.scope, self.check = scope, check
        self._builder, self._busy = _Builder(scope, check), False

    def append(self, value, *, record_schema):
        require(self._builder is not None and not self._busy, 'incremental builder is closed or busy')
        LogicalIdentity(record_schema, '0'*64, 0)
        self._busy = True
        builder = self._builder
        try:
            builder.digest, builder.length = sha256(), 0
            node = builder.add(value)
            owner = Scratch(builder.work_budget, 1024+4*len(record_schema))
            result = _BuiltNode(builder._build_token, node,
                LogicalIdentity(record_schema, builder.digest.hexdigest(), builder.length), owner)
            self.check()
            return result
        except BaseException:
            # Do not reuse a partially built inventory; failed frames keep it paid.
            self._builder = None
            raise
        finally:
            self._busy = False

    def finish(self, value, *, record_schema):
        from record_views import CompactRecord
        require(self._builder is not None and not self._busy, 'incremental builder is closed or busy')
        LogicalIdentity(record_schema, '0'*64, 0)
        self._busy = True
        builder = self._builder
        try:
            builder.digest, builder.length = sha256(), 0
            root = builder.add(value)
            metadata, arrays = builder.finish(root, record_schema)
            self.check()
            return CompactRecord._from_built(metadata, arrays, scope=self.scope, check=self.check)
        finally:
            self._builder, self._busy = None, False

    def close(self):
        require(not self._busy, 'incremental builder is busy')
        self._builder = None


@dataclass(frozen=True, slots=True)
class ArrayInfo:
    name: str
    dtype: str
    shape: tuple
    logical_bytes: int


def freeze_arrays(arrays):
    # Immutable bytes, not a reversible numpy WRITEABLE flag.
    return MappingProxyType({name: np.frombuffer(array.tobytes(), dtype=array.dtype)
                             .reshape(array.shape) for name, array in arrays.items()})
