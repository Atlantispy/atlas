"""Independent extensive-account readback; never reruns the nonlinear solver."""
import math


def _close(actual, expected, tolerance, label):
    if not math.isfinite(actual) or not math.isfinite(expected) or abs(actual-expected) > tolerance:
        raise ValueError('coupled soil account differs: '+label)


def event(model, forcing, result, controls):
    if result.get('status') != 'MODELLED':
        raise ValueError('complete coupled soil event required for final account audit')
    initial, final, ledger = result['initial_state'], result['final_state'], result['ledger']
    n, constants = len(model['layers']), model['constants']
    rho = constants['water_density_kg_m3']
    cw, ci = constants['water_heat_capacity_j_kg_k'], constants['ice_heat_capacity_j_kg_k']
    latent, tm = constants['latent_heat_j_kg'], constants['melting_temperature_k']
    wt, et = controls['water_atol_m'], controls['energy_atol_j_m2']
    for state in (initial, final):
        for key in ('head_m', 'total_water', 'temperature_k', 'temperature_offset_k', 'liquid_water',
                    'ice_water', 'enthalpy_j_m2'):
            if len(state[key]) != n:
                raise ValueError('coupled soil account layer inventory differs')
        for i, layer in enumerate(model['layers']):
            theta, liquid, ice, temperature = (state[k][i] for k in
                ('total_water', 'liquid_water', 'ice_water', 'temperature_k'))
            if not layer['theta_r'] <= liquid <= theta <= layer['theta_s'] or ice < 0 or temperature <= 0:
                raise ValueError('coupled soil account has invalid phase/temperature')
            offset = state['temperature_offset_k'][i]
            _close(temperature, tm+offset, 0., 'readable temperature and retained offset')
            _close(theta, liquid+ice, 32*math.ulp(max(1., abs(theta))), 'liquid plus ice')
            capacity = layer['dry_heat_capacity_j_m3_k'] + rho*(cw*liquid+ci*ice)
            energy = layer['thickness_m']*(capacity*offset+rho*latent*liquid)
            _close(state['enthalpy_j_m2'][i], energy, et, 'phase enthalpy')
    for name in ('face_water_m', 'face_downward_m', 'face_upward_m',
                 'face_conductive_energy_j_m2', 'face_advective_energy_j_m2'):
        if len(ledger[name]) != n+1:
            raise ValueError('coupled soil account face inventory differs')
    if [row['layer_id'] for row in ledger['layers']] != [row['layer_id'] for row in model['layers']]:
        raise ValueError('coupled soil ledger layer order differs')
    q = ledger['face_water_m']
    energy_faces = [a+b for a, b in zip(ledger['face_conductive_energy_j_m2'],
                                       ledger['face_advective_energy_j_m2'])]
    water_residuals, energy_residuals = [], []
    for i, layer in enumerate(model['layers']):
        row, dz = ledger['layers'][i], layer['thickness_m']
        if row['thickness_m'] != dz:
            raise ValueError('coupled soil ledger layer thickness differs')
        initial_water, final_water = initial['total_water'][i]*dz, final['total_water'][i]*dz
        _close(row['initial_water_m'], initial_water, wt, 'initial layer water')
        _close(row['final_water_m'], final_water, wt, 'final layer water')
        _close(row['water_change_m'], final_water-initial_water, wt, 'layer water change')
        _close(row['enthalpy_change_j_m2'], final['enthalpy_j_m2'][i]-initial['enthalpy_j_m2'][i], et, 'layer energy change')
        w = final_water-initial_water-q[i]+q[i+1]+row['root_withdrawal_m']
        e = final['enthalpy_j_m2'][i]-initial['enthalpy_j_m2'][i]-energy_faces[i]+energy_faces[i+1]+row['root_enthalpy_j_m2']
        _close(w, 0, wt, 'layer water balance')
        _close(e, 0, et, 'layer energy balance')
        _close(row['water_residual_m'], w, wt, 'reported layer water residual')
        _close(row['energy_residual_j_m2'], e, et, 'reported layer energy residual')
        water_residuals.append(w); energy_residuals.append(e)
    wr, er = math.fsum(water_residuals), math.fsum(energy_residuals)
    _close(wr, 0, wt, 'column water balance')
    _close(er, 0, et, 'column energy balance')
    for i, (down, up) in enumerate(zip(ledger['face_downward_m'], ledger['face_upward_m'])):
        if down < 0 or up < 0:
            raise ValueError('negative gross soil transfer')
        _close(down-up, q[i], wt, 'gross/signed face water')
    rain = forcing['duration_s']*forcing['surface_water_flux_m_s']
    _close(ledger['surface_input_m'], rain, wt, 'once-only supplied surface water')
    _close(ledger['surface_runoff_m'], rain-q[0], wt, 'surface input/runoff account')
    water0 = math.fsum(state_water*layer['thickness_m'] for state_water, layer in
                       zip(initial['total_water'], model['layers']))
    water1 = math.fsum(state_water*layer['thickness_m'] for state_water, layer in
                       zip(final['total_water'], model['layers']))
    energy0, energy1 = math.fsum(initial['enthalpy_j_m2']), math.fsum(final['enthalpy_j_m2'])
    expected_water = {'initial_storage_m': water0, 'final_storage_m': water1,
                      'storage_change_m': water1-water0,
                      'root_withdrawal_m': math.fsum(row['root_withdrawal_m'] for row in ledger['layers']),
                      'water_residual_m': wr, 'infiltration_m': ledger['face_downward_m'][0],
                      'surface_exfiltration_m': ledger['face_upward_m'][0],
                      'bottom_downward_m': ledger['face_downward_m'][-1],
                      'bottom_upward_m': ledger['face_upward_m'][-1],
                      'rain_excess_runoff_m': rain-ledger['face_downward_m'][0]}
    for key, expected in expected_water.items():
        _close(ledger[key], expected, wt, key)
    representation = rain-ledger['face_downward_m'][0]-ledger['rain_excess_runoff_m']
    _close(representation, 0, wt, 'surface input representation')
    _close(ledger['surface_input_representation_residual_m'], representation, wt, 'reported surface input representation')
    rain_h = rho*(latent+cw*(forcing['surface_water_temperature_k']-tm))
    expected_energy = {'initial_enthalpy_j_m2': energy0, 'final_enthalpy_j_m2': energy1,
                       'enthalpy_change_j_m2': energy1-energy0,
                       'root_enthalpy_j_m2': math.fsum(row['root_enthalpy_j_m2'] for row in ledger['layers']),
                       'energy_residual_j_m2': er,
                       'rain_excess_enthalpy_j_m2': expected_water['rain_excess_runoff_m']*rain_h}
    for key, expected in expected_energy.items():
        _close(ledger[key], expected, et, key)
    _close(ledger['elapsed_s'], forcing['duration_s'], 16*math.ulp(max(1., forcing['duration_s'])), 'event coverage')
    _close(final['elapsed_seconds'], initial['elapsed_seconds']+forcing['duration_s'],
           16*math.ulp(max(1., final['elapsed_seconds'])), 'event state clock')
    return {'scope': 'INDEPENDENT_EXTENSIVE_ACCOUNTS_NOT_A_SPATIAL_ACCURACY_CERTIFICATE',
            'water_residual_m': wr, 'energy_residual_j_m2': er}
