"""Physical-owned coastal contrast and finite subgrid stock partition.

Partitioning changes support area, never the stock density or contact sequence.
Any profile displacement must be supplied separately as a labelled scenario;
neither the historical Sea zero nor the R18 root zero determines that offset.
"""
from dataclasses import replace
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path

from work.generator_upgrade_r16 import columns
from work.generator_upgrade_r18 import composite

INPUT = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-5/02_Working_Files/Physical_Inputs_R19/COASTAL_PHYSICAL_INPUTS_R1.json')
INPUT_SHA = 'a7f5a85eac707a8836da7a07235df4048b1035f80307e211c5de312fb2dcc02e'


def decision():
    raw = INPUT.read_bytes()
    if hashlib.sha256(raw).hexdigest() != INPUT_SHA:
        raise ValueError('Physical R19 input changed; no automatic repin')
    data = json.loads(raw)
    if (data['decision'] != 'READY_FOR_AUTHORISED_BOUNDED_IMPLEMENTATION'
            or data['source_status'] != 'WORKING NON-CANON'
            or data['vertical_and_geometry']['r18_to_sea_registration'] != 'NOT_ASSERTED'):
        raise ValueError('explicit bounded Physical working decision required')
    return data


def bedrock_contrast(material_id, palette):
    """Dimensionless owner hypothesis, NOT a coastal erosion coefficient."""
    descriptor = composite._validated(material_id, palette)
    if descriptor['phase'] != 'bedrock':
        raise ValueError('bedrock contrast cannot substitute for a mobile-material law')
    reference = decision()['substrate_and_materials']['bounded_coastal_contrast']['reference_k_per_year']
    return columns._q(descriptor['k_per_year'], 'bound modified K', nonnegative=True) / F(str(reference))


def partition(column, areas_m2):
    """Disjoint complete area partition of one actual finite native column.

Returns child columns and an exact stock receipt. All children keep the same
base and contacts. No subgrid cliff shape or independent source resolution is
asserted. A caller must include an inactive remainder if only a strip evolves.
"""
    if type(areas_m2) is not dict or not 1 <= len(areas_m2) <= 32:
        raise ValueError('bounded explicit complete area partition required')
    if any(type(key) is not str or not key.strip() for key in areas_m2):
        raise ValueError('named subgrid supports required')
    areas = {key: columns._q(value, 'subgrid area', positive=True)
             for key, value in areas_m2.items()}
    if sum(areas.values(), F()) != column.area_m2:
        raise ValueError('subgrid areas must partition the parent exactly; no stock duplication')
    children = {}
    for key, area in sorted(areas.items()):
        fraction = area / column.area_m2
        children[key] = replace(column, area_m2=area,
            layers=tuple(replace(layer, mass_kg=columns._q(layer.mass_kg*fraction, 'partitioned finite mass', positive=True)) for layer in column.layers))
        if children[key].surface_m != column.surface_m:
            raise ArithmeticError('partition changed layer geometry')
    for index, layer in enumerate(column.layers):
        if sum((child.layers[index].mass_kg for child in children.values()), F()) != layer.mass_kg:
            raise ArithmeticError('subgrid material partition does not close')
    return children, {'schema': 'diadem.finite-coastal-subgrid-partition.r19',
        'parent_area_m2': str(column.area_m2),
        'child_areas_m2': {key: str(area) for key, area in sorted(areas.items())},
        'parent_mass_kg': str(column.mass_kg), 'mass_residual_kg': '0',
        'solid_volume_residual_m3': '0', 'area_residual_m2': '0',
        'geometry_scope': 'DISJOINT_EQUAL_PROFILE_PRISMS_NOT_NEW_RESOLVED_COASTAL_GEOMETRY'}


def strip_depth(column, depth_m):
    """Apply a caller-computed lowering to finite exposed contacts, top first.

No erosion rate is supplied by this operation. Returned parcels retain their
original density, porosity, phase and evidence; the receiver owns conversion
to a fresh mobile deposit and any associated pore-water transfer.
"""
    demand = columns._q(depth_m, 'requested lowering', nonnegative=True)*column.area_m2
    remaining = demand
    layers, removed = list(column.layers), []
    while remaining and layers:
        layer = layers.pop()
        volume = min(remaining, layer.bulk_volume_m3)
        mass = columns._q(volume*layer.grain_density_kg_m3*(1-layer.porosity), 'finite removed mass')
        removed.append(replace(layer, mass_kg=mass))
        if mass < layer.mass_kg:
            layers.append(replace(layer, mass_kg=layer.mass_kg-mass))
        remaining -= volume
    after = replace(column, layers=tuple(layers))
    if column.mass_kg-after.mass_kg != sum((layer.mass_kg for layer in removed), F()):
        raise ArithmeticError('coastal finite removal mass does not close')
    if (column.surface_m-after.surface_m)*column.area_m2 != demand-remaining:
        raise ArithmeticError('coastal finite removal geometry does not close')
    return after, tuple(removed), remaining/column.area_m2
