"""S2 revision 5: the delta re-review's P2 and P3-a/b/d (T/so/refute/s2/delta-review.txt); writes s2/r5/.

Sources (sha-checked): compact_restart_patch e28331f2, ledger_fresh_interval 17162d30, test_wp16_preadvance 4bc22b32.
- compact_restart_patch: the import-time route check is removed (every workflow process imports this module, and
  find_spec proves presence, not pinning). require_capture_route(store) replaces it: for a CompactRestartStore it
  imports capture_store and storage_zstd_backend (so the selected runtime's Loader runs their pin check) and loads
  the pinned library; both drivers call it before any physical work (two lines each, applied by Runner).
- ledger_fresh_interval: before the output buffer is allocated, raw_bytes and stored_bytes must be at most the
  writer's ceiling (16 GiB), container_sha256 must be 64 lowercase hex, and stored_bytes must equal the file size.
  A truncated or damaged legacy gzip operand refuses (LedgerRefused, REFUSED) instead of exiting as FAIL.
- test_wp16_preadvance: the import-time test is replaced by tests of the run-start check, the compose paths and
  the ledger refusals (test_s2_route_wiring.py, a separate new file, checks the two driver call sites).
"""
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = {'compact_restart_patch.py': 'e28331f2', 'ledger_fresh_interval.py': '17162d30',
           'test_wp16_preadvance.py': '4bc22b32'}

CRP_EDITS = [
    ('import-time check', '''def _capture_route_present():
    """Refuse at import (run start), not after the advance, when the composition lacks the capture route."""
    from importlib.util import find_spec
    missing = [name for name in ('capture_store', 'storage_zstd_backend') if find_spec(name) is None]
    if not CAPTURE_LIBRARY.is_file():
        missing.append(str(CAPTURE_LIBRARY))
    if missing:
        raise ImportError('WP16 pre-advance capture route incomplete: '+', '.join(missing))


_capture_route_present()


def capture_backend():''', '''def capture_backend():'''),
    ('run-start check', '''    return _CAPTURE_BACKEND


def _capture_parts(blocks, check):''', '''    return _CAPTURE_BACKEND


def require_capture_route(store):
    """Refuse at run start, not after the advance, when a compact run cannot write its captures.

    Both callers of inspect_compact_preadvance (fresh_interval_driver.advance_first_interval
    and prepared_interval_driver.advance_prepared_interval) call this before any physical
    work. The two capture modules are imported, not only found, so inside the selected
    runtime its Loader runs their pin check now; capture_backend() then loads the pinned
    library and checks its sha256. Any other store is not checked here, and this module
    itself imports without the capture route, so compositions without it still import.
    Returns the library's sha256 for a compact store, else None.
    """
    from compact_restart_store import is_compact_restart_store
    if not is_compact_restart_store(store):
        return None
    import importlib
    try:
        for name in ('capture_store', 'storage_zstd_backend'):
            importlib.import_module(name)
    except ImportError as error:
        raise ImportError('WP16 pre-advance capture route incomplete: '+str(error)) from error
    return capture_backend().library_sha256


def _capture_parts(blocks, check):'''),
]

LG_EDITS = [
    ('zlib import', 'import sys\nfrom fractions import Fraction\n', 'import sys\nimport zlib\nfrom fractions import Fraction\n'),
    ('ceiling', "CAPTURE_LIBRARY_SHA256 = 'a40c24ad328da37a42c7f69e434c576254f11fde4097cd5de7416f8f78444f28'\n",
     "CAPTURE_LIBRARY_SHA256 = 'a40c24ad328da37a42c7f69e434c576254f11fde4097cd5de7416f8f78444f28'\n"
     "# The writer's explicit ceiling (compact_restart_patch.CAPTURE_MAX_BYTES): a receipt beyond it\n"
     "# refuses before the reader allocates its output buffer.\n"
     "CAPTURE_MAX_BYTES = 16 << 30\n"
     "_HEX = frozenset('0123456789abcdef')\n"),
    ('docstring', '''    The receipt's sizes bound the reader (a larger capture refuses) and size the one output
    buffer, so each operand is held once.''', '''    Before the one output buffer is allocated, the receipt's sizes must be at most the
    writer's ceiling, its container pin must be 64 lowercase hex, and stored_bytes must equal
    the file's size; the reader is then held to raw_bytes, so each operand is held once.'''),
    ('receipt checks', '''    require(type(raw_bytes) is int and type(stored_bytes) is int and raw_bytes >= 0 and stored_bytes > 0,
            'capture receipt sizes required: '+str(path))
    buffer, filled = bytearray(raw_bytes), 0
''', '''    require(type(raw_bytes) is int and type(stored_bytes) is int and 0 <= raw_bytes <= CAPTURE_MAX_BYTES and
            0 < stored_bytes <= CAPTURE_MAX_BYTES,
            'capture receipt sizes required (at most %d bytes): %s' % (CAPTURE_MAX_BYTES, path))
    require(type(container_sha256) is str and len(container_sha256) == 64 and set(container_sha256) <= _HEX,
            'capture receipt container_sha256 required (64 lowercase hex): '+str(path))
    require(Path(path).stat().st_size == stored_bytes, 'pre-advance capture size differs from its receipt: '+str(path))
    buffer, filled = bytearray(raw_bytes), 0
'''),
    ('legacy gzip', '''    else:
        raw = gzip.decompress(Path(directory, operand['path']).read_bytes())
''', '''    else:
        try:
            raw = gzip.decompress(Path(directory, operand['path']).read_bytes())
        except (EOFError, zlib.error) as error:  # a damaged r9 operand is a bad input: REFUSED, not FAIL
            raise LedgerRefused('legacy pre-advance capture is not a whole gzip stream: %s (%s)'
                                % (operand['path'], error)) from None
'''),
]

OLD_TEST = '''    def test_capture_route_is_checked_at_import(self):
        import importlib.util
        real = importlib.util.find_spec
        CRP._capture_route_present()
        for missing in ('capture_store', 'storage_zstd_backend'):
            importlib.util.find_spec = lambda name, *rest, missing=missing: None if name == missing else real(name, *rest)
            try:
                with self.assertRaisesRegex(ImportError, missing):
                    CRP._capture_route_present()
            finally:
                importlib.util.find_spec = real
        library = CRP.CAPTURE_LIBRARY
        CRP.CAPTURE_LIBRARY = self.dir/'wp10_zstd.dll'
        try:
            with self.assertRaisesRegex(ImportError, 'wp10_zstd.dll'):
                CRP._capture_route_present()
        finally:
            CRP.CAPTURE_LIBRARY = library

'''

NEW_TESTS = '''    def _compact_store(self):
        import compact_restart_store
        # Type identity only (is_compact_restart_store is an exact type check); never used as a store.
        return object.__new__(compact_restart_store.CompactRestartStore)

    @contextmanager
    def refusing_loader(self, *names):
        """Like the selected runtime's Finder: each module is found, and refused only when executed."""
        class Refusing(importlib.abc.Loader):
            def create_module(self, spec):
                return None

            def exec_module(self, module):
                raise ImportError('unbound source import: '+module.__name__+'.py')

        class Finder(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                return importlib.util.spec_from_loader(name, Refusing()) if name in names else None
        saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
        finder = Finder()
        sys.meta_path.insert(0, finder)
        try:
            yield
        finally:
            sys.meta_path.remove(finder)
            for name in names:
                sys.modules.pop(name, None)
            sys.modules.update(saved)

    def test_run_start_check_executes_the_capture_imports_for_a_compact_store(self):
        store = self._compact_store()
        self.assertEqual(CRP.require_capture_route(store), CRP.CAPTURE_LIBRARY_SHA256)
        for name in ('capture_store', 'storage_zstd_backend'):
            with self.refusing_loader(name):
                with self.assertRaisesRegex(ImportError, 'capture route incomplete: unbound source import: '+name):
                    CRP.require_capture_route(store)
        self.assertEqual(CRP.require_capture_route(store), CRP.CAPTURE_LIBRARY_SHA256)

    def test_run_start_check_leaves_other_stores_alone(self):
        import compact_restart_store
        subclass = type('Subclass', (compact_restart_store.CompactRestartStore,), {})
        with self.refusing_loader('capture_store', 'storage_zstd_backend'):
            for store in (None, object(), SimpleNamespace(scope=object()), object.__new__(subclass)):
                self.assertIsNone(CRP.require_capture_route(store), type(store).__name__)

    def test_run_start_check_refuses_a_missing_or_changed_library(self):
        store, saved = self._compact_store(), (CRP._CAPTURE_BACKEND, CRP.CAPTURE_LIBRARY)
        try:
            CRP._CAPTURE_BACKEND, CRP.CAPTURE_LIBRARY = None, self.dir/'wp10_zstd.dll'
            with self.assertRaises(FileNotFoundError):
                CRP.require_capture_route(store)
            (self.dir/'wp10_zstd.dll').write_bytes(b'not the pinned library')
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                CRP.require_capture_route(store)
        finally:
            CRP._CAPTURE_BACKEND, CRP.CAPTURE_LIBRARY = saved

    def test_module_imports_over_the_compose_paths_without_the_capture_route(self):
        # integration_regional_workflow imports this module in every workflow process; over the compose paths
        # as they stand today (no capture_store on either) it must still import.
        root = Path(os.environ['SO_R'])
        paths = {'step8-runtime/compose': [root/'compact-geometry-r1', root.parent/'runtime-integration-r1'/'runtime-src',
                                           root],
                 'composed-r2 run roots': [root/'composed-r2'/'helpers', root/'composed-r2'/'src']}
        probe = ("import sys\\n"
                 "sys.path[:0] = sys.argv[1:]\\n"
                 "import importlib.util\\n"
                 "if importlib.util.find_spec('capture_store') is not None:\\n"
                 "    raise SystemExit('capture_store is on this path: the probe proves nothing')\\n"
                 "import compact_restart_patch\\n"
                 "print(compact_restart_patch.__file__)\\n")
        own = Path(CRP.__file__).resolve()
        for label, roots in paths.items():
            done = subprocess.run([sys.executable, '-I', '-B', '-c', probe, str(own.parent), *map(str, roots)],
                                  capture_output=True, text=True, timeout=300, cwd=str(TMP))
            self.assertEqual(done.returncode, 0, label+': '+done.stdout[-400:]+done.stderr[-1200:])
            self.assertEqual(Path(done.stdout.strip()).resolve(), own, label)

    def test_reader_refuses_malformed_receipts_before_allocating(self):
        raw = self.payload(2*65536+5)
        row = CRP.capture_operands(self.dir, budget=self.budget, check=lambda: None, bounds=raw)['bounds']
        path, good = self.dir/row['path'], (row['container_sha256'], row['raw_bytes'], row['stored_bytes'])
        self.assertEqual((LG.CAPTURE_MAX_BYTES, CRP.CAPTURE_MAX_BYTES), (16 << 30, 16 << 30))
        cases = {'raw 2**45': (good[0], 1 << 45, good[2]), 'raw 2**63': (good[0], 1 << 63, good[2]),
                 'stored +1000': (good[0], good[1], good[2]+1000), 'stored over ceiling': (good[0], good[1], (16 << 30)+1),
                 'container None': (None, good[1], good[2]), 'container upper': (good[0].upper(), good[1], good[2]),
                 'container short': (good[0][:63], good[1], good[2]), 'container bytes': (good[0].encode(), good[1], good[2])}
        for label, (container, raw_bytes, stored_bytes) in cases.items():
            with self.assertRaises(LG.LedgerRefused, msg=label):
                LG.captured_bytes(path, container, raw_bytes, stored_bytes)
        # The same refusals through the ledger entry (main reports REFUSED, never FAIL).
        for field, value in (('raw_bytes', 1 << 63), ('stored_bytes', good[2]+1000), ('container_sha256', None)):
            with self.assertRaises(LG.LedgerRefused, msg=field):
                LG.capture(self.dir, dict(row, **{field: value}))
        # The ceiling is the bound itself: a capture exactly at it reads, one byte over refuses.
        saved = LG.CAPTURE_MAX_BYTES
        try:
            LG.CAPTURE_MAX_BYTES = len(raw)
            self.assertEqual(bytes(LG.captured_bytes(path, *good)), raw)
            LG.CAPTURE_MAX_BYTES = len(raw)-1
            with self.assertRaises(LG.LedgerRefused):
                LG.captured_bytes(path, *good)
        finally:
            LG.CAPTURE_MAX_BYTES = saved
        self.assertEqual(bytes(LG.captured_bytes(path, *good)), raw)
        # The stored ceiling binds on its own: an incompressible capture is larger stored than raw.
        noise = b''.join(sha256(i.to_bytes(4, 'big')).digest() for i in range(4096))
        other = CRP.capture_operands(self.dir, budget=self.budget, check=lambda: None, mesh=noise)['mesh']
        args = (self.dir/other['path'], other['container_sha256'], other['raw_bytes'], other['stored_bytes'])
        self.assertGreater(other['stored_bytes'], other['raw_bytes'])
        try:
            LG.CAPTURE_MAX_BYTES = other['raw_bytes']
            with self.assertRaises(LG.LedgerRefused):
                LG.captured_bytes(*args)
        finally:
            LG.CAPTURE_MAX_BYTES = saved
        self.assertEqual(bytes(LG.captured_bytes(*args)), noise)

    def test_damaged_legacy_gzip_refuses(self):
        bounds = {'cells': [{'cell_id': 'c%d' % i} for i in range(300)], 'face_intervals': [],
                  'finite_exchange_intervals': []}
        raw = json.dumps(bounds, sort_keys=True).encode()
        row = legacy_gzip(self.dir, 'bounds', raw)
        path = self.dir/row['path']
        whole = path.read_bytes()
        # Header is 10 bytes (no name, mtime 0); 0x07 starts a final block of the reserved type.
        for label, data in (('truncated', whole[:len(whole)//2]), ('no trailer', whole[:-8]),
                            ('reserved block type', whole[:10]+bytes([7])+whole[11:])):
            path.write_bytes(data)
            with self.assertRaises(LG.LedgerRefused, msg=label):
                LG.capture(self.dir, row)
        path.write_bytes(whole)
        self.assertEqual(LG.capture(self.dir, row), bounds)

'''

TEST_EDITS = [
    ('imports', 'import copy\nimport gzip\nimport json\nimport os\nimport sys\nimport tempfile\nimport unittest\n'
                'from hashlib import sha256\n',
     'import copy\nimport gzip\nimport importlib.abc\nimport importlib.util\nimport json\nimport os\nimport subprocess\n'
     'import sys\nimport tempfile\nimport unittest\nfrom contextlib import contextmanager\nfrom hashlib import sha256\n'),
    ('docstring', '"""WP16 pre-advance captures: exact bytes, codec-independent logical identity, fail-closed reads."""',
     '"""WP16 pre-advance captures: exact bytes, codec-independent logical identity, fail-closed reads (S2 r5)."""'),
    ('old route test', OLD_TEST, NEW_TESTS),
]


def apply(text, edits, label):
    for name, old, new in edits:
        if text.count(old) != 1:
            raise SystemExit('%s/%s: seam found %d times' % (label, name, text.count(old)))
        text = text.replace(old, new)
    return text


def main():
    sources = {}
    for name, short in SOURCES.items():
        data = (HERE/name).read_bytes()
        if hashlib.sha256(data).hexdigest()[:8] != short:
            raise SystemExit('%s is not %s: refusing' % (name, short))
        sources[name] = data.decode('utf8')
    out = {'compact_restart_patch.py': apply(sources['compact_restart_patch.py'], CRP_EDITS, 'CRP'),
           'ledger_fresh_interval.py': apply(sources['ledger_fresh_interval.py'], LG_EDITS, 'LG'),
           'test_wp16_preadvance.py': apply(sources['test_wp16_preadvance.py'], TEST_EDITS, 'test')}
    if '_capture_route_present' in out['compact_restart_patch.py'] or '_capture_route_present' in out['test_wp16_preadvance.py']:
        raise SystemExit('the import-time check is still referenced')
    for name, text in out.items():
        compile(text, name, 'exec')
    target = HERE/'r5'
    target.mkdir(exist_ok=True)
    if any((target/name).exists() for name in out):
        raise SystemExit('r5 sources exist: a new revision is a new folder')
    for name, text in out.items():
        data = text.encode('utf8')
        (target/name).write_bytes(data)
        print('wrote', target/name, hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    sys.exit(main())
