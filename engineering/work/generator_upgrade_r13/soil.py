"""Coupled, fixed-geometry soil water/enthalpy finite volumes (R13).

Depth and face fluxes are positive DOWNWARDS; extensive quantities are per m2.
The supplied VG/Mualem law and an explicitly identified freezing closure define
equilibrium, including subfreezing liquid. The default is Dall'Amico et al.
(2011), equations 4, 10, 17, 20, 22--24. The selectable Painter--Karra (2014)
apparent-pore closure uses their equations 15, 18--19 with omega=1/beta and an
explicitly supplied beta; its primary head is LIQUID pressure, including in
saturated frozen cells. It is not an ad-hoc extension of the default law. Ice and
water have the SAME supplied density: deformation, vapour, salt, hysteresis,
ice transport and an ice-pressure law are outside this model. In particular,
positive saturated pressure AND ice is outside the default zero-ice-pressure law.

Both conservation equations are solved together by backward Euler, with an
analytic Jacobian. Two half steps are accepted only after comparison against
one full step. Conservation residuals and temporal error estimates are separate
gates; neither proves spatial convergence or empirical accuracy. No cell merge,
minimum-thickness replacement, numerical-zero ledger, or physical default is
used. The linear, phase-weighted conductivity interpolation is an explicitly
supplied phenomenological law, NOT a calibrated Johansen soil model.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

import numpy as np
from scipy.optimize import least_squares


SCHEMA = "diadem.coupled-soil.r13"
STATE_SCHEMA = SCHEMA + ".state"
SOURCE = "https://tc.copernicus.org/articles/5/469/2011/tc-5-469-2011.pdf"
PAINTER_KARRA_SOURCE = "https://acsess.onlinelibrary.wiley.com/doi/full/10.2136/vzj2013.04.0071"
DALL_AMICO = "DALL_AMICO_2011_ZERO_ICE_PRESSURE"
PAINTER_KARRA = "PAINTER_KARRA_2014_APPARENT_PORE"
STATUSES = {"CANON", "WORKING NON-CANON", "SYNTHETIC TEST", "UNKNOWN"}
LAYER_NUMBERS = (
    "thickness_m", "theta_r", "theta_s", "vg_alpha_per_m", "vg_n",
    "mualem_l", "saturated_conductivity_m_s", "ice_impedance",
    "dry_heat_capacity_j_m3_k", "conductivity_dry_w_m_k",
    "conductivity_saturated_unfrozen_w_m_k", "conductivity_saturated_frozen_w_m_k",
)
CONSTANTS = (
    "water_density_kg_m3", "water_heat_capacity_j_kg_k", "ice_heat_capacity_j_kg_k",
    "latent_heat_j_kg", "melting_temperature_k", "gravity_m_s2",
)
CONTROL_NUMBERS = (
    "initial_step_s", "min_step_s", "max_step_s", "water_atol_m",
    "water_fraction_atol", "energy_atol_j_m2", "head_atol_m", "temperature_atol_k",
    "relative_tolerance", "nonlinear_water_atol_m", "nonlinear_energy_atol_j_m2",
    "min_head_m", "max_head_m", "min_temperature_k", "max_temperature_k",
)
STATE_FIELDS = (
    "schema", "model_sha256", "head_m", "total_water", "temperature_k",
    "temperature_offset_k", "liquid_water", "ice_water", "liquid_head_m", "enthalpy_j_m2", "elapsed_seconds",
)
ASSUMPTIONS = [
    "One-dimensional rigid fixed geometry; equal liquid/ice density; no cell merging.",
    "Local phase equilibrium: supplied VG retention and linearised Dall'Amico Clapeyron law.",
    "Zero ice pressure; positive saturated pressure with ice is outside this closure.",
    "No vapour, salt, deformation, ice transport, hysteresis or preferential flow.",
    "Supplied linear phase-weighted conductivity; air heat capacity neglected.",
    "Zero surface pond storage; excess input and exfiltration become explicit runoff.",
    "Root removal exports liquid enthalpy; atmospheric vaporisation energy is not modelled.",
    "Backward-Euler step doubling estimates temporal error, not spatial or empirical accuracy.",
    "Temperature offset from the common melting datum is authoritative; absolute kelvin is its readable recomposition.",
]


class UnknownInput(ValueError):
    """Required physical evidence is unknown, never a numerical zero."""


class ConstitutiveDomainError(ValueError):
    """The supplied state is outside the explicitly admitted physical closure."""


def _number(x, label):
    if type(x) not in (int, float):
        raise ValueError(label + " requires a finite JSON number, not bool")
    try:
        result = float(x)
    except OverflowError as error:
        raise ValueError(label + " exceeds finite binary64") from error
    if not math.isfinite(result):
        raise ValueError(label + " requires a finite JSON number")
    return result


def _keys(obj, required, label, optional=()):
    if type(obj) is not dict or not set(required) <= set(obj) or set(obj) - set(required) - set(optional):
        raise ValueError("exact " + label + " fields required")


def _text(x, label):
    if type(x) is not str or not x.strip() or len(x) > 4096:
        raise ValueError("explicit bounded " + label + " required")


def _evidence(obj):
    _text(obj["evidence"], "evidence")
    if obj["source_status"] not in STATUSES:
        raise ValueError("explicit source status required")
    if obj["source_status"] == "UNKNOWN":
        raise UnknownInput("required physical evidence is UNKNOWN")


def model_digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _model(model):
    _keys(model, ("layers", "constants", "evidence", "source_status"), "model", ("freezing_model", "clapeyron_beta"))
    _evidence(model)
    law = model.get("freezing_model", DALL_AMICO)
    if law not in (DALL_AMICO, PAINTER_KARRA):
        raise ValueError("explicit supported freezing_model required")
    if law == PAINTER_KARRA:
        if "clapeyron_beta" not in model or model["clapeyron_beta"] is None:
            raise UnknownInput("Painter--Karra requires explicit clapeyron_beta (omega=1/beta)")
        if _number(model["clapeyron_beta"], "clapeyron_beta") <= 0:
            raise ValueError("clapeyron_beta must be positive")
    elif "clapeyron_beta" in model:
        raise ValueError("no unused Painter--Karra coefficient on Dall'Amico model")
    _keys(model["constants"], CONSTANTS, "constants")
    for k in CONSTANTS:
        if model["constants"][k] is None:
            raise UnknownInput(k + " is unresolved")
        if _number(model["constants"][k], k) <= 0:
            raise ValueError(k + " must be positive")
    layers = model["layers"]
    if type(layers) is not list or not 1 <= len(layers) <= 128:
        raise ValueError("one to 128 explicit ordered material layers required")
    identities = set()
    for layer in layers:
        _keys(layer, (*LAYER_NUMBERS, "layer_id", "evidence", "source_status"), "layer")
        _evidence(layer)
        _text(layer["layer_id"], "layer identity")
        if layer["layer_id"] in identities:
            raise ValueError("duplicate layer identity")
        identities.add(layer["layer_id"])
        for k in LAYER_NUMBERS:
            if layer[k] is None:
                raise UnknownInput(k + " is unresolved")
            _number(layer[k], k)
        if not 0 <= layer["theta_r"] < layer["theta_s"] <= 1:
            raise ValueError("require 0 <= residual < saturated fraction <= 1")
        for k in ("thickness_m", "vg_alpha_per_m", "dry_heat_capacity_j_m3_k"):
            if layer[k] <= 0:
                raise ValueError(k + " must be positive")
        if layer["vg_n"] <= 1:
            raise ValueError("VG n must exceed one; m=1-1/n")
        for k in ("mualem_l", "saturated_conductivity_m_s", "ice_impedance",
                  "conductivity_dry_w_m_k", "conductivity_saturated_unfrozen_w_m_k",
                  "conductivity_saturated_frozen_w_m_k"):
            if layer[k] < 0:
                raise ValueError(k + " must be nonnegative")
    if not math.isfinite(math.fsum(l["thickness_m"] for l in layers)):
        raise ValueError("column thickness overflow")
    return len(layers)


def _controls(controls, model):
    _keys(controls, (*CONTROL_NUMBERS, "max_steps", "max_nonlinear_evaluations"), "controls")
    for k in CONTROL_NUMBERS:
        _number(controls[k], k)
    for k in CONTROL_NUMBERS:
        if k not in ("min_head_m", "max_head_m", "relative_tolerance") and controls[k] <= 0:
            raise ValueError(k + " must be positive")
    if not 0 <= controls["relative_tolerance"] < 1:
        raise ValueError("relative tolerance must be in [0,1)")
    if not controls["min_step_s"] <= controls["initial_step_s"] <= controls["max_step_s"]:
        raise ValueError("require min_step <= initial_step <= max_step")
    if not controls["min_head_m"] < 0 < controls["max_head_m"]:
        raise ValueError("head bounds must straddle zero")
    if not controls["min_temperature_k"] < controls["max_temperature_k"]:
        raise ValueError("temperature bounds out of order")
    c = model["constants"]
    if model.get("freezing_model", DALL_AMICO) == DALL_AMICO and controls["min_head_m"] <= -c["latent_heat_j_kg"] / c["gravity_m_s2"]:
        raise ValueError("linearised Clapeyron onset must remain above absolute zero")
    # The latent plus sensible phase derivative must stay positive; otherwise
    # the chosen constant-property extrapolation is not an invertible enthalpy law.
    for t in (controls["min_temperature_k"], controls["max_temperature_k"]):
        if c["latent_heat_j_kg"] + (c["water_heat_capacity_j_kg_k"] - c["ice_heat_capacity_j_kg_k"]) * (t-c["melting_temperature_k"]) <= 0:
            raise ValueError("enthalpy phase derivative nonpositive in supplied temperature bounds")
    for k in ("max_steps", "max_nonlinear_evaluations"):
        if type(controls[k]) is not int or not 1 <= controls[k] <= 1000000:
            raise ValueError(k + " requires a bounded positive integer")


def _event(event, n):
    _keys(event, ("duration_s", "surface_water_flux_m_s", "surface_water_temperature_k",
                 "top_heat", "bottom_heat", "bottom_water", "evidence", "source_status"), "event",
          ("root_withdrawal_m_s", "uptake", "potential_root_demand_m_s"))
    _evidence(event)
    for k in ("duration_s", "surface_water_flux_m_s", "surface_water_temperature_k"):
        if event[k] is None:
            raise UnknownInput(k + " is unresolved")
        if _number(event[k], k) < 0 or k.endswith("temperature_k") and event[k] == 0:
            raise ValueError("positive temperature and nonnegative duration/input required")
    for name in ("top_heat", "bottom_heat"):
        b = event[name]
        _keys(b, ("kind", "value", "evidence", "source_status"), name)
        _evidence(b)
        if b["kind"] not in ("temperature", "flux"):
            raise ValueError("heat boundary must be temperature or downward flux")
        if b["value"] is None:
            raise UnknownInput(name + " value is unresolved")
        value = _number(b["value"], "heat boundary")
        if b["kind"] == "temperature" and value <= 0:
            raise ValueError("positive boundary temperature required")
    b = event["bottom_water"]
    _keys(b, ("kind", "evidence", "source_status"), "bottom water", ("head_m", "temperature_k"))
    _evidence(b)
    if b["kind"] not in ("noflow", "free_drainage", "head"):
        raise ValueError("unsupported bottom water boundary")
    if b["kind"] == "head":
        if set(b) != {"kind", "evidence", "source_status", "head_m", "temperature_k"}:
            raise ValueError("fixed head requires head and inflowing liquid temperature")
        if b["head_m"] is None or b["temperature_k"] is None:
            raise UnknownInput("fixed head or inflowing liquid temperature is unresolved")
        _number(b["head_m"], "bottom head")
        if _number(b["temperature_k"], "bottom inflow temperature") <= 0:
            raise ValueError("positive bottom inflow temperature required")
    elif set(b) != {"kind", "evidence", "source_status"}:
        raise ValueError("no unused head/temperature on closed or free drainage boundary")
    if "root_withdrawal_m_s" in event:
        if "uptake" in event or "potential_root_demand_m_s" in event:
            raise ValueError("choose direct root withdrawal OR potential demand with uptake")
        rates = event["root_withdrawal_m_s"]
        if type(rates) is not list or len(rates) != n or any(_number(x, "root withdrawal") < 0 for x in rates):
            raise ValueError("one nonnegative explicit root withdrawal per layer required")
    else:
        if not {"uptake", "potential_root_demand_m_s"} <= set(event):
            raise ValueError("explicit root withdrawal or uptake model required, even when zero")
        if _number(event["potential_root_demand_m_s"], "root demand") < 0:
            raise ValueError("root demand must be nonnegative")
        u = event["uptake"]
        _keys(u, ("weights", "dry_zero_head_m", "dry_full_head_m", "wet_full_head_m", "wet_zero_head_m"), "uptake",
              ("evidence", "source_status"))
        if "evidence" in u or "source_status" in u:
            if not {"evidence", "source_status"} <= set(u):
                raise ValueError("uptake evidence and source status must occur together")
            _evidence(u)
        weights = u["weights"]
        if type(weights) is not list or len(weights) != n or any(_number(x, "uptake weight") < 0 for x in weights) or abs(math.fsum(weights)-1) > 8*math.ulp(1.):
            raise ValueError("uptake weights must match layers and sum to one")
        a, b, c, d = (_number(u[k], k) for k in ("dry_zero_head_m", "dry_full_head_m", "wet_full_head_m", "wet_zero_head_m"))
        if not a < b <= c < d <= 0:
            raise ValueError("require dry-zero < dry-full <= wet-full < wet-zero <= zero")


def _vg(layer, h, *, with_deficit=False):
    """Value and analytic head derivatives; log forms preserve dry-end accuracy."""
    r, s, a, n, ell, ks = (layer[k] for k in ("theta_r", "theta_s", "vg_alpha_per_m", "vg_n", "mualem_l", "saturated_conductivity_m_s"))
    if h >= 0:
        return (s, ks, 0., 0., 0.) if with_deficit else (s, ks, 0., 0.)
    m = 1-1/n
    logx = n*(math.log(a)+math.log(-h))
    logterm = float(np.logaddexp(0., logx))
    logse = -m*logterm
    se = math.exp(logse)
    dlogse = -m*n*math.exp(logx-logterm)/h
    one_minus_v = -math.expm1(logse/m)
    if one_minus_v == 0:
        # At unrepresentably tiny suction the saturated branch is the finite
        # limit. Such a branch cannot be used to certify a singular pressure.
        return (s, ks, 0., 0., 0.) if with_deficit else (s, ks, 0., 0.)
    bracket = -math.expm1(m*math.log(one_minus_v))
    factor = math.exp(ell*logse)
    k = ks*factor*bracket*bracket
    db = math.exp((m-1)*math.log(one_minus_v)+logse/m)*dlogse
    dk = ks*factor*(ell*dlogse*bracket*bracket+2*bracket*db)
    deficit = (s-r)*(-math.expm1(logse))
    theta = s-deficit if deficit < (s-r)/2 else r+(s-r)*se
    result = (theta, k, (s-r)*se*dlogse, dk)
    return (*result, deficit) if with_deficit else result


def _content_difference(a, deficit_a, b, deficit_b):
    """a-b, choosing the smaller complementary operands to avoid cancellation.

    Deficits share one unchanged porosity datum within each cell. They retain
    microscopic unsaturated storage even when readable theta rounds to phi.
    Direct contents remain preferable at the dry end of the same exact law.
    """
    return np.where(np.maximum(np.abs(deficit_a), np.abs(deficit_b)) < np.maximum(np.abs(a), np.abs(b)),
                    np.asarray(deficit_b)-np.asarray(deficit_a), np.asarray(a)-np.asarray(b))


def _properties(model, head, temperature, *, temperature_offset=None, permit_frozen_positive=False):
    c, layers = model["constants"], model["layers"]
    rho, cw, ci, latent, tm, g = (c[k] for k in CONSTANTS)
    result = {k: [] for k in ("theta", "liquid", "ice", "liquid_head", "conductivity", "thermal_conductivity",
                              "capacity", "energy", "theta_h", "theta_t", "liquid_h", "liquid_t", "psi_h", "psi_t",
                              "k_h", "k_t", "lambda_h", "lambda_t", "energy_h", "energy_t", "theta_deficit", "liquid_deficit")}
    offsets = np.asarray(temperature)-tm if temperature_offset is None else np.asarray(temperature_offset)
    for layer, h, t, offset in zip(layers, head, temperature, offsets):
        total, _, total_h, _, total_deficit = _vg(layer, h, with_deficit=True)
        total_t = 0.
        ice = None
        if t <= 0:
            raise ConstitutiveDomainError("nonpositive absolute temperature")
        if model.get("freezing_model", DALL_AMICO) == PAINTER_KARRA:
            # A is FULL saturation (including residual), not effective
            # saturation. The apparent pore space is (1-s_i)*porosity.
            # h remains liquid transport pressure; the retention head used
            # only for liquid mobility must never replace it in Darcy flow.
            phi = layer["theta_s"]
            theta_a, deficit_a, theta_a_h = total, total_deficit, total_h
            cold_head = model["clapeyron_beta"]*latent/(g*tm)*min(0., offset)
            cold_theta, cold_k, cold_dtheta, cold_dk, deficit_b = _vg(layer, cold_head, with_deficit=True)
            cold_t = model["clapeyron_beta"]*latent/(g*tm) if offset < 0 else 0.
            if _content_difference(theta_a, deficit_a, cold_theta, deficit_b) > 0:
                liquid, liquid_h, liquid_t = cold_theta, 0., cold_dtheta*cold_t
                total_deficit = cold_theta*deficit_a/theta_a
                liquid_deficit = deficit_b
                total = phi-total_deficit
                total_h = phi*cold_theta*theta_a_h/(theta_a*theta_a)
                total_t = -liquid_t*deficit_a/theta_a
                ice = phi*float(_content_difference(theta_a, deficit_a, cold_theta, deficit_b))/theta_a
                k0, k0_h, k0_t = cold_k, 0., cold_dk*cold_t
            else:
                liquid, k0, liquid_h, k0_h, liquid_deficit = _vg(layer, h, with_deficit=True)
                liquid_t, k0_t = 0., 0.
                ice = 0.
            psi, psi_h, psi_t = h, 1., 0.
        else:
            psi0 = min(h, 0.)
            onset_offset = g*tm*psi0/latent
            onset = tm+onset_offset
            if onset <= 0:
                raise ConstitutiveDomainError("nonpositive freezing onset")
            if offset < onset_offset:
                if h > 0 and not permit_frozen_positive:
                    raise ConstitutiveDomainError("positive saturated pressure with ice requires an independent ice-pressure closure")
                psi = psi0 + latent/(g*onset)*(offset-onset_offset)
                psi_h = (2*tm*onset_offset+onset_offset*onset_offset-tm*offset)/(onset*onset) if h < 0 else 0.
                psi_t = latent/(g*onset)
                liquid, k0, dl_dpsi, dk_dpsi, liquid_deficit = _vg(layer, psi, with_deficit=True)
                liquid_h, liquid_t = dl_dpsi*psi_h, dl_dpsi*psi_t
                k0_h, k0_t = dk_dpsi*psi_h, dk_dpsi*psi_t
            else:
                psi, psi_h, psi_t = h, 1., 0.
                liquid, k0, dl_dpsi, dk_dpsi, liquid_deficit = _vg(layer, psi, with_deficit=True)
                liquid_h, liquid_t = total_h, 0.
                k0_h, k0_t = dk_dpsi, 0.
        if not math.isfinite(total_t):
            raise ConstitutiveDomainError("nonpositive absolute temperature/freezing onset")
        if ice is None:
            ice = float(_content_difference(total, total_deficit, liquid, liquid_deficit))
        # No clamping mass/phase after a solve. An out-of-regime constitutive
        # value is a failed trial, even if a caller chose permissive tolerances.
        if not layer["theta_r"] <= liquid <= total <= layer["theta_s"]:
            raise ConstitutiveDomainError("soil phase violates residual/porosity bounds")
        ice_h, ice_t = total_h-liquid_h, total_t-liquid_t
        impedance = math.log(10.)*layer["ice_impedance"]/(layer["theta_s"]-layer["theta_r"])
        imp = math.exp(-impedance*ice)
        k = k0*imp
        kh = imp*k0_h-k*impedance*ice_h
        kt = imp*k0_t-k*impedance*ice_t
        dry, unf, froz = (layer[k] for k in ("conductivity_dry_w_m_k", "conductivity_saturated_unfrozen_w_m_k", "conductivity_saturated_frozen_w_m_k"))
        lam = dry+(unf-dry)*liquid/layer["theta_s"]+(froz-dry)*ice/layer["theta_s"]
        lam_h = ((unf-dry)*liquid_h+(froz-dry)*ice_h)/layer["theta_s"]
        lam_t = ((unf-dry)*liquid_t+(froz-dry)*ice_t)/layer["theta_s"]
        cap = layer["dry_heat_capacity_j_m3_k"]+rho*(cw*liquid+ci*ice)
        phase_energy = latent+(cw-ci)*offset
        energy = layer["thickness_m"]*(cap*offset+rho*latent*liquid)
        eh = layer["thickness_m"]*rho*(ci*total_h*offset+phase_energy*liquid_h)
        et = layer["thickness_m"]*(cap+rho*(ci*total_t*offset+phase_energy*liquid_t))
        values = (total, liquid, ice, psi, k, lam, cap, energy, total_h, total_t, liquid_h, liquid_t,
                  psi_h, psi_t, kh, kt, lam_h, lam_t, eh, et, total_deficit, liquid_deficit)
        if not all(math.isfinite(v) for v in values) or k < 0 or lam < 0 or et <= 0:
            raise ConstitutiveDomainError("unrepresentable/nonmonotone supplied constitutive law")
        for key, value in zip(result, values):
            result[key].append(value)
    return {k: np.asarray(v) for k, v in result.items()}


def _state(model, head, temperature, elapsed, *, temperature_offset=None):
    tm = model["constants"]["melting_temperature_k"]
    offsets = np.asarray(temperature)-tm if temperature_offset is None else np.asarray(temperature_offset)
    props = _properties(model, head, temperature, temperature_offset=offsets)
    return {"schema": STATE_SCHEMA, "model_sha256": model_digest(model),
            "head_m": [float(x) for x in head], "total_water": props["theta"].tolist(),
            "temperature_k": [float(tm+x) for x in offsets], "temperature_offset_k": offsets.tolist(),
            "liquid_water": props["liquid"].tolist(),
            "ice_water": props["ice"].tolist(), "liquid_head_m": props["liquid_head"].tolist(),
            "enthalpy_j_m2": props["energy"].tolist(), "elapsed_seconds": float(elapsed)}


def initial_state(model, head_m, temperature_k, *, elapsed_seconds=0.0, temperature_offset_k=None):
    """Heads use the SELECTED law: total-water head for Dall'Amico, liquid for PK.

    Switching closures on a cold state requires a water-preserving initial-head
    conversion by the caller; relabelling an old cold head would change storage.
    Saturated water content alone never determines the supplied pressure.
    """
    n = _model(model)
    for vector, label in ((head_m, "initial head"), (temperature_k, "initial temperature")):
        if type(vector) not in (list, tuple) or len(vector) != n:
            raise ValueError(label + " must match all material cells")
        for x in vector:
            _number(x, label)
    if _number(elapsed_seconds, "elapsed time") < 0:
        raise ValueError("elapsed time must be nonnegative")
    tm = model["constants"]["melting_temperature_k"]
    offsets = [float(t)-tm for t in temperature_k] if temperature_offset_k is None else temperature_offset_k
    if type(offsets) not in (list, tuple) or len(offsets) != n:
        raise ValueError("one explicit temperature offset per layer required")
    for t, offset in zip(temperature_k, offsets):
        _number(offset, "temperature offset")
        if t != tm+offset:
            raise ValueError("readable temperature must exactly recompose from melting datum plus offset")
    return _state(model, head_m, temperature_k, elapsed_seconds, temperature_offset=offsets)


def _read_state(model, state):
    _keys(state, STATE_FIELDS, "state")
    for key in ("total_water", "liquid_water", "ice_water", "liquid_head_m", "enthalpy_j_m2", "temperature_offset_k"):
        if type(state[key]) is not list or len(state[key]) != len(model["layers"]):
            raise ValueError("derived state vectors must match all material cells")
        for x in state[key]:
            _number(x, "derived " + key)
    expected = initial_state(model, state["head_m"], state["temperature_k"], elapsed_seconds=state["elapsed_seconds"],
                             temperature_offset_k=state["temperature_offset_k"])
    if state != expected:
        raise ValueError("state binding, derived phase, or enthalpy differs from its actual supplied model/state")
    return np.asarray(state["head_m"]), np.asarray(state["temperature_k"]), np.asarray(state["temperature_offset_k"])


def _rates(model, props, temperature, event, *, temperature_offset=None):
    """One shared face flux and upwind enthalpy, used by BOTH adjoining cells."""
    n = len(temperature)
    c = model["constants"]
    rho, cw, latent, tm = (c[key] for key in ("water_density_kg_m3", "water_heat_capacity_j_kg_k", "latent_heat_j_kg", "melting_temperature_k"))
    offsets = np.asarray(temperature)-tm if temperature_offset is None else np.asarray(temperature_offset)
    dz = np.asarray([l["thickness_m"] for l in model["layers"]])
    psi, k, lam = (props[x] for x in ("liquid_head", "conductivity", "thermal_conductivity"))
    matrices = {}
    for name, hk, tk in (("p", "psi_h", "psi_t"), ("k", "k_h", "k_t"), ("l", "lambda_h", "lambda_t")):
        a = np.zeros((n, 2*n))
        a[np.arange(n), np.arange(n)] = props[hk]
        a[np.arange(n), n+np.arange(n)] = props[tk]
        matrices[name] = a
    dp, dk, dl = (matrices[x] for x in ("p", "k", "l"))
    dtemp = np.zeros((n, 2*n)); dtemp[:, n:] = np.eye(n)
    q, heat = np.zeros(n+1), np.zeros(n+1)
    # Magnitudes of the actual arithmetic operands, BEFORE cancelling the
    # pressure gradient. In a nanometre cell |q| alone severely understates
    # binary64 evaluation roundoff when two ~metre heads are subtracted.
    q_operands = np.zeros(n+1)
    dq, dh = np.zeros((n+1, 2*n)), np.zeros((n+1, 2*n))
    cap = k[0]*(1-2*psi[0]/dz[0])
    if cap < event["surface_water_flux_m_s"]:
        q[0] = cap
        q_operands[0] = k[0]*(1+2*abs(psi[0])/dz[0])
        dq[0] = (1-2*psi[0]/dz[0])*dk[0]-2*k[0]/dz[0]*dp[0]
    else:
        q[0] = event["surface_water_flux_m_s"]
        q_operands[0] = abs(q[0])
    for face in range(1, n):
        i, j = face-1, face
        distance = (dz[i]+dz[j])/2
        if k[i] > 0 and k[j] > 0:
            a, b = dz[i]/(2*k[i]), dz[j]/(2*k[j])
            conductance = 1/(a+b)
            q[face] = conductance*(distance+psi[i]-psi[j])
            q_operands[face] = conductance*(distance+abs(psi[i])+abs(psi[j]))
            dq[face] = conductance*(dp[i]-dp[j])+q[face]*(a/(a+b)*dk[i]/k[i]+b/(a+b)*dk[j]/k[j])
        if lam[i] > 0 and lam[j] > 0:
            a, b = dz[i]/(2*lam[i]), dz[j]/(2*lam[j])
            conductance = 1/(a+b)
            heat[face] = conductance*(offsets[i]-offsets[j])
            dh[face] = conductance*(dtemp[i]-dtemp[j])+heat[face]*(a/(a+b)*dl[i]/lam[i]+b/(a+b)*dl[j]/lam[j])
    b = event["bottom_water"]
    if b["kind"] == "free_drainage":
        q[-1], dq[-1] = k[-1], dk[-1]
        q_operands[-1] = k[-1]
    elif b["kind"] == "head":
        factor = 1-2*(b["head_m"]-psi[-1])/dz[-1]
        q[-1] = k[-1]*factor
        q_operands[-1] = k[-1]*(1+2*(abs(b["head_m"])+abs(psi[-1]))/dz[-1])
        dq[-1] = factor*dk[-1]+2*k[-1]/dz[-1]*dp[-1]
    for face, cell, name, sign in ((0, 0, "top_heat", 1), (-1, -1, "bottom_heat", -1)):
        b = event[name]
        if b["kind"] == "flux":
            heat[face] = b["value"]
        else:
            difference = sign*((b["value"]-tm)-offsets[cell])
            heat[face] = 2*lam[cell]/dz[cell]*difference
            dh[face] = 2/dz[cell]*(difference*dl[cell]-sign*lam[cell]*dtemp[cell])
    if "root_withdrawal_m_s" in event:
        root = np.asarray(event["root_withdrawal_m_s"])
        root_operands = np.abs(root)
        dr = np.zeros((n, 2*n))
    else:
        u = event["uptake"]
        a, b, c, d = (u[key] for key in ("dry_zero_head_m", "dry_full_head_m", "wet_full_head_m", "wet_zero_head_m"))
        stress, slope, stress_operands = np.zeros(n), np.zeros(n), np.zeros(n)
        for i, p in enumerate(psi):
            if a < p < b:
                stress[i], slope[i] = (p-a)/(b-a), 1/(b-a)
                stress_operands[i] = (abs(p)+abs(a)+stress[i]*(abs(b)+abs(a)))/(b-a)
            elif b <= p <= c:
                stress[i] = 1.
                stress_operands[i] = 1.
            elif c < p < d:
                stress[i], slope[i] = (d-p)/(d-c), -1/(d-c)
                stress_operands[i] = (abs(d)+abs(p)+stress[i]*(abs(d)+abs(c)))/(d-c)
        potential = event["potential_root_demand_m_s"]*np.asarray(u["weights"])
        root, dr = potential*stress, (potential*slope)[:, None]*dp
        root_operands = potential*stress_operands
    adv, da = np.zeros(n+1), np.zeros((n+1, 2*n))
    for face in range(n+1):
        if face == 0 and q[face] >= 0:
            offset, dt = event["surface_water_temperature_k"]-tm, np.zeros(2*n)
        elif face == n and q[face] < 0:
            offset, dt = event["bottom_water"]["temperature_k"]-tm, np.zeros(2*n)
        else:
            donor = face-1 if q[face] >= 0 else face
            # Zero external bottom flow uses the soil donor, not an invented
            # boundary temperature on the noflow/free-drainage records.
            donor = min(max(donor, 0), n-1)
            offset, dt = offsets[donor], dtemp[donor]
        specific = latent+cw*offset
        adv[face] = rho*q[face]*specific
        da[face] = rho*(specific*dq[face]+q[face]*cw*dt)
    specific = latent+cw*offsets
    root_energy = rho*root*specific
    dre = rho*(specific[:, None]*dr+(root*cw)[:, None]*dtemp)
    arrays = (q, heat, adv, root, root_energy, dq, dh, da, dr, dre, q_operands, root_operands)
    if not all(np.all(np.isfinite(x)) for x in arrays):
        raise ConstitutiveDomainError("unrepresentable face flux/Jacobian")
    return {"water": q, "heat": heat, "advection": adv, "root": root, "root_energy": root_energy,
            "water_roundoff_operands": q_operands, "root_roundoff_operands": root_operands,
            "water_jac": dq, "heat_jac": dh, "advection_jac": da, "root_jac": dr, "root_energy_jac": dre}


def _changes(model, old, new, old_t, new_t, *, old_offset=None, new_offset=None):
    c = model["constants"]
    rho, cw, ci, latent, tm, _ = (c[k] for k in CONSTANTS)
    dz = np.asarray([l["thickness_m"] for l in model["layers"]])
    dw = _content_difference(new["theta"], new["theta_deficit"], old["theta"], old["theta_deficit"])
    dl = _content_difference(new["liquid"], new["liquid_deficit"], old["liquid"], old["liquid_deficit"])
    old_offset = np.asarray(old_t)-tm if old_offset is None else np.asarray(old_offset)
    new_offset = np.asarray(new_t)-tm if new_offset is None else np.asarray(new_offset)
    # Algebraically Enew-Eold, without subtracting two large latent stores.
    de = dz*(new["capacity"]*(new_offset-old_offset)+rho*(ci*dw+(cw-ci)*dl)*old_offset+rho*latent*dl)
    return dw*dz, de


def _project_endpoint(model, head, temperature, props, rates, event, controls,
                      remaining_evaluations, *, temperature_offset):
    """Restore the PK saturated DAE endpoint, NOT its historical BE stage.

    A step that finishes filling a rigid pore has a mean integration pressure,
    while its zero-storage endpoint pressure satisfies instantaneous continuity.
    Solve that algebraic constraint at fixed inventories/temperature, including
    all saturated neighbours. Never replace already integrated face transfers.
    The 128-epsilon gate uses actual Darcy/root operand magnitudes before
    pressure cancellation, not |net flux| or a dt-scaled storage tolerance.
    """
    h = np.asarray(head).copy()
    active = np.flatnonzero((h >= 0.) & (props["theta_deficit"] == 0.)) if model.get("freezing_model", DALL_AMICO) == PAINTER_KARRA else np.array([], dtype=int)
    diagnostic = {"semantics": "FIXED_INVENTORY_INSTANTANEOUS_SATURATED_PRESSURE",
                  "layer_indices": active.tolist(), "evaluations": 0,
                  "integration_head_m": h[active].tolist(), "endpoint_head_m": h[active].tolist(),
                  "flux_residual_m_s": [], "flux_roundoff_limit_m_s": [],
                  "state_correction_ratio": 0.}
    if len(active) == 0:
        return h, props, diagnostic
    original = props
    nfev = 0
    while True:
        q, root = rates["water"], rates["root"]
        residual = np.asarray([math.fsum((q[i], -q[i+1], -root[i])) for i in active])
        qo, ro = rates["water_roundoff_operands"], rates["root_roundoff_operands"]
        magnitude = np.asarray([math.fsum((qo[i], qo[i+1], ro[i])) for i in active])
        limit = 128.*np.finfo(float).eps*magnitude
        jac = (rates["water_jac"][:-1]-rates["water_jac"][1:]-rates["root_jac"])[np.ix_(active, active)]
        rows = np.max(np.abs(jac), axis=1)
        if np.any(rows == 0.):
            raise ValueError("saturated endpoint pressure system is rank deficient")
        scaled = jac/rows[:, None]
        columns = np.linalg.norm(scaled, axis=0)
        if np.any(columns == 0.) or np.linalg.matrix_rank(scaled/columns) < len(active):
            raise ValueError("saturated endpoint pressure system is rank deficient")
        correction = np.linalg.solve(scaled, residual/rows)
        allowance = controls["head_atol_m"]+controls["relative_tolerance"]*np.abs(h[active])
        correction_ratio = float(np.max(np.abs(correction)/allowance))
        if np.all(np.abs(residual) <= limit) and correction_ratio <= .01:
            diagnostic.update(evaluations=nfev, endpoint_head_m=h[active].tolist(),
                              flux_residual_m_s=residual.tolist(), flux_roundoff_limit_m_s=limit.tolist(),
                              state_correction_ratio=correction_ratio)
            return h, props, diagnostic
        candidate = h.copy()
        candidate[active] -= correction
        if not np.all(np.isfinite(candidate)) or np.any(candidate[active] < 0.) or np.any(candidate[active] >= controls["max_head_m"]) or np.any(candidate[active] <= controls["min_head_m"]):
            raise ValueError("saturated endpoint projection leaves its nonnegative pressure branch/bounds")
        if nfev >= remaining_evaluations:
            raise ValueError("saturated endpoint projection exhausted remaining nonlinear evaluation budget")
        nfev += 1
        projected = _properties(model, candidate, temperature, temperature_offset=temperature_offset)
        for key in ("theta", "liquid", "ice", "energy", "theta_deficit", "liquid_deficit"):
            if not np.array_equal(projected[key], original[key]):
                raise ValueError("saturated endpoint projection changed a conserved/phase inventory")
        # Reevaluate every actual active branch, including surface exfiltration
        # and Feddes withdrawal. No negative-pressure clamp or stale Jacobian.
        rates = _rates(model, projected, temperature, event, temperature_offset=temperature_offset)
        h, props = candidate, projected


def _step(model, head, temperature, dt, event, controls, *, temperature_offset=None):
    n = len(head)
    tm = model["constants"]["melting_temperature_k"]
    dz = np.asarray([l["thickness_m"] for l in model["layers"]])
    offsets = np.asarray(temperature)-tm if temperature_offset is None else np.asarray(temperature_offset)
    old = _properties(model, head, temperature, temperature_offset=offsets)
    scale = np.r_[np.full(n, controls["nonlinear_water_atol_m"]), np.full(n, controls["nonlinear_energy_atol_j_m2"])]
    # At most 2*max_steps halfsteps can enter one event. Allocate half its
    # declared column balance budget to nonlinear residuals, leaving half for
    # accumulation arithmetic. This only TIGHTENS the old local gates; it does
    # not demand impossible zero residuals on individual nanometre faces.
    column_water_limit = min(controls["nonlinear_water_atol_m"], controls["water_atol_m"]/(4*controls["max_steps"]))
    def column_score(residual):
        value = abs(math.fsum(residual[:n]))
        return value/column_water_limit if column_water_limit else (math.inf if value else 0.)
    lower = np.r_[np.full(n, controls["min_head_m"]), np.full(n, controls["min_temperature_k"]-tm)]
    upper = np.r_[np.full(n, controls["max_head_m"]), np.full(n, controls["max_temperature_k"]-tm)]
    last_x, last_value, evaluation_count = None, None, 0
    def evaluate(x):
        nonlocal last_x, last_value, evaluation_count
        if last_x is not None and np.array_equal(last_x, x):
            return last_value
        if evaluation_count >= controls["max_nonlinear_evaluations"]:
            raise ValueError("nonlinear residual evaluation budget exhausted")
        evaluation_count += 1
        p = _properties(model, x[:n], x[n:]+tm, temperature_offset=x[n:], permit_frozen_positive=True)
        rates = _rates(model, p, x[n:]+tm, event, temperature_offset=x[n:])
        dw, de = _changes(model, old, p, temperature, x[n:]+tm, old_offset=offsets, new_offset=x[n:])
        residual = np.r_[dw-dt*(rates["water"][:-1]-rates["water"][1:]-rates["root"]),
                         de-dt*((rates["heat"]+rates["advection"])[:-1]-(rates["heat"]+rates["advection"])[1:]-rates["root_energy"])]
        jac = np.zeros((2*n, 2*n))
        jac[np.arange(n), np.arange(n)] = dz*p["theta_h"]
        jac[np.arange(n), n+np.arange(n)] = dz*p["theta_t"]
        jac[n+np.arange(n), np.arange(n)] = p["energy_h"]
        jac[n+np.arange(n), n+np.arange(n)] = p["energy_t"]
        jac[:n] -= dt*(rates["water_jac"][:-1]-rates["water_jac"][1:]-rates["root_jac"])
        e_jac = rates["heat_jac"]+rates["advection_jac"]
        jac[n:] -= dt*(e_jac[:-1]-e_jac[1:]-rates["root_energy_jac"])
        last_x, last_value = x.copy(), (residual, jac, p, rates)
        return last_value
    start = np.r_[head, offsets]
    try:
        def inspected(x):
            r, j, _, _ = evaluate(x)
            correction = np.linalg.solve(j/scale[:, None], r/scale)
            allowances = np.r_[controls["head_atol_m"]+controls["relative_tolerance"]*np.abs(x[:n]),
                                controls["temperature_atol_k"]+controls["relative_tolerance"]*np.abs(x[n:])]
            ratio = float(np.max(np.abs(correction)/allowances))
            return correction, max(float(np.max(np.abs(r)/scale)), ratio/.01, column_score(r)), last_value
        x, score, newton_evaluations = start.copy(), math.inf, 0
        # A valid saturated PK pressure is already on an admissible surface
        # branch. A stiff thermal trust-region search can leave that branch
        # and manufacture a nearly unanchored pressure system. First attempt
        # at most four ordinary Newton updates of the SAME coupled equations.
        # Bounds/domain failures or non-improvement fall back to trust-region
        # search with the remaining real evaluation budget, never a new budget.
        if model.get("freezing_model", DALL_AMICO) == PAINTER_KARRA and np.any((np.asarray(head) >= 0.) & (old["theta_deficit"] == 0.)):
            try:
                correction, score, accepted_evaluation = inspected(x)
                for _ in range(4):
                    if score <= 1 or evaluation_count >= controls["max_nonlinear_evaluations"]:
                        break
                    candidate = x-correction
                    if not np.all(np.isfinite(candidate)) or not np.all(candidate > lower) or not np.all(candidate < upper):
                        break
                    trial_correction, trial_score, trial_evaluation = inspected(candidate)
                    if not math.isfinite(trial_score) or trial_score >= score:
                        break
                    x, correction, score, accepted_evaluation = candidate, trial_correction, trial_score, trial_evaluation
            except (ConstitutiveDomainError, ValueError, FloatingPointError, OverflowError, np.linalg.LinAlgError):
                # Only a candidate failed; x still denotes the last valid
                # improved seed. No failed evaluation becomes an accepted tuple.
                score = math.inf
            newton_evaluations = evaluation_count
        if score <= 1:
            solver_success, solver_status = True, "NEWTON_CONVERGED"
        else:
            remaining = controls["max_nonlinear_evaluations"]-evaluation_count
            if remaining <= 0:
                return None, "nonlinear residual evaluation budget exhausted"
            solved = least_squares(lambda x: evaluate(x)[0]/scale, x,
                jac=lambda x: evaluate(x)[1]/scale[:, None], bounds=(lower, upper), x_scale="jac",
                ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=remaining)
            x = solved.x.copy()
            solver_success = bool(solved.success)
            solver_status = "TRUST_REGION_SUCCEEDED" if solver_success else "TRUST_REGION_FAILED"
            correction, score, accepted_evaluation = inspected(x)
        # Polish the SAME equations after trust-region stopping if physical
        # residuals/corrections still require it. Both paths retain their actual
        # solver status and face exactly the same final acceptance gates below.
        extra = 0
        budget = min(24, controls["max_nonlinear_evaluations"]-evaluation_count)
        while score > 1 and extra < budget:
            factor, improved = 1., False
            while factor >= 2**-12 and extra < budget:
                candidate = x-factor*correction
                if np.all(candidate > lower) and np.all(candidate < upper):
                    extra += 1
                    trial_correction, trial_score, trial_evaluation = inspected(candidate)
                    if math.isfinite(trial_score) and trial_score < score:
                        x, correction, score = candidate, trial_correction, trial_score
                        accepted_evaluation = trial_evaluation
                        improved = True
                        break
                factor /= 2
            if not improved:
                break
        # A rejected last candidate may own the one-entry evaluation cache.
        # Reuse the retained accepted tuple, rather than spending an unreported
        # extra residual evaluation after the declared work budget is exhausted.
        residual, jac, p, rates = accepted_evaluation
        # Inspect the PHYSICAL balance and pressure/temperature correction, not
        # the optimizer's success label or a small integrated residual alone.
        scaled_jac = jac/scale[:, None]
        columns = np.linalg.norm(scaled_jac, axis=0)
        if np.any(columns == 0) or np.linalg.matrix_rank(scaled_jac/columns) < 2*n:
            return None, "pressure/thermal system is rank deficient"
        correction = np.linalg.solve(scaled_jac, residual/scale)
        h, t = x[:n], x[n:]+tm
        allowance = np.r_[controls["head_atol_m"]+controls["relative_tolerance"]*np.abs(h),
                          controls["temperature_atol_k"]+controls["relative_tolerance"]*np.abs(x[n:])]
        correction_ratio = float(np.max(np.abs(correction)/allowance))
        if not solver_success or not np.all(np.isfinite(residual)) or np.max(np.abs(residual)/scale) > 1 or correction_ratio > .01:
            return None, "nonlinear balance or state-correction tolerance failed"
        if column_score(residual) > 1:
            return None, "nonlinear column water residual allocation failed"
        if np.any(x <= lower) or np.any(x >= upper):
            return None, "numerical state bound reached"
        _properties(model, h, t, temperature_offset=x[n:])  # Enforce phase/pressure scope.
        h, p, projection = _project_endpoint(model, h, t, p, rates, event, controls,
            controls["max_nonlinear_evaluations"]-evaluation_count, temperature_offset=x[n:])
        evaluation_count += projection["evaluations"]
        return {"head": h, "temperature": t, "temperature_offset": x[n:].copy(), "props": p, "water_storage": p["theta"]*dz,
                "water": dt*rates["water"], "heat": dt*rates["heat"], "advection": dt*rates["advection"],
                "root": dt*rates["root"], "root_energy": dt*rates["root_energy"],
                "water_residual": residual[:n], "energy_residual": residual[n:],
                "column_water_residual": math.fsum(residual[:n]),
                "nfev": evaluation_count, "correction_ratio": correction_ratio,
                "solver_status": solver_status, "warm_start_newton_evaluations": newton_evaluations,
                "endpoint_pressure_projection": projection}, None
    except (ConstitutiveDomainError, ValueError, FloatingPointError, OverflowError, np.linalg.LinAlgError) as error:
        return None, str(error)


def _errors(full, first, second, controls, tm):
    rtol = controls["relative_tolerance"]
    components = {}
    def compare(label, a, b, atol):
        a, b = np.asarray(a), np.asarray(b)
        ratios = np.abs(a-b)/(atol+rtol*np.maximum(np.abs(a), np.abs(b)))
        components[label] = {"ratio": float(np.max(ratios)), "index": int(np.argmax(ratios)),
                             "absolute_difference": float(np.max(np.abs(a-b)))}
    compare("head_m", full["head"], second["head"], controls["head_atol_m"])
    compare("temperature_k", full["temperature_offset"], second["temperature_offset"], controls["temperature_atol_k"])
    for key in ("theta", "liquid", "ice"):
        compare(key, full["props"][key], second["props"][key], controls["water_fraction_atol"])
    compare("water_storage_m", full["water_storage"], second["water_storage"], controls["water_atol_m"])
    compare("enthalpy_j_m2", full["props"]["energy"], second["props"]["energy"], controls["energy_atol_j_m2"])
    for key in ("water", "heat", "advection", "root", "root_energy"):
        atol = controls["water_atol_m"] if key in ("water", "root") else controls["energy_atol_j_m2"]
        compare(key+"_integral", full[key], first[key]+second[key], atol)
        # Net cancellation must not hide opposite-direction transfers.
        compare(key+"_positive_integral", np.maximum(full[key], 0), np.maximum(first[key], 0)+np.maximum(second[key], 0), atol)
        compare(key+"_negative_integral", np.minimum(full[key], 0), np.minimum(first[key], 0)+np.minimum(second[key], 0), atol)
    worst = max(components, key=lambda k: components[k]["ratio"])
    return components[worst]["ratio"], components, worst


def _accepted_step_proposal(dt, error_ratio, controls):
    """BE local step-doubling error is O(dt²); target .9² of its allowance.

    This proposes work, never accepts it: all actual state/flux/conservation
    gates and the unchanged rejected-step policy still apply to every trial.
    """
    if not math.isfinite(error_ratio) or not 0 <= error_ratio <= 1:
        raise ValueError("accepted finite temporal error ratio required")
    factor = 2. if error_ratio == 0 else min(2., .9/math.sqrt(error_ratio))
    return max(controls["min_step_s"], min(controls["max_step_s"], dt*factor))


def advance(model, state, event, controls):
    """Advance ONE constant-forcing event; failure exposes only accepted prefix.

    Invalid/tampered schemas raise ValueError. UNKNOWN inputs return UNKNOWN.
    Numerical/constitutive failure returns final_state=None and an independently
    usable last_accepted_state, NEVER a failed trial relabelled as success.
    """
    base = {"schema": SCHEMA, "status": None, "final_state": None,
            "initial_state": deepcopy(state), "last_accepted_state": deepcopy(state),
            "ledger": None, "accepted_steps": [], "reason": None,
            "physical_acceptance": False, "assumptions": list(ASSUMPTIONS), "primary_source": SOURCE}
    try:
        n = _model(model)
        _event(event, n)
    except UnknownInput as error:
        return {**base, "status": "UNKNOWN", "source_status": "UNKNOWN", "reason": str(error),
                "last_accepted_state": None}
    _controls(controls, model)
    head, temperature, offsets = _read_state(model, state)
    tm = model["constants"]["melting_temperature_k"]
    if any(not controls["min_head_m"] < x < controls["max_head_m"] for x in head) or any(not controls["min_temperature_k"]-tm < x < controls["max_temperature_k"]-tm for x in offsets):
        raise ValueError("initial state outside explicitly supplied numerical bounds")
    provenance_records = [model, *model["layers"], event, event["top_heat"], event["bottom_heat"], event["bottom_water"]]
    if "uptake" in event and "source_status" in event["uptake"]:
        provenance_records.append(event["uptake"])
    source_status = "SYNTHETIC TEST" if all(x["source_status"] == "SYNTHETIC TEST" for x in provenance_records) else "WORKING NON-CANON"
    base.update(source_status=source_status, model_sha256=model_digest(model))
    law = model.get("freezing_model", DALL_AMICO)
    base.update(freezing_model=law, head_semantics="LIQUID_PRESSURE_HEAD" if law == PAINTER_KARRA else "TOTAL_WATER_RETENTION_HEAD_AND_UNFROZEN_SATURATED_PRESSURE")
    if law == PAINTER_KARRA:
        base["primary_source"] = PAINTER_KARRA_SOURCE
        base["assumptions"][1] = "Painter--Karra apparent-pore Eq15/18--19; explicit supplied beta; omega=1/beta."
        base["assumptions"][2] = "Primary liquid pressure remains an independent saturated variable; no added compressibility."
        base["assumptions"].append("Saturated endpoint pressure satisfies instantaneous continuity at fixed inventories; historical backward-Euler flux/root/energy integrals are unchanged.")
    initial_t, initial_offsets = temperature.copy(), offsets.copy()
    original = _properties(model, head, temperature, temperature_offset=offsets)
    dz = np.asarray([l["thickness_m"] for l in model["layers"]])
    totals = {k: np.zeros(n if k in ("root", "root_energy", "water_residual", "energy_residual") else n+1)
              for k in ("water", "heat", "advection", "root", "root_energy", "water_residual", "energy_residual")}
    down, up = np.zeros(n+1), np.zeros(n+1)
    time, dt, attempts, rejected = 0., controls["initial_step_s"], 0, 0
    accepted_rows, last_trial = [], None
    rain_excess_terms = []
    def finish(status, reason=None):
        current = _properties(model, head, temperature, temperature_offset=offsets)
        dw, de = _changes(model, original, current, initial_t, temperature, old_offset=initial_offsets, new_offset=offsets)
        water_residual = dw-(totals["water"][:-1]-totals["water"][1:]-totals["root"])
        eface = totals["heat"]+totals["advection"]
        energy_residual = de-(eface[:-1]-eface[1:]-totals["root_energy"])
        # Both signed and gross face transfers remain visible. Rain which never
        # entered the soil carries its own incoming-liquid enthalpy into runoff.
        rain = event["surface_water_flux_m_s"]*time
        rain_excess = math.fsum(rain_excess_terms)
        c = model["constants"]
        rain_h = c["water_density_kg_m3"]*(c["latent_heat_j_kg"]+c["water_heat_capacity_j_kg_k"]*(event["surface_water_temperature_k"]-c["melting_temperature_k"]))
        ledger = {"elapsed_s": time, "initial_storage_m": float(math.fsum(original["theta"]*dz)),
                  "final_storage_m": float(math.fsum(current["theta"]*dz)),
                  "initial_enthalpy_j_m2": float(math.fsum(original["energy"])),
                  "final_enthalpy_j_m2": float(math.fsum(current["energy"])),
                  "storage_change_m": float(math.fsum(dw)), "enthalpy_change_j_m2": float(math.fsum(de)),
                  "surface_input_m": rain, "infiltration_m": float(down[0]),
                  "surface_input_representation_residual_m": rain-float(down[0])-rain_excess,
                  "rain_excess_runoff_m": rain_excess, "surface_exfiltration_m": float(up[0]),
                  "surface_runoff_m": rain_excess+float(up[0]), "rain_excess_enthalpy_j_m2": rain_excess*rain_h,
                  "bottom_downward_m": float(down[-1]), "bottom_upward_m": float(up[-1]),
                  "root_withdrawal_m": float(math.fsum(totals["root"])),
                  "root_enthalpy_j_m2": float(math.fsum(totals["root_energy"])),
                  "face_water_m": totals["water"].tolist(), "face_downward_m": down.tolist(), "face_upward_m": up.tolist(),
                  "face_conductive_energy_j_m2": totals["heat"].tolist(),
                  "face_advective_energy_j_m2": totals["advection"].tolist(),
                  "water_residual_m": float(math.fsum(water_residual)),
                  "energy_residual_j_m2": float(math.fsum(energy_residual)),
                  "layers": [{"layer_id": layer["layer_id"], "thickness_m": layer["thickness_m"],
                              "initial_water_m": float(original["theta"][i]*dz[i]), "final_water_m": float(current["theta"][i]*dz[i]),
                              "water_change_m": float(dw[i]), "enthalpy_change_j_m2": float(de[i]),
                              "root_withdrawal_m": float(totals["root"][i]), "root_enthalpy_j_m2": float(totals["root_energy"][i]),
                              "water_residual_m": float(water_residual[i]), "energy_residual_j_m2": float(energy_residual[i])}
                             for i, layer in enumerate(model["layers"])]}
        accepted_state = _state(model, head, temperature, state["elapsed_seconds"]+time, temperature_offset=offsets)
        return {**base, "status": status, "reason": reason,
                "final_state": deepcopy(accepted_state) if status == "MODELLED" else None,
                "last_accepted_state": accepted_state, "ledger": ledger, "accepted_steps": deepcopy(accepted_rows),
                "numerics": {"method": "FULLY_COUPLED_BACKWARD_EULER_TWO_HALF_STEPS", "attempts": attempts,
                             "nonlinear_column_water_atol_m": min(controls["nonlinear_water_atol_m"], controls["water_atol_m"]/(4*controls["max_steps"])),
                             "rejected_trials": rejected, "accepted_steps": len(accepted_rows), "last_trial": deepcopy(last_trial),
                             "accepted_step_proposal": "0.9/sqrt(error_ratio), growth capped at 2, clipped to declared step bounds",
                             "controls": deepcopy(controls), "residual_interpretation": "actual binary64 residuals, not zeroed; local temporal estimates are not global error bounds"}}
    duration = event["duration_s"]
    while time < duration:
        if attempts >= controls["max_steps"]:
            return finish("NUMERICAL_FAILURE", "adaptive work budget exhausted")
        attempts += 1
        dt = min(dt, duration-time)
        if dt <= 0 or time+dt == time or state["elapsed_seconds"]+time+dt == state["elapsed_seconds"]+time:
            return finish("NUMERICAL_FAILURE", "time increment unrepresentable")
        full, fwhy = _step(model, head, temperature, dt, event, controls, temperature_offset=offsets)
        first, awhy = _step(model, head, temperature, dt/2, event, controls, temperature_offset=offsets)
        second, bwhy = (None, "first half failed") if first is None else _step(model, first["head"], first["temperature"], dt/2, event, controls, temperature_offset=first["temperature_offset"])
        ratio, components, worst = None, None, None
        if all(x is not None for x in (full, first, second)):
            ratio, components, worst = _errors(full, first, second, controls, model["constants"]["melting_temperature_k"])
        last_trial = {"start_s": time, "step_s": dt, "error_ratio": ratio, "error_components": components,
                      "worst_component": worst, "solve_failures": {"full": fwhy, "first_half": awhy, "second_half": bwhy}}
        if ratio is None or ratio > 1:
            rejected += 1
            if dt/2 < controls["min_step_s"]:
                return finish("NUMERICAL_FAILURE", "nonlinear/constitutive gate failed at minimum step" if ratio is None else "temporal accuracy gate failed at minimum step")
            dt /= 2
            continue
        # Gate cumulative layer AND column residuals before promoting the two
        # half steps. Failed tentative state and transfers never enter a prefix.
        prospective = {k: totals[k]+first[k]+second[k] for k in totals}
        dw, de = _changes(model, original, second["props"], initial_t, second["temperature"], old_offset=initial_offsets, new_offset=second["temperature_offset"])
        wr = dw-(prospective["water"][:-1]-prospective["water"][1:]-prospective["root"])
        ef = prospective["heat"]+prospective["advection"]
        er = de-(ef[:-1]-ef[1:]-prospective["root_energy"])
        if not np.all(np.isfinite(wr)) or not np.all(np.isfinite(er)) or max(float(np.max(np.abs(wr))), abs(math.fsum(wr))) > controls["water_atol_m"] or max(float(np.max(np.abs(er))), abs(math.fsum(er))) > controls["energy_atol_j_m2"]:
            return finish("NUMERICAL_FAILURE", "cumulative finite-volume water/enthalpy residual gate failed")
        totals = prospective
        rain_excess_terms.extend((event["surface_water_flux_m_s"]*dt/2-max(float(step["water"][0]), 0.)) for step in (first, second))
        down += np.maximum(first["water"], 0)+np.maximum(second["water"], 0)
        up += np.maximum(-first["water"], 0)+np.maximum(-second["water"], 0)
        head, temperature, offsets = second["head"], second["temperature"], second["temperature_offset"]
        time = duration if dt == duration-time else time+dt
        accepted_row = {"end_s": time, "step_s": dt, "error_ratio": ratio, "worst_component": worst,
                              "maximum_layer_water_residual_m": float(np.max(np.abs(first["water_residual"])+np.abs(second["water_residual"]))),
                              "maximum_substep_column_water_residual_m": max(abs(x["column_water_residual"]) for x in (full, first, second)),
                              "maximum_layer_energy_residual_j_m2": float(np.max(np.abs(first["energy_residual"])+np.abs(second["energy_residual"]))),
                              "nonlinear_evaluations": sum(x["nfev"] for x in (full, first, second)),
                              "warm_start_newton_evaluations": sum(x["warm_start_newton_evaluations"] for x in (full, first, second)),
                              "solver_statuses": [x["solver_status"] for x in (full, first, second)],
                              "maximum_state_correction_ratio": max(x["correction_ratio"] for x in (full, first, second))}
        active_projections = {name: step["endpoint_pressure_projection"] for name, step in (("full", full), ("first_half", first), ("second_half", second)) if step["endpoint_pressure_projection"]["layer_indices"]}
        if active_projections:
            accepted_row["endpoint_pressure_projection"] = active_projections
        accepted_rows.append(accepted_row)
        dt = _accepted_step_proposal(dt, ratio, controls)
    return finish("MODELLED")
