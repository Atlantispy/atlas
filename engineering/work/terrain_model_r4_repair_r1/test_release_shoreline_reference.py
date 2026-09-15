"""Focused, mocked tests for the sealed R4 release harness; no numerical release."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
import release_shoreline_reference as release


class ReleaseHarnessTests(unittest.TestCase):
    SOURCES=[{'name':'synthetic-source.py','bytes':1,'sha256':'a'*64}]
    IDS=['test_fake.Fixture.test_one']

    def patches(self,root):
        digest=hashlib.sha256(release.io.canonical(self.IDS)).hexdigest()
        return mock.patch.multiple(
            release,ROOT=root,EXPECTED_TEST_COUNT=1,
            EXPECTED_TEST_MODULES=('test_fake',),EXPECTED_TEST_FILES=('test_fake.py',),
            EXPECTED_TEST_IDS_SHA256=digest,
        )

    def identity(self):
        return release._identity()

    def worker(self,identity):
        digest=hashlib.sha256(release.io.canonical(self.IDS)).hexdigest()
        return {'schema':'diadem.terrain.shoreline-test-worker.r4','status':'PASS','tests_run':1,
                'test_ids':list(self.IDS),'test_ids_sha256':digest,'test_modules':['test_fake'],
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


if __name__=='__main__':unittest.main()
