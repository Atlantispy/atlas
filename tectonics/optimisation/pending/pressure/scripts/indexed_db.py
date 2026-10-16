"""P1 r4 D-b on the indexed spatial-state route, at the reviewed helper fixture's scale.

No small end-to-end case reaches the indexed route: indexed states arise only from a compact
mesh (a compact reopen), and the prepared driver still refuses compact end meshes. So this
checks the one thing r4 changes, the bytes a worker receives, on the indexed route itself:
the reviewed fixture test_pressure_indexed_patch (imported read-only from its own folder,
compact-geometry-r1, in a fresh process; byte-identical to composed-r2/helpers) builds the
same regions on the legacy route, the compact (indexed) route and the mixed route. The
candidate module's own _enc and _plain_planes (compiled from its file against the fixture's
package) must then give:
  - for every indexed and mixed region after _plain_planes, an encoding byte-identical to the
    legacy region's (deep values AND types, dict key order);
  - _enc refusing the indexed region without _plain_planes (control);
  - legacy regions passing through _plain_planes unchanged (the same object).
Mutants of _plain_planes (reversed pairs, region unchanged, dropped pairs) must be CAUGHT.
The fixture's own parity test (moving_wall_integrals equal on legacy and owned regions) is run too.
Usage: indexed_db.py <candidate integration_pressure_walls.py> <compact-geometry-r1 folder>
"""
import ast
from fractions import Fraction
import json
from pathlib import Path
import sys
import unittest


def functions(path, names):
    tree = ast.parse(Path(path).read_text(encoding='utf8'))
    found = {node.name: ast.get_source_segment(Path(path).read_text(encoding='utf8'), node)
             for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names}
    if set(found) != set(names):
        raise SystemExit('INDEXED-DB FAIL missing functions %r' % (set(names)-set(found)))
    return found


def build(sources, V, replace=None):
    namespace = {'__name__': 'atlas_tectonics._ps_probe', '__package__': 'atlas_tectonics',
                 'Fraction': Fraction, 'V': V, 'sys': sys}
    for name, source in sources.items():
        if replace is not None and name == replace[0]:
            if source.count(replace[1]) != 1:
                raise SystemExit('INDEXED-DB FAIL mutant anchor %r' % replace[1])
            source = source.replace(replace[1], replace[2])
        exec(compile(source, '<candidate %s>' % name, 'exec'), namespace)  # noqa: S102
    return namespace


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf8')


def compare(T, ns):
    """Failing checks for one _enc/_plain_planes namespace over the fixture's routes."""
    enc, plain = ns['_enc'], ns['_plain_planes']
    fails, regions_seen, pairs_seen = [], 0, 0
    with T.stubs():
        for endpoint, now in (('end', 1), ('start', 0)):
            legacy = T.regions(T.legacy_state(now), T.FIX.natives, endpoint)
            with T.no_whole_exports():
                compact = T.regions(T.compact_state(now), T.FIX.compact, endpoint)
                mixed = T.regions(T.compact_state(now), T.FIX.natives, endpoint)
            for label, result in (('compact', compact), ('mixed', mixed)):
                if len(result[0]) != len(legacy[0]):
                    fails.append('%s %s: region count differs' % (label, endpoint))
                    continue
                for i, (region, reference) in enumerate(zip(result[0], legacy[0], strict=True)):
                    regions_seen += 1
                    pairs_seen += len(reference.get('_physical_planes') or ())
                    try:
                        sent = canonical(enc(plain(region)))
                    except Exception as error:  # noqa: BLE001
                        fails.append('%s %s region %d not sent: %s' % (label, endpoint, i, error))
                        continue
                    if sent != canonical(enc(reference)):
                        fails.append('%s %s region %d encodes differently from legacy' % (label, endpoint, i))
                    planes = region.get('_physical_planes')
                    if planes is not None and type(planes) is not tuple:
                        try:
                            enc(region)
                            fails.append('%s %s region %d: _enc accepted %s' % (label, endpoint, i, type(planes).__name__))
                        except TypeError:
                            pass
            for region in legacy[0]:
                if plain(region) is not region:
                    fails.append('legacy %s: a plain region was rebuilt' % endpoint)
            del legacy, compact, mixed
    if not pairs_seen:
        fails.append('vacuous: no physical-plane pairs')
    return fails, regions_seen, pairs_seen


MUTANTS = (
    ('reversed', '_plain_planes', 'tuple(iter(planes))', 'tuple(reversed(tuple(iter(planes))))'),
    ('unchanged', '_plain_planes', "return dict(region, _physical_planes=tuple(iter(planes)))", 'return region'),
    ('dropped', '_plain_planes', 'tuple(iter(planes))', 'tuple(iter(planes))[:-1]'),
)


def main():
    candidate, fixture = Path(sys.argv[1]), Path(sys.argv[2])
    sys.path.insert(0, str(fixture))
    import test_pressure_indexed_patch as T
    T.setUpModule()
    sources = functions(candidate, ('_enc', '_plain_planes'))
    bad = []
    fails, regions_seen, pairs_seen = compare(T, build(sources, T.V))
    print('control', 'PASS' if not fails else 'FAIL', 'regions', regions_seen, 'pairs', pairs_seen, flush=True)
    for failure in fails:
        print('  ', failure, flush=True)
    if fails:
        bad.append('control')
    for label, name, old, new in MUTANTS:
        fails, _, _ = compare(T, build(sources, T.V, (name, old, new)))
        print('mutant', label, 'CAUGHT: '+fails[0][:140] if fails else 'MISSED', flush=True)
        if not fails:
            bad.append(label)
    # TestCase.run directly: a TestSuite would call setUpModule a second time, which the fixture refuses.
    outcome = unittest.TestResult()
    T.PressureIndexedTests('test_regions_parity_legacy_compact_and_mixed').run(outcome)
    for _, trace in outcome.errors+outcome.failures:
        print(trace, flush=True)
    passed = outcome.wasSuccessful() and outcome.testsRun == 1
    print('fixture parity test', 'PASS' if passed else 'FAIL (ran %d)' % outcome.testsRun, flush=True)
    if not passed:
        bad.append('fixture-parity')
    T.tearDownModule()
    print('INDEXED-DB PASS' if not bad else 'INDEXED-DB FAIL %r' % bad, flush=True)
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
