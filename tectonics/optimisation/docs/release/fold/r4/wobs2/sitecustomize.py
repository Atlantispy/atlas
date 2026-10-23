"""Worker observer r2 for the R1 fold parity arms (arms_r8.py) = wobs/sitecustomize.py with one addition (RF2
condition c, 23 Oct): at a normal exit, after the worker's work, the snapshot also records the GMP and MPFR native
libraries the process has loaded (each module whose file name starts libmpfr or libgmp, from K32EnumProcessModules
and GetModuleFileNameW, with the file's sha256), sys.exec_prefix, and the path RF2's _ASSEMBLY_MPFR_PATH is joined
to. The log is silenced before that record, so ctypes, imported for it at exit, leaves no line: the log and the
module list are what r1 writes. Only the snapshot's own thread is silenced; an import by any other thread is logged
as in r1. A worker the pool kills leaves no snapshot, so no record (arms_r8 counts them).

Active only in a heat worker (argv `<file> worker`) whose environment names RM_FOLD_WORKER_OBS, which arms_r8.py sets
for the control call in every arm. It reads module state and writes two files; it changes nothing a worker computes.
- w<pid>.log, line by line as it happens, so a worker the pool ends by force still leaves its list:
  's <pid>' when the observer starts; 'f <name>' for every module the import system looks for (a finder placed first
  in sys.meta_path that only writes the name and declines, so importlib.import_module is seen as well as import
  statements); 'i <name>' for every audit 'import' event.
- w<pid>.json at a normal exit: every sys.modules entry with its __file__, sys.path, the compiled-dot seal facts
  (the bare module's __file__ and _H3_SEAL, the file's sha256, the certification kernel's _H3_SHA256) and the native
  record, for arms_r8 to judge.
"""
import os
import sys

_DIR = os.environ.get('RM_FOLD_WORKER_OBS')
if _DIR and sys.argv[1:] == ['worker']:
    from _thread import get_ident as _ident   # already loaded by the import system: no new module, no log line
    import atexit
    import json

    _PID = os.getpid()
    _LOG = open(os.path.join(_DIR, 'w%d.log' % _PID), 'x', encoding='utf8', buffering=1)
    _LOG.write('s %d\n' % _PID)
    _QUIET = []   # r2: the snapshot's thread, once it starts, so the native record's own imports write nothing

    def _hook(event, args):
        if event == 'import' and args and isinstance(args[0], str) and _ident() not in _QUIET:
            _LOG.write('i ' + args[0] + '\n')
    sys.addaudithook(_hook)

    class _Names:
        """Writes each name the import system looks for, then declines, so the next finder answers as before."""

        @staticmethod
        def find_spec(name, path=None, target=None):
            if _ident() not in _QUIET:
                _LOG.write('f ' + name + '\n')
            return None

        @staticmethod
        def invalidate_caches():
            pass
    sys.meta_path.insert(0, _Names)

    def _native(sha256):
        """r2: {path: sha256} of each loaded module whose file name starts libmpfr or libgmp."""
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
            length = k32.GetModuleFileNameW(handle, buffer, len(buffer))
            if not length:
                raise OSError(ctypes.get_last_error(), 'GetModuleFileNameW')
            path = buffer.value
            if os.path.basename(path).lower().startswith(('libmpfr', 'libgmp')):
                with open(path, 'rb') as handle_file:
                    found[path] = sha256(handle_file.read()).hexdigest()
        return found

    def _snapshot():
        from hashlib import sha256
        modules = {name: getattr(module, '__file__', None) for name, module in list(sys.modules.items())}
        ck = sys.modules.get('atlas_tectonics._private.private_heat_certification_kernel_r1')
        h3 = sys.modules.get('private_heat_compiled_dot_r1')
        facts = None
        if h3 is not None:
            path = getattr(h3, '__file__', None)
            try:
                with open(path, 'rb') as handle:
                    digest = sha256(handle.read()).hexdigest()
            except (OSError, TypeError):
                digest = None
            seal = getattr(h3, '_H3_SEAL', None)
            facts = dict(file=path, sha256=digest, seal=list(seal) if isinstance(seal, tuple) else repr(seal),
                         pin=getattr(ck, '_H3_SHA256', None))
        finder_first = bool(sys.meta_path) and sys.meta_path[0] is _Names
        _QUIET.append(_ident())
        native = dict(exec_prefix=sys.exec_prefix,
                      expected_mpfr=os.path.join(sys.exec_prefix, 'Lib', 'site-packages', 'gmpy2.libs',
                                                 'libmpfr-6.dll'))
        try:
            native['modules'] = _native(sha256)
        except Exception as error:   # recorded; arms_r8's check then fails this worker
            native['error'] = '%s: %s' % (type(error).__name__, str(error)[:300])
        with open(os.path.join(_DIR, 'w%d.json' % _PID), 'x', encoding='utf8') as handle:
            json.dump(dict(pid=_PID, argv=sys.argv, modules=modules, h3=facts, path=sys.path,
                           finder_first=finder_first, native=native), handle)
    atexit.register(_snapshot)
