"""I01 MC-03: instantaneous one-dimensional two-phase compaction closure for melt segregation.

WORKING NON-CANON. For ONE fixed column state (liquid volume fraction and melting rate per cell), declared constant
phase densities, melt, shear and bulk viscosities and a porosity-power permeability, one symmetric tridiagonal solve
determines the overpressure Sigma = P_f - P_total = (zeta + 4 eta/3) dW/dz, the Darcy segregation flux
q = phi (w_f - W) = -(K/mu)(dSigma/dz - (1 - phi)(rho_s - rho_f) g) and the matrix velocity W, with the mixture
volume balance d(W + q)/dz = Gamma (1/rho_f - 1/rho_s). This is McKenzie's (1984) formulation in one dimension as
written by Spiegelman (1993, eqs 1-4, 13, 14 and section 3.2); it agrees with ASPECT's melt-transport eqs 29-31.
z points upward. Nothing is time-stepped: porosity, melting rate, thermochemistry and the domain stay fixed, and those
couplings remain I05/I06 work. Not a focusing, axial-lid or calibrated-extraction model; current selection status
belongs in docs/CURRENT_STATE.md, not in this source-bound control.
Run: python -B tectonics/tools/check_i01_melt_segregation.py --output NEW.json   (campaign; exclusive new receipt)
     python -B tectonics/tools/check_i01_melt_segregation.py --timing           (raw matched timings; no claim)
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import dataclasses
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.linalg import cho_solve_banded, cholesky_banded

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "atlas.two-phase-compaction-1d.v1"
EVIDENCE_SCHEMA = "atlas.i01-melt-segregation.v1"
CASE_SCHEMA = "atlas.i01-melt-segregation-case.v1"
CASE = "cases/i01_melt_segregation_v1.json"
PASS = "PASS_BOUNDED_CONTROLS_ONLY"
NEW_FILES = ("tools/check_i01_melt_segregation.py", "cases/i01_melt_segregation_v1.json",
             "docs/I01_MELT_SEGREGATION.md", "tests/test_i01_melt_segregation.py")
CASE_FIELDS = {"schema", "status", "contract", "document", "policy", "synthetic", "controls", "source"}
# Frozen before execution; cases/i01_melt_segregation_v1.json must carry exactly this policy.
POLICY = {
    "maximum_cells": 65536,                         # bounded memory: every prepared array is O(cells)
    "maximum_cell_over_compaction_length": 0.25,    # h <= delta/4 in every wet cell, else refused (never coarsened)
    "balance_relative": 1e-12,                      # per-cell mixture and phase balances: rounding only
    "compatibility_relative": 1e-12,                # both matrix velocities declared: exactly rounded volume balance
    "pressure_relative": 1e-11,                     # the reported fluid pressure reproduces the Darcy flux
    "constant_coefficient_error_coefficient": 0.5,  # error/max|exact| <= 0.5 (h/min(delta, L))^2 vs the closed form
    "order_window": [1.8, 2.2],                     # observed order between successive halvings of h
    "manufactured_error_cap": 1e-2,                 # finest manufactured error; excludes O(1) mistakes only
    "discrimination_fraction": 0.25,                # a claimed contrast exceeds a quarter of its reference
    "gauss_points_per_cell": 8,                     # manufactured W reference quadrature
    "timing_repetitions": 5,
    "maximum_seconds": 120.0,
}
ASSUMPTIONS = {
    "geometry": "one vertical column of fixed cells; z upward; gravity is -g z",
    "time": "instantaneous: liquid volume fraction, melting rate, thermochemistry and domain fixed; tendencies are "
            "reported, never integrated",
    "phases": "individually incompressible; one declared constant density each; rho_s and rho_f may differ",
    "reaction_volume": "retained: d(W + q)/dz = Gamma (1/rho_f - 1/rho_s); never R = 0 with unequal densities",
    "momentum": "creeping flow with one liquid pressure: dP_f/dz = d/dz[(zeta + 4 eta/3) dW/dz] - rho_bar g",
    "liquid": "Darcy flux relative to the matrix; isotropic K = K_r (phi/phi_K)^n with n > 0",
    "matrix": "constant shear viscosity eta; bulk viscosity zeta = zeta_r (phi/phi_z)^-m with m >= 0",
    "dry": "phi = 0 exactly: no liquid or liquid pressure, zero permeability, no compaction; no floor or threshold",
}
INVALID = "REFUSED_INVALID_INPUT"
UNSUPPORTED = "REFUSED_UNSUPPORTED_INPUT"
PROVENANCE = "REFUSED_PROVENANCE_ABSENT"
DECLARATION = "REFUSED_BOUNDARY_DECLARATION"
INCOMPATIBLE = "REFUSED_INCOMPATIBLE_BOUNDARY"
DRY_BOUNDARY = "REFUSED_DRY_BOUNDARY_CONDITION"
DRY_REACTION = "REFUSED_DRY_REACTION"
RANGE = "REFUSED_NUMERIC_RANGE"
UNRESOLVED = "REFUSED_UNRESOLVED_COMPACTION_LENGTH"
MISMATCH = "REFUSED_OPERATOR_MISMATCH"
KINDS = ("flux", "rigid", "free_flux")


# ----------------------------------------------------------------------------- refusals and validated values

class Refusal(ValueError):
    """Explicit, atomic refusal with a stable code: no result exists and no input has been modified."""

    def __init__(self, code, detail):
        super().__init__(code+": "+detail)
        self.code = code


def _frozen(values, dtype=float):
    """A read-only copy backed by immutable bytes (a writeable flag on an owning array could be reversed)."""
    out = np.array(values, dtype=dtype)
    if out.size == 0:
        out.setflags(write=False)
        return out
    return np.frombuffer(out.tobytes(), dtype=out.dtype).reshape(out.shape)


def _real(value, name, code=INVALID):
    """A finite real scalar. A sequence means a varying property, which this closure does not support."""
    if value is None or isinstance(value, (bool, np.bool_, str, bytes, complex, np.complexfloating)):
        raise Refusal(code, name+" must be a real number")
    try:
        varies = np.ndim(value) != 0
    except (ValueError, TypeError):
        varies = True
    if varies:
        raise Refusal(UNSUPPORTED, name+" varies: one declared constant is supported, not a field")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise Refusal(code, name+" must be a real number") from None
    if not math.isfinite(value):
        raise Refusal(code, name+" must be finite")
    return value+0.0                                   # -0.0 becomes 0.0


def _vector(values, name, count=None):
    """A finite one-dimensional float vector; text, booleans, complex, ragged or nested input are refused."""
    if values is None or isinstance(values, (str, bytes, Mapping)):
        raise Refusal(INVALID, name+" must be a sequence of real numbers")
    try:
        array = np.asarray(values)
    except (ValueError, TypeError):
        raise Refusal(INVALID, name+" must be a sequence of real numbers") from None
    if array.ndim != 1 or array.dtype.kind not in "iuf":
        raise Refusal(INVALID, name+" must be a one-dimensional sequence of real numbers")
    with np.errstate(all="ignore"):
        array = array.astype(float)
    if not np.all(np.isfinite(array)):
        raise Refusal(INVALID, name+" must be finite")
    if count is not None and array.size != count:
        raise Refusal(INVALID, f"{name} needs exactly {count} values, one per cell")
    return _frozen(array+0.0)


def _text(value, name, code=PROVENANCE):
    if type(value) is not str or not value.strip():
        raise Refusal(code, "a nonempty "+name+" text is required")
    return value


# ----------------------------------------------------------------------------- declarations (explicit, with provenance)

MATERIAL_NUMBERS = ("solid_density_kg_m3", "liquid_density_kg_m3", "gravity_m_s2", "liquid_viscosity_pa_s",
                    "shear_viscosity_pa_s", "bulk_viscosity_pa_s", "bulk_viscosity_reference_porosity",
                    "bulk_viscosity_exponent", "permeability_m2", "permeability_reference_porosity",
                    "permeability_exponent")
MATERIAL_FIELDS = MATERIAL_NUMBERS+("provenance",)
PROVENANCE_KEYS = ("status", "densities", "gravity", "viscosities", "permeability")
POSITIVE = ("solid_density_kg_m3", "liquid_density_kg_m3", "gravity_m_s2", "liquid_viscosity_pa_s",
            "shear_viscosity_pa_s", "bulk_viscosity_pa_s", "permeability_m2", "permeability_exponent")
# The material values that define the operator. Densities and gravity enter only the loads (buoyancy, reaction
# volume and weight), so a changed density or gravity reuses a prepared factor exactly.
OPERATOR_MATERIAL = ("liquid_viscosity_pa_s", "shear_viscosity_pa_s", "bulk_viscosity_pa_s",
                     "bulk_viscosity_reference_porosity", "bulk_viscosity_exponent", "permeability_m2",
                     "permeability_reference_porosity", "permeability_exponent")
COLUMN_FIELDS = ("face_heights_m", "liquid_volume_fraction", "melting_rate_kg_m3_s", "provenance")
MASS_FRACTIONS = frozenset({"melt_fraction", "liquid_mass_fraction", "mass_melt_fraction", "degree_of_melting"})
BOUNDARY_FIELDS = ("bottom", "top", "provenance", "bottom_flux_m_s", "top_flux_m_s", "bottom_matrix_velocity_m_s",
                   "top_matrix_velocity_m_s")
REQUIRED_BOUNDARY = frozenset({"bottom", "top", "provenance"})


def _provenance(value):
    """Exactly PROVENANCE_KEYS mapped to nonempty text, kept as an immutable tuple of pairs in that order."""
    if isinstance(value, tuple):
        try:
            value = dict(value)
        except (TypeError, ValueError):
            value = None
    if not isinstance(value, Mapping) or set(value) != set(PROVENANCE_KEYS):
        raise Refusal(PROVENANCE, "provenance maps exactly "+", ".join(PROVENANCE_KEYS)+" to text")
    return tuple((key, _text(value[key], "provenance "+key)) for key in PROVENANCE_KEYS)


@dataclass(frozen=True)
class Material:
    """Declared closure inputs in SI units, with provenance for every group; nothing has a default.

    K(phi) = permeability_m2 (phi/permeability_reference_porosity)^permeability_exponent with exponent > 0, so that
    K(0) = 0 exactly. zeta(phi) = bulk_viscosity_pa_s (phi/bulk_viscosity_reference_porosity)^-bulk_viscosity_exponent
    for phi > 0. eta and mu are constants; rho_s and rho_f are constants of individually incompressible phases.
    """
    solid_density_kg_m3: float
    liquid_density_kg_m3: float
    gravity_m_s2: float
    liquid_viscosity_pa_s: float
    shear_viscosity_pa_s: float
    bulk_viscosity_pa_s: float
    bulk_viscosity_reference_porosity: float
    bulk_viscosity_exponent: float
    permeability_m2: float
    permeability_reference_porosity: float
    permeability_exponent: float
    provenance: tuple

    def __post_init__(self):
        values = {name: _real(getattr(self, name), name) for name in MATERIAL_NUMBERS}
        for name in POSITIVE:
            if not values[name] > 0:
                raise Refusal(INVALID, name+" must be positive")
        if not values["bulk_viscosity_exponent"] >= 0:
            raise Refusal(INVALID, "bulk_viscosity_exponent must be nonnegative")
        for name in ("bulk_viscosity_reference_porosity", "permeability_reference_porosity"):
            if not 0 < values[name] < 1:
                raise Refusal(INVALID, name+" must lie strictly between 0 and 1")
        provenance = _provenance(self.provenance)
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "provenance", provenance)


def material(declaration):
    """A validated Material from a Material or a mapping with exactly its fields."""
    if type(declaration) is Material:
        return Material(**{name: getattr(declaration, name) for name in MATERIAL_FIELDS})
    if not isinstance(declaration, Mapping) or set(declaration) != set(MATERIAL_FIELDS):
        raise Refusal(INVALID, "a material declares exactly "+", ".join(MATERIAL_FIELDS))
    return Material(**{name: declaration[name] for name in MATERIAL_FIELDS})


@dataclass(frozen=True, eq=False)
class Column:
    """One fixed column state: face heights (m, strictly increasing upward) and, per cell, the liquid VOLUME fraction
    phi in [0, 1) and the melting rate Gamma (kg of solid becoming liquid per m3 of mixture per s; < 0 freezes)."""
    face_heights_m: np.ndarray
    liquid_volume_fraction: np.ndarray
    melting_rate_kg_m3_s: np.ndarray
    provenance: str

    def __post_init__(self):
        z = _vector(self.face_heights_m, "face_heights_m")
        if not 2 <= z.size <= POLICY["maximum_cells"]+1:
            raise Refusal(INVALID, "a column has between 1 and %d cells" % POLICY["maximum_cells"])
        with np.errstate(all="ignore"):
            h = np.diff(z)
        if not np.all(np.isfinite(h) & (h > 0)):
            raise Refusal(INVALID, "face heights must increase strictly upward with representable cell heights")
        cells = z.size-1
        phi = _vector(self.liquid_volume_fraction, "liquid_volume_fraction", cells)
        if np.any(phi < 0) or np.any(phi >= 1):
            raise Refusal(INVALID, "the liquid volume fraction lies in [0, 1): pure liquid is not a compacting matrix")
        rate = _vector(self.melting_rate_kg_m3_s, "melting_rate_kg_m3_s", cells)
        object.__setattr__(self, "face_heights_m", z)
        object.__setattr__(self, "liquid_volume_fraction", phi)
        object.__setattr__(self, "melting_rate_kg_m3_s", rate)
        object.__setattr__(self, "provenance", _text(self.provenance, "column provenance"))


def column(declaration):
    """A validated Column from a Column or a mapping with exactly its fields. A mass fraction is never a porosity."""
    if type(declaration) is Column:
        return Column(**{name: getattr(declaration, name) for name in COLUMN_FIELDS})
    if isinstance(declaration, Mapping) and set(declaration) & MASS_FRACTIONS:
        raise Refusal(INVALID, "a liquid MASS fraction or degree of melting is not a volume fraction: declare "
                               "liquid_volume_fraction (porosity_from_liquid_mass_fraction converts a LOCAL retained "
                               "mass fraction, never a cumulative degree of melting)")
    if not isinstance(declaration, Mapping) or set(declaration) != set(COLUMN_FIELDS):
        raise Refusal(INVALID, "a column declares exactly "+", ".join(COLUMN_FIELDS))
    return Column(**{name: declaration[name] for name in COLUMN_FIELDS})


@dataclass(frozen=True)
class Boundary:
    """Declared boundary data. Melt condition per end (Spiegelman 1993, section 3.2): 'flux' (the Darcy flux q in
    m/s is given; zero is impermeable), 'rigid' (compaction rate dW/dz = 0, so Sigma = 0) or 'free_flux'
    (dSigma/dz = 0: no compaction resistance to the normal flux). Matrix velocity W (m/s, upward positive) at one end,
    or at both ends only when neither melt condition is rigid; the mixture volume balance must then close."""
    bottom: str
    top: str
    provenance: str
    bottom_flux_m_s: float | None = None
    top_flux_m_s: float | None = None
    bottom_matrix_velocity_m_s: float | None = None
    top_matrix_velocity_m_s: float | None = None

    def __post_init__(self):
        for end in ("bottom", "top"):
            kind = getattr(self, end)
            if type(kind) is not str or kind not in KINDS:
                raise Refusal(DECLARATION, end+" melt condition must be one of "+", ".join(KINDS))
            flux = getattr(self, end+"_flux_m_s")
            if (kind == "flux") != (flux is not None):
                raise Refusal(DECLARATION, end+": a flux value is required for, and only for, a 'flux' condition")
            if flux is not None:
                object.__setattr__(self, end+"_flux_m_s", _real(flux, end+"_flux_m_s", DECLARATION))
            velocity = getattr(self, end+"_matrix_velocity_m_s")
            if velocity is not None:
                object.__setattr__(self, end+"_matrix_velocity_m_s",
                                   _real(velocity, end+"_matrix_velocity_m_s", DECLARATION))
        lower, upper = self.bottom_matrix_velocity_m_s, self.top_matrix_velocity_m_s
        if lower is None and upper is None:
            raise Refusal(DECLARATION, "one matrix-velocity datum is required: compaction fixes W only up to a constant")
        if lower is not None and upper is not None and "rigid" in (self.bottom, self.top):
            raise Refusal(DECLARATION, "two matrix-velocity data with a rigid melt condition over-determine the column")
        object.__setattr__(self, "provenance", _text(self.provenance, "boundary provenance"))


def boundary(declaration):
    """A validated Boundary from a Boundary or a mapping with bottom, top, provenance and only optional fields."""
    if type(declaration) is Boundary:
        return Boundary(**{name: getattr(declaration, name) for name in BOUNDARY_FIELDS})
    if (not isinstance(declaration, Mapping) or not REQUIRED_BOUNDARY <= set(declaration)
            or not set(declaration) <= set(BOUNDARY_FIELDS)):
        raise Refusal(DECLARATION, "a boundary declares bottom, top and provenance, plus only "
                                   + ", ".join(BOUNDARY_FIELDS[3:]))
    return Boundary(**{name: declaration[name] for name in declaration})


# ----------------------------------------------------------------------------- the prepared operator and the solve

OPERATOR_ARRAYS = ("face_heights_m", "cell_heights_m", "liquid_volume_fraction", "wet", "wet_index", "mobility",
                   "compaction_viscosity", "dilation", "compaction_length", "conductance", "face_mobility",
                   "face_fraction", "factor")


def operator_key(mat, col, bnd):
    """Exact identity of an operator: the transport-law values, the grid and fraction bytes and the two kinds."""
    return (tuple(getattr(mat, name) for name in OPERATOR_MATERIAL), col.face_heights_m.tobytes(),
            col.liquid_volume_fraction.tobytes(), bnd.bottom, bnd.top)


@dataclass(frozen=True, eq=False)
class Operator:
    """The prepared compaction operator of one grid, liquid volume fraction, transport law and pair of melt-condition
    kinds. Loads (densities, gravity, melting rate, boundary values, matrix velocity) may change; the factor is reused
    exactly and nothing accumulates between solves.

    Per cell: mobility k = K/mu (m2 Pa-1 s-1; exactly 0 dry), compaction viscosity xi = zeta + 4 eta/3 (Pa s; inf dry:
    a pore-free cell cannot compact), dilation h/xi (0 dry) and compaction length sqrt(k xi) (m; NaN dry). Per face:
    conductance G (m Pa-1 s-1) with q = F - G (Sigma_above - Sigma_below), the mobility carrying the buoyancy part F
    and the liquid volume fraction of that buoyancy term.
    """
    key: tuple
    face_heights_m: np.ndarray
    cell_heights_m: np.ndarray
    liquid_volume_fraction: np.ndarray
    wet: np.ndarray
    wet_index: np.ndarray
    mobility: np.ndarray
    compaction_viscosity: np.ndarray
    dilation: np.ndarray
    compaction_length: np.ndarray
    conductance: np.ndarray
    face_mobility: np.ndarray
    face_fraction: np.ndarray
    bottom: str
    top: str
    factor: np.ndarray | None

    def solve(self, material_, column_, boundary_):
        """Solve THIS operator for the loads of these declarations; refuse if any operator input differs."""
        mat, col, bnd = material(material_), column(column_), boundary(boundary_)
        if operator_key(mat, col, bnd) != self.key:
            raise Refusal(MISMATCH, "grid, liquid volume fraction, viscosities, permeability or melt-condition kinds "
                                    "differ from this prepared operator")
        return _solve(self, mat, col, bnd)

    def fingerprint(self):
        """SHA-256 of the key and every prepared array: evidence that solving leaves the operator unchanged."""
        hasher = hashlib.sha256(repr((self.key[0], self.key[3], self.key[4])).encode())
        for name in OPERATOR_ARRAYS:
            value = getattr(self, name)
            hasher.update(name.encode()+(b"" if value is None else value.tobytes()))
        return hasher.hexdigest()

    @property
    def nbytes(self):
        return sum(0 if getattr(self, name) is None else getattr(self, name).nbytes for name in OPERATOR_ARRAYS)


def prepare(material_, column_, boundary_):
    """Validate the declarations, then assemble and factorise the wet-cell compaction operator.

    Refusals are atomic: invalid or unsupported inputs; a rigid or free-flux melt condition at a dry boundary cell
    (no liquid pressure exists there); a wet cell whose permeability, compaction viscosity or compaction length is
    not representable (never floored); a wet cell coarser than POLICY maximum_cell_over_compaction_length.
    """
    mat, col, bnd = material(material_), column(column_), boundary(boundary_)
    z, phi = col.face_heights_m, col.liquid_volume_fraction
    n, h = phi.size, np.diff(z)
    wet = phi > 0
    index = np.flatnonzero(wet)
    mobility, viscosity = np.zeros(n), np.full(n, np.inf)
    dilation, length = np.zeros(n), np.full(n, np.nan)
    with np.errstate(all="ignore"):
        fraction = phi[index]
        k = (mat.permeability_m2*(fraction/mat.permeability_reference_porosity)**mat.permeability_exponent
             / mat.liquid_viscosity_pa_s)
        xi = (mat.bulk_viscosity_pa_s*(fraction/mat.bulk_viscosity_reference_porosity)**-mat.bulk_viscosity_exponent
              + 4.0*mat.shear_viscosity_pa_s/3.0)
        a = h[index]/xi
        delta = np.sqrt(k*xi)
    if not all(np.all(np.isfinite(v) & (v > 0)) for v in (k, xi, a, delta)):
        raise Refusal(RANGE, "a wet cell's permeability, compaction viscosity or compaction length is not "
                             "representable; declare the cell exactly dry or rescale, never a floor")
    if np.any(h[index] > POLICY["maximum_cell_over_compaction_length"]*delta):
        raise Refusal(UNRESOLVED, "a wet cell is coarser than %g compaction lengths; refine the grid"
                                  % POLICY["maximum_cell_over_compaction_length"])
    mobility[index], viscosity[index], dilation[index], length[index] = k, xi, a, delta
    conductance, face_mobility, face_fraction = np.zeros(n+1), np.zeros(n+1), np.zeros(n+1)
    if n > 1:
        below, above = h[:-1], h[1:]
        both = wet[:-1] & wet[1:]
        with np.errstate(all="ignore"):
            k_below, k_above = np.where(both, mobility[:-1], 1.0), np.where(both, mobility[1:], 1.0)
            inner = np.where(both, 1.0/(0.5*below/k_below+0.5*above/k_above), 0.0)   # two half cells in series
            conductance[1:n] = inner
            face_mobility[1:n] = inner*(0.5*(below+above))
        face_fraction[1:n] = (phi[:-1]*below+phi[1:]*above)/(below+above)           # mean over the two half cells
        if np.any(both & ~(np.isfinite(inner) & (inner > 0))):
            raise Refusal(RANGE, "a face between wet cells has no representable conductance")
    for face, cell, kind in ((0, 0, bnd.bottom), (n, n-1, bnd.top)):
        face_fraction[face] = phi[cell]
        if not wet[cell]:
            if kind != "flux":
                raise Refusal(DRY_BOUNDARY, "a dry boundary cell has no liquid pressure: only a 'flux' condition, "
                                            "which must be zero, applies there")
            continue
        if kind != "flux":
            face_mobility[face] = mobility[cell]
        if kind == "rigid":
            with np.errstate(all="ignore"):
                conductance[face] = 2.0*mobility[cell]/h[cell]                     # half cell to Sigma = 0
    if not (np.all(np.isfinite(conductance)) and np.all(np.isfinite(face_mobility))):
        raise Refusal(RANGE, "a face conductance is not representable")
    factor = None
    if index.size:
        band = np.zeros((2, index.size))
        band[1] = dilation[index]+conductance[index]+conductance[index+1]
        band[0, 1:] = -conductance[index[:-1]+1]                                   # 0 across a dry gap
        try:
            factor = _frozen(cholesky_banded(band, lower=False))
        except (np.linalg.LinAlgError, ValueError):
            raise Refusal(RANGE, "the wet-cell compaction operator is not numerically positive definite") from None
    return Operator(key=operator_key(mat, col, bnd), face_heights_m=z, cell_heights_m=_frozen(h),
                    liquid_volume_fraction=phi, wet=_frozen(wet, bool), wet_index=_frozen(index, np.int64),
                    mobility=_frozen(mobility), compaction_viscosity=_frozen(viscosity), dilation=_frozen(dilation),
                    compaction_length=_frozen(length), conductance=_frozen(conductance),
                    face_mobility=_frozen(face_mobility), face_fraction=_frozen(face_fraction), bottom=bnd.bottom,
                    top=bnd.top, factor=factor)


def solve(material_, column_, boundary_):
    """Prepare and solve one fixed state (use prepare(...).solve(...) to reuse the operator for changed loads)."""
    return prepare(material_, column_, boundary_).solve(material_, column_, boundary_)


RESULT_ARRAYS = ("overpressure_pa", "compaction_rate_per_s", "matrix_velocity_m_s", "segregation_flux_m_s",
                 "total_pressure_pa", "fluid_pressure_pa", "reaction_volume_rate_per_s", "liquid_tendency_per_s",
                 "solid_tendency_per_s", "mixture_residual_m_s", "compaction_length_m")


@dataclass(frozen=True, eq=False)
class Result:
    """Instantaneous fields of one fixed state (SI units, z upward, pressures relative to the top face's total).

    Faces (cells + 1): W and q. Cells: Sigma, C = dW/dz, P_total, P_f, R, the matrix-frame porosity tendencies from
    the liquid and from the solid volume balance, the mixture residual (W + q)_above - (W + q)_below - R h and delta.
    Sigma, P_f and delta are NaN in dry cells, where no liquid exists; C is exactly zero there.
    """
    material: Material
    column: Column
    boundary: Boundary
    wet: np.ndarray
    overpressure_pa: np.ndarray
    compaction_rate_per_s: np.ndarray
    matrix_velocity_m_s: np.ndarray
    segregation_flux_m_s: np.ndarray
    total_pressure_pa: np.ndarray
    fluid_pressure_pa: np.ndarray
    reaction_volume_rate_per_s: np.ndarray
    liquid_tendency_per_s: np.ndarray
    solid_tendency_per_s: np.ndarray
    mixture_residual_m_s: np.ndarray
    compaction_length_m: np.ndarray
    balance_scale_m_s: float
    top_matrix_velocity_mismatch_m_s: float | None

    @property
    def mixture_flux_m_s(self):
        """W + q at faces: the mixture volume flux."""
        return self.matrix_velocity_m_s+self.segregation_flux_m_s

    @property
    def relative_liquid_mass_flux_kg_m2_s(self):
        """rho_f q at faces: liquid mass flux relative to the matrix."""
        return self.material.liquid_density_kg_m3*self.segregation_flux_m_s

    def liquid_mass_flux_at_faces(self, face_liquid_volume_fraction, face_velocity_m_s):
        """Liquid mass crossing explicitly moving faces, rho_f*(phi_face*(W-v_face)+q).

        Caller supplies the admitted phase trace (not the buoyancy interpolation) and face speed. Fixed receivers
        use zero speed; material-following faces use W and recover rho_f*q. This instantaneous flux is not a
        finite-inventory update, boundary reconstruction, or permission to debit material.
        """
        count = self.matrix_velocity_m_s.size
        phi = _vector(face_liquid_volume_fraction, "face_liquid_volume_fraction", count)
        velocity = _vector(face_velocity_m_s, "face_velocity_m_s", count)
        if np.any(phi < 0) or np.any(phi >= 1):
            raise Refusal(INVALID, "face liquid volume fractions must lie in [0, 1)")
        with np.errstate(all="ignore"):
            flux = self.material.liquid_density_kg_m3*(
                phi*(self.matrix_velocity_m_s-velocity)+self.segregation_flux_m_s)
        if not np.all(np.isfinite(flux)):
            raise Refusal(RANGE, "moving-face liquid mass flux is not representable")
        return _frozen(flux)

    def summary(self):
        """Scalar record. top_segregation_flux_m_s is the instantaneous liquid flux relative to the matrix through the
        DECLARED top condition: not column production, a steady extraction rate, a focused supply or a lid."""
        h = np.diff(self.column.face_heights_m)
        rate, q, wet = self.column.melting_rate_kg_m3_s, self.segregation_flux_m_s, self.wet
        rho_f = self.material.liquid_density_kg_m3
        length = self.compaction_length_m[wet]
        return dict(
            contract=CONTRACT, cells=int(h.size), wet_cells=int(np.count_nonzero(wet)),
            bottom_segregation_flux_m_s=float(q[0]), top_segregation_flux_m_s=float(q[-1]),
            top_relative_liquid_mass_flux_kg_m2_s=float(rho_f*q[-1]),
            bottom_matrix_velocity_m_s=float(self.matrix_velocity_m_s[0]),
            top_matrix_velocity_m_s=float(self.matrix_velocity_m_s[-1]),
            top_matrix_velocity_mismatch_m_s=self.top_matrix_velocity_mismatch_m_s,
            column_melting_rate_kg_m2_s=math.fsum((rate*h).tolist()),
            column_liquid_production_m_s=math.fsum((rate*h/rho_f).tolist()),
            column_reaction_volume_m_s=math.fsum((self.reaction_volume_rate_per_s*h).tolist()),
            max_abs_mixture_residual_m_s=float(np.max(np.abs(self.mixture_residual_m_s))),
            balance_scale_m_s=self.balance_scale_m_s,
            min_compaction_length_m=float(np.min(length)) if length.size else None,
            max_cell_over_compaction_length=float(np.max(h[wet]/length)) if length.size else None,
            assumptions=dict(ASSUMPTIONS))


def _solve(op, mat, col, bnd):
    phi, h, wet = op.liquid_volume_fraction, op.cell_heights_m, op.wet
    n = phi.size
    rho_s, rho_f, g = mat.solid_density_kg_m3, mat.liquid_density_kg_m3, mat.gravity_m_s2
    rate = col.melting_rate_kg_m3_s
    dry = ~wet
    if np.any(dry & (rate < 0)):
        raise Refusal(DRY_REACTION, "a dry cell holds no liquid to freeze")
    reaction = rate*(1.0/rho_f-1.0/rho_s)              # R = Gamma (1/rho_f - 1/rho_s), 1/s
    if np.any(dry & (reaction != 0)):
        raise Refusal(DRY_REACTION, "melting with a reaction-volume change in a dry cell must open pores, which this "
                                    "closure's pore-free cell cannot do; the onset needs a resolved transient (I05/I06)")
    source = reaction*h                                # mixture volume source of each cell, m/s
    flux = op.face_mobility*((1.0-op.face_fraction)*(rho_s-rho_f)*g)   # buoyancy part F of q, m/s
    for face, cell, kind, value in ((0, 0, bnd.bottom, bnd.bottom_flux_m_s), (n, n-1, bnd.top, bnd.top_flux_m_s)):
        if kind == "flux":
            if not wet[cell] and value != 0:
                raise Refusal(INCOMPATIBLE, "a dry boundary cell is impermeable: its declared melt flux must be zero")
            flux[face] = value
    lower, upper = bnd.bottom_matrix_velocity_m_s, bnd.top_matrix_velocity_m_s
    if lower is not None and upper is not None:
        # Boundary refuses a rigid end with two velocities, so both boundary fluxes are known here.
        terms = [upper, float(flux[n]), -lower, -float(flux[0])]+(-source).tolist()
        if abs(math.fsum(terms)) > POLICY["compatibility_relative"]*math.fsum(abs(t) for t in terms):
            raise Refusal(INCOMPATIBLE, "the declared boundary volume fluxes violate the mixture balance "
                                        "W_top + q_top - W_bottom - q_bottom = sum(Gamma (1/rho_f - 1/rho_s) h)")
    sigma = np.zeros(n)
    if op.factor is not None:
        i = op.wet_index
        sigma[i] = cho_solve_banded((op.factor, False), source[i]-flux[i+1]+flux[i])
    q = flux-op.conductance*np.diff(np.concatenate(([0.0], sigma, [0.0])))
    increment = op.dilation*sigma                      # W across each cell, Sigma h/xi; exactly 0 in dry cells
    if lower is not None:
        w = lower+np.concatenate(([0.0], np.cumsum(increment)))
    else:
        w = upper-np.concatenate((np.cumsum(increment[::-1])[::-1], [0.0]))
    compaction = np.zeros(n)
    compaction[op.wet_index] = sigma[op.wet_index]/op.compaction_viscosity[op.wet_index]
    dq = np.diff(q)
    liquid = rate/rho_f-phi*compaction-dq/h            # D phi/Dt following the matrix, liquid volume balance
    solid = (1.0-phi)*compaction+rate/rho_s            # the same from the solid volume balance
    residual = np.diff(w)+dq-source
    weight = (phi*rho_f+(1.0-phi)*rho_s)*g*h           # rho_bar g h of each cell, Pa
    total = np.concatenate((np.cumsum(weight[::-1])[::-1][1:], [0.0]))+0.5*weight
    if not all(np.all(np.isfinite(v)) for v in (q, w, sigma, compaction, liquid, solid, residual, total)):
        raise Refusal(RANGE, "a solved field is not representable")
    scale = math.fsum(float(np.max(np.abs(v))) for v in (flux, q, w, source, increment))
    return Result(material=mat, column=col, boundary=bnd, wet=op.wet,
                  overpressure_pa=_frozen(np.where(wet, sigma, np.nan)), compaction_rate_per_s=_frozen(compaction),
                  matrix_velocity_m_s=_frozen(w), segregation_flux_m_s=_frozen(q), total_pressure_pa=_frozen(total),
                  fluid_pressure_pa=_frozen(np.where(wet, total+sigma, np.nan)),
                  reaction_volume_rate_per_s=_frozen(reaction), liquid_tendency_per_s=_frozen(liquid),
                  solid_tendency_per_s=_frozen(solid), mixture_residual_m_s=_frozen(residual),
                  compaction_length_m=op.compaction_length, balance_scale_m_s=scale,
                  top_matrix_velocity_mismatch_m_s=None if lower is None or upper is None else float(w[-1]-upper))


# ----------------------------------------------------------------------------- volume fraction versus mass fraction

def _positive_fraction(liquid, solid):
    """Exact scalar ratio before one float rounding; never overflow the sum or silently erase a positive phase.

    These scalar interface conversions are outside the spatial solve. Fraction preserves finite input values
    exactly, including tiny amounts and densities; it does not add arbitrary precision to field evolution.
    """
    value = float(liquid/(liquid+solid))
    if (liquid > 0 and value == 0) or (solid > 0 and value == 1):
        raise Refusal(RANGE, "both phases exist but their fraction is not representable")
    return value

def porosity_from_liquid_mass_fraction(mass_fraction, solid_density_kg_m3, liquid_density_kg_m3):
    """Liquid VOLUME fraction phi from the LOCAL retained liquid mass fraction x of the material present in a cell.

    rho_bar x = rho_f phi and rho_bar (1 - x) = rho_s (1 - phi) (Keller & Katz 2016, section 2.2.1) give
    phi = (x/rho_f)/(x/rho_f + (1 - x)/rho_s). x is NOT a parcel's cumulative degree of melting F: once liquid has
    segregated, F records production history, not the liquid now present.
    """
    x = _real(mass_fraction, "liquid mass fraction")
    rho_s, rho_f = _real(solid_density_kg_m3, "solid density"), _real(liquid_density_kg_m3, "liquid density")
    if not (0 <= x <= 1 and rho_s > 0 and rho_f > 0):
        raise Refusal(INVALID, "a mass fraction in [0, 1] and positive phase densities are required")
    liquid, solid = Fraction(x)/Fraction(rho_f), (1-Fraction(x))/Fraction(rho_s)
    return _positive_fraction(liquid, solid)


def liquid_mass_fraction_from_porosity(liquid_volume_fraction, solid_density_kg_m3, liquid_density_kg_m3):
    """The inverse identity x = rho_f phi/(rho_f phi + rho_s (1 - phi))."""
    phi = _real(liquid_volume_fraction, "liquid volume fraction")
    rho_s, rho_f = _real(solid_density_kg_m3, "solid density"), _real(liquid_density_kg_m3, "liquid density")
    if not (0 <= phi <= 1 and rho_s > 0 and rho_f > 0):
        raise Refusal(INVALID, "a volume fraction in [0, 1] and positive phase densities are required")
    return _positive_fraction(Fraction(rho_f)*Fraction(phi), Fraction(rho_s)*(1-Fraction(phi)))


def porosity_from_phase_volumes(liquid_volume_m3, solid_volume_m3):
    """phi = V_liquid/(V_liquid + V_solid) from extensive phase volumes (for example a provider state's V accounts,
    summed over its solid phases). An empty volume has no fraction and is refused."""
    liquid, solid = _real(liquid_volume_m3, "liquid volume"), _real(solid_volume_m3, "solid volume")
    if liquid < 0 or solid < 0 or (liquid == 0 and solid == 0):
        raise Refusal(INVALID, "nonnegative phase volumes with a positive total are required")
    return _positive_fraction(Fraction(liquid), Fraction(solid))


# ----------------------------------------------------------------------------- independent references (not the producer)

def constant_coefficient(mobility, xi, buoyancy, reaction, bottom_m, top_m, bottom, top, *, w_bottom=None,
                         w_top=None):
    """Exact solution for uniform coefficients, derived independently of the finite-volume operator.

    -(k Sigma')' + Sigma/xi = R, q = -k (Sigma' - beta) and W' = Sigma/xi on [z_b, z_t]. With delta = sqrt(k xi),
    Sigma = xi R + a exp(-(z_t - z)/delta) + c exp(-(z - z_b)/delta); a and c follow from one condition per end:
    ('flux', q), ('rigid',) meaning Sigma = 0, or ('free_flux',) meaning Sigma' = 0. Each exponential is anchored at
    its own end, so nothing overflows. Returns a function of heights giving (Sigma, q, W); give one W datum.
    """
    if (w_bottom is None) == (w_top is None):
        raise ValueError("give exactly one matrix-velocity datum")
    delta = math.sqrt(mobility*xi)
    e = math.exp(-(top_m-bottom_m)/delta)
    rows = []
    for condition, first in ((bottom, True), (top, False)):
        kind = condition[0]
        if kind == "flux":
            rows.append(((-e, 1.0), (condition[1]-mobility*buoyancy)*delta/mobility) if first
                        else ((1.0, -e), (mobility*buoyancy-condition[1])*delta/mobility))
        elif kind == "rigid":
            rows.append(((e, 1.0), -xi*reaction) if first else ((1.0, e), -xi*reaction))
        elif kind == "free_flux":
            rows.append(((e, -1.0), 0.0) if first else ((1.0, -e), 0.0))
        else:
            raise ValueError("unknown melt condition "+repr(kind))
    ((p, r), b0), ((s, t), b1) = rows
    det = p*t-r*s
    a, c = (b0*t-r*b1)/det, (p*b1-s*b0)/det

    def evaluate(z):
        z = np.asarray(z, dtype=float)
        up, down = np.exp(-(top_m-z)/delta), np.exp(-(z-bottom_m)/delta)
        sigma = xi*reaction+a*up+c*down
        q = mobility*buoyancy-(mobility/delta)*(a*up-c*down)
        if w_bottom is not None:
            w = w_bottom+reaction*(z-bottom_m)+(a*delta/xi)*(up-e)+(c*delta/xi)*(1.0-down)
        else:
            w = w_top-(reaction*(top_m-z)+(a*delta/xi)*(1.0-up)+(c*delta/xi)*(down-e))
        return sigma, q, w
    return evaluate


def coefficients(mat, phi):
    """Scalar k = K/mu, xi = zeta + 4 eta/3 and beta = (1 - phi)(rho_s - rho_f) g at one liquid volume fraction."""
    k = (mat.permeability_m2*(phi/mat.permeability_reference_porosity)**mat.permeability_exponent
         / mat.liquid_viscosity_pa_s)
    xi = (mat.bulk_viscosity_pa_s*(phi/mat.bulk_viscosity_reference_porosity)**-mat.bulk_viscosity_exponent
          + 4.0*mat.shear_viscosity_pa_s/3.0)
    return k, xi, (1.0-phi)*(mat.solid_density_kg_m3-mat.liquid_density_kg_m3)*mat.gravity_m_s2


def manufactured(spec):
    """Smooth variable-coefficient reference on the synthetic column: phi = phi0 (1 + A sin(pi x/L)),
    Sigma = S cos(pi x/(2L)) with x = z - z_b (Sigma = 0 at the top, which is rigid), q = -k (Sigma' - beta) from
    analytic derivatives, R = Sigma/xi + q' and Gamma = R/(1/rho_f - 1/rho_s). Independent of the operator."""
    syn, cfg = spec["synthetic"], spec["controls"]["manufactured"]
    mat = _material(spec)
    bottom_m, length = float(syn["column_bottom_m"]), float(syn["column_top_m"])-float(syn["column_bottom_m"])
    phi0, amplitude, peak = syn["uniform_liquid_volume_fraction"], cfg["fraction_amplitude"], cfg["overpressure_pa"]
    kr = mat.permeability_m2/mat.liquid_viscosity_pa_s
    n, m = mat.permeability_exponent, mat.bulk_viscosity_exponent
    drho_g = (mat.solid_density_kg_m3-mat.liquid_density_kg_m3)*mat.gravity_m_s2
    specific = 1.0/mat.liquid_density_kg_m3-1.0/mat.solid_density_kg_m3
    wave, half = math.pi/length, math.pi/(2.0*length)

    def evaluate(z):
        x = np.asarray(z, dtype=float)-bottom_m
        phi = phi0*(1.0+amplitude*np.sin(wave*x))
        dphi = phi0*amplitude*wave*np.cos(wave*x)
        k = kr*(phi/mat.permeability_reference_porosity)**n
        dk = n*k*dphi/phi
        xi = mat.bulk_viscosity_pa_s*(phi/mat.bulk_viscosity_reference_porosity)**-m+4.0*mat.shear_viscosity_pa_s/3.0
        beta, dbeta = (1.0-phi)*drho_g, -dphi*drho_g
        sigma = peak*np.cos(half*x)
        dsigma, d2sigma = -peak*half*np.sin(half*x), -peak*half*half*np.cos(half*x)
        q = -k*(dsigma-beta)
        dq = -dk*(dsigma-beta)-k*(d2sigma-dbeta)
        return dict(phi=phi, xi=xi, sigma=sigma, q=q, gamma=(sigma/xi+dq)/specific)
    return evaluate


def _relative(numeric, exact):
    """max|numeric - exact|/max|exact|; an exactly zero reference must be reproduced exactly."""
    exact = np.asarray(exact, dtype=float)
    error = float(np.max(np.abs(np.asarray(numeric, dtype=float)-exact)))
    scale = float(np.max(np.abs(exact)))
    return error/scale if scale > 0 else (0.0 if error == 0 else math.inf)


def closed_form_errors(result, exact, first, last, datum):
    """Errors of cells [first, last) and faces first..last of a solved column against a closed form on that range."""
    faces = result.column.face_heights_m[first:last+1]
    sigma, _, _ = exact(0.5*(faces[1:]+faces[:-1]))
    _, q, w = exact(faces)
    return dict(overpressure=_relative(result.overpressure_pa[first:last], sigma),
                segregation_flux=_relative(result.segregation_flux_m_s[first:last+1], q),
                matrix_velocity=_relative(result.matrix_velocity_m_s[first:last+1]-datum, w-datum))


def allowance(faces, delta):
    """The frozen closed-form allowance: coefficient (h_max/min(delta, L))^2, the shorter length of variation."""
    faces = np.asarray(faces, dtype=float)
    shortest = min(delta, float(faces[-1]-faces[0]))
    return POLICY["constant_coefficient_error_coefficient"]*(float(np.max(np.diff(faces)))/shortest)**2


def _within(row):
    return all(value <= row["allowance"] for value in row["errors"].values())


# ----------------------------------------------------------------------------- synthetic builders (case values only)

def _material(spec, **change):
    return material(dict(spec["synthetic"]["material"], **change))


def _faces(spec, cells):
    syn = spec["synthetic"]
    return np.linspace(float(syn["column_bottom_m"]), float(syn["column_top_m"]), cells+1)


def column_declaration(spec, faces, fraction, rate):
    return {"face_heights_m": np.array(faces, dtype=float), "liquid_volume_fraction": np.array(fraction, dtype=float),
            "melting_rate_kg_m3_s": np.array(rate, dtype=float), "provenance": spec["synthetic"]["column_provenance"]}


def boundary_declaration(spec, bottom, top, *, w_bottom=None, w_top=None):
    declared = {"bottom": bottom[0], "top": top[0], "provenance": spec["synthetic"]["boundary_provenance"]}
    for end, condition in (("bottom", bottom), ("top", top)):
        if condition[0] == "flux":
            declared[end+"_flux_m_s"] = condition[1]
    if w_bottom is not None:
        declared["bottom_matrix_velocity_m_s"] = w_bottom
    if w_top is not None:
        declared["top_matrix_velocity_m_s"] = w_top
    return declared


def _column(spec, faces, fraction, rate):
    return column(column_declaration(spec, faces, fraction, rate))


def _boundary(spec, bottom, top, **velocity):
    return boundary(boundary_declaration(spec, bottom, top, **velocity))


def _condition(spec, end, kind):
    return (kind, spec["controls"]["flux_values_m_s"][end]) if kind == "flux" else (kind,)


def variable_state(spec, cells, amplitude, dry_ranges, grading=1.0, factor=1.0):
    """Synthetic phi0 (1 + A sin 2 pi x) and melting rate factor Gamma0 cos 2 pi x (melting and freezing), with
    exactly dry cell ranges, on faces z_b + L s^grading."""
    syn = spec["synthetic"]
    bottom_m, top_m = float(syn["column_bottom_m"]), float(syn["column_top_m"])
    faces = bottom_m+(top_m-bottom_m)*np.linspace(0.0, 1.0, cells+1)**grading
    x = (0.5*(faces[1:]+faces[:-1])-bottom_m)/(top_m-bottom_m)
    phi = syn["uniform_liquid_volume_fraction"]*(1.0+amplitude*np.sin(2.0*np.pi*x))
    rate = factor*syn["melting_rate_kg_m3_s"]*np.cos(2.0*np.pi*x)
    for first, last in dry_ranges:
        phi[first:last] = 0.0
        rate[first:last] = 0.0
    return faces, phi, rate


def uniform_case(spec, faces, bottom, top, *, gamma=None, change=None, w_bottom=None, w_top=None):
    """A uniform synthetic column solved and compared with the independent closed form.

    Errors are max|numeric - exact|/max|exact| for Sigma (cells), q (faces) and W minus its datum (faces). The frozen
    allowance is the error coefficient times (h/min(delta, L))^2.
    """
    syn = spec["synthetic"]
    mat = _material(spec, **(change or {}))
    phi0 = syn["uniform_liquid_volume_fraction"]
    gamma0 = syn["melting_rate_kg_m3_s"] if gamma is None else gamma
    if w_bottom is None and w_top is None:
        w_bottom = syn["matrix_velocity_m_s"]
    cells = faces.size-1
    result = solve(mat, _column(spec, faces, np.full(cells, phi0), np.full(cells, gamma0)),
                   _boundary(spec, bottom, top, w_bottom=w_bottom, w_top=w_top))
    k, xi, beta = coefficients(mat, phi0)
    reaction = gamma0*(1.0/mat.liquid_density_kg_m3-1.0/mat.solid_density_kg_m3)
    exact = constant_coefficient(k, xi, beta, reaction, float(faces[0]), float(faces[-1]), bottom, top,
                                 w_bottom=w_bottom, w_top=w_top)
    datum = w_bottom if w_bottom is not None else w_top
    return dict(result=result, exact=exact, errors=closed_form_errors(result, exact, 0, cells, datum),
                allowance=allowance(faces, math.sqrt(k*xi)), compaction_length_m=math.sqrt(k*xi))


def manufactured_errors(spec, cells):
    """Solve the manufactured state on a uniform grid (given base flux, rigid top); W reference by Gauss quadrature."""
    w0 = spec["synthetic"]["matrix_velocity_m_s"]
    evaluate = manufactured(spec)
    faces = _faces(spec, cells)
    centres = 0.5*(faces[1:]+faces[:-1])
    at_centres, at_faces = evaluate(centres), evaluate(faces)
    result = solve(_material(spec), _column(spec, faces, at_centres["phi"], at_centres["gamma"]),
                   _boundary(spec, ("flux", float(at_faces["q"][0])), ("rigid",), w_bottom=w0))
    nodes, weights = np.polynomial.legendre.leggauss(POLICY["gauss_points_per_cell"])
    half = 0.5*np.diff(faces)
    points = centres[:, None]+half[:, None]*nodes[None, :]
    local = evaluate(points.ravel())
    increments = half*((local["sigma"]/local["xi"]).reshape(points.shape)@weights)
    w_exact = w0+np.concatenate(([0.0], np.cumsum(increments)))
    return dict(cells=cells, overpressure=_relative(result.overpressure_pa, at_centres["sigma"]),
                segregation_flux=_relative(result.segregation_flux_m_s, at_faces["q"]),
                matrix_velocity=_relative(result.matrix_velocity_m_s-w0, w_exact-w0))


# ----------------------------------------------------------------------------- campaign helpers

def finish(checks, **data):
    checks = {name: bool(value) for name, value in checks.items()}
    return dict(passed=all(checks.values()), checks=checks, **data)


def check_deadline(deadline):
    if deadline is not None and time.perf_counter() > deadline:
        raise RuntimeError("cooperative time budget exhausted; nothing further run")


def refusal_code(call):
    try:
        call()
    except Refusal as exc:
        return exc.code
    return None


def fingerprint(value):
    """Digest of nested declarations (mappings, sequences, arrays, dataclasses, scalars): shows nothing changed."""
    hasher = hashlib.sha256()

    def feed(item):
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            feed({field.name: getattr(item, field.name) for field in dataclasses.fields(item)})
        elif isinstance(item, Mapping):
            hasher.update(b"{")
            for key in sorted(item, key=str):
                hasher.update(repr(key).encode())
                feed(item[key])
            hasher.update(b"}")
        elif isinstance(item, (list, tuple)):
            hasher.update(b"[")
            for entry in item:
                feed(entry)
            hasher.update(b"]")
        elif isinstance(item, np.ndarray):
            hasher.update(repr((item.dtype.str, item.shape)).encode()+np.ascontiguousarray(item).tobytes())
        else:
            hasher.update(repr(item).encode())
    feed(value)
    return hasher.hexdigest()


def attempt(expected, call, *inputs):
    """Run a call expected to refuse; report its code and whether its inputs are byte-identical afterwards."""
    before = fingerprint(inputs)
    code = refusal_code(call)
    return dict(expected=expected, code=code, refused_as_expected=code == expected,
                inputs_unchanged=before == fingerprint(inputs))


def _all_refused(cases):
    return all(case["refused_as_expected"] and case["inputs_unchanged"] for case in cases.values())


# ----------------------------------------------------------------------------- campaign controls (frozen case)

def derivation_control(spec, deadline=None):
    """Closed forms for every declared melt-condition pair (melting, unequal densities); the sealed-base compaction
    boundary layer against the rigid-matrix Darcy flux; a stiffer matrix suppressing segregation; and the top flux
    and its increment differing from column production and its increment."""
    check_deadline(deadline)
    cfg, syn = spec["controls"], spec["synthetic"]
    faces = _faces(spec, cfg["grids"][-1])
    k, xi, beta = coefficients(_material(spec), syn["uniform_liquid_volume_fraction"])
    delta, rigid_darcy = math.sqrt(k*xi), k*beta
    pairs = {}
    for bottom_kind, top_kind in cfg["boundary_pairs"]:
        check_deadline(deadline)
        row = uniform_case(spec, faces, _condition(spec, "bottom", bottom_kind), _condition(spec, "top", top_kind))
        pairs[bottom_kind+"/"+top_kind] = dict(errors=row["errors"], allowance=row["allowance"], within=_within(row),
                                               top_segregation_flux_m_s=float(row["result"].segregation_flux_m_s[-1]))
    sealed, rigid = ("flux", 0.0), ("rigid",)
    soft = uniform_case(spec, faces, sealed, rigid, gamma=0.0)
    factor = cfg["stiff_viscosity_factor"]
    stiff = uniform_case(spec, faces, sealed, rigid, gamma=0.0, change={
        "shear_viscosity_pa_s": factor*syn["material"]["shear_viscosity_pa_s"],
        "bulk_viscosity_pa_s": factor*syn["material"]["bulk_viscosity_pa_s"]})
    melting = uniform_case(spec, faces, sealed, rigid)
    doubled = uniform_case(spec, faces, sealed, rigid, gamma=2.0*syn["melting_rate_kg_m3_s"])
    check_deadline(deadline)
    soft_result = soft["result"]
    q_soft, q_stiff = soft_result.segregation_flux_m_s, stiff["result"].segregation_flux_m_s
    probe = int(np.argmin(np.abs(faces-(faces[0]+0.5*delta))))
    mixture = soft_result.mixture_flux_m_s
    cells = faces.size-1
    production = melting["result"].summary()["column_liquid_production_m_s"]
    top, top_doubled = float(melting["result"].segregation_flux_m_s[-1]), float(doubled["result"].segregation_flux_m_s[-1])
    frac = POLICY["discrimination_fraction"]
    return finish(dict(
        all_pairs_match_closed_form=all(row["within"] for row in pairs.values()),
        sealed_base_compacts=soft_result.compaction_rate_per_s[0] < 0 and soft_result.overpressure_pa[0] < 0,
        boundary_layer_departs_from_rigid_darcy=abs(float(q_soft[probe])-rigid_darcy) >= frac*rigid_darcy,
        sealed_base_matches_closed_form=_within(soft),
        mixture_flux_uniform_without_reaction=(float(np.max(np.abs(mixture-mixture[0])))
                                               <= cells*POLICY["balance_relative"]*soft_result.balance_scale_m_s),
        stiff_matches_closed_form=_within(stiff),
        stiffer_matrix_suppresses_segregation=float(np.max(np.abs(q_stiff))) <= frac*float(np.max(np.abs(q_soft))),
        melting_matches_closed_form=_within(melting) and _within(doubled),
        top_flux_is_not_production=abs(top-production) >= frac*production,
        flux_increment_is_not_production_increment=abs((top_doubled-top)-production) >= frac*production),
        cells=cells, compaction_length_m=delta, rigid_matrix_darcy_flux_m_s=rigid_darcy, pairs=pairs,
        sealed_base=dict(errors=soft["errors"], allowance=soft["allowance"], probe_height_m=float(faces[probe]),
                         probe_segregation_flux_m_s=float(q_soft[probe]),
                         base_compaction_rate_per_s=float(soft_result.compaction_rate_per_s[0])),
        stiff=dict(errors=stiff["errors"], allowance=stiff["allowance"], compaction_length_m=stiff["compaction_length_m"],
                   max_segregation_flux_m_s=float(np.max(np.abs(q_stiff)))),
        production=dict(column_liquid_production_m_s=production, top_segregation_flux_m_s=top,
                        doubled_top_segregation_flux_m_s=top_doubled, errors=melting["errors"],
                        doubled_errors=doubled["errors"]))


def refinement_control(spec, deadline=None):
    """Second-order convergence: constant coefficients against the closed form (sealed base, rigid top, melting) and
    variable coefficients against the manufactured solution (given base flux, rigid top) on the declared grids."""
    constant, made = [], []
    for cells in spec["controls"]["grids"]:
        check_deadline(deadline)
        row = uniform_case(spec, _faces(spec, cells), ("flux", 0.0), ("rigid",))
        constant.append(dict(cells=cells, allowance=row["allowance"], **row["errors"]))
        made.append(manufactured_errors(spec, cells))
    names = ("overpressure", "segregation_flux", "matrix_velocity")
    low, high = POLICY["order_window"]

    def orders(rows):
        return {name: [math.log2(a[name]/b[name]) if a[name] > 0 and b[name] > 0 else None
                       for a, b in zip(rows, rows[1:])] for name in names}

    def in_window(table):
        return all(value is not None and low <= value <= high for values in table.values() for value in values)
    constant_orders, made_orders = orders(constant), orders(made)
    return finish(dict(
        constant_second_order=in_window(constant_orders),
        manufactured_second_order=in_window(made_orders),
        constant_within_allowance=all(row[name] <= row["allowance"] for row in constant for name in names),
        manufactured_finest_within_cap=all(made[-1][name] <= POLICY["manufactured_error_cap"] for name in names)),
        constant=constant, manufactured=made, constant_orders=constant_orders, manufactured_orders=made_orders)


def reversal_control(spec, deadline=None):
    """Buoyancy reversal: swapping the phase densities negates Sigma, q and W bitwise through ONE factor (densities
    are loads). Pressure reversal: an injected downward top flux drives liquid down against buoyancy where the closed
    form says so, and up elsewhere."""
    check_deadline(deadline)
    syn, cfg = spec["synthetic"], spec["controls"]
    faces = _faces(spec, cfg["grids"][-1])
    cells = faces.size-1
    decl = syn["material"]
    light = material(decl)
    dense = material(dict(decl, solid_density_kg_m3=decl["liquid_density_kg_m3"],
                          liquid_density_kg_m3=decl["solid_density_kg_m3"]))
    phi0 = syn["uniform_liquid_volume_fraction"]
    still = _column(spec, faces, np.full(cells, phi0), np.zeros(cells))
    sealed = ("flux", 0.0)
    bnd = _boundary(spec, sealed, ("rigid",), w_bottom=0.0)
    op = prepare(light, still, bnd)
    up, down = op.solve(light, still, bnd), op.solve(dense, still, bnd)
    negated = all(np.array_equal(getattr(down, name), -getattr(up, name))
                  for name in ("overpressure_pa", "segregation_flux_m_s", "matrix_velocity_m_s"))
    k, xi, beta = coefficients(light, phi0)
    injected = cfg["injected_top_flux_over_buoyancy_flux"]*k*beta
    pushed = uniform_case(spec, faces, sealed, ("flux", injected), gamma=0.0, w_bottom=0.0)
    _, q_exact, _ = pushed["exact"](faces)
    q = pushed["result"].segregation_flux_m_s
    clear = np.abs(q_exact) > POLICY["discrimination_fraction"]*k*beta
    return finish(dict(
        light_liquid_rises=bool(np.all(up.segregation_flux_m_s[1:cells] > 0)),
        dense_liquid_sinks=bool(np.all(down.segregation_flux_m_s[1:cells] < 0)),
        exact_negation_one_factor=negated,
        pushed_matches_closed_form=_within(pushed),
        signs_follow_closed_form=bool(np.array_equal(np.sign(q[clear]), np.sign(q_exact[clear]))),
        downward_against_buoyancy=bool(np.any(clear & (q_exact < 0) & (q < 0))),
        upward_with_buoyancy=bool(np.any(clear & (q_exact > 0) & (q > 0)))),
        cells=cells, buoyancy_flux_m_s=k*beta, injected_top_flux_m_s=injected, errors=pushed["errors"],
        allowance=pushed["allowance"], faces_compared=int(np.count_nonzero(clear)),
        top_segregation_flux_light_m_s=float(up.segregation_flux_m_s[-1]),
        top_segregation_flux_dense_m_s=float(down.segregation_flux_m_s[-1]))


def balance_control(spec, deadline=None):
    """Per-cell mixture and phase volume balances, the column total, the reported fluid pressure reproducing the Darcy
    flux, zero flux on every dry-sided face and rigid translation through dry cells, on a graded grid with a dry base,
    a disconnected wet segment, melting and freezing, a free-flux top and a top matrix-velocity datum."""
    check_deadline(deadline)
    syn, cfg = spec["synthetic"], spec["controls"]["balance"]
    mat = _material(spec)
    faces, phi, rate = variable_state(spec, cfg["cells"], cfg["fraction_amplitude"], cfg["dry_ranges"],
                                      cfg["grading_exponent"])
    w_top = syn["matrix_velocity_m_s"]
    r = solve(mat, _column(spec, faces, phi, rate), _boundary(spec, ("flux", 0.0), ("free_flux",), w_top=w_top))
    h, cells = np.diff(faces), phi.size
    q, w, scale, tol = r.segregation_flux_m_s, r.matrix_velocity_m_s, r.balance_scale_m_s, POLICY["balance_relative"]
    rho_s, rho_f, g = mat.solid_density_kg_m3, mat.liquid_density_kg_m3, mat.gravity_m_s2
    phase_gap = float(np.max(np.abs(r.liquid_tendency_per_s-r.solid_tendency_per_s)*h))
    phase_scale = scale+float(np.max(np.abs(rate)*h))/min(rho_s, rho_f)
    total = math.fsum([float(w[-1]), float(q[-1]), -float(w[0]), -float(q[0])]
                      + (-r.reaction_volume_rate_per_s*h).tolist())
    wet = phi > 0
    dry = ~wet
    # Independent face mobility: the declared law at the two cell centres combined as two half cells in series.
    k_cell = np.zeros(cells)
    k_cell[wet] = (mat.permeability_m2*(phi[wet]/mat.permeability_reference_porosity)**mat.permeability_exponent
                   / mat.liquid_viscosity_pa_s)
    lower = np.flatnonzero(wet[:-1] & wet[1:])
    upper = lower+1
    k_face = (h[lower]+h[upper])/(h[lower]/k_cell[lower]+h[upper]/k_cell[upper])
    centres = 0.5*(faces[1:]+faces[:-1])
    distance = centres[upper]-centres[lower]
    pf = r.fluid_pressure_pa
    darcy = -k_face*((pf[upper]-pf[lower])/distance+rho_f*g)
    darcy_scale = k_face*(np.maximum(np.abs(pf[upper]), np.abs(pf[lower]))/distance+rho_f*g)+np.abs(q[upper])
    dry_sided = np.zeros(cells+1, dtype=bool)
    dry_sided[:-1] |= dry
    dry_sided[1:] |= dry
    first, last = cfg["dry_ranges"][0][1], cfg["dry_ranges"][1][0]
    segment = math.fsum((r.reaction_volume_rate_per_s[first:last]*h[first:last]).tolist())
    return finish(dict(
        melting_and_freezing_present=bool(np.any(wet & (rate > 0)) and np.any(wet & (rate < 0))),
        mixture_balance_per_cell=float(np.max(np.abs(r.mixture_residual_m_s))) <= tol*scale,
        phase_balances_agree=phase_gap <= tol*phase_scale,
        column_balance=abs(total) <= cells*tol*scale,
        fluid_pressure_drives_darcy_flux=bool(np.all(np.abs(q[upper]-darcy)
                                                     <= POLICY["pressure_relative"]*darcy_scale)),
        dry_sided_faces_carry_no_flux=bool(np.all(q[dry_sided] == 0)),
        matrix_translates_through_dry_cells=bool(np.all(w[1:][dry] == w[:-1][dry])),
        disconnected_segment_sealed=bool(q[first] == 0 and q[last] == 0),
        disconnected_dilation_equals_reaction=abs(float(w[last]-w[first])-segment) <= (last-first)*tol*scale,
        dry_cells_have_no_liquid_pressure=bool(np.all(np.isnan(r.overpressure_pa[dry]))
                                               and np.all(np.isnan(r.fluid_pressure_pa[dry]))
                                               and np.all(np.isfinite(r.fluid_pressure_pa[wet]))),
        top_datum_honoured=float(w[-1]) == w_top),
        cells=cells, wet_cells=int(np.count_nonzero(wet)), balance_scale_m_s=scale,
        max_mixture_residual_m_s=float(np.max(np.abs(r.mixture_residual_m_s))), max_phase_gap_m_s=phase_gap,
        column_total_m_s=total, max_darcy_difference_m_s=float(np.max(np.abs(q[upper]-darcy))),
        disconnected_cells=[first, last], summary=r.summary())


def dry_limits_control(spec, deadline=None):
    """Zero flow without buoyancy or reaction volume; an all-dry column; a dry base and a disconnected wet segment
    acting as impermeable boundaries exactly as the sealed closed forms predict; and the dry refusals."""
    check_deadline(deadline)
    syn, cfg = spec["synthetic"], spec["controls"]
    decl = syn["material"]
    faces = _faces(spec, cfg["grids"][-1])
    cells = faces.size-1
    phi0, gamma0, w0 = syn["uniform_liquid_volume_fraction"], syn["melting_rate_kg_m3_s"], syn["matrix_velocity_m_s"]
    sealed, rigid = ("flux", 0.0), ("rigid",)
    mat = material(decl)
    neutral_decl = dict(decl, liquid_density_kg_m3=decl["solid_density_kg_m3"])
    neutral = material(neutral_decl)
    uniform, melting = np.full(cells, phi0), np.full(cells, gamma0)
    still = solve(neutral, _column(spec, faces, uniform, melting), _boundary(spec, sealed, rigid, w_bottom=w0))
    parched = solve(mat, _column(spec, faces, np.zeros(cells), np.zeros(cells)),
                    _boundary(spec, sealed, sealed, w_bottom=w0))
    k, xi, beta = coefficients(mat, phi0)
    delta = math.sqrt(k*xi)
    reaction = gamma0*(1.0/mat.liquid_density_kg_m3-1.0/mat.solid_density_kg_m3)
    base = cfg["dry_base_cells"]
    phi, rate = uniform.copy(), melting.copy()
    phi[:base], rate[:base] = 0.0, 0.0
    based = solve(mat, _column(spec, faces, phi, rate), _boundary(spec, sealed, rigid, w_bottom=w0))
    base_exact = constant_coefficient(k, xi, beta, reaction, float(faces[base]), float(faces[-1]), sealed, rigid,
                                      w_bottom=w0)
    base_errors = closed_form_errors(based, base_exact, base, cells, w0)
    (d0, d1), (d2, d3) = cfg["disconnected_ranges"]
    split_phi, split_rate = uniform.copy(), melting.copy()
    for first, last in ((d0, d1), (d2, d3)):
        split_phi[first:last], split_rate[first:last] = 0.0, 0.0
    split = solve(mat, _column(spec, faces, split_phi, split_rate), _boundary(spec, sealed, rigid, w_bottom=w0))
    w_upper = w0+reaction*float(faces[d2]-faces[d1])      # a sealed segment dilates by exactly its reaction volume
    segment_exact = constant_coefficient(k, xi, beta, reaction, float(faces[d1]), float(faces[d2]), sealed, sealed,
                                         w_bottom=w0)
    upper_exact = constant_coefficient(k, xi, beta, reaction, float(faces[d3]), float(faces[-1]), sealed, rigid,
                                       w_bottom=w_upper)
    segment_errors = closed_form_errors(split, segment_exact, d1, d2, w0)
    upper_errors = closed_form_errors(split, upper_exact, d3, cells, w_upper)
    check_deadline(deadline)
    # Refusals and the admitted equal-density onset.
    dry_base = uniform.copy()
    dry_base[:base] = 0.0
    dry_top = uniform.copy()
    dry_top[-base:] = 0.0
    freezing = np.where(dry_base > 0, gamma0, -gamma0)
    onset_column = column_declaration(spec, faces, dry_base, melting)
    sealed_rigid = boundary_declaration(spec, sealed, rigid, w_bottom=w0)
    variants = {
        "melting_with_volume_change_in_dry_cell": (DRY_REACTION, decl, onset_column, sealed_rigid),
        "freezing_in_dry_cell": (DRY_REACTION, decl, column_declaration(spec, faces, dry_base, freezing),
                                 sealed_rigid),
        "rigid_condition_at_dry_top": (DRY_BOUNDARY, decl, column_declaration(spec, faces, dry_top, np.zeros(cells)),
                                       boundary_declaration(spec, sealed, rigid, w_bottom=w0)),
        "free_flux_at_dry_base": (DRY_BOUNDARY, decl, column_declaration(spec, faces, dry_base, np.zeros(cells)),
                                  boundary_declaration(spec, ("free_flux",), rigid, w_bottom=w0)),
        "flux_into_dry_base": (INCOMPATIBLE, decl, column_declaration(spec, faces, dry_base, np.zeros(cells)),
                               boundary_declaration(spec, ("flux", cfg["flux_values_m_s"]["top"]), rigid,
                                                    w_bottom=w0)),
    }
    cases = {name: attempt(code, (lambda m=m, c=c, b=b: solve(m, c, b)), m, c, b)
             for name, (code, m, c, b) in variants.items()}
    onset = solve(neutral_decl, onset_column, sealed_rigid)
    onset_dry = ~onset.wet
    return finish(dict(
        neutral_no_overpressure=bool(np.all(still.overpressure_pa == 0)),
        neutral_no_segregation=bool(np.all(still.segregation_flux_m_s == 0)),
        neutral_matrix_uniform=bool(np.all(still.matrix_velocity_m_s == w0)),
        neutral_liquid_stored_in_place=bool(np.array_equal(still.liquid_tendency_per_s,
                                                           melting/neutral.liquid_density_kg_m3)),
        all_dry_no_flux=bool(np.all(parched.segregation_flux_m_s == 0)),
        all_dry_rigid_translation=bool(np.all(parched.matrix_velocity_m_s == w0)),
        all_dry_liquid_pressure_undefined=bool(np.all(np.isnan(parched.fluid_pressure_pa))
                                               and np.all(np.isnan(parched.overpressure_pa))),
        all_dry_total_pressure_defined=bool(np.all(np.isfinite(parched.total_pressure_pa))
                                            and np.all(np.diff(parched.total_pressure_pa) < 0)),
        dry_base_zero_flux=bool(np.all(based.segregation_flux_m_s[:base+1] == 0)),
        dry_base_rigid_translation=bool(np.all(based.matrix_velocity_m_s[:base+1] == w0)),
        dry_base_is_sealed_closed_form=all(v <= allowance(faces[base:], delta) for v in base_errors.values()),
        disconnected_faces_zero=bool(split.segregation_flux_m_s[d1] == 0 and split.segregation_flux_m_s[d2] == 0
                                     and split.segregation_flux_m_s[d3] == 0),
        disconnected_segment_is_sealed_closed_form=all(v <= allowance(faces[d1:d2+1], delta)
                                                       for v in segment_errors.values()),
        upper_region_is_sealed_closed_form=all(v <= allowance(faces[d3:], delta) for v in upper_errors.values()),
        equal_density_onset_admitted=bool(np.array_equal(onset.liquid_tendency_per_s[onset_dry],
                                                         melting[onset_dry]/neutral.liquid_density_kg_m3)
                                          and np.all(onset.segregation_flux_m_s == 0)),
        dry_refusals=_all_refused(cases)),
        cells=cells, dry_base_cells=base, dry_base_errors=base_errors, segment_errors=segment_errors,
        upper_errors=upper_errors, disconnected_ranges=[[d0, d1], [d2, d3]], refusals=cases)


def boundaries_control(spec, deadline=None):
    """Mixture volume compatibility when both matrix velocities are declared (closed boxes with and without reaction
    volume, open columns) and malformed boundary declarations, each refused with its code and inputs unchanged."""
    check_deadline(deadline)
    syn, cfg = spec["synthetic"], spec["controls"]
    decl = syn["material"]
    faces = _faces(spec, cfg["grids"][-1])
    cells = faces.size-1
    phi0, gamma0, w0 = syn["uniform_liquid_volume_fraction"], syn["melting_rate_kg_m3_s"], syn["matrix_velocity_m_s"]
    mat = material(decl)
    reaction = gamma0*(1.0/mat.liquid_density_kg_m3-1.0/mat.solid_density_kg_m3)
    sealed, tol = ("flux", 0.0), POLICY["balance_relative"]
    melting_column = column_declaration(spec, faces, np.full(cells, phi0), np.full(cells, gamma0))
    still_column = column_declaration(spec, faces, np.full(cells, phi0), np.zeros(cells))
    closed = boundary_declaration(spec, sealed, sealed, w_bottom=0.0, w_top=0.0)
    box = solve(decl, still_column, closed)
    neutral_box = solve(dict(decl, liquid_density_kg_m3=decl["solid_density_kg_m3"]), melting_column, closed)
    opened = solve(decl, melting_column, boundary_declaration(
        spec, sealed, sealed, w_bottom=w0, w_top=w0+reaction*float(faces[-1]-faces[0])))
    base = boundary_declaration(spec, sealed, ("rigid",), w_bottom=w0)
    variants = {
        "closed_rigid_box_with_melting": (INCOMPATIBLE, closed, melting_column),
        "open_top_velocity_ignoring_reaction": (INCOMPATIBLE, boundary_declaration(
            spec, sealed, sealed, w_bottom=w0, w_top=w0), melting_column),
        "no_matrix_velocity": (DECLARATION, {key: v for key, v in base.items() if key != "bottom_matrix_velocity_m_s"},
                               still_column),
        "two_velocities_with_rigid_end": (DECLARATION, dict(base, top_matrix_velocity_m_s=w0), still_column),
        "flux_without_value": (DECLARATION, {key: v for key, v in base.items() if key != "bottom_flux_m_s"},
                               still_column),
        "value_with_rigid": (DECLARATION, dict(base, top_flux_m_s=0.0), still_column),
        "unknown_kind": (DECLARATION, dict(base, top="open"), still_column),
        "nonfinite_flux": (DECLARATION, dict(base, bottom_flux_m_s=float("nan")), still_column),
        "varying_flux": (UNSUPPORTED, dict(base, bottom_flux_m_s=[0.0, 1e-10]), still_column),
        "unknown_field": (DECLARATION, dict(base, top_overpressure_pa=0.0), still_column),
        "blank_provenance": (PROVENANCE, dict(base, provenance=" "), still_column),
    }
    cases = {name: attempt(code, (lambda b=b, c=c: solve(decl, c, b)), decl, c, b)
             for name, (code, b, c) in variants.items()}
    return finish(dict(
        closed_box_without_reaction_admitted=(box.top_matrix_velocity_mismatch_m_s is not None and
                                              abs(box.top_matrix_velocity_mismatch_m_s)
                                              <= cells*tol*box.balance_scale_m_s),
        closed_box_mixture_flux_vanishes=(float(np.max(np.abs(box.mixture_flux_m_s)))
                                          <= cells*tol*box.balance_scale_m_s),
        closed_box_still_segregates=bool(np.max(box.segregation_flux_m_s) > 0 and np.min(box.matrix_velocity_m_s) < 0),
        equal_density_closed_box_admitted=bool(np.all(neutral_box.segregation_flux_m_s == 0)
                                               and np.all(neutral_box.overpressure_pa == 0)),
        open_compatible_admitted=abs(opened.top_matrix_velocity_mismatch_m_s) <= cells*tol*opened.balance_scale_m_s,
        refusals=_all_refused(cases)),
        cells=cells, closed_box_top_mismatch_m_s=box.top_matrix_velocity_mismatch_m_s,
        open_top_mismatch_m_s=opened.top_matrix_velocity_mismatch_m_s,
        closed_box_max_segregation_flux_m_s=float(np.max(box.segregation_flux_m_s)), refusals=cases)


def porosity_basis_control(spec, deadline=None):
    """Liquid volume fraction against liquid mass fraction: an exact rational reference, the round trip, the
    equal-density identity, extensive phase volumes, and refusal of a mass fraction offered as a column state."""
    check_deadline(deadline)
    syn, cfg = spec["synthetic"], spec["controls"]["porosity_basis"]
    decl = syn["material"]
    rho_s, rho_f = decl["solid_density_kg_m3"], decl["liquid_density_kg_m3"]
    x = cfg["liquid_mass_fraction"]
    liquid = Fraction(x)/Fraction(rho_f)
    exact = float(liquid/(liquid+(1-Fraction(x))/Fraction(rho_s)))
    phi = porosity_from_liquid_mass_fraction(x, rho_s, rho_f)
    back = liquid_mass_fraction_from_porosity(phi, rho_s, rho_f)
    same = porosity_from_liquid_mass_fraction(x, rho_s, rho_s)
    volumes = porosity_from_phase_volumes(cfg["liquid_volume_m3"], cfg["solid_volume_m3"])
    volume_exact = float(Fraction(cfg["liquid_volume_m3"])/(Fraction(cfg["liquid_volume_m3"])
                                                           + Fraction(cfg["solid_volume_m3"])))
    eps = 8*2.0**-52
    faces = _faces(spec, 4)
    offered = {"face_heights_m": faces, "liquid_mass_fraction": [x]*4, "melting_rate_kg_m3_s": [0.0]*4,
               "provenance": syn["column_provenance"]}
    bnd = boundary_declaration(spec, ("flux", 0.0), ("rigid",), w_bottom=0.0)
    cases = {
        "mass_fraction_as_column_state": attempt(INVALID, lambda: solve(decl, offered, bnd), decl, offered, bnd),
        "mass_fraction_above_one": attempt(INVALID, lambda: porosity_from_liquid_mass_fraction(1.5, rho_s, rho_f)),
        "empty_phase_volumes": attempt(INVALID, lambda: porosity_from_phase_volumes(0.0, 0.0)),
        "negative_phase_volume": attempt(INVALID, lambda: porosity_from_phase_volumes(-1.0, 2.0)),
    }
    return finish(dict(
        volume_fraction_matches_exact=abs(phi-exact) <= eps*exact,
        round_trip=abs(back-x) <= eps*x,
        lighter_liquid_occupies_more_volume=(phi > x) == (rho_f < rho_s),
        equal_densities_identity=abs(same-x) <= eps*x,
        phase_volumes=abs(volumes-volume_exact) <= eps*volume_exact,
        refusals=_all_refused(cases)),
        liquid_mass_fraction=x, liquid_volume_fraction=phi, exact_liquid_volume_fraction=exact,
        round_trip_mass_fraction=back, phase_volume_fraction=volumes, refusals=cases)


def reuse_control(spec, deadline=None):
    """One prepared operator reused for changed loads (melting rate, liquid density, gravity, matrix velocity):
    bitwise equal to a fresh preparation for each load; the operator unchanged by solving and of fixed size; any
    change of an operator input (fraction, grid, transport law, melt-condition kind) refused."""
    check_deadline(deadline)
    syn, cfg = spec["synthetic"], spec["controls"]["reuse"]
    decl = syn["material"]
    faces, phi, rate = variable_state(spec, cfg["cells"], cfg["fraction_amplitude"], [[0, cfg["dry_base_cells"]]])
    sealed, rigid = ("flux", 0.0), ("rigid",)

    def load(entry):
        return (material(dict(decl, liquid_density_kg_m3=entry["liquid_density_kg_m3"],
                              gravity_m_s2=entry["gravity_m_s2"])),
                _column(spec, faces, phi, entry["melting_rate_factor"]*rate),
                _boundary(spec, sealed, rigid, w_bottom=entry["matrix_velocity_m_s"]))
    loads = [load(entry) for entry in cfg["loads"]]
    op = prepare(*loads[0])
    before, size = op.fingerprint(), op.nbytes
    identical, tops = [], []
    for mat, col, bnd in loads:
        check_deadline(deadline)
        reused, fresh = op.solve(mat, col, bnd), prepare(mat, col, bnd).solve(mat, col, bnd)
        identical.append(all(np.array_equal(getattr(reused, name), getattr(fresh, name), equal_nan=True)
                             for name in RESULT_ARRAYS))
        tops.append(float(reused.segregation_flux_m_s[-1]))
    mat0, col0, bnd0 = loads[0]
    nudged = phi.copy()
    cell = int(np.flatnonzero(phi > 0)[0])
    nudged[cell] = np.nextafter(nudged[cell], 1.0)
    moved = faces.copy()
    moved[1] = np.nextafter(moved[1], moved[2])
    variants = {
        "fraction_one_ulp": (mat0, _column(spec, faces, nudged, rate), bnd0),
        "face_one_ulp": (mat0, _column(spec, moved, phi, rate), bnd0),
        "permeability_one_ulp": (material(dict(decl, permeability_m2=math.nextafter(decl["permeability_m2"],
                                                                                    math.inf))), col0, bnd0),
        "shear_viscosity": (material(dict(decl, shear_viscosity_pa_s=2*decl["shear_viscosity_pa_s"])), col0, bnd0),
        "bulk_exponent": (material(dict(decl, bulk_viscosity_exponent=0.0)), col0, bnd0),
        "liquid_viscosity": (material(dict(decl, liquid_viscosity_pa_s=2*decl["liquid_viscosity_pa_s"])), col0,
                             bnd0),
        "top_kind": (mat0, col0, _boundary(spec, sealed, ("free_flux",), w_bottom=syn["matrix_velocity_m_s"])),
    }
    cases = {name: attempt(MISMATCH, (lambda v=v: op.solve(*v)), *v) for name, v in variants.items()}
    read_only = all(not getattr(op, name).flags.writeable for name in OPERATOR_ARRAYS if getattr(op, name) is not None)
    return finish(dict(
        reuse_bitwise_identical=all(identical),
        loads_change_results=len(set(tops)) > 1,
        operator_unchanged_by_solving=op.fingerprint() == before and op.nbytes == size,
        operator_arrays_read_only=read_only,
        operator_mismatch_refused=_all_refused(cases)),
        cells=cfg["cells"], loads=len(loads), operator_bytes=size, top_segregation_fluxes_m_s=tops, refusals=cases)


# ----------------------------------------------------------------------------- timing (raw, no claim)

TIMING_SCOPE = ("raw interleaved wall-clock samples of identical validated solves: a fresh preparation for every load "
                "against one preparation reused for all loads; results compared bitwise; no saving or cost is claimed")


def timing_rows(spec, deadline=None):
    cfg, syn = spec["controls"]["timing"], spec["synthetic"]
    mat = _material(spec)
    rows = []
    for cells in cfg["cells"]:
        check_deadline(deadline)
        faces = _faces(spec, cells)
        phi = np.full(cells, syn["uniform_liquid_volume_fraction"])
        bnd = _boundary(spec, ("flux", 0.0), ("rigid",), w_bottom=syn["matrix_velocity_m_s"])
        loads = [_column(spec, faces, phi, np.full(cells, factor*syn["melting_rate_kg_m3_s"]))
                 for factor in np.linspace(-1.0, 2.0, cfg["loads"]).tolist()]
        samples = {"fresh_seconds": [], "reuse_seconds": []}
        identical = True
        for _ in range(POLICY["timing_repetitions"]):
            check_deadline(deadline)
            begin = time.perf_counter()
            fresh = [prepare(mat, col, bnd).solve(mat, col, bnd) for col in loads]
            samples["fresh_seconds"].append(time.perf_counter()-begin)
            begin = time.perf_counter()
            op = prepare(mat, loads[0], bnd)
            reused = [op.solve(mat, col, bnd) for col in loads]
            samples["reuse_seconds"].append(time.perf_counter()-begin)
            identical = identical and all(np.array_equal(a.segregation_flux_m_s, b.segregation_flux_m_s)
                                          and np.array_equal(a.matrix_velocity_m_s, b.matrix_velocity_m_s)
                                          for a, b in zip(fresh, reused))
        rows.append(dict(cells=cells, loads=len(loads), samples_seconds=samples, bitwise_identical=identical,
                         median_seconds={key: float(np.median(value)) for key, value in samples.items()}))
    return rows


def timing_control(spec, deadline=None):
    """Raw matched timings (see TIMING_SCOPE); only finiteness and bitwise agreement are checked."""
    rows = timing_rows(spec, deadline)
    finite = all(math.isfinite(s) and s >= 0 for row in rows for values in row["samples_seconds"].values()
                 for s in values)
    return finish(dict(finite_nonnegative=finite, bitwise_identical=all(row["bitwise_identical"] for row in rows)),
                  grids=rows, scope=TIMING_SCOPE)


CONTROLS = (("derivation", derivation_control), ("refinement", refinement_control), ("reversal", reversal_control),
            ("balances", balance_control), ("dry_limits", dry_limits_control), ("boundaries", boundaries_control),
            ("porosity_basis", porosity_basis_control), ("reuse", reuse_control), ("timing", timing_control))


# ----------------------------------------------------------------------------- case, bindings and receipt

def load_case(path=None):
    spec = json.loads((ROOT/CASE if path is None else Path(path)).read_text(encoding="utf-8"))
    if (type(spec) is not dict or set(spec) != CASE_FIELDS or spec["schema"] != CASE_SCHEMA
            or spec["contract"] != CONTRACT or spec["policy"] != POLICY):
        raise ValueError("case fields/schema/contract/policy differ from the executable")
    return spec


def digest(name):
    return hashlib.sha256((ROOT/name).read_bytes()).hexdigest()


def bindings():
    return {name: digest(name) for name in NEW_FILES}


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


def runtime():
    return dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                system=platform.system(), machine=platform.machine())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="new receipt path; an existing file is never overwritten")
    mode.add_argument("--timing", action="store_true", help="print raw matched timings only; writes nothing")
    args = parser.parse_args()
    if args.timing:
        start = time.perf_counter()
        rows = timing_rows(load_case(), start+POLICY["maximum_seconds"])
        print(json.dumps(jsonable(dict(scope=TIMING_SCOPE, runtime=runtime(), grids=rows)), indent=2, allow_nan=False))
        return 0
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        result = dict(schema=EVIDENCE_SCHEMA, status="INCOMPLETE", scientific_acceptance=False, mc03_closed=False,
                      contract=CONTRACT, runtime=runtime(), controls={})
        start = time.perf_counter()
        try:
            before = bindings()
            result["source_sha256"] = before
            spec = load_case()
            deadline = start+POLICY["maximum_seconds"]           # cooperative budget, checked inside every control
            for name, control in CONTROLS:
                begin = time.perf_counter()
                try:
                    data = control(spec, deadline)
                    check_deadline(deadline)                    # an overrunning control is not recorded as a pass
                    result["controls"][name] = dict(status="PASS" if data["passed"] else "FAIL",
                                                    seconds=time.perf_counter()-begin, **data)
                except (ValueError, RuntimeError, ArithmeticError, KeyError, TypeError, IndexError) as exc:
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
            result = dict(schema=EVIDENCE_SCHEMA, status="FAIL", scientific_acceptance=False, mc03_closed=False,
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
