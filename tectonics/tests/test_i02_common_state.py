"""Focused I02.1 checks: the real finite-strain initial column inside the common-state envelope.

The retained campaign tools only build the fixture; the package API receives their native values. Tiny order-8
and order-4 columns: no evolution, no external process and no new dependency. Successor states and their
continuation are checked in test_i02_evolution.py; here the root's identity-bound records must stay verifiable.
SPDX-License-Identifier: AGPL-3.0-only
"""
import ast
import copy
import dataclasses
import hashlib
import json
import math
from pathlib import Path
import pickle
import platform
import sys
import unittest

import numpy as np
import scipy
from threadpoolctl import threadpool_limits

from atlas_tectonics import integration_state as I
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.materials import MaterialCohort, MaterialState
from atlas_tectonics.mesh import ColumnGrid1D
from atlas_tectonics.regional import RegionalGrid1D
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.w08_inventory import W08Inventory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_finite_admission as fa
import check_i01_finite_strain as fs

w, heat, tm = fs.weakening, fs.heat, fs.tm
SPEC, CTX = fs.load_case()
LAW, DRIVE = CTX["law"], CTX["drive"]
START, EPOCH, FRAME = 2.5e6, "i01-finite-strain-reference-epoch", "i01-finite-strain-strip"
LAYERED_ORIGIN, UNIFORM_ORIGIN = "cases/i01_weakening_v1.json", "cases/i01_column_heat_v1.json#campaign/homogeneous"
BASIS = "declared-exterior-enthalpy"
# Declared producer identities: the finite-strain tool's own source bindings and this runtime's versions.
SOURCE_ID = hashlib.sha256(json.dumps(fs.bindings(), sort_keys=True).encode()).hexdigest()
RUNTIME_ID = hashlib.sha256(json.dumps(dict(python=platform.python_version(), numpy=np.__version__,
                                            scipy=scipy.__version__), sort_keys=True).encode()).hexdigest()
FIX = {}


def setUpModule():
    with threadpool_limits(limits=1, user_api="blas"):
        base, thermal, key, rebuild = fs.layered(CTX, 8)
        hb, ht, h = tm.homogeneous_setup(CTX, 4)
    layer = h["layer"]
    uniform_inputs = dict(
        thicknesses=[layer["thickness_m"]],
        props=[dict(name=layer["name"], conductivity_w_m_k=h["thermal"]["conductivity_w_m_k"],
                    heat_capacity_j_kg_k=h["thermal"]["heat_capacity_j_kg_k"], radiogenic_w_m3=0.)],
        densities=[h["thermal"]["density_kg_m3"]],
        boundaries=dict(top=dict(type="insulated"), bottom=dict(type="insulated")),
        reference_temperature=layer["temperature_k"][0])
    FIX.update(base=base, thermal=thermal, key=key, rebuild=rebuild, hb=hb, ht=ht, h=h,
               hkey=([layer], 4, w.SUPPLIED, None), hinputs=uniform_inputs)


def mechanical(base, key, **changes):
    """The retained preparation's attributes, handed to the package as native values."""
    density = None if np.all(np.isnan(base.density)) else base.density
    values = dict(key=key, fingerprint=base.fingerprint, layer=base.layer, depth_m=base.depth_m, weight=base.weight,
                  reference_pa=base.reference_pa, density=density, thickness_m=base.thickness_m)
    values.update(changes)
    return values


def thermal_side(thermal, inputs, **changes):
    values = dict(provider=I.COLUMN_THERMAL_BASIS, inputs=inputs, fingerprint=thermal.fingerprint,
                  mechanical_fingerprint=thermal.mechanical_fingerprint, layer=thermal.layer,
                  depth_m=thermal.depth_m, volume_m=thermal.volume_m,
                  reference_density_kg_m3=thermal.reference_density_kg_m3, capacity=thermal.capacity,
                  radiogenic=thermal.radiogenic, steady_k=thermal.steady_k,
                  boundary_temperature=thermal.boundary_temperature, thickness_m=thermal.thickness_m)
    values.update(changes)
    return values


def reference(mech=None, therm=None, budget=None):
    return I.ColumnReference(mechanical=mechanical(FIX["base"], FIX["key"]) if mech is None else mech,
                             thermal=thermal_side(FIX["thermal"], FIX["rebuild"]) if therm is None else therm,
                             budget=budget)


def settings(**changes):
    values = dict(representation=SPEC["representation"], law=dataclasses.asdict(LAW),
                  drive=dataclasses.asdict(DRIVE), heat_fractions=CTX["heat"]["heat_fractions"],
                  policy=SPEC["policy"], schedule=dict(duration_s=SPEC["drive"]["duration_s"], steps=16))
    values.update(changes)
    return I.ColumnSettings(**values)


def identity(**changes):
    values = dict(world_id="atlas-bounded-control:not-a-generated-world",
                  scenario_id="cases/i01_finite_strain_v1.json#layered-order-8", epoch_id=EPOCH,
                  source_id=SOURCE_ID, runtime_id=RUNTIME_ID, unit_system=I.UNIT_SYSTEM)
    values.update(changes)
    return I.StateIdentity(**values)


def cohorts(layers, origin, *, frame=FRAME, epoch=EPOCH, time_s=START, scale=1., extra=()):
    """Native W02 cohorts for the layers: declared origins, unknown formation times, one strip cell."""
    ids = tuple("layer-%d-%s" % (k, layer["name"]) for k, layer in enumerate(layers))
    records = [MaterialCohort(cohort, layer["name"], "%s#layers/%d" % (origin, k), None)
               for k, (cohort, layer) in enumerate(zip(ids, layers))]
    thickness = [[float(layer["thickness_m"])*scale] for layer in layers]
    for record, value in extra:
        records.append(record)
        thickness.append([value])
    order = sorted(range(len(records)), key=lambda i: records[i].cohort_id)
    state = MaterialState(ColumnGrid1D([0., DRIVE.width_m], frame_id=frame), tuple(records[i] for i in order),
                          [thickness[i] for i in order], time_s=time_s, epoch_id=epoch)
    return state, ids


def reservoir(**changes):
    values = dict(node_ids=("exterior-store",), node_kinds=("reservoir",), component_ids=("A",),
                  component_mass_kg=[[5.]], enthalpy_j=[-3.], source_id="declared-exterior-stock",
                  enthalpy_source=BASIS, time_s=START, formation_time_s=[START-10.],
                  origin_ids=("declared-exterior-origin",))
    values.update(changes)
    return W08Inventory(**values)


def theta_signed(base):
    """A nonzero departure of both signs: warmer above mid-depth, cooler below, inside the declared window."""
    return 2.*np.sin(2.*math.pi*np.asarray(base.depth_m)/base.thickness_m)


def build(ref=None, sett=None, ident=None, theta=None, kappa=None, materials=None, layer_cohorts=None,
          reservoirs=None, basis=None, start=START, frame=FRAME, budget=None):
    base = FIX["base"]
    if materials is None:
        materials, layer_cohorts = cohorts(FIX["key"][0], LAYERED_ORIGIN)
    return I.initial_state(identity=identity() if ident is None else ident, start_time_s=start, frame_id=frame,
                           reference=reference() if ref is None else ref,
                           settings=settings() if sett is None else sett,
                           theta0_k=theta_signed(base) if theta is None else theta,
                           kappa0=w.initial_history(base, CTX["weak"]) if kappa is None else kappa,
                           materials=materials, layer_cohorts=layer_cohorts, reservoirs=reservoirs,
                           reservoir_basis=basis, budget=budget)


class Limited(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api="blas")
        self.addCleanup(lease.restore_original_limits)

    def refuses(self, cases):
        for name, fn in cases.items():
            with self.subTest(name), self.assertRaises(TectonicsError):
                fn()


class RepresentationTests(Limited):
    def test_real_initial_column_retains_references_histories_and_provenance(self):
        base, thermal, key = FIX["base"], FIX["thermal"], FIX["key"]
        theta0, kappa0 = theta_signed(base), w.initial_history(base, CTX["weak"])
        materials, ids = cohorts(key[0], LAYERED_ORIGIN)
        state = build(theta=theta0, kappa=kappa0, materials=materials, layer_cohorts=ids)
        ref, col = state.reference, state.column
        self.assertEqual((state.schema, state.route, state.admission), (I.SCHEMA, I.ROUTE, I.NOT_CONFERRED))
        # Both original references, exactly as prepared, with the pinned inputs that reproduce them.
        self.assertEqual(ref.mechanical_fingerprint, base.fingerprint)
        self.assertEqual(ref.mechanical_fingerprint, w.fingerprint(*key))
        self.assertEqual(ref.thermal_fingerprint, thermal.fingerprint)
        self.assertEqual((ref.closure, ref.order, ref.gravity_m_s2), (w.LITHOSTATIC, 8, 9.81))
        self.assertEqual(ref.layer_names, tuple(layer["name"] for layer in key[0]))
        self.assertEqual((ref.thickness_m, ref.boundary_temperature_k), (base.thickness_m, (273., 1613.)))
        for mine, theirs in ((ref.depth_m, base.depth_m), (ref.weight_m, base.weight),
                             (ref.overburden_pa, base.reference_pa), (ref.density_kg_m3, base.density),
                             (ref.steady_temperature_k, thermal.steady_k), (ref.capacity_j_m2_k, thermal.capacity),
                             (ref.radiogenic_w_m2, thermal.radiogenic),
                             (ref.thermal_density_kg_m3, thermal.reference_density_kg_m3)):
            self.assertEqual(mine.tobytes(), np.asarray(theirs).tobytes())
        np.testing.assert_array_equal(ref.point_layer, base.layer)
        self.assertEqual(ref.preparation_key(), key)
        self.assertEqual(ref.thermal_inputs(), FIX["rebuild"])
        # Nonzero initial thermal departure and inherited weakening history; nothing booked since the reference.
        self.assertEqual(col.theta_k.tobytes(), theta0.tobytes())
        self.assertEqual(col.initial_theta_k.tobytes(), theta0.tobytes())
        self.assertEqual(col.kappa.tobytes(), kappa0.tobytes())
        self.assertEqual(col.initial_kappa.tobytes(), kappa0.tobytes())
        self.assertTrue(np.any(col.theta_k > 0) and np.any(col.theta_k < 0) and np.any(col.kappa > 0))
        self.assertEqual((col.stretch, col.elapsed_s, col.accepted_steps, col.clock_s, col.displacement_m,
                          col.log_path, col.log_strain_quadrature), (1., 0., 0, 0., 0., 0., 0.))
        self.assertEqual(col.accounts_j_m, dict.fromkeys(I.STAGE_ACCOUNTS+I.THERMAL_ACCOUNTS, 0.))
        self.assertEqual(col.counters, dict.fromkeys(I.COUNTERS, 0))
        self.assertEqual(col.extrema, dict.fromkeys(I.EXTREMA))
        self.assertIsNone(col.velocity_start_m_s)
        self.assertFalse(np.any(col.yield_stage_counts))
        # Clock, lineage and geometry measured from the reference; reference mass versus conserved volume.
        self.assertEqual((state.start_time_s, state.time_s, state.epoch_id, state.frame_id), (START, START, EPOCH, FRAME))
        self.assertIsNone(state.parent_state_id)
        self.assertEqual(state.root_state_id, state.state_id)
        self.assertEqual((state.current_width_m, state.current_thickness_m), (DRIVE.width_m, base.thickness_m))
        self.assertEqual(state.current_depth_m.tobytes(), np.asarray(base.depth_m).tobytes())
        self.assertEqual(state.reference_volume_m2, DRIVE.width_m*base.thickness_m)
        self.assertEqual(state.reference_mass_kg_m, DRIVE.width_m*math.fsum(base.density*base.weight))
        self.assertEqual(state.departure_enthalpy_j_m, DRIVE.width_m*math.fsum(np.asarray(thermal.capacity)*theta0))
        self.assertEqual(state.temperature_k.tobytes(), (np.asarray(thermal.steady_k)+theta0).tobytes())
        # Native material provenance is held, not flattened: same object, origins and unknown formation times.
        self.assertIs(state.materials, materials)
        self.assertEqual(state.layer_cohorts, ids)
        by_id = {cohort.cohort_id: cohort for cohort in state.materials.cohorts}
        for k, cohort_id in enumerate(ids):
            self.assertEqual(by_id[cohort_id].material_id, key[0][k]["name"])
            self.assertEqual(by_id[cohort_id].origin_id, "%s#layers/%d" % (LAYERED_ORIGIN, k))
            self.assertIsNone(by_id[cohort_id].formation_time_s)
            self.assertEqual(state.cohort_reference_volume_m2()[cohort_id], DRIVE.width_m*key[0][k]["thickness_m"])
        described = state.descriptor()
        self.assertEqual(described["materials"]["state_id"], materials.state_id)
        self.assertEqual(described["materials"]["descriptor"], materials.descriptor())
        # The native payload keeps its own date and is labelled as the unchanged reference inventory.
        self.assertEqual((described["materials"]["dated_time_s"], described["materials"]["role"]),
                         (START, I.MATERIAL_ROLE))
        self.assertEqual(state.remaining_steps, state.settings.steps)
        # Every identity recomputes from its record and arrays: what a continuation verifies before advancing.
        self.assertEqual(I._identity(ref._record, ref._arrays()), ref.reference_id)
        self.assertEqual(I._identity(col._record, col._arrays()), col.column_state_id)
        self.assertIs(I._verified(state), state)
        # Units, support and single ownership are declared, including explicit unknown physics.
        declared = {entry["name"]: entry for entry in state.declaration()}
        self.assertEqual((declared["theta_k"]["units"], declared["capacity_j_m2_k"]["units"],
                          declared["accounts.heat_j_m"]["units"]), ("K", "J/(m2 K)", "J/m"))
        self.assertEqual(declared["reference_depth_m"]["support"], "material point")
        self.assertEqual(declared["material_cohorts"]["owner"], "W02 material inventory")
        for name in ("elastic_stress_pa", "melt_fraction", "absolute_elevation_m", "global_position",
                     "external_loads_pa"):
            self.assertEqual((declared[name]["status"], declared[name]["known"]), ("unknown", False))
        self.assertTrue(declared["reference_density_kg_m3"]["known"])
        self.assertFalse(declared["finite_reservoirs"]["known"])
        specs = {spec["name"]: spec for spec in described["reference"]["arrays"]}
        self.assertEqual((specs["steady_temperature_k"]["units"], specs["reference_overburden_pa"]["units"]), ("K", "Pa"))

    def test_identity_is_deterministic_and_bound_to_content(self):
        base = FIX["base"]
        first = build()
        listed = mechanical(base, list(copy.deepcopy(FIX["key"])), layer=base.layer.tolist(),
                            depth_m=base.depth_m.tolist(), weight=base.weight.tolist(),
                            reference_pa=base.reference_pa.tolist(), density=base.density.tolist())
        second = build(ref=reference(mech=listed), theta=theta_signed(base).tolist(),
                       kappa=w.initial_history(base, CTX["weak"]).tolist())
        self.assertEqual(second.state_id, first.state_id)
        self.assertEqual(second.identities(), first.identities())
        self.assertEqual(second.descriptor(), first.descriptor())
        kappa = np.array(w.initial_history(base, CTX["weak"]))
        kappa[0] = np.nextafter(kappa[0], 3.)
        nudged = build(kappa=kappa)
        self.assertNotEqual(nudged.state_id, first.state_id)
        self.assertNotEqual(nudged.column.column_state_id, first.column.column_state_id)
        self.assertEqual(nudged.reference.reference_id, first.reference.reference_id)
        self.assertEqual(nudged.settings.settings_id, first.settings.settings_id)
        epoch = "another-epoch"
        materials, ids = cohorts(FIX["key"][0], LAYERED_ORIGIN, epoch=epoch)
        moved = build(ident=identity(epoch_id=epoch), materials=materials, layer_cohorts=ids)
        self.assertNotEqual(moved.state_id, first.state_id)
        self.assertEqual(moved.column.column_state_id, first.column.column_state_id)
        self.assertNotEqual(build(ident=identity(source_id="0"*64)).state_id, first.state_id)
        tighter = build(sett=settings(policy=dict(SPEC["policy"], maximum_seconds=60.)))
        self.assertNotEqual(tighter.state_id, first.state_id)
        self.assertNotEqual(tighter.settings.policy_id, first.settings.policy_id)
        self.assertEqual((tighter.settings.closure_id, tighter.settings.parameter_id),
                         (first.settings.closure_id, first.settings.parameter_id))

    def test_negative_enthalpy_is_retained_not_rejected(self):
        base, thermal = FIX["base"], FIX["thermal"]
        cooler = -2.*np.sin(math.pi*np.asarray(base.depth_m)/base.thickness_m)
        stock = reservoir()
        state = build(theta=cooler, reservoirs=stock, basis=BASIS)
        self.assertLess(state.departure_enthalpy_j_m, 0.)
        self.assertEqual(state.departure_enthalpy_j_m, DRIVE.width_m*math.fsum(np.asarray(thermal.capacity)*cooler))
        self.assertEqual(state.column.theta_k.tobytes(), cooler.tobytes())
        self.assertIs(state.reservoirs, stock)
        self.assertEqual(state.reservoirs.enthalpy_j.tolist(), [-3.])
        self.assertEqual(state.reservoir_basis, BASIS)
        self.assertEqual(state.descriptor()["reservoirs"]["inventory_id"], stock.inventory_id)
        self.assertTrue({entry["name"]: entry for entry in state.declaration()}["finite_reservoirs"]["known"])

    def test_route_constants_follow_the_retained_tool(self):
        # I02.2b: one copy each, owned by the package solver and re-exported by the retained tool.
        self.assertIs(I.REPRESENTATION, fs.REPRESENTATION)
        self.assertIs(I.STRETCH_CEILING, fs.STRETCH_CEILING)
        self.assertIs(I.TEMPERATURE_CEILING_K, fs.TEMPERATURE_CEILING_K)
        self.assertIs(I.THERMAL_ACCOUNTS, fs.THERMAL_ACCOUNTS)
        self.assertEqual(I.REPRESENTATION, fs.REPRESENTATION)
        self.assertEqual((I.STRETCH_CEILING, I.TEMPERATURE_CEILING_K), (fs.STRETCH_CEILING, fs.TEMPERATURE_CEILING_K))
        self.assertEqual(I.STAGE_ACCOUNTS, tuple(name for name, _ in fs.STAGE_ACCOUNTS))
        self.assertEqual(I.THERMAL_ACCOUNTS, fs.THERMAL_ACCOUNTS)
        self.assertLessEqual(set(I.COUNTERS+I.EXTREMA), set(fs.SCALARS))
        self.assertEqual((I.MAX_LAYERS, I.MAX_ORDER), (fs.column.POLICY["max_layers"], fs.column.POLICY["max_order"]))
        self.assertEqual((I.LITHOSTATIC, I.SUPPLIED, I.MAX_STEPS), (w.LITHOSTATIC, w.SUPPLIED, SPEC["policy"]["max_steps"]))
        self.assertEqual(I.HORIZON_CEILING_S, fa.HORIZON_CEILING_S)
        names = [entry[0] for entry in I.CATALOGUE]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual([name[9:] for name in names if name.startswith("accounts.")],
                         list(I.STAGE_ACCOUNTS+I.THERMAL_ACCOUNTS))
        for entry in I.CATALOGUE:
            self.assertEqual(len(entry), len(I.CATALOGUE_FIELDS))
            self.assertIn(entry[5], ("required", "supported", "unknown"))
            self.assertTrue(entry[3] and entry[4])                       # one owner and one producer
        self.assertEqual({entry[0] for entry in I.CATALOGUE if entry[5] == "supported"}, set(I._PRESENCE))

    def test_package_module_does_not_reach_campaign_tools(self):
        source = Path(I.__file__).read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add("."*node.level+(node.module or ""))
        self.assertFalse({name for name in imported if name.startswith("check_") or name in ("sys", "pickle")},
                         imported)
        self.assertNotIn("sys.path", source)


class RefusalTests(Limited):
    def test_wrong_time_epoch_and_frame_refuse(self):
        layers = FIX["key"][0]
        later, ids = cohorts(layers, LAYERED_ORIGIN, time_s=START+1.)
        elsewhen, _ = cohorts(layers, LAYERED_ORIGIN, epoch="another-epoch")
        elsewhere, _ = cohorts(layers, LAYERED_ORIGIN, frame="another-frame")
        plain, _ = cohorts(layers, LAYERED_ORIGIN)
        frameless = MaterialState(RegionalGrid1D(1, DRIVE.width_m), plain.cohorts, plain.thickness_m,
                                  time_s=START, epoch_id=EPOCH)
        self.refuses({
            "material_time": lambda: build(materials=later, layer_cohorts=ids),
            "material_epoch": lambda: build(materials=elsewhen, layer_cohorts=ids),
            "reservoir_time": lambda: build(reservoirs=reservoir(time_s=START+1.), basis=BASIS),
            "start_not_finite": lambda: build(start=float("nan")),
            "start_as_text": lambda: build(start="2.5e6"),
            "start_as_bool": lambda: build(start=True),
            "material_frame": lambda: build(materials=elsewhere, layer_cohorts=ids),
            "frameless_material_grid": lambda: build(materials=frameless, layer_cohorts=ids),
            "blank_frame": lambda: build(frame=" "),
        })

    def test_wrong_units_refuse(self):
        thermal, rebuild = FIX["thermal"], FIX["rebuild"]
        km, ids = cohorts(FIX["key"][0], LAYERED_ORIGIN, scale=1e-3)
        kilojoules = copy.deepcopy(rebuild)
        for prop in kilojoules["props"]:
            prop["heat_capacity_j_kg_k"] /= 1e3
        self.refuses({
            "declared_unit_system": lambda: identity(unit_system="CGS: cm, g, s"),
            "drive_width_in_km": lambda: build(sett=settings(drive=dict(dataclasses.asdict(DRIVE),
                                                                        width_m=DRIVE.width_m/1e3))),
            "cohort_thickness_in_km": lambda: build(materials=km, layer_cohorts=ids),
            "capacity_in_kilojoules": lambda: reference(therm=thermal_side(
                thermal, rebuild, capacity=np.asarray(thermal.capacity)/1e3)),
            "heat_capacity_input_in_kilojoules": lambda: reference(therm=thermal_side(thermal, kilojoules)),
            "steady_temperature_in_celsius": lambda: build(ref=reference(therm=thermal_side(
                thermal, rebuild, steady_k=np.asarray(thermal.steady_k)-273.15))),
        })

    def test_wrong_support_and_reference_refuse(self):
        base, thermal, key, rebuild = FIX["base"], FIX["thermal"], FIX["key"], FIX["rebuild"]
        stale = copy.deepcopy(key[0])
        stale[0]["temperature_k"] = [t+1e-9 for t in stale[0]["temperature_k"]]
        wet = copy.deepcopy(key[0])
        wet[0]["pore_pressure_pa"] = [0., 1e6]
        stretched = fs.column_at(base, fs.coefficients(base), 1.1, np.array(thermal.steady_k))
        other, _ = w.base_prepare(CTX["weak"], order=8, offset_k=1.)
        thick = [layer["thickness_m"] for layer in key[0]]
        dens = [layer["density_kg_m3"] for layer in key[0]]
        foreign = heat.prepare_thermal(*heat.geometry(thick[::-1], 8), thick[::-1], CTX["heat"]["thermal_layers"],
                                       dens, CTX["heat"]["boundaries"], mechanical_fingerprint=base.fingerprint)
        shifted = dataclasses.replace(thermal, depth_m=w.frozen(np.asarray(thermal.depth_m)+1.))
        _, coarse, _, _ = fs.layered(CTX, 4)
        plain, ids = cohorts(key[0], LAYERED_ORIGIN)
        two_cells = MaterialState(ColumnGrid1D([0., DRIVE.width_m/2, DRIVE.width_m], frame_id=FRAME), plain.cohorts,
                                  np.repeat(plain.thickness_m, 2, axis=1), time_s=START, epoch_id=EPOCH)
        self.refuses({
            "stale_pinned_inputs": lambda: reference(mech=mechanical(base, (stale, *key[1:]))),
            "stretched_preparation_as_reference": lambda: reference(mech=mechanical(stretched, key)),
            "stretched_arrays_under_reference_identity": lambda: reference(mech=mechanical(
                base, key, depth_m=stretched.depth_m, weight=stretched.weight, thickness_m=stretched.thickness_m)),
            "nonzero_pore_pressure": lambda: reference(mech=mechanical(base, (wet, *key[1:]))),
            "reversed_overburden": lambda: reference(mech=mechanical(
                base, key, reference_pa=np.asarray(base.reference_pa)[::-1].copy())),
            "density_not_the_pinned_layers": lambda: reference(mech=mechanical(
                base, key, density=np.asarray(base.density)+1.)),
            "thermal_for_another_column": lambda: reference(therm=thermal_side(
                thermal, rebuild, mechanical_fingerprint=other.fingerprint)),
            "same_size_foreign_support": lambda: reference(therm=thermal_side(foreign, rebuild)),
            "shifted_support_copy": lambda: reference(therm=thermal_side(shifted, rebuild)),
            "support_of_another_order": lambda: reference(therm=thermal_side(coarse, rebuild)),
            "departure_on_another_support": lambda: build(theta=np.zeros(base.size+1)),
            "initial_temperature_outside_window": lambda: build(theta=np.full(base.size, 1000.)),
            "two_cell_material": lambda: build(materials=two_cells, layer_cohorts=ids),
        })

    def test_wrong_provider_and_duplicate_ownership_refuse(self):
        thermal, rebuild = FIX["thermal"], FIX["rebuild"]
        plain, ids = cohorts(FIX["key"][0], LAYERED_ORIGIN)
        slab = MaterialCohort("unowned-slab", "mantle-lithosphere-dry-olivine", "declared-extra-material", None)
        extra, _ = cohorts(FIX["key"][0], LAYERED_ORIGIN, extra=((slab, 1000.),))
        self.refuses({
            "thermal_provider": lambda: reference(therm=thermal_side(thermal, rebuild,
                                                                    provider="corrected-G25 common Gibbs")),
            "reservoir_basis_mismatch": lambda: build(reservoirs=reservoir(), basis="another-enthalpy-convention"),
            "reservoir_claims_the_column_basis": lambda: build(
                reservoirs=reservoir(enthalpy_source=I.COLUMN_THERMAL_BASIS), basis=I.COLUMN_THERMAL_BASIS),
            "reservoir_reuses_a_cohort": lambda: build(reservoirs=reservoir(node_ids=(ids[0],)), basis=BASIS),
            "reservoir_copies_crust": lambda: build(reservoirs=reservoir(node_kinds=("crust",)), basis=BASIS),
            "cohort_owns_two_layers": lambda: build(materials=plain, layer_cohorts=(ids[0], ids[0], ids[2], ids[3])),
            "cohort_describes_another_layer": lambda: build(materials=plain,
                                                            layer_cohorts=(ids[1], ids[0], ids[2], ids[3])),
            "unowned_cohort": lambda: build(materials=extra, layer_cohorts=ids),
            "missing_cohort": lambda: build(materials=plain, layer_cohorts=ids[:3]),
            "untyped_cohort_order": lambda: build(materials=plain, layer_cohorts=list(ids)),
        })

    def test_unsupported_closure_policy_and_schedule_refuse(self):
        rep, pol = SPEC["representation"], SPEC["policy"]
        law = dataclasses.asdict(LAW)
        self.refuses({
            "eulerian_geometry": lambda: settings(representation=dict(
                rep, geometry="Eulerian column with advective face fluxes")),
            "prescribed_motion": lambda: settings(representation=dict(
                rep, control="prescribed smooth affine stretch history")),
            "latent_heat_field": lambda: settings(representation=dict(rep, latent_heat_j_kg=3e5)),
            "missing_heating_field": lambda: settings(representation={k: v for k, v in rep.items() if k != "heating"}),
            "widened_stretch": lambda: settings(representation=dict(rep, stretch_window=[.5, 1.5])),
            "window_without_reference": lambda: settings(representation=dict(rep, stretch_window=[1.1, 1.4])),
            "widened_temperature": lambda: settings(representation=dict(rep, temperature_window_k=[200., 1700.])),
            "temperature_guard": lambda: settings(representation=dict(rep, max_temperature_step_k=6.)),
            "raised_step_ceiling": lambda: settings(policy=dict(pol, max_steps=512)),
            "missing_step_ceiling": lambda: settings(policy={k: v for k, v in pol.items() if k != "max_steps"}),
            "missing_time_budget": lambda: settings(policy={k: v for k, v in pol.items() if k != "maximum_seconds"}),
            "nonfinite_policy": lambda: settings(policy=dict(pol, energy_relative=float("nan"))),
            "steps_beyond_ceiling": lambda: settings(schedule=dict(duration_s=1e14, steps=257)),
            "fractional_steps": lambda: settings(schedule=dict(duration_s=1e14, steps=2.)),
            "zero_duration": lambda: settings(schedule=dict(duration_s=0., steps=16)),
            "duration_beyond_horizon": lambda: settings(schedule=dict(duration_s=1.1e14, steps=16)),
            "missing_steps": lambda: settings(schedule=dict(duration_s=1e14)),
            "empty_weakening_interval": lambda: settings(law=dict(law, start=3.)),
            "strengthening_law": lambda: settings(law=dict(law, cohesion_factor=1.5)),
            "drive_without_drag": lambda: settings(drive=dict(dataclasses.asdict(DRIVE), drag_pa_s=0.)),
            "amplified_heat": lambda: settings(heat_fractions=(1.5, 1.)),
        })

    def test_required_inputs_refuse_rather_than_default(self):
        base = FIX["base"]
        materials, ids = cohorts(FIX["key"][0], LAYERED_ORIGIN)
        common = dict(identity=identity(), start_time_s=START, frame_id=FRAME, reference=reference(),
                      settings=settings(), theta0_k=theta_signed(base), kappa0=w.initial_history(base, CTX["weak"]),
                      materials=materials, layer_cohorts=ids, reservoirs=None, reservoir_basis=None)
        self.assertEqual(I.initial_state(**common).column.stretch, 1.)
        for name in ("identity", "reference", "settings", "theta0_k", "kappa0", "materials", "layer_cohorts"):
            with self.subTest(name), self.assertRaises(TectonicsError):
                I.initial_state(**dict(common, **{name: None}))
        with self.assertRaises(TypeError):                                # an omitted input is not defaulted
            I.initial_state(**{k: v for k, v in common.items() if k != "reservoirs"})
        mech = mechanical(base, FIX["key"])
        self.refuses({
            "lithostatic_density": lambda: reference(mech=dict(mech, density=None)),
            "missing_overburden": lambda: reference(mech={k: v for k, v in mech.items() if k != "reference_pa"}),
            "undeclared_mechanical_field": lambda: reference(mech=dict(mech, pore_pa=base.pore_pa)),
            "missing_thermal_boundaries": lambda: reference(therm=thermal_side(
                FIX["thermal"], {k: v for k, v in FIX["rebuild"].items() if k != "boundaries"})),
            "reservoirs_without_basis": lambda: I.initial_state(**dict(common, reservoirs=reservoir())),
            "basis_without_reservoirs": lambda: I.initial_state(**dict(common, reservoir_basis=BASIS)),
            "missing_unit_declaration": lambda: identity(unit_system=None),
        })

    def test_unknown_optional_fields_stay_unknown(self):
        hb, ht, h = FIX["hb"], FIX["ht"], FIX["h"]
        ref = I.ColumnReference(mechanical=mechanical(hb, FIX["hkey"]), thermal=thermal_side(ht, FIX["hinputs"]))
        self.assertEqual((ref.closure, ref.gravity_m_s2, ref.density_kg_m3), (I.SUPPLIED, None, None))
        materials, ids = cohorts([h["layer"]], UNIFORM_ORIGIN)
        state = I.initial_state(identity=identity(scenario_id="cases/i01_column_heat_v1.json#homogeneous-order-4"),
                                start_time_s=START, frame_id=FRAME, reference=ref, settings=settings(),
                                theta0_k=np.zeros(hb.size), kappa0=np.full(hb.size, float(h["initial_history"])),
                                materials=materials, layer_cohorts=ids, reservoirs=None, reservoir_basis=None)
        self.assertIsNone(state.reference_mass_kg_m)
        self.assertEqual(state.reference.thermal_density_kg_m3.tobytes(),
                         np.asarray(ht.reference_density_kg_m3).tobytes())
        declared = {entry["name"]: entry for entry in state.declaration()}
        self.assertFalse(declared["reference_density_kg_m3"]["known"] or declared["reference_mass_kg_m"]["known"])
        self.assertTrue(declared["thermal_density_kg_m3"]["known"])
        unknown = {entry["name"] for entry in state.unknown()}
        expected = {"elastic_stress_pa", "melt_fraction", "absolute_elevation_m", "global_position",
                    "lateral_structure", "external_loads_pa", "velocity_start_m_s", "column_force_start_n_m",
                    "finite_reservoirs", "reference_density_kg_m3", "reference_mass_kg_m"}
        self.assertLessEqual(expected | {"extrema."+name for name in I.EXTREMA}, unknown)
        self.assertFalse(any(entry["status"] == "required" for entry in state.unknown()))
        self.assertEqual(state.descriptor()["reference"]["unknown"], ["reference_density_kg_m3", "reference_mass_kg_m"])
        self.assertTrue(all(cohort.formation_time_s is None for cohort in state.materials.cohorts))
        self.assertFalse(hasattr(state, "elastic_stress_pa") or hasattr(state.column, "elastic_stress_pa"))
        with self.assertRaises(TectonicsError):              # the preparation's NaN density must be declared unknown
            I.ColumnReference(mechanical=dict(mechanical(hb, FIX["hkey"]), density=hb.density),
                              thermal=thermal_side(ht, FIX["hinputs"]))


class OwnershipTests(Limited):
    def test_public_base_descriptors_cannot_mutate_retained_state(self):
        state = build()
        accessors = ((state.reference, (
            "layer_thickness_m", "point_layer", "depth_m", "weight_m", "overburden_pa", "density_kg_m3",
            "steady_temperature_k", "capacity_j_m2_k", "radiogenic_w_m2", "thermal_density_kg_m3")),
            (state.column, ("theta_k", "initial_theta_k", "kappa", "initial_kappa", "yield_stage_counts")))
        before = state.identities(), state.descriptor()
        for part, names in accessors:
            for name in names:
                with self.subTest(name):
                    value = getattr(part, name)
                    expected = value.shape, value.dtype, value.tobytes()
                    # Mutate every publicly reachable ndarray descriptor, not only the outer view.
                    cursor = value
                    while isinstance(cursor, np.ndarray):
                        cursor.shape = (1, cursor.size)
                        cursor.dtype = np.uint8
                        cursor = cursor.base
                    actual = getattr(part, name)
                    self.assertEqual((actual.shape, actual.dtype, actual.tobytes()), expected)
                    self.assertTrue(np.shares_memory(actual, value))   # payload still reused, not copied
        self.assertEqual((state.identities(), state.descriptor()), before)

    def test_caller_mutation_cannot_reach_the_envelope(self):
        base, thermal = FIX["base"], FIX["thermal"]
        key, rebuild = copy.deepcopy(FIX["key"]), copy.deepcopy(FIX["rebuild"])
        mech = mechanical(base, key, **{name: np.array(getattr(base, name))
                                        for name in ("layer", "depth_m", "weight", "reference_pa", "density")})
        therm = thermal_side(thermal, rebuild, **{name: np.array(getattr(thermal, name)) for name in (
            "layer", "depth_m", "volume_m", "reference_density_kg_m3", "capacity", "radiogenic", "steady_k")})
        rep, pol = copy.deepcopy(SPEC["representation"]), copy.deepcopy(SPEC["policy"])
        law, drive = dataclasses.asdict(LAW), dataclasses.asdict(DRIVE)
        plan, fractions = dict(duration_s=SPEC["drive"]["duration_s"], steps=16), list(CTX["heat"]["heat_fractions"])
        theta, kappa = theta_signed(base), np.array(w.initial_history(base, CTX["weak"]))
        state = build(ref=I.ColumnReference(mechanical=mech, thermal=therm),
                      sett=I.ColumnSettings(representation=rep, law=law, drive=drive, heat_fractions=fractions,
                                            policy=pol, schedule=plan), theta=theta, kappa=kappa)

        def snapshot():
            return (state.state_id, json.dumps(state.descriptor(), sort_keys=True),
                    *(a.tobytes() for a in (state.column.theta_k, state.column.kappa, state.reference.depth_m,
                                            state.reference.point_layer, state.reference.capacity_j_m2_k,
                                            state.reference.steady_temperature_k)))
        before = snapshot()
        for array in (*(v for v in (*mech.values(), *therm.values()) if isinstance(v, np.ndarray)), theta, kappa):
            array[...] = 7
        key[0][0]["thickness_m"], key[0][1]["creep"][0]["n"] = 1., 9.
        rebuild["props"][0]["conductivity_w_m_k"], rebuild["boundaries"]["top"]["value_k"] = 99., 1.
        rep["control"], rep["stretch_window"][1], pol["max_steps"], pol["oracle_order_range"][0] = "edited", 9., 1, 0.
        law["start"], drive["width_m"], plan["steps"], fractions[0] = 99., 1., 1, 0.
        self.assertEqual(snapshot(), before)
        for array in (state.column.theta_k, state.column.kappa, state.reference.depth_m, state.reference.point_layer,
                      state.column.yield_stage_counts):
            with self.assertRaises(ValueError):
                array[0] = 1
            with self.assertRaises(ValueError):
                array.setflags(write=True)
        view = state.reference.depth_m
        view.shape = (1, base.size)
        self.assertEqual(state.reference.depth_m.shape, (base.size,))
        detached = state.descriptor()
        detached["clock"]["elapsed_s"] = 5.
        detached["reference"]["pinned_preparation"]["layers"][0]["thickness_m"] = 1.
        pinned = state.reference.preparation_key()
        pinned[0][0]["thickness_m"] = 1.
        policy, accounts = state.settings.policy(), state.column.accounts_j_m
        policy["max_steps"], accounts["heat_j_m"] = 1, 1.
        self.assertEqual(snapshot(), before)
        self.assertEqual(state.reference.preparation_key()[0][0]["thickness_m"], FIX["key"][0][0]["thickness_m"])
        self.assertEqual((state.settings.policy()["max_steps"], state.column.accounts_j_m["heat_j_m"]), (256, 0.))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            state.state_id = "edited"
        with self.assertRaises(TypeError):
            pickle.dumps(state)
        with self.assertRaises(TypeError):
            dataclasses.replace(state.reference)
        with self.assertRaises(TypeError):
            I.CommonState()
        with self.assertRaises(TypeError):
            I.ColumnState()
        self.assertIs(copy.deepcopy(state), state)

    def test_nonfinite_and_malformed_input_cannot_enter_through_aliases(self):
        base, thermal, key, rebuild = FIX["base"], FIX["thermal"], FIX["key"], FIX["rebuild"]
        nan_theta = theta_signed(base)
        nan_theta[3] = np.nan
        buffer = np.array(thermal.steady_k)
        buffer[0] = np.inf
        infinite = buffer.view()
        infinite.setflags(write=False)                     # read-only view of a writable, nonfinite owner
        nan_layers = copy.deepcopy(key[0])
        nan_layers[0]["thickness_m"] = float("nan")
        masked = np.ma.masked_array(np.zeros(base.size), mask=[True]+[False]*(base.size-1))
        self.refuses({
            "nan_departure": lambda: build(theta=nan_theta),
            "infinite_steady_through_read_only_alias": lambda: reference(therm=thermal_side(
                thermal, rebuild, steady_k=infinite)),
            "nan_capacity": lambda: reference(therm=thermal_side(thermal, rebuild, capacity=np.full(base.size, np.nan))),
            "nan_pinned_input": lambda: reference(mech=mechanical(base, (nan_layers, *key[1:]))),
            "boolean_history": lambda: build(kappa=np.ones(base.size, dtype=bool)),
            "text_history": lambda: build(kappa=["2"]*base.size),
            "masked_departure": lambda: build(theta=masked),
            "two_dimensional_departure": lambda: build(theta=np.zeros((base.size, 1))),
            "negative_history": lambda: build(kappa=-w.initial_history(base, CTX["weak"])),
            "fractional_layer_indices": lambda: reference(mech=mechanical(
                base, key, layer=np.asarray(base.layer, dtype=float))),
            "boundary_temperature_shape": lambda: reference(therm=thermal_side(
                thermal, rebuild, boundary_temperature=(273.,))),
        })
        writable = np.array(base.depth_m)
        alias = writable.view()
        alias.setflags(write=False)                        # an unchecked alias: detached, not borrowed
        ref = reference(mech=mechanical(base, key, depth_m=alias))
        writable[:] = 0.
        self.assertEqual(ref.depth_m.tobytes(), np.asarray(base.depth_m).tobytes())
        self.assertFalse(np.shares_memory(ref.depth_m, writable))
        # Proven immutable native payloads are reused without another copy.
        self.assertTrue(np.shares_memory(reference().depth_m, base.depth_m))

    def test_resources_and_references_survive_and_admission_is_not_conferred(self):
        base, thermal, key = FIX["base"], FIX["thermal"], FIX["key"]
        tiny = WorkBudget(4096)
        with self.assertRaises(MemoryLimitError):
            reference(budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)
        ample = WorkBudget(64 << 20)
        state = build(ref=reference(budget=ample), budget=ample)
        self.assertEqual(ample.reserved_bytes, 0)
        self.assertGreater(ample.peak_reserved_bytes, 0)
        s = state.settings
        self.assertEqual((s.max_steps, s.maximum_seconds, s.steps, s.duration_s, state.column.accepted_steps),
                         (256, SPEC["policy"]["maximum_seconds"], 16, SPEC["drive"]["duration_s"], 0))
        self.assertEqual(s.step_s, SPEC["drive"]["duration_s"]/16)
        self.assertEqual(s.policy(), SPEC["policy"])
        self.assertEqual(s.window_mapping(), fs.declared_window(SPEC))
        self.assertEqual(s.temperature_step_k, SPEC["representation"]["max_temperature_step_k"])
        self.assertEqual(s.drive_parameters, (DRIVE.force_n_m, DRIVE.drag_pa_s, DRIVE.width_m))
        self.assertEqual(s.law_parameters, (LAW.start, LAW.end, LAW.cohesion_factor, LAW.friction_factor))
        self.assertEqual(s.heat_fractions, tuple(CTX["heat"]["heat_fractions"]))
        # The carried references rebuild bitwise through the retained preparation: the I02.2 seam.
        layers, order, closure, gravity = state.reference.preparation_key()
        again = w.prepare(layers, order, closure=closure, gravity=gravity)
        self.assertEqual(again.fingerprint, base.fingerprint)
        for mine, theirs in ((state.reference.depth_m, again.depth_m), (state.reference.weight_m, again.weight),
                             (state.reference.overburden_pa, again.reference_pa),
                             (state.reference.density_kg_m3, again.density)):
            self.assertEqual(mine.tobytes(), np.asarray(theirs).tobytes())
        inputs = state.reference.thermal_inputs()
        rebuilt = heat.prepare_thermal(again.layer, again.depth_m, again.weight, inputs["thicknesses"],
                                       inputs["props"], inputs["densities"], inputs["boundaries"],
                                       reference_temperature=inputs["reference_temperature"],
                                       mechanical_fingerprint=again.fingerprint)
        self.assertEqual(rebuilt.fingerprint, state.reference.thermal_fingerprint)
        for mine, theirs in ((state.reference.steady_temperature_k, rebuilt.steady_k),
                             (state.reference.capacity_j_m2_k, rebuilt.capacity),
                             (state.reference.radiogenic_w_m2, rebuilt.radiogenic)):
            self.assertEqual(mine.tobytes(), np.asarray(theirs).tobytes())
        self.assertIsNotNone(fs.paired(again, rebuilt, modes=None, conduction=True, rebuild=None,
                                       inputs=state.reference.preparation_key()))
        self.assertEqual(w.fingerprint(*key), base.fingerprint)
        self.assertTrue(heat.valid_thermal(thermal))
        # Wrapping the state issues nothing to the finite-admission tool.
        scope = dict(window=fs.declared_window(SPEC), horizon_s=SPEC["drive"]["duration_s"])
        with self.assertRaisesRegex(ValueError, "committed finite-strain state"):
            fa.prepare(base, thermal, LAW, DRIVE, key, state, **scope)
        with self.assertRaisesRegex(ValueError, "committed finite-strain state"):
            fa.issued(state, base, thermal, LAW, DRIVE)
        built = fa.State(state.column.stretch, state.column.elapsed_s, state.current_width_m, state.current_thickness_m,
                         state.column.kappa, state.column.theta_k, state.reference.mechanical_fingerprint)
        with self.assertRaisesRegex(ValueError, "not issued"):
            fa.prepare(base, thermal, LAW, DRIVE, key, built, **scope)
        self.assertEqual((state.admission, state.descriptor()["admission"]), (I.NOT_CONFERRED, I.NOT_CONFERRED))
        self.assertFalse(hasattr(state, "evolution"))


if __name__ == "__main__":
    unittest.main()
