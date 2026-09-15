"""Event-bounded continuous channel-to-pool reference; see driver contract.

The direct-exterior spill envelope is deliberate. This is not a full hydraulic
network, field calibration or production generator. All trial states are pure.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import math
import time

import capture
import continuous_pool
import event_settling
import forced_drying
import exact_forced_endpoint
import shoreline
from shoreline_materials import hillslope_trial
from shoreline_network import build_network, _neighbours
from r3_bindings import settling

MAX_SUBSTEPS = 4096
MAX_REJECTS = 4096
MAX_CELL_TRIALS = 2097152
MAX_BISECTIONS = 48
EVENT_ATOL_YEARS = 1e-10
EVENT_RTOL = 1e-11


class CouplingError(ValueError):
    def __init__(self, message, **context):
        super().__init__(message)
        self.context = context


def _height_tolerance(*values):
    return 1e-9 + 1e-11 * max(map(abs, values), default=0.)


def _check_ledger(residual, scale, label, roundoff=0.):
    band = 1e-9 + 1e-12 * scale + roundoff
    if abs(residual) > band:
        raise CouplingError(label + ' budget does not close', residual=residual, tolerance=band)
    return {'residual_m3': residual, 'tolerance_m3': band}


def _pool_rates(network, report):
    rates = {p['id']: [[], []] for p in network['pools']}
    for row in report['pool_ports']:
        rates[row['pool_id']][0].append(row['liquid_m3_year'])
        rates[row['pool_id']][1].append(row['suspended_solid_m3_year'])
    for row in report['pool_local_runoff']:
        rates[row['pool_id']][0].append(row['liquid_m3_year'])
    return {p: (math.fsum(w), math.fsum(s)) for p, (w, s) in rates.items()}


def _external_boundary_representation(state, pool, inflow):
    sill = pool['spill']['spill_m']
    cells = pool['cell_indices']
    residuals = capture.phase_storage.liquid_remainders(state.liquid_m3, getattr(state,'liquid_remainder_m3',None))
    deficit = sum((Fraction(state.cell_area_m2[i]) * (Fraction(sill)-Fraction(state.bed_m[i]))
                   - Fraction(state.liquid_m3[i]) - residuals[i] - Fraction(state.suspended_solid_m3[i]) for i in cells), Fraction())
    area = sum((Fraction(state.cell_area_m2[i]) for i in cells), Fraction())
    bound = Fraction(math.ulp(sill)) * area / 2
    if deficit < 0 or deficit > bound:
        raise CouplingError('rounded external sill exceeds declared sub-ULP capacity envelope')
    return {'closure': 'EXACT_CAPACITY' if deficit == 0 else 'QUANTISED_EXTERNAL_BOUNDARY_ONLY',
            'exact_capacity_deficit': {'numerator': deficit.numerator, 'denominator': deficit.denominator},
            'capacity_deficit_m3': float(deficit), 'capacity_quantisation_bound_m3': float(bound),
            'early_spill_time_bound_years': float(deficit/Fraction(inflow)) if inflow > 0 else None,
            'inventories_adjusted': False, 'native_wetting_authorised': False}


def _check_displacement_routes(routed, external_outlets, prior):
    """Bed-change/end-bracket equilibration cannot bypass a real dry reach."""
    topology = routed['topology']
    rows = {row['id']: row for row in topology['basins']}
    certificates = []
    for transfer in routed['events']:
        if transfer['kind'] != 'spill': continue
        name = transfer['from']; footprint = set(rows[name]['cell_indices'])
        event = next((e for e in topology['saddle_events'] if e.get('source') == name or name in e.get('children', [])), None)
        if event is not None:
            edge = event['edge_cells']
            if all(prior.liquid_m3[i]+prior.suspended_solid_m3[i] > 0 for i in edge) and any(
                    set(edge) <= set(pool['wet_cell_indices']) for pool in routed['active_pools']):
                certificates.append({'source_basin':name, 'kind':'INTRA_EXISTING_POSITIVE_POOL_REALLOCATION',
                                     'edge_cells':edge, 'transfer':transfer})
                continue
        if transfer['to_leaf'] is not None or event is None:
            raise CouplingError('displacement requires inter-pool/corridor exchange integration', transfer=transfer)
        recipients = [i for i in event['edge_cells'] if i not in footprint]
        if len(recipients) != 1 or recipients[0] not in external_outlets:
            raise CouplingError('displaced water cannot bypass downstream dry-channel material work', transfer=transfer)
        certificates.append({'source_basin': name, 'receiver_cell': recipients[0],
                             'kind': 'IMMEDIATE_EXTERNAL', 'transfer': transfer})
    return certificates


def _phase_representation_evidence(*routings):
    records = []
    for position, routed in enumerate(routings):
        for pool in routed['active_pools']:
            row = pool.get('full_sill_representation')
            if row is not None:
                records.append({'routing_position':position, 'pool_id':pool['id'], **row})
    return {'records':records,
            'liquid_adjustment_m3':math.fsum(r['adjustment_liquid_m3'] for r in records),
            'suspended_solid_adjustment_m3':math.fsum(r['adjustment_suspended_solid_m3'] for r in records),
            'liquid_adjustment_bound_m3':math.fsum(r.get('adjustment_liquid_bound_m3',0.) for r in records),
            'suspended_solid_adjustment_bound_m3':math.fsum(r.get('adjustment_suspended_solid_bound_m3',0.) for r in records),
            'arithmetic_bound_m3':math.fsum(r['arithmetic_bound_m3'] for r in records),
            'physical_transfer':False}


def _exact_ratio(record, label):
    if (type(record) is not dict or set(record) != {'numerator','denominator'}
            or type(record['numerator']) is not int
            or type(record['denominator']) is not int
            or record['denominator'] <= 0):
        raise CouplingError(label+' lacks an exact rational representation')
    return Fraction(record['numerator'],record['denominator'])


def _existing_pool_shallowest_tie(base, pool):
    """Derive the complete positive-depth tie from the exact current stage."""
    exact_stage=_exact_ratio(pool['exact_stage_m'],'pool stage')
    positive,zero=[],[]
    for cell in pool['cell_indices']:
        depth=exact_stage-Fraction(base.bed_m[cell])
        if depth < 0:
            raise CouplingError('pool cell lies above its exact represented stage',
                                pool_id=pool['id'],cell_index=cell)
        (positive if depth > 0 else zero).append((cell,depth))
    if not positive:
        raise CouplingError('positive-inventory pool has no exact positive-depth native cell',
                            pool_id=pool['id'])
    wet=set(pool['wet_cell_indices']);incipient=set(pool['incipient_cell_indices'])
    if wet != {cell for cell,_ in positive} or incipient != {cell for cell,_ in zero}:
        raise CouplingError('pool wet/incipient inventory disagrees with exact stage and bed',
                            pool_id=pool['id'])
    minimum=min(depth for _,depth in positive)
    ties=[cell for cell,depth in positive if depth == minimum]
    represented=float(minimum)
    if not math.isfinite(represented) or represented <= 0:
        raise CouplingError('exact shallowest positive depth is not representable',pool_id=pool['id'])
    return {'cell_indices':ties,'represented_depth_m':represented,
            'exact_depth':{'numerator':minimum.numerator,'denominator':minimum.denominator},
            'all_positive_depth_cell_indices':[cell for cell,_ in positive],
            'excluded_zero_depth_right_limit_cell_indices':[cell for cell,_ in zero],
            'completeness':'ALL_EXACT_POSITIVE_DEPTH_CELLS_IN_NETWORK_POOL'}


def _fraction_record(value):
    return {'numerator':value.numerator,'denominator':value.denominator}


def _activated_margin_invariant(pool, row, velocity, area, tie):
    margins=tie['excluded_zero_depth_right_limit_cell_indices']
    if not margins:
        return None
    if row['qo'] != 0:
        raise CouplingError('overflow activation cannot certify a zero-depth margin',
                            pool_id=pool['id'],cell_indices=margins)
    volume=Fraction(pool['liquid_m3'])+Fraction(pool['suspended_solid_m3'])
    concentration=Fraction(pool['suspended_solid_m3'])/volume
    exact_area=Fraction(area);exact_velocity=Fraction(velocity)
    total_input=Fraction(row['qw'])+Fraction(row['qs'])
    stage_rate=total_input/exact_area
    right_rate=stage_rate-exact_velocity*concentration
    if right_rate <= 0:
        raise CouplingError('exact zero-depth margin lacks positive right-limit depth',
                            pool_id=pool['id'],cell_indices=margins,
                            exact_right_rate=_fraction_record(right_rate))
    if exact_velocity == 0:
        proof='ZERO_SETTLING_POSITIVE_STAGE_RATE'
        threshold=None;polynomial=None
    else:
        threshold=stage_rate/exact_velocity
        if threshold >= 1:
            proof='DEPTH_RATE_THRESHOLD_AT_OR_ABOVE_UNIT_CONCENTRATION'
            polynomial=None
        else:
            k=exact_velocity*exact_area
            polynomial=(Fraction(row['qs'])-(total_input+k)*threshold
                        +k*threshold*threshold)
            if polynomial != -Fraction(row['qw']) or polynomial > 0:
                raise CouplingError('zero-depth margin threshold-sign identity failed',
                                    pool_id=pool['id'])
            proof='THRESHOLD_CONCENTRATION_DERIVATIVE_NONPOSITIVE'
    return {'status':'CERTIFIED_ZERO_MARGIN_NOT_FIRST_LATER_DRYING_EVENT',
            'proof':proof,'cell_indices':margins,'mixture_export_m3_year':0.,
            'initial_concentration':_fraction_record(concentration),
            'initial_right_depth_rate_m_year':_fraction_record(right_rate),
            'threshold_concentration':None if threshold is None else _fraction_record(threshold),
            'threshold_concentration_polynomial':None if polynomial is None else _fraction_record(polynomial),
            'derivation':'AT_HPRIME_ZERO_DC_DT_SIGN_EQUALS_MINUS_QW_OVER_POSITIVE_VOLUME',
            'constant_forcing_only':True,'physical_acceptance':False}


def _stable_forced_certificate(result, tie, margin_invariant):
    certificate={key:deepcopy(value) for key,value in result.items() if key != 'wall_seconds'}
    certificate['driver_exact_tie_derivation']=deepcopy(tie)
    certificate['activated_zero_depth_margin_invariant']=deepcopy(margin_invariant)
    certificate['bounded_probe_inventory']=len(result['probes'])
    return certificate


def _detect_forced_event(counts, state, **kwargs):
    try:
        result = forced_drying.first_event(**kwargs)
    except forced_drying.ForcedDryingError as exc:
        counts['scalar_rhs_evaluations'] += exc.scalar_rhs_evaluations
        exc.driver_counts = dict(counts)
        exc.unchanged_driver_checkpoint = state.as_dict()
        raise
    counts['scalar_rhs_evaluations'] += result['scalar_rhs_evaluations']
    return result


def _trial_impl(state, dt, parameters, counts, deadline, *, finalise=False):
    counts['trial_calls'] += 1
    counts['trial_cell_evaluations'] += state.size
    if counts['trial_cell_evaluations'] > MAX_CELL_TRIALS or time.monotonic() > deadline:
        raise CouplingError('coupled trial resource envelope exhausted')
    p = parameters
    base, hill = hillslope_trial(state, dx_m=p['dx_m'], dy_m=p['dy_m'],
                diffusivity_m2_year=p['diffusivity_m2_year'], dt_years=dt)
    routed_start = capture.route(base, p['external_outlets'], p['connectivity'])
    if (any(n for n,d in routed_start['liquid_remainder_m3']) or routed_start['exported_liquid_remainder_m3'][0]):
        raise CouplingError('nonzero liquid remainder requires exact shoreline transport')
    start_spill_certificates = _check_displacement_routes(routed_start, p['external_outlets'], base)
    base = capture.from_route(base, routed_start)
    network_args = {key: p[key] for key in ('dx_m', 'dy_m', 'external_outlets',
                    'runoff_m_year', 'connectivity', 'incoming_liquid_m3_year', 'incoming_solid_m3_year')}
    network = build_network(base, **network_args)
    margins = [row for row in network['zero_depth_margin_candidates']
               if row['pool_liquid_inflow_m3_year'] > 0]
    if margins:
        claims = {}
        for row in margins:
            if not row['exact_stage_equals_bed']:
                raise CouplingError('native contact is not exact despite rounded stage equality', margin=row)
            cell = row['cell_index']
            if cell in claims and claims[cell] != row['pool_id']:
                raise CouplingError('simultaneous zero-head pool join requires an explicit event closure')
            claims[cell] = row['pool_id']
        network = build_network(base, **network_args, activated_margins=claims)
    channel_args = {key: p[key] for key in ('runoff_m_year', 'sediment_k_per_year',
                    'rock_k_per_year', 'cover_scale_m', 'settling_m_year',
                    'incoming_liquid_m3_year', 'incoming_solid_m3_year')}
    dry, channel = shoreline.channel_trial(base, **network['channel_kwargs'], **channel_args, dt_years=dt)
    rates = _pool_rates(network, channel)
    owners = network['channel_kwargs']['pool_owner']
    contacts, pools = [], []
    for pool in network['pools']:
        cells = pool['cell_indices']; area = math.fsum(base.cell_area_m2[i] for i in cells)
        qw, qs = rates[pool['id']]; incoming = math.fsum((qw, qs))
        eta = pool['stage_m']; spill = pool['spill']; sill = spill['spill_m']
        # The actual numerical geometric stage controls this reduced boundary.
        # The network has already rejected an exact inventory above the sill.
        overflowing = sill is not None and eta == sill
        if overflowing and incoming > 0 and not spill['supports_current_driver']:
            raise CouplingError('pool spill to a dry corridor or another pool is not integrated', spill=spill)
        qo = incoming if overflowing else 0.
        boundary_representation = _external_boundary_representation(base, pool, incoming) if overflowing else None
        eta_rate = (incoming - qo) / area
        if margins and any(row['pool_id'] == pool['id'] for row in margins):
            depth_rate = eta_rate - p['basin_settling_m_year'] * pool['solid_volume_fraction']
            if depth_rate <= 0:
                raise CouplingError('zero-depth margin does not have positive right-limit depth',
                                    pool_id=pool['id'], depth_rate_m_year=depth_rate)
        final_eta = math.fsum((eta, eta_rate * dt))
        boundary = sorted({j for i in cells for j, _, _ in _neighbours(i, base.shape, p['connectivity'])
                           if j not in cells})
        for j in boundary:
            if owners[j] is not None:
                raise CouplingError('distinct pools contact without an explicit join event')
            old_gap = base.bed_m[j] - eta
            new_gap = dry.bed_m[j] - final_eta
            if old_gap < 0:
                raise CouplingError('trial begins with a submerged unowned cell')
            if old_gap > 0 and new_gap <= 0:
                contacts.append({'kind': 'EXTERIOR_SPILL_START' if j in p['external_outlets'] else 'NATIVE_WETTING',
                                 'pool_id': pool['id'], 'cell_index': j, 'old_freeboard_m': old_gap,
                                 'new_freeboard_m': new_gap, 'stage_m': final_eta,
                                 'overshoot_m': -new_gap,
                                 'affine_contact_years': dt * old_gap / (old_gap - new_gap)})
        pools.append({'pool': pool, 'area_m2': area, 'qw': qw, 'qs': qs, 'qo': qo,
                      'eta_rate': eta_rate, 'predicted_stage_m': final_eta,
                      'boundary_representation': boundary_representation})
    evidence = {'dt_years': dt, 'contacts': contacts, 'network': network,
                'hillslope': hill, 'channel': channel, 'start_routing': routed_start,
                'displacement_spill_certificates': start_spill_certificates,
                'fixed_coefficient_operator_split': True}
    if contacts and not finalise:
        return None, evidence

    bed_solid = list(dry.bed_solid_m3); water = list(dry.liquid_m3); solid = list(dry.suspended_solid_m3)
    pool_rows = []
    for row in pools:
        if time.monotonic() >= deadline:
            raise CouplingError('shared coupling deadline exhausted between pool solves')
        pool = row['pool']; cells = pool['cell_indices']; area = row['area_m2']
        if row['qw'] == row['qs'] == row['qo'] == 0:
            # The independently verified daughter-pool solver already locates
            # every internal drying event. Do not replace it with a fixed-area
            # scalar call or re-mix its daughters at their equal dry saddle.
            subset = replace(dry, liquid_m3=tuple(dry.liquid_m3[i] if i in cells else 0. for i in range(dry.size)),
                             suspended_solid_m3=tuple(dry.suspended_solid_m3[i] if i in cells else 0. for i in range(dry.size)))
            remaining_wall = deadline-time.monotonic()
            if remaining_wall <= 0: raise CouplingError('coupled wall envelope exhausted before closed solve')
            closed, closed_report = event_settling.settle_components(subset,
                        settling_m_year=p['basin_settling_m_year'], elapsed_years=dt,
                        connectivity=p['connectivity'], wall_seconds=min(120., remaining_wall))
            counts['closed_event_solver_calls'] += closed_report['solver_calls']
            counts['trial_cell_evaluations'] += state.size+closed_report['cell_visits']
            if counts['trial_cell_evaluations'] > MAX_CELL_TRIALS:
                raise CouplingError('nested closed-pool cell envelope exhausted')
            for i in cells:
                bed_solid[i], water[i], solid[i] = closed.bed_solid_m3[i], closed.liquid_m3[i], closed.suspended_solid_m3[i]
            solved = {'liquid_m3': math.fsum(water[i] for i in cells),
                      'suspended_solid_m3': math.fsum(solid[i] for i in cells),
                      'deposited_solid_m3': math.fsum(bed_solid[i]-dry.bed_solid_m3[i] for i in cells),
                      'exported_liquid_m3': 0., 'exported_suspended_solid_m3': 0., 'evaluations': 0,
                      'method': 'EVENT_RESOLVED_CLOSED_DAUGHTER_POOLS'}
            pool_rows.append({'pool_id': pool['id'], 'cell_indices': cells, 'stage_m': pool['stage_m'],
                              'continuous_phases': solved, 'closed_event_settling': closed_report,
                              'spill_boundary': pool['spill'], 'mixture_export_m3_year': 0.,
                              'external_boundary_representation': row['boundary_representation']})
            continue
        forced_certificate=None
        exact_endpoint=None
        if (pool['liquid_m3'] or pool['suspended_solid_m3']) and any(
                value != 0 for value in (row['qw'],row['qs'],row['qo'])):
            if any(Fraction(base.bed_m[i]) != Fraction(dry.bed_m[i]) for i in cells):
                raise CouplingError('forced-pool bed changed before fixed-area event solve',
                                    pool_id=pool['id'])
            tie=_existing_pool_shallowest_tie(base,pool)
            positive_area=math.fsum(base.cell_area_m2[i]
                                    for i in tie['all_positive_depth_cell_indices'])
            margin_invariant=_activated_margin_invariant(
                pool,row,p['basin_settling_m_year'],area,tie)
            remaining_wall=deadline-time.monotonic()
            if remaining_wall <= 0:
                raise CouplingError('coupled wall envelope exhausted before forced-event solve')
            detected=_detect_forced_event(counts,state,
                liquid_m3=pool['liquid_m3'],
                suspended_solid_m3=pool['suspended_solid_m3'],
                total_wet_area_m2=area,
                shallowest_depth_m=tie['represented_depth_m'],
                shallowest_depth_ratio=tie['exact_depth'],
                shallowest_cell_indices=tie['cell_indices'],
                shallowest_cell_depths_m=[tie['represented_depth_m']]*len(tie['cell_indices']),
                native_cell_count=base.size,
                positive_depth_area_m2=positive_area,
                liquid_input_m3_year=row['qw'],solid_input_m3_year=row['qs'],
                mixture_export_m3_year=row['qo'],
                settling_m_year=p['basin_settling_m_year'],duration_years=dt,
                start_time_years=state.time_years,
                wall_seconds=min(forced_drying.MAX_WALL_SECONDS,remaining_wall))
            forced_certificate=_stable_forced_certificate(detected,tie,margin_invariant)
            exact_endpoint=exact_forced_endpoint.certify(base,pool,row,tie,
                p['basin_settling_m_year'],dt,detected)
            if detected['status'] == 'FIRST_DRYING_EVENT' and exact_endpoint is None:
                event=detected['event']
                bracket={'relative_low_years':event['low']['time_years'],
                         'relative_high_years':event['high']['time_years'],
                         'absolute_low_years':event['absolute_low_years'],
                         'absolute_high_years':event['absolute_high_years'],
                         'width_years':event['width_years'],
                         'simultaneous_cell_indices':event['simultaneous_cell_indices']}
                raise CouplingError('BLOCKED_FORCED_DAUGHTER_COUPLING',
                    status='BLOCKED_FORCED_DAUGHTER_COUPLING',pool_id=pool['id'],
                    event_bracket=bracket,forced_drying_certificate=forced_certificate,
                    forcing_ownership_gap={
                        'liquid_input_m3_year':row['qw'],
                        'solid_input_m3_year':row['qs'],
                        'mixture_export_m3_year':row['qo'],
                        'reason':'native recipient ownership is retained; post-event zero-head/spill exchange is not integrated'},
                    unchanged_driver_checkpoint=state.as_dict())
            if detected['status'] != 'NO_DRYING_CERTIFIED' and exact_endpoint is None:
                raise CouplingError(detected['status'],status=detected['status'],
                    pool_id=pool['id'],forced_drying_certificate=forced_certificate,
                    unchanged_driver_checkpoint=state.as_dict())
            endpoints=[probe for probe in detected['probes']
                       if probe['status']=='PASS' and Fraction(probe['time_years']) == Fraction(dt)]
            if len(endpoints) != 1:
                raise CouplingError('NO_DRYING certificate lacks one exact interval endpoint',
                                    pool_id=pool['id'])
            solved=endpoints[0]['scalar_result']
        else:
            try:
                solved = continuous_pool.advance_pool(pool['liquid_m3'], pool['suspended_solid_m3'], area,
                             row['qw'], row['qs'], row['qo'], p['basin_settling_m_year'], dt)
            except continuous_pool.ContinuousPoolError as exc:
                counts['scalar_rhs_evaluations'] += exc.evaluations
                raise
            counts['scalar_rhs_evaluations'] += solved['evaluations']
        if time.monotonic() >= deadline:
            raise CouplingError('shared coupling deadline exhausted after scalar pool solve')
        if exact_endpoint is not None:
            bs,ws,ss,endpoint_record=exact_forced_endpoint.reconstruct(dry,cells,area,
                exact_endpoint,p['connectivity'],p)
            for i,b,w,s in zip(cells,bs,ws,ss):
                bed_solid[i],water[i],solid[i]=b,w,s
            pool_rows.append({'pool_id':pool['id'],'cell_indices':cells,
                'stage_m':exact_endpoint['stage_m'],'continuous_phases':solved,
                'spill_boundary':pool['spill'],'mixture_export_m3_year':row['qo'],
                'external_boundary_representation':row['boundary_representation'],
                'forced_drying_certificate':forced_certificate,
                'exact_endpoint_drying':endpoint_record})
            continue
        rise = solved['deposited_solid_m3'] / area
        concentration0 = pool['solid_volume_fraction']
        volume1 = math.fsum((solved['liquid_m3'], solved['suspended_solid_m3']))
        concentration1 = solved['suspended_solid_m3'] / volume1 if volume1 else 0.
        # This legacy endpoint guard remains only for zero-inventory births;
        # existing forced pools already carry the stronger first-event proof.
        minimum_depth_rate = row['eta_rate'] - p['basin_settling_m_year'] * max(concentration0, concentration1)
        for i in cells:
            old_depth = pool['stage_m'] - base.bed_m[i]
            if (forced_certificate is None and old_depth > 0
                    and old_depth + min(0., minimum_depth_rate) * dt <= 0):
                raise CouplingError('simultaneously forced drying needs a resolved first-event solve',
                                    pool_id=pool['id'], cell_index=i)
            amount = rise * base.cell_area_m2[i]
            bed_solid[i] = math.fsum((bed_solid[i], amount))
            if amount > 0 and bed_solid[i] == dry.bed_solid_m3[i]:
                raise CouplingError('pool bed transfer has no representable native stock change')
        actual_bed = [dry.bedrock_m[i] + bed_solid[i] / base.cell_area_m2[i] for i in cells]
        stage, depths, geometry = settling._stage(actual_bed, [base.cell_area_m2[i] for i in cells], volume1)
        if stage is None or any(h <= 0 for h in depths):
            raise CouplingError('forced-pool wet footprint dries during a fixed-area trial')
        if abs(stage - row['predicted_stage_m']) > _height_tolerance(stage, row['predicted_stage_m']):
            raise CouplingError('continuous pool stage disagrees with water/solid/bed occupancy')
        weights = [a * h for a, h in zip([base.cell_area_m2[i] for i in cells], depths)]
        ws, wr = settling._phase_allocation(solved['liquid_m3'], weights)
        ss, sr = settling._phase_allocation(solved['suspended_solid_m3'], weights)
        for i, w, s in zip(cells, ws, ss): water[i], solid[i] = w, s
        pool_rows.append({'pool_id': pool['id'], 'cell_indices': cells, 'stage_m': stage,
                          'geometric_volume_residual_m3': geometry, 'continuous_phases': solved,
                          'phase_allocation_adjustment_m3': [wr, sr],
                          'spill_boundary': pool['spill'], 'mixture_export_m3_year': row['qo'],
                          'external_boundary_representation': row['boundary_representation'],
                          'minimum_depth_rate_bound_m_year': minimum_depth_rate,
                          'forced_drying_certificate': forced_certificate})
    updated = replace(dry, bed_solid_m3=tuple(bed_solid), liquid_m3=tuple(water), suspended_solid_m3=tuple(solid))
    routed_end = capture.route(updated, p['external_outlets'], p['connectivity'])
    if (any(n for n,d in routed_end['liquid_remainder_m3']) or routed_end['exported_liquid_remainder_m3'][0]):
        raise CouplingError('nonzero liquid remainder requires exact shoreline transport')
    end_spill_certificates = _check_displacement_routes(routed_end, p['external_outlets'], updated)
    final = replace(capture.from_route(updated, routed_end), time_years=state.time_years + dt)
    for row in pool_rows:
        if 'exact_endpoint_drying' in row:
            for i in row['cell_indices']:
                if (final.liquid_m3[i] != updated.liquid_m3[i]
                        or final.suspended_solid_m3[i] != updated.suspended_solid_m3[i]):
                    raise CouplingError('end routing changed the exact forced-drying snapshot')
    relief = shoreline.check_relief(base.bed_m, final.bed_m, channel['active_links'])
    exported_w = math.fsum([routed_start['exported_liquid_m3'], routed_end['exported_liquid_m3'],
                    channel['external_liquid_export_m3'], *[r['continuous_phases']['exported_liquid_m3'] for r in pool_rows]])
    exported_s = math.fsum([routed_start['exported_suspended_solid_m3'], routed_end['exported_suspended_solid_m3'],
                    channel['external_solid_export_m3'], *[r['continuous_phases']['exported_suspended_solid_m3'] for r in pool_rows]])
    imported_w = math.fsum((r*a + q)*dt for r,a,q in zip(p['runoff_m_year'],state.cell_area_m2,p['incoming_liquid_m3_year']))
    imported_s = math.fsum(q*dt for q in p['incoming_solid_m3_year'])
    dw = math.fsum([*final.liquid_m3, *(-v for v in state.liquid_m3)])
    ds = math.fsum([*final.bed_solid_m3,*final.suspended_solid_m3,
                   *(-v for v in state.bed_solid_m3),*(-v for v in state.suspended_solid_m3)])
    rock = math.fsum((b-a)*v for b,a,v in zip(state.bedrock_m,final.bedrock_m,state.cell_area_m2))
    roundoff = math.fsum(4*math.ulp(b)*a for b,a in zip(state.bedrock_m,state.cell_area_m2))
    ledgers = {'liquid': _check_ledger(math.fsum((dw,exported_w,-imported_w)), max(abs(dw),exported_w,imported_w),'liquid'),
               'solid': _check_ledger(math.fsum((ds,exported_s,-imported_s,-rock)),
                         max(abs(ds),exported_s,imported_s,rock),'solid',roundoff)}
    representation = _phase_representation_evidence(routed_start,routed_end)
    evidence.update(pool_intervals=pool_rows, final_routing=routed_end, post_pool_relief=relief,
                    end_bracket_spill_certificates=end_spill_certificates,
                    exported_liquid_m3=exported_w, exported_solid_m3=exported_s,
                    imported_liquid_m3=imported_w, imported_solid_m3=imported_s,
                    geometric_rock_loss_m3=rock, ledgers=ledgers,
                    phase_representation=representation)
    if time.monotonic() > deadline: raise CouplingError('coupled wall envelope exhausted after trial')
    return final, evidence


def _trial(state, dt, parameters, counts, deadline, *, finalise=False):
    try:
        return _trial_impl(state, dt, parameters, counts, deadline, finalise=finalise)
    except Exception as exc:
        # A rejected recomputation cannot advance its checkpoint. Carry the
        # measured failure costs and that exact checkpoint, never zeros/PASS.
        exc.coupling_counts = dict(counts)
        exc.coupling_time_years = state.time_years
        exc.coupling_trial_years = dt
        exc.last_valid_state = state.as_dict()
        raise


def advance(state, *, steps, dt_years, dx_m, dy_m, external_outlets, runoff_m_year,
            sediment_k_per_year, rock_k_per_year, cover_scale_m, settling_m_year,
            basin_settling_m_year, diffusivity_m2_year, connectivity=8,
            incoming_liquid_m3_year=None, incoming_solid_m3_year=None, wall_seconds=120.):
    if not isinstance(state, capture.CaptureState): raise CouplingError('R4 capture state required')
    shoreline._state(state)  # Reject unsupported durable phase residuals before work.
    if state.size > forced_drying.MAX_NATIVE_CELLS:
        raise CouplingError('native-cell count exceeds forced-event/driver hard bound')
    if type(steps) is not int or not 1 <= steps <= MAX_SUBSTEPS: raise CouplingError('bounded outer steps required')
    dt = capture.number(dt_years, 'outer dt', 0, True)
    outer_targets = [capture.number(state.time_years+(i+1)*dt, 'represented outer target',
                     state.time_years+i*dt, True) for i in range(steps)]
    wall = capture.number(wall_seconds, 'wall seconds', 0, True)
    if wall > 120: raise CouplingError('wall cap exceeds declared contract')
    deadline = time.monotonic() + wall; original = state
    parameters = {'dx_m': dx_m, 'dy_m': dy_m, 'external_outlets': list(external_outlets),
                  'connectivity': connectivity, 'cover_scale_m': cover_scale_m,
                  'settling_m_year': settling_m_year, 'basin_settling_m_year': basin_settling_m_year}
    for key, values in {'runoff_m_year': runoff_m_year, 'sediment_k_per_year': sediment_k_per_year,
                        'rock_k_per_year': rock_k_per_year, 'diffusivity_m2_year': diffusivity_m2_year,
                        'incoming_liquid_m3_year': [0.]*state.size if incoming_liquid_m3_year is None else incoming_liquid_m3_year,
                        'incoming_solid_m3_year': [0.]*state.size if incoming_solid_m3_year is None else incoming_solid_m3_year}.items():
        parameters[key] = capture.vector(values, state.size, key, 0)
    parameters['basin_settling_m_year'] = capture.number(basin_settling_m_year, 'basin velocity', 0)
    counts = {'trial_calls': 0, 'trial_cell_evaluations': 0, 'scalar_rhs_evaluations': 0,
              'closed_event_solver_calls': 0, 'accepted_substeps': 0, 'rejected_proposals': 0}
    rows, events = [], []
    for outer in range(steps):
        target = outer_targets[outer]
        while state.time_years < target:
            remaining = target-state.time_years
            trial_dt = remaining; bracket = None
            while True:
                if counts['rejected_proposals'] >= MAX_REJECTS or counts['accepted_substeps'] >= MAX_SUBSTEPS:
                    raise CouplingError('coupling retry/substep envelope exhausted', counts=counts)
                try:
                    final, report = _trial(state, trial_dt, parameters, counts, deadline)
                except shoreline.ShorelineError as exc:
                    if 'relative link relief' not in str(exc): raise
                    counts['rejected_proposals'] += 1; trial_dt /= 2
                    if state.time_years + trial_dt == state.time_years: raise CouplingError('no representable time progress') from exc
                    continue
                if report['contacts']:
                    low, high = 0., trial_dt
                    for bisect in range(MAX_BISECTIONS):
                        if counts['rejected_proposals'] >= MAX_REJECTS:
                            raise CouplingError('event bracket rejection envelope exhausted', counts=dict(counts))
                        mid = low + (high-low)/2
                        if mid in (low, high): raise CouplingError('event time bracket cannot progress')
                        _, probe = _trial(state, mid, parameters, counts, deadline)
                        counts['rejected_proposals'] += 1
                        if probe['contacts']: high = mid
                        else: low = mid
                        tolerance = EVENT_ATOL_YEARS + EVENT_RTOL*trial_dt
                        if high-low <= tolerance:
                            _, crossed = _trial(state, high, parameters, counts, deadline)
                            if all(r['overshoot_m'] <= _height_tolerance(r['stage_m']) for r in crossed['contacts']):
                                bracket = {'lower_years': state.time_years+low, 'upper_years': state.time_years+high,
                                           'width_years': high-low, 'bisections': bisect+1, 'contacts': crossed['contacts']}
                                trial_dt = high
                                final, report = _trial(state, trial_dt, parameters, counts, deadline, finalise=True)
                                break
                    else: raise CouplingError('first wetting/spill bracket budget exhausted')
                # Recompute from the unchanged checkpoint. No double application.
                repeat, repeat_report = _trial(state, trial_dt, parameters, counts, deadline, finalise=bracket is not None)
                if repeat != final or repeat_report != report:
                    raise CouplingError('fixed-coefficient trial replay did not stabilise')
                break
            if final is None or final.time_years <= state.time_years:
                raise CouplingError('coupling failed to make represented positive time progress')
            for event in report['network']['zero_time_events']:
                events.append({**event, 'absolute_time_years': state.time_years})
            for pool_row in report['pool_intervals']:
                if 'exact_endpoint_drying' in pool_row:
                    events.append({'kind':'EXACT_FORCED_DRYING_ENDPOINT',
                        'absolute_time_years':final.time_years,
                        'pool_id':pool_row['pool_id'],**pool_row['exact_endpoint_drying']})
                for event in pool_row.get('closed_event_settling', {}).get('events', []):
                    events.append({'kind':'CLOSED_POOL_INTERNAL_EVENT', **event,
                                   'absolute_time_years':state.time_years+event['time_years']})
            if bracket: events.append({'kind': 'BRACKETED_NATIVE_CONTACT', **bracket})
            rows.append({'outer_step': outer, 'from_time_years': state.time_years,
                         'to_time_years': final.time_years, 'event_bracket': bracket,
                         'stable_recomputations': 2, **report})
            state = final; counts['accepted_substeps'] += 1
    return state, {'status': 'BOUNDED_CONTINUOUS_SHORELINE_REFERENCE', 'steps': rows, 'events': events,
                   'counts': counts, 'whole_interval_completed': True,
                   'direct_exterior_spill_only': True, 'physical_acceptance': False,
                   'production_authorised': False, 'fresh_optimisation_speedup_established': False}
