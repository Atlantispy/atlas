"""Frozen case, real visual-data joins, source dependencies and publication rules.
SPDX-License-Identifier: AGPL-3.0-only
"""
import hashlib
import contextlib
import io
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose,assert_array_equal
from atlas_tectonics import reference_rheology
from atlas_tectonics import reuse
ROOT=Path(__file__).resolve().parents[1]


def visual_tool():
    spec=importlib.util.spec_from_file_location('r3_visual_tool',ROOT/'tools/visual_r3.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class CaseTests(unittest.TestCase):
    def setUp(self):self.case=json.loads((ROOT/'cases/physical_closure_r3.json').read_text())
    def test_registered_profiles_exact(self):
        for name,record in self.case['reference_profiles'].items():
            with self.subTest(name=name):
                self.assertEqual(json.loads(json.dumps(reference_rheology(name).descriptor())),record)
    def test_published_local_models_not_convection_claims(self):
        self.assertFalse(self.case['acceptance']['R4_started'])
        self.assertFalse(self.case['acceptance']['physical_validation'])
        self.assertIn('NOT R4',self.case['scope'])
    def test_reference_sources_include_exact_locations(self):
        source=self.case['primary_sources']
        self.assertEqual(source[0]['doi'],'10.1002/2015GC005807')
        self.assertIn('Table 1',source[0]['used'])
        self.assertEqual(source[1]['doi'],'10.1029/2023GC011179')
        self.assertIn('equations 6-8',source[1]['used'])
    def test_diffusive_and_depth_scales_separate(self):
        self.assertIn('separately required',self.case['scales']['depth'])
    def test_fixed_length_is_explicit_extension(self):
        self.assertIn('Atlas-declared',self.case['regularisation']['origin'])
        self.assertIn('coupled',self.case['regularisation']['not_accepted'])
    def test_sign_discrepancy_visible_not_silent_repair(self):
        self.assertIn('No author-confirmed erratum',self.case['frozen_solver_contract_for_R4']['printed_momentum_sign_note'])
    def test_all_new_loaded_modules_in_context(self):
        for name in ('constitutive','constitutive_execution','damage_regularisation'):
            self.assertIn(name,reuse._IDENTITY_MODULES)
    def test_banded_solver_runtime_identified(self):
        record=reuse._runtime_record('scipy')
        self.assertIn('scipy_lapack',record['binaries'])
    def test_agpl_full_text_in_package(self):
        s=(ROOT/'LICENSE').read_text()
        self.assertIn('GNU AFFERO GENERAL PUBLIC LICENSE',s)
        self.assertIn('13. Remote Network Interaction',s)
        self.assertIn('17. Interpretation of Sections 15 and 16',s)
        self.assertGreater(len(s),30000)
    def test_license_metadata_and_notice(self):
        import tomllib
        md=tomllib.loads((ROOT/'pyproject.toml').read_text())
        self.assertEqual(md['project']['license'],{'file':'LICENSE'})
        self.assertIn('AGPL-3.0-only',(ROOT/'THIRD_PARTY_NOTICES.md').read_text())
    def test_third_party_reference_notice_retained(self):
        self.assertIn('ODC-By',(ROOT/'THIRD_PARTY_NOTICES.md').read_text())
        self.assertTrue((ROOT/'reference_data/pb2002/LICENSE.md').is_file())


class VisualDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module=visual_tool();cls.data,cls.ids,cls.budget=cls.module.data_curves()
    def test_viscosity_axis_and_source_joins(self):
        T=self.data['temperature_axis'];self.assertEqual(len(T),241)
        self.assertEqual((T[0],T[-1]),(0,1))
        assert_allclose(self.data['tosi-1_viscosity'],np.exp(-np.log(1e5)*T),rtol=0,atol=0)
    def test_plastic_zero_end_and_no_fake_floor(self):
        self.assertGreater(self.data['tosi-2_viscosity'][0],self.data['tosi-1_viscosity'][0]/2)
        self.assertTrue(np.all(np.diff(self.data['tosi-4_viscosity'])<0))
    def test_weakening_stress_axes_match(self):
        for d in (0,5,10):self.assertEqual(self.data[f'damage_{d}_stress'].shape,self.data['strain_rate_axis'].shape)
        self.assertLess(self.data['damage_10_stress'][-1],self.data['damage_0_stress'][-1])
    def test_actual_memory_starts_above_saturation(self):
        for T in (0.,.025,.05):
            a=self.data[f'healing_T_{T:g}'];self.assertEqual(a[0],20.)
            self.assertTrue(np.all(np.diff(a)<=0))
            self.assertEqual(len(a),len(self.data['elapsed_axis']))
    def test_length_refinement_joins(self):
        errors=[]
        for n in (24,48,96):
            x=self.data[f'length_{n}_x_km'];a=self.data[f'length_{n}_damage']
            self.assertEqual(len(x),n);self.assertEqual(len(a),n)
            exact=2+np.cos(2*np.pi*x/1000)/(1+(.1*2*np.pi)**2)
            errors.append(np.max(abs(exact-a)))
        self.assertGreater(errors[0]/errors[-1],15)
    def test_warm_body_force_sign(self):
        a=self.data['buoyancy_C_0'];self.assertLess(a[0],0);self.assertGreater(a[-1],0)
    def test_all_plot_data_finite(self):
        self.assertTrue(all(np.isfinite(a).all() for a in self.data.values()))
    def test_no_retained_plan_leases(self):self.assertEqual(self.budget['reserved_bytes'],0)
    def test_existing_output_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError):self.module.main(['--output',tmp])
    def test_atomic_failed_render_not_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'new'
            with mock.patch.object(self.module,'render',side_effect=ValueError('bad image')):
                with self.assertRaises(ValueError):self.module.main(['--output',str(out)])
            self.assertFalse(out.exists());self.assertFalse(out.with_name('new.preparing').exists())
    def test_successful_output_publishes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'new'
            def render(stage):
                (stage/'visual_manifest.json').write_text('{}')
                return {'status':'RENDERED_AWAITING_VISUAL_REVIEW','outputs':{}}
            with mock.patch.object(self.module,'render',render), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.module.main(['--output',str(out)]),0)
            self.assertTrue((out/'visual_manifest.json').exists())


if __name__=='__main__':unittest.main()
