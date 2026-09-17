"""Shared byte admission for accounted work, not an operating-system RSS limiter.

A parent budget composes independently bounded subsystems. A reservation charges
all distinct ancestors exactly once, even when both a store and its caller name
related budgets. Retained capacity must stay reserved for its owner's lifetime.
Caller buffers/native allocator baselines need explicit allowances and measured
headroom; reserving estimated bytes does not constrain the allocator itself.
"""
from __future__ import annotations
from contextlib import contextmanager, ExitStack
import math
import threading


class MemoryLimitError(ValueError):
    """A requested operation exceeds its explicit allocation envelope."""


class WorkBudget:
    """Nonblocking, thread-safe admission; parents coordinate component limits.

    ``statistics`` returns a detached accounting snapshot, not measured RSS.
    The maximum is immutable so a live reservation cannot be invalidated by a
    caller lowering the limit or silently widening an established envelope.
    """
    def __init__(self, max_bytes: int, *, parent: WorkBudget | None = None):
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if parent is not None and not isinstance(parent, WorkBudget):
            raise TypeError("parent must be a WorkBudget")
        self._max_bytes = max_bytes
        self._parent = parent
        self._used = 0
        self._peak = 0
        self._refusals = 0
        self._categories = {}
        self._category_peaks = {}
        self._lock = threading.Lock()

    @property
    def max_bytes(self):
        return self._max_bytes

    @property
    def reserved_bytes(self):
        with self._lock:
            return self._used

    @property
    def peak_reserved_bytes(self):
        with self._lock:
            return self._peak

    @property
    def available_bytes(self):
        # Admission rechecks atomically: this value is only a scheduling hint.
        with self._lock:
            available = self._max_bytes - self._used
        if self._parent is not None:
            available = min(available, self._parent.available_bytes)
        return available

    def statistics(self):
        with self._lock:
            return dict(max_bytes=self._max_bytes, reserved_bytes=self._used,
                        peak_reserved_bytes=self._peak, refusals=self._refusals,
                        categories=dict(self._categories),
                        category_peaks=dict(self._category_peaks))

    def reserve(self, count: int, *, category: str = 'work'):
        return reserve_budgets(count, self, category=category)


@contextmanager
def reserve_budgets(count: int, *budgets: WorkBudget, category: str = 'work'):
    """Atomically charge overlapping budgets once; refusal leaves all unchanged.

    Locks have one total order, never a wait while retaining another budget's
    reservation. This prevents both ancestor double-counting and partial-admission
    leaks. The category inventory is bounded to avoid turning diagnostics into an
    unbounded cache; additional caller categories are grouped as ``other``.
    """
    if type(count) is not int or count < 0:
        raise ValueError("reservation must be a nonnegative integer")
    if type(category) is not str or not category or len(category) > 64:
        raise ValueError("category must be a nonempty string of at most 64 characters")
    unique = {}
    for budget in budgets:
        if not isinstance(budget, WorkBudget):
            raise TypeError("budgets must be WorkBudget instances")
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
    charged = []
    with ExitStack() as stack:
        for node in ordered:
            stack.enter_context(node._lock)
        if any(count > node._max_bytes - node._used for node in ordered):
            for node in ordered:
                node._refusals += 1
            raise MemoryLimitError("projected combined workspace exceeds memory budget")
        for node in ordered:
            label = category if category in node._categories or len(node._categories) < 63 else 'other'
            node._used += count
            node._peak = max(node._peak, node._used)
            node._categories[label] = node._categories.get(label, 0) + count
            node._category_peaks[label] = max(node._category_peaks.get(label, 0), node._categories[label])
            charged.append((node, label))
    try:
        yield
    finally:
        with ExitStack() as stack:
            for node in ordered:
                stack.enter_context(node._lock)
            for node, label in charged:
                node._used -= count
                node._categories[label] -= count


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
