"""Bounded W09 mobile-soil transport (WORKING NON-CANON).

Roering et al. (1999), equation 8 supplies the nonlinear face law. A sparse
backward-Euler Newton solve evolves physical elevations; the same integrated
shared faces feed an implicit, conservative, well-mixed tag transport solve.
This is a first-order finite-volume model, not a frozen-flux evolution or a
landslide/bare-rock law. A soil-exhaustion event returns its valid endpoint;
the caller decides the next interval. No weathering or saturation is invented.

Preparation follows reuse.ExecutionContext and resources.WorkBudget, retaining
one exact result only. External faces are export-only Dirichlet heights. Geometry
must be a supplied one-dimensional finite-volume strip (or periodic chain): areas,
centre distances and physical face widths. The nonlinear denominator uses that
one-dimensional slope; this is not a reconstructed full-vector 2D gradient law.
Branching supports refuse. Arbitrary graph links do not establish a physical mesh.

Primary references inspected, no third-party implementation copied:
https://seismo.berkeley.edu/~kirchner/reprints/1999_29_Roering_nonlinear.pdf
https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.nonlinear_diffusion.Perron_nl_diffuse.html
https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.spsolve.html
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import threading

import numpy as np
from scipy.sparse import bmat, coo_matrix, diags
from scipy.sparse.linalg import spsolve

from ._validation import TectonicsError, frozen, input_shape, scalar, snapshot, text
from .constitutive import _cancel
from .materials import _json
from .resources import WorkBudget, select_budget
from .reuse import ExecutionContext
from .stokes_execution import _native_lease


CAP = 128 * 1024**2
LIMIT = 256
EPS = np.finfo(float).eps


def _hash(record, *arrays):
    h = hashlib.sha256(_json(record))
    for a in arrays:
        h.update(str(a.shape).encode('ascii'))
        h.update(a.tobytes())
    return h.hexdigest()


def _account(initial, remaining, exported, name):
    for k, value in enumerate(initial):
        terms = [float(value), -float(exported[k]),
                 *(-float(x) for x in remaining[:, k])]
        if abs(math.fsum(terms)) > 128*EPS*math.fsum(abs(x) for x in terms):
            raise TectonicsError(name+' account does not close')


@dataclass(frozen=True)
class SoilTag:
    tag_id: str
    density_kg_m3: float
    specific_enthalpy_J_kg: float
    formation_time_s: float
    origin_id: str
    enthalpy_reference: str

    def __post_init__(self):
        for name in ('tag_id', 'origin_id', 'enthalpy_reference'):
            text(getattr(self, name), name)
        for name in ('density_kg_m3', 'specific_enthalpy_J_kg', 'formation_time_s'):
            object.__setattr__(self, name, scalar(getattr(self, name), name,
                positive=name == 'density_kg_m3'))


@dataclass(frozen=True, init=False)
class SoilState:
    """Finite grain stocks; porosity describes explicitly unsaturated voids.

    Heat is signed sensible/reference enthalpy carried by immutable cohorts.
    There is no thermal evolution, pore-water account or deposition-age adapter
    in this increment. The base is immobile; soil motion cannot erode it.
    """
    base_m: np.ndarray
    mass_kg: np.ndarray
    porosity: np.ndarray
    tags: tuple
    exported_mass_kg: np.ndarray
    initial_mass_kg: np.ndarray
    time_s: float
    accepted_intervals: int
    plan_id: str
    execution_id: str
    _record: bytes

    def __init__(self, base_m, mass_kg, porosity, tags, *, exported_mass_kg,
                 initial_mass_kg, time_s, accepted_intervals, plan_id,
                 execution_id, parent_id=None):
        shape = input_shape(mass_kg, 'soil mass')
        tags = tuple(tags)
        if (len(shape) != 2 or not 1 <= shape[0] <= LIMIT or
                not 1 <= shape[1] <= LIMIT or shape[0]*shape[1] > 8192 or
                len(tags) != shape[1] or any(type(t) is not SoilTag for t in tags) or
                len({t.tag_id for t in tags}) != len(tags)):
            raise TectonicsError('bounded cells and unique soil tags required')
        if len({t.enthalpy_reference for t in tags}) != 1:
            raise TectonicsError('common explicit enthalpy reference required')
        arrays = {name: snapshot(value, name, nonnegative=name != 'base_m')
                  for name, value in dict(base_m=base_m, mass_kg=mass_kg,
                    porosity=porosity, exported_mass_kg=exported_mass_kg,
                    initial_mass_kg=initial_mass_kg).items()}
        if (arrays['base_m'].shape != (shape[0],) or
                arrays['porosity'].shape != (shape[0],) or
                arrays['initial_mass_kg'].shape != (shape[1],) or
                arrays['exported_mass_kg'].shape != (shape[1],) or
                np.any(arrays['porosity'] >= 1)):
            raise TectonicsError('invalid soil geometry/account shape or porosity')
        if type(accepted_intervals) is not int or not 0 <= accepted_intervals <= LIMIT:
            raise TectonicsError('cumulative accepted hillslope interval limit')
        record = dict(schema='atlas.w09-soil.v1', tags=[asdict(t) for t in tags],
            time_s=scalar(time_s, 'soil time'), accepted_intervals=accepted_intervals,
            plan_id=text(plan_id, 'plan'), execution_id=text(execution_id, 'execution'),
            parent_id=parent_id)
        if any(t.formation_time_s > record['time_s'] for t in tags):
            raise TectonicsError('soil cohort cannot precede its formation time')
        _account(arrays['initial_mass_kg'], arrays['mass_kg'],
                 arrays['exported_mass_kg'], 'soil mass')
        enthalpy = np.array([t.specific_enthalpy_J_kg for t in tags])
        _account(arrays['initial_mass_kg']*enthalpy, arrays['mass_kg']*enthalpy,
                 arrays['exported_mass_kg']*enthalpy, 'soil enthalpy')
        for name, value in arrays.items():
            object.__setattr__(self, name, value)
        for name in ('time_s', 'accepted_intervals', 'plan_id', 'execution_id'):
            object.__setattr__(self, name, record[name])
        object.__setattr__(self, 'tags', tags)
        object.__setattr__(self, '_record', _json(record))

    @property
    def exported_enthalpy_J(self):
        return frozen(self.exported_mass_kg * [t.specific_enthalpy_J_kg for t in self.tags])

    @property
    def enthalpy_J(self):
        return frozen(self.mass_kg * [t.specific_enthalpy_J_kg for t in self.tags])

    def descriptor(self):
        return json.loads(self._record)

    @property
    def state_id(self):
        return _hash(self.descriptor(), self.base_m, self.mass_kg, self.porosity,
                     self.initial_mass_kg, self.exported_mass_kg)


@dataclass(frozen=True)
class DepletionEvent:
    time_s: float
    cell_ids: tuple


@dataclass(frozen=True)
class HillslopeResult:
    state: SoilState
    face_tag_mass_kg: np.ndarray
    exported_mass_kg: np.ndarray
    exported_enthalpy_J: np.ndarray
    depletion_events: tuple
    requested_end_time_s: float
    status: str


def roering_flux(slope, diffusivity_m2_s, critical_slope, *, mobile=True):
    """Signed downhill bulk flux per contour width, m2/s; no denominator clamp."""
    s = scalar(slope, 'slope')
    d = scalar(diffusivity_m2_s, 'diffusivity', nonnegative=True)
    sc = scalar(critical_slope, 'critical slope', positive=True)
    if type(mobile) is not bool:
        raise TectonicsError('explicit mobile-soil presence required')
    if not mobile:
        return 0.
    if abs(s) >= sc:
        raise TectonicsError('mobile soil at critical slope requires a failure law')
    return scalar(d*s/(1-(s/sc)**2), 'bulk face flux')


class PreparedHillslope:
    """Immutable physical faces and source/runtime identity; one cached result.

    Faces are (a,b), with b=-1 for an export-only fixed-height external face.
    Heights are cell means. Open faces require centre-to-boundary distances;
    internal faces require centre-to-centre distances on a declared 1D strip.
    There are at most two incident physical faces per cell. Close to Sc the Newton
    method uses damping and explicit failure, never a changed transport law.
    """
    _immutable = ('areas_m2', 'faces', 'distances_m', 'widths_m',
                  'boundary_elevations_m', 'diffusivity_m2_s', 'critical_slope',
                  'plan_id', 'execution_id', 'frame_id', 'datum_id', 'source_id')

    def __setattr__(self, name, value):
        if name in self._immutable and hasattr(self, name):
            raise AttributeError('prepare a new hillslope model for changed inputs')
        object.__setattr__(self, name, value)

    def __init__(self, areas_m2, faces, distances_m, widths_m, *,
                 diffusivity_m2_s, critical_slope, frame_id, datum_id, source_id,
                 boundary_elevations_m=None, budget=None):
        self._closed = self._active = False
        self._context = self._guard = None
        self._owner = threading.get_ident()
        self._latest = None
        self._stats = dict(preparations=1, computed_intervals=0, latest_hits=0)
        self._resource = WorkBudget(CAP, parent=select_budget(budget))
        nshape, fshape = input_shape(areas_m2), input_shape(faces)
        if (len(nshape) != 1 or not 1 <= nshape[0] <= LIMIT or len(fshape) != 2 or
                fshape[1] != 2 or not 1 <= fshape[0] <= 2048):
            raise TectonicsError('1..256 cells and 1..2048 physical faces required')
        self._guard = self._resource.reserve(16*1024**2, category='w09-hillslope-retained')
        self._guard.__enter__()
        try:
            self.areas_m2 = snapshot(areas_m2, 'cell areas')
            if np.asarray(faces).dtype.kind not in 'iu':
                raise TectonicsError('integer cell indices required')
            f = snapshot(faces, 'faces')
            if np.any(f != np.floor(f)):
                raise TectonicsError('integer cell indices required')
            n = self.areas_m2.size
            pairs = tuple((int(a), int(b)) for a, b in f)
            if (np.any(self.areas_m2 <= 0) or any(a < 0 or a >= n or b < -1 or
                    b >= n or a == b for a, b in pairs) or
                    len({tuple(sorted((a,b))) for a,b in pairs if b >= 0}) !=
                    sum(b >= 0 for a,b in pairs)):
                raise TectonicsError('positive areas and unique valid internal faces required')
            degree = np.zeros(n,dtype=int)
            for a,b in pairs:
                degree[a] += 1
                if b >= 0:
                    degree[b] += 1
            if np.any(degree > 2):
                raise TectonicsError('one-dimensional strip required; branching/2D slope unsupported')
            self.faces = pairs
            self.distances_m = snapshot(distances_m, 'physical face distances')
            self.widths_m = snapshot(widths_m, 'physical face widths')
            if (self.distances_m.shape != (len(pairs),) or
                    self.widths_m.shape != (len(pairs),) or
                    np.any(self.distances_m <= 0) or np.any(self.widths_m <= 0)):
                raise TectonicsError('positive distance and width per face required')
            if boundary_elevations_m is None:
                if any(b == -1 for a,b in pairs):
                    raise TectonicsError('external face elevations required')
                boundary_elevations_m = np.zeros(len(pairs))
            self.boundary_elevations_m = snapshot(boundary_elevations_m, 'boundary elevations')
            if self.boundary_elevations_m.shape != (len(pairs),):
                raise TectonicsError('one boundary elevation per face required')
            self.diffusivity_m2_s = scalar(diffusivity_m2_s, 'diffusivity', nonnegative=True)
            self.critical_slope = scalar(critical_slope, 'critical slope', positive=True)
            for name, value in dict(frame_id=frame_id, datum_id=datum_id, source_id=source_id).items():
                setattr(self, name, text(value, name))
            self._context = ExecutionContext('scipy')
            self.execution_id = self._context.identity
            self.plan_id = _hash(dict(schema='atlas.w09-hillslope.v1', faces=pairs,
                D=self.diffusivity_m2_s, Sc=self.critical_slope, frame=frame_id,
                datum=datum_id, source=source_id, execution=self.execution_id,
                method='nonlinear-BE-shared-face-implicit-tag-mixing',
                geometry='supplied-one-dimensional-strip-metric',
                boundary='export-only-Dirichlet', max_intervals=LIMIT),
                self.areas_m2, self.distances_m, self.widths_m, self.boundary_elevations_m)
        except BaseException:
            self.close()
            raise

    def _check(self, cancel=None):
        if self._closed or threading.get_ident() != self._owner:
            raise TectonicsError('hillslope model closed or driven from another thread')
        _cancel(cancel)
        self._context.verify()

    @contextmanager
    def _operation(self, cancel=None):
        self._check(cancel)
        if self._active:
            raise TectonicsError('reentrant hillslope operation')
        self._active = True
        try:
            with _native_lease():
                yield
            self._check(cancel)
        finally:
            self._active = False

    def _validate(self, state):
        if (type(state) is not SoilState or state.plan_id != self.plan_id or
                state.execution_id != self.execution_id or
                state.base_m.shape != self.areas_m2.shape):
            raise TectonicsError('soil state plan/source/runtime mismatch')

    def initial_state(self, base_m, mass_kg, tags, *, porosity=0.4, time_s=0.,
                      accepted_intervals=0):
        with self._operation():
            if input_shape(porosity) == ():
                porosity = np.full(len(self.areas_m2), scalar(porosity, 'porosity', nonnegative=True))
            shape = input_shape(mass_kg, 'soil mass')
            if len(shape) != 2 or shape[0] != len(self.areas_m2) or math.prod(shape) > 8192:
                raise TectonicsError('bounded mass array on prepared cells required')
            m = snapshot(mass_kg, 'soil mass', nonnegative=True)
            initial = [math.fsum(float(v) for v in m[:,k]) for k in range(m.shape[1])]
            return SoilState(base_m, m, porosity, tags, exported_mass_kg=np.zeros(m.shape[1]),
                initial_mass_kg=initial, time_s=time_s, accepted_intervals=accepted_intervals,
                plan_id=self.plan_id, execution_id=self.execution_id)

    def heights(self, state):
        self._validate(state)
        rho = np.array([t.density_kg_m3 for t in state.tags])
        return frozen(state.base_m + np.sum(state.mass_kg/rho, axis=1)/
                      (self.areas_m2*(1-state.porosity)))

    def _flux(self, v, state, mobile, *, derivative=False):
        n = len(v)
        inv = 1/(self.areas_m2*(1-state.porosity))
        z = state.base_m + v*inv
        q, row, col, val = np.zeros(len(self.faces)), [], [], []
        net = np.zeros(n)
        for j, (a,b) in enumerate(self.faces):
            other = z[b] if b >= 0 else self.boundary_elevations_m[j]
            s = (z[a]-other)/self.distances_m[j]
            donor = a if s >= 0 else b
            if donor < 0 or not mobile[donor]:
                continue
            q[j] = roering_flux(s, self.diffusivity_m2_s, self.critical_slope)*self.widths_m[j]*(1-state.porosity[donor])
            net[a] += q[j]
            if b >= 0:
                net[b] -= q[j]
            if derivative:
                u = (s/self.critical_slope)**2
                k = (self.diffusivity_m2_s*self.widths_m[j]*(1-state.porosity[donor])*
                     (1+u)/(1-u)**2/self.distances_m[j])
                row.append(a); col.append(a); val.append(k*inv[a])
                if b >= 0:
                    row.extend((a,b,b)); col.extend((b,a,b))
                    val.extend((-k*inv[b],-k*inv[a],k*inv[b]))
        jac = coo_matrix((val,(row,col)), shape=(n,n)).tocsc() if derivative else None
        return q, net, jac

    def face_bulk_flux_m2_s(self, state):
        """Instantaneous diagnostic, signed a->b; no integration implied."""
        with self._operation():
            self._validate(state)
            v = np.sum(state.mass_kg/[t.density_kg_m3 for t in state.tags],axis=1)
            q, _, _ = self._flux(v, state, v > 0)
            out = np.zeros(len(q))
            for j,(a,b) in enumerate(self.faces):
                donor = a if q[j] >= 0 else b
                if donor >= 0:
                    out[j] = q[j]/self.widths_m[j]/(1-state.porosity[donor])
            return frozen(out)

    def _solve(self, v0, state, dt, cancel, *, event=None, guess=None):
        """Newton solve, optionally with time unknown and v[event]=0 exactly."""
        mobile = v0 > 0
        v = v0.copy() if guess is None else guess.copy()
        if event is not None:
            v[event] = 0.
        step = dt
        scale = max(float(np.max(v0)), np.finfo(float).tiny)
        for _ in range(48):
            _cancel(cancel)
            q, net, jac = self._flux(v, state, mobile, derivative=True)
            r = v-v0+step*net
            if np.max(np.abs(r)) <= 4*EPS*scale:
                return v, step, q
            system = diags(np.ones(len(v)), format='csc') + step*jac
            if event is None:
                delta = spsolve(system, -r, use_umfpack=False)
                dtime = 0.
            else:
                constraint = coo_matrix(([1.],([0],[event])),shape=(1,len(v))).tocsc()
                augmented = bmat([[system, coo_matrix(net[:,None])],
                                  [constraint, None]], format='csc')
                update = spsolve(augmented, np.r_[-r, 0.], use_umfpack=False)
                delta, dtime = update[:-1], update[-1]
            if not np.isfinite(delta).all() or not math.isfinite(dtime):
                raise TectonicsError('nonfinite hillslope Newton update')
            norm = np.max(np.abs(r))
            accepted = False
            for k in range(32):
                factor = 2.**-k
                candidate = v+factor*delta
                if event is not None:
                    candidate[event] = 0.
                next_time = step+factor*dtime
                if next_time <= 0:
                    continue
                try:
                    _, next_net, _ = self._flux(candidate,state,mobile)
                except TectonicsError:
                    continue
                residual = candidate-v0+next_time*next_net
                if np.max(np.abs(residual)) < norm or np.max(np.abs(residual)) <= 4*EPS*scale:
                    v,step = candidate,next_time
                    accepted = True
                    break
            if not accepted:
                raise TectonicsError('hillslope Newton damping failed; refine interval')
        raise TectonicsError('hillslope nonlinear iteration bound; refine interval')

    def _interval(self, state, dt, cancel):
        rho = np.array([t.density_kg_m3 for t in state.tags])
        solid = state.mass_kg/rho
        v0 = np.sum(solid,axis=1)
        # The endpoint solve may temporarily extend positive donors below zero
        # solely to locate the first exhaustion. Such candidates are never exposed.
        v, used, q = self._solve(v0,state,dt,cancel)
        depleted = ()
        if np.any(v < 0):
            lo, hi = 0., dt
            high_v = v
            for _ in range(52):
                middle = (lo+hi)/2
                trial, _, _ = self._solve(v0,state,middle,cancel)
                if np.any(trial < 0):
                    hi, high_v = middle, trial
                else:
                    lo = middle
                if hi-lo <= 16*EPS*dt:
                    break
            event = int(np.argmin(high_v))
            v, used, q = self._solve(v0,state,hi,cancel,event=event,guess=high_v)
            if used > dt or used <= 0 or np.any(v < 0):
                raise TectonicsError('unresolved simultaneous depletion; refine interval')
            depleted = tuple(int(i) for i in np.flatnonzero((v0 > 0) & (v == 0)))
        else:
            depleted = tuple(int(i) for i in np.flatnonzero((v0 > 0) & (v == 0)))
        transfer = used*q
        outgoing = np.zeros(len(v))
        rows,cols,vals = [],[],[]
        for j,(a,b) in enumerate(self.faces):
            donor,receiver = (a,b) if transfer[j] >= 0 else (b,a)
            if donor < 0:
                raise TectonicsError('undeclared external soil supply')
            amount = abs(transfer[j])
            outgoing[donor] += amount
            if receiver >= 0 and amount:
                rows.append(receiver); cols.append(donor); vals.append(-amount)
        diag = v+outgoing
        empty = diag == 0
        diag[empty] = 1.
        mixing = diags(diag,format='csc') + coo_matrix((vals,(rows,cols)),shape=(len(v),len(v))).tocsc()
        concentration = spsolve(mixing, solid, use_umfpack=False)
        if concentration.ndim == 1:
            concentration = concentration[:,None]
        if np.any(concentration < 0) or not np.isfinite(concentration).all():
            raise TectonicsError('negative/nonfinite tagged soil concentration')
        mass = (v[:,None]*concentration)*rho
        booked = np.zeros((len(self.faces),len(rho)))
        exported = np.zeros(len(rho))
        for j,(a,b) in enumerate(self.faces):
            donor = a if transfer[j] >= 0 else b
            booked[j] = transfer[j]*concentration[donor]*rho
            if b == -1:
                exported += booked[j]
        # Independent per-cell account of precisely these shared transfers.
        for i in range(len(v)):
            for k in range(len(rho)):
                terms = [float(state.mass_kg[i,k]),-float(mass[i,k])]
                for j,(a,b) in enumerate(self.faces):
                    if i == a: terms.append(-float(booked[j,k]))
                    elif i == b: terms.append(float(booked[j,k]))
                if abs(math.fsum(terms)) > 128*EPS*math.fsum(abs(x) for x in terms):
                    raise TectonicsError('shared-face cell mass account does not close')
        new = SoilState(state.base_m,mass,state.porosity,state.tags,
            exported_mass_kg=state.exported_mass_kg+exported,
            initial_mass_kg=state.initial_mass_kg,time_s=state.time_s+used,
            accepted_intervals=state.accepted_intervals+1,plan_id=self.plan_id,
            execution_id=self.execution_id,parent_id=state.state_id)
        # Newly wetted mobile donors also have to remain within the chosen law.
        self._flux(v,new,v > 0)
        return new,booked,exported,depleted

    def advance(self, state, duration_s, *, partitions=1, cancel=None):
        with self._operation(cancel):
            self._validate(state)
            duration = scalar(duration_s,'duration',nonnegative=True)
            end = scalar(state.time_s+duration,'end time')
            if duration > 0 and end <= state.time_s:
                raise TectonicsError('unrepresentable hillslope interval')
            if type(partitions) is not int or not 1 <= partitions <= LIMIT:
                raise TectonicsError('1..256 interval partitions required')
            if duration and state.accepted_intervals+partitions > LIMIT:
                raise TectonicsError('cumulative accepted hillslope interval limit')
            key = (state.state_id,duration,partitions)
            if self._latest is not None and self._latest[0] == key:
                self._stats['latest_hits'] += 1
                return self._latest[1]
            face = np.zeros((len(self.faces),len(state.tags)))
            exports = np.zeros(len(state.tags))
            current, events = state, []
            with self._resource.reserve(16*1024**2,category='w09-hillslope-candidate'):
                if duration:
                    for part in range(partitions):
                        target = state.time_s+duration*(part+1)/partitions
                        current,booked,out,depleted = self._interval(current,target-current.time_s,cancel)
                        self._stats['computed_intervals'] += 1
                        face += booked; exports += out
                        if depleted:
                            events.append(DepletionEvent(current.time_s,depleted))
                            break
                result = HillslopeResult(current,frozen(face),frozen(exports),
                    frozen(exports*[t.specific_enthalpy_J_kg for t in state.tags]),
                    tuple(events),end,'DEPLETED' if events else 'COMPLETE')
                self._check(cancel)
                self._latest = (key,result)
                return result

    def statistics(self):
        return dict(self._stats, budget=self._resource.statistics())

    def close(self):
        if not self._closed:
            self._closed = True
            self._latest = None
            try:
                if self._context is not None:
                    self._context.close()
            finally:
                if self._guard is not None:
                    self._guard.__exit__(None,None,None)
                    self._guard = None

    def __enter__(self):
        self._check()
        return self

    def __exit__(self,*args):
        self.close()
