"""WP16 pre-advance captures: exact bytes, codec-independent logical identity, fail-closed reads."""
import copy
import gzip
import json
import os
import sys
import tempfile
import unittest
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

    def test_capture_route_is_checked_at_import(self):
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


if __name__ == '__main__':
    unittest.main()
