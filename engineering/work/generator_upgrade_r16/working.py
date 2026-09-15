"""Compile Physical Frame's pinned, explicitly hypothetical finite-fold model.

These authored values are not measured Diadem geology or universal rock ranges.
No historical atlas or active-world terrain is consumed or silently warped.
"""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path

from . import regional, provenance as p
from .structure import FiniteMap

OWNER = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-5/02_Working_Files/Physical_Inputs_R16')
CONTRACT = OWNER/'REGIONAL_PHYSICS_CONTRACT_R1.md'
CONTRACT_SHA = '6674349237a151175493baf0261b46a7e759cb77d3a0632596e39389dc271d5f'
RECIPE = OWNER/'REGIONAL_WORKING_RECIPE_R1.json'
RECIPE_SHA = '7859d3b2d3cebd71cb124cb91e0152d4d7401cef3793ef1ed2f29ac6b3de5e17'
STATUS = 'WORKING NON-CANON'
EVIDENCE = 'GEO-R16-REGIONAL-PHYSICS-2026-09-14/result R1; authored finite kinematic scenario, not actual Diadem calibration'
CONTACTS = (-5000, -1000, 0, 1000, 1300)
# ID, grain density [kg/m3], porosity, K_ref [1/year]. Owner sections4-5.
MATERIALS = (('R16_CRYSTALLINE', 2700, '1/50', 1e-5),
             ('R16_WEAK_SEDIMENTARY', 2650, '1/5', 1e-4),
             ('R16_CARBONATE', 2750, '2/25', 2e-5),
             ('R16_BASALT', 2900, '1/25', 1e-5))


def _read(path, expected):
    with path.open('rb') as stream:
        raw = stream.read(262145)
    if len(raw) > 262144 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Physical Frame method/input source changed; no repin')
    return raw


def owner_recipe():
    _read(CONTRACT, CONTRACT_SHA)
    return json.loads(_read(RECIPE, RECIPE_SHA))


def model():
    return FiniteMap(F(9, 10), (1016000, 808000), 0, 1200, 32000, F(1, 100))


def compile_recipe(supports=None):
    """Evaluate the analytic field at supplied centres, not between three anchors."""
    recipe = owner_recipe()
    chosen = deepcopy(recipe['supports'] if supports is None else supports)
    if type(chosen) is not dict or not 1 <= len(chosen) <= 32:
        raise ValueError('one to32 explicitly located representative supports required')
    mapping, rows, events = model(), {}, []
    for key, support in chosen.items():
        regional.contract.text(key)
        if type(support) is not dict or set(support) not in (
                {'xy_m', 'area_m2'}, {'xy_m', 'area_m2', 'basal_elevation_m'}):
            raise ValueError('explicit XY/area support required; base is derived from the model')
        if type(support['xy_m']) is not list or len(support['xy_m']) != 2:
            raise ValueError('explicit metre XY support required')
        x, y = [regional._signed(v) for v in support['xy_m']]
        if not -16000 <= x-1016000 <= 16000 or not -8000 <= y-808000 <= 8000:
            raise ValueError('support outside the owner model definition domain')
        area = regional._signed(support['area_m2'])
        row = mapping.column(x, y, CONTACTS, 1000, area)
        rows[key] = row
        initial_base = F(row['pre_contacts_m'][0])-F(row['displacement_m'])
        if 'basal_elevation_m' in support and F(support['basal_elevation_m']) != initial_base:
            raise ValueError('supplied initial base conflicts with reference contact map')
        support.update(xy_m=[str(x), str(y)], area_m2=str(area), basal_elevation_m=str(initial_base))
        def event(identity, kind, **payload):
            return {'event_id': key+'-'+identity, 'cell_id': key, 'kind': kind,
                    'evidence': EVIDENCE, 'source_status': STATUS, **payload}
        contacts = [F(v) for v in row['pre_contacts_m']]
        for i, (material, density, phi, _) in enumerate(MATERIALS):
            events.append(event('emplace-'+str(i+1), 'emplace', layer={
                'material_id': material, 'grain_density_kg_m3': str(density),
                'porosity': phi, 'phase': 'bedrock', 'thickness_m': str(contacts[i+1]-contacts[i]),
                'evidence': EVIDENCE+'; reference-preimage stock, not mass created by shortening'}))
        events.append(event('fold', 'translate_base', displacement_m=row['displacement_m']))
        if F(row['final_top_m']) < contacts[-1]:
            events.append(event('planation', 'strip_to_elevation', surface_m=row['final_top_m']))
    recipe['supports'], recipe['events'] = chosen, events
    return recipe, rows


def build(supports=None):
    """Construct the working model with its actual shortening/preimage receipt."""
    recipe, analytic = compile_recipe(supports)
    result = regional.build(recipe)
    science = result['scientific']
    for key, row in analytic.items():
        actual = science['stratigraphy'][key]
        if actual['surface_m'] != row['final_top_m'] or F(actual['bottom_to_top'][0]['bottom_m']) != F(row['final_base_m']):
            raise ArithmeticError('native geological construction differs from analytic map')
        expected = [(mid, F(thickness)) for (mid, *_), thickness in zip(MATERIALS, row['retained_thicknesses_m']) if F(thickness)]
        received = [(v['material_id'], F(v['top_m'])-F(v['bottom_m'])) for v in actual['bottom_to_top']]
        if received != expected:
            raise ArithmeticError('native layers/exposure differ from analytic stratigraphy')
    science['structural_model'] = {
        'method': 'OWNER_PRESCRIBED_VOLUME_PRESERVING_PLANE_STRAIN_THEN_FOLD_AND_PLANATION',
        'parameters': {'shortening_ratio': '9/10', 'centre_m': [1016000, 808000],
            'z0_m': 0, 'amplitude_m': 1200, 'wavelength_m': 32000, 'tilt': '1/100'},
        'reference_contacts_m': list(CONTACTS), 'cap_m': 1000,
        'owner_recipe_sha256': RECIPE_SHA, 'analytic_columns': analytic,
        'geological_duration_required': False, 'plate_velocities_required_for_this_snapshot': False,
        'calibration': 'AUTHOR_SELECTED_WORKING_NON_CANON_SCENARIO',
        'support_meaning': 'centre-sampled prismatic representatives, not a mesh or area-averaged raster'}
    result['execution']['scientific_sha256'] = p.sha(science)
    p.verify(result['execution']['identity'])
    return result


def erosion_laws():
    """Owner's bedrock laws only; sediment parameters are NOT inferred."""
    _read(CONTRACT, CONTRACT_SHA)
    _, native = p.backend()
    def prop(name, value, unit):
        return native.PhysicalProperty(name, value, unit, EVIDENCE+'; contract section4', STATUS)
    return [native.ErosionLaw(mid, 'bedrock',
        prop('erosion_coefficient_at_reference_runoff', k, '1/year'),
        prop('reference_runoff', 1., 'm/year')) for mid, _, _, k in MATERIALS]
