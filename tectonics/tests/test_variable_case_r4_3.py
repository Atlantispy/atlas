"""Registered scope, actual-source visual data and output publication.
SPDX-License-Identifier: AGPL-3.0-only
"""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import visual_variable_stokes_r4_3 as visual
from atlas_tectonics import reference_rheology

class RegisteredCase(unittest.TestCase):
    def setUp(self):self.case=json.loads((ROOT/'cases/variable_stokes_r4_3.json').read_text())
    def test_r4_remains_in_progress(self):
        self.assertFalse(self.case['R4_complete']);self.assertEqual(self.case['R4_status'],'IN_PROGRESS')
        self.assertIn('R4.4',self.case['next_increment'])
    def test_no_new_rheology_selected(self):
        self.assertIn('unchanged R3',self.case['physics']['rheology'])
        self.assertIn('frozen',self.case['physics']['memory'])
    def test_declared_stress_not_eta_laplacian(self):
        self.assertIn('div(2 eta e)',self.case['physics']['momentum'])
        self.assertIn('S.T eta_v S',self.case['numerics']['sparse_velocity'])
    def test_baseline_and_physical_limits_explicit(self):
        self.assertEqual(self.case['baseline_package'],'0.1.0.dev29')
        self.assertIn('full Tosi convection reproduction',self.case['verification']['not_claimed'])
    def test_independent_mechanics_and_strength_families_used(self):
        self.assertIn('T08',self.case['verification']['families']);self.assertIn('T09',self.case['verification']['families'])
    def test_gmres_not_minres_for_nonsymmetric_preconditioner(self):
        self.assertIn('GMRES',self.case['numerics']['normal_solve'])
        self.assertEqual(self.case['numerics']['linear_rtol'],1e-12)
    def test_publication_requires_true_updated_rheology(self):
        self.assertIn('returned',self.case['numerics']['publication'])
        self.assertIn('updated',self.case['numerics']['nonlinear'])
    def test_sources_are_primary_and_no_new_pb2002(self):
        self.assertTrue(any(x['id']=='PETSc-DMStag-ex4' for x in self.case['sources']))
        self.assertTrue(any('no R1 reacquisition' in x['use'] for x in self.case['sources']))

class VisualData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data,cls.provenance,cls.refinements=visual.build_data()
    def test_nonzero_solved_fields_and_named_inputs(self):
        self.assertGreater(np.max(abs(self.data['snapshot_u_m_s'])),0)
        self.assertIn('AUTHORED',self.provenance['origin']);self.assertIn('SOLVED',self.provenance['origin'])
    def test_fraction_means_continuous_viscosity_not_binary_yield(self):
        r=self.data['viscosity_fraction_of_zero_rate']
        self.assertTrue(np.all((r>0)&(r<=1+1e-14)));self.assertLess(r.min(),.99)
        self.assertIn('not a discrete',self.provenance['viscosity_reduction'])
    def test_end_fields_actually_evolved(self):
        self.assertGreater(np.max(abs(self.data['evolved_temperature_k']-self.data['initial_temperature_k'])),0)
        self.assertGreater(np.max(abs(self.data['evolved_composition']-self.data['initial_composition'])),0)
    def test_endpoint_flow_different_identity_from_split_stages(self):
        self.assertNotIn(self.provenance['endpoint_solution_id'],self.provenance['step_records'][-1]['stage_flow_ids'])
    def test_true_residual_below_registered_gates(self):
        self.assertLess(self.data['nonlinear_momentum_residual'][-1],1e-9)
        self.assertLess(self.data['viscosity_log_change'][-1],1e-8)
    def test_evolution_uses_two_converged_stages(self):
        for r in self.provenance['step_records']:
            self.assertEqual(len(r['nonlinear_mechanics']['stages']),2)
            self.assertLess(r['balances']['composition_relative_residual'],1e-11)
    def test_output_arrays_all_finite(self):
        for k,a in self.data.items():
            with self.subTest(k=k):self.assertTrue(np.isfinite(a).all())
    def test_no_remaining_resource_reservations(self):
        self.assertEqual(self.provenance['budget']['reserved_bytes'],0)
    def test_existing_destination_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'keep';path.mkdir();(path/'sentinel').write_text('keep')
            with self.assertRaises(FileExistsError):visual.main(['--output',str(path)])
            self.assertEqual((path/'sentinel').read_text(),'keep')
    def test_failed_render_does_not_publish_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'failed'
            with mock.patch.object(visual,'render',side_effect=ValueError('injected')):
                with self.assertRaises(ValueError):visual.main(['--output',str(path)])
            self.assertFalse(path.exists());self.assertEqual(list(Path(tmp).iterdir()),[])
