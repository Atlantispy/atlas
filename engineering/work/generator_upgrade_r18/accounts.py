"""Exact constituent grain-stock accounts for congruent composite transfers."""
from fractions import Fraction as F

from work.generator_upgrade_r16 import columns
from . import composite


def quantity(value):
    if type(value) is list and len(value) == 2 and all(type(v) is int for v in value):
        value = F(*value)
    return columns._q(value, 'constituent account quantity', nonnegative=True)


def construction_from_bulk(imported_m3, exported_m3, final_m3, materials):
    """Account actual emplacement/replacement, separately from final assembly.

Unit prototype density/porosity stay fixed during construction. Replacement
exchanges equal bulk volumes, not necessarily equal mass or grain volume.
"""
    rows = []
    for unit in sorted(set(imported_m3) | set(exported_m3) | set(final_m3)):
        material = materials[unit]
        rho = columns._q(material['grain_density_kg_m3'], 'unit density', positive=True)
        phi = columns._q(material['porosity'], 'unit porosity', nonnegative=True)
        if phi >= 1:
            raise ValueError('unit porosity must be below one')
        row = {'unit_id': unit, 'initial_mass_kg': '0', 'initial_solid_volume_m3': '0'}
        for label, values in (('imported', imported_m3), ('exported', exported_m3), ('final', final_m3)):
            bulk = quantity(values.get(unit, 0))
            solid = columns._q(bulk*(1-phi), 'construction unit solid volume')
            row[label+'_bulk_volume_m3'] = str(bulk)
            row[label+'_solid_volume_m3'] = str(solid)
            row[label+'_mass_kg'] = str(columns._q(solid*rho, 'construction unit mass'))
        for suffix in ('bulk_volume_m3', 'solid_volume_m3', 'mass_kg'):
            residual = quantity(row['imported_'+suffix])-quantity(row['exported_'+suffix])-quantity(row['final_'+suffix])
            if residual:
                raise ArithmeticError('construction unit '+suffix+' does not close')
            row['residual_'+suffix] = '0'
        rows.append(row)
    return rows


def project_balances(rows, palette, stages):
    """Project actual native balances, retaining every constituent mass/solid.

stages contains (name, native_mass_key, native_solid_key, balance_sign).
This projects represented actual transfers, not preferential entrainment,
dissolution, grain sorting or a new component pore-volume partition.
"""
    totals = {}
    for row in rows:
        mid = row['material_id']
        for label, mass_key, solid_key, sign in stages:
            mass, solid = quantity(row[mass_key]), quantity(row[solid_key])
            projected = composite.project_mass(mid, mass, palette)
            if sum((quantity(v['mass_kg']) for v in projected.values()), F()) != mass:
                raise ArithmeticError('projected constituent mass differs from native account')
            if sum((quantity(v['solid_volume_m3']) for v in projected.values()), F()) != solid:
                raise ArithmeticError('projected constituent solid differs from native account')
            for unit, values in projected.items():
                target = totals.setdefault(unit, {})
                for suffix, source in (('mass_kg', 'mass_kg'), ('solid_volume_m3', 'solid_volume_m3')):
                    key = label+'_'+suffix
                    target[key] = columns._q(target.get(key, F())+quantity(values[source]), 'summed constituent stock')
    answer = []
    for unit, values in sorted(totals.items()):
        for suffix in ('mass_kg', 'solid_volume_m3'):
            residual = F()
            for label, _, _, sign in stages:
                if sign not in (-1, 1):
                    raise ValueError('explicit conservation stage sign required')
                residual = columns._q(residual+sign*values.get(label+'_'+suffix, F()), 'constituent residual')
            if residual:
                raise ArithmeticError('constituent '+suffix+' account does not close')
            values['residual_'+suffix] = residual
        answer.append({'unit_id': unit, **{key: str(value) for key, value in values.items()}})
    return answer


CONSTRUCTION_STAGES = (
    ('initial', 'initial_mass_kg', 'initial_solid_volume_m3', 1),
    ('imported', 'external_import_mass_kg', 'external_import_solid_volume_m3', 1),
    ('exported', 'export_mass_kg', 'export_solid_volume_m3', -1),
    ('final', 'final_mass_kg', 'final_solid_volume_m3', -1))
EROSION_STAGES = (
    ('initial', 'initial_mass_kg', 'initial_solid_volume_m3', 1),
    ('deposited', 'deposited_mass_kg', 'deposited_solid_volume_m3', 1),
    ('eroded', 'eroded_mass_kg', 'eroded_solid_volume_m3', -1),
    ('final', 'final_mass_kg', 'final_solid_volume_m3', -1))
TERRAIN_STAGES = (
    ('initial', 'initial_mass_kg', 'initial_solid_m3', 1),
    ('exported', 'exported_mass_kg', 'exported_solid_m3', -1),
    ('final', 'final_mass_kg', 'final_solid_m3', -1))
