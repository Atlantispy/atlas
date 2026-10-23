"""Write mutants_r4.py from mutants_r3.py by exact replacements, each required to match a stated number of times.

    python -B -I mk_mutants_r4.py FOLD_DIR

FOLD_DIR holds mutants_r3.py; mutants_r4.py must not exist yet. Prints the two shas.
"""
from hashlib import sha256
import sys
from pathlib import Path

PARAGRAPH = '''r4 (23 Oct; FOLD.md §13 item 7): the sibling-layout mutant. Each folded module holding a fold_r5 data key as a
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

'''

PREFLIGHT = '''LG = 'atlas_tectonics/_private/ledger_fresh_interval.py'
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
'''

SIBLING = '''    # r4, M12 / N3 / N4 (FOLD.md §13 item 7): the data-key holders' own preflight in three layouts.
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
'''

EDITS = [
    ('"""R1 fold mutants (', '"""R1 fold mutants r4 (', 1),
    ('    python -B mutants_r3.py ', '    python -B mutants_r4.py ', 2),
    ('r3 (Plan 20 r11, 23 Oct):', PARAGRAPH + 'r3 (Plan 20 r11, 23 Oct):', 1),
    ('def tree(parity_dir, original_root, fold_out, work_dir):\n', PREFLIGHT, 1),
    ("    source = {p.relative_to(fold_out/'folded').as_posix(): sha256(p.read_bytes()).hexdigest()\n", SIBLING, 1),
]


def main(argv):
    if len(argv) != 1:
        raise SystemExit(__doc__)
    fold = Path(argv[0])
    source, target = fold/'mutants_r3.py', fold/'mutants_r4.py'
    if target.exists():
        raise SystemExit('%s exists' % target)
    text = source.read_text(encoding='utf-8')
    for old, new, count in EDITS:
        found = text.count(old)
        if found != count:
            raise SystemExit('expected %d of %r, found %d' % (count, old[:60], found))
        text = text.replace(old, new)
    with open(target, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    for path in (source, target):
        print(sha256(path.read_bytes()).hexdigest(), path.name)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
