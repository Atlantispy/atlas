"""R2 finite-quantum channel numerics; unchanged R14 law and native guards.

The trial kernel below is a static adaptation of topography_r1/kernels.py.
Only applied partial erosion and packet splits change representation. Original
law/binary64 errors remain separate from conservative integer Q-unit L1 bounds.
No predecessor source or module globals are mutated.
"""
from dataclasses import replace
from fractions import Fraction as F
import hashlib
from pathlib import Path

from work.geology_r1 import native as g1
from work.generator_upgrade_r28.preflight import clone
from work.native_terrain_r1 import domain as retained_domain
from work.topography_r1 import kernels
from . import numerics as n


def _verify_source():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != globals().get('_R12_EXECUTED_SHA256'):
        raise ValueError('executed R2 channel source differs; no repin')


def _floor_pair(proposed):
    """Outgoing/debited floor plus conservative paired debit-credit L1 units."""
    if type(proposed) not in (int, F) or proposed < 0:
        raise ValueError('nonnegative exact proposed mass required')
    scaled = F(proposed) / n.Q
    applied = n.mass(scaled.numerator // scaled.denominator)
    paired = 2 * n.ceil_error_units(F(proposed)-applied)
    n.mass(paired)  # enforce the same bounded integer count, including sums
    return applied, paired


def _finish_compaction(record):
    total = record['erosion_rounding_l1_units'] + record['packet_split_l1_units']
    if total != sum(record['by_material_l1_units'].values()):
        raise ArithmeticError('integer compaction error ledger does not close')
    record['total_l1_units'] = total
    record['total_l1_bound_kg'] = n.mass(total)
    if any(type(value) is not int or value < 0 for value in record['by_material_l1_units'].values()):
        raise ValueError('nonnegative integer per-material error units required')


def _compact_erosion(native, state, forcings, laws, duration):
    """Keep the R14 proposal intact; finalise only rebuilt finite Q debits.

    Full contacts stay exact. A partial closes its column's interval, so
    retaining its sub-Q remainder cannot expose another contact in this call.
    Proposal contact times and native metadata are retained explicitly.
    """
    before = state.column_map
    for column in before.values():
        for layer in column.layers:
            n.units(layer.mass_kg)
    proposal = g1.erosion.advance(state, forcings, laws, duration)
    receipt = proposal.receipt
    if receipt.get('schema') != g1.erosion.SCHEMA:
        raise ValueError('actual retained R14 erosion proposal required')
    records = receipt['numerical_representation']
    if len(records) != len(proposal.eroded_parcels):
        raise ValueError('R14 proposal parcel/representation record count differs')
    remaining = {key: [layer.mass_kg for layer in column.layers] for key, column in before.items()}
    seen, closed_partial, applied_parcels, rounding = set(), set(), [], []
    error = {'mass_quantum_kg': n.Q, 'erosion_rounding_l1_units': 0,
             'packet_split_l1_units': 0,
             'by_material_l1_units': {layer.material_id: 0 for column in before.values() for layer in column.layers},
             'bound_scope': 'Paired debit/credit L1 enclosure for representation changes in this frozen trial only; integer Q units. Not original-law, adaptive, global trajectory or empirical error.',
             'original_R14_local_mass_representation_error_bound_kg': receipt['local_mass_representation_error_bound_kg'],
             'original_R14_bound_scope': receipt['representation_bound_scope']}
    for row, parcel in zip(records, proposal.eroded_parcels, strict=True):
        key, index = row['column_id'], row['source_layer_index']
        if type(index) is not int or key not in before or not 0 <= index < len(before[key].layers):
            raise ValueError('R14 proposal has no finite input layer')
        identity = key, index
        original = before[key].layers[index]
        amount = parcel.source_layer.mass_kg
        if (identity in seen or key in closed_partial or parcel.column_id != key
                or F(row['applied_mass_kg']) != amount or row['material_id'] != original.material_id
                or F(row['start_year']) != parcel.start_year or F(row['end_year']) != parcel.end_year
                or replace(parcel.source_layer, mass_kg=original.mass_kg) != original
                or any(remaining[key][index+1:]) or not 0 < amount <= original.mass_kg):
            raise ValueError('R14 proposal source/order/contact identity differs')
        seen.add(identity)
        if row['kind'] == 'FULL_CONTACT_EXACT_APPLIED_STOCK':
            if amount != original.mass_kg:
                raise ValueError('full contact must remove exactly its finite stock')
            applied, paired = amount, 0
            n.units(applied)
        elif row['kind'] == 'PARTIAL_BINARY64_REQUEST_EXACT_APPLIED_SPLIT':
            if amount >= original.mass_kg or parcel.end_year != proposal.state.elapsed_years:
                raise ValueError('partial must retain stock and finish its column interval')
            applied, paired = _floor_pair(amount)
            closed_partial.add(key)
        else:
            raise ValueError('unsupported R14 contact representation kind')
        remaining[key][index] -= applied
        n.units(remaining[key][index])
        if applied:
            applied_parcels.append(replace(parcel, source_layer=replace(original, mass_kg=applied)))
        error['erosion_rounding_l1_units'] += paired
        error['by_material_l1_units'][original.material_id] += paired
        rounding.append({'source_cell': key, 'source_layer_index': index, 'material_id': original.material_id,
                         'contact_kind': row['kind'], 'proposed_mass_kg': amount,
                         'applied_mass_kg': applied, 'paired_l1_units': paired})
    columns = []
    for key, column in state.columns:
        layers = tuple(replace(layer, mass_kg=amount) for layer, amount in zip(column.layers, remaining[key], strict=True) if amount)
        columns.append((key, replace(column, layers=layers, source_status=proposal.state.column_map[key].source_status)))
    applied_state = replace(proposal.state, columns=tuple(columns))
    engine = native.landscape
    column_receipts = []
    for row in receipt['columns']:
        key = row['column_id']
        column_receipts.append(dict(row,
            final_surface_m=engine._pair(applied_state.column_map[key].surface_m),
            material_balance=engine._balance(before[key].layers, (), applied_state.column_map[key].layers,
                [parcel.source_layer for parcel in applied_parcels if parcel.column_id == key])))
    applied_receipt = dict(receipt,
        schema='diadem.layered-landscape-applied-quantum.native-r2',
        columns=column_receipts,
        eroded_parcels=[{'column_id': parcel.column_id, 'start_year': engine._pair(parcel.start_year),
            'end_year': engine._pair(parcel.end_year), 'source_layer': engine._layer_record(parcel.source_layer)}
            for parcel in applied_parcels],
        global_material_balance=engine._balance([layer for column in before.values() for layer in column.layers], (),
            [layer for _, column in columns for layer in column.layers], [parcel.source_layer for parcel in applied_parcels]),
        numerical_representation=rounding,
        contact_solver='Unchanged R14 proposal contact path and times; full contacts exact; partial applied debit floored to Q. No zero layer or sub-Q stock deletion.',
        representation_bound_scope='Original R14 numerical bounds are proposal diagnostics only, separately retained in actual_R14_erosion_receipt; applied Q rounding is recorded in numeric_compaction.',
        local_mass_representation_error_bound_kg=str(n.mass(error['erosion_rounding_l1_units'])))
    error['erosion_rounding'] = rounding
    return replace(proposal, state=applied_state, eroded_parcels=tuple(applied_parcels), receipt=applied_receipt), error, receipt


def trial(domain, state, runoff, duration, laws, sediment_laws, controls, *, evidence_id):
    """One same-native-type trial; no acceptance or automatic migration."""
    _verify_source()
    retained_domain._verify_source()
    if type(domain) is not retained_domain.Domain:
        raise ValueError('one retained source-checked native Domain required')
    domain._state(state)
    expected = kernels.p.sources()
    g1.ground_gate.verify_backend()
    native, _, scope, route = retained_domain._prepared()
    composed = clone(_trial_kernel, **dict(scope, route_water=route, _reuse_settling=True,
        _native=native, _compact_erosion=_compact_erosion, _floor_pair=_floor_pair,
        _units=n.units, _finish_compaction=_finish_compaction))
    result = composed(state, runoff, domain.connectors, laws, sediment_laws,
        duration_years=duration, controls=controls, evidence_id=evidence_id)
    domain._state(result.state)
    retained_domain.channel_layer_sources(state, result)
    g1.ground_gate.verify_backend()
    kernels.p.verify_sources(expected)
    retained_domain._verify_source()
    _verify_source()
    return result


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
    eroded, compaction, r14_receipt = _compact_erosion(_native, state, forcing, laws, duration)
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
            proposed_outgoing = amount * factor
            exported, split_units = _floor_pair(proposed_outgoing)
            deposited = amount - exported
            _units(deposited)
            compaction["packet_split_l1_units"] += split_units
            compaction["by_material_l1_units"][layer.material_id] += split_units
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
                              "constitutive_precision": "unchanged binary64 factor; outgoing floored to Q; exact complementary deposit",
                              "proposed_outgoing_kg": proposed_outgoing,
                              "compaction_paired_l1_units": split_units})
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
    _finish_compaction(compaction)
    for column in output.values():
        for layer in column.layers:
            _units(layer.mass_kg)
    verify(); landscape._verify_sources()
    receipt = {"schema": "diadem.runoff-layered-sediment-trial.native-r2", "source_status": "WORKING NON-CANON",
               "status": "CONSERVATIVE_FROZEN_TOPOLOGY_TRIAL_NOT_COUPLED_ACCEPTANCE", "production_authorised": False,
               "evidence_id": evidence_id, "duration_years": duration, "start_year": state.elapsed_years,
               "end_year": final.elapsed_years, "water_routing": flow["rows"],
               "local_runoff_m3": flow["local_runoff_m3"], "water_exports_m3": flow["external_exports_m3"],
               "water_residual_m3": F(0), "material_balances": balances,
               "sediment_transfers": transfers, "relief_checks": relief, "maximum_solid_liquid_flux_ratio": max_ratio,
               "initial_surfaces_m": {k: _surface(before, k) for k in before},
               "final_surfaces_m": {k: _surface(output, k) for k in output},
               "actual_R14_erosion_receipt": r14_receipt,
               "actual_R14_receipt_role": "UNCHANGED PROPOSAL; APPLIED debits are in applied_erosion_receipt and erosion_events",
               "applied_erosion_receipt": eroded.receipt,
               "numeric_compaction": compaction,
               "solid_model": "unchanged contact-resolved R14 proposal and binary64 settling factor; partial debits and outgoing packets downward Q-quantised; exact finite applied ledger",
               "water_model": "conserved imposed local runoff, instantaneous open-DAG accumulation; no hydraulic depth/backwater",
               "pore_water": "not included in runoff export ledger; companion remap must conserve carried/released pore water separately",
               "adaptive_acceptance": "ROOT COUPLED DRIVER REQUIRED: full-vs-two-half comparison including water and material state",
               "soil_meaning": "updated physical columns only; no inferred pedogenesis, horizons or soil fertility"}
    return TerrainTrial(eroded.state, final, tuple(events), tuple(deposit_events), tuple(exports), receipt)

