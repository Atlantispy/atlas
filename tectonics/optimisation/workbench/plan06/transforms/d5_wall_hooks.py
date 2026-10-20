"""D5: GMP-resident twins of the wall-measure kernels (_rotated_normal, _clip2, _line).

Source transform of atlas_tectonics/integration_wall_measures.py (reviewed input below). The file gains only
guarded hooks: each of the three functions first calls its twin in the new module
integration_wall_measures_gmp (shared native primitives in the new module integration_exact_twin) and runs
its own, unchanged code whenever the twin returns DECLINED. The twins compute the same rationals and return
the same objects (new Fractions, or the reference's own input objects where it returns those), make the same
work calls and reservations, and add only a NATIVE_RETAINED surcharge for natives kept across Taylor steps.
Record identity: numbers and representations identical; the file digests change and two files are added
(D-b).
"""
from hashlib import sha256

INPUT_SHA256 = {
    'd6b7d472246af0e8a9415b01465f035c0c860c7b358126fd1bba5c0025e671e0':
        'integration_wall_measures.py of the composed candidates final-f2 and jets-r1',
    'a7a7dc432a45439aa47d912fd6d1424be7f7c1081d03bd079aa075be6550ebef':
        'N9 test-only W from ps/c/wr1; C6 proof required, not a selected Plan31 candidate',
}
MARK = '# D5: GMP-resident twins'
HOOK = '''    twin = _D5.{call}
    if twin is not _D5.DECLINED:
        return twin
'''
REPLACEMENTS = (
    ('    middle, half = (t0+t1)/2, (t1-t0)/2\n    derivative = O._cross(omega, normal)\n',
     HOOK.format(call='rotated_normal(normal, omega, t0, t1, level, arena)')
     + '    middle, half = (t0+t1)/2, (t1-t0)/2\n    derivative = O._cross(omega, normal)\n'),
    ('    """Counterclockwise convex polygon clipped by a*u+b*v+c >= 0."""\n    if arena is not None:\n',
     '    """Counterclockwise convex polygon clipped by a*u+b*v+c >= 0."""\n'
     + HOOK.format(call='clip2(poly, line, arena)') + '    if arena is not None:\n'),
    ('def _line(face, normal, offset=0):\n    return O._dot(normal, face[1]),',
     'def _line(face, normal, offset=0):\n' + HOOK.format(call='line(face, normal, offset)')
     + '    return O._dot(normal, face[1]),'),
)
TAIL = '''

{mark} of _rotated_normal, _clip2 and _line (integration_wall_measures_gmp);
# a declined call runs the code above. Imported last, so the module is complete when the twins record
# its reference objects.
from . import integration_wall_measures_gmp as _D5  # noqa: E402
_D5.attach(__name__)
'''.format(mark=MARK)


def transform(source, *, allow_unreviewed_input=False):
    if MARK in source or '_D5' in source:
        raise ValueError('D5 transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in INPUT_SHA256:
        raise ValueError('wall-measures input is not the reviewed file')
    for name in ('def _rotated_normal(', 'def _clip2(', 'def _line('):
        if source.count(name) != 1:
            raise ValueError('D5 expects exactly one %s' % name)
    for old, _ in REPLACEMENTS:
        if source.count(old) != 1:
            raise ValueError('D5 anchor must occur exactly once: %r' % old.splitlines()[0])
    for old, new in REPLACEMENTS:
        source = source.replace(old, new)
    return source.rstrip('\n') + '\n' + TAIL


if __name__ == '__main__':
    import sys
    from pathlib import Path
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    if dst.exists():
        raise SystemExit('%s exists' % dst)
    before = src.read_bytes()
    after = transform(before.decode('utf8')).encode('utf8')
    dst.write_bytes(after)
    print(src.name, sha256(before).hexdigest(), '->', sha256(after).hexdigest())
