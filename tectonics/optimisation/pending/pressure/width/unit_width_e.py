"""Unit tests and planted mutants for (ce), the exterior mesh deviation sum (design r2 addendum).

Usage: unit_width_e.py frozen:<after> frozen:<before> OUT_JSON
  after  = base + b + c + ce (compose_width_r2.py), before = base + b + c (E before ce)
Synthetic inputs only; nothing is built from a record. Sections:
  T  transforms: every composed file matches WIDTH_COMPOSITION.json along its transform chain; ce applied to
     the before E reproduces the after E byte for byte; ce refuses a second application, an unpinned input,
     and an input with one comparison block missing (anchor count 2).
  P  pass/fail cannot flip, per builder (build_exterior_mesh, _build_exterior_mesh_record), from the AST:
     - removing the one inserted statement gives the before builder exactly (ast.dump equal), so every
       statement up to and including the exact `total_error > width` check is the before code;
     - the inserted statement immediately follows that check in the same block;
     - after it, total_error is read once only, as geometry_volume_max_deviation_m3=_enc(total_error),
       and never assigned again;
     - every other top-level definition of E is unchanged; only the helper and its constant are new.
  H  E._stored_deviation: the same AST as M's, and unit_width.deviation_properties (outward, relative
     excess < 2**-64, <= width, 0 -> 0, refuses unchecked input).
  F  the inserted text is float-free (unit_width.float_free).
  M  planted mutants, each of which must be caught: round-down, min dropped, rounding before the check.
Exit 0 only if the clean build passes everything and every mutant is caught.
"""
import ast
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# top-level names carry their occurrence: E defines build_exterior_mesh twice (the native builder,
# then a compact-context wrapper that calls it as _build_exterior_mesh_native)
BUILDERS = ('build_exterior_mesh#1', '_build_exterior_mesh_record#1')
INSERT = 'total_error = _stored_deviation(total_error, width)'
NEW_NAMES = {'DEVIATION_STORED_BITS#1', '_stored_deviation#1'}
E_FILE = 'integration_exterior_mesh.py'


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


unit = _load(HERE/'unit_width.py', 'unit_width')
ce = _load(HERE/'width_deviation_bound_exterior.py', 'width_deviation_bound_exterior')


def package_of(runtime):
    kind, _, folder = runtime.partition(':')
    if kind != 'frozen':
        raise SystemExit('runtimes must be frozen:<folder>')
    return Path(folder).resolve()/'src'/'atlas_tectonics'


def _is_insert(node):
    return isinstance(node, ast.Assign) and ast.unparse(node) == INSERT


def _is_check(node):
    return (isinstance(node, ast.If) and ast.unparse(node.test) == 'total_error > width' and not node.orelse
            and len(node.body) == 1 and isinstance(node.body[0], ast.Raise))


def _top_level(source):
    out, seen = {}, {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign):
            name = ast.unparse(node.targets[0])
        else:
            continue
        seen[name] = seen.get(name, 0)+1
        out['%s#%d' % (name, seen[name])] = node
    return out


def pass_fail_proof(after_source, before_source, check, tag):
    after, before = _top_level(after_source), _top_level(before_source)
    changed = {name for name in after.keys() | before.keys()
               if name not in before or name not in after or ast.dump(after[name]) != ast.dump(before[name])}
    check.require(changed == set(BUILDERS) | NEW_NAMES, tag, 'changed top-level definitions', sorted(changed))
    for name in BUILDERS:
        if name not in after or name not in before:
            check.require(False, tag, name, 'missing builder')
            continue
        fn = copy.deepcopy(after[name])
        inserts = []
        for node in ast.walk(fn):
            for field in ('body', 'orelse', 'finalbody'):
                block = getattr(node, field, None)
                if isinstance(block, list):
                    inserts += [(block, i) for i, stmt in enumerate(block) if _is_insert(stmt)]
        check.require(len(inserts) == 1, tag, name, 'inserted statements', len(inserts))
        if len(inserts) != 1:
            continue
        block, i = inserts[0]
        check.require(i > 0 and _is_check(block[i-1]), tag, name, 'insert does not directly follow the exact check')
        line = block[i].lineno
        del block[i]
        check.require(ast.dump(fn) == ast.dump(before[name]), tag, name, 'builder differs beyond the insert')
        reads = [n for n in ast.walk(after[name]) if isinstance(n, ast.Name) and n.id == 'total_error'
                 and n.lineno > line]
        stores = [n for n in reads if not isinstance(n.ctx, ast.Load)]
        check.require(not stores, tag, name, 'total_error assigned after the insert')
        header = [kw for node in ast.walk(after[name]) if isinstance(node, ast.Call) for kw in node.keywords
                  if kw.arg == 'geometry_volume_max_deviation_m3' and isinstance(kw.value, ast.Call)
                  and ast.unparse(kw.value) == '_enc(total_error)' and kw.value.lineno > line]
        check.require(len(reads) == 1 and len(header) == 1 and header[0].value.args[0] is reads[0], tag, name,
                      'total_error read after the insert other than the stored header', len(reads))


def transform_checks(after_pkg, before_pkg, check):
    folder = after_pkg.parents[1]
    manifest = json.loads((folder/'WIDTH_COMPOSITION.json').read_text(encoding='utf8'))
    chain = {}
    for entry in manifest['transforms']:
        name = Path(entry['file']).name
        if name in chain:
            check.require(entry['input_sha256'] == chain[name], 'transform chain broken', name, entry['transform'])
        chain[name] = entry['output_sha256']
    for name, want in chain.items():
        got = hashlib.sha256((after_pkg/name).read_bytes()).hexdigest()
        check.require(got == want, 'composed file differs from its last transform', name)
    before = (before_pkg/E_FILE).read_bytes().decode('utf8')
    after = (after_pkg/E_FILE).read_bytes().decode('utf8')
    check.require(ce.transform_exterior_mesh(before) == after, 'ce on the before E does not give the after E')
    one_block = before.replace(ce.CHECK_OLD, '', 1)
    for label, source, kwargs in (('second application', after, {}), ('unpinned input', before+'\n', {}),
                                  ('one comparison block missing', one_block, dict(allow_unreviewed_input=True))):
        try:
            ce.transform_exterior_mesh(source, **kwargs)
            check.require(False, 'ce transform accepted', label)
        except ValueError:
            check.require(True)


def helper_checks(env, after_pkg, check, stored):
    e_fn = _top_level((after_pkg/E_FILE).read_text(encoding='utf8')).get('_stored_deviation#1')
    m_source = (after_pkg/'integration_differential_mesh.py').read_text(encoding='utf8')
    m_fn = _top_level(m_source).get('_stored_deviation#1')
    check.require(e_fn is not None and m_fn is not None and ast.dump(e_fn) == ast.dump(m_fn),
                  'E and M stored-deviation helpers differ')
    bits = env['E'].DEVIATION_STORED_BITS
    check.require(bits == unit.DEVIATION_BITS, 'E stored bits', bits)
    unit.deviation_properties(stored, check)


MUTANTS = (
    ('ce: stores a round-down', 'helper', ('return min(-((-total)//quantum)*quantum, width)',
                                           'return min((total//quantum)*quantum, width)')),
    ('ce: stored value not capped at width', 'helper', ('return min(-((-total)//quantum)*quantum, width)',
                                                        'return -((-total)//quantum)*quantum')),
    ('ce: rounds before the exact check (first builder)', 'source', (ce.CHECK_NEW, INSERT.join(
        ('        ', '\n'+ce.CHECK_OLD)))),
    ('ce: rounds before the exact check (second builder)', 'source-last', (ce.CHECK_NEW, INSERT.join(
        ('        ', '\n'+ce.CHECK_OLD)))),
)


def run_mutants(env, after_pkg, before_source, clean_failures):
    source = (after_pkg/E_FILE).read_text(encoding='utf8')
    results = []
    for label, kind, (old, new) in MUTANTS:
        check, raised = unit.Checks(), None
        try:
            if kind == 'helper':
                namespace = unit.mutated_namespace(env['E'], source, ((old, new),))[0]
                unit.deviation_properties(namespace['_stored_deviation'], check)
            else:
                if source.count(old) != 2:
                    raise ValueError('mutant anchor must occur exactly twice')
                at = source.find(old) if kind == 'source' else source.rfind(old)
                pass_fail_proof(source[:at]+new+source[at+len(old):], before_source, check, 'mutant')
        except Exception as error:      # noqa: BLE001 - an exception is a catch only if it is a refusal
            raised = error
        new_failures = [f for f in check.failures if f not in clean_failures]
        caught = bool(new_failures) or type(raised).__name__ == 'VolumeError'
        first = sorted(set(new_failures))[:2]+([] if raised is None else ['raised %s: %s' % (type(raised).__name__,
                                                                                          raised)])
        results.append(dict(mutant=label, caught=caught, first_failures=first, failing_checks=len(new_failures)))
        print('MUTANT %-52s %s %s' % (label, 'CAUGHT' if caught else 'MISSED', first[:2]), flush=True)
    return results


def main():
    after_runtime, before_runtime, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    after_pkg, before_pkg = package_of(after_runtime), package_of(before_runtime)
    env = unit.setup(after_runtime)
    check = unit.Checks()
    loaded = Path(env['E'].__file__).resolve()
    check.require(loaded == (after_pkg/E_FILE).resolve(), 'loaded E is not the after runtime', loaded)
    before_source = (before_pkg/E_FILE).read_text(encoding='utf8')
    transform_checks(after_pkg, before_pkg, check)
    pass_fail_proof((after_pkg/E_FILE).read_text(encoding='utf8'), before_source, check, 'clean')
    helper_checks(env, after_pkg, check, env['E']._stored_deviation)
    for label, text in (('ce-helper', ce.HELPER_NEW), ('ce-check', ce.CHECK_NEW)):
        for problem in unit.float_free(text):
            check.require(False, 'float use in', label, problem)
    print('clean build: %d checks, %d failures' % (check.count, len(check.failures)), flush=True)
    for failure in check.failures[:20]:
        print('  FAIL', failure)
    mutants = run_mutants(env, after_pkg, before_source, set(check.failures))
    missed = [m['mutant'] for m in mutants if not m['caught']]
    out.write_text(json.dumps(dict(after=after_runtime, before=before_runtime, checks=check.count,
                                   failures=check.failures, mutants=mutants,
                                   loaded_sources=unit.runtime_sources(env['rc1_env'])), indent=1), encoding='utf8')
    print('UNIT WIDTH E %s: %d checks, %d failures; mutants caught %d/%d%s' % (
        'PASS' if not check.failures and not missed else 'FAIL', check.count, len(check.failures),
        len(mutants)-len(missed), len(mutants), (' MISSED %r' % missed) if missed else ''))
    raise SystemExit(1 if check.failures or missed else 0)


if __name__ == '__main__':
    main()
