"""Independent continuous control-volume ODE, not the split production solver.

The saturated single-pool oracle has explicit phase supply, mixed overflow and
bed deposition together. This tests numerical consistency, not real hydraulics.
"""
from copy import deepcopy
from decimal import Decimal, localcontext
import math
import unittest

import capture
from capture_fixtures import suite


def continuous_reference(steps):
    with localcontext() as context:
        context.prec=60
        D=Decimal;dt=D(1)/steps
        y=(D('49.95'),D('.05'),D(0))
        def rhs(state):
            w,s,b=state;v=w+s
            return (D('.999')-w/v,D('.001')-s/v-D(10)*s/v,D(10)*s/v)
        def shifted(state,k,factor):return tuple(v+dt*factor*q for v,q in zip(state,k))
        for _ in range(steps):
            a=rhs(y);b=rhs(shifted(y,a,D('.5')));c=rhs(shifted(y,b,D('.5')));d=rhs(shifted(y,c,D(1)))
            y=tuple(v+dt*(aa+2*bb+2*cc+dd)/6 for v,aa,bb,cc,dd in zip(y,a,b,c,d))
        return tuple(float(v) for v in y)


def coupled_recipe(steps):
    recipe=deepcopy(suite()[1]);recipe['scenario_id']='continuous_overflow_and_settling_oracle'
    recipe['state']['liquid_m3']=[0.,49.95,0.]
    recipe['state']['suspended_solid_m3']=[0.,.05,0.]
    recipe['forcing'].update(steps=steps,dt_years=1./steps,settling_m_year=1.,
        liquid_input_m3_year=[0.,.999,0.],suspended_input_m3_year=[0.,.001,0.])
    return recipe


def measure():
    reference=continuous_reference(1024);coarser=continuous_reference(512)
    if max(abs(a-b) for a,b in zip(reference,coarser))>1e-12:
        raise AssertionError('independent coupled ODE refinement does not meet 1e-12 m3 accuracy check')
    rows=[]
    for steps in (10,20,40):
        recipe=coupled_recipe(steps)
        state,diagnostics=capture.advance(capture.CaptureState(**recipe['state']),**recipe['forcing'])
        actual=(sum(state.liquid_m3),sum(state.suspended_solid_m3),sum(state.bed_solid_m3))
        errors=[abs(a-b) for a,b in zip(actual,reference)]
        rows.append({'steps':steps,'actual_liquid_suspended_bed_m3':actual,'absolute_errors_m3':errors,
                     'max_error_m3':max(errors),'liquid_ledger':diagnostics['liquid_ledger'],
                     'solid_ledger':diagnostics['solid_ledger']})
    orders=[math.log2(a['max_error_m3']/b['max_error_m3']) for a,b in zip(rows,rows[1:])]
    return {'reference_liquid_suspended_bed_m3':reference,'reference_512_vs_1024_max_difference_m3':max(abs(a-b) for a,b in zip(reference,coarser)),
            'measurements':rows,'observed_global_orders':orders,'minimum_declared_order':capture.CONTRACT['minimum_smooth_convergence_order']}


class CoupledEquationTests(unittest.TestCase):
    def test_continuous_overflow_settling_bed_reference(self):
        report=measure()
        for order in report['observed_global_orders']:
            self.assertGreaterEqual(order,report['minimum_declared_order'])
        for row in report['measurements']:
            for key in ('liquid_ledger','solid_ledger'):
                self.assertLessEqual(abs(row[key]['residual']),row[key]['tolerance'])
        # No incoming bed source: bed gain is suspension transferred, not added mass.
        w,s,b=report['reference_liquid_suspended_bed_m3']
        self.assertAlmostEqual(w+s+b,50.,places=11)
        self.assertGreater(b,0.)
        self.assertLess(s,.05)


if __name__=='__main__':unittest.main()
