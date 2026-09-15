"""Bounded open-transect moist-air transport, not atmospheric circulation.

Prescribed lower-air temperature/pressure and 10 m wind drive finite vapour,
cloud and precipitation transfers. No old climate parent is renormalised here.
"""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction as F
import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np
from scipy.linalg import expm

MAX_CELLS=32
MAX_BITS=8192
SATURATION_CONVENTION='LIQUID_WATER'


def _text(v,name):
    if type(v) is not str or not v.strip() or len(v)>2048:raise ValueError(name+': explicit bounded identity/evidence required')
    return v


def _number(v,name,positive=False,signed=False):
    if type(v) not in (int,float,F):raise ValueError(name+': known numeric quantity required')
    try:f=float(v)
    except OverflowError as e:raise ValueError(name+': unrepresentable') from e
    if not math.isfinite(f) or (v and f==0) or (not signed and f<0) or (positive and f<=0):
        raise ValueError(name+': finite representable physical range required')
    q=F(v)
    if max(q.numerator.bit_length(),q.denominator.bit_length())>MAX_BITS:raise ValueError(name+': exact resource bound')
    return f


def _safe(v,name):return _number(v,name,signed=True)


def _fraction(v):
    q=F(v)
    if max(q.numerator.bit_length(),q.denominator.bit_length())>MAX_BITS:raise ValueError('atmospheric exact resource bound')
    return q


def _json(v):
    if isinstance(v,F):return str(v)
    if isinstance(v,dict):return {k:_json(x) for k,x in v.items()}
    if isinstance(v,(tuple,list)):return [_json(x) for x in v]
    return v


def saturation_liquid(temperature_c):
    """Murphy–Koop 2005 Eq10 pure liquid/supercooled water, Pa and Pa/K.

    Not ice saturation, mixed-phase microphysics, Kelvin curvature or the small
    moist-air enhancement correction. Mathematical source range 123<T<332 K.
    """
    t=_number(temperature_c,'temperature',signed=True)+273.15
    if not 123<t<332:raise ValueError('liquid saturation fit requires 123<T<332 K')
    b=53.878-1331.22/t-9.44523*math.log(t)+.014025*t
    db=1331.22/t**2-9.44523/t+.014025
    h=math.tanh(.0415*(t-218.8))
    loge=54.842763-6763.22/t-4.210*math.log(t)+.000367*t+h*b
    derivative=6763.22/t**2-4.210/t+.000367+.0415*(1-h*h)*b+h*db
    e=math.exp(loge)
    return _number(e,'saturation pressure',True),_number(e*derivative,'saturation slope',True)


@dataclass(frozen=True)
class Cell:
    cell_id:str
    length_m:float
    width_m:float
    elevation_m:float
    evidence:str

    def __post_init__(self):
        _text(self.cell_id,'cell');_text(self.evidence,'terrain evidence')
        for k in ('length_m','width_m'):object.__setattr__(self,k,_number(getattr(self,k),k,True))
        object.__setattr__(self,'elevation_m',_number(self.elevation_m,'elevation',signed=True))
        _number(self.length_m*self.width_m,'cell plan area',True)


@dataclass(frozen=True)
class AirMass:
    """Reference ground elevation with representative air T/p at 2 m above it.

    Target T/p refer to 2 m above each target ground cell. Equal added heights
    cancel in the reference-to-target elevation difference. The lower air is
    assumed vertically well mixed for the exposed q2m value, not observed so.
    """
    reference_elevation_m:float
    reference_temperature_c:float
    reference_pressure_pa:float
    lapse_k_m:float
    wind_east_10m_m_s:float
    wind_north_10m_m_s:float
    dry_air_flux_kg_s:float
    inlet_specific_humidity:float
    inlet_condensate_kg_per_kg_dry_air:float
    gravity_m_s2:float
    dry_air_gas_constant_j_kg_k:float
    epsilon:float
    water_density_kg_m3:float
    evidence:str

    def __post_init__(self):
        _text(self.evidence,'atmospheric forcing evidence')
        signed=('reference_elevation_m','reference_temperature_c','lapse_k_m','wind_east_10m_m_s','wind_north_10m_m_s')
        positive=('reference_pressure_pa','dry_air_flux_kg_s','gravity_m_s2','dry_air_gas_constant_j_kg_k','epsilon','water_density_kg_m3')
        for k in signed+positive+('inlet_specific_humidity','inlet_condensate_kg_per_kg_dry_air'):
            object.__setattr__(self,k,_number(getattr(self,k),k,k in positive,k in signed))
        if self.inlet_specific_humidity>=1 or self.epsilon>=1:raise ValueError('q and molecular-mass ratio must be below one')
        saturation_liquid(self.reference_temperature_c)


@dataclass(frozen=True)
class Controls:
    condensation_seconds:float
    fallout_seconds:float
    evaporation_seconds:float
    transect_east_unit:float
    transect_north_unit:float
    calm_threshold_m_s:float
    maximum_relief_slope:float
    maximum_cloud_mixing_ratio:float
    maximum_supersaturation:float
    evidence:str

    def __post_init__(self):
        _text(self.evidence,'process/regime evidence')
        for k in ('condensation_seconds','fallout_seconds','evaporation_seconds','maximum_relief_slope','maximum_cloud_mixing_ratio','maximum_supersaturation'):
            object.__setattr__(self,k,_number(getattr(self,k),k,True))
        for k in ('transect_east_unit','transect_north_unit'):
            object.__setattr__(self,k,_number(getattr(self,k),k,signed=True))
        object.__setattr__(self,'calm_threshold_m_s',_number(self.calm_threshold_m_s,'calm threshold'))
        if abs(math.hypot(self.transect_east_unit,self.transect_north_unit)-1)>1e-12:
            raise ValueError('explicit unit transect direction required')
        if self.maximum_supersaturation<1 or self.maximum_cloud_mixing_ratio>=1:
            raise ValueError('explicit bounded cloud and saturation regime required')


def _transition(vapour,cloud,saturation,seconds,controls):
    """Exact mass accounting for represented constant-state compartment solves.

    Above saturation: excess vapour -> cloud -> fallout (two exponential waits).
    Below saturation: cloud evaporates and falls concurrently until saturation;
    thereafter only fallout. Thermal energy is externally maintained, not solved.
    """
    t=_number(seconds,'air travel time',True)
    a=_number(1/controls.condensation_seconds,'condensation rate',True)
    b=_number(1/controls.fallout_seconds,'fallout rate',True)
    e=_number(1/controls.evaporation_seconds,'evaporation rate',True)
    products=[_number(rate*t,'microphysical rate*time',True) for rate in (a,b,e)]
    if max(products)>100:raise ValueError('microphysical rate*time exceeds bounded matrix regime; refine spatial cells')
    v,c,s=map(F,(vapour,cloud,saturation))
    if min(v,c,s)<0:raise ValueError('negative atmospheric stock')
    # A sufficient continuous-time envelope, not a sampled peak estimate:
    # cloud can receive at most all supersaturated vapour; evaporation/fallout
    # only remove cloud. This intentionally rejects some safe fast-fallout cases.
    envelope=c+max(v-s,F(0))
    if envelope>F(controls.maximum_cloud_mixing_ratio):
        raise ValueError('continuous cloud envelope exceeds bounded regime; endpoint samples are insufficient')
    record={'initial_vapour':v,'initial_cloud':c,'saturation_mixing_ratio':s,'seconds':t,
            'continuous_cloud_upper_bound':envelope,'cloud_bound_method':'sufficient cloud plus all available supersaturated vapour; not an exact peak'}
    if v>s:
        # A conservative continuous-time compartment matrix. Independent tests
        # use analytical equal-rate limits and a separate ODE integration.
        matrix=np.array([[-a,0,0],[a,-b,0],[0,b,0]],dtype=float)*t
        raw=expm(matrix)
        columns=[];deviation=[]
        for j in (0,1):
            values=[F(float(raw[i,j])) for i in range(3)]
            if any(x<0 for x in values):raise ValueError('negative matrix transition probability')
            total=sum(values,F(0));delta=total-1
            if abs(delta)>F(1e-12):raise ValueError('matrix transition fails conservative probability bound')
            if (j==0 and any(values[i]==0 for i in (0,1,2))) or (j==1 and any(values[i]==0 for i in (1,2))):
                raise ValueError('positive atmospheric branch vanished numerically')
            columns.append([x/total for x in values]);deviation.append(delta)
        x=v-s;p0,p1=columns
        v1=s+x*p0[0];c1=x*p0[1]+c*p1[1];rain=x*p0[2]+c*p1[2]
        record.update(regime='CONDENSATION_AND_DELAYED_FALLOUT',probability_sum_errors=deviation,
                      probability_normalisation='exact positive column normalisation of represented expm coefficients')
    elif c and v<s:
        rate=_number(e+b,'combined cloud removal rate',True)
        loss=F(-math.expm1(-rate*t));share=F(e)/(F(e)+F(b))
        if not 0<loss<1:raise ValueError('positive cloud removal/survival branch vanished; refine spatial cells')
        potential=c*loss*share;deficit=s-v
        if potential<=deficit:
            evaporated=potential;rain=c*loss*(1-share);c1=c-evaporated-rain;v1=v+evaporated
        else:
            x=deficit/(c*share)
            hit=-math.log1p(-float(x))/rate
            if not 0<hit<t:raise ValueError('saturation switch not numerically resolved')
            evaporated=deficit;rain0=deficit*F(b)/F(e);left=c-evaporated-rain0
            if left<0:raise ValueError('cloud overdraw at saturation switch')
            fraction=F(-math.expm1(-b*(t-hit)))
            if left and not 0<fraction<1:raise ValueError('positive post-switch cloud branch vanished; refine spatial cells')
            rain=rain0+left*fraction;c1=left*(1-fraction);v1=s
        record.update(regime='LEE_EVAPORATION_AND_FALLOUT',evaporated=evaporated)
    else:
        loss=F(-math.expm1(-b*t))
        if c and not 0<loss<1:raise ValueError('positive fallout/survival branch vanished; refine spatial cells')
        rain=c*loss;c1=c-rain;v1=v
        record.update(regime='PURE_FALLOUT_OR_DRY_AIR')
    for x in (v1,c1,rain):_fraction(x)
    if min(v1,c1,rain)<0 or v+c!=v1+c1+rain:raise ArithmeticError('atmospheric material budget failed')
    record.update(final_vapour=v1,final_cloud=c1,precipitated=rain,residual=F(0))
    return v1,c1,rain,record


def _thermo(cell,air):
    dz=cell.elevation_m-air.reference_elevation_m
    base=air.reference_temperature_c+273.15
    t=base-air.lapse_k_m*dz
    es,delta=saturation_liquid(t-273.15)
    # Dry-reference hydrostatic profile; no assertion that moist dynamic
    # pressure/circulation has been solved from the current q field.
    x=-air.lapse_k_m*dz/base
    if x<=-1:raise ValueError('nonpositive environmental temperature')
    factor=1.0 if x==0 else math.log1p(x)/x
    log_ratio=-air.gravity_m_s2*dz/(air.dry_air_gas_constant_j_kg_k*base)*factor
    try:p=air.reference_pressure_pa*math.exp(log_ratio)
    except OverflowError as exc:raise ValueError('hydrostatic pressure overflow') from exc
    p=_number(p,'hydrostatic pressure',True)
    if es>=p:raise ValueError('saturation vapour pressure must be below total pressure')
    rs=_number(air.epsilon*es/(p-es),'saturation dry-air mixing ratio',True)
    return t-273.15,p,es,delta,F(rs)


def generate(cells,atmosphere,controls):
    """Return JSON-safe scalars/ledgers from actual current terrain.

    Cells are ordered along the declared horizontal transect. Negative projected
    wind reverses traversal, not geography. Crosswind, calm flow, unequal widths
    and unresolved/unsupported physical regimes reject; no invented zero climate.
    """
    if type(atmosphere) is not AirMass or type(controls) is not Controls:raise ValueError('typed atmosphere and controls required')
    if type(cells) not in (tuple,list) or not 1<=len(cells)<=MAX_CELLS or any(type(c) is not Cell for c in cells):
        raise ValueError('bounded typed transect required')
    if len({c.cell_id for c in cells})!=len(cells):raise ValueError('duplicate cell identity')
    if len({c.width_m for c in cells})!=1:raise ValueError('constant streamtube width required; no unmodelled lateral convergence')
    a=atmosphere;c=controls
    along=a.wind_east_10m_m_s*c.transect_east_unit+a.wind_north_10m_m_s*c.transect_north_unit
    across=-a.wind_east_10m_m_s*c.transect_north_unit+a.wind_north_10m_m_s*c.transect_east_unit
    speed=math.hypot(a.wind_east_10m_m_s,a.wind_north_10m_m_s)
    if not math.isfinite(speed) or abs(along)<=c.calm_threshold_m_s:raise ValueError('calm/indeterminate advective forcing requires another model')
    if abs(across)>1e-12*speed:raise ValueError('crosswind transport outside one-dimensional transect')
    for left,right in zip(cells,cells[1:]):
        slope=abs(right.elevation_m-left.elevation_m)/((left.length_m+right.length_m)/2)
        if slope>c.maximum_relief_slope:raise ValueError('terrain slope outside supplied flow-over regime')
    ordered=tuple(cells if along>0 else reversed(cells))
    q=F(a.inlet_specific_humidity);v=q/(1-q);cloud=F(a.inlet_condensate_kg_per_kg_dry_air)
    inlet=v+cloud;dry=F(a.dry_air_flux_kg_s);precipitated=F(0);delivered=F(0);out={};ledger=[]
    for cell in ordered:
        t,p,es,delta,rs=_thermo(cell,a)
        travel=_number(cell.length_m/abs(along),'cell travel time',True)
        if v>rs*F(c.maximum_supersaturation) or cloud>F(c.maximum_cloud_mixing_ratio):
            raise ValueError('inflow exceeds explicitly bounded cloud/supersaturation regime')
        mid_v,mid_cloud,rain1,first=_transition(v,cloud,rs,travel/2,c)
        end_v,end_cloud,rain2,second=_transition(mid_v,mid_cloud,rs,travel/2,c)
        if max(mid_cloud,end_cloud)>F(c.maximum_cloud_mixing_ratio):
            raise ValueError('formed condensate exceeds explicitly bounded cloud regime')
        rain=rain1+rain2
        qq=mid_v/(1+mid_v)
        qf=_number(qq,'specific humidity')
        vapour_pressure=p*qf/(a.epsilon+(1-a.epsilon)*qf)
        virtual=(t+273.15)*(1+(1/a.epsilon-1)*qf)
        rho=p/(a.dry_air_gas_constant_j_kg_k*virtual)
        area=F(cell.length_m)*F(cell.width_m)
        rate=rain*dry/(area*F(a.water_density_kg_m3));represented_rate=_number(rate,'precipitation rate')
        delivered_mass=F(represented_rate)*area*F(a.water_density_kg_m3)
        out[cell.cell_id]={'temperature_c':t,'pressure_pa':p,'specific_humidity_kg_kg':qf,
            'vapour_pressure_pa':vapour_pressure,'saturation_vapour_pressure_pa':es,'saturation_slope_pa_k':delta,
            'saturation_convention':SATURATION_CONVENTION,'moist_air_density_kg_m3':_number(rho,'moist-air density',True),
            'relative_humidity_liquid':vapour_pressure/es,'epsilon':a.epsilon,
            'wind_east_10m_m_s':a.wind_east_10m_m_s,'wind_north_10m_m_s':a.wind_north_10m_m_s,
            'mean_scalar_speed_10m_m_s':speed,'resultant_speed_10m_m_s':speed,
            'wind_from_degrees':math.degrees(math.atan2(-a.wind_east_10m_m_s,-a.wind_north_10m_m_s))%360,
            'wind_direction_flag':'DEFINED_SINGLE_PRESCRIBED_FLOW','precipitation_m_s':represented_rate,
            'precipitation_representation_error_m_s':F(represented_rate)-rate,
            'vapour_support':'2m representative cell centre under explicit vertically well-mixed lower-air hypothesis',
            'cloud_mixing_ratio_kg_per_kg_dry_air':float(mid_cloud),
            'wind_support':'supplied 10m vector, assumed also representative transport velocity; not solved circulation',
            'source_status':'WORKING NON-CANON'}
        ledger.append({'cell_id':cell.cell_id,'elevation_m':cell.elevation_m,'area_m2':area,'travel_seconds':travel,
            'inlet_vapour_kg_s':v*dry,'inlet_cloud_kg_s':cloud*dry,
            'outlet_vapour_kg_s':end_v*dry,'outlet_cloud_kg_s':end_cloud*dry,
            'precipitation_kg_s':rain*dry,'water_mass_residual_kg_s':F(0),
            'delivered_precipitation_m_s':represented_rate,'delivered_precipitation_kg_s':delivered_mass,
            'precipitation_flux_conversion_error_kg_s':delivered_mass-rain*dry,'microphysics':(first,second)})
        precipitated+=rain;delivered+=delivered_mass;v,cloud=end_v,end_cloud
    residual=(inlet-v-cloud-precipitated)*dry
    if residual:raise ArithmeticError('whole-transect water budget failed')
    return _json({'cells':out,'receipt':{'schema':'diadem.moist-air-transect.r4','status':'BOUNDED_MECHANISTIC_REFERENCE',
        'source_status':'WORKING NON-CANON','inlet_water_kg_s':inlet*dry,'outlet_vapour_kg_s':v*dry,
        'outlet_cloud_kg_s':cloud*dry,'precipitation_kg_s':precipitated*dry,'water_mass_residual_kg_s':residual,
        'delivered_precipitation_kg_s':delivered,'precipitation_flux_conversion_error_kg_s':delivered-precipitated*dry,
        'traversal':[x.cell_id for x in ordered],'cells':ledger,'thermal_profile':'externally maintained lapse and dry-reference hydrostatic pressure; reference T/p at 2m above reference ground datum, target T/p at 2m above target ground; no latent-energy or circulation closure',
        'saturation_law':'Murphy-Koop2005 Eq10 pure liquid/supercooled water, analytic derivative, 123<T<332K; no air-enhancement correction',
        'accounting':'exact represented compartment transfers; constitutive exponentials and thermodynamics are binary64 approximations',
        'limits':'steady open straight transect, piecewise constant thermal cells, prescribed flow-over; no lateral convergence, blocking/waves, recycling, convection or resolved vertical atmosphere',
        'old_climate_parent_reused':False,'production_authorised':False,'evidence':a.evidence}})


def retained_candidate_cell(row,col):
    """Read one real A 5 km monthly cell; never relabel it G or new-terrain climate."""
    if type(row) is not int or type(col) is not int or not (0<=row<372 and 0<=col<440):raise ValueError('bounded candidate row/column required')
    pins=json.loads((Path(__file__).parent/'CLIMATE_SOURCE_BINDINGS.json').read_text(encoding='utf-8'))
    sources=pins['retained_bridge'];read={}
    for key,record in sources.items():
        path=Path(record['path']);raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('retained candidate binding changed: '+key)
        read[key]=raw
    with np.load(io.BytesIO(read['geometry']),allow_pickle=False) as d:
        if d['land'].shape!=(372,440) or d['land'][row,col]!=1:raise ValueError('selected candidate cell is not known land')
        elevation=float(d['terrain_m'][row,col])
    with np.load(io.BytesIO(read['monthly']),allow_pickle=False) as d:
        months=d['months'].tolist()
        if months!=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'] or float(d['cell_km'])!=5:
            raise ValueError('candidate calendar/grid changed')
        fields={}
        for key in ('temperature_c','precipitation_mm','pet_mm','snow_fraction'):
            values=d[key]
            if values.shape!=(12,372,440):raise ValueError('candidate monthly shape changed')
            fields[key]=values[:,row,col].astype(float).tolist()
    if any(not math.isfinite(v) for values in fields.values() for v in values):raise ValueError('unknown candidate monthly value')
    if min(fields['precipitation_mm']+fields['pet_mm']+fields['snow_fraction'])<0 or max(fields['snow_fraction'])>1:
        raise ValueError('candidate water/phase bounds failed')
    fields['snowfall_we_mm']=[p*f for p,f in zip(fields['precipitation_mm'],fields['snow_fraction'])]
    return {'months':months,'days':[31,28,31,30,31,30,31,31,30,31,30,31],'fields':fields,
        'row':row,'col':col,'cell_km':5,'parent_elevation_m':elevation,
        'status':'RETAINED_A_PARENT_FIXED_FORCING_SENSITIVITY_ONLY','candidate_status':'PASS_CORE_PENDING_MICHAEL_VISUAL_REVIEW',
        'G_role':'separate 1km derivative; C4=R1 identity placeholder; G values not read here',
        'new_terrain_compatible':False,'source_bindings':sources,
        'limits':'real monthly A input, not event history or a changed-terrain macro recomputation; no wind or humidity inferred'}
