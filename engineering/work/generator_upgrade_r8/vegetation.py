"""Explicit seasonal PFT admissibility, not realised cover or productivity.

The available-water reservoir is a declared reduced model: dS/dt=I-D*S/C,
0<=S<=C. Overflow is unpartitioned surplus, not groundwater/runoff prediction.
"""
from dataclasses import dataclass, asdict
from fractions import Fraction as F
import math

KNOWN = {'SYNTHETIC TEST', 'WORKING NON-CANON', 'CANON', 'MODELLED'}
STATUSES = KNOWN | {'UNKNOWN', 'CONFLICT', 'INCOMPLETE'}
METRICS = {'coldest_month_temperature_c', 'warmest_month_temperature_c',
           'growing_degree_days', 'rooted_depth_m',
           'active_actual_to_potential_transpiration_ratio',
           'dry_active_duration_s', 'longest_dry_active_spell_s'}
METRIC_UNITS = {'coldest_month_temperature_c':'degC', 'warmest_month_temperature_c':'degC',
    'growing_degree_days':'K * supplied calendar day', 'rooted_depth_m':'m',
    'active_actual_to_potential_transpiration_ratio':'1', 'dry_active_duration_s':'s',
    'longest_dry_active_spell_s':'s'}


def plain(value):
    if isinstance(value,F):return str(value)
    if hasattr(value,'__dataclass_fields__'):return plain(asdict(value))
    if type(value) is dict:return {str(k):plain(v) for k,v in value.items()}
    if type(value) in (tuple,list):return [plain(v) for v in value]
    return value


def text(value, name):
    if type(value) is not str or not value.strip() or len(value)>4096:
        raise ValueError(name+' requires bounded explicit text')
    return value


def number(value, name, *, low=0., high=1e100, positive=False, unknown=False):
    if value is None and unknown:return None
    if type(value) not in (int,float):raise ValueError(name+' requires finite numeric input, not bool')
    try:value=float(value)
    except OverflowError as exc:raise ValueError(name+' exceeds range') from exc
    if not math.isfinite(value) or not low<=value<=high or (positive and value==0):
        raise ValueError(name+' outside explicit supported range')
    return value


def rational(value, name):
    if type(value) not in (int,float,F) or isinstance(value,bool):raise ValueError(name+' requires exact represented quantity')
    try:value=F(value)
    except (ValueError,OverflowError) as exc:raise ValueError(name+' is not finite') from exc
    if value<=0 or max(value.numerator.bit_length(),value.denominator.bit_length())>4096:
        raise ValueError(name+' requires positive bounded quantity')
    return value


def provenance(instance):
    text(instance.evidence,'evidence')
    if type(instance.source_status) is not str or instance.source_status not in STATUSES:raise ValueError('explicit source status required')


@dataclass(frozen=True)
class Calendar:
    calendar_id: str
    month_durations_seconds: tuple
    day_seconds: F
    evidence: str

    def __post_init__(self):
        text(self.calendar_id,'calendar');text(self.evidence,'calendar evidence')
        object.__setattr__(self,'day_seconds',rational(self.day_seconds,'day duration'))
        if type(self.month_durations_seconds) is not tuple or len(self.month_durations_seconds)!=12:
            raise ValueError('this bounded reference requires twelve explicit months')
        durations=tuple(rational(x,'month duration') for x in self.month_durations_seconds)
        if sum(durations,F())!=365*self.day_seconds:raise ValueError('explicit reference cycle must contain exactly365 supplied days')
        if not 1<=self.day_seconds<=10000000:raise ValueError('day duration outside bounded reference')
        object.__setattr__(self,'month_durations_seconds',durations)

    @property
    def cycle_seconds(self):return sum(self.month_durations_seconds,F())


@dataclass(frozen=True)
class Event:
    event_id: str
    month_id: int
    duration_seconds: F
    temperature_c: float | None
    liquid_input_m_s: float | None
    potential_transpiration_m_s: float | None
    active: bool | None
    evidence: str
    source_status: str

    def __post_init__(self):
        text(self.event_id,'event');provenance(self)
        if type(self.month_id) is not int or not 1<=self.month_id<=12:raise ValueError('month ID1..12 required')
        object.__setattr__(self,'duration_seconds',rational(self.duration_seconds,'event duration'))
        object.__setattr__(self,'temperature_c',number(self.temperature_c,'temperature',low=-100,high=100,unknown=True))
        for key in ('liquid_input_m_s','potential_transpiration_m_s'):
            object.__setattr__(self,key,number(getattr(self,key),key,high=1,unknown=True))
        if self.active is not None and type(self.active) is not bool:raise ValueError('explicit active-season phenology or UNKNOWN required')


@dataclass(frozen=True)
class WaterCapacity:
    capacity_m: float | None
    rooted_depth_m: float | None
    support_id: str
    evidence: str
    source_status: str

    def __post_init__(self):
        provenance(self);text(self.support_id,'physical support')
        for key in ('capacity_m','rooted_depth_m'):
            object.__setattr__(self,key,number(getattr(self,key),key,high=1e4,unknown=True))
        if self.capacity_m is not None and self.rooted_depth_m is not None and self.capacity_m>self.rooted_depth_m:
            raise ValueError('available water cannot exceed rooted bulk volume')


@dataclass(frozen=True)
class Limit:
    metric: str
    minimum: float | None
    maximum: float | None
    evidence: str
    source_status: str

    def __post_init__(self):
        provenance(self)
        if type(self.metric) is not str or self.metric not in METRICS:raise ValueError('unsupported metric')
        for key in ('minimum','maximum'):
            object.__setattr__(self,key,number(getattr(self,key),key,low=-1e100,unknown=True))
        if self.minimum is None and self.maximum is None:raise ValueError('at least one explicit bound required; unknown uses source status')
        if self.minimum is not None and self.maximum is not None and self.minimum>self.maximum:raise ValueError('inverted bound')


@dataclass(frozen=True)
class PFTConstraints:
    pft_id: str
    base_temperature_c: float | None
    dry_stress_fraction: float | None
    limits: tuple
    external_requirements: tuple
    evidence: str
    source_status: str

    def __post_init__(self):
        text(self.pft_id,'PFT');provenance(self)
        object.__setattr__(self,'base_temperature_c',number(self.base_temperature_c,'GDD base',low=-100,high=100,unknown=True))
        object.__setattr__(self,'dry_stress_fraction',number(self.dry_stress_fraction,'dry threshold',high=1,unknown=True))
        if type(self.limits) is not tuple or not 1<=len(self.limits)<=len(METRICS) or any(type(v) is not Limit for v in self.limits):
            raise ValueError('explicit nonempty typed constraint set required')
        if len({v.metric for v in self.limits})!=len(self.limits):raise ValueError('duplicate metric constraint')
        if type(self.external_requirements) is not tuple or len(self.external_requirements)>64 or len(set(self.external_requirements))!=len(self.external_requirements):
            raise ValueError('unique bounded external requirement names required')
        for name in self.external_requirements:text(name,'external requirement')


@dataclass(frozen=True)
class Numerics:
    storage_atol_m: float = 1e-11
    flux_atol_m: float = 1e-11
    ratio_atol: float = 1e-9
    duration_atol_s: float = 1e-3
    relative_tolerance: float = 1e-9
    max_cycles: int = 4096

    def __post_init__(self):
        for key in ('storage_atol_m','flux_atol_m','ratio_atol','duration_atol_s','relative_tolerance'):
            object.__setattr__(self,key,number(getattr(self,key),key,positive=True,high=.1 if key=='relative_tolerance' else 1e6))
        if type(self.max_cycles) is not int or not 1<=self.max_cycles<=10000:raise ValueError('bounded periodic work budget required')


def _phi(x):
    if x<1e-4:
        # Integral of (1-exp(-x*u)); avoids cancellation in continuous-input ET.
        psi=x*(.5+x*(-1/6+x*(1/24+x*(-1/120+x/720))))
        return 1-psi,psi
    phi=-math.expm1(-x)/x
    return phi,1-phi


def reservoir_step(capacity_m, initial_m, duration_seconds, liquid_input_m_s,
                   potential_transpiration_m_s, *, numerics=None):
    """Analytic constant-forcing capped reservoir, with independent ET integral."""
    n=Numerics() if numerics is None else numerics
    if type(n) is not Numerics:raise ValueError('typed numerical controls required')
    c=number(capacity_m,'capacity',positive=True,high=1e4)
    s=number(initial_m,'initial water',high=c)
    exact_dt=rational(duration_seconds,'duration')
    try:dt=float(exact_dt)
    except OverflowError as exc:raise ValueError('duration exceeds represented range') from exc
    i=number(liquid_input_m_s,'liquid input',high=1)
    d=number(potential_transpiration_m_s,'potential transpiration',high=1)
    if not math.isfinite(dt):raise ValueError('unrepresentable duration')
    incoming=i*dt; potential=d*dt
    if (i>0 and incoming==0) or (d>0 and potential==0):raise ArithmeticError('positive water transfer underflow')
    if not all(math.isfinite(v) for v in (incoming,potential)):raise ArithmeticError('water transfer overflow')
    hit=None; overflow=0.; actual=0.
    if d==0:
        room=c-s
        if incoming>room:
            hit=room/i; final=c; overflow=incoming-room
        else:final=s+incoming
    else:
        k=d/c; x=k*dt
        if not math.isfinite(x) or x==0:raise ArithmeticError('unrepresentable positive depletion dose')
        if i>d:
            if s==c:hit=0.
            else:
                y=k*(c-s)/(i-d)
                if not math.isfinite(y):raise ArithmeticError('unrepresentable saturation crossing')
                hit=(c-s)/(i-d)*(math.log1p(y)/y if y else 1.)
            if hit>dt:hit=None
        t=dt if hit is None else hit
        dose=k*t
        phi,psi=_phi(dose)
        actual=s*(-math.expm1(-dose))+i*t*psi
        if hit is None:
            final=s if i==k*s else s*math.exp(-dose)+i*t*phi
        else:
            final=c; actual+=d*(dt-hit); overflow=(i-d)*(dt-hit)
        if (s>0 or i>0) and actual==0:raise ArithmeticError('positive actual uptake underflow')
    tolerance=n.flux_atol_m+n.relative_tolerance*max(c,incoming,potential,s)
    if not all(math.isfinite(v) for v in (final,actual,overflow)) or min(final,actual,overflow)<0 or final>c+tolerance or actual>potential+tolerance:
        raise ArithmeticError('reservoir physical bounds failed')
    # Roundoff at the exact capacity branch is diagnosed, never stored above C.
    if final>c:raise ArithmeticError('represented uncapped endpoint exceeds capacity')
    residual=F(s)+F(i)*F(dt)-F(final)-F(actual)-F(overflow)
    if abs(float(residual))>tolerance:raise ArithmeticError('independent water balance exceeds tolerance')
    return {'initial_m':s,'final_m':final,'duration_seconds':dt,'liquid_input_m_s':i,
        'supplied_duration_seconds':str(exact_dt),'duration_conversion_residual_s':str(F(dt)-exact_dt),
        'potential_transpiration_m_s':d,'input_m':incoming,'potential_transpiration_m':potential,
        'actual_transpiration_m':actual,'overflow_m':overflow,'capacity_hit_seconds':hit,
        'numerical_residual_m':str(residual),'capacity_m':c}


advance_reservoir = reservoir_step


def _dry_interval(row, threshold):
    """Exact crossing for monotonic constant-event storage; times relative to event."""
    s=row['initial_m']; end=row['final_m']; c=row['capacity_m']; dt=row['duration_seconds']; target=threshold*c
    if max(s,end)<target:return (0.,dt)
    if min(s,end)>=target:return None
    i=row['liquid_input_m_s']; d=row['potential_transpiration_m_s']
    if d==0:t=(target-s)/i
    else:
        k=d/c; velocity=i-k*s; y=k*(target-s)/velocity
        if not 0<=y<1:raise ArithmeticError('dry-threshold crossing unresolved at represented precision')
        t=(target-s)/velocity*((-math.log1p(-y)/y) if y else 1.)
    if not math.isfinite(t) or not 0<=t<=dt:raise ArithmeticError('dry crossing outside event')
    return (0.,t) if s<target else (t,dt)


def _cycle(c,initial,events,dry_threshold,n):
    s=initial; rows=[]; dry=[]; cursor=0.; demand=[]; actual=[]
    for event in events:
        row=reservoir_step(c,s,event.duration_seconds,event.liquid_input_m_s,event.potential_transpiration_m_s,numerics=n)
        row['event_id']=event.event_id;row['month_id']=event.month_id;row['active']=event.active
        if event.active:
            demand.append(row['potential_transpiration_m']);actual.append(row['actual_transpiration_m'])
            if dry_threshold is not None:
                interval=_dry_interval(row,dry_threshold)
                if interval is not None and interval[1]>interval[0]:dry.append((cursor+interval[0],cursor+interval[1]))
        cursor+=row['duration_seconds'];s=row['final_m'];rows.append(row)
    merged=[]
    for lo,hi in dry:
        if merged and lo==merged[-1][1]:merged[-1]=(merged[-1][0],hi)
        else:merged.append((lo,hi))
    longest=max((hi-lo for lo,hi in merged),default=0.)
    if len(merged)>1 and merged[0][0]==0 and merged[-1][1]==cursor:
        longest=max(longest,merged[0][1]+cursor-merged[-1][0])
    total_demand=math.fsum(demand);total_actual=math.fsum(actual)
    residual=sum((F(row['numerical_residual_m']) for row in rows),F())
    duration_residual=sum((F(row['duration_conversion_residual_s']) for row in rows),F())
    all_input=math.fsum(row['input_m'] for row in rows)
    all_demand=math.fsum(row['potential_transpiration_m'] for row in rows)
    if abs(float(residual))>n.flux_atol_m+n.relative_tolerance*max(c,all_input,all_demand):
        raise ArithmeticError('whole-cycle independent water balance failed')
    if abs(float(duration_residual))>n.duration_atol_s+n.relative_tolerance*cursor:
        raise ArithmeticError('whole-cycle duration representation error failed')
    return {'initial_m':initial,'final_m':s,'events':rows,
        'active_potential_transpiration_m':total_demand,'active_actual_transpiration_m':total_actual,
        'active_actual_to_potential_transpiration_ratio':None if total_demand==0 else total_actual/total_demand,
        'dry_active_duration_s':None if dry_threshold is None else math.fsum(hi-lo for lo,hi in merged),
        'longest_dry_active_spell_s':None if dry_threshold is None else longest,
        'overflow_m':math.fsum(row['overflow_m'] for row in rows),
        'input_m':all_input,'all_potential_transpiration_m':all_demand,
        'all_actual_transpiration_m':math.fsum(row['actual_transpiration_m'] for row in rows),
        'duration_conversion_residual_s':str(duration_residual),'numerical_residual_m':str(residual)}


def _events(calendar,events):
    if type(calendar) is not Calendar or type(events) is not tuple or not 12<=len(events)<=8192 or any(type(e) is not Event for e in events):
        raise ValueError('complete typed calendar/events required')
    if len({e.event_id for e in events})!=len(events):raise ValueError('duplicate event identity')
    if [e.month_id for e in events]!=sorted(e.month_id for e in events):raise ValueError('events must preserve calendar chronology')
    for m,expected in enumerate(calendar.month_durations_seconds,1):
        if sum((e.duration_seconds for e in events if e.month_id==m),F())!=expected:raise ValueError('complete exact month duration required')


def periodic_water(capacity,calendar,events,*,dry_stress_fraction,numerics=None):
    n=Numerics() if numerics is None else numerics
    if type(capacity) is not WaterCapacity or type(n) is not Numerics:raise ValueError('typed capacity/numerics required')
    _events(calendar,events)
    threshold=number(dry_stress_fraction,'dry threshold',high=1,unknown=True)
    if capacity.source_status not in KNOWN or capacity.capacity_m is None or any(e.source_status not in KNOWN or e.liquid_input_m_s is None or e.potential_transpiration_m_s is None or e.active is None for e in events):
        return {'status':'UNKNOWN','reason':'seasonal water/phenology/capacity evidence unresolved','lower':None,'upper':None}
    c=capacity.capacity_m
    if c==0:return {'status':'OUTSIDE_REGIME','reason':'zero available-water capacity requires a different rooting/water regime','lower':None,'upper':None}
    lo=0.;hi=c
    try:
        for cycle in range(1,n.max_cycles+1):
            a=_cycle(c,lo,events,threshold,n);b=_cycle(c,hi,events,threshold,n)
            if a['final_m']>b['final_m']+n.storage_atol_m:raise ArithmeticError('periodic monotone bracket failed')
            if a['final_m']<lo-n.storage_atol_m or b['final_m']>hi+n.storage_atol_m:
                raise ArithmeticError('periodic lower/upper invariant failed')
            close=hi-lo<=n.storage_atol_m+n.relative_tolerance*c
            for key,atol in (('active_actual_to_potential_transpiration_ratio',n.ratio_atol),
                             ('dry_active_duration_s',n.duration_atol_s),('longest_dry_active_spell_s',n.duration_atol_s)):
                if a[key] is not None and b[key] is not None:
                    close &= abs(a[key]-b[key])<=atol+n.relative_tolerance*max(abs(a[key]),abs(b[key]))
            if close:
                return {'status':'MODELLED_PERIODIC_BRACKET','cycles':cycle,'lower':a,'upper':b,
                    'reason':'entire seasonal response bracket, not a climatology inferred from a short event',
                    'capacity_m':c,'numerics':asdict(n),'water_model':'LINEAR_AVAILABLE_STORAGE_STRESS_NOT_RICHARDS_OR_SPLASH_REPLICATION'}
            lo=a['final_m'];hi=b['final_m']
        return {'status':'UNKNOWN','reason':'periodic initial-state/stress bracket has not converged; no preferred initial water','cycles':n.max_cycles,'lower':a,'upper':b}
    except (ArithmeticError,OverflowError) as exc:
        return {'status':'NUMERICAL_FAILURE','reason':str(exc),'lower':None,'upper':None}


def evaluate(capacity,calendar,events,constraints,external_gates,*,numerics=None):
    """Three-valued, evidence-explicit feasibility; no dominance or cover law."""
    if type(capacity) is not WaterCapacity or type(constraints) is not PFTConstraints:raise ValueError('typed PFT/capacity required')
    _events(calendar,events)
    if type(external_gates) is not dict or set(external_gates)-set(constraints.external_requirements):raise ValueError('only named external requirements permitted')
    gates={}
    for name in constraints.external_requirements:
        row=external_gates.get(name,{'status':'UNKNOWN','evidence':'required external support not supplied'})
        if type(row) is not dict or set(row)!={'status','evidence'} or type(row['status']) is not str or row['status'] not in {'PASS','FAIL','UNKNOWN'}:
            raise ValueError('external gate needs exact status/evidence')
        text(row['evidence'],'external gate evidence');gates[name]=dict(row)
    metrics={key:None for key in METRICS};intervals={key:None for key in METRICS}
    if capacity.source_status in KNOWN:metrics['rooted_depth_m']=capacity.rooted_depth_m
    thermal=all(e.source_status in KNOWN and e.temperature_c is not None for e in events)
    if thermal:
        means=[float(sum((F(e.temperature_c)*e.duration_seconds for e in events if e.month_id==m),F())/duration)
               for m,duration in enumerate(calendar.month_durations_seconds,1)]
        metrics['coldest_month_temperature_c']=min(means);metrics['warmest_month_temperature_c']=max(means)
        if constraints.base_temperature_c is not None:
            metrics['growing_degree_days']=math.fsum(max(e.temperature_c-constraints.base_temperature_c,0)*float(e.duration_seconds/calendar.day_seconds) for e in events)
    water=periodic_water(capacity,calendar,events,dry_stress_fraction=constraints.dry_stress_fraction,numerics=numerics)
    for key in ('active_actual_to_potential_transpiration_ratio','dry_active_duration_s','longest_dry_active_spell_s'):
        if water['status']=='MODELLED_PERIODIC_BRACKET':
            a,b=water['lower'][key],water['upper'][key]
            if a is not None and b is not None:
                intervals[key]=[min(a,b),max(a,b)]
                metrics[key]=a+(b-a)/2
    for key,value in metrics.items():
        if value is not None and intervals[key] is None:intervals[key]=[value,value]
    results=[]
    for limit in constraints.limits:
        interval=intervals[limit.metric];status='UNKNOWN';reason='input, periodic state, or trait evidence unresolved'
        if constraints.source_status in KNOWN and limit.source_status in KNOWN and interval is not None:
            low,high=interval
            fail=(limit.minimum is not None and high<limit.minimum) or (limit.maximum is not None and low>limit.maximum)
            passed=(limit.minimum is None or low>=limit.minimum) and (limit.maximum is None or high<=limit.maximum)
            status='FAIL' if fail else 'PASS' if passed else 'UNKNOWN'
            reason='entire computed bracket violates bound' if fail else 'entire computed bracket meets bound' if passed else 'computed uncertainty bracket straddles threshold'
        results.append({**asdict(limit),'status':status,'value':metrics[limit.metric],'interval':intervals[limit.metric],'reason':reason})
    statuses=[row['status'] for row in results]+[row['status'] for row in gates.values()]
    status='FAIL' if 'FAIL' in statuses else 'UNKNOWN' if 'UNKNOWN' in statuses else 'PASS'
    if water['status']=='NUMERICAL_FAILURE':status='NUMERICAL_FAILURE'
    return plain({'schema':'diadem.pft-seasonal-admissibility.r8','pft_id':constraints.pft_id,'status':status,
        'metrics':metrics,'metric_units':dict(METRIC_UNITS),'metric_intervals':intervals,
        'numerical_metric_representation':'midpoint of numerical periodic-initial-state bracket; whole interval used for constraints; not an ecological scenario selection',
        'constraints':results,'external_gates':gates,'water':water,
        'inputs':{'capacity':asdict(capacity),'calendar':asdict(calendar),'events':[asdict(e) for e in events],'constraints':asdict(constraints)},
        'source_status':'WORKING NON-CANON','scope':'potential PFT feasibility under declared seasonal and trait hypotheses; not NPP, observed cover, species occurrence, soil pressure or flood hydroperiod'})
