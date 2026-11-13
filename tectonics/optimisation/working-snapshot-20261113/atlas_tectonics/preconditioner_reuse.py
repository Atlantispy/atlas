"""Guarded, request-local velocity-preconditioner reuse; current physical operator.

SPDX-License-Identifier: AGPL-3.0-only
This is a numerical helper policy, never permission to solve stale equations.
No approximate reuse or decision history survives a nonlinear request. Cache-hit
telemetry is deliberately excluded from deterministic scientific provenance.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import math
import numpy as np
from ._validation import TectonicsError, scalar
from .constitutive import _json

_METHOD = 'atlas.velocity-preconditioner-request-reuse.v2'
_REASONS = ('request_start', 'exact_match', 'age_limit', 'viscosity_change',
            'linear_work_growth', 'bounded_reuse', 'zero_rhs')


@dataclass(frozen=True, slots=True)
class PreconditionerReusePolicy:
    """Four-use assessed default; None on a plan preserves rebuild-on-change.

    A helper remains fixed inside each GMRES call. The pressure approximation
    and physical stress operator always use current coefficients. Only the
    supported Tosi plastic law activates changed-coefficient reuse; strain-
    independent laws bypass the extra work. Direct/prescribed/BF use is refused.
    """
    max_uses: int = 4
    maximum_log_change: float = math.log(2.0)
    iteration_growth: float = 1.5
    iteration_floor: int = 40

    def __post_init__(self):
        if type(self.max_uses) is not int or not 1 <= self.max_uses <= 8:
            raise TectonicsError('preconditioner max_uses must be an integer in [1,8]')
        if type(self.iteration_floor) is not int or not 1 <= self.iteration_floor <= 1000000:
            raise TectonicsError('preconditioner iteration_floor must be in [1,1000000]')
        for key, lo, hi in (('maximum_log_change', 0., math.log(10.)),
                            ('iteration_growth', 1., 1000.)):
            v = scalar(getattr(self, key), key, positive=True)
            if not lo <= v <= hi:
                raise TectonicsError('unsupported preconditioner '+key)
            object.__setattr__(self, key, v)


def check_policy(policy, nonlinear_policy):
    if type(policy) is not PreconditionerReusePolicy:
        raise TectonicsError('typed preconditioner-reuse policy required')
    if nonlinear_policy is None or nonlinear_policy.method != 'gmres':
        raise TectonicsError('preconditioner reuse requires GMRES variable mechanics')


def coefficient_key(op):
    return hashlib.sha256(op.eta_c.tobytes()+op.eta_v.tobytes()).hexdigest()


def request_bytes(cells, maximum_iterations):
    """Coefficient copies, logarithm scratch and bounded records; not an RSS cap."""
    return 64*cells+262144+2048*maximum_iterations


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _hex(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise TectonicsError('invalid coefficient/history hash')


class _Request:
    """Private state allocated only under a request's WorkBudget reservation."""
    def __init__(self, policy):
        self.policy = policy
        self.c = self.v = None
        self.uses = 0
        self.build_iterations = self.last_iterations = None
        self.pending = None
        self.rows = []

    def decision(self, op, factor_key):
        current = coefficient_key(op)
        change = None
        if self.c is None:
            reason = 'request_start'
        elif factor_key == current:
            reason = 'exact_match'
        elif self.uses >= self.policy.max_uses:
            reason = 'age_limit'
        else:
            change = max(float(np.max(np.abs(np.log(op.eta_c)-np.log(self.c)))),
                         float(np.max(np.abs(np.log(op.eta_v)-np.log(self.v)))))
            if change > self.policy.maximum_log_change:
                reason = 'viscosity_change'
            elif (self.last_iterations is not None and self.build_iterations is not None and
                  self.last_iterations > max(self.policy.iteration_floor,
                      self.policy.iteration_growth*self.build_iterations)):
                reason = 'linear_work_growth'
            else:
                reason = 'bounded_reuse'
        return reason, current, change

    def selected(self, op, factor_key, decision):
        reason, current, change = decision
        if reason != 'bounded_reuse' and factor_key != current:
            raise TectonicsError('current-coefficient factor required at rebuild boundary')
        if reason not in ('bounded_reuse', 'exact_match'):
            # This reset is logical, not contingent on an actual cache miss.
            # Identical requests therefore have identical decision provenance.
            self.c = op.eta_c.copy(); self.v = op.eta_v.copy()
            self.uses = 0; self.build_iterations = None
        self.uses += 1
        self.pending = dict(decision=reason, uses=self.uses,
            current_coefficient_sha256=current, factor_coefficient_sha256=factor_key,
            max_log_change_from_factor=change)

    def complete(self, op, iterations):
        if self.pending is None:
            self.rows.append(dict(decision='zero_rhs', iterations=iterations, uses=0,
                current_coefficient_sha256=None, factor_coefficient_sha256=None,
                max_log_change_from_factor=None))
            return
        if coefficient_key(op) != self.pending['current_coefficient_sha256']:
            raise TectonicsError('physical operator changed during linear solve')
        if self.build_iterations is None:
            self.build_iterations = iterations
        self.last_iterations = iterations
        self.rows.append(dict(self.pending, iterations=iterations))
        self.pending = None


def summary(policy, active, iterations, rows):
    return dict(method=_METHOD, policy=asdict(policy), active=active,
                nonlinear_iterations=iterations, linear_calls=len(rows),
                decisions={reason:sum(r['decision']==reason for r in rows) for reason in _REASONS},
                history_sha256=_hash(rows))


def check_summary(record, iterations, expected_policy=None):
    try:
        keys={'method','policy','active','nonlinear_iterations','linear_calls','decisions','history_sha256'}
        if type(record) is not dict or set(record)!=keys or record['method']!=_METHOD:
            raise TectonicsError('noncanonical preconditioner-reuse summary')
        p=PreconditionerReusePolicy(**record['policy'])
        if _json(asdict(p))!=_json(record['policy']):
            raise TectonicsError('noncanonical preconditioner-reuse policy')
        if expected_policy is not None and _json(asdict(expected_policy))!=_json(record['policy']):
            raise TectonicsError('preconditioner-reuse policy mismatch')
        if type(record['active']) is not bool or type(iterations) is not int or iterations<1:
            raise TectonicsError('invalid reuse activation/iteration count')
        if type(record['nonlinear_iterations']) is not int or record['nonlinear_iterations']!=iterations:
            raise TectonicsError('invalid reuse nonlinear count')
        n=record['linear_calls'];d=record['decisions']
        if type(n) is not int or n!=(iterations if record['active'] else 0):
            raise TectonicsError('reuse linear-call count differs')
        if type(d) is not dict or set(d)!=set(_REASONS) or any(type(x) is not int or x<0 for x in d.values()):
            raise TectonicsError('invalid reuse decisions')
        if sum(d.values())!=n or d['request_start']>1:
            raise TectonicsError('inconsistent reuse decision counts')
        _hex(record['history_sha256'])
        return p
    except (KeyError, TypeError, ValueError) as exc:
        raise TectonicsError('invalid preconditioner-reuse record') from exc


def check_history(record, rows, history, nonlinear_policy):
    p=check_summary(record,len(history));check_policy(p,nonlinear_policy)
    if type(rows) is not list or len(rows)!=record['linear_calls'] or _hash(rows)!=record['history_sha256']:
        raise TectonicsError('inconsistent preconditioner decision history')
    origin=None;uses=0;build_it=last_it=None
    keys={'decision','iterations','uses','current_coefficient_sha256',
          'factor_coefficient_sha256','max_log_change_from_factor'}
    for i,r in enumerate(rows):
        if type(r) is not dict or set(r)!=keys or r['decision'] not in _REASONS:
            raise TectonicsError('invalid preconditioner history entry')
        reason=r['decision'];count=r['iterations'];change=r['max_log_change_from_factor']
        if type(count) is not int or count!=history[i]['linear_iterations']:
            raise TectonicsError('preconditioner history linear count differs')
        if type(r['uses']) is not int or r['uses']<0:
            raise TectonicsError('invalid factor use count')
        if reason=='zero_rhs':
            if count or r['uses'] or r['current_coefficient_sha256'] is not None or r['factor_coefficient_sha256'] is not None or change is not None:
                raise TectonicsError('invalid zero-force reuse record')
            continue
        current=r['current_coefficient_sha256'];factor=r['factor_coefficient_sha256']
        _hex(current);_hex(factor)
        if change is not None:scalar(change,'factor-origin viscosity change',nonnegative=True)
        if reason=='request_start':
            if origin is not None or uses!=0:raise TectonicsError('repeated reuse request start')
        elif origin is None:raise TectonicsError('missing first current-coefficient factor')
        if reason=='bounded_reuse':
            if (factor!=origin or factor==current or uses>=p.max_uses or change is None or
                    change>p.maximum_log_change or (last_it is not None and
                    last_it>max(p.iteration_floor,p.iteration_growth*build_it))):
                raise TectonicsError('reuse guard violated in record')
        elif reason=='exact_match':
            if factor!=origin or factor!=current:raise TectonicsError('invalid exact factor record')
        else:
            if factor!=current:raise TectonicsError('stale factor at rebuild boundary')
            if reason=='age_limit' and uses<p.max_uses:raise TectonicsError('invalid age rebuild')
            if reason=='viscosity_change' and (change is None or change<=p.maximum_log_change):
                raise TectonicsError('invalid viscosity rebuild')
            if reason=='linear_work_growth' and (last_it is None or
                    last_it<=max(p.iteration_floor,p.iteration_growth*build_it)):
                raise TectonicsError('invalid linear growth rebuild')
            origin=factor;uses=0;build_it=None
        uses+=1
        if r['uses']!=uses:raise TectonicsError('factor age mismatch')
        if build_it is None:build_it=count
        last_it=count
    expected=summary(p,record['active'],len(history),rows)
    if _json(expected)!=_json(record):raise TectonicsError('reuse summary differs from history')
