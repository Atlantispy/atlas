"""Data-driven finite geological stages, with explicit owner physical choices."""
from copy import deepcopy
from fractions import Fraction as F

from work.generator_upgrade_r16 import columns
from . import rules, replacement, composite, accounts


def batch_limit(programme):
    # Each top-relative replacement can introduce at most one new contact.
    maximum_layers = sum(stage['kind'] in ('emplace', 'replace') for stage in programme['stages'])
    return min(32, 256//(maximum_layers+1))


def interpret(samples, supports, programme, materials, *, k_mixing='arithmetic'):
    """Evaluate a bound programme; no material or stratigraphic defaults.

The caller provides raw-field ranges, derived expressions in order, ordered
emplacement/replacement stages, a base and translation expression, and an
eligible-host K-only modifier. Raw source affinities are preserved separately.
"""
    if k_mixing not in ('arithmetic', 'harmonic'):
        raise ValueError('explicit owner arithmetic/harmonic K scenario required')
    if set(samples) != set(supports):
        raise ValueError('complete source sample per support required')
    palette, resolved = {}, {}
    for key, raw in samples.items():
        if set(raw) != set(programme['field_ranges']):
            raise ValueError('complete exact owner field inventory required')
        values = {}
        for name, value in raw.items():
            q = columns._q(value, 'source sample '+name)
            lower, upper = programme['field_ranges'][name]
            if q < columns._q(lower, 'source lower bound') or (upper is not None and q > columns._q(upper, 'source upper bound')):
                raise ValueError('source outside owner physical range; no clipping: '+name)
            values[name] = q
        for row in programme['derived_fields']:
            if row['name'] in values:
                raise ValueError('derived field cannot overwrite a source or prior expression')
            values[row['name']] = rules.evaluate(row['expression'], values)
        area = columns._q(supports[key]['area_m2'], 'support area', positive=True)
        layers, imported, exported, history = [], {}, {}, []
        def add(target, unit, thickness):
            if unit not in materials:
                raise ValueError('unknown unit prototype: '+unit)
            target[unit] = columns._q(target.get(unit, F())+area*thickness, 'unit bulk construction stock')
        for stage in programme['stages']:
            identity = stage['stage_id']
            if stage['kind'] == 'emplace':
                height = columns._q(rules.evaluate(stage['thickness_m'], values), 'owner cover thickness', nonnegative=True)
                weights = {unit: columns._q(rules.evaluate(expr, values), 'owner composition support', nonnegative=True)
                           for unit, expr in stage['weights'].items()}
                total = columns._sum(weights.values(), 'owner compartment total support')
                fallback = False
                if not total and height:
                    unit = stage.get('fallback_unit_id')
                    if unit is None:
                        raise ValueError('positive compartment lacks material support and owner fallback')
                    weights = {unit: F(1)}; total = F(1); fallback = True
                if height:
                    weights = {unit: columns._q(weight/total, 'new bulk mixture weight')
                               for unit, weight in weights.items() if weight}
                    layer = {'compartment_id': identity, 'thickness_m': str(height),
                             'weights': {unit: str(weight) for unit, weight in weights.items()}}
                    layers.append(layer)
                    for unit, weight in weights.items():
                        add(imported, unit, columns._q(height*weight, 'emplaced unit thickness'))
                history.append({'stage_id': identity, 'kind': 'emplace', 'thickness_m': str(height),
                                'omitted_zero_thickness': not bool(height), 'fallback_used': fallback})
            elif stage['kind'] == 'replace':
                replacements = {unit: rules.evaluate(expr, values) for unit, expr in stage['supports'].items()}
                for unit in replacements:
                    if unit not in materials:
                        raise ValueError('unknown replacement prototype: '+unit)
                depth = rules.evaluate(stage['depth_m'], values)
                coverage = None if 'coverage' not in stage else rules.evaluate(stage['coverage'], values)
                layers, transfers = replacement.replace(layers, depth, replacements,
                    eligible_units=stage.get('eligible_units'), protected_units=stage.get('protected_units', ()),
                    coverage=coverage)
                for transfer in transfers:
                    for unit, thickness in transfer['removed_bulk_thickness_m'].items():
                        add(exported, unit, columns._q(thickness, 'removed unit thickness'))
                    for unit, thickness in transfer['introduced_bulk_thickness_m'].items():
                        add(imported, unit, columns._q(thickness, 'introduced unit thickness'))
                history.append({'stage_id': identity, 'kind': 'replace', 'depth_m': str(depth), 'transfers': transfers})
            else:
                raise ValueError('unsupported owner construction stage')
        final_bulk, native_layers, modifiers = {}, [], []
        overlay = programme['mechanical_overlay']
        strength = columns._q(values[overlay['field']], 'overlay strength', nonnegative=True)
        if strength > 1:
            raise ValueError('overlay strength exceeds one')
        for layer in layers:
            components, effective_terms, unit_k = [], [], {}
            for unit, weight in layer['weights'].items():
                prototype = materials[unit]
                if prototype['phase'] != 'bedrock':
                    raise ValueError('this owner rock programme requires solid bedrock prototypes')
                weight = columns._q(weight, 'final bulk constituent weight')
                k = columns._q(prototype['k_per_year'], 'prototype mechanical K', positive=True)
                if unit in overlay['eligible_units']:
                    k = columns._q((1-strength)*k+strength*columns._q(overlay['target_k_per_year'], 'overlay K', positive=True), 'modified constituent K')
                unit_k[unit] = str(k)
                components.append({'unit_id': unit, 'bulk_weight': str(weight),
                    'grain_density_kg_m3': prototype['grain_density_kg_m3'], 'porosity': prototype['porosity']})
                effective_terms.append(columns._q(weight*k if k_mixing == 'arithmetic' else weight/k, 'K mixture term'))
                add(final_bulk, unit, columns._q(columns._q(layer['thickness_m'], 'final layer thickness')*weight, 'final unit thickness'))
            k = columns._sum(effective_terms, 'effective K mixture')
            if k_mixing == 'harmonic':
                k = columns._q(1/k, 'harmonic effective K', positive=True)
            descriptor = composite.create(components, k, phase='bedrock', evidence=programme['evidence'])
            mid = descriptor['material_id']
            if mid in palette and palette[mid] != descriptor:
                raise ValueError('composition-bound identity collision')
            palette[mid] = descriptor
            native_layers.append({'compartment_id': layer['compartment_id'], 'material_id': mid,
                                  'thickness_m': layer['thickness_m']})
            modifiers.append({'compartment_id': layer['compartment_id'], 'material_id': mid,
                              'constituent_k_per_year': unit_k})
        ledger = accounts.construction_from_bulk(imported, exported, final_bulk, materials)
        resolved[key] = {'basal_elevation_m': str(rules.evaluate(programme['base_m'], values)),
            'translation_m': str(rules.evaluate(programme['translation_m'], values)), 'layers': native_layers,
            'interpretation': {'raw_independent_fields': deepcopy(raw),
                'derived_fields': {row['name']: str(values[row['name']]) for row in programme['derived_fields']},
                'construction_stages': history, 'geological_constituent_balances': ledger,
                'mechanical_overlay': {'unit_id': overlay['unit_id'], 'strength': str(strength),
                    'added_volume_m3': '0', 'added_mass_kg': '0', 'layers': modifiers},
                'k_mixing': k_mixing, 'chosen_order': [stage['stage_id'] for stage in programme['stages']],
                'coequal_affinities_preserved': True, 'source_affinities_are_not_volume_measurements': True}}
    return resolved, palette
