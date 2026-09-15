"""R6: analytic-Jacobian mixed Richards flow with explicit precision evidence.

Depth x and Darcy flux are positive DOWNWARD; pressure head h is relative to
atmospheric pressure. q=K(1-dh/dx). All physical coefficients are supplied.
Backward Euler remains available; explicit SDIRK2 uses the same mixed storage
equations and accuracy guards. No silent minimum-step or tolerance changes,
and no removal of thin material cells.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
import math
from types import SimpleNamespace
import numpy as np
from scipy.optimize import least_squares
from work.generator_upgrade_r6 import hydraulic_jacobian as hj

STATUS = {"CANON", "WORKING NON-CANON", "SYNTHETIC TEST", "UNKNOWN"}
MAX_CELLS = 128


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(name + " requires explicit bounded evidence/identity")


def _num(value, name, *, nullable=False):
    if value is None and nullable:
        return None
    if type(value) not in (int, float):
        raise ValueError(name + " requires a finite int/float, not bool or a score")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(name + " is outside finite binary64 range") from exc
    if not math.isfinite(value):
        raise ValueError(name + " requires finite binary64")
    return value


def _provenance(evidence, source_status):
    _text(evidence, "physical evidence")
    if source_status not in STATUS:
        raise ValueError("unsupported source status")


@dataclass(frozen=True)
class HydraulicLayer:
    layer_id: str
    thickness_m: float
    theta_r: float | None
    theta_s: float | None
    alpha_per_m: float | None
    n: float | None
    mualem_l: float | None
    ksat_m_s: float | None
    evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.layer_id, "layer")
        _provenance(self.evidence, self.source_status)
        for key in ("thickness_m", "theta_r", "theta_s", "alpha_per_m", "n", "mualem_l", "ksat_m_s"):
            object.__setattr__(self, key, _num(getattr(self, key), key, nullable=key != "thickness_m"))
        if self.thickness_m <= 0:
            raise ValueError("positive cell thickness required")
        for key in ("theta_r", "theta_s", "mualem_l", "ksat_m_s"):
            value = getattr(self, key)
            if value is not None and value < 0:
                raise ValueError(key + " must be nonnegative in this admitted regime")
        if self.theta_s is not None and not 0 < self.theta_s <= 1:
            raise ValueError("saturated water fraction must be in (0,1]")
        if self.theta_r is not None and self.theta_s is not None and self.theta_r >= self.theta_s:
            raise ValueError("residual water must be less than saturated water content")
        if self.alpha_per_m is not None and self.alpha_per_m <= 0:
            raise ValueError("positive inverse-metre retention alpha required")
        if self.n is not None and self.n <= 1:
            raise ValueError("van Genuchten n must exceed one; m=1-1/n")

    @property
    def known(self):
        return self.source_status != "UNKNOWN" and all(getattr(self, k) is not None for k in ("theta_r", "theta_s", "alpha_per_m", "n", "mualem_l", "ksat_m_s"))


@dataclass(frozen=True)
class Column:
    column_id: str
    layers: tuple[HydraulicLayer, ...]
    root_boundary_index: int
    evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.column_id, "column")
        _provenance(self.evidence, self.source_status)
        if type(self.layers) is not tuple or not 1 <= len(self.layers) <= MAX_CELLS or any(type(x) is not HydraulicLayer for x in self.layers):
            raise ValueError("bounded nonempty top-to-bottom hydraulic cells required")
        if len({x.layer_id for x in self.layers}) != len(self.layers):
            raise ValueError("duplicate hydraulic cell identity")
        if type(self.root_boundary_index) is not int or not 1 <= self.root_boundary_index <= len(self.layers):
            raise ValueError("root lower boundary must coincide with an explicit cell face")
        if not math.isfinite(math.fsum(x.thickness_m for x in self.layers)):
            raise ValueError("column depth overflow")


def column_digest(column):
    return hashlib.sha256(json.dumps(asdict(column), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class State:
    head_m: tuple[float, ...]
    elapsed_seconds: float
    column_sha256: str

    def __post_init__(self):
        if type(self.head_m) is not tuple or not 1 <= len(self.head_m) <= MAX_CELLS:
            raise ValueError("explicit bounded pressure heads required")
        object.__setattr__(self, "head_m", tuple(_num(x, "pressure head") for x in self.head_m))
        object.__setattr__(self, "elapsed_seconds", _num(self.elapsed_seconds, "elapsed time"))
        if self.elapsed_seconds < 0:
            raise ValueError("elapsed time must be nonnegative")
        if type(self.column_sha256) is not str or len(self.column_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.column_sha256):
            raise ValueError("state must bind exact hydraulic geometry and parameters")


def initial_state(column, head_m, *, elapsed_seconds=0.0):
    if type(column) is not Column or len(head_m) != len(column.layers):
        raise ValueError("heads must match the supplied column")
    return State(tuple(head_m), elapsed_seconds, column_digest(column))


@dataclass(frozen=True)
class Boundary:
    kind: str
    head_m: float | None
    evidence: str
    source_status: str

    def __post_init__(self):
        _provenance(self.evidence, self.source_status)
        if self.kind not in {"fixed_head", "free_drainage", "no_flow"}:
            raise ValueError("explicit supported lower boundary required")
        object.__setattr__(self, "head_m", _num(self.head_m, "lower pressure head", nullable=True))
        if self.kind != "fixed_head" and self.head_m is not None:
            raise ValueError("a head is only meaningful for a fixed-head lower boundary")


@dataclass(frozen=True)
class Uptake:
    weights: tuple[float, ...]
    dry_zero_head_m: float
    dry_full_head_m: float
    wet_full_head_m: float
    wet_zero_head_m: float
    evidence: str
    source_status: str

    def __post_init__(self):
        _provenance(self.evidence, self.source_status)
        if type(self.weights) is not tuple or not 1 <= len(self.weights) <= MAX_CELLS:
            raise ValueError("explicit root uptake weights required")
        weights = tuple(_num(x, "uptake fraction") for x in self.weights)
        if any(x < 0 for x in weights) or abs(math.fsum(weights)-1) > 8*math.ulp(1.0):
            raise ValueError("root uptake fractions must sum to one")
        object.__setattr__(self, "weights", weights)
        names = ("dry_zero_head_m", "dry_full_head_m", "wet_full_head_m", "wet_zero_head_m")
        values = tuple(_num(getattr(self, k), k) for k in names)
        for k, v in zip(names, values):
            object.__setattr__(self, k, v)
        if not values[0] < values[1] <= values[2] < values[3] <= 0:
            raise ValueError("require dry-zero < dry-full <= wet-full < wet-zero <= 0")


@dataclass(frozen=True)
class Forcing:
    duration_seconds: float
    surface_input_m_s: float | None
    potential_et_m_s: float | None
    uptake: Uptake | None
    evidence: str
    source_status: str

    def __post_init__(self):
        _provenance(self.evidence, self.source_status)
        for key in ("duration_seconds", "surface_input_m_s", "potential_et_m_s"):
            object.__setattr__(self, key, _num(getattr(self, key), key, nullable=key != "duration_seconds"))
            if getattr(self, key) is not None and getattr(self, key) < 0:
                raise ValueError("time and forcing rates must be nonnegative")
        if self.uptake is not None and type(self.uptake) is not Uptake:
            raise ValueError("explicit Uptake or None required")
        if self.potential_et_m_s is not None and self.potential_et_m_s > 0 and self.uptake is None:
            raise ValueError("positive ET requires an explicit root uptake law; no biological defaults")


@dataclass(frozen=True)
class Controls:
    initial_dt_s: float
    min_dt_s: float
    max_dt_s: float
    theta_atol: float
    head_atol_m: float
    flux_integral_atol_m: float
    relative_tolerance: float
    nonlinear_mass_atol_m: float
    total_mass_atol_m: float
    min_head_m: float
    max_head_m: float
    max_steps: int
    max_nfev: int
    integration_method: str = "BACKWARD_EULER"

    def __post_init__(self):
        for key in ("initial_dt_s", "min_dt_s", "max_dt_s", "theta_atol", "head_atol_m",
                    "flux_integral_atol_m", "relative_tolerance", "nonlinear_mass_atol_m",
                    "total_mass_atol_m", "min_head_m", "max_head_m"):
            object.__setattr__(self, key, _num(getattr(self, key), key))
        if type(self.integration_method) is not str or self.integration_method not in {"BACKWARD_EULER", "SDIRK2"}:
            raise ValueError("explicit supported integration method required")
        for key in ("initial_dt_s", "min_dt_s", "max_dt_s", "theta_atol", "head_atol_m", "flux_integral_atol_m", "relative_tolerance", "nonlinear_mass_atol_m", "total_mass_atol_m"):
            if getattr(self, key) <= 0:
                raise ValueError("positive numerical tolerances/steps required")
        if not self.min_dt_s <= self.initial_dt_s <= self.max_dt_s or self.min_head_m >= 0 or self.max_head_m <= 0:
            raise ValueError("invalid numerical step/head bounds")
        if self.relative_tolerance >= 1:
            raise ValueError("relative error tolerance must be below one")
        for key in ("max_steps", "max_nfev"):
            if type(getattr(self, key)) is not int or not 1 <= getattr(self, key) <= 100000:
                raise ValueError("bounded positive numerical work budget required")


def hydraulic_properties(layer, head_m):
    """VG retention and Mualem conductivity; constants are supplied, not fitted."""
    if type(layer) is not HydraulicLayer or not layer.known:
        raise ValueError("known hydraulic law required")
    h = _num(head_m, "pressure head")
    if h >= 0:
        return layer.theta_s, layer.ksat_m_s
    m = 1-1/layer.n
    # Log form avoids (alpha*abs(h))**n overflow and dry-end cancellation.
    loga = math.log(layer.alpha_per_m) + math.log(-h)
    logterm = float(np.logaddexp(0.0, layer.n*loga))
    logse = -m*logterm
    se = math.exp(logse)
    theta = layer.theta_r + (layer.theta_s-layer.theta_r)*se
    power = math.exp(logse/m)
    bracket = -math.expm1(m*math.log1p(-power)) if power < 1 else 1.0
    conductivity = layer.ksat_m_s * math.exp(layer.mualem_l*logse) * bracket*bracket
    if not all(math.isfinite(v) for v in (theta, conductivity)) or not layer.theta_r <= theta <= layer.theta_s or not 0 <= conductivity <= layer.ksat_m_s*(1+1e-14):
        raise ValueError("unrepresentable hydraulic constitutive law")
    return theta, conductivity


def head_from_theta(layer, theta, *, saturated_head_m=None):
    """Inverse retention. Saturated water content does NOT determine pressure."""
    theta = _num(theta, "water fraction")
    if type(layer) is not HydraulicLayer or not layer.known or not layer.theta_r < theta <= layer.theta_s:
        raise ValueError("water content must be strictly above residual and at/below saturation")
    if theta == layer.theta_s:
        if saturated_head_m is None or _num(saturated_head_m, "explicit saturated head") < 0:
            raise ValueError("saturated stock requires an independently supplied nonnegative pressure head")
        return float(saturated_head_m)
    se = (theta-layer.theta_r)/(layer.theta_s-layer.theta_r)
    m = 1-1/layer.n
    value = -math.expm1(-math.log(se)/m)**(1/layer.n)/layer.alpha_per_m
    if not math.isfinite(value):
        raise ValueError("unrepresentable inverse retention")
    return value


def _arrays(column, head):
    theta, conductivity = zip(*(hydraulic_properties(layer, float(h)) for layer, h in zip(column.layers, head)))
    return np.asarray(theta), np.asarray(conductivity)


def _stress(head, uptake):
    dry0, dry1, wet1, wet0 = (uptake.dry_zero_head_m, uptake.dry_full_head_m, uptake.wet_full_head_m, uptake.wet_zero_head_m)
    return np.minimum(np.clip((head-dry0)/(dry1-dry0), 0, 1), np.clip((wet0-head)/(wet0-wet1), 0, 1))


def _fluxes(column, head, forcing, boundary):
    dz = np.array([x.thickness_m for x in column.layers])
    theta, k = _arrays(column, head)
    q = np.empty(len(head)+1)
    # Zero-pressure surface is a complementarity cap. Negative q is seepage
    # exfiltration; there is no unreported surface pond storage.
    q[0] = min(forcing.surface_input_m_s, k[0]*(1-head[0]/(dz[0]/2)))
    for i in range(1, len(head)):
        distance = (dz[i-1]+dz[i])/2
        conductance = 0 if k[i-1] == 0 or k[i] == 0 else 1/(dz[i-1]/(2*k[i-1])+dz[i]/(2*k[i]))
        q[i] = conductance*(distance-head[i]+head[i-1])
    if boundary.kind == "free_drainage":
        q[-1] = k[-1]
    elif boundary.kind == "no_flow":
        q[-1] = 0.0
    else:
        q[-1] = k[-1]*(1-(boundary.head_m-head[-1])/(dz[-1]/2))
    uptake = np.zeros(len(head)) if forcing.uptake is None else forcing.potential_et_m_s*np.array(forcing.uptake.weights)*_stress(head, forcing.uptake)
    if not np.all(np.isfinite(q)) or not np.all(np.isfinite(uptake)):
        raise ValueError("nonfinite Darcy/uptake flux")
    return theta, q, uptake


def _stage(column, old, dt, forcing, boundary, controls, *, kernel, known_source_m=None, guess=None):
    dz = np.array([x.thickness_m for x in column.layers])
    theta_old, _ = _arrays(column, old)
    if kernel is None:
        kernel = hj.prepare(column, forcing, boundary)
    elif kernel.column is not column or kernel.forcing is not forcing or kernel.boundary is not boundary:
        raise ValueError('prepared hydraulic kernel belongs to different inputs')
    known_source_m = np.zeros(len(old)) if known_source_m is None else known_source_m
    def residual(head):
        theta, q, sink = _fluxes(column, head, forcing, boundary)
        return (theta-theta_old)*dz-dt*(q[:-1]-q[1:]-sink)-known_source_m
    scale = max(controls.nonlinear_mass_atol_m, dt*max(forcing.surface_input_m_s, forcing.potential_et_m_s,
                                                     max(p.ksat_m_s for p in column.layers)))
    # The derivative is of the same mixed finite-volume residual. Avoid finite
    # differences between nearly equal water/flux values in very thin cells.
    # Cache only the most recent evaluation inside this solve: scipy commonly
    # asks for f and J at the same head, and no geometry/forcing state is reused.
    last_head, last_pair = None, None
    def evaluate(head):
        nonlocal last_head, last_pair
        if last_head is None or not np.array_equal(head, last_head):
            r, jac = kernel.residual_and_jacobian(head, theta_old, dt)
            last_pair = (r-known_source_m, jac)
            last_head = head.copy()
        return last_pair
    solution = None
    start = np.asarray(old if guess is None else guess).copy()
    newton_evaluations = 0
    if controls.integration_method == 'SDIRK2':
        # Solving J dh=-F directly avoids minimising squared, very differently
        # scaled layer balances. A bounded correction-norm line search checks
        # pressure progress; actual scalar physical residuals remain authority.
        # This is only a nonlinear strategy, not a different time/soil equation.
        limit = min(40, max(0, controls.max_nfev-1))
        def inspected(value):
            nonlocal newton_evaluations
            newton_evaluations += 1
            jac = evaluate(value)[1]
            physical = residual(value)
            correction = np.linalg.solve(jac, physical)
            ratio = float(np.max(np.abs(correction)/(controls.head_atol_m+controls.relative_tolerance*np.abs(value))))
            return physical, jac, correction, ratio
        try:
            if limit:
                physical, jac, correction, ratio = inspected(start)
                while newton_evaluations < limit:
                    if ratio <= .01 and np.max(np.abs(physical)) <= controls.nonlinear_mass_atol_m:
                        # A tolerated residual is not a reason to keep an
                        # easily removable stiff mode. One representable Newton
                        # polish avoids persistent tiny heads driving appreciable
                        # gross flux when conductance is extremely large.
                        candidate = start-correction
                        if (np.any(candidate != start) and np.all(candidate > controls.min_head_m)
                                and np.all(candidate < controls.max_head_m) and newton_evaluations < limit):
                            trial = inspected(candidate)
                            if trial[3] <= ratio and np.max(np.abs(trial[0])) <= np.max(np.abs(physical)):
                                start = candidate
                                physical, jac, correction, ratio = trial
                        solution = SimpleNamespace(x=start, jac=jac/scale, success=True,
                            nfev=newton_evaluations, status=1, message='bounded analytic Newton pressure and mass gates')
                        break
                    factor = 1.
                    improved = False
                    while newton_evaluations < limit and factor >= 2**-16:
                        candidate = start-factor*correction
                        if np.all(candidate > controls.min_head_m) and np.all(candidate < controls.max_head_m):
                            trial = inspected(candidate)
                            if trial[3] < ratio or (trial[3] <= .01 and np.max(np.abs(trial[0])) <= controls.nonlinear_mass_atol_m):
                                start = candidate
                                physical, jac, correction, ratio = trial
                                improved = True
                                break
                        factor /= 2
                    if not improved:
                        break
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            # The unchanged bounded least-squares strategy remains a fallback;
            # all shared physical/rank/head acceptance gates still apply below.
            pass
    if solution is None:
        solution = least_squares(lambda h: evaluate(h)[0]/scale, start,
            jac=lambda h: evaluate(h)[1]/scale,
            bounds=(controls.min_head_m, controls.max_head_m), xtol=1e-13, ftol=1e-13, gtol=1e-13,
            max_nfev=controls.max_nfev-newton_evaluations, x_scale="jac")
        solution.nfev += newton_evaluations
    head = solution.x
    error = residual(head)
    if not solution.success or not np.all(np.isfinite(head)) or np.max(np.abs(error)) > controls.nonlinear_mass_atol_m:
        return None
    # Fully saturated isolated compartments have no retention capacity and can
    # leave pressure undetermined. A small mass residual is not a pressure solve.
    if np.linalg.matrix_rank(solution.jac) < len(old):
        return None
    # At very short dt, an unbalanced saturated head can have tiny integrated
    # mass error. Require the local Newton head correction to be small as well.
    try:
        correction = np.linalg.solve(solution.jac, error/scale)
    except np.linalg.LinAlgError:
        return None
    if np.max(np.abs(correction)/(controls.head_atol_m+controls.relative_tolerance*np.abs(head))) > .01:
        return None
    theta, q, sink = _fluxes(column, head, forcing, boundary)
    if np.any(head <= controls.min_head_m) or np.any(head >= controls.max_head_m):
        return None
    return {"head": head, "theta": theta, "q_m": dt*q, "et_m": dt*sink, "residual_m": error, "nfev": solution.nfev}


def _step(column, old, dt, forcing, boundary, controls, *, kernel=None):
    """One bounded mixed-form step; all flux quadrature weights are positive.

    Alexander SDIRK2: gamma=1-1/sqrt(2), stiffly accurate second stage.
    The stage-2 known source is an integrated flux, NOT a fabricated water state.
    Signed transfers suffice for local error control; gross ledgers retain each
    stage separately to avoid cancelling opposing flows within one step.
    """
    if kernel is None:
        kernel = hj.prepare(column, forcing, boundary)
    initial_q_m = dt*_fluxes(column, old, forcing, boundary)[1]
    if controls.integration_method == "BACKWARD_EULER":
        result = _stage(column, old, dt, forcing, boundary, controls, kernel=kernel)
        if result is not None:
            result['quadrature'] = [(dt, result['q_m'], result['et_m'])]
            result['initial_q_m'] = initial_q_m
        return result
    gamma = 1-1/math.sqrt(2)
    first = _stage(column, old, gamma*dt, forcing, boundary, controls, kernel=kernel)
    if first is None:
        return None
    weight = (1-gamma)/gamma
    first_q, first_et = weight*first['q_m'], weight*first['et_m']
    known_source = first_q[:-1]-first_q[1:]-first_et
    second = _stage(column, old, gamma*dt, forcing, boundary, controls, kernel=kernel,
                    known_source_m=known_source, guess=first['head'])
    if second is None:
        return None
    q_m, et_m = first_q+second['q_m'], first_et+second['et_m']
    theta_old, _ = _arrays(column, old)
    dz = np.asarray([p.thickness_m for p in column.layers])
    error = (second['theta']-theta_old)*dz-(q_m[:-1]-q_m[1:]-et_m)
    if not np.all(np.isfinite(error)) or np.max(np.abs(error)) > controls.nonlinear_mass_atol_m:
        return None
    return {"head": second['head'], "theta": second['theta'], "q_m": q_m,
            "et_m": et_m, "residual_m": error, "nfev": first['nfev']+second['nfev'],
            "initial_q_m": initial_q_m,
            "quadrature": [((1-gamma)*dt, first_q, first_et),
                           (gamma*dt, second['q_m'], second['et_m'])]}


def _temporal_errors(column, full, first, second, controls):
    """Exact existing step-doubling tests, retaining the worst support per field.

    A finite-volume mass PASS alone does not establish temporal head accuracy.
    Records are strict-JSON compatible, including an unrepresentable ratio.
    """
    def component(a, b, atol, support):
        difference = np.abs(a-b)
        allowance = atol + controls.relative_tolerance*np.maximum(np.abs(a), np.abs(b))
        with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
            ratios = difference/allowance
        index = int(np.argmax(ratios))
        ratio = float(ratios[index])
        row = {"error_ratio": ratio if math.isfinite(ratio) else None,
               "absolute_difference": float(difference[index]) if math.isfinite(float(difference[index])) else None,
               "allowed_difference": float(allowance[index]) if math.isfinite(float(allowance[index])) else None,
               "support_index": index, "support_kind": support}
        if support == "cell":
            row.update(layer_id=column.layers[index].layer_id,
                       thickness_m=column.layers[index].thickness_m)
        return ratio if math.isfinite(ratio) else math.inf, row
    def gross(step):
        return (sum((np.maximum(q, 0) for _, q, _ in step['quadrature']), np.zeros(len(column.layers)+1)),
                sum((np.maximum(-q, 0) for _, q, _ in step['quadrature']), np.zeros(len(column.layers)+1)))
    fd, fu = gross(full)
    ad, au = gross(first)
    bd, bu = gross(second)
    fields = {
        "head_m": (second['head'], full['head'], controls.head_atol_m, 'cell'),
        "theta_m3_m3": (second['theta'], full['theta'], controls.theta_atol, 'cell'),
        "face_flux_integral_m": (first['q_m']+second['q_m'], full['q_m'], controls.flux_integral_atol_m, 'face'),
        "root_uptake_integral_m": (first['et_m']+second['et_m'], full['et_m'], controls.flux_integral_atol_m, 'cell'),
        "gross_downward_m": (ad+bd, fd, controls.flux_integral_atol_m, 'face'),
        "gross_upward_m": (au+bu, fu, controls.flux_integral_atol_m, 'face')}
    # Stiffly stable endpoint convergence does not certify gross transfers.
    # A very fast mode can reverse a stage flow and then disappear before both
    # endpoints, even making full/fine gross sums agree at the wrong limit.
    # Resolve material sign changes, including a brief initial opposite flow.
    # Initial q is diagnostic ONLY and is never added to a physical ledger.
    # This is a conservative event-resolution guard, not a monotonicity theorem.
    reversal = np.zeros(len(column.layers)+1)
    for step, down, up in ((full, fd, fu), (first, ad, au), (second, bd, bu)):
        initial = step['initial_q_m']
        unresolved = np.maximum.reduce((np.minimum(down, up),
            np.minimum(np.maximum(initial, 0), up), np.minimum(np.maximum(-initial, 0), down)))
        allowance = controls.flux_integral_atol_m+controls.relative_tolerance*np.maximum(down, up)
        reversal = np.maximum(reversal, unresolved/allowance)
    computed = {key: component(*values) for key, values in fields.items()}
    index = int(np.argmax(reversal))
    value = float(reversal[index])
    computed['unresolved_flow_reversal'] = (value if math.isfinite(value) else math.inf,
        {'error_ratio': value if math.isfinite(value) else None,
         'support_index': index, 'support_kind': 'face',
         'interpretation': 'opposing initial/stage transfer must be resolved below the declared flux allowance; not a ledger source'})
    worst = max(computed, key=lambda key: computed[key][0])
    return computed[worst][0], {key: value[1] for key, value in computed.items()}, worst


def advance(column, state, forcing, boundary, controls, *, water_density_kg_m3, gravity_m_s2):
    """Advance constant event forcing. Failure returns NULL state, never partial PASS.

    Accepted solution is TWO implicit half steps. A full step supplies independent
    local truncation estimates for heads, theta and signed integrated face fluxes.
    """
    if any(type(v) is not t for v, t in ((column, Column), (state, State), (forcing, Forcing), (boundary, Boundary), (controls, Controls))):
        raise ValueError("typed hydraulic column/state/forcing/boundary/controls required")
    if state.column_sha256 != column_digest(column) or len(state.head_m) != len(column.layers):
        raise ValueError("state belongs to a different hydraulic geometry/parameter binding")
    rho = _num(water_density_kg_m3, "water density")
    gravity = _num(gravity_m_s2, "gravity")
    if rho <= 0 or gravity <= 0:
        raise ValueError("positive fluid density and gravity required")
    if any(not controls.min_head_m < h < controls.max_head_m for h in state.head_m):
        raise ValueError("initial head outside numerical range")
    if forcing.uptake is not None and (len(forcing.uptake.weights) != len(column.layers) or any(w > 0 for w in forcing.uptake.weights[column.root_boundary_index:])):
        raise ValueError("uptake weights must match cells and remain above the root boundary")
    base = {"schema": "diadem.layered-richards.r6", "state": None, "layers": None, "ledger": None,
            "column_sha256": column_digest(column), "source_status": "SYNTHETIC TEST" if all(x.source_status == "SYNTHETIC TEST" for x in (*column.layers, column, forcing, boundary, *((forcing.uptake,) if forcing.uptake is not None else ()))) else "WORKING NON-CANON",
            "model": "1D_MIXED_RICHARDS_VG_MUALEM_"+controls.integration_method+"_STEP_DOUBLING",
            "physical_acceptance": False, "pore_pressure_support": "cell centre; not an inferred slip-plane or terrain-cell mean"}
    unknown = (not all(x.known for x in column.layers) or any(x.source_status == "UNKNOWN" for x in (column, forcing, boundary))
               or forcing.surface_input_m_s is None or forcing.potential_et_m_s is None
               or (boundary.kind == "fixed_head" and boundary.head_m is None)
               or (forcing.uptake is not None and forcing.uptake.source_status == "UNKNOWN"))
    if unknown:
        return {**base, "status": "UNKNOWN", "reason": "required hydraulic/forcing/uptake/boundary evidence unresolved"}
    if forcing.duration_seconds == 0:
        return {**base, "status": "NO_ADVANCE", "state": state, "reason": "zero duration does not certify re-equilibrated pressure"}
    kernel = hj.prepare(column, forcing, boundary)
    head = np.asarray(state.head_m)
    theta0, _ = _arrays(column, head)
    n = len(head)
    dz = np.asarray([x.thickness_m for x in column.layers])
    time, dt, attempts, accepted = 0.0, controls.initial_dt_s, 0, 0
    down, up, ets, cell_residual = np.zeros(n+1), np.zeros(n+1), np.zeros(n), np.zeros(n)
    step_rows = []
    max_error = 0.0
    excess_terms = []
    rejected = {"nonlinear_solution": 0, "temporal_accuracy": 0}
    last_trial = None
    minimum_attempted_dt = None
    while time < forcing.duration_seconds:
        attempts += 1
        if attempts > controls.max_steps:
            return {**base, "status": "NUMERICAL_FAILURE", "reason": "adaptive work budget exceeded", "attempts": attempts,
                    "diagnostics": {"last_trial": last_trial, "rejected_trials": rejected}}
        dt = min(dt, forcing.duration_seconds-time)
        if dt <= 0 or time+dt == time:
            return {**base, "status": "NUMERICAL_FAILURE", "reason": "time interval unrepresentable"}
        full = _step(column, head, dt, forcing, boundary, controls, kernel=kernel)
        first = _step(column, head, dt/2, forcing, boundary, controls, kernel=kernel)
        second = None if first is None else _step(column, first["head"], dt/2, forcing, boundary, controls, kernel=kernel)
        error = math.inf
        components, worst = None, None
        if full is not None and first is not None and second is not None:
            error, components, worst = _temporal_errors(column, full, first, second, controls)
        minimum_attempted_dt = dt if minimum_attempted_dt is None else min(minimum_attempted_dt, dt)
        nonlinear_pass = all(step is not None for step in (full, first, second))
        last_trial = {"column_id": column.column_id, "start_seconds": time,
                      "dt_seconds": dt, "minimum_permitted_dt_seconds": controls.min_dt_s,
                      "minimum_layer_thickness_m": float(np.min(dz)),
                      "nonlinear_solutions_accepted": {"full": full is not None, "first_half": first is not None,
                                                        "second_half": second is not None},
                      "error_components": components, "worst_component": worst,
                      "gate": "temporal_accuracy" if nonlinear_pass else "nonlinear_solution"}
        if error > 1:
            rejected[last_trial['gate']] += 1
            if dt/2 < controls.min_dt_s:
                reason = ("temporal accuracy" if nonlinear_pass else "nonlinear solution") + " gate failed at minimum time step"
                # The retained R3 coupling propagates only reason, not this
                # result dictionary. Keep the material support visible there.
                if nonlinear_pass:
                    component = components[worst]
                    reason += (f" (column {column.column_id}; {worst} at {component['support_kind']} "
                               f"{component['support_index']}; error/allowance={component['error_ratio']}; "
                               f"attempted_dt={dt} s; floor={controls.min_dt_s} s)")
                return {**base, "status": "NUMERICAL_FAILURE", "reason": reason, "attempts": attempts,
                        "diagnostics": {"last_trial": last_trial, "rejected_trials": rejected,
                                        "interpretation": "No partial state accepted; time-step floor and all accuracy guards remain unchanged"}}
            dt /= 2
            continue
        for step in (first, second):
            for weight_dt, stage_q, stage_et in step['quadrature']:
                down += np.maximum(stage_q, 0)
                up += np.maximum(-stage_q, 0)
                ets += stage_et
                excess_terms.append(max(0.0, forcing.surface_input_m_s*weight_dt-max(float(stage_q[0]), 0.0)))
            cell_residual += step["residual_m"]
        head = second["head"]
        time += dt
        accepted += 1
        max_error = max(max_error, error)
        step_rows.append({"end_seconds": time, "dt_seconds": dt, "error_ratio": error})
        if error < .125:
            dt = min(2*dt, controls.max_dt_s)
    theta, _ = _arrays(column, head)
    initial_water = theta0*dz
    final_water = theta*dz
    incoming = forcing.surface_input_m_s*forcing.duration_seconds
    infiltration, exfiltration = float(down[0]), float(up[0])
    excess = math.fsum(excess_terms)
    residual = math.fsum([*initial_water, incoming, float(up[-1]), *(-ets), -float(down[-1]), -excess, -exfiltration, *(-final_water)])
    per_cell = final_water-initial_water-(down[:-1]-up[:-1])+(down[1:]-up[1:])+ets
    if excess < 0 or not math.isfinite(residual) or abs(residual) > controls.total_mass_atol_m or np.max(np.abs(per_cell)) > controls.total_mass_atol_m:
        return {**base, "status": "NUMERICAL_FAILURE", "reason": "final finite-volume water conservation gate failed", "water_residual_m": residual}
    root = column.root_boundary_index
    layers = []
    depth = 0.0
    for i, layer in enumerate(column.layers):
        pressure = rho*gravity*float(head[i])
        if not math.isfinite(pressure):
            raise ValueError("pore pressure overflow")
        layers.append({"layer_id": layer.layer_id, "top_depth_m": depth, "centre_depth_m": depth+layer.thickness_m/2,
                       "bottom_depth_m": depth+layer.thickness_m, "head_m": float(head[i]), "theta_m3_m3": float(theta[i]),
                       "effective_saturation": float((theta[i]-layer.theta_r)/(layer.theta_s-layer.theta_r)),
                       "pore_saturation": float(theta[i]/layer.theta_s), "water_m3_m2": float(final_water[i]),
                       "water_m3_m2_exact_represented": str(Fraction(float(theta[i]))*Fraction(layer.thickness_m)),
                       "signed_pore_pressure_pa": pressure, "positive_pore_pressure_pa": max(0.0, pressure),
                       "et_m": float(ets[i]), "water_residual_m": float(per_cell[i])})
        depth += layer.thickness_m
    following = State(tuple(float(h) for h in head), state.elapsed_seconds+forcing.duration_seconds, column_digest(column))
    return {**base, "status": "MODELLED", "state": following, "layers": layers,
            "ledger": {"initial_storage_m": float(math.fsum(initial_water)), "final_storage_m": float(math.fsum(final_water)),
                       "surface_input_m": incoming, "infiltration_m": infiltration, "rain_excess_runoff_m": excess,
                       "surface_exfiltration_m": exfiltration, "surface_runoff_m": excess+exfiltration,
                       "actual_et_m": float(math.fsum(ets)), "potential_et_m": forcing.potential_et_m_s*forcing.duration_seconds,
                       "bottom_downward_m": float(down[-1]), "bottom_upward_m": float(up[-1]),
                       "root_zone_gross_downward_m": float(down[root]), "root_zone_upward_capillary_m": float(up[root]),
                       "face_downward_m": down.tolist(), "face_upward_m": up.tolist(), "water_residual_m": residual},
            "numerics": {"accepted_steps": accepted, "attempts": attempts, "maximum_error_ratio": max_error,
                         "rejected_trials": rejected, "minimum_attempted_dt_seconds": minimum_attempted_dt,
                         "controls": asdict(controls), "accepted_steps_detail": step_rows},
            "forcing": asdict(forcing), "lower_boundary": asdict(boundary),
            "fluid": {"water_density_kg_m3": rho, "gravity_m_s2": gravity},
            "scope": "matrix vertical flow, root-uptake ET only, zero pond storage; external fixed-head exchange explicitly counted"}


def state_to_json(state):
    return json.dumps({"schema": "diadem.richards-state.r6", **asdict(state)}, sort_keys=True, allow_nan=False)


def state_from_json(raw, column):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate checkpoint key")
            value[key] = item
        return value
    def invalid(value):
        raise ValueError("nonfinite checkpoint")
    data = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    if set(data) != {"schema", "head_m", "elapsed_seconds", "column_sha256"} or data["schema"] != "diadem.richards-state.r6":
        raise ValueError("unknown checkpoint schema/fields")
    state = State(tuple(data["head_m"]), data["elapsed_seconds"], data["column_sha256"])
    if state.column_sha256 != column_digest(column) or len(state.head_m) != len(column.layers):
        raise ValueError("checkpoint column mismatch")
    return state
