"""Finite enthalpy/phase-change cells; supplied free-water law, no frozen Richards.

Extensive water mass and energy are the state. Every coefficient and boundary
is caller supplied. Heat exchange is backward Euler on each declared link;
the ordered link/forcing split needs temporal refinement in coupled use.
"""
from fractions import Fraction as F
from copy import deepcopy
import hashlib
import json
import math


def fields(value,names,label):
    if type(value) is not dict or set(value)!=set(names): raise ValueError('exact '+label+' fields required')
    return value


def number(value,label,*,positive=False,nonnegative=False):
    if type(value) not in (int,float,str,F): raise ValueError(label+' requires a real quantity, not Boolean')
    try: result=F(value)
    except (ValueError,ZeroDivisionError,OverflowError) as error: raise ValueError('invalid '+label) from error
    try: finite=math.isfinite(float(result))
    except OverflowError: finite=False
    if max(result.numerator.bit_length(),result.denominator.bit_length())>8192 or not finite:
        raise ValueError('bounded finite '+label+' required')
    if positive and result<=0 or nonnegative and result<0: raise ValueError(label+' outside admitted range')
    return result


def text(value):
    if type(value) is not str or not value.strip() or len(value)>4096: raise ValueError('explicit bounded identity/evidence required')
    return value


def plain(value):
    if isinstance(value,F): return str(value)
    if type(value) is dict:
        if any(type(k) is not str for k in value): raise ValueError('string JSON keys required')
        return {k:plain(v) for k,v in value.items()}
    if type(value) in (tuple,list): return [plain(v) for v in value]
    if value is None or type(value) in (str,int,bool): return value
    if type(value) is float and math.isfinite(value): return value
    raise ValueError('strict JSON-compatible value required')


def digest(value):
    return hashlib.sha256(json.dumps(plain(value),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def represented(value,label):
    """One binary64 transfer; never silently turn a positive process into zero."""
    value=number(value,label)
    result=F(float(value))
    if value and not result: raise ValueError(label+' underflows the represented transfer precision')
    return result


CELL_FIELDS=('cell_id','solid_heat_capacity_j_k','liquid_heat_capacity_j_kg_k','ice_heat_capacity_j_kg_k',
    'latent_heat_j_kg','freezing_temperature_k','evidence','source_status')


def coefficients(cell):
    fields(cell,CELL_FIELDS,'thermal cell'); text(cell['cell_id']); text(cell['evidence'])
    if cell['source_status'] not in ('SYNTHETIC TEST','WORKING NON-CANON','UNKNOWN'): raise ValueError('explicit thermal source status required')
    if cell['source_status']=='UNKNOWN' or any(cell[k] is None for k in CELL_FIELDS[1:6]):
        raise ValueError('UNKNOWN thermal coefficients are not zero or defaults')
    return tuple(number(cell[k],k,positive=True) for k in CELL_FIELDS[1:6])


def phase(cell,water_mass_kg,energy_j):
    cd,cw,ci,latent,tf=coefficients(cell); mass=number(water_mass_kg,'water mass',nonnegative=True); energy=number(energy_j,'enthalpy')
    if energy<0: temperature=tf+energy/(cd+mass*ci); liquid=F()
    elif energy>mass*latent: temperature=tf+(energy-mass*latent)/(cd+mass*cw); liquid=mass
    else: temperature=tf; liquid=energy/latent
    if temperature<=0: raise ValueError('enthalpy implies nonphysical absolute temperature')
    return {'cell_id':cell['cell_id'],'temperature_k':float(temperature),'temperature_k_exact':str(temperature),
        'water_mass_kg':str(mass),'liquid_water_kg':str(liquid),'ice_water_kg':str(mass-liquid),
        'liquid_fraction':float(liquid/mass) if mass else 0.,'energy_j':str(energy),
        'phase_law':'SUPPLIED_ISOTHERMAL_FREE_WATER_PHASE_CHANGE','sample':'INSTANTANEOUS_CELL_STATE'}


def initial_cell(cell,water_mass_kg,temperature_k,*,liquid_fraction_at_freezing=None):
    cd,cw,ci,latent,tf=coefficients(cell); mass=number(water_mass_kg,'water mass',nonnegative=True)
    temperature=number(temperature_k,'absolute temperature',positive=True)
    if temperature==tf:
        if liquid_fraction_at_freezing is None: raise ValueError('freezing temperature alone does not determine ice/liquid partition')
        fraction=number(liquid_fraction_at_freezing,'liquid fraction',nonnegative=True)
        if fraction>1: raise ValueError('liquid fraction exceeds unity')
        energy=mass*latent*fraction
    else:
        if liquid_fraction_at_freezing is not None: raise ValueError('phase fraction only supplied at freezing temperature')
        energy=(cd+mass*(ci if temperature<tf else cw))*(temperature-tf)+(mass*latent if temperature>tf else 0)
    return {'water_mass_kg':str(mass),'energy_j':str(energy)}


def liquid_enthalpy(cell,temperature_k):
    _,cw,_,latent,tf=coefficients(cell); temperature=number(temperature_k,'liquid temperature',positive=True)
    if temperature<tf: raise ValueError('supercooled liquid is outside this phase law')
    return latent+cw*(temperature-tf)


def add_liquid(cell,state,mass_kg,temperature_k):
    fields(state,('water_mass_kg','energy_j'),'thermal state'); phase(cell,**state)
    mass=number(mass_kg,'incoming liquid',nonnegative=True); number(temperature_k,'inflow absolute temperature',positive=True)
    if not mass: return deepcopy(state),F()
    energy=mass*liquid_enthalpy(cell,temperature_k)
    updated={'water_mass_kg':str(number(state['water_mass_kg'],'water')+mass),'energy_j':str(number(state['energy_j'],'energy')+energy)}
    phase(cell,**updated)
    return updated,energy


def remove_liquid(cell,state,mass_kg,*,energy_atol_j=None):
    fields(state,('water_mass_kg','energy_j'),'thermal state')
    mass=number(mass_kg,'outgoing liquid',nonnegative=True); current=phase(cell,**state)
    if mass>F(current['liquid_water_kg']): raise ValueError('ice or absent liquid cannot be exported as liquid water')
    if energy_atol_j is not None: number(energy_atol_j,'advective energy representation allowance',positive=True)
    if not mass: return deepcopy(state),F()
    energy=mass*liquid_enthalpy(cell,current['temperature_k_exact'])
    if energy_atol_j is not None:
        tolerance=number(energy_atol_j,'advective energy representation allowance',positive=True)
        rounded=represented(energy,'advected energy')
        if abs(rounded-energy)>tolerance: raise ValueError('advective energy representation exceeds supplied allowance')
        energy=rounded
    updated={'water_mass_kg':str(F(state['water_mass_kg'])-mass),'energy_j':str(F(state['energy_j'])-energy)}
    phase(cell,**updated)
    return updated,energy


def _branches(cell,mass):
    cd,cw,ci,latent,tf=coefficients(cell); cap=mass*latent
    return ((1/(cd+mass*ci),tf,None,F()),(F(),tf,F(),cap),
        (1/(cd+mass*cw),tf-cap/(cd+mass*cw),cap,None))


def _inside(value,branch):
    return (branch[2] is None or value>=branch[2]) and (branch[3] is None or value<=branch[3])


def exchange_heat(left,left_state,right,right_state,conductance_w_k,duration_seconds,*,energy_atol_j):
    """Exact piecewise-linear implicit pair, rounded transfer with measured residual."""
    g=number(conductance_w_k,'thermal conductance',nonnegative=True); dt=number(duration_seconds,'heat duration',positive=True)
    tolerance=number(energy_atol_j,'heat equation allowance',positive=True)
    fields(left_state,('water_mass_kg','energy_j'),'left thermal state'); fields(right_state,('water_mass_kg','energy_j'),'right thermal state')
    ma,mb=F(left_state['water_mass_kg']),F(right_state['water_mass_kg']); ea,eb=F(left_state['energy_j']),F(right_state['energy_j'])
    phase(left,ma,ea); phase(right,mb,eb)
    for a in _branches(left,ma):
        for b in _branches(right,mb):
            q=dt*g*(a[0]*ea+a[1]-b[0]*eb-b[1])/(1+dt*g*(a[0]+b[0]))
            if not _inside(ea-q,a) or not _inside(eb+q,b): continue
            rounded=represented(q,'pair heat transfer'); sa={'water_mass_kg':str(ma),'energy_j':str(ea-rounded)}; sb={'water_mass_kg':str(mb),'energy_j':str(eb+rounded)}
            ta=F(phase(left,**sa)['temperature_k_exact']); tb=F(phase(right,**sb)['temperature_k_exact'])
            residual=rounded-dt*g*(ta-tb)
            if abs(residual)>tolerance: raise ValueError('thermal implicit equation representation exceeds supplied allowance')
            return sa,sb,{'energy_left_to_right_j':str(rounded),'equation_residual_j':str(residual),'energy_residual_j':'0'}
    raise ValueError('thermal phase branch solution not found')


def boundary_heat(cell,state,temperature_k,conductance_w_k,duration_seconds,*,energy_atol_j):
    fields(state,('water_mass_kg','energy_j'),'thermal state')
    temperature=number(temperature_k,'boundary temperature',positive=True); g=number(conductance_w_k,'boundary conductance',nonnegative=True)
    dt=number(duration_seconds,'heat duration',positive=True); tolerance=number(energy_atol_j,'heat equation allowance',positive=True)
    mass=F(state['water_mass_kg']); energy=F(state['energy_j']); phase(cell,mass,energy)
    for branch in _branches(cell,mass):
        q=dt*g*(temperature-branch[0]*energy-branch[1])/(1+dt*g*branch[0])
        if not _inside(energy+q,branch): continue
        rounded=represented(q,'boundary heat transfer'); updated={'water_mass_kg':str(mass),'energy_j':str(energy+rounded)}
        residual=rounded-dt*g*(temperature-F(phase(cell,**updated)['temperature_k_exact']))
        if abs(residual)>tolerance: raise ValueError('boundary heat equation representation exceeds supplied allowance')
        return updated,{'energy_into_cell_j':str(rounded),'equation_residual_j':str(residual)}
    raise ValueError('boundary thermal phase solution not found')


def initial_column(cells,states,*,source_binding_sha256,elapsed_seconds=0):
    """A fixed-water/geometry thermal state, independently of reservoir temperature."""
    if type(cells) is not dict or not 1<=len(cells)<=128 or type(states) is not dict or set(cells)!=set(states): raise ValueError('exact bounded thermal supports required')
    if type(source_binding_sha256) is not str or len(source_binding_sha256)!=64 or any(c not in '0123456789abcdef' for c in source_binding_sha256): raise ValueError('thermal source SHA256 required')
    for key,cell in cells.items():
        if cell['cell_id']!=key: raise ValueError('thermal support identity mismatch')
        fields(states[key],('water_mass_kg','energy_j'),'thermal initial state'); phase(cell,**states[key])
    return {'schema':'diadem.held-water-thermal-state.r11','cells_sha256':digest(cells),'source_binding_sha256':source_binding_sha256,
        'elapsed_seconds':str(number(elapsed_seconds,'thermal initial time',nonnegative=True)),'cells':plain(states),'consumed_event_ids':[]}


def advance_column(cells,state,links,boundaries,*,event_id,duration_seconds,max_dt_seconds,max_substeps,energy_atol_j):
    """Held water-mass heat conduction; NOT hydrothermally coupled soil Richards.

    A driver may initialise each cell from actual layer mass/geometry but must
    supply heat capacities, conductances, initial soil T and freezing law. The
    boundary temperature cannot be silently replaced by reservoir/air T.
    """
    fields(state,('schema','cells_sha256','source_binding_sha256','elapsed_seconds','cells','consumed_event_ids'),'thermal column state')
    if state['schema']!='diadem.held-water-thermal-state.r11' or state['cells_sha256']!=digest(cells): raise ValueError('thermal geometry/law state mismatch')
    initial_column(cells,state['cells'],source_binding_sha256=state['source_binding_sha256'],elapsed_seconds=state['elapsed_seconds'])
    text(event_id)
    if type(state['consumed_event_ids']) is not list or len(set(state['consumed_event_ids']))!=len(state['consumed_event_ids']) or event_id in state['consumed_event_ids']: raise ValueError('thermal event already consumed or invalid history')
    dtmax=number(max_dt_seconds,'thermal maximum step',positive=True); duration=number(duration_seconds,'thermal event duration',positive=True)
    if type(max_substeps) is not int or not 1<=max_substeps<=100000: raise ValueError('explicit thermal work budget required')
    number(energy_atol_j,'energy equation allowance',positive=True)
    if type(links) is not list or len(links)>256: raise ValueError('bounded heat links required')
    ids=set()
    for link in links:
        fields(link,('link_id','left','right','conductance_w_k','evidence'),'thermal link'); text(link['link_id']); text(link['evidence'])
        if link['link_id'] in ids or link['left'] not in cells or link['right'] not in cells or link['left']==link['right']: raise ValueError('unique heat links and distinct supports required')
        ids.add(link['link_id']); number(link['conductance_w_k'],'thermal link conductance',nonnegative=True)
    if type(boundaries) is not dict or set(boundaries)!=set(cells): raise ValueError('all thermal boundary supports required')
    unknown=False
    for row in boundaries.values():
        fields(row,('temperature_k','conductance_w_k','evidence'),'thermal boundary'); text(row['evidence'])
        unknown=unknown or row['temperature_k'] is None or row['conductance_w_k'] is None
    if unknown: return {'schema':'diadem.held-water-thermal-result.r11','status':'UNKNOWN','event_id':event_id,'final_state':None,'last_accepted_state':deepcopy(state),'reason':'required soil thermal boundary unknown; no air/reservoir substitution'}
    working=deepcopy(state['cells']); elapsed=F(); steps=[]; boundary_total=F(); initial_energy=sum((F(x['energy_j']) for x in working.values()),F())
    while elapsed<duration:
        if len(steps)>=max_substeps: raise ValueError('thermal work budget exhausted')
        dt=min(dtmax,duration-elapsed)
        for key,row in boundaries.items():
            working[key],receipt=boundary_heat(cells[key],working[key],row['temperature_k'],row['conductance_w_k'],dt,energy_atol_j=energy_atol_j)
            boundary_total+=F(receipt['energy_into_cell_j'])
        for link in links:
            a,b=link['left'],link['right']
            working[a],working[b],_=exchange_heat(cells[a],working[a],cells[b],working[b],link['conductance_w_k'],dt,energy_atol_j=energy_atol_j)
        elapsed+=dt
        steps.append({'duration_seconds_exact':str(dt),'elapsed_seconds_exact':str(elapsed),'end_layers':{key:phase(cells[key],**value) for key,value in working.items()}})
    final_energy=sum((F(x['energy_j']) for x in working.values()),F())
    residual=initial_energy+boundary_total-final_energy
    if residual: raise ValueError('thermal energy conservation failure')
    updated=dict(state,elapsed_seconds=str(F(state['elapsed_seconds'])+duration),cells=working,consumed_event_ids=state['consumed_event_ids']+[event_id])
    return {'schema':'diadem.held-water-thermal-result.r11','status':'MODELLED','event_id':event_id,'source_binding_sha256':state['source_binding_sha256'],
        'inputs_sha256':digest({'cells':cells,'initial':state,'links':links,'boundaries':boundaries,'event_id':event_id,'duration_seconds':duration_seconds,
            'max_dt_seconds':max_dt_seconds,'max_substeps':max_substeps,'energy_atol_j':energy_atol_j}),
        'initial_state':deepcopy(state),'final_state':updated,'accepted_steps':steps,'duration_seconds_exact':str(duration),
        'energy_ledger_j':plain({'initial':initial_energy,'boundary_input':boundary_total,'final':final_energy,'residual':residual}),
        'water_mass_kg':{key:working[key]['water_mass_kg'] for key in working},'water_mass_changed':False,
        'geometry_feedback':'NOT_APPLIED','hydraulic_feedback':'NOT_FROZEN_RICHARDS','phase_law_applicability':'SUPPLIED_FREE_WATER_FREEZING_TEST_NOT_GENERAL_SOIL_UNFROZEN_WATER_CURVE'}
