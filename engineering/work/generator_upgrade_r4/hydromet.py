"""Source-bound rain/snow, persistent SWE and SI potential evaporation demand.

This is a reduced, declared forcing model, not an energy-balance snowpack,
glacier, realised ET calculation, or automatic monthly weather disaggregation.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from fractions import Fraction as F
import ast
import hashlib
import json
import math
from pathlib import Path
from scipy.special import ndtr

STATUS = {"SYNTHETIC TEST", "WORKING NON-CANON", "CANON", "UNKNOWN"}
BASE = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-07-11/referenced-chatgpt-conversation-this-is-untrusted')
SNOW_SOURCE = BASE/'work/cryosphere/c1_r1/snow_model.py'
PINS = {
    str(SNOW_SOURCE): '3e940ea75930d1abe337d7e34ec1bdb19c89b0457b96c06355f8037492a3e2c8',
    str(BASE/'work/climate_ecology/c0r3_natural_geometry/build_c0r3_natural_geometry.py'): '726b9db001f58a09e9b25985fca7dec15015f4ce1ae49165104342e734413a4a',
    str(BASE/'work/climate_ecology/c1r2_1km_preview/build_c1r2_1km_preview.py'): '63a6975740a2ab3c1d0caa3ce3ea9235b590dab010bcfc4e798eb964411853f2',
    'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-4/outputs/Water_Source_Binding_Decisions_2026-09-10_R1.md': '41f2351fe9e0a1e97e3c70b083914ea51d0036ff4b46d157f12a2eb038b3e88f',
    'C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace/02_Working_Files/Geography/Climate_Biomes_Soils/Scientific_Upgrade_Decisions/2026-09-10-R1/CLIMATE_SOILS_OWNER_DECISION_2026-09-10_R1.md': 'ba909d8a3e34a1722cba51925d602eca28d749a91a7bbf2162baf99221b4de19',
}


def _text(v, name):
    if type(v) is not str or not v.strip() or len(v)>4096:
        raise ValueError(name+': explicit bounded identity/evidence required')
    return v


def _hash(v):
    if type(v) is not str or len(v)!=64 or any(c not in '0123456789abcdef' for c in v):
        raise ValueError('exact source/binding SHA256 required')
    return v


def _q(v, name, *, signed=False, positive=False):
    if type(v) not in (int,float,F) or (type(v) is float and not math.isfinite(v)):
        raise ValueError(name+': finite explicit physical quantity required')
    q=F(v)
    if max(q.numerator.bit_length(),q.denominator.bit_length())>8192 or (not signed and q<0) or (positive and q<=0):
        raise ValueError(name+': physical/representation range violated')
    return q


def _float(v, name, *, signed=False, positive=False):
    q=_q(v,name,signed=signed,positive=positive)
    try: result=float(q)
    except OverflowError as exc: raise ValueError(name+': binary64 overflow') from exc
    if not math.isfinite(result) or (q and result==0):
        raise ValueError(name+': not representable in binary64')
    return result


def _provenance(evidence, source_status):
    _text(evidence,'evidence')
    if source_status not in STATUS:raise ValueError('explicit supported source status required')


def verify_sources():
    for name,expected in PINS.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=expected:
            raise ValueError('protected hydrometeorology source changed: '+name)
    return dict(PINS)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def quantity(value):
    value=_q(value,'output quantity',signed=True)
    return {'exact':str(value),'value':_float(value,'output quantity',signed=True)}


@dataclass(frozen=True)
class SnowScenario:
    scenario_id: str
    degree_day_factor_mm_c_day: float
    temperature_sigma_c: float
    standing: str

    def __post_init__(self):
        if (self.scenario_id,self.degree_day_factor_mm_c_day,self.temperature_sigma_c,self.standing) not in (
            ('LOW_DDF3_SIGMA2',3.,2.,'COEQUAL_SENSITIVITY'),
            ('DIAGNOSTIC_DDF4_SIGMA4',4.,4.,'COEQUAL_SENSITIVITY'),
            ('HIGH_DDF5_SIGMA6',5.,6.,'COEQUAL_SENSITIVITY')):
            raise ValueError('preserve the three source-bound coequal joint scenarios; no selected median')
        _float(self.degree_day_factor_mm_c_day,'degree-day factor',positive=True)
        _float(self.temperature_sigma_c,'temperature sigma',positive=True)


def snow_scenarios():
    """Read the actual pinned predecessor declaration, without running its main."""
    verify_sources()
    tree=ast.parse(SNOW_SOURCE.read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MELT_SCENARIOS' for t in n.targets))
    result=tuple(SnowScenario(*row) for row in ast.literal_eval(node.value))
    if len(result)!=3 or len({x.scenario_id for x in result})!=3:raise ValueError('incomplete coequal snow family')
    return result


def positive_temperature(mean_c, sigma_c):
    """E[max(T,0)] under the explicitly chosen Gaussian thermal hypothesis."""
    t=_float(mean_c,'temperature C',signed=True);s=_float(sigma_c,'sigma C',positive=True)
    z=t/s
    if not math.isfinite(z):raise ValueError('unrepresentable thermal distribution')
    phi=math.exp(-.5*z*z)/math.sqrt(2*math.pi)
    result=math.fsum((s*phi,t*float(ndtr(z))))
    if not math.isfinite(result) or result<0 or (result==0 and t<0):
        raise ValueError('positive-temperature tail not representable; do not manufacture zero melt')
    return result


@dataclass(frozen=True)
class PhaseLaw:
    snow_at_or_below_c: float
    rain_at_or_above_c: float
    temperature_basis: str
    evidence: str

    def __post_init__(self):
        lo=_float(self.snow_at_or_below_c,'snow threshold',signed=True)
        hi=_float(self.rain_at_or_above_c,'rain threshold',signed=True)
        if lo>=hi or lo<=-273.15:raise ValueError('physical strictly ordered phase thresholds required')
        if self.temperature_basis not in ('AIR_TEMPERATURE','SUPPLIED_WET_BULB'):
            raise ValueError('explicit phase temperature meaning required')
        _text(self.evidence,'phase evidence')


def partition_precipitation(precipitation_m_s, temperature_c, law, *, wet_bulb_c=None, evidence, source_status):
    """Representative-interval linear phase hypothesis, never a universal 0 C rule."""
    if type(law) is not PhaseLaw:raise ValueError('explicit PhaseLaw required')
    _provenance(evidence,source_status)
    if source_status=='UNKNOWN' or precipitation_m_s is None or temperature_c is None or (law.temperature_basis=='SUPPLIED_WET_BULB' and wet_bulb_c is None):
        return {'status':'UNKNOWN','rain_m_s':None,'snowfall_m_s':None,'snow_fraction':None}
    p=_q(precipitation_m_s,'precipitation rate');air=_float(temperature_c,'air temperature',signed=True)
    if air<=-273.15:raise ValueError('air temperature at/below absolute zero')
    if law.temperature_basis=='AIR_TEMPERATURE':
        if wet_bulb_c is not None:raise ValueError('unused wet-bulb forcing is ambiguous')
        t=air
    else:
        t=_float(wet_bulb_c,'wet-bulb temperature',signed=True)
        if t>air:raise ValueError('wet bulb above air temperature requires another supersaturated regime')
    fraction=min(F(1),max(F(0),(F(law.rain_at_or_above_c)-F(t))/(F(law.rain_at_or_above_c)-F(law.snow_at_or_below_c))))
    snow=p*fraction;rain=p-snow
    return {'status':'MODELLED','source_status':'WORKING NON-CANON','precipitation_m_s':p,'rain_m_s':rain,'snowfall_m_s':snow,
            'snow_fraction':fraction,'phase_temperature_c':t,'law':asdict(law),'evidence':evidence,
            'scope':'supplied representative precipitation-time temperature, not a diagnosed unique submonthly phase history'}


def psychrometric_wet_bulb(temperature_c,vapour_pressure_pa,gamma_pa_k,*,saturation_liquid,
                          lower_bound_c,temperature_atol_c,vapour_atol_pa,max_iterations,evidence):
    """Solve es(Tw)-gamma*(T-Tw)=ea using the bound Climate saturation law.

    Constant-gamma ventilated psychrometric approximation, not an exact moist
    enthalpy/ice-bulb solver. No dry-air shortcut or pressure-independent fit.
    """
    _text(evidence,'wet-bulb model evidence')
    t=_float(temperature_c,'air temperature',signed=True);ea=_float(vapour_pressure_pa,'vapour pressure')
    gamma=_float(gamma_pa_k,'psychrometric gamma',positive=True)
    lo=_float(lower_bound_c,'wet-bulb lower bound',signed=True)
    xtol=_float(temperature_atol_c,'temperature tolerance',positive=True);ftol=_float(vapour_atol_pa,'vapour tolerance',positive=True)
    if lo>=t or lo<=-273.15 or not callable(saturation_liquid) or type(max_iterations) is not int or not 1<=max_iterations<=1000:
        raise ValueError('explicit bounded wet-bulb bracket and work budget required')
    def residual(x):
        es,slope=saturation_liquid(x)
        return _float(es,'saturation pressure',positive=True)-gamma*(t-x)-ea,_float(slope,'saturation slope',positive=True)
    fl,_=residual(lo);fh,_=residual(t)
    if fh<0:return {'status':'OUTSIDE_REGIME','wet_bulb_c':None,'reason':'supersaturated air is outside this phase proxy'}
    if fh==0:return {'status':'MODELLED','wet_bulb_c':t,'vapour_residual_pa':0.,'iterations':0,'model':'CONSTANT_GAMMA_PSYCHROMETRIC_LIQUID_WATER','evidence':evidence}
    if fl>0:return {'status':'OUTSIDE_REGIME','wet_bulb_c':None,'reason':'wet bulb falls below declared saturation-law bracket'}
    hi=t
    for count in range(1,max_iterations+1):
        mid=lo+(hi-lo)/2;fm,_=residual(mid)
        if abs(fm)<=ftol and hi-lo<=xtol:
            return {'status':'MODELLED','wet_bulb_c':mid,'vapour_residual_pa':fm,'iterations':count,
                    'model':'CONSTANT_GAMMA_PSYCHROMETRIC_LIQUID_WATER','evidence':evidence}
        if fm>0:hi=mid
        else:lo=mid
    return {'status':'NUMERICAL_FAILURE','wet_bulb_c':None,'reason':'wet-bulb residual/bracket did not converge within supplied work budget'}


@dataclass(frozen=True)
class SnowState:
    cell_id: str
    scenario_id: str
    binding_sha256: str
    elapsed_seconds: F
    swe_m: F
    chain_sha256: str

    def __post_init__(self):
        _text(self.cell_id,'snow cell');_text(self.scenario_id,'snow scenario');_hash(self.binding_sha256);_hash(self.chain_sha256)
        object.__setattr__(self,'elapsed_seconds',_q(self.elapsed_seconds,'elapsed seconds'))
        object.__setattr__(self,'swe_m',_q(self.swe_m,'physical SWE'))


def initial_snow(cell_id,scenario,initial_swe_m,*,binding_sha256,elapsed_seconds,evidence):
    if type(scenario) is not SnowScenario:raise ValueError('explicit retained snow scenario required')
    _text(evidence,'initial SWE evidence')
    initial=_q(initial_swe_m,'initial SWE');time=_q(elapsed_seconds,'start seconds')
    seed=digest({'cell':cell_id,'scenario':asdict(scenario),'swe':str(initial),'time':str(time),'binding':binding_sha256,'evidence':evidence})
    return SnowState(cell_id,scenario.scenario_id,binding_sha256,time,initial,seed)


def snow_step(state,scenario,*,temperature_c,precipitation_m_s,snowfall_m_s,start_seconds,duration_seconds,day_seconds,
              interval_id,input_sha256,binding_sha256,evidence,source_status,temperature_distribution_evidence):
    """Constant-rate snow balance, integrated exactly for represented melt capacity.

    The cursor makes replay of an already consumed interval fail. A parent must
    commit this returned state and its liquid transfer atomically; trial branches
    may evaluate the same immutable prior state without consuming anything.
    """
    if type(state) is not SnowState or type(scenario) is not SnowScenario:raise ValueError('typed persistent snow state/scenario required')
    _provenance(evidence,source_status);_text(temperature_distribution_evidence,'thermal-distribution hypothesis')
    _text(interval_id,'forcing interval');_hash(input_sha256);_hash(binding_sha256)
    start=_q(start_seconds,'start seconds');duration=_q(duration_seconds,'duration seconds',positive=True);day=_q(day_seconds,'explicit coefficient day seconds',positive=True)
    if state.scenario_id!=scenario.scenario_id or state.binding_sha256!=binding_sha256 or start!=state.elapsed_seconds:
        raise ValueError('snow state/scenario/source/cursor mismatch; repeated or skipped forcing prohibited')
    if source_status=='UNKNOWN' or any(v is None for v in (temperature_c,precipitation_m_s,snowfall_m_s)):
        return {'status':'UNKNOWN','state':None,'liquid_input_m_s':None,'ledger':None}
    p=_q(precipitation_m_s,'precipitation rate');sf=_q(snowfall_m_s,'snowfall rate')
    if sf>p:raise ValueError('snowfall water cannot exceed precipitation')
    warm=positive_temperature(temperature_c,scenario.temperature_sigma_c)
    capacity_rate=F(scenario.degree_day_factor_mm_c_day)*F(warm)/1000/day
    available=state.swe_m+sf*duration;capacity=capacity_rate*duration
    melt=min(available,capacity);end=available-melt;rain=(p-sf)*duration
    ledger={'initial_swe_m':state.swe_m,'precipitation_m':p*duration,'snowfall_m':sf*duration,'rain_m':rain,
            'potential_melt_m':capacity,'melt_m':melt,'final_swe_m':end,'liquid_to_soil_m':rain+melt,
            'snow_residual_m':state.swe_m+sf*duration-melt-end,
            'total_water_residual_m':state.swe_m+p*duration-(rain+melt)-end}
    # With constant snowfall and capacity, depletion occurs at this exact time;
    # the mean liquid rate alone does not imply a uniform melt history.
    depletion=None
    if capacity_rate>sf and state.swe_m:
        event=state.swe_m/(capacity_rate-sf)
        if event<duration:depletion=event
    identity={'prior':state.chain_sha256,'interval_id':interval_id,'input_sha256':input_sha256,
              'binding_sha256':binding_sha256,'start_seconds':str(start),'duration_seconds':str(duration),
              'day_seconds':str(day),'temperature_c':_float(temperature_c,'temperature',signed=True),
              'precipitation_m_s':str(p),'snowfall_m_s':str(sf),'scenario':asdict(scenario),
              'evidence':evidence,'source_status':source_status,'temperature_distribution_evidence':temperature_distribution_evidence}
    following=SnowState(state.cell_id,state.scenario_id,state.binding_sha256,start+duration,end,digest(identity))
    return {'status':'MODELLED','source_status':'WORKING NON-CANON','state':following,'scenario':asdict(scenario),
            'ledger':ledger,'liquid_input_m_s':(rain+melt)/duration,'mean_melt_m_s':melt/duration,
            'mean_positive_temperature_c':warm,'depletion_after_seconds':depletion,'forcing':identity,
            'coefficient_day_role':'RETAINED_86400_SECOND_DAY' if day==86400 else 'EXPLICIT_DAY_UNIT_SENSITIVITY_NOT_RETAINED_NUMERICS',
            'scope':'Gaussian temperature-index sensitivity; constant-rate snowfall; no refreezing/sublimation/ice flow or event truth'}


def state_json(state):
    if type(state) is not SnowState:raise ValueError('SnowState required')
    return {**asdict(state),'elapsed_seconds':str(state.elapsed_seconds),'swe_m':str(state.swe_m)}


def restore_snow(raw):
    if type(raw) is not dict or set(raw)!=set(SnowState.__dataclass_fields__):raise ValueError('exact snow checkpoint fields required')
    for key in ('elapsed_seconds','swe_m'):
        if type(raw[key]) is not str or len(raw[key])>6000:raise ValueError('bounded exact stored quantity required')
    return SnowState(**{**raw,'elapsed_seconds':F(raw['elapsed_seconds']),'swe_m':F(raw['swe_m'])})


def disaggregate_total(total_m,duration_seconds,fractions,*,evidence):
    """Explicit supplied weights, not an inferred storm distribution."""
    _text(evidence,'disaggregation hypothesis');total=_q(total_m,'monthly water total')
    if type(duration_seconds) is not tuple or type(fractions) is not tuple or not 1<=len(fractions)<=10000 or len(fractions)!=len(duration_seconds):
        raise ValueError('matching bounded interval and weight tuples required')
    durations=tuple(_q(v,'interval seconds',positive=True) for v in duration_seconds)
    weights=tuple(_q(v,'water fraction') for v in fractions)
    if sum(weights,F())!=1:raise ValueError('disaggregation fractions must sum exactly to one')
    return tuple({'duration_seconds':dt,'water_m':total*f,'rate_m_s':total*f/dt,'evidence':evidence} for dt,f in zip(durations,weights))


@dataclass(frozen=True)
class DemandSurface:
    net_radiation_w_m2: float
    ground_heat_flux_w_m2: float
    aerodynamic_resistance_s_m: float
    surface_resistance_s_m: float
    evidence: str

    def __post_init__(self):
        _float(self.net_radiation_w_m2,'net radiation',signed=True);_float(self.ground_heat_flux_w_m2,'ground heat',signed=True)
        _float(self.aerodynamic_resistance_s_m,'aerodynamic resistance',positive=True)
        _float(self.surface_resistance_s_m,'surface resistance');_text(self.evidence,'reference surface evidence')


@dataclass(frozen=True)
class DemandConstants:
    cp_air_j_kg_k: float
    latent_heat_j_kg: float
    molecular_mass_ratio: float
    water_density_kg_m3: float
    evidence: str

    def __post_init__(self):
        for n in ('cp_air_j_kg_k','latent_heat_j_kg','molecular_mass_ratio','water_density_kg_m3'):_float(getattr(self,n),n,positive=True)
        if self.molecular_mass_ratio>=1:raise ValueError('supplied water-vapour/dry-air molar mass ratio must be below one')
        _text(self.evidence,'physical constant evidence')


def penman_monteith(air,surface,constants,*,evidence,source_status):
    """General resistance PM in W/m2 and m/s; signed condensation kept separate.

    Thermodynamic es/slope/density come from the actual Climate producer. Their
    physical support and saturation convention must be supplied, not guessed.
    """
    if type(air) is not dict or type(surface) is not DemandSurface or type(constants) is not DemandConstants:
        raise ValueError('actual scalar air fields, DemandSurface and DemandConstants required')
    _provenance(evidence,source_status)
    names=('temperature_c','pressure_pa','specific_humidity_kg_kg','saturation_vapour_pressure_pa',
           'saturation_slope_pa_k','moist_air_density_kg_m3','saturation_convention')
    if source_status=='UNKNOWN' or any(air.get(n) is None for n in names):
        return {'status':'UNKNOWN','potential_evaporation_m_s':None,'potential_condensation_m_s':None,'signed_latent_heat_flux_w_m2':None}
    if air['saturation_convention']!='LIQUID_WATER':raise ValueError('this demand requires an explicit liquid-water saturation law')
    t=_float(air['temperature_c'],'air temperature',signed=True)
    if t<=-273.15:raise ValueError('air temperature below absolute zero')
    p=_float(air['pressure_pa'],'air pressure',positive=True);q=_float(air['specific_humidity_kg_kg'],'specific humidity')
    if q>=1:raise ValueError('specific humidity is kg water per kg moist air, below one')
    es=_float(air['saturation_vapour_pressure_pa'],'saturation vapour pressure',positive=True)
    delta=_float(air['saturation_slope_pa_k'],'saturation slope',positive=True)
    rho=_float(air['moist_air_density_kg_m3'],'moist air density',positive=True)
    c=constants;eps=c.molecular_mass_ratio
    if 'epsilon' in air and _float(air['epsilon'],'atmospheric molecular mass ratio',positive=True)!=eps:
        raise ValueError('atmosphere and demand use different molecular mass ratios')
    ea=p*q/(eps+(1-eps)*q)
    if es>=p or ea>=p:raise ValueError('vapour partial pressure must be below total pressure')
    if 'vapour_pressure_pa' in air:
        supplied=_float(air['vapour_pressure_pa'],'actual vapour pressure')
        if abs(supplied-ea)>1e-10*max(1,abs(ea),abs(supplied)):raise ValueError('q/pressure/epsilon and supplied vapour pressure disagree')
    gamma=c.cp_air_j_kg_k*p/(eps*c.latent_heat_j_kg)
    available=surface.net_radiation_w_m2-surface.ground_heat_flux_w_m2
    radiative=delta*available
    aerodynamic=rho*c.cp_air_j_kg_k*(es-ea)/surface.aerodynamic_resistance_s_m
    denominator=delta+gamma*(1+surface.surface_resistance_s_m/surface.aerodynamic_resistance_s_m)
    latent=(radiative+aerodynamic)/denominator
    rate=latent/(c.latent_heat_j_kg*c.water_density_kg_m3)
    if not all(math.isfinite(x) for x in (ea,gamma,available,radiative,aerodynamic,denominator,latent,rate)):
        raise ValueError('nonfinite potential evaporation calculation')
    return {'status':'MODELLED','source_status':'WORKING NON-CANON','signed_latent_heat_flux_w_m2':latent,
            'signed_potential_water_flux_m_s':rate,'potential_evaporation_m_s':max(0.,rate),
            'potential_condensation_m_s':max(0.,-rate),'actual_et_m_s':None,'actual_condensation_m_s':None,
            'vapour_pressure_pa':ea,'vapour_pressure_deficit_pa':es-ea,'psychrometric_constant_pa_k':gamma,
            'net_available_energy_w_m2':available,'radiative_numerator':radiative,'aerodynamic_numerator':aerodynamic,
            'denominator_pa_k':denominator,'surface':asdict(surface),'constants':asdict(constants),
            'atmospheric_inputs':{n:air[n] for n in names},'evidence':evidence,
            'scope':'supplied reference-surface potential demand only; condensation is potential, not a created soil-water input'}
