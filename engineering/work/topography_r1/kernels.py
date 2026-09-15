"""Exact invocation-local terrain geometry, settling and route reuse.

The retained R3 trial arithmetic is copied below with only prepared views and
settling-factor lookup added. R14 contact-resolved erosion is privately composed.
No sealed code, global state, material origins or represented factors are changed.
"""
from dataclasses import replace
from copy import deepcopy
from types import SimpleNamespace
from fractions import Fraction as F
from collections.abc import Mapping

from work.geology_r1 import native as g1
from work.generator_upgrade_r28.preflight import clone
from . import provenance as p


class _Geometry:
    """Strong object references prevent identity reuse; no view escapes a trial."""
    def __init__(self, enabled=True):
        self.enabled = enabled
        self._maps = {}
        self._surfaces = {}

    def columns(self, state):
        if not self.enabled:
            return state.column_map
        key = id(state)
        if key not in self._maps:
            self._maps[key] = (state, state.column_map)
        return self._maps[key][1]

    def surface(self, columns, key):
        column = columns[key]
        if not self.enabled:
            return column.surface_m
        identity = id(column)
        if identity not in self._surfaces:
            self._surfaces[identity] = (column, column.surface_m)
        return self._surfaces[identity][1]


def _state_binding(state):
    return (state.elapsed_years, state.applied_deposition_ids, tuple(
        (key, column.area_m2, column.basal_elevation_m, column.source_status,
         tuple((layer.material_id, layer.mass_kg, layer.grain_density_kg_m3,
                layer.porosity, layer.phase, layer.evidence) for layer in column.layers))
        for key, column in state.columns))


class _RouteReuse:
    """Private, single-use route; bind values before exposing flow to the caller."""
    def __init__(self, native, route, state, runoff, connectors, duration):
        self.native = native
        self.route = route
        self._source = (native, route, native.route_water, native.verify,
                        native.landscape._verify_sources)
        self.state = state
        self.binding = _state_binding(state)
        self.runoff = dict(runoff)
        self.connectors = deepcopy(tuple(connectors))
        self.duration = F(duration)
        self.used = False
        self.flow = route(state, runoff, connectors, duration_years=duration)
        self._pristine_flow = deepcopy(self.flow)

    def take(self, state, runoff, connectors, *, duration_years):
        native = self.native
        if (native is not self._source[0] or self.route is not self._source[1]
                or native.route_water is not self._source[2]
                or native.verify is not self._source[3]
                or native.landscape._verify_sources is not self._source[4]):
            raise ValueError('pre-erosion route callable/source identity changed')
        # Retain the original route's validation semantics, not merely coercive
        # equality (False == 0, for example, must not admit Boolean runoff).
        native.verify()
        native.landscape._verify_sources()
        if type(state) is not native.LandscapeState or not 0 < len(state.columns) <= native.MAX_CELLS:
            raise native.TerrainContractError('bounded shared pinned LandscapeState required')
        if sum(len(c.layers) for _, c in state.columns) > native.MAX_LAYERS:
            raise native.TerrainContractError('bounded finite-layer inventory exceeded')
        duration = native._q(duration_years, 'duration in explicitly bound model years', True)
        if not isinstance(runoff, Mapping) or set(runoff) != {key for key, _ in state.columns}:
            raise native.TerrainContractError('one explicit local runoff volume per cell required')
        local = {key: native._q(runoff[key], 'local runoff:'+key) for key in sorted(runoff)}
        if (type(connectors) not in (tuple, list) or len(connectors) > native.MAX_CONNECTORS
                or any(type(c) is not native.Connector for c in connectors)):
            raise native.TerrainContractError('bounded explicit connector inventory required')
        if (self.used or state is not self.state or _state_binding(state) != self.binding
                or local != self.runoff or tuple(connectors) != self.connectors
                or duration != self.duration or self.flow != self._pristine_flow):
            raise ValueError('pre-erosion route is immutable, bound and single-use')
        self.used = True
        # Match the original route's fresh entry AND exit source boundaries.
        native.verify()
        native.landscape._verify_sources()
        return self.flow


def _scope(geometry):
    _, native = g1.ground_gate.backend()
    view = _Geometry(geometry)
    scope = dict(native.terrain_trial.__globals__,
                 _maps=view.columns, _surface=view.surface)
    scope['landscape'] = SimpleNamespace(
        Forcing=native.landscape.Forcing, advance=g1.erosion.advance,
        _verify_sources=native.landscape._verify_sources)
    route = clone(_route_kernel, **scope)
    return native, view, scope, route


def _trial(state, local_runoff_m3, connectors, laws, sediment_laws, *,
           duration_years, controls, evidence_id, geometry=True, settling=True,
           route_token=None, prepared=None):
    """Internal feature switches are only for paired measurements/composition."""
    expected = p.sources()
    native, view, scope, route = _scope(geometry) if prepared is None else prepared
    g1.ground_gate.verify_backend()
    scope = dict(scope, route_water=route if route_token is None else route_token.take,
                 _reuse_settling=settling)
    composed = clone(_trial_kernel, **scope)
    result = composed(state, local_runoff_m3, connectors, laws, sediment_laws,
                      duration_years=duration_years, controls=controls, evidence_id=evidence_id)
    receipt = dict(result.receipt)
    successor = receipt.pop('actual_R1_erosion_receipt')
    if successor.get('schema') != g1.erosion.SCHEMA:
        raise ValueError('topography trial requires actual R14 erosion receipt')
    receipt.update(schema='diadem.runoff-layered-sediment-trial.r14',
        actual_R14_erosion_receipt=successor,
        numerical_composition='Topography R1 private exact geometry and settling views; R14 successor erosion; no sealed module mutation',
        solid_model='R14 contact-resolved finite erosion with bounded represented rates/partial transfers and exact applied material splits; R3 per-material steady settling with binary64 factor and exact split')
    g1.ground_gate.verify_backend()
    p.verify_sources(expected)
    return replace(result, receipt=receipt)


def trial(state, local_runoff_m3, connectors, laws, sediment_laws, *,
          duration_years, controls, evidence_id):
    return _trial(state, local_runoff_m3, connectors, laws, sediment_laws,
                  duration_years=duration_years, controls=controls, evidence_id=evidence_id)


def route_water(state, local_runoff_m3, connectors, *, duration_years):
    expected = p.sources()
    _, _, _, route = _scope(True)
    result = route(state, local_runoff_m3, connectors, duration_years=duration_years)
    p.verify_sources(expected)
    return result


def _route_kernel(state, local_runoff_m3, connectors, *, duration_years):
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
    columns = _maps(state)
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
        receiver_level = c.outlet_elevation_m if c.receiver_id is None else _surface(columns, c.receiver_id)
        drop = _surface(columns, c.source_id) - receiver_level
        if drop > 0:
            options[c.source_id].append((drop / c.length_m, c, drop))
    selected = {}
    for k, rows in options.items():
        if rows:
            selected[k] = sorted(rows, key=lambda r: (-r[0], r[1].connector_id))[0]
    order = sorted(columns, key=lambda k: (-_surface(columns, k), k))
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


def _trial_kernel(state, local_runoff_m3, connectors, laws, sediment_laws, *,
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
    duration = flow["duration_years"]; before = _maps(state)
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
    erosion_columns = _maps(eroded.state)
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
        settling_factors = {}
        for identity, amount in sorted(incoming.items()):
            origin = origins[identity]; layer = origin["layer"]; law = smap[layer.material_id]
            if not _reuse_settling or layer.material_id not in settling_factors:
                settling_factors[layer.material_id] = _settling_factor(qw, law.settling_m_year * before[k].area_m2)
            factor, theoretical_factor = settling_factors[layer.material_id]
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
            receiver_level = row["outlet_elevation_m"] if target is None else _surface(columns, target)
            drop = _surface(columns, k) - receiver_level
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
               "initial_surfaces_m": {k: _surface(before, k) for k in before},
               "final_surfaces_m": {k: _surface(output, k) for k in output},
               "actual_R1_erosion_receipt": eroded.receipt,
               "solid_model": "finite contact-resolved R1 erosion; per-material well-mixed steady settling Q/(Q+v*A), binary64-represented factor, exact represented mass ledger",
               "water_model": "conserved imposed local runoff, instantaneous open-DAG accumulation; no hydraulic depth/backwater",
               "pore_water": "not included in runoff export ledger; companion remap must conserve carried/released pore water separately",
               "adaptive_acceptance": "ROOT COUPLED DRIVER REQUIRED: full-vs-two-half comparison including water and material state",
               "soil_meaning": "updated physical columns only; no inferred pedogenesis, horizons or soil fertility"}
    return TerrainTrial(eroded.state, final, tuple(events), tuple(deposit_events), tuple(exports), receipt)
