"""Frozen A02/A03 analytic controls and the full-vector material bridge."""
from concurrent.futures import CancelledError
import math
from threading import Event
import unittest
from unittest import mock
import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.geometry import PlanarGeometry
from atlas_tectonics.materials import MaterialCohort
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.transform import (AffineMotionInterval, PreparedAffineMotion,
    PreparedPlanarMaterials, boundary_flux_kg_s, reframe_vectors)


def square(x=0., y=0., width=1., frame='test-plane'):
    return PlanarGeometry.polygon([[x,y],[x+width,y],[x+width,y+width],[x,y+width]], frame_id=frame)


def motion(gradient=((0.,0.),(0.,0.)), velocity=(0.,0.), *, count=1, histories=None,
           budget=None, polygons=None):
    if polygons is None: polygons = tuple(square(float(i)) for i in range(count))
    if histories is None: histories = (AffineMotionInterval(1., gradient, velocity, (0.,0.), 'test-motion'),)
    return PreparedAffineMotion(polygons, histories, parcel_ids=tuple('p'+str(i) for i in range(len(polygons))),
        time_s=0., source_id='analytic-A02', budget=budget)


def materials(m, context, *, enthalpy=True):
    n = len(m.parcel_ids)
    return PreparedPlanarMaterials(m, (MaterialCohort('a','upper','source-a',-10.),
        MaterialCohort('b','lower','source-b',None)), np.tile([[10000.],[20000.]], (1,n)),
        density_kg_m3=[2700.,2850.], epoch_id='test-epoch', datum_id='test-datum',
        source_id='test-inventory', specific_enthalpy_j_kg=(np.tile([[100.],[-50.]], (1,n)) if enthalpy else None),
        enthalpy_source='relative-heat' if enthalpy else None, context=context)


class TransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.context = ExecutionContext('scipy')
    @classmethod
    def tearDownClass(cls): cls.context.close()

    def test_A02_pure_simple_shear_rotation_translation(self):
        variants = [(((math.log(2),0),(0,-math.log(2))), (0,0), [[2,0],[0,.5]]),
                    (((0,2),(0,0)), (0,0), [[1,2],[0,1]]),
                    (((0,-math.pi/2),(math.pi/2,0)), (0,0), [[0,-1],[1,0]]),
                    (((0,0),(0,0)), (3,-2), [[1,0],[0,1]])]
        for gradient, velocity, expected in variants:
            with self.subTest(expected=expected), motion(gradient, velocity) as m, materials(m,self.context) as p:
                state = p.evaluate(1.)
                np.testing.assert_allclose(state.motion.deformation_gradient[0], expected, atol=1e-14)
                np.testing.assert_allclose(state.motion.jacobian,1.,atol=1e-14)
                np.testing.assert_allclose(state.thickness_m[:,0],[10000.,20000.],rtol=1e-14)
                np.testing.assert_array_equal(state.mass_kg,p.evaluate(0.).mass_kg)
                if expected == [[0,-1],[1,0]] or velocity == (3,-2):
                    np.testing.assert_allclose(state.motion.green_strain,0.,atol=1e-14)

    def test_noncommuting_history_and_objectivity(self):
        shear = ((0,2),(0,0)); shrink = ((math.log(.8),0),(0,0))
        outputs=[]
        for first, second in ((shrink,shear),(shear,shrink)):
            history=(AffineMotionInterval(1,first,(0,0),(0,0),'one'),
                     AffineMotionInterval(2,second,(0,0),(0,0),'two'))
            with motion(histories=history) as m: outputs.append(m.evaluate(2).deformation_gradient[0])
        np.testing.assert_allclose(outputs[0],[[.8,2],[0,1]],atol=1e-14)
        np.testing.assert_allclose(outputs[1],[[.8,1.6],[0,1]],atol=1e-14)
        history=(AffineMotionInterval(1,shear,(0,0),(0,0),'shear'),
                 AffineMotionInterval(2,((0,-math.pi/2),(math.pi/2,0)),(0,0),(0,0),'rotate'))
        with motion(histories=history) as m:
            np.testing.assert_allclose(m.evaluate(1).right_cauchy_green,m.evaluate(2).right_cauchy_green,atol=1e-13)

    def test_spatial_and_time_partitions_do_not_accumulate_remap_error(self):
        for cells in (8,16,32):
            final=[]
            for parts in (1,2,4):
                history=tuple(AffineMotionInterval(i/parts,((-.1,.2),(0,.03)),(.1,-.2),(0,0),'same') for i in range(1,parts+1))
                with motion(count=cells,histories=history) as m:
                    final.append(m.evaluate(1).deformation_gradient)
                    m.evaluate(.137); m.evaluate(.687)
                    np.testing.assert_array_equal(final[-1],m.evaluate(1).deformation_gradient)
            np.testing.assert_allclose(final[0],final[1],atol=1e-14)
            np.testing.assert_allclose(final[0],final[2],atol=1e-14)

    def test_full_vector_frame_and_relative_flux(self):
        q=np.array([[0.,-1.],[1.,0.]])
        positions=np.array([[3.,2.]]); velocities=np.array([[.5,10.]])
        points, v = reframe_vectors(positions,velocities,rotation=q,origin_m=[2,1],frame_velocity_m_s=[.25,9])
        np.testing.assert_array_equal(points,[[-1,1]]); np.testing.assert_array_equal(v,[[-1,.25]])
        kwargs=dict(thickness_m=3,density_kg_m3=4,length_m=2)
        self.assertEqual(boundary_flux_kg_s(**kwargs,material_velocity_m_s=[.5,10],boundary_velocity_m_s=[.25,-5],outward_normal=[1,0]),6.)
        self.assertEqual(boundary_flux_kg_s(**kwargs,material_velocity_m_s=[.5,10],boundary_velocity_m_s=[.5,-5],outward_normal=[1,0]),0.)
        self.assertEqual(boundary_flux_kg_s(**kwargs,material_velocity_m_s=q@np.array([3.5,8.]),boundary_velocity_m_s=q@np.array([3.25,-7.]),outward_normal=q@np.array([1.,0.])),6.)

    def test_material_crop_signed_heat_cache_and_immutable_fields(self):
        with motion(velocity=(.25,.1),count=2) as m, materials(m,self.context) as p:
            targets=(square(),square(1.))
            kwargs=dict(target_ids=('left','right'),exterior_id='outside',source_id='view')
            view=p.project(1,targets,**kwargs)
            self.assertIs(view,p.project(1,targets,**kwargs))
            initial=p.evaluate(0)
            for k, field in enumerate((view.volume_m3,view.mass_kg,view.enthalpy_j)):
                expected=(initial.volume_m3,initial.mass_kg,initial.enthalpy_j)[k]
                np.testing.assert_allclose(field.sum(axis=1)+view.outside[k].sum(axis=1),expected.sum(axis=1),rtol=1e-14)
            self.assertGreater(view.outside[0].sum(),0)
            with self.assertRaises(ValueError): view.account.inside[0,0]=0
            before=view.mass_kg.shape; changed=view.account.inside; changed.shape=(-1,)
            self.assertEqual(view.mass_kg.shape,before)
            self.assertFalse(p.project(.5,targets,**kwargs) is view)

    def test_unknown_heat_and_provenance(self):
        with motion() as m, materials(m,self.context,enthalpy=False) as p:
            state=p.evaluate(1)
            self.assertFalse(state.descriptor()['enthalpy_present'])
            self.assertIsNone(state.cohorts[1].formation_time_s)
            self.assertEqual(state.descriptor()['epoch'],'test-epoch')

    def test_integrated_actual_region_exchange(self):
        with motion(velocity=(1.,0.),count=2) as m, materials(m,self.context) as p:
            regions=(square(),square(1.))
            result=p.exchange(0,1,regions,regions,region_ids=('left','right'),exterior_id='outside',source_id='boundary-scenario')
            # Uniform original first parcel moves wholly from left to right;
            # original second parcel moves wholly from right to retained exterior.
            np.testing.assert_allclose(result.transfer[0],[[0,10000,0],[0,0,10000],[0,0,0]])
            self.assertEqual(result.descriptor()['material_plan'],p.plan_id)
            self.assertEqual(result.descriptor()['field_order'][2],['mass_kg','a'])
            with self.assertRaises(TectonicsError):
                p.exchange(1,0,regions,regions,region_ids=('left','right'),exterior_id='outside',source_id='reverse')

    def test_nodal_network_material_projection_and_exchange(self):
        from atlas_tectonics.deformation_network import NodalMotionInterval, PreparedDeformationNetwork
        vertices=np.array([[0.,0.],[2.,0.],[2.,2.],[0.,2.],[1.,1.]])
        triangles=np.array([[0,1,4],[1,2,4],[2,3,4],[3,0,4]])
        velocity=np.zeros_like(vertices); velocity[4]=[.2,-.1]
        with PreparedDeformationNetwork(vertices,triangles,(NodalMotionInterval(1,velocity,'interior-strain'),),
            time_s=0,frame_id='test-plane',source_id='nodal-test',triangle_ids=('t0','t1','t2','t3')) as m:
            with PreparedPlanarMaterials(m,(MaterialCohort('a','crust','initial',0),),[[1,1,1,1]],density_kg_m3=[2],
                epoch_id='test',datum_id='reference',source_id='initial-material',context=self.context) as p:
                state=p.evaluate(1)
                self.assertLess(state.thickness_m.min(),1); self.assertGreater(state.thickness_m.max(),1)
                region=(square(width=2),)
                view=p.project(1,region,target_ids=('whole',),exterior_id='outside',source_id='fixed')
                np.testing.assert_allclose(view.volume_m3,[[4.]])
                result=p.exchange(0,1,region,region,region_ids=('whole',),exterior_id='outside',source_id='junction-account')
                np.testing.assert_allclose(result.transfer[0],[[4,0],[0,0]])

    def test_source_mutation_refuses_cached_view(self):
        with motion() as m:
            p=materials(m,self.context)
            try:
                kwargs=dict(target_ids=('a',),exterior_id='out',source_id='view')
                p.project(1,(square(),),**kwargs)
                with mock.patch('atlas_tectonics.transform.MAP_ERROR',.5):
                    with self.assertRaises(TectonicsError): p.project(1,(square(),),**kwargs)
            finally: p.close()

    def test_stale_preparation_cannot_adopt_a_new_source_context(self):
        with motion() as m:
            # This represents a newly captured runtime after a helper changed:
            # precomputed maps remain bound to the identity that produced them.
            with mock.patch('atlas_tectonics.transform.MAP_ERROR',5e-11):
                with ExecutionContext('scipy') as changed:
                    with self.assertRaisesRegex(TectonicsError,'different source/runtime'):
                        materials(m,changed)

    def test_fault_slip_material_bridge_preserves_thickness_and_exterior(self):
        from atlas_tectonics.fault_slip import SlipInterval, PreparedFaultSlip
        polygons=(square(-1),square())
        with PreparedFaultSlip(polygons,(SlipInterval(1,[0,-.25],[0,.5],[0,0],'opposing-slip'),),
            parcel_ids=('negative','positive'),sides=(-1,1),interface_point_m=[0,0],interface_normal=[1,0],
            interface_id='named-transform',time_s=0,source_id='slip-case') as m, materials(m,self.context) as p:
            state=p.evaluate(1)
            np.testing.assert_allclose(state.thickness_m,[[10000,10000],[20000,20000]],rtol=1e-14)
            result=p.exchange(0,1,polygons,polygons,region_ids=('negative','positive'),exterior_id='outside',source_id='fault-regions')
            self.assertAlmostEqual(result.transfer[0,0,2],2500.)
            self.assertAlmostEqual(result.transfer[0,1,2],5000.)
            self.assertEqual(result.transfer[0,0,1],0.)
            self.assertEqual(result.transfer[0,1,0],0.)

    def test_invalid_history_geometry_budget_cancel_and_closed(self):
        with self.assertRaises(TectonicsError): AffineMotionInterval(1,[[0,0]], [0,0],[0,0],'bad')
        with self.assertRaises(TectonicsError): motion(histories=())
        with self.assertRaises(MemoryLimitError): motion(budget=WorkBudget(100))
        with motion(polygons=(square(),square(.5))) as m:
            with self.assertRaises(TectonicsError): materials(m,self.context)
        with motion() as m:
            cancel=Event(); cancel.set()
            with self.assertRaises(CancelledError): m.evaluate(1,cancel=cancel)
            with self.assertRaises(TectonicsError): m.evaluate(2)
        with self.assertRaises(TectonicsError): m.evaluate(1)
        budget=WorkBudget(128*1024**2)
        with motion(budget=budget) as m:
            with materials(m,self.context) as p: p.evaluate(1)
        self.assertEqual(budget.reserved_bytes,0)


if __name__ == '__main__': unittest.main()
