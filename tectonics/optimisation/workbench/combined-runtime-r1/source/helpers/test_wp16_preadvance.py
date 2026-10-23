"""WP16 pre-advance captures: exact bytes, codec-independent logical identity, fail-closed reads."""
import ast
import copy
import gzip
import importlib.abc
import importlib.util
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
import weakref
import zlib
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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


@contextmanager
def unopened():
    """The ledger opens no file meanwhile: a malformed receipt refuses on its own fields and the stat size."""
    def refuse(*args, **keys):
        raise AssertionError('the ledger opened a file for a malformed receipt: %r' % (args[:1],))
    assert 'open' not in vars(LG)
    LG.open = refuse
    try:
        yield
    finally:
        del LG.open


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

    def test_duplicated_capture_constants_agree(self):
        # Review r1 L3: the ledger keeps its own copies so it stays standalone; every CAPTURE_* name it
        # defines must also be the writer's, with an equal value of the same type.
        mine = {name for name in vars(LG) if name.startswith('CAPTURE_')}
        self.assertEqual(mine, {'CAPTURE_FORMAT', 'CAPTURE_LIBRARY_KEY', 'CAPTURE_LIBRARY', 'CAPTURE_LIBRARY_SHA256',
                                'CAPTURE_MAX_BYTES'})
        self.assertLessEqual(mine, set(vars(CRP)))
        for name in sorted(mine):
            ours, theirs = getattr(LG, name), getattr(CRP, name)
            self.assertIs(type(ours), type(theirs), name)
            self.assertEqual(ours, theirs, name)
        self.assertIsNotNone(LG.CAPTURE_LIBRARY)

    def test_library_is_found_by_its_task_key(self):
        # Review r1 L4: no machine path is written in either module; the library is the one file its
        # task-relative key names under an ancestor of the module, and an ambiguous or absent key is None.
        for module in (CRP, LG):
            located = module.task_file(module.CAPTURE_LIBRARY_KEY)
            self.assertEqual(module.CAPTURE_LIBRARY, located, module.__name__)
            self.assertIn(located.parents[len(Path(module.CAPTURE_LIBRARY_KEY).parts)-1],
                          Path(module.__file__).resolve().parents, module.__name__)
            self.assertEqual(located.as_posix()[-len(module.CAPTURE_LIBRARY_KEY):], module.CAPTURE_LIBRARY_KEY)
            tree = ast.parse(Path(module.__file__).read_text(encoding='utf8'))
            texts = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and type(node.value) is str]
            machine = [text for text in texts if re.search(r'(^|[^A-Za-z0-9])[A-Za-z]:[\\/]|^[\\/]{2}|/Users/|/home/', text)]
            self.assertEqual(machine, [], module.__name__)
        for module in (CRP, LG):
            tree = self.dir/module.__name__
            for folder in ('a/x', 'a/b/c', 'a/k', 'a/b/k'):
                (tree/folder).mkdir(parents=True)
            (tree/'a/k/lib.bin').write_bytes(b'1')
            self.assertEqual(module.task_file('k/lib.bin', tree/'a/x'), (tree/'a/k/lib.bin').resolve())
            self.assertEqual(module.task_file('k/lib.bin', tree/'a/k'), (tree/'a/k/lib.bin').resolve())
            (tree/'a/b/k/lib.bin').write_bytes(b'2')
            self.assertIsNone(module.task_file('k/lib.bin', tree/'a/b/c'), 'two ancestors hold the key')
            self.assertIsNone(module.task_file('k/absent.bin', tree/'a/b/c'), 'no ancestor holds the key')
            (tree/'a/b/c/k').mkdir()
            self.assertIsNone(module.task_file('k', tree/'a/b/c'), 'a folder is not the file')

    def test_refused_ancestor_probe_is_not_a_holder(self):
        # Storage review of r11, item 1: before Python 3.14 is_file() re-raises errors other than
        # not-found, so an access-restricted ancestor would stop either module importing on every route.
        # A probe that raises counts as not holding the key: the exactly-one rule holds over the probes that
        # answer, and a lone holder behind a refused probe gives None, so the capture route refuses at use.
        is_file, refused = Path.is_file, set()

        def probe(path):
            if path in refused:
                raise PermissionError(13, 'access is denied', str(path))
            return is_file(path)

        def refuse_all(path):
            raise PermissionError(13, 'access is denied', str(path))

        for module in (CRP, LG):
            tree = self.dir/('refused-'+module.__name__)
            for folder in ('a/k', 'a/b/k', 'a/b/c'):
                (tree/folder).mkdir(parents=True)
            (tree/'a/k/lib.bin').write_bytes(b'1')
            (tree/'a/b/k/lib.bin').write_bytes(b'2')
            outer, inner = (tree/'a/k/lib.bin').resolve(), (tree/'a/b/k/lib.bin').resolve()
            with mock.patch.object(Path, 'is_file', probe):
                refused.add(inner)
                self.assertEqual(module.task_file('k/lib.bin', tree/'a/b/c'), outer, module.__name__)
                refused.add(outer)
                self.assertIsNone(module.task_file('k/lib.bin', tree/'a/b/c'), module.__name__)
                refused.discard(inner)
                self.assertEqual(module.task_file('k/lib.bin', tree/'a/b/c'), inner, module.__name__)
                refused.clear()
                self.assertIsNone(module.task_file('k/lib.bin', tree/'a/b/c'), 'two ancestors hold the key')
            # The import-time lookup itself, re-executed in a fresh copy of the module: every probe refused
            # gives CAPTURE_LIBRARY None, never an exception at import.
            with mock.patch.object(Path, 'is_file', refuse_all):
                self.assertIsNone(module.task_file(module.CAPTURE_LIBRARY_KEY), module.__name__)
                spec = importlib.util.spec_from_file_location('refused_import_'+module.__name__, module.__file__)
                fresh = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(fresh)
            self.assertIsNone(fresh.CAPTURE_LIBRARY, module.__name__)
            self.assertIs(Path.is_file, is_file)

    def test_capture_parts_releases_each_block_before_the_next(self):
        # Storage review of r12: a large block and its view are released before the next block is
        # produced, so the unbooked hold is one item and one 64 KiB slice copy, not two items.
        class Big(bytearray):
            pass

        refs, size = [], 3*CRP.CAPTURE_CHUNK+5

        def blocks():
            for index in range(3):
                if refs:
                    self.assertIsNone(refs[-1](), 'block %d is still held' % (index-1))
                holder = [Big(bytes([index])*size)]
                refs.append(weakref.ref(holder[0]))
                yield holder.pop()

        parts = list(CRP._capture_parts(blocks(), lambda: None))
        self.assertTrue(all(type(p) is bytes and len(p) <= CRP.CAPTURE_CHUNK for p in parts))
        self.assertEqual(b''.join(parts), b''.join(bytes([index])*size for index in range(3)))
        self.assertEqual(len(refs), 3)

    def test_capture_parts_refuses_wide_or_shaped_items(self):
        # Cold review of r12: a view counts items, so only one-dimensional single-byte buffers keep every
        # part to at most 64 KiB of exact bytes; anything else is refused before a part is produced.
        import array
        for label, block in (('wide', array.array('I', range(70000))), ('wide-small', array.array('I', [1])),
                             ('shaped', memoryview(bytes(16)).cast('B', (4, 4)))):
            with self.subTest(label), self.assertRaises(TypeError):
                list(CRP._capture_parts([block], lambda: None))

    def test_folded_key_finds_the_package_copy(self):
        # The fold's one decision for this literal: retarget the task key to the package key. The same
        # rule then finds the library carried inside the package, and nothing else.
        package_key = 'atlas_tectonics/_private/native/wp10_zstd.dll'
        private = self.dir/'folded'/'atlas_tectonics'/'_private'
        (private/'native').mkdir(parents=True)
        shutil.copyfile(CRP.CAPTURE_LIBRARY, private/'native'/'wp10_zstd.dll')
        text = Path(CRP.__file__).read_text(encoding='utf8')
        old = "CAPTURE_LIBRARY_KEY = ('fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/'\n" \
              "                       'resumability-r1/compact-geometry-r1/native/wp10_zstd.dll')\n"
        self.assertEqual(text.count(old), 1)
        (private/'compact_restart_patch.py').write_text(text.replace(old, 'CAPTURE_LIBRARY_KEY = %r\n' % package_key),
                                                        encoding='utf8')
        # A child process loads the copied library, so this process never holds the temporary file open.
        import storage_zstd_backend
        probe = ("import importlib.util, json, sys\n"
                 "sys.path[:0] = [sys.argv[2]]\n"
                 "spec = importlib.util.spec_from_file_location('folded_capture_probe', sys.argv[1])\n"
                 "folded = importlib.util.module_from_spec(spec)\n"
                 "spec.loader.exec_module(folded)\n"
                 "print(json.dumps([str(folded.CAPTURE_LIBRARY), folded.capture_backend().library_sha256,\n"
                 "                  folded.task_file(folded.CAPTURE_LIBRARY_KEY, sys.argv[3])]))\n")
        done = subprocess.run([sys.executable, '-B', '-c', probe, str(private/'compact_restart_patch.py'),
                               str(Path(storage_zstd_backend.__file__).resolve().parent), str(self.dir)],
                              capture_output=True, text=True, timeout=300, cwd=str(self.dir))
        self.assertEqual(done.returncode, 0, done.stdout[-400:]+done.stderr[-1200:])
        library, digest, elsewhere = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(Path(library), (private/'native'/'wp10_zstd.dll').resolve())
        self.assertEqual(digest, CRP.CAPTURE_LIBRARY_SHA256)
        self.assertIsNone(elsewhere)

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
            # A key no single ancestor holds leaves the library unnamed: refused, never guessed.
            CRP._CAPTURE_BACKEND, CRP.CAPTURE_LIBRARY = None, None
            with self.assertRaisesRegex(FileNotFoundError, 'not under exactly one ancestor'):
                CRP.require_capture_route(store)
        finally:
            CRP._CAPTURE_BACKEND, CRP.CAPTURE_LIBRARY = saved
        saved = LG.CAPTURE_LIBRARY
        try:
            LG.CAPTURE_LIBRARY = None
            with self.assertRaisesRegex(LG.LedgerRefused, 'not under exactly one ancestor'):
                LG.captured_bytes(self.dir/'absent.capture', '0'*64, 1, 1)
        finally:
            LG.CAPTURE_LIBRARY = saved

    def test_run_start_check_refuses_an_unresolved_compact_store(self):
        # Review r1 M1 (fold mutant P20-M1, EXPECTED-FAIL against r9): a compact store whose predicate cannot
        # be resolved refuses. r9 looked the store module up by name and returned None for both cases below.
        # A class of the same name from another copy of the module (a missed fold rewrite loads one):
        twin = type('CompactRestartStore', (), {'__module__': 'atlas_tectonics._private.compact_restart_store'})
        with self.refusing_loader('capture_store', 'storage_zstd_backend'):
            with self.assertRaisesRegex(ValueError, 'not the loaded CompactRestartStore'):
                CRP.require_capture_route(object.__new__(twin))
        # The compact store module not importable under the name this module imports (a fold that
        # qualified the store but not this import, or a missing module):
        store = self._compact_store()
        with self.refusing_loader('compact_restart_store'):
            with self.assertRaisesRegex(ImportError, 'compact store whose module is not importable'):
                CRP.require_capture_route(store)
        saved = sys.modules.pop('compact_restart_store')
        sys.modules['compact_restart_store'] = None
        try:
            with self.assertRaisesRegex(ImportError, 'compact store whose module is not importable'):
                CRP.require_capture_route(store)
        finally:
            sys.modules['compact_restart_store'] = saved
        self.assertEqual(CRP.require_capture_route(store), CRP.CAPTURE_LIBRARY_SHA256)

    def test_run_start_check_resolves_the_store_predicate_by_import(self):
        # Review r1 M1: no module-name string lookup that a fold could leave unqualified; import statements
        # (which import rewriting covers), the store's reached only after its class names the compact store.
        tree = ast.parse(Path(CRP.__file__).read_text(encoding='utf8'))
        route = next(node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name == 'require_capture_route')
        nodes = list(ast.walk(route))
        self.assertEqual([node for node in nodes if isinstance(node, ast.Attribute) and node.attr == 'modules'], [])
        modules = {'compact_restart_store', 'capture_store', 'storage_zstd_backend'}
        self.assertEqual([node.value for node in nodes if isinstance(node, ast.Constant) and node.value in modules], [])
        self.assertEqual([node.id for node in nodes if isinstance(node, ast.Name) and node.id in ('importlib', '__import__')],
                         [])
        found = [[alias.name for alias in node.names] for node in nodes
                 if isinstance(node, ast.ImportFrom) and node.module == 'compact_restart_store']
        self.assertEqual(found, [['is_compact_restart_store']])
        # The capture modules likewise (refuter r11): plain import statements, each once.
        found = [alias.name for node in nodes if isinstance(node, ast.Import) for alias in node.names]
        self.assertEqual(found, ['capture_store', 'storage_zstd_backend'])

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
        # Each refuses at its own check, before the file is opened (the hash pass would refuse later).
        expected = dict.fromkeys(('raw 2**45', 'raw 2**63', 'stored over ceiling'), 'capture receipt sizes required')
        expected.update(dict.fromkeys(('container None', 'container upper', 'container short', 'container bytes'),
                                      r'container_sha256 required \(64 lowercase hex\)'))
        expected['stored +1000'] = 'pre-advance capture size differs from its receipt'
        self.assertEqual(set(expected), set(cases))
        with unopened():
            for label, (container, raw_bytes, stored_bytes) in cases.items():
                with self.assertRaisesRegex(LG.LedgerRefused, expected[label], msg=label):
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
        # With no gzip_bytes nothing else sees a missing end; the reader itself requires a whole stream.
        for label, data in (('truncated', whole[:len(whole)//2]), ('no trailer', whole[:-8])):
            path.write_bytes(data)
            with self.assertRaisesRegex(LG.LedgerRefused, 'not a whole gzip stream', msg=label):
                LG.legacy_bytes(path, len(raw))
        path.write_bytes(whole)
        self.assertEqual(bytes(LG.legacy_bytes(path, len(raw))), raw)
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

    def test_run_start_check_imports_nothing_for_other_stores(self):
        # A legacy run never loads compact_restart_store (R's driver tests cannot import it), so the
        # check reads the store's own class first, and a non-compact call imports nothing.
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

    def test_reader_authenticates_the_file_before_allocating(self):
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

    def test_legacy_reads_are_contained_and_bounded(self):
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

    def test_legacy_reader_streams_the_file(self):
        # A large file named by a legacy receipt costs its 1 MiB read blocks, not its size.
        noise = random.Random(7).randbytes(24 << 20)
        (self.dir/'big.json.gz').write_bytes(gzip.compress(noise, compresslevel=0, mtime=0))
        (self.dir/'unrelated.bin').write_bytes(noise)
        del noise
        tracemalloc.start()
        try:
            with self.assertRaisesRegex(LG.LedgerRefused, 'exceeds its receipt raw_bytes'):
                LG.legacy_bytes(self.dir/'big.json.gz', 10)
            with self.assertRaisesRegex(LG.LedgerRefused, 'not a whole gzip stream'):
                LG.legacy_bytes(self.dir/'unrelated.bin', 1 << 30)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 4 << 20)
        # Members, headers and zero padding may span the read blocks; the result is still gzip.decompress's.
        source = random.Random(8).randbytes(3 << 20)
        first = gzip.compress(source[:900000], compresslevel=0, mtime=0)
        second = gzip.compress(source[900000:], compresslevel=1, mtime=0)
        third = gzip.compress(source[:5000], mtime=0)
        self.assertLess(len(first), (1 << 20)-5)
        path = self.dir/'blocks.json.gz'
        for label, packed in (
                ('header across a block', first+bytes((1 << 20)-5-len(first))+second),
                ('padding across a block', first+bytes((1 << 20)+50-len(first))+second+third),
                ('trailer across a block', first+bytes((1 << 20)+4-len(first)-len(third))+third+second+bytes(3))):
            path.write_bytes(packed)
            expected = gzip.decompress(packed)
            self.assertEqual(bytes(LG.legacy_bytes(path, len(expected))), expected, msg=label)
            with self.assertRaisesRegex(LG.LedgerRefused, 'exceeds its receipt raw_bytes', msg=label):
                LG.legacy_bytes(path, len(expected)-1)
        # Zero padding follows a member; it never starts the file (gzip.decompress refuses that too).
        packed = bytes(5)+first
        with self.assertRaises(gzip.BadGzipFile):
            gzip.decompress(packed)
        path.write_bytes(packed)
        with self.assertRaisesRegex(LG.LedgerRefused, 'not a whole gzip stream'):
            LG.legacy_bytes(path, 900000)
        # A whole member followed by part of another is not a whole stream, even across a block.
        packed = first+bytes((1 << 20)-len(first))+second[:len(second)//2]
        path.write_bytes(packed)
        with self.assertRaisesRegex(LG.LedgerRefused, 'not a whole gzip stream'):
            LG.legacy_bytes(path, len(source))

    def test_footer_may_span_the_last_two_read_blocks(self):
        import capture_store
        footer = capture_store.FOOTER
        for extra in (0, 1, 40, footer.size-1, footer.size, footer.size+1, (1 << 20)-1):
            data = bytes((1 << 20)+extra-footer.size)+footer.pack(b'F', 0, 12345, bytes(32), bytes(32))
            path = self.dir/('footer-%d.bin' % extra)
            path.write_bytes(data)
            pin = sha256(data).hexdigest()
            LG._container_pinned(path, pin, 12345, len(data), footer)
            with self.assertRaisesRegex(LG.LedgerRefused, 'footer differs', msg=extra):
                LG._container_pinned(path, pin, 12346, len(data), footer)

    def test_legacy_reader_checks_the_size_it_read(self):
        # The file is held to its size when the read began: a growing file stops at the first read block
        # past that size, and a shrinking one refuses even when what was read is a whole stream.
        member = gzip.compress(b'a legacy operand', mtime=0)
        path = self.dir/'sized.json.gz'
        path.write_bytes(member+bytes(7))
        reads = []

        class Counted(io.BytesIO):
            def read(self, size=-1):
                reads.append(size)
                return super().read(size)

        def serving(data):
            def opening(name, mode):
                self.assertEqual((Path(name), mode), (path, 'rb'))
                return Counted(data)
            return opening
        try:
            LG.open = serving(member+bytes(8 << 20))
            with self.assertRaisesRegex(LG.LedgerRefused, 'changed while it was read'):
                LG.legacy_bytes(path, 100)
            self.assertEqual(reads, [1 << 20])
            LG.open = serving(member)
            with self.assertRaisesRegex(LG.LedgerRefused, 'changed while it was read'):
                LG.legacy_bytes(path, 100)
            LG.open = serving(member+bytes(7))
            self.assertEqual(bytes(LG.legacy_bytes(path, 100)), b'a legacy operand')
        finally:
            del LG.open
        self.assertEqual(bytes(LG.legacy_bytes(path, 100)), gzip.decompress(path.read_bytes()))

    def test_legacy_reader_accepts_no_more_than_gzip(self):
        raw = b'{"cells": []}'*50
        member = gzip.compress(raw, mtime=0)
        path = self.dir/'subset.json.gz'
        # gzip.decompress refuses each of these, and so does the reader.
        for label, data in (('zlib format', zlib.compress(raw)), ('space padding', member+b' '),
                            ('tab and newline padding', member+bytes(3)+b'\t\n'), ('magic only', b'\x1f\x8b'),
                            ('header only', member[:10]), ('padding only', bytes(9))):
            with self.assertRaises((OSError, EOFError, zlib.error), msg=label):
                gzip.decompress(data)
            path.write_bytes(data)
            with self.assertRaisesRegex(LG.LedgerRefused, 'not a whole gzip stream', msg=label):
                LG.legacy_bytes(path, len(raw))
        # Two of zlib's checks are stricter than gzip.decompress, which skips both: a header CRC must match,
        # and reserved header flags refuse. A correct header CRC reads.
        head = bytearray(member[:10])
        head[3] |= 2
        crc = zlib.crc32(head) & 0xffff
        reserved = bytearray(member)
        reserved[3] |= 0x20
        for label, data, accepted in (('header crc', bytes(head)+crc.to_bytes(2, 'little')+member[10:], True),
                                      ('wrong header crc', bytes(head)+(crc ^ 1).to_bytes(2, 'little')+member[10:], False),
                                      ('reserved flag', bytes(reserved), False)):
            self.assertEqual(gzip.decompress(data), raw, label)
            path.write_bytes(data)
            if accepted:
                self.assertEqual(bytes(LG.legacy_bytes(path, len(raw))), raw, label)
            else:
                with self.assertRaisesRegex(LG.LedgerRefused, 'not a whole gzip stream', msg=label):
                    LG.legacy_bytes(path, len(raw))

    def test_legacy_reader_holds_one_block_over_many(self):
        # A member followed by 24 MiB of zero padding is one whole stream read over 25 blocks; the reader
        # holds one block (beside the rest of it after a member ends), never the blocks before it.
        member = gzip.compress(b'operand', mtime=0)
        path = self.dir/'padded.json.gz'
        with open(path, 'wb') as handle:
            handle.write(member)
            for _ in range(24):
                handle.write(bytes(1 << 20))
        tracemalloc.start()
        try:
            self.assertEqual(bytes(LG.legacy_bytes(path, 7)), b'operand')
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 5 << 19)


if __name__ == '__main__':
    unittest.main()
