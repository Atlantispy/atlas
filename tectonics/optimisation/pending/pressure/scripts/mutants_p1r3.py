"""P1 r3 mutants (refuter finding 4): unit_ps.py section 5 must FAIL on every mutant and pass unmutated.

Each mutant is compiled from the loaded candidate's own function source into a copy of the module
namespace (the loaded module is never changed, except _decoded_bound swapped for one call):
  enter-unreferenced  reserve(...).__enter__() on an unreferenced generator context (released at once)
  no-booking          the decoded bound is never booked
  short-bound         _decoded_bound drops the interface route's 65536 constant
  raw-only-bound      _decoded_bound books the raw size only
Usage: mutants_p1r3.py <candidate frozen:folder>
"""
import inspect
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402
import unit_ps  # noqa: E402

BOOK = "holds.enter_context(ledger.reserve(decoded, category='pressure-wall-inputs'))"
MUTANTS = (
    ('enter-unreferenced', '_open_ledger', BOOK, "ledger.reserve(decoded, category='pressure-wall-inputs').__enter__()"),
    ('no-booking', '_open_ledger', '    '+BOOK+'\n', ''),
    ('short-bound', '_decoded_bound', '+65536+4*len(raw)', '+4*len(raw)'),
    ('raw-only-bound', '_decoded_bound', '_decoded_json_capacity(raw)+65536+4*len(raw)', 'len(raw)'),
)


def mutant(W, name, old, new):
    source = textwrap.dedent(inspect.getsource(getattr(W, name)))
    if source.count(old) != 1:
        raise SystemExit('mutant anchor not found once in %s: %r' % (name, old))
    namespace = dict(vars(W))
    exec(compile(source.replace(old, new), '<mutant %s>' % name, 'exec'), namespace)  # noqa: S102
    return namespace[name]


def main():
    rc1_env.install(sys.argv[1])
    from atlas_tectonics import integration_pressure_walls as W
    from atlas_tectonics import resources as RS
    bad = []
    control = unit_ps.open_ledger_failures(W, RS, W._open_ledger)
    print('control', 'PASS' if not control else 'FAIL %r' % control, flush=True)
    if control:
        bad.append('control')
    for label, name, old, new in MUTANTS:
        fn = mutant(W, name, old, new)
        saved = W._decoded_bound
        try:
            if name == '_decoded_bound':
                W._decoded_bound = fn
                fails = unit_ps.open_ledger_failures(W, RS, W._open_ledger)
            else:
                fails = unit_ps.open_ledger_failures(W, RS, fn)
        finally:
            W._decoded_bound = saved
        print(label, 'CAUGHT %r' % fails[0] if fails else 'MISSED', flush=True)
        if not fails:
            bad.append(label)
    print('MUTANTS PASS' if not bad else 'MUTANTS FAIL %r' % bad, flush=True)
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
