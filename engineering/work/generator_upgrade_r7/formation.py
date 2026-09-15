"""Finite mineral formation and explicit operational soil-profile diagnostics.

The output is a fixed snapshot under supplied exposure hypotheses, not a unique
world history. Mineral production, size alteration and pedogenic solum are three
distinct quantities. No fertility, clay mineralogy, hydraulic state or taxonomy
is inferred here. Represented mass/size ledgers use exact rational arithmetic.
"""
from dataclasses import dataclass, replace, asdict
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
from scipy.special import gammainc

SIZE_CLASSES = ('coarse_gt2mm','sand_0.05_to2mm','silt_0.002_to0.05mm','clay_size_lt0.002mm')
PHASES = {'bedrock','immobile_regolith','mobile_sediment'}
HORIZONS = {'O','A','E','B','C','R'}
KNOWN = {'CANON','WORKING NON-CANON','SYNTHETIC TEST'}
STATUSES = KNOWN | {'UNKNOWN','INCOMPLETE','CONFLICT'}
MAX_LAYERS = 128
MAX_SEGMENTS = 32
MAX_BITS = 8192
PROBABILITY_ERROR_LIMIT = 2e-14
OWNER_PATH = Path('C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace/02_Working_Files/Geography/Climate_Biomes_Soils/Scientific_Upgrade_Decisions/2026-09-10-R1/CLIMATE_SOILS_OWNER_DECISION_2026-09-10_R1.md')
OWNER_SHA256 = 'ba909d8a3e34a1722cba51925d602eca28d749a91a7bbf2162baf99221b4de19'


def _text(v,name):
    if type(v) is not str or not v.strip() or len(v)>4096:raise ValueError(name+' requires bounded identity/evidence')


def _q(v,name,*,signed=False):
    if type(v) not in (int,float,str,F) or isinstance(v,bool):raise ValueError(name+' requires exact represented number')
    if isinstance(v,str) and len(v)>4096:raise ValueError('numeric input too large')
    try:q=F(v)
    except (ValueError,ZeroDivisionError,OverflowError) as exc:raise ValueError(name+' must be finite') from exc
    if max(q.numerator.bit_length(),q.denominator.bit_length())>MAX_BITS:raise ValueError('exact arithmetic budget exceeded')
    if not signed and q<0:raise ValueError(name+' must be nonnegative')
    return q


def _float(v,name,*,positive=False):
    if type(v) not in (int,float) or isinstance(v,bool):raise ValueError(name+' requires finite SI number')
    try:v=float(v)
    except OverflowError as exc:raise ValueError('number outside binary64') from exc
    if not math.isfinite(v) or v<0 or (positive and v==0):raise ValueError(name+' outside finite physical domain')
    return v


def _represented(q,name):
    try:v=float(q)
    except OverflowError as exc:raise ValueError(name+' unrepresentable') from exc
    if not math.isfinite(v) or (q!=0 and v==0):raise ValueError(name+' unrepresentable')
    return v


def _source(evidence,status):
    _text(evidence,'evidence')
    if type(status) is not str or status not in STATUSES:raise ValueError('source status required')


def _candidates(v):
    if type(v) is not tuple or len(v)!=len(set(v)) or any(k not in HORIZONS for k in v):raise ValueError('explicit unique operational horizon alternatives required')


def plain(v):
    if isinstance(v,F):return str(v)
    if hasattr(v,'__dataclass_fields__'):return plain(asdict(v))
    if isinstance(v,dict):return {k:plain(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [plain(x) for x in v]
    return v


def digest(v):return hashlib.sha256(json.dumps(plain(v),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class FormationLayer:
    layer_id: str
    material_id: str
    phase: str
    mineral_mass_kg_m2: F
    grain_density_kg_m3: F
    porosity: F
    particle_masses_kg_m2: tuple
    inherited_horizon_candidates: tuple
    evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.layer_id,'layer');_text(self.material_id,'material');_source(self.evidence,self.source_status)
        if self.phase not in PHASES:raise ValueError('explicit bedrock/regolith/mobile phase required')
        for k in ('mineral_mass_kg_m2','grain_density_kg_m3','porosity'):object.__setattr__(self,k,_q(getattr(self,k),k))
        if self.mineral_mass_kg_m2<=0 or self.grain_density_kg_m3<=0 or self.porosity>=1:raise ValueError('positive finite mineral stock/density and porosity<1 required')
        if type(self.particle_masses_kg_m2) is not tuple or len(self.particle_masses_kg_m2)!=4:raise ValueError('four particle-size mass stocks required')
        masses=tuple(_q(v,'size mass') for v in self.particle_masses_kg_m2)
        if sum(masses,F())!=self.mineral_mass_kg_m2:raise ValueError('size stocks must close exactly to dry mineral mass')
        object.__setattr__(self,'particle_masses_kg_m2',masses);_candidates(self.inherited_horizon_candidates)
        if self.phase=='bedrock' and set(self.inherited_horizon_candidates)-{'C','R'}:raise ValueError('intact bedrock cannot be an inherited O/A/E/B mineral solum')
        _q(self.thickness_m,'thickness');_represented(self.thickness_m,'thickness')

    @property
    def thickness_m(self):return self.mineral_mass_kg_m2/(self.grain_density_kg_m3*(1-self.porosity))


@dataclass(frozen=True)
class FormationState:
    column_id: str
    layers: tuple
    base_elevation_m: F
    elapsed_seconds: F=F()
    applied_exposure_ids: tuple=()

    def __post_init__(self):
        _text(self.column_id,'column')
        if type(self.layers) is not tuple or len(self.layers)>MAX_LAYERS or any(type(v) is not FormationLayer for v in self.layers):raise ValueError('bounded top-to-bottom mineral layers required')
        if len({l.layer_id for l in self.layers})!=len(self.layers):raise ValueError('duplicate layer identity')
        object.__setattr__(self,'base_elevation_m',_q(self.base_elevation_m,'base',signed=True))
        object.__setattr__(self,'elapsed_seconds',_q(self.elapsed_seconds,'elapsed seconds'))
        if type(self.applied_exposure_ids) is not tuple or len(self.applied_exposure_ids)>1024 or len(set(self.applied_exposure_ids))!=len(self.applied_exposure_ids):raise ValueError('bounded unique exposure IDs required')
        for key in self.applied_exposure_ids:_text(key,'exposure ID')
        densities={}
        for layer in self.layers:
            if layer.material_id in densities and densities[layer.material_id]!=layer.grain_density_kg_m3:raise ValueError('one material cannot change grain density silently')
            densities[layer.material_id]=layer.grain_density_kg_m3
        _q(self.surface_elevation_m,'surface',signed=True);_represented(self.surface_elevation_m,'surface')

    @property
    def surface_elevation_m(self):return self.base_elevation_m+sum((l.thickness_m for l in self.layers),F())


def state_to_dict(state):
    if type(state) is not FormationState:raise ValueError('typed formation state required')
    return {'schema':'diadem.mineral-formation-state.r7',**plain(state)}


def state_from_dict(record):
    names=set(FormationState.__dataclass_fields__)
    if type(record) is not dict or set(record)!=names|{'schema'} or record['schema']!='diadem.mineral-formation-state.r7':raise ValueError('exact formation state schema required')
    if type(record['layers']) is not list:raise ValueError('serialized layers must be a list')
    layers=[]
    for row in record['layers']:
        if type(row) is not dict or set(row)!=set(FormationLayer.__dataclass_fields__):raise ValueError('exact layer schema required')
        values=dict(row)
        for key in ('particle_masses_kg_m2','inherited_horizon_candidates'):
            if type(values[key]) is not list:raise ValueError('serialized layer sequences must be lists')
            values[key]=tuple(values[key])
        layers.append(FormationLayer(**values))
    if type(record['applied_exposure_ids']) is not list:raise ValueError('serialized exposure IDs must be a list')
    return FormationState(record['column_id'],tuple(layers),record['base_elevation_m'],record['elapsed_seconds'],tuple(record['applied_exposure_ids']))


@dataclass(frozen=True)
class ExposureSegment:
    exposure_id: str
    duration_seconds: F
    soil_temperature_k: float|None
    water_filled_pore_fraction: float|None
    environment_state_id: str
    evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.exposure_id,'exposure ID');_text(self.environment_state_id,'actual environment state');_source(self.evidence,self.source_status)
        object.__setattr__(self,'duration_seconds',_q(self.duration_seconds,'exposure duration'))
        for k in ('soil_temperature_k','water_filled_pore_fraction'):
            if getattr(self,k) is not None:object.__setattr__(self,k,_float(getattr(self,k),k,positive=k=='soil_temperature_k'))
        if self.water_filled_pore_fraction is not None and self.water_filled_pore_fraction>1:raise ValueError('WFPS outside [0,1]')


@dataclass(frozen=True)
class ProductionLaw:
    material_id: str
    bare_rate_m_s: float
    cover_scale_m: float
    regolith_porosity: F
    dissolved_mass_fraction: F
    reference_temperature_k: float
    activation_energy_j_mol: float
    gas_constant_j_mol_k: float
    minimum_temperature_k: float
    maximum_temperature_k: float
    regime: str
    evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.material_id,'material');_source(self.evidence,self.source_status)
        if self.regime!='DEPTH_LIMITED_NONSELECTIVE_ROCK_DISAGGREGATION':raise ValueError('explicit reduced production regime required')
        for k in ('bare_rate_m_s','cover_scale_m','reference_temperature_k','activation_energy_j_mol','gas_constant_j_mol_k','minimum_temperature_k','maximum_temperature_k'):
            object.__setattr__(self,k,_float(getattr(self,k),k,positive=k not in ('bare_rate_m_s','activation_energy_j_mol')))
        for k in ('regolith_porosity','dissolved_mass_fraction'):object.__setattr__(self,k,_q(getattr(self,k),k))
        if self.regolith_porosity>=1 or self.dissolved_mass_fraction>1:raise ValueError('packing/yield fraction outside regime')
        if not self.minimum_temperature_k<=self.reference_temperature_k<=self.maximum_temperature_k:raise ValueError('thermal reference outside declared calibration range')


def _thermal(segment,law):
    t=segment.soil_temperature_k
    if not law.minimum_temperature_k<=t<=law.maximum_temperature_k:raise ValueError('soil temperature outside declared production regime')
    exponent=law.activation_energy_j_mol/law.gas_constant_j_mol_k*(1/law.reference_temperature_k-1/t)
    try:value=math.exp(exponent)*segment.water_filled_pore_fraction
    except OverflowError as exc:raise ValueError('thermal rate unrepresentable') from exc
    if not math.isfinite(value) or (segment.water_filled_pore_fraction>0 and value==0):raise ValueError('thermal/wetness driver unrepresentable')
    return value


def _balances(before,after,transfers):
    keys=sorted({l.material_id for l in (*before.layers,*after.layers)})
    rows=[]
    for key in keys:
        initial=sum((l.mineral_mass_kg_m2 for l in before.layers if l.material_id==key),F())
        final=sum((l.mineral_mass_kg_m2 for l in after.layers if l.material_id==key),F())
        dissolved=sum((t['dissolved_kg_m2'] for t in transfers if t['material_id']==key),F())
        if initial-final-dissolved:raise ArithmeticError('mineral mass ledger failed')
        rows.append(dict(material_id=key,initial_kg_m2=initial,final_kg_m2=final,dissolved_kg_m2=dissolved,residual_kg_m2=F()))
    return rows


def form_snapshot(state,exposures,laws,*,organic_cover_m):
    """Finite successive rock contacts with evolving cover; no grain-age shortcut.

    All non-rock layers remain separate. Their total bulk depth attenuates rock
    production. Intrusive/interbedded rock above buried regolith is excluded.
    Organic cover is an explicit fixed geometric scenario, not counted as mineral.
    """
    if type(state) is not FormationState or type(exposures) is not tuple or not 1<=len(exposures)<=MAX_SEGMENTS or any(type(x) is not ExposureSegment for x in exposures):raise ValueError('typed bounded state/exposure sequence required')
    if type(laws) is not tuple or any(type(x) is not ProductionLaw for x in laws) or len({x.material_id for x in laws})!=len(laws):raise ValueError('unique explicit material laws required')
    organic_cover=_q(organic_cover_m,'fixed organic cover')
    ids=tuple(x.exposure_id for x in exposures)
    if len(set(ids))!=len(ids) or set(ids)&set(state.applied_exposure_ids):raise ValueError('exposure replay/duplicate refused')
    rock_seen=False
    for l in state.layers:
        if l.phase=='bedrock':rock_seen=True
        elif rock_seen:raise ValueError('bounded model requires regolith cover above ordered bedrock, not interbedded/intrusive geometry')
    bylaw={x.material_id:x for x in laws}
    if any(l.material_id not in bylaw for l in state.layers if l.phase=='bedrock'):raise ValueError('every finite buried rock material requires a law')
    needed=[x for x in exposures if x.duration_seconds>0]
    if (any(l.source_status not in KNOWN for l in state.layers) or any(x.source_status not in KNOWN for x in laws)
            or any(x.source_status not in KNOWN or x.soil_temperature_k is None or x.water_filled_pore_fraction is None for x in needed)):
        return {'schema':'diadem.mineral-formation-snapshot.r7','status':'UNKNOWN','state':None,'reason':'required material/history/environment evidence unknown'}
    layers=list(state.layers);transfers=[];segment_rows=[]
    for segment in exposures:
        remaining=segment.duration_seconds;used=F();count=0
        while remaining>0:
            indices=[i for i,l in enumerate(layers) if l.phase=='bedrock']
            if not indices:break
            index=indices[0];rock=layers[index];law=bylaw[rock.material_id]
            factor=_thermal(segment,law);effective=law.bare_rate_m_s*factor
            if effective==0:
                if law.bare_rate_m_s>0 and factor>0:raise ValueError('positive production driver underflowed')
                break
            if not math.isfinite(effective):raise ValueError('effective production rate overflowed')
            cover=organic_cover+sum((l.thickness_m for l in layers[:index]),F())
            h=_represented(cover,'cover');scale=law.cover_scale_m
            rate=effective*math.exp(-h/scale)
            if rate==0 or not math.isfinite(rate):raise ValueError('positive attenuated production under/overflow')
            rb=rock.grain_density_kg_m3*(1-rock.porosity)
            gb=rock.grain_density_kg_m3*(1-law.regolith_porosity)
            gamma=(1-law.dissolved_mass_fraction)*rb/gb
            g=_represented(gamma,'cover feedback') if gamma else 0.
            dt=_represented(remaining,'exposure interval')
            raw=rate*dt
            lowering=raw if g==0 else scale/g*math.log1p(g*raw/scale)
            if not math.isfinite(lowering) or lowering<=0:raise ValueError('integrated lowering unrepresentable')
            demand=_q(lowering,'represented lowering')*rb
            consumed=min(rock.mineral_mass_kg_m2,demand)
            contact=remaining
            if demand>rock.mineral_mass_kg_m2:
                rock_depth=_represented(rock.thickness_m,'finite rock depth')
                try:t=rock_depth/rate if g==0 else scale/(g*rate)*math.expm1(g*rock_depth/scale)
                except OverflowError as exc:raise ValueError('finite contact time unrepresentable') from exc
                contact=_q(t,'represented contact time')
                if contact<=0 or contact>remaining:raise ValueError('contact time ordering unrepresentable')
            taken=tuple(v*consumed/rock.mineral_mass_kg_m2 for v in rock.particle_masses_kg_m2)
            dissolved=consumed*law.dissolved_mass_fraction
            retained=consumed-dissolved
            replacement=[];product_id=None
            if retained:
                product_id='formed-'+digest([state.column_id,segment.exposure_id,rock.layer_id,count])[:32]
                replacement.append(FormationLayer(product_id,rock.material_id,'immobile_regolith',retained,
                    rock.grain_density_kg_m3,law.regolith_porosity,tuple(v*(1-law.dissolved_mass_fraction) for v in taken),
                    ('C',),'Fresh weathered parent material; no automatic pedogenic horizon or inherited full age. '+law.evidence,'WORKING NON-CANON'))
            if consumed<rock.mineral_mass_kg_m2:
                replacement.append(replace(rock,mineral_mass_kg_m2=rock.mineral_mass_kg_m2-consumed,
                    particle_masses_kg_m2=tuple(a-b for a,b in zip(rock.particle_masses_kg_m2,taken))))
            layers[index:index+1]=replacement
            if len(layers)>MAX_LAYERS:raise ValueError('formation layer budget exceeded')
            transfers.append(dict(exposure_id=segment.exposure_id,source_layer_id=rock.layer_id,product_layer_id=product_id,
                material_id=rock.material_id,rock_consumed_kg_m2=consumed,regolith_produced_kg_m2=retained,dissolved_kg_m2=dissolved,
                size_origin_consumed_kg_m2=taken,size_origin_dissolved_kg_m2=tuple(v*law.dissolved_mass_fraction for v in taken),
                interval_start_seconds=used,interval_end_seconds=used+contact,cover_m=cover,environment_factor=factor,
                exposure_inheritance='Product birth spans this interval; no full-interval particle/organic age assigned'))
            remaining-=contact;used+=contact;count+=1
            if consumed<rock.mineral_mass_kg_m2:break
        segment_rows.append(dict(exposure_id=segment.exposure_id,environment_state_id=segment.environment_state_id,
            duration_seconds=segment.duration_seconds,production_active_seconds=used,inactive_or_exhausted_seconds=remaining))
    after=FormationState(state.column_id,tuple(layers),state.base_elevation_m,
        state.elapsed_seconds+sum((x.duration_seconds for x in exposures),F()),state.applied_exposure_ids+ids)
    changed=[(l.layer_id,l.mineral_mass_kg_m2,l.porosity) for l in state.layers]!=[(l.layer_id,l.mineral_mass_kg_m2,l.porosity) for l in after.layers]
    result={'schema':'diadem.mineral-formation-snapshot.r7','status':'MODELLED','state':after,'mineral_balances':_balances(state,after,transfers),'transfers':transfers,
        'exposures':segment_rows,'initial_surface_elevation_m':state.surface_elevation_m,'final_surface_elevation_m':after.surface_elevation_m,
        'geometry_changed':changed,'requires_water_rebind':changed,
        'input_state_sha256':digest(state),'exposure_hypotheses_sha256':digest(exposures),'production_laws_sha256':digest(laws),
        'numerical_scope':'binary64 integrated lowering/contact time; exact represented per-material and particle-origin mass transfers',
        'scope':'Finite weathered-parent production, not pedogenic solum; no hydraulic/pore-pressure reuse on changed geometry.'}
    json.dumps(plain(result),allow_nan=False);return result


def alter_particle_sizes(layer,*,rate_per_second,exposure,reference_temperature_k,
        activation_energy_j_mol,gas_constant_j_mol_k,minimum_temperature_k,maximum_temperature_k,evidence):
    """Equal-rate first-order fragmentation chain, preserving every mineral kg.

    The supplied exposure belongs to this existing cohort. It is not copied from
    the total age of a column containing material produced later.
    """
    if type(layer) is not FormationLayer or type(exposure) is not ExposureSegment:raise ValueError('typed existing layer/exposure required')
    _text(evidence,'fragmentation evidence');rate=_float(rate_per_second,'fragmentation rate')
    if layer.phase=='bedrock':raise ValueError('size alteration requires released regolith/sediment, not an intact bedrock grain proxy')
    law=ProductionLaw(layer.material_id,rate,1,layer.porosity,0,reference_temperature_k,activation_energy_j_mol,
        gas_constant_j_mol_k,minimum_temperature_k,maximum_temperature_k,'DEPTH_LIMITED_NONSELECTIVE_ROCK_DISAGGREGATION',evidence,exposure.source_status)
    if layer.source_status not in KNOWN or exposure.source_status not in KNOWN or exposure.soil_temperature_k is None or exposure.water_filled_pore_fraction is None:
        return {'status':'UNKNOWN','layer':None,'reason':'fragmentation environment/cohort unknown'}
    factor=_thermal(exposure,law) if exposure.duration_seconds else 0.
    dose=rate*factor*_represented(exposure.duration_seconds,'fragmentation duration') if exposure.duration_seconds else 0.
    if rate>0 and factor>0 and exposure.duration_seconds>0 and dose==0:raise ValueError('positive fragmentation dose underflowed')
    if dose==0:
        return {'status':'MODELLED','layer':layer,'transition_rows':[], 'mineral_mass_residual_kg_m2':F(),
            'clay_mineralogy':'NOT_PREDICTED','geometry_changed':False}
    if not math.isfinite(dose) or not 1e-100<=dose<=500:raise ValueError('fragmentation dose outside represented four-class reference envelope')
    survival=math.exp(-dose);matrix=[];reports=[]
    for origin in range(4):
        if origin==3:weights=[0.,0.,0.,1.]
        else:
            steps=3-origin;weights=[0.]*origin
            weights += [survival*dose**j/math.factorial(j) for j in range(steps)]
            weights += [float(gammainc(steps,dose))]
        if any(not math.isfinite(w) or w<0 for w in weights) or any(weights[j]<=0 for j in range(origin,4)):raise ValueError('positive particle pathway underflowed')
        total=sum((F(w) for w in weights),F())
        if abs(total-1)>F(PROBABILITY_ERROR_LIMIT):raise ValueError('particle probability closure exceeds declared numerical bound')
        row=tuple(F(w)/total for w in weights);matrix.append(row)
        correction=max(abs(p-F(w)) for p,w in zip(row,weights))
        if correction>F(PROBABILITY_ERROR_LIMIT):raise ValueError('particle normalisation correction exceeds declared numerical bound')
        reports.append({'origin':SIZE_CLASSES[origin],'represented_probabilities':row,
            'maximum_normalisation_change':float(correction),'probability_error_limit':PROBABILITY_ERROR_LIMIT})
    masses=tuple(sum((layer.particle_masses_kg_m2[i]*matrix[i][j] for i in range(4)),F()) for j in range(4))
    after=replace(layer,particle_masses_kg_m2=masses)
    return {'status':'MODELLED','layer':after,'transition_rows':reports,'dose':dose,
        'exposure_id':exposure.exposure_id,'environment_state_id':exposure.environment_state_id,
        'mineral_mass_residual_kg_m2':sum(masses,F())-layer.mineral_mass_kg_m2,
        'clay_mineralogy':'NOT_PREDICTED; clay-size particles are not a clay-mineral reaction product',
        'geometry_changed':False,'chemical_release_kg_m2':F()}


@dataclass(frozen=True)
class HorizonProtocol:
    protocol_id: str
    carbon_enrichment_threshold_low: F
    carbon_enrichment_threshold_high: F
    evidence: str

    def __post_init__(self):
        _text(self.protocol_id,'protocol');_text(self.evidence,'protocol evidence')
        for k in ('carbon_enrichment_threshold_low','carbon_enrichment_threshold_high'):object.__setattr__(self,k,_q(getattr(self,k),'C/kg mineral threshold'))
        if not 0<self.carbon_enrichment_threshold_low<=self.carbon_enrichment_threshold_high:raise ValueError('positive ordered explicit natural C-enrichment thresholds required')


def diagnose_horizons(state,organic_by_layer,parent_carbon_ratios,protocol,*,surface_organic=None,absent_solum_evidence=None,
        reconciled_mineral_thickness_m=None,geometry_evidence=None):
    """A/C candidates from carbon enrichment, inherited E/B only, optional O.

    organic_by_layer rows are actual MODELLED organic-module results. Parent
    references are explicit (low,high) C kg / mineral kg, not P1 support indices.
    Optional surface_organic is {result,bulk_density_kg_m3,layer_id,evidence} and
    represents a separately supplied organic-only O mantle, not mineral mixing.
    """
    if hashlib.sha256(OWNER_PATH.read_bytes()).hexdigest()!=OWNER_SHA256:raise ValueError('soil owner definition changed; no silent repin')
    if type(state) is not FormationState or type(protocol) is not HorizonProtocol or type(organic_by_layer) is not dict or type(parent_carbon_ratios) is not dict:raise ValueError('typed state and explicit diagnostic mappings required')
    ids={l.layer_id for l in state.layers}
    if set(organic_by_layer)-ids or set(parent_carbon_ratios)-ids:raise ValueError('organic/parent diagnostic support outside this column')
    references={}
    for key,pair in parent_carbon_ratios.items():
        if type(pair) is not tuple or len(pair)!=2:raise ValueError('ordered parent carbon reference pair required')
        lo,hi=(_q(v,'parent C/kg mineral') for v in pair)
        if lo>hi:raise ValueError('inverted parent reference')
        references[key]=(lo,hi)
    if absent_solum_evidence is not None:_text(absent_solum_evidence,'absent solum evidence')
    rows=[];organic_depth=F();depth=F();unknown_before=False;solum=F();boundary=False;possible_pedogenic=False
    def organic_values(row,layer_id):
        if type(row) is not dict:raise ValueError('actual organic result dictionary required')
        if row.get('schema')!='diadem.organic-carbon-snapshot.r7' or row.get('layer_id')!=layer_id or row.get('support_id')!=state.column_id:raise ValueError('organic result schema/layer/support identity mismatch')
        if row.get('status')!='MODELLED':return None
        carbon=_q(row.get('final_organic_carbon_kg_m2'),'actual organic carbon')
        dry=_q(row.get('final_organic_dry_mass_kg_m2'),'actual organic dry matter')
        if carbon>dry:raise ValueError('carbon exceeds organic dry matter')
        snapshot=plain(row.get('state'))
        carbon_ledger=row.get('carbon');dry_ledger=row.get('organic_dry_matter')
        if (type(snapshot) is not dict or snapshot.get('layer_id')!=layer_id or snapshot.get('support_id')!=state.column_id
                or type(carbon_ledger) is not dict or type(dry_ledger) is not dict):raise ValueError('actual organic state and conservative ledgers required')
        if (_q(snapshot.get('fast_carbon_kg_m2'),'fast carbon')+_q(snapshot.get('slow_carbon_kg_m2'),'slow carbon')!=carbon
                or _q(carbon_ledger.get('final_kg_m2'),'carbon ledger final')!=carbon
                or _q(dry_ledger.get('final_kg_m2'),'dry ledger final')!=dry
                or _q(carbon_ledger.get('residual_kg_m2'),'carbon residual',signed=True)!=0
                or _q(dry_ledger.get('residual_kg_m2'),'dry residual',signed=True)!=0):raise ValueError('organic diagnostic stock and ledger disagree')
        return carbon,dry
    organics={key:organic_values(value,key) for key,value in organic_by_layer.items()}
    mixed_positive=any(value is not None and value[1]>0 for value in organics.values())
    mixed_unknown=any(value is None for value in organics.values())
    material_unknown=any(layer.source_status not in KNOWN for layer in state.layers)
    geometry_known=not (mixed_positive or mixed_unknown or material_unknown)
    thicknesses={layer.layer_id:layer.thickness_m for layer in state.layers}
    if reconciled_mineral_thickness_m is not None:
        if type(reconciled_mineral_thickness_m) is not dict or set(reconciled_mineral_thickness_m)!=ids:raise ValueError('reconciled geometry must identify every current mineral layer exactly')
        _text(geometry_evidence,'explicit joint mineral/organic packing evidence')
        thicknesses={key:_q(value,'reconciled layer thickness') for key,value in reconciled_mineral_thickness_m.items()}
        for layer in state.layers:
            value=thicknesses[layer.layer_id]
            if value<layer.mineral_mass_kg_m2/layer.grain_density_kg_m3:raise ValueError('reconciled thickness below mineral solid volume')
            _represented(value,'reconciled thickness')
        geometry_known=not (mixed_unknown or material_unknown)
    elif geometry_evidence is not None:raise ValueError('geometry evidence without reconciled thicknesses')
    if surface_organic is not None:
        if type(surface_organic) is not dict or set(surface_organic)!={'result','bulk_density_kg_m3','layer_id','evidence'}:raise ValueError('explicit organic mantle geometry required')
        _text(surface_organic['layer_id'],'O layer');_text(surface_organic['evidence'],'O evidence')
        if surface_organic['layer_id'] in ids:raise ValueError('organic-only mantle duplicates a mineral layer')
        values=organic_values(surface_organic['result'],surface_organic['layer_id']);rho=_q(surface_organic['bulk_density_kg_m3'],'organic bulk density')
        if rho<=0:raise ValueError('positive organic-only bulk density required')
        if values is None:organic_depth=None
        else:organic_depth=values[1]/rho
        rows.append({'layer_id':surface_organic['layer_id'],'candidates':('O',) if values is not None and values[1]>0 else (),
            'top_depth_m':F(),'bottom_depth_m':organic_depth,'organic_carbon_kg_m2':None if values is None else values[0],
            'interpretation':'explicit separate organic-only surface mantle'})
        depth=organic_depth
    for layer in state.layers:
        inherited=layer.inherited_horizon_candidates
        candidates=inherited;diagnostic='inherited operational hypothesis, not inferred from material phase'
        values=organics.get(layer.layer_id)
        if layer.phase!='bedrock' and not set(inherited)&{'E','B','O'}:
            if values is None or layer.layer_id not in parent_carbon_ratios:candidates=()
            else:
                lo,hi=references[layer.layer_id]
                ratio=values[0]/layer.mineral_mass_kg_m2
                low,high=ratio-hi,ratio-lo
                candidates=('A',) if low>=protocol.carbon_enrichment_threshold_high else ('C',) if high<protocol.carbon_enrichment_threshold_low else ('A','C')
                diagnostic='computed organomineral carbon enrichment under '+protocol.protocol_id
        if layer.source_status not in KNOWN:
            candidates=();diagnostic='material/horizon evidence '+layer.source_status+'; supplied labels are not established'
        top=depth;thickness=thicknesses[layer.layer_id]
        depth=None if depth is None else depth+thickness
        rows.append({'layer_id':layer.layer_id,'material_id':layer.material_id,'candidates':candidates,
            'top_depth_m':top,'bottom_depth_m':depth,'mineral_mass_kg_m2':layer.mineral_mass_kg_m2,
            'organic_carbon_kg_m2':None if values is None else values[0],'interpretation':diagnostic,
            'material_source_status':layer.source_status,
            'thickness_m':thickness if geometry_known else None,'mineral_skeleton_thickness_m':layer.thickness_m,
            'depth_geometry_status':'MODELLED_EXPLICIT_PACKING' if geometry_known else 'UNRECONCILED_ORGANOMINERAL_GEOMETRY'})
        possible_pedogenic |= bool(set(candidates)&{'A','E','B'})
        if not boundary:
            if candidates and set(candidates)<={'C','R'}:boundary=True
            elif candidates and set(candidates)<={'A','E','B'}:solum+=thickness
            else:unknown_before=True
    if absent_solum_evidence is not None and possible_pedogenic:raise ValueError('explicit absent solum conflicts with possible pedogenic horizon')
    known=boundary and not unknown_before
    if solum==0 and absent_solum_evidence is None:known=False
    if absent_solum_evidence is not None and not possible_pedogenic and not unknown_before:solum=F();known=True
    if not geometry_known:known=False
    if not geometry_known:
        for row in rows:
            if row['layer_id'] in ids:row['top_depth_m']=None;row['bottom_depth_m']=None
    result={'schema':'diadem.operational-soil-profile.r7','status':'MODELLED','protocol_id':protocol.protocol_id,'horizons':rows,
        'mineral_pedogenic_solum_depth_m':solum if known else None,'solum_status':'MODELLED' if known else 'UNKNOWN',
        'surface_organic_thickness_m':organic_depth,'accepted_taxonomy':'NOT_SELECTED',
        'soil_formation_status':'operational C-enrichment profile hypotheses; not surveyed horizons or universal diagnostic taxonomy',
        'surface_organic_interpretation':'explicit separate mantle' if surface_organic is not None else 'no separate O mantle included in this declared column model',
        'profile_geometry_scope':'explicit reconciled mineral-plus-organic layer geometry and separate O mantle; never inferred pressure',
        'reconciled_mineral_thickness_m':None if reconciled_mineral_thickness_m is None else thicknesses,'geometry_evidence':geometry_evidence,
        'material_geometry_status':'UNKNOWN' if material_unknown else 'KNOWN_SUPPLIED_HYPOTHESIS',
        'requires_geometry_reconciliation':not geometry_known}
    json.dumps(plain(result),allow_nan=False);return result
