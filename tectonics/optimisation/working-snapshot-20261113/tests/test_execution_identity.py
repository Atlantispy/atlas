"""The execution identity leaves out the four execution-only modules, and binds the interpreter's arithmetic.

T-X1 reads the package's syntax trees only and imports nothing from it. T-X2, T-X3 and the arithmetic test
run the package in a child process on a temporary copy that leaves out the installed inventory pair and the
fixtures, so the package takes its own unbound route and the copy can be edited.
"""
import ast
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / 'atlas_tectonics'
LISTED = ('machine_resources_monitor', 'resources_gate', 'integration_parallel_rolling',
          'integration_parallel_selection')
ADMITTED = LISTED[:3]  # admitted by construction; selection is held by (c)
STANDARD = set(sys.stdlib_module_names) | {'psutil'}

# What every other package module takes from each listed module: names, and attribute chains read through an
# alias of the module. A new entry is a new value crossing from outside the identity into bound code.
READERS = {
    'machine_resources_monitor': {
        '_private.fresh_interval_driver': ['Timings', 'launch_load', 'reading', 'save_store', 'use_store'],
        '_private.historical_admission': ['machine_memory'],
        '_private.interface_worker_selection': ['Timings', 'reading'],
        '_private.private_heat_continuation_guard_r3': ['free_memory', 'machine_memory'],
        '_private.private_heat_process_meter_r1': ['Timings'],
        '_private.reopen_fresh_restart': ['free_memory', 'machine_memory'],
        '_private.reopen_prepared_restart': ['free_memory'],
        '_private.run_fresh_interval': ['free_memory'],
        '_private.run_prepared_restart': ['free_memory', 'machine_memory'],
        '_private.start_gate': ['reading'],
        'integration_initial_parallel': ['Timings', 'reading'],
        'integration_parallel_profile': ['machine_memory', 'reported_cores'],
    },
    'resources_gate': {
        '_private.fresh_interval_driver': ['launch_width', 'setting', 'widths_record'],
        '_private.historical_admission': ['FLOOR_BYTES', 'cap_bound'],
        '_private.interface_worker_selection': ['free_cores', 'launch_width', 'run_cores', 'setting', 'step_down'],
        '_private.private_heat_continuation_guard_r3': ['FLOOR_BYTES', 'cap_bound'],
        '_private.reopen_prepared_restart': ['EARLIER_LIMITS', 'FLOOR_BYTES'],
        '_private.run_prepared_restart': ['FLOOR_BYTES', 'cap_bound'],
        '_private.start_gate': ['ALLOWANCE_BYTES', 'EARLIER_LIMITS', 'FLOOR_BYTES', 'check_limits', 'limits', 'setting', 'start_need'],
        'integration_initial_parallel': ['pool_ceiling', 'setting'],
    },
    'integration_parallel_selection': {
        '_private.interface_worker_selection': ['InterfaceParallelPolicy'],
        '_private.prepared_interval_driver': ['InterfaceParallelPolicy'],
        '_private.q297_end_provider_v2': ['open_automatic'],
        '_private.run_fresh_interval': ['InterfaceParallelPolicy'],
        '_private.runtime_joined_control': ['InterfaceParallelPolicy', 'MODES', 'last_decision'],
        'integration_component_volume_auto': ['_Rolling', '_public', '_text'],
        'integration_differential_ale': ['open_automatic', 'open_interface_batches', 'open_wall_batches'],
        'integration_pressure_walls': ['InterfaceParallelPolicy', '_Automatic'],
    },
}

# What selection takes from package modules outside the list.
SELECTION_TAKES = {
    '_private.partition_routing_patch': ['rolling_facts'],
    'integration_differential_geometry': ['W._decode', 'W._q', '_qtext'],
    'integration_parallel_binding': ['BATCH_LIMIT'],
    'integration_parallel_dispatch': ['BatchParallelSession', 'CHILD_BASELINE', 'InterfaceParallelSession', 'MAX_BATCH_INPUT', 'PARENT_STORAGE',
                                      'SCAN_LIMIT', 'WallParallelSession', 'WallParallelSession._screen',
                                      '_wall_request', 'transport'],
    'integration_parallel_owner': ['nodes_for'],
    'integration_parallel_profile': ['MAX_CLASSES', 'MAX_DECISIONS', 'MAX_SAMPLES', 'aggregate', 'binding_digest', 'class_digest', 'class_key',
                                     'class_rows', 'code_digest', 'component_walls', 'current_binding', 'decisions',
                                     'dispatch_rows', 'entry_observations', 'exact_key', 'exact_row', 'exact_rows',
                                     'fold', 'fork_store', 'instrumented', 'last_decision', 'loaded_digest',
                                     'new_observations', 'open_store', 'record_decision', 'save', 'summary',
                                     'wall_class_key', 'wall_exact_key', 'width_bucket'],
    'integration_parallel_results': ['MOMENTS', 'raw_capacity'],
    'resources': ['WorkBudget'],
    'reuse': ['ExecutionContext', 'execution_mode'],
}


def _module_of(path):
    return path.relative_to(PACKAGE).with_suffix('').as_posix().replace('/', '.')


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
    tree = ast.parse(path.read_text(encoding='utf-8'))
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
                    if (PACKAGE / (full.replace('.', '/') + '.py')).is_file() and wanted(full):
                        alias[a.asname or a.name] = full
                    elif base and wanted(base):
                        taken.setdefault(base, set()).add(a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith('atlas_tectonics.') and wanted(a.name[16:]):
                        if a.asname is None:
                            raise AssertionError(f'{me}: plain dotted import of {a.name} is not read by this test')
                        alias[a.asname] = a.name[16:]
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
    for path in sorted(PACKAGE.rglob('*.py')):
        if _module_of(path) in LISTED:
            continue
        for module, names in _taken(path, lambda m: m in LISTED).items():
            out.setdefault(module, {})[_module_of(path)] = sorted(names)
    return out


def _selection_takes():
    path = PACKAGE / 'integration_parallel_selection.py'
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
            path = PACKAGE / f'{name}.py'
            me = _module_of(path)
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
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
                        target = full if (PACKAGE / (full.replace('.', '/') + '.py')).is_file() else base
                        self.assertIn(target, LISTED, f'{name} imports {target}')

    def test_bound_modules_take_only_the_tabled_names_from_listed_modules(self):
        self.assertEqual(_readers(), READERS)

    def test_selection_takes_only_the_tabled_names_and_its_claims_return_only_the_session(self):
        self.assertEqual(_selection_takes(), SELECTION_TAKES)
        tree = ast.parse((PACKAGE / 'integration_parallel_selection.py').read_text(encoding='utf-8'))
        claims = [f for c in tree.body if isinstance(c, ast.ClassDef)
                  for f in c.body if isinstance(f, ast.FunctionDef) and f.name == 'claim']
        self.assertEqual(len(claims), 3)
        for function in claims:
            self.assertTrue(_claim_returns_only_the_session(function), f'claim at line {function.lineno}')


PROBE = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import atlas_tectonics.reuse as r
import atlas_tectonics.integration_parallel_selection  # all four loaded, so their constants are captured
step = sys.argv[2]
with r.ExecutionContext('scipy') as c:
    if step == 'identity':
        print(json.dumps(c.identity))
    elif step == 'edit-then-verify':
        c.identity  # proved once, as a run does on entry
        target = r.Path(sys.argv[1]) / 'atlas_tectonics' / 'resources_gate.py'
        try:
            with open(target, 'ab') as f:
                f.write(b'\n')
        except PermissionError:
            print(json.dumps('write refused'))
        else:
            try:
                c.verify_boundary()
            except r.TectonicsError as error:
                print(json.dumps(str(error)))
            else:
                print(json.dumps('accepted'))
    elif step == 'runtime':
        print(json.dumps(c._runtime))
'''


class _Copy:
    """A temporary copy of the package on its unbound route: no installed inventory pair, no fixtures."""

    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix='atlas-identity-'))
        shutil.copytree(PACKAGE, self.root / 'atlas_tectonics', ignore=shutil.ignore_patterns(
            '_application_sources.json', '_application_sources.sha256', '_fixtures', '__pycache__'))
        return self

    def __exit__(self, *_):
        shutil.rmtree(self.root, ignore_errors=True)

    def run(self, step):
        done = subprocess.run([sys.executable, '-B', '-I', '-c', PROBE, str(self.root), step],
                              capture_output=True, text=True, timeout=300)
        if done.returncode:
            raise AssertionError(done.stderr[-2000:])
        return json.loads(done.stdout.strip().splitlines()[-1])

    def edit(self, name, change):
        path = self.root / 'atlas_tectonics' / name
        before = path.read_bytes()
        path.write_bytes(change(before))
        return before


class IdentityProbeTest(unittest.TestCase):

    def test_listed_edits_leave_the_identity_and_a_bound_edit_moves_it(self):
        """T-X2."""
        with _Copy() as copy:
            base = copy.run('identity')
            for name, change in (
                    ('machine_resources_monitor.py', lambda b: b + b'\n'),
                    ('resources_gate.py', lambda b: b.replace(b'FLOOR_BYTES = GIB ', b'FLOOR_BYTES = GIB+1', 1))):
                before = copy.edit(name, change)
                self.assertNotEqual((copy.root / 'atlas_tectonics' / name).read_bytes(), before)
                self.assertEqual(copy.run('identity'), base, name)
                copy.edit(name, lambda _: before)
            copy.edit('integration_parallel_dispatch.py', lambda b: b + b'\n')
            self.assertNotEqual(copy.run('identity'), base)

    def test_a_listed_file_edited_during_a_run_is_refused(self):
        """T-X3: the digest leaves the file out; the boundary check does not."""
        with _Copy() as copy:
            outcome = copy.run('edit-then-verify')
        self.assertIn(outcome, ('write refused', 'source changed; create a new execution context'))

    def test_the_interpreter_arithmetic_is_bound(self):
        """Issue 51: the Python DLL, the Decimal extension with libmpdec, and the decimal and fractions sources."""
        with _Copy() as copy:
            runtime = copy.run('runtime')
        expected = {'decimal_extension', 'stdlib:decimal', 'stdlib:fractions'}
        if sys.platform == 'win32':
            expected.add('python_dll')
        self.assertLessEqual(expected, set(runtime['binaries']))
        self.assertIn('libmpdec', runtime['versions'])
        self.assertEqual(runtime['versions']['python_dll_scope'],
                         'loaded-handle' if sys.platform == 'win32' else 'not examined; interpreter library unbound')

    def test_an_arithmetic_module_without_a_file_refuses(self):
        script = (PROBE.split('step = ')[0] + "import fractions\n"
                  "del fractions.__file__\n"
                  "try:\n    r._decimal_runtime()\nexcept r.TectonicsError as e:\n    print(json.dumps(str(e)))\n"
                  "else:\n    print(json.dumps('accepted'))\n")
        with _Copy() as copy:
            done = subprocess.run([sys.executable, '-B', '-I', '-c', script, str(copy.root)],
                                  capture_output=True, text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertEqual(json.loads(done.stdout.strip().splitlines()[-1]),
                         'loaded arithmetic module has no file to bind: fractions')


if __name__ == '__main__' and sys.argv[1:] == ['--tables']:
    print(json.dumps({'READERS': _readers(), 'SELECTION_TAKES': _selection_takes()}, indent=1))
elif __name__ == '__main__':
    unittest.main()
