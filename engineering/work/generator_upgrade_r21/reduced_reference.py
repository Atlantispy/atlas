"""Exact Resources Seasonal/Exclusion/Dry geometry and unchanged R1 crop values.

This four-day engineering reference is not an agronomic calibration. Carbon
fraction below is solely the native human converter's cancelling intermediary;
it supplies no carbon-production claim and changes none of R1's food values.
"""
from copy import deepcopy

from . import crops, reduced


E = 'SYNTHETIC TEST: explicit engineering oracle, not a proposed Diadem parameter set'
S = 'SYNTHETIC TEST'
DAY = 86400


def _rectangle(left, right):
    return {'type': 'Polygon', 'coordinates': [[[left, 0], [right, 0], [right, 1], [left, 1], [left, 0]]]}


def scenario(case='seasonal'):
    """Return a plain common envelope; the integrating pipeline binds sources."""
    if case not in ('seasonal', 'exclusion', 'dry'):
        raise ValueError('explicit Resources seasonal/exclusion/dry reference required')
    scenario_id = 'R21-R-'+case.capitalize()
    geometry = [('A', 0, 5), ('B', 5, 8 if case == 'exclusion' else 10)]
    plots = [{'id': ident, 'geometry': _rectangle(a, b), 'crop_ids': ['grain'],
        'management_permission': 'ALLOWED', 'evidence': E, 'source_status': S,
        'source_role': 'EXPLICIT_PLOT_HYPOTHESIS'} for ident, a, b in geometry]
    plans = []
    for ident, a, b in geometry:
        plans.append({'plan_id': ident+'-grain', 'support_id': ident,
            'irrigation_sink_id': ident+'-root-inlet', 'settlement_id': 'town',
            'area_m2': str(b-a), 'season_start_seconds': '0', 'day_duration_seconds': str(DAY),
            'root_zone': {'field_capacity_m3_m3': .3, 'wilting_point_m3_m3': .1,
                'rooting_depth_m': 1, 'depletion_fraction': .5, 'evidence': E, 'source_status': S},
            'initial_depletion_mm': 0, 'application_efficiency': .5,
            'application_evidence': E, 'delivery_boundary': 'ROOT_ZONE_NET',
            'regime': crops.REGIME, 'evidence': E, 'source_status': S,
            'daily_forcing': [{'precipitation_mm': 0, 'runoff_mm': 0,
                'net_irrigation_mm': 50, 'capillary_rise_mm': 0, 'potential_crop_et_mm': 50} for _ in range(4)],
            'segments': [{'segment_id': ident+'-grain-cycle', 'kind': 'CROP', 'start_day': 0, 'stop_day': 4,
                'evidence': E, 'source_status': S, 'commodity_id': 'grain',
                'crop_parameters': {'potential_yield_kg_m2': 1, 'yield_response_factor': 1,
                    'minimum_valid_et_ratio': .5, 'evidence': E, 'source_status': S},
                'conversion': {'mass_basis': 'EDIBLE_DRY_FOOD_KG', 'carbon_fraction_dry_matter': '1/2',
                    'edible_fraction': 1, 'processing_loss_fraction': 0, 'edible_energy_kcal_kg': 1000,
                    'food_quality_evidence': E, 'evidence_id': E, 'source_status': S}}]})
    windows = []
    for name, start, end in [('growing', 0, 4*DAY), ('after-harvest', 4*DAY, 365*DAY)]:
        obligation = {'obligation_id': name+'-consumption', 'node_id': 'town', 'bundle_id': 'grain-diet',
            'kind': 'recurring_consumption', 'recurrence': 'per_year', 'amount_unit': 'kcal',
            'amount': '6000', 'component_claim_ids': [name+'-claim'], 'evidence': E, 'source_status': S}
        windows.append({'id': name, 'start_seconds': str(start), 'end_seconds': str(end),
            'obligations': [obligation], 'policies': [{'node_id': 'town',
                'protected_order': ['recurring_consumption'], 'obligation_order': [obligation['obligation_id']],
                'block_export_on_shortfall': True, 'evidence': E}]})
    return deepcopy({'context': {'world_id': 'SYNTHETIC_NOT_DIADEM',
        'snapshot_id': 'synthetic-one-annual-cycle', 'calendar_id': 'synthetic-365-day-reference',
        'spatial_frame_id': 'synthetic-metre-grid', 'vertical_reference': 'SYNTHETIC_LOCAL_METRES',
        'scenario_id': scenario_id}, 'terrain_generation': 'EXPLICIT_SYNTHETIC_RECTANGLES_NOT_TERRAIN_GENERATION',
        'source_status': S, 'evidence': E, 'engine': reduced.ENGINE,
        'land': {'plots': plots, 'land_geometry': _rectangle(0, 10),
            'exclusions': [{'id': 'reference-exclusion', 'rule': 'EXPLICIT_REFERENCE_EXCLUSION',
                'geometries': [_rectangle(8, 10)] if case == 'exclusion' else [], 'evidence': E, 'source_status': S}],
            'admission': {'scenario_id': scenario_id, 'source_status': S, 'evidence': E,
                'land_complete': True, 'exclusions_complete': True,
                'required_exclusion_rules': ['EXPLICIT_REFERENCE_EXCLUSION'], 'forbidden_source_roles': []}},
        'plans': plans, 'water': {'source_id': 'shared-pool', 'initial_stock_m3': '0' if case == 'dry' else '2',
            'evidence': E, 'source_status': S, 'connection_law': reduced.CONNECTION},
        'food': {'windows': windows, 'bundles': [{'bundle_id': 'grain-diet',
            'components': [{'commodity_id': 'grain', 'energy_share': '1', 'edible_energy_kcal_kg': '1000',
                'composition_evidence': E}], 'energy_kcal_person_day': '600/73', 'diet_evidence': E, 'source_status': S}],
            'calendar': {'days_per_year': '365', 'day_duration_seconds': str(DAY), 'evidence': E},
            'evidence': E, 'source_status': S}})
