"""S2 revision 6: the r5 delta re-check's findings (T/so/refute/s2/delta-r5/review.txt); writes s2/r6/.

Sources r5: compact_restart_patch 1a1088d9, ledger_fresh_interval 775bb0a4, test_wp16_preadvance fc8bc908.
- P2: require_capture_route imported compact_restart_store before it knew the store was compact, so a
  legacy run (R's driver tests: no compact_restart_store on their path) failed at run start, and a cold
  non-compact call imported ~940 modules. It now looks the module up in sys.modules, never imports it:
  a compact store's module is loaded wherever a compact store exists. Same result for every store.
- P3-a: captured_bytes allocated raw_bytes before anything authenticated the file. The whole file must
  now hash to the receipt's container pin and the footer that pin covers must state the receipt's
  raw_bytes before the buffer is allocated; stored_bytes must be at least the format's minimum.
- P3-c (pre-existing): the legacy gzip branch read any path and decompressed without a bound. Both forms
  now take plain file names only, and legacy_bytes decompresses member by member, never past the
  receipt's raw_bytes; gzip_bytes, when present, must equal the file size. gzip is no longer imported.
The driver lines and test_s2_route_wiring (50ea132c) do not change; test_wp16_preadvance gains three tests.
"""
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

CRP_OLD = '''    library and checks its sha256. Any other store is not checked here, and this module
    itself imports without the capture route, so compositions without it still import.
    Returns the library's sha256 for a compact store, else None.
    """
    from compact_restart_store import is_compact_restart_store
    if not is_compact_restart_store(store):
        return None
'''
CRP_NEW = '''    library and checks its sha256. Any other store is not checked here and imports
    nothing: the store's module is looked up, never imported, since it is loaded wherever
    a compact store exists. This module itself imports without the capture route, so
    compositions without it still import. Returns the library's sha256 for a compact
    store, else None.
    """
    crs = sys.modules.get('compact_restart_store')
    if crs is None or not crs.is_compact_restart_store(store):
        return None
'''

LG_IMPORT_OLD = 'import argparse\nimport gzip\nimport json\n'
LG_IMPORT_NEW = 'import argparse\nimport json\n'

LG_HELPERS_OLD = "_HEX = frozenset('0123456789abcdef')\n\n\ndef captured_bytes("
LG_HELPERS_NEW = '''_HEX = frozenset('0123456789abcdef')


def _container_pinned(path, container_sha256, raw_bytes, stored_bytes, footer):
    """The whole file hashes to the receipt's container pin, and its footer states raw_bytes.

    The container hash covers every byte, footer included, so once it matches the receipt
    the footer is the writer's own; its raw_bytes must then equal the receipt's. The file is
    read 1 MiB at a time, so nothing the receipt sizes is allocated here.
    """
    digest, left, tail = sha256(), stored_bytes, b''
    with open(path, 'rb') as handle:
        while left:
            block = handle.read(min(left, 1 << 20))
            require(block, 'pre-advance capture is shorter than its receipt: '+str(path))
            digest.update(block)
            tail = block[-footer.size:] if len(block) >= footer.size else (tail+block)[-footer.size:]
            left -= len(block)
        require(not handle.read(1), 'pre-advance capture is longer than its receipt: '+str(path))
    require(digest.hexdigest() == container_sha256, 'pre-advance capture differs from its container pin: '+str(path))
    tag, _, footer_raw_bytes, _, _ = footer.unpack(tail)
    require(tag == b'F' and footer_raw_bytes == raw_bytes,
            'pre-advance capture footer differs from its receipt raw_bytes: '+str(path))


def legacy_bytes(path, raw_bytes, gzip_bytes=None):
    """The exact bytes of one legacy (r9) gzip operand, never decompressed past its receipt.

    The rules are gzip.decompress's (members in sequence, zero padding between them, an
    empty file is empty), but the members together may not produce more than the receipt's
    raw_bytes, so a damaged or hostile file cannot make the ledger allocate past its
    receipt. gzip_bytes, which receipts may omit (the owner's fixtures do), must equal the
    file's size when present. A damaged stream refuses (REFUSED), never a FAIL-coded crash.
    """
    require(type(raw_bytes) is int and 0 <= raw_bytes <= CAPTURE_MAX_BYTES,
            'legacy capture receipt raw_bytes required (at most %d bytes): %s' % (CAPTURE_MAX_BYTES, path))
    size = Path(path).stat().st_size
    require(size <= CAPTURE_MAX_BYTES, 'legacy pre-advance capture exceeds the ceiling: '+str(path))
    require(gzip_bytes is None or (type(gzip_bytes) is int and gzip_bytes == size),
            'legacy pre-advance capture gzip_bytes differs from its file: '+str(path))
    with open(path, 'rb') as handle:
        data = handle.read(size+1)
    require(len(data) == size, 'legacy pre-advance capture changed while it was read: '+str(path))
    out = bytearray()
    try:
        while data:
            member = zlib.decompressobj(wbits=31)
            out += member.decompress(data, raw_bytes+1-len(out))
            require(len(out) <= raw_bytes, 'legacy pre-advance capture exceeds its receipt raw_bytes: '+str(path))
            require(member.eof, 'legacy pre-advance capture is not a whole gzip stream: '+str(path))
            data = member.unused_data.lstrip(b'\\0')
    except zlib.error as error:  # a damaged r9 operand is a bad input: REFUSED, not FAIL
        raise LedgerRefused('legacy pre-advance capture is not a whole gzip stream: %s (%s)' % (path, error)) from None
    return out


def captured_bytes('''

LG_DOC_OLD = '''    Before the one output buffer is allocated, the receipt's sizes must be at most the
    writer's ceiling, its container pin must be 64 lowercase hex, and stored_bytes must equal
    the file's size; the reader is then held to raw_bytes, so each operand is held once. The reader needs the composed helpers and runtime
    source on sys.path; without them the ledger refuses (REFUSED), never a FAIL-coded crash.
    """
    try:
        from atlas_tectonics.resources import WorkBudget
        from capture_store import CaptureReader
'''
LG_DOC_NEW = '''    Before the one output buffer is allocated, the receipt's sizes must lie between the
    format's minimum and the writer's ceiling, its container pin must be 64 lowercase hex,
    stored_bytes must equal the file's size, the whole file must hash to the container pin
    and the footer that pin covers must state the receipt's raw_bytes, so a receipt never
    sizes an allocation its file does not back. The reader is then held to raw_bytes, so
    each operand is held once. The reader needs the composed helpers and runtime source on
    sys.path; without them the ledger refuses (REFUSED), never a FAIL-coded crash.
    """
    try:
        from atlas_tectonics.resources import WorkBudget
        from capture_store import CaptureReader, FOOTER, PREAMBLE
'''

LG_MIN_OLD = '            0 < stored_bytes <= CAPTURE_MAX_BYTES,\n'
LG_MIN_NEW = '            PREAMBLE.size+32+FOOTER.size <= stored_bytes <= CAPTURE_MAX_BYTES,\n'

LG_ALLOC_OLD = ("    require(Path(path).stat().st_size == stored_bytes, 'pre-advance capture size differs from its receipt: '"
                "+str(path))\n    buffer, filled = bytearray(raw_bytes), 0\n")
LG_ALLOC_NEW = ("    require(Path(path).stat().st_size == stored_bytes, 'pre-advance capture size differs from its receipt: '"
                "+str(path))\n    _container_pinned(path, container_sha256, raw_bytes, stored_bytes, FOOTER)\n"
                "    buffer, filled = bytearray(raw_bytes), 0\n")

LG_CAPTURE_OLD = '''    WP16 captures (format atlas.diagnostic-capture.v1) are fully verified against their
    own container_sha256; legacy gzip operands (r9) stay readable. Both then meet the
    same raw_bytes/raw_sha256 receipt check, the codec-independent logical identity.
    """
    if operand.get('format') == CAPTURE_FORMAT:
        raw = captured_bytes(Path(directory, operand['path']), operand['container_sha256'],
                             operand['raw_bytes'], operand['stored_bytes'])
    else:
        try:
            raw = gzip.decompress(Path(directory, operand['path']).read_bytes())
        except (EOFError, zlib.error) as error:  # a damaged r9 operand is a bad input: REFUSED, not FAIL
            raise LedgerRefused('legacy pre-advance capture is not a whole gzip stream: %s (%s)'
                                % (operand['path'], error)) from None
    require(len(raw) == operand['raw_bytes'] and sha256(raw).hexdigest() == operand['raw_sha256'],
            'pre-advance capture differs from its receipt: '+operand['path'])
'''
LG_CAPTURE_NEW = '''    The receipt names a plain file name in the run's own folder (both writers record
    path.name). WP16 captures (format atlas.diagnostic-capture.v1) are fully verified
    against their own container_sha256; legacy gzip operands (r9) stay readable, bounded by
    their receipt's raw_bytes. Both then meet the same raw_bytes/raw_sha256 receipt check,
    the codec-independent logical identity.
    """
    name = operand['path']
    require(type(name) is str and name not in ('', '.', '..') and Path(name).name == name,
            'pre-advance capture path must be a plain file name: %r' % (name,))
    if operand.get('format') == CAPTURE_FORMAT:
        raw = captured_bytes(Path(directory, name), operand['container_sha256'],
                             operand['raw_bytes'], operand['stored_bytes'])
    else:
        raw = legacy_bytes(Path(directory, name), operand['raw_bytes'], operand.get('gzip_bytes'))
    require(len(raw) == operand['raw_bytes'] and sha256(raw).hexdigest() == operand['raw_sha256'],
            'pre-advance capture differs from its receipt: '+name)
'''

TEST_DOC_OLD = '(S2 r5)."""\n'
TEST_DOC_NEW = '(S2 r6)."""\n'
TEST_IMPORT_OLD = 'import tempfile\nimport unittest\n'
TEST_IMPORT_NEW = 'import tempfile\nimport tracemalloc\nimport unittest\n'
TEST_TAIL_OLD = "        self.assertEqual(CRP.CAPTURE_MAX_BYTES, 16 << 30)\n\n\nif __name__ == '__main__':"
TEST_TAIL_NEW = '''        self.assertEqual(CRP.CAPTURE_MAX_BYTES, 16 << 30)

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
            for name in ('../'+receipt['path'], '..\\\\'+receipt['path'], str(target.resolve()),
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


if __name__ == '__main__':'''


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise SystemExit('%s: seam found %d times' % (label, text.count(old)))
    return text.replace(old, new)


def checked(path, short):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest()[:8] != short:
        raise SystemExit('%s is not %s: refusing' % (path, short))
    return data.decode('utf8')


def main():
    r5, target = HERE/'r5', HERE/'r6'
    crp = checked(r5/'compact_restart_patch.py', '1a1088d9')
    lg = checked(r5/'ledger_fresh_interval.py', '775bb0a4')
    test = checked(r5/'test_wp16_preadvance.py', 'fc8bc908')
    checked(r5/'test_s2_route_wiring.py', '50ea132c')
    crp = replace_once(crp, CRP_OLD, CRP_NEW, 'CRP route')
    for label, old, new in (('LG import', LG_IMPORT_OLD, LG_IMPORT_NEW), ('LG helpers', LG_HELPERS_OLD, LG_HELPERS_NEW),
                            ('LG doc', LG_DOC_OLD, LG_DOC_NEW), ('LG minimum', LG_MIN_OLD, LG_MIN_NEW),
                            ('LG allocation', LG_ALLOC_OLD, LG_ALLOC_NEW), ('LG capture', LG_CAPTURE_OLD, LG_CAPTURE_NEW)):
        lg = replace_once(lg, old, new, label)
    if 'gzip' in lg.replace('gzip_bytes', '').replace('gzip operand', '').replace('gzip stream', '').replace(
            'gzip.decompress', '').replace('gzip-1', ''):
        raise SystemExit('LG still names the gzip module')
    for label, old, new in (('test doc', TEST_DOC_OLD, TEST_DOC_NEW), ('test import', TEST_IMPORT_OLD, TEST_IMPORT_NEW),
                            ('test tail', TEST_TAIL_OLD, TEST_TAIL_NEW)):
        test = replace_once(test, old, new, label)
    for name, text in (('compact_restart_patch.py', crp), ('ledger_fresh_interval.py', lg),
                       ('test_wp16_preadvance.py', test)):
        compile(text, name, 'exec')
    target.mkdir(exist_ok=False)
    for name, text in (('compact_restart_patch.py', crp), ('ledger_fresh_interval.py', lg),
                       ('test_wp16_preadvance.py', test)):
        (target/name).write_bytes(text.encode('utf8'))
    for name in ('test_s2_route_wiring.py', 'test_ledger_fresh_interval.py', 'test_step8_coverage.py'):
        shutil.copyfile(r5/name, target/name)
    for path in sorted(target.iterdir()):
        print('wrote', path.name, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    sys.exit(main())
