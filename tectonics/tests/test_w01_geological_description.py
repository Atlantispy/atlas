"""Stage 4 contract tests: declarative geology on verified geometry, not W03.

Synthetic properties only. Existing fixtures/tolerances are not modified. Tests
separate schema consistency from unperformed sampling and physical calibration.
"""
from concurrent.futures import ThreadPoolExecutor, CancelledError
from dataclasses import FrozenInstanceError, replace
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import pickle
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np
from atlas_tectonics import (GeologyError, GeologySource, MaterialDefinition,
    CohortDescription, ThermalInitialProfile, LayerComponent, GeologicalLayer,
    ColumnDescription, SurfaceSelector, GeologicalProvince, FaultDescription,
    WeakZoneDescription, FeaturePrecedence, GeologyLimits, FeatureGeometry,
    GeologicalCase, save_geological_case, load_geological_case,
    MaterialCohort, PlanarGeometry, SphericalGeometry, SphericalChart,
    SphericalFrame, BoundaryRegion, build_boundary_network, PlanetPartitionSettings,
    generate_planetary_partition, GeometryLimits, TectonicsError)
from atlas_tectonics.geological_case import _snapshot, restore_geological_case
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits, StoreError
from atlas_tectonics.reuse import ExecutionContext

SOURCE = GeologySource('synthetic','synthetic','Synthetic case; no Earth calibration.')
ROCK = MaterialDefinition('rock','solid','synthetic',3000.,3.,1000.,0.,3e-5,300.,(0.,2000.))
WATER = MaterialDefinition('water','fluid','synthetic',1000.,.6,4000.,0.,0.,300.)
COHORT = CohortDescription(MaterialCohort('old','rock','origin-old',-100.),'synthetic')
YOUNG = CohortDescription(MaterialCohort('young','rock','origin-young',0.),'synthetic')
TEMP = ThermalInitialProfile('initial','synthetic','constant',temperatures_k=(300.,))


def layer(name='crust', role='crust', thickness=10., porosity=0., components=None):
    return GeologicalLayer(name,role,thickness,components or (LayerComponent('old',1.),),porosity,'synthetic',
                           'not measured' if porosity is None else None)


def column(name='continental', layers=None, profile='initial', **kw):
    ls = (layer(),layer('mantle','lithospheric_mantle',20.)) if layers is None else layers
    return ColumnDescription(name,'continental',ls,math.fsum(x.bulk_thickness_m for x in ls),profile,'synthetic',**kw)


def regional():
    domain = PlanarGeometry.polygon([(0,0),(10,0),(10,10),(0,10)],frame_id='test-frame')
    left = PlanarGeometry.polygon([(0,0),(5,0),(5,10),(0,10)],frame_id='test-frame')
    right = PlanarGeometry.polygon([(5,0),(10,0),(10,10),(5,10)],frame_id='test-frame')
    return build_boundary_network(domain,(BoundaryRegion('left','p1',left),BoundaryRegion('right','p2',right)))


def ingredients(topology=None):
    return dict(case_id='initial-test',topology=regional() if topology is None else topology,
        time_s=0.,epoch_id='test-epoch',depth_reference_id='local-surface',source_id='synthetic',
        sources=(SOURCE,),materials=(ROCK,),cohorts=(COHORT,),thermal_profiles=(TEMP,),
        columns=(column(),),provinces=(GeologicalProvince('background','continental',SurfaceSelector('domain'),'synthetic'),),
        precedence=FeaturePrecedence(('background',)))


def make(topology=None, **changes):
    d = ingredients(topology); d.update(changes)
    return GeologicalCase(**d)


def rich(topology=None):
    d=ingredients(topology)
    if type(d['topology']) is not type(regional()):
        s=d['topology'].sphere; chart=SphericalChart(s,(1,0,0))
        trace=SphericalGeometry.polyline([(1,-.1,0),(1,.1,0)],chart=chart)
        patch=SphericalGeometry.polygon([(1,-.2,-.2),(1,.2,-.2),(1,.2,.2),(1,-.2,.2)],chart=chart)
    else:
        trace=PlanarGeometry.polyline([(1,1),(4,4)],frame_id='test-frame')
        patch=PlanarGeometry.polygon([(1,1),(4,1),(4,4),(1,4)],frame_id='test-frame')
    d.update(geometries=(FeatureGeometry('trace',trace,'synthetic'),FeatureGeometry('patch',patch,'synthetic')),
        columns=(column(),column('other')),
        provinces=(d['provinces'][0],GeologicalProvince('island','other',SurfaceSelector('geometry',('patch',)),'synthetic')),
        faults=(FaultDescription('fault',('trace',),0.,20.,math.pi/4,'right','synthetic'),),
        weak_zones=(WeakZoneDescription('zone',SurfaceSelector('geometry',('trace',)),0.,20.,.1,.5,'synthetic'),),
        precedence=FeaturePrecedence(('island','background')))
    return GeologicalCase(**d)


class RecordContracts(unittest.TestCase):
    def test_explicit_si_values_no_earth_defaults(self):
        with self.assertRaises(TypeError): MaterialDefinition('x','solid','synthetic')
        with self.assertRaises(TypeError): GeologicalLayer('x','crust',1.)
        self.assertEqual(ROCK.density_kg_m3,3000.)

    def test_frozen_records(self):
        for item,key in ((ROCK,'density_kg_m3'),(TEMP,'mode'),(COHORT,'source_id'),(SOURCE,'kind')):
            with self.assertRaises(FrozenInstanceError): setattr(item,key,None)

    def test_evidence_classification_and_reference(self):
        with self.assertRaises(GeologyError): GeologySource('x','literature','claim')
        src=GeologySource('x','literature','supplied reference, not authentication',('doi:example',),'a'*64)
        self.assertEqual(src.content_sha256,'a'*64)
        with self.assertRaises(GeologyError): replace(src,content_sha256='invalid')

    def test_source_invalid_values(self):
        for change in ({'source_id':''},{'kind':'canon'},{'statement':' '},{'references':['x']},{'references':('x','x')}):
            with self.subTest(change=change), self.assertRaises(TectonicsError): replace(SOURCE,**change)

    def test_nonfinite_boolean_and_negative_properties(self):
        for value in (True,float('nan'),float('inf'),0.,-1.):
            with self.subTest(value=value),self.assertRaises(TectonicsError): replace(ROCK,density_kg_m3=value)
        with self.assertRaises(TectonicsError): replace(ROCK,heat_production_w_m3=-1.)

    def test_material_unknowns_require_reason(self):
        with self.assertRaises(TectonicsError): replace(ROCK,conductivity_w_m_k=None)
        m=replace(ROCK,conductivity_w_m_k=None,unknown_reason='not supplied')
        self.assertIsNone(m.conductivity_w_m_k)
        with self.assertRaises(TectonicsError): replace(ROCK,unknown_reason='contradiction')

    def test_reference_properties_and_validity_range(self):
        for changes in ({'valid_temperature_k':(500.,1000.)},{'valid_temperature_k':(1.,0.)},
                        {'valid_temperature_k':[0,2000]},{'density_kg_m3':None,'unknown_reason':'unknown'}):
            with self.subTest(changes=changes),self.assertRaises(TectonicsError): replace(ROCK,**changes)

    def test_negative_expansion_is_not_clipped(self):
        self.assertEqual(replace(ROCK,thermal_expansion_per_k=-1e-6).thermal_expansion_per_k,-1e-6)

    def test_components_are_solid_volume_not_mass(self):
        l=layer(components=(LayerComponent('young',.75),LayerComponent('old',.25)),porosity=.2)
        self.assertEqual(tuple(x.cohort_id for x in l.components),('old','young'))
        self.assertEqual(l.components[0].solid_volume_fraction,.25)

    def test_invalid_component_totals_and_ids(self):
        for components in ((LayerComponent('old',.9),),(LayerComponent('old',.5),LayerComponent('old',.5))):
            with self.assertRaises(GeologyError): layer(components=components)
        for value in (0,1.1,True,float('nan')):
            with self.assertRaises(TectonicsError): LayerComponent('old',value)

    def test_fraction_validation_never_normalises(self):
        value=1.-5e-13
        self.assertEqual(layer(components=(LayerComponent('old',value),)).components[0].solid_volume_fraction,value)

    def test_porosity_is_explicit(self):
        self.assertIsNone(layer(porosity=None).porosity)
        with self.assertRaises(TectonicsError): replace(layer(),porosity=None)
        for value in (1.,-1.,True):
            with self.assertRaises(TectonicsError): layer(porosity=value)

    def test_layers_are_ordered_and_unique(self):
        with self.assertRaises(TectonicsError): column(layers=(layer('m','lithospheric_mantle'),layer()))
        with self.assertRaises(TectonicsError): column(layers=(layer(),layer()))
        with self.assertRaises(TectonicsError): column(layers=(layer('m','lithospheric_mantle'),))

    def test_crust_and_lithosphere_are_distinct(self):
        c=column(layers=(layer('s','sediment',2),layer('c','crust',8),layer('m','lithospheric_mantle',20)))
        self.assertEqual(c.crust_thickness_m,10.)
        self.assertEqual(c.lithosphere_thickness_m,30.)
        self.assertEqual(c.layer_edges_m,(0.,2.,10.,30.))

    def test_thickness_mismatch_overflow_and_unresolved_layers(self):
        with self.assertRaises(TectonicsError): replace(column(),lithosphere_thickness_m=99.)
        with self.assertRaises(TectonicsError): ColumnDescription('overflow','continental',(layer(thickness=1e308),layer('m','lithospheric_mantle',1e308)),1e308,'initial','synthetic')
        with self.assertRaises(TectonicsError): column(layers=(layer(thickness=1e20),layer('m','lithospheric_mantle',1e-10)))

    def test_nonzero_porosity_needs_a_fluid(self):
        with self.assertRaises(TectonicsError): column(layers=(layer(porosity=.2),))
        self.assertEqual(column(layers=(layer(porosity=.2),),fluid_material_id='water').fluid_material_id,'water')

    def test_half_space_is_separate_from_formation_age(self):
        t=ThermalInitialProfile('t','synthetic','half_space',temperatures_k=(300.,1300.),diffusivity_m2_s=1e-6,cooling_start_time_s=-20.)
        c=make(thermal_profiles=(t,),columns=(column(profile='t'),))
        self.assertEqual(c.cohorts[0].cohort.formation_time_s,-100.)
        self.assertEqual(c.thermal_profiles[0].cooling_start_time_s,-20.)

    def test_unknown_thermal_rejects_guessed_numbers(self):
        t=ThermalInitialProfile('t','synthetic','unknown',unknown_reason='no initial data')
        with self.assertRaises(TectonicsError): replace(t,temperatures_k=(300.,))
        with self.assertRaises(TectonicsError): replace(t,unknown_reason=None)

    def test_table_depths_and_interpolation_are_declared(self):
        t=ThermalInitialProfile('t','synthetic','tabulated',depths_m=(0.,10.,30.),temperatures_k=(300.,1000.,700.))
        self.assertEqual(t.temperatures_k[-1],700.) # nonmonotonic temperatures are not repaired
        for changes in ({'depths_m':(1.,10.,30.)},{'depths_m':(0.,10.,10.)},{'temperatures_k':(300.,)},
                        {'extrapolation':'constant'},{'interpolation':'nearest'}):
            with self.subTest(changes=changes),self.assertRaises(TectonicsError):replace(t,**changes)

    def test_known_profile_rejects_unrelated_payload(self):
        for changes in ({'depths_m':(0.,)},{'temperatures_k':(300.,400.)},{'diffusivity_m2_s':1.},
                        {'cooling_start_time_s':0.},{'unknown_reason':'unknown'}):
            with self.assertRaises(TectonicsError):replace(TEMP,**changes)

    def test_fault_has_directed_dip_not_displacement(self):
        f=FaultDescription('f',('trace',),0.,10.,math.pi/2,'left','synthetic')
        self.assertEqual(f.dip_rad,math.pi/2)
        for changes in ({'dip_rad':0.},{'dip_rad':2.},{'dip_side':'north'},{'bottom_depth_m':0.},{'trace_keys':()}):
            with self.assertRaises(TectonicsError):replace(f,**changes)

    def test_weakness_unknowns_and_bounds(self):
        z=WeakZoneDescription('w',SurfaceSelector('domain'),0.,10.,None,None,'synthetic','unknown strength')
        self.assertIsNone(z.strength_factor)
        for changes in ({'strength_factor':0.},{'strength_factor':2.},{'half_width_m':0.}):
            with self.assertRaises(TectonicsError):replace(z,**changes)

    def test_selector_validation_and_canonical_keys(self):
        self.assertEqual(SurfaceSelector('plates',('b','a')).keys,('a','b'))
        for args in (('domain',('a',)),('plates',()),('geometry',('a','a')),('unknown',())):
            with self.assertRaises(TectonicsError):SurfaceSelector(*args)

    def test_precedence_not_file_order(self):
        with self.assertRaises(TectonicsError):FeaturePrecedence(('a','a'))
        with self.assertRaises(TectonicsError):FeaturePrecedence(('a',),'retain_all',('w',))


class CaseAssembly(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.top=regional()

    def test_complete_known_case(self):
        c=make(self.top)
        self.assertEqual(c.unresolved,())
        self.assertEqual(c.column('continental').crust_thickness_m,10.)

    def test_case_immutable_and_descriptor_detached(self):
        c=rich(self.top); d=c.descriptor();d['materials'][0]['density_kg_m3']=0
        self.assertEqual(c.materials[0].density_kg_m3,3000.)
        with self.assertRaises(FrozenInstanceError):c.case_id='change'
        with self.assertRaises(TypeError):c._lookups['columns']['fake']=c.columns[0]
        self.assertIs(copy.deepcopy(c),c)

    def test_catalogue_order_is_not_identity(self):
        a=rich(self.top);d=ingredients(self.top)
        for name in ('materials','sources','cohorts','columns','thermal_profiles','provinces','geometries','faults','weak_zones'):
            d[name]=tuple(reversed(getattr(a,name)))
        d['precedence']=a.precedence
        self.assertEqual(GeologicalCase(**d).definition_id,a.definition_id)

    def test_province_order_is_identity(self):
        d=ingredients(self.top);d['columns']=(column(),column('other'))
        d['provinces']+=(GeologicalProvince('one','other',SurfaceSelector('plates',('p1',)),'synthetic'),GeologicalProvince('two','continental',SurfaceSelector('regions',('left',)),'synthetic'))
        d['precedence']=FeaturePrecedence(('one','two','background'));a=GeologicalCase(**d)
        d['precedence']=FeaturePrecedence(('two','one','background'));b=GeologicalCase(**d)
        self.assertNotEqual(a.definition_id,b.definition_id)
        self.assertEqual(a.resolve_provinces(('two','one')).province_id,'one')
        self.assertEqual(b.resolve_provinces(('one','two')).province_id,'two')

    def test_background_is_explicit(self):
        with self.assertRaises(TectonicsError):make(self.top,provinces=())
        p=GeologicalProvince('local','continental',SurfaceSelector('plates',('p1',)),'synthetic')
        with self.assertRaises(TectonicsError):make(self.top,provinces=(p,),precedence=FeaturePrecedence(('local',)))
        self.assertEqual(make(self.top).resolve_provinces(()).province_id,'background')

    def test_incomplete_or_bad_precedence_refused(self):
        a=rich(self.top)
        for order in (('background',),('background','island'),('island','absent','background')):
            d=ingredients(self.top)
            for name in ('columns','provinces','geometries'):d[name]=getattr(a,name)
            d['precedence']=FeaturePrecedence(order)
            with self.assertRaises(TectonicsError):GeologicalCase(**d)

    def test_missing_catalogue_references_refused(self):
        changes=[{'source_id':'absent'},{'columns':(replace(column(),source_id='absent'),)},
                 {'cohorts':(replace(COHORT,cohort=replace(COHORT.cohort,material_id='absent')), )},
                 {'columns':(column(profile='absent'),)},
                 {'columns':(column(layers=(layer(components=(LayerComponent('absent',1),)),)),)}]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(TectonicsError):make(self.top,**change)

    def test_duplicate_catalogue_ids_refused(self):
        for key,value in (('sources',SOURCE),('materials',ROCK),('cohorts',COHORT),('thermal_profiles',TEMP),('columns',column())):
            with self.subTest(key=key),self.assertRaises(TectonicsError):make(self.top,**{key:(value,value)})

    def test_formation_cannot_be_in_future(self):
        with self.assertRaises(TectonicsError):make(self.top,cohorts=(replace(COHORT,cohort=replace(COHORT.cohort,formation_time_s=1.)),))

    def test_cooling_start_cannot_be_in_future(self):
        p=ThermalInitialProfile('initial','synthetic','half_space',temperatures_k=(300.,1000.),diffusivity_m2_s=1.,cooling_start_time_s=1.)
        with self.assertRaises(TectonicsError):make(self.top,thermal_profiles=(p,))

    def test_unknown_values_are_listed_not_filled(self):
        m=replace(ROCK,conductivity_w_m_k=None,unknown_reason='unknown conductivity')
        t=ThermalInitialProfile('initial','synthetic','unknown',unknown_reason='unmeasured')
        co=replace(COHORT,cohort=replace(COHORT.cohort,formation_time_s=None))
        c=make(self.top,materials=(m,),cohorts=(co,),thermal_profiles=(t,),columns=(replace(column(layers=(layer(porosity=None),)),crust_type='unknown'),))
        self.assertEqual(len(c.unresolved),5)
        self.assertIsNone(c.cohorts[0].cohort.formation_time_s)
        self.assertIsNone(c.materials[0].conductivity_w_m_k)

    def test_profile_must_cover_full_column(self):
        t=ThermalInitialProfile('initial','synthetic','tabulated',depths_m=(0.,10.),temperatures_k=(300.,900.))
        with self.assertRaises(TectonicsError):make(self.top,thermal_profiles=(t,))

    def test_pore_fluid_cannot_be_solid_or_a_cohort(self):
        c=column(layers=(layer(porosity=.1),),fluid_material_id='rock')
        with self.assertRaises(TectonicsError):make(self.top,columns=(c,))
        with self.assertRaises(TectonicsError):make(self.top,materials=(replace(ROCK,material_class='fluid'),))
        c=replace(c,fluid_material_id='water')
        self.assertEqual(make(self.top,columns=(c,),materials=(ROCK,WATER)).columns[0].fluid_material_id,'water')

    def test_constant_temperature_validity(self):
        with self.assertRaises(TectonicsError):make(self.top,thermal_profiles=(replace(TEMP,temperatures_k=(3000.,)),))

    def test_frame_mismatch_and_outside_geometry(self):
        for frame,points in [('wrong',[(1,1),(2,1),(2,2),(1,2)]),('test-frame',[(9,9),(11,9),(11,11),(9,11)])]:
            g=PlanarGeometry.polygon(points,frame_id=frame)
            with self.assertRaises(TectonicsError):make(self.top,geometries=(FeatureGeometry('g',g,'synthetic'),))

    def test_province_geometry_must_be_area(self):
        g=PlanarGeometry.polyline([(1,1),(2,2)],frame_id='test-frame')
        p=GeologicalProvince('p','continental',SurfaceSelector('geometry',('line',)),'synthetic')
        with self.assertRaises(TectonicsError):make(self.top,geometries=(FeatureGeometry('line',g,'synthetic'),),provinces=ingredients(self.top)['provinces']+(p,),precedence=FeaturePrecedence(('p','background')))

    def test_unknown_plate_region_and_geometry_refs(self):
        for kind in ('plates','regions','geometry'):
            p=GeologicalProvince('p','continental',SurfaceSelector(kind,('absent',)),'synthetic')
            with self.assertRaises(TectonicsError):make(self.top,provinces=ingredients(self.top)['provinces']+(p,),precedence=FeaturePrecedence(('p','background')))

    def test_fault_trace_validation(self):
        g=PlanarGeometry.polygon([(1,1),(2,1),(2,2),(1,2)],frame_id='test-frame')
        f=FaultDescription('f',('g',),0,10,1,'right','synthetic')
        with self.assertRaises(TectonicsError):make(self.top,geometries=(FeatureGeometry('g',g,'synthetic'),),faults=(f,))

    def test_corridor_is_declared_without_polygon_buffer(self):
        c=rich(self.top)
        self.assertEqual(c.weak_zones[0].half_width_m,.1)
        self.assertEqual(c._lookups['geometries']['trace'].geometry.kind,'LineString')

    def test_weak_zone_width_and_geometry_consistent(self):
        c=rich(self.top);d=ingredients(self.top);d['geometries']=c.geometries
        for zone in (replace(c.weak_zones[0],half_width_m=None),replace(c.weak_zones[0],selector=SurfaceSelector('geometry',('patch',)))):
            with self.assertRaises(TectonicsError):make(self.top,geometries=c.geometries,weak_zones=(zone,))

    def test_weak_zone_overlap_is_not_implicitly_multiplied(self):
        z=WeakZoneDescription('a',SurfaceSelector('domain'),0,30,None,.5,'synthetic')
        b=replace(z,zone_id='b',strength_factor=.2)
        c=make(self.top,weak_zones=(z,b))
        self.assertEqual(c.resolve_weak_zones(('b','a')),('a','b'))
        d=make(self.top,weak_zones=(z,b),precedence=FeaturePrecedence(('background',),'ordered_override',('b','a')))
        self.assertEqual(d.resolve_weak_zones(('a','b')),('b',))

    def test_invalid_candidate_ids_refused(self):
        c=make(self.top)
        for call in (lambda:c.resolve_provinces(('no',)),lambda:c.resolve_weak_zones(('no',)),lambda:c.column('no')):
            with self.assertRaises(TectonicsError):call()

    def test_density_evidence_geometry_epoch_change_identity(self):
        base=make(self.top)
        for changes in ({'materials':(replace(ROCK,density_kg_m3=2900.),)}, {'time_s':2.}, {'epoch_id':'other'},
                        {'sources':(replace(SOURCE,statement='Different declared evidence'),)}, {'depth_reference_id':'different-surface'}):
            self.assertNotEqual(make(self.top,**changes).definition_id,base.definition_id)

    def test_bounds_before_building_maps(self):
        with self.assertRaises(TectonicsError):make(self.top,limits=GeologyLimits(max_records=2))
        with self.assertRaises(TectonicsError):make(self.top,limits=GeologyLimits(max_definition_bytes=64))
        with self.assertRaises(TectonicsError):make(self.top,thermal_profiles=(ThermalInitialProfile('initial','synthetic','tabulated',depths_m=(0,10,30),temperatures_k=(300,600,900)),),limits=GeologyLimits(max_profile_points=2))

    def test_memory_and_cancellation_refusal(self):
        b=WorkBudget(8)
        with self.assertRaises(MemoryLimitError):make(self.top,budget=b)
        self.assertEqual(b.reserved_bytes,0)
        c=threading.Event();c.set()
        with self.assertRaises(CancelledError):make(self.top,cancel=c)

    def test_thread_reads_are_stable(self):
        c=rich(self.top)
        with ThreadPoolExecutor(4) as pool:
            results=list(pool.map(lambda _:c.resolve_provinces(('island',)),range(32)))
        self.assertEqual(len(set(results)),1)

    def test_no_spatial_sampling_or_evolution_during_construction(self):
        with mock.patch('atlas_tectonics.thermal.half_space_temperature',side_effect=AssertionError('evolution')), \
             mock.patch('atlas_tectonics.materials.advect_materials',side_effect=AssertionError('transport')), \
             mock.patch('atlas_tectonics.geometry.PlanarGeometry.classify',side_effect=AssertionError('sampling')):
            c=rich(self.top)
        self.assertEqual(c.resolve_provinces(('island',)).column_id,'other')

    def test_definition_is_compact_not_cell_sized(self):
        c=make(self.top)
        self.assertLess(c.definition_bytes,8192)
        self.assertNotIn('cells',c.descriptor())


class PlanetaryDescriptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.atlas=generate_planetary_partition(SphericalFrame(2.,'test-planet'),PlanetPartitionSettings(4,22))

    def test_generated_planet_accepts_case(self):
        c=make(self.atlas)
        self.assertEqual(c.descriptor()['topology_id'],self.atlas.atlas_id)
        self.assertEqual(c.topology.descriptor()['source_bindings'],self.atlas.descriptor()['source_bindings'])

    def test_plate_selector_does_not_relabel_crust(self):
        p=GeologicalProvince('oceanic','different',SurfaceSelector('plates',(self.atlas.plate_ids[0],)),'synthetic')
        c=make(self.atlas,columns=(column(),replace(column('different'),crust_type='oceanic')),
            provinces=ingredients(self.atlas)['provinces']+(p,),precedence=FeaturePrecedence(('oceanic','background')))
        self.assertEqual(len(c.topology.plate_ids),4)
        self.assertEqual(c.resolve_provinces(('oceanic',)).column_id,'different')

    def test_spherical_features_and_faults(self):
        c=rich(self.atlas)
        self.assertEqual(c.geometries[0].geometry.chart.sphere,self.atlas.sphere)

    def test_planet_frame_mismatch_refused(self):
        chart=SphericalChart(SphericalFrame(2.,'other'),(1,0,0))
        g=SphericalGeometry.polyline([(1,0,0),(1,.1,0)],chart=chart)
        with self.assertRaises(TectonicsError):make(self.atlas,geometries=(FeatureGeometry('g',g,'synthetic'),))

    def test_geological_region_can_cross_plates(self):
        c=rich(self.atlas)
        self.assertEqual(c.provinces[1].selector.kind,'geometry')
        self.assertEqual(c.topology.atlas_id,self.atlas.atlas_id)


class PersistenceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.case=rich(regional())

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'case.db'
        self.limits=StoreLimits(4096,4<<20,16<<20,8192)
        self.store=ArrayStore(self.path,self.limits)
    def tearDown(self): self.store.close();self.tmp.cleanup()

    def test_self_contained_regional_round_trip(self):
        c=self.case;save_geological_case(c,self.store);r=load_geological_case(self.store,c.definition_id)
        self.assertEqual(r.definition_id,c.definition_id);self.assertEqual(r.descriptor(),c.descriptor())
        self.assertEqual(r.topology.network_id,c.topology.network_id)

    def test_self_contained_planet_round_trip(self):
        a=generate_planetary_partition(SphericalFrame(2.,'test-planet'),PlanetPartitionSettings(4,22))
        c=rich(a);save_geological_case(c,self.store);r=load_geological_case(self.store,c.definition_id)
        self.assertEqual(r.topology.descriptor(),a.descriptor());self.assertEqual(r.definition_id,c.definition_id)

    def test_unknowns_survive_restore(self):
        c=make(thermal_profiles=(ThermalInitialProfile('initial','synthetic','unknown',unknown_reason='not observed'),))
        save_geological_case(c,self.store);r=load_geological_case(self.store,c.definition_id)
        self.assertEqual(r.unresolved,c.unresolved)

    def test_snapshot_deduplicates_identical_geometry(self):
        c=self.case;save_geological_case(c,self.store);count=self.store.statistics()['unique_chunks']
        d=ingredients(c.topology)
        for name in ('columns','geometries','provinces','faults','weak_zones','precedence'):d[name]=getattr(c,name)
        d['case_id']='another-interpretation'
        other=GeologicalCase(**d);save_geological_case(other,self.store)
        self.assertGreaterEqual(self.store.statistics()['unique_chunks'],count)
        self.assertEqual(self.store.statistics()['snapshots'],2)
        before=self.store._manifest(c.definition_id)['arrays']
        after=self.store._manifest(other.definition_id)['arrays']
        for key in before:
            if key != 'definition': self.assertEqual(before[key]['chunks'],after[key]['chunks'])

    def test_payload_is_shared_across_two_geometry_names(self):
        c=self.case;g=c.geometries[0]
        d=ingredients(c.topology);d['geometries']=(g,replace(g,key='another-name'))
        x=GeologicalCase(**d);meta,arrays=_snapshot(x)
        self.assertEqual(len(meta['geometries']),len({g.geometry_id for g in (x.topology.domain,*(r.geometry for r in x.topology.regions),g.geometry)}))

    def test_pickle_and_deepcopy_keep_immutability(self):
        c=self.case;r=pickle.loads(pickle.dumps(c))
        self.assertEqual(r.definition_id,c.definition_id)
        with self.assertRaises(FrozenInstanceError):r.columns[0].layers[0].bulk_thickness_m=5
        with self.assertRaises(TypeError):r._lookups['sources']['x']=SOURCE
        self.assertIs(copy.deepcopy(c),c)

    def test_absent_is_none_not_regenerated(self):
        self.assertIsNone(load_geological_case(self.store,'0'*64))

    def test_corruption_refused(self):
        save_geological_case(self.case,self.store)
        self.store._db.execute('UPDATE chunks SET payload=? WHERE id=(SELECT id FROM chunks LIMIT 1)',(b'corrupt',))
        with self.assertRaises((TectonicsError,StoreError)):load_geological_case(self.store,self.case.definition_id)

    def test_missing_dependency_refused(self):
        meta,arrays=_snapshot(self.case);arrays.pop(next(iter(arrays)))
        with self.assertRaises(TectonicsError):restore_geological_case(meta,arrays,self.case.definition_id)

    def test_unexpected_payload_refused(self):
        meta,arrays=_snapshot(self.case);arrays['extra']=np.ones(3)
        with self.assertRaises(TectonicsError):restore_geological_case(meta,arrays,self.case.definition_id)

    def test_definition_tampering_refused(self):
        meta,arrays=_snapshot(self.case);raw=json.loads(arrays['definition'].tobytes());raw['time_s']=10.;arrays['definition']=np.frombuffer(json.dumps(raw).encode(),dtype='u1')
        with self.assertRaises(TectonicsError):restore_geological_case(meta,arrays,self.case.definition_id)

    def test_topology_tampering_refused(self):
        meta,arrays=_snapshot(self.case);meta['topology']['network_id']='0'*64
        with self.assertRaises(TectonicsError):restore_geological_case(meta,arrays,self.case.definition_id)

    def test_restore_limit_refusals(self):
        meta,arrays=_snapshot(self.case)
        for limits in (GeologyLimits(max_definition_bytes=64),GeologyLimits(max_geometry_bytes=1),GeologyLimits(max_records=1)):
            with self.subTest(limits=limits),self.assertRaises(TectonicsError):restore_geological_case(meta,arrays,self.case.definition_id,limits=limits)

    def test_cancelled_save_no_snapshot(self):
        event=threading.Event();event.set()
        with self.assertRaises(CancelledError):save_geological_case(self.case,self.store,cancel=event)
        self.assertEqual(self.store.statistics()['snapshots'],0)

    def test_save_failure_has_no_partial_definition(self):
        with mock.patch.object(self.store,'_encode',side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):save_geological_case(self.case,self.store)
        self.assertEqual(self.store.statistics()['snapshots'],0)

    def test_backup_without_original_store(self):
        c=self.case;save_geological_case(c,self.store)
        backup=Path(self.tmp.name)/'backup.db';self.store.backup_to(backup)
        self.store.close();self.path.unlink()
        with ArrayStore(backup,self.limits) as s:
            r=load_geological_case(s,c.definition_id)
        self.assertEqual(r.definition_id,c.definition_id)

    def test_fresh_process_restoration(self):
        c=self.case;save_geological_case(c,self.store)
        code='''import sys\nfrom atlas_tectonics import load_geological_case\nfrom atlas_tectonics.storage import ArrayStore,StoreLimits\nwith ArrayStore(sys.argv[1],StoreLimits(4096,4<<20,16<<20,8192)) as s:\n c=load_geological_case(s,sys.argv[2]);print(c.definition_id)\n'''
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        p=subprocess.run([sys.executable,'-B','-c',code,str(self.path),c.definition_id],env=env,text=True,capture_output=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),c.definition_id)

    def test_concurrent_saves_preserve_one_definition(self):
        with ThreadPoolExecutor(2) as pool:
            out=list(pool.map(lambda _:save_geological_case(self.case,self.store),range(4)))
        self.assertEqual(set(out),{self.case.definition_id})
        self.assertEqual(self.store.statistics()['snapshots'],1)

    def test_identity_context_covers_new_modules(self):
        import atlas_tectonics.geological_records as records
        from atlas_tectonics.reuse import _IDENTITY_MODULES
        self.assertIn('geological_case',_IDENTITY_MODULES);self.assertIn('geological_records',_IDENTITY_MODULES)
        context=ExecutionContext()
        with mock.patch.object(records,'_depths',lambda x:None):
            with self.assertRaises(TectonicsError):context.verify()
        context.verify();context.close()


class AdditionalAcceptance(unittest.TestCase):
    def test_case_fixture_tolerances_match_implementation(self):
        from atlas_tectonics.geological_records import FRACTION_ABSOLUTE_TOLERANCE, STACK_RELATIVE_TOLERANCE
        case=json.loads((Path(__file__).resolve().parents[1]/'cases/w01_geological_description.json').read_text())
        self.assertEqual(case['acceptance']['fraction_absolute_tolerance'],FRACTION_ABSOLUTE_TOLERANCE)
        self.assertEqual(case['acceptance']['stack_relative_tolerance'],STACK_RELATIVE_TOLERANCE)

    def test_mutable_catalogues_are_rejected(self):
        with self.assertRaises(TectonicsError):make(sources=[SOURCE])
        with self.assertRaises(TectonicsError):replace(column(),layers=list(column().layers))
        with self.assertRaises(TectonicsError):replace(TEMP,temperatures_k=[300.])

    def test_reference_error_releases_budget(self):
        budget=WorkBudget(8<<20)
        with self.assertRaises(TectonicsError):make(source_id='missing',budget=budget)
        self.assertEqual(budget.reserved_bytes,0)

    def test_cooling_age_overflow_is_refused(self):
        p=ThermalInitialProfile('initial','synthetic','half_space',temperatures_k=(300.,1300.),diffusivity_m2_s=1.,cooling_start_time_s=-1e308)
        with self.assertRaises(TectonicsError):make(thermal_profiles=(p,),time_s=1e308)

    def test_thermal_future_date_preserves_unknown_formation(self):
        c=replace(COHORT,cohort=replace(COHORT.cohort,formation_time_s=None))
        p=ThermalInitialProfile('initial','synthetic','half_space',temperatures_k=(300.,1300.),diffusivity_m2_s=1.,cooling_start_time_s=0.)
        case=make(cohorts=(c,),thermal_profiles=(p,))
        self.assertIsNone(case.cohorts[0].cohort.formation_time_s)
        self.assertEqual(case.thermal_profiles[0].cooling_start_time_s,0.)

    def test_initial_datasets_are_compressed_not_repeated_metadata(self):
        case=make();meta,arrays=_snapshot(case)
        self.assertNotIn('case',meta)
        self.assertEqual(arrays['definition'].tobytes(),case._definition)
        self.assertEqual(arrays['definition'].dtype,np.dtype('u1'))
        self.assertFalse(arrays['definition'].flags.writeable)

    def test_typed_payload_bad_dtype_is_refused(self):
        c=rich();meta,arrays=_snapshot(c)
        key=next(k for k in arrays if k!='definition')
        arrays[key]=('nonsense',(1,),b'x')
        with self.assertRaises(TectonicsError):restore_geological_case(meta,arrays,c.definition_id)

    def test_limits_include_owned_topology_payload(self):
        with self.assertRaises(TectonicsError):make(limits=GeologyLimits(max_geometry_bytes=1))

    def test_multiple_columns_reuse_one_profile_record(self):
        c=make(columns=(column(),column('second')))
        self.assertEqual(len(c.thermal_profiles),1)
        self.assertEqual({x.thermal_profile_id for x in c.columns},{'initial'})

    def test_unused_snapshot_dependency_is_rejected(self):
        c=make();meta,arrays=_snapshot(c)
        g=PlanarGeometry.polyline([(1,1),(2,2)],frame_id='test-frame')
        meta['geometries'][g.geometry_id]={'array':'extraneous','descriptor':g.descriptor()}
        arrays['extraneous']=np.frombuffer(g.wkb,dtype='u1')
        with self.assertRaises(TectonicsError):restore_geological_case(meta,arrays,c.definition_id)

    def test_spherical_regional_case_round_trip(self):
        sphere=SphericalFrame(1000.,'regional-sphere'); chart=SphericalChart(sphere,(1,0,0))
        geom=SphericalGeometry.polygon([(1,-.2,-.2),(1,.2,-.2),(1,.2,.2),(1,-.2,.2)],chart=chart)
        net=build_boundary_network(geom,(BoundaryRegion('r','p',geom),))
        c=make(net);meta,arrays=_snapshot(c)
        restored=restore_geological_case(meta,arrays,c.definition_id)
        self.assertEqual(restored.definition_id,c.definition_id)

    def test_large_profile_table_limit_before_case_serialisation(self):
        p=ThermalInitialProfile('initial','synthetic','tabulated',depths_m=tuple(float(i) for i in range(64)),temperatures_k=(300.,)*64)
        with self.assertRaises(TectonicsError):make(thermal_profiles=(p,),limits=GeologyLimits(max_profile_points=100))


    def test_precedence_ranks_are_shared_immutable_metadata(self):
        c=rich()
        self.assertEqual(c._province_rank['island'],0)
        with self.assertRaises(TypeError):c._province_rank['island']=2
        r=c.resolve_provinces(('island',))
        self.assertEqual(r.matching_province_ids,('island','background'))

    def test_save_reservation_releases_on_invalid_budget(self):
        c=make();b=WorkBudget(1)
        with tempfile.TemporaryDirectory() as tmp, ArrayStore(Path(tmp)/'g.db',StoreLimits(4096,1<<20,4<<20)) as store:
            with self.assertRaises(MemoryLimitError):save_geological_case(c,store,budget=b)
            self.assertEqual(store.statistics()['snapshots'],0)
        self.assertEqual(b.reserved_bytes,0)


if __name__ == '__main__': unittest.main()
