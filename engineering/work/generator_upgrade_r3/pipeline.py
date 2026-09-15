"""Bounded, restartable, reservoir-lagged terrain--water--soil reference.

Every accepted macro interval is two half trials of the complete feedback loop.
No independent component PASS substitutes for this coupled error/budget gate.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from fractions import Fraction as F
import math

from . import soil_inputs as si, soil_water as sw, terrain_transport as tt, storage
from .deps import landscape
from work.generator_upgrade_r2 import soil_physics as sp

STATUS='WORKING NON-CANON'
SCHEMA='diadem.terrain-water-soil-recipe.r3'


def fields(value, expected):
    if type(value) is not dict or set(value)!=set(expected):raise ValueError('exact recipe/state fields required')


def number(v, *, positive=False):
    if type(v) not in (int,float) or not math.isfinite(v) or v<0 or (positive and v==0):
        raise ValueError('explicit finite physical/numerical quantity required')
    return v


def rational(v):
    if type(v) is not str or len(v)>6000:raise ValueError('bounded exact rational string required')
    q=F(v)
    if q<0 or max(q.numerator.bit_length(),q.denominator.bit_length())>8192:raise ValueError('bounded nonnegative exact quantity required')
    return q


def plain(value):
    if isinstance(value,F):return str(value)
    if isinstance(value,(tuple,list)):return [plain(v) for v in value]
    if isinstance(value,dict):return {k:plain(v) for k,v in value.items()}
    if hasattr(value,'__dataclass_fields__'):return plain(asdict(value))
    return value


@dataclass(frozen=True)
class Model:
    recipe: dict
    profiles: dict
    connectors: tuple
    erosion: tuple
    sediment: tuple
    deposition_properties: dict
    water_controls: object
    terrain_controls: object


def parse(recipe):
    storage.encoded(recipe)
    fields(recipe,('schema','evidence','source_status','seconds_per_year','water_density_kg_m3','gravity_m_s2',
        'cells','connectors','erosion','sediment','deposition_properties','water_controls','terrain_controls','coupling_controls','events'))
    if recipe['schema']!=SCHEMA or recipe['source_status'] not in ('SYNTHETIC TEST',STATUS):raise ValueError('reference recipe only; no canon/production authority')
    si._text(recipe['evidence'],'recipe evidence')
    for k in ('seconds_per_year','water_density_kg_m3','gravity_m_s2'):number(recipe[k],positive=True)
    if type(recipe['cells']) is not dict or not 1<=len(recipe['cells'])<=8:raise ValueError('one to eight explicit cells required')
    profiles={}
    for key,row in sorted(recipe['cells'].items()):
        si._text(key,'cell identity')
        fields(row,('profile','surface_water_m3','surface_residence_seconds','saturated_initial_guess_m',
            'root_lower_layer_id','stability_layer_id','representative_slope_degrees','stability_roots','stability_regime'))
        p=si.HydraulicProfile.from_dict(row['profile'])
        if not p.bindings or p.profile_id!=key:raise ValueError('nonempty compatible cell profile required')
        rational(row['surface_water_m3']);number(row['surface_residence_seconds'],positive=True)
        number(row['saturated_initial_guess_m']);number(row['representative_slope_degrees'],positive=True)
        if row['representative_slope_degrees']>=90:raise ValueError('slope must be below vertical')
        if row['stability_regime'] not in ('SHALLOW_TRANSLATIONAL_SOIL','ROCKFALL','DEEP_FAILURE','OTHER','UNKNOWN'):
            raise ValueError('explicit supported/conditional stability regime required')
        roots=row['stability_roots']
        fields(roots,('basal_cohesion_pa','maximum_active_depth_m','mode','evidence'))
        sp.Roots(sp.Interval(roots['basal_cohesion_pa'],roots['basal_cohesion_pa'],'Pa',roots['evidence'],STATUS),
            sp.Interval(roots['maximum_active_depth_m'],roots['maximum_active_depth_m'],'m',roots['evidence'],STATUS),roots['mode'],roots['evidence'])
        if any(row[n] not in {b.layer_id for b in p.bindings} for n in ('root_lower_layer_id','stability_layer_id')):
            raise ValueError('root and slip support must identify supplied physical layers')
        profiles[key]=p
    connectors=tuple(tt.Connector(**r) for r in recipe['connectors'])
    erosion=[]
    for row in recipe['erosion']:
        fields(row,('material_id','phase','k_per_year','reference_runoff_m_year','evidence'))
        number(row['k_per_year']);number(row['reference_runoff_m_year'],positive=True)
        erosion.append(landscape.ErosionLaw(row['material_id'],row['phase'],
            landscape.PhysicalProperty('erosion_coefficient_at_reference_runoff',row['k_per_year'],'1/year',row['evidence'],STATUS),
            landscape.PhysicalProperty('reference_runoff',row['reference_runoff_m_year'],'m/year',row['evidence'],STATUS)))
    sediment=tuple(tt.SedimentLaw(**r) for r in recipe['sediment'])
    dp=tuple(si.MaterialHydraulics.from_dict(r) for r in recipe['deposition_properties'])
    properties={p.material_id:p for p in dp}
    if len(properties)!=len(dp) or set(properties)!={s.material_id for s in sediment}:raise ValueError('one explicit deposited hydraulic law per material required')
    for s in sediment:
        if properties[s.material_id].phase!='mobile_sediment' or properties[s.material_id].porosity!=s.deposited_porosity:
            raise ValueError('deposited packing and hydraulic law differ')
    wc=sw.Controls(**recipe['water_controls']);tc=tt.TrialControls(**recipe['terrain_controls'])
    controls=recipe['coupling_controls']
    fields(controls,('initial_dt_seconds','min_dt_seconds','max_dt_seconds','water_atol_m3','height_atol_m',
        'head_integral_atol_m2','mass_atol_kg','relative_tolerance','budget_atol_m3','max_attempts'))
    for k,v in controls.items():number(v,positive=True)
    if (not controls['min_dt_seconds']<=controls['initial_dt_seconds']<=controls['max_dt_seconds'] or
        controls['relative_tolerance']>=1 or type(controls['max_attempts']) is not int or controls['max_attempts']>1000):
        raise ValueError('bounded coupled control regime required')
    events=recipe['events']
    if type(events) is not list or not 1<=len(events)<=8:raise ValueError('bounded explicit event forcing required')
    for event in events:
        fields(event,('duration_seconds','cells','evidence'));number(event['duration_seconds'],positive=True)
        if set(event['cells'])!=set(profiles):raise ValueError('one explicit forcing per cell required')
        for row in event['cells'].values():
            fields(row,('liquid_input_m_s','potential_et_m_s','uptake','boundary'))
            number(row['liquid_input_m_s']);number(row['potential_et_m_s'])
            boundary=sw.Boundary(**row['boundary'])
            if boundary.source_status=='UNKNOWN' or (boundary.kind=='fixed_head' and boundary.head_m is None):
                raise ValueError('known lower boundary hypothesis required before generation')
    model=Model(recipe,profiles,connectors,tuple(erosion),sediment,properties,wc,tc)
    # Validate support and constitutive domains before any material transition.
    for key,p in profiles.items():
        column,_=water_column(model,key,p)
        for event in events:water_forcing(column,event['cells'][key],event['duration_seconds'],event['evidence'])
        if recipe['cells'][key]['stability_roots']['mode']=='ABSENT' and any(e['cells'][key]['potential_et_m_s']>0 for e in events):
            raise ValueError('positive root uptake contradicts explicitly absent roots in this column')
    tt.route_water(landscape.LandscapeState(tuple((k,p.column) for k,p in profiles.items())),
        {k:rational(recipe['cells'][k]['surface_water_m3']) for k in profiles},connectors,duration_years=F(1))
    return model


def water_column(model,key,profile):
    rows=si.hydraulic_rows(profile)
    if not rows:raise ValueError('exhausted hydraulic column needs an explicit exterior-bedrock model')
    root=model.recipe['cells'][key]['root_lower_layer_id']
    ids=[r['layer_id'] for r in rows]
    if root not in ids:raise ValueError('eroded root support needs an explicitly revised biological scenario')
    layers=tuple(sw.HydraulicLayer(r['layer_id'],*[float(r[n]) for n in
        ('thickness_m','theta_r','theta_s','alpha_per_m','n','mualem_l','ksat_m_s')],r['evidence'],r['source_status']) for r in rows)
    column=sw.Column(key,layers,ids.index(root)+1,model.recipe['evidence'],STATUS)
    heads=tuple(sw.head_from_theta(layer,float(row['theta']),
        saturated_head_m=model.recipe['cells'][key]['saturated_initial_guess_m']) for layer,row in zip(layers,rows))
    return column,heads


def water_forcing(column,forcing,duration,evidence):
    uptake=forcing['uptake']
    if uptake is not None:
        fields(uptake,('by_layer_id','dry_zero_head_m','dry_full_head_m','wet_full_head_m','wet_zero_head_m','evidence','source_status'))
        weights=uptake['by_layer_id']
        if type(weights) is not dict or any(i not in {l.layer_id for l in column.layers} for i in weights):
            raise ValueError('eroded/unknown uptake support cannot be silently relocated')
        uptake=sw.Uptake(tuple(weights.get(l.layer_id,0) for l in column.layers),
            **{n:v for n,v in uptake.items() if n!='by_layer_id'})
        if uptake.source_status=='UNKNOWN' or any(w>0 for w in uptake.weights[column.root_boundary_index:]):
            raise ValueError('known uptake above the explicit root boundary required')
    return sw.Forcing(float(duration),forcing['liquid_input_m_s'],forcing['potential_et_m_s'],uptake,evidence,STATUS)


def initial(model):
    profiles=model.profiles.copy()
    return {'profiles':profiles,'surface':{k:rational(model.recipe['cells'][k]['surface_water_m3']) for k in profiles},
        'elapsed':F(0),'completed_events':0,'water':{},'history':[]}


def stock(state):
    return sum((p.water_volume_m3+state['surface'][k] for k,p in state['profiles'].items()),F(0))


def trial(model,state,event,dt):
    """One Lie-split interval; no mutation of a rejected parent state."""
    dt=F(dt);seconds=model.recipe['seconds_per_year'];profiles=state['profiles'];surface={};release={}
    for k,v in state['surface'].items():
        fraction=F(-math.expm1(-float(dt)/model.recipe['cells'][k]['surface_residence_seconds']))
        release[k]=v*fraction;surface[k]=v-release[k]
    terrain=tt.terrain_trial(landscape.LandscapeState(tuple((k,p.column) for k,p in profiles.items()),state['elapsed']/F(seconds)),
        release,model.connectors,model.erosion,model.sediment,duration_years=dt/F(seconds),
        controls=model.terrain_controls,evidence_id=event['evidence'])
    remapped={k:si.reconcile_eroded_column(p,terrain.erosion_state.column_map[k]).profile for k,p in profiles.items()}
    carried={};remap=[]
    for row in terrain.erosion_events:
        k,i=row['source_cell'],row['source_layer_index']
        carried[k,i]=profiles[k].bindings[i].water_volume_m3*row['eroded_mass_kg']/row['source_initial_mass_kg']
    wet_export=sum((carried[r['source_cell'],r['source_layer_index']]*r['fraction_of_eroded_mass'] for r in terrain.exports),F(0))
    for row in terrain.deposit_events:
        k=row['destination_cell']
        water=sum((carried[s['source_cell'],s['source_layer_index']]*s['fraction_of_eroded_mass'] for s in row['sources']),F(0))
        # ID is physical event support, not the rejected trial's execution order.
        identity=storage.sha(storage.encoded([str(state['elapsed']),str(dt),k,row['material_id']]))
        change=si.deposit_surface(remapped[k],row['layer'],model.deposition_properties[row['material_id']],water,
            layer_id='deposit-'+identity,evidence=event['evidence'])
        remapped[k]=change.profile;surface[k]+=change.water_to_surface_m3
        remap.append(change.receipt)
    if any(p.column.layers!=terrain.state.column_map[k].layers for k,p in remapped.items()):raise ArithmeticError('actual terrain and water geometry differ')
    if stock(state)-sum(release.values(),F(0))-wet_export != sum((p.water_volume_m3+surface[k] for k,p in remapped.items()),F(0)):
        raise ArithmeticError('exact wet-material remap budget failed')
    following={};water_outputs={};incoming=F(0);et=F(0);bottom_in=F(0);bottom_out=F(0)
    for k,p in remapped.items():
        column,heads=water_column(model,k,p)
        # Preserve actual previous pressure when no geometry changed. Otherwise
        # use theta inversion plus an explicit saturated nonlinear initial guess.
        prior=state['water'].get(k)
        if prior and prior['state']['column_sha256']==sw.column_digest(column):heads=tuple(prior['state']['head_m'])
        hstate=sw.initial_state(column,heads,elapsed_seconds=float(state['elapsed']))
        forcing=event['cells'][k]
        result=sw.advance(column,hstate,water_forcing(column,forcing,dt,event['evidence']),
            sw.Boundary(**forcing['boundary']),model.water_controls,
            water_density_kg_m3=model.recipe['water_density_kg_m3'],gravity_m_s2=model.recipe['gravity_m_s2'])
        if result['status']!='MODELLED':raise CoupledStepFailure('soil-water: '+result['status']+': '+result['reason'])
        # Use exact physical bulk volumes with represented theta. Binary64 dz is
        # a solver approximation, not permission to overfill exact pore space.
        values=tuple(F(r['theta_m3_m3'])*l.bulk_volume_m3 for r,l in zip(reversed(result['layers']),p.column.layers))
        following[k],_=si.replace_porewater(p,values,evidence=event['evidence'])
        area=p.column.area_m2;ledger=result['ledger']
        surface[k]+=F(ledger['surface_runoff_m'])*area
        incoming+=F(ledger['surface_input_m'])*area;et+=F(ledger['actual_et_m'])*area
        bottom_in+=F(ledger['bottom_upward_m'])*area;bottom_out+=F(ledger['bottom_downward_m'])*area
        water_outputs[k]=plain(result)
    out={'profiles':following,'surface':surface,'elapsed':state['elapsed']+dt,
         'completed_events':state['completed_events'],'water':water_outputs,'history':list(state['history'])}
    runoff_export=sum(release.values(),F(0))
    residual=stock(state)+incoming+bottom_in-et-bottom_out-runoff_export-wet_export-stock(out)
    if abs(float(residual))>model.recipe['coupling_controls']['budget_atol_m3']:raise CoupledStepFailure('whole coupled water budget exceeds declared tolerance')
    row={'start_seconds':str(state['elapsed']),'duration_seconds':str(dt),'initial_water_m3':str(stock(state)),
        'final_water_m3':str(stock(out)),'liquid_input_m3':str(incoming),'actual_et_m3':str(et),
        'bottom_in_m3':str(bottom_in),'bottom_out_m3':str(bottom_out),'runoff_export_m3':str(runoff_export),
        'sediment_porewater_export_m3':str(wet_export),'numerical_water_residual_m3':str(residual),
        'terrain':plain(terrain.receipt),'wet_deposition':remap,
        'root_flux_m3':{k:{n+'3':float(F(water_outputs[k]['ledger'][n])*following[k].column.area_m2)
            for n in ('root_zone_gross_downward_m','root_zone_upward_capillary_m')} for k in following}}
    out['history'].append(row)
    return out


class CoupledStepFailure(ValueError):pass


def compare(model,a,b,baseline):
    """Compare inventories AND physical-depth pressure integrals on unlike grids."""
    c=model.recipe['coupling_controls'];errors={}
    def add(name,x,y,atol):
        x,y=float(x),float(y)
        errors[name]=abs(x-y)/(atol+c['relative_tolerance']*max(abs(x),abs(y)))
    for k,p in a['profiles'].items():
        q=b['profiles'][k]
        add(k+'/surface_water',a['surface'][k],b['surface'][k],c['water_atol_m3'])
        original=baseline['profiles'][k]
        add(k+'/pore_water_change',p.water_volume_m3-original.water_volume_m3,q.water_volume_m3-original.water_volume_m3,c['water_atol_m3'])
        # Compare displacement relative to fixed basal support, not absolute
        # regional elevation (which would hide errors behind a huge datum).
        add(k+'/height_change',p.column.surface_m-original.column.surface_m,q.column.surface_m-original.column.surface_m,c['height_atol_m'])
        materials={(l.material_id,l.phase) for l in (*p.column.layers,*q.column.layers)}
        for m,phase in materials:
            old=sum((l.mass_kg for l in original.column.layers if (l.material_id,l.phase)==(m,phase)),F())
            add(k+'/mass_change/'+m+'/'+phase,sum((l.mass_kg for l in p.column.layers if (l.material_id,l.phase)==(m,phase)),F())-old,
                sum((l.mass_kg for l in q.column.layers if (l.material_id,l.phase)==(m,phase)),F())-old,c['mass_atol_kg'])
        if (p.column.layers[-1].material_id,p.column.layers[-1].phase)!=(q.column.layers[-1].material_id,q.column.layers[-1].phase):
            errors[k+'/exposed_material_mismatch']=2.0
        ar=a['water'][k]['layers'];br=b['water'][k]['layers']
        # L1 head difference at COMMON physical elevations, not two differently
        # positioned surface-relative grids. Nonoverlap gets a zero-extension
        # norm plus independent changed-height/material/storage gates.
        delta=0.0;scale=0.0
        sa=float(p.column.surface_m);sb=float(q.column.surface_m)
        matched_a=[0.0]*len(ar);matched_b=[0.0]*len(br)
        for i,x in enumerate(ar):
            for j,y in enumerate(br):
                overlap=max(0.0,min(sa-x['top_depth_m'],sb-y['top_depth_m'])-max(sa-x['bottom_depth_m'],sb-y['bottom_depth_m']))
                matched_a[i]+=overlap;matched_b[j]+=overlap
                delta+=overlap*abs(x['head_m']-y['head_m'])
                scale+=overlap*max(abs(x['head_m']),abs(y['head_m']))
        for rows,matched in ((ar,matched_a),(br,matched_b)):
            for x,covered in zip(rows,matched):
                outside=max(0.0,x['bottom_depth_m']-x['top_depth_m']-covered)*abs(x['head_m'])
                delta+=outside;scale+=outside
        errors[k+'/head_integral']=delta/(c['head_integral_atol_m2']+c['relative_tolerance']*scale)
    start=len(baseline['history'])
    for key in ('liquid_input_m3','actual_et_m3','bottom_in_m3','bottom_out_m3','runoff_export_m3','sediment_porewater_export_m3'):
        add('flux/'+key,sum((F(r[key]) for r in a['history'][start:]),F()),
            sum((F(r[key]) for r in b['history'][start:]),F()),c['water_atol_m3'])
    for k in a['profiles']:
        for direction in ('root_zone_gross_downward_m3','root_zone_upward_capillary_m3'):
            add(k+'/flux/'+direction,sum(r['root_flux_m3'][k][direction] for r in a['history'][start:]),
                sum(r['root_flux_m3'][k][direction] for r in b['history'][start:]),c['water_atol_m3'])
    return max(errors.values(),default=0.0),errors


def advance_event(model,state,event):
    c=model.recipe['coupling_controls'];left=F(event['duration_seconds']);dt=F(c['initial_dt_seconds']);attempts=0;checks=[]
    while left:
        attempts+=1
        if attempts>c['max_attempts']:raise CoupledStepFailure('coupled work budget exhausted; no partial PASS')
        dt=min(dt,left)
        try:
            full=trial(model,state,event,dt)
            half=trial(model,state,event,dt/2)
            fine=trial(model,half,event,dt/2)
            error,components=compare(model,full,fine,state)
        except (tt.TerrainStepTooLarge,CoupledStepFailure):error=math.inf
        if error>1:
            if dt/2<F(c['min_dt_seconds']):raise CoupledStepFailure('coupled truncation/solver gate failed at minimum timestep')
            dt/=2;continue
        state=fine;left-=dt
        checks.append({'duration_seconds':str(dt),'error_ratio':error,'components':components})
        if error<.125:dt=min(2*dt,F(c['max_dt_seconds']))
    state['completed_events']+=1
    # The accepted state includes no rejected trial mutations or deposit IDs.
    state['history'][-1]['coupled_acceptance']={'attempts':attempts,'accepted_intervals':checks}
    return state


def soil_products(model,state):
    out={}
    def point(v,u,e):return sp.Interval(float(v),float(v),u,e,STATUS)
    for k,p in state['profiles'].items():
        water=state['water'][k];rows=si.hydraulic_rows(p);e=model.recipe['evidence']
        conductivities=sp.layered_ksat(tuple(sp.ConductivityLayer(r['layer_id'],point(r['thickness_m'],'m',e),
            point(r['ksat_horizontal_m_s'],'m/s',e),point(r['ksat_m_s'],'m/s',e)) for r in rows))
        selected=model.recipe['cells'][k]['stability_layer_id']
        target=next((i for i,r in enumerate(rows) if r['layer_id']==selected),None)
        stability={'mask':'INAPPLICABLE','reason':'original prescribed slip-support layer has eroded; no automatic relocation'}
        if target is not None:
            r=rows[target];w=water['layers'][target];z=w['centre_depth_m']
            # Actual vertical overburden (solid + water) above this cell centre.
            mass=sum((rows[i]['mass_kg']+rows[i]['water_volume_m3']*F(model.recipe['water_density_kg_m3']) for i in range(target)),F())
            mass+=(r['mass_kg']+r['water_volume_m3']*F(model.recipe['water_density_kg_m3']))/2
            gamma=float(mass/p.column.area_m2)*model.recipe['gravity_m_s2']/z
            root=model.recipe['cells'][k]['stability_roots']
            regime=model.recipe['cells'][k]['stability_regime']
            # Phase alone does not establish a soil failure regime; a declared
            # shallow-soil hypothesis also cannot turn coherent bedrock to soil.
            if regime=='SHALLOW_TRANSLATIONAL_SOIL' and r['phase'] not in ('immobile_regolith','mobile_sediment'):regime='OTHER'
            case=sp.SlopeCase(k+'-current-slip',regime,point(z,'m',e),
                point(model.recipe['cells'][k]['representative_slope_degrees'],'degree',e),point(gamma,'N/m3',e),
                point(r['effective_cohesion_pa'],'Pa',e),point(r['friction_angle_deg'],'degree',e),
                point(w['signed_pore_pressure_pa'],'Pa',e),
                sp.Roots(point(root['basal_cohesion_pa'],'Pa',root['evidence']),point(root['maximum_active_depth_m'],'m',root['evidence']),root['mode'],root['evidence']),
                sp.Support('SCALAR_REFERENCE',None,None,k,e),storage.sha(storage.encoded(water)),
                storage.sha(storage.encoded(p.as_dict())),e)
            stability=sp.factor_of_safety(case)
        out[k]={'source_status':STATUS,'hydraulic_profile':p.as_dict(),'layered_saturated_conductivity':plain(conductivities),
            'saturation':[{n:r[n] for n in ('layer_id','pore_saturation','effective_saturation','signed_pore_pressure_pa')} for r in water['layers']],
            'stability':plain(stability),'pedogenic_horizons':'NOT_INFERRED','fertility':'SEPARATE_CAPABILITY_NOT_CLAIMED',
            'pressure_support':'current hydraulic cell centre; no saturation-to-positive-pressure guess'}
    return out


def serialise(state):
    return {'profiles':{k:p.as_dict() for k,p in state['profiles'].items()},'surface':{k:str(v) for k,v in state['surface'].items()},
        'elapsed':str(state['elapsed']),'completed_events':state['completed_events'],'water':state['water'],'history':state['history']}


def run(recipe,*,stop_after=None,resume=None,source_sha256=None):
    model=parse(recipe);state=initial(model);recipe_sha=storage.sha(storage.encoded(recipe))
    if stop_after is None:stop_after=len(recipe['events'])
    if type(stop_after) is not int or not 0<=stop_after<=len(recipe['events']):raise ValueError('valid event-boundary stop required')
    if resume is not None:
        raw=storage.restore(resume,recipe_sha256=recipe_sha,source_sha256=source_sha256)
        fields(raw,('profiles','surface','elapsed','completed_events','water','history'))
        completed=raw['completed_events']
        if type(completed) is not int or not 0<=completed<=stop_after:raise ValueError('checkpoint event cursor invalid')
        # Revalidation by isolated deterministic replay also rejects a forged
        # self-consistent checksum, altered material law, or fabricated ledger.
        for event in recipe['events'][:completed]:state=advance_event(model,state,event)
        if serialise(state)!=raw:raise ValueError('checkpoint is not the reproducible physical state of this recipe')
    for event in recipe['events'][state['completed_events']:stop_after]:state=advance_event(model,state,event)
    saved=serialise(state)
    result={'schema':'diadem.connected-terrain-water-soil.r3','status':'BOUNDED_CONNECTED_REFERENCE',
        'source_status':STATUS,'production_installed':False,'canon_changed':False,
        'state':saved,'soil_products':soil_products(model,state) if state['water'] else {},
        'coupling':'explicit surface reservoir release; morphology/wet-remap then mixed Richards; full-vs-two-half whole-state gate',
        'initial_total_water_m3':str(stock(initial(model))),'final_total_water_m3':str(stock(state)),
        'water_residual_m3':str(sum((F(r['numerical_water_residual_m3']) for r in state['history']),F())),
        'scope':'small open drainage graph, dilute steady settling, vertical matrix flow, supplied physical materials and static representative stability; not regional calibration'}
    storage.encoded(result)
    return result
