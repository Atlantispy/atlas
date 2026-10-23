"""R1 fold mutants r4 (FOLD.md §6, §10.4; review r1 decision 6). Each mutant must make a gate or the records check fail;
each negative control must pass. Mutants act on copies, never on evidence.

    python -B mutants_r4.py tree PARITY_DIR ORIGINAL_ROOT FOLD_OUT WORK_DIR
    python -B mutants_r4.py records PARITY_DIR A_RECORD B_RECORD A2_RECORD MANIFEST WORK_DIR

r4 (23 Oct; FOLD.md §13 item 7): the sibling-layout mutant. Each folded module holding a fold_r5 data key as a
string constant (the retargeted atlas_tectonics/_private/native/wp10_zstd.dll) is a holder; CRP and LG must both be
among them. Each holder is put, with the key's file, into two fresh layouts, and its own preflight is run there:
- M12: the composition's layout. The helper sits in helpers/ beside src/, and the package is src/atlas_tectonics.
  No ancestor of helpers/ holds the key, so the module's task_file finds nothing, and its preflight must refuse.
  CRP's capture_backend is executed and must raise its FileNotFoundError. LG's reader cannot run without the
  package, so LG's refusal is static: require(CAPTURE_LIBRARY is not None, ...) must be a direct statement of a
  module-level function. Whether that function runs on the capture route is not shown here.
- N3: the folded location; the key must be found exactly once.
- N4, recorded as the claim's boundary: a helpers/ folder directly beside atlas_tectonics/ does find the key. That is
  benign, because the sha256 pin authenticates the bytes when they are loaded.
The preflight runs only the module's task_file, its CAPTURE_LIBRARY* assignments and its capture_backend, with every
module-level function those call, transitively (r4.1, 23 Oct evening: r12's task_file calls _holds), executed in
module order from its AST with __file__ set to the copy and nothing imported but pathlib. A name it cannot resolve
still ends as ERROR. Verdicts are FOUND, REFUSED or ERROR (any other outcome). A refusal for another reason is ERROR,
never REFUSED.

r3 (Plan 20 r11, 23 Oct): where the folded CRP no longer holds the qualified store lookup P20-M1 edits, P20-M1 is
RETIRED only if route_proof holds (no sys.modules access or importer call in CRP or LG, original or folded; helper-name
strings are listed with their context); otherwise it FAILS. The proof is written to mutants.json either way. M11, for each fold_r5 data key in
key_map, puts the workspace literal back in place of the package key in the folded CRP; the ast gate must fail (the
USER_PATH scan cannot see such a literal). Everything else is mutants_r2's.

tree: WORK_DIR (new) gets one byte copy of FOLD_OUT/folded; each mutant is applied, its gate run and the copy restored
(checked file by file at the end). M9 a code edit outside the declared fold (ast), M9b one qualified helper import
reverted to its bare name (ast), M10 a pinned file holding the original's stale bytes (pins), M10b a stale bare copy
importable at top level (pins). P20-M1 reverts the qualified `sys.modules.get` store name in compact_restart_patch to
the bare one: the gate compares it equal to the original's bare string, so it passes here and is recorded as
EXPECTED-FAIL; the fail-closed guard belongs to Plan 20's CRP revision (review r1 decision 6). N0: the copy passes both.
records: FOLD §6 record mutants on a copy of B's record. Each edit is followed by recomputing B's own self-IDs (deepest
first), so a mutant is caught by its edit and not by a stale ID; M8 alone forges an ID. M1 +1 ulp, M2 a non-identity
int, M3 an absolute path in a sources key, M4 a sibling pin dropped, M5 a pin left at the pre-fold sha, M6 a key the
fold did not emit, M7 a booking that grows, M8 a forged self-ID. N1 the sources table in another insertion order,
N2 A against A2 (the noise arm).
WORK_DIR/mutants.json lists each mutant, the verdict, whether it is as expected, and why.
"""
import ast
import copy
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import shutil
import sys

CRP = 'atlas_tectonics/_private/compact_restart_patch.py'
CRP_QUALIFIED = "sys.modules.get('atlas_tectonics._private.compact_restart_store')"
CRP_BARE = "sys.modules.get('compact_restart_store')"
PRIVATE = 'atlas_tectonics._private'
SOURCES = ('caller_snapshot', 'private_sources')


def _parity(parity_dir):
    sys.path.insert(0, str(Path(parity_dir).resolve()))
    import parity  # the gate revision under test, from PARITY_DIR
    return parity


def _gate(call):
    try:
        out = call()
        return ('PASS' if out.get('status') == 'PASS' else 'FAIL'), str(out)[:200]
    except Exception as error:  # every gate failure is a verdict here, never a crash of the runner
        return 'FAIL', '%s: %s' % (type(error).__name__, str(error)[:200])


def _int_site(text):
    """(start, end, new) of the first int literal >= 2 inside a function body, as character offsets in text."""
    lines = text.splitlines(True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Constant) and type(inner.value) is int and inner.value >= 2:
                row = inner.lineno - 1
                start = offsets[row] + len(lines[row].encode('utf8')[:inner.col_offset].decode('utf8'))
                end = start + len(str(inner.value))
                if text[start:end] == str(inner.value):
                    return start, end, str(inner.value + 1)
    return None


def _qualified_import(text, private):
    """(start, end, bare) of the first statement-level qualified helper import's module name, or None."""
    for match in re.finditer(r'^[ \t]*(?:from|import)[ \t]+(%s\.(\w+))\b' % re.escape(PRIVATE), text, re.M):
        if match.group(2) in private:
            return match.start(1), match.end(1), private[match.group(2)]
    return None


ROUTE = ('compact_restart_patch', 'ledger_fresh_interval')
IMPORTERS = ('import_module', '__import__', 'find_spec', 'spec_from_file_location', 'module_from_spec', 'run_module',
             'find_loader', 'load_module')
IMPORT_MODULES = ('importlib', 'imp', 'runpy', 'pkgutil', 'zipimport')
DYNAMIC = ('exec', 'eval', 'compile', 'vars', 'globals', 'locals')


def route_proof(original_root, folded, manifest):
    """r3: the AST evidence for retiring P20-M1. In both route modules, original and folded: no `sys.modules` access
    and no importer call (IMPORTERS), the only ways a module is looked up by a name string. A str constant that equals
    a composition helper's name (bare or qualified; such as a record field label) is listed with its enclosing
    expression, not refused: with no lookup by name left in the route, none of them names a module there.

    Conservative after the cold review (refuter r3: `import sys as _sys; _sys.modules` and an aliased import_module
    passed): any `.modules` or `.__dict__` attribute on any base, any 'modules' or importer-name string, any import
    of importlib, imp, runpy, pkgutil or zipimport (or from them), any name or attribute spelled as an importer, and
    any exec, eval, compile, vars, globals or locals reference counts against the proof."""
    helpers = {p.stem for p in (Path(original_root)/'helpers').glob('*.py')}    # folded, excluded and tests alike
    if not {Path(old).stem for old in manifest['modules'] if old.startswith('helpers/')} <= helpers:
        raise SystemExit('the manifest names helpers that ORIGINAL_ROOT/helpers does not hold')
    found = dict(sys_modules=[], importers=[], name_strings=[])
    for stem in ROUTE:
        for side, path in (('original', Path(original_root)/'helpers'/(stem + '.py')),
                           ('folded', Path(folded)/'atlas_tectonics'/'_private'/(stem + '.py'))):
            tree = ast.parse(path.read_bytes())
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            for node in ast.walk(tree):
                where = '%s %s:%d' % (side, stem, getattr(node, 'lineno', 0))
                if isinstance(node, ast.Attribute) and node.attr in ('modules', '__dict__') \
                        or isinstance(node, ast.Constant) and node.value == 'modules':
                    found['sys_modules'].append(where)
                elif isinstance(node, ast.Import) and any(a.name.split('.')[0] in IMPORT_MODULES for a in node.names) \
                        or isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] in IMPORT_MODULES \
                        or isinstance(node, ast.Name) and node.id in IMPORTERS + DYNAMIC \
                        or isinstance(node, ast.Attribute) and node.attr in IMPORTERS \
                        or isinstance(node, ast.alias) and (node.name in IMPORTERS or node.asname in IMPORTERS) \
                        or isinstance(node, ast.Constant) and node.value in IMPORTERS:
                    found['importers'].append(where)
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    name = node.value[len(PRIVATE) + 1:] if node.value.startswith(PRIVATE + '.') else node.value
                    if name.split('.')[0] in helpers and re.fullmatch(r'[A-Za-z_][\w.]*', name):
                        parent = parents.get(node)
                        found['name_strings'].append('%s %r in %s' % (where, node.value,
                                                                      ast.unparse(parent)[:80] if parent else '-'))
    ok = not (found['sys_modules'] or found['importers'])
    return dict(ok=ok, route=list(ROUTE), **found)


LG = 'atlas_tectonics/_private/ledger_fresh_interval.py'
REFUSAL = 'pinned capture library is not under exactly one ancestor'
GUARD = ast.dump(ast.parse('CAPTURE_LIBRARY is not None', mode='eval').body)


def _datakey_preflight(module_path, key):
    """r4: MODULE_PATH's own task_file(KEY) run from MODULE_PATH, and how the module refuses a missing key.
    Returns (verdict, why): FOUND (one file), REFUSED (none, and the module's own preflight refuses) or ERROR."""
    tree = ast.parse(Path(module_path).read_text(encoding='utf8'))
    defs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    need, todo = set(), ['task_file', 'capture_backend']
    while todo:   # r4.1: and every module-level function they call, transitively (r12's task_file calls _holds)
        name = todo.pop()
        if name in defs and name not in need:
            need.add(name)
            todo += [node.id for node in ast.walk(defs[name]) if isinstance(node, ast.Name)]
    body = [node for node in tree.body
            if (isinstance(node, ast.FunctionDef) and node.name in need)
            or (isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and t.id.startswith(
                ('CAPTURE_LIBRARY', '_CAPTURE_BACKEND')) for t in node.targets))]
    names = {node.name for node in body if isinstance(node, ast.FunctionDef)}
    if 'task_file' not in names:
        return 'ERROR', 'no task_file in %s' % Path(module_path).name
    ns = {'__file__': str(module_path), '__name__': 'datakey_preflight', 'Path': Path}
    try:
        exec(compile(ast.Module(body=body, type_ignores=[]), str(module_path), 'exec'), ns)
    except Exception as error:
        return 'ERROR', 'the preflight subset did not run: %s: %s' % (type(error).__name__, str(error)[:160])
    if ns.get('CAPTURE_LIBRARY_KEY') != key:
        return 'ERROR', 'CAPTURE_LIBRARY_KEY is %r, not %r' % (ns.get('CAPTURE_LIBRARY_KEY'), key)
    found = ns.get('CAPTURE_LIBRARY')
    if found is not None:
        return 'FOUND', str(found)
    if 'capture_backend' in names:
        try:
            ns['capture_backend']()
        except FileNotFoundError as error:
            if REFUSAL in str(error):
                return 'REFUSED', 'capture_backend: %s' % str(error)[:160]
            return 'ERROR', 'capture_backend raised another FileNotFoundError: %s' % str(error)[:160]
        except Exception as error:
            return 'ERROR', 'capture_backend raised %s: %s' % (type(error).__name__, str(error)[:160])
        return 'ERROR', 'capture_backend did not refuse a missing library'
    guards = [function.name for function in tree.body if isinstance(function, ast.FunctionDef)
              for stmt in function.body if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
              and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == 'require'
              and stmt.value.args and ast.dump(stmt.value.args[0]) == GUARD]
    if guards:
        return 'REFUSED', 'require(CAPTURE_LIBRARY is not None, ...) is a statement of %s()' % ', '.join(guards)
    return 'ERROR', 'nothing refuses a missing library'


def tree(parity_dir, original_root, fold_out, work_dir):
    P = _parity(parity_dir)
    fold_out, work = Path(fold_out), Path(work_dir)
    work.mkdir(parents=True)
    folded = work/'folded'
    shutil.copytree(fold_out/'folded', folded)
    manifest = json.loads((fold_out/'MANIFEST.json').read_text(encoding='utf8'))
    ctx = P.Context(manifest)
    original_root = str(Path(original_root).resolve())
    old_of = {new: old for old, new in manifest['modules'].items()}
    privates = sorted(k for k in old_of if k.startswith('atlas_tectonics/_private/') and k != CRP)
    texts = {key: (folded/key).read_bytes().decode('utf8') for key in privates}
    m9 = next(((key, site) for key in privates for site in [_int_site(texts[key])] if site), None)
    m9b = next(((key, site) for key in privates for site in [_qualified_import(texts[key], ctx.private)] if site), None)
    if m9 is None or m9b is None:
        raise SystemExit('no site for M9 or M9b')
    results = []

    def run(name, expect, gate, paths=(), apply=lambda: None, created=()):
        saved = {path: path.read_bytes() for path in paths}
        try:
            apply()
            verdict, why = _gate(gate)
        finally:
            for path, raw in saved.items():
                path.write_bytes(raw)
            for path in created:
                path.unlink(missing_ok=True)
        restored = all(path.read_bytes() == raw for path, raw in saved.items()) and not any(
            path.exists() for path in created)
        results.append(dict(mutant=name, expected=expect, verdict=verdict, ok=verdict == expect and restored,
                            restored=restored, why=why))
        print('%-4s %-7s %-4s %s' % ('ok' if results[-1]['ok'] else 'BAD', name, verdict, why[:120]), flush=True)

    def ast_gate():
        return P.check_ast(original_root, str(folded), manifest)

    def pins_gate():
        return P.check_pins(str(folded), manifest)

    def splice(key, site):
        path, (start, end, new) = folded/key, site
        return dict(paths=[path], apply=lambda: path.write_bytes(
            (texts[key][:start] + new + texts[key][end:]).encode('utf8')))

    run('N0-ast', 'PASS', ast_gate)
    run('N0-pins', 'PASS', pins_gate)
    run('M9', 'FAIL', ast_gate, **splice(*m9))
    run('M9b', 'FAIL', ast_gate, **splice(*m9b))
    stale_key = m9[0]
    stale = (Path(original_root)/old_of[stale_key]).read_bytes()
    run('M10', 'FAIL', pins_gate, paths=[folded/stale_key], apply=lambda: (folded/stale_key).write_bytes(stale))
    twin = folded/(Path(old_of[stale_key]).stem + '.py')
    if twin.exists():
        raise SystemExit('a top-level %s already exists in the folded copy' % twin.name)
    run('M10b', 'FAIL', pins_gate, created=[twin], apply=lambda: twin.write_bytes(stale))
    crp = folded/CRP
    crp_text = crp.read_bytes().decode('utf8')
    # r3, M11: each fold_r5 data key (a relative key_map path) put back as the workspace literal in the folded CRP.
    for literal, key in sorted((k, v) for k, v in manifest['key_map'].items() if not P._is_abs(k)):
        spelled = "'%s'" % key
        if crp_text.count(spelled) != 1:
            raise SystemExit('data key %s is not in the folded CRP exactly once' % key)
        run('M11', 'FAIL', ast_gate, paths=[crp], apply=lambda s=spelled, w="'%s'" % literal: crp.write_bytes(
            crp_text.replace(s, w).encode('utf8')))
    lookups = crp_text.count(CRP_QUALIFIED)
    proof = route_proof(original_root, folded, manifest)
    if lookups == 1:
        run('P20-M1', 'PASS', ast_gate, paths=[crp], apply=lambda: crp.write_bytes(
            crp_text.replace(CRP_QUALIFIED, CRP_BARE).encode('utf8')))
        results[-1]['note'] = ('EXPECTED-FAIL: the gate reads the reverted store name as equal to the original; the '
                               'guard belongs to Plan 20 CRP revision')
    elif lookups == 0:
        # r3: the route the mutant edited is gone; it is retired only when the AST shows no lookup by name remains.
        results.append(dict(mutant='P20-M1', expected='RETIRED', verdict='RETIRED' if proof['ok'] else 'FAIL',
                            ok=proof['ok'], restored=True, why='no %s in the folded CRP; route proof %s'
                            % (CRP_QUALIFIED, 'holds' if proof['ok'] else 'fails')))
        print('%-4s %-7s %-4s %s' % ('ok' if proof['ok'] else 'BAD', 'P20-M1', results[-1]['verdict'],
                                     results[-1]['why'][:120]), flush=True)
    else:
        raise SystemExit('the qualified store lookup is in the folded CRP more than once')
    # r4, M12 / N3 / N4 (FOLD.md §13 item 7): the data-key holders' own preflight in three layouts.
    data_keys = sorted({v for k, v in manifest['key_map'].items() if not P._is_abs(k)})
    constants = {rel: {node.value for node in ast.walk(ast.parse((folded/rel).read_bytes().decode('utf8')))
                       if isinstance(node, ast.Constant) and isinstance(node.value, str)}
                 for rel in old_of if rel.endswith('.py')}
    holders = sorted((rel, key) for rel in constants for key in data_keys if key in constants[rel])
    if not {CRP, LG} <= {rel for rel, _ in holders}:
        raise SystemExit('the data-key holders are %s; CRP and LG must both be among them'
                         % sorted({rel for rel, _ in holders}))
    for rel, key in holders:
        name = Path(rel).name
        cases = [('N3', 'FOUND', folded/rel, None)]
        for label, expect, package in (('M12', 'REFUSED', 'src'), ('N4', 'FOUND', '.')):
            lay = work/('%s-%s' % (label.lower(), Path(rel).stem))
            (lay/package/key).parent.mkdir(parents=True)
            shutil.copyfile(folded/key, lay/package/key)
            (lay/'helpers').mkdir()
            shutil.copyfile(folded/rel, lay/'helpers'/name)
            cases.append((label, expect, lay/'helpers'/name, lay))
        for label, expect, module, lay in cases:
            verdict, why = _datakey_preflight(module, key)
            if verdict == 'FOUND' and lay is None and Path(why).resolve() != (folded/key).resolve():
                verdict, why = 'ERROR', 'found %s, not the folded key file' % why
            if lay is not None:
                shutil.rmtree(lay)
            restored = lay is None or not lay.exists()
            results.append(dict(mutant=label, expected=expect, verdict=verdict, ok=verdict == expect and restored,
                                restored=restored, why='%s: %s' % (name, why)))
            print('%-4s %-7s %-7s %s' % ('ok' if results[-1]['ok'] else 'BAD', label, verdict,
                                         results[-1]['why'][:120]), flush=True)
    source = {p.relative_to(fold_out/'folded').as_posix(): sha256(p.read_bytes()).hexdigest()
              for p in (fold_out/'folded').rglob('*') if p.is_file()}
    copied = {p.relative_to(folded).as_posix(): sha256(p.read_bytes()).hexdigest()
              for p in folded.rglob('*') if p.is_file()}
    unchanged = source == copied
    report = dict(mode='tree', sites=dict(M9=[m9[0], list(m9[1])], M9b=[m9b[0], list(m9b[1])], M10=stale_key),
                  copy_restored=unchanged, mutants=results, p20_m1_route_proof=proof,
                  status='PASS' if unchanged and all(r['ok'] for r in results) else 'FAIL')
    (work/'mutants.json').write_text(json.dumps(report, indent=1), encoding='utf8')
    print(json.dumps(dict(status=report['status'], restored=unchanged)))
    return 0 if report['status'] == 'PASS' else 1


def _leaves(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaves(item, path + (index,))
    else:
        yield path, value


def records(parity_dir, a_path, b_path, a2_path, manifest_path, work_dir):
    P = _parity(parity_dir)
    a, b, a2 = (json.loads(Path(p).read_text(encoding='utf8')) for p in (a_path, b_path, a2_path))
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf8'))
    ctx = P.Context(manifest)
    work = Path(work_dir)
    work.mkdir(parents=True)
    self_ids = [tuple(path) for path in manifest.get('self_ids', ())]
    held = {tuple(path) for path in manifest.get('bookings', ())} | set(self_ids) | {
        tuple(entry['path']) for entry in manifest.get('external', ())}
    leaves = [(path, value) for path, value in _leaves(b) if not any(path[:len(h)] == h for h in held)
              and path[:2] != SOURCES]
    floats = [(path, value) for path, value in leaves if type(value) is float and math.isfinite(value) and value]
    ints = [(path, value) for path, value in leaves if type(value) is int and value > 1]
    table = P._get(b, SOURCES)
    key = sorted(table)[0]
    repinned = sorted(k for k in table if ctx.sha_map.get(k, (None, None))[0] not in (None, table[k]))
    results = []

    def reseal(record):
        for path in sorted(self_ids, key=len, reverse=True):
            enclosing = dict(P._get(record, path[:-1]))
            enclosing.pop(path[-1])
            P._set(record, path, P.stream_hash(enclosing))

    def run(name, expect, mutate, seal=True):
        record = copy.deepcopy(b)
        mutate(record)
        if seal:
            reseal(record)
        verdict, why = _gate(lambda: P.check_records(a, record, manifest))
        results.append(dict(mutant=name, expected=expect, verdict=verdict, ok=verdict == expect, why=why))
        print('%-4s %-6s %-4s %s' % ('ok' if results[-1]['ok'] else 'BAD', name, verdict, why[:120]), flush=True)

    def sources(record):
        return P._get(record, SOURCES)

    def reorder(record):
        items = list(sources(record).items())
        sources(record).clear()
        sources(record).update(reversed(items))

    run('N0', 'PASS', lambda record: None)
    if floats:
        run('M1', 'FAIL', lambda record: P._set(record, floats[0][0], math.nextafter(floats[0][1], math.inf)))
    run('M2', 'FAIL', lambda record: P._set(record, ints[0][0], ints[0][1] + 1))
    run('M3', 'FAIL', lambda record: sources(record).__setitem__('C:/Users/x/' + key, sources(record).pop(key)))
    run('M4', 'FAIL', lambda record: sources(record).pop(key))
    if repinned:
        run('M5', 'FAIL', lambda record: sources(record).__setitem__(repinned[0], ctx.sha_map[repinned[0]][0]))
    run('M6', 'FAIL', lambda record: sources(record).__setitem__(PRIVATE.replace('.', '/') + '/not_emitted.py',
                                                                 '0' * 64))
    for booking in manifest.get('bookings', ())[:1]:
        grown = P._get(a, ctx.a_path(booking)) + 1
        run('M7', 'FAIL', lambda record, path=booking, value=grown: P._set(record, path, value))
    if self_ids:
        run('M8', 'FAIL', lambda record: P._set(record, self_ids[0], sha256(b'forged').hexdigest()), seal=False)
    run('N1', 'PASS', reorder)
    verdict, why = _gate(lambda: dict(status='PASS') if P.canonical(a) == P.canonical(a2) else dict(
        status='FAIL', at=P.first_difference(a, a2)))
    results.append(dict(mutant='N2', expected='PASS', verdict=verdict, ok=verdict == 'PASS', why=why))
    skipped = [name for name, ok in (('M1', floats), ('M5', repinned), ('M7', manifest.get('bookings')),
                                     ('M8', self_ids)) if not ok]
    report = dict(mode='records', skipped=skipped, mutants=results,
                  status='PASS' if all(r['ok'] for r in results) and not skipped else 'FAIL')
    (work/'mutants.json').write_text(json.dumps(report, indent=1), encoding='utf8')
    print(json.dumps(dict(status=report['status'], skipped=skipped)))
    return 0 if report['status'] == 'PASS' else 1


def main(argv):
    if argv[:1] == ['tree'] and len(argv) == 5:
        return tree(*argv[1:])
    if argv[:1] == ['records'] and len(argv) == 7:
        return records(*argv[1:])
    raise SystemExit(__doc__)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
