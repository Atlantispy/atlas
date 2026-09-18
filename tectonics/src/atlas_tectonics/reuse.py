"""Optional persistent reuse for known pure kernels, never inside their equations.

Inputs are detached before hashing and use. Identity includes typed input bytes,
resolved parameters, current package source, loaded Python instructions and the
selected runtime. This is provenance/invalidation, not a hostile-runtime sandbox.
No parameter-only hash is treated as a complete scientific result identity.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, is_dataclass
from functools import lru_cache
import hashlib
import inspect
import json
import marshal
import math
from pathlib import Path
import platform
import sys
import types
import importlib
import os
import errno
import time
import threading
import weakref
from collections import OrderedDict
from contextlib import contextmanager
from concurrent.futures import Future, CancelledError, TimeoutError as FutureTimeout

import numpy as np

from ._validation import snapshot as array, frozen, input_shape, TectonicsError
from .resources import elements, select_budget, MemoryLimitError
from .storage import ArrayStore
from .thermal import half_space_temperature, cooling_work_bytes
from .flexure import PeriodicFlexure
from .parameters import ThermalParameters


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _file_hash(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise TectonicsError('runtime/source file unavailable or linked')
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


@lru_cache(maxsize=16)
def _loaded_binary(path):
    # Binary modules are assumed immutable for a process lifetime. Python source
    # and loaded instructions are re-examined per invocation. Paths are not IDs.
    return _file_hash(path)


def _interpreter_binary():
    """Identify the executable target, not a virtual environment's launch link.

    Python virtual environments may legitimately link their interpreter. Resolve
    only this interpreter path; source, data and extension-module paths still
    pass through the unchanged strict hashing rules. The resolved binary bytes,
    not the installation path, enter the runtime identity. Loaded binaries retain
    the existing process-lifetime immutability assumption; this is not protection
    against a hostile process replacing its executable while it runs.
    """
    if not isinstance(sys.executable, str) or not sys.executable:
        raise TectonicsError('Python interpreter path is unavailable')
    try:
        target = Path(sys.executable).resolve(strict=True)
        if not target.is_file():
            raise TectonicsError('Python interpreter target is not a regular file')
    except (OSError, RuntimeError) as exc:
        raise TectonicsError('Python interpreter target cannot be resolved') from exc
    return str(target)


def _normal_code(code):
    return code.replace(co_filename='<atlas>', co_consts=tuple(
        _normal_code(c) if isinstance(c, types.CodeType) else c for c in code.co_consts))


# Fixed kernel dependency set: unrelated later imports cannot change a cache key.
# New package source files still participate in source membership verification.
_IDENTITY_MODULES = ("_validation", "resources", "parameters", "kinematics",
                     "thermal", "flexure", "transport", "storage", "reuse", "regional", "materials", "mesh", "remapping", "topology", "markers", "coordinates", "timebase", "geometry", "spherical_geometry", "geometry_index", "boundaries", "spherical_atlas", "planetary_generation", "geological_records", "geological_case", "material_library", "plate_reference", "plate_layout", "geological_domain", "precursor", "precursor_sampling", "_spherical_candidates", "precursor_execution", "execution")


def _source_bytes():
    root = Path(__file__).parent
    out = {}
    for p in sorted(root.rglob("*.py")):
        if p.is_symlink() or not p.is_file():
            raise TectonicsError("runtime/source file unavailable or linked")
        remaining = 2*1024**2 - sum(map(len,out.values()))
        with p.open("rb") as stream:
            raw = stream.read(remaining+1)
        if len(out) >= 128 or len(raw) > remaining:
            raise TectonicsError("execution source inventory exceeds context budget")
        out[p.relative_to(root).as_posix()] = raw
    return out


def _constant(value):
    if value is None or type(value) in (bool, int, float, str):
        return value
    if type(value) in (tuple, list):
        return [_constant(x) for x in value]
    if type(value) is dict:
        return {str(k): _constant(v) for k,v in sorted(value.items())}
    if is_dataclass(value) and not isinstance(value, type):
        return {"type": type(value).__qualname__, "values": _constant(asdict(value))}
    # Runtime objects (locks/budgets/modules) are not arbitrary serialised graphs.
    return {"type": type(value).__module__+"."+type(value).__qualname__}


def _callable_inventory(backend="reference"):
    signatures, tokens, constants = {}, [], {}
    modules = _IDENTITY_MODULES + (("_regional_native", "_transport_native", "_materials_native", "_mesh_native", "_geometry_native") if backend == "numba" else ())
    for name in modules:
        module = importlib.import_module("atlas_tectonics."+name)
        for label, obj in sorted(vars(module).items()):
            # These are process-wide resource leases, not scientific constants.
            # Their changes are guarded by the executor, not source invalidation.
            transient = name == 'execution' and label in (
                '_LIMIT_USERS', '_LIMIT_VALUE', '_LIMIT_OWNER', '_LIMIT_HANDLE',
                '_POOL_SLOTS', '_PROCESS_LIMIT_HANDLE')
            if not transient and label.isupper() and (type(obj) in (str, int, float, bool, tuple)
                                   or (is_dataclass(obj) and not isinstance(obj, type))):
                constants[module.__name__+"."+label] = _constant(obj)
            members = [(label, obj)]
            if isinstance(obj, type) and obj.__module__ == module.__name__:
                members = []
                for member, method in sorted(vars(obj).items()):
                    if isinstance(method, (staticmethod, classmethod)):
                        method = method.__func__
                    elif isinstance(method, property):
                        method = method.fget
                    members.append((label+"."+member, method))
            for label2, fn in members:
                if hasattr(fn, "py_func") and inspect.isfunction(fn.py_func):
                    # Inspect the Python definition AND selected JIT options; a
                    # dispatcher object's address alone is not code provenance.
                    key = module.__name__+"."+label2
                    origin = fn.py_func
                    defaults = (_constant(origin.__defaults__), _constant(origin.__kwdefaults__),
                                _constant(fn.targetoptions))
                    tokens.append((key, fn, origin.__code__, defaults))
                    signatures[key] = (origin.__code__, defaults)
                elif inspect.isfunction(fn):
                    key = module.__name__+"."+label2
                    defaults = (_constant(fn.__defaults__), _constant(fn.__kwdefaults__))
                    # Keep actual objects alive; identity checks cannot suffer id reuse.
                    tokens.append((key, fn, fn.__code__, defaults))
                    signatures[key] = (fn.__code__, defaults)
                elif callable(fn) and not isinstance(fn, type):
                    # Ufunc/builtin/callable aliases are runtime identity guards.
                    key = module.__name__+"."+label2
                    tokens.append((key, fn, None, b""))
    return signatures, tuple(tokens), _json(constants)


def _runtime_record(backend):
    if backend not in ("reference", "scipy", "numba"):
        raise TectonicsError("unknown execution backend")
    import numpy._core._multiarray_umath as core
    import numpy.fft._pocketfft_umath as fft
    interpreter = _interpreter_binary()
    binaries = {"python": _loaded_binary(interpreter),
                "numpy_core": _loaded_binary(core.__file__),
                "numpy_fft": _loaded_binary(fft.__file__),
                "math": _loaded_binary(getattr(math, "__file__", interpreter))}
    versions = {"python": sys.version, "numpy": np.__version__, "machine": platform.machine(),
                "platform": platform.system(), "byteorder": sys.byteorder}
    if backend == "scipy":
        try:
            import scipy
            import scipy.special._ufuncs as sf
        except ImportError as exc:
            raise TectonicsError("requested scipy runtime unavailable") from exc
        versions["scipy"] = scipy.__version__
        binaries["scipy_special"] = _loaded_binary(sf.__file__)
    if backend == "numba":
        import numba, llvmlite
        import numba._helperlib as helper
        versions.update(numba=numba.__version__, llvmlite=llvmlite.__version__,
                        cpu_name=numba.config.CPU_NAME, cpu_features=numba.config.CPU_FEATURES,
                        disable_jit=numba.config.DISABLE_JIT, fastmath=False, disk_jit_cache=False)
        binaries["numba_helper"] = _loaded_binary(helper.__file__)
        candidates = [p for p in (Path(llvmlite.__file__).parent / "binding").glob("*llvmlite*")
                      if p.suffix in (".so", ".dll", ".dylib")]
        if len(candidates) != 1:
            raise TectonicsError("cannot identify the selected LLVM native library")
        binaries["llvmlite"] = _loaded_binary(candidates[0])
    # Global atlas broad-phase queries use SciPy's native spatial tree. Record
    # that executable dependency even when the requested physical kernel is the
    # reference backend; ordinary reference calls without a context stay minimal.
    import scipy
    import scipy.spatial._ckdtree as spatial_tree
    versions['scipy_spatial'] = scipy.__version__
    binaries['scipy_ckdtree'] = _loaded_binary(spatial_tree.__file__)
    # Stage 3C's native convex hull also participates in execution identity.
    import scipy.spatial._qhull as qhull
    binaries['scipy_qhull'] = _loaded_binary(qhull.__file__)
    # The reference-conditioned layout uses these native sparse-graph routines.
    # Identify selected implementations; this is not a recursively sealed runtime.
    import scipy.sparse.csgraph._shortest_path as shortest_path
    import scipy.sparse.csgraph._traversal as traversal
    import scipy.sparse._sparsetools as sparse_tools
    for label, module in (('shortest_path',shortest_path),('traversal',traversal),('sparse_tools',sparse_tools)):
        binaries['scipy_'+label] = _loaded_binary(module.__file__)
    import shapely
    import shapely.lib as geometry_lib
    versions.update(shapely=shapely.__version__, geos=shapely.geos_version_string)
    binaries['shapely_extension'] = _loaded_binary(geometry_lib.__file__)
    # Official wheels place the linked GEOS libraries in a sibling .libs folder.
    # Non-wheel/system installations need an explicitly supplied deployment audit;
    # never label a version string alone a sealed native dependency closure.
    geos_dir = Path(shapely.__file__).parent.parent / 'shapely.libs'
    geos_files = sorted(p for p in geos_dir.glob('*') if p.is_file() and 'geos' in p.name.lower())
    versions['geos_binary_scope'] = 'wheel-libraries' if geos_files else 'extension-only; external GEOS unsealed'
    for p in geos_files:
        binaries['geos:'+p.name] = _loaded_binary(p)
    return {"versions": versions, "binaries": binaries}


class ExecutionContext:
    """Reusable identity preparation, not a promise that live files cannot change.

    Every use compares the complete current source bytes and callable/default
    inventory with the captured state. Only repeated SHA/marshal/normalisation is
    removed. Timestamps are never used as evidence. Runtime binaries retain the
    pre-existing process-lifetime immutability assumption. This is not a sandbox.
    """
    def __init__(self, backend="reference"):
        self.backend = backend
        self._runtime = _runtime_record(backend)  # resolve lazy runtime imports first
        signatures, self._tokens, self._constants = _callable_inventory(backend)
        self._sources = _source_bytes()
        loaded = {k: {"code": _digest(marshal.dumps(_normal_code(code))),
                      "defaults": _digest(_json(defaults))}
                  for k, (code, defaults) in signatures.items()}
        self._identity = _digest(_json({"schema": "atlas.kernel-execution.v2",
            "backend": backend, "sources": {k:_digest(v) for k,v in self._sources.items()},
            "loaded_code": loaded, "constants": _digest(self._constants),
            "runtime": self._runtime}))
        self._closed = False
        self.verify()

    @property
    def identity(self):
        self.verify()
        return self._identity

    def verify(self):
        if self._closed:
            raise TectonicsError("execution context is closed")
        # Exact equality, including inventory membership. No cached mtime check.
        if _source_bytes() != self._sources:
            raise TectonicsError("source changed; create a new execution context")
        _, tokens, constants = _callable_inventory(self.backend)
        if constants != self._constants or len(tokens) != len(self._tokens):
            raise TectonicsError("loaded implementation changed")
        for now, old in zip(tokens, self._tokens):
            if now[0] != old[0] or now[1] is not old[1] or now[2] is not old[2] or now[3] != old[3]:
                raise TectonicsError("loaded implementation changed")

    def close(self):
        if not self._closed:
            try:
                self.verify()
            finally:
                self._closed = True

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, *args):
        self.close()


def execution_identity(backend="reference"):
    return ExecutionContext(backend).identity


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
    execution = execution_identity(backend) if context is None else context.identity
    if context is not None and context.backend != backend:
        raise TectonicsError("context/backend mismatch")
    return {"schema": "atlas.kernel-invocation.v2", "operation": operation,
        "backend": backend, "execution": execution,
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
        _cancelled(cancel)
        ident = threading.get_ident()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                if len(self._entries) >= self.max_entries:
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
                    self._entries.pop(key, None)
        else:
            deadline = time.monotonic()+timeout
            try:
                while True:
                    _cancelled(cancel)
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("waiting for identical cache request timed out")
                    try:
                        result = future.result(timeout=min(.05,remaining))
                        break
                    except FutureTimeout:
                        if future.done():
                            raise  # a producer's own TimeoutError is not a wait timeout
            finally:
                with self._lock:
                    self._waiters -= 1
        _cancelled(cancel)
        if not leader and validate is not None:
            validate()
        return result.view()


_FLIGHTS = _Flights()


@contextmanager
def _process_claim(store, key, cancel, timeout):
    """Crash-released local OS lock; 16 fixed stripes, no stale lease takeover.

    Same-process requests first use _FLIGHTS. Separate connections/processes
    recheck the database after taking this lock. Different keys can share a stripe;
    that only serialises extra work. No scientific data are stored in lock files.
    """
    from .storage import _path
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
            if st.st_size == 0:
                os.write(fd,b"0")
            def take():
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
        while not acquired:
            _cancelled(cancel)
            try:
                take(); acquired = True
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK): raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("cache compute lock timed out") from exc
                time.sleep(.01)
        yield
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
    key = _digest(_json(record))
    count = elements(shape)
    def check_result(result):
        if type(result) is not np.ndarray or result.shape != shape or result.dtype != np.dtype("float64"):
            raise TectonicsError("cached result contract mismatch")
        return result
    def produce():
        # Kernel/get workspace ends at return, but its result remains resident
        # through validation, compression and publication. Reserve that lifetime
        # before execution so a concurrent producer cannot consume its capacity.
        with budget.reserve(8 * elements(shape), category="pending-result"), \
                _process_claim(store,key,cancel,wait_timeout):
            _cancelled(cancel)
            costs = controller.cost(key)
            recompute = cache_policy.mode == "auto" and costs.get("restore",0) > costs.get("compute",float("inf"))
            start = time.perf_counter()
            restored = None if recompute else store.get(key,budget=budget)
            restore_time = time.perf_counter()-start
            if restored is not None:
                if set(restored) != {"result"} or store.metadata(key) != record:
                    raise TectonicsError("cached result contract mismatch")
                result = check_result(restored["result"])
                context.verify()
                _cancelled(cancel)
                controller.count("hits")
                controller.cost(key,restore=restore_time)
                if admission_key is not None:
                    controller.profile(admission_key, restore=restore_time)
                return result
            controller.count("recomputes" if recompute else "misses")
            _cancelled(cancel)
            start = time.perf_counter(); result = check_result(compute())
            compute_time = time.perf_counter()-start
            context.verify(); _cancelled(cancel)
            controller.cost(key,compute=compute_time)
            if admission_key is not None:
                controller.profile(admission_key,compute=compute_time)
            admit = cache_policy.mode == "always" or (not recompute and
                compute_time >= cache_policy.min_compute_seconds and
                cache_policy.expected_reuses*(compute_time-costs.get("restore",0)) > costs.get("write",0))
            if admit:
                start = time.perf_counter()
                def publication_check():
                    context.verify()
                    _cancelled(cancel)
                store.put(key,{"result":result},record,publication_check=publication_check,
                          cancel=cancel,budget=budget)
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
    return _FLIGHTS.run(flight_key,produce,cancel=cancel,timeout=wait_timeout,validate=context.verify)


def _policy(value):
    if value is None: return CachePolicy()
    if not isinstance(value,CachePolicy): raise TectonicsError("typed CachePolicy required")
    return value


def _prepare_reuse(store, cache_policy, nbytes, controller, operation, backend):
    policy = _policy(cache_policy)
    if store is None: return policy, None, False, None
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
    if not use: control.count("bypasses")
    return policy, control, use, admission_key


def _direct(compute, control, admission_key, policy, cancel, context=None, backend=None):
    _cancelled(cancel)
    if context is not None:
        if not isinstance(context,ExecutionContext) or context.backend != backend:
            raise TectonicsError("context/backend mismatch")
        context.verify()
    start=time.perf_counter()
    result=compute()
    duration=time.perf_counter()-start
    if context is not None:
        context.verify()
    _cancelled(cancel)
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
    wait_timeout = _timeout(wait_timeout); _cancelled(cancel)
    # A store-bound wrapper joins its run envelope even when auto bypasses disk.
    # The caller may still supply an explicitly related per-call child budget.
    if budget is None and isinstance(store, ArrayStore):
        budget = store._budget
    ds,ts = _shape(depth_m),_shape(age_s)
    bs = np.broadcast_shapes(ds,ts)
    policy,control,use,admission_key = _prepare_reuse(store,cache_policy,8*elements(bs),controller,"cooling",backend)
    if not use:
        d = depth_m.array if type(depth_m) is PreparedInput else depth_m
        a = age_s.array if type(age_s) is PreparedInput else age_s
        return _direct(lambda:half_space_temperature(d,a,parameters,backend=backend,budget=budget),
                       control,admission_key,policy,cancel,context,backend)
    resource = select_budget(budget)
    with resource.reserve(16*(elements(ds)+elements(ts))):
        depth,dh = _capture(depth_m,"depth",nonnegative=True)
        age,ah = _capture(age_s,"age",nonnegative=True)
        if not isinstance(parameters,ThermalParameters):
            raise TectonicsError("explicit ThermalParameters required")
        ctx = control.context(backend) if context is None else context
        if not isinstance(ctx,ExecutionContext) or ctx.backend != backend:
            raise TectonicsError("context/backend mismatch")
        with resource.reserve(cooling_work_bytes(ds,ts)):
            record = _invocation_record("half-space-temperature-v2",{"depth":depth,"age":age},
                asdict(parameters),backend,context=ctx,digests={"depth":dh,"age":ah})
        return _evaluate(store,record,lambda:half_space_temperature(depth,age,parameters,
            backend=backend,budget=resource),bs,resource,context=ctx,controller=control,
            cache_policy=policy,cancel=cancel,wait_timeout=wait_timeout,admission_key=admission_key)


def cached_flexure(operator: PeriodicFlexure, load_pa, *, store: ArrayStore | None = None,
                   budget=None, context=None, controller=None, cache_policy=None,
                   cancel=None, wait_timeout=30.):
    if not isinstance(operator,PeriodicFlexure): raise TectonicsError("explicit PeriodicFlexure required")
    wait_timeout = _timeout(wait_timeout); _cancelled(cancel)
    if budget is None and isinstance(store, ArrayStore):
        budget = store._budget
    shape = _shape(load_pa)
    if not shape or shape[-1] != operator.grid.cells:
        raise TectonicsError("load final dimension must equal grid cells")
    policy,control,use,admission_key = _prepare_reuse(store,cache_policy,8*elements(shape),controller,"flexure","fft")
    if not use:
        load = load_pa.array if type(load_pa) is PreparedInput else load_pa
        return _direct(lambda:operator.solve(load,budget=budget),control,admission_key,policy,cancel,context,"reference")
    resource = select_budget(budget)
    with resource.reserve(16*elements(shape)):
        load,digest = _capture(load_pa,"load")
        ctx = control.context("reference") if context is None else context
        if not isinstance(ctx,ExecutionContext) or ctx.backend != "reference":
            raise TectonicsError("context/backend mismatch")
        with resource.reserve(operator.work_bytes(shape)):
            record = _invocation_record("periodic-flexure-v2",{"load":load},
                {"grid":asdict(operator.grid),"material":asdict(operator.parameters),
                 "operator_id":operator.operator_id},"reference",context=ctx,digests={"load":digest})
        return _evaluate(store,record,lambda:operator.solve(load,budget=resource),shape,resource,
            context=ctx,controller=control,cache_policy=policy,cancel=cancel,wait_timeout=wait_timeout,admission_key=admission_key)


def cached_regional_transport(thickness_m, face_velocity_m_s, grid, duration_s, *,
        left, right, scheme="muscl", backend="numba", store=None, budget=None,
        context=None, controller=None, cache_policy=None, cancel=None, wait_timeout=30.):
    """W02 persistence through existing admission/claims/store, never a new cache.

    Cheap evolving steps normally bypass persistence. On admission, capture the
    same immutable inputs for identity and execution; key the external states,
    frame/grid, interval, scheme and compiler as well as interior data. The packed
    result is a versioned transfer format, not a lower-precision representation.
    """
    from .regional import (advect_regional, regional_work_bytes, _validate_definition,
                           pack_regional_result, unpack_regional_result)
    from ._validation import scalar
    _validate_definition(grid,left,right,scheme,backend)
    dt=scalar(duration_s,"duration_s",nonnegative=True)
    wait_timeout=_timeout(wait_timeout); _cancelled(cancel)
    if budget is None and isinstance(store,ArrayStore): budget=store._budget
    shapes=(_shape(thickness_m),_shape(face_velocity_m_s))
    if shapes != ((grid.cells,),(grid.cells+1,)):
        raise TectonicsError("expected N thicknesses and N+1 face velocities")
    size=2*grid.cells+9
    policy,control,use,admission_key=_prepare_reuse(store,cache_policy,8*size,controller,
                                                  "regional-"+scheme,backend)
    if not use:
        h=thickness_m.array if type(thickness_m) is PreparedInput else thickness_m
        u=face_velocity_m_s.array if type(face_velocity_m_s) is PreparedInput else face_velocity_m_s
        return _direct(lambda:advect_regional(h,u,grid,dt,left=left,right=right,scheme=scheme,
            backend=backend,budget=budget,cancel=cancel),control,admission_key,policy,cancel,context,backend)
    resource=select_budget(budget)
    with resource.reserve(16*(2*grid.cells+1),category="regional-cache-input"):
        h,hd=_capture(thickness_m,"thickness",nonnegative=True)
        u,ud=_capture(face_velocity_m_s,"face velocities")
        ctx=control.context(backend) if context is None else context
        if not isinstance(ctx,ExecutionContext) or ctx.backend != backend:
            raise TectonicsError("context/backend mismatch")
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
    from .materials import (advect_materials, material_work_bytes, _definition,
        _end_time, _exterior, _hash_array, pack_material_result, unpack_material_result)
    from ._validation import scalar
    _definition(state,left,right,scheme,backend)
    dt=scalar(duration_s,'duration',nonnegative=True);_end_time(state,dt)
    wait_timeout=_timeout(wait_timeout);_cancelled(cancel)
    if budget is None and isinstance(store,ArrayStore):budget=store._budget
    n=state.grid.cells;c=len(state.cohorts)
    if _shape(face_velocity_m_s)!=(n+1,):raise TectonicsError('N+1 velocities required')
    shape=(c,2*n+9);size=elements(shape)
    policy,control,use,admission_key=_prepare_reuse(store,cache_policy,8*size,controller,
                                                   'material-'+scheme,backend)
    if not use:
        velocity=face_velocity_m_s.array if type(face_velocity_m_s) is PreparedInput else face_velocity_m_s
        return _direct(lambda:advect_materials(state,velocity,dt,left=left,right=right,
            scheme=scheme,backend=backend,budget=budget,cancel=cancel),control,admission_key,
            policy,cancel,context,backend)
    resource=select_budget(budget)
    with resource.reserve(16*(n+1),category='material-cache-input'):
        u,ud=_capture(face_velocity_m_s,'face velocities')
        _exterior(state,u,left,True);_exterior(state,u,right,False)
        ctx=control.context(backend) if context is None else context
        if not isinstance(ctx,ExecutionContext) or ctx.backend!=backend:
            raise TectonicsError('context/backend mismatch')
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
    from .remapping import remap_materials,RemapPlan,restore_remap_result,_mesh_state
    from .mesh import ColumnGrid1D
    _mesh_state(state)
    if type(target) is not ColumnGrid1D or scheme not in ('linear','constant') or backend not in ('numba','reference'):
        raise TectonicsError('invalid remap definition')
    if budget is None and isinstance(store,ArrayStore):budget=store._budget
    shape=(len(state.cohorts),target.cells);size=elements(shape)
    policy,control,use,key=_prepare_reuse(store,cache_policy,8*size,controller,'material-remap-'+scheme,backend)
    if not use:return _direct(lambda:remap_materials(state,target,plan=plan,scheme=scheme,backend=backend,budget=budget,cancel=cancel),
                              control,key,policy,cancel,context,backend)
    resource=select_budget(budget)
    with resource.reserve(48*size+128*(state.grid.cells+target.cells)+8192,category='remap-cache'):
        op=RemapPlan(state.grid,target,backend=backend,budget=resource) if plan is None else plan
        if type(op) is not RemapPlan or op.source!=state.grid or op.target!=target:raise TectonicsError('stale remap plan')
        ctx=control.context(backend) if context is None else context
        if not isinstance(ctx,ExecutionContext) or ctx.backend!=backend:raise TectonicsError('context/backend mismatch')
        record=_invocation_record('material-remap-v1',{}, {'state_id':state.state_id,'state':state.descriptor(),
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
    from .remapping import advect_ale,restore_ale_result,_mesh_state,_boundary_values
    from .materials import pack_material_result,_end_time
    from ._validation import scalar
    _mesh_state(state);dt=scalar(duration_s,'duration',nonnegative=True);end=_end_time(state,dt)
    if scheme not in ('muscl','upwind') or backend not in ('numba','reference'):raise TectonicsError('invalid ALE method')
    for t in event_times_s:
        if state.time_s<scalar(t,'event time')<end:raise TectonicsError('interval crosses known event')
    n=state.grid.cells;c=len(state.cohorts)
    if _shape(face_velocity_m_s)!=(n+1,) or _shape(mesh_velocity_m_s)!=(n+1,):raise TectonicsError('N+1 physical/mesh velocities required')
    if budget is None and isinstance(store,ArrayStore):budget=store._budget
    shape=(c,2*n+9);size=elements(shape)
    policy,control,use,key=_prepare_reuse(store,cache_policy,8*size,controller,'ale-'+scheme,backend)
    if not use:
        u=face_velocity_m_s.array if type(face_velocity_m_s) is PreparedInput else face_velocity_m_s
        w=mesh_velocity_m_s.array if type(mesh_velocity_m_s) is PreparedInput else mesh_velocity_m_s
        return _direct(lambda:advect_ale(state,u,w,dt,left=left,right=right,scheme=scheme,backend=backend,
             event_times_s=event_times_s,budget=budget,cancel=cancel),control,key,policy,cancel,context,backend)
    resource=select_budget(budget)
    with resource.reserve(48*size+128*n+8192,category='ale-cache'):
        u,ud=_capture(face_velocity_m_s,'physical velocity');w,wd=_capture(mesh_velocity_m_s,'mesh velocity')
        _boundary_values(state,u-w,left,True);_boundary_values(state,u-w,right,False)
        ctx=control.context(backend) if context is None else context
        if not isinstance(ctx,ExecutionContext) or ctx.backend!=backend:raise TectonicsError('context/backend mismatch')
        record=_invocation_record('ale-packed-v1',{'u':u,'w':w},{'state_id':state.state_id,
             'state':state.descriptor(),'duration_s':dt,'left':asdict(left),'right':asdict(right),'scheme':scheme},
             backend,context=ctx,digests={'u':ud,'w':wd})
        record=json.loads(_json(record))
        packed=_evaluate(store,record,lambda:pack_material_result(advect_ale(state,u,w,dt,left=left,right=right,
               scheme=scheme,backend=backend,budget=resource,cancel=cancel)),shape,resource,context=ctx,
               controller=control,cache_policy=policy,cancel=cancel,wait_timeout=_timeout(wait_timeout),admission_key=key)
        return restore_ale_result(state,u,w,dt,left,right,scheme,backend,packed,budget=resource)
