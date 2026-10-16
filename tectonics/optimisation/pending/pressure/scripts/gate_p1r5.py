"""P1 r5 transport gate checks (refuter 16 Oct finding 1): the gate must admit the real small case and
refuse at each bound, and every mutant must fail.

Real numbers: sm6 (c/w6f4, r4) recorded raw 2921506 bytes, decoded bound 75428604, policy child_bytes
536870912; r4 refused it (decoded > PARENT_STORAGE//4). Mutants, compiled from the loaded candidate's own
_transport_fits source into a copy of the module namespace:
  r4-rule      the decoding bound against the parent share (r3/r4)
  no-decoded   the decoding bound unchecked
  no-raw       the raw size unchecked against the parent share
  strict-lt    decoded < child_bytes (boundary)
Usage: gate_p1r5.py <candidate frozen:|test:folder>
"""
import inspect
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402

SIZE, DECODED, CHILD = 2921506, 75428604, 536870912
MUTANTS = (
    ('r4-rule', 'decoded <= child_bytes', 'decoded <= D.PARENT_STORAGE//4'),
    ('no-decoded', ' and decoded <= child_bytes', ''),
    ('no-raw', 'size <= D.PARENT_STORAGE//4 and ', ''),
    ('strict-lt', 'decoded <= child_bytes', 'decoded < child_bytes'),
)


def failures(D, fits):
    share = D.PARENT_STORAGE//4
    cases = (
        ('real small case admitted', (SIZE, DECODED, CHILD), True),
        ('decoded == child_bytes admitted', (SIZE, CHILD, CHILD), True),
        ('decoded > child_bytes refused', (SIZE, CHILD+1, CHILD), False),
        ('raw == parent share admitted', (share, DECODED, CHILD), True),
        ('raw > parent share refused', (share+1, DECODED, CHILD), False),
        ('raw > batch cap refused', (D.MAX_BATCH_INPUT+1, DECODED, CHILD), False),
    )
    return [name for name, args, want in cases if bool(fits(*args)) is not want]


def main():
    rc1_env.install(sys.argv[1])
    from atlas_tectonics import integration_parallel_dispatch as D
    from atlas_tectonics import integration_pressure_walls as W
    bad = []
    control = failures(D, W._transport_fits)
    print('control', 'PASS' if not control else 'FAIL %r' % control, flush=True)
    if control:
        bad.append('control')
    wired = inspect.getsource(W._Run).count('_transport_fits(size, decoded, policy.child_bytes)') == 1
    print('gate wired in _Run', wired, flush=True)
    if not wired:
        bad.append('wiring')
    source = textwrap.dedent(inspect.getsource(W._transport_fits))
    for label, old, new in MUTANTS:
        if source.count(old) != 1:
            raise SystemExit('mutant anchor not found once: %r' % old)
        namespace = dict(vars(W))
        exec(compile(source.replace(old, new), '<mutant %s>' % label, 'exec'), namespace)  # noqa: S102
        fails = failures(D, namespace['_transport_fits'])
        print(label, 'CAUGHT %r' % fails[0] if fails else 'MISSED', flush=True)
        if not fails:
            bad.append(label)
    print('GATE PASS' if not bad else 'GATE FAIL %r' % bad, flush=True)
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
