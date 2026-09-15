"""Persistent stratigraphy under explicitly prescribed erosion and deposition.

This is a bounded, detachment-limited column operator, NOT a hydrodynamic,
sediment-transport, SPACE, or complete R7 landscape solver. Hydraulic forcing is
held fixed within a call. Exact layer-contact times prevent an exposed material's
erodibility being applied through a different buried material. Timed deposition
pulses are caller-supplied material inputs, not predictions made by this module.
See LANDSCAPE_DESIGN.md for equations, assumptions and acceptance boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
import types
from typing import Mapping
import uuid


FOUNDATION = Path(__file__).resolve().parents[1] / "scientific_foundation_r1"
FOUNDATION_PINS = {
    "materials.py": "ea5a155fe056bc9b88a1d62882877e35af8d7a6585fbbcd99fd5f94f07a1d966",
    "erosion.py": "e4d7b6307dd21bbc9716b966a77a2ec8e2bf2cf96609a1ea25d631e48056c204",
}
MAX_COLUMNS = 1024
MAX_TOTAL_LAYERS = 16384
MAX_DEPOSITION_EVENTS = 4096
MAX_EVENT_HISTORY = 16384
MAX_EXACT_BITS = 8192
STATUSES = {"CANON", "WORKING NON-CANON", "SYNTHETIC TEST"}
PHASES = {"bedrock", "immobile_regolith", "mobile_sediment", "organic"}


def _read_pinned(path, expected):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("foundation source drift: " + str(path))
    return raw


def _load_pinned(path, expected):
    raw = _read_pinned(path, expected)
    name = "_landscape_foundation_" + uuid.uuid4().hex
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    try:
        # Compile precisely the bytes checked above; no stale bytecode/import
        # alias and no assert-stripping dependence on the caller's -OO mode.
        exec(compile(raw, str(path), "exec", dont_inherit=True, optimize=0), module.__dict__)
    finally:
        del sys.modules[name]
    return module


_materials = _load_pinned(FOUNDATION / "materials.py", FOUNDATION_PINS["materials.py"])
_erosion = _load_pinned(FOUNDATION / "erosion.py", FOUNDATION_PINS["erosion.py"])
Column = _materials.Column
Layer = _materials.Layer
PhysicalProperty = _materials.PhysicalProperty


def _verify_sources():
    for name, digest in FOUNDATION_PINS.items():
        _read_pinned(FOUNDATION / name, digest)


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(name + " must be nonempty bounded text")
    return value


def _quantity(value, name, *, positive=False):
    result = _materials.exact(value, name, positive=positive)
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > MAX_EXACT_BITS:
        raise ValueError(name + " exceeds bounded exact-arithmetic resources")
    return result


def _property(value, name, unit, *, positive=False, binary64=False):
    if type(value) is not PhysicalProperty:
        raise ValueError(name + " requires the pinned physical-property contract")
    _text(value.evidence, name + " evidence")
    result = _quantity(value.require(name, unit), name, positive=positive)
    if binary64:
        # Foundation law's explicit binary64 input contract is retained. Do not
        # silently round a Fraction, score, bool or arbitrary numeric object.
        _erosion.real(value.value, name, positive=positive)
    return result


def _pair(value):
    return [value.numerator, value.denominator]


def _unpair(value, name):
    if type(value) is not list or len(value) != 2 or any(type(x) is not int for x in value) or value[1] <= 0:
        raise ValueError(name + " requires an exact numerator/positive denominator")
    return _quantity(Fraction(*value), name)


def _layer_record(layer):
    return {**vars(layer), **{key: _pair(getattr(layer, key))
                              for key in ("mass_kg", "grain_density_kg_m3", "porosity")}}


def _check_layer(layer):
    if type(layer) is not Layer:
        raise ValueError("only material-bearing pinned Layer instances are supported")
    _text(layer.material_id, "material identity")
    _text(layer.evidence, "material evidence")
    for key in ("mass_kg", "grain_density_kg_m3", "porosity"):
        _quantity(getattr(layer, key), key, positive=key != "porosity")
    _quantity(layer.bulk_volume_m3, "layer bulk volume", positive=True)


@dataclass(frozen=True)
class ErosionLaw:
    """K [1/year] calibrated at this law's explicit R_ref [m/year]."""
    material_id: str
    phase: str
    k_per_year: PhysicalProperty
    reference_runoff_m_year: PhysicalProperty

    def __post_init__(self):
        _text(self.material_id, "material identity")
        if self.phase not in PHASES:
            raise ValueError("unsupported material phase")
        _property(self.k_per_year, "erosion_coefficient_at_reference_runoff", "1/year")
        _property(self.reference_runoff_m_year, "reference_runoff", "m/year", positive=True, binary64=True)


@dataclass(frozen=True)
class Forcing:
    """Externally calculated hydraulic quantities; constant during this call."""
    discharge_m3_year: PhysicalProperty
    slope: PhysicalProperty

    def __post_init__(self):
        _property(self.discharge_m3_year, "discharge", "m3/year", binary64=True)
        _property(self.slope, "hydraulic_slope", "1", binary64=True)


@dataclass(frozen=True)
class Deposition:
    """An externally supplied sediment pulse placed before erosion at its time.

    Equal-time pulses must have explicit distinct sequence numbers per column:
    increasing sequence is bottom-to-top. The order has physical consequences.
    """
    event_id: str
    column_id: str
    at_year: Fraction
    sequence: int
    layer: Layer
    source_status: str

    def __post_init__(self):
        _text(self.event_id, "deposition identity")
        _text(self.column_id, "column identity")
        object.__setattr__(self, "at_year", _quantity(self.at_year, "deposition time"))
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("explicit nonnegative integer deposition sequence required")
        _check_layer(self.layer)
        if self.layer.phase != "mobile_sediment":
            raise ValueError("deposition requires mobile sediment; no implicit lithification or phase conversion")
        if self.source_status not in STATUSES:
            raise ValueError("deposition source status is unresolved")


@dataclass(frozen=True)
class LandscapeState:
    """Persistent physical stocks, model clock and deposition replay protection."""
    columns: tuple[tuple[str, Column], ...]
    elapsed_years: Fraction = Fraction()
    applied_deposition_ids: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "elapsed_years", _quantity(self.elapsed_years, "model time"))
        if type(self.columns) is not tuple or not 0 < len(self.columns) <= MAX_COLUMNS:
            raise ValueError("bounded nonempty immutable column inventory required")
        identities = set()
        total_layers = 0
        for entry in self.columns:
            if type(entry) is not tuple or len(entry) != 2:
                raise ValueError("column inventory requires (identity, Column) tuples")
            key, column = entry
            _text(key, "column identity")
            if key in identities or type(column) is not Column:
                raise ValueError("duplicate column or incompatible material-column type")
            identities.add(key)
            _quantity(column.area_m2, "column area", positive=True)
            _quantity(abs(column.basal_elevation_m), "absolute basal elevation")
            for layer in column.layers:
                _check_layer(layer)
            _quantity(abs(column.surface_m), "absolute column surface")
            total_layers += len(column.layers)
        if total_layers > MAX_TOTAL_LAYERS:
            raise ValueError("column inventory exceeds bounded layer resources")
        if type(self.applied_deposition_ids) is not tuple or len(self.applied_deposition_ids) > MAX_EVENT_HISTORY:
            raise ValueError("bounded immutable deposition history required")
        if any(type(key) is not str or not key.strip() or len(key) > 4096 for key in self.applied_deposition_ids):
            raise ValueError("invalid deposition history identity")
        if len(set(self.applied_deposition_ids)) != len(self.applied_deposition_ids):
            raise ValueError("deposition history contains a replay")

    @property
    def column_map(self):
        return dict(self.columns)

    def as_dict(self):
        return {"schema": "diadem.layered-landscape-state.r1", "elapsed_years": _pair(self.elapsed_years),
                "columns": [{"column_id": key, "column": column.as_dict()} for key, column in self.columns],
                "applied_deposition_ids": list(self.applied_deposition_ids),
                "foundation_sources": dict(FOUNDATION_PINS)}

    @classmethod
    def from_dict(cls, data):
        _verify_sources()
        expected = {"schema", "elapsed_years", "columns", "applied_deposition_ids", "foundation_sources"}
        if type(data) is not dict or set(data) != expected or data["schema"] != "diadem.layered-landscape-state.r1":
            raise ValueError("invalid layered landscape state schema")
        if data["foundation_sources"] != FOUNDATION_PINS:
            raise ValueError("state material semantics/source pins do not match")
        rows = data["columns"]
        if type(rows) is not list or not 0 < len(rows) <= MAX_COLUMNS:
            raise ValueError("invalid state column inventory")
        columns = []
        for row in rows:
            if type(row) is not dict or set(row) != {"column_id", "column"}:
                raise ValueError("invalid state column row")
            if type(row["column"]) is not dict or type(row["column"].get("layers")) is not list or len(row["column"]["layers"]) > 4096:
                raise ValueError("invalid bounded state layer array")
            columns.append((row["column_id"], Column.from_dict(row["column"])))
        history = data["applied_deposition_ids"]
        if type(history) is not list:
            raise ValueError("invalid deposition history")
        return cls(tuple(columns), _unpair(data["elapsed_years"], "model time"), tuple(history))

    @classmethod
    def from_json(cls, text):
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate JSON key: " + key)
                result[key] = value
            return result
        def invalid_constant(value):
            raise ValueError("nonfinite JSON value: " + value)
        if type(text) is not str or len(text) > 32 * 1024 * 1024:
            raise ValueError("bounded state JSON string required")
        return cls.from_dict(json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant))


@dataclass(frozen=True)
class ErodedParcel:
    """Removed stock, retaining its original phase, density and evidence.

    start/end are erosion intervals, not arrival times at any other location.
    No deposition timing/porosity is inferred from these records.
    """
    column_id: str
    start_year: Fraction
    end_year: Fraction
    source_layer: Layer

    def __post_init__(self):
        _text(self.column_id, "eroded source column identity")
        object.__setattr__(self, "start_year", _quantity(self.start_year, "erosion interval start"))
        object.__setattr__(self, "end_year", _quantity(self.end_year, "erosion interval end"))
        if self.end_year <= self.start_year:
            raise ValueError("an eroded parcel requires a strictly positive source time interval")
        _check_layer(self.source_layer)


@dataclass(frozen=True)
class StepResult:
    state: LandscapeState
    eroded_parcels: tuple[ErodedParcel, ...]
    receipt: dict


def redeposit(parcel, *, event_id, column_id, at_year, sequence, sediment_porosity, source_status):
    """Explicit mass-preserving mechanical fragmentation/redeposition interface.

    The caller owns destination, arrival time and porosity. This does not model
    travel, sorting, dissolution, abrasion, transport capacity or compaction.
    """
    if type(parcel) is not ErodedParcel:
        raise ValueError("a material-bearing erosion parcel is required")
    _check_layer(parcel.source_layer)
    porosity = _property(sediment_porosity, "deposited_sediment_porosity", "1")
    if porosity >= 1:
        raise ValueError("deposited sediment porosity must be below one")
    at = _quantity(at_year, "arrival time")
    if at < parcel.end_year:
        raise ValueError("a whole parcel cannot arrive before its erosion interval has finished")
    layer = replace(parcel.source_layer, porosity=porosity, phase="mobile_sediment",
                    evidence=parcel.source_layer.evidence + "; prescribed redeposition: " + sediment_porosity.evidence)
    return Deposition(event_id, column_id, at, sequence, layer, source_status)


def _inventory(layers):
    result = {}
    for layer in layers:
        row = result.setdefault(layer.material_id, [Fraction(), Fraction()])
        row[0] += layer.mass_kg
        row[1] += layer.mass_kg / layer.grain_density_kg_m3
    return result


def _balance(initial, deposited, final, eroded):
    inventories = [_inventory(layers) for layers in (initial, deposited, final, eroded)]
    rows = []
    for identity in sorted(set().union(*(set(inv) for inv in inventories))):
        values = [inv.get(identity, (Fraction(), Fraction())) for inv in inventories]
        residuals = [values[0][j] + values[1][j] - values[2][j] - values[3][j] for j in (0, 1)]
        if any(residuals):
            raise ArithmeticError("material identity/mass/solid volume failed to close")
        row = {"material_id": identity}
        for index, quantity in enumerate(("mass_kg", "solid_volume_m3")):
            for label, value in zip(("initial", "deposited", "final", "eroded"), values):
                row[label + "_" + quantity] = _pair(_quantity(value[index], quantity))
            row["residual_" + quantity] = _pair(residuals[index])
        rows.append(row)
    return rows


def _evolve_interval(column_id, column, begin, end, rates):
    clock = begin
    parcels = []
    active = zero_rate = exhausted = Fraction()
    while clock < end:
        if not column.layers:
            exhausted += end - clock
            break
        layer = column.exposed
        erosion_rate = rates[(layer.material_id, layer.phase)]
        if not erosion_rate:
            zero_rate += end - clock
            break
        mass_rate = _quantity(erosion_rate * column.area_m2 * layer.grain_density_kg_m3 * (1-layer.porosity),
                              "erosion mass rate", positive=True)
        contact_time = _quantity(layer.mass_kg / mass_rate, "layer-contact time", positive=True)
        used_time = min(end-clock, contact_time)
        removed_mass = _quantity(mass_rate * used_time, "removed mass", positive=True)
        after, removal = column.strip_mass(removed_mass)
        if removal["unmet_mass_kg"] or removal["mass_residual_kg"] or len(removal["removed_layers"]) != 1:
            raise ArithmeticError("layer contact removal contract failed")
        next_clock = _quantity(clock + used_time, "erosion event time")
        parcels.append(ErodedParcel(column_id, clock, next_clock, removal["removed_layers"][0]))
        active += used_time
        column = after
        clock = next_clock
    if active + zero_rate + exhausted != end-begin:
        raise ArithmeticError("erosion interval time budget failed to close")
    return column, parcels, (active, zero_rate, exhausted)


def advance(state, forcings: Mapping[str, Forcing], laws, duration_years, depositions=()):
    """Advance finite columns through every erosion contact and supplied pulse.

    Events lie in the closed interval [old_time, new_time]; the persistent event
    ledger rejects reapplication at a continuation boundary. No partial state is
    returned on invalid inputs or resource refusal. Outputs never acquire CANON.
    """
    _verify_sources()
    if type(state) is not LandscapeState:
        raise ValueError("persistent LandscapeState required")
    duration = _quantity(duration_years, "duration")
    final_time = _quantity(state.elapsed_years + duration, "final model time")
    columns = state.column_map
    if not isinstance(forcings, Mapping) or set(forcings) != set(columns) or any(type(f) is not Forcing for f in forcings.values()):
        raise ValueError("one explicit hydraulic forcing per column is required")
    if type(laws) not in (tuple, list) or len(laws) > MAX_TOTAL_LAYERS or any(type(law) is not ErosionLaw for law in laws):
        raise ValueError("bounded explicit material law inventory required")
    law_map = {(law.material_id, law.phase): law for law in laws}
    if len(law_map) != len(laws):
        raise ValueError("duplicate material/phase erosion law")
    if type(depositions) not in (tuple, list) or len(depositions) > MAX_DEPOSITION_EVENTS or any(type(e) is not Deposition for e in depositions):
        raise ValueError("bounded explicit deposition event inventory required")
    events = {key: [] for key in columns}
    event_ids = set(state.applied_deposition_ids)
    order_keys = set()
    for event in depositions:
        if event.event_id in event_ids:
            raise ValueError("deposition event replay/duplicate: " + event.event_id)
        if event.column_id not in columns or not state.elapsed_years <= event.at_year <= final_time:
            raise ValueError("deposition destination/time is outside this step")
        order_key = (event.column_id, event.at_year, event.sequence)
        if order_key in order_keys:
            raise ValueError("ambiguous equal-time deposition order")
        order_keys.add(order_key)
        event_ids.add(event.event_id)
        events[event.column_id].append(event)
    if len(event_ids) > MAX_EVENT_HISTORY:
        raise ValueError("deposition history resource budget exhausted; no silent history pruning")
    all_layers = [layer for _, column in state.columns for layer in column.layers] + [event.layer for event in depositions]
    if len(all_layers) > MAX_TOTAL_LAYERS:
        raise ValueError("input and scheduled deposition exceed layer resources")
    densities = {}
    required_keys = set()
    for layer in all_layers:
        key = (layer.material_id, layer.phase)
        required_keys.add(key)
        previous = densities.setdefault(layer.material_id, layer.grain_density_kg_m3)
        if previous != layer.grain_density_kg_m3:
            raise ValueError("one material identity cannot carry conflicting grain densities")
    if not required_keys <= set(law_map):
        raise ValueError("a current, buried or deposited material lacks its explicit erosion law")
    # All required laws/forcing combinations are validated before any evolution.
    rates_by_column = {}
    forcing_receipts = []
    for key, column in state.columns:
        forcing = forcings[key]
        rates = {}
        local_keys = {(layer.material_id, layer.phase) for layer in column.layers}
        local_keys.update((event.layer.material_id, event.layer.phase) for event in events[key])
        for material_key in sorted(local_keys):
            law = law_map[material_key]
            coefficient = _property(law.k_per_year, "erosion_coefficient_at_reference_runoff", "1/year")
            intensity = _erosion.runoff_normalised_intensity(forcing.discharge_m3_year.value,
                                                            forcing.slope.value,
                                                            law.reference_runoff_m_year.value)
            rates[material_key] = _quantity(coefficient * Fraction(intensity), "erosion rate")
        rates_by_column[key] = rates
        forcing_receipts.append({"column_id": key, "discharge": vars(forcing.discharge_m3_year),
                                 "slope": vars(forcing.slope),
                                 "represented_rates_m_year": [{"material_id": m, "phase": p, "rate": _pair(r)}
                                                              for (m, p), r in sorted(rates.items())]})
    output = []
    parcels = []
    column_receipts = []
    for key, source in state.columns:
        column = source
        clock = state.elapsed_years
        local_parcels = []
        times = [Fraction(), Fraction(), Fraction()]
        ordered = sorted(events[key], key=lambda e: (e.at_year, e.sequence))
        for event in (*ordered, None):
            boundary = final_time if event is None else event.at_year
            column, removed, interval_times = _evolve_interval(key, column, clock, boundary, rates_by_column[key])
            local_parcels.extend(removed)
            times = [a+b for a, b in zip(times, interval_times)]
            clock = boundary
            if event is not None:
                column = column.deposit(event.layer)
        statuses = [source.source_status, forcings[key].discharge_m3_year.status, forcings[key].slope.status]
        statuses.extend(event.source_status for event in ordered)
        for material_key in rates_by_column[key]:
            statuses.extend((law_map[material_key].k_per_year.status, law_map[material_key].reference_runoff_m_year.status))
        output_status = "SYNTHETIC TEST" if all(status == "SYNTHETIC TEST" for status in statuses) else "WORKING NON-CANON"
        column = replace(column, source_status=output_status)
        if sum(times, Fraction()) != duration:
            raise ArithmeticError("column time accounting failed")
        output.append((key, column))
        parcels.extend(local_parcels)
        column_receipts.append({"column_id": key, "initial_surface_m": _pair(source.surface_m),
                                "final_surface_m": _pair(column.surface_m),
                                "erosion_active_years": _pair(times[0]), "zero_rate_years": _pair(times[1]),
                                "stock_exhausted_years": _pair(times[2]),
                                "material_balance": _balance(source.layers, [e.layer for e in ordered], column.layers,
                                                             [p.source_layer for p in local_parcels])})
    new_state = LandscapeState(tuple(output), final_time, tuple(sorted(event_ids)))
    receipt = {
        "schema": "diadem.layered-landscape-step.r1",
        "status": "BOUNDED PRESCRIBED-FORCING CONSTRUCTION; NOT EMPIRICALLY ACCEPTED",
        "erosion_law": "E = K_at_reference * sqrt(Q / R_reference) * hydraulic_slope",
        "contact_solver": "exact piecewise-constant rates for represented binary64 intensity",
        "mass_accounting": "EXACT BY MATERIAL; this is not a physical accuracy certificate",
        "hydraulic_coupling": "CALLER PRESCRIBED; constant forcing within each call; no R7 mixed-phase coupling",
        "deposition_model": "externally supplied, explicitly ordered instantaneous sediment pulses",
        "start_year": _pair(state.elapsed_years), "end_year": _pair(final_time),
        "foundation_executed_sources": dict(FOUNDATION_PINS),
        "forcings": forcing_receipts,
        "laws": [{"material_id": law.material_id, "phase": law.phase,
                  "k_per_year": {**vars(law.k_per_year), "value": _pair(Fraction(law.k_per_year.value))},
                  "reference_runoff_m_year": vars(law.reference_runoff_m_year)} for law in laws],
        "depositions": [{"event_id": e.event_id, "column_id": e.column_id, "at_year": _pair(e.at_year),
                         "sequence": e.sequence, "source_status": e.source_status, "layer": _layer_record(e.layer)}
                        for e in sorted(depositions, key=lambda e: (e.at_year, e.column_id, e.sequence))],
        "eroded_parcels": [{"column_id": p.column_id, "start_year": _pair(p.start_year),
                            "end_year": _pair(p.end_year), "source_layer": _layer_record(p.source_layer)} for p in parcels],
        "columns": column_receipts,
        "global_material_balance": _balance([layer for _, c in state.columns for layer in c.layers],
                                             [e.layer for e in depositions],
                                             [layer for _, c in output for layer in c.layers],
                                             [p.source_layer for p in parcels]),
    }
    return StepResult(new_state, tuple(parcels), receipt)


def verification_reference():
    """Deterministic tiny executed reference for the parent acceptance runner.

    All inputs are analytical SYNTHETIC TEST fixtures, never Diadem parameters.
    The contact/deposition sequence is compared with an independent exact oracle
    and a persisted split run before its JSON-safe output is returned.
    """
    def physical(name, value, unit):
        return PhysicalProperty(name, value, unit, "independent layered reference fixture", "SYNTHETIC TEST")
    rock = Layer("reference-rock", Fraction(100), Fraction(10), Fraction(), "bedrock", "finite synthetic rock")
    sand = Layer("reference-sand", Fraction(10), Fraction(10), Fraction(1, 2), "mobile_sediment", "finite synthetic deposit")
    source = LandscapeState((("reference-column", Column(Fraction(1), Fraction(), (rock,), "SYNTHETIC TEST")),))
    laws = tuple(ErosionLaw(identity, phase,
                            physical("erosion_coefficient_at_reference_runoff", rate, "1/year"),
                            physical("reference_runoff", 1, "m/year"))
                 for identity, phase, rate in (("reference-rock", "bedrock", 1), ("reference-sand", "mobile_sediment", 2)))
    forcing = {"reference-column": Forcing(physical("discharge", 4, "m3/year"), physical("hydraulic_slope", .5, "1"))}
    pulse = Deposition("reference-pulse", "reference-column", Fraction(1, 2), 0, sand, "SYNTHETIC TEST")
    whole = advance(source, forcing, laws, 2, (pulse,))
    first = advance(source, forcing, laws, Fraction(1, 2), (pulse,))
    recovered = LandscapeState.from_json(json.dumps(first.state.as_dict(), allow_nan=False))
    continued = advance(recovered, forcing, laws, Fraction(3, 2))
    if whole.state != continued.state or whole.state.column_map["reference-column"].mass_kg != 90:
        raise ArithmeticError("independent contact/restart reference failed")
    expected = [(Fraction(), Fraction(1, 2), "reference-rock", Fraction(5)),
                (Fraction(1, 2), Fraction(3, 2), "reference-sand", Fraction(10)),
                (Fraction(3, 2), Fraction(2), "reference-rock", Fraction(5))]
    observed = [(p.start_year, p.end_year, p.source_layer.material_id, p.source_layer.mass_kg) for p in whole.eroded_parcels]
    if observed != expected:
        raise ArithmeticError("independent layer exposure-time oracle failed")
    replay_rejected = False
    try:
        advance(recovered, forcing, laws, Fraction(3, 2), (pulse,))
    except ValueError as error:
        if "replay" not in str(error):
            raise
        replay_rejected = True
    if not replay_rejected:
        raise ArithmeticError("persisted deposition replay guard failed")
    return {"status": "SYNTHETIC TEST ONLY", "state": whole.state.as_dict(), "receipt": whole.receipt,
            "independent_oracle": {"final_mass_kg": [90, 1], "final_surface_m": [9, 1],
                                   "exported_rock_mass_kg": [10, 1], "exported_sand_mass_kg": [10, 1]},
            "restart_identical": True, "replay_rejected": replay_rejected}
