"""Optional sealed-array disk cache; ArrayStore remains the sole authority.

One raw file per explicitly selected hot column is addressed by its sealed
reference, dtype/shape and ordered native chunk/descriptor bindings. No SQLite,
catalog or scientific identity changes. Existing files are authenticated against
the store on each opener, before use. Windows share-read handles prohibit writes
and replacement for the complete borrow lifetime; other hosts use ordinary reads.

There is deliberately no second in-memory page cache. Read-only mmap windows
exist only while borrowed. Their page-rounded capacity and carriers use the
existing retained scope; pressure declines the optional mapping. NumPy's buffer
base owns the mapping, so slices/asarray/memoryview aliases keep it charged after
the explicit borrow closes. Ordinary-read arrays also pin their paid bytes.

Michael explicitly authorised activation after reviewing the component results
on 15 October 2026. Selected sealed hot arrays therefore use this cache by
default; that decision is not a representative WP0b gate pass. Experimental
measurements alone never change the default. A future evidence-based admission
still requires both hot-read savings >=5% of the run and net run savings >=5%,
including creation/verification costs; its report is authenticated by the owner.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import ctypes
import math
import mmap
import os
from pathlib import Path
import stat
import threading
import time
import uuid

import numpy as np

from compact_contracts import ContractError
from content_cache import ChargeSpec, check_cancel
from interval_catalog import safe_path
from segment_store import SegmentView, _chunk, canonical, require


MAX_ARRAYS = 32
MAX_FILE_BYTES = 256 << 20
MAX_TOTAL_BYTES = 1 << 30
MAX_WINDOW_BYTES = 64 << 20
CONTROL_BYTES = 64 << 10
NATIVE_BYTES = 64 << 10
GATE_SCHEMA = 'atlas.raw-sidecar-adoption.v1'
DEFAULT_ENABLED = True
ACTIVATION_DECISION_ID = 'wp12-user-activate-20261015'
ACTIVATION_USER_STATEMENT = 'I want you to activate it'
ACTIVATION_REPORT_SHA256 = 'db0bb67064255f267c55b41f1d0845f6dadaa690f7ec3c48410cb2e6b6d912db'


def _digest(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def assess_adoption(evidence=None):
    """Review data only; never writes configuration or authenticates a report."""
    evidence = {} if evidence is None else evidence
    require(type(evidence) is dict, 'sidecar evidence must be a plain mapping')
    missing, failed = [], []
    if evidence.get('schema') != GATE_SCHEMA:
        missing.append('WP0b sidecar adoption schema')
    if evidence.get('source_kind') != 'real':
        missing.append('representative real WP0b run path')
    for name in ('report_sha256', 'input_binding_sha256', 'candidate_source_sha256'):
        if not _digest(evidence.get(name)):
            missing.append(name)
    for name in ('matched_configuration', 'includes_creation_and_verification', 'exact_identity'):
        if evidence.get(name) is not True:
            missing.append(name)
    names = evidence.get('array_names')
    if (type(names) is not list or not names or len(names) > MAX_ARRAYS
            or any(type(n) is not str for n in names)
            or len(set(names)) != len(names)):
        missing.append('array_names')
    times = {}
    for name in ('baseline_run_seconds', 'candidate_run_seconds',
                 'baseline_hot_read_seconds', 'candidate_hot_read_seconds'):
        value = evidence.get(name)
        try:
            valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
        except OverflowError:
            valid = False
        if not valid or (name == 'baseline_run_seconds' and value == 0):
            missing.append(name)
        else:
            times[name] = Decimal(str(value))
    if len(times) == 4:
        baseline, candidate = times['baseline_run_seconds'], times['candidate_run_seconds']
        before, after = times['baseline_hot_read_seconds'], times['candidate_hot_read_seconds']
        if before > baseline or after > candidate:
            failed.append('hot-read time exceeds enclosing run time')
        if (before - after) * 20 < baseline:
            failed.append('hot-read saving is below 5% of baseline run path')
        if candidate * 20 > baseline * 19:
            failed.append('net run saving is below 5% including creation and verification')
    return dict(status='INCOMPLETE' if missing else 'TESTED_DISABLED' if failed else 'READY_FOR_OWNER_REVIEW',
                missing_evidence=missing, failed_gates=failed, enabled=False,
                policy_written=False)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            getattr(info, 'st_birthtime_ns', info.st_ctime_ns), info.st_nlink,
            getattr(info, 'st_file_attributes', 0))


def _path_identity(path):
    safe_path(path, existing=True)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'sidecar must be an unlinked regular file')
    return _identity(info)


class _LockedFile:
    """Read handle denies write/delete sharing, including existing writer races."""
    def __init__(self, path, size):
        require(os.name == 'nt', 'immutable sidecar mapping requires Windows file sharing locks')
        import msvcrt
        from ctypes import wintypes
        self.file = None
        self.path, before = path, _path_identity(path)
        require(before[2] == size, 'sidecar length differs from authoritative array')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        create.restype = wintypes.HANDLE
        handle = create(str(path), 0x80000000, 1, None, 3, 0x08200000, None)
        require(handle != ctypes.c_void_p(-1).value, 'cannot lock sidecar against writes/replacement')
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle(handle)
            raise
        self.file = os.fdopen(fd, 'rb', buffering=0)
        self.identity = _identity(os.fstat(self.file.fileno()))
        require(before == self.identity == _path_identity(path), 'sidecar changed while opening')

    def check(self):
        require(self.file is not None and not self.file.closed, 'sidecar handle closed')
        require(self.identity == _identity(os.fstat(self.file.fileno())) ==
                _path_identity(self.path), 'sidecar changed after verification')

    def close(self):
        if self.file is not None:
            file, self.file = self.file, None
            file.close()
        pin = getattr(self, '_control_pin', None)
        if pin is not None:
            self._control_pin = None
            pin.close()

    def __del__(self):
        self.close()


class _PaidMapping(mmap.mmap):
    """The actual Python buffer owns its funding, not an outer ndarray wrapper."""
    def close(self):
        # Exported NumPy memoryviews make native close raise BufferError. Never
        # credit funding until native close succeeds.
        super().close()
        owner = getattr(self, '_paid_owner', None)
        if owner is not None:
            self._paid_owner = None
            counters, lock, count = self._counters, self._counter_lock, self._page_bytes
            with lock:
                counters['live_mapped_bytes'] -= count
                counters['live_mappings'] -= 1
            self._counters = self._counter_lock = None
            owner.close()
            pin, self._file_pin = self._file_pin, None
            pin.close()

    def __del__(self):
        self.close()


class _ArrayAnchor:
    """No-copy readonly NumPy base holding the actual ordinary-read owner.

    A memoryview finalizer is insufficient: re-exporting that memoryview can
    bypass its lifetime. NumPy instead retains this array-interface base through
    slicing/asarray and buffer re-exports of the ndarray. The anchor itself does
    not expose the underlying bytes as a separately borrowable buffer.
    """
    __slots__ = ('_owner', '_carrier', '_pointer', '_dtype', '_count')

    def __init__(self, owner, carrier, dtype):
        self._owner, self._carrier = owner, carrier
        self._dtype = dtype
        self._count = len(owner.value) // np.dtype(dtype).itemsize
        self._pointer = np.frombuffer(owner.value, dtype=dtype).__array_interface__['data'][0]

    @property
    def __array_interface__(self):
        return dict(version=3, shape=(self._count,), typestr=self._dtype,
                    data=(self._pointer, True))

    def __del__(self):
        if hasattr(self, '_owner'):
            self._owner.close()
            self._carrier.close()


class BorrowedArray:
    """Closing releases this reference; escaped NumPy aliases retain funding."""
    def __init__(self, array, *, mapped):
        self._array, self.mapped = array, mapped

    @property
    def value(self):
        if self._array is None:
            raise RuntimeError('closed array borrow')
        return self._array

    def close(self):
        self._array = None

    def __enter__(self):
        self.value
        return self

    def __exit__(self, kind, value, traceback):
        # A traceback holding an extracted ndarray still keeps its buffer paid.
        self.close()


@dataclass(frozen=True, slots=True)
class _Description:
    name: str
    dtype: str
    shape: tuple
    size: int
    binding: str
    path: Path


def _describe(view, name, root):
    with view.verified_read():
        with view.info.array(name) as descriptor:
            info = descriptor.value
            require(info.logical_bytes <= MAX_FILE_BYTES, 'selected array exceeds sidecar file cap')
            name, dtype, shape, size = info.name, info.dtype, info.shape, info.logical_bytes
        identity = view.cache_identity()
        require(identity is not None, 'mutable candidates cannot use raw sidecars')
        digest = sha256(b'atlas.raw-sidecar.v1\0' + identity + view.ref.to_json())
        digest.update(canonical(dict(name=name, dtype=dtype, shape=shape, bytes=size)))
        for entry in view._entries(name=name):
            raw = canonical(entry)
            digest.update(len(raw).to_bytes(8, 'big'))
            digest.update(raw)
        binding = digest.hexdigest()
    return _Description(name, dtype, shape, size, binding, root / ('raw-' + binding + '.bin'))


class RawSidecarStore:
    """Explicit cache facade over one live sealed SegmentView.

    Use .build() only to create a selected local cache, and .read() for flattened
    element ranges. Missing files never trigger an implicit rebuild. .close()
    retires the handles; already borrowed arrays remain usable, paid and locked.
    A changed/corrupt present file is an error, never a silent cache miss.
    """
    def __init__(self, view, cache_dir, *, array_names, enabled=DEFAULT_ENABLED,
                 experimental=False, adoption_evidence=None):
        require(isinstance(view, SegmentView), 'a sealed SegmentView is required')
        require(type(enabled) is bool and type(experimental) is bool, 'explicit boolean cache mode required')
        require(type(array_names) is tuple and 0 < len(array_names) <= MAX_ARRAYS,
                'bounded explicit tuple of hot array names required')
        require(all(type(name) is str and name for name in array_names)
                and len(set(array_names)) == len(array_names), 'unique array names required')
        require(view.cache_identity() is not None, 'mutable candidates cannot use raw sidecars')
        self.view, self.scope, self.cancel = view, view.scope, view.cancel
        self._lock = threading.RLock()
        self._closed, self._control = False, None
        self._files, self._descriptions = {}, {}
        self.root = safe_path(cache_dir)
        self.experimental = experimental
        self.enabled = enabled and os.name == 'nt'
        self.activation_status = 'EXPERIMENTAL_ONLY' if enabled and experimental else 'DISABLED'
        self._counters = dict(hits=0, misses=0, mapped_reads=0, fallback_reads=0,
            verified_files=0, verified_bytes=0, mapped_bytes=0, live_mapped_bytes=0,
            peak_mapped_bytes=0, live_mappings=0, builds=0, build_bytes=0,
            build_seconds=0.0, verify_seconds=0.0, optional_declines=0)
        reservation = self.scope.reserve(ChargeSpec('raw-sidecar-control', CONTROL_BYTES), cancel=self.cancel)
        self._control = reservation.commit(None, dependencies=(view._owner,))
        for name in array_names:
            if self.enabled:
                self._descriptions[name] = _describe(view, name, self.root)
            else:
                with view.info.array(name) as descriptor:
                    info = descriptor.value
                    self._descriptions[name] = _Description(
                        name, info.dtype, info.shape, info.logical_bytes, '', self.root)
        require(sum(d.size for d in self._descriptions.values()) <= MAX_TOTAL_BYTES,
                'selected sidecars exceed total disk cap')
        self.input_binding_sha256 = sha256(canonical(
            [self._descriptions[n].binding for n in sorted(self._descriptions)])).hexdigest()
        if enabled and not experimental and adoption_evidence is None:
            self.activation_status = ('ENABLED_USER_AUTHORISED' if self.enabled else
                                      'UNSUPPORTED_HOST_FALLBACK')
        elif enabled and not experimental:
            decision = assess_adoption(adoption_evidence)
            require(decision['status'] == 'READY_FOR_OWNER_REVIEW', 'real WP0b 5% run-path gate not demonstrated')
            require(adoption_evidence['input_binding_sha256'] == self.input_binding_sha256
                    and set(adoption_evidence['array_names']) == set(array_names)
                    and adoption_evidence['candidate_source_sha256'] ==
                    sha256(Path(__file__).read_bytes()).hexdigest(), 'adoption evidence does not bind this candidate/input')
            self.activation_status = 'ENABLED_REAL_WP0B' if self.enabled else 'UNSUPPORTED_HOST_FALLBACK'
        elif enabled and os.name != 'nt':
            self.activation_status = 'UNSUPPORTED_HOST_FALLBACK'
        if self.enabled:
            for description in self._descriptions.values():
                self._open_if_present(description)

    def _live(self):
        require(not self._closed, 'raw sidecar store is closed')
        check_cancel(self.cancel)
        self.view.check_unchanged()

    def sidecar_path(self, name):
        self._live()
        description = self._descriptions[name]
        return (description.path if description.binding else
                _describe(self.view, name, self.root).path)

    def _open_if_present(self, description):
        # lstat also catches dangling links; safe_path rejects reparse ancestors.
        safe_path(description.path)
        try:
            description.path.lstat()
        except FileNotFoundError:
            return None
        reservation = self.scope.reserve(ChargeSpec('raw-sidecar-file', 8192),
                                         required=False, cancel=self.cancel)
        if reservation is None:
            self._counters['optional_declines'] += 1
            return None
        pin = self._control._share(required=False, cancel=self.cancel)
        if pin is None:
            reservation.close()
            self._counters['optional_declines'] += 1
            return None
        # Backing retains the control pin without a cycle; the file owner is
        # held by mappings and failed frames until native resources are gone.
        locked = _LockedFile(description.path, description.size)
        locked._control_pin = pin
        owner = reservation.commit(locked)
        started = time.perf_counter()
        with self.view.verified_read():
            for entry in self.view._entries(name=description.name):
                body = entry['content']
                if not body['count']:
                    continue
                with _chunk(self.view.resolver, entry['owner'], body['chunk_id'],
                            canonical(entry['descriptor']), self.cancel) as raw:
                    # read allocation is bounded and charged before it exists.
                    with self.scope.reserve(ChargeSpec('raw-sidecar-verify', NATIVE_BYTES),
                                            cancel=self.cancel) as scratch:
                        data = locked.file.read(len(raw.value))
                        paid = scratch.commit(data)
                        require(data == raw.value, 'sidecar bytes differ from authenticated store chunk')
                        del data
                        paid.close()
                        self._counters['verified_bytes'] += len(raw.value)
            require(locked.file.read(1) == b'', 'sidecar has trailing bytes')
            locked.check()
        self._counters['verify_seconds'] += time.perf_counter() - started
        self._counters['verified_files'] += 1
        self._files[description.name] = owner
        return owner

    def build(self):
        """Explicit bounded creation, no overwrites or scientific writes."""
        with self._lock:
            self._live()
            require(self.enabled, 'building requires admitted or experimental cache mode')
            self.root = safe_path(self.root)
            self.root.mkdir(exist_ok=True)
            require(self.root.is_dir(), 'sidecar root must be a directory')
            for description in self._descriptions.values():
                if description.name in self._files:
                    continue
                if self._open_if_present(description) is not None:
                    continue
                # Existing but unadmitted files are never overwritten.
                if description.path.exists():
                    continue
                started = time.perf_counter()
                temporary = self.root / ('.raw-' + uuid.uuid4().hex + '.partial')
                safe_path(temporary)
                written = 0
                try:
                    with self.view.verified_read():
                        with temporary.open('xb', buffering=0) as output:
                            for entry in self.view._entries(name=description.name):
                                body = entry['content']
                                if not body['count']:
                                    continue
                                with _chunk(self.view.resolver, entry['owner'], body['chunk_id'],
                                            canonical(entry['descriptor']), self.cancel) as raw:
                                    count = output.write(raw.value)
                                    require(count == len(raw.value), 'short sidecar write')
                                    written += count
                                    require(written <= description.size, 'sidecar exceeded declared size')
                            require(written == description.size, 'sidecar write coverage differs')
                            output.flush()
                            os.fsync(output.fileno())
                        safe_path(description.path)
                        # Windows rename refuses an existing destination. It
                        # cannot replace another process's borrowed raw file.
                        require(os.name == 'nt', 'sidecar publication requires no-overwrite Windows rename')
                        os.rename(temporary, description.path)
                    self._counters['build_bytes'] += written
                    self._counters['builds'] += 1
                    self._counters['build_seconds'] += time.perf_counter() - started
                    self._open_if_present(description)
                except BaseException:
                    # Only this uniquely created, bounded temporary is removed;
                    # original stores and an existing destination are untouched.
                    if temporary.exists():
                        safe_path(temporary, existing=True)
                        temporary.unlink()
                    raise
            return self.stats()

    def _ordinary(self, description, start, stop, maximum):
        self._counters['fallback_reads'] += 1
        with self.view.verified_read():
            owner = self.view.read(description.name, start, stop, max_owned_bytes=maximum)
            reservation = self.scope.reserve(ChargeSpec('raw-sidecar-array', 0), cancel=self.cancel)
            anchor = _ArrayAnchor(owner, reservation.commit(None), description.dtype)
            array = np.asarray(anchor)
            require(array.base is anchor and not array.flags.writeable,
                    'ordinary array must retain its paid readonly base')
        return BorrowedArray(array, mapped=False)

    def read(self, name, start, stop, *, max_owned_bytes):
        with self._lock:
            self._live()
            description = self._descriptions[name]
            require(type(start) is int and type(stop) is int and
                    0 <= start <= stop <= math.prod(description.shape), 'array range is invalid')
            require(type(max_owned_bytes) is int and max_owned_bytes >= 0,
                    'explicit nonnegative read allowance required')
            itemsize = np.dtype(description.dtype).itemsize
            size = (stop - start) * itemsize
            require(size <= max_owned_bytes, 'explicit read allowance exceeded')
            owner = self._files.get(name) if self.enabled else None
            if owner is None or size == 0 or size > MAX_WINDOW_BYTES:
                self._counters['misses'] += 1
                return self._ordinary(description, start, stop, max_owned_bytes)
            offset = start * itemsize
            aligned = offset - offset % mmap.ALLOCATIONGRANULARITY
            prefix = offset - aligned
            length = prefix + size
            pages = ((length + mmap.PAGESIZE - 1) // mmap.PAGESIZE) * mmap.PAGESIZE
            reservation = self.scope.reserve(ChargeSpec('raw-sidecar-mapping', pages),
                                             required=False, cancel=self.cancel)
            if reservation is None:
                self._counters['optional_declines'] += 1
                self._counters['misses'] += 1
                return self._ordinary(description, start, stop, max_owned_bytes)
            pin = owner._share(required=False, cancel=self.cancel)
            if pin is None:
                reservation.close()
                self._counters['optional_declines'] += 1
                self._counters['misses'] += 1
                return self._ordinary(description, start, stop, max_owned_bytes)
            locked = pin.value
            with self.view.verified_read():
                locked.check()
                mapping = _PaidMapping(locked.file.fileno(), length, access=mmap.ACCESS_READ, offset=aligned)
                mapping._paid_owner = reservation.commit(None)
                mapping._file_pin = pin
                mapping._page_bytes = pages
                mapping._counters, mapping._counter_lock = self._counters, self._lock
                self._counters['live_mapped_bytes'] += pages
                self._counters['live_mappings'] += 1
                self._counters['mapped_bytes'] += pages
                self._counters['peak_mapped_bytes'] = max(
                    self._counters['peak_mapped_bytes'], self._counters['live_mapped_bytes'])
                # frombuffer keeps an exported memoryview: native close refuses
                # while even a base/slice/np.asarray alias still uses the map.
                array = np.frombuffer(mapping, dtype=description.dtype,
                                      count=stop-start, offset=prefix)
                require(not array.flags.writeable, 'mapped array must be read-only')
                locked.check()
                check_cancel(self.cancel)
            self._counters['hits'] += 1
            self._counters['mapped_reads'] += 1
            return BorrowedArray(array, mapped=True)

    def stats(self):
        with self._lock:
            return dict(self._counters, enabled=self.enabled,
                        experimental=self.experimental, activation_status=self.activation_status,
                        activation_decision_id=(ACTIVATION_DECISION_ID
                            if self.activation_status == 'ENABLED_USER_AUTHORISED' else None),
                        representative_wp0b_gate_passed=self.activation_status == 'ENABLED_REAL_WP0B')

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for owner in self._files.values():
                owner._retire()
            self._files.clear()
            self._descriptions.clear()
            if self._control is not None:
                owner, self._control = self._control, None
                owner._retire()

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, kind, value, traceback):
        self.close()

    def __del__(self):
        if hasattr(self, '_lock'):
            self.close()

