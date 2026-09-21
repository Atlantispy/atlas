"""Focused strict SI-publication refinement controls; no campaign qualification.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
from pathlib import Path
import sys
import threading
import unittest

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import atlas_tectonics as at
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.variable_stokes_execution import (
    VariableStokesSolution, _PublicationRefinementRequired)
from stokes_fixtures import unit_box,unit_scales
from test_adaptive_inner_r4_4 import solve,arrays


class ConversionLoss(at.PreparedVariableStokes2D):
    """Inject a finite conversion defect after, never before, strict input checking.

    The exaggerated pressure perturbation makes the branch deterministic on a
    tiny grid. This control is not a reproduction of large-grid round-off.
    """
    repeat_loss=False
    cancel_after_loss=False

    def __init__(self,*args,**kwargs):
        self.linear_calls=0;self.publication_attempts=0;self.publication_checks=0
        self.refinement_inputs=[];self.pending=None;self.cancel_event=threading.Event()
        super().__init__(*args,**kwargs)

    def solve_rheology(self,*args,**kwargs):
        kwargs['cancel']=self.cancel_event
        return super().solve_rheology(*args,**kwargs)

    def _linear(self,rhs,guess,cancel):
        self.linear_calls+=1
        if self.pending is not None:
            self.refinement_inputs.append(np.array_equal(guess,self.pending))
            self.pending=None
        return super()._linear(rhs,guess,cancel)

    def _publish(self,vector,*args,**kwargs):
        self.publication_attempts+=1;self.publication_checks=0
        try:return super()._publish(vector,*args,**kwargs)
        except _PublicationRefinementRequired:
            self.pending=vector.copy()
            if self.cancel_after_loss:self.cancel_event.set()
            raise

    def _certify_adaptive_publication(self,vector,rhs,cancel):
        self.publication_checks+=1
        if self.publication_checks==2 and (self.repeat_loss or self.publication_attempts==1):
            vector[self._op.nv]+=1e-8
        return super()._certify_adaptive_publication(vector,rhs,cancel)


def mechanical(*,anderson=False,maximum=400,budget=None):
    return ConversionLoss(unit_box(4),unit_scales(),
        policy=at.NonlinearStokesPolicy(max_picard_iterations=maximum,ilu_fill_factor=17),
        adaptive_inner_policy=at.AdaptiveInnerPolicy(),
        anderson_policy=at.AndersonPolicy() if anderson else None,
        preconditioner_reuse_policy=at.PreconditionerReusePolicy(),budget=budget)


class PublicationRefinementTests(unittest.TestCase):
    def test_picard_and_anderson_refine_actual_return_with_complete_history(self):
        for accelerated in (False,True):
            with self.subTest(anderson=accelerated),mechanical(anderson=accelerated) as q:
                result=solve(q);metadata=result.descriptor()
                history=metadata['nonlinear_history']
                attempts=[row['publication'] for row in history if 'publication' in row]
                self.assertEqual([row['status'] for row in attempts],['refine','accepted'])
                self.assertEqual(q.refinement_inputs,[True])
                self.assertEqual(q.linear_calls,len(history))
                self.assertEqual(len(metadata['adaptive_inner_history']),len(history))
                self.assertEqual(len(metadata['preconditioner_history']),len(history))
                self.assertLessEqual(attempts[0]['internal_residual_l2'],attempts[0]['target_l2'])
                self.assertGreater(attempts[0]['returned_residual_l2'],attempts[0]['target_l2'])
                self.assertLessEqual(attempts[-1]['returned_residual_l2'],attempts[-1]['target_l2'])
                self.assertEqual(VariableStokesSolution(metadata,arrays(result)).result_id,result.result_id)
                self.assertIsNone(q._adaptive_request)
                if accelerated:
                    self.assertEqual(history[-1]['anderson']['action'],'not_proposed')
                for mutation in ('invalid_input','false_refinement','false_acceptance'):
                    bad=result.descriptor()
                    rows=[row['publication'] for row in bad['nonlinear_history'] if 'publication' in row]
                    if mutation=='invalid_input':rows[0]['internal_residual_l2']=2*rows[0]['target_l2']
                    elif mutation=='false_refinement':rows[0]['returned_residual_l2']=0.
                    else:rows[-1]['status']='refine'
                    with self.subTest(mutation=mutation),self.assertRaises(at.TectonicsError):
                        VariableStokesSolution(bad,arrays(result))

    def test_refinement_cannot_extend_nonlinear_envelope(self):
        budget=WorkBudget(1<<28)
        with mechanical(maximum=2,budget=budget) as q:
            q.repeat_loss=True
            with self.assertRaisesRegex(at.TectonicsError,'fixed Picard envelope'):
                solve(q,zero=True)
            self.assertEqual(q.publication_attempts,2)
            self.assertEqual(q.linear_calls,2)
            self.assertIsNone(q._adaptive_request)
        self.assertEqual(budget.reserved_bytes,0)

    def test_cancellation_after_conversion_failure_releases_request(self):
        budget=WorkBudget(1<<28)
        with mechanical(budget=budget) as q:
            q.cancel_after_loss=True
            with self.assertRaises(CancelledError):solve(q,zero=True)
            self.assertEqual(q.publication_attempts,1)
            self.assertEqual(q.linear_calls,1)
            self.assertIsNone(q._adaptive_request)
        self.assertEqual(budget.reserved_bytes,0)


if __name__=='__main__':unittest.main(verbosity=2)
