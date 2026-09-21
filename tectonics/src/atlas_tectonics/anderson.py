"""R4.4 bounded Anderson acceleration; independent Picard checks stay authoritative.

SPDX-License-Identifier: AGPL-3.0-only
Type-II velocity-error least squares with whole-vector affine correction. The
caller evaluates every proposal using the actual current rheology and admits
history before allocation. This module adds no alternate physical model.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import numpy as np
from numpy.linalg import lstsq as _least_squares
from ._validation import TectonicsError, scalar
from .constitutive import _json

_METHOD = 'atlas.anderson-type2-velocity.v1'
_FINAL = 'fresh-picard-image-returned-si'

@dataclass(frozen=True, slots=True)
class AndersonPolicy:
    """Explicit bounded type-II velocity-error mixing, with physical safeguarding.

    None on a prepared plan selects unchanged Picard. History is private to one
    nonlinear request; no cross-step/result cache is implicit. These are numerical
    policy controls, not weaker physical convergence requirements.
    """
    depth: int = 5
    rcond: float = 1e-10
    coefficient_l1_limit: float = 10.0
    warmup_maps: int = 2

    def __post_init__(self):
        if type(self.depth) is not int or not 1 <= self.depth <= 10:
            raise TectonicsError('Anderson history depth must be an integer in [1, 10]')
        if type(self.warmup_maps) is not int or not 2 <= self.warmup_maps <= self.depth+1:
            raise TectonicsError('Anderson warmup must lie in [2, depth+1]')
        for key,lo,hi in (('rcond',np.finfo(float).eps,1.),('coefficient_l1_limit',1.,1000.)):
            value=scalar(getattr(self,key),key,positive=True)
            if not lo <= value <= hi or (key=='rcond' and value==1.):
                raise TectonicsError('Anderson '+key+' is outside supported bounds')
            object.__setattr__(self,key,value)


def history_bytes(unknowns: int, policy: AndersonPolicy) -> int:
    """Conservative history/SVD/diagnostic scratch admission, not an RSS cap."""
    return 8*unknowns*(8*(policy.depth+1)+32)+262144


def check_policy(policy, nonlinear_policy):
    if type(policy) is not AndersonPolicy:
        raise TectonicsError('typed Anderson policy required')
    if nonlinear_policy.relaxation != 1.0:
        raise TectonicsError('Anderson requires full Picard relaxation; no ignored policy')


def _merit(d: dict, policy) -> float:
    """Use actual updated-law diagnostics, not the least-squares prediction."""
    value = max(
        d['momentum_linf'] / policy.momentum_tolerance,
        d['divergence_linf'] / policy.divergence_tolerance,
        d['pressure_gauge_relative'] / policy.gauge_tolerance,
        d['gauge_multiplier_abs'] / policy.divergence_tolerance,
        d['work_balance_relative'] / policy.work_balance_tolerance,
    )
    if not math.isfinite(value):raise TectonicsError('normalised Anderson merit is outside finite range')
    return value


def _propose(images: list[np.ndarray], errors: list[np.ndarray],
            velocity_count: int, policy: AndersonPolicy) -> tuple[np.ndarray | None, dict]:
    """Type-II affine Anderson proposal using velocity fixed-point differences.

    Viscosity depends on velocity, not dynamic pressure. Fit velocity residuals;
    apply the same affine coefficients to the entire velocity/pressure/gauge
    vector. SVD-based least squares avoids squaring the condition number.
    """
    if len(images) != len(errors) or len(images) < 2:
        return None, {'reason': 'insufficient_history'}
    width = min(policy.depth, len(images) - 1)
    drops = 0
    while width > 0:
        fs = errors[-width-1:]
        ys = images[-width-1:]
        df = np.column_stack([fs[i+1][:velocity_count] - fs[i][:velocity_count]
                              for i in range(width)])
        scale = max(float(np.max(np.abs(df))), float(np.max(np.abs(fs[-1][:velocity_count]))))
        if not math.isfinite(scale) or scale == 0:
            return None, {'reason': 'zero_or_nonfinite_history', 'rank_drops': drops}
        try:
            gamma, _, rank, singular = _least_squares(
                df/scale, fs[-1][:velocity_count]/scale, rcond=policy.rcond)
        except np.linalg.LinAlgError:
            return None, {'reason': 'least_squares_failure', 'rank_drops': drops}
        if rank != width:
            width -= 1
            drops += 1
            continue
        # y_k - sum gamma_i (y_{i+1}-y_i) = sum alpha_i y_i.
        alpha = np.concatenate(([gamma[0]], np.diff(gamma), [1.0-gamma[-1]]))
        l1 = float(np.sum(np.abs(alpha)))
        details = {'depth_used': width, 'rank_drops': drops, 'coefficient_l1': l1,
                   'coefficient_sum': float(np.sum(alpha)),
                   'singular_ratio': float(singular[-1]/singular[0])}
        if not np.isfinite(gamma).all() or not math.isfinite(l1) or l1 > policy.coefficient_l1_limit:
            return None, dict(details, reason='coefficient_bound')
        candidate = ys[-1].copy()
        for i in range(width):
            candidate -= gamma[i] * (ys[i+1] - ys[i])
        if not np.isfinite(candidate).all():
            return None, dict(details, reason='nonfinite_proposal')
        return candidate, dict(details, reason='proposal')
    return None, {'reason': 'rank_deficient', 'rank_drops': drops}



def summary(policy, iterations, accepted, rejected):
    return dict(method=_METHOD,policy=asdict(policy),nonlinear_iterations=iterations,
                accepted_mixed_updates=accepted,rejected_proposals=rejected,final_acceptance=_FINAL)


def check_summary(record, iterations, expected_policy=None):
    """Validate persisted algorithm controls/counts without claiming authenticity."""
    keys={'method','policy','nonlinear_iterations','accepted_mixed_updates','rejected_proposals','final_acceptance'}
    try:
        if type(record) is not dict or set(record)!=keys or record['method']!=_METHOD or record['final_acceptance']!=_FINAL:
            raise TectonicsError('noncanonical Anderson provenance')
        policy=AndersonPolicy(**record['policy'])
        if _json(asdict(policy))!=_json(record['policy']):
            raise TectonicsError('noncanonical Anderson policy')
        if expected_policy is not None and _json(record['policy'])!=_json(asdict(expected_policy)):
            raise TectonicsError('Anderson policy differs from declared solve')
        for key in ('nonlinear_iterations','accepted_mixed_updates','rejected_proposals'):
            if type(record[key]) is not int or record[key]<0:
                raise TectonicsError('invalid Anderson count')
        if (record['nonlinear_iterations']!=iterations or iterations<1 or
                record['accepted_mixed_updates']+record['rejected_proposals']>iterations-1):
            raise TectonicsError('inconsistent Anderson counts')
        return policy
    except (KeyError,TypeError,ValueError) as exc:
        raise TectonicsError('invalid Anderson record') from exc


def check_history(history, record):
    policy=check_summary(record,len(history))
    accepted=rejected=0
    for i,item in enumerate(history):
        row=item.get('anderson')
        keys={'action','picard_merit','trial_merit','depth_used'}
        if type(row) is not dict or set(row)!=keys:
            raise TectonicsError('complete Anderson per-iteration record required')
        action=row['action']
        if action not in ('not_proposed','accepted','rejected_history','rejected_true_residual','rejected_invalid_trial'):
            raise TectonicsError('unsupported Anderson action')
        scalar(row['picard_merit'],'Picard merit',nonnegative=True)
        if type(row['depth_used']) is not int or not 0<=row['depth_used']<=policy.depth:
            raise TectonicsError('invalid Anderson depth')
        if row['trial_merit'] is not None:
            scalar(row['trial_merit'],'trial merit',nonnegative=True)
        if action=='accepted':
            if row['trial_merit'] is None or row['trial_merit']>row['picard_merit'] or row['depth_used']==0:
                raise TectonicsError('unacceptable accelerated update in history')
            accepted+=1
        elif action.startswith('rejected'):
            rejected+=1
        elif row['trial_merit'] is not None or row['depth_used']:
            raise TectonicsError('unexpected proposal fields')
        if i==len(history)-1 and action!='not_proposed':
            raise TectonicsError('Anderson final result must be a fresh Picard image')
    if accepted!=record['accepted_mixed_updates'] or rejected!=record['rejected_proposals']:
        raise TectonicsError('Anderson history/count mismatch')
