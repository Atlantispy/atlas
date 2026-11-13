"""D1 plate torque balance on the I03 spherical network, driven by GPE from P1 columns (I04.2, Part A).

The selected law is atlas.plate-torque-resistance.v1 (docs/I01_PHYSICAL_CONTRACT.md section 3): for each plate i,
M_i omega_i + interface reactions = b_i, with M_i = int D (|r|^2 I - r r^T) dA. This module evaluates it on the
faces and boundary edges of one issued I03 network, with no quadrature:

- Basal moments are closed form. For a region of the unit sphere bounded by great-circle arcs a -> b shorter
  than pi, with the region on the left, int n n^T dA = (2 A I - sum (c s^T + s c^T))/6, where s = a + b and
  c = ((b - a) x a)/(1 + a.b) (= tan(theta/2) times the outward conormal, evaluated without cancellation). It
  follows from Laplacian_s(n_i n_j) = 2 delta_ij - 6 n_i n_j and the divergence theorem; A is I03's own measured
  face area, so trace(int n n^T) = A. Each ring's orientation is checked (outer counter-clockwise, holes
  clockwise), because neither the trace nor the diagonal detects a reversed ring.
- GPE drives a rigid plate only through its boundary: e_k x r is divergence-free on the sphere, so
  int_P r x grad_s U dA = oint U (r x nu) ds, and on a great-circle edge int (r x nu_left) ds = R^2 (b - a). The
  traction -(L0/L) grad_s U therefore gives -(L0/L) R^2 sum_e U_e (b - a) on the edge's left plate and the
  opposite on its right. U_e is the column anomaly at the edge midpoint (P1). At a plate boundary the trace is
  single-valued, the mean of the two sides' columns, so internal GPE torques cancel; the torque that would move
  between the plates if that partition changed is reported per boundary, with the motion it would cause.
- Slab pull f = C g S n (N/m) on a trench's subducting plate gives C g S R^2 (b - a) per edge, toward the trench.
- The optional linear interface k_ij (a verification option) and a rigid mantle rotation omega_m are closed form.
- The optional explicitly declared radial-pressure route consumes actual shell-side moments
  K=R^-2 integral(p r^2 dr), not planar GPE. Its named central-half interface closure has torque
  -R^2 Kcentral(b-a) on the left, with the opposite right reaction and factor one. This is a reduced
  discretised pressure closure, not recovered full interfacial stress. One common exact K reference is
  removed before binary64 projection; its torque telescopes to zero around every closed plate.

Every force term is either supplied or explicitly declared omitted; a missing one refuses. Net rotation is a
diagnostic and never subtracted. The column and solve kernels reproduce the retained I01 tools
(tools/check_i01_gpe.py columns/Datum, tools/check_i01_closures.py solve_torque) without importing them; tests
check the equivalence. This is a reduced balance with authored, labelled forcing, not a generated world.

SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import math
from numbers import Real
from types import MappingProxyType

import numpy as np

from . import integration_ports as P
from . import integration_sphere as S
from . import integration_state as _state
from ._validation import TectonicsError
from .integration_junction_paths import exponential
from .materials import _json, _name


SCHEMA = 'atlas.i04-driving-balance.v1'
METHOD = 'atlas.plate-torque-resistance.v1'
ROUTE = 'd1_reduced_known_forcing_v1'
PREPARED = 'atlas.i04-driving-operator.v1'
# Retained I01 policy values, unchanged: tools/check_i01_gpe.py POLICY and tools/check_i01_closures.py.
POLICY = dict(max_columns=32768, max_layers=32, max_density_anomaly=.1, algebra_relative=1e-11)
SYMMETRY_RELATIVE = 1e-13      # check_i01_closures.solve_torque, literal
MAX_CONDITION = 1e12           # check_i01_closures.solve_torque, literal
TRACE_PARTITION = .5           # declared single-valued plate-boundary trace: the mean of the two sides
CENTRAL_RADIAL_PRESSURE = 'central-half-radial-pressure-trace-v1'
MAX_PLATES = 4096
TERMS = ('gpe', 'slab_pull', 'mantle_traction', 'authored_torque', 'interface')

NULLSPACE = 'unresolved frame or nullspace'
DOUBLE_OWNERSHIP = 'double ownership'
MISSING_FORCE = 'missing force'
UNSUPPORTED = 'unsupported'
INVALID = 'invalid input'
RESIDUAL = 'torque residual'
STALE = 'stale identity'
NONCONVERGED = 'nonconverged balance'
CODES = (NULLSPACE, DOUBLE_OWNERSHIP, MISSING_FORCE, UNSUPPORTED, INVALID, RESIDUAL, STALE, NONCONVERGED,
         'non-monotone belt response', 'unresolved inner solve')
EVALUATION = 'explicit, single evaluation at the start of the interval; no temporal-accuracy or convergence claim'
# I04.4 coupled route (d1d2_endpoint_fixed_point_v1): properties and the balance at the interval's endpoint.
EVALUATION_ENDPOINT = ('implicit endpoint evaluation (backward Euler, first order in time); the interval is a fixed '
                       'point to its declared residual; I09 owns the final coupled convergence')
EVALUATIONS = {'start': EVALUATION, 'end': EVALUATION_ENDPOINT}
NEWTON_RELATIVE = 1e-10        # _integration_motion.FORCE_TOL: the same drive/drag/column balance in scalar form
NEWTON_ITERATIONS = 96         # _integration_motion.MAX_ITERATIONS
NEWTON_HALVINGS = 64           # residual-decrease backtracking per step (ruling C1(3))
PARTITION = 4e-11              # _integration_weakening.respond's creep/plastic work partition, 2 TOL
NON_MONOTONE = 'non-monotone belt response'
UNRESOLVED_INNER = 'unresolved inner solve'
PARTITION_LOCAL = ('local linearisation at the solved motion, with material state held fixed; scaled to a half-unit '
                   'trace-partition perturbation, not a finite-shift solution')
PARTITION_AT_REST = 'unavailable: a belt at rest has no supported finite tangent for the partition sensitivity'


class DrivingRefused(TectonicsError):
    """A D1 balance that cannot be formed or solved as declared; ``code`` is one of CODES. Nothing was issued."""

    def __init__(self, message, code, detail=None):
        if code not in CODES:
            raise ValueError('unknown driving refusal code')
        super().__init__(message)
        self.code, self.detail = code, detail


# ---------------------------------------------------------------------------------------------------------------
# Retained I01 column kernel (tools/check_i01_gpe.py), reproduced: same equations, arithmetic order and refusals.

def number(value, name, *, positive=False):
    if isinstance(value, (bool, str, bytes)) or np.ndim(value) != 0:
        raise DrivingRefused(name+" must be a real scalar", INVALID)
    try:
        value = float(value)
    except (TypeError, OverflowError) as exc:
        raise DrivingRefused(name+" must be a real scalar", INVALID) from exc
    if not math.isfinite(value) or (positive and value <= 0):
        raise DrivingRefused(name+" outside finite support", INVALID)
    return value


def real_array(value):
    a = np.asarray(value)
    if a.dtype.kind not in "fiu" or not np.all(np.isfinite(a)):
        raise DrivingRefused("finite real arrays required", INVALID)
    return np.asarray(a, dtype=float)


@dataclass(frozen=True)
class Datum:
    """Common basal pressure, vertical origin, gravity and reference mantle (the D5 datum; IN-07)."""
    pressure_pa: float
    compensation_elevation_m: float
    mantle_density_kg_m3: float = 3300.
    gravity_m_s2: float = 9.81
    reference_temperature_k: float = 293.15

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, number(getattr(self, name), name,
                positive=name != "compensation_elevation_m"))

    def record(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _moments(h, rb, rt):
    """Exact moments for linear density, layer order bottom to top."""
    load = h*(rb+rt)/2
    local_moment = h*h*(rb+2*rt)/6
    base = np.cumsum(h, axis=1)-h
    return load.sum(axis=1), (base*load+local_moment).sum(axis=1)


def columns(datum, thickness_m, reference_density_kg_m3, alpha_per_k,
            bottom_temperature_k, top_temperature_k):
    """Static dry support and GPE from the SAME prescribed material columns (I01_GPE.md, unchanged equations).

    h is (columns,layers); other inputs must broadcast to that exact shape. Temperature is linear within each
    layer. The anomaly g(q - m^2/(2 rm)) is evaluated without subtracting two large absolute energies. One
    deviation from the tool: a floating-point overflow is refused as DrivingRefused, not FloatingPointError.
    """
    if not isinstance(datum, Datum):
        raise DrivingRefused("one shared Datum required", INVALID)
    h = real_array(thickness_m)
    if (h.ndim != 2 or not 1 <= h.shape[0] <= POLICY["max_columns"] or
            not 1 <= h.shape[1] <= POLICY["max_layers"] or np.any(h <= 0)):
        raise DrivingRefused("positive bounded column/layer thicknesses required", INVALID)
    try:
        rho, alpha, tb, tt = [np.broadcast_to(real_array(v), h.shape) for v in
            (reference_density_kg_m3, alpha_per_k, bottom_temperature_k, top_temperature_k)]
    except ValueError as exc:
        if isinstance(exc, DrivingRefused):
            raise
        raise DrivingRefused("column inputs must broadcast to the thickness shape", INVALID) from exc
    if np.any(rho <= 0) or np.any(alpha < 0) or np.any(tb <= 0) or np.any(tt <= 0):
        raise DrivingRefused("positive densities/Kelvin and nonnegative expansivity required", INVALID)
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            db = alpha*(tb-datum.reference_temperature_k)
            dt = alpha*(tt-datum.reference_temperature_k)
            if max(float(np.max(np.abs(db))), float(np.max(np.abs(dt)))) > POLICY["max_density_anomaly"]:
                raise DrivingRefused("thermal density anomaly exceeds Boussinesq control support", INVALID)
            load, moment = _moments(h, rho*(1-db), rho*(1-dt))
            rm, g = datum.mantle_density_kg_m3, datum.gravity_m_s2
            fill = (datum.pressure_pa/g-load)/rm
            if np.any(fill < 0):
                raise DrivingRefused("column extends below supported compensation pressure", INVALID)
            anomaly = g*(moment-load*load/(2*rm))
            result = dict(surface_elevation_m=datum.compensation_elevation_m+fill+h.sum(axis=1),
                mantle_fill_m=fill, gpe_anomaly_j_m2=anomaly,
                effective_rock_load_kg_m2=load,
                reference_rock_mass_kg_m2=(rho*h).sum(axis=1),
                pressure_residual_pa=g*(rm*fill+load)-datum.pressure_pa)
    except FloatingPointError as exc:
        raise DrivingRefused("column result not representable", INVALID) from exc
    if not all(np.all(np.isfinite(v)) for v in result.values()):
        raise DrivingRefused("column result not representable", INVALID)
    return result


# ---------------------------------------------------------------------------------------------------------------
# Retained I01 torque solve (tools/check_i01_closures.py solve_torque), reproduced; the residual is returned.

def datum_id(datum):
    """The shared datum's identity, for port headers."""
    if not isinstance(datum, Datum):
        from .integration_radial_pressure import RadialDatum
        if type(datum) is not RadialDatum:
            raise DrivingRefused('one shared planar or explicit radial Datum required', INVALID)
        return datum.datum_id
    return hashlib.sha256(_json(datum.record())).hexdigest()


def _relative(actual, expected):
    actual, expected = np.asarray(actual), np.asarray(expected)
    return float(np.linalg.norm(actual - expected) /
                 max(float(np.linalg.norm(expected)), np.finfo(float).tiny))


def _finite(value, name):
    result = np.asarray(value, dtype=float)
    if not np.isfinite(result).all():
        raise DrivingRefused(f"{name} must be finite", INVALID)
    return result


def solve_torque(matrix, torque):
    """omega and its relative residual: symmetric, positive definite, conditioned at most 1e12, residual 1e-11."""
    matrix, torque = _finite(matrix, "matrix"), _finite(torque, "torque")
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or torque.shape != (len(matrix),):
        raise DrivingRefused("square torque system required", INVALID)
    if np.linalg.norm(matrix-matrix.T) > SYMMETRY_RELATIVE*np.linalg.norm(matrix):
        raise DrivingRefused("symmetric dissipative resistance required", NULLSPACE)
    eigenvalues = np.linalg.eigvalsh(matrix)
    if eigenvalues[0] <= 0 or eigenvalues[-1] / eigenvalues[0] > MAX_CONDITION:
        raise DrivingRefused("unresolved frame/nullspace or ill-conditioned resistance", NULLSPACE)
    omega = np.linalg.solve(matrix, torque)
    residual = _relative(matrix @ omega, torque) if np.any(torque) else float(np.linalg.norm(omega))
    if not residual <= POLICY["algebra_relative"]:
        raise DrivingRefused("torque residual", RESIDUAL)
    return omega, residual


# ---------------------------------------------------------------------------------------------------------------
# Closed-form spherical geometry.

def _edges(rings):
    for ring in rings:
        ring = np.asarray(ring, dtype=float)
        yield ring, np.roll(ring, -1, axis=0)


def edge_sum(rings):
    """sum over every ring's arcs of c s^T + s c^T, with c = ((b - a) x a)/(1 + a.b) and s = a + b.

    Every arc must be shorter than pi. Orientation is checked per ring with the signed first moment
    (1/2) sum theta_e p_e . c_anchor, p_e = (a x b)/|a x b|: positive for the outer ring, negative for each hole.
    """
    rings = [np.asarray(ring, dtype=float) for ring in rings]
    anchor = S._mean_direction(rings[0])
    total = np.zeros((3, 3))
    for index, (a, b) in enumerate(_edges(rings)):
        d = b-a
        x = np.cross(d, a)
        q = 1+np.einsum('ij,ij->i', a, b)
        if not np.all(q > 0):
            raise DrivingRefused('every arc must be shorter than pi', INVALID)
        theta = np.arctan2(np.linalg.norm(x, axis=1), np.einsum('ij,ij->i', a, b))
        # x = (b - a) x a = -(a x b), so the signed first moment is -(1/2) sum theta x/|x| . anchor.
        lengths = np.linalg.norm(x, axis=1)
        if np.any(lengths == 0):
            raise DrivingRefused('a ring repeats a vertex', INVALID)
        turn = -math.fsum(float(v) for v in theta*(x @ anchor)/lengths)/2
        if (turn > 0) != (index == 0):
            raise DrivingRefused('ring orientation: the outer ring must be counter-clockwise and holes clockwise',
                                 INVALID)
        c = x/q[:, None]
        s = a+b
        edge = np.einsum('ij,ik->jk', c, s)
        total += edge+edge.T
    return total


def polygon_moment(rings, area_sr):
    """int n n^T dA (sr) over one region of the unit sphere: outer ring counter-clockwise, holes clockwise.

    ``area_sr`` is the region's measured area (I03 ``_measure``), so that trace(result) equals it identically.
    """
    return (2*area_sr*np.eye(3)-edge_sum(rings))/6


def arc_moment(a, b):
    """int n n^T ds along the minor great-circle arc a -> b of the unit sphere, and its angle."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    theta = math.atan2(float(np.linalg.norm(np.cross(a, b))), float(a @ b))
    if not 0 < theta < math.pi:
        raise DrivingRefused("an interface edge needs a proper minor arc", INVALID)
    t = np.cross(np.cross(a, b), a)
    t /= np.linalg.norm(t)
    m = (np.outer(a, a)*(theta/2+math.sin(2*theta)/4) + np.outer(t, t)*(theta/2-math.sin(2*theta)/4)
         + (np.outer(a, t)+np.outer(t, a))*math.sin(theta)**2/2)
    return m, theta


def face_moments(network):
    """Per face: (measured area sr, int n n^T dA in the sphere's axes), consistent with ``face_area_m2``.

    Rings are taken in the face's plate-local coordinates (as I03 measures them) and rotated by the plate frame.
    """
    if type(network) is not S.SphereNetwork:
        raise DrivingRefused("an issued SphereNetwork is required", INVALID)
    frames = {plate: rotation.matrix for plate, rotation in network.frames.items()}
    areas, moments = [], []
    for index, face in enumerate(network.faces):
        rings = network.face_coordinates(index)
        area = S._measure(rings)
        local = polygon_moment(rings, area)
        f = np.asarray(frames[face.plate_id])
        areas.append(area)
        moments.append(f @ local @ f.T)
    return np.array(areas), np.array(moments)


# ---------------------------------------------------------------------------------------------------------------
# Declared inputs.

def _vector(value, name):
    v = np.asarray(value)
    if v.shape != (3,) or v.dtype.kind not in 'fiu' or not np.all(np.isfinite(v)):
        raise DrivingRefused(name+": three finite components required", INVALID)
    return tuple(float(x) for x in v)


def _positive(value, name):
    try:
        number_ = None if isinstance(value, bool) or not isinstance(value, Real) else float(value)
    except (TypeError, OverflowError):
        number_ = None
    if number_ is None or not math.isfinite(number_) or number_ <= 0:
        raise DrivingRefused(name+" must be positive and finite", INVALID)
    return number_


@dataclass(frozen=True, slots=True)
class Slab:
    """A declared attached slab on one trench: section mass anomaly S = int (rho_slab - rho_m) dA (kg/m) and the
    transmission factor C (IN-02/IN-03). Pull f = C g S along the subducting plate's outward conormal."""
    section_mass_anomaly_kg_m: float
    transmission: float
    source: str

    def __post_init__(self):
        _positive(self.section_mass_anomaly_kg_m, 'slab section mass anomaly')
        if (isinstance(self.transmission, bool) or not isinstance(self.transmission, Real)
                or not math.isfinite(float(self.transmission)) or self.transmission < 0):
            raise DrivingRefused('slab transmission must be finite and nonnegative', INVALID)
        object.__setattr__(self, 'section_mass_anomaly_kg_m', float(self.section_mass_anomaly_kg_m))
        object.__setattr__(self, 'transmission', float(self.transmission))
        _name(self.source, 'slab source')


@dataclass(frozen=True, slots=True)
class Forcing:
    """Every D1 input with its provenance. Each term in TERMS is either supplied or named in ``omitted``.

    basal_drag_pa_s_m: plate -> D = eta_a/H_a > 0 (Pa s/m), required for every plate (it anchors the frame).
    gamma: the common L0/L for GPE; mantle_omega_rad_s: a rigid mantle rotation (the only mantle forcing admitted
    in Part A); slabs: trench boundary -> Slab, with slab_omitted naming trenches whose slab pull is the declared
    reduced omission; authored_torque_n_m: plate -> labelled known external torque; interface_k_pa_s: boundary ->
    linear k (verification option); regional_reactions: boundary -> (torque on left, torque on right), owned by a
    regional replacement; belts: the boundaries whose resistance is the I04.3 reduced D2 belt (its content is the
    strength declaration, passed to balance() as the belt term). A boundary has at most one of k, a regional reaction
    and a belt. frame_id, when given, must be the
    network's frame: every vector here is in the network's axes, and the mantle frame is those axes
    (``mantle_label`` is only a kinematic description). Boundaries without k or a regional reaction, trenches with
    a declared omission and plates without an authored torque are recorded per item in the Balance.
    basal_drag_radius_m optionally declares the actual concentric drag surface; None preserves the original
    reference-R convention and old records. radial_pressure_rule explicitly owns the additional radial pressure
    term and requires its matching typed port/rule at balance(), no gamma or implicit GPE substitution.
    """
    basal_drag_pa_s_m: tuple
    provenance: str
    gamma: object = None
    mantle_omega_rad_s: object = None
    slabs: tuple = ()
    slab_omitted: tuple = ()
    authored_torque_n_m: tuple = ()
    interface_k_pa_s: tuple = ()
    regional_reactions: tuple = ()
    omitted: tuple = ()
    frame_id: object = None
    belts: tuple = ()
    mantle_label: str = 'declared mantle reference: the network axes'
    basal_drag_radius_m: object = None
    radial_pressure_rule: object = None

    def __post_init__(self):
        _name(self.provenance, 'forcing provenance')
        _name(self.mantle_label, 'mantle label')
        if self.frame_id is not None:
            _name(self.frame_id, 'frame')
        if type(self.omitted) is not tuple or len(set(self.omitted)) != len(self.omitted) or not set(
                self.omitted) <= set(TERMS):
            raise DrivingRefused('omitted must name distinct terms of %s' % (TERMS,), INVALID)
        drag = _pairs(self.basal_drag_pa_s_m, 'basal drag')
        object.__setattr__(self, 'basal_drag_pa_s_m', tuple((k, _positive(v, 'basal drag D')) for k, v in drag))
        if self.gamma is not None:
            object.__setattr__(self, 'gamma', _positive(self.gamma, 'L0/L'))
        if self.basal_drag_radius_m is not None:
            object.__setattr__(self, 'basal_drag_radius_m', _positive(self.basal_drag_radius_m, 'basal drag radius'))
        if self.radial_pressure_rule is not None:
            if type(self.radial_pressure_rule) is not str or self.radial_pressure_rule != CENTRAL_RADIAL_PRESSURE:
                raise DrivingRefused('unsupported explicit radial interface pressure rule', UNSUPPORTED)
            if self.gamma is not None:
                raise DrivingRefused('radial pressure and planar GPE cannot own the same driving term', DOUBLE_OWNERSHIP)
            if self.basal_drag_radius_m is None:
                raise DrivingRefused('radial pressure requires an explicit physical basal drag radius', MISSING_FORCE)
        if self.mantle_omega_rad_s is not None:
            object.__setattr__(self, 'mantle_omega_rad_s', _vector(self.mantle_omega_rad_s, 'mantle omega'))
        slabs = _pairs(self.slabs, 'slabs')
        if any(type(v) is not Slab for _, v in slabs):
            raise DrivingRefused('slabs must be Slab records', INVALID)
        object.__setattr__(self, 'slabs', slabs)
        omitted = tuple(sorted(self.slab_omitted))
        if len(set(omitted)) != len(omitted):
            raise DrivingRefused('slab omissions must be distinct', INVALID)
        object.__setattr__(self, 'slab_omitted', omitted)
        object.__setattr__(self, 'authored_torque_n_m', tuple(
            (k, _vector(v, 'authored torque')) for k, v in _pairs(self.authored_torque_n_m, 'authored torque')))
        object.__setattr__(self, 'interface_k_pa_s', tuple(
            (k, _positive(v, 'interface k')) for k, v in _pairs(self.interface_k_pa_s, 'interface k')))
        reactions = []
        for k, v in _pairs(self.regional_reactions, 'regional reactions'):
            if type(v) is not tuple or len(v) != 2:
                raise DrivingRefused('a regional reaction is (torque on left, torque on right)', INVALID)
            reactions.append((k, (_vector(v[0], 'regional reaction'), _vector(v[1], 'regional reaction'))))
        object.__setattr__(self, 'regional_reactions', tuple(reactions))
        both = set(dict(self.interface_k_pa_s)) & set(dict(self.regional_reactions))
        if both:
            raise DrivingRefused('boundary %r has both a reduced resistance and a regional replacement'
                                 % sorted(both)[0], DOUBLE_OWNERSHIP)
        if (type(self.belts) is not tuple or any(type(name) is not str or not name for name in self.belts)
                or len(set(self.belts)) != len(self.belts)):
            raise DrivingRefused('belts must name distinct boundaries', INVALID)
        object.__setattr__(self, 'belts', tuple(sorted(self.belts)))
        owned = set(self.belts) & (set(dict(self.interface_k_pa_s)) | set(dict(self.regional_reactions)))
        if owned:
            raise DrivingRefused('boundary %r has a D2 belt and another reduced resistance or regional replacement'
                                 % sorted(owned)[0], DOUBLE_OWNERSHIP)
        supplied = dict(gpe=self.gamma is not None, slab_pull=bool(self.slabs or self.slab_omitted),
                        mantle_traction=self.mantle_omega_rad_s is not None,
                        authored_torque=bool(self.authored_torque_n_m),
                        interface=bool(self.interface_k_pa_s or self.regional_reactions or self.belts))
        for term in TERMS:
            if supplied[term] and term in self.omitted:
                raise DrivingRefused(term+' is both supplied and declared omitted', INVALID)
            if not supplied[term] and term not in self.omitted:
                raise DrivingRefused(term+' is neither supplied nor declared omitted: a missing force is not zero',
                                     MISSING_FORCE)

    def record(self):
        record = dict(basal_drag_pa_s_m=[list(p) for p in self.basal_drag_pa_s_m], provenance=self.provenance,
                      gamma=self.gamma, mantle_omega_rad_s=self.mantle_omega_rad_s,
                      slabs=[[k, v.section_mass_anomaly_kg_m, v.transmission, v.source] for k, v in self.slabs],
                      slab_omitted=list(self.slab_omitted),
                      authored_torque_n_m=[[k, list(v)] for k, v in self.authored_torque_n_m],
                      interface_k_pa_s=[list(p) for p in self.interface_k_pa_s],
                      regional_reactions=[[k, [list(v[0]), list(v[1])]] for k, v in self.regional_reactions],
                      omitted=sorted(self.omitted), frame_id=self.frame_id, mantle_label=self.mantle_label)
        if self.belts:                       # Part A forcings (no belt) keep their record and identity
            record['belts'] = list(self.belts)
        if self.basal_drag_radius_m is not None:
            record['basal_drag_radius_m'] = self.basal_drag_radius_m
        if self.radial_pressure_rule is not None:
            record['radial_pressure_rule'] = self.radial_pressure_rule
        return record

    @property
    def forcing_id(self):
        return hashlib.sha256(_json(self.record())).hexdigest()

    @classmethod
    def from_record(cls, record):
        """The forcing a stored record names (for replay); the caller checks that its identity reproduces."""
        return cls(tuple((k, v) for k, v in record['basal_drag_pa_s_m']), record['provenance'],
                   gamma=record['gamma'], mantle_omega_rad_s=record['mantle_omega_rad_s'],
                   slabs=tuple((k, Slab(s, c, src)) for k, s, c, src in record['slabs']),
                   slab_omitted=tuple(record['slab_omitted']),
                   authored_torque_n_m=tuple((k, tuple(v)) for k, v in record['authored_torque_n_m']),
                   interface_k_pa_s=tuple((k, v) for k, v in record['interface_k_pa_s']),
                   regional_reactions=tuple((k, (tuple(v[0]), tuple(v[1]))) for k, v in record['regional_reactions']),
                   omitted=tuple(record['omitted']), frame_id=record['frame_id'], mantle_label=record['mantle_label'],
                   belts=tuple(record.get('belts', ())),
                   basal_drag_radius_m=record.get('basal_drag_radius_m'),
                   radial_pressure_rule=record.get('radial_pressure_rule'))


def _pairs(value, label):
    items = sorted(value.items()) if isinstance(value, dict) else list(value)
    if any(type(p) is not tuple or len(p) != 2 or type(p[0]) is not str for p in items):
        raise DrivingRefused(label+': (name, value) pairs required', INVALID)
    names = [p[0] for p in items]
    if len(set(names)) != len(names):
        raise DrivingRefused(label+': each name at most once', INVALID)
    return tuple(sorted(items))


# ---------------------------------------------------------------------------------------------------------------
# Prepared operator: geometry and drag only, reused under its complete determining identity.

@dataclass(frozen=True, init=False, eq=False, slots=True)
class Prepared(_state._Immutable):
    """The assembled resistance for one network and one drag/interface declaration (3P unknowns)."""
    network_id: str
    plate_ids: tuple
    prepared_id: str
    radius_m: float
    basal_drag_radius_m: float
    matrix: np.ndarray = field(repr=False)
    basal: np.ndarray = field(repr=False)
    geometry: np.ndarray = field(repr=False)
    face_plate: np.ndarray = field(repr=False)
    face_drag: np.ndarray = field(repr=False)
    face_tensor: np.ndarray = field(repr=False)
    interfaces: tuple = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('Prepared operators are issued by prepare()')


def _frozen(array, dtype=float):
    raw = np.ascontiguousarray(array, dtype=dtype)
    return np.frombuffer(raw.tobytes(), dtype=dtype).reshape(raw.shape)


def prepare(network, forcing):
    """Assemble M (+ B) for the network's plates. Any change of geometry, drag or interface k gives a new ID."""
    if type(network) is not S.SphereNetwork:
        raise DrivingRefused('an issued SphereNetwork is required', INVALID)
    if type(forcing) is not Forcing:
        raise DrivingRefused('a Forcing record is required', INVALID)
    if len(network.plate_ids) > MAX_PLATES:
        raise DrivingRefused('too many plates for one dense D1 solve', UNSUPPORTED)
    plates = network.plate_ids
    drag = dict(forcing.basal_drag_pa_s_m)
    if set(drag) != set(plates):
        raise DrivingRefused('basal drag is required for exactly the network plates', MISSING_FORCE)
    radius = float(network.sphere.radius_m)
    areas, moments = face_moments(network)
    order = {plate: i for i, plate in enumerate(plates)}
    face_plate = np.array([order[face.plate_id] for face in network.faces], dtype=np.int64)
    # Per face: K_f = A_f I - S_f (unit sphere); D_f R^4 K_f is that face's basal resistance (N m s).
    tensor = areas[:, None, None]*np.eye(3)-moments
    face_drag = np.array([drag[face.plate_id] for face in network.faces])
    drag_radius = radius if forcing.basal_drag_radius_m is None else forcing.basal_drag_radius_m
    if drag_radius > radius:
        raise DrivingRefused('basal drag radius cannot lie outside the declared reference sphere', INVALID)
    scale = drag_radius**4
    n = len(plates)
    basal = np.zeros((n, 3, 3))
    geometry = np.zeros((n, 3, 3))
    for i in range(n):
        mask = face_plate == i
        geometry[i] = scale*tensor[mask].sum(axis=0)
        basal[i] = scale*np.einsum('f,fij->ij', face_drag[mask], tensor[mask])
    matrix = np.zeros((3*n, 3*n))
    for i in range(n):
        matrix[3*i:3*i+3, 3*i:3*i+3] = basal[i]
    interfaces = []
    k_of = dict(forcing.interface_k_pa_s)
    known = {boundary.boundary_id: boundary for boundary in network.boundaries}
    unknown = set(k_of) - set(known)
    if unknown:
        raise DrivingRefused('interface k on unknown boundary %r' % sorted(unknown)[0], INVALID)
    index = {vertex: i for i, vertex in enumerate(network.vertex_ids)}
    directions = np.asarray(network.vertex_direction, dtype=float)
    for name in sorted(k_of):
        boundary = known[name]
        chain = list(boundary.vertex_ids)
        pairs = list(zip(chain, chain[1:]))+([(chain[-1], chain[0])] if boundary.closed else [])
        block = np.zeros((3, 3))
        for first, second in pairs:
            m, theta = arc_moment(directions[index[first]], directions[index[second]])
            block += theta*np.eye(3)-m
        block *= k_of[name]*radius**3
        i, j = order[boundary.left_plate_id], order[boundary.right_plate_id]
        matrix[3*i:3*i+3, 3*i:3*i+3] += block
        matrix[3*j:3*j+3, 3*j:3*j+3] += block
        matrix[3*i:3*i+3, 3*j:3*j+3] -= block
        matrix[3*j:3*j+3, 3*i:3*i+3] -= block
        interfaces.append((name, i, j, _frozen(block)))
    record = dict(schema=PREPARED, network_id=network.network_id, plates=list(plates),
                  basal_drag_pa_s_m=[list(p) for p in forcing.basal_drag_pa_s_m],
                  interface_k_pa_s=[list(p) for p in forcing.interface_k_pa_s])
    if forcing.basal_drag_radius_m is not None:
        record['basal_drag_radius_m'] = forcing.basal_drag_radius_m
    return _state._issue(Prepared, network_id=network.network_id, plate_ids=plates, radius_m=radius,
                         basal_drag_radius_m=drag_radius,
                         prepared_id=hashlib.sha256(_json(record)).hexdigest(), matrix=_frozen(matrix),
                         basal=_frozen(basal), geometry=_frozen(geometry), face_plate=_frozen(face_plate, np.int64),
                         face_drag=_frozen(face_drag), face_tensor=_frozen(tensor), interfaces=tuple(interfaces))


def _expected_prepared_id(network, forcing):
    record = dict(schema=PREPARED, network_id=network.network_id, plates=list(network.plate_ids),
                  basal_drag_pa_s_m=[list(p) for p in forcing.basal_drag_pa_s_m],
                  interface_k_pa_s=[list(p) for p in forcing.interface_k_pa_s])
    if forcing.basal_drag_radius_m is not None:
        record['basal_drag_radius_m'] = forcing.basal_drag_radius_m
    return hashlib.sha256(_json(record)).hexdigest()


# ---------------------------------------------------------------------------------------------------------------
# GPE traces from P1 columns.

def trace_anomaly(datum, port, *, water_regime=None, water_density_kg_m3=None):
    """The GPE anomaly (J/m2) at every P1 point, from the reproduced I01 column kernel.

    Water depths are accepted only in the declared zero-rigidity (Airy) regime, as a top water layer (rho_w,
    alpha 0, T_ref): I01_WATER_GPE's structural limit. Finite rigidity is refused: with no declared elastic core
    by MC-07, and with one because no spherical flexure producer exists yet (I08).
    """
    if not isinstance(datum, Datum):
        raise DrivingRefused('one shared Datum required', INVALID)
    if type(port) is not P.Columns:
        raise DrivingRefused('P1 columns are required', INVALID)
    if water_regime not in (None, 'airy', 'finite'):
        raise DrivingRefused('water regime is None (dry), airy or finite', INVALID)
    if water_regime == 'finite':
        raise P.PortRefused('finite-rigidity water loading needs a declared elastic core and a spherical flexure '
                            'producer, neither available in Part A', P.UNSUPPORTED,
                            detail='REFUSED_CORE_PLACEMENT_ABSENT')
    water = port.water_depth_m
    if water is not None and water_regime != 'airy':
        raise P.PortRefused('water depths given without the declared Airy regime', P.UNSUPPORTED,
                            detail='water regime not declared')
    if water_regime == 'airy':
        if water is None:
            raise P.PortRefused('the Airy regime needs declared water depths', P.MISSING_VALUE)
        if water_density_kg_m3 is None:
            raise DrivingRefused('the Airy regime needs the declared water density (IN-07)', MISSING_FORCE)
        rho_w = number(water_density_kg_m3, 'water density', positive=True)
    if np.any(port.unknown):
        raise P.PortRefused('a trace column is unknown: no GPE torque can be formed', P.UNRESOLVED_COLUMN)
    points = port.points
    result = np.empty(points)
    groups = {}
    for i in range(points):
        h, rho, alpha, tb, tt = port.layers(i)
        if water_regime == 'airy':
            effective = np.minimum(rho*(1-alpha*(tb-datum.reference_temperature_k)),
                                   rho*(1-alpha*(tt-datum.reference_temperature_k)))
            if not float(np.min(effective)) > rho_w:
                raise P.PortRefused('a trace column has rock lighter than water', P.UNSUPPORTED,
                                    detail='REFUSED_WATER_IN_ROCK_COLUMN')
            if water[i] > 0:
                t = datum.reference_temperature_k
                h, rho, alpha, tb, tt = (np.r_[h, water[i]], np.r_[rho, rho_w], np.r_[alpha, 0.],
                                         np.r_[tb, t], np.r_[tt, t])
        groups.setdefault(len(h), []).append((i, h, rho, alpha, tb, tt))
    for count, rows in sorted(groups.items()):
        for start in range(0, len(rows), POLICY['max_columns']):
            chunk = rows[start:start+POLICY['max_columns']]
            stacked = [np.array([row[k] for row in chunk]) for k in range(1, 6)]
            try:
                out = columns(datum, *stacked)['gpe_anomaly_j_m2']
            except DrivingRefused as exc:
                raise P.PortRefused('a trace column is outside the I01 column kernel support', P.UNSUPPORTED,
                                    detail=str(exc)) from exc
            result[[row[0] for row in chunk]] = out
    return result


# ---------------------------------------------------------------------------------------------------------------
# The balance.

@dataclass(frozen=True, init=False, eq=False, slots=True)
class Balance(_state._Immutable):
    """One solved D1 balance: angular velocities with every term, residual and power account kept separate.

    Its mappings are read-only, so record() always matches balance_id.
    """
    network_id: str
    network_time_s: float
    parent_state_id: object
    interval: object
    prepared_id: str
    forcing_id: str
    columns_id: object
    datum: object
    water_regime: object
    water_density_kg_m3: object
    plate_ids: tuple
    frame_id: str
    mantle_label: str
    omitted_slabs: tuple
    omitted_interfaces: tuple
    unauthored_plates: tuple
    omega_rad_s: np.ndarray = field(repr=False)
    terms: dict = field(repr=False)
    jump_sensitivity: tuple = field(repr=False)
    partition_motion: tuple = field(repr=False)
    net_rotation_rad_s: np.ndarray = field(repr=False)
    residual: float
    power: dict
    omitted: tuple
    trace_partition: float
    evaluation: str
    balance_id: str
    endpoint_state_id: object = None
    belt: object = None
    cell_mean_points: tuple = ()
    partition_motion_evaluation: object = None
    radial_pressure: object = None

    def __init__(self, *args, **kwargs):
        raise TypeError('a Balance is issued by balance()')

    def omega(self, plate_id):
        return self.omega_rad_s[self.plate_ids.index(plate_id)].copy()

    def record(self):
        return dict(schema=SCHEMA, method=METHOD, route=ROUTE, network_id=self.network_id,
                    parent_state_id=self.parent_state_id,
                    interval=None if self.interval is None else list(self.interval),
                    prepared_id=self.prepared_id, forcing_id=self.forcing_id, columns_id=self.columns_id,
                    datum=None if self.datum is None else dict(self.datum), water_regime=self.water_regime,
                    water_density_kg_m3=self.water_density_kg_m3, plate_ids=list(self.plate_ids),
                    frame_id=self.frame_id, mantle_label=self.mantle_label, network_time_s=self.network_time_s,
                    omitted_slabs=list(self.omitted_slabs), omitted_interfaces=list(self.omitted_interfaces),
                    unauthored_plates=list(self.unauthored_plates),
                    omega_rad_s=self.omega_rad_s.tolist(), residual=self.residual, power=dict(self.power),
                    omitted=list(self.omitted), trace_partition=self.trace_partition, evaluation=self.evaluation,
                    partition_motion=[[name, peak] for name, _, peak in self.partition_motion],
                    net_rotation_rad_s=self.net_rotation_rad_s.tolist(),
                    terms={k: v.tolist() for k, v in sorted(self.terms.items())},
                    jump_sensitivity=[[name, list(v)] for name, v in self.jump_sensitivity],
                    **self._extra())

    def _extra(self):
        """Fields of the coupled route, absent from Part A records."""
        extra = {}
        if self.endpoint_state_id is not None:
            extra['endpoint_state_id'] = self.endpoint_state_id
        if self.belt is not None:
            extra['belt'] = dict(self.belt)
        if self.cell_mean_points:
            extra['cell_mean_points'] = list(self.cell_mean_points)
        if self.partition_motion_evaluation is not None:
            extra['partition_motion_evaluation'] = self.partition_motion_evaluation
        if self.radial_pressure is not None:
            extra['radial_pressure'] = dict(self.radial_pressure,
                common_reference_n_m=list(self.radial_pressure['common_reference_n_m']))
        return extra


def _support_matches(support, network):
    if type(support) is not P.TraceSupport:
        raise P.PortRefused('a P1 trace support is required', P.INCOMPATIBLE_SUPPORT, detail='support')
    if support.network_id != network.network_id:
        raise P.PortRefused('the trace support belongs to another network', P.STALE_IDENTITY, detail='network_id')


def _interval(value, network):
    if (type(value) is not tuple or len(value) != 4 or any(type(v) is not int for v in value[:2])
            or any(isinstance(v, bool) or not isinstance(v, Real) for v in value[2:])):
        raise P.PortRefused('an interval is (start_step, end_step, start_s, end_s)', P.MISSING_VALUE,
                            detail='interval')
    start, end, start_s, end_s = value[0], value[1], float(value[2]), float(value[3])
    if not (start == network.step and start <= end <= _state.MAX_STEPS and start_s == network.time_s <= end_s):
        raise P.PortRefused('Part A evaluates at the start of the interval, at the network step and time',
                            P.UNSUPPORTED, detail=EVALUATION)
    return (start, end, start_s, end_s)


def _endpoint_interval(value, network):
    """The coupled route's interval: the network is the candidate endpoint, at the interval's end step and time."""
    if (type(value) is not tuple or len(value) != 4 or any(type(v) is not int for v in value[:2])
            or any(isinstance(v, bool) or not isinstance(v, Real) for v in value[2:])):
        raise P.PortRefused('an interval is (start_step, end_step, start_s, end_s)', P.MISSING_VALUE,
                            detail='interval')
    start, end, start_s, end_s = value[0], value[1], float(value[2]), float(value[3])
    if not (0 <= start < end == network.step <= _state.MAX_STEPS and start_s < end_s == network.time_s):
        raise P.PortRefused('the coupled route evaluates at the end of the interval, at the network step and time',
                            P.UNSUPPORTED, detail=EVALUATION_ENDPOINT)
    return (start, end, start_s, end_s)


def balance(network, forcing, *, support=None, columns_port=None, datum=None, water_regime=None,
            water_density_kg_m3=None, prepared=None, parent_state_id=None, interval=None, belt_term=None,
            evaluation='start', endpoint_state_id=None, omega_start=None, radial_pressure_port=None,
            interface_pressure_rule=None):
    """Solve M omega = b for one network and one declared Forcing; returns an issued Balance.

    GPE needs the network's TraceSupport, P1 columns on it and the shared Datum. ``prepared`` is reused only when
    its identity matches this network and drag/interface declaration exactly; otherwise it is refused. The parent
    state and interval come from the P1 header when GPE is used, and may be given explicitly (they must then agree);
    P5 can be issued only for a Balance that has both.

    I04.4 (``evaluation='end'``): the network and P1 belong to the interval's candidate endpoint. Headers name the
    interval's parent state S0 (``parent_state_id``, required) and bind the endpoint through its network_id and
    moving identity; ``endpoint_state_id`` (required) is recorded. A forcing with D2 belts needs ``belt_term``
    (integration_strength.BeltTerm on this network): M omega = b + tau_belt(omega) is solved by exact-tangent Newton
    (_belt_newton) from ``omega_start`` (a committed or iterate value; None starts from the belt-free balance).
    """
    if type(network) is not S.SphereNetwork:
        raise DrivingRefused('an issued SphereNetwork is required', INVALID)
    if type(forcing) is not Forcing:
        raise DrivingRefused('a Forcing record is required', INVALID)
    radial = forcing.radial_pressure_rule is not None
    if radial:
        if radial_pressure_port is None:
            raise DrivingRefused('declared radial pressure requires its actual source trace', MISSING_FORCE)
        if interface_pressure_rule != forcing.radial_pressure_rule:
            raise DrivingRefused('the radial interface closure must match the explicit forcing declaration', STALE)
        if columns_port is not None or forcing.gamma is not None or water_regime is not None or water_density_kg_m3 is not None:
            raise DrivingRefused('radial pressure cannot be combined with planar columns/GPE or planar water loading', DOUBLE_OWNERSHIP)
        if forcing.slabs or forcing.belts or belt_term is not None:
            raise DrivingRefused('radial slab placement and reduced belt column laws require their own physical contracts', UNSUPPORTED)
    elif radial_pressure_port is not None or interface_pressure_rule is not None:
        raise DrivingRefused('radial pressure was not declared by this forcing', MISSING_FORCE)
    if evaluation not in EVALUATIONS:
        raise DrivingRefused('evaluation is start (Part A) or end (the coupled route)', INVALID)
    if evaluation == 'end' and (parent_state_id is None or interval is None or endpoint_state_id is None):
        raise P.PortRefused('the coupled route names the interval, its parent state and the endpoint state',
                            P.MISSING_VALUE, detail='parent_state_id/interval/endpoint_state_id')
    if forcing.belts and belt_term is None:
        raise DrivingRefused('a forcing with D2 belts needs their belt term', MISSING_FORCE)
    if belt_term is not None:
        from . import integration_strength as _strength
        if type(belt_term) is not _strength.BeltTerm:
            raise DrivingRefused('the belt term is an integration_strength.BeltTerm', INVALID)
        if belt_term.network_id != network.network_id or set(belt_term.boundaries) != set(forcing.belts):
            raise DrivingRefused('the belt term does not match this network and the belts of the forcing', STALE)
        header = belt_term.strength.header      # P2 names the interval's parent and interval (ruling P6)
        if parent_state_id is not None and header.parent_state_id != parent_state_id:
            raise P.PortRefused('P2 names another parent state', P.STALE_IDENTITY, detail='parent_state_id')
        if interval is not None and tuple(header.interval) != tuple(interval):
            raise P.PortRefused('P2 names another interval', P.STALE_IDENTITY, detail='interval')
        if datum is None and header.datum_id is not None:
            raise P.PortRefused('the balance names no datum for P2', P.MISSING_VALUE, detail='datum_id')
        if header.datum_id != (None if datum is None else datum_id(datum)):
            raise P.PortRefused('P2 was evaluated on another datum', P.STALE_IDENTITY, detail='datum_id')
    # Axis-dependent vectors (authored torques, a mantle rotation, regional reactions) are meaningful only in named
    # axes: such a forcing must name the network's frame. An axis-free forcing (drag, gamma, slabs, k) may omit it.
    axis_dependent = bool(forcing.authored_torque_n_m or forcing.mantle_omega_rad_s is not None
                          or forcing.regional_reactions)
    if (axis_dependent or forcing.frame_id is not None) and forcing.frame_id != network.sphere.frame_id:
        raise DrivingRefused('the forcing is not declared in the network frame (axis-dependent vectors need it)',
                             STALE)
    if water_regime not in (None, 'airy', 'finite'):
        raise DrivingRefused('water regime is None (dry), airy or finite', INVALID)
    if water_regime is not None and forcing.gamma is None:
        raise DrivingRefused('a water regime without the GPE term', INVALID)
    if water_regime == 'airy':
        if water_density_kg_m3 is not None:
            water_density_kg_m3 = number(water_density_kg_m3, 'water density', positive=True)
    elif water_density_kg_m3 is not None:
        raise DrivingRefused('a water density without the declared Airy regime', INVALID)
    if parent_state_id is not None:
        P._sha(parent_state_id, 'parent state')
    if interval is not None:
        interval = _endpoint_interval(interval, network) if evaluation == 'end' else _interval(interval, network)
    if evaluation == 'end':
        P._sha(endpoint_state_id, 'endpoint state')
    if datum is not None and not isinstance(datum, Datum) and not radial:
        raise DrivingRefused('one shared Datum required', INVALID)
    if prepared is None:
        prepared = prepare(network, forcing)
    elif type(prepared) is not Prepared or prepared.prepared_id != _expected_prepared_id(network, forcing):
        raise DrivingRefused('the prepared operator does not match this network and resistance', STALE)
    plates = network.plate_ids
    order = {plate: i for i, plate in enumerate(plates)}
    n, radius = len(plates), prepared.radius_m
    terms = {}
    known = {boundary.boundary_id: boundary for boundary in network.boundaries}
    jumps = []
    radial_record = None
    if radial:
        from .integration_radial_pressure import RadialDatum, RadialPressureTrace
        if type(radial_pressure_port) is not RadialPressureTrace or type(datum) is not RadialDatum:
            raise DrivingRefused('issued radial pressure trace and its explicit RadialDatum required', INVALID)
        _support_matches(support, network)
        header = radial_pressure_port.header
        for actual, expected, label in (
            (header.port, 'P1', 'port'),
            (header.network_id, network.network_id, 'network_id'),
            (header.frame_id, network.sphere.frame_id, 'frame_id'),
            (header.support_id, support.support_id, 'support_id'),
            (radial_pressure_port.support_id, support.support_id, 'support_id'),
            (header.datum_id, datum_id(datum), 'datum_id'),
            (radial_pressure_port.datum.datum_id, datum_id(datum), 'datum_id'),
            (header.parameter_id, radial_pressure_port.moving_id, 'parameter_id'),
            (datum.reference_radius_m, radius, 'reference_radius_m')):
            if actual != expected:
                raise P.PortRefused('radial pressure belongs to another '+label, P.STALE_IDENTITY, detail=label)
        if parent_state_id is not None and header.parent_state_id != parent_state_id:
            raise P.PortRefused('radial pressure names another parent state', P.STALE_IDENTITY, detail='parent_state_id')
        if interval is not None and header.interval != interval:
            raise P.PortRefused('radial pressure names another interval', P.STALE_IDENTITY, detail='interval')
        if radial_pressure_port.points != 2*support.edges:
            raise P.PortRefused('radial pressure does not span the actual trace support', P.INCOMPATIBLE_SUPPORT)
        actual_source = endpoint_state_id if evaluation == 'end' else header.parent_state_id
        if radial_pressure_port.source_state_id != actual_source:
            raise P.PortRefused('radial pressure is not from the actual evaluated source state', P.STALE_IDENTITY,
                                detail='source_state_id')
        if evaluation == 'end':
            if not header.endpoint_s == header.interval[3] == network.time_s or header.interval[1] != network.step:
                raise P.PortRefused('radial pressure is not evaluated at the interval endpoint', P.UNSUPPORTED,
                                    detail=EVALUATION_ENDPOINT)
        else:
            if not header.endpoint_s == header.interval[2] == network.time_s or header.interval[0] != network.step:
                raise P.PortRefused('radial pressure is not evaluated at the interval start', P.UNSUPPORTED,
                                    detail=EVALUATION)
            parent_state_id = header.parent_state_id
        interval = header.interval
        k = radial_pressure_port.exact_pressure_moment_n_m
        if (type(k) is not tuple or len(k) != 2*support.edges or
                any(type(value) is not Fraction for value in k)):
            raise DrivingRefused('exact material-side radial pressure moments are required', INVALID)
        # One common scalar reference cancels around every closed plate. Remove
        # it exactly before force projection, preserving tiny real contrasts
        # against a large hydrostatic background. Never choose per-edge offsets.
        reference = k[0]
        central = tuple((k[i]+k[i+1])/2-reference for i in range(0, len(k), 2))
        differences = tuple(k[i+1]-k[i] for i in range(0, len(k), 2))
        try:
            trace, delta_k = [np.asarray([float(v) for v in values]) for values in (central, differences)]
        except OverflowError as exc:
            raise DrivingRefused('radial pressure contrast cannot be represented', INVALID) from exc
        if (not np.isfinite(trace).all() or not np.isfinite(delta_k).all() or
                any(q != 0 and value == 0 for values, projected in ((central, trace), (differences, delta_k))
                    for q, value in zip(values, projected))):
            raise DrivingRefused('radial pressure contrast projection overflows or erases a nonzero value', INVALID)
        # Physical radial wall: dA=r dr dtheta, lever arm=r n. Thus
        # tau_left=-int p r^2 dr * (b-a)=-R^2 K*(b-a); no planar gamma.
        pressure = np.zeros((n, 3)); jump = {}
        for e, chord in enumerate(support.end-support.start):
            left, right = support.plates[e]
            contribution = -radius*radius*trace[e]*chord
            pressure[order[left]] += contribution
            pressure[order[right]] -= contribution
            name = support.boundary_ids[int(support.edge_boundary[e])]
            jump[name] = jump.get(name, 0.)-radius*radius*delta_k[e]*chord
        terms['radial_pressure'] = pressure
        jumps = [(name, tuple(float(x) for x in value)) for name, value in sorted(jump.items())]
        radial_record = dict(port_id=radial_pressure_port.port_id, moving_id=radial_pressure_port.moving_id,
            material_id=radial_pressure_port.material_id, source_state_id=radial_pressure_port.source_state_id,
            support_id=support.support_id, interface_pressure_rule=interface_pressure_rule,
            closure_scope='explicit reduced central interface pressure; not a resolved interfacial stress',
            pressure_torque_factor=1., pressure_reference_radius_m=radius,
            common_reference_n_m=(str(reference.numerator), str(reference.denominator)),
            reference_rule='one exact first-side moment subtracted globally before binary64 force projection',
            basal_drag_radius_m=prepared.basal_drag_radius_m,
            interface_k_radius_m=radius if forcing.interface_k_pa_s else None)
    if forcing.gamma is not None:
        if columns_port is None or support is None:
            raise DrivingRefused('GPE needs a trace support and P1 columns', MISSING_FORCE)
        if datum is None:
            raise P.PortRefused('GPE needs the shared Datum', P.MISSING_VALUE, detail='datum')
        if type(columns_port) is not P.Columns:
            raise P.PortRefused('P1 columns are required', P.UNSUPPORTED, detail='columns_port')
        _support_matches(support, network)
        header = columns_port.header
        if header.network_id != network.network_id:
            raise P.PortRefused('P1 columns belong to another network', P.STALE_IDENTITY, detail='network_id')
        if parent_state_id is not None and header.parent_state_id != parent_state_id:
            raise P.PortRefused('P1 columns belong to another parent state', P.STALE_IDENTITY,
                                detail='parent_state_id')
        if interval is not None and header.interval != interval:
            raise P.PortRefused('P1 columns belong to another interval', P.STALE_IDENTITY, detail='interval')
        if header.support_id != support.support_id or columns_port.points != 2*support.edges:
            raise P.PortRefused('P1 columns are not on this trace support', P.INCOMPATIBLE_SUPPORT,
                                detail='support_id')
        if not isinstance(datum, Datum):
            raise DrivingRefused('one shared Datum required', INVALID)
        if header.datum_id != datum_id(datum):
            raise P.PortRefused('P1 columns were issued for another datum', P.STALE_IDENTITY, detail='datum_id')
        if header.frame_id != network.sphere.frame_id:
            raise P.PortRefused('P1 columns were issued in another frame', P.STALE_IDENTITY, detail='frame_id')
        if evaluation == 'end':
            if not header.endpoint_s == header.interval[3] == network.time_s or header.interval[1] != network.step:
                raise P.PortRefused('the coupled route evaluates P1 at the end of the interval, at the network time',
                                    P.UNSUPPORTED, detail=EVALUATION_ENDPOINT)
        else:
            if not header.endpoint_s == header.interval[2] == network.time_s or header.interval[0] != network.step:
                raise P.PortRefused('Part A evaluates P1 at the start of the interval, at the network time',
                                    P.UNSUPPORTED, detail=EVALUATION)
            parent_state_id = header.parent_state_id
        interval = header.interval
        u = trace_anomaly(datum, columns_port, water_regime=water_regime,
                          water_density_kg_m3=water_density_kg_m3).reshape(-1, 2)
        trace = u[:, 0]+TRACE_PARTITION*(u[:, 1]-u[:, 0])
        chord = support.end-support.start
        gpe = np.zeros((n, 3))
        jump = {}
        scale = -forcing.gamma*radius*radius
        for e in range(support.edges):
            left, right = support.plates[e]
            contribution = scale*trace[e]*chord[e]
            gpe[order[left]] += contribution
            gpe[order[right]] -= contribution
            name = support.boundary_ids[int(support.edge_boundary[e])]
            jump[name] = jump.get(name, 0.)+scale*(u[e, 1]-u[e, 0])*chord[e]
        terms['gpe'] = gpe
        jumps = [(name, tuple(float(x) for x in value)) for name, value in sorted(jump.items())]
    if forcing.slabs or forcing.slab_omitted:
        trenches = {name for name, boundary in known.items() if boundary.kind == S.TRENCH}
        slabs = dict(forcing.slabs)
        declared = set(slabs) | set(forcing.slab_omitted)
        if set(slabs) & set(forcing.slab_omitted):
            raise DrivingRefused('a trench has both a slab and a declared omission', INVALID)
        if declared - trenches:
            raise DrivingRefused('slab pull declared on a boundary that is not a trench', INVALID)
        if trenches - declared:
            raise DrivingRefused('trench %r has neither a slab nor a declared omission'
                                 % sorted(trenches - declared)[0], MISSING_FORCE)
        if slabs and datum is None:
            raise DrivingRefused('slab pull needs the shared Datum gravity', MISSING_FORCE)
        index = {vertex: i for i, vertex in enumerate(network.vertex_ids)}
        directions = np.asarray(network.vertex_direction, dtype=float)
        slab = np.zeros((n, 3))
        for name, record in sorted(slabs.items()):
            boundary = known[name]
            chain = list(boundary.vertex_ids)
            pairs = list(zip(chain, chain[1:]))+([(chain[-1], chain[0])] if boundary.closed else [])
            chord = sum((directions[index[b]]-directions[index[a]] for a, b in pairs), np.zeros(3))
            # int r x f ds = C g S R^2 (b - a) for the left plate's outward conormal; opposite for the right.
            sign = 1. if boundary.subducting_side == 'left' else -1.
            pull = record.transmission*datum.gravity_m_s2*record.section_mass_anomaly_kg_m*radius*radius
            plate = boundary.left_plate_id if sign > 0 else boundary.right_plate_id
            slab[order[plate]] += sign*pull*chord
        if slabs:
            terms['slab_pull'] = slab
    if forcing.authored_torque_n_m:
        authored = np.zeros((n, 3))
        for plate, value in forcing.authored_torque_n_m:
            if plate not in order:
                raise DrivingRefused('authored torque on unknown plate %r' % plate, INVALID)
            authored[order[plate]] = value
        terms['authored_torque'] = authored
    if forcing.regional_reactions:
        regional = np.zeros((n, 3))
        for name, (left, right) in forcing.regional_reactions:
            if name not in known:
                raise DrivingRefused('regional reaction on unknown boundary %r' % name, INVALID)
            regional[order[known[name].left_plate_id]] += left
            regional[order[known[name].right_plate_id]] += right
        terms['regional_reaction'] = regional
    if forcing.mantle_omega_rad_s is not None:
        terms['mantle_traction'] = np.einsum('pij,j->pi', prepared.basal, np.asarray(forcing.mantle_omega_rad_s))
    # Missing forces stay visible per item (rulings: driving-slab-omission, driving-partial-interface).
    omitted_slabs = tuple(sorted(forcing.slab_omitted))
    owned = set(dict(forcing.interface_k_pa_s)) | set(dict(forcing.regional_reactions)) | set(forcing.belts)
    omitted_interfaces = tuple(sorted(name for name in known if name not in owned))
    authored_plates = set(dict(forcing.authored_torque_n_m))
    unauthored = tuple(plate for plate in plates if plate not in authored_plates) if authored_plates else ()
    torque = np.zeros((n, 3))
    for value in terms.values():
        torque += value
    belt = None
    if belt_term is None:
        omega_flat, residual = solve_torque(prepared.matrix, torque.reshape(-1))
        omega = omega_flat.reshape(n, 3)
        power = _power(prepared, terms, omega, forcing)
    else:
        omega_flat, residual, belt_torque, report, belt_tangent = _belt_newton(
            prepared.matrix, torque.reshape(-1), belt_term, n, omega_start, with_tangent=True)
        omega = omega_flat.reshape(n, 3)
        unbalanced = prepared.matrix @ omega_flat-torque.reshape(-1)-belt_torque.reshape(-1)
        power = _power(prepared, terms, omega, forcing, belt_dissipation=report['dissipation_w'],
                       belt_column_work=report['column_work_w'],
                       unbalanced_w=math.fsum(float(x) for x in omega_flat*unbalanced))
        # Derived closure (ruling C2(3)): the torque residual (NEWTON_RELATIVE), the belt's U residual and the kernel's
        # work partition (PARTITION); the precedent is motion.solve's power gate at 2 FORCE_TOL.
        bound = NEWTON_RELATIVE+report['u_residual']+PARTITION
        power['closure_bound'] = bound
        if not power['column_closure_relative'] <= bound:
            raise DrivingRefused('the belt power account does not close within its derived bound', RESIDUAL)
        terms['belt'] = belt_torque.reshape(n, 3)
        belt = dict(report, residual=residual)
    cell_mean = ()
    if columns_port is not None and forcing.gamma is not None and columns_port.representation is not None:
        cell_mean = tuple(i for i, entry in enumerate(columns_port.representation) if entry is not None)
    # A half-unit trace-partition perturbation moves J_b/2 between the two plates. Without belts the response is
    # exactly linear. With belts use the converged M + J tangent: this is only a local linearisation with the
    # material state held fixed, not a solve at the finite new partition. At rest the nonlinear belt tangent is
    # unsupported; omit this diagnostic explicitly without changing the solved production motion.
    motion = []
    partition_operator, partition_evaluation = prepared.matrix, None
    if belt_term is not None and jumps:
        if any(response['u'] == 0. for response in belt_term.last[1]):
            partition_operator, partition_evaluation = None, PARTITION_AT_REST
        else:
            partition_operator = prepared.matrix+belt_tangent
            partition_evaluation = PARTITION_LOCAL
    for name, value in jumps if partition_operator is not None else ():
        boundary = known[name]
        rhs = np.zeros((n, 3))
        rhs[order[boundary.left_plate_id]] += np.asarray(value)/2
        rhs[order[boundary.right_plate_id]] -= np.asarray(value)/2
        delta = np.linalg.solve(partition_operator, rhs.reshape(-1)).reshape(n, 3)
        motion.append((name, _frozen(delta), float(np.max(np.linalg.norm(delta, axis=1)))*radius))
    geometry = prepared.geometry.sum(axis=0)
    net = np.linalg.solve(geometry, np.einsum('pij,pj->i', prepared.geometry, omega))
    record = dict(network_id=network.network_id, prepared_id=prepared.prepared_id, forcing_id=forcing.forcing_id,
                  columns_id=None if columns_port is None or forcing.gamma is None else columns_port.port_id,
                  datum=None if datum is None else datum.record(), omitted=sorted(forcing.omitted),
                  water_regime=water_regime, water_density_kg_m3=water_density_kg_m3,
                  parent_state_id=parent_state_id, interval=None if interval is None else list(interval),
                  frame_id=network.sphere.frame_id, omitted_slabs=list(omitted_slabs),
                  omitted_interfaces=list(omitted_interfaces), unauthored_plates=list(unauthored))
    if evaluation == 'end':                  # coupled-route fields; Part A records and identities are unchanged
        record.update(evaluation=EVALUATION_ENDPOINT, endpoint_state_id=endpoint_state_id)
    if omega_start is not None:
        record['omega_start'] = [float(x) for x in np.asarray(omega_start, dtype=float).reshape(-1)]
    if belt is not None:
        record['belt'] = belt
    if cell_mean:
        record['cell_mean_points'] = list(cell_mean)
    if partition_evaluation is not None:
        record['partition_motion_evaluation'] = partition_evaluation
    if radial_record is not None:
        record['radial_pressure'] = radial_record
    arrays = [('omega', _frozen(omega))]+[('term.'+k, _frozen(v)) for k, v in sorted(terms.items())]
    digest = hashlib.sha256(_json(dict(record, schema=SCHEMA, method=METHOD, route=ROUTE)))
    for name, array in arrays:
        digest.update(b'\0'+_json([name, array.dtype.str, list(array.shape)]))
        digest.update(array.tobytes())
    return _state._issue(Balance, network_id=network.network_id, network_time_s=float(network.time_s),
                         parent_state_id=parent_state_id, interval=interval,
                         prepared_id=prepared.prepared_id, forcing_id=forcing.forcing_id,
                         columns_id=record['columns_id'],
                         datum=None if record['datum'] is None else MappingProxyType(dict(record['datum'])),
                         water_regime=water_regime, water_density_kg_m3=water_density_kg_m3,
                         plate_ids=plates, frame_id=network.sphere.frame_id, mantle_label=forcing.mantle_label,
                         omitted_slabs=omitted_slabs, omitted_interfaces=omitted_interfaces,
                         unauthored_plates=unauthored, omega_rad_s=_frozen(omega),
                         terms=MappingProxyType({k: _frozen(v) for k, v in terms.items()}),
                         jump_sensitivity=tuple(jumps),
                         net_rotation_rad_s=_frozen(net), residual=residual, power=MappingProxyType(power),
                         partition_motion=tuple(motion), evaluation=EVALUATIONS[evaluation],
                         omitted=tuple(sorted(forcing.omitted)), trace_partition=TRACE_PARTITION,
                         balance_id=digest.hexdigest(), endpoint_state_id=endpoint_state_id,
                         belt=None if belt is None else MappingProxyType(belt), cell_mean_points=cell_mean,
                         partition_motion_evaluation=partition_evaluation,
                         radial_pressure=None if radial_record is None else MappingProxyType(radial_record))


def _power(prepared, terms, omega, forcing, *, belt_dissipation=None, belt_column_work=None, unbalanced_w=None):
    """Power account (W), evaluated per face and per interface edge block, independent of the block matrix.

    The exact identity used (rulings A5.3, form ii): omega . tau_known = sum_f D_f int |v - v_m|^2 dA
    + sum_e k int |dv|^2 ds + sum_f D_f int (v - v_m) . v_m dA, the last term being the power delivered into the
    mantle. tau_known is every applied torque except the mantle traction M omega_m; velocities are in the sphere
    frame.
    """
    mantle = np.zeros(3) if forcing.mantle_omega_rad_s is None else np.asarray(forcing.mantle_omega_rad_s)
    driving = math.fsum(float(np.dot(omega[i], value[i])) for name, value in sorted(terms.items())
                        if name not in ('mantle_traction', 'regional_reaction') for i in range(len(omega)))
    regional = terms.get('regional_reaction')
    regional_w = None if regional is None else math.fsum(float(np.dot(omega[i], regional[i]))
                                                         for i in range(len(omega)))
    if regional_w is not None:            # booked on its own line (ruling P3), not inside driving_w
        driving_known = driving+regional_w
    else:
        driving_known = driving
    scale = prepared.basal_drag_radius_m**4
    relative = omega[prepared.face_plate]-mantle
    basal = scale*math.fsum(float(x) for x in prepared.face_drag*np.einsum(
        'fi,fij,fj->f', relative, prepared.face_tensor, relative))
    interface = math.fsum(float((omega[i]-omega[j]) @ block @ (omega[i]-omega[j]))
                          for _, i, j, block in prepared.interfaces)
    to_mantle = scale*math.fsum(float(x) for x in prepared.face_drag*np.einsum(
        'i,fij,fj->f', mantle, prepared.face_tensor, relative))
    supplied = basal+interface+to_mantle
    column_closure = None
    if belt_dissipation is not None:
        # The D2 belt dissipates sum_e f_e.dv_e L_e = 2 S U L_e; the converged Newton balance leaves an unbalanced
        # torque whose power omega.R is reported separately (bounded by the residual). The belt's column work
        # sum_cells 2 e S dy L_e differs from 2 S U L_e by the belt's U residual and the kernel's work partition.
        supplied += belt_dissipation-unbalanced_w
        column_closure = abs(driving_known-(basal+interface+to_mantle+belt_column_work)) / max(
            abs(driving_known), basal+interface+abs(to_mantle)+belt_column_work, np.finfo(float).tiny)
    # Rounding is measured at the scale of every evaluated term's magnitude (rounds 1 and 2): the dissipation, the
    # power delivered to the mantle and the mantle-traction power |omega . M omega_m|, so that an exact balance whose
    # driving power is small next to them does not appear to fail.
    traction = terms.get('mantle_traction')
    mantle_power = 0. if traction is None else math.fsum(float(np.dot(omega[i], traction[i]))
                                                          for i in range(len(omega)))
    scale = max(abs(driving_known), basal+interface+abs(to_mantle)+abs(mantle_power)+(belt_dissipation or 0.))
    closure = abs(driving_known-supplied)/scale if scale else 0.
    out = dict(driving_w=driving, basal_dissipation_w=basal, interface_dissipation_w=interface,
               to_mantle_w=to_mantle, closure_relative=closure)
    if regional_w is not None:
        out['regional_reaction_w'] = regional_w
    if belt_dissipation is not None:
        out.update(belt_dissipation_w=belt_dissipation, belt_column_work_w=belt_column_work, unbalanced_w=unbalanced_w,
                   column_closure_relative=column_closure)
    return out


def _general_solve(matrix, rhs):
    """A general (non-symmetric) solve with the retained conditioning gate (condition number at most MAX_CONDITION)
    and relative residual algebra_relative."""
    matrix, rhs = _finite(matrix, 'tangent'), _finite(rhs, 'residual')
    singular = np.linalg.svd(matrix, compute_uv=False)
    if singular[-1] <= 0 or singular[0]/singular[-1] > MAX_CONDITION:
        raise DrivingRefused('the belt tangent is singular or ill-conditioned', NULLSPACE)
    step = np.linalg.solve(matrix, rhs)
    if np.any(rhs) and _relative(matrix @ step, rhs) > POLICY['algebra_relative']:
        raise DrivingRefused('torque residual', RESIDUAL)
    return step, float(singular[0]/singular[-1])


def _belt_newton(matrix, known, belt_term, n, omega_start=None, *, with_tangent=False):
    """M omega = b + tau_belt(omega) by exact-tangent Newton on omega (3P unknowns), rulings C1 and C2.

    ``belt_term.evaluate(omega)`` returns the belt torques (n, 3), the exact tangent J = -d tau/d omega (3n, 3n;
    non-symmetric where dS/dc != 0) and a report. Each step solves (M + J) d = -R by a general solve. The residual is
    ||M omega - b - tau||_2 / max(||M omega||, ||b||, ||tau||) (the _relative convention), held to NEWTON_RELATIVE,
    with the relative omega increment at most NEWTON_RELATIVE or cond(M + J) NEWTON_RELATIVE at most 1e-9 (else
    'unresolved inner solve'). Backtracking halves a step at most NEWTON_HALVINGS times (else 'nonconverged balance',
    detail 'halvings') and stops when the trial no longer changes omega; a trial the belt kernel refuses is halved,
    except a tangent that is not representable near U = 0, which refuses by name (detail 'tangent'). The accepted
    solution's assembled symmetric part of M + J must be positive semidefinite (else 'non-monotone belt response').
    Zero forcing returns omega = 0 exactly. ``omega_start`` is the start (a committed or iterate value); None starts
    from the belt-free balance. Nothing is issued on refusal. ``with_tangent`` additionally returns the converged
    tangent already calculated by the solve, for the local partition-sensitivity diagnostic.
    """
    known = np.asarray(known, dtype=float)
    if not np.any(known):
        # omega = 0 exactly; the belt is evaluated there (U = 0 on every edge: the continuous zero limit, no kernel
        # call), so its products are the exact zeros of this balance.
        torque, jacobian, report = belt_term.evaluate(np.zeros((n, 3)))
        report = dict(report, newton_iterations=0, newton_relative=0., omega_increment=0., condition=None)
        out = (np.zeros(3*n), 0., np.asarray(torque, dtype=float).reshape(-1), report)
        return out+(jacobian,) if with_tangent else out
    if omega_start is None:
        omega, _ = solve_torque(matrix, known)
    else:
        omega = np.array(omega_start, dtype=float).reshape(-1)
        if omega.shape != (3*n,) or not np.all(np.isfinite(omega)):
            raise DrivingRefused('the Newton start is one finite angular velocity per plate', INVALID)

    def residual_of(value):
        torque, jacobian, report = belt_term.evaluate(value.reshape(n, 3))
        torque = np.asarray(torque, dtype=float).reshape(-1)
        moment = matrix @ value
        residual = moment-known-torque
        scale = max(float(np.linalg.norm(moment)), float(np.linalg.norm(known)), float(np.linalg.norm(torque)))
        return residual, float(np.linalg.norm(residual))/scale, torque, np.asarray(jacobian, dtype=float), report
    residual, relative, torque, jacobian, report = residual_of(omega)
    increment, condition = math.inf, None
    for iteration in range(NEWTON_ITERATIONS):
        if relative <= NEWTON_RELATIVE and (increment <= NEWTON_RELATIVE or (
                condition is not None and condition*NEWTON_RELATIVE <= 1e-9)):
            break
        step, condition = _general_solve(matrix+jacobian, -residual)
        alpha = 1.
        for _ in range(NEWTON_HALVINGS):
            trial = omega+alpha*step
            if np.array_equal(trial, omega):
                break
            try:
                trial_state = residual_of(trial)
            except TectonicsError as exc:   # a trial outside the belt kernel's support is a rejected trial: halve it
                if getattr(exc, 'detail', None) == 'tangent':
                    raise                   # a tangent that is not representable near U = 0 refuses by name
                alpha /= 2
                continue
            if trial_state[1] < relative or relative <= NEWTON_RELATIVE:
                break
            alpha /= 2
        else:
            raise DrivingRefused('the belt balance made no progress in %d halvings' % NEWTON_HALVINGS, NONCONVERGED,
                                 'halvings')
        if np.array_equal(trial, omega):
            if relative <= NEWTON_RELATIVE:
                increment = 0.
                break
            raise DrivingRefused('a Newton step no longer changes omega before the residual is met', UNRESOLVED_INNER)
        increment = float(np.linalg.norm(trial-omega))/max(float(np.linalg.norm(trial)), np.finfo(float).tiny)
        omega = trial
        residual, relative, torque, jacobian, report = trial_state
    else:
        raise DrivingRefused('the belt balance did not converge in %d Newton steps' % NEWTON_ITERATIONS, NONCONVERGED)
    if not relative <= NEWTON_RELATIVE:
        raise DrivingRefused('the belt balance did not meet its residual', NONCONVERGED)
    if not (increment <= NEWTON_RELATIVE or (condition is not None and condition*NEWTON_RELATIVE <= 1e-9)):
        raise DrivingRefused('the inner solve stopped with an omega increment above its tolerance', UNRESOLVED_INNER)
    assembled = matrix+jacobian
    lowest = float(np.linalg.eigvalsh((assembled+assembled.T)/2)[0])
    if lowest < 0:
        raise DrivingRefused('the belt response is not monotone at the solution: the symmetric part of M + J is '
                             'indefinite', NON_MONOTONE)
    report = dict(report, newton_iterations=iteration, newton_relative=relative, omega_increment=increment,
                  condition=condition, symmetric_min_eigenvalue=lowest)
    out = (omega, relative, torque, report)
    return out+(jacobian,) if with_tangent else out


def stage_rotations(motion):
    """Finite stage rotations exp(omega dt) for I03 Motion.rotations from one P5 value, omega held constant over
    its own interval (declared, explicit), so the duration is the P5 interval's: dt = end_s - start_s.

    A zero angular velocity gives the exact identity. A turn of pi or more in one interval is refused: it must be
    divided into shorter intervals.
    """
    if type(motion) is not P.PlateMotion:
        raise DrivingRefused('stage rotations are taken from an issued P5 value', INVALID)
    dt = _positive(motion.duration_s, 'interval duration')
    rotations = {}
    for plate, omega in zip(motion.plate_ids, motion.omega_rad_s):
        vector = omega*dt
        if not float(np.linalg.norm(vector)) < math.pi:
            raise DrivingRefused('a plate turns by pi or more in one interval: divide it', UNSUPPORTED)
        rotations[plate] = exponential(vector)
    return rotations


def motion_port(result, header):
    """P5, issued only here from a solved Balance.

    The header must name the balance's parent state, interval, network, per-plate support, frame, forcing and
    datum (None exactly when the balance used none), with the endpoint at the start of the interval at the network
    time (Part A explicit evaluation). The value carries the D-P3 evaluation label.
    """
    if type(result) is not Balance:
        raise DrivingRefused('a Balance is required', INVALID)
    if type(header) is not P.Header or header.port != 'P5':
        raise P.PortRefused('a P5 header is required', P.UNSUPPORTED)
    if result.parent_state_id is None or result.interval is None:
        raise P.PortRefused('this balance is bound to no parent state and interval', P.MISSING_VALUE,
                            detail='parent_state_id/interval')
    checks = (('parent_state_id', result.parent_state_id), ('interval', result.interval),
              ('network_id', result.network_id), ('frame_id', result.frame_id),
              ('support_id', P.plate_support_id(result.network_id, result.plate_ids)),
              ('parameter_id', result.forcing_id),
              ('datum_id', None if result.datum is None else hashlib.sha256(_json(dict(result.datum))).hexdigest()))
    for name, expected in checks:
        if getattr(header, name) != expected:
            raise P.PortRefused('the P5 header does not match its balance', P.STALE_IDENTITY, detail=name)
    if not header.endpoint_s == header.interval[2] == result.network_time_s:
        raise P.PortRefused('Part A evaluates P5 at the start of the interval, at the network time', P.UNSUPPORTED,
                            detail=EVALUATION)
    return P._plate_motion(header, result.plate_ids, result.omega_rad_s, frame_id=result.frame_id,
                           balance_id=result.balance_id, evaluation=result.evaluation)
