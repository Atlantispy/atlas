"""Supplied coeval facies in one finite bulk compartment, not stacked strata.

The caller supplies normalised bulk-volume weights and the effective erosion
coefficient. This module chooses no K mixing law or rock parameters. Projection
applies only to congruent, well-mixed transfers: sorting, selective weathering
and component-selective erosion require a different explicit model.
"""
import hashlib
import json

from work.generator_upgrade_r16 import columns


SCHEMA = 'diadem.congruent-composite-material.r18'
SCOPE = 'SHARED_BULK_COMPARTMENT_CONGRUENT_WELL_MIXED_TRANSFERS_ONLY'
INPUT = {'unit_id', 'bulk_weight', 'grain_density_kg_m3', 'porosity'}
COMPONENT = INPUT | {'mass_fraction', 'solid_fraction'}
DESCRIPTOR = {'schema', 'material_id', 'grain_density_kg_m3', 'porosity',
              'k_per_year', 'phase', 'evidence', 'constituents',
              'omitted_zero_weight_unit_ids', 'scope'}
PHASES = {'bedrock', 'immobile_regolith', 'mobile_sediment', 'organic'}
MAX_CONSTITUENTS = 64


def _exact(value, keys):
    if type(value) is not dict or set(value) != keys:
        raise ValueError('exact composite fields required')


def _label(value, name):
    columns._text(value, name)
    if value in {'UNKNOWN', 'INCOMPLETE', 'CONFLICT'}:
        raise ValueError('resolved '+name+' required')
    return value


def create(constituents, k_per_year, *, phase, evidence):
    """Return a canonical plain-JSON descriptor with exact rational strings.

Each constituent has exactly unit_id, bulk_weight, grain_density_kg_m3 and
porosity. Nonnegative weights must sum exactly to one; zeros are explicitly
reported and omitted from the material identity. Phase and evidence are required.
Identity binds sorted active definitions, exact weights, supplied K and phase,
but not evidence, location, area, thickness or amount. No renormalisation occurs.
"""
    if type(constituents) is not list or not 1 <= len(constituents) <= MAX_CONSTITUENTS:
        raise ValueError('1..64 explicit composite constituents required')
    if type(phase) is not str or phase not in PHASES:
        raise ValueError('explicit supported composite phase required')
    _label(evidence, 'composite evidence')
    k = columns._q(k_per_year, 'supplied composite K', nonnegative=True)
    definitions, seen, omitted = [], set(), []
    total_weight = columns._q(0, 'composite weight')
    for row in constituents:
        _exact(row, INPUT)
        unit = _label(row['unit_id'], 'constituent unit identity')
        if unit in seen:
            raise ValueError('duplicate composite constituent unit identity')
        seen.add(unit)
        weight = columns._q(row['bulk_weight'], 'bulk constituent weight', nonnegative=True)
        density = columns._q(row['grain_density_kg_m3'], 'constituent grain density', positive=True)
        phi = columns._q(row['porosity'], 'constituent porosity', nonnegative=True)
        if phi >= 1:
            raise ValueError('constituent porosity must be below one')
        total_weight = columns._q(total_weight+weight, 'total bulk weight')
        if weight == 0:
            omitted.append(unit)
        else:
            definitions.append({'unit_id': unit, 'bulk_weight': str(weight),
                                'grain_density_kg_m3': str(density), 'porosity': str(phi)})
    if total_weight != 1:
        raise ValueError('composite bulk weights must sum exactly to one')
    definitions.sort(key=lambda row: row['unit_id'])
    solid_weights, mass_weights, pore_weights = [], [], []
    for row in definitions:
        weight = columns._q(row['bulk_weight'], 'bulk constituent weight')
        phi = columns._q(row['porosity'], 'constituent porosity')
        density = columns._q(row['grain_density_kg_m3'], 'constituent grain density')
        solid = columns._q(weight*columns._q(1-phi, 'constituent solid fraction'), 'bulk solid weight')
        solid_weights.append(solid)
        mass_weights.append(columns._q(solid*density, 'bulk mass weight'))
        pore_weights.append(columns._q(weight*phi, 'bulk pore weight'))
    solid_total = columns._sum(solid_weights, 'total solid fraction')
    mass_total = columns._sum(mass_weights, 'bulk mixture density')
    phi = columns._sum(pore_weights, 'effective porosity')
    if columns._q(solid_total+phi, 'bulk volume closure') != 1:
        raise ArithmeticError('exact composite bulk-volume closure failed')
    density = columns._q(mass_total/solid_total, 'effective grain density', positive=True)
    identity = {'schema': SCHEMA, 'constituents': definitions, 'k_per_year': str(k), 'phase': phase}
    raw = json.dumps(identity, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    material_id = 'R18_COMPOSITE_'+hashlib.sha256(raw).hexdigest()
    components = []
    for row, solid, mass in zip(definitions, solid_weights, mass_weights):
        components.append(dict(row,
            mass_fraction=str(columns._q(mass/mass_total, 'constituent mass fraction')),
            solid_fraction=str(columns._q(solid/solid_total, 'constituent solid-volume fraction'))))
    return {'schema': SCHEMA, 'material_id': material_id,
            'grain_density_kg_m3': str(density), 'porosity': str(phi),
            'k_per_year': str(k), 'phase': phase, 'evidence': evidence,
            'constituents': components, 'omitted_zero_weight_unit_ids': sorted(omitted), 'scope': SCOPE}


def _validated(material_id, palette):
    _label(material_id, 'composite material identity')
    if type(palette) is not dict or material_id not in palette:
        raise ValueError('bound composite palette entry required')
    descriptor = palette[material_id]
    _exact(descriptor, DESCRIPTOR)
    if type(descriptor['constituents']) is not list or not 1 <= len(descriptor['constituents']) <= MAX_CONSTITUENTS:
        raise ValueError('bounded composite descriptor constituents required')
    inputs = []
    for row in descriptor['constituents']:
        _exact(row, COMPONENT)
        inputs.append({key: row[key] for key in INPUT})
    expected = create(inputs, descriptor['k_per_year'], phase=descriptor['phase'], evidence=descriptor['evidence'])
    omitted = descriptor['omitted_zero_weight_unit_ids']
    if type(omitted) is not list or len(omitted)+len(inputs) > MAX_CONSTITUENTS:
        raise ValueError('bounded omitted zero-weight identities required')
    for unit in omitted:
        _label(unit, 'omitted constituent unit identity')
    if len(set(omitted)) != len(omitted) or set(omitted) & {row['unit_id'] for row in inputs}:
        raise ValueError('duplicate omitted composite constituent identity')
    expected['omitted_zero_weight_unit_ids'] = sorted(omitted)
    if expected != descriptor or expected['material_id'] != material_id:
        raise ValueError('composite descriptor or identity changed')
    return expected


def project_mass(material_id, mass_kg, palette):
    """Project a nonnegative composite stock to exact per-unit mass and solids.

Palette is material_id -> create() descriptor. The descriptor is revalidated;
supplied fractions or checksums alone are never trusted. Its grain composition
is fixed by identity. A native deposited layer may have different phase or
porosity without changing this mass/solid projection; bulk volume is not inferred.
"""
    descriptor = _validated(material_id, palette)
    mass = columns._q(mass_kg, 'composite stock mass', nonnegative=True)
    density = columns._q(descriptor['grain_density_kg_m3'], 'effective grain density', positive=True)
    result = {}
    for row in descriptor['constituents']:
        fraction = columns._q(row['mass_fraction'], 'constituent mass fraction')
        unit_mass = columns._q(mass*fraction, 'projected constituent mass')
        unit_density = columns._q(row['grain_density_kg_m3'], 'constituent grain density', positive=True)
        result[row['unit_id']] = {'mass_kg': str(unit_mass),
            'solid_volume_m3': str(columns._q(unit_mass/unit_density, 'projected constituent solid volume'))}
    mass_sum = columns._sum((columns._q(row['mass_kg'], 'projected mass') for row in result.values()), 'projected mass sum')
    solid_sum = columns._sum((columns._q(row['solid_volume_m3'], 'projected solid volume') for row in result.values()), 'projected solid sum')
    if mass_sum != mass or solid_sum != columns._q(mass/density, 'composite stock solid volume'):
        raise ArithmeticError('exact composite constituent mass/solid closure failed')
    return result
