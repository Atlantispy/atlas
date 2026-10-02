"""R2 definition/provenance contracts; synthetic inputs are not Earth validation."""
from dataclasses import FrozenInstanceError, replace
import copy
import math
import threading
from concurrent.futures import CancelledError
import unittest
import numpy as np

from atlas_tectonics import (
    GeologicalDomain, GeologicalCase, GeologyError, TectonicsError,
    PlanarGeometry, SphericalFrame, SphericalChart, SphericalGeometry,
    SurfaceSelector, GeologicalProvince, FeatureGeometry, FeaturePrecedence,
    InputOrigin, CoolingHistory, MaterialVolumeBasis, PrecursorState,
    SeededSpatialPrior, InitialScalarField, SubsurfaceBody, ThermalInitialProfile,
    GeologySource, MaterialCohort, CohortDescription, LayerComponent,
    earth_material_library,
)
from atlas_tectonics import ColumnDescription
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from precursor_fixtures import (case, state, ingredients, rectangle, column, layer,
    REQUEST, FRAME, SOURCE, ROCK, ROCK_B, WATER, OLD, YOUNG, TEMP)


class DomainContracts(unittest.TestCase):
    def test_no_fake_plate_or_region_labels(self):
        d=case().topology
        self.assertEqual(d.plate_ids, ())
        self.assertEqual(d.region_ids, ())
        self.assertEqual(d.regions, ())
        self.assertEqual(d.frame_id, FRAME)

    def test_full_sphere_is_not_fake_single_polygon(self):
        d=GeologicalDomain(SphericalFrame(1000., 'world'), 'fixture')
        self.assertTrue(d.full_sphere)
        with self.assertRaises(GeologyError): _=d.domain
        self.assertEqual(case(d.surface).topology.domain_id,d.domain_id)

    def test_bounded_spherical_domain(self):
        ch=SphericalChart(SphericalFrame(1000.,'world'), (1,0,0))
        g=SphericalGeometry.polygon([(1,-.2,-.2),(1,.2,-.2),(1,.2,.2),(1,-.2,.2)],chart=ch)
        c=case(g)
        self.assertFalse(c.topology.full_sphere)
        self.assertEqual(c.topology.sphere,ch.sphere)

    def test_lines_and_untyped_surfaces_refused(self):
        line=PlanarGeometry.polyline([(0,0),(1,1)],frame_id=FRAME)
        for g in (line,{},None):
            with self.subTest(g=type(g)),self.assertRaises(GeologyError): GeologicalDomain(g,'fixture')

    def test_final_plate_selectors_refused(self):
        for kind in ('plates','regions'):
            p=GeologicalProvince('background','continent',SurfaceSelector(kind,('p1',)),'fixture')
            with self.subTest(kind=kind), self.assertRaises(GeologyError): case(provinces=(p,))

    def test_domain_source_must_be_in_case(self):
        with self.assertRaises(GeologyError): case(topology=GeologicalDomain(rectangle(),'absent'))

    def test_mixed_frames_and_outside_geometry_refused(self):
        for g in (rectangle(frame='different'), rectangle(-1,2)):
            with self.subTest(g=g.geometry_id),self.assertRaises(GeologyError):
                case(geometries=(FeatureGeometry('bad',g,'fixture'),))

    def test_domain_identity_tracks_actual_support(self):
        a=case(); b=case(rectangle(0,11))
        self.assertNotEqual(a.definition_id,b.definition_id)
        self.assertNotEqual(a.topology.domain_id,b.topology.domain_id)


class ProvenanceContracts(unittest.TestCase):
    def test_origin_inventory_exact(self):
        for origins in ((), (InputOrigin('absent','authored','case'),), (InputOrigin('fixture','authored','case'),)*2):
            with self.subTest(origins=origins), self.assertRaises(GeologyError): state(origins=origins)

    def test_observation_requires_evidence(self):
        with self.assertRaises(GeologyError): state(origins=(InputOrigin('fixture','observed','survey'),))
        src=replace(SOURCE,kind='observation',references=('doi:synthetic-fixture-only',))
        s=state(case(sources=(src,)),origins=(InputOrigin('fixture','observed','survey'),))
        self.assertEqual(s.origins[0].basis_id,'survey')

    def test_model_import_requires_parent_hash(self):
        with self.assertRaises(GeologyError): InputOrigin('fixture','model_evolved','model')
        s=state(origins=(InputOrigin('fixture','model_evolved','model-run','a'*64),))
        self.assertEqual(s.origins[0].parent_state_id,'a'*64)
        with self.assertRaises(GeologyError): InputOrigin('fixture','authored','model','a'*64)

    def test_formation_and_cooling_are_not_interchangeable(self):
        s=state()
        self.assertEqual(s.case.cohorts[0].cohort.formation_time_s,-100.)
        self.assertEqual(s.cooling_history[0].start_time_s,-10.)
        self.assertNotEqual(s.case.time_s-s.case.cohorts[0].cohort.formation_time_s,
                            s.case.time_s-s.cooling_history[0].start_time_s)

    def test_explicit_unknown_cooling_is_retained(self):
        s=state(cooling_history=(CoolingHistory('initial','fixture',None,'not measured'),))
        self.assertIsNone(s.cooling_history[0].start_time_s)
        s.require(require_temperature=True)  # temperature can be authored independently
        with self.assertRaises(GeologyError): CoolingHistory('initial','fixture',None)
        with self.assertRaises(GeologyError): CoolingHistory('initial','fixture',-10.,'contradictory')

    def test_future_or_overflow_cooling_refused(self):
        with self.assertRaises(GeologyError): state(cooling_history=(CoolingHistory('initial','fixture',1.),))
        with self.assertRaises(GeologyError): state(case(time_s=1e308),cooling_history=(CoolingHistory('initial','fixture',-1e308),))

    def test_half_space_history_must_match(self):
        p=ThermalInitialProfile('initial','fixture','half_space',temperatures_k=(300.,1000.),
                               diffusivity_m2_s=1e-6,cooling_start_time_s=-1e6)
        s=state(case(thermal_profiles=(p,)))
        self.assertEqual(s.cooling_history[0].start_time_s,p.cooling_start_time_s)
        with self.assertRaises(GeologyError): state(s.case,cooling_history=(CoolingHistory('initial','fixture',-10.),))

    def test_all_profiles_require_cooling_record(self):
        with self.assertRaises(GeologyError): state(cooling_history=())

    def test_required_unknowns_reported_not_zeroed(self):
        p=ThermalInitialProfile('initial','fixture','unknown',unknown_reason='no temperatures')
        c=case(thermal_profiles=(p,),columns=(column(layers=(layer(porosity=None),)),))
        s=state(c)
        issues=s.preflight(require_temperature=True,require_porosity=True,required_fields=('sigma_xx','damage'))
        self.assertEqual(len(issues),4)
        with self.assertRaises(GeologyError): s.require(require_temperature=True)
        self.assertIn(('stress','not supplied; neither zero nor inferred from a weak-zone multiplier'),s.unresolved_initial_state)

    def test_field_role_units_and_exact_one_representation(self):
        for kwargs in ({}, {'constant_value':0.,'unknown_reason':'x'}):
            with self.assertRaises(GeologyError): InitialScalarField('s','stress','Pa','fixture','sigma_xx',**kwargs)
        with self.assertRaises(GeologyError): InitialScalarField('s','stress','K','fixture','sigma_xx',constant_value=0.)
        with self.assertRaises(TectonicsError): InitialScalarField('s','stress','Pa','fixture','sigma_xx',constant_value=float('nan'))

    def test_prescribed_force_has_no_predicted_motion_claim(self):
        f=InitialScalarField('basal','prescribed_forcing','Pa','fixture','Authored basal shear component in local x.',constant_value=3.)
        s=state(fields=(f,))
        s.require(required_fields=('basal',))
        self.assertEqual(s.fields[0].constant_value,3.)

    def test_material_volume_basis_required(self):
        with self.assertRaises(GeologyError): state(material_bases=())
        with self.assertRaises(GeologyError): state(material_bases=(MaterialVolumeBasis('grain_a','fluid','fixture'),))

    def test_no_double_porosity_on_bulk_reference_rock(self):
        c=case(materials=(ROCK,WATER),columns=(column(layers=(layer(porosity=.1),),fluid='fluid'),))
        bases=(MaterialVolumeBasis('grain_a','bulk_reference','fixture'),MaterialVolumeBasis('fluid','fluid','fixture'))
        with self.assertRaises(GeologyError): state(c,material_bases=bases)

    def test_state_and_nested_maps_are_immutable(self):
        s=state()
        with self.assertRaises(FrozenInstanceError): s.state_id='x'
        with self.assertRaises(TypeError): s._maps['materials']['grain_a']=ROCK_B
        self.assertIs(copy.deepcopy(s),s)
        d=s.descriptor(); d['origins'].clear()
        self.assertEqual(len(s.origins),1)

    def test_input_change_invalidates_identity(self):
        a=state(); b=state(case(time_s=1.))
        c=state(cooling_history=(CoolingHistory('initial','fixture',-9.),))
        d=state(fields=(InitialScalarField('s','stress','Pa','fixture','sigma_xx',constant_value=0.),))
        self.assertEqual(len({x.state_id for x in (a,b,c,d)}),4)

    def test_definition_budget_and_cancellation(self):
        budget=WorkBudget(1)
        with self.assertRaises(MemoryLimitError): state(budget=budget)
        self.assertEqual(budget.reserved_bytes,0)
        cancel=threading.Event(); cancel.set()
        with self.assertRaises(CancelledError): state(cancel=cancel)

    def test_body_precedence_is_explicit(self):
        body=SubsurfaceBody('mantle','mantle',SurfaceSelector('domain'),30.,50.,layer('deep',20.,'lithospheric_mantle'),
                            'initial','fixture')
        with self.assertRaises(GeologyError): state(bodies=(body,))
        s=state(bodies=(body,),body_order=('mantle',))
        self.assertEqual(s.units[-1].bottom_depth_m,50.)

    def test_body_thickness_and_pore_fluid_requirements(self):
        with self.assertRaises(GeologyError): SubsurfaceBody('b','slab',SurfaceSelector('domain'),2.,8.,layer(),'initial','fixture')
        with self.assertRaises(GeologyError): SubsurfaceBody('b','slab',SurfaceSelector('domain'),0.,10.,layer(porosity=.2),'initial','fixture')

    def test_body_must_have_declared_cohort_and_area(self):
        b=SubsurfaceBody('b','slab',SurfaceSelector('geometry',('absent',)),0.,10.,layer(),'initial','fixture')
        with self.assertRaises(GeologyError): state(bodies=(b,),body_order=('b',))
        b=replace(b,selector=SurfaceSelector('domain'),layer=layer(cohort='absent'))
        with self.assertRaises(GeologyError): state(bodies=(b,),body_order=('b',))

    def test_body_temperature_no_extrapolation(self):
        p=ThermalInitialProfile('initial','fixture','tabulated',depths_m=(0.,30.),temperatures_k=(300.,900.))
        b=SubsurfaceBody('b','mantle',SurfaceSelector('domain'),30.,50.,layer('deep',20.,'lithospheric_mantle'),'initial','fixture')
        with self.assertRaises(GeologyError): state(case(thermal_profiles=(p,)),bodies=(b,),body_order=('b',))


class ThermalTableCoverageContracts(unittest.TestCase):
    """A tabulated profile must reach the represented column base, not only the declared one."""
    def stack(self, thicknesses, declared, table_end):
        named=(('sediment','sediment'),('crust','crust'),('mantle','lithospheric_mantle'))[-len(thicknesses):]
        layers=tuple(layer(name,t,role) for (name,role),t in zip(named,thicknesses))
        c=ColumnDescription('continent','continental',layers,declared,'initial','fixture')
        p=ThermalInitialProfile('initial','fixture','tabulated',depths_m=(0.,table_end),temperatures_k=(300.,400.))
        return c,dict(thermal_profiles=(p,),columns=(c,))

    def test_table_ending_at_declared_thickness_above_the_last_layer_edge_is_refused_at_stage_4(self):
        # 0.1 m + 0.2 m: the running sum of the layers is 0.30000000000000004, one
        # rounding unit deeper than a declared 0.3 m and inside the 1e-12 stack tolerance.
        c,changes=self.stack((.1,.2),.3,.3)
        self.assertGreater(c.layer_edges_m[-1],c.lithosphere_thickness_m)
        with self.assertRaises(GeologyError): case(**changes)

    def test_table_reaching_the_last_layer_edge_is_accepted_at_both_stages(self):
        c,changes=self.stack((.1,.2),.3,.1+.2)
        s=state(case(**changes))
        self.assertEqual(s.units[-1].bottom_depth_m,c.layer_edges_m[-1])
        self.assertEqual(s.case.thermal_profiles[0].depths_m[-1],c.layer_edges_m[-1])

    def test_declared_thickness_still_binds_when_it_is_the_deeper(self):
        # 0.1 m + 0.7 m: the running sum 0.7999999999999999 is shallower than a declared 0.8 m.
        c,changes=self.stack((.1,.7),.8,.1+.7)
        self.assertLess(c.layer_edges_m[-1],c.lithosphere_thickness_m)
        with self.assertRaises(GeologyError): case(**changes)
        c,changes=self.stack((.1,.7),.8,.8)
        self.assertEqual(state(case(**changes)).units[-1].bottom_depth_m,c.layer_edges_m[-1])

    def test_table_between_depths_thousands_of_rounding_units_apart_is_refused_at_stage_4(self):
        # 40 km + 60 km end at exactly 100000 m. A declared thickness 5e-13 or 9.9e-13
        # relative away passes the 1e-12 stack check thousands of rounding units from that
        # edge, on either side. A table ending short of the deeper depth is refused at stage 4.
        for declared in (1e5*(1-5e-13),1e5*(1+5e-13),1e5*(1-9.9e-13),1e5*(1+9.9e-13)):
            c,_=self.stack((4e4,6e4),declared,1e5)
            edge=c.layer_edges_m[-1]; shallower,deeper=sorted((declared,edge))
            self.assertEqual(edge,1e5)
            self.assertGreater(deeper-shallower,1000*math.ulp(deeper))
            for end in (shallower,shallower+(deeper-shallower)/2,math.nextafter(deeper,0.)):
                with self.subTest(declared=declared,end=end),self.assertRaises(GeologyError):
                    case(**self.stack((4e4,6e4),declared,end)[1])
            with self.subTest(declared=declared,end=deeper):
                s=state(case(**self.stack((4e4,6e4),declared,deeper)[1]))
                self.assertEqual(s.units[-1].bottom_depth_m,edge)

    def test_table_short_of_a_three_layer_running_sum_is_refused_at_stage_4(self):
        # 0.1 m + 0.2 m + 0.3 m: the declared 0.6 m is the correctly rounded layer sum, yet
        # the edges, added one layer at a time, end one rounding unit deeper. A table
        # ending at the declared thickness does not reach them.
        c,changes=self.stack((.1,.2,.3),.6,.6)
        self.assertEqual(c.lithosphere_thickness_m,math.fsum((.1,.2,.3)))
        self.assertEqual(c.layer_edges_m[-1],math.nextafter(.6,1.))
        with self.assertRaises(GeologyError): case(**changes)
        c,changes=self.stack((.1,.2,.3),.6,c.layer_edges_m[-1])
        self.assertEqual(state(case(**changes)).units[-1].bottom_depth_m,c.layer_edges_m[-1])

    def test_body_refusal_names_its_unit(self):
        p=ThermalInitialProfile('initial','fixture','tabulated',depths_m=(0.,30.),temperatures_k=(300.,900.))
        b=SubsurfaceBody('deep-slab','mantle',SurfaceSelector('domain'),30.,50.,layer('slab-mantle',20.,'lithospheric_mantle'),
                         'initial','fixture')
        with self.assertRaises(GeologyError) as refused:
            state(case(thermal_profiles=(p,)),bodies=(b,),body_order=('deep-slab',))
        for name in ('body','deep-slab','slab-mantle'):
            self.assertIn(name,str(refused.exception))

    def test_body_table_must_reach_its_base_exactly_at_stage_5(self):
        # PrecursorState compares exactly: the stack tolerance never excuses a short table.
        b=SubsurfaceBody('deep-slab','mantle',SurfaceSelector('domain'),30.,50.,layer('slab-mantle',20.,'lithospheric_mantle'),
                         'initial','fixture')
        for end,reaches in ((50.,True),(math.nextafter(50.,0.),False),(50.*(1-5e-13),False)):
            p=ThermalInitialProfile('initial','fixture','tabulated',depths_m=(0.,end),temperatures_k=(300.,900.))
            c=case(thermal_profiles=(p,))  # stage 4 accepts each: the 30 m column is covered
            with self.subTest(end=end):
                if reaches:
                    self.assertEqual(state(c,bodies=(b,),body_order=('deep-slab',)).units[-1].bottom_depth_m,50.)
                else:
                    with self.assertRaises(GeologyError): state(c,bodies=(b,),body_order=('deep-slab',))


class PriorContracts(unittest.TestCase):
    def prior(self, **changes):
        d=dict(name='declared-fabric',seed=42,mean=10.,amplitude=3.,wavelengths_m=(5.,30.,200.),
               origin_m=(0.,0.,0.),domain_id=case().topology.domain_id,frame_id=FRAME)
        d.update(changes)
        return SeededSpatialPrior(**d)

    def test_batching_order_and_refinement_do_not_redraw_world(self):
        p=self.prior(); points=np.random.default_rng(22).uniform(0.,10.,(137,3))
        a=p.evaluate(points,batch_points=1); b=p.evaluate(points,batch_points=31)
        np.testing.assert_array_equal(a,b)
        np.testing.assert_array_equal(a[::-1],p.evaluate(points[::-1]))
        np.testing.assert_array_equal(a[::3],p.evaluate(points[::3]))
        self.assertTrue(np.all(np.abs(a-p.mean)<=p.amplitude))

    def test_seed_scales_origin_and_domain_change_identity(self):
        p=self.prior()
        for changes in ({'seed':43},{'wavelengths_m':(6.,)}, {'origin_m':(1.,0.,0.)},{'domain_id':'f'*64}):
            with self.subTest(changes=changes): self.assertNotEqual(p.prior_id,replace(p,**changes).prior_id)

    def test_invalid_seeds_scales_and_envelopes_refused(self):
        for changes in ({'seed':True},{'seed':-1},{'seed':2**64},{'amplitude':-1.},
                        {'wavelengths_m':()},{'wavelengths_m':(0.,)}, {'mean':1e308,'amplitude':1e308}):
            with self.subTest(changes=changes),self.assertRaises(TectonicsError): self.prior(**changes)

    def test_prior_values_immutable_owned(self):
        a=self.prior().evaluate([[1.,2.,3.]])
        with self.assertRaises(ValueError): a.setflags(write=True)

    def test_unresolved_phase_refused_without_aliasing(self):
        with self.assertRaises(GeologyError): self.prior(wavelengths_m=(1e-100,)).evaluate([[1.,2.,3.]])

    def test_prior_budget_and_cancel(self):
        with self.assertRaises(MemoryLimitError): self.prior().evaluate([[1,2,3]],budget=WorkBudget(1))
        e=threading.Event(); e.set()
        with self.assertRaises(CancelledError): self.prior().evaluate([[1,2,3]],cancel=e)

    def test_exact_prior_source_binding(self):
        p=self.prior(); src=GeologySource('prior','generated','Named synthetic precursor assumption, not evolution.')
        c=case(sources=(SOURCE,src))
        f=InitialScalarField('temperature-offset','temperature_offset','K','prior','Declared deterministic mode field.',prior=p)
        origins=(InputOrigin('fixture','authored','test'),InputOrigin('prior','sampled_prior',p.prior_id))
        s=state(c,origins=origins,fields=(f,))
        self.assertEqual(s.fields[0].prior.prior_id,p.prior_id)
        with self.assertRaises(GeologyError): state(c,origins=origins,fields=(replace(f,prior=replace(p,seed=43)),))
        with self.assertRaises(GeologyError): state(c,origins=origins,fields=())

    def test_field_prior_wrong_domain_or_frame_refused(self):
        src=GeologySource('prior','generated','Named synthetic assumption.')
        for kwargs in ({'domain_id':'a'*64},{'frame_id':'another-frame'}):
            p=self.prior(**kwargs)
            f=InitialScalarField('f','stress','Pa','prior','sigma_xx',prior=p)
            with self.subTest(kwargs=kwargs),self.assertRaises(GeologyError):
                state(case(sources=(SOURCE,src)),fields=(f,),origins=(InputOrigin('fixture','authored','test'),InputOrigin('prior','sampled_prior',p.prior_id)))


class SourcedMaterialContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library=earth_material_library()
        cls.definitions,cls.sources=cls.library.definitions(('mineral.quartz',))

    def make_sourced(self, **changes):
        m=self.definitions[0]
        c=case(materials=self.definitions,sources=(SOURCE,*self.sources),
            cohorts=(CohortDescription(MaterialCohort('old',m.material_id,'authored-province',-100.),'fixture'),))
        args=dict(material_bases=(),library=self.library)
        args.update(changes)
        return state(c,**args)

    def test_sourced_profile_autobinds_without_per_cell_property_entry(self):
        s=self.make_sourced()
        self.assertEqual(s.material_bases[0].basis,self.library['mineral.quartz'].basis)
        self.assertEqual(s.library.library_id,self.library.library_id)

    def test_library_dependency_cannot_be_omitted(self):
        with self.assertRaises(GeologyError): self.make_sourced(library=None)

    def test_changed_reference_not_silently_rebound(self):
        m=replace(self.definitions[0],density_kg_m3=self.definitions[0].density_kg_m3+1)
        c=case(materials=(m,),sources=(SOURCE,*self.sources),
            cohorts=(CohortDescription(MaterialCohort('old',m.material_id,'authored-province',-100.),'fixture'),))
        with self.assertRaises(GeologyError): state(c,material_bases=(),library=self.library)

    def test_hot_reference_mass_refused(self):
        s=self.make_sourced()
        self.assertEqual(s.require_reference_densities(293.15),293.15)
        with self.assertRaises(GeologyError): s.require_reference_densities(1000.)

    def test_density_basis_cannot_be_overridden(self):
        m=self.definitions[0]
        wrong='bulk_reference' if self.library['mineral.quartz'].basis=='grain' else 'grain'
        with self.assertRaises(GeologyError): self.make_sourced(material_bases=(MaterialVolumeBasis(m.material_id,wrong,m.source_id),))
