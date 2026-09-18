"""Verify data joins, map clipping and labels independently of image appearance.

The optional renderer is not imported here. Human inspection of produced PNGs
remains separate from these exact source/geometry checks.
"""
from dataclasses import replace
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock
import numpy as np

from atlas_tectonics import PreparedPrecursor, LayerComponent
from atlas_tectonics.timebase import JULIAN_MEGAYEAR

ROOT = Path(__file__).resolve().parents[1]

def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

visual = load_tool('visual_qa')
example = load_tool('prepare_precursor_example')


class VisualSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = example.build_example()

    def wrapped(self, *, time_s=None, cohorts=None, units=None):
        c = self.state.case
        return SimpleNamespace(case=SimpleNamespace(time_s=c.time_s if time_s is None else time_s,
            cohorts=c.cohorts if cohorts is None else cohorts), units=self.state.units if units is None else units)

    def test_authored_ages_are_joined_by_cohort_not_array_order(self):
        lookup, known, records = visual.formation_age_lookup(self.state)
        by_layer = {r['layer_id']: lookup[i] for i, r in enumerate(records)}
        self.assertEqual(by_layer, {'continental-crust': 2000., 'continental-mantle': 3000.,
                                    'oceanic-crust': 80., 'oceanic-mantle': 3000.})
        self.assertTrue(known.all())

    def test_cohort_order_does_not_change_join(self):
        a = visual.formation_age_lookup(self.state)
        b = visual.formation_age_lookup(self.wrapped(cohorts=tuple(reversed(self.state.case.cohorts))))
        np.testing.assert_array_equal(a[0], b[0]); self.assertEqual(a[2], b[2])

    def test_different_sampling_epoch_changes_age(self):
        a = visual.formation_age_lookup(self.state)[0]
        b = visual.formation_age_lookup(self.wrapped(time_s=5*JULIAN_MEGAYEAR.seconds_per_unit))[0]
        np.testing.assert_allclose(b-a, 5., rtol=0, atol=1e-12)

    def test_changed_source_formation_time_changes_age(self):
        cohorts = tuple(replace(d, cohort=replace(d.cohort, formation_time_s=-123.*JULIAN_MEGAYEAR.seconds_per_unit))
                        if d.cohort.cohort_id=='oceanic' else d for d in self.state.case.cohorts)
        lookup, _, records = visual.formation_age_lookup(self.wrapped(cohorts=cohorts))
        self.assertEqual(lookup[next(i for i,r in enumerate(records) if r['layer_id']=='oceanic-crust')], 123.)

    def test_missing_date_is_unknown_not_zero(self):
        cohorts = tuple(replace(d, cohort=replace(d.cohort, formation_time_s=None))
                        if d.cohort.cohort_id=='oceanic' else d for d in self.state.case.cohorts)
        lookup, known, records = visual.formation_age_lookup(self.wrapped(cohorts=cohorts))
        i = next(i for i,r in enumerate(records) if r['layer_id']=='oceanic-crust')
        self.assertTrue(np.isnan(lookup[i])); self.assertFalse(known[i])

    def test_mixed_ages_are_not_silently_averaged(self):
        u = self.state.units[0]
        layer = replace(u.layer, components=(LayerComponent('continental',.5), LayerComponent('oceanic',.5)))
        lookup, known, records = visual.formation_age_lookup(self.wrapped(units=(replace(u,layer=layer),)))
        self.assertFalse(known[0]); self.assertTrue(np.isnan(lookup[0]))
        self.assertEqual([c['age_ma'] for c in records[0]['components']], [2000.,80.])

    def test_future_formation_is_not_negative_display_age(self):
        with self.assertRaisesRegex(ValueError, 'non-negative'):
            visual.formation_age_lookup(self.wrapped(time_s=-4000*JULIAN_MEGAYEAR.seconds_per_unit))

    def test_sample_codes_read_actual_units(self):
        c = self.state.case
        with PreparedPrecursor(self.state) as plan:
            sample = plan.sample_points([[40000.,50000.],[140000.,50000.],[140000.,50000.]], [1000.,1000.,50000.],
                frame_id=c.topology.frame_id,epoch_id=c.epoch_id,depth_reference_id=c.depth_reference_id)
        lookup, known, _ = visual.formation_age_lookup(self.state)
        ages, mask = visual.ages_for_codes(sample.array('unit_code'),lookup,known)
        np.testing.assert_array_equal(ages,[80.,2000.,3000.]); self.assertTrue(mask.all())

    def test_invalid_sample_codes_cannot_index_another_unit(self):
        for codes in ([-1],[4],[0.5],[True]):
            with self.subTest(codes=codes), self.assertRaises(ValueError):
                visual.ages_for_codes(codes, np.arange(4), np.ones(4,dtype=bool))

    def test_cooling_age_not_used_for_formation(self):
        lookup = visual.formation_age_lookup(self.state)[0]
        h = self.state.cooling_history[0]
        cooling = (self.state.case.time_s-h.start_time_s)/JULIAN_MEGAYEAR.seconds_per_unit
        self.assertEqual(cooling,60.); self.assertFalse(np.any(lookup==cooling))

    def test_hyphen_does_not_mean_transform(self):
        self.assertEqual(visual.boundary_label(SimpleNamespace(kind='boundary',name='AF-AN')),
                         'Non-subducting (not necessarily transform)')

    def test_subduction_symbols_preserve_polarity(self):
        self.assertEqual(visual.boundary_label(SimpleNamespace(kind='boundary',name='AF/AN')),
                         'Subduction: right-hand plate beneath left')
        self.assertEqual(visual.boundary_label(SimpleNamespace(kind='boundary',name='AF\\AN')),
                         'Subduction: left-hand plate beneath right')

    def test_unknown_segment_is_not_guessed(self):
        for kind,name in [('plate','AF'),('boundary','AF?AN'),('boundary','AF--AN')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                visual.boundary_label(SimpleNamespace(kind=kind,name=name))

    def test_retained_source_readme_defines_non_subduction(self):
        s = (ROOT/'reference_data/pb2002/original/README.md').read_text()
        self.assertIn('All non-subducting plate boundary segments have a hyphen', s)


class VisualGeometryTests(unittest.TestCase):
    def test_antimeridian_segments_reach_both_map_edges(self):
        q = visual.lonlat_vectors([[179.,10.],[-179.,10.]])
        parts = visual.seam_segments(q)
        self.assertEqual(len(parts),2)
        self.assertEqual(parts[0][-1,0],180.); self.assertEqual(parts[1][0,0],-180.)
        self.assertEqual(parts[0][-1,1],parts[1][0,1])
        expected = np.rad2deg(np.arctan(np.tan(np.deg2rad(10.))/np.cos(np.deg2rad(1.))))
        self.assertAlmostEqual(parts[0][-1,1],expected,places=12)

    def test_reverse_seam_crossing(self):
        parts = visual.seam_segments(visual.lonlat_vectors([[-179.,10.],[179.,10.]]))
        self.assertEqual(parts[0][-1,0],-180.);self.assertEqual(parts[1][0,0],180.)

    def test_360_longitudes_normalise_only_display(self):
        raw=np.array([[190.,10.],[191.,10.]]);original=raw.copy()
        parts=visual.seam_segments(visual.lonlat_vectors(raw))
        self.assertEqual(len(parts),1);np.testing.assert_allclose(parts[0][:,0],[-170.,-169.])
        np.testing.assert_array_equal(raw,original)

    def test_seam_near_pole_remains_finite(self):
        parts=visual.seam_segments(visual.lonlat_vectors([[179.,89.],[-179.,89.]]))
        self.assertTrue(all(np.isfinite(p).all() and np.max(abs(p[:,1]))<=90. for p in parts))
        self.assertTrue(all(np.max(abs(np.diff(p[:,0])))<=180. for p in parts))

    def test_arc_density_preserves_endpoints_and_unit_sphere(self):
        a,b=visual.lonlat_vectors([[40.,20.],[80.,30.]])
        q=visual.densify_arc(a,b)
        np.testing.assert_allclose(q[[0,-1]], [a,b],atol=1e-15,rtol=0)
        np.testing.assert_allclose(np.linalg.norm(q,axis=1),1.,atol=3e-16,rtol=0)
        angles=np.arctan2(np.linalg.norm(np.cross(q[:-1],q[1:]),axis=1),np.sum(q[:-1]*q[1:],axis=1))
        self.assertLessEqual(np.rad2deg(angles).max(),.35+1e-12)

    def test_repeated_points_do_not_invent_arcs(self):
        a=visual.lonlat_vectors([[0.,0.]])[0]
        np.testing.assert_array_equal(visual.densify_arc(a,a),[a,a])

    def test_antipodal_arc_refused(self):
        with self.assertRaisesRegex(ValueError, 'antipodal'):
            visual.densify_arc([1.,0.,0.],[-1.,0.,0.])

    def test_invalid_display_step_refused(self):
        for v in [0.,-1.,float('nan'),10.]:
            with self.subTest(v=v),self.assertRaises(ValueError):visual.densify_arc([1,0,0],[0,1,0],max_angle_deg=v)

    def test_visible_limb_is_inserted_exactly(self):
        q=visual.lonlat_vectors([[60.,0.],[120.,0.]])
        parts=visual.visible_segments(q,0.,0.)
        self.assertEqual(len(parts),1)
        np.testing.assert_allclose(parts[0][-1],[1.,0.],rtol=0,atol=1e-15)
        self.assertTrue(np.all(np.linalg.norm(parts[0],axis=1)<=1.+1e-15))

    def test_back_hemisphere_not_drawn_through_globe(self):
        q=visual.lonlat_vectors([[170.,0.],[-170.,0.]])
        self.assertEqual(visual.visible_segments(q,0.,0.),[])

    def test_six_views_include_both_poles(self):
        self.assertIn((0.,90.),visual.CAMERAS);self.assertIn((0.,-90.),visual.CAMERAS)
        lons,lats=np.meshgrid(np.linspace(-180,180,37),np.linspace(-90,90,19))
        q=visual.lonlat_vectors(np.column_stack((lons.ravel(),lats.ravel())))
        seen=np.max(np.column_stack([q@visual.camera_axes(*v)[0] for v in visual.CAMERAS]),axis=1)
        self.assertTrue(np.all(seen>0))

    def test_camera_axes_are_orthonormal(self):
        for v in visual.CAMERAS:
            b=np.stack(visual.camera_axes(*v))
            np.testing.assert_allclose(b@b.T,np.eye(3),atol=1e-15,rtol=0)

    def test_existing_output_refused_without_rendering(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(visual,'render') as renderer:
            with self.assertRaises(FileExistsError):visual.main(['--output',d])
            renderer.assert_not_called()

    def test_failed_render_does_not_publish_or_retain_claim(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(visual,'render',side_effect=ValueError('test')):
            path=Path(d)/'new'
            with self.assertRaises(ValueError):visual.main(['--output',str(path)])
            self.assertFalse(path.exists());self.assertEqual(list(Path(d).iterdir()),[])
