"""I02.2a package owner of the I01 layered-column conduction and heat deposition. WORKING NON-CANON.

One control volume per mechanical Gauss point with series interface resistance and a discrete steady reference;
exact modal (ETD2) conduction; the column kernel's own Arrhenius terms rebuilt at a new temperature; and the reviewed
stress solve returning creep plus plastic heat deposited once per control volume. Moved without change from
tools/check_i01_column_heat.py, which re-exports these same objects and keeps its supplied-rate evolution,
analytical oracles, case loading and campaign.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np
from scipy.linalg import eigh, solve_banded

from . import _integration_column as column
from . import _integration_weakening as weakening

R = column.R
TOL = weakening.TOL
UNIT_ROUNDOFF = np.finfo(float).eps/2
number, positive = weakening.number, weakening.positive
THERMAL_KEYS = {"name", "conductivity_w_m_k", "heat_capacity_j_kg_k", "radiogenic_w_m3"}
BOUNDARY_TYPES = ("temperature", "insulated")


def phi_functions(z):
    """e^z and phi_1..3(z) = sum_j z^j/(j+k)!, series for |z| < 1 (no cancellation)."""
    z = np.asarray(z, dtype=float)
    out = [np.exp(z)]+[np.empty_like(z) for _ in range(3)]
    small = np.abs(z) < 1.
    zs, zl = z[small], z[~small]
    for k in (1, 2, 3):
        acc = np.zeros_like(zs)
        for j in reversed(range(24)):
            acc = acc*zs+1./math.factorial(j+k)
        out[k][small] = acc
    em1 = np.expm1(zl)
    out[1][~small] = em1/zl
    out[2][~small] = (em1-zl)/zl**2
    out[3][~small] = (em1-zl-zl*zl/2)/zl**3
    return out


# ----------------------------------------------------------------------------- thermal support

@dataclass(frozen=True, eq=False)
class ThermalColumn:
    """Prepared conduction support; valid only for its fingerprinted geometry/properties/boundaries."""
    fingerprint: str
    mechanical_fingerprint: str | None
    layer: np.ndarray
    depth_m: np.ndarray
    volume_m: np.ndarray            # control-volume widths = Gauss weights
    reference_density_kg_m3: np.ndarray  # actual thermal inventory density, not a caller's identity label
    lower_face_m: np.ndarray
    upper_face_m: np.ndarray
    capacity: np.ndarray            # J m^-2 K^-1
    conductance: np.ndarray         # W m^-2 K^-1 between neighbouring points
    boundary_conductance: tuple     # (surface, base); zero when insulated
    boundary_temperature: tuple     # K, or None when insulated
    radiogenic: np.ndarray          # W m^-2 per control volume
    steady_k: np.ndarray            # discrete steady reference temperature
    thickness_m: float
    _prepared_sha256: str = dataclasses.field(default="", repr=False)

    @property
    def size(self):
        return int(self.volume_m.size)

    def operator(self):
        n, g = self.size, self.conductance
        k = np.zeros((n, n))
        idx = np.arange(n-1)
        k[idx, idx] += g
        k[idx+1, idx+1] += g
        k[idx, idx+1] -= g
        k[idx+1, idx] -= g
        k[0, 0] += self.boundary_conductance[0]
        k[-1, -1] += self.boundary_conductance[1]
        return k

    def upward_flows(self, temperature):
        """Upward heat flow (W/m^2) at the surface, every internal face and the base."""
        t = np.asarray(temperature, float)
        top, bottom = self.boundary_temperature
        surface = self.boundary_conductance[0]*(t[0]-top) if top is not None else 0.
        base = self.boundary_conductance[1]*(bottom-t[-1]) if bottom is not None else 0.
        return surface, self.conductance*(t[1:]-t[:-1]), base


def thermal_identity(thermal):
    """Bind the prepared values as well as the input identity; no solve or numerical recomputation."""
    digest = hashlib.sha256(json.dumps(
        [thermal.fingerprint, thermal.mechanical_fingerprint, thermal.boundary_conductance,
         thermal.boundary_temperature, thermal.thickness_m], allow_nan=False).encode())
    for name in ("layer", "depth_m", "volume_m", "reference_density_kg_m3", "lower_face_m", "upper_face_m",
                 "capacity", "conductance", "radiogenic", "steady_k"):
        values = np.asarray(getattr(thermal, name))
        digest.update(json.dumps([name, values.dtype.str, values.shape]).encode())
        digest.update(values.tobytes())
    return digest.hexdigest()


def valid_thermal(thermal):
    """Reject unprepared or replaced derived state instead of trusting a copied fingerprint."""
    if type(thermal) is not ThermalColumn:
        return False
    try:
        return thermal._prepared_sha256 == thermal_identity(thermal)
    except (TypeError, ValueError, AttributeError):
        return False


def scalar(value, name, **kw):
    """A plain real number: profiles/functions (e.g. temperature-dependent conductivity) are refused."""
    if type(value) not in (int, float):
        raise ValueError(name+" must be one constant real value")
    return number(value, name, **kw)


def validate_thermal_layers(props, names):
    if type(props) is not list or len(props) != len(names):
        raise ValueError("one thermal property set per mechanical layer")
    for p, name in zip(props, names):
        if type(p) is not dict or set(p) != THERMAL_KEYS or p["name"] != name:
            raise ValueError("thermal layers declare only conductivity, heat capacity and radiogenic heat, by layer name")
        scalar(p["conductivity_w_m_k"], "conductivity", positive=True)
        scalar(p["heat_capacity_j_kg_k"], "heat capacity", positive=True)
        scalar(p["radiogenic_w_m3"], "radiogenic heat", nonnegative=True)
    return props


def validate_boundaries(boundaries):
    if type(boundaries) is not dict or set(boundaries) != {"top", "bottom"}:
        raise ValueError("top and bottom thermal boundaries required")
    out = []
    for side in ("top", "bottom"):
        b = boundaries[side]
        if type(b) is not dict or b.get("type") not in BOUNDARY_TYPES:
            raise ValueError("thermal boundary must be a fixed temperature or insulated")
        if b["type"] == "temperature":
            if set(b) != {"type", "value_k"}:
                raise ValueError("fixed-temperature boundary declares only its value")
            out.append(scalar(b["value_k"], "boundary temperature", positive=True))
        else:
            if set(b) != {"type"}:
                raise ValueError("insulated boundary takes no value; supplied heat flux is not admitted")
            out.append(None)
    return tuple(out)


def width_tolerance(n):
    """Relative round-off bound on |fsum(w) - h| for one layer's n Gauss widths w_i = fl(W_i h)/2.

    NumPy's leggauss rescales its weights W by 2/fl(sum W), so their exact sum is 2 within (n+1)u
    (the float sum, one division, one product each). Scaling to the layer rounds each width once and
    fsum rounds the total once: (n+3)u, with u = eps/2. The factor 8 is margin for second-order terms.
    """
    return 8*(n+3)*UNIT_ROUNDOFF


def validate_support(layer, depth, weight, thicknesses):
    """Refuse a malformed or materially wrong support before assembly; it is never repaired at a face.

    Returns integer layer IDs, float depths and widths, and the declared layer tops.
    """
    if type(thicknesses) not in (list, tuple) or not thicknesses:
        raise ValueError("declared layer thicknesses required")
    h = [positive(t, "thickness") for t in thicknesses]
    layer, depth, weight = (np.asarray(a) for a in (layer, depth, weight))
    if layer.ndim != 1 or layer.size == 0 or depth.shape != layer.shape or weight.shape != layer.shape:
        raise ValueError("support needs nonempty one-dimensional layer, depth and width arrays of one length")
    if layer.dtype.kind not in "iu" or depth.dtype.kind not in "fiu" or weight.dtype.kind not in "fiu":
        raise ValueError("support layer IDs must be integers, depths and widths real")
    depth, weight = depth.astype(float), weight.astype(float)
    if not (np.all(np.isfinite(depth)) and np.all(np.isfinite(weight))):
        raise ValueError("support depths and widths must be finite")
    step = np.diff(layer)
    if layer[0] != 0 or layer[-1] != len(h)-1 or np.any((step != 0) & (step != 1)):
        raise ValueError("layer IDs must run 0, 1, ... in order with every declared layer present")
    if np.any(np.diff(depth) <= 0) or np.any(weight <= 0):
        raise ValueError("support depths must strictly increase and widths must be positive")
    for li, t in enumerate(h):
        w = weight[layer == li]
        if abs(math.fsum(w)-t) > width_tolerance(w.size)*t:
            raise ValueError("control-volume widths of layer %d do not sum to its declared thickness" % li)
    return layer, depth, weight, np.concatenate([[0.], np.cumsum(h)])


def prepare_thermal(layer, depth, weight, thicknesses, props, densities, boundaries, *,
                    reference_temperature=None, mechanical_fingerprint=None):
    """Control volumes of the mechanical quadrature, series interface resistance, steady reference."""
    if (type(thicknesses) not in (list, tuple) or type(props) is not list
            or not len(props) == len(thicknesses) == len(densities)):
        raise ValueError("thermal properties must match the layers")
    n_layers = len(thicknesses)
    validate_thermal_layers(props, [p.get("name") if type(p) is dict else None for p in props])
    layer, depth, weight, tops = validate_support(layer, depth, weight, thicknesses)
    bc = validate_boundaries(boundaries)
    lower, upper = np.empty(weight.size), np.empty(weight.size)
    for li in range(n_layers):
        m = np.flatnonzero(layer == li)
        edges = tops[li]+np.concatenate([[0.], np.cumsum(weight[m])])
        edges[0], edges[-1] = tops[li], tops[li+1]           # validated above: the last face moves by round-off only
        lower[m], upper[m] = edges[:-1], edges[1:]
    if not (np.all(lower < depth) and np.all(depth < upper)):
        raise ValueError("a quadrature point lies outside its control volume")
    k = np.array([positive(props[i]["conductivity_w_m_k"], "conductivity") for i in layer])
    density = np.array([positive(densities[i], "density") for i in layer])
    rho_cp = np.array([positive(densities[i], "density")*positive(props[i]["heat_capacity_j_kg_k"], "heat capacity")
                       for i in layer])
    heat = np.array([number(props[i]["radiogenic_w_m3"], "radiogenic heat", nonnegative=True) for i in layer])
    face = upper[:-1]
    conductance = 1./((face-depth[:-1])/k[:-1]+(depth[1:]-face)/k[1:])
    g_top = k[0]/depth[0] if bc[0] is not None else 0.
    g_bot = k[-1]/(tops[-1]-depth[-1]) if bc[1] is not None else 0.
    radiogenic = weight*heat
    n = weight.size
    if bc[0] is None and bc[1] is None:
        if np.any(radiogenic > 0) or reference_temperature is None:
            raise ValueError("an insulated column has a steady reference only without radiogenic heat")
        steady = np.full(n, positive(reference_temperature, "reference temperature"))
    else:
        if reference_temperature is not None:
            raise ValueError("the steady reference is fixed by the boundary temperatures")
        band = np.zeros((3, n))
        band[0, 1:] = -conductance
        band[2, :-1] = -conductance
        band[1] = np.concatenate([conductance, [0.]])+np.concatenate([[0.], conductance])
        band[1, 0] += g_top
        band[1, -1] += g_bot
        rhs = radiogenic.copy()
        rhs[0] += g_top*(bc[0] or 0.)
        rhs[-1] += g_bot*(bc[1] or 0.)
        steady = solve_banded((1, 1), band, rhs)
    if not np.all(np.isfinite(steady) & (steady > 0)):
        raise ValueError("steady reference temperature not physical")
    text = json.dumps(dict(props=props, densities=list(map(float, densities)), boundaries=boundaries,
                           thicknesses=list(map(float, thicknesses)), reference=reference_temperature), sort_keys=True)
    support = layer.astype(np.int64).tobytes()+depth.tobytes()+weight.tobytes()     # layer ownership included
    digest = hashlib.sha256(text.encode()+support).hexdigest()
    frozen = weakening.frozen
    prepared = ThermalColumn(
        fingerprint=digest, mechanical_fingerprint=mechanical_fingerprint, layer=frozen(layer, int),
        depth_m=frozen(depth), volume_m=frozen(weight), reference_density_kg_m3=frozen(density),
        lower_face_m=frozen(lower), upper_face_m=frozen(upper),
        capacity=frozen(rho_cp*weight), conductance=frozen(conductance), boundary_conductance=(g_top, g_bot),
        boundary_temperature=bc, radiogenic=frozen(radiogenic), steady_k=frozen(steady), thickness_m=float(tops[-1]))
    return dataclasses.replace(prepared, _prepared_sha256=thermal_identity(prepared))


@dataclass(frozen=True, eq=False)
class Propagator:
    """Exact modal conduction over one fixed step; prepared once while support and step are unchanged."""
    fingerprint: str
    dt: float
    lam: np.ndarray
    to_modal: np.ndarray            # Q^T C^{1/2}
    source_modal: np.ndarray        # Q^T C^{-1/2}
    from_modal: np.ndarray          # C^{-1/2} Q
    e: np.ndarray
    p1: np.ndarray
    p2: np.ndarray
    p3: np.ndarray


def prepare_propagator(thermal, dt):
    if not valid_thermal(thermal):
        raise ValueError("thermal preparation content differs from its prepared identity")
    dt = positive(dt, "time step")
    s = 1./np.sqrt(thermal.capacity)
    lam, q = eigh(s[:, None]*thermal.operator()*s[None, :])
    if lam.min() < -1e-12*max(lam.max(), 1e-300):
        raise RuntimeError("conduction operator is not positive semidefinite")
    lam = np.maximum(lam, 0.)
    e, p1, p2, p3 = phi_functions(-lam*dt)
    frozen = weakening.frozen
    return Propagator(fingerprint=thermal.fingerprint, dt=dt, lam=frozen(lam),
                      to_modal=frozen(q.T*np.sqrt(thermal.capacity)[None, :]),
                      source_modal=frozen(q.T*s[None, :]), from_modal=frozen(s[:, None]*q),
                      e=frozen(e), p1=frozen(p1), p2=frozen(p2), p3=frozen(p3))


def conduct(prop, theta, source_n, source_a=None):
    """ETD2 for C dtheta/dt = -K theta + sigma(t), sigma linear between the two stages.

    Returns (theta_new, integral of theta over the step). With source_a omitted this is
    the predictor with a constant source. Departures from the steady reference only.
    """
    h = prop.dt
    v = prop.to_modal@theta
    g_n = prop.source_modal@source_n
    delta = 0. if source_a is None else prop.source_modal@source_a-g_n
    v_new = prop.e*v+h*prop.p1*g_n+h*prop.p2*delta
    integral = h*prop.p1*v+h*h*prop.p2*g_n+h*h*prop.p3*delta
    return prop.from_modal@v_new, prop.from_modal@integral


# ----------------------------------------------------------------------------- mechanics at temperature

@dataclass(frozen=True, eq=False)
class ArrheniusUpdate:
    """Temperature-dependent creep terms of a reviewed preparation, recomputed for every new state.

    log_c = [log A - m log d] - (E + P V)/(R T) and V/(R T): the kernel's own expression and
    operation order, so a reprepared column is bitwise equal to the kernel at the same inputs.
    """
    base: weakening.PreparedColumn
    constant: np.ndarray
    numerator: np.ndarray
    volume: np.ndarray

    @classmethod
    def of(cls, base):
        if type(base) is not weakening.PreparedColumn:
            raise ValueError("a reviewed prepared column is required")
        width = base.log_c.shape[1]
        constant = np.full((base.size, width), -math.inf)
        numerator = np.zeros((base.size, width))
        volume = np.zeros((base.size, width))
        for i in range(base.size):
            mechanisms, grain, _ = base.layer_inputs[int(base.layer[i])]
            p = float(base.reference_pa[i])
            for j, m in enumerate(mechanisms):
                constant[i, j] = math.log(m.a)-m.grain_exponent*math.log(grain)
                numerator[i, j] = m.energy_j_mol+p*m.volume_m3_mol
                volume[i, j] = m.volume_m3_mol
        return cls(base, weakening.frozen(constant), weakening.frozen(numerator), weakening.frozen(volume))

    def at(self, temperature):
        t = np.asarray(temperature)
        if t.dtype.kind != "f" or t.shape != (self.base.size,) or not np.all(np.isfinite(t) & (t > 0)):
            raise ValueError("temperature must be finite, positive and one value per material point")
        rt = R*t
        log_c = self.constant-self.numerator/rt[:, None]
        if not np.all(np.isfinite(log_c[self.base.active])):
            raise ValueError("log creep coefficient outside finite support")
        vrt = self.volume/rt[:, None] if self.base.closure == weakening.LITHOSTATIC else np.zeros_like(self.volume)
        digest = hashlib.sha256(self.base.fingerprint.encode()+t.astype(float).tobytes()).hexdigest()
        frozen = weakening.frozen
        return dataclasses.replace(self.base, temperature_k=frozen(t), log_c=frozen(log_c),
                                   volume_rt=frozen(vrt), fingerprint=digest)


def mechanics(prep, law, kappa, rate, guess, fractions):
    """The reviewed stress solve and column sums, plus once-only heat deposition per control volume."""
    kappa = weakening.history_array(prep, kappa)
    local = weakening.stresses(prep, law.factors(kappa), rate, guess)
    w, s = prep.weight, local["stress"]
    force = math.copysign(math.fsum(2*w*s), rate)
    work = force*rate
    creep_work = math.fsum(2*w*s*local["creep_rate"])
    plastic_work = math.fsum(2*w*s*local["plastic_rate"])
    if abs(creep_work+plastic_work-work)/work > 2*TOL:
        raise ValueError("constitutive work partition failed")
    fc, fp = fractions
    source = w*2*s*(fc*local["creep_rate"]+fp*local["plastic_rate"])      # W/m^2 per control volume
    return dict(rate=rate, force=force, work=work, creep_work=creep_work, plastic_work=plastic_work,
                heat=fc*creep_work+fp*plastic_work, stored=(1-fc)*creep_work+(1-fp)*plastic_work,
                source=source, stress=s, x=local["x"], kdot=2*local["plastic_rate"],
                plastic_rate=local["plastic_rate"], iterations=local["iterations"])


def heat_fractions(fractions):
    if type(fractions) not in (list, tuple) or len(fractions) != 2:
        raise ValueError("creep and plastic heat fractions required")
    out = tuple(number(f, "heat fraction", nonnegative=True) for f in fractions)
    if any(f > 1 for f in out):
        raise ValueError("heat fractions must lie in [0, 1]; dissipation is not amplified")
    return out


def policy_limits(policy):
    if type(policy) is not dict or type(policy.get("max_steps")) is not int or not 1 <= policy["max_steps"] <= 256:
        raise ValueError("step ceiling outside the fixed execution limit")


# ----------------------------------------------------------------------------- coupled support pairing

def same_support(thermal, base):
    """Match the actual material support and known reference density, with intact thermal preparation.

    Supplied-pressure analytical columns carry no mechanical density (all NaN); their thermal density
    remains an explicit independent input. Lithostatic columns must use the same reference inventory.
    """
    if not valid_thermal(thermal) or type(base) is not weakening.PreparedColumn:
        return False
    if not all(np.array_equal(a, b) for a, b in ((thermal.layer, base.layer), (thermal.depth_m, base.depth_m),
                                                (thermal.volume_m, base.weight))):
        return False
    if base.closure == weakening.LITHOSTATIC:
        return np.array_equal(thermal.reference_density_kg_m3, base.density)
    return base.closure == weakening.SUPPLIED and np.all(np.isnan(base.density))
