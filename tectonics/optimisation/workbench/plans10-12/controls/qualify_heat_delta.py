"""Bounded queued qualification of the combined Plan10/11/12 heat seam.

Source preparation does not execute this runner. Root owns queue admission.
Four fresh child processes: current identity admission, eight-cell full forward,
compact store reopen, and mutations of disposable helper copies. No full
workflow, historical migration, native production acceptance or timing claim.
"""
import argparse
import ast
from hashlib import sha256
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback

HERE = Path(__file__).resolve().parent
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
ROOT = T / 'ac/p1012-r1'
COMPOSITION_SHA = 'cb71df92d0ab2f3ab175c43a669d5b8ffc1d4d350cbdc49b68fd6f2cabfb74d5'
PROFILE = T / 'ac/p1012-run-r1/fresh-profile.json'
PROFILE_SHA = '5d1912888fff8271c8241ec6b10b961e9bb2acb7f6189b9d423b90f8235b0ad1'
DELTA_SHA = 'e26d7afd1d2672306bcbfaef540a8b2387af19eef6fdd2846e642679cb4626e1'
FIXTURE = HERE.parents[1] / 'plan05/integrated-r13/order-repair/test_physical_order_r1.py'
FIXTURE_SHA = 'c2dd52a4d962cd28f71f196932e1d3d08aa5026ee27eac3c029344831d2f6c6f'
STORE_FIXTURE = ROOT / 'helpers/test_private_heat_snapshot_store_r4.py'
STORE_FIXTURE_SHA = '824cee4c00ba330fb327d1857acd300d0cf1710323a6d0eeb730bc54348ef579'
CASES = ('identities', 'eight-cell', 'compact-reopen', 'mutation')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def raw_pin(path, expected):
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == expected, 'Source pin differs: ' + str(path))
    return raw


def refused(operation, error_type, text):
    try:
        operation()
    except error_type as error:
        require(text in str(error), 'Unexpected refusal: ' + repr(error))
        return type(error).__name__ + ': ' + str(error)
    raise AssertionError('Required refusal did not happen: ' + text)


def source_inputs():
    composition = json.loads(raw_pin(ROOT / 'composition.json', COMPOSITION_SHA))
    raw_pin(PROFILE, PROFILE_SHA)
    delta = json.loads(raw_pin(HERE / 'integration-map.json', DELTA_SHA))
    require((len(composition['outputs']), len(composition['helpers'])) == (239, 390),
            'Exact combined source inventory required')
    require(len(delta['files']) == 17 and delta['selected']['lane'] == 'lf3'
            and delta['selected']['h5a_enabled'] is False, 'Exact selected delta required')
    for name, row in delta['files'].items():
        area, member = name.split('/', 1)
        declared = composition['helpers' if area == 'helpers' else 'outputs'][member]
        require(declared == row['output_sha256'], 'Combined heat delta differs: ' + name)
        raw_pin(ROOT / name, declared)
    raw_pin(FIXTURE, FIXTURE_SHA)
    raw_pin(STORE_FIXTURE, STORE_FIXTURE_SHA)
    return composition


class PinnedLoader(importlib.machinery.SourceFileLoader):
    def __init__(self, fullname, path, expected):
        super().__init__(fullname, str(path))
        self.expected = expected

    def get_code(self, fullname):
        return compile(raw_pin(Path(self.path), self.expected), self.path, 'exec')

    def get_source(self, fullname):
        return raw_pin(Path(self.path), self.expected).decode('utf8')


class SourceFence(importlib.abc.MetaPathFinder):
    """All declared native/helper imports use pinned source bytes, never pyc."""
    def __init__(self, composition, helpers):
        self.native = composition['outputs']
        self.helpers = composition['helpers']
        self.helper_root = helpers

    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'atlas_tectonics' or fullname.startswith('atlas_tectonics.'):
            stem = fullname.replace('.', '/')
            member = stem + '.py'
            package = member not in self.native
            if package:
                member = stem + '/__init__.py'
            require(member in self.native, 'Undeclared native import: ' + fullname)
            source, expected = ROOT / 'src' / member, self.native[member]
        elif '.' not in fullname and fullname + '.py' in self.helpers:
            source = self.helper_root / (fullname + '.py')
            expected, package = self.helpers[fullname + '.py'], False
        else:
            return None
        loader = PinnedLoader(fullname, source, expected)
        return importlib.util.spec_from_file_location(fullname, source, loader=loader,
            submodule_search_locations=[str(source.parent)] if package else None)


def install_fence(composition, helpers):
    sys.dont_write_bytecode = True
    # Keep only interpreter/runtime search roots; remove caller/project paths.
    prefixes = (Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve())
    sys.path[:] = [str(ROOT / 'src'), str(helpers)] + [p for p in sys.path if p
        and any(Path(p).resolve().is_relative_to(root) for root in prefixes)]
    require(not any(n == 'atlas_tectonics' or n.startswith('private_heat_') for n in sys.modules),
            'Fresh child process required before scientific imports')
    sys.meta_path.insert(0, SourceFence(composition, helpers))


def current():
    import private_heat_native_issuer_r13 as I
    import private_heat_checkpoint_consumer_r10 as C
    import private_heat_joined_consumer_r6 as J
    import private_heat_restored_binding_r10 as B
    from atlas_tectonics import integration_private_heat_cold as cold
    return I, C, J, B, cold


def identity_body(composition, helpers):
    I, C, J, B, cold = current()
    import private_heat_restored_binding_ram_context_r1 as context
    import private_heat_restored_binding_ram_recovery_r1 as recovery
    from atlas_tectonics.reuse import ExecutionContext
    require(I.HERE == helpers.resolve(), 'Issuer lookup root escaped combined helpers')
    require(I.F.ORDER in I._private_modules(), 'ORDER absent from loaded identity')
    require(str(Path(I.F.ORDER.__file__).resolve()) in dict(I._IMPORTED_SOURCES),
            'ORDER absent from imported-source closure')
    I._verify_implementation()
    I.F._check_sources(lambda: None)
    C._verify(None)
    sources = J.source_bindings()
    require(all(composition['helpers'][name] == pin for name, pin in sources.items()),
            'Joined current source bindings differ')
    require(cold.B is B and cold._BINDING_SHA == composition['helpers'][Path(B.__file__).name],
            'Native cold binding must select current restored-r10')
    cold._verify(None)
    with ExecutionContext('scipy') as execution:
        B._verify(execution, None)
        context._verify(execution, None)
        recovery._verify(execution, None)
    foreign = refused(lambda: cold.restore_checkpoint(object(), parent={}, head={},
        spatial_state=None, collar_state=None, source_audit=None, exchange={}, audit_arrays={}),
        TypeError, 'Actual spatial CollarWorkflow recovery context required')
    for module in tuple(sys.modules.values()):
        file = getattr(module, '__file__', None)
        name = getattr(module, '__name__', '')
        if file and (name.startswith('atlas_tectonics') or name + '.py' in composition['helpers']):
            path = Path(file).resolve()
            expected_root = ROOT / 'src' if name.startswith('atlas_tectonics') else helpers
            require(path.is_relative_to(expected_root.resolve()), 'Loaded source escaped fence: ' + str(path))
    return dict(current_source_admission=True, order_loaded_and_source_bound=True,
                native_cold_foreign_context_refusal=foreign)


def identities(composition, helpers):
    import run_fresh_interval as fresh
    profile = fresh.FreshProfile.read(PROFILE, PROFILE_SHA)
    sources = fresh.FreshSources(profile)
    require(sources.native_root == ROOT / 'src' and sources.import_roots[0] == helpers,
            'Actual fresh profile selects another source root')
    # Existing source admission performs its required complete verification at
    # entry/exit; do not add a second manual full inventory scan.
    with sources.selected():
        result = identity_body(composition, helpers)
        selected = sources.module('private_heat_joined_consumer_r6')
        require(selected is sys.modules['private_heat_joined_consumer_r6'], 'Profile module binding differs')
        result.update(profile_sha256=PROFILE_SHA, manifest_sha256=sources.manifest_pin,
                      actual_fresh_sources_consumed=True, native_launch_preflight=False)
    return result


def eight_cell(composition, helpers):
    """Reuse just the pinned manufactured fixture and its exact assertions."""
    import gc
    import unittest
    from fractions import Fraction
    import private_heat_forward_kernel_r13 as F
    from atlas_tectonics.resources import WorkBudget
    tree = ast.parse(raw_pin(FIXTURE, FIXTURE_SHA))
    names = ('digest', 'cube_record', 'block_record')
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    require(len(selected) == len(names), 'Manufactured fixture functions changed')
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'PhysicalOrder')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                  and node.name == 'test_actual_full_forward_entry_eight_cell_cube')
    assignment = [node for node in method.body if isinstance(node, ast.Assign)
                  and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                  and node.targets[0].id == 'forward']
    require(len(assignment) == 1 and isinstance(assignment[0].value, ast.Call)
            and isinstance(assignment[0].value.func, ast.Name) and assignment[0].value.func.id == 'load',
            'Expected original benchmark import seam changed')
    # Sole fixture adaptation: actual fenced combined F replaces old hs/lf3 load.
    assignment[0].value = ast.copy_location(ast.Name(id='F', ctx=ast.Load()), assignment[0].value)
    case = ast.ClassDef(name='CombinedEightCell', bases=[ast.Attribute(
        value=ast.Name(id='unittest', ctx=ast.Load()), attr='TestCase', ctx=ast.Load())],
        keywords=[], body=[method], decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=selected + [case], type_ignores=[]))
    env = dict(F=F, ORDER=F.ORDER, WorkBudget=WorkBudget, gc=gc, Fraction=Fraction,
               sha256=sha256, json=json, unittest=unittest, __name__='combined_eight_cell_fixture')
    exec(compile(module, str(FIXTURE) + ':selected-eight-cell', 'exec'), env)
    test = env['CombinedEightCell']('test_actual_full_forward_entry_eight_cell_cube')
    test.test_actual_full_forward_entry_eight_cell_cube()
    return dict(eight_cells=8, physical_faces=36, workers=0, exact_accounts=True,
                original_public_cell_and_face_owner_order=True, reserved_bytes_after_release=0,
                fixture_adaptation='forward import only; original selected assertions retained')


def compact_reopen(composition, helpers, scratch):
    """Current compact persistence and binding derivation, not workflow replay."""
    import gc
    import numpy as np
    from unittest.mock import patch
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext
    from atlas_tectonics.storage import ArrayStore
    from compact_contracts import ContractError
    from content_cache import create_retained_scope
    from heat_ledger_tables import CompactHeatSnapshot
    from interval_store_set import IntervalStoreSet
    import private_heat_snapshot_store_r4 as S
    I, C, J, B, cold = current()
    budget = WorkBudget(1 << 30)
    scope = create_retained_scope(budget, process_epoch='plans10-12-heat-qualification')
    stores = candidate = snapshot = None
    try:
        with ExecutionContext('scipy') as execution:
            B._verify(execution, None)
            # A bounded reference tests actual current binding logic; it is not
            # an issued actual-owner result and never enters native restoration.
            plan = dict(original_target=dict(kind='decimal-string', value='1e-24'))
            sources = J.source_bindings()
            expected = dict(consumer=I.RESOURCES.stream_hash(C._SOURCES, None), call='1'*64,
                plan=I.RESOURCES.stream_hash(plan, None), geometry='2'*64, state='3'*64,
                loaded_dependencies=I._LOADED_IMPLEMENTATION.descriptor()['identity'],
                runtime=I.RESOURCES.stream_hash(execution.provenance, None),
                fixture_status=sha256(b'actual-owner').hexdigest())
            reference = dict(schema=B.REF_SCHEMA, consumer_sources=sources, call_id=expected['call'],
                ledger='complete immutable cell/paired-face ledger in authenticated CAS',
                plan_id=expected['plan'], geometry_id=expected['geometry'], state_id=expected['state'],
                loaded_dependency_identity=expected['loaded_dependencies'], runtime_identity=expected['runtime'],
                fixture_status=expected['fixture_status'], original_target=plan['original_target'],
                native_admission=False, production_acceptance=False)
            with budget.reserve(1 << 20, category='heat-qualification-binding-codec'):
                bindings = B._expected_bindings(reference, plan, '2'*64, '3'*64, execution, None)
                require(bindings == expected, 'Current restored binding derivation differs')
                bad = dict(reference, consumer_sources={**sources, 'private_heat_forward_kernel_r13.py': '0'*64})
                refused(lambda: B._expected_bindings(bad, plan, '2'*64, '3'*64, execution, None),
                        ValueError, 'Bounded composed heat reference required')
                bad_runtime = dict(reference, runtime_identity='0'*64)
                refused(lambda: B._expected_bindings(bad_runtime, plan, '2'*64, '3'*64, execution, None),
                        ValueError, 'Committed heat source/runtime/plan/target/reference differs')
            stores = IntervalStoreSet.create_migration(scratch / 'catalog.json', workflow_id='a'*64, scope=scope)
            candidate = stores.begin_interval(None, producer_identity=expected['consumer'],
                                               runtime_identity=expected['runtime'])
            data = dict(cell_ids=['d'*64], face_ids=['e'*64], q=['0x2', '0x4'], rows=[1, 2])
            arrays = dict(a=np.array([-0., 1.]), empty=np.empty(0))
            snapshot = CompactHeatSnapshot.from_components(data, arrays, scope=scope)
            with patch.object(ArrayStore, 'get', side_effect=AssertionError('whole store get')):
                receipt = S.save(candidate, snapshot, bindings=bindings, scope=scope)
                before = candidate.local_statistics()
                require(S.save(candidate, snapshot, bindings=bindings, scope=scope) == receipt,
                        'Compact save is not idempotent')
                require(candidate.local_statistics() == before, 'Duplicate save changed storage')
                with S.open(candidate, receipt, expected_result_id=snapshot.result_id,
                            bindings=bindings, scope=scope) as owner:
                    restored = owner.value
                    require(restored.result_id == snapshot.result_id and restored.nbytes == snapshot.nbytes,
                            'Compact detached reopen identity differs')
                    require(restored.array('a').tobytes() == arrays['a'].tobytes(), 'Stored float bytes differ')
                    restored.close()
                del restored, owner
                refused(lambda: S.open(candidate, receipt, expected_result_id=snapshot.result_id,
                    bindings=dict(bindings, consumer='0'*64), scope=scope), ContractError, 'source/call')
                wrong = json.loads(json.dumps(receipt))
                wrong['metadata']['metadata_bytes'] += 1
                refused(lambda: S.open(candidate, wrong, expected_result_id=snapshot.result_id,
                    bindings=bindings, scope=scope), ContractError, '')
            cold._verify(None)
    finally:
        if snapshot is not None:
            snapshot.close()
        if candidate is not None:
            candidate.close()
        if stores is not None:
            stores.close()
        snapshot = candidate = stores = None
        gc.collect()
        scope.close()
    require(budget.reserved_bytes == 0, 'Compact persistence leaked retained leases')
    return dict(current_binding_derivation=True, wrong_source_and_runtime_refused=True,
                compact_save_reopen=True, receipt_mutation_refused=True, whole_store_gets=0,
                reserved_bytes_after_release=0, full_workflow_cold_restore=False)


def mutation(composition, helpers):
    I, C, J, B, cold = current()
    I.F._check_sources(lambda: None)
    C._verify(None)
    cold._verify(None)
    failures = {}
    targets = (
        ('private_heat_physical_order_r1.py', {'forward': lambda: I.F._check_sources(lambda: None)}),
        ('private_heat_forward_kernel_r13.py', {'checkpoint': lambda: C._verify(None),
                                              'joined': lambda: J.source_bindings()}),
        ('private_heat_restored_binding_r10.py', {'native-cold': lambda: cold._verify(None)}),
    )
    for name, checks in targets:
        path = helpers / name
        original = raw_pin(path, composition['helpers'][name])
        require(helpers != ROOT / 'helpers' and path.parent == helpers, 'Disposable helper root required')
        try:
            path.write_bytes(original + b'\n# bounded disposable source mutation\n')
            for label, check in checks.items():
                failures[label] = refused(check, ValueError, 'changed')
        finally:
            path.write_bytes(original)
        raw_pin(path, composition['helpers'][name])
    return dict(disposable_mutation_refusals=failures, frozen_sources_modified=False)


def child(case, scratch):
    composition = source_inputs()
    helpers = ROOT / 'helpers'
    if case == 'mutation':
        helpers = scratch / 'helpers'
        helpers.mkdir()
        for name, pin in composition['helpers'].items():
            destination = helpers / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw_pin(ROOT / 'helpers' / name, pin))
    install_fence(composition, helpers)
    if case == 'identities':
        return identities(composition, helpers)
    if case == 'eight-cell':
        return eight_cell(composition, helpers)
    if case == 'compact-reopen':
        return compact_reopen(composition, helpers, scratch)
    return mutation(composition, helpers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--scratch', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.case:
        require(args.scratch is not None and args.scratch.is_dir(), 'Explicit fresh child scratch required')
        evidence = child(args.case, args.scratch)
        print(json.dumps(dict(case=args.case, status='PASS', evidence=evidence), sort_keys=True))
        return 0
    require(args.output is not None and not args.output.exists(), 'New qualification output directory required')
    source_inputs()
    runner_pin = sha256(Path(__file__).read_bytes()).hexdigest()
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(('PYTHON', 'PYDEVD', 'COVERAGE'))}
    env.update(PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    args.output.mkdir(parents=True)
    records = []
    began = time.perf_counter()
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix='heat-' + case + '-', dir=args.output) as temporary:
            command = [sys.executable, '-B', '-s', '-P', str(Path(__file__).resolve()), '--case', case, '--scratch', temporary]
            start = time.perf_counter()
            result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT, env=env,
                                    timeout=180, check=False)
            (args.output / (case + '.stdout.txt')).write_text(result.stdout, encoding='utf8')
            (args.output / (case + '.stderr.txt')).write_text(result.stderr, encoding='utf8')
            records.append(dict(case=case, returncode=result.returncode, seconds=time.perf_counter()-start,
                stdout_sha256=sha256(result.stdout.encode('utf8')).hexdigest(),
                stderr_sha256=sha256(result.stderr.encode('utf8')).hexdigest()))
            print(json.dumps(records[-1]), flush=True)
            if result.returncode:
                break
    passed = len(records) == len(CASES) and all(row['returncode'] == 0 for row in records)
    raw_pin(Path(__file__), runner_pin)
    raw_pin(ROOT / 'composition.json', COMPOSITION_SHA)
    raw_pin(PROFILE, PROFILE_SHA)
    report = dict(schema='plans10-12.focused-heat-qualification.r1', status='PASS' if passed else 'FAIL',
        runner_sha256=runner_pin, seconds=time.perf_counter()-began, composition_sha256=COMPOSITION_SHA,
        profile_sha256=PROFILE_SHA, delta_sha256=DELTA_SHA,
        fixture_sha256=FIXTURE_SHA, store_fixture_sha256=STORE_FIXTURE_SHA,
        cases=records, excludes=['full workflow lineage/cold recovery', 'historical migration',
                               'native production acceptance', 'scientific acceptance', 'performance'])
    (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    return 0 if passed else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
