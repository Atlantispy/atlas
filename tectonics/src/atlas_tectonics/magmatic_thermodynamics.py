"""W08 prescribed isobaric enthalpy closure; WORKING NON-CANON.

For a congruent common-Tm mixture, H=Cp*(T-Tref)+L*f, where Cp=sum(Ck*cpk)
and L=sum(Ck*Lk). These are extensive quantities. There is no melt-production
rate, extraction law, pressure work or chemical partitioning in this module.

The sensible/latent separation follows the supplied W08 C06 contract. ASPECT's
latent_heat_melt source books latent heat with phase reaction, not advection;
Keller & Suckale (2019), doi:10.1093/gji/ggz287, eq.39c and Appendix B, keep
latent reaction heating distinct from transport and other energy contributions.
No upstream implementation is copied and their dynamic closures are not adopted.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from atlas_tectonics._validation import TectonicsError, input_shape, read_array, scalar, text
from atlas_tectonics.resources import WorkBudget, select_budget

_MAX_NODES = 64
_MAX_COMPONENTS = 64
_MAX_WORK_BYTES = 128 * 1024 * 1024


def _budget(parent):
    """Every operation has a 128 MiB child even when its parent allows more."""
    return WorkBudget(_MAX_WORK_BYTES, parent=select_budget(parent))


def _identity(component_ids, cp, latent, tm, tref, source_id, provenance):
    """Canonical exact binary64 hex strings preserve order and signed zero."""
    record = dict(method="atlas.magmatic-thermodynamics.v1",
        component_ids=component_ids, cp_j_kg_k=[float(x).hex() for x in cp],
        latent_heat_j_kg=[float(x).hex() for x in latent],
        melting_temperature_k=tm.hex(), reference_temperature_k=tref.hex(),
        source_id=source_id, provenance=provenance)
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")).hexdigest()


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError("magmatic thermodynamics cancelled; no result published")


@dataclass(frozen=True, slots=True, init=False)
class MagmaticThermodynamics:
    """Supplied additive constant properties and one common melting temperature.

    Each component uses the same reference temperature and congruent liquid
    fraction. This is not a multicomponent solidus/liquidus or partition model.
    Descriptors returned by array properties are independent and bytes-backed.
    """
    component_ids: tuple[str, ...]
    melting_temperature_k: float
    reference_temperature_k: float
    source_id: str
    provenance: str
    thermodynamics_id: str
    _cp: bytes
    _latent: bytes

    def __init__(self, component_ids, cp_j_kg_k, latent_heat_j_kg, *,
                 melting_temperature_k, reference_temperature_k, source_id,
                 provenance, budget=None, cancel=None):
        _cancel(cancel)
        if type(component_ids) is not tuple or not 0 < len(component_ids) <= _MAX_COMPONENTS:
            raise TectonicsError("component_ids must be a nonempty tuple of at most 64 components")
        for value in component_ids:
            text(value, "component_id")
        if len(set(component_ids)) != len(component_ids):
            raise TectonicsError("component IDs must be unique")
        shape = (len(component_ids),)
        if input_shape(cp_j_kg_k) != shape or input_shape(latent_heat_j_kg) != shape:
            raise TectonicsError("one cp and latent heat required per component")
        tm = scalar(melting_temperature_k, "melting_temperature_k", positive=True)
        tref = scalar(reference_temperature_k, "reference_temperature_k", nonnegative=True)
        text(source_id, "source_id"); text(provenance, "provenance")
        # Capture/identity work is charged here; retained bytes become caller-owned.
        with _budget(budget).reserve(4096 + 512 * len(component_ids),
                                    category="magma-thermodynamics"):
            cp = read_array(cp_j_kg_k, "cp_j_kg_k", ndim=1)
            latent = read_array(latent_heat_j_kg, "latent_heat_j_kg", ndim=1,
                                nonnegative=True)
            if cp.shape != shape or latent.shape != shape or np.any(cp <= 0):
                raise TectonicsError("positive cp and unchanged component shapes required")
            _cancel(cancel)
            for name, value in dict(component_ids=component_ids,
                    melting_temperature_k=tm, reference_temperature_k=tref,
                    source_id=source_id, provenance=provenance,
                    thermodynamics_id=_identity(component_ids, cp, latent, tm, tref,
                                                 source_id, provenance),
                    _cp=cp.tobytes(), _latent=latent.tobytes()).items():
                object.__setattr__(self, name, value)

    @property
    def cp_j_kg_k(self):
        return np.frombuffer(self._cp, dtype=np.float64)

    @property
    def latent_heat_j_kg(self):
        return np.frombuffer(self._latent, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class MagmaticThermalState:
    """Immutable extensive state; None means no defined intensive quantity.

    Empty nodes require exactly zero enthalpy and have T=f=None. A node with
    zero total latent heat has a defined T but f=None and phase='single_phase':
    enthalpy supplies no phase information for a zero-cost transition.
    """
    component_ids: tuple[str, ...]
    thermodynamics_id: str
    temperature_k: tuple[float | None, ...]
    liquid_fraction: tuple[float | None, ...]
    phase: tuple[str, ...]
    _component_mass: bytes
    _enthalpy: bytes
    _mass: bytes

    @property
    def enthalpy_source_id(self):
        """Exact closure identity, not the caller's potentially reused source label."""
        return self.thermodynamics_id

    @property
    def component_mass_kg(self):
        return np.frombuffer(self._component_mass, dtype=np.float64).reshape(
            len(self.phase), len(self.component_ids))

    @property
    def enthalpy_j(self):
        return np.frombuffer(self._enthalpy, dtype=np.float64)

    @property
    def mass_kg(self):
        return np.frombuffer(self._mass, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class MagmaticHeatUpdate:
    state: MagmaticThermalState
    _heat: bytes

    @property
    def applied_heat_j(self):
        """Positive into material, negative heat released to surroundings."""
        return np.frombuffer(self._heat, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class MagmaticMeltConversion:
    remaining: MagmaticThermalState
    melted: MagmaticThermalState
    heat_used_j: float
    heat_remaining_j: float


def _shape(component_mass_kg, enthalpy_j, thermodynamics):
    if type(thermodynamics) is not MagmaticThermodynamics:
        raise TectonicsError("explicit MagmaticThermodynamics required")
    shape = input_shape(component_mass_kg, "component_mass_kg")
    if (len(shape) != 2 or not 0 < shape[0] <= _MAX_NODES
            or shape[1] != len(thermodynamics.component_ids)
            or input_shape(enthalpy_j, "enthalpy_j") != (shape[0],)):
        raise TectonicsError("component masses must be N by K and enthalpy N, with 1 <= N <= 64")
    return shape


def thermodynamics_work_bytes(nodes, components):
    """Conservative accounted work including output; not an RSS guarantee.

    Caller-held buffers, previously returned states and interpreter/native
    baselines are outside this operation reservation, as in the existing kernels.
    """
    if type(nodes) is not int or type(components) is not int or min(nodes, components) <= 0:
        raise TectonicsError("positive integer node/component counts required")
    if nodes > _MAX_NODES or components > _MAX_COMPONENTS:
        raise TectonicsError("thermodynamic closure supports at most 64 nodes and 64 components")
    return 4096 + 64 * nodes * components + 320 * nodes + 96 * components


def _sum(values, name):
    try:
        result = math.fsum(values)
    except (OverflowError, ValueError) as exc:
        raise TectonicsError(name + " outside finite binary64 range") from exc
    if not math.isfinite(result):
        raise TectonicsError(name + " outside finite binary64 range")
    return result


def _product(a, b, name):
    result = float(a) * float(b)
    if not math.isfinite(result) or (a != 0 and b != 0 and result == 0):
        raise TectonicsError(name + " outside binary64 range")
    return result


def _totals(row, thermodynamics):
    mass = _sum((float(x) for x in row), "total mass")
    cp = _sum((_product(c, p, "extensive heat capacity")
               for c, p in zip(row, thermodynamics.cp_j_kg_k)), "heat capacity")
    latent = _sum((_product(c, p, "extensive latent heat")
                   for c, p in zip(row, thermodynamics.latent_heat_j_kg)), "latent heat")
    return mass, cp, latent


def _invert(component_mass, enthalpy, thermodynamics, cancel):
    p = thermodynamics
    temperatures, fractions, phases, masses = [], [], [], []
    for row, energy in zip(component_mass, enthalpy):
        _cancel(cancel)
        mass, cp, latent = _totals(row, p)
        masses.append(mass)
        if mass == 0:
            if energy != 0:
                raise TectonicsError("empty node must have exactly zero enthalpy")
            temperatures.append(None); fractions.append(None); phases.append("empty")
            continue
        if cp <= 0:
            raise TectonicsError("nonempty node has unrepresentable heat capacity")
        if latent == 0:
            temperature = p.reference_temperature_k + float(energy) / cp
            fraction, phase = None, "single_phase"
        else:
            solidus = _product(cp, p.melting_temperature_k - p.reference_temperature_k,
                                "solidus enthalpy")
            liquidus = _sum((solidus, latent), "liquidus enthalpy")
            if liquidus <= solidus:
                raise TectonicsError("latent plateau cannot be resolved in binary64")
            if energy <= solidus:
                temperature = p.melting_temperature_k + (float(energy) - solidus) / cp
                fraction, phase = 0.0, "solid"
            elif energy >= liquidus:
                temperature = p.melting_temperature_k + (float(energy) - liquidus) / cp
                fraction, phase = 1.0, "liquid"
            else:
                temperature = p.melting_temperature_k
                fraction, phase = (float(energy) - solidus) / latent, "two_phase"
        if not math.isfinite(temperature) or temperature <= 0:
            raise TectonicsError("enthalpy implies an invalid absolute temperature")
        temperatures.append(temperature); fractions.append(fraction); phases.append(phase)
    _cancel(cancel)
    return MagmaticThermalState(p.component_ids, p.thermodynamics_id, tuple(temperatures),
        tuple(fractions), tuple(phases), component_mass.tobytes(), enthalpy.tobytes(),
        np.asarray(masses, dtype=np.float64).tobytes())


def invert_enthalpy(component_mass_kg, enthalpy_j, thermodynamics, *, budget=None,
                    cancel=None):
    """Invert the supplied common-Tm phase rule exactly, without iteration."""
    _cancel(cancel)
    shape = _shape(component_mass_kg, enthalpy_j, thermodynamics)
    with _budget(budget).reserve(thermodynamics_work_bytes(*shape),
                                category="magma-enthalpy"):
        mass = read_array(component_mass_kg, "component_mass_kg", ndim=2, nonnegative=True)
        energy = read_array(enthalpy_j, "enthalpy_j", ndim=1)
        if mass.shape != shape or energy.shape != (shape[0],):
            raise TectonicsError("input shape changed during capture")
        return _invert(mass, energy, thermodynamics, cancel)


def reheat(component_mass_kg, enthalpy_j, heat_j, thermodynamics, *, budget=None,
           cancel=None):
    """Apply explicitly booked signed external heat to a fixed finite inventory.

    This may melt or crystallise according to the same enthalpy rule. It never
    creates/extracts material or rebooks latent heat during bulk transfer.
    """
    _cancel(cancel)
    shape = _shape(component_mass_kg, enthalpy_j, thermodynamics)
    if input_shape(heat_j, "heat_j") != (shape[0],):
        raise TectonicsError("one heat increment required per node")
    with _budget(budget).reserve(2 * thermodynamics_work_bytes(*shape),
                                category="magma-reheat"):
        mass = read_array(component_mass_kg, "component_mass_kg", ndim=2, nonnegative=True)
        energy = read_array(enthalpy_j, "enthalpy_j", ndim=1)
        heat = read_array(heat_j, "heat_j", ndim=1)
        if mass.shape != shape or energy.shape != (shape[0],) or heat.shape != energy.shape:
            raise TectonicsError("input shape changed during capture")
        _invert(mass, energy, thermodynamics, cancel)
        with np.errstate(over="ignore", invalid="ignore"):
            final = energy + heat
        if not np.isfinite(final).all():
            raise TectonicsError("heated enthalpy outside finite binary64 range")
        state = _invert(mass, final, thermodynamics, cancel)
        return MagmaticHeatUpdate(state, heat.tobytes())


def melt_source_fraction(component_mass_kg, enthalpy_j, fraction, external_heat_j,
                         thermodynamics, *, liquid_temperature_k, budget=None,
                         cancel=None):
    """Heat and convert a prescribed congruent parcel from one finite solid node.

    Inputs retain N=1 shape. The unselected solid keeps its existing specific
    enthalpy. The parcel becomes fully liquid at supplied T>=Tm. All sensible and
    latent costs are paid once by external heat; unused supplied heat is returned.
    This is a prescribed isolated-parcel heating operation, not phase extraction
    from an equilibrated mixed node. Empty, already-molten, mixed-phase and
    zero-latent/phase-ambiguous sources are refused. Use ordinary bulk transport
    for already-liquid material; calling this again on the liquid is an error.
    """
    _cancel(cancel)
    shape = _shape(component_mass_kg, enthalpy_j, thermodynamics)
    if shape[0] != 1:
        raise TectonicsError("conversion requires exactly one source node")
    fraction = scalar(fraction, "fraction", positive=True)
    if fraction > 1:
        raise TectonicsError("conversion fraction must not exceed one")
    heat = scalar(external_heat_j, "external_heat_j", nonnegative=True)
    target_t = scalar(liquid_temperature_k, "liquid_temperature_k", positive=True)
    if target_t < thermodynamics.melting_temperature_k:
        raise TectonicsError("liquid target temperature must be at least Tm")
    with _budget(budget).reserve(4 * thermodynamics_work_bytes(*shape),
                                category="magma-phase-conversion"):
        mass = read_array(component_mass_kg, "component_mass_kg", ndim=2, nonnegative=True)
        energy = read_array(enthalpy_j, "enthalpy_j", ndim=1)
        if mass.shape != shape or energy.shape != (1,):
            raise TectonicsError("input shape changed during capture")
        source = _invert(mass, energy, thermodynamics, cancel)
        if source.phase != ("solid",):
            raise TectonicsError("phase conversion requires an unambiguously solid source")
        parcel = mass * fraction
        if np.any((mass > 0) & (parcel == 0)):
            raise TectonicsError("converted component mass underflow")
        initial_e = _product(float(energy[0]), fraction, "parcel initial enthalpy")
        _, cp, latent = _totals(parcel[0], thermodynamics)
        final_e = _sum((_product(cp, target_t - thermodynamics.reference_temperature_k,
                                "parcel sensible enthalpy"), latent), "parcel liquid enthalpy")
        cost = _sum((final_e, -initial_e), "conversion heat")
        if cost <= 0:
            raise TectonicsError("positive melting heat cost must be representable")
        if heat < cost:
            raise TectonicsError("external heat does not pay sensible and latent conversion cost")
        remainder = mass - parcel
        remaining_e = float(energy[0]) - initial_e
        if fraction == 1:
            remainder = np.zeros_like(mass)
            remaining_e = 0.0
        melted = _invert(parcel, np.array([final_e]), thermodynamics, cancel)
        if melted.phase != ("liquid",):
            raise TectonicsError("liquid target is not resolved by supplied enthalpy")
        remaining = _invert(remainder, np.array([remaining_e]), thermodynamics, cancel)
        _cancel(cancel)
        return MagmaticMeltConversion(remaining, melted, cost, heat - cost)
