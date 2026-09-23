"""W02 material cohorts, conservative exchanges and immutable formation history.

Fixed 1D columns, prescribed common velocity, constant-density volume accounts.
H[k,i] is the nonnegative partial thickness of cohort k, in metres. Total H is
DERIVED, never advanced independently or repaired by renormalising fractions.
Formation time belongs to a cohort; age is queried relative to an explicit epoch.
No relative motion between materials, density/energy solver or plate topology.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
import hashlib
import json
import math
from typing import Any, Mapping
import numpy as np
from ._validation import (FloatArray, TectonicsError, input_shape, snapshot,
                          read_array, frozen, scalar)
from .regional import (RegionalGrid1D, TransportBoundary, _reference, _cancelled,
                       unpack_regional_result, _METRICS)
from .resources import select_budget, MemoryLimitError
from .mesh import ColumnGrid1D


_SCHEMA = 'atlas.material-state.v1'
_METHOD = 'cohort-partial-thickness-regional-v2'
# Same local roundoff budget as the regional predecessor, not a tolerance relaxation.
_ROUNDOFF = 128*np.finfo(np.float64).eps


def _name(value, label):
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise TectonicsError(label+' must be nonblank text of at most 256 characters')
    return value


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise TectonicsError('invalid material metadata') from exc


def _immutable_bytes(value):
    """Capture once or reuse compact immutable backing; avoid tobytes-after-freeze."""
    view=frozen(value)
    owner=view
    while type(owner) is np.ndarray:owner=owner.base
    if type(owner) is not bytes or len(owner)!=view.nbytes:
        raise TectonicsError('compact bytes backing required')
    return owner


def _hash_array(a):
    h=hashlib.sha256(_json({'dtype':a.dtype.str, 'shape':list(a.shape)}))
    h.update(memoryview(a).cast('B'))
    return h.hexdigest()


def _sha(value, label):
    if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise TectonicsError(label+' must be a lowercase SHA256 identity')
    return value


def _catalogue(cohorts, time_s):
    if type(cohorts) is not tuple or not cohorts or any(type(c) is not MaterialCohort for c in cohorts):
        raise TectonicsError('nonempty tuple of MaterialCohort records required')
    ids=tuple(c.cohort_id for c in cohorts)
    if ids != tuple(sorted(ids)) or len(set(ids))!=len(ids):
        raise TectonicsError('cohorts must have unique lexically sorted IDs; reorder data explicitly')
    for c in cohorts:
        if c.formation_time_s is not None and c.formation_time_s>time_s:
            raise TectonicsError('cohort formation lies in the future; register it at its event time')
    return ids


@dataclass(frozen=True, slots=True)
class MaterialCohort:
    """A stable origin and formation event, NOT a computational-cell/plate ID.

    None is explicitly unknown formation time, never a hidden zero-age value.
    Different histories use different cohort IDs even for the same material class.
    Times are seconds in the containing state's named epoch, increasing forwards.
    """
    cohort_id: str
    material_id: str
    origin_id: str
    formation_time_s: float | None

    def __post_init__(self):
        for label in ('cohort_id','material_id','origin_id'):
            _name(getattr(self,label),label)
        if self.formation_time_s is not None:
            object.__setattr__(self,'formation_time_s',scalar(self.formation_time_s,'formation time'))


@dataclass(frozen=True, slots=True, init=False)
class MaterialState:
    """Compact immutable C-order C×N partial thickness with one shared catalogue.

    Array properties create private descriptors backed by immutable bytes. Changing
    a caller's shape/dtype cannot mutate this state. Capture forbids concurrent
    caller mutation; publication/restore never relies on ndarray writeable flags.
    Parent/transition identities retain lineage without copying an entire history.
    Owner must account retained payloads outside calls; WorkBudget is not RSS.
    """
    grid: RegionalGrid1D | ColumnGrid1D
    cohorts: tuple[MaterialCohort, ...]
    time_s: float
    epoch_id: str
    parent_state_id: str | None
    transition_id: str | None
    state_id: str
    _payload: bytes = field(repr=False, compare=False)
    _transition_payload: bytes = field(repr=False, compare=False)

    def __init__(self, grid, cohorts, thickness_m, *, time_s, epoch_id,
                 parent_state_id=None, transition_id=None, transition=None, budget=None):
        if type(grid) not in (RegionalGrid1D, ColumnGrid1D):
            raise TectonicsError('explicit RegionalGrid1D or ColumnGrid1D required')
        now=scalar(time_s,'time_s');_name(epoch_id,'epoch_id')
        ids=_catalogue(cohorts,now)
        if (parent_state_id is None)!=(transition_id is None):
            raise TectonicsError('parent and transition identities must be supplied together')
        if parent_state_id is not None:
            _sha(parent_state_id,'parent');_sha(transition_id,'transition')
            if type(transition) is not dict or transition.get('parent')!=parent_state_id:
                raise TectonicsError('transition receipt must name its parent state')
            if hashlib.sha256(_json(transition)).hexdigest()!=transition_id:
                raise TectonicsError('transition receipt identity mismatch')
        elif transition is not None:
            raise TectonicsError('root state cannot attach an unparented transition')
        transition_bytes=_json(transition)
        if len(transition_bytes)>8192*len(ids)+8192:
            raise TectonicsError('transition receipt exceeds metadata bound')
        if input_shape(thickness_m,'cohort thickness')!=(len(ids),grid.cells):
            raise TectonicsError('partial thickness needs shape (cohorts, cells)')
        with select_budget(budget).reserve(_state_work_bytes(len(ids),grid.cells),
                                           category='material-state'):
            values=snapshot(thickness_m,'partial thickness',nonnegative=True)
            owner=values
            while type(owner) is np.ndarray: owner=owner.base
            if type(owner) is not bytes or len(owner)!=values.nbytes:
                raise TectonicsError('material state needs compact immutable byte backing')
            for key,val in (('grid',grid),('cohorts',cohorts),('time_s',now),('epoch_id',epoch_id),
                            ('parent_state_id',parent_state_id),('transition_id',transition_id),('_payload',owner),('_transition_payload',transition_bytes)):
                object.__setattr__(self,key,val)
            h=hashlib.sha256(_json(self.descriptor()))
            h.update(b'\0');h.update(owner)
            object.__setattr__(self,'state_id',h.hexdigest())

    @property
    def thickness_m(self) -> FloatArray:
        return np.frombuffer(self._payload,dtype=np.float64).reshape(len(self.cohorts),self.grid.cells)

    @property
    def nbytes(self):
        return len(self._payload)

    @property
    def transition_record(self):
        """Detached last-transition receipt; not a growing per-cell event log."""
        return json.loads(self._transition_payload)

    def descriptor(self):
        """Detached metadata. Formation/cooling/burial ages are not conflated."""
        return {'schema':(_SCHEMA if type(self.grid) is RegionalGrid1D else 'atlas.material-state.v2'),
                'grid':(asdict(self.grid) if type(self.grid) is RegionalGrid1D else self.grid.descriptor()),
                'cohorts':[asdict(c) for c in self.cohorts], 'time_s':self.time_s,
                'epoch_id':self.epoch_id,'parent_state_id':self.parent_state_id,
                'transition_id':self.transition_id,'transition':self.transition_record,'dtype':np.dtype(np.float64).str,
                'layout':'cohort,cell','quantity':'partial-thickness-m'}

    def ages_s(self):
        return tuple(None if c.formation_time_s is None else scalar(
            self.time_s-c.formation_time_s,'cohort age',nonnegative=True) for c in self.cohorts)

    def total_thickness(self, *, backend='numba', budget=None):
        """Derived compensated total. No permanent duplicate total-H field/cache."""
        _backend(backend)
        with select_budget(budget).reserve(24*self.grid.cells+8192,category='material-total'):
            try:
                if backend=='numba':
                    from ._materials_native import column_totals
                    total=column_totals(self.thickness_m)
                else:
                    h=self.thickness_m
                    total=np.fromiter((math.fsum(h[:,i]) for i in range(self.grid.cells)),
                                      dtype=np.float64,count=self.grid.cells)
                return frozen(total)
            except (ValueError,OverflowError,FloatingPointError) as exc:
                raise TectonicsError('invalid total thickness') from exc

    def fractions(self, *, backend='numba', budget=None):
        """(volume fractions, occupied mask). Values are zero in empty columns.

        Fractions in empty columns are undefined: consumers MUST use the returned
        mask. No NaN, dummy cohort, rescaling of conserved data or fabricated age.
        """
        with select_budget(budget).reserve(3*self.nbytes+32*self.grid.cells+8192,
                                           category='material-fractions'):
            total=self.total_thickness(backend=backend,budget=budget)
            occupied=total>0
            result=np.zeros_like(self.thickness_m)
            np.divide(self.thickness_m,total,out=result,where=occupied)
            return frozen(result),np.frombuffer(occupied.tobytes(),dtype=np.bool_)

    def __reduce__(self):
        if type(self.grid) is ColumnGrid1D:
            return (_restore_mesh_material,(self.descriptor(),self.thickness_m,self.state_id,self.grid.edges_m))
        return (restore_material_state,(self.descriptor(),self.thickness_m,self.state_id))

    def __deepcopy__(self,memo):
        memo[id(self)]=self
        return self


def restore_material_state(descriptor, thickness_m, expected_id, *, budget=None, edges_m=None):
    """Validate a complete stored state; a prior history file is not needed to decode."""
    fields={'schema','grid','cohorts','time_s','epoch_id','parent_state_id','transition_id',
            'dtype','layout','quantity','transition'}
    if (type(descriptor) is not dict or set(descriptor)!=fields or descriptor['schema'] not in (_SCHEMA,'atlas.material-state.v2')
            or descriptor['layout']!='cohort,cell' or descriptor['quantity']!='partial-thickness-m'
            or descriptor['dtype']!=np.dtype(np.float64).str):
        raise TectonicsError('incompatible material-state descriptor')
    try:
        if descriptor['schema']==_SCHEMA:
            if edges_m is not None:raise TectonicsError('legacy fixed-grid state cannot attach mesh edges')
            grid=RegionalGrid1D(**descriptor['grid'])
        else:
            if edges_m is None:raise TectonicsError('mesh edges are a required snapshot dependency')
            grid=ColumnGrid1D(edges_m,frame_id=descriptor['grid']['frame_id'],budget=budget)
            if grid.descriptor()!=descriptor['grid']:raise TectonicsError('mesh descriptor/bytes mismatch')
        result=MaterialState(grid,
            tuple(MaterialCohort(**c) for c in descriptor['cohorts']),thickness_m,
            time_s=descriptor['time_s'],epoch_id=descriptor['epoch_id'],
            parent_state_id=descriptor['parent_state_id'],transition_id=descriptor['transition_id'],transition=descriptor['transition'],budget=budget)
    except (TypeError,KeyError) as exc:
        raise TectonicsError('invalid material-state descriptor') from exc
    if result.state_id!=_sha(expected_id,'expected state'):
        raise TectonicsError('material-state identity mismatch')
    return result


@dataclass(frozen=True, slots=True)
class MaterialBoundary:
    """External partial-thickness map frozen as sorted (cohort ID, thickness) pairs.

    An explicitly supplied map means omitted catalogue cohorts have zero inflow.
    None means NO incoming composition was supplied; inward flow must refuse it.
    Every open boundary names its external source/destination reservoir. Catalogue
    IDs are checked even at outflow so a reversal cannot hide stale metadata.
    """
    mode: str
    exterior: tuple[tuple[str,float], ...] | Mapping[str,float] | None = None
    reservoir_id: str | None = None

    def __post_init__(self):
        if self.mode not in ('open','closed'):raise TectonicsError('open/closed boundary required')
        if self.mode=='closed':
            if self.exterior is not None or self.reservoir_id is not None:
                raise TectonicsError('closed boundary cannot name an external reservoir/composition')
            return
        _name(self.reservoir_id,'reservoir_id')
        if self.exterior is not None:
            pairs=tuple(self.exterior.items()) if isinstance(self.exterior,Mapping) else self.exterior
            if type(pairs) is not tuple:raise TectonicsError('explicit cohort-thickness mapping required')
            try:
                pairs=tuple(sorted((_name(k,'boundary cohort'),scalar(v,'external thickness',nonnegative=True))
                                   for k,v in pairs))
            except (TypeError,ValueError) as exc:
                raise TectonicsError('invalid exterior cohort mapping') from exc
            if len({k for k,_ in pairs})!=len(pairs):raise TectonicsError('duplicate boundary cohort')
            object.__setattr__(self,'exterior',pairs)


def _backend(backend):
    if backend not in ('numba','reference'):raise TectonicsError('backend must be numba/reference; no fallback')


def _definition(state,left,right,scheme,backend):
    if type(state) is not MaterialState:raise TectonicsError('explicit MaterialState required')
    if type(state.grid) is not RegionalGrid1D:
        raise TectonicsError('fixed-grid transport needs RegionalGrid1D; use advect_ale for a column mesh')
    if type(left) is not MaterialBoundary or type(right) is not MaterialBoundary:
        raise TectonicsError('explicit material boundaries required')
    if scheme not in ('muscl','upwind'):raise TectonicsError('scheme must be muscl/upwind; no fallback')
    _backend(backend)


def _exterior(state,u,boundary,is_left):
    ids=tuple(c.cohort_id for c in state.cohorts)
    vals=dict(boundary.exterior or ())
    if not vals.keys()<=set(ids):raise TectonicsError('external cohort not registered in state catalogue')
    face=float(u[0] if is_left else u[-1])
    inward=face>0 if is_left else face<0
    if boundary.mode=='closed' and face!=0:raise TectonicsError('closed boundary requires zero velocity')
    if inward and boundary.exterior is None:raise TectonicsError('inflow requires explicit cohort composition')
    return np.array([vals.get(k,0.0) for k in ids],dtype=np.float64)


def _state_work_bytes(cohorts,cells):
    return 24*cohorts*cells+4096*cohorts+8192


def material_work_bytes(cohorts, cells, *, scheme='muscl'):
    """Outputs/joint RK scratch O(C*N); includes reference and publication work."""
    if type(cohorts) is not int or cohorts<1 or type(cells) is not int or cells<1 or scheme not in ('muscl','upwind'):
        raise TectonicsError('invalid material workspace dimensions')
    field_bytes = 128 if scheme == 'muscl' else 64
    return field_bytes*cohorts*cells+160*cells+8192*cohorts+16384


def _end_time(state,dt):
    """Publish only a clock interval that represents the integrated duration.

    An increasing endpoint alone can label three integrated seconds as four at
    a large epoch. Apply the existing relative roundoff envelope; never change
    the caller's duration or silently rebase its named epoch. Zero steps remain
    explicit no-time transitions.
    """
    end=scalar(state.time_s+dt,'end time')
    if dt>0 and end<=state.time_s:raise TectonicsError('positive interval is unresolvable in this time epoch')
    if dt>0:
        represented=end-state.time_s
        if not math.isfinite(represented) or abs(represented-dt)/dt>_ROUNDOFF:
            raise TectonicsError('represented clock interval differs from integrated duration; use a suitable epoch or interval')
    return end


def _transition_record(state,dt,left,right,scheme,backend,velocity_id):
    _sha(velocity_id,'velocity identity')
    return {'operation':_METHOD,'parent':state.state_id,
        'duration_s':dt,'left':asdict(left),'right':asdict(right),'scheme':scheme,
        'backend':backend,'velocity':velocity_id}


def _positive_total(values, backend='numba'):
    """Accurate nonnegative reduction; reuse the verified native exact accumulator."""
    if backend=='numba':
        from ._transport_native import positive_sum
        return float(positive_sum(values))
    return math.fsum(values)


def _account(before,after,lx,rx,maximum):
    before=scalar(before,'before inventory',nonnegative=True)
    after=scalar(after,'after inventory',nonnegative=True)
    lx=scalar(lx,'left exchange');rx=scalar(rx,'right exchange')
    incoming=math.fsum((max(lx,0.),max(rx,0.)))
    outgoing=math.fsum((max(-lx,0.),max(-rx,0.)))
    residual=math.fsum((after,-before,-lx,-rx))
    tolerance=_ROUNDOFF*max(before,after,incoming,outgoing,np.finfo(float).tiny)
    if not math.isfinite(residual) or abs(residual)>tolerance:
        raise TectonicsError('cohort conservation exceeds regional roundoff budget')
    return (before,after,incoming,outgoing,residual,float(maximum),lx,rx)


@dataclass(frozen=True,slots=True)
class MaterialTransportResult:
    """Immutable candidate plus per-cohort interval-mean flux and eight accounts.

    accounts columns use regional._METRICS; incoming/outgoing are nonnegative.
    Catalogue stays in state, not repeated per cell or per boundary face.
    """
    state: MaterialState
    scheme: str
    backend: str
    _flux: bytes = field(repr=False)
    _accounts: bytes = field(repr=False)

    @property
    def face_flux_m2_s(self):
        return np.frombuffer(self._flux,dtype=np.float64).reshape(len(self.state.cohorts),self.state.grid.cells+1)

    @property
    def accounts(self):
        return np.frombuffer(self._accounts,dtype=np.float64).reshape(len(self.state.cohorts),8)

    @property
    def account_names(self):return _METRICS

    def total_account(self):
        """Domain volume account derived from cohort accounts, with MAX not sum CFL."""
        a=self.accounts
        totals=_account(math.fsum(a[:,0]),math.fsum(a[:,1]),math.fsum(a[:,6]),
                        math.fsum(a[:,7]),float(np.max(a[:,5])))
        return dict(zip(_METRICS,totals))

    @property
    def numerical_method(self):
        # The result container is shared, but ALE must not claim the fixed-grid law.
        operation = (self.state.transition_record or {}).get('operation')
        method = operation if operation in ('ale-cohort-ssprk2-v1',
            'cohort-partial-thickness-regional-v1',_METHOD) else _METHOD
        return method+'-'+self.scheme+'-'+self.backend

    @property
    def nbytes(self):return self.state.nbytes+len(self._flux)+len(self._accounts)

    def __deepcopy__(self,memo):
        memo[id(self)]=self
        return self


def _cohort_slopes_reference(h):
    """Independent whole-field MC candidates, including positive endpoint traces."""
    slopes=np.zeros_like(h)
    n=h.shape[1]
    if n>2:
        dl=h[:,1:-1]-h[:,:-2];dr=h[:,2:]-h[:,1:-1]
        size=np.minimum(np.minimum(2*np.abs(dl),2*np.abs(dr)),np.abs(.5*dl+.5*dr))
        slopes[:,1:-1]=np.where((dl>0)&(dr>0),size,np.where((dl<0)&(dr<0),-size,0.))
    if n>1:
        for k,row in enumerate(h):
            for i in (0,n-1):
                if n==2:
                    value=float(row[1]-row[0])
                else:
                    d1=float(row[1]-row[0] if i==0 else row[-1]-row[-2])
                    d2=float(row[2]-row[1] if i==0 else row[-2]-row[-3])
                    options=(2*d1,1.5*d1-.5*d2,2*d2)
                    value=min(options) if min(options)>0 else max(options) if max(options)<0 else 0.
                slopes[k,i]=math.copysign(min(abs(value),2*float(row[i])),value)
    return slopes


def _cohort_fluxes_reference(h,u,left,right):
    """Scalar total MC trace, partitioned by jointly limited cohort slopes."""
    c,n=h.shape
    total=np.array([math.fsum(h[:,i]) for i in range(n)])
    total_slope=_cohort_slopes_reference(total[None,:])[0]
    slopes=_cohort_slopes_reference(h)
    for i in range(n):
        rate=total_slope[i]/total[i] if total[i] else 0.
        candidate_rate=math.fsum(slopes[:,i])/total[i] if total[i] else 0.
        base=h[:,i]*rate
        delta=slopes[:,i]-h[:,i]*candidate_rate
        theta=1.
        for k in range(c):
            if delta[k]>0:bound=h[k,i]*(2-rate)/delta[k]
            elif delta[k]<0:bound=h[k,i]*(2+rate)/(-delta[k])
            else:continue
            # Inward reconstruction rounding; states/traces still reject negatives.
            bound*=1.-8.*np.finfo(np.float64).eps
            if bound<theta:theta=max(float(bound),0.)
        slopes[:,i]=base+theta*delta
    lower=h-.5*slopes;upper=h+.5*slopes
    if np.any(lower<0) or np.any(upper<0):
        raise TectonicsError('cohort reconstruction outside nonnegative range')
    flux=np.empty((c,n+1))
    flux[:,0]=u[0]*(left if u[0]>0 else lower[:,0])
    flux[:,-1]=u[-1]*(right if u[-1]<0 else upper[:,-1])
    flux[:,1:-1]=u[1:-1]*np.where(u[1:-1]>=0,upper[:,:-1],lower[:,1:])
    if not np.isfinite(flux).all():raise TectonicsError('nonfinite cohort face flux')
    return flux


def _cohort_reference(h,u,ratio,left,right):
    outgoing=np.maximum(u[1:],0)*ratio+np.maximum(-u[:-1],0)*ratio
    if not np.isfinite(outgoing).all() or np.any(outgoing>.5):
        raise TectonicsError('outgoing Courant sum exceeds scheme limit or numerical range')
    flux=_cohort_fluxes_reference(h,u,left,right)
    if ratio==0 or not np.any(u):
        updated=h.copy()
    else:
        stage=h+ratio*flux[:,:-1]-ratio*flux[:,1:]
        if np.any(stage<0) or not np.isfinite(stage).all():raise TectonicsError('invalid MUSCL stage')
        second_flux=_cohort_fluxes_reference(stage,u,left,right)
        second=stage+ratio*second_flux[:,:-1]-ratio*second_flux[:,1:]
        if np.any(second<0) or not np.isfinite(second).all():raise TectonicsError('invalid MUSCL stage')
        updated=h+.5*(second-h)
        flux=flux+.5*(second_flux-flux)
    totals=np.array([(math.fsum(h[k]),math.fsum(updated[k])) for k in range(h.shape[0])])
    return updated,flux,totals,float(outgoing.max())


def advect_materials(state: MaterialState, face_velocity_m_s: Any, duration_s: float, *,
                     left: MaterialBoundary, right: MaterialBoundary, scheme='muscl',
                     backend='numba', budget=None, cancel=None) -> MaterialTransportResult:
    """Advance every cohort with the same prescribed u, conserving its own inventory.

    Accuracy-first default: sum-consistent MC-MUSCL/SSP-RK2 (method v2).
    Cohort traces are jointly nonnegative and sum to the scalar total trace at
    both stages; varying-total cohort fields need not be individually TVD.
    Upwind requires explicit choice;
    executor/cache/timestep admission NEVER changes numerical scheme. Formation
    metadata remains fixed; time advances only in the returned candidate state.
    Existing materials are not independently reclassified or renormalised.
    """
    _cancelled(cancel);_definition(state,left,right,scheme,backend)
    dt=scalar(duration_s,'duration_s',nonnegative=True);end=_end_time(state,dt)
    n=state.grid.cells;c=len(state.cohorts)
    if input_shape(face_velocity_m_s,'face velocity')!=(n+1,):raise TectonicsError('N+1 face velocities required')
    with select_budget(budget).reserve(material_work_bytes(c,n,scheme=scheme)-_state_work_bytes(c,n),category='cohort-transport'):
        u=snapshot(face_velocity_m_s,'face velocities')
        el,er=_exterior(state,u,left,True),_exterior(state,u,right,False)
        ratio=dt/state.grid.spacing_m
        if not math.isfinite(ratio) or (dt>0 and ratio==0):raise TectonicsError('interval/spacing outside numerical range')
        try:
            if backend=='numba':
                from ._materials_native import advance_cohorts
                h,flux,totals,maximum=advance_cohorts(state.thickness_m,u,ratio,el,er,scheme=='muscl')
            elif scheme=='muscl' and c>1:
                with np.errstate(over='raise',invalid='raise',divide='raise'):
                    h,flux,totals,maximum=_cohort_reference(state.thickness_m,u,ratio,el,er)
            else:
                h=np.empty((c,n));flux=np.empty((c,n+1));totals=np.empty((c,2));maximum=0.
                for k in range(c):
                    _cancelled(cancel)
                    with np.errstate(over='raise',invalid='raise',divide='raise'):
                        hh,ff,b,a,maximum=_reference(state.thickness_m[k],u,ratio,el[k],er[k],scheme=='muscl')
                    h[k],flux[k],totals[k]=hh,ff,(b,a)
            accounts=np.empty((c,8))
            for k in range(c):
                accounts[k]=_account(totals[k,0]*state.grid.spacing_m,totals[k,1]*state.grid.spacing_m,
                                     dt*float(flux[k,0]),-dt*float(flux[k,-1]),maximum)
            receipt=_transition_record(state,dt,left,right,scheme,backend,_hash_array(u))
            receipt['cohort_accounts_m2']={c.cohort_id:dict(zip(_METRICS,map(float,accounts[k])))
                                         for k,c in enumerate(state.cohorts)}
            tid=hashlib.sha256(_json(receipt)).hexdigest()
            new=MaterialState(state.grid,state.cohorts,h,time_s=end,epoch_id=state.epoch_id,
                              parent_state_id=state.state_id,transition_id=tid,transition=receipt,budget=budget)
            # Total thickness remains derived from conserved cohort inventories;
            # sum consistency is established in reconstruction, never repaired here.
            result=MaterialTransportResult(new,scheme,backend,_immutable_bytes(flux),_immutable_bytes(accounts))
        except ImportError as exc:raise TectonicsError('Numba required for selected backend; no fallback') from exc
        except MemoryLimitError:raise
        except (ValueError,OverflowError,FloatingPointError) as exc:raise TectonicsError(str(exc)) from exc
        _cancelled(cancel)
        return result


def register_cohorts(state: MaterialState, additions: tuple[MaterialCohort,...], *, budget=None):
    """Explicit zero-inventory registration before possible external inflow/birth.

    No old identity can be relabelled; no material is created by registration.
    Zero rows preserve retired cohorts/history rather than silently pruning them.
    """
    if type(state) is not MaterialState:raise TectonicsError('MaterialState required')
    _catalogue(additions,state.time_s)
    old={c.cohort_id:c for c in state.cohorts}
    for c in additions:
        if c.cohort_id in old and old[c.cohort_id]!=c:raise TectonicsError('cohort identity cannot be reassigned')
        old[c.cohort_id]=c
    cohorts=tuple(old[k] for k in sorted(old))
    if cohorts==state.cohorts:return state
    with select_budget(budget).reserve(material_work_bytes(len(cohorts),state.grid.cells)-_state_work_bytes(len(cohorts),state.grid.cells),category='cohort-register'):
        h=np.zeros((len(cohorts),state.grid.cells));indices={c.cohort_id:k for k,c in enumerate(cohorts)}
        for k,c in enumerate(state.cohorts):h[indices[c.cohort_id]]=state.thickness_m[k]
        receipt={'operation':'register-cohorts-v1','parent':state.state_id,
                 'additions':[asdict(c) for c in additions]}
        tid=hashlib.sha256(_json(receipt)).hexdigest()
        return MaterialState(state.grid,cohorts,h,time_s=state.time_s,epoch_id=state.epoch_id,
                             parent_state_id=state.state_id,transition_id=tid,transition=receipt,budget=budget)


@dataclass(frozen=True,slots=True)
class MaterialEvent:
    """A prescribed instantaneous transfer, NOT a solved production/removal rate.

    Apply only at state.time_s; split transport at event times explicitly. 'birth'
    requires formation_time==event time, 'add' transfers existing material without
    resetting age, 'remove' exports it. parent_state_id prevents double application
    to a successor. Repeating on the same immutable parent yields the same result.
    """
    event_id: str
    parent_state_id: str
    time_s: float
    operation: str
    cohort: MaterialCohort
    reservoir_id: str

    def __post_init__(self):
        _name(self.event_id,'event_id');_sha(self.parent_state_id,'parent state')
        _name(self.reservoir_id,'reservoir_id')
        object.__setattr__(self,'time_s',scalar(self.time_s,'event time'))
        if self.operation not in ('birth','add','remove'):raise TectonicsError('birth/add/remove required')
        if type(self.cohort) is not MaterialCohort:raise TectonicsError('MaterialCohort required')
        if self.operation=='birth' and self.cohort.formation_time_s!=self.time_s:
            raise TectonicsError('birth event requires known formation time equal to event time')


@dataclass(frozen=True,slots=True)
class MaterialEventResult:
    state: MaterialState
    event: MaterialEvent
    transferred_volume_m2: float
    before_volume_m2: float
    after_volume_m2: float
    balance_residual_m2: float
    amount_id: str


def apply_material_event(state: MaterialState, event: MaterialEvent, thickness_m: Any, *,
                         budget=None,cancel=None) -> MaterialEventResult:
    """Accounted local injection/extraction with a named external reservoir.

    No closure of a planetary mantle reservoir is claimed. The supplied transfer
    amount (m) is validated and hashed. Removing too much refuses without clipping;
    density changes, reactions, thermal effects and phase partitioning are absent.
    """
    _cancelled(cancel)
    if type(state) is not MaterialState or type(event) is not MaterialEvent:
        raise TectonicsError('typed material state and event required')
    if event.parent_state_id!=state.state_id or event.time_s!=state.time_s:
        raise TectonicsError('event must match its exact parent and time; split intervals explicitly')
    if input_shape(thickness_m,'transfer thickness')!=(state.grid.cells,):raise TectonicsError('one amount per cell required')
    old={c.cohort_id:c for c in state.cohorts};key=event.cohort.cohort_id
    if key in old and old[key]!=event.cohort:raise TectonicsError('cannot redefine existing cohort history')
    if event.operation=='remove' and key not in old:raise TectonicsError('cannot remove absent cohort')
    old[key]=event.cohort;cohorts=tuple(old[k] for k in sorted(old));_catalogue(cohorts,state.time_s)
    c,n=len(cohorts),state.grid.cells
    with select_budget(budget).reserve(material_work_bytes(c,n)-_state_work_bytes(c,n),category='material-event'):
        amount=snapshot(thickness_m,'transfer',nonnegative=True)
        h=np.zeros((c,n));indices={c.cohort_id:i for i,c in enumerate(cohorts)}
        for k,cohort in enumerate(state.cohorts):h[indices[cohort.cohort_id]]=state.thickness_m[k]
        row=h[indices[key]]
        if event.operation=='remove' and np.any(amount>row):raise TectonicsError('removal exceeds available cohort; no clipping')
        try:
            before=scalar(_column_inventory(row,state.grid),'before volume',nonnegative=True)
            transfer=scalar(_column_inventory(amount,state.grid),'transfer volume',nonnegative=True)
            with np.errstate(over='raise',invalid='raise'):
                if event.operation=='remove':np.subtract(row,amount,out=row)
                else:np.add(row,amount,out=row)
            after=scalar(_column_inventory(row,state.grid),'after volume',nonnegative=True)
            signed=transfer if event.operation!='remove' else -transfer
            residual=_account(before,after,signed,0.,0.)[4]
            amount_id=_hash_array(amount)
            receipt={'operation':'material-transfer-v1','parent':state.state_id,
                     'event':asdict(event),'amount_id':amount_id,'volume_unit':'m2-per-unit-width',
                     'before_m2':before,'after_m2':after,'transfer_m2':transfer,'residual_m2':residual}
            tid=hashlib.sha256(_json(receipt)).hexdigest()
            new=MaterialState(state.grid,cohorts,h,time_s=state.time_s,epoch_id=state.epoch_id,
                              parent_state_id=state.state_id,transition_id=tid,transition=receipt,budget=budget)
        except MemoryLimitError:raise
        except (ValueError,OverflowError,FloatingPointError) as exc:raise TectonicsError(str(exc)) from exc
        _cancelled(cancel)
        return MaterialEventResult(new,event,transfer,before,after,residual,amount_id)


def pack_material_result(result):
    """C rows of [H[N], mean-F[N+1], eight metrics], only for IPC/persistence."""
    n=result.state.grid.cells;c=len(result.state.cohorts)
    out=np.empty((c,2*n+9));out[:,:n]=result.state.thickness_m
    out[:,n:2*n+1]=result.face_flux_m2_s;out[:,2*n+1:]=result.accounts
    return frozen(out)


def unpack_material_result(payload, parent, dt, left, right, scheme, backend, velocity_id, *,budget=None):
    _definition(parent,left,right,scheme,backend)
    n=parent.grid.cells;c=len(parent.cohorts)
    dt=scalar(dt,'duration',nonnegative=True);end=_end_time(parent,dt)
    if input_shape(payload)!=(c,2*n+9):raise TectonicsError('invalid material result layout')
    with select_budget(budget).reserve(material_work_bytes(c,n)-_state_work_bytes(c,n),category='material-restore'):
        raw=read_array(payload,'material result')
        for k in range(c):
            checked=unpack_regional_result(raw[k],n,scheme,backend)
            expected_before=_positive_total(parent.thickness_m[k],backend)*parent.grid.spacing_m
            expected_after=_positive_total(checked.thickness_m,backend)*parent.grid.spacing_m
            if (checked.solid_volume_per_width_before_m2!=expected_before or
                checked.solid_volume_per_width_after_m2!=expected_after or
                checked.left_exchange_m2!=dt*float(checked.face_flux_m2_s[0]) or
                checked.right_exchange_m2!=-dt*float(checked.face_flux_m2_s[-1])):
                raise TectonicsError('restored cohort account disagrees with fields or parent')
            _account(expected_before,expected_after,checked.left_exchange_m2,checked.right_exchange_m2,
                     checked.maximum_outflow_fraction)
        receipt=_transition_record(parent,dt,left,right,scheme,backend,velocity_id)
        receipt['cohort_accounts_m2']={c.cohort_id:dict(zip(_METRICS,map(float,raw[k,2*n+1:])))
                                     for k,c in enumerate(parent.cohorts)}
        tid=hashlib.sha256(_json(receipt)).hexdigest()
        new=MaterialState(parent.grid,parent.cohorts,raw[:,:n],time_s=end,epoch_id=parent.epoch_id,
            parent_state_id=parent.state_id,transition_id=tid,transition=receipt,budget=budget)
        return MaterialTransportResult(new,scheme,backend,_immutable_bytes(raw[:,n:2*n+1]),
                                       _immutable_bytes(raw[:,2*n+1:]))


def save_material_state(state, store, *, budget=None,cancel=None):
    """Lossless self-contained snapshot in the existing deduplicated ArrayStore.

    Identity is that of this supplied state, not proof of physical acceptance.
    Parent IDs express lineage, not decoder dependencies. No generic object pickle.
    """
    from .storage import ArrayStore
    if type(state) is not MaterialState or not isinstance(store,ArrayStore):raise TectonicsError('typed state/store required')
    arrays={'partial_thickness_m':state.thickness_m}
    if type(state.grid) is ColumnGrid1D:arrays['mesh_edges_m']=state.grid.edges_m
    return store.put(state.state_id,arrays,state.descriptor(),budget=budget,cancel=cancel)


def load_material_state(store, state_id, *, budget=None):
    from .storage import ArrayStore
    if not isinstance(store,ArrayStore):raise TectonicsError('ArrayStore required')
    _sha(state_id,'state')
    policy=store._budget if budget is None else select_budget(budget)
    data=store.get(state_id,budget=policy)
    if data is None:return None
    meta=store.metadata(state_id)
    expected={'partial_thickness_m','mesh_edges_m'} if meta.get('schema')=='atlas.material-state.v2' else {'partial_thickness_m'}
    if set(data)!=expected:raise TectonicsError('invalid material snapshot fields')
    return restore_material_state(meta,data['partial_thickness_m'],state_id,budget=policy,
                                  edges_m=data.get('mesh_edges_m'))


def material_native_build_info():
    from . import _materials_native as native
    import numba,llvmlite
    assembly='\n'.join(f.inspect_asm(s) for f in
        (native.advance_cohorts,native.cohort_fluxes,native.column_totals) for s in f.signatures)
    return {'method':_METHOD,'default_scheme':'muscl','default_backend':'numba',
            'numba':numba.__version__,'llvmlite':llvmlite.__version__,'fastmath':False,
            'disk_jit_cache':False,'assembly_sha256':hashlib.sha256(assembly.encode()).hexdigest()}


def validate_material_result(result, parent, duration_s):
    """Validate immutable IPC results against their exact submitted parent.

    Compilers/process transfer do not authenticate scientific correctness. These
    checks restore the same shape, time, inventory and immutability contract, not
    an alternative solver or proof that the selected material model is realistic.
    """
    if type(result) is not MaterialTransportResult or type(result.state) is not MaterialState:
        raise TectonicsError('invalid material worker result')
    state=result.state;n=parent.grid.cells;c=len(parent.cohorts)
    dt=scalar(duration_s,'duration',nonnegative=True)
    if (state.grid!=parent.grid or state.cohorts!=parent.cohorts or state.epoch_id!=parent.epoch_id
            or state.parent_state_id!=parent.state_id or state.time_s!=_end_time(parent,dt)
            or type(result._flux) is not bytes or type(result._accounts) is not bytes
            or len(result._flux)!=8*c*(n+1) or len(result._accounts)!=64*c):
        raise TectonicsError('material worker result disagrees with parent/shape')
    if result.scheme not in ('muscl','upwind'):raise TectonicsError('invalid returned scheme')
    _backend(result.backend)
    receipt=state.transition_record
    if (type(receipt) is not dict or receipt.get('operation')!=_METHOD
            or receipt.get('scheme')!=result.scheme or receipt.get('backend')!=result.backend
            or receipt.get('duration_s')!=dt):
        raise TectonicsError('material result disagrees with its numerical receipt')
    for k in range(c):
        before=_positive_total(parent.thickness_m[k],result.backend)*parent.grid.spacing_m
        after=_positive_total(state.thickness_m[k],result.backend)*parent.grid.spacing_m
        a=result.accounts[k];flux=result.face_flux_m2_s[k]
        if not np.isfinite(flux).all() or a[5]<0 or a[5]>(0.5 if result.scheme=='muscl' else 1.):
            raise TectonicsError('invalid material worker flux/admission')
        expected=_account(before,after,dt*float(flux[0]),-dt*float(flux[-1]),float(a[5]))
        if tuple(a)!=expected:raise TectonicsError('material worker accounts disagree with fields')
    return result


def material_timestep_limit(state, face_velocity_m_s, *, left, right,
                            scheme='muscl', backend='numba', budget=None):
    """The existing velocity-based adviser after validating material inflow.

    Advises a duration only; never shortens an interval, changes the scheme or
    invents incoming composition. All cohorts share this common face velocity.
    """
    from .regional import transport_timestep_limit
    _definition(state,left,right,scheme,backend)
    n=state.grid.cells
    if input_shape(face_velocity_m_s)!=(n+1,):raise TectonicsError('N+1 face velocities required')
    with select_budget(budget).reserve(16*(n+1)+16*len(state.cohorts)+8192,category='material-limit'):
        u=snapshot(face_velocity_m_s,'face velocity')
        a,b=_exterior(state,u,left,True),_exterior(state,u,right,False)
        try:
            lb=TransportBoundary('closed') if left.mode=='closed' else TransportBoundary('open',math.fsum(a),left.reservoir_id)
            rb=TransportBoundary('closed') if right.mode=='closed' else TransportBoundary('open',math.fsum(b),right.reservoir_id)
            return transport_timestep_limit(u,state.grid,left=lb,right=rb,scheme=scheme,backend=backend,budget=budget)
        except (OverflowError,ValueError) as exc:
            if isinstance(exc,MemoryLimitError):raise
            raise TectonicsError(str(exc)) from exc


def _restore_mesh_material(descriptor, values, expected_id, edges):
    return restore_material_state(descriptor,values,expected_id,edges_m=edges)


def _column_inventory(values, grid):
    """Constant-density volume: uniform legacy arithmetic is preserved exactly."""
    if type(grid) is RegionalGrid1D:return _positive_total(values)*grid.spacing_m
    with np.errstate(over='raise',invalid='raise'):
        return _positive_total(values*grid.widths_m)
