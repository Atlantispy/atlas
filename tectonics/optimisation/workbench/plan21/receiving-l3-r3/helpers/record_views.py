"""Owned non-Mapping references over generic columns or bounded segment reads."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager, nullcontext
from collections import OrderedDict, deque
from hashlib import sha256
import gc
import json
import math
import struct
import sys
import threading
import weakref

import numpy as np

from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from compact_contracts import ContractError, LogicalIdentity
from content_cache import ChargeSpec, OwnedStream, VerifiedCacheKey, get_content_cache
import record_tables as T

_NAMES = frozenset(('node.kind', 'node.payload', 'node.shape', 'node.length',
    'node.charge', 'node.offset', 'edge.child', 'shape.offset', 'shape.key',
    'token.offset', 'token.bytes', 'int.offset', 'int.bytes', 'int.sign',
    'int.mode', 'int.exponent', 'float.value', 'id.bytes', 'q.numerator', 'q.denominator'))
_BYTE = {'node.kind', 'token.bytes', 'int.bytes', 'int.sign', 'int.mode', 'id.bytes'}
_U64 = {'node.length', 'node.charge', 'node.offset', 'shape.offset', 'token.offset',
        'int.offset', 'int.exponent'}
OWNER_BYTES = 4096
# Measured (tracemalloc, CPython 3.12, numpy) retained cost of one in-memory
# record beyond its column bytes: the parsed metadata per raw metadata byte, and
# per column the ndarray and bytes headers, plus the record, column map and
# memory-view objects. A 20-column record with 2,593 B of metadata holds about
# 20 KB besides its columns and the content_cache carrier (a1 overheads.json).
_RECORD_FIXED = 4096
_RECORD_PER_COLUMN = 256
_METADATA_PER_BYTE = 5
# Measured Python objects of one row reference in a row block (RecordRef and
# its instance dictionary, the tuple slot); its owner carrier is charged by
# content_cache.retain() separately.
_ROW_REF_BYTES = 768
# Measured transient of decoding one scalar of ``length`` canonical bytes
# (parts, join, decoder str), beyond the decoded result; see _export_ref.
_SCALAR_DECODE_FACTOR = 3
_SCALAR_DECODE_BLOCK = 4*T.CHUNK
# R1: exact Python-scalar reads of the authenticated little-endian columns
# through memoryview casts (the values .item() returns, without one numpy
# scalar per read). Used only on a little-endian host whose struct sizes equal
# the column widths; anywhere else every read keeps the numpy route.
_FORMATS = {'|u1': 'B', '<u2': 'H', '<u4': 'I', '<u8': 'Q', '<f8': 'd'}
_CAST = sys.byteorder == 'little' and all(struct.calcsize(code) == np.dtype(dtype).itemsize
                                          for dtype, code in _FORMATS.items())
# Inside one read batch, a pinned-page column read re-checks liveness,
# cancellation and its page's batch pin on every _ACCESS_CHECK-th access and
# on every page change; freshness stays checked before and after each batch.
_ACCESS_CHECK = 64
# Subtrees up to this canonical width are decoded by one C JSON decode of
# their exact canonical bytes in the large export route (buffer + decoder str
# copy stay inside the export charge's fixed 65,536 B part).
_DECODE_SUBTREE = 16384
_NULL_JSON, _TRUE_JSON, _FALSE_JSON = T.canonical(None), T.canonical(True), T.canonical(False)
# Item 14: a view's page binding and cache key (canonical binding, its wire
# fields, the key digest) depend only on the view's fixed identity, the
# column's descriptor and one authenticated cursor entry (or one complete
# small column). At most this many rows keep them beside the bounded cursor
# index. A row is booked at the cursor row's 2,048 B (its entry may outlive a
# cursor eviction) plus the binding bound and the key, tuple and slot objects;
# a binding over the bound is never kept (it is rebuilt per access as before).
_PAGE_KEY_ROWS = 128+len(_NAMES)
_PAGE_KEY_ROW_BYTES = 4096
_PAGE_KEY_BINDING_MAX = 1024
# L3: a view's batch registry and its verified page pins are carried from one
# outer read batch to the next of the same _Segment (see read_batch). They stay
# booked at their existing charges: the registry's and, per pin, its holder's
# charged_bytes (the page allocation plus, for a cache hit's share, its own
# carrier; never the cache entry's charge as well). No new reservation. Caps:
# the registry's 128 pages and _CARRY_VIEW_BYTES booked per view (trimmed
# LRU-first); _CARRY_TOTAL_BYTES booked across the process (refused and
# dropped beyond it). The process total adds the views' booked bytes, so an
# allocation pinned by two views of one segment counts once per view. Carried
# pins yield to eviction pressure and scope close (_CarryReclaimer).
_CARRY_VIEW_BYTES = 10 << 20
_CARRY_TOTAL_BYTES = 32 << 20
# Lock order: a segment's _read_lock, then a view's _carry_lock, then
# _CARRY_LOCK. Code here takes no other lock under the last two and drops no
# registry or pin there (their finalizers take a scope's _charges_lock); a
# collection may still run such finalizers inside them, which is safe because
# no holder of _charges_lock waits for either lock: the reclaimer is never
# called under it, and a collected view's __del__ never blocks. __del__ pushes
# its carried bytes onto _COLLECTED, and carry_stats and _carry return them
# under _CARRY_LOCK.
_CARRY_LOCK = threading.RLock()
_COLLECTED = deque()
_CARRY_STATS = dict.fromkeys((
    'carried', 'carried_pages', 'adopted', 'refused', 'trimmed', 'booked', 'raw', 'peak_booked', 'peak_raw',
    'view_peak_booked', 'view_peak_raw', 'dropped_close', 'dropped_entry', 'dropped_exception',
    'dropped_fallback', 'dropped_refused', 'dropped_collected', 'dropped_pressure', 'dropped_scope_close'), 0)
# One reclaimer per retained scope while any of its views carries (see
# _CarryReclaimer); it holds the scope weakly, so the entry dies with it.
_RECLAIMERS = weakref.WeakKeyDictionary()


def _drain_collected():
    # Under _CARRY_LOCK: return the bytes of views collected since the last drain.
    stats = _CARRY_STATS
    while True:
        try:
            booked, raw = _COLLECTED.popleft()
        except IndexError:
            return
        stats['booked'] -= booked
        stats['raw'] -= raw
        stats['dropped_collected'] += 1


def carry_stats():
    """L3 counters and current/peak carried bytes (booked and raw), process-wide."""
    with _CARRY_LOCK:
        _drain_collected()
        return dict(_CARRY_STATS)


def _carry_count(name, count=1):
    with _CARRY_LOCK:
        _CARRY_STATS[name] += count


class _CarryReclaimer:
    """L3: carried pins yield to eviction and to scope close.

    Carried pins pin their cache entries, which the page cache cannot evict.
    This object sits in the scope's cache set, which
    RetainedScope.evict_unpinned (and so every reservation under pressure) and
    RetainedScope.close walk, with a ContentCache's protocol there (category,
    _evict, close). An eviction request first evicts unpinned pages; only if
    that falls short are the scope's carried registries released and the pages
    they unpinned evicted. Scope close releases them all. Each view's carry is
    taken under that view's own _carry_lock, which is held only to move the
    carried registry in or out, never across a batch body; so a carry is
    reclaimable while any thread reads the same segment. A view inside a
    batch has nothing carried (it adopted its carry at entry) and its active
    registry is never touched here.
    """
    category = 'pages'

    def __init__(self, scope):
        self._scope = weakref.ref(scope)
        self._views = weakref.WeakSet()
        self._nested = threading.local()

    def _evict(self, *, requested_bytes, needed_bytes=0, needed_entries=0):
        scope = self._scope()
        if scope is None or not requested_bytes or getattr(self._nested, 'active', False):
            return 0
        self._nested.active = True
        try:
            before = scope.retained_budget.reserved_bytes
            scope.evict_unpinned(requested_bytes=requested_bytes, category=self.category)
            short = before-scope.retained_budget.reserved_bytes < requested_bytes
            if short and self._release('dropped_pressure'):
                scope.evict_unpinned(requested_bytes=requested_bytes, category=self.category)
            return max(0, before-scope.retained_budget.reserved_bytes)
        finally:
            self._nested.active = False

    def close(self):
        self._release('dropped_scope_close')

    def _release(self, reason):
        with _CARRY_LOCK:
            views = tuple(self._views)
        released = 0
        for view in views:
            taken = view._detach_carried()
            if taken is not None:
                _close_pages(taken[0])
                _carry_count(reason)
                released += 1
        return released


def _reclaimer(scope):
    """The scope's carry reclaimer, registered in its cache set; None (no carry) without one."""
    caches = getattr(scope, '_caches', None)
    lock = getattr(scope, '_charges_lock', None)
    if not isinstance(caches, weakref.WeakSet) or lock is None:
        return None
    with _CARRY_LOCK:
        reclaimer = _RECLAIMERS.get(scope)
        created = reclaimer is None
        if created:
            reclaimer = _RECLAIMERS[scope] = _CarryReclaimer(scope)
    if created:
        # Not under _CARRY_LOCK: nothing is taken under it (lock order above).
        with lock:
            caches.add(reclaimer)
    return reclaimer


def _close_pages(registry):
    """Close a registry taken out of its view, and its pins; the view's batch totals are left alone."""
    pages = registry.value
    for owner in pages.values():
        owner.close()
    pages.clear()
    registry.close()


def _cast(buffer, dtype):
    """Exact scalar view of one complete column buffer, or None (keep .item())."""
    code = _FORMATS.get(dtype) if _CAST else None
    if code is None:
        return None
    try:
        return memoryview(buffer).cast('B').cast(code)
    except (TypeError, ValueError):
        return None


class _Overflow(Exception):
    """A node's emitted bytes exceed the bound it was rendered under."""


def _record_charge(total, metadata_bytes, columns):
    return total+_RECORD_FIXED+_METADATA_PER_BYTE*metadata_bytes+_RECORD_PER_COLUMN*columns


def _owned(scope, count, factory, purpose='record-output', dependencies=()):
    with scope.reserve(ChargeSpec(purpose, count), required=True, cancel=None) as reservation:
        return reservation.commit(factory(), dependencies=dependencies)


def _bound(value, name, maximum=(1 << 64)-1):
    T.require(type(value) is int and 0 <= value <= maximum, 'invalid '+name)


class _Memory:
    def __init__(self, arrays):
        self.arrays = arrays

    def value(self, name, index):
        return self.arrays[name][index].item()

    def raw(self, name, start, stop):
        return memoryview(self.arrays[name]).cast('B')[start:stop]


@dataclass(frozen=True, slots=True)
class _ColumnPage:
    binding: bytes
    expected_sha256: str
    expected_bytes: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class _NativeChunkPage:
    binding: bytes
    expected_sha256: str
    expected_bytes: int
    raw: bytes
    descriptor: bytes


def _column_key(epoch, binding, expected_sha256, expected_bytes):
    digest = sha256(b'atlas.record-column-page.v1\0')
    digest.update(len(binding).to_bytes(8, 'little'))
    digest.update(binding)
    digest.update(bytes.fromhex(expected_sha256))
    digest.update(expected_bytes.to_bytes(8, 'little'))
    return VerifiedCacheKey('pages', epoch, digest.digest())


def _verify_column_page(key, page):
    if (type(page) not in (_ColumnPage, _NativeChunkPage) or type(page.raw) is not bytes or
            not len(page.raw) == page.expected_bytes <= T.CHUNK or
            _column_key(key.process_epoch, page.binding, page.expected_sha256,
                        page.expected_bytes) != key):
        return False
    if type(page) is _ColumnPage:
        return sha256(page.raw).hexdigest() == page.expected_sha256
    if type(page.descriptor) is not bytes or len(page.descriptor) > 1024:
        return False
    # The typed chunk digest sha256(prefix + descriptor + NUL + raw), fed in
    # parts: the same digest without an unbooked concatenated copy per check.
    digest = sha256(b'atlas-typed-chunk-v1\0')
    digest.update(page.descriptor)
    digest.update(b'\0')
    digest.update(page.raw)
    return digest.hexdigest() == page.expected_sha256


class _OptionalScratch(T.Scratch):
    def __init__(self, budget, size, category='record-column-lookup'):
        self._lease = budget.try_reserve(size, category=category)
        self.admitted = self._lease.__enter__()


class _BatchPage:
    """Internal immutable borrow, valid only while the compound read owns it."""
    __slots__ = ('_owner', '_array', '_view', '_booked', '_raw', '_touched')

    def __init__(self, owner, touched=None):
        self._owner = owner
        self._array = None
        self._view = None
        # L3 booking (see _CARRY_VIEW_BYTES) and real page bytes.
        self._booked = owner.charged_bytes
        self._raw = len(owner.value.raw)
        self._touched = touched

    def view(self, code):
        # One exact scalar view of the pinned verified page; dropped on close
        # and when its batch ends (L3: the page may be carried), so no reader
        # outside a batch keeps a view of a pinned page.
        view = self._view
        if view is None:
            view = self._view = memoryview(self._owner.value.raw).cast(code)
            if self._touched is not None:
                self._touched.add(self)
        return view

    def scalar(self, index, dtype):
        code = _FORMATS.get(dtype.str) if _CAST else None
        if code is not None:
            return self.view(code)[index]
        if self._array is None:
            self._array = np.frombuffer(self._owner.value.raw, dtype=dtype)
            if self._touched is not None:
                self._touched.add(self)
        return self._array[index].item()

    def unview(self):
        self._array = None
        self._view = None

    def close(self):
        self._array = None
        self._view = None
        self._owner.close()
        if self._touched is not None:
            self._touched.discard(self)

    @property
    def value(self):
        return self._owner.value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _Segment:
    """No eager array load. Payload reads remain bounded and owned by WP1."""
    def __init__(self, segment, descriptors, *, use_page_cache=True):
        self.segment, self.descriptors = segment, descriptors
        self.cache = None
        self._page_cursors = None
        self._page_keys = self._page_key_lock = None
        self._batch_pages = None
        self._batch_depth = 0
        # L3: the registry carried between outer batches (never read outside
        # read_batch), its booked/raw bytes, the active registry's page totals
        # and the pages given a view in the current batch. _carry_lock guards
        # the three carried fields only (reentrant, as _CARRY_LOCK).
        self._carry_lock = threading.RLock()
        self._carried = None
        self._carried_booked = self._carried_raw = 0
        self._batch_booked = self._batch_raw = 0
        # Only live registry pages need withdrawal at the block boundary.
        # Evicted/closed pages remove themselves, keeping this set within the
        # same 128-page bound even during a long batch.
        self._touched = set()
        self._carry_enabled = True
        self._reclaimer = None  # this scope's _CarryReclaimer, once this view has carried
        self.file_identity = segment.cache_identity() if use_page_cache else None
        if self.file_identity is not None:
            T.require(type(self.file_identity) is bytes and len(self.file_identity) == 32,
                      'bounded authenticated file identity required for cached columns')
            try:
                self.cache = get_content_cache(segment.scope, 'pages', enabled=True,
                                               verifier=_verify_column_page)
            except MemoryLimitError:
                # Optional reuse must not prevent the existing required read.
                self.cache = None
        if self.cache is not None:
            # Item 14: bounded (binding, key) rows in the shared retained scope;
            # declined, every access rebuilds them as before. The memo has its
            # own lock: small-column sources need not carry a segment read lock,
            # and it is never held while another lock is taken.
            reservation = segment.scope.reserve(
                ChargeSpec('record-page-keys', _PAGE_KEY_ROWS*_PAGE_KEY_ROW_BYTES+4096),
                required=False, cancel=segment.cancel)
            if reservation is not None:
                with reservation:
                    self._page_keys = reservation.commit(OrderedDict())
                self._page_key_lock = threading.Lock()
        if self.cache is not None and any(row['shape'][0]*np.dtype(row['dtype']).itemsize > T.CHUNK
                                           for row in descriptors.values()):
            # At most 128 authenticated leaf bindings, not another payload
            # cache. Their bounded index shares the existing retained scope.
            reservation = segment.scope.reserve(ChargeSpec('record-page-cursors', 128*2048+4096),
                                                 required=False, cancel=segment.cancel)
            if reservation is not None:
                with reservation:
                    self._page_cursors = reservation.commit(OrderedDict())

    @contextmanager
    def read_batch(self):
        """Pin at most 128 existing verified immutable pages for one atomic read.

        No payload copy or independent cache: these are charged borrows from
        the shared page cache, served only inside a verified read. L3: after a
        normal exit of this view's outer batch, the registry and its pins are
        carried to this view's next outer batch (_carry: trimmed LRU-first to
        _CARRY_VIEW_BYTES, refused and dropped beyond _CARRY_TOTAL_BYTES),
        booked at their existing charges. When this batch's verified read is
        the store set's outermost read, the carry follows its closing
        freshness check. When it is nested in another view's batch or another
        verified read of the same store set (compact_store's preparation
        enters two batches in one statement), the carry happens before that
        enclosing read's closing check, and a refusal there does not drop it.
        That is safe because the store set never re-pins or refreshes a
        changed token, so the next batch's entry check refuses before
        anything carried is adopted (cross-lane contract C-L3S1). Carried
        pages are adopted only after the next batch has entered its verified
        read, and dropped on release() (view close), a failed entry, an
        uncached fallback, the caps, an eviction request that unpinned pages
        cannot meet, or scope close (_CarryReclaimer). Outside a batch no reader sees them
        (_batch_pages is None, and the batch's page views are dropped).
        A carried page is not re-verified on each hit for the life of the
        view (it was verified when cached and is content-addressed); the
        batch's verified read still checks the file identity. Failed frames
        keep their paid registry until their traceback is freed; it is never
        carried.
        """
        if self.cache is None:
            # No page cache: no registry, nothing carried (as before).
            with self.segment.verified_read():
                self._batch_depth += 1
                try:
                    yield
                finally:
                    self._batch_depth -= 1
            return
        with self.segment._read_lock:
            outer = self._batch_depth == 0
            # Leave the carry reclaimable while verified_read admits its
            # required entry owner. No reader can adopt it before entry passes.
            registry = None
            try:
                with self.segment.verified_read():
                    if outer:
                        registry = self._take_carried()
                        if registry is not None:
                            _carry_count('adopted')
                        else:
                            self._batch_booked = self._batch_raw = 0
                            reservation = self.segment.scope.reserve(
                                ChargeSpec('record-batch-page-borrows', 128*2048+4096),
                                required=False, cancel=self.segment.cancel)
                            if reservation is not None:
                                with reservation:
                                    registry = reservation.commit(OrderedDict())
                        self._batch_pages = registry
                    self._batch_depth += 1
                    try:
                        yield
                    finally:
                        self._batch_depth -= 1
            except BaseException:
                if outer:
                    self._unview_touched()
                    carried = self._take_carried()
                    if carried is not None:
                        self._close_registry(carried)
                        _carry_count('dropped_entry')
                    if self._batch_pages is not None:
                        # This frame (registry) keeps the pins paid with the
                        # traceback; they are not carried.
                        self._batch_pages = None
                        _carry_count('dropped_exception')
                raise
            if outer:
                self._carry()

    def _unview_touched(self):
        touched = self._touched
        for page in touched:
            page.unview()
        touched.clear()

    def _close_registry(self, registry):
        _close_pages(registry)
        self._batch_booked = self._batch_raw = 0

    def _detach_carried(self):
        """(registry, booked, raw) taken out of the carry and its bytes returned, or None."""
        with self._carry_lock:
            registry = self._carried
            if registry is None:
                return None
            self._carried = None
            booked, raw = self._carried_booked, self._carried_raw
            self._carried_booked = self._carried_raw = 0
            with _CARRY_LOCK:
                _CARRY_STATS['booked'] -= booked
                _CARRY_STATS['raw'] -= raw
        return registry, booked, raw

    def _take_carried(self):
        # The owning thread: the carry becomes this view's registry (batch totals set).
        taken = self._detach_carried()
        if taken is None:
            return None
        registry, booked, raw = taken
        self._batch_booked, self._batch_raw = booked-registry.charged_bytes, raw
        return registry

    def _carry(self):
        """After a normal outer exit: trim, then carry or refuse the registry."""
        self._unview_touched()
        registry, self._batch_pages = self._batch_pages, None
        if registry is None:
            return
        pages = registry.value
        if self._carry_enabled and pages and self._reclaimer is None:
            self._reclaimer = _reclaimer(self.segment.scope)
        if not self._carry_enabled or not pages or self._reclaimer is None:
            self._close_registry(registry)
            return
        booked = registry.charged_bytes+self._batch_booked
        trimmed = 0
        while booked > _CARRY_VIEW_BYTES and pages:
            _, page = pages.popitem(last=False)
            booked -= page._booked
            self._batch_raw -= page._raw
            page.close()
            trimmed += 1
        raw = self._batch_raw
        # Counted and stored together, so a reclaimer sees both or neither.
        with self._carry_lock:
            with _CARRY_LOCK:
                _drain_collected()
                stats = _CARRY_STATS
                stats['trimmed'] += trimmed
                refused = stats['booked']+booked > _CARRY_TOTAL_BYTES
                if refused:
                    stats['refused'] += 1
                    stats['dropped_refused'] += 1
                else:
                    self._reclaimer._views.add(self)
                    stats['carried'] += 1
                    stats['carried_pages'] += len(pages)
                    stats['booked'] += booked
                    stats['raw'] += raw
                    stats['peak_booked'] = max(stats['peak_booked'], stats['booked'])
                    stats['peak_raw'] = max(stats['peak_raw'], stats['raw'])
                    stats['view_peak_booked'] = max(stats['view_peak_booked'], booked)
                    stats['view_peak_raw'] = max(stats['view_peak_raw'], raw)
            if not refused:
                self._carried, self._carried_booked, self._carried_raw = registry, booked, raw
        if refused:
            self._close_registry(registry)

    def release(self):
        """L3: drop carried pins and the view's bounded memos (CompactRecord.close).

        A column, _Access or stream that outlives the view may keep this
        object. Afterwards nothing is carried again and its reads take the
        rebuilt-key and uncached routes, as when those optional reservations
        were declined. Inside an active batch (a misuse) only carrying stops.
        """
        with self.segment._read_lock:
            self._carry_enabled = False
            if self._batch_depth:
                return
            registry = self._take_carried()
            if registry is not None:
                self._close_registry(registry)
                _carry_count('dropped_close')
            self._unview_touched()
            keys, cursors = self._page_keys, self._page_cursors
            self._page_keys = self._page_cursors = None
            for owner in (keys, cursors):
                if owner is not None:
                    owner.close()

    def __del__(self):
        # Backstop for a holder without release(): the carried pins go with
        # this object (their owners close when collected); its bytes are
        # queued for the next drain. Never a blocking acquire (lock order
        # above). The carry lock is busy here only when a reclaimer revived
        # this object through its weak set, and that reclaimer takes the carry.
        lock = getattr(self, '_carry_lock', None)
        if lock is None or getattr(self, '_carried', None) is None or not lock.acquire(blocking=False):
            return
        registry = None
        try:
            registry = self._carried
            if registry is not None:
                self._carried = None
                _COLLECTED.append((self._carried_booked, self._carried_raw))
                self._carried_booked = self._carried_raw = 0
        finally:
            lock.release()
        del registry  # its pins close here, outside the carry lock

    def _drop_batch_pages(self):
        # Before an uncached read: drop the active registry and any carried one.
        registry, self._batch_pages = self._batch_pages, None
        if registry is not None:
            self._close_registry(registry)
            _carry_count('dropped_fallback')
        if self._carried is not None:
            # Under the carry lock alone (as a reclaimer): it is outside any
            # batch, so no batch totals change.
            taken = self._detach_carried()
            if taken is not None:
                _close_pages(taken[0])
                _carry_count('dropped_fallback')

    def _borrowed(self, key):
        if self._batch_pages is None:
            return None
        pages = self._batch_pages.value
        owner = pages.get(key)
        if owner is not None:
            pages.move_to_end(key)
            return owner
        return None

    def _pin_page(self, key, owner):
        if owner is None or self._batch_pages is None:
            return owner
        pages = self._batch_pages.value
        if len(pages) == 128:
            _, previous = pages.popitem(last=False)
            self._batch_booked -= previous._booked
            self._batch_raw -= previous._raw
            previous.close()
        page = _BatchPage(owner, self._touched)
        pages[key] = page
        self._batch_booked += page._booked
        self._batch_raw += page._raw
        return page

    def _fill(self, name, descriptor, binding, size):
        reservation = self.segment.scope.reserve(
            ChargeSpec('record-column-page', size+len(binding)+4096), required=False,
            cancel=self.segment.cancel)
        if reservation is None:
            return None
        with reservation:
            with self.segment.read(name, 0, descriptor['shape'][0], max_owned_bytes=T.CHUNK+OWNER_BYTES) as source:
                return reservation.commit(_ColumnPage(binding, descriptor['sha256'], size,
                                          bytes(memoryview(source.value))))

    def _page_key(self, row, entry, descriptor, dtype, size, make, *args):
        """(binding, key) for one page, from the bounded memo or rebuilt.

        A row is used only for the identical authenticated cursor entry object
        (None for a complete small column), the identical descriptor object
        with the same digest and shape values, the same dtype, size and process
        epoch: everything the rebuilt binding and key are computed from besides
        the view's fixed file identity and segment reference. The memo keeps
        the entry alive, so identity cannot be matched by a reused address. The
        cache still verifies every page against the key it returns.
        """
        keys, lock = self._page_keys, self._page_key_lock
        if keys is None or lock is None:
            return make(*args)
        facts = (dtype.str, size, self.segment.scope.process_epoch, descriptor['sha256'],
                 tuple(descriptor['shape']))
        with lock:
            memo = keys.value.get(row)
            if memo is not None and memo[0] is entry and memo[1] is descriptor and memo[2] == facts:
                keys.value.move_to_end(row)
                return memo[3], memo[4]
        binding, key = make(*args)
        if len(binding) <= _PAGE_KEY_BINDING_MAX:
            with lock:
                rows = keys.value
                rows.pop(row, None)
                if len(rows) >= _PAGE_KEY_ROWS:
                    rows.popitem(last=False)
                rows[row] = (entry, descriptor, facts, binding, key)
        return binding, key

    def _small_key(self, name, descriptor, dtype, size):
        binding = T.canonical(dict(file_identity=self.file_identity.hex(),
            segment=self.segment.info.ref.to_wire(), name=name, dtype=dtype.str,
            shape=descriptor['shape'], start=0, stop=descriptor['shape'][0]))
        return binding, _column_key(self.segment.scope.process_epoch, binding, descriptor['sha256'], size)

    def _native_key(self, name, descriptor, dtype, start, stop, chunk_id, owner, size):
        binding = T.canonical(dict(kind='native-chunk-v1', file_identity=self.file_identity.hex(),
            segment=self.segment.info.ref.to_wire(), name=name, dtype=dtype.str,
            shape=descriptor['shape'], start=start, stop=stop, owner=owner))
        return binding, _column_key(self.segment.scope.process_epoch, binding, chunk_id, size)

    def _cached_owner(self, name, descriptor, dtype, size):
        self.segment.check_unchanged()
        borrowed = self._borrowed((name, 0))
        if borrowed is not None:
            return borrowed
        scratch = _OptionalScratch(self.segment.scope.run_budget, 16384)
        if not scratch.admitted:
            return None
        binding, key = self._page_key((name, None), None, descriptor, dtype, size,
                                      self._small_key, name, descriptor, dtype, size)
        held = self.cache.get(key, cancel=self.segment.cancel)
        if held is None:
            # Independent paid immutable copy lets the shared cache
            # outlive this view without pinning its SegmentView owner.
            held = self._fill(name, descriptor, binding, size)
            if held is not None:
                self.cache.offer_verified(key, held, cancel=self.segment.cancel)
        return self._pin_page((name, 0), held)

    def _cached_value(self, name, index, descriptor, dtype, size):
        held = self._cached_owner(name, descriptor, dtype, size)
        if held is None:
            return None
        with held:
            result = (held.scalar(index, dtype) if isinstance(held, _BatchPage) else
                      np.frombuffer(held.value.raw, dtype=dtype, count=1,
                                    offset=index*dtype.itemsize)[0].item())
        self.segment.check_unchanged()
        return result

    def _native_binding(self, name, index, descriptor, dtype):
        with self.segment._read_lock:
            return self._native_binding_locked(name, index, descriptor, dtype)

    def _native_binding_locked(self, name, index, descriptor, dtype):
        width = T.CHUNK//dtype.itemsize
        start = index//width*width
        stop = min(start+width, descriptor['shape'][0])
        cursors, cursor_key = self._page_cursors.value, (name, start)
        entry = cursors.get(cursor_key)
        if entry is not None:
            cursors.move_to_end(cursor_key)
            return entry
        rows = list(self.segment._entries(name=name, start=start, stop=stop))
        T.require(len(rows) == 1, 'native page must bind exactly one authenticated chunk')
        row, body = rows[0], rows[0]['content']
        T.require(body['start'] == start and body['count'] == stop-start and
                  body['dtype'] == dtype.str and math.prod(body['shape']) == descriptor['shape'][0],
                  'native page typed range differs')
        entry = (start, stop, body['chunk_id'], T.canonical(row['descriptor']), row['owner'])
        if len(cursors) == 128:
            cursors.popitem(last=False)
        cursors[cursor_key] = entry
        return entry

    def _cached_native_owner(self, name, index, descriptor, dtype):
        self.segment.check_unchanged()
        start = index//(T.CHUNK//dtype.itemsize)*(T.CHUNK//dtype.itemsize)
        borrowed = self._borrowed((name, start))
        if borrowed is not None:
            return borrowed, start, min(start+T.CHUNK//dtype.itemsize, descriptor['shape'][0])
        scratch = _OptionalScratch(self.segment.scope.run_budget, 16384)
        if not scratch.admitted:
            return None
        entry = self._native_binding(name, index, descriptor, dtype)
        start, stop, chunk_id, native_descriptor, owner = entry
        size = (stop-start)*dtype.itemsize
        binding, key = self._page_key((name, start), entry, descriptor, dtype, size, self._native_key,
                                      name, descriptor, dtype, start, stop, chunk_id, owner, size)
        held = self.cache.get(key, cancel=self.segment.cancel)
        if held is None:
            reservation = self.segment.scope.reserve(ChargeSpec('record-native-page', size+len(binding)+8192),
                                                      required=False, cancel=self.segment.cancel)
            if reservation is None:
                return None
            with reservation:
                raw = self._bound_chunk(owner, chunk_id, native_descriptor, size)
                if raw is None:
                    with self.segment.read(name, start, stop, max_owned_bytes=T.CHUNK+OWNER_BYTES) as source:
                        raw = bytes(memoryview(source.value))
                held = reservation.commit(_NativeChunkPage(binding, chunk_id, size, raw, native_descriptor))
                del raw
            self.cache.offer_verified(key, held, cancel=self.segment.cancel)
        return self._pin_page((name, start), held), start, stop

    def _bound_chunk(self, owner, chunk_id, native_descriptor, size):
        """The bound chunk's verified bytes, without a second index walk (R1).

        The binding (owner, chunk ID, typed descriptor, range) comes from this
        view's authenticated root-to-leaf walk (_native_binding, kept in the
        bounded cursor index). SegmentView.read would walk to the same leaf
        again and then make exactly this resolver call, which verifies the
        chunk's stored checksum and typed content hash. One verified read
        keeps freshness before and after it. None: use SegmentView.read.
        """
        chunk = getattr(sys.modules.get(type(self.segment).__module__), '_chunk', None)
        if chunk is None:
            return None
        with self.segment.verified_read():
            source = chunk(self.segment.resolver, owner, chunk_id, native_descriptor, self.segment.cancel)
            try:
                T.require(len(source.value) == size, 'decoded chunk size differs')
                return bytes(memoryview(source.value))
            finally:
                source.close()

    def _cached_native_raw(self, name, start, stop, descriptor, dtype):
        size = (stop-start)*dtype.itemsize
        if size > T.CHUNK:
            return None
        reservation = self.segment.scope.reserve(ChargeSpec('record-column-slice', 2*size+4096),
                                                  required=False, cancel=self.segment.cancel)
        if reservation is None:
            return None
        with reservation:
            raw = bytearray()
            at = start
            while at < stop:
                result = self._cached_native_owner(name, at, descriptor, dtype)
                if result is None:
                    return None
                held, lo, hi = result
                end = min(stop, hi)
                with held:
                    raw.extend(memoryview(held.value.raw)[(at-lo)*dtype.itemsize:(end-lo)*dtype.itemsize])
                at = end
            self.segment.check_unchanged()
            return reservation.commit(bytes(raw))

    def value(self, name, index):
        descriptor = self.descriptors[name]
        T.require(type(index) is int and 0 <= index < descriptor['shape'][0],
                  'column index outside bounds')
        dtype = np.dtype(descriptor['dtype'])
        size = descriptor['shape'][0]*dtype.itemsize
        if self._batch_pages is not None:
            start = 0 if size <= T.CHUNK else index//(T.CHUNK//dtype.itemsize)*(T.CHUNK//dtype.itemsize)
            page = self._borrowed((name, start))
            if page is not None:
                # The enclosing sealed read checks freshness before and after
                # the batch; keep liveness and cancellation on every access.
                self.segment.check_unchanged()
                return page.scalar(index-start, dtype)
        if self.cache is not None and size <= T.CHUNK:
            # Complete small columns use the authenticated column digest.
            try:
                result = self._cached_value(name, index, descriptor, dtype, size)
            except MemoryLimitError:
                result = None
            if result is not None:
                return result
        elif self.cache is not None and self._page_cursors is not None:
            try:
                page = self._cached_native_owner(name, index, descriptor, dtype)
                if page is not None:
                    held, start, _ = page
                    with held:
                        result = (held.scalar(index-start, dtype) if isinstance(held, _BatchPage) else
                            np.frombuffer(held.value.raw, dtype=dtype, count=1,
                                          offset=(index-start)*dtype.itemsize)[0].item())
                    self.segment.check_unchanged()
                    return result
            except MemoryLimitError:
                pass
        self._drop_batch_pages()
        with self.segment.read(name, index, index+1, max_owned_bytes=65536) as row:
            return np.frombuffer(row.value, dtype=dtype, count=1)[0].item()

    def raw(self, name, start, stop):
        # Keys and string bodies use the same verified column as scalar reads.
        # Return a paid independent slice; no unowned cache backing can escape.
        descriptor = self.descriptors[name]
        dtype = np.dtype(descriptor['dtype'])
        size = descriptor['shape'][0]*dtype.itemsize
        T.require(type(start) is int and type(stop) is int and
                  0 <= start <= stop <= descriptor['shape'][0], 'raw column range outside bounds')
        if self.cache is not None and size <= T.CHUNK:
            try:
                held = self._cached_owner(name, descriptor, dtype, size)
                if held is not None:
                    with held:
                        result = _owned(self.segment.scope, (stop-start)*dtype.itemsize+4096,
                            lambda: bytes(memoryview(held.value.raw)[start*dtype.itemsize:stop*dtype.itemsize]),
                            'record-column-slice')
                        self.segment.check_unchanged()
                        return result
            except MemoryLimitError:
                pass
        elif self.cache is not None and self._page_cursors is not None:
            try:
                result = self._cached_native_raw(name, start, stop, descriptor, dtype)
                if result is not None:
                    return result
            except MemoryLimitError:
                pass
        self._drop_batch_pages()
        return self.segment.read(name, start, stop, max_owned_bytes=65536+2*(stop-start))


class _NoPage:
    __slots__ = ()
    _view = None


_NO_PAGE = _NoPage()


class _ItemColumn:
    """Per-read column access through the backing's own value() (the unchanged route)."""
    __slots__ = ('_columns', '_name')

    def __init__(self, columns, name):
        self._columns, self._name = columns, name

    def __getitem__(self, index):
        return self._columns.value(self._name, index)


def _raw_into(columns, name, out, start, stop):
    """Append raw[start:stop] exactly as CompactRecord._bytes reads it."""
    for at in range(start, stop, T.CHUNK):
        end = min(stop, at+T.CHUNK)
        if isinstance(columns, _Memory):
            out += columns.raw(name, at, end)
        else:
            with columns.raw(name, at, end) as held:
                out += held.value


class _PagedColumn:
    """Exact reads of one sealed column from its verified page pinned in the read batch.

    A read inside the pinned page's range is served from that page. Any other
    read (another page, a dropped pin, every _ACCESS_CHECK-th read) goes
    through _Segment's own route: a pinned page is re-borrowed with
    check_unchanged, an unpinned one is pinned by _Segment.value (verified
    page cache, authenticated fill). With no batch registry (outside a batch,
    no cache, an optional admission declined) every read is _Segment.value
    and every byte range _Segment.raw, exactly as before.
    """
    __slots__ = ('_code', '_columns', '_count', '_hi', '_lo', '_name', '_page', '_quota', '_width')

    def __init__(self, columns, name, code):
        descriptor = columns.descriptors[name]
        itemsize = np.dtype(descriptor['dtype']).itemsize
        self._columns, self._name, self._code = columns, name, code
        self._count = descriptor['shape'][0]
        self._width = self._count if self._count*itemsize <= T.CHUNK else T.CHUNK//itemsize
        self._page, self._lo, self._hi, self._quota = _NO_PAGE, 0, 0, _ACCESS_CHECK

    def _bind(self, index):
        columns = self._columns
        if columns._batch_pages is None or not (type(index) is int and 0 <= index < self._count):
            return False
        start = index//self._width*self._width
        key = (self._name, start)
        page = columns._borrowed(key)
        if page is None:
            # The existing verified route pins the page in this batch.
            columns.value(self._name, index)
            page = columns._borrowed(key)
            if page is None:
                return False
        else:
            columns.segment.check_unchanged()
        view = page.view(self._code)
        self._page, self._lo, self._hi, self._quota = page, start, start+len(view), _ACCESS_CHECK
        return True

    def __getitem__(self, index):
        view = self._page._view
        if view is not None and self._lo <= index < self._hi:
            self._quota -= 1
            if self._quota > 0:
                return view[index-self._lo]
        if self._bind(index):
            return self._page._view[index-self._lo]
        return self._columns.value(self._name, index)

    def put(self, out, start, stop):
        T.require(type(start) is int and type(stop) is int and 0 <= start <= stop <= self._count,
                  'raw column range outside bounds')
        at = start
        while at < stop:
            view = self._page._view
            self._quota -= 1
            if view is None or not self._lo <= at < self._hi or self._quota <= 0:
                if not self._bind(at):
                    _raw_into(self._columns, self._name, out, at, stop)
                    return
                view = self._page._view
            end = min(stop, self._hi)
            out += view[at-self._lo:end-self._lo]
            at = end


class _Access:
    """Per-traversal exact column access (no state outlives the traversal).

    In-memory columns are read through memoryview casts of their frozen
    arrays; sealed segment columns through _PagedColumn; anything else (and
    any dtype without an exact cast) through the backing's own value()/raw().
    """
    __slots__ = ('_columns', '_views')

    def __init__(self, columns):
        self._columns, self._views = columns, {}

    def column(self, name):
        view = self._views.get(name)
        if view is None:
            columns = self._columns
            view = None
            if isinstance(columns, _Memory):
                array = columns.arrays[name]
                view = _cast(array, array.dtype.str)
            elif isinstance(columns, _Segment) and _CAST:
                code = _FORMATS.get(columns.descriptors[name]['dtype'])
                if code is not None:
                    view = _PagedColumn(columns, name, code)
            if view is None:
                view = _ItemColumn(columns, name)
            self._views[name] = view
        return view

    def put(self, out, name, start, stop):
        """Append the byte column's raw[start:stop] to out."""
        view = self.column(name)
        if type(view) is memoryview:
            out += view[start:stop]
        elif type(view) is _PagedColumn:
            view.put(out, start, stop)
        else:
            _raw_into(self._columns, name, out, start, stop)

    def get(self, name, start, stop):
        out = bytearray()
        self.put(out, name, start, stop)
        return bytes(out)


def _metadata(raw):
    T.require(type(raw) is bytes and len(raw) <= 65536, 'bounded immutable record metadata required')
    def pairs(rows):
        result = {}
        for key, value in rows:
            T.require(key not in result, 'duplicate metadata key')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError) as exc:
        raise ContractError('invalid record metadata') from exc
    T.require(type(value) is dict and set(value) == {'schema', 'profile', 'features', 'root', 'identity', 'arrays'},
              'unknown/missing record metadata field')
    T.require(T.canonical(value) == raw, 'noncanonical record metadata')
    T.require(value['schema'] == T.SCHEMA and value['profile'] == T.PROFILE and value['features'] == [],
              'unknown physical schema, profile or feature')
    identity = LogicalIdentity.from_wire(value['identity'])
    descriptors = value['arrays']
    T.require(type(descriptors) is dict and set(descriptors) == _NAMES, 'unknown/missing record column')
    for name, row in descriptors.items():
        T.require(type(row) is dict and set(row) == {'dtype', 'shape', 'sha256'}, 'invalid column descriptor')
        allowed = ('|u1',) if name in _BYTE else ('<u8',) if name in _U64 else ('<f8',) if name == 'float.value' else ('|u1', '<u2', '<u4', '<u8')
        T.require(row['dtype'] in allowed and type(row['shape']) is list and len(row['shape']) == 1,
                  'invalid authenticated dtype/shape')
        _bound(row['shape'][0], 'column length')
        T.require(type(row['sha256']) is str and len(row['sha256']) == 64 and
                  all(c in '0123456789abcdef' for c in row['sha256']), 'invalid column digest')
    return value, identity


class _CanonicalMemo:
    """Optional paid bytes for small DAG nodes, confined to one traversal.

    This is not a logical-identity shortcut: every occurrence still enters the
    ordered byte stream. Both actual construction and retained bytes are bound.
    """
    CAPACITY = 1 << 20
    MAX_ENTRIES = 1024

    def __init__(self, scope):
        self.owner = None
        self.render = None
        self.free = self.CAPACITY-4096
        reservation = scope.reserve(ChargeSpec('record-canonical-reuse', self.CAPACITY),
                                    required=False, cancel=None)
        if reservation is not None:
            with reservation:
                self.owner = reservation.commit(OrderedDict())


class CompactRecord:
    """Sealed exact logical identity with explicitly owned traversal/expansion."""
    def __init__(self, owner, metadata, identity, columns, check):
        self._owner, self._meta, self._identity = owner, metadata, identity
        self._columns, self._check = columns, check
        self._root = metadata['root']

    @classmethod
    def _from_built(cls, raw_metadata, arrays, *, scope, check):
        metadata, identity = _metadata(raw_metadata)
        total = sum(a.nbytes for a in arrays.values())
        owner = _owned(scope, _record_charge(total, len(raw_metadata), len(arrays)),
                       lambda: (raw_metadata, T.freeze_arrays(arrays)), 'record-tables')
        return cls(owner, metadata, identity, _Memory(owner.value[1]), check)

    @classmethod
    def _from_columns(cls, build, total, *, scope, check, metadata_bound):
        """Columns are materialised once, inside the retained reservation that keeps them.

        ``build`` returns (raw_metadata, arrays) whose column bytes total exactly
        ``total`` and whose metadata is at most ``metadata_bound`` bytes; the
        reservation is admitted before any column is allocated.
        """
        def make():
            raw_metadata, arrays = build()
            T.require(sum(a.nbytes for a in arrays.values()) == total and len(arrays) == len(_NAMES) and
                      len(raw_metadata) <= metadata_bound, 'built record differs from its funded plan')
            return raw_metadata, T.freeze_arrays(arrays)
        owner = _owned(scope, _record_charge(total, metadata_bound, len(_NAMES)), make, 'record-tables')
        metadata, identity = _metadata(owner.value[0])
        return cls(owner, metadata, identity, _Memory(owner.value[1]), check)

    @classmethod
    def from_payload(cls, raw_metadata, arrays, *, scope, check, expected_identity=None):
        metadata_scratch = T.Scratch(scope.run_budget, 2 << 20)
        metadata, identity = _metadata(raw_metadata)
        T.require(set(arrays) == _NAMES, 'unknown/missing record array')
        for name, descriptor in metadata['arrays'].items():
            array = arrays[name]
            T.require(type(array) is np.ndarray and array.dtype.str == descriptor['dtype'] and
                      list(array.shape) == descriptor['shape'] and array.flags.c_contiguous,
                      'column descriptor differs')
            T.require(sha256(memoryview(array).cast('B')).hexdigest() == descriptor['sha256'], 'column digest differs')
        if expected_identity is not None:
            T.require(expected_identity == identity, 'logical identity differs')
        result = cls._from_built(raw_metadata, arrays, scope=scope, check=check)
        result._validate()
        del metadata_scratch
        return result

    @classmethod
    def from_segment(cls, segment, metadata=None, *, check=lambda: None, use_page_cache=True):
        """Own the SegmentView until all child references/streams are released.

        Metadata is the original bounded codec payload. WP1 authenticates the
        segment bindings; this layer checks physical dispatch and logical bytes.
        """
        scope = segment.scope
        metadata_scratch = T.Scratch(scope.run_budget, 2 << 20)
        if metadata is None:
            with segment.metadata() as held:
                raw = held.value
                parsed, identity = _metadata(raw)
        else:
            raw = metadata
            parsed, identity = _metadata(raw)
        T.require(segment.info.ref.identity == identity, 'segment logical identity differs')
        T.require(segment.info.array_count == len(_NAMES), 'segment array inventory differs')
        if segment.cache_identity() is not None:
            # One authenticated ordered walk, including empty columns. The
            # segment validates physical ranges; verify full codec inventory,
            # typed descriptors and each column digest here as before.
            seen, current, digest, count = set(), None, None, 0
            with segment.scan(max_owned_bytes=2*T.CHUNK) as stream:
                for block in stream:
                    with block:
                        row = block.value
                        name = row.info.name
                        T.require(name in parsed['arrays'], 'unknown segment column')
                        descriptor = parsed['arrays'][name]
                        if name != current:
                            if current is not None:
                                T.require(digest.hexdigest() == parsed['arrays'][current]['sha256'] and
                                          count == parsed['arrays'][current]['shape'][0],
                                          'segment column digest/extent differs')
                            T.require(name not in seen, 'repeated segment column')
                            seen.add(name)
                            current, digest, count = name, sha256(), 0
                        T.require(row.info.dtype == descriptor['dtype'] and
                                  list(row.info.shape) == descriptor['shape'] and row.start == count,
                                  'segment column descriptor/range differs')
                        digest.update(row.data)
                        count = row.stop
            T.require(seen == _NAMES and digest.hexdigest() == parsed['arrays'][current]['sha256'] and
                      count == parsed['arrays'][current]['shape'][0],
                      'segment column inventory/digest/extent differs')
        else:
            for name, descriptor in parsed['arrays'].items():
                with segment.info.array(name) as held:
                    info = held.value
                    T.require(info.dtype == descriptor['dtype'] and list(info.shape) == descriptor['shape'],
                              'segment column descriptor differs')
                digest = sha256()
                with segment.iter(name, block_bytes=T.CHUNK, max_owned_bytes=2*T.CHUNK) as stream:
                    for block in stream:
                        with block:
                            digest.update(block.value)
                T.require(digest.hexdigest() == descriptor['sha256'], 'segment column digest differs')
        # Segment is intentionally owned as a dependency by this wrapper. Its
        # close is delayed until this backing allocation has no live borrows.
        owner = _owned(scope, 65536+8*len(raw), lambda: raw, 'record-segment-view',
                       dependencies=(segment._owner,))
        result = cls(owner, parsed, identity, _Segment(segment, parsed['arrays'],
                     use_page_cache=use_page_cache), check)
        result._validate()
        del metadata_scratch
        return result

    @property
    def scope(self):
        return self._owner.scope

    def _live(self):
        self._owner.value
        self._check()

    def _read_batch(self):
        return (self._columns.read_batch()
                if isinstance(self._columns, _Segment) else nullcontext())

    def identity(self):
        self._live()
        return self._identity

    def root(self):
        self._live()
        return RecordRef(self, self._root)

    def close(self):
        self._owner.assert_unborrowed()
        if isinstance(self._columns, _Segment):
            # L3: carried pins and memos go now, not when a surviving column
            # or access lets the _Segment be collected.
            self._columns.release()
        self._columns = self._meta = None
        self._owner.close()

    def _v(self, name, index):
        return self._columns.value(name, index)

    def _n(self, name):
        return self._meta['arrays'][name]['shape'][0]

    def _range(self, name, index):
        return self._v(name+'.offset', index), self._v(name+'.offset', index+1)

    def _bytes(self, name, start, stop):
        for at in range(start, stop, T.CHUNK):
            end = min(stop, at+T.CHUNK)
            if isinstance(self._columns, _Memory):
                yield self._columns.raw(name, at, end)
            else:
                with self._columns.raw(name, at, end) as held:
                    yield held.value

    def _token(self, index):
        a, b = self._range('token', index)
        return json.loads(b''.join(self._bytes('token.bytes', a, b)))

    def _int(self, index):
        if self._v('int.mode', index):
            value = 1 << self._v('int.exponent', index)
        else:
            a, b = self._range('int', index)
            value = int.from_bytes(b''.join(self._bytes('int.bytes', a, b)), 'little')
        return -value if self._v('int.sign', index) else value

    def _hex(self, index):
        yield b'"-0x' if self._v('int.sign', index) else b'"0x'
        if self._v('int.mode', index):
            exponent = self._v('int.exponent', index)
            yield b'1248'[exponent % 4:exponent % 4+1]
            zeros = exponent//4
            while zeros:
                amount = min(T.CHUNK, zeros)
                yield b'0'*amount
                zeros -= amount
        else:
            a, b = self._range('int', index)
            if a == b:
                yield b'0'
            first = True
            while b > a:
                lo = max(a, b-T.CHUNK//2)
                raw = b''.join(self._bytes('int.bytes', lo, b))
                token = raw[::-1].hex().encode('ascii')
                yield token.lstrip(b'0') if first else token
                first = False
                b = lo
        yield b'"'

    def _children(self, node):
        kind, payload = self._v('node.kind', node), self._v('node.payload', node)
        if kind == T.RATIONAL:
            return (self._v('q.numerator', payload), self._v('q.denominator', payload))
        a, b = self._range('node', node)
        return range(a, b)

    def _child(self, node, position):
        kind, payload = self._v('node.kind', node), self._v('node.payload', node)
        if kind == T.RATIONAL:
            return self._v('q.numerator' if position == 0 else 'q.denominator', payload)
        a, _ = self._range('node', node)
        return self._v('edge.child', a+position)

    def _size(self, node):
        kind = self._v('node.kind', node)
        if kind == T.RATIONAL:
            return 2
        if kind in (T.ARRAY, T.OBJECT):
            a, b = self._range('node', node)
            return b-a
        return self._v('node.length', node)

    def _access(self):
        return _Access(self._columns)

    def _renderer(self, access):
        """emit(node, depth, out, limit): append node's exact canonical bytes to out.

        The same bytes, in the same order, as _uncached_parts (with _parts for
        every child: the record check and the depth bound before each child),
        appended into one buffer instead of one generator per node. The
        caller performs the record check and depth bound of the top node.
        Raises _Overflow before out could grow beyond about ``limit`` bytes
        (declared widths are only an eligibility hint on unvalidated input);
        the caller then takes the unchanged streaming route.
        """
        column = access.column
        kinds, payloads, shapes = column('node.kind'), column('node.payload'), column('node.shape')
        node_offsets, edges = column('node.offset'), column('edge.child')
        shape_offsets, shape_keys, token_offsets = column('shape.offset'), column('shape.key'), column('token.offset')
        numerators, denominators, floats = column('q.numerator'), column('q.denominator'), column('float.value')
        int_offsets, int_signs, int_modes, int_exponents = (column('int.offset'), column('int.sign'),
                                                            column('int.mode'), column('int.exponent'))
        put, get, check, require = access.put, access.get, self._check, T.require
        TEXT, HEX, IDENT, NULL, BOOL, INTEGER = T.TEXT, T.HEX, T.IDENT, T.NULL, T.BOOL, T.INTEGER
        OBJECT, ARRAY, RATIONAL, MAX_DEPTH, HALF = T.OBJECT, T.ARRAY, T.RATIONAL, T.MAX_DEPTH, T.CHUNK//2
        canonical = T.canonical
        # Direct byte views where the backing is in memory; else put/get.
        tokens, magnitudes, identities = (view if type(view) is memoryview else None for view in
                                          (column('token.bytes'), column('int.bytes'), column('id.bytes')))

        def emit(node, depth, out, limit):
            # Iterative over an explicit stack of open containers [kind,
            # payload, size, edge start, key start, depth, position]: no
            # recursion and no self-referencing closure (nothing forms a cycle).
            stack = []
            while True:
                kind, payload = kinds[node], payloads[node]
                frame = None
                if kind == OBJECT or kind == ARRAY or kind == RATIONAL:
                    out += b'{' if kind == OBJECT else b'['
                    if kind == RATIONAL:
                        size, edge_start = 2, None
                    else:
                        edge_start = node_offsets[node]
                        size = node_offsets[node+1]-edge_start
                    if size:
                        frame = [kind, payload, size, edge_start,
                                 shape_offsets[shapes[node]] if kind == OBJECT else None, depth, 0]
                        stack.append(frame)
                    else:
                        out += b'}' if kind == OBJECT else b']'
                elif kind == TEXT:
                    a, b = token_offsets[payload], token_offsets[payload+1]
                    if len(out)+b-a > limit:
                        raise _Overflow
                    if tokens is not None:
                        out += tokens[a:b]
                    else:
                        put(out, 'token.bytes', a, b)
                elif kind == HEX:
                    out += b'"-0x' if int_signs[payload] else b'"0x'
                    if int_modes[payload]:
                        exponent = int_exponents[payload]
                        if len(out)+exponent//4+2 > limit:
                            raise _Overflow
                        out += b'1248'[exponent % 4:exponent % 4+1]
                        out += b'0'*(exponent//4)
                    else:
                        a, b = int_offsets[payload], int_offsets[payload+1]
                        if a == b:
                            out += b'0'
                        first = True
                        while b > a:
                            lo = max(a, b-HALF)
                            raw = bytes(magnitudes[lo:b]) if magnitudes is not None else get('int.bytes', lo, b)
                            token = raw[::-1].hex().encode('ascii')
                            if first:
                                token = token.lstrip(b'0')
                            # The closing quote always follows: exact, not an estimate.
                            if len(out)+len(token)+1 > limit:
                                raise _Overflow
                            out += token
                            first = False
                            b = lo
                    out += b'"'
                elif kind == IDENT:
                    raw = (identities[32*payload:32*(payload+1)] if identities is not None else
                           get('id.bytes', 32*payload, 32*(payload+1)))
                    out += b'"'+raw.hex().encode('ascii')+b'"'
                elif kind == NULL:
                    out += _NULL_JSON
                elif kind == BOOL:
                    out += _TRUE_JSON if payload else _FALSE_JSON
                else:
                    if kind == INTEGER:
                        # CompactRecord._int, from the same columns.
                        if int_modes[payload]:
                            value = 1 << int_exponents[payload]
                        else:
                            a, b = int_offsets[payload], int_offsets[payload+1]
                            value = int.from_bytes(bytes(magnitudes[a:b]) if magnitudes is not None
                                                   else get('int.bytes', a, b), 'little')
                        value = -value if int_signs[payload] else value
                    else:
                        value = floats[payload]
                    text = canonical(value)
                    if len(out)+len(text) > limit:
                        raise _Overflow
                    out += text
                if frame is None:
                    # This node is complete: continue its innermost open container.
                    while stack:
                        if len(out) > limit:
                            raise _Overflow
                        frame = stack[-1]
                        frame[6] += 1
                        if frame[6] < frame[2]:
                            out += b','
                            break
                        stack.pop()
                        out += b'}' if frame[0] == OBJECT else b']'
                    else:
                        return
                # Child frame[6] of the open container: its key, then the record
                # check and depth bound that _parts(child, depth+1) performs.
                kind, i = frame[0], frame[6]
                if kind == OBJECT:
                    key = shape_keys[frame[4]+i]
                    a, b = token_offsets[key], token_offsets[key+1]
                    if len(out)+b-a > limit:
                        raise _Overflow
                    if tokens is not None:
                        out += tokens[a:b]
                    else:
                        put(out, 'token.bytes', a, b)
                    out += b':'
                    node = edges[frame[3]+i]
                elif kind == RATIONAL:
                    node = numerators[frame[1]] if i == 0 else denominators[frame[1]]
                else:
                    node = edges[frame[3]+i]
                check()
                depth = frame[5]+1
                require(depth <= MAX_DEPTH, 'record depth exceeds bound')
        return emit

    def _rendered(self, node, depth, limit, memo):
        """Exact canonical bytes of node (top record check/depth done by the caller), or None."""
        if memo.render is None:
            memo.render = self._renderer(self._access())
        out = bytearray()
        try:
            memo.render(node, depth, out, limit)
        except _Overflow:
            return None
        return bytes(out) if len(out) <= limit else None

    def _parts(self, node, depth=0, memo=None):
        self._check()
        T.require(depth <= T.MAX_DEPTH, 'record depth exceeds bound')
        if memo is not None and memo.owner is not None:
            entries = memo.owner.value
            cached = entries.get(node)
            if cached is not None:
                entries.move_to_end(node)
                yield cached
                return
            limit = T.CHUNK
            if 0 < self._v('node.length', node) <= limit:
                # Declared width is only an eligibility hint. Check actual
                # emitted bytes before extending, even on unvalidated input.
                scratch = _OptionalScratch(self.scope.run_budget, 3*limit+4096)
                if scratch.admitted:
                    # R1: one buffer filled without a generator per node; the
                    # same bytes. Past the bound: the unchanged streaming route.
                    raw = self._rendered(node, depth, limit, memo)
                    if raw is None:
                        buffer = bytearray()
                        parts = self._uncached_parts(node, depth, memo)
                        for part in parts:
                            if len(buffer)+len(part) > limit:
                                if buffer:
                                    yield bytes(buffer)
                                yield part
                                yield from parts
                                return
                            buffer.extend(part)
                        raw = bytes(buffer)
                    # A run of unique IDs must not permanently crowd out later
                    # repeated ledger rows. Retire only this traversal's oldest
                    # bytes; active construction remains covered by scratch.
                    while entries and (len(entries) >= memo.MAX_ENTRIES or len(raw)+512 > memo.free):
                        _, previous = entries.popitem(last=False)
                        memo.free += len(previous)+512
                        del previous
                    entries[node] = raw
                    memo.free -= len(raw)+512
                    yield raw
                    return
        yield from self._uncached_parts(node, depth, memo)

    def _uncached_parts(self, node, depth, memo):
        kind, payload = self._v('node.kind', node), self._v('node.payload', node)
        if kind == T.TEXT:
            a, b = self._range('token', payload)
            yield from self._bytes('token.bytes', a, b)
        elif kind == T.HEX:
            yield from self._hex(payload)
        elif kind == T.IDENT:
            raw = b''.join(self._bytes('id.bytes', 32*payload, 32*(payload+1)))
            yield b'"'+raw.hex().encode('ascii')+b'"'
        elif kind in (T.ARRAY, T.OBJECT, T.RATIONAL):
            yield b'{' if kind == T.OBJECT else b'['
            if kind == T.RATIONAL:
                size, edge_start = 2, None
            else:
                edge_start, edge_stop = self._range('node', node)
                size = edge_stop-edge_start
            if kind == T.OBJECT:
                a, _ = self._range('shape', self._v('node.shape', node))
            for i in range(size):
                if i:
                    yield b','
                if kind == T.OBJECT:
                    key = self._v('shape.key', a+i)
                    lo, hi = self._range('token', key)
                    yield from self._bytes('token.bytes', lo, hi)
                    yield b':'
                child = (self._v('q.numerator' if i == 0 else 'q.denominator', payload)
                         if kind == T.RATIONAL else self._v('edge.child', edge_start+i))
                yield from self._parts(child, depth+1, memo)
            yield b'}' if kind == T.OBJECT else b']'
        else:
            value = (None if kind == T.NULL else bool(payload) if kind == T.BOOL else
                     self._int(payload) if kind == T.INTEGER else self._v('float.value', payload))
            yield T.canonical(value)

    def _stream(self, node, max_chunk_bytes, parent_owner=None):
        _bound(max_chunk_bytes, 'chunk bound', T.CHUNK)
        T.require(max_chunk_bytes > 0, 'positive chunk bound required')
        self._live()
        anchor = (self._owner if parent_owner is None else parent_owner).retain()
        def chunks():
            scratch = T.Scratch(self.scope.run_budget, 3*T.CHUNK+65536+T.MAX_DEPTH*1024)
            memo = _CanonicalMemo(self.scope)
            buffer = bytearray()
            for part in self._parts(node, memo=memo):
                for start in range(0, len(part), max_chunk_bytes):
                    token = part[start:start+max_chunk_bytes]
                    if len(buffer)+len(token) > max_chunk_bytes:
                        yield _owned(self.scope, len(buffer)+128, lambda: bytes(buffer))
                        buffer.clear()
                    buffer.extend(token)
            if buffer:
                yield _owned(self.scope, len(buffer)+128, lambda: bytes(buffer))
            del scratch, memo
        def generate():
            iterator = chunks()
            while True:
                self._live()
                with self._read_batch():
                    try:
                        block = next(iterator)
                    except StopIteration:
                        return
                yield block
        return OwnedStream(generate(), owners=(anchor,), scope=self.scope)

    def iter_json(self, *, max_chunk_bytes=T.CHUNK):
        return self._stream(self._root, max_chunk_bytes)

    def _export(self, node, *, max_logical_bytes, max_owned_bytes):
        with RecordRef(self, node) as ref:
            return _export_ref(ref, max_logical_bytes=max_logical_bytes,
                               max_owned_bytes=max_owned_bytes)

    def export(self, *, max_logical_bytes, max_owned_bytes):
        return self._export(self._root, max_logical_bytes=max_logical_bytes, max_owned_bytes=max_owned_bytes)

    def metadata_bytes(self):
        self._live()
        return _owned(self.scope, 65536, lambda: T.canonical(self._meta), 'record-metadata')

    def storage_payload(self):
        self._live()
        T.require(isinstance(self._columns, _Memory), 'persisted views use array_sources without eager arrays')
        return _owned(self.scope, 65536, lambda: (T.canonical(self._meta), self._columns.arrays),
                      'record-payload', dependencies=(self._owner,))

    def array_sources(self):
        self._live()
        for name in sorted(self._meta['arrays'], key=lambda n: n.encode('utf-8')):
            source = _ArraySource(self, name)
            try:
                yield source
            finally:
                source.close()

    def _validate(self):
        # Item 14: the optional high-byte memo must never turn an open that
        # fits without it into a refusal. If it was admitted and the scan runs
        # out of memory, the failed frame is collected (its leases with it) and
        # the scan runs again exactly as before, without the memo.
        admitted, retry = [], False
        try:
            with self._read_batch():
                self._validate_batch(keep_highs=admitted)
        except MemoryLimitError:
            if not admitted:
                raise
            retry = True
        if retry:
            gc.collect()
            with self._read_batch():
                self._validate_batch()

    def _validate_batch(self, keep_highs=None):
        """Bounded structural scan plus exact identity; no recursive expansion."""
        work_budget = WorkBudget(T.MAX_BUILD_BYTES, parent=self.scope.run_budget)
        n = self._n('node.kind')
        T.require(0 < n <= T.MAX_ITEMS and type(self._root) is int and 0 <= self._root < n,
                  'invalid root/node count')
        for name in ('node.payload', 'node.shape', 'node.length', 'node.charge'):
            T.require(self._n(name) == n, 'node column count differs')
        for name in ('int.sign', 'float.value', 'q.numerator', 'q.denominator'):
            T.require(self._n(name) <= T.MAX_ITEMS, 'pool count exceeds bound')
        for name in ('token.offset', 'shape.offset'):
            T.require(1 <= self._n(name) <= T.MAX_ITEMS+1, 'offset pool count exceeds bound')
        T.require(self._n('edge.child') <= 4*T.MAX_ITEMS and self._n('shape.key') <= 4*T.MAX_ITEMS and
                  self._n('id.bytes') <= 32*T.MAX_ITEMS, 'edge/key/ID inventory exceeds bound')
        # R1: every column value below is read through exact per-validation
        # column views (_Access): the same values and the same checks in the
        # same order; on a sealed segment from the pages pinned in this one
        # read batch, freshness checked before and after it.
        access = self._access()
        column, get = access.column, access.get
        for prefix, count, total in (('node', n, self._n('edge.child')),
                ('shape', self._n('shape.offset')-1, self._n('shape.key')),
                ('token', self._n('token.offset')-1, self._n('token.bytes')),
                ('int', self._n('int.sign'), self._n('int.bytes'))):
            offsets = column(prefix+'.offset')
            T.require(self._n(prefix+'.offset') == count+1 and offsets[0] == 0 and
                      offsets[count] == total, 'invalid CSR extent')
            previous = 0
            for i in range(count+1):
                current = offsets[i]
                T.require(previous <= current <= total, 'invalid CSR ordering')
                previous = current
        ints = self._n('int.sign')
        T.require(self._n('int.mode') == ints == self._n('int.exponent'), 'integer columns differ')
        T.require(self._n('q.numerator') == self._n('q.denominator') and self._n('id.bytes') % 32 == 0,
                  'invalid pair/ID columns')
        scratch = T.Scratch(work_budget, 65536+256*n)
        depths = np.zeros(n, dtype='u1')
        reachable = np.zeros(n, dtype='u1')
        widths = np.zeros(n, dtype='<u8')
        seen_nodes = {}
        int_offsets, int_modes, int_signs = column('int.offset'), column('int.mode'), column('int.sign')
        int_exponents, int_bytes, floats = column('int.exponent'), column('int.bytes'), column('float.value')
        token_offsets = column('token.offset')
        check, require = self._check, T.require
        # Item 14: the HEX width check below reads int.bytes[hi-1] of integer
        # 'payload' under exactly this loop's condition (binary mode, hi > lo),
        # the byte checked here; keeping it (one byte per integer, optional and
        # booked in this scan's budget) spares a second sweep of int.bytes pages.
        highs = highs_scratch = None
        if keep_highs is not None and ints:
            highs_scratch = _OptionalScratch(work_budget, 4096+ints, 'record-validate-highs')
            if highs_scratch.admitted:
                highs = bytearray(ints)
                keep_highs.append(True)
        for i in range(ints):
            check()
            a, b = int_offsets[i], int_offsets[i+1]
            mode, sign, exp = int_modes[i], int_signs[i], int_exponents[i]
            require(sign in (0, 1) and mode in (0, 1) and b-a <= T.MAX_INTEGER_BYTES,
                    'unknown integer sign/mode or magnitude bound')
            if mode:
                require(a == b and 64 <= exp < 8*T.MAX_INTEGER_BYTES, 'invalid dyadic encoding')
            else:
                require(exp == 0 and (b > a or sign == 0), 'invalid integer zero/exponent')
                if b > a:
                    high = int_bytes[b-1]
                    require(high != 0, 'nonminimal binary integer')
                    if highs is not None:
                        highs[i] = high
        for i in range(self._n('float.value')):
            require(math.isfinite(floats[i]), 'nonfinite float')
        for i in range(self._n('token.offset')-1):
            a, b = token_offsets[i], token_offsets[i+1]
            require(2 <= b-a <= T.MAX_TOKEN_BYTES, 'token length exceeds bound')
            token_scratch = T.Scratch(work_budget, 4096+16*(b-a))
            raw = get('token.bytes', a, b)
            value = json.loads(raw)
            require(type(value) is str and T.canonical(value) == raw, 'noncanonical string token')
            del raw, value, token_scratch
        limits = {T.NULL: 1, T.BOOL: 2, T.INTEGER: ints, T.FLOAT: self._n('float.value'),
                  T.TEXT: self._n('token.offset')-1, T.IDENT: self._n('id.bytes')//32,
                  T.HEX: ints, T.RATIONAL: self._n('q.numerator')}
        ref_max = max(n, ints, limits[T.TEXT], limits[T.FLOAT], limits[T.IDENT],
                      limits[T.RATIONAL], self._n('shape.offset')-1)
        for name, maximum in (('node.payload', ref_max), ('node.shape', self._n('shape.offset')-1),
                              ('edge.child', n), ('shape.key', limits[T.TEXT]),
                              ('q.numerator', n), ('q.denominator', n)):
            T.require(self._meta['arrays'][name]['dtype'] == np.dtype(T.narrow(maximum)).str,
                      'pool references are not the narrowest authenticated width')
        kinds, payloads, shapes = column('node.kind'), column('node.payload'), column('node.shape')
        node_offsets, lengths, charges = column('node.offset'), column('node.length'), column('node.charge')
        shape_offsets, shape_keys, edges = column('shape.offset'), column('shape.key'), column('edge.child')
        numerators, denominators = column('q.numerator'), column('q.denominator')
        shape_count = self._n('shape.offset')-1
        RATIONAL, OBJECT, ARRAY, TEXT, HEX = T.RATIONAL, T.OBJECT, T.ARRAY, T.TEXT, T.HEX
        for i in range(n):
            check()
            kind, payload, shape = kinds[i], payloads[i], shapes[i]
            a, b = node_offsets[i], node_offsets[i+1]
            require(0 <= kind <= RATIONAL, 'unknown node tag')
            if kind == ARRAY or kind == OBJECT or kind == RATIONAL:
                require(kind == RATIONAL or payload == 0, 'hidden container payload')
                if kind == RATIONAL:
                    require(payload < limits[kind] and a == b, 'invalid rational reference')
                size = 2 if kind == RATIONAL else b-a
                width = 2+max(0, size-1)
                if kind == OBJECT:
                    require(shape < shape_count, 'shape reference outside pool')
                    sa, sb = shape_offsets[shape], shape_offsets[shape+1]
                    require(sb-sa == size, 'shape/row cardinality differs')
                    previous = None
                    previous_scratch = None
                    for j in range(sa, sb):
                        key = shape_keys[j]
                        require(key < limits[TEXT], 'shape key outside pool')
                        lo, hi = token_offsets[key], token_offsets[key+1]
                        key_scratch = T.Scratch(work_budget, 4096+32*(hi-lo))
                        value = json.loads(get('token.bytes', lo, hi))
                        require(previous is None or previous < value, 'key shape not sorted and unique')
                        # The preceding decoded key survives across iterations;
                        # its lease must survive with it, including on failure.
                        previous = None
                        del previous_scratch
                        previous = value
                        previous_scratch = key_scratch
                        width += hi-lo+1
                        del value, key_scratch
                    previous = None
                    del previous_scratch
                else:
                    require(shape == 0, 'hidden shape on array')
                depth = 1
                for j in range(size):
                    child = ((numerators[payload] if j == 0 else denominators[payload])
                             if kind == RATIONAL else edges[a+j])
                    require(child < i, 'forward/cyclic child reference')
                    if kind == RATIONAL:
                        require(kinds[child] == HEX, 'rational spelling class differs')
                    depth = max(depth, 1+int(depths[child]))
                    width += int(widths[child])
                require(depth <= T.MAX_DEPTH, 'DAG depth exceeds bound')
                depths[i] = depth
            else:
                require(a == b and shape == 0 and payload < limits[kind], 'invalid scalar reference')
                minimum = 4096
                if kind == TEXT or kind == HEX:
                    minimum = max(minimum, 4096+16*lengths[i])
                if kind == T.INTEGER:
                    lo, hi = int_offsets[payload], int_offsets[payload+1]
                    binary = (int_exponents[payload]//8+1 if int_modes[payload] else hi-lo)
                    minimum = max(minimum, 4096+16*binary)
                require(charges[i] >= minimum, 'understated scalar allocation bound')
                if kind == TEXT:
                    width = token_offsets[payload+1]-token_offsets[payload]
                elif kind == T.IDENT:
                    width = 66
                elif kind == HEX:
                    if int_modes[payload]:
                        digits = int_exponents[payload]//4+1
                    else:
                        lo, hi = int_offsets[payload], int_offsets[payload+1]
                        high = (highs[payload] if highs is not None else int_bytes[hi-1]) if hi > lo else 0
                        digits = max(1, 2*(hi-lo)-(high < 16))
                    width = 4+digits+int_signs[payload]
                else:
                    scalar_scratch = T.Scratch(work_budget, charges[i])
                    # _parts(i): the record check, then T.canonical of the scalar.
                    check()
                    if kind == T.NULL:
                        value = None
                    elif kind == T.BOOL:
                        value = bool(payload)
                    elif kind == T.INTEGER:
                        if int_modes[payload]:
                            value = 1 << int_exponents[payload]
                        else:
                            value = int.from_bytes(get('int.bytes', int_offsets[payload], int_offsets[payload+1]),
                                                   'little')
                        value = -value if int_signs[payload] else value
                    else:
                        value = floats[payload]
                    width = len(T.canonical(value))
                    del scalar_scratch, value
            require(width <= (1 << 64)-1 and width == lengths[i], 'node canonical length differs')
            widths[i] = width
            key_hash = sha256(bytes((kind,))+payload.to_bytes(8, 'little')+shape.to_bytes(8, 'little'))
            for edge in range(a, b):
                key_hash.update(edges[edge].to_bytes(8, 'little'))
            key = key_hash.digest()
            if key in seen_nodes:
                other = seen_nodes[key]
                oa, ob = node_offsets[other], node_offsets[other+1]
                equal = (kind == kinds[other] and payload == payloads[other]
                         and shape == shapes[other] and b-a == ob-oa and
                         all(edges[a+j] == edges[oa+j] for j in range(b-a)))
                require(not equal, 'duplicate hash-consed node')
            seen_nodes[key] = i
        reachable[self._root] = 1
        for i in range(n-1, -1, -1):
            if not reachable[i]:
                continue
            kind = kinds[i]
            if kind == RATIONAL:
                payload = payloads[i]
                reachable[numerators[payload]] = 1
                reachable[denominators[payload]] = 1
            elif kind == ARRAY or kind == OBJECT:
                for j in range(node_offsets[i], node_offsets[i+1]):
                    reachable[edges[j]] = 1
        require(bool(np.all(reachable)), 'unreachable hidden scientific node')
        digest, length = sha256(), 0
        stream_scratch = T.Scratch(work_budget, 65536*4+T.MAX_DEPTH*1024)
        memo = _CanonicalMemo(self.scope)
        for part in self._parts(self._root, memo=memo):
            digest.update(part); length += len(part)
        T.require(length == self._identity.canonical_bytes == self._v('node.length', self._root) and
                  digest.hexdigest() == self._identity.sha256, 'logical canonical identity differs')
        del stream_scratch, scratch, memo, highs, highs_scratch


class RecordRef:
    """Explicit reference. Intentionally has no mapping/sequence protocol."""
    def __init__(self, view, index, *, fields=None, selection_owner=None, parent_owner=None):
        T.require(isinstance(view, CompactRecord) and type(index) is int and
                  0 <= index < view._n('node.kind'), 'reference outside validated record')
        self._view, self.index, self._fields = view, index, fields
        self._owner = (view._owner if parent_owner is None else parent_owner).retain()
        self._selection_owner = None if selection_owner is None else selection_owner.retain()

    @property
    def scope(self):
        return self._owner.scope

    def _live(self):
        self._owner.value
        self._view._check()

    def borrow(self):
        """An independently paid child wrapper; the parent remains borrowed."""
        from copy import copy
        self._live()
        result = copy(self)
        result._owner = self._owner.retain()
        if self._selection_owner is not None:
            result._selection_owner = self._selection_owner.retain()
        return result

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.close()
            return False
        # Failure path: a failed frame below (an owned key inventory, a child
        # export) can still hold child borrows of this owner while its
        # traceback is alive, so closing here would refuse and replace the
        # original error (a guard stop, cancellation or timeout) with "owner has
        # live child borrows". Retire instead: each owner closes now if it is
        # unborrowed, else when its last borrower drops (content_cache.Owned).
        self._owner._retire()
        self._fields = None
        if self._selection_owner is not None:
            self._selection_owner._retire()
            self._selection_owner = None
        self._view = None
        return False

    def _logical_length(self):
        self._live()
        T.require(self._fields is None, 'row projection requires explicit object selection')
        return self._view._v('node.length', self.index)

    def keys(self, *, max_owned_bytes=4 << 20):
        """Explicit paid object-key inventory, never a Mapping protocol."""
        self._live()
        T.require(self.kind == 'object', 'object keys required')
        _bound(max_owned_bytes, 'key inventory bound')
        with self._view._read_batch():
            view = self._view
            start, stop = view._range('shape', view._v('node.shape', self.index))
            charge = 4096+128*(stop-start)
            for at in range(start, stop):
                token = view._v('shape.key', at)
                a, b = view._range('token', token)
                charge += 32*(b-a)
            T.require(charge+OWNER_BYTES <= max_owned_bytes, 'object keys exceed owned byte bound')
            def decode():
                return tuple(view._token(view._v('shape.key', at)) for at in range(start, stop)
                             if self._fields is None or view._token(view._v('shape.key', at)) in self._fields)
            return _owned(self.scope, charge, decode, 'record-keys', dependencies=(self._owner,))

    def get(self, name, default=None, *, max_owned_bytes=4 << 20):
        """Owned scalar or explicit child reference; containers never expand."""
        try:
            child = self.field(name)
        except KeyError:
            T.require(default is None or type(default) in (bool, int, float, str),
                      'missing-field default must be a scalar')
            record = T.RecordCodec().pack_record(default, record_schema='atlas.json-value.v1',
                                                scope=self.scope, check=self._live)
            with record.root() as root:
                result = root.scalar(max_owned_bytes=max_owned_bytes)
            record.close()
            return result
        if child.kind != 'scalar':
            return child
        try:
            return child.scalar(max_owned_bytes=max_owned_bytes)
        finally:
            child.close()

    def select(self, names):
        return _ObjectRecordRef(self, fields=names)

    def without(self, names):
        return _ObjectRecordRef(self, without=names)

    @property
    def kind(self):
        self._live()
        kind = self._view._v('node.kind', self.index)
        return 'object' if kind == T.OBJECT else 'array' if kind in (T.ARRAY, T.RATIONAL) else 'scalar'

    @property
    def size(self):
        self._live()
        return len(self._fields) if self._fields is not None else self._view._size(self.index)

    def field(self, name):
        self._live()
        with self._view._read_batch():
            return self._field_batch(name)

    def _field_batch(self, name):
        T.require(self.kind == 'object' and type(name) is str, 'object and string field required')
        if self._fields is not None and name not in self._fields:
            raise KeyError(name)
        v = self._view
        start, stop = v._range('shape', v._v('node.shape', self.index))
        low, high = start, stop
        while low < high:
            middle = (low+high)//2
            token = v._v('shape.key', middle)
            a, b = v._range('token', token)
            scratch = T.Scratch(self.scope.run_budget, 4096+32*(b-a))
            key = v._token(token)
            if key < name:
                low = middle+1
            else:
                high = middle
            del key, scratch
        if low == stop:
            raise KeyError(name)
        token = v._v('shape.key', low)
        a, b = v._range('token', token)
        scratch = T.Scratch(self.scope.run_budget, 4096+32*(b-a))
        if v._token(token) != name:
            raise KeyError(name)
        del scratch
        return RecordRef(v, v._child(self.index, low-start), parent_owner=self._owner)

    def at(self, index):
        T.require(self.kind == 'array' and type(index) is int and 0 <= index < self.size, 'array index outside record')
        return RecordRef(self._view, self._view._child(self.index, index), parent_owner=self._owner)

    def scalar(self, *, max_owned_bytes):
        self._live()
        with self._view._read_batch():
            return self._scalar_batch(max_owned_bytes=max_owned_bytes)

    def _scalar_batch(self, *, max_owned_bytes):
        T.require(self.kind == 'scalar', 'container expansion requires explicit export')
        _bound(max_owned_bytes, 'scalar allocation bound')
        charge = self._view._v('node.charge', self.index)
        T.require(charge+OWNER_BYTES <= max_owned_bytes, 'scalar allocation bound exceeded before decode')
        return _owned(self.scope, charge, lambda: json.loads(b''.join(self._view._parts(self.index))), 'record-scalar')

    def iter_rows(self, *, max_rows, max_owned_bytes, fields=None):
        T.require(self.kind == 'array', 'row iteration requires array')
        _bound(max_rows, 'row count', T.MAX_ITEMS)
        _bound(max_owned_bytes, 'row byte bound')
        T.require(max_rows > 0 and max_owned_bytes >= OWNER_BYTES+8192, 'positive bounded row block required')
        selection = None
        if fields is not None:
            T.require(type(fields) in (tuple, list) and len(fields) <= T.MAX_ITEMS and
                      all(type(f) is str for f in fields), 'bounded string fields required')
            field_charge = 4096+128*len(fields)+sum(16*len(f) for f in fields)
            T.require(field_charge+OWNER_BYTES <= max_owned_bytes, 'field selection exceeds owned byte bound')
            def selected_fields():
                T.require(len(set(fields)) == len(fields), 'distinct string fields required')
                return tuple(fields)
            selection = _owned(self.scope, field_charge, selected_fields, 'record-selected-fields')
            fields = selection.value
        view, node = self._view, self.index
        anchor = self._owner.retain()
        def generate():
            at, size = 0, view._size(node)
            count = min(max_rows, (max_owned_bytes-OWNER_BYTES)//(12288 if selection else 8192))
            T.require(count > 0, 'row block cannot fit one shallow reference')
            while at < size:
                amount = min(count, size-at)
                def make():
                    rows = tuple(RecordRef(view, view._child(node, i), fields=fields,
                                          selection_owner=selection, parent_owner=anchor)
                                 for i in range(at, at+amount))
                    if fields is not None:
                        for row in rows:
                            T.require(row.kind == 'object', 'field selection requires object rows')
                            for field in fields:
                                child = row.field(field)
                                child.close()
                    return rows
                yield _owned(self.scope, 1024+amount*_ROW_REF_BYTES, make, 'record-rows')
                at += amount
        return OwnedStream(generate(), owners=(anchor,) if selection is None else (anchor, selection), scope=self.scope)

    def identity(self):
        self._live()
        if self._fields is not None:
            raise ContractError('projection has no implicit full-record identity')
        digest, length = sha256(), 0
        with self.iter_json() as stream:
            for held in stream:
                with held:
                    digest.update(held.value); length += len(held.value)
        return LogicalIdentity(self._view._identity.record_schema, digest.hexdigest(), length)

    def iter_json(self, *, max_chunk_bytes=T.CHUNK):
        self._live()
        T.require(self._fields is None, 'projection streaming requires an explicit selected-object adapter')
        return self._view._stream(self.index, max_chunk_bytes, parent_owner=self._owner)

    def export(self, *, max_logical_bytes, max_owned_bytes):
        self._live()
        T.require(self._fields is None, 'projection export requires explicit field selection')
        return _export_ref(self, max_logical_bytes=max_logical_bytes, max_owned_bytes=max_owned_bytes)

    def close(self):
        self._owner.close()
        self._fields = None
        if self._selection_owner is not None:
            self._selection_owner.close()
            self._selection_owner = None
        self._view = None


class LogicalRecord(RecordRef):
    pass


class LogicalExchange(LogicalRecord):
    @classmethod
    def from_body(cls, record, *, state_id, result_id):
        """Public exchange fields over one compact body; no second body pack."""
        from compact_contracts import _sha
        _sha(state_id, 'state ID'); _sha(result_id, 'result ID')
        body = record.root() if isinstance(record, CompactRecord) else record.borrow()
        headers = T.RecordCodec().pack_record(dict(state_id=state_id, result_id=result_id),
            record_schema='atlas.exchange-header.v1', scope=body.scope, check=body._view._check)
        overlay = headers.root()
        result = _ObjectRecordRef(body, overlay=overlay)
        # The result retains the tiny header backing as well as the original body.
        return result

    @classmethod
    def from_records(cls, body, **children):
        """Compose borrowed child records without encoding them again."""
        return _ObjectRecordRef(body, overrides=children)

    def body(self):
        return self.without(('state_id', 'result_id'))

    def composite_identity(self, state_id, *, record_schema='atlas.exchange-result.v1'):
        """Original identity is hash({state_id, exchange: body}), in that order
        after legacy sorted-key canonicalisation (exchange precedes state_id).
        Role separation is explicit; no Mapping conversion or synthetic merge.
        """
        T.require(type(state_id) is str and len(state_id) == 64 and
                  all(c in '0123456789abcdef' for c in state_id), 'state_id must be an exact content ID')
        digest, length = sha256(), 0
        prefix, suffix = b'{"exchange":', b',"state_id":'+T.canonical(state_id)+b'}'
        digest.update(prefix); length += len(prefix)
        with self.iter_json() as stream:
            for block in stream:
                with block:
                    digest.update(block.value); length += len(block.value)
        digest.update(suffix); length += len(suffix)
        return LogicalIdentity(record_schema, digest.hexdigest(), length)


class _ObjectRecordRef(LogicalExchange):
    """Paid, canonical object selection/overlay over immutable child references."""
    def __init__(self, base, *, fields=None, without=(), overlay=None, overrides=None):
        T.require(isinstance(base, RecordRef) and base.kind == 'object', 'object base required')
        T.require(overlay is None or isinstance(overlay, RecordRef) and
                  overlay.kind == 'object' and overlay.scope is base.scope, 'same-scope object overlay required')
        for names in (without, () if fields is None else fields):
            T.require(type(names) in (tuple, list) and len(names) <= T.MAX_ITEMS and
                      all(type(name) is str for name in names), 'explicit bounded string field names required')
        T.require(overrides is None or type(overrides) is dict and
                  all(type(k) is str and isinstance(v, RecordRef) and v.scope is base.scope
                      for k, v in overrides.items()), 'same-scope child overrides required')
        T.require(overlay is None or overrides is None, 'one overlay source required')
        with base.keys(max_owned_bytes=T.MAX_ROW_WORK_BYTES) as base_keys:
            extra = None if overlay is None else overlay.keys(max_owned_bytes=T.MAX_ROW_WORK_BYTES)
            try:
                overlay_keys = tuple(overrides) if overrides is not None else (() if extra is None else extra.value)
                charge = (8192+256*(len(base_keys.value)+len(overlay_keys))+
                          32*sum(map(len, base_keys.value))+32*sum(map(len, overlay_keys)))
                T.require(charge+OWNER_BYTES <= T.MAX_ROW_WORK_BYTES, 'object selection exceeds row bound')
                def make():
                    keys = set(base_keys.value) | set(overlay_keys)
                    if fields is not None:
                        T.require(len(set(fields)) == len(fields), 'duplicate selected fields')
                        for name in fields:
                            if name not in keys:
                                raise KeyError(name)
                        keys.intersection_update(fields)
                    keys.difference_update(without)
                    keys = tuple(sorted(keys))
                    length = 2+max(0, len(keys)-1)
                    for name in keys:
                        child = (overrides[name].borrow() if overrides is not None and name in overrides
                                 else (overlay if name in overlay_keys else base).field(name))
                        with child:
                            length += len(T.canonical(name))+1+child._logical_length()
                    return (base.borrow(), None if overlay is None else overlay.borrow(),
                            keys, frozenset(overlay_keys), length,
                            {} if overrides is None else {k: v.borrow() for k, v in overrides.items()})
                self._owner = _owned(base.scope, charge, make, 'record-object-view',
                    dependencies=(base._owner,) if overlay is None else (base._owner, overlay._owner))
            finally:
                if extra is not None:
                    extra.close()
        self._view, self.index = base._view, base.index
        self._fields = self._selection_owner = None

    def _live(self):
        base, overlay, _, _, _, overrides = self._owner.value
        base._live()
        if overlay is not None:
            overlay._live()
        for child in overrides.values():
            child._live()

    @property
    def kind(self):
        self._live()
        return 'object'

    @property
    def size(self):
        self._live()
        return len(self._owner.value[2])

    def _logical_length(self):
        self._live()
        return self._owner.value[4]

    def keys(self, *, max_owned_bytes=4 << 20):
        self._live()
        _bound(max_owned_bytes, 'key inventory bound')
        names = self._owner.value[2]
        charge = 4096+128*len(names)+32*sum(map(len, names))
        T.require(charge+OWNER_BYTES <= max_owned_bytes, 'object keys exceed owned byte bound')
        return _owned(self.scope, charge, lambda: names, 'record-keys', dependencies=(self._owner,))

    def field(self, name):
        self._live()
        T.require(type(name) is str, 'string field required')
        base, overlay, names, overridden, _, overrides = self._owner.value
        if name not in names:
            raise KeyError(name)
        if name in overrides:
            return overrides[name].borrow()
        return (overlay if name in overridden else base).field(name)

    def iter_json(self, *, max_chunk_bytes=T.CHUNK):
        self._live()
        T.require(type(max_chunk_bytes) is int and 0 < max_chunk_bytes <= T.CHUNK,
                  'positive bounded object stream chunk required')
        anchor = self.borrow()
        def parts():
            yield b'{'
            for at, name in enumerate(anchor._owner.value[2]):
                if at:
                    yield b','
                yield from T.string_parts(name, max_chunk_bytes)
                yield b':'
                with anchor.field(name) as child, child.iter_json(max_chunk_bytes=max_chunk_bytes) as stream:
                    for block in stream:
                        with block:
                            yield block.value
            yield b'}'
        def generate():
            scratch = T.Scratch(anchor.scope.run_budget, 65536+4*max_chunk_bytes)
            buffer = bytearray()
            for part in parts():
                anchor._live()
                for at in range(0, len(part), max_chunk_bytes):
                    buffer.extend(part[at:at+max_chunk_bytes])
                    if len(buffer) >= max_chunk_bytes:
                        raw = _owned(anchor.scope, 4096+max_chunk_bytes,
                                     lambda chunk_buffer=buffer: bytes(chunk_buffer[:max_chunk_bytes]), 'record-object-chunk')
                        del buffer[:max_chunk_bytes]
                        yield raw
            if buffer:
                yield _owned(anchor.scope, 4096+len(buffer), lambda chunk_buffer=buffer: bytes(chunk_buffer), 'record-object-chunk')
            del buffer, scratch
        return OwnedStream(generate(), owners=(anchor._owner,), scope=self.scope)

    def export(self, *, max_logical_bytes, max_owned_bytes):
        return _export_ref(self, max_logical_bytes=max_logical_bytes, max_owned_bytes=max_owned_bytes)


def _decoded_stats(ref, cap, memo):
    """Bound expanded Python objects using validated structure, not JSON width.

    Repeated DAG children count on every edge: deduplicated storage never
    discounts the separate objects a native consumer requests. The bounded
    memo only avoids re-counting the same immutable subtree.
    """
    ref._live()
    ordinary = type(ref) in (RecordRef, LogicalRecord, LogicalExchange)
    if ordinary and ref._fields is None:
        # R1: an ordinary reference's subtree is the column walk _node_stats
        # (equal (cost, maximum) and cap refusal), with the key inventory
        # bound this walk applies through RecordRef.keys() at every object.
        nodes = memo.get(('nodes', id(ref._view)))
        if nodes is None:
            nodes = memo[('nodes', id(ref._view))] = {}
        with ref._view._read_batch():
            return _node_stats(ref._view, ref.index, cap, nodes, keys_bound=T.MAX_ROW_WORK_BYTES)
    key = ((id(ref._view), ref.index) if ordinary else
           (ref._owner.allocation_id, ref.index, ref.kind, ref._logical_length()))
    if key in memo:
        return memo[key]
    kind, maximum = ref.kind, 0
    if kind == 'scalar':
        length = ref._logical_length()
        tag = ref._view._v('node.kind', ref.index) if ordinary else None
        if not ordinary:
            # Domain adapters can expose authenticated scalars outside the
            # backing DAG. Bound their actual canonical width conservatively.
            cost = 128+4*length
        elif tag in (T.TEXT, T.HEX, T.IDENT):
            # Unicode may widen an otherwise ASCII string. Exact hex and IDs
            # are authenticated ASCII and cannot have that widening.
            cost = 128+4*length if tag == T.TEXT else 64+length
        elif tag == T.INTEGER:
            cost = 128+4*length
        else:
            cost = 128
        maximum = length
    else:
        count = ref.size
        # Includes container growth and a native row's one shallow dict copy.
        cost = 512+128*count if kind == 'object' else 64+8*count
        if kind == 'object':
            with ref.keys(max_owned_bytes=T.MAX_ROW_WORK_BYTES) as names:
                for name in names.value:
                    key_bytes = sum(len(part) for part in T.string_parts(name))
                    cost += 128+4*key_bytes
                    maximum = max(maximum, key_bytes)
                    with ref.field(name) as child:
                        amount, scalar = _decoded_stats(child, cap, memo)
                    cost += amount
                    maximum = max(maximum, scalar)
                    T.require(cost <= cap, 'owned export bound exceeded before allocation')
        else:
            for at in range(count):
                with ref.at(at) as child:
                    amount, scalar = _decoded_stats(child, cap, memo)
                cost += amount
                maximum = max(maximum, scalar)
                T.require(cost <= cap, 'owned export bound exceeded before allocation')
    T.require(cost <= cap, 'owned export bound exceeded before allocation')
    result = cost, maximum
    if len(memo) < 256:
        memo[key] = result
    return result


def _node_stats(view, node, cap, memo, *, keys_bound=None, access=None):
    """_decoded_stats of an ordinary RecordRef(view, node), read from the columns.

    Same (cost, maximum) and the same cap refusal. A validated record holds
    sorted, unique, canonical key tokens, so the key inventory, the field
    lookups and the re-encoded key widths of _decoded_stats equal the shape
    order, the edge order and the token widths read here, without its per-key
    decodes, child references and lookup leases.

    R1: the same walk over exact column views with an explicit stack (same
    visiting order, memo insertions, sums and cap checks; no generator,
    wrapper or recursion per node). ``keys_bound`` (large route) adds, at
    every object, the key inventory bound RecordRef.keys() applies there.
    """
    column = (view._access() if access is None else access).column
    kinds, payloads, lengths = column('node.kind'), column('node.payload'), column('node.length')
    node_offsets, edges, shapes = column('node.offset'), column('edge.child'), column('node.shape')
    shape_offsets, shape_keys, token_offsets = column('shape.offset'), column('shape.key'), column('token.offset')
    numerators, denominators = column('q.numerator'), column('q.denominator')
    check, require = view._check, T.require
    OBJECT, ARRAY, RATIONAL, TEXT, INTEGER, HEX, IDENT = T.OBJECT, T.ARRAY, T.RATIONAL, T.TEXT, T.INTEGER, T.HEX, T.IDENT
    refused = 'owned export bound exceeded before allocation'
    # frame: [node, kind, cost, maximum, position, count, edge start or children, key start]
    stack = []
    while True:
        if node in memo:
            result = memo[node]
        else:
            check()
            kind = kinds[node]
            frame = None
            if kind == OBJECT:
                a, b = node_offsets[node], node_offsets[node+1]
                keys = shape_offsets[shapes[node]]
                frame = [node, kind, 512+128*(b-a), 0, 0, b-a, a, keys]
                if keys_bound is not None:
                    shape = shapes[node]
                    start, stop = shape_offsets[shape], shape_offsets[shape+1]
                    charge = 4096+128*(stop-start)
                    for at in range(start, stop):
                        token = shape_keys[at]
                        charge += 32*(token_offsets[token+1]-token_offsets[token])
                    require(charge+OWNER_BYTES <= keys_bound, 'object keys exceed owned byte bound')
            elif kind == ARRAY or kind == RATIONAL:
                if kind == RATIONAL:
                    payload = payloads[node]
                    children = (numerators[payload], denominators[payload])
                    frame = [node, kind, 64+16, 0, 0, 2, children, None]
                else:
                    a, b = node_offsets[node], node_offsets[node+1]
                    frame = [node, kind, 64+8*(b-a), 0, 0, b-a, a, None]
            else:
                maximum = lengths[node]
                cost = (128+4*maximum if kind == TEXT or kind == INTEGER else
                        64+maximum if kind == HEX or kind == IDENT else 128)
                require(cost <= cap, refused)
                result = cost, maximum
                if len(memo) < 256:
                    memo[node] = result
            if frame is not None:
                if frame[5]:
                    stack.append(frame)
                    node = _stats_child(frame, shape_keys, token_offsets, edges)
                    continue
                require(frame[2] <= cap, refused)
                result = frame[2], frame[3]
                if len(memo) < 256:
                    memo[frame[0]] = result
        # result belongs to the last completed node: fold it into its container.
        while stack:
            frame = stack[-1]
            amount, scalar = result
            frame[2] += amount
            frame[3] = max(frame[3], scalar)
            require(frame[2] <= cap, refused)
            frame[4] += 1
            if frame[4] < frame[5]:
                node = _stats_child(frame, shape_keys, token_offsets, edges)
                break
            stack.pop()
            require(frame[2] <= cap, refused)
            result = frame[2], frame[3]
            if len(memo) < 256:
                memo[frame[0]] = result
        else:
            return result


def _stats_child(frame, shape_keys, token_offsets, edges):
    """Next child of a _node_stats container frame (object keys add their width first)."""
    position = frame[4]
    if frame[1] == T.OBJECT:
        key = shape_keys[frame[7]+position]
        width = token_offsets[key+1]-token_offsets[key]
        frame[2] += 128+4*width
        frame[3] = max(frame[3], width)
        return edges[frame[6]+position]
    if frame[1] == T.RATIONAL:
        return frame[6][position]
    return edges[frame[6]+position]


class _Decode:
    """_decode_ref of an ordinary RecordRef(view, node), read from the columns (R1).

    The same values (types, key order: shape order is the sorted canonical key
    order RecordRef.keys()/field() follow) and the same key inventory bound.
    A subtree of at most _DECODE_SUBTREE canonical bytes is one C JSON decode
    of its exact canonical bytes, which is the value the per-node route builds
    from the same bytes; larger scalars keep the per-scalar join and decode.
    """
    __slots__ = ('access', 'denominators', 'edges', 'emit', 'kinds', 'lengths', 'node_offsets', 'numerators',
                 'payloads', 'shape_keys', 'shape_offsets', 'shapes', 'token_offsets', 'view')

    def __init__(self, view):
        self.view, self.access = view, view._access()
        self.emit = view._renderer(self.access)
        column = self.access.column
        for name in ('kinds', 'payloads', 'lengths', 'node_offsets', 'edges', 'shapes', 'shape_offsets',
                     'shape_keys', 'token_offsets', 'numerators', 'denominators'):
            setattr(self, name, column(_DECODE_COLUMNS[name]))

    def node(self, node):
        self.view._check()
        length = self.lengths[node]
        if length <= _DECODE_SUBTREE:
            out = bytearray()
            try:
                self.emit(node, 0, out, length)
            except _Overflow:
                out = None
            if out is not None:
                return json.loads(out)
        kind = self.kinds[node]
        if kind == T.OBJECT:
            shape = self.shapes[node]
            start, stop = self.shape_offsets[shape], self.shape_offsets[shape+1]
            token_offsets, shape_keys = self.token_offsets, self.shape_keys
            charge = 4096+128*(stop-start)
            for at in range(start, stop):
                token = shape_keys[at]
                charge += 32*(token_offsets[token+1]-token_offsets[token])
            T.require(charge+OWNER_BYTES <= T.MAX_ROW_WORK_BYTES, 'object keys exceed owned byte bound')
            edge = self.node_offsets[node]
            result = {}
            for i in range(self.node_offsets[node+1]-edge):
                token = shape_keys[start+i]
                name = json.loads(self.access.get('token.bytes', token_offsets[token], token_offsets[token+1]))
                result[name] = self.node(self.edges[edge+i])
            return result
        if kind == T.ARRAY or kind == T.RATIONAL:
            if kind == T.RATIONAL:
                payload = self.payloads[node]
                children = (self.numerators[payload], self.denominators[payload])
            else:
                edge = self.node_offsets[node]
                children = range(edge, self.node_offsets[node+1])
            # Allocate the exact pointer vector once, avoiding append overgrowth.
            result = [None]*len(children)
            for at, child in enumerate(children):
                result[at] = self.node(child if kind == T.RATIONAL else self.edges[child])
            return result
        return json.loads(b''.join(self.view._parts(node)))


_DECODE_COLUMNS = {'kinds': 'node.kind', 'payloads': 'node.payload', 'lengths': 'node.length',
                   'node_offsets': 'node.offset', 'edges': 'edge.child', 'shapes': 'node.shape',
                   'shape_offsets': 'shape.offset', 'shape_keys': 'shape.key', 'token_offsets': 'token.offset',
                   'numerators': 'q.numerator', 'denominators': 'q.denominator'}


def _decode_ref(ref):
    """Direct bounded construction: only bounded subtrees and scalars pass through JSON."""
    if type(ref) in (RecordRef, LogicalRecord, LogicalExchange) and ref._fields is None:
        ref._live()
        with ref._view._read_batch():
            return _Decode(ref._view).node(ref.index)
    with ref._view._read_batch():
        if ref.kind == 'scalar':
            if type(ref) not in (RecordRef, LogicalRecord, LogicalExchange):
                with ref.scalar(max_owned_bytes=T.MAX_ROW_WORK_BYTES) as scalar:
                    return scalar.value
            return json.loads(b''.join(ref._view._parts(ref.index)))
        if ref.kind == 'object':
            result = {}
            with ref.keys(max_owned_bytes=T.MAX_ROW_WORK_BYTES) as names:
                for name in names.value:
                    with ref.field(name) as child:
                        result[name] = _decode_ref(child)
            return result
        # Allocate the exact pointer vector once, avoiding append overgrowth.
        result = [None]*ref.size
        for at in range(ref.size):
            with ref.at(at) as child:
                result[at] = _decode_ref(child)
        return result


def _export_ref(ref, *, max_logical_bytes, max_owned_bytes):
    _bound(max_logical_bytes, 'logical export bound')
    _bound(max_owned_bytes, 'owned export bound')
    ref._live()
    length = ref._logical_length()
    T.require(length <= max_logical_bytes, 'logical export bound exceeded')
    # Rows up to 32 KiB keep the C JSON decoder; no whole graph can enter
    # through this bounded fast path. Every row, small or large, is admitted
    # at the same structural bound before decode (the small-row 65536+192 x
    # width charge was ~50x the real decoded rows).
    small = type(ref) in (RecordRef, LogicalRecord, LogicalExchange) and length <= 32768
    # Fixed preflight funding covers the bounded memo, traversal stack and
    # key-encoding chunks; all child/key carriers have their own reservations.
    scratch = T.Scratch(ref.scope.run_budget, 65536+256*256+T.MAX_DEPTH*1024)
    # One set of exact column views serves the small row's stats and decode.
    access = ref._view._access() if small else None
    with ref._view._read_batch():
        decoded, scalar = (_node_stats(ref._view, ref.index, max_owned_bytes, {}, access=access) if small else
                           _decoded_stats(ref, max_owned_bytes, {}))
    # Decoding the largest scalar holds its streamed parts, their join and the
    # JSON decoder's str copy beside the result counted in ``decoded``; hex
    # bodies add one bounded block of reversal/hex workspace.
    charge = 65536+decoded+_SCALAR_DECODE_FACTOR*scalar+min(4*scalar, _SCALAR_DECODE_BLOCK)
    T.require(charge+OWNER_BYTES <= max_owned_bytes, 'owned export bound exceeded before allocation')
    if small:
        def small_decode():
            # One canonical buffer of at most the row's width, filled by the
            # column renderer (R1: the same bytes as _parts, without a
            # generator per node), then the str copy inside json.loads. The
            # held scratch funds them (2 x 32 KiB at most, plus append growth)
            # and the traversal stack beside the result booked in ``charge``.
            view = ref._view
            with view._read_batch():
                view._check()
                out = bytearray()
                try:
                    view._renderer(access)(ref.index, 0, out, length)
                except _Overflow:
                    out = None
                if out is not None:
                    return json.loads(out)
                buffer, at = bytearray(length), 0
                for part in ref._view._parts(ref.index):
                    buffer[at:at+len(part)] = part
                    at += len(part)
                del buffer[at:]
                return json.loads(buffer)
        result = _owned(ref.scope, charge, small_decode, 'record-export')
        del scratch
        return result
    del scratch
    return _owned(ref.scope, charge, lambda: _decode_ref(ref), 'record-export')


class _ArraySource:
    def __init__(self, record, name):
        self.record, self.name = record, name
        self._owner = record._owner.retain()
        row = record._meta['arrays'][name]
        self.info = T.ArrayInfo(name, row['dtype'], tuple(row['shape']),
                               row['shape'][0]*np.dtype(row['dtype']).itemsize)

    def blocks(self, *, max_owned_bytes):
        T.require(max_owned_bytes >= OWNER_BYTES+128+8, 'array output bound too small')
        amount = min(T.CHUNK, max_owned_bytes-OWNER_BYTES-128)
        itemsize = np.dtype(self.info.dtype).itemsize
        amount -= amount % itemsize
        T.require(amount > 0, 'array output bound below element width')
        record, name = self.record, self.name
        anchor = self._owner.retain()
        def generate():
            for start in range(0, self.info.logical_bytes, amount):
                stop = min(self.info.logical_bytes, start+amount)
                if isinstance(record._columns, _Memory):
                    yield _owned(record.scope, stop-start+128,
                                 lambda: bytes(record._columns.raw(name, start, stop)), 'record-array-block')
                else:
                    yield record._columns.segment.read(name, start//itemsize, stop//itemsize,
                                                       max_owned_bytes=max_owned_bytes)
        return OwnedStream(generate(), owners=(anchor,), scope=record.scope)

    def close(self):
        self._owner.close()
        self.record = None
