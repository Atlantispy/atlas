"""I01 MC-07: water-loaded, flexed columns -> gravitational driving potential and traction.

WORKING NON-CANON. Planar periodic join of the retained dry GPE columns and the retained
finite-water/flexure equilibrium, with no second Airy rebalance and no second water load.
Finite-rigidity joins are conditional on a declared shear-transfer depth; none is assumed.
Not I04 world sampling or I08 regional/global support.
Run: python -B tectonics/tools/check_i01_water_gpe.py --output NEW.json
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy

import check_i01_gpe as gpe                  # retained dry columns (imports the D1 torque helpers)
import check_i01_closures as closures        # bound because the GPE helper imports it; not called here
import check_i01_water_flexure as water      # retained periodic plate and finite connected water

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "atlas.water-loaded-gpe.v1"
EVIDENCE_SCHEMA = "atlas.i01-water-gpe.v1"
CASE_SCHEMA = "atlas.i01-water-gpe-case.v1"
CASE = "cases/i01_water_gpe_v1.json"
PASS = "PASS_BOUNDED_CONTROLS_ONLY"
NEW_FILES = ("tools/check_i01_water_gpe.py", "cases/i01_water_gpe_v1.json",
             "docs/I01_WATER_GPE.md", "tests/test_i01_water_gpe.py")
RETAINED = ("tools/check_i01_gpe.py", "tools/check_i01_closures.py", "tools/check_i01_water_flexure.py",
            "cases/i01_gpe_v1.json", "cases/i01_water_flexure_v1.json")
# Digests of the retained producers' receipts, copied from the evidence register (not recomputed here).
ACCEPTED_RECEIPTS = {
    "evidence/i01-gpe-r1.json": "bfd5ddbaa6a204ca156b9d94b981269fb9ce0956bb5ec37d1fd111b6c248e4fd",
    "evidence/i01-water-flexure-r1.json": "6e22ad6d509520eaefb30f2ddcba1eea2957770ce3c4f33e78aabe712b6c3932",
}
IMPORTED = {"tools/check_i01_gpe.py": gpe, "tools/check_i01_closures.py": closures,
            "tools/check_i01_water_flexure.py": water}
GPE_KEYS = ("datum", "reduction", "crust_density_kg_m3", "mean_crust_m")
WATER_KEYS = ("plate", "mean_depth_m", "grids")
CASE_FIELDS = {"schema", "status", "contract", "document", "policy", "retained", "controls", "source"}
# Frozen before execution; cases/i01_water_gpe_v1.json must carry exactly this policy.
POLICY = {
    "force_relative_tolerance": 1e-7,         # = retained water force tolerance
    "volume_relative_tolerance": 1e-11,       # = retained water volume tolerance
    "state_tolerance_m": 1e-6,                # = retained water RMS target: reference-bed and depth consistency
    "closed_form_displacement_m": 2e-6,       # retained oblique-mode test tolerance
    "translated_displacement_m": 1e-7,
    "quadrature_fraction_of_reference": 1e-12,
    "operator_relative": 1e-12,
    "discrimination_factor": 1000.0,
    "gauss_order": 3,
    "quadrature_sample_stride": 16,
    "timing_repetitions": 5,
    "maximum_seconds": 60.0,
}
COMPENSATED = "COMPENSATED"
FLEXURAL = "FLEXURAL_CONDITIONAL_SHEAR_LEVEL"
UNSUPPORTED = "REFUSED_UNSUPPORTED_CONTRACT"
INVALID = "REFUSED_INVALID_INPUT"
COLUMNS = "REFUSED_INVALID_COLUMNS"
SHAPE = "REFUSED_SHAPE_SUPPORT_MISMATCH"
MATERIAL = "REFUSED_MATERIAL_MISMATCH"
WATER_IN_ROCK = "REFUSED_WATER_IN_ROCK_COLUMN"
REFERENCE = "REFUSED_REFERENCE_MISMATCH"
LOAD = "REFUSED_WATER_LOAD_MISMATCH"
EQUILIBRIUM = "REFUSED_NOT_FLEXURAL_EQUILIBRIUM"
UNDECLARED = "REFUSED_SHEAR_LEVEL_UNDECLARED"
OUTSIDE = "REFUSED_SHEAR_LEVEL_OUTSIDE_ROCK"
BELOW = "REFUSED_BELOW_DATUM"
NONFINITE = "REFUSED_NONFINITE"
NEGATIVE_WATER = "REFUSED_NEGATIVE_WATER_DEPTH"
# Structural no-load-transfer limits: B vanishes identically in the exact equilibrium (I01_WATER_GPE.md section 4).
ZERO_WATER, ZERO_RIGIDITY, UNIFORM_LOAD = "zero_water", "zero_rigidity", "uniform_load"


class Refusal(ValueError):
    """Explicit, atomic refusal: no result exists and no input has been modified."""

    def __init__(self, code, detail):
        super().__init__(code+": "+detail)
        self.code = code


def _grid(value, shape, name):
    a = np.asarray(value)
    if a.shape != shape or a.dtype.kind not in "fiu":
        raise Refusal(SHAPE, name+" must be a real grid of the plate shape")
    a = np.array(a, dtype=float, copy=True)
    if not np.all(np.isfinite(a)):
        raise Refusal(NONFINITE, name+" contains non-finite values")
    return a


def _shear_depth(declaration):
    """None, or the declared effective flexural shear-transfer depth below the loaded bed (m)."""
    if declaration is None:
        return None
    if not isinstance(declaration, Mapping) or set(declaration) != {"depth_below_bed_m", "basis"}:
        raise Refusal(INVALID, "a shear level declares exactly depth_below_bed_m and basis")
    if type(declaration["basis"]) is not str or not declaration["basis"].strip():
        raise Refusal(INVALID, "a nonempty shear-level basis is required")
    depth = declaration["depth_below_bed_m"]
    if isinstance(depth, (bool, str, bytes)) or np.ndim(depth) != 0:
        raise Refusal(INVALID, "shear-level depth must be a real scalar")
    depth = float(depth)
    if not math.isfinite(depth):
        raise Refusal(INVALID, "shear-level depth must be finite")
    return depth


def reference_top(datum):
    """Top of the common pure-mantle reference column, Z_ref = zc + P/(g rho_m)."""
    return datum.compensation_elevation_m+datum.pressure_pa/(datum.gravity_m_s2*datum.mantle_density_kg_m3)


def quadrature_tolerance(datum):
    """Absolute oracle tolerance: a fixed fraction of the reference integrated pressure P^2/(2 g rho_m)."""
    return POLICY["quadrature_fraction_of_reference"]*datum.pressure_pa**2/(
        2*datum.gravity_m_s2*datum.mantle_density_kg_m3)


def flexural_support(plate, displacement_m):
    """D biharmonic(w) in Pa, rebuilt from the plate's public rigidity and lengths.

    Used to authenticate a supplied equilibrium and report the plate's load transfer; never to solve, and
    never to class a state as compensated.
    """
    ny, nx = plate.shape
    kx = 2*np.pi*np.fft.rfftfreq(nx, plate.length_x_m/nx)
    ky = 2*np.pi*np.fft.fftfreq(ny, plate.length_y_m/ny)
    symbol = plate.rigidity_n_m*(kx[None, :]**2+ky[:, None]**2)**2
    return np.fft.irfft2(np.fft.rfft2(displacement_m)*symbol, s=plate.shape)


def water_loaded_gpe(datum, thickness_m, reference_density_kg_m3, alpha_per_k, bottom_temperature_k,
                     top_temperature_k, plate, water_state, *, volume_m3, geometry, connectivity,
                     shear_level=None):
    """Driving potential of water-loaded, flexed columns; never a second Airy rebalance or water load.

    The dry state is produced here by the retained columns(); columns are one per plate cell in (ny,nx)
    row-major order. water_state must be the total water/flexure equilibrium of THAT dry surface under
    this plate and finite volume; it is authenticated by its own equilibrium conditions, never by a
    status string. delta V = delta U0 + c B + g rho_m w (e0 - w/2) + g rho_w d^2/2 (I01_WATER_GPE.md).
    Only the structural limits (zero water, zero rigidity, an exactly flat dry surface) are compensated;
    every other state needs a declared shear level, however small its support. Negative depth is refused.
    """
    if geometry != "periodic_flat_plate" or connectivity != "one_communicating_reservoir":
        raise Refusal(UNSUPPORTED, "only the planar periodic, one-reservoir support is joined")
    if not isinstance(datum, gpe.Datum) or type(plate) is not water.Plate:
        raise Refusal(UNSUPPORTED, "the retained Datum and Plate types are required")
    if plate.rho_m_kg_m3 != datum.mantle_density_kg_m3 or plate.gravity_m_s2 != datum.gravity_m_s2:
        raise Refusal(MATERIAL, "plate and datum must share one mantle density and gravity")
    depth_c = _shear_depth(shear_level)
    try:
        dry = gpe.columns(datum, thickness_m, reference_density_kg_m3, alpha_per_k,
                          bottom_temperature_k, top_temperature_k)
    except ValueError as exc:
        raise Refusal(COLUMNS, str(exc)) from None
    shape = plate.shape
    h = np.asarray(thickness_m, dtype=float)
    if h.shape[0] != shape[0]*shape[1]:
        raise Refusal(SHAPE, "one column per plate cell, in (ny,nx) row-major order, is required")
    rho, alpha, tb, tt = (np.broadcast_to(gpe.real_array(v), h.shape) for v in (
        reference_density_kg_m3, alpha_per_k, bottom_temperature_k, top_temperature_k))
    tref, rho_w, g, rho_m = (datum.reference_temperature_k, plate.rho_w_kg_m3,
                             datum.gravity_m_s2, datum.mantle_density_kg_m3)
    lightest = min(float(np.min(rho*(1-alpha*(tb-tref)))), float(np.min(rho*(1-alpha*(tt-tref)))))
    if not lightest > rho_w:
        raise Refusal(WATER_IN_ROCK, "rock layers must be denser than water; water belongs to the finite reservoir")
    if not isinstance(water_state, Mapping) or not {"displacement_m", "bed_m", "depth_m", "sea_level_m"} <= set(water_state):
        raise Refusal(SHAPE, "a water/flexure equilibrium with displacement, bed, depth and sea level is required")
    w = _grid(water_state["displacement_m"], shape, "displacement")
    bed = _grid(water_state["bed_m"], shape, "loaded bed")
    d = _grid(water_state["depth_m"], shape, "water depth")
    if np.any(d < 0):                             # before any load, volume or mass account; never clipped
        raise Refusal(NEGATIVE_WATER, "water depth must be nonnegative in every cell, however small the deficit")
    level = water_state["sea_level_m"]
    try:
        volume = water.scalar(volume_m3, "volume")
    except ValueError as exc:
        raise Refusal(INVALID, str(exc)) from None
    tolerance = POLICY["state_tolerance_m"]
    z0 = dry["surface_elevation_m"].reshape(shape)
    reference_residual = float(np.max(np.abs(bed+w-z0)))
    if not reference_residual <= tolerance:
        raise Refusal(REFERENCE, "loaded bed plus displacement is not this dry surface (other unloaded bed, datum or order)")
    mean = volume/(plate.length_x_m*plate.length_y_m)
    if volume == 0:
        if level is not None or np.any(d != 0):
            raise Refusal(LOAD, "zero water has no sea level and no depth")
        depth_residual = volume_residual = 0.
    else:
        if (level is None or isinstance(level, (bool, str, bytes)) or np.ndim(level) != 0
                or not math.isfinite(float(level)) or not mean > 0):
            raise Refusal(LOAD, "finite water needs one finite communicating level and a representable amount")
        level = float(level)
        depth_residual = float(np.max(np.abs(d-np.maximum(level-bed, 0.))))
        volume_residual = abs(float(np.mean(d))-mean)/mean
        if not (depth_residual <= tolerance and volume_residual <= POLICY["volume_relative_tolerance"]):
            raise Refusal(LOAD, "depth is not the supplied level above the loaded bed, or the finite volume changed")
    support = flexural_support(plate, w)
    load = rho_w*g*d
    scale = max(1., float(np.linalg.norm(load)))
    force_residual = float(np.linalg.norm(support+plate.dry_k*w-load))/scale
    if not force_residual <= POLICY["force_relative_tolerance"]:
        raise Refusal(EQUILIBRIUM, "displacement is not the dry-restoring plate response to exactly this water load")
    support_relative = float(np.linalg.norm(support))/scale      # diagnostic only; never classifies
    # Admission above is numerical. The no-load-transfer class is structural, from independent inputs only:
    # B vanishes identically for zero water, zero rigidity or an exactly flat dry surface (uniform load).
    # A small support is still flexural: its L2 ratio to the load falls as uniform water is added.
    limit = (ZERO_WATER if volume == 0 else ZERO_RIGIDITY if plate.rigidity_n_m == 0
             else UNIFORM_LOAD if np.all(z0 == z0.flat[0]) else None)
    thickness = h.sum(axis=1).reshape(shape)
    if limit is None and depth_c is None:
        raise Refusal(UNDECLARED, "nonuniform finite-rigidity loading transfers load, however small; "
                                  "a declared shear-transfer depth is required and none is assumed")
    if depth_c is not None and not 0 < depth_c < float(np.min(thickness)):
        raise Refusal(OUTSIDE, "the declared shear-transfer level must lie strictly inside every rock column")
    fill = dry["mantle_fill_m"].reshape(shape)-w
    if not np.all(fill > 0):
        raise Refusal(BELOW, "a displaced column base reaches the compensation datum; use a deeper common datum")
    load_m = dry["effective_rock_load_kg_m2"].reshape(shape)
    e0 = thickness-load_m/rho_m                   # dry surface above the reference mantle top, no large numbers
    excess = g*(rho_w*d-rho_m*w)                  # B = overburden at the datum minus the uniform datum pressure
    c = 0. if depth_c is None else depth_c
    dry_anomaly = dry["gpe_anomaly_j_m2"].reshape(shape)
    anomaly = dry_anomaly+c*excess+g*rho_m*w*(e0-w/2)+.5*g*rho_w*d*d
    result = dict(
        contract=CONTRACT, regime=FLEXURAL if limit is None else COMPENSATED, no_transfer_limit=limit,
        shear_level=None if depth_c is None else dict(depth_below_bed_m=depth_c, basis=shear_level["basis"]),
        finite_rigidity_closure=False,
        gpe_anomaly_j_m2=anomaly, dry_gpe_anomaly_j_m2=dry_anomaly,
        basal_overburden_excess_pa=excess, flexural_support_pa=support,
        displacement_m=w, loaded_bed_m=bed, depth_m=d, sea_level_m=None if volume == 0 else level,
        top_surface_m=bed+d, dry_surface_m=z0, surface_above_reference_m=e0,
        reference_top_elevation_m=reference_top(datum), mantle_fill_m=fill,
        reference_rock_mass_kg_m2=dry["reference_rock_mass_kg_m2"].reshape(shape),
        effective_rock_load_kg_m2=load_m, water_mass_kg_m2=rho_w*d,
        reference_bed_residual_m=reference_residual, depth_residual_m=depth_residual,
        volume_relative_residual=volume_residual, force_relative_residual=force_residual,
        flexural_support_relative=support_relative,
        shear_level_sensitivity_bound_j_m2=float(np.max(thickness*np.abs(excess))))
    if not all(np.all(np.isfinite(v)) for v in result.values() if isinstance(v, (np.ndarray, float))):
        raise Refusal(NONFINITE, "water-loaded potential not representable")
    return result


def planar_traction(anomaly_j_m2, *, plate, reduction):
    """-reduction * grad V on the plate's periodic grid by second-order central differences, Pa.

    The last axis holds (x, y). A shoreline is a gradient kink in V: treated without spectral ringing,
    at first order locally. No ridge push or water push is added.
    """
    if type(plate) is not water.Plate:
        raise Refusal(UNSUPPORTED, "the retained Plate support is required")
    v = _grid(anomaly_j_m2, plate.shape, "GPE anomaly")
    try:
        gamma = gpe.number(reduction, "common L0/L", positive=True)
    except ValueError as exc:
        raise Refusal(INVALID, str(exc)) from None
    dx, dy = plate.length_x_m/plate.shape[1], plate.length_y_m/plate.shape[0]
    gx = (np.roll(v, -1, axis=1)-np.roll(v, 1, axis=1))/(2*dx)
    gy = (np.roll(v, -1, axis=0)-np.roll(v, 1, axis=0))/(2*dy)
    result = -gamma*np.stack((gx, gy), axis=-1)
    if not np.all(np.isfinite(result)):
        raise Refusal(NONFINITE, "traction not representable")
    return result


# ----------------------------------------------------------------------------- independent controls (not the join)

def independent_column_anomaly(datum, thickness_m, bottom_density_kg_m3, top_density_kg_m3, *, rho_w_kg_m3,
                               water_depth_m, displacement_m, split_depth_below_bed_m=None, order=None):
    """ONE column's explicit pressure profile integrated by Gauss quadrature, minus P^2/(2 g rho_m).

    Independent oracle: forms the geometry and pressure itself and never uses the join's algebra.
    Layers are bottom to top with linear effective density. Above the split, pressure is the overburden
    from the traction-free top; below it, hydrostatic from P at the datum. No split gives the overburden
    everywhere: the naive fixed-datum lithostatic anomaly delta U_o. Every return is an anomaly; absolute
    integrals, which gain a common reference term when the datum is deepened, are never compared.
    """
    g, rho_m = datum.gravity_m_s2, datum.mantle_density_kg_m3
    p0, zc = datum.pressure_pa, datum.compensation_elevation_m
    nodes, weights = np.polynomial.legendre.leggauss(POLICY["gauss_order"] if order is None else order)
    rule = list(zip(nodes.tolist(), weights.tolist()))

    def integral(lo, hi, piece):              # exact for linear density on [lo, hi] inside the piece
        b, t, db, dt = piece
        half, mid = (hi-lo)/2, (hi+lo)/2
        return half*math.fsum(wi*(db+(dt-db)*(mid+half*xi-b)/(t-b)) for xi, wi in rule)

    layers = [(float(h), float(rb), float(rt)) for h, rb, rt in
              zip(thickness_m, bottom_density_kg_m3, top_density_kg_m3)]
    mass = math.fsum(integral(0., h, (0., h, rb, rt)) for h, rb, rt in layers)
    z = zc+(p0/g-mass)/rho_m-float(displacement_m)
    pieces = [(zc, z, rho_m, rho_m)]
    for h, rb, rt in layers:
        pieces.append((z, z+h, rb, rt))
        z += h
    bed = z
    if water_depth_m > 0:
        pieces.append((bed, bed+float(water_depth_m), float(rho_w_kg_m3), float(rho_w_kg_m3)))
    split = None if split_depth_below_bed_m is None else bed-float(split_depth_below_bed_m)
    if split is not None:
        cut = []
        for b, t, db, dt in pieces:
            if b < split < t:
                ds = db+(dt-db)*(split-b)/(t-b)
                cut += [(b, split, db, ds), (split, t, ds, dt)]
            else:
                cut.append((b, t, db, dt))
        pieces = cut

    def pressure(zq):
        if split is None or zq > split:
            return g*math.fsum(integral(max(zq, p[0]), p[1], p) for p in pieces if p[1] > zq)
        return p0-g*math.fsum(integral(p[0], min(zq, p[1]), p) for p in pieces if p[0] < zq)

    total = math.fsum((t-b)/2*wi*pressure((t+b)/2+(t-b)/2*xi) for b, t, _, _ in pieces for xi, wi in rule)
    return total-p0*p0/(2*g*rho_m)


def fourier_mode_state(plate, dry_surface_m, *, mode, mean_water_m, bed_amplitude_m, surface_mean_m):
    """Closed-form fully wet equilibrium for dry surface = mean + a cos(theta) on the constant-D plate.

    w and d are the retained oblique-mode test solution; B follows from the plate equation. Independent
    of the solver; bed is taken from the actual dry surface so authentication sees one reference.
    """
    ny, nx = plate.shape
    mx, my = mode
    y, x = np.indices(plate.shape)
    cosine = np.cos(2*np.pi*(mx*x/nx+my*y/ny))
    k2 = (2*np.pi*mx/plate.length_x_m)**2+(2*np.pi*my/plate.length_y_m)**2
    lam = plate.rigidity_n_m*k2*k2+plate.dry_k
    cw = plate.rho_w_kg_m3*plate.gravity_m_s2
    q, a = plate.density_ratio, bed_amplitude_m
    w = q*mean_water_m-a*cw/(lam-cw)*cosine
    d = mean_water_m-a*lam/(lam-cw)*cosine
    return dict(displacement_m=w, bed_m=np.asarray(dry_surface_m, dtype=float)-w, depth_m=d,
                sea_level_m=float(surface_mean_m+(1-q)*mean_water_m),
                basal_overburden_excess_pa=-cw*a*plate.rigidity_n_m*k2*k2/(lam-cw)*cosine)


def water_layer_route(datum, columns_args, depth_m, rho_w_kg_m3):
    """The UNCHANGED dry helper with the water appended as a top layer: local Airy compensation.

    Valid only where the plate transfers no load (zero rigidity or uniform loading); elsewhere it is the
    forbidden re-float and serves only as a contrast. Returns (anomaly, top) per column in grid order.
    """
    h, rho, alpha, tb, tt = (np.broadcast_to(gpe.real_array(v), np.shape(columns_args[0])) for v in columns_args)
    d = np.asarray(depth_m, dtype=float).ravel()
    dry = gpe.columns(datum, *columns_args)
    anomaly, top = dry["gpe_anomaly_j_m2"].copy(), dry["surface_elevation_m"].copy()
    wet = d > 0
    if np.any(wet):
        extra = np.ones((int(wet.sum()), 1))
        aug = gpe.columns(datum, np.hstack((h[wet], d[wet, None])), np.hstack((rho[wet], extra*rho_w_kg_m3)),
                          np.hstack((alpha[wet], 0*extra)), np.hstack((tb[wet], extra*datum.reference_temperature_k)),
                          np.hstack((tt[wet], extra*datum.reference_temperature_k)))
        anomaly[wet], top[wet] = aug["gpe_anomaly_j_m2"], aug["surface_elevation_m"]
    return anomaly, top


def perturbation_bound(plate, result, depth_c, dw, dd):
    """Largest |delta V| change from displacement/depth perturbations dw, dd (m) at fixed columns."""
    g, rho_m, rho_w = plate.gravity_m_s2, plate.rho_m_kg_m3, plate.rho_w_kg_m3
    e0, w, d = (result[k] for k in ("surface_above_reference_m", "displacement_m", "depth_m"))
    return (g*rho_m*dw*(depth_c+float(np.max(np.abs(e0)))+float(np.max(np.abs(w)))+dw)
            + g*rho_w*dd*(depth_c+float(np.max(d))+dd))


def deepen(datum, delta_m):
    """The same mantle extended downward: datum lowered with the matching pressure increment."""
    return gpe.Datum(datum.pressure_pa+datum.mantle_density_kg_m3*datum.gravity_m_s2*delta_m,
                     datum.compensation_elevation_m-delta_m, datum.mantle_density_kg_m3,
                     datum.gravity_m_s2, datum.reference_temperature_k)


def translate(datum, shift_m):
    """Every elevation translated at fixed basal pressure."""
    return gpe.Datum(datum.pressure_pa, datum.compensation_elevation_m+shift_m, datum.mantle_density_kg_m3,
                     datum.gravity_m_s2, datum.reference_temperature_k)


def crust_columns(ret, surface_relative_m):
    """One retained-case crust layer whose dry surface is Z_ref + f h0 + surface_relative (f = 1 - rho_c/rho_m)."""
    rho_c, h0 = float(ret["crust_density_kg_m3"]), float(ret["mean_crust_m"])
    f = 1-rho_c/ret["datum"].mantle_density_kg_m3
    return ((h0+np.asarray(surface_relative_m, dtype=float)/f).reshape(-1, 1), rho_c, 0., 1000., 1000.)


def join(ret, columns_args, plate, state, volume, shear=None, datum=None):
    return water_loaded_gpe(ret["datum"] if datum is None else datum, *columns_args, plate, state,
                            volume_m3=volume, shear_level=shear, **water.ARGS)


def refusal_code(call):
    try:
        call()
    except Refusal as exc:
        return exc.code
    return None


def fingerprint(value):
    """Digest of nested inputs, to show that a refused call modified nothing."""
    hasher = hashlib.sha256()

    def feed(item):
        if isinstance(item, Mapping):
            for key in sorted(item, key=str):
                hasher.update(repr(key).encode())
                feed(item[key])
        elif isinstance(item, (list, tuple)):
            hasher.update(b"[")
            for entry in item:
                feed(entry)
            hasher.update(b"]")
        elif isinstance(item, np.ndarray):
            hasher.update(repr((item.dtype.str, item.shape)).encode())
            hasher.update(np.ascontiguousarray(item).tobytes())
        else:
            hasher.update(repr(item).encode())
    feed(value)
    return hasher.hexdigest()


def attempt(expected, datum, columns_args, plate, state, volume, shear, **contract):
    inputs = (datum, columns_args, plate, state, volume, shear)
    before = fingerprint(inputs)
    arguments = dict(water.ARGS, **contract)
    code = refusal_code(lambda: water_loaded_gpe(datum, *columns_args, plate, state, volume_m3=volume,
                                                 shear_level=shear, **arguments))
    return dict(expected=expected, code=code, refused_as_expected=code == expected,
                inputs_unchanged=before == fingerprint(inputs))


def check_deadline(deadline):
    if deadline is not None and time.perf_counter() > deadline:
        raise RuntimeError("cooperative time budget exhausted; nothing further run")


def finish(checks, **data):
    checks = {name: bool(value) for name, value in checks.items()}
    return dict(passed=all(checks.values()), checks=checks, **data)


def _span(values):
    values = np.asarray(values)
    return float(np.max(values)-np.min(values))


def _fixture(ret, n):
    plate, bed, volume = water.fixture(n, ret["water"])
    cols = crust_columns(ret, bed)
    z0 = gpe.columns(ret["datum"], *cols)["surface_elevation_m"].reshape(plate.shape)
    return plate, cols, z0, volume


# ----------------------------------------------------------------------------- campaign controls (frozen case)

def dry_parity_control(spec, ret, deadline=None):
    """Zero water through the retained solver: potential and traction bitwise equal to the dry helper."""
    check_deadline(deadline)
    n = ret["water"]["grids"][0]
    plate, cols, z0, _ = _fixture(ret, n)
    dry = gpe.columns(ret["datum"], *cols)
    r = join(ret, cols, plate, plate.equilibrium(z0, 0., **water.ARGS), 0.)
    t = planar_traction(r["gpe_anomaly_j_m2"], plate=plate, reduction=ret["reduction"])
    t_dry = planar_traction(dry["gpe_anomaly_j_m2"].reshape(plate.shape), plate=plate, reduction=ret["reduction"])
    return finish(dict(
        compensated=r["regime"] == COMPENSATED and r["no_transfer_limit"] == ZERO_WATER,
        potential_bitwise=np.array_equal(r["gpe_anomaly_j_m2"], dry["gpe_anomaly_j_m2"].reshape(plate.shape)),
        traction_bitwise=np.array_equal(t, t_dry),
        no_water_or_level=r["sea_level_m"] is None and not np.any(r["depth_m"]) and not np.any(r["displacement_m"]),
        reference_mass_unchanged=np.array_equal(r["reference_rock_mass_kg_m2"],
                                                dry["reference_rock_mass_kg_m2"].reshape(plate.shape))),
        cells=n*n, max_abs_traction_pa=float(np.max(np.abs(t))))


def uniform_load_control(spec, ret, deadline=None):
    """A flat bed under finite water is locally compensated for every rigidity: no shear level needed."""
    check_deadline(deadline)
    cfg, datum = spec["controls"]["uniform"], ret["datum"]
    shape, pc = tuple(cfg["shape"]), ret["water"]["plate"]
    cols = crust_columns(ret, np.zeros(shape))
    z0 = gpe.columns(datum, *cols)["surface_elevation_m"].reshape(shape)
    runs = []
    for te in (pc["elastic_thickness_m"], 0.):
        each = water.Plate(shape, pc["length_x_m"], pc["length_y_m"], te)
        volume = cfg["mean_water_m"]*each.length_x_m*each.length_y_m
        state = each.equilibrium(z0, volume, **water.ARGS)
        runs.append((each, state, join(ret, cols, each, state, volume)))
    (plate, state, r), (_, _, airy) = runs
    declared = join(ret, cols, plate, state, volume, spec["controls"]["shear_level"])
    v, tol = r["gpe_anomaly_j_m2"], quadrature_tolerance(datum)
    t = planar_traction(v, plate=plate, reduction=ret["reduction"])
    expected, top = water_layer_route(datum, cols, r["depth_m"], plate.rho_w_kg_m3)
    excess = float(np.max(np.abs(r["basal_overburden_excess_pa"])))
    e0, w, d = (r[k] for k in ("surface_above_reference_m", "displacement_m", "depth_m"))
    q, hw, h = plate.density_ratio, cfg["mean_water_m"], float(cols[0][0, 0])
    airy_bound = excess*(float(np.max(np.abs(e0)))+float(np.max(np.abs(w)))+q*float(np.max(d)))+tol
    quad = [independent_column_anomaly(datum, [h], [cols[1]], [cols[1]], rho_w_kg_m3=plate.rho_w_kg_m3,
                                       water_depth_m=float(d[0, 0]), displacement_m=float(w[0, 0]),
                                       split_depth_below_bed_m=split) for split in (None, h/2)]
    split_bound = tol+excess*(reference_top(datum)-datum.compensation_elevation_m+float(np.max(np.abs(e0)))+h)
    spacing = min(plate.length_x_m/shape[1], plate.length_y_m/shape[0])
    return finish(dict(
        compensated_every_rigidity=(r["regime"] == COMPENSATED and airy["regime"] == COMPENSATED
                                    and (r["no_transfer_limit"], airy["no_transfer_limit"]) == (UNIFORM_LOAD, ZERO_RIGIDITY)),
        declared_level_immaterial=(declared["regime"] == COMPENSATED
                                   and float(np.max(np.abs(declared["gpe_anomaly_j_m2"]-v))) <= tol),
        rigidity_independent=float(np.max(np.abs(v-airy["gpe_anomaly_j_m2"]))) <= tol,
        uniform_potential=_span(v) <= tol,
        zero_traction=float(np.max(np.abs(t))) <= ret["reduction"]*tol/spacing,
        matches_water_layer_dry_helper=float(np.max(np.abs(v.ravel()-expected))) <= airy_bound,
        airy_top_is_sea_level=float(np.max(np.abs(top-r["sea_level_m"]))) <= excess/(
            plate.gravity_m_s2*plate.rho_m_kg_m3)+POLICY["state_tolerance_m"],
        quadrature_at_any_shear_depth=max(abs(x-float(v[0, 0])) for x in quad) <= split_bound,
        not_double_loaded=float(np.max(np.abs(w-q*hw))) <= POLICY["state_tolerance_m"]),
        potential_j_m2=float(v[0, 0]), displacement_m=float(w[0, 0]),
        double_feedback_displacement_m=plate.rho_w_kg_m3*hw/(plate.rho_m_kg_m3-plate.rho_w_kg_m3),
        max_abs_basal_excess_pa=excess, max_abs_traction_pa=float(np.max(np.abs(t))))


def zero_rigidity_control(spec, ret, deadline=None):
    """Te = 0 on the partly wet retained fixture equals the unchanged dry helper with water appended."""
    check_deadline(deadline)
    cfg, datum = spec["controls"]["zero_rigidity"], ret["datum"]
    local = dict(ret, water=dict(ret["water"], plate=dict(ret["water"]["plate"],
                                                         elastic_thickness_m=cfg["elastic_thickness_m"])))
    plate, cols, z0, volume = _fixture(local, cfg["grid"])
    r = join(ret, cols, plate, plate.equilibrium(z0, volume, **water.ARGS), volume)
    expected, top = water_layer_route(datum, cols, r["depth_m"], plate.rho_w_kg_m3)
    excess = float(np.max(np.abs(r["basal_overburden_excess_pa"])))
    bound = excess*(float(np.max(np.abs(r["surface_above_reference_m"])))+float(np.max(np.abs(r["displacement_m"])))
                    + plate.density_ratio*float(np.max(r["depth_m"])))+quadrature_tolerance(datum)
    wet = float(np.mean(r["depth_m"] > 0))
    difference = float(np.max(np.abs(r["gpe_anomaly_j_m2"].ravel()-expected)))
    return finish(dict(
        compensated=r["regime"] == COMPENSATED and r["no_transfer_limit"] == ZERO_RIGIDITY,
        partly_wet=0 < wet < 1,
        matches_water_layer_dry_helper=difference <= bound,
        airy_top_matches=float(np.max(np.abs(r["top_surface_m"].ravel()-top))) <= excess/(
            plate.gravity_m_s2*plate.rho_m_kg_m3)+POLICY["state_tolerance_m"]),
        cells=cfg["grid"]**2, wet_fraction=wet, max_difference_j_m2=difference, bound_j_m2=bound,
        max_abs_basal_excess_pa=excess)


def fourier_control(spec, ret, deadline=None):
    """Finite rigidity: retained solver vs closed form, independent quadrature, level and datum sensitivity."""
    check_deadline(deadline)
    cfg, datum, gamma = spec["controls"]["fourier"], ret["datum"], ret["reduction"]
    shape, (mx, my), pc = tuple(cfg["shape"]), cfg["mode"], ret["water"]["plate"]
    plate = water.Plate(shape, pc["length_x_m"], pc["length_y_m"], pc["elastic_thickness_m"])
    y, x = np.indices(shape)
    a, hw = cfg["bed_amplitude_m"], cfg["mean_water_m"]
    cols = crust_columns(ret, a*np.cos(2*np.pi*(mx*x/shape[1]+my*y/shape[0])))
    z0 = gpe.columns(datum, *cols)["surface_elevation_m"].reshape(shape)
    volume = hw*plate.length_x_m*plate.length_y_m
    f = 1-ret["crust_density_kg_m3"]/datum.mantle_density_kg_m3
    solved = plate.equilibrium(z0, volume, **water.ARGS)
    exact = fourier_mode_state(plate, z0, mode=(mx, my), mean_water_m=hw, bed_amplitude_m=a,
                               surface_mean_m=reference_top(datum)+f*ret["mean_crust_m"])
    shear = spec["controls"]["shear_level"]
    c, c2 = shear["depth_below_bed_m"], spec["controls"]["alternative_shear_depth_m"]
    undeclared = refusal_code(lambda: join(ret, cols, plate, solved, volume))
    r_exact = join(ret, cols, plate, exact, volume, shear)
    r_solved = join(ret, cols, plate, solved, volume, shear)
    deeper = deepen(datum, spec["controls"]["datum_extension_m"])
    r_deeper = join(ret, cols, plate, exact, volume, shear, datum=deeper)
    h, w_e, d_e = cols[0][:, 0], exact["displacement_m"].ravel(), exact["depth_m"].ravel()

    def quadrature(dat, split):
        check_deadline(deadline)
        return np.array([independent_column_anomaly(dat, [hi], [cols[1]], [cols[1]], rho_w_kg_m3=plate.rho_w_kg_m3,
                                                     water_depth_m=di, displacement_m=wi, split_depth_below_bed_m=split)
                         for hi, di, wi in zip(h, d_e, w_e)]).reshape(shape)
    at_c, at_c2, naive = quadrature(datum, c), quadrature(datum, c2), quadrature(datum, None)
    at_c_deep, naive_deep = quadrature(deeper, c), quadrature(deeper, None)
    tol, tol_deep = quadrature_tolerance(datum), quadrature_tolerance(deeper)
    excess, v = exact["basal_overburden_excess_pa"], r_exact["gpe_anomaly_j_m2"]
    load_scale = plate.rho_w_kg_m3*plate.gravity_m_s2*float(np.max(d_e))
    dw = POLICY["closed_form_displacement_m"]
    shift = spec["controls"]["datum_extension_m"]*excess
    t, t_q = (planar_traction(field, plate=plate, reduction=gamma) for field in (v, at_c))
    spacing = min(plate.length_x_m/shape[1], plate.length_y_m/shape[0])
    net = float(np.max(np.abs(t.sum(axis=(0, 1)))))
    rebuilt, _ = water_layer_route(datum, cols, d_e, plate.rho_w_kg_m3)
    discriminating = POLICY["discrimination_factor"]*tol
    return finish(dict(
        undeclared_level_refused=undeclared == UNDECLARED,
        conditional_regime=r_exact["regime"] == FLEXURAL and r_solved["regime"] == FLEXURAL,
        solver_matches_closed_form=(float(np.max(np.abs(solved["displacement_m"]-exact["displacement_m"]))) <= dw
                                    and float(np.max(np.abs(solved["depth_m"]-exact["depth_m"]))) <= 2*dw),
        excess_matches_closed_form=float(np.max(np.abs(r_exact["basal_overburden_excess_pa"]-excess)))
        <= POLICY["operator_relative"]*load_scale,
        support_matches_excess=float(np.max(np.abs(r_exact["flexural_support_pa"]-excess)))
        <= POLICY["force_relative_tolerance"]*load_scale,
        join_matches_quadrature=float(np.max(np.abs(v-at_c))) <= tol,
        solver_join_within_propagated=float(np.max(np.abs(r_solved["gpe_anomaly_j_m2"]-v)))
        <= perturbation_bound(plate, r_exact, c, dw, 2*dw)+tol,
        level_sensitivity_is_excess=float(np.max(np.abs(at_c2-at_c-(c2-c)*excess))) <= 2*tol,
        datum_extension_bitwise=np.array_equal(r_deeper["gpe_anomaly_j_m2"], v),
        quadrature_datum_invariant=float(np.max(np.abs(at_c_deep-at_c))) <= tol+tol_deep,
        naive_shifts_by_delta_excess=float(np.max(np.abs(naive_deep-naive-shift))) <= tol+tol_deep,
        naive_shift_nonuniform=_span(shift) > POLICY["discrimination_factor"]*(tol+tol_deep),
        traction_matches_quadrature=float(np.max(np.abs(t-t_q))) <= gamma*tol/spacing,
        periodic_net_force_zero=net <= 4*v.size*np.finfo(float).eps*float(np.max(np.abs(v)))*gamma/spacing,
        airy_rebuild_differs=float(np.max(np.abs(rebuilt-v.ravel()))) > discriminating),
        cells=v.size, flexural_support_relative=r_exact["flexural_support_relative"],
        max_abs_basal_excess_pa=float(np.max(np.abs(excess))), shear_term_range_j_m2=_span(c*excess),
        water_effect_range_j_m2=_span(v-r_exact["dry_gpe_anomaly_j_m2"]),
        max_solver_displacement_error_m=float(np.max(np.abs(solved["displacement_m"]-exact["displacement_m"]))),
        max_join_quadrature_difference_j_m2=float(np.max(np.abs(v-at_c))),
        naive_datum_shift_range_j_m2=_span(shift), airy_rebuild_max_difference_j_m2=float(np.max(np.abs(rebuilt-v.ravel()))),
        max_abs_traction_pa=float(np.max(np.abs(t))), net_traction_pa=net)


def small_support_control(spec, ret, deadline=None):
    """A genuine but tiny nonuniform support stays flexural whatever the uniform water; never L2-classified.

    The reviewed reproducer: the Fourier control's mode with a 0.1 mm bed amplitude and its exact state. The
    closed-form B does not depend on the mean water, so every amount carries the same nonuniform support.
    """
    check_deadline(deadline)
    cfg, mode_cfg, datum = spec["controls"]["small_support"], spec["controls"]["fourier"], ret["datum"]
    shape, (mx, my), pc = tuple(mode_cfg["shape"]), mode_cfg["mode"], ret["water"]["plate"]
    plate = water.Plate(shape, pc["length_x_m"], pc["length_y_m"], pc["elastic_thickness_m"])
    shear, a = spec["controls"]["shear_level"], cfg["bed_amplitude_m"]
    c, tol = shear["depth_below_bed_m"], quadrature_tolerance(datum)
    y, x = np.indices(shape)
    cols = crust_columns(ret, a*np.cos(2*np.pi*(mx*x/shape[1]+my*y/shape[0])))
    z0 = gpe.columns(datum, *cols)["surface_elevation_m"].reshape(shape)
    surface_mean = reference_top(datum)+(1-ret["crust_density_kg_m3"]/datum.mantle_density_kg_m3)*ret["mean_crust_m"]
    rows = []
    for hw in cfg["mean_water_m"]:
        check_deadline(deadline)
        volume = hw*plate.length_x_m*plate.length_y_m
        exact = fourier_mode_state(plate, z0, mode=(mx, my), mean_water_m=hw, bed_amplitude_m=a,
                                   surface_mean_m=surface_mean)
        undeclared = refusal_code(lambda: join(ret, cols, plate, exact, volume))
        r = join(ret, cols, plate, exact, volume, shear)
        quad = np.array([independent_column_anomaly(datum, [hi], [cols[1]], [cols[1]], rho_w_kg_m3=plate.rho_w_kg_m3,
                                                    water_depth_m=di, displacement_m=wi, split_depth_below_bed_m=c)
                         for hi, di, wi in zip(cols[0][:, 0], exact["depth_m"].ravel(), exact["displacement_m"].ravel())])
        excess = r["basal_overburden_excess_pa"]
        rows.append(dict(
            mean_water_m=hw, undeclared_refusal=undeclared, regime=r["regime"],
            flexural_support_relative=r["flexural_support_relative"],
            max_abs_basal_excess_pa=float(np.max(np.abs(excess))),
            closed_form_excess_difference_pa=float(np.max(np.abs(excess-exact["basal_overburden_excess_pa"]))),
            closed_form_excess_tolerance_pa=POLICY["operator_relative"]*plate.rho_w_kg_m3*plate.gravity_m_s2
            * float(np.max(exact["depth_m"])),
            max_abs_level_term_j_m2=float(np.max(np.abs(c*excess))),
            max_join_quadrature_difference_j_m2=float(np.max(np.abs(r["gpe_anomaly_j_m2"].ravel()-quad)))))
    ratios = [row["flexural_support_relative"] for row in rows]
    return finish(dict(
        undeclared_refused_at_every_amount=all(row["undeclared_refusal"] == UNDECLARED for row in rows),
        conditional_with_declared_level=all(row["regime"] == FLEXURAL for row in rows),
        same_closed_form_support=all(row["closed_form_excess_difference_pa"] <= row["closed_form_excess_tolerance_pa"]
                                     for row in rows),
        l2_ratio_crosses_retained_tolerance=min(ratios) <= POLICY["force_relative_tolerance"] < max(ratios),
        omitted_level_term_exceeds_oracle=min(row["max_abs_level_term_j_m2"] for row in rows) > tol,
        join_matches_quadrature=all(row["max_join_quadrature_difference_j_m2"] <= tol for row in rows)),
        cells=int(np.prod(shape)), bed_amplitude_m=a, shear_depth_m=c, quadrature_tolerance_j_m2=tol, amounts=rows)


def fixture_control(spec, ret, deadline=None):
    """The retained water fixture on its three grids, joined to the retained GPE datum and crust."""
    datum, gamma, shear = ret["datum"], ret["reduction"], spec["controls"]["shear_level"]
    c, c2 = shear["depth_below_bed_m"], spec["controls"]["alternative_shear_depth_m"]
    tol, records, first = quadrature_tolerance(datum), [], None
    for n in ret["water"]["grids"]:
        check_deadline(deadline)
        plate, cols, z0, volume = _fixture(ret, n)
        begin = time.perf_counter()
        state = plate.equilibrium(z0, volume, **water.ARGS)
        solve_seconds = time.perf_counter()-begin
        undeclared = refusal_code(lambda: join(ret, cols, plate, state, volume))
        begin = time.perf_counter()
        r = join(ret, cols, plate, state, volume, shear)
        t = planar_traction(r["gpe_anomaly_j_m2"], plate=plate, reduction=gamma)
        join_seconds = time.perf_counter()-begin
        alternative = join(ret, cols, plate, state, volume, dict(shear, depth_below_bed_m=c2))
        excess = r["basal_overburden_excess_pa"]
        water_mass = float(np.sum(r["water_mass_kg_m2"]))*plate.length_x_m*plate.length_y_m/(n*n)
        records.append(dict(
            cells=n*n, regime=r["regime"], undeclared_refusal=undeclared, wet_fraction=float(np.mean(r["depth_m"] > 0)),
            flexural_support_relative=r["flexural_support_relative"], force_relative_residual=r["force_relative_residual"],
            volume_relative_residual=r["volume_relative_residual"], reference_bed_residual_m=r["reference_bed_residual_m"],
            depth_residual_m=r["depth_residual_m"],
            water_mass_relative_error=abs(water_mass-plate.rho_w_kg_m3*volume)/(plate.rho_w_kg_m3*volume),
            max_abs_basal_excess_pa=float(np.max(np.abs(excess))),
            water_effect_range_j_m2=_span(r["gpe_anomaly_j_m2"]-r["dry_gpe_anomaly_j_m2"]),
            shear_term_range_j_m2=_span(c*excess),
            alternative_level_max_change_j_m2=float(np.max(np.abs(alternative["gpe_anomaly_j_m2"]-r["gpe_anomaly_j_m2"]))),
            shear_level_sensitivity_bound_j_m2=r["shear_level_sensitivity_bound_j_m2"],
            max_abs_traction_pa=float(np.max(np.abs(t))),
            max_abs_water_traction_pa=float(np.max(np.abs(planar_traction(
                r["gpe_anomaly_j_m2"]-r["dry_gpe_anomaly_j_m2"], plate=plate, reduction=gamma)))),
            max_abs_shear_term_traction_pa=float(np.max(np.abs(planar_traction(c*excess, plate=plate, reduction=gamma)))),
            retained_solve_seconds=solve_seconds, join_and_traction_seconds=join_seconds))
        if first is None:
            first = (plate, cols, z0, volume, state, r)
    plate, cols, z0, volume, state, r = first
    index = np.arange(0, r["gpe_anomaly_j_m2"].size, POLICY["quadrature_sample_stride"])
    h, w, d = cols[0][:, 0], r["displacement_m"].ravel(), r["depth_m"].ravel()

    def quadrature(dat, split):
        check_deadline(deadline)
        return np.array([independent_column_anomaly(dat, [h[i]], [cols[1]], [cols[1]], rho_w_kg_m3=plate.rho_w_kg_m3,
                                                     water_depth_m=d[i], displacement_m=w[i], split_depth_below_bed_m=split)
                         for i in index])
    sampled = quadrature(datum, c)
    moved = translate(datum, spec["controls"]["vertical_translation_m"])
    z0_moved = gpe.columns(moved, *cols)["surface_elevation_m"].reshape(plate.shape)
    state_moved = plate.equilibrium(z0_moved, volume, **water.ARGS)
    r_moved = join(ret, cols, plate, state_moved, volume, shear, datum=moved)
    tr = POLICY["translated_displacement_m"]
    deeper = deepen(datum, spec["controls"]["datum_extension_m"])
    r_deeper = join(ret, cols, plate, state, volume, shear, datum=deeper)
    naive, naive_deep = quadrature(datum, None), quadrature(deeper, None)
    tol_deep = quadrature_tolerance(deeper)
    shift = spec["controls"]["datum_extension_m"]*r["basal_overburden_excess_pa"].ravel()[index]
    rebuilt, _ = water_layer_route(datum, cols, r["depth_m"], plate.rho_w_kg_m3)
    checks = dict(
        conditional_regime_all=all(x["regime"] == FLEXURAL for x in records),
        undeclared_refused_all=all(x["undeclared_refusal"] == UNDECLARED for x in records),
        water_mass_conserved_all=all(x["water_mass_relative_error"] <= POLICY["volume_relative_tolerance"] for x in records),
        sampled_quadrature=float(np.max(np.abs(r["gpe_anomaly_j_m2"].ravel()[index]-sampled))) <= tol,
        translation_resolve_matches=(
            float(np.max(np.abs(state_moved["displacement_m"]-state["displacement_m"]))) <= tr
            and float(np.max(np.abs(state_moved["depth_m"]-state["depth_m"]))) <= 2*tr),
        translation_invariant_potential=float(np.max(np.abs(r_moved["gpe_anomaly_j_m2"]-r["gpe_anomaly_j_m2"])))
        <= perturbation_bound(plate, r, c, tr, 2*tr)+tol,
        extension_bitwise=np.array_equal(r_deeper["gpe_anomaly_j_m2"], r["gpe_anomaly_j_m2"]),
        naive_shifts_by_delta_excess=float(np.max(np.abs(naive_deep-naive-shift))) <= tol+tol_deep,
        naive_shift_nonuniform=_span(shift) > POLICY["discrimination_factor"]*(tol+tol_deep),
        airy_rebuild_differs=float(np.max(np.abs(rebuilt-r["gpe_anomaly_j_m2"].ravel())))
        > POLICY["discrimination_factor"]*tol)
    return finish(checks, grids=records, sampled_columns=len(index),
                  max_sampled_quadrature_difference_j_m2=float(np.max(np.abs(r["gpe_anomaly_j_m2"].ravel()[index]-sampled))),
                  translated_max_potential_change_j_m2=float(np.max(np.abs(r_moved["gpe_anomaly_j_m2"]-r["gpe_anomaly_j_m2"]))),
                  naive_datum_shift_range_j_m2=_span(shift),
                  airy_rebuild_max_difference_j_m2=float(np.max(np.abs(rebuilt-r["gpe_anomaly_j_m2"].ravel()))))


def refusals_control(spec, ret, deadline=None):
    """Forged, stale, doubled or incompatible inputs built from retained output: each refused atomically."""
    check_deadline(deadline)
    datum, shear = ret["datum"], spec["controls"]["shear_level"]
    plate, cols, z0, volume = _fixture(ret, ret["water"]["grids"][0])
    state = plate.equilibrium(z0, volume, **water.ARGS)
    area, q, h = plate.length_x_m*plate.length_y_m, plate.density_ratio, cols[0]
    pc, rho_c = ret["water"]["plate"], float(ret["crust_density_kg_m3"])

    def restate(surface, displacement, water_volume):   # self-consistent bed and refilled water for a forged w
        loaded = surface-displacement
        level, depth, _, _ = water._fill(loaded, water_volume/area)
        return dict(displacement_m=displacement, bed_m=loaded, depth_m=depth, sea_level_m=level)

    flat = crust_columns(ret, np.zeros(plate.shape))
    z_flat = gpe.columns(datum, *flat)["surface_elevation_m"].reshape(plate.shape)
    hw = volume/area
    feedback = np.full(plate.shape, plate.rho_w_kg_m3*hw/(plate.rho_m_kg_m3-plate.rho_w_kg_m3))
    doubled = plate.equilibrium(z0, 2*volume, **water.ARGS)
    airy = water.Plate(plate.shape, pc["length_x_m"], pc["length_y_m"], 0.).equilibrium(z0, volume, **water.ARGS)
    shallow = gpe.Datum(datum.gravity_m_s2*(rho_c*float(ret["mean_crust_m"])
                                            + datum.mantle_density_kg_m3*spec["controls"]["below_datum_fill_m"]),
                        datum.compensation_elevation_m, datum.mantle_density_kg_m3, datum.gravity_m_s2,
                        datum.reference_temperature_k)
    z_shallow = gpe.columns(shallow, *flat)["surface_elevation_m"].reshape(plate.shape)
    wet_rock = (np.hstack((h, np.full((len(h), 1), 100.))), [rho_c, plate.rho_w_kg_m3], 0., 1000., 1000.)
    nan_depth = state["depth_m"].copy()
    nan_depth[0, 0] = np.nan
    dry_cells = np.flatnonzero(state["depth_m"] == 0)
    if not dry_cells.size:
        raise ValueError("the retained fixture has no exactly dry cell for the negative-depth probe")
    negative_depth = state["depth_m"].copy()           # one exactly dry cell; every other producer field unchanged
    negative_depth.flat[int(dry_cells[0])] = spec["controls"]["negative_depth_at_dry_cell_m"]
    check_deadline(deadline)
    cases = {
        "doubled_depth": attempt(LOAD, datum, cols, plate, dict(state, depth_m=2*state["depth_m"]), volume, shear),
        "extra_local_airy": attempt(EQUILIBRIUM, datum, cols, plate, restate(
            z0, state["displacement_m"]+q*state["depth_m"], volume), volume, shear),
        "double_water_feedback": attempt(EQUILIBRIUM, datum, flat, plate, restate(z_flat, feedback, volume), volume, shear),
        "increment_as_total": attempt(EQUILIBRIUM, datum, cols, plate, restate(
            z0, doubled["displacement_m"]-state["displacement_m"], 2*volume), 2*volume, shear),
        "airy_rebuild_on_stiff_plate": attempt(EQUILIBRIUM, datum, cols, plate, airy, volume, shear),
        "dropped_flexure": attempt(EQUILIBRIUM, datum, cols, plate, restate(z0, np.zeros(plate.shape), volume),
                                   volume, shear),
        "shifted_reference": attempt(REFERENCE, datum, cols, plate, plate.equilibrium(
            z0+spec["controls"]["shifted_reference_m"], volume, **water.ARGS), volume, shear),
        "reordered_columns": attempt(REFERENCE, datum, (h.reshape(plate.shape).T.reshape(-1, 1),)+cols[1:],
                                     plate, state, volume, shear),
        "mantle_density_mismatch": attempt(MATERIAL, datum, cols, water.Plate(
            plate.shape, pc["length_x_m"], pc["length_y_m"], pc["elastic_thickness_m"], rho_m_kg_m3=3250.),
            state, volume, shear),
        "gravity_mismatch": attempt(MATERIAL, datum, cols, water.Plate(
            plate.shape, pc["length_x_m"], pc["length_y_m"], pc["elastic_thickness_m"], gravity_m_s2=9.8),
            state, volume, shear),
        "column_count": attempt(SHAPE, datum, (h[:-1],)+cols[1:], plate, state, volume, shear),
        "forged_status_only": attempt(SHAPE, datum, cols, plate, {"status": PASS,
                                      "law": "atlas.fixed-datum-support-water.v1"}, volume, shear),
        "forged_status_zero_arrays": attempt(LOAD, datum, cols, plate, {
            "status": PASS, "displacement_m": np.zeros(plate.shape), "bed_m": z0.copy(),
            "depth_m": np.zeros(plate.shape), "sea_level_m": None}, volume, shear),
        "undeclared_shear_level": attempt(UNDECLARED, datum, cols, plate, state, volume, None),
        "shear_level_below_rock": attempt(OUTSIDE, datum, cols, plate, state, volume,
                                          dict(shear, depth_below_bed_m=float(np.min(h))+1.)),
        "shear_level_at_bed": attempt(OUTSIDE, datum, cols, plate, state, volume, dict(shear, depth_below_bed_m=0.)),
        "shear_level_without_basis": attempt(INVALID, datum, cols, plate, state, volume, dict(shear, basis=" ")),
        "shear_level_nonfinite": attempt(INVALID, datum, cols, plate, state, volume,
                                         dict(shear, depth_below_bed_m=float("nan"))),
        "below_datum": attempt(BELOW, shallow, flat, plate, plate.equilibrium(z_shallow, volume, **water.ARGS),
                               volume, shear),
        "water_in_rock_column": attempt(WATER_IN_ROCK, datum, wet_rock, plate, state, volume, shear),
        "unsupported_geometry": attempt(UNSUPPORTED, datum, cols, plate, state, volume, shear, geometry="sphere"),
        "foreign_plate": attempt(UNSUPPORTED, datum, cols, dict(shape=plate.shape), state, volume, shear),
        "nonfinite_depth": attempt(NONFINITE, datum, cols, plate, dict(state, depth_m=nan_depth), volume, shear),
        "negative_depth_at_dry_cell": attempt(NEGATIVE_WATER, datum, cols, plate, dict(state, depth_m=negative_depth),
                                              volume, shear),
        "zero_volume_with_water": attempt(LOAD, datum, cols, plate, state, 0., shear),
        "negative_volume": attempt(INVALID, datum, cols, plate, state, -1., shear),
        "boolean_volume": attempt(INVALID, datum, cols, plate, state, True, shear),
        "invalid_columns": attempt(COLUMNS, datum, (-h,)+cols[1:], plate, state, volume, shear),
    }
    return finish({name: case["refused_as_expected"] and case["inputs_unchanged"] for name, case in cases.items()},
                  cases=cases, negative_depth_cell=int(dry_cells[0]))


def timing_control(spec, ret, deadline=None):
    """Raw interleaved timings of the retained solve and this join on identical inputs; no saving claimed."""
    rows = []
    for n in ret["water"]["grids"]:
        plate, cols, z0, volume = _fixture(ret, n)
        samples = {"retained_water_solve": [], "join_and_traction": []}
        for _ in range(POLICY["timing_repetitions"]):
            check_deadline(deadline)
            begin = time.perf_counter()
            state = plate.equilibrium(z0, volume, **water.ARGS)
            samples["retained_water_solve"].append(time.perf_counter()-begin)
            begin = time.perf_counter()
            r = join(ret, cols, plate, state, volume, spec["controls"]["shear_level"])
            planar_traction(r["gpe_anomaly_j_m2"], plate=plate, reduction=ret["reduction"])
            samples["join_and_traction"].append(time.perf_counter()-begin)
        rows.append(dict(cells=n*n, samples_seconds=samples,
                         median_seconds={k: float(np.median(v)) for k, v in samples.items()}))
    finite = all(math.isfinite(s) and s >= 0 for row in rows for v in row["samples_seconds"].values() for s in v)
    return finish(dict(finite_nonnegative=finite), grids=rows,
                  scope="raw timings of different work on identical inputs; no matched baseline, so no saving is claimed")


CONTROLS = (("dry_parity", dry_parity_control), ("uniform_load", uniform_load_control),
            ("zero_rigidity", zero_rigidity_control), ("finite_rigidity_fourier", fourier_control),
            ("small_nonuniform_support", small_support_control),
            ("retained_fixture_join", fixture_control), ("refusals", refusals_control),
            ("timing", timing_control))


# ----------------------------------------------------------------------------- case, bindings and receipt

def load_case(path=None):
    spec = json.loads((ROOT/CASE if path is None else Path(path)).read_text(encoding="utf-8"))
    if (type(spec) is not dict or set(spec) != CASE_FIELDS or spec["schema"] != CASE_SCHEMA
            or spec["contract"] != CONTRACT or spec["policy"] != POLICY):
        raise ValueError("case fields/schema/contract/policy differ from the executable")
    return spec


def retained_inputs(spec):
    """Read-only retained GPE and water case values; refuse drift from this control's frozen declaration."""
    observed = {}
    for label, path, keys in (("gpe_case", "cases/i01_gpe_v1.json", GPE_KEYS),
                              ("water_case", "cases/i01_water_flexure_v1.json", WATER_KEYS)):
        record = json.loads((ROOT/path).read_text(encoding="utf-8"))
        observed[label] = {key: record[key] for key in keys}
    if observed != spec["retained"]:
        raise ValueError("retained GPE/water case values differ from this control's frozen declaration")
    for mine, theirs in (("force_relative_tolerance", "force_relative_tolerance"),
                         ("volume_relative_tolerance", "volume_relative_tolerance"),
                         ("state_tolerance_m", "rms_error_m")):
        if POLICY[mine] != water.POLICY[theirs]:
            raise ValueError("copied tolerance differs from the retained water executable: "+mine)
    g = observed["gpe_case"]
    return dict(datum=gpe.Datum(**g["datum"]), reduction=g["reduction"],
                crust_density_kg_m3=g["crust_density_kg_m3"], mean_crust_m=g["mean_crust_m"],
                water=dict(observed["water_case"]))


def digest(name):
    return hashlib.sha256((ROOT/name).read_bytes()).hexdigest()


def bindings():
    return {name: digest(name) for name in NEW_FILES+RETAINED+tuple(ACCEPTED_RECEIPTS)}


def evidence_match(current):
    """Retained producers are the bytes their accepted receipts recorded, and imports resolve to them.

    Gated: the receipts and every retained file this join executes or reads. Reported only: the other
    files those receipts recorded (their method documents and tests), which this join does not run.
    """
    receipts = {name: current[name] == value for name, value in ACCEPTED_RECEIPTS.items()}
    recorded = {}
    for name in ACCEPTED_RECEIPTS:
        for source, value in json.loads((ROOT/name).read_text(encoding="utf-8"))["source_sha256"].items():
            recorded.setdefault(source, set()).add(value)

    def matches(source):
        present = (ROOT/source).is_file()
        now = current[source] if source in current else (digest(source) if present else None)
        return bool(recorded.get(source)) and present and len(recorded[source]) == 1 and now in recorded[source]
    return dict(receipts=receipts, retained={name: matches(name) for name in RETAINED},
                imported={name: Path(module.__file__).resolve() == (ROOT/name).resolve()
                          for name, module in IMPORTED.items()},
                informational={name: matches(name) for name in sorted(recorded) if name not in RETAINED})


def jsonable(value):
    """Plain JSON types; non-finite floats stay in place so serialisation refuses them."""
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return jsonable(value.tolist())
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        result = dict(schema=EVIDENCE_SCHEMA, status="INCOMPLETE", scientific_acceptance=False,
                      finite_rigidity_closure=False, contract=CONTRACT,
                      runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                                   system=platform.system(), machine=platform.machine()),
                      controls={})
        start = time.perf_counter()
        try:
            before = bindings()
            result["source_sha256"] = before
            match = evidence_match(before)
            result["retained_evidence"] = match
            if not all(all(match[key].values()) for key in ("receipts", "retained", "imported")):
                raise ValueError("retained producers differ from their accepted receipts, or imports resolve elsewhere")
            spec = load_case()
            ret = retained_inputs(spec)
            deadline = start+POLICY["maximum_seconds"]      # cooperative budget, checked inside every control
            for name, control in CONTROLS:
                begin = time.perf_counter()
                try:
                    data = control(spec, ret, deadline)
                    check_deadline(deadline)                # an overrunning control is not recorded as a pass
                    result["controls"][name] = dict(status="PASS" if data["passed"] else "FAIL",
                                                    seconds=time.perf_counter()-begin, **data)
                except (ValueError, RuntimeError, ArithmeticError, KeyError, TypeError) as exc:
                    result["controls"][name] = dict(status="FAIL", seconds=time.perf_counter()-begin,
                                                    error_type=type(exc).__name__,
                                                    error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
            result["source_unchanged"] = before == bindings()
            passed = (result["source_unchanged"] and len(result["controls"]) == len(CONTROLS)
                      and all(c["status"] == "PASS" for c in result["controls"].values()))
            result["status"] = PASS if passed else "FAIL"
        except Exception as exc:
            # Deliberately do not publish arbitrary exception paths or tracebacks.
            result.update(status="FAIL", error_type=type(exc).__name__)
            if isinstance(exc, (ValueError, RuntimeError)):
                result["error"] = str(exc).replace(str(ROOT), "TECTONICS_ROOT")
        result["elapsed_seconds_after_imports"] = time.perf_counter()-start
        try:
            body = json.dumps(jsonable(result), indent=2, allow_nan=False)
        except (TypeError, ValueError) as exc:          # never leave a partial or non-finite record behind
            result = dict(schema=EVIDENCE_SCHEMA, status="FAIL", scientific_acceptance=False,
                          runtime=result["runtime"], error_type=type(exc).__name__,
                          error="evidence record not serialisable: "+str(exc)[:200], controls={},
                          elapsed_seconds_after_imports=result["elapsed_seconds_after_imports"])
            body = json.dumps(result, indent=2, allow_nan=False)
        stream.write(body+"\n")
    print(json.dumps({key: result.get(key) for key in ("status", "elapsed_seconds_after_imports", "error")}
                     | {"controls": {k: c["status"] for k, c in result["controls"].items()}}))
    return 0 if result["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
