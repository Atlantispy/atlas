"""W01 4B reference-data transcription, units, mixtures and integration.

Independent numerical examples are calculated from reported source values or exact
fractions, not regenerated from the library. These are reference/contract tests,
NOT evidence of temperature-pressure validity or geological calibration. Existing
science tolerances and fixtures are untouched. Temporary stores only; no network.
"""
from concurrent.futures import ThreadPoolExecutor, CancelledError
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
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
from numpy.testing import assert_allclose, assert_array_equal
from atlas_tectonics import (earth_material_library, EarthMaterialLibrary,
    EarthMaterialProfile, MaterialReferenceSource, PropertyDatum, MaterialLibraryError,
    SedimentMatrixRecipe, PreparedMaterialTable, RadiogenicAssay, mix_materials,
    sediment_matrix, save_material_library, load_material_library,
    resolve_geological_layer, GeologicalCase, GeologySource, MaterialCohort,
    CohortDescription, GeologicalLayer, LayerComponent, ColumnDescription,
    ThermalInitialProfile, GeologicalProvince, SurfaceSelector, FeaturePrecedence,
    save_geological_case, load_geological_case, TectonicsError)
from atlas_tectonics.material_library import (_restore_table, restore_material_library,
    MAX_CATALOGUE_BYTES, PROPERTIES)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits, StoreError
from atlas_tectonics.reuse import ExecutionContext
from test_w01_geological_description import regional

LIB=earth_material_library()
CASE=json.loads((Path(__file__).resolve().parents[1]/"cases/w01_earth_materials.json").read_text())


def canon(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


def synthetic_library():
    source=MaterialReferenceSource('s','Synthetic verification only','https://example.invalid/reference','Not Earth data.')
    def profile(name,rho,cp,k,q):
        data=tuple(PropertyDatum(p,v,u,'s','synthetic independent calculation') for p,v,u in (
            ('density',rho,'kg/m3'),('heat_capacity',cp,'J/kg/K'),
            ('conductivity',k,'W/m/K'),('heat_production',q,'W/m3')))
        return EarthMaterialProfile(name,name,'synthetic','grain',(),data)
    return EarthMaterialLibrary('test', (profile('a',2000.,800.,2.,0.),profile('b',4000.,1000.,8.,4e-6)), (source,))


def earth_case(*, rock='mineral.quartz', porosity=.25, library=LIB):
    ids=(rock,'fluid.fresh_water')
    definitions,refs=library.definitions(ids)
    own=GeologySource('case','authored','Illustrative layer geometry and formation history, not calibration.')
    cohort=CohortDescription(MaterialCohort('old',rock,'origin',-100.),'case')
    layer=GeologicalLayer('bed','crust',10.,(LayerComponent('old',1.),),porosity,'case',
                         'not supplied' if porosity is None else None)
    return GeologicalCase('earth-reference-fixture',regional(),time_s=0.,epoch_id='test',
        depth_reference_id='surface',source_id='case',sources=(own,*refs),materials=definitions,
        cohorts=(cohort,),thermal_profiles=(ThermalInitialProfile('initial','case','constant',temperatures_k=(293.15,)),),
        columns=(ColumnDescription('column','continental',(layer,),10.,'initial','case','fluid.fresh_water'),),
        provinces=(GeologicalProvince('background','column',SurfaceSelector('domain'),'case'),),
        precedence=FeaturePrecedence(('background',)))


class SourceDataTests(unittest.TestCase):
    def test_broad_named_rock_coverage(self):
        required=('granite','granodiorite','rhyolite','diorite','andesite','gabbro','basalt','dolerite',
            'sandstone','siltstone','argillite','aluminous_shale','iron_rich_shale','limestone','dolostone',
            'marl','anhydrite','gypsum','rock_salt','coal','quartzite','marble','slate','phyllite','schist',
            'gneiss','amphibolite','hornfels','serpentinite','soapstone','peridotite','harzburgite','lherzolite','pyroxenite')
        for name in required:self.assertEqual(LIB['rock.'+name].basis,'bulk_reference')
        self.assertEqual(len(LIB.profiles),67)
        self.assertEqual(CASE["expected_profile_count"],67)
        self.assertEqual(CASE["reference_library"],LIB.version)

    def test_minerals_fluids_and_ice(self):
        for name in ('quartz','albite','anorthite','orthoclase','microcline','forsterite','fayalite',
                     'enstatite','diopside','hornblende','illite','smectite','calcite','chlorite','muscovite'):
            self.assertEqual(LIB['mineral.'+name].basis,'grain')
        self.assertEqual(LIB['fluid.fresh_water'].basis,'fluid')
        self.assertEqual(LIB['solid.ice'].datum('density').reference_temperature_k,273.15)

    def test_quartz_original_table3(self):
        q=LIB['mineral.quartz']
        self.assertEqual(q.datum('density').reported_value,2.648)
        self.assertEqual(q.datum('density').value_si,2648.)
        self.assertEqual(q.datum('heat_capacity').value_si,741.)
        self.assertEqual(q.datum('conductivity').value_si,7.69)
        self.assertEqual(q.datum('heat_capacity').source_id,'GOTO2008')

    def test_feldspar_independent_transcription(self):
        for id,rho,cp,k in (('albite',2620.,776.,2.2),('anorthite',2760.,745.,1.68),('orthoclase',2570.,707.,2.32)):
            p=LIB['mineral.'+id]
            assert_allclose([p.datum(x).value_si for x in ('density','heat_capacity','conductivity')],[rho,cp,k],rtol=0,atol=1e-12)

    def test_clay_and_carbonate_transcription(self):
        for id,rho,cp,k in (('illite',2660.,808.,1.85),('smectite',2608.,795.,1.88),('calcite',2710.,820.,3.59)):
            p=LIB['mineral.'+id]
            assert_allclose([p.datum(x).value_si for x in ('density','heat_capacity','conductivity')],[rho,cp,k],rtol=0,atol=1e-12)

    def test_granite_source_bounds_and_selected_midpoint(self):
        p=LIB['rock.granite'];rho=p.datum('density');cp=p.datum('heat_capacity')
        self.assertEqual(rho.bounds_si,(2600.,2700.));self.assertEqual(rho.value_si,2650.)
        self.assertEqual(cp.bounds_si,(600.,950.));self.assertAlmostEqual(cp.value_si,775.)
        self.assertEqual(rho.selection,'midpoint_of_reported_range')
        self.assertIn('not a measured mean',p.note)

    def test_basalt_range_not_one_exact_rock(self):
        p=LIB['rock.basalt']
        self.assertEqual(p.datum('density').bounds_si,(2300.,3000.))
        self.assertEqual(p.datum('conductivity').bounds_si,(1.2,2.3))
        self.assertIsNone(p.datum('heat_production'))

    def test_bulk_mantle_and_metamorphic_references(self):
        expected={'peridotite':(3190.,1005.),'lherzolite':(3200.,778.),'harzburgite':(3200.,759.),
                  'amphibolite':(3010.,700.),'slate':(2770.,1113.)}
        for id,values in expected.items():
            p=LIB['rock.'+id];assert_allclose([p.datum(x).value_si for x in ('density','heat_capacity')],values,rtol=0,atol=1e-12)
        self.assertTrue(LIB['rock.peridotite'].missing('conduction_reference',temperature_k=1573.15))

    def test_dolerite_alias_is_unambiguous(self):
        self.assertEqual([p.material_id for p in LIB.find('DIABASE')],['rock.dolerite'])
        self.assertEqual(LIB.find('imaginary rock'),())
        with self.assertRaises(MaterialLibraryError):LIB['granite']

    def test_source_locations_for_every_value(self):
        source_ids={s.source_id for s in LIB.sources}
        for p in LIB.profiles:
            for d in p.properties:
                self.assertIn(d.source_id,source_ids);self.assertTrue(d.locator)
                self.assertTrue(math.isfinite(d.value_si))
                self.assertLessEqual(d.bounds_si[0],d.value_si);self.assertGreaterEqual(d.bounds_si[1],d.value_si)

    def test_heat_capacity_temperatures_preserved(self):
        self.assertEqual(LIB['mineral.microcline'].datum('heat_capacity').reference_temperature_k,273.15)
        self.assertEqual(LIB['mineral.enstatite'].datum('heat_capacity').reference_temperature_k,333.15)
        self.assertEqual(LIB['mineral.magnetite'].datum('heat_capacity').value_si,600.)
        self.assertTrue(LIB['mineral.microcline'].missing('sensible_heat_reference'))

    def test_expansion_secant_is_not_room_derivative(self):
        q=LIB['mineral.quartz'].datum('thermal_expansion')
        self.assertTrue(q.is_secant);self.assertEqual(q.temperature_span_k,(293.15,673.15))
        self.assertAlmostEqual(q.value_si,4.98e-5)
        self.assertTrue(LIB['mineral.quartz'].missing('instantaneous_buoyancy'))
        self.assertFalse(LIB['mineral.quartz'].missing('expansion_secant'))

    def test_rock_isotropic_secant_conversion(self):
        d=LIB['rock.granite'].datum('thermal_expansion')
        self.assertEqual(d.temperature_span_k,(293.15,373.15))
        self.assertAlmostEqual(d.value_si,24e-6)
        self.assertEqual(d.selection,'isotropic_interval_secant')
        assert_allclose(d.bounds_si,(15e-6,33e-6),rtol=1e-15)

    def test_radiogenic_populations_distinct(self):
        a=LIB['rock.aluminous_shale'].datum('heat_production')
        b=LIB['rock.iron_rich_shale'].datum('heat_production')
        self.assertAlmostEqual(a.value_si,2.9e-6);self.assertAlmostEqual(b.value_si,1.7e-6)
        self.assertEqual(a.selection,'population_representative')

    def test_water_and_seawater_not_same_profile(self):
        fresh=LIB['fluid.fresh_water'];salt=LIB['fluid.seawater']
        self.assertEqual(fresh.datum('density').value_si,998.2)
        self.assertEqual(fresh.datum('heat_capacity').value_si,4182.)
        self.assertEqual(salt.datum('density').value_si,1024.)
        self.assertEqual(salt.datum('heat_capacity').value_si,3993.)
        self.assertIn('salinity',salt.note)

    def test_capabilities_are_condition_specific(self):
        c=LIB.coverage()
        self.assertIn('rock.granite',c['conduction_reference'])
        self.assertNotIn('mineral.microcline',c['conduction_reference'])
        self.assertEqual(c['instantaneous_buoyancy'],())
        self.assertIn('solid.ice',LIB.coverage(reference_temperature_k=273.15)['conduction_reference'])
        self.assertNotIn('solid.ice',c['conduction_reference'])

    def test_preflight_reports_all_selected_gaps(self):
        missing=LIB.unresolved(('rock.granite','mineral.microcline'),reference_temperature_k=300.)
        self.assertEqual(len(missing),2)
        self.assertTrue(all(len(problems)>=2 for _,problems in missing))
        with self.assertRaises(MaterialLibraryError):LIB['rock.granite'].require('conduction_reference',temperature_k=1200.)
        with self.assertRaises(MaterialLibraryError):LIB['rock.granite'].require('conduction_reference',pressure_pa=1e9)
        with self.assertRaises(MaterialLibraryError):LIB['rock.granite'].require('rheology')

    def test_recipes_are_assumptions_not_observations(self):
        self.assertEqual(len(LIB.recipes),7)
        for r in LIB.recipes:
            self.assertAlmostEqual(math.fsum(v for _,v in r.components),1.)
            self.assertTrue(r.statement)
            self.assertTrue(all(LIB[id].basis=='grain' for id,_ in r.components))


class LibraryContractTests(unittest.TestCase):
    def test_frozen_and_detached_manifest(self):
        with self.assertRaises(FrozenInstanceError):LIB.version='bad'
        with self.assertRaises(TypeError):LIB._index['x']=LIB.profiles[0]
        d=LIB.descriptor();d['profiles'][0]['name']='changed'
        self.assertNotEqual(LIB.profiles[0].name,'changed')
        self.assertIs(copy.deepcopy(LIB),LIB)

    def test_profile_and_library_identity_changes(self):
        p=LIB['rock.granite'];changed=replace(p,note=p.note+' New evidence.')
        self.assertNotEqual(p.profile_id,changed.profile_id)
        lib=EarthMaterialLibrary(LIB.version,tuple(changed if x==p else x for x in LIB.profiles),LIB.sources,LIB.recipes)
        self.assertNotEqual(lib.library_id,LIB.library_id)

    def test_library_order_and_version(self):
        same=EarthMaterialLibrary(LIB.version,LIB.profiles[::-1],LIB.sources[::-1],LIB.recipes)
        self.assertEqual(same.library_id,LIB.library_id)
        different=EarthMaterialLibrary(LIB.version+'x',LIB.profiles,LIB.sources,LIB.recipes)
        self.assertNotEqual(different.library_id,LIB.library_id)

    def test_duplicate_or_unknown_sources_refused(self):
        with self.assertRaises(MaterialLibraryError):EarthMaterialLibrary('x',(LIB.profiles[0],)*2,LIB.sources)
        with self.assertRaises(MaterialLibraryError):EarthMaterialLibrary('x',LIB.profiles,LIB.sources[:-1])
        with self.assertRaises(MaterialLibraryError):EarthMaterialLibrary('x',LIB.profiles,LIB.sources+(LIB.sources[0],))

    def test_bad_units_and_signs(self):
        original=LIB['rock.granite'].datum('density')
        for changes in ({'reported_unit':'J/kg/K'},{'reported_unit':'guessed'}, {'reported_value':-1},
                        {'reported_value':True},{'reported_value':float('nan')},{'reported_value':float('inf')}):
            with self.subTest(changes=changes),self.assertRaises(TectonicsError):replace(original,**changes)

    def test_bad_range_selection_and_secant_refused(self):
        d=LIB['rock.granite'].datum('density')
        for changes in ({'reported_bounds':(4.,5.)},{'reported_bounds':[-1,3]}, {'reported_bounds':None},
                        {'reported_value':2.6},{'temperature_span_k':(200.,400.)}):
            with self.subTest(changes=changes),self.assertRaises(MaterialLibraryError):replace(d,**changes)
        with self.assertRaises(MaterialLibraryError):PropertyDatum('thermal_expansion',8.,'linear_micro/K_isotropic','s','test')

    def test_missing_properties_never_assume_zero(self):
        p=LIB['rock.granite'];self.assertIsNone(p.datum('heat_production'))
        with self.assertRaises(MaterialLibraryError):p.require('radiogenic_reference')
        definitions,_=LIB.definitions((p.material_id,))
        self.assertIsNone(definitions[0].heat_production_w_m3)
        self.assertIn('heat_production',definitions[0].unknown_reason)

    def test_pressure_and_temperature_no_extrapolation(self):
        for condition in ({'temperature_k':1000.},{'pressure_pa':0.},{'pressure_pa':2e9}):
            with self.subTest(condition=condition),self.assertRaises(MaterialLibraryError):LIB['mineral.quartz'].require(**condition)
        self.assertIs(LIB['rock.granite'].require(temperature_k=293.15),LIB['rock.granite'])

    def test_stage4_bindings_preserve_evidence(self):
        definitions,sources=LIB.definitions(('rock.granite','mineral.microcline'))
        by={d.material_id:d for d in definitions};ev={s.source_id:s for s in sources}
        self.assertEqual(by['rock.granite'].density_kg_m3,2650.)
        self.assertIsNone(by['mineral.microcline'].specific_heat_j_kg_k)
        self.assertIsNone(by['rock.granite'].thermal_expansion_per_k)
        self.assertIsNone(by['rock.granite'].valid_temperature_k)
        for d in definitions:
            record=json.loads(ev[d.source_id].statement)
            self.assertEqual(record['library'],LIB.library_id)
            self.assertEqual(record['profile'],LIB[d.material_id].profile_id)
            self.assertTrue(record['reference_only']);self.assertTrue(ev[d.source_id].references)

    def test_all_profiles_export_without_synthetic_padding(self):
        d,s=LIB.definitions(tuple(p.material_id for p in LIB.profiles))
        self.assertEqual(len(d),len(LIB.profiles));self.assertTrue(all(x.kind=='literature' for x in s))
        self.assertTrue(all(x.unknown_reason for x in d))

    def test_binding_changes_with_library_and_condition(self):
        a,sa=LIB.definitions(('rock.granite',))
        b,sb=LIB.definitions(('rock.granite',),reference_temperature_k=273.15)
        self.assertNotEqual(a[0].source_id,b[0].source_id)
        lib=EarthMaterialLibrary('new',LIB.profiles,LIB.sources,LIB.recipes)
        c,_=lib.definitions(('rock.granite',));self.assertNotEqual(a[0].source_id,c[0].source_id)

    def test_binding_selection_rejects_bad_ids(self):
        for ids in ((),('rock.granite','rock.granite'),['rock.granite'],('unknown',)):
            with self.subTest(ids=ids),self.assertRaises(MaterialLibraryError):LIB.definitions(ids)

    def test_alias_ambiguity_returns_all_not_first(self):
        source=LIB.sources
        a=replace(LIB['rock.granite'],aliases=('shared',));b=replace(LIB['rock.basalt'],aliases=('shared',))
        lib=EarthMaterialLibrary('ambiguous',(a,b),source)
        self.assertEqual(len(lib.find('shared')),2)
        with self.assertRaises(MaterialLibraryError):lib['shared']

    def test_library_pickle_reconstructs_and_validates(self):
        new=pickle.loads(pickle.dumps(LIB))
        self.assertEqual(new.library_id,LIB.library_id)
        with self.assertRaises(TypeError):new._index['x']=new.profiles[0]


class MixtureTests(unittest.TestCase):
    def setUp(self):self.lib=synthetic_library()
    def mix(self,**kw):return mix_materials(self.lib,(('a',.25),('b',.75)),fraction_basis='volume',**kw)

    def test_volume_mixture_density_and_heat_capacity(self):
        b=self.mix();self.assertEqual(b.density_kg_m3,3500.)
        expected=Fraction(1,4)*2000*800+Fraction(3,4)*4000*1000
        self.assertEqual(b.volumetric_heat_capacity_j_m3_k,float(expected))
        self.assertEqual(b.specific_heat_j_kg_k,float(expected/Fraction(3500)))
        self.assertNotEqual(b.specific_heat_j_kg_k,.25*800+.75*1000)

    def test_mass_fraction_conversion(self):
        b=mix_materials(self.lib,(('a',.5),('b',.5)),fraction_basis='mass')
        assert_allclose([v for _,v in b.component_volume_fractions],[2/3,1/3],rtol=1e-15)
        self.assertAlmostEqual(b.specific_heat_j_kg_k,900.)
        self.assertAlmostEqual(b.density_kg_m3,float(Fraction(1,1)/(Fraction(1,2)/2000+Fraction(1,2)/4000)))

    def test_default_conductivity_is_bounds(self):
        b=self.mix();self.assertIsNone(b.conductivity_w_m_k)
        lower=float(1/(Fraction(1,4)/2+Fraction(3,4)/8));upper=6.5
        self.assertEqual(b.conductivity_bounds_w_m_k,(lower,upper))
        self.assertEqual(b.conductivity_model,'bounds')

    def test_explicit_arrangements(self):
        lower,upper=self.mix().conductivity_bounds_w_m_k
        self.assertEqual(self.mix(conductivity='series').conductivity_w_m_k,lower)
        self.assertEqual(self.mix(conductivity='parallel').conductivity_w_m_k,upper)
        geometric=self.mix(conductivity='geometric')
        self.assertAlmostEqual(geometric.conductivity_w_m_k,2**.25*8**.75)
        self.assertTrue(any('approximation' in x for x in geometric.notes))

    def test_exact_heat_production_mixture(self):
        self.assertAlmostEqual(self.mix().heat_production_w_m3,3e-6)
        b=mix_materials(LIB,(('rock.granite',1.),),fraction_basis='volume')
        self.assertIsNone(b.heat_production_w_m3)

    def test_single_constituent_limits(self):
        for id in ('a','b'):
            b=mix_materials(self.lib,((id,1.),),fraction_basis='volume',conductivity='parallel')
            p=self.lib[id]
            for val,key in ((b.density_kg_m3,'density'),(b.specific_heat_j_kg_k,'heat_capacity'),(b.conductivity_w_m_k,'conductivity')):
                self.assertEqual(val,p.datum(key).value_si)

    def test_porous_quartz_water_independent_values(self):
        b=sediment_matrix('quartz_sand_or_silt_matrix',porosity=.3,pore_fluid='fluid.fresh_water')
        self.assertAlmostEqual(b.density_kg_m3,.7*2648+.3*998.2)
        cv=.7*2648*741+.3*998.2*4182
        self.assertAlmostEqual(b.volumetric_heat_capacity_j_m3_k,cv)
        self.assertAlmostEqual(b.specific_heat_j_kg_k,cv/b.density_kg_m3)
        self.assertIsNone(b.heat_production_w_m3)

    def test_porosity_cannot_be_added_twice(self):
        with self.assertRaisesRegex(MaterialLibraryError,'bulk'):
            mix_materials(LIB,(('rock.sandstone',1.),),fraction_basis='volume',porosity=.2,pore_fluid='fluid.fresh_water')

    def test_pore_fluid_requires_explicit_definition(self):
        for phi,fluid in ((.3,None),(0.,'fluid.fresh_water'),(.3,'rock.granite'),(.3,'unknown')):
            with self.subTest(phi=phi,fluid=fluid),self.assertRaises(MaterialLibraryError):
                mix_materials(LIB,(('mineral.quartz',1.),),fraction_basis='volume',porosity=phi,pore_fluid=fluid)

    def test_invalid_fractions_and_bases(self):
        for components in ((('a',.8),),(('a',.5),('a',.5)),(('a',-1.),('b',2.)),(('a',True),)):
            with self.subTest(components=components),self.assertRaises(TectonicsError):mix_materials(self.lib,components,fraction_basis='volume')
        for basis in ('molar','guessed',None):
            with self.assertRaises(MaterialLibraryError):mix_materials(self.lib,(('a',1.),),fraction_basis=basis)

    def test_no_implicit_thermal_extrapolation_in_mix(self):
        with self.assertRaises(MaterialLibraryError):self.mix(reference_temperature_k=1500.)
        b=mix_materials(LIB,(('mineral.microcline',1.),),fraction_basis='volume')
        self.assertIsNone(b.specific_heat_j_kg_k)
        self.assertTrue(any('missing' in x.lower() for x in b.notes))

    def test_fluid_not_matrix_and_porosity_limits(self):
        with self.assertRaises(MaterialLibraryError):mix_materials(LIB,(('fluid.fresh_water',1.),),fraction_basis='volume')
        for phi in (-.1,1.,1.1,True):
            with self.assertRaises(TectonicsError):self.mix(porosity=phi)

    def test_blend_identity_and_immutability(self):
        a=self.mix();b=self.mix(conductivity='parallel')
        self.assertNotEqual(a.blend_id,b.blend_id)
        with self.assertRaises(FrozenInstanceError):a.density_kg_m3=1.
        with self.assertRaises(MaterialLibraryError):replace(a,density_kg_m3=-1.)

    def test_budget_refusal_is_clean(self):
        budget=WorkBudget(100)
        with self.assertRaises(MemoryLimitError):self.mix(budget=budget)
        self.assertEqual(budget.reserved_bytes,0)

    def test_all_sediment_recipes_resolve_without_grain_duplication(self):
        for recipe in LIB.recipes:
            b=sediment_matrix(recipe.recipe_id,porosity=.25,pore_fluid='fluid.seawater')
            self.assertIsNotNone(b.specific_heat_j_kg_k);self.assertIsNotNone(b.conductivity_bounds_w_m_k)
            self.assertAlmostEqual(sum(x for _,x in b.component_volume_fractions),1.)


class PreparedPropertyTests(unittest.TestCase):
    def setUp(self):self.table=LIB.prepare(('rock.granite','rock.basalt','mineral.quartz'))
    def test_native_gather_matches_reference(self):
        codes=np.array([[0,1,2],[2,1,0]],dtype=np.int16)
        out=self.table.gather(codes)
        expected=np.array([[[LIB[self.table.material_ids[i]].datum(p).value_si for p in self.table.properties] for i in row] for row in codes])
        assert_array_equal(out,expected)
        with self.assertRaises(ValueError):out.setflags(write=True)
        codes[:]=-1;assert_array_equal(out,expected)

    def test_large_bounded_batch_and_strides(self):
        codes=np.tile(np.arange(3,dtype=np.uint8),70000)[::2]
        out=self.table.gather(codes)
        self.assertEqual(out.shape,(len(codes),3))
        v,_=self.table.inspect();assert_array_equal(out,v[codes])

    def test_missing_placeholder_never_leaks(self):
        t=LIB.prepare(('mineral.microcline',))
        vals,known=t.inspect();self.assertFalse(known[0,1]);self.assertEqual(vals[0,1],0)
        with self.assertRaises(MaterialLibraryError):t.gather(np.array([0],dtype=np.uint8))

    def test_secant_cannot_be_gathered_as_instantaneous_alpha(self):
        t=LIB.prepare(('rock.granite',),('thermal_expansion',))
        with self.assertRaises(MaterialLibraryError):t.gather(np.array([0]))

    def test_frozen_table_and_descriptors(self):
        v,k=self.table.inspect();v.shape=(9,);k.shape=(9,)
        self.assertEqual(self.table.inspect()[0].shape,(3,3))
        with self.assertRaises(ValueError):v.setflags(write=True)
        with self.assertRaises(FrozenInstanceError):self.table.library_id='x'
        self.assertIs(copy.deepcopy(self.table),self.table)

    def test_restore_and_digest(self):
        t=pickle.loads(pickle.dumps(self.table))
        self.assertEqual(t.table_id,self.table.table_id)
        with self.assertRaises(ValueError):t.inspect()[0].setflags(write=True)
        args=(t.library_id,t.material_ids,t.properties,t.reference_temperature_k,t._values,t._known,t.table_id)
        with self.assertRaises(MaterialLibraryError):_restore_table(*args[:-1],'a'*64)
        with self.assertRaises(MaterialLibraryError):_restore_table(*args[:4],b'bad',*args[5:])

    def test_integer_codes_not_booleans_masks_or_names(self):
        for codes in (np.array([True]),np.array([1.]),np.array([-1]),np.array([3]),np.ma.array([0]),[0],np.array(['granite'])):
            with self.subTest(codes=str(codes)),self.assertRaises(MaterialLibraryError):self.table.gather(codes)

    def test_scalar_empty_and_endian_inputs(self):
        self.assertEqual(self.table.gather(np.array(2)).shape,(3,))
        self.assertEqual(self.table.gather(np.zeros((0,4),dtype=np.int16)).shape,(0,4,3))
        assert_array_equal(self.table.gather(np.array([0,2],dtype='>i4')),self.table.gather(np.array([0,2])))

    def test_cancellation_and_memory_release(self):
        cancel=threading.Event();cancel.set();budget=WorkBudget(1<<20)
        with self.assertRaises(CancelledError):self.table.gather(np.array([0]),cancel=cancel,budget=budget)
        self.assertEqual(budget.reserved_bytes,0)
        with self.assertRaises(MemoryLimitError):self.table.gather(np.zeros(1000,dtype=int),budget=WorkBudget(1))

    def test_parallel_reads_no_shared_writes(self):
        codes=np.resize(np.arange(3),1000)
        with ThreadPoolExecutor(4) as pool:outputs=list(pool.map(lambda _:self.table.gather(codes),range(8)))
        self.assertTrue(all(x.tobytes()==outputs[0].tobytes() for x in outputs))

    def test_context_includes_data_code_and_preserves_identity(self):
        with ExecutionContext() as context:
            before=context.identity
            LIB.prepare(('mineral.quartz',));earth_material_library()
            context.verify();self.assertEqual(context.identity,before)


class RadiogenicTests(unittest.TestCase):
    def test_equation_units_against_fraction(self):
        a=RadiogenicAssay(2.,8.,2.,'sample')
        expected=Fraction(2700)*Fraction(1,10**11)*(Fraction(952,100)*2+Fraction(256,100)*8+Fraction(348,100)*2)
        self.assertAlmostEqual(a.heat_production(2700.),float(expected),places=18)

    def test_explicit_zero_is_allowed(self):
        self.assertEqual(RadiogenicAssay(0.,0.,0.,'measured-zero-assumption').heat_production(2700.),0.)

    def test_elemental_units_and_mass_limit(self):
        for args in ((-1,0,0,'s'),(True,0,0,'s'),(0,0,101,'s'),(1e6,1,0,'s'),(0,0,1,'')):
            with self.assertRaises(TectonicsError):RadiogenicAssay(*args)
        with self.assertRaises(TectonicsError):RadiogenicAssay(1,2,3,'s').heat_production(-1)

    def test_assay_identity_does_not_infer_formation_time(self):
        a=RadiogenicAssay(1,2,3,'s')
        with self.assertRaises(FrozenInstanceError):a.uranium_ppm=0
        self.assertNotEqual(a,replace(a,source_id='different sample'))
        self.assertNotIn('age',a.__dataclass_fields__)


class LayerIntegrationTests(unittest.TestCase):
    def test_real_library_in_existing_description(self):
        case=earth_case();b=resolve_geological_layer(case,'column','bed')
        self.assertAlmostEqual(b.density_kg_m3,.75*2648+.25*998.2)
        self.assertEqual(case.cohorts[0].cohort.formation_time_s,-100.)
        self.assertTrue(case.unresolved)  # radiogenic/instantaneous alpha are NOT fabricated.

    def test_bulk_rock_cannot_be_reporosified_by_layer_adapter(self):
        with self.assertRaises(MaterialLibraryError):resolve_geological_layer(earth_case(rock='rock.granite'),'column','bed')
        b=resolve_geological_layer(earth_case(rock='rock.granite',porosity=0.),'column','bed')
        self.assertEqual(b.density_kg_m3,2650.)

    def test_missing_porosity_and_wrong_layer_fail_before_resolution(self):
        with self.assertRaises(MaterialLibraryError):resolve_geological_layer(earth_case(porosity=None),'column','bed')
        with self.assertRaises(MaterialLibraryError):resolve_geological_layer(earth_case(),'column','wrong')

    def test_changed_case_property_is_not_silently_overwritten(self):
        case=earth_case()
        kwargs={x:getattr(case,x) for x in ('case_id','topology','time_s','epoch_id','depth_reference_id','source_id','sources','materials','cohorts','thermal_profiles','columns','provinces','precedence')}
        kwargs['materials']=tuple(replace(m,density_kg_m3=2800.) if m.material_id=='mineral.quartz' else m for m in case.materials)
        altered=GeologicalCase(**kwargs)
        with self.assertRaises(MaterialLibraryError):resolve_geological_layer(altered,'column','bed')

    def test_library_revision_must_be_bound_explicitly(self):
        case=earth_case();other=EarthMaterialLibrary('next',LIB.profiles,LIB.sources,LIB.recipes)
        with self.assertRaises(MaterialLibraryError):resolve_geological_layer(case,'column','bed',library=other)

    def test_same_material_different_cohorts_preserve_histories(self):
        case=earth_case(porosity=0.)
        kwargs={x:getattr(case,x) for x in ('case_id','topology','time_s','epoch_id','depth_reference_id','source_id','sources','materials','cohorts','thermal_profiles','columns','provinces','precedence')}
        younger=CohortDescription(MaterialCohort('young','mineral.quartz','other-origin',0.),'case')
        kwargs['cohorts']=(case.cohorts[0],younger)
        bed=replace(case.columns[0].layers[0],components=(LayerComponent('old',.4),LayerComponent('young',.6)))
        kwargs['columns']=(replace(case.columns[0],layers=(bed,)),)
        both=GeologicalCase(**kwargs);b=resolve_geological_layer(both,'column','bed')
        self.assertEqual(b.component_volume_fractions,(('mineral.quartz',1.),))
        self.assertEqual(len(both.cohorts),2)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'library.sqlite'
        self.budget=WorkBudget(64<<20)
        self.limits=StoreLimits(4096,2<<20,16<<20,decoded_cache_bytes=8192)
        self.store=ArrayStore(self.path,self.limits,budget=self.budget)
    def tearDown(self):
        self.store.close();self.tmp.cleanup();self.assertEqual(self.budget.reserved_bytes,0)

    def test_complete_lossless_reference_round_trip(self):
        key=save_material_library(LIB,self.store)
        out=load_material_library(self.store,key)
        self.assertEqual(out._payload,LIB._payload);self.assertEqual(out.library_id,LIB.library_id)
        with self.assertRaises(TypeError):out._index['x']=out.profiles[0]

    def test_repeated_save_deduplicates(self):
        save_material_library(LIB,self.store);before=self.store.statistics()
        save_material_library(LIB,self.store);after=self.store.statistics()
        self.assertEqual(before['unique_chunks'],after['unique_chunks'])
        self.assertEqual(after['snapshots'],1)
        self.assertLess(after['encoded_payload_bytes'],LIB.nbytes)

    def test_missing_snapshot_is_only_normal_miss(self):
        self.assertIsNone(load_material_library(self.store,'a'*64))
        with self.assertRaises(MaterialLibraryError):load_material_library(self.store,'bad')

    def test_corrupt_payload_not_miss(self):
        save_material_library(LIB,self.store)
        self.store._db.execute("UPDATE chunks SET payload=? WHERE id=(SELECT id FROM chunks LIMIT 1)",(b'bad',))
        with self.assertRaises(StoreError):load_material_library(self.store,LIB.library_id)

    def test_untrusted_snapshot_inventory_refused(self):
        self.store.put('b'*64,{'not_catalogue':np.array([1],dtype=np.uint8)}, {'schema':'atlas.earth-material-snapshot.v1','library_id':'b'*64,'version':'x'})
        with self.assertRaises(MaterialLibraryError):load_material_library(self.store,'b'*64)

    def test_cancellation_does_not_publish(self):
        e=threading.Event();e.set()
        with self.assertRaises(CancelledError):save_material_library(LIB,self.store,cancel=e)
        self.assertEqual(self.store.statistics()['snapshots'],0)

    def test_low_restore_budget_refuses_without_leaks(self):
        save_material_library(LIB,self.store)
        b=WorkBudget(10)
        with self.assertRaises(MemoryLimitError):load_material_library(self.store,LIB.library_id,budget=b)
        self.assertEqual(b.reserved_bytes,0)

    def test_independent_backup_after_original_removal(self):
        save_material_library(LIB,self.store)
        path=self.store.backup_to(Path(self.tmp.name)/'backup.sqlite')
        self.store.close();self.path.unlink()
        with ArrayStore(path,self.limits,budget=self.budget) as other:
            self.assertEqual(load_material_library(other,LIB.library_id)._payload,LIB._payload)

    def test_fresh_process_reuses_actual_stored_records(self):
        save_material_library(LIB,self.store)
        script="""import sys
from atlas_tectonics import load_material_library
from atlas_tectonics.storage import ArrayStore, StoreLimits
with ArrayStore(sys.argv[1],StoreLimits(4096,2<<20,16<<20)) as s:
 lib=load_material_library(s,sys.argv[2]);print(lib.library_id);print(lib['mineral.quartz'].datum('density').value_si)
"""
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),PYTHONDONTWRITEBYTECODE='1')
        p=subprocess.run([sys.executable,'-B','-c',script,str(self.path),LIB.library_id],env=env,text=True,capture_output=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout.strip().splitlines(),[LIB.library_id,'2648.0'])

    def test_case_and_library_recover_together(self):
        case=earth_case();save_material_library(LIB,self.store);key=save_geological_case(case,self.store)
        restored=load_geological_case(self.store,key);lib=load_material_library(self.store,LIB.library_id)
        b=resolve_geological_layer(restored,'column','bed',library=lib)
        self.assertEqual(b.blend_id,resolve_geological_layer(case,'column','bed').blend_id)
        self.assertEqual(restored.definition_id,case.definition_id)

    def test_manifest_tampering_and_size_refusal(self):
        raw=LIB._payload
        with self.assertRaises(MaterialLibraryError):restore_material_library(raw,'0'*64)
        with self.assertRaises(MaterialLibraryError):restore_material_library(b' '*(MAX_CATALOGUE_BYTES+1),'0'*64)
        d=LIB.descriptor();d['profiles'][0]['properties'][0]['reported_unit']='wrong'
        bad=canon(d)
        with self.assertRaises(MaterialLibraryError):restore_material_library(bad,hashlib.sha256(bad).hexdigest())

    def test_duplicate_json_or_noncanonical_data_refused(self):
        bad=b'{"schema":"a","schema":"b"}'
        with self.assertRaises(MaterialLibraryError):restore_material_library(bad,hashlib.sha256(bad).hexdigest())
        raw=json.dumps(LIB.descriptor(),indent=2).encode()
        with self.assertRaises(MaterialLibraryError):restore_material_library(raw,hashlib.sha256(raw).hexdigest())




class AdditionalSafetyTests(unittest.TestCase):
    def test_runtime_changes_to_library_functions_are_detected(self):
        import atlas_tectonics.material_library as module
        with ExecutionContext() as context:
            original=module._unit_info
            replacement=lambda unit:('density',1.)
            replacement.__module__=module.__name__
            with mock.patch.object(module,'_unit_info',replacement):
                with self.assertRaises(TectonicsError):context.verify()
            self.assertIs(module._unit_info,original)
            context.verify()

    def test_unit_definition_changes_are_detected(self):
        import atlas_tectonics.material_library as module
        with ExecutionContext() as context:
            with mock.patch.object(module,'UNIT_DEFINITIONS',module.UNIT_DEFINITIONS+(('wrong','density',1.),)):
                with self.assertRaises(TectonicsError):context.verify()
            context.verify()

    def test_huge_fractions_refused_before_sum_overflow(self):
        with self.assertRaises(MaterialLibraryError):mix_materials(synthetic_library(),(('a',1e308),('b',1e308)),fraction_basis='volume')

    def test_inconsistent_blend_refused(self):
        b=mix_materials(synthetic_library(),(('a',1.),),fraction_basis='volume')
        with self.assertRaises(MaterialLibraryError):replace(b,specific_heat_j_kg_k=999.)

    def test_excessive_property_list_refused_before_constructing(self):
        d=LIB.descriptor();d['profiles'][0]['properties']*=10
        raw=canon(d)
        with mock.patch('atlas_tectonics.material_library.PropertyDatum',side_effect=AssertionError('constructed before count check')):
            with self.assertRaises(MaterialLibraryError):restore_material_library(raw,hashlib.sha256(raw).hexdigest())



class DecimalIsolationTests(unittest.TestCase):
    def test_source_conversion_independent_of_ambient_precision(self):
        from decimal import localcontext
        original=LIB['rock.granite'].datum('density')
        with localcontext() as context:
            context.prec=1
            restored=replace(original)
            self.assertEqual(restored.value_si,2650.)
            self.assertEqual(restored.bounds_si,(2600.,2700.))


if __name__=='__main__':unittest.main()
