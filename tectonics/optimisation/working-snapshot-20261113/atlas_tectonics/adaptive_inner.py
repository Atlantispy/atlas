"""WORKING NON-CANON: bounded provisional accuracy; strict publication only.

SPDX-License-Identifier: AGPL-3.0-only
ATLAS-R44-ADAPTIVE-INNER-20260921. This is the assessed defect-based
schedule, not an Eisenstat-Walker or Newton implementation. Request-local
records are bounded by the existing nonlinear iteration envelope.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib

from ._validation import TectonicsError, scalar
from .constitutive import _json

_METHOD = 'atlas.adaptive-inner.defect-correction.v1'


@dataclass(frozen=True, slots=True)
class AdaptiveInnerPolicy:
    """Explicit intermediate targets; final targets come from NonlinearStokesPolicy.

    These bounds only allow schedules no looser than the assessed candidate.
    Once strict certification begins, the rest of that request remains strict.
    No policy means the original full-solution GMRES path, not strict correction.
    """
    defect_fraction: float = 0.1
    rhs_relative_cap: float = 1e-4
    strict_defect_relative: float = 1e-6

    def __post_init__(self):
        for key, maximum in (('defect_fraction', 0.1),
                             ('rhs_relative_cap', 1e-4),
                             ('strict_defect_relative', 1.0)):
            value = scalar(getattr(self, key), key, positive=True)
            if value > maximum or (key == 'strict_defect_relative' and value < 1e-6):
                raise TectonicsError('adaptive inner '+key+' exceeds assessed bounds')
            object.__setattr__(self, key, value)


def check_policy(policy, nonlinear_policy):
    if type(policy) is not AdaptiveInnerPolicy:
        raise TectonicsError('typed adaptive-inner policy required')
    if (nonlinear_policy is None or nonlinear_policy.method != 'gmres' or
            nonlinear_policy.relaxation != 1.0):
        raise TectonicsError('adaptive inner requires GMRES and unit relaxation')


def target(policy, linear_rtol, rhs_norm, defect_norm, force_strict):
    """Absolute target relative to the ORIGINAL RHS, never a relaxed final gate."""
    strict = linear_rtol * rhs_norm
    certify = bool(force_strict or defect_norm <= policy.strict_defect_relative*rhs_norm)
    value = strict if certify else max(strict, min(
        policy.defect_fraction*defect_norm, policy.rhs_relative_cap*rhs_norm))
    return float(value), bool(certify or value == strict)


def request_bytes(unknowns, maximum_iterations):
    # Defect, delta, result, current/last-strict coefficients and residual scratch.
    # GMRES basis is already in the existing mechanical scratch reservation.
    return 128*unknowns + 2048*maximum_iterations + 262144


class _Request:
    def __init__(self, policy):
        self.policy = policy
        self.strict_phase = False
        self.has_strict = False
        self.rows = []
        self.cert_c = self.cert_v = None
        self.returned_residual = None
        self.coefficient_hash = None


def summary(policy, request, iterations, nonlinear_policy):
    rows = [] if request is None else request.rows
    final = None
    if request is not None:
        if not rows or not rows[-1]['strict_certified'] or request.returned_residual is None:
            raise TectonicsError('adaptive result lacks fresh strict final certification')
        last = rows[-1]
        final = dict(linear_rtol=nonlinear_policy.linear_rtol,
                     rhs_l2=last['rhs_l2'], target_l2=last['target_l2'],
                     internal_residual_l2=last['residual_l2'],
                     returned_residual_l2=request.returned_residual,
                     coefficient_sha256=request.coefficient_hash,
                     system='last-frozen-viscosity-linear-system')
    return dict(method=_METHOD, policy=asdict(policy), active=request is not None,
                nonlinear_iterations=iterations, linear_calls=len(rows),
                strict_calls=sum(r['strict_certified'] for r in rows),
                history_sha256=hashlib.sha256(_json(rows)).hexdigest(),
                final_certification=final)


def check_summary(record, iterations, nonlinear_policy, expected_policy=None):
    """Validate compact stage evidence without pretending hashes prove physics."""
    try:
        keys = {'method', 'policy', 'active', 'nonlinear_iterations', 'linear_calls',
                'strict_calls', 'history_sha256', 'final_certification'}
        if type(record) is not dict or set(record) != keys or record['method'] != _METHOD:
            raise TectonicsError('noncanonical adaptive-inner summary')
        policy = AdaptiveInnerPolicy(**record['policy'])
        check_policy(policy, nonlinear_policy)
        if _json(asdict(policy)) != _json(record['policy']):
            raise TectonicsError('noncanonical adaptive-inner policy')
        if expected_policy is not None and policy != expected_policy:
            raise TectonicsError('adaptive-inner policy mismatch')
        if type(record['active']) is not bool:
            raise TectonicsError('invalid adaptive-inner activation')
        for key in ('nonlinear_iterations', 'linear_calls', 'strict_calls'):
            if type(record[key]) is not int or record[key] < 0:
                raise TectonicsError('invalid adaptive-inner count')
        if record['nonlinear_iterations'] != iterations or not 1 <= iterations <= nonlinear_policy.max_picard_iterations:
            raise TectonicsError('adaptive nonlinear count mismatch')
        n = record['linear_calls']
        if n != (iterations if record['active'] else 0):
            raise TectonicsError('adaptive linear count mismatch')
        h = record['history_sha256']
        if type(h) is not str or len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
            raise TectonicsError('invalid adaptive history hash')
        if not record['active']:
            if record['strict_calls'] or record['final_certification'] is not None or h != hashlib.sha256(_json([])).hexdigest():
                raise TectonicsError('inactive adaptive policy claims work')
            return policy
        if not 1 <= record['strict_calls'] <= n:
            raise TectonicsError('missing strict certification')
        f = record['final_certification']
        if type(f) is not dict or set(f) != {'linear_rtol', 'rhs_l2', 'target_l2',
                'internal_residual_l2', 'returned_residual_l2', 'coefficient_sha256', 'system'}:
            raise TectonicsError('invalid final linear certificate')
        if f['system'] != 'last-frozen-viscosity-linear-system' or f['linear_rtol'] != nonlinear_policy.linear_rtol:
            raise TectonicsError('final certificate uses different linear policy')
        for key in ('rhs_l2', 'target_l2', 'internal_residual_l2', 'returned_residual_l2'):
            scalar(f[key], key, nonnegative=True)
        if (f['target_l2'] != nonlinear_policy.linear_rtol*f['rhs_l2'] or
                max(f['internal_residual_l2'], f['returned_residual_l2']) > f['target_l2']):
            raise TectonicsError('final strict linear target not satisfied')
        h = f['coefficient_sha256']
        if type(h) is not str or len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
            raise TectonicsError('invalid certification coefficient hash')
        return policy
    except (KeyError, TypeError, ValueError) as exc:
        raise TectonicsError('invalid adaptive-inner summary') from exc


def check_history(record, rows, history, nonlinear_policy):
    policy = check_summary(record, len(history), nonlinear_policy)
    if (type(rows) is not list or len(rows) != record['linear_calls'] or
            hashlib.sha256(_json(rows)).hexdigest() != record['history_sha256']):
        raise TectonicsError('adaptive history differs from summary')
    strict_phase = False
    for i, row in enumerate(rows):
        if type(row) is not dict or set(row) != {'rhs_l2', 'defect_l2', 'target_l2',
                'residual_l2', 'strict_requested', 'strict_certified', 'history_reset', 'iterations'}:
            raise TectonicsError('invalid adaptive linear record')
        for key in ('rhs_l2', 'defect_l2', 'target_l2', 'residual_l2'):
            scalar(row[key], key, nonnegative=True)
        for key in ('strict_requested', 'strict_certified', 'history_reset'):
            if type(row[key]) is not bool:
                raise TectonicsError('invalid adaptive certification flag')
        if type(row['iterations']) is not int or row['iterations'] != history[i]['linear_iterations']:
            raise TectonicsError('adaptive iteration count differs')
        wanted, strict = target(policy, nonlinear_policy.linear_rtol,
                                row['rhs_l2'], row['defect_l2'], row['strict_requested'])
        if (row['target_l2'] != wanted or row['residual_l2'] > wanted or
                row['strict_certified'] != strict or (strict_phase and not row['strict_requested'])):
            raise TectonicsError('adaptive schedule or certification violated')
        if row['history_reset'] != (strict and not strict_phase):
            raise TectonicsError('invalid adaptive strict-history transition')
        strict_phase = strict_phase or strict
    if rows:
        f = record['final_certification']; last = rows[-1]
        if (not last['strict_certified'] or record['strict_calls'] != sum(r['strict_certified'] for r in rows) or
                f['rhs_l2'] != last['rhs_l2'] or f['target_l2'] != last['target_l2'] or
                f['internal_residual_l2'] != last['residual_l2']):
            raise TectonicsError('final certification differs from final linear solve')


def check_stage(record, rows, iterations, linear_iterations, nonlinear_policy, expected_policy):
    """Audit bounded per-stage tolerances, including unsaved intermediate steps.

    Full mechanical records also check these rows against their nonlinear history.
    A coupled ledger retains the actual target/residual sequence, not only its hash.
    """
    check_summary(record, iterations, nonlinear_policy, expected_policy)
    if type(rows) is not list or len(rows) != record['linear_calls']:
        raise TectonicsError('missing or oversized adaptive stage history')
    if not record['active']:
        check_history(record, rows, [{} for _ in range(iterations)], nonlinear_policy)
        return
    if any(type(row) is not dict or type(row.get('iterations')) is not int or
           row['iterations'] < 0 for row in rows):
        raise TectonicsError('invalid adaptive stage linear counts')
    if sum(row['iterations'] for row in rows) != linear_iterations:
        raise TectonicsError('adaptive stage linear count differs from ledger')
    check_history(record, rows, [{'linear_iterations': row['iterations']} for row in rows],
                  nonlinear_policy)
