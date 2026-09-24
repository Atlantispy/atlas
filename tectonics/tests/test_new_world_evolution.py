"""Focused independent controls for the generated regional material bridge."""
from concurrent.futures import CancelledError
import copy
import math
from pathlib import Path
import sys
from threading import Event
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src')]
import new_world_evolution as model
from new_world_contract import ContractError


def initial(gradient=None, velocity=(0., 0.)):
    # Analytical control, deliberately not offered as generated-world evidence.
    native = dict(polygons_m=[[[0.,0.],[10000.,0.],[10000.,10000.],[0.,10000.]]],
        parcel_ids=['control'], cohorts=[dict(cohort_id='crust', material_id='rock',
            origin_id='analytic', formation_time_s=None)], density_kg_m3=[2700.],
        volume_m3=[[3e12]], epoch_id='control-epoch', epoch_time_s=0.,
        frame_id='control-plane', datum_id='initial-surface',
        gradient_s=gradient if gradient is not None else [[-1e-14,0.],[2e-14,0.]],
        velocity_m_s=list(velocity), anchor_m=[0.,0.], max_elapsed_s=1e12,
        max_work_bytes=128*1024**2, mantle_density_kg_m3=3300.)
    r = dict(schema=model.SCHEMA, method=model.METHOD, source_binding={'test':'analytic'},
        project_id='analytic-not-generated', max_elapsed_s=1e12, native_input=native,
        support=dict(method='dry-local-Airy-change-v1', elastic_rigidity_nm=0.,
            fill_density_kg_m3=0., mantle_density_kg_m3=3300.))
    r['initial_id'] = model._digest(r)
    return r


class SupportTests(unittest.TestCase):
    def test_independent_column_weight_balance_and_sign(self):
        d, s, b, residual = model.local_isostatic_change([[30000.]], [[40000.]], [2700.], 3300.)
        np.testing.assert_allclose(d, [10000.])
        np.testing.assert_allclose(s, [10000.*600/3300])
        np.testing.assert_allclose(b, [-10000.*2700/3300])
        np.testing.assert_allclose(residual, 0., atol=1e-8)

    def test_multilayer_and_invalid_density(self):
        _, s, _, residual = model.local_isostatic_change([[10000.],[20000.]],
            [[12000.],[24000.]], [2600.,2900.], 3300.)
        np.testing.assert_allclose(s, [(2000.*700+4000.*400)/3300])
        np.testing.assert_allclose(residual, 0., atol=1e-8)
        with self.assertRaises(ContractError):
            model.local_isostatic_change([[1.]], [[2.]], [3400.], 3300.)


class NativeEvolutionTests(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(model, 'source_binding', return_value={'test':'analytic'})
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_oblique_shortening_conserves_material_and_generates_uplift(self):
        with model.PreparedEvolution(initial()) as prepared:
            start = prepared.evaluate(0.)
            end = prepared.evaluate(1e12)
        j = math.exp(-.01)
        np.testing.assert_allclose(end['area_ratio'], [j], rtol=1e-14)
        np.testing.assert_allclose(end['thickness_m'], [[30000./j]], rtol=1e-14)
        np.testing.assert_array_equal(end['mass_kg'], start['mass_kg'])
        np.testing.assert_array_equal(end['volume_m3'], start['volume_m3'])
        np.testing.assert_allclose(end['surface_change_m'], [(30000./j-30000.)*600/3300], rtol=1e-12)
        self.assertGreater(end['deformation_gradient'][0][1][0], 0.)
        self.assertIsNone(end['enthalpy_j'])
        self.assertFalse(end['enthalpy_known'])
        self.assertIsNone(end['cohorts'][0]['formation_time_s'])

    def test_pure_shear_and_rigid_translation_do_not_create_relief(self):
        for g, v in [([[0.,0.],[2e-14,0.]], (0.,0.)),
                     ([[0.,0.],[0.,0.]], (1e-9,-2e-9))]:
            with self.subTest(g=g), model.PreparedEvolution(initial(g,v)) as prepared:
                result = prepared.evaluate(1e12)
                np.testing.assert_allclose(result['area_ratio'], [1.], atol=1e-14)
                np.testing.assert_allclose(result['surface_change_m'], [0.], atol=1e-9)
                self.assertNotEqual(result['polygons_m'], initial(g,v)['native_input']['polygons_m'])

    def test_finite_expansion_thins_and_subsides(self):
        with model.PreparedEvolution(initial([[1e-14,0.],[2e-14,0.]])) as prepared:
            result = prepared.evaluate(1e12)
        self.assertLess(result['surface_change_m'][0], 0.)
        self.assertGreater(result['base_change_m'][0], 0.)

    def test_restore_direct_finite_map_matches_uninterrupted_outputs(self):
        r = initial()
        with model.PreparedEvolution(r) as prepared:
            expected = [prepared.evaluate(t)['output_id'] for t in (0.,5e11,1e12)]
        actual = []
        for t in (0.,5e11,1e12):
            with model.PreparedEvolution(copy.deepcopy(r)) as restored:
                actual.append(restored.evaluate(t)['output_id'])
        self.assertEqual(actual, expected)

    def test_changed_initial_changed_source_and_unsupported_time_refuse(self):
        r = initial(); r['native_input']['volume_m3'][0][0] *= 2
        with self.assertRaises(ContractError):
            model.PreparedEvolution(r)
        with patch.object(model, 'source_binding', return_value={'test':'changed'}):
            with self.assertRaises(ContractError):
                model.PreparedEvolution(initial())
        with model.PreparedEvolution(initial()) as p:
            for value in (-1., 1e12+1., float('nan'), True):
                with self.subTest(value=value), self.assertRaises(ContractError):
                    p.evaluate(value)

    def test_cancelled_preparation_and_closed_owner_refuse(self):
        event = Event(); event.set()
        with self.assertRaises(CancelledError):
            model.PreparedEvolution(initial(), cancel=event)
        p = model.PreparedEvolution(initial()); p.close()
        with self.assertRaises(ContractError):
            p.evaluate(0.)


if __name__ == '__main__':
    unittest.main()
