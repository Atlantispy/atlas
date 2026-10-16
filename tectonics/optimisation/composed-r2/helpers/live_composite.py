"""Step 8: issue live working records by reference, never by re-import.

A producer dictionary can hold RecordRef children that belong to another live
compact holder: bounds fields inside a closed graph, graph fields inside a
finite proposal, and graph/transport/proposal inside an exchange. Packing such
a value with RecordCodec imports every borrowed subtree into new global tables
while the lending holder stays live, so the same scientific data is held twice
(and each import must fit the 256 MiB builder child).

Here only the native part is packed. Borrowed children stay borrowed through
the existing paid object overlay (record_views._ObjectRecordRef), which keeps
their owners funded for as long as the composite lives. Bytes are unchanged:
object keys are emitted in the same sorted canonical order and each child
streams its own exact canonical bytes. The logical identity is streamed once
and cached on the immutable wrapper, then every later caller reuses it.
"""
from hashlib import sha256

from compact_contracts import ContractError, LogicalIdentity
from record_tables import MAX_DEPTH, RecordCodec
from record_views import LogicalExchange, LogicalRecord, RecordRef, _ObjectRecordRef

SCHEMA = 'atlas.live-composite-record.v1'
# Test-only route switch for same-source A/B measurement: False sends every
# value to the unchanged import pack, so both arms share source bytes and hence
# provenance-bound identities. Production code never changes it.
ENABLED = True


def require(ok, message):
    if not ok:
        raise ContractError(message)


def has_ref(value, depth=0):
    """True when a JSON-domain value contains a borrowed RecordRef anywhere."""
    require(depth <= MAX_DEPTH, 'record nesting exceeds bound')
    if isinstance(value, RecordRef):
        return True
    if type(value) is dict:
        return any(has_ref(child, depth+1) for child in value.values())
    if type(value) is list:
        return any(has_ref(child, depth+1) for child in value)
    return False


class Imports:
    """Explicit record of borrowed subtrees that still had to be imported.

    Only a borrowed child inside a list position cannot be overlaid by key.
    Such imports are counted with their logical bytes, never hidden.
    """
    __slots__ = ('count', 'logical_bytes')

    def __init__(self):
        self.count = self.logical_bytes = 0

    def add(self, value):
        stack = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, RecordRef):
                self.count += 1
                self.logical_bytes += item._logical_length()
            elif type(item) is dict:
                stack.extend(item.values())
            elif type(item) is list:
                stack.extend(item)


def detach(ref, depth=0):
    """An independent paid borrow of the same immutable node or overlay.

    The composite must not hang its borrows off the caller's handle: callers
    close their handles when their access block ends, and a child borrow on a
    handle refuses that close. Borrowing the lending record's own owner keeps
    the backing funded exactly as long as the composite, and nothing longer.
    """
    require(depth <= MAX_DEPTH, 'record overlay nesting exceeds bound')
    if type(ref) is _ObjectRecordRef:
        base, overlay, keys, _, _, overrides = ref._owner.value
        return _ObjectRecordRef(detach(base, depth+1), fields=keys,
            overlay=None if overlay is None else detach(overlay, depth+1),
            overrides={key: detach(child, depth+1) for key, child in overrides.items()} or None)
    require(type(ref) in (RecordRef, LogicalRecord, LogicalExchange) and ref._fields is None,
            'only whole record nodes or object overlays can be borrowed')
    ref._live()
    return RecordRef(ref._view, ref.index, parent_owner=ref._view._owner)


def _compose(value, *, record_schema, scope, check, imports, depth):
    """Composite RecordRef for a dict holding borrowed children; caller owns it."""
    require(type(value) is dict and depth <= MAX_DEPTH, 'object composition requires a bounded dict')
    native, borrowed = {}, {}
    for key, child in value.items():
        require(type(key) is str, 'object keys must be strings')
        if isinstance(child, RecordRef):
            require(child.scope is scope, 'borrowed child has a foreign retained scope')
            borrowed[key] = detach(child)
        elif type(child) is dict and has_ref(child, depth+1):
            borrowed[key] = _compose(child, record_schema=record_schema, scope=scope,
                                     check=check, imports=imports, depth=depth+1)
        else:
            if type(child) is list and has_ref(child, depth+1):
                imports.add(child)
            native[key] = child
    check()
    skeleton = RecordCodec().pack_record(native, record_schema=record_schema, scope=scope, check=check)
    base = skeleton.root()
    # The overlay borrows every child; local carriers retire by reference
    # count once the overlay holds its own paid borrows.
    composite = _ObjectRecordRef(base, overrides=borrowed) if borrowed else base
    return composite


class LiveRecord:
    """Holder payload: one immutable composite plus its cached exact identity.

    It offers the CompactRecord surface that the live holders use (identity,
    root, scope, iteration, close) without owning any copied tables. A lazy
    identity is streamed on first use only; the exchange body never needs its
    own identity (its holder caches the composite result ID instead), so one
    full stream of graph, transport and proposal bytes is not spent on it.
    """
    __slots__ = ('_identity', '_ref', '_schema', '_stream_check', 'imports')

    def __init__(self, ref, identity, imports, *, record_schema=None, check=None):
        self._ref, self._identity, self.imports = ref, identity, imports
        self._schema, self._stream_check = record_schema, check

    @property
    def scope(self):
        return self._ref.scope

    @property
    def _check(self):
        return self._ref._view._check

    def _live(self):
        self._ref._live()

    def identity(self):
        self._live()
        if self._identity is None:
            self._identity = stream_identity(self._ref, self._schema, self._stream_check)
        return self._identity

    def root(self):
        """A caller-closed borrow, as CompactRecord.root() returns."""
        self._live()
        return self._ref.borrow()

    # LogicalExchange.from_body borrows non-CompactRecord bodies by this name.
    borrow = root

    def iter_json(self, *, max_chunk_bytes=65536):
        self._live()
        return self._ref.iter_json(max_chunk_bytes=max_chunk_bytes)

    def close(self):
        self._ref.close()


def stream_identity(ref, record_schema, check):
    digest, length = sha256(), 0
    with ref.iter_json() as stream:
        for block in stream:
            with block:
                check()
                digest.update(block.value)
                length += len(block.value)
    require(length == ref._logical_length(), 'composite canonical length differs')
    return LogicalIdentity(record_schema, digest.hexdigest(), length)


def compose_record(value, *, record_schema, scope, check, eager_identity=True):
    """LiveRecord for a dict with borrowed children; None means pack natively."""
    LogicalIdentity(record_schema, '0'*64, 0)
    if not ENABLED or type(value) is not dict or not has_ref(value):
        return None
    imports = Imports()
    ref = _compose(value, record_schema=record_schema, scope=scope, check=check,
                   imports=imports, depth=0)
    identity = stream_identity(ref, record_schema, check) if eager_identity else None
    check()
    return LiveRecord(ref, identity, imports, record_schema=record_schema, check=check)


def is_live(value):
    return type(value) is LiveRecord
