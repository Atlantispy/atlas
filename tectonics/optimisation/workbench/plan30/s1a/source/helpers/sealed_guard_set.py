"""S1 Stage A: guard-equivalent freshness for a sealed interval file (Windows, NTFS).

Today every outer read batch re-walks the interval file's path (interval_catalog.file_token: one lstat of the file,
one of each ancestor and three sidecar probes). A guard set replaces the walk for a reader that holds it:

- At open, `acquire` holds every ancestor directory down from the drive root (FILE_LIST_DIRECTORY, sharing
  READ|WRITE) and then the file (GENERIC_READ, sharing READ only). No guard shares DELETE, so while the set is held
  none of those objects can be renamed or deleted, and the file cannot be opened for writing. Directory guards share
  WRITE, so entries can still be created, renamed, moved in or removed inside them (publication and quarantine).
- `acquire` then binds the textual path to the held objects: the full walk runs again under the guards, every
  ancestor's lstat (st_dev, st_ino) must equal its held handle's, no ancestor may carry a reparse bit, the held
  file's token (fstat's fields, with st_ctime_ns read from the handle as lstat reports it) must equal the path
  token field by field, and the held file's final DOS path must equal the text. The drive's DOS device target is
  recorded.
- Per batch, `GuardSet.token` first checks the drive mapping; if it changed, that check is today's walk. Otherwise
  it checks the held objects in today's refusal order and texts: one plain lstat of the file's path, each held
  ancestor's reparse tag, the held file's link, link-count and type checks, the same three sidecar lstats as today,
  and the held file's token, which the path's lstat must equal.

Anything that cannot be established (not Windows, not an absolute drive-letter path, not NTFS, a sharing violation,
a refused or mismatched binding, a final path that differs) returns None and the reader keeps today's walk
unchanged. Once a set is held, a failure raises; it never falls back. One recorded divergence: ancestors are no
longer looked up by path at each batch, so an OSError that only a permission change on an ancestor directory would
raise from today's walk no longer refuses; held ancestors cannot be renamed, deleted or re-tagged unseen.
"""
from collections import Counter
import os
from pathlib import Path
import re
import stat
import threading
import weakref

from compact_contracts import ContractError
from interval_catalog import file_token

# False sends every reader to today's walk. The walk is the reference behaviour, so this never weakens a check.
ENABLED = True
# Diagnostics only: 'guarded', 'released' and 'fallback:<reason>' counts.
STATS = Counter()
_STATS_LOCK = threading.Lock()


def _count(name):
    with _STATS_LOCK:
        STATS[name] += 1

_REPARSE = 0x400
_DRIVE_PATH = re.compile(r'[A-Za-z]:\\(?:[^\\/:*?"<>|\x00-\x1f]+\\)*[^\\/:*?"<>|\x00-\x1f]+')

_FILE_LIST_DIRECTORY = 0x1
_FILE_READ_ATTRIBUTES = 0x80
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_TAG_INFO = 9
# A directory guard is share-checked against rename and delete only because it asks for data-class access
# (FILE_LIST_DIRECTORY); attribute-only access would not be.
_DIRECTORY_GUARD = (_FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES, _FILE_SHARE_READ | _FILE_SHARE_WRITE,
                    _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT)
_FILE_GUARD = (_GENERIC_READ, _FILE_SHARE_READ, _FILE_FLAG_OPEN_REPARSE_POINT)

_api = None


def _kernel():
    global _api
    if _api is None:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                        wintypes.DWORD]
        kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
        kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
                                                     wintypes.DWORD]
        kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        kernel.GetVolumeInformationByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
                                                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                                         wintypes.LPWSTR, wintypes.DWORD]
        kernel.GetVolumeInformationByHandleW.restype = wintypes.BOOL
        kernel.QueryDosDeviceW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        kernel.QueryDosDeviceW.restype = wintypes.DWORD
        _api = (ctypes, wintypes, kernel, wintypes.HANDLE(-1).value)
    return _api


def _open(path, access, share, flags):
    """A raw handle for path, or OSError (a sharing violation included)."""
    ctypes, _, kernel, invalid = _kernel()
    handle = kernel.CreateFileW(path, access, share, None, _OPEN_EXISTING, flags, None)
    if handle is None or handle == invalid:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def _hold(path, guard):
    """(fd, handle) for one guard; the C runtime fd owns the handle and os.close releases it."""
    import msvcrt
    handle = _open(path, *guard)
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY), handle
    except BaseException:
        _kernel()[2].CloseHandle(handle)
        raise


def _release(held):
    for fd, _ in reversed(held):
        try:
            os.close(fd)
        except OSError:
            pass   # already closed; nothing is left to release


def _tag(handle):
    """FileAttributeTagInfo attributes of a held object; OSError if the handle cannot be queried."""
    ctypes, wintypes, kernel, _ = _kernel()
    info = (wintypes.DWORD * 2)()
    if not kernel.GetFileInformationByHandleEx(handle, _FILE_ATTRIBUTE_TAG_INFO, info, ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return info[0]


def _final_path(handle):
    ctypes, _, kernel, _ = _kernel()
    size = 1024
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        length = kernel.GetFinalPathNameByHandleW(handle, buffer, size, 0)   # FILE_NAME_NORMALIZED|VOLUME_NAME_DOS
        if length == 0:
            raise ctypes.WinError(ctypes.get_last_error())
        if length < size:
            return buffer.value
        size = length + 1


def _filesystem(handle):
    ctypes, _, kernel, _ = _kernel()
    name = ctypes.create_unicode_buffer(64)
    if not kernel.GetVolumeInformationByHandleW(handle, None, 0, None, None, None, name, len(name)):
        raise ctypes.WinError(ctypes.get_last_error())
    return name.value


def _dos_device(drive):
    """The full QueryDosDeviceW target list of a drive letter ('C:'), as one string."""
    ctypes, _, kernel, _ = _kernel()
    size = 1024
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        length = kernel.QueryDosDeviceW(drive, buffer, size)
        if length:
            return buffer[:length]
        error = ctypes.get_last_error()
        if error != 122 or size >= 1 << 16:   # ERROR_INSUFFICIENT_BUFFER
            raise ctypes.WinError(error)
        size *= 4


def _lstat(path):
    return os.lstat(path)


def _fstat(fd):
    return os.fstat(fd)


def _created_ns(handle):
    """The held file's creation time in ns since the epoch.

    lstat reports this as st_ctime_ns on Windows; Python 3.12's fstat reports the metadata change time there instead,
    which differs for any file whose attributes changed after creation (every sealed interval)."""
    ctypes, _, kernel, _ = _kernel()
    info = (ctypes.c_longlong * 5)()   # FILE_BASIC_INFO: four LARGE_INTEGER times, then FileAttributes
    if not kernel.GetFileInformationByHandleEx(handle, 0, info, ctypes.sizeof(info)):   # FileBasicInfo
        raise ctypes.WinError(ctypes.get_last_error())
    return (info[0] - 116444736000000000) * 100


def _token(info):
    # Field for field the tuple interval_catalog.file_token returns.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, getattr(info, 'st_file_attributes', 0))


def _held_token(info, handle):
    """_token of the held file: fstat's fields, with st_ctime_ns as lstat reports it (_created_ns)."""
    dev, ino, size, mtime_ns, _, mode, attributes = _token(info)
    return dev, ino, size, mtime_ns, _created_ns(handle), mode, attributes


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & _REPARSE


def _fallback(reason):
    _count('fallback:' + reason)


class _HandleLifetime:
    """One release state shared before acquisition, through registration and finalization.

    In particular, weakref.finalize can register its callback and then be interrupted before GuardSet.__init__
    or acquire receives its result. Both cleanup paths already hold this same lifetime and cannot close an fd
    twice. The lock is also the token lock, so a finalizer cannot release handles while token queries them.
    """

    def __init__(self, held):
        self.held = held
        self.lock = threading.Lock()
        self.closed = False

    def close(self):
        with self.lock:
            if self.closed:
                return False
            self.closed = True
            _release(self.held)
            return True


def acquire(path):
    """A bound guard set for the sealed interval file at path, or None (the caller keeps today's walk)."""
    if not ENABLED:
        return _fallback('disabled')
    if os.name != 'nt':
        return _fallback('platform')
    text = str(path)
    if not _DRIVE_PATH.fullmatch(text):
        return _fallback('path-form')
    parts = text.split('\\')
    held, guards = [], None
    lifetime = _HandleLifetime(held)
    try:
        for prefix in [parts[0] + '\\'] + ['\\'.join(parts[:i]) for i in range(2, len(parts))]:
            held.append(_hold(prefix, _DIRECTORY_GUARD))
        held.append(_hold(text, _FILE_GUARD))
        guards = GuardSet(text, held, lifetime=lifetime)
        reason = guards._bind()
    except (OSError, ContractError):
        # A sharing violation, a missing component or a walk refusal. The reader's own walk, which runs next,
        # gives today's refusal for anything that is still wrong.
        reason = 'acquire'
    except BaseException:
        lifetime.close()
        raise
    if reason is not None:
        lifetime.close()
        return _fallback(reason)
    _count('guarded')
    return guards


class GuardSet:
    """Held handles on a sealed interval file and every ancestor, bound to the file's textual path."""

    def __init__(self, text, held, *, lifetime=None):
        self._text, self._path, self._drive = text, Path(text), text[:2]
        # (fd, handle) pairs: ancestors root-down, then the file.
        self._dirs, self._file, self._device = held[:-1], held[-1], None
        self._lifetime = _HandleLifetime(held) if lifetime is None else lifetime
        self._lock = self._lifetime.lock
        # A set dropped without close is released when collected, as an unclosed SQLite connection is today.
        self._finalizer = weakref.finalize(self, self._lifetime.close)

    def _bind(self):
        """None when the textual path provably resolves through the held objects; otherwise a fallback reason."""
        if _filesystem(self._file[1]) != 'NTFS':
            return 'filesystem'
        expected = file_token(self._path, reject_sidecars=True)   # today's full walk, now under the guards
        ancestors = [self._path.parents[i] for i in range(len(self._dirs) - 1, -1, -1)]
        for ancestor, (fd, handle) in zip(ancestors, self._dirs, strict=True):
            info, held = _lstat(ancestor), _fstat(fd)
            if ((info.st_dev, info.st_ino) != (held.st_dev, held.st_ino) or not stat.S_ISDIR(held.st_mode)
                    or _linked(info) or _tag(handle) & _REPARSE):
                return 'binding'
        if _held_token(_fstat(self._file[0]), self._file[1]) != expected:
            return 'token-drift'
        final = _final_path(self._file[1])
        # Exact apart from the drive letter's case: 8.3 names, subst, mapped drives and case differences fall back.
        if not final.startswith('\\\\?\\') or final[4:5].upper() + final[5:] != self._text[:1].upper() + self._text[1:]:
            return 'final-path'
        self._device = _dos_device(self._drive)
        return None

    def token(self):
        """Today's per-batch refusals, judged on the held objects; returns the file_token tuple from fstat."""
        with self._lock:
            if self._lifetime.closed:
                raise ContractError('interval handle is closed')
            # 0. The drive letter still names the device it named at open (P8). If it does not, the held objects no
            #    longer stand for the path, so this check is today's walk: its refusals, in its order, and its token.
            if _dos_device(self._drive) != self._device:
                return file_token(self._path, reject_sidecars=True)
            # 1. The file's path, as today's walk sees it first (P1, P2, P4 on the path).
            try:
                info = _lstat(self._text)
            except FileNotFoundError:
                raise ContractError('required interval file is missing') from None
            if _linked(info):
                raise ContractError('linked/reparse paths are forbidden')
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise ContractError('hard-linked files are forbidden')
            # 2. No held ancestor has gained a reparse tag (P3).
            for _, handle in self._dirs:
                if _tag(handle) & _REPARSE:
                    raise ContractError('linked/reparse paths are forbidden')
            # 3. The held file itself (P2, P4, P5).
            held = _fstat(self._file[0])
            if _linked(held):
                raise ContractError('linked/reparse paths are forbidden')
            if stat.S_ISREG(held.st_mode) and held.st_nlink != 1:
                raise ContractError('hard-linked files are forbidden')
            if not (stat.S_ISREG(held.st_mode) and stat.S_ISREG(info.st_mode)):
                raise ContractError('required path is not a regular file')
            # 4. Stage A keeps today's three sidecar lstats verbatim (P6).
            for suffix in ('-journal', '-wal', '-shm'):
                sidecar = Path(self._text + suffix)
                try:
                    sidecar.lstat()
                except FileNotFoundError:
                    continue
                raise ContractError('sealed interval has a journal/WAL sidecar')
            # 5. The path still names the held file, unchanged since this batch's fstat (P7 is the caller's).
            current = _held_token(held, self._file[1])
            if _token(info) != current:
                raise ContractError('immutable interval file identity changed')
            return current

    def close(self):
        # Wait on the shared lock even if another thread has already called the finalizer but is still closing.
        # Keep the existing diagnostic meaning: released counts first explicit closes, not GC/fallback cleanup.
        if self._lifetime.close():
            _count('released')
        self._finalizer.detach()
