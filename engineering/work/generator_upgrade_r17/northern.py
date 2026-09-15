"""Owner-defined northern geological reconstruction, not a global rock default.

R17 contract sections Owner-assigned construction and Vertical-order uncertainty
define these rules. Independent source affinities remain in the output; they are
not normalised, classified as final outcrop, or converted from ordinal strength.
"""
from copy import deepcopy
from fractions import Fraction as F
import math
import time

from work.generator_upgrade_r16 import regional
from work.generator_upgrade_r14 import erosion
from . import fields, provenance as p

FIELD_NAMES = {'crown_massif_support', 'affinity_nc_01', 'affinity_bx_00',
               'affinity_nk_01', 'affinity_ek_02', 'affinity_nv_01',
               'affinity_nv_02', 'affinity_ed_01'}
DEFAULT = 'DEFAULT_WORKING_ORDER'
ALTERNATIVE = 'NO_CARBONATE_UNDER_VOLCANIC_CORE'
# Fixed effective property assignments from Physical Frame's R17 contract.
MATERIALS = (('R17_NORTH_CRYSTALLINE', 2700, '1/50', 1e-5),
             ('R17_NORTH_CARBONATE', 2750, '2/25', 2e-5),
             ('R17_NORTH_NV01', 2800, '1/25', 1e-5),
             ('R17_NORTH_NV02', 2500, '3/100', 1e-5))


def compile_recipe(samples, supports, context, owner_source, evidence, source_status,
                   alternative=DEFAULT):
    """Compile explicit source samples into native finite construction events."""
    if alternative not in (DEFAULT, ALTERNATIVE):
        raise ValueError('explicit owner reconstruction alternative required')
    if set(samples) != set(supports) or not 1 <= len(supports) <= 32:
        raise ValueError('one complete sampled record per bounded support required')
    context = deepcopy(context)
    if alternative != DEFAULT:
        context['snapshot_id'] += '/' + alternative
    recipe = {'schema': regional.SCHEMA, 'context': context,
              'source_status': source_status, 'evidence': evidence,
              'owner_source': deepcopy(owner_source), 'supports': {}, 'events': []}
    interpretations = {}
    for key, support in supports.items():
        if set(support) != {'xy_m', 'area_m2'}:
            raise ValueError('support XY and area required; native base is constructed')
        row = samples[key]
        if set(row) != FIELD_NAMES:
            raise ValueError('all eight owner fields required; no substitute priors')
        affinity = {}
        for name, value in row.items():
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('finite source affinity in [0,1] required; no clipping')
            affinity[name] = F(value)
        nk = 2000*affinity['affinity_nk_01']
        ek = 1000*affinity['affinity_ek_02']
        carbonate = max(nk, ek)
        omitted = alternative == ALTERNATIVE and affinity['affinity_nv_01'] >= F(1, 2)
        if omitted:
            carbonate = F()
        thicknesses = (F(10000), carbonate, 2000*affinity['affinity_nv_01'],
                       300*affinity['affinity_nv_02'])
        shift = 6000*affinity['crown_massif_support']
        recipe['supports'][key] = {**deepcopy(support), 'basal_elevation_m': '-10000'}
        sequence = []
        for index, ((material, density, porosity, _), thickness) in enumerate(zip(MATERIALS, thicknesses)):
            if not thickness:
                continue
            sequence.append(material)
            recipe['events'].append({'event_id': key+'-emplace-'+str(index),
                'cell_id': key, 'kind': 'emplace', 'source_status': source_status,
                'evidence': evidence, 'layer': {'material_id': material,
                    'grain_density_kg_m3': str(density), 'porosity': porosity,
                    'phase': 'bedrock', 'thickness_m': str(thickness),
                    'evidence': evidence+'; explicit northern effective material scenario'}})
        recipe['events'].append({'event_id': key+'-structure', 'cell_id': key,
            'kind': 'translate_base', 'source_status': source_status,
            'evidence': evidence, 'displacement_m': str(shift)})
        interpretations[key] = {'raw_independent_fields': deepcopy(row),
            'carbonate_contributions_m': {'NK-01': str(nk), 'EK-02': str(ek)},
            'carbonate_volcanic_overlap_score': str(min(max(affinity['affinity_nk_01'],
                affinity['affinity_ek_02']), affinity['affinity_nv_01'])),
            'reference_thicknesses_m': list(map(str, thicknesses)),
            'structural_elevation_contribution_m': str(shift),
            'expected_base_m': str(-10000+shift),
            'expected_surface_m': str(shift+sum(thicknesses[1:], F())),
            'chosen_bottom_to_top_sequence': sequence,
            'carbonate_omitted_by_alternative': omitted,
            'alternative': alternative, 'vertical_architecture_status': 'WORKING NON-CANON',
            'carbonate_under_volcanic_fringe': 'UNKNOWN',
            'root_composition': 'NC-01/BX-00 effective homogenisation; ED-01 host annotation',
            'coequal_affinities_preserved': True}
    return recipe, interpretations


def build(packet, supports, alternative=DEFAULT):
    """Read actual fields, construct geology, and bind it to the native consumer."""
    started = time.perf_counter()
    regional.contract.plain(packet)
    regional.contract.exact(packet, ('context', 'source_status', 'evidence',
                                    'owner_source', 'fields', 'source_package'), 'R17 input packet')
    if set(packet['fields']) != FIELD_NAMES:
        raise ValueError('the eight bound northern field inputs are required')
    regional._owner_source(packet['owner_source'])
    # Package binding is separate from array checks: the control and causal
    # branches can share registry bytes without sharing numerical fields.
    regional._owner_source(packet['source_package'])
    binding = p.identity()
    sampled = fields.sample_fields(packet['fields'], supports,
        packet['context']['spatial_frame_id'], packet['source_status'])
    recipe, interpreted = compile_recipe(sampled['samples'], supports,
        packet['context'], packet['owner_source'], packet['evidence'], packet['source_status'], alternative)
    result = regional.build(recipe)
    science = result['scientific']
    for key, interpretation in interpreted.items():
        actual = science['stratigraphy'][key]
        if (actual['surface_m'] != interpretation['expected_surface_m'] or
                actual['bottom_to_top'][0]['bottom_m'] != interpretation['expected_base_m'] or
                [v['material_id'] for v in actual['bottom_to_top']] != interpretation['chosen_bottom_to_top_sequence']):
            raise ArithmeticError('native geological output differs from source-driven construction')
    science['regional_input'] = {'schema': 'diadem.northern-geological-input.r17',
        'packet_sha256': p.sha(packet), 'source_package': deepcopy(packet['source_package']),
        'sampling': sampled, 'interpretations': interpreted, 'alternative': alternative,
        'output_role': 'PRE_TERRAIN_FINITE_GEOLOGICAL_BODY_AND_INITIAL_SURFACE',
        'current_dem_consumed': False, 'active_terrain_registration_claimed': False,
        'geology_affects_native_material_stocks_and_geometry': True,
        'sampling_scope': 'NATIVE_CENTRE_PRISMS_OR_DECLARED_POINT_SAMPLES_NOT_CONSERVATIVE_REMAP',
        'hydrology_or_groundwater_connectivity_inferred': False,
        'execution_binding_sha256': p.sha(binding)}
    result['execution']['regional_input_identity'] = binding
    result['execution']['scientific_sha256'] = p.sha(science)
    result['execution']['regional_input_elapsed_wall_seconds'] = time.perf_counter()-started
    p.verify(binding)
    return result


def erosion_laws(source_status, evidence):
    """Native-law property rows; no sediment or groundwater law is inferred."""
    def prop(name, value, unit):
        return {'name': name, 'value': value, 'unit': unit,
                'status': source_status, 'evidence': evidence}
    return [{'material_id': mid, 'phase': 'bedrock',
             'k_per_year': prop('erosion_coefficient_at_reference_runoff', k, '1/year'),
             'reference_runoff_m_year': prop('reference_runoff', 1., 'm/year')}
            for mid, _, _, k in MATERIALS]


def _verify_snapshot(snapshot):
    p.verify(snapshot['execution']['regional_input_identity'])
    science = snapshot['scientific']
    if (science['regional_input']['execution_binding_sha256'] != p.sha(snapshot['execution']['regional_input_identity']) or
            snapshot['execution']['scientific_sha256'] != p.sha(science)):
        raise ValueError('regional input execution binding differs')
    regional.p.verify(snapshot['execution']['identity'])
    regional._owner_source(science['owner_source'])
    return science


def _lineage(snapshot):
    return {'r17_input_scientific_sha256': snapshot['execution']['scientific_sha256'],
            'r17_regional_input_sha256': p.sha(snapshot['scientific']['regional_input']),
            'r17_execution_sha256': p.sha(snapshot['execution']['regional_input_identity'])}


def incise(snapshot, forcing, duration_years):
    """Native finite bedrock erosion under explicit local discharge/slope.

This is not regional water routing. Removed stocks are returned in the native
erosion account; transport/deposition needs its separately supplied laws.
"""
    science = _verify_snapshot(snapshot)
    _, native = regional.p.backend()
    initial = native.LandscapeState.from_dict(science['state'])
    regional.contract.plain(forcing)
    if set(forcing) != set(initial.column_map):
        raise ValueError('one explicit forcing per generated geological column required')
    native_forcing = {}
    for key, row in forcing.items():
        regional.contract.exact(row, ('discharge_m3_year', 'hydraulic_slope', 'evidence', 'source_status'), 'local erosion forcing')
        regional.contract.text(row['evidence'])
        if row['source_status'] != science['source_status']:
            raise ValueError('local forcing and geological input statuses differ')
        def prop(name, value, unit):
            return native.PhysicalProperty(name, value, unit, row['evidence'], row['source_status'])
        native_forcing[key] = native.landscape.Forcing(
            prop('discharge', row['discharge_m3_year'], 'm3/year'),
            prop('hydraulic_slope', row['hydraulic_slope'], '1'))
    law_rows = erosion_laws(science['source_status'], 'R17 owner-defined northern mechanical incision law')
    laws = [native.ErosionLaw(row['material_id'], row['phase'],
        native.PhysicalProperty(**row['k_per_year']), native.PhysicalProperty(**row['reference_runoff_m_year']))
        for row in law_rows]
    result = erosion.advance(initial, native_forcing, laws, regional._signed(duration_years))
    _verify_snapshot(snapshot)
    return {'state': result.state.as_dict(), 'receipt': regional._plain(result.receipt),
            'forcing': deepcopy(forcing), 'duration_years': str(regional._signed(duration_years)),
            'source_status': science['source_status'],
            'scope': 'PRESCRIBED_LOCAL_BEDROCK_EROSION_NOT_REGIONAL_HYDROLOGY_OR_SEDIMENT_ROUTING',
            **_lineage(snapshot)}


def terrain_step(snapshot, forcing):
    """Use actual generated geology; explicit hydrology/sediment forcing required."""
    _verify_snapshot(snapshot)
    result = regional.terrain_step(snapshot, forcing)
    result.update(_lineage(snapshot))
    return result
