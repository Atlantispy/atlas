"""Bounded 1-D mixed-form Richards flow, not a bucket or full catchment model.

Depth x and Darcy flux are positive DOWNWARD; pressure head h is relative to
atmospheric pressure. q=K(1-dh/dx). All physical coefficients are supplied.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
import math
import numpy as np
from scipy.optimize import least_squares

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

    def __post_init__(self):
        for key in tuple(self.__dataclass_fields__)[:-2]:
            object.__setattr__(self, key, _num(getattr(self, key), key))
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


def _step(column, old, dt, forcing, boundary, controls):
    dz = np.array([x.thickness_m for x in column.layers])
    theta_old, _ = _arrays(column, old)
    def residual(head):
        theta, q, sink = _fluxes(column, head, forcing, boundary)
        return (theta-theta_old)*dz-dt*(q[:-1]-q[1:]-sink)
    scale = max(controls.nonlinear_mass_atol_m, dt*max(forcing.surface_input_m_s, forcing.potential_et_m_s,
                                                     max(p.ksat_m_s for p in column.layers)))
    solution = least_squares(lambda h: residual(h)/scale, old,
        bounds=(controls.min_head_m, controls.max_head_m), xtol=1e-13, ftol=1e-13, gtol=1e-13,
        max_nfev=controls.max_nfev, x_scale="jac")
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
    base = {"schema": "diadem.layered-richards.r3", "state": None, "layers": None, "ledger": None,
            "column_sha256": column_digest(column), "source_status": "SYNTHETIC TEST" if all(x.source_status == "SYNTHETIC TEST" for x in (*column.layers, column, forcing, boundary, *((forcing.uptake,) if forcing.uptake is not None else ()))) else "WORKING NON-CANON",
            "model": "1D_MIXED_RICHARDS_VG_MUALEM_BACKWARD_EULER_STEP_DOUBLING",
            "physical_acceptance": False, "pore_pressure_support": "cell centre; not an inferred slip-plane or terrain-cell mean"}
    unknown = (not all(x.known for x in column.layers) or any(x.source_status == "UNKNOWN" for x in (column, forcing, boundary))
               or forcing.surface_input_m_s is None or forcing.potential_et_m_s is None
               or (boundary.kind == "fixed_head" and boundary.head_m is None)
               or (forcing.uptake is not None and forcing.uptake.source_status == "UNKNOWN"))
    if unknown:
        return {**base, "status": "UNKNOWN", "reason": "required hydraulic/forcing/uptake/boundary evidence unresolved"}
    if forcing.duration_seconds == 0:
        return {**base, "status": "NO_ADVANCE", "state": state, "reason": "zero duration does not certify re-equilibrated pressure"}
    head = np.asarray(state.head_m)
    theta0, _ = _arrays(column, head)
    n = len(head)
    dz = np.asarray([x.thickness_m for x in column.layers])
    time, dt, attempts, accepted = 0.0, controls.initial_dt_s, 0, 0
    down, up, ets, cell_residual = np.zeros(n+1), np.zeros(n+1), np.zeros(n), np.zeros(n)
    step_rows = []
    max_error = 0.0
    excess_terms = []
    while time < forcing.duration_seconds:
        attempts += 1
        if attempts > controls.max_steps:
            return {**base, "status": "NUMERICAL_FAILURE", "reason": "adaptive work budget exceeded", "attempts": attempts}
        dt = min(dt, forcing.duration_seconds-time)
        if dt <= 0 or time+dt == time:
            return {**base, "status": "NUMERICAL_FAILURE", "reason": "time interval unrepresentable"}
        full = _step(column, head, dt, forcing, boundary, controls)
        first = _step(column, head, dt/2, forcing, boundary, controls)
        second = None if first is None else _step(column, first["head"], dt/2, forcing, boundary, controls)
        error = math.inf
        if full is not None and first is not None and second is not None:
            herror = np.max(np.abs(second["head"]-full["head"])/(controls.head_atol_m+controls.relative_tolerance*np.maximum(np.abs(second["head"]), np.abs(full["head"]))))
            terror = np.max(np.abs(second["theta"]-full["theta"])/(controls.theta_atol+controls.relative_tolerance*np.maximum(np.abs(second["theta"]), np.abs(full["theta"]))))
            fine_flux = first["q_m"]+second["q_m"]
            ferror = np.max(np.abs(fine_flux-full["q_m"])/(controls.flux_integral_atol_m+controls.relative_tolerance*np.maximum(np.abs(fine_flux), np.abs(full["q_m"]))))
            fine_et = first["et_m"]+second["et_m"]
            eerror = np.max(np.abs(fine_et-full["et_m"])/(controls.flux_integral_atol_m+controls.relative_tolerance*np.maximum(np.abs(fine_et), np.abs(full["et_m"]))))
            error = float(max(herror, terror, ferror, eerror))
        if error > 1:
            if dt/2 < controls.min_dt_s:
                return {**base, "status": "NUMERICAL_FAILURE", "reason": "convergence/truncation gate failed at minimum time step", "attempts": attempts}
            dt /= 2
            continue
        for step in (first, second):
            down += np.maximum(step["q_m"], 0)
            up += np.maximum(-step["q_m"], 0)
            ets += step["et_m"]
            cell_residual += step["residual_m"]
            excess_terms.append(max(0.0, forcing.surface_input_m_s*(dt/2)-max(float(step["q_m"][0]), 0.0)))
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
                         "controls": asdict(controls), "accepted_steps_detail": step_rows},
            "forcing": asdict(forcing), "lower_boundary": asdict(boundary),
            "fluid": {"water_density_kg_m3": rho, "gravity_m_s2": gravity},
            "scope": "matrix vertical flow, root-uptake ET only, zero pond storage; external fixed-head exchange explicitly counted"}


def state_to_json(state):
    return json.dumps({"schema": "diadem.richards-state.r3", **asdict(state)}, sort_keys=True, allow_nan=False)


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
    if set(data) != {"schema", "head_m", "elapsed_seconds", "column_sha256"} or data["schema"] != "diadem.richards-state.r3":
        raise ValueError("unknown checkpoint schema/fields")
    state = State(tuple(data["head_m"]), data["elapsed_seconds"], data["column_sha256"])
    if state.column_sha256 != column_digest(column) or len(state.head_m) != len(column.layers):
        raise ValueError("checkpoint column mismatch")
    return state
