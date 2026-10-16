"""Shared retained ownership and opt-in content caches for compact components.

Charges are held *existing* WorkBudget contexts. No resource admission scope or
optional-worker revoker is installed. Logical capacity is not measured RSS.
Raw ``value`` escapes require the caller to keep their Owned wrapper alive.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import CancelledError
from dataclasses import dataclass
import hashlib
import threading
from types import MappingProxyType
from typing import Generic, TypeVar
import uuid
import weakref

from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from compact_contracts import (FACT_CACHE_BYTES, PAGE_CACHE_BYTES, RETAINED_BYTES,
                               SUPPORT_CACHE_BYTES, ContractError)

T = TypeVar('T')
OWNER_BYTES = 4096
CACHE_CONTROL_BYTES = 2048
_QUOTAS = {'supports': SUPPORT_CACHE_BYTES, 'facts': FACT_CACHE_BYTES,
           'pages': PAGE_CACHE_BYTES, 'hashes': 20_000_000,
           'handles': RETAINED_BYTES}
_SCOPES = weakref.WeakKeyDictionary()
_SCOPES_LOCK = threading.Lock()
_CREATING = object()


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError('compact operation cancelled')


@dataclass(frozen=True, slots=True)
class ChargeSpec:
    purpose: str
    backing_bytes: int
    owner_bytes: int = OWNER_BYTES
    index_bytes: int = 0

    def __post_init__(self):
        if type(self.purpose) is not str or not 1 <= len(self.purpose) <= 48:
            raise ValueError('purpose must contain 1..48 characters')
        for value in (self.backing_bytes, self.owner_bytes, self.index_bytes):
            if type(value) is not int or value < 0:
                raise ValueError('charge capacities must be nonnegative integers')
        if self.owner_bytes < OWNER_BYTES:
            raise ValueError('owner capacity must fund the ownership carrier')

    @property
    def total_bytes(self):
        return self.backing_bytes + self.owner_bytes + self.index_bytes


class _Charge:
    """Entered WorkBudget context whose lifetime follows a real ownership object."""
    def __init__(self, scope, context, spec):
        self.scope, self.context, self.spec = scope, context, spec
        self.state = 'pending'
        self.allocation = None
        with scope._charges_lock:
            scope._charges[id(self)] = self

    def close(self):
        if self.context is not None:
            context, self.context = self.context, None
            with self.scope._charges_lock:
                self.scope._charges.pop(id(self), None)
            context.__exit__(None, None, None)

    def __del__(self):
        self.close()


class _Allocation:
    def __init__(self, value, charge, dependencies):
        self.value, self.charge, self.dependencies = value, charge, dependencies
        self.token = object()
        self.holders = weakref.WeakSet()
        self.cache_categories = {}
        self.charge_total = charge.spec.total_bytes
        self.lock = threading.RLock()
        charge.state = 'live'
        charge.allocation = weakref.ref(self)

    @property
    def cached(self):
        with self.lock:
            return bool(self.cache_categories)

    @property
    def pinned(self):
        with self.lock:
            return any(not holder._cache or holder._busy or holder._children
                       for holder in self.holders)

    def __del__(self):
        # Drop the backing before its funding, including dependency pins.
        self.value = None
        self.dependencies = ()
        self.charge.close()


class Reservation:
    def __init__(self, charge):
        self._charge = charge
        self._committed = False

    def commit(self, backing: T, *, dependencies=()) -> Owned[T]:
        if self._charge is None or self._committed:
            raise RuntimeError('reservation is closed or already committed')
        scope = self._charge.scope
        dependencies = tuple(dependencies)
        if any(not isinstance(owner, Owned) or owner.scope is not scope
               for owner in dependencies):
            raise ValueError('foreign dependency owner')
        held = tuple(owner.retain() for owner in dependencies)
        allocation = _Allocation(backing, self._charge, held)
        result = Owned._new(allocation)
        self._charge, self._committed = None, True
        return result

    def close(self):
        if self._charge is not None:
            charge, self._charge = self._charge, None
            charge.close()

    def __enter__(self):
        if self._charge is None:
            raise RuntimeError('closed reservation')
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        # Failed producer frames may hold an allocated backing before commit.
        # The reservation itself in that frame keeps the charge until GC.
        if exc_type is None:
            self.close()
        return False

    def __del__(self):
        self.close()


class Owned(Generic[T]):
    """One paid carrier; retain is a child borrow, cache shares are siblings."""
    @classmethod
    def _new(cls, allocation, *, carrier=None, parent=None, cache=False, category=None):
        result = cls.__new__(cls)
        result._allocation, result._carrier = allocation, carrier
        result._parent, result._cache = parent, cache
        result._cache_category = category
        result._children = result._busy = 0
        result._retired = False
        result._lock = threading.RLock()
        with allocation.lock:
            allocation.holders.add(result)
            if carrier is not None:
                carrier.state, carrier.allocation = 'live', weakref.ref(allocation)
                for name in allocation.cache_categories:
                    allocation.charge.scope._cache_charge(name, carrier.spec.total_bytes)
                allocation.charge_total += carrier.spec.total_bytes
            if category is not None:
                if category not in allocation.cache_categories:
                    allocation.charge.scope._cache_charge(category, allocation.charge_total)
                allocation.cache_categories[category] = allocation.cache_categories.get(category, 0) + 1
        if parent is not None:
            parent._children += 1
        return result

    @property
    def value(self) -> T:
        if self._allocation is None:
            raise RuntimeError('closed owner')
        return self._allocation.value

    @property
    def scope(self):
        if self._allocation is None:
            raise RuntimeError('closed owner')
        return self._allocation.charge.scope

    @property
    def allocation_id(self):
        if self._allocation is None:
            raise RuntimeError('closed owner')
        return self._allocation.token

    @property
    def charged_bytes(self):
        if self._allocation is None:
            return 0
        return self._allocation.charge.spec.total_bytes + (
            0 if self._carrier is None else self._carrier.spec.total_bytes)

    @property
    def borrow_count(self):
        with self._lock:
            return self._children + self._busy

    def assert_unborrowed(self):
        """Preflight native close; caller serialises native handle operations."""
        with self._lock:
            if self._children or self._busy:
                raise RuntimeError('owner has live child borrows')

    def _share(self, *, cache=False, spec=None, required=True, cancel=None):
        with self._lock:
            if self._allocation is None:
                raise RuntimeError('closed owner')
            self._busy += 1
            allocation = self._allocation
        try:
            reservation = allocation.charge.scope.reserve(
                spec or ChargeSpec('owner-carrier', 0), required=required, cancel=cancel)
            if reservation is None:
                return None
            with self._lock:
                result = Owned._new(allocation, carrier=reservation._charge,
                                    parent=None if cache else self, cache=cache,
                                    category=spec.purpose[6:] if cache else None)
                reservation._charge = None
            return result
        finally:
            with self._lock:
                self._busy -= 1
                if self._retired and not self._busy and not self._children:
                    self.close()

    def retain(self):
        return self._share()

    def _retire(self):
        with self._lock:
            self._retired = True
            if not self._busy and not self._children:
                self.close()

    def close(self):
        with self._lock:
            if self._allocation is None:
                return
            if self._children or self._busy:
                raise RuntimeError('owner has live child borrows')
            allocation, self._allocation = self._allocation, None
            with allocation.lock:
                allocation.holders.discard(self)
                if self._carrier is not None:
                    count = self._carrier.spec.total_bytes
                    for name in allocation.cache_categories:
                        allocation.charge.scope._cache_charge(name, -count)
                    allocation.charge_total -= count
                if self._cache_category is not None:
                    category = self._cache_category
                    allocation.cache_categories[category] -= 1
                    if not allocation.cache_categories[category]:
                        del allocation.cache_categories[category]
                        allocation.charge.scope._cache_charge(category, -allocation.charge_total)
            # Avoid keeping a local allocation after crediting its backing.
            del allocation
            if self._carrier is not None:
                carrier, self._carrier = self._carrier, None
                carrier.close()
            parent, self._parent = self._parent, None
            if parent is not None:
                with parent._lock:
                    parent._children -= 1
                    if parent._retired and not parent._children and not parent._busy:
                        parent.close()

    def __enter__(self):
        if self._allocation is None:
            raise RuntimeError('closed owner')
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.close()
        return False

    def __del__(self):
        if hasattr(self, '_lock'):
            self._retire()


class OwnedStream(Generic[T]):
    """A funded producer; escaped yields have independent owner lifetimes."""
    def __init__(self, iterator, *, owners=(), scope=None):
        owners = tuple(owners)
        if scope is None and owners:
            scope = owners[0].scope
        if not isinstance(scope, RetainedScope):
            raise ValueError('stream requires its retained scope or input owners')
        self._state = None
        self._failed = False
        with scope.reserve(ChargeSpec('stream-state', 0)) as reservation:
            self._state = reservation.commit(iter(iterator), dependencies=owners)

    def __iter__(self):
        return self

    def __next__(self):
        if self._state is None:
            raise StopIteration
        try:
            result = next(self._state.value)
            if not isinstance(result, Owned) or result.scope is not self._state.scope:
                raise ValueError('stream yielded an unowned or foreign value')
            return result
        except StopIteration:
            self.close()
            raise
        except BaseException:
            self._failed = True
            raise

    def close(self):
        if self._state is not None:
            iterator = self._state.value
            closer = getattr(iterator, 'close', None)
            if closer is not None:
                closer()
            # A failed iterator may still be reachable through a held traceback.
            # Keep its state funding until this stream itself is discarded.
            if not self._failed:
                self._state.close()
                self._state = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.close()
        else:
            self._failed = True
        return False


@dataclass(frozen=True, slots=True)
class RetainedStats:
    retained_bytes: int
    peak_retained_bytes: int
    pinned_bytes: int
    pending_bytes: int
    evictable_bytes: int
    non_cache_owned_bytes: int
    optional_declines: int
    required_refusals: int
    hits: object
    misses: object
    evictions: object
    insertions: object
    entries: object
    reclaimed_bytes: object
    category_bytes: object
    category_peak_bytes: object
    purpose_bytes: object
    purpose_peak_bytes: object

    @property
    def live_bytes(self):
        return self.retained_bytes - self.pending_bytes


class RetainedScope:
    def __init__(self, run_budget, *, process_epoch, _factory=False):
        if not _factory:
            raise TypeError('use create_retained_scope for one shared child')
        self._run_budget = run_budget
        self._retained_budget = WorkBudget(RETAINED_BYTES, parent=run_budget)
        self._scope_id, self._process_epoch = uuid.uuid4().hex, process_epoch
        self._charges, self._caches = weakref.WeakValueDictionary(), weakref.WeakSet()
        self._charges_lock = threading.RLock()
        self._cache_slots, self._shared_caches = {}, {}
        self._closed = False
        self._admitting = 0
        self._optional_declines = 0
        self._counter_lock = threading.Lock()
        self._cache_bytes = {category: 0 for category in _QUOTAS}
        self._cache_peaks = dict(self._cache_bytes)
        self._counters = {name: {category: 0 for category in _QUOTAS}
                          for name in ('hits', 'misses', 'evictions', 'insertions',
                                       'entries', 'reclaimed_bytes')}
        reservation = self.reserve(ChargeSpec('scope-control', 1024))
        self._base, reservation._charge = reservation._charge, None
        self._base.state = 'control'

    @property
    def run_budget(self):
        return self._run_budget

    @property
    def retained_budget(self):
        return self._retained_budget

    @property
    def scope_id(self):
        return self._scope_id

    @property
    def process_epoch(self):
        return self._process_epoch

    def _count(self, name, category, count=1):
        with self._counter_lock:
            self._counters[name][category] += count

    def _cache_charge(self, category, change):
        with self._counter_lock:
            self._cache_bytes[category] += change
            self._cache_peaks[category] = max(self._cache_peaks[category], self._cache_bytes[category])

    def reserve(self, spec, *, required=True, cancel=None):
        with self._charges_lock:
            if self._closed:
                raise RuntimeError('closed retained scope')
            self._admitting += 1
        try:
            return self._reserve(spec, required=required, cancel=cancel)
        finally:
            with self._charges_lock:
                self._admitting -= 1

    def _reserve(self, spec, *, required, cancel):
        if not isinstance(spec, ChargeSpec) or type(required) is not bool:
            raise TypeError('explicit ChargeSpec and boolean admission mode required')
        check_cancel(cancel)
        count, category = spec.total_bytes, 'retained:' + spec.purpose
        context = self.retained_budget.try_reserve(count, category=category)
        admitted = context.__enter__()
        if not admitted:
            context.__exit__(None, None, None)
            self.evict_unpinned(requested_bytes=count)
            check_cancel(cancel)
            if required:
                context = self.retained_budget.reserve(count, category=category)
                context.__enter__()
            else:
                context = self.retained_budget.try_reserve(count, category=category)
                if not context.__enter__():
                    context.__exit__(None, None, None)
                    self._optional_declines += 1
                    return None
        charge = _Charge(self, context, spec)
        try:
            check_cancel(cancel)
            return Reservation(charge)
        except BaseException:
            charge.close()
            raise

    def evict_unpinned(self, *, requested_bytes, category=None):
        if type(requested_bytes) is not int or requested_bytes < 0:
            raise ValueError('requested bytes must be nonnegative')
        if category is not None and category not in _QUOTAS:
            raise ValueError('unknown cache category')
        before = self.retained_budget.reserved_bytes
        for cache in tuple(self._caches):
            if category is None or cache.category == category:
                cache._evict(requested_bytes=requested_bytes)
                if before - self.retained_budget.reserved_bytes >= requested_bytes:
                    break
        return max(0, before - self.retained_budget.reserved_bytes)

    def stats(self):
        ledger = self.retained_budget.statistics()
        pending = pinned = evictable = non_cache = 0
        with self._charges_lock:
            for charge in self._charges.values():
                if charge.context is None:
                    continue
                count = charge.spec.total_bytes
                allocation = None if charge.allocation is None else charge.allocation()
                if charge.state == 'pending':
                    pending += count
                elif allocation is not None and allocation.cached:
                    if allocation.pinned:
                        pinned += count
                    else:
                        evictable += count
                else:
                    non_cache += count
        with self._counter_lock:
            counters = {name: MappingProxyType(dict(values))
                        for name, values in self._counters.items()}
            category_bytes = MappingProxyType(dict(self._cache_bytes))
            category_peak_bytes = MappingProxyType(dict(self._cache_peaks))
        return RetainedStats(ledger['reserved_bytes'], ledger['peak_reserved_bytes'],
            pinned, pending, evictable, non_cache, self._optional_declines,
            ledger['refusals'], **counters,
            category_bytes=category_bytes, category_peak_bytes=category_peak_bytes,
            purpose_bytes=MappingProxyType(ledger['categories']),
            purpose_peak_bytes=MappingProxyType(ledger['category_peaks']))

    def close(self):
        if self._closed:
            return
        for cache in tuple(self._caches):
            cache.close()
        with self._charges_lock:
            if self._admitting or any(charge is not self._base and charge.context is not None
                   for charge in self._charges.values()):
                raise RuntimeError('retained scope still has live owners or reservations')
            self._base.close()
            self._closed = True


def create_retained_scope(run_budget, *, process_epoch):
    if not isinstance(run_budget, WorkBudget):
        raise TypeError('run budget must be an existing WorkBudget')
    if type(process_epoch) is not str or not 1 <= len(process_epoch) <= 256:
        raise ValueError('process epoch must contain 1..256 characters')
    with _SCOPES_LOCK:
        reference = _SCOPES.get(run_budget)
        if reference is _CREATING:
            raise RuntimeError('retained scope creation already in progress')
        existing = None if reference is None else reference()
        if existing is not None and not existing._closed:
            if existing.process_epoch != process_epoch:
                raise ValueError('run budget already has another process epoch')
            return existing
        _SCOPES[run_budget] = _CREATING
    # Construction may trigger the existing worker revoker; never call it
    # while holding even the scope registry's lock.
    try:
        scope = RetainedScope(run_budget, process_epoch=process_epoch, _factory=True)
    except BaseException:
        with _SCOPES_LOCK:
            _SCOPES.pop(run_budget, None)
        raise
    with _SCOPES_LOCK:
        _SCOPES[run_budget] = weakref.ref(scope)
    return scope


@dataclass(frozen=True, slots=True)
class VerifiedCacheKey:
    category: str
    process_epoch: str
    authenticated_key_bytes: bytes

    def __post_init__(self):
        if self.category not in _QUOTAS:
            raise ValueError('unknown cache category')
        if type(self.process_epoch) is not str or not 1 <= len(self.process_epoch) <= 256:
            raise ValueError('invalid process epoch')
        if type(self.authenticated_key_bytes) is not bytes or len(self.authenticated_key_bytes) != 32:
            raise ValueError('cache key requires a complete authenticated SHA-256 binding')


def _key(category, epoch, tag, fields):
    digest = hashlib.sha256(tag.encode('ascii') + b'\0')
    for name, value in fields:
        if type(name) is not str or not name or type(value) is not bytes:
            raise TypeError('key fields require named exact bytes')
        label = name.encode('utf-8')
        digest.update(len(label).to_bytes(8, 'big'))
        digest.update(label)
        digest.update(len(value).to_bytes(8, 'big'))
        digest.update(value)
    return VerifiedCacheKey(category, epoch, digest.digest())


def support_key(*, process_epoch, support_identity, decoder_schema):
    return _key('supports', process_epoch, 'atlas.support-cache.v1',
                (('support', support_identity), ('decoder-schema', decoder_schema)))


def page_key(*, process_epoch, file_identity, chunk_id, descriptor_digest):
    return _key('pages', process_epoch, 'atlas.page-cache.v1',
                (('immutable-file', file_identity), ('typed-chunk', chunk_id),
                 ('descriptor', descriptor_digest)))


def verified_hash_key(*, process_epoch, file_identity, chunk_id, descriptor_digest):
    return _key('hashes', process_epoch, 'atlas.verified-hash-cache.v1',
                (('immutable-file', file_identity), ('typed-chunk', chunk_id),
                 ('descriptor', descriptor_digest)))


def view_seal_key(*, process_epoch, ordered_bindings, logical_schema,
                  canonical_profile, logical_identity):
    fields = [('logical-schema', logical_schema), ('profile', canonical_profile),
              ('logical-identity', logical_identity)]
    fields.extend(('ordered-descriptor', binding) for binding in ordered_bindings)
    return _key('hashes', process_epoch, 'atlas.view-seal-cache.v1', fields)


class ContentCache(Generic[T]):
    """Opt-in LRU; verifier must establish key/value binding before insertion."""
    def __init__(self, scope, category, *, max_bytes=None, max_entries=None,
                 enabled=True, verifier=None):
        if not isinstance(scope, RetainedScope) or category not in _QUOTAS:
            raise ValueError('cache requires the shared scope and known category')
        ceiling = _QUOTAS[category]
        if max_bytes is None:
            max_bytes = ceiling
        if type(max_bytes) is not int or not 0 <= max_bytes <= ceiling:
            raise ValueError('cache retention quota exceeds its frozen ceiling')
        if max_entries is None:
            max_entries = 200_000 if category == 'hashes' else 1_000_000
        if type(max_entries) is not int or max_entries < 0 or (
                category == 'hashes' and max_entries > 200_000):
            raise ValueError('invalid cache entry quota')
        if enabled and not callable(verifier):
            raise TypeError('enabled cache requires an insertion verifier')
        if enabled and max_bytes < CACHE_CONTROL_BYTES + OWNER_BYTES:
            raise ValueError('cache quota cannot fund its control capacity')
        with scope._charges_lock:
            reference = scope._cache_slots.get(category)
            if reference is _CREATING:
                raise RuntimeError('cache creation already in progress for this category')
            if reference is not None and reference() is not None:
                raise ValueError('share the existing cache for this scope/category')
            scope._cache_slots[category] = _CREATING
        try:
            self.scope, self.category = scope, category
            self.max_bytes, self.max_entries = max_bytes, max_entries
            self.enabled, self.verifier = bool(enabled), verifier
            self._lock, self._entries, self._closed = threading.RLock(), OrderedDict(), False
            self._allocations = {}
            with scope.reserve(ChargeSpec('cache-control', CACHE_CONTROL_BYTES)) as reservation:
                self._control = reservation.commit(None)
            if self.enabled:
                scope._cache_charge(category, self._control.charged_bytes)
            self._retention_bytes = self._control.charged_bytes
            with scope._charges_lock:
                scope._caches.add(self)
                scope._cache_slots[category] = weakref.ref(self)
        except BaseException:
            with scope._charges_lock:
                scope._cache_slots.pop(category, None)
            raise

    def _validate(self, key):
        if self._closed:
            raise RuntimeError('closed cache')
        if not isinstance(key, VerifiedCacheKey) or key.category != self.category:
            raise ValueError('cache key category mismatch')
        if key.process_epoch != self.scope.process_epoch:
            raise ValueError('cache key belongs to another process epoch')

    def _occupancy(self):
        return self._retention_bytes

    def _insert_entry(self, key, owner):
        allocation = owner._allocation
        if allocation not in self._allocations:
            self._retention_bytes += allocation.charge.spec.total_bytes
        self._allocations[allocation] = self._allocations.get(allocation, 0) + 1
        self._retention_bytes += owner._carrier.spec.total_bytes
        self._entries[key] = owner

    def _remove_entry(self, key):
        owner = self._entries.pop(key)
        allocation = owner._allocation
        self._retention_bytes -= owner._carrier.spec.total_bytes
        self._allocations[allocation] -= 1
        if not self._allocations[allocation]:
            del self._allocations[allocation]
            self._retention_bytes -= allocation.charge.spec.total_bytes
        return owner

    def get(self, key, *, cancel=None):
        self._validate(key)
        check_cancel(cancel)
        with self._lock:
            owner = self._entries.get(key) if self.enabled else None
            if owner is not None:
                self._entries.move_to_end(key)
                with owner._lock:
                    owner._busy += 1
        if owner is None:
            self.scope._count('misses', self.category)
            return None
        try:
            result = owner._share(cancel=cancel)
            # A failing verifier may leave a raw value in its traceback. The
            # still-live result in this frame keeps that value charged/pinned.
            if self.verifier(key, result.value) is not True:
                raise ContractError('cached content changed since verification')
            check_cancel(cancel)
            self.scope._count('hits', self.category)
            return result
        finally:
            with owner._lock:
                owner._busy -= 1
                if owner._retired and not owner._busy and not owner._children:
                    owner.close()

    def offer_verified(self, key, value, *, cancel=None):
        self._validate(key)
        if not isinstance(value, Owned) or value.scope is not self.scope:
            raise ValueError('cache cannot adopt a foreign owner')
        check_cancel(cancel)
        if not self.enabled:
            return False
        if self.verifier(key, value.value) is not True:
            raise ContractError('cache insertion did not verify its exact content binding')
        check_cancel(cancel)
        carrier_spec = ChargeSpec('cache-' + self.category, 0,
                                 index_bytes=512 + len(key.process_epoch.encode('utf-8')) * 4 + 32)
        cost = value._allocation.charge.spec.total_bytes + carrier_spec.total_bytes
        if cost > self.max_bytes or not self.max_entries:
            self.scope._optional_declines += 1
            return False
        self._evict(requested_bytes=0, needed_bytes=cost, needed_entries=1)
        with self._lock:
            if key in self._entries:
                return True
            if self._occupancy() + cost > self.max_bytes or len(self._entries) >= self.max_entries:
                self.scope._optional_declines += 1
                return False
        cached = value._share(cache=True, spec=carrier_spec, required=False, cancel=cancel)
        if cached is None:
            return False
        try:
            check_cancel(cancel)
            with self._lock:
                if self._closed:
                    raise RuntimeError('cache closed during insertion')
                if key in self._entries:
                    return True
                if self._occupancy() + cost > self.max_bytes or len(self._entries) >= self.max_entries:
                    self.scope._optional_declines += 1
                    return False
                self._insert_entry(key, cached)
                cached = None
                self.scope._count('entries', self.category)
                self.scope._count('insertions', self.category)
                return True
        finally:
            if cached is not None:
                cached._retire()

    def _evict(self, *, requested_bytes, needed_bytes=0, needed_entries=0):
        before = self.scope.retained_budget.reserved_bytes
        while True:
            reclaimed = max(0, before - self.scope.retained_budget.reserved_bytes)
            if requested_bytes and reclaimed >= requested_bytes:
                break
            with self._lock:
                enough_space = self._occupancy() + needed_bytes <= self.max_bytes
                enough_entries = len(self._entries) + needed_entries <= self.max_entries
                if requested_bytes == 0 and enough_space and enough_entries:
                    break
                owner = None
                for key, candidate in self._entries.items():
                    if not candidate._allocation.pinned:
                        owner = candidate
                        break
                if owner is None:
                    break
                self._remove_entry(key)
                self.scope._count('entries', self.category, -1)
                self.scope._count('evictions', self.category)
            # No admission/callback under the lock and no whole-LRU snapshot.
            owner._retire()
            owner = candidate = None
        reclaimed = max(0, before - self.scope.retained_budget.reserved_bytes)
        self.scope._count('reclaimed_bytes', self.category, reclaimed)
        return reclaimed

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
        while True:
            with self._lock:
                if not self._entries:
                    break
                owner = self._remove_entry(next(iter(self._entries)))
                self.scope._count('entries', self.category, -1)
            owner._retire()
        if self.enabled:
            self.scope._cache_charge(self.category, -self._control.charged_bytes)
        self._control.close()
        with self.scope._charges_lock:
            reference = self.scope._cache_slots.get(self.category)
            if reference is not None and reference is not _CREATING and reference() is self:
                self.scope._cache_slots.pop(self.category)
            if self.scope._shared_caches.get(self.category) is self:
                self.scope._shared_caches.pop(self.category)

    def __del__(self):
        if hasattr(self, '_control'):
            self.close()


def get_content_cache(scope, category, *, enabled, verifier, max_bytes=None, max_entries=None):
    """Share one configured cache until scope close; enablement is explicit.

    A stable module-level verifier is part of the shared configuration. Different
    verifiers, modes or quotas refuse instead of replacing another consumer's
    cache. A concurrent/reentrant construction refuses rather than holding any
    cache/registry lock during mandatory admission and worker revocation.
    """
    if not isinstance(scope, RetainedScope) or category not in _QUOTAS:
        raise ValueError('cache requires the shared scope and known category')
    if type(enabled) is not bool:
        raise TypeError('shared cache enablement must be explicit boolean')
    expected_bytes = _QUOTAS[category] if max_bytes is None else max_bytes
    expected_entries = (200_000 if category == 'hashes' else 1_000_000) if max_entries is None else max_entries
    if type(expected_bytes) is not int or not 0 <= expected_bytes <= _QUOTAS[category]:
        raise ValueError('invalid shared cache byte quota')
    if type(expected_entries) is not int or expected_entries < 0 or (
            category == 'hashes' and expected_entries > 200_000):
        raise ValueError('invalid shared cache entry quota')
    with scope._charges_lock:
        if scope._closed:
            raise RuntimeError('closed retained scope')
        reference = scope._cache_slots.get(category)
        if reference is _CREATING:
            raise RuntimeError('cache creation already in progress for this category')
        cache = None if reference is None else reference()
        if cache is not None:
            if (cache.enabled != enabled or cache.verifier is not verifier or
                    cache.max_bytes != expected_bytes or cache.max_entries != expected_entries):
                raise ValueError('shared cache configuration differs')
            if cache._closed:
                raise RuntimeError('cache close is in progress')
            scope._shared_caches[category] = cache
            return cache
    cache = ContentCache(scope, category, enabled=enabled, verifier=verifier,
                         max_bytes=max_bytes, max_entries=max_entries)
    with scope._charges_lock:
        if scope._closed or cache._closed:
            raise RuntimeError('shared cache was closed during creation')
        scope._shared_caches[category] = cache
    return cache
