"""Synthetic W01 Stage-6 kinematic/reduction tests; no convection campaign."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import replace, FrozenInstanceError
from pathlib import Path
import hashlib
import json
import math
import pickle
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (PlanarGeometry, SphericalGeometry, SphericalFrame,
    SphericalChart, SphericalPatch, BoundaryRegion, build_boundary_network,
    build_spherical_atlas, Rotation, LocalCartesianFrame, RegionalGrid1D,
    TransportBoundary, advect_regional, GeometryLimits, TectonicsError)
from atlas_tectonics.regional_forcing import (PrescribedPlateMotion, PlanarRegionalSection,
    SphericalRegionalSection, RegionalReduction, RegionalMotionDefinition,
    PreparedRegionalForcing, MotionReductionError, save_regional_forcing, load_regional_forcing)
from atlas_tectonics.geological_records import GeologySource
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits
import atlas_tectonics.regional_forcing as rf

ROOT = Path(__file__).resolve().parents[1]
SOURCE = GeologySource('s6-control', 'synthetic', 'Explicit synthetic prescribed velocities and interval, not a force law')
UNITS = dict(length_unit='m', velocity_unit='m/s', angular_velocity_unit='rad/s')


def box(x0=0., y0=0., x1=10., y1=10., frame='plane'):
    return PlanarGeometry.polygon(((x0,y0),(x1,y0),(x1,y1),(x0,y1)), frame_id=frame)


def network(split=False, same_plate=False):
    domain = box()
    regions = (BoundaryRegion('whole', 'A', domain),) if not split else (
        BoundaryRegion('west', 'A', box(x1=5.)),
        BoundaryRegion('east', 'A' if same_plate else 'B', box(x0=5.)))
    return build_boundary_network(domain, regions)


def motion(plate='A', *, frame='plane', mode='planar-rigid', translation=(1.,0.,0.),
           omega=(0.,0.,0.), pivot=(0.,0.,0.), time=0., epoch='epoch'):
    return PrescribedPlateMotion(plate, frame, epoch, time, mode, translation, omega, pivot, SOURCE, **UNITS)


def planar(**changes):
    d = dict(section_id='section', frame_id='plane', epoch_id='epoch', time_s=0.,
             origin_m=(0.,5.,0.), direction_xy=(1.,0.), length_m=10.,
             frame_velocity_m_s=(0.,0.,0.), frame_angular_velocity_rad_s=(0.,0.,0.), source=SOURCE, **UNITS)
    d.update(changes)
    return PlanarRegionalSection(**d)


def definition(net=None, motions=None, **changes):
    net = network() if net is None else net
    d = dict(topology=net, motions=tuple(motion(p) for p in sorted(set(net.plate_ids))) if motions is None else motions,
             epoch_id='epoch', start_time_s=0., duration_s=.25, time_unit='s', source=SOURCE)
    d.update(changes)
    return RegionalMotionDefinition(**d)


def reduction(spherical=False):
    return RegionalReduction('great-circle-columns' if spherical else 'planar-columns', 'frozen-at-start', SOURCE, 1.)


def query(plan):
    return dict(frame_id=plan.section.frame_id, epoch_id=plan.definition.epoch_id, time_s=plan.definition.start_time_s)


def faces(plan, grid=None, **changes):
    kw = dict(frame_id=plan.section.frame_id, epoch_id=plan.definition.epoch_id,
              start_time_s=plan.definition.start_time_s, duration_s=plan.definition.duration_s)
    kw.update(changes)
    return plan.faces(grid or RegionalGrid1D(10, plan.section.length_m), **kw)


def atlas(sphere=None, one=True, rotation=None):
    # Independent octahedral ownership: east/west depends on the sign of X.
    import itertools
    sphere = sphere or SphericalFrame(2., 'world')
    vertices={'px':(1.,0.,0.),'nx':(-1.,0.,0.),'py':(0.,1.,0.),'ny':(0.,-1.,0.),'pz':(0.,0.,1.),'nz':(0.,0.,-1.)}
    patches=[]
    for sx,sy,sz in itertools.product((-1,1),repeat=3):
        ids=[('p' if sx>0 else 'n')+'x',('p' if sy>0 else 'n')+'y',('p' if sz>0 else 'n')+'z']
        if sx*sy*sz<0: ids[1],ids[2]=ids[2],ids[1]
        plate='A' if one else 'E' if sx>0 else 'W'
        centre=(sx,sy,sz) if rotation is None else tuple(rotation.apply([sx,sy,sz]))
        patches.append(SphericalPatch(f'{sx}{sy}{sz}',plate,plate,tuple(ids),SphericalChart(sphere,centre)))
    if rotation is not None: vertices={k:tuple(rotation.apply(v)) for k,v in vertices.items()}
    return build_spherical_atlas(sphere, vertices, tuple(patches))


def spherical(net=None, *, omega=(0.,0.,1.), frame_omega=(0.,0.,0.), start=(1.,0.,0.), pole=(0.,0.,1.), length=None):
    net=atlas() if net is None else net
    sphere=net.sphere if hasattr(net,'sphere') else net.domain.chart.sphere
    s=SphericalRegionalSection('arc',sphere,'epoch',0.,start,pole,
        sphere.radius_m*math.pi*.75 if length is None else length, frame_omega,SOURCE,**UNITS)
    mm=tuple(motion(p,frame=sphere.frame_id,mode='spherical-euler',translation=(0.,0.,0.),omega=omega) for p in sorted(set(net.plate_ids)))
    return definition(net,mm),s


def store_limits():
    return StoreLimits(4096, 8*1024**2, 32*1024**2, decoded_cache_bytes=65536,
                       max_manifest_bytes=1024**2, verified_cache_entries=32, sqlite_cache_bytes=65536)


class PlanarMotionChecks(unittest.TestCase):
    def test_uniform_motion_known_components_and_no_force_output(self):
        with PreparedRegionalForcing(definition(),planar(),reduction()) as p:
            a=p.project([0.,2.,10.],**query(p)); f=faces(p)
            assert_array_equal(a.components_m_s,[[1.,0.,0.]]*3)
            assert_array_equal(f.face_velocity_m_s,np.ones(11))
            self.assertEqual(f.duration_s,.25); self.assertEqual(f.start_time_s,0.)
            self.assertNotIn('stress',f.arrays()); self.assertNotIn('material',f.arrays())

    def test_translating_frame_subtracts_all_components(self):
        d=definition(motions=(motion(translation=(3.,4.,5.)),))
        s=planar(frame_velocity_m_s=(1.,4.,5.))
        with PreparedRegionalForcing(d,s,reduction()) as p:
            a=p.project([1.,7.],**query(p))
            assert_array_equal(a.absolute_velocity_m_s,[[3.,4.,5.]]*2)
            assert_array_equal(a.reference_velocity_m_s,[[1.,4.,5.]]*2)
            assert_array_equal(a.components_m_s,[[2.,0.,0.]]*2)
            assert_array_equal(faces(p).face_velocity_m_s,2*np.ones(11))

    def test_rotating_planar_frame_and_pivot_offset(self):
        # v=(-1.5,.5*x,0). Frame at (0,5) has velocity (0,.0,0)
        # plus .5*k cross (r-(0,5)) = (0,.5*x,0). Relative u=-1.5.
        d=definition(motions=(motion(omega=(0.,0.,.5)),))
        s=planar(frame_angular_velocity_rad_s=(0.,0.,.5))
        with PreparedRegionalForcing(d,s,reduction()) as p:
            a=p.project([0.,4.,10.],**query(p))
            assert_array_equal(a.components_m_s,[[-1.5,0.,0.]]*3)
            assert_array_equal(faces(p).face_velocity_m_s,-1.5*np.ones(11))

    def test_unrepresented_rotation_refused_even_if_one_query_cross_is_zero(self):
        d=definition(motions=(motion(translation=(0.,0.,0.),omega=(0.,0.,1.),pivot=(0.,5.,0.)),))
        with PreparedRegionalForcing(d,planar(),reduction()) as p:
            a=p.project([0.,2.,4.],**query(p))
            assert_array_equal(a.components_m_s,[[0.,0.,0.],[0.,2.,0.],[0.,4.,0.]])
            with self.assertRaises(MotionReductionError): faces(p)

    def test_vertical_and_tiny_transverse_flow_are_not_clipped(self):
        for v in ((1.,0.,2.),(1e-30,1e-30,0.)):
            with self.subTest(v=v), PreparedRegionalForcing(definition(motions=(motion(translation=v),)),planar(),reduction()) as p:
                a=p.project([1.],**query(p)); assert_array_equal(a.components_m_s[0],v)
                with self.assertRaises(MotionReductionError): faces(p)

    def test_section_reversal_changes_along_and_cross_not_up(self):
        d=definition(motions=(motion(translation=(2.,3.,4.)),))
        with PreparedRegionalForcing(d,planar(),reduction()) as p, PreparedRegionalForcing(d,planar(origin_m=(10.,5.,0.),direction_xy=(-1.,0.)),reduction()) as r:
            a=p.project([1.,7.],**query(p)); b=r.project([9.,3.],**query(r))
            assert_array_equal(a.positions_m,b.positions_m)
            assert_array_equal(b.components_m_s,[[-2.,-3.,4.]]*2)

    def test_frame_rotation_covariance(self):
        q=Rotation.from_axis_angle((0.,0.,1.),.41)
        domain=box(); xy=np.c_[np.asarray(domain._geom.exterior.coords)[:-1],np.zeros(4)]
        geom=PlanarGeometry.polygon(q.apply(xy)[:,:2],frame_id='rotated')
        net=build_boundary_network(geom,(BoundaryRegion('whole','A',geom),))
        # Keep this covariance fixture inside the domain: independently rounded
        # rotated endpoints need not lie EXACTLY on the rotated polygon boundary.
        v=tuple(q.apply((2.,0.,0.))); o=tuple(q.apply((1.,5.,0.))); t=tuple(q.apply((1.,0.,0.))[:2])
        with PreparedRegionalForcing(definition(net,(motion(frame='rotated',translation=v),)),planar(frame_id='rotated',origin_m=o,direction_xy=t,length_m=8.),reduction()) as p:
            assert_allclose(faces(p,RegionalGrid1D(8,8.)).face_velocity_m_s,2.,rtol=5e-15,atol=0)

    def test_scalar_and_vectorised_reference_agree_for_rigid_motion(self):
        d=definition(motions=(motion(translation=(.3,-.7,.5),omega=(0.,0.,.25)),))
        with PreparedRegionalForcing(d,planar(frame_velocity_m_s=(.5,1.,.4),frame_angular_velocity_rad_s=(0.,0.,-.1)),reduction()) as p:
            s=np.linspace(0.,10.,31)
            a=p.project(s,**query(p)); b=p.project(s,backend='reference',**query(p))
            assert_allclose(a.values_m_s,b.values_m_s,rtol=3e-15,atol=1e-15)

    def test_grid_refinement_reordering_and_batching_do_not_redraw_motion(self):
        d=definition(); before=d.identity
        with PreparedRegionalForcing(d,planar(),reduction()) as p:
            coarse=faces(p,RegionalGrid1D(4,10.)); fine=faces(p,RegionalGrid1D(8,10.))
            assert_array_equal(coarse.face_velocity_m_s,fine.face_velocity_m_s[::2])
            a=p.project([1.,9.,3.,1.],**query(p))
            b=list(p.project_batches(([1.,9.],[3.,1.]),**query(p)))
            assert_array_equal(a.values_m_s,np.vstack([x.values_m_s for x in b]))
            self.assertEqual(faces(p,RegionalGrid1D(4,10.)).forcing_id,coarse.forcing_id)
        self.assertEqual(before,d.identity)

    def test_unrepresented_plate_cannot_hide_between_coarse_faces(self):
        net=network(split=True)
        d=definition(net,(motion('A'),motion('B',translation=(1.,1.,0.))))
        with PreparedRegionalForcing(d,planar(),reduction()) as p:
            with self.assertRaises(MotionReductionError): faces(p,RegionalGrid1D(1,1.,1.))

    def test_all_geological_description_bytes_survive_queries(self):
        from test_w01_geological_description import rich
        case=rich(); old=case.descriptor(); identity=case.definition_id
        ms=tuple(motion(x,frame='test-frame',epoch='test-epoch') for x in ('p1','p2'))
        d=definition(case.topology,ms,epoch_id='test-epoch')
        with PreparedRegionalForcing(d,planar(frame_id='test-frame',epoch_id='test-epoch'),reduction()) as p:
            faces(p,RegionalGrid1D(3,9.)); faces(p,RegionalGrid1D(30,9.))
            p.project([9.,1.,5.,1.],**query(p))
        self.assertEqual(case.descriptor(),old); self.assertEqual(case.definition_id,identity)

    def test_no_covered_endpoints_shortcut_across_domain_hole(self):
        g=PlanarGeometry.polygon(((0,0),(10,0),(10,10),(0,10)),holes=(((4,4),(6,4),(6,6),(4,6)),),frame_id='plane')
        net=build_boundary_network(g,(BoundaryRegion('holed','A',g),))
        with self.assertRaises(MotionReductionError): PreparedRegionalForcing(definition(net),planar(),reduction())

    def test_outside_or_unresolvable_section_refused(self):
        with self.assertRaises(MotionReductionError): PreparedRegionalForcing(definition(),planar(length_m=11.),reduction())
        with PreparedRegionalForcing(definition(),planar(),reduction()) as p:
            with self.assertRaises(MotionReductionError): p.project([math.nextafter(10.,math.inf)],**query(p))
            with self.assertRaises(MotionReductionError): p.project([-1.],**query(p))


class OwnershipAndTransportChecks(unittest.TestCase):
    def test_internal_interface_cannot_hide_between_grid_faces(self):
        d=definition(network(True),(motion('A'),motion('B',translation=(2.,0.,0.))))
        with PreparedRegionalForcing(d,planar(),reduction()) as p:
            for n in (1,2,3,10):
                with self.subTest(cells=n), self.assertRaises(MotionReductionError):
                    faces(p,RegionalGrid1D(n,10.))
            assert_array_equal(faces(p,RegionalGrid1D(2,3.,1.)).face_velocity_m_s,[1.]*3)
            assert_array_equal(faces(p,RegionalGrid1D(2,3.,6.)).face_velocity_m_s,[2.]*3)

    def test_narrow_interior_plate_cannot_hide_behind_equal_endpoint_speeds(self):
        net=build_boundary_network(box(),(
            BoundaryRegion('left','A',box(x1=4.9)),
            BoundaryRegion('middle','B',box(x0=4.9,x1=5.1)),
            BoundaryRegion('right','A',box(x0=5.1))))
        d=definition(net,(motion('A'),motion('B',translation=(2.,0.,0.))))
        with PreparedRegionalForcing(d,planar(),reduction()) as p:
            with self.assertRaises(MotionReductionError): faces(p,RegionalGrid1D(1,10.))

    def test_shared_same_plate_regions_keep_all_memberships(self):
        with PreparedRegionalForcing(definition(network(True,True)),planar(),reduction()) as p:
            a=p.project([5.],**query(p)); self.assertEqual(len(a.owner_pairs),2)
            self.assertGreaterEqual(a.selected_rows[0],0)
            assert_array_equal(faces(p).face_velocity_m_s,np.ones(11))

    def test_distinct_owners_with_common_velocity_not_arbitrarily_assigned(self):
        with PreparedRegionalForcing(definition(network(True)),planar(),reduction()) as p:
            a=p.project([5.],**query(p)); self.assertEqual(a.selected_rows[0],-1)
            f=faces(p); self.assertEqual(f.samples.selected_rows[5],-1)
            self.assertEqual(f.face_velocity_m_s[5],1.)
            self.assertEqual(len(f.samples.owner_pairs),12)

    def test_discontinuity_preserved_and_internal_selection_not_fake_interface_law(self):
        d=definition(network(True),(motion('A'),motion('B',translation=(2.,0.,0.))))
        with PreparedRegionalForcing(d,planar(),reduction()) as p:
            a=p.project([5.],selections=('west',),**query(p))
            self.assertEqual(set(a.components_m_s[:,0]),{1.,2.})
            self.assertEqual(a.region_ids[a.owner_pairs[a.selected_rows[0],1]],'west')
            for selections in (None, (None,)*5+('west',)+(None,)*5):
                with self.assertRaises(MotionReductionError): faces(p,selections=selections)

    def test_explicit_endpoint_side_must_cover_adjacent_cell(self):
        d=definition(network(True),(motion('A'),motion('B',translation=(2.,0.,0.))))
        with PreparedRegionalForcing(d,planar(),reduction()) as p:
            grid=RegionalGrid1D(5,5.,5.)
            with self.assertRaises(MotionReductionError): faces(p,grid)
            with self.assertRaises(MotionReductionError): faces(p,grid,selections=('west',)+(None,)*5)
            f=faces(p,grid,selections=('east',)+(None,)*5)
            assert_array_equal(f.face_velocity_m_s,2*np.ones(6))
            with self.assertRaises(MotionReductionError): p.project([1.],selections=('east',),**query(p))

    def test_boundary_velocities_never_zeroed_and_reservoir_not_invented(self):
        with PreparedRegionalForcing(definition(),planar(),reduction()) as p: f=faces(p)
        with self.assertRaises(TectonicsError): f.validate_boundaries(left=TransportBoundary('closed'),right=TransportBoundary('open'))
        with self.assertRaises(TectonicsError): f.validate_boundaries(left=TransportBoundary('open'),right=TransportBoundary('open'))
        f.validate_boundaries(left=TransportBoundary('open',4.),right=TransportBoundary('open'))
        assert_array_equal(f.face_velocity_m_s,np.ones(11))

    def test_tiny_direct_regional_compatibility_witness(self):
        with PreparedRegionalForcing(definition(),planar(),reduction()) as p:
            f=faces(p,RegionalGrid1D(3,3.))
        for backend in ('reference','numba'):
            result=advect_regional([1.,2.,3.],f.face_velocity_m_s,f.grid,f.duration_s,
                left=TransportBoundary('open',4.,'explicit-reservoir'),right=TransportBoundary('open'),scheme='upwind',backend=backend)
            # H_i' = H_i - .25 * (outgoing donor - incoming donor).
            assert_array_equal(result.thickness_m,[1.75,1.75,2.75])
            self.assertEqual(result.inflow_m2,1.); self.assertEqual(result.outflow_m2,.75)
            self.assertEqual(result.balance_residual_m2,0.)

    def test_section_reversal_reverses_external_flow_without_boundary_repair(self):
        with PreparedRegionalForcing(definition(),planar(origin_m=(10.,5.,0.),direction_xy=(-1.,0.)),reduction()) as p:
            f=faces(p)
        assert_array_equal(f.face_velocity_m_s,-np.ones(11))
        with self.assertRaises(TectonicsError): f.validate_boundaries(left=TransportBoundary('open'),right=TransportBoundary('open'))
        f.validate_boundaries(left=TransportBoundary('open'),right=TransportBoundary('open',2.))


class SphericalMotionChecks(unittest.TestCase):
    def test_atlas_discontinuity_cannot_hide_between_grid_faces(self):
        net=atlas(one=False); d,s=spherical(net)
        d=replace(d,motions=(motion('E',frame='world',mode='spherical-euler',translation=(0.,0.,0.),omega=(0.,0.,1.)),
                            motion('W',frame='world',mode='spherical-euler',translation=(0.,0.,0.),omega=(0.,0.,2.))))
        with PreparedRegionalForcing(d,s,reduction(True)) as p:
            for n in (1,2,3):
                with self.subTest(cells=n), self.assertRaises(MotionReductionError):
                    faces(p,RegionalGrid1D(n,s.length_m))
            assert_allclose(faces(p,RegionalGrid1D(2,1.,.1)).face_velocity_m_s,2.,rtol=4e-15)

    def test_coplanar_arc_overlap_and_ambiguous_plane_are_not_missed(self):
        basis=np.eye(3)
        a=np.array((math.cos(.2),math.sin(.2),0.))
        b=np.array((math.cos(.4),math.sin(.4),0.))
        hits=rf._arc_seam_intervals(a,b,basis,1.)
        self.assertEqual(len(hits),1)
        self.assertLessEqual(hits[0][0],.2); self.assertGreaterEqual(hits[0][1],.4)
        self.assertEqual(rf._arc_seam_intervals(-a,-b,basis,1.),[])
        b[2]=1e-16
        self.assertEqual(rf._arc_seam_intervals(a,b,basis,1.),[(0.,1.)])

    def test_conditioned_network_discontinuity_cannot_hide_between_faces(self):
        sp=SphericalFrame(2.,'world'); chart=SphericalChart(sp,(1.,0.,0.))
        def patch(x0,x1):
            return SphericalGeometry.from_projected_wkb(box(x0,-.5,x1,.5).wkb,chart=chart)
        net=build_boundary_network(patch(-.5,.5),(
            BoundaryRegion('west','W',patch(-.5,0.)),
            BoundaryRegion('east','E',patch(0.,.5))))
        d,s=spherical(net,start=(1.,-.2,0.),length=1.)
        d=replace(d,motions=(motion('E',frame='world',mode='spherical-euler',translation=(0.,0.,0.),omega=(0.,0.,1.)),
                            motion('W',frame='world',mode='spherical-euler',translation=(0.,0.,0.),omega=(0.,0.,2.))))
        with PreparedRegionalForcing(d,s,reduction(True)) as p:
            with self.assertRaises(MotionReductionError): faces(p,RegionalGrid1D(1,1.))

    def test_short_rotated_seam_crossing_is_retained(self):
        q=Rotation.from_axis_angle((1.,2.,3.),.61)
        basis=q.apply(np.eye(3))
        point=q.apply((math.cos(.4),math.sin(.4),0.))
        a=rf._unit(point-1e-9*basis[2]); b=rf._unit(point+1e-9*basis[2])
        hits=rf._arc_seam_intervals(a,b,basis,1.)
        self.assertTrue(any(lo <= .4 <= hi for lo,hi in hits))

    def test_axial_rotation_exact_speed_and_reference_subtraction(self):
        d,s=spherical(frame_omega=(0.,0.,.25))
        with PreparedRegionalForcing(d,s,reduction(True)) as p:
            f=faces(p,RegionalGrid1D(12,s.length_m))
            assert_allclose(f.face_velocity_m_s,1.5,rtol=4e-15,atol=0.)
            assert_allclose(f.samples.components_m_s[:,1:],0.,rtol=0.,atol=4e-16)
            assert_allclose(np.linalg.norm(f.samples.positions_m,axis=1),2.,rtol=4e-15)
            a=p.project([.1,.7,2.],backend='reference',**query(p)); b=p.project([.1,.7,2.],**query(p))
            assert_allclose(a.values_m_s,b.values_m_s,rtol=2e-15,atol=4e-16)

    def test_pole_crossing_has_no_longitude_singularity(self):
        d,s=spherical(omega=(0.,-1.,0.),pole=(0.,-1.,0.))
        with PreparedRegionalForcing(d,s,reduction(True)) as p:
            f=faces(p,RegionalGrid1D(3,s.length_m))
            assert_allclose(f.face_velocity_m_s,2.,rtol=4e-15)
            # Mid-arc distances pi on radius two reaches the north pole.
            a=p.project([math.pi],**query(p)); assert_allclose(a.positions_m[0],[0.,0.,2.],atol=3e-16)

    def test_nonaxial_rotation_retains_cross_component_and_refuses_reduction(self):
        d,s=spherical(omega=(0.,1.,1.))
        with PreparedRegionalForcing(d,s,reduction(True)) as p:
            a=p.project([0.],**query(p)); assert_array_equal(a.components_m_s,[[2.,-2.,0.]])
            with self.assertRaises(MotionReductionError): faces(p)

    def test_frame_corotation_can_make_relative_spherical_motion_zero(self):
        d,s=spherical(omega=(.3,.4,.5),frame_omega=(.3,.4,.5))
        with PreparedRegionalForcing(d,s,reduction(True)) as p:
            f=faces(p); assert_array_equal(f.face_velocity_m_s,np.zeros(11))
            assert_allclose(f.samples.absolute_velocity_m_s,f.samples.reference_velocity_m_s,rtol=0,atol=0)

    def test_spherical_section_reversal(self):
        d,s=spherical(length=math.pi)
        rev=replace(s,start_direction=(0.,1.,0.),pole_direction=(0.,0.,-1.))
        with PreparedRegionalForcing(d,s,reduction(True)) as p, PreparedRegionalForcing(d,rev,reduction(True)) as q:
            f=faces(p); r=faces(q)
            assert_allclose(f.face_velocity_m_s,-r.face_velocity_m_s[::-1],rtol=4e-15)
            assert_allclose(f.samples.positions_m,r.samples.positions_m[::-1],atol=6e-16)

    def test_spherical_frame_rotation_covariance(self):
        q=Rotation.from_axis_angle((1.,2.,3.),.61)
        net=atlas(rotation=q)
        start=tuple(q.apply((1.,0.,0.))); pole=tuple(q.apply((0.,0.,1.)))
        d,s=spherical(net,omega=tuple(q.apply((0.,0.,1.))),start=start,pole=pole)
        with PreparedRegionalForcing(d,s,reduction(True)) as p:
            assert_allclose(faces(p).face_velocity_m_s,2.,rtol=5e-15)

    def test_interplate_atlas_seam_discontinuity_not_averaged(self):
        net=atlas(one=False); d,s=spherical(net,length=math.pi*1.5)
        d=replace(d,motions=(motion('E',frame='world',mode='spherical-euler',translation=(0.,0.,0.),omega=(0.,0.,1.)),
                            motion('W',frame='world',mode='spherical-euler',translation=(0.,0.,0.),omega=(0.,0.,2.))))
        with PreparedRegionalForcing(d,s,reduction(True)) as p:
            a=p.project([math.pi],**query(p)); self.assertEqual(len(a.owner_pairs),2)
            self.assertEqual(a.selected_rows[0],-1)
            with self.assertRaises(MotionReductionError): faces(p,RegionalGrid1D(3,s.length_m))

    def test_conditioned_spherical_network_uses_directions_not_radius_scaled_chart(self):
        # Small R catches accidentally passing physical positions to _project,
        # whose conditioning criterion explicitly expects UNIT directions.
        sp=SphericalFrame(.01,'small'); chart=SphericalChart(sp,(1.,0.,0.))
        g=SphericalGeometry.from_projected_wkb(box(-.5,-.5,.5,.5).wkb,chart=chart)
        net=build_boundary_network(g,(BoundaryRegion('whole','A',g),))
        d,s=spherical(net,length=.001)
        with PreparedRegionalForcing(d,s,reduction(True)) as p:
            assert_allclose(faces(p).face_velocity_m_s,.01,rtol=4e-15)

    def test_radius_and_horizon_mismatches_refused(self):
        d,s=spherical()
        with self.assertRaises(MotionReductionError): PreparedRegionalForcing(d,replace(s,sphere=SphericalFrame(3.,'world')),reduction(True))
        with self.assertRaises(MotionReductionError): replace(s,length_m=2.*math.pi)
        with self.assertRaises(MotionReductionError): replace(s,pole_direction=(1.,0.,1.))
        with self.assertRaises(MotionReductionError): motion(mode='spherical-euler',translation=(1.,0.,0.))


class ValidationResourceAndPersistenceChecks(unittest.TestCase):
    def test_malformed_units_epoch_and_missing_motion(self):
        with self.assertRaises(TypeError): PrescribedPlateMotion('A','plane','epoch',0.,'planar-rigid',(1.,0.,0.),(0.,0.,0.),(0.,0.,0.),SOURCE)
        for change in ({'velocity_unit':'mm/yr'},{'angular_velocity_unit':'deg/Ma'},{'length_unit':'km'}):
            with self.subTest(change=change), self.assertRaises(MotionReductionError): replace(motion(),**change)
        with self.assertRaises(MotionReductionError): definition(time_unit='yr')
        with self.assertRaises(MotionReductionError): definition(motions=(motion(epoch='other'),))
        with self.assertRaises(MotionReductionError): definition(network(True),(motion(),))
        with self.assertRaises(MotionReductionError): definition(motions=(motion(),motion()))
        with self.assertRaises(MotionReductionError): motion(omega=(1.,0.,0.))

    def test_requested_interval_and_query_metadata_not_silently_changed(self):
        with PreparedRegionalForcing(definition(),planar(),reduction()) as p:
            for kw in ({'duration_s':.2},{'start_time_s':1.},{'epoch_id':'other'},{'frame_id':'other'}):
                with self.subTest(kw=kw), self.assertRaises(MotionReductionError): faces(p,**kw)
            with self.assertRaises(MotionReductionError): p.project([1.],frame_id='plane',epoch_id='epoch',time_s=1.)
            with self.assertRaises(MotionReductionError): p.project([1.],selections=['whole'],**query(p))
        with self.assertRaises(TectonicsError): definition(motions=(motion(time=1e30),),start_time_s=1e30,duration_s=.25)

    def test_explicit_reduction_only_no_ignore_flags(self):
        with self.assertRaises(MotionReductionError): RegionalReduction('project-anything','frozen-at-start',SOURCE,1.)
        with self.assertRaises(MotionReductionError): RegionalReduction('planar-columns','ignore-cross',SOURCE,1.)
        with self.assertRaises(MotionReductionError): PreparedRegionalForcing(definition(),planar(),reduction(True))

    def test_source_kind_and_motion_identity_preserved(self):
        d=definition(); authored=replace(d,source=replace(SOURCE,kind='authored'))
        generated=replace(d,source=replace(SOURCE,kind='generated'))
        self.assertNotEqual(authored.identity,generated.identity)
        with PreparedRegionalForcing(authored,planar(),reduction()) as p: a=faces(p)
        with PreparedRegionalForcing(generated,planar(),reduction()) as p: b=faces(p)
        assert_array_equal(a.face_velocity_m_s,b.face_velocity_m_s)
        self.assertNotEqual(a.forcing_id,b.forcing_id)
        self.assertEqual(a.descriptor()['samples']['definition']['source']['kind'],'authored')

    def test_immutable_inputs_results_and_private_array_descriptors(self):
        d=definition(); s=planar()
        with PreparedRegionalForcing(d,s,reduction()) as p:
            a=p.project([1.,2.],**query(p)); f=faces(p)
            with self.assertRaises(MotionReductionError): p.definition=definition()
            with self.assertRaises(FrozenInstanceError): s.length_m=5.
            with self.assertRaises(ValueError): f.face_velocity_m_s[0]=0.
            with self.assertRaises(ValueError): a.values_m_s.setflags(write=True)
            view=a.values_m_s; view.shape=(18,)
            self.assertEqual(a.values_m_s.shape,(2,9))
            desc=f.descriptor(); desc['grid']['cells']=123
            self.assertEqual(f.grid.cells,10)
        self.assertEqual(pickle.loads(pickle.dumps(d)).identity,d.identity)

    def test_cancelled_query_and_budget_refusal_release_reservations(self):
        b=WorkBudget(16*1024**2); event=threading.Event()
        with PreparedRegionalForcing(definition(),planar(),reduction(),budget=b) as p:
            before=b.reserved_bytes; event.set()
            with self.assertRaises(CancelledError): p.project([1.],cancel=event,**query(p))
            self.assertEqual(b.reserved_bytes,before)
            with self.assertRaises(MemoryLimitError): p.project(np.linspace(0,10,100000),**query(p))
            self.assertEqual(b.reserved_bytes,before)
            event.clear(); assert_array_equal(faces(p).face_velocity_m_s,np.ones(11))
        self.assertEqual(b.reserved_bytes,0)
        tiny=WorkBudget(1)
        with self.assertRaises(MemoryLimitError): PreparedRegionalForcing(definition(),planar(),reduction(),budget=tiny)
        self.assertEqual(tiny.reserved_bytes,0)

    def test_late_cancel_does_not_publish_or_change_input(self):
        class Late:
            def __init__(self): self.count=0
            def is_set(self):
                self.count+=1
                return self.count>=5
        with PreparedRegionalForcing(definition(),planar(),reduction()) as p:
            baseline=faces(p); token=Late()
            with self.assertRaises(CancelledError): faces(p,cancel=token)
            self.assertEqual(faces(p).forcing_id,baseline.forcing_id)

    def test_close_and_source_mutation_refuse_without_leaks(self):
        b=WorkBudget(16*1024**2)
        with PreparedRegionalForcing(definition(),planar(),reduction(),budget=b) as p:
            with mock.patch.object(rf,'_METHOD','mutated'):
                with self.assertRaises(TectonicsError): faces(p)
            faces(p)
        self.assertEqual(b.reserved_bytes,0)
        with self.assertRaises(MotionReductionError): p.project([1.],**query(p))

    def test_inventory_metric_is_explicit_positive_and_identity_bound(self):
        with self.assertRaises(TypeError): RegionalReduction('planar-columns','frozen-at-start',SOURCE)
        for w in (0.,-1.,float('nan'),True):
            with self.assertRaises(TectonicsError): replace(reduction(),reference_width_m=w)
        with PreparedRegionalForcing(definition(),planar(),reduction()) as p:
            a=faces(p)
        with PreparedRegionalForcing(definition(),planar(),replace(reduction(),reference_width_m=2.)) as p:
            b=faces(p)
        assert_array_equal(a.face_velocity_m_s,b.face_velocity_m_s)
        self.assertNotEqual(a.forcing_id,b.forcing_id)

    def test_prepared_transforms_are_immutable_and_result_constructors_refuse(self):
        with PreparedRegionalForcing(definition(),planar(),reduction()) as p:
            for name in ('definition','_basis','_coefficients','_motion_data','_checks','_execution_id','_index','_discontinuities'):
                with self.subTest(name=name), self.assertRaises(MotionReductionError):
                    setattr(p,name,None)
            self.assertEqual(len(faces(p).face_velocity_m_s),11)
        for cls in (rf.SectionMotionSamples, rf.RegionalFaceForcing):
            with self.assertRaises(MotionReductionError): cls()

    def test_concurrent_queries_have_no_hidden_scratch(self):
        with PreparedRegionalForcing(definition(),planar(),reduction()) as p:
            expected=faces(p).forcing_id
            with ThreadPoolExecutor(2) as pool:
                ids=list(pool.map(lambda _:faces(p).forcing_id,range(4)))
            self.assertEqual(ids,[expected]*4)

    def test_store_roundtrip_and_existing_cache_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            with PreparedRegionalForcing(definition(),planar(),reduction()) as p: f=faces(p)
            with ArrayStore(Path(tmp)/'forcing.sqlite',store_limits()) as store:
                save_regional_forcing(f,store); save_regional_forcing(f,store)
                a=load_regional_forcing(store,f.forcing_id); b=load_regional_forcing(store,f.forcing_id)
                self.assertEqual(a.forcing_id,f.forcing_id); self.assertEqual(b.forcing_id,f.forcing_id)
                for name,value in f.arrays().items(): assert_array_equal(a.arrays()[name],value)
                self.assertIsNone(load_regional_forcing(store,'0'*64))

    def test_spherical_store_roundtrip(self):
        d,s=spherical()
        with tempfile.TemporaryDirectory() as tmp:
            with PreparedRegionalForcing(d,s,reduction(True)) as p: f=faces(p)
            with ArrayStore(Path(tmp)/'forcing.sqlite',store_limits()) as store:
                save_regional_forcing(f,store); restored=load_regional_forcing(store,f.forcing_id)
                self.assertEqual(f.forcing_id,restored.forcing_id)
                assert_array_equal(f.face_velocity_m_s,restored.face_velocity_m_s)

    def test_corrupt_payload_and_policy_are_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with PreparedRegionalForcing(definition(),planar(),reduction()) as p: f=faces(p)
            with ArrayStore(Path(tmp)/'forcing.sqlite',store_limits()) as store:
                save_regional_forcing(f,store)
                original=store.get
                def corrupt(invocation,**kwargs):
                    a=original(invocation,**kwargs)
                    if invocation==f.forcing_id:
                        a=dict(a);a['face_velocity_m_s']=a['face_velocity_m_s'].copy();a['face_velocity_m_s'][0]+=1.
                    return a
                with mock.patch.object(store,'get',side_effect=corrupt):
                    with self.assertRaises(MotionReductionError): load_regional_forcing(store,f.forcing_id)
                meta=store.metadata; bad=f.descriptor(); bad['samples']['reduction']['temporal_rule']='ignore'
                with mock.patch.object(store,'metadata',side_effect=lambda key: bad if key==f.forcing_id else meta(key)):
                    with self.assertRaises(MotionReductionError): load_regional_forcing(store,f.forcing_id)

    def test_fresh_process_relocated_source_and_changed_source_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            with PreparedRegionalForcing(definition(),planar(),reduction()) as p: f=faces(p)
            db=tmp/'forcing.sqlite'
            with ArrayStore(db,store_limits()) as store: save_regional_forcing(f,store)
            source=tmp/'src'; shutil.copytree(ROOT/'src',source)
            code='''import sys
sys.path.insert(0,sys.argv[1])
from atlas_tectonics.regional_forcing import load_regional_forcing,MotionReductionError
from atlas_tectonics.storage import ArrayStore,StoreLimits
with ArrayStore(sys.argv[2],StoreLimits(4096,8*1024**2,32*1024**2,decoded_cache_bytes=65536,max_manifest_bytes=1024**2,verified_cache_entries=32,sqlite_cache_bytes=65536)) as s:
 try:
  f=load_regional_forcing(s,sys.argv[3])
  assert sys.argv[4]=='same' and f.forcing_id==sys.argv[3]
  print('same-source forcing exact')
 except MotionReductionError:
  assert sys.argv[4]=='changed'
  print('changed-source forcing refused')
'''
            for mode in ('same','changed'):
                if mode=='changed':
                    pth=source/'atlas_tectonics/regional_forcing.py'
                    pth.write_bytes(pth.read_bytes()+b'\n# deliberate changed-source test\n')
                run=subprocess.run([sys.executable,'-I','-B','-c',code,str(source),str(db),f.forcing_id,mode],capture_output=True,text=True,timeout=30)
                self.assertEqual(run.returncode,0,run.stderr); self.assertIn(mode+'-source forcing',run.stdout)


if __name__ == '__main__':
    unittest.main()
