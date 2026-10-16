"""Private JSON view inventories for the heat path, not allocator or native acceptance.

Successor facade of issuer resources r3 (and through it r1). Every exact,
decimal, GMP, sparse and projection inventory is re-exported unchanged; the
installed 512-byte scalar/1024-byte container policy still sizes all of them.
Only three things differ, all for decoded JSON views:

1. Decode sizing. r1 charged that scalar/container policy to every JSON token.
   This module derives what CPython 3.12 json.loads allocates for ASCII JSON:
   the temporary text copy, one str per string token, dict objects with their
   key tables, the decoder's key memo, list objects with their over-allocated
   item arrays, int/float objects, and the one container that is being
   resized. Each object is charged the allocator block it can occupy: its
   16-byte class, or for a string that contains an escape the over-allocated
   buffer it was built in, which a shrinking reallocation may keep. The scan
   still parses nothing, so it cannot know how items are spread over the
   lists and dicts or which keys repeat: it charges the worst spread and no
   sharing, and one eighth for allocator overhead. That figure is booked
   BEFORE json.loads runs. Once it has returned, the decoded value is walked
   once in constant working memory and the booking falls to what is really
   there: every object at its block, a key or cached small integer that is
   provably the same object charged once.
2. Lifetime of the stream-codec share. r1 held it for the life of every view.
   Here ``decoded`` books the decode only; ``codec`` books the encoder while a
   ``stream_hash`` of that view runs, and ``codec_for_value`` does so for a
   value that never was a view. ``stream_hash`` itself is the unchanged r1
   function and still books nothing.
3. ``extracted`` gives a caller a compact owned copy of the few fields it
   reads, so that it can release a full decode before the next one. The copy
   is sized before it exists and counted once it does, like a decode.

These are accounting policies: an upper limit on the bytes of the blocks that
the objects of one decode or one stream encoding occupy under the probed
runtime, with a share for the allocators' own overhead. They are NOT an
allocator proof, a process-memory bound or a native admission: memory the C
heap sets aside beyond the blocks in use (its unused reserve for each block
size, for one) is process memory. Process memory stays the supervisor's
concern. Receipts produced under r1 remain valid under r1 and are not
reinterpreted by these numbers.

The derivation depends on the interpreter build. ``RUNTIME`` records the probe;
if any fact differs, or the integer-digit limit is not 1..4300 at call time,
the preserved r1 formula and its r1 lifetime are used instead.
https://github.com/python/cpython/blob/v3.12.14/Modules/_json.c
https://github.com/python/cpython/blob/v3.12.14/Objects/dictobject.c
https://github.com/python/cpython/blob/v3.12.14/Objects/listobject.c
https://github.com/python/cpython/blob/v3.12.14/Objects/unicodeobject.c
https://github.com/python/cpython/blob/v3.12.14/Objects/obmalloc.c
https://github.com/python/cpython/blob/v3.12.14/Lib/json/encoder.py
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import sys

import private_heat_issuer_resources_r3 as FACADE
import private_heat_issuer_resources_r1 as BASE

HERE = Path(__file__).resolve().parent
_PINS = {
    'private_heat_issuer_resources_r3.py': '6517cc80b676a7a66a0ab573899d2e6e6beadf20af5fd7f9b6987962f35621cd',
    'private_heat_issuer_resources_r1.py': 'f46aefd332c97c5e7fd6ddd9de3a0783d7608d3820a9b440483bf0fee36d7318',
}
for _name, _pin in _PINS.items():
    if sha256((HERE/_name).read_bytes()).hexdigest() != _pin:
        raise ValueError('Pinned issuer resource predecessor changed: '+_name)
if (FACADE.BASE is not BASE or Path(FACADE.__file__).resolve() != HERE/'private_heat_issuer_resources_r3.py'
        or Path(BASE.__file__).resolve() != HERE/'private_heat_issuer_resources_r1.py'):
    raise ValueError('Issuer resource predecessors were loaded from another source')
_SELF_SHA = sha256(Path(__file__).read_bytes()).hexdigest()

A, D, L, P, UNIT, O = FACADE.A, FACADE.D, FACADE.L, FACADE.P, FACADE.UNIT, FACADE.O
check, workspace = FACADE.check, FACADE.workspace
source_hash, stream_hash, target_bytes = FACADE.source_hash, FACADE.stream_hash, FACADE.target_bytes
owner_projection_bytes = FACADE.owner_projection_bytes
projection_output_plan = FACADE.projection_output_plan
calculate, ProjectionNumerics = FACADE.calculate, FACADE.ProjectionNumerics
_ProjectionArithmetic = FACADE._ProjectionArithmetic
pair_shape = BASE.pair_shape

DERIVED, LEGACY = 'cpython312-json-objects.r1', 'r1-scalar-container'
INT_DIGIT_LIMIT = 4300

# 64-bit CPython 3.12 object layouts and pymalloc's 16-byte size classes.
STR_ASCII = 40             # PyASCIIObject; one NUL follows the characters
STR_COMPACT = 56           # PyCompactUnicodeObject, the non-ASCII kinds
DICT_OBJECT = 64           # 48-byte dict and its 16-byte collector header
DICT_FIRST_KEYS = 120      # 32 header, 8 index bytes, 5 unicode entries of 16
LIST_OBJECT = 56           # 40-byte list and its 16-byte collector header
FLOAT_OBJECT = 24
INT_OBJECT = 28            # 24 header and one 30-bit digit of 4 bytes
BYTES_OBJECT = 33
TUPLE_PAIR = 56

SMALL_BLOCK = 512          # pymalloc's largest block; a larger one is a C-heap block
HEAP_HEADER = 16           # the C heap's own header in front of such a block

# What json.loads creates, from the record's bytes (see JsonCost).
STRING_WRITER = 4          # escape writer: the old buffer during a move, widest kind
WRITER_KEPT = 2            # a string with an escape may keep its buffer: 1/2 more
# One list of n items: its 64-byte object and an item array that append grows
# in the steps 4, 8, 16, 24, 32, 40, 52, ... slots, never more than n + n/8 + 6.
# These lines (bytes for the list, bytes per item) each bound that cost and
# their minimum is concave, so the lists of a record together cost no more than
# the least of the lines taken on their totals, however the items are spread.
LIST_LINES = ((64, 32), (84, 12), (128, 9))
LIST_GROWTH_ITEM = 8       # the full old array of the one list being resized
# One dict of n entries: its 64-byte object; nothing more when empty; a first
# key table of 128 bytes up to five entries; then a full table is replaced by
# one of twice its slots, so it has under three slots per entry: 16-byte
# entries for two thirds of them and an index of at most four bytes per slot
# (eight from 2**28 entries, the second pair of lines).
DICT_LINES = ((64, 128), (148, 44)), ((64, 128), (148, 56))
DICT_GROWTH_ENTRY = 22, 28  # the full old table of the one dict being resized
NUMBER_UNIT = 32           # float 24 in its class; int 28 + 4 per 30 bits, under its text
NUMBER_WORK = 16           # one token: bytes copy and strtod/long scratch
FIXED_DECODE = 1 << 16     # decoder state, small temporaries, free lists
FIXED_POOLS = (2 << 20)-FIXED_DECODE   # the part-used pool of each size class and one
                           # part-used arena; never more than an eighth of the objects
ALLOCATOR_SHARE = 3        # one eighth on a figure sized in advance, and on C-heap
                           # blocks: their headers and bucket rounding
SMALL_SHARE = 4            # one sixteenth on counted pymalloc blocks: pool headers and
                           # tails are at most 3.3 % of a pool

# The compact copy and the one re-insert are sized in advance with these
# older, more generous units; a copy is then counted like a decode.
DICT_UNIT = 192            # 64 object + 128: first table, or two table headers
LIST_UNIT = 160            # 64 object + 96: 48 array slack, 16 rounding, 32 block
LIST_GROWTH_UNIT = 96      # the same fixed part of the array being replaced
LIST_ITEM = 9              # 8 bytes and the one-eighth over-allocation
FIXED_COPY = 1 << 16

# One stream hash.
FIXED_CODEC = 1 << 17
CODEC_CHUNK = 16           # per character of the largest escaped chunk; three are live
CODEC_RAW_CHUNK = 18       # per raw string byte: three live chunks, six characters each
CODEC_ENTRY = 96           # sorted (key, value) tuples of every ancestor object
CODEC_LEVEL = 4096         # generator frame, marker entry, item view per level
CODEC_WALK_FROM = 16 << 20  # a larger figure from the bytes is checked against the value

# Counting a decoded value: identities of the keys already charged. Only dicts
# of at most KEY_DICT entries feed it (rows repeat their keys; a wide map's
# keys are mostly its own), and it stops growing at KEY_IDS: a quarter of a
# mebibyte, beside 80 bytes for each level of nesting.
KEY_IDS = 4096
KEY_DICT = 64
_SMALL_INTS = tuple(range(-5, 257))

# _json interns the name of every NaN, Infinity or -Infinity token it reads.
# '-Infinity' is the only one the interpreter does not already keep. Without
# this reference each such token would insert it into, and remove it from, the
# interpreter-wide interned-strings table and use up one of its slots; the
# rebuild that follows happens inside json.loads and is sized by the process,
# not by the record.
_NEGATIVE_INFINITY = sys.intern('-Infinity')


def _dict_entry(colons):
    """(retained, growing) bytes per entry of a unicode-key table, generously.

    Used for the compact copy and the one re-insert: any table of fewer than
    six slots per entry, and the full old table beside it while it grows.
    """
    index = 4 if colons < (1 << 28) else 8
    return 64+6*index, 80+8*index


def _with_allocator(count):
    return L._size(count+(count >> ALLOCATOR_SHARE))


def _fixed(count):
    """The fixed part beside ``count`` bytes of objects.

    A small record opens no pool or arena of its own worth charging; a large
    one can leave one pool of every size class and one arena part used.
    """
    return FIXED_DECODE+min(FIXED_POOLS, count >> 3)


@dataclass(frozen=True)
class JsonCost:
    """Token counters of one ASCII JSON record; no decoded value is held."""
    encoded_bytes: int
    strings: int
    string_storage: int
    largest_string: int
    dicts: int
    lists: int
    commas: int
    colons: int
    outside_bytes: int
    largest_gap: int
    writer_storage: int
    writer_strings: int
    string_blocks: int

    @property
    def _numbers(self):
        # A number needs a value slot and at least one byte outside strings
        # that is not one of the four counted structural bytes.
        slots = self.lists+self.commas+self.colons+1
        other = self.outside_bytes-self.dicts-self.lists-self.commas-self.colons
        return min(slots, other), other

    @property
    def _objects(self):
        """Every object json.loads can leave: strings, lists, dicts, numbers."""
        items = self.lists+self.commas          # each item follows a '[' or a comma
        lists = min(base*self.lists+slope*items for base, slope in LIST_LINES)
        dicts = min(base*self.dicts+slope*self.colons
                    for base, slope in DICT_LINES[self.colons >= (1 << 28)])
        numbers, other = self._numbers
        return self.string_blocks+lists+dicts+NUMBER_UNIT*numbers+other

    @property
    def decode_retained_bytes(self):
        """The decoded value after json.loads has returned, sized in advance.

        ``decoded`` books the smaller of this and what it then counts.
        """
        objects = self._objects
        return _with_allocator(_fixed(objects)+objects)

    @property
    def decode_peak_bytes(self):
        """Everything json.loads can hold at once, its text copy included."""
        wide = self.colons >= (1 << 28)
        base, slope = DICT_LINES[wide][1]
        objects = self._objects
        return _with_allocator(_fixed(objects)+objects
            # Transients. The text copy. The old buffer of the one string being
            # built. The key memo, one more dict: every key that a colon follows
            # and the one read before its colon is looked for. One container
            # being resized: the full old table of a dict (or of the memo), or
            # the full old array of a list. One number token.
            +self.encoded_bytes+STR_ASCII+1+HEAP_HEADER+16
            +STRING_WRITER*self.largest_string+1024
            +base+slope*(self.colons+1)
            +DICT_GROWTH_ENTRY[wide]*self.colons+64
            +LIST_GROWTH_ITEM*(self.lists+self.commas)+64
            +NUMBER_WORK*self.largest_gap)

    @property
    def stream_codec_bytes(self):
        """One json.JSONEncoder(sort_keys=True).iterencode pass.

        For consecutive list items three chunk-sized strings are live: the
        chunk the caller still holds, the escaped item, and separator plus
        item. A raw 0x7f is written as six characters, the largest growth.
        Also covers any part of the value, and one small wrapper object of at
        most eight entries around it (an identity record of metadata and arrays).
        """
        depth = min(self.dicts+self.lists+2, sys.getrecursionlimit()+2)
        return _with_allocator(FIXED_CODEC+CODEC_RAW_CHUNK*self.largest_string
            +NUMBER_WORK*self.largest_gap+CODEC_ENTRY*(self.colons+8)+CODEC_LEVEL*depth)

    # The preserved r1 policy: fallback, and before/after reporting.
    @property
    def legacy_decode_bytes(self):
        return L._size(65536+self.encoded_bytes+self.string_storage+UNIT*(self.dicts+self.lists)
            +D.DECIMAL80_SLOT*(self.strings+self.commas+self.colons+1)+4*self.outside_bytes)

    @property
    def legacy_stream_codec_bytes(self):
        return L._size(65536+8*self.largest_string+96*(self.strings+self.commas+self.colons)
            +192*(self.dicts+self.lists))

    def view_bytes(self, policy):
        """(while json.loads runs, while the view lives) for one policy."""
        if policy == LEGACY:
            count = self.legacy_decode_bytes+self.legacy_stream_codec_bytes
            return count, count
        return self.decode_peak_bytes, self.decode_retained_bytes


def json_cost(blob, cancel=None):
    """No JSON parse, substring copies or integer coefficient allocation.

    Only canonical ensure_ascii byte records are in scope. Counters only grow
    along the input and every coefficient above is non-negative, so the bounds
    also cover any prefix consumed by a parse that then fails. Escaped quotes
    are recognised; a unicode escape widens its own string to four bytes per
    character, and the storage of every string that contains a backslash is
    also counted on its own. Each string adds the block it can occupy. Lists,
    dicts and numbers are only counted here; ``JsonCost`` bounds them from the
    totals. JSON.loads remains the syntax validator after admission.
    """
    if type(blob) is not bytes or not blob.isascii():
        raise ValueError('Owned ensure_ascii JSON bytes required')
    if 0 in blob[:2]:
        # json.loads would detect UTF-16/32 and read other tokens than this scan.
        raise ValueError('ASCII JSON bytes cannot begin with NUL')
    strings = dicts = lists = commas = colons = storage = largest = outside = gap = 0
    written = writers = blocks = 0
    at, size = 0, len(blob)
    while at < size:
        check(cancel)
        begin = blob.find(b'"', at)
        stop = size if begin < 0 else begin
        if stop > at:
            dicts += blob.count(b'{', at, stop)
            lists += blob.count(b'[', at, stop)
            commas += blob.count(b',', at, stop)
            colons += blob.count(b':', at, stop)
            outside += stop-at
            if stop-at > gap:
                gap = stop-at
        if begin < 0:
            break
        end = begin+1
        while True:
            end = blob.find(b'"', end)
            if end < 0:
                raise ValueError('Unterminated JSON string in sealed record')
            before = end-1
            while before > begin and blob[before] == 92:
                before -= 1
            if (end-1-before) % 2 == 0:
                break
            end += 1
        length = end-begin-1
        escape = blob.find(b'\\', begin+1, end)
        if escape < 0:
            # An exact substring of the text: 40 + 1 + its characters.
            need = length+STR_ASCII+1
        else:
            # The scanner builds this string with its escape writer, in a
            # buffer of up to 1.5 times its characters, and a shrinking
            # reallocation may leave it in that block.
            if blob.find(b'\\u', escape, end) >= 0:
                length *= 4
                need = length+length//WRITER_KEPT+STR_COMPACT+4
            else:
                need = length+(length+WRITER_KEPT-1)//WRITER_KEPT+STR_ASCII+1
            written += length
            writers += 1
        blocks += ((need+15) & -16)+(HEAP_HEADER if need > SMALL_BLOCK else 0)
        storage += length
        if length > largest:
            largest = length
        strings += 1
        at = end+1
    return JsonCost(size, strings, storage, largest, dicts, lists, commas, colons, outside, gap,
                    written, writers, blocks)


def _default_allocator():
    """No allocator debug hooks or replacement were requested for this process.

    Debug hooks pad every block; the units above have no room for that.
    """
    if sys.flags.dev_mode or hasattr(sys, 'gettotalrefcount'):
        return False
    return (bool(sys.flags.ignore_environment)
            or os.environ.get('PYTHONMALLOC', '') in ('', 'default', 'pymalloc'))


def _runtime():
    """Facts the derivation uses; a constant-size inspection at import."""
    grown, listed = {}, []
    for at in range(6):
        grown['k%d' % at] = None
    listed.append(None)
    return dict(
        implementation=sys.implementation.name == 'cpython',
        version=sys.version_info[:2] == (3, 12),
        pointer=struct.calcsize('P') == 8,
        # Block sizes and process memory were measured on this platform only.
        platform=sys.platform == 'win32',
        allocator=_default_allocator(),
        interned_constant=sys.intern(''.join(('-', 'Infinity'))) is _NEGATIVE_INFINITY,
        str_ascii=sys.getsizeof('') == STR_ASCII+1 and sys.getsizeof('a'*100) == STR_ASCII+101,
        str_latin=sys.getsizeof('\xe9'*100) == STR_COMPACT+101,
        str_ucs2=sys.getsizeof('中'*100) == STR_COMPACT+202,
        str_ucs4=sys.getsizeof('\U0001f600'*100) == STR_COMPACT+404,
        dict_empty=sys.getsizeof({}) == DICT_OBJECT,
        dict_first=sys.getsizeof({'a': None}) == DICT_OBJECT+DICT_FIRST_KEYS,
        dict_grown=sys.getsizeof(grown) == DICT_OBJECT+32+16+10*16,
        list_empty=sys.getsizeof([]) == LIST_OBJECT,
        list_first=sys.getsizeof(listed) == LIST_OBJECT+4*8,
        float_object=sys.getsizeof(1.5) == FLOAT_OBJECT,
        int_object=sys.getsizeof(1) == INT_OBJECT and sys.getsizeof(2**30) == INT_OBJECT+4,
        int_digit=sys.int_info.bits_per_digit == 30 and sys.int_info.sizeof_digit == 4,
        bytes_object=sys.getsizeof(b'') == BYTES_OBJECT,
        tuple_pair=sys.getsizeof((None, None)) == TUPLE_PAIR,
        c_scanner=(getattr(json.decoder, 'c_scanstring', None) is not None
                   and type(json._default_decoder.scan_once).__module__ == '_json'),
    )


RUNTIME = _runtime()
_DERIVED_RUNTIME = all(RUNTIME.values())


def _derived_now():
    return _DERIVED_RUNTIME and 0 < sys.get_int_max_str_digits() <= INT_DIGIT_LIMIT


def select_policy(policy=None):
    """The derived policy on the probed runtime, else the preserved r1 one."""
    if policy is None:
        return DERIVED if _derived_now() else LEGACY
    if policy == LEGACY:
        return LEGACY
    if policy != DERIVED:
        raise ValueError('Unknown JSON view accounting policy')
    if not _derived_now():
        raise RuntimeError('Derived JSON accounting requires the probed CPython 3.12 runtime')
    return DERIVED


def _counted(value, cancel=None):
    """(pymalloc bytes, C-heap bytes) of the blocks a decoded value occupies.

    One walk with a stack of iterators, one per nesting level, and a bounded
    set of key identities: constant working memory, under the caller's
    booking. Every list, dict, float and value string is its own object and is
    charged in full. A key is charged once only when the same object has been
    charged already (the decoder returns one object for equal keys); an
    integer or a literal is free only when it is the interpreter's own cached
    object. A str that the escape writer built can sit in a larger block than
    its size; ``held_bytes`` adds that from the record's counters.
    """
    small = large = count = 0
    seen = set()
    getsize, ints = sys.getsizeof, _SMALL_INTS
    stack = [iter((value,))]
    while stack:
        for node in stack[-1]:
            kind = type(node)
            if kind is str:
                size = getsize(node)
                if size > SMALL_BLOCK:
                    large += ((size+15) & -16)+HEAP_HEADER
                else:
                    small += (size+15) & -16
            elif kind is list:
                # 64-byte object; the item array is a block of its own.
                size = getsize(node)-LIST_OBJECT
                if size > SMALL_BLOCK:
                    large += ((size+15) & -16)+HEAP_HEADER
                    small += 64
                else:
                    small += 64+((size+15) & -16)
                if node:
                    count += 1
                    if not count & 4095:
                        check(cancel)
                    stack.append(iter(node))
                    break
            elif kind is dict:
                # 64-byte object; the key table is a block of its own.
                size = getsize(node)-DICT_OBJECT
                if size > SMALL_BLOCK:
                    large += ((size+15) & -16)+HEAP_HEADER
                    small += 64
                else:
                    small += 64+((size+15) & -16)
                if node:
                    count += 1
                    if not count & 4095:
                        check(cancel)
                    narrow = len(node) <= KEY_DICT
                    for key in node:
                        mark = id(key)
                        if mark in seen:
                            continue
                        if narrow and len(seen) < KEY_IDS:
                            seen.add(mark)
                        if type(key) is not str:
                            raise TypeError('Decoded JSON values required')
                        size = getsize(key)
                        if size > SMALL_BLOCK:
                            large += ((size+15) & -16)+HEAP_HEADER
                        else:
                            small += (size+15) & -16
                    stack.append(iter(node.values()))
                    break
            elif kind is float:
                small += 32
            elif kind is int:
                if -5 <= node <= 256 and node is ints[node+5]:
                    continue
                size = getsize(node)+4          # allocated for one digit more than it may use
                if size > SMALL_BLOCK:
                    large += ((size+15) & -16)+HEAP_HEADER
                else:
                    small += (size+15) & -16
            elif node is None or kind is bool:
                continue
            else:
                raise TypeError('Decoded JSON values required')
        else:
            stack.pop()
    return small, large


def writer_excess(cost):
    """Most that the blocks of a record's escaped strings exceed their sizes by."""
    return ((cost.writer_storage+WRITER_KEPT-1)//WRITER_KEPT
            +(15+HEAP_HEADER)*cost.writer_strings)


def held_bytes(value, cost=None, cancel=None):
    """Booking for a value that json.loads (or the compact copy) has just built.

    ``cost`` is the record's counters when the value comes from json.loads: a
    string with an escape may sit in the block of its buffer, up to half its
    storage larger than its size shows, in the next class, and behind a heap
    header that its size alone would not have. The caller still holds the
    booking under which the value was built. A caller that later makes the
    value larger books that itself.
    """
    small, large = _counted(value, cancel)
    if cost is not None:
        large += writer_excess(cost)
    return L._size(_fixed(small+large)+small+(small >> SMALL_SHARE)+large+(large >> ALLOCATOR_SHARE))


class DecodedView(P.OwnedSolve):
    """Owner of one decoded record; its counters fund a later codec scope."""
    def __init__(self, value, owned, cost, policy, retained_bytes):
        super().__init__(value, owned)
        self.cost, self.policy, self.retained_bytes = cost, policy, retained_bytes


def decoded(blob, *, budget, cancel=None, policy=None):
    policy = select_policy(policy)
    with workspace(budget, D.METADATA_WORK_BYTES, cancel=cancel,
                   category='private-heat-json-metadata'):
        cost = json_cost(blob, cancel)
    peak, retained = cost.view_bytes(policy)
    owned = workspace(budget, peak, cancel=cancel, category='private-heat-json-view')
    owned.__enter__()
    try:
        value = json.loads(blob)
        check(cancel)
        if policy == DERIVED:
            # json.loads has returned: its text copy, key memo and growth
            # transients are dropped. What the decoded value holds is counted
            # under the peak booking, and only that stays charged.
            retained = min(retained, held_bytes(value, cost, cancel))
        if retained != peak:
            owned.resize_before_allocation_or_after_drop(retained)
        return DecodedView(value, owned, cost, policy, retained)
    except BaseException:
        owned.__exit__(*sys.exc_info())
        raise


def codec(view, *, budget, cancel=None):
    """Book the encoder for stream hashes of one live view, or of parts of it.

    An r1-policy view already carries its codec share for life, as in r1.
    From the bytes, every dict entry of the record is charged as if all were
    on one path from the root. Where that figure is large the decoded value is
    walked for its longest path, and the smaller of the two bounds is booked.
    """
    if type(view) is not DecodedView:
        raise TypeError('A decoded JSON view owner is required')
    value = view.value
    count = 0 if view.policy == LEGACY else view.cost.stream_codec_bytes
    if count > CODEC_WALK_FROM:
        with workspace(budget, D.METADATA_WORK_BYTES+CODEC_LEVEL*sys.getrecursionlimit(), cancel=cancel,
                       category='private-heat-json-codec-sizing'):
            try:
                count = min(count, value_codec_bytes(value, cancel))
            except RecursionError:
                pass                            # nested too deeply to walk: the figure from the bytes stands
    return workspace(budget, count, cancel=cancel, category='private-heat-json-codec')


def _codec_scan(node, depth, entries, state, cancel):
    kind = type(node)
    if kind is dict:
        check(cancel)
        entries += len(node)
        state[1] = max(state[1], CODEC_LEVEL*depth+CODEC_ENTRY*entries)
        for key, item in node.items():
            _codec_scan(key, depth+1, entries, state, cancel)
            _codec_scan(item, depth+1, entries, state, cancel)
    elif kind in (list, tuple):
        check(cancel)
        state[1] = max(state[1], CODEC_LEVEL*depth+CODEC_ENTRY*entries)
        for item in node:
            _codec_scan(item, depth+1, entries, state, cancel)
    elif kind is str:
        state[0] = max(state[0], 2+(6 if node.isascii() else 12)*len(node))
    elif kind is int:
        state[0] = max(state[0], 4+(node.bit_length()*30103)//100000)
    elif node is None or kind in (bool, float):
        state[0] = max(state[0], 32)
    else:
        raise TypeError('JSON values required for stream codec sizing')


def value_codec_bytes(value, cancel=None):
    """Encoder bound of an already owned value: no copy, formatting or sort.

    Caller holds the metadata lease for this traversal. The bound also covers
    a stream hash of any part of the value, and of one small wrapper object of
    at most eight entries around it.
    """
    state = [32, 0]
    _codec_scan(value, 2, 8, state, cancel)
    return _with_allocator(FIXED_CODEC+CODEC_CHUNK*state[0]+state[1])


def codec_for_value(value, *, budget, cancel=None):
    """Book the encoder for stream hashes of a value that is not a view."""
    with workspace(budget, D.METADATA_WORK_BYTES+CODEC_LEVEL*sys.getrecursionlimit(), cancel=cancel,
                   category='private-heat-json-codec-sizing'):
        count = value_codec_bytes(value, cancel)
    return workspace(budget, count, cancel=cancel, category='private-heat-json-codec')


def verified_private(result, method, *, budget, cancel=None):
    """Exactly one funded parse, same sealed result hash and source checks."""
    if type(result) is not method.PrivateNumericalResult:
        raise TypeError('The fixed current finisher result class is required')
    blob = result._sealed
    owner = decoded(blob, budget=budget, cancel=cancel)
    try:
        record = owner.value
        identity = record.pop('result_id')
        with codec(owner, budget=budget, cancel=cancel):
            if stream_hash(record, cancel) != identity:
                raise ValueError('Private corrected result identity changed')
        if any(source_hash(path, cancel) != digest for path, digest in record['sources'].items()):
            raise ValueError('Private corrected result source binding changed')
        # A pop does not give its entry back, so re-inserting the key into a
        # full table replaces it by one of twice its slots, for good. This
        # workspace funds the old and the new table together; before it is
        # released the view takes over what the table has grown by.
        before = sys.getsizeof(record)
        with workspace(budget, 4096+_dict_entry(len(record))[1]*(len(record)+1), cancel=cancel,
                       category='private-heat-json-reinsert'):
            record['result_id'] = identity
            grown = sys.getsizeof(record)-before
            if grown > 0 and owner.policy == DERIVED:
                owner.retained_bytes += _with_allocator(grown+16+HEAP_HEADER)
                owner._workspace.resize_before_allocation_or_after_drop(owner.retained_bytes)
        if result._sealed is not blob:
            raise ValueError('Private corrected result changed while decoding')
        return owner
    except BaseException:
        owner.__exit__(*sys.exc_info())
        raise


class Rows:
    """Selection applied to every row of a list of objects."""
    def __init__(self, fields):
        self.fields = fields


ALL = Rows(None)   # sentinel: the complete value


def _scalar_bytes(value):
    # The copy and one transient of the same size, each in its class and block.
    return 2*(sys.getsizeof(value)+64)


def _copy_bytes(value, spec, cancel):
    kind = type(value)
    if spec is not ALL and type(spec) is dict and kind is dict:
        check(cancel)
        _, growing = _dict_entry(len(spec))
        return DICT_UNIT+sum(growing+_scalar_bytes(key)+_copy_bytes(value[key], sub, cancel)
                             for key, sub in spec.items() if key in value)
    if spec is not ALL and type(spec) is Rows and kind is list:
        check(cancel)
        return (LIST_UNIT+LIST_GROWTH_UNIT+(LIST_ITEM+LIST_GROWTH_ITEM)*len(value)
                +sum(_copy_bytes(row, spec.fields, cancel) for row in value))
    if kind is dict:
        check(cancel)
        _, growing = _dict_entry(len(value))
        return DICT_UNIT+sum(growing+_scalar_bytes(key)+_copy_bytes(item, ALL, cancel)
                             for key, item in value.items())
    if kind is list:
        check(cancel)
        return (LIST_UNIT+LIST_GROWTH_UNIT+(LIST_ITEM+LIST_GROWTH_ITEM)*len(value)
                +sum(_copy_bytes(item, ALL, cancel) for item in value))
    if value is None or kind in (bool, str, int, float):
        return _scalar_bytes(value)
    raise TypeError('Decoded JSON values required for an owned extract')


def _copy_scalar(value):
    kind = type(value)
    if kind is str:
        # A new str: nothing may keep the decoded view's own objects alive.
        return (value+'\0')[:-1]
    if kind is int:
        size = (value.bit_length()+8)//8
        return int.from_bytes(value.to_bytes(size, 'little', signed=True), 'little', signed=True)
    if kind is float:
        return struct.unpack('<d', struct.pack('<d', value))[0]
    if value is None or kind is bool:
        return value
    raise TypeError('Decoded JSON values required for an owned extract')


def _copy_value(value, spec, cancel):
    kind = type(value)
    if spec is not ALL and type(spec) is dict and kind is dict:
        check(cancel)
        return {_copy_scalar(key): _copy_value(value[key], sub, cancel)
                for key, sub in spec.items() if key in value}
    if spec is not ALL and type(spec) is Rows and kind is list:
        check(cancel)
        return [_copy_value(row, spec.fields, cancel) for row in value]
    if kind is dict:
        check(cancel)
        return {_copy_scalar(key): _copy_value(item, ALL, cancel) for key, item in value.items()}
    if kind is list:
        check(cancel)
        return [_copy_value(item, ALL, cancel) for item in value]
    return _copy_scalar(value)


def extracted(view, spec, *, budget, cancel=None):
    """Own a compact copy of selected fields; it aliases nothing of the view.

    ``spec`` maps keys to ALL, to a nested mapping, or to Rows(mapping) for a
    list of objects. Absent keys stay absent, so the caller's own lookups and
    refusals are unchanged. Sized from the live view before any copy exists;
    once it exists, what it holds is counted and only that stays charged.
    """
    if type(view) is not DecodedView or type(spec) is not dict:
        raise TypeError('A decoded JSON view owner and a field selection are required')
    value = view.value
    with workspace(budget, D.METADATA_WORK_BYTES+CODEC_LEVEL*sys.getrecursionlimit(), cancel=cancel,
                   category='private-heat-json-extract-sizing'):
        count = _with_allocator(FIXED_COPY+_copy_bytes(value, spec, cancel))
    owned = workspace(budget, count, cancel=cancel, category='private-heat-json-extract')
    owned.__enter__()
    try:
        copy = _copy_value(value, spec, cancel)
        held = held_bytes(copy, None, cancel)
        if held < count:
            owned.resize_before_allocation_or_after_drop(held)
        return P.OwnedSolve(copy, owned)
    except BaseException:
        owned.__exit__(*sys.exc_info())
        raise
