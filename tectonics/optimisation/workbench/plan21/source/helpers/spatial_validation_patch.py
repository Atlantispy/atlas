"""Bounded compact inputs for the unchanged spatial acceptance equations.

These opt-in, exact source transforms do not edit a frozen runtime. Graphs
never become dictionaries: their identity is streamed and their cells are
visited one charged row at a time. r2: a transport, dual audit or stock
object wider than LAZY_MIN_BYTES is streamed (_Lazy/_Vector), its snapshot
identity hashed from canonical bytes; smaller ones keep the explicit 32 MiB
(transport) or 4 MiB whole export. Legacy dictionaries keep their routes.

WP7 must apply joined_source/context_source to its selected helper successors
and adapt the cold bridge plus restored binding restore/validate_for seams.
This component does not claim full cold-checkpoint compatibility by itself.
"""
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager, nullcontext
import ast
import gc
import json
import re

from compact_contracts import ContractError
from record_views import RecordRef
import record_views as _RV
from atlas_tectonics.resources import MemoryLimitError

SMALL_BYTES = 4 << 20
ROW_BYTES = 4 << 20
TRANSPORT_BYTES = 32 << 20
_GRAPH_FIELDS = frozenset(('graph', 'spatial_graph', 'finite_proposal', 'joined_heat_plan'))
_MARKER = '\nimport spatial_validation_patch as _SV  # compact validation r1\n'

# Streamed exact containers (r2). Objects named here, when their canonical
# logical width exceeds LAZY_MIN_BYTES, are never exported whole: the native
# equations read scalars, bounded small fields, single vector elements and
# one bounded vector at a time. Smaller objects keep the exact r1 whole export.
# None of these widens an export cap: every decode stays within SMALL_BYTES or
# ROW_BYTES, and TRANSPORT_BYTES remains the cap of the whole-export route.
_LAZY_FIELDS = frozenset(('transport', 'dual_measure_audit', 'stocks'))
LAZY_MIN_BYTES = 65536
VECTOR_MIN_BYTES = 4096
VECTOR_WHOLE_BYTES = 512 << 10
KEYED_OBJECT_KEYS = 256
_STRING = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"')
_TOKEN = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"|[\[\]{},]')
_STRIP = re.compile(rb'"[^"\\]*(?:\\.[^"\\]*)*"')
_NUMBER = re.compile(rb'-?[0-9][0-9.eE+-]*')


def is_record(value):
    return type(value) is dict or isinstance(value, _Object) or (
        isinstance(value, RecordRef) and value.kind == 'object')


def is_state_record(value):
    if type(value) is dict:
        return True
    from spatial_records_patch import _OwnedDict
    from spatial_indexed_patch import _LogicalRecord
    if type(value) is _OwnedDict:
        if not value._owners:
            return False
        for owner in value._owners:
            owner.value  # Closed backing must refuse before native validation.
        return True
    return type(value) is _LogicalRecord and value._allocation._guard is not None


def _reference(value):
    return value.ref if isinstance(value, _Object) else value


class _Object:
    """Validator-local, non-Mapping accessor; no keys/items/full decode API.

    Only the finite set of fields explicitly requested by the native validator
    is retained. Its scope owns every exported value until that validator ends.
    Cells use a separate row lifetime and are never cached as decoded lists.
    """
    def __init__(self, ref, stack):
        self.ref, self.stack, self.cache = ref, stack, {}

    def __contains__(self, key):
        try:
            child = self.ref.field(key)
        except KeyError:
            return False
        child.close()
        return True

    def __getitem__(self, key):
        if key in self.cache:
            return self.cache[key]
        child = self.ref.field(key)
        self.stack.callback(child.close)
        value = self._convert(key, child)
        self.cache[key] = value
        return value

    def _convert(self, key, child):
        kind = child.kind
        if key in _GRAPH_FIELDS and kind == 'object':
            return _Object(child, self.stack)
        if key == 'cells' and kind == 'array':
            return _Rows(child)
        # Subclasses outside this module (live_spatial_patch) keep the r1
        # whole-field exports their own consumers expect.
        if (type(self) is _Object and key in _LAZY_FIELDS and kind == 'object' and
                child._logical_length() > LAZY_MIN_BYTES):
            return _Lazy(child, self.stack)
        return self._export(child, TRANSPORT_BYTES if key == 'transport' else SMALL_BYTES)

    def _export(self, child, limit):
        owned = (child.scalar(max_owned_bytes=limit) if child.kind == 'scalar'
                 else child.export(max_logical_bytes=limit, max_owned_bytes=limit))
        self.stack.enter_context(owned)
        return owned.value

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


class _Rows:
    """Reiterable row source with at most one decoded row in flight."""
    def __init__(self, ref):
        self.ref = ref

    def __len__(self):
        return self.ref.size

    def __iter__(self):
        with self.ref.iter_rows(max_rows=1, max_owned_bytes=ROW_BYTES) as stream:
            for block in stream:
                with block:
                    row = block.value[0]
                    try:
                        decoded = row.export(max_logical_bytes=ROW_BYTES,
                                             max_owned_bytes=ROW_BYTES)
                        # A caller's loop variable (including a failed
                        # traceback) owns the decoded row beyond generator
                        # resumption. Never credit that backing at yield end.
                        value = _OwnedRow(decoded.value, decoded)
                        yield value
                        value = decoded = None
                    finally:
                        row.close()


class _OwnedRow(dict):
    def __init__(self, value, owner):
        super().__init__(value)
        self._owned = owner


class _Lazy(_Object):
    """Streamed exact object (r2) for transport, dual audits and stocks.

    It answers the read protocol the unchanged native equations use on these
    containers: item access, get/in, len, iteration, keys/values/items and
    exact equality with dictionaries or other streamed objects (Python dict
    semantics, never canonical-byte shortcuts). Large child objects stay
    streamed, large arrays become _Vector, small fields are bounded exports
    owned by the validator scope. Objects with many keys are read one decoded
    entry at a time from their canonical stream.
    """
    __hash__ = None

    def __init__(self, ref, stack):
        super().__init__(ref, stack)
        self._names = None
        # W3 (Decision 3): (arrays head bytes, snapshot identity) teed from the
        # exchange identity stream; snapshot() uses it only on an equal head.
        self._tee = None

    def _convert(self, key, child):
        kind = child.kind
        if kind == 'object' and child._logical_length() > LAZY_MIN_BYTES:
            return _Lazy(child, self.stack)
        # Two-element arrays are exact rational pairs, which native decoders
        # (_q) require as plain lists, so they are always exported.
        if kind == 'array' and child.size > 2 and child._logical_length() > VECTOR_MIN_BYTES:
            return _Vector(child)
        return self._export(child, SMALL_BYTES)

    def __len__(self):
        return self.ref.size

    def _keyed(self):
        return self.ref.size <= KEYED_OBJECT_KEYS

    def _key_names(self):
        if self._names is None:
            owned = self.ref.keys(max_owned_bytes=SMALL_BYTES)
            self.stack.enter_context(owned)
            self._names = owned.value
        return self._names

    def keys(self):
        if self._keyed():
            return iter(self._key_names())
        return (key for key, _ in _object_entries(self.ref))

    __iter__ = keys

    def items(self):
        if self._keyed():
            return ((key, self[key]) for key in self._key_names())
        return _object_entries(self.ref)

    def values(self):
        return (value for _, value in self.items())

    def __eq__(self, other):
        if isinstance(other, _Lazy):
            if len(self) != len(other):
                return False
            if self._keyed():
                names = self._key_names()
                # Both inventories are canonical (sorted), so equal key sets
                # are equal tuples; values compare with dict semantics.
                return names == other._key_names() and all(_equal(self[k], other[k]) for k in names)
            # Entry streams are always consumed to their end (see _object_entries).
            result = True
            for a, b in zip(self.items(), other.items(), strict=True):
                result = result and a[0] == b[0] and _equal(a[1], b[1])
            return result
        if isinstance(other, dict):
            if len(self) != len(other):
                return False
            result = True
            for key, value in self.items():
                result = result and key in other and _equal(value, other[key])
            return result
        return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result


class _Vector:
    """Streamed exact array (r2): len, single-element reads, bounded iteration.

    An element read decodes one element under ROW_BYTES; iteration decodes the
    whole vector once under SMALL_BYTES (above VECTOR_WHOLE_BYTES logical
    bytes it reads element by element). Decoded values are plain JSON values;
    values a native equation keeps belong to that equation's own workspace.
    """
    __hash__ = None

    def __init__(self, ref):
        self.ref = ref

    def __len__(self):
        return self.ref.size

    def __getitem__(self, index):
        if type(index) is not int:
            if isinstance(index, slice):
                raise ContractError('streamed exact vectors do not export slices')
            raise TypeError('list indices must be integers or slices, not '+type(index).__name__)
        size = self.ref.size
        position = index+size if index < 0 else index
        if not 0 <= position < size:
            raise IndexError('list index out of range')
        child = self.ref.at(position)
        try:
            owned = (child.scalar(max_owned_bytes=ROW_BYTES) if child.kind == 'scalar'
                     else child.export(max_logical_bytes=ROW_BYTES, max_owned_bytes=ROW_BYTES))
        finally:
            child.close()
        value = owned.value
        owned.close()
        return value

    def __iter__(self):
        if self.ref._logical_length() > VECTOR_WHOLE_BYTES:
            for position in range(self.ref.size):
                yield self[position]
            return
        owned = self.ref.export(max_logical_bytes=SMALL_BYTES, max_owned_bytes=SMALL_BYTES)
        try:
            yield from owned.value
        finally:
            owned.close()

    def __eq__(self, other):
        if isinstance(other, (_Vector, list)):
            return len(self) == len(other) and all(
                _equal(a, b) for a, b in zip(self, other, strict=True))
        return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result


def _equal(left, right):
    """Python equality where either side may be a streamed container."""
    if isinstance(left, (_Lazy, _Vector)):
        result = left.__eq__(right)
    elif isinstance(right, (_Lazy, _Vector)):
        result = right.__eq__(left)
    else:
        return left == right
    return False if result is NotImplemented else result


def _decoded_estimate(raw):
    """Admission for json.loads of one canonical ASCII entry, before decoding.

    Counted from syntax (CPython 3.12): 56 B per string plus its characters,
    16 B per escaped code unit (wider string headers), 96 B per list, 232 B per
    object plus 64 B per member, 9 B per element slot, 40 B per number plus its
    digits. Measured against tracemalloc in test_wp6_streamed_validation.
    """
    stripped, strings = _STRIP.subn(b'', raw)
    numbers = _NUMBER.findall(stripped)
    slots = stripped.count(b',')+stripped.count(b'[')+stripped.count(b'{')
    return (4096+56*strings+(len(raw)-len(stripped))+16*raw.count(b'\\u')+
            96*stripped.count(b'[')+232*stripped.count(b'{')+64*stripped.count(b':')+
            9*slots+sum(40+len(n) for n in numbers))


def _value_end(text, start):
    """Index of the ',' or '}' ending the value at start, or None if incomplete."""
    depth, last = 0, start
    for match in _TOKEN.finditer(text, start):
        if '"' in text[last:match.start()]:
            return None  # an unterminated string continues in a later chunk
        token, last = match.group(), match.end()
        if token[0] == '"':
            continue
        if token in '[{':
            depth += 1
        elif token in ']}':
            if not depth:
                return match.start()
            depth -= 1
        elif not depth:
            return match.start()
    return None


def _object_entries(ref):
    """Decoded (key, value) entries of a canonical object, one at a time.

    The text buffer holds at most one entry plus one stream chunk and refuses
    an entry wider than ROW_BYTES. Buffer and entry decode are charged to the
    run budget before allocation; an entry's charge is held while it is
    yielded and released when the consumer advances.
    """
    from record_tables import Scratch
    budget = ref.scope.run_budget
    text, at, done, scratch = '', 0, False, None
    with ref.iter_json() as stream:
        blocks = iter(stream)

        def fill():
            nonlocal text, at, done, scratch
            if done:
                return False
            for block in blocks:
                with block:
                    rest = text[at:]
                    if len(rest) > ROW_BYTES:
                        raise ContractError('streamed object entry exceeds row bound')
                    scratch = None
                    scratch = Scratch(budget, 4096+2*(len(rest)+len(block.value)))
                    text, at = rest+block.value.decode('ascii'), 0
                return True
            done = True
            return False

        while not text and fill():
            pass
        if text[:1] != '{':
            raise ContractError('streamed exact container is not an object')
        at, first = 1, True
        while True:
            while at >= len(text):
                if not fill():
                    raise ContractError('streamed object ended inside an entry')
            if first and text[at] == '}':
                return
            first = False
            while True:
                key = _STRING.match(text, at)
                end = (_value_end(text, key.end()+1) if key is not None and key.end() < len(text)
                       else None)
                if end is not None:
                    break
                if not fill():
                    raise ContractError('streamed object entry is incomplete')
            if text[key.end()] != ':' or text[end] not in ',}':
                raise ContractError('streamed object entry is not canonical')
            key_raw, value_raw, separator = key.group(), text[key.end()+1:end], text[end]
            held = Scratch(budget, _decoded_estimate((key_raw+value_raw).encode('ascii')))
            name, value = json.loads(key_raw), json.loads(value_raw)
            at = end+1
            yield name, value
            del name, value, held
            if separator == '}':
                # Finish the canonical stream so composed child streams close
                # in order (an abandoned stream is only retired by GC).
                for block in blocks:
                    with block:
                        if block.value:
                            raise ContractError('streamed object has trailing bytes')
                return


def copy_row(value, **changes):
    if type(value) is not _OwnedRow:
        return dict(value, **changes)
    from content_cache import ChargeSpec
    with value._owned.scope.reserve(ChargeSpec('spatial-row-copy', 4096+256*(len(value)+len(changes))),
                                   required=True) as reservation:
        owner = reservation.commit(None, dependencies=(value._owned,))
    return _OwnedRow(dict(value, **changes), owner)


def rows(value):
    return _Rows(value) if isinstance(value, RecordRef) else value


class _AppendedRows:
    def __init__(self, original):
        self.original, self.added = rows(original), []

    def append(self, row):
        self.added.append(row)

    def __len__(self):
        return len(self.original)+len(self.added)

    def __iter__(self):
        yield from self.original
        yield from self.added


def appendable_rows(value):
    return _AppendedRows(value) if isinstance(value, RecordRef) else list(value)


# D1-B: an interval's carried start holds an index of
# its compact rows, never every decoded row at once. Interval two carries about
# 3,388 rows; held together with honest row booking (about 98 KB each) they book
# about 333 MB against the 256 MiB retained scope while real memory is about
# 60 MB, and interval three exceeds the scope even with exact booking. Index
# booking per entry (CPython 3.12, checked against tracemalloc in
# test_d1b_carried_start): the key string's object header (49 B), its integer
# position (28 B) and a string-keyed dict slot with its index bytes at their
# largest just after a resize (about 34 B measured, 48 B booked), plus the
# key's canonical length. A carried entry books only a slot: its key string
# and position are shared with the geometry mapping and the start index. Both
# indexes stay well under 1 MB at interval two.
_INDEX_FIXED = 4096
_INDEX_ROW = 128
_CARRIED_ROW = 48
_MISSING = object()


def _key_value(field):
    """The exact decoded key: a scalar, or a container that the index then refuses."""
    owned = (field.scalar(max_owned_bytes=SMALL_BYTES) if field.kind == 'scalar' else
             field.export(max_logical_bytes=SMALL_BYTES, max_owned_bytes=SMALL_BYTES))
    with owned:
        return owned.value


# S3 (backlog item 12, 16 Oct 2026): a carried row read by item exports only
# the fields read. The owner's close_graph reads one field of every carried row
# per pass (volume_m3; geometry_volume_error_m3; exact[name]) and its transport
# reads prior rows' volume_m3, while a whole-row export decodes every field
# (IV1: 0.253 ms a row; volume_m3 alone 0.126 ms, exact[name] 0.186 ms). get()
# keeps the whole row: transport reads a row's volume and all of its exact
# values, which one whole export serves more cheaply than single fields.
_ROW_FIELDS = frozenset(('volume_m3', 'geometry_volume_error_m3'))


def _field_value(field):
    """One field's exact decoded value, or _MISSING when the whole row must answer.

    Called only for an admitted row. A container field is exported under the
    row's bounds: its stats and largest scalar are at most the whole row's, so
    its export refuses only where the whole row's would. scalar() books the
    pack-time charge of a text or hex scalar (4096 + 16 bytes a character),
    above the export's model, so when it refuses the whole row answers (r2);
    a budget refusal is answered by the whole row in _LazyRow._field (r3),
    after a collection (r4).
    """
    if field.kind == 'scalar':
        try:
            owned = field.scalar(max_owned_bytes=ROW_BYTES)
        except ContractError:
            return _MISSING
    else:
        owned = field.export(max_logical_bytes=ROW_BYTES, max_owned_bytes=ROW_BYTES)
    with owned:
        return owned.value


def _admits(cells, at, bound):
    """Whether row ``at`` passes the whole-row export's refusals before decode (S3 r2).

    record_views._export_ref at max_logical_bytes = max_owned_bytes = bound,
    without its decode: the logical width, then the same funded decoded-object
    stats walk (small or large route, with its cap refusal), then the charge
    that export books. A failed walk retains its booking with its traceback,
    just as export does; successful walks release it before field export.
    """
    with cells.at(at) as ref:
        length = ref._logical_length()
        if length > bound:
            return False
        scratch = _RV.T.Scratch(ref.scope.run_budget, 65536+256*256+_RV.T.MAX_DEPTH*1024)
        small = type(ref) in (RecordRef, _RV.LogicalRecord, _RV.LogicalExchange) and length <= 32768
        access = ref._view._access() if small else None
        refused = False
        try:
            with ref._view._read_batch():
                decoded, scalar = (_RV._node_stats(ref._view, ref.index, bound, {}, access=access) if small else
                                   _RV._decoded_stats(ref, bound, {}))
        except ContractError:
            refused = True
        if refused:
            # Collect unreachable failure frames while their workspace is still
            # funded. Return releases scratch only if no traceback retains it.
            gc.collect()
            return False
        del scratch
    charge = 65536+decoded+_RV._SCALAR_DECODE_FACTOR*scalar+min(4*scalar, _RV._SCALAR_DECODE_BLOCK)
    return charge+_RV.OWNER_BYTES <= bound


class _LazyRow(Mapping):
    """A carried row read by item: single-field exports, else the whole row (S3).

    row['volume_m3'] and row['geometry_volume_error_m3'] export that field
    alone, and row['exact'][name] exports exact.<name> alone. Each returns the
    value the whole-row export holds there (the same canonical bytes through
    the same JSON decode). Single fields answer only while every row of the
    mapping passes the whole-row export's own refusals (r2:
    _StartRows._fields_admitted); otherwise, and when a field is absent, exact
    is not an object, a scalar's own charge refuses or any budget of the field
    path refuses (r3), the whole row answers, so the value or error is the whole
    row's. A single field therefore answers wherever the whole row answers, with
    the same value. It may answer where only the whole row's own work refuses:
    its larger booking, or decoding a field this read does not touch (the packer
    refuses such values, and issue and restore export whole rows first). Every
    other read (another key, get,
    membership, iteration, length, views, equality, repr) exports the whole
    row once, exactly as before S3 (copy_row for a carried child), and later
    reads use it, so its types, booking and errors are unchanged.
    """
    __slots__ = ('_at', '_child', '_start', '_whole')

    def __init__(self, start, at, child=_MISSING):
        self._start, self._at, self._child, self._whole = start, at, child, None

    def _row(self):
        if self._whole is None:
            whole = self._start._row(self._at)
            self._whole = whole if self._child is _MISSING else copy_row(whole, cell_id=self._child)
        return self._whole

    def _field(self, name, inner=None):
        """row[name], or row[name][inner], from that field alone; _MISSING if the whole row must answer.

        r3: a budget refusal anywhere on this path (the admission walk, the key
        search's scratch, the holders, the field's own charge or export) is
        answered by the whole row. r4: the with blocks release their bookings,
        but on a sealed segment a failed chunk read keeps its leases on the
        error, in a reference cycle (integration_spatial_transport._workspace),
        until a collection. One runs once the error is unreachable, so the whole
        row then answers or refuses with exactly the base's budget
        (CompactRecord._validate's pattern). Only a budget refusal pays for it.
        """
        try:
            if not self._start._fields_admitted():
                return _MISSING
            with self._start._cells.at(self._at) as row, ExitStack() as stack:
                try:
                    field = stack.enter_context(row.field(name))
                    if inner is not None:
                        if field.kind != 'object':
                            return _MISSING
                        field = stack.enter_context(field.field(inner))
                except KeyError:
                    return _MISSING
                return _field_value(field)
        except MemoryLimitError:
            pass  # answered below, once the error and its cycle are unreachable
        gc.collect()
        return _MISSING

    def __getitem__(self, name):
        if self._whole is None and type(name) is str:
            if name in _ROW_FIELDS:
                value = self._field(name)
                if value is not _MISSING:
                    return value
            elif name == 'exact':
                return _LazyExact(self)
        return self._row()[name]

    def get(self, name, default=None):
        return self._row().get(name, default)

    def __contains__(self, name):
        return name in self._row()

    def __iter__(self):
        return iter(self._row())

    def __reversed__(self):
        return reversed(self._row())

    def __len__(self):
        return len(self._row())

    def keys(self):
        return self._row().keys()

    def items(self):
        return self._row().items()

    def values(self):
        return self._row().values()

    def __eq__(self, other):
        return self._row() == (other._row() if type(other) is _LazyRow else other)

    def __repr__(self):
        return repr(self._row())


class _LazyExact(Mapping):
    """row['exact'] of a _LazyRow: [name] exports exact.<name> alone; any other read is the whole row's."""
    __slots__ = ('_parent',)

    def __init__(self, parent):
        self._parent = parent

    def _exact(self):
        return self._parent._row()['exact']

    def __getitem__(self, name):
        if self._parent._whole is None and type(name) is str:
            value = self._parent._field('exact', name)
            if value is not _MISSING:
                return value
        return self._exact()[name]

    def get(self, name, default=None):
        return self._exact().get(name, default)

    def __contains__(self, name):
        return name in self._exact()

    def __iter__(self):
        return iter(self._exact())

    def __reversed__(self):
        return reversed(self._exact())

    def __len__(self):
        return len(self._exact())

    def keys(self):
        return self._exact().keys()

    def items(self):
        return self._exact().items()

    def values(self):
        return self._exact().values()

    def __eq__(self, other):
        return self._exact() == (other._exact() if type(other) is _LazyExact else other)

    def __repr__(self):
        return repr(self._exact())


class _StartRows(Mapping):
    """Exact lazy mapping of compact carried rows by cell id (D1-B).

    Keys keep the native comprehension's order and duplicate rule (a key keeps
    its first position and the last row wins). A row is exported with _Rows's
    bounded row export only when its value is read, and released when its
    reader drops it; membership, length and key iteration never decode a row.
    S3: an item read returns a _LazyRow, which exports only the fields read;
    get() returns the whole row as before. r2: single fields answer only when
    _fields_admitted() (a cached bound and flag, within the fixed index charge).
    Only the index is held, booked on the retained scope before it is built.
    """
    __slots__ = ('_admitted', '_cells', '_index', '_owned')

    def __init__(self, cells):
        from content_cache import ChargeSpec
        size, text = cells.size, 0
        for at in range(size):
            with cells.at(at) as row, row.field('cell_id') as field:
                text += field._logical_length()
        with cells.scope.reserve(ChargeSpec('spatial-start-index', _INDEX_FIXED+_INDEX_ROW*size+text),
                                 required=True) as reservation:
            self._owned = reservation.commit(None)
        index = {}
        for at in range(size):
            with cells.at(at) as row, row.field('cell_id') as field:
                index[_key_value(field)] = at
        self._cells, self._index = cells, index
        self._admitted = None

    def _row(self, at):
        with self._cells.at(at) as row:
            decoded = row.export(max_logical_bytes=ROW_BYTES, max_owned_bytes=ROW_BYTES)
        return _OwnedRow(decoded.value, decoded)

    def _fields_admitted(self):
        """Whether every indexed row passes the whole-row export's refusals at ROW_BYTES (S3 r2).

        Single-field reads answer only then. One row whose whole export would
        refuse sends every read of this mapping to its whole row, which refuses
        or answers exactly as before S3. Checked once per bound, at the first
        single-field read: one stats walk a row, no decode.
        """
        if self._admitted is None or self._admitted[0] != ROW_BYTES:
            self._admitted = (ROW_BYTES, all(_admits(self._cells, at, ROW_BYTES) for at in self._index.values()))
        return self._admitted[1]

    def __getitem__(self, key):
        return _LazyRow(self, self._index[key])

    def get(self, key, default=None):
        # Never Mapping.get: a KeyError raised while decoding a present row must
        # propagate, not read as an absent carried cell.
        at = self._index.get(key, _MISSING)
        return default if at is _MISSING else self._row(at)

    def __contains__(self, key):
        return key in self._index

    def __iter__(self):
        return iter(self._index)

    def __len__(self):
        return len(self._index)


class _CarriedRows(Mapping):
    """Exact identity transfer: child cell id -> its parent row renamed (D1-B).

    Only the child's parent position is recorded; each read exports the parent
    row and returns copy_row(row, cell_id=child), equal to the native
    dict(old, cell_id=child). Insertion order is the native carried order.
    S3: an item read returns a _LazyRow of the parent's position; its whole
    row (any read other than a single field) is that copy_row.
    """
    __slots__ = ('_owned', '_parents', '_start')

    def __init__(self, start):
        from content_cache import ChargeSpec
        # A one-to-one identity carries each parent at most once.
        with start._cells.scope.reserve(ChargeSpec('spatial-carried-index',
                                                   _INDEX_FIXED+_CARRIED_ROW*len(start)),
                                        required=True) as reservation:
            self._owned = reservation.commit(None)
        self._start, self._parents = start, {}

    def _carry(self, child, parent):
        self._parents[child] = self._start._index[parent]

    def __getitem__(self, child):
        return _LazyRow(self._start, self._parents[child], child)

    def get(self, child, default=None):
        at = self._parents.get(child, _MISSING)
        return default if at is _MISSING else copy_row(self._start._row(at), cell_id=child)

    def __contains__(self, child):
        return child in self._parents

    def __iter__(self):
        return iter(self._parents)

    def __len__(self):
        return len(self._parents)


class _LineageRow:
    """A carried parent as the identity check reads it: one exported field (D1-B).

    _carried_start_cells reads only a parent's source_key before carry() keeps
    the parent's position, so a compact start exports that field alone instead
    of the whole row (a whole-row export rebuilds every node's canonical bytes,
    about 1 ms for an interval-1 row).
    """
    __slots__ = ('_at', '_cells')

    def __init__(self, cells, at):
        self._cells, self._at = cells, at

    def __getitem__(self, name):
        with self._cells.at(self._at) as row, row.field(name) as field:
            return _key_value(field)


def lineage_row(previous, parent):
    """The carried parent for the lineage check (None when absent)."""
    if type(previous) is _StartRows:
        at = previous._index.get(parent, _MISSING)
        return None if at is _MISSING else _LineageRow(previous._cells, at)
    return previous.get(parent)


def start_rows(cells):
    """Carried start rows: an index over compact cells (D1-B), else the native comprehension."""
    ref = cells.ref if type(cells) is _Rows else cells
    if isinstance(ref, RecordRef):
        return _StartRows(ref)
    return {row['cell_id']: row for row in cells}


def carried_rows(previous):
    return _CarriedRows(previous) if type(previous) is _StartRows else {}


def carry(carried, child, parent, old):
    """One exact identity child; a compact start keeps only its parent's position."""
    if type(carried) is _CarriedRows:
        carried._carry(child, parent)
    else:
        carried[child] = copy_row(old, cell_id=child)


@contextmanager
def access(*values):
    """Explicit lifetime for requested scalars/fields, never a whole graph."""
    stack = ExitStack()
    converted = tuple(_Object(v, stack) if isinstance(v, RecordRef) else v for v in values)
    try:
        yield converted[0] if len(converted) == 1 else converted
    except BaseException:
        # The failing validation frame can retain raw decoded fields. Keep
        # callbacks/owners reachable through its accessor and this traceback;
        # GC retires them only once the exception is no longer retained.
        raise
    else:
        for value in converted:
            if isinstance(value, _Object) and value.stack is stack:
                value.cache.clear()
        stack.close()


@contextmanager
def transport_access(graph, result):
    """The sole native transport boundary, charged before decoding."""
    ref = _reference(result)
    stack = ExitStack()
    try:
        if isinstance(result, _Lazy):
            pass  # Already streamed and owned by the caller's validator scope.
        elif isinstance(ref, RecordRef) and ref.kind == 'object' and ref._logical_length() > LAZY_MIN_BYTES:
            result = _Lazy(ref, stack)
        elif isinstance(ref, RecordRef):
            owned = stack.enter_context(ref.export(max_logical_bytes=TRANSPORT_BYTES,
                                                   max_owned_bytes=TRANSPORT_BYTES))
            result = owned.value
        graph = stack.enter_context(access(graph))
        yield graph, result
    except BaseException:
        raise
    else:
        stack.close()


def identity(value, ordinary_hash):
    ref = _reference(value)
    return ref.identity().sha256 if isinstance(ref, RecordRef) else ordinary_hash(value)


def excluded_identity(value, excluded, ordinary_hash):
    ref = _reference(value)
    if not isinstance(ref, RecordRef):
        return ordinary_hash({k: v for k, v in value.items() if k not in excluded})
    selected = ref.without(excluded)
    try:
        return selected.identity().sha256
    finally:
        selected.close()


def _arrays_head(fields):
    """The '{"arrays":...}' bytes snapshot() hashes first, from (key, shape, raw)."""
    from hashlib import sha256
    return json.dumps({'arrays': {key: {'shape': shape, 'sha256': sha256(raw).hexdigest()}
                                  for key, shape, raw in fields}},
                      sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def _speculative_head(audit_arrays):
    """Arrays head of the transport fields as given, or None (W3, Decision 3).

    Only plain C-contiguous binary64 arrays are described; anything else
    leaves the snapshot to its unchanged streamed route. snapshot() compares
    this head with the one built from the native snapshot's own fields, so a
    difference only costs the second stream, never an identity.
    """
    import numpy as np
    if type(audit_arrays) is not dict:
        return None
    fields = []
    for key, value in audit_arrays.items():
        if type(key) is not str or not key.startswith('spatial-transport:'):
            continue
        if type(value) is not np.ndarray or value.dtype != np.float64 or not value.flags.c_contiguous:
            return None
        fields.append((key.removeprefix('spatial-transport:'), list(value.shape),
                       b'' if value.size == 0 else value))
    return _arrays_head(fields) if fields else None


def _feed(digests, ref):
    with ref.iter_json() as stream:
        for block in stream:
            with block:
                for digest in digests:
                    digest.update(block.value)


def _feed_key(digests, at, name):
    import record_tables as tables
    for digest in digests:
        if at:
            digest.update(b',')
        for part in tables.string_parts(name):
            digest.update(part)
        digest.update(b':')


def _tee_transport(child, exchange_digest, snapshot_digest):
    """Feed the transport's canonical bytes once into both digests.

    The exchange digest receives every member; the snapshot digest receives
    the transport without result_id, exactly as ref.without(('result_id',))
    streams it ('{' + sorted members + '}'). Returns False, having fed
    nothing, if the key inventory is refused (the caller then streams the
    transport whole, as the unchanged route does).
    """
    import record_tables as tables
    try:
        names = child.keys(max_owned_bytes=tables.MAX_ROW_WORK_BYTES)
    except ContractError:
        return False
    with names:
        exchange_digest.update(b'{')
        snapshot_digest.update(b'{')
        kept = 0
        for at, name in enumerate(names.value):
            _feed_key((exchange_digest,), at, name)
            if name == 'result_id':
                targets = (exchange_digest,)
            else:
                _feed_key((snapshot_digest,), kept, name)
                kept += 1
                targets = (exchange_digest, snapshot_digest)
            with child.field(name) as member:
                _feed(targets, member)
        exchange_digest.update(b'}')
        snapshot_digest.update(b'}')
    return True


def exchange_identity(value, state_id, ordinary_hash, audit_arrays=None):
    ref = _reference(value)
    if not isinstance(ref, RecordRef):
        body = {k: v for k, v in value.items() if k not in ('state_id', 'result_id')}
        return ordinary_hash(dict(state_id=state_id, exchange=body))
    # A public LogicalExchange may be an overlay. The explicit projection also
    # handles a full persisted record and preserves missing/extra-field checks.
    from hashlib import sha256
    import record_tables as tables
    # W3 (Decision 3): a streamed transport that snapshot() hashes again is fed
    # once into both digests. The exchange bytes are unchanged: the body
    # projection streams '{' + sorted members + '}' exactly as fed here.
    lazy = value.cache.get('transport') if isinstance(value, _Object) else None
    head = _speculative_head(audit_arrays) if isinstance(lazy, _Lazy) else None
    body = ref.without(('state_id', 'result_id'))
    try:
        digest = sha256(b'{"exchange":')
        if head is None:
            _feed((digest,), body)
        else:
            snapshot_digest = sha256(head[:-1]+b',"metadata":')
            teed = False
            with body.keys(max_owned_bytes=tables.MAX_ROW_WORK_BYTES) as names:
                digest.update(b'{')
                for at, name in enumerate(names.value):
                    _feed_key((digest,), at, name)
                    with body.field(name) as child:
                        if name == 'transport' and child.kind == 'object':
                            teed = _tee_transport(child, digest, snapshot_digest)
                            if not teed:
                                _feed((digest,), child)
                        else:
                            _feed((digest,), child)
                digest.update(b'}')
            if teed:
                snapshot_digest.update(b'}')
                lazy._tee = (head, snapshot_digest.hexdigest())
        digest.update(b',"state_id":'+tables.canonical(state_id)+b'}')
        return digest.hexdigest()
    finally:
        body.close()


def native_width(value, ordinary_width):
    # All compact exports above are already reserved by their ownership scope.
    # Native equation workspaces and numerical output reservations stay intact.
    return 0 if isinstance(_reference(value), RecordRef) else ordinary_width(value)


def _measure(ref, path, size=False):
    """Logical width (or element count) of a nested compact field; 0 if absent."""
    held = []
    try:
        node = ref
        for name in path:
            if node.kind != 'object':
                return 0
            node = node.field(name)
            held.append(node)
        return node.size if size else node._logical_length()
    except KeyError:
        return 0
    finally:
        for node in reversed(held):
            node.close()


def native_workspace(exchange, ordinary_width):
    """validate_exchange workspace: legacy 3*_width for dictionaries.

    For a compact exchange (r2) every container export is already owned by
    its scope and the transport snapshot identity is streamed, so this books
    only the native objects the unchanged equations still build: the
    prior-geometry rational map, the transport cell position map, the heat
    snapshot encode, and the whole-export snapshot encode of a small transport
    (measured in test_wp6_streamed_validation; real <= booked).
    """
    ref = _reference(exchange)
    if not isinstance(ref, RecordRef):
        return 3*ordinary_width(exchange)
    transport = _measure(ref, ('transport',))
    return (65536+3*_measure(ref, ('dual_measure_audit', 'prior_geometry_m3'))+
            64*_measure(ref, ('transport', 'cell_ids'), size=True)+
            4*_measure(ref, ('joined_heat',))+
            (4*transport if transport <= LAZY_MIN_BYTES else 0))


def finite_workspace(values, ordinary_width):
    """validate_saved workspace: legacy 8*_width for every dictionary input.

    Compact proposals (r2) book the native parent copy, its encode and hash
    plus the graph end-volume map; compact transports book the cell position
    map (a small whole-export transport also books its decoded copy).
    """
    total = 0
    for value in values:
        ref = _reference(value)
        if not isinstance(ref, RecordRef):
            total += 8*ordinary_width(value)
            continue
        cells = _measure(ref, ('cell_ids',), size=True)
        width = ref._logical_length()
        total += (12*_measure(ref, ('parent',))+400*_measure(ref, ('graph', 'cells'), size=True)+
                  64*cells+(8*width if width <= LAZY_MIN_BYTES else 0))
    return total


def snapshot(metadata, arrays, native):
    """RegionalMechanicalSnapshot result for a transport without result_id.

    Dictionaries keep the exact native construction. A streamed transport
    hashes '{"arrays":...,"metadata":<canonical stream>}', the same bytes as
    _hash({'metadata': ..., 'arrays': ...}); the native class still validates
    and freezes the arrays.
    """
    if not isinstance(metadata, _Lazy):
        return native({k: v for k, v in metadata.items() if k != 'result_id'}, arrays)
    from hashlib import sha256
    from types import SimpleNamespace
    fields = native({}, arrays)._fields
    head = _arrays_head(fields)
    tee, metadata._tee = metadata._tee, None
    if tee is not None and tee[0] == head:
        # W3 (Decision 3): the same head over the same immutable transport
        # bytes, already streamed once by exchange_identity.
        return SimpleNamespace(result_id=tee[1])
    digest = sha256(head[:-1]+b',"metadata":')
    body = metadata.ref.without(('result_id',))
    try:
        with body.iter_json() as stream:
            for block in stream:
                with block:
                    digest.update(block.value)
    finally:
        body.close()
    digest.update(b'}')
    return SimpleNamespace(result_id=digest.hexdigest())


def field_equals(value, key, expected):
    """value.get(key) == expected for dictionaries and every compact form.

    RecordRef.get returns an owned wrapper for scalars, which never compares
    equal to a string; compact exchanges compare the decoded scalar here.
    """
    if isinstance(value, _Object):
        return value.get(key) == expected
    ref = _reference(value)
    if not isinstance(ref, RecordRef):
        return value.get(key) == expected
    if type(expected) not in (str, int, float, bool) and expected is not None:
        raise ContractError('compact field comparison requires a scalar')
    try:
        child = ref.field(key)
    except KeyError:
        return expected is None
    try:
        if child.kind != 'scalar':
            return False  # A decoded container never equals a scalar.
        owned = child.scalar(max_owned_bytes=SMALL_BYTES)
    finally:
        child.close()
    try:
        return owned.value == expected
    finally:
        owned.close()


def encoding_capacity(value, budget, ordinary_capacity):
    return (0, 0) if isinstance(_reference(value), RecordRef) else ordinary_capacity(value, budget)


def codec_scope(value, budget, cancel, ordinary_codec):
    return nullcontext() if isinstance(_reference(value), RecordRef) else ordinary_codec(
        value, budget=budget, cancel=cancel)


def _replace(source, old, new, count=1):
    if source.count(old) != count:
        raise ContractError('compact validation source anchor differs: '+old[:160])
    return source.replace(old, new)


def _function(source, name, changes=(), *, scope=None):
    """Edit exactly one function and retain all untouched acceptance code."""
    nodes = [n for n in ast.walk(ast.parse(source))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(nodes) != 1:
        raise ContractError('compact validation function anchor differs: '+name)
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    part = ''.join(lines[node.lineno-1:node.end_lineno])
    for change in changes:
        part = _replace(part, *change)
    if scope is not None:
        # Retain the docstring; place the ownership scope before the first
        # executable statement. Reparse after substitutions for exact offsets.
        import textwrap
        parsed = ast.parse(textwrap.dedent(part)).body[0]
        first = parsed.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            first = parsed.body[1]
        split = part.splitlines(keepends=True)
        indent = ' '*(node.col_offset+4)
        start = first.lineno-1
        part = ''.join(split[:start])+indent+scope+'\n'+''.join('    '+line if line.strip() else line for line in split[start:])
    lines[node.lineno-1:node.end_lineno] = [part]
    return ''.join(lines)


def _finish(source):
    if _MARKER in source:
        raise ContractError('compact validation transform already applied')
    result = source.rstrip()+_MARKER
    ast.parse(result)
    return result


def owner_source(source):
    if 'from spatial_transfer import validate_projected_payload' in source:
        source = _function(source, 'restore', (
            ("for row in body['cells']:", "for row in _SV.rows(body['cells']):"),
            ('type(record) is not dict', 'not _SV.is_state_record(record)'),
        ))
        source = _replace(source, 'from spatial_transfer import validate_projected_payload',
                          'from spatial_indexed_patch import validate_projected_payload')
        source = _function(source, '_check_measures', (
            ("cells = list(record['cells'])", "cells = _SV.appendable_rows(record['cells'])"),
        ))
        # D1-B: an index of the carried rows, each exported when read.
        source = _function(source, '_carried_start_cells', (
            ("previous = {row['cell_id']: row for row in state['cells']}",
             "previous = _SV.start_rows(state['cells'])"),
            ('parents, children, carried = set(), set(), {}',
             'parents, children, carried = set(), set(), _SV.carried_rows(previous)'),
            ('old = previous.get(parent)', 'old = _SV.lineage_row(previous, parent)'),
            ('carried[child] = dict(old, cell_id=child)',
             '_SV.carry(carried, child, parent, old)'),
        ))
        source = _function(source, 'from_saved', (
            ("for row in initial_record['cells']:", "for row in _SV.rows(initial_record['cells']):", 2),
        ))
    source = _function(source, '_validate_heat_plan', (
        ('type(definition) is dict and _hash(definition)',
         '_SV.is_record(definition) and _SV.identity(definition, _hash)'),
    ), scope='with _SV.access(definition, heat_record) as (definition, heat_record):')
    source = _function(source, 'validate_exchange', (
        ('type(exchange) is dict', '_SV.is_record(exchange)'),
        ('type(exchange) is not dict', 'not _SV.is_record(exchange)'),
        ("_hash(exchange['spatial_graph'])", "_SV.identity(exchange['spatial_graph'], _hash)"),
        ("body = {k: v for k, v in exchange.items() if k not in ('state_id', 'result_id')}",
         'body = _SV.exchange_identity(exchange, state.state_id, _hash, audit_arrays)'),
        ('_hash(dict(state_id=state.state_id, exchange=body))', 'body'),
        ('3*_width(exchange)', '_SV.native_workspace(exchange, _width)'),
        ("RegionalMechanicalSnapshot({k: v for k, v in exchange['transport'].items() if k != 'result_id'}, transport)",
         "_SV.snapshot(exchange['transport'], transport, RegionalMechanicalSnapshot)"),
        ('type(finite) is not dict', 'not _SV.is_record(finite)'),
        ('type(audit) is not dict', 'not _SV.is_record(audit)'),
        ("for cell in r['cells']:", "for cell in _SV.rows(r['cells']):"),
    ), scope='with _SV.access(exchange) as exchange:')
    return _finish(source)


def indexed_owner_source(source):
    """Native restore gates after the existing indexed-state transform."""
    return owner_source(source)


def reservoir_source(source):
    source = _function(source, 'validate_saved', (
        ('8*sum(map(_width, (state_record, proposal_record, transport_record)))',
         '_SV.finite_workspace((state_record, proposal_record, transport_record), _width)'),
        ('type(proposal_record) is not dict', 'not _SV.is_record(proposal_record)'),
        ("_hash({k: v for k, v in proposal_record.items() if k != 'proposal_id'})",
         "_SV.excluded_identity(proposal_record, ('proposal_id',), _hash)"),
    ), scope='with _SV.transport_access(proposal_record, transport_record) as (proposal_record, transport_record):')
    source = _function(source, '_finished_record', (
        ("_hash(p['graph'])", "_SV.identity(p['graph'], _hash)"),
    ), scope='with _SV.transport_access(p, r) as (p, r):')
    return _finish(source)


def measures_source(source):
    source = _function(source, 'transport_audit', (
        ('_json_encoding_capacity(graph, budget)', '_SV.encoding_capacity(graph, budget, _json_encoding_capacity)'),
    ), scope='with _SV.transport_access(graph, result) as (graph, result):')
    source = _function(source, '_transport_audit', (
        ("hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()",
         "_SV.identity(graph, lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest())"),
    ), scope='with _SV.transport_access(graph, result) as (graph, result):')
    source = _function(source, '_dual_audit_capacity', (),
                       scope='with _SV.transport_access(graph, result) as (graph, result):')
    return _finish(source)


def workflow_source(source):
    source = _function(source, '_check_certification_records', (
        ("_hash(graph) != s['graph_id']", "_SV.identity(graph, _hash) != s['graph_id']"),
    ), scope='with _SV.access(graph) as graph:')
    # This exact scope retains graph fields through certification and releases
    # them before _refresh returns, including all refusal paths.
    start = "                            graph = exchange['spatial_graph']\n"
    call_anchor = "                            self._restore_certification(previous['differential_certification'], certification_arrays,\n"
    if source.count(start) != 1 or source.count(call_anchor) != 1:
        raise ContractError('compact refresh graph block anchor differs')
    left = source.index(start)
    call_line = source[:source.index(call_anchor, left)].count('\n')+1
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
             and node.lineno == call_line and isinstance(node.func, ast.Attribute)
             and node.func.attr == '_restore_certification']
    if len(calls) != 1:
        raise ContractError('compact refresh certification call extent differs')
    right = sum(len(line) for line in source.splitlines(keepends=True)[:calls[0].end_lineno])
    block = source[left:right].replace(start,
        "                            graph = _validation_exchange['spatial_graph']\n", 1)
    source = source[:left]+"                            with _SV.access(exchange) as _validation_exchange:\n"+''.join(
        '    '+line if line.strip() else line for line in block.splitlines(keepends=True))+source[right:]
    # r2: compact restored exchanges dispatch on their decoded schema scalar,
    # exactly as the legacy dictionary does (RecordRef.get returns a wrapper).
    source = _replace(source, "if exchange.get('schema') == 'atlas.private.spatial-composed-advance.r1':",
                      "if _SV.field_equals(exchange, 'schema', 'atlas.private.spatial-composed-advance.r1'):")
    return _finish(source)


def joined_source(source):
    # A bounded plan export is deliberately explicit. The original target
    # provenance check still receives its exact unchanged native dictionary.
    source = _function(source, 'validate_plan', (),
        scope='with _SV.access(definition, header) as (definition, header):')
    source = _function(source, 'validate_plan', (
        ('type(definition) is not dict', 'not _SV.is_record(definition)'),
        ('sha256(_json(definition)).hexdigest()',
         '_SV.identity(definition, lambda value: sha256(_json(value)).hexdigest())'),
    ))
    source = _function(source, 'validate_saved_exchange', (),
        scope='with _SV.access(exchange) as exchange:')
    return _finish(source)


def context_source(source):
    """For WP7's selected restored-binding successor, never modify r9 in place."""
    source = _function(source, '_context', (
        ('R.codec_for_value(exchange, budget=budget, cancel=cancel)',
         '_SV.codec_scope(exchange, budget, cancel, R.codec_for_value)'),
        ("body = {k: v for k,v in exchange.items() if k not in ('state_id','result_id')}",
         'body = _SV.exchange_identity(exchange, state.state_id, lambda value: R.stream_hash(value, cancel))'),
        ('type(finite) is not dict or type(finite.get(\'graph\')) is not dict',
         "not _SV.is_record(finite) or not _SV.is_record(finite.get('graph'))"),
        ("R.stream_hash(finite['graph'], cancel)",
         "_SV.identity(finite['graph'], lambda value: R.stream_hash(value, cancel))"),
        ('R.stream_hash(dict(state_id=state.state_id, exchange=body), cancel)', 'body'),
        ('R.stream_hash(graph, cancel)', '_SV.identity(graph, lambda value: R.stream_hash(value, cancel))'),
    ))
    # Returned plan/ref are native owned exports. Their lifetime must be the
    # caller's existing work stack, because _context's result escapes.
    source = _function(source, '_context', (
        ('    _verify(execution, cancel)\n',
         '    exchange = work.stack.enter_context(_SV.access(exchange))\n    _verify(execution, cancel)\n'),
    ))
    return _finish(source)
