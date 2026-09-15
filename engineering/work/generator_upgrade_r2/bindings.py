"""Scoped parent compatibility and actual once-consumed snow-water forcing.

Owner source/scenario decisions are distinct from scientific acceptance. These
checks cannot authenticate an author's authority or turn a file into canon.
Dependency planning is deliberately per output, never a global pending-owner hold.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
import re
import stat


COORD=Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks')
REGISTRY=COORD/'work/scientific_upgrade_decisions_r1/owner_returns_B1.json'
REGISTRY_SHA='30fcc9f11ec8da39644cebad96854187c86b659ded921d89ac66f0c71e70f52e'
CHECKPOINT=COORD/'outputs/Scientific_Upgrade_Owner_Integration_2026-09-10_B1.md'
CHECKPOINT_SHA='13466bce2823bae90f2c08db762b5736c6195fa98a4d5fe7f36d153edab8bdab'
ECO_CHECKPOINT=COORD/'outputs/Scientific_Upgrade_Ecology_Integration_2026-09-10_B2.md'
ECO_CHECKPOINT_SHA='7989cd757944503143dc1256dbcd1f1022a3207a8392ecb9511585f847545b97'
ECO_OWNER=COORD.parent/'the-diadem-local-tasks-8/outputs/GEO_ENGINEERING_SCIENTIFIC_UPGRADE_DECISIONS_2026-09-10_R1_ECOLOGY.md'
ECO_OWNER_SHA='e43b6edabced8f9c652da23e8f1dfa49fa2d7ff30488eaf79eac49edce08965b'
HS11_CHECKPOINT=COORD/'outputs/Scientific_Upgrade_HS11_Integration_2026-09-10_B3.md'
HS11_CHECKPOINT_SHA='2b475af90a7b1e7aa29ae9a634897418528c182f008c9e0596a30fecda5a8954'
HS11_OWNER=COORD.parent/'diadem-species-coordinator/outputs/HS11_Larval_Host_Guild_Decision_2026-09-10_R1.md'
HS11_OWNER_SHA='d836e68c227dbf8d75be32cbfc9f42760377db301e00a738cc3037d2f81cb676'
REQUIRED={
    'terrain':set(), 'substrate':set(), 'politics':set(), 'population':set(),
    'climate_macro':{'terrain'}, 'climate_local':{'terrain','climate_macro'},
    'snowfall':{'climate_local'}, 'snowmelt':{'snowfall'},
    'water':{'terrain','climate_local','snowmelt'},
    'soil_hydraulic':{'water','climate_local','substrate'},
    'soil_substrate':{'substrate'}, 'biomes':{'climate_local','soil_hydraulic'},
    'sites':{'terrain','water','politics'}, 'productive_land':{'sites','politics','water'},
    'food':{'productive_land','water','climate_local'},
    'transport':{'sites','water','politics'}, 'food_delivery':{'food','transport','population'},
    'ecology_meanings':set(), 'ecology_arrays':{'terrain','climate_local','water','ecology_meanings'},
    'ecology_connectivity':{'terrain','water','ecology_arrays'},
}


def label(value,name):
    if type(value) is not str or not value.strip() or len(value)>1024:
        raise ValueError(name+' must be bounded nonblank text')
    return value


def digest(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}',value):
        raise ValueError('exact lowercase SHA256 required')
    return value


def captured(path,expected,max_bytes=24_576):
    path=Path(path)
    if not path.is_absolute():raise ValueError('absolute evidence path required')
    for item in (path,*path.parents):
        info=item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('linked/reparse evidence is not admitted')
    if not path.is_file() or path.stat().st_size>max_bytes:raise ValueError('evidence exceeds bounded slice')
    raw=path.read_bytes()
    if len(raw)>max_bytes or hashlib.sha256(raw).hexdigest()!=digest(expected):
        raise ValueError('evidence changed; no implicit source repin: '+str(path))
    return raw


def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    def bad(value):raise ValueError('nonfinite JSON')
    def real(value):
        value=float(value)
        if not math.isfinite(value):raise ValueError('unrepresentable JSON number')
        return value
    return json.loads(raw.decode('utf-8-sig'),object_pairs_hook=pairs,parse_constant=bad,parse_float=real)


def owner_bindings():
    """Read/hash each current decision slice separately; never re-audit its corpus."""
    captured(CHECKPOINT,CHECKPOINT_SHA)
    registry=strict_json(captured(REGISTRY,REGISTRY_SHA))
    rows=[]
    for item in registry['returns']:
        raw=captured(item['path'],item['sha256'])
        if len(raw)!=item['bytes']:raise ValueError('owner slice byte count changed')
        receipts=[]
        if 'source_receipt' in item:
            source=item['source_receipt'];r=captured(source['path'],source['sha256'])
            if len(r)!=source['bytes']:raise ValueError('source receipt byte count changed')
            receipts.append({'path':source['path'],'sha256':source['sha256']})
        rows.append({key:item[key] for key in ('key','path','sha256','status','decision_id','closed','remaining')}|
                    {'source_receipts':receipts})
    if [r['key'] for r in rows]!=['settlements','resources','infrastructure','water_systems','climate_biomes_soils']:
        raise ValueError('unexpected B1 owner inventory')
    captured(ECO_CHECKPOINT,ECO_CHECKPOINT_SHA);captured(ECO_OWNER,ECO_OWNER_SHA)
    captured(HS11_CHECKPOINT,HS11_CHECKPOINT_SHA);captured(HS11_OWNER,HS11_OWNER_SHA)
    return {'change_id':registry['change_id'],'checkpoint_sha256':CHECKPOINT_SHA,'registry_sha256':REGISTRY_SHA,
            'owner_slices':rows,'b1_pending_owners':registry['pending'],
            'ecology_delta':{'change_id':'GEO-SCIENTIFIC-UPGRADE-ECOLOGY-INTEGRATION-2026-09-10-B2',
                'checkpoint_path':str(ECO_CHECKPOINT),'checkpoint_sha256':ECO_CHECKPOINT_SHA,
                'owner_path':str(ECO_OWNER),'owner_sha256':ECO_OWNER_SHA,
                'status':'OWNER-BOUND WORKING MODEL CONTRACT - NOT CANON - NOT INSTALLED'},
            'pending_owners':['physical_frame','political_geography'],
            'hs11_permission':{'change_id':'GEO-SCIENTIFIC-UPGRADE-HS11-INTEGRATION-2026-09-10-B3',
                'checkpoint_path':str(HS11_CHECKPOINT),'checkpoint_sha256':HS11_CHECKPOINT_SHA,
                'owner_path':str(HS11_OWNER),'owner_sha256':HS11_OWNER_SHA,
                'permission':'WORKING NON-CANON conditional larval resource-guild hypothesis allowed',
                'gates':'local recruitment, not universal adult-cell occupancy',
                'persistence':'adult resources/refuge and reachable viable recruitment or explicit immigration; ECO-02 seed/reachability still required',
                'host_support_unknown':'CONDITIONAL_UNKNOWN, not zero or exclusion',
                'guild_support_alone_proves_recruitment':False,'named_guild_or_rate_selected':False,
                'essential_permission_choice_pending':False,
                'primary_source_status':'PRIMARY_DOMAIN_SOURCE_STATUS_UNVERIFIED'},
            'global_generation_hold':False,'physical_acceptance':False,'production_authority':False,
            'meaning':'bound owner source/scenario choices; unresolved choices limit only dependent outputs'}


def ecology_role(*,parent_branch,selected_climate_branch,arrays_match_parents,water_topology_bound,
                 organism_id,requires_hs11_host_gate=False,hs11_host_decision_bound=False):
    """Bind B2 reference/candidate roles; this does not generate realised ranges."""
    if parent_branch not in {'ECO_01_RETAINED_REFERENCE','SUCCESSOR_CANDIDATE'}:
        raise ValueError('explicit ecological parent branch required')
    if selected_climate_branch not in {'C1_R1_ORIGINAL','R1T14C_A_G_CANDIDATE'}:
        raise ValueError('explicit climate branch required')
    if type(organism_id) is not int or not 1<=organism_id<=20:
        raise ValueError('bound HS1-HS20 organism identity required')
    for flag in (arrays_match_parents,water_topology_bound,requires_hs11_host_gate,hs11_host_decision_bound):
        if type(flag) is not bool:raise ValueError('explicit compatibility flags required')
    reasons=[]
    if parent_branch=='ECO_01_RETAINED_REFERENCE' and selected_climate_branch!='C1_R1_ORIGINAL':
        reasons.append('retained ECO-01 is not compatible approval for climate A/G candidate')
    if not arrays_match_parents:reasons.append('recompute affected support/occupancy/barrier/endpoint arrays')
    if not water_topology_bound:reasons.append('bind reviewed successor Water topology; old 14 km is reference only')
    if organism_id==11 and requires_hs11_host_gate and not hs11_host_decision_bound:
        reasons.append('HS11 product must bind B3 local-recruitment permission; owner choice is closed')
    return {'state':'CONDITIONAL_UNKNOWN' if reasons else 'BOUND_SCENARIO_ONLY','reasons':reasons,
            'parent_independent_meanings_reusable':True,'realised_range_generated':False,
            'entity_density':'NOT_APPLICABLE' if organism_id==19 else 'REQUIRES_OWN_COUNTED_ENTITY_AND_MODEL',
            'population_totals_owner':'GEO - Populations & Active Bonds','global_hold':False,
            'physical_acceptance':False}


@dataclass(frozen=True)
class Product:
    role:str
    artifact_id:str
    content_sha256:str
    frame_id:str
    parents:dict[str,str]
    source_status:str

    def __post_init__(self):
        if self.role not in REQUIRED:raise ValueError('unknown dependency role')
        label(self.artifact_id,'artifact_id');label(self.frame_id,'frame_id');digest(self.content_sha256)
        if not isinstance(self.parents,(dict,MappingProxyType)) or not REQUIRED[self.role]<=set(self.parents):
            raise ValueError('product omitted a required physical dependency')
        if any(k not in REQUIRED or k==self.role for k in self.parents):raise ValueError('invalid parent role')
        for value in self.parents.values():digest(value)
        if self.source_status not in {'CANON','WORKING NON-CANON','REVIEW ONLY','SYNTHETIC TEST','UNKNOWN'}:
            raise ValueError('unsupported source status')
        object.__setattr__(self,'parents',MappingProxyType(dict(self.parents)))


def compatibility_plan(products, selected_hashes, *, frame_id):
    """Per-role dirty propagation. Identity compatibility is not physical approval."""
    label(frame_id,'frame_id')
    if type(selected_hashes) is not dict or any(k not in REQUIRED for k in selected_hashes):
        raise ValueError('explicit selected role identities required')
    for value in selected_hashes.values():digest(value)
    if not isinstance(products,(tuple,list)) or any(not isinstance(p,Product) for p in products):
        raise ValueError('typed products required')
    by_role={p.role:p for p in products}
    if len(by_role)!=len(products):raise ValueError('coequal branches cannot be collapsed to duplicate roles')
    states={};visiting=set()
    def visit(role):
        if role in states:return states[role]
        if role in visiting:raise ValueError('dependency cycle')
        if role not in by_role:
            return {'state':'MISSING_OUTPUT','reasons':[role]}
        visiting.add(role);product=by_role[role];reasons=[]
        if product.source_status=='UNKNOWN':reasons.append('unknown source')
        if product.frame_id!=frame_id:reasons.append('incompatible spatial frame')
        if selected_hashes.get(role)!=product.content_sha256:reasons.append('selected output identity differs or missing')
        for parent,expected in sorted(product.parents.items()):
            if selected_hashes.get(parent)!=expected:reasons.append('changed/missing parent:'+parent)
            if visit(parent)['state']!='REUSABLE_BY_IDENTITY':reasons.append('parent needs work:'+parent)
        visiting.remove(role)
        states[role]={'state':'RECOMPUTE_OR_BIND' if reasons else 'REUSABLE_BY_IDENTITY','reasons':reasons}
        return states[role]
    for role in sorted(by_role):visit(role)
    return {'products':states,'physical_acceptance':False,'global_hold':False,
            'scope':'declared dependencies/identities; no automatic source or canon adoption'}


def climate_role(*, branch, sensitivity, terrain_matches, purpose):
    if branch not in {'C1_R1_ORIGINAL','R1T14C_A_G_CANDIDATE'}:raise ValueError('undeclared climate branch')
    if purpose not in {'RECONCILED_SNAPSHOT','FIXED_FORCING_COMPARISON'}:raise ValueError('explicit experiment role required')
    if type(terrain_matches) is not bool:raise ValueError('terrain compatibility must be explicit')
    if branch=='R1T14C_A_G_CANDIDATE' and sensitivity=='G_C4_LOWER_EVAPORATION':
        raise ValueError('G C4=R1 is an identity placeholder, not a lower-evaporation scenario')
    allowed=({'R1','C4_UNRESOLVED_SENSITIVITY'} if branch=='C1_R1_ORIGINAL' else
             {'A_EVAP_750','A_EVAP_900','G_R1_C4_IDENTITY_PLACEHOLDER'})
    if sensitivity not in allowed:raise ValueError('scenario cannot cross climate parent branches')
    return {'branch':branch,'sensitivity':sensitivity,
            'action':'RECOMPUTE_MACRO_LOCAL_AND_AFFECTED_DESCENDANTS' if not terrain_matches and purpose=='RECONCILED_SNAPSHOT'
                     else 'FIXED_FORCING_COMPARISON_ONLY' if not terrain_matches else 'BOUND_REFERENCE_OR_CANDIDATE',
            'evaporation_envelope_mm_year':[750,1000],'chosen_evaporation_endpoint':None,
            'new_candidate_status':'WORKING NON-CANON','physical_acceptance':False}


def exact(value,name):
    if isinstance(value,bool) or not isinstance(value,(int,float,Fraction)):
        raise ValueError(name+' must be explicit finite nonnegative water volume')
    if isinstance(value,float) and not math.isfinite(value):raise ValueError('nonfinite water')
    q=Fraction(value)
    if q<0 or max(q.numerator.bit_length(),q.denominator.bit_length())>4096:raise ValueError('water quantity/resource bound')
    return q


@dataclass(frozen=True)
class SnowPacket:
    packet_id:str
    producer_id:str
    period_id:str
    domain_id:str
    climate_id:str
    initial_swe_m3:object
    snowfall_m3:object
    melt_m3:object
    final_swe_m3:object
    evidence:str

    def __post_init__(self):
        for key in ('packet_id','producer_id','period_id','domain_id','climate_id','evidence'):label(getattr(self,key),key)
        for key in ('initial_swe_m3','snowfall_m3','melt_m3','final_swe_m3'):
            object.__setattr__(self,key,exact(getattr(self,key),key))
        if self.initial_swe_m3+self.snowfall_m3!=self.melt_m3+self.final_swe_m3:
            raise ValueError('snow producer water ledger does not reconcile')


def consume_snow_liquid(packet, *, total_precipitation_m3, rain_m3, expected_producer_id,
                        period_id, domain_id, climate_id, consumed=()):
    """Compute actual rain+melt forcing and a persistable consumption ledger.

    Neither snow input nor groundwater recharge/release is added as a second
    independent liquid input. A caller must persist returned consumed keys with
    its state; this pure function is not a cross-process transaction manager.
    """
    if not isinstance(packet,SnowPacket):raise ValueError('typed snow-ledger output required')
    for name in ('period_id','domain_id','climate_id'):
        if getattr(packet,name)!=locals()[name]:raise ValueError('incompatible snow forcing '+name)
    if packet.producer_id!=expected_producer_id:raise ValueError('snow melt must have one named producer')
    if not isinstance(consumed,(tuple,list)) or len(consumed)>=4096 or any(type(x) is not str or len(x)>4096 for x in consumed):
        raise ValueError('bounded persisted consumption ledger required')
    if len(set(consumed))!=len(consumed):raise ValueError('duplicate consumption history')
    key=json.dumps([packet.producer_id,period_id,domain_id],separators=(',',':'))
    if key in consumed:raise ValueError('snow melt already consumed for this producer/domain/period')
    total=exact(total_precipitation_m3,'total precipitation');rain=exact(rain_m3,'rain')
    if total!=rain+packet.snowfall_m3:raise ValueError('rain/snow partition differs from precipitation')
    liquid=rain+packet.melt_m3
    return {'schema':'diadem.single-snow-liquid-forcing.r1','liquid_input_m3':str(liquid),
            'rain_m3':str(rain),'snow_melt_m3':str(packet.melt_m3),'retained_swe_m3':str(packet.final_swe_m3),
            'water_residual_m3':'0','consumed':[*consumed,key],'packet_id':packet.packet_id,
            'period_id':period_id,'domain_id':domain_id,'climate_id':climate_id,
            'source_status':'WORKING NON-CANON','scope':'input conservation only; not runoff or aquifer generation'}
