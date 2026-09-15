import copy
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from . import binding as b, provenance as p


class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle=b.load()

    def test_exact_parent_seal(self):
        self.assertEqual(p.sha(p.checked(p.R6_SEAL)),p.R6_SEAL_SHA256)
        for path,digest in self.bundle.identity['external_test_reference_sources'].items():
            self.assertEqual(p.sha(p.checked(path)),digest)

    def test_parent_identity(self):
        self.assertEqual(self.bundle.parent.verify(),p.R6_SOURCE_SHA256)

    def test_recursive_parent_identity(self):
        self.assertEqual(self.bundle.identity['retained_source_identity'],p.retained_record()['source_identity'])

    def test_actual_preserved_driver(self):
        self.assertTrue(self.bundle.parent.pipeline.__file__.endswith('generator_upgrade_r4\\pipeline.py'))
        self.assertTrue(self.bundle.parent.r3.__file__.endswith('generator_upgrade_r3\\pipeline.py'))

    def test_same_solver_class_identity(self):
        self.assertIs(self.bundle.parent.r3.sw,self.bundle.parent.solver)
        self.assertTrue(self.bundle.parent.solver.__file__.endswith('generator_upgrade_r6\\soil_water.py'))

    def test_no_global_predecessor_module(self):
        self.assertFalse(any(k.startswith('work.generator_upgrade_r6.') for k in sys.modules))

    def test_no_private_namespace_leak(self):
        self.assertFalse(any(k.startswith('_diadem_r6_') for k in sys.modules))

    def test_public_pipeline_ignores_preloaded_module(self):
        from types import ModuleType
        fake=ModuleType('work.generator_upgrade_r7.pipeline'); fake.preloaded_stale=True
        with patch.dict(sys.modules,{'work.generator_upgrade_r7.pipeline':fake}):
            actual=self.bundle.pipeline
        self.assertIsNot(actual,fake)
        self.assertFalse(hasattr(actual,'preloaded_stale'))
        self.assertEqual(self.bundle.graph.executed['work.generator_upgrade_r7.pipeline']['sha256'],
            self.bundle.identity['r7_sources'][str(p.HERE/'pipeline.py')])

    def test_changed_source_hash_rejected(self):
        with self.assertRaises(ValueError): p.checked(p.HERE/'binding.py','0'*64)

    def test_relative_path_refused(self):
        with self.assertRaises(ValueError): p.plain_path('binding.py')

    def test_traversal_refused(self):
        with self.assertRaises(ValueError): p.plain_path(p.HERE/'..'/'binding.py')

    def test_nonexistent_file_refused(self):
        with self.assertRaises(ValueError): p.checked(p.HERE/'no-such-source.py')

    def test_directory_refused(self):
        with self.assertRaises(ValueError): p.checked(p.HERE)

    def test_oversize_refused(self):
        with patch.object(p,'MAX_BYTES',1):
            with self.assertRaises(ValueError): p.checked(p.HERE/'binding.py')

    def test_reparse_directory_checked_before_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); original=Path.lstat
            def mocked(path,*args,**kwargs):
                if path==root:
                    from types import SimpleNamespace
                    return SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)
                return original(path,*args,**kwargs)
            with patch.object(Path,'lstat',mocked):
                with self.assertRaisesRegex(ValueError,'linked/reparse'): p.source_snapshot(root)

    def test_empty_source_inventory_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError): p.source_snapshot(Path(directory))

    def test_changed_r6_inventory_rejected(self):
        with patch.object(p,'source_snapshot',return_value={}):
            with self.assertRaises(ValueError): p.retained_record()

    def test_changed_r7_inventory_rejected(self):
        altered=copy.deepcopy(self.bundle.identity); altered['r7_sources']['unexpected']='0'*64
        with patch.object(p,'source_identity',return_value=(altered,self.bundle.source_sha256)):
            with self.assertRaises(ValueError): self.bundle.verify()

    def test_checkpoint_reverifies_current_sources(self):
        with patch.object(self.bundle,'verify',side_effect=ValueError('changed')):
            with self.assertRaisesRegex(ValueError,'changed'): self.bundle.checkpoint({})

    def test_checkpoint_refuses_predecessor_schema(self):
        with self.assertRaises(ValueError): self.bundle.checkpoint({'schema':'diadem.strict-soil-water-result.r6'})

    def test_checkpoint_detaches_state(self):
        row={'schema':b.RESULT_SCHEMA,'source_sha256':self.bundle.source_sha256,
             'recipe_sha256':'1'*64,'state':{'completed_exposures':0}}
        result=self.bundle.checkpoint(row); row['state']['completed_exposures']=1
        self.assertEqual(result['state']['completed_exposures'],0)
        self.assertEqual(result['state_sha256'],self.bundle.storage.sha(self.bundle.storage.encoded(result['state'])))

    def test_duplicate_json_refused(self):
        with self.assertRaises(ValueError): self.bundle.storage.decoded(b'{"x":1,"x":2}')

    def test_nonfinite_json_refused(self):
        with self.assertRaises(ValueError): self.bundle.storage.decoded(b'{"x":NaN}')

    def test_current_flags_are_reportable(self):
        self.assertIn(sys.flags.optimize,(0,2))


class VerificationTests(unittest.TestCase):
    def setUp(self):
        from . import verify
        self.v=verify
        self.ids=['synthetic.Test.test_one']
        self.record={'status':'PASS','tests':1,'test_ids':self.ids,'inventory_sha256':verify.inventory_digest(self.ids),
            'started':self.ids,'stopped':self.ids,'passed':self.ids,'failures':0,'errors':0,'skips':0,
            'expected_failures':0,'unexpected_successes':0}

    def validate(self,record):
        with patch.object(self.v,'EXPECTED_COUNT',1),patch.object(self.v,'INVENTORY_SHA256',self.v.inventory_digest(self.ids)):
            self.v.validate_tests(record)

    def test_inventory_requires_reviewed_pin(self):
        with patch.object(self.v,'EXPECTED_COUNT',None):
            with self.assertRaisesRegex(ValueError,'pending'): self.v.require_inventory(self.ids)

    def test_exact_inventory_accepts_actual_success(self):
        self.validate(self.record)

    def test_count_without_test_identity_not_enough(self):
        self.record['test_ids']=['synthetic.Test.different']
        with self.assertRaises(ValueError): self.validate(self.record)

    def test_boolean_test_count_is_not_integer_evidence(self):
        self.record['tests']=True
        with self.assertRaises(ValueError): self.validate(self.record)

    def test_skipped_test_not_success(self):
        self.record['skips']=1
        with self.assertRaises(ValueError): self.validate(self.record)

    def test_expected_failure_not_success(self):
        self.record['expected_failures']=1
        with self.assertRaises(ValueError): self.validate(self.record)

    def test_actual_started_inventory_required(self):
        self.record['started']=[]
        with self.assertRaises(ValueError): self.validate(self.record)

    def test_actual_stopped_inventory_required(self):
        self.record['stopped']=[]
        with self.assertRaises(ValueError): self.validate(self.record)

    def test_actual_passed_inventory_required(self):
        self.record['passed']=[]
        with self.assertRaises(ValueError): self.validate(self.record)

    def test_declared_inventory_hash_rechecked(self):
        self.record['inventory_sha256']='0'*64
        with self.assertRaises(ValueError): self.validate(self.record)

    def test_parent_oo_environment_does_not_corrupt_normal_worker(self):
        helper,_,_=self.v.utility()
        with patch.dict(os.environ,{'PYTHONOPTIMIZE':'2'}):
            environment=helper.child_environment()
        self.assertNotIn('PYTHONOPTIMIZE',environment)

    def test_nonfresh_verifier_entry_refused(self):
        with patch.object(self.v,'ENTRY_SOURCE_SHA256',None):
            with self.assertRaises(ValueError): self.v.install()

    def test_missing_execution_map_refused(self):
        helper,_,_=self.v.utility()
        with self.assertRaises(ValueError): self.v.validate_execution({},None,helper)

    def test_forged_execution_hash_refused(self):
        helper,_,_=self.v.utility(); path=str(p.HERE/'verify.py')
        with patch.object(self.v,'source_map',return_value={path:p.sha(p.checked(path))}):
            with self.assertRaises(ValueError): self.v.validate_execution({path:'0'*64},None,helper)

    def test_required_execution_cannot_be_omitted(self):
        helper,_,_=self.v.utility(); path=str(p.HERE/'verify.py'); digest=p.sha(p.checked(path))
        with patch.object(self.v,'source_map',return_value={path:digest}):
            with self.assertRaisesRegex(ValueError,'required actual source'): self.v.validate_execution({path:digest},None,helper)


if __name__=='__main__': unittest.main()
