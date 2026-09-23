"""R4.4 driver, receipt audit and actual coupled recovery checks.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
from concurrent.futures import CancelledError
from dataclasses import replace
import copy
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np
import atlas_tectonics as atlas
from atlas_tectonics.resources import WorkBudget

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import run_convection_r4_4 as runner
import analyse_convection_r4_4 as audit
import assess_convection_suite_r4_4 as campaign
import visual_convection_r4_4 as visual

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
    def test_raw_visual_export_without_plot_library_is_not_visual_acceptance(self):
        output=self.destination()
        result=subprocess.run([sys.executable,'-I','-B',str(ROOT/'tools/visual_convection_r4_4.py'),
            '--run',str(self.reference),'--output',str(output),'--raw-only'],
            env=ENV,capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        metadata_path=output/'metadata.json';metadata=json.loads(metadata_path.read_bytes())
        self.assertEqual(metadata['output_kind'],'RAW_DATA_ONLY')
        self.assertEqual(metadata['state_id'],self.reference_id)
        self.assertEqual(metadata['budget_after_close']['reserved_bytes'],0)
        self.assertEqual(set(metadata['files']),{'raw_fields_and_history.npz'})
        with np.load(output/'raw_fields_and_history.npz',allow_pickle=False) as data:
            self.assertEqual(data['temperature'].shape,(4,4))
            self.assertEqual(data['u_m_s'].shape,(4,5))
            self.assertEqual(data['w_m_s'].shape,(5,4))
            self.assertAlmostEqual(data['sample_times'][-1],metadata['time'])
            self.assertAlmostEqual(data['temperature'].mean(),metadata['diagnostic']['diagnostics']['temperature_mean'])
        # Even an otherwise correctly bound claimed inspection cannot promote raw data.
        inspection=output/'inspection.json'
        inspection.write_bytes(runner.encode(dict(metadata='metadata.json',metadata_sha256=runner.digest(metadata_path.read_bytes()),
            state_id=metadata['state_id'],flow_id=metadata['flow_id'],passed=True)))
        gate=campaign.visual_gate(inspection,output,metadata['configuration']['case'],
            [{'latest_diagnostics_state_id':metadata['state_id']}])
        self.assertFalse(gate['passed']);self.assertIn('raw-only export is not visual evidence',gate['errors'])
    @unittest.skipUnless(importlib.util.find_spec('matplotlib'), 'optional visual dependencies not installed')
    def test_graphical_export_matches_raw_arrays_and_remains_unaccepted(self):
        output=self.destination();raw=output.with_name(output.name+'-raw')
        for destination,options in ((output,()),(raw,('--raw-only',))):
            result=subprocess.run([sys.executable,'-I','-B',str(ROOT/'tools/visual_convection_r4_4.py'),
                '--run',str(self.reference),'--output',str(destination),*options],
                env=ENV,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        metadata=json.loads((output/'metadata.json').read_bytes())
        self.assertEqual(metadata['output_kind'],'RAW_DATA_AND_PLOTS')
        self.assertEqual(metadata['state_id'],self.reference_id)
        self.assertEqual(metadata['assistant_visual_inspection'],'NOT_RECORDED_BY_RENDERER')
        self.assertFalse(metadata['full_benchmark_accepted'])
        self.assertEqual(metadata['budget_after_close']['reserved_bytes'],0)
        images={'01_temperature.png','02_viscosity.png','03_pressure.png','04_velocity.png',
            '05_heat_flux_history.png','06_temperature_history.png'}
        self.assertEqual(set(metadata['files']),images|{'raw_fields_and_history.npz'})
        from PIL import Image
        for name,expected_hash in metadata['files'].items():
            path=output/name
            self.assertEqual(runner.digest(path.read_bytes()),expected_hash)
            if name in images:
                with Image.open(path) as image:
                    self.assertEqual(image.format,'PNG');image.load()
                    self.assertGreater(min(image.size),100)
                    self.assertTrue(any(lo!=hi for lo,hi in image.convert('RGB').getextrema()))
        with np.load(output/'raw_fields_and_history.npz',allow_pickle=False) as plotted, \
                np.load(raw/'raw_fields_and_history.npz',allow_pickle=False) as unplotted:
            self.assertEqual(set(plotted.files),set(unplotted.files))
            for name in plotted.files:np.testing.assert_array_equal(plotted[name],unplotted[name])
        gate=campaign.visual_gate(None,output,metadata['configuration']['case'],
            [{'latest_diagnostics_state_id':metadata['state_id']}])
        self.assertFalse(gate['passed'])
    def test_case5b_short_trajectory_audit_does_not_claim_acceptance(self):
        out=self.destination()
        result=execute(ROOT,out,'--case','tosi-5b','--yield-stress',4.,'--cells',4,'--dt',1e-5,
            '--max-steps',4,'--sample-every',1,'--save-every',2,'--segment-steps',4)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        report=audit.analyse_run(out)
        self.assertFalse(report['mature_regime_gate']);self.assertFalse(report['full_benchmark_accepted'])
        comparison=report['table_comparison']
        self.assertEqual(comparison['status'],'UNRESOLVED')
        self.assertEqual(len(comparison['published_regime_groups']['periodic']),9)
        self.assertEqual(comparison['run_cells'],4)
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


class VisualExportTests(unittest.TestCase):
    def test_missing_plot_library_fails_before_reading_run_or_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'output'
            with mock.patch.dict(sys.modules,{'matplotlib':None}),mock.patch.object(audit,'read_run') as read:
                with self.assertRaisesRegex(ValueError,'--raw-only'):visual.render(Path(tmp)/'unused',output)
                read.assert_not_called()
            self.assertFalse(output.exists())
    def test_existing_six_plot_calls_are_preserved_without_changing_arrays(self):
        arrays={k:np.ones((4,4)) for k in ('temperature','viscosity_cell_pa_s','pressure_pa')}
        arrays.update(u_m_s=np.ones((4,5)),w_m_s=np.ones((5,4)),sample_times=np.array([0.,1.]))
        arrays.update({f'history_{k}':np.array([1.,2.]) for k in ('Nu_top','Nu_bottom','temperature_mean')})
        before={k:v.copy() for k,v in arrays.items()};plt=mock.MagicMock();figures=[]
        def subplots(**kwargs):
            fig,ax=mock.MagicMock(),mock.MagicMock();figures.append((fig,ax));return fig,ax
        plt.subplots.side_effect=subplots
        visual._plots(plt,arrays,{'case':{'name':'tosi-1','yield_stress':None},'cells':4},1.,
            {'diagnostics':{'velocity_rms':1.}},Path('unused'))
        self.assertEqual([fig.savefig.call_args.args[0].name for fig,ax in figures],
            ['01_temperature.png','02_viscosity.png','03_pressure.png','04_velocity.png',
             '05_heat_flux_history.png','06_temperature_history.png'])
        self.assertEqual(plt.close.call_count,6)
        for k in arrays:np.testing.assert_array_equal(arrays[k],before[k])


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
        self.assertEqual(audit.compare_table('tosi-5a',{},self.spec)['comparisons']['printed_Phi_min']['status'],'MISSING')
    def test_case5a_explicit_mapping_and_extrema_wiring(self):
        ref=self.spec['reported_values']['tosi-5a']
        periodic={}
        for key in ('temperature_mean','Nu_top','velocity_rms','dissipation_over_Ra'):
            source='printed_Phi' if key=='dissipation_over_Ra' else key
            periodic[key]=dict(periodic_samples=True,
                minimum=float(np.mean(list(ref[source+'_min'].values()))),
                maximum=float(np.mean(list(ref[source+'_max'].values()))))
        periodic['Nu_top']['period']=float(np.mean(list(ref['period'].values())))
        periodic['dissipation']=dict(periodic_samples=True,
            minimum=100*periodic['dissipation_over_Ra']['minimum'],
            maximum=100*periodic['dissipation_over_Ra']['maximum'])
        d=audit.case5a_periodic_metrics(periodic)
        r=audit.compare_table('tosi-5a',d,self.spec)
        self.assertTrue(r['all_available_metrics_within_envelope'])
        row=r['comparisons']['printed_Phi_min']
        self.assertEqual(row['diagnostic'],'dissipation_over_Ra_min')
        self.assertFalse(row['author_confirmed'])
        self.assertAlmostEqual(d['dissipation_min'],100*d['dissipation_over_Ra_min'])
        # Neither raw-Phi substitution nor dividing an already-scaled channel again passes.
        for factor in (100,.01):
            bad=dict(d);bad['dissipation_over_Ra_min']*=factor
            self.assertFalse(audit.compare_table('tosi-5a',bad,self.spec)['all_available_metrics_within_envelope'])
        periodic['dissipation_over_Ra']['periodic_samples']=False
        self.assertNotIn('dissipation_over_Ra_min',audit.case5a_periodic_metrics(periodic))
        # A raw-only result must not silently stand in for a missing scaled result.
        del d['dissipation_over_Ra_min']
        self.assertEqual(audit.compare_table('tosi-5a',d,self.spec)['comparisons']['printed_Phi_min']['status'],'MISSING')
    def test_changed_or_missing_mapping_never_silently_passes(self):
        for field,value in (('status','AUTHOR_CONFIRMED'),('author_confirmed',True),('rayleigh',1),
                            ('diagnostics',{'printed_Phi_min':'dissipation_min'})):
            spec=copy.deepcopy(self.spec);spec['reference_policy']['case5a_dissipation'][field]=value
            with self.subTest(field=field):
                self.assertFalse(audit.case5a_mapping_verified(spec))
                self.assertEqual(audit.compare_table('tosi-5a',{},spec)['comparisons']['printed_Phi_min']['status'],'UNRESOLVED')
        del self.spec['reference_policy']['case5a_dissipation']
        self.assertFalse(audit.case5a_mapping_verified(self.spec))
    def test_case_specific_contributor_policy_does_not_invent_numerical_rows(self):
        self.assertEqual(len(audit.reference_contributors('tosi-1',self.spec)),10)
        codes=audit.reference_contributors('tosi-5b',self.spec)
        self.assertEqual(len(codes),9);self.assertNotIn('ELEFANT',codes);self.assertNotIn('MC3D',codes)
        self.assertIsInstance(self.spec['cases']['case5b_numerical_targets'],dict)
        # Even populated flat rows cannot erase missing yield/grid/regime evidence.
        self.spec['reported_values']['tosi-5b']={'Nu_top':dict.fromkeys(codes,3.)}
        self.assertEqual(audit.compare_table('tosi-5b',{'Nu_top':3.},self.spec)['status'],'UNRESOLVED')
        for replacement in ('MC3D','ELEFANT','YACC'):
            spec=copy.deepcopy(self.spec);spec['reference_policy']['case5b_codes'][-1]=replacement
            with self.subTest(replacement=replacement),self.assertRaises(ValueError):
                audit.reference_contributors('tosi-5b',spec)
    def test_removed_diagnostic_cannot_shrink_acceptance_requirements(self):
        del self.spec['reported_values']['tosi-5a']['printed_Phi_min']
        self.assertEqual(audit.compare_table('tosi-5a',{},self.spec)['status'],'UNRESOLVED')
    def test_nonfinite_table_value_refused(self):
        with self.assertRaises(ValueError):audit.compare_table('tosi-1',{'temperature_mean':float('nan')},self.spec)
    def test_nine_contributors_do_not_satisfy_ten_code_policy(self):
        del self.spec['reported_values']['tosi-1']['temperature_mean']['ELEFANT']
        d={k:np.mean(list(v.values())) for k,v in self.spec['reported_values']['tosi-1'].items()}
        r=audit.compare_table('tosi-1',d,self.spec)
        self.assertFalse(r['all_available_metrics_within_envelope'])
        self.assertEqual(r['comparisons']['temperature_mean']['missing_codes'],['ELEFANT'])
        self.spec['included_codes'].remove('ELEFANT')
        self.assertEqual(audit.compare_table('tosi-1',d,self.spec)['status'],'UNRESOLVED')
    def test_different_equation_contributor_cannot_replace_missing_code(self):
        row=self.spec['reported_values']['tosi-1']['temperature_mean']
        row['MC3D']=row.pop('ELEFANT')
        r=audit.compare_table('tosi-1',{'temperature_mean':.776},self.spec)
        self.assertEqual(r['comparisons']['temperature_mean']['status'],'UNRESOLVED')
        self.assertEqual(r['comparisons']['temperature_mean']['unexpected_codes'],['MC3D'])
    def test_empty_or_nonfinite_reference_cannot_pass(self):
        self.spec['reported_values']['empty']={}
        self.assertFalse(audit.compare_table('empty',{},self.spec)['all_available_metrics_within_envelope'])
        self.spec['reported_values']['tosi-1']['temperature_mean']['YACC']=float('nan')
        with self.assertRaises(ValueError):audit.compare_table('tosi-1',{'temperature_mean':.776},self.spec)
    def test_drifting_cycle_extrema_are_averaged_not_global_extrema(self):
        values=[0.,20.]
        for i in range(1,11):values.extend([float(i),20.+i])
        values.append(0.)
        r=audit.cycle_extrema(np.arange(len(values)),values)
        self.assertEqual(r['mean_cycle_minimum'],5.5)
        self.assertEqual(r['mean_cycle_maximum'],25.5)
        self.assertEqual((r['minimum'],r['maximum']),(1.,30.))
        self.assertFalse(audit.cycle_extrema(np.arange(len(values)-2),values[:-2])['resolved'])
        # Extraction is not maturity: this deliberately drifting history fails.
        self.assertFalse(atlas.periodic_window(np.arange(len(values)),values)['periodic_samples'])
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


class Case5bReferenceTests(unittest.TestCase):
    def setUp(self):
        self.spec=json.loads((ROOT/'cases/convection_r4_4.json').read_bytes())
        self.data,self.sha=audit.case5b_reference.load_reference(self.spec)
    def compare(self,diagnostics,stress=4.,regime='periodic'):
        return audit.compare_table('tosi-5b',diagnostics,self.spec,yield_stress=stress,regime=regime,cells=128)
    def periodic_diagnostics(self):
        rows=[t['rows']['4.0'][-1] for t in self.data['tables'] if t['code']!='MC3D']
        return dict(resolved=True,complete_cycles=10,
            mean_cycle_minimum=sum(float(r[0]) for r in rows)/len(rows),
            mean_cycle_maximum=sum(float(r[1]) for r in rows)/len(rows))
    def test_source_inventory_and_font_regimes_preserved(self):
        self.assertEqual(len(self.data['tables']),10)
        self.assertEqual(sum(c is not None for t in self.data['tables'] for r in t['rows'].values() for c in r),626)
        by_code={t['code']:t for t in self.data['tables']}
        self.assertEqual(by_code['ASPECT']['rows']['4.0'][-1],['2.6827','7.4246','periodic'])
        # Unequal printed extrema are not permission to override upright font.
        self.assertEqual(by_code['GAIA']['rows']['3.8'][-1],['4.6298','4.6383','steady'])
        self.assertEqual(by_code['MC3D']['table'],'S23')
        self.assertEqual(self.data['source']['sha256'],self.spec['cases']['case5b_numerical_targets']['source_pdf_sha256'])
    def test_changed_reference_bytes_refused_by_comparator_and_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            changed=copy.deepcopy(self.data);del changed['tables'][0]['rows']['4.0']
            (Path(tmp)/audit.case5b_reference.FILENAME).write_text(json.dumps(changed))
            with mock.patch.object(audit.case5b_reference,'CASE_DIR',Path(tmp)):
                with self.assertRaisesRegex(ValueError,'bytes changed'):self.compare(self.periodic_diagnostics())
                with self.assertRaisesRegex(ValueError,'bytes changed'):runner.source_record()
                self.assertTrue(any('Case 5b' in x for x in campaign.unresolved_references(self.spec)))
    def test_source_record_binds_actual_reference_and_comparator(self):
        source=runner.source_record()
        self.assertEqual(source['case5b_reference'],self.sha)
        self.assertEqual(source['case5b_comparator'],runner.digest((ROOT/'tools/tosi_case5b_reference.py').read_bytes()))
    def test_isolated_runner_loads_reference_without_script_path(self):
        code="import runpy,sys; r=runpy.run_path(sys.argv[1]); print(r['source_record']()['case5b_reference'])"
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT/'tools/run_convection_r4_4.py')],
            env=ENV,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),self.sha)
    def test_missing_target_or_changed_pin_reopens_reference_requirement(self):
        for target in (None,{},dict(self.spec['cases']['case5b_numerical_targets'],sha256='0'*64)):
            spec=copy.deepcopy(self.spec);spec['cases']['case5b_numerical_targets']=target
            with self.subTest(target=target):
                self.assertTrue(any('Case 5b' in x for x in campaign.unresolved_references(spec)))
    def test_both_ten_cycle_means_required_without_global_extrema_substitution(self):
        good=self.periodic_diagnostics();r=self.compare(good)
        self.assertTrue(r['all_available_metrics_within_envelope'])
        self.assertEqual(len(r['published_regime_groups']['periodic']),9)
        self.assertFalse(r['source_absent']);self.assertFalse(r['mixed_published_regimes'])
        for key in ('mean_cycle_minimum','mean_cycle_maximum'):
            bad=dict(good);del bad[key];bad['minimum']=1.;bad['maximum']=9.
            with self.subTest(key=key):
                self.assertEqual(self.compare(bad)['comparisons'][key]['status'],'MISSING')
                bad=dict(good);bad[key]*=2
                self.assertFalse(self.compare(bad)['all_available_metrics_within_envelope'])
        for value in (9,11,True,10.):
            self.assertEqual(self.compare(dict(good,complete_cycles=value))['status'],'UNRESOLVED')
        self.assertEqual(self.compare(dict(good,resolved=False))['status'],'UNRESOLVED')
    def test_source_absence_never_falls_back_to_coarser_mesh_or_another_yield(self):
        for stress,code,reason in ((3.,'ASPECT','printed dash'),(3.9,'StagYY','printed dash'),(3.1,'ASPECT','yield not tabulated')):
            r=self.compare({'Nu_top':4.7},stress,'steady')
            with self.subTest(stress=stress,code=code):
                entry=next(x for x in r['source_absent'] if x['code']==code)
                self.assertEqual(entry['reason'],reason)
                self.assertEqual(entry['status'],'SOURCE_ABSENT')
                self.assertNotIn(code,[x['code'] for g in r['published_regime_groups'].values() for x in g])
    def test_disagreeing_regimes_remain_separate_and_visible(self):
        r=self.compare({'Nu_top':4.634},3.8,'steady')
        self.assertTrue(r['mixed_published_regimes']);self.assertTrue(r['all_available_metrics_within_envelope'])
        self.assertEqual([x['code'] for x in r['published_regime_groups']['steady']],['GAIA'])
        self.assertEqual(len(r['published_regime_groups']['periodic']),8)
        self.assertEqual(self.compare({'Nu_top':4.634},4.,'steady')['status'],'UNRESOLVED')
    def test_bad_coordinates_and_nonfinite_diagnostics_refused(self):
        for stress in (True,3.01,2.9,5.1,float('nan'),float('inf'),'4'):
            with self.subTest(stress=stress),self.assertRaises(ValueError):self.compare({},stress)
        for cells in (True,0,128.,'128'):
            with self.subTest(cells=cells),self.assertRaises(ValueError):
                audit.compare_table('tosi-5b',{},self.spec,yield_stress=4.,regime='periodic',cells=cells)
        for value in (float('nan'),float('inf'),'2.7',True):
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.compare(dict(self.periodic_diagnostics(),mean_cycle_minimum=value))
    def test_adequacy_includes_both_cycle_means(self):
        reports=AnalysisPolicyTests().reports()
        for r in reports:
            r['case']={'name':'tosi-5b','yield_stress':4.}
            r['configuration']['case']=r['case'];r['regime']='periodic'
            r['periodic_sampling']={k:dict(periodic_samples=True,period=1.,minimum=1.,maximum=3.)
                for k in ('temperature_mean','Nu_top','velocity_rms','dissipation','dissipation_over_Ra')}
            r['case5b_cycle_extrema']=dict(resolved=True,complete_cycles=10,mean_cycle_minimum=1.,mean_cycle_maximum=3.)
        with mock.patch.object(audit,'cross_run_phase_field_gate',return_value={'status':'PASS','passed':True}):
            r=audit.study(reports,'mesh')
            self.assertEqual(r['status'],'ADEQUACY_GATE_PASSED')
            self.assertTrue(r['per_metric_passed']['Nu_top_mean_cycle_minimum'])
            self.assertTrue(r['per_metric_passed']['Nu_top_mean_cycle_maximum'])
            reports[-1]['case5b_cycle_extrema']['mean_cycle_minimum']=2.
            self.assertEqual(audit.study(reports,'mesh')['status'],'ADEQUACY_GATE_FAILED')
            reports[-1]['case5b_cycle_extrema']['resolved']=False
            with self.assertRaisesRegex(ValueError,'ten-cycle'):audit.study(reports,'mesh')
    def test_cross_axis_regimes_must_match(self):
        for regimes,expected in ((['periodic']*3,True),(['steady']*3,True),(['periodic','steady','periodic'],False),([],False)):
            reports=[dict(case={'name':'tosi-5b'},regime=r) for r in regimes]
            self.assertEqual(campaign.matched_representative_regimes(reports)['passed'],expected)


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
        self.assertEqual(result['unresolved_reference_requirements'],[])
    def test_changed_mapping_reopens_reference_requirement(self):
        spec=json.loads((ROOT/'cases/convection_r4_4.json').read_bytes())
        del spec['reference_policy']['case5a_dissipation']
        self.assertIn('Case 5a explicit derived dissipation mapping missing or changed',campaign.unresolved_references(spec))
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
