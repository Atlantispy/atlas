"""Compile resolved owner compartments into existing finite native geology.

Regional interpretation belongs to the source-bound caller. This adapter neither
chooses layer order nor converts independent affinities into probabilities.
"""
from copy import deepcopy
from fractions import Fraction as F
import time

from work.generator_upgrade_r16 import regional, columns as quantities
from . import composite, accounts, provenance as p


def build(packet, supports, sampling, resolved, palette, reference_runoff_m_year):
    """Construct resolved finite prisms and retain constituent grain accounts.

Each resolved support contains basal_elevation_m, translation_m, layers and
interpretation. Layers explicitly contain compartment_id, material_id and
thickness_m. Zero-thickness compartments are omitted by the regional interpreter.
"""
    started = time.perf_counter()
    for value in (packet, supports, sampling, resolved, palette):
        regional.contract.plain(value)
    if set(supports) != set(resolved) or set(supports) != set(sampling['samples']):
        raise ValueError('one resolved and sampled record per supplied support required')
    if not 1 <= len(supports) <= 32:
        raise ValueError('native per-call support bound exceeded')
    regional._owner_source(packet['owner_source'])
    regional._owner_source(packet['source_package'])
    reference = quantities._q(reference_runoff_m_year, 'reference runoff normalisation', positive=True)
    binding = p.identity()
    recipe = {'schema': regional.SCHEMA, 'context': deepcopy(packet['context']),
        'source_status': packet['source_status'], 'evidence': packet['evidence'],
        'owner_source': deepcopy(packet['owner_source']), 'supports': {}, 'events': []}
    interpretations = {}
    used = set()
    for key, point in supports.items():
        regional.contract.exact(point, ('xy_m', 'area_m2'), 'native geological support')
        row = resolved[key]
        regional.contract.exact(row, ('basal_elevation_m', 'translation_m', 'layers', 'interpretation'), 'resolved geological column')
        base = quantities._q(row['basal_elevation_m'], 'explicit finite base')
        shift = quantities._q(row['translation_m'], 'explicit structural translation')
        recipe['supports'][key] = {**deepcopy(point), 'basal_elevation_m': str(base)}
        if type(row['layers']) is not list or not row['layers']:
            raise ValueError('at least one positive finite geological compartment required')
        seen = set(); height = F(); sequence = []
        for index, layer in enumerate(row['layers']):
            regional.contract.exact(layer, ('compartment_id', 'material_id', 'thickness_m'), 'resolved geological compartment')
            compartment = layer['compartment_id']
            regional.contract.text(compartment)
            if compartment in seen:
                raise ValueError('duplicate compartment in one column')
            seen.add(compartment)
            mid = layer['material_id']
            material = composite._validated(mid, palette)
            used.add(mid); sequence.append(mid)
            thickness = quantities._q(layer['thickness_m'], 'finite positive compartment thickness', positive=True)
            height = quantities._q(height+thickness, 'total geological height')
            recipe['events'].append({'event_id': key+'-emplace-'+str(index), 'cell_id': key,
                'kind': 'emplace', 'source_status': packet['source_status'],
                'evidence': material['evidence'], 'layer': {'material_id': mid,
                    'grain_density_kg_m3': material['grain_density_kg_m3'],
                    'porosity': material['porosity'], 'phase': material['phase'],
                    'thickness_m': str(thickness), 'evidence': material['evidence']}})
        if shift:
            recipe['events'].append({'event_id': key+'-structure', 'cell_id': key,
                'kind': 'translate_base', 'source_status': packet['source_status'],
                'evidence': packet['evidence'], 'displacement_m': str(shift)})
        interpretations[key] = {**deepcopy(row['interpretation']),
            'compartments': deepcopy(row['layers']), 'expected_base_m': str(base+shift),
            'expected_surface_m': str(base+shift+height), 'chosen_bottom_to_top_sequence': sequence}
    if len(recipe['events']) > 256:
        raise ValueError('native event bound exceeded; reduce the support batch size')
    if used != set(palette):
        raise ValueError('palette must exactly cover the constructed native materials')
    result = regional.build(recipe)
    science = result['scientific']
    for key, expected in interpretations.items():
        actual = science['stratigraphy'][key]
        if (actual['surface_m'] != expected['expected_surface_m'] or
                actual['bottom_to_top'][0]['bottom_m'] != expected['expected_base_m'] or
                [layer['material_id'] for layer in actual['bottom_to_top']] != expected['chosen_bottom_to_top_sequence']):
            raise ArithmeticError('native geological geometry differs from resolved owner construction')
    science['regional_input'] = {'schema': 'diadem.geological-coverage-input.r18',
        'packet_sha256': p.sha(packet), 'source_package': deepcopy(packet['source_package']),
        'sampling': deepcopy(sampling), 'interpretations': interpretations,
        'palette': deepcopy(palette), 'reference_runoff_m_year': str(reference),
        'constituent_balances': accounts.project_balances(science['construction']['material_accounts'], palette, accounts.CONSTRUCTION_STAGES),
        'output_role': 'PRE_TERRAIN_FINITE_GEOLOGICAL_BODY_AND_INITIAL_SURFACE',
        'current_dem_consumed': False, 'active_terrain_registration_claimed': False,
        'geology_affects_native_material_stocks_and_geometry': True,
        'mixture_transfer_scope': composite.SCOPE,
        'sampling_scope': 'NATIVE_CENTRE_PRISMS_OR_DECLARED_POINT_SAMPLES_NOT_CONSERVATIVE_REMAP',
        'hydrology_or_groundwater_connectivity_inferred': False,
        'execution_binding_sha256': p.sha(binding)}
    actual_history = [row.get('geological_constituent_balances') for row in interpretations.values()]
    if any(value is not None for value in actual_history):
        if any(value is None for value in actual_history):
            raise ValueError('geological event accounts must cover every constructed support')
        totals = {}
        for ledger in actual_history:
            for row in ledger:
                target = totals.setdefault(row['unit_id'], {})
                for name, value in row.items():
                    if name != 'unit_id':
                        if name.startswith('residual_') and accounts.quantity(value):
                            raise ArithmeticError('nonzero supplied geological construction residual')
                        target[name] = quantities._q(target.get(name, F())+accounts.quantity(value), 'batch geological construction account')
        native_totals = {row['unit_id']: row for row in science['regional_input']['constituent_balances']}
        for unit, row in totals.items():
            for suffix in ('mass_kg', 'solid_volume_m3'):
                if row['imported_'+suffix]-row['exported_'+suffix] != row['final_'+suffix]:
                    raise ArithmeticError('batch geological replacement account does not close')
                if row['final_'+suffix] != accounts.quantity(native_totals.get(unit, {}).get('final_'+suffix, '0')):
                    raise ArithmeticError('native constructed stock differs from actual geological event account')
        if set(native_totals)-set(totals):
            raise ArithmeticError('native stock lacks geological construction account')
        science['regional_input']['geological_constituent_balances'] = [
            {'unit_id': unit, **{name: str(value) for name, value in row.items()}}
            for unit, row in sorted(totals.items())]
        science['regional_input']['account_scopes'] = {
            'geological_constituent_balances': 'ACTUAL_EMPLACEMENT_AND_REPLACEMENT_IMPORTS_EXPORTS_AND_FINAL_STOCK',
            'constituent_balances': 'FINAL_NATIVE_ASSEMBLY_NOT_A_SECOND_GEOLOGICAL_HISTORY',
            'construction': 'NATIVE_FINAL_ASSEMBLY_EVENTS_SEPARATE_FROM_OWNER_REPLACEMENT_HISTORY'}
    result['execution']['regional_input_identity'] = binding
    result['execution']['scientific_sha256'] = p.sha(science)
    result['execution']['regional_input_elapsed_wall_seconds'] = time.perf_counter()-started
    p.verify(binding)
    return result
