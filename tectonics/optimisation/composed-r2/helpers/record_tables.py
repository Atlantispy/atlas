"""Generic exact JSON DAG columns. No domain admission, migration or fallback.

One traversal packs, interns and hashes the original canonical JSON. Scientific
JSON strings remain strings, including binary-encoded canonical hex spellings.
Optional parent seeding and locality permutation are deliberately disabled.

The builder streams: only its deduplication tables stay resident. Token bodies,
integer magnitudes, node rows, edges and pool rows are appended to paid spill
buffers that flush in 64 KiB blocks to temporary files and are streamed into the
final columns once, at finish. Deduplication uses array-backed open-addressing
tables (64-bit fingerprint + 32-bit pool index per slot). Keys of at most 7
bytes are held exactly in the slot (flag bit, length, bytes), so their match is
equality; every other fingerprint hit is confirmed against the spilled bytes
(directly, or through a small paid cache of earlier confirmation reads), so a
hashed fingerprint alone never merges two values. The final columns, metadata,
identities and record bytes are exactly those of the previous all-in-memory
builder.

Booking is honest: every resident object is admitted at (or just above) its
measured CPython 3.12 size before it is allocated, and returned when dropped.
"""
from __future__ import annotations

from array import array
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
import re
import struct
import sys
import tempfile
from types import MappingProxyType

import numpy as np

from atlas_tectonics.resources import WorkBudget, _ResizableLease
from compact_contracts import ContractError, LogicalIdentity, UINT64_MAX

SCHEMA = 'atlas.compact-record.v1'
PROFILE = 'atlas.legacy-json.v1'
# D1 derivation (R1, 16 Oct 2026, re-derived after the W2 tables, exact short
# slots, confirmed-entry caches and re-emission memo; literals unchanged:
# raising needs Michael, and lowering would change accept/refuse decisions):
# - MAX_ITEMS (nodes, and each pool and container width): segment design,
#   8-byte node columns (length/charge/offset) in one 128 MiB segment put ->
#   2**24-1 = 16,777,215. Builder memory: fixed state at most about 6.6 MB
#   (stack, spill buffers and block caches, key cache, five confirmed-entry
#   caches, memo and capture buffer) plus the 48,000,412 B rows of a
#   MAX_ITEMS-wide array; measured honest peak 36.8 B per unique node on fully
#   unique graph-like content (1,980,300 nodes, 72.8 MB) -> 5.8 M; unique
#   integers 45.5 B/node -> 4.7 M; unique 70-char strings 45.9 B/node -> 4.7 M.
#   Synthetic worst shape, unique single-key objects (token, shape and node
#   entries each): 94.3 B/node measured at 500,002 nodes, up to about 114 B/node
#   after simultaneous resizes -> 1.9-2.3 M, below the literal; such records
#   refuse honestly (MemoryLimitError, booked before allocation). Measured at
#   the real literals: MAX_ITEMS nodes, tokens and width pass, one more refuses.
# - MAX_EDGES: 4-byte edge.child per 128 MiB segment -> 33,554,432; edges are
#   spilled (no resident cost per edge): 16,000,000 kept (passes, +1 refuses).
# - MAX_ROW_WORK_BYTES: largest admissible row is an object of MAX_ITEMS keys,
#   16 B per key + 785 -> 64,000,785 B (an array of MAX_ITEMS needs 32,000,076);
#   kept at 32 MiB, so objects stop at 2,097,102 keys (passes, +1 refuses).
# - MAX_BUILD_BYTES: 256 MiB fixed by decision.
MAX_ITEMS = 4_000_000
MAX_EDGES = 4*MAX_ITEMS
MAX_DEPTH = 128
MAX_INTEGER_BYTES = 1 << 20
MAX_TOKEN_BYTES = 256 << 20
MAX_BUILD_BYTES = 256 << 20
MAX_ROW_WORK_BYTES = 32 << 20
CHUNK = 65536
NULL, BOOL, INTEGER, FLOAT, TEXT, IDENT, HEX, ARRAY, OBJECT, RATIONAL = range(10)
_HEX = re.compile(r'-?0x(?:0|[1-9a-f][0-9a-f]*)\Z')
_ID = re.compile(r'[0-9a-f]{64}\Z')
# Two code points that JSON decoding would merge into one character.
_SURROGATE_PAIR = re.compile('[\ud800-\udbff][\udc00-\udfff]')

# Spill directory: None uses ATLAS_RECORD_SPILL_DIR, else the process temporary directory.
SPILL_DIRECTORY = None
# Token and integer keys up to this many bytes are kept exactly; longer keys are
# SHA-256 digests whose hits are always verified against the spilled body.
EXACT_KEY_BYTES = 48
# Bounded exact str -> (token, encoded) cache for short strings (keys, short text).
KEY_CACHE_ENTRIES = 4096
KEY_CACHE_CHARS = 64
_NODE = struct.Struct('<IIQQQ')      # payload, shape, logical, charge, edge end
_INT = struct.Struct('<BBQQ')        # sign, mode, exponent, magnitude end
_PAIR = struct.Struct('<II')         # numerator node, denominator node
_U32 = struct.Struct('<I')
_U64 = struct.Struct('<Q')
_NONE = 0xFFFFFFFF
# Measured CPython 3.12 object sizes (sys.getsizeof equals the traced allocation).
_INT_OBJECT = 32                     # ints above the small-int cache, below 2**60
_ARRAY_OBJECT = sys.getsizeof(array('I'))
_BYTES_OBJECT = sys.getsizeof(b'')
_BYTEARRAY_OBJECT = sys.getsizeof(bytearray(1))-1
_LIST_OBJECT = sys.getsizeof([])
_STR_OBJECT = sys.getsizeof('')
# Python frames, iterators and closures of the bounded recursion (128 levels).
_STACK_LEVEL = 2048
_STACK_BYTES = MAX_DEPTH*_STACK_LEVEL
_STACK_START = 16                    # levels booked when a builder starts
# Set entry for referenced incremental nodes: table slots at the worst load
# factor during a resize (old plus new table) and the int object.
_SET_ENTRY = 160
# Deduplication tables: 8-byte fingerprint + 4-byte index per slot, linear
# probing, power-of-two slots doubled at 2/3 load. Booked per array as the
# measured array object (plus a 16-byte allocator header) and its items.
_M64 = (1 << 64)-1
_MIX = 0x9E3779B97F4A7C15            # Fibonacci hashing: slot = top bits of fp*_MIX
_TABLE_SLOTS = 16
_TABLE_ARRAY = _ARRAY_OBJECT+16
_SLOT_BYTES = 12                     # pool indices < MAX_ITEMS < _NONE (the empty-slot mark)
# Keys of at most SHORT_KEY_BYTES are stored exactly in the 64-bit slot: bit 63
# set, length in bits 56-58, key bytes little-endian below. Hashed fingerprints
# never set bit 63, so an exact slot can only match the same short key.
SHORT_KEY_BYTES = 7
_SHORT = 1 << 63
_LOW63 = _SHORT-1
# Confirmed-entry cache per hashed table (see _Confirmed): exact content bytes
# (at most CONFIRM_KEY_BYTES, as read back from the spill) -> pool index, at
# most CONFIRM_CACHE_ENTRIES entries; booked per entry and per dict resize, and
# cleared when full.
CONFIRM_KEY_BYTES = 64
CONFIRM_CACHE_ENTRIES = 2048
# Re-emission memo (incremental finish): node index -> (exact spelling, nesting
# need) for subtrees of at most MEMO_NODE_BYTES, at most MEMO_BYTES booked in
# total (cleared when full). One fixed capture buffer of MEMO_NODE_BYTES.
MEMO_NODE_BYTES = 16 << 10
MEMO_BYTES = 1 << 20
_MEMO_ENTRY = 56+_INT_OBJECT         # the (bytes, height) tuple and the index int


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


def _spill_directory():
    return SPILL_DIRECTORY or os.environ.get('ATLAS_RECORD_SPILL_DIR') or None


def _hex_magnitude_bytes(value):
    """Binary magnitude width of a canonical hex spelling, without parsing it."""
    negative = value[0] == '-'
    digits = len(value)-2-negative
    return (4*(digits-1)+int(value[2+negative], 16).bit_length()+7)//8


def _round_trip_refusal():
    raise ContractError('string does not round-trip through JSON (surrogate pair held as two code points)')


class _Live:
    """One resizable lease for what the builder really holds now.

    Growth is admitted before allocation; returned bytes are released in 64 KiB
    steps. Failure frames that keep the builder alive keep this funding.
    """
    def __init__(self, budget):
        self.lease = _ResizableLease(budget, category='record-workspace')
        self.lease.__enter__()
        self.free = 0

    def take(self, size):
        if size > self.free:
            grow = max(CHUNK, size-self.free)
            self.lease.resize(self.lease.count+grow)
            self.free += grow
        self.free -= size

    def give(self, size):
        self.free += size
        if self.free > 4*CHUNK:
            drop = self.free-CHUNK
            self.lease.resize(self.lease.count-drop)
            self.free -= drop

    def close(self):
        lease, self.lease = getattr(self, 'lease', None), None
        if lease is not None:
            lease.__exit__(None, None, None)

    __del__ = close


class _Map:
    """Exact dictionary whose table growth is booked before CPython resizes it.

    CPython 3.12 grows to the next power of two of three times the used count
    when an insertion finds no usable entry; the old and new tables coexist
    during a resize. Every prediction is checked against sys.getsizeof.
    """
    __slots__ = ('d', 'live', 'table', 'slots', 'owned', 'anomalies')

    def __init__(self, live):
        self.d, self.live = {}, live
        self.table, self.slots, self.owned, self.anomalies = sys.getsizeof(self.d), 0, 0, 0
        live.take(self.table)

    def get(self, key):
        return self.d.get(key)

    def put(self, key, value, owned):
        d, live = self.d, self.live
        live.take(owned)
        self.owned += owned
        if len(d) >= (2*self.slots)//3:
            slots = 8 if self.slots == 0 else 2*self.slots
            index = 1 if slots < 128 else 2 if slots < 32768 else 4 if slots < (1 << 31) else 8
            predicted = 64+64+slots*index+(2*slots//3)*24
            live.take(predicted)
            d[key] = value
            actual = sys.getsizeof(d)
            if actual > predicted:
                self.anomalies += 1
                live.take(actual-predicted)
                predicted = actual
            live.give(self.table+predicted-actual)
            self.table, self.slots = actual, slots
            return
        d[key] = value
        actual = sys.getsizeof(d)
        if actual != self.table:
            # Unpredicted resize: book it now and record the anomaly for tests.
            self.anomalies += 1
            if actual > self.table:
                live.take(actual-self.table)
            else:
                live.give(self.table-actual)
            self.table = actual

    def clear(self):
        self.d.clear()
        self.d = {}
        self.live.give(self.table+self.owned-sys.getsizeof(self.d))
        self.table, self.slots, self.owned = sys.getsizeof(self.d), 0, 0


def _hashed(key):
    """63-bit hash of a longer deduplication key (a candidate, never a proof)."""
    return hash(key) & _LOW63


def _fingerprint(key):
    """Slot fingerprint of an exact deduplication key (bytes).

    Keys of at most SHORT_KEY_BYTES are encoded exactly (bit 63, length, bytes),
    so equal fingerprints mean equal keys and need no confirmation. Longer keys
    get a 63-bit hash, which is only a candidate to confirm.
    """
    size = len(key)
    if size <= SHORT_KEY_BYTES:
        return _SHORT | (size << 56) | int.from_bytes(key, 'little')
    return _hashed(key)


class _Table:
    """Array-backed open-addressing deduplication table.

    Each slot holds a 64-bit fingerprint and the 32-bit pool index it names.
    A fingerprint match is only a candidate: ``equal(index)`` confirms it
    against the spilled bytes, and a mismatch keeps probing, so values with
    equal fingerprints occupy separate slots and are never merged. Exact
    tables (``exact=True``) store the complete 64-bit key as the fingerprint,
    so a match is equality; so do short keys in hashed tables (bit 63 set, see
    _fingerprint). At most one entry per value exists, which gives the same
    deduplication decisions as an exact dictionary.

    Both arrays are booked before they are allocated; while a resize copies
    the entries the old and new arrays are alive together and both are booked.
    """
    __slots__ = ('anomalies', 'booked', 'confirms', 'count', 'exact', 'exact_hits', 'fps', 'hint',
                 'hint_fp', 'idx', 'limit', 'live', 'mask', 'rejects', 'shift')

    def __init__(self, live, exact=False):
        self.live, self.exact = live, exact
        self.count = self.booked = self.anomalies = self.confirms = self.rejects = self.exact_hits = 0
        # The empty slot where the last unsuccessful find stopped (its probe path's end).
        self.hint, self.hint_fp = 0, None
        self.fps, self.idx, self.booked = self._arrays(_TABLE_SLOTS)
        self._shape(_TABLE_SLOTS)

    def _arrays(self, slots):
        cost = 2*_TABLE_ARRAY+_SLOT_BYTES*slots
        self.live.take(cost)
        fps = array('Q', [0])*slots
        idx = array('I', [_NONE])*slots
        actual = sys.getsizeof(fps)+sys.getsizeof(idx)
        if actual > cost-32:
            # Never expected: book what really exists and record it for tests.
            self.anomalies += 1
            self.live.take(actual+32-cost)
            cost = actual+32
        return fps, idx, cost

    def _shape(self, slots):
        self.mask, self.shift, self.limit = slots-1, 65-slots.bit_length(), (2*slots)//3

    def find(self, fp, equal):
        """Pool index of the confirmed equal value, or None."""
        idx, fps, mask = self.idx, self.fps, self.mask
        slot = ((fp*_MIX) & _M64) >> self.shift
        # Exact tables hold complete keys; in hashed tables only short keys set bit 63.
        trusted = self.exact or fp >= _SHORT
        while True:
            index = idx[slot]
            if index == _NONE:
                self.hint, self.hint_fp = slot, fp
                return None
            if fps[slot] == fp:
                if trusted:
                    self.exact_hits += 1
                    return index
                self.confirms += 1
                if equal(index):
                    return index
                self.rejects += 1
            slot = (slot+1) & mask

    def insert(self, fp, index):
        """Add a value the caller has just confirmed absent (find returned None)."""
        if self.count >= self.limit:
            self._grow()
        idx, mask = self.idx, self.mask
        if self.hint_fp == fp and idx[self.hint] == _NONE:
            # Same table shape as that find (a resize clears the hint) and the slot is
            # still empty: every slot before it on fp's probe path is occupied (there
            # are no deletions), so it is where the probe below would stop.
            slot = self.hint
        else:
            slot = ((fp*_MIX) & _M64) >> self.shift
            while idx[slot] != _NONE:
                slot = (slot+1) & mask
        self.hint_fp = None
        self.fps[slot] = fp
        idx[slot] = index
        self.count += 1

    def _grow(self):
        old_fps, old_idx, old_booked = self.fps, self.idx, self.booked
        self.hint_fp = None
        slots = 2*len(old_idx)
        fps, idx, cost = self._arrays(slots)
        self._shape(slots)
        mask, shift = self.mask, self.shift
        for slot in range(len(old_idx)):
            index = old_idx[slot]
            if index != _NONE:
                fp = old_fps[slot]
                at = ((fp*_MIX) & _M64) >> shift
                while idx[at] != _NONE:
                    at = (at+1) & mask
                fps[at] = fp
                idx[at] = index
        self.fps, self.idx, self.booked = fps, idx, cost
        del old_fps, old_idx
        self.live.give(old_booked)

    def clear(self):
        self.fps = self.idx = None
        booked, self.booked, self.count = self.booked, 0, 0
        if booked:
            self.live.give(booked)


def _spill_equal(spill, position, data):
    """True when the spilled bytes at ``position`` equal ``data`` (read in bounded blocks)."""
    view = memoryview(data).cast('B')
    size = len(view)
    for at in range(0, size, CHUNK):
        if spill.peek(position+at, min(CHUNK, size-at)) != view[at:at+CHUNK]:
            return False
    return True


class _Confirmed:
    """Small paid cache of confirmed entries for one hashed table.

    Maps an entry's exact content bytes (at most CONFIRM_KEY_BYTES; the same
    bytes as the table's key for that content) to its pool index. Entries are
    added only after the table proved the match: by reading the entry back
    from its spill and comparing (``confirm``; the bytes read become the
    key), or by an exact short-key slot (``remember``). Pool entries never
    change once spilled and each content has at most one entry, so a hit is
    the same decision the table would make. Each entry and every dict resize
    (old and new tables together) is booked before it exists; the cache is
    cleared when full.
    """
    __slots__ = ('hits', 'map', 'reads')

    def __init__(self, live):
        self.map, self.hits, self.reads = _Map(live), 0, 0

    def get(self, content):
        found = self.map.d.get(content)
        if found is not None:
            self.hits += 1
        return found

    def confirm(self, index, content, load):
        """Compare ``content`` with entry ``index`` read back from its spill."""
        self.reads += 1
        got = load(index)
        if got is None or got != content:
            return False
        self.remember(got, index)
        return True

    def remember(self, content, index):
        d = self.map.d
        if content in d:
            return
        if len(d) >= CONFIRM_CACHE_ENTRIES:
            self.map.clear()
        self.map.put(content, index, sys.getsizeof(content)+_INT_OBJECT)

    @property
    def anomalies(self):
        return self.map.anomalies

    def clear(self):
        self.map.clear()


class _Blocks:
    """Resident fixed-width array in paid 64 KiB blocks (no reallocation copy)."""
    __slots__ = ('blocks', 'count', 'live', 'typecode', 'fill', 'per', 'booked')

    def __init__(self, live, typecode, fill):
        self.blocks, self.count, self.live = [], 0, live
        self.typecode, self.fill = typecode, fill
        self.per = CHUNK//array(typecode).itemsize
        self.booked = _LIST_OBJECT+64
        live.take(self.booked)

    def _ensure(self, index):
        while index >= len(self.blocks)*self.per:
            cost = _ARRAY_OBJECT+CHUNK+16
            self.live.take(cost)
            self.booked += cost
            self.blocks.append(array(self.typecode, [self.fill])*self.per)

    def get(self, index):
        if index >= len(self.blocks)*self.per:
            return self.fill
        return self.blocks[index//self.per][index % self.per]

    def set(self, index, value):
        self._ensure(index)
        self.blocks[index//self.per][index % self.per] = value

    def append(self, value):
        self.set(self.count, value)
        self.count += 1

    def tobytes(self, count):
        width = array(self.typecode).itemsize
        return b''.join(memoryview(block)[:min(self.per, count-i*self.per)].cast('B')
                        for i, block in enumerate(self.blocks) if i*self.per < count)[:count*width]

    def close(self):
        self.blocks = []
        booked, self.booked = self.booked, 0
        if booked:
            self.live.give(booked)


class _Spill:
    """Append-only paid buffer flushed in 64 KiB blocks to a temporary file.

    The resident buffer grows from 1 KiB to one 64 KiB block; a spill that never
    fills a block never creates a file. One cached block serves random reads.
    """
    __slots__ = ('live', 'file', 'buffer', 'used', 'flushed', 'cache_at', 'cache', 'booked')

    def __init__(self, live, head=b''):
        self.live, self.file = live, None
        self.buffer, self.used, self.flushed, self.booked = None, 0, 0, 0
        self.cache_at, self.cache = -1, None
        if head:
            self.write(head)

    @property
    def size(self):
        return self.flushed+self.used

    def _grow(self, need):
        capacity = CHUNK if need > CHUNK//2 else max(1024, 1 << (need-1).bit_length())
        cost = _BYTEARRAY_OBJECT+capacity+1
        self.live.take(cost)
        buffer = bytearray(capacity)
        if self.used:
            buffer[:self.used] = memoryview(self.buffer)[:self.used]
        old, self.buffer = self.buffer, buffer
        self.booked += cost
        if old is not None:
            size = _BYTEARRAY_OBJECT+len(old)+1
            del old
            self.booked -= size
            self.live.give(size)

    def write(self, data):
        view = memoryview(data).cast('B')
        size, at = len(view), 0
        while at < size:
            take = min(CHUNK-self.used, size-at)
            need = self.used+take
            if self.buffer is None or need > len(self.buffer):
                self._grow(need)
            self.buffer[self.used:need] = view[at:at+take]
            self.used = need
            at += take
            if self.used == CHUNK:
                self._flush()

    def _flush(self):
        if not self.used:
            return
        if self.file is None:
            self.file = tempfile.TemporaryFile(dir=_spill_directory(), buffering=0)
        self.file.seek(self.flushed)
        view = memoryview(self.buffer)[:self.used]
        while view:
            view = view[self.file.write(view):]
        del view
        self.flushed += self.used
        self.used = 0

    def _file_read(self, position, size):
        self.file.seek(position)
        parts, remaining = [], size
        while remaining:
            part = self.file.read(remaining)
            require(part, 'record spill file truncated')
            parts.append(part)
            remaining -= len(part)
        return parts[0] if len(parts) == 1 else b''.join(parts)

    def read(self, position, size):
        """Bytes [position, position+size); callers fund transients above one block."""
        end = position+size
        require(0 <= position and end <= self.size, 'record spill read outside written bytes')
        if not size:
            return b''
        if position >= self.flushed:
            return bytes(self.buffer[position-self.flushed:end-self.flushed])
        block = position-position % CHUNK
        if end <= min(self.flushed, block+CHUNK):
            if self.cache_at != block:
                if self.cache is None:
                    self.live.take(CHUNK+_BYTES_OBJECT)
                    self.booked += CHUNK+_BYTES_OBJECT
                self.cache = None
                self.cache = self._file_read(block, min(CHUNK, self.flushed-block))
                self.cache_at = block
            return self.cache[position-block:end-block]
        head = self._file_read(position, min(end, self.flushed)-position)
        if end <= self.flushed:
            return head
        return head+bytes(self.buffer[:end-self.flushed])

    def peek(self, position, size):
        """Like read() for a deduplication confirmation (size <= one block).

        Random confirmations read only the bytes they compare and leave the
        cached block (used by sequential re-emission) in place.
        """
        end = position+size
        require(0 <= position and end <= self.size and size <= CHUNK, 'record spill read outside written bytes')
        if position >= self.flushed:
            return bytes(self.buffer[position-self.flushed:end-self.flushed])
        cache, cache_at = self.cache, self.cache_at
        if cache is not None and 0 <= cache_at <= position and end <= cache_at+len(cache):
            return cache[position-cache_at:end-cache_at]
        if end <= self.flushed:
            return self._file_read(position, size)
        return self._file_read(position, self.flushed-position)+bytes(self.buffer[:end-self.flushed])

    def chunks(self, size=CHUNK):
        """Yield the written bytes in order, each part at most ``size`` bytes."""
        if self.file is None:
            for at in range(0, self.used, size):
                yield bytes(self.buffer[at:min(self.used, at+size)])
            return
        self._flush()
        for at in range(0, self.flushed, size):
            yield self._file_read(at, min(size, self.flushed-at))

    def readall(self):
        """The complete contents as one immutable bytes object (the final column)."""
        if self.file is None:
            return bytes(self.buffer[:self.used]) if self.used else b''
        self._flush()
        return self._file_read(0, self.flushed)

    def close(self):
        """Close the file. Resident buffers stay funded until release()."""
        file, self.file = self.file, None
        if file is not None:
            file.close()

    def release(self):
        self.close()
        self.buffer = self.cache = None
        booked, self.booked = self.booked, 0
        if booked:
            self.live.give(booked)


class _Builder:
    def __init__(self, scope, check):
        self.scope, self.check = scope, check
        # A mandatory child ledger, not another retained scope/revoker. It
        # bounds all simultaneously live builder maps, buffers and row scratch.
        self.work_budget = WorkBudget(MAX_BUILD_BYTES, parent=scope.run_budget)
        self.live = _Live(self.work_budget)
        # Builder object and pool counters, plus the recursion stack booked by
        # level (2 KiB each, as _STACK_BYTES): 16 levels now, more before any
        # deeper level runs, never more than MAX_DEPTH levels.
        self._stack_levels = _STACK_START
        self.live.take(8192+_STACK_START*_STACK_LEVEL)
        live = self.live
        # Resident deduplication state: fingerprint tables confirmed against the
        # spills (floats and rational pairs keep their complete 64-bit key) and
        # the bounded exact cache of short strings.
        self.token_index, self.integer_index = _Table(live), _Table(live)
        self.float_index, self.id_index = _Table(live, exact=True), _Table(live)
        self.shape_index, self.pair_index = _Table(live), _Table(live, exact=True)
        self.node_index, self.key_cache = _Table(live), _Map(live)
        # Confirmation-read caches of the hashed tables (short content only).
        self.token_seen, self.integer_seen = _Confirmed(live), _Confirmed(live)
        self.id_seen, self.shape_seen, self.node_seen = _Confirmed(live), _Confirmed(live), _Confirmed(live)
        # Re-emission memo and its capture buffer (allocated at first use).
        self.spelling = _Map(live)
        self._capture, self._capture_booked = None, 0
        self._capture_at = self._capturing = 0
        self._capture_overflow = False
        self.memo_hits = 0
        self.kinds = _Blocks(live, 'B', 0)
        self.node_of = {kind: _Blocks(live, 'I', _NONE) for kind in
                        (INTEGER, FLOAT, TEXT, IDENT, HEX, RATIONAL)}
        self.fixed_nodes = {}
        # Spilled bodies and rows. Offset spills start with their leading zero.
        self.node_rows, self.edges = _Spill(live), _Spill(live)
        self.token_bytes, self.token_ends = _Spill(live), _Spill(live, _U64.pack(0))
        self.int_bytes, self.int_rows = _Spill(live), _Spill(live)
        self.float_values, self.id_bytes = _Spill(live), _Spill(live)
        self.shape_keys, self.shape_ends = _Spill(live), _Spill(live, _U64.pack(0))
        self.pair_rows = _Spill(live)
        self.n = self.e = self.tokens = self.integers = self.floats = 0
        self.ids = self.shapes = self.pairs = self.shape_key_count = 0
        self.digest, self.length = sha256(), 0
        self._build_token = object()
        self._referenced = set()
        self._closed = False

    def _spills(self):
        return (self.node_rows, self.edges, self.token_bytes, self.token_ends, self.int_bytes,
                self.int_rows, self.float_values, self.id_bytes, self.shape_keys, self.shape_ends,
                self.pair_rows)

    def scratch(self, size):
        require(size <= MAX_ROW_WORK_BYTES, 'record row workspace exceeds fixed 32 MiB import bound')
        return Scratch(self.work_budget, size)

    def _row(self, size):
        """Transient row workspace: paid before allocation, returned by the caller."""
        require(size <= MAX_ROW_WORK_BYTES, 'record row workspace exceeds fixed 32 MiB import bound')
        self.live.take(size)
        return size

    def _deeper(self, depth):
        """Book recursion levels up to ``depth`` (doubling) before they run; at most
        MAX_DEPTH levels, the whole-stack reserve the builder booked up front before."""
        levels = min(MAX_DEPTH, max(depth+1, 2*self._stack_levels))
        if levels > self._stack_levels:
            self.live.take((levels-self._stack_levels)*_STACK_LEVEL)
            self._stack_levels = levels

    def emit(self, part):
        self.check()
        self.digest.update(part)
        self.length += len(part)
        require(self.length <= UINT64_MAX, 'logical byte count overflow')
        if self._capturing:
            end = self._capture_at+len(part)
            if end <= MEMO_NODE_BYTES:
                self._capture[self._capture_at:end] = part
                self._capture_at = end
            else:
                self._capture_overflow = True

    # ---- spilled table readers -------------------------------------------------
    def _token_range(self, index):
        return struct.unpack('<QQ', self.token_ends.read(8*index, 16))

    def _int_row(self, index):
        if index == 0:
            sign, mode, exponent, end = _INT.unpack(self.int_rows.read(0, _INT.size))
            return sign, mode, exponent, 0, end
        # This row and the previous row's end, in one read.
        raw = self.int_rows.read(_INT.size*(index-1), 2*_INT.size)
        sign, mode, exponent, end = _INT.unpack_from(raw, _INT.size)
        return sign, mode, exponent, _INT.unpack_from(raw, 0)[3], end

    def _node_row(self, index):
        if index == 0:
            payload, shape, logical, charge, end = _NODE.unpack(self.node_rows.read(0, _NODE.size))
            return payload, shape, logical, charge, 0, end
        # This row and the previous row's end, in one read.
        raw = self.node_rows.read(_NODE.size*(index-1), 2*_NODE.size)
        payload, shape, logical, charge, end = _NODE.unpack_from(raw, _NODE.size)
        return payload, shape, logical, charge, _NODE.unpack_from(raw, 0)[4], end

    def _shape_start(self, index):
        return _U64.unpack(self.shape_ends.read(8*index, 8))[0]

    # ---- deduplication confirmations (peek: no cached-block churn) -------------
    @staticmethod
    def _peek_row(spill, row, index):
        """Row ``index`` and the previous row's last field (0 for the first row)."""
        if index == 0:
            return row.unpack(spill.peek(0, row.size)), 0
        raw = spill.peek(row.size*(index-1), 2*row.size)
        return row.unpack_from(raw, row.size), row.unpack_from(raw, 0)[-1]

    def _peek_range(self, ends, index):
        return struct.unpack('<QQ', ends.peek(8*index, 16))

    def _token_equal(self, index, raw):
        start, end = self._peek_range(self.token_ends, index)
        return end-start == len(raw) and _spill_equal(self.token_bytes, start, raw)

    def _integer_equal(self, index, sign, mode, exponent, magnitude):
        (other_sign, other_mode, other_exponent, end), start = self._peek_row(self.int_rows, _INT, index)
        return (other_sign == sign and other_mode == mode and other_exponent == exponent and
                end-start == len(magnitude) and _spill_equal(self.int_bytes, start, magnitude))

    def _id_equal(self, index, raw):
        return self.id_bytes.peek(32*index, 32) == raw

    def _shape_equal(self, index, refs):
        start, end = self._peek_range(self.shape_ends, index)
        return end-start == len(refs) and _spill_equal(self.shape_keys, 4*start, refs)

    def _node_equal(self, index, kind, shape, children):
        if self.kinds.get(index) != kind:
            return False
        (_, other_shape, _, _, end), start = self._peek_row(self.node_rows, _NODE, index)
        return (other_shape == shape and end-start == len(children) and
                _spill_equal(self.edges, 4*start, children))

    @staticmethod
    def _find(table, seen, fp, content, load):
        """Pool index of short ``content`` (bytes, the complete key) or None.

        A hashed-slot match is confirmed by reading the entry back from its
        spill; an exact short-key slot match is equality. Either way the proven
        match is remembered in the paid cache ``seen``.
        """
        found = table.find(fp, lambda index: seen.confirm(index, content, load))
        if found is not None and fp >= _SHORT:
            seen.remember(content, found)
        return found

    # ---- confirmation contents (read back from the spills, for _Confirmed) ------
    # Each returns the exact bytes the matching key would have, or None when the
    # entry's content is longer than CONFIRM_KEY_BYTES.
    def _token_content(self, index):
        start, end = self._peek_range(self.token_ends, index)
        return self.token_bytes.peek(start, end-start) if end-start <= CONFIRM_KEY_BYTES else None

    def _integer_content(self, index):
        """The dictionary key form: (3, sign, exponent) for dyadics, else sign + magnitude."""
        (sign, mode, exponent, end), start = self._peek_row(self.int_rows, _INT, index)
        if mode:
            return bytes((3, sign))+exponent.to_bytes(8, 'little')
        if end-start >= EXACT_KEY_BYTES:
            return None
        return bytes((sign,))+(self.int_bytes.peek(start, end-start) if end > start else b'')

    def _id_content(self, index):
        return self.id_bytes.peek(32*index, 32)

    def _shape_content(self, index):
        start, end = self._peek_range(self.shape_ends, index)
        if 4*(end-start) > CONFIRM_KEY_BYTES:
            return None
        return self.shape_keys.peek(4*start, 4*(end-start)) if end > start else b''

    def _node_content(self, index):
        """kind + shape + children bytes, as the container key is built."""
        kind = self.kinds.get(index)
        (_, shape, _, _, end), start = self._peek_row(self.node_rows, _NODE, index)
        if 5+4*(end-start) > CONFIRM_KEY_BYTES:
            return None
        children = self.edges.peek(4*start, 4*(end-start)) if end > start else b''
        return bytes((kind,))+shape.to_bytes(4, 'little')+children

    # ---- pools -----------------------------------------------------------------
    def _token_raw(self, raw):
        """Intern an encoded string token; returns its pool index."""
        short = len(raw) <= CONFIRM_KEY_BYTES
        if short:
            found = self.token_seen.get(raw)
            if found is not None:
                return found
        key = raw if len(raw) <= EXACT_KEY_BYTES else b'\x01'+sha256(raw).digest()
        fp = _fingerprint(key)
        del key
        if short:
            found = self._find(self.token_index, self.token_seen, fp, raw, self._token_content)
        else:
            found = self.token_index.find(fp, lambda index: self._token_equal(index, raw))
        if found is not None:
            return found
        require(len(raw) <= MAX_TOKEN_BYTES, 'encoded string exceeds token bound')
        result = self.tokens
        require(result < MAX_ITEMS, 'token pool exceeds count bound')
        self.token_bytes.write(raw)
        self.token_ends.write(_U64.pack(self.token_bytes.size))
        self.tokens += 1
        self.token_index.insert(fp, result)
        return result

    def _encode(self, value):
        """Exact encoded token for a short string, refusing non-round-trip text."""
        raw = json.dumps(value, ensure_ascii=True).encode('ascii')
        if b'\\ud' in raw and _SURROGATE_PAIR.search(value):
            _round_trip_refusal()
        return raw

    def _cached(self, value):
        return self.key_cache.get(value) if len(value) <= KEY_CACHE_CHARS else None

    def token(self, value):
        """Token index and encoded bytes (None for long strings); short strings are cached."""
        cached = self._cached(value)
        if cached is not None:
            return cached
        require(len(value) <= MAX_TOKEN_BYTES, 'string exceeds token bound')
        if len(value) <= CHUNK:
            # The str and bytes produced by json.dumps(...).encode(): at most
            # 12 ASCII bytes per character, each held twice at the peak.
            work = self._row(_BYTES_OBJECT+_STR_OBJECT+24*len(value)+256)
            raw = self._encode(value)
            result = self._token_raw(raw), raw
            if len(value) <= KEY_CACHE_CHARS:
                if len(self.key_cache.d) >= KEY_CACHE_ENTRIES:
                    self.key_cache.clear()
                self.key_cache.put(value, result, sys.getsizeof(value)+sys.getsizeof(raw)+
                                   sys.getsizeof(result)+_INT_OBJECT)
            self.live.give(work)
            return result
        return self._long_token(value), None

    def _long_token(self, value):
        """Two streamed passes: digest then (if new) spill; no complete raw copy."""
        work = self._row(8*CHUNK+4096)
        digest, size, pair_check = sha256(), 0, False
        for part in string_parts(value):
            digest.update(part)
            size += len(part)
            pair_check = pair_check or b'\\ud' in part
        if pair_check and _SURROGATE_PAIR.search(value):
            _round_trip_refusal()
        require(size <= MAX_TOKEN_BYTES, 'encoded string exceeds token bound')
        fp = _fingerprint(b'\x01'+digest.digest())

        def equal(index):
            start, end = self._peek_range(self.token_ends, index)
            if end-start != size:
                return False
            at = start
            for part in string_parts(value):
                if not _spill_equal(self.token_bytes, at, part):
                    return False
                at += len(part)
            return True
        found = self.token_index.find(fp, equal)
        if found is not None:
            self.live.give(work)
            return found
        result = self.tokens
        require(result < MAX_ITEMS, 'token pool exceeds count bound')
        for part in string_parts(value):
            self.token_bytes.write(part)
        self.token_ends.write(_U64.pack(self.token_bytes.size))
        self.tokens += 1
        self.token_index.insert(fp, result)
        self.live.give(work)
        return result

    def integer(self, value):
        count = (abs(value).bit_length()+7)//8
        require(count <= MAX_INTEGER_BYTES, 'individual binary magnitude exceeds 1 MiB')
        sign = int(value < 0)
        magnitude = (-value if sign else value).to_bytes(count, 'little')
        # Magnitudes are exact and sign is independent. Dyadics have no large body.
        dyadic = count > 8 and magnitude.count(0) == count-1 and magnitude[-1] & (magnitude[-1]-1) == 0
        exponent = 8*(count-1)+magnitude[-1].bit_length()-1 if dyadic else 0
        return self._integer_row(sign, int(dyadic), exponent, b'' if dyadic else magnitude)

    def _integer_row(self, sign, dyadic, exponent, magnitude):
        if dyadic or len(magnitude) < EXACT_KEY_BYTES:
            # The key is the complete content: (3, sign, exponent) or sign + magnitude.
            key = bytes((3, sign))+exponent.to_bytes(8, 'little') if dyadic else bytes((sign,))+magnitude
            found = self.integer_seen.get(key)
            if found is not None:
                return found
            fp = _fingerprint(key)
            found = self._find(self.integer_index, self.integer_seen, fp, key, self._integer_content)
        else:
            digest = sha256(bytes((sign,)))
            digest.update(magnitude)
            key = b'\x02'+digest.digest()
            fp = _fingerprint(key)
            found = self.integer_index.find(
                fp, lambda index: self._integer_equal(index, sign, dyadic, exponent, magnitude))
        del key
        if found is not None:
            return found
        result = self.integers
        require(result < MAX_ITEMS, 'integer pool exceeds count bound')
        self.int_bytes.write(magnitude)
        self.int_rows.write(_INT.pack(sign, dyadic, exponent, self.int_bytes.size))
        self.integers += 1
        self.integer_index.insert(fp, result)
        return result

    # ---- nodes -----------------------------------------------------------------
    def _new_node(self, kind, payload, shape, logical, charge, edges=None, count=0):
        require(self.n < MAX_ITEMS, 'node count exceeds bound')
        result = self.n
        if count:
            self.edges.write(edges)
            self.e += count
        self.node_rows.write(_NODE.pack(payload, shape, logical, charge, self.e))
        self.kinds.append(kind)
        self.n += 1
        return result

    def _scalar_node(self, kind, payload, logical, charge):
        if kind in (NULL, BOOL):
            found = self.fixed_nodes.get((kind, payload))
            if found is None:
                self.live.take(256)
                found = self.fixed_nodes[(kind, payload)] = self._new_node(kind, payload, 0, logical, charge)
            return found
        table = self.node_of[kind]
        found = table.get(payload)
        if found != _NONE:
            return found
        result = self._new_node(kind, payload, 0, logical, charge)
        table.set(payload, result)
        return result

    def _container_node(self, kind, shape, children, logical):
        count = len(children)
        work = self._row(2*(_BYTES_OBJECT+5+4*count))
        key = b''.join((bytes((kind,)), shape.to_bytes(4, 'little'), memoryview(children).cast('B')))
        if len(key) <= CONFIRM_KEY_BYTES:
            found = self.node_seen.get(key)
            if found is not None:
                self.live.give(work)
                return found
            fp = _fingerprint(key)
            found = self._find(self.node_index, self.node_seen, fp, key, self._node_content)
            del key
        else:
            # Long keys are not kept: the confirmation compares against the spill directly.
            fp = _fingerprint(key)
            del key
            found = self.node_index.find(fp, lambda index: self._node_equal(index, kind, shape, children))
        if found is None:
            found = self._new_node(kind, 0, shape, logical, 4096, children, count)
            self.node_index.insert(fp, found)
        self.live.give(work)
        return found

    # ---- traversal -------------------------------------------------------------
    def add(self, value, depth=0):
        from record_views import RecordRef
        if type(value) is _BuiltNode:
            require(value.token is self._build_token and 0 <= value.index < self.n,
                    'foreign incremental record node')
            # Re-emission reads one bounded block at a time and streams scalar
            # bodies in chunks. This row covers the per-node frame transients;
            # each scalar body books its own chunk workspace where it is
            # emitted (_emit_fresh, _emit_token), and the memo, its capture
            # buffer and the recursion levels are booked where they are held.
            work = self._row(4096)
            self._emit_node(value.index, depth)
            if value.index not in self._referenced:
                self.live.take(_SET_ENTRY)
                self._referenced.add(value.index)
            self.live.give(work)
            return value.index
        if isinstance(value, RecordRef):
            with value._view._read_batch():
                return self._add(value, depth)
        return self._add(value, depth)

    def _emit_node(self, index, depth):
        """Hash existing exact nodes without reconstructing a second DAG.

        Returns the subtree's nesting need (0 for a scalar, 1 + the largest
        child need for a container): emitting it at ``depth`` is admissible
        exactly when depth + need <= MAX_DEPTH, which is what the per-level
        checks below enforce. The spelling of a subtree of at most
        MEMO_NODE_BYTES is kept in the paid memo as the bytes emitted here (a
        pure function of the immutable pools), so a shared subtree emitted
        again streams the same bytes after the same depth check.
        """
        self.check()
        memo = self.spelling.d.get(index)
        if memo is not None:
            data, need = memo
            require(depth+need <= MAX_DEPTH, 'record nesting exceeds bound')
            self.memo_hits += 1
            self.emit(data)
            return need
        row = self._node_row(index)
        if row[2] > MEMO_NODE_BYTES:
            return self._emit_fresh(index, depth, row)
        if not self._capturing:
            if self._capture is None:
                self._capture_booked = _BYTEARRAY_OBJECT+MEMO_NODE_BYTES+1
                self.live.take(self._capture_booked)
                self._capture = bytearray(MEMO_NODE_BYTES)
            self._capture_at, self._capture_overflow = 0, False
        start = self._capture_at
        self._capturing += 1
        try:
            need = self._emit_fresh(index, depth, row)
        finally:
            self._capturing -= 1
        if not self._capture_overflow:
            size = self._capture_at-start
            owned = _BYTES_OBJECT+size+_MEMO_ENTRY
            spelling = self.spelling
            if spelling.owned+owned > MEMO_BYTES:
                spelling.clear()
            # Booked before the copy exists (one copy, through a memoryview);
            # _Map books the dict growth.
            self.live.take(owned)
            spelling.owned += owned
            with memoryview(self._capture) as view:
                data = bytes(view[start:self._capture_at])
            spelling.put(index, (data, need), 0)
        return need

    def _emit_fresh(self, index, depth, row):
        """Emit one node from the spilled pools (children through _emit_node)."""
        if depth >= self._stack_levels:
            self._deeper(depth)
        kind = self.kinds.get(index)
        if kind in (ARRAY, OBJECT, RATIONAL):
            require(depth < MAX_DEPTH, 'record nesting exceeds bound')
            payload, shape, _, _, start, end = row
            need = 1
            object_kind = kind == OBJECT
            self.emit(b'{' if object_kind else b'[')
            if kind == RATIONAL:
                children = _PAIR.unpack(self.pair_rows.read(_PAIR.size*payload, _PAIR.size))
            else:
                children = range(start, end)
            if object_kind:
                key_start = self._shape_start(shape)
            for i, child in enumerate(children):
                if i:
                    self.emit(b',')
                if object_kind:
                    token = _U32.unpack(self.shape_keys.read(4*(key_start+i), 4))[0]
                    self._emit_token(token)
                    self.emit(b':')
                if kind != RATIONAL:
                    child = _U32.unpack(self.edges.read(4*child, 4))[0]
                need = max(need, 1+self._emit_node(child, depth+1))
            self.emit(b'}' if object_kind else b']')
            return need
        require(depth <= MAX_DEPTH, 'record nesting exceeds bound')
        payload = row[0]
        if kind == NULL:
            self.emit(b'null')
        elif kind == BOOL:
            self.emit(b'true' if payload else b'false')
        elif kind == FLOAT:
            self.emit(canonical(struct.unpack('<d', self.float_values.read(8*payload, 8))[0]))
        elif kind == IDENT:
            self.emit(b'"'+self.id_bytes.read(32*payload, 32).hex().encode('ascii')+b'"')
        elif kind == TEXT:
            self._emit_token(payload)
        elif kind == HEX:
            sign, mode, exponent, start, end = self._int_row(payload)
            # One chunk at a time: zeros (one bytes object), or a magnitude slice
            # of m <= CHUNK/2 bytes read (two copies if it straddles the spill
            # buffer), reversed, as hex str, encoded and stripped: <= 9 m.
            work = self._row(_BYTES_OBJECT+min(CHUNK, exponent//4)+512 if mode else
                             9*min(CHUNK//2, end-start)+512)
            self.emit(b'"-0x' if sign else b'"0x')
            if mode:
                self.emit(b'1248'[exponent % 4:exponent % 4+1])
                zeros = exponent//4
                while zeros:
                    amount = min(CHUNK, zeros)
                    self.emit(b'0'*amount)
                    zeros -= amount
            else:
                if start == end:
                    self.emit(b'0')
                first = True
                while end > start:
                    low = max(start, end-CHUNK//2)
                    digits = self.int_bytes.read(low, end-low)[::-1].hex().encode('ascii')
                    self.emit(digits.lstrip(b'0') if first else digits)
                    first = False
                    end = low
            self.emit(b'"')
            self.live.give(work)
        elif kind == INTEGER:
            sign, mode, exponent, start, end = self._int_row(payload)
            # Magnitude bytes (two copies if straddling), the int and its negation,
            # and the decimal str and bytes (at most 2.41 digits per byte): <= 9 m.
            work = self._row(9*(exponent//8+1 if mode else end-start)+512)
            number = (1 << exponent) if mode else int.from_bytes(self.int_bytes.read(start, end-start), 'little')
            self.emit(canonical(-number if sign else number))
            del number
            self.live.give(work)
        else:
            raise ContractError('unknown incremental record node kind')
        return 0

    def _emit_token(self, token):
        start, end = self._token_range(token)
        # One chunk read at a time (two copies and their join if it straddles
        # the spill buffer).
        work = self._row(2*(_BYTES_OBJECT+min(CHUNK, end-start))+256)
        for at in range(start, end, CHUNK):
            self.emit(self.token_bytes.read(at, min(CHUNK, end-at)))
        self.live.give(work)

    def _add(self, value, depth=0):
        from record_views import RecordRef, LogicalRecord, LogicalExchange
        self.check()
        if depth >= self._stack_levels:
            self._deeper(depth)
        is_ref = isinstance(value, RecordRef)
        if is_ref:
            require(value.scope is self.scope, 'foreign record scope')
            if type(value) in (RecordRef, LogicalRecord, LogicalExchange) and value._fields is None:
                value._live()
                return self._import(value._view, value.index, depth)
            if value.kind == 'scalar':
                require(depth <= MAX_DEPTH, 'record nesting exceeds bound')
                with value.scalar(max_owned_bytes=MAX_ROW_WORK_BYTES) as scalar:
                    return self.add(scalar.value, depth)
        start = self.length
        if value is None:
            require(depth <= MAX_DEPTH, 'record nesting exceeds bound')
            self.emit(b'null')
            return self._scalar_node(NULL, 0, 4, 4096)
        if type(value) is bool:
            require(depth <= MAX_DEPTH, 'record nesting exceeds bound')
            self.emit(b'true' if value else b'false')
            return self._scalar_node(BOOL, int(value), self.length-start, 4096)
        if type(value) is int:
            require(depth <= MAX_DEPTH, 'record nesting exceeds bound')
            count = (abs(value).bit_length()+7)//8
            # Magnitude bytes, decimal str and its bytes (legacy 4,300-digit cap).
            work = self._row(4096+8*count)
            payload = self.integer(value)
            # Preserve the process conversion limit. Refuse what legacy JSON refuses.
            try:
                raw = canonical(value)
            except ValueError as exc:
                raise ContractError('integer cannot use the unchanged legacy JSON profile') from exc
            self.emit(raw)
            result = self._scalar_node(INTEGER, payload, len(raw), max(4096, 4096+32*len(raw)))
            del raw
            self.live.give(work)
            return result
        if type(value) is float:
            require(depth <= MAX_DEPTH, 'record nesting exceeds bound')
            require(math.isfinite(value), 'nonfinite JSON scalar')
            raw = struct.pack('<d', value)
            # Exact table: the fingerprint is the complete IEEE bit pattern.
            fp = _U64.unpack(raw)[0]
            payload = self.float_index.find(fp, None)
            if payload is None:
                payload = self.floats
                self.float_values.write(raw)
                self.floats += 1
                self.float_index.insert(fp, payload)
            self.emit(canonical(value))
            return self._scalar_node(FLOAT, payload, self.length-start, 4096)
        if type(value) is str:
            require(depth <= MAX_DEPTH, 'record nesting exceeds bound')
            return self._string(value)
        if is_ref or type(value) in (list, dict, StreamingRows):
            # One depth convention with the reader: a container is a level.
            require(depth < MAX_DEPTH, 'record nesting exceeds bound')
            count = value.size if is_ref else (value.count if type(value) is StreamingRows else len(value))
            require(count <= MAX_ITEMS, 'container count exceeds bound')
            object_kind = value.kind == 'object' if is_ref else type(value) is dict
            if object_kind:
                if is_ref:
                    keys_owner = value.keys(max_owned_bytes=MAX_ROW_WORK_BYTES)
                    keys = keys_owner.value
                    try:
                        return self._object(keys, lambda i, key: self._ref_field(value, key, depth), start)
                    finally:
                        del keys
                        keys_owner.close()
                require(all(type(k) is str for k in value), 'object keys must be strings')
                work = self._row(_LIST_OBJECT+8*count)
                keys = sorted(value)
                result = self._object(keys, lambda i, key: self.add(value[key], depth+1), start)
                del keys
                self.live.give(work)
                return result
            if is_ref:
                return self._array(count, start, item=lambda i: self._ref_item(value, i, depth))
            if type(value) is StreamingRows:
                return self._streaming(value, count, depth, start)
            return self._array(count, start, item=lambda i: self.add(value[i], depth+1))
        raise ContractError('unsupported JSON-domain type; no coercion')

    def _ref_field(self, ref, key, depth):
        with ref.field(key) as child:
            return self.add(child, depth+1)

    def _ref_item(self, ref, index, depth):
        with ref.at(index) as child:
            return self.add(child, depth+1)

    def _string(self, value):
        start = self.length
        if len(value) == 64 and _ID.match(value):
            raw = bytes.fromhex(value)
            payload = self.id_seen.get(raw)
            if payload is None:
                fp = _fingerprint(raw)
                payload = self._find(self.id_index, self.id_seen, fp, raw, self._id_content)
                if payload is None:
                    payload = self.ids
                    self.id_bytes.write(raw)
                    self.ids += 1
                    self.id_index.insert(fp, payload)
            self.emit(b'"'+value.encode('ascii')+b'"')
            return self._scalar_node(IDENT, payload, 66, 4096+16*66)
        if (len(value) <= 2*MAX_INTEGER_BYTES+4 and _HEX.fullmatch(value) and value != '-0x0'
                and _hex_magnitude_bytes(value) <= MAX_INTEGER_BYTES):
            # Gate on magnitude: an over-wide hex spelling stays a legacy TEXT token.
            # Measured peak about 1.6 L: the int (0.53 L) with its hex() parity
            # str (L), then the int, a negated copy (0.53 L) and the magnitude (L/2).
            work = self._row(4096+2*len(value))
            number = int(value, 16)
            require(hex(number) == value, 'hex spelling parity failed')
            payload = self.integer(number)
            del number
            for part in string_parts(value):
                self.emit(part)
            logical = self.length-start
            result = self._scalar_node(HEX, payload, logical, 4096+16*logical)
            self.live.give(work)
            return result
        payload, raw = self.token(value)
        if raw is not None:
            self.emit(raw)
        else:
            for part in string_parts(value):
                self.emit(part)
        del raw
        logical = self.length-start
        return self._scalar_node(TEXT, payload, logical, 4096+16*logical)

    def _object(self, keys, child, start):
        count = len(keys)
        # Token indices, shape key bytes and children; encoded keys are not
        # retained (they come from the bounded cache or stream from the spill).
        work = self._row(3*(_ARRAY_OBJECT+4*count)+_BYTES_OBJECT+4*count+512)
        refs = array('I', [0])*count
        for i, key in enumerate(keys):
            require(type(key) is str, 'object keys must be strings')
            refs[i] = self.token(key)[0]
        shape_key = refs.tobytes()
        if len(shape_key) <= CONFIRM_KEY_BYTES:
            shape = self.shape_seen.get(shape_key)
            if shape is None:
                fp = _fingerprint(shape_key)
                shape = self._find(self.shape_index, self.shape_seen, fp, shape_key, self._shape_content)
            del shape_key
        else:
            fp = _fingerprint(shape_key)
            del shape_key
            shape = self.shape_index.find(fp, lambda index, refs=refs: self._shape_equal(index, refs))
        if shape is None:
            shape = self.shapes
            self.shape_keys.write(refs)
            self.shape_key_count += count
            self.shape_ends.write(_U64.pack(self.shape_key_count))
            self.shapes += 1
            self.shape_index.insert(fp, shape)
        children = array('I', [0])*count
        self.emit(b'{')
        for i, key in enumerate(keys):
            if i:
                self.emit(b',')
            cached = self._cached(key)
            if cached is not None and cached[0] == refs[i]:
                self.emit(cached[1])
            else:
                self._emit_token(refs[i])
            del cached
            self.emit(b':')
            children[i] = child(i, key)
        self.emit(b'}')
        result = self._container_node(OBJECT, shape, children, self.length-start)
        del refs, children
        self.live.give(work)
        return result

    def _array(self, count, start, *, item):
        work = self._row(_ARRAY_OBJECT+4*count+256)
        children = array('I', [0])*count
        self.emit(b'[')
        for i in range(count):
            if i:
                self.emit(b',')
            children[i] = item(i)
        self.emit(b']')
        result = self._finish_array(children, start)
        del children
        self.live.give(work)
        return result

    def _finish_array(self, children, start):
        if (len(children) == 2 and self.kinds.get(children[0]) == HEX and
                self.kinds.get(children[1]) == HEX):
            # Two string nodes retain lexical type. Denominators already
            # share exact integer entries; no GCD, reduction or LCM.
            # Exact table: the fingerprint is the complete (numerator, denominator) node pair.
            key = (children[0] << 32) | children[1]
            payload = self.pair_index.find(key, None)
            if payload is None:
                payload = self.pairs
                self.pair_rows.write(_PAIR.pack(children[0], children[1]))
                self.pairs += 1
                self.pair_index.insert(key, payload)
            return self._scalar_node(RATIONAL, payload, self.length-start, 4096)
        return self._container_node(ARRAY, 0, children, self.length-start)

    def _streaming(self, value, count, depth, start):
        from content_cache import Owned
        work = self._row(_ARRAY_OBJECT+4*count+256)
        children = array('I', [0])*count
        self.emit(b'[')
        rows = iter(value.rows_factory())
        done = 0
        for i, row in enumerate(rows):
            require(isinstance(row, Owned) and row.scope is self.scope,
                    'streaming row must be owned in the same scope')
            with row:
                require(i < count, 'streaming row count exceeds declaration')
                if i:
                    self.emit(b',')
                children[i] = self.add(row.value, depth+1)
                done += 1
        require(done == count, 'streaming row count below declaration')
        closer = getattr(rows, 'close', None)
        if closer is not None:
            closer()
        self.emit(b']')
        result = self._finish_array(children, start)
        del children
        self.live.give(work)
        return result

    def _import(self, view, node, depth):
        """Ordinary same-scope reference: copy by position, decode only scalars and keys."""
        self.check()
        if depth >= self._stack_levels:
            self._deeper(depth)
        view._check()
        kind = view._v('node.kind', node)
        start = self.length
        if kind == OBJECT:
            require(depth < MAX_DEPTH, 'record nesting exceeds bound')
            key_start, key_stop = view._range('shape', view._v('node.shape', node))
            edge_start, _ = view._range('node', node)
            count = key_stop-key_start
            work = self._row(_LIST_OBJECT+8*count)
            keys, owned = [None]*count, 0
            for i in range(count):
                lo, hi = view._range('token', view._v('shape.key', key_start+i))
                # Decoded key str: at most one 4-byte code point per encoded byte.
                size = 80+4*(hi-lo)
                self._row(size)
                owned += size
                keys[i] = view._token(view._v('shape.key', key_start+i))
            result = self._object(
                keys, lambda i, key: self._import(view, view._v('edge.child', edge_start+i), depth+1), start)
            del keys
            self.live.give(owned+work)
            return result
        if kind in (ARRAY, RATIONAL):
            require(depth < MAX_DEPTH, 'record nesting exceeds bound')
            count = view._size(node)
            return self._array(count, start, item=lambda i: self._import(view, view._child(node, i), depth+1))
        require(depth <= MAX_DEPTH, 'record nesting exceeds bound')
        length = view._v('node.length', node)
        # Joined canonical bytes plus the decoded scalar (ASCII str, int or float).
        work = self._row(4096+3*length)
        value = json.loads(b''.join(view._parts(node)))
        result = self._add(value, depth)
        del value
        self.live.give(work)
        return result

    # ---- finish ----------------------------------------------------------------
    def _check_reachable(self, root, appended):
        """Refuse unreachable appended nodes (every reopen route would refuse them)."""
        if all(index in self._referenced for index in appended):
            return
        n = self.n
        self.live.take(_BYTEARRAY_OBJECT+n+1)
        reachable = bytearray(n)
        reachable[root] = 1
        for i in range(n-1, -1, -1):
            if not reachable[i]:
                continue
            kind = self.kinds.get(i)
            if kind == RATIONAL:
                for child in _PAIR.unpack(self.pair_rows.read(_PAIR.size*self._node_row(i)[0], _PAIR.size)):
                    reachable[child] = 1
            elif kind in (ARRAY, OBJECT):
                _, _, _, _, start, end = self._node_row(i)
                for at in range(start, end):
                    reachable[_U32.unpack(self.edges.read(4*at, 4))[0]] = 1
        missing = reachable.count(0)
        del reachable
        self.live.give(_BYTEARRAY_OBJECT+n+1)
        require(missing == 0, 'incremental builder has %d appended nodes the final root does not reach; '
                'reopen would refuse them' % missing)

    def _plan(self):
        n, e = self.n, self.e
        require(e <= MAX_EDGES, 'edge count exceeds bound')
        refs = narrow(max(n, self.integers, self.tokens, self.floats, self.ids, self.pairs, self.shapes))
        dtypes = {'node.kind': 'u1', 'node.payload': refs, 'node.shape': narrow(self.shapes),
                  'node.length': '<u8', 'node.charge': '<u8', 'node.offset': '<u8',
                  'edge.child': narrow(n), 'shape.offset': '<u8', 'shape.key': narrow(self.tokens),
                  'token.offset': '<u8', 'token.bytes': 'u1', 'int.offset': '<u8', 'int.bytes': 'u1',
                  'int.sign': 'u1', 'int.mode': 'u1', 'int.exponent': '<u8', 'float.value': '<f8',
                  'id.bytes': 'u1', 'q.numerator': narrow(n), 'q.denominator': narrow(n)}
        counts = {'node.kind': n, 'node.payload': n, 'node.shape': n, 'node.length': n,
                  'node.charge': n, 'node.offset': n+1, 'edge.child': e,
                  'shape.offset': self.shapes+1, 'shape.key': self.shape_key_count,
                  'token.offset': self.tokens+1, 'token.bytes': self.token_bytes.size,
                  'int.offset': self.integers+1, 'int.bytes': self.int_bytes.size,
                  'int.sign': self.integers, 'int.mode': self.integers, 'int.exponent': self.integers,
                  'float.value': self.floats, 'id.bytes': self.id_bytes.size,
                  'q.numerator': self.pairs, 'q.denominator': self.pairs}
        return dtypes, counts

    def column_bytes(self):
        dtypes, counts = self._plan()
        return sum(np.dtype(dtypes[name]).itemsize*counts[name] for name in dtypes)

    def _release_maps(self):
        for table in (self.token_index, self.integer_index, self.float_index, self.id_index,
                      self.shape_index, self.pair_index, self.node_index, self.key_cache,
                      self.token_seen, self.integer_seen, self.id_seen, self.shape_seen, self.node_seen,
                      self.spelling):
            table.clear()
        self._capture = None
        booked, self._capture_booked = self._capture_booked, 0
        if booked:
            self.live.give(booked)
        for blocks in self.node_of.values():
            blocks.close()

    def _materialise(self):
        """Stream every spilled table once into one immutable bytes object per column.

        The caller has already funded the final columns; this books only the
        bounded block transients and the per-field output buffers.
        """
        dtypes, counts = self._plan()
        # One spilled block read, one converted field block and the joined
        # node-kind column (twice: join then trim), plus interpreter headroom.
        work = self._row(3*CHUNK+4096+2*(_BYTES_OBJECT+self.n))
        columns = {}

        def split(spill, layout, fields, prefix=()):
            outputs = {name: _Spill(self.live) for name in fields}
            try:
                for name in prefix:
                    outputs[name].write(_U64.pack(0))
                record = np.dtype(layout)
                rows_per = max(1, CHUNK//record.itemsize)
                for part in spill.chunks(rows_per*record.itemsize):
                    self.check()
                    rows = np.frombuffer(part, dtype=record)
                    for name, field in fields.items():
                        outputs[name].write(rows[field].astype(dtypes[name]))
                    del rows, part
                for name, output in outputs.items():
                    columns[name] = output.readall()
            finally:
                for output in outputs.values():
                    output.release()

        def convert(name, spill, source):
            if np.dtype(dtypes[name]) == np.dtype(source):
                columns[name] = spill.readall()
                return
            split(spill, [('v', source)], {name: 'v'})

        columns['node.kind'] = self.kinds.tobytes(self.n)
        split(self.node_rows, [('payload', '<u4'), ('shape', '<u4'), ('length', '<u8'),
                               ('charge', '<u8'), ('end', '<u8')],
              {'node.payload': 'payload', 'node.shape': 'shape', 'node.length': 'length',
               'node.charge': 'charge', 'node.offset': 'end'}, prefix=('node.offset',))
        convert('edge.child', self.edges, '<u4')
        columns['shape.offset'] = self.shape_ends.readall()
        convert('shape.key', self.shape_keys, '<u4')
        columns['token.offset'] = self.token_ends.readall()
        columns['token.bytes'] = self.token_bytes.readall()
        split(self.int_rows, [('sign', 'u1'), ('mode', 'u1'), ('exponent', '<u8'), ('end', '<u8')],
              {'int.offset': 'end', 'int.sign': 'sign', 'int.mode': 'mode', 'int.exponent': 'exponent'},
              prefix=('int.offset',))
        columns['int.bytes'] = self.int_bytes.readall()
        columns['float.value'] = self.float_values.readall()
        columns['id.bytes'] = self.id_bytes.readall()
        split(self.pair_rows, [('num', '<u4'), ('den', '<u4')],
              {'q.numerator': 'num', 'q.denominator': 'den'})
        arrays = {}
        for name in ('node.kind', 'node.payload', 'node.shape', 'node.length', 'node.charge',
                     'node.offset', 'edge.child', 'shape.offset', 'shape.key', 'token.offset',
                     'token.bytes', 'int.offset', 'int.bytes', 'int.sign', 'int.mode', 'int.exponent',
                     'float.value', 'id.bytes', 'q.numerator', 'q.denominator'):
            data = columns.pop(name)
            dtype = np.dtype(dtypes[name])
            require(len(data) == dtype.itemsize*counts[name], 'record column size differs from plan')
            arrays[name] = np.frombuffer(data, dtype=dtype)
        self.live.give(work)
        return arrays

    def _metadata(self, root, record_schema, arrays):
        identity = LogicalIdentity(record_schema, self.digest.hexdigest(), self.length)
        metadata = dict(schema=SCHEMA, profile=PROFILE, features=[], root=root,
                        identity=identity.to_wire(), arrays={})
        for name, array_ in arrays.items():
            raw = memoryview(array_).cast('B')
            metadata['arrays'][name] = dict(dtype=array_.dtype.str, shape=list(array_.shape),
                                           sha256=sha256(raw).hexdigest())
        raw_metadata = canonical(metadata)
        require(len(raw_metadata) <= 65536, 'record root metadata exceeds bound')
        return raw_metadata

    def finish(self, root, record_schema, appended=()):
        """Compatibility finish: columns are funded by this builder's own ledger."""
        self._check_reachable(root, appended)
        self._release_maps()
        total = self.column_bytes()
        self.live.take(total+65536)
        arrays = self._materialise()
        return self._metadata(root, record_schema, arrays), arrays

    def finish_record(self, root, record_schema, appended=()):
        """Columns are funded once, directly by the retained scope that keeps them."""
        from record_views import CompactRecord
        from atlas_tectonics.resources import MemoryLimitError
        self._check_reachable(root, appended)
        self._release_maps()
        total = self.column_bytes()

        def build():
            arrays = self._materialise()
            raw_metadata = self._metadata(root, record_schema, arrays)
            return raw_metadata, arrays
        # The metadata length is known exactly before any column exists: only
        # the fixed-width column digests are unknown.
        dtypes, counts = self._plan()
        placeholder = {name: dict(dtype=np.dtype(dtypes[name]).str, shape=[counts[name]], sha256='0'*64)
                       for name in dtypes}
        identity = LogicalIdentity(record_schema, self.digest.hexdigest(), self.length)
        bound = len(canonical(dict(schema=SCHEMA, profile=PROFILE, features=[], root=root,
                                   identity=identity.to_wire(), arrays=placeholder)))
        del placeholder
        try:
            return CompactRecord._from_columns(build, total, scope=self.scope, check=self.check,
                                               metadata_bound=bound)
        except MemoryLimitError as exc:
            raise MemoryLimitError(
                'compact record columns (%d bytes) do not fit the retained scope; publish large records '
                'as segments instead of an in-memory CompactRecord' % total) from exc

    def close(self):
        """Close spill files. Funding stays with the builder (and any failure frame)."""
        if self._closed:
            return
        self._closed = True
        for spill in self._spills():
            spill.close()

    def release(self):
        """Successful completion: drop every resident table and return all funding."""
        self.close()
        self._release_maps()
        for spill in self._spills():
            spill.release()
        self.kinds.close()
        self._referenced = set()
        self.live.close()


class RecordCodec:
    def pack_record(self, value, *, record_schema, scope, check,
                    id_pool=None, shape_pool=None, profile=PROFILE):
        require(profile == PROFILE, 'unknown canonicalisation profile')
        require(id_pool is None and shape_pool is None,
                'parent pool seeding disabled pending measured benefit gate')
        LogicalIdentity(record_schema, '0'*64, 0)
        builder = _Builder(scope, check)
        try:
            root = builder.add(value)
            record = builder.finish_record(root, record_schema)
        finally:
            # Spill files never outlive the pack; failed frames keep the funding.
            builder.close()
        builder.release()
        try:
            check()
        except BaseException:
            record.close()
            raise
        # The trusted builder already verified logical parity in the pack pass.
        return record

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
    Finalisation refuses appended nodes that the final root does not reach.
    """
    def __init__(self, *, scope, check=lambda: None):
        from content_cache import RetainedScope
        require(type(scope) is RetainedScope and not scope._closed, 'open retained scope required')
        require(callable(check), 'callable builder check required')
        self.scope, self.check = scope, check
        self._builder, self._busy = _Builder(scope, check), False
        self._appended = array('I')

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
            if len(self._appended) % 1024 == 0:
                # array growth: at most the new and the previous buffer coexist.
                builder.live.take(8*1024+_ARRAY_OBJECT)
            self._appended.append(node)
            self.check()
            return result
        except BaseException:
            # Do not reuse a partially built inventory; failed frames keep it paid.
            self._builder = None
            builder.close()
            raise
        finally:
            self._busy = False

    def finish(self, value, *, record_schema):
        require(self._builder is not None and not self._busy, 'incremental builder is closed or busy')
        LogicalIdentity(record_schema, '0'*64, 0)
        self._busy = True
        builder = self._builder
        try:
            builder.digest, builder.length = sha256(), 0
            root = builder.add(value)
            record = builder.finish_record(root, record_schema, self._appended)
            builder.close()
            builder.release()
            try:
                self.check()
            except BaseException:
                record.close()
                raise
            return record
        finally:
            builder.close()
            self._builder, self._busy = None, False
            self._appended = array('I')

    def close(self):
        require(not self._busy, 'incremental builder is busy')
        if self._builder is not None:
            self._builder.release()
        self._builder = None


@dataclass(frozen=True, slots=True)
class ArrayInfo:
    name: str
    dtype: str
    shape: tuple
    logical_bytes: int


def _immutable(array_):
    """True only for a C-contiguous view of an entire immutable bytes object."""
    base = array_.base
    return (type(base) is bytes and not array_.flags.writeable and array_.flags.c_contiguous and
            array_.ndim == 1 and array_.nbytes == len(base))


def freeze_arrays(arrays):
    # Immutable bytes, not a reversible numpy WRITEABLE flag. Arrays already
    # backed by a whole immutable bytes object are kept without a second copy.
    return MappingProxyType({name: array_ if _immutable(array_) else
                             np.frombuffer(array_.tobytes(), dtype=array_.dtype).reshape(array_.shape)
                             for name, array_ in arrays.items()})
