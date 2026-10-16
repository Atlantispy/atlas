"""Parallel adoption of the complementary-cut certificate (companion of complementary_cut.py).

Source transform of atlas_tectonics/integration_parallel_results.py. Without it every
worker-made record with the rule 'exact-zero-area-from-complementary-moving-cuts' is
refused (the rule is not in CERTIFICATE) and the parent recomputes the query serially:
same record, about 5 CPU-s more per proved query.

1. CERTIFICATE gains the rule with its only optional key, zero_area_certificate
   (leaves 1 and met True are then enforced by the existing zero-rule check).
2. The digest check compares that certificate's source_sha256 with the PARENT's loaded
   geometry constant _CP_SOURCE_SHA256 (the sha256 of the certificate helper text), not
   with the interface-exclusion module's digest, and never with a worker-echoed value.
   A parent without the constant refuses. All other rules are checked exactly as before.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '8320e243f50e19e7bba281a87441231e03fc53a8dfa74b60e842d75b3dbbce22': 'RC1 composed-r1 runtime-src',
}
RULE = 'exact-zero-area-from-complementary-moving-cuts'

OLD_RULES = "    'exact-zero-area-from-actual-moving-halfspace': ZERO_AREA,\n"
NEW_RULES = ("    'exact-zero-area-from-actual-moving-halfspace': ZERO_AREA,\n"
             "    '%s': ZERO_AREA,  # geometry transform complementary_cut\n" % RULE)

OLD_CHECK = '''        if extra is not None:
            detail = record[extra]
            # The PARENT's loaded module digest, not one echoed by the worker.
            if type(detail) is not dict or detail.get('source_sha256') != digests[extra]:
                return False
'''
NEW_CHECK = '''        if extra is not None:
            detail = record[extra]
            # The PARENT's loaded module digest, not one echoed by the worker.
            expected = digests[extra]
            if rule == '%s':
                # Issued by the geometry module's certificate helper: the parent's loaded constant.
                from . import integration_differential_geometry as _geometry
                expected = getattr(_geometry, '_CP_SOURCE_SHA256', None)
            if type(expected) is not str or type(detail) is not dict or detail.get('source_sha256') != expected:
                return False
''' % RULE


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('complementary-cut adoption anchor must occur exactly once: ' + old[:60])
    return source.replace(old, new)


def transform(source, *, allow_unreviewed_input=False):
    if RULE in source:
        raise ValueError('complementary-cut adoption already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('adoption input is not the reviewed module; pass allow_unreviewed_input and re-run parity')
    source = _once(source, OLD_RULES, NEW_RULES)
    source = _once(source, OLD_CHECK, NEW_CHECK)
    return source
