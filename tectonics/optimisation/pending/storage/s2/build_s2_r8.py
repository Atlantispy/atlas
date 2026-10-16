"""S2 revision 8: the r5->r7 delta re-check's four findings.

- NEW-1 (fixed): legacy_bytes read the whole legacy file before decompressing it, so a large file named by a
  legacy receipt allocated its own size first. It now streams the file 1 MiB at a time through the same
  member-by-member decompression; the output bound (receipt raw_bytes + 1) and every message are unchanged.
- NEW-2 (residual, unchanged): captured_bytes allocates the receipt's raw_bytes once the container pin and
  its footer agree; the note records why.
- NEW-3 (test): _container_pinned's footer can span the last two read blocks; tested at 1 MiB + k bytes.
- NEW-4 (rebase): R's fresh driver moved f328f314 -> d7bba076 (item 21 added advance_successor_interval,
  which starts an interval N >= 2 run and reaches the same pre-advance capture). The route check goes first
  in both fresh entry points; test_s2_route_wiring checks all three.
Writes s2/r8/ (modules, tests, driver-lines.diff) and r8-check/drivers/ (local wiring copies only).
"""
import difflib
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = HERE.parent.parent
R = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
R7, R8, CHECK = HERE/'r7', HERE/'r8', HERE/'r8-check'
DRV, NOSUCC = CHECK/'drivers', CHECK/'drivers-no-successor'
PINS = {R7/'compact_restart_patch.py': '301845b1', R7/'ledger_fresh_interval.py': 'f303d402',
        R7/'test_wp16_preadvance.py': '2be4805f', R7/'test_s2_route_wiring.py': '50ea132c',
        R7/'test_ledger_fresh_interval.py': '69a4dda0', R7/'test_step8_coverage.py': '5c07cb3b',
        R/'fresh_interval_driver.py': 'd7bba076', R/'prepared_interval_driver.py': '6fb4ab6d'}
UNCHANGED = ('compact_restart_patch.py', 'test_ledger_fresh_interval.py', 'test_step8_coverage.py')

LEDGER_EDITS = [
    ('''    raw_bytes, so a damaged or hostile file cannot make the ledger allocate past its
    receipt. gzip_bytes, which receipts may omit (the owner's fixtures do), must equal the
    file's size when present. A damaged stream refuses (REFUSED), never a FAIL-coded crash.
''', '''    raw_bytes, so a damaged or hostile file cannot make the ledger allocate past its
    receipt. The file is read 1 MiB at a time, so a large file allocates no more than a
    small one. gzip_bytes, which receipts may omit (the owner's fixtures do), must equal
    the file's size when present. A damaged stream refuses (REFUSED), never a FAIL-coded crash.
'''),
    ('''    with open(path, 'rb') as handle:
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
''', '''    out, member, ended, read = bytearray(), None, False, 0
    try:
        with open(path, 'rb') as handle:
            while True:
                data = handle.read(1 << 20)
                if not data:
                    break
                read += len(data)
                require(read <= size, 'legacy pre-advance capture changed while it was read: '+str(path))
                while data:
                    if member is None:
                        if ended:  # zero padding may follow a member, never start the file
                            data = data.lstrip(b'\\0')
                            if not data:
                                break
                        member = zlib.decompressobj(wbits=31)
                    out += member.decompress(data, raw_bytes+1-len(out))
                    require(len(out) <= raw_bytes, 'legacy pre-advance capture exceeds its receipt raw_bytes: '+str(path))
                    if member.eof:
                        data, member, ended = member.unused_data, None, True
                    else:
                        data = member.unconsumed_tail
    except zlib.error as error:  # a damaged r9 operand is a bad input: REFUSED, not FAIL
        raise LedgerRefused('legacy pre-advance capture is not a whole gzip stream: %s (%s)' % (path, error)) from None
    require(read == size, 'legacy pre-advance capture changed while it was read: '+str(path))
    require(member is None, 'legacy pre-advance capture is not a whole gzip stream: '+str(path))
    return out
'''),
]

TEST_EDITS = [
    ('"""WP16 pre-advance captures: exact bytes, codec-independent logical identity, fail-closed reads (S2 r7)."""\n',
     '"""WP16 pre-advance captures: exact bytes, codec-independent logical identity, fail-closed reads (S2 r8)."""\n'),
    ('import os\n', 'import os\nimport random\n'),
    ('''        path.write_bytes(b'')
        self.assertEqual((bytes(LG.legacy_bytes(path, 0)), gzip.decompress(b'')), (b'', b''))
''', '''        path.write_bytes(b'')
        self.assertEqual((bytes(LG.legacy_bytes(path, 0)), gzip.decompress(b'')), (b'', b''))

    def test_legacy_reader_streams_the_file(self):  # r8: the r5->r7 delta's NEW-1
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

    def test_footer_may_span_the_last_two_read_blocks(self):  # r8: the r5->r7 delta's NEW-3
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
'''),
]

WIRING_EDITS = [
    ('''"""S2: both callers of inspect_compact_preadvance check the capture route at run start (source check, no import).

DriverTests read the drivers found on sys.path (fresh_interval_driver, prepared_interval_driver) and pass
only once Runner has added, as top-level statements of each function:
    from compact_restart_patch import require_capture_route
    require_capture_route(store)              # advance_first_interval, before _seed_pinned()
    require_capture_route(workflow._store)    # advance_prepared_interval, after the duration require,
                                              # before record.update(original_target=...)
''', '''"""S2: every entry point that reaches inspect_compact_preadvance checks the capture route at run start (r8).

This is a source check; nothing is imported. DriverTests read the drivers found on sys.path
(fresh_interval_driver, prepared_interval_driver). They pass only once the integrator has added these
top-level statements to each function:
    from compact_restart_patch import require_capture_route
    require_capture_route(store)              # advance_first_interval, before _seed_pinned()
    require_capture_route(store)              # advance_successor_interval, before _seed_pinned()
    require_capture_route(workflow._store)    # advance_prepared_interval, after the duration require,
                                              # before record.update(original_target=...)
'''),
    ('''def check_fresh(source):
    node = _function(source, 'advance_first_interval')
    if 'store' not in [arg.arg for arg in node.args.args+node.args.kwonlyargs]:
        raise AssertionError('advance_first_interval: no store parameter')
    check = route_check_index(source, 'advance_first_interval', 'store')
    seed = _first(node.body, lambda s: _calls(s, lambda call: _named(call, '_seed_pinned')), '_seed_pinned()')
    if not check < seed:
        raise AssertionError('advance_first_interval: the route check must come before _seed_pinned()')
''', '''def check_fresh(source, function='advance_first_interval'):
    node = _function(source, function)
    if 'store' not in [arg.arg for arg in node.args.args+node.args.kwonlyargs]:
        raise AssertionError(function+': no store parameter')
    check = route_check_index(source, function, 'store')
    seed = _first(node.body, lambda s: _calls(s, lambda call: _named(call, '_seed_pinned')), '_seed_pinned()')
    if not check < seed:
        raise AssertionError(function+': the route check must come before _seed_pinned()')


def check_successor(source):
    check_fresh(source, 'advance_successor_interval')
'''),
    ('''    def test_fresh_driver_checks_the_route_first(self):
        check_fresh(self.source('fresh_interval_driver'))
''', '''    def test_fresh_driver_checks_the_route_first(self):
        check_fresh(self.source('fresh_interval_driver'))

    def test_successor_driver_checks_the_route_first(self):
        check_successor(self.source('fresh_interval_driver'))
'''),
    ('''            with self.assertRaises(AssertionError, msg=label):
                check_fresh(FRESH.format(lines=lines))
''', '''            with self.assertRaises(AssertionError, msg=label):
                check_fresh(FRESH.format(lines=lines))

    def test_successor_placements(self):
        successor = FRESH.replace('advance_first_interval(m, *, store,', 'advance_successor_interval(m, *, store, lineage,')
        good = IMPORT+'    require_capture_route(store)\\n    _seed_pinned()'
        check_successor(successor.format(lines=good))
        both = FRESH.format(lines=good)+successor.format(lines=good)
        check_fresh(both)
        check_successor(both)
        for label, lines in {'missing': IMPORT+'    _seed_pinned()',
                             'after the seed': IMPORT+'    _seed_pinned()\\n    require_capture_route(store)',
                             'other argument': IMPORT+'    require_capture_route(lineage)\\n    _seed_pinned()'}.items():
            with self.assertRaises(AssertionError, msg=label):
                check_successor(FRESH.format(lines=good)+successor.format(lines=lines))
        with self.assertRaises(AssertionError, msg='no successor'):
            check_successor(FRESH.format(lines=good))
'''),
]

LINES = '''    from compact_restart_patch import require_capture_route
    require_capture_route(store)
'''
FIRST_OLD = '''    runner's successor checks compare against state the advance could not touch.
    ``measurements``: see admission.
    """
    _seed_pinned()
'''
SUCCESSOR_OLD = '''    ``query_checkpoints``, ``finish`` and ``measurements``: as for advance_first_interval.
    """
    _seed_pinned()
'''
# Unchanged since r7: after the if/else that ends in the ordinary route's lineage_gate record, before derivations.
PREPARED_OLD = '''        record['lineage_gate'] = dict(found, lineage_schema=LINEAGE_SCHEMA, parent_advance_duration_s=first_duration)
    derivations = dict(joined=joined.derivation(), continuation=continuation.derivation())
'''
PREPARED_NEW = '''        record['lineage_gate'] = dict(found, lineage_schema=LINEAGE_SCHEMA, parent_advance_duration_s=first_duration)
    from compact_restart_patch import require_capture_route
    require_capture_route(workflow._store)
    derivations = dict(joined=joined.derivation(), continuation=continuation.derivation())
'''


def short(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8]


def replace(text, old, new, what):
    if text.count(old) != 1:
        sys.exit('%s: seam count %d: %r' % (what, text.count(old), old[:70]))
    return text.replace(old, new)


def edited(path, edits, what):
    text = path.read_text(encoding='utf8')
    for old, new in edits:
        text = replace(text, old, new, what)
    compile(text, what, 'exec')
    return text


def write(path, text):
    path.write_text(text, encoding='utf8', newline='\n')


def main():
    for path, pin in PINS.items():
        if short(path) != pin:
            sys.exit('%s is %s, not %s: refusing' % (path, short(path), pin))
    for folder in (R8, DRV, NOSUCC):
        folder.mkdir(parents=True, exist_ok=False)
    for name in UNCHANGED:
        shutil.copyfile(R7/name, R8/name)
    write(R8/'ledger_fresh_interval.py', edited(R7/'ledger_fresh_interval.py', LEDGER_EDITS, 'ledger_fresh_interval'))
    write(R8/'test_wp16_preadvance.py', edited(R7/'test_wp16_preadvance.py', TEST_EDITS, 'test_wp16_preadvance'))
    write(R8/'test_s2_route_wiring.py', edited(R7/'test_s2_route_wiring.py', WIRING_EDITS, 'test_s2_route_wiring'))
    fresh = (R/'fresh_interval_driver.py').read_text(encoding='utf8')
    first_only = replace(fresh, FIRST_OLD, FIRST_OLD.replace('    _seed_pinned()\n', LINES+'    _seed_pinned()\n'),
                         'fresh: advance_first_interval')
    both = replace(first_only, SUCCESSOR_OLD, SUCCESSOR_OLD.replace('    _seed_pinned()\n', LINES+'    _seed_pinned()\n'),
                   'fresh: advance_successor_interval')
    prepared_base = (R/'prepared_interval_driver.py').read_text(encoding='utf8')
    prepared = replace(prepared_base, PREPARED_OLD, PREPARED_NEW, 'prepared_interval_driver')
    for text, what in ((first_only, 'fresh first only'), (both, 'fresh'), (prepared, 'prepared')):
        compile(text, what, 'exec')
    write(DRV/'fresh_interval_driver.py', both)
    write(DRV/'prepared_interval_driver.py', prepared)
    write(NOSUCC/'fresh_interval_driver.py', first_only)  # control: the r7 placement only
    write(NOSUCC/'prepared_interval_driver.py', prepared)
    write(CHECK/'README.txt', 'Local S2 r8 wiring checks only. The integrator applies r8/driver-lines.diff on the live '
                              'driver SHAs.\n')
    diff = ''.join(difflib.unified_diff(fresh.splitlines(True), both.splitlines(True),
                                        'R/fresh_interval_driver.py (d7bba076)',
                                        'R/fresh_interval_driver.py + S2 route checks'))
    diff += ''.join(difflib.unified_diff(prepared_base.splitlines(True), prepared.splitlines(True),
                                         'R/prepared_interval_driver.py (6fb4ab6d)',
                                         'R/prepared_interval_driver.py + S2 route check'))
    write(R8/'driver-lines.diff', diff)
    for path in sorted(R8.iterdir())+sorted(DRV.iterdir())+sorted(NOSUCC.iterdir()):
        print(short(path), path.relative_to(HERE))


if __name__ == '__main__':
    main()
