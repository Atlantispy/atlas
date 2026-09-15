"""Explicit synthetic seasonal/PFT scenarios; not adopted Diadem calibration."""
from copy import deepcopy
from fractions import Fraction as F
import math
from . import binding

E = 'SYNTHETIC TEST: fixed formed R7 soil, separately supplied representative Jan-Dec circulation and natural-vegetation trait hypotheses; not calibrated Diadem distributions'


def recipe(bundle):
    soil = bundle.parent.reference.recipe(bundle.parent)
    retained = soil['parent_recipe']['retained_recipe']
    cm = bundle.parent.parent.pipeline.climate
    cell_ids = [v['cell_id'] for v in retained['transect']]
    months = []
    temperatures = (-3, -1, 3, 8, 13, 17, 19, 18, 14, 9, 3, -1)
    for index, temperature in enumerate(temperatures, 1):
        regimes = []
        for name, weight, humidity_fraction, cloud in (('wet', 0.25, 0.75, 0.001), ('dry', 0.75, 0.5, 0.)):
            air = deepcopy(retained['events'][0]['atmosphere'])
            vapour = cm.saturation_liquid(temperature)[0] * humidity_fraction
            q = air['epsilon'] * vapour / (air['reference_pressure_pa'] - (1 - air['epsilon']) * vapour)
            air.update(reference_temperature_c=temperature, inlet_specific_humidity=q,
                       inlet_condensate_kg_per_kg_dry_air=cloud, dry_air_flux_kg_s=300000,
                       evidence=E + '; independently prescribed seasonal air mass and finite vapour/cloud inflow')
            surfaces = {cell: {'net_radiation_w_m2': 35 + 90 * max(0, math.sin(math.pi * (index - 2) / 12)),
                               'ground_heat_flux_w_m2': 0., 'aerodynamic_resistance_s_m': 50.,
                               'surface_resistance_s_m': 70., 'evidence': E + '; supplied mean reference-surface energy/resistance, not inferred vegetation'} for cell in cell_ids}
            regimes.append({'regime_id': name, 'weight': weight, 'atmosphere': air,
                            'climate_controls': deepcopy(retained['events'][0]['climate_controls']),
                            'surfaces': surfaces, 'evidence': E + '; explicit wet/dry occupancy fractions, not observed event frequency'})
        months.append({'month_id': index, 'regimes': regimes,
                       'evidence': E + '; monthly stationary mixture, uniform monthly rainfall/snowfall hypothesis with explicit melt depletion'})
    seasonal = {'calendar': {'calendar_id': 'JAN_DEC_365_FEB28',
                            'month_days': [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31],
                            'day_seconds': 86400, 'evidence': E + '; explicit retained reporting calendar, not inferred from short parent'},
                'transect': deepcopy(retained['transect']), 'months': months,
                'phase': deepcopy(retained['phase']), 'phase_controls': deepcopy(retained['phase_controls']),
                'demand_constants': deepcopy(retained['demand_constants']), 'snow_max_cycles': 20, 'snow_atol_m': 1e-10,
                'temperature_distribution_evidence': E + '; Gaussian temperature-index snow sensitivity separately preserves all three coequal joint parameters', 'evidence': E}
    pfts = {}
    # coldest lower/upper, minimum thermal sum, maximum root depth, demand fraction,
    # minimum active-season AET/demand. These are test hypotheses, not species facts.
    parameters = {
        'alpine': ('COLD_HERB', -55, 12, 30, 0.2, 0.35, 0.10),
        'conifer': ('COLD_CONIFER', -40, 8, 150, 1.0, 0.70, 0.20),
        'temperate': ('TEMPERATE_TREE', -15, 25, 500, 1.2, 0.80, 0.25),
        'macroforest': ('MACROFOREST_TREE', -10, 25, 700, 1.5, 0.95, 0.45),
        'grass': ('GRASS', -40, 30, 100, 0.5, 0.45, 0.15),
        'steppe': ('GRASS', -40, 35, 150, 0.4, 0.30, 0.05),
    }
    for ident, (guild, cold_min, cold_max, gdd, depth, demand, water) in parameters.items():
        pfts[ident] = {'guild': guild, 'evidence': E,
            'rooting': {'maximum_root_depth_m': depth, 'upper_head_m': -0.1, 'lower_head_m': -100.,
                        'allowed_phases': ['organic_mantle', 'mobile_sediment', 'immobile_regolith'],
                        'evidence': E + '; explicit rooted matrix and available-water matric endpoints, not universal field capacity/wilting point'},
            'active_above_temperature_c': 0. if ident == 'alpine' else 5.,
            'reference_transpiration_fraction': demand,
            'constraints': {'pft_id': ident, 'base_temperature_c': 5., 'dry_stress_fraction': 0.5,
                'limits': [{'metric': 'coldest_month_temperature_c', 'minimum': cold_min, 'maximum': cold_max, 'evidence': E, 'source_status': 'SYNTHETIC TEST'},
                           {'metric': 'growing_degree_days', 'minimum': gdd, 'maximum': 15000., 'evidence': E, 'source_status': 'SYNTHETIC TEST'},
                           {'metric': 'rooted_depth_m', 'minimum': 0.05, 'maximum': depth, 'evidence': E, 'source_status': 'SYNTHETIC TEST'},
                           {'metric': 'active_actual_to_potential_transpiration_ratio', 'minimum': water, 'maximum': 1., 'evidence': E, 'source_status': 'SYNTHETIC TEST'}],
                'external_requirements': ['aeration', 'chemical_regime'], 'evidence': E, 'source_status': 'SYNTHETIC TEST'},
            'chemical_regime': {'minimum_ph_water': 4., 'maximum_ph_water': 8., 'maximum_ec_ds_m': 2.,
                                'cec_method': soil['fertility']['chemistry']['cec_method'],
                                'evidence': E + '; whole-profile common chemical context applicability, not nutrient sufficiency or plant demand'}}
    def response(metric, unit, points):
        return {'metric': metric, 'unit': unit, 'points': points, 'outside': 'HOLD', 'required': True, 'evidence': E}
    thermal = lambda points: response('warmest_month_temperature_c', 'degC', points)
    water_response = lambda points: response('annual_precipitation_to_reference_pet_ratio', '1', points)
    definitions = [
        (1, [], 'NONVEGETATED', [response('snow_persistence_fraction', '1', [[0, 0], [0.5, 0.1], [1, 1]]), thermal([[-40, 1], [0, 1], [5, 0.3], [12, 0], [45, 0]])]),
        (2, ['alpine'], 'ANY', [thermal([[-40, 0], [-5, 0.5], [8, 1], [16, 0], [45, 0]])]),
        (3, ['conifer'], 'ANY', [thermal([[-40, 0], [5, 0.2], [10, 1], [20, 0], [45, 0]])]),
        (4, ['conifer'], 'ANY', [thermal([[-40, 0], [4, 0.1], [12, 1], [24, 0], [45, 0]])]),
        (5, ['conifer', 'temperate'], 'ALL', [thermal([[-40, 0], [8, 0.2], [15, 1], [27, 0], [45, 0]])]),
        (6, ['macroforest'], 'ANY', [thermal([[-40, 0], [9, 0], [17, 1], [30, 1], [45, 0]]), water_response([[0, 0], [0.6, 0.1], [1.5, 1], [10, 1]])]),
        (7, ['temperate'], 'ANY', [thermal([[-40, 0], [5, 0], [18, 1], [30, 0.7], [45, 0]])]),
        (8, ['temperate', 'grass'], 'ALL', [water_response([[0, 0], [0.3, 0.5], [0.8, 1], [1.5, 0.3], [4, 0]])]),
        (9, ['grass'], 'ANY', [water_response([[0, 0], [0.4, 0.3], [1, 1], [4, 1]])]),
        (10, ['steppe'], 'ANY', [water_response([[0, 1], [0.4, 1], [1, 0.2], [2, 0], [10, 0]])]),
    ]
    families = []
    for family_id, operator, demand_scale in (('R8_A', 'GEOMETRIC', 0.9), ('R8_B', 'MINIMUM', 1.0), ('R8_C', 'GEOMETRIC', 1.1)):
        families.append({'family_id': family_id, 'evidence': E + '; new coequal R8 structural/demand sensitivity, not a reused historical EP1 family',
            'pft_score_rules': {ident: {'metric': 'active_actual_to_potential_transpiration_ratio', 'unit': '1',
                                      'points': [[0, 0], [1, 1]], 'evidence': E + '; transparent water adequacy support, not NPP or occurrence probability'} for ident in pfts},
            'formations': [{'code': code, 'pft_ids': ids, 'pft_operator': pft_operator,
                            'responses': responses, 'factor_operator': operator, 'evidence': E + '; qualitative potential formation semantics retained, new explicit synthetic response curves'} for code, ids, pft_operator, responses in definitions]})
    return {'schema': binding.RECIPE_SCHEMA, 'source_status': 'WORKING NON-CANON', 'source_sha256': bundle.source_sha256,
            'evidence': E, 'soil_recipe': soil, 'seasonal': seasonal, 'pfts': pfts, 'families': families,
            'family_demand_multipliers': {'R8_A': 0.9, 'R8_B': 1.0, 'R8_C': 1.1},
            'cell_context': {cell: {'domain': {'kind': 'LAND', 'evidence': E + '; independent explicit land mask', 'source_status': 'SYNTHETIC TEST'},
                                   'external_gates': {'aeration': {'status': 'PASS', 'evidence': E + '; explicitly drained, non-inundated matrix scenario; not inferred from the 30-second water probe'}}} for cell in cell_ids},
            'classification_controls': {'low_support_threshold': 0.1, 'broad_margin': 0.1, 'formation_margin': 0.1, 'tie_tolerance': 1e-12},
            'edges': [{'a': 'upper', 'b': 'lower', 'length_m': 1000., 'evidence': E + '; declared physical transect adjacency, no implicit circular wrap'}],
            'actual_vegetation_overlays': [],
            'limits': 'Hydrothermal/chemical-regime potential only; nutrient sufficiency, competition, disturbance, actual cover and species occupancy not solved.'}


def verification_reference(bundle):
    return bundle.run(recipe(bundle))
