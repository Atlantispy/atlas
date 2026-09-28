"""I02.2b package-owned continuable core of the first I02 route: the finite-strain column. WORKING NON-CANON.

A closed, laterally uniform, incompressible plane-strain strip of unit strike deforms by affine pure shear about its
surface: w = w0 lam, z = z0/lam, h = h0/lam, lam_dot = a lam and edge speed v = w a = w0 lam_dot. Temperature, raw
plastic history and material labels stay at their material points. Every stage rebuilds the current geometry,
quadrature widths, overburden and creep coefficients before balancing F = D v + F_column(v/w). Conduction follows the
material-coordinate heat equation, whose whole-strip operator is lam^2 times the reference one, so one eigensystem is
advanced along a thermal clock. No inflow, extraction, lateral localisation, rupture, melting or world assembly.

This module is the one implementation of those retained I01 equations, moved without change from
tools/check_i01_finite_strain.py (I02.2a) and split (I02.2b) around one immutable prepared ``Runner``: ``begin``
balances the reference stage, ``advance`` extends an accepted ``Prefix`` by whole steps of the runner's fixed schedule
dt = duration/steps, ``resume`` rebuilds a carried prefix and re-solves its endpoint stage, and ``finish`` constructs
the result. ``evolve`` keeps its signature, defaults and output as a wrapper over exactly that path; there is one step
loop. A piece works on local candidate values and only accepted steps reach the prefix it returns. The runner owns
private descriptors of its preparation and operators, captured once; it hands out only fresh inspection copies, so
neither those copies nor the caller's originals can reach a piece. The tool re-exports these objects and keeps the
prescribed-history conduction control, independent oracles, case loading, campaign and evidence.
integration_state.Continuation connects the common state; there is no transaction, storage, accepted clock or event
calendar here.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import dataclasses
import hashlib
import math

import numpy as np

from . import _integration_heat as heat
from . import _integration_motion as motion
from . import _integration_thermomechanical as tm
from . import _integration_weakening as weakening

STRETCH_CEILING = (.6, 1.4)              # frozen: the drag-only reachable range at the authored forcing and 1e14 s
TEMPERATURE_CEILING_K = (273., 1613.)    # frozen: the reviewed surface and strip-base temperatures
MAX_TEMPERATURE_STEP_K = 5.              # frozen: the declared per-step temperature guard ceiling
# The route's declared representation: the one package copy, shared by the common-state carrier and the I01 tool.
REPRESENTATION = {
    "geometry": "closed laterally uniform incompressible plane-strain strip of unit strike; affine pure shear about "
                "the surface: w = w0 lam, z = z0/lam, h = h0/lam; no inflow, extraction, births or mixing",
    "finite_strain": "log stretch ln(lam) with lam_dot = v/w0 = a lam; raw engineering plastic history is "
                     "constitutive memory, never geometry",
    "control": "constant external driving force balanced by disjoint generalised drag and the layered column "
               "resistance at the current geometry, overburden and temperature at every stage",
    "thermal": "material-coordinate conduction C0 dT/dt = -lam^2 (K0 T - b0) + radiogenic + mechanical heat; "
               "constant per-material properties, perfect layer contact, fixed-temperature surface and strip base; "
               "fixed enthalpy reference",
    "heating": "column creep plus plastic dissipation deposited once per material control volume; external drag "
               "dissipation is not column heat; no latent or adiabatic heat",
    "time_integration": "one reference eigensystem; ETD2 along the thermal clock dtau = 2 dt/(lam_n^-2 + lam_a^-2); "
                        "the same stage weights integrate history, stretch and every account; accepted endpoint "
                        "re-solved before commit",
}
REPRESENTATION_LIMITS = frozenset(("stretch_window", "temperature_window_k", "max_temperature_step_k"))
number, positive, check_deadline = weakening.number, weakening.positive, weakening.check_deadline
ratio, expired = tm.ratio, tm.expired
REBUILD_KEYS = {"thicknesses", "props", "densities", "boundaries", "reference_temperature"}
# Weighted-trapezoid accounts (account, stage power); all are whole-strip W/m of strike integrated to J/m.
STAGE_ACCOUNTS = (("drive_work_j_m", "drive_power_w_m"), ("drag_work_j_m", "drag_power_w_m"),
                  ("creep_work_j_m", "creep_power_w_m"), ("plastic_work_j_m", "plastic_power_w_m"),
                  ("column_work_j_m", "column_power_w_m"), ("heat_j_m", "heat_power_w_m"),
                  ("stored_j_m", "stored_power_w_m"))
THERMAL_ACCOUNTS = ("radiogenic_j_m", "reference_outflow_j_m", "departure_surface_loss_j_m",
                    "departure_basal_gain_j_m", "reference_surface_loss_j_m", "reference_basal_gain_j_m",
                    "thermal_change_j_m")
ACCOUNTS = tuple(name for name, _ in STAGE_ACCOUNTS)+THERMAL_ACCOUNTS       # the 14 accounts a prefix carries
# The running stage diagnostics of the retained evolve, in its order: four extrema, then four counters.
DIAGNOSTICS = ("max_force_relative", "max_power_relative", "min_source_w_m2", "min_dissipation_w_m",
               "restress_mismatches", "evaluations", "iterations", "stages")
COUNTS = frozenset(DIAGNOSTICS[4:])


class Refused(Exception):
    """An atomic refusal of one trial step; nothing of the trial is booked and the accepted prefix is returned."""

    def __init__(self, status, reason):
        super().__init__(reason)
        self.status, self.reason = status, reason


# ----------------------------------------------------------------------------- material strip at a stretch

def coefficients(base):
    """Temperature- and pressure-independent creep terms per (point, mechanism), padded as the kernel pads them.

    ``constant = log A - m log d`` and ``volume`` are heat.ArrheniusUpdate.of's; ``energy`` is E. At lam = 1 the
    rebuilt numerator E + P V is therefore ArrheniusUpdate's, bitwise.
    """
    arr = heat.ArrheniusUpdate.of(base)
    energy = np.zeros(arr.numerator.shape)
    for i in range(base.size):
        mechanisms, _, _ = base.layer_inputs[int(base.layer[i])]
        for j, m in enumerate(mechanisms):
            energy[i, j] = m.energy_j_mol
    return arr.constant, weakening.frozen(energy), arr.volume


def column_at(base, coeffs, stretch, temperature):
    """The reviewed preparation at the current geometry and transported temperature, with a new identity.

    At fixed material coordinates depths, quadrature widths, thickness and overburden (lithostatic, or the supplied
    oracle overburden) all scale as 1/lam; log c = [log A - m log d] - (E + P V)/(R T) and V/(R T) are rebuilt with
    the kernel's own expression. At lam = 1 this equals heat.ArrheniusUpdate.of(base).at(T) bitwise.
    """
    lam = number(stretch, "stretch", positive=True)
    t = np.asarray(temperature)
    if t.dtype.kind != "f" or t.shape != (base.size,) or not np.all(np.isfinite(t) & (t > 0)):
        raise ValueError("temperature must be finite, positive and one value per material point")
    constant, energy, volume = coeffs
    pressure = base.reference_pa/lam
    rt = heat.R*t
    log_c = constant-(energy+pressure[:, None]*volume)/rt[:, None]
    if not np.all(np.isfinite(log_c[base.active])):
        raise ValueError("log creep coefficient outside finite support")
    vrt = volume/rt[:, None] if base.closure == weakening.LITHOSTATIC else np.zeros_like(volume)
    digest = hashlib.sha256(base.fingerprint.encode()+np.float64(lam).tobytes()+t.astype(float).tobytes()).hexdigest()
    frozen = weakening.frozen
    return dataclasses.replace(base, thickness_m=base.thickness_m/lam, depth_m=frozen(base.depth_m/lam),
                               weight=frozen(base.weight/lam), reference_pa=frozen(pressure), temperature_k=frozen(t),
                               log_c=frozen(log_c), volume_rt=frozen(vrt), fingerprint=digest)


def stage(base, coeffs, law, stretch, temperature, kappa, drive, fractions, *, geometry_feedback=True, warm=None,
          deadline=None):
    """Balance F = D v + F_column(v/w) at the current geometry, overburden and temperature; heat from that state.

    ``drive.width_m`` is the reference width w0. The retained thermomechanical stage multiplies per-current-area
    column powers by the current width once; ``msource`` is the mechanical heat per reference-area control volume,
    (w/w0) sigma, used by the thermal clock. ``warm`` is a starting guess only, never a cached answer.
    """
    geometry = stretch if geometry_feedback else 1.
    prep = column_at(base, coeffs, geometry, temperature)
    local = motion.Drive(drive.force_n_m, drive.drag_pa_s, drive.width_m*geometry)
    s = tm.stage(prep, law, kappa, local, fractions, warm=warm, deadline=deadline)
    width = local.width_m
    return dict(s, geometry=geometry, width_m=width, thickness_m=prep.thickness_m, column_power_w_m=width*s["work"],
                heat_power_w_m=width*s["heat"], stored_power_w_m=width*s["stored"], speed=abs(s["rate"]),
                msource=geometry*s["source"])


# ----------------------------------------------------------------------------- thermal clock

def clock(stretch_n, stretch_a, dt):
    """Thermal-clock increment and stage weights of one step (method document, section 3).

    dtau = 2 dt/(lam_n^-2 + lam_a^-2) is the tau-trapezoid of dt/dtau = lam^-2 spanning exactly dt; the weights
    lam^-2/(lam_n^-2 + lam_a^-2) then integrate every account, history and stretch with one rule, exact for constants.
    """
    wn, wa = 1./(stretch_n*stretch_n), 1./(stretch_a*stretch_a)
    total = wn+wa
    return 2*dt/total, wn/total, wa/total


def clock_source(radiogenic, msource, stretch):
    """Source along the clock per reference area [W/m^2]: r0/lam^2 - r0 + m/lam^2; exactly m at lam = 1."""
    inv = 1./(stretch*stretch)
    return (radiogenic*inv-radiogenic)+msource*inv


def eigensystem(thermal, modes=None):
    """One reference eigensystem per support; its dt and time factors are replaced for every step."""
    modes = heat.prepare_propagator(thermal, 1.) if modes is None else modes
    if type(modes) is not heat.Propagator or modes.fingerprint != thermal.fingerprint:
        raise ValueError("eigensystem prepared for a different thermal support")
    return modes


def clock_propagator(modes, dtau):
    """The reference eigensystem over one clock increment: new exponential and phi factors, same eigenvectors.

    C0^(-1/2) (lam^2 K0) C0^(-1/2) = lam^2 Q Lambda Q^T with a constant whole-strip capacity, so only the factors of
    -Lambda dtau change. A step's factors are never reused for a different increment.
    """
    e, p1, p2, p3 = heat.phi_functions(-modes.lam*dtau)
    frozen = weakening.frozen
    return dataclasses.replace(modes, dt=dtau, e=frozen(e), p1=frozen(p1), p2=frozen(p2), p3=frozen(p3))


def rebuilt_propagator(thermal, inputs, stretch, dt):
    """Comparator only: the retained support assembled at the current geometry and factorised again for the step."""
    now = heat.prepare_thermal(thermal.layer, thermal.depth_m/stretch, thermal.volume_m/stretch,
                               [h/stretch for h in inputs["thicknesses"]], inputs["props"], inputs["densities"],
                               inputs["boundaries"], reference_temperature=inputs["reference_temperature"])
    return heat.prepare_propagator(now, dt)


def check_rebuild(thermal, inputs):
    if type(inputs) is not dict or set(inputs) != REBUILD_KEYS:
        raise ValueError("rebuild declares only thicknesses, properties, densities, boundaries and reference")
    again = heat.prepare_thermal(thermal.layer, thermal.depth_m, thermal.volume_m, list(inputs["thicknesses"]),
                                 inputs["props"], inputs["densities"], inputs["boundaries"],
                                 reference_temperature=inputs["reference_temperature"],
                                 mechanical_fingerprint=thermal.mechanical_fingerprint)
    if again.fingerprint != thermal.fingerprint:
        raise ValueError("rebuild inputs do not reproduce the supplied thermal support")


def advance_map(thermal, modes, rebuild, dtau, dt):
    """Conduction over one clock increment: returns f(theta, g_n[, g_a]) -> (theta_new, integral of theta dtau)."""
    if rebuild is not None:
        # Frozen coefficient lam_bar^2 = dtau/dt over dt: the same exponentials, source lam_bar g per current area.
        lam = math.sqrt(dtau/dt)
        p, scale = rebuilt_propagator(thermal, rebuild, lam, dt), lam*lam

        def rebuilt(theta, g_n, g_a=None):
            new, integral = heat.conduct(p, theta, lam*g_n, None if g_a is None else lam*g_a)
            return new, scale*integral
        return rebuilt
    if modes is not None:
        p = clock_propagator(modes, dtau)
        return lambda theta, g_n, g_a=None: heat.conduct(p, theta, g_n, g_a)
    capacity = np.asarray(thermal.capacity)

    def still(theta, g_n, g_a=None):          # conduction explicitly off: C0 dtheta/dtau = g, exact for linear g
        g_a = g_n if g_a is None else g_a
        return (theta+dtau*(g_n+g_a)/2/capacity,
                dtau*theta+dtau*dtau*(g_n/2+(g_a-g_n)/6)/capacity)
    return still


# ----------------------------------------------------------------------------- coupled evolution

def window_of(window):
    """A declared stretch/temperature window inside the frozen ceilings; a tighter window is always admitted."""
    if type(window) is not dict or set(window) != {"stretch", "temperature_k"}:
        raise ValueError("window declares only its stretch and temperature ranges")
    bounds = []
    for key in ("stretch", "temperature_k"):
        pair = window[key]
        if type(pair) not in (list, tuple) or len(pair) != 2:
            raise ValueError(key+" window must be [low, high]")
        bounds += [number(value, key+" window") for value in pair]
    lo, hi, tlo, thi = bounds
    if not STRETCH_CEILING[0] <= lo < 1. < hi <= STRETCH_CEILING[1]:
        raise ValueError("stretch window must contain the reference geometry and lie within [0.6, 1.4]")
    if not TEMPERATURE_CEILING_K[0] <= tlo < thi <= TEMPERATURE_CEILING_K[1]:
        raise ValueError("temperature window must lie within the reviewed [273, 1613] K range")
    return lo, hi, tlo, thi


def paired(base, thermal, *, modes, conduction, rebuild, inputs):
    """Refuse stale, foreign, replaced or contradictory preparations before any work; return the modes to reuse."""
    if type(base) is not weakening.PreparedColumn or type(thermal) is not heat.ThermalColumn:
        raise ValueError("reviewed mechanical preparation and thermal support required")
    if inputs is not None and weakening.fingerprint(*inputs) != base.fingerprint:
        raise ValueError("prepared coefficients are stale for these inputs; prepare again")
    if thermal.mechanical_fingerprint != base.fingerprint:
        raise ValueError("thermal support was prepared for a different mechanical column")
    if not heat.same_support(thermal, base):          # a matching label is not evidence of equal support
        raise ValueError("thermal layers, depths or widths differ from the mechanical quadrature")
    if np.any(np.asarray(base.pore_pa) != 0):
        raise ValueError("supplied pore pressure is not transported under finite strain")
    if type(conduction) is not bool:
        raise ValueError("conduction must be boolean")
    if not conduction:
        if modes is not None or rebuild is not None or any(thermal.boundary_conductance):
            raise ValueError("conduction off admits only an insulated support, without modes or a rebuild")
        return None
    if rebuild is not None:
        if modes is not None:
            raise ValueError("the rebuilt comparator reuses no eigensystem")
        check_rebuild(thermal, rebuild)
        return None
    return eigensystem(thermal, modes)


def weighted(dt, wn, wa, a, b, name):
    return dt*(wn*a[name]+wa*b[name])


# ----------------------------------------------------------------------------- the continuable core

def detached(value):
    """A private copy of nested caller dict/list/tuple/array containers; immutable scalars are shared."""
    if type(value) is dict:
        return {key: detached(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return type(value)(detached(item) for item in value)
    if isinstance(value, np.ndarray):
        return np.array(value)
    return value


def _fresh(array):
    """A new descriptor chain over immutable bytes: callers never reach a held descriptor or its ``.base``.

    Compact immutable ``bytes`` backing is shared without copying the payload; any other array is copied once.
    """
    owner = array
    while type(owner) is np.ndarray:
        owner = owner.base
    if type(owner) is not bytes or len(owner) != array.nbytes or not array.flags.c_contiguous:
        return weakening.frozen(array, array.dtype)
    return np.frombuffer(owner, dtype=array.dtype).reshape(array.shape)


def _owned(item):
    """A copy of a prepared dataclass whose arrays are new descriptors over immutable bytes (see ``_fresh``).

    Scalars, texts and tuples are shared; nothing is re-derived, rehashed or factorised. prepare_run() captures the
    checked preparation, support and eigensystem this way once, and Runner inspection hands out further copies.
    """
    if item is None:
        return None
    values = {f.name: getattr(item, f.name) for f in dataclasses.fields(item)}
    return dataclasses.replace(item, **{name: _fresh(value) for name, value in values.items()
                                        if isinstance(value, np.ndarray)})


def _frozen_stage(s):
    """A retained stage whose arrays are detached immutable copies: warm data a holder cannot edit in place."""
    return {key: weakening.frozen(value, value.dtype) if isinstance(value, np.ndarray) else value
            for key, value in s.items()}


def _issue(cls, **values):
    item = object.__new__(cls)
    for key, value in values.items():
        object.__setattr__(item, key, value)
    return item


class _Issued:
    """Issued by this module only: no public constructor, replace(), pickle or copies of prepared operators."""
    __slots__ = ()

    def __init__(self, *args, **kwargs):
        raise TypeError(type(self).__name__+" is issued by prepare_run(), begin(), advance() or resume() only")

    def __reduce__(self):
        raise TypeError(type(self).__name__+" is never serialised: rebuild it from the pinned inputs")

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self


@dataclasses.dataclass(frozen=True, eq=False, init=False, slots=True)
class Runner(_Issued):
    """Immutable prepared context of one scheduled history, reused unchanged by every piece and never serialised.

    The reviewed preparation and its paired support, the one reference eigensystem (None with conduction off or the
    rebuilt comparator), the frozen creep terms, typed law and drive, heat fractions, declared window and step guard,
    and the fixed schedule ``dt = duration_s/steps`` over ``steps`` whole steps. A continuation cannot choose a new dt.
    Pieces read only the private preparation, support, eigensystem, creep terms and rebuild inputs. ``base``,
    ``thermal``, ``modes``, ``coeffs`` and ``rebuild`` return fresh copies of the same types over the same immutable
    bytes on every access, so editing one (shape, dtype, ``.base`` or nested data) never reaches a piece.
    """
    _base: weakening.PreparedColumn = dataclasses.field(repr=False)
    _thermal: heat.ThermalColumn = dataclasses.field(repr=False)
    law: weakening.WeakeningLaw
    drive: motion.Drive
    fractions: tuple
    _coeffs: tuple = dataclasses.field(repr=False)
    _modes: object = dataclasses.field(repr=False)
    _rebuild: object = dataclasses.field(repr=False)
    geometry_feedback: bool
    warm_start: bool
    bounds: tuple
    limit: float
    duration_s: float
    steps: int
    dt: float
    produced_w_m2: float
    reference_flows: tuple

    @property
    def base(self):
        return _owned(self._base)

    @property
    def thermal(self):
        return _owned(self._thermal)

    @property
    def modes(self):
        return _owned(self._modes)

    @property
    def coeffs(self):
        return tuple(_fresh(array) for array in self._coeffs)

    @property
    def rebuild(self):
        return detached(self._rebuild)


@dataclasses.dataclass(frozen=True, eq=False, init=False, slots=True)
class Prefix(_Issued):
    """One accepted prefix of a scheduled history, with the balanced stage at its endpoint; immutable.

    ``accepted`` is the global accepted-step index: elapsed time is ``accepted*dt`` of the runner's schedule. The
    fields are exactly what a common state carries (``carried()``), measured from the reference at lam = 1 with the
    original ``theta0``/``kappa0``. The endpoint stage is warm operational data owned by this prefix alone and bound
    to the runner that solved it, so it cannot outlive its state or physics; it is never booked twice.
    """
    _runner: Runner = dataclasses.field(repr=False)
    accepted: int
    stretch: float
    clock_s: float
    displacement_m: float
    log_strain_quadrature: float
    log_path: float
    max_step_energy_relative: float
    max_temperature_step_k: float
    velocity_start_m_s: float
    column_force_start_n_m: float
    accounts: tuple
    diagnostics: tuple
    _theta0: np.ndarray = dataclasses.field(repr=False)
    _theta: np.ndarray = dataclasses.field(repr=False)
    _kappa0: np.ndarray = dataclasses.field(repr=False)
    _kappa: np.ndarray = dataclasses.field(repr=False)
    _yield: np.ndarray = dataclasses.field(repr=False)
    _stage: dict = dataclasses.field(repr=False)

    def carried(self):
        """The carried values as fresh descriptors over immutable bytes: exactly resume()'s keywords."""
        return dict(accepted=self.accepted, stretch=self.stretch, clock_s=self.clock_s,
                    displacement_m=self.displacement_m, log_strain_quadrature=self.log_strain_quadrature,
                    log_path=self.log_path, theta0=_fresh(self._theta0), theta=_fresh(self._theta),
                    kappa0=_fresh(self._kappa0), kappa=_fresh(self._kappa), accounts=dict(self.accounts),
                    diagnostics=dict(self.diagnostics), yield_counts=_fresh(self._yield),
                    max_step_energy_relative=self.max_step_energy_relative,
                    max_temperature_step_k=self.max_temperature_step_k, velocity_start_m_s=self.velocity_start_m_s,
                    column_force_start_n_m=self.column_force_start_n_m)

    @property
    def stage_work(self):
        """Solver work of the held endpoint stage: operational only, never a booked counter."""
        return dict(evaluations=self._stage["evaluations"], iterations=self._stage["iterations"])


def prepare_run(base, thermal, law, drive, *, duration_s, steps, window, temperature_step_k, fractions, policy,
                modes=None, conduction=True, geometry_feedback=True, warm_start=True, rebuild=None, inputs=None):
    """Validate and prepare one scheduled history once, with evolve's configuration refusals in evolve's order.

    ``steps`` whole steps of dt = duration_s/steps form the fixed schedule, capped by ``policy["max_steps"]`` (at most
    256). The eigensystem is prepared here unless supplied. Once checked, the preparation, support and eigensystem are
    captured as private copies over the same immutable bytes and ``rebuild`` as a private nested copy, so objects the
    caller still holds never reach a piece. The initial departure and history are checked by begin().
    """
    lo, hi, tlo, thi = window_of(window)
    if type(law) is not weakening.WeakeningLaw or type(drive) is not motion.Drive:
        raise ValueError("typed weakening law and external drive required")
    if type(geometry_feedback) is not bool or type(warm_start) is not bool:
        raise ValueError("geometry_feedback and warm_start must be boolean")
    modes = paired(base, thermal, modes=modes, conduction=conduction, rebuild=rebuild, inputs=inputs)
    # One-time capture of the checked objects: every later read and every piece uses these private copies.
    base, thermal, modes, rebuild = _owned(base), _owned(thermal), _owned(modes), detached(rebuild)
    heat.policy_limits(policy)
    if type(steps) is not int or not 1 <= steps <= policy["max_steps"]:
        raise ValueError("accepted steps must be an integer in 1..256")
    limit = positive(temperature_step_k, "temperature step guard")
    if limit > MAX_TEMPERATURE_STEP_K:
        raise ValueError("temperature step guard above the declared 5 K ceiling")
    duration = positive(duration_s, "duration")
    fractions = heat.heat_fractions(fractions)
    law.certify(base)
    flows = tm.reference_throughput(thermal, 0.)
    return _issue(Runner, _base=base, _thermal=thermal, law=law, drive=drive, fractions=fractions,
                  _coeffs=coefficients(base), _modes=modes, _rebuild=rebuild,
                  geometry_feedback=geometry_feedback, warm_start=warm_start, bounds=(lo, hi, tlo, thi), limit=limit,
                  duration_s=duration, steps=steps, dt=duration/steps,
                  produced_w_m2=math.fsum(np.asarray(thermal.radiogenic)),   # W/m^2 of reference area; constant
                  reference_flows=(flows["surface_outflow_w_m2"], flows["basal_inflow_w_m2"],
                                   flows["balance_relative"]))


def _solve(run, stretch, th, k, previous, deadline, trial=True):
    """One balanced stage at (stretch, T_steady + th, k); a failed trial is an atomic constitutive refusal."""
    warm = previous if run.warm_start and previous is not None and previous["x"] is not None else None
    try:
        return stage(run._base, run._coeffs, run.law, stretch, np.asarray(run._thermal.steady_k)+th, k, run.drive,
                     run.fractions, geometry_feedback=run.geometry_feedback, warm=warm, deadline=deadline)
    except ValueError as exc:
        if not trial:
            raise
        raise Refused("REFUSED_CONSTITUTIVE", str(exc)) from exc


def begin(run, kappa0, theta0=None, *, deadline=None):
    """Initialise a history at the reference geometry lam = 1: the reference stage is balanced and noted once.

    ``theta0`` (zero when omitted, as in evolve) and ``kappa0`` are the original departure and inherited history.
    Nothing is accepted; the prefix holds zero steps and zero accounts.
    """
    if type(run) is not Runner:
        raise ValueError("a prepared runner is required")
    base = run._base
    kappa0 = weakening.history_array(base, kappa0).copy()
    theta = np.zeros(base.size) if theta0 is None else tm.departure(theta0, base.size)
    _, _, tlo, thi = run.bounds
    temperature = np.asarray(run._thermal.steady_k)+theta    # fixed enthalpy reference; never a stretched geotherm
    if not bool(np.all((temperature >= tlo) & (temperature <= thi))):
        raise ValueError("initial material temperatures lie outside the declared window")
    current = _solve(run, 1., theta, kappa0, None, deadline, trial=False)
    stats = dict(max_force_relative=0., max_power_relative=0., min_source_w_m2=math.inf, min_dissipation_w_m=math.inf,
                 restress_mismatches=0, evaluations=0, iterations=0, stages=0)
    tm.note(stats, current)
    frozen = weakening.frozen
    theta, kappa0 = frozen(theta), frozen(kappa0)
    return _issue(Prefix, _runner=run, accepted=0, stretch=1., clock_s=0., displacement_m=0.,
                  log_strain_quadrature=0., log_path=0., max_step_energy_relative=0., max_temperature_step_k=0.,
                  velocity_start_m_s=current["velocity_m_s"], column_force_start_n_m=current["force"],
                  accounts=tuple(dict.fromkeys(ACCOUNTS, 0.).items()), diagnostics=tuple(stats.items()),
                  _theta0=theta, _theta=theta, _kappa0=kappa0, _kappa=kappa0,
                  _yield=frozen(current["plastic_rate"] > 0, np.int64), _stage=_frozen_stage(current))


def advance(run, prefix, steps, *, deadline=None):
    """Extend an accepted prefix by ``steps`` whole steps of the runner's fixed schedule: the one step loop.

    Each accepted step: Euler stretch lam_a = lam_n + dt v_n/w0; clock increment and stage weights from (lam_n,
    lam_a); ETD2 predictor temperature; predictor stage at (lam_a, T_a, kappa_n + dt kdot_n); ETD2 corrector with the
    clock source linear between the stages; weighted-trapezoid history, stretch, displacement and accounts; checks;
    the endpoint re-solved at the committed state before anything is booked. Trials run on local candidate values:
    stretch-window, temperature-window, temperature-step, constitutive and deadline refusals return the accepted
    prefix (``prefix`` itself when nothing was accepted) with the retained status and reason. Returns (prefix,
    status, reason); "COMPLETE" means this piece, not necessarily the whole schedule.
    """
    if type(run) is not Runner or type(prefix) is not Prefix or prefix._runner is not run:
        raise ValueError("an accepted prefix issued for this prepared runner is required")
    remaining = run.steps-prefix.accepted
    if type(steps) is not int or not 1 <= steps <= remaining:
        raise ValueError("a piece selects whole remaining steps of the fixed schedule: %d remain" % remaining)
    base, thermal, drive, modes, rebuild = run._base, run._thermal, run.drive, run._modes, run._rebuild
    lo, hi, tlo, thi = run.bounds
    limit, dt, w0 = run.limit, run.dt, drive.width_m
    reference = np.asarray(thermal.steady_k)          # fixed enthalpy reference; never reset to a stretched geotherm
    r0, capacity = np.asarray(thermal.radiogenic), np.asarray(thermal.capacity)
    produced = run.produced_w_m2
    g_top, g_bot = thermal.boundary_conductance
    q_top, q_base, _ = run.reference_flows

    def inside(temperature):
        return bool(np.all((temperature >= tlo) & (temperature <= thi)))

    def solve(stretch, th, k, previous):
        return _solve(run, stretch, th, k, previous, deadline)

    kappa0 = prefix._kappa0
    theta, kappa, lam, path, current = prefix._theta, prefix._kappa, prefix.stretch, prefix.log_path, prefix._stage
    displacement, log_quadrature, tau = prefix.displacement_m, prefix.log_strain_quadrature, prefix.clock_s
    acc, stats = dict(prefix.accounts), dict(prefix.diagnostics)
    yield_stages = np.array(prefix._yield)
    worst_energy, worst_step = prefix.max_step_energy_relative, prefix.max_temperature_step_k
    accepted, status, reason = prefix.accepted, "COMPLETE", None
    for _ in range(steps):
        try:
            check_deadline(deadline)
            lam_a = lam+dt*current["velocity_m_s"]/w0
            if not lo <= lam_a <= hi:
                raise Refused("REFUSED_STRETCH_WINDOW", "predictor stretch leaves the declared window")
            dtau, wn, wa = clock(lam, lam_a, dt)
            conduct = advance_map(thermal, modes, rebuild, dtau, dt)
            g_n = clock_source(r0, current["msource"], lam)
            theta_a, _ = conduct(theta, g_n)
            if not np.all(np.isfinite(theta_a)):
                raise RuntimeError("predictor temperature is not finite")
            if not inside(reference+theta_a):
                raise Refused("REFUSED_TEMPERATURE_WINDOW", "predictor temperature leaves the declared window")
            predictor = solve(lam_a, theta_a, kappa+dt*current["kdot"], current)
            new_theta, integral = conduct(theta, g_n, clock_source(r0, predictor["msource"], lam_a))
            new_kappa = kappa+dt*(wn*current["kdot"]+wa*predictor["kdot"])
            moved = weighted(dt, wn, wa, current, predictor, "velocity_m_s")
            new_lam = lam+moved/w0
            new_path = path+weighted(dt, wn, wa, current, predictor, "speed")
            if not lo <= new_lam <= hi:
                raise Refused("REFUSED_STRETCH_WINDOW", "endpoint stretch leaves the declared window")
            jump = float(np.abs(new_theta-theta).max())
            if jump > limit:
                raise Refused("REFUSED_TEMPERATURE_STEP", "temperature change exceeds the per-step guard")
            new_t = reference+new_theta
            if not np.all(np.isfinite(new_t)) or np.any(new_t <= 0) or np.any(new_kappa < kappa):
                raise RuntimeError("temperature nonpositive or raw history decreased")
            if not inside(new_t):
                raise Refused("REFUSED_TEMPERATURE_WINDOW", "endpoint temperature leaves the declared window")
            if np.any(new_kappa-kappa0 > 2*new_path*(1+1e-10)):
                raise RuntimeError("plastic history exceeds twice the accumulated log-strain path")
            endpoint = solve(new_lam, new_theta, new_kappa, predictor)     # re-solved before anything is booked
            check_deadline(deadline)                                    # final solve may consume the remaining budget
        except RuntimeError:
            if not expired(deadline):
                raise
            status, reason = "REFUSED_DEADLINE", "cooperative time budget exhausted during the trial step"
            break
        except Refused as refusal:
            status, reason = refusal.status, refusal.reason
            break
        heat_step = weighted(dt, wn, wa, current, predictor, "heat_power_w_m")
        surface = w0*g_top*integral[0]                 # departure heat leaving at the surface [J/m]
        base_in = -w0*g_bot*integral[-1]               # departure heat entering at the strip base
        radiogenic, outflow = w0*produced*dt, w0*produced*dtau
        change = w0*math.fsum(capacity*(new_theta-theta))
        budget = heat_step+(radiogenic-outflow)-surface+base_in
        worst_energy = max(worst_energy, ratio(change-budget, abs(heat_step)+abs(radiogenic-outflow)+abs(surface)
                                               + abs(base_in)))
        for key, name in STAGE_ACCOUNTS:
            acc[key] += weighted(dt, wn, wa, current, predictor, name)
        for key, value in (("radiogenic_j_m", radiogenic), ("reference_outflow_j_m", outflow),
                           ("departure_surface_loss_j_m", surface), ("departure_basal_gain_j_m", base_in),
                           ("reference_surface_loss_j_m", w0*q_top*dtau), ("reference_basal_gain_j_m", w0*q_base*dtau),
                           ("thermal_change_j_m", change)):
            acc[key] += value
        displacement += moved
        log_quadrature += weighted(dt, wn, wa, current, predictor, "rate")
        tau += dtau
        theta, kappa, lam, path, current = new_theta, new_kappa, new_lam, new_path, endpoint
        worst_step = max(worst_step, jump)
        accepted += 1
        for s in (predictor, endpoint):
            tm.note(stats, s)
            yield_stages += s["plastic_rate"] > 0
    if accepted == prefix.accepted:
        return prefix, status, reason
    frozen = weakening.frozen
    return _issue(Prefix, _runner=run, accepted=accepted, stretch=lam, clock_s=tau, displacement_m=displacement,
                  log_strain_quadrature=log_quadrature, log_path=path, max_step_energy_relative=worst_energy,
                  max_temperature_step_k=worst_step, velocity_start_m_s=prefix.velocity_start_m_s,
                  column_force_start_n_m=prefix.column_force_start_n_m, accounts=tuple(acc.items()),
                  diagnostics=tuple(stats.items()), _theta0=prefix._theta0, _theta=frozen(theta),
                  _kappa0=prefix._kappa0, _kappa=frozen(kappa), _yield=frozen(yield_stages, np.int64),
                  _stage=_frozen_stage(current)), status, reason


def resume(run, *, accepted, stretch, clock_s, displacement_m, log_strain_quadrature, log_path, theta0, theta, kappa0,
           kappa, accounts, diagnostics, yield_counts, max_step_energy_relative, max_temperature_step_k,
           velocity_start_m_s, column_force_start_n_m, deadline=None):
    """Rebuild a carried accepted prefix (at least one step) and re-solve its endpoint stage cold at that state.

    Only cumulative values are carried. The endpoint stage is operational warm data: it is balanced again without a
    guess and is never noted, booked or counted, so a resumed endpoint is not observed twice. Its solver path differs
    from the uninterrupted run's warm path, so later evaluation/iteration counts may differ while the physical results
    agree within the solver tolerances. Inside one prepared session, advance() keeps the warm stage instead.
    """
    if type(run) is not Runner:
        raise ValueError("a prepared runner is required")
    base = run._base
    lo, hi, tlo, thi = run.bounds
    if type(accepted) is not int or not 1 <= accepted <= run.steps:
        raise ValueError("a carried prefix holds 1..%d accepted steps; begin() issues the reference" % run.steps)
    stretch, clock_s, log_path = (number(v, name) for v, name in ((stretch, "stretch"), (clock_s, "clock"),
                                                                  (log_path, "log-strain path")))
    displacement_m, log_strain_quadrature = number(displacement_m, "displacement"), number(log_strain_quadrature,
                                                                                         "log-strain quadrature")
    worst_energy = number(max_step_energy_relative, "step energy residual", nonnegative=True)
    worst_step = number(max_temperature_step_k, "largest temperature step", nonnegative=True)
    velocity, force = number(velocity_start_m_s, "initial velocity"), number(column_force_start_n_m, "initial force")
    if not lo <= stretch <= hi or clock_s <= 0 or log_path < 0 or worst_step > run.limit:
        raise ValueError("carried stretch, clock, path or temperature step lie outside the admitted history")
    theta0, theta = (tm.departure(a, base.size) for a in (theta0, theta))
    kappa0, kappa = (weakening.history_array(base, a) for a in (kappa0, kappa))
    for temperature in (np.asarray(run._thermal.steady_k)+theta0, np.asarray(run._thermal.steady_k)+theta):
        if not np.all((temperature >= tlo) & (temperature <= thi)):
            raise ValueError("carried material temperatures lie outside the declared window")
    if np.any(kappa < kappa0) or np.any(kappa-kappa0 > 2*log_path*(1+1e-10)):
        raise ValueError("carried raw history decreased or exceeds twice the accumulated log-strain path")
    if type(accounts) is not dict or set(accounts) != set(ACCOUNTS):
        raise ValueError("a carried prefix holds exactly the 14 accumulated accounts")
    if type(diagnostics) is not dict or set(diagnostics) != set(DIAGNOSTICS):
        raise ValueError("a carried prefix holds exactly the eight running stage diagnostics")
    stats = {}
    for name in DIAGNOSTICS:
        value = diagnostics[name]
        if name in COUNTS and (type(value) is not int or value < 0):
            raise ValueError("stage counters are nonnegative integers")
        stats[name] = value if name in COUNTS else number(value, name)
    if stats["stages"] != 1+2*accepted:
        raise ValueError("stage count is not the reference balance plus two stages per accepted step")
    yields = np.asarray(yield_counts)
    if (yields.dtype.kind not in "iu" or yields.shape != (base.size,) or np.any(yields < 0)
            or np.any(yields > stats["stages"])):
        raise ValueError("yield counts must be integers within the booked stages, one per material point")
    current = _solve(run, stretch, theta, kappa, None, deadline, trial=False)
    frozen = weakening.frozen
    return _issue(Prefix, _runner=run, accepted=accepted, stretch=stretch, clock_s=clock_s,
                  displacement_m=displacement_m, log_strain_quadrature=log_strain_quadrature, log_path=log_path,
                  max_step_energy_relative=worst_energy, max_temperature_step_k=worst_step,
                  velocity_start_m_s=velocity, column_force_start_n_m=force,
                  accounts=tuple((name, number(accounts[name], name)) for name in ACCOUNTS),
                  diagnostics=tuple(stats.items()), _theta0=frozen(theta0), _theta=frozen(theta),
                  _kappa0=frozen(kappa0), _kappa=frozen(kappa), _yield=frozen(yields, np.int64),
                  _stage=_frozen_stage(current))


def finish(run, prefix, status, reason):
    """The retained evolve result of an accepted prefix: derived identities are built on a copy, never carried.

    Returned arrays and the final stage are fresh copies; editing them cannot reach the prefix or its warm stage.
    """
    if type(run) is not Runner or type(prefix) is not Prefix or prefix._runner is not run:
        raise ValueError("an accepted prefix issued for this prepared runner is required")
    base, thermal, drive = run._base, run._thermal, run.drive
    w0, dt = drive.width_m, run.dt
    capacity = np.asarray(thermal.capacity)
    produced = run.produced_w_m2
    q_top, q_base, balance = run.reference_flows
    acc, stats = dict(prefix.accounts), dict(prefix.diagnostics)
    accepted, tau, lam = prefix.accepted, prefix.clock_s, prefix.stretch
    displacement, log_quadrature, path = prefix.displacement_m, prefix.log_strain_quadrature, prefix.log_path
    theta, theta_start, kappa, kappa0 = (np.array(a) for a in (prefix._theta, prefix._theta0, prefix._kappa,
                                                               prefix._kappa0))
    yield_stages = prefix._yield
    current = {key: np.array(value) if isinstance(value, np.ndarray) else value for key, value in prefix._stage.items()}
    worst_energy, worst_step = prefix.max_step_energy_relative, prefix.max_temperature_step_k
    fc, fp = run.fractions
    drive_work, drag_work = acc["drive_work_j_m"], acc["drag_work_j_m"]
    column_terms = acc["creep_work_j_m"]+acc["plastic_work_j_m"]
    ideal = fc*acc["creep_work_j_m"]+fp*acc["plastic_work_j_m"]
    exchange = acc["radiogenic_j_m"]-acc["reference_outflow_j_m"]
    surface = acc["reference_surface_loss_j_m"]+acc["departure_surface_loss_j_m"]
    basal = acc["reference_basal_gain_j_m"]+acc["departure_basal_gain_j_m"]
    departure = acc["heat_j_m"]+exchange-acc["departure_surface_loss_j_m"]+acc["departure_basal_gain_j_m"]
    absolute = acc["heat_j_m"]+acc["radiogenic_j_m"]-surface+basal
    acc.update(
        surface_loss_j_m=surface, basal_gain_j_m=basal,
        motion_work_relative=ratio(drive_work-drag_work-column_terms, drive_work),
        drive_displacement_relative=ratio(drive_work-drive.force_n_m*displacement, drive_work),
        partition_relative=ratio(column_terms-acc["column_work_j_m"], acc["column_work_j_m"]),
        column_energy_relative=ratio(acc["column_work_j_m"]-acc["heat_j_m"]-acc["stored_j_m"], acc["column_work_j_m"]),
        work_to_heat_relative=ratio(acc["heat_j_m"]-ideal, ideal),
        drag_excluded_relative=ratio(acc["heat_j_m"]+acc["stored_j_m"]-(drive_work-drag_work), drive_work),
        energy_relative=ratio(acc["thermal_change_j_m"]-departure, abs(acc["heat_j_m"])+abs(exchange)
                              + abs(acc["departure_surface_loss_j_m"])+abs(acc["departure_basal_gain_j_m"])),
        absolute_energy_relative=ratio(acc["thermal_change_j_m"]-absolute, abs(acc["heat_j_m"])
                                       + abs(acc["radiogenic_j_m"])+abs(surface)+abs(basal)))
    width, thickness = w0*lam, base.thickness_m/lam
    volume0 = w0*base.thickness_m
    mass0 = w0*math.fsum(base.density*base.weight) if base.closure == weakening.LITHOSTATIC else None
    capacity0 = w0*math.fsum(capacity)
    conservation = dict(
        volume_relative=ratio(width*thickness-volume0, volume0),
        mass_relative=None if mass0 is None else ratio(width*math.fsum(base.density*(base.weight/lam))-mass0, mass0),
        capacity_relative=ratio(width*math.fsum(capacity/lam)-capacity0, capacity0))
    switching = (yield_stages > 0) & (yield_stages < stats["stages"])
    return dict(status=status, reason=reason, accepted_steps=accepted, elapsed_s=accepted*dt, time_step_s=dt,
                clock_s=tau, stretch=lam, log_strain=math.log(lam), log_strain_quadrature=log_quadrature,
                log_path=path, width_m=width, thickness_m=thickness, displacement_m=displacement, theta=theta,
                theta0=theta_start, kappa=kappa, kappa0=kappa0,
                mean_history_gain=math.fsum(base.weight*(kappa-kappa0))/math.fsum(base.weight),
                velocity_start_m_s=prefix.velocity_start_m_s, velocity_end_m_s=current["velocity_m_s"],
                column_force_start_n_m=prefix.column_force_start_n_m, column_force_end_n_m=current["force"],
                accounts=acc, conservation=conservation,
                reference=dict(surface_outflow_w_m2=q_top, basal_inflow_w_m2=q_base, radiogenic_w_m2=produced,
                               balance_relative=balance,
                               note="per reference area at lam = 1; whole-strip flows are w0 lam^2 times these"),
                max_step_energy_relative=worst_energy, max_temperature_step_k=worst_step,
                yield_switching_points=int(np.count_nonzero(switching)), yielded=yield_stages > 0, final=current,
                **stats)


def evolve(base, thermal, law, kappa0, drive, *, duration_s, steps, window, temperature_step_k, fractions, policy,
           modes=None, conduction=True, geometry_feedback=True, theta0=None, warm_start=True, rebuild=None,
           inputs=None, deadline=None):
    """Constant-drive evolution of stretch lam, temperature departure theta and raw history kappa at material points.

    Every run starts at the reference geometry lam = 1, where ``drive.width_m`` is w0, and advances all ``steps``
    steps of dt = duration_s/steps in one piece: prepare_run, begin, advance and finish, the one continuable core.
    Stretch-window, temperature-window, temperature-step, constitutive and deadline refusals return the accepted
    prefix unchanged. ``geometry_feedback=False`` is a comparator only: the mechanics stays at the reference geometry
    while kinematics and conduction follow lam.
    """
    run = prepare_run(base, thermal, law, drive, duration_s=duration_s, steps=steps, window=window,
                      temperature_step_k=temperature_step_k, fractions=fractions, policy=policy, modes=modes,
                      conduction=conduction, geometry_feedback=geometry_feedback, warm_start=warm_start,
                      rebuild=rebuild, inputs=inputs)
    return finish(run, *advance(run, begin(run, kappa0, theta0, deadline=deadline), steps, deadline=deadline))
