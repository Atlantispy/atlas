"""Admission option 1a(i) (coordinator, 16 Oct 2026): hold share-deny-write handles on every package source.

Source transform of atlas_tectonics/reuse.py. ExecutionContext.verify_boundary re-reads and
re-hashes EVERY package source on every call (about 30% of the fresh admission's initial
metrics: 3,876 calls, 1.9M stat calls). The guarantee it gives is that no package source has
changed since capture. This transform keeps that guarantee, by a different mechanism:

- At capture (non-release modes, Windows only), BEFORE anything is captured, the context
  opens every package `.py` with CreateFileW(GENERIC_READ, FILE_SHARE_READ). While those
  handles are held the OS refuses any write, truncation, rename or delete of those files by
  any process, and any rename of a directory that contains them. Capture refuses if a handle
  cannot be taken (for example another process holds the file open for writing), or if the
  package contains a junction, symbolic link or other reparse point.
- verify_boundary then checks, on EVERY call (_SourceHandles.check), that:
  the handles are still this context's and still open on the same files (each answers with
  the volume and file ID it had when taken, and is still a plain file, not a directory or
  reparse point); the package directory the import path names is still the directory that
  was locked (volume and file ID, so a junction retarget or drive remap ABOVE the package is
  refused); and the live membership (relative names, by a non-following walk) is unchanged
  with no reparse point inside the package. It no longer re-reads the bytes, which cannot
  have changed. The callable/default inventory re-walk stays on every call, unchanged.
- The handles are released on every exit path: close() (also via __exit__); any failure
  anywhere in capture after locking (released before the exception propagates); garbage
  collection or interpreter exit (a weakref.finalize on the holder itself, registered before
  the first handle is taken). Release is idempotent.
- Release mode (shared captures across contexts) and non-Windows hosts keep the original
  byte re-hash path unchanged.
r2 (16 Oct refuter): root identity + reparse refusal + per-handle file IDs; one try around
the whole capture; holder-level finalizer. r1 is kept as superseded/source_handles_r1.py.
Residual (not covered; needs an in-process bug): a foreign CloseHandle on one of these handle
values followed by a reopen of the SAME file under the same value; check() would still see
the same file ID.
Evidence: G/scripts/test_source_handles.py (OS refusals, junction retarget, reparse refusal,
foreign close, reopen refusal, release on every exit path, unchanged acceptance and timing).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '96e2092c2e056cc4f6bfb5caef70818567f59af54b4cdfc7d101bdea090e10fe': 'RC1 composed-r1 runtime-src',
}

ANCHOR_CLASS = 'class ExecutionContext:\n'
HELPER = '''
def _source_walk():
    """Package *.py membership by a non-following walk, and whether any reparse point was met.

    For a tree without reparse points these are exactly _source_bytes' rglob("*.py") names
    (files and directories, case-insensitive on Windows, the same 512-entry budget); capture
    checks the two agree. Any junction, symbolic link or other reparse point inside the
    package sets the flag, and every caller refuses on it. Windows only.
    """
    root = Path(__file__).parent
    names, linked, pending = [], False, [('', str(root))]
    while pending:
        prefix, directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                # Find-data attributes: no extra system call per entry.
                if entry.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    linked = True
                    continue
                name = prefix + entry.name
                if entry.name.lower().endswith('.py'):
                    if len(names) >= _SOURCE_FILES:
                        raise TectonicsError("execution source inventory exceeds context budget")
                    names.append(name)
                if entry.is_dir(follow_symlinks=False):
                    pending.append((name + '/', entry.path))
    return tuple(sorted(names)), linked


def _directory_id(path):
    """Volume and file ID of the directory a path names now (following any junction or remap)."""
    found = os.stat(path)
    return found.st_dev, found.st_ino


def _close_source_handles(kernel32, box):
    handles = box[:]
    box.clear()
    for handle in handles:
        kernel32.CloseHandle(handle)


class _SourceHandles:
    """Share-deny-write handles on every package source (Windows), released exactly once.

    check() is the per-call test that replaces the byte re-hash (see verify_boundary).
    """

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class _Info(ctypes.Structure):          # BY_HANDLE_FILE_INFORMATION
            _fields_ = [('attributes', wintypes.DWORD), ('created', wintypes.FILETIME),
                        ('accessed', wintypes.FILETIME), ('written', wintypes.FILETIME),
                        ('volume', wintypes.DWORD), ('size_high', wintypes.DWORD),
                        ('size_low', wintypes.DWORD), ('links', wintypes.DWORD),
                        ('index_high', wintypes.DWORD), ('index_low', wintypes.DWORD)]
        self._kernel32 = kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel32.CreateFileW
        create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        create.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        info = kernel32.GetFileInformationByHandle
        info.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Info))
        info.restype = wintypes.BOOL
        self._info, self._info_type, self._byref = info, _Info, ctypes.byref
        invalid = wintypes.HANDLE(-1).value
        self._box = box = []
        self._ids, self.names = (), ()
        self.held = True
        # Registered before the first handle is taken: a failure anywhere after this point,
        # or a holder dropped without release(), still closes every handle.
        self._finalizer = weakref.finalize(self, _close_source_handles, kernel32, box)
        self._root = root = Path(__file__).parent
        try:
            self._root_id = _directory_id(root)
            names, linked = _source_walk()
            if linked:
                raise TectonicsError("package sources contain a link or junction; they cannot be held")
            ids = []
            for name in names:
                # GENERIC_READ, FILE_SHARE_READ only, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL.
                handle = create(str(root.joinpath(*name.split('/'))), 0x80000000, 0x00000001, None, 3, 0x80, None)
                if handle is None or handle == invalid:
                    raise TectonicsError("a package source cannot be held against writes: " + name)
                box.append(handle)
                found = self._file_id(handle, _Info())
                if found is None:
                    raise TectonicsError("a package source is not a plain file: " + name)
                ids.append(found)
            self._ids, self.names = tuple(ids), names
            # Nothing moved while locking: the import path still names the locked directory
            # and the membership is the one locked.
            if not self.check():
                raise TectonicsError("source changed during inventory capture")
        except BaseException:
            self.release()
            raise

    def _file_id(self, handle, info):
        if not self._info(handle, self._byref(info)):
            return None
        if info.attributes & (stat.FILE_ATTRIBUTE_DIRECTORY | stat.FILE_ATTRIBUTE_REPARSE_POINT):
            return None
        return info.volume, info.index_high, info.index_low

    def check(self):
        """True only while every condition that makes a byte re-hash unnecessary holds."""
        handles = tuple(self._box)
        if not self.held or not handles or len(handles) != len(self._ids):
            return False
        try:
            if _directory_id(self._root) != self._root_id or _source_walk() != (self.names, False):
                return False
        except OSError:
            return False
        info = self._info_type()
        for handle, expected in zip(handles, self._ids):
            if self._file_id(handle, info) != expected:
                return False
        return self.held

    def release(self):
        self.held = False
        _close_source_handles(self._kernel32, self._box)


'''

OLD_CAPTURE_HEAD = '''    def _capture(self, backend):
        self.backend = backend
'''
NEW_CAPTURE_HEAD = '''    def _capture(self, backend):
        self._source_handles = None
        if os.name == 'nt' and getattr(self, '_mode', None) != 'release':
            # Taken BEFORE anything is captured: from here no process can write, rename or
            # delete a package source until this context releases the handles.
            self._source_handles = _SourceHandles()
        try:
            self._capture_sources(backend)
        except BaseException:
            # Any failure after locking releases now, not at garbage collection.
            if self._source_handles is not None:
                self._source_handles.release()
            raise

    def _capture_sources(self, backend):
        self.backend = backend
'''

OLD_CAPTURE = '''        self._sources = _source_bytes()
        # Protocol >=3 records object-sharing/reference state.'''
NEW_CAPTURE = '''        self._sources = _source_bytes()
        if self._source_handles is not None and tuple(sorted(self._sources)) != self._source_handles.names:
            raise TectonicsError("source changed during inventory capture")
        # Protocol >=3 records object-sharing/reference state.'''

OLD_VERIFY = '''        # Exact digest-record equality, including membership. All bytes reread.
        if _source_bytes() != self._sources:
            raise TectonicsError("source changed; create a new execution context")'''
NEW_VERIFY = '''        handles = getattr(self, '_source_handles', None)
        if handles is not None:
            # The share-deny-write handles taken before capture are still this context's, on
            # the same files, under the same package directory, with unchanged membership and
            # no link inside: no package source byte can have changed (_SourceHandles.check).
            if not handles.check():
                raise TectonicsError("source changed; create a new execution context")
        # Release mode and non-Windows hosts: exact digest-record equality, including
        # membership. All bytes reread.
        elif _source_bytes() != self._sources:
            raise TectonicsError("source changed; create a new execution context")'''

OLD_CLOSE = '''    def close(self):
        if not self._closed:
            try:
                self.verify()
            finally:
                self._closed = True'''
NEW_CLOSE = '''    def close(self):
        if not self._closed:
            try:
                self.verify()
            finally:
                self._closed = True
                handles = getattr(self, '_source_handles', None)
                if handles is not None:
                    handles.release()'''

OLD_DOC = '''    Strict use hashes the complete current source bytes, comparing the bounded
'''
NEW_DOC = '''    Strict use hashes the complete current source bytes (on Windows outside
    release mode: once at capture, with every source then held against writes
    and the hold confirmed on each check; see _SourceHandles), comparing the bounded
'''


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('source-handles anchor must occur exactly once: ' + old[:60])
    return source.replace(old, new)


def transform(source, *, allow_unreviewed_input=False):
    if '_SourceHandles' in source:
        raise ValueError('source-handles transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('reuse.py input is not the reviewed module; pass allow_unreviewed_input and re-run tests')
    for needed in ('\nimport os\n', '\nimport stat\n', '\nimport weakref\n', '\nfrom pathlib import Path\n'):
        if needed not in source:
            raise ValueError('reuse.py lacks an expected import: ' + needed.strip())
    source = _once(source, ANCHOR_CLASS, HELPER.lstrip('\n') + ANCHOR_CLASS)
    source = _once(source, OLD_DOC, NEW_DOC)
    source = _once(source, OLD_CAPTURE_HEAD, NEW_CAPTURE_HEAD)
    source = _once(source, OLD_CAPTURE, NEW_CAPTURE)
    source = _once(source, OLD_VERIFY, NEW_VERIFY)
    source = _once(source, OLD_CLOSE, NEW_CLOSE)
    return source
