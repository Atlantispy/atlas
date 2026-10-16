"""Bounded orchestration controls; synthetic archives are NOT run acceptance."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import ast
import gc
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

import initial_workload as IW
import run_prepared_restart as R

HERE = Path(__file__).resolve().parent


def encoded(row):
    return json.dumps(row, sort_keys=True, separators=(',', ':')).encode()


def loaded_here():
    """Every R module this process has loaded; selection fences must pin them."""
    found = set()
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name and Path(name).suffix == '.py' and Path(name).resolve().parent == HERE:
            found.add(Path(name).resolve())
    return found


def calls_named(function):
    named = lambda n: n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, 'id', None)
    result = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            result.setdefault(named(node), []).append(node)
    return result


def function_node(tree, name):
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rp-', dir=HERE)
        self.folder = Path(self.temp.name)
        self.native = self.folder/'src'
        (self.native/'atlas_tectonics').mkdir(parents=True)
        (self.native/'atlas_tectonics/__init__.py').write_text('# synthetic source-fence fixture\n', encoding='utf8')
        self.helper = self.folder/'fixture_restart_driver.py'
        self.helper.write_text('def advance_prepared_interval(**kwargs):\n    return {"status": "PASS"}\n', encoding='utf8')
        self.policy = self.folder/'fixture-policy.json'
        self.policy.write_bytes(encoded({'fixture': 'NOT A COMPATIBILITY POLICY'}))
        self.manifest = self.folder/'manifest.json'
        self.extra, self.data = [], []
        self.write_manifest()
        pin = lambda p: dict(path=self.relative(p), sha256=R.file_hash(p))
        self.row = dict(schema=R.PROFILE_SCHEMA, workspace=str(HERE),
            source_manifest=pin(self.manifest), native_root=self.relative(self.native),
            # R itself is a root here because this test and the runner load from it.
            import_roots=[self.relative(self.folder), '.'],
            modules={name: self.relative(self.helper) for name in R.REQUIRED_MODULES},
            preparation=pin(self.helper), compatibility_policy=pin(self.policy), evidence_root=self.relative(self.folder),
            historical_source_root=self.relative(self.native), advance_driver=dict(module='fixture_restart_driver', **pin(self.helper)),
            output_directory=str(self.folder/'new-output'), store_limits={}, compression={},
            completed_query_directory=self.relative(self.folder/'completed-queries'),
            completed_query_limits=dict(max_entries=2000000, max_store_bytes=8 << 30))
        self.path = self.folder/'profile.json'
        self.profile = self.write_profile()

    def relative(self, path):
        return Path(path).relative_to(HERE).as_posix()

    def write_manifest(self):
        paths = {Path(R.__file__).resolve(), Path(__file__).resolve(), self.helper,
                 self.native/'atlas_tectonics/__init__.py', *loaded_here(), *self.extra}
        self.manifest.write_bytes(encoded(dict(files={self.relative(p): R.file_hash(p) for p in paths},
            source_hashes={'atlas_tectonics/__init__.py': R.file_hash(self.native/'atlas_tectonics/__init__.py')},
            data_only={self.relative(p): R.file_hash(p) for p in self.data})))

    def write_profile(self):
        self.row['source_manifest'] = dict(path=self.relative(self.manifest), sha256=R.file_hash(self.manifest))
        self.path.write_bytes(encoded(self.row))
        return R.RestartProfile.read(self.path, R.file_hash(self.path))

    def tearDown(self):
        for name in ('fixture_restart_driver', 'shadow_mod', 'data_ref'):
            sys.modules.pop(name, None)
        self.temp.cleanup()

    def test_inspection_only_has_no_outputs_or_native_imports(self):
        argv = R.command(self.profile, sys.executable)
        self.assertIn('--launch', argv)
        self.assertIn('--workload', argv)
        self.assertNotIn('--stop-before-advance', argv)
        self.assertFalse(Path(self.row['output_directory']).exists())
        self.assertNotIn('atlas_tectonics', sys.modules)
        self.assertEqual((R.RSS_BYTES, R.FREE_BYTES, R.START_BYTES, R.LOGICAL_BYTES),
                         (12 << 30, 1 << 30, 10 << 30, 16 << 30))

    def test_compact_profile_explicit_format_and_complete_helpers(self):
        self.row['storage_format'] = 'interval-catalog-v1'
        with self.assertRaisesRegex(R.RestartRefused, 'helper module bindings'):
            self.write_profile()
        self.row['modules'].update({name: self.relative(self.helper) for name in R.COMPACT_MODULES})
        profile = self.write_profile()
        self.assertTrue(R.compact_profile(profile.record()))
        R.RestartSources(profile).verify()
        self.row['storage_format'] = 'unknown-format'
        with self.assertRaisesRegex(R.RestartRefused, 'storage format'):
            self.write_profile()

    def test_dev_timing_command_preserves_off_argv(self):
        baseline = R.command(self.profile, sys.executable)
        self.assertNotIn('--dev-timing', baseline)
        self.assertEqual(R.command(self.profile, sys.executable, dev_timing=False), baseline)
        self.assertEqual(R.command(self.profile, sys.executable, dev_timing=True),
                         baseline+['--dev-timing'])
        self.assertEqual(R.command(self.profile, sys.executable, stop_before_advance=True,
                                   dev_timing=True), baseline+['--stop-before-advance', '--dev-timing'])
        with self.assertRaisesRegex(R.RestartRefused, 'dev timing flag'):
            R.command(self.profile, sys.executable, dev_timing='1')

    def test_changed_helper_membership_and_profile_refuse(self):
        self.helper.write_text('# changed source\n', encoding='utf8')
        with self.assertRaisesRegex(R.RestartRefused, 'source changed'):
            R.RestartSources(self.profile).verify()
        self.path.write_bytes(encoded(dict(self.row, unexpected='no schema extension')))
        with self.assertRaisesRegex(R.RestartRefused, 'closed reviewed'):
            R.RestartProfile.read(self.path, R.file_hash(self.path))

    def test_extra_native_file_refused_even_when_existing_hashes_match(self):
        (self.native/'atlas_tectonics/unreviewed.py').write_text('# unbound\n', encoding='utf8')
        with self.assertRaisesRegex(R.RestartRefused, 'inventory'):
            R.RestartSources(self.profile).verify()

    def test_import_source_pin_and_module_identity(self):
        sources = R.RestartSources(self.profile)
        before = list(sys.path)
        with sources.selected():
            module = sources.module('fixture_restart_driver')
            self.assertEqual(module.advance_prepared_interval(), {'status': 'PASS'})
            # This textual success has no capability to call the runner.
            with self.assertRaisesRegex(R.RestartRefused, 'actual selected'):
                R.run_prepared_restart({'status': 'PASS'}, sources=sources, guard=None, record={}, save=lambda: None)
        self.assertEqual(sys.path, before)

    def test_existing_output_and_traversal_refused(self):
        Path(self.row['output_directory']).mkdir()
        with self.assertRaisesRegex(R.RestartRefused, 'exclusive new'):
            R.command(self.profile, sys.executable)
        self.row['native_root'] = '../outside'
        with self.assertRaisesRegex(R.RestartRefused, 'contained'):
            R.RestartSources(self.write_profile())

    def test_duplicate_json_and_missing_policy_refused(self):
        with self.assertRaisesRegex(R.RestartRefused, 'duplicate'):
            R._json(b'{"pin":1,"pin":2}')
        self.policy.unlink()
        with self.assertRaises(FileNotFoundError):
            R.command(self.profile, sys.executable)

    def test_live_configuration_cannot_diverge_from_pinned_file(self):
        sources = R.RestartSources(self.profile)
        with self.assertRaisesRegex(R.RestartRefused, 'immutable'):
            sources.manifest_pin = '0'*64
        forged = R.RestartProfile(self.path, self.profile.sha256,
            encoded(dict(self.row, output_directory='different')))
        with self.assertRaisesRegex(R.RestartRefused, 'in-memory profile'):
            R.RestartSources(forged)

    def test_authenticated_copy_precedes_store_aware_conversion(self):
        tree = ast.parse(Path(R.__file__).read_text(encoding='utf8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_prepared_restart')
        calls = [n for n in ast.walk(function) if isinstance(n, ast.Call)]
        named = lambda n: n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, 'id', None)
        admission = next(n for n in calls if named(n) == 'admit_historical_endpoint')
        copied = next(n for n in calls if named(n) == '_copy_original')
        converted = next(n for n in calls if named(n) == 'materialise')
        published = next(n for n in calls if named(n) == 'publish_and_reopen')
        self.assertLess(admission.lineno, copied.lineno)
        self.assertLess(copied.lineno, converted.lineno)
        self.assertLess(converted.lineno, published.lineno)
        self.assertEqual(next(k.value.id for k in converted.keywords if k.arg == 'working_store'), 'store')

    # New refusals: extended module binding, path hygiene, data-only, profile fields.
    def test_extended_required_modules_and_shadowing_refused(self):
        for name in ('probe_heat_original_connected_r9', 'private_heat_original_joined_r6',
                     'private_heat_original_continuation_r1', 'private_heat_joined_consumer_r6',
                     'private_heat_original_coverage_r3', 'private_heat_issuer_resources_r1',
                     'private_heat_gmp_resources_r1', 'private_heat_functionals_parallel_r1',
                     'private_heat_restored_binding_ram_recovery_r1', 'private_heat_restored_binding_ram_context_r1',
                     'private_heat_resource_diagnostics_r1', 'private_heat_geometry_observer_r1',
                     'initial_workload', 'funding_transfer', 'continuation_transfer', 'partition_store',
                     'i04_differential_modes', 'dev_stage_timing'):
            self.assertIn(name, R.REQUIRED_MODULES)
        self.assertEqual(len(set(R.REQUIRED_MODULES)), len(R.REQUIRED_MODULES))
        self.assertNotIn('prepared_interval_driver', R.REQUIRED_MODULES)
        self.row['modules'] = dict(self.row['modules'], extra='x.py')
        with self.assertRaisesRegex(R.RestartRefused, 'complete explicit helper'):
            self.write_profile()
        # R/initial_workload.py resolves before the bound fixture copy.
        bound = self.folder/'initial_workload.py'
        bound.write_text('# bound copy that a same-named source shadows\n', encoding='utf8')
        self.extra = [bound, Path(IW.__file__).resolve()]
        self.write_manifest()
        self.row['modules'] = {name: self.relative(self.helper) for name in R.REQUIRED_MODULES}
        self.row['modules']['initial_workload'] = self.relative(bound)
        self.row['import_roots'] = ['.', self.relative(self.folder)]
        sources = R.RestartSources(self.write_profile())
        with sources.selected():
            with self.assertRaisesRegex(R.RestartRefused, 'shadowing refused: initial_workload'):
                sources.module('initial_workload')

    def test_first_resolution_over_selected_roots(self):
        first, second = self.folder/'a', self.folder/'b'
        for root in (first, second):
            root.mkdir()
            (root/'shadow_mod.py').write_text('ROOT = %r\n' % root.name, encoding='utf8')
        self.extra = [first/'shadow_mod.py', second/'shadow_mod.py']
        self.write_manifest()
        self.row['import_roots'] = [self.relative(first), self.relative(second), '.']
        sources = R.RestartSources(self.write_profile())
        with sources.selected():
            import shadow_mod
            self.assertEqual(shadow_mod.ROOT, 'a')
            sources.check_imported()
            sys.modules.pop('shadow_mod')
            spec = importlib.util.spec_from_file_location('shadow_mod', second/'shadow_mod.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules['shadow_mod'] = module
            try:
                with self.assertRaisesRegex(R.RestartRefused, 'first resolution over selected roots: shadow_mod'):
                    sources.check_imported()
            finally:
                sys.modules.pop('shadow_mod', None)

    def test_historical_sys_path_entries_refused(self):
        historical = HERE/R.HISTORICAL_RELATIVE
        for entry, refused in ((historical, True), (historical/'source/tectonics/src', True),
                               (historical/'native-composed-r7/tectonics/src', True),
                               (historical/'native-composed-r6', True),
                               (historical/'source/tectonics/tests', False), (HERE, False)):
            self.assertIs(R.historical_import_path(HERE, str(entry)), refused, entry)
        sources = R.RestartSources(self.profile)
        with sources.selected():
            sources.check_imported()
            sys.path.append(str(historical/'source'/'tectonics'/'src'))
            with self.assertRaisesRegex(R.RestartRefused, 'historical import root'):
                sources.check_imported()
            sys.path.pop()

    def test_native_module_outside_selected_root_refused(self):
        sources = R.RestartSources(self.profile)
        with sources.selected():
            fake = types.ModuleType('atlas_tectonics.foreign')
            fake.__file__ = str(self.folder/'old/atlas_tectonics/foreign.py')
            sys.modules['atlas_tectonics.foreign'] = fake
            try:
                with self.assertRaisesRegex(R.RestartRefused, 'native module outside the selected runtime'):
                    sources.check_imported()
            finally:
                sys.modules.pop('atlas_tectonics.foreign', None)

    def test_data_only_references_hashed_and_never_imported(self):
        reference = self.folder/'data_ref.py'
        reference.write_text('VALUE = 1\n', encoding='utf8')
        self.data = [reference]
        self.write_manifest()
        sources = R.RestartSources(self.write_profile())
        sources.verify()
        with sources.selected():
            with self.assertRaisesRegex(R.RestartRefused, 'unbound source import'):
                import data_ref  # noqa: F401
            spec = importlib.util.spec_from_file_location('data_ref', reference)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules['data_ref'] = module
            try:
                with self.assertRaisesRegex(R.RestartRefused, 'data-only reference imported as code'):
                    sources.check_imported()
            finally:
                sys.modules.pop('data_ref', None)
        reference.write_text('VALUE = 2\n', encoding='utf8')
        with self.assertRaisesRegex(R.RestartRefused, 'data-only reference changed'):
            sources.verify()
        self.extra = [reference]
        self.write_manifest()
        with self.assertRaisesRegex(R.RestartRefused, 'disjoint'):
            R.RestartSources(self.write_profile())

    def test_manifest_without_data_only_refused(self):
        row = json.loads(self.manifest.read_bytes())
        del row['data_only']
        self.manifest.write_bytes(encoded(row))
        with self.assertRaisesRegex(R.RestartRefused, 'data-only'):
            R.RestartSources(self.write_profile())

    def test_noncanonical_output_and_query_limits_refused(self):
        canonical = self.row['output_directory']
        for value in (str(self.folder/'x'/'..'/'new-output'), canonical.lower(), 'relative-output',
                      canonical.replace('\\', '/')):
            self.row['output_directory'] = value
            with self.assertRaisesRegex(R.RestartRefused, 'canonical absolute restart output'):
                self.write_profile()
        self.row['output_directory'] = canonical
        for limits in (None, {}, dict(max_entries=0, max_store_bytes=1), dict(max_entries=1),
                       dict(max_entries=True, max_store_bytes=1), dict(max_entries=1, max_store_bytes=1, extra=1)):
            self.row['completed_query_limits'] = limits
            with self.assertRaisesRegex(R.RestartRefused, 'completed-query entry and byte limits'):
                self.write_profile()

    def test_stop_before_advance_is_never_pass(self):
        argv = R.command(self.profile, sys.executable, stop_before_advance=True)
        self.assertEqual(argv[-1], '--stop-before-advance')
        self.assertEqual(R.final_status([], stop_before_advance=True), R.STOPPED_STATUS)
        self.assertEqual(R.final_status([], stop_before_advance=False), R.PASS_STATUS)
        for flag in (True, False):
            self.assertEqual(R.final_status([dict(type='x')], stop_before_advance=flag), 'FAILED')
        self.assertNotIn('PASS', R.STOPPED_STATUS)
        with self.assertRaisesRegex(R.RestartRefused, 'explicit stop-before-advance'):
            R.command(self.profile, sys.executable, stop_before_advance='yes')
        tree = ast.parse(Path(R.__file__).read_text(encoding='utf8'))
        function = function_node(tree, 'run_prepared_restart')
        branch = next(n for n in ast.walk(function) if isinstance(n, ast.If) and
                      isinstance(n.test, ast.Name) and n.test.id == 'stop_before_advance')
        inside = lambda nodes, name: any(isinstance(n, ast.Call) and getattr(n.func, 'id', None) == name
                                         for node in nodes for n in ast.walk(node))
        self.assertFalse(inside(branch.body, '_advance_checked'))
        self.assertFalse(inside(branch.body, 'EndpointCheckpoints'))
        self.assertTrue(inside(branch.orelse, '_advance_checked'))
        self.assertEqual(len(calls_named(function)['_advance_checked']), 1)
        workload = function_node(tree, '_workload')
        status = [n for n in ast.walk(workload) if isinstance(n, ast.Constant) and n.value == R.PASS_STATUS]
        self.assertEqual(status, [], 'the workload must derive its status from final_status only')

    def test_run_order_gates_and_storage_points(self):
        tree = ast.parse(Path(R.__file__).read_text(encoding='utf8'))
        function = function_node(tree, 'run_prepared_restart')
        calls = calls_named(function)
        line = lambda name: min(n.lineno for n in calls[name])
        order =('module', 'interpreter_gate', '_check_historical_root', '_guard_boundary', 'phase',
                 'admit_historical_endpoint', '_copy_original', 'materialise', '_check_runtime_binding',
                 'initial_workload_state', 'require_initial_duration', 'publish_and_reopen',
                 '_published_root', '_advance_checked')
        self.assertEqual([line(name) for name in order], sorted(line(name) for name in order))
        labels = [n.args[1].value for n in sorted(calls['storage_point'], key=lambda n: n.lineno)]
        self.assertEqual(labels, ['original', 'after-copy', 'after-materialise', 'after-publish-reopen',
                                  'before-advance', 'after-advance', 'after-store-close'])
        driver = calls['_advance_checked'][0]
        self.assertEqual(ast.unparse(next(k.value for k in driver.keywords if k.arg == 'fence')),
                         'sources.check_imported')
        checkpoints = calls['EndpointCheckpoints'][0]
        self.assertLessEqual({'max_store_bytes', 'max_entries'}, {k.arg for k in checkpoints.keywords})
        boundary = ast.unparse(function_node(tree, '_guard_boundary'))
        self.assertIn('H.DIAGNOSTICS_PIN', boundary)
        self.assertIn("sources.module('private_heat_resource_diagnostics_r1')", boundary)

    def test_interpreter_gate_requires_seeded_hook_free_start(self):
        code = ('import json, run_prepared_restart as R\n'
                'try:\n    print(json.dumps(R.interpreter_gate()))\n'
                'except R.RestartRefused as error:\n    print(json.dumps({"refused": str(error)}))\n')
        for seed, refused in (('0', None), ('123', 'PYTHONHASHSEED=0'), (None, 'PYTHONHASHSEED=0')):
            env = {k: v for k, v in R.launch_environment().items() if k != 'PYTHONHASHSEED'}
            if seed is not None:
                env['PYTHONHASHSEED'] = seed
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=HERE, env=env,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            row = json.loads(result.stdout)
            if refused:
                self.assertIn(refused, row['refused'])
            else:
                self.assertEqual(row['interpreter_seed'], dict(PYTHONHASHSEED='0', hash_randomization=0))
                self.assertEqual(row['instrumentation_at_start'], dict(trace=False, profile=False,
                                 monitoring_tools={}, tracemalloc=False))
                self.assertEqual(row['launch_environment'], R.LAUNCH_ENV)
        env = dict(R.launch_environment(), PYTHONTRACEMALLOC='1')
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=HERE, env=env,
                                capture_output=True, text=True, timeout=60)
        self.assertIn('foreign instrumentation', json.loads(result.stdout)['refused'])

    def test_storage_points_are_stat_only(self):
        checkpoint = self.folder/'checkpoint.sqlite'
        checkpoint.write_bytes(b'x'*1000)
        Path(str(checkpoint)+'-journal').write_bytes(b'j')
        queries = self.folder/'queries'
        queries.mkdir()
        (queries/'owner.lock').write_bytes(b'')
        (queries/'a.query').write_bytes(b'q'*10)
        (queries/'b.query').write_bytes(b'q'*5)
        (queries/'c.partial-0123').write_bytes(b'p'*7)
        (queries/'stray').write_bytes(b's')

        class Store:
            def statistics(self):
                return dict(unique_chunks=3, encoded_payload_bytes=9, snapshots=2, database_bytes=1000,
                            operations={}, shared_budget={})
        record = {}
        with mock.patch('sqlite3.connect', side_effect=AssertionError('sqlite opened')):
            first = R.storage_point(record, 'after-copy', checkpoint=checkpoint, query_directory=queries,
                                    output=self.folder, store=Store())
            Path(str(checkpoint)+'-journal').unlink()
            R.storage_point(record, 'after-store-close', checkpoint=checkpoint)
        self.assertEqual(first['checkpoint_bytes'], 1000)
        self.assertEqual(first['sidecars'], ['-journal'])
        self.assertEqual(first['completed_query_directory'], dict(query_files=2, query_bytes=15, partial_files=1,
                         partial_bytes=7, other_files=1, other_bytes=1))
        self.assertEqual(first['store'], dict(unique_chunks=3, encoded_payload_bytes=9, snapshots=2,
                                              database_bytes=1000))
        self.assertGreater(first['output_tree']['files'], 5)
        self.assertEqual([row['label'] for row in record['storage']], ['after-copy', 'after-store-close'])
        self.assertEqual(record['storage'][1]['sidecars'], [])


class DevTimingIntegrationTests(unittest.TestCase):
    def test_checkpoints_follow_completed_subsections_outside_loops(self):
        tree = ast.parse(Path(R.__file__).read_text(encoding='utf8'))
        function = function_node(tree, 'run_prepared_restart')
        calls = calls_named(function)
        checkpoints = sorted(calls['checkpoint'], key=lambda node: node.lineno)
        for compact in (False, True):
            labels = []
            for node in checkpoints:
                label = node.args[0]
                if isinstance(label, ast.IfExp):
                    self.assertEqual(ast.unparse(label.test), 'compact')
                    label = label.body if compact else label.orelse
                labels.append(ast.literal_eval(label))
            self.assertEqual(labels, [
                'current-plans-prepared', 'historical-endpoint-authenticated',
                'authenticated-original-bound' if compact else 'authenticated-checkpoint-copied',
                'endpoint-materialised', 'frozen-initial-workload-authenticated',
                'root-published-and-reopened', 'sources-and-original-verified'])
        self.assertTrue(all(ast.unparse(node.func) == 'timing.checkpoint' for node in checkpoints))
        self.assertIn("timing = sources.module('dev_stage_timing')", ast.unparse(function))
        preceding = ('preparation', 'admit_historical_endpoint', '_copy_original',
                     'materialise', 'require_initial_duration', 'publish_and_reopen')
        following = ('open_original_readonly', '_copy_original', 'materialise',
                     'initial_workload_state', 'publish_and_reopen', '_published_root')
        for checkpoint, before, after in zip(checkpoints, preceding, following, strict=False):
            self.assertLess(min(node.lineno for node in calls[before]), checkpoint.lineno)
            self.assertLess(checkpoint.lineno, min(node.lineno for node in calls[after]))
        self.assertLess(max(node.lineno for node in calls['file_hash']
                            if node.lineno < checkpoints[-1].lineno), checkpoints[-1].lineno)
        self.assertLess(checkpoints[-1].lineno,
                        min(node.lineno for node in ast.walk(function) if isinstance(node, ast.Return)))
        for loop in (node for node in ast.walk(function) if isinstance(node, (ast.For, ast.While))):
            self.assertFalse(any(node in checkpoints for node in ast.walk(loop)))

    def test_cli_resolves_opt_in_before_source_loading(self):
        args = ['--profile', 'unused.json', '--profile-sha256', '0'*64]
        for flag, env, expected in ((False, '0', False), (True, '0', True),
                                    (False, '1', True), (False, '', False)):
            with self.subTest(flag=flag, env=env), mock.patch.dict(os.environ,
                    {'ATLAS_DEV_STAGE_TIMING': env}), mock.patch.object(
                    R.RestartProfile, 'read', return_value=object()) as read, mock.patch.object(
                    R, 'command', return_value=['fixture']) as command, mock.patch('builtins.print'):
                self.assertEqual(R.main(args+(['--dev-timing'] if flag else [])), 0)
                read.assert_called_once()
                self.assertIs(command.call_args.kwargs['dev_timing'], expected)
        with mock.patch.dict(os.environ, {'ATLAS_DEV_STAGE_TIMING': 'yes'}), mock.patch.object(
                R.RestartProfile, 'read') as read:
            with self.assertRaisesRegex(R.RestartRefused, 'unset, 0 or 1'):
                R.main(args+['--dev-timing'])
            read.assert_not_called()
        with mock.patch.dict(os.environ, {'ATLAS_DEV_STAGE_TIMING': '1'}), mock.patch.object(
                R.RestartProfile, 'read', return_value=object()), mock.patch.object(
                R, '_workload', return_value=0) as workload:
            self.assertEqual(R.main(args+['--workload']), 0)
            self.assertIs(workload.call_args.kwargs['dev_timing'], True)

    def test_workload_collect_is_selected_and_closes_before_finalisation(self):
        for enabled in (False, True):
            for failure in (False, True):
                with self.subTest(enabled=enabled, failure=failure), tempfile.TemporaryDirectory() as directory:
                    events = []
                    output = Path(directory)/'run.json'
                    profile = types.SimpleNamespace(sha256='a'*64,
                        record=lambda: dict(output_directory=directory))
                    budget = types.SimpleNamespace(reserved_bytes=0)
                    budget.statistics = lambda: dict(peak_reserved_bytes=64 if enabled else 0, category_peaks={})
                    active = [False]
                    self_assert = self.assertTrue

                    class Guard:
                        def __init__(self, path, record, save):
                            self.budget = budget

                        def check(self, **kwargs):
                            self_assert(budget.reserved_bytes == 0)
                            events.append('final-check')

                        def close(self):
                            events.append('guard-close')

                    def save(path, record):
                        path.write_text(json.dumps(record), encoding='utf8')

                    @contextmanager
                    def collect(guard, path, *, enabled, record, metadata):
                        self_assert(active[0] and path == Path(directory))
                        self_assert(metadata == dict(profile_sha256=profile.sha256))
                        events.append('collect-enter')
                        budget.reserved_bytes = 64 if enabled else 0
                        try:
                            yield None
                        finally:
                            budget.reserved_bytes = 0
                            events.append('collect-exit')

                    timing = types.SimpleNamespace(enabled=lambda flag: flag, collect=collect)
                    guardian = types.SimpleNamespace(ContinuationGuard=Guard, _write=save)

                    class Sources:
                        @contextmanager
                        def selected(self):
                            active[0] = True
                            events.append('selected')
                            try:
                                yield
                            finally:
                                active[0] = False
                                events.append('unselected')

                        def module(self, name):
                            self_assert(active[0])
                            events.append('module:'+name)
                            return timing if name == 'dev_stage_timing' else guardian

                        def check_imported(self):
                            self_assert(budget.reserved_bytes == 0)
                            events.append('final-imports')

                        def verify(self):
                            self_assert(budget.reserved_bytes == 0)
                            events.append('final-sources')

                    def run(*args, **kwargs):
                        self.assertIs(kwargs['stop_before_advance'], True)
                        self.assertEqual(budget.reserved_bytes, 64 if enabled else 0)
                        events.append('run')
                        if failure:
                            raise RuntimeError('fixture failure')
                        return budget

                    with mock.patch.dict(os.environ, {'ATLAS_DEV_STAGE_TIMING': '0'}), mock.patch.object(
                            R, 'RestartSources', return_value=Sources()), mock.patch.object(
                            R, 'run_prepared_restart', side_effect=run):
                        code = R._workload(profile, stop_before_advance=True, dev_timing=enabled)
                    record = json.loads(output.read_bytes())
                    self.assertEqual(code, int(failure))
                    self.assertEqual(record['status'], 'FAILED' if failure else R.STOPPED_STATUS)
                    self.assertEqual(record['final_reserved_bytes'], 0)
                    self.assertLess(events.index('selected'), events.index('module:dev_stage_timing'))
                    self.assertLess(events.index('collect-enter'), events.index('run'))
                    self.assertLess(events.index('run'), events.index('collect-exit'))
                    self.assertLess(events.index('collect-exit'), events.index('final-imports'))
                    self.assertEqual(events[-1], 'unselected')

    def test_invalid_environment_precedes_workload_output(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = types.SimpleNamespace(record=lambda: dict(output_directory=directory))
            with mock.patch.dict(os.environ, {'ATLAS_DEV_STAGE_TIMING': 'true'}), mock.patch.object(
                    R, 'RestartSources') as sources:
                with self.assertRaisesRegex(R.RestartRefused, 'unset, 0 or 1'):
                    R._workload(profile)
                sources.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])


class FakeBudget:
    def __init__(self):
        self.reserved_bytes = 0
        self.categories = []

    def reserve(self, size, *, category):
        budget = self

        class Lease:
            def __enter__(self):
                budget.reserved_bytes += size
                budget.categories.append(category)
                return self

            def __exit__(self, *_):
                budget.reserved_bytes -= size
        return Lease()


class FakeControl:
    def duration(self, case):
        masses = np.sum(case['state'].native_state.array('component_mass_kg'), axis=0)
        return float(np.sum(case['state'].native_state.array('enthalpy_j')/masses))/1000


class InitialWorkloadTests(unittest.TestCase):
    inner = (slice(1, 3),)*3
    shapes = dict(component_mass_kg=(2, 2, 2, 2), enthalpy_j=(2, 2, 2))

    def slice_array(self, name, value):
        return value[(slice(None), *self.inner)] if name == 'component_mass_kg' else value[self.inner]

    def full(self):
        mass = np.arange(2*4*4*4, dtype='<f8').reshape(2, 4, 4, 4)+1
        enthalpy = np.arange(4*4*4, dtype='<f8').reshape(4, 4, 4)*3+5
        return dict(component_mass_kg=mass, enthalpy_j=enthalpy)

    def build(self, budget, shapes=None):
        return IW._build(self.full(), slice_array=self.slice_array, shapes=shapes or self.shapes,
                         root_key='root-key', budget=budget, check=lambda: None)

    def test_workload_state_exposes_only_two_read_only_retained_arrays(self):
        budget = FakeBudget()
        full = self.full()
        state = self.build(budget)
        retained = 2*2*2*2*8+2*2*2*8+4096
        self.assertEqual(budget.reserved_bytes, retained)
        enthalpy = state.native_state.array('enthalpy_j')
        np.testing.assert_array_equal(enthalpy, full['enthalpy_j'][self.inner])
        np.testing.assert_array_equal(state.native_state.array('component_mass_kg'),
                                      full['component_mass_kg'][(slice(None), *self.inner)])
        with self.assertRaises(ValueError):
            enthalpy[0, 0, 0] = 1.
        for access in (lambda: state.native_state.array('tracer:damage'), lambda: state.fields,
                       lambda: state.result_id, lambda: state.native_state.descriptor()):
            with self.assertRaises(IW.InitialWorkloadRefused):
                access()
        with self.assertRaisesRegex(IW.InitialWorkloadRefused, 'immutable'):
            state.native_state = None
        with self.assertRaisesRegex(IW.InitialWorkloadRefused, 'immutable'):
            state.native_state._arrays = {}
        row = state.record()
        self.assertEqual(row['root_key'], 'root-key')
        self.assertEqual(row['arrays']['enthalpy_j']['sha256'],
                         sha256(np.ascontiguousarray(full['enthalpy_j'][self.inner]).tobytes()).hexdigest())
        # An escaped view keeps the retained reservation alive; release follows it.
        escaped = enthalpy[1]
        state = enthalpy = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, retained)
        del escaped
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(budget.categories, ['restart-initial-workload-scratch', 'restart-initial-workload-retained'])

    def test_layout_refusal_and_held_error_release(self):
        budget = FakeBudget()
        with self.assertRaisesRegex(IW.InitialWorkloadRefused, 'layout differs: component_mass_kg'):
            self.build(budget, dict(self.shapes, component_mass_kg=(3, 2, 2, 2)))
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        full = self.full()
        full['enthalpy_j'] = full['enthalpy_j'].astype('>f8')
        with self.assertRaisesRegex(IW.InitialWorkloadRefused, 'layout differs: enthalpy_j'):
            IW._build(full, slice_array=self.slice_array, shapes=self.shapes, root_key='r', budget=budget,
                      check=lambda: None)
        with self.assertRaisesRegex(IW.InitialWorkloadRefused, 'exact original root workload'):
            IW._build(dict(full, extra=full['enthalpy_j']), slice_array=self.slice_array, shapes=self.shapes,
                      root_key='r', budget=budget, check=lambda: None)
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_duration_gate_refuses_before_any_driver_work(self):
        budget = FakeBudget()
        state = self.build(budget)
        case = dict(native='plans', state=state)
        expected = FakeControl().duration(case)
        self.assertEqual(IW.require_initial_duration(FakeControl(), case, expected=expected), expected)
        with self.assertRaisesRegex(IW.InitialWorkloadRefused, 'differs from the authenticated first-interval'):
            IW.require_initial_duration(FakeControl(), case, expected=expected*(1+2**-40))
        with self.assertRaisesRegex(IW.InitialWorkloadRefused, r"case\['state'\] must be the authenticated"):
            IW.require_initial_duration(FakeControl(), dict(native='plans'), expected=expected)
        with self.assertRaisesRegex(IW.InitialWorkloadRefused, 'not dict'):
            IW.require_initial_duration(FakeControl(), dict(state={}), expected=expected)
        for value in (1, float('nan'), -1., None):
            with self.assertRaisesRegex(IW.InitialWorkloadRefused, 'expected duration'):
                IW.require_initial_duration(FakeControl(), case, expected=value)


class ProbeExecutionIdentityTests(unittest.TestCase):
    """Store-free probe controls; a synthetic package stands in for the runtime."""
    workspace = HERE.parents[3]

    def setUp(self):
        import probe_execution_identity as PROBE
        self.PROBE = PROBE
        self.temp = tempfile.TemporaryDirectory(prefix='pe-', dir=HERE)
        folder = Path(self.temp.name)
        self.native, self.helpers = folder/'src', folder/'helpers'
        (self.native/'atlas_tectonics').mkdir(parents=True)
        self.helpers.mkdir()
        (self.native/'atlas_tectonics/__init__.py').write_text('# synthetic probe package\n', encoding='utf8')
        (self.native/'atlas_tectonics/reuse.py').write_text(
            'class ExecutionContext:\n'
            '    def __init__(self, backend):\n'
            '        self.provenance = dict(execution_identity="f"*64, execution_mode="strict")\n'
            '    def __enter__(self):\n        return self\n'
            '    def __exit__(self, *args):\n        return False\n'
            '    def verify_boundary(self):\n        pass\n'
            'def require_strict_execution():\n    pass\n', encoding='utf8')
        self.manifest = folder/'manifest.json'
        self.write_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def relative(self, path):
        return Path(path).relative_to(self.workspace).as_posix()

    def write_manifest(self, data_only=None):
        files = [Path(R.__file__).resolve(), Path(self.PROBE.__file__).resolve(),
                 *sorted((self.native/'atlas_tectonics').glob('*.py'))]
        self.manifest.write_bytes(encoded(dict(files={self.relative(p): R.file_hash(p) for p in files},
            source_hashes={p.relative_to(self.native).as_posix(): R.file_hash(p)
                           for p in sorted((self.native/'atlas_tectonics').glob('*.py'))},
            data_only={} if data_only is None else data_only)))
        return R.file_hash(self.manifest)

    def config(self, **changes):
        options = dict(workspace=str(self.workspace), manifest=self.relative(self.manifest),
            manifest_sha256=R.file_hash(self.manifest), native_root=self.relative(self.native),
            import_roots=[self.relative(self.helpers)], backend='scipy', python=sys.executable)
        options.update(changes)
        return self.PROBE.configuration(**options)

    def test_configuration_refusals(self):
        config = self.config()
        self.assertEqual(config['roots'], [self.native, self.helpers])
        historical = R.HISTORICAL_RELATIVE
        for root in (historical, historical+'/source/tectonics/src', historical+'/native-composed-r7/tectonics/src'):
            with self.subTest(root=root), self.assertRaisesRegex(self.PROBE.ProbeRefused, 'historical import root'):
                self.config(import_roots=[root])
        for changes, error, message in (
                (dict(python=str(Path(self.temp.name)/'python.exe')), self.PROBE.ProbeRefused, '.r44-env'),
                (dict(manifest_sha256='0'*64), R.RestartRefused, 'pinned configuration changed'),
                (dict(native_root=self.relative(self.helpers), import_roots=[self.relative(self.native)]),
                 self.PROBE.ProbeRefused, 'atlas_tectonics package'),
                (dict(import_roots=[]), self.PROBE.ProbeRefused, 'explicit distinct import roots'),
                (dict(import_roots=[self.relative(self.helpers)]*2), self.PROBE.ProbeRefused, 'distinct'),
                (dict(backend='numba'), self.PROBE.ProbeRefused, 'backend'),
                (dict(import_roots=['../outside']), self.PROBE.ProbeRefused, 'contained')):
            with self.subTest(message=message), self.assertRaisesRegex(error, message):
                self.config(**changes)
        argv = self.PROBE.child_command(config, manifest=self.relative(self.manifest),
            native_root=self.relative(self.native), import_roots=[self.relative(self.helpers)])
        self.assertEqual(argv[:4], [str(Path(sys.executable).absolute()), '-B', str(Path(self.PROBE.__file__).resolve()),
                                    '--child'])
        self.assertEqual(argv[argv.index('--import-root')+1], self.relative(self.helpers))

    def test_child_refuses_outside_launch_environment_and_changed_sources(self):
        config = self.config()
        with mock.patch.dict(os.environ, dict(PYTHONHASHSEED='1')):
            with self.assertRaisesRegex(self.PROBE.ProbeRefused, 'exact restart launch environment'):
                self.PROBE.child(config)
        self.PROBE._verify(config)
        (self.native/'atlas_tectonics/extra.py').write_text('# unreviewed\n', encoding='utf8')
        with self.assertRaisesRegex(self.PROBE.ProbeRefused, 'native package inventory'):
            self.PROBE._verify(config)
        (self.native/'atlas_tectonics/extra.py').unlink()
        self.write_manifest()
        config = self.config()
        (self.native/'atlas_tectonics/reuse.py').write_text('# changed\n', encoding='utf8')
        with self.assertRaisesRegex(self.PROBE.ProbeRefused, 'pinned source changed'):
            self.PROBE._verify(config)

    def test_fresh_child_measures_under_the_launch_environment(self):
        stdout = __import__('io').StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(stdout):
            code = self.PROBE.main(['--workspace', str(self.workspace), '--manifest', self.relative(self.manifest),
                '--manifest-sha256', R.file_hash(self.manifest), '--native-root', self.relative(self.native),
                '--import-root', self.relative(self.helpers)])
        self.assertEqual(code, 0)
        measured = json.loads(stdout.getvalue())
        self.assertEqual(measured['execution_provenance'], dict(execution_identity='f'*64, execution_mode='strict'))
        self.assertEqual(measured['launch_environment'], R.LAUNCH_ENV)
        self.assertEqual(measured['interpreter']['hash_randomization'], 0)
        self.assertEqual((measured['status'], measured['fresh_process'], measured['policy_written']),
                         ('MEASURED_NOT_REVIEWED', True, False))
        self.assertEqual(measured['loaded_workspace_sources'], 4)
        self.assertNotIn('atlas_tectonics', sys.modules)


class SuccessorStore:
    """Small metadata-only store fake: key -> metadata, change token, read log."""
    def __init__(self, rows):
        self.rows, self.token, self.reads, self.write_on_read = deepcopy(rows), 0, [], False

    def metadata(self, key):
        self.reads.append(key)
        if self.write_on_read:
            self.token += 1
        value = self.rows.get(key)
        return None if value is None else deepcopy(value)

    def change_token(self):
        return self.token


class SuccessorWorkflow:
    """The live workflow fields _successor_checks reads after a driver returns."""
    def __init__(self, store, root_bytes, head, *, time_s, funding_id='funding', workflow_id='wf'):
        self._store, self._root, self._head = store, root_bytes, deepcopy(head)
        self.time_s, self.funding_id, self.workflow_id = time_s, funding_id, workflow_id

    def inspect(self):
        return dict(workflow_id=self.workflow_id, head=self._head['key'], intervals=self._head['sequence'],
                    time_s=self.time_s, funding_id=self.funding_id)


class SuccessorCheckTests(unittest.TestCase):
    """Owner decision 14 Oct 2026: structural successor checks, no same-process cold reopen."""
    def setUp(self):
        import workflow_transfer as W
        self.W = W
        self.root = dict(schema=W.WORKFLOW_SCHEMA, workflow_id='wf', key='r'*64, kind='migrated-root', sequence=3,
                         funding_id='funding', state=dict(fields=dict(time_s=12.5)))
        self.head = dict(schema=W.WORKFLOW_SCHEMA, workflow_id='wf', key=W.workflow_key('successor', 'r'*64),
                         kind='successor', sequence=4, parent_key='r'*64, parent_digest=W.digest(self.root),
                         funding_id='funding', state=dict(fields=dict(time_s=25.)))
        self.before = dict(workflow_id='wf', head='r'*64, intervals=3, time_s=12.5, funding_id='funding')
        self.root_bytes = W.canonical(self.root)
        self.budget = FakeBudget()

    def tearDown(self):
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def run_checks(self, *, rows=None, head=None, store=None, passed_store=None, root_bytes=None, **live):
        store = store or SuccessorStore({self.root['key']: self.root, self.head['key']: self.head}
                                        if rows is None else rows)
        workflow = SuccessorWorkflow(store, self.root_bytes if root_bytes is None else root_bytes,
                                     self.head if head is None else head, **dict(dict(time_s=25.), **live))
        return R._successor_checks(workflow, store=store if passed_store is None else passed_store,
                                   before=dict(self.before), parent=deepcopy(self.root),
                                   root_bytes=self.root_bytes, budget=self.budget), store

    def test_persisted_successor_passes_with_small_metadata_reads_only(self):
        after, store = self.run_checks()
        self.assertEqual(self.budget.categories, ['workflow-transfer-metadata-scratch'])
        self.assertEqual(after, dict(workflow_id='wf', head=self.head['key'], intervals=4, time_s=25.,
                                     funding_id='funding'))
        # The new head, its parent, the root and the absent next key; nothing else.
        self.assertEqual(store.reads, [self.head['key'], 'r'*64, 'r'*64,
                                       self.W.workflow_key('successor', self.head['key'])])
        self.assertEqual(R.SAME_PROCESS_REOPEN_DROPPED, 'dropped by owner decision 14 Oct 2026; '
                         'the mandatory independent fresh-process reader performs the cold reopen')

    def test_driver_without_a_valid_persisted_successor_is_refused(self):
        W, root, head = self.W, self.root, self.head
        changed = lambda row, **values: dict(deepcopy(row), **values)
        rows = lambda *extra: {r['key']: r for r in (root, *extra)}
        foreign = changed(head, key='f'*64)
        cases = {
            # A textual PASS: the driver returned without any successor.
            'live_head_advanced_exactly_one_interval': dict(head=root, time_s=12.5),
            'successor_head_persisted': dict(rows=rows()),
            'persisted_head_equals_live_head': dict(rows=rows(changed(head, sequence=5))),
            'persisted_successor_links_parent': dict(rows=rows(changed(head, parent_digest='0'*64)),
                                                     head=changed(head, parent_digest='0'*64)),
            'live_root_workflow_and_funding_unchanged': dict(funding_id='new-funding'),
            'clock_advanced_and_persisted': dict(rows=rows(changed(head, state=dict(fields=dict(time_s=12.5)))),
                                                 head=changed(head, state=dict(fields=dict(time_s=12.5))),
                                                 time_s=12.5),
            'persisted_parent_unchanged': dict(rows={root['key']: changed(root, sequence=2), head['key']: head}),
            'no_further_successor': dict(rows=rows(head, changed(head, key=W.workflow_key('successor', head['key'])))),
        }
        variants = {
            'persisted funding change': ('persisted_successor_links_parent',
                dict(rows=rows(changed(head, funding_id='new')), head=changed(head, funding_id='new'))),
            'foreign successor key': ('persisted_successor_links_parent', dict(rows=rows(foreign), head=foreign)),
            'persisted clock differs from live': ('clock_advanced_and_persisted', dict(time_s=30.)),
            'root bytes changed': ('live_root_workflow_and_funding_unchanged',
                                   dict(root_bytes=W.canonical(changed(root, sequence=9)))),
            'workflow identity changed': ('live_root_workflow_and_funding_unchanged', dict(workflow_id='other')),
            'incomplete persisted successor': ('successor metadata incomplete',
                dict(rows=rows({k: v for k, v in head.items() if k != 'state'}),
                     head={k: v for k, v in head.items() if k != 'state'})),
        }
        cases.update({name: (check, options) for name, (check, options) in variants.items()})
        for name, value in cases.items():
            check, options = (name, value) if type(value) is dict else value
            with self.subTest(name), self.assertRaisesRegex(R.RestartRefused, check):
                self.run_checks(**options)
        written = SuccessorStore({root['key']: root, head['key']: head})
        written.write_on_read = True
        with self.assertRaisesRegex(R.RestartRefused, 'store_unchanged_during_checks'):
            self.run_checks(store=written)
        with self.assertRaisesRegex(R.RestartRefused, 'workflow store replaced'):
            self.run_checks(passed_store=SuccessorStore({}))

    def test_no_same_process_successor_reopen_and_exact_record(self):
        tree = ast.parse(Path(R.__file__).read_text(encoding='utf8'))
        for name in ('_advance_checked', '_successor_checks'):
            text = ast.unparse(function_node(tree, name))
            for forbidden in ('open_migrated', 'store.get(', '_store.get(', 'iter_chunks', '_manifest(',
                              'spatial_audit_arrays'):
                self.assertNotIn(forbidden, text, name)
        self.assertIn('_successor_checks', calls_named(function_node(tree, '_advance_checked')))
        updates = [node for node in ast.walk(function_node(tree, 'run_prepared_restart'))
                   if isinstance(node, ast.Call) and getattr(node.func, 'attr', None) == 'update' and
                   'same_process_cold_reopen' in {k.arg for k in node.keywords}]
        self.assertEqual(len(updates), 1)
        keywords = {k.arg: ast.unparse(k.value) for k in updates[0].keywords}
        self.assertEqual((keywords['same_process_cold_reopen'], keywords['same_process_cold_reopen_reason'],
                          keywords['successor_checks']),
                         ('False', 'SAME_PROCESS_REOPEN_DROPPED', 'list(SUCCESSOR_CHECKS)'))
        self.assertEqual(len(set(R.SUCCESSOR_CHECKS)), len(R.SUCCESSOR_CHECKS))
        self.assertEqual(R.PASS_STATUS, 'PASS_ONE_INTERVAL_PENDING_INDEPENDENT_REOPEN')


def native_fixture(directory):
    """Actual tiny owner/store transitions; explicitly synthetic old evidence.

    Only the existing fixture source composer prepares a temporary package.
    Production sources and protected callable/identity objects are not patched.
    """
    import test_workflow_fresh_process as F
    import workflow_transfer as W
    import spatial_transfer as S
    F.compose(directory)
    TS, TG = F.initialise_child(directory)
    from atlas_tectonics.storage import ArrayStore, StoreLimits
    owner = TS.SpatialTransferTests
    budget = owner.budget
    original, working = directory/'original.sqlite', directory/'new.sqlite'
    limits = StoreLimits(chunk_bytes=1024, max_array_bytes=2 << 20, max_store_bytes=16 << 20,
        max_manifest_bytes=2 << 20, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)

    def exercise():
        fixture = TS.SpatialTransferTests('test_old_root_restore_remains_strict')
        fixture.setUp()
        spatial = initial = None
        try:
            with S.admit_migrated_spatial_owner(**fixture.args) as lease:
                initial = lease.adopt()
            metadata, arrays = F.archive_operands(fixture, initial, TS, TG)
            native, spatial, interval, bridge, partition = F.restore_transfers(metadata, arrays, owner, TS, TG)
            current = TG.D.current_geometry_from_interval(interval, budget=budget)
            chain, audit = F.fixture_chain(native.record(), fixture.args, spatial, interval, partition, current, TS)
            with ArrayStore(original, limits, budget=budget) as store:
                for row in chain:
                    store.put(row['key'], {'fixture': np.array([1], dtype=np.uint8)}, row, budget=budget)
                with store._read_scope():
                    manifests = {r['key']: deepcopy(store._manifest(r['key'])) for r in chain}
            original_sha = R.file_hash(original)
            capsule = dict(schema='atlas.restart-historical-endpoint.v1', authority=F.FIXTURE_ONLY,
                chain_metadata=chain, snapshot_manifests=manifests,
                source=dict(root_key=chain[0]['key'], head_key=chain[-1]['key'], workflow_id=chain[0]['workflow_id'],
                    sequence=3, time_s=12.5, store_token=dict(fixture=F.FIXTURE_ONLY)),
                producer=dict(execution_identity='a'*64, source_manifest_sha256='b'*64))
            historical, compatibility = F.fixture_admissions(capsule, native.record()['input']['origin'],
                audit, original, native.record(), budget)
            # Explicit synthetic fixture issuer binding, never a public issuer.
            binding = historical.binding()
            binding['database_sha256'] = original_sha
            object.__setattr__(historical, '_binding', W.canonical(binding))
            base = W.bind_migrated_base(native_transfer=native, spatial_transfer=spatial,
                geometry_transfer=bridge, interval=interval, partition=partition,
                historical_admission=historical, runtime_admission=compatibility, budget=budget)
            source, pin = R._copy_original(historical, working, budget=budget, check=lambda: None)
            assert source == original and pin == original_sha
            phases = []
            with ArrayStore(working, limits, budget=budget) as store:
                with R.publish_and_reopen(store, base, budget=budget, check=lambda: None, phase=phases.append) as workflow:
                    assert workflow._head['sequence'] == 3
                    assert workflow._state.record() == native.state.record()
                    assert workflow._funding is spatial.funding
                    before = store.change_token()
                    previous_capture = os.environ.get('ATLAS_FOCUSED_ARTIFACT_DIR')
                    fences = []
                    def fake_success(**kwargs):
                        assert os.environ['ATLAS_FOCUSED_ARTIFACT_DIR'] == str(directory)
                        assert fences == ['fence']
                        return {'status': 'SUCCESS'}
                    try:
                        R._advance_checked(fake_success, workflow=workflow, base=base,
                            case={}, execution=None, guard=None, record={}, save=lambda: None, artifacts=directory,
                            fence=lambda: fences.append('fence'))
                    except R.RestartRefused as error:
                        assert 'exactly one valid successor' in str(error)
                    else:
                        raise AssertionError('mere SUCCESS was accepted without a real successor')
                    assert fences == ['fence', 'fence'], fences
                    assert os.environ.get('ATLAS_FOCUSED_ARTIFACT_DIR') == previous_capture
                    assert store.change_token() == before
                    assert owner.native.statistics()['accepted_intervals'] == 0
                    assert [store.metadata(r['key']) for r in chain] == chain
                    # A driver that moves only the live head (nothing persisted) is
                    # refused by the structural checks on the actual workflow/store.
                    saved_head = workflow._head

                    def unpersisted_head(*, workflow, **kwargs):
                        head = workflow._head
                        workflow._head = dict(head, key=W.workflow_key('successor', head['key']),
                                              kind='successor', sequence=head['sequence']+1)
                    try:
                        R._advance_checked(unpersisted_head, workflow=workflow, base=base,
                            case={}, execution=None, guard=None, record={}, save=lambda: None, artifacts=directory,
                            fence=lambda: None)
                    except R.RestartRefused as error:
                        assert 'successor_head_persisted' in str(error), str(error)
                    else:
                        raise AssertionError('an unpersisted live successor head was accepted')
                    finally:
                        workflow._head = saved_head
                    assert store.change_token() == before
                    assert workflow.inspect()['head'] == saved_head['key']
            assert phases == ['publish-migrated-root', 'cold-reopen-migrated-root']
            assert R.file_hash(original) == original_sha
            try:
                R._copy_original({'status': 'PASS'}, directory/'refused.sqlite', budget=budget, check=lambda: None)
            except R.RestartRefused:
                pass
            else:
                raise AssertionError('dictionary admitted as historical evidence')
            assert not (directory/'refused.sqlite').exists()
        finally:
            if spatial is not None:
                spatial.owner.close()
            if initial is not None:
                initial.owner.close()
            fixture.args = fixture.native_owned = None

    exercise()
    TS.SpatialTransferTests.tearDownClass()
    TS.SpatialTransferTests.collar = TS.SpatialTransferTests.native = None
    TS.SpatialTransferTests.old = TS.SpatialTransferTests.current = None
    gc.collect()
    assert budget.reserved_bytes == 0, budget.statistics()
    print('ACTUAL_NATIVE_RESTART_PHASE_FIXTURE_PASS reserved_bytes=0; no solve or acceptance', flush=True)


class NativePhaseTests(unittest.TestCase):
    def test_actual_copy_publish_reopen_and_fake_success_refusal(self):
        with tempfile.TemporaryDirectory(prefix='rn-', dir=HERE) as temporary:
            result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                '--native-fixture', temporary], capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout[-2000:]+result.stderr[-10000:])
            self.assertIn('ACTUAL_NATIVE_RESTART_PHASE_FIXTURE_PASS', result.stdout)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--native-fixture':
        native_fixture(Path(sys.argv[2]).resolve())
    else:
        unittest.main(verbosity=2)
