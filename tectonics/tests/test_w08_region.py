"""Current-stock W08 regional diagnostics: conservation, geometry and refusal."""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError
import math
from threading import Event
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.geometry import PlanarGeometry
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.w08_inventory import W08Inventory
from atlas_tectonics.w08_region import W08Region


def rectangle(x=0., width=1., frame='planar'):
    return PlanarGeometry.polygon([[x,0.],[x+width,0.],[x+width,1.],[x,1.]],frame_id=frame)


def inventory(**changes):
    values = dict(node_ids=('base','extrusive','intrusive','unrepresented'),
        node_kinds=('crust','extrusion','intrusion','reservoir'), component_ids=('a','b'),
        component_mass_kg=[[12.,24.],[3.,9.],[8.,8.],[10.,20.]],
        enthalpy_j=[-360.,120.,32.,300.], formation_time_s=[-10.]*4,
        origin_ids=('origin-rock','origin-lava','origin-underplate','origin-reservoir'),
        source_id='current-producing-plan',enthalpy_source='isobaric-datum',time_s=1.)
    values.update(changes)
    return W08Inventory(**values)


def region(**changes):
    values = dict(polygons=(rectangle(),rectangle(1.,2.)),parcel_ids=('left','right'),
        node_ids=('base','extrusive','intrusive'), density_kg_m3=[2.,3.,4.],
        mass_weights=[[.25,.75],[.5,.5],[1.,0.]],
        placement_modes=('existing-column','extrusive','underplating'),
        source_id='supplied-placement',epoch_id='epoch',datum_id='vertical-datum',gravity_m_s2=10.)
    values.update(changes)
    return W08Region(**values)


class W08RegionTests(unittest.TestCase):
    def test_complete_current_mass_components_and_signed_enthalpy_are_conserved(self):
        definition = region(); state = inventory()
        view = definition.regional_view(state,definition.polygons,reference_inventory=state)
        for row in range(3):
            self.assertEqual(math.fsum(view.mass_kg[row]),state.mass_kg[row])
            self.assertEqual(math.fsum(view.enthalpy_j[row]),state.enthalpy_j[row])
            for k in range(2):
                self.assertEqual(math.fsum(view.component_mass_kg[row,:,k]),state.component_mass_kg[row,k])
        np.testing.assert_array_equal(view.mass_kg,[[9.,27.],[6.,6.],[16.,0.]])
        np.testing.assert_array_equal(view.enthalpy_j,[[-90.,-270.],[60.,60.],[32.,0.]])
        np.testing.assert_array_equal(view.volume_m3,view.mass_kg/np.array([2.,3.,4.])[:,None])
        np.testing.assert_array_equal(view.thickness_m,view.volume_m3/[1.,2.])
        np.testing.assert_array_equal(view.load_change_pa,[0.,0.])
        self.assertEqual(math.fsum(view.mass_kg.flat),64.)
        self.assertEqual(view.descriptor()['heat_source_j'],0.)
        self.assertEqual(view.descriptor()['node_ids'],['base','extrusive','intrusive'])

    def test_shortening_uses_mass_over_current_area_and_reference_area_load(self):
        definition = region(); initial = inventory(time_s=0.,source_id='initial-source')
        current = inventory()
        shortened = (rectangle(width=.8),rectangle(.8,1.6))
        view = definition.regional_view(current,shortened,reference_inventory=initial)
        original = definition.regional_view(initial,definition.polygons,reference_inventory=initial)
        np.testing.assert_allclose(view.thickness_m,original.thickness_m/.8,rtol=1e-15)
        np.testing.assert_allclose(view.load_change_pa,[77.5,41.25],rtol=1e-15)
        np.testing.assert_array_equal(view.surface_addition_m,[0.,0.])
        np.testing.assert_array_equal(view.basal_addition_m,[0.,0.])
        same_area = definition.regional_view(current,shortened,reference_inventory=initial,
                                            reference_polygons=shortened)
        np.testing.assert_array_equal(same_area.load_change_pa,[0.,0.])

    def test_emplacement_uses_only_stock_delta_and_density_never_changes_mass_load(self):
        definition = region(); current = inventory()
        initial = inventory(component_mass_kg=[[12.,24.],[1.,3.],[2.,2.],[10.,20.]],
                            enthalpy_j=[-360.,40.,8.,300.],time_s=0.,source_id='initial')
        view = definition.regional_view(current,definition.polygons,reference_inventory=initial)
        np.testing.assert_allclose(view.surface_addition_m,[4./3.,2./3.],rtol=1e-15)
        np.testing.assert_array_equal(view.basal_addition_m,[3.,0.])
        np.testing.assert_array_equal(view.load_change_pa,[160.,20.])
        denser = region(density_kg_m3=[4.,6.,8.])
        other = denser.regional_view(current,denser.polygons,reference_inventory=initial)
        np.testing.assert_array_equal(view.load_change_pa,other.load_change_pa)
        np.testing.assert_array_equal(view.mass_kg,other.mass_kg)
        np.testing.assert_array_equal(view.enthalpy_j,other.enthalpy_j)
        np.testing.assert_array_equal(view.volume_m3/2.,other.volume_m3)
        self.assertNotEqual(definition.region_id,denser.region_id)

    def test_empty_reference_and_complete_empty_current_are_supported(self):
        definition = region(); current = inventory()
        empty = inventory(component_mass_kg=np.zeros((4,2)),enthalpy_j=np.zeros(4),time_s=0.)
        view = definition.regional_view(current,definition.polygons,reference_inventory=empty)
        np.testing.assert_array_equal(view.load_change_pa,[310.,165.])
        np.testing.assert_array_equal(view.surface_addition_m,[2.,1.])
        np.testing.assert_array_equal(view.basal_addition_m,[4.,0.])
        zero = definition.regional_view(empty,definition.polygons,reference_inventory=empty)
        for field in (zero.mass_kg,zero.component_mass_kg,zero.enthalpy_j,zero.volume_m3,
                      zero.thickness_m,zero.load_change_pa,zero.surface_addition_m,zero.basal_addition_m):
            self.assertFalse(field.any())

    def test_overlap_modes_weights_and_reference_source_mismatches_are_refused(self):
        for changes in (dict(polygons=(rectangle(),rectangle(.5))),
                        dict(placement_modes=('existing-column','replacement','underplating')),
                        dict(placement_modes=('existing-column','extrusive','host-displacement')),
                        dict(density_kg_m3=[0.,3.,4.]),
                        dict(mass_weights=[[.5,.6],[.5,.5],[1.,0.]]),
                        dict(node_ids=('intrusive','extrusive','base'))):
            with self.subTest(changes=changes),self.assertRaises(TectonicsError):
                region(**changes)
        definition = region(); current = inventory()
        for reference in (inventory(enthalpy_source='other-enthalpy-datum'),
                          inventory(origin_ids=('different-rock','origin-lava','origin-underplate','origin-reservoir')),
                          inventory(formation_time_s=[-11.]*4)):
            with self.assertRaises(TectonicsError):
                definition.regional_view(current,definition.polygons,reference_inventory=reference)
        wrong_mode = region(placement_modes=('extrusive','extrusive','underplating'))
        with self.assertRaises(TectonicsError):
            wrong_mode.regional_view(current,wrong_mode.polygons,reference_inventory=current)
        for polygons in ((rectangle(),rectangle(.5)),(rectangle(frame='other'),rectangle(1.,2.))):
            with self.assertRaises(TectonicsError):
                definition.regional_view(current,polygons,reference_inventory=current)
        with self.assertRaises(TectonicsError):
            definition.regional_view(current,definition.polygons,reference_inventory=current,
                                     reference_polygons=(rectangle(),rectangle(.5)))

    def test_immutable_capture_budget_admission_and_cancellation(self):
        weights = np.array([[.25,.75],[.5,.5],[1.,0.]])
        definition = region(mass_weights=weights); weights[:]=0.
        self.assertEqual(definition.mass_weights[0,0],.25)
        state = inventory(); view = definition.regional_view(state,definition.polygons,reference_inventory=state)
        for array in (definition.density_kg_m3,definition.mass_weights,view.mass_kg,
                      view.component_mass_kg,view.enthalpy_j,view.load_change_pa):
            with self.assertRaises(ValueError): array.setflags(write=True)
        with self.assertRaises(FrozenInstanceError): definition.source_id='changed'
        with self.assertRaises(FrozenInstanceError): view.time_s=0.
        self.assertEqual(definition.reference_wkb,tuple(g.wkb for g in definition.polygons))
        changed = definition.descriptor(); changed['density_kg_m3'][0]=99.
        self.assertEqual(definition.density_kg_m3[0],2.)
        budget = WorkBudget(1)
        with mock.patch('atlas_tectonics.w08_region.np.empty',side_effect=AssertionError('allocation before admission')):
            with self.assertRaises(MemoryLimitError):
                definition.regional_view(state,definition.polygons,reference_inventory=state,budget=budget)
        self.assertEqual(budget.reserved_bytes,0)
        with self.assertRaises(MemoryLimitError): region(budget=budget)
        with self.assertRaises(TectonicsError): region(budget=WorkBudget(129*1024**2))
        cancel = Event(); cancel.set()
        with self.assertRaises(CancelledError):
            definition.regional_view(state,definition.polygons,reference_inventory=state,cancel=cancel)


if __name__ == '__main__':
    unittest.main()
