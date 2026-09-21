"""W01 Stage 5: synthetic representation checks, not geological acceptance."""
from dataclasses import replace, FrozenInstanceError
import math
from pathlib import Path
import tempfile
import unittest
import sys

import numpy as np

from atlas_tectonics import (
    InitialConditionState, PreparedPrecursor, InitialSamplingCell,
    InputOrigin, CoolingHistory, MaterialVolumeBasis, GeologicalCase,
    GeologicalProvince, SurfaceSelector, FeaturePrecedence, ThermalInitialProfile,
    WeakZoneDescription, InitialScalarField, SphericalFrame, PlanetPartitionSettings,
    generate_planetary_partition, GeologyError, save_initial_samples, load_initial_samples,
    save_precursor_state, load_precursor_state, repatch_planetary_partition, build_boundary_network,
)
from atlas_tectonics.storage import ArrayStore, StoreLimits
from atlas_tectonics.resources import WorkBudget
from test_w01_geological_description import ingredients, column, layer, ROCK, WATER, TEMP
from test_precursor_scaling import policy


def initial(case, **changes):
    args = dict(
        origins=tuple(InputOrigin(s.source_id, 'authored', 'stage5-synthetic') for s in case.sources),
        cooling_history=tuple(CoolingHistory(t.profile_id, t.source_id,
            t.cooling_start_time_s if t.mode == 'half_space' else None,
            None if t.mode == 'half_space' else 'not supplied') for t in case.thermal_profiles),
        material_bases=tuple(MaterialVolumeBasis(m.material_id,
            'fluid' if m.material_class == 'fluid' else 'grain', m.source_id) for m in case.materials))
    args.update(changes)
    return InitialConditionState(case, **args)


def regional_case(**changes):
    args = ingredients()
    args.update(columns=(column(), column('other', profile='hot')),
        thermal_profiles=(TEMP, replace(TEMP, profile_id='hot', temperatures_k=(500.,))),
        provinces=(args['provinces'][0], GeologicalProvince('left-province', 'other',
            SurfaceSelector('plates', ('p1',)), 'synthetic')),
        precedence=FeaturePrecedence(('left-province', 'background')))
    args.update(changes)
    return GeologicalCase(**args)


def request(state):
    return dict(frame_id=state.sampling_domain.frame_id, epoch_id=state.case.epoch_id,
                depth_reference_id=state.case.depth_reference_id)


def prism(case, name='whole', footprint=None, top=0., bottom=30.):
    return InitialSamplingCell(name, case.topology.domain if footprint is None else footprint, top, bottom)


class RegionalInitialSampling(unittest.TestCase):
    def test_plate_selection_shared_boundary_and_original_identity(self):
        c = regional_case(); s = initial(c)
        with PreparedPrecursor(s) as plan:
            r = plan.sample_points([[2,5],[5,5],[8,5]], 5., **request(s))
        self.assertIs(s.case, c)
        self.assertEqual(s.descriptor()['case_definition_id'], c.definition_id)
        np.testing.assert_array_equal(r.temperature(), [500,500,300])
        np.testing.assert_array_equal(r.array('province_offsets'), [0,2,4,5])
        with self.assertRaises(FrozenInstanceError):
            s.case = c

    def test_region_selection_and_weak_zone(self):
        c = regional_case()
        args = ingredients(c.topology)
        args.update(columns=c.columns, thermal_profiles=c.thermal_profiles,
            provinces=(c.provinces[0], replace(c.provinces[1], selector=SurfaceSelector('regions', ('right',)))),
            precedence=c.precedence,
            weak_zones=(WeakZoneDescription('right-zone', SurfaceSelector('regions', ('right',)),
                0., 10., None, .5, 'synthetic'),))
        s = initial(GeologicalCase(**args))
        with PreparedPrecursor(s) as p:
            r = p.sample_points([[2,5],[5,5],[8,5]], 5., **request(s))
        np.testing.assert_array_equal(r.temperature(), [300,500,500])
        np.testing.assert_array_equal(r.array('weak_zone_offsets'), [0,0,1,2])

    def test_mixed_cells_and_refinement_conserve_reference_inventory(self):
        c = regional_case(); s = initial(c)
        with PreparedPrecursor(s) as p:
            coarse = p.sample_cells((prism(c),), reference_mass_temperature_k=300., **request(s))
            cells = tuple(prism(c, f'{r.region_id}-{i}', r.geometry, a, b)
                for r in c.topology.regions for i,(a,b) in enumerate(((0,7),(7,17),(17,30))))
            fine = p.sample_cells(cells, reference_mass_temperature_k=300., **request(s))
        self.assertAlmostEqual(coarse.temperature()[0], 400.)
        for result in (coarse, fine):
            self.assertAlmostEqual(sum(result.array('phase_volume_m3')), 3000.)
            self.assertAlmostEqual(sum(result.array('reference_mass_kg')), 9_000_000.)
        self.assertAlmostEqual(sum(fine.temperature()*fine.array('cell_volume_m3'))/3000., 400.)

    def test_changed_topology_changes_state_identity(self):
        c = regional_case(); args = ingredients(c.topology)
        original = GeologicalCase(**args)
        changed = build_boundary_network(c.topology.domain,
            tuple(replace(r,plate_id='renamed-'+r.plate_id) for r in c.topology.regions))
        other = GeologicalCase(**(args | {'topology': changed}))
        self.assertNotEqual(initial(original).state_id, initial(other).state_id)

    def test_profile_extrema_reused_for_repeated_depth_supports(self):
        from atlas_tectonics import precursor_sampling as sampling
        c = regional_case(); s = initial(c)
        cells = (prism(c,'a'),prism(c,'b'))
        calls = []
        def count(frame,event,arg):
            if event == 'call' and frame.f_code is sampling._temperature_bounds.__code__:
                calls.append(1)
        with PreparedPrecursor(s) as p:
            previous = sys.getprofile()
            try:
                # Observe calls without replacing source-bound implementation.
                sys.setprofile(count)
                p.sample_cells(cells,allow_overlapping_queries=True,**request(s))
            finally:
                sys.setprofile(previous)
        self.assertEqual(len(calls),4)  # Two profiles, two layer depth bands; not eight.

    def test_routing_once_per_repeated_footprint_not_depth_band(self):
        from atlas_tectonics import precursor_sampling as sampling
        c = regional_case(); s = initial(c); calls = []
        cells = tuple(prism(c,str(i),top=i*5.,bottom=(i+1)*5.) for i in range(6))
        def count(frame,event,arg):
            if event == 'call' and frame.f_code is sampling.PreparedPrecursor._candidate_keys.__code__:
                calls.append(1)
        with PreparedPrecursor(s) as p:
            previous = sys.getprofile()
            try:
                sys.setprofile(count)
                result = p.sample_cells(cells,**request(s))
            finally:
                sys.setprofile(previous)
            again = p.sample_cells(cells,**request(s))
        self.assertEqual(len(calls),1)
        self.assertEqual(result.sample_id,again.sample_id)
        self.assertAlmostEqual(sum(result.array('phase_volume_m3')),3000.)

    def test_cached_material_intersection_preserves_unknown_and_fluid_checks(self):
        args = ingredients()
        args.update(materials=(replace(ROCK,valid_temperature_k=None),replace(WATER,valid_temperature_k=(290.,310.))),
            columns=(column(layers=(layer(thickness=30.,porosity=.2),),fluid_material_id='water'),))
        s = initial(GeologicalCase(**args))
        with PreparedPrecursor(s) as p:
            for values in ((300.,300.), (290.,310.)):
                self.assertFalse(p._check_unit_temperature(0,*values))
            with self.assertRaisesRegex(GeologyError,'water'): p._check_unit_temperature(0,300.,311.)
            with self.assertRaisesRegex(GeologyError,'water'): p._check_unit_temperature(0,289.,300.)

    def test_vector_interpolation_preserves_segment_summation(self):
        from atlas_tectonics.precursor_sampling import _profile_mean, _depth_factor
        from atlas_tectonics import PrecursorSamplingLimits
        zs = tuple(np.linspace(0.,100.,1025))
        ts = tuple(300.+100.*np.sin(np.linspace(0.,9.,1025)))
        profile = ThermalInitialProfile('table','synthetic','tabulated',depths_m=zs,temperatures_k=ts)
        for top,bottom in ((0.,100.),(zs[13],zs[997]),(.127,99.87)):
            for radius in (None,1000.):
                cuts = (top,*(z for z in zs if top < z < bottom),bottom)
                terms = []
                for a,b in zip(cuts,cuts[1:]):
                    ta,tb = np.interp((a,b),zs,ts)
                    h = b-a
                    if radius is None: terms.append(h*(ta+tb)/2)
                    else:
                        r=(radius-a)/radius; q=h/radius
                        terms.append(h*(ta*(r*r-r*q+q*q/3)+(tb-ta)*(r*r/2-2*r*q/3+q*q/4)))
                expected = math.fsum(terms)/_depth_factor(top,bottom,radius)
                actual,error = _profile_mean(profile,top,bottom,0.,radius,PrecursorSamplingLimits(),None)
                self.assertEqual(actual,expected)
                self.assertEqual(error,0.)

    def test_tabulated_means_against_independent_rational_oracles(self):
        from atlas_tectonics.precursor_sampling import _profile_mean
        from atlas_tectonics import PrecursorSamplingLimits
        # Independent affine/tent areas, and polynomial antiderivatives of
        # T(z)*(R-z)**2 divided by ((R-top)**3-(R-bottom)**3)/3.
        # These expectations do not reuse the production segment formula.
        cases = (
            # Exact-knot endpoints; outside segments must not contribute.
            ((0.,1.,2.,4.,6.), (99.,2.,8.,4.,99.), 1.,4.,10.,17/3,5783/1026),
            # Partial interval entirely within the affine piece T=2*z-2.
            ((0.,2.,6.), (100.,2.,10.), 3.,5.,6.,6.,70/13),
            # Partial interval with an interior peak: T=500-100*abs(z-2).
            ((0.,2.,4.), (300.,500.,300.), 1.,3.,4.,450.,5825/13),
        )
        for zs,ts,top,bottom,radius,planar,spherical in cases:
            profile = ThermalInitialProfile('oracle','synthetic','tabulated',
                depths_m=zs,temperatures_k=ts)
            for r,expected in ((None,planar),(radius,spherical)):
                with self.subTest(depths=zs,top=top,bottom=bottom,radius=r):
                    actual,error = _profile_mean(profile,top,bottom,0.,r,
                        PrecursorSamplingLimits(),None)
                    self.assertAlmostEqual(actual,expected,delta=16*math.ulp(expected))
                    self.assertEqual(error,0.)

    def test_tabulated_mean_refuses_one_ulp_extrapolation(self):
        from atlas_tectonics.precursor_sampling import _profile_mean
        from atlas_tectonics import PrecursorSamplingLimits
        profile = ThermalInitialProfile('oracle','synthetic','tabulated',
            depths_m=(0.,2.,4.),temperatures_k=(300.,400.,500.))
        with self.assertRaisesRegex(GeologyError,'extrapolation'):
            _profile_mean(profile,1.,math.nextafter(4.,math.inf),0.,None,
                PrecursorSamplingLimits(),None)

    def test_frame_domain_and_depth_refusals(self):
        c = regional_case(); s = initial(c)
        with PreparedPrecursor(s) as p:
            for xy, z, kw in (([[11,5]],5.,request(s)), ([[5,5]],30.,request(s)),
                              ([[5,5]],5.,request(s)|{'frame_id':'wrong'})):
                with self.assertRaises(GeologyError): p.sample_points(xy,z,**kw)

    def test_unknown_porosity_and_temperature_remain_explicit(self):
        c = regional_case(columns=(column(layers=(layer(thickness=30.,porosity=None),)),),
            provinces=ingredients()['provinces'], precedence=FeaturePrecedence(('background',)),
            thermal_profiles=(ThermalInitialProfile('initial','synthetic','unknown',unknown_reason='unmeasured'),))
        s = initial(c)
        with PreparedPrecursor(s) as p:
            r = p.sample_points([[2,5]],5.,require_temperature=False,**request(s))
            self.assertFalse(r.array('temperature_known')[0])
            with self.assertRaises(GeologyError): r.temperature()
            with self.assertRaisesRegex(GeologyError,'porosity'):
                p.sample_cells((prism(c),),include_temperature=False,**request(s))

    def test_unused_unknown_density_does_not_block_reference_mass(self):
        missing = replace(ROCK, material_id='unused', density_kg_m3=None,
                          thermal_expansion_per_k=None, unknown_reason='unmeasured')
        c = regional_case(materials=(ROCK, missing)); s = initial(c)
        with PreparedPrecursor(s) as p:
            r = p.sample_cells((prism(c),), reference_mass_temperature_k=300., **request(s))
        self.assertAlmostEqual(sum(r.array('reference_mass_kg')), 9_000_000.)

    def test_used_unknown_density_refuses_only_mass_not_volume(self):
        missing = replace(ROCK, density_kg_m3=None, thermal_expansion_per_k=None, unknown_reason='unmeasured')
        c = regional_case(materials=(missing,)); s = initial(c)
        with PreparedPrecursor(s) as p:
            p.sample_cells((prism(c),), **request(s))
            with self.assertRaisesRegex(GeologyError,'density unavailable'):
                p.sample_cells((prism(c),), reference_mass_temperature_k=300., **request(s))

    def test_temperature_validity_checks_interior_not_mean(self):
        profile = ThermalInitialProfile('initial','synthetic','tabulated',
            depths_m=(0.,15.,30.), temperatures_k=(300.,800.,300.))
        c = regional_case(materials=(replace(ROCK, valid_temperature_k=(250.,600.)),),
            columns=(column(),), thermal_profiles=(profile,), provinces=ingredients()['provinces'],
            precedence=FeaturePrecedence(('background',)))
        s = initial(c)
        with PreparedPrecursor(s) as p:
            p.sample_points([[5,5]],0.,**request(s))
            with self.assertRaisesRegex(GeologyError,'material validity'): p.sample_points([[5,5]],15.,**request(s))
            with self.assertRaisesRegex(GeologyError,'material validity'): p.sample_cells((prism(c),),**request(s))

    def test_pore_fluid_validity_and_unknown_range_mask(self):
        args = ingredients()
        args.update(materials=(ROCK,replace(WATER,valid_temperature_k=(290.,310.))),
            columns=(column(layers=(layer(thickness=30.,porosity=.2),),fluid_material_id='water'),))
        c = GeologicalCase(**args)
        offset = InitialScalarField('warm','temperature_offset','K','synthetic','declared offset',constant_value=20.)
        s = initial(c, fields=(offset,))
        with PreparedPrecursor(s) as p:
            with self.assertRaisesRegex(GeologyError,'water'): p.sample_points([[5,5]],5.,**request(s))
            with self.assertRaisesRegex(GeologyError,'water'): p.sample_cells((prism(c),),**request(s))
        s = initial(regional_case(materials=(replace(ROCK,valid_temperature_k=None),)))
        with PreparedPrecursor(s) as p:
            r = p.sample_cells((prism(s.case),),**request(s))
        self.assertFalse(r.array('material_temperature_validity_known')[0])

    def test_serial_parallel_and_budget_release(self):
        c = regional_case(); s = initial(c); budget = WorkBudget(128<<20)
        results = []
        for mode in ('serial','threads'):
            with PreparedPrecursor(s,execution_policy=policy(mode),budget=budget) as p:
                points = p.sample_points([[2,5],[5,5],[8,5]],5.,**request(s))
                cells = p.sample_cells(tuple(prism(c,r.region_id,r.geometry) for r in c.topology.regions),**request(s))
                results.append((points.sample_id,cells.sample_id))
            self.assertEqual(budget.reserved_bytes,0)
        self.assertEqual(*results)

    def test_state_and_sample_cold_restore_retain_original_case(self):
        s = initial(regional_case())
        with PreparedPrecursor(s) as p: r = p.sample_cells((prism(s.case),),**request(s))
        with tempfile.TemporaryDirectory() as tmp:
            with ArrayStore(Path(tmp)/'store', StoreLimits(4096, 8<<20, 32<<20)) as store:
                save_precursor_state(s,store); save_initial_samples(r,store)
            with ArrayStore(Path(tmp)/'store', StoreLimits(4096, 8<<20, 32<<20)) as store:
                restored = load_initial_samples(store,r.sample_id)
                state = load_precursor_state(store,s.state_id)
            self.assertIs(type(state),InitialConditionState)
            self.assertEqual(state.case.definition_id,s.case.definition_id)
            self.assertEqual(restored.state.case.topology.network_id,s.case.topology.network_id)
            with PreparedPrecursor(state) as p:
                again = p.sample_cells((prism(state.case),),**request(state))
            self.assertEqual(again.sample_id,r.sample_id)


class PlanetaryInitialSampling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.topology = repatch_planetary_partition(generate_planetary_partition(
            SphericalFrame(1000.,'stage5-planet'),PlanetPartitionSettings(4,22)))

    def make_state(self):
        args = ingredients(self.topology)
        args.update(columns=(column(),column('other',profile='hot')),
            thermal_profiles=(TEMP,replace(TEMP,profile_id='hot',temperatures_k=(500.,))),
            provinces=(args['provinces'][0],GeologicalProvince('selected','other',
                SurfaceSelector('plates',(self.topology.plate_ids[0],)),'synthetic')),
            precedence=FeaturePrecedence(('selected','background')))
        return initial(GeologicalCase(**args))

    def test_all_face_inventories_and_multiface_plate_points(self):
        s = self.make_state(); topology = self.topology
        cells = tuple(InitialSamplingCell(r.region_id,r.geometry,0.,30.) for r in topology.regions)
        # Use each patch's actual vertex centroid, not its chart centre.
        lookup = dict(zip(topology.vertex_ids,topology.vertex_directions))
        points = [np.sum([lookup[k] for k in patch.vertex_ids],axis=0) for patch in topology.patches]
        with PreparedPrecursor(s) as p:
            r = p.sample_cells(cells,**request(s))
            q = p.sample_points(points,5.,**request(s))
        expected = [500. if patch.plate_id == topology.plate_ids[0] else 300. for patch in topology.patches]
        np.testing.assert_allclose(q.temperature(),expected,rtol=0,atol=0)
        np.testing.assert_allclose(r.temperature(),expected,rtol=0,atol=1e-10)
        self.assertAlmostEqual(sum(r.array('phase_volume_m3'))/(4*math.pi*(1000.**3-970.**3)/3),1.,places=12)
        self.assertFalse(r.descriptor()['overlapping_queries_allowed'])

    def test_same_face_overlapping_depths_still_refused(self):
        s = self.make_state(); g = self.topology.regions[0].geometry
        with PreparedPrecursor(s) as p:
            with self.assertRaisesRegex(GeologyError,'overlap'):
                p.sample_cells((InitialSamplingCell('a',g,0.,20.),InitialSamplingCell('b',g,10.,30.)),**request(s))

    def test_logical_region_selection_includes_every_patch(self):
        rid = self.topology.patches[0].region_id
        selected = [r for patch,r in zip(self.topology.patches,self.topology.regions) if patch.region_id == rid]
        self.assertGreater(len(selected),1)
        args = ingredients(self.topology)
        args.update(columns=(column(),column('other',profile='hot')),
            thermal_profiles=(TEMP,replace(TEMP,profile_id='hot',temperatures_k=(500.,))),
            provinces=(args['provinces'][0],GeologicalProvince('selected','other',SurfaceSelector('regions',(rid,)),'synthetic')),
            precedence=FeaturePrecedence(('selected','background')))
        s = initial(GeologicalCase(**args))
        cells = tuple(InitialSamplingCell(r.region_id,r.geometry,0.,30.) for r in self.topology.regions)
        with PreparedPrecursor(s) as p: result = p.sample_cells(cells,**request(s))
        expected = [500. if patch.region_id == rid else 300. for patch in self.topology.patches]
        np.testing.assert_allclose(result.temperature(),expected,rtol=0,atol=1e-10)

    def test_planet_round_trip_and_seam_sampling(self):
        s = self.make_state()
        with PreparedPrecursor(s) as p: r = p.sample_points(self.topology.vertex_directions,5.,**request(s))
        with tempfile.TemporaryDirectory() as tmp:
            with ArrayStore(Path(tmp)/'store', StoreLimits(4096, 8<<20, 32<<20)) as store:
                save_initial_samples(r,store)
                restored = load_initial_samples(store,r.sample_id)
        self.assertEqual(restored.state.case.topology.atlas_id,self.topology.atlas_id)
        self.assertEqual(restored.sample_id,r.sample_id)
        self.assertTrue(restored.array('temperature_known').all())


if __name__ == '__main__': unittest.main()
