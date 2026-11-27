"""Cooperative admission for a canonical interval store and its run home."""
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
import ctypes
from functools import wraps
import json
import os
from pathlib import Path
import stat
import threading
from uuid import uuid4


class HomeBusy(RuntimeError):
    """Another home client owns an incompatible lock."""


class RecoveryRequired(RuntimeError):
    """Protected outputs are unavailable until a pending transition is recovered."""


def _ordinary(path, *, existing=False):
    return _ordinary_info(path, existing=existing)[0]


def _ordinary_info(path, *, existing=False):
    path = Path(path).absolute()
    target = None
    for item in (path, *path.parents):
        info = _ordinary_leaf(item, existing=existing and item == path, check_links=item == path)
        if item == path:
            target = info
    return path, target


def _ordinary_leaf(path, *, existing=False, check_links=True):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if existing:
            raise
        return None
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('linked interval admission path')
    if check_links and stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise ValueError('hard-linked interval admission file')
    return info


def flush_file(file):
    file.flush()
    if os.name == 'nt':
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        flush = kernel.FlushFileBuffers
        flush.argtypes, flush.restype = [ctypes.c_void_p], ctypes.c_int
        if not flush(msvcrt.get_osfhandle(file.fileno())):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.fsync(file.fileno())


def durable_replace(source, target):
    source, target = _ordinary(source, existing=True), _ordinary(target)
    if not source.is_file():
        raise ValueError('durable replacement requires an ordinary file')
    _durable_rename(source, target, replace=True)


def durable_move(source, target):
    source, target = _ordinary(source, existing=True), _ordinary(target)
    if os.path.lexists(target):
        raise FileExistsError(target)
    _durable_rename(source, target, replace=False)


def _durable_rename(source, target, *, replace):
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        move = kernel.MoveFileExW
        move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move.restype = ctypes.c_int
        if not move(str(source), str(target), (0x1 if replace else 0) | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        (os.replace if replace else os.rename)(source, target)
        for parent in dict.fromkeys((target.parent, source.parent)):
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)


def canonical_store(path):
    candidate = Path(path).absolute()
    held = _active.get().get(candidate)
    if held is not None:
        return held.store
    ordinary, info = _ordinary_info(candidate)
    store = ordinary.resolve()
    if not store.name or store.name.endswith('.atlas-home') or not store.parent.is_dir():
        raise ValueError('unambiguous interval store and existing parent required')
    if info is not None and not stat.S_ISDIR(info.st_mode):
        raise ValueError('interval store is not a directory')
    return store


def _control(store):
    path = store.parent/f'.{store.name}.atlas-home'
    info = _ordinary_leaf(path)
    if info is None:
        path.mkdir(exist_ok=True)
        info = _ordinary_leaf(path, existing=True)
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('interval admission control is not a directory')
    return path


class _Overlapped(ctypes.Structure):
    _fields_ = [('internal', ctypes.c_size_t), ('internal_high', ctypes.c_size_t),
                ('offset', ctypes.c_uint32), ('offset_high', ctypes.c_uint32), ('event', ctypes.c_void_p)]


def _lock_file(path, exclusive):
    _ordinary_leaf(path)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    stream = os.fdopen(descriptor, 'r+b', buffering=0)
    try:
        info = os.fstat(descriptor)
        after = _ordinary_leaf(path, existing=True)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not os.path.samestat(info, after):
            raise ValueError('admission lock file changed during opening')
        if os.name == 'nt':
            import msvcrt
            lock = ctypes.WinDLL('kernel32', use_last_error=True).LockFileEx
            lock.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                             ctypes.c_uint32, ctypes.POINTER(_Overlapped)]
            lock.restype = ctypes.c_int
            overlap = _Overlapped()
            if not lock(msvcrt.get_osfhandle(descriptor), 1 | (2 if exclusive else 0), 0, 1, 0,
                        ctypes.byref(overlap)):
                error = ctypes.get_last_error()
                if error in (33, 997):
                    raise HomeBusy(f'interval home admission is busy: {path.name}')
                raise ctypes.WinError(error)
        else:
            import fcntl
            try:
                fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise HomeBusy(f'interval home admission is busy: {path.name}') from exc
        return stream
    except BaseException:
        stream.close()
        raise


@contextmanager
def driver_claim(store):
    store = canonical_store(store)
    control = _control(store)
    with _lock_file(control/'driver.lock', True):
        yield store


class _HomeAccess:
    def __init__(self, store, control, stream, exclusive):
        self.store, self.control, self.stream, self.exclusive = store, control, stream, exclusive
        self._references = 1
        self._lock = threading.Lock()

    def retain(self):
        with self._lock:
            if not self._references:
                raise RuntimeError('interval home admission has closed')
            self._references += 1
        return self

    def close(self):
        with self._lock:
            if self._references == 0:
                return
            self._references -= 1
            if self._references == 0:
                self.stream.close()

    def require_exclusive(self):
        if not self.exclusive or self.stream.closed:
            raise RecoveryRequired('protected move requires exclusive interval access')

    @property
    def pending_path(self):
        return self.control/'pending.json'

    def pending(self):
        if _ordinary_leaf(self.pending_path) is None:
            return None
        with self.pending_path.open('rb') as stream:
            raw = stream.read((64 << 10)+1)
        if len(raw) > 64 << 10:
            raise RecoveryRequired('interval recovery reference exceeds its bound')
        try:
            record = json.loads(raw)
            if (record['store'] != str(self.store) or
                    json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() != raw):
                raise ValueError('different store')
        except (TypeError, ValueError, KeyError) as exc:
            raise RecoveryRequired('interval recovery reference is unreadable') from exc
        return record

    def publish_pending(self, reference):
        self.require_exclusive()
        if _ordinary_leaf(self.pending_path) is not None:
            raise RecoveryRequired('interval recovery is already pending')
        image = json.dumps(dict(reference, store=str(self.store)), sort_keys=True, separators=(',', ':')).encode()
        temporary = self.control/f'pending-{uuid4().hex}.tmp'
        with temporary.open('xb') as stream:
            stream.write(image)
            flush_file(stream)
        durable_replace(temporary, self.pending_path)

    def clear_pending(self):
        self.require_exclusive()
        retired = self.control/f'cleared-{uuid4().hex}.tmp'
        durable_replace(self.pending_path, retired)
        retired.unlink()


_active = ContextVar('atlas-interval-home-access', default={})


def acquire(store, *, exclusive=False, recovery=False):
    return _acquire_canonical(canonical_store(store), exclusive=exclusive, recovery=recovery)


def _acquire_canonical(store, *, exclusive=False, recovery=False):
    held = _active.get().get(store)
    if held is not None:
        if exclusive:
            held.require_exclusive()
        return held.retain()
    control = _control(store)
    access = _HomeAccess(store, control, _lock_file(control/'access.lock', exclusive), exclusive)
    try:
        if _ordinary_leaf(access.pending_path) is not None and not (exclusive and recovery):
            raise RecoveryRequired('interval home requires recovery before ordinary access')
    except BaseException:
        access.close()
        raise
    return access


@contextmanager
def admitted(stores, *, exclusive=False, recovery=False):
    stores = sorted({canonical_store(path) for path in stores}, key=lambda path: os.path.normcase(str(path)))
    if any(child.is_relative_to(parent) for i, parent in enumerate(stores) for child in stores[i+1:]):
        raise ValueError('overlapping interval store assignments')
    with ExitStack() as stack:
        held = {}
        for store in stores:
            access = _acquire_canonical(store, exclusive=exclusive, recovery=recovery)
            stack.callback(access.close)
            held[store] = access
        token = _active.set({**_active.get(), **held})
        try:
            yield held
        finally:
            _active.reset(token)


@contextmanager
def inherit_exclusive(access):
    """Use the driver's already-held access inside the authenticated store owner."""
    access.require_exclusive()
    store = access.store
    held = _active.get().get(store)
    if held is access:
        yield
        return
    if held is not None:
        raise RuntimeError('interval access is already installed in this scope')
    token = _active.set({**_active.get(), store: access})
    try:
        yield
    finally:
        _active.reset(token)


def protect_profile(function):
    @wraps(function)
    def protected(profile, *args, **kwargs):
        with admitted((profile.record()['store_directory'],)):
            return function(profile, *args, **kwargs)
    return protected
