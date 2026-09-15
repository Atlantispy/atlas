"""Finite heterogeneous column erosion and conservative steady sediment routing.

A trial freezes slopes/receivers and runoff rates. Root's coupled driver owns
adaptive full-versus-two-half refinement, including the accompanying pore water.
This is a small open-drainage, dilute-transport reference, not flood hydraulics,
lake ownership, soil formation, or the full SPACE/R7 equations.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction as F
import hashlib
import math
from typing import Mapping

from .deps import landscape, verify

Layer = landscape.Layer
Column = landscape.Column
LandscapeState = landscape.LandscapeState
PhysicalProperty = landscape.PhysicalProperty
ErosionLaw = landscape.ErosionLaw
MAX_CELLS = 32
MAX_CONNECTORS = 256
MAX_LAYERS = 2048
MAX_BITS = 8192


class TerrainContractError(ValueError):
    """Invalid, unknown or unsupported physical input; do not silently fill."""


class TerrainStepTooLarge(ValueError):
    """Trial geometry exceeds its declared bound; coupled driver may refine."""


class TerrainRegimeError(ValueError):
    """Positive-water closed pit or non-dilute transport needs another model."""


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 1024:
        raise TerrainContractError(name + ": bounded evidence/identity required")
    return value


def _q(value, name, positive=False, signed=False):
    if type(value) not in (int, float, F):
        raise TerrainContractError(name + ": explicit known physical quantity required")
    if type(value) is float and not math.isfinite(value):
        raise TerrainContractError(name + ": nonfinite quantity")
    result = F(value)
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > MAX_BITS:
        raise TerrainContractError(name + ": exact arithmetic envelope exceeded")
    if (not signed and result < 0) or (positive and result <= 0):
        raise TerrainContractError(name + ": physical range violated")
    return result


def _float(value, name):
    try:
        answer = float(value)
    except OverflowError as exc:
        raise TerrainContractError(name + ": binary64 overflow") from exc
    if not math.isfinite(answer) or (value and answer == 0):
        raise TerrainContractError(name + ": not finite/nonzero-representable")
    return answer


def _settling_factor(discharge, settling_area):
    """Represent the constitutive factor, not mass: every later split is exact.

    Unrelated exact denominators otherwise multiply through every wet-deposit
    cycle. Binary64 is the disclosed constitutive precision already used by R1
    erosion. A positive physical branch must not vanish in this representation.
    """
    theoretical = discharge / (discharge + settling_area)
    represented = F(float(theoretical))
    if represented <= 0 or (settling_area > 0 and represented >= 1):
        raise TerrainContractError("settling factor loses a positive transport/deposition branch in binary64")
    return represented, theoretical


def exact_json(value):
    """Lossless JSON-safe form; rationals are strings, never rounded silently."""
    if isinstance(value, F): return str(value)
    if isinstance(value, (tuple, list)): return [exact_json(v) for v in value]
    if isinstance(value, dict): return {k: exact_json(v) for k, v in value.items()}
    return value


@dataclass(frozen=True)
class Connector:
    connector_id: str
    source_id: str
    receiver_id: str | None
    length_m: object
    outlet_elevation_m: object
    evidence: str

    def __post_init__(self):
        for key in ("connector_id", "source_id", "evidence"):
            _text(getattr(self, key), key)
        object.__setattr__(self, "length_m", _q(self.length_m, "connector length", True))
        if self.receiver_id is None:
            object.__setattr__(self, "outlet_elevation_m", _q(self.outlet_elevation_m, "explicit outlet level", signed=True))
        else:
            _text(self.receiver_id, "receiver_id")
            if self.receiver_id == self.source_id or self.outlet_elevation_m is not None:
                raise TerrainContractError("internal connector needs a distinct receiver and no external level")


@dataclass(frozen=True)
class SedimentLaw:
    material_id: str
    settling_m_year: object
    deposited_porosity: object
    deposition_order: int
    evidence: str

    def __post_init__(self):
        _text(self.material_id, "sediment material identity"); _text(self.evidence, "sediment scenario evidence")
        object.__setattr__(self, "settling_m_year", _q(self.settling_m_year, "effective settling velocity"))
        object.__setattr__(self, "deposited_porosity", _q(self.deposited_porosity, "deposited porosity"))
        if self.deposited_porosity >= 1:
            raise TerrainContractError("deposited porosity must be below one")
        if type(self.deposition_order) is not int or self.deposition_order < 0:
            raise TerrainContractError("explicit nonnegative simultaneous-deposition order required")


@dataclass(frozen=True)
class TrialControls:
    max_relief_change_fraction: object
    max_solid_liquid_ratio: object
    evidence: str

    def __post_init__(self):
        _text(self.evidence, "numerical/regime control evidence")
        for key in ("max_relief_change_fraction", "max_solid_liquid_ratio"):
            object.__setattr__(self, key, _q(getattr(self, key), key, True))
        if self.max_relief_change_fraction > F(1, 2) or self.max_solid_liquid_ratio >= 1:
            raise TerrainContractError("relief fraction must be <=1/2; explicit solid/liquid regime bound must be <1")


@dataclass(frozen=True)
class TerrainTrial:
    erosion_state: LandscapeState
    state: LandscapeState
    erosion_events: tuple[dict, ...]
    deposit_events: tuple[dict, ...]
    exports: tuple[dict, ...]
    receipt: dict


def _inventory(columns):
    result = {}
    for column in columns.values():
        for layer in column.layers:
            row = result.setdefault(layer.material_id, [F(0), F(0)])
            row[0] += layer.mass_kg
            row[1] += layer.mass_kg / layer.grain_density_kg_m3
    return result


def _layer_record(layer):
    return {"material_id": layer.material_id, "mass_kg": layer.mass_kg,
            "grain_density_kg_m3": layer.grain_density_kg_m3, "porosity": layer.porosity,
            "phase": layer.phase, "evidence": layer.evidence}


def route_water(state, local_runoff_m3, connectors, *, duration_years):
    """Recompute exact current steepest positive slopes and conserved discharge.

    Connectors are supplied candidate physical adjacencies, not generated roads
    or DEM hydrology. Equal-slope ties use connector_id, an explicit numerical
    tie-break. Sinks with any accumulated water require a separate pond model.
    """
    verify()
    landscape._verify_sources()
    if type(state) is not LandscapeState or not 0 < len(state.columns) <= MAX_CELLS:
        raise TerrainContractError("bounded shared pinned LandscapeState required")
    if sum(len(c.layers) for _, c in state.columns) > MAX_LAYERS:
        raise TerrainContractError("bounded finite-layer inventory exceeded")
    duration = _q(duration_years, "duration in explicitly bound model years", True)
    columns = state.column_map
    if not isinstance(local_runoff_m3, Mapping) or set(local_runoff_m3) != set(columns):
        raise TerrainContractError("one explicit local runoff volume per cell required")
    local = {k: _q(local_runoff_m3[k], "local runoff:" + k) for k in sorted(columns)}
    if type(connectors) not in (tuple, list) or len(connectors) > MAX_CONNECTORS or any(type(c) is not Connector for c in connectors):
        raise TerrainContractError("bounded explicit connector inventory required")
    if len({c.connector_id for c in connectors}) != len(connectors):
        raise TerrainContractError("duplicate connector identity")
    seen_pairs = set(); options = {k: [] for k in columns}
    for c in sorted(connectors, key=lambda c: c.connector_id):
        if c.source_id not in columns or (c.receiver_id is not None and c.receiver_id not in columns):
            raise TerrainContractError("unknown connector endpoint")
        pair = (c.source_id, c.receiver_id, c.outlet_elevation_m)
        if pair in seen_pairs:
            raise TerrainContractError("duplicate candidate physical connector")
        seen_pairs.add(pair)
        receiver_level = c.outlet_elevation_m if c.receiver_id is None else columns[c.receiver_id].surface_m
        drop = columns[c.source_id].surface_m - receiver_level
        if drop > 0:
            options[c.source_id].append((drop / c.length_m, c, drop))
    selected = {}
    for k, rows in options.items():
        if rows:
            selected[k] = sorted(rows, key=lambda r: (-r[0], r[1].connector_id))[0]
    order = sorted(columns, key=lambda k: (-columns[k].surface_m, k))
    through = dict(local); exports = {}; receivers = {}; slope = {}; rows = []
    for k in order:
        choice = selected.get(k)
        if choice is None:
            if through[k]:
                raise TerrainRegimeError("positive-water cell has no downhill open connector: " + k)
            receivers[k] = None; slope[k] = F(0)
            continue
        gradient, c, drop = choice
        receivers[k] = c.receiver_id; slope[k] = gradient
        if c.receiver_id is None:
            exports[c.connector_id] = through[k]
        else:
            through[c.receiver_id] += through[k]
        rows.append({"cell_id": k, "connector_id": c.connector_id, "receiver_id": c.receiver_id,
                     "length_m": c.length_m, "outlet_elevation_m": c.outlet_elevation_m,
                     "initial_drop_m": drop, "slope": gradient, "through_volume_m3": through[k],
                     "discharge_m3_year": through[k] / duration, "evidence": c.evidence})
    if sum(local.values(), F(0)) != sum(exports.values(), F(0)):
        raise ArithmeticError("exact routed water conservation failed")
    verify(); landscape._verify_sources()
    return {"local_runoff_m3": local, "through_volume_m3": through,
            "discharge_m3_year": {k: through[k] / duration for k in columns},
            "slopes": slope, "receivers": receivers, "selected": selected,
            "order": tuple(order), "rows": rows, "external_exports_m3": exports,
            "duration_years": duration}


def terrain_trial(state, local_runoff_m3, connectors, laws, sediment_laws, *,
                  duration_years, controls, evidence_id):
    """One conservative frozen-topology trial, never an adaptive coupled claim.

    Water volumes are independent local surface runoff from the water solver,
    not upstream accumulation supplied twice. Root owns substep rejection and
    full-vs-half refinement, including any pore water displaced/carried by solid
    transfers. No pore-water content or horizon label is assigned here.
    """
    _text(evidence_id, "runoff/process binding evidence")
    if type(controls) is not TrialControls:
        raise TerrainContractError("explicit trial controls required")
    flow = route_water(state, local_runoff_m3, connectors, duration_years=duration_years)
    duration = flow["duration_years"]; before = state.column_map
    if type(sediment_laws) not in (tuple, list) or any(type(s) is not SedimentLaw for s in sediment_laws) or len(sediment_laws) > MAX_LAYERS:
        raise TerrainContractError("bounded explicit material sediment laws required")
    smap = {s.material_id: s for s in sediment_laws}
    if len(smap) != len(sediment_laws) or len({s.deposition_order for s in sediment_laws}) != len(smap):
        raise TerrainContractError("duplicate material or ambiguous simultaneous-deposition order")
    materials = {l.material_id for c in before.values() for l in c.layers}
    if not materials <= set(smap):
        raise TerrainContractError("settling/deposition law missing for current/buried material")
    required_mobile = {(m, "mobile_sediment") for m in materials}
    if type(laws) not in (tuple, list) or any(type(l) is not ErosionLaw for l in laws):
        raise TerrainContractError("shared pinned erosion-law inventory required")
    if not required_mobile <= {(l.material_id, l.phase) for l in laws}:
        raise TerrainContractError("deposited material requires its explicit mobile-sediment erosion law")
    forcing = {k: landscape.Forcing(
        PhysicalProperty("discharge", _float(flow["discharge_m3_year"][k], "discharge"), "m3/year", evidence_id, "WORKING NON-CANON"),
        PhysicalProperty("hydraulic_slope", _float(flow["slopes"][k], "slope"), "1", evidence_id, "WORKING NON-CANON")) for k in before}
    eroded = landscape.advance(state, forcing, laws, duration)
    erosion_columns = eroded.state.column_map
    origins = {}; packets = {k: {} for k in before}; events = []
    source_indices = {k: len(c.layers) - 1 for k, c in before.items()}
    remaining = {k: [l.mass_kg for l in c.layers] for k, c in before.items()}
    for parcel in eroded.eroded_parcels:
        k = parcel.column_id; index = source_indices[k]
        while index >= 0 and remaining[k][index] == 0:
            index -= 1
        if index < 0:
            raise ArithmeticError("erosion parcel has no finite source layer")
        source_indices[k] = index; original = before[k].layers[index]
        identity = (k, index)
        if identity in origins:
            raise ArithmeticError("unsegmented R1 trial repeated one source layer unexpectedly")
        if (original.material_id, original.phase, original.grain_density_kg_m3, original.porosity, original.evidence) != (
                parcel.source_layer.material_id, parcel.source_layer.phase, parcel.source_layer.grain_density_kg_m3,
                parcel.source_layer.porosity, parcel.source_layer.evidence):
            raise ArithmeticError("erosion parcel source-layer identity changed")
        amount = parcel.source_layer.mass_kg
        if amount > remaining[k][index]:
            raise ArithmeticError("erosion source-layer overdraw")
        remaining[k][index] -= amount
        event = {"source_cell": k, "source_layer_index": index, "source_layer": _layer_record(original),
                 "source_initial_mass_kg": original.mass_kg, "eroded_mass_kg": amount,
                 "remaining_mass_kg": remaining[k][index], "start_year": parcel.start_year, "end_year": parcel.end_year}
        origins[identity] = {"layer": original, "amount": amount, "destinations": {}, "exported": F(0)}
        packets[k][identity] = amount; events.append(event)
    deposits = {k: {} for k in before}; exports = []; transfers = []; max_ratio = F(0)
    for k in flow["order"]:
        incoming = packets[k]
        qw = flow["discharge_m3_year"][k]
        if not incoming:
            continue
        if qw <= 0 or k not in flow["selected"]:
            raise TerrainRegimeError("eroded/transported sediment lacks transporting water and open route")
        out_solid = F(0)
        for identity, amount in sorted(incoming.items()):
            origin = origins[identity]; layer = origin["layer"]; law = smap[layer.material_id]
            factor, theoretical_factor = _settling_factor(qw, law.settling_m_year * before[k].area_m2)
            exported = amount * factor; deposited = amount - exported
            if deposited:
                record = deposits[k].setdefault(layer.material_id, {"mass_kg": F(0), "sources": []})
                record["mass_kg"] += deposited
                record["sources"].append({"source_cell": identity[0], "source_layer_index": identity[1],
                                           "mass_kg": deposited, "fraction_of_eroded_mass": deposited / origin["amount"]})
                origin["destinations"][k] = origin["destinations"].get(k, F(0)) + deposited
            out_solid += exported / layer.grain_density_kg_m3
            receiver = flow["receivers"][k]
            connector_id = flow["selected"][k][1].connector_id
            transfers.append({"cell_id": k, "receiver_id": receiver, "connector_id": connector_id,
                              "source_cell": identity[0], "source_layer_index": identity[1], "material_id": layer.material_id,
                              "incoming_kg": amount, "deposited_kg": deposited, "outgoing_kg": exported,
                              "transport_fraction": factor,
                              "exact_theoretical_transport_fraction": theoretical_factor,
                              "transport_fraction_representation_error": factor - theoretical_factor,
                              "constitutive_precision": "binary64 factor; exact represented mass split"})
            if receiver is None:
                origin["exported"] += exported
                exports.append({"outlet_connector": connector_id, "source_cell": identity[0], "source_layer_index": identity[1],
                                "material_id": layer.material_id, "mass_kg": exported,
                                "solid_volume_m3": exported / layer.grain_density_kg_m3,
                                "fraction_of_eroded_mass": exported / origin["amount"]})
            elif exported:
                packets[receiver][identity] = packets[receiver].get(identity, F(0)) + exported
        ratio = out_solid / (qw * duration)
        max_ratio = max(max_ratio, ratio)
        if ratio > controls.max_solid_liquid_ratio:
            raise TerrainRegimeError("solid/liquid flux ratio exceeds explicitly declared dilute regime")
    output = dict(erosion_columns); deposit_events = []
    density = {l.material_id: l.grain_density_kg_m3 for c in before.values() for l in c.layers}
    for k in sorted(output):
        for material in sorted(deposits[k], key=lambda m: smap[m].deposition_order):
            row = deposits[k][material]; law = smap[material]
            evidence = "R3 material transfer; law: " + law.evidence + "; origin evidence captured in erosion ledger"
            layer = Layer(material, row["mass_kg"], density[material], law.deposited_porosity, "mobile_sediment", evidence)
            index = len(output[k].layers)
            output[k] = output[k].deposit(layer)
            deposit_events.append({"destination_cell": k, "destination_layer_index": index,
                                   "layer": layer, "material_id": material, "mass_kg": row["mass_kg"],
                                   "sources": tuple(row["sources"]), "deposition_order": law.deposition_order,
                                   "pore_water_assignment": "UNASSIGNED: companion water/soil remap must supply and conserve it"})
    if sum(len(c.layers) for c in output.values()) > MAX_LAYERS:
        raise TerrainContractError("deposition exceeds finite-layer reference envelope")
    relief = []
    for row in flow["rows"]:
        k = row["cell_id"]; target = row["receiver_id"]
        initial_drop = row["initial_drop_m"]
        for stage, columns in (("after_erosion", erosion_columns), ("after_deposition", output)):
            receiver_level = row["outlet_elevation_m"] if target is None else columns[target].surface_m
            drop = columns[k].surface_m - receiver_level
            change = abs(drop - initial_drop) / initial_drop
            if drop <= 0 or change > controls.max_relief_change_fraction:
                raise TerrainStepTooLarge("frozen-route relief bound exceeded at " + k + "/" + stage)
            relief.append({"cell_id": k, "stage": stage, "drop_m": drop, "fractional_change": change})
    final = LandscapeState(tuple((k, output[k]) for k, _ in state.columns), eroded.state.elapsed_years,
                           eroded.state.applied_deposition_ids)
    inventory0 = _inventory(before); inventory1 = _inventory(output); balances = []
    for material in sorted(inventory0):
        mass_export = sum((r["mass_kg"] for r in exports if r["material_id"] == material), F(0))
        solid_export = sum((r["solid_volume_m3"] for r in exports if r["material_id"] == material), F(0))
        end_mass, end_solid = inventory1.get(material, (F(0), F(0)))
        residual_mass = inventory0[material][0] - end_mass - mass_export
        residual_solid = inventory0[material][1] - end_solid - solid_export
        if residual_mass or residual_solid:
            raise ArithmeticError("exact material/solid-volume balance failed")
        balances.append({"material_id": material, "initial_mass_kg": inventory0[material][0],
                         "final_mass_kg": end_mass, "exported_mass_kg": mass_export, "mass_residual_kg": residual_mass,
                         "initial_solid_m3": inventory0[material][1], "final_solid_m3": end_solid,
                         "exported_solid_m3": solid_export, "solid_residual_m3": residual_solid})
    for identity, origin in origins.items():
        if sum(origin["destinations"].values(), F(0)) + origin["exported"] != origin["amount"]:
            raise ArithmeticError("per-origin sediment split failed")
    verify(); landscape._verify_sources()
    receipt = {"schema": "diadem.runoff-layered-sediment-trial.r3", "source_status": "WORKING NON-CANON",
               "status": "CONSERVATIVE_FROZEN_TOPOLOGY_TRIAL_NOT_COUPLED_ACCEPTANCE", "production_authorised": False,
               "evidence_id": evidence_id, "duration_years": duration, "start_year": state.elapsed_years,
               "end_year": final.elapsed_years, "water_routing": flow["rows"],
               "local_runoff_m3": flow["local_runoff_m3"], "water_exports_m3": flow["external_exports_m3"],
               "water_residual_m3": F(0), "material_balances": balances,
               "sediment_transfers": transfers, "relief_checks": relief, "maximum_solid_liquid_flux_ratio": max_ratio,
               "initial_surfaces_m": {k: c.surface_m for k, c in before.items()},
               "final_surfaces_m": {k: c.surface_m for k, c in output.items()},
               "actual_R1_erosion_receipt": eroded.receipt,
               "solid_model": "finite contact-resolved R1 erosion; per-material well-mixed steady settling Q/(Q+v*A), binary64-represented factor, exact represented mass ledger",
               "water_model": "conserved imposed local runoff, instantaneous open-DAG accumulation; no hydraulic depth/backwater",
               "pore_water": "not included in runoff export ledger; companion remap must conserve carried/released pore water separately",
               "adaptive_acceptance": "ROOT COUPLED DRIVER REQUIRED: full-vs-two-half comparison including water and material state",
               "soil_meaning": "updated physical columns only; no inferred pedogenesis, horizons or soil fertility"}
    return TerrainTrial(eroded.state, final, tuple(events), tuple(deposit_events), tuple(exports), receipt)
