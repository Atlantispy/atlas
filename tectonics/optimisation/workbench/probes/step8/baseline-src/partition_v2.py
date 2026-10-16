"""Partition domain adapter over bounded generic DAG/segment records.

The physical record is the exact native descriptor, including its support list.
The native partition identity still hashes the body only. No scientific issue,
whole-record decode, parent-pool seeding or locality permutation is implied.
"""
from hashlib import sha256
import json
from types import MappingProxyType

from compact_contracts import ContractError, LogicalIdentity, SegmentRef
from content_cache import ChargeSpec, Owned, OwnedStream, OWNER_BYTES
import record_tables as T
from record_views import CompactRecord, RecordRef, _owned

DESCRIPTOR = 'atlas.differential-partition-descriptor.v1'
PROFILE = 'atlas.compact-partition.v2'
MAX_HEADER_BYTES = 16 << 20
MAX_NATIVE_SUPPORT_BYTES = 128 << 20


def _require(ok, message):
    if not ok:
        raise ContractError(message)


def _fields(ref, allowed, required=()):
    """Known-field validation needs no unbounded object-key materialisation."""
    _require(ref.kind == 'object', 'scientific object required')
    present = []
    for name in sorted(allowed):
        try:
            child = ref.field(name)
        except KeyError:
            continue
        child.close()
        present.append(name)
    _require(len(present) == ref.size and set(required) <= set(present),
             'unknown or missing scientific field')
    return tuple(present)


def _scalar(ref):
    try:
        with ref.scalar(max_owned_bytes=1 << 20) as owned:
            return owned.value
    finally:
        ref.close()


def _children(ref):
    """Yield one owning child from an authenticated object shape at a time."""
    _require(ref.kind == 'object', 'named object required')
    view = ref._view
    start, stop = view._range('node', ref.index)
    for edge in range(start, stop):
        yield RecordRef(view, view._v('edge.child', edge), parent_owner=ref._owner)


def _rational(ref):
    try:
        _require(ref.kind == 'array' and ref.size == 2, 'exact rational pair required')
        for i in range(2):
            child = ref.at(i)
            try:
                # The native individual binary-magnitude ceiling remains 1 MiB.
                # Keep the owned decoded string and parse scratch charged while
                # validating; a large exact rational is not a small header scalar.
                with child.scalar(max_owned_bytes=64 << 20) as owned:
                    value = owned.value
                    _require(type(value) is str and value.startswith(('0x', '-0x')) and
                             len(value) <= 2*T.MAX_INTEGER_BYTES+3, 'exact rational string required')
                    try:
                        integer = int(value, 16)
                    except ValueError as error:
                        raise ContractError('invalid exact rational string') from error
                    _require((abs(integer).bit_length()+7)//8 <= T.MAX_INTEGER_BYTES,
                             'individual binary magnitude exceeds 1 MiB')
                    del integer, value
            finally:
                child.close()
    finally:
        ref.close()


def _vector(ref):
    try:
        _require(ref.kind == 'array' and ref.size == 3, 'exact three-vector required')
        for i in range(3):
            _rational(ref.at(i))
    finally:
        ref.close()


def _schema_gate(body, supports):
    # Imports are lazy: partition_tables re-exports this module after v1 loads.
    import partition_tables as P
    checked = set()
    checked_shapes = {}
    arena = T._Arena(body.scope.run_budget)
    def fields(ref, allowed, required=()):
        # A shape is one authenticated ordered key inventory. Revalidate values
        # per row, but do not repeat the same field-name search for every support.
        _require(ref.kind == 'object', 'scientific object required')
        key = (ref._view._v('node.shape', ref.index), frozenset(allowed), frozenset(required))
        if key not in checked_shapes:
            arena.hold(4096+128*len(allowed))
            checked_shapes[key] = _fields(ref, allowed, required)
        return checked_shapes[key]
    fields(body, P.PARTITION_FIELDS, P.PARTITION_REQUIRED)
    _require(_scalar(body.field('schema')) == P.PARTITION and
             _scalar(body.field('scope')) in ('initial-current', 'physical-interval'),
             'unsupported native partition schema/scope')

    def constraint(ref):
        try:
            if ref.index in checked:
                return
            kind = _scalar(ref.field('kind'))
            _require(kind in P.CONSTRAINT_FIELDS, 'unknown physical constraint kind')
            fields(ref, P.CONSTRAINT_FIELDS[kind], P.CONSTRAINT_FIELDS[kind])
            if kind == 'snapshot-rotated':
                _rational(ref.field('snapshot_offset_s'))
                constraint(ref.field('constraint'))
            if kind in ('snapshot-rotated', 'rotated-normal'):
                _vector(ref.field('angular_velocity_rad_s'))
            if kind in ('fixed-plane', 'rotated-normal'):
                _vector(ref.field('normal'))
            if kind == 'fixed-plane':
                _rational(ref.field('offset'))
            if kind == 'moving-ray-edge':
                rays = ref.field('rays')
                try:
                    _require(rays.kind == 'array' and rays.size == 2, 'two exact rays required')
                    for i in range(2):
                        ray = rays.at(i)
                        try:
                            names = fields(ray, {'direction', 'angular_velocity_rad_s', 'prior_rotations'},
                                            {'direction', 'angular_velocity_rad_s'})
                            _vector(ray.field('direction')); _vector(ray.field('angular_velocity_rad_s'))
                            if 'prior_rotations' in names:
                                history = ray.field('prior_rotations')
                                try:
                                    _require(history.kind == 'array', 'ray history required')
                                    for j in range(history.size):
                                        step = history.at(j)
                                        try:
                                            fields(step, {'angular_velocity_rad_s', 'duration_s'},
                                                    {'angular_velocity_rad_s', 'duration_s'})
                                            _vector(step.field('angular_velocity_rad_s'))
                                            _rational(step.field('duration_s'))
                                        finally:
                                            step.close()
                                finally:
                                    history.close()
                        finally:
                            ray.close()
                finally:
                    rays.close()
            arena.hold(128)
            checked.add(ref.index)
        finally:
            ref.close()

    def constraints(ref):
        for child in _children(ref):
            constraint(child)

    def literals(ref, names):
        try:
            _require(ref.kind == 'array', 'ordered literals required')
            for i in range(ref.size):
                pair = ref.at(i)
                try:
                    _require(pair.kind == 'array' and pair.size == 2, 'signed literal required')
                    sign = _scalar(pair.at(1))
                    _require(type(sign) is int and sign in (-1, 1), 'integer signed literal required')
                    names.field(_scalar(pair.at(0))).close()
                finally:
                    pair.close()
        finally:
            ref.close()

    for support in supports:
        try:
            fields(support, P.SUPPORT_FIELDS, P.SUPPORT_REQUIRED)
            _require(_scalar(support.field('schema')) == P.SUPPORT, 'unsupported support schema')
            _vector(support.field('material_angular_velocity_rad_s'))
            names, components = support.field('constraints'), support.field('components')
            try:
                constraints(names)
                _require(components.kind == 'array', 'ordered components required')
                for j in range(components.size):
                    component = components.at(j)
                    try:
                        fields(component, P.COMPONENT_FIELDS,
                                {'logical_cell_id', 'partition_path', 'owner_ray_ids', 'constraints'})
                        cell = _scalar(component.field('logical_cell_id'))
                        P.M._sha(cell)
                        literals(component.field('constraints'), names)
                    finally:
                        component.close()
            finally:
                components.close(); names.close()
        finally:
            support.close()
    regions = body.field('source_regions')
    try:
        _require(regions.kind == 'array', 'ordered source regions required')
        for i in range(regions.size):
            region = regions.at(i)
            try:
                names = fields(region, P.REGION_FIELDS,
                    {'source_key', 'plate_id', 'radial_band', 'chart', 'radial_layer', 'source_chart_id'})
                if 'source_constraint_chart' in names:
                    chart = region.field('source_constraint_chart')
                    try:
                        fields(chart, {'constraints', 'literals'}, {'constraints', 'literals'})
                        table = chart.field('constraints')
                        try:
                            constraints(table); literals(chart.field('literals'), table)
                        finally:
                            table.close()
                    finally:
                        chart.close()
            finally:
                region.close()
    finally:
        regions.close()


class PartitionBodyRef(RecordRef):
    """Exact body projection; normal field access stays a generic owned ref."""
    def iter_json(self, *, max_chunk_bytes=T.CHUNK):
        _require(type(max_chunk_bytes) is int and 0 < max_chunk_bytes <= T.CHUNK,
                 'bounded body stream required')
        self._live()
        anchor = self._owner.retain()
        def pieces():
            yield b'{'
            for i, name in enumerate(self._fields):
                if i:
                    yield b','
                yield T.canonical(name)+b':'
                child = self.field(name)
                try:
                    with child.iter_json(max_chunk_bytes=max_chunk_bytes) as stream:
                        for part in stream:
                            with part:
                                yield part.value
                finally:
                    child.close()
            yield b'}'
        def generate():
            scratch = T.Scratch(self.scope.run_budget, 3*T.CHUNK+65536)
            buffer = bytearray()
            for part in pieces():
                for start in range(0, len(part), max_chunk_bytes):
                    chunk = part[start:start+max_chunk_bytes]
                    if len(buffer)+len(chunk) > max_chunk_bytes:
                        yield _owned(self.scope, len(buffer)+128, lambda: bytes(buffer))
                        buffer.clear()
                    buffer.extend(chunk)
            if buffer:
                yield _owned(self.scope, len(buffer)+128, lambda: bytes(buffer))
            del scratch
        return OwnedStream(generate(), owners=(anchor,), scope=self.scope)

    def identity(self):
        digest, count = sha256(), 0
        with self.iter_json() as stream:
            for part in stream:
                with part:
                    digest.update(part.value); count += len(part.value)
        import partition_tables as P
        return LogicalIdentity(P.PARTITION, digest.hexdigest(), count)

    def export(self, *, max_logical_bytes, max_owned_bytes):
        length = self.identity().canonical_bytes
        charge = 65536+192*length
        _require(type(max_logical_bytes) is int and type(max_owned_bytes) is int and
                 0 <= length <= max_logical_bytes and charge+OWNER_BYTES <= max_owned_bytes,
                 'body export exceeds explicit bound before allocation')
        def decode():
            chunks = []
            with self.iter_json() as stream:
                for part in stream:
                    with part:
                        chunks.append(part.value)
            return json.loads(b''.join(chunks))
        return _owned(self.scope, charge, decode, 'partition-body-export')


class PartitionV2:
    """Sealed descriptor with a separately verified body and support inventory."""
    __slots__ = ('_record', '_index', '_body_fields', '_partition_id', '_segment_ref', '_sealed')

    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('immutable sealed partition v2')
        object.__setattr__(self, name, value)

    def __init__(self, record, *, expected_partition_id, segment_ref=None, check=lambda: None):
        import partition_tables as P
        _require(type(record) is CompactRecord and record.identity().record_schema == DESCRIPTOR,
                 'partition v2 requires exact descriptor record')
        P.M._sha(expected_partition_id)
        _require(segment_ref is None or type(segment_ref) is SegmentRef and
                 segment_ref.identity == record.identity(), 'partition segment identity differs')
        self._record, self._segment_ref, self._sealed = record, segment_ref, False
        with record._read_batch():
            self._validate_domain(expected_partition_id, check)
        self._sealed = True

    def _validate_domain(self, expected_partition_id, check):
        import partition_tables as P
        record = self._record
        root = record.root()
        try:
            self._body_fields = tuple(name for name in _fields(root,
                P.PARTITION_FIELDS | {'partition_id', 'supports'},
                P.PARTITION_REQUIRED | {'partition_id', 'supports'})
                if name not in ('partition_id', 'supports'))
            self._partition_id = _scalar(root.field('partition_id'))
            _require(self._partition_id == expected_partition_id, 'partition original identity differs')
            body = self.root()
            try:
                _require(body.identity().sha256 == expected_partition_id, 'partition body hash differs')
                ids, supports = root.field('support_ids'), root.field('supports')
                try:
                    _require(ids.kind == supports.kind == 'array' and ids.size == supports.size,
                             'ordered support inventory differs')
                    with record.scope.reserve(ChargeSpec('partition-support-index',
                            65536+1024*ids.size)) as reservation:
                        ordered, lookup, identities, nodes = [], {}, [], []
                        for i in range(ids.size):
                            check()
                            identity = _scalar(ids.at(i)); P.M._sha(identity)
                            _require(identity not in lookup, 'duplicate support ID')
                            support = supports.at(i)
                            try:
                                actual = support.identity()
                                _require(actual.sha256 == identity, 'ordered support hash differs')
                                identities.append(LogicalIdentity(P.SUPPORT, actual.sha256, actual.canonical_bytes))
                                nodes.append(support.index)
                            finally:
                                support.close()
                            lookup[identity] = i; ordered.append(identity)
                        self._index = reservation.commit((tuple(ordered), MappingProxyType(lookup),
                                                          tuple(identities), tuple(nodes)))
                    schema_scratch = T.Scratch(record.scope.run_budget, 2 << 20)
                    _schema_gate(body, (supports.at(i) for i in range(supports.size)))
                    del schema_scratch
                finally:
                    supports.close(); ids.close()
            finally:
                body.close()
        finally:
            root.close()
        check()

    @property
    def record(self):
        return self._record

    @property
    def scope(self):
        return self._record.scope

    @property
    def budget(self):
        return self.scope.run_budget

    @property
    def partition_id(self):
        return self._partition_id

    @property
    def segment_ref(self):
        return self._segment_ref

    @property
    def support_count(self):
        return len(self._index.value[0])

    def bind_segment(self, ref):
        _require(type(ref) is SegmentRef and ref.identity == self.identity(), 'partition segment binding differs')
        _require(self._segment_ref is None or self._segment_ref == ref, 'partition binding is immutable')
        object.__setattr__(self, '_segment_ref', ref)

    def root(self):
        return PartitionBodyRef(self._record, self._record._root, fields=self._body_fields)

    def support_id(self, index):
        _require(type(index) is int and 0 <= index < self.support_count, 'support index outside inventory')
        return self._index.value[0][index]

    def support(self, index):
        self.support_id(index)
        root = self._record.root()
        supports = root.field('supports')
        try:
            result = supports.at(index)
            # Domain provenance for native routing consumers. The genuine
            # reference still owns its generic record and complete ancestry.
            result._partition = self
            return result
        finally:
            # The returned child owns its ancestry; explicit close would refuse.
            del supports, root

    def support_by_id(self, identity):
        _require(identity in self._index.value[1], 'missing partition support ID')
        return self.support(self._index.value[1][identity])

    def support_identity(self, support_id):
        """Reuse the sealed body verification only while its file is unchanged."""
        self.identity()
        _require(support_id in self._index.value[1], 'missing partition support ID')
        return self._index.value[2][self._index.value[1][support_id]]

    def support_node(self, support_id):
        self.identity()
        _require(support_id in self._index.value[1], 'missing partition support ID')
        return self._index.value[3][self._index.value[1][support_id]]

    def identity(self):
        segment = getattr(self._record._columns, 'segment', None)
        if segment is not None:
            if hasattr(segment.resolver, 'interval'):
                segment._live()
                segment.resolver._owner.value
                segment.resolver.stores.assert_cached_read_safe(cancel=segment.cancel)
            else:
                segment.check_unchanged()
        return self._record.identity()

    def iter_json(self, *, max_chunk_bytes=T.CHUNK):
        return self._record.iter_json(max_chunk_bytes=max_chunk_bytes)

    def legacy_record(self, ref=None, *, max_logical_bytes=MAX_HEADER_BYTES,
                      max_owned_bytes=256 << 20):
        """Explicit, bounded native compatibility export; never a normal read."""
        target = self.root() if ref is None else ref
        try:
            _require(isinstance(target, RecordRef) and target.scope is self.scope,
                     'same-scope partition operand required')
            return target.export(max_logical_bytes=max_logical_bytes,
                                 max_owned_bytes=max_owned_bytes)
        finally:
            if ref is None:
                target.close()

    def close(self):
        self._record._owner.assert_unborrowed()
        self._index.assert_unborrowed()
        self._index.close()
        self._record.close()
        object.__setattr__(self, '_sealed', False)


def pack_partition_v2(body, supports, *, expected_partition_id, scope, check=lambda: None,
                      parent_pool=None, locality_permutation=None, support_cache=False):
    import partition_tables as P
    _require(parent_pool is None, 'parent pool seeding disabled pending measured benefit gate')
    _require(locality_permutation is None, 'locality permutation disabled pending measured benefit gate')
    _require(support_cache is False, 'support cache disabled pending measured benefit gate')
    _require(type(body) is dict and P.PARTITION_REQUIRED <= set(body) <= P.PARTITION_FIELDS,
             'complete native partition body required')
    _require(type(body['support_ids']) is list, 'ordered support IDs required')
    def rows():
        for row in supports:
            check()
            if isinstance(row, Owned):
                _require(row.scope is scope, 'foreign support row scope')
                yield row.retain()
            else:
                # Inputs are caller-owned native rows. Transfer a paid carrier
                # while the builder consumes this one row; never retain a list.
                _require(type(row) is dict, 'owned native support object required')
                with scope.reserve(ChargeSpec('partition-input-support',
                        65536+192*P.M._width(row))) as reservation:
                    yield reservation.commit(row)
    descriptor = dict(body, partition_id=expected_partition_id,
                      supports=T.StreamingRows(len(body['support_ids']), rows))
    record = T.RecordCodec().pack_record(descriptor, record_schema=DESCRIPTOR, scope=scope, check=check)
    return PartitionV2(record, expected_partition_id=expected_partition_id, check=check)
