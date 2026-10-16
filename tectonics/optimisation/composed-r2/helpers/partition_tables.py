"""Private lossless DifferentialPartition/support DAG, not scientific admission.

The native partition hash excludes its embedded support records. Both that hash
and the ordered, complete support hashes are checked independently here. Exact
rational-hex pairs, arbitrary integers, SHA IDs and strings have shared pools;
lists/objects use CSR child references. In particular, carried snapshot-rotated
constraints and ray histories are shared nodes, not repeated JSON blobs.

This is a partition-specific representation, not a replacement storage engine.
Publish storage_payload() through the existing ArrayStore transaction/CAS. Its
immutable numeric arrays can use existing chunk deduplication. The native typed
issuer and consumers still need explicit indexed adapters; a valid table is NOT
authority to bypass funding, trajectory, geometry or accounting checks.

No normal read expands a nested container. NodeRef is deliberately not a Mapping.
Retain each OwnedRow while borrowing its value. legacy_record() is an explicit,
funded compatibility export, never part of row access. Import accepts an owned
body plus a support iterator, so it need not assemble a complete descriptor.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from types import MappingProxyType

import numpy as np

import mesh_tables as M


SCHEMA = 'atlas.compact-differential-partition.v1'
PARTITION = 'atlas.differential-partition.v1'
SUPPORT = 'atlas.differential-physical-support.v1'
MAX_NODES = M.MAX_ITEMS
MAX_EDGES = 4*M.MAX_ITEMS
MAX_DEPTH = 128
MAX_ROW_ITEMS = 256
MAX_STRING_BYTES = 1 << 16
NULL, BOOL, INTEGER, FLOAT, TEXT, IDENT, RATIONAL, LIST, OBJECT = range(9)
KINDS = ('null', 'bool', 'integer', 'float', 'string', 'id', 'rational', 'list', 'object')
PARTITION_FIELDS = frozenset(('schema', 'scope', 'funding_id', 'source', 'collar_plan_id',
    'volume_map_id', 'current_geometry_id', 'network_id', 'start_time_s', 'end_time_s',
    'component_keys', 'component_registry', 'grid_id', 'grid_lines', 'grid_origin_m',
    'grid_basis', 'initial_source_plate_ids', 'source_regions', 'excluded_static_cells',
    'native_cells', 'support_ids', 'native_contacts', 'max_components', 'coverage', 'stocks',
    'interval_id', 'parent_partition_id', 'parent_network_id', 'endpoint_network_id',
    'start_support_id', 'end_support_id', 'trajectory', 'trajectory_id', 'prior_trajectory_id',
    'identity_start_cells', 'start_remap', 'finite_state_id', 'finite_owner_id', 'component_registry_id'))
PARTITION_REQUIRED = frozenset(('schema', 'scope', 'funding_id', 'source', 'collar_plan_id',
    'volume_map_id', 'current_geometry_id', 'network_id', 'start_time_s', 'end_time_s',
    'component_keys', 'component_registry', 'grid_id', 'grid_lines', 'grid_origin_m',
    'grid_basis', 'initial_source_plate_ids', 'source_regions', 'excluded_static_cells',
    'native_cells', 'support_ids', 'native_contacts', 'max_components', 'coverage', 'stocks'))
SUPPORT_FIELDS = frozenset(('schema', 'interval_id', 'kind', 'plate_id', 'source_key',
    'radial_layer', 'voxel', 'exclusion_ids', 'exclusion_cells', 'material_angular_velocity_rad_s',
    'constraints', 'components', 'max_components', 'work_units', 'start_time_s', 'end_time_s',
    'duration_s', 'coverage', 'birth_start_union', 'current_geometry_id', 'network_id',
    'physical_velocity', 'grid_id', 'voxel_index', 'radial_band', 'chart', 'source_chart_id',
    'finite_stock_id', 'stock_lineage', 'birth_boundary_id', 'birth_side'))
SUPPORT_REQUIRED = frozenset(('schema', 'interval_id', 'kind', 'plate_id', 'source_key',
    'radial_layer', 'voxel', 'exclusion_ids', 'exclusion_cells', 'material_angular_velocity_rad_s',
    'constraints', 'components', 'max_components', 'work_units', 'start_time_s', 'end_time_s',
    'duration_s', 'coverage'))
COMPONENT_FIELDS = frozenset(('logical_cell_id', 'partition_path', 'owner_ray_ids',
                              'constraints', 'parent_cell_id', 'start_identity'))
REGION_FIELDS = frozenset(('source_key', 'plate_id', 'source_face_id', 'radial_band', 'chart',
    'radial_layer', 'original_cone', 'source_chart_id', 'kind', 'source_constraint_chart',
    'parent_owner_ray_ids', 'parent_cells', 'parent_chart', 'finite_stock_id', 'stock_lineage',
    'birth_boundary_id', 'birth_side'))
CONSTRAINT_FIELDS = {
    'fixed-plane': frozenset(('kind', 'normal', 'offset')),
    'rotated-normal': frozenset(('kind', 'normal', 'angular_velocity_rad_s')),
    'moving-ray-edge': frozenset(('kind', 'rays')),
    'snapshot-rotated': frozenset(('kind', 'constraint', 'snapshot_offset_s', 'angular_velocity_rad_s'))}


class PartitionTablesRefused(ValueError):
    pass


def require(test, message):
    if not test:
        raise PartitionTablesRefused(message)


def _hash_json(record, budget):
    def extent(value):
        if type(value) is dict:
            rows = value.values()
            count, largest = len(value), max((M._width(k) for k in value), default=0)
        elif type(value) is list:
            rows, count, largest = value, len(value), 0
        else:
            return 0, M._width(value)
        for child in rows:
            slots, width = extent(child)
            count += slots; largest = max(largest, width)
        return count, largest
    slots, largest = extent(record)
    owner = M._Allocation(budget, 65536+128*slots+8*largest)
    h = sha256()
    for part in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(record):
        h.update(part.encode('ascii'))
    _ = owner
    return h.hexdigest()


class _Arena:
    """Incremental retained build/index charges, not a schema-maximum reserve."""
    def __init__(self, budget):
        self.budget, self.owners, self.free = budget, [], 0

    def hold(self, size):
        if size > self.free:
            size_new = max(65536, size+256)
            owner = M._Allocation(self.budget, size_new)
            self.owners.append(owner)
            self.free += size_new-256
        self.free -= size


class _Builder:
    def __init__(self, budget, check):
        self.arena = _Arena(budget)
        self.arena.hold(8192)
        self.pool = M._Pools()
        self.strings, self.string_values = {}, []
        self.floats, self.float_values = {}, []
        self.nodes, self.index, self.check = [], {}, check

    def string(self, value):
        require(type(value) is str and M._width(value) <= MAX_STRING_BYTES, 'bounded string required')
        # The lookup is against the caller-owned string; reserve before encoding.
        if value not in self.strings:
            self.arena.hold(512+8*M._width(value))
            self.strings[value] = len(self.string_values)
            self.string_values.append(M.canonical(value))
        return self.strings[value]

    def add(self, value, depth=0):
        self.check()
        require(depth <= MAX_DEPTH, 'partition DAG depth exceeds bound')
        rational = (type(value) is list and len(value) == 2 and
                    all(type(v) is str and v.startswith(('0x', '-0x')) for v in value))
        # One temporary row only; recursive child charges stay alive in frames.
        if rational:
            require(all(len(v) <= 2*M.MAX_INTEGER_BYTES+3 for v in value), 'rational text exceeds bound')
            scratch = M._Allocation(self.arena.budget, 4096+16*sum(len(v) for v in value))
        elif type(value) in (dict, list):
            require(len(value) <= MAX_EDGES, 'container exceeds item bound')
            scratch = M._Allocation(self.arena.budget, 4096+128*len(value))
        else:
            scratch = M._Allocation(self.arena.budget, 4096+8*M._width(value))
        edges = ()
        if value is None:
            kind, payload = NULL, 0
        elif type(value) is bool:
            kind, payload = BOOL, int(value)
        elif type(value) is int:
            if value not in self.pool.integers:
                self.arena.hold(256+(abs(value).bit_length()+7)//8)
            kind, payload = INTEGER, self.pool.integer(value)
        elif type(value) is float:
            require(math.isfinite(value), 'nonfinite value refused')
            raw = M.canonical(value)
            if raw not in self.floats:
                self.arena.hold(256)
                self.floats[raw] = len(self.float_values)
                self.float_values.append(value)
            kind, payload = FLOAT, self.floats[raw]
        elif type(value) is str:
            if len(value) == 64 and all(c in '0123456789abcdef' for c in value):
                if value not in self.pool.ids:
                    self.arena.hold(256)
                kind, payload = IDENT, self.pool.ident(value)
            else:
                kind, payload = TEXT, self.string(value)
        elif rational:
            indexes = tuple(self.pool.integers.get(int(v, 16)) for v in value)
            if None in indexes or indexes not in self.pool.rationals:
                self.arena.hold(1024+8*sum(len(v) for v in value))
            kind, payload = RATIONAL, self.pool.rational(value)
        elif type(value) is list:
            kind, payload = LIST, 0
            edges = tuple((M.NULL, self.add(v, depth+1)) for v in value)
        elif type(value) is dict:
            require(all(type(k) is str for k in value), 'string object keys required')
            kind, payload = OBJECT, 0
            edges = tuple((self.string(k), self.add(value[k], depth+1)) for k in sorted(value))
        else:
            raise PartitionTablesRefused('unsupported record value; no implicit conversion')
        key = kind, payload, edges
        if key not in self.index:
            require(len(self.nodes) < MAX_NODES, 'partition node count exceeds bound')
            self.arena.hold(512+96*len(edges))
            self.index[key] = len(self.nodes)
            self.nodes.append(key)
        _ = scratch
        return self.index[key]

    def finish(self):
        count = len(self.nodes)
        edges = sum(len(row[2]) for row in self.nodes)
        require(edges <= MAX_EDGES, 'partition edge count exceeds bound')
        self.arena.hold(128*count+32*edges+sum(map(len, self.string_values))+65536)
        kind, payload, offsets, children, keys = [], [], [0], [], []
        for k, p, rows in self.nodes:
            kind.append(k); payload.append(p)
            for key, child in rows:
                keys.append(key); children.append(child)
            offsets.append(len(children))
        string_offsets, raw = [0], bytearray()
        for value in self.string_values:
            raw.extend(value); string_offsets.append(len(raw))
        arrays = {'node.kind': np.array(kind, dtype='u1'), 'node.payload': np.array(payload, dtype='<u8'),
            'node.offset': np.array(offsets, dtype='<u8'), 'edge.child': np.array(children, dtype='<u8'),
            'edge.key': np.array(keys, dtype='<u8'), 'string.offset': np.array(string_offsets, dtype='<u8'),
            'string.bytes': np.frombuffer(raw, dtype='u1'), 'float.value': np.array(self.float_values, dtype='<f8')}
        self.pool.finish(arrays)
        # No annotation blobs: every scientific container is an indexed node.
        del arrays['tag.offset'], arrays['tag.bytes']
        return arrays


def pack_partition(body, supports, *, expected_partition_id, budget, check=lambda: None):
    """Convert an already-owned native body and one support record at a time.

    The input body is exactly DifferentialPartition.record(), NOT descriptor().
    This import does not issue a native partition or certify physical geometry.
    """
    M._budget(budget)
    require(type(body) is dict and set(body) <= PARTITION_FIELDS and PARTITION_REQUIRED <= set(body),
            'unknown or missing partition field; no field may be dropped')
    require(body['schema'] == PARTITION, 'unsupported partition schema')
    require(type(body['support_ids']) is list and len(body['support_ids']) <= MAX_NODES,
            'bounded ordered support inventory required')
    M._sha(expected_partition_id)
    width = M._width(body)
    require(width <= M.MAX_BYTES, 'partition body exceeds import bound')
    scratch = M._Allocation(budget, 65536+8*max((M._width(k) for k in body), default=0))
    builder = _Builder(budget, check)
    body_node = builder.add(body)
    require(_hash_json(body, budget) == expected_partition_id, 'original partition body hash differs')
    roots, support_ids = [], []
    for row in supports:
        check()
        at = len(roots)
        require(at < len(body['support_ids']), 'extra support record')
        require(type(row) is dict and set(row) <= SUPPORT_FIELDS and SUPPORT_REQUIRED <= set(row),
                'unknown or missing support field; no field may be dropped')
        require(row['schema'] == SUPPORT and M._width(row) <= M.MAX_BYTES, 'unsupported support schema/size')
        builder.arena.hold(128)
        root = builder.add(row)
        ident = _hash_json(row, budget)
        require(ident == body['support_ids'][at], 'ordered native support hash differs')
        roots.append(root); support_ids.append(builder.pool.ident(ident))
    require(len(roots) == len(body['support_ids']), 'missing support record')
    require(len(set(body['support_ids'])) == len(roots), 'duplicate support ID')
    arrays = builder.finish()
    arrays['support.node'] = np.array(roots, dtype='<u8')
    arrays['support.id'] = np.array(support_ids, dtype='<u8')
    arrays['support.lookup'] = np.array(sorted(range(len(roots)), key=lambda i: body['support_ids'][i]), dtype='<u8')
    metadata = dict(schema=SCHEMA, partition_id=expected_partition_id, body_node=body_node,
        support_count=len(roots), arrays={k: dict(dtype=v.dtype.str, shape=list(v.shape),
        sha256=sha256(M._raw_view(v)).hexdigest()) for k, v in arrays.items()})
    result = metadata, M._freeze(arrays, metadata, budget)
    _ = scratch
    return result


@dataclass(frozen=True, slots=True)
class NodeRef:
    """Immutable owning reference, not a dict/list proxy or admission token."""
    _view: object
    index: int

    def __post_init__(self):
        require(type(self._view) is CompactPartition and type(self.index) is int and
                0 <= self.index < self._view.node_count, 'node reference outside validated partition')

    @property
    def kind(self):
        return KINDS[int(self._view._arrays['node.kind'][self.index])]

    @property
    def size(self):
        require(self.kind in ('object', 'list'), 'container reference required')
        a, b = self._view._bounds(self.index)
        return b-a

    def field(self, name):
        require(self.kind == 'object' and type(name) is str, 'object and string field required')
        def compare(edge):
            i = int(self._view._arrays['edge.key'][edge])
            offsets = self._view._arrays['string.offset']
            owner = M._Allocation(self._view.budget, 4096+32*int(offsets[i+1]-offsets[i]))
            key = self._view._text(i)
            result = (key > name)-(key < name)
            _ = owner
            return result
        a, b = self._view._bounds(self.index)
        while a < b:
            m = (a+b)//2
            if compare(m) < 0:
                a = m+1
            else:
                b = m
        end = self._view._bounds(self.index)[1]
        require(a < end and compare(a) == 0,
                'missing partition field: '+name)
        result = NodeRef(self._view, int(self._view._arrays['edge.child'][a]))
        return result

    def at(self, index):
        require(self.kind == 'list' and type(index) is int and 0 <= index < self.size,
                'list index outside partition row')
        start, _ = self._view._bounds(self.index)
        return NodeRef(self._view, int(self._view._arrays['edge.child'][start+index]))

    def scalar(self):
        require(self.kind not in ('object', 'list'), 'container expansion requires explicit legacy export')
        owner = M._Allocation(self._view.budget, self._view._scalar_charge(self.index))
        return M.OwnedRow(self._view._scalar(self.index), (owner, self._view))

    def row(self):
        """One shallow row. Every child, including scalars, remains a NodeRef."""
        require(self.kind in ('object', 'list') and self.size <= MAX_ROW_ITEMS,
                'row exceeds bounded access; use field()/at() instead')
        a, b = self._view._bounds(self.index)
        key_bytes = 0
        if self.kind == 'object':
            offsets = self._view._arrays['string.offset']
            key_bytes = sum(int(offsets[int(i)+1]-offsets[int(i)])
                for i in self._view._arrays['edge.key'][a:b])
        owner = M._Allocation(self._view.budget, 4096+512*self.size+32*key_bytes)
        children = self._view._arrays['edge.child']
        value = ({self._view._text(int(self._view._arrays['edge.key'][i])):
            NodeRef(self._view, int(children[i])) for i in range(a, b)} if self.kind == 'object'
            else tuple(NodeRef(self._view, int(children[i])) for i in range(a, b)))
        return M.OwnedRow(value, (owner, self._view))


class CompactPartition:
    __slots__ = ('_arrays', '_metadata', '_budget', '_check', '_body', 'partition_id',
                 'support_count', 'node_count', '_sealed', '_max_scalar')

    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('immutable validated compact partition')
        object.__setattr__(self, name, value)

    def __init__(self, metadata, arrays, *, expected_partition_id, budget, check=lambda: None):
        M._budget(budget)
        require(type(metadata) is dict and set(metadata) == {'schema', 'partition_id', 'body_node',
            'support_count', 'arrays'} and metadata['schema'] == SCHEMA and
            metadata['partition_id'] == M._sha(expected_partition_id), 'partition schema or expected identity differs')
        require(M._width(metadata) < 65536 and type(arrays) is dict and set(arrays) == set(metadata['arrays']),
                'complete bounded array inventory required')
        require(all(type(a) is np.ndarray and a.flags.c_contiguous and not a.dtype.hasobject for a in arrays.values())
                and sum(a.nbytes for a in arrays.values()) <= M.MAX_BYTES, 'bounded contiguous numeric arrays required')
        scratch = M._Allocation(budget, 65536+12*M._width(metadata))
        metadata = json.loads(M.canonical(metadata))
        self._arrays = MappingProxyType(M._freeze(arrays, metadata, budget))
        for name, array in self._arrays.items():
            row = metadata['arrays'][name]
            require(type(row) is dict and set(row) == {'dtype', 'shape', 'sha256'} and
                array.dtype.str == row['dtype'] and list(array.shape) == row['shape'] and
                sha256(M._raw_view(array)).hexdigest() == row['sha256'], 'array content differs: '+name)
        self._metadata, self._budget, self._check = M.canonical(metadata), budget, check
        self.partition_id, self._body = expected_partition_id, metadata['body_node']
        self.support_count = metadata['support_count']
        self.node_count = len(self._arrays['node.kind']) if 'node.kind' in self._arrays else 0
        self._max_scalar = 65536
        self._validate()
        _schema_gate(self)
        require(self._hash(self._body) == expected_partition_id, 'streamed native partition hash differs')
        ids = self.root().field('support_ids')
        require(ids.kind == 'list' and ids.size == self.support_count, 'support inventory count differs')
        previous = None
        for i in range(self.support_count):
            check()
            ident = self.support_id(i)
            require(ids.at(i).scalar().value == ident and self._hash(self.support(i).index) == ident,
                    'streamed native support identity/order differs')
            j = int(self._arrays['support.lookup'][i])
            ordered = self.support_id(j)
            require(previous is None or previous < ordered, 'support lookup not unique/sorted')
            previous = ordered
        self._sealed = True
        _ = scratch

    @property
    def budget(self):
        return self._budget

    @property
    def nbytes(self):
        return len(self._metadata)+sum(a.nbytes for a in self._arrays.values())

    def _bounds(self, node):
        return tuple(map(int, self._arrays['node.offset'][node:node+2]))

    def _text(self, i):
        a, b = map(int, self._arrays['string.offset'][i:i+2])
        return json.loads(self._arrays['string.bytes'][a:b].tobytes())

    def _integer(self, i):
        a, b = map(int, self._arrays['int.offset'][i:i+2])
        return int(self._arrays['int.sign'][i])*int.from_bytes(M._raw_view(self._arrays['int.bytes'][a:b]), 'little')

    def _scalar(self, node):
        kind, p = int(self._arrays['node.kind'][node]), int(self._arrays['node.payload'][node])
        if kind == NULL:
            return None
        if kind == BOOL:
            return bool(p)
        if kind == INTEGER:
            return self._integer(p)
        if kind == FLOAT:
            return float(self._arrays['float.value'][p])
        if kind == TEXT:
            return self._text(p)
        if kind == IDENT:
            return self._arrays['id.bytes'][p].tobytes().hex()
        if kind == RATIONAL:
            return [hex(self._integer(int(i))) for i in self._arrays['q.pair'][p]]
        raise PartitionTablesRefused('scalar required')

    def _scalar_charge(self, node):
        k, p = int(self._arrays['node.kind'][node]), int(self._arrays['node.payload'][node])
        if k == TEXT:
            size = int(self._arrays['string.offset'][p+1]-self._arrays['string.offset'][p])
        elif k in (INTEGER, RATIONAL):
            indexes = (p,) if k == INTEGER else self._arrays['q.pair'][p]
            size = sum(int(self._arrays['int.offset'][int(i)+1]-self._arrays['int.offset'][int(i)]) for i in indexes)
        else:
            size = 128
        return 4096+32*size

    def root(self):
        return NodeRef(self, self._body)

    def support(self, i):
        require(type(i) is int and 0 <= i < self.support_count, 'support index outside inventory')
        return NodeRef(self, int(self._arrays['support.node'][i]))

    def support_id(self, i):
        require(type(i) is int and 0 <= i < self.support_count, 'support index outside inventory')
        return self._arrays['id.bytes'][int(self._arrays['support.id'][i])].tobytes().hex()

    def support_by_id(self, ident):
        M._sha(ident)
        a, b = 0, self.support_count
        while a < b:
            m = (a+b)//2
            if self.support_id(int(self._arrays['support.lookup'][m])) < ident:
                a = m+1
            else:
                b = m
        require(a < self.support_count and self.support_id(int(self._arrays['support.lookup'][a])) == ident,
                'unknown support ID')
        return self.support(int(self._arrays['support.lookup'][a]))

    def component(self, support_index, component_index):
        return self.support(support_index).field('components').at(component_index)

    def constraint(self, support_index, name):
        return self.support(support_index).field('constraints').field(name)

    def storage_payload(self):
        owner = M._Allocation(self.budget, M._decode_charge(self._metadata)+512*len(self._arrays))
        return M.OwnedRow((json.loads(self._metadata), dict(self._arrays)), (owner, self))

    def _iter(self, node):
        self._check()
        k = int(self._arrays['node.kind'][node])
        if k not in (LIST, OBJECT):
            yield M.canonical(self._scalar(node))
            return
        a, b = self._bounds(node)
        yield b'[' if k == LIST else b'{'
        for edge in range(a, b):
            if edge > a:
                yield b','
            if k == OBJECT:
                i = int(self._arrays['edge.key'][edge])
                start, end = map(int, self._arrays['string.offset'][i:i+2])
                yield self._arrays['string.bytes'][start:end].tobytes()
                yield b':'
            yield from self._iter(int(self._arrays['edge.child'][edge]))
        yield b']' if k == LIST else b'}'

    def iter_legacy_json(self, ref=None):
        node = self._body if ref is None else self._owned_ref(ref)
        owner = M._Allocation(self.budget, 65536+MAX_DEPTH*512+2*self._max_scalar)
        yield from self._iter(node)
        _ = owner

    def _owned_ref(self, ref):
        require(type(ref) is NodeRef and ref._view is self, 'reference belongs to another partition')
        return ref.index

    def _hash(self, node):
        h = sha256()
        for part in self.iter_legacy_json(NodeRef(self, node)):
            h.update(part)
        return h.hexdigest()

    def legacy_record(self, ref=None):
        """Explicit costly subtree export; never used by indexed consumers."""
        node = self._body if ref is None else self._owned_ref(ref)
        # Scan actual output before allocation. No decoded graph during sizing.
        size, pieces = 0, 0
        for part in self.iter_legacy_json(NodeRef(self, node)):
            size += len(part); pieces += 1
            require(size <= M.MAX_BYTES, 'legacy export exceeds explicit byte bound')
        owner = M._Allocation(self.budget, 65536+16*size+256*pieces)
        raw = b''.join(self.iter_legacy_json(NodeRef(self, node)))
        return M.OwnedRow(json.loads(raw), (owner, self))

    def _validate(self):
        a, n, s = self._arrays, self.node_count, self.support_count
        require(type(s) is int and 0 <= s <= MAX_NODES and type(self._body) is int and
                0 <= self._body < n <= MAX_NODES, 'invalid node/support counts')
        specs = {'node.kind': ('|u1', (n,)), 'node.payload': ('<u8', (n,)), 'node.offset': ('<u8', (n+1,)),
            'support.node': ('<u8', (s,)), 'support.id': ('<u8', (s,)), 'support.lookup': ('<u8', (s,))}
        tails = {'edge.child': ('<u8', ()), 'edge.key': ('<u8', ()), 'int.sign': ('|i1', ()),
            'int.offset': ('<u8', ()), 'int.bytes': ('|u1', ()), 'q.pair': ('<u8', (2,)),
            'id.bytes': ('|u1', (32,)), 'string.offset': ('<u8', ()), 'string.bytes': ('|u1', ()),
            'float.value': ('<f8', ())}
        require(set(a) == set(specs)|set(tails), 'unknown/missing compact scientific array')
        for name, (dtype, shape) in specs.items():
            require(a[name].dtype.str == dtype and a[name].shape == shape, 'invalid column: '+name)
        for name, (dtype, tail) in tails.items():
            require(a[name].dtype.str == dtype and a[name].ndim == 1+len(tail) and a[name].shape[1:] == tail,
                    'invalid pool column: '+name)
        def offsets(name, count, total):
            values = a[name]
            require(len(values) == count+1 and int(values[0]) == 0 and int(values[-1]) == total and
                    all(int(x) <= int(y) for x, y in zip(values[:-1], values[1:])), 'invalid CSR: '+name)
        require(len(a['edge.child']) == len(a['edge.key']) <= MAX_EDGES, 'invalid edge inventory')
        offsets('node.offset', n, len(a['edge.child']))
        offsets('int.offset', len(a['int.sign']), len(a['int.bytes']))
        offsets('string.offset', len(a['string.offset'])-1, len(a['string.bytes']))
        scan = _Arena(self.budget)
        scan.hold(65536+192*(n+sum(len(a[k]) for k in ('int.sign', 'q.pair', 'id.bytes', 'string.offset'))))
        seen = set()
        for i, sign in enumerate(a['int.sign']):
            self._check()
            lo, hi = map(int, a['int.offset'][i:i+2])
            require(hi-lo <= M.MAX_INTEGER_BYTES and int(sign) in (-1, 0, 1) and
                ((lo == hi and sign == 0) or (lo < hi and sign != 0 and int(a['int.bytes'][hi-1]) != 0)),
                'noncanonical arbitrary integer')
            key = int(sign), sha256(M._raw_view(a['int.bytes'][lo:hi])).digest()
            require(key not in seen, 'duplicate integer pool entry'); seen.add(key)
            self._max_scalar = max(self._max_scalar, 4096+64*(hi-lo))
        seen = set()
        for pair in a['q.pair']:
            require(all(int(i) < len(a['int.sign']) for i in pair), 'rational pool index outside integer pool')
            number_owner = M._Allocation(self.budget, 2*self._max_scalar)
            num, den = (self._integer(int(i)) for i in pair)
            key = tuple(map(int, pair))
            require(den > 0 and math.gcd(num, den) == 1 and key not in seen, 'noncanonical/duplicate rational')
            seen.add(key)
            del num, den, number_owner
        seen = set()
        for i in range(len(a['string.offset'])-1):
            lo, hi = map(int, a['string.offset'][i:i+2])
            require(0 < hi-lo <= MAX_STRING_BYTES, 'string exceeds bound')
            temporary = M._Allocation(self.budget, 4096+32*(hi-lo))
            raw = a['string.bytes'][lo:hi].tobytes()
            value = json.loads(raw)
            require(type(value) is str and M.canonical(value) == raw, 'noncanonical string')
            # Retain fixed digests only, not all string bodies in the scan set.
            key = sha256(raw).digest()
            require(key not in seen, 'duplicate string pool entry'); seen.add(key)
            self._max_scalar = max(self._max_scalar, 4096+32*(hi-lo))
            del raw, value, temporary
        require(len({r.tobytes() for r in a['id.bytes']}) == len(a['id.bytes']), 'duplicate ID pool entry')
        require(all(math.isfinite(float(v)) for v in a['float.value']) and
                len({M.canonical(float(v)) for v in a['float.value']}) == len(a['float.value']), 'invalid float pool')
        limits = {NULL: 1, BOOL: 2, INTEGER: len(a['int.sign']), FLOAT: len(a['float.value']),
                  TEXT: len(a['string.offset'])-1, IDENT: len(a['id.bytes']), RATIONAL: len(a['q.pair'])}
        depths = np.zeros(n, dtype='u1')
        widths = np.zeros(n, dtype='<u8')
        seen = set()
        for i in range(n):
            self._check()
            kind, payload = int(a['node.kind'][i]), int(a['node.payload'][i])
            lo, hi = self._bounds(i)
            require(kind in range(9), 'unknown node kind')
            h = sha256(bytes((kind,))+payload.to_bytes(8, 'little'))
            if kind in (LIST, OBJECT):
                require(payload == 0 and all(int(v) < i for v in a['edge.child'][lo:hi]),
                        'cyclic/forward DAG reference or hidden container payload')
                depth, last, width = 1, None, 2+max(0, hi-lo-1)
                text = None
                key_size = (max((int(a['string.offset'][int(k)+1]-a['string.offset'][int(k)])
                    for k in a['edge.key'][lo:hi] if int(k) < limits[TEXT]), default=0) if kind == OBJECT else 0)
                row_owner = M._Allocation(self.budget, 4096+64*key_size)
                for j in range(lo, hi):
                    child, key = int(a['edge.child'][j]), int(a['edge.key'][j])
                    depth = max(depth, 1+int(depths[child]))
                    width += int(widths[child])
                    if kind == OBJECT:
                        require(key < limits[TEXT], 'object key outside string pool')
                        text = self._text(key)
                        require(last is None or last < text, 'object fields not unique/sorted')
                        last = text
                        width += 1+int(a['string.offset'][key+1]-a['string.offset'][key])
                    else:
                        require(key == M.NULL, 'hidden key on list edge')
                    h.update(key.to_bytes(8, 'little')+child.to_bytes(8, 'little'))
                require(depth <= MAX_DEPTH, 'DAG depth exceeds bound')
                depths[i] = depth
                del last, text, row_owner
            else:
                require(lo == hi and payload < limits[kind], 'invalid scalar payload/edges')
                scalar_owner = M._Allocation(self.budget, self._scalar_charge(i))
                width = len(M.canonical(self._scalar(i)))
                del scalar_owner
            require(width <= M.MAX_BYTES, 'expanded logical node exceeds byte bound')
            widths[i] = width
            key = h.digest()
            require(key not in seen, 'duplicate DAG node'); seen.add(key)
        require(all(int(i) < n for i in a['support.node']) and
                all(int(i) < len(a['id.bytes']) for i in a['support.id']) and
                sorted(map(int, a['support.lookup'])) == list(range(s)), 'invalid support index/lookup')
        require(int(widths[self._body])+sum(int(widths[int(i)]) for i in a['support.node']) <= M.MAX_BYTES,
                'complete logical partition exceeds explicit byte bound')
        reachable = np.zeros(n, dtype='u1')
        reachable[self._body] = 1
        for i in a['support.node']:
            reachable[int(i)] = 1
        for i in range(n-1, -1, -1):
            if reachable[i]:
                lo, hi = self._bounds(i)
                for child in a['edge.child'][lo:hi]:
                    reachable[int(child)] = 1
        require(bool(np.all(reachable)), 'unreachable hidden DAG nodes refused')
        _ = scan


def _fields(ref, allowed, required=()):
    require(ref.kind == 'object', 'expected scientific record object')
    row = ref.row()
    require(set(row.value) <= allowed and set(required) <= set(row.value),
            'unknown or missing scientific field; no field may be dropped')
    return row


def _value(ref):
    return ref.scalar().value


def _schema_gate(view):
    """Known native container schemas; provenance values are preserved verbatim.

    This is format validation only. It intentionally does not replace native
    physical geometry/lineage validation or manufacture issued source objects.
    """
    root = view.root()
    held = _fields(root, PARTITION_FIELDS, PARTITION_REQUIRED)
    require(_value(root.field('schema')) == PARTITION and
            _value(root.field('scope')) in ('initial-current', 'physical-interval'), 'unsupported native partition schema/scope')
    owner = M._Allocation(view.budget, 65536+192*view.node_count+4*view._max_scalar)
    checked = set()
    def vector(ref):
        require(ref.kind == 'list' and ref.size == 3 and all(ref.at(i).kind == 'rational' for i in range(3)),
                'exact three-vector required')
    def constraint(ref):
        if ref.index in checked:
            return
        kind = _value(ref.field('kind'))
        require(kind in CONSTRAINT_FIELDS, 'unknown physical constraint kind')
        row = _fields(ref, CONSTRAINT_FIELDS[kind], CONSTRAINT_FIELDS[kind])
        if kind == 'snapshot-rotated':
            require(ref.field('snapshot_offset_s').kind == 'rational', 'exact snapshot offset required')
            constraint(ref.field('constraint'))
        if kind in ('snapshot-rotated', 'rotated-normal'):
            vector(ref.field('angular_velocity_rad_s'))
        if kind in ('fixed-plane', 'rotated-normal'):
            vector(ref.field('normal'))
        if kind == 'fixed-plane':
            require(ref.field('offset').kind == 'rational', 'exact plane offset required')
        if kind == 'moving-ray-edge':
            rays = ref.field('rays')
            require(rays.kind == 'list' and rays.size == 2, 'moving edge requires two exact rays')
            for i in range(2):
                ray = rays.at(i)
                ray_row = _fields(ray, {'direction', 'angular_velocity_rad_s', 'prior_rotations'},
                                  {'direction', 'angular_velocity_rad_s'})
                vector(ray.field('direction')); vector(ray.field('angular_velocity_rad_s'))
                if 'prior_rotations' in ray_row.value:
                    history = ray.field('prior_rotations')
                    require(history.kind == 'list', 'ray rotation history required')
                    for j in range(history.size):
                        step = history.at(j)
                        step_row = _fields(step, {'angular_velocity_rad_s', 'duration_s'}, {'angular_velocity_rad_s', 'duration_s'})
                        vector(step.field('angular_velocity_rad_s'))
                        require(step.field('duration_s').kind == 'rational', 'exact history duration required')
                        del step_row
                del ray_row
        checked.add(ref.index)
        _ = row
    def constraints(ref):
        require(ref.kind == 'object', 'named constraint table required')
        lo, hi = view._bounds(ref.index)
        for edge in range(lo, hi):
            constraint(NodeRef(view, int(view._arrays['edge.child'][edge])))
    def literals(ref, names):
        require(ref.kind == 'list', 'ordered constraint literals required')
        for i in range(ref.size):
            pair = ref.at(i)
            require(pair.kind == 'list' and pair.size == 2 and _value(pair.at(1)) in (-1, 1) and
                    pair.at(1).kind == 'integer', 'signed named constraint literal required')
            names.field(_value(pair.at(0)))
    for i in range(view.support_count):
        view._check()
        support = view.support(i)
        support_row = _fields(support, SUPPORT_FIELDS, SUPPORT_REQUIRED)
        require(_value(support.field('schema')) == SUPPORT, 'unsupported support schema')
        vector(support.field('material_angular_velocity_rad_s'))
        names = support.field('constraints'); constraints(names)
        components = support.field('components')
        require(components.kind == 'list', 'ordered components required')
        for j in range(components.size):
            component = components.at(j)
            component_row = _fields(component, COMPONENT_FIELDS,
                {'logical_cell_id', 'partition_path', 'owner_ray_ids', 'constraints'})
            require(component.field('logical_cell_id').kind == 'id', 'logical cell ID required')
            literals(component.field('constraints'), names)
            del component_row
        del support_row
    regions = root.field('source_regions')
    require(regions.kind == 'list', 'ordered source regions required')
    for i in range(regions.size):
        region = regions.at(i)
        region_row = _fields(region, REGION_FIELDS, {'source_key', 'plate_id', 'radial_band',
                                                   'chart', 'radial_layer', 'source_chart_id'})
        if 'source_constraint_chart' in region_row.value:
            chart = region.field('source_constraint_chart')
            chart_row = _fields(chart, {'constraints', 'literals'}, {'constraints', 'literals'})
            names = chart.field('constraints'); constraints(names)
            literals(chart.field('literals'), names)
            del chart_row
        del region_row
    _ = held, owner


# Keep source-transform imports independent of the loaded native runtime.
def __getattr__(name):
    if name == 'PartitionV2':
        from partition_v2 import PartitionV2
        return PartitionV2
    raise AttributeError(name)


def pack_partition_v2(*args, **kwargs):
    from partition_v2 import pack_partition_v2 as pack
    return pack(*args, **kwargs)
