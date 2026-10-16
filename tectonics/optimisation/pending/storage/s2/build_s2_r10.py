"""S2 r10: the r9 candidate with the capture library's path taken from the module's own folder.

r9 named the pinned WP10 library by an absolute machine path in compact_restart_patch.py and
ledger_fresh_interval.py. Both modules live at the top of the resumability tree, beside
compact-geometry-r1, so r10 takes the library from there (the tree's existing HERE-relative
convention); its sha256 pin is unchanged, so the same bytes or a refusal. test_wp16 gains one
assertion that the path is module-relative. Nothing else changes.

For the checks, r10/ mirrors the tree's layout: the pinned library is copied (sha checked) to
r10/compact-geometry-r1/native/. Writes r10/, r10-diffs/, r10-check/{run_tests_r10.py,
drv/drivers_r10.py}; refuses if any exists.

Usage: python -B build_s2_r10.py
"""
import difflib
import hashlib
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = HERE.parents[1]
R = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
R9, R10, DIFFS, CHECK = HERE/'r9', HERE/'r10', HERE/'r10-diffs', HERE/'r10-check'
LIBRARY = Path('compact-geometry-r1', 'native', 'wp10_zstd.dll')
LIBRARY_SHA256 = 'a40c24ad328da37a42c7f69e434c576254f11fde4097cd5de7416f8f78444f28'
PINS = {R9/'compact_restart_patch.py': '7afe82bf', R9/'ledger_fresh_interval.py': '06040fd2',
        R9/'test_wp16_preadvance.py': '25e9d8c6', R9/'test_s2_route_wiring.py': 'd5f68374',
        R9/'test_ledger_fresh_interval.py': '69a4dda0', R9/'test_step8_coverage.py': '5c07cb3b',
        R9/'driver-lines.diff': '1e2652b8', HERE/'base/compact_restart_patch.py': '9d076c80',
        HERE/'base/ledger_fresh_interval.py': 'cd89718b', HERE/'r9-check/run_tests_r9.py': 'bd168bfd',
        HERE/'r9-check/drv/drivers_r9b.py': 'bcc307fe'}
UNCHANGED = ('test_s2_route_wiring.py', 'test_ledger_fresh_interval.py', 'test_step8_coverage.py', 'driver-lines.diff')
# r9's absolute path, three source lines; matched by shape so no machine path is written here.
OLD_PATH = re.compile(r"CAPTURE_LIBRARY = Path\('[A-Za-z]:/[^\n]*\n[^\n]*\n[^\n]*/wp10_zstd\.dll'\)\n")
NEW_PATH = "CAPTURE_LIBRARY = Path(__file__).resolve().parent/'compact-geometry-r1'/'native'/'wp10_zstd.dll'\n"

CRP_EDITS = [
    ("# The existing pinned WP10 Zstandard library in its permanent folder; there is no\n"
     "# raw or gzip fallback: a missing or changed library refuses.\n",
     "# The existing pinned WP10 Zstandard library, at its place beside this module\n"
     "# (compact-geometry-r1/native in the resumability tree); there is no raw or gzip\n"
     "# fallback: a missing or changed library refuses.\n"),
]
LEDGER_EDITS = [
    ("CAPTURE_FORMAT = 'atlas.diagnostic-capture.v1'\n",
     "CAPTURE_FORMAT = 'atlas.diagnostic-capture.v1'\n"
     "# The writer's library (compact_restart_patch.CAPTURE_LIBRARY), from this module's folder.\n"),
]
TEST_EDITS = [
    ("        # Writer and reader name the same format and the same pinned library.\n",
     "        # The library sits beside the module, as in the resumability tree; no machine path.\n"
     "        self.assertEqual(CRP.CAPTURE_LIBRARY, Path(CRP.__file__).resolve().parent/'compact-geometry-r1'/'native'/\n"
     "                         'wp10_zstd.dll')\n"
     "        # Writer and reader name the same format and the same pinned library.\n"),
]


def short(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8]


def edited(path, edits, what, library=False):
    text = path.read_text(encoding='utf8')
    if library:
        if len(OLD_PATH.findall(text)) != 1:
            sys.exit('%s: absolute library path found %d times' % (what, len(OLD_PATH.findall(text))))
        text = OLD_PATH.sub(lambda _: NEW_PATH, text)
    for old, new in edits:
        if text.count(old) != 1:
            sys.exit('%s: seam count %d: %r' % (what, text.count(old), old[:70]))
        text = text.replace(old, new)
    compile(text, what, 'exec')
    return text


def write(path, text):
    path.write_text(text, encoding='utf8', newline='\n')


def diff(old_path, new_text, old_label, new_label):
    return ''.join(difflib.unified_diff(old_path.read_text(encoding='utf8').splitlines(True),
                                        new_text.splitlines(True), old_label, new_label))


def main():
    for path, pin in PINS.items():
        if short(path) != pin:
            sys.exit('%s is %s, not %s: refusing' % (path, short(path), pin))
    if hashlib.sha256((R/LIBRARY).read_bytes()).hexdigest() != LIBRARY_SHA256:
        sys.exit('the pinned library changed: refusing')
    for folder in (R10, CHECK/'drv', DIFFS):
        folder.mkdir(parents=True, exist_ok=False)
    for name in UNCHANGED:
        shutil.copyfile(R9/name, R10/name)
    texts = {'compact_restart_patch.py': edited(R9/'compact_restart_patch.py', CRP_EDITS, 'compact_restart_patch', True),
             'ledger_fresh_interval.py': edited(R9/'ledger_fresh_interval.py', LEDGER_EDITS, 'ledger_fresh_interval', True),
             'test_wp16_preadvance.py': edited(R9/'test_wp16_preadvance.py', TEST_EDITS, 'test_wp16_preadvance')}
    for name, text in texts.items():
        if re.search(r"[A-Za-z]:[/\\]Users", text):
            sys.exit(name+': a machine path remains')
        write(R10/name, text)
        write(DIFFS/('delta-r9-r10-'+name[:-3]+'.diff'), diff(R9/name, text, 'r9/'+name, 'r10/'+name))
    for name, base in (('compact_restart_patch.py', '9d076c80'), ('ledger_fresh_interval.py', 'cd89718b')):
        write(DIFFS/(name[:-3]+'.diff'), diff(HERE/'base'/name, texts[name], 'R/%s (%s)' % (name, base),
                                              '%s S2 r10 (%s)' % (name, short(R10/name))))
    (R10/LIBRARY).parent.mkdir(parents=True)
    shutil.copyfile(R/LIBRARY, R10/LIBRARY)
    if hashlib.sha256((R10/LIBRARY).read_bytes()).hexdigest() != LIBRARY_SHA256:
        sys.exit('library copy differs: refusing')
    # R's own driver tests: drivers_r9b.py (R's test_fresh 60fba3c7; the unseeded scenario allowed) with r10's CRP.
    harness = (HERE/'r9-check/drv/drivers_r9b.py').read_text(encoding='utf8')
    for old, new in (("S2/'r9/compact_restart_patch.py': '7afe82bf'",
                      "S2/'r10/compact_restart_patch.py': '%s'" % short(R10/'compact_restart_patch.py')),
                     ('"""S2 r9 evidence', '"""S2 r10 evidence'),
                     ('VARIANT: base (nothing preloaded) or r9 (that CRP', 'VARIANT: base (nothing preloaded) or r10 (that CRP'),
                     ('  drivers_r9.py fresh', '  drivers_r10.py fresh'), ('  drivers_r9.py prepared', '  drivers_r10.py prepared'),
                     ('  drivers_r9.py scenario', '  drivers_r10.py scenario')):
        if harness.count(old) != 1:
            sys.exit('drivers harness: seam count %d: %r' % (harness.count(old), old))
        harness = harness.replace(old, new)
    compile(harness, 'drivers_r10', 'exec')
    write(CHECK/'drv'/'drivers_r10.py', harness)
    runner = (HERE/'r9-check/run_tests_r9.py').read_text(encoding='utf8')
    old = '"""S2 r9 harness (run_tests_r8.py with a fail-closed seed check): run_tests_r9.py'
    if runner.count(old) != 1:
        sys.exit('test harness: seam count %d' % runner.count(old))
    runner = runner.replace(old, '"""S2 r10 harness (run_tests_r9.py, unchanged but for this line): run_tests_r10.py')
    compile(runner, 'run_tests_r10', 'exec')
    write(CHECK/'run_tests_r10.py', runner)
    for path in sorted(R10.iterdir())+sorted(DIFFS.iterdir())+[R10/LIBRARY, CHECK/'drv'/'drivers_r10.py',
                                                             CHECK/'run_tests_r10.py']:
        if path.is_file():
            print(short(path), path.relative_to(HERE))


if __name__ == '__main__':
    main()
