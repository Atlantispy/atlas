"""Read-only numerical verification, not workflow adoption or physical approval.

One prepared b/B/W/S snapshot is used for every requested timestep. Soil is
prepared once in verify_near_flat; a separate retained R2 rejection check has
its own historical prefix. No files are written. Error floors are frozen R3
geometry/volume bands, not fitted convergence thresholds. Apparent orders use
the explicitly identified finest numerical run, not an analytical truth.
"""
from copy import deepcopy
import hashlib
from fractions import Fraction
import math
from pathlib import Path
import time

import shoreline_driver as driver
import shoreline_fixtures
from r4_io import io, verify_dependencies

HERE = Path(__file__).resolve().parent
DEFAULT_DTS = (.1, .05, .025, .0125, .00625)
EXTRA_FINER_DT = .003125
MINIMUM_ORDER = .8
MAX_VERIFICATION_CELLS = 64
MAX_CASES = 6
MAX_WALL_SECONDS = 600.
FIELDS = {'b':('bedrock_m', 'm'), 'B':('bed_solid_m3', 'm3'),
          'W':('liquid_m3', 'm3'), 'S':('suspended_solid_m3', 'm3')}


class VerificationError(ValueError):
    pass


def canonical(value):
    return io.canonical(value)


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def source_snapshot():
    rows = []
    for path in sorted(HERE.iterdir()):
        if path.suffix in {'.py', '.json', '.md', '.ps1'}:
            raw = io.read_bytes(path)
            rows.append({'name':path.name, 'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()})
    return rows+verify_dependencies()


LOADED_SOURCE_PINS = source_snapshot()


def number(value, label, *, positive=False):
    if type(value) not in (int, float):
        raise VerificationError(label+': finite real required')
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise VerificationError(label+': unrepresentable number') from exc
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise VerificationError(label+': outside finite nonnegative range')
    return value


def finite_values(values, label):
    if type(values) not in (list, tuple) or not values:
        raise VerificationError(label+': nonempty sequence required')
    result = []
    for value in values:
        if type(value) not in (int, float):
            raise VerificationError(label+': finite numeric entries required')
        try:value = float(value)
        except (OverflowError, ValueError) as exc:raise VerificationError(label+': number overflow') from exc
        if not math.isfinite(value):raise VerificationError(label+': nonfinite entry')
        result.append(value)
    return result


def signed_number(value,label):
    if type(value) not in (int,float):raise VerificationError(label+': finite real required')
    try:value=float(value)
    except (ValueError,OverflowError) as exc:raise VerificationError(label+': overflow') from exc
    if not math.isfinite(value):raise VerificationError(label+': nonfinite')
    return value


def error_metrics(reference, actual):
    """Unweighted native-cell errors; RMS is not an area-weighted statistic."""
    expected, observed = finite_values(reference, 'reference'), finite_values(actual, 'actual')
    if len(expected) != len(observed):raise VerificationError('field lengths differ')
    differences = [a-b for a,b in zip(observed, expected)]
    if any(not math.isfinite(v) for v in differences):raise VerificationError('field difference overflow')
    maximum = max(abs(v) for v in differences)
    rms = 0. if maximum == 0 else maximum*math.sqrt(math.fsum((v/maximum)**2 for v in differences)/len(differences))
    return {'count':len(differences), 'max_abs':maximum, 'rms':rms,
            'bias':math.fsum(v/len(differences) for v in differences)}


def observed_orders(dts, errors, floors, *, minimum=MINIMUM_ORDER):
    """No invented order for zero/noise-floor errors; failures remain visible."""
    hs = [number(v, 'dt', positive=True) for v in dts]
    es = [number(v, 'error') for v in errors]
    fs = [number(v, 'floor') for v in floors]
    minimum = number(minimum, 'minimum order', positive=True)
    if not len(hs) == len(es) == len(fs) or len(hs) < 2 or any(a <= b for a,b in zip(hs, hs[1:])):
        raise VerificationError('matching strictly refined timestep/error/floor sequences required')
    rows = []
    for i in range(len(hs)-1):
        if es[i] <= fs[i] or es[i+1] <= fs[i+1]:
            rows.append({'coarse_dt':hs[i], 'fine_dt':hs[i+1], 'order':None,
                         'status':'BELOW_DECLARED_NUMERICAL_FLOOR'})
        else:
            order = (math.log(es[i])-math.log(es[i+1]))/(math.log(hs[i])-math.log(hs[i+1]))
            rows.append({'coarse_dt':hs[i], 'fine_dt':hs[i+1], 'order':order,
                         'status':'PASS' if order >= minimum else 'FAIL'})
    usable = [row for row in rows if row['order'] is not None]
    all_below = all(e <= f for e,f in zip(es,fs))
    status = ('FAIL' if any(row['status'] == 'FAIL' for row in usable) else
              'PASS' if len(usable) >= 2 else 'CONSISTENT_AT_NUMERICAL_FLOOR' if all_below else 'INCOMPLETE')
    return {'status':status, 'pairs':rows, 'minimum_order':minimum,
            'usable_orders':len(usable), 'convergence_order_demonstrated':status == 'PASS',
            'resolution_or_order_check_passed':status in ('PASS','CONSISTENT_AT_NUMERICAL_FLOOR')}


def compare_refinement(cases):
    if len(cases) < 3:raise VerificationError('at least three numerical runs required')
    if any(row.get('status') != 'PASS' for row in cases):
        return {'status':'FAIL', 'reason':'A requested integration failed; no successful-run substitution.',
                'fields':{}, 'numerical_reference_dt':cases[-1]['dt_years']}
    reference = cases[-1]['final_state']
    dts = [row['dt_years'] for row in cases[:-1]]
    fields = {}
    for symbol,(key,unit) in FIELDS.items():
        rows = []
        for case in cases[:-1]:
            stats = error_metrics(reference[key], case['final_state'][key])
            scale = max(abs(v) for v in [*reference[key], *case['final_state'][key]])
            floor = 1e-9+(1e-11 if symbol == 'b' else 1e-12)*scale
            rows.append({'dt_years':case['dt_years'], **stats, 'numerical_floor':floor})
        orders = {metric:observed_orders(dts, [row[metric] for row in rows],
                                         [row['numerical_floor'] for row in rows])
                  for metric in ('max_abs','rms')}
        fields[symbol] = {'source_field':key, 'unit':unit, 'errors':rows, 'orders':orders}
    all_orders = [row for field in fields.values() for row in field['orders'].values()]
    status = 'FAIL' if any(row['status'] == 'FAIL' for row in all_orders) else (
        'PASS' if all(row['resolution_or_order_check_passed'] for row in all_orders) else 'INCOMPLETE')
    return {'status':status, 'numerical_reference_dt':cases[-1]['dt_years'],
            'reference_kind':'FINER_NUMERICAL_SOLUTION_NOT_INDEPENDENT_TRUTH',
            'orders_are_finite_reference_biased':True, 'fields':fields}


def compare_recipients(cases, initial_time, duration):
    """Compare left-limit identities at common coarse-grid physical times.

Samples inside either recorded event bracket are explicitly unresolved, not
counted as an identity match. Exact pool/native recipient identities otherwise
must match the finest run. This is not a whole-trajectory error estimator.
"""
    if any(case.get('status') != 'PASS' for case in cases):
        return {'status':'FAIL','reason':'Failed integrations have no complete recipient history.','samples':[]}
    coarse = cases[0]['dt_years'];count = round(duration/coarse)
    if count*coarse != duration:raise VerificationError('common recipient sampling grid does not cover duration')
    def within(case, at):
        return any(event['kind'] == 'BRACKETED_NATIVE_CONTACT' and event['lower_years'] <= at <= event['upper_years']
                   for event in case['events'])
    def identity(case, at):
        hits = [row for row in case['recipient_intervals'] if row['from_years'] < at <= row['to_years']]
        if len(hits) != 1:raise VerificationError('recipient timeline gap or overlap at common sample')
        return {key:hits[0][key] for key in ('destinations','destination_cell_indices','pools','pool_cells','ports')}
    records = []
    for case in cases[:-1]:
        for index in range(1,count+1):
            at = initial_time+index*coarse
            if within(case,at) or within(cases[-1],at):
                records.append({'dt_years':case['dt_years'],'time_years':at,'status':'EVENT_BRACKET_UNRESOLVED'})
                continue
            a,b = identity(case,at),identity(cases[-1],at)
            records.append({'dt_years':case['dt_years'],'time_years':at,
                            'status':'PASS' if canonical(a) == canonical(b) else 'FAIL',
                            'coarse_identity':a,'reference_identity':b})
    usable = [row for row in records if row['status'] != 'EVENT_BRACKET_UNRESOLVED']
    return {'status':'FAIL' if any(row['status'] == 'FAIL' for row in records) else 'PASS' if usable else 'INCOMPLETE',
            'samples':records,'sampling':'LEFT_LIMIT_COMMON_COARSE_PHYSICAL_TIMES',
            'event_bracket_samples_do_not_count_as_matches':True}


def _exact_state(first, second):
    return canonical(first) == canonical(second)


def _failure(exc):
    context = getattr(exc, 'context', None)
    try:canonical(context)
    except (TypeError,ValueError,OverflowError):context = repr(context)
    return {'type':type(exc).__name__, 'message':str(exc), 'context':context}


def retained_rejection(recipe):
    """Separate frozen R2 run; a rejection supplies no final terrain baseline."""
    before = canonical(recipe)
    expected = 'channel timestep consumes relative link relief excessively; reduce dt'
    try:
        io.execute(deepcopy(recipe))
    except Exception as exc:
        matched = type(exc) is ValueError and str(exc) == expected
        return {'status':'PASS_RETAINED_REJECTION' if matched else 'FAIL',
                'error':_failure(exc), 'recipe_sha256':hashlib.sha256(before).hexdigest(),
                'recipe_unchanged':canonical(recipe) == before, 'valid_final_terrain_exists':False,
                'new_speedup_baseline':False}
    return {'status':'FAIL', 'reason':'Frozen R2 rejection unexpectedly succeeded.',
            'recipe_sha256':hashlib.sha256(before).hexdigest(), 'new_speedup_baseline':False}


def _arguments(prepared, dt, duration):
    ratio = duration/dt
    if not math.isfinite(ratio):raise VerificationError('step count overflow')
    steps = round(ratio)
    if not 1 <= steps <= 4096 or steps*dt != duration:
        raise VerificationError('requested interval must comprise exact represented outer steps')
    forcing = prepared['forcing'];grid = prepared['grid']
    required = {'external_outlets','runoff_m_year','sediment_k_per_year','rock_k_per_year',
                'cover_scale_m','settling_m_year','diffusivity_m2_year'}
    allowed = required|{'kind','steps','dt_years','incoming_liquid_m3_year','incoming_solid_m3_year'}
    if type(forcing) is not dict or not required <= set(forcing) or set(forcing)-allowed:
        raise VerificationError('prepared forcing inventory differs from retained coupled interface')
    if 'kind' in forcing and forcing['kind'] != 'coupled':
        raise VerificationError('prepared operation is not coupled')
    if (type(grid) is not dict or set(grid) != {'rows','cols','dx_m','dy_m'}
            or grid['rows'] != prepared['initial_state'].shape[0]
            or grid['cols'] != prepared['initial_state'].shape[1]):
        raise VerificationError('prepared grid/state binding differs')
    return {key:deepcopy(forcing[key]) for key in ('external_outlets','runoff_m_year','sediment_k_per_year',
                'rock_k_per_year','cover_scale_m','settling_m_year','diffusivity_m2_year')} | {
        'steps':steps, 'dt_years':dt, 'dx_m':grid['dx_m'], 'dy_m':grid['dy_m'],
        'basin_settling_m_year':prepared['basin_settling_m_year'], 'connectivity':8,
        **{key:deepcopy(forcing[key]) for key in ('incoming_liquid_m3_year','incoming_solid_m3_year') if key in forcing}}


def _ledger(residual, scale, *, rock=False, representation=0.):
    if type(residual) not in (int,float) or not math.isfinite(residual):
        raise VerificationError('ledger residual is not a finite real')
    scale=number(scale,'ledger scale');representation=number(representation,'representation bound')
    tolerance = (1e-6 if rock else 1e-9)+(1e-11 if rock else 1e-12)*scale+representation
    if not math.isfinite(tolerance) or abs(residual) > tolerance:
        raise VerificationError('independent whole-interval ledger exceeds frozen tolerance')
    return {'residual':residual, 'tolerance':tolerance, 'representation_bound':representation}


def representation_summary(rows):
    records=[];liquid=[];solid=[];bounds=[];liquid_bounds=[];solid_bounds=[]
    for step,row in enumerate(rows):
        evidence=row.get('phase_representation')
        if type(evidence) is not dict or evidence.get('physical_transfer') is not False:
            raise VerificationError('phase representation evidence missing or mislabelled')
        if set(evidence) != {'records','liquid_adjustment_m3','suspended_solid_adjustment_m3',
                             'liquid_adjustment_bound_m3','suspended_solid_adjustment_bound_m3',
                             'arithmetic_bound_m3','physical_transfer'}:
            raise VerificationError('phase representation evidence inventory changed')
        for record in evidence['records']:
            if (record.get('physical_transfer') is not False or record.get('exact_capacity_matched') is not True
                    or type(record.get('exact_adjustment')) is not dict):
                raise VerificationError('full-sill representation record is not an arithmetic certificate')
            liquid_adjustment=signed_number(record['adjustment_liquid_m3'],'liquid representation adjustment')
            solid_adjustment=signed_number(record['adjustment_suspended_solid_m3'],'solid representation adjustment')
            a,b=abs(liquid_adjustment),abs(solid_adjustment)
            bound=number(record['arithmetic_bound_m3'],'phase arithmetic bound')
            liquid_bound=number(record.get('adjustment_liquid_bound_m3',0.),'liquid adjustment bound')
            solid_bound=number(record.get('adjustment_suspended_solid_bound_m3',0.),'solid adjustment bound')
            if abs(liquid_adjustment+solid_adjustment) > bound or a > liquid_bound or b > solid_bound:
                raise VerificationError('phase adjustment exceeds its arithmetic certificate')
            exact=record['exact_adjustment']
            if set(exact) != {'numerator','denominator'} or type(exact['numerator']) is not int or type(exact['denominator']) is not int or exact['denominator'] <= 0:
                raise VerificationError('exact phase adjustment rational is invalid')
            cell_changes={'liquid':Fraction(),'suspended_solid':Fraction()}
            for cell in record.get('cell_adjustments',[]):
                if set(cell) != {'phase','cell_offset','before_m3','after_m3','adjustment_m3'} or cell['phase'] not in cell_changes:
                    raise VerificationError('phase cell-adjustment record is invalid')
                difference=Fraction(cell['after_m3'])-Fraction(cell['before_m3'])
                if difference != Fraction(cell['adjustment_m3']):raise VerificationError('cell adjustment does not match before/after')
                cell_changes[cell['phase']] += difference
            if (float(cell_changes['liquid']) != liquid_adjustment
                    or float(cell_changes['suspended_solid']) != solid_adjustment
                    or sum(cell_changes.values(),Fraction()) != Fraction(exact['numerator'],exact['denominator'])):
                raise VerificationError('represented phase adjustments differ from exact/cell certificate')
            records.append({'accepted_step_index':step,**deepcopy(record)})
        liquid.append(signed_number(evidence['liquid_adjustment_m3'],'liquid representation aggregate'))
        solid.append(signed_number(evidence['suspended_solid_adjustment_m3'],'solid representation aggregate'))
        bounds.append(number(evidence['arithmetic_bound_m3'],'phase arithmetic aggregate'))
        liquid_bounds.extend(number(record.get('adjustment_liquid_bound_m3',0.),'liquid adjustment bound') for record in evidence['records'])
        solid_bounds.extend(number(record.get('adjustment_suspended_solid_bound_m3',0.),'solid adjustment bound') for record in evidence['records'])
        if (evidence['liquid_adjustment_m3'] != math.fsum(r['adjustment_liquid_m3'] for r in evidence['records'])
                or evidence['suspended_solid_adjustment_m3'] != math.fsum(r['adjustment_suspended_solid_m3'] for r in evidence['records'])
                or evidence['liquid_adjustment_bound_m3'] != math.fsum(r.get('adjustment_liquid_bound_m3',0.) for r in evidence['records'])
                or evidence['suspended_solid_adjustment_bound_m3'] != math.fsum(r.get('adjustment_suspended_solid_bound_m3',0.) for r in evidence['records'])
                or evidence['arithmetic_bound_m3'] != math.fsum(r['arithmetic_bound_m3'] for r in evidence['records'])):
            raise VerificationError('phase representation aggregate differs from raw records')
    return {'records':records,'liquid_adjustment_m3':math.fsum(liquid),
            'suspended_solid_adjustment_m3':math.fsum(solid),'arithmetic_bound_m3':math.fsum(bounds),
            'liquid_adjustment_bound_m3':math.fsum(liquid_bounds),
            'suspended_solid_adjustment_bound_m3':math.fsum(solid_bounds),
            'physical_transfer':False,'interpretation':'BINARY64_OUTPUT_REPRESENTATION_NOT_PHYSICAL_TRANSFER'}


def summarise_run(initial, final, report, arguments, dissolved):
    """Independently reconcile full interval; preserve event and port evidence."""
    if (report.get('whole_interval_completed') is not True or report.get('physical_acceptance') is not False
            or report.get('production_authorised') is not False):
        raise VerificationError('completion/authority flags are not strictly truthful')
    initial_dict, final_dict = initial.as_dict(), final.as_dict()
    for key in ('shape','cell_area_m2','solid_density_kg_m3','water_density_kg_m3','frame','vertical_datum','source_status'):
        if canonical(initial_dict[key]) != canonical(final_dict[key]):raise VerificationError('native state binding changed: '+key)
    duration = arguments['steps']*arguments['dt_years']
    if final.time_years != initial.time_years+duration:raise VerificationError('reported whole interval is incomplete')
    rows = report['steps'];counts = report['counts']
    if not rows or counts['accepted_substeps'] != len(rows):raise VerificationError('accepted-step evidence missing')
    for key in ('trial_calls','trial_cell_evaluations','scalar_rhs_evaluations','closed_event_solver_calls','accepted_substeps','rejected_proposals'):
        if type(counts[key]) is not int or counts[key] < 0:raise VerificationError('invalid measured work count')
    if counts['trial_calls'] < 2*len(rows):raise VerificationError('stable recomputations not counted')
    cursor = initial.time_years
    recipients, scalar_minimum, closed_minimum = [], 0, 0
    for row in rows:
        if row['from_time_years'] != cursor or row['to_time_years'] <= cursor:
            raise VerificationError('accepted interval sequence has a gap or overlap')
        cursor = row['to_time_years']
        if row['stable_recomputations'] != 2:raise VerificationError('stable trial recomputation missing')
        if row['post_pool_relief']['status'] != 'PASS' or row['post_pool_relief']['maximum_fraction'] > .20:
            raise VerificationError('original dry-link relief failed')
        for ledger in row['ledgers'].values():
            residual = ledger['residual_m3'];tol = number(ledger['tolerance_m3'], 'step ledger tolerance')
            if not math.isfinite(residual) or abs(residual) > tol:raise VerificationError('step ledger failed')
        scalar_values=[pool['continuous_phases']['evaluations'] for pool in row['pool_intervals']]
        closed_values=[pool.get('closed_event_settling',{}).get('solver_calls',0) for pool in row['pool_intervals']]
        if any(type(value) is not int or value < 0 for value in (*scalar_values,*closed_values)):
            raise VerificationError('pool scalar/event work count is invalid')
        scalar_minimum += 2*sum(scalar_values);closed_minimum += 2*sum(closed_values)
        network = row['network']
        recipients.append({'from_years':row['from_time_years'], 'to_years':row['to_time_years'],
                           'destinations':deepcopy(network['destinations']),
                           'destination_cell_indices':list(network['destination_cell_indices']),
                           'pools':[{'id':pool['id'],'cell_indices':list(pool['cell_indices'])}
                                    for pool in network['pools']],
                           'pool_cells':sorted([list(pool['cell_indices']) for pool in network['pools']]),
                           'ports':[{'source_cell':port['source_cell'], 'recipient_cell':port['recipient_cell'],
                                     'pool_id':port['pool_id']} for port in row['channel']['pool_ports']]})
    if (cursor != final.time_years or counts['scalar_rhs_evaluations'] < scalar_minimum
            or counts['closed_event_solver_calls'] < closed_minimum):
        raise VerificationError('final interval or scalar work accounting missing')
    for event in report['events']:
        if event['kind'] == 'BRACKETED_NATIVE_CONTACT':
            lo, hi, width = (number(event[key],key) for key in ('lower_years','upper_years','width_years'))
            if (not initial.time_years <= lo <= hi <= final.time_years
                    or width < 0 or width > 1e-10+1e-11*arguments['dt_years']
                    or abs((hi-lo)-width) > 2*math.ulp(max(abs(lo),abs(hi)))):
                raise VerificationError('event bracket exceeds preregistered bounds')
            for contact in event['contacts']:
                old=number(contact['old_freeboard_m'],'old freeboard',positive=True)
                new=contact['new_freeboard_m']
                if type(new) not in (int,float) or not math.isfinite(new) or old <= 0 or new > 0:
                    raise VerificationError('event is not a crossed bracket endpoint')
                overshoot=number(contact['overshoot_m'],'event overshoot');stage=contact['stage_m']
                if type(stage) not in (int,float) or not math.isfinite(stage):raise VerificationError('event stage nonfinite')
                if overshoot > 1e-9+1e-11*abs(stage):
                    raise VerificationError('event height overshoot exceeds frozen geometry band')
    area = initial.cell_area_m2;density = initial.solid_density_kg_m3
    representation=representation_summary(rows)
    imported_w = math.fsum((r*a+q)*duration for r,a,q in zip(arguments['runoff_m_year'], area,
                           arguments.get('incoming_liquid_m3_year',[0.]*initial.size)))
    imported_s = math.fsum(q*duration for q in arguments.get('incoming_solid_m3_year',[0.]*initial.size))
    exported_w = math.fsum(row['exported_liquid_m3'] for row in rows)
    exported_s = math.fsum(row['exported_solid_m3'] for row in rows)
    rock = math.fsum((a-b)*v for a,b,v in zip(initial.bedrock_m,final.bedrock_m,area))
    rate_rock = math.fsum(row['channel']['rate_rock_loss_solid_m3'] for row in rows)
    roundoff = math.fsum(row['channel']['height_subtraction_roundoff_bound_m3'] for row in rows)
    water_residual = math.fsum([*final.liquid_m3,*(-v for v in initial.liquid_m3),exported_w,-imported_w])
    solid_residual = math.fsum([*final.bed_solid_m3,*final.suspended_solid_m3,
                              *(-v for v in initial.bed_solid_m3),*(-v for v in initial.suspended_solid_m3),
                              exported_s,-imported_s,-rock])
    scale_w = max(imported_w,exported_w,math.fsum(initial.liquid_m3),math.fsum(final.liquid_m3))
    scale_s = max(imported_s,exported_s,abs(rock),math.fsum(initial.bed_solid_m3),math.fsum(final.bed_solid_m3),
                  math.fsum(initial.suspended_solid_m3),math.fsum(final.suspended_solid_m3))
    totals = {'initial_liquid_m3':math.fsum(initial.liquid_m3), 'final_liquid_m3':math.fsum(final.liquid_m3),
              'initial_bed_solid_m3':math.fsum(initial.bed_solid_m3), 'final_bed_solid_m3':math.fsum(final.bed_solid_m3),
              'initial_suspended_m3':math.fsum(initial.suspended_solid_m3), 'final_suspended_m3':math.fsum(final.suspended_solid_m3),
              'imported_liquid_m3':imported_w, 'exported_liquid_m3':exported_w,
              'imported_solid_m3':imported_s, 'exported_solid_m3':exported_s,
              'geometric_rock_debit_m3':rock, 'rate_rock_debit_m3':rate_rock,
              'geometric_rock_debit_kg':rock*density, 'soil_dissolved_export_kg':dissolved,
              'solid_density_kg_m3':density, 'water_density_kg_m3':initial.water_density_kg_m3,
              'final_liquid_mass_kg':math.fsum(final.liquid_m3)*initial.water_density_kg_m3,
              'final_mobile_plus_suspended_kg':math.fsum([*final.bed_solid_m3,*final.suspended_solid_m3])*density}
    ledgers = {'liquid_m3':_ledger(water_residual,scale_w),
               'solid_m3':_ledger(solid_residual,scale_s,representation=roundoff),
               'rock_derived_kg':_ledger(solid_residual*density,scale_s*density,rock=True,representation=roundoff*density),
               'geometric_vs_rate_rock_m3':_ledger(rock-rate_rock,max(abs(rock),rate_rock),representation=roundoff)}
    ledgers['liquid_m3']['representation_explained_residual'] = water_residual-representation['liquid_adjustment_m3']
    ledgers['liquid_m3']['explained_check'] = _ledger(ledgers['liquid_m3']['representation_explained_residual'],scale_w)
    ledgers['solid_m3']['representation_explained_residual'] = solid_residual-representation['suspended_solid_adjustment_m3']
    ledgers['solid_m3']['explained_check'] = _ledger(ledgers['solid_m3']['representation_explained_residual'],scale_s,representation=roundoff)
    ledgers['rock_derived_kg']['representation_explained_residual'] = ((solid_residual-
        representation['suspended_solid_adjustment_m3'])*density)
    ledgers['rock_derived_kg']['explained_check'] = _ledger(ledgers['rock_derived_kg']['representation_explained_residual'],
                                                           scale_s*density,rock=True,representation=roundoff*density)
    canonical(totals);canonical(ledgers)
    return {'totals':totals, 'ledgers':ledgers, 'phase_representation':representation,
            'events':deepcopy(report['events']),
            'recipient_intervals':recipients, 'counts':deepcopy(counts),
            'driver_report_sha256':digest(report), 'whole_interval_completed':True,
            'maximum_old_link_relief_fraction':max(row['post_pool_relief']['maximum_fraction'] for row in rows)}


def _run(initial, prepared, dt, duration, source_pins, deadline):
    started = time.perf_counter();before = canonical(initial.as_dict())
    args = _arguments(prepared,dt,duration)
    row = {'dt_years':dt, 'requested_duration_years':duration, 'steps':args['steps'],
           'prepared_state_sha256':hashlib.sha256(before).hexdigest()}
    try:
        if source_snapshot() != source_pins:raise VerificationError('source drift before integration')
        remaining = deadline-time.monotonic()
        if remaining <= 0:raise VerificationError('whole verification wall envelope exhausted')
        final, report = driver.advance(driver.capture.CaptureState(**io.parse_json(before)), **args,
                                       wall_seconds=min(120.,remaining))
        summary = summarise_run(initial,final,report,args,prepared.get('soil_dissolved_rock_export_kg',0.))
        if 'original_recipe' in prepared:
            prior = prepared['original_recipe']['initial'];rho = initial.solid_density_kg_m3
            rock = math.fsum((a-b)*v for a,b,v in zip(prior['bedrock_m'],final.bedrock_m,initial.cell_area_m2))
            dissolved = prepared['soil_dissolved_rock_export_kg']
            terms = [*(v*rho for v in final.bed_solid_m3),*(v*rho for v in final.suspended_solid_m3),
                     *(-v*rho for v in prior['mobile_solid_m3']),
                     summary['totals']['exported_solid_m3']*rho,-summary['totals']['imported_solid_m3']*rho,
                     dissolved,-rock*rho]
            residual = math.fsum(terms)
            roundoff = summary['ledgers']['solid_m3']['representation_bound']*rho+math.fsum(
                4*math.ulp(b)*a*rho for b,a in zip(prior['bedrock_m'],initial.cell_area_m2))
            combined = _ledger(residual,max(abs(v) for v in terms),rock=True,representation=roundoff)
            explained = residual-summary['phase_representation']['suspended_solid_adjustment_m3']*rho
            combined['representation_explained_residual'] = explained
            combined['explained_check'] = _ledger(explained,max(abs(v) for v in terms),
                                                  rock=True,representation=roundoff)
            summary['ledgers']['soil_plus_coupled_rock_derived_kg'] = combined
            summary['totals']['soil_plus_coupled_geometric_rock_debit_kg'] = rock*rho
        row.update(status='PASS',final_state=final.as_dict(),final_state_sha256=digest(final.as_dict()), **summary)
    except Exception as exc:
        context = getattr(exc,'context',{})
        row.update(status='FAIL',error=_failure(exc), counts=getattr(exc,'coupling_counts',
                   context.get('counts') if isinstance(context,dict) else None))
        row['failed_trial_time_years'] = getattr(exc,'coupling_time_years',None)
        row['failed_trial_duration_years'] = getattr(exc,'coupling_trial_years',None)
        last = getattr(exc,'last_valid_state',None)
        row['last_valid_state'] = last.as_dict() if isinstance(last,driver.capture.CaptureState) else last
    finally:
        row['driver_and_validation_wall_seconds'] = time.perf_counter()-started
        row['initial_state_unchanged'] = canonical(initial.as_dict()) == before
        try:
            row['sources_unchanged'] = source_snapshot() == source_pins
        except Exception as exc:
            row['sources_unchanged'] = False;row['source_recheck_error'] = _failure(exc)
        if not row['initial_state_unchanged'] or not row['sources_unchanged']:
            row['status'] = 'FAIL'
        if time.monotonic() > deadline:
            row['status'] = 'FAIL';row['verification_wall_bound_exceeded'] = True
    return row


def verify_prepared(prepared, *, dts=DEFAULT_DTS, repeat_dt=.025, extra_finer=False, wall_seconds=MAX_WALL_SECONDS):
    """No preparation or writes. Each attempt starts from the exact same bytes."""
    started = time.monotonic();wall = number(wall_seconds,'wall',positive=True)
    if wall > MAX_WALL_SECONDS:raise VerificationError('verification wall bound exceeded')
    hs = [number(v,'dt',positive=True) for v in dts]
    if not 3 <= len(hs) <= MAX_CASES or any(a <= b for a,b in zip(hs,hs[1:])):
        raise VerificationError('three to six strictly refined cases required')
    if type(prepared) is not dict:raise VerificationError('prepared fixture mapping required')
    initial = prepared['initial_state'];duration = number(prepared['coupled_duration_years'],'duration',positive=True)
    if not isinstance(initial,driver.capture.CaptureState) or initial.size > MAX_VERIFICATION_CELLS:
        raise VerificationError('bounded native verification state required')
    if prepared.get('physical_acceptance') is not False or prepared.get('production_authorised') is not False:
        raise VerificationError('prepared fixture cannot assert authority')
    if repeat_dt not in hs:raise VerificationError('repeat must use one requested timestep')
    dissolved = number(prepared.get('soil_dissolved_rock_export_kg',0.),'dissolved export')
    control_identity={'initial_state':initial.as_dict(),'grid':prepared['grid'],'forcing':prepared['forcing'],
                      'coupled_duration_years':duration,'basin_settling_m_year':prepared['basin_settling_m_year'],
                      'soil_dissolved_rock_export_kg':dissolved,'physical_acceptance':prepared['physical_acceptance'],
                      'production_authorised':prepared['production_authorised']}
    control_bytes=canonical(control_identity)
    pins = source_snapshot()
    if pins != LOADED_SOURCE_PINS:raise VerificationError('source files changed since import; use fresh frozen process')
    deadline = started+wall
    cases = [_run(initial,prepared,h,duration,pins,deadline) for h in hs]
    initial_refinement = compare_refinement(cases)
    if extra_finer:
        if len(cases) >= MAX_CASES:raise VerificationError('additional reference exceeds case cap')
        h = hs[-1]/2
        cases.append(_run(initial,prepared,h,duration,pins,deadline))
    refinement = compare_refinement(cases)
    recipient_stability = compare_recipients(cases,initial.time_years,duration)
    base = next(row for row in cases if row['dt_years'] == repeat_dt)
    repeated = _run(initial,prepared,repeat_dt,duration,pins,deadline)
    repeat_ok = (base['status'] == repeated['status'] == 'PASS'
                 and _exact_state(base['final_state'],repeated['final_state'])
                 and base['driver_report_sha256'] == repeated['driver_report_sha256'])
    first = _run(initial,prepared,repeat_dt,duration/2,pins,deadline)
    second = None
    if first['status'] == 'PASS':
        restored = driver.capture.CaptureState(**io.parse_json(canonical(first['final_state'])))
        resume_prepared = dict(prepared)
        resume_prepared.pop('original_recipe',None)
        resume_prepared['soil_dissolved_rock_export_kg'] = 0.
        second = _run(restored,resume_prepared,repeat_dt,duration/2,pins,deadline)
    restart_ok = (base['status'] == 'PASS' and second is not None and second['status'] == 'PASS'
                  and _exact_state(base['final_state'],second['final_state']))
    all_pass = (all(row['status'] == 'PASS' for row in cases) and repeat_ok and restart_ok
                and refinement['status'] == 'PASS' and recipient_stability['status'] == 'PASS' and source_snapshot() == pins)
    return {'schema':'diadem.terrain.shoreline-verification.r4', 'status':'PASS' if all_pass else 'FAIL',
            'scope':'BOUNDED_SYNTHETIC_NUMERICAL_DRIVER_VERIFICATION_ONLY',
            'prepared_state_sha256':digest(initial.as_dict()), 'prepared_state':initial.as_dict(),
            'prepared_control_sha256':hashlib.sha256(control_bytes).hexdigest(),
            'soil_dissolved_rock_export_kg':dissolved, 'sources':pins, 'cases':cases,
            'initial_refinement':initial_refinement, 'refinement':refinement,
            'recipient_stability':recipient_stability,
            'additional_reference_requested':bool(extra_finer),
            'identical_repeat':{'status':'PASS' if repeat_ok else 'FAIL','dt_years':repeat_dt,'run':repeated},
            'json_checkpoint_restart':{'status':'PASS' if restart_ok else 'FAIL','dt_years':repeat_dt,
                                       'prefix_duration_years':duration/2,'first':first,'second':second,
                                       'soil_prefix_reapplied':False,
                                       'second_interval_ledger_scope':'RESTORED_CAPTURE_STATE_AND_SECOND_INTERVAL_TRANSFERS',
                                       'requirement':'EXACT_FINAL_STATE_BYTES_SAME_OUTER_DT'},
            'whole_verification_wall_seconds':time.monotonic()-started,
            'physical_acceptance':False,'production_authorised':False,'workflow_adoption':False,
            'fresh_optimisation_speedup_established':False,'optimisation_speedup_percent':None}


def verify_near_flat(*, extra_finer=False):
    """Requested retained 0.8-year case; no hidden calibration or soil repeats."""
    rejection = retained_rejection(shoreline_fixtures.retained_recipe())
    prepared = shoreline_fixtures.near_flat()
    if prepared['coupled_duration_years'] != .8:raise VerificationError('retained duration changed')
    report = verify_prepared(prepared,extra_finer=extra_finer)
    report['retained_r2_rejection'] = rejection
    report['comparison_soil_preparation_count'] = 1
    report['soil_prefix_result_sha256'] = digest(prepared['soil_prefix_result'])
    report['original_recipe_sha256'] = digest(prepared['original_recipe'])
    if rejection['status'] != 'PASS_RETAINED_REJECTION' or not rejection['recipe_unchanged']:
        report['status'] = 'FAIL'
    return report
