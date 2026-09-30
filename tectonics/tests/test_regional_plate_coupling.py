"""Analytical work-conjugacy and real solver controls; no world simulation."""
from concurrent.futures import CancelledError
from dataclasses import replace
from pathlib import Path
import sys
from threading import Event
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src')]
import regional_plate_coupling as model
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.geological_records import GeologySource
from atlas_tectonics.regional_forcing import PrescribedPlateMotion
from atlas_tectonics.regional_execution import RegionalMechanicsScales
from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES


Q = np.array([[0.,0.,1.],[1.,0.,0.],[0.,1.,0.]])


def plan():
    bc = {s:('traction',)*3 for s in SIDES}
    bc['z0'] = bc['z1'] = ('velocity',)*3
    return PreparedRegionalStokes3D((2,2,2),(2.,3.,4.),2.,bc,
        scales=RegionalMechanicsScales(1.,1.), reference_viscosity_pa_s=2.,
        frame_id='local-box', vertical_datum='fixed-box-bottom',
        material_source='synthetic-constant-viscosity', method='direct')


def options(p):
    xyz = p.coordinates('velocity')
    owners = np.full(len(xyz),-1,dtype=int)
    owners[xyz[:,2] == 4.] = 0
    return dict(global_frame_id='planet-centred',origin_m=Q@np.array([-1.,-1.5,10.]),
        local_axes_global=Q,plate_ids=('plate-a',),node_plate_index=owners,
        geometry_source='synthetic-embedded-box',max_work_bytes=4*1024**2)


def motion(rate=(.5,0.,0.)):
    return PrescribedPlateMotion('plate-a','planet-centred','instant',0.,
        'spherical-euler',(0.,0.,0.),tuple(rate),(0.,0.,0.),
        GeologySource('analytical','synthetic','Analytical rotating boundary.'),'m','m/s','rad/s')


def request():
    return dict(parent_state_id='same-material',epoch_id='instant',time_s=0.,
                force_source='analytical-zero-body',boundary_source='analytical-twist')


def twisting_tractions(p, omega=.5):
    fields = {s:np.zeros_like(p.coordinates(s)) for s in SIDES}
    # eta=2, H=4. Manufactured sigma_xz=-eta*omega*Y/H,
    # sigma_yz=eta*omega*X/H; lateral work vanishes (u_z=0).
    for s,coord,centre,sign in [('x0',1,1.5,1),('x1',1,1.5,-1),
                               ('y0',0,1.,-1),('y1',0,1.,1)]:
        fields[s][...,2] = sign*2.*omega/4.*(p.coordinates(s)[...,coord]-centre)
    return fields


class PlateMappingTests(unittest.TestCase):
    def test_all_components_and_planet_centre_are_used(self):
        with plan() as p:
            opts = options(p)
            opts['origin_m'] = np.array([6e6,2e5,-1e5])
            mapped = model.PreparedPlateBoundary3D(p,**opts)
            xyz = p.coordinates('velocity'); base = np.zeros_like(xyz)
            rate = np.array([1e-15,-2e-15,3e-15])
            result = mapped.prescribed_velocity([motion(rate)],base,epoch_id='instant',time_s=0.)
            expected = np.cross(rate,opts['origin_m']+xyz@Q.T)@Q
            owned = opts['node_plate_index'] == 0
            assert_allclose(result[owned],expected[owned],rtol=3e-15,atol=1e-23)
            assert_array_equal(result[~owned],base[~owned])
            self.assertTrue(np.all(np.any(result[owned] != 0,axis=0)))
            # Caller edits cannot alter a prepared map, even on a reuse path.
            opts['origin_m'][:] = 0; opts['node_plate_index'][:] = -1
            assert_array_equal(mapped.prescribed_velocity([motion(rate)],base,
                epoch_id='instant',time_s=0.), result)
            with self.assertRaises(ValueError):
                result.setflags(write=True)

    def test_multiple_plates_keep_distinct_motion_and_single_ownership(self):
        with plan() as p:
            opts=options(p); xyz=p.coordinates('velocity')
            opts['node_plate_index'][xyz[:,2] == 0.] = 1
            opts['plate_ids'] = ('plate-a','plate-b')
            mapped=model.PreparedPlateBoundary3D(p,**opts)
            motions=[motion((.1,.2,.3)),replace(motion((-.4,.5,-.6)),plate_id='plate-b')]
            result=mapped.prescribed_velocity(motions,np.zeros_like(xyz),epoch_id='instant',time_s=0.)
            for i,m in enumerate(motions):
                at=opts['node_plate_index'] == i
                expected=np.cross(m.angular_velocity_rad_s,opts['origin_m']+xyz[at]@Q.T)@Q
                assert_allclose(result[at],expected,atol=2e-15)

    def test_prescribed_exact_twist_torque_and_work(self):
        with plan() as p:
            mapped=model.PreparedPlateBoundary3D(p,**options(p)); xyz=p.coordinates('velocity')
            result=mapped.solve_prescribed([motion()],0.,np.zeros_like(xyz),twisting_tractions(p),**request())
            exact=np.column_stack((-.5*xyz[:,2]*(xyz[:,1]-1.5)/4.,
                                   .5*xyz[:,2]*(xyz[:,0]-1.)/4.,np.zeros(len(xyz))))
            assert_allclose(result.mechanical.array('velocity_m_s'),exact,atol=3e-13)
            assert_allclose(result.exchange.array('torque_on_region_nm'),[[1.625,0.,0.]],atol=2e-12)
            assert_array_equal(result.exchange.array('torque_on_plates_nm'),
                               -result.exchange.array('torque_on_region_nm'))
            assert_allclose(result.exchange.array('plate_power_into_region_w'),[.8125],atol=2e-12)
            owned=options(p)['node_plate_index'] == 0
            # Independent force-moment calculation, not another mode contraction.
            r=options(p)['origin_m']+xyz[owned]@Q.T
            force=result.mechanical.array('velocity_constraint_reaction_n')[owned]@Q.T
            assert_allclose(np.cross(r,force).sum(axis=0),[1.625,0.,0.],atol=2e-12)
            self.assertEqual(result.exchange.descriptor()['mechanical_result_id'],result.mechanical.result_id)

    def test_full_torque_solve_and_prepared_response_reuse(self):
        with plan() as p:
            mapped=model.PreparedPlateBoundary3D(p,**options(p)); base=np.zeros_like(p.coordinates('velocity'))
            args=(0.,base,twisting_tractions(p),[[1.625,0.,0.]],np.zeros((3,3)))
            result=mapped.solve_torque_coupled(*args,coupling_source='analytical-torque',**request())
            repeated=mapped.solve_torque_coupled(*args,coupling_source='analytical-torque',**request())
            assert_allclose(result.exchange.array('angular_velocity_rad_s'),[[.5,0.,0.]],atol=2e-12)
            assert_allclose(result.exchange.array('torque_on_region_nm'),args[3],atol=2e-12)
            assert_array_equal(result.exchange.array('angular_velocity_rad_s'),repeated.exchange.array('angular_velocity_rad_s'))
            self.assertEqual(p.statistics()['factorizations'],1)
            self.assertEqual(p.statistics()['coupling_response_hits'],1)
            self.assertEqual(result.exchange.result_id,repeated.exchange.result_id)

    def test_geometry_and_ownership_refusals(self):
        with plan() as p:
            original=options(p)
            bad=[dict(local_axes_global=np.diag([1.,1.,-1.])),dict(local_axes_global=Q*2),
                 dict(origin_m=[np.inf,0,0]),dict(max_work_bytes=1),dict(plate_ids=('a','a')),
                 dict(node_plate_index=original['node_plate_index'].astype(float)),
                 dict(node_plate_index=np.zeros(len(original['node_plate_index']),dtype=int)),
                 dict(node_plate_index=np.full(len(original['node_plate_index']),-1,dtype=int)),
                 dict(node_plate_index=np.full(len(original['node_plate_index']),2,dtype=int))]
            for change in bad:
                with self.subTest(change=list(change)),self.assertRaises(TectonicsError):
                    model.PreparedPlateBoundary3D(p,**(original|change))

    def test_request_refusals_and_unchanged_native_guards(self):
        with plan() as p:
            mapped=model.PreparedPlateBoundary3D(p,**options(p)); base=np.zeros_like(p.coordinates('velocity'))
            for bad in [replace(motion(),frame_id='different'),replace(motion(),epoch_id='older'),
                        replace(motion(),time_s=1.),replace(motion(),plate_id='unlisted'),
                        replace(motion(),mode='planar-rigid',angular_velocity_rad_s=(0.,0.,0.))]:
                with self.subTest(motion=bad),self.assertRaises(TectonicsError):
                    mapped.prescribed_velocity([bad],base,epoch_id='instant',time_s=0.)
            with self.assertRaises(TectonicsError):
                mapped.prescribed_velocity([motion()],base+1,epoch_id='instant',time_s=0.)
            with self.assertRaises(TectonicsError):
                mapped.solve_torque_coupled(0.,base,twisting_tractions(p),[[1.,0.,0.]],-np.eye(3),
                    coupling_source='invalid-drag',**request())
            event=Event(); event.set()
            with self.assertRaises(CancelledError):
                mapped.solve_prescribed([motion()],0.,base,twisting_tractions(p),cancel=event,**request())
            with patch.object(model,'_SOURCE_SHA','invalid'),self.assertRaises(TectonicsError):
                mapped.prescribed_velocity([motion()],base,epoch_id='instant',time_s=0.)
            with self.assertRaises(TectonicsError):
                mapped.mapping_id='edited'

    def test_numeric_overflow_is_refused(self):
        with plan() as p:
            mapped=model.PreparedPlateBoundary3D(p,**options(p))
            with self.assertRaises(TectonicsError):
                mapped.prescribed_velocity([motion((1e308,1e308,1e308))],
                    np.zeros_like(p.coordinates('velocity')),epoch_id='instant',time_s=0.)


class GaugeTorqueTests(unittest.TestCase):
    """R1 (s11-2): closed-box per-plate torques carried the arbitrary pressure mean."""
    def closed(self, pmean):
        bc = {s:('velocity',)*3 for s in SIDES}
        return PreparedRegionalStokes3D((2,2,2),(2.,3.,4.),2.,bc,scales=RegionalMechanicsScales(1.,1.),
            reference_viscosity_pa_s=2.,frame_id='closed-box',vertical_datum='fixed-box-bottom',
            material_source='synthetic-constant-viscosity',method='direct',physical_mean_pressure_pa=pmean)

    def torques(self, pmean, origin):
        with self.closed(pmean) as p:
            xyz = p.coordinates('velocity'); owners = np.full(len(xyz),-1)
            owners[xyz[:,2] == 4.] = 0; owners[xyz[:,2] == 0.] = 1
            mapped = model.PreparedPlateBoundary3D(p,global_frame_id='planet-centred',origin_m=np.asarray(origin),
                local_axes_global=np.eye(3),plate_ids=('plate-a','plate-b'),node_plate_index=owners,
                geometry_source='synthetic-closed-box',max_work_bytes=4*1024**2)
            rate = (.3,-.2,0.)
            motions = [replace(motion(rate),plate_id=pid) for pid in ('plate-a','plate-b')]
            result = mapped.solve_prescribed(motions,0.,np.zeros_like(xyz),{s:0. for s in SIDES},**request())
            return mapped.descriptor().get('mode_net_flux_neutral'), result.exchange.array('torque_on_region_nm')

    def test_gauge_only_pressure_refuses_non_neutral_plate_torques(self):
        off_centre = [2.,5.,10.]
        # Each plate mode has net flux here: a 1000 Pa constant moves the two
        # plate torques by +/-(39000, -18000, 0) N m but leaves their sum.
        neutral, zero = self.torques(0., off_centre)
        _, shifted = self.torques(1000., off_centre)
        assert_allclose(shifted-zero, [[-39000.,18000.,0.],[39000.,-18000.,0.]], atol=1e-6)
        assert_allclose(shifted.sum(axis=0), zero.sum(axis=0), atol=1e-6)
        with self.assertRaisesRegex(TectonicsError,'undetermined pressure constant'):
            self.torques(None, off_centre)
        # Rotation about z is tangential on the owned top/bottom faces: neutral.
        self.assertEqual(neutral, [False, False, True, False, False, True])

    def test_neutral_modes_keep_gauge_free_torques_in_a_closed_box(self):
        centred = [-1.,-1.5,10.]
        neutral, gauge = self.torques(None, centred)
        self.assertEqual(neutral, [True]*6)
        for pmean in (0., 1000.):
            assert_allclose(self.torques(pmean, centred)[1], gauge, atol=1e-9)


if __name__ == '__main__':
    unittest.main()
