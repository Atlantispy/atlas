"""R2 analytical inventory/temperature tests and resolution invariants.

Expected inventories come from disjoint rectangle/prism and octant shell
formulae, not regenerating outputs of the sampling implementation.
"""
from dataclasses import replace
import itertools
import math
import unittest
import numpy as np
from numpy.polynomial.legendre import leggauss

from atlas_tectonics import (
    PreparedPrecursor, InitialSamplingCell, PrecursorSamplingLimits,
    ThermalInitialProfile, LayerComponent, SurfaceSelector, SubsurfaceBody,
    FeatureGeometry, GeologicalProvince, FeaturePrecedence, WeakZoneDescription,
    FaultDescription, PlanarGeometry, SphericalFrame, SphericalChart, SphericalGeometry,
    MaterialVolumeBasis, GeologyError, TectonicsError,
    SeededSpatialPrior, InitialScalarField, InputOrigin, GeologySource,
)
from atlas_tectonics.precursor_sampling import _prior_mean
from precursor_fixtures import (case,state,mixed_case,cell,rectangle,column,layer,
    REQUEST,FRAME,SOURCE,ROCK,ROCK_B,WATER,OLD,YOUNG,TEMP)


def phase_totals(result):
    ids=result.descriptor()['cohort_ids']
    return {name: math.fsum(result.array('phase_volume_m3')[result.array('phase_cohort_code')==i]) for i,name in enumerate(ids)}


def prior_state(surface=None,*,role='temperature_offset',mean=0.,amplitude=10.,scales=(13.,31.),seed=52):
    c=case(surface,sources=(SOURCE,GeologySource('prior','generated','Declared synthetic modes, not evolved geology.')))
    p=SeededSpatialPrior('input-prior',seed,mean,amplitude,scales,(0.,0.,0.),c.topology.domain_id,c.topology.frame_id)
    f=InitialScalarField('perturbation',role,'K' if role=='temperature_offset' else 'Pa','prior','Explicit initial scalar in named frame.',prior=p)
    return state(c,fields=(f,),origins=(InputOrigin('fixture','authored','test'),InputOrigin('prior','sampled_prior',p.prior_id)))


class PlanarSampling(unittest.TestCase):
    def test_mixed_cell_is_not_centre_point_winner(self):
        s=state(mixed_case())
        with PreparedPrecursor(s) as p:
            result=p.sample_cells((cell(),),**REQUEST)
            point=p.sample_points([[5.,5.]],15.,**REQUEST)
        self.assertEqual(phase_totals(result),{'old':1800.,'young':1200.})
        np.testing.assert_array_equal(result.temperature(),[380.])
        np.testing.assert_array_equal(point.temperature(),[300.])
        np.testing.assert_array_equal(result.array('coverage_residual_m3'),[0.])

    def test_vertical_layer_crossing_uses_thickness_not_midpoint(self):
        with PreparedPrecursor(state()) as p:
            r=p.sample_cells((cell(top=8.,bottom=13.),),**REQUEST)
        np.testing.assert_array_equal(r.array('bulk_volume_m3'),[200.,300.])
        self.assertEqual(r.array('cell_volume_m3')[0],500.)

    def test_horizontal_and_depth_refinement_preserves_inventories(self):
        fine=tuple(cell('c'+str(i)+'_'+str(j),rectangle(i,i+1),a,b) for i in range(10) for j,(a,b) in enumerate(((0.,7.),(7.,17.),(17.,30.))))
        with PreparedPrecursor(state(mixed_case(edge=3.7))) as p:
            coarse=p.sample_cells((cell(),),**REQUEST)
            r=p.sample_cells(fine,**REQUEST)
        for k,v in phase_totals(coarse).items(): self.assertAlmostEqual(v,phase_totals(r)[k],places=10)
        integrated=math.fsum(r.temperature()*r.array('cell_volume_m3'))/3000.
        self.assertAlmostEqual(integrated,coarse.temperature()[0],places=11)

    def test_point_layer_boundary_is_top_inclusive(self):
        with PreparedPrecursor(state()) as p:
            r=p.sample_points([[5,5],[5,5],[5,5]],np.array([0.,np.nextafter(10.,0.),10.]),**REQUEST)
            with self.assertRaises(GeologyError): p.sample_points([[5,5]],30.,**REQUEST)
        np.testing.assert_array_equal(r.array('unit_code'),[0,0,1])

    def test_point_province_boundary_retains_both_candidates(self):
        s=state(mixed_case())
        with PreparedPrecursor(s) as p: r=p.sample_points([[4,5],[8,5]],5.,**REQUEST)
        offsets=r.array('province_offsets'); codes=r.array('province_candidates')
        names=tuple(x.province_id for x in s.case.provinces)
        self.assertEqual(tuple(names[i] for i in codes[offsets[0]:offsets[1]]),('ocean-region','background'))
        self.assertEqual(names[r.array('province_code')[0]],'ocean-region')

    def test_union_selector_not_double_counted(self):
        c=mixed_case(edge=6.)
        gs=(FeatureGeometry('a',rectangle(0,4),'fixture'),FeatureGeometry('b',rectangle(2,6),'fixture'))
        provinces=(c.provinces[0],replace(c.provinces[1],selector=SurfaceSelector('geometry',('a','b'))))
        # Fixture case canonical order is background, ocean-region.
        d=dict(case_id=c.case_id,topology=c.topology,time_s=c.time_s,epoch_id=c.epoch_id,depth_reference_id=c.depth_reference_id,
               source_id=c.source_id,sources=c.sources,materials=c.materials,cohorts=c.cohorts,thermal_profiles=c.thermal_profiles,
               columns=c.columns,provinces=provinces,precedence=c.precedence,geometries=gs)
        from atlas_tectonics import GeologicalCase
        with PreparedPrecursor(state(GeologicalCase(**d))) as p: r=p.sample_cells((cell(),),**REQUEST)
        self.assertEqual(phase_totals(r),{'old':1200.,'young':1800.})

    def test_hole_in_query_retains_empty_volume(self):
        g=PlanarGeometry.polygon([(0,0),(10,0),(10,10),(0,10)],holes=([(2,2),(4,2),(4,4),(2,4)],),frame_id=FRAME)
        with PreparedPrecursor(state()) as p: r=p.sample_cells((cell(footprint=g),),**REQUEST)
        self.assertEqual(r.array('cell_volume_m3')[0],2880.)
        self.assertEqual(sum(phase_totals(r).values()),2880.)

    def test_pore_and_solid_volumes_and_reference_mass_separate(self):
        ls=(layer(thickness=10.,porosity=.2,components=(LayerComponent('old',.25),LayerComponent('young',.75))),)
        s=state(case(materials=(ROCK,ROCK_B,WATER),cohorts=(OLD,YOUNG),columns=(column(layers=ls,fluid='fluid'),)))
        with PreparedPrecursor(s) as p: r=p.sample_cells((cell(bottom=10.),),reference_mass_temperature_k=300.,**REQUEST)
        np.testing.assert_array_equal(r.array('bulk_volume_m3'),[1000.])
        np.testing.assert_array_equal(r.array('solid_volume_m3'),[800.])
        np.testing.assert_array_equal(r.array('explicit_pore_volume_m3'),[200.])
        self.assertEqual(phase_totals(r),{'old':200.,'young':600.})
        self.assertEqual(math.fsum(r.array('reference_mass_kg')),2e6)
        self.assertFalse(r.descriptor()['reference_mass_is_in_situ_mass'])

    def test_bulk_reference_does_not_claim_true_solid_volume(self):
        s=state(material_bases=(MaterialVolumeBasis('grain_a','bulk_reference','fixture'),))
        with PreparedPrecursor(s) as p: r=p.sample_cells((cell(),),**REQUEST)
        self.assertFalse(r.array('solid_volume_known').any())
        self.assertEqual(math.fsum(r.array('matrix_volume_m3')),3000.)

    def test_no_renormalisation_of_authored_component_fraction(self):
        fraction=1-5e-13
        c=case(columns=(column(layers=(layer(components=(LayerComponent('old',fraction),)),)),))
        with PreparedPrecursor(state(c)) as p: r=p.sample_cells((cell(bottom=10.),),**REQUEST)
        self.assertEqual(r.array('phase_volume_m3')[0],1000.*fraction)
        self.assertNotEqual(r.array('phase_volume_m3')[0],1000.)

    def test_unknown_porosity_refuses_inventory_not_point_temperature(self):
        s=state(case(columns=(column(layers=(layer(porosity=None),)),)))
        with PreparedPrecursor(s) as p:
            self.assertEqual(p.sample_points([[5,5]],1.,**REQUEST).temperature()[0],300.)
            with self.assertRaises(GeologyError): p.sample_cells((cell(bottom=10.),),**REQUEST)

    def test_mass_not_requested_has_explicit_unknown_mask(self):
        with PreparedPrecursor(state()) as p: r=p.sample_cells((cell(),),**REQUEST)
        self.assertFalse(r.array('reference_mass_known').any())
        self.assertIsNone(r.descriptor()['reference_mass_temperature_k'])

    def test_missing_or_nonmatching_density_refuses_requested_reference_mass(self):
        m=replace(ROCK,density_kg_m3=None,reference_temperature_k=None,valid_temperature_k=None,
                  conductivity_w_m_k=None,specific_heat_j_kg_k=None,heat_production_w_m3=None,
                  thermal_expansion_per_k=None,unknown_reason='no reference properties')
        with PreparedPrecursor(state(case(materials=(m,)))) as p:
            p.sample_cells((cell(),),**REQUEST)
            with self.assertRaises(GeologyError): p.sample_cells((cell(),),reference_mass_temperature_k=300.,**REQUEST)
        with PreparedPrecursor(state()) as p:
            with self.assertRaises(GeologyError): p.sample_cells((cell(),),reference_mass_temperature_k=1500.,**REQUEST)

    def test_query_overlap_is_not_silently_double_counted(self):
        overlapping=(cell('a',rectangle(0,6)),cell('b',rectangle(4,10)))
        with PreparedPrecursor(state()) as p:
            with self.assertRaises(GeologyError): p.sample_cells(overlapping,**REQUEST)
            r=p.sample_cells(overlapping,allow_overlapping_queries=True,**REQUEST)
        self.assertTrue(r.descriptor()['overlapping_queries_allowed'])
        self.assertEqual(math.fsum(r.array('cell_volume_m3')),3600.)

    def test_outside_domain_units_epoch_frame_and_depth_refused(self):
        with PreparedPrecursor(state()) as p:
            for key in REQUEST:
                wrong=REQUEST|{key:'incorrect'}
                with self.subTest(key=key),self.assertRaises(GeologyError): p.sample_points([[5,5]],1.,**wrong)
            for points,depth in (([[11,5]],1.),([[5,5]],-1.),([[5,5]],100.)):
                with self.subTest(points=points,depth=depth),self.assertRaises(TectonicsError): p.sample_points(points,depth,**REQUEST)
            with self.assertRaises(GeologyError): p.sample_cells((cell(footprint=rectangle(0,11)),),**REQUEST)

    def test_body_replaces_material_without_double_counting(self):
        b=SubsurfaceBody('slab','slab',SurfaceSelector('geometry',('body',)),5.,15.,layer('slab-layer',10.,cohort='young'),
                         'initial','fixture')
        c=case(materials=(ROCK,ROCK_B),cohorts=(OLD,YOUNG),geometries=(FeatureGeometry('body',rectangle(0,4),'fixture'),))
        with PreparedPrecursor(state(c,bodies=(b,),body_order=('slab',))) as p:
            r=p.sample_cells((cell(),),**REQUEST)
            point=p.sample_points([[1,5],[8,5]],10.,**REQUEST)
        self.assertEqual(phase_totals(r),{'old':2600.,'young':400.})
        self.assertEqual(point.state.units[point.array('unit_code')[0]].kind,'body')
        self.assertEqual(point.state.units[point.array('unit_code')[1]].kind,'column')

    def test_mantle_input_can_extend_below_lithosphere(self):
        b=SubsurfaceBody('mantle','mantle',SurfaceSelector('domain'),30.,50.,layer('deep',20.,'lithospheric_mantle'),'initial','fixture')
        with PreparedPrecursor(state(bodies=(b,),body_order=('mantle',))) as p:
            r=p.sample_cells((cell(bottom=50.),),**REQUEST)
            self.assertEqual(p.sample_points([[5,5]],40.,**REQUEST).temperature()[0],300.)
            with self.assertRaises(GeologyError): p.sample_cells((cell(bottom=51.),),**REQUEST)
        self.assertEqual(sum(phase_totals(r).values()),5000.)

    def test_body_precedence_changes_only_overridden_inventory(self):
        a=SubsurfaceBody('a','slab',SurfaceSelector('domain'),0.,10.,layer('a',10.,cohort='young'),'initial','fixture')
        b=SubsurfaceBody('b','slab',SurfaceSelector('domain'),5.,15.,layer('b',10.,cohort='old'),'initial','fixture')
        c=case(materials=(ROCK,ROCK_B),cohorts=(OLD,YOUNG))
        for order,young in ((('a','b'),1000.),(('b','a'),500.)):
            with self.subTest(order=order),PreparedPrecursor(state(c,bodies=(a,b),body_order=order)) as p:
                r=p.sample_cells((cell(),),**REQUEST)
                self.assertEqual(phase_totals(r)['young'],young)

    def test_fault_and_weak_zone_not_turned_into_damage(self):
        g=PlanarGeometry.polyline([(5,2),(5,8)],frame_id=FRAME)
        z=WeakZoneDescription('inherited',SurfaceSelector('geometry',('trace',)),0.,20.,.5,.4,'fixture')
        f=FaultDescription('suture',('trace',),0.,20.,math.pi/4,'right','fixture')
        c=case(geometries=(FeatureGeometry('trace',g,'fixture'),),weak_zones=(z,),faults=(f,))
        with PreparedPrecursor(state(c)) as p: r=p.sample_points([[5,1.4],[5,1.6],[5.3,4],[5,4]],np.array([5.,5.,5.,20.]),**REQUEST)
        np.testing.assert_array_equal(r.array('weak_zone_offsets'),[0,0,1,2,2])
        self.assertEqual(r.state.case.faults,(f,))
        self.assertFalse(any(x.role=='damage' for x in r.state.fields))

    def test_weak_zone_override_is_explicit_not_multiplication(self):
        a=WeakZoneDescription('a',SurfaceSelector('domain'),0.,20.,None,.4,'fixture')
        b=replace(a,zone_id='b',strength_factor=.2)
        c=case(weak_zones=(a,b),precedence=FeaturePrecedence(('background',),'ordered_override',('b','a')))
        with PreparedPrecursor(state(c)) as p: r=p.sample_points([[5,5]],1.,**REQUEST)
        np.testing.assert_array_equal(r.array('weak_zone_codes'),[1])


class ThermalSampling(unittest.TestCase):
    def test_piecewise_linear_profile_integrates_breaks_exactly(self):
        t=ThermalInitialProfile('initial','fixture','tabulated',depths_m=(0.,10.,30.),temperatures_k=(300.,500.,900.))
        with PreparedPrecursor(state(case(thermal_profiles=(t,)))) as p: r=p.sample_cells((cell(),),**REQUEST)
        self.assertAlmostEqual(r.temperature()[0],600.,places=12)
        self.assertEqual(r.array('temperature_quadrature_error_k')[0],0.)

    def test_half_space_mean_against_independent_antiderivative(self):
        age=4e6; kappa=1e-6; diffusion=2*math.sqrt(kappa*age)
        t=ThermalInitialProfile('initial','fixture','half_space',temperatures_k=(300.,1000.),
                               diffusivity_m2_s=kappa,cooling_start_time_s=-age)
        def primitive(z): return z*math.erf(z/diffusion)+diffusion/math.sqrt(math.pi)*math.exp(-(z/diffusion)**2)
        with PreparedPrecursor(state(case(thermal_profiles=(t,)))) as p:
            for lo,hi in ((0.,30.),(1.,3.),(8.,22.)):
                r=p.sample_cells((cell(top=lo,bottom=hi),),**REQUEST)
                expected=300+700*(primitive(hi)-primitive(lo))/(hi-lo)
                self.assertAlmostEqual(r.temperature()[0],expected,places=9)

    def test_zero_cooling_age_surface_has_zero_volume(self):
        t=ThermalInitialProfile('initial','fixture','half_space',temperatures_k=(300.,1000.),diffusivity_m2_s=1e-6,cooling_start_time_s=0.)
        with PreparedPrecursor(state(case(thermal_profiles=(t,)))) as p:
            r=p.sample_cells((cell(),),**REQUEST)
            q=p.sample_points([[5,5],[5,5]],np.array([0.,1.]),**REQUEST)
        np.testing.assert_array_equal(r.temperature(),[1000.])
        np.testing.assert_array_equal(q.temperature(),[300.,1000.])

    def test_unknown_temperature_explicit_opt_out(self):
        t=ThermalInitialProfile('initial','fixture','unknown',unknown_reason='not supplied')
        with PreparedPrecursor(state(case(thermal_profiles=(t,)))) as p:
            with self.assertRaises(GeologyError): p.sample_points([[5,5]],1.,**REQUEST)
            q=p.sample_points([[5,5]],1.,require_temperature=False,**REQUEST)
            with self.assertRaises(GeologyError): q.temperature()
            with self.assertRaises(GeologyError): p.sample_cells((cell(),),**REQUEST)
            r=p.sample_cells((cell(),),include_temperature=False,**REQUEST)
            with self.assertRaises(GeologyError): r.temperature()
        self.assertEqual(math.fsum(r.array('bulk_volume_m3')),3000.)

    def test_constant_offset_and_field_masks(self):
        f=InitialScalarField('offset','temperature_offset','K','fixture','Authored temperature adjustment.',constant_value=10.)
        unknown=InitialScalarField('stress','stress','Pa','fixture','sigma_xx',unknown_reason='not supplied')
        with PreparedPrecursor(state(fields=(f,unknown))) as p:
            a=p.sample_points([[5,5]],1.,fields=('stress','offset'),**REQUEST)
            b=p.sample_cells((cell(),),fields=('stress','offset'),**REQUEST)
        for r in (a,b):
            self.assertEqual(r.temperature()[0],310.)
            self.assertEqual(r.field_values('offset')[0],10.)
            with self.assertRaises(GeologyError): r.field_values('stress')

    def test_negative_temperature_offset_refused(self):
        f=InitialScalarField('offset','temperature_offset','K','fixture','Authored invalid temperature adjustment.',constant_value=-400.)
        with PreparedPrecursor(state(fields=(f,))) as p:
            with self.assertRaises(GeologyError): p.sample_points([[5,5]],1.,**REQUEST)
            with self.assertRaises(GeologyError): p.sample_cells((cell(),),**REQUEST)

    def test_prior_prism_mean_matches_independent_separable_integral(self):
        for scales in ((13.,31.),(1e8,), (1e16,),(.37,.79)):
            s=prior_state(scales=scales); prior=s.fields[0].prior
            g=rectangle(1,8,2,9); lo,hi=3.,20.
            expected=prior.mean
            for kx,ky,kz,phase in prior._waves:
                angle=kx*4.5+ky*5.5+kz*11.5+phase
                expected+=prior.amplitude/len(prior._waves)*math.cos(angle)*np.sinc(kx*7/(2*math.pi))*np.sinc(ky*7/(2*math.pi))*np.sinc(kz*17/(2*math.pi))
            self.assertAlmostEqual(_prior_mean(prior,g,lo,hi),expected,places=11)

    def test_prior_holes_and_reversed_rings_preserve_average(self):
        prior=prior_state().fields[0].prior
        exterior=[(0,0),(10,0),(10,10),(0,10)];hole=[(2,2),(4,2),(4,4),(2,4)]
        expected=(_prior_mean(prior,rectangle(),0.,30.)*100-_prior_mean(prior,rectangle(2,4,2,4),0.,30.)*4)/96
        for reverse in (False,True):
            g=PlanarGeometry.polygon(exterior[::-1] if reverse else exterior,holes=(hole[::-1] if reverse else hole,),frame_id=FRAME)
            self.assertAlmostEqual(_prior_mean(prior,g,0.,30.),expected,places=11)

    def test_prior_cell_refinement_preserves_integrated_world(self):
        with PreparedPrecursor(prior_state()) as p:
            coarse=p.sample_cells((cell(),),**REQUEST)
            fine=p.sample_cells(tuple(cell('c'+str(i),rectangle(i,i+1)) for i in range(10)),**REQUEST)
        self.assertAlmostEqual(math.fsum(fine.temperature())/10,coarse.temperature()[0],places=11)


class SphericalSampling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sphere=SphericalFrame(1000.,'spherical-fixture')
        cls.request=REQUEST|{'frame_id':cls.sphere.frame_id}
        cls.chart=SphericalChart(cls.sphere,(1,1,1))
        cls.octant=SphericalGeometry.polygon([(1,0,0),(0,1,0),(0,0,1)],chart=cls.chart)

    def test_true_shell_volume_not_surface_area_times_depth(self):
        with PreparedPrecursor(state(case(self.sphere))) as p:
            r=p.sample_cells((cell(footprint=self.octant),),**self.request)
        expected=math.pi/2*(1000.**3-970.**3)/3
        self.assertAlmostEqual(r.array('cell_volume_m3')[0]/expected,1.,places=13)
        self.assertNotAlmostEqual(expected,self.octant.area_m2*30.,places=0)

    def test_radial_linear_temperature_weighted_by_volume(self):
        t=ThermalInitialProfile('initial','fixture','tabulated',depths_m=(0.,30.),temperatures_k=(300.,900.))
        with PreparedPrecursor(state(case(self.sphere,thermal_profiles=(t,)))) as p:
            r=p.sample_cells((cell(footprint=self.octant),),**self.request)
        # Independent exact polynomial antiderivatives in depth.
        def v(z): return 1000**2*z-1000*z*z+z**3/3
        def vz(z): return 1000**2*z*z/2-2000*z**3/3+z**4/4
        expected=300+20*vz(30)/v(30)
        self.assertAlmostEqual(r.temperature()[0],expected,places=10)
        self.assertLess(expected,600.)

    def test_octant_subdivision_inventory_invariance(self):
        centre=np.array([1.,1.,1.])/math.sqrt(3)
        vs=[(1,0,0),(0,1,0),(0,0,1)]
        parts=tuple(cell('triangle'+str(i),SphericalGeometry.polygon([vs[i],vs[(i+1)%3],centre],chart=self.chart)) for i in range(3))
        with PreparedPrecursor(state(case(self.sphere))) as p:
            coarse=p.sample_cells((cell(footprint=self.octant),),**self.request)
            fine=p.sample_cells(parts,**self.request)
        self.assertAlmostEqual(math.fsum(fine.array('cell_volume_m3'))/coarse.array('cell_volume_m3')[0],1.,places=13)

    def test_cross_chart_total_is_not_silently_certified_as_disjoint_mesh(self):
        cells=[]
        for i,signs in enumerate(itertools.product((-1.,1.),repeat=3)):
            ch=SphericalChart(self.sphere,signs)
            vs=[(signs[0],0,0),(0,signs[1],0),(0,0,signs[2])]
            cells.append(cell('octant'+str(i),SphericalGeometry.polygon(vs,chart=ch)))
        with PreparedPrecursor(state(case(self.sphere))) as p:
            with self.assertRaisesRegex(GeologyError,'disjointness'):
                p.sample_cells(tuple(cells),**self.request)
            # This tests the sum of separate query volumes, not a certified
            # shared-topology mesh. The explicit opt-in remains in the result.
            r=p.sample_cells(tuple(cells),allow_overlapping_queries=True,**self.request)
        self.assertTrue(r.descriptor()['overlapping_queries_allowed'])
        expected=4*math.pi*(1000.**3-970.**3)/3
        self.assertAlmostEqual(math.fsum(r.array('cell_volume_m3'))/expected,1.,places=13)

    def test_spherical_points_use_normalised_directions(self):
        with PreparedPrecursor(state(case(self.sphere))) as p:
            a=p.sample_points([[1,0,0],[0,1,0]],5.,**self.request)
            b=p.sample_points([[7,0,0],[0,3,0]],5.,**self.request)
        np.testing.assert_array_equal(a.array('points'),b.array('points'))
        np.testing.assert_array_equal(a.temperature(),b.temperature())

    def test_spherical_prior_is_cartesian_without_longitude_seam(self):
        s=prior_state(self.sphere,scales=(1000.,))
        with PreparedPrecursor(s) as p:
            r=p.sample_points([[1,0,0],[1,0,0]],np.array([5.,5.]),**self.request)
            with self.assertRaisesRegex(GeologyError,'spherical cell means'):
                p.sample_cells((cell(footprint=self.octant),),**self.request)
            # Material inventory can explicitly omit the unsupported temperature mean.
            p.sample_cells((cell(footprint=self.octant),),include_temperature=False,**self.request)
        np.testing.assert_array_equal(r.temperature(),[r.temperature()[0]]*2)

    def test_no_centre_or_cross_frame_support(self):
        with self.assertRaises(GeologyError): cell(footprint=self.octant,bottom=1000.)
        with PreparedPrecursor(state(case(self.sphere))) as p:
            with self.assertRaises(GeologyError): p.sample_points([[1,0,0]],1000.,**self.request)
            with self.assertRaises(GeologyError): p.sample_cells((cell(),),**self.request)
