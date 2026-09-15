"""Explicit bounded seasonal hypotheses, not adopted Diadem calibration."""
from copy import deepcopy
from . import binding

E='SYNTHETIC TEST: one representative year starting from retained formed-profile heads and organic pools; no historical or whole-Diadem climate calibration'


def recipe(bundle):
    parent=bundle.parent.reference.recipe(bundle.parent)
    physical=parent['parent_recipe']
    cells=sorted(physical['cell_context'])
    controls=deepcopy(physical['soil_recipe']['water_consumer']['controls'])
    controls['max_dt_s']=86400.
    hypotheses={}
    for family in sorted(physical['family_demand_multipliers']):
        hypotheses['TEMPERATE_'+family]={
            'pft_id':'temperate','family_id':family,'evidence':E+'; separate counterfactual temperate-stand hydraulic demand using the exact existing PFT/family multiplier',
            'source_status':'SYNTHETIC TEST',
            'columns':{cell:{'root_boundary_above_layer_id':cell+'-substrate',
                'root_weights_by_layer':{cell+'-mineral':1.},
                'uptake':{'dry_zero_head_m':-100.,'dry_full_head_m':-1.,'wet_full_head_m':-.1,'wet_zero_head_m':0.,
                    'evidence':E+'; explicit Feddes stress and concentrated mineral-layer roots, not inferred from rooted water capacity','source_status':'SYNTHETIC TEST'},
                'boundary':{'kind':'no_flow','head_m':None,'evidence':E+'; explicit impermeable lower-boundary sensitivity, not inferred aquifer geology','source_status':'SYNTHETIC TEST'},
                'initial_condition':'RETAINED_FORMED_PROBE_FINAL_HEADS_ALIGNED_TO_YEAR_START',
                'initial_condition_evidence':E+'; retained water probe end is independently designated Jan1; original30s elapsed clock is retained, not a spin-up or equilibrium',
                'soil_thermal_regime':'UNFROZEN_CONDITIONAL',
                'thermal_evidence':E+'; unfrozen liquid-matrix experiment including cold-air intervals; actual soil heat, ice fraction and freezing hydraulic response remain unresolved',
                'evidence':E} for cell in cells}}
    return {'schema':binding.RECIPE_SCHEMA,'source_sha256':bundle.source_sha256,'source_status':'WORKING NON-CANON',
        'evidence':E,'parent_recipe':parent,'hydraulic_hypotheses':hypotheses,
        'hydraulic_controls':controls,'water_density_kg_m3':1000.,'gravity_m_s2':9.81,
        'duration_atol_s':1e-6,'budget_atol_m':1e-6,
        'carbon':{'selected_layer_suffixes':['-mineral','-organic-mantle'],
            'soil_temperature_k_by_month':[275.,276.,279.,284.,289.,293.,295.,294.,290.,285.,279.,276.],
            'fast_litter_carbon_kg_m2_s_by_month':[0.,0.,1e-10,2e-10,3e-10,4e-10,4e-10,3e-10,2e-10,2e-9,1e-9,0.],
            'slow_litter_carbon_kg_m2_s_by_month':[0.]*12,'redox':'OXIC',
            'regime_by_suffix':{'-mineral':'AERATED_MINERAL','-organic-mantle':'ORGANIC_DOMINATED'},
            'evidence':E+'; independently declared soil-temperature/redox/litter experiment, not air temperature, observed litter or inferred oxygen; event-start liquid WFPS held as a diagnostic approximation; fixed geometry is not updated',
            'source_status':'SYNTHETIC TEST'},
        'limits':'Representative seasonal states and explicit conditional experiments only; no soil heat/freezing, routed rivers/lakes, nutrient transport, plant growth/yields, food availability, transport disruption, demographic history or seasonal political relocation inferred.'}


def verification_reference(bundle):
    return bundle.run(recipe(bundle))
