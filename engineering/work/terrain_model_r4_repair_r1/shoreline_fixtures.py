"""Unaltered R2 capture regression and separately declared R4 water initialisation."""
from copy import deepcopy
import hashlib
import math
import types

from capture import CaptureState
from r4_io import io, verify_dependencies

R2_FIXTURES_SHA256 = '5a1e685b0ac0b2fb2165345696e7f09f09a0db88a97d8ada0b1b322e43d3514a'


def retained_recipe():
    verify_dependencies()
    path = io.HERE / 'fixtures.py'
    raw = io.read_bytes(path)
    if hashlib.sha256(raw).hexdigest() != R2_FIXTURES_SHA256:
        raise ValueError('frozen R2 fixture source changed')
    module = types.ModuleType('_r4_reviewed_r2_shoreline_fixtures')
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module.near_flat_capture_regression()


def near_flat():
    """Apply only the original soil prefix, once. No coupled generation here."""
    original = retained_recipe()
    prefix = deepcopy(original)
    prefix['operations'] = original['operations'][:1]
    if len(original['operations']) != 2 or prefix['operations'][0]['kind'] != 'soil':
        raise ValueError('retained soil/channel sequence changed')
    prepared = io.execute(prefix)
    state = prepared['state']
    if any(state['porosity']) or prepared['auxiliary_layers'] or any(
            t['regolith_after_kg'] for t in prepared['operations'][0]['transfers']):
        raise ValueError('R4 adapter cannot silently flatten a porous or immobile layer')
    if state['rock_density_kg_m3'] != state['sediment_density_kg_m3']:
        raise ValueError('R4 adapter requires equal constant mineral density')
    grid = original['grid']; n = grid['rows'] * grid['cols']
    initial = CaptureState((grid['rows'], grid['cols']), (grid['dx_m'] * grid['dy_m'],) * n,
                           tuple(state['bedrock_m']), tuple(state['mobile_solid_m3']),
                           (0.,) * n, (0.,) * n, state['rock_density_kg_m3'])
    dissolved = math.fsum(t['dissolved_rock_produced_kg'] for t in prepared['operations'][0]['transfers'])
    return {'initial_state': initial, 'forcing': deepcopy(original['operations'][1]),
            'grid': deepcopy(grid), 'original_recipe': original,
            'soil_prefix_result': prepared, 'soil_dissolved_rock_export_kg': dissolved,
            'source_sha256': R2_FIXTURES_SHA256,
            'coupled_duration_years': original['operations'][1]['steps'] * original['operations'][1]['dt_years'],
            'basin_settling_m_year': 5.,
            'basin_settling_status': 'NEW SYNTHETIC supplied reservoir velocity, not inferred from the channel value',
            'water_initial_status': 'NEW SYNTHETIC W=S=0; not recovered Diadem hydrology',
            'physical_acceptance': False, 'production_authorised': False}
