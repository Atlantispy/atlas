"""Allocation admission for array kernels, not a process-wide RSS limiter.

Caller-owned inputs, retained outputs and third-party native allocator overhead are
outside this estimate. Share one budget across concurrent calls. No waiting queue:
refusal leaves accepted state unchanged. Limits are execution policy, not physics.
"""
from __future__ import annotations
from contextlib import contextmanager
import math
import threading


class MemoryLimitError(ValueError):
    """A requested operation exceeds its explicit allocation envelope."""


class WorkBudget:
    def __init__(self, max_bytes: int):
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self.max_bytes = max_bytes
        self._used = 0
        self._peak = 0
        self._lock = threading.Lock()

    @property
    def reserved_bytes(self):
        with self._lock:
            return self._used

    @property
    def peak_reserved_bytes(self):
        with self._lock:
            return self._peak

    @contextmanager
    def reserve(self, count: int):
        if type(count) is not int or count < 0:
            raise ValueError("reservation must be a nonnegative integer")
        with self._lock:
            if count > self.max_bytes - self._used:
                raise MemoryLimitError("projected array workspace exceeds memory budget")
            self._used += count
            self._peak = max(self._peak, self._used)
        try:
            yield
        finally:
            with self._lock:
                self._used -= count


# Conservative local allocation policy, not an owner hardware specification.
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
