"""Small, standard-library runtime for verified generation reuse and recovery.

Receipts are a fast *early return* only after their complete, nonempty manifest
has been content-verified. Checkpoints are JSON, never executable serialisation.
Callers own semantic input selection, final writes, and any domain validation.
An input contract must be rechecked before committing outputs if its sources
could have changed while computation ran. Concurrent mutation is rejected when
observed; callers must serialise writers for a transaction-wide snapshot.

``bounded_map`` controls admission, not arbitrary allocations inside a task.
Estimates must include retained input and result memory. Workers should compute
only; the consuming caller commits results. Close its iterator explicitly when
abandoning it early, so all active work is joined before cleaning private state.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import importlib.metadata
import json
import math
import multiprocessing
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import sqlite3
import stat
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Iterator, TypeVar


_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_RECORD_BYTES = 64 * 1024 * 1024
_CHECKPOINT_SCHEMA = "diadem.generation.checkpoint.v1"
_RECEIPT_SCHEMA = "diadem.generation.receipt.v1"
_DEPENDENCIES = ("numpy", "rasterio", "shapely", "zarr", "numcodecs", "zstandard", "scipy")
_RECORD_WRITE_LOCK = threading.Lock()
_T = TypeVar("_T")
_R = TypeVar("_R")


class UnstableFileError(OSError):
    """The selected path changed while its content was being verified."""


class UnsafePathError(ValueError):
    """A runtime record refers to an unsafe or non-regular filesystem path."""


class GenerationCancelled(RuntimeError):
    """Cancellation was requested; all admitted workers have now been joined."""


def _canonical_json(value: Any) -> bytes:
    # Reject Python-only dictionary keys rather than changing their meaning on
    # JSON round-trip. allow_nan=False also prevents non-portable JSON values.
    def check(item: Any) -> None:
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise TypeError("JSON object keys must be strings")
            for child in item.values():
                check(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                check(child)
    check(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _nonempty_string(value: str, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _absolute(path: Path) -> Path:
    value = os.path.abspath(os.fspath(path))
    # The bundled Windows interpreter can hit MAX_PATH even when pathlib is
    # used. Extended names are strictly an IO detail, never a semantic key.
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
    return Path(value)


def _display_path(path: Path) -> str:
    value = str(path)
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    return value[4:] if value.startswith("\\\\?\\") else value


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _no_links(path: Path, *, allow_missing: bool = False) -> None:
    """Reject symlinks and Windows junction/reparse paths, including parents."""
    path = _absolute(path)
    chain = list(reversed(path.parents)) + [path]
    for part in chain:
        try:
            info = part.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise
        if _is_link(info):
            raise UnsafePathError(f"Links/reparse points are not reusable paths: {part}")
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise UnsafePathError(f"Non-directory path component: {part}")


def _state(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _same_path_and_handle(path_state: tuple[int, ...], handle_state: tuple[int, ...]) -> bool:
    # Python 3.12 on Windows may expose creation time through path.stat's
    # st_ctime and change time through fstat's st_ctime. Compare these APIs
    # without that incompatible field; all stability checks below use fstat
    # consistently, retaining genuine change-time mutation detection.
    if os.name == "nt":
        return path_state[:5] + path_state[6:] == handle_state[:5] + handle_state[6:]
    return path_state == handle_state


def _regular_state(path: Path) -> tuple[int, ...]:
    _no_links(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise UnsafePathError(f"Expected a regular file: {path}")
    with path.open("rb") as stream:
        observed = _state(os.fstat(stream.fileno()))
    if not _same_path_and_handle(_state(info), observed):
        raise UnstableFileError(f"Path changed before opening: {path}")
    return observed


def file_identity(path: Path) -> dict[str, Any]:
    """Hash a stable regular file; metadata is a race check, not cache proof.

    Missing files and unsupported paths raise. A source mutation, replacement,
    or link race detected between opening and the final check raises instead
    of returning an identity which could silently reuse unrelated content.
    """
    path = _absolute(path)
    before = _regular_state(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        opened = _state(os.fstat(stream.fileno()))
        if opened != before:
            raise UnstableFileError(f"File changed before hashing: {path}")
        for chunk in iter(lambda: stream.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
        finished = _state(os.fstat(stream.fileno()))
    after = _regular_state(path)
    if before != finished or before != after:
        raise UnstableFileError(f"File changed while hashing: {path}")
    return {"size_bytes": before[3], "sha256": digest.hexdigest()}


def implementation_identity(paths: Iterable[Path], *, root: Path | None = None) -> dict[str, Any]:
    """Bind explicitly supplied source/lock files plus runtime versions.

    Exact content is bound under portable logical paths relative to root (or
    the selected files' common parent). Absolute machine paths never enter
    the semantic contract. Supply root when retaining a wider logical layout
    matters. Distribution metadata is read without importing numerical
    packages. Callers supply the dependency closure and lock/manifest files;
    this function does not infer imports or scan a project.
    """
    selected = sorted({_absolute(path) for path in paths}, key=lambda p: str(p))
    if not selected:
        raise ValueError("At least one implementation or runtime-lock file is required")
    logical_root = _absolute(root) if root is not None else Path(
        os.path.commonpath([str(path.parent) for path in selected]))
    try:
        logical = {path: path.relative_to(logical_root).as_posix() for path in selected}
    except ValueError as exc:
        raise ValueError("All implementation files must be beneath their logical root") from exc
    if len({name.casefold() for name in logical.values()}) != len(selected):
        raise ValueError("Implementation files have colliding logical names")
    selected.sort(key=lambda path: logical[path])
    initial = {path: _regular_state(path) for path in selected}
    identities = [dict(path=logical[path], **file_identity(path)) for path in selected]
    dependencies: dict[str, str | None] = {}
    for name in _DEPENDENCIES:
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    result = {
        "schema": "diadem.generation.implementation.v1",
        "files": identities,
        "python": {"implementation": platform.python_implementation(),
                   "version": sys.version, "cache_tag": sys.implementation.cache_tag},
        "platform": {"system": platform.system(), "release": platform.release(),
                     "machine": platform.machine(), "byteorder": sys.byteorder},
        "dependencies": dependencies,
        "sqlite_version": sqlite3.sqlite_version,
    }
    if any(_regular_state(path) != initial[path] for path in selected):
        raise UnstableFileError("Implementation files changed during identity assembly")
    return result


def semantic_identity(producer: str, inputs: dict[str, Any],
                      parameters: dict[str, Any],
                      implementation: dict[str, Any]) -> str:
    """Return the stable SHA-256 identity of an explicit generation contract."""
    _nonempty_string(producer, "producer")
    for name, value in (("inputs", inputs), ("parameters", parameters),
                        ("implementation", implementation)):
        if not isinstance(value, dict):
            raise TypeError(f"{name} must be a dictionary")
    value = {"schema": "diadem.generation.semantic.v1", "producer": producer,
             "inputs": inputs, "parameters": parameters, "implementation": implementation}
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _envelope(content: dict[str, Any]) -> dict[str, Any]:
    return {"content": content, "content_sha256": hashlib.sha256(_canonical_json(content)).hexdigest()}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant: {value}")


def _load_checked(path: Path) -> dict[str, Any] | None:
    try:
        path = _absolute(path)
        before = _regular_state(path)
        if before[3] > _MAX_RECORD_BYTES:
            return None
        with path.open("rb") as stream:
            if _state(os.fstat(stream.fileno())) != before:
                return None
            raw = stream.read(_MAX_RECORD_BYTES + 1)
            if _state(os.fstat(stream.fileno())) != before:
                return None
        if len(raw) > _MAX_RECORD_BYTES or _regular_state(path) != before:
            return None
        envelope = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if not isinstance(envelope, dict) or set(envelope) != {"content", "content_sha256"}:
            return None
        content = envelope["content"]
        if not isinstance(content, dict):
            return None
        checksum = hashlib.sha256(_canonical_json(content)).hexdigest()
        if envelope["content_sha256"] != checksum:
            return None
        return content
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return None


def _directory(path: Path) -> tuple[int, int]:
    _no_links(path, allow_missing=True)
    path.mkdir(parents=True, exist_ok=True)
    _no_links(path)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise UnsafePathError(f"Expected directory: {path}")
    return info.st_dev, info.st_ino


def _fsync_directory(path: Path) -> None:
    # Windows does not expose directory fsync through os.open. The temporary
    # file is fsynced on every platform before atomic replacement.
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    encoded = _canonical_json(value)
    if len(encoded) > _MAX_RECORD_BYTES:
        raise ValueError("Runtime record exceeds the 64 MiB safety limit")
    # Generation already uses a coordinator writer. This lock additionally
    # protects concurrent API callers on Windows, where transient stat/open
    # handles can otherwise deny an atomic replacement of the same filename.
    with _RECORD_WRITE_LOCK:
        _atomic_record_bytes(path, encoded)


def _atomic_record_bytes(path: Path, encoded: bytes) -> None:
    path = _absolute(path)
    parent_state = _directory(path.parent)
    _no_links(path, allow_missing=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
            written_state = _state(os.fstat(stream.fileno()))
        _no_links(path, allow_missing=True)
        parent = path.parent.stat()
        if (parent.st_dev, parent.st_ino) != parent_state:
            raise UnstableFileError(f"Record parent directory changed: {path.parent}")
        if _regular_state(temporary) != written_state:
            raise UnstableFileError(f"Temporary record changed: {temporary}")
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        # Only this invocation's securely allocated temporary file is removed.
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class CheckpointStore:
    """Identity-namespaced, content-checked JSON results for completed units."""

    def __init__(self, root: Path, identity: str):
        self.root = _absolute(root)
        self.identity = _nonempty_string(identity, "identity")
        namespace = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        self.directory = self.root / namespace

    def _path(self, key: str) -> Path:
        _nonempty_string(key, "key")
        return self.directory / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")

    def load(self, key: str) -> Any | None:
        content = _load_checked(self._path(key))
        if content is None or set(content) != {"schema", "identity", "key", "payload"}:
            return None
        if (content["schema"] != _CHECKPOINT_SCHEMA or content["identity"] != self.identity
                or content["key"] != key):
            return None
        return content["payload"]

    def save(self, key: str, payload: Any) -> None:
        path = self._path(key)
        content = {"schema": _CHECKPOINT_SCHEMA, "identity": self.identity,
                   "key": key, "payload": payload}
        _atomic_json(path, _envelope(content))


def _root_path(root: Path) -> Path:
    root = _absolute(root)
    _no_links(root)
    if not root.is_dir():
        raise UnsafePathError(f"Output root is not a directory: {root}")
    return root


def _manifest_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise UnsafePathError("Output paths must be nonempty relative POSIX paths")
    pure = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    parts = relative.split("/")
    if (pure.is_absolute() or windows.is_absolute() or windows.drive
            or any(part in ("", ".", "..") or ":" in part
                   or part.endswith((".", " ")) for part in parts)):
        raise UnsafePathError(f"Unsafe output path: {relative!r}")
    path = root.joinpath(*parts)
    if not path.is_relative_to(root):
        raise UnsafePathError(f"Output escapes its root: {relative!r}")
    _no_links(path)
    return path


def _output_relative(root: Path, output: Path) -> str:
    path = _absolute(output)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise UnsafePathError(f"Output is outside its root: {path}") from exc
    _manifest_path(root, relative)
    return relative


def save_receipt(path: Path, identity: str, root: Path,
                 outputs: Iterable[Path], result: dict[str, Any]) -> None:
    """Atomically save proof for an exact, nonempty set of completed files.

    Outputs must be file Paths under root, not directories, globs or symlinks.
    The saved result must be a dictionary and is returned by load_receipt.
    This function does not perform domain validation or discover missing files.
    """
    _nonempty_string(identity, "identity")
    if not isinstance(result, dict):
        raise TypeError("Receipt result must be a dictionary")
    root = _root_path(root)
    receipt_path = _absolute(path)
    names = [_output_relative(root, output) for output in outputs]
    if not names or len(names) != len(set(names)):
        raise ValueError("Receipt outputs must be nonempty and contain no duplicates")
    selected = [(name, _manifest_path(root, name)) for name in sorted(names)]
    if len({output for _, output in selected}) != len(selected):
        raise ValueError("Receipt outputs contain duplicate filesystem paths")
    if any(output == receipt_path for _, output in selected):
        raise ValueError("A receipt cannot include itself as an output")
    initial = {output: _regular_state(output) for _, output in selected}
    manifest = [dict(path=name, **file_identity(output)) for name, output in selected]
    if any(_regular_state(output) != initial[output] for _, output in selected):
        raise UnstableFileError("Outputs changed while their receipt was assembled")
    content = {"schema": _RECEIPT_SCHEMA, "identity": identity,
               "output_root": _display_path(root), "outputs": manifest, "result": result}
    _atomic_json(receipt_path, _envelope(content))


def load_receipt(path: Path, identity: str, root: Path) -> dict[str, Any] | None:
    """Return the saved result only after every exact listed output verifies.

    A missing, malformed, stale, corrupt or unsafe receipt is a cache miss.
    Never treats an empty output set as proof of complete generation.
    """
    _nonempty_string(identity, "identity")
    try:
        root = _root_path(root)
        content = _load_checked(path)
        if content is None or set(content) != {"schema", "identity", "output_root", "outputs", "result"}:
            return None
        if (content["schema"] != _RECEIPT_SCHEMA or content["identity"] != identity
                or content["output_root"] != _display_path(root) or not isinstance(content["result"], dict)):
            return None
        outputs = content["outputs"]
        if not isinstance(outputs, list) or not outputs:
            return None
        initial: dict[Path, tuple[int, ...]] = {}
        for item in outputs:
            if not isinstance(item, dict) or set(item) != {"path", "size_bytes", "sha256"}:
                return None
            if (type(item["size_bytes"]) is not int or item["size_bytes"] < 0
                    or not isinstance(item["sha256"], str) or len(item["sha256"]) != 64
                    or any(char not in "0123456789abcdef" for char in item["sha256"])):
                return None
            output = _manifest_path(root, item["path"])
            if output in initial or output == _absolute(path):
                return None
            initial[output] = _regular_state(output)
            if file_identity(output) != {"size_bytes": item["size_bytes"], "sha256": item["sha256"]}:
                return None
        if any(_regular_state(output) != state for output, state in initial.items()):
            return None
        return content["result"]
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return None


def _positive_integer(value: int, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass
class _ProcessResult:
    value: Any
    started: float
    finished: float
    cpu_seconds: float
    process_id: int


def _process_invoke(function: Callable[[_T], _R], item: _T) -> _ProcessResult:
    """Spawn-safe worker envelope; no parent locks, stats or handles cross over."""
    started = time.perf_counter()
    cpu_started = time.process_time()
    value = function(item)
    return _ProcessResult(value, started, time.perf_counter(),
                          time.process_time() - cpu_started, os.getpid())


def _interval_peak(intervals: list[tuple[float, float]]) -> int:
    # End events precede start events at equal times: adjacent calls do not
    # establish concurrent computation.
    events = sorted([(start, 1) for start, end in intervals if end > start]
                    + [(end, -1) for start, end in intervals if end > start])
    active = peak = 0
    for _, change in events:
        active += change
        peak = max(peak, active)
    return peak


def bounded_map(function: Callable[[_T], _R], items: Iterable[_T], *,
                workers: int = 1, max_inflight: int | None = None,
                memory_budget_bytes: int = 256 * 1024 * 1024,
                estimated_task_bytes: int = 64 * 1024 * 1024,
                cancel_event: Any = None, stats: RuntimeStats | None = None,
                phase: str = "compute", backend: str = "thread",
                worker_overhead_bytes: int = 64 * 1024 * 1024) -> Iterator[_R]:
    """Yield ordered results with conservative worker and memory admission.

    Items are pulled exclusively by the caller thread, lazily, at most
    min(workers, max_inflight, budget // estimate) at once. With workers=1
    function runs directly in that thread: the sequential reference path.
    Cancellation raises GenerationCancelled; exceptions are propagated only
    after all admitted workers stop. No unbounded work queue is constructed.
    Optional phase telemetry reports actual overlapping worker calls, not just
    the requested limit. Worker elapsed time is a sum, not phase wall time.
    The caller must release large committed results before requesting the next
    item; admission cannot constrain references retained by application code.
    The process backend uses spawn and requires picklable module-level functions
    and private inputs. Each process slot additionally reserves the supplied
    interpreter/import estimate. If fewer than two process slots fit, execute
    the same function directly, without spawning. One worker is always direct.
    Process task estimates must cover retained parent/child data and IPC copies,
    separately from worker_overhead_bytes. Process completion/timing telemetry
    covers envelopes consumed by the caller: work joined after cancellation or
    failure is intentionally not reported as successfully consumed output.
    """
    _positive_integer(workers, "workers")
    limit = workers if max_inflight is None else _positive_integer(max_inflight, "max_inflight")
    _positive_integer(memory_budget_bytes, "memory_budget_bytes")
    _positive_integer(estimated_task_bytes, "estimated_task_bytes")
    if backend not in {"thread", "process"}:
        raise ValueError("backend must be thread or process")
    if type(worker_overhead_bytes) is not int or worker_overhead_bytes < 0:
        raise ValueError("worker_overhead_bytes must be a nonnegative integer")
    slots = memory_budget_bytes // estimated_task_bytes
    if slots < 1:
        raise ValueError("memory_budget_bytes cannot admit one estimated task")
    capacity = min(workers, limit, slots)
    use_processes = backend == "process" and capacity > 1
    if use_processes:
        process_slots = memory_budget_bytes // (estimated_task_bytes + worker_overhead_bytes)
        capacity = min(capacity, process_slots) if process_slots >= 2 else 1
        if os.name == "nt":
            capacity = min(capacity, 61)  # ProcessPoolExecutor's Windows limit.
        use_processes = capacity > 1
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise TypeError("cancel_event must provide is_set()")
    _nonempty_string(phase, "phase")
    if stats is not None and not isinstance(stats, RuntimeStats):
        raise TypeError("stats must be RuntimeStats")
    if stats is not None:
        stats.maximum(f"{phase}.requested_workers", workers)
        stats.maximum(f"{phase}.worker_limit", capacity)
        stats.maximum(f"{phase}.estimated_task_bytes", estimated_task_bytes)
        stats.maximum(f"{phase}.memory_budget_bytes", memory_budget_bytes)
        stats.maximum(f"{phase}.worker_overhead_bytes", worker_overhead_bytes if use_processes else 0)
        stats.maximum(f"{phase}.process_worker_limit", capacity if use_processes else 0)
    active_lock = threading.Lock()
    active = 0

    def invoke(item: _T) -> _R:
        nonlocal active
        if stats is None:
            return function(item)
        with active_lock:
            active += 1
            stats.maximum(f"{phase}.peak_active_workers", active)
        try:
            with stats.measure(f"{phase}.worker_elapsed_sum"):
                result = function(item)
            stats.increment(f"{phase}.completed")
            return result
        except BaseException:
            stats.increment(f"{phase}.failed")
            raise
        finally:
            with active_lock:
                active -= 1

    def admitted(inflight: int) -> None:
        if stats is not None:
            stats.increment(f"{phase}.admitted")
            stats.maximum(f"{phase}.peak_inflight", inflight)

    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise GenerationCancelled("Generation cancelled; active work has been joined")

    iterator = iter(items)
    if capacity == 1:
        while True:
            check_cancelled()
            try:
                item = next(iterator)
            except StopIteration:
                return
            check_cancelled()
            admitted(1)
            result = invoke(item)
            del item
            check_cancelled()
            yield result
            del result
        return

    pending: deque[tuple[Future[Any], float]] = deque()
    executor = (ProcessPoolExecutor(max_workers=capacity,
                    mp_context=multiprocessing.get_context("spawn")) if use_processes
                else ThreadPoolExecutor(max_workers=capacity, thread_name_prefix="generation"))
    process_intervals: list[tuple[float, float]] = []
    process_ids: set[int] = set()
    exhausted = False
    try:
        while True:
            check_cancelled()
            while not exhausted and len(pending) < capacity:
                check_cancelled()
                try:
                    item = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                check_cancelled()
                submitted = time.perf_counter()
                future = (executor.submit(_process_invoke, function, item) if use_processes
                          else executor.submit(invoke, item))
                pending.append((future, submitted))
                admitted(len(pending))
                del item
            if not pending:
                return
            future, _ = pending.popleft()
            try:
                result = future.result()
            except BaseException:
                if use_processes and stats is not None:
                    stats.increment(f"{phase}.failed")
                raise
            finally:
                del future
            if use_processes:
                if stats is not None:
                    stats.increment(f"{phase}.completed")
                    stats.add_seconds(f"{phase}.worker_elapsed_sum", result.finished - result.started)
                    stats.add_seconds(f"{phase}.worker_cpu_sum", result.cpu_seconds)
                    process_ids.add(result.process_id)
                    stats.maximum(f"{phase}.observed_processes", len(process_ids))
                    process_intervals.append((result.started, result.finished))
                    stats.maximum(f"{phase}.peak_active_workers", _interval_peak(process_intervals))
                    # No unconsumed/future call can start before its submission.
                    # Retain only intervals which could overlap such calls;
                    # this telemetry therefore stays bounded by in-flight work.
                    cutoff = min((submitted for _, submitted in pending),
                                 default=time.perf_counter())
                    process_intervals = [(start, end) for start, end in process_intervals
                                         if end >= cutoff]
                result = result.value
            check_cancelled()
            yield result
            del result
    finally:
        for future, _ in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)


@dataclass
class RuntimeStats:
    """Optional thread-safe counters/timings; excluded from semantic identity."""

    seconds: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    _lock: Any = field(default_factory=threading.Lock, repr=False)

    def increment(self, label: str, amount: int = 1) -> None:
        _nonempty_string(label, "label")
        if type(amount) is not int:
            raise TypeError("Counter increments must be integers")
        with self._lock:
            self.counts[label] = self.counts.get(label, 0) + amount

    def maximum(self, label: str, value: int) -> None:
        """Record a nonnegative integer high-water mark, never semantic state."""
        _nonempty_string(label, "label")
        if type(value) is not int or value < 0:
            raise ValueError("High-water marks must be nonnegative integers")
        with self._lock:
            self.counts[label] = max(self.counts.get(label, 0), value)

    def add_seconds(self, label: str, seconds: float) -> None:
        _nonempty_string(label, "label")
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Elapsed seconds must be finite and nonnegative")
        with self._lock:
            self.seconds[label] = self.seconds.get(label, 0.0) + seconds

    @contextmanager
    def measure(self, label: str) -> Iterator[None]:
        _nonempty_string(label, "label")
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            with self._lock:
                self.seconds[label] = self.seconds.get(label, 0.0) + elapsed

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"seconds": dict(sorted(self.seconds.items())),
                    "counts": dict(sorted(self.counts.items()))}
