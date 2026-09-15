"""Small explicitly synthetic supplied landscapes; not replacement Diadem terrain."""
from copy import deepcopy
from fractions import Fraction as F
from work.generator_upgrade_r13 import soil
from .pipeline import SCHEMA

EVIDENCE = 'SYNTHETIC TEST: supplied SI material and reduced response coefficients; not Diadem calibration'
STATUS = {'evidence': EVIDENCE, 'source_status': 'SYNTHETIC TEST'}


def recipe(*, duration_s=600., event_count=2, erosion=True):
    layer = {'layer_id': 'mineral', 'thickness_m': .2, 'theta_r': .03, 'theta_s': .4,
             'vg_alpha_per_m': 2., 'vg_n': 2., 'mualem_l': .5,
             'saturated_conductivity_m_s': 1e-6, 'ice_impedance': 7.,
             'dry_heat_capacity_j_m3_k': 1.4e6, 'conductivity_dry_w_m_k': .25,
             'conductivity_saturated_unfrozen_w_m_k': 1.6,
             'conductivity_saturated_frozen_w_m_k': 2.2, **STATUS}
    constants = {'water_density_kg_m3': 1000., 'water_heat_capacity_j_kg_k': 4180.,
                 'ice_heat_capacity_j_kg_k': 2100., 'latent_heat_j_kg': 334000.,
                 'melting_temperature_k': 273.15, 'gravity_m_s2': 9.80665}
    model = {'layers': [layer], 'constants': constants, 'freezing_model': soil.PAINTER_KARRA,
             'clapeyron_beta': 1., **STATUS}
    initial = soil.initial_state(model, [-1.], [280.])
    mass = F(2600)*F(layer['thickness_m'])*(1-F(layer['theta_s']))
    material = {'material_id': 'mineral', 'phase': 'immobile_regolith',
                'grain_density_kg_m3': 2600., 'dry_mass_kg_m2': str(mass), 'evidence': EVIDENCE}
    cells = {}
    for name, area, base in (('upper', 1., 1.), ('lower', 2., 0.)):
        water = .02*area
        cells[name] = {'area_m2': area, 'base_elevation_m': base,
            'model': deepcopy(model), 'soil': deepcopy(initial), 'materials': [deepcopy(material)],
            'surface_water_m3': water,
            'surface_enthalpy_j': water*1000.*(334000.+4180.*(280.-273.15)),
            'surface_residence_seconds': 86400.}
    wref = initial['total_water'][0]*layer['thickness_m']/float(mass)
    deformation = {'reference_specific_volume_m3_kg': layer['thickness_m']/float(mass),
        'reference_water_m3_kg': wref, 'reference_ice_m3_kg': 0.,
        'water_volume_response': .2, 'ice_volume_response': .02,
        'relaxation_time_s': 86400., 'min_porosity': .2, 'max_porosity': .7,
        'reference_porosity': .4, 'reference_ksat_m_s': 1e-6,
        'reference_alpha_per_m': 2., 'ksat_porosity_exponent': 3.,
        'alpha_porosity_exponent': 1., 'mechanical_energy_per_bulk_volume_j_m3': 0., **STATUS}
    def prop(name, value, unit):
        return {'name': name, 'value': value, 'unit': unit,
                'evidence': EVIDENCE, 'status': 'SYNTHETIC TEST'}
    erosion_laws = [{'material_id': 'mineral', 'phase': phase,
        'k_per_year': prop('erosion_coefficient_at_reference_runoff', .05 if erosion else 0., '1/year'),
        'reference_runoff_m_year': prop('reference_runoff', 1., 'm/year')}
        for phase in ('immobile_regolith', 'mobile_sediment')]
    soil_controls = {'initial_step_s': 60., 'min_step_s': 1e-10, 'max_step_s': 86400.,
        'max_steps': 4000, 'max_nonlinear_evaluations': 80,
        'water_atol_m': 1e-8, 'nonlinear_water_atol_m': 1e-11,
        'energy_atol_j_m2': .1, 'nonlinear_energy_atol_j_m2': 1e-4,
        'head_atol_m': .001, 'temperature_atol_k': .001,
        'water_fraction_atol': 1e-5, 'relative_tolerance': 1e-4,
        'min_head_m': -1000., 'max_head_m': 100., 'min_temperature_k': 230., 'max_temperature_k': 330.}
    events = []
    for i in range(event_count):
        forcing = {'duration_s': duration_s, 'surface_water_flux_m_s': (1e-8, 0., 5e-9)[i % 3],
            'root_withdrawal_m_s': [0.],
            'surface_water_temperature_k': 280.,
            'top_heat': {'kind': 'temperature', 'value': (280., 283., 278.)[i % 3], **STATUS},
            'bottom_heat': {'kind': 'temperature', 'value': 280., **STATUS},
            'bottom_water': {'kind': 'free_drainage', **STATUS}, **STATUS}
        events.append({'event_id': 'controlled-period-'+str(i+1), 'duration_s': duration_s,
                       'forcing': {key: deepcopy(forcing) for key in cells}, **STATUS})
    scenario = 'R14_CONTROLLED_GROUND_FEEDBACK'
    return {'schema': SCHEMA, 'scenario_id': scenario, **STATUS,
        'context': {'world_id': 'SYNTHETIC_NOT_DIADEM', 'snapshot_id': 'CONTROLLED_COLUMNS',
            'calendar_id': 'EXPLICIT_SECONDS_NO_YEAR_CLAIM', 'spatial_frame_id': 'SUPPLIED_COLUMN_ADJACENCY_METRES',
            'vertical_reference': 'FIXED_LOCAL_BASE_METRES_UP', 'scenario_id': scenario},
        'seconds_per_year': 31536000., 'cells': cells,
        'connectors': [{'connector_id': 'upper-lower', 'source_id': 'upper', 'receiver_id': 'lower',
                        'length_m': 10., 'outlet_elevation_m': None, 'evidence': EVIDENCE},
                       {'connector_id': 'lower-exterior', 'source_id': 'lower', 'receiver_id': None,
                        'length_m': 10., 'outlet_elevation_m': -1., 'evidence': EVIDENCE}],
        'erosion_laws': erosion_laws,
        'sediment_laws': [{'material_id': 'mineral', 'settling_m_year': 50.,
                          'deposited_porosity': .4, 'deposition_order': 0, 'evidence': EVIDENCE}],
        'deposition_templates': {'mineral': deepcopy(layer)},
        'deformation_laws': {'mineral': deformation}, 'soil_controls': soil_controls,
        'terrain_controls': {'max_relief_change_fraction': .25, 'max_solid_liquid_ratio': .1, 'evidence': EVIDENCE},
        'coupling_controls': {'initial_step_s': min(86400., duration_s), 'min_step_s': .01,
            'max_step_s': min(86400., duration_s), 'max_attempts': 200,
            'relative_tolerance': .01, 'height_atol_m': 1e-4, 'water_atol_m3': 1e-4,
            'energy_atol_j': 30000., 'mass_atol_kg': .01,
            'head_integral_atol_m2': .001, 'temperature_integral_atol_k_m': .01,
            'budget_water_atol_m3': 1e-7, 'budget_energy_atol_j': 1.},
        'events': events}
