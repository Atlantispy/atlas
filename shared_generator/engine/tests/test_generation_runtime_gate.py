from __future__ import annotations

import json
import base64
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from diadem_launch_gate import cli
from diadem_launch_gate.gate import GateError, TASKS, _resolve_profile, _validated_run_options


class RuntimeLaunchGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.generator = self.root / "06_Generator_System"
        for profile in TASKS.values():
            path = self.generator / profile["entry"]
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix:
                path.touch()
            else:
                path.mkdir(exist_ok=True)
        self.source = self.root / "02_Working_Files" / "source.sqlite"
        self.source.parent.mkdir()
        self.source.write_bytes(b"fixture")
        self.output = self.generator / "generated_outputs" / "acceptance"

    def resolve(self, task, *, output=None, database=None, options=None):
        return _resolve_profile(workspace_root=self.root, generator_root=self.generator,
            task=task, database=str(database) if database else None,
            output_directory=str(output) if output else None, run_options=options)

    def test_later_stages_require_explicit_output(self):
        for task in ("Refine10m", "Physical10m", "Population"):
            with self.subTest(task=task), self.assertRaises(GateError):
                self.resolve(task)

    def test_new_write_profiles_bind_exact_target_and_options(self):
        options = {"workers": 2, "memory_budget_mb": 512, "no_reuse": False}
        value = self.resolve("Refine10m", output=self.output, options=options)
        self.assertEqual(value["target"], self.output)
        self.assertEqual(value["profile"]["target_kind"], "tree")
        self.assertEqual(value["invocation"]["run_options"], options)

    def test_population_source_and_target_bound(self):
        value = self.resolve("Population", output=self.output, database=self.source,
                             options={"expected_active_sites": 25})
        self.assertEqual(value["target"], self.output)
        self.assertEqual(value["invocation"]["database"], "02_Working_Files/source.sqlite")

    def test_output_escape_and_source_overlap_rejected(self):
        for output in (self.root / "elsewhere", self.generator / "generated_outputs"):
            with self.subTest(output=output), self.assertRaises(GateError):
                self.resolve("Refine10m", output=output)
        self.output.mkdir(parents=True)
        source = self.output / "source.sqlite"
        source.touch()
        with self.assertRaises(GateError):
            self.resolve("Population", output=self.output, database=source)

    def test_smoke_stays_read_only_unless_work_output_explicit(self):
        self.assertIsNone(self.resolve("Smoke")["target"])
        self.assertEqual(self.resolve("Smoke", output=self.output)["target"], self.output)

    def test_options_reject_unbounded_or_wrong_types(self):
        for options in ({"workers": 0}, {"workers": True}, {"workers": 33},
                        {"memory_budget_mb": 1}, {"command": "anything"},
                        {"no_reuse": "false"}, {"smoke_limit": 108}):
            with self.subTest(options=options), self.assertRaises(GateError):
                _validated_run_options("Refine10m", options)

    def test_wrong_stage_options_fail_closed(self):
        for task, options in (("Population", {"scope": "FT0"}),
                              ("Physical10m", {"scope": "UNKNOWN"}),
                              ("Physical10m", {"memory_budget_mb": 256}),
                              ("Full", {"memory_budget_mb": 128}),
                              ("Full", {"prefetch_memory_mib": 64}),
                              ("Validate", {"no_reuse": False})):
            with self.subTest(task=task), self.assertRaises(GateError):
                _validated_run_options(task, options)
        with self.assertRaises(GateError):
            self.resolve("Smoke", options=[])

    def test_common_worker_controls_are_bound_for_every_builder(self):
        options = {"workers": 4, "memory_budget_mb": 1024, "no_reuse": False}
        for task in ("Full", "Smoke", "Refine10m", "Physical10m", "Population"):
            with self.subTest(task=task):
                self.assertEqual(_validated_run_options(task, options), options)
                value = self.resolve(task, output=self.output,
                                     database=self.source if task == "Population" else None,
                                     options=options)
                self.assertEqual(value["invocation"]["run_options"], options)

    def test_algorithm_mode_is_typed_and_bound_across_builders(self):
        for task in ("Full", "Smoke", "Refine10m", "Physical10m", "Population"):
            for mode in ("auto", "reference"):
                with self.subTest(task=task, mode=mode):
                    value = self.resolve(task, output=self.output,
                        database=self.source if task == "Population" else None,
                        options={"algorithm_mode": mode})
                    self.assertEqual(value["invocation"]["run_options"]["algorithm_mode"], mode)
            for invalid in (None, True, 1, [], {}, "unsafe", "Auto"):
                with self.subTest(task=task, invalid=invalid), self.assertRaises(GateError):
                    _validated_run_options(task, {"algorithm_mode": invalid})
        with self.assertRaises(GateError):
            _validated_run_options("Validate", {"algorithm_mode": "auto"})

    def test_schema_task_enumerations_match_profiles(self):
        schemas = Path(__file__).resolve().parents[1] / "launch_gate" / "schemas"
        for name in ("generator_launch_intent.schema.json", "generator_run.schema.json"):
            value = json.loads((schemas / name).read_text("utf-8"))
            self.assertEqual(set(value["properties"]["task"]["enum"]), set(TASKS))


class RuntimeLaunchGateCliTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows launcher default selection")
    def test_launcher_automatic_and_explicit_reference_worker_selection(self):
        launcher = Path(__file__).resolve().parents[2] / "Run-Generator.ps1"
        # Evaluate only the two reviewed pure assignments from the real launcher,
        # never its dependency checks, locks, gate or generation commands.
        script = """
        $ErrorActionPreference='Stop'
        $tokens=$null; $parseErrors=$null
        $ast=[Management.Automation.Language.Parser]::ParseFile($env:DIADEM_TEST_LAUNCHER,[ref]$tokens,[ref]$parseErrors)
        if ($parseErrors.Count) { throw 'Launcher parse failed' }
        $assignments=@($ast.FindAll({param($node)
            $node -is [Management.Automation.Language.AssignmentStatementAst] -and
            $node.Left.Extent.Text -in @('$selectedWorkers','$selectedPrefetchWorkers')
        },$false))
        if ($assignments.Count -ne 2) { throw 'Expected worker assignments missing' }
        $results=@(foreach ($Task in @('Full','Smoke','Refine10m','Physical10m','Population')) {
            foreach ($Workers in @(0,1,8)) {
                foreach ($assignment in $assignments) { . ([ScriptBlock]::Create($assignment.Extent.Text)) }
                @{task=$Task;requested=$Workers;compute=$selectedWorkers;prefetch=$selectedPrefetchWorkers}
            }
        })
        @{processors=[Environment]::ProcessorCount;results=$results} | ConvertTo-Json -Depth 4 -Compress
        """
        environment = dict(os.environ, DIADEM_TEST_LAUNCHER=str(launcher))
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                env=environment, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(len(values["results"]), 15)
        for row in values["results"]:
            automatic = 1 if row["task"] == "Physical10m" else max(1, min(4, values["processors"]))
            expected = row["requested"] or automatic
            self.assertEqual(row["compute"], expected, row)
            self.assertEqual(row["prefetch"], expected, row)

    def invoke(self, options):
        return cli.main(["prepare", "--workspace", ".", "--task", "Smoke", *options])

    def test_base64_roundtrip_raw_compatibility_and_default(self):
        value = {"no_reuse": False, "prefetch_workers": 4, "smoke_limit": 25}
        encoded = base64.b64encode(json.dumps(value).encode("utf-8")).decode("ascii")
        for args, expected in ((["--run-options-base64", encoded], value),
                               (["--run-options", json.dumps(value)], value), ([], {})):
            with self.subTest(args=args), mock.patch.object(cli, "prepare_run", return_value={"run_id": "test"}) as prepare:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.invoke(args), 0)
                self.assertEqual(prepare.call_args.kwargs["run_options"], expected)

    def test_invalid_or_oversized_payloads_fail_before_preparation(self):
        invalid = ["not-base64!", "é", base64.b64encode(b"\xff").decode("ascii"),
                   base64.b64encode(b"{broken}").decode("ascii"),
                   base64.b64encode(b"[]").decode("ascii"),
                   "A" * (cli.MAX_ENCODED_RUN_OPTIONS_BYTES + 1)]
        args = [["--run-options-base64", value] for value in invalid]
        args.append(["--run-options", " " * (cli.MAX_RUN_OPTIONS_BYTES + 1)])
        for value in args:
            with self.subTest(length=len(value[1])), mock.patch.object(cli, "prepare_run") as prepare:
                with contextlib.redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(self.invoke(value), 2)
                self.assertFalse(json.loads(error.getvalue())["ok"])
                prepare.assert_not_called()

    def test_raw_and_encoded_options_are_mutually_exclusive(self):
        with mock.patch.object(cli, "prepare_run") as prepare, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                self.invoke(["--run-options", "{}", "--run-options-base64", "e30="])
            self.assertEqual(error.exception.code, 2)
            prepare.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell native argument regression")
    def test_windows_powershell_native_prepare_array_preserves_encoded_json(self):
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        if not powershell.is_file():
            self.skipTest("Windows PowerShell is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            probe = Path(temporary) / "gate_transport_probe.py"
            probe.write_text(
                "import json,sys\nfrom diadem_launch_gate import cli\n"
                "args=cli._parser().parse_args(sys.argv[1:])\n"
                "print(json.dumps(cli._run_options(args),sort_keys=True))\n", encoding="utf-8")
            def literal(value):
                return "'" + str(value).replace("'", "''") + "'"
            script = "\n".join([
                "$ErrorActionPreference='Stop'",
                "$python=" + literal(sys.executable),
                "$runOptions=@{no_reuse=$false;prefetch_workers=4;prefetch_depth=4;prefetch_memory_mib=1024;smoke_limit=25}",
                "$prepareArgs=@('prepare','--workspace','C:\\workspace with spaces','--task','Smoke')",
                "$runOptionsJson=$runOptions | ConvertTo-Json -Compress",
                "$runOptionsBase64=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($runOptionsJson))",
                "$prepareArgs+=@('--run-options-base64',$runOptionsBase64)",
                "& $python -B -m gate_transport_probe @prepareArgs",
                "exit $LASTEXITCODE",
            ])
            environment = dict(os.environ)
            environment["PYTHONPATH"] = temporary + os.pathsep + environment.get("PYTHONPATH", "")
            result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                                    env=environment, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"no_reuse": False, "prefetch_workers": 4,
                "prefetch_depth": 4, "prefetch_memory_mib": 1024, "smoke_limit": 25})


if __name__ == "__main__":
    unittest.main()
