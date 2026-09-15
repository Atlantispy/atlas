"""Constant-flux, fixed-wet-area, one-class well-mixed reservoir reference.

W and S are liquid and suspended solid volumes [m3]; D is transferred solid
volume, not bulk porous sediment. qW/qS/qO are m3/year, area is m2, settling
velocity is m/year and time is years. With V=W+S and k=v*A:
  W'=qW-qO*W/V; S'=qS-(qO+k)*S/V; D'=k*S/V.
Both phase exports are integrated separately. No clipping or residual repair.

RK4 step doubling accepts the unextrapolated two-half-step state only when all
stages are nonnegative and the error estimate is within the predeclared local
budget. Local budgets sum to the stated solver budget over the requested time.
This estimate is not a rigorous global error bound. Independent refinement and
analytical tests are required; this is not hydraulic/physical validation.

Conservation tolerances copy frozen R3 settling.py eac658c58a362f29448e77b9327c1
e06f12e311fcc6cba919bd3d8a62d8be5ba: 1e-9 m3 + 1e-12*scale. Solver settings
below were declared before the first numerical test. No source/filesystem I/O.
Caller owns geometry, wetting/drying/sill events, export closure and applicability.
In particular qO=qW+qS permits occupied V to fall as nonporous D raises the bed;
it is not a claim that a changing pool has constant water/mixture volume.
"""
from __future__ import annotations

import math
import time

VOLUME_ATOL_M3 = 1e-9
VOLUME_RTOL = 1e-12
SOLVER_ATOL_M3 = 1e-12
SOLVER_RTOL = 2e-13
MAX_ATTEMPTS = 8192
MAX_EVALUATIONS = 65536
MAX_WALL_SECONDS = 30.


class ContinuousPoolError(ValueError):
    """Invalid, unrepresentable or out-of-envelope reference request."""


class _StageDomain(Exception):
    pass


def _number(value, name, *, positive=False):
    if type(value) not in (int, float):
        raise ContinuousPoolError(name+': finite scalar required, not Boolean')
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise ContinuousPoolError(name+': scalar exceeds binary64') from exc
    if not math.isfinite(value) or value < 0 or (positive and value <= 0):
        raise ContinuousPoolError(name+': outside finite nonnegative domain')
    return value


def _sum(values, name):
    try:
        result = math.fsum(values)
    except (ValueError, OverflowError) as exc:
        raise ContinuousPoolError(name+': sum exceeds binary64') from exc
    if not math.isfinite(result):
        raise ContinuousPoolError(name+': nonfinite sum')
    return result


def _product(a, b, name):
    result = a*b
    if not math.isfinite(result) or (a and b and result == 0):
        raise ContinuousPoolError(name+': product overflow/underflow')
    return result


def _ratio(a, b, name):
    result = a/b
    if not math.isfinite(result) or (a and result == 0):
        raise ContinuousPoolError(name+': ratio overflow/underflow')
    return result


def _balance(final_terms, initial, supplied, removed):
    # Preserve each stored/transferred phase until the signed residual is
    # summed; rounding S+D first can conceal a sub-ULP deposition residual.
    final = _sum(final_terms, 'ledger final total')
    residual = _sum((*final_terms, -initial, -supplied, removed), 'volume residual')
    tolerance = VOLUME_ATOL_M3 + VOLUME_RTOL*max(final, initial, supplied, removed)
    if abs(residual) > tolerance:
        raise ContinuousPoolError('volume ledger exceeds frozen R3 tolerance')
    return {'initial_m3':initial, 'input_m3':supplied, 'final_m3':final,
            'final_components_m3':list(final_terms),
            'exported_or_transferred_m3':removed, 'residual_m3':residual,
            'tolerance_m3':tolerance}


def _birth(qw, qs, k, duration):
    """Stable positive quadratic root; no subtractive qS-s deposition rate."""
    if qs == 0:
        return (_product(qw, duration, 'birth liquid'), 0., 0., 0., 0.)
    scale = max(qw, qs, k)
    a, b, c = (_ratio(value, scale, 'scaled birth rate') for value in (qw, qs, k))
    coefficient = _sum((a, c, -b), 'birth quadratic coefficient')
    cross = 2*math.sqrt(a)*math.sqrt(b)
    discriminant = math.hypot(coefficient, cross)
    if coefficient >= 0:
        root = _ratio(_product(2*a, b, 'birth quadratic numerator'),
                      discriminant+coefficient, 'positive birth root')
    else:
        root = (discriminant-coefficient)/2
    solid_rate = _product(scale, root, 'birth suspended rate')
    deposition_rate = _product(k, _ratio(solid_rate, _sum((qw, solid_rate), 'birth volume rate'),
                                         'birth concentration'), 'birth deposition rate')
    return (_product(qw, duration, 'birth liquid'),
            _product(solid_rate, duration, 'birth suspended'),
            _product(deposition_rate, duration, 'birth deposit'), 0., 0.)


def _advance_pool(liquid_m3, suspended_solid_m3, area_m2,
                  liquid_input_m3_year, solid_input_m3_year,
                  mixture_export_m3_year, settling_m_year, dt_years,
                  _work):
    """Return W/S/D and separate exports; never mutate inputs or own geometry.

Zero inventory with qO=0 uses the exact self-similar birth solution. Positive
export at zero inventory rejects: an export/wetting closure is caller-owned.
A dry endpoint in the pure-liquid linear limit is allowed; an interval beyond
drying is rejected. General depletion that loses positive stages fails closed.
"""
    started = time.monotonic()
    w0 = _number(liquid_m3, 'liquid_m3')
    s0 = _number(suspended_solid_m3, 'suspended_solid_m3')
    area = _number(area_m2, 'area_m2', positive=True)
    qw = _number(liquid_input_m3_year, 'liquid_input_m3_year')
    qs = _number(solid_input_m3_year, 'solid_input_m3_year')
    qo = _number(mixture_export_m3_year, 'mixture_export_m3_year')
    velocity = _number(settling_m_year, 'settling_m_year')
    duration = _number(dt_years, 'dt_years')
    if (s0 > 0 and w0 == 0) or (qs > 0 and qw == 0):
        raise ContinuousPoolError('suspension requires same-pool liquid/carrier supply')
    k = _product(velocity, area, 'settling area rate')
    _sum((w0, s0), 'initial mixture')
    imported_w = _product(qw, duration, 'liquid input')
    imported_s = _product(qs, duration, 'solid input')
    exported_volume = _product(qo, duration, 'mixture export')
    evaluations = attempts = accepted = rejected = 0
    largest_error_ratio = 0.
    minimum_step = None

    def check_bound():
        if time.monotonic()-started > MAX_WALL_SECONDS:
            raise ContinuousPoolError('continuous reservoir wall-time envelope exceeded')

    def rhs(state):
        nonlocal evaluations
        evaluations += 1
        _work['evaluations'] = evaluations
        if evaluations > MAX_EVALUATIONS:
            raise ContinuousPoolError('continuous reservoir evaluation envelope exceeded')
        w, s, deposited, ew, es = state
        if any(not math.isfinite(x) or x < 0 for x in state):
            raise _StageDomain()
        volume = _sum((w, s), 'stage mixture')
        if volume <= 0 or (s > 0 and w == 0):
            raise _StageDomain()
        fw = _ratio(w, volume, 'liquid fraction')
        fs = _ratio(s, volume, 'suspended fraction')
        out_w = _product(qo, fw, 'liquid export rate')
        out_s = _product(qo, fs, 'solid export rate')
        settling = _product(k, fs, 'settling rate')
        return (_sum((qw, -out_w), 'liquid derivative'),
                _sum((qs, -out_s, -settling), 'suspension derivative'),
                settling, out_w, out_s)

    def shifted(state, derivative, step):
        return tuple(_sum((value, _product(step, rate, 'RK stage change')), 'RK stage')
                     for value, rate in zip(state, derivative))

    def rk4(state, step):
        half = step/2
        if half == 0:
            raise ContinuousPoolError('RK stage time underflows')
        a = rhs(state)
        b = rhs(shifted(state, a, half))
        c = rhs(shifted(state, b, half))
        d = rhs(shifted(state, c, step))
        result = tuple(_sum((value, _product(step, _sum((aa/6, bb/3, cc/3, dd/6),
                                                        'RK weighted derivative'), 'RK change')), 'RK result')
                       for value, aa, bb, cc, dd in zip(state, a, b, c, d))
        if (any(value < 0 for value in result) or result[0]+result[1] <= 0
                or (result[1] > 0 and result[0] == 0)):
            raise _StageDomain()
        return result

    if duration == 0:
        state, method = (w0, s0, 0., 0., 0.), 'EXACT_ZERO_DURATION'
    elif w0 == 0:
        if qo > 0:
            raise ContinuousPoolError('positive export from empty pool needs a wetting/export closure')
        state = _birth(qw, qs, k, duration) if qw > 0 else (0., 0., 0., 0., 0.)
        method = 'EXACT_SELF_SIMILAR_EMPTY_POOL_BIRTH'
    elif s0 == 0 and qs == 0:
        water = _sum((w0, imported_w, -exported_volume), 'pure liquid final inventory')
        if water < 0:
            raise ContinuousPoolError('requested interval passes pure-liquid drying event')
        state, method = (water, 0., 0., exported_volume, 0.), 'EXACT_PURE_LIQUID_LIMIT'
    elif qw == qs == qo == k == 0:
        state, method = (w0, s0, 0., 0., 0.), 'EXACT_UNFORCED_LIMIT'
    else:
        state, now, step = (w0, s0, 0., 0., 0.), 0., duration
        method = 'POSITIVE_STAGE_RK4_STEP_DOUBLING'
        while now < duration:
            check_bound()
            attempts += 1
            _work['attempts'] = attempts
            if attempts > MAX_ATTEMPTS:
                raise ContinuousPoolError('continuous reservoir attempt envelope exceeded')
            remaining = duration-now
            step = min(step, remaining)
            if step <= 0 or now+step == now:
                raise ContinuousPoolError('positive reservoir step is below time resolution; event outside fixed-set scope')
            try:
                coarse = rk4(state, step)
                refined = rk4(rk4(state, step/2), step/2)
                ratio = 0.
                for a, b, old in zip(coarse, refined, state):
                    local_budget = (SOLVER_ATOL_M3+SOLVER_RTOL*max(abs(old), abs(a), abs(b)))*(step/duration)
                    if local_budget <= 0:
                        raise ContinuousPoolError('local error budget underflows')
                    ratio = max(ratio, abs(a-b)/(15*local_budget))
            except _StageDomain:
                rejected += 1
                step /= 2
                continue
            if ratio > 1:
                rejected += 1
                step *= max(.1, .8*ratio**(-.2))
                continue
            state = refined
            now = duration if step == remaining else now+step
            accepted += 1
            minimum_step = step if minimum_step is None else min(minimum_step, step)
            largest_error_ratio = max(largest_error_ratio, ratio)
            step *= 2. if ratio == 0 else min(2., max(1.05, .9*ratio**(-.2)))
    check_bound()
    w, s, deposited, ew, es = state
    if any(not math.isfinite(value) or value < 0 for value in state):
        raise ContinuousPoolError('nonfinite or negative final reservoir phase')
    if s > 0 and w == 0:
        raise ContinuousPoolError('final suspension has no represented liquid carrier')
    _sum((w, s), 'final mixture')
    ledgers = {'liquid':_balance((w,), w0, imported_w, ew),
               'solid':_balance((s, deposited), s0, imported_s, es),
               'mixture_export':_balance((ew, es), 0., exported_volume, 0.)}
    return {'status':'PASS_FIXED_WET_SET_NUMERICAL_REFERENCE', 'method':method,
            'liquid_m3':w, 'suspended_solid_m3':s, 'deposited_solid_m3':deposited,
            'exported_liquid_m3':ew, 'exported_suspended_solid_m3':es,
            'imported_liquid_m3':imported_w, 'imported_suspended_solid_m3':imported_s,
            'elapsed_years':duration, 'wet_area_m2':area, 'ledgers':ledgers,
            'evaluations':evaluations, 'attempts':attempts, 'accepted_steps':accepted,
            'rejected_steps':rejected, 'minimum_accepted_step_years':minimum_step,
            'largest_accepted_error_ratio':largest_error_ratio,
            'bounds':{'attempts':MAX_ATTEMPTS, 'evaluations':MAX_EVALUATIONS, 'wall_seconds':MAX_WALL_SECONDS},
            'solver_atol_m3':SOLVER_ATOL_M3, 'solver_rtol':SOLVER_RTOL,
            'physical_acceptance':False, 'production_authorised':False,
            'geometry_or_wet_events_solved':False, 'hydraulics_solved':False}


def advance_pool(liquid_m3, suspended_solid_m3, area_m2,
                 liquid_input_m3_year, solid_input_m3_year,
                 mixture_export_m3_year, settling_m_year, dt_years):
    """Advance one bounded pool and attach attempted work to every error.

    Validation failures occur before numerical work and therefore carry zero
    counts.  Once integration begins, the counters are updated before each
    attempt and RHS evaluation, including the operation that exhausts a cap.
    """
    work = {'evaluations':0, 'attempts':0}
    try:
        return _advance_pool(liquid_m3, suspended_solid_m3, area_m2,
            liquid_input_m3_year, solid_input_m3_year,
            mixture_export_m3_year, settling_m_year, dt_years, work)
    except ContinuousPoolError as exc:
        exc.evaluations = work['evaluations']
        exc.attempts = work['attempts']
        raise
