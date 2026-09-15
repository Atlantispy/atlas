"""Read-only staged launcher review and isolated gate/shim integration tests.

The installed SafetyControls implementation is imported read-only. Every fake
workspace, recipe and output is temporary; no official launcher is executed.
PowerShell is used only to parse the two staged scripts into syntax trees.
"""
from copy import deepcopy
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


HERE = Path(__file__).resolve().parent
INTEGRATION = HERE / "integration"
SAFETY_SRC = Path("C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace/04_Manifests/Tools/LocalFirst/SafetyControls/package/src")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (SAFETY_SRC / "diadem_safety" / "__init__.py").is_file():
            raise AssertionError("The reviewed installed SafetyControls source is unavailable")
        with patch.object(sys, "path", [str(SAFETY_SRC), *sys.path]):
            cls.before = load("terrain_registration_before_test", INTEGRATION / "gate.before.py")
            cls.gate = load("terrain_registration_candidate_test", INTEGRATION / "gate.py")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.generator = self.root / "06_Generator_System"
        self.generator.mkdir()
        for task in self.gate.TASKS.values():
            entry = self.generator / task["entry"]
            if entry.suffix:
                entry.parent.mkdir(parents=True, exist_ok=True)
                entry.write_bytes(b"# synthetic entry; never executed")
            else:
                entry.mkdir(parents=True, exist_ok=True)
        self.recipe = self.root / "recipe.json"
        self.recipe.write_bytes(b'{"purpose":"test only"}')
        self.sha = hashlib.sha256(self.recipe.read_bytes()).hexdigest()
        self.output = self.generator / "generated_outputs" / "terrain-test"
        self.options = {"recipe_path": str(self.recipe), "recipe_sha256": self.sha, "resume": False}

    def resolve(self, **kwargs):
        args = {"workspace_root": self.root, "generator_root": self.generator,
                "task": "TerrainReference", "database": None,
                "output_directory": str(self.output), "run_options": self.options}
        args.update(kwargs)
        return self.gate._resolve_profile(**args)

    def test_existing_task_registry_is_unchanged_and_new_task_is_explicit(self):
        previous = self.before.TASKS
        self.assertEqual({k: v for k, v in self.gate.TASKS.items() if k != "TerrainReference"}, previous)
        self.assertEqual(self.gate.TASKS["TerrainReference"],
                         {"entry": "engine/build_terrain_reference.py", "target": None, "target_kind": "tree"})

    def test_existing_valid_and_invalid_option_behaviour_is_unchanged(self):
        cases = [ {}, {"workers": 4}, {"workers": 0}, {"workers": True},
                  {"memory_budget_mb": 1024}, {"memory_budget_mb": 64},
                  {"algorithm_mode": "auto"}, {"algorithm_mode": "reference"},
                  {"algorithm_mode": "anything"}, {"no_reuse": True}, {"no_reuse": 1},
                  {"scope": "FT0"}, {"scope": "ALL"}, {"scope": "bad"},
                  {"smoke_limit": 25}, {"smoke_limit": 108},
                  {"expected_active_sites": 30097}, {"prefetch_depth": 4}, {"arbitrary_argv": "--production"}]
        def outcome(module, task, options):
            try:
                return "PASS", module._validated_run_options(task, deepcopy(options))
            except module.GateError as exc:
                return "FAIL", str(exc)
        for task in self.before.TASKS:
            for options in cases:
                with self.subTest(task=task, options=options):
                    self.assertEqual(outcome(self.before, task, options), outcome(self.gate, task, options))

    def test_new_profile_binds_exact_recipe_output_and_resume_without_writes(self):
        before = {str(p.relative_to(self.root)) for p in self.root.rglob("*")}
        resolved = self.resolve()
        self.assertEqual(resolved["target"], self.output)
        self.assertEqual(resolved["invocation"]["run_options"], self.options)
        self.assertEqual(resolved["invocation"]["output_directory"],
                         "06_Generator_System/generated_outputs/terrain-test")
        self.assertIsNone(resolved["invocation"]["database"])
        self.assertEqual({str(p.relative_to(self.root)) for p in self.root.rglob("*")}, before)
        self.assertFalse(self.output.exists())

    def test_new_options_reject_arbitrary_arguments_and_wrong_types(self):
        invalid = [{"workers": 1}, {"algorithm_mode": "auto"}, {"no_reuse": True},
                   {"production": True}, {"force": True}, {"resume": 1},
                   {"resume": "true"}, {"recipe_path": "relative.json"},
                   {"recipe_path": " "}, {"recipe_path": None},
                   {"recipe_sha256": "A" * 64}, {"recipe_sha256": "0" * 63},
                   {"recipe_sha256": "g" * 64}, {"recipe_sha256": 1}]
        for changes in invalid:
            options = {**self.options, **changes}
            with self.subTest(changes=changes), self.assertRaises(self.gate.GateError):
                self.resolve(run_options=options)
        for key in self.options:
            options = dict(self.options); options.pop(key)
            with self.subTest(missing=key), self.assertRaises(self.gate.GateError):
                self.resolve(run_options=options)

    def test_explicit_output_recipe_and_non_database_contract(self):
        for changes in ({"output_directory": None}, {"output_directory": ""},
                        {"database": str(self.recipe)}, {"run_options": None}):
            with self.subTest(changes=changes), self.assertRaises(self.gate.GateError):
                self.resolve(**changes)
        self.recipe.unlink()
        with self.assertRaises(self.gate.GateError): self.resolve()

    def test_recipe_hash_change_and_size_cap_are_checked_before_launch(self):
        self.recipe.write_bytes(b"changed")
        with self.assertRaisesRegex(self.gate.GateError, "changed"):
            self.resolve()
        self.recipe.write_bytes(b'{"purpose":"test only"}')
        original_stat = Path.stat
        def oversized(path, *args, **kwargs):
            observed = original_stat(path, *args, **kwargs)
            if path == self.recipe:
                values = {key: getattr(observed, key) for key in dir(observed) if key.startswith("st_")}
                values["st_size"] = 16 * 1024 * 1024 + 1
                return SimpleNamespace(**values)
            return observed
        with patch.object(Path, "stat", oversized), patch.object(self.gate, "sha256_file", side_effect=AssertionError("oversize must reject before hashing")), \
                self.assertRaisesRegex(self.gate.GateError, "oversized"):
            self.resolve()

    def test_recipe_must_be_inside_workspace_and_outside_output_tree(self):
        outside = Path(self.temp.name) / "outside.json"
        outside.write_bytes(self.recipe.read_bytes())
        with self.assertRaisesRegex(self.gate.GateError, "within the local workspace"):
            self.resolve(run_options={**self.options, "recipe_path": str(outside)})
        nested = self.output / "inputs" / "recipe.json"
        nested.parent.mkdir(parents=True); nested.write_bytes(self.recipe.read_bytes())
        with self.assertRaisesRegex(self.gate.GateError, "must not contain"):
            self.resolve(run_options={**self.options, "recipe_path": str(nested)})
        self.assertEqual(nested.read_bytes(), self.recipe.read_bytes())

    def test_output_child_boundary_and_traversal_fail_closed(self):
        for output in (self.generator / "generated_outputs", self.root / "arbitrary",
                       self.generator / "generated_outputs-other" / "x",
                       self.generator / "generated_outputs" / ".." / "escaped"):
            with self.subTest(output=str(output)), self.assertRaises(self.gate.GateError):
                self.resolve(output_directory=str(output))
        self.assertFalse(self.output.exists())

    def test_recipe_and_output_reparse_validation_is_not_bypassed(self):
        original = self.gate.reject_reparse_chain
        for rejected in (self.recipe, self.output):
            def guarded(root, candidate, *args, **kwargs):
                if candidate == rejected:
                    raise self.gate.PathSafetyError("synthetic reparse rejection")
                return original(root, candidate, *args, **kwargs)
            with self.subTest(rejected=str(rejected)), patch.object(self.gate, "reject_reparse_chain", side_effect=guarded), \
                    self.assertRaises(self.gate.PathSafetyError):
                self.resolve()
        self.assertFalse(self.output.exists())


class ShimTests(unittest.TestCase):
    def setUp(self):
        # Loading the shim is safe: __main__ is not run. Its package-path
        # addition is scoped and restored, and the workflow is mocked below.
        with patch.object(sys, "path", list(sys.path)):
            self.shim = load("terrain_reference_build_shim_test", INTEGRATION / "build_terrain_reference.py")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.recipe = root / "recipe.json"; self.recipe.write_bytes(b"synthetic recipe")
        self.output = root / "outputs" / "scene"
        self.sha = hashlib.sha256(self.recipe.read_bytes()).hexdigest()

    def invoke(self, args):
        with patch.object(sys, "argv", ["build_terrain_reference.py", *args]), contextlib.redirect_stdout(io.StringIO()):
            self.shim.main()

    def test_shim_passes_hash_and_explicit_resume_to_bounded_runner(self):
        fake = SimpleNamespace(read_bytes=lambda path: path.read_bytes(), run=Mock(return_value={"production_authorised": False}))
        with patch.object(self.shim, "workflow", fake):
            self.invoke(["--recipe", str(self.recipe), "--expected-recipe-sha256", self.sha,
                         "--output", str(self.output), "--resume"])
        fake.run.assert_called_once_with(self.recipe, self.output, resume=True, expected_recipe_sha256=self.sha)
        self.assertFalse(self.output.exists())

    def test_shim_stale_hash_never_calls_runner(self):
        fake = SimpleNamespace(read_bytes=lambda path: path.read_bytes(), run=Mock())
        with patch.object(self.shim, "workflow", fake), self.assertRaisesRegex(ValueError, "changed"):
            self.invoke(["--recipe", str(self.recipe), "--expected-recipe-sha256", "0" * 64,
                         "--output", str(self.output)])
        fake.run.assert_not_called()

    def test_shim_has_no_production_force_or_missing_hash_bypass(self):
        complete = ["--recipe", str(self.recipe), "--expected-recipe-sha256", self.sha, "--output", str(self.output)]
        for args in (complete + ["--production"], complete + ["--force"],
                     ["--recipe", str(self.recipe), "--output", str(self.output)]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_info:
                self.invoke(args)
            self.assertNotEqual(exit_info.exception.code, 0)


class PowerShellRegistrationTests(unittest.TestCase):
    def test_scripts_parse_in_both_available_powershell_runtimes(self):
        shells = list(dict.fromkeys(path for name in ("pwsh", "powershell") if (path := shutil.which(name))))
        if not shells:
            self.fail("PowerShell parser unavailable; registration has not been verified")
        for executable in shells:
            for filename in ("Run-Generator.before.ps1", "Run-Generator.ps1"):
                path = str(INTEGRATION / filename).replace("'", "''")
                command = ("$tokens = $null; $parseErrors = $null; "
                           "[void][System.Management.Automation.Language.Parser]::ParseFile('" + path + "', [ref]$tokens, [ref]$parseErrors); "
                           "if ($parseErrors.Count -gt 0) { $parseErrors | ForEach-Object { $_.Message }; exit 1 }; 'PARSE_PASS'")
                with self.subTest(shell=executable, script=filename):
                    result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-Command", command],
                                            text=True, capture_output=True, timeout=30, check=False)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("PARSE_PASS", result.stdout)

    def test_prior_task_switch_arms_are_preserved_verbatim(self):
        previous = (INTEGRATION / "Run-Generator.before.ps1").read_text(encoding="utf-8")
        current = (INTEGRATION / "Run-Generator.ps1").read_text(encoding="utf-8")
        start = "$pythonArguments = @(switch ($Task) {"
        def arms(text):
            return text.split(start, 1)[1].split("\n})", 1)[0].splitlines()
        original = arms(previous)
        modified = [line for line in arms(current) if "'TerrainReference'" not in line]
        self.assertEqual(modified, original)
        self.assertIn("--expected-recipe-sha256', $terrainRecipeHash", current)
        self.assertIn("if ($Task -eq 'TerrainReference' -and $ResumeTerrainReference)", current)
        # Child execution still follows the existing single-use authorisation;
        # the new task adds no direct launch path before that guard.
        self.assertLess(current.index("-m diadem_launch_gate authorize"), current.index("& $python -B @pythonArguments"))


if __name__ == "__main__":
    unittest.main()
