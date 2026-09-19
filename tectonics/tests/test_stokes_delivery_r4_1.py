"""R4 continuation is explicit; visual arrays originate in the actual solver.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import numpy as np
from numpy.testing import assert_array_equal,assert_allclose
from atlas_tectonics import StokesSolvePolicy
ROOT=Path(__file__).resolve().parents[1]


def tool():
    spec=importlib.util.spec_from_file_location('atlas_r4_visual',ROOT/'tools/visual_stokes_r4_1.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


class ContinuationTests(unittest.TestCase):
    def setUp(self):self.case=json.loads((ROOT/'cases/stokes_r4_1.json').read_text())
    def test_r4_explicitly_in_progress_not_complete(self):
        self.assertEqual(self.case['R4_status'],'IN_PROGRESS');self.assertIs(self.case['R4_complete'],False)
    def test_all_next_parts_remain_unstarted(self):
        sequence=self.case['continuation'];self.assertEqual(len(sequence),4)
        for record in sequence[1:]:self.assertEqual(record['status'],'not_started')
        self.assertIn('R4.2',self.case['next_increment'])
    def test_default_policy_exactly_registered(self):
        self.assertEqual(self.case['default_policy'],asdict(StokesSolvePolicy()))
    def test_no_false_thermal_or_convection_acceptance(self):
        for key in ('physical_validation','R4_complete','thermal_evolution','composition_transport_2d',
                    'variable_viscosity','Tosi_convection_benchmark_reproduced','evolving_restart'):
            self.assertIs(self.case['acceptance'][key],False)
    def test_existing_t08_and_other_families_reused(self):
        self.assertIn('T08',self.case['verification_families']);self.assertIn('T15',self.case['verification_families'])
    def test_two_maintained_plans_have_progress_links(self):
        a=(ROOT/'docs/TECTONICS_PLAN.md').read_text();b=(ROOT/'docs/OPTIMISATION_REFERENCE.md').read_text()
        self.assertIn('R4 as a whole is NOT complete',a);self.assertIn('3cr4-progress',a)
        self.assertIn('Continue with R4.2',b)
    def test_r3_case_is_historical_not_rewritten_for_current_stage(self):
        old=json.loads((ROOT/'cases/physical_closure_r3.json').read_text())
        self.assertIs(old['acceptance']['R4_started'],False)
    def test_primary_references_record_implementation_not_copied_code(self):
        self.assertEqual(len(self.case['primary_sources']),4)
        self.assertIn('not copied',self.case['primary_sources'][0]['used'])


class VisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.tool=tool();cls.data,cls.meta=cls.tool.build_snapshot(16)
    def test_velocity_is_solved_and_temperature_labelled_authored(self):
        self.assertIn('AUTHORED',self.meta['temperature_origin'])
        self.assertIn('SOLVED',self.meta['kinematics_origin'])
        self.assertFalse(self.meta['solution']['R4_complete'])
    def test_actual_staggered_shapes_retained(self):
        self.assertEqual(self.data['u_m_s'].shape,(16,17));self.assertEqual(self.data['w_m_s'].shape,(17,16))
        self.assertEqual(self.data['pressure_pa'].shape,(16,16))
    def test_authored_temperature_matches_exact_declared_function(self):
        x,z=np.meshgrid(self.data['x_m'],self.data['z_m'])
        assert_allclose(self.data['authored_temperature_k'],1000+100*np.sin(np.pi*x/3e6)*np.sin(np.pi*z/3e6),rtol=0,atol=3e-13)
    def test_density_is_actual_r3_boussinesq_response(self):
        expected=-3300*3e-5*(self.data['authored_temperature_k']-1000)
        assert_array_equal(self.data['density_anomaly_kg_m3'],expected)
    def test_solved_central_upwelling_and_wall_impermeability(self):
        self.assertGreater(self.data['w_m_s'][8,8],0.)
        assert_array_equal(self.data['u_m_s'][:,[0,-1]],0.)
        assert_array_equal(self.data['w_m_s'][[0,-1]],0.)
    def test_divergence_is_raw_face_difference_not_display_smoothing(self):
        h=3e6/16
        d=np.diff(self.data['u_m_s'],axis=1)/h+np.diff(self.data['w_m_s'],axis=0)/h
        assert_allclose(self.data['divergence_s_1'],d,atol=1e-26)
    def test_visual_reuses_budget_and_closes_native_resources(self):
        self.assertEqual(self.meta['budget']['reserved_bytes'],0)
    def test_existing_destination_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileExistsError):self.tool.main(['--output',td])
    def test_render_failure_is_atomic_and_claim_released(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'new'
            with mock.patch.object(self.tool,'render',side_effect=ValueError('injected')):
                with self.assertRaises(ValueError):self.tool.main(['--output',str(p)])
            self.assertFalse(p.exists());self.assertFalse(p.with_name(p.name+'.preparing').exists())


if __name__=='__main__':unittest.main()
