"""Make tests/test_s1_closed_reuse_r2.py from r1 (exact-once edits): adds last-index and exterior stale mutants.

Usage: python -B make_test_s1_r2.py TESTS_DIR   (r1 must be f3528707...; r2 must not exist)
"""
from hashlib import sha256
from pathlib import Path
import sys

folder = Path(sys.argv[1])
raw = (folder/'test_s1_closed_reuse.py').read_bytes()
if not sha256(raw).hexdigest().startswith('f3528707') or b'\r' in raw:
    raise SystemExit('unexpected r1')
text = raw.decode('utf8')


def once(old, new):
    global text
    if text.count(old) != 1:
        raise SystemExit('anchor not found exactly once: %r' % old[:80])
    text = text.replace(old, new)


once('"""S1 tests: closed_owned_r4 against r5', '"""S1 tests r2: closed_owned_r4 against r5')
once("""   wrong certificate without refusing.
""", """   wrong certificate without refusing.
   R2 adds stale mutants on the LAST cell, the last interior face, the exterior face and a ledger-preserving shift,
   so an r5 that compared only the first energy or face would fail here (independent review, 16 Oct).
""")
# Inserted as source text of the test's MUTANTS dict: every backslash-n below is written to the file as the two
# characters backslash, n (raw strings), so the generated test holds ordinary escaped string literals.
put = r"    del states\n    ar.put(%s, %d, ar.op('add', %s[1][%d], G.mpq(1, 7)))\n"
once("""    'zero-theta-confusion':""", r"""    'energies-last': ([("    del states\n", "%s")], 'full', 'certified energies differ'),
    'faces-last-interior': ([("    del states\n", "%s")], 'full', 'certified face transfers differ'),
    'faces-exterior': ([("    del states\n", "%s")], 'full', 'certified face transfers differ'),
    'ledger-preserving-shift': ([("    del states\n", "    del states\n"
                                  "    ar.put(dq, 6, ar.op('add', dq[1][6], G.mpq(1, 7)))\n"
                                  "    ar.put(difference, 3, ar.op('subtract', difference[1][3], G.mpq(1, 7)))\n"
                                  "    ar.put(difference, 5, ar.op('add', difference[1][5], G.mpq(1, 7)))\n")],
                                'full', 'certified energies differ'),
    'zero-theta-confusion':""" % (put % ('difference', 5, 'difference', 5),
                                 put % ('dq', 6, 'dq', 6), put % ('dq', 7, 'dq', 7)))
out = folder/'test_s1_closed_reuse_r2.py'
if out.exists():
    raise SystemExit('r2 exists')
compile(text, out.name, 'exec')
out.write_bytes(text.encode('utf8'))
print(out.name, sha256(text.encode('utf8')).hexdigest())
