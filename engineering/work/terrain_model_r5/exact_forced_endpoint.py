"""Independent rational certificate for the narrow EXACT_ENDPOINT_DESIGN path."""
from fractions import Fraction as F
import math

import event_settling


def ratio(value):
    return {'numerator': value.numerator, 'denominator': value.denominator}


def represented(value, label):
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(label+' is not representable') from exc
    if not math.isfinite(result) or F(result) != value:
        raise ValueError(label+' is not exactly representable')
    return result


def certify(state, pool, row, tie, velocity, duration, detected):
    """Return None outside the exact branch; never accept an error-band sign."""
    if detected['status'] not in ('BLOCKED_NUMERICAL_EVENT_SIGN', 'FIRST_DRYING_EVENT'):
        return None
    if tie['excluded_zero_depth_right_limit_cell_indices']:
        return None
    cells = pool['cell_indices']
    w, s = F(pool['liquid_m3']), F(pool['suspended_solid_m3'])
    area, t, v = F(row['area_m2']), F(duration), F(velocity)
    if t <= 0 or area <= 0 or w <= 0 or s <= 0:
        return None
    if (sum((F(state.liquid_m3[i]) for i in cells), F()) != w
            or sum((F(state.suspended_solid_m3[i]) for i in cells), F()) != s
            or sum((F(state.cell_area_m2[i]) for i in cells), F()) != area):
        return None
    if any(n for n, d in getattr(state, 'liquid_remainder_m3', ())):
        return None
    qw, qs, qo = (F(row[name]) for name in ('qw', 'qs', 'qo'))
    c, k, q = s/(w+s), v*area, qw+qs
    if qs-(q+k)*c+k*c*c != 0:
        return None
    depth = F(tie['exact_depth']['numerator'], tie['exact_depth']['denominator'])
    slope = (q-qo)/area-v*c
    if slope >= 0 or depth+slope*t != 0:
        return None
    represented(F(state.time_years)+t, 'absolute endpoint time')
    expected = {'liquid_m3': w+qw*t-qo*(1-c)*t,
                'suspended_solid_m3': s+qs*t-qo*c*t-k*c*t,
                'deposited_solid_m3': k*c*t,
                'exported_liquid_m3': qo*(1-c)*t,
                'exported_suspended_solid_m3': qo*c*t,
                'imported_liquid_m3': qw*t, 'imported_suspended_solid_m3': qs*t}
    if expected['liquid_m3'] <= 0 or any(value < 0 for value in expected.values()):
        return None
    endpoints = [p for p in detected['probes'] if p['status'] == 'PASS' and F(p['time_years']) == t]
    if len(endpoints) != 1:
        raise ValueError('exact endpoint requires one counted scalar probe')
    solved = endpoints[0]['scalar_result']
    for name, value in expected.items():
        if solved[name] != represented(value, name):
            raise ValueError('numerical endpoint disagrees with exact '+name)
    eta = F(pool['exact_stage_m']['numerator'], pool['exact_stage_m']['denominator'])+(q-qo)*t/area
    return {'status': 'EXACT_CONSTANT_CONCENTRATION_ENDPOINT',
            'proof': 'RATIONAL_EQUILIBRIUM_AND_STRICTLY_DECREASING_AFFINE_DEPTH',
            'concentration': ratio(c), 'depth_rate_m_year': ratio(slope),
            'relative_time_years': duration, 'stage_m': represented(eta, 'endpoint stage'),
            'exact_stage_m': ratio(eta), 'scalar_result': solved,
            'exact_phase_and_transfer_m3': {key: ratio(value) for key, value in expected.items()},
            'dried_cells': list(tie['cell_indices']), 'post_event_hydraulics_solved': False}


def reconstruct(state, cells, area, certificate, connectivity, parameters):
    """Produce only exactly representable native endpoint stocks and geometry."""
    phase = {key: F(value['numerator'], value['denominator'])
             for key, value in certificate['exact_phase_and_transfer_m3'].items()}
    stage = F(certificate['exact_stage_m']['numerator'], certificate['exact_stage_m']['denominator'])
    rise = phase['deposited_solid_m3']/F(area)
    bed_solid, weights = [], []
    for i in cells:
        a = F(state.cell_area_m2[i])
        stock = represented(F(state.bed_solid_m3[i])+rise*a, 'native deposited stock')
        actual_bed = state.bedrock_m[i]+stock/state.cell_area_m2[i]
        if F(actual_bed)-F(state.bed_m[i]) != rise:
            raise ValueError('endpoint tie is not representable in durable bed geometry')
        if F(actual_bed) > stage:
            raise ValueError('exact endpoint cannot clip a negative native depth')
        bed_solid.append(stock)
        weights.append((stage-F(actual_bed))*a)
    dried = [i for i, weight in zip(cells, weights) if weight == 0]
    if dried != certificate['dried_cells']:
        raise ValueError('durable endpoint does not preserve the complete exact drying tie')
    volume = phase['liquid_m3']+phase['suspended_solid_m3']
    if sum(weights, F()) != volume:
        raise ValueError('exact endpoint phase volume differs from native geometry')
    water = [represented(phase['liquid_m3']*weight/volume, 'native liquid') for weight in weights]
    solid = [represented(phase['suspended_solid_m3']*weight/volume, 'native suspension') for weight in weights]
    wet = [i for i, weight in zip(cells, weights) if weight > 0]
    daughters = event_settling.wet_components(wet, state.shape, connectivity)
    values = {i: (w, s) for i, w, s in zip(cells, water, solid)}
    record = {key: value for key, value in certificate.items() if key != 'scalar_result'}
    record.update(parent_cells=list(cells), daughters=[{
        'cell_indices': group,
        'liquid_m3': represented(sum((F(values[i][0]) for i in group), F()), 'daughter liquid'),
        'suspended_solid_m3': represented(sum((F(values[i][1]) for i in group), F()), 'daughter suspension')}
        for group in daughters], split=len(daughters) > 1,
        native_forcing=[{'cell_index': i, 'runoff_m_year': parameters['runoff_m_year'][i],
                         'incoming_liquid_m3_year': parameters['incoming_liquid_m3_year'][i],
                         'incoming_solid_m3_year': parameters['incoming_solid_m3_year'][i]}
                        for i in cells],
        forcing_allocation='NATIVE_SOURCE_RECORDS_RETAINED_NO_POST_EVENT_FLUX_INFERRED')
    return bed_solid, water, solid, record
