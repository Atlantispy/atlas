"""Deterministic proposals from authenticated accepted native-step evidence.

This changes the requested trial sequence, not acceptance tolerances or physics.
The caller must validate the current session first and use remaining_halvings
with the original acceptance object, retaining the old absolute trial floor.
Every proposed interval still needs the retained full/two-half-step comparison,
topology checks and resource guards. Historical success never accepts a new step.
"""
from dataclasses import dataclass
from fractions import Fraction as F


MAX_DURATION_YEARS = F(5)
MAX_ACCEPTED_STEPS = 256
RECOVERY_PERIOD = 4
RECOVERY_MARGIN = F(1, 16)
POLICY = 'native-history-duration-proposal.r1'


@dataclass(frozen=True)
class Proposal:
    duration_years: F
    skipped_halvings: int
    remaining_halvings: int
    evidence: dict


def _q(value, name, *, positive=False):
    if type(value) not in (F, str, int):
        raise ValueError(name + ' requires an exact rational')
    try:
        result = F(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(name + ' requires an exact rational') from error
    if result < 0 or (positive and not result):
        raise ValueError(name + ' is outside its nonnegative/positive bound')
    return result


def latest_accepted_row(history):
    """Read only the last complete row; never expand the whole closed history.

    R3 iteration/indexing yields summaries without rejection or acceptance
    evidence. Its private authenticated single-entry reader is deliberately
    isolated here so an archive API change has one explicit adaptation point.
    Lists/tuples are supported for already validated in-memory envelopes.
    """
    if type(history) in (list, tuple):
        return history[-1] if history else None
    from work.native_terrain_r3 import history as archived
    if type(history) is not archived.History:
        raise ValueError('validated native history container required')
    archived._verify_source()
    if not len(history):
        return None
    return archived._parse(history._raw(history._entries[-1], authenticate_summary=True))


def _halvings(baseline, duration, ceiling):
    for count in range(ceiling + 1):
        if baseline == duration:
            return count
        baseline /= 2
    raise ValueError('requested duration differs from retained bounded halving grid')


def _acceptance(acceptance):
    names = ('max_surface_error_m', 'max_material_bulk_l1_error_m3',
             'max_allocation_error_m3', 'max_halvings', 'evidence')
    try:
        values = {name: getattr(acceptance, name) for name in names}
    except AttributeError as error:
        raise ValueError('complete original acceptance contract required') from error
    if (type(values['max_halvings']) is not int or not 0 <= values['max_halvings'] <= 12
            or type(values['evidence']) is not str or not values['evidence']):
        raise ValueError('original bounded acceptance contract required')
    for name in names[:3]:
        values[name] = _q(values[name], name)
    return values


def _validate_latest(row, elapsed, target, acceptance):
    if type(row) is not dict:
        raise ValueError('complete latest accepted row required')
    try:
        start = _q(row['start_year'], 'history start')
        duration = _q(row['duration_years'], 'history duration', positive=True)
        requested = _q(row['requested_duration_years'], 'history request', positive=True)
        if start + duration != elapsed or row['accepted_method'] != 'TWO_HALF_STEPS_FULL_TRIAL_DISCARDED':
            raise ValueError('latest accepted row does not end at current elapsed time')
        if type(row['operation_id']) is not str or not row['operation_id']:
            raise ValueError('latest accepted operation identity required')
        prior = row['acceptance']
        if type(prior) is not dict or set(prior) != set(acceptance):
            raise ValueError('latest acceptance contract differs')
        for name, value in acceptance.items():
            if name == 'max_halvings':
                continue
            observed = prior[name] if name == 'evidence' else _q(prior[name], name)
            if observed != value:
                raise ValueError('latest acceptance tolerance/evidence differs')
        skipped = _halvings(min(MAX_DURATION_YEARS, target - start), requested,
                            acceptance['max_halvings'])
        if (type(prior['max_halvings']) is not int
                or prior['max_halvings'] != acceptance['max_halvings'] - skipped):
            raise ValueError('latest trial floor differs from original acceptance budget')
        rejected = row['rejected_trials']
        if type(rejected) not in (list, tuple) or len(rejected) > prior['max_halvings']:
            raise ValueError('bounded complete rejected-trial history required')
        trial_duration = requested
        for trial in rejected:
            if type(trial) is not dict or _q(trial['duration_years'], 'rejected duration', positive=True) != trial_duration:
                raise ValueError('rejected trial halving sequence differs')
            if 'kind' in trial:
                if (trial['kind'] not in ('TerrainStepTooLarge', 'HillslopeStepTooLarge')
                        or type(trial['reason']) is not str or not trial['reason']):
                    raise ValueError('unsupported trial-size rejection evidence')
            else:
                residuals = _diagnostics(trial, trial_duration, acceptance)
                if all(value <= 1 for value in residuals):
                    raise ValueError('recorded numerical rejection satisfies acceptance')
            trial_duration /= 2
        if trial_duration != duration:
            raise ValueError('accepted duration differs from rejected trial sequence')
        ratios = _diagnostics(row['diagnostics'], duration, acceptance)
        if any(value > 1 for value in ratios):
            raise ValueError('latest accepted diagnostics exceed original tolerances')
    except (KeyError, TypeError) as error:
        raise ValueError('latest accepted evidence is incomplete') from error
    return duration, rejected, ratios


def _ratio(value, maximum):
    # Zero tolerances permit growth only for an exactly zero observed error.
    return value / maximum if maximum else (F() if value == 0 else F(2))


def _diagnostics(diagnostics, duration, acceptance):
    if (type(diagnostics) is not dict
            or _q(diagnostics['duration_years'], 'diagnostic duration', positive=True) != duration
            or diagnostics['topology_equal'] is not True
            or diagnostics['within_operator_topology_change'] is not False):
        raise ValueError('accepted/rejected topology or duration evidence differs')
    fields = (('surface_error_m', 'max_surface_error_m'),
              ('material_bulk_l1_error_m3', 'max_material_bulk_l1_error_m3'),
              ('cumulative_allocation_error_m3', 'max_allocation_error_m3'))
    return tuple(_ratio(_q(diagnostics[field], field), acceptance[limit]) for field, limit in fields)


def propose_duration(history, remaining_years, acceptance, *, elapsed_years, previous_count=0):
    """Select a bounded next request and explicit changed-execution evidence.

    Recovery tries one larger rung every fourth upcoming accepted-step index,
    only after a rejection-free step whose two local error ratios are <=1/16.
    The retained solver decides whether that trial is acceptable. This small
    heuristic is not an error extrapolation guarantee or physical calibration.
    All timing/trial savings require a separately observed matched comparison.
    """
    remaining = _q(remaining_years, 'remaining years', positive=True)
    elapsed = _q(elapsed_years, 'elapsed years')
    original = _acceptance(acceptance)
    if type(previous_count) is not int or previous_count < 0:
        raise ValueError('nonnegative predecessor accepted-step count required')
    count = previous_count + len(history)
    if count >= MAX_ACCEPTED_STEPS:
        raise ValueError('retained 256 accepted-step ceiling reached')
    baseline = min(MAX_DURATION_YEARS, remaining)
    duration, skipped, reason = baseline, 0, 'NO_ACCEPTED_HISTORY'
    row = latest_accepted_row(history)
    evidence = {'policy': POLICY, 'source_status': 'WORKING NON-CANON',
                'baseline_duration_years': str(baseline),
                'original_max_halvings': original['max_halvings'],
                'absolute_trial_floor_years': str(baseline / 2 ** original['max_halvings']),
                'next_accepted_step_index': count + 1,
                'recovery_period_steps': RECOVERY_PERIOD, 'recovery_error_ratio_limit': str(RECOVERY_MARGIN),
                'acceptance_and_topology_checks_required': True,
                'complete_scientific_body_identity_expected': False}
    if row is not None:
        latest, rejected, ratios = _validate_latest(row, elapsed, elapsed + remaining, original)
        wanted = latest
        reason = 'REUSE_LAST_ACCEPTED_DURATION'
        if (not rejected and (count + 1) % RECOVERY_PERIOD == 0
                and all(ratio <= RECOVERY_MARGIN for ratio in ratios[:2])):
            wanted *= 2
            reason = 'PERIODIC_LOW_ERROR_RECOVERY_PROBE'
        while duration > wanted and skipped < original['max_halvings']:
            duration /= 2
            skipped += 1
        if duration > wanted:
            reason = 'ORIGINAL_TRIAL_FLOOR_GUARD'
        if duration == baseline and baseline <= latest:
            reason = 'TARGET_OR_MAXIMUM_CLAMP'
        evidence.update(last_operation_id=row['operation_id'], last_accepted_duration_years=str(latest),
                        previous_rejected_durations_years=[str(F(item['duration_years'])) for item in rejected],
                        last_local_error_ratios=[str(value) for value in ratios[:2]])
    remaining_halvings = original['max_halvings'] - skipped
    evidence.update(reason=reason, proposed_duration_years=str(duration),
                    skipped_halvings=skipped, remaining_halvings=remaining_halvings)
    return Proposal(duration, skipped, remaining_halvings, evidence)
