"""Write arms_r8.py from arms_r7.py by exact replacements, each required to match a stated number of times.

    python -B -I mk_arms_r8.py FOLD_DIR

FOLD_DIR holds arms_r7.py; arms_r8.py must not exist yet. Prints the two shas.
"""
from hashlib import sha256
import sys
from pathlib import Path

PARAGRAPH = '''Revision 8 (23 Oct) = revision 7 with the native library record (RF2 condition c, FOLD.md §14):
- child's arm.json gains native: sys.exec_prefix, the path RF2's _ASSEMBLY_MPFR_PATH is joined to (exec_prefix
  /Lib/site-packages/gmpy2.libs/libmpfr-6.dll) and {path: sha256} of each module this process has loaded whose file
  name starts libmpfr or libgmp (K32EnumProcessModules, GetModuleFileNameW). It is read after the control call, the
  audit, the observer and the digests are finished, and the sha256 is the untapped one, so no record changes.
- The workers' observer is wobs2/sitecustomize.py, which writes the same record into each worker's exit snapshot;
  each workers row carries it (None for a worker that left no snapshot).
v27/mpfr_same.py judges the records across the arms and their workers.

'''

NATIVE = '''def _native_modules():
    """r8: {path: sha256} of each module this process has loaded whose file name starts libmpfr or libgmp."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)   # a private handle: no shared argtypes change
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32EnumProcessModules.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD))
    k32.K32EnumProcessModules.restype = wintypes.BOOL
    k32.GetModuleFileNameW.argtypes = (wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
    k32.GetModuleFileNameW.restype = wintypes.DWORD
    process, size, needed = k32.GetCurrentProcess(), 1024, wintypes.DWORD()
    while True:
        handles = (wintypes.HMODULE * size)()
        if not k32.K32EnumProcessModules(process, handles, ctypes.sizeof(handles), ctypes.byref(needed)):
            raise OSError(ctypes.get_last_error(), 'K32EnumProcessModules')
        if needed.value <= ctypes.sizeof(handles):
            break
        size = needed.value // ctypes.sizeof(wintypes.HMODULE) + 64
    found, buffer = {}, ctypes.create_unicode_buffer(32768)
    for handle in handles[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
        if not k32.GetModuleFileNameW(handle, buffer, len(buffer)):
            raise OSError(ctypes.get_last_error(), 'GetModuleFileNameW')
        if os.path.basename(buffer.value).lower().startswith(('libmpfr', 'libgmp')):
            found[buffer.value] = _sha(Path(buffer.value).read_bytes())
    return found


def _native_record():
    """r8 (RF2 condition c): the GMP and MPFR libraries this process loaded, and where RF2 expects MPFR."""
    record = dict(exec_prefix=sys.exec_prefix, expected_mpfr=os.path.join(
        sys.exec_prefix, 'Lib', 'site-packages', 'gmpy2.libs', 'libmpfr-6.dll'))
    try:
        record['modules'] = _native_modules()
    except Exception as error:   # recorded; v27/mpfr_same.py then fails this arm
        record['error'] = '%s: %s' % (type(error).__name__, str(error)[:300])
    return record


def child(layout, out_dir, reference=None):
'''

EDITS = [
    ('"""R1 fold parity arms, revision 7 (', '"""R1 fold parity arms, revision 8 (', 1),
    ('  python -B arms_r7.py ', '  python -B arms_r8.py ', 3),
    ('Revision 7 (23 Oct) = revision 6', PARAGRAPH + 'Revision 7 (23 Oct) = revision 6', 1),
    ("OBS_DIR = Path(__file__).resolve().parent/'wobs'            # sitecustomize.py: the worker observer",
     "OBS_DIR = Path(__file__).resolve().parent/'wobs2'           # sitecustomize.py: the worker observer r2", 1),
    ('def child(layout, out_dir, reference=None):\n', NATIVE, 1),
    ("                  control_seconds=result.get('elapsed_seconds'), gmp=_gmp_record(),\n",
     "                  control_seconds=result.get('elapsed_seconds'), gmp=_gmp_record(), native=_native_record(),\n",
     1),
    ("                   modules=None if snapshot is None else len(snapshot['modules']))\n",
     "                   modules=None if snapshot is None else len(snapshot['modules']),\n"
     "                   native=None if snapshot is None else snapshot.get('native'))   # r8\n", 1),
]


def main(argv):
    if len(argv) != 1:
        raise SystemExit(__doc__)
    fold = Path(argv[0])
    source, target = fold/'arms_r7.py', fold/'arms_r8.py'
    if target.exists():
        raise SystemExit('%s exists' % target)
    text = source.read_text(encoding='utf-8')
    for old, new, count in EDITS:
        found = text.count(old)
        if found != count:
            raise SystemExit('expected %d of %r, found %d' % (count, old[:60], found))
        text = text.replace(old, new)
    with open(target, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    for path in (source, target):
        print(sha256(path.read_bytes()).hexdigest(), path.name)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
