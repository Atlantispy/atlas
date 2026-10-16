"""WP16 pre-advance captures: exact bytes, codec-independent logical identity, fail-closed reads (S2 r6)."""
import copy
import gzip
import importlib.abc
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
TMP = Path(os.environ.get('SO_TMP', HERE))
sys.path[:0] = [str(HERE)]

from atlas_tectonics.resources import WorkBudget
import compact_restart_patch as CRP
import ledger_fresh_interval as LG
import test_ledger_fresh_interval as TL


def legacy_gzip(directory, name, raw):
    """The current gzip-1 writer of private_heat_original_coverage_r1.save_operands (copied)."""
    path = Path(directory)/('preadvance-'+name+'.json.gz')
    with path.open('xb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream,
                                                 mtime=0, compresslevel=1) as packed:
        view = memoryview(raw)
        for start in range(0, len(view), 65536):
            packed.write(view[start:start+65536])
    return dict(path=path.name, raw_bytes=len(raw), gzip_bytes=path.stat().st_size,
                raw_sha256=sha256(raw).hexdigest(), gzip_sha256=sha256(path.read_bytes()).hexdigest())


def read(directory, row):
    """Exact bytes of either receipt form, through the ledger's reader."""
    if row.get('format') == CRP.CAPTURE_FORMAT:
        return LG.captured_bytes(Path(directory)/row['path'], row['container_sha256'],
                                 row['raw_bytes'], row['stored_bytes'])
    return gzip.decompress((Path(directory)/row['path']).read_bytes())


def flip(path, offset_from_end):
    data = bytearray(Path(path).read_bytes())
    data[len(data)-offset_from_end] ^= 1
    os.chmod(path, 0o666)
    Path(path).write_bytes(bytes(data))


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wp16-', dir=TMP)
        self.dir = Path(self.temp.name)
        self.budget = WorkBudget(256 << 20)

    def tearDown(self):
        self.temp.cleanup()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def payload(self, size, seed=7):
        # Compressible JSON-like text with a non-repeating tail across 64 KiB frames.
        line = json.dumps({'cell_id': 'c', 'end_volume_m3': ['0x1f', '0x3'], 'seed': seed}).encode()
        raw = (line*(size//len(line)+1))[:size]
        return raw[:-64]+sha256(raw).hexdigest().encode()

    def test_chunking_is_exact_for_every_block_shape(self):
        raw = self.payload(3*65536+1234)
        shapes = {'one-bytes': [raw],
                  'small-bytes': [raw[i:i+1000] for i in range(0, len(raw), 1000)],
                  'bytearray': [bytearray(raw[:70000]), bytearray(raw[70000:])],
                  'memoryview': [memoryview(raw)[:65536], memoryview(raw)[65536:]],
                  'boundary': [raw[:65536], raw[65536:131072], raw[131072:]]}
        for label, blocks in shapes.items():
            parts = list(CRP._capture_parts(blocks, lambda: None))
            self.assertTrue(all(type(p) is bytes and len(p) <= 65536 for p in parts), label)
            self.assertEqual(b''.join(parts), raw, label)
            (self.dir/label).mkdir()
            row = CRP.capture_operand(self.dir/label, 'mesh', blocks, budget=self.budget, check=lambda: None)
            self.assertEqual((row['raw_bytes'], row['raw_sha256']), (len(raw), sha256(raw).hexdigest()), label)
            self.assertEqual(read(self.dir/label, row), raw, label)

    def test_same_bytes_same_logical_identity_across_formats(self):
        raw = self.payload(200000)
        for name in ('g', 'c'):
            (self.dir/name).mkdir()
        old = legacy_gzip(self.dir/'g', 'bounds', raw)
        new = CRP.capture_operands(self.dir/'c', budget=self.budget, check=lambda: None, bounds=raw)['bounds']
        self.assertEqual((old['raw_bytes'], old['raw_sha256']), (new['raw_bytes'], new['raw_sha256']))
        self.assertLess(new['stored_bytes'], len(raw))
        self.assertEqual(read(self.dir/'g', old), read(self.dir/'c', new))
        self.assertEqual(new['format'], CRP.CAPTURE_FORMAT)
        self.assertNotIn('format', old)

    def test_ledger_reads_both_formats_and_refuses_changes(self):
        bounds = {'cells': [{'cell_id': 'a'}], 'face_intervals': [], 'finite_exchange_intervals': []}
        raw = json.dumps(bounds, sort_keys=True).encode()
        for name in ('g', 'c'):
            (self.dir/name).mkdir()
        old = legacy_gzip(self.dir/'g', 'bounds', raw)
        new = CRP.capture_operands(self.dir/'c', budget=self.budget, check=lambda: None, bounds=raw)['bounds']
        self.assertEqual(LG.capture(self.dir/'g', old), bounds)
        self.assertEqual(LG.capture(self.dir/'c', new), bounds)
        # The receipt's logical pin still binds the capture.
        for field, value in (('raw_sha256', '0'*64), ('raw_bytes', len(raw)+1)):
            with self.assertRaises(LG.LedgerRefused):
                LG.capture(self.dir/'c', dict(new, **{field: value}))
        # The container pin authenticates the file itself.
        with self.assertRaises(ValueError):
            LG.capture(self.dir/'c', dict(new, container_sha256='0'*64))
        # One flipped payload byte (inside the only frame) is refused before decoding.
        flip(self.dir/'c'/new['path'], 200)
        with self.assertRaises(ValueError):
            LG.capture(self.dir/'c', new)

    def test_flipped_byte_in_a_large_capture_refuses(self):
        raw = self.payload(5*65536)
        row = CRP.capture_operands(self.dir, budget=self.budget, check=lambda: None, closed_graph=raw)['closed_graph']
        for offset in (row['stored_bytes']//2, 100, 10):
            path = self.dir/row['path']
            original = path.read_bytes()
            flip(path, offset)
            with self.assertRaises(ValueError, msg=str(offset)):
                read(self.dir, row)
            path.write_bytes(original)
        self.assertEqual(read(self.dir, row), raw)

    def test_exclusive_publication_and_type_refusals(self):
        raw = self.payload(1000)
        CRP.capture_operands(self.dir, budget=self.budget, check=lambda: None, bounds=raw)
        with self.assertRaises(FileExistsError):
            CRP.capture_operands(self.dir, budget=self.budget, check=lambda: None, bounds=raw)
        with self.assertRaises(TypeError):
            CRP.capture_operands(self.dir, budget=self.budget, check=lambda: None, mesh=bytearray(raw))
        with self.assertRaises(TypeError):
            CRP.capture_operand(self.dir, 'mesh', [raw], budget=SimpleNamespace(), check=lambda: None)
        with self.assertRaises(KeyError):
            CRP.capture_operand(self.dir, 'trace', [raw], budget=self.budget, check=lambda: None)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ['preadvance-bounds.capture'])

    def test_cancellation_publishes_nothing(self):
        raw = self.payload(4*65536)
        calls = []

        def check():
            calls.append(1)
            if len(calls) > 6:
                raise KeyboardInterrupt('cancel')
        with self.assertRaises(KeyboardInterrupt):
            CRP.capture_operand(self.dir, 'mesh', [raw], budget=self.budget, check=check)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_backend_is_the_pinned_library(self):
        native = CRP.capture_backend()
        self.assertEqual(native.library_sha256, CRP.CAPTURE_LIBRARY_SHA256)
        self.assertIs(CRP.capture_backend(), native)
        # Writer and reader name the same format and the same pinned library.
        self.assertEqual((LG.CAPTURE_FORMAT, LG.CAPTURE_LIBRARY, LG.CAPTURE_LIBRARY_SHA256),
                         (CRP.CAPTURE_FORMAT, CRP.CAPTURE_LIBRARY, CRP.CAPTURE_LIBRARY_SHA256))

    def test_whole_ledger_identical_for_gzip_and_capture_receipts(self):
        def run(capture, changed=False):
            runs = TL.Runs(self.dir/(('c' if capture else 'g')+('1' if changed else '0')))
            runs.directory.mkdir()
            if capture:
                original = runs.receipt

                def receipt(name, bounds, arrays, **keys):
                    folder, record = original(name, bounds, arrays, **keys)
                    (folder/'preadvance-bounds.json.gz').unlink()
                    raw = json.dumps(bounds, sort_keys=True).encode()
                    record['preadvance_operands']['bounds'] = CRP.capture_operands(
                        folder, budget=self.budget, check=lambda: None, bounds=raw)['bounds']
                    return folder, record
                runs.receipt = receipt
            if not changed:
                return runs.run()
            bounds = copy.deepcopy(runs.bounds)
            bounds['cells'][0]['end_volume_bounds_m3'] = [TL.pair(31), TL.pair(39)]
            runs.replay[('a', 'end')] = TL.row('a', 'end', 31, 39)
            return runs.run(rerun_bounds=bounds)
        for changed, verdict in ((False, 'PASS'), (True, 'PASS')):
            gz, cap = run(False, changed), run(True, changed)
            self.assertEqual(json.dumps(gz, sort_keys=True), json.dumps(cap, sort_keys=True))
            self.assertEqual(gz['verdict'], verdict)
        self.assertEqual(len(gz['heat_inputs']['bounds']['attributed']), 1)

    def test_mixed_ledger_gzip_r9_against_capture_rerun(self):
        # The real first use: r9 keeps its gzip receipt, only the rerun writes captures.
        def run(mixed, changed):
            runs = TL.Runs(self.dir/(('m' if mixed else 'g')+('1' if changed else '0')))
            runs.directory.mkdir()
            if mixed:
                original = runs.receipt

                def receipt(name, bounds, arrays, **keys):
                    folder, record = original(name, bounds, arrays, **keys)
                    if name == 'rerun':
                        (folder/'preadvance-bounds.json.gz').unlink()
                        raw = json.dumps(bounds, sort_keys=True).encode()
                        record['preadvance_operands']['bounds'] = CRP.capture_operands(
                            folder, budget=self.budget, check=lambda: None, bounds=raw)['bounds']
                    return folder, record
                runs.receipt = receipt
            if not changed:
                return runs.run()
            bounds = copy.deepcopy(runs.bounds)
            bounds['cells'][0]['end_volume_bounds_m3'] = [TL.pair(31), TL.pair(39)]
            runs.replay[('a', 'end')] = TL.row('a', 'end', 31, 39)
            return runs.run(rerun_bounds=bounds)
        for changed in (False, True):
            gz, mixed = run(False, changed), run(True, changed)
            self.assertEqual(json.dumps(gz, sort_keys=True), json.dumps(mixed, sort_keys=True))
            self.assertEqual(mixed['verdict'], 'PASS')
        self.assertTrue((self.dir/'m1'/'r9'/'preadvance-bounds.json.gz').is_file())
        self.assertTrue((self.dir/'m1'/'rerun'/'preadvance-bounds.capture').is_file())
        self.assertEqual(len(mixed['heat_inputs']['bounds']['attributed']), 1)

    def test_reader_is_bounded_by_the_receipt_sizes(self):
        raw = self.payload(3*65536+17)
        row = CRP.capture_operands(self.dir, budget=self.budget, check=lambda: None, closed_graph=raw)['closed_graph']
        path = self.dir/row['path']
        got = LG.captured_bytes(path, row['container_sha256'], row['raw_bytes'], row['stored_bytes'])
        self.assertEqual((type(got), bytes(got)), (bytearray, raw))
        for raw_bytes, stored_bytes in ((len(raw)-1, row['stored_bytes']), (len(raw)+1, row['stored_bytes']),
                                        (len(raw), row['stored_bytes']-1)):
            with self.assertRaises(ValueError, msg=(raw_bytes, stored_bytes)):
                LG.captured_bytes(path, row['container_sha256'], raw_bytes, stored_bytes)
        for raw_bytes, stored_bytes in ((None, row['stored_bytes']), (len(raw), 0), (-1, row['stored_bytes']),
                                        (float(len(raw)), row['stored_bytes'])):
            with self.assertRaises(LG.LedgerRefused, msg=(raw_bytes, stored_bytes)):
                LG.captured_bytes(path, row['container_sha256'], raw_bytes, stored_bytes)
        # A receipt whose sizes differ from its capture refuses through the ledger entry too.
        for field, value in (('raw_bytes', len(raw)-1), ('stored_bytes', row['stored_bytes']-1)):
            with self.assertRaises(ValueError, msg=field):
                LG.capture(self.dir, dict(row, **{field: value}))

    def test_missing_capture_reader_refuses_instead_of_crashing(self):
        saved = sys.modules.get('capture_store')
        sys.modules['capture_store'] = None
        try:
            with self.assertRaises(LG.LedgerRefused) as caught:
                LG.captured_bytes(self.dir/'absent.capture', '0'*64, 1, 1)
        finally:
            if saved is None:
                sys.modules.pop('capture_store')
            else:
                sys.modules['capture_store'] = saved
        self.assertIn('composed helpers and runtime source', str(caught.exception))

    def _compact_store(self):
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
        probe = ("import sys\n"
                 "sys.path[:0] = sys.argv[1:]\n"
                 "import importlib.util\n"
                 "if importlib.util.find_spec('capture_store') is not None:\n"
                 "    raise SystemExit('capture_store is on this path: the probe proves nothing')\n"
                 "import compact_restart_patch\n"
                 "print(compact_restart_patch.__file__)\n")
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

    def test_writer_passes_the_explicit_ceilings(self):
        import capture_store
        seen, real = [], capture_store.write_capture

        def recording(*args, **keys):
            seen.append((keys['max_logical_bytes'], keys['max_stored_bytes']))
            return real(*args, **keys)
        capture_store.write_capture = recording
        try:
            CRP.capture_operands(self.dir, budget=self.budget, check=lambda: None, bounds=self.payload(1000))
        finally:
            capture_store.write_capture = real
        self.assertEqual(seen, [(16 << 30, 16 << 30)])
        self.assertEqual(CRP.CAPTURE_MAX_BYTES, 16 << 30)

    def test_run_start_check_imports_nothing_for_other_stores(self):  # r6: the r5 delta's P2
        # A legacy run never loads compact_restart_store (R's driver tests cannot import it), so the
        # check looks the module up instead of importing it, and a non-compact call imports nothing.
        saved = sys.modules.pop('compact_restart_store', None)
        try:
            before = set(sys.modules)
            with self.refusing_loader('compact_restart_store', 'capture_store', 'storage_zstd_backend'):
                for store in (None, object(), SimpleNamespace(scope=object())):
                    self.assertIsNone(CRP.require_capture_route(store), type(store).__name__)
            self.assertEqual(sorted(set(sys.modules)-before), [])
        finally:
            if saved is not None:
                sys.modules['compact_restart_store'] = saved
        self.assertEqual(CRP.require_capture_route(self._compact_store()), CRP.CAPTURE_LIBRARY_SHA256)

    def test_reader_authenticates_the_file_before_allocating(self):  # r6: the r5 delta's P3-a
        import capture_store
        raw = self.payload(2*65536+9)
        row = CRP.capture_operands(self.dir, budget=self.budget, check=lambda: None, bounds=raw)['bounds']
        path, container, stored = self.dir/row['path'], row['container_sha256'], row['stored_bytes']
        sizes, real = [], bytearray

        def spy(*args):
            if args and type(args[0]) is int:
                sizes.append(args[0])
                if args[0] > 16 << 20:
                    raise AssertionError('allocated %d bytes before authenticating the file' % args[0])
            return real(*args)
        LG.bytearray = spy
        try:
            for raw_bytes in (len(raw)-1, len(raw)+1, 1 << 30, 16 << 30):
                with self.assertRaisesRegex(LG.LedgerRefused, 'footer differs', msg=raw_bytes):
                    LG.captured_bytes(path, container, raw_bytes, stored)
            with self.assertRaisesRegex(LG.LedgerRefused, 'container pin'):
                LG.captured_bytes(path, sha256(b'another file').hexdigest(), len(raw), stored)
            self.assertEqual(sizes, [])
            self.assertEqual(bytes(LG.captured_bytes(path, container, len(raw), stored)), raw)
            self.assertEqual(sizes, [len(raw)])
        finally:
            del LG.bytearray
        # Below the format's minimum a receipt refuses before the file is opened.
        low = capture_store.PREAMBLE.size+32+capture_store.FOOTER.size
        for stored_bytes in (1, low-1):
            with self.assertRaisesRegex(LG.LedgerRefused, 'sizes required', msg=stored_bytes):
                LG.captured_bytes(path, container, len(raw), stored_bytes)

    def test_legacy_reads_are_contained_and_bounded(self):  # r6: the r5 delta's P3-c
        bounds = {'cells': [{'cell_id': 'c%d' % i} for i in range(300)], 'face_intervals': [],
                  'finite_exchange_intervals': []}
        raw = json.dumps(bounds, sort_keys=True).encode()
        row = legacy_gzip(self.dir, 'bounds', raw)
        path = self.dir/row['path']
        new = CRP.capture_operands(self.dir, budget=self.budget, check=lambda: None, mesh=raw)['mesh']
        (self.dir/'sub').mkdir()
        # Plain file names only, in both forms: each path below reaches a real file outside 'sub'.
        for receipt in (row, new):
            target = self.dir/receipt['path']
            for name in ('../'+receipt['path'], '..\\'+receipt['path'], str(target.resolve()),
                         target.resolve().as_posix(), 'sub/../../'+receipt['path'], '..', '.', '', None, 7):
                with self.assertRaisesRegex(LG.LedgerRefused, 'plain file name', msg=repr(name)):
                    LG.capture(self.dir/'sub', dict(receipt, path=name))
            self.assertEqual(LG.capture(self.dir, receipt), bounds)
        # A gzip bomb (32 MiB of zeros) against a 10-byte receipt stops at 11 bytes.
        (self.dir/'bomb.json.gz').write_bytes(gzip.compress(bytes(32 << 20), compresslevel=9, mtime=0))
        tracemalloc.start()
        try:
            with self.assertRaisesRegex(LG.LedgerRefused, 'exceeds its receipt raw_bytes'):
                LG.capture(self.dir, dict(path='bomb.json.gz', raw_bytes=10, raw_sha256='0'*64))
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 4 << 20)
        # gzip_bytes must equal the file when present; receipts without it still read.
        for value in (1, row['gzip_bytes']+1, str(row['gzip_bytes']), True):
            with self.assertRaisesRegex(LG.LedgerRefused, 'gzip_bytes differs', msg=repr(value)):
                LG.capture(self.dir, dict(row, gzip_bytes=value))
        self.assertEqual(LG.capture(self.dir, {k: v for k, v in row.items() if k != 'gzip_bytes'}), bounds)
        for value in ('10', -1, LG.CAPTURE_MAX_BYTES+1, None, float(len(raw))):
            with self.assertRaisesRegex(LG.LedgerRefused, 'raw_bytes required', msg=repr(value)):
                LG.legacy_bytes(path, value)
        # The file itself is held to the ceiling: an incompressible operand is larger stored than raw.
        noise = b''.join(sha256(i.to_bytes(4, 'big')).digest() for i in range(2048))
        noisy = legacy_gzip(self.dir, 'mesh', noise)
        saved = LG.CAPTURE_MAX_BYTES
        try:
            LG.CAPTURE_MAX_BYTES = len(noise)
            with self.assertRaisesRegex(LG.LedgerRefused, 'exceeds the ceiling'):
                LG.capture(self.dir, noisy)
        finally:
            LG.CAPTURE_MAX_BYTES = saved
        self.assertEqual(bytes(LG.legacy_bytes(self.dir/noisy['path'], len(noise))), noise)
        # gzip.decompress's rules: members in sequence, zero padding between them, an empty file is empty.
        packed = gzip.compress(raw[:100], mtime=0)+bytes(7)+gzip.compress(raw[100:], compresslevel=1, mtime=0)+bytes(2)
        path.write_bytes(packed)
        self.assertEqual(bytes(LG.legacy_bytes(path, len(raw))), gzip.decompress(packed))
        self.assertEqual(LG.capture(self.dir, dict(row, gzip_bytes=len(packed))), bounds)
        path.write_bytes(b'')
        self.assertEqual((bytes(LG.legacy_bytes(path, 0)), gzip.decompress(b'')), (b'', b''))


if __name__ == '__main__':
    unittest.main()
