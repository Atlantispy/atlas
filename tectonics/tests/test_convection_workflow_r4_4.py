"""R4.4 driver, receipt audit and actual coupled recovery checks.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
from concurrent.futures import CancelledError
from dataclasses import replace
import copy
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import numpy as np
import atlas_tectonics as atlas
from atlas_tectonics.resources import WorkBudget

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import run_convection_r4_4 as runner
import analyse_convection_r4_4 as audit
import assess_convection_suite_r4_4 as campaign

ENV={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}


def execute(root, output, *args):
    return subprocess.run([sys.executable,'-I','-B',str(root/'tools/run_convection_r4_4.py'),
        '--output',str(output),*map(str,args)],env=ENV,capture_output=True,text=True,timeout=120)


def new_run(root, output, segment=4):
    return execute(root,output,'--cells',4,'--dt',1e-5,'--max-steps',4,
        '--sample-every',1,'--save-every',2,'--segment-steps',segment)


def clone_runtime(destination):
    destination.mkdir()
    for folder in ('src','tools','cases'):
        shutil.copytree(ROOT/folder,destination/folder)
    return destination


class DriverRecoveryTests(unittest.TestCase):
    """Each subprocess has its own loaded native/source identity and store."""
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='atlas-r4-4-driver-')
        cls.base=Path(cls.temp.name)
        cls.reference=cls.base/'reference'
        result=new_run(ROOT,cls.reference)
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        cls.reference_id=json.loads(sorted(cls.reference.glob('receipt_*.json'))[-1].read_bytes())['state_id']
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def destination(self):return self.base/self.id().split('.')[-1]
    def test_fresh_process_resume_matches_uninterrupted(self):
        out=self.destination()
        first=new_run(ROOT,out,2);self.assertEqual(first.returncode,0,first.stdout+first.stderr)
        second=execute(ROOT,out,'--resume','--segment-steps',2)
        self.assertEqual(second.returncode,0,second.stdout+second.stderr)
        final=json.loads(sorted(out.glob('receipt_*.json'))[-1].read_bytes())
        self.assertEqual(final['state_id'],self.reference_id)
        self.assertEqual(json.loads(second.stdout.splitlines()[-1])['budget_after_close']['reserved_bytes'],0)
    def test_new_runs_record_optimised_r4_4_fill_policy(self):
        config=json.loads((self.reference/'run.json').read_bytes())
        self.assertEqual(config['nonlinear_policy']['ilu_fill_factor'],17.0)
        self.assertEqual(atlas.NonlinearStokesPolicy().ilu_fill_factor,12.0)
    def test_128_default_budget_uses_single_owned_mechanics_plan(self):
        out=self.destination()
        result=execute(ROOT,out,'--cells',128,'--dt',1e-6,'--max-steps',1,
            '--sample-every',1,'--save-every',1,'--segment-steps',1,'--budget-mib',1024)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        record=json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(record['status'],'FINITE_SCHEDULE_COMPLETE')
        self.assertEqual(record['budget_after_close']['reserved_bytes'],0)
        self.assertLessEqual(record['budget_after_close']['peak_reserved_bytes'],1024<<20)
    def test_relocated_source_store_reopen_matches_uninterrupted(self):
        out=self.destination();first=new_run(ROOT,out,2)
        self.assertEqual(first.returncode,0,first.stdout+first.stderr)
        alternate=clone_runtime(self.base/'relocated-source')
        moved=self.base/'relocated-store';shutil.copytree(out,moved)
        second=execute(alternate,moved,'--resume','--segment-steps',2)
        self.assertEqual(second.returncode,0,second.stdout+second.stderr)
        self.assertEqual(json.loads(second.stdout.splitlines()[-1])['last_state_id'],self.reference_id)
    def test_changed_source_refused_without_rebinding(self):
        out=self.destination();shutil.copytree(self.reference,out)
        alternate=clone_runtime(self.base/'changed-source')
        with (alternate/'src/atlas_tectonics/convection_benchmark.py').open('a') as f:f.write('\n# Deliberately changed exact source bytes.\n')
        result=execute(alternate,out,'--resume','--segment-steps',1)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('changed source/runner/specification',result.stderr)
        self.assertFalse((out/'RUNNING.lock').exists())
    def test_changed_case_specification_refused(self):
        out=self.destination();shutil.copytree(self.reference,out)
        alternate=clone_runtime(self.base/'changed-specification')
        with (alternate/'cases/convection_r4_4.json').open('a') as f:f.write('\n')
        result=execute(alternate,out,'--resume','--segment-steps',1)
        self.assertNotEqual(result.returncode,0);self.assertIn('changed source/runner/specification',result.stderr)
    def test_changed_frozen_timestep_refused(self):
        out=self.destination();shutil.copytree(self.reference,out)
        path=out/'run.json';obj=json.loads(path.read_bytes());obj['dt']/=2;path.write_bytes(runner.encode(obj))
        result=execute(ROOT,out,'--resume','--segment-steps',1)
        self.assertNotEqual(result.returncode,0);self.assertIn('receipt/configuration chain changed',result.stdout)
    def test_resume_rejects_resupplied_policy(self):
        result=execute(ROOT,self.reference,'--resume','--dt',1e-5)
        self.assertEqual(result.returncode,2);self.assertIn('do not resupply',result.stderr)
    def test_existing_output_not_overwritten(self):
        before={p.name:p.read_bytes() for p in self.reference.glob('receipt_*.json')}
        result=new_run(ROOT,self.reference)
        self.assertEqual(result.returncode,2)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.reference.glob('receipt_*.json')})
    def test_foreign_lock_never_removed(self):
        out=self.destination();shutil.copytree(self.reference,out)
        lock=out/'RUNNING.lock';lock.write_text('foreign lock')
        result=execute(ROOT,out,'--resume','--segment-steps',1)
        self.assertEqual(result.returncode,2);self.assertEqual(lock.read_text(),'foreign lock')
    def test_closed_actual_trajectory_audit(self):
        config,records,samples,steps,states,head=audit.read_run(self.reference)
        self.assertEqual(len(steps),4);self.assertEqual(samples[-1]['state_id'],self.reference_id)
        result=audit.analyse_run(self.reference)
        self.assertFalse(result['mature_regime_gate']);self.assertFalse(result['full_benchmark_accepted'])
        self.assertTrue(result['every_accepted_step']['conservation_passed'])
    def test_closed_run_cli_serialises_full_diagnostic_record(self):
        output=self.base/'full_audit.json'
        result=subprocess.run([sys.executable,'-I','-B',str(ROOT/'tools/analyse_convection_r4_4.py'),
            '--run',str(self.reference),'--output',str(output)],env=ENV,capture_output=True,text=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        record=json.loads(output.read_bytes())['runs'][0]
        self.assertIs(type(record['latest_sample_is_saved_endpoint']),bool)
        self.assertFalse(record['full_benchmark_accepted'])
    def test_live_trajectory_audit_refused(self):
        out=self.destination();shutil.copytree(self.reference,out);(out/'RUNNING.lock').write_text('live')
        with self.assertRaisesRegex(ValueError,'closed run'):audit.read_run(out)
    def test_deleted_receipt_breaks_chain(self):
        out=self.destination();shutil.copytree(self.reference,out)
        (out/'receipt_000000002.json').unlink()
        with self.assertRaisesRegex(ValueError,'chain changed'):audit.read_run(out)
    def test_corrupt_saved_state_refused(self):
        # Corrupt a referenced record ID, not a different unreferenced blob.
        out=self.destination();shutil.copytree(self.reference,out)
        path=out/'receipt_000000004.json';obj=json.loads(path.read_bytes());obj['state_id']='f'*64
        path.write_bytes(runner.encode(obj))
        with self.assertRaises((ValueError,KeyError,atlas.TectonicsError)):audit.read_run(out)
    def test_receipt_sample_state_mismatch_refused(self):
        out=self.destination();shutil.copytree(self.reference,out)
        path=out/'receipt_000000004.json';obj=json.loads(path.read_bytes());obj['samples'][-1]['state_id']='f'*64
        path.write_bytes(runner.encode(obj))
        with self.assertRaisesRegex(ValueError,'sample/accepted'):audit.read_run(out)
    def test_cooperative_bound_saves_then_resumes(self):
        out=self.destination()
        result=execute(ROOT,out,'--cells',4,'--dt',1e-5,'--max-steps',4,'--save-every',2,
            '--sample-every',1,'--segment-steps',4,'--seconds',.000001)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        record=json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(record['status'],'CANCELLED_ACCEPTED_STATE_SAVED')
        self.assertEqual(record['last_saved_step'],0)
        resumed=execute(ROOT,out,'--resume','--segment-steps',4)
        self.assertEqual(resumed.returncode,0,resumed.stdout+resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout.splitlines()[-1])['last_state_id'],self.reference_id)


class StageCancellation:
    """Explicit diagnostic fault injection through the supported cancel protocol."""
    def __init__(self):self.hit=False
    def is_set(self):
        frame=inspect.currentframe()
        try:
            while frame is not None:
                if frame.f_code.co_name=='_flow' and frame.f_locals.get('stage')=='advection RK stage 1 before final diffusion half':
                    self.hit=True;return True
                frame=frame.f_back
        finally:del frame
        return False


class CombinedCoupledRecoveryTests(unittest.TestCase):
    def test_second_rk_stage_cancellation_is_atomic_and_recoverable(self):
        budget=WorkBudget(128<<20);problem=atlas.TosiCase('tosi-2').problem(4)
        state=atlas.ThermochemicalState(problem,atlas.tosi_initial_temperature(4),np.zeros((4,4)),
            time_s=0,source='R4.4 controlled cancellation',budget=budget)
        initial=state.state_id;cancel=StageCancellation()
        with atlas.PreparedThermochemical2D(problem,budget=budget) as prepared:
            with self.assertRaises(CancelledError):prepared.advance(state,1e-5,source='same step',cancel=cancel)
            self.assertTrue(cancel.hit);self.assertEqual(state.state_id,initial);self.assertEqual(state.step_index,0)
            resumed=prepared.advance(state,1e-5,source='same step').state
        with atlas.PreparedThermochemical2D(problem,budget=budget) as prepared:
            clean=prepared.advance(state,1e-5,source='same step').state
        self.assertEqual(resumed.state_id,clean.state_id)
        np.testing.assert_array_equal(resumed.array('temperature_k'),clean.array('temperature_k'))
        self.assertEqual(budget.statistics()['reserved_bytes'],0)


class AnalysisPolicyTests(unittest.TestCase):
    def setUp(self):self.spec=json.loads((ROOT/'cases/convection_r4_4.json').read_bytes())
    def test_published_envelope_comparator(self):
        ref=self.spec['reported_values']['tosi-1']
        d={k:np.mean(list(v.values())) for k,v in ref.items()}
        result=audit.compare_table('tosi-1',d,self.spec)
        self.assertTrue(result['all_available_metrics_within_envelope'])
        d['Nu_top']*=2;self.assertFalse(audit.compare_table('tosi-1',d,self.spec)['all_available_metrics_within_envelope'])
    def test_missing_and_unresolved_not_pass(self):
        self.assertFalse(audit.compare_table('tosi-1',{},self.spec)['all_available_metrics_within_envelope'])
        self.assertEqual(audit.compare_table('tosi-5b',{},self.spec)['status'],'UNRESOLVED')
        self.assertEqual(audit.compare_table('tosi-5a',{},self.spec)['comparisons']['printed_Phi_min']['status'],'UNRESOLVED')
    def test_nonfinite_table_value_refused(self):
        with self.assertRaises(ValueError):audit.compare_table('tosi-1',{'temperature_mean':float('nan')},self.spec)
    def test_cycle_both_minima_and_maxima(self):
        t=np.linspace(0,12,12001);v=3+2*np.cos(2*np.pi*(t-.25))
        r=audit.cycle_extrema(t,v)
        self.assertTrue(r['resolved']);self.assertEqual(r['complete_cycles'],10)
        self.assertAlmostEqual(r['mean_cycle_minimum'],1,places=13);self.assertAlmostEqual(r['mean_cycle_maximum'],5,places=13)
    def test_insufficient_cycles_not_resolved(self):
        t=np.linspace(0,5,5001);r=audit.cycle_extrema(t,np.cos(2*np.pi*t))
        self.assertFalse(r['resolved'])
    def test_nonpositive_cycle_count_refused(self):
        for cycles in (0,-1,True,2.5):
            with self.subTest(cycles=cycles),self.assertRaises(ValueError):audit.cycle_extrema([0,1,2],[1,0,1],cycles)
    def phase(self,drift=0):
        t=np.linspace(0,11,2201)
        return [(x,np.array([[.5+.1*np.sin(2*np.pi*x)+drift*x]])) for x in t]
    def test_phase_field_exact_periodic_passes(self):
        r=audit.phase_field_gate(self.phase(),np.arange(11))
        self.assertTrue(r['passed']);self.assertLess(r['temperature_linf'],1e-14)
    def test_phase_field_drift_rejected(self):
        self.assertFalse(audit.phase_field_gate(self.phase(.01),np.arange(11))['passed'])
    def test_sparse_checkpoint_phase_alias_rejected(self):
        self.assertFalse(audit.phase_field_gate(self.phase()[::100],np.arange(11))['passed'])
    def test_insufficient_saved_field_coverage_rejected(self):
        self.assertFalse(audit.phase_field_gate(self.phase()[100:],np.arange(11))['passed'])
    def reports(self):
        c=dict(schema='test',case={'name':'tosi-1','yield_stress':None},cells=32,dt=1e-5,maximum_steps=20000,
            save_every=10,sample_every=1,thermal_policy={'max_steps':20000},
            nonlinear_policy={'momentum_tolerance':1e-9,'linear_rtol':1e-12,'viscosity_rtol':1e-8})
        result=[]
        for n,x in zip((32,64,128),(1.001,1.0002,1.00004)):
            cfg=copy.deepcopy(c);cfg['cells']=n
            result.append(dict(case=c['case'],source={'source':'same'},configuration=cfg,mature_regime_gate=True,
                latest_diagnostics={k:x for k in audit._METRICS}))
        return result
    def test_declared_mesh_differences(self):
        r=audit.study(self.reports(),'mesh');self.assertEqual(r['status'],'ADEQUACY_GATE_PASSED');self.assertFalse(r['full_benchmark_accepted'])
    def test_small_exploratory_grids_never_predeclared_pass(self):
        rr=self.reports()
        for r,n in zip(rr,(8,16,32)):r['configuration']['cells']=n
        self.assertEqual(audit.study(rr,'mesh')['status'],'EXPLORATORY_NOT_PREDECLARED_ADEQUACY_GRID')
    def test_transient_study_does_not_pass(self):
        rr=self.reports();rr[1]['mature_regime_gate']=False
        self.assertEqual(audit.study(rr,'mesh')['status'],'NOT_A_MATURE_REGIME_ADEQUACY_STUDY')
    def test_mixed_case_source_and_controls_refused(self):
        for field in ('source','case','dt'):
            rr=self.reports()
            if field=='dt':rr[1]['configuration']['dt']/=2
            else:rr[1][field]={'different':True}
            with self.subTest(field=field),self.assertRaises(ValueError):audit.study(rr,'mesh')
    def test_nonmonotone_refinement_not_pass(self):
        rr=self.reports()
        rr[1]['latest_diagnostics']['Nu_top']=.9999
        self.assertEqual(audit.study(rr,'mesh')['status'],'ADEQUACY_GATE_FAILED')
    def test_three_timestep_ratios(self):
        rr=self.reports()
        for r,ratio in zip(rr,(1,.5,.25)):
            r['configuration']['cells']=128;r['configuration']['dt']*=ratio
        self.assertEqual(audit.study(rr,'timestep')['status'],'ADEQUACY_GATE_PASSED')
    def test_incomplete_nonlinear_tightening_refused(self):
        rr=self.reports()
        for r,ratio in zip(rr,(1,.1,.01)):
            r['configuration']['cells']=128;r['configuration']['nonlinear_policy']['momentum_tolerance']*=ratio
        with self.assertRaisesRegex(ValueError,'incomplete declared nonlinear'):audit.study(rr,'nonlinear')
    def test_three_nonlinear_tightening_ratios(self):
        rr=self.reports()
        for r,ratio in zip(rr,(1,.1,.01)):
            r['configuration']['cells']=128
            for key in ('momentum_tolerance','linear_rtol','viscosity_rtol'):r['configuration']['nonlinear_policy'][key]*=ratio
        self.assertEqual(audit.study(rr,'nonlinear')['status'],'ADEQUACY_GATE_PASSED')


class SuiteAcceptanceTests(unittest.TestCase):
    def test_all_twenty_six_applicable_configurations_present(self):
        cases=campaign.expected_cases()
        self.assertEqual(len(cases),26)
        self.assertEqual(len({campaign.case_key(c) for c in cases}),26)
    def test_empty_campaign_keeps_every_missing_case_open(self):
        result=campaign.assess(ROOT/'cases/convection_r4_4_campaign.example.json')
        self.assertEqual(result['passed_cases'],0)
        self.assertEqual(result['status'],'INCOMPLETE_R4_4')
        self.assertFalse(result['full_benchmark_accepted'])
        self.assertEqual(len(result['unresolved_reference_requirements']),2)
    def test_absent_visual_inspection_never_passes(self):
        self.assertFalse(campaign.visual_gate(None,ROOT,{'name':'tosi-1','yield_stress':None},[])['passed'])
    def test_absent_verification_never_passes(self):
        self.assertFalse(campaign.verification_gate(None)['passed'])
    def test_fake_or_stale_regression_record_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'record.json'
            path.write_text(json.dumps({'tests_run':9999,'failures':0,'errors':0,'skips':0,
                'status':'PASS_MATHEMATICAL_TESTS_ONLY','source_unchanged_during_tests':True,
                'resource_acceptance':{'status':'PASS_BOUNDED_CURRENT_PLATFORM'}}))
            self.assertFalse(campaign.verification_gate(path)['passed'])
    def test_duplicate_campaign_case_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'campaign.json';case={'case':{'name':'tosi-1','yield_stress':None}}
            path.write_text(json.dumps({'schema':'atlas.convection-campaign-r4-4.v1','cases':[case,case]}))
            with self.assertRaisesRegex(ValueError,'duplicate'):campaign.assess(path)


if __name__=='__main__':unittest.main()
