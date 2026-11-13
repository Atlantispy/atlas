"""Shared byte admission for accounted work, not an operating-system RSS limiter.

A parent budget composes independently bounded subsystems. A reservation charges
all distinct ancestors exactly once, even when both a store and its caller name
related budgets. Retained capacity must stay reserved for its owner's lifetime.
Caller buffers/native allocator baselines need explicit allowances and measured
headroom; reserving estimated bytes does not constrain the allocator itself.
"""
from __future__ import annotations
from contextlib import contextmanager
import math
import sys
import threading


class MemoryLimitError(ValueError):
    """A requested operation exceeds its explicit allocation envelope."""


# One budget may carry one private admission scope (WorkBudget._scope). The
# admission asks it, before any lock is taken, which ledger a category is
# charged on: the budget itself, or a side ledger the scope owns while it
# charges the budget with measured memory. Without a scope nothing differs.
SCOPE_ADMISSION = 'scope-admission.r1'


class PredicateWorkLimitError(ValueError):
    """Explicit finite predicate-work allowance, measured in units, exhausted."""
    def __init__(self, count, category):
        self.requested_units, self.category = count, category
        super().__init__(f'projected combined predicate work exceeds allowance '
                         f'(request {count} units; category {category!r})')


class _BudgetLocks:
    """Enter already ordered, distinct ledger locks without late registration.

    ExitStack.enter_context acquires a lock before allocating/registering its
    exit callback. A RecursionError in that gap strands the lock. Prepare every
    protocol callback and ownership slot before taking any lock instead. The
    rollback is inline: calling another Python cleanup frame while already at
    the recursion limit would introduce the same hazard during unwinding.
    Hooks implement the non-suppressing threading.Lock context protocol, not
    arbitrary suppressing context managers. Every acquired hook is exited even
    if another exit raises, with the current exception and its context chain.
    """
    def __init__(self, ordered):
        self.entries = []
        for node in ordered:
            lock = node._lock
            self.entries.append([lock, type(lock).__enter__, type(lock).__exit__, False])
        self.reverse = self.entries[::-1]

    def __enter__(self):
        try:
            for entry in self.entries:
                entry[1](entry[0])
                entry[3] = True
        except BaseException:
            details = sys.exc_info()
            frame_error = details[1]
            failure = None
            for entry in self.reverse:
                if entry[3]:
                    entry[3] = False
                    try:
                        entry[2](entry[0], details[0], details[1], details[2])
                    except BaseException as error:
                        context = error
                        if error is not details[1]:
                            while context.__context__ is not details[1]:
                                if context.__context__ is None or context.__context__ is frame_error:
                                    context.__context__ = details[1]
                                    break
                                context = context.__context__
                        details = (type(error), error, error.__traceback__)
                        failure = error
            if failure is not None:
                context = failure.__context__
                try:
                    raise failure
                except BaseException:
                    failure.__context__ = context
                    raise
            raise
        return self

    def __exit__(self, kind, error, traceback):
        details = (kind, error, traceback)
        frame_error = sys.exc_info()[1]
        failure = None
        for entry in self.reverse:
            if entry[3]:
                entry[3] = False
                try:
                    entry[2](entry[0], details[0], details[1], details[2])
                except BaseException as caught:
                    context = caught
                    if caught is not details[1]:
                        while context.__context__ is not details[1]:
                            if context.__context__ is None or context.__context__ is frame_error:
                                context.__context__ = details[1]
                                break
                            context = context.__context__
                    details = (type(caught), caught, caught.__traceback__)
                    failure = caught
        if failure is not None:
            context = failure.__context__
            try:
                raise failure
            except BaseException:
                failure.__context__ = context
                raise
        return False


class WorkBudget:
    """Nonblocking, thread-safe admission; parents coordinate component limits.

    ``statistics`` returns a detached accounting snapshot, not measured RSS.
    The maximum is immutable so a live reservation cannot be invalidated by a
    caller lowering the limit or silently widening an established envelope.
    """
    _scope = None

    def __init__(self, max_bytes: int, *, parent: WorkBudget | None = None,
                 max_predicate_work_units: int | None = None):
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if parent is not None and not isinstance(parent, WorkBudget):
            raise TypeError("parent must be a WorkBudget")
        if max_predicate_work_units is None and parent is not None:
            max_predicate_work_units = parent.max_predicate_work_units
        if max_predicate_work_units is not None:
            if type(max_predicate_work_units) is not int or max_predicate_work_units <= 0:
                raise ValueError('max_predicate_work_units must be a positive integer or None')
            if parent is not None and parent.max_predicate_work_units is None:
                raise ValueError('separate predicate work requires an opted-in parent scope')
        # A private parallel tree reuses the exact integer admission ledger.
        # Its counts are predicate units, NOT RAM bytes; never expose its byte-
        # named implementation statistics or charge it for physical storage.
        self._predicate_work = (None if max_predicate_work_units is None else
            WorkBudget(max_predicate_work_units,
                       parent=None if parent is None else parent._predicate_work))
        self._max_bytes = max_bytes
        self._parent = parent
        self._used = 0
        self._peak = 0
        self._refusals = 0
        self._categories = {}
        self._category_peaks = {}
        self._lock = threading.Lock()
        # Private optional-work owner, registered on both complete ledger
        # ancestries under their ordered locks. One owner per shared ancestry.
        # revoke() must close optional admission, confirm its workers stopped,
        # then release only its charges. It must serialise concurrent calls,
        # reject same-thread reentrancy, and propagate any stop failure.
        self._revoker = None
        # Returned reservations waiting for the lock. A lease is often returned by a garbage-collection
        # finalizer, which runs in whatever thread triggered the collection and at any point, possibly while
        # that thread holds this lock; a return therefore never waits for it (_release), and whoever holds
        # the lock next applies the queue first.
        self._returned = []
        # Private retryable leases use one cumulative receipt per ancestor,
        # not one allocation per shrink. GC may enqueue without this lock.
        self._ticket_returns = {}
        self._return_draining = None
        self._return_active = None

    def _settle(self):
        # The caller holds self._lock. list.append/pop are atomic, so a finalizer may queue meanwhile.
        while (self._returned or self._ticket_returns or self._return_draining is not None
               or self._return_active is not None):
            if not (self._ticket_returns or self._return_draining is not None
                    or self._return_active is not None):
                count, label = self._returned.pop()
                self._used -= count
                self._categories[label] -= count
                continue
            if self._return_draining is None:
                self._return_draining = self._ticket_returns
            if self._ticket_returns is self._return_draining:
                # Retain the old table before replacing it. Producers that
                # selected the old table requeue into the new one, so neither
                # interruption nor recursive GC can lose their entry. Dropping
                # the drained table also drops its peak-sized hash capacity.
                self._ticket_returns = {}
            if self._return_active is None:
                if not self._return_draining:
                    self._return_draining = None
                    continue
                entry = next(iter(self._return_draining))
                target = entry.returned
                delta = target-entry.applied
                # Publish the whole transaction before changing either
                # balance. Every admission/snapshot resumes it first.
                self._return_active = (entry, target, self._used-delta,
                                       self._categories[entry.label]-delta)
            entry, target, used, category = self._return_active
            self._return_draining.pop(entry, None)
            self._used = used
            self._categories[entry.label] = category
            entry.applied = target
            # A recursive finalizer may have increased the cumulative target
            # while this transaction was active. Do not discard that return.
            if entry.returned > target:
                self._ticket_returns.setdefault(entry, None)
            self._return_active = None

    @property
    def max_predicate_work_units(self):
        """None retains legacy byte-equivalent work; children inherit opt-in."""
        return None if self._predicate_work is None else self._predicate_work.max_bytes

    @property
    def max_bytes(self):
        return self._max_bytes

    @property
    def reserved_bytes(self):
        with self._lock:
            self._settle()
            return self._used

    @property
    def peak_reserved_bytes(self):
        with self._lock:
            return self._peak

    @property
    def available_bytes(self):
        # Admission rechecks atomically: this value is only a scheduling hint.
        with self._lock:
            self._settle()
            available = self._max_bytes - self._used
        if self._parent is not None:
            available = min(available, self._parent.available_bytes)
        return available

    def statistics(self):
        work = self._predicate_work
        ordered = (self,) if work is None else sorted((self, work), key=id)
        # Owner registration takes both ledgers in this same global order.
        # Read both under those locks, without recursively acquiring either.
        with _BudgetLocks(ordered):
            self._settle()
            result = dict(max_bytes=self._max_bytes, reserved_bytes=self._used,
                          peak_reserved_bytes=self._peak, refusals=self._refusals,
                          categories=dict(self._categories),
                          category_peaks=dict(self._category_peaks))
            if work is not None:
                work._settle()
                result['predicate_work'] = dict(max_units=work._max_bytes,
                    reserved_units=work._used, peak_reserved_units=work._peak,
                    refusals=work._refusals, categories=dict(work._categories),
                    category_peaks=dict(work._category_peaks))
            return result

    @contextmanager
    def reserve_predicate_work(self, count: int, *, category: str = 'predicate-work'):
        """Reserve units on an explicitly opted-in scope, never physical bytes."""
        with _GrowingPredicateLease(self) as lease:
            lease.add(count, category=category)
            yield

    def reserve(self, count: int, *, category: str = 'work'):
        return reserve_budgets(count, self, category=category)

    @contextmanager
    def try_reserve(self, count: int, *, category: str = 'work'):
        """Yield admission without refusal statistics when optional work cannot fit.

        Admission checks and charges every distinct ancestor under the same
        locks as mandatory reservations. A false result changes no accounting
        except settling returned leases; invalid arguments still raise.
        """
        charged = _admit_budgets(count, self, category=category, _optional=True)
        try:
            yield charged is not None
        finally:
            if charged is not None:
                _release(charged, count)


def _admit_budgets(count: int, *budgets: WorkBudget, category: str = 'work', _optional=False):
    """Atomically charge overlapping budgets once; no partial request charges.

    Locks have one total order, never a wait while retaining another budget's
    reservation. This prevents both ancestor double-counting and partial-admission
    leaks. The category inventory is bounded to avoid turning diagnostics into an
    unbounded cache; additional caller categories are grouped as ``other``.
    Optional misses never revoke or count refusals. A mandatory shortfall may
    revoke one registered optional owner outside all locks, then retry once;
    only an unresolved shortfall counts the original refusal on every ledger.
    """
    if type(count) is not int or count < 0:
        raise ValueError("reservation must be a nonnegative integer")
    if type(category) is not str or not category or len(category) > 64:
        raise ValueError("category must be a nonempty string of at most 64 characters")
    unique = {}
    for budget in budgets:
        if not isinstance(budget, WorkBudget):
            raise TypeError("budgets must be WorkBudget instances")
        scope = budget._scope
        if scope is not None:
            budget = scope.admit(budget, count, category)
            if type(budget) is not WorkBudget:
                raise TypeError("an admission scope must name a WorkBudget")
        node = budget
        seen = set()
        while node is not None:
            if id(node) in seen:
                raise ValueError("cyclic budget ancestry")
            seen.add(id(node)); unique[id(node)] = node
            node = node._parent
    if not unique:
        raise ValueError("at least one budget required")
    ordered = sorted(unique.values(), key=id)
    attempted = False
    while True:
        revoker = None
        with _BudgetLocks(ordered):
            for node in ordered:
                node._settle()
            if any(count > node._max_bytes - node._used for node in ordered):
                if _optional:
                    return None
                if not attempted:
                    for node in ordered:
                        if count > node._max_bytes - node._used and node._revoker is not None:
                            if revoker is not None and node._revoker is not revoker:
                                raise RuntimeError('multiple optional owners in one mandatory admission')
                            revoker = node._revoker
                if revoker is None:
                    for node in ordered:
                        node._refusals += 1
                    raise MemoryLimitError("projected combined workspace exceeds memory budget")
            else:
                charged = []
                for node in ordered:
                    label = category if category in node._categories or len(node._categories) < 63 else 'other'
                    node._used += count
                    node._peak = max(node._peak, node._used)
                    node._categories[label] = node._categories.get(label, 0) + count
                    node._category_peaks[label] = max(node._category_peaks.get(label, 0), node._categories[label])
                    charged.append((node, label))
                return charged
        # Never stop workers or wait on their owner while holding a ledger
        # lock. A failed stop aborts here without releasing any owned charges.
        revoker.revoke()
        attempted = True


@contextmanager
def reserve_budgets(count: int, *budgets: WorkBudget, category: str = 'work'):
    """Atomically reserve related budgets; release this charge on exit."""
    charged = _admit_budgets(count, *budgets, category=category)
    try:
        yield
    finally:
        _release(charged, count)


class _GrowingLease:
    """One owner, exact cumulative charges grouped by budget and actual label.

    Like _Arena/ExitStack, the ledger itself is single-owner, not concurrently
    mutated. Shared WorkBudgets retain their existing atomic admission locks.
    """
    def __init__(self, *budgets):
        self.budgets, self.charges, self.closed = budgets, {}, False

    def __enter__(self):
        return self

    def add(self, count, *, category='work'):
        if self.closed:
            raise RuntimeError('closed cumulative lease')
        charged = _admit_budgets(count, *self.budgets, category=category)
        try:
            # A ledger-allocation exception must return just this increment,
            # leaving the already-owned charges intact for normal unwind.
            updated = dict(self.charges)
            for node, label in charged:
                key = (node, label)
                updated[key] = updated.get(key, 0)+count
        except BaseException:
            _release(charged, count)
            raise
        self.charges = updated

    def __exit__(self, *args):
        if not self.closed:
            self.closed = True
            charged, self.charges = self.charges, {}
            for (node, label), count in charged.items():
                _release(((node, label),), count)
        return False


class _GrowingPredicateLease(_GrowingLease):
    """Cumulative unit charges with the same ancestor/atomic/release policy."""
    def __init__(self, *budgets):
        if not budgets or any(not isinstance(budget, WorkBudget) for budget in budgets):
            raise TypeError('predicate work requires explicit WorkBudget instances')
        if any(budget._predicate_work is None for budget in budgets):
            raise ValueError('predicate work requires an explicit finite unit allowance')
        super().__init__(*(budget._predicate_work for budget in budgets))

    def add(self, count, *, category='predicate-work'):
        try:
            super().add(count, category=category)
        except MemoryLimitError:
            # New traceback has no byte-admission frame: failure capture must
            # not mislabel a predicate count as a requested physical allocation.
            raise PredicateWorkLimitError(count, category) from None


class _ResizableLease:
    """One live allocation pool, not a cumulative history of allocations.

    Growing is admitted atomically before the owner allocates; shrinking is
    allowed only after the owner drops or transfers the corresponding objects.
    The fixed category keeps the ancestor/overflow labels stable for releases.
    """
    def __init__(self, *budgets, category='work'):
        self.budgets, self.category = budgets, category
        self.count, self.charged, self.closed = 0, (), False

    def __enter__(self):
        if self.closed:
            raise RuntimeError('closed live lease')
        return self

    def resize(self, count):
        if self.closed:
            raise RuntimeError('closed live lease')
        if type(count) is not int or count < 0:
            raise ValueError('live capacity must be a nonnegative integer')
        delta = count-self.count
        if delta > 0:
            charged = _admit_budgets(delta, *self.budgets, category=self.category)
            if self.charged and charged != self.charged:
                _release(charged, delta)
                raise RuntimeError('live lease budget labels changed')
            self.charged = charged
        elif delta < 0:
            _release(self.charged, -delta)
        self.count = count

    def __exit__(self, *args):
        if not self.closed:
            self.closed = True
            _release(self.charged, self.count)
            self.count = 0
        return False


class _ReturnEntry:
    __slots__ = ('node', 'label', 'returned', 'applied')

    def __init__(self, node, label):
        self.node, self.label = node, label
        self.returned = self.applied = 0


class _ReturnTicket:
    """Private single-owner, cumulative return receipt, funded by its caller.

    Retain this ticket before the first return. With it, _release's count is
    the TOTAL returned over the lease lifetime, not a new decrement. Replaying
    that total is harmless even after a queue/settle call was interrupted.
    Ordinary leases retain their existing delta-return API and guarantees.
    """
    __slots__ = ('charged', 'entries')

    def __init__(self, charged):
        self.charged = charged
        self.entries = tuple(_ReturnEntry(node, label) for node, label in charged)


def _release(charged, count, *, _ticket=None):
    """Return one reservation without ever waiting for a lock.

    A return may run inside a garbage-collection finalizer (weakref.finalize of a lease owner), in whatever thread
    triggered the collection and at any point of it, including while that thread holds one of these locks inside
    another reservation; waiting there would deadlock. Each budget queues the return and applies it now when its lock
    is free, otherwise its next holder applies it before using the account. Refusal and admission stay atomic.
    """
    if _ticket is None:
        for node, label in charged:
            node._returned.append((count, label))
    else:
        if _ticket.charged is not charged or type(count) is not int or count < 0:
            raise ValueError('a return ticket requires its original charge and cumulative count')
        for entry in _ticket.entries:
            entry.returned = max(entry.returned, count)
            while True:
                incoming = entry.node._ticket_returns
                incoming.setdefault(entry, None)
                if incoming is entry.node._ticket_returns:
                    break
    for node, _ in charged:
        if node._lock.acquire(blocking=False):
            try:
                node._settle()
            finally:
                node._lock.release()


# Conservative local policy, not the owner's hardware specification. Stores and
# executors now join this same envelope unless an explicit run budget is supplied.
DEFAULT_BUDGET = WorkBudget(256 * 1024 * 1024)


def elements(shape):
    if len(shape) > 32 or any(type(n) is not int or n < 0 for n in shape):
        raise ValueError("invalid array shape")
    return math.prod(shape)


def select_budget(budget):
    if budget is None:
        return DEFAULT_BUDGET
    if not isinstance(budget, WorkBudget):
        raise TypeError("budget must be a WorkBudget")
    return budget
