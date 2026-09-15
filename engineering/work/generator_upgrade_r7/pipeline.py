"""Actual preserved producer -> explicit fixed-exposure pedogenesis reference.

The independently declared soil-exposure time is not inferred from the short
climate experiment. No antecedent pressure is certified on changed geometry.
"""
from dataclasses import asdict, replace
from fractions import Fraction as F
import math

from . import binding


def plain(value):
    if isinstance(value,F): return str(value)
    if hasattr(value,'__dataclass_fields__'): return plain(asdict(value))
    if type(value) is dict: return {str(k):plain(v) for k,v in value.items()}
    if type(value) in (tuple,list): return [plain(v) for v in value]
    return value


def number(value,name,*,positive=False,maximum=1e13):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0 or value>maximum or (positive and value==0):
        raise ValueError(name+' needs explicit finite supported number')
    return float(value)


def text(value,name):
    if type(value) is not str or not value.strip() or len(value)>4096:
        raise ValueError(name+' needs explicit bounded evidence')
    return value


def exact(value,keys,name):
    if type(value) is not dict or set(value)!=set(keys):
        raise ValueError(name+' exact field inventory differs')
    return value


def extract_exposure(bundle,parent_result,*,air_to_soil_offset_k,temperature_evidence):
    """Keep actual temporal/spatial support explicit; never invent layer means."""
    if (type(parent_result) is not dict or parent_result.get('schema')!='diadem.strict-soil-water-result.r6'
            or parent_result.get('source_sha256')!=bundle.parent.source_sha256):
        raise ValueError('actual source-bound R6 producer result required')
    if type(air_to_soil_offset_k) not in (int,float) or not math.isfinite(air_to_soil_offset_k) or abs(air_to_soil_offset_k)>100:
        raise ValueError('explicit supported air-to-soil temperature hypothesis required')
    text(temperature_evidence,'air-to-soil temperature evidence')
    result_sha = bundle.storage.sha(bundle.storage.encoded(parent_result))
    output = {}
    for scenario,member in parent_result['state']['members'].items():
        physical=member['physical']; history=member['joint_history']
        if not history or not physical['water']:
            raise ValueError('completed actual climate and Water intervals required')
        total=F(0); end=F(0)
        for row in history:
            start=F(row['start_seconds']); dt=F(row['duration_seconds'])
            if start!=end or dt<=0: raise ValueError('climate exposure history is not contiguous')
            total+=dt; end+=dt
        if end!=F(physical['elapsed']): raise ValueError('climate/physical duration differs')
        cells={}
        for cell,record in physical['profiles'].items():
            profile=bundle.parent.r3.si.HydraulicProfile.from_dict(record)
            rows=bundle.parent.r3.si.hydraulic_rows(profile)
            water=physical['water'][cell]
            if water['status']!='MODELLED' or len(rows)!=len(water['layers']):
                raise ValueError('current complete layer Water output required')
            dt=F(water['forcing']['duration_seconds'])
            if dt<=0 or F(water['state']['elapsed_seconds'])!=end:
                raise ValueError('last Water interval support differs')
            air=sum((F(r['cells'][cell]['temperature_c'])*F(r['duration_seconds']) for r in history),F())/total
            soil=float(air)+273.15+air_to_soil_offset_k
            if not 200<=soil<=350: raise ValueError('soil temperature hypothesis outside admitted regime')
            layers=[]
            for i,(row,solved) in enumerate(zip(rows,water['layers'])):
                if row['layer_id']!=solved['layer_id']:
                    raise ValueError('actual material and Water layer identities differ')
                wfps=float(row['theta']/row['theta_s'])
                if not 0<=wfps<=1: raise ValueError('actual physical WFPS outside pore capacity')
                layers.append({**plain(row),'mineral_mass_kg_m2':str(row['mass_kg']/profile.column.area_m2),
                    'water_storage_m':str(row['water_volume_m3']/profile.column.area_m2),
                    'wfps':wfps,'downward_m_s':float(F(water['ledger']['face_downward_m'][i+1])/dt),
                    'upward_m_s':float(F(water['ledger']['face_upward_m'][i+1])/dt),
                    'water_state_id':bundle.storage.sha(bundle.storage.encoded([result_sha,scenario,cell,solved,water['ledger']])),
                    'moisture_support':'FINAL_ACTUAL_LAYER_STATE_HELD_FIXED_NOT_TEMPORAL_MEAN',
                    'flux_support':'FINAL_ACTUAL_WATER_INTERVAL_GROSS_FACE_INTEGRAL_DIVIDED_BY_ITS_DURATION'})
            volume=sum((l.bulk_volume_m3 for l in profile.column.layers),F())
            pores=sum((l.bulk_volume_m3*l.porosity for l in profile.column.layers),F())
            cells[cell]={'profile_id':profile.profile_id,'area_m2':str(profile.column.area_m2),
                'base_elevation_m':str(profile.column.basal_elevation_m),'surface_elevation_m':str(profile.column.surface_m),
                'parent_porewater_m':str(profile.water_volume_m3/profile.column.area_m2),
                'parent_surface_water_m':str(F(physical['surface'][cell])/profile.column.area_m2),
                'profile_wfps':float(profile.water_volume_m3/pores),
                'profile_water_storage_m':float(profile.water_volume_m3/profile.column.area_m2),
                'downward_m_s':float(F(water['ledger']['bottom_downward_m'])/dt),
                'upward_m_s':float(F(water['ledger']['bottom_upward_m'])/dt),
                'climate_air_temperature_c':float(air),'soil_temperature_k':soil,
                'climate_duration_seconds':str(total),'last_water_duration_seconds':str(dt),
                'temperature_evidence':temperature_evidence,'air_to_soil_offset_k':air_to_soil_offset_k,
                'water_state_id':bundle.storage.sha(bundle.storage.encoded([result_sha,scenario,cell,water])),
                'layers':layers,'parent_water_ledger':water['ledger'],
                'source_status':profile.source_status}
        output[scenario]=cells
    return {'schema':'diadem.actual-soil-exposure.r7','parent_result_sha256':result_sha,
        'parent_source_sha256':bundle.parent.source_sha256,'members':output,
        'scope':'SHORT GENERATED CLIMATE/WATER REFERENCE; fixed-exposure hypothesis only; no annual climatology, historical layer mean, thermal model or inferred pedogenic age'}


def postformation_water(bundle,geometry,support,options):
    """Actual R6 consumer on new geometry, with a declared mixing experiment.

    Porewater and available surface water are mixed once. The finite external
    reservoir supplies only a deficit; remaining water stays explicitly at the
    surface. This is an initial-condition experiment, not resolved capillarity
    during soil formation. The subsequent pressure is genuinely solved.
    """
    if options is None:
        return {'status':'REQUIRES_WATER_RECOMPUTATION','reason':'No explicit new geometry hydraulic/initial-water/probe law supplied'}
    exact(options,('laws','initial_pore_saturation','reservoir_water_m','duration_seconds',
        'surface_input_m_s','boundary','controls','water_density_kg_m3','gravity_m_s2','evidence'), 'fresh Water consumer')
    evidence=text(options['evidence'],'explicit formed-soil Water reference evidence')
    saturation=number(options['initial_pore_saturation'],'initial pore saturation',positive=True,maximum=1)
    if saturation==1: raise ValueError('bounded probe requires finite unsaturated initial head, not inferred saturated pressure')
    reservoir=F(number(options['reservoir_water_m'],'finite supplied wetting reservoir'))
    sw=bundle.parent.solver; layers=[]; depths=[]
    if type(geometry) is not list or not 1<=len(geometry)<=128: raise ValueError('bounded formed geometry required')
    for row in geometry:
        key=row['material_id']+'|'+row['phase']
        if key not in options['laws']: raise ValueError('new formed material requires its explicit joint hydraulic law: '+key)
        law=exact(options['laws'][key],('porosity','density_protocol','theta_r','alpha_per_m','n','mualem_l','ksat_m_s','evidence'),'joint material hydraulic law')
        if F(law['porosity'])!=F(row['porosity']) or law['density_protocol']!='ADDITIVE_EXPLICIT_MINERAL_ORGANIC_SOLID_VOLUMES':
            raise ValueError('new physical packing/density and hydraulic law differ')
        dz=F(row['thickness_m']); depths.append(dz)
        if dz<=0: raise ValueError('positive actual layer thickness required')
        layers.append(sw.HydraulicLayer(row['layer_id'],float(dz),law['theta_r'],float(F(row['porosity'])),
            law['alpha_per_m'],law['n'],law['mualem_l'],law['ksat_m_s'],law['evidence'],'SYNTHETIC TEST'))
    column=sw.Column(support['profile_id']+'-formed-probe',tuple(layers),len(layers),
        evidence+'; root diagnostic face is column base, no biological root-depth claim','SYNTHETIC TEST')
    heads=tuple(sw.head_from_theta(layer,layer.theta_s*saturation) for layer in layers)
    initial=sw.initial_state(column,heads,elapsed_seconds=0)
    actual_initial=sum((F(sw.hydraulic_properties(layer,h)[0])*dz for layer,h,dz in zip(layers,heads,depths)),F())
    antecedent=F(support['parent_porewater_m'])+F(support['parent_surface_water_m'])
    withdrawal=max(F(),actual_initial-antecedent)
    if withdrawal>reservoir: raise ValueError('explicit wetting reservoir insufficient for new physical initial condition')
    surface=max(F(),antecedent-actual_initial)
    if antecedent+withdrawal!=actual_initial+surface: raise ArithmeticError('exact initial redistribution ledger failed')
    forcing=sw.Forcing(number(options['duration_seconds'],'probe duration',positive=True),
        number(options['surface_input_m_s'],'probe liquid flux',maximum=1),0.,None,evidence,'SYNTHETIC TEST')
    result=sw.advance(column,initial,forcing,sw.Boundary(**options['boundary']),sw.Controls(**options['controls']),
        water_density_kg_m3=options['water_density_kg_m3'],gravity_m_s2=options['gravity_m_s2'])
    if result['status']!='MODELLED': raise ValueError('formed-soil actual Water consumer failed: '+result['status']+': '+result['reason'])
    final=sum((F(row['theta_m3_m3'])*dz for row,dz in zip(result['layers'],depths)),F())
    ledger=result['ledger']; final_surface=surface+F(ledger['surface_runoff_m'])
    final_reservoir=reservoir-withdrawal
    residual=antecedent+reservoir+F(ledger['surface_input_m'])+F(ledger['bottom_upward_m'])-final-final_surface-final_reservoir-F(ledger['bottom_downward_m'])-F(ledger['actual_et_m'])
    if abs(float(residual))>options['controls']['total_mass_atol_m']:
        raise ArithmeticError('physical formed-soil porewater/surface/reservoir budget failed')
    return {'status':'MODELLED_NEW_GEOMETRY_WATER_PROBE','geometry_sha256':bundle.storage.sha(bundle.storage.encoded(plain(geometry))),
        'column':plain(column),'initial_head_status':'EXPLICIT_REDISTRIBUTION_NUMERICAL_INITIAL_CONDITION_NOT_BORROWED_PARENT_PRESSURE',
        'result':plain(result),'inputs':options,'water_accounting':{
            'parent_porewater_m':support['parent_porewater_m'],'parent_surface_water_m':support['parent_surface_water_m'],
            'reservoir_initial_m':str(reservoir),'reservoir_withdrawal_m':str(withdrawal),'reservoir_final_m':str(final_reservoir),
            'formed_initial_porewater_m':str(actual_initial),'formed_final_porewater_m':str(final),
            'surface_after_redistribution_m':str(surface),'surface_final_m':str(final_surface),
            'external_liquid_m':ledger['surface_input_m'],'bottom_in_m':ledger['bottom_upward_m'],
            'bottom_out_m':ledger['bottom_downward_m'],'actual_et_m':ledger['actual_et_m'],
            'physical_numerical_residual_m':str(residual)},
        'scope':'one fresh actual soil-water solve; climate, terrain routing, erosion laws and stability need their own changed-geometry rebind before adoption'}


def parse(bundle,recipe):
    s=bundle.storage; recipe=s.decoded(s.encoded(recipe))
    exact(recipe,('schema','source_status','source_sha256','evidence','parent_recipe','parent_mass_interpretation',
        'soil_exposures','temperature_hypothesis','materials','formation','organic','fertility','water_consumer'),'R7 recipe')
    if (recipe['schema']!=binding.RECIPE_SCHEMA or recipe['source_sha256']!=bundle.source_sha256
            or recipe['source_status']!='WORKING NON-CANON'
            or recipe['parent_mass_interpretation']!='MINERAL_ONLY_WITH_SEPARATE_EXPLICIT_ORGANIC_INVENTORY'):
        raise ValueError('exact source-bound R7 recipe and mineral-only interpretation required')
    text(recipe['evidence'],'soil scenario evidence')
    rows=recipe['soil_exposures']
    if type(rows) is not list or not 1<=len(rows)<=8: raise ValueError('one to eight explicitly bounded soil exposures required')
    for row in rows:
        exact(row,('exposure_id','duration_seconds','evidence'),'soil exposure')
        text(row['exposure_id'],'exposure ID'); text(row['evidence'],'soil age evidence')
        number(row['duration_seconds'],'soil exposure seconds',positive=True)
    if len({r['exposure_id'] for r in rows})!=len(rows): raise ValueError('repeated soil exposure ID')
    exact(recipe['temperature_hypothesis'],('air_to_soil_offset_k','evidence'),'temperature hypothesis')
    if type(recipe['materials']) is not dict or not 1<=len(recipe['materials'])<=128: raise ValueError('explicit material property cases required')
    for key,row in recipe['materials'].items():
        exact(row,('particle_mass_fractions','inherited_horizon_candidates','cec_cmolc_kg_by_fine_size',
            'reserve_mass_fractions','labile_mass_fractions','evidence'),'material composition')
        text(key,'material identity'); text(row['evidence'],'material evidence')
        fractions=row['particle_mass_fractions']
        if type(fractions) is not list or len(fractions)!=4: raise ValueError('explicit four-class particle fractions required')
        if any(type(v) not in (str,int,float) for v in fractions): raise ValueError('particle fractions are explicit numbers, not booleans')
        values=[F(v) for v in fractions]
        if any(v<0 for v in values) or sum(values,F())!=1: raise ValueError('exact material particle fractions must sum to one')
        total=F()
        for name in ('reserve_mass_fractions','labile_mass_fractions'):
            exact(row[name],('N','P','K'),'elemental concentration')
            total+=sum((F(number(v,'elemental mass fraction',maximum=1)) for v in row[name].values()),F())
        if total>1: raise ValueError('elemental assay inventory exceeds finite actual dry material')
        if type(row['cec_cmolc_kg_by_fine_size']) is not list or len(row['cec_cmolc_kg_by_fine_size'])!=3:
            raise ValueError('explicit sand/silt/clay-size CEC coefficients required')
    exact(recipe['formation'],('laws','fragmentation','horizon_protocol','parent_carbon_ratio','production_moisture_hypothesis','evidence'),'formation case')
    if recipe['formation']['production_moisture_hypothesis']!='PARENT_COLUMN_FINAL_WFPS_HELD_BULK_PRODUCTION_SENSITIVITY':
        raise ValueError('explicit bulk rock-production moisture support required')
    if any(F(row['dissolved_mass_fraction'])!=0 for row in recipe['formation']['laws']):
        raise ValueError('this connected trace-assay regime requires no unmodelled bulk dissolution')
    exact(recipe['organic'],('law','initial_carbon_per_kg_mineral','surface_initial_carbon_kg_m2',
        'fast_litter_carbon_per_kg_mineral_s','slow_litter_carbon_per_kg_mineral_s','surface_fast_litter_carbon_kg_m2_s',
        'surface_slow_litter_carbon_kg_m2_s','grain_density_kg_m3','surface_porosity','mixture_porosity_by_material',
        'redox','regime','surface_regime','surface_moisture_hypothesis','new_material_exposure','evidence'),'organic case')
    if recipe['organic']['surface_moisture_hypothesis']!='PARENT_COLUMN_FINAL_WFPS_HELD_HOMOGENISATION':
        raise ValueError('new organic mantle requires explicit moisture exposure hypothesis')
    if recipe['organic']['new_material_exposure']!='NEW_COHORT_ZERO_AGE_THEN_HELD_PARENT_COLUMN_WFPS':
        raise ValueError('explicit new material cohort/exposure policy required')
    for key in ('initial_carbon_per_kg_mineral','surface_initial_carbon_kg_m2'):
        values=recipe['organic'][key]
        if type(values) is not list or len(values)!=2: raise ValueError('explicit fast/slow initial organic pair required')
        for value in values: number(value,'initial organic carbon')
    exact(recipe['fertility'],('chemistry','laws','protocol','assay_duration_s','organic_cec_cmolc_kg',
        'upward_concentrations_kg_m3','organic_reserve_mass_fractions','organic_labile_mass_fractions',
        'organic_chemistry_evidence','natural_reference_evidence'),'fertility case')
    organic_elements=F()
    for name in ('organic_reserve_mass_fractions','organic_labile_mass_fractions'):
        exact(recipe['fertility'][name],('N','P','K'),'current organic elemental composition')
        organic_elements+=sum((F(number(v,'organic elemental mass fraction',maximum=1)) for v in recipe['fertility'][name].values()),F())
    if organic_elements+F(recipe['organic']['law']['carbon_fraction_dry_matter'])>1:
        raise ValueError('organic carbon plus elemental stock exceeds actual organic drymass')
    text(recipe['fertility']['organic_chemistry_evidence'],'independent current organic chemistry evidence')
    if set(recipe['fertility']['upward_concentrations_kg_m3'])!={'N','P','K'} or any(v!=0 for v in recipe['fertility']['upward_concentrations_kg_m3'].values()):
        raise ValueError('inherent assay requires explicit zero future external N/P/K concentrations')
    return recipe


def _organic_law(row,om):
    row=dict(row)
    for key in ('moisture_curve','redox_factors'): row[key]=tuple(tuple(v) for v in row[key])
    row['regimes']=tuple(row['regimes'])
    return om.OrganicLaw(**row)


def _material(recipe,layer):
    key=layer.material_id+'|'+layer.phase
    if key not in recipe['materials']: raise ValueError('explicit formed material composition missing: '+key)
    return recipe['materials'][key]


def _geometry(state,organic,surface,recipe):
    """Mass and explicit additive solid volumes; no inferred packing/Ksat."""
    spec=recipe['organic']; organic_density=F(number(spec['grain_density_kg_m3'],'organic grain density',positive=True))
    rows=[]
    if surface['final_organic_dry_mass_kg_m2']>0:
        dry=F(surface['final_organic_dry_mass_kg_m2']); phi=F(spec['surface_porosity'])
        if not 0<=phi<1: raise ValueError('organic surface porosity outside physical range')
        rows.append({'layer_id':surface['layer_id'],'material_id':'organic','phase':'organic_mantle',
            'mineral_mass_kg_m2':F(),'organic_dry_mass_kg_m2':dry,'total_dry_mass_kg_m2':dry,
            'grain_density_kg_m3':organic_density,'porosity':phi,'thickness_m':dry/organic_density/(1-phi)})
    for layer in state.layers:
        row=organic.get(layer.layer_id); dry=F() if row is None else F(row['final_organic_dry_mass_kg_m2'])
        key=layer.material_id+'|'+layer.phase
        phi=layer.porosity if layer.phase=='bedrock' else F(spec['mixture_porosity_by_material'][key])
        if not layer.porosity<=phi<1: raise ValueError('bounded mixture requires explicit porosity >= mineral skeleton porosity and <1')
        mass=layer.mineral_mass_kg_m2+dry
        solid=layer.mineral_mass_kg_m2/layer.grain_density_kg_m3+dry/organic_density
        rows.append({'layer_id':layer.layer_id,'material_id':layer.material_id,'phase':layer.phase,
            'mineral_mass_kg_m2':layer.mineral_mass_kg_m2,'organic_dry_mass_kg_m2':dry,'total_dry_mass_kg_m2':mass,
            'grain_density_kg_m3':mass/solid,'porosity':phi,'thickness_m':solid/(1-phi)})
    return rows


def _assay(state,organic,surface,support,recipe,ft):
    spec=recipe['fertility']; chemistry=ft.Chemistry(**spec['chemistry']); components=[]; reserves={n:0. for n in ft.NUTRIENTS}; labile=dict(reserves)
    fine=F(); dry_organic=F(surface['final_organic_dry_mass_kg_m2'])
    for layer in state.layers:
        if layer.phase=='bedrock': continue  # Mineral solum/parent fine-earth assay, not consolidated rock.
        material=_material(recipe,layer)
        for i,mass in enumerate(layer.particle_masses_kg_m2[1:]):
            fine+=mass
            components.append(ft.ExchangeComponent(layer.layer_id+'-'+str(i),float(mass),material['cec_cmolc_kg_by_fine_size'][i],chemistry.cec_method,material['evidence']))
        actual_fine=sum(layer.particle_masses_kg_m2[1:],F())
        for nutrient in ft.NUTRIENTS:
            reserves[nutrient]+=float(actual_fine)*material['reserve_mass_fractions'][nutrient]
            labile[nutrient]+=float(actual_fine)*material['labile_mass_fractions'][nutrient]
        dry_organic+=F(organic[layer.layer_id]['final_organic_dry_mass_kg_m2'])
    total=fine+dry_organic
    for nutrient in ft.NUTRIENTS:
        reserves[nutrient]+=float(dry_organic)*spec['organic_reserve_mass_fractions'][nutrient]
        labile[nutrient]+=float(dry_organic)*spec['organic_labile_mass_fractions'][nutrient]
    if sum(reserves.values())+sum(labile.values())>float(total): raise ValueError('actual elemental stock exceeds complete assay drymass')
    components.append(ft.ExchangeComponent('actual-organic-dry-matter',float(dry_organic),spec['organic_cec_cmolc_kg'],chemistry.cec_method,recipe['organic']['evidence']))
    assay_id=binding.provenance.sha(binding.provenance.encoded(plain([state,support['water_state_id'],recipe['fertility']])))
    exchange=ft.exchange_capacity(tuple(components),dry_fine_earth_and_organic_mass_kg_m2=float(total),chemistry=chemistry,support_id=assay_id)
    laws={row['nutrient']:ft.NutrientLaw(**row) for row in spec['laws']}
    if len(laws)!=len(spec['laws']) or set(laws)!=set(ft.NUTRIENTS): raise ValueError('one matching nutrient law per N/P/K required')
    results={}
    for nutrient in ft.NUTRIENTS:
        exposure=ft.WaterExposure(spec['assay_duration_s'],support['soil_temperature_k'],support['profile_wfps'],
            support['profile_water_storage_m'],support['downward_m_s'],support['upward_m_s'],
            spec['upward_concentrations_kg_m3'][nutrient],spec['natural_reference_evidence']+'; actual Water state '+support['water_state_id'])
        results[nutrient]=ft.advance_nutrient(ft.NutrientPool(nutrient,reserves[nutrient],labile[nutrient],
            'Explicit trace concentrations applied to current formed fine mineral and organic masses; '+spec['organic_chemistry_evidence']),laws[nutrient],(exposure,),
            sorbent_mass_kg_m2=float(total),chemistry=chemistry,support_id=assay_id)
    result=ft.profile_fertility(results,exchange,ft.FertilityProtocol(**spec['protocol']),natural_reference_evidence=spec['natural_reference_evidence'])
    result['assay_support']={'formed_fine_mineral_kg_m2':str(fine),'actual_organic_dry_kg_m2':str(dry_organic),
        'duration_s':spec['assay_duration_s'],'age_interpretation':'separate present-formed-soil reference assay, not historical nutrient evolution',
        'organic_nitrogen':'EXPLICIT_CURRENT_ELEMENTAL_COMPOSITION_NOT_INFERRED_FROM_CARBON_DYNAMICS',
        'organic_chemistry_evidence':spec['organic_chemistry_evidence'],
        'soil_solution_support':'held actual freshly formed-geometry Water probe; not claimed historical flow'}
    return result


def _simulate_cell(bundle,recipe,support,climate_id,until):
    from . import formation as fm, organic as om, fertility as ft
    spec=recipe['organic']; law=_organic_law(spec['law'],om); layers=[]
    for row in support['layers']:
        key=row['material_id']+'|'+row['phase']
        if key not in recipe['materials']: raise ValueError('actual geology/material identity lacks composition: '+key)
        item=recipe['materials'][key]; mass=F(row['mineral_mass_kg_m2'])
        layers.append(fm.FormationLayer(row['layer_id'],row['material_id'],row['phase'],mass,F(row['grain_density_kg_m3']),
            F(row['theta_s']),tuple(mass*F(v) for v in item['particle_mass_fractions']),tuple(item['inherited_horizon_candidates']),
            item['evidence'],'SYNTHETIC TEST'))
    state=fm.FormationState(support['profile_id'],tuple(layers),F(support['base_elevation_m']))
    original_ids={layer.layer_id for layer in layers}; initial_mineral=sum((l.mineral_mass_kg_m2 for l in layers),F())
    parent_layer_support={row['layer_id']:row for row in support['layers']}
    organic_states={}; organic_results={}; reports=[]
    def initial(layer_id,fast,slow):
        return om.initial_state(layer_id,state.column_id,fast,slow,evidence=spec['evidence'],source_status='SYNTHETIC TEST')
    def forcing(duration,fast,slow,evidence,*,surface=False,cohort_id=None):
        source=parent_layer_support.get(cohort_id) if not surface else None
        wfps=support['profile_wfps'] if source is None else source['wfps']
        water_id=support['water_state_id'] if source is None else source['water_state_id']
        policy=(spec['surface_moisture_hypothesis'] if surface else spec['new_material_exposure']) if source is None else 'ACTUAL_ORIGINAL_LAYER_FINAL_WFPS_HELD'
        return om.OrganicForcing(F(duration),F(fast),F(slow),support['soil_temperature_k'],wfps,
            spec['redox'],spec['surface_regime'] if surface else spec['regime'],climate_id,water_id,support['temperature_evidence'],
            spec['evidence'],evidence+'; moisture support '+policy,'SYNTHETIC TEST')
    def zero_result(ostate,*,surface=False):
        out=om.advance_layer(ostate,(forcing(0,0,0,'Explicit zero-age organic cohort at formation-stage boundary',surface=surface,cohort_id=ostate.layer_id),),law)
        if out['status']!='MODELLED': raise ValueError('organic zero-age initialisation failed: '+out['reason'])
        return out
    for layer in layers:
        if layer.phase!='bedrock':
            ratios=spec['initial_carbon_per_kg_mineral']
            organic_states[layer.layer_id]=initial(layer.layer_id,layer.mineral_mass_kg_m2*F(ratios[0]),layer.mineral_mass_kg_m2*F(ratios[1]))
            organic_results[layer.layer_id]=zero_result(organic_states[layer.layer_id])
    surface_id=state.column_id+'-organic-mantle'
    surface_state=initial(surface_id,*spec['surface_initial_carbon_kg_m2']); surface_result=zero_result(surface_state,surface=True)
    initial_organic=sum((F(r['final_organic_dry_mass_kg_m2']) for r in (*organic_results.values(),surface_result)),F())
    for event in recipe['soil_exposures'][:until]:
        dt=F(event['duration_seconds']); prior_geometry=_geometry(state,organic_results,surface_result,recipe)
        min_thickness={l.layer_id:l.thickness_m for l in state.layers}
        fixed_extra_cover=sum((F(row['thickness_m'])-min_thickness.get(row['layer_id'],F()) for row in prior_geometry),F())
        exposure=fm.ExposureSegment(event['exposure_id'],dt,support['soil_temperature_k'],support['profile_wfps'],
            support['water_state_id'],event['evidence']+'; '+recipe['formation']['production_moisture_hypothesis'],'SYNTHETIC TEST')
        # Existing-cohort size/organic exposure only. Material born below does
        # not inherit the entire prior age or litter input of this interval.
        altered=[]; particle=[]
        for layer in state.layers:
            if layer.phase=='bedrock': altered.append(layer); continue
            source=parent_layer_support.get(layer.layer_id)
            cohort_exposure=exposure if source is None else replace(exposure,water_filled_pore_fraction=source['wfps'],
                environment_state_id=source['water_state_id'],evidence=event['evidence']+'; actual original-layer final WFPS held')
            result=fm.alter_particle_sizes(layer,exposure=cohort_exposure,**recipe['formation']['fragmentation'])
            if result['status']!='MODELLED': raise ValueError('particle cohort exposure failed')
            altered.append(result['layer']); particle.append(result)
            of=forcing(dt,F(spec['fast_litter_carbon_per_kg_mineral_s'])*layer.mineral_mass_kg_m2,
                F(spec['slow_litter_carbon_per_kg_mineral_s'])*layer.mineral_mass_kg_m2,event['evidence'],cohort_id=layer.layer_id)
            result=om.advance_layer(organic_states[layer.layer_id],(of,),law)
            if result['status']!='MODELLED': raise ValueError('organic exposure failed: '+result['reason'])
            organic_states[layer.layer_id]=result['state']; organic_results[layer.layer_id]=result
        state=replace(state,layers=tuple(altered))
        production=fm.form_snapshot(state,(exposure,),tuple(fm.ProductionLaw(**row) for row in recipe['formation']['laws']),organic_cover_m=fixed_extra_cover)
        if production['status']!='MODELLED': raise ValueError('finite material production failed: '+production['reason'])
        state=production['state']
        for layer in state.layers:
            if layer.phase!='bedrock' and layer.layer_id not in organic_states:
                organic_states[layer.layer_id]=initial(layer.layer_id,0,0)
                organic_results[layer.layer_id]=zero_result(organic_states[layer.layer_id])
        surface_result=om.advance_layer(surface_state,(forcing(dt,spec['surface_fast_litter_carbon_kg_m2_s'],
            spec['surface_slow_litter_carbon_kg_m2_s'],event['evidence'],surface=True),),law)
        if surface_result['status']!='MODELLED': raise ValueError('surface organic exposure failed')
        surface_state=surface_result['state']
        reports.append({'exposure_id':event['exposure_id'],'production':production,'particle_alteration':particle,
            'organic_results':dict(organic_results),'surface_organic_result':surface_result,
            'fixed_initial_extra_organic_mixture_cover_m':fixed_extra_cover,
            'coupling':'DECLARED_STAGE_SPLIT: initial cover held during rock production; existing cohorts age, new rock cohorts begin at zero; not simultaneous long-history cover feedback'})
    geometry=_geometry(state,organic_results,surface_result,recipe)
    mixed={row['layer_id']:row['thickness_m'] for row in geometry if row['phase']!='organic_mantle'}
    o_geometry=next((row for row in geometry if row['phase']=='organic_mantle'),None)
    organic_mantle=None if o_geometry is None else {'result':surface_result,
        'bulk_density_kg_m3':o_geometry['grain_density_kg_m3']*(1-o_geometry['porosity']),'layer_id':surface_id,'evidence':spec['evidence']}
    horizons=fm.diagnose_horizons(state,organic_results,
        {l.layer_id:tuple(recipe['formation']['parent_carbon_ratio']) for l in state.layers if l.phase!='bedrock'},
        fm.HorizonProtocol(**recipe['formation']['horizon_protocol']),surface_organic=organic_mantle,
        reconciled_mineral_thickness_m=mixed,geometry_evidence=spec['evidence']+'; exact additive mineral/organic solid volumes and explicit joint porosity')
    final_mineral=sum((l.mineral_mass_kg_m2 for l in state.layers),F())
    if initial_mineral!=final_mineral: raise ArithmeticError('connected mineral stock changed without compatible elemental export')
    final_organic=sum((F(r['final_organic_dry_mass_kg_m2']) for r in (*organic_results.values(),surface_result)),F())
    imported=F(); decomposed=F()
    for report in reports:
        for result in (*report['organic_results'].values(),report['surface_organic_result']):
            # New zero-age results have zero flux; each continuing cohort is
            # reported exactly once in each applied exposure.
            imported+=F(result['organic_dry_matter']['input_kg_m2'])
            decomposed+=F(result['organic_dry_matter']['decomposed_dry_matter_origin_kg_m2'])
    dry_residual=initial_organic+imported-decomposed-final_organic
    if dry_residual: raise ArithmeticError('exact complete organic dry-origin ledger failed')
    consumer=postformation_water(bundle,plain(geometry),support,recipe['water_consumer']) if until else None
    assay=None
    if until:
        if consumer['status']!='MODELLED_NEW_GEOMETRY_WATER_PROBE':
            assay={'status':'UNKNOWN','index_0_1':None,'reason':'formed geometry lacks fresh compatible Water support; antecedent pressure/flow not reused'}
        else:
            water=consumer['result']; dt=F(water['forcing']['duration_seconds'])
            pores=sum((F(row['porosity'])*F(row['thickness_m']) for row in geometry),F())
            store=F(consumer['water_accounting']['formed_final_porewater_m'])
            current_support={**support,'profile_water_storage_m':float(store),'profile_wfps':float(store/pores),
                'downward_m_s':float(F(water['ledger']['bottom_downward_m'])/dt),
                'upward_m_s':float(F(water['ledger']['bottom_upward_m'])/dt),
                'water_state_id':bundle.storage.sha(bundle.storage.encoded(consumer))}
            assay=_assay(state,organic_results,surface_result,current_support,recipe,ft)
            assay['assay_support']['actual_formed_water_sha256']=current_support['water_state_id']
    return {'formation_state':state,'geometry':geometry,'horizons':horizons,'organic_by_layer':organic_results,
        'surface_organic':surface_result,'exposure_history':reports,
        'total_dry_mass_accounting':{'initial_mineral_kg_m2':initial_mineral,'final_mineral_kg_m2':final_mineral,
            'initial_separate_organic_kg_m2':initial_organic,'natural_organic_input_kg_m2':imported,
            'organic_decomposition_origin_kg_m2':decomposed,'final_organic_kg_m2':final_organic,
            'final_combined_dry_kg_m2':final_mineral+final_organic,'residual_kg_m2':dry_residual,
            'scope':'organic dry-matter origin balance; noncarbon fate not a gas speciation claim'},
        'fertility':assay,'formed_soil_water':consumer,
        'source_parent_layer_ids':sorted(original_ids),
        'macro_consumer_status':'CHANGED_GEOMETRY_REQUIRES_FRESH_CLIMATE_TERRAIN_EROSION_STABILITY_BINDINGS; original source exposure retained only as labelled sensitivity'}


def run(bundle,recipe,*,stop_after=None,resume=None):
    bundle.verify(); recipe=parse(bundle,recipe); s=bundle.storage
    recipe_sha=s.sha(s.encoded(recipe)); count=len(recipe['soil_exposures'])
    until=count if stop_after is None else stop_after
    if type(until) is not int or not 0<=until<=count: raise ValueError('valid whole soil-exposure stop cursor required')
    saved=None
    if resume is not None:
        saved=s.decoded(s.encoded(resume))
        exact(saved,('schema','recipe_sha256','source_sha256','state_sha256','state'),'R7 checkpoint')
        if (saved['schema']!=binding.CHECKPOINT_SCHEMA or saved['recipe_sha256']!=recipe_sha or saved['source_sha256']!=bundle.source_sha256
                or saved['state_sha256']!=s.sha(s.encoded(saved['state']))): raise ValueError('R7 source/recipe/restart binding differs; old checkpoints not adopted')
        exact(saved['state'],('completed_exposures','parent_result_sha256','exposure_sha256','members'),'R7 soil state')
    parent=bundle.parent.run(recipe['parent_recipe'])
    exposure=extract_exposure(bundle,parent,air_to_soil_offset_k=recipe['temperature_hypothesis']['air_to_soil_offset_k'],
        temperature_evidence=recipe['temperature_hypothesis']['evidence'])
    def simulate(cursor):
        members={scenario:{cell:_simulate_cell(bundle,recipe,support,exposure['parent_result_sha256'],cursor)
            for cell,support in cells.items()} for scenario,cells in exposure['members'].items()}
        return plain({'completed_exposures':cursor,'parent_result_sha256':exposure['parent_result_sha256'],
            'exposure_sha256':s.sha(s.encoded(exposure)),'members':members})
    if saved is not None:
        cursor=saved['state'].get('completed_exposures')
        if type(cursor) is not int or not 0<=cursor<=until: raise ValueError('valid continuing soil exposure cursor required')
        if simulate(cursor)!=saved['state']: raise ValueError('checkpoint cannot replay actual parent and complete soil state')
    state=simulate(until); bundle.verify()
    result={'schema':binding.RESULT_SCHEMA,'status':'BOUNDED_SOIL_FORMATION_REFERENCE','source_status':'WORKING NON-CANON',
        'source_sha256':bundle.source_sha256,'recipe_sha256':recipe_sha,'state':state,'actual_exposure':exposure,'parent_result':parent,
        'product_inventory':{'current':'state.members -> formed geometry, operational horizons, actual organic pools, explicit fertility assay, fresh formed-soil Water',
            'parent_result':'PRE_FORMATION_REFERENCE_NOT_CURRENT; retained soil-products limitations remain historical, not the R7 capability status'},
        'soil_age_status':'EXPLICIT_FIXED_EXPOSURE_SCENARIO_NOT_INFERRED_FROM_SHORT_CLIMATE; staged cover hypothesis, not reconstructed simultaneous history',
        'snow_family':'THREE_COEQUAL_SENSITIVITIES_NO_PREFERRED_MEMBER','production_installed':False,'canon_changed':False,
        'optimisation_performed':False}
    return s.decoded(s.encoded(result))
