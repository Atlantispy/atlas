"""Pressure-dominated mechanics must supply usable incompressible transport.
SPDX-License-Identifier: AGPL-3.0-only
"""
import math
import time
import unittest

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (BoussinesqMaterial, DiffusiveScales, PreparedStokes2D,
    PreparedThermochemical2D, StokesBox2D, ThermochemicalProblem, ThermochemicalState,
    ThermalBoundary2D, ThermochemicalPolicy, TectonicsError, reference_rheology)
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.stokes import _MACOperator, _SeparableVelocityInverse
from atlas_tectonics.thermochemical_execution import _courant_arrays
from stokes_fixtures import analytic, request, unit_box, unit_scales


def cooling(nz, steps):
    """Independent finite-time continuum cell-average oracle, not solver output."""
    budget=WorkBudget(512<<20)
    box=StokesBox2D(2*nz,nz,20000.,10000.,'synthetic-cooling-slab')
    material=BoussinesqMaterial('synthetic-slab','Independent analytic conduction control',
        3300.,1000.,3.3,3e-5,300.,0.,0.,(200.,1500.))
    problem=ThermochemicalProblem(box,material,ThermalBoundary2D('fixed-top-bottom',1300.,300.),
        reference_rheology('constant'),DiffusiveScales('synthetic-slab',10000.,1e-6,1e21,300.,1000.,10000.),
        (0.,-9.81),'synthetic-start','absent-constituent','Hydrostatic slab control')
    z=(np.arange(nz)+.5)/nz
    steady=1300.-1000.*z
    mode=80.*np.sinc(1/(2*nz))*np.sin(np.pi*z)
    temperature=np.broadcast_to((steady+mode)[:,None],(nz,2*nz))
    state=ThermochemicalState(problem,temperature,np.zeros_like(temperature),time_s=0.,
        source='exact initial cell averages',budget=budget)
    initial_id=state.state_id; initial=state
    duration=5e12; start=time.perf_counter()
    with PreparedThermochemical2D(problem,budget=budget) as plan:
        for _ in range(steps):
            state=plan.advance(state,duration/steps,source='analytic cooling interval').state
    expected=np.broadcast_to((steady+mode*np.exp(-1e-6*np.pi**2*duration/10000.**2))[:,None],temperature.shape)
    error=state.array('temperature_k')-expected
    return dict(nz=nz,steps=steps,elapsed_s=time.perf_counter()-start,
        rms_error_k=float(np.sqrt(np.mean(error**2))),max_error_k=float(np.max(np.abs(error))),
        temperature=state.array('temperature_k'),initial_unchanged=initial.state_id==initial_id,
        reserved_bytes=budget.reserved_bytes,final_time_s=state.time_s,
        composition_max=float(np.max(np.abs(state.array('composition')))))


class HydrostaticTransportTests(unittest.TestCase):
    cooling_metrics=None

    def test_projection_preserves_momentum_and_pressure_gauge(self):
        box=unit_box(9,5,width=3.,height=2.)
        op=_MACOperator(box,3/9,2/5); inv=_SeparableVelocityInverse(op)
        vector=np.random.default_rng(47).normal(size=op.n)
        before=op.matvec(vector)[:op.nv].copy(); pressure_mean=op.split(vector)[2].mean()
        inv.project_velocity(vector)
        u,w,p,_=op.split(vector)
        assert_allclose(op.matvec(vector)[:op.nv],before,rtol=2e-13,atol=2e-13)
        assert_allclose(op.divergence(u,w),0.,atol=4e-15)
        self.assertAlmostEqual(p.mean(),pressure_mean,places=14)

    def test_axis_only_gradient_velocity_removed_without_amplitude_threshold(self):
        box=unit_box(8,4); op=_MACOperator(box,1/8,1/4); inv=_SeparableVelocityInverse(op)
        for amplitude in (1.,1e-90,1e90):
            vector=np.zeros(op.n);u,w,_,_=op.split(vector)
            u[:]=amplitude*np.arange(1,8)[None,:]
            w[:]=amplitude*np.arange(1,4)[:,None]
            inv.project_velocity(vector)
            assert_array_equal(u,0.);assert_array_equal(w,0.)

    def test_nonseparable_gradient_and_tiny_circulation_pass_transport_gate(self):
        box=unit_box(10,7,width=2.,height=1.)
        x,z=np.meshgrid(*box.axes()); pressure=np.sin(1.3*x+.7*z)+z
        gradient=(np.diff(pressure,axis=1)/(2/10),np.diff(pressure,axis=0)/(1/7))
        flow=analytic(box)
        velocities=[]
        for amplitude in (1.,1e-80):
            with PreparedStokes2D(box,reference_rheology('constant'),unit_scales()) as plan:
                for relative in (0.,1e-5):
                    forces=tuple(amplitude*(g+relative*f) for g,f in zip(gradient,flow[:2]))
                    result=plan.solve(*forces,**request(box))
                    u=result.array('u_m_s');w=result.array('w_m_s')
                    _courant_arrays(box,u,w,.001,ThermochemicalPolicy())
                    if relative:
                        self.assertGreater(max(np.max(np.abs(u)),np.max(np.abs(w))),0.)
                        velocities.append((u/amplitude,w/amplitude))
        for first,second in zip(*velocities):
            assert_allclose(first,second,rtol=2e-9,atol=1e-15)

    def test_transport_still_rejects_compressible_tiny_velocity(self):
        box=unit_box(6,4);u=np.zeros((4,7));w=np.zeros((5,6));u[:,2]=1e-80
        with self.assertRaisesRegex(TectonicsError,'not discretely incompressible'):
            _courant_arrays(box,u,w,1.,ThermochemicalPolicy())

    def test_finite_time_cooling_converges_and_step_subdivision_agrees(self):
        results=[cooling(n,4) for n in (8,16,32)]
        control=cooling(32,8)
        for result in results+[control]:
            self.assertTrue(result['initial_unchanged']);self.assertEqual(result['reserved_bytes'],0)
            self.assertEqual(result['final_time_s'],5e12);self.assertEqual(result['composition_max'],0.)
        for coarse,fine in zip(results,results[1:]):
            self.assertGreater(coarse['rms_error_k']/fine['rms_error_k'],3.8)
        self.assertLess(results[-1]['max_error_k'],.025)
        difference=float(np.max(np.abs(results[-1]['temperature']-control['temperature'])))
        self.assertLess(difference,2e-10)
        type(self).cooling_metrics=dict(
            grids=[{k:v for k,v in r.items() if k!='temperature'} for r in results],
            timestep_control={k:v for k,v in control.items() if k!='temperature'},
            subdivision_max_difference_k=difference,
            observed_orders=[math.log(a['rms_error_k']/b['rms_error_k'],2) for a,b in zip(results,results[1:])])


if __name__=='__main__':
    unittest.main()
