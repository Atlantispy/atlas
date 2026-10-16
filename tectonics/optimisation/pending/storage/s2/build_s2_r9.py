"""S2 revision 9: the r7->r8 delta re-check's wording and test findings. No behaviour changes.

- P3-a (wording): legacy_bytes accepts a subset of what gzip.decompress accepts; zlib also checks a header
  CRC and refuses reserved header flags. The docstring says so, and a test holds both sides.
- P2 (residual, booked): the legacy output may briefly need about twice raw_bytes; the docstring says so.
- P3-c, P3-d, P3-e (tests): the read-size checks, the negative cases (zlib format, whitespace padding, a
  stream cut before any output) and the memory bound over many read blocks.
- P3-f (wording): require_capture_route's docstring names all three entry points.
- Review IDs are dropped from the new test files' comments and docstrings.
Driver lines are unchanged (r8/driver-lines.diff). Writes s2/r9/, r9-diffs/ and r9-check/drv/drivers_r9.py.
"""
import difflib
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R8, R9, CHECK, DIFFS = HERE/'r8', HERE/'r9', HERE/'r9-check', HERE/'r9-diffs'
PINS = {R8/'compact_restart_patch.py': '301845b1', R8/'ledger_fresh_interval.py': '7d8a0c91',
        R8/'test_wp16_preadvance.py': '42d2576a', R8/'test_s2_route_wiring.py': '8e7b3daa',
        R8/'test_ledger_fresh_interval.py': '69a4dda0', R8/'test_step8_coverage.py': '5c07cb3b',
        R8/'driver-lines.diff': '1e2652b8', HERE/'base/compact_restart_patch.py': '9d076c80',
        HERE/'base/ledger_fresh_interval.py': 'cd89718b', HERE/'r8-check/drv/drivers_r8.py': None}
UNCHANGED = ('test_ledger_fresh_interval.py', 'test_step8_coverage.py', 'driver-lines.diff')

LEDGER_EDITS = [
    ('''    The rules are gzip.decompress's (members in sequence, zero padding between them, an
    empty file is empty), but the members together may not produce more than the receipt's
    raw_bytes, so a damaged or hostile file cannot make the ledger allocate past its
    receipt. The file is read 1 MiB at a time, so a large file allocates no more than a
    small one. gzip_bytes, which receipts may omit (the owner's fixtures do), must equal
    the file's size when present. A damaged stream refuses (REFUSED), never a FAIL-coded crash.
''', '''    The rules are gzip.decompress's (members in sequence, zero padding between them, an
    empty file is empty), with two stricter checks of zlib's that gzip.decompress skips: a
    header CRC, when present, must match, and reserved header flags refuse (writers set
    neither). The members together may not produce more than the receipt's raw_bytes, so a
    damaged or hostile file cannot make the ledger allocate past its receipt. The file is
    read 1 MiB at a time, so its size costs one block; the output may briefly need about
    twice raw_bytes (a decompressed chunk beside the buffer it joins, and the buffer's
    growth). gzip_bytes, which receipts may omit (the owner's fixtures do), must equal the
    file's size when present. A damaged stream refuses (REFUSED), never a FAIL-coded crash.
'''),
]

CRP_EDITS = [
    ('''    Both callers of inspect_compact_preadvance (fresh_interval_driver.advance_first_interval
    and prepared_interval_driver.advance_prepared_interval) call this before any physical
    work. The two capture modules are imported, not only found, so inside the selected
''', '''    Every entry point that reaches inspect_compact_preadvance calls this before any
    physical work: fresh_interval_driver's advance_first_interval and
    advance_successor_interval, and prepared_interval_driver's advance_prepared_interval.
    The two capture modules are imported, not only found, so inside the selected
'''),
]

WIRING_EDITS = [
    ('"""S2: every entry point that reaches inspect_compact_preadvance checks the capture route at run start (r8).\n',
     '"""Every entry point that reaches inspect_compact_preadvance checks the capture route at run start.\n'),
]

TEST_EDITS = [
    ('"""WP16 pre-advance captures: exact bytes, codec-independent logical identity, fail-closed reads (S2 r8)."""\n',
     '"""WP16 pre-advance captures: exact bytes, codec-independent logical identity, fail-closed reads."""\n'),
    ('import importlib.util\nimport json\n', 'import importlib.util\nimport io\nimport json\n'),
    ('import unittest\nfrom contextlib', 'import unittest\nimport zlib\nfrom contextlib'),
    ('        # r7: each refuses at its own check', '        # Each refuses at its own check'),
    ('        # r7: with no gzip_bytes nothing', '        # With no gzip_bytes nothing'),
    ("(self):  # r6: the r5 delta's P2\n", '(self):\n'),
    ("(self):  # r6: the r5 delta's P3-a\n", '(self):\n'),
    ("(self):  # r6: the r5 delta's P3-c\n", '(self):\n'),
    ("(self):  # r8: the r5->r7 delta's NEW-1\n", '(self):\n'),
    ("(self):  # r8: the r5->r7 delta's NEW-3\n", '(self):\n'),
    ('''            with self.assertRaisesRegex(LG.LedgerRefused, 'footer differs', msg=extra):
                LG._container_pinned(path, pin, 12346, len(data), footer)
''', '''            with self.assertRaisesRegex(LG.LedgerRefused, 'footer differs', msg=extra):
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
                            ('tab and newline padding', member+bytes(3)+b'\\t\\n'), ('magic only', b'\\x1f\\x8b'),
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
'''),
]


# Every process that imports the runtime runs with the string-hash seed 0 (no -I or -E; PYTHONHASHSEED=0).
SEEDED = '''    if sys.flags.hash_randomization != 0:
        raise SystemExit('refusing: the string-hash seed is not 0 (run without -I or -E, with PYTHONHASHSEED=0)')
'''


def short(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8]


def edited(path, edits, what):
    text = path.read_text(encoding='utf8')
    for old, new in edits:
        if text.count(old) != 1:
            sys.exit('%s: seam count %d: %r' % (what, text.count(old), old[:70]))
        text = text.replace(old, new)
    compile(text, what, 'exec')
    return text


def write(path, text):
    path.write_text(text, encoding='utf8', newline='\n')


def diff(old_path, new_text, old_label, new_label):
    return ''.join(difflib.unified_diff(old_path.read_text(encoding='utf8').splitlines(True), new_text.splitlines(True),
                                        old_label, new_label))


def main():
    for path, pin in PINS.items():
        if pin is not None and short(path) != pin:
            sys.exit('%s is %s, not %s: refusing' % (path, short(path), pin))
    for folder in (R9, CHECK/'drv', DIFFS):
        folder.mkdir(parents=True, exist_ok=False)
    for name in UNCHANGED:
        shutil.copyfile(R8/name, R9/name)
    texts = {'ledger_fresh_interval.py': edited(R8/'ledger_fresh_interval.py', LEDGER_EDITS, 'ledger_fresh_interval'),
             'compact_restart_patch.py': edited(R8/'compact_restart_patch.py', CRP_EDITS, 'compact_restart_patch'),
             'test_wp16_preadvance.py': edited(R8/'test_wp16_preadvance.py', TEST_EDITS, 'test_wp16_preadvance'),
             'test_s2_route_wiring.py': edited(R8/'test_s2_route_wiring.py', WIRING_EDITS, 'test_s2_route_wiring')}
    for name, text in texts.items():
        write(R9/name, text)
        write(DIFFS/('delta-r8-r9-'+name[:-3]+'.diff'), diff(R8/name, text, 'r8/'+name, 'r9/'+name))
    for name, base in (('compact_restart_patch.py', '9d076c80'), ('ledger_fresh_interval.py', 'cd89718b')):
        write(DIFFS/(name[:-3]+'.diff'), diff(HERE/'base'/name, texts[name], 'R/%s (%s)' % (name, base),
                                              '%s S2 r9 (%s)' % (name, short(R9/name))))
    # R's own driver tests with the r9 CRP preloaded: drivers_r8.py with r9's pin, same patched drivers.
    harness = (HERE/'r8-check/drv/drivers_r8.py').read_text(encoding='utf8')
    for old, new in (("S2/'r8/compact_restart_patch.py': '301845b1'",
                      "S2/'r9/compact_restart_patch.py': '%s'" % short(R9/'compact_restart_patch.py')),
                     ('"""S2 r8 evidence', '"""S2 r9 evidence'),
                     ('VARIANT: base (nothing preloaded) or r8 (that CRP', 'VARIANT: base (nothing preloaded) or r9 (that CRP'),
                     ('  drivers_r8.py fresh', '  drivers_r9.py fresh'), ('  drivers_r8.py prepared', '  drivers_r9.py prepared'),
                     ('  drivers_r8.py scenario', '  drivers_r9.py scenario'),
                     ('def main():\n    pinned()\n', 'def main():\n'+SEEDED+'    pinned()\n')):
        if harness.count(old) != 1:
            sys.exit('drivers harness: seam count %d: %r' % (harness.count(old), old))
        harness = harness.replace(old, new)
    compile(harness, 'drivers_r9', 'exec')
    write(CHECK/'drv'/'drivers_r9.py', harness)
    # The test harness: run_tests_r8.py with the same fail-closed seed check before anything is imported.
    runner = (HERE/'r8-check/run_tests_r8.py').read_text(encoding='utf8')
    for old, new in (('"""S2 r8 harness (run_tests_r7.py with roots from this file): run_tests_r8.py',
                      '"""S2 r9 harness (run_tests_r8.py with a fail-closed seed check): run_tests_r9.py'),
                     ('from pathlib import Path\n\n', 'from pathlib import Path\n\n'+SEEDED.replace('    ', '', 1)
                      .replace('\n    ', '\n')+'\n')):
        if runner.count(old) != 1:
            sys.exit('test harness: seam count %d: %r' % (runner.count(old), old))
        runner = runner.replace(old, new)
    compile(runner, 'run_tests_r9', 'exec')
    write(CHECK/'run_tests_r9.py', runner)
    for path in sorted(R9.iterdir())+sorted(DIFFS.iterdir())+[CHECK/'drv'/'drivers_r9.py', CHECK/'run_tests_r9.py']:
        print(short(path), path.relative_to(HERE))


if __name__ == '__main__':
    main()
