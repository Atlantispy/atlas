"""Admission option 1a(i) (coordinator, 16 Oct 2026): hold share-deny-write handles on every package source.

Source transform of atlas_tectonics/reuse.py. ExecutionContext.verify_boundary re-reads and
re-hashes EVERY package source on every call (about 30% of the fresh admission's initial
metrics: 3,876 calls, 1.9M stat calls). The guarantee it gives is that no package source has
changed since capture. This transform keeps that guarantee exactly, by a different mechanism:

- At capture (non-release modes, Windows only), the context opens every package `.py` with
  CreateFileW(GENERIC_READ, FILE_SHARE_READ) BEFORE the captured hash is taken. While those
  handles are held the OS refuses any write, truncation, rename or delete of those files by
  any process, and any rename of a directory that contains them. If a handle cannot be
  taken (for example another process holds the file open for writing), capture refuses.
- verify_boundary then checks, on EVERY call, that the handles are still held by this context
  and that the package's source membership (relative names) is unchanged (so an added or
  removed source file is still refused). It no longer re-reads the bytes, which cannot have
  changed. The callable/default inventory re-walk stays on every call, unchanged.
- The handles are released on every exit path: close() (also via __exit__), garbage
  collection or interpreter exit (weakref.finalize registered immediately after locking),
  and a capture that fails after locking. Release is idempotent.
- Release mode (shared captures across contexts) and non-Windows hosts keep the original
  byte re-hash path unchanged.
Evidence: G/scripts/test_source_handles.py (OS refusals, reopen refusal, release on every exit
path, unchanged acceptance and timing).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '96e2092c2e056cc4f6bfb5caef70818567f59af54b4cdfc7d101bdea090e10fe': 'RC1 composed-r1 runtime-src',
}

ANCHOR_CLASS = 'class ExecutionContext:\n'
HELPER = '''
def _source_names():
    """Relative names of the package sources (the membership _source_bytes checks)."""
    root = Path(__file__).parent
    root_parts = len(root.parts)
    names = []
    for p in root.rglob("*.py"):
        if len(names) >= _SOURCE_FILES:
            raise TectonicsError("execution source inventory exceeds context budget")
        names.append('/'.join(p.parts[root_parts:]))
    return tuple(sorted(names))


class _SourceHandles:
    """Share-deny-write handles on every package source (Windows), released exactly once."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._kernel32 = kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel32.CreateFileW
        create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        create.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        invalid = wintypes.HANDLE(-1).value
        self.handles, self.held = [], True
        root = Path(__file__).parent
        root_parts = len(root.parts)
        names = []
        try:
            for p in sorted(root.rglob("*.py")):
                if len(names) >= _SOURCE_FILES:
                    raise TectonicsError("execution source inventory exceeds context budget")
                # GENERIC_READ, FILE_SHARE_READ only, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL.
                handle = create(str(p), 0x80000000, 0x00000001, None, 3, 0x80, None)
                if handle is None or handle == invalid:
                    raise TectonicsError("a package source cannot be held against writes: "
                                         + '/'.join(p.parts[root_parts:]))
                self.handles.append(handle)
                names.append('/'.join(p.parts[root_parts:]))
        except BaseException:
            self.release()
            raise
        self.names = tuple(sorted(names))

    def release(self):
        handles, self.handles, self.held = self.handles, [], False
        for handle in handles:
            self._kernel32.CloseHandle(handle)


def _release_source_handles(holder):
    holder.release()


'''

OLD_CAPTURE = '''        self._sources = _source_bytes()
        # Protocol >=3 records object-sharing/reference state.'''
NEW_CAPTURE = '''        self._source_handles = None
        if os.name == 'nt' and getattr(self, '_mode', None) != 'release':
            # Taken BEFORE the captured hash: from here no process can write, rename or
            # delete a package source until this context releases the handles.
            self._source_handles = _SourceHandles()
            self._source_finalizer = weakref.finalize(self, _release_source_handles, self._source_handles)
        try:
            self._sources = _source_bytes()
            if self._source_handles is not None and tuple(sorted(self._sources)) != self._source_handles.names:
                raise TectonicsError("source changed during inventory capture")
        except BaseException:
            if self._source_handles is not None:
                self._source_handles.release()
            raise
        # Protocol >=3 records object-sharing/reference state.'''

OLD_VERIFY = '''        # Exact digest-record equality, including membership. All bytes reread.
        if _source_bytes() != self._sources:
            raise TectonicsError("source changed; create a new execution context")'''
NEW_VERIFY = '''        handles = getattr(self, '_source_handles', None)
        if handles is not None:
            # The share-deny-write handles taken before capture are still held, so no
            # package source byte can have changed; membership is still checked live.
            if not handles.held or _source_names() != handles.names:
                raise TectonicsError("source changed; create a new execution context")
        # Exact digest-record equality, including membership. All bytes reread.
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

OLD_VERIFY_FAIL = '''        self._closed = False
        self._immutable = {}        # private: deeply immutable constants' normalised forms (see verify)
        self.verify_boundary()'''
NEW_VERIFY_FAIL = '''        self._closed = False
        self._immutable = {}        # private: deeply immutable constants' normalised forms (see verify)
        try:
            self.verify_boundary()
        except BaseException:
            if self._source_handles is not None:
                self._source_handles.release()
            raise'''


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('source-handles anchor must occur exactly once: ' + old[:60])
    return source.replace(old, new)


def transform(source, *, allow_unreviewed_input=False):
    if '_SourceHandles' in source:
        raise ValueError('source-handles transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('reuse.py input is not the reviewed module; pass allow_unreviewed_input and re-run tests')
    for needed in ('\nimport os\n', '\nimport weakref\n', '\nfrom pathlib import Path\n'):
        if needed not in source:
            raise ValueError('reuse.py lacks an expected import: ' + needed.strip())
    source = _once(source, ANCHOR_CLASS, HELPER.lstrip('\n') + ANCHOR_CLASS)
    source = _once(source, OLD_CAPTURE, NEW_CAPTURE)
    source = _once(source, OLD_VERIFY_FAIL, NEW_VERIFY_FAIL)
    source = _once(source, OLD_VERIFY, NEW_VERIFY)
    source = _once(source, OLD_CLOSE, NEW_CLOSE)
    return source
