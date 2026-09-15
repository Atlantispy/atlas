"""Bounded scene and persistence tests; all written artefacts stay in tempdirs.

These verify numerical plumbing and engineering identity, never physical or
Diadem approval. The known unsupported near-flat soil/channel case is retained
as a rejection regression; the working integration test declares a plane.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import fixtures
import workflow as w


def selected(name):
    return next(r for r in fixtures.suite() if r["scenario_id"] == name)


def flat_scene():
    r = selected("gentle_plain_zero_forcing")
    r["operations"][0]["steps"] = 1
    return r


def soil_plane():
    r = selected("weathering_to_soil_to_channels")
    # Explicit alternative geometry, not a repair to the retained fixture.
    r["initial"]["bedrock_m"] = [10. + .1 * (4 - i // 4) for i in range(16)]
    r["operations"][1]["dt_years"] = .01
    return r


class SceneTests(unittest.TestCase):
    def assert_unapproved(self, result):
        self.assertIs(result["production_authorised"], False)
        self.assertIs(result["diadem_canon_changed"], False)
        self.assertEqual(result["status"], "NUMERICAL_REFERENCE_NOT_PHYSICAL_ACCEPTANCE")
        self.assertEqual(result["gates"]["whole_model_B"], "INCOMPLETE")
        self.assertEqual(result["gates"]["physical_C"], "INCOMPLETE")
        for gate in ("optimisation_D", "production_E", "adoption_F"):
            self.assertEqual(result["gates"][gate], "NOT_RUN")
        self.assertEqual(result["downstream_invalidation"]["status"],
                         "REQUIRED_IF_ADOPTED_NO_PRODUCTS_REBUILT")

    def test_suite_is_independent_complete_coverage_and_valid_metadata(self):
        recipes = fixtures.suite()
        self.assertEqual(len(recipes), 9)
        self.assertEqual(len({r["scenario_id"] for r in recipes}), 9)
        for recipe in recipes:
            with self.subTest(scenario=recipe["scenario_id"]):
                state = w.validate_recipe(recipe)
                self.assertEqual(state.grid.size, len(recipe["initial"]["bedrock_m"]))
                self.assertEqual(set(recipe["coverage"]),
                                 {f"L{i:02d}" for i in range(1, 12)} | {"additional"})
        before = w.canonical(recipes[1])
        recipes[0]["initial"]["bedrock_m"][0] = -123.
        recipes[0]["coverage"]["L01"]["reason"] = "mutated"
        self.assertEqual(w.canonical(recipes[1]), before)

    def test_supported_suite_scenes_repeat_exactly_without_mutating_recipes(self):
        for recipe in fixtures.suite():
            with self.subTest(scenario=recipe["scenario_id"]):
                original = w.canonical(recipe)
                a, b = w.execute(recipe), w.execute(recipe)
                self.assertEqual(w.canonical(a), w.canonical(b))
                self.assertEqual(w.canonical(recipe), original)
                self.assert_unapproved(a)
                self.assertEqual(len(a["state"]["surface_m"]),
                                 recipe["grid"]["rows"] * recipe["grid"]["cols"])

    def test_known_near_flat_soil_channel_scene_rejects_link_step(self):
        recipe = fixtures.near_flat_capture_regression()
        original = w.canonical(recipe)
        with self.assertRaisesRegex(ValueError, "link relief"):
            w.execute(recipe)
        self.assertEqual(w.canonical(recipe), original)

    def test_flat_no_forcing_preserves_actual_surface_and_stocks_exactly(self):
        recipe = flat_scene()
        state = w.validate_recipe(recipe)
        result = w.execute(recipe)
        self.assertEqual(result["state"]["surface_m"], list(state.surface_m))
        self.assertEqual(result["state"]["bedrock_m"], list(state.bedrock_m))
        self.assertEqual(result["state"]["mobile_solid_m3"], list(state.mobile_solid_m3))
        self.assertEqual(result["change_m"], [0.] * state.grid.size)
        self.assertEqual(result["gradients"]["grade_m_per_m"], [0.] * state.grid.size)

    def test_planar_soil_to_channels_tracks_rock_mobile_and_dissolved_stocks(self):
        recipe = soil_plane()
        initial = w.validate_recipe(recipe)
        result = w.execute(recipe)
        self.assert_unapproved(result)
        transfers = result["operations"][0]["transfers"]
        self.assertGreater(math.fsum(t["rock_consumed_kg"] for t in transfers), 0.)
        self.assertGreater(math.fsum(t["dissolved_rock_produced_kg"] for t in transfers), 0.)
        for t in transfers:
            self.assertAlmostEqual(t["rock_consumed_kg"],
                                   t["mobile_produced_kg"] + t["regolith_produced_kg"] +
                                   t["dissolved_rock_produced_kg"], places=11)
        rock_loss = math.fsum((old - new) * initial.grid.area_m2 * 2700.
                             for old, new in zip(initial.bedrock_m, result["state"]["bedrock_m"]))
        mobile_gain = (math.fsum(result["state"]["mobile_solid_m3"]) -
                       math.fsum(initial.mobile_solid_m3)) * 2700.
        dissolved = math.fsum(t["dissolved_rock_produced_kg"] for t in transfers)
        export = result["unconsumed_channel_boundary_transfer"]["solid_m3"] * 2700.
        self.assertAlmostEqual(rock_loss, mobile_gain + dissolved + export, places=7)
        prefix = deepcopy(recipe); prefix["operations"] = prefix["operations"][:1]
        soil_only = w.execute(prefix)
        # The stock ledger debits each ordered operation. A single combined
        # subtraction has a different rounding order at a 1e9 kg initial stock.
        for before, after, old_stock, remaining in zip(soil_only["state"]["bedrock_m"], result["state"]["bedrock_m"],
                soil_only["finite_rock_remaining_kg"], result["finite_rock_remaining_kg"]):
            self.assertEqual(remaining, old_stock - (before - after) * initial.grid.area_m2 * 2700.)

    def test_linked_receiver_consumes_channel_export_once_and_preserves_water(self):
        recipe = selected("upland_to_submerged_receiver")
        prefix = deepcopy(recipe); prefix["operations"] = prefix["operations"][:1]
        upstream = w.execute(prefix)
        result = w.execute(recipe)
        linked = result["operations"][-1]
        source = upstream["unconsumed_channel_boundary_transfer"]
        self.assertEqual(linked["internal_transfer_from_channels"], source)
        self.assertEqual(result["unconsumed_channel_boundary_transfer"], {"solid_m3": 0., "water_m3": 0.})
        cells = linked["cells"]
        self.assertAlmostEqual(math.fsum(c["supplied_solid_m3"] for c in cells), source["solid_m3"])
        self.assertAlmostEqual(math.fsum(c["deposited_solid_m3"] + c["exported_solid_m3"] for c in cells), source["solid_m3"])
        for i, (old, new) in enumerate(zip(upstream["state"]["mobile_solid_m3"], result["state"]["mobile_solid_m3"])):
            deposited = math.fsum(c["deposited_solid_m3"] for c in cells if c["cell"] == i)
            self.assertAlmostEqual(new - old, deposited, places=10)
        recipe["operations"].append(deepcopy(recipe["operations"][-1]))
        repeated = w.execute(recipe)
        self.assertEqual(repeated["operations"][-1]["internal_transfer_from_channels"], {"solid_m3": 0., "water_m3": 0.})
        self.assertEqual(repeated["state"], result["state"])
        water_input = math.fsum(s["channel"]["water_input_m3"] for s in result["operations"][0]["steps"])
        stored = math.fsum(s["channel"]["unresolved_terminal_water_storage_m3"] for s in result["operations"][0]["steps"])
        self.assertAlmostEqual(source["water_m3"] + stored, water_input, places=9)

    def test_linked_receiver_rejects_independent_supply_and_fraction_reset(self):
        for change in ({"incoming_solid_m3_per_year": 10.},
                       {"water_discharge_m3_per_year": 10.}, {"fraction": .5}):
            recipe = selected("upland_to_submerged_receiver")
            recipe["operations"][-1]["parameters"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                w.execute(recipe)

    def test_dissolution_solid_water_and_finite_substrate_accounting(self):
        recipe = selected("carbonate_dissolved_export")
        initial = w.validate_recipe(recipe)
        result = w.execute(recipe)
        for i, t in enumerate(result["operations"][0]["transfers"]):
            self.assertEqual(t["carrier_water_input_m3"], t["carrier_water_output_m3"])
            self.assertAlmostEqual(t["rock_consumed_kg"], t["dissolved_rock_output_kg"] - t["dissolved_rock_input_kg"], places=14)
            self.assertEqual(result["state"]["mobile_solid_m3"][i], initial.mobile_solid_m3[i])
            self.assertAlmostEqual((initial.bedrock_m[i] - result["state"]["bedrock_m"][i]) * initial.grid.area_m2,
                                   t["rock_solid_removed_m3"], places=12)
        recipe["operations"].append(deepcopy(recipe["operations"][0]))
        with self.assertRaisesRegex(ValueError, "finite rock inventory reset"):
            w.execute(recipe)

    def test_organic_compaction_preserves_solids_and_expels_only_pore_water(self):
        recipe = selected("organic_accumulation_compaction")
        initial = w.validate_recipe(recipe)
        result = w.execute(recipe)
        layer = result["auxiliary_layers"]["organic"]
        self.assertEqual(result["state"]["bedrock_m"], list(initial.bedrock_m))
        self.assertEqual(result["state"]["mobile_solid_m3"], list(initial.mobile_solid_m3))
        for i, (growth, compact) in enumerate(zip(result["operations"][0]["transfers"], result["operations"][1]["transfers"])):
            self.assertEqual(compact["solid_volume_m3"], growth["solid_volume_after_m3"])
            self.assertEqual(layer["organic_kg"][i], growth["organic_after_kg"])
            self.assertEqual(layer["mineral_kg"][i], growth["mineral_after_kg"])
            self.assertAlmostEqual(growth["organic_input_kg"], growth["organic_after_kg"] + growth["decomposed_organic_origin_kg"], places=12)
            self.assertAlmostEqual(growth["pore_water_before_m3"] + growth["external_water_supplied_m3"],
                                   growth["water_output_m3"] + compact["expelled_water_m3"] + compact["pore_water_after_m3"], places=14)
            expected = initial.surface_m[i] + compact["bulk_volume_after_m3"] / initial.grid.area_m2
            self.assertEqual(result["state"]["surface_m"][i], expected)

    def test_basin_uses_real_auxiliary_layer_and_cannot_publish_stale_depth(self):
        recipe = selected("organic_accumulation_compaction")
        recipe["initial"]["bedrock_m"] = [0.] * 4
        recipe["initial"]["mobile_solid_m3"] = [0.] * 4
        basin = {"kind": "basin", "basins": [{"id": "peat-water", "cell_indices": [0, 1, 2, 3],
                    "children": [], "spill_m": 1., "spill_to_leaf": None}], "leaf_water_m3": {"peat-water": 100.}}
        recipe["operations"].insert(1, basin)
        result = w.execute(recipe)
        operation_water = result["operations"][1]["result"]
        organic = result["operations"][0]["transfers"]
        for i, depth in enumerate(operation_water["water_depth_m"]):
            self.assertAlmostEqual(operation_water["water_surface_m"][i], depth + organic[i]["bulk_volume_after_m3"] / 100., places=13)
        # A later material operation may invalidate this field or recompute it,
        # but the final output must never present old depth on a changed bed.
        if result["water"] is not None:
            for i, depth in enumerate(result["water"]["water_depth_m"]):
                if depth > 0:
                    self.assertAlmostEqual(result["water"]["water_surface_m"][i],
                                           result["state"]["surface_m"][i] + depth, places=13)

    def test_basin_exact_storage_is_separate_from_physical_bed(self):
        recipe = selected("nested_basin_partial_and_spill")
        result = w.execute(recipe)
        self.assertEqual(result["state"]["bedrock_m"], recipe["initial"]["bedrock_m"])
        self.assertEqual(result["water"]["input_volume_m3"], 13.)
        self.assertAlmostEqual(result["water"]["stored_volume_m3"], 13.)
        self.assertEqual(result["water"]["exported_volume_m3"], 0.)
        self.assertEqual(result["water"]["merged_basins"], ["joined"])
        self.assertIs(result["water"]["hierarchy_geometry_independently_verified"], False)

    def test_layered_state_rejects_unrepresented_inventory_or_erosion(self):
        recipe = selected("organic_accumulation_compaction")
        recipe["operations"][0]["organic_kg"][0] = 1.
        with self.assertRaisesRegex(ValueError, "zero initial inventory"):
            w.execute(recipe)
        recipe = selected("organic_accumulation_compaction")
        recipe["operations"].append(deepcopy(recipe["operations"][0]))
        with self.assertRaisesRegex(ValueError, "previous layer inventories"):
            w.execute(recipe)
        recipe = selected("organic_accumulation_compaction")
        recipe["operations"].append(flat_scene()["operations"][0])
        with self.assertRaisesRegex(ValueError, "organic/immobile layers"):
            w.execute(recipe)

    def test_constructive_sequence_debits_shared_bed_and_mobile_material(self):
        recipe = selected("ice_to_tephra_to_wind")
        initial = w.validate_recipe(recipe)
        result = w.execute(recipe)
        glacial, tephra, wind = [r["result"] for r in result["operations"]]
        bed_loss = math.fsum((b - a) * 100. for b, a in zip(initial.bedrock_m, result["state"]["bedrock_m"]))
        self.assertAlmostEqual(bed_loss, glacial["ledger"]["eroded_solid_m3"], places=12)
        supplied = tephra["ledger"]["external_supply_solid_m3"]
        export = math.fsum(op["result"]["ledger"]["exported_solid_m3"] for op in result["operations"])
        self.assertAlmostEqual(bed_loss + supplied,
                               math.fsum(result["state"]["mobile_solid_m3"]) + export, places=12)
        self.assertGreater(wind["ledger"]["eroded_solid_m3"], 0.)
        for i, surface in enumerate(result["state"]["surface_m"]):
            self.assertEqual(surface, result["state"]["bedrock_m"][i] + result["state"]["mobile_solid_m3"][i] / 60.)

    def test_positive_north_wind_agrees_with_south_positive_scene_grid(self):
        recipe = selected("ice_to_tephra_to_wind")
        wind = deepcopy(recipe["operations"][-1])
        wind["parameters"].update(receivers=[-1, -1, -1, 0, 1, 2],
                                  friction_velocity_east_m_s=[0.] * 6,
                                  friction_velocity_north_m_s=[.6] * 6)
        recipe["initial"]["mobile_solid_m3"] = [60.] * 6
        recipe["operations"] = [wind]
        result = w.execute(recipe)
        self.assertGreater(result["operations"][0]["result"]["ledger"]["exported_solid_m3"], 0.)
        self.assertEqual(result["state"]["bedrock_m"], recipe["initial"]["bedrock_m"])

    def test_tephra_position_wind_and_nonzero_grid_origin_roundtrip(self):
        recipe = selected("ice_to_tephra_to_wind")
        recipe["grid"].update(origin_x_m=100., origin_y_m=200.)
        tephra = deepcopy(recipe["operations"][1])
        tephra["parameters"].update(origin_x_m=100., origin_y_m=200., vent_x_m=115., vent_y_m=205.,
                                     wind_x_m_s=0., wind_y_m_s=1., fall_time_s=5., diffusivity_m2_s=1.)
        recipe["operations"] = [tephra]
        result = w.execute(recipe)["operations"][0]["result"]
        self.assertEqual(result["gaussian_mean_m"], [115., 210.])
        self.assertEqual(result["delivered_frame"], "synthetic_local_m_x_east_y_south")
        # Mean lies on the row boundary: north and south row probabilities
        # agree and the central column retains most of the supplied material.
        amounts = result["deposited_solid_m3_by_cell"]
        for col in range(3): self.assertAlmostEqual(amounts[col], amounts[col + 3], places=14)
        self.assertGreater(amounts[1], amounts[0])
        self.assertGreater(amounts[4], amounts[5])

    def test_material_density_and_porosity_cannot_change_via_operation(self):
        recipe = selected("ice_to_tephra_to_wind")
        recipe["operations"] = recipe["operations"][-1:]
        recipe["operations"][0]["parameters"]["grain_density_kg_m3"] = 1000.
        with self.assertRaisesRegex(ValueError, "density"): w.execute(recipe)
        recipe = selected("ice_to_tephra_to_wind")
        recipe["operations"][0]["parameters"]["bedrock_porosity"] = .2
        with self.assertRaisesRegex(ValueError, "nonporous"): w.execute(recipe)
        recipe = selected("organic_accumulation_compaction")
        prefix = deepcopy(recipe); prefix["operations"] = prefix["operations"][:1]
        layer = w.execute(prefix)["auxiliary_layers"]["organic"]
        continued = deepcopy(prefix["operations"][0])
        for key in ("organic_kg", "mineral_kg", "void_ratio"): continued[key] = layer[key]
        continued["parameters"]["organic_grain_density_kg_m3"] = 2000.
        prefix["operations"].append(continued)
        with self.assertRaisesRegex(ValueError, "grain densities"): w.execute(prefix)

    def test_constraints_apply_to_final_layered_surface_not_bare_bedrock(self):
        recipe = selected("organic_accumulation_compaction")
        before = w.validate_recipe(recipe).surface_m[0]
        recipe["constraints"] = [{"id": "held-surface", "cell": 0, "minimum_m": before,
                                  "maximum_m": before, "role": "hard", "reason": "synthetic exact surface",
                                  "source_status": "SYNTHETIC", "source_sha256": "a" * 64, "owner": "Engineering test"}]
        with self.assertRaisesRegex(ValueError, "held-surface"): w.execute(recipe)

    def test_rejects_production_status_frame_and_coverage_bypasses(self):
        mutations = [lambda r: r.update(purpose="PRODUCTION"),
                     lambda r: r.update(source_status="CANON"),
                     lambda r: r["initial"].update(source_status="CANON"),
                     lambda r: r.update(production_authorised=True),
                     lambda r: r.update(schema="diadem.terrain.production"),
                     lambda r: r["grid"].update(frame="Diadem_km"),
                     lambda r: r["grid"].update(vertical_datum="approved_sea_level"),
                     lambda r: r["coverage"].pop("L05"),
                     lambda r: r["coverage"]["L05"].update(status="PASS"),
                     lambda r: r["coupling"].update(mode="FULLY_VALIDATED"),
                     lambda r: r.update(parameter_evidence=[]),
                     lambda r: r.update(operations=[]),
                     lambda r: r.update(operations=[{"kind": "production"}])]
        for i, change in enumerate(mutations):
            recipe = flat_scene(); change(recipe)
            with self.subTest(mutation=i), self.assertRaises((ValueError, TypeError)):
                w.execute(recipe)

    def test_finite_numeric_typed_limits_and_operation_caps(self):
        for value in (0, -1, True, math.inf, math.nan, 10**1000):
            recipe = flat_scene(); recipe["limits"]["max_cells"] = value
            with self.subTest(value=str(value)[:20]), self.assertRaises(ValueError):
                w.execute(recipe)
        for key, value in (("max_cells", 15), ("max_steps", 1), ("max_cell_steps", 15)):
            recipe = flat_scene(); recipe["operations"][0]["steps"] = 2
            recipe["limits"][key] = value
            with self.subTest(limit=key), self.assertRaises(ValueError):
                w.execute(recipe)
        recipe = flat_scene(); recipe["operations"] *= 65
        with self.assertRaises(ValueError): w.execute(recipe)
        recipe = flat_scene(); recipe["operations"][0]["_deadline"] = math.inf
        with self.assertRaises(ValueError): w.execute(recipe)
        recipe = flat_scene()
        with patch.object(w.time, "monotonic", side_effect=[0., 121.]), self.assertRaisesRegex(ValueError, "wall-time"):
            w.execute(recipe)

    def test_last_operation_cannot_overrun_declared_wall_envelope(self):
        recipe = selected("organic_accumulation_compaction")
        recipe["operations"] = recipe["operations"][:1]
        values = iter((0., 0.))
        # Deadline creation and first operation start are in budget; all later
        # reads report expiration. A final check is necessary for the last op.
        with patch.object(w.time, "monotonic", side_effect=lambda: next(values, 121.)), \
                self.assertRaisesRegex(ValueError, "wall-time"):
            w.execute(recipe)

    def test_scientific_state_override_and_forcing_extrapolation_rejected(self):
        for key, value in (("rows", 2), ("bed_elevation_m", [0.] * 6), ("cell_size_m", 1.)):
            recipe = selected("ice_to_tephra_to_wind")
            recipe["operations"][0]["parameters"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): w.execute(recipe)
        recipe = selected("organic_accumulation_compaction")
        recipe["coupling"]["terrain_forcing_max_change_m"] = 0.
        with self.assertRaisesRegex(ValueError, "sensitivity envelope"):
            w.execute(recipe)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.here = self.root / "work" / "terrain_model_r2"
        self.here.mkdir(parents=True)
        # Fake implementation inventory permits isolated identity-mutation
        # tests; no actual source or shared workspace file is ever changed.
        (self.here / "fixture.py").write_bytes(b"x")
        (self.here / "METHODS.md").write_bytes(b"synthetic test implementation closure")
        self.patch_here = patch.object(w, "HERE", self.here)
        self.patch_here.start(); self.addCleanup(self.patch_here.stop)
        self.recipe_path = self.root / "recipe.json"
        self.recipe = flat_scene()
        self.recipe_path.write_bytes(w.canonical(self.recipe))
        self.original_recipe = self.recipe_path.read_bytes()
        self.original_implementation = {p.name: p.read_bytes() for p in self.here.iterdir()}
        self.output = self.root / "outputs" / "terrain-model-r2-repair-r1" / "scene"

    def committed(self):
        report = w.run(self.recipe_path, self.output)
        receipt = w.read_json(self.output / "RECEIPT.json")
        return report, receipt

    def assert_sources_unchanged(self):
        self.assertEqual(self.recipe_path.read_bytes(), self.original_recipe)
        self.assertEqual({p.name: p.read_bytes() for p in self.here.iterdir()}, self.original_implementation)

    def pending(self):
        matches = list(self.output.parent.glob("scene.pending-*"))
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_commit_and_verified_reuse_bind_real_scene_and_all_products(self):
        report, receipt = self.committed()
        self.assertEqual(report["status"], "COMMITTED_BOUNDED_REFERENCE")
        self.assertIs(report["production_authorised"], False)
        self.assertEqual({p.name for p in self.output.iterdir()}, {"RECIPE.json", "RESULT.json", "RECEIPT.json"})
        self.assertEqual(w.read_bytes(self.output / "RESULT.json"), w.canonical(w.execute(self.recipe)))
        self.assertEqual(receipt["identity"]["recipe_sha256"], hashlib.sha256(self.original_recipe).hexdigest())
        with patch.object(w, "execute", side_effect=AssertionError("verified reuse must not recompute")):
            reused = w.run(self.recipe_path, self.output, resume=True)
        self.assertEqual(reused["status"], "VERIFIED_REUSE")
        self.assertEqual(reused["generation_id"], report["generation_id"])
        self.assert_sources_unchanged()

    def test_existing_output_and_atomic_json_never_overwrite(self):
        self.committed()
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        with self.assertRaises(FileExistsError): w.run(self.recipe_path, self.output)
        with self.assertRaises(FileExistsError): w.write_json_new(self.output / "RESULT.json", {"wrong": True})
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, before)
        self.assert_sources_unchanged()

    def test_output_containment_and_recipe_ancestor_rejected(self):
        for output in (self.root / "foreign", self.root, self.output.parent,
                       self.root / "outputs" / "terrain-model-r2-other" / "x",
                       self.output.parent / ".." / "escaped"):
            with self.subTest(output=str(output)), self.assertRaises(ValueError):
                w.run(self.recipe_path, output)
        self.assertFalse(self.output.exists())
        self.assert_sources_unchanged()

    def test_mixed_missing_extra_and_corrupt_products_fail_closed(self):
        _, receipt = self.committed()
        expected = receipt["identity"]
        target = self.output / "RESULT.json"
        original = target.read_bytes()
        target.write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "corrupt"): w.verify_generation(self.output, expected)
        target.write_bytes(original)
        extra = self.output / "EXTRA.json"; extra.write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "mixed/extra"): w.verify_generation(self.output, expected)
        extra.unlink()
        target.rename(self.output / "MISSING.json")
        with self.assertRaises(ValueError): w.verify_generation(self.output, expected)
        self.assert_sources_unchanged()

    def test_strict_receipt_identity_rejects_boolean_number_and_signed_zero_aliases(self):
        _, receipt = self.committed()
        original = deepcopy(receipt["identity"])
        changed = deepcopy(original)
        next(p for p in changed["implementation"] if p["name"] == "fixture.py")["bytes"] = True
        self.assertEqual(original, changed)  # Demonstrates Python equality trap.
        with self.assertRaisesRegex(ValueError, "identity"): w.verify_generation(self.output, changed)
        for supplied in (-0., 0.):
            altered = deepcopy(receipt)
            altered["identity"]["probe"] = supplied
            (self.output / "RECEIPT.json").write_bytes(w.canonical(altered))
            expected = deepcopy(altered["identity"]); expected["probe"] = -supplied
            with self.assertRaisesRegex(ValueError, "identity"): w.verify_generation(self.output, expected)

    def test_receipt_cannot_assert_production_or_change_member_inventory(self):
        _, receipt = self.committed()
        for mutation in (lambda r: r.update(production_authorised=True),
                         lambda r: r.update(production_authorised=0),
                         lambda r: r["products"].pop("RESULT.json"),
                         lambda r: r["products"].update({"../elsewhere.json": {"bytes": 0, "sha256": "0" * 64}})):
            altered = deepcopy(receipt); mutation(altered)
            (self.output / "RECEIPT.json").write_bytes(w.canonical(altered))
            with self.assertRaises(ValueError): w.verify_generation(self.output, receipt["identity"])

    def test_product_receipt_pin_requires_strict_integer_bytes(self):
        _, receipt = self.committed()
        receipt["products"]["RESULT.json"]["bytes"] = float(receipt["products"]["RESULT.json"]["bytes"])
        (self.output / "RECEIPT.json").write_bytes(w.canonical(receipt))
        with self.assertRaises(ValueError): w.verify_generation(self.output, receipt["identity"])

    def test_interrupted_sealed_commit_resumes_without_recomputation(self):
        with self.assertRaisesRegex(RuntimeError, "after receipt"):
            w.run(self.recipe_path, self.output, interrupt_at="after_receipt")
        pending = self.pending()
        before = {p.name: p.read_bytes() for p in pending.iterdir()}
        self.assertFalse(self.output.exists())
        with self.assertRaises(FileExistsError): w.run(self.recipe_path, self.output)
        with patch.object(w, "execute", side_effect=AssertionError("sealed reuse must not recompute")):
            report = w.run(self.recipe_path, self.output, resume=True)
        self.assertEqual(report["status"], "COMMITTED_BOUNDED_REFERENCE")
        self.assertFalse(pending.exists())
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, before)
        self.assert_sources_unchanged()

    def test_unsealed_products_reconstruct_and_verify_before_sealing(self):
        with self.assertRaisesRegex(RuntimeError, "after products"):
            w.run(self.recipe_path, self.output, interrupt_at="after_products")
        pending = self.pending()
        before = {p.name: p.read_bytes() for p in pending.iterdir()}
        self.assertEqual(set(before), {"RECIPE.json", "RESULT.json"})
        with patch.object(w, "execute", wraps=w.execute) as execute:
            w.run(self.recipe_path, self.output, resume=True)
        execute.assert_called_once()
        for name, data in before.items(): self.assertEqual((self.output / name).read_bytes(), data)
        self.assert_sources_unchanged()

    def test_corrupt_unsealed_partial_is_preserved_not_repaired(self):
        with self.assertRaises(RuntimeError): w.run(self.recipe_path, self.output, interrupt_at="after_products")
        pending = self.pending()
        target = pending / "RESULT.json"; target.write_bytes(target.read_bytes() + b" ")
        before = {p.name: p.read_bytes() for p in pending.iterdir()}
        with self.assertRaisesRegex(ValueError, "unsealed recovery"):
            w.run(self.recipe_path, self.output, resume=True)
        self.assertEqual({p.name: p.read_bytes() for p in pending.iterdir()}, before)
        self.assertFalse(self.output.exists())
        self.assert_sources_unchanged()

    def test_incomplete_or_foreign_partial_is_not_deleted(self):
        with self.assertRaises(RuntimeError): w.run(self.recipe_path, self.output, interrupt_at="after_products")
        pending = self.pending()
        (pending / "RESULT.json").unlink()
        before = {p.name: p.read_bytes() for p in pending.iterdir()}
        with self.assertRaisesRegex(ValueError, "partial products"):
            w.run(self.recipe_path, self.output, resume=True)
        self.assertEqual({p.name: p.read_bytes() for p in pending.iterdir()}, before)
        self.assertFalse(self.output.exists())

    def test_changed_recipe_or_implementation_refuses_old_identity_on_reuse(self):
        self.committed()
        original_outputs = {p.name: p.read_bytes() for p in self.output.iterdir()}
        self.recipe["scenario_id"] = "different"
        self.recipe_path.write_bytes(w.canonical(self.recipe))
        with self.assertRaisesRegex(ValueError, "identity"): w.run(self.recipe_path, self.output, resume=True)
        self.recipe_path.write_bytes(self.original_recipe)
        (self.here / "new_dependency.py").write_bytes(b"added after run")
        with self.assertRaisesRegex(ValueError, "identity"): w.run(self.recipe_path, self.output, resume=True)
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, original_outputs)

    def test_source_changed_during_construction_refuses_commit(self):
        actual = w.execute
        def changed(recipe):
            result = actual(recipe)
            self.recipe_path.write_bytes(self.original_recipe + b" ")
            return result
        with patch.object(w, "execute", side_effect=changed), self.assertRaisesRegex(ValueError, "source changed"):
            w.run(self.recipe_path, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.parent.exists())

    def test_caller_authorised_recipe_pin_is_checked_before_execution(self):
        with patch.object(w, "execute", side_effect=AssertionError("must reject before execution")), \
                self.assertRaisesRegex(ValueError, "authorisation"):
            w.run(self.recipe_path, self.output, expected_recipe_sha256="0" * 64)
        self.assertFalse(self.output.exists())
        expected = hashlib.sha256(self.original_recipe).hexdigest()
        report = w.run(self.recipe_path, self.output, expected_recipe_sha256=expected)
        self.assertEqual(report["status"], "COMMITTED_BOUNDED_REFERENCE")
        self.assert_sources_unchanged()

    def test_aba_source_read_cannot_bind_a_recipe_but_execute_another(self):
        alternate = deepcopy(self.recipe); alternate["scenario_id"] = "second-read-substitution"
        alternate_bytes = w.canonical(alternate)
        actual_read = w.read_bytes
        calls = []
        def swapped(path, maximum=w.MAX_FILE):
            if Path(path) == self.recipe_path:
                calls.append(path)
                return alternate_bytes if len(calls) == 2 else self.original_recipe
            return actual_read(path, maximum)
        # Both a detected source change and parsing the originally pinned bytes
        # are safe; emitting the alternate scenario under the first pin is not.
        with patch.object(w, "read_bytes", side_effect=swapped):
            try:
                w.run(self.recipe_path, self.output)
            except ValueError:
                pass
        if self.output.exists():
            result = w.read_json(self.output / "RESULT.json")
            self.assertEqual(result["scenario_id"], self.recipe["scenario_id"])
        self.assert_sources_unchanged()

    def test_post_commit_source_check_runs_after_receipt_readback(self):
        original_verify = w.verify_generation
        def changed(directory, identity):
            result = original_verify(directory, identity)
            if directory == self.output:
                self.recipe_path.write_bytes(self.original_recipe + b" ")
            return result
        with patch.object(w, "verify_generation", side_effect=changed), self.assertRaisesRegex(ValueError, "after commit"):
            w.run(self.recipe_path, self.output)
        self.assertTrue((self.output / "RECEIPT.json").is_file())

    def test_racing_existing_output_is_preserved_before_commit(self):
        original_verify = w.verify_generation
        def competing(directory, identity):
            result = original_verify(directory, identity)
            if ".pending-" in directory.name and not self.output.exists():
                self.output.mkdir(); (self.output / "OTHER-WRITER.txt").write_bytes(b"preserve")
            return result
        with patch.object(w, "verify_generation", side_effect=competing), self.assertRaises(FileExistsError):
            w.run(self.recipe_path, self.output)
        self.assertEqual((self.output / "OTHER-WRITER.txt").read_bytes(), b"preserve")
        self.assertTrue((self.pending() / "RECEIPT.json").is_file())
        self.assert_sources_unchanged()

    def test_file_and_total_product_caps_fail_before_commit(self):
        with self.assertRaises(ValueError): w.read_bytes(self.recipe_path, maximum=1)
        with patch.object(w, "MAX_FILE", 1), self.assertRaises(ValueError):
            w.write_json_new(self.root / "too-large.json", {"a": 1})
        self.assertFalse((self.root / "too-large.json").exists())
        self.recipe["limits"]["max_product_bytes"] = 1
        self.recipe_path.write_bytes(w.canonical(self.recipe))
        with self.assertRaisesRegex(ValueError, "product budget"): w.run(self.recipe_path, self.output)
        self.assertFalse(self.output.exists())

    def test_total_budget_includes_receipt_bytes(self):
        # The declared cap must bound every emitted file, not only scientific
        # products. Find the tiny fixed point caused by cap digits in recipe.
        for _ in range(4):
            self.recipe["limits"]["max_product_bytes"] = len(w.canonical(self.recipe)) + len(w.canonical(w.execute(self.recipe)))
        self.recipe_path.write_bytes(w.canonical(self.recipe))
        try:
            w.run(self.recipe_path, self.output)
        except ValueError:
            return
        actual = sum(p.stat().st_size for p in self.output.iterdir())
        self.assertLessEqual(actual, self.recipe["limits"]["max_product_bytes"])

    def test_duplicate_nonfinite_and_noncanonical_numeric_json_rejected(self):
        for data in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}'):
            self.recipe_path.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(ValueError): w.read_json(self.recipe_path)

    def test_symlink_and_windows_reparse_ancestors_fail_closed(self):
        original_is_link = Path.is_symlink
        ancestor = self.output.parent
        def linked(path):
            return path == ancestor or original_is_link(path)
        with patch.object(Path, "is_symlink", linked), self.assertRaisesRegex(ValueError, "linked/reparse"):
            w.run(self.recipe_path, self.output)
        original_stat = Path.stat
        def reparse(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            if path == self.root:
                values = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
                values["st_file_attributes"] = 0x400
                return SimpleNamespace(**values)
            return result
        with patch.object(Path, "stat", reparse), self.assertRaisesRegex(ValueError, "linked/reparse"):
            w.run(self.recipe_path, self.output)
        self.assertFalse(self.output.exists())
        self.assert_sources_unchanged()

    def test_read_rejects_changed_stat_and_write_rejects_readback_corruption(self):
        original_stat = Path.stat
        reads = []
        def changing(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            if path == self.recipe_path:
                reads.append(path)
                values = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
                values["st_mtime_ns"] += len(reads)
                return SimpleNamespace(**values)
            return result
        with patch.object(Path, "stat", changing), self.assertRaisesRegex(ValueError, "changed"):
            w.read_bytes(self.recipe_path)
        target = self.root / "readback.json"
        with patch.object(w, "read_bytes", return_value=b"corrupt"), self.assertRaisesRegex(ValueError, "readback"):
            w.write_json_new(target, {"expected": True})
        self.assertEqual(target.read_bytes(), w.canonical({"expected": True}))


if __name__ == "__main__":
    unittest.main()
