"""I02.2a package owner of the I01 evolving-weakening column response. WORKING NON-CANON.

A laterally uniform, coaxial plane-strain column: per-point creep/plasticity coefficients prepared through the column
kernel, the ASPECT-form weakening law on raw engineering plastic history, and the vectorised safeguarded stress solve
with its force/work sums. Moved without change from tools/check_i01_weakening.py, which re-exports these same objects
and keeps its own rate/force evolution, envelopes, oracles, case loading and campaign. No localisation, rupture,
necking or breakup.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import time

import numpy as np

from . import _integration_column as column

LITHOSTATIC, SUPPLIED = "lithostatic_vertical", "supplied_mean"
COMMON_LAYER_KEYS = {"name", "thickness_m", "temperature_k", "pore_pressure_pa", "grain_m",
                     "cohesion_pa", "friction_rad", "plastic_viscosity_pa_s", "creep"}
LAYER_KEYS = {LITHOSTATIC: COMMON_LAYER_KEYS | {"density_kg_m3"},
              SUPPLIED: COMMON_LAYER_KEYS | {"mean_pressure_pa"}}
CREEP_KEYS = {"a", "n", "energy_j_mol", "volume_m3_mol", "grain_exponent"}
TOL = column.POLICY["rate_relative_tolerance"]
number = column.number


def positive(value, name):
    return number(value, name, positive=True)


def check_deadline(deadline):
    if deadline is not None and time.perf_counter() > deadline:
        raise RuntimeError("cooperative time budget exhausted; nothing further committed")


# ----------------------------------------------------------------------------- inputs

@dataclass(frozen=True)
class WeakeningLaw:
    """ASPECT-form linear interval law on raw engineering plastic shear.

    lambda = 1 - (1 - f) clip((kappa - start)/(end - start), 0, 1);
    C = C0 lambda_C, phi = phi0 lambda_phi. Factors of 1 switch weakening off exactly.
    """
    start: float
    end: float
    cohesion_factor: float
    friction_factor: float

    def __post_init__(self):
        for key in ("start", "end", "cohesion_factor", "friction_factor"):
            object.__setattr__(self, key, number(getattr(self, key), key, nonnegative=True))
        if not self.start < self.end:
            raise ValueError("weakening interval end must exceed its start")
        if not (0 < self.cohesion_factor <= 1 and 0 < self.friction_factor <= 1):
            raise ValueError("weakening factors must lie in (0, 1]; no strengthening or zero strength")

    @classmethod
    def from_spec(cls, spec):
        if type(spec) is not dict or set(spec) != {"interval_engineering", "cohesion_factor", "friction_factor"}:
            raise ValueError("weakening must declare only the interval and the two factors")
        interval = spec["interval_engineering"]
        if type(interval) is not list or len(interval) != 2:
            raise ValueError("weakening interval must be [start, end]")
        return cls(interval[0], interval[1], spec["cohesion_factor"], spec["friction_factor"])

    def factors(self, kappa):
        fraction = np.clip((kappa-self.start)/(self.end-self.start), 0., 1.)
        return 1.-(1.-self.cohesion_factor)*fraction, 1.-(1.-self.friction_factor)*fraction

    def certify(self, prep):
        """Yield must be non-increasing in history for every admissible effective pressure.

        dY/du at P_eff=0 is worst: require phi0 (1-f_phi) tan(phi0) <= 1-f_C where C0 > 0.
        """
        risky = prep.plastic & (prep.cohesion_pa > 0) & (
            prep.friction_rad*(1.-self.friction_factor)*np.tan(prep.friction_rad) > 1.-self.cohesion_factor)
        if np.any(risky):
            raise ValueError("weakening law can raise near-surface yield; history monotonicity not certified")
        return True


def validate_creep(law):
    if type(law) is not dict or not {"a", "n", "energy_j_mol"} <= set(law) <= CREEP_KEYS:
        raise ValueError("creep laws declare only a, n, energy and optional volume/grain exponent")
    return column.Creep(**law)


def validate_layers(layers, closure):
    if closure not in LAYER_KEYS:
        raise ValueError("unsupported pressure closure")
    if type(layers) is not list or not 1 <= len(layers) <= column.POLICY["max_layers"]:
        raise ValueError("one to 64 layers required")
    for layer in layers:
        if type(layer) is not dict or set(layer) != LAYER_KEYS[closure]:
            raise ValueError("layer fields do not match the declared pressure closure")
        if type(layer["creep"]) is not list or not 1 <= len(layer["creep"]) <= column.POLICY["max_mechanisms"]:
            raise ValueError("one to four creep laws per layer")
        for law in layer["creep"]:
            validate_creep(law)
        for key in ("temperature_k", "pore_pressure_pa") + (("mean_pressure_pa",) if closure == SUPPLIED else ()):
            if type(layer[key]) is not list or len(layer[key]) != 2:
                raise ValueError(key+" must be a [top, bottom] profile")
        if closure == LITHOSTATIC:
            positive(layer["density_kg_m3"], "density")
    return layers


def fingerprint(layers, order, closure, gravity):
    text = json.dumps(dict(layers=layers, order=order, closure=closure, gravity=gravity),
                      sort_keys=True, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def frozen(values, dtype=float):
    out = np.asarray(values, dtype=dtype)
    # A flag on an owning array can be reversed, invalidating fingerprint reuse.
    return np.frombuffer(out.tobytes(), dtype=out.dtype).reshape(out.shape)


@dataclass(frozen=True, eq=False)
class PreparedColumn:
    """Immutable per-point coefficients; valid only while its fingerprinted inputs are unchanged."""
    closure: str
    order: int
    fingerprint: str
    thickness_m: float
    layer: np.ndarray
    depth_m: np.ndarray
    weight: np.ndarray
    temperature_k: np.ndarray
    reference_pa: np.ndarray        # lithostatic vertical stress, or supplied mean pressure
    pore_pa: np.ndarray
    density: np.ndarray
    cohesion_pa: np.ndarray
    friction_rad: np.ndarray
    log_c: np.ndarray               # kernel coefficients at reference_pa, padded with -inf
    exponent: np.ndarray
    volume: np.ndarray
    volume_rt: np.ndarray           # V/(R T) for the lithostatic pressure feedback, else 0
    active: np.ndarray
    eta: np.ndarray                 # plastic viscosity; 1 where no plastic branch
    plastic: np.ndarray
    layer_inputs: tuple

    @property
    def size(self):
        return int(self.weight.size)


def prepare(layers, order, *, closure, gravity=None):
    """Prepare through the read-only column kernel: identical quadrature and creep coefficients."""
    validate_layers(layers, closure)
    g = positive(gravity, "gravity") if closure == LITHOSTATIC else None
    kernel_layers, top = [], 0.
    for layer in layers:
        k = {key: layer[key] for key in COMMON_LAYER_KEYS - {"name"}}
        if closure == LITHOSTATIC:
            bottom = top+number(layer["density_kg_m3"], "density")*g*number(layer["thickness_m"], "thickness")
            k["mean_pressure_pa"] = [top, bottom]
            top = bottom
        else:
            k["mean_pressure_pa"] = layer["mean_pressure_pa"]
        kernel_layers.append(k)
    kernel = column.Column(kernel_layers, order)
    nodes, _ = np.polynomial.legendre.leggauss(order)
    width = max(len(layer["creep"]) for layer in layers)
    rows, index, depth_top, inputs = [], 0, 0., []
    for li, (layer, k) in enumerate(zip(layers, kernel_layers)):
        t0, t1 = (number(v, "temperature", positive=True) for v in k["temperature_k"])
        p0, p1 = (number(v, "pressure", nonnegative=True) for v in k["mean_pressure_pa"])
        w0, w1 = (number(v, "pore pressure", nonnegative=True) for v in k["pore_pressure_pa"])
        c0, phi = number(k["cohesion_pa"], "cohesion"), number(k["friction_rad"], "friction")
        h = number(k["thickness_m"], "thickness")
        mechanisms = tuple(column.Creep(**law) for law in k["creep"])
        eta = k["plastic_viscosity_pa_s"]
        inputs.append((mechanisms, number(k["grain_m"], "grain"), None if eta is None else float(eta)))
        for node in nodes:
            weight, law = kernel.points[index]
            index += 1
            f = (float(node)+1)/2
            t, p, pore = t0*(1-f)+t1*f, p0*(1-f)+p1*f, w0*(1-f)+w1*f
            if law.yield_pa != c0*math.cos(phi)+max(p-pore, 0.)*math.sin(phi):
                raise RuntimeError("prepared quadrature differs from the column kernel")
            pad = width-len(mechanisms)
            volumes = [m.volume_m3_mol for m in mechanisms]+[0.]*pad
            rows.append(dict(
                layer=li, depth=depth_top+f*h, weight=weight, t=t, p=p, pore=pore,
                rho=float(layer["density_kg_m3"]) if closure == LITHOSTATIC else math.nan,
                c0=c0, phi=phi, log_c=list(law.log_coefficients)+[-math.inf]*pad,
                n=list(law.exponents)+[1.]*pad, volume=volumes,
                vrt=[v/(column.R*t) if closure == LITHOSTATIC else 0. for v in volumes],
                active=[True]*len(mechanisms)+[False]*pad,
                eta=1. if law.plastic_viscosity_pa_s is None else law.plastic_viscosity_pa_s,
                plastic=law.plastic_viscosity_pa_s is not None))
        depth_top += h
    col = lambda key, dtype=float: frozen([r[key] for r in rows], dtype)
    return PreparedColumn(
        closure=closure, order=order, fingerprint=fingerprint(layers, order, closure, g),
        thickness_m=kernel.thickness_m, layer=col("layer", int), depth_m=col("depth"), weight=col("weight"),
        temperature_k=col("t"), reference_pa=col("p"), pore_pa=col("pore"), density=col("rho"),
        cohesion_pa=col("c0"), friction_rad=col("phi"), log_c=col("log_c"), exponent=col("n"),
        volume=col("volume"), volume_rt=col("vrt"), active=col("active", bool), eta=col("eta"),
        plastic=col("plastic", bool), layer_inputs=tuple(inputs))


def history_array(prep, kappa):
    kappa = np.asarray(kappa)
    if (kappa.dtype.kind not in "fiu" or kappa.shape != (prep.size,)
            or not np.all(np.isfinite(kappa)) or np.any(kappa < 0)):
        raise ValueError("raw history must be finite, nonnegative and one value per material point")
    return np.asarray(kappa, dtype=float)


# ----------------------------------------------------------------------------- constitutive response

def _evaluate(prep, x, le, sign, cc, sp, inv):
    """Scaled total rate/e and its log-stress derivative at every point; no clipping."""
    s = np.exp(x)
    expo = prep.log_c+prep.exponent*x[:, None]-le
    litho = prep.closure == LITHOSTATIC
    if litho:
        expo = expo+sign*prep.volume_rt*s[:, None]
    if np.any(expo[prep.active] > 700.):
        raise ValueError("stress outside bounded representable support")
    scaled = np.exp(expo)                                  # padded mechanisms give exp(-inf)=0
    creep = scaled.sum(axis=1)
    slope = prep.exponent+sign*prep.volume_rt*s[:, None] if litho else prep.exponent
    dcreep = (scaled*slope).sum(axis=1)
    base = prep.reference_pa-prep.pore_pa
    if litho:
        effective = base-sign*s
        y = cc+np.maximum(effective, 0.)*sp
        dy = np.where(effective > 0, -sign*sp, 0.)
    else:
        y = cc+np.maximum(base, 0.)*sp
        dy = 0.
    over = s-y
    yielding = prep.plastic & (over > 0)
    plastic = np.where(yielding, over*inv, 0.)
    dplastic = np.where(yielding, s*(1.-dy)*inv, 0.)
    return dict(s=s, creep=creep, plastic=plastic, total=creep+plastic, derivative=dcreep+dplastic,
                yield_pa=y, slope_min=np.where(prep.active, slope, np.inf).min(axis=1))


def stresses(prep, factors, rate, guess=None):
    """Vectorised safeguarded Newton in log stress, one independent root per material point."""
    rate = number(rate, "signed axial rate")
    if rate == 0:
        raise ValueError("a nonzero axial rate is required")
    e, sign = abs(rate), math.copysign(1., rate)
    le = math.log(e)
    lam_c, lam_f = factors
    friction = prep.friction_rad*lam_f
    cc, sp = prep.cohesion_pa*lam_c*np.cos(friction), np.sin(friction)
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        inv = np.where(prep.plastic, np.exp(-math.log(2)-np.log(prep.eta)-le), 0.)
        hi = np.where(prep.active, (le-prep.log_c)/prep.exponent, np.inf).min(axis=1)
        y0 = cc+np.maximum(prep.reference_pa-prep.pore_pa, 0.)*sp
        plastic_bound = np.logaddexp(math.log(2)+np.log(prep.eta)+le, np.log(y0))
        hi = np.where(prep.plastic, np.minimum(hi, plastic_bound), hi)
        lo = hi-np.log(prep.active.sum(axis=1)+prep.plastic)
        if not (np.all(np.isfinite(lo)) and np.all(np.isfinite(hi)) and lo.min() > -700 and hi.max() < 700):
            raise ValueError("stress outside bounded representable support")
        # Validate both bracket ends by evaluation; pressure feedback can move a branch root.
        for _ in range(64):
            out = _evaluate(prep, hi, le, sign, cc, sp, inv)
            short = out["total"] < 1.
            if not short.any():
                break
            hi = np.where(short, hi+math.log(2), hi)
        else:
            raise ValueError("no upper stress bracket within the supported range")
        if np.any(out["slope_min"] <= 0):
            raise ValueError("creep rate is not monotone in stress under the compressive pressure closure")
        for _ in range(64):
            out = _evaluate(prep, lo, le, sign, cc, sp, inv)
            long = out["total"] > 1.
            if not long.any():
                break
            lo = np.where(long, lo-math.log(2), lo)
        else:
            raise ValueError("no lower stress bracket within the supported range")
        x = hi.copy() if guess is None else np.where((guess > lo) & (guess < hi), guess, hi)
        done = np.zeros(prep.size, dtype=bool)
        for iteration in range(column.POLICY["iterations"]):
            out = _evaluate(prep, x, le, sign, cc, sp, inv)
            residual = out["total"]-1.
            done |= np.abs(residual) <= TOL
            if done.all():
                break
            open_ = ~done
            hi = np.where(open_ & (residual > 0), x, hi)
            lo = np.where(open_ & (residual <= 0), x, lo)
            trial = x-np.log(out["total"])/(out["derivative"]/out["total"])
            candidate = np.where((trial > lo) & (trial < hi), trial, (lo+hi)/2)
            if np.any(open_ & (candidate == x)):
                raise ValueError("stress resolution exhausted before convergence")
            x = np.where(open_, candidate, x)
        else:
            raise ValueError("vectorised creep/plasticity solve did not converge")
    s = out["s"]
    tangent = s/(e*out["derivative"])
    if not np.all(np.isfinite(tangent) & (tangent > 0)):
        raise ValueError("constitutive tangent not representable")
    return dict(x=x, stress=s, creep_rate=e*out["creep"], plastic_rate=e*out["plastic"],
                yield_pa=out["yield_pa"], tangent=tangent, iterations=iteration+1)


def respond(prep, law, kappa, rate, guess=None):
    """Column resistance for a supplied state and signed axial rate a.

    F = sign(a) 2 sum(w s) [N/m]; W = a F = creep + plastic [W/m^2];
    dF/da = 2 sum(w ds/de) > 0; kdot = 2 e_p [1/s], engineering plastic shear.
    """
    kappa = history_array(prep, kappa)
    local = stresses(prep, law.factors(kappa), rate, guess)
    w, s = prep.weight, local["stress"]
    force = math.copysign(math.fsum(2*w*s), rate)
    work = force*rate
    creep_work = math.fsum(2*w*s*local["creep_rate"])
    plastic_work = math.fsum(2*w*s*local["plastic_rate"])
    residual = abs(creep_work+plastic_work-work)/work
    if residual > 2*TOL:
        raise ValueError("constitutive work partition failed")
    return dict(rate=rate, force=force, dforce=math.fsum(2*w*local["tangent"]), work=work,
                creep_work=creep_work, plastic_work=plastic_work, work_residual=residual,
                stress=s, x=local["x"], kdot=2*local["plastic_rate"], plastic_rate=local["plastic_rate"],
                yield_pa=local["yield_pa"], iterations=local["iterations"])
