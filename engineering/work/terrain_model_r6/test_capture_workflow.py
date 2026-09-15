"""Adversarial synthetic persistence checks; all writes remain in tempdirs.

HERE is redirected only for the workflow's allowed output root/source-discovery
fixture. Numerical modules and their frozen R2/R3 dependencies remain read-only.
These checks establish no Diadem, shoreline or physical acceptance.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import capture_fixtures
import r4_io


def _fixture_recipes():
    return deepcopy(capture_fixtures.suite())

import capture_workflow as w


def small_recipe():
    r = deepcopy(_fixture_recipes()[0])
    r["scenario_id"] = "peer_closed_column"
    r["forcing"]["steps"] = 3
    r["forcing"]["dt_years"] = .1
    r["limits"]["checkpoint_steps"] = 1
    return r


class DependencyTests(unittest.TestCase):
    def test_predecessor_source_and_release_closures_are_verified(self):
        pins = r4_io.verify_dependencies()
        names = [row['name'] for row in pins]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn('R3/REFERENCE_VERIFICATION.json', names)
        self.assertIn('R2/REFERENCE_VERIFICATION.json', names)
        self.assertIn('R3/capture.py', names)
        self.assertIn('R2/workflow.py', names)
        self.assertTrue(all(type(row['bytes']) is int and row['bytes'] > 0
                            and len(row['sha256']) == 64 for row in pins))

    def test_either_predecessor_receipt_drift_fails_without_source_writes(self):
        read = r4_io.io.read_bytes
        for target in (r4_io.r3_bindings.INDEX, r4_io._r3_io.INDEX):
            def changed(path, *args, **kwargs):
                raw = read(path, *args, **kwargs)
                return raw + b' ' if Path(path) == target else raw
            with self.subTest(path=target), patch.object(r4_io.io, 'read_bytes', changed):
                with self.assertRaisesRegex(ValueError, 'predecessor release identity changed'):
                    r4_io.verify_dependencies()
        r4_io.verify_dependencies()

    def test_cached_r3_capture_cannot_be_admitted_as_r4(self):
        spec = importlib.util.spec_from_file_location('_r4_peer_namespace_check', w.__file__)
        module = importlib.util.module_from_spec(spec)
        previous = SimpleNamespace(__file__=str(r4_io.r3_bindings.R3 / 'capture.py'))
        with patch.dict(sys.modules, {'capture': previous}):
            with self.assertRaisesRegex(ValueError, 'R4 numerical namespace mismatch'):
                spec.loader.exec_module(module)


class ValidationTests(unittest.TestCase):
    def test_nine_fixture_recipes_are_valid_and_independent(self):
        recipes = _fixture_recipes()
        self.assertEqual(len(recipes), 9)
        self.assertEqual(len({r["scenario_id"] for r in recipes}), 9)
        for recipe in recipes:
            before = w.io.canonical(recipe)
            state = w.validate(recipe)
            self.assertEqual(state.size, len(recipe["state"]["liquid_m3"]))
            self.assertEqual(w.io.canonical(recipe), before)
            self.assertIs(recipe["physical_acceptance"], False)
            self.assertIs(recipe["production_authorised"], False)

    def test_missing_and_extra_recipe_fields_fail(self):
        for key in small_recipe():
            r = small_recipe()
            del r[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                w.validate(r)
        r = small_recipe()
        r["override_authority"] = True
        with self.assertRaises(ValueError):
            w.validate(r)

    def test_purpose_and_authority_cannot_be_promoted(self):
        for key, value in (("purpose", "PRODUCTION"), ("schema", "anything"),
                           ("schema", "diadem.terrain.capture.recipe.r3"),
                           ("physical_acceptance", True), ("physical_acceptance", 0),
                           ("production_authorised", True), ("production_authorised", 0)):
            r = small_recipe()
            r[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                w.validate(r)

    def test_state_frame_datum_status_and_density_are_bound(self):
        for key, value in (("frame", "diadem_km"), ("vertical_datum", "MSL"),
                           ("source_status", "CANON"), ("water_density_kg_m3", 3000.)):
            r = small_recipe()
            r["state"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                w.validate(r)

    def test_nonfinite_nonnumeric_and_negative_forcing_reject(self):
        for bad in (True, None, "1", math.nan, math.inf, -1., 10**1000):
            for key in ("dt_years", "settling_m_year"):
                r = small_recipe()
                r["forcing"][key] = bad
                with self.subTest(key=key, bad=str(bad)[:20]), self.assertRaises(ValueError):
                    w.validate(r)
            for key in ("liquid_input_m3_year", "suspended_input_m3_year", "bed_input_solid_m3_year"):
                r = small_recipe()
                r["forcing"][key] = [bad]
                with self.subTest(key=key, bad=str(bad)[:20]), self.assertRaises(ValueError):
                    w.validate(r)

    def test_forcing_label_topology_and_carrier_validate_before_reuse(self):
        for key, value in (("source_label", "CANON"), ("source_label", ""),
                           ("outlets", [True]), ("outlets", [0, 0]),
                           ("connectivity", True), ("connectivity", 6)):
            r = small_recipe()
            r["forcing"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                w.validate(r)
        r = small_recipe()
        r["forcing"]["suspended_input_m3_year"] = [.1]
        with self.assertRaises(ValueError):
            w.validate(r)

    def test_bounds_and_bounded_checkpoint_count(self):
        for key, value in (("max_product_bytes", 0), ("max_product_bytes", 64*1024*1024+1),
                           ("wall_seconds", True), ("wall_seconds", 121),
                           ("checkpoint_steps", 0), ("checkpoint_steps", 4097)):
            r = small_recipe()
            r["limits"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                w.validate(r)
        for value in (0, True, 4097):
            r = small_recipe()
            r["forcing"]["steps"] = value
            with self.assertRaises(ValueError):
                w.validate(r)
        r = small_recipe()
        r["forcing"]["steps"] = 129
        with self.assertRaises(ValueError):
            w.validate(r)

    def test_controls_use_actual_bed_and_unique_provenance(self):
        c = {"id": "fixed-bed", "cell": 0, "minimum_m": 0., "maximum_m": 0.,
             "source_status": "WORKING NON-CANON SYNTHETIC", "source_label": "SYNTHETIC fixed bed"}
        r = small_recipe()
        r["constraints"] = [c]
        w.validate(r)
        for change in ({"source_status": "CANON"}, {"cell": True}, {"minimum_m": .1}):
            bad = deepcopy(r)
            bad["constraints"][0].update(change)
            with self.assertRaises(ValueError):
                w.validate(bad)
        r["constraints"] = [c, deepcopy(c)]
        with self.assertRaises(ValueError):
            w.validate(r)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="capture-workflow-peer-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.here = self.root / "work" / "terrain_model_r4"
        self.here.mkdir(parents=True)
        # A discovery fixture, not a substituted implementation or numerical oracle.
        self.stub = self.here / "identity_fixture.py"
        self.stub.write_bytes(b"# synthetic identity-discovery fixture\n")
        self.addCleanup(patch.stopall)
        patch.object(w, "HERE", self.here).start()
        # Match the discovery fixture's import-time baseline; subsequent drift
        # is still rejected. This does not mutate any real source file.
        patch.object(w, "LOADED_SOURCE_PINS", w.source_pins()).start()
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.allowed = self.root / "outputs" / "terrain-model-r6-capture"
        self.recipe = self.inputs / "recipe.json"
        self.write_recipe(small_recipe())

    def write_recipe(self, recipe):
        self.recipe.write_bytes(w.io.canonical(recipe))

    def output(self, name="candidate"):
        return self.allowed / name

    def pending(self, name="candidate"):
        values = list(self.allowed.glob(name + ".pending-*"))
        self.assertEqual(len(values), 1)
        return values[0]

    def interrupt(self, *, step=1, at=None):
        with self.assertRaisesRegex(RuntimeError, "injected interruption"):
            w.run(self.recipe, self.output(), interrupt_after_step=None if at else step, interrupt_at=at)
        self.assertFalse(self.output().exists())
        return self.pending()

    def digest_tree(self, root):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*") if p.is_file()}

    def reseal_product(self, output, name):
        receipt = w.io.read_json(output / "RECEIPT.json")
        raw = (output / name).read_bytes()
        receipt["products"][name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        (output / "RECEIPT.json").write_bytes(w.io.canonical(receipt))

    def test_clean_commit_readback_preserves_sources_and_all_phase_stores(self):
        recipe_before, code_before = self.recipe.read_bytes(), self.stub.read_bytes()
        response = w.run(self.recipe, self.output())
        self.assertEqual(response["status"], "COMMITTED_CAPTURE_REFERENCE")
        result = w.io.read_json(self.output() / "RESULT.json")
        self.assertEqual(result['schema'], 'diadem.terrain.capture.result.r4')
        receipt = w.io.read_json(self.output() / 'RECEIPT.json')
        self.assertEqual(receipt['identity']['mode'], 'event_resolved_prescribed_port_capture_reference_r4')
        state = result["state"]
        self.assertGreater(state["time_years"], 0.)
        self.assertGreater(state["bed_solid_m3"][0], 0.)
        self.assertEqual(state["liquid_m3"], [100.])
        self.assertLess(state["suspended_solid_m3"][0], .1)
        for key in ("physical_acceptance", "shoreline_capture_acceptance", "production_authorised"):
            self.assertIs(result[key], False)
        checkpoint = w.io.read_json(self.output() / "CHECKPOINT-000003.json")
        self.assertEqual(w.io.canonical(checkpoint["state"]), w.io.canonical(state))
        self.assertEqual(self.recipe.read_bytes(), recipe_before)
        self.assertEqual(self.stub.read_bytes(), code_before)

    def test_committed_reuse_is_verified_and_byte_preserving(self):
        w.run(self.recipe, self.output())
        before = self.digest_tree(self.output())
        with patch.object(w.capture, "advance", side_effect=AssertionError("reuse must not recompute")):
            response = w.run(self.recipe, self.output(), resume=True)
        self.assertEqual(response["status"], "VERIFIED_CAPTURE_REUSE")
        self.assertEqual(self.digest_tree(self.output()), before)

    def test_no_overwrite_committed_or_unrelated_target(self):
        w.run(self.recipe, self.output())
        before = self.digest_tree(self.output())
        with self.assertRaises(FileExistsError):
            w.run(self.recipe, self.output())
        self.assertEqual(self.digest_tree(self.output()), before)
        foreign = self.output("foreign")
        foreign.mkdir()
        (foreign / "keep.txt").write_bytes(b"existing unrelated data")
        with self.assertRaises(FileExistsError):
            w.run(self.recipe, foreign)
        self.assertEqual((foreign / "keep.txt").read_bytes(), b"existing unrelated data")

    def test_interrupted_checkpoint_resumes_exact_state_result_and_inventory(self):
        pending = self.interrupt(step=2)
        kept = self.digest_tree(pending)
        self.assertIn("CHECKPOINT-000002.json", kept)
        self.assertNotIn("RECEIPT.json", kept)
        w.run(self.recipe, self.output(), resume=True)
        w.run(self.recipe, self.output("clean"))
        self.assertEqual(self.digest_tree(self.output()), self.digest_tree(self.output("clean")))
        for name, digest in kept.items():
            self.assertEqual(self.digest_tree(self.output())[name], digest)
        self.assertFalse(pending.exists())

    def test_interrupted_after_products_and_receipt_resume_exact(self):
        for marker in ("after_products", "after_receipt"):
            with self.subTest(marker=marker):
                target = self.output(marker)
                with self.assertRaises(RuntimeError):
                    w.run(self.recipe, target, interrupt_at=marker)
                w.run(self.recipe, target, resume=True)
        self.assertEqual(self.digest_tree(self.output("after_products")),
                         self.digest_tree(self.output("after_receipt")))

    def test_partial_requires_explicit_resume_and_is_preserved(self):
        pending = self.interrupt()
        before = self.digest_tree(pending)
        with self.assertRaises(FileExistsError):
            w.run(self.recipe, self.output())
        self.assertEqual(self.digest_tree(pending), before)

    def test_corrupt_existing_checkpoint_rejected_without_repair_or_commit(self):
        pending = self.interrupt()
        checkpoint = pending / "CHECKPOINT-000001.json"
        data = w.io.read_json(checkpoint)
        data["state"]["liquid_m3"][0] += 1.
        checkpoint.write_bytes(w.io.canonical(data))
        corrupt = checkpoint.read_bytes()
        with self.assertRaises(ValueError):
            w.run(self.recipe, self.output(), resume=True)
        self.assertEqual(checkpoint.read_bytes(), corrupt)
        self.assertFalse(self.output().exists())

    def test_mixed_generation_and_foreign_partial_fail_closed(self):
        pending = self.interrupt()
        checkpoint = pending / "CHECKPOINT-000001.json"
        data = w.io.read_json(checkpoint)
        data["identity"] = "f" * 64
        checkpoint.write_bytes(w.io.canonical(data))
        with self.assertRaises(ValueError):
            w.run(self.recipe, self.output(), resume=True)
        (pending / "unlisted.bin").write_bytes(b"foreign")
        with self.assertRaisesRegex(ValueError, "foreign"):
            w.run(self.recipe, self.output(), resume=True)

    def test_committed_corruption_and_missing_or_extra_members_fail(self):
        w.run(self.recipe, self.output())
        result = self.output() / "RESULT.json"
        before = result.read_bytes()
        result.write_bytes(before + b" ")
        with self.assertRaises(ValueError):
            w.run(self.recipe, self.output(), resume=True)
        result.write_bytes(before)
        (self.output() / "unlisted.txt").write_bytes(b"extra")
        with self.assertRaises(ValueError):
            w.run(self.recipe, self.output(), resume=True)
        (self.output() / "unlisted.txt").unlink()
        result.unlink()
        with self.assertRaises(ValueError):
            w.run(self.recipe, self.output(), resume=True)

    def test_receipt_type_drift_is_not_boolean_numeric_equal(self):
        w.run(self.recipe, self.output())
        receipt_path = self.output() / "RECEIPT.json"
        receipt = w.io.read_json(receipt_path)
        receipt["production_authorised"] = 0
        receipt_path.write_bytes(w.io.canonical(receipt))
        with self.assertRaises(ValueError):
            w.run(self.recipe, self.output(), resume=True)

    def test_canonical_stored_recipe_must_match_original_recipe_identity(self):
        w.run(self.recipe, self.output())
        altered = w.io.read_json(self.output() / "RECIPE.json")
        altered["scenario_id"] = "another_valid_but_unbound_recipe"
        (self.output() / "RECIPE.json").write_bytes(w.io.canonical(altered))
        self.reseal_product(self.output(), "RECIPE.json")
        with self.assertRaises(ValueError):
            w.run(self.recipe, self.output(), resume=True)

    def test_checkpoint_chain_and_result_are_validated_beyond_container_hashes(self):
        for mutation in ("identity", "previous_state_sha256", "completed_steps", "final_state"):
            with self.subTest(mutation=mutation):
                output = self.output("chain-" + mutation)
                w.run(self.recipe, output)
                name = "CHECKPOINT-000003.json"
                checkpoint = w.io.read_json(output / name)
                if mutation == "final_state":
                    checkpoint["state"]["liquid_m3"][0] += 1.
                elif mutation == "completed_steps":
                    checkpoint[mutation] = 2
                else:
                    checkpoint[mutation] = "e" * 64
                (output / name).write_bytes(w.io.canonical(checkpoint))
                self.reseal_product(output, name)
                with self.assertRaises(ValueError):
                    w.run(self.recipe, output, resume=True)

    def test_checkpoint_readback_mutation_cannot_become_next_state(self):
        original = w.io.read_json
        injected = [False]
        def mutate(path):
            path = Path(path)
            if path.name == "CHECKPOINT-000001.json" and not injected[0]:
                injected[0] = True
                record = original(path)
                record["state"]["liquid_m3"][0] += 1.
                path.write_bytes(w.io.canonical(record))
            return original(path)
        with patch.object(w.io, "read_json", side_effect=mutate), self.assertRaises(ValueError):
            w.run(self.recipe, self.output())
        self.assertTrue(injected[0])
        self.assertFalse(self.output().exists())

    def test_source_and_recipe_drift_during_execution_prevent_commit(self):
        advance = w.capture.advance
        for mutate_source in (True, False):
            with self.subTest(source=mutate_source):
                target = self.output("source-drift" if mutate_source else "recipe-drift")
                before = self.stub.read_bytes(), self.recipe.read_bytes()
                changed = [False]
                def drift(*args, **kwargs):
                    value = advance(*args, **kwargs)
                    if not changed[0]:
                        changed[0] = True
                        path = self.stub if mutate_source else self.recipe
                        path.write_bytes(path.read_bytes() + b"\n")
                    return value
                with patch.object(w.capture, "advance", side_effect=drift), self.assertRaisesRegex(ValueError, "source drift"):
                    w.run(self.recipe, target)
                self.assertFalse(target.exists())
                self.stub.write_bytes(before[0])
                self.recipe.write_bytes(before[1])

    def test_changed_recipe_or_implementation_cannot_reuse_committed_output(self):
        w.run(self.recipe, self.output())
        original_recipe = self.recipe.read_bytes()
        original_stub = self.stub.read_bytes()
        self.recipe.write_bytes(original_recipe + b"\n")
        with self.assertRaises(ValueError):
            w.run(self.recipe, self.output(), resume=True)
        self.recipe.write_bytes(original_recipe)
        self.stub.write_bytes(original_stub + b"# changed\n")
        with self.assertRaises(ValueError):
            w.run(self.recipe, self.output(), resume=True)

    def test_pretty_input_is_bound_without_confusing_canonical_saved_recipe(self):
        self.recipe.write_text(json.dumps(small_recipe(), indent=2), encoding="utf-8")
        w.run(self.recipe, self.output())
        self.assertEqual(w.run(self.recipe, self.output(), resume=True)["status"], "VERIFIED_CAPTURE_REUSE")

    def test_output_root_recipe_inside_output_and_traversal_are_rejected(self):
        for output in (self.root / "elsewhere", self.allowed, self.allowed / ".." / "escaped"):
            with self.subTest(output=str(output)), self.assertRaises(ValueError):
                w.run(self.recipe, output)
        inside = self.output("inside")
        inside.mkdir(parents=True)
        recipe = inside / "recipe.json"
        recipe.write_bytes(self.recipe.read_bytes())
        with self.assertRaises(ValueError):
            w.run(recipe, inside)
        self.assertEqual(recipe.read_bytes(), self.recipe.read_bytes())

    def test_mocked_symlink_and_reparse_sources_outputs_and_products_fail(self):
        original_link = Path.is_symlink
        for blocked in (self.recipe, self.output(), self.allowed):
            def is_link(path, blocked=blocked):
                return path == blocked or original_link(path)
            with patch.object(Path, "is_symlink", is_link), self.assertRaises(ValueError):
                w.run(self.recipe, self.output())
        original_stat = Path.stat
        def reparse_stat(path, *args, **kwargs):
            value = original_stat(path, *args, **kwargs)
            if path == self.recipe:
                return SimpleNamespace(st_file_attributes=0x400, st_mode=value.st_mode)
            return value
        with patch.object(Path, "stat", reparse_stat), self.assertRaises(ValueError):
            w.run(self.recipe, self.output())
        w.run(self.recipe, self.output())
        leaf = self.output() / "RESULT.json"
        with patch.object(Path, "is_symlink", lambda path: path == leaf or original_link(path)), self.assertRaises(ValueError):
            w.run(self.recipe, self.output(), resume=True)

    def test_tiny_product_budget_preserves_sources_without_commit(self):
        r = small_recipe()
        r["limits"]["max_product_bytes"] = 1
        self.write_recipe(r)
        raw = self.recipe.read_bytes()
        with self.assertRaisesRegex(ValueError, "storage envelope"):
            w.run(self.recipe, self.output())
        self.assertFalse(self.output().exists())
        self.assertEqual(self.recipe.read_bytes(), raw)

    def test_receipt_overhead_is_included_in_storage_budget(self):
        w.run(self.recipe, self.output("sized"))
        total_products = sum(p.stat().st_size for p in self.output("sized").iterdir() if p.name != "RECEIPT.json")
        r = small_recipe()
        r["limits"]["max_product_bytes"] = total_products + 32
        self.write_recipe(r)
        with self.assertRaisesRegex(ValueError, "storage envelope"):
            w.run(self.recipe, self.output())
        self.assertFalse(self.output().exists())

    def test_last_step_wall_overrun_fails_and_retains_checkpoint(self):
        advance = w.capture.advance
        clock = [0.]
        def slow(*args, **kwargs):
            result = advance(*args, **kwargs)
            clock[0] = 121.
            return result
        with patch.object(w.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(w.capture, "advance", side_effect=slow), \
             self.assertRaisesRegex(ValueError, "wall-time envelope"):
            w.run(self.recipe, self.output())
        self.assertFalse(self.output().exists())
        self.assertTrue((self.pending() / "CHECKPOINT-000001.json").exists())

    def test_invalid_json_duplicate_keys_nonfinite_and_corrupt_partial_are_rejected(self):
        for raw in (b'{"purpose":0,"purpose":1}', b'{"x":NaN}', b'{broken'):
            self.recipe.write_bytes(raw)
            with self.assertRaises(ValueError):
                w.run(self.recipe, self.output())
            self.assertFalse(self.output().exists())
        self.write_recipe(small_recipe())
        pending = self.interrupt()
        (pending / "CHECKPOINT-000001.json").write_bytes(b"{broken")
        with self.assertRaises(ValueError):
            w.run(self.recipe, self.output(), resume=True)


if __name__ == "__main__":
    unittest.main()
