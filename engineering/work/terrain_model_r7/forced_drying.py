"""First forced-pool drying event for the bounded R4 reduced reference.

The fixed wet set is one level, well-mixed reservoir.  Each probe calls
``continuous_pool.advance_pool`` from the identical initial checkpoint.  This
module finds only the first loss of the shallowest native cell(s); it neither
constructs daughter geometry nor assigns continuing forcing to daughters.
"""
from __future__ import annotations

from fractions import Fraction
import functools
import hashlib
import math
from pathlib import Path
import time

import continuous_pool
import event_bounds

MAX_NATIVE_CELLS = 4096
MAX_SCALAR_CALLS = 128
MAX_SCALAR_EVALUATIONS = 1_048_576
MAX_BISECTIONS = 48
MAX_WALL_SECONDS = 60.0
TIME_ATOL_YEARS = 1e-10
TIME_RTOL = 1e-11
HEIGHT_ATOL_M = 1e-9
HEIGHT_RTOL = 1e-11
_BASE = Path(__file__).resolve().parent
SOURCE_PINS = {
    'continuous_pool.py':'e27bb4aa4c9495273fbc94fcb10d0a842317c623d7577cbc23c46f75f955beb7',
    'event_bounds.py':'8a8531c7ca11d23bed280fc2f1708af6879eef516772f1db92bb7f5e73c42cdf',
    'FORCED_DRYING_DESIGN.md':'5c72073686f8dc929274c5703793d1092b456a3bedb8db8a975297b92e7695e2',
}


class ForcedDryingError(ValueError):
    """Invalid request outside the bounded fixed-wet-set event contract."""

    def __init__(self, message, *, failure_kind='INVALID_INPUT'):
        super().__init__(message)
        self.failure_kind = failure_kind


def _number(value, name, *, positive=False):
    if type(value) not in (int, float):
        raise ForcedDryingError(name+': finite scalar required, not Boolean')
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise ForcedDryingError(name+': scalar exceeds binary64') from exc
    if not math.isfinite(value) or value < 0 or (positive and value <= 0):
        raise ForcedDryingError(name+': outside finite nonnegative domain')
    return value


def _rate(value, name):
    return _number(value, name)


def _sum(values, name):
    try:
        result=math.fsum(values)
    except (ValueError,OverflowError) as exc:
        raise ForcedDryingError(name+': sum exceeds binary64') from exc
    if not math.isfinite(result):
        raise ForcedDryingError(name+': nonfinite sum')
    return result


def _product(left, right, name):
    result=left*right
    if not math.isfinite(result) or (left and right and result == 0):
        raise ForcedDryingError(name+': product overflow/underflow')
    return result


def _equilibrium(qw, qs, k):
    total = math.fsum((qw, qs))
    if qs == 0:
        return 0.0
    if k == 0:
        return qs/total
    scale = max(total, k)
    q, kk, ww = total/scale, k/scale, qw/scale
    discriminant = math.hypot(q-kk, 2*math.sqrt(kk)*math.sqrt(ww))
    scaled_solid=qs/scale
    root = 2*scaled_solid/(q+kk+discriminant)
    if qs > 0 and (scaled_solid == 0 or root == 0):
        raise ForcedDryingError('positive concentration equilibrium underflows binary64')
    if not math.isfinite(root) or not 0 <= root < 1:
        raise ForcedDryingError('physical concentration equilibrium is unrepresentable')
    return root


def _source_snapshot(implementation_bytes=None):
    for name,module in (('continuous_pool',continuous_pool),('event_bounds',event_bounds)):
        bound_module=(_BASE/(name+'.py')).resolve()
        loaded_path=getattr(module,'__file__',None)
        if loaded_path is None or Path(loaded_path).resolve() != bound_module:
            raise ForcedDryingError('loaded '+name+' module is not the bound source path',
                                    failure_kind='SOURCE_INTEGRITY_FAILURE')
    records=[]
    for name,expected in SOURCE_PINS.items():
        path=_BASE/name;data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
        if digest != expected:
            raise ForcedDryingError('bound forced-drying source identity mismatch: '+name, failure_kind='SOURCE_INTEGRITY_FAILURE')
        records.append({'name':name,'path':str(path),'size_bytes':len(data),'sha256':digest})
    implementation=_BASE/'forced_drying.py';data=implementation.read_bytes()
    if implementation_bytes is not None and data != implementation_bytes:
        raise ForcedDryingError('forced-drying implementation changed during event solve',
                                failure_kind='SOURCE_INTEGRITY_FAILURE')
    records.append({'name':'forced_drying.py','path':str(implementation),
                    'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    return records,data


def _branch(w, s, qw, qs, velocity, area):
    volume = Fraction(w)+Fraction(s)
    concentration = Fraction(s)/volume
    total = Fraction(qw)+Fraction(qs)
    # The sign is a mathematical branch decision.  Form k from the exact
    # supplied binary64 values rather than from their rounded product.
    exact_k = Fraction(velocity)*Fraction(area)
    polynomial = (Fraction(qs)-(total+exact_k)*concentration
                  +exact_k*concentration*concentration)
    return ('INCREASING_CONCENTRATION' if polynomial > 0 else
            'DECREASING_CONCENTRATION' if polynomial < 0 else
            'CONSTANT_CONCENTRATION'), concentration, polynomial


def _fraction_interval(value):
    """Smallest binary64 interval enclosing an exact Fraction."""
    try:
        centre = float(value)
    except OverflowError as exc:
        raise ForcedDryingError('derived rational value exceeds binary64') from exc
    if not math.isfinite(centre):
        raise ForcedDryingError('derived rational value exceeds binary64')
    represented = Fraction(centre)
    low = math.nextafter(centre, -math.inf) if represented > value else centre
    high = math.nextafter(centre, math.inf) if represented < value else centre
    return centre, low, high


def _blocked(base, status, reason, **extra):
    return {**base, 'status':status, 'reason':reason, **extra,
            'physical_acceptance':False, 'production_authorised':False,
            'daughter_geometry_solved':False, 'remaining_interval_completed':False}


def _guard_public_sources(function):
    """Recheck the complete bound closure on every return and exception."""
    @functools.wraps(function)
    def guarded(*args, **kwargs):
        work = {'scalar_calls':0, 'scalar_rhs_evaluations':0}
        try:
            if '_work' in kwargs:
                raise ForcedDryingError('private work tracker is not a caller control')
            entry_identity, implementation_bytes = _source_snapshot()
            try:
                result = function(*args, **kwargs, _work=work)
            finally:
                exit_identity,_ = _source_snapshot(implementation_bytes)
        except ForcedDryingError as exc:
            for name, value in work.items():
                setattr(exc, name, value)
            raise
        if isinstance(result, dict):
            # The inner solve reports probe-adjacent and pre-finish rechecks.
            # Count its initial snapshot and this public-exit snapshot too.
            result['source_rechecks'] = result.get('source_rechecks', 0)+2
            result['source_identity_public_entry'] = entry_identity
            result['source_identity_public_exit'] = exit_identity
        return result
    return guarded


@_guard_public_sources
def first_event(*, liquid_m3, suspended_solid_m3, total_wet_area_m2,
                shallowest_depth_m, shallowest_cell_indices,
                shallowest_cell_depths_m, liquid_input_m3_year,
                solid_input_m3_year, mixture_export_m3_year,
                settling_m_year, duration_years, native_cell_count,
                start_time_years=0.0, shallowest_depth_ratio=None,
                positive_depth_area_m2=None,
                post_event_schedule=None, max_scalar_calls=MAX_SCALAR_CALLS,
                max_scalar_evaluations=MAX_SCALAR_EVALUATIONS,
                wall_seconds=MAX_WALL_SECONDS, _work=None):
    """Return a certified no-event result or a bracketed first drying event.

    ``shallowest_cell_indices`` is the caller's exact router-derived tie set;
    every corresponding supplied depth must equal ``shallowest_depth_m`` as a
    binary64 value.  Aggregate parent forcing is never assigned to daughters.
    """
    started = time.monotonic()
    source_identity,implementation_bytes=_source_snapshot()
    w0 = _number(liquid_m3, 'liquid_m3')
    s0 = _number(suspended_solid_m3, 'suspended_solid_m3')
    area = _number(total_wet_area_m2, 'total_wet_area_m2', positive=True)
    positive_area=(area if positive_depth_area_m2 is None else
                   _number(positive_depth_area_m2,'positive_depth_area_m2',positive=True))
    if Fraction(positive_area) > Fraction(area):
        raise ForcedDryingError('positive-depth area exceeds total wet area')
    depth = _number(shallowest_depth_m, 'shallowest_depth_m', positive=True)
    if shallowest_depth_ratio is None:
        depth_fraction=Fraction(depth)
        depth_authority='SUPPLIED_BINARY64_DEPTH'
    else:
        if (type(shallowest_depth_ratio) is not dict
                or set(shallowest_depth_ratio) != {'numerator','denominator'}
                or type(shallowest_depth_ratio['numerator']) is not int
                or type(shallowest_depth_ratio['denominator']) is not int
                or shallowest_depth_ratio['numerator'] <= 0
                or shallowest_depth_ratio['denominator'] <= 0
                or shallowest_depth_ratio['numerator'].bit_length() > 4096
                or shallowest_depth_ratio['denominator'].bit_length() > 4096):
            raise ForcedDryingError('exact shallowest-depth ratio requires positive integer numerator/denominator')
        depth_fraction=Fraction(shallowest_depth_ratio['numerator'],
                                shallowest_depth_ratio['denominator'])
        try:
            represented_depth=float(depth_fraction)
        except OverflowError as exc:
            raise ForcedDryingError('exact shallowest-depth ratio exceeds binary64') from exc
        if represented_depth != depth:
            raise ForcedDryingError('represented shallowest depth does not match exact ratio')
        depth_authority='CALLER_SUPPLIED_EXACT_RATIO'
    qw = _rate(liquid_input_m3_year, 'liquid_input_m3_year')
    qs = _rate(solid_input_m3_year, 'solid_input_m3_year')
    qo = _rate(mixture_export_m3_year, 'mixture_export_m3_year')
    velocity = _rate(settling_m_year, 'settling_m_year')
    duration = _number(duration_years, 'duration_years')
    absolute_start = _number(start_time_years, 'start_time_years')
    wall = _number(wall_seconds, 'wall_seconds', positive=True)
    if wall > MAX_WALL_SECONDS:
        raise ForcedDryingError('outer wall-time envelope exceeds hard bound')
    if type(max_scalar_calls) is not int or not 1 <= max_scalar_calls <= MAX_SCALAR_CALLS:
        raise ForcedDryingError('scalar-call envelope outside hard bound')
    if type(max_scalar_evaluations) is not int or not 1 <= max_scalar_evaluations <= MAX_SCALAR_EVALUATIONS:
        raise ForcedDryingError('scalar-evaluation envelope outside hard bound')
    if type(native_cell_count) is not int or not 1 <= native_cell_count <= MAX_NATIVE_CELLS:
        raise ForcedDryingError('native-cell count outside hard bound')
    if w0+s0 <= 0 or (s0 > 0 and w0 == 0) or (qs > 0 and qw == 0):
        raise ForcedDryingError('represented pool needs positive liquid-carried inventory')
    if (not math.isfinite(w0+s0)
            or depth_fraction > (Fraction(w0)+Fraction(s0))/Fraction(positive_area)):
        raise ForcedDryingError('shallowest depth is inconsistent with represented pool volume')
    if duration and absolute_start+duration == absolute_start:
        return _blocked({}, 'BLOCKED_UNREPRESENTABLE_EVENT',
                        'positive relative interval cannot advance absolute binary64 time')
    if (type(shallowest_cell_indices) not in (list, tuple)
            or type(shallowest_cell_depths_m) not in (list, tuple)
            or not shallowest_cell_indices
            or len(shallowest_cell_indices) != len(shallowest_cell_depths_m)
            or len(shallowest_cell_indices) > native_cell_count):
        raise ForcedDryingError('bounded exact shallowest-cell tie inventory required')
    indices = []
    for cell in shallowest_cell_indices:
        if type(cell) is not int or cell < 0 or cell >= native_cell_count or cell in indices:
            raise ForcedDryingError('shallowest-cell indices must be unique and inside native-cell count')
        indices.append(cell)
    tied_depths = [_number(value, 'shallowest cell depth', positive=True)
                   for value in shallowest_cell_depths_m]
    if any(Fraction(value) != Fraction(depth) for value in tied_depths):
        raise ForcedDryingError('supplied shallowest-cell tie is not exact')
    if post_event_schedule is not None:
        raise ForcedDryingError('post-event schedule is unsupported until hash-bound piecewise forcing exists')
    post = {'liquid_input_m3_year':qw, 'solid_input_m3_year':qs,
            'mixture_export_m3_year':qo}

    k = _product(velocity,area,'settling area rate')
    total_rate = _sum((qw,qs),'combined input rate')
    net_rate = _sum((total_rate,-qo),'net occupied-volume rate')
    eta_rate = net_rate/area
    if not math.isfinite(eta_rate) or (net_rate and eta_rate == 0):
        raise ForcedDryingError('stage rate overflow/underflow')
    eta_rate_fraction=(Fraction(qw)+Fraction(qs)-Fraction(qo))/Fraction(area)
    branch, c0_fraction, polynomial = _branch(w0, s0, qw, qs, velocity, area)
    analytic_bound = event_bounds.no_drying_bound(liquid=w0,solid=s0,area=area,
        qw=qw,qs=qs,qo=qo,velocity=velocity,duration=duration,depth=depth_fraction)
    c0 = float(c0_fraction)
    equilibrium = _equilibrium(qw, qs, k)
    deadline = started+wall
    probes = []
    scalar_calls = scalar_evaluations = source_rechecks = 0

    base = {'mathematical_branch':branch, 'equilibrium_concentration':equilibrium,
            'initial_concentration':c0,
            'initial_polynomial_sign':1 if polynomial > 0 else -1 if polynomial < 0 else 0,
            'stage_rate_m_year':eta_rate, 'settling_area_rate_m3_year':k,
            'shallowest_depth_m':depth, 'shallowest_cell_indices':indices,
            'shallowest_cell_depths_m':tied_depths, 'start_time_years':absolute_start,
            'shallowest_depth_exact':{'numerator':depth_fraction.numerator,
                                       'denominator':depth_fraction.denominator},
            'shallowest_depth_authority':depth_authority,
            'native_cell_count':native_cell_count,
            'total_wet_area_m2':area,'positive_depth_area_m2':positive_area,
            'shallowest_tie_certificate':'CALLER_SUPPLIED_EXACT_PRECONDITION_NOT_INTERNALLY_COMPLETE',
            'requested_duration_years':duration,
            'event_time_tolerance_years':TIME_ATOL_YEARS+TIME_RTOL*duration,
            'height_tolerance_m':HEIGHT_ATOL_M+HEIGHT_RTOL*depth,
            'post_event_schedule':None,
            'post_event_forcing_inference':'CONSTANT_PRE_EVENT_RATES_ONLY',
            'probe_origin':'IDENTICAL_INITIAL_CHECKPOINT','source_identity':source_identity}

    def check_resources():
        if time.monotonic() > deadline:
            raise ForcedDryingError('forced-drying cooperative wall-time envelope exceeded', failure_kind='RESOURCE_EXHAUSTED')

    def probe(t):
        nonlocal scalar_calls, scalar_evaluations, source_rechecks
        check_resources()
        if scalar_calls >= max_scalar_calls:
            raise ForcedDryingError('forced-drying scalar-call envelope exhausted', failure_kind='RESOURCE_EXHAUSTED')
        scalar_calls += 1
        _work['scalar_calls'] = scalar_calls
        _source_snapshot(implementation_bytes);source_rechecks+=1
        try:
            remaining = max_scalar_evaluations-scalar_evaluations
            # Retain the normal per-call guard; a smaller aggregate allowance
            # is enforced BEFORE another numerical RHS operation executes.
            kwargs = {'max_evaluations':remaining} if remaining < continuous_pool.MAX_EVALUATIONS else {}
            result = continuous_pool.advance_pool(w0, s0, area, qw, qs, qo, velocity, t, **kwargs)
            evaluations=result.get('evaluations')
            if type(evaluations) is not int or not 0 <= evaluations <= continuous_pool.MAX_EVALUATIONS:
                raise ForcedDryingError('scalar result has invalid RHS-evaluation count')
            scalar_evaluations += evaluations
            _work['scalar_rhs_evaluations'] = scalar_evaluations
            if scalar_evaluations > max_scalar_evaluations:
                raise ForcedDryingError('forced-drying scalar-evaluation envelope exhausted', failure_kind='RESOURCE_EXHAUSTED')
        except continuous_pool.ContinuousPoolError as exc:
            known=getattr(exc,'evaluations',None)
            if (type(known) is int and 0 <= known
                    <= continuous_pool.MAX_EVALUATIONS+1):
                scalar_evaluations += known
                _work['scalar_rhs_evaluations'] = scalar_evaluations
                counted=True
            else:
                counted=False
            if scalar_evaluations > max_scalar_evaluations or getattr(exc,'evaluation_budget_exhausted',False):
                raise ForcedDryingError('forced-drying scalar-evaluation envelope exhausted', failure_kind='RESOURCE_EXHAUSTED') from exc
            kind=getattr(exc,'failure_kind','INVALID_INPUT')
            if kind != 'PHASE_DOMAIN_FAILURE':
                raise ForcedDryingError('scalar solver '+kind+': '+str(exc), failure_kind=kind) from exc
            row = {'time_years':t, 'status':'PHASE_DOMAIN_FAILURE',
                   'error_type':type(exc).__name__, 'error':str(exc),
                   'failed_rhs_evaluations_counted':counted,
                   'failed_rhs_evaluations':known if counted else None}
            probes.append(row)
            return row
        finally:
            _source_snapshot(implementation_bytes);source_rechecks+=1
            check_resources()
        mixture = math.fsum((result['liquid_m3'], result['suspended_solid_m3']))
        if mixture <= 0 or (result['suspended_solid_m3'] > 0 and result['liquid_m3'] == 0):
            row = {'time_years':t, 'status':'PHASE_DOMAIN_FAILURE',
                   'error_type':'ForcedDryingError', 'error':'probe lost represented carrier phase',
                   'failed_rhs_evaluations_counted':True,
                   'failed_rhs_evaluations':evaluations}
            probes.append(row)
            return row
        exact_method = result['method'].startswith('EXACT_')
        scale = max(w0, s0, result['liquid_m3'], result['suspended_solid_m3'],
                    result['deposited_solid_m3'], result['imported_liquid_m3'],
                    result['imported_suspended_solid_m3'], result['exported_liquid_m3'],
                    result['exported_suspended_solid_m3'])
        volume_error_fraction=(Fraction(0) if exact_method else
            Fraction(continuous_pool.SOLVER_ATOL_M3)
            +Fraction(continuous_pool.SOLVER_RTOL)*Fraction(scale))
        _, _, volume_error=_fraction_interval(volume_error_fraction)
        if Fraction(result['liquid_m3'])+Fraction(result['suspended_solid_m3']) <= 2*volume_error_fraction:
            row = {'time_years':t, 'status':'PHASE_DOMAIN_FAILURE',
                   'error_type':'ForcedDryingError', 'error':'concentration error band consumes mixture'}
            probes.append(row)
            return row
        exact_mixture=(Fraction(result['liquid_m3'])
                       +Fraction(result['suspended_solid_m3']))
        exact_concentration=Fraction(result['suspended_solid_m3'])/exact_mixture
        if volume_error_fraction == 0:
            concentration_radius=Fraction(0)
        else:
            denominator=exact_mixture-2*volume_error_fraction
            if denominator <= 0:
                row = {'time_years':t, 'status':'PHASE_DOMAIN_FAILURE',
                       'error_type':'ForcedDryingError', 'error':'concentration error band consumes mixture'}
                probes.append(row)
                return row
            concentration_radius=min(Fraction(1),2*volume_error_fraction/denominator)
        concentration, _, _ = _fraction_interval(exact_concentration)
        c_low_exact=max(Fraction(0),exact_concentration-concentration_radius)
        c_high_exact=min(Fraction(1),exact_concentration+concentration_radius)
        _, concentration_low, _=_fraction_interval(c_low_exact)
        _, _, concentration_high=_fraction_interval(c_high_exact)
        exact_height=(depth_fraction
                      +(Fraction(qw)+Fraction(qs)-Fraction(qo))*Fraction(t)/Fraction(area)
                      -Fraction(result['deposited_solid_m3'])/Fraction(area))
        height_radius=volume_error_fraction/Fraction(area)
        height, height_lower, _=_fraction_interval(exact_height-height_radius)
        centre_height, _, _=_fraction_interval(exact_height)
        _, _, height_upper=_fraction_interval(exact_height+height_radius)
        exact_slope_centre=eta_rate_fraction-Fraction(velocity)*exact_concentration
        slope, _, _=_fraction_interval(exact_slope_centre)
        _, slope_lower, _=_fraction_interval(eta_rate_fraction-Fraction(velocity)*c_high_exact)
        _, _, slope_upper=_fraction_interval(eta_rate_fraction-Fraction(velocity)*c_low_exact)
        concentration_error=max(concentration-concentration_low,
                                concentration_high-concentration)
        height_error=max(centre_height-height_lower,height_upper-centre_height)
        slope_error=max(slope-slope_lower,slope_upper-slope)
        height=centre_height
        if not all(math.isfinite(value) for value in (height, height_error, concentration,
                                                       concentration_error, slope, slope_error,
                                                       height_lower,height_upper,slope_lower,slope_upper)):
            raise ForcedDryingError('nonfinite derived event probe')
        row = {'time_years':t, 'status':'PASS', 'height_m':height,
               'height_lower_m':height_lower, 'height_upper_m':height_upper,
               'height_error_estimate_m':height_error, 'concentration':concentration,
               'concentration_error_estimate':concentration_error,
               'depth_rate_m_year':slope, 'depth_rate_error_estimate_m_year':slope_error,
               'concentration_lower':concentration_low,
               'concentration_upper':concentration_high,
               'depth_rate_lower_m_year':slope_lower,
               'depth_rate_upper_m_year':slope_upper,
               'interval_semantics':'HEURISTIC_NOT_VALIDATED_ENCLOSURE',
               'scalar_result':result}
        probes.append(row)
        check_resources()
        return row

    def finish(result):
        nonlocal source_rechecks
        final_identity,_=_source_snapshot(implementation_bytes)
        source_rechecks+=1
        result['scalar_calls'] = scalar_calls
        result['scalar_rhs_evaluations'] = scalar_evaluations
        result['source_rechecks'] = source_rechecks
        result['source_identity_final'] = final_identity
        result['probes'] = probes
        result['resource_bounds'] = {'native_cell_count_enforced':native_cell_count,
            'maximum_native_cells':MAX_NATIVE_CELLS,
            'scalar_calls':max_scalar_calls, 'scalar_evaluations':max_scalar_evaluations,
            'minimum_bisections':MAX_BISECTIONS, 'root_bisections':MAX_BISECTIONS,
            'wall_seconds':wall}
        result['wall_seconds'] = time.monotonic()-started
        result['numerical_event_evidence'] = 'ESTIMATED_NOT_VALIDATED_ENCLOSURE'
        if 'minimum_certificate' in result:
            result['minimum_estimate']=result.pop('minimum_certificate')
        result['independent_no_drying_certificate'] = analytic_bound
        return result

    def no_event(reason, minimum):
        proved=analytic_bound['status']=='PROVED_POSITIVE_DEPTH'
        return finish({**base, 'status':'NO_DRYING_CERTIFIED' if proved else 'NO_DRYING_ESTIMATED', 'reason':reason,
                       'minimum_certificate':minimum, 'remaining_years':duration,
                       'physical_acceptance':False, 'production_authorised':False,
                       'daughter_geometry_solved':False, 'remaining_interval_completed':proved})

    def blocked(status, reason, **extra):
        return finish(_blocked(base,status,reason,**extra))

    zero = probe(0.0)
    if zero['status'] != 'PASS':
        return blocked('BLOCKED_PHASE_DEPLETION','initial checkpoint is outside scalar phase domain')
    if duration == 0:
        return no_event('zero requested interval',zero)

    def crossed(low, high):
        if low['status'] != high['status'] or low['status'] != 'PASS':
            return blocked('BLOCKED_PHASE_DEPLETION','phase-domain failure prevents a drying bracket',
                           depletion_bracket={'low':low,'high':high})
        if low['height_lower_m'] <= 0 or high['height_upper_m'] > 0:
            return blocked('BLOCKED_NUMERICAL_EVENT_SIGN','event endpoints lack separated sign bands',
                           unresolved_bracket={'low':low,'high':high})
        tolerance = base['event_time_tolerance_years']
        bisections = 0
        while high['time_years']-low['time_years'] > tolerance:
            if bisections >= MAX_BISECTIONS:
                return blocked('BLOCKED_UNREPRESENTABLE_EVENT','first-root bisection cap exhausted',
                               unresolved_bracket={'low':low,'high':high})
            mid_time=(low['time_years']+high['time_years'])/2
            if mid_time in (low['time_years'],high['time_years']):
                return blocked('BLOCKED_UNREPRESENTABLE_EVENT','first-root time cannot advance in binary64',
                               unresolved_bracket={'low':low,'high':high})
            mid=probe(mid_time);bisections+=1
            if mid['status']!='PASS':
                return blocked('BLOCKED_PHASE_DEPLETION','phase-domain failure entered first-root bracket',
                               depletion_bracket={'low':low,'high':mid})
            if mid['height_lower_m'] > 0:low=mid
            elif mid['height_upper_m'] <= 0:high=mid
            else:
                # A probe centred exactly on the root may straddle zero even
                # though the outer bracket is sound.  Probe a target-width
                # neighbourhood and accept it only when both signs separate.
                if bisections+2 > MAX_BISECTIONS:
                    return blocked('BLOCKED_NUMERICAL_EVENT_SIGN','solver sign band cannot be separated within root cap',
                                   unresolved_bracket={'low':low,'probe':mid,'high':high})
                radius=.49*tolerance
                left_time=max(low['time_years'],mid_time-radius)
                right_time=min(high['time_years'],mid_time+radius)
                if left_time in (low['time_years'],mid_time) or right_time in (mid_time,high['time_years']):
                    return blocked('BLOCKED_UNREPRESENTABLE_EVENT','root-side probe cannot advance in binary64',
                                   unresolved_bracket={'low':low,'probe':mid,'high':high})
                left,right=probe(left_time),probe(right_time);bisections+=2
                if left['status']!='PASS' or right['status']!='PASS':
                    return blocked('BLOCKED_PHASE_DEPLETION','phase domain fails around unresolved root probe',
                                   depletion_bracket={'left':left,'probe':mid,'right':right})
                if left['height_lower_m'] > 0 and right['height_upper_m'] <= 0:
                    low,high=left,right
                else:
                    return blocked('BLOCKED_NUMERICAL_EVENT_SIGN','both root-side sign bands remain unresolved',
                                   unresolved_bracket={'left':left,'probe':mid,'right':right})
        overshoot=max(0.,-high['height_m'])
        if overshoot > base['height_tolerance_m']:
            return blocked('BLOCKED_UNREPRESENTABLE_EVENT','accepted high endpoint exceeds geometry overshoot band',
                           unresolved_bracket={'low':low,'high':high},overshoot_m=overshoot)
        remaining=duration-high['time_years']
        continuing=any(value != 0 for value in post.values()) and remaining > 0
        continuation=('BLOCKED_FORCED_DAUGHTER_COUPLING' if continuing else
                      'NO_REMAINING_INTERVAL' if remaining == 0 else
                      'CLOSED_DAUGHTER_SETTLING_AVAILABLE_NOT_EXECUTED')
        absolute_low=absolute_start+low['time_years']
        absolute_high=absolute_start+high['time_years']
        if (absolute_low <= absolute_start or absolute_high <= absolute_start
                or absolute_high <= absolute_low):
            return blocked('BLOCKED_UNREPRESENTABLE_EVENT',
                           'event bracket does not advance absolute binary64 time',
                           unresolved_bracket={'low':low,'high':high},
                           absolute_low_years=absolute_low,absolute_high_years=absolute_high)
        return finish({**base,'status':'FIRST_DRYING_ESTIMATED','reason':'first descending root estimated, not a validated enclosure',
            'event':{'low':low,'high':high,'width_years':high['time_years']-low['time_years'],
                     'absolute_low_years':absolute_low,
                     'absolute_high_years':absolute_high,
                     'overshoot_m':overshoot,'bisections':bisections,
                     'simultaneous_cell_indices':indices},
            'remaining_years':remaining,'remaining_interval_status':continuation,
            'physical_acceptance':False,'production_authorised':False,
            'daughter_geometry_solved':False,'remaining_interval_completed':False})

    endpoint = probe(duration)
    if endpoint['status']=='PASS' and analytic_bound['status']=='PROVED_POSITIVE_DEPTH':
        return no_event('independent exact invariant proves positive depth for the whole interval',
                        {'initial':zero,'final':endpoint})
    if endpoint['status'] != 'PASS':
        if not endpoint.get('failed_rhs_evaluations_counted',False):
            return blocked('BLOCKED_PHASE_DEPLETION',
                           'scalar phase failure has no accountable RHS-work count; no further probes allowed',
                           depletion_bracket={'last_valid':zero,'first_failed':endpoint})
        low, failed = zero, endpoint
        for _ in range(MAX_BISECTIONS):
            mid_time=(low['time_years']+failed['time_years'])/2
            if mid_time in (low['time_years'],failed['time_years']):
                break
            mid=probe(mid_time)
            if mid['status']!='PASS':
                if not mid.get('failed_rhs_evaluations_counted',False):
                    return blocked('BLOCKED_PHASE_DEPLETION',
                                   'scalar phase failure has no accountable RHS-work count; no further probes allowed',
                                   depletion_bracket={'last_valid':low,'first_failed':mid})
                failed=mid
            elif mid['height_upper_m'] <= 0:return crossed(zero,mid)
            else:low=mid
        return blocked('BLOCKED_PHASE_DEPLETION','scalar phase domain ends before a certified drying state',
                       depletion_bracket={'last_valid':low,'first_failed':failed})

    if velocity == 0 or branch in ('INCREASING_CONCENTRATION','CONSTANT_CONCENTRATION'):
        if endpoint['height_lower_m'] > 0:
            reason = ('affine endpoint minimum is positive' if velocity == 0 or branch == 'CONSTANT_CONCENTRATION'
                      else 'concave depth has positive endpoint minima')
            return no_event(reason,{'initial':zero,'final':endpoint})
        if endpoint['height_upper_m'] <= 0:
            return crossed(zero,endpoint)
        return blocked('BLOCKED_NUMERICAL_EVENT_SIGN','endpoint height error band straddles zero',
                       unresolved_bracket={'low':zero,'high':endpoint})

    slope0 = eta_rate_fraction-Fraction(velocity)*c0_fraction
    if slope0 >= 0:
        return no_event('convex depth is nondecreasing from its initial minimum',zero)
    slope_end_low=endpoint['depth_rate_lower_m_year']
    slope_end_high=endpoint['depth_rate_upper_m_year']
    if slope_end_high <= 0:
        if endpoint['height_lower_m'] > 0:
            return no_event('convex depth decreases to a positive endpoint minimum',endpoint)
        if endpoint['height_upper_m'] <= 0:
            return crossed(zero,endpoint)
        return blocked('BLOCKED_NUMERICAL_EVENT_SIGN','endpoint minimum height band straddles zero',
                       unresolved_bracket={'low':zero,'high':endpoint})
    if slope_end_low <= 0:
        return blocked('BLOCKED_NUMERICAL_EVENT_SIGN',
                       'endpoint derivative band straddles zero before convex-minimum search',
                       minimum_certificate={'initial':zero,'final':endpoint})

    low, high = zero, endpoint
    for _ in range(MAX_BISECTIONS):
        mid_time=(low['time_years']+high['time_years'])/2
        if mid_time in (low['time_years'],high['time_years']):break
        mid=probe(mid_time)
        if mid['status']!='PASS':
            return blocked('BLOCKED_PHASE_DEPLETION','phase domain fails while locating convex minimum',
                           depletion_bracket={'last_valid':low,'first_failed':mid})
        lo=mid['depth_rate_lower_m_year']
        hi=mid['depth_rate_upper_m_year']
        if mid['height_upper_m'] < 0:
            return crossed(zero,mid)
        if hi < 0:low=mid
        elif lo > 0:high=mid
        else:
            conservative_exact=(Fraction(min(low['height_lower_m'],high['height_lower_m']))
                -(abs(eta_rate_fraction)+Fraction(velocity))
                 *Fraction(high['time_years']-low['time_years']))
            _, conservative, _=_fraction_interval(conservative_exact)
            minimum={'low':low,'probe':mid,'high':high,'conservative_height_lower_m':conservative}
            if conservative > 0:
                return no_event('convex interior minimum has a positive conservative lower bound',minimum)
            if (mid['height_m'] == 0 and mid['height_error_estimate_m'] == 0
                    and mid['depth_rate_m_year'] == 0):
                return blocked('BLOCKED_GRAZING_TANGENT','interior minimum touches zero without a descending crossing',
                               minimum_certificate=minimum)
            return blocked('BLOCKED_NUMERICAL_EVENT_SIGN',
                           'convex-minimum derivative band straddles zero',minimum_certificate=minimum)
    minimum_probe=min((low,high),key=lambda row:row['height_m'])
    if minimum_probe['height_upper_m'] < 0:
        return crossed(zero,minimum_probe)
    slope_lipschitz=abs(eta_rate_fraction)+Fraction(velocity)
    minimum_lower_exact=(Fraction(min(low['height_lower_m'],high['height_lower_m']))
        -slope_lipschitz*Fraction(high['time_years']-low['time_years']))
    _, minimum_lower, _=_fraction_interval(minimum_lower_exact)
    minimum={'low':low,'high':high,'conservative_height_lower_m':minimum_lower}
    if minimum_lower > 0:
        return no_event('convex interior minimum has a positive conservative lower bound',minimum)
    if (minimum_probe['height_m'] == 0 and minimum_probe['height_error_estimate_m'] == 0
            and low['depth_rate_m_year'] <= 0 <= high['depth_rate_m_year']):
        return blocked('BLOCKED_GRAZING_TANGENT','interior minimum touches zero without a descending crossing',
                       minimum_certificate=minimum)
    return blocked('BLOCKED_NUMERICAL_EVENT_SIGN','convex minimum cannot be separated from zero',
                   minimum_certificate=minimum)
