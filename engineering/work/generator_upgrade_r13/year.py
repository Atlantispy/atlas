"""One exact supplied seasonal calendar, persistent coupled soil state."""
from copy import deepcopy
from fractions import Fraction
import math
import time
from . import provenance as p, soil, audit

SCHEMA = 'diadem.coupled-soil-year-recipe.r13'
FIELDS = {'schema', 'scenario_id', 'context', 'model', 'initial', 'calendar',
          'events', 'controls', 'joins', 'evidence', 'source_status'}
FRAME = {'world_id', 'snapshot_id', 'calendar_id', 'spatial_frame_id',
         'vertical_reference', 'scenario_id'}


def plain(value, depth=0):
    if depth > 48:
        raise ValueError('bounded soil JSON nesting required')
    if type(value) is dict:
        if any(type(k) is not str for k in value):
            raise ValueError('string soil JSON keys required')
        for item in value.values():
            plain(item, depth + 1)
    elif type(value) is list:
        for item in value:
            plain(item, depth + 1)
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError('finite soil JSON required')
    elif type(value) not in (int, str, bool, type(None)):
        raise ValueError('plain soil JSON required')
    return value


def exact(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('exact '+label+' fields required')


def text(value):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError('explicit bounded soil identity/evidence required')


def duration(value):
    if type(value) not in (int, float, str):
        raise ValueError('explicit soil duration required')
    try:
        result = Fraction(value)
        if not 0 < result <= 10**9 or not math.isfinite(float(result)):
            raise ValueError('bounded positive soil duration required')
    except (OverflowError, ZeroDivisionError) as exc:
        raise ValueError('invalid soil duration') from exc
    return result


def validate(spec):
    plain(spec)
    if len(p.encoded(spec)) > p.shared.LIMIT:
        raise ValueError('bounded soil recipe required')
    exact(spec, FIELDS, 'soil year recipe')
    if spec['schema'] != SCHEMA:
        raise ValueError('R13 soil recipe required')
    for key in ('scenario_id', 'evidence'):
        text(spec[key])
    exact(spec['context'], FRAME, 'soil frame')
    for value in spec['context'].values():
        text(value)
    if spec['context']['scenario_id'] != spec['scenario_id']:
        raise ValueError('soil scenario/frame mismatch')
    if spec['source_status'] not in ('SYNTHETIC TEST', 'WORKING NON-CANON', 'UNKNOWN'):
        raise ValueError('explicit soil source status required')
    exact(spec['initial'], ('head_m', 'temperature_k', 'elapsed_seconds'), 'initial soil inputs')
    exact(spec['calendar'], ('calendar_id', 'month_durations_seconds'), 'soil calendar')
    if spec['calendar']['calendar_id'] != spec['context']['calendar_id']:
        raise ValueError('soil calendar/frame mismatch')
    months = spec['calendar']['month_durations_seconds']
    if type(months) is not list or len(months) != 12:
        raise ValueError('twelve explicit soil calendar months required')
    expected = [duration(value) for value in months]
    if type(spec['events']) is not list or not 12 <= len(spec['events']) <= 8192:
        raise ValueError('bounded complete seasonal soil event inventory required')
    totals = [Fraction() for _ in expected]
    ids, elapsed, previous_month = set(), Fraction(), 1
    for row in spec['events']:
        exact(row, ('event_id', 'month_id', 'start_seconds_in_year', 'duration_seconds',
                    'forcing', 'evidence', 'source_status'), 'soil year event')
        text(row['event_id']); text(row['evidence'])
        month = row['month_id']
        if (row['event_id'] in ids or type(month) is not int
                or not previous_month <= month <= 12
                or type(row['start_seconds_in_year']) not in (int, float, str)
                or Fraction(row['start_seconds_in_year']) != elapsed):
            raise ValueError('unique contiguous chronological soil events required')
        if row['source_status'] not in ('SYNTHETIC TEST', 'WORKING NON-CANON', 'UNKNOWN'):
            raise ValueError('explicit soil forcing source status required')
        dt = duration(row['duration_seconds'])
        if type(row['forcing']) is not dict or row['forcing'].get('duration_s') != float(dt):
            raise ValueError('soil event/core duration mismatch')
        ids.add(row['event_id']); totals[month-1] += dt
        elapsed += dt; previous_month = month
    if totals != expected:
        raise ValueError('soil events must cover each exact calendar month once')
    return expected


def _unknown(value):
    if value is None:
        return True
    if type(value) is dict:
        return value.get('source_status') == 'UNKNOWN' or any(_unknown(v) for v in value.values())
    if type(value) is list:
        return any(_unknown(v) for v in value)
    return False


def _row(forcing, result):
    return {key: forcing[key] for key in ('event_id', 'month_id', 'start_seconds_in_year',
            'duration_seconds')} | {'forcing_sha256': p.sha(forcing), 'result': result}


def _certificate(source_sha, spec_sha, forcing, state, row):
    key = p.sha({'schema': 'diadem.soil-invocation.r13', 'source': source_sha,
                 'recipe': spec_sha, 'forcing': p.sha(forcing), 'initial': p.sha(state)})
    return key, {'schema': 'diadem.soil-verified-result.r13', 'invocation': key,
                 'row_sha256': p.sha(row)}


def run(spec, *, stop_after=None, resume=None, progress=False, store=None, on_checkpoint=None):
    """Journal accepted events; authenticate reuse or retain the no-cache replay path."""
    started = time.perf_counter()
    if type(progress) is not bool:
        raise ValueError('progress requires an explicit boolean')
    if on_checkpoint is not None and not callable(on_checkpoint):
        raise ValueError('checkpoint callback must be callable')
    spec = deepcopy(spec)
    validate(spec)
    binding = p.identity()
    source_sha, spec_sha = p.sha(binding), p.sha(spec)
    if store is not None:
        from work.generator_runtime_r12.store import Store
        if type(store) is not Store or store.namespace != source_sha:
            raise ValueError('authenticated soil store with exact source/runtime namespace required')
    warnings, reused = [], 0
    count = len(spec['events']) if stop_after is None else stop_after
    if type(count) is not int or not 0 <= count <= len(spec['events']):
        raise ValueError('bounded complete soil event cursor required')
    rows, state, completed = [], None, 0
    if resume is not None:
        exact(resume, ('schema', 'source_sha256', 'recipe_sha256', 'state_sha256', 'state'), 'soil checkpoint')
        if (resume['schema'] != 'diadem.coupled-soil-checkpoint.r13'
                or resume['source_sha256'] != source_sha or resume['recipe_sha256'] != spec_sha
                or resume['state_sha256'] != p.sha(plain(resume['state']))):
            raise ValueError('soil checkpoint source/recipe/state binding differs')
        exact(resume['state'], ('completed_events', 'continuing_state', 'accepted_events'), 'soil checkpoint state')
        completed = resume['state']['completed_events']
        if type(completed) is not int or not 0 <= completed <= count:
            raise ValueError('soil checkpoint cursor exceeds requested prefix')
        if store is None:
            replay = run(spec, stop_after=completed)['scientific']['checkpoint']
            if resume != replay:
                raise ValueError('soil checkpoint differs from actual coupled event replay')
        else:
            accepted = resume['state']['accepted_events']
            if type(accepted) is not list or len(accepted) != completed:
                raise ValueError('exact authenticated soil prefix inventory required')
            unknown = spec['source_status'] == 'UNKNOWN' or _unknown(spec['model']) or _unknown(spec['initial'])
            expected = None if unknown else soil.initial_state(spec['model'], **spec['initial'])
            if unknown and completed:
                raise ValueError('unknown soil initial state cannot have a completed prefix')
            for forcing, saved_row in zip(spec['events'], accepted):
                if (type(saved_row) is not dict or saved_row != _row(forcing, saved_row.get('result'))
                        or type(saved_row['result']) is not dict
                        or saved_row['result'].get('initial_state') != expected):
                    raise ValueError('authenticated soil prefix event/initial-state lineage differs')
                key, certificate = _certificate(source_sha, spec_sha, forcing, expected, saved_row)
                actual = store.get(key)
                if actual is None:
                    raise ValueError('soil prefix has no authenticated certificate; explicit no-cache replay required: '+forcing['event_id'])
                if actual != certificate:
                    raise ValueError('soil prefix differs from authenticated result: '+forcing['event_id'])
                audit.event(spec['model'], forcing['forcing'], saved_row['result'], spec['controls'])
                expected = saved_row['result']['final_state']
            if expected != resume['state']['continuing_state']:
                raise ValueError('authenticated soil prefix endpoint differs')
            reused = completed
        rows = deepcopy(resume['state']['accepted_events'])
        state = deepcopy(resume['state']['continuing_state'])
    status, reason = None, None
    if spec['source_status'] == 'UNKNOWN' or _unknown(spec['model']) or _unknown(spec['initial']):
        status, reason = 'UNKNOWN', 'required soil law/initial state unknown; no default substitution'
    elif state is None:
        state = soil.initial_state(spec['model'], **spec['initial'])
    initial_state = deepcopy(state) if completed == 0 else deepcopy(rows[0]['result']['initial_state'])

    def snapshot():
        complete = status is None and completed == len(spec['events'])
        saved = {'completed_events': completed, 'continuing_state': state, 'accepted_events': rows}
        checkpoint = {'schema': 'diadem.coupled-soil-checkpoint.r13', 'source_sha256': source_sha,
                      'recipe_sha256': spec_sha, 'state_sha256': p.sha(saved), 'state': saved}
        result = {'schema': 'diadem.coupled-soil-year.r13',
                  'status': status or ('MODELLED_COUPLED_SOIL_YEAR' if complete else 'STOPPED'),
                  'source_status': spec['source_status'], 'source_sha256': source_sha,
                  'recipe_sha256': spec_sha, 'scenario_id': spec['scenario_id'],
                  'context': spec['context'], 'joins': spec['joins'],
                  'initial_state': initial_state, 'completed_events': completed, 'events': rows,
                  'final_state': state if complete else None, 'last_complete_event_state': state,
                  'checkpoint': checkpoint, 'reason': reason,
                  'held_initial_water': False, 'geometry_feedback_applied': False,
                  'downstream_old_moisture_products': 'NOT_REVALIDATED_BY_THIS_SOIL_SUCCESSOR',
                  'production_authorised': False, 'canon_changed': False,
                  'whole_diadem_year_verified': False}
        return {'scientific': plain(result), 'execution': {'identity': binding,
                'elapsed_wall_seconds': time.perf_counter()-started,
                'resume_policy': 'AUTHENTICATED_COMPLETE_EVENT_REUSE' if store is not None else 'EXACT_COMPLETE_EVENT_REPLAY',
                'reused_events': reused, 'cache_stats': None if store is None else store.stats,
                'cache_warnings': list(warnings), 'complete': complete,
                'incremental_checkpoints': on_checkpoint is not None, 'progress_reporting': progress}}

    def commit():
        p.verify(binding)
        value = snapshot()
        if on_checkpoint is not None:
            on_checkpoint(deepcopy(value))
        return value

    commit()  # Persist the verified initial/resumed prefix before further computation.
    for row in spec['events'][completed:count]:
        if status:
            break
        if row['source_status'] == 'UNKNOWN' or _unknown(row['forcing']):
            status, reason = 'UNKNOWN', 'required soil forcing unknown at '+row['event_id']
            break
        solved = soil.advance(spec['model'], state, row['forcing'], spec['controls'])
        if solved['status'] != 'MODELLED':
            status = solved['status']
            reason = {'event_id': row['event_id'], 'failure': solved}
            break
        if solved['initial_state'] != state:
            raise ValueError('coupled soil event initial state differs from accepted prefix')
        try:
            audit.event(spec['model'], row['forcing'], solved, spec['controls'])
        except ValueError as error:
            status = 'NUMERICAL_FAILURE'
            reason = {'event_id': row['event_id'], 'failure': {
                'status': 'REJECTED_BY_INDEPENDENT_ACCOUNT', 'reason': str(error),
                'rejected_producer_result': solved}}
            break
        accepted_row = _row(row, solved)
        if store is not None:
            p.verify(binding)
            key, certificate = _certificate(source_sha, spec_sha, row, state, accepted_row)
            before = store.stats
            store.put(key, certificate)
            actual = store.get(key)
            if actual is None:
                cause = 'full' if store.stats['skipped_full'] > before['skipped_full'] else 'oversized'
                warning = 'Authenticated soil cache '+cause+'; saved uncached events require explicit no-cache replay.'
                if warning not in warnings:
                    warnings.append(warning)
                    if progress:
                        print(p.encoded({'status': 'CACHE_WARNING', 'warning': warning}).decode(), flush=True)
            elif actual != certificate:
                raise ValueError('soil certificate readback differs')
        state = solved['final_state']
        rows.append(accepted_row)
        completed += 1
        commit()
        if progress:
            print(p.encoded({'event_id': row['event_id'], 'completed_events': completed,
                             'status': 'VERIFIED_EVENT',
                             'elapsed_wall_seconds': time.perf_counter()-started}).decode(), flush=True)
    return commit()
