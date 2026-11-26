"""The execution identity leaves out the four execution-only modules, and binds the interpreter's arithmetic.

T-X1 reads the package's syntax trees only and imports nothing from it. T-X2, T-X3 and the arithmetic test
run the package in a child process on a temporary copy that leaves out the installed inventory pair and the
fixtures, so the package takes its own unbound route and the copy can be edited.
"""
import ast
from importlib.util import find_spec
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / 'atlas_tectonics'
SHARED = Path(find_spec('atlas_shared').origin).parent
LISTED = ('atlas_shared.machine.resources_monitor', 'atlas_shared.machine.resources_gate', 'atlas_shared.execution.schedule',
          'integration_parallel_selection')
ADMITTED = LISTED[:3]  # admitted by construction; selection is held by (c)
STANDARD = set(sys.stdlib_module_names) | {'psutil'}

# What every other package module takes from each listed module: names, and attribute chains read through an
# alias of the module. A new entry is a new value crossing from outside the identity into bound code.
READERS = {
    'atlas_shared.machine.resources_monitor': {
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
    'atlas_shared.machine.resources_gate': {
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
            path = _module_path(name)
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
                        target = full if _module_path(full).is_file() else base
                        if (name, target, a.name, a.asname) == (
                                'atlas_shared.machine.resources_gate', 'atlas_shared.errors', 'AtlasError', None):
                            continue  # ResourcesRefused retains its builtin base and adds the shared marker.
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
    elif step == 'shared':
        print(json.dumps([c.identity, c._shared_source_sha256]))
    elif step == 'runtime':
        print(json.dumps(c._runtime))
'''

PROJECTED_PROBE = r'''
import json, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import numpy as np
from atlas_shared.machine import resources_gate_sibling as sibling
from atlas_tectonics import reuse as r
from atlas_tectonics.parameters import PlateCoolingParameters
from atlas_tectonics.storage import StoreConflict, StoreLimits

root, phase = Path(sys.argv[1]), sys.argv[2]
r._PROJECTED_DEPENDENCIES = {
    **r._PROJECTED_DEPENDENCIES, 'fixture-uses-shared': ('atlas_shared.machine.resources_gate_sibling',)}
profile = r.ThermalParameters('fixture', 'identity test', 273.0, 1573.0, 1e-6)
parameters = r.asdict(profile)
depth = np.arange(4096, dtype=np.float64)
age = np.array(123456789.0)
policy = r.CachePolicy(min_result_bytes=8, min_compute_seconds=0.0, expected_reuses=1024)
inputs = {'depth': depth, 'age': age}
limits = StoreLimits(16384, 1<<20, 32<<20)
with r.ExecutionContext('scipy') as ctx, r.ArrayStore(root/'projected.sqlite', limits) as store:
    controller = r.ReuseController()
    def cooling():
        return r.cached_temperature(depth, age, profile, store=store, context=ctx, controller=controller,
                                    cache_policy=policy)
    cooling()  # the ordinary auto policy first observes a direct calculation
    assert controller.statistics()['bypasses'] == 1
    result = cooling()
    plate = PlateCoolingParameters(profile, 100000., 3.)
    plate_control = r.ReuseController()
    def finite():
        return r.cached_plate_temperature(depth, age, plate, store=store, context=ctx, controller=plate_control,
                                          cache_policy=policy)
    finite()
    finite()
    finite_record = r._invocation_record('finite-plate-temperature-v1', inputs, r.asdict(plate), 'scipy', context=ctx)
    finite_key = r._digest(r._json(finite_record))
    assert plate_control.statistics()['writes' if phase == 'first' else 'hits'] == 1
    finite_producer = store.metadata(finite_key)
    if phase == 'first':
        assert finite_producer['producer_shared_source_sha256'] == ctx._shared_source_sha256
    record = r._invocation_record('half-space-temperature-v2', inputs, parameters, 'scipy', context=ctx)
    key = r._digest(r._json(record))
    assert r.invocation_identity('half-space-temperature-v2', inputs, parameters, backend='scipy') == key
    using = r._invocation_record('fixture-uses-shared', inputs, parameters, 'scipy', context=ctx)
    r._evaluate(store, using, lambda: result + np.float64(sibling.VALUE), result.shape, store._budget,
                context=ctx, controller=controller, cache_policy=policy)
    producer = store.metadata(key)
    if phase == 'first':
        assert controller.statistics()['writes'] == 2
        assert producer['producer_execution'] == ctx.identity
        assert producer['producer_shared_source_sha256'] == ctx._shared_source_sha256
        legacy = dict(record, schema='atlas.kernel-invocation.v2', execution=ctx.identity)
        legacy_key = r._digest(r._json(legacy))
        with r.ArrayStore(root/'legacy.sqlite', limits) as old:
            old.put(legacy_key, {'result': result}, legacy)
            def unexpected_compute():
                raise AssertionError('exact current v2 winner should have been restored')
            restored = r._evaluate(old, record, unexpected_compute, result.shape, old._budget, context=ctx,
                                   controller=r.ReuseController(), cache_policy=policy)
            assert restored.tobytes() == result.tobytes() and old.metadata(key) is None
        actual = ctx.identity
        with patch.object(ctx, '_actual_identity', actual, create=True), patch.object(ctx, '_identity', 'f'*64):
            branded = r._invocation_record('unknown-fixture-operation', inputs, parameters, 'scipy', context=ctx)
            assert branded['schema'] == 'atlas.kernel-invocation.v2' and branded['execution'] == actual
    else:
        assert controller.statistics()['hits'] == 1 and controller.statistics()['misses'] == 1
        assert producer['producer_execution'] != ctx.identity
        # The existing same-key rollback control now competes through _evaluate.
        for different in (False, True):
            db = root/f'projected-race-{different}.sqlite'
            with r.ArrayStore(db, limits) as loser, r.ArrayStore(db, limits) as winner:
                put = loser.put
                observed = {}
                def competing(invocation, result_arrays, metadata, **kwargs):
                    winner.put(invocation, {'result': result}, producer)
                    observed['before'] = winner.statistics()
                    return put(invocation, result_arrays, metadata, **kwargs)
                with patch.object(loser, 'put', side_effect=competing):
                    candidate = result + 1000.0 if different else result
                    try:
                        observed['out'] = r._evaluate(loser, record, lambda: candidate, result.shape, loser._budget,
                            context=ctx, controller=r.ReuseController(), cache_policy=policy)
                    except StoreConflict:
                        assert different, 'the projected winner and the losing result match'
                    else:
                        assert not different and observed['out'].tobytes() == result.tobytes()
                assert winner.statistics()['unique_chunks'] == observed['before']['unique_chunks']
                assert winner.metadata(key) == producer
    print(json.dumps({'key': key, 'using': r._digest(r._json(using)), 'producer': producer['producer_execution'],
                      'finite_key': finite_key, 'finite_producer': finite_producer['producer_execution'],
                      'finite_source': finite_producer['producer_shared_source_sha256'],
                      'current_source': ctx._shared_source_sha256, 'current_execution': ctx.identity}))
'''


class _Copy:
    """A temporary copy of the package on its unbound route: no installed inventory pair, no fixtures."""

    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix='atlas-identity-'))
        shutil.copytree(PACKAGE, self.root / 'atlas_tectonics', ignore=shutil.ignore_patterns(
            '_application_sources.json', '_application_sources.sha256', '_fixtures', '__pycache__'))
        shutil.copytree(SHARED, self.root / 'atlas_shared', ignore=shutil.ignore_patterns('__pycache__'))
        (self.root/'atlas_shared/machine/resources_gate_sibling.py').write_bytes(b'VALUE = 1\n')
        return self

    def __exit__(self, *_):
        shutil.rmtree(self.root, ignore_errors=True)

    def run(self, step, *args):
        done = subprocess.run([sys.executable, '-B', '-I', '-c', PROBE, str(self.root), step, *args],
                              capture_output=True, text=True, timeout=300)
        if done.returncode:
            raise AssertionError(done.stderr[-2000:])
        return json.loads(done.stdout.strip().splitlines()[-1])

    def edit(self, name, change):
        path = self.root / name
        before = path.read_bytes()
        path.write_bytes(change(before))
        return before


class IdentityProbeTest(unittest.TestCase):

    def test_listed_edits_leave_the_identity_and_a_bound_edit_moves_it(self):
        """T-X2."""
        with _Copy() as copy:
            base = copy.run('identity')
            for name, change in (
                    ('atlas_shared/machine/resources_monitor.py', lambda b: b + b'\n'),
                    ('atlas_shared/machine/resources_gate.py',
                     lambda b: b.replace(b'FLOOR_BYTES = GIB ', b'FLOOR_BYTES = GIB+1', 1))):
                before = copy.edit(name, change)
                self.assertNotEqual((copy.root / name).read_bytes(), before)
                self.assertEqual(copy.run('identity'), base, name)
                copy.edit(name, lambda _: before)
            copy.edit('atlas_tectonics/integration_parallel_dispatch.py', lambda b: b + b'\n')
            self.assertNotEqual(copy.run('identity'), base)

    def test_bound_shared_sibling_changes_fingerprint_on_restart(self):
        path = 'atlas_shared/machine/resources_gate_sibling.py'
        with _Copy() as copy:
            before = copy.run('shared')
            copy.edit(path, lambda b: b + b'# bound source change\n')
            after = copy.run('shared')
            self.assertNotEqual(before[0], after[0])
            self.assertNotEqual(before[1], after[1])

    def test_projected_auto_hit_and_same_key_rollback(self):
        def run(copy, phase):
            done = subprocess.run([sys.executable, '-B', '-I', '-c', PROJECTED_PROBE, str(copy.root), phase],
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(done.returncode, 0, done.stderr[-3000:])
            return json.loads(done.stdout.strip().splitlines()[-1])

        with _Copy() as copy:
            first = run(copy, 'first')
            copy.edit('atlas_shared/machine/resources_gate_sibling.py', lambda data: data+b'# source edit\n')
            copy.edit('atlas_shared/execution/profiling.py', lambda data: data+b'# diagnostic edit\n')
            after = run(copy, 'after')
        self.assertEqual(first['key'], after['key'])
        self.assertEqual(first['producer'], after['producer'])
        self.assertEqual(first['finite_key'], after['finite_key'])
        self.assertEqual(first['finite_producer'], after['finite_producer'])
        self.assertEqual(first['finite_source'], after['finite_source'])
        self.assertNotEqual(first['current_source'], after['current_source'])
        self.assertNotEqual(first['current_execution'], after['current_execution'])
        self.assertNotEqual(first['using'], after['using'])

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
