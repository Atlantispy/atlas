"""I01 MC-07: one declared elastic core supplies both the plate stiffness and the shear-transfer depth.

WORKING NON-CANON. A homogeneous, isotropic, horizontally constant elastic core between depths a < b below each
column's rock surface gives the retained periodic Plate its rigidity D = E (b-a)^3/[12(1-nu^2)] and gives the
unchanged water/GPE join its effective shear-transfer depth c = (a+b)/2, the centroid of the core's Kirchhoff
shear-divergence density. Not a strength-envelope producer, a variable-D or multi-core law, or I04/I08 support.
Run: python -B tectonics/tools/check_i01_elastic_core.py --output NEW.json
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy

import check_i01_water_gpe as j              # retained water/GPE join; imports the dry GPE and water/flexure helpers

gpe, water, closures = j.gpe, j.water, j.closures

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "atlas.single-elastic-core.v1"
EVIDENCE_SCHEMA = "atlas.i01-elastic-core.v1"
CASE_SCHEMA = "atlas.i01-elastic-core-case.v1"
CASE = "cases/i01_elastic_core_v1.json"
PASS = "PASS_BOUNDED_CONTROLS_ONLY"
NEW_FILES = ("tools/check_i01_elastic_core.py", "cases/i01_elastic_core_v1.json",
             "docs/I01_ELASTIC_CORE.md", "tests/test_i01_elastic_core.py")
RETAINED = ("tools/check_i01_water_gpe.py", "cases/i01_water_gpe_v1.json", "tools/check_i01_gpe.py",
            "tools/check_i01_closures.py", "tools/check_i01_water_flexure.py", "cases/i01_gpe_v1.json",
            "cases/i01_water_flexure_v1.json")
# Digests of the accepted receipts, copied from the evidence register (not recomputed here).
ACCEPTED_RECEIPTS = {
    "evidence/i01-water-gpe-r1.json": "539f76c29ca0d94e302f81da1cccc1a48dd2460f544d5ce07f8b561eca09100d",
    "evidence/i01-gpe-r1.json": "bfd5ddbaa6a204ca156b9d94b981269fb9ce0956bb5ec37d1fd111b6c248e4fd",
    "evidence/i01-water-flexure-r1.json": "6e22ad6d509520eaefb30f2ddcba1eea2957770ce3c4f33e78aabe712b6c3932",
}
IMPORTED = {"tools/check_i01_water_gpe.py": j, "tools/check_i01_gpe.py": gpe,
            "tools/check_i01_closures.py": closures, "tools/check_i01_water_flexure.py": water}
CASE_FIELDS = {"schema", "status", "contract", "document", "policy", "retained", "controls", "source"}
# Frozen before execution; cases/i01_elastic_core_v1.json must carry exactly this policy.
POLICY = {
    "force_relative_tolerance": 1e-7,          # = retained join and water force tolerance
    "volume_relative_tolerance": 1e-11,        # = retained join and water volume tolerance
    "closed_form_displacement_m": 2e-6,        # = retained oblique-mode tolerance
    "translated_displacement_m": 1e-7,         # = retained join translation re-solve
    "quadrature_fraction_of_reference": 1e-12, # = retained join oracle tolerance
    "operator_relative": 1e-12,                # = retained join: exact algebra evaluated in floating point
    "discrimination_factor": 1000.0,
    "gauss_order": 3,                          # exact for the cubic in-core vertical stress on every piece
    "quadrature_sample_stride": 16,
    "timing_repetitions": 5,
    "maximum_seconds": 60.0,
}
COPIED = ("force_relative_tolerance", "volume_relative_tolerance", "closed_form_displacement_m",
          "translated_displacement_m", "quadrature_fraction_of_reference", "operator_relative",
          "discrimination_factor", "gauss_order", "quadrature_sample_stride")
Refusal = j.Refusal                          # one atomic refusal type for the core and the join it wraps
INVALID_CORE = "REFUSED_INVALID_CORE"
UNPLACED = "REFUSED_CORE_PLACEMENT_ABSENT"
UNSUPPORTED_CORE = "REFUSED_UNSUPPORTED_CORE"
OUTSIDE_ROCK = "REFUSED_CORE_OUTSIDE_ROCK"
MISMATCH = "REFUSED_CORE_SOLVER_MISMATCH"
NOT_A_CORE = "REFUSED_ZERO_RIGIDITY_NOT_A_CORE"
ROCK_SURFACE = "rock_surface"
FIELDS = ("material", "basis", "depth_reference", "top_depth_m", "bottom_depth_m", "young_pa", "poisson")
SEVERAL = frozenset({"layers", "cores"})     # layered or multiple cores: not this branch
BRANCH = "one homogeneous isotropic core; horizontally constant; follows each column's rock surface"
DERIVATION = ("Kirchhoff bending about the core mid-surface with shear-free faces: the horizontal divergence of the "
              "parabolic transverse shear is B*6(s-a)(b-s)/h^3, whose centroid c = (a+b)/2 is the transfer depth")


def _real(value, name):
    """A finite real scalar; an array is a horizontally varying (or layered) core, which is not this branch."""
    if value is None or isinstance(value, (bool, np.bool_, str, bytes, complex, np.complexfloating)):
        raise Refusal(INVALID_CORE, name+" must be a real scalar")
    try:
        varies = np.ndim(value) != 0
    except ValueError:                           # ragged sequences
        varies = True
    if varies:
        raise Refusal(UNSUPPORTED_CORE, name+" varies: horizontally varying, layered or multiple cores are not this branch")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise Refusal(INVALID_CORE, name+" must be a real scalar") from None
    if not math.isfinite(value):
        raise Refusal(INVALID_CORE, name+" must be finite")
    return value


@dataclass(frozen=True)
class ElasticCore:
    """One homogeneous, isotropic elastic core: depths below each column's rock surface (m), E (Pa) and nu.

    Horizontally constant and column-following. Rigidity and shear-transfer depth are both DERIVED from the
    interval; neither D nor Te is an input, because neither locates the core (I01_ELASTIC_CORE.md section 3).
    """
    material: str
    basis: str
    depth_reference: str
    top_depth_m: float
    bottom_depth_m: float
    young_pa: float
    poisson: float

    def __post_init__(self):
        if self.top_depth_m is None or self.bottom_depth_m is None:
            raise Refusal(UNPLACED, "a core declares its top and bottom depths; D or Te alone cannot locate it")
        for name in ("material", "basis"):
            text = getattr(self, name)
            if type(text) is not str or not text.strip():
                raise Refusal(INVALID_CORE, "a nonempty "+name+" text is required")
        if type(self.depth_reference) is not str or self.depth_reference != ROCK_SURFACE:
            raise Refusal(INVALID_CORE, "core depths are measured below each column's rock surface: 'rock_surface'")
        names = ("top_depth_m", "bottom_depth_m", "young_pa", "poisson")
        top, bottom, young, poisson = (_real(getattr(self, name), name) for name in names)
        if top < 0:
            raise Refusal(OUTSIDE_ROCK, "the core top lies above the rock surface")
        if not top < bottom:
            raise Refusal(INVALID_CORE, "the core needs top < bottom: a positive thickness")
        if not young > 0:
            raise Refusal(INVALID_CORE, "Young's modulus must be positive")
        if not -1 < poisson < .5:
            raise Refusal(INVALID_CORE, "Poisson's ratio must lie in the isotropic elastic range (-1, 1/2)")
        for name, value in zip(names, (top, bottom, young, poisson)):
            object.__setattr__(self, name, value)
        try:
            representable = (0 < self.rigidity_n_m < math.inf) and math.isfinite(self.shear_transfer_depth_m)
        except OverflowError:
            representable = False
        if not representable:
            raise Refusal(INVALID_CORE, "core rigidity or transfer depth is not representable")

    @property
    def thickness_m(self):
        """h = b - a."""
        return self.bottom_depth_m-self.top_depth_m

    @property
    def rigidity_n_m(self):
        """D = E h^3/[12(1-nu^2)]: the retained Plate's own expression, so equal inputs give equal bits."""
        return self.young_pa*self.thickness_m**3/(12*(1-self.poisson**2))

    @property
    def shear_transfer_depth_m(self):
        """c = (a+b)/2 below the rock surface: the centroid of the Kirchhoff shear-divergence density."""
        return .5*(self.top_depth_m+self.bottom_depth_m)


def elastic_core(declaration):
    """A validated ElasticCore from an ElasticCore or a mapping with exactly its declared fields."""
    if type(declaration) is ElasticCore:
        return ElasticCore(**{name: getattr(declaration, name) for name in FIELDS})     # validated again
    if isinstance(declaration, (list, tuple)):
        raise Refusal(UNSUPPORTED_CORE, "one core per declaration: multiple cores are not this branch")
    if not isinstance(declaration, Mapping):
        raise Refusal(INVALID_CORE, "an elastic-core declaration is required")
    keys = set(declaration)
    if keys & SEVERAL:
        raise Refusal(UNSUPPORTED_CORE, "layered or multiple cores are not this branch")
    if not {"top_depth_m", "bottom_depth_m"} <= keys:
        raise Refusal(UNPLACED, "a core declares its top and bottom depths; D or Te alone cannot locate it")
    if keys != set(FIELDS):
        raise Refusal(INVALID_CORE, "a core declares exactly "+", ".join(FIELDS)+"; its D, Te and c are derived")
    return ElasticCore(**{name: declaration[name] for name in FIELDS})


def core_shear_level(core):
    """The join's shear-level declaration derived from the core: c = (a+b)/2 below the rock surface, with its basis."""
    core = elastic_core(core)
    return {"depth_below_bed_m": core.shear_transfer_depth_m,
            "basis": (f"{CONTRACT}: centroid (a+b)/2 of the Kirchhoff shear-divergence density of the declared "
                      f"homogeneous isotropic elastic core {core.material!r}, {core.top_depth_m!r} to "
                      f"{core.bottom_depth_m!r} m below the rock surface, E {core.young_pa!r} Pa, "
                      f"nu {core.poisson!r}. Declared basis: {core.basis}")}


def _retained_representable(core):
    if not core.poisson >= 0:
        raise Refusal(UNSUPPORTED_CORE, "the retained Plate admits 0 <= nu < 1/2; an auxetic core is not representable")


def core_plate(core, datum, shape, length_x_m, length_y_m, *, rho_w_kg_m3):
    """The retained periodic Plate whose stiffness IS this core: Te = b - a, the core's E and nu, the datum's rho_m, g."""
    core = elastic_core(core)
    _retained_representable(core)
    if not isinstance(datum, gpe.Datum):
        raise Refusal(j.UNSUPPORTED, "the retained Datum is required")
    try:
        return water.Plate(shape, length_x_m, length_y_m, core.thickness_m, young_pa=core.young_pa,
                           poisson=core.poisson, rho_m_kg_m3=datum.mantle_density_kg_m3,
                           rho_w_kg_m3=rho_w_kg_m3, gravity_m_s2=datum.gravity_m_s2)
    except (ValueError, ArithmeticError) as exc:
        raise Refusal(j.INVALID, "the retained Plate refused this core: "+str(exc)) from None


def authenticate_plate(core, plate):
    """The validated core, provided the retained plate carries exactly its stiffness. Zero rigidity is not a core."""
    core = elastic_core(core)
    if type(plate) is not water.Plate:
        raise Refusal(j.UNSUPPORTED, "the retained Plate type is required")
    if plate.rigidity_n_m == 0:
        raise Refusal(NOT_A_CORE, "a finite core cannot represent zero rigidity; the join takes that limit without a core")
    _retained_representable(core)
    if ((plate.elastic_thickness_m, plate.young_pa, plate.poisson) != (core.thickness_m, core.young_pa, core.poisson)
            or plate.rigidity_n_m != core.rigidity_n_m):
        raise Refusal(MISMATCH, "the plate's Te, E and nu must be exactly this core's b - a, E and nu")
    return core


def thinnest_rock_m(thickness_m):
    """The thinnest represented rock column (m), from the same (columns, layers) thicknesses the join validates."""
    try:
        h = gpe.real_array(thickness_m)
    except (ValueError, TypeError) as exc:
        raise Refusal(j.COLUMNS, str(exc)) from None
    if h.ndim != 2 or 0 in h.shape or np.any(h <= 0):
        raise Refusal(j.COLUMNS, "positive (columns, layers) rock thicknesses are required")
    return float(np.min(h.sum(axis=1)))


def core_loaded_gpe(datum, thickness_m, reference_density_kg_m3, alpha_per_k, bottom_temperature_k,
                    top_temperature_k, core, plate, water_state, *, volume_m3, geometry, connectivity):
    """Water-loaded driving potential whose shear-transfer depth comes from one declared elastic core.

    Checks, in order: the core declaration; the retained Plate carrying exactly this core's stiffness (a
    zero-rigidity plate is not a core); the core inside every rock column, 0 <= a < b <= min H; then the
    UNCHANGED water/GPE join with c = (a+b)/2 and the core's basis, which authenticates datum, material,
    columns, water and equilibrium itself. Refusals raise before any result exists; inputs are never modified.
    Returns the join's result unchanged, plus the core record under "elastic_core".
    """
    core = authenticate_plate(core, plate)
    thinnest = thinnest_rock_m(thickness_m)
    if not core.bottom_depth_m <= thinnest:
        raise Refusal(OUTSIDE_ROCK, "the core must lie inside every rock column; its base is below the thinnest rock base")
    joined = j.water_loaded_gpe(datum, thickness_m, reference_density_kg_m3, alpha_per_k, bottom_temperature_k,
                                top_temperature_k, plate, water_state, volume_m3=volume_m3, geometry=geometry,
                                connectivity=connectivity, shear_level=core_shear_level(core))
    return dict(joined, elastic_core=dict(
        contract=CONTRACT, branch=BRANCH, derivation=DERIVATION, material=core.material, basis=core.basis,
        depth_reference=ROCK_SURFACE, top_depth_m=core.top_depth_m, bottom_depth_m=core.bottom_depth_m,
        thickness_m=core.thickness_m, young_pa=core.young_pa, poisson=core.poisson, rigidity_n_m=core.rigidity_n_m,
        shear_transfer_depth_m=core.shear_transfer_depth_m, thinnest_rock_m=thinnest,
        rock_below_core_m=thinnest-core.bottom_depth_m))


# ----------------------------------------------------------------------------- independent controls (not the producer)

def _rule(order=None):
    nodes, weights = np.polynomial.legendre.leggauss(POLICY["gauss_order"] if order is None else order)
    return list(zip(nodes.tolist(), weights.tolist()))


def shear_density(depth_m, top_m, bottom_m):
    """Normalised Kirchhoff shear-divergence density phi(s) = 6 (s-a)(b-s)/h^3 inside the core (1/m)."""
    return 6*(depth_m-top_m)*(bottom_m-depth_m)/(bottom_m-top_m)**3


def carried_fraction(depth_m, top_m, bottom_m, order=None):
    """Share of the transferred load taken up between the core top and depth s: Gauss integral of phi from a to s."""
    half, mid = (depth_m-top_m)/2, (depth_m+top_m)/2
    return half*math.fsum(wi*shear_density(mid+half*xi, top_m, bottom_m) for xi, wi in _rule(order))


def shear_moments(top_m, bottom_m, order=None):
    """Integral and first moment (m) of phi over the core by Gauss quadrature; never the closed-form (a+b)/2."""
    half, mid, rule = (bottom_m-top_m)/2, (bottom_m+top_m)/2, _rule(order)
    total = half*math.fsum(wi*shear_density(mid+half*xi, top_m, bottom_m) for xi, wi in rule)
    moment = half*math.fsum(wi*(mid+half*xi)*shear_density(mid+half*xi, top_m, bottom_m) for xi, wi in rule)
    return total, moment


def kirchhoff_rigidity(core, order=None):
    """D recovered from the core's stresses: the thickness integral of the shear-divergence weight
    E/[2(1-nu^2)] (h^2/4 - zeta^2) per unit biharmonic(w), by Gauss quadrature (Kelly eqs 6.4.12-6.4.15)."""
    half, modulus = core.thickness_m/2, core.young_pa/(2*(1-core.poisson**2))
    return half*math.fsum(wi*modulus*(half*half-(half*xi)**2) for xi, wi in _rule(order))


def kirchhoff_transfer(core, plate, displacement_m, order=None):
    """Per cell, the vertical load carried by the core's own Kirchhoff shear (Pa).

    kirchhoff_rigidity x biharmonic(w), with a spectral biharmonic that never uses the plate's rigidity or the
    join's algebra. Where it equals the column's excess B, the basal pressure is the uniform datum pressure.
    """
    ny, nx = plate.shape
    kx = 2*np.pi*np.fft.rfftfreq(nx, plate.length_x_m/nx)
    ky = 2*np.pi*np.fft.fftfreq(ny, plate.length_y_m/ny)
    spectrum = np.fft.rfft2(np.asarray(displacement_m, dtype=float))*(kx[None, :]**2+ky[:, None]**2)**2
    return kirchhoff_rigidity(core, order)*np.fft.irfft2(spectrum, s=plate.shape)


def smooth_core_column(datum, thickness_m, bottom_density_kg_m3, top_density_kg_m3, *, rho_w_kg_m3, water_depth_m,
                       displacement_m, core_top_m, core_bottom_m, transfer_pa=None, order=None):
    """ONE column's vertical stress with the core's smooth Kirchhoff transition, integrated by Gauss quadrature.

    Independent oracle: builds the displaced column, its overburden p_o and -sigma_zz = p_o - T G(s), where G is
    the running integral of the normalised parabolic shear density from the core top (0 above the core, 1 below)
    and T the transferred load. T defaults to this column's own excess over the datum pressure, p_o(zc) - P; a
    supplied T (the core's Kirchhoff shear) tests force balance through the returned basal pressure. Layers are
    bottom to top with linear effective density. Never uses (a+b)/2, c B or the join's algebra. Returns the
    anomaly (integral minus P^2/(2 g rho_m)), the basal pressure and the column excess.
    """
    g, rho_m = datum.gravity_m_s2, datum.mantle_density_kg_m3
    p0, zc = datum.pressure_pa, datum.compensation_elevation_m
    rule = _rule(order)

    def mass(lo, hi, piece):                  # exact for linear density on [lo, hi] inside the piece
        b, t, db, dt = piece
        half, mid = (hi-lo)/2, (hi+lo)/2
        return half*math.fsum(wi*(db+(dt-db)*(mid+half*xi-b)/(t-b)) for xi, wi in rule)

    layers = [(float(h), float(rb), float(rt)) for h, rb, rt in
              zip(thickness_m, bottom_density_kg_m3, top_density_kg_m3)]
    load = math.fsum(mass(0., h, (0., h, rb, rt)) for h, rb, rt in layers)
    z = zc+(p0/g-load)/rho_m-float(displacement_m)
    pieces = [(zc, z, rho_m, rho_m)]
    for h, rb, rt in layers:
        pieces.append((z, z+h, rb, rt))
        z += h
    rock = z
    if water_depth_m > 0:
        pieces.append((rock, rock+float(water_depth_m), float(rho_w_kg_m3), float(rho_w_kg_m3)))
    top, bottom = float(core_top_m), float(core_bottom_m)
    upper, lower = rock-top, rock-bottom      # the core faces as elevations: they follow this column's rock surface
    for split in (upper, lower):
        cut = []
        for b, t, db, dt in pieces:
            if b < split < t:
                ds = db+(dt-db)*(split-b)/(t-b)
                cut += [(b, split, db, ds), (split, t, ds, dt)]
            else:
                cut.append((b, t, db, dt))
        pieces = cut

    def overburden(zq):
        return g*math.fsum(mass(max(zq, p[0]), p[1], p) for p in pieces if p[1] > zq)
    excess = overburden(zc)-p0
    transfer = excess if transfer_pa is None else float(transfer_pa)

    def pressure(zq):                         # -sigma_zz
        if zq > upper:
            return overburden(zq)
        if zq < lower:
            return overburden(zq)-transfer
        return overburden(zq)-transfer*carried_fraction(rock-zq, top, bottom, order)
    total = math.fsum((t-b)/2*wi*pressure((t+b)/2+(t-b)/2*xi) for b, t, _, _ in pieces for xi, wi in rule)
    return dict(anomaly_j_m2=total-p0*p0/(2*g*rho_m), basal_pressure_pa=overburden(zc)-transfer,
                column_excess_pa=excess)


def smooth_potential(datum, columns_args, state, top_m, bottom_m, *, rho_w_kg_m3, index=None, transfer_pa=None,
                     deadline=None):
    """The smooth-profile oracle at the listed columns (all if None) of one unheated crust layer per column."""
    h, rho = np.asarray(columns_args[0], dtype=float), columns_args[1]
    if h.ndim != 2 or h.shape[1] != 1 or np.ndim(rho) != 0 or np.any(np.asarray(columns_args[2]) != 0):
        raise ValueError("the sampled oracle takes one unheated constant-density layer per column")
    w, d = np.asarray(state["displacement_m"]).ravel(), np.asarray(state["depth_m"]).ravel()
    t = None if transfer_pa is None else np.asarray(transfer_pa, dtype=float).ravel()
    rows = []
    for i in (range(h.shape[0]) if index is None else index):
        j.check_deadline(deadline)
        rows.append(smooth_core_column(datum, [h[i, 0]], [rho], [rho], rho_w_kg_m3=rho_w_kg_m3, water_depth_m=d[i],
                                       displacement_m=w[i], core_top_m=top_m, core_bottom_m=bottom_m,
                                       transfer_pa=None if t is None else t[i]))
    return {key: np.array([row[key] for row in rows]) for key in ("anomaly_j_m2", "basal_pressure_pa", "column_excess_pa")}


def produce(datum, columns_args, core, plate, state, volume):
    return core_loaded_gpe(datum, *columns_args, core, plate, state, volume_m3=volume, **water.ARGS)


def same_result(result, joined):
    """Every field of the unchanged join's result is present and equal (arrays bitwise)."""
    return all(key in result and (np.array_equal(result[key], value) if isinstance(value, np.ndarray)
                                  else result[key] == value) for key, value in joined.items())


def attempt(expected, datum, columns_args, core, plate, state, volume):
    inputs = (datum, columns_args, core, plate, state, volume)
    before = j.fingerprint(inputs)
    code = j.refusal_code(lambda: produce(datum, columns_args, core, plate, state, volume))
    return dict(expected=expected, code=code, refused_as_expected=code == expected,
                inputs_unchanged=before == j.fingerprint(inputs))


def declaration_attempt(expected, declaration):
    before = j.fingerprint(declaration)
    code = j.refusal_code(lambda: elastic_core(declaration))
    return dict(expected=expected, code=code, refused_as_expected=code == expected,
                inputs_unchanged=before == j.fingerprint(declaration))


def _span(values):
    values = np.asarray(values)
    return float(np.max(values)-np.min(values))


def _largest(values, mask=None):
    values = np.abs(np.asarray(values, dtype=float))
    values = values if mask is None else values[mask]
    return float(np.max(values)) if values.size else 0.


def _core(spec, key="core", **change):
    return elastic_core(dict(spec["controls"][key], **change))


def _plate(core, ret, shape):
    lengths = ret["water"]["plate"]
    return core_plate(core, ret["datum"], shape, lengths["length_x_m"], lengths["length_y_m"],
                      rho_w_kg_m3=ret["rho_w_kg_m3"])


def _fixture(core, ret, n):
    """The retained partly wet water fixture on the core's own plate, with the retained GPE crust."""
    plate = _plate(core, ret, (n, n))
    retained_plate, bed, volume = water.fixture(n, ret["water"])
    cols = j.crust_columns(ret, bed)
    z0 = gpe.columns(ret["datum"], *cols)["surface_elevation_m"].reshape(plate.shape)
    return plate, retained_plate, cols, z0, volume


# ----------------------------------------------------------------------------- campaign controls (frozen case)

def derivation_control(spec, ret, deadline=None):
    """D and c from the declared interval; the shear density's integral, centroid and running share, and D from the
    core's own stresses, by independent quadrature; the same stiffness at other depths; the explicit surface core."""
    j.check_deadline(deadline)
    core, surface = _core(spec), _core(spec, "surface_core")
    delta = spec["controls"]["core_shift_m"]
    shifted = _core(spec, top_depth_m=core.top_depth_m+delta, bottom_depth_m=core.bottom_depth_m+delta)
    a, b, h, c = core.top_depth_m, core.bottom_depth_m, core.thickness_m, core.shear_transfer_depth_m
    lengths, n = ret["water"]["plate"], ret["water"]["grids"][0]
    plate = _plate(core, ret, (n, n))
    retained_plate = water.Plate((n, n), lengths["length_x_m"], lengths["length_y_m"], lengths["elastic_thickness_m"])
    total, moment = shear_moments(a, b)
    shares = [(u, carried_fraction(a+u*h, a, b)) for u in (.25, .5, .75)]
    rigidity = kirchhoff_rigidity(core)
    rel = POLICY["operator_relative"]
    return j.finish(dict(
        retained_plate_carries_core=plate == retained_plate and plate.rigidity_n_m == core.rigidity_n_m,
        rigidity_from_core_stresses=abs(rigidity-core.rigidity_n_m) <= rel*core.rigidity_n_m,
        density_integrates_to_one=abs(total-1) <= rel,
        density_centroid_is_mid_surface=abs(moment-c) <= rel*b,
        running_share_is_cubic=all(abs(share-(3*u*u-2*u**3)) <= rel for u, share in shares),
        running_share_symmetric=abs(shares[0][1]+shares[2][1]-1) <= rel,
        stiffness_does_not_locate_core=(surface.rigidity_n_m == core.rigidity_n_m
                                        and _plate(surface, ret, (n, n)) == plate
                                        and surface.shear_transfer_depth_m != c),
        explicit_surface_core_is_retained_level=(surface.top_depth_m == 0
                                                 and surface.shear_transfer_depth_m == ret["control_shear_depth_m"]),
        shift_keeps_stiffness_moves_depth=(shifted.rigidity_n_m == core.rigidity_n_m
                                           and shifted.shear_transfer_depth_m == c+delta)),
        top_depth_m=a, bottom_depth_m=b, thickness_m=h, rigidity_n_m=core.rigidity_n_m,
        rigidity_from_core_stresses_n_m=rigidity, shear_transfer_depth_m=c, density_integral=total,
        density_first_moment_m=moment, running_shares=[[u, share] for u, share in shares],
        surface_core_shear_transfer_depth_m=surface.shear_transfer_depth_m)


def fourier_control(spec, ret, deadline=None):
    """Fully wet (2,1) mode on the core's own plate: the smooth through-core profile against the producer for both
    signs of B, force balance from the core's Kirchhoff shear, water once, datum handling and the retained solver."""
    j.check_deadline(deadline)
    cfg, datum, gamma = spec["controls"]["fourier"], ret["datum"], ret["reduction"]
    shape, (mx, my) = tuple(cfg["shape"]), cfg["mode"]
    core, surface = _core(spec), _core(spec, "surface_core")
    a, b, c = core.top_depth_m, core.bottom_depth_m, core.shear_transfer_depth_m
    plate = _plate(core, ret, shape)
    y, x = np.indices(shape)
    amplitude, hw = cfg["bed_amplitude_m"], cfg["mean_water_m"]
    cols = j.crust_columns(ret, amplitude*np.cos(2*np.pi*(mx*x/shape[1]+my*y/shape[0])))
    volume = hw*plate.length_x_m*plate.length_y_m
    f = 1-ret["crust_density_kg_m3"]/datum.mantle_density_kg_m3

    def exact(dat):                           # closed-form fully wet equilibrium on this datum's dry surface
        z0 = gpe.columns(dat, *cols)["surface_elevation_m"].reshape(shape)
        return z0, j.fourier_mode_state(plate, z0, mode=(mx, my), mean_water_m=hw, bed_amplitude_m=amplitude,
                                        surface_mean_m=j.reference_top(dat)+f*ret["mean_crust_m"])
    z0, state = exact(datum)
    r = produce(datum, cols, core, plate, state, volume)
    joined = j.water_loaded_gpe(datum, *cols, plate, state, volume_m3=volume, shear_level=core_shear_level(core),
                                **water.ARGS)
    v, excess = r["gpe_anomaly_j_m2"], r["basal_overburden_excess_pa"]
    transfer = kirchhoff_transfer(core, plate, state["displacement_m"])
    support = j.flexural_support(plate, state["displacement_m"])
    load_scale = plate.rho_w_kg_m3*plate.gravity_m_s2*float(np.max(state["depth_m"]))
    oracle = smooth_potential(datum, cols, state, a, b, rho_w_kg_m3=plate.rho_w_kg_m3, transfer_pa=transfer,
                              deadline=deadline)
    v_q, basal = oracle["anomaly_j_m2"].reshape(shape), oracle["basal_pressure_pa"].reshape(shape)
    tol = j.quadrature_tolerance(datum)
    spacing = min(plate.length_x_m/shape[1], plate.length_y_m/shape[0])
    big = np.abs(excess) >= .5*float(np.max(np.abs(excess)))
    positive, negative = excess > 0, excess < 0
    t, t_q = (j.planar_traction(field, plate=plate, reduction=gamma) for field in (v, v_q))
    net = float(np.max(np.abs(t.sum(axis=(0, 1)))))
    steps = [j.water_loaded_gpe(datum, *cols, plate, state, volume_m3=volume, shear_level={
        "depth_below_bed_m": face, "basis": "contrast only: a step at a core face, not the derived level"},
        **water.ARGS)["gpe_anomaly_j_m2"] for face in (a, b)]
    solved = plate.equilibrium(z0, volume, **water.ARGS)
    r_solved = produce(datum, cols, core, plate, solved, volume)
    dw = POLICY["closed_form_displacement_m"]
    bound = j.perturbation_bound(plate, r, c, dw, 2*dw)+tol
    deeper = j.deepen(datum, spec["controls"]["datum_extension_m"])
    moved = j.translate(datum, spec["controls"]["vertical_translation_m"])
    r_deeper = produce(deeper, cols, core, plate, state, volume)
    r_moved = produce(moved, cols, core, plate, exact(moved)[1], volume)
    v_q_deeper = smooth_potential(deeper, cols, state, a, b, rho_w_kg_m3=plate.rho_w_kg_m3, transfer_pa=transfer,
                                  deadline=deadline)["anomaly_j_m2"].reshape(shape)
    r_surface = produce(datum, cols, surface, plate, state, volume)
    retained_level = j.water_loaded_gpe(datum, *cols, plate, state, volume_m3=volume,
                                        shear_level=ret["control_shear_level"], **water.ARGS)
    water_mass = float(np.sum(r["water_mass_kg_m2"]))*plate.length_x_m*plate.length_y_m/v.size
    discriminating = POLICY["discrimination_factor"]*tol
    return j.finish(dict(
        flexural=r["regime"] == j.FLEXURAL and r_solved["regime"] == j.FLEXURAL,
        producer_is_unchanged_join=same_result(r, joined),
        derived_level_supplied=(r["shear_level"]["depth_below_bed_m"] == c
                                and r["elastic_core"]["shear_transfer_depth_m"] == c
                                and r["elastic_core"]["rigidity_n_m"] == plate.rigidity_n_m),
        core_shear_is_plate_support=_largest(transfer-support) <= POLICY["operator_relative"]*load_scale,
        core_shear_carries_excess=_largest(transfer-excess) <= POLICY["force_relative_tolerance"]*load_scale,
        basal_pressure_is_datum_pressure=_largest(basal-datum.pressure_pa) <= POLICY["force_relative_tolerance"]*load_scale,
        both_signs_present=bool(np.any(positive & big) and np.any(negative & big)),
        smooth_profile_where_excess_positive=_largest(v_q-v, positive) <= tol,
        smooth_profile_where_excess_negative=_largest(v_q-v, negative) <= tol,
        face_steps_differ=min(_largest(step-v_q) for step in steps) > discriminating,
        traction_matches_smooth_profile=_largest(t-t_q) <= gamma*tol/spacing,
        periodic_net_force_zero=net <= 4*v.size*np.finfo(float).eps*_largest(v)*gamma/spacing,
        water_counted_once=(abs(water_mass-plate.rho_w_kg_m3*volume)
                            <= POLICY["volume_relative_tolerance"]*plate.rho_w_kg_m3*volume),
        solver_within_propagated=_largest(r_solved["gpe_anomaly_j_m2"]-v) <= bound,
        datum_extension_bitwise=np.array_equal(r_deeper["gpe_anomaly_j_m2"], v),
        datum_translation_bitwise=np.array_equal(r_moved["gpe_anomaly_j_m2"], v),
        smooth_profile_datum_invariant=_largest(v_q_deeper-v_q) <= tol+j.quadrature_tolerance(deeper),
        explicit_surface_core_is_retained_level=np.array_equal(r_surface["gpe_anomaly_j_m2"],
                                                               retained_level["gpe_anomaly_j_m2"])),
        cells=v.size, core_top_m=a, core_bottom_m=b, shear_transfer_depth_m=c,
        max_abs_basal_excess_pa=_largest(excess), core_term_range_j_m2=_span(c*excess),
        max_core_shear_minus_support_pa=_largest(transfer-support),
        max_core_shear_minus_excess_pa=_largest(transfer-excess),
        max_basal_pressure_error_pa=_largest(basal-datum.pressure_pa),
        max_smooth_difference_positive_j_m2=_largest(v_q-v, positive),
        max_smooth_difference_negative_j_m2=_largest(v_q-v, negative),
        min_face_step_difference_j_m2=min(_largest(step-v_q) for step in steps),
        max_traction_difference_pa=_largest(t-t_q), max_abs_traction_pa=_largest(t), net_traction_pa=net,
        solver_potential_difference_j_m2=_largest(r_solved["gpe_anomaly_j_m2"]-v), solver_bound_j_m2=bound,
        quadrature_tolerance_j_m2=tol)


def core_shift_control(spec, ret, deadline=None):
    """A physical shift of the core by Delta on the partly wet retained fixture, against coordinate-datum changes.

    Same h, E and nu: the same plate, water and deflection; the potential changes by Delta B and the traction by
    -gamma Delta grad B. Deepening or translating the datum by the same Delta moves no material and changes neither.
    """
    j.check_deadline(deadline)
    datum, gamma, delta = ret["datum"], ret["reduction"], spec["controls"]["core_shift_m"]
    n = spec["controls"]["fixture_grid"]
    core = _core(spec)
    shifted = _core(spec, top_depth_m=core.top_depth_m+delta, bottom_depth_m=core.bottom_depth_m+delta)
    plate, retained_plate, cols, z0, volume = _fixture(core, ret, n)
    plate_shifted = _plate(shifted, ret, (n, n))
    state, state_shifted = (p.equilibrium(z0, volume, **water.ARGS) for p in (plate, plate_shifted))
    r = produce(datum, cols, core, plate, state, volume)
    r_shifted = produce(datum, cols, shifted, plate_shifted, state_shifted, volume)
    v, v_shifted, excess = r["gpe_anomaly_j_m2"], r_shifted["gpe_anomaly_j_m2"], r["basal_overburden_excess_pa"]
    rounding = POLICY["operator_relative"]*max(_largest(v), _largest(v_shifted))
    spacing = min(plate.length_x_m/n, plate.length_y_m/n)
    t, t_shifted, t_predicted = (j.planar_traction(field, plate=plate, reduction=gamma)
                                 for field in (v, v_shifted, delta*excess))
    tol = j.quadrature_tolerance(datum)
    index = np.arange(0, n*n, POLICY["quadrature_sample_stride"])
    q, q_shifted = (smooth_potential(datum, cols, state, top, bottom, rho_w_kg_m3=plate.rho_w_kg_m3, index=index,
                                     deadline=deadline)
                    for top, bottom in ((core.top_depth_m, core.bottom_depth_m),
                                        (shifted.top_depth_m, shifted.bottom_depth_m)))
    deeper = j.deepen(datum, delta)
    r_deeper = produce(deeper, cols, core, plate, state, volume)
    moved = j.translate(datum, delta)
    state_moved = plate.equilibrium(gpe.columns(moved, *cols)["surface_elevation_m"].reshape(plate.shape), volume,
                                    **water.ARGS)
    r_moved = produce(moved, cols, core, plate, state_moved, volume)
    tr, c = POLICY["translated_displacement_m"], core.shear_transfer_depth_m
    wet = float(np.mean(state["depth_m"] > 0))
    return j.finish(dict(
        same_stiffness_plate=plate_shifted == plate and plate == retained_plate,
        same_water_and_deflection=(all(np.array_equal(state[key], state_shifted[key])
                                       for key in ("displacement_m", "bed_m", "depth_m"))
                                   and state["sea_level_m"] == state_shifted["sea_level_m"]),
        partly_wet_flexural=0 < wet < 1 and r["regime"] == r_shifted["regime"] == j.FLEXURAL,
        depth_moves_by_delta=r_shifted["elastic_core"]["shear_transfer_depth_m"] == c+delta,
        potential_changes_by_delta_excess=_largest(v_shifted-v-delta*excess) <= rounding,
        traction_changes_by_minus_gamma_delta_grad_excess=_largest(t_shifted-t-t_predicted) <= rounding*gamma/spacing,
        change_is_nonuniform=_span(delta*excess) > POLICY["discrimination_factor"]*tol,
        smooth_profile_matches_both=(_largest(q["anomaly_j_m2"]-v.ravel()[index]) <= tol
                                     and _largest(q_shifted["anomaly_j_m2"]-v_shifted.ravel()[index]) <= tol),
        smooth_shift_is_delta_excess=_largest(q_shifted["anomaly_j_m2"]-q["anomaly_j_m2"]
                                              - delta*q["column_excess_pa"]) <= 2*tol,
        datum_deepening_leaves_potential=np.array_equal(r_deeper["gpe_anomaly_j_m2"], v),
        datum_translation_resolve_matches=(_largest(state_moved["displacement_m"]-state["displacement_m"]) <= tr
                                           and _largest(state_moved["depth_m"]-state["depth_m"]) <= 2*tr),
        datum_translation_leaves_potential=(_largest(r_moved["gpe_anomaly_j_m2"]-v)
                                            <= j.perturbation_bound(plate, r, c, tr, 2*tr)+tol),
        core_translates_with_column=_largest(r_moved["loaded_bed_m"]-r["loaded_bed_m"]-delta) <= 2*tr),
        cells=n*n, wet_fraction=wet, core_shift_m=delta, max_abs_basal_excess_pa=_largest(excess),
        potential_change_range_j_m2=_span(v_shifted-v), max_potential_change_error_j_m2=_largest(v_shifted-v-delta*excess),
        rounding_bound_j_m2=rounding, max_traction_change_error_pa=_largest(t_shifted-t-t_predicted),
        max_traction_change_pa=_largest(t_shifted-t), sampled_columns=len(index),
        max_smooth_difference_j_m2=max(_largest(q["anomaly_j_m2"]-v.ravel()[index]),
                                       _largest(q_shifted["anomaly_j_m2"]-v_shifted.ravel()[index])),
        translated_max_potential_change_j_m2=_largest(r_moved["gpe_anomaly_j_m2"]-v))


def limits_control(spec, ret, deadline=None):
    """Dry and uniform-load limits admit a core (its depth immaterial); zero rigidity is not a core and is refused,
    while the unchanged join still takes that Airy limit without one."""
    j.check_deadline(deadline)
    datum, gamma, n = ret["datum"], ret["reduction"], spec["controls"]["fixture_grid"]
    declared, core = spec["controls"]["core"], _core(spec)
    plate, _, cols, z0, volume = _fixture(core, ret, n)
    dry = gpe.columns(datum, *cols)
    r_dry = produce(datum, cols, core, plate, plate.equilibrium(z0, 0., **water.ARGS), 0.)
    t_dry, t_reference = (j.planar_traction(field, plate=plate, reduction=gamma)
                          for field in (r_dry["gpe_anomaly_j_m2"], dry["gpe_anomaly_j_m2"].reshape(plate.shape)))
    cfg = spec["controls"]["uniform"]
    shape = tuple(cfg["shape"])
    flat = j.crust_columns(ret, np.zeros(shape))
    uniform_plate = _plate(core, ret, shape)
    z_flat = gpe.columns(datum, *flat)["surface_elevation_m"].reshape(shape)
    uniform_volume = cfg["mean_water_m"]*uniform_plate.length_x_m*uniform_plate.length_y_m
    uniform_state = uniform_plate.equilibrium(z_flat, uniform_volume, **water.ARGS)
    r_uniform = produce(datum, flat, core, uniform_plate, uniform_state, uniform_volume)
    bare = j.water_loaded_gpe(datum, *flat, uniform_plate, uniform_state, volume_m3=uniform_volume, **water.ARGS)
    lengths = ret["water"]["plate"]
    airy_plate = water.Plate((n, n), lengths["length_x_m"], lengths["length_y_m"], 0.)
    airy_state = airy_plate.equilibrium(z0, volume, **water.ARGS)
    refused = attempt(NOT_A_CORE, datum, cols, declared, airy_plate, airy_state, volume)
    airy = j.water_loaded_gpe(datum, *cols, airy_plate, airy_state, volume_m3=volume, **water.ARGS)
    degenerate = {"zero_modulus": declaration_attempt(INVALID_CORE, dict(declared, young_pa=0)),
                  "zero_thickness": declaration_attempt(INVALID_CORE, dict(declared,
                                                                           bottom_depth_m=declared["top_depth_m"]))}
    tol = j.quadrature_tolerance(datum)
    spacing = min(uniform_plate.length_x_m/shape[1], uniform_plate.length_y_m/shape[0])
    return j.finish(dict(
        dry_compensated=(r_dry["regime"], r_dry["no_transfer_limit"]) == (j.COMPENSATED, j.ZERO_WATER),
        dry_potential_bitwise=np.array_equal(r_dry["gpe_anomaly_j_m2"], dry["gpe_anomaly_j_m2"].reshape(plate.shape)),
        dry_traction_bitwise=np.array_equal(t_dry, t_reference),
        uniform_compensated=(r_uniform["regime"], r_uniform["no_transfer_limit"]) == (j.COMPENSATED, j.UNIFORM_LOAD),
        uniform_core_depth_immaterial=_largest(r_uniform["gpe_anomaly_j_m2"]-bare["gpe_anomaly_j_m2"]) <= tol,
        uniform_potential=_span(r_uniform["gpe_anomaly_j_m2"]) <= tol,
        uniform_zero_traction=_largest(j.planar_traction(r_uniform["gpe_anomaly_j_m2"], plate=uniform_plate,
                                                         reduction=gamma)) <= gamma*tol/spacing,
        zero_rigidity_is_not_a_core=refused["refused_as_expected"] and refused["inputs_unchanged"],
        zero_rigidity_joins_without_core=(airy["regime"], airy["no_transfer_limit"]) == (j.COMPENSATED, j.ZERO_RIGIDITY),
        degenerate_cores_refused=all(case["refused_as_expected"] and case["inputs_unchanged"]
                                     for case in degenerate.values())),
        dry_cells=n*n, uniform_cells=int(np.prod(shape)), max_abs_uniform_excess_pa=_largest(r_uniform["basal_overburden_excess_pa"]),
        uniform_core_term_max_j_m2=core.shear_transfer_depth_m*_largest(r_uniform["basal_overburden_excess_pa"]),
        zero_rigidity_refusal=refused, degenerate=degenerate)


def refusals_control(spec, ret, deadline=None):
    """Absent placement, Te/D-only, out-of-rock, varying or multiple cores, non-finite values, invalid provenance and
    incompatible stiffness, material or solver state: each refused with its code, inputs byte-identical."""
    j.check_deadline(deadline)
    datum, n = ret["datum"], spec["controls"]["fixture_grid"]
    declared, rcfg, lengths = spec["controls"]["core"], spec["controls"]["refusal"], ret["water"]["plate"]
    core = elastic_core(declared)
    plate, _, cols, z0, volume = _fixture(core, ret, n)
    state = plate.equilibrium(z0, volume, **water.ARGS)
    thinnest, h = thinnest_rock_m(cols[0]), cols[0]
    a, b, margin = declared["top_depth_m"], declared["bottom_depth_m"], rcfg["below_rock_margin_m"]

    def plate_with(**change):
        base = dict(elastic_thickness_m=core.thickness_m, young_pa=core.young_pa, poisson=core.poisson)
        return water.Plate(plate.shape, lengths["length_x_m"], lengths["length_y_m"], **dict(base, **change))

    def varied(**change):
        return dict(declared, **change)
    other = plate_with(elastic_thickness_m=rcfg["foreign_elastic_thickness_m"])
    stale = other.equilibrium(z0, volume, **water.ARGS)
    airy = plate_with(elastic_thickness_m=0.).equilibrium(z0, volume, **water.ARGS)
    unplaced = {key: value for key, value in declared.items() if key not in ("top_depth_m", "bottom_depth_m")}
    outside = varied(top_depth_m=thinnest+margin-core.thickness_m, bottom_depth_m=thinnest+margin)
    edge = varied(top_depth_m=thinnest-core.thickness_m, bottom_depth_m=thinnest)
    scaled = core.young_pa*(core.thickness_m/(b-a-rcfg["same_rigidity_thinner_by_m"]))**3
    j.check_deadline(deadline)
    cases = {
        "placement_absent": attempt(UNPLACED, datum, cols, unplaced, plate, state, volume),
        "te_only": attempt(UNPLACED, datum, cols, dict(unplaced, elastic_thickness_m=core.thickness_m), plate, state,
                           volume),
        "rigidity_only": attempt(UNPLACED, datum, cols, dict(unplaced, rigidity_n_m=core.rigidity_n_m), plate, state,
                                 volume),
        "null_placement": attempt(UNPLACED, datum, cols, varied(top_depth_m=None), plate, state, volume),
        "declared_te_with_placement": attempt(INVALID_CORE, datum, cols, varied(elastic_thickness_m=core.thickness_m),
                                              plate, state, volume),
        "inverted_interval": attempt(INVALID_CORE, datum, cols, varied(top_depth_m=b, bottom_depth_m=a), plate, state,
                                     volume),
        "zero_thickness": attempt(INVALID_CORE, datum, cols, varied(bottom_depth_m=a), plate, state, volume),
        "above_rock_surface": attempt(OUTSIDE_ROCK, datum, cols, varied(top_depth_m=rcfg["above_rock_top_m"]), plate,
                                      state, volume),
        "below_thinnest_rock_base": attempt(OUTSIDE_ROCK, datum, cols, outside, _plate(elastic_core(outside), ret,
                                                                                       plate.shape), state, volume),
        "horizontally_varying_depth": attempt(UNSUPPORTED_CORE, datum, cols, varied(top_depth_m=np.full(n*n, a)), plate,
                                              state, volume),
        "horizontally_varying_modulus": attempt(UNSUPPORTED_CORE, datum, cols, varied(
            young_pa=[core.young_pa, 2*core.young_pa]), plate, state, volume),
        "multiple_cores": attempt(UNSUPPORTED_CORE, datum, cols, [declared, varied(top_depth_m=b, bottom_depth_m=b+1.)],
                                  plate, state, volume),
        "layered_core": attempt(UNSUPPORTED_CORE, datum, cols, varied(layers=[declared]), plate, state, volume),
        "nonfinite_depth": attempt(INVALID_CORE, datum, cols, varied(bottom_depth_m=float("nan")), plate, state, volume),
        "nonfinite_modulus": attempt(INVALID_CORE, datum, cols, varied(young_pa=float("inf")), plate, state, volume),
        "boolean_modulus": attempt(INVALID_CORE, datum, cols, varied(young_pa=True), plate, state, volume),
        "nonpositive_modulus": attempt(INVALID_CORE, datum, cols, varied(young_pa=0), plate, state, volume),
        "poisson_at_half": attempt(INVALID_CORE, datum, cols, varied(poisson=.5), plate, state, volume),
        "poisson_at_minus_one": attempt(INVALID_CORE, datum, cols, varied(poisson=-1), plate, state, volume),
        "auxetic_not_retained": attempt(UNSUPPORTED_CORE, datum, cols, varied(poisson=rcfg["auxetic_poisson"]), plate,
                                        state, volume),
        "blank_basis": attempt(INVALID_CORE, datum, cols, varied(basis=" "), plate, state, volume),
        "missing_material": attempt(INVALID_CORE, datum, cols, varied(material=""), plate, state, volume),
        "non_text_basis": attempt(INVALID_CORE, datum, cols, varied(basis=b"control"), plate, state, volume),
        "sea_surface_reference": attempt(INVALID_CORE, datum, cols, varied(depth_reference="sea_surface"), plate, state,
                                         volume),
        "thickness_mismatch": attempt(MISMATCH, datum, cols, declared, other, stale, volume),
        "modulus_mismatch": attempt(MISMATCH, datum, cols, declared, plate_with(young_pa=rcfg["foreign_young_pa"]),
                                    state, volume),
        "poisson_mismatch": attempt(MISMATCH, datum, cols, declared, plate_with(poisson=rcfg["foreign_poisson"]), state,
                                    volume),
        "same_rigidity_other_material": attempt(MISMATCH, datum, cols, varied(
            bottom_depth_m=b-rcfg["same_rigidity_thinner_by_m"], young_pa=scaled), plate, state, volume),
        "zero_rigidity_plate": attempt(NOT_A_CORE, datum, cols, declared, plate_with(elastic_thickness_m=0.), airy,
                                       volume),
        "foreign_plate": attempt(j.UNSUPPORTED, datum, cols, declared, {"shape": plate.shape}, state, volume),
        "state_from_other_rigidity": attempt(j.EQUILIBRIUM, datum, cols, declared, plate, stale, volume),
        "airy_state_on_core_plate": attempt(j.EQUILIBRIUM, datum, cols, declared, plate, airy, volume),
        "mantle_density_mismatch": attempt(j.MATERIAL, datum, cols, declared, plate_with(rho_m_kg_m3=3250.), state,
                                           volume),
        "gravity_mismatch": attempt(j.MATERIAL, datum, cols, declared, plate_with(gravity_m_s2=9.8), state, volume),
        "invalid_columns": attempt(j.COLUMNS, datum, (-h,)+cols[1:], declared, plate, state, volume),
        "column_count": attempt(j.SHAPE, datum, (h[:-1],)+cols[1:], declared, plate, state, volume),
    }
    edge_result = produce(datum, cols, edge, _plate(elastic_core(edge), ret, plate.shape), state, volume)
    checks = {name: case["refused_as_expected"] and case["inputs_unchanged"] for name, case in cases.items()}
    checks["thinnest_rock_base_admitted"] = (edge_result["regime"] == j.FLEXURAL
                                             and edge_result["elastic_core"]["rock_below_core_m"] == 0)
    return j.finish(checks, cases=cases, thinnest_rock_m=thinnest)


def timing_control(spec, ret, deadline=None):
    """Raw interleaved timings of the unchanged join with the derived level and of the core producer; no claim."""
    core, rows = _core(spec), []
    shear = core_shear_level(core)
    for n in spec["controls"]["timing_grids"]:
        j.check_deadline(deadline)
        plate, _, cols, z0, volume = _fixture(core, ret, n)
        state = plate.equilibrium(z0, volume, **water.ARGS)
        samples = {"join_with_derived_level": [], "core_producer": []}
        for _ in range(POLICY["timing_repetitions"]):
            j.check_deadline(deadline)
            begin = time.perf_counter()
            j.water_loaded_gpe(ret["datum"], *cols, plate, state, volume_m3=volume, shear_level=shear, **water.ARGS)
            samples["join_with_derived_level"].append(time.perf_counter()-begin)
            begin = time.perf_counter()
            produce(ret["datum"], cols, core, plate, state, volume)
            samples["core_producer"].append(time.perf_counter()-begin)
        medians = {key: float(np.median(value)) for key, value in samples.items()}
        rows.append(dict(cells=n*n, samples_seconds=samples, median_seconds=medians,
                         median_overhead_seconds=medians["core_producer"]-medians["join_with_derived_level"]))
    finite = all(math.isfinite(s) and s >= 0 for row in rows for v in row["samples_seconds"].values() for s in v)
    return j.finish(dict(finite_nonnegative=finite), grids=rows,
                    scope="raw interleaved timings of the producer and the join it wraps on identical inputs; "
                          "no saving or cost is claimed")


CONTROLS = (("derivation", derivation_control), ("smooth_profile_fourier", fourier_control),
            ("core_shift", core_shift_control), ("limits", limits_control), ("refusals", refusals_control),
            ("timing", timing_control))


# ----------------------------------------------------------------------------- case, bindings and receipt

def load_case(path=None):
    spec = json.loads((ROOT/CASE if path is None else Path(path)).read_text(encoding="utf-8"))
    if (type(spec) is not dict or set(spec) != CASE_FIELDS or spec["schema"] != CASE_SCHEMA
            or spec["contract"] != CONTRACT or spec["policy"] != POLICY):
        raise ValueError("case fields/schema/contract/policy differ from the executable")
    return spec


def retained_inputs(spec):
    """Read-only retained values through the accepted water/GPE declarations; refuse drift from this case."""
    base = j.load_case()
    ret = j.retained_inputs(base)
    observed = {"water_gpe_case": {"retained": base["retained"],
                                   "control_shear_depth_m": base["controls"]["shear_level"]["depth_below_bed_m"]}}
    if observed != spec["retained"]:
        raise ValueError("retained water/GPE case values differ from this control's frozen declaration")
    for key in COPIED:
        if POLICY[key] != j.POLICY[key]:
            raise ValueError("copied tolerance differs from the retained water/GPE executable: "+key)
    return dict(ret, control_shear_level=dict(base["controls"]["shear_level"]),
                control_shear_depth_m=base["controls"]["shear_level"]["depth_below_bed_m"],
                rho_w_kg_m3=water.Plate((4, 4), 1., 1., 1.).rho_w_kg_m3)


def digest(name):
    return hashlib.sha256((ROOT/name).read_bytes()).hexdigest()


def bindings():
    return {name: digest(name) for name in NEW_FILES+RETAINED+tuple(ACCEPTED_RECEIPTS)}


def evidence_match(current):
    """Retained sources are the bytes their accepted receipts recorded, and imports resolve to them.

    Gated: the receipts and every retained file this producer executes or reads. Reported only: the other
    files those receipts recorded (their method documents and tests), which this producer does not run.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        result = dict(schema=EVIDENCE_SCHEMA, status="INCOMPLETE", scientific_acceptance=False, contract=CONTRACT,
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
                    j.check_deadline(deadline)              # an overrunning control is not recorded as a pass
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
            body = json.dumps(j.jsonable(result), indent=2, allow_nan=False)
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
