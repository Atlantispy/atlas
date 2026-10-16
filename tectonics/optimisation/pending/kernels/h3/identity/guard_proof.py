"""H3 on Heat's loaded-identity guard: the path that stopped q06's h3 proof arm, checked in the small lane.

Child (one fresh process per layout):  python -B guard_proof.py child LAYOUT
  Imports private_heat_native_issuer_r13 from LAYOUT's paths, which captures its loaded-dependency identity at
  import (as the control's child does), then makes the first certification-kernel call (solve_enclosure, which
  loads the compiled route on first use), runs the issuer's own _verify_implementation() (the call that raised in
  arm 1), and repeats with a second call at another precision (one the helper has not seen, so an upper-case
  settings memo would change). Also compares fresh LoadedIdentity digests of the
  same modules, and of the compiled helper module itself, before and after. Prints one JSON line.
Driver:  python -B guard_proof.py drive OUT LAYOUT_R3 LAYOUT_R2 H2_HELPERS TRANSFORM HELPER_R2
  OUT must not exist. Builds two well-formed mutant layouts from H2_HELPERS with TRANSFORM (the H3 transform)
  and ../build_layout.py: m1 = the r3 transform with the route cache named upper-case (_H3_ROUTE); m2 = the r3
  kernel pinned to HELPER_R2 (the r2 helper whose settings memo is upper-case _SETTINGS). Runs the child on
  LAYOUT_R3 (expect: guard passes, every identity equal), LAYOUT_R2 (q06's l3: guard refuses), m1 (guard
  refuses) and m2 (kernel guard passes, since the helper is outside Heat's walk; helper identity changes).
  Writes OUT/report.json; exit 0 only if all four behave as expected.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

KERNEL = 'private_heat_certification_kernel_r1.py'
RESOURCES = 'private_heat_certification_resources_r1.py'
COMPILED = 'private_heat_compiled_dot_r1.py'
CHANGED = 'Private source or loaded implementation changed'


def child(layout):
    if sys.flags.hash_randomization:   # production pins seed 0 (work units follow set order)
        raise SystemExit('set PYTHONHASHSEED=0')
    from fractions import Fraction as Q
    layout = Path(layout).resolve()
    sys.path[:0] = json.loads((layout/'control.json').read_text(encoding='utf8'))['paths']
    import private_heat_native_issuer_r13 as I
    import private_heat_loaded_identity_r1 as LI
    K = sys.modules['private_heat_certification_kernel_r1']
    modules = [m for m in I._private_modules() if m is not sys.modules[I.__name__]]
    report = dict(layout=str(layout), kernel_in_walk=K in modules,
                  kernel_sha256=sha256(Path(K.__file__).read_bytes()).hexdigest(),
                  captured_equals_fresh=I._LOADED_IMPLEMENTATION.identity == LI.LoadedIdentity(modules).identity)
    matrix = [[Q(i+j+1, 1+(i*j) % 5)+(3 if i == j else 0) for j in range(4)] for i in range(6)]
    rhs = [Q(k+1, 7) for k in range(4)]
    helper_ids = []
    for step, precision in enumerate((128, 96), 1):   # neither is in the helper's self-test (53, 200)
        bounds, _, facts = K.solve_enclosure(matrix, rhs, precision=precision)   # (bounds, Arithmetic, facts)
        report['bounds_%d' % step] = sha256(repr((bounds, facts)).encode()).hexdigest()[:16]
        try:
            I._verify_implementation()
            report['guard_%d' % step] = 'pass'
        except ValueError as error:
            report['guard_%d' % step] = 'refused: %s' % error
        report['fresh_equal_%d' % step] = I._LOADED_IMPLEMENTATION.identity == LI.LoadedIdentity(modules).identity
        helper = sys.modules.get(K._H3_NAME)
        helper_ids.append(None if helper is None else LI.LoadedIdentity([helper]).identity)
    report['route'] = K.h3_status()['route']
    report['helper_identity_equal'] = helper_ids[0] is not None and helper_ids[0] == helper_ids[1]
    print(json.dumps(report))


def build_mutant(out, name, h2_helpers, transform, base_layout, *, upper_route=False, helper=None):
    spec = importlib.util.spec_from_file_location('h3_mutant_transform_'+name, transform)
    T = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(T)
    if upper_route:
        assert T.HELPER.count('_h3_route') >= 6
        T.HELPER = T.HELPER.replace('_h3_route', '_H3_ROUTE')
    if helper is not None:
        T.COMPILED_SOURCE = Path(helper)
        T.COMPILED_SHA256 = sha256(Path(helper).read_bytes()).hexdigest()
    h3 = out/(name+'-h3')
    h3.mkdir()
    kin, rin = (Path(h2_helpers)/KERNEL).read_bytes(), (Path(h2_helpers)/RESOURCES).read_bytes()
    kout = T.transform(kin.decode('utf8')).encode('utf8')
    rout = T.repin(rin.decode('utf8'), sha256(kin).hexdigest(), sha256(kout).hexdigest()).encode('utf8')
    (h3/KERNEL).write_bytes(kout)
    (h3/RESOURCES).write_bytes(rout)
    shutil.copyfile(T.COMPILED_SOURCE, h3/COMPILED)
    subprocess.run([sys.executable, '-B', '-I', str(Path(__file__).resolve().parents[1]/'build_layout.py'),
                    str(base_layout), str(out/name), str(h3)], check=True)
    return out/name


def run_child(layout):
    env = dict(os.environ, PYTHONHASHSEED='0')
    env.pop('PYTHONPATH', None)
    done = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), 'child', str(layout)],
                          capture_output=True, text=True, env=env)
    lines = [x for x in done.stdout.splitlines() if x.startswith('{')]
    return json.loads(lines[-1]) if done.returncode == 0 and lines else dict(exit=done.returncode,
                                                                               stderr=done.stderr[-2000:])


def drive(out, r3, r2, h2_helpers, transform, helper_r2):
    out = Path(out).resolve()
    out.mkdir()
    m1 = build_mutant(out, 'm1', h2_helpers, transform, r3, upper_route=True)
    m2 = build_mutant(out, 'm2', h2_helpers, transform, r3, helper=helper_r2)
    runs = {name: run_child(layout) for name, layout in (('r3', r3), ('r2', r2), ('m1', m1), ('m2', m2))}

    def ok(r, keys):
        return all(r.get(k) == v for k, v in keys.items())
    refused = 'refused: '+CHANGED
    expect = dict(
        r3=dict(route='compiled', kernel_in_walk=True, captured_equals_fresh=True, guard_1='pass', guard_2='pass',
                fresh_equal_1=True, fresh_equal_2=True, helper_identity_equal=True),
        r2=dict(route='compiled', kernel_in_walk=True, captured_equals_fresh=True, guard_1=refused,
                fresh_equal_1=False),
        m1=dict(route='compiled', kernel_in_walk=True, captured_equals_fresh=True, guard_1=refused,
                fresh_equal_1=False),
        m2=dict(route='compiled', kernel_in_walk=True, guard_1='pass', guard_2='pass', helper_identity_equal=False))
    verdict = {name: ok(runs[name], keys) for name, keys in expect.items()}
    same_numbers = all(len({runs[n].get(key) for n in runs}) == 1 for key in ('bounds_1', 'bounds_2'))
    report = dict(runs=runs, expect=expect, verdict=verdict, same_bounds_all_layouts=same_numbers,
                  passed=all(verdict.values()) and same_numbers)
    (out/'report.json').write_text(json.dumps(report, indent=1), encoding='utf8')
    print(json.dumps(dict(verdict=verdict, same_bounds_all_layouts=same_numbers, passed=report['passed'])))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    if sys.argv[1] == 'child':
        child(sys.argv[2])
    elif sys.argv[1] == 'drive':
        sys.exit(drive(*sys.argv[2:8]))
    else:
        raise SystemExit(__doc__)
