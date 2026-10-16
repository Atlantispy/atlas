"""Step 10 static import-closure check over a frozen composition (coordinator, 16 Oct ~11:20).

Usage: python -B -I check_import_closure.py COMPOSED_ROOT H_TESTS OUT.json

Every Import / ImportFrom in every module of COMPOSED_ROOT/src (package atlas_tectonics) and
COMPOSED_ROOT/helpers, including imports inside functions and relative imports, must resolve to:
  - a module of the composed package (atlas_tectonics.*, or a name its __init__ defines), or
  - a top-level module in COMPOSED_ROOT/helpers or H_TESTS, or
  - the standard library, or
  - a pinned third-party distribution (THIRD_PARTY below; assemble_resumable's list).
Literal importlib.import_module('x') / __import__('x') calls are checked the same way.
Imports inside a try whose handler catches ImportError/ModuleNotFoundError are reported as
'optional'; unresolved imports in test_*.py helpers are reported separately ('test-only').
Exit 1 if any runtime (non-test, non-optional) import is unresolved.
"""
import ast
import json
from pathlib import Path
import sys

THIRD_PARTY = {'numpy', 'scipy', 'psutil', 'gmpy2', 'threadpoolctl', 'numba', 'llvmlite', 'shapely', 'blosc2',
               '_winapi', 'msvcrt', 'winreg'}
PKG = 'atlas_tectonics'
# Route (1) entry modules (Steps 8-9, 16 Oct 11:12): the runner family. FRESH_MODULES and the
# driver are read from run_fresh_interval.py itself; the whole composed package is reachable.
ENTRIES = ('launch_fresh_interval', 'launch_monitored_interval', 'run_fresh_interval', 'run_prepared_restart',
           'reopen_fresh_restart', 'reopen_prepared_restart', 'fresh_interval_driver', 'width_gate',
           'ledger_fresh_interval', 'interface_worker_selection')
# Function-level exceptions inside reachable modules, each with its justification.
EXCEPTIONS = {
    ('probe_heat_original_connected_r9.py', 'probe_heat_original_reopen_r4'):
        'inside run(), the preserved r9 probe entry; route (1) uses only D._Cancel, ADVANCE_OPTIONS, arrays, '
        'physical_control, POLICY, snapshots, TARGET (fresh_interval_driver), never D.run',
}


def fresh_modules(helpers):
    tree = ast.parse((helpers / 'run_fresh_interval.py').read_text(encoding='utf8'))
    names = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) in ('FRESH_MODULES', 'DRIVER')
                                                for t in node.targets):
            value = ast.literal_eval(node.value)
            names += list(value) if isinstance(value, tuple) else [value]
    return names


def optional_ranges(tree):
    ranges = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            names = set()
            for handler in node.handlers:
                kind = handler.type
                for item in (kind.elts if isinstance(kind, ast.Tuple) else [kind]):
                    if isinstance(item, ast.Name):
                        names.add(item.id)
            if names & {'ImportError', 'ModuleNotFoundError', 'Exception', 'BaseException'}:
                ranges.append((node.body[0].lineno, node.body[-1].end_lineno))
    return ranges


def main():
    root, h_tests, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3])
    src, helpers = root / 'src', root / 'helpers'
    package = {}
    for path in (src / PKG).rglob('*.py'):
        parts = path.relative_to(src).with_suffix('').parts
        name = '.'.join(parts[:-1]) if parts[-1] == '__init__' else '.'.join(parts)
        package[name] = path
    init_names = set()
    for node in ast.parse((src / PKG / '__init__.py').read_text(encoding='utf8')).body:
        for target in getattr(node, 'names', []) or []:
            init_names.add(getattr(target, 'asname', None) or getattr(target, 'name', ''))
    top = {p.stem for p in helpers.glob('*.py')} | {p.stem for p in h_tests.glob('*.py')}
    stdlib = set(sys.stdlib_module_names)

    def resolves(module):
        if module == PKG or module in package:
            return True
        head = module.split('.')[0]
        if head == PKG:
            return False
        return head in top or head in stdlib or head in THIRD_PARTY

    files = [(p, True) for p in sorted((src / PKG).rglob('*.py'))] + [(p, False) for p in sorted(helpers.glob('*.py'))]
    unresolved, optional, test_only, counted = [], [], [], 0
    edges = {}  # helper or package module -> top-level helper names it imports (resolved)
    for path, native in files:
        tree = ast.parse(path.read_text(encoding='utf8'))
        guards = optional_ranges(tree)
        own = '.'.join(path.relative_to(src).with_suffix('').parts) if native else path.stem
        if own.endswith('.__init__'):
            own = own[:-len('.__init__')]
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = own.split('.')
                    is_pkg = path.name == '__init__.py'
                    anchor = base if is_pkg else base[:-1]
                    anchor = anchor[:len(anchor) - (node.level - 1)]
                    module = '.'.join(anchor + ([node.module] if node.module else []))
                    names = [module] + [f'{module}.{a.name}' for a in node.names]
                    # 'from . import x' resolves if x is a submodule or a name of the package
                    names = [n for n in names if n != module or node.module]
                    ok_names = [n for n in names if n in package or n == module]
                    if node.module and module in package:
                        names = [module]
                    elif ok_names:
                        names = ok_names[:1]
                else:
                    module = node.module
                    if module == PKG:
                        names = [f'{PKG}.{a.name}' if f'{PKG}.{a.name}' in package or a.name not in init_names
                                 else PKG for a in node.names]
                    else:
                        names = [module]
            elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and
                  isinstance(node.args[0].value, str) and
                  ((isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module') or
                   (isinstance(node.func, ast.Name) and node.func.id == '__import__'))):
                names = [node.args[0].value]
            for name in names:
                counted += 1
                head = name.split('.')[0]
                if head in top and head != PKG:
                    edges.setdefault(own if native else path.stem, set()).add(head)
                if resolves(name):
                    continue
                row = dict(module=str(path.relative_to(root)), file=path.name, native=native,
                           owner=own if native else path.stem, line=node.lineno, imports=name)
                if any(a <= node.lineno <= b for a, b in guards):
                    optional.append(row)
                elif not native and path.name.startswith('test_'):
                    test_only.append(row)
                else:
                    unresolved.append(row)
    # Module reachability from the route (1) entries, the FRESH_MODULES and the whole package.
    reachable = set(ENTRIES) | set(fresh_modules(helpers)) | {m for m in package}
    frontier = list(reachable)
    while frontier:
        current = frontier.pop()
        for nxt in edges.get(current, ()):
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    failing, excepted, unreachable = [], [], []
    for row in unresolved:
        key = (row['file'], row['imports'].split('.')[0])
        if key in EXCEPTIONS:
            excepted.append(dict(row, why=EXCEPTIONS[key]))
        elif row['native'] or row['owner'] in reachable:
            failing.append(row)
        else:
            unreachable.append(row)
    result = dict(root=str(root), h_tests=str(h_tests), files=len(files), imports_checked=counted,
                  reachable_helper_modules=sorted(m for m in reachable if m in top),
                  failing=failing, excepted=excepted, unreachable_tools=unreachable,
                  optional=optional, test_only=test_only)
    out.write_text(json.dumps(result, indent=1) + '\n', encoding='utf8')
    print(json.dumps(dict(files=len(files), imports_checked=counted,
                          reachable_helpers=len(result['reachable_helper_modules']), failing=len(failing),
                          excepted=len(excepted), unreachable_tools=len(unreachable),
                          optional=len(optional), test_only=len(test_only)), indent=1))
    for row in failing[:40]:
        print('FAILING   ', row['module'], row['line'], row['imports'])
    for row in excepted:
        print('excepted  ', row['module'], row['line'], row['imports'], '|', row['why'][:90])
    for row in unreachable[:20]:
        print('tool-only ', row['module'], row['line'], row['imports'])
    if failing:
        raise SystemExit(1)
    print('import-closure-pass')


if __name__ == '__main__':
    main()
