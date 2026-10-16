"""Step 8: spatial publication by reference; live records are never re-imported.

The WP5 bundle packs every sibling row into one new codec DAG. Rows that
borrow live compact records (graph, transport, finite proposal, state cells)
were imported into that DAG while their holders stayed live: a second copy in
memory and a builder pass over the whole borrowed size. Instead:

- each distinct backing CompactRecord that a row borrows beyond a small bound
  is published once, as its own direct segment, straight from its existing
  columns (no builder; the segment backend streams 64 KiB blocks);
- native fields and small borrowed pieces still go into one small bundle DAG;
- each such kind's descriptor carries a bounded recipe naming segment nodes and
  the object overlays that reassemble its exact logical record.

Publication proves each recipe by rebuilding it over the very columns it will
persist and comparing the streamed bytes with an independent stream of the
original value. Readers rebuild over authenticated segments and prove each
kind's identity before returning it. Old readers refuse the new descriptor
schema (v1 requires its three fields) and the direct segment schema.
"""
import json
from hashlib import sha256

from compact_contracts import ContractError, SegmentRef
from record_tables import SCHEMA as CODEC_SCHEMA
from record_tables import canonical
from record_views import (
    CompactRecord,
    LogicalExchange,
    LogicalRecord,
    RecordRef,
    _ObjectRecordRef,
)
from segment_store import SegmentBackend

REF_V2 = 'atlas.spatial-record-ref.v2'
DIRECT_SCHEMA = 'atlas.spatial-record-direct.v1'
SMALL_IMPORT_BYTES = 4 << 20
MAX_IMPORT_BYTES = 32 << 20
MAX_RECIPE_DEPTH = 32
MAX_RECIPE_NODES = 1024
MAX_DESCRIPTOR_BYTES = 32 << 10
MAX_SEGMENTS = 64
MAX_FRAGMENTS = 1024
# One bundle key holds every native fragment as a list, so the bundle's own
# record index stays one entry larger than the plain v1 kinds it carries.
FRAGMENTS = '~fragments'
_ORDINARY = (RecordRef, LogicalRecord, LogicalExchange)


def require(ok, message):
    if not ok:
        raise ContractError(message)


def _leaf(value):
    require(type(value) in _ORDINARY and value._fields is None,
            'only whole record nodes or object overlays can be persisted by reference')
    return value


def borrowed_bytes(value, depth=0):
    """Logical bytes of borrowed compact content inside a row value."""
    require(depth <= MAX_RECIPE_DEPTH, 'record overlay nesting exceeds bound')
    if type(value) is _ObjectRecordRef:
        base, overlay, _, _, _, overrides = value._owner.value
        return sum(borrowed_bytes(item, depth+1)
                   for item in (base, overlay, *overrides.values()) if item is not None)
    if isinstance(value, RecordRef):
        return _leaf(value)._logical_length()
    if type(value) is dict:
        return sum(borrowed_bytes(item, depth+1) for item in value.values())
    if type(value) is list:
        return sum(borrowed_bytes(item, depth+1) for item in value)
    return 0


def needs_recipe(value):
    """Rows with no large borrowed content keep the unchanged v1 bundle field."""
    return borrowed_bytes(value) > SMALL_IMPORT_BYTES


class Planner:
    """Symbolic recipes; segment slots and node numbers are fixed after publish."""

    def __init__(self, scope):
        self.scope = scope
        self.fragments = []
        self.views = {}
        self.direct = []
        self.keep = []
        self.nodes = 0
        self.imported_bytes = 0

    def close(self):
        """Release field borrows taken while planning (fragments are dropped)."""
        for child in reversed(self.keep):
            child.close()
        self.keep.clear()
        self.fragments = []

    def _fragment(self, value):
        self.imported_bytes += borrowed_bytes(value)
        require(self.imported_bytes <= MAX_IMPORT_BYTES, 'small borrowed imports exceed their bound')
        require(len(self.fragments) < MAX_FRAGMENTS, 'too many native record fragments')
        self.fragments.append(value)
        return ('fragment', len(self.fragments)-1)

    def _direct(self, ref):
        view = ref._view
        require(type(view) is CompactRecord and view.scope is self.scope,
                'borrowed record has a foreign retained scope')
        slot = self.views.get(id(view))
        if slot is None:
            require(len(self.direct) < MAX_SEGMENTS, 'too many directly published records')
            slot = self.views[id(view)] = len(self.direct)
            self.direct.append(view)
        return ('direct', slot, ref.index)

    def recipe(self, value, depth=0, needed=None):
        """Plan only what the selected keys need (needed=None: the whole value).

        An overlay that hides keys (an exchange body without its graph and
        transport) must not drag the hidden records into its recipe: they
        would be published, referenced and re-validated for nothing.
        """
        require(depth <= MAX_RECIPE_DEPTH and self.nodes < MAX_RECIPE_NODES, 'record recipe exceeds bound')
        self.nodes += 1
        if type(value) is _ObjectRecordRef:
            base, overlay, keys, overlay_keys, _, overrides = value._owner.value
            keys = tuple(key for key in keys if needed is None or key in needed)
            overrides = {key: child for key, child in overrides.items() if key in keys}
            from_overlay = set(keys) & set(overlay_keys) if overlay is not None else set()
            from_base = set(keys) - set(overrides) - from_overlay
            return ('overlay', self.recipe(base, depth+1, from_base), keys,
                    self.recipe(overlay, depth+1, from_overlay) if from_overlay else None,
                    {key: self.recipe(child, depth+1) for key, child in overrides.items()} or None)
        if isinstance(value, RecordRef):
            _leaf(value)
            if needed is not None and value.kind == 'object':
                with value.keys(max_owned_bytes=MAX_DESCRIPTOR_BYTES) as names:
                    all_keys = names.value
                if set(needed) != set(all_keys):
                    # Select the needed fields one by one; the rest stays out.
                    selected = {}
                    for key in sorted(needed):
                        child = value.field(key)
                        self.keep.append(child)
                        selected[key] = self.recipe(child, depth+1)
                    return ('overlay', self._fragment({}), tuple(sorted(needed)), None, selected or None)
            if value._logical_length() <= SMALL_IMPORT_BYTES:
                return self._fragment(value)
            return self._direct(value)
        if type(value) is dict and borrowed_bytes(value) > SMALL_IMPORT_BYTES:
            native = {key: child for key, child in value.items() if borrowed_bytes(child) <= SMALL_IMPORT_BYTES}
            large = {key: self.recipe(child, depth+1) for key, child in value.items() if key not in native}
            return ('overlay', self._fragment(native), tuple(sorted(value)), None, large)
        return self._fragment(value)


def wire(recipe, *, bundle_slot, direct_slots, fragment_nodes):
    tag = recipe[0]
    if tag == 'fragment':
        return {'node': [bundle_slot, fragment_nodes[recipe[1]]]}
    if tag == 'direct':
        return {'node': [direct_slots[recipe[1]], recipe[2]]}
    _, base, keys, overlay, overrides = recipe
    again = lambda part: wire(part, bundle_slot=bundle_slot, direct_slots=direct_slots,
                              fragment_nodes=fragment_nodes)
    return {'base': again(base), 'keys': list(keys),
            'overlay': None if overlay is None else again(overlay),
            'overrides': None if overrides is None else {k: again(v) for k, v in overrides.items()}}


def used_segments(recipe, found=None):
    found = set() if found is None else found
    if recipe[0] == 'fragment':
        found.add(('bundle',))
    elif recipe[0] == 'direct':
        found.add(('direct', recipe[1]))
    else:
        _, base, _, overlay, overrides = recipe
        for part in (base, overlay, *(overrides or {}).values()):
            if part is not None:
                used_segments(part, found)
    return found


def check_wire(recipe, segment_count, depth=0, budget=None):
    """Strict shape, before any record is built from an untrusted descriptor."""
    budget = [MAX_RECIPE_NODES] if budget is None else budget
    budget[0] -= 1
    require(depth <= MAX_RECIPE_DEPTH and budget[0] >= 0 and type(recipe) is dict, 'invalid record recipe')
    if set(recipe) == {'node'}:
        node = recipe['node']
        require(type(node) is list and len(node) == 2 and all(type(x) is int for x in node) and
                0 <= node[0] < segment_count and 0 <= node[1] <= (1 << 63), 'invalid recipe node')
        return
    require(set(recipe) == {'base', 'keys', 'overlay', 'overrides'}, 'invalid recipe overlay')
    keys = recipe['keys']
    require(type(keys) is list and all(type(k) is str for k in keys) and keys == sorted(set(keys)),
            'recipe keys must be sorted distinct strings')
    require(recipe['overlay'] is None or recipe['overrides'] is None, 'one overlay source required')
    check_wire(recipe['base'], segment_count, depth+1, budget)
    if recipe['overlay'] is not None:
        check_wire(recipe['overlay'], segment_count, depth+1, budget)
    if recipe['overrides'] is not None:
        require(type(recipe['overrides']) is dict and recipe['overrides'] and
                set(recipe['overrides']) <= set(keys), 'invalid recipe overrides')
        for child in recipe['overrides'].values():
            check_wire(child, segment_count, depth+1, budget)


def build(recipe, records):
    """Caller-owned RecordRef/overlay over already authenticated records.

    A recipe that names a key its parts do not supply is refused here; one
    that names the wrong but well-formed node is refused by the identity
    comparison every caller makes before the result escapes.
    """
    if set(recipe) == {'node'}:
        slot, index = recipe['node']
        return RecordRef(records[slot], index)
    base = build(recipe['base'], records)
    overlay = None if recipe['overlay'] is None else build(recipe['overlay'], records)
    overrides = (None if recipe['overrides'] is None else
                 {key: build(child, records) for key, child in recipe['overrides'].items()})
    try:
        # The overlay borrows its parts; local carriers retire by reference count.
        return _ObjectRecordRef(base, fields=tuple(recipe['keys']), overlay=overlay, overrides=overrides)
    except KeyError as error:
        raise ContractError('record recipe names a key its parts do not supply') from error


def fragment_nodes(bundle, count):
    """Node index of each native fragment inside a packed or reopened bundle."""
    with bundle.root() as root, root.field(FRAGMENTS) as fragments:
        require(fragments.kind == 'array' and fragments.size == count, 'record fragment inventory differs')
        nodes = []
        for at in range(count):
            with fragments.at(at) as item:
                nodes.append(item.index)
        return nodes


def check_direct_metadata(segment, producer=None):
    """Authenticated root metadata only; never the payload columns."""
    row = segment._owner.value
    if producer is not None:
        require(row['producer'] == producer, 'record producer differs from authenticated root')
    metadata = row['metadata']
    require(type(metadata) is dict and set(metadata) == {'schema', 'codec'} and
            metadata['schema'] == DIRECT_SCHEMA and type(metadata['codec']) is dict,
            'unknown or incomplete direct record metadata')
    codec = metadata['codec']
    require(codec.get('identity') == segment.info.ref.identity.to_wire() and
            type(codec.get('arrays')) is dict and segment.info.array_count == len(codec['arrays']),
            'direct record codec identity or column inventory differs from authenticated root')
    return metadata


def stream_identity(value, check):
    digest, length = sha256(), 0
    with value.iter_json() as stream:
        for block in stream:
            with block:
                check()
                digest.update(block.value)
                length += len(block.value)
    return {'bytes': length, 'sha256': digest.hexdigest()}


def value_identity(value, *, scope, check, record_schema='atlas.spatial-record-row.v1'):
    """Independent identity of an original row value, by its own objects."""
    if isinstance(value, RecordRef):
        return stream_identity(value, check)
    import live_composite as LIVE
    composed = LIVE.compose_record(value, record_schema=record_schema, scope=scope, check=check)
    if composed is None:
        raw = canonical(value)
        return {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}
    try:
        with composed.root() as root:
            return stream_identity(root, check)
    finally:
        composed.close()


def publish_direct(store, view, *, producer, scope, cancel):
    """One existing record's exact columns as its own segment; no builder."""
    identity = view.identity()
    with view.metadata_bytes() as held:
        metadata = canonical({'schema': DIRECT_SCHEMA, 'codec': json.loads(held.value)})
    return SegmentBackend().publish(store, record_schema=identity.record_schema, identity=identity,
        metadata=metadata, arrays=view.array_sources, producer=producer,
        representation_profile=CODEC_SCHEMA, scope=scope, cancel=cancel)


def open_direct(segment, producer=None, check=lambda: None):
    """Authenticated direct segment metadata, then the exact validated record."""
    metadata = check_direct_metadata(segment, producer)
    return CompactRecord.from_segment(segment, canonical(metadata['codec']), check=check)


def descriptor_wire(kind, identity, segments, recipe):
    compact = {'schema': REF_V2, 'segments': [ref.to_wire() for ref in segments], 'recipe': recipe}
    result = {**identity, 'compact': compact}
    require(len(canonical(result)) <= MAX_DESCRIPTOR_BYTES, 'record descriptor exceeds bound: '+kind)
    return result


def parse_descriptor(value, kind):
    """(segments, recipe) for a v2 descriptor; strict and bounded."""
    require(type(value) is dict and set(value) == {'bytes', 'sha256', 'compact'},
            'complete compact record descriptor required')
    require(type(value['bytes']) is int and value['bytes'] >= 0 and
            type(value['sha256']) is str and len(value['sha256']) == 64 and
            all(c in '0123456789abcdef' for c in value['sha256']), 'invalid logical record identity')
    require(len(canonical(value)) <= MAX_DESCRIPTOR_BYTES, 'record descriptor exceeds bound')
    compact = value['compact']
    require(type(compact) is dict and set(compact) == {'schema', 'segments', 'recipe'} and
            compact['schema'] == REF_V2, 'record reference schema/binding differs')
    segments = compact['segments']
    require(type(segments) is list and 0 < len(segments) <= MAX_SEGMENTS, 'invalid recipe segment list')
    parsed = [SegmentRef.from_wire(item) for item in segments]
    require(len({ref.to_json() for ref in parsed}) == len(parsed), 'repeated recipe segment')
    check_wire(compact['recipe'], len(parsed))
    return parsed, compact['recipe']


def is_v2(value):
    return (type(value) is dict and type(value.get('compact')) is dict and
            value['compact'].get('schema') == REF_V2)
