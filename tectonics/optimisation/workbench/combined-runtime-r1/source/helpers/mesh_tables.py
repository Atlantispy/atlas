"""Private lossless ExteriorMesh tables; no scientific admission or native patch.

Metrics/connectivity are fixed numeric arrays. Exact rationals use a deduplicated
arbitrary-integer pool, never float conversion. Physical support records are
separate content-addressed canonical blobs. A reader reconstructs at most ONE
requested row/support; full legacy reconstruction is explicit diagnostic export.

The supplied support writer/reader owns persistence and its returned input bytes.
Publish the mesh arrays/header through the existing ArrayStore transaction only
after support blobs are durable. Unreferenced blobs after cancellation confer no
completion. Caller must retain OwnedRow while borrowing its .value, just as the
native owned-view APIs require. This module changes no native source or guards.
"""
from dataclasses import dataclass
from contextlib import contextmanager
from fractions import Fraction
from hashlib import sha256
from itertools import chain
import json
import math
from types import MappingProxyType

import numpy as np


SCHEMA = 'atlas.compact-exterior-mesh.v1'
LEGACY = 'atlas.source-bound-exterior-thermal-mesh.v1'
METHOD = 'continuous-cartesian-quadratic-interpolant-exact-mortar-v1'
NULL = (1 << 64)-1
MAX_ITEMS = 1_000_000
MAX_BYTES = 1 << 30
MAX_SUPPORT_BYTES = 128 << 20
MAX_INTEGER_BYTES = 1 << 20
MAX_HEADER_BYTES = 2 << 20
MAX_TAG_BYTES = 1 << 16
TABLES = ('voxels', 'radial_layers', 'cones', 'differential_supports')
CELL_TAGS = frozenset(('kind', 'index', 'source_key', 'plate_id', 'material_support_kind',
                       'metric_point_kind', 'voxel_index', 'radial_band', 'chart'))
CELL_FIELDS = CELL_TAGS | {'cell_id', 'logical_cell_id', 'physical_cell_id', 'volume_m3',
    'centroid_m', 'faces', 'physical_volume_bounds_m3', 'geometry_volume_max_deviation_m3',
    'physical_support', 'volume_centroid_m'}
FACE_TAGS = frozenset(('kind', 'geometry_kind', 'relative_advection', 'boundary_role'))
FACE_FIELDS = FACE_TAGS | {'face_id', 'centroid_m', 'area_vector_m2', 'owners',
                         'vertices_m', 'cartesian_support', 'reservoir_cut'}
HEADER_FIELDS = frozenset(('schema', 'method', 'physical_geometry_family', 'funding_id',
    'source', 'support_id', 'trajectory_id', 'trajectory_segments', 'endpoint',
    'wall_measure_id', 'time_s', 'grid_id', 'support_ids', 'representative_quaternion',
    'pose_operator_error_bound', 'geometry_volume_max_deviation_m3',
    'max_geometry_volume_error_m3', 'radial_rule', 'endpoint_lower_rule', 'advection_rule',
    'scope', 'booked_cell_rule', 'current_geometry_id', 'partition_id', 'initial_bounds_id',
    'interval_id', 'ale_bounds_id', 'parent_partition_id', 'thermal_subdivisions',
    'thermal_witness_refinements', 'max_thermal_witness_refinements', 'thermal_aggregation'))
SPECIAL = frozenset(('cells', 'faces', 'support_tables', 'grid_lines',
                     'thermal_shared_lines', 'required_thermal_boundary_faces'))
SUPPORT_KEYS = ('voxel_id', 'radial_layer_id', 'cone_id', 'differential_support_id', 'logical_cell_id')


class MeshTablesRefused(ValueError):
    pass


def require(test, message):
    if not test:
        raise MeshTablesRefused(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def digest(value):
    return sha256(canonical(value)).hexdigest()


def _sha(value):
    require(type(value) is str and len(value) == 64 and
            all(c in '0123456789abcdef' for c in value), 'canonical SHA-256 ID required')
    return value


def _width(value, depth=0, top=None):
    """Allocation-free encoded upper width; only bounded JSON-domain inputs.

    x-mesh-booking (A5): when `top` is a three-item list, top[0] >= top[1]
    are kept as the two largest scalar (string/number) widths seen, and
    top[2] (re-check defect 4) as the largest sum of two scalar widths that
    are consecutive elements of one list: json's iterencode yields those as
    consecutive chunks, while a container element, or a dict key and its
    separator, puts small chunks of its own between two scalars. The width
    returned is unchanged. pack_mesh books its transient token copies from it.
    """
    require(depth <= 128, 'record nesting exceeds bound')
    if value is None or type(value) is bool:
        return 5
    if type(value) is str:
        # ensure_ascii emits two UTF-16 escapes for non-BMP code points.
        # ASCII control characters also escape even when no quote/backslash
        # occurs; an isascii() fast path alone underestimates these strings.
        # x-mesh-cert: printable ASCII (0x20-0x7e, the only characters the
        # formula below counts as 1 or 2) gives the identical value at C speed.
        if value.isascii() and value.isprintable():
            result = 2+len(value)+value.count('"')+value.count('\\')
        else:
            result = 2+sum(12 if ord(c) > 0xffff else 6 if ord(c) < 32 or ord(c) > 126
                           else 2 if c in ('"', '\\') else 1 for c in value)
    elif type(value) is int:
        result = 3+abs(value).bit_length()
    elif type(value) is float:
        require(math.isfinite(value), 'nonfinite metadata refused')
        result = 32
    elif type(value) is list:
        require(len(value) <= MAX_ITEMS, 'list exceeds bound')
        if top is None:
            return 2+sum(1+_width(v, depth+1) for v in value)
        total, previous = 2, 0
        for v in value:
            current = _width(v, depth+1, top)
            total += 1+current
            if type(v) is list or type(v) is dict:
                previous = 0
            else:
                top[2] = max(top[2], previous+current)
                previous = current
        return total
    elif type(value) is dict:
        require(len(value) <= MAX_ITEMS and all(type(k) is str for k in value), 'JSON object required')
        return 2+sum(2+_width(k, depth+1, top)+_width(v, depth+1, top) for k, v in value.items())
    else:
        raise MeshTablesRefused('unsupported record value; no implicit conversion')
    if top is not None and result > top[1]:
        top[0], top[1] = (result, top[0]) if result > top[0] else (top[0], result)
    return result


def _decode_charge(raw):
    """Bound decoded JSON objects without first creating those objects.

    Count syntax only outside strings. Containers, entries, scalar slots and
    string headers have separate overhead: a forest of tiny empty objects does
    not fit a simple encoded-byte multiplier. Four bytes per source byte also
    covers decoded Unicode storage and integer magnitude. This is allocation
    admission, not a parser or a replacement for canonical JSON validation.
    """
    total, quoted, escaped = 65536+4*len(raw), False, False
    for value in raw:
        if quoted:
            if escaped:
                escaped = False
            elif value == 92:
                escaped = True
            elif value == 34:
                quoted = False
        elif value == 34:
            quoted = True
            total += 128
        elif value in (123, 91):
            total += 256
        elif value in (44, 58):
            total += 128
    return total


class _Allocation:
    def __init__(self, budget, size):
        self.guard = None
        self.size = size
        guard = budget.reserve(size, category='compact-mesh-owned')
        guard.__enter__()
        self.guard = guard

    def __del__(self):
        guard = getattr(self, 'guard', None)
        if guard is not None:
            self.guard = None
            guard.__exit__(None, None, None)


def _view_allocation(view, size):
    if view._scope is None:
        return _Allocation(view._budget, size)
    from content_cache import ChargeSpec
    return view._scope.reserve(ChargeSpec('mesh-row', size)).commit(None, dependencies=(view._owner,))


class _Bytes(bytes):
    def __new__(cls, data, owner):
        result = super().__new__(cls, data)
        object.__setattr__(result, 'owner', owner)
        return result

    def __setattr__(self, name, value):
        raise AttributeError('immutable owned bytes')


def _raw_view(array):
    # Flatten first: memoryview.cast rejects some zero-length multi-D arrays.
    return memoryview(array.reshape(-1)).cast('B')


@dataclass(frozen=True)
class OwnedRow:
    """Small decoded result; retain this object while borrowing its value."""
    value: object
    _owner: object


@dataclass(frozen=True, slots=True)
class SharedSupportRecord:
    """One reference, not a retained decoded support or compatibility JSON."""
    view: object
    identity: str

    def open(self):
        from partition_v2 import PartitionV2
        from support_source import SupportSource
        require((type(self.view) is PartitionV2 and self.view._sealed) or type(self.view) is SupportSource,
                'sealed compact partition support required')
        ref = (self.view.ref_for(self.identity) if type(self.view) is SupportSource else
               self.view.support_by_id(self.identity))
        # Close only after a successful export. A failed export's frames still
        # hold child borrows of ``ref``, so closing it then would refuse and
        # replace the original error (a guard stop or cancellation) with "owner
        # has live child borrows". On failure ``ref`` stays paid until those
        # frames are released; its owner then retires (content_cache.Owned).
        exported = ref.export(max_logical_bytes=MAX_SUPPORT_BYTES, max_owned_bytes=256 << 20)
        ref.close()
        return exported


def _budget(budget):
    from atlas_tectonics.resources import WorkBudget
    require(type(budget) is WorkBudget, 'actual shared WorkBudget required')


def _freeze(arrays, metadata, budget, *, owner=None):
    size = sum(a.nbytes for a in arrays.values())
    require(size <= MAX_BYTES, 'compact arrays exceed byte bound')
    if owner is None:
        owner = _Allocation(budget, size+8*len(canonical(metadata))+512*len(arrays)+65536)
    result = {}
    for name, array in arrays.items():
        raw = _Bytes(_raw_view(array), owner)
        result[name] = np.frombuffer(raw, dtype=array.dtype).reshape(array.shape)
    return result


class _Pools:
    def __init__(self):
        self.integers, self.integer_values = {}, []
        self.rationals, self.rational_values = {}, []
        self.ids, self.id_values = {}, []
        self.tags, self.tag_values = {}, []

    @staticmethod
    def _index(mapping, values, value):
        if value not in mapping:
            require(len(values) < MAX_ITEMS, 'shared pool exceeds bound')
            mapping[value] = len(values)
            values.append(value)
        return mapping[value]

    def ident(self, value):
        return self._index(self.ids, self.id_values, _sha(value))

    def integer(self, value):
        require((abs(value).bit_length()+7)//8 <= MAX_INTEGER_BYTES, 'arbitrary integer exceeds byte bound')
        return self._index(self.integers, self.integer_values, value)

    def rational(self, pair):
        require(type(pair) is list and len(pair) == 2 and all(type(s) is str for s in pair),
                'canonical rational-hex pair required')
        require(all(len(s) <= 2*MAX_INTEGER_BYTES+3 for s in pair), 'rational text exceeds bound')
        try:
            n, d = (int(v, 16) for v in pair)
        except ValueError as error:
            raise MeshTablesRefused('invalid rational integer') from error
        require(d > 0 and math.gcd(n, d) == 1 and pair == [hex(n), hex(d)],
                'rational must be canonical, reduced, with positive denominator')
        value = self.integer(n), self.integer(d)
        return self._index(self.rationals, self.rational_values, value)

    def vector(self, value, count=3):
        require(type(value) is list and len(value) == count, 'exact vector width differs')
        return [self.rational(v) for v in value]

    def tag(self, value):
        require(_width(value) <= MAX_TAG_BYTES, 'row annotation exceeds bound')
        raw = canonical(value)
        return self._index(self.tags, self.tag_values, raw)

    def finish(self, arrays):
        offsets, magnitude, signs = [0], bytearray(), []
        for value in self.integer_values:
            signs.append(0 if value == 0 else 1 if value > 0 else -1)
            magnitude.extend(abs(value).to_bytes((abs(value).bit_length()+7)//8, 'little'))
            offsets.append(len(magnitude))
        tag_offsets, tag_bytes = [0], bytearray()
        for raw in self.tag_values:
            tag_bytes.extend(raw)
            tag_offsets.append(len(tag_bytes))
        arrays.update({'int.sign': np.array(signs, dtype='i1'),
            'int.offset': np.array(offsets, dtype='<u8'), 'int.bytes': np.frombuffer(magnitude, dtype='u1'),
            'q.pair': np.array(self.rational_values, dtype='<u8').reshape(-1, 2),
            'id.bytes': np.frombuffer(b''.join(bytes.fromhex(v) for v in self.id_values), dtype='u1').reshape(-1, 32),
            'tag.offset': np.array(tag_offsets, dtype='<u8'), 'tag.bytes': np.frombuffer(tag_bytes, dtype='u1')})


def _array(rows, width=None, dtype='<u8'):
    result = np.array(rows, dtype=dtype)
    return result if width is None else result.reshape(-1, width)


def _support_value(table, value):
    if table != 'differential_supports' or type(value) is dict:
        return value
    require(table == 'differential_supports' and callable(getattr(value, 'record', None)),
            'issued differential support or explicit support record required')
    return value.record()


@contextmanager
def _support_record(table, value):
    # Fresh compact construction may name an ephemeral partition support.
    # Keep its paid export alive for exactly this one operation.
    if table == 'differential_supports' and type(value) is SharedSupportRecord:
        held = value.open()
        try:
            yield held.value
        except BaseException:
            # An escaped failing consumer frame may still hold the value.
            raise
        else:
            del held
    else:
        yield _support_value(table, value)


def _support_width(table, value):
    with _support_record(table, value) as decoded:
        return _width(decoded)


def _shared_view(value):
    from partition_v2 import PartitionV2
    from support_source import SupportSource
    view = value.view
    require((type(view) is PartitionV2 and view._sealed) or type(view) is SupportSource,
            'sealed compact partition support required')
    return view, type(view) is SupportSource


def _shared_identity(value):
    """The sealed partition's authenticated identity of one shared support."""
    view, source = _shared_view(value)
    found = view.identity(value.identity) if source else view.support_identity(value.identity)
    size = found.canonical_bytes
    require(type(size) is int and 0 <= size and type(found.sha256) is str, 'shared support identity required')
    return found


def _shared_bytes(value):
    """One stream of a shared support: its exact bytes, checked against its identity.

    x-mesh-cert (F5): replaces three decodes per shared support (width,
    canonical blob, geometry stream). The partition's authenticated length
    sizes the buffer; the SHA-256 and length of the streamed bytes must equal
    that identity, so the bytes are exactly the canonical support (refused
    otherwise, as the old canonical(decoded) comparison refused).
    """
    found = _shared_identity(value)
    size = found.canonical_bytes
    require(size <= MAX_SUPPORT_BYTES, 'support blob exceeds bound')
    view, source = _shared_view(value)
    ref = view.ref_for(value.identity) if source else view.support_by_id(value.identity)
    try:
        raw, digest, offset = bytearray(size), sha256(), 0
        with ref.iter_json(max_chunk_bytes=65536) as stream:
            for part in stream:
                with part:
                    stop = offset+len(part.value)
                    require(stop <= size, 'fresh support differs from compact partition')
                    raw[offset:stop] = part.value
                    digest.update(part.value)
                    offset = stop
        content = digest.hexdigest()
        require(offset == size and content == found.sha256, 'fresh support differs from compact partition')
        result = bytes(raw)
        del raw
    except BaseException:
        # A failed stream frame may still borrow the reference; an explicit
        # close would replace the original refusal. The traceback owns it.
        del ref
        raise
    ref.close()
    return content, result


def _largest_support(table, value):
    if table == 'differential_supports' and type(value) is SharedSupportRecord:
        # Exact canonical length from the authenticated identity: no decode.
        return _shared_identity(value).canonical_bytes
    return _support_width(table, value)


def _input_stream(record, *, check, support):
    """iter_input_json's exact bytes; support(table, ident, value) gives each support's bytes."""
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False)
    yield b'{'
    for at, (name, value) in enumerate(sorted(record.items())):
        check()
        if at:
            yield b','
        yield canonical(name)+b':'
        if name != 'support_tables':
            for text in encoder.iterencode(value):
                yield text.encode('ascii')
            continue
        yield b'{'
        for ti, (table, entries) in enumerate(sorted(value.items())):
            if ti:
                yield b','
            yield canonical(table)+b':{'
            for si, (ident, item) in enumerate(sorted(entries.items())):
                check()
                if si:
                    yield b','
                yield canonical(ident)+b':'
                yield support(table, ident, item)
            yield b'}'
        yield b'}'
    yield b'}'


def iter_input_json(record, *, check=lambda: None):
    """Canonical fresh-producer bytes, with only one native support decoded."""
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False)
    yield b'{'
    for at, (name, value) in enumerate(sorted(record.items())):
        check()
        if at:
            yield b','
        yield canonical(name)+b':'
        if name != 'support_tables':
            for text in encoder.iterencode(value):
                yield text.encode('ascii')
            continue
        yield b'{'
        for ti, (table, entries) in enumerate(sorted(value.items())):
            if ti:
                yield b','
            yield canonical(table)+b':{'
            for si, (ident, support) in enumerate(sorted(entries.items())):
                check()
                if si:
                    yield b','
                yield canonical(ident)+b':'
                with _support_record(table, support) as decoded:
                    for text in encoder.iterencode(decoded):
                        yield text.encode('ascii')
                del decoded
            yield b'}'
        yield b'}'
    yield b'}'


def _dict_bytes(count):
    """Upper traced bytes of a dict holding `count` entries (CPython 3.12).

    Key tables are powers of two from 8 with 2/3 usable entries of 24 bytes
    and 1-8 byte indices; a full table is rebuilt at the smallest power of
    two >= 3*used, the old table living until the new one is filled.
    """
    def table(size):
        index = 1 if size <= 0x80 else 2 if size <= 0x8000 else 4 if size <= 0x80000000 else 8
        return 40+size*index+(2*size//3)*24
    size, previous = 8, 0
    while 2*size//3 < count:
        previous = size
        size = 1 << max(3, (3*(2*size//3)-1).bit_length())
    return 64+table(size)+(table(previous) if previous else 0)


def _list_bytes(count):
    return 64+8*(count+(count >> 3)+6)


def _scratch_bytes(record, cells, faces, supports, width, support_count, largest_support, longest=(0, 0, 0)):
    """Peak builder bytes of pack_mesh, assuming no value is shared (W3, M12).

    Structure counts come from one allocation-free pass over the admitted
    rows (malformed rows count as empty; the main loop refuses them). Each
    term is an upper bound of the traced CPython/numpy objects pack_mesh
    builds for that structure (64-bit, CPython 3.12), see
    test_w3_mesh_booking for the measured comparison:
    - rational pool: 2-tuple 56 + index int 32 + list slot 9 + q.pair 16 per
      reference, plus its dict; integer pool per integer: int header 32 +
      index int 32 + slot 9 + finish offset/sign rows 59, plus its dict;
      integer digits: int objects 4 B per 30 bits and the magnitude buffer
      (with growth) are at most 1.1 B per encoded hex digit, <= 1.1*width;
    - IDs: index int 32 + slot 9 + finish fromhex/join 113 per reference (the
      64-character strings are the caller's, except support content hashes,
      113 B each); tags: index int 32 + slot 9 + bytes 33 + finish 45 plus
      2.25 B per encoded tag byte;
    - cell rows 394 + cell columns 169 + lookup 53 per cell, 27 per face
      reference; face rows 341 + columns 190 per face, 113 per vertex, 17
      per owner, 145 per Cartesian support; cell/face ID maps;
    - one support decode and its canonical blob (4x its width), 230 B per
      support inventory entry, and 64 KiB of fixed allocator and stream slack;
    - x-mesh-booking (A5): transient copies of the widest scalar tokens,
      2*max(L1, P)+256 for the largest scalar width L1 and the largest sum P
      of two scalar widths adjacent in one list (longest[0], longest[2]).
      The input stream holds at most two tokens' copies at once: the
      previous chunk's str and bytes (its generator and loop variables)
      while json builds the next chunk's escaped str and its separator
      concatenation, each about one token width plus a 41/33 B header.
      Two such tokens are consecutive chunks only as neighbouring scalars of
      one list (re-check defect 4: 2*(L1+L2) over-booked about 2x when the
      two widest tokens were not neighbours).
      The canonical-spelling check (hex(n), hex(d) next to fresh ints) and
      the finish of the widest integer (abs copy + to_bytes) are smaller and
      run in other phases. The steady int digits/magnitude stay in 1.1*width.
    """
    def rows(value):
        return value if type(value) is list else ()
    rationals = sum(len(rows(axis)) for field in ('grid_lines', 'thermal_shared_lines')
                    for axis in rows(record.get(field)))
    ids = 2*support_count
    tags = tag_width = face_refs = vertices = owners = carts = 0
    for row in cells:
        if type(row) is not dict:
            continue
        rationals += 4+2*('physical_volume_bounds_m3' in row)+('geometry_volume_max_deviation_m3' in row)+(
            3*('volume_centroid_m' in row))
        ids += 1+('logical_cell_id' in row)+('physical_cell_id' in row)+(
            len(row['physical_support']) if type(row.get('physical_support')) is dict else 0)
        face_refs += len(rows(row.get('faces')))
        tags += 1
        tag_width += _width({k: v for k, v in row.items() if k in CELL_TAGS})
    for row in faces:
        if type(row) is not dict:
            continue
        count = len(rows(row.get('vertices_m')))
        cart = len(rows(row.get('cartesian_support')))
        rationals += 6+3*count+cart
        ids += 1+2*cart+('reservoir_cut' in row)
        vertices += count; carts += cart; owners += len(rows(row.get('owners')))
        tags += 1
        tag_width += _width({k: v for k, v in row.items() if k in FACE_TAGS})
    integers = 2*rationals
    count_cells, count_faces = len(cells), len(faces)
    return (113*rationals+_dict_bytes(rationals)+_list_bytes(rationals)+
            132*integers+_dict_bytes(integers)+_list_bytes(integers)+(11*width+9)//10+
            154*ids+_dict_bytes(ids)+_list_bytes(ids)+113*support_count+
            119*tags+_dict_bytes(tags)+_list_bytes(tags)+(9*tag_width+3)//4+
            (394+169+53+32)*count_cells+_dict_bytes(count_cells)+27*face_refs+
            (341+190+53+32)*count_faces+_dict_bytes(count_faces)+113*vertices+17*owners+145*carts+
            4*largest_support+230*support_count+65536+2*max(longest[0], longest[2])+256)


def pack_mesh(record, *, support_writer, budget, check=lambda: None, _defer_freeze=False):
    """Return (small metadata, immutable numeric arrays); no whole output JSON.

    Input is an already-owned legacy record. support_writer(content_sha, bytes)
    must persist/own one canonical blob without collecting all support dicts.
    A future native builder can emit these same tables without a legacy import.
    """
    _budget(budget)
    require(type(record) is dict and set(record) <= HEADER_FIELDS | SPECIAL and
            {'schema', 'method', 'cells', 'faces', 'support_tables', 'grid_lines'} <= set(record),
            'unsupported or missing mesh field; no scientific field may be dropped')
    require(record['schema'] == LEGACY and record['method'] == METHOD, 'unsupported mesh science schema/method')
    cells, faces, supports = record['cells'], record['faces'], record['support_tables']
    require(type(cells) is list and type(faces) is list and 0 < len(cells) <= MAX_ITEMS and
            0 < len(faces) <= MAX_ITEMS, 'bounded nonempty cells/faces required')
    require(type(supports) is dict and set(supports) <= set(TABLES) and
            all(type(v) is dict for v in supports.values()), 'unsupported support table')
    header = {k: v for k, v in record.items() if k not in SPECIAL}
    require(_width(header) <= MAX_HEADER_BYTES, 'small mesh header exceeds bound')
    longest = [0, 0, 0]
    width = _width(header, 0, longest)+_width(cells, 0, longest)+_width(faces, 0, longest)+sum(
        _width(record[field], 0, longest) for field in ('grid_lines', 'thermal_shared_lines',
            'required_thermal_boundary_faces') if field in record)
    support_count = sum(len(table) for table in supports.values())
    require(support_count <= MAX_ITEMS, 'support inventory exceeds bound')
    largest_support = max((_largest_support(name, v) for name, table in supports.items()
                           for v in table.values()), default=0)
    require(width <= MAX_BYTES and largest_support <= MAX_SUPPORT_BYTES, 'mesh import exceeds bounded size')
    # Support values stay caller-owned and only one is encoded at a time. The
    # sorted inventory, shared IDs, content hashes and numeric column builders
    # nevertheless grow with every support entry, not its largest blob.
    # W3 (M12): derived from per-structure costs, not 12x the encoded width.
    scratch = _Allocation(budget, _scratch_bytes(record, cells, faces, supports, width,
                                                 support_count, largest_support, longest))
    pool, arrays = _Pools(), {}
    cell_ids = {_sha(r['cell_id']): i for i, r in enumerate(cells)}
    face_ids = {_sha(r['face_id']): i for i, r in enumerate(faces)}
    require(len(cell_ids) == len(cells) and len(face_ids) == len(faces), 'duplicate cell/face IDs')
    ids, qs, tags, refs, masks, offsets, incidence, signs = [], [], [], [], [], [0], [], []
    for row in cells:
        check()
        require(type(row) is dict and set(row) <= CELL_FIELDS and
                {'cell_id', 'volume_m3', 'centroid_m', 'faces'} <= set(row), 'unsupported cell fields')
        mask = 0
        row_ids = [pool.ident(row['cell_id']), NULL, NULL]
        for bit, name in enumerate(('logical_cell_id', 'physical_cell_id')):
            if name in row:
                mask |= 1 << bit
                row_ids[bit+1] = pool.ident(row[name])
        values = [pool.rational(row['volume_m3']), *pool.vector(row['centroid_m']), *([NULL]*6)]
        for bit, name, start, count in ((2, 'physical_volume_bounds_m3', 4, 2),
                (3, 'geometry_volume_max_deviation_m3', 6, 1), (4, 'volume_centroid_m', 7, 3)):
            if name in row:
                mask |= 1 << bit
                values[start:start+count] = ([pool.rational(row[name])] if count == 1 else pool.vector(row[name], count))
        support = [NULL]*5
        if 'physical_support' in row:
            mask |= 32
            item = row['physical_support']
            require(type(item) is dict and set(item) in ({'voxel_id'},
                {'voxel_id', 'radial_layer_id', 'cone_id'}, {'differential_support_id', 'logical_cell_id'}),
                'unsupported exact physical-support reference')
            for at, name in enumerate(SUPPORT_KEYS):
                if name in item:
                    support[at] = pool.ident(item[name])
        require(type(row['faces']) is list and len(row['faces']) <= MAX_ITEMS, 'cell face list required')
        for item in row['faces']:
            require(type(item) is list and len(item) == 2 and item[0] in face_ids and
                    type(item[1]) is int and item[1] in (-1, 1), 'invalid signed face reference')
            incidence.append(face_ids[item[0]]); signs.append(item[1])
        offsets.append(len(incidence))
        ids.append(row_ids); qs.append(values); refs.append(support); masks.append(mask)
        tags.append(pool.tag({k: v for k, v in row.items() if k in CELL_TAGS}))
    arrays.update({'c.id': _array(ids, 3), 'c.q': _array(qs, 10), 'c.tag': _array(tags),
        'c.support': _array(refs, 5), 'c.mask': _array(masks, dtype='u1'),
        'c.face_offset': _array(offsets), 'c.face': _array(incidence), 'c.sign': _array(signs, dtype='i1'),
        'c.lookup': _array(sorted(range(len(cells)), key=lambda i: cells[i]['cell_id']))})
    del ids, qs, tags, refs, masks, offsets, incidence, signs
    ids, qs, tags, masks, vertices, voff, owners, ooff, cart, coff, cuts = [], [], [], [], [], [0], [], [0], [], [0], []
    for row in faces:
        check()
        require(type(row) is dict and set(row) <= FACE_FIELDS and
                {'face_id', 'centroid_m', 'area_vector_m2', 'owners', 'vertices_m'} <= set(row), 'unsupported face fields')
        ids.append(pool.ident(row['face_id'])); qs.append(pool.vector(row['centroid_m'])+pool.vector(row['area_vector_m2']))
        tags.append(pool.tag({k: v for k, v in row.items() if k in FACE_TAGS}))
        require(type(row['owners']) is list and 1 <= len(row['owners']) <= 2 and
                all(v in cell_ids for v in row['owners']), 'invalid named face owners')
        owners.extend(cell_ids[v] for v in row['owners']); ooff.append(len(owners))
        require(type(row['vertices_m']) is list and 3 <= len(row['vertices_m']) <= MAX_ITEMS,
                'bounded face polygon required')
        vertices.extend(pool.vector(v) for v in row['vertices_m']); voff.append(len(vertices))
        mask = 0
        if 'cartesian_support' in row:
            mask |= 1
            require(type(row['cartesian_support']) is list, 'Cartesian support list required')
            for item in row['cartesian_support']:
                require(type(item) is dict and set(item) == {'cell_id', 'physical_voxel_id', 'axis', 'end', 'local_coordinate_m'} and
                    type(item['axis']) is int and item['axis'] in (0, 1, 2) and type(item['end']) is int and item['end'] in (0, 1),
                    'invalid Cartesian face support')
                cart.append([pool.ident(item['cell_id']), pool.ident(item['physical_voxel_id']), item['axis'], item['end'],
                             pool.rational(item['local_coordinate_m'])])
        coff.append(len(cart))
        cut = [NULL]*3
        if 'reservoir_cut' in row:
            mask |= 2
            item = row['reservoir_cut']
            require(type(item) is dict and set(item) == {'cell_id', 'axis', 'end'} and
                    type(item['axis']) is int and item['axis'] in (0, 1, 2) and type(item['end']) is int and item['end'] in (0, 1),
                    'invalid reservoir cut')
            cut = [pool.ident(item['cell_id']), item['axis'], item['end']]
        cuts.append(cut); masks.append(mask)
    arrays.update({'f.id': _array(ids), 'f.q': _array(qs, 6), 'f.tag': _array(tags), 'f.mask': _array(masks, dtype='u1'),
        'f.vertex_offset': _array(voff), 'f.vertex': _array(vertices, 3), 'f.owner_offset': _array(ooff),
        'f.owner': _array(owners), 'f.cart_offset': _array(coff), 'f.cart': _array(cart, 5), 'f.cut': _array(cuts, 3),
        'f.lookup': _array(sorted(range(len(faces)), key=lambda i: faces[i]['face_id']))})
    del ids, qs, tags, masks, vertices, voff, owners, ooff, cart, coff, cuts, cell_ids
    grid_fields = [k for k in ('grid_lines', 'thermal_shared_lines') if k in record]
    for field in grid_fields:
        axes = record[field]
        require(type(axes) is list and len(axes) == 3, 'three exact grid axes required')
        off, values = [0], []
        for axis in axes:
            require(type(axis) is list, 'grid axis must be a list')
            values.extend(pool.rational(q) for q in axis); off.append(len(values))
        arrays[field+'.offset'], arrays[field+'.q'] = _array(off), _array(values)
        del off, values
    if 'required_thermal_boundary_faces' in record:
        require(type(record['required_thermal_boundary_faces']) is list and
                all(v in face_ids for v in record['required_thermal_boundary_faces']), 'required thermal face absent')
        arrays['required.face'] = _array([face_ids[v] for v in record['required_thermal_boundary_faces']])
    del face_ids
    tables, support_ids, blob_ids, sizes = [], [], [], []
    table_names = sorted(supports)
    # x-mesh-cert (F5): the geometry stream and the support blobs share ONE
    # pass in the same sorted (table, ID) order as before; pool IDs are
    # assigned in that same order, so every column and blob is unchanged.
    # Each support's exact bytes feed its writer and the geometry hash once.
    def support(table, ident, value, pool=pool, tables=tables, support_ids=support_ids,
                blob_ids=blob_ids, sizes=sizes):
        check()
        if table == 'differential_supports' and type(value) is SharedSupportRecord:
            content, raw = _shared_bytes(value)
        else:
            with _support_record(table, value) as decoded:
                raw = canonical(decoded)
            del decoded
            require(len(raw) <= MAX_SUPPORT_BYTES, 'support blob exceeds bound')
            content = sha256(raw).hexdigest()
        support_writer(content, raw)
        tables.append(TABLES.index(table)); support_ids.append(pool.ident(ident))
        blob_ids.append(pool.ident(content)); sizes.append(len(raw))
        return raw
    original_hash = sha256()
    for raw in _input_stream(record, check=check, support=support):
        check()
        original_hash.update(raw)
    del raw, support
    arrays.update({'s.table': _array(tables, dtype='u1'), 's.id': _array(support_ids),
                   's.blob': _array(blob_ids), 's.size': _array(sizes)})
    pool.finish(arrays)
    del pool, tables, support_ids, blob_ids, sizes
    metadata = dict(schema=SCHEMA, geometry_id=original_hash.hexdigest(), header=header,
        grid_fields=grid_fields, support_tables=table_names,
        required_faces_present='required_thermal_boundary_faces' in record,
        cell_count=len(cells), face_count=len(faces),
        arrays={k: dict(dtype=v.dtype.str, shape=list(v.shape), sha256=sha256(_raw_view(v)).hexdigest())
                for k, v in arrays.items()})
    if _defer_freeze:
        # Private producer transfer: the returned owner must accompany these
        # mutable builders until CompactMesh has validated and frozen them.
        return metadata, arrays, scratch
    frozen = _freeze(arrays, metadata, budget)
    _ = scratch
    return metadata, frozen


class CompactMesh:
    """Authenticated storage view, NOT an issued scientific ExteriorMesh."""
    __slots__ = ('_metadata', '_budget', '_reader', '_check', '_arrays', 'geometry_id',
                 '_header', 'cell_count', 'face_count', '_grids', '_tables', '_required', '_sealed',
                 '_scope', '_owner', '_segment', '_logical_identity')

    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('immutable validated compact mesh')
        object.__setattr__(self, name, value)

    def __init__(self, metadata, arrays, *, support_reader, expected_geometry_id, budget, check=lambda: None,
                 scope=None, dependencies=()):
        _budget(budget)
        require(type(metadata) is dict and set(metadata) == {'schema', 'geometry_id', 'header', 'grid_fields',
            'support_tables', 'required_faces_present', 'cell_count', 'face_count', 'arrays'} and
            metadata['schema'] == SCHEMA and metadata['geometry_id'] == _sha(expected_geometry_id),
            'compact mesh schema or independently expected geometry ID differs')
        require(_width(metadata) <= 4*MAX_HEADER_BYTES and type(arrays) is dict and
                set(arrays) == set(metadata['arrays']), 'complete bounded compact array inventory required')
        require(all(type(a) is np.ndarray and a.flags.c_contiguous and not a.dtype.hasobject
                    for a in arrays.values()), 'contiguous numeric arrays required')
        require(sum(a.nbytes for a in arrays.values()) <= MAX_BYTES, 'compact arrays exceed byte bound')
        scratch = _Allocation(budget, 12*_width(metadata)+sum(a.nbytes for a in arrays.values())+65536)
        for name, row in metadata['arrays'].items():
            a = arrays[name]
            require(type(a) is np.ndarray and a.flags.c_contiguous and a.dtype.str == row['dtype'] and
                    list(a.shape) == row['shape'] and a.nbytes <= MAX_BYTES and
                    sha256(_raw_view(a)).hexdigest() == row['sha256'], 'compact array byte identity differs: '+name)
        self._metadata = canonical(metadata)
        self._budget, self._reader, self._check = budget, support_reader, check
        immutable_owner = None
        if scope is not None:
            from content_cache import ChargeSpec
            require(scope.run_budget is budget and all(owner.scope is scope for owner in dependencies),
                    'fresh mesh requires one shared retained scope')
            size = sum(a.nbytes for a in arrays.values())+8*len(canonical(metadata))+512*len(arrays)+65536
            immutable_owner = scope.reserve(ChargeSpec('mesh-memory-columns', size)).commit(None)
        self._arrays = MappingProxyType(_freeze(arrays, metadata, budget, owner=immutable_owner))
        self.geometry_id = expected_geometry_id
        self._header = canonical(metadata['header'])
        self.cell_count, self.face_count = metadata['cell_count'], metadata['face_count']
        self._grids = tuple(metadata['grid_fields'])
        self._tables = tuple(metadata['support_tables'])
        self._required = metadata['required_faces_present']
        self._scope, self._owner, self._segment = scope, None, None
        if scope is not None:
            self._owner = scope.reserve(ChargeSpec('mesh-memory-view', 4096)).commit(
                None, dependencies=(immutable_owner, *dependencies))
        self._validate()
        found, size = sha256(), 0
        for part in self.iter_legacy_json():
            check(); found.update(part)
            size += len(part)
        require(found.hexdigest() == expected_geometry_id, 'streamed original geometry identity differs')
        from compact_contracts import LogicalIdentity
        self._logical_identity = LogicalIdentity(LEGACY, expected_geometry_id, size)
        self._sealed = True
        _ = scratch

    @property
    def budget(self):
        return self._budget

    @property
    def scope(self):
        return self._scope

    def identity(self):
        """Reuse only this process's verified immutable logical identity."""
        self._check()
        if self._segment is not None:
            self._segment._live()
            if hasattr(self._segment.resolver, 'interval'):
                self._segment.resolver._owner.value
                self._segment.resolver.stores.assert_cached_read_safe(cancel=self._segment.cancel)
            else:
                self._segment.check_unchanged()
            self._reader.source.check_unchanged()
        if self._owner is not None:
            self._owner.value
        require(self._sealed, 'unsealed mesh has no reusable identity')
        return self._logical_identity

    def close(self):
        require(self._scope is not None, 'explicit close is available for retained v3 views')
        owner = self._owner
        owner.assert_unborrowed()
        reader, segment = self._reader, self._segment
        if segment is None:
            for name in ('_arrays', '_reader', '_metadata', '_header'):
                object.__setattr__(self, name, None)
            owner.close()
            return
        reader.arrays = None
        for name in ('_arrays', '_reader', '_segment', '_metadata', '_header'):
            object.__setattr__(self, name, None)
        owner.close()
        reader.owner.close()
        reader.source = reader.segment = reader.static = None
        segment.close()

    @property
    def nbytes(self):
        return sum(a.nbytes for a in self._arrays.values())+len(self._metadata)

    def header(self):
        owner = _view_allocation(self, _decode_charge(self._header))
        return OwnedRow(json.loads(self._header), owner)

    def support_bindings(self):
        """Authenticated (content SHA-256, byte length), without decoding blobs."""
        for ident, size in zip(self._arrays['s.blob'], self._arrays['s.size']):
            yield self.ident(int(ident)), int(size)

    def support_blobs(self):
        """Owned canonical bytes for bounded cross-store persistence, one each."""
        require(self._segment is None, 'v3 shared supports remain partition-owned')
        for index, ident in enumerate(self._arrays['s.blob']):
            raw, held = self._support_blob(index)
            yield OwnedRow((self.ident(int(ident)), raw), held)
            del raw, held

    def storage_payload(self):
        """Owned (detached metadata, immutable arrays) for atomic persistence.

        Keep the returned OwnedRow through publication. Its arrays remain owned
        if independently retained; its detached metadata is borrowed from this
        wrapper, never an alias into the validated view.
        """
        require(self._segment is None, 'v3 mesh republication uses its authenticated segment reference')
        owner = _view_allocation(self, _decode_charge(self._metadata)+512*len(self._arrays))
        return OwnedRow((json.loads(self._metadata), dict(self._arrays)), owner)

    def _validate(self):
        a = self._arrays
        c, f = self.cell_count, self.face_count
        require(type(c) is int and type(f) is int and 0 < c <= MAX_ITEMS and 0 < f <= MAX_ITEMS,
                'invalid compact mesh counts')
        fixed = {'c.id': ('<u8', (c, 3)), 'c.q': ('<u8', (c, 10)), 'c.tag': ('<u8', (c,)),
            'c.mask': ('|u1', (c,)), 'c.support': ('<u8', (c, 5)), 'c.face_offset': ('<u8', (c+1,)),
            'c.lookup': ('<u8', (c,)), 'f.id': ('<u8', (f,)), 'f.q': ('<u8', (f, 6)),
            'f.tag': ('<u8', (f,)), 'f.mask': ('|u1', (f,)), 'f.cut': ('<u8', (f, 3)),
            'f.vertex_offset': ('<u8', (f+1,)), 'f.owner_offset': ('<u8', (f+1,)),
            'f.cart_offset': ('<u8', (f+1,)), 'f.lookup': ('<u8', (f,))}
        variable = {'c.face': ('<u8', ()), 'c.sign': ('|i1', ()), 'f.vertex': ('<u8', (3,)),
            'f.owner': ('<u8', ()), 'f.cart': ('<u8', (5,)), 'int.sign': ('|i1', ()),
            'int.offset': ('<u8', ()), 'int.bytes': ('|u1', ()), 'q.pair': ('<u8', (2,)),
            'id.bytes': ('|u1', (32,)), 'tag.offset': ('<u8', ()), 'tag.bytes': ('|u1', ()),
            's.table': ('|u1', ()), 's.id': ('<u8', ()), 's.blob': ('<u8', ()), 's.size': ('<u8', ())}
        require(self._grids in (('grid_lines',), ('grid_lines', 'thermal_shared_lines')) and
                self._tables == tuple(sorted(set(self._tables))) and set(self._tables) <= set(TABLES) and
                type(self._required) is bool, 'invalid optional array groups')
        for name in self._grids:
            fixed[name+'.offset'] = '<u8', (4,)
            variable[name+'.q'] = '<u8', ()
        if self._required:
            variable['required.face'] = '<u8', ()
        require(set(a) == set(fixed) | set(variable), 'unknown compact scientific column')
        for name, (dtype, shape) in fixed.items():
            require(a[name].dtype.str == dtype and a[name].shape == shape, 'invalid fixed column: '+name)
        for name, (dtype, tail) in variable.items():
            require(a[name].dtype.str == dtype and a[name].ndim == 1+len(tail) and
                    a[name].shape[1:] == tail and
                    a[name].shape[0] <= (MAX_BYTES if name in ('int.bytes', 'tag.bytes') else MAX_ITEMS),
                    'invalid variable column: '+name)
        def offsets(name, total, count=None):
            values = a[name]
            require(len(values) > 0 and int(values[0]) == 0 and int(values[-1]) == total and
                    (count is None or len(values) == count+1) and
                    all(int(values[i]) <= int(values[i+1]) for i in range(len(values)-1)),
                    'invalid CSR offsets: '+name)
        offsets('int.offset', len(a['int.bytes']), len(a['int.sign']))
        offsets('tag.offset', len(a['tag.bytes']))
        offsets('c.face_offset', len(a['c.face']), c)
        offsets('f.owner_offset', len(a['f.owner']), f)
        offsets('f.vertex_offset', len(a['f.vertex']), f)
        offsets('f.cart_offset', len(a['f.cart']), f)
        for name in self._grids:
            offsets(name+'.offset', len(a[name+'.q']), 3)
        require(len(a['c.face']) == len(a['c.sign']) and
                all(int(v) in (-1, 1) for v in a['c.sign']), 'invalid signed incidence')
        ids, integers, rationals = len(a['id.bytes']), len(a['int.sign']), len(a['q.pair'])
        # Pool/lookup uniqueness needs bounded sets, never a whole decoded mesh.
        # Retain this allocation in any held error traceback as well.
        scan_owner = _Allocation(self._budget, 192*(ids+integers+rationals+c+f+len(a['tag.offset']))+65536)
        seen = set()
        for i in range(integers):
            self._check()
            start, end = map(int, a['int.offset'][i:i+2])
            sign = int(a['int.sign'][i])
            require(end-start <= MAX_INTEGER_BYTES and sign in (-1, 0, 1) and
                    ((start == end and sign == 0) or (start < end and sign != 0 and int(a['int.bytes'][end-1]) != 0)),
                    'noncanonical integer magnitude/sign')
            key = sign, sha256(_raw_view(a['int.bytes'][start:end])).digest()
            require(key not in seen, 'duplicate arbitrary integer pool entry')
            seen.add(key)
        seen = set()
        for at, pair in enumerate(a['q.pair']):
            require(all(int(v) < integers for v in pair), 'rational integer index outside pool')
            number_owner = self._row_owner((at,))
            n, d = (self.integer(int(v)) for v in pair)
            require(d > 0 and math.gcd(n, d) == 1, 'noncanonical rational pool')
            key = tuple(map(int, pair))
            require(key not in seen, 'duplicate rational pool entry')
            seen.add(key)
            del n, d, number_owner
        require(len({row.tobytes() for row in a['id.bytes']}) == ids, 'duplicate shared ID pool entry')
        def indexes(name, count, nullable=False):
            require(all(int(v) < count or nullable and int(v) == NULL for v in a[name].flat),
                    'index outside pool: '+name)
        for name in ('c.id', 'c.support'):
            indexes(name, ids, True)
        for name in ('f.id', 's.id', 's.blob'):
            indexes(name, ids)
        indexes('c.q', rationals, True); indexes('f.q', rationals); indexes('f.vertex', rationals)
        indexes('c.tag', len(a['tag.offset'])-1); indexes('f.tag', len(a['tag.offset'])-1)
        indexes('c.face', f); indexes('f.owner', c)
        for name in self._grids:
            indexes(name+'.q', rationals)
        if self._required:
            indexes('required.face', f)
        for i in range(len(a['tag.offset'])-1):
            start, end = map(int, a['tag.offset'][i:i+2])
            require(end-start <= MAX_TAG_BYTES, 'row annotation exceeds bound')
        require(len({sha256(_raw_view(a['tag.bytes'][int(start):int(end)])).digest()
                     for start, end in zip(a['tag.offset'][:-1], a['tag.offset'][1:])}) == len(a['tag.offset'])-1,
                'duplicate annotation pool entry')
        for row in a['f.cart']:
            require(int(row[0]) < ids and int(row[1]) < ids and int(row[2]) < 3 and
                    int(row[3]) < 2 and int(row[4]) < rationals, 'invalid Cartesian support index')
        require(all(len(a[k]) == len(a['s.table']) for k in ('s.id', 's.blob', 's.size')) and
                all(int(v) < len(TABLES) and TABLES[int(v)] in self._tables for v in a['s.table']) and
                all(0 < int(v) <= MAX_SUPPORT_BYTES for v in a['s.size']), 'invalid support inventory')
        previous = None
        for i in range(len(a['s.id'])):
            key = TABLES[int(a['s.table'][i])], self.ident(int(a['s.id'][i]))
            require(previous is None or previous < key, 'support inventory must be unique and sorted')
            previous = key
        for prefix, count in (('c', c), ('f', f)):
            order = a[prefix+'.lookup']
            require(sorted(map(int, order)) == list(range(count)), 'invalid ID lookup permutation')
            keys = [self.cell_id(int(i)) if prefix == 'c' else self.face_id(int(i)) for i in order]
            require(keys == sorted(set(keys)), 'duplicate or unsorted cell/face lookup')
        for i in range(c):
            mask = int(a['c.mask'][i])
            require(mask < 64 and int(a['c.id'][i, 0]) < ids and
                    all(int(v) < rationals for v in a['c.q'][i, :4]), 'invalid cell flags/ID/metric')
            for bit in (0, 1):
                require((int(a['c.id'][i, bit+1]) != NULL) == bool(mask & (1 << bit)),
                        'cell optional ID mask differs')
            for bit, start, count in ((2, 4, 2), (3, 6, 1), (4, 7, 3)):
                require(all((int(v) != NULL) == bool(mask & (1 << bit)) for v in a['c.q'][i, start:start+count]),
                        'cell optional metric mask differs')
            row = self.cell(i)
            require(set(row.value) <= CELL_FIELDS, 'unknown cell annotation field')
            support = row.value.get('physical_support')
            if support is not None:
                require(set(support) in ({'voxel_id'}, {'voxel_id', 'radial_layer_id', 'cone_id'},
                        {'differential_support_id', 'logical_cell_id'}), 'invalid physical support references')
                for field, table in zip(SUPPORT_KEYS[:4], TABLES):
                    if field in support:
                        self._support_position(table, support[field])
            else:
                require(all(int(v) == NULL for v in a['c.support'][i]), 'hidden support reference without flag')
        for i in range(f):
            mask = int(a['f.mask'][i])
            require(mask < 4, 'invalid face flags')
            require(1 <= int(a['f.owner_offset'][i+1]-a['f.owner_offset'][i]) <= 2 and
                    int(a['f.vertex_offset'][i+1]-a['f.vertex_offset'][i]) >= 3,
                    'invalid face ownership or polygon size')
            require(bool(mask & 1) or a['f.cart_offset'][i] == a['f.cart_offset'][i+1],
                    'hidden Cartesian support without flag')
            cut = a['f.cut'][i]
            require((int(cut[0]) < ids and int(cut[1]) < 3 and int(cut[2]) < 2) if mask & 2
                    else all(int(v) == NULL for v in cut), 'invalid reservoir-cut mask or index')
            row = self.face(i)
            require(set(row.value) <= FACE_FIELDS, 'unknown face annotation field')
        header_owner = self.header()
        header = header_owner.value
        require(set(header) <= HEADER_FIELDS and header.get('schema') == LEGACY and header.get('method') == METHOD,
                'unsupported scientific header')
        _ = scan_owner

    def ident(self, index):
        require(type(index) is int and 0 <= index < len(self._arrays['id.bytes']), 'ID index outside pool')
        return self._arrays['id.bytes'][index].tobytes().hex()

    def integer(self, index):
        require(type(index) is int and 0 <= index < len(self._arrays['int.sign']), 'integer index outside pool')
        a = self._arrays
        start, end = map(int, a['int.offset'][index:index+2])
        return int(a['int.sign'][index])*int.from_bytes(a['int.bytes'][start:end], 'little')

    def rational(self, index):
        require(type(index) is int and 0 <= index < len(self._arrays['q.pair']), 'rational index outside pool')
        n, d = (self.integer(int(v)) for v in self._arrays['q.pair'][index])
        return Fraction(n, d)

    def _pair(self, index):
        q = self.rational(int(index))
        return [hex(q.numerator), hex(q.denominator)]

    def _tag(self, index):
        start, end = map(int, self._arrays['tag.offset'][index:index+2])
        raw = self._arrays['tag.bytes'][start:end].tobytes()
        value = json.loads(raw)
        require(type(value) is dict and canonical(value) == raw, 'noncanonical row annotation')
        return value

    def _tag_charge(self, index):
        start, end = map(int, self._arrays['tag.offset'][index:index+2])
        return _decode_charge(self._arrays['tag.bytes'][start:end])+end-start

    def _range(self, name, index):
        return slice(*map(int, self._arrays[name][index:index+2]))

    def _row_owner(self, qindexes=(), extra=0):
        # Hex strings plus Python exact integers/Fractions and the row's lists.
        size = 65536+extra
        for index in qindexes:
            if int(index) != NULL:
                for integer in self._arrays['q.pair'][int(index)]:
                    start, end = map(int, self._arrays['int.offset'][int(integer):int(integer)+2])
                    size += 32*(end-start+64)
        return _view_allocation(self, size)

    def cell_id(self, index):
        require(type(index) is int and 0 <= index < self.cell_count, 'cell index outside table')
        return self.ident(int(self._arrays['c.id'][index, 0]))

    def face_id(self, index):
        require(type(index) is int and 0 <= index < self.face_count, 'face index outside table')
        return self.ident(int(self._arrays['f.id'][index]))

    def cell(self, index):
        """One exact legacy-shaped row, not a materialised cells table."""
        ident = self.cell_id(index)
        a, mask = self._arrays, int(self._arrays['c.mask'][index])
        linked = self._range('c.face_offset', index)
        owner = self._row_owner(a['c.q'][index], 512*(linked.stop-linked.start)+self._tag_charge(int(a['c.tag'][index])))
        value = self._tag(int(a['c.tag'][index]))
        require(set(value) <= CELL_TAGS, 'unknown cell annotation')
        value.update(cell_id=ident, volume_m3=self._pair(a['c.q'][index, 0]),
            centroid_m=[self._pair(v) for v in a['c.q'][index, 1:4]],
            faces=[[self.face_id(int(i)), int(s)] for i, s in zip(a['c.face'][linked], a['c.sign'][linked])])
        for bit, name in enumerate(('logical_cell_id', 'physical_cell_id')):
            if mask & (1 << bit):
                value[name] = self.ident(int(a['c.id'][index, bit+1]))
        for bit, name, start, count in ((2, 'physical_volume_bounds_m3', 4, 2),
                (3, 'geometry_volume_max_deviation_m3', 6, 1), (4, 'volume_centroid_m', 7, 3)):
            if mask & (1 << bit):
                values = [self._pair(v) for v in a['c.q'][index, start:start+count]]
                value[name] = values[0] if count == 1 else values
        if mask & 32:
            value['physical_support'] = {name: self.ident(int(v)) for name, v in
                zip(SUPPORT_KEYS, a['c.support'][index]) if int(v) != NULL}
        return OwnedRow(value, owner)

    def face(self, index):
        ident = self.face_id(index)
        a, mask = self._arrays, int(self._arrays['f.mask'][index])
        vertices, cart = self._range('f.vertex_offset', index), self._range('f.cart_offset', index)
        # Visit indices without an unfunded list proportional to polygon size.
        qindexes = chain(a['f.q'][index], a['f.vertex'][vertices].flat, a['f.cart'][cart, 4])
        owner = self._row_owner(qindexes, self._tag_charge(int(a['f.tag'][index]))+
                                1024*(vertices.stop-vertices.start+cart.stop-cart.start))
        value = self._tag(int(a['f.tag'][index]))
        require(set(value) <= FACE_TAGS, 'unknown face annotation')
        value.update(face_id=ident, centroid_m=[self._pair(v) for v in a['f.q'][index, :3]],
            area_vector_m2=[self._pair(v) for v in a['f.q'][index, 3:]],
            owners=[self.cell_id(int(v)) for v in a['f.owner'][self._range('f.owner_offset', index)]],
            vertices_m=[[self._pair(v) for v in point] for point in a['f.vertex'][vertices]])
        if mask & 1:
            value['cartesian_support'] = [dict(cell_id=self.ident(int(r[0])), physical_voxel_id=self.ident(int(r[1])),
                axis=int(r[2]), end=int(r[3]), local_coordinate_m=self._pair(r[4])) for r in a['f.cart'][cart]]
        if mask & 2:
            r = a['f.cut'][index]
            value['reservoir_cut'] = dict(cell_id=self.ident(int(r[0])), axis=int(r[1]), end=int(r[2]))
        return OwnedRow(value, owner)

    def cell_metrics(self, index):
        self.cell_id(index)
        a = self._arrays
        linked = self._range('c.face_offset', index)
        owner = self._row_owner(a['c.q'][index, :4], 64*(linked.stop-linked.start))
        return OwnedRow(dict(cell_id=self.cell_id(index), volume=self.rational(int(a['c.q'][index, 0])),
            centre=tuple(self.rational(int(q)) for q in a['c.q'][index, 1:4]),
            face_indices=tuple(map(int, a['c.face'][linked])), signs=tuple(map(int, a['c.sign'][linked]))), owner)

    def face_metrics(self, index):
        self.face_id(index)
        a = self._arrays
        owner = self._row_owner(a['f.q'][index])
        return OwnedRow(dict(face_id=self.face_id(index), centre=tuple(self.rational(int(q)) for q in a['f.q'][index, :3]),
            normal=tuple(self.rational(int(q)) for q in a['f.q'][index, 3:]),
            owners=tuple(map(int, a['f.owner'][self._range('f.owner_offset', index)]))), owner)

    def _support_position(self, table, ident):
        require(table in self._tables, 'support table absent')
        _sha(ident)
        a, low, high = self._arrays, 0, len(self._arrays['s.id'])
        wanted = table, ident
        while low < high:
            middle = (low+high)//2
            found = TABLES[int(a['s.table'][middle])], self.ident(int(a['s.id'][middle]))
            if found < wanted:
                low = middle+1
            else:
                high = middle
        require(low < len(a['s.id']) and (TABLES[int(a['s.table'][low])], self.ident(int(a['s.id'][low]))) == wanted,
                'physical support ID absent from authenticated inventory')
        return low

    def _support_blob(self, index):
        a = self._arrays
        size, ident = int(a['s.size'][index]), self.ident(int(a['s.blob'][index]))
        owner = _view_allocation(self, 2*size+65536)
        self._check()
        raw = self._reader(ident, size)
        require(type(raw) is bytes and len(raw) == size and sha256(raw).hexdigest() == ident,
                'support blob length/hash differs')
        decoded_owner = _view_allocation(self, _decode_charge(raw))
        value = json.loads(raw)
        require(canonical(value) == raw, 'support blob is not canonical')
        return raw, OwnedRow(value, (owner, decoded_owner))

    def support(self, table, ident):
        """Decode only the named support; no retained decoded-support cache."""
        if hasattr(self._reader, 'export'):
            from content_cache import ChargeSpec
            index = self._support_position(table, ident)
            held = self._reader.export(index)
            return self._scope.reserve(ChargeSpec('mesh-support-borrow', 0)).commit(
                held.value, dependencies=(held, self._owner))
        return self._support_blob(self._support_position(table, ident))[1]

    def iter_legacy_json(self, *, encode=canonical):
        """Explicit streamed hash/export: only one complete row/support at once."""
        header_owner = self.header()
        header = header_owner.value
        keys = set(header) | {'cells', 'faces', 'support_tables'} | set(self._grids)
        if self._required:
            keys.add('required_thermal_boundary_faces')
        yield b'{'
        for at, name in enumerate(sorted(keys)):
            self._check()
            if at:
                yield b','
            yield encode(name)
            yield b':'
            if name in header:
                yield encode(header[name])
            elif name in ('cells', 'faces'):
                yield b'['
                count, load = (self.cell_count, self.cell) if name == 'cells' else (self.face_count, self.face)
                for index in range(count):
                    if index:
                        yield b','
                    held = load(index)
                    yield encode(held.value)
                    del held
                yield b']'
            elif name == 'support_tables':
                yield b'{'
                for ti, table in enumerate(self._tables):
                    if ti:
                        yield b','
                    yield encode(table)
                    yield b':{'
                    first = True
                    for index in range(len(self._arrays['s.id'])):
                        if TABLES[int(self._arrays['s.table'][index])] != table:
                            continue
                        if not first:
                            yield b','
                        first = False
                        yield encode(self.ident(int(self._arrays['s.id'][index])))
                        yield b':'
                        if hasattr(self._reader, 'iter_json'):
                            with self._reader.iter_json(index) as stream:
                                for held in stream:
                                    with held:
                                        yield held.value
                        else:
                            raw, held = self._support_blob(index)
                            yield raw
                            del raw, held
                    yield b'}'
                yield b'}'
            elif name == 'required_thermal_boundary_faces':
                yield b'['
                for index, value in enumerate(self._arrays['required.face']):
                    if index:
                        yield b','
                    yield encode(self.face_id(int(value)))
                yield b']'
            else:
                yield b'['
                for axis in range(3):
                    if axis:
                        yield b','
                    yield b'['
                    for index, value in enumerate(self._arrays[name+'.q'][self._range(name+'.offset', axis)]):
                        self._check()
                        if index:
                            yield b','
                        grid_owner = self._row_owner((value,))
                        yield encode(self._pair(value))
                        del grid_owner
                    yield b']'
                yield b']'
        yield b'}'

    def legacy_record(self):
        """Explicit diagnostic export ONLY; deliberately charges full expansion."""
        size = sum(len(part) for part in self.iter_legacy_json())
        owner = _view_allocation(self, 2*size+65536)
        raw = b''.join(self.iter_legacy_json())
        decoded_owner = _view_allocation(self, _decode_charge(raw))
        return OwnedRow(json.loads(raw), (owner, decoded_owner))


class _OwnedArray(np.ndarray):
    """A bounded slice retains its actual charged source, including escapes."""
    def __array_finalize__(self, source):
        self._held = getattr(source, '_held', None)


class SegmentColumn:
    """Numpy-shaped bounded reads, sharing WP2's authenticated page cache."""
    def __init__(self, columns, name, descriptor):
        self.columns, self.name = columns, name
        self.dtype, self.shape = np.dtype(descriptor['dtype']), tuple(descriptor['shape'])
        self.ndim = len(self.shape)
        self.size = math.prod(self.shape)
        self.nbytes = self.size*self.dtype.itemsize

    def __len__(self):
        return self.shape[0]

    def _flat_value(self, index):
        return self.columns.value(self.name, index)

    def _range_read(self, start, stop, shape):
        # Share the generic verified owned-range path for both cache hits and
        # direct reads; numpy never receives an unowned borrowed byte slice.
        held = self.columns.raw(self.name, start, stop)
        result = np.frombuffer(held.value, dtype=self.dtype).reshape(shape).view(_OwnedArray)
        result._held = held
        return result

    def __getitem__(self, key):
        if isinstance(key, tuple):
            require(len(key) == 2 and self.ndim == 2, 'unsupported mesh column selection')
            first, second = key
            if type(first) is int and type(second) is int:
                first = first if first >= 0 else len(self)+first
                second = second if second >= 0 else self.shape[1]+second
                require(0 <= first < len(self) and 0 <= second < self.shape[1], 'column index outside range')
                return self._flat_value(first*self.shape[1]+second)
            # A selected row or CSR block is bounded by its owning read.
            return self[first][(..., second)]
        if isinstance(key, (int, np.integer)):
            index = int(key)
            index = index if index >= 0 else len(self)+index
            if not 0 <= index < len(self):
                raise IndexError(index)
            if self.ndim == 1:
                return self._flat_value(index)
            width = math.prod(self.shape[1:])
            return self._range_read(index*width, (index+1)*width, self.shape[1:])
        require(isinstance(key, slice), 'mesh column needs a bounded integer/slice')
        start, stop, step = key.indices(len(self))
        require(step == 1, 'strided mesh column read refused')
        width = math.prod(self.shape[1:])
        return self._range_read(start*width, stop*width, (max(0, stop-start), *self.shape[1:]))

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]

    @property
    def flat(self):
        for index in range(self.size):
            yield self._flat_value(index)


class DerivedSupportColumn:
    """Virtual compatibility columns; differential hashes/lengths are not stored twice."""
    dtype = np.dtype('<u8')
    ndim = 1

    def __init__(self, count, read):
        self.shape, self.size, self.nbytes = (count,), count, count*8
        self._read = read

    def __len__(self):
        return self.size

    def __getitem__(self, index):
        require(type(index) is int and 0 <= index < self.size, 'support index outside inventory')
        return self._read(index)

    def __iter__(self):
        for index in range(self.size):
            yield self[index]

    @property
    def flat(self):
        return iter(self)


def mesh_from_segment(segment, metadata, arrays, reader, *, check=lambda: None):
    """Cold v3 admission: authenticate all columns and exactly one logical stream."""
    from compact_contracts import LogicalIdentity
    from content_cache import ChargeSpec
    scope = segment.scope
    require(type(metadata) is dict and metadata.get('schema') == SCHEMA,
            'supported mesh codec required')
    require(set(metadata) == {'schema', 'geometry_id', 'header', 'grid_fields', 'support_tables',
            'required_faces_present', 'cell_count', 'face_count', 'arrays'}, 'mesh metadata fields differ')
    require(set(arrays) == set(metadata['arrays']), 'complete virtual mesh columns required')
    raw = canonical(metadata)
    require(len(raw) <= 4*MAX_HEADER_BYTES, 'mesh metadata exceeds bounded header')
    owner = scope.reserve(ChargeSpec('mesh-segment-view', 8*len(raw)+65536)).commit(
        raw, dependencies=(segment._owner, reader.owner))
    view = object.__new__(CompactMesh)
    view._metadata, view._scope, view._owner, view._segment = raw, scope, owner, segment
    view._budget, view._reader, view._check = scope.run_budget, reader, check
    view._arrays = MappingProxyType(arrays)
    view.geometry_id, view._header = metadata['geometry_id'], canonical(metadata['header'])
    view.cell_count, view.face_count = metadata['cell_count'], metadata['face_count']
    view._grids, view._tables = tuple(metadata['grid_fields']), tuple(metadata['support_tables'])
    view._required = metadata['required_faces_present']
    view._sealed = False
    # Accept the completed view only after both immutable sources pass their
    # closing freshness check. Scalars keep cancellation checks within this
    # single bounded, paid internal read operation.
    with arrays['id.bytes'].columns.read_batch(), reader.source._partition.record._read_batch():
        view._validate()
        found, length = sha256(), 0
        for part in view.iter_legacy_json():
            check(); found.update(part); length += len(part)
    identity = LogicalIdentity(LEGACY, found.hexdigest(), length)
    require(identity == segment.info.ref.identity and identity.sha256 == view.geometry_id,
            'streamed original geometry identity differs')
    view._logical_identity = identity
    view._sealed = True
    return view


class _PublishedSupports:
    """Support reads of a produced mesh after its own v3 publication.

    Reads stay on the producer's in-memory static table and partition
    references, exactly as before publication; nothing walks the candidate.
    ``source`` is the partition support source the publication verified, and
    ``owner`` is the produced view's owner, so a close of the bound view
    releases the in-memory columns once (CompactMesh.close, segment branch).
    """
    __slots__ = ('arrays', 'owner', 'read', 'segment', 'source', 'static')

    def __init__(self, read, source, owner):
        self.read, self.source, self.owner = read, source, owner
        self.arrays = self.segment = self.static = None

    def __call__(self, ident, size):
        return self.read(ident, size)


def bind_published(view, segment, source, *, check=lambda: None):
    """The produced in-memory mesh, bound to the v3 segment it was published as.

    Same-interval reads then use the very columns that CompactMesh.__init__
    validated and streamed, never a per-scalar walk of the unsealed candidate
    (mesh_from_segment's cold admission). The caller has compared the segment
    root with this view. The stored bytes are hashed by bounded_preseal before
    the seal, and the sealed file is validated in full by the fresh reader.
    """
    from content_cache import ChargeSpec
    from support_source import SupportSource
    require(type(view) is CompactMesh and getattr(view, '_sealed', False) and view._segment is None and
            view._scope is not None and view._scope is segment.scope and view._owner is not None,
            'sealed same-scope produced mesh required')
    require(type(source) is SupportSource and source.scope is view._scope,
            'published mesh support source has foreign scope')
    require(segment.info.ref.identity == view.identity(), 'published mesh identity differs from the produced mesh')
    reader = _PublishedSupports(view._reader, source, view._owner)
    owner = view._scope.reserve(ChargeSpec('mesh-published-view', 4096)).commit(
        None, dependencies=(segment._owner, view._owner))
    bound = object.__new__(CompactMesh)
    for name in ('_metadata', '_budget', '_arrays', 'geometry_id', '_header', 'cell_count', 'face_count',
                 '_grids', '_tables', '_required', '_scope', '_logical_identity'):
        setattr(bound, name, getattr(view, name))
    bound._owner, bound._segment, bound._reader, bound._check = owner, segment, reader, check
    bound._sealed = True
    return bound
