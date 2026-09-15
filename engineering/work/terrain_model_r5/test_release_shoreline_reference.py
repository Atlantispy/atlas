"""Focused, mocked tests for the sealed R4 release harness; no numerical release."""
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import os
from pathlib import Path
import py_compile
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
import release_shoreline_reference as release
import release_source_runtime as source_runtime


class ReleaseHarnessTests(unittest.TestCase):
    SOURCES=[{'name':'test_fake.py','bytes':1,'sha256':'a'*64}]
    IDS=['test_fake.Fixture.test_one']

    def patches(self,root):
        digest=hashlib.sha256(release.io.canonical(self.IDS)).hexdigest()
        return mock.patch.multiple(
            release,ROOT=root,EXPECTED_TEST_COUNT=1,
            EXPECTED_TEST_MODULES=('test_fake',),EXPECTED_TEST_FILES=('test_fake.py',),
            EXPECTED_TEST_IDS_SHA256=digest,
            REQUIRED_RUNTIME_FILES=('test_fake.py',),
            _source_runtime_check=lambda *args:self.SOURCES,
        )

    def identity(self):
        return release._identity()

    def worker(self,identity):
        digest=hashlib.sha256(release.io.canonical(self.IDS)).hexdigest()
        return {'schema':'diadem.terrain.shoreline-test-worker.r4','status':'PASS','tests_run':1,
                'test_ids':list(self.IDS),'test_ids_sha256':digest,'test_modules':['test_fake'],
                'started_test_ids':list(self.IDS),'stopped_test_ids':list(self.IDS),
                'successful_test_ids':list(self.IDS),'executed_local_sources':deepcopy(self.SOURCES),
                'discovered_test_files':['test_fake.py'],'failures':0,'errors':0,'skipped':0,
                'expected_failures':0,'unexpected_successes':0,'loader_errors':[],
                'source_snapshot_sha256':hashlib.sha256(release.io.canonical(identity['sources'])).hexdigest(),
                'sources_unchanged':True,'python':identity['python'],'platform':identity['platform'],
                'test_log_sha256':'b'*64,'elapsed_seconds':.1,'return_code':0}

    def report(self,identity):
        result={key:None for key in release.REPORT_KEYS}
        result.update(schema='diadem.terrain.shoreline-verification.r4',status='PASS',
                      scope='BOUNDED_SYNTHETIC_NUMERICAL_DRIVER_VERIFICATION_ONLY',
                      sources=identity['sources'],additional_reference_requested=False,
                      physical_acceptance=False,production_authorised=False,workflow_adoption=False,
                      fresh_optimisation_speedup_established=False,optimisation_speedup_percent=None,
                      whole_verification_wall_seconds=9.,
                      cases=[{'status':'PASS','dt_years':dt,
                              'driver_and_validation_wall_seconds':1.} for dt in release.verification.DEFAULT_DTS],
                      identical_repeat={'status':'PASS','run':{'driver_and_validation_wall_seconds':1.}},
                      json_checkpoint_restart={'status':'PASS',
                                               'first':{'driver_and_validation_wall_seconds':1.},
                                               'second':{'driver_and_validation_wall_seconds':1.}},
                      refinement={'status':'PASS'},recipient_stability={'status':'PASS'},
                      retained_r2_rejection={'status':'PASS_RETAINED_REJECTION','recipe_unchanged':True})
        return result

    def scientific(self,report):
        result=deepcopy(report);del result['whole_verification_wall_seconds']
        for row in result['cases']:del row['driver_and_validation_wall_seconds']
        del result['identical_repeat']['run']['driver_and_validation_wall_seconds']
        del result['json_checkpoint_restart']['first']['driver_and_validation_wall_seconds']
        del result['json_checkpoint_restart']['second']['driver_and_validation_wall_seconds']
        return result

    def shape_patches(self,report):
        return mock.patch.multiple(
            release,EXPECTED_TIMED_REPORT_SHAPE_SHA256=release._shape_digest(report),
            EXPECTED_SCIENTIFIC_REPORT_SHAPE_SHA256=release._shape_digest(self.scientific(report)),
        )

    def mocked_run(self,root,output,*,interrupt_at=None):
        with self.patches(root), mock.patch.object(release.verification,'source_snapshot',return_value=self.SOURCES):
            identity=self.identity();report=self.report(identity);worker=self.worker(identity)
            with self.shape_patches(report), \
                 mock.patch.object(release,'_test_worker',return_value=worker) as test_worker, \
                 mock.patch.object(release.verification,'verify_near_flat',side_effect=[deepcopy(report),deepcopy(report)]):
                result=release.run(output,interrupt_at=interrupt_at)
            return result,test_worker.call_count,identity

    def test_timing_removal_is_path_specific(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'evidence';root.mkdir()
            with self.patches(root), mock.patch.object(release.verification,'source_snapshot',return_value=self.SOURCES):
                identity=self.identity();report=self.report(identity)
                with self.shape_patches(report):
                    stripped=release._strip_timing(report,identity)
                    self.assertFalse(release._walk_key_paths(stripped,release.TIMING_KEYS))
                    report['prepared_state']={'driver_and_validation_wall_seconds':2.}
                    with self.assertRaisesRegex(ValueError,'timing field locations'):
                        release._strip_timing(report,identity)

    def test_report_authority_and_schema_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'evidence';root.mkdir()
            with self.patches(root), mock.patch.object(release.verification,'source_snapshot',return_value=self.SOURCES):
                identity=self.identity();report=self.report(identity)
                with self.shape_patches(report):
                    for key in ('physical_acceptance','production_authorised','workflow_adoption'):
                        bad=deepcopy(report);bad[key]=True
                        with self.subTest(key=key),self.assertRaises(ValueError):
                            release._validate_report(bad,identity,timed=True)
                    bad=deepcopy(report);bad['unknown_promotion']=True
                    with self.assertRaisesRegex(ValueError,'schema differs'):
                        release._validate_report(bad,identity,timed=True)
                    bad=deepcopy(report);bad['prepared_state']={'physical_acceptance':True}
                    with self.assertRaisesRegex(ValueError,'flag is not false'):
                        release._validate_report(bad,identity,timed=True)

    def test_worker_zero_skip_and_id_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'evidence';root.mkdir()
            with self.patches(root), mock.patch.object(release.verification,'source_snapshot',return_value=self.SOURCES):
                identity=self.identity();valid=self.worker(identity);release._validate_worker(valid,identity)
                mutations=(('tests_run',0),('skipped',1),('expected_failures',1),
                           ('unexpected_successes',1),('errors',1),('failures',1))
                for key,value in mutations:
                    bad=deepcopy(valid);bad[key]=value
                    with self.subTest(key=key),self.assertRaises(ValueError):release._validate_worker(bad,identity)
                bad=deepcopy(valid);bad['test_ids']=['test_fake.Fixture.test_other']
                with self.assertRaisesRegex(ValueError,'ID digest'):
                    release._validate_worker(bad,identity)

    def test_mocked_commit_is_exact_and_nonoverwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'evidence';root.mkdir();output=root/'release_01'
            result,calls,identity=self.mocked_run(root,output)
            self.assertEqual((result['status'],calls),('COMMITTED_BOUNDED_REFERENCE',2))
            self.assertEqual({p.name for p in output.iterdir()},set(release.NAMES))
            with self.patches(root), mock.patch.object(release.verification,'source_snapshot',return_value=self.SOURCES):
                report=self.report(identity)
                with self.shape_patches(report):
                    with self.assertRaises(FileExistsError):release.run(output)
                    reused=release.run(output,resume=True)
                    self.assertEqual(reused['status'],'VERIFIED_REUSE')
                    release.verify(output,identity)

    def test_interruption_preserves_seal_and_resume_commits_without_rework(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'evidence';root.mkdir();output=root/'release_02'
            with self.assertRaisesRegex(RuntimeError,'injected interruption'):
                self.mocked_run(root,output,interrupt_at='after_receipt')
            pending=list(root.glob('release_02.pending-*'))
            self.assertEqual(len(pending),1);self.assertEqual({p.name for p in pending[0].iterdir()},set(release.NAMES))
            with self.patches(root), mock.patch.object(release.verification,'source_snapshot',return_value=self.SOURCES), \
                 mock.patch.object(release,'_test_worker') as worker, \
                 mock.patch.object(release.verification,'verify_near_flat') as verifier:
                identity=self.identity();report=self.report(identity)
                with self.shape_patches(report):
                    resumed=release.run(output,resume=True)
                    self.assertEqual(resumed['status'],'COMMITTED_BOUNDED_REFERENCE')
                    worker.assert_not_called();verifier.assert_not_called()

    def test_reuse_rejects_missing_workers_and_contradictory_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'evidence';root.mkdir();output=root/'release_03'
            _,_,identity=self.mocked_run(root,output)
            receipt_path=output/'RECEIPT.json';original=release.io.read_json(receipt_path)
            for mutation in ('workers','authority'):
                receipt=deepcopy(original)
                if mutation=='workers':receipt['test_workers']=receipt['test_workers'][:1]
                else:receipt['physical_acceptance']=True
                receipt_path.unlink();receipt_path.write_bytes(release.io.canonical(receipt))
                with self.patches(root):
                    with self.shape_patches(self.report(identity)):
                        with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                            release.verify(output,identity)
            receipt_path.unlink();receipt_path.write_bytes(release.io.canonical(original))

    def test_live_target_lock_blocks_second_invocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'evidence';root.mkdir();output=root/'release_04'
            with self.patches(root), mock.patch.object(release.verification,'source_snapshot',return_value=self.SOURCES):
                identity=self.identity();descriptor,lock,lock_identity=release._acquire_lock(
                    root,output,identity['generation_id'])
                try:
                    with self.assertRaises(FileExistsError):release.run(output)
                finally:release._release_lock(root,descriptor,lock,lock_identity)
            self.assertFalse(output.exists())

    def test_stale_unlocked_lock_file_allows_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'evidence';root.mkdir();output=root/'release_05'
            (root/'release_05.release.lock').write_text('stale prior owner',encoding='ascii')
            result,calls,_=self.mocked_run(root,output)
            self.assertEqual((result['status'],calls),('COMMITTED_BOUNDED_REFERENCE',2))
            self.assertTrue((root/'release_05.release.lock').is_file())

    def test_hard_linked_lock_is_rejected_without_touching_other_inode(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);root=base/'evidence';root.mkdir();output=root/'release_06'
            victim=base/'outside.txt';original=b'must remain byte exact';victim.write_bytes(original)
            os.link(victim,root/'release_06.release.lock')
            with self.patches(root), mock.patch.object(release.verification,'source_snapshot',return_value=self.SOURCES):
                with self.assertRaisesRegex(ValueError,'hard-linked release lock'):
                    release.run(output)
            self.assertEqual(victim.read_bytes(),original)
            self.assertFalse(output.exists())

    def test_hard_linked_evidence_is_rejected_without_touching_outside_victim(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);root=base/'evidence';root.mkdir();output=root/'release_07'
            _,_,identity=self.mocked_run(root,output)
            product=output/'EVIDENCE-A.json';original=product.read_bytes();victim=base/'outside-evidence.json'
            victim.write_bytes(original);product.unlink();os.link(victim,product)
            with self.patches(root), self.shape_patches(self.report(identity)):
                with self.assertRaisesRegex(ValueError,'singly-linked regular file'):
                    release.verify(output,identity)
            self.assertEqual(victim.read_bytes(),original)

    def test_resume_rejects_hard_linked_pending_product(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);root=base/'evidence';root.mkdir();output=root/'release_08'
            with self.assertRaisesRegex(RuntimeError,'injected interruption'):
                self.mocked_run(root,output,interrupt_at='after_receipt')
            pending=next(root.glob('release_08.pending-*'));product=pending/'EVIDENCE-B.json'
            original=product.read_bytes();victim=base/'outside-pending.json';victim.write_bytes(original)
            product.unlink();os.link(victim,product)
            with self.patches(root), mock.patch.object(release.verification,'source_snapshot',return_value=self.SOURCES):
                identity=self.identity()
                with self.shape_patches(self.report(identity)):
                    with self.assertRaisesRegex(ValueError,'singly-linked regular file'):
                        release.run(output,resume=True)
            self.assertFalse(output.exists());self.assertEqual(victim.read_bytes(),original)

    def test_output_is_safe_named_direct_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'evidence';root.mkdir()
            with self.patches(root):
                with self.assertRaises(ValueError):release.run(root/'nested'/'release')
                with self.assertRaises(ValueError):release.run(root/'bad.name')
                with self.assertRaises(ValueError):release.run(root.parent/'escape')

    def test_non_windows_commit_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'evidence';root.mkdir();pending=root/'pending';pending.mkdir()
            with mock.patch.object(release.sys,'platform','linux'):
                with self.assertRaisesRegex(RuntimeError,'only for Windows'):
                    release._commit_no_clobber(root,pending,root/'release')


    def test_worker_requires_each_executed_identity_not_just_discovery_and_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.patches(Path(temporary)),mock.patch.object(release.verification,'source_snapshot',return_value=self.SOURCES):
                identity=self.identity();valid=self.worker(identity)
                for key in ('started_test_ids','stopped_test_ids','successful_test_ids'):
                    for value in ([],self.IDS*2,['test_fake.Fixture.test_substitute']):
                        bad=deepcopy(valid);bad[key]=value
                        with self.subTest(key=key,value=value),self.assertRaisesRegex(ValueError,'executed ID'):
                            release._validate_worker(bad,identity)

    def test_worker_requires_executed_test_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.patches(Path(temporary)),mock.patch.object(release.verification,'source_snapshot',return_value=self.SOURCES):
                identity=self.identity();valid=self.worker(identity)
                for value in ([],self.SOURCES*2,[{**self.SOURCES[0],'sha256':'b'*64}]):
                    bad=deepcopy(valid);bad['executed_local_sources']=value
                    with self.subTest(value=value),self.assertRaises(ValueError):release._validate_worker(bad,identity)

    def test_parent_receipt_requires_actual_numerical_source_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'evidence';root.mkdir();output=root/'source_bound'
            _,_,identity=self.mocked_run(root,output)
            receipt_path=output/'RECEIPT.json';receipt=release.io.read_json(receipt_path)
            receipt['executed_local_sources']=[]
            receipt_path.unlink();receipt_path.write_bytes(release.io.canonical(receipt))
            with self.patches(root),self.shape_patches(self.report(identity)):
                with self.assertRaisesRegex(ValueError,'executed release source'):
                    release.verify(output,identity)

    def test_worker_timeout_is_bounded_and_propagated(self):
        with mock.patch.object(release.subprocess,'run',side_effect=release.subprocess.TimeoutExpired('worker',600)) as process:
            with self.assertRaises(release.subprocess.TimeoutExpired):release._test_worker({})
        self.assertEqual(process.call_args.kwargs['timeout'],600)


class ExecutionIdentityTests(unittest.TestCase):
    def run_cases(self,suite):
        return unittest.TextTestRunner(stream=release.string_io.StringIO(),
                                       resultclass=release.TrackedResult).run(suite)

    def test_one_success_has_three_matching_execution_identities(self):
        case=unittest.FunctionTestCase(lambda:None)
        suite=unittest.TestSuite([case]);ids=release._suite_ids(suite)
        self.assertTrue(release._executed_exactly(self.run_cases(suite),ids))

    def test_same_count_substituted_test_is_not_discovery_identity(self):
        class Substitute(unittest.TestCase):
            def test_other(self):pass
        class Advertised(unittest.TestCase):
            def test_expected(self):pass
            def run(self,result=None):return Substitute('test_other').run(result)
        suite=unittest.TestSuite([Advertised('test_expected')]);ids=release._suite_ids(suite)
        tested=self.run_cases(suite)
        self.assertEqual(tested.testsRun,len(ids));self.assertTrue(tested.wasSuccessful())
        self.assertFalse(release._executed_exactly(tested,ids))

    def test_skipped_expected_failed_and_unexpected_success_are_not_complete(self):
        class Cases(unittest.TestCase):
            @unittest.skip('deliberate regression fixture')
            def test_skip(self):pass
            @unittest.expectedFailure
            def test_expected(self):self.fail('deliberate regression fixture')
            @unittest.expectedFailure
            def test_unexpected(self):pass
        for name in ('test_skip','test_expected','test_unexpected'):
            suite=unittest.TestSuite([Cases(name)]);ids=release._suite_ids(suite)
            with self.subTest(name=name):self.assertFalse(release._executed_exactly(self.run_cases(suite),ids))

    def test_missing_duplicate_or_reordered_execution_cannot_pass(self):
        first=unittest.FunctionTestCase(lambda:None,description='first')
        second=unittest.FunctionTestCase(lambda:None,description='second')
        # Explicit IDs avoid FunctionTestCase's identical lambda names.
        first.id=lambda:'fixture.first';second.id=lambda:'fixture.second'
        suite=unittest.TestSuite([first,second]);ids=release._suite_ids(suite)
        tested=self.run_cases(suite);self.assertTrue(release._executed_exactly(tested,ids))
        for attribute in ('started_ids','stopped_ids','success_ids'):
            for value in (ids[:1],[ids[0],ids[0]],list(reversed(ids))):
                with self.subTest(attribute=attribute,value=value),mock.patch.object(tested,attribute,value):
                    self.assertFalse(release._executed_exactly(tested,ids))


class ExactSourceRuntimeTests(unittest.TestCase):
    NAME='_r5_release_probe_module'

    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='r5-release-source-')
        self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.path=self.root/(self.NAME+'.py');self.path.write_bytes(b'value = 1\n')
        self.addCleanup(sys.modules.pop,self.NAME,None)

    def runtime(self):
        runtime=source_runtime.SourceRuntime(self.root)
        runtime.install();self.addCleanup(runtime.uninstall)
        return runtime

    def test_preloaded_same_path_module_rejects_before_execution(self):
        foreign=types.ModuleType(self.NAME);foreign.__file__=str(self.path)
        runtime=source_runtime.SourceRuntime(self.root)
        with mock.patch.dict(sys.modules,{self.NAME:foreign}):
            with self.assertRaisesRegex(ValueError,'fresh process'):runtime.install()

    def test_timestamp_valid_stale_bytecode_is_never_executed(self):
        original=self.path.stat();py_compile.compile(str(self.path),doraise=True)
        self.path.write_bytes(b'value = 2\n')
        os.utime(self.path,ns=(original.st_atime_ns,original.st_mtime_ns))
        spec=importlib.util.spec_from_file_location(self.NAME,self.path)
        stale=importlib.util.module_from_spec(spec);spec.loader.exec_module(stale)
        self.assertEqual(stale.value,1)  # Ordinary Python accepts this stale pyc.
        runtime=self.runtime();actual=importlib.import_module(self.NAME)
        self.assertEqual(actual.value,2)
        self.assertEqual(runtime.check(),[source_runtime.source_pin(self.path.name,b'value = 2\n')])

    def test_compilation_explicitly_preserves_assertions_and_disables_inheritance(self):
        self.path.write_bytes(b'assert False, "assertions must execute"\n')
        self.runtime()
        with mock.patch.object(source_runtime,'compile',wraps=compile,create=True) as compiler:
            with self.assertRaisesRegex(AssertionError,'assertions must execute'):
                importlib.import_module(self.NAME)
        self.assertEqual(compiler.call_args.kwargs,{'dont_inherit':True,'optimize':0})

    def test_change_between_capture_and_validation_is_rejected(self):
        with mock.patch.object(source_runtime,'read_source',side_effect=[b'value = 1\n',b'value = 9\n']):
            with self.assertRaisesRegex(ValueError,'after capture'):source_runtime.SourceRuntime(self.root)

    def test_source_change_before_compilation_rejects_without_running_it(self):
        runtime=self.runtime();self.path.write_bytes(b'raise AssertionError("must not execute")\n')
        with self.assertRaisesRegex(ValueError,'before compilation'):importlib.import_module(self.NAME)
        self.assertFalse(runtime.loaded)

    def test_source_change_during_execution_cannot_be_receipted(self):
        self.path.write_bytes(b'from pathlib import Path\nPath(__file__).write_bytes(b"value = 9\\n")\nvalue = 1\n')
        runtime=self.runtime()
        with self.assertRaisesRegex(ValueError,'during execution'):importlib.import_module(self.NAME)
        self.assertFalse(runtime.loaded)

    def test_loaded_module_replacement_rejects_even_at_the_same_path(self):
        runtime=self.runtime();importlib.import_module(self.NAME)
        foreign=types.ModuleType(self.NAME);foreign.__file__=str(self.path)
        with mock.patch.dict(sys.modules,{self.NAME:foreign}):
            with self.assertRaisesRegex(ValueError,'identity was replaced'):runtime.check()

    def test_added_source_inventory_rejects(self):
        runtime=self.runtime();(self.root/'new_module.py').write_bytes(b'value = 0\n')
        with self.assertRaisesRegex(ValueError,'inventory changed'):runtime.check()

    def test_mixed_case_inventory_uses_the_verifiers_path_order(self):
        (self.root/'Z_METADATA.md').write_bytes(b'working')
        (self.root/'a_metadata.json').write_bytes(b'{}')
        runtime=self.runtime()
        self.assertEqual([row['name'] for row in runtime.pins],
                         [path.name for path in sorted(self.root.iterdir())])
        self.assertEqual(runtime.check(),[])

    def test_changed_helper_bootstrap_bytes_reject(self):
        (self.root/'release_source_runtime.py').write_bytes(b'value = 1\n')
        with mock.patch.object(source_runtime,'EXECUTED_SOURCE_BYTES',b'value = 9\n',create=True):
            with self.assertRaisesRegex(ValueError,'bootstrap helper bytes'):source_runtime.launch(self.root)

    def test_unbound_release_fails_before_creating_output(self):
        output=self.root/'not-created'
        with mock.patch.dict(sys.modules,{'_r5_release_source_runtime':None}):
            with self.assertRaisesRegex(ValueError,'exact-source CLI bootstrap'):release.run(output)
        self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
