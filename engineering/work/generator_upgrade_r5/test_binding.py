"""Independent source isolation/recovery checks; no retained files are edited."""
import builtins
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import py_compile
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import binding as b
from . import verify as v


class SourceIsolationTests(unittest.TestCase):
    def test_actual_private_pipeline_edges_and_shared_material_identity(self):
        bundle = b.load()
        self.assertIs(bundle.pipeline.r3, bundle.r3)
        self.assertIs(bundle.r3.sw, bundle.solver)
        self.assertIs(bundle.r3.si.landscape, bundle.r3.tt.landscape)
        self.assertIs(bundle.r3.landscape, bundle.r3.si.landscape)
        self.assertEqual(bundle.pipeline.SCHEMA, 'diadem.climate-terrain-water-soil-recipe.r4')
        self.assertEqual(bundle.r3.SCHEMA, 'diadem.terrain-water-soil-recipe.r3')

    def test_canonical_modules_builtins_and_global_import_hooks_are_unchanged(self):
        from work.generator_upgrade_r4 import pipeline as original_r4
        from work.generator_upgrade_r3 import pipeline as original_r3, soil_water as original_solver
        before = (original_r4.r3, original_r3.sw, builtins.__import__, tuple(sys.meta_path))
        bundle = b.load()
        self.assertEqual(before, (original_r4.r3, original_r3.sw, builtins.__import__, tuple(sys.meta_path)))
        self.assertIsNot(bundle.pipeline, original_r4)
        self.assertIsNot(bundle.r3, original_r3)
        self.assertIsNot(bundle.solver, original_solver)

    def test_private_namespace_is_removed_after_success(self):
        bundle = b.load()
        self.assertFalse(any(name.startswith(bundle.graph.prefix) for name in sys.modules))

    def test_distinct_bindings_do_not_share_mutable_private_modules(self):
        first, second = b.load(), b.load()
        self.assertIsNot(first.pipeline, second.pipeline)
        self.assertIsNot(first.solver, second.solver)
        self.assertEqual(first.source_sha256, second.source_sha256)
        first.pipeline.private_sentinel = True
        self.assertFalse(hasattr(second.pipeline, 'private_sentinel'))

    def test_actual_retained_source_tranches_are_verified_without_test_recount(self):
        bundle = b.load()
        old = bundle.identity['retained_source_identity']
        self.assertEqual([len(old[k]) for k in ('r4_sources', 'r3_sources', 'protected_sources',
                                               'executed_dependency_sources', 'category_contracts')], [26,25,161,2,4])
        self.assertEqual(bundle.identity['retained_r4_seal']['sha256'], b.R4_SEAL_SHA256)

    def test_changed_R4_seal_rejected_without_repin(self):
        with patch.object(b, 'R4_SEAL_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'no silent repin'):
                b.load()

    def test_exact_source_not_timestamp_valid_stale_bytecode_executes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'value.py'
            path.write_bytes(b'VALUE=99\n')
            before = path.stat()
            py_compile.compile(str(path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
            path.write_bytes(b'VALUE=11\n')
            os.utime(path, ns=(before.st_atime_ns,before.st_mtime_ns))
            spec = importlib.util.spec_from_file_location('ordinary_stale_fixture', path)
            ordinary = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ordinary)
            self.assertEqual(ordinary.VALUE, 99)
            graph = b.PrivateGraph({'work.fixture.value': (path,b.sha(path.read_bytes()))})
            self.assertEqual(graph.load('work.fixture.value').VALUE, 11)

    def test_private_compile_failure_cleans_namespace(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bad.py'
            raw = b'raise ValueError("intentional private fixture")\n'
            path.write_bytes(raw)
            graph = b.PrivateGraph({'work.fixture.bad': (path,b.sha(raw))})
            with self.assertRaisesRegex(ValueError, 'intentional private fixture'):
                graph.load('work.fixture.bad')
            self.assertFalse(any(name.startswith(graph.prefix) for name in sys.modules))
            self.assertEqual(graph.active, set())

    def test_undeclared_project_import_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bad.py'
            raw = b'from work.unbound_package import missing\n'
            path.write_bytes(raw)
            graph = b.PrivateGraph({'work.fixture.bad': (path,b.sha(raw))})
            with self.assertRaisesRegex(ValueError, 'undeclared private dependency'):
                graph.load('work.fixture.bad')

    def test_changed_captured_module_is_not_reused_as_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'value.py'
            path.write_bytes(b'VALUE=1\n')
            graph = b.PrivateGraph({'work.fixture.value': (path,b.sha(path.read_bytes()))})
            graph.load('work.fixture.value')
            path.write_bytes(b'VALUE=2\n')
            with self.assertRaisesRegex(ValueError, 'no silent repin'):
                graph.verify()

    def test_reparse_guard_runs_before_directory_or_suffix_filtering(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(b, 'HERE', Path(temp)):
            directory = Path(temp) / 'linked_directory'
            directory.mkdir()
            original = b.plain_path
            def guard(path):
                if Path(path) == directory:
                    raise ValueError('linked/reparse fixture')
                return original(path)
            with patch.object(b, 'plain_path', side_effect=guard):
                with self.assertRaisesRegex(ValueError, 'linked/reparse'):
                    b.current_sources()

    def test_real_reparse_attribute_and_path_traversal_rejected(self):
        with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFREG,st_file_attributes=0x400)):
            with self.assertRaisesRegex(ValueError, 'linked/reparse'):
                b.plain_path(b.HERE)
        with self.assertRaises(ValueError):
            b.plain_path(b.HERE/'..'/'outside.py')

    def test_r5_snapshot_change_invalidates_existing_bundle(self):
        bundle = b.load()
        with patch.object(b, 'current_sources', return_value={}):
            with self.assertRaisesRegex(ValueError, 'R5 source inventory changed'):
                bundle.verify()

    def test_retained_test_bytes_bind_only_successor_solver(self):
        bundle = b.load()
        module = bundle.retained_soil_tests()
        self.assertIs(module.w, bundle.solver)
        record = bundle.graph.executed['work.generator_upgrade_r5.retained_soil_water_tests']
        self.assertEqual(record['path'], str(b.TASK/'work/generator_upgrade_r3/test_soil_water.py'))
        self.assertEqual(record['sha256'], b.sha(b.checked(record['path'])))


class RestartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = b.load()
        cls.recipe = cls.bundle.wrap_recipe(cls.bundle.reference.recipe(), evidence='SYNTHETIC R5 wrapper/restart check')
        cls.result = cls.bundle.run(cls.recipe, stop_after=0)

    def test_actual_zero_cursor_wrapper_and_restart(self):
        checkpoint = self.bundle.checkpoint(self.result)
        self.assertEqual(checkpoint['schema'], b.CHECKPOINT_SCHEMA)
        self.assertEqual(self.bundle.run(self.recipe, stop_after=0, resume=checkpoint), self.result)

    def test_old_R4_checkpoint_cannot_be_claimed_as_R5(self):
        old = self.bundle.storage.checkpoint(self.result['state'],
            recipe_sha256=self.result['recipe_sha256'], source_sha256=self.bundle.source_sha256)
        with self.assertRaisesRegex(ValueError, 'old checkpoints are not successors'):
            self.bundle.run(self.recipe, stop_after=0, resume=old)

    def test_old_unwrapped_recipe_is_not_an_R5_recipe(self):
        with self.assertRaisesRegex(ValueError, 'R5 wrapper recipe'):
            self.bundle.run(self.recipe['retained_recipe'], stop_after=0)

    def test_rechecksummed_reset_snow_is_rejected_by_actual_deterministic_replay(self):
        cp = self.bundle.checkpoint(self.result)
        cp['state']['members']['LOW_DDF3_SIGMA2']['snow']['upper']['swe_m'] = '100'
        cp['state_sha256'] = b.sha(self.bundle.storage.encoded(cp['state']))
        with self.assertRaisesRegex(ValueError, 'deterministic'):
            self.bundle.run(self.recipe, stop_after=0, resume=cp)

    def test_changed_wrapper_recipe_cannot_reuse_checkpoint(self):
        changed = deepcopy(self.recipe)
        changed['evidence'] = 'different explicit experiment identity'
        with self.assertRaisesRegex(ValueError, 'restart identity differs'):
            self.bundle.run(changed, stop_after=0, resume=self.bundle.checkpoint(self.result))

    def test_changed_solver_binding_cannot_be_silently_reused(self):
        changed = deepcopy(self.recipe)
        changed['source_sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'source-bound R5'):
            self.bundle.run(changed, stop_after=0)

    def test_checkpoint_detaches_state_and_checks_current_source(self):
        cp = self.bundle.checkpoint(self.result)
        cp['state']['completed_events'] = 99
        self.assertEqual(self.result['state']['completed_events'], 0)
        with patch.object(self.bundle, 'verify', side_effect=ValueError('source changed')):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                self.bundle.checkpoint(self.result)

    def test_resume_shape_and_resource_bounds_apply_before_replay(self):
        cp = self.bundle.checkpoint(self.result)
        cp['extra'] = 'unrecognised'
        with self.assertRaises(ValueError):
            self.bundle.run(self.recipe, stop_after=0, resume=cp)
        cp = self.bundle.checkpoint(self.result)
        cp['state']['invalid'] = float('nan')
        with self.assertRaises(ValueError):
            self.bundle.run(self.recipe, stop_after=0, resume=cp)


class VerificationTests(unittest.TestCase):
    def record(self):
        ids = ['fixture.one', 'fixture.two']
        return {'status':'PASS', 'tests':2, 'failures':0, 'errors':0, 'skips':0,
            'expected_failures':0, 'unexpected_successes':0, 'test_ids':ids,
            'inventory_sha256':v.inventory_digest(ids),'started':ids[:],'stopped':ids[:],'passed':ids[:]}

    def validate(self, record):
        with patch.object(v,'EXPECTED_NEW_COUNT',2), patch.object(v,'NEW_INVENTORY_SHA256',v.inventory_digest(['fixture.one','fixture.two'])):
            v.validate_tests(record)

    def test_exact_complete_inventory_passes(self):
        self.validate(self.record())

    def test_same_count_substituted_test_is_not_equivalent(self):
        record = self.record(); record['test_ids'][1] = 'substituted'
        with self.assertRaisesRegex(ValueError,'inventory'):
            self.validate(record)

    def test_success_count_does_not_replace_execution_identity(self):
        record = self.record(); record['passed'].reverse()
        with self.assertRaisesRegex(ValueError,'identities'):
            self.validate(record)

    def test_bool_count_and_skipped_check_fail_closed(self):
        for key,value in (('tests',True),('skips',1),('expected_failures',1)):
            record = self.record(); record[key] = value
            with self.assertRaises(ValueError): self.validate(record)

    def test_pending_inventory_cannot_be_sealed(self):
        with patch.object(v,'EXPECTED_NEW_COUNT',None):
            with self.assertRaisesRegex(ValueError,'PENDING'):
                v.require_inventory(['fixture'])

    def test_inherited_optimisation_is_removed_from_child_environment(self):
        helper,_,_ = v.utility()
        with patch.dict(os.environ, {'PYTHONOPTIMIZE':'2'}):
            result = helper.child_environment()
        self.assertNotIn('PYTHONOPTIMIZE',result)
        self.assertEqual(result['PYTHONDONTWRITEBYTECODE'],'1')

    def test_normalisation_removes_only_observed_wall_timer(self):
        value = {'elapsed_wall_seconds':4.,'dt_seconds':1e-8,'head_m':[-.2],
                 'nested':[{'elapsed_wall_seconds':1.,'error_ratio':2000.}]}
        self.assertEqual(v.semantic(value), {'dt_seconds':1e-8,'head_m':[-.2],'nested':[{'error_ratio':2000.}]})
        self.assertEqual(value['elapsed_wall_seconds'],4.)

    def test_empty_workers_or_fake_modes_are_not_actual_execution(self):
        with self.assertRaisesRegex(ValueError,'exactly two'):
            v.validate_workers([],None,None)
        with self.assertRaisesRegex(ValueError,'actual normal'):
            v.validate_workers([{'optimisation_flag':False},{'optimisation_flag':2}],None,None)

    def test_missing_scientific_reports_cannot_be_a_success(self):
        with self.assertRaisesRegex(ValueError,'three actual'):
            v.validate_experiments({'reports':[]}, 'a'*64)

    def test_execution_source_requires_actual_capture(self):
        helper,_,_ = v.utility()
        with self.assertRaisesRegex(ValueError,'actual executed'):
            v.validate_executed({}, {},helper)


if __name__ == '__main__':
    unittest.main()
