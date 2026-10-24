"""Static release-closure check (release decision 6, RELEASE-CHECKS E1 and section 3.3 b).

usage: release_closure_check.py PACKAGE_DIR [--extra FILE ...] [--json OUT]

PACKAGE_DIR is the directory of the ``atlas_tectonics`` package whose bytes a release would ship; ``--extra`` adds
other shipped entry files (the allow-listed tools). The check reads source only (``ast``); it imports and runs
nothing. It fails when a shipped module:

- imports ``unittest``, ``mock`` or ``pytest``, or a module whose last name part matches ``test_*``, ``probe_*``,
  ``measure_*`` or ``*ref_*`` (the build-time import ban);
- assigns to, deletes or augments an attribute of another imported atlas module, calls ``setattr``/``delattr`` on
  one, or uses ``mock.patch`` (in-memory rebinding of another module's functions or registered constants);
- rebinds one of its own upper-case module constants from inside a function (``global NAME`` then assignment);
- contains an ``assert`` statement (``-O`` would strip it; release refuses ``-O``, but explicit raises are the rule).

Modules of the package whose own name matches the ban are reported as excluded from the release bytes and are not
checked further. Unresolved dynamic imports fail closed and remain listed for review. There are no dynamic-import
exemptions: a future reviewed exemption must bind the source and exact call, not merely a module or line number.
This is a bounded static policy check, not a hostile-code sandbox or a general Python data-flow proof.
"""
import argparse
import ast
import fnmatch
import json
import sys
from pathlib import Path

PACKAGE = 'atlas_tectonics'
BANNED_ROOTS = ('unittest', 'mock', 'pytest')
BANNED_NAMES = ('test_*', 'probe_*', 'measure_*', '*ref_*')
# The same exemption as reuse._callable_inventory: process-wide resource leases of the executor, not registered
# constants (their changes are guarded by the executor, not source invalidation).
TRANSIENT = {'atlas_tectonics.execution': frozenset(('_LIMIT_USERS', '_LIMIT_VALUE', '_LIMIT_OWNER', '_LIMIT_HANDLE',
                                                     '_POOL_SLOTS', '_PROCESS_LIMIT_HANDLE'))}


def banned_module(name):
    if not name:
        return False
    parts = name.split('.')
    return parts[0] in BANNED_ROOTS or any(fnmatch.fnmatchcase(parts[-1], p) for p in BANNED_NAMES)


def _resolve(module, level, current, is_package=False):
    """Absolute dotted name of an import inside ``current`` (a dotted package module name)."""
    if not level:
        return module or ''
    parts = current.split('.') if is_package else current.split('.')[:-1]
    if level > len(parts):
        return ''
    base = parts[:len(parts) - level + 1]
    return '.'.join(base + ([module] if module else []))


class _Module(ast.NodeVisitor):
    def __init__(self, name, path, modules, is_package=False):
        self.name, self.path, self.modules = name, path, modules
        self.atlas_aliases = {}   # local name -> imported atlas module or member
        self.findings, self.dynamic = [], []
        self._function = 0
        self.is_package = is_package
        self.import_aliases = {'__import__': '__import__'}
        self.import_modules = {'importlib', 'builtins'}

    def finding(self, node, kind, detail):
        self.findings.append({'file': self.path, 'line': getattr(node, 'lineno', 0), 'kind': kind,
                              'detail': detail})

    # imports
    def _imported(self, node, target):
        if banned_module(target):
            self.finding(node, 'banned-import', target)

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name in ('importlib', 'builtins'):
                self.import_modules.add(alias.asname or alias.name)
            self._imported(node, alias.name)
            if alias.name.split('.')[0] == PACKAGE:
                self.atlas_aliases[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else PACKAGE
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        base = _resolve(node.module, node.level, self.name, self.is_package)
        if node.level and not base:
            self.finding(node, 'unresolved-import', 'relative import escapes package')
        self._imported(node, base)
        for alias in node.names:
            if (base, alias.name) in (('importlib', 'import_module'), ('builtins', '__import__')):
                self.import_aliases[alias.asname or alias.name] = alias.name
            if alias.name == '*':
                self.finding(node, 'unresolved-import', 'star import prevents alias accounting')
            full = base + '.' + alias.name if base else alias.name
            # Inside the package only a member that is itself a module counts (a function named measure_* does
            # not); outside it a matching name is treated as a module.
            is_module = full in self.modules if base.split('.')[0] == PACKAGE else True
            if is_module and banned_module(full) and not banned_module(base):
                self.finding(node, 'banned-import', full)
            if base.split('.')[0] == PACKAGE and alias.name != '*':
                # ``from atlas_tectonics import reuse`` binds a module; a function or constant binds a value
                # whose attribute assignment is caught as a module-level rebinding only if it is a module.
                self.atlas_aliases.setdefault(alias.asname or alias.name, full)
        self.generic_visit(node)

    def _import_function(self, func):
        if isinstance(func, ast.Name):
            return self.import_aliases.get(func.id)
        if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                and func.value.id in self.import_modules
                and func.attr in ('import_module', '__import__')):
            return func.attr
        return None

    def _import_target(self, node):
        """Resolve literal imports only; computed names require explicit review."""
        kind = self._import_function(node.func)
        if kind is None:
            return None
        first = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == 'name'), None)
        if not isinstance(first, ast.Constant) or type(first.value) is not str or not first.value:
            return ''
        name = first.value
        if kind == '__import__':
            level = node.args[4] if len(node.args) > 4 else next((k.value for k in node.keywords if k.arg == 'level'), None)
            if level is not None and not (isinstance(level, ast.Constant) and level.value == 0):
                return ''
        if name.startswith('.'):
            if kind != 'import_module':
                return ''
            package = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == 'package'), None)
            if isinstance(package, ast.Name) and package.id == '__package__':
                package_name = self.name if self.is_package else self.name.rpartition('.')[0]
            elif isinstance(package, ast.Constant) and type(package.value) is str:
                package_name = package.value
            else:
                return ''
            level = len(name) - len(name.lstrip('.'))
            return _resolve(name.lstrip('.'), level, package_name, True)
        return name

    def visit_Call(self, node):
        func = node.func
        name = func.id if type(func) is ast.Name else func.attr if type(func) is ast.Attribute else None
        target = self._import_target(node)
        if target is not None:
            if target:
                self._imported(node, target)
            else:
                self.dynamic.append({'file': self.path, 'line': node.lineno})
                self.finding(node, 'unresolved-import', ast.unparse(node))
        if name in ('setattr', 'delattr') and node.args and self._atlas_target(node.args[0]):
            self.finding(node, 'module-rebinding', '%s on %s' % (name, ast.unparse(node.args[0])))
        if type(func) is ast.Attribute and func.attr in ('patch', 'object') and 'mock' in ast.unparse(func.value):
            self.finding(node, 'mock-patch', ast.unparse(func))
        self.generic_visit(node)

    # rebinding
    def _atlas_target(self, node):
        root = node
        while type(root) is ast.Attribute:
            root = root.value
        return type(root) is ast.Name and root.id in self.atlas_aliases

    def _store(self, target, node):
        if isinstance(target, ast.Attribute) and self._atlas_target(target.value):
            self.finding(node, 'module-rebinding', 'assignment to %s' % ast.unparse(target))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._store(item, node)
        elif isinstance(target, ast.Starred):
            self._store(target.value, node)

    def _bind_aliases(self, targets, value):
        # Preserve provenance through simple aliases and literal dynamic module imports.
        # Computed imports are already blocking, so their target cannot make a package pass.
        module = self._import_target(value) if isinstance(value, ast.Call) else None
        if isinstance(value, ast.Name):
            module = self.atlas_aliases.get(value.id, module)
        elif isinstance(value, ast.Attribute) and self._atlas_target(value):
            module = PACKAGE  # conservatively retain imported-Atlas provenance
        importer = self._import_function(value)
        for target in targets:
            if isinstance(target, ast.Name):
                if module and module.split('.')[0] == PACKAGE:
                    self.atlas_aliases[target.id] = module
                if importer:
                    self.import_aliases[target.id] = importer

    def visit_Assign(self, node):
        self._bind_aliases(node.targets, node.value)
        for target in node.targets:
            self._store(target, node)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        self._store(node.target, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self._bind_aliases([node.target], node.value)
        self._store(node.target, node)
        self.generic_visit(node)

    def visit_NamedExpr(self, node):
        self._bind_aliases([node.target], node.value)
        self._store(node.target, node)
        self.generic_visit(node)

    def visit_Delete(self, node):
        for target in node.targets:
            self._store(target, node)
        self.generic_visit(node)

    def _function_body(self, node):
        self._function += 1
        declared = {name for child in ast.walk(node) if isinstance(child, ast.Global) for name in child.names}
        declared -= TRANSIENT.get(self.name, frozenset())
        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                targets = child.targets
            elif isinstance(child, (ast.AugAssign, ast.AnnAssign)):
                targets = [child.target]
            elif isinstance(child, ast.Delete):
                targets = child.targets
            else:
                targets = []
            for target in targets:
                for leaf in ast.walk(target):
                    if (isinstance(leaf, ast.Name) and isinstance(leaf.ctx, (ast.Store, ast.Del))
                            and leaf.id in declared and leaf.id.isupper()):
                        self.finding(child, 'constant-rebinding', 'global %s changed in %s' % (leaf.id, node.name))
        self.generic_visit(node)
        self._function -= 1

    visit_FunctionDef = visit_AsyncFunctionDef = _function_body

    def visit_Assert(self, node):
        self.finding(node, 'assert', ast.unparse(node.test)[:120])
        self.generic_visit(node)


def check(package_dir, extra=()):
    package_dir = Path(package_dir)
    if (not package_dir.is_dir() or package_dir.name != PACKAGE
            or not (package_dir / '__init__.py').is_file()):
        return {'schema': 'atlas.private.release-closure-check.r1', 'shipped_modules': 0,
                'excluded_from_release': [], 'counts': {'invalid-package': 1},
                'findings': [{'file': package_dir.as_posix(), 'line': 0, 'kind': 'invalid-package',
                              'detail': 'existing atlas_tectonics package with __init__.py required'}],
                'dynamic_imports': [], 'passed': False}
    shipped, excluded = [], []
    for path in sorted(package_dir.rglob('*.py')):
        relative = path.relative_to(package_dir.parent).with_suffix('')
        name = '.'.join(relative.parts)
        name = name.removesuffix('.__init__')
        (excluded if banned_module(name) else shipped).append((name, path))
    modules = frozenset(name for name, _ in shipped + excluded)
    shipped.extend((Path(p).stem, Path(p)) for p in extra)
    findings, dynamic = [], []
    for name, path in shipped:
        visitor = _Module(name, path.as_posix(), modules, path.name == '__init__.py')
        visitor.visit(ast.parse(path.read_bytes(), filename=str(path)))
        findings.extend(visitor.findings)
        dynamic.extend(visitor.dynamic)
    counts = {}
    for item in findings:
        counts[item['kind']] = counts.get(item['kind'], 0) + 1
    return {'schema': 'atlas.private.release-closure-check.r1', 'shipped_modules': len(shipped),
            'excluded_from_release': [p.as_posix() for _, p in excluded], 'counts': counts,
            'findings': findings, 'dynamic_imports': dynamic, 'passed': not findings}


def main(argv=None):
    parser = argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0])
    parser.add_argument('package_dir', type=Path)
    parser.add_argument('--extra', type=Path, action='append', default=[])
    parser.add_argument('--json', type=Path)
    args = parser.parse_args(argv)
    report = check(args.package_dir, args.extra)
    text = json.dumps(report, indent=1, sort_keys=True)
    if args.json:
        args.json.write_text(text + '\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'shipped_modules': report['shipped_modules'],
                      'excluded': len(report['excluded_from_release']), 'counts': report['counts'],
                      'dynamic_imports': len(report['dynamic_imports'])}, sort_keys=True))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
