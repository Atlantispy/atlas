"""Explicit synthetic scientific case, not calibrated Diadem soil defaults."""
from . import binding

EVIDENCE='SYNTHETIC TEST: explicit mineral-only columns, natural litter and finite trace-element assay; illustrative SI physical/chemical hypotheses, not Diadem calibration or reconstructed soil history'


def recipe(bundle):
    parent=bundle.parent.reference.recipe()
    controls=parent['physical_recipe']['water_controls']
    controls.update(integration_method='SDIRK2',min_dt_s=1e-14,max_steps=10000)
    parent=bundle.parent.wrap_recipe(parent,evidence=EVIDENCE+'; actual all-three-member climate/terrain/water producer, retained default accuracy bounds')
    keys=('substrate|bedrock','substrate|immobile_regolith','substrate|mobile_sediment','mineral|immobile_regolith','mineral|mobile_sediment')
    materials={key:{'particle_mass_fractions':['1/10','1/2','3/10','1/10'],
        'inherited_horizon_candidates':['R'] if key.endswith('|bedrock') else ['C'],
        'cec_cmolc_kg_by_fine_size':[1.,5.,20.],
        'reserve_mass_fractions':{'N':0.0001,'P':0.0002,'K':0.001},
        'labile_mass_fractions':{'N':0.00001,'P':0.00002,'K':0.0001},'evidence':EVIDENCE+'; explicit four-size/minor-element composition, no clay mineralogy inferred'} for key in keys}
    organic_law={'fast_rate_per_s':1e-8,'slow_rate_per_s':1e-9,'fast_to_slow_fraction':0.25,'carbon_fraction_dry_matter':0.5,
        'reference_temperature_k':283.15,'fast_activation_energy_j_mol':30000.,'slow_activation_energy_j_mol':30000.,
        'gas_constant_j_mol_k':8.314462618,'minimum_temperature_k':260.,'maximum_temperature_k':320.,
        'moisture_curve':[[0.,0.],[0.6,1.],[1.,0.4]],'redox_factors':[['OXIC',1.,1.],['ANOXIC',0.1,0.1]],
        'regimes':['AERATED_MINERAL','ORGANIC_DOMINATED'],'evidence':EVIDENCE+'; explicitly oxic despite high WFPS sensitivity; same supplied coefficients separately admitted for synthetic mineral mixture and organic mantle, not universal peat','source_status':'SYNTHETIC TEST'}
    chemistry={'chemistry_id':'synthetic-common-assay','ph_water':6.5,'electrical_conductivity_ds_m':0.2,
        'cec_method':'EXPLICIT_FIXED_PH_6_5_REFERENCE','evidence':EVIDENCE+'; fixed joint pH/salinity/exchange hypothesis, not predicted field chemistry'}
    nutrient_laws=[{'nutrient':n,'release_per_s':1e-8,'kd_m3_kg':0. if n=='N' else 0.001,
        'available_fraction':0.5,'reference_temperature_k':283.15,'activation_energy_j_mol':30000.,
        'gas_constant_j_mol_k':8.314462618,'chemistry_id':chemistry['chemistry_id'],
        'species':'NITRATE_N' if n=='N' else 'EXPLICIT_TRACE_'+n,'evidence':EVIDENCE+'; net mobilisation, Kd per complete fine-earth plus organic assay mass, no full speciation'} for n in ('N','P','K')]
    hydraulic={}
    for key in (*keys,'organic|organic_mantle'):
        phi=0.7 if key.startswith('organic|') else 0.4 if key=='substrate|immobile_regolith' else 0.25
        hydraulic[key]={'porosity':phi,'density_protocol':'ADDITIVE_EXPLICIT_MINERAL_ORGANIC_SOLID_VOLUMES',
            'theta_r':0.02,'alpha_per_m':2.,'n':2.,'mualem_l':0.5,'ksat_m_s':1e-5 if key.startswith('organic|') else 1e-6,
            'evidence':EVIDENCE+'; prescribed joint packing/retention/Ksat case, not texture-derived hydraulic estimation'}
    return {'schema':binding.RECIPE_SCHEMA,'source_status':'WORKING NON-CANON','source_sha256':bundle.source_sha256,'evidence':EVIDENCE,
        'parent_recipe':parent,'parent_mass_interpretation':'MINERAL_ONLY_WITH_SEPARATE_EXPLICIT_ORGANIC_INVENTORY',
        'soil_exposures':[{'exposure_id':'declared-soil-stage-'+str(i),'duration_seconds':31536000,
            'evidence':EVIDENCE+'; independently supplied 31536000-second fixed-exposure stage, not derived from the 240-second parent run'} for i in (1,2)],
        'temperature_hypothesis':{'air_to_soil_offset_k':0.,'evidence':EVIDENCE+'; soil temperature held equal to actual time-weighted parent air temperature; no thermal model'},
        'materials':materials,
        'formation':{'laws':[{'material_id':'substrate','bare_rate_m_s':1e-9,'cover_scale_m':0.5,'regolith_porosity':0.4,
            'dissolved_mass_fraction':0,'reference_temperature_k':283.15,'activation_energy_j_mol':30000.,'gas_constant_j_mol_k':8.314462618,
            'minimum_temperature_k':260.,'maximum_temperature_k':320.,'regime':'DEPTH_LIMITED_NONSELECTIVE_ROCK_DISAGGREGATION',
            'evidence':EVIDENCE+'; finite stock disaggregation, zero bulk dissolution in separate trace-assay regime','source_status':'SYNTHETIC TEST'}],
            'fragmentation':{'rate_per_second':1e-9,'reference_temperature_k':283.15,'activation_energy_j_mol':30000.,
                'gas_constant_j_mol_k':8.314462618,'minimum_temperature_k':260.,'maximum_temperature_k':320.,'evidence':EVIDENCE+'; explicit size-only fragmentation, no chemical clay production'},
            'horizon_protocol':{'protocol_id':'synthetic-carbon-enrichment','carbon_enrichment_threshold_low':'1/2000',
                'carbon_enrichment_threshold_high':'1/1000','evidence':EVIDENCE+'; illustrative operational A/C diagnostic, not adopted taxonomy'},
            'parent_carbon_ratio':[0,0],'production_moisture_hypothesis':'PARENT_COLUMN_FINAL_WFPS_HELD_BULK_PRODUCTION_SENSITIVITY','evidence':EVIDENCE},
        'organic':{'law':organic_law,'initial_carbon_per_kg_mineral':[0,0],'surface_initial_carbon_kg_m2':[0,0],
            'fast_litter_carbon_per_kg_mineral_s':5e-11,'slow_litter_carbon_per_kg_mineral_s':0.,
            'surface_fast_litter_carbon_kg_m2_s':1e-9,'surface_slow_litter_carbon_kg_m2_s':0.,
            'grain_density_kg_m3':1500.,'surface_porosity':0.7,
            'mixture_porosity_by_material':{key:(0.4 if key=='substrate|immobile_regolith' else 0.25) for key in keys if not key.endswith('|bedrock')},
            'redox':'OXIC','regime':'AERATED_MINERAL','surface_regime':'ORGANIC_DOMINATED',
            'surface_moisture_hypothesis':'PARENT_COLUMN_FINAL_WFPS_HELD_HOMOGENISATION',
            'new_material_exposure':'NEW_COHORT_ZERO_AGE_THEN_HELD_PARENT_COLUMN_WFPS',
            'evidence':EVIDENCE+'; all organic mass arrives as explicit natural litter; additive constituent solid volumes plus supplied joint packing'},
        'fertility':{'chemistry':chemistry,'laws':nutrient_laws,'protocol':{'protocol_id':'synthetic-natural-reference',
            'nitrogen_reference_kg_m2':0.01,'phosphorus_reference_kg_m2':0.01,'potassium_reference_kg_m2':0.05,
            'exchange_reference_cmolc_m2':1000.,'evidence':EVIDENCE+'; explicit half-response scales, not universal biological requirement'},
            'assay_duration_s':31536000.,'organic_cec_cmolc_kg':150.,'upward_concentrations_kg_m3':{'N':0.,'P':0.,'K':0.},
            'organic_reserve_mass_fractions':{'N':0.01,'P':0.001,'K':0.002},
            'organic_labile_mass_fractions':{'N':0.001,'P':0.0001,'K':0.0002},
            'organic_chemistry_evidence':EVIDENCE+'; separate current formed organic elemental composition hypothesis, not nutrient prediction from carbon dynamics',
            'natural_reference_evidence':EVIDENCE+'; separate one-year open fixed-water reference assay on current formed soil; unequal flows use mathematical solute-free water exchange, not irrigation or R6 transient replay; no future nutrient influx, explicit zero capillary concentrations'},
        'water_consumer':{'laws':hydraulic,'initial_pore_saturation':0.6,'reservoir_water_m':1.,'duration_seconds':30.,
            'surface_input_m_s':0.,'boundary':{'kind':'free_drainage','head_m':None,'evidence':EVIDENCE,'source_status':'SYNTHETIC TEST'},
            'controls':dict(controls),'water_density_kg_m3':1000.,'gravity_m_s2':9.81,'evidence':EVIDENCE+'; fresh formed-profile no-ET water probe with explicit reservoir and initial redistribution'}}


def verification_reference(bundle):
    return bundle.run(recipe(bundle))
