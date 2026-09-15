"""Bounded, deterministic process dispatch; no scientific or storage policy.

Workers and initializers must be importable/picklable callables. Even a one-worker
pool uses a spawned child: initializers never alter the coordinator's globals.
The memory bound is a caller-supplied per-worker estimate, not an OS RSS limit.
Only the coordinator receives results; this module never writes any files.
"""
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import math
import multiprocessing
import os
import pickle
import sys
import threading
import time


_IN_WORKER = False
_WORKER = None
_FIELDS = frozenset(("product", "artifacts", "diagnostics"))
_HEX = frozenset("0123456789abcdef")


def _positive_int(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(name + " must be a positive integer")
    return value


def _json_value(value):
    """Validate without serialising/copying potentially large artifact records."""
    active = set()

    def visit(item):
        kind = type(item)
        if item is None or kind in (str, bool, int):
            return
        if kind is float:
            if not math.isfinite(item):
                raise ValueError("non-finite JSON number")
            return
        if kind not in (list, dict):
            raise ValueError("job/result contains a non-JSON value")
        marker = id(item)
        if marker in active:
            raise ValueError("cyclic job/result")
        active.add(marker)
        try:
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        raise ValueError("JSON object keys must be strings")
                    visit(child)
            else:
                for child in item:
                    visit(child)
        finally:
            active.remove(marker)

    visit(value)


def _record(value):
    if type(value) is not dict or set(value) != _FIELDS:
        raise ValueError("worker must return exactly product, artifacts and diagnostics")
    if any(type(value[key]) is not dict for key in _FIELDS):
        raise ValueError("worker product, artifacts and diagnostics must be objects")
    for key, artifact in value["artifacts"].items():
        if (type(key) is not str or len(key) != 64 or not set(key) <= _HEX
                or type(artifact) is not dict):
            raise ValueError("artifacts must map lowercase SHA256 keys to objects")
    _json_value(value)
    return value


def _initialise(worker, initializer, initargs):
    global _IN_WORKER, _WORKER
    _IN_WORKER = True
    _WORKER = worker
    if initializer is not None:
        initializer(*initargs)


def _invoke(job):
    if not _IN_WORKER or _WORKER is None:
        raise RuntimeError("worker was not initialised")
    started = time.perf_counter()
    record = _record(_WORKER(job))
    return record, os.getpid(), time.perf_counter() - started


class PoolBackend:
    """Persistent spawn pool, with at most effective_workers jobs in flight.

    execute accepts a list of JSON objects with unique stage_id strings and
    returns an insertion-ordered mapping in the same order as the submitted
    jobs. Every returned record is complete and structurally validated. Caller
    validation must additionally enforce source bindings, artifact checksums,
    scientific contracts and dependency independence.

    Any dispatch/worker/protocol failure permanently closes the backend, cancels
    queued futures, waits for running workers and raises: no partial mapping is
    returned. Reusing successful workers across execute calls is supported.
    """

    def __init__(self, worker, *, initializer=None, initargs=(), workers=2,
                 memory_budget_mb=1024, worker_memory_mb=256, cpu_count=None):
        if _IN_WORKER or multiprocessing.current_process().name != "MainProcess":
            raise RuntimeError("nested process pools are forbidden")
        if not callable(worker) or (initializer is not None and not callable(initializer)):
            raise ValueError("worker and optional initializer must be callable")
        if type(initargs) is not tuple:
            raise ValueError("initargs must be a tuple")
        for value, name in ((workers, "workers"), (memory_budget_mb, "memory_budget_mb"),
                            (worker_memory_mb, "worker_memory_mb")):
            _positive_int(value, name)
        cpus = _positive_int(cpu_count, "cpu_count") if cpu_count is not None else (os.cpu_count() or 1)
        capacity = memory_budget_mb // worker_memory_mb
        if not capacity:
            raise ValueError("memory budget cannot accommodate one estimated worker")
        try:
            pickle.dumps(worker)
            if initializer is not None:
                pickle.dumps(initializer)
        except Exception as exc:
            raise ValueError("worker and initializer must be importable/picklable") from exc
        self.effective_workers = min(workers, cpus, capacity, 61 if sys.platform == "win32" else workers)
        self._worker = worker
        self._initializer = initializer
        self._initargs = initargs
        self._executor = None
        self._state = "NEW"
        self._lock = threading.Lock()
        self._pids = set()
        self._job_timings = []
        self._execute_timings = []
        self._peak_in_flight = 0

    @property
    def observed_pids(self):
        return tuple(sorted(self._pids))

    @property
    def timings(self):
        return {"jobs": [dict(item) for item in self._job_timings],
                "executions": [dict(item) for item in self._execute_timings],
                "peak_in_flight": self._peak_in_flight}

    def __enter__(self):
        if self._state != "NEW":
            raise RuntimeError("backend cannot be entered more than once")
        self._executor = ProcessPoolExecutor(
            max_workers=self.effective_workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_initialise,
            initargs=(self._worker, self._initializer, self._initargs))
        self._state = "OPEN"
        return self

    def close(self):
        executor, self._executor = self._executor, None
        if self._state != "FAILED":
            self._state = "CLOSED"
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def execute(self, jobs):
        if self._state != "OPEN":
            raise RuntimeError("execute requires an open, nonfailed backend context")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("concurrent execute calls are forbidden")
        started = time.perf_counter()
        pending = {}
        status = "FAILED"
        try:
            if type(jobs) is not list:
                raise ValueError("jobs must be a list")
            order = []
            seen = set()
            for job in jobs:
                if type(job) is not dict:
                    raise ValueError("each job must be an object")
                stage_id = job.get("stage_id")
                if (type(stage_id) is not str or not stage_id or len(stage_id) > 256
                        or stage_id.strip() != stage_id):
                    raise ValueError("stage_id must be a nonempty bounded string without surrounding whitespace")
                if stage_id in seen:
                    raise ValueError("duplicate stage_id: " + stage_id)
                seen.add(stage_id)
                order.append(stage_id)
                _json_value(job)
            next_index = 0
            records = {}
            while next_index < len(jobs) or pending:
                while next_index < len(jobs) and len(pending) < self.effective_workers:
                    future = self._executor.submit(_invoke, jobs[next_index])
                    pending[future] = next_index
                    next_index += 1
                    self._peak_in_flight = max(self._peak_in_flight, len(pending))
                finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in sorted(finished, key=pending.__getitem__):
                    index = pending.pop(future)
                    record, pid, elapsed = future.result()
                    _record(record)
                    records[order[index]] = record
                    self._pids.add(pid)
                    self._job_timings.append({"stage_id": order[index], "pid": pid, "wall_s": elapsed})
            status = "PASS"
            return {stage_id: records[stage_id] for stage_id in order}
        except BaseException:
            self._state = "FAILED"
            for future in pending:
                future.cancel()
            self.close()
            raise
        finally:
            self._execute_timings.append({"wall_s": time.perf_counter() - started,
                                          "status": status, "job_count": len(jobs) if type(jobs) is list else None})
            self._lock.release()
