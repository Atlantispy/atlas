"""Bounded cross-run phase fields and configuration-only campaign preflight.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import analyse_convection_r4_4 as audit
import assess_convection_suite_r4_4 as campaign


def reports(axis='mesh'):
    case={'name':'tosi-5a','yield_stress':None};result=[]
    for i,n in enumerate((32,64,128)):
        config=dict(schema='synthetic',case=case,identities={'synthetic':True},cells=n if axis=='mesh' else 128,
            dt=1e-5*(1,.5,.25)[i] if axis=='timestep' else 1e-5,maximum_steps=30000,
            save_every=500,sample_every=25,thermal_policy={'max_steps':30000},
            nonlinear_policy={'momentum_tolerance':1e-9,'linear_rtol':1e-12,'viscosity_rtol':1e-8})
        if axis=='nonlinear':
            for k in config['nonlinear_policy']:config['nonlinear_policy'][k]*=(1,.1,.01)[i]
        result.append(dict(case=case,source={'synthetic':True},configuration=config,config_id=str(i),
            receipt_head='receipt-'+str(i),mature_regime_gate=True,regime='periodic',
            periodic_sampling={k:dict(periodic_samples=True,period=1.,minimum=.4,maximum=.6)
                for k in ('temperature_mean','Nu_top','velocity_rms','dissipation','dissipation_over_Ra')}))
    return result


def cycles(rr,offsets=(.001,.0002,.00004)):
    result=[];phase=np.linspace(0,1,101)
    for r,offset in zip(rr,offsets):
        n=r['configuration']['cells']
        result.append(dict(status='READY',cells=n,peak_times=[2.,3.],maximum_gap=.01,phase_samples=101,
            fields=np.broadcast_to((.5+.1*np.sin(2*np.pi*phase)+offset)[:,None,None],(101,n,n)),
            **{k:r[k] for k in ('config_id','receipt_head','source')}))
    return result


class PhaseStudyTests(unittest.TestCase):
    def test_scalar_only_periodic_study_is_incomplete(self):
        self.assertEqual(audit.study(reports(),'mesh')['status'],'INCOMPLETE_PHASE_FIELD_ADEQUACY')

    def test_all_three_axes_include_fields_at_unchanged_threshold(self):
        for axis,threshold in (('mesh',.01),('timestep',.005),('nonlinear',.001)):
            rr=reports(axis)
            with self.subTest(axis=axis):
                r=audit.study(rr,axis,phase_fields=cycles(rr))
                self.assertEqual(r['status'],'ADEQUACY_GATE_PASSED')
                self.assertEqual(r['phase_field_comparison']['tolerance'],threshold)
                self.assertFalse(r['full_benchmark_accepted'])

    def test_agreeing_scalars_cannot_hide_disagreeing_fields(self):
        rr=reports();cc=cycles(rr,(.03,.02,0.))
        r=audit.study(rr,'mesh',phase_fields=cc)
        self.assertTrue(all(r['per_metric_passed'].values()))
        self.assertEqual(r['status'],'ADEQUACY_GATE_FAILED')

    def test_mesh_restricts_cell_averages_instead_of_point_sampling(self):
        rr=reports();cc=cycles(rr,(0.,0.,0.))
        for c in cc[1:]:
            c['fields']=c['fields']+np.tile([-.05,.05],c['cells']//2)[None,None,:]
        r=audit.study(rr,'mesh',phase_fields=cc)
        self.assertEqual(r['status'],'ADEQUACY_GATE_PASSED')
        self.assertEqual(r['phase_field_comparison']['common_cells'],32)
        self.assertLess(r['phase_field_comparison']['middle_to_fine_linf'],1e-14)

    def test_nonlinear_fields_keep_same_support(self):
        rr=reports('nonlinear');cc=cycles(rr,(0.,0.,0.))
        cc[-1]['fields']=cc[-1]['fields']+np.tile([-.01,.01],64)[None,None,:]
        r=audit.study(rr,'nonlinear',phase_fields=cc)
        self.assertEqual(r['status'],'ADEQUACY_GATE_FAILED')
        self.assertEqual(r['phase_field_comparison']['common_cells'],128)

    def test_receipt_source_configuration_support_and_cadence_fail_closed(self):
        for key,value in (('receipt_head','stale'),('source',{'changed':True}),('config_id','stale'),
                          ('cells',63),('fields',np.zeros((100,64,64))),('maximum_gap',.011)):
            rr=reports();cc=cycles(rr);cc[1][key]=value
            with self.subTest(key=key):
                self.assertEqual(audit.study(rr,'mesh',phase_fields=cc)['status'],'INCOMPLETE_PHASE_FIELD_ADEQUACY')

    def test_nonmonotone_field_trend_is_not_promoted(self):
        rr=reports();cc=cycles(rr,(.001,-.0002,.00004))
        r=audit.study(rr,'mesh',phase_fields=cc)
        self.assertEqual(r['status'],'ADEQUACY_GATE_FAILED')
        self.assertFalse(r['phase_field_comparison']['monotone'])

    def test_final_cycle_is_interpolated_and_bound_without_full_history(self):
        report=reports()[0];report['configuration']['cells']=2
        t=np.arange(-2.,3.005,.005)
        states=[(float(x),np.full((2,2),x)) for x in t]
        c=audit.final_cycle_fields(report,states,[1.003,2.003],samples_per_period=100)
        self.assertEqual(c['status'],'READY');self.assertEqual(c['fields'].shape,(101,2,2))
        np.testing.assert_allclose(c['fields'][:,0,0],np.linspace(1.003,2.003,101),rtol=0,atol=1e-15)
        self.assertEqual(c['receipt_head'],report['receipt_head'])

    def test_sparse_or_uncovered_final_cycle_is_incomplete(self):
        report=reports()[0];report['configuration']['cells']=2
        for t in (np.linspace(0,2,101),np.linspace(1.1,2,101)):
            states=[(float(x),np.zeros((2,2))) for x in t]
            self.assertEqual(audit.final_cycle_fields(report,states,[1,2],samples_per_period=100)['status'],'INCOMPLETE')

    def test_cycle_array_envelope_is_fail_closed(self):
        report=reports()[0];report['configuration']['cells']=512
        states=[(float(x),np.zeros((1,1))) for x in np.linspace(0,1,101)]
        c=audit.final_cycle_fields(report,states,[0,1],samples_per_period=100)
        self.assertEqual(c['status'],'INCOMPLETE');self.assertIn('64 MiB',c['reason'])


class PreflightTests(unittest.TestCase):
    def test_preflight_cli_reads_no_run_arrays_or_analysis_and_reports_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);rr=reports();case=rr[0]['case']
            for i,r in enumerate(rr):
                path=base/str(i);path.mkdir();(path/'run.json').write_text(json.dumps(r['configuration']))
            manifest=base/'campaign.json';output=base/'preflight.json'
            manifest.write_text(json.dumps(dict(schema='atlas.convection-campaign-r4-4.v1',cases=[dict(
                case=case,mesh=['0','1','2'],timestep=['0','1','2'],nonlinear=['missing'])])))
            with mock.patch.object(campaign,'source_record',return_value={'synthetic':True}), \
                    mock.patch.object(audit,'analyse_run',side_effect=AssertionError('no analysis')) as analyse, \
                    mock.patch.object(audit,'ArrayStore',side_effect=AssertionError('no arrays')) as arrays, \
                    mock.patch.object(campaign.atlas,'PreparedThermochemical2D',side_effect=AssertionError('no solve')), \
                    mock.patch.object(sys,'argv',['assess','--manifest',str(manifest),'--output',str(output),'--preflight']), \
                    mock.patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(campaign.main(),0)
            r=json.loads(output.read_bytes())
            self.assertFalse(r['run_arrays_read']);self.assertFalse(r['full_benchmark_accepted'])
            self.assertEqual(r['distinct_planned_runs'],3);self.assertEqual(r['planned_run_references'],6)
            self.assertEqual(len(r['planned_run_reuse']),3)
            self.assertEqual(r['unresolved_reference_requirements'],[])
            self.assertTrue(r['study_configuration_issues'])
            self.assertTrue(all(run['schedule']['known_blockers'] for run in r['runs']))
            analyse.assert_not_called();arrays.assert_not_called()

    def test_missing_run_configurations_are_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'campaign.json'
            path.write_text(json.dumps(dict(schema='atlas.convection-campaign-r4-4.v1',cases=[dict(
                case=reports()[0]['case'],mesh=['absent-a','absent-b','absent-c'])])))
            r=campaign.preflight(path)
            self.assertEqual(len(r['runs']),3)
            self.assertTrue(all(run['status']=='MISSING_RUN_CONFIGURATION' for run in r['runs']))

    def test_malformed_schedule_is_reported_without_opening_arrays(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);config=reports()[0]['configuration'];config['sample_every']=0
            run=base/'bad';run.mkdir();(run/'run.json').write_text(json.dumps(config))
            path=base/'campaign.json'
            path.write_text(json.dumps(dict(schema='atlas.convection-campaign-r4-4.v1',cases=[dict(
                case=config['case'],mesh=['bad','other','third'])])))
            with mock.patch.object(audit,'ArrayStore',side_effect=AssertionError('no arrays')):
                r=campaign.preflight(path)
            self.assertEqual(r['runs'][0]['status'],'INVALID_RUN_CONFIGURATION')

    def test_full_assessment_forwards_cycles_and_does_not_replace_its_gates(self):
        rr=reports();cc=cycles(rr);case=rr[0]['case'];by_name=dict(zip(('a','b','c'),zip(rr,cc)))
        def analyse(path,*,phase_fields):
            report,cycle=by_name[path.name];phase_fields.update(cycle)
            return copy.deepcopy(report)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'campaign.json'
            path.write_text(json.dumps(dict(schema='atlas.convection-campaign-r4-4.v1',cases=[dict(
                case=case,mesh=['a','b','c'])])))
            with mock.patch.object(campaign,'expected_cases',return_value=[case]), \
                    mock.patch.object(audit,'analyse_run',side_effect=analyse) as analysis:
                r=campaign.assess(path)
            self.assertEqual(analysis.call_count,3)
            self.assertEqual(r['cases'][0]['studies']['mesh']['status'],'ADEQUACY_GATE_PASSED')
            self.assertFalse(r['full_benchmark_accepted'])


if __name__=='__main__':unittest.main()
