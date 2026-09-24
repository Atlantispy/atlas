"""Frozen W09 E1-E3 and finite-material implicit evolution contracts."""
from concurrent.futures import CancelledError
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import math
import unittest

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
from atlas_tectonics.w09_erosion import (PreparedErosion, ErosionTag,
    ErosionExhaustionError, cover_rates)


TAG=ErosionTag('rock-A',1.,-100.,-1.,'synthetic-rock-A','synthetic-signed-reference')


def plan(**kwargs):
    options=dict(rock_erodibility=[[1.],[0.]],sediment_erodibility=0.,
                 frame_id='synthetic-SI',datum_id='synthetic-z',source_id='E1-E3')
    options.update(kwargs)
    return PreparedErosion([1.,0.],[1,-1],[1.,1.],[0.,0.],[TAG],**options)


def state(p, height=4., soil=0.):
    return p.initialise([[[height]],[[0.]]],[[soil],[0.]])


class W09ErosionTests(unittest.TestCase):
    def test_e1_discrete_and_time_refinement(self):
        with plan() as p:
            initial=state(p)
            out=p.advance(initial,1.,discharge_m3_s=1.,forcing_id='E1')
            self.assertAlmostEqual(p.heights(out)[0],2.,places=12)
            self.assertAlmostEqual(out.released_rock_kg[0,0],2.,places=12)
            errors=[]
            for n in (16,32,64):
                out=p.advance(initial,1.,discharge_m3_s=1.,forcing_id='E1',partitions=n)
                z=p.heights(out)[0]
                self.assertAlmostEqual(z,4/(1+1/n)**n,places=12)
                errors.append(abs(z-4*math.exp(-1))/(4*math.exp(-1)))
            self.assertLess(errors[-1],.01)
            self.assertGreater(errors[0]/errors[1],1.5)
            self.assertGreater(errors[1]/errors[2],1.5)

    def test_e2_rates_threshold_and_dry(self):
        np.testing.assert_allclose(cover_rates(math.log(2),1,.02,.04,.004,.008),[.008,.016],rtol=1e-10,atol=1e-12)
        self.assertEqual(cover_rates(0,1,.02,.04,.004,.008)[1],0)
        self.assertEqual(cover_rates(1,1,.02,.04,.004,.008,wet=False),(0,0))
        self.assertEqual(cover_rates(1,1,.004,.008,.004,.008),(0,0))

    def test_e3_exact_finite_release_signed_heat_and_no_replay(self):
        with plan() as p:
            initial=state(p,2.)
            with self.assertRaises(ErosionExhaustionError) as caught:
                p.prescribed_release(initial,0,3.,1.,source_id='E3')
            out=caught.exception.state
            self.assertAlmostEqual(out.time_s,2/3,places=15)
            self.assertEqual(out.released_rock_kg[0,0],2.)
            self.assertEqual(p.released_enthalpy_J(out)[0,0],-200.)
            with self.assertRaises(ErosionExhaustionError) as repeated:
                p.prescribed_release(out,0,3.,1.,source_id='E3')
            self.assertEqual(repeated.exception.state.released_rock_kg[0,0],2.)
            np.testing.assert_array_equal(initial.rock_mass_kg,[[[2.]],[[0.]]])

    def test_updated_receiver_not_frozen_old_slope(self):
        with PreparedErosion([1,1,0],[1,2,-1],[1,1,1],[0,0,0],[TAG],
                rock_erodibility=[[1],[1],[0]],sediment_erodibility=0,
                frame_id='f',datum_id='d',source_id='chain') as p:
            initial=p.initialise([[[4]],[[2]],[[0]]])
            out=p.advance(initial,1,discharge_m3_s=1,forcing_id='chain')
            np.testing.assert_allclose(p.heights(out),[2.5,1,0],rtol=1e-12,atol=1e-12)

    def test_covered_cell_satisfies_both_implicit_equations(self):
        with plan(sediment_erodibility=.4,roughness_m=.7,rock_threshold_m_s=.03,
                  sediment_threshold_m_s=.04) as p:
            initial=state(p,4.,soil=.6)
            out=p.advance(initial,.8,discharge_m3_s=1,forcing_id='cover')
            h=out.soil_mass_kg[0,0]/.6
            z=p.heights(out)[0]
            er,es=cover_rates(h,.7,z,.4*z,.03,.04)
            self.assertAlmostEqual(out.released_rock_kg[0,0],.8*er,places=12)
            self.assertAlmostEqual(out.released_soil_kg[0,0],.8*es,places=12)
            self.assertAlmostEqual(z,5-out.released_rock_kg[0,0]-out.released_soil_kg[0,0]/.6,places=12)

    def test_dry_flooded_and_high_threshold_do_not_erode(self):
        with plan(rock_threshold_m_s=4.) as p:
            initial=state(p)
            for q,mask in ((0,None),(1,[True,False]),(1,None)):
                out=p.advance(initial,1,discharge_m3_s=q,inundated=mask,forcing_id='no-erosion')
                np.testing.assert_array_equal(out.rock_mass_kg,initial.rock_mass_kg)

    def test_layer_event_changes_properties_and_preserves_cohorts(self):
        tag2=ErosionTag('B',2.,50.,-2.,'synthetic-B','synthetic-signed-reference')
        with PreparedErosion([1,0],[1,-1],[1,1],[0,0],[TAG,tag2],
                rock_erodibility=[[1,.25],[0,0]],sediment_erodibility=0,
                frame_id='f',datum_id='d',source_id='layers') as p:
            initial=p.initialise([[[1,0],[0,6]],[[0,0],[0,0]]])
            out=p.advance(initial,1,discharge_m3_s=1,forcing_id='layers')
            # First BE event is 1/3 s: old height4 ->3. Remaining2/3 with K=.25.
            self.assertAlmostEqual(p.heights(out)[0],3/(1+.25*2/3),places=11)
            self.assertEqual(out.released_rock_kg[0,0],1.)
            self.assertAlmostEqual(out.released_rock_kg[0,1],2*(3-3/(1+.25*2/3)),places=11)
            self.assertEqual(out.accepted_intervals,2)
            out.check_balance()
            exact=3*math.exp(-.25*(1-math.log(4/3)))
            errors=[]
            for partitions in (16,32,64):
                refined=p.advance(initial,1,discharge_m3_s=1,forcing_id='layers',partitions=partitions)
                errors.append(abs(p.heights(refined)[0]-exact)/exact)
            self.assertLess(errors[-1],.01)
            self.assertGreater(errors[0]/errors[1],1.5)
            self.assertGreater(errors[1]/errors[2],1.5)

    def test_finite_substrate_exhaustion_has_valid_endpoint(self):
        with PreparedErosion([1,0],[1,-1],[1,1],[3,0],[TAG],
                rock_erodibility=[[1],[0]],sediment_erodibility=0,
                frame_id='f',datum_id='d',source_id='finite') as p:
            initial=state(p,1.)
            with self.assertRaises(ErosionExhaustionError) as caught:
                p.advance(initial,1,discharge_m3_s=1,forcing_id='finite')
            out=caught.exception.state
            self.assertAlmostEqual(out.time_s,1/3,places=12)
            self.assertEqual(out.rock_mass_kg[0,0,0],0.)
            self.assertEqual(out.released_rock_kg[0,0],1.)

    def test_tiny_soil_transfer_not_erased_by_height_subtraction(self):
        with plan(rock_erodibility=[[0],[0]],sediment_erodibility=1e-18) as p:
            initial=state(p,4.,soil=.6)
            out=p.advance(initial,1,discharge_m3_s=1,forcing_id='tiny')
            self.assertGreater(out.released_soil_kg[0,0],0.)
            self.assertAlmostEqual(out.released_soil_kg[0,0]/(5e-18*(-math.expm1(-1))),1.,places=12)

    def test_latest_reuse_is_exact_and_forcing_change_computes(self):
        with plan() as p:
            initial=state(p)
            out=p.advance(initial,1,discharge_m3_s=1,forcing_id='same')
            same=p.advance(initial,1,discharge_m3_s=1,forcing_id='same')
            self.assertEqual(same.state_id,out.state_id)
            other=p.advance(initial,1,discharge_m3_s=4,forcing_id='changed')
            self.assertNotEqual(other.state_id,out.state_id)
            self.assertEqual(p.statistics()['latest_hits'],1)
            with self.assertRaises(ValueError): out.rock_mass_kg.setflags(write=True)

    def test_cancel_budget_invalid_and_wrong_plan(self):
        owner=WorkBudget(128*1024**2)
        with plan(budget=owner) as p:
            initial=state(p)
            event=Event(); event.set()
            with self.assertRaises(CancelledError):
                p.advance(initial,1,discharge_m3_s=1,forcing_id='cancel',cancel=event)
            with self.assertRaises(TectonicsError):
                p.advance(initial,1,discharge_m3_s=True,forcing_id='bad')
            with self.assertRaises(TectonicsError):
                p.advance(initial,1,discharge_m3_s=1,forcing_id='bad',partitions=257)
        self.assertEqual(owner.reserved_bytes,0)
        with self.assertRaises(MemoryLimitError): plan(budget=WorkBudget(1024))
        with plan(source_id='other') as p:
            with self.assertRaises(TectonicsError): p.heights(initial)

    def test_checkpoint_continuation_is_exact(self):
        with TemporaryDirectory() as root:
            owner=WorkBudget(128*1024**2)
            with ArrayStore(Path(root)/'erosion.sqlite',limits=StoreLimits(65536,1048576,16777216),
                    compression=Compression(codec='raw',shuffle='none'),budget=owner) as store:
                with plan(budget=owner,store=store) as p:
                    initial=state(p)
                    midway=p.advance(initial,.5,discharge_m3_s=1,forcing_id='first')
                    key=p.checkpoint(midway)
                    expected=p.advance(midway,.5,discharge_m3_s=1,forcing_id='second')
                with plan(budget=owner,store=store) as p:
                    restored=p.restore(key)
                    out=p.advance(restored,.5,discharge_m3_s=1,forcing_id='second')
                    self.assertEqual(out.state_id,expected.state_id)
                    for name,a in out.arrays().items(): np.testing.assert_array_equal(a,expected.arrays()[name])

    def test_signed_heat_and_release_time_numeric_range_refuse(self):
        huge=ErosionTag('huge',1.,1e308,-1.,'huge','synthetic-reference')
        with PreparedErosion([1,0],[1,-1],[1,1],[0,0],[huge],
                rock_erodibility=[[1],[0]],sediment_erodibility=0,
                frame_id='f',datum_id='d',source_id='range') as p:
            with self.assertRaises(TectonicsError):p.initialise([[[4]],[[0]]])
        with plan() as p:
            late=p.initialise([[[4]],[[0]]],time_s=1e20)
            with self.assertRaises(TectonicsError):
                p.prescribed_release(late,0,1.,1.,source_id='unrepresentable')


if __name__ == '__main__': unittest.main()
