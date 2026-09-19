"""R4.2 status, actual-code example and optional-visual execution checks.
SPDX-License-Identifier: AGPL-3.0-only
"""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import thermochemical_example as example
import visual_thermochemical_r4_2 as visual
from atlas_tectonics import PreparedThermochemical2D,TectonicsError
from atlas_tectonics.resources import WorkBudget
from thermochemical_fixtures import problem,initial,circulation


class Delivery(unittest.TestCase):
    def test_case_keeps_R4_in_progress(self):
        d=json.loads((ROOT/'cases/thermochemical_r4_2.json').read_text())
        self.assertFalse(d['R4_complete']);self.assertEqual(d['R4_status'],'IN_PROGRESS')
        self.assertIn('R4.3',d['next_increment']);self.assertIn('R4.4',d['later_increment'])
    def test_source_references_are_explicit(self):
        d=json.loads((ROOT/'cases/thermochemical_r4_2.json').read_text());self.assertEqual(len(d['references']),5)
        for s in d['references']:self.assertTrue(s['url'].startswith('https://'))
    def test_example_shapes_units(self):
        s,c,h=example.build_initial_state(8)
        self.assertEqual(s.array('temperature_k').shape,(8,8));self.assertEqual(len(h),64)
        self.assertEqual(s.problem.box.width_m,1e6);self.assertTrue(np.all((s.array('composition')>=0)&(s.array('composition')<=1)))
    def test_example_evolves_not_renames_start(self):
        d,m=example.evolve_example(8,2)
        self.assertNotEqual(m['initial_id'],m['final_id']);self.assertEqual(m['final_time_s'],2e12)
        self.assertGreater(float(abs(d['final_temperature_k']-d['initial_temperature_k']).max()),0.)
        self.assertGreater(float(abs(d['final_composition']-d['initial_composition']).max()),0.)
        self.assertIn('SEPARATELY SOLVED',m['endpoint_flow_origin'])
        self.assertEqual(m['work_budget']['reserved_bytes'],0)
    def test_bound_example_arguments(self):
        for n in (0,1,193,True):
            with self.subTest(n=n),self.assertRaises(ValueError):example.build_initial_state(n)
        with self.assertRaises(ValueError):example.evolve_example(4,0)
    def test_visual_refuses_existing_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileExistsError):visual.main(['--output',temp])
    def test_visual_failure_does_not_publish_partial_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'new'
            with mock.patch.object(visual,'render',side_effect=RuntimeError('injected')):
                with self.assertRaises(RuntimeError):visual.main(['--output',str(out)])
            self.assertFalse(out.exists());self.assertFalse(out.with_name('new.preparing').exists())
            self.assertEqual(list(Path(temp).iterdir()),[])
    def test_second_stage_CFL_failure_is_atomic(self):
        p=problem(4);s=initial(p);v=circulation(p);b=WorkBudget(64<<20)
        u=v.array('u_m_s');w=v.array('w_m_s');sid=s.state_id
        with PreparedThermochemical2D(p,budget=b) as plan:
            held=b.reserved_bytes
            # An injected second-stage field checks failure handling only; it is
            # not a physical oracle or accepted endpoint produced by fake forcing.
            with mock.patch.object(plan,'_flow',side_effect=[(u,w,'0'*64),(u*1e6,w*1e6,'1'*64)]) as f:
                with self.assertRaises(TectonicsError):plan.advance(s,.1,source='injected stage-2 CFL')
                self.assertEqual(f.call_count,2)
            self.assertEqual(b.reserved_bytes,held)
            plan.advance(s,.01,source='real mechanics after failed call')
        self.assertEqual(s.state_id,sid);self.assertEqual(b.reserved_bytes,0)
    def test_states_not_declared_physical_acceptance(self):
        s,_,_=example.build_initial_state(4)
        self.assertFalse(s.descriptor()['physical_validation'])
    def test_maintained_stage_is_not_one_and_done(self):
        d=(ROOT/'docs/TECTONICS_PLAN.md').read_text()
        self.assertIn('R4.2',d);self.assertIn('R4.3',d);self.assertIn('R4.4',d)

if __name__=='__main__':unittest.main()
