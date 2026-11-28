"""Optional persistent reuse for known pure kernels, never inside their equations.

Inputs are detached before hashing and use. Identity includes typed input bytes,
resolved parameters, declared package provenance and the selected numerical runtime.
No parameter-only hash is treated as a complete scientific result identity.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import os
import errno
import time
import threading
import weakref
from collections import OrderedDict
from contextlib import contextmanager
from concurrent.futures import Future, CancelledError, TimeoutError as FutureTimeout

import numpy as np

from atlas_tectonics._validation import snapshot as array, frozen, input_shape, TectonicsError
from atlas_tectonics.integration.resources import elements, select_budget, MemoryLimitError
from atlas_tectonics.integration.resources import check_event
from atlas_tectonics.integration.resources import canonical_json as _json
from atlas_tectonics.codecs.storage import ArrayStore
from atlas_tectonics.thermal.thermal import half_space_temperature, cooling_work_bytes
from atlas_tectonics.mechanics.flexure import PeriodicFlexure
from atlas_tectonics.mechanics.finite_flexure import FiniteRegionFlexure
from atlas_tectonics.planet.parameters import ThermalParameters


def _digest(data):
    return hashlib.sha256(data).hexdigest()


# Fields that name code, not content: exact names only (a data digest under another name is content).
_CODE_FIELDS = frozenset(('execution', 'execution_id', 'source_execution_id', 'source_sha256', 'context', 'context_id',
                          'generator_source_sha256', 'pressure_source_sha256', 'helper_source_sha256'))


def content_record(value):
    """``value`` without the fields that name code, at any depth: what a content identifier hashes.

    A dropped field must hold a 64-character lower-case hex digest or None; a record (dict) under such a name is kept and
    read through (E-15); anything else that shares the name is refused, never dropped silently. The input is not altered; the record keeps its fields for the compares.
    """
    # Copies only the containers on a path to a dropped field; every untouched subtree is the input's own object.
    if type(value) is dict:
        out = None
        for i, (key, item) in enumerate(value.items()):
            if key in _CODE_FIELDS and type(item) is not dict:
                if item is not None and not (type(item) is str and len(item) == 64
                                             and all(c in '0123456789abcdef' for c in item)):
                    raise TectonicsError(f'{key} does not hold a code digest; content identity refused')
                if out is None:
                    out = {k: value[k] for k in list(value)[:i]}
                continue
            new = content_record(item)
            if out is None and new is not item:
                out = {k: value[k] for k in list(value)[:i]}
            if out is not None:
                out[key] = new
        return value if out is None else out
    if type(value) in (list, tuple):
        out = None
        for i, item in enumerate(value):
            new = content_record(item)
            if out is None and new is not item:
                out = list(value[:i])
            if out is not None:
                out.append(new)
        return value if out is None else type(value)(out)
    return value


def _file_hash(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise TectonicsError('runtime/source file unavailable or linked')
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


@lru_cache(maxsize=None)
def _loaded_binary(path):
    # Binary modules are assumed immutable for a process lifetime. Python source
    # and loaded instructions are re-examined per invocation. Paths are not IDs.
    # Unbounded: the keys are the fixed paths of _runtime_record (about 20, with
    # L4's Python DLL and _decimal). A
    # 16-entry bound was smaller than the scipy and numba sets, so every new
    # context of those backends re-read its binaries from disk (R7, s01-3).
    return _file_hash(path)


def _runtime_record(backend):
    if backend not in ("reference", "scipy", "numba"):
        raise TectonicsError("unknown execution backend")
    import scipy
    import shapely
    import decimal
    from atlas_tectonics._exact_runtime import selected
    versions = {"python": sys.version, "numpy": np.__version__, "machine": platform.machine(),
                "platform": platform.system(), "byteorder": sys.byteorder,
                "scipy_spatial": scipy.__version__, "shapely": shapely.__version__,
                "geos": shapely.geos_version_string, "decimal": decimal.__version__,
                "decimal_implementation": decimal.Decimal.__module__}
    if hasattr(decimal, "__libmpdec_version__"):
        versions["libmpdec"] = decimal.__libmpdec_version__
        versions["decimal_implementation"] = "_decimal"
    if backend in ("scipy", "numba"):
        versions["scipy"] = scipy.__version__
    if backend == "numba":
        import numba
        import llvmlite
        from llvmlite import binding
        versions.update(numba=numba.__version__, llvmlite=llvmlite.__version__,
                        llvm=list(binding.llvm_version_info), cpu_name=numba.config.CPU_NAME,
                        cpu_features=numba.config.CPU_FEATURES, disable_jit=numba.config.DISABLE_JIT,
                        fastmath=False, disk_jit_cache=False)
    versions.update(selected.runtime()['versions'])
    return {"versions": versions, "binaries": {}}


_lock = threading.RLock()
# Entered contexts are weakly held and tracked by nesting depth for B13 publication.
_entered = weakref.WeakKeyDictionary()


def publication_boundary():
    """Require live admitted contexts before publishing to another process (B13).

    Compact seal, promote and adopt call this. Strict checks the active contexts.
    A concurrently closed context is skipped only after successful close and hold
    release. A failed or in-progress close refuses publication.
    """
    with _lock:
        contexts = [context for context, depth in _entered.items() if depth]
    for context in contexts:
        # Never wait for another thread's close or check, and never hold the registry
        # lock while taking a context lock. A failed close is not proof of identity.
        if not context._close_lock.acquire(blocking=False):
            raise TectonicsError("execution context close or publication check is in progress")
        try:
            if context._closed:
                if not context._close_verified:
                    raise TectonicsError("execution context closed without successful verification")
                continue
            try:
                context.verify_boundary()
            except TectonicsError:
                if not (context._closed and context._close_verified):
                    raise
        finally:
            context._close_lock.release()


@lru_cache(maxsize=32)
def _execution_build(backend, runtime, version):
    return _digest(_json(dict(schema='atlas.kernel-execution.v7', backend=backend, runtime=json.loads(runtime), version=version)))


class ExecutionContext:
    """Frozen numerical execution binding with a context-owned lifetime."""
    def __init__(self, backend="reference"):
        self._open(backend)

    def _open(self, backend):
        self.backend = backend
        self._runtime = _runtime_record(backend)
        self._closed = self._close_verified = False
        self._close_lock = threading.RLock()
        from atlas_tectonics import __version__
        with _lock:
            self._identity = _execution_build(backend, _json(self._runtime), __version__)

    @property
    def provenance(self):
        return {'execution_identity': self.identity}

    @property
    def identity(self):
        return self._identity

    def verify(self):
        if self._closed:
            raise TectonicsError("execution context is closed")

    def verify_boundary(self):
        self.verify()

    def close(self):
        with self._close_lock:
            if not self._closed:
                self._closed = True
                self._close_verified = True

    def __enter__(self):
        try:
            self.verify()
        except BaseException as error:
            try:
                self.close()
            except BaseException as cleanup:
                error.add_note('Execution context cleanup also failed: ' + repr(cleanup))
            raise
        with _lock:
            _entered[self] = _entered.get(self, 0) + 1
        return self

    def __exit__(self, *args):
        try:
            self.close()
        finally:
            with _lock:
                depth = _entered.get(self, 0) - 1
                if depth > 0:
                    _entered[self] = depth
                else:
                    _entered.pop(self, None)


def execution_identity(backend="reference"):
    with ExecutionContext(backend) as context:
        return context.identity


def _array_identity(a):
    h = hashlib.sha256(_json({'dtype': a.dtype.str, 'shape': a.shape}))
    view = memoryview(a).cast('B')
    for offset in range(0, len(view), 1024 * 1024):
        h.update(view[offset:offset+1024*1024])
    return h.hexdigest()


@dataclass(frozen=True, slots=True, init=False)
class PreparedInput:
    """Compact immutable numerical bytes plus their precomputed typed digest.

    Each .array access creates private metadata. Never cache hashes by the identity
    of an arbitrary mutable NumPy object. Caller owns the prepared payload lifetime.
    """
    _payload: bytes
    shape: tuple[int, ...]
    digest: str
    nonnegative: bool

    def __init__(self, value, *, budget=None):
        shape = input_shape(value, "prepared input")
        with select_budget(budget).reserve(24 * elements(shape)):
            captured = array(value, "prepared input")
            owner = captured
            while type(owner) is np.ndarray:
                owner = owner.base
            # snapshot compacts slices and guarantees a bytes-backed C-order f64.
            if type(owner) is not bytes or len(owner) != captured.nbytes:
                raise TectonicsError("prepared input requires compact immutable backing")
            object.__setattr__(self, "_payload", owner)
            object.__setattr__(self, "shape", captured.shape)
            object.__setattr__(self, "digest", _array_identity(captured))
            object.__setattr__(self, "nonnegative", bool(np.all(captured >= 0)))

    @property
    def array(self):
        return np.frombuffer(self._payload, dtype=np.float64).reshape(self.shape)

    @property
    def nbytes(self):
        return len(self._payload)

    def __reduce__(self):
        return (type(self), (self.array,))


def _shape(value):
    return value.shape if type(value) is PreparedInput else input_shape(value)


def _capture(value, name, *, nonnegative=False):
    if type(value) is PreparedInput:
        if nonnegative and not value.nonnegative:
            raise TectonicsError(name+": nonnegative data required")
        return value.array, value.digest
    captured = array(value, name, nonnegative=nonnegative)
    return captured, None


def _invocation_record(operation, inputs, parameters, backend, *, context=None, digests=None):
    if context is None:
        with ExecutionContext(backend) as selected:
            return _invocation_record(operation, inputs, parameters, backend, context=selected, digests=digests)
    execution = context.identity
    # A diagnostic declaration can brand a run while its cache still needs the actual code identity.
    execution = getattr(context, '_actual_identity', execution)
    if context.backend != backend:
        raise TectonicsError("context/backend mismatch")
    return {"schema": "atlas.kernel-invocation.v2",
        "operation": operation, "backend": backend, "execution": execution,
        "inputs": {k: {"identity": (digests or {}).get(k) or _array_identity(v),
                       "shape": list(v.shape), "dtype": v.dtype.str}
                   for k,v in sorted(inputs.items())}, "parameters": parameters}


def invocation_identity(operation, inputs, parameters, *, backend="reference"):
    return _digest(_json(_invocation_record(operation, inputs, parameters, backend)))


@dataclass(frozen=True, slots=True)
class CachePolicy:
    """Execution policy only. auto admits expensive, likely reusable results.

    Timing thresholds affect reuse, never the numerical answer. 'always' is the
    explicit reproducibility/storage-test override; 'off' performs no store I/O.
    Defaults are conservative local policy, not universal performance predictions.
    """
    mode: str = "auto"
    min_result_bytes: int = 256 * 1024
    max_result_bytes: int = 64 * 1024 * 1024
    min_compute_seconds: float = 0.01
    expected_reuses: int = 3

    def __post_init__(self):
        if self.mode not in ("auto", "always", "off"):
            raise TectonicsError("cache mode must be auto/always/off")
        for name in ("min_result_bytes", "max_result_bytes", "expected_reuses"):
            value = getattr(self, name)
            if type(value) is not int or value < (1 if name != "min_result_bytes" else 0):
                raise TectonicsError("invalid cache admission bound")
        if self.min_result_bytes > self.max_result_bytes:
            raise TectonicsError("invalid cache size interval")
        if (type(self.min_compute_seconds) not in (int,float)
                or not math.isfinite(self.min_compute_seconds) or self.min_compute_seconds < 0):
            raise TectonicsError("invalid cache timing threshold")


_FLIGHT_RETRIES = 3


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError("caller cancelled; completed publications are not rolled back")


class _Flights:
    """Bounded process-local single-flight. Completed results are not a new cache."""
    def __init__(self, max_entries=32, max_waiters=128):
        self._lock = threading.Lock()
        self._entries = {}
        self._waiters = 0
        self.max_entries, self.max_waiters = max_entries, max_waiters

    def run(self, key, produce, *, cancel=None, timeout=30., validate=None):
        check_event(cancel, 'caller cancelled; completed publications are not rolled back')
        ident = threading.get_ident()
        deadline = time.monotonic()+timeout
        # An owner's own cancellation is not a waiter's: a waiter whose event is unset registers again (becoming
        # the owner, or waiting for a newer one) within its first deadline. Other failures are shared as before.
        # An owner resolves its future before it removes its entry, so a retry skips the future it already saw.
        seen = None
        for attempt in range(_FLIGHT_RETRIES+1):
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None and entry[1] is seen:
                    entry = None
                if entry is None:
                    if attempt and time.monotonic() >= deadline:
                        raise TimeoutError("waiting for identical cache request timed out")
                    if len(self._entries) >= self.max_entries and key not in self._entries:
                        raise MemoryLimitError("too many active cache computations")
                    future = Future()
                    self._entries[key] = (ident, future)
                    leader = True
                else:
                    owner, future = entry
                    if owner == ident:
                        raise TectonicsError("recursive same-key cache request")
                    if self._waiters >= self.max_waiters:
                        raise MemoryLimitError("too many waiting cache consumers")
                    self._waiters += 1
                    leader = False
            if leader:
                try:
                    result = produce()
                    # The future owns private array metadata; each consumer gets a view.
                    result = frozen(result)
                    future.set_result(result)
                except BaseException as exc:
                    future.set_exception(exc)
                    raise
                finally:
                    with self._lock:
                        if self._entries.get(key, (None, None))[1] is future:
                            del self._entries[key]
                break
            try:
                while True:
                    check_event(cancel, 'caller cancelled; completed publications are not rolled back')
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("waiting for identical cache request timed out")
                    try:
                        result = future.result(timeout=min(.05,remaining))
                        break
                    except FutureTimeout:
                        if future.done():
                            raise  # a producer's own TimeoutError is not a wait timeout
            except CancelledError as exc:
                check_event(cancel, 'caller cancelled; completed publications are not rolled back')               # this caller's own cancellation stays its own
                seen = future
                if attempt == _FLIGHT_RETRIES:
                    raise TectonicsError("identical cache computation was cancelled by its other callers "
                                         "%d times; nothing was cancelled here, retry" % (attempt+1)) from exc
                continue
            finally:
                with self._lock:
                    self._waiters -= 1
            break
        check_event(cancel, 'caller cancelled; completed publications are not rolled back')
        if not leader and validate is not None:
            validate()
        return result.view()


_FLIGHTS = _Flights()


@contextmanager
def _process_claim(store, key, cancel, timeout):
    """Crash-released local OS lock; 16 fixed stripes, no stale lease takeover.

    Same-process requests first use _FLIGHTS. Separate connections/processes
    recheck the database after taking this lock. Different keys can share a stripe:
    the holder records its key after the locked byte, and a request for another key
    proceeds without the claim instead of waiting behind unrelated work (its lookup
    and publication are still rechecked and idempotent). A request for the key the
    holder is computing waits, up to its timeout. While an unrelated key holds the
    stripe, requests for one key in several processes therefore each compute (a
    duplicate, never a wrong result). Yields whether the claim is held. The key is a
    cache identity, not scientific data; a stale or partly written record only
    decides whether to wait (never correctness).
    """
    from atlas_tectonics.codecs.storage import _path
    from atlas_tectonics.integration.resources import _sha256_pattern as _SHA
    import stat
    stripe = int(key[:8],16) % 16
    path = store.path.with_name(store.path.name+f".compute-{stripe:02d}.lock")
    _path(path)
    flags = os.O_RDWR | os.O_CREAT | getattr(os,"O_BINARY",0) | getattr(os,"O_NOFOLLOW",0)
    fd = os.open(path, flags, 0o600)
    acquired = False
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise TectonicsError("cache lock must be a local regular file")
        deadline = time.monotonic()+timeout
        if os.name == "nt":
            import msvcrt
            def take():
                # A rival may initialise and lock the byte after our size check.
                # Keep initialisation inside the same bounded contention loop.
                if os.fstat(fd).st_size == 0:
                    os.lseek(fd,0,os.SEEK_SET)
                    os.write(fd,b"0")
                os.lseek(fd,0,os.SEEK_SET)
                msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            def release():
                os.lseek(fd,0,os.SEEK_SET)
                msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
        elif os.name == "posix":
            import fcntl
            def take(): fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            def release(): fcntl.flock(fd,fcntl.LOCK_UN)
        else:
            raise TectonicsError("local process cache locks unsupported on this platform")
        def holder():
            # Bytes 1-64 lie outside the one locked byte, so they stay readable on Windows as well.
            os.lseek(fd,1,os.SEEK_SET)
            text = os.read(fd,64).decode("ascii","replace")
            return text if _SHA.fullmatch(text) else None
        while not acquired:
            check_event(cancel, 'caller cancelled; completed publications are not rolled back')
            try:
                take(); acquired = True
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK): raise
                other = holder()
                if other is not None and other != key:
                    break            # an unrelated computation holds this stripe: do not wait behind it
                if time.monotonic() >= deadline:
                    raise TimeoutError("cache compute lock timed out") from exc
                time.sleep(.01)
        if acquired:
            try:
                os.lseek(fd,1,os.SEEK_SET)
                os.write(fd,key.encode("ascii"))
            except OSError:
                pass                 # only a hint; a stale one decides at most whether another key waits
        yield acquired
    finally:
        if acquired: release()
        os.close(fd)


class ReuseController:
    """Finite per-store identity/cost state. No retained scientific result arrays."""
    def __init__(self, *, max_cost_records=128):
        if type(max_cost_records) is not int or max_cost_records < 1:
            raise TectonicsError("positive cost record bound required")
        self._lock = threading.RLock()
        self._contexts = {}
        self._costs = OrderedDict()
        self._profiles = OrderedDict()
        self._max_cost_records = max_cost_records
        self._counts = {name:0 for name in ("hits","misses","writes","bypasses","recomputes")}

    def context(self, backend):
        with self._lock:
            old = self._contexts.get(backend)
            if old is None:
                old = ExecutionContext(backend)
                self._contexts[backend] = old
            # A changed context fails; it is never silently re-pinned.
            return old

    def count(self, name):
        with self._lock: self._counts[name] += 1

    def cost(self, key, **updates):
        with self._lock:
            value = dict(self._costs.get(key, {}))
            if updates:
                value.update(updates)
                self._costs[key] = value
                self._costs.move_to_end(key)
                while len(self._costs) > self._max_cost_records:
                    self._costs.popitem(last=False)
            return value

    def profile(self, key, **updates):
        with self._lock:
            value = dict(self._profiles.get(key, {}))
            if updates:
                value.update(updates)
                self._profiles[key] = value
                self._profiles.move_to_end(key)
                while len(self._profiles)>self._max_cost_records:
                    self._profiles.popitem(last=False)
            return value

    def statistics(self):
        with self._lock:
            return dict(self._counts, cost_records=len(self._costs),
                        admission_profiles=len(self._profiles), contexts=len(self._contexts))


_CONTROLLERS = weakref.WeakKeyDictionary()
_CONTROLLER_LOCK = threading.Lock()


def _controller(store):
    with _CONTROLLER_LOCK:
        controller = _CONTROLLERS.get(store)
        if controller is None:
            controller = ReuseController()
            _CONTROLLERS[store] = controller
        return controller


def _evaluate(store, record, compute, shape, budget, *, context, controller,
              cache_policy, cancel=None, wait_timeout=30., admission_key=None):
    encoded = _json(record)
    key = _digest(encoded)
    nbytes = 8 * elements(shape)

    def check_result(result):
        if type(result) is not np.ndarray or result.shape != shape or result.dtype != np.dtype("float64"):
            raise TectonicsError("cached result contract mismatch")
        return result

    def restore(snapshot):
        arrays, winner = snapshot
        if set(arrays) != {"result"}:
            raise TectonicsError("cached result contract mismatch")
        if winner != record:
            raise TectonicsError("cached result contract mismatch")
        return check_result(arrays['result'])

    # One deadline covers this caller's waiting: for an identical in-process flight, then, if it becomes the
    # owner (also after another owner's cancellation), for the process claim.
    deadline = time.monotonic()+wait_timeout
    def produce():
        # Kernel/get workspace ends at return, but its result remains resident
        # through validation, compression and publication. Reserve that lifetime
        # before execution so a concurrent producer cannot consume its capacity.
        with budget.reserve(nbytes, category="pending-result"), \
                _process_claim(store,key,cancel,max(0.,deadline-time.monotonic())):
            check_event(cancel, 'caller cancelled; completed publications are not rolled back')
            costs = controller.cost(key)
            recompute = cache_policy.mode == "auto" and costs.get("restore",0) > costs.get("compute",float("inf"))
            start = time.perf_counter()
            snapshot = None if recompute else store._restore_snapshot(key, budget=budget, evidence=True)
            restore_time = time.perf_counter()-start
            if snapshot is not None:
                result = restore(snapshot)
                check_event(cancel, 'caller cancelled; completed publications are not rolled back')
                controller.count("hits")
                controller.cost(key,restore=restore_time)
                if admission_key is not None:
                    controller.profile(admission_key, restore=restore_time)
                return result
            controller.count("recomputes" if recompute else "misses")
            check_event(cancel, 'caller cancelled; completed publications are not rolled back')
            start = time.perf_counter(); result = check_result(compute())
            compute_time = time.perf_counter()-start
            check_event(cancel, 'caller cancelled; completed publications are not rolled back')
            controller.cost(key,compute=compute_time)
            if admission_key is not None:
                controller.profile(admission_key,compute=compute_time)
            admit = cache_policy.mode == "always" or (not recompute and
                compute_time >= cache_policy.min_compute_seconds and
                cache_policy.expected_reuses*(compute_time-costs.get("restore",0)) > costs.get("write",0))
            if admit:
                start = time.perf_counter()
                def publication_check():
                    check_event(cancel, 'caller cancelled; completed publications are not rolled back')
                store.put(key, {"result": result}, record, publication_check=publication_check,
                          cancel=cancel, budget=budget)
                write_time = time.perf_counter()-start
                controller.cost(key,write=write_time)
                if admission_key is not None:
                    controller.profile(admission_key,write=write_time)
                controller.count("writes")
            else:
                controller.count("bypasses")
            return result
    # Store path and key define the shared work. Different admission policies are
    # kept separate so an explicit always/off request does not inherit auto policy.
    flight_key = (str(store.path),key,cache_policy)
    return _FLIGHTS.run(flight_key,produce,cancel=cancel,timeout=wait_timeout)


def _policy(value):
    if value is None: return CachePolicy()
    if not isinstance(value,CachePolicy): raise TectonicsError("typed CachePolicy required")
    return value


def _prepare_reuse(store, cache_policy, nbytes, controller, operation, backend, context):
    policy = _policy(cache_policy)
    if store is None: return policy, None, False, None, context
    if not isinstance(store,ArrayStore): raise TectonicsError("store must be an ArrayStore")
    control = _controller(store) if controller is None else controller
    if not isinstance(control,ReuseController): raise TectonicsError("typed ReuseController required")
    admission_key = (operation,backend,nbytes.bit_length(),store.limits.chunk_bytes,
                     store.compression,policy)
    use = policy.mode == "always"
    if policy.mode == "auto" and policy.min_result_bytes <= nbytes <= policy.max_result_bytes:
        profile = control.profile(admission_key)
        # First observation computes directly. Avoid hashing/copying/locking a
        # cheap result merely to discover that persistence cannot repay its cost.
        # These timings choose execution only; they never authenticate data.
        compute = profile.get("compute",0.)
        restore = profile.get("restore",0.)
        use = (compute >= policy.min_compute_seconds and "compute" in profile and
               policy.expected_reuses*(compute-restore)>profile.get("write",0.))
    if use:
        context_backend = "reference" if backend == "fft" else backend
        context = control.context(context_backend) if context is None else context
        if not isinstance(context, ExecutionContext) or context.backend != context_backend:
            raise TectonicsError("context/backend mismatch")
    if not use:
        control.count("bypasses")
    return policy, control, use, admission_key, context


def _direct(compute, control, admission_key, policy, cancel, context=None, backend=None):
    check_event(cancel, 'caller cancelled; completed publications are not rolled back')
    if context is not None:
        if not isinstance(context,ExecutionContext) or context.backend != backend:
            raise TectonicsError("context/backend mismatch")
    start=time.perf_counter()
    result=compute()
    duration=time.perf_counter()-start
    if context is not None:
        pass
    check_event(cancel, 'caller cancelled; completed publications are not rolled back')
    if control is not None and policy.mode == "auto":
        control.profile(admission_key,compute=duration)
    return result


def _timeout(value):
    if type(value) not in (int,float) or not math.isfinite(value) or value <= 0:
        raise TectonicsError("positive finite wait_timeout required")
    return float(value)


def cached_temperature(depth_m, age_s, parameters: ThermalParameters, *,
                       store: ArrayStore | None = None, backend="scipy", budget=None,
                       context=None, controller=None, cache_policy=None, cancel=None,
                       wait_timeout=30.):
    """Optimised cooling; auto admission skips cheap results, never physics."""
    wait_timeout = _timeout(wait_timeout); check_event(cancel, 'caller cancelled; completed publications are not rolled back')
    # A store-bound wrapper joins its run envelope even when auto bypasses disk.
    # The caller may still supply an explicitly related per-call child budget.
    if budget is None and isinstance(store, ArrayStore):
        budget = store._budget
    ds,ts = _shape(depth_m),_shape(age_s)
    bs = np.broadcast_shapes(ds,ts)
    policy,control,use,admission_key, ctx = _prepare_reuse(store,cache_policy,8*elements(bs),controller,"cooling",backend, context)
    if not use:
        d = depth_m.array if type(depth_m) is PreparedInput else depth_m
        a = age_s.array if type(age_s) is PreparedInput else age_s
        return _direct(lambda:half_space_temperature(d,a,parameters,backend=backend,budget=budget),
                       control,admission_key,policy,cancel,ctx,backend)
    resource = select_budget(budget)
    with resource.reserve(16*(elements(ds)+elements(ts))):
        depth,dh = _capture(depth_m,"depth",nonnegative=True)
        age,ah = _capture(age_s,"age",nonnegative=True)
        if not isinstance(parameters,ThermalParameters):
            raise TectonicsError("explicit ThermalParameters required")
        with resource.reserve(cooling_work_bytes(ds,ts)):
            record = _invocation_record("half-space-temperature-v2",{"depth":depth,"age":age},
                asdict(parameters),backend,context=ctx,digests={"depth":dh,"age":ah})
        return _evaluate(store,record,lambda:half_space_temperature(depth,age,parameters,
            backend=backend,budget=resource),bs,resource,context=ctx,controller=control,
            cache_policy=policy,cancel=cancel,wait_timeout=wait_timeout,admission_key=admission_key)


def cached_plate_temperature(depth_m, age_s, parameters, *, cell_bottom_m=None,
                             store=None, budget=None, context=None, controller=None,
                             cache_policy=None, cancel=None, wait_timeout=30.):
    """Same verified auto-reuse policy as half-space cooling, including cell means."""
    from atlas_tectonics.plates.cooling import finite_plate_temperature, plate_cooling_work_bytes
    from atlas_tectonics.planet.parameters import PlateCoolingParameters
    if type(parameters) is not PlateCoolingParameters:
        raise TectonicsError('explicit PlateCoolingParameters required')
    wait_timeout = _timeout(wait_timeout); check_event(cancel, 'caller cancelled; completed publications are not rolled back')
    if budget is None and isinstance(store, ArrayStore):
        budget = store._budget
    raw = {'depth': depth_m, 'age': age_s}
    if cell_bottom_m is not None:
        raw['bottom'] = cell_bottom_m
    shapes = {key: _shape(value) for key, value in raw.items()}
    try:
        shape = np.broadcast_shapes(*shapes.values())
    except ValueError as exc:
        raise TectonicsError('plate cooling inputs cannot broadcast') from exc
    policy, control, use, key, ctx = _prepare_reuse(store, cache_policy, 8*elements(shape),
        controller, 'plate-cooling', 'scipy', context)
    def compute(values, resource):
        return finite_plate_temperature(values['depth'], values['age'], parameters,
            cell_bottom_m=values.get('bottom'), budget=resource, cancel=cancel)
    if not use:
        values = {k: v.array if type(v) is PreparedInput else v for k, v in raw.items()}
        return _direct(lambda: compute(values, budget), control, key, policy, cancel, ctx, 'scipy')
    resource = select_budget(budget)
    with resource.reserve(16*sum(elements(s) for s in shapes.values())):
        captured = {k: _capture(v, k, nonnegative=True) for k, v in raw.items()}
        values = {k: v[0] for k, v in captured.items()}
        with resource.reserve(plate_cooling_work_bytes(shapes['depth'], shapes['age'], shapes.get('bottom'))):
            record = _invocation_record('finite-plate-temperature-v1', values, asdict(parameters),
                'scipy', context=ctx, digests={k: v[1] for k, v in captured.items()})
        return _evaluate(store, record, lambda: compute(values, resource), shape, resource,
            context=ctx, controller=control, cache_policy=policy, cancel=cancel,
            wait_timeout=wait_timeout, admission_key=key)


def cached_plate_thermal_response(age_s, reference_age_s, plate, material, parameters, *,
                                  store=None, budget=None, context=None, controller=None,
                                  cache_policy=None, cancel=None, wait_timeout=30.):
    """Source-bound whole-column thermal load/support; auto skips cheap persistence."""
    from atlas_tectonics.thermal.thermal_support import plate_thermal_response, _plate_material
    _plate_material(plate, material, parameters)
    wait_timeout = _timeout(wait_timeout); check_event(cancel, 'caller cancelled; completed publications are not rolled back')
    if budget is None and isinstance(store, ArrayStore):
        budget = store._budget
    shapes = (_shape(age_s), _shape(reference_age_s))
    try:
        age_shape = np.broadcast_shapes(*shapes)
    except ValueError as exc:
        raise TectonicsError('cooling/reference ages cannot broadcast') from exc
    shape = age_shape+(3,)
    policy, control, use, key, ctx = _prepare_reuse(store, cache_policy, 8*elements(shape),
        controller, 'plate-thermal-support', 'scipy', context)
    def compute(age, reference, resource):
        return plate_thermal_response(age, reference, plate, material, parameters,
            budget=resource, cancel=cancel)
    if not use:
        age = age_s.array if type(age_s) is PreparedInput else age_s
        reference = reference_age_s.array if type(reference_age_s) is PreparedInput else reference_age_s
        return _direct(lambda: compute(age, reference, budget), control, key, policy, cancel, ctx, 'scipy')
    resource = select_budget(budget)
    with resource.reserve(16*sum(elements(s) for s in shapes)+128*elements(age_shape)+8192):
        age, ah = _capture(age_s, 'cooling age', nonnegative=True)
        reference, rh = _capture(reference_age_s, 'reference cooling age', nonnegative=True)
        record = _invocation_record('plate-thermal-support-v1', {'age': age, 'reference_age': reference},
            {'plate': asdict(plate), 'material': asdict(material), 'support': asdict(parameters),
             'layout': 'buoyancy-sheet-kg/m2,downward-Pa,total-reference-downward-m'},
            'scipy', context=ctx, digests={'age': ah, 'reference_age': rh})
        # BoussinesqMaterial carries a tuple validity interval; persisted JSON
        # represents it as a list. Preserve strict equality using canonical form.
        record = json.loads(_json(record))
        return _evaluate(store, record, lambda: compute(age, reference, resource), shape, resource,
            context=ctx, controller=control, cache_policy=policy, cancel=cancel,
            wait_timeout=wait_timeout, admission_key=key)


def cached_compaction_response(void_ratio, stress_pa, maximum_stress_pa, new_stress_pa, parameters, *,
        store=None, budget=None, context=None, controller=None, cache_policy=None, cancel=None, wait_timeout=30.):
    """History-aware constitutive reuse; cheap calculations auto-bypass persistence."""
    from atlas_tectonics.mechanics.compaction import CompactionParameters, compaction_response
    if type(parameters) is not CompactionParameters:
        raise TectonicsError('explicit CompactionParameters required')
    wait_timeout = _timeout(wait_timeout); check_event(cancel, 'caller cancelled; completed publications are not rolled back')
    if budget is None and isinstance(store, ArrayStore):
        budget = store._budget
    inputs = (void_ratio, stress_pa, maximum_stress_pa, new_stress_pa)
    shapes = tuple(_shape(a) for a in inputs)
    try:
        shape = np.broadcast_shapes(*shapes)+(2,)
    except ValueError as exc:
        raise TectonicsError('compaction fields cannot broadcast') from exc
    policy, control, use, key, ctx = _prepare_reuse(store, cache_policy, 8*elements(shape),
        controller, 'drained-compaction', 'reference', context)
    def compute(arrays, resource):
        return compaction_response(*arrays, parameters, budget=resource, cancel=cancel)
    if not use:
        arrays = tuple(a.array if type(a) is PreparedInput else a for a in inputs)
        return _direct(lambda: compute(arrays, budget), control, key, policy, cancel, ctx, 'reference')
    resource = select_budget(budget)
    with resource.reserve(16*sum(elements(s) for s in shapes)+64*elements(shape)+8192):
        names = ('void_ratio', 'stress_pa', 'maximum_stress_pa', 'new_stress_pa')
        captures = [_capture(a, name, nonnegative=True) for name, a in zip(names, inputs)]
        arrays = dict(zip(names, (a for a, _ in captures)))
        digests = dict(zip(names, (h for _, h in captures)))
        record = _invocation_record('drained-compaction-v1', arrays,
            {'parameters': asdict(parameters), 'layout': 'void-ratio,maximum-effective-stress-Pa'},
            'reference', context=ctx, digests=digests)
        return _evaluate(store, record, lambda: compute(tuple(arrays.values()), resource), shape, resource,
            context=ctx, controller=control, cache_policy=policy, cancel=cancel,
            wait_timeout=wait_timeout, admission_key=key)


def cached_column_load_change(reference, current, gravity_m_s2, *, store=None,
        budget=None, context=None, controller=None, cache_policy=None, cancel=None,
        batch_columns=32768, wait_timeout=30.):
    """Reuse immutable source-bound load states through the existing cache policy.

    State identities cover captured bytes, catalogue, fixed geometry, source and
    epoch. No duplicate captures/hashes of those immutable arrays are needed.
    Execution/source/runtime identity is still verified by the normal machinery.
    Cheap loads default to direct computation, not mandatory persistence.
    """
    from atlas_tectonics.mechanics.column_loads import column_load_change, _compatible
    g = _compatible(reference, current, gravity_m_s2, batch_columns)
    wait_timeout = _timeout(wait_timeout); check_event(cancel, 'caller cancelled; completed publications are not rolled back')
    if budget is None and isinstance(store, ArrayStore):
        budget = store._budget
    shape = (len(reference.support.column_ids), 4)
    policy, control, use, key, ctx = _prepare_reuse(store, cache_policy, 8*elements(shape),
        controller, 'fixed-column-loads', 'reference', context)
    def compute():
        return column_load_change(reference, current, g, budget=budget,
                                  cancel=cancel, batch_columns=batch_columns)
    if not use:
        return _direct(compute, control, key, policy, cancel, ctx, 'reference')
    resource = select_budget(budget)
    record = _invocation_record('fixed-column-loads-v1', {},
        {'reference_state': reference.state_id, 'current_state': current.state_id,
         'gravity_m_s2': g, 'support': reference.support.support_id,
         'layout': 'inventory-kg/m2,replacement-kg/m2,thermal-buoyancy-kg/m2,total-downward-Pa'},
        'reference', context=ctx)
    return _evaluate(store, record, compute, shape, resource, context=ctx,
        controller=control, cache_policy=policy, cancel=cancel, wait_timeout=wait_timeout,
        admission_key=key)


def cached_flexure(operator: PeriodicFlexure, load_pa, *, store: ArrayStore | None = None,
                   budget=None, context=None, controller=None, cache_policy=None,
                   cancel=None, wait_timeout=30.):
    if not isinstance(operator,PeriodicFlexure): raise TectonicsError("explicit PeriodicFlexure required")
    wait_timeout = _timeout(wait_timeout); check_event(cancel, 'caller cancelled; completed publications are not rolled back')
    if budget is None and isinstance(store, ArrayStore):
        budget = store._budget
    shape = _shape(load_pa)
    if not shape or shape[-1] != operator.grid.cells:
        raise TectonicsError("load final dimension must equal grid cells")
    policy,control,use,admission_key, ctx = _prepare_reuse(store,cache_policy,8*elements(shape),controller,"flexure","fft", context)
    if not use:
        load = load_pa.array if type(load_pa) is PreparedInput else load_pa
        return _direct(lambda:operator.solve(load,budget=budget),control,admission_key,policy,cancel,ctx,"reference")
    resource = select_budget(budget)
    with resource.reserve(16*elements(shape)):
        load,digest = _capture(load_pa,"load")
        with resource.reserve(operator.work_bytes(shape)):
            record = _invocation_record("periodic-flexure-v2",{"load":load},
                {"grid":asdict(operator.grid),"material":asdict(operator.parameters),
                 "operator_id":operator.operator_id},"reference",context=ctx,digests={"load":digest})
        return _evaluate(store,record,lambda:operator.solve(load,budget=resource),shape,resource,
            context=ctx,controller=control,cache_policy=policy,cancel=cancel,wait_timeout=wait_timeout,admission_key=admission_key)


def cached_finite_flexure(operator, load_pa, *, store=None, budget=None, context=None,
                         controller=None, cache_policy=None, cancel=None, wait_timeout=30.):
    """Verified reuse of the distinct continuous regional operator and derivatives."""
    if type(operator) is not FiniteRegionFlexure:
        raise TectonicsError('explicit FiniteRegionFlexure required')
    wait_timeout = _timeout(wait_timeout); check_event(cancel, 'caller cancelled; completed publications are not rolled back')
    if budget is None and isinstance(store, ArrayStore):
        budget = store._budget
    shape = _shape(load_pa)
    operator.work_bytes(shape)
    output_shape = (2*operator.grid.cells+1, 4)
    policy, control, use, key, ctx = _prepare_reuse(store, cache_policy, 8*elements(output_shape),
        controller, 'finite-region-flexure', 'fft', context)
    if not use:
        load = load_pa.array if type(load_pa) is PreparedInput else load_pa
        return _direct(lambda: operator.solve(load,budget=budget), control,key,policy,cancel,ctx,'reference')
    resource = select_budget(budget)
    with resource.reserve(16*elements(shape)):
        load, digest = _capture(load_pa,'regional_load')
        record = _invocation_record('continuous-regional-flexure-v1',{'regional_load':load},
            {'grid':asdict(operator.grid),'material':asdict(operator.parameters),
             'boundary':asdict(operator.boundary),'operator_id':operator.operator_id},
            'reference',context=ctx,digests={'regional_load':digest})
        return _evaluate(store,record,lambda:operator.solve(load,budget=resource),output_shape,resource,
            context=ctx,controller=control,cache_policy=policy,cancel=cancel,
            wait_timeout=wait_timeout,admission_key=key)


def cached_variable_flexure(operator, load_pa, *, store=None, budget=None, context=None,
                           controller=None, cache_policy=None, cancel=None, wait_timeout=30.):
    """Source-bound adaptive Hermite response; SciPy/LAPACK identity is required."""
    from atlas_tectonics.mechanics.variable_flexure import VariableRigidityFlexure
    if type(operator) is not VariableRigidityFlexure or operator._closed:
        raise TectonicsError('live explicit variable-rigidity operator required')
    wait_timeout=_timeout(wait_timeout);check_event(cancel, 'caller cancelled; completed publications are not rolled back')
    if budget is None and isinstance(store,ArrayStore): budget=store._budget
    shape=_shape(load_pa);operator.work_bytes(shape)
    output_shape=(operator.grid.cells,5,4)
    policy,control,use,key, ctx=_prepare_reuse(store,cache_policy,8*elements(output_shape),controller,
                                         'variable-rigidity-flexure','scipy', context)
    if not use:
        load=load_pa.array if type(load_pa) is PreparedInput else load_pa
        return _direct(lambda:operator.solve(load,budget=budget,cancel=cancel),control,key,policy,cancel,ctx,'scipy')
    resource=select_budget(budget)
    with resource.reserve(16*elements(shape)):
        load,digest=_capture(load_pa,'regional_load')
        record=_invocation_record('hermite-variable-rigidity-refined-v1',{'regional_load':load},
            {'operator_id':operator.operator_id,'profile_id':operator.profile.profile_id,
             'accuracy':asdict(operator.accuracy)},'scipy',context=ctx,digests={'regional_load':digest})
        return _evaluate(store,record,lambda:operator.solve(load,budget=resource,cancel=cancel),output_shape,resource,
            context=ctx,controller=control,cache_policy=policy,cancel=cancel,
            wait_timeout=wait_timeout,admission_key=key)


def cached_regional_transport(thickness_m, face_velocity_m_s, grid, duration_s, *,
        left, right, scheme="muscl", backend="numba", store=None, budget=None,
        context=None, controller=None, cache_policy=None, cancel=None, wait_timeout=30.):
    """W02 persistence through existing admission/claims/store, never a new cache.

    Cheap evolving steps normally bypass persistence. On admission, capture the
    same immutable inputs for identity and execution; key the external states,
    frame/grid, interval, scheme and compiler as well as interior data. The packed
    result is a versioned transfer format, not a lower-precision representation.
    """
    from atlas_tectonics.regional.regional import (advect_regional, regional_work_bytes, _validate_definition,
                           pack_regional_result, unpack_regional_result)
    from atlas_tectonics._validation import scalar
    _validate_definition(grid,left,right,scheme,backend)
    dt=scalar(duration_s,"duration_s",nonnegative=True)
    wait_timeout=_timeout(wait_timeout); check_event(cancel, 'caller cancelled; completed publications are not rolled back')
    if budget is None and isinstance(store,ArrayStore): budget=store._budget
    shapes=(_shape(thickness_m),_shape(face_velocity_m_s))
    if shapes != ((grid.cells,),(grid.cells+1,)):
        raise TectonicsError("expected N thicknesses and N+1 face velocities")
    size=2*grid.cells+9
    policy,control,use,admission_key, ctx=_prepare_reuse(store,cache_policy,8*size,controller,
                                                  "regional-"+scheme,backend, context)
    if not use:
        h=thickness_m.array if type(thickness_m) is PreparedInput else thickness_m
        u=face_velocity_m_s.array if type(face_velocity_m_s) is PreparedInput else face_velocity_m_s
        return _direct(lambda:advect_regional(h,u,grid,dt,left=left,right=right,scheme=scheme,
            backend=backend,budget=budget,cancel=cancel),control,admission_key,policy,cancel,ctx,backend)
    resource=select_budget(budget)
    with resource.reserve(16*(2*grid.cells+1),category="regional-cache-input"):
        h,hd=_capture(thickness_m,"thickness",nonnegative=True)
        u,ud=_capture(face_velocity_m_s,"face velocities")
        with resource.reserve(regional_work_bytes(grid.cells,scheme=scheme)):
            record=_invocation_record("regional-transport-packed-v1",{"thickness":h,"velocity":u},
                {"grid":asdict(grid),"duration_s":dt,"left":asdict(left),"right":asdict(right),
                 "scheme":scheme,"flux":"interval-mean-m2/s","inventory":"volume-per-width-m2",
                 "layout":"H[N];F[N+1];before,after,in,out,residual,C,left-in,right-in"},
                backend,context=ctx,digests={"thickness":hd,"velocity":ud})
        def compute():
            # Candidate fields survive while the transfer payload is packed.
            with resource.reserve(32*size,category="regional-result-packing"):
                return pack_regional_result(advect_regional(h,u,grid,dt,left=left,right=right,
                    scheme=scheme,backend=backend,budget=resource,cancel=cancel))
        packed=_evaluate(store,record,compute,(size,),resource,context=ctx,controller=control,
            cache_policy=policy,cancel=cancel,wait_timeout=wait_timeout,admission_key=admission_key)
        return unpack_regional_result(packed,grid.cells,scheme,backend)


def cached_material_transport(state, face_velocity_m_s, duration_s, *, left, right,
        scheme='muscl', backend='numba', store=None, budget=None, context=None,
        controller=None, cache_policy=None, cancel=None, wait_timeout=30.):
    """Cohort data and histories participate in the existing result-cache contract.

    An immutable state's payload digest can be reused; state_id also binds cohort
    formation, origin, epoch and lineage. A changed composition is not the same
    invocation even when total thickness is identical. Store/controller admission
    may change reuse behaviour only, never downgrade the selected accuracy scheme.
    """
    from atlas_tectonics.materials.materials import (advect_materials, material_work_bytes, _definition,
        _end_time, _exterior, _hash_array, pack_material_result, unpack_material_result)
    from atlas_tectonics._validation import scalar
    _definition(state,left,right,scheme,backend)
    dt=scalar(duration_s,'duration',nonnegative=True);_end_time(state,dt)
    wait_timeout=_timeout(wait_timeout);check_event(cancel, 'caller cancelled; completed publications are not rolled back')
    if budget is None and isinstance(store,ArrayStore):budget=store._budget
    n=state.grid.cells;c=len(state.cohorts)
    if _shape(face_velocity_m_s)!=(n+1,):raise TectonicsError('N+1 velocities required')
    shape=(c,2*n+9);size=elements(shape)
    policy,control,use,admission_key, ctx=_prepare_reuse(store,cache_policy,8*size,controller,
                                                   'material-'+scheme,backend, context)
    if not use:
        velocity=face_velocity_m_s.array if type(face_velocity_m_s) is PreparedInput else face_velocity_m_s
        return _direct(lambda:advect_materials(state,velocity,dt,left=left,right=right,
            scheme=scheme,backend=backend,budget=budget,cancel=cancel),control,admission_key,
            policy,cancel,ctx,backend)
    resource=select_budget(budget)
    with resource.reserve(16*(n+1),category='material-cache-input'):
        u,ud=_capture(face_velocity_m_s,'face velocities')
        _exterior(state,u,left,True);_exterior(state,u,right,False)
        record=_invocation_record('material-transport-packed-v1',{'velocity':u},
            {'state_id':state.state_id,'state':state.descriptor(),'duration_s':dt,
             'left':asdict(left),'right':asdict(right),'scheme':scheme,
             'layout':'cohorts x [H[N],F[N+1],eight regional metrics]'},
            backend,context=ctx,digests={'velocity':ud})
        # JSON persistence represents tuples as lists. Compare the same canonical
        # metadata representation on hits; do not relax the metadata equality check.
        record=json.loads(_json(record))
        def compute():
            with resource.reserve(32*size,category='material-result-packing'):
                return pack_material_result(advect_materials(state,u,dt,left=left,right=right,
                    scheme=scheme,backend=backend,budget=resource,cancel=cancel))
        packed=_evaluate(store,record,compute,shape,resource,context=ctx,controller=control,
            cache_policy=policy,cancel=cancel,wait_timeout=wait_timeout,admission_key=admission_key)
        # Captured velocity has the same typed identity as direct execution.
        return unpack_material_result(packed,state,dt,left,right,scheme,backend,
                                      _hash_array(u),budget=resource)


def cached_material_remap(state,target,*,plan=None,scheme='linear',backend='numba',
        store=None,budget=None,context=None,controller=None,cache_policy=None,cancel=None,wait_timeout=30.):
    """Reuse remap results through existing policy; mesh-only setup is separately reusable."""
    from atlas_tectonics.planet.remapping import remap_materials,RemapPlan,restore_remap_result,_mesh_state
    from atlas_tectonics.planet.mesh import ColumnGrid1D
    _mesh_state(state)
    if type(target) is not ColumnGrid1D or scheme not in ('linear','constant') or backend not in ('numba','reference'):
        raise TectonicsError('invalid remap definition')
    if budget is None and isinstance(store,ArrayStore):budget=store._budget
    shape=(len(state.cohorts),target.cells);size=elements(shape)
    policy,control,use,key, ctx=_prepare_reuse(store,cache_policy,8*size,controller,'material-remap-'+scheme,backend, context)
    if not use:return _direct(lambda:remap_materials(state,target,plan=plan,scheme=scheme,backend=backend,budget=budget,cancel=cancel),
                              control,key,policy,cancel,ctx,backend)
    resource=select_budget(budget)
    with resource.reserve(48*size+128*(state.grid.cells+target.cells)+8192,category='remap-cache'):
        op=RemapPlan(state.grid,target,backend=backend,budget=resource) if plan is None else plan
        if type(op) is not RemapPlan or op.source!=state.grid or op.target!=target:raise TectonicsError('stale remap plan')
        record=_invocation_record('material-remap-v2',{}, {'state_id':state.state_id,'state':state.descriptor(),
                       'target':target.descriptor(),'plan_id':op.plan_id,'scheme':scheme},backend,context=ctx)
        record=json.loads(_json(record))
        packed=_evaluate(store,record,lambda:remap_materials(state,target,plan=op,scheme=scheme,backend=backend,
                         budget=resource,cancel=cancel).thickness_m,shape,resource,context=ctx,controller=control,
                         cache_policy=policy,cancel=cancel,wait_timeout=_timeout(wait_timeout),admission_key=key)
        return restore_remap_result(state,target,packed,plan=op,scheme=scheme,backend=backend,budget=resource)


def cached_ale_transport(state,face_velocity_m_s,mesh_velocity_m_s,duration_s,*,left,right,
        scheme='muscl',backend='numba',event_times_s=(),store=None,budget=None,context=None,
        controller=None,cache_policy=None,cancel=None,wait_timeout=30.):
    """Relative motion, geometry, cohort history, boundaries and time all bind reuse."""
    from atlas_tectonics.planet.remapping import advect_ale,restore_ale_result,_mesh_state,_boundary_values
    from atlas_tectonics.materials.materials import pack_material_result,_end_time
    from atlas_tectonics._validation import scalar
    _mesh_state(state);dt=scalar(duration_s,'duration',nonnegative=True);end=_end_time(state,dt)
    if scheme not in ('muscl','upwind') or backend not in ('numba','reference'):raise TectonicsError('invalid ALE method')
    for t in event_times_s:
        if state.time_s<scalar(t,'event time')<end:raise TectonicsError('interval crosses known event')
    n=state.grid.cells;c=len(state.cohorts)
    if _shape(face_velocity_m_s)!=(n+1,) or _shape(mesh_velocity_m_s)!=(n+1,):raise TectonicsError('N+1 physical/mesh velocities required')
    if budget is None and isinstance(store,ArrayStore):budget=store._budget
    shape=(c,2*n+9);size=elements(shape)
    policy,control,use,key, ctx=_prepare_reuse(store,cache_policy,8*size,controller,'ale-'+scheme,backend, context)
    if not use:
        u=face_velocity_m_s.array if type(face_velocity_m_s) is PreparedInput else face_velocity_m_s
        w=mesh_velocity_m_s.array if type(mesh_velocity_m_s) is PreparedInput else mesh_velocity_m_s
        return _direct(lambda:advect_ale(state,u,w,dt,left=left,right=right,scheme=scheme,backend=backend,
             event_times_s=event_times_s,budget=budget,cancel=cancel),control,key,policy,cancel,ctx,backend)
    resource=select_budget(budget)
    with resource.reserve(48*size+128*n+8192,category='ale-cache'):
        u,ud=_capture(face_velocity_m_s,'physical velocity');w,wd=_capture(mesh_velocity_m_s,'mesh velocity')
        _boundary_values(state,u-w,left,True);_boundary_values(state,u-w,right,False)
        record=_invocation_record('ale-packed-v2',{'u':u,'w':w},{'state_id':state.state_id,
             'state':state.descriptor(),'duration_s':dt,'left':asdict(left),'right':asdict(right),'scheme':scheme},
             backend,context=ctx,digests={'u':ud,'w':wd})
        record=json.loads(_json(record))
        packed=_evaluate(store,record,lambda:pack_material_result(advect_ale(state,u,w,dt,left=left,right=right,
               scheme=scheme,backend=backend,budget=resource,cancel=cancel)),shape,resource,context=ctx,
               controller=control,cache_policy=policy,cancel=cancel,wait_timeout=_timeout(wait_timeout),admission_key=key)
        return restore_ale_result(state,u,w,dt,left,right,scheme,backend,packed,budget=resource)
