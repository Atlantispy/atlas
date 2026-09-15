"""Actual A-parent monthly inputs through all three persistent snow ledgers.

Fixed-forcing sensitivity only: no new-terrain compatibility, event truth,
inferred meteorology, recomputed PM demand or realised ET is asserted.
"""
from fractions import Fraction as F
from . import climate, hydromet as hm


def run(row,col,*,initial_swe_m_by_scenario,initial_stock_evidence,model_day_seconds,
        coefficient_day_seconds,disaggregation_evidence,source_sha256):
    hm._text(initial_stock_evidence,'initial snow stock evidence')
    hm._text(disaggregation_evidence,'monthly forcing interpretation')
    hm._hash(source_sha256)
    model_day=hm._q(model_day_seconds,'explicit model calendar day seconds',positive=True)
    coefficient_day=hm._q(coefficient_day_seconds,'DDF coefficient day seconds',positive=True)
    parent=climate.retained_candidate_cell(row,col)
    scenarios=hm.snow_scenarios();ids={s.scenario_id for s in scenarios}
    if type(initial_swe_m_by_scenario) is not dict or set(initial_swe_m_by_scenario)!=ids:
        raise ValueError('explicit initial physical SWE for every coequal scenario required')
    stocks={k:hm._q(v,'initial SWE') for k,v in initial_swe_m_by_scenario.items()}
    binding=hm.digest({'parent':parent,'initial_stocks':{k:str(v) for k,v in sorted(stocks.items())},
        'stock_evidence':initial_stock_evidence,'model_day_seconds':str(model_day),'coefficient_day_seconds':str(coefficient_day),
        'disaggregation_evidence':disaggregation_evidence,'source_sha256':source_sha256})
    members={};fields=parent['fields']
    for scenario in scenarios:
        state=hm.initial_snow('A-'+str(row)+'-'+str(col),scenario,stocks[scenario.scenario_id],
            binding_sha256=binding,elapsed_seconds=0,evidence=initial_stock_evidence)
        monthly=[]
        for index,(month,days) in enumerate(zip(parent['months'],parent['days'])):
            dt=F(days)*model_day
            p=F(fields['precipitation_mm'][index])/1000
            sf=F(fields['snowfall_we_mm'][index])/1000
            pet=F(fields['pet_mm'][index])/1000
            forcing={'month':month,'temperature_c':fields['temperature_c'][index],
                'precipitation_m':str(p),'snowfall_m':str(sf),'retained_pet_m':str(pet),
                'parent_bindings':parent['source_bindings'],'interpretation':disaggregation_evidence}
            result=hm.snow_step(state,scenario,temperature_c=fields['temperature_c'][index],
                precipitation_m_s=p/dt,snowfall_m_s=sf/dt,start_seconds=state.elapsed_seconds,duration_seconds=dt,
                day_seconds=coefficient_day,interval_id='retained-A-'+month,input_sha256=hm.digest(forcing),
                binding_sha256=binding,evidence=disaggregation_evidence,source_status='WORKING NON-CANON',
                temperature_distribution_evidence='Retained regional coequal Gaussian DDF/sigma hypothesis applied to actual A monthly mean; not measured weather')
            if result['status']!='MODELLED':raise ValueError('retained forcing did not yield a valid snow ledger')
            monthly.append({'month':month,'start_seconds':state.elapsed_seconds,'duration_seconds':dt,
                'temperature_c':fields['temperature_c'][index],'snow_ledger':result['ledger'],
                'liquid_input_mean_m_s':result['liquid_input_m_s'],'snow_depletion_after_seconds':result['depletion_after_seconds'],
                'retained_pet_m':pet,'retained_pet_mean_m_s':pet/dt,'actual_et_m':None,
                'coefficient_day_role':result['coefficient_day_role'],'forcing_sha256':hm.digest(forcing)})
            state=result['state']
        initial=stocks[scenario.scenario_id]
        precipitation=sum((r['snow_ledger']['precipitation_m'] for r in monthly),F())
        liquid=sum((r['snow_ledger']['liquid_to_soil_m'] for r in monthly),F())
        if initial+precipitation-liquid-state.swe_m:raise ArithmeticError('retained annual snow/liquid budget failed')
        members[scenario.scenario_id]={'scenario':scenario.__dict__,'initial_swe_m':initial,'final_swe_m':state.swe_m,
            'annual_precipitation_m':precipitation,'annual_liquid_to_soil_m':liquid,
            'annual_melt_m':sum((r['snow_ledger']['melt_m'] for r in monthly),F()),
            'annual_retained_pet_m':sum((r['retained_pet_m'] for r in monthly),F()),
            'annual_total_water_residual_m':F(0),'state':hm.state_json(state),'monthly':monthly}
    return {'status':'ACTUAL_A_MONTHLY_SNOW_DEMAND_FIXED_FORCING_SENSITIVITY','source_status':'WORKING NON-CANON',
        'binding_sha256':binding,'source_sha256':source_sha256,'parent':parent,'members':members,
        'snow_family':'THREE_COEQUAL_SENSITIVITIES_NO_PREFERRED_MEMBER','duration_seconds':sum(parent['days'])*model_day,
        'calendar':'JAN_DEC_365_FEB28','model_day_seconds':model_day,'coefficient_day_seconds':coefficient_day,
        'disaggregation_evidence':disaggregation_evidence,'initial_stock_evidence':initial_stock_evidence,
        'new_terrain_compatible':False,'realised_et_computed':False,'pm_recomputed':False,
        'limits':'actual retained A temperature/P/snowfall/PET only; no invented q/wind/radiation or unique event history; monthly mean liquid must not bypass depletion-aware dynamic coupling'}
