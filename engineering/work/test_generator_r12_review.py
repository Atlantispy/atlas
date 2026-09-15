"""Independent, isolated regression probes; never run a scientific producer."""

import json
import os
import hashlib
from copy import deepcopy
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from work.generator_runtime_r12 import executor, parents, provenance
from work.generator_runtime_r12.store import Store, CacheError


class ReviewProbes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seal = json.loads(provenance.checked(provenance.SEAL, provenance.SEAL_SHA))
        path = provenance.R11 / "snapshot.py"
        digest = seal["source_identity"]["r11_sources"][str(path)]
        raw = provenance.checked(path, digest)
        cls.snapshot = types.ModuleType("_independent_sealed_r11_snapshot")
        exec(compile(raw, str(path), "exec", dont_inherit=True), cls.snapshot.__dict__)

    def graph(self):
        s = self.snapshot
        context = dict(zip(s.FRAME_FIELDS, ("world", "time", "calendar", "grid", "datum", "scenario")))
        port = {"quantity": "independent integer oracle", "unit": "count",
                "support_id": "test cell", "temporal_support": "test year"}
        calls = []
        def producer(ctx, inputs, incoming):
            calls.append(inputs["id"])
            return s.emission(ctx, {"v": port}, {"v": inputs["n"] + sum(incoming.values())},
                              evidence="SYNTHETIC TEST; no scientific producer execution")
        registry = {"sum": {"sha256": "a" * 64, "run": producer, "verify": lambda: None}}
        stages = []
        for ident, dependencies in (("a", ()), ("b", ()), ("c", ("a", "b"))):
            stages.append({"stage_id": ident, "category": "hydrology", "producer_id": "sum",
                           "producer_sha256": "a" * 64, "inputs": {"id": ident, "n": 1},
                           "dependencies": {name: {"stage_id": name, "output": "v", "port": port}
                                            for name in dependencies},
                           "outputs": {"v": port}, "missing_inputs": [], "mode": "GENERATED",
                           "acceptance": {"status": "BOUNDED_REFERENCE_VERIFIED", "evidence": "test only"}})
        recipe = {"schema": "diadem.snapshot-graph-recipe.r11", "context": context, "stages": stages,
                  "required_categories": ["hydrology"], "evidence": "SYNTHETIC TEST only"}
        return recipe, registry, calls

    def private_package(self, root):
        package = root / "work" / "generator_runtime_r12"
        package.mkdir(parents=True)
        for name in ("__init__.py", "provenance.py"):
            (package / name).write_bytes((Path(provenance.__file__).parent / name).read_bytes())
        (package / "executor.py").write_text("def retained_answer():\n    return 1\n", encoding="utf-8")
        return package

    def run_private(self, root, script):
        flags = ["-OO"] if sys.flags.optimize == 2 else []
        result = subprocess.run([sys.executable, "-B", *flags, "-c", script],
                                cwd=root, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        return result

    def test_loaded_code_must_not_be_rebound_to_changed_disk_source(self):
        """Private fixture: stale execution must not inherit fresh disk identity."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.private_package(root)
            self.run_private(root, """
from pathlib import Path
from types import SimpleNamespace
from work.generator_runtime_r12 import provenance, executor
bundle = SimpleNamespace(source_sha256='a'*64, identity={'runtime':{}}, verify=lambda: None)
provenance.SCIENCE_SHA = provenance.sha(bundle.identity)
bundle.source_sha256 = provenance.SCIENCE_SHA
identity = provenance.execution_identity(bundle)
provenance.verify_execution(bundle, identity)
path = Path(executor.__file__)
path.write_text('def retained_answer():\\n    return 2\\n', encoding='utf-8')
if executor.retained_answer() != 1:
    raise RuntimeError('fixture did not retain loaded code')
try:
    provenance.execution_identity(bundle)
except ValueError:
    pass
else:
    raise RuntimeError('stale loaded code accepted under new disk identity')
""")

    def test_timestamp_valid_stale_component_bytecode_is_ignored(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            package = self.private_package(root)
            component = package / "executor.py"
            before = component.stat()
            py_compile.compile(str(component), doraise=True, optimize=sys.flags.optimize)
            component.write_text("def retained_answer():\n    return 2\n", encoding="utf-8")
            os.utime(component, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.run_private(root, """
from types import SimpleNamespace
from work.generator_runtime_r12 import provenance, executor
if executor.retained_answer() != 2:
    raise RuntimeError('timestamp-valid old component bytecode was executed')
bundle = SimpleNamespace(source_sha256='a'*64, identity={'runtime':{}}, verify=lambda: None)
provenance.SCIENCE_SHA = provenance.sha(bundle.identity)
bundle.source_sha256 = provenance.SCIENCE_SHA
identity = provenance.execution_identity(bundle)
provenance.verify_execution(bundle, identity)
""")

    def test_timestamp_valid_stale_bootstrap_bytecode_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            package = self.private_package(root)
            bootstrap = package / "__init__.py"
            original = bootstrap.read_bytes()
            bootstrap.write_bytes(original + b"\n_REVIEW_TAG = 1\n")
            before = bootstrap.stat()
            py_compile.compile(str(bootstrap), doraise=True, optimize=sys.flags.optimize)
            bootstrap.write_bytes(original + b"\n_REVIEW_TAG = 2\n")
            os.utime(bootstrap, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.run_private(root, """
try:
    import work.generator_runtime_r12
except ValueError as exc:
    if 'bootstrap' not in str(exc):
        raise
else:
    raise RuntimeError('stale bootstrap bytecode was accepted')
""")

    def test_uncached_parent_execution_must_not_look_like_zero_executions(self):
        invoked = []
        class FakeParent:
            def run(self, recipe, *, stop_after=None, resume=None):
                invoked.append(recipe)
                return {"result": True}
        parent = FakeParent()
        bundle = types.SimpleNamespace(parent=parent)
        stats = {}
        with parents.reuse(bundle, None, stats):
            parent.run({"actual": "uncached invocation"})
        self.assertEqual(len(invoked), 1)
        self.assertTrue(stats.get("executed") or str(stats.get("accounting", "")).startswith("NOT_COLLECTED"),
                        "An uninstrumented baseline must be labelled, not presented as zero parent executions")

    def test_actual_hmac_store_and_executor_exact_restart(self):
        recipe, registry, calls = self.graph()
        baseline = self.snapshot.run(recipe, registry)
        with tempfile.TemporaryDirectory() as name:
            cache = Store(Path(name) / "cache", "f" * 64)
            calls.clear()
            stopped = executor.run(self.snapshot, recipe, registry, store=cache, stop_after=2)
            self.assertEqual(calls, ["a", "b"])
            calls.clear()
            stats = {}
            fresh_instance = Store(cache.root, "f" * 64)
            resumed = executor.run(self.snapshot, recipe, registry, store=fresh_instance,
                                   resume=self.snapshot.checkpoint(stopped), stats=stats)
            self.assertEqual(calls, ["c"])
            self.assertEqual(resumed, baseline)
            self.assertEqual(stats["restored_prefix_stage_ids"], ["a", "b"])

    def test_rehashed_forged_checkpoint_rejected_against_actual_hmac_store(self):
        recipe, registry, calls = self.graph()
        with tempfile.TemporaryDirectory() as name:
            cache = Store(Path(name) / "cache", "f" * 64)
            stopped = executor.run(self.snapshot, recipe, registry, store=cache, stop_after=2)
            checkpoint = self.snapshot.checkpoint(stopped)
            forged = checkpoint["state"]["rows"]["a"]
            forged["product"]["values"]["v"] += 100
            forged["product_sha256"] = self.snapshot.sha(forged["product"])
            checkpoint["state_sha256"] = self.snapshot.sha(checkpoint["state"])
            calls.clear()
            with self.assertRaises(ValueError):
                executor.run(self.snapshot, recipe, registry, store=cache, resume=checkpoint)
            self.assertEqual(calls, [])

    def test_rehashed_cache_file_cannot_authorise_checkpoint_prefix(self):
        recipe, registry, calls = self.graph()
        with tempfile.TemporaryDirectory() as name:
            cache = Store(Path(name) / "cache", "f" * 64)
            stopped = executor.run(self.snapshot, recipe, registry, store=cache, stop_after=2)
            invocation = stopped["state"]["rows"]["a"]["invocation_sha256"]
            path = cache.root / ("f" * 64) / (invocation + ".json")
            record = json.loads(path.read_bytes())
            row = record["value"]["row"]
            row["product"]["values"]["v"] += 100
            row["product_sha256"] = self.snapshot.sha(row["product"])
            record["value_sha256"] = hashlib.sha256(provenance.encoded(record["value"])).hexdigest()
            path.write_bytes(provenance.encoded(record))
            calls.clear()
            with self.assertRaises(CacheError):
                executor.run(self.snapshot, recipe, registry, store=cache,
                             resume=self.snapshot.checkpoint(stopped))
            self.assertEqual(calls, [])

    def test_actual_store_reuses_only_unchanged_causal_inputs(self):
        recipe, registry, calls = self.graph()
        with tempfile.TemporaryDirectory() as name:
            cache = Store(Path(name) / "cache", "f" * 64)
            executor.run(self.snapshot, recipe, registry, store=cache)
            changed = deepcopy(recipe)
            changed["stages"][0]["inputs"]["n"] = 10
            calls.clear()
            result = executor.run(self.snapshot, changed, registry, store=cache)
            self.assertEqual(calls, ["a", "c"])
            self.assertEqual(result, self.snapshot.run(changed, registry))

    def test_public_module_cli_help_works_without_science(self):
        flags = ["-OO"] if sys.flags.optimize == 2 else []
        result = subprocess.run([sys.executable, "-B", *flags, "-m", "work.generator_runtime_r12", "--help"],
                                cwd=provenance.TASK, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertIn(b"--reference", result.stdout)

    def light_gate_fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        paths = [root / "r11_binding.py", root / "r10_provenance.py", root / "r6_kernel.py"]
        pins = {}
        for index, path in enumerate(paths):
            raw = ("VALUE = %d\n" % index).encode("ascii")
            path.write_bytes(raw)
            pins[str(path)] = hashlib.sha256(raw).hexdigest()
        scientific_identity = {"runtime": {"fixture": "no science"},
            "r11_sources": {str(paths[0]): pins[str(paths[0])]},
            "retained_source_identity": {"bootstrap": {str(paths[1]): pins[str(paths[1])]},
                "retained_source_identity": [{"deep_sources": {str(paths[2]): pins[str(paths[2])]}}]}}
        checks = []
        bundle = types.SimpleNamespace(identity=scientific_identity,
            source_sha256=provenance.sha(scientific_identity),
            verify=lambda: checks.append("full_recursive"),
            graph=types.SimpleNamespace(executed={}, verify=lambda: checks.append("executed_graph")))
        return bundle, provenance.execution_identity(bundle), paths, checks

    def verify_fixture(self, bundle, identity, *, full=True):
        # Only the declared seal constant is replaced for this tiny private
        # identity; all source extraction, hashing and runtime checks remain real.
        with mock.patch.object(provenance, "SCIENCE_SHA", identity["science_sha256"]):
            return provenance.verify_execution(bundle, identity, full=full)

    def refresh_fixture_identity(self, bundle):
        bundle.source_sha256 = provenance.sha(bundle.identity)
        return provenance.execution_identity(bundle)

    def test_lighter_gate_hashes_valid_pins_without_recursive_reconstruction(self):
        bundle, identity, _, checks = self.light_gate_fixture()
        self.verify_fixture(bundle, identity, full=False)
        self.assertNotIn("full_recursive", checks)
        self.assertIn("executed_graph", checks)

    def test_full_gate_still_calls_original_recursive_verification(self):
        bundle, identity, _, checks = self.light_gate_fixture()
        self.verify_fixture(bundle, identity)
        self.assertIn("full_recursive", checks)

    def test_lighter_gate_rejects_bootstrap_drift_with_unchanged_size_and_timestamp(self):
        bundle, identity, paths, _ = self.light_gate_fixture()
        path = paths[0]
        original = path.stat()
        path.write_bytes(b"VALUE = 9\n")
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        with self.assertRaises(ValueError):
            self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_rejects_deep_predecessor_drift_with_unchanged_timestamp(self):
        bundle, identity, paths, _ = self.light_gate_fixture()
        path = paths[2]
        original = path.stat()
        path.write_bytes(b"VALUE = 9\n")
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        with self.assertRaises(ValueError):
            self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_rejects_missing_pinned_predecessor(self):
        bundle, identity, paths, _ = self.light_gate_fixture()
        paths[1].unlink()
        with self.assertRaises(ValueError):
            self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_rejects_mutated_identity_instead_of_silent_repin(self):
        bundle, identity, paths, _ = self.light_gate_fixture()
        changed = b"VALUE = 9\n"
        paths[0].write_bytes(changed)
        bundle.identity["r11_sources"][str(paths[0])] = hashlib.sha256(changed).hexdigest()
        # Do not update the scientific source digest or accepted execution identity.
        with self.assertRaises(ValueError):
            self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_rejects_conflicting_repeated_source_pins(self):
        bundle, _, paths, _ = self.light_gate_fixture()
        path = str(paths[0])
        actual = bundle.identity["r11_sources"][path]
        bundle.identity["r11_sources"][path] = "0" * 64
        bundle.identity["retained_source_identity"]["duplicate"] = {path: actual}
        identity = self.refresh_fixture_identity(bundle)
        with self.assertRaises(ValueError):
            self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_accepts_identical_repeated_pins(self):
        bundle, _, paths, checks = self.light_gate_fixture()
        path = str(paths[0])
        bundle.identity["retained_source_identity"]["duplicate"] = {
            path: bundle.identity["r11_sources"][path]}
        identity = self.refresh_fixture_identity(bundle)
        self.verify_fixture(bundle, identity, full=False)
        self.assertNotIn("full_recursive", checks)

    def test_lighter_gate_rejects_nonabsolute_python_pin(self):
        bundle, _, _, _ = self.light_gate_fixture()
        bundle.identity["r11_sources"]["relative/unbound.py"] = "a" * 64
        identity = self.refresh_fixture_identity(bundle)
        with self.assertRaises(ValueError):
            self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_rejects_parent_traversal_python_pin(self):
        bundle, _, paths, _ = self.light_gate_fixture()
        unsafe = paths[0].parent / "folder" / ".." / paths[0].name
        bundle.identity["r11_sources"][str(unsafe)] = "a" * 64
        identity = self.refresh_fixture_identity(bundle)
        with self.assertRaises(ValueError):
            self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_rejects_malformed_python_digest_values(self):
        for invalid in (None, True, 12, [], {}, "", "z" * 64, "A" * 64, "a" * 63):
            with self.subTest(digest=invalid):
                bundle, _, paths, _ = self.light_gate_fixture()
                bundle.identity["r11_sources"][str(paths[0])] = invalid
                identity = self.refresh_fixture_identity(bundle)
                with self.assertRaises(ValueError):
                    self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_rejects_unbound_empty_python_inventory(self):
        bundle, _, _, _ = self.light_gate_fixture()
        bundle.identity = {"runtime": {"fixture": "no sources"}}
        identity = self.refresh_fixture_identity(bundle)
        with self.assertRaises(ValueError):
            self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_retains_actual_executed_graph_verification(self):
        bundle, identity, _, _ = self.light_gate_fixture()
        def fail_graph():
            raise ValueError("independent executed-graph failure")
        bundle.graph.verify = fail_graph
        with self.assertRaisesRegex(ValueError, "executed-graph failure"):
            self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_rejects_changed_numerical_runtime_environment(self):
        bundle, identity, _, _ = self.light_gate_fixture()
        before = os.environ.get("OMP_NUM_THREADS")
        changed = "17" if before != "17" else "19"
        with mock.patch.dict(os.environ, {"OMP_NUM_THREADS": changed}):
            with self.assertRaises(ValueError):
                self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_rejects_actually_executed_source_outside_pin_inventory(self):
        bundle, identity, paths, _ = self.light_gate_fixture()
        foreign = paths[0].parent / "unbound_execution.py"
        raw = b"VALUE = 44\n"
        foreign.write_bytes(raw)
        bundle.graph.executed = {"foreign": {"path": str(foreign), "sha256": hashlib.sha256(raw).hexdigest()}}
        with self.assertRaisesRegex(ValueError, "not sealed"):
            self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_checks_executed_inventory_in_predecessor_graphs(self):
        bundle, identity, paths, _ = self.light_gate_fixture()
        bundle.parent = types.SimpleNamespace(graph=types.SimpleNamespace(
            executed={"ancestor": {"path": str(paths[1]), "sha256": "0" * 64}}, verify=lambda: None))
        with self.assertRaisesRegex(ValueError, "not sealed"):
            self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_checks_every_ancestor_graph(self):
        bundle, identity, paths, checks = self.light_gate_fixture()
        digest = bundle.identity["retained_source_identity"]["bootstrap"][str(paths[1])]
        bundle.parent = types.SimpleNamespace(graph=types.SimpleNamespace(
            executed={"ancestor": {"path": str(paths[1]), "sha256": digest}},
            verify=lambda: checks.append("ancestor_executed_graph")))
        self.verify_fixture(bundle, identity, full=False)
        self.assertIn("executed_graph", checks)
        self.assertIn("ancestor_executed_graph", checks)

    def test_lighter_gate_rejects_cyclic_bundle_ancestry(self):
        bundle, identity, _, _ = self.light_gate_fixture()
        bundle.parent = bundle
        with self.assertRaisesRegex(ValueError, "cyclic"):
            self.verify_fixture(bundle, identity, full=False)

    def test_lighter_gate_requires_supplied_execution_science_digest_to_match(self):
        bundle, identity, _, _ = self.light_gate_fixture()
        changed = deepcopy(identity)
        changed["science_sha256"] = "0" * 64
        with mock.patch.object(provenance, "SCIENCE_SHA", bundle.source_sha256):
            with self.assertRaisesRegex(ValueError, "sealed scientific identity"):
                provenance.verify_execution(bundle, changed, full=False)


if __name__ == "__main__":
    unittest.main()
