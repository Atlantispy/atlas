"""Read only the explicitly authorised Water/Physical working decisions."""
import hashlib
import json
from pathlib import Path
from . import substrate

ROOT = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-4/02_Working_Files/Coastal_Water_R19')
PINS = {'METHOD_R2.json': '3635cc07535b90b1e5b0379fe3fbf582b05a300b207271799c493c314a8b8939',
        'WORKING_SCENARIO_R2.json': '584d7f659b8800a6a28f59f00908d826fc58db40371610b4b2965a36c2ca4199',
        'SOURCES_R1.json': 'becbc983ca85dd59d25f2671bf84f77413c9d3584932b915acc7f023aeff6fa5'}


def read(path, sha):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('coastal owner source changed: '+str(path))
    return json.loads(raw)


def inputs():
    method, scenario, _ = (read(ROOT/name, PINS[name]) for name in PINS)
    physical = substrate.decision()
    if (method['status'] != 'WORKING NON-CANON' or scenario['status'] != 'WORKING NON-CANON'
            or method['decision'] != 'AUTHORISE_DEFINED_WORKING_METHOD_FOR_BOUNDED_IMPLEMENTATION'):
        raise ValueError('explicit owner working coastal method required')
    if scenario['parameters']['fresh_mobile_deposit_porosity'] != physical['sediment_material_default']['fresh_deposit_porosity']:
        raise ValueError('Water/Physical deposit porosity decisions differ')
    return method, scenario


def binding():
    inputs()
    return {'water': {str(ROOT/name): sha for name, sha in PINS.items()},
            'physical': {str(substrate.INPUT): substrate.INPUT_SHA},
            'status': 'WORKING NON-CANON', 'sea_vertical_registration': 'NOT_ASSERTED'}


def parameters():
    _, scenario = inputs()
    return dict(scenario['parameters'],
        water_density_kg_m3=scenario['constants']['water_density_kg_m3'],
        dilute_suspended_solid_volume_fraction_max=scenario['numerics']['dilute_suspended_solid_volume_fraction_max'])


def sources():
    """Verify recovered source controls without inferring a spatial/datum join."""
    data = read(ROOT/'SOURCES_R1.json', PINS['SOURCES_R1.json'])
    for row in data['local']:
        root = Path(data['roots'][row['root']]).resolve()
        path = (root/row['path']).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('recovered coastal source changed: '+row['id'])
    return data
