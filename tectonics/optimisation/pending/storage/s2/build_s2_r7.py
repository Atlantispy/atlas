"""S2 revision 7: r6's modules unchanged; tests that kill r6's four surviving mutants; driver lines rebased.

Sources r6: compact_restart_patch 301845b1, ledger_fresh_interval f303d402 (both copied unchanged),
test_wp16_preadvance 04347dff. The r6 mutant run (r6-check/tests-r6.log) left l3, l4, l8 and l6 alive:
- l3/l8 (container form check removed or case-blind) and l4 (stat-size check removed): r6's hash pass still
  refuses those receipts, but later, after opening and reading the file, with another message. The test
  now pins the earliest refusal: its own message, with the ledger's open() refusing to be called.
- l6 (legacy eof check removed): every test path passed gzip_bytes, which refused first. legacy_bytes is
  now called directly with no gzip_bytes, where a missing trailer otherwise reads as whole.
R's prepared_interval_driver moved c4f5c4fb -> 6fb4ab6d (Runner, item 21, 15:39): the duration require now
sits in both branches of an if/else. The route check goes after that if/else, before derivations, so it
covers the migrated and the ordinary route; test_s2_route_wiring (50ea132c) accepts that place unchanged.
Writes s2/r7/ (modules, tests, driver-lines.diff) and r7-check/drivers/ (local wiring copies only).
"""
import difflib
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = HERE.parent.parent
R = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
R6, R7, DRV = HERE/'r6', HERE/'r7', HERE/'r7-check'/'drivers'
PINS = {R6/'compact_restart_patch.py': '301845b1', R6/'ledger_fresh_interval.py': 'f303d402',
        R6/'test_wp16_preadvance.py': '04347dff', R6/'test_s2_route_wiring.py': '50ea132c',
        R6/'test_ledger_fresh_interval.py': '69a4dda0', R6/'test_step8_coverage.py': '5c07cb3b',
        R/'fresh_interval_driver.py': 'f328f314', R/'prepared_interval_driver.py': '6fb4ab6d',
        HERE/'r5-check/drivers/fresh_interval_driver.py': '228ddffb'}
UNCHANGED = ('compact_restart_patch.py', 'ledger_fresh_interval.py', 'test_s2_route_wiring.py',
             'test_ledger_fresh_interval.py', 'test_step8_coverage.py')

TEST_EDITS = [
    ('"""WP16 pre-advance captures: exact bytes, codec-independent logical identity, fail-closed reads (S2 r6)."""\n',
     '"""WP16 pre-advance captures: exact bytes, codec-independent logical identity, fail-closed reads (S2 r7)."""\n'),
    ('''def flip(path, offset_from_end):
''', '''@contextmanager
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
'''),
    ('''        for label, (container, raw_bytes, stored_bytes) in cases.items():
            with self.assertRaises(LG.LedgerRefused, msg=label):
                LG.captured_bytes(path, container, raw_bytes, stored_bytes)
''', '''        # r7: each refuses at its own check, before the file is opened (the hash pass would refuse later).
        expected = dict.fromkeys(('raw 2**45', 'raw 2**63', 'stored over ceiling'), 'capture receipt sizes required')
        expected.update(dict.fromkeys(('container None', 'container upper', 'container short', 'container bytes'),
                                      r'container_sha256 required \\(64 lowercase hex\\)'))
        expected['stored +1000'] = 'pre-advance capture size differs from its receipt'
        self.assertEqual(set(expected), set(cases))
        with unopened():
            for label, (container, raw_bytes, stored_bytes) in cases.items():
                with self.assertRaisesRegex(LG.LedgerRefused, expected[label], msg=label):
                    LG.captured_bytes(path, container, raw_bytes, stored_bytes)
'''),
    ('''            path.write_bytes(data)
            with self.assertRaises(LG.LedgerRefused, msg=label):
                LG.capture(self.dir, row)
        path.write_bytes(whole)
''', '''            path.write_bytes(data)
            with self.assertRaises(LG.LedgerRefused, msg=label):
                LG.capture(self.dir, row)
        # r7: with no gzip_bytes nothing else sees a missing end; the reader itself requires a whole stream.
        for label, data in (('truncated', whole[:len(whole)//2]), ('no trailer', whole[:-8])):
            path.write_bytes(data)
            with self.assertRaisesRegex(LG.LedgerRefused, 'not a whole gzip stream', msg=label):
                LG.legacy_bytes(path, len(raw))
        path.write_bytes(whole)
        self.assertEqual(bytes(LG.legacy_bytes(path, len(raw))), raw)
'''),
]
# After the if/else that ends in the ordinary route's lineage_gate record, before derivations.
DRIVER_OLD = '''        record['lineage_gate'] = dict(found, lineage_schema=LINEAGE_SCHEMA, parent_advance_duration_s=first_duration)
    derivations = dict(joined=joined.derivation(), continuation=continuation.derivation())
'''
DRIVER_NEW = '''        record['lineage_gate'] = dict(found, lineage_schema=LINEAGE_SCHEMA, parent_advance_duration_s=first_duration)
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


def main():
    for path, pin in PINS.items():
        if short(path) != pin:
            sys.exit('%s is %s, not %s: refusing' % (path, short(path), pin))
    R7.mkdir(exist_ok=False)
    DRV.mkdir(parents=True, exist_ok=False)
    for name in UNCHANGED:
        shutil.copyfile(R6/name, R7/name)
    text = (R6/'test_wp16_preadvance.py').read_text(encoding='utf8')
    for old, new in TEST_EDITS:
        text = replace(text, old, new, 'test_wp16_preadvance')
    compile(text, 'test_wp16_preadvance', 'exec')
    (R7/'test_wp16_preadvance.py').write_text(text, encoding='utf8', newline='\n')
    base = (R/'prepared_interval_driver.py').read_text(encoding='utf8')
    prepared = replace(base, DRIVER_OLD, DRIVER_NEW, 'prepared_interval_driver')
    compile(prepared, 'prepared_interval_driver', 'exec')
    (DRV/'prepared_interval_driver.py').write_text(prepared, encoding='utf8', newline='\n')
    shutil.copyfile(HERE/'r5-check/drivers/fresh_interval_driver.py', DRV/'fresh_interval_driver.py')
    (DRV/'NOT-FOR-APPLICATION.txt').write_text(
        'Local S2 r7 wiring check only. Runner applies the lines in r7/driver-lines.diff on his own driver SHAs.\n',
        encoding='utf8', newline='\n')
    fresh = (R/'fresh_interval_driver.py').read_text(encoding='utf8')
    diff = ''.join(difflib.unified_diff(fresh.splitlines(True), (DRV/'fresh_interval_driver.py').read_text(
        encoding='utf8').splitlines(True), 'R/fresh_interval_driver.py (f328f314)',
        'R/fresh_interval_driver.py + S2 route check'))
    diff += ''.join(difflib.unified_diff(base.splitlines(True), prepared.splitlines(True),
                                         'R/prepared_interval_driver.py (6fb4ab6d)',
                                         'R/prepared_interval_driver.py + S2 route check'))
    (R7/'driver-lines.diff').write_text(diff, encoding='utf8', newline='\n')
    for path in sorted(R7.iterdir())+sorted(DRV.iterdir()):
        print(short(path), path.relative_to(HERE))


if __name__ == '__main__':
    main()
