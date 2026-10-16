"""WP22/WP23 (profile-ranked): the zero test of the directed decimal interval product, without a generator.

Source transform of atlas_tectonics/integration_q2_directed.py. In the profile of the full
candidate on the hardest IV2 interfaces, `_Intervals.mul` runs about 1.2e8 times and its
line `if any(x.is_zero() for x in (*a, *b)):` alone costs about 12% of interface CPU (a
tuple build plus a generator per call). For interval pairs the same test is the short-
circuit chain a[0].is_zero() or a[1].is_zero() or b[0].is_zero() or b[1].is_zero(): the
same Decimal method calls in the same order, stopping at the same element, so the branch
taken and every product are identical. Inputs that are not pairs keep the original line.
Record identity: numbers byte-identical; the module's source digest (folded into the
moving-face and moving-interface digests written into records) changes. Coordinator D-b
(16 Oct 2026) allows digest-only record changes for new intervals, judged per change by
field-by-field parity.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '7f73fa1aba238c2eeb3e0cdc0b5785bf07bf63663f60ed62d68850cfcdd466ff': 'RC1 composed-r1 runtime-src',
}
OLD = '        if any(x.is_zero() for x in (*a, *b)):\n'
NEW = ('        if ((a[0].is_zero() or a[1].is_zero() or b[0].is_zero() or b[1].is_zero())\n'
       '                if len(a) == 2 == len(b) else any(x.is_zero() for x in (*a, *b))):\n')


def transform(source, *, allow_unreviewed_input=False):
    if NEW in source:
        raise ValueError('q2 zero-test transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('q2 input is not the reviewed module; pass allow_unreviewed_input and re-run parity')
    if source.count(OLD) != 1:
        raise ValueError('q2 zero-test anchor must occur exactly once')
    return source.replace(OLD, NEW)
