"""Execution-only module dependencies and selected arithmetic runtime facts."""
import ast
import functools
from importlib.util import find_spec
import json
import sys
import unittest
from pathlib import Path

PACKAGE = Path(find_spec('atlas_tectonics').origin).parent
SHARED = Path(find_spec('atlas_shared').origin).parent
LISTED = ('atlas_shared.machine.resources_monitor', 'atlas_shared.machine.resources_gate', 'atlas_shared.execution.schedule',
          'integration.parallel.selection')
ADMITTED = LISTED[:3]  # admitted by construction; selection is held by (c)
STANDARD = set(sys.stdlib_module_names) | {'psutil'}


@functools.cache
def _tree(path):
    return ast.parse(path.read_text(encoding='utf-8'))  # shared by the tests; trees are only walked


# What every other package module takes from each listed module: names, and attribute chains read through an
# alias of the module. A new entry is a new value crossing from outside the identity into bound code.
READERS = {
    'atlas_shared.machine.resources_monitor': {
        '_private.integration.fresh_interval_driver': ['Timings', 'launch_load', 'reading', 'save_store', 'use_store'],
        '_private.integration.parallel.interface_worker_selection': ['Timings', 'reading'],
        '_private.integration.heat.continuation_guard': ['free_memory', 'machine_memory'],
        '_private.integration.heat.process_meter': ['Timings'],
        '_private.integration.reopen_fresh_restart': ['free_memory', 'machine_memory'],
        '_private.integration.reopen_prepared_restart': ['free_memory'],
        '_private.integration.run_fresh_interval': ['free_memory'],
        '_private.integration.run_prepared_restart': ['free_memory'],
        '_private.integration.start_gate': ['reading'],
        'integration.parallel.initial_parallel': ['Timings', 'reading'],
        'integration.parallel.profile': ['machine_memory', 'reported_cores'],
    },
    'atlas_shared.machine.resources_gate': {
        '_private.integration.fresh_interval_driver': ['launch_width', 'setting', 'widths_record'],
        '_private.integration.parallel.interface_worker_selection': ['free_cores', 'launch_width', 'run_cores', 'setting', 'step_down'],
        '_private.integration.heat.continuation_guard': ['FLOOR_BYTES', 'cap_bound'],
        '_private.integration.start_gate': ['ALLOWANCE_BYTES', 'EARLIER_LIMITS', 'FLOOR_BYTES', 'check_limits', 'limits', 'setting', 'start_need'],
        'integration.parallel.initial_parallel': ['pool_ceiling', 'setting'],
    },
    'integration.parallel.selection': {
        '_private.integration.parallel.interface_worker_selection': ['InterfaceParallelPolicy'],
        '_private.integration.prepared_interval_driver': ['InterfaceParallelPolicy'],
        '_private.integration.geometry.endpoint_geometry_provider': ['open_automatic'],
        '_private.integration.run_fresh_interval': ['InterfaceParallelPolicy'],
        '_private.integration.runtime_joined_control': ['InterfaceParallelPolicy', 'last_decision'],
        'integration.geometry.component_volume_auto': ['_Rolling', '_public', '_text'],
        'integration.geometry.differential_ale': ['open_automatic', 'open_interface_batches', 'open_wall_batches'],
        'integration.coupling.pressure_walls': ['InterfaceParallelPolicy', '_Automatic'],
    },
}

# What selection takes from package modules outside the list.
SELECTION_TAKES = {
    '_private.integration.geometry.partition_routing_patch': ['rolling_facts'],
    'integration.geometry.differential_geometry': ['W._decode', 'W._q', '_qtext'],
    'integration.parallel.binding': ['BATCH_LIMIT'],
    'integration.parallel.dispatch': ['BatchParallelSession', 'CHILD_BASELINE', 'InterfaceParallelSession', 'MAX_BATCH_INPUT', 'PARENT_STORAGE',
                                      'SCAN_LIMIT', 'WallParallelSession', 'WallParallelSession._screen',
                                      '_wall_request', 'transport'],
    'integration.parallel.owner': ['nodes_for'],
    'integration.parallel.profile': ['MAX_CLASSES', 'MAX_DECISIONS', 'MAX_SAMPLES', 'aggregate', 'binding_digest', 'class_digest', 'class_key',
                                     'class_rows', 'component_walls', 'current_binding', 'decisions',
                                     'dispatch_rows', 'entry_observations', 'exact_key', 'exact_row', 'exact_rows',
                                     'fold', 'fork_store', 'instrumented', 'last_decision', 'loaded_digest',
                                     'new_observations', 'open_store', 'record_decision', 'save', 'summary',
                                     'wall_class_key', 'wall_exact_key', 'width_bucket'],
    'integration.parallel.results': ['MOMENTS', 'raw_capacity'],
    'integration.resources': ['WorkBudget'],
    'integration.reuse': ['ExecutionContext'],
}


def _module_of(path):
    if path.is_relative_to(SHARED):
        return '.'.join(('atlas_shared', *path.relative_to(SHARED).with_suffix('').parts))
    return path.relative_to(PACKAGE).with_suffix('').as_posix().replace('/', '.')


def _module_path(name):
    if name.startswith('atlas_shared.'):
        return SHARED.joinpath(*name.split('.')[1:]).with_suffix('.py')
    return PACKAGE.joinpath(*name.split('.')).with_suffix('.py')


def _resolve(node, me):
    """The package module ('a.b') an ImportFrom names, or None outside the package."""
    if node.level:
        parts = me.split('.')[:-1]
        parts = parts[:len(parts) - (node.level - 1)]
        return '.'.join(parts + (node.module.split('.') if node.module else []))
    if node.module == 'atlas_tectonics':
        return ''
    if node.module and node.module.startswith('atlas_tectonics.'):
        return node.module[len('atlas_tectonics.'):]
    if node.module and node.module.partition('.')[0] == 'atlas_shared':
        return node.module
    return None


def _scopes(tree):
    """(scope node, its own statements' nodes) for the module and every function, nested functions apart."""
    out = []

    def visit(scope):
        own = []
        stack = list(ast.iter_child_nodes(scope))
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                visit(node)
                own.append(node)  # the function itself, not its body, belongs to the enclosing scope
                stack.extend(node.args.defaults + node.args.kw_defaults if isinstance(node, ast.Lambda) else
                             node.decorator_list + node.args.defaults + [d for d in node.args.kw_defaults if d])
                continue
            own.append(node)
            stack.extend(ast.iter_child_nodes(node))
        out.append((scope, own))

    visit(tree)
    return out


def _chain(node):
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    return (node.id if isinstance(node, ast.Name) else None), '.'.join(reversed(names))


def _taken(path, wanted):
    """{package module: names and chains} that the file takes from modules for which wanted(module) is true.

    Imports bind in their own function (and the functions inside it); module-level imports bind everywhere.
    A bare use of a module alias, other than as the base of an attribute, is recorded as '<module>'.
    """
    me = _module_of(path)
    tree = _tree(path)
    taken = {}
    scopes = _scopes(tree)
    parent_alias = {}

    def aliases_in(own):
        alias = {}
        for node in own:
            if isinstance(node, ast.ImportFrom):
                base = _resolve(node, me)
                if base is None:
                    continue
                for a in node.names:
                    full = f'{base}.{a.name}' if base else a.name
                    if _module_path(full).is_file():
                        if wanted(full):
                            alias[a.asname or a.name] = full
                    elif base and wanted(base):
                        taken.setdefault(base, set()).add(a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    head, _, member = a.name.partition('.')
                    name = member if head == 'atlas_tectonics' else a.name
                    if head in ('atlas_tectonics', 'atlas_shared') and wanted(name):
                        if a.asname is None:
                            raise AssertionError(f'{me}: plain dotted import of {a.name} is not read by this test')
                        alias[a.asname] = name
        return alias

    # A function sees its own imports and those of every enclosing scope.
    enclosing = {}
    for scope, own in scopes:
        for node in own:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                enclosing[id(node)] = scope
    for scope, own in scopes:
        parent_alias[id(scope)] = aliases_in(own)
    for scope, own in scopes:
        seen, s = {}, scope
        chain_scopes = []
        while s is not None:
            chain_scopes.append(s)
            s = enclosing.get(id(s))
        for s in reversed(chain_scopes):
            seen.update(parent_alias[id(s)])
        bases = {id(n.value) for n in own if isinstance(n, ast.Attribute)}
        for node in own:
            if isinstance(node, ast.Attribute) and id(node) not in bases:
                head, rest = _chain(node)
                if head in seen:
                    taken.setdefault(seen[head], set()).add(rest)
            elif (isinstance(node, ast.Name) and node.id in seen and id(node) not in bases
                  and isinstance(node.ctx, ast.Load)):
                taken.setdefault(seen[node.id], set()).add('<module>')
    return taken


def _readers():
    out = {}
    for path in sorted((*PACKAGE.rglob('*.py'), *SHARED.rglob('*.py'))):
        if _module_of(path) in LISTED:
            continue
        for module, names in _taken(path, lambda m: m in LISTED).items():
            out.setdefault(module, {})[_module_of(path)] = sorted(names)
    return out


def _selection_takes():
    path = PACKAGE / 'integration/parallel/selection.py'
    taken = _taken(path, lambda m: m not in LISTED)
    return {module: sorted(names) for module, names in sorted(taken.items())}


def _claim_returns_only_the_session(function):
    """Each return of a claim method is X.claim(request, budget), None, or a name bound only from such a call."""

    def call(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'claim'
                and [getattr(a, 'id', None) for a in node.args] == ['request', 'budget'] and not node.keywords)

    def allowed(node, names):
        if isinstance(node, ast.Constant) and node.value is None:
            return True
        if isinstance(node, ast.IfExp):
            return allowed(node.body, names) and allowed(node.orelse, names)
        if isinstance(node, ast.Name):
            return node.id in names
        return call(node)

    stores = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            stores.setdefault(node.id, 0)
            stores[node.id] += 1
    from_claim = set()
    for node in ast.walk(function):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and call(node.value)):
            name = node.targets[0].id
            if stores[name] == 1:
                from_claim.add(name)
    returns = [n for n in ast.walk(function) if isinstance(n, ast.Return)]
    return bool(returns) and all(r.value is not None and allowed(r.value, from_claim) for r in returns)


class StaticBoundaryTest(unittest.TestCase):
    """T-X1: what crosses between the four modules and bound code is fixed by the tables above."""

    def test_admitted_modules_import_only_the_standard_library_psutil_and_listed_modules(self):
        for name in ADMITTED:
            path = _module_path(name)
            me = _module_of(path)
            for node in ast.walk(_tree(path)):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        self.assertIn(a.name.split('.')[0], STANDARD, f'{name} imports {a.name}')
                elif isinstance(node, ast.ImportFrom):
                    base = _resolve(node, me)
                    if base is None:
                        self.assertIn(node.module.split('.')[0], STANDARD, f'{name} imports {node.module}')
                        continue
                    for a in node.names:
                        full = f'{base}.{a.name}' if base else a.name
                        target = full if _module_path(full).is_file() else base
                        if (name, target, a.name, a.asname) == (
                                'atlas_shared.machine.resources_gate', 'atlas_shared.errors', 'AtlasError', None):
                            continue  # ResourcesRefused retains its builtin base and adds the shared marker.
                        self.assertIn(target, LISTED, f'{name} imports {target}')

    def test_bound_modules_take_only_the_tabled_names_from_listed_modules(self):
        self.assertEqual(_readers(), READERS)

    def test_selection_takes_only_the_tabled_names_and_its_claims_return_only_the_session(self):
        self.assertEqual(_selection_takes(), SELECTION_TAKES)
        tree = _tree(PACKAGE / 'integration/parallel/selection.py')
        claims = [f for c in tree.body if isinstance(c, ast.ClassDef)
                  for f in c.body if isinstance(f, ast.FunctionDef) and f.name == 'claim']
        self.assertEqual(len(claims), 3)
        for function in claims:
            self.assertTrue(_claim_returns_only_the_session(function), f'claim at line {function.lineno}')

    def test_execution_context_names_used_in_the_package_are_defined(self):
        # Routes no test reaches can call a context name a regroup dropped (_verify_selection, dev52).
        tree = _tree(PACKAGE / 'integration/reuse.py')
        cls, = (c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'ExecutionContext')
        allowed = set(dir(object))
        for node in cls.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                allowed.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                allowed |= {t.id for t in targets if isinstance(t, ast.Name)}
        allowed |= {n.attr for n in ast.walk(cls) if isinstance(n, ast.Attribute)
                    and isinstance(n.ctx, ast.Store) and isinstance(n.value, ast.Name) and n.value.id == 'self'}

        def holder(node):
            name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
            return name if name and (name == 'execution' or name.endswith('_execution')) else None

        missing = []
        for path in sorted(PACKAGE.rglob('*.py')):
            if path == PACKAGE / 'materials/constitutive_execution.py':
                continue  # its `execution` is an ExecutionPolicy, not the context
            tree = _tree(path)
            imported = {(a.asname or a.name).split('.')[0] for n in ast.walk(tree)
                        if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
            missing += [f'{path.relative_to(PACKAGE).as_posix()}:{n.lineno} {n.attr}' for n in ast.walk(tree)
                        if isinstance(n, ast.Attribute) and holder(n.value) not in (None, *imported)
                        and n.attr not in allowed]
        self.maxDiff = None
        self.assertEqual(missing, [])


class IdentityProbeTest(unittest.TestCase):
    def test_the_interpreter_arithmetic_is_bound(self):
        from atlas_tectonics.integration import reuse

        runtime = reuse._runtime_record('reference')
        self.assertIn('libmpdec', runtime['versions'])
        self.assertEqual(runtime['versions']['decimal_implementation'], '_decimal')


if __name__ == '__main__' and sys.argv[1:] == ['--tables']:
    print(json.dumps({'READERS': _readers(), 'SELECTION_TAKES': _selection_takes()}, indent=1))
elif __name__ == '__main__':
    unittest.main()
