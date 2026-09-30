"""Focused public W07 surface state/evolution tests, not B09 acceptance.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError, ThreadPoolExecutor
import threading
from time import perf_counter
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.free_surface import PreparedFreeSurface2D
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot, RegionalMechanicsScales
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.surface_geometry import cell_volume_and_flux


MEASUREMENTS=[]


def plan(nx=4,nz=2,**changes):
    values=dict(width_m=2.,bottom_m=0.,reference_height_m=1.,viscosity_pa_s=1.,
        density_kg_m3=1.,gravity_m_s2=1.,external_pressure_pa=0.,strike_width_m=1.,
        scales=RegionalMechanicsScales(1.,1.),frame_id='synthetic surface',
        vertical_datum='flat bottom zero',material_source='homogeneous isothermal control',
        load_source='explicit self gravity and external pressure',method='direct')
    values.update(changes)
    return PreparedFreeSurface2D(nx,nz,**values)


def altered(state,metadata=None,arrays=None):
    description=state.descriptor()
    if metadata:description.update(metadata)
    fields={key:state.array(key) for key in state.array_names}
    if arrays:fields.update(arrays)
    return RegionalMechanicalSnapshot(description,fields)


class FreeSurfaceTests(unittest.TestCase):
    def test_flat_rest_physical_pressure_and_nonunit_si(self):
        with plan(width_m=4000.,reference_height_m=1000.,viscosity_pa_s=1e18,
                  density_kg_m3=3300.,gravity_m_s2=9.81,external_pressure_pa=1e5,
                  strike_width_m=250.,scales=RegionalMechanicsScales(2000.,1e-10)) as p:
            top=np.full(9,1000.)
            state=p.initial_state(top,epoch_id='flat SI',time_s=120.)
            result=p.mechanics(state)
            points=result.array('quadrature_points_m')
            exact=1e5+3300.*9.81*(1000.-points[...,1])
            np.testing.assert_allclose(result.array('pressure_q_pa'),exact,rtol=1e-11,atol=1e-7)
            self.assertLess(np.max(np.abs(result.array('velocity_nodes_m_s')))/1e-10,1e-9)
            np.testing.assert_allclose(state.array('cell_mass_kg').sum(),4000.*1000.*3300.*250.,rtol=1e-14)
            advance=p.advance(state,1000.,steps=1)
            np.testing.assert_allclose(advance.state.array('mesh_nodes_m'),state.array('mesh_nodes_m'),atol=1e-10,rtol=0.)
            self.assertTrue(advance.mechanics.descriptor()['diagnostics']['gates_passed'])
            self.assertEqual(advance.state.descriptor()['time_s'],1120.)
            self.assertFalse(advance.descriptor()['heat_or_heterogeneous_remap'])
            MEASUREMENTS.append(dict(case='flat SI',diagnostics=result.descriptor()['diagnostics'],
                                     budget_peak=p.statistics()['budget']['peak_reserved_bytes']))

    def test_relaxation_gate_refuses_steps_that_would_grow_topography(self):
        # R1 (s08-1): with z=rate*dt above 2, SSP-RK2 amplifies a relaxing mode
        # by 1-z+z^2/2 per step; 3 steps at z=4 grew a cosine 128-fold, accepted.
        rate=0.14424591716886523
        with plan() as p:
            x=np.linspace(0.,2.,9)
            state=p.initial_state(1.+1e-4*np.cos(np.pi*x),epoch_id='relaxation gate')
            for z,steps in ((.5,1),(3.,1),(3.,4),(4.,3)):
                with self.subTest(z=z,steps=steps),self.assertRaisesRegex(TectonicsError,'relaxation limit'):
                    p.advance(state,z*steps/rate,steps=steps)
            # The refusal names an admissible partition; it tracks the analysis.
            with self.assertRaisesRegex(TectonicsError,'at least 12 steps'):
                p.advance(state,1./rate,steps=1)
            result=p.advance(state,1./rate,steps=12)
            fine=p.advance(state,1./rate,steps=96)
            amplitude=lambda s:float(np.dot(s.array('mesh_nodes_m')[-1,:,1]-1.,np.cos(np.pi*x))/5.)
            # Time-only error after one e-folding is about z^2/6 (z<=0.1/1.114).
            self.assertLess(abs(amplitude(result.state)/amplitude(fine.state)-1.),2e-3)
            self.assertLess(amplitude(result.state),1e-4)
            self.assertTrue(all(i['relaxation_step']<=.1 for i in result.descriptor()['intervals']))
        with self.assertRaisesRegex(TectonicsError,'above 0.25'):
            plan(relaxation_step_limit=.3)
        with plan(relaxation_step_limit=.05) as p:
            state=p.initial_state(1.+1e-4*np.cos(np.pi*np.linspace(0.,2.,9)),epoch_id='tighter')
            with self.assertRaisesRegex(TectonicsError,'at least 23 steps'):
                p.advance(state,1./rate,steps=12)
            self.assertEqual(p.descriptor()['relaxation_step_limit'],.05)

    def test_sloped_surface_steps_obey_the_surface_courant_limit(self):
        # Verification finding: on sloped topography surface-parallel flow adds
        # advective modes (lambda*dt ~ 2.06i*C) that SSP-RK2 amplifies at any dt;
        # a relaxation-admitted single step grew a seeded mode 1.135-fold.
        from atlas_tectonics.free_surface import RELAXATION_RATE_COEFFICIENT
        with plan(16,2,budget=WorkBudget(1<<30)) as p:
            x=np.linspace(0.,2.,33)
            state=p.initial_state(1.+.3*np.cos(np.pi*x/2.),epoch_id='sloped')
            dt=.1/(RELAXATION_RATE_COEFFICIENT*1.3)*.97
            with self.assertRaisesRegex(TectonicsError,'surface Courant limit 0.1') as caught:
                p.advance(state,dt,steps=1)
            needed=int(str(caught.exception).split('at least ')[1].split()[0])
            result=p.advance(state,dt,steps=needed)
            self.assertTrue(all(i['surface_courant']<=.1 and i['relaxation_step']<=.1
                                for i in result.descriptor()['intervals']))
        with self.assertRaisesRegex(TectonicsError,'above 0.1'):
            plan(surface_courant_limit=.11)
        # A vanishing declared limit refuses cleanly instead of overflowing.
        with plan(relaxation_step_limit=5e-324) as p:
            state=p.initial_state(1.+1e-4*np.cos(np.pi*np.linspace(0.,2.,9)),epoch_id='tiny')
            with self.assertRaisesRegex(TectonicsError,'more than the 256'):
                p.advance(state,1.,steps=1)

    def test_si_relaxation_step_is_refused_not_published(self):
        # A 24,957-year step on a 9,983-year relaxation time gave 7.93 m of relief
        # from a 5 m cosine (exact 0.41 m), with every conservation gate passing.
        with plan(width_m=4000.,reference_height_m=1000.,viscosity_pa_s=1e18,density_kg_m3=3300.,
                  gravity_m_s2=9.81,external_pressure_pa=0.,strike_width_m=1.,
                  scales=RegionalMechanicsScales(1000.,1e-10)) as p:
            x=np.linspace(0.,4000.,9)
            state=p.initial_state(1000.+5.*np.cos(np.pi*x/2000.),epoch_id='SI relaxation')
            with self.assertRaisesRegex(TectonicsError,'relaxation limit'):
                p.advance(state,24957.*31557600.,steps=1)

    def test_last_substep_ends_exactly_at_the_declared_end(self):
        t1=0.011583828702548055
        self.assertNotEqual(t1*3/3,t1)
        with plan() as p:
            state=p.initial_state(1.+1e-4*np.cos(np.pi*np.linspace(0.,2.,9)),epoch_id='clock')
            result=p.advance(state,t1-0.,steps=3,end_time_s=t1)
            self.assertEqual(result.state.descriptor()['time_s'],t1)
            self.assertEqual(result.descriptor()['intervals'][-1]['end_time_s'],t1)
            self.assertEqual(p.advance(state,t1,steps=3).state.descriptor()['time_s'],t1)
            later=p.initial_state(1.+1e-4*np.cos(np.pi*np.linspace(0.,2.,9)),epoch_id='clock',
                                  time_s=0.006394989738541456)
            end=0.02878803804725395
            self.assertNotEqual(0.006394989738541456+(end-0.006394989738541456),end)
            moved=p.advance(later,end-0.006394989738541456,steps=1,end_time_s=end)
            self.assertEqual(moved.state.descriptor()['time_s'],end)
            with self.assertRaisesRegex(TectonicsError,'declared interval end'):
                p.advance(later,.01,steps=1,end_time_s=end)

    def test_curved_one_advance_conserves_mass_volume_and_uniform_density(self):
        with plan(8,4,width_m=8.,reference_height_m=3.,viscosity_pa_s=25.,
                  density_kg_m3=2.,gravity_m_s2=3.,external_pressure_pa=7.,strike_width_m=5.,
                  scales=RegionalMechanicsScales(4.,.2),method='gmres') as p:
            x=np.linspace(0.,8.,17);top=3.+1e-4*np.cos(np.pi*x/8.)
            initial=p.initial_state(top,epoch_id='curved SI')
            first=p.mechanics(initial);before=initial.array('mesh_nodes_m').copy()
            started=perf_counter();result=p.advance(initial,.1,steps=1);elapsed=perf_counter()-started
            final=result.state;area,_=cell_volume_and_flux(final.array('mesh_nodes_m'))
            np.testing.assert_allclose(final.array('cell_mass_kg'),10.*area,rtol=1e-9,atol=0.)
            np.testing.assert_allclose(final.array('cell_mass_kg').sum(),initial.array('cell_mass_kg').sum(),rtol=1e-9)
            self.assertLess(abs(area.sum()-24.)/24.,1e-9)
            np.testing.assert_array_equal(initial.array('mesh_nodes_m'),before)
            self.assertLess(np.ptp(final.array('mesh_nodes_m')[-1,:,1]),np.ptp(top))
            self.assertGreater(np.max(np.abs(first.array('velocity_nodes_m_s'))),0.)
            self.assertEqual(final.descriptor()['accepted_steps'],1)
            self.assertEqual(final.descriptor()['parent_state_id'],initial.result_id)
            self.assertEqual(result.mechanics.descriptor()['state_id'],final.result_id)
            self.assertIn('physical minus mesh',result.descriptor()['transport'])
            for error in ('volume_residual_scaled','mass_residual_scaled','uniform_density_residual_scaled'):
                self.assertLessEqual(result.descriptor()['intervals'][0][error],1e-9)
            self.assertIs(p.mechanics(final),result.mechanics)
            MEASUREMENTS.append(dict(case='curved SI',seconds=elapsed,interval=result.descriptor()['intervals'][0],
                diagnostics=result.mechanics.descriptor()['diagnostics'],
                budget_peak=p.statistics()['budget']['peak_reserved_bytes']))

    def test_latest_cache_is_source_bound_and_immutable(self):
        with plan() as p:
            state=p.initial_state(np.ones(9),epoch_id='cache')
            first=p.mechanics(state);second=p.mechanics(state)
            self.assertIs(first,second)
            self.assertEqual(p.statistics()['mechanical_solves'],1)
            self.assertEqual(p.statistics()['latest_result_hits'],1)
            with self.assertRaises(ValueError):first.array('stress_q_pa').setflags(write=True)
            with self.assertRaises(TectonicsError):first.result_id='changed'
            descriptor=state.descriptor();descriptor['definition']['density_kg_m3']=9.
            self.assertEqual(state.descriptor()['definition']['density_kg_m3'],1.)
            for changes in ({'material_source':'different declared material'},{'method':'gmres'},
                            {'gravity_m_s2':2.},{'scales':RegionalMechanicsScales(2.,1.)}):
                with plan(**changes) as other:
                    with self.assertRaisesRegex(TectonicsError,'mismatch'):other.mechanics(state)
            # No filesystem edits: a changed live binding must also invalidate a cache hit.
            with mock.patch('atlas_tectonics.free_surface.cell_volume_and_flux',new=lambda *a,**k:None):
                with self.assertRaises(TectonicsError):p.mechanics(state)
            self.assertEqual(p.statistics()['latest_result_hits'],1)
            self.assertEqual(p.statistics()['mechanical_solves'],1)

    def test_state_metadata_fields_geometry_and_material_are_validated(self):
        with plan() as p:
            state=p.initial_state(np.ones(9),epoch_id='valid')
            cases=[{'epoch_id':''},{'time_s':'0'},{'time_s':True},
                {'accepted_steps':-1},{'accepted_steps':257},{'accepted_steps':True},
                {'accepted_steps':1},{'parent_state_id':'x'*64},
                {'context_id':'wrong'},{'source_status':'CANON'},
                {'definition':dict(state.descriptor()['definition'],density_kg_m3=2.)}]
            for change in cases:
                with self.subTest(change=change),self.assertRaises(TectonicsError):p.mechanics(altered(state,change))
            for mass in (np.ones((2,5)),np.zeros((2,4)),-np.ones((2,4)),
                         np.full((2,4),np.inf),2.*state.array('cell_mass_kg')):
                with self.subTest(mass=mass.shape),self.assertRaises(TectonicsError):
                    p.mechanics(altered(state,arrays={'cell_mass_kg':mass}))
            mesh=state.array('mesh_nodes_m').copy();mesh[...,0]+=.1
            with self.assertRaisesRegex(TectonicsError,'horizontal geometry'):
                p.mechanics(altered(state,arrays={'mesh_nodes_m':mesh}))
            self.assertEqual(p.statistics()['mechanical_solves'],0)

    def test_initial_geometry_exact_positivity_and_input_refusals(self):
        with self.assertRaisesRegex(TectonicsError,'bottom_m=0'):plan(bottom_m=1e-15)
        for changes in ({'frame_id':''},{'density_kg_m3':0.},{'method':'auto'},
                        {'external_pressure_pa':-1.},{'scales':None}):
            with self.subTest(changes=changes),self.assertRaises(TectonicsError):plan(**changes)
        with plan(2,2) as p:
            # All Q2 nodes are above zero, but the first quadratic dips below it.
            with self.assertRaisesRegex(TectonicsError,'Jacobian'):
                p.initial_state(np.array([1.,.01,.01,1.,1.]),epoch_id='folded')
            for top in (np.ones(4),np.ones((1,5)),np.array([1.,1.,np.nan,1.,1.])):
                with self.assertRaises(TectonicsError):p.initial_state(top,epoch_id='bad')
            self.assertEqual(p.statistics()['mechanical_solves'],0)
            good=p.initial_state(np.ones(5),epoch_id='good')
            for steps in (0,257,True,1.5):
                with self.assertRaises(TectonicsError):p.advance(good,1.,steps=steps)
            for duration in (0.,-1.,np.inf):
                with self.assertRaises(TectonicsError):p.advance(good,duration,steps=1)

    def test_cancellation_thread_and_closed_refusals_release_admission(self):
        parent=WorkBudget(128*1024**2)
        with plan(budget=parent) as p:
            state=p.initial_state(np.ones(9),epoch_id='cancel')
            cancelled=threading.Event();cancelled.set()
            with self.assertRaises(CancelledError):p.mechanics(state,cancel=cancelled)
            self.assertEqual(p.statistics()['mechanical_solves'],0)
            p.mechanics(state)
            with self.assertRaises(CancelledError):p.advance(state,.1,steps=1,cancel=cancelled)
            self.assertEqual(p.statistics()['accepted_steps'],0)
            with ThreadPoolExecutor(max_workers=1) as executor:
                with self.assertRaises(TectonicsError):executor.submit(p.mechanics,state).result()
            self.assertGreater(parent.reserved_bytes,0)
        self.assertEqual(parent.reserved_bytes,0)
        with self.assertRaises(TectonicsError):p.mechanics(state)
        with self.assertRaises(TectonicsError):p.__enter__()
        p.close()

    def test_shared_memory_covers_public_arrays_and_refuses_before_solve(self):
        small=WorkBudget(1024)
        with self.assertRaises(MemoryLimitError):plan(budget=small)
        self.assertEqual(small.reserved_bytes,0)
        parent=WorkBudget(128*1024**2)
        with plan(budget=parent) as p:
            state=p.initial_state(np.ones(9),epoch_id='budget')
            baseline=parent.reserved_bytes
            with parent.reserve(parent.available_bytes-1,category='explicit-caller-allowance'):
                with self.assertRaises(MemoryLimitError):p.mechanics(state)
                self.assertEqual(p.statistics()['mechanical_solves'],0)
            self.assertEqual(parent.reserved_bytes,baseline)
            mechanical=p.mechanics(state)
            allowance=p.statistics()['public_workspace_allowance_bytes']
            self.assertGreater(allowance,4*mechanical.nbytes+16*state.nbytes)
            self.assertLessEqual(parent.peak_reserved_bytes,128*1024**2)
        self.assertEqual(parent.reserved_bytes,0)
        MEASUREMENTS.append(dict(case='public admission',allowance=allowance,
            mechanical_bytes=mechanical.nbytes,state_bytes=state.nbytes))

    def test_cumulative_256_step_history_is_not_reset_by_continuation(self):
        with plan(2,2,gravity_m_s2=0.) as p:
            initial=p.initial_state(np.ones(5),epoch_id='ceiling')
            started=perf_counter();first=p.advance(initial,.254,steps=254)
            second=p.advance(first.state,.001,steps=1)
            third=p.advance(second.state,.001,steps=1)
            self.assertEqual(third.state.descriptor()['accepted_steps'],256)
            self.assertEqual(p.statistics()['accepted_steps'],256)
            self.assertEqual(third.state.descriptor()['parent_state_id'],second.state.result_id)
            np.testing.assert_array_equal(third.state.array('mesh_nodes_m'),initial.array('mesh_nodes_m'))
            with self.assertRaisesRegex(TectonicsError,'256'):p.advance(third.state,.001,steps=1)
            self.assertEqual(p.statistics()['accepted_steps'],256)
            MEASUREMENTS.append(dict(case='256 ceiling',seconds=perf_counter()-started,
                                     mechanical_solves=p.statistics()['mechanical_solves']))


if __name__=='__main__':unittest.main()
