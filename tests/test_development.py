"""Focused public-development tests. No historical checkpoints or model trajectories."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "development"))
from atlas_dev import core, fixture, cli, SCOPE


class FileTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="atlas-dev-file-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_duplicate_json_keys_refused(self):
        with self.assertRaises(core.DevelopmentError):
            core.parse(b'{"key":1,"key":2}')

    def test_nonfinite_json_refused(self):
        for raw in (b'NaN', b'Infinity', b'-Infinity'):
            with self.subTest(raw=raw), self.assertRaises(core.DevelopmentError):
                core.parse(raw)

    def test_invalid_encoding_and_json_refused(self):
        for raw in (b'\xff', b'{'):
            with self.subTest(raw=raw), self.assertRaises(core.DevelopmentError):
                core.parse(raw)

    def test_canonical_order_and_exact_integer_roundtrip(self):
        data = {"large": 2**200, "unicode": "\u96ea"}
        self.assertEqual(core.parse(core.canonical(data)), data)
        self.assertEqual(core.canonical(data), core.canonical(dict(reversed(list(data.items())))))

    def test_new_publication_preserves_existing_bytes(self):
        target = self.root / "nested/record.json"
        core.write_new(target, b'one')
        with self.assertRaises(core.DevelopmentError):
            core.write_new(target, b'two')
        self.assertEqual(core.read(target), b'one')
        self.assertEqual(list(target.parent.iterdir()), [target])

    def test_failed_publication_does_not_leave_completed_output(self):
        target = self.root / "record.json"
        with patch.object(core.os, "link", side_effect=OSError("injected publication failure")):
            with self.assertRaises(OSError):
                core.write_new(target, b'data')
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_racing_destination_is_not_overwritten(self):
        target = self.root / "record.json"
        real_link = os.link
        def race(source, destination):
            target.write_bytes(b'other writer')
            real_link(source, destination)
        with patch.object(core.os, "link", side_effect=race), self.assertRaises(FileExistsError):
            core.write_new(target, b'ours')
        self.assertEqual(target.read_bytes(), b'other writer')
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_file_size_and_directory_refused(self):
        path = self.root / "large.py"
        path.write_bytes(b'1234')
        with self.assertRaises(core.DevelopmentError):
            core.read(path, 3)
        with self.assertRaises(core.DevelopmentError):
            core.read(self.root)

    @unittest.skipIf(os.name == "nt", "real symlink creation needs Windows privilege; reparse flag tested separately")
    def test_symlink_source_and_destination_refused(self):
        path = self.root / "source.py"
        path.write_text("value = 1\n")
        link = self.root / "link.py"
        link.symlink_to(path)
        with self.assertRaises(core.DevelopmentError):
            core.read(link)
        with self.assertRaises(core.DevelopmentError):
            core.write_new(link, b'changed')
        self.assertEqual(path.read_text(), "value = 1\n")

    def test_windows_reparse_flag_refused_without_claiming_windows_execution(self):
        from types import SimpleNamespace
        with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=0o100644, st_file_attributes=0x400)):
            with self.assertRaises(core.DevelopmentError):
                core.safe(self.root / "file")


class BindingTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="atlas-dev-binding-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name in core.SOURCE_ROOTS:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.path = self.root / "engineering/work/example.py"
        self.path.write_text("VALUE = 1\n")
        fake = patch.object(core, "runtime_identity", return_value={"python": "synthetic runtime gate fixture"})
        fake.start()
        self.addCleanup(fake.stop)
        self.record = core.capture(self.root)

    def test_fresh_capture_and_roundtrip_verification(self):
        record = core.parse(core.canonical(self.record))
        self.assertEqual(core.verify(record, self.root), self.record["binding_sha256"])
        self.assertEqual(record["binding"]["scope"], SCOPE)

    def test_changed_source_requires_new_identity(self):
        self.path.write_text("VALUE = 2\n")
        with self.assertRaisesRegex(core.DevelopmentError, "source changed"):
            core.verify(self.record, self.root)
        new = core.capture(self.root)
        self.assertNotEqual(new["binding_sha256"], self.record["binding_sha256"])
        self.assertEqual(core.verify(new, self.root), new["binding_sha256"])

    def test_added_source_changes_identity(self):
        (self.path.parent / "extra.py").write_text("VALUE = 3\n")
        with self.assertRaises(core.DevelopmentError):
            core.verify(self.record, self.root)

    def test_deleted_source_changes_identity(self):
        self.path.unlink()
        with self.assertRaises(core.DevelopmentError):
            core.verify(self.record, self.root)

    def test_changed_runtime_is_not_adopted(self):
        with patch.object(core, "runtime_identity", return_value={"python": "different"}):
            with self.assertRaisesRegex(core.DevelopmentError, "runtime changed"):
                core.verify(self.record, self.root)

    def test_changed_binding_commitment_refused(self):
        self.record["binding_sha256"] = "0" * 64
        with self.assertRaises(core.DevelopmentError):
            core.verify(self.record, self.root)

    def test_historical_schema_and_claims_refused_even_if_rehashed(self):
        for field, value in (("schema", "diadem.native-shared-storage-execution.r5"),
                             ("scope", "DOMAIN_ACCEPTED"), ("package_version", "999")):
            record = deepcopy(self.record)
            record["binding"][field] = value
            record["binding_sha256"] = core.digest(core.canonical(record["binding"]))
            with self.subTest(field=field), self.assertRaises(core.DevelopmentError):
                core.verify(record, self.root)

    def test_saved_historical_control_is_not_an_import_format(self):
        with self.assertRaises(core.DevelopmentError):
            core.verify({"storage_schema": "diadem.native-shared-history-controls.r5"}, self.root)

    def test_relocation_is_not_silent_compatibility(self):
        record = deepcopy(self.record)
        record["binding"]["source_root"] = str(self.root / "other")
        record["binding_sha256"] = core.digest(core.canonical(record["binding"]))
        with self.assertRaises(core.DevelopmentError):
            core.verify(record, self.root)

    def test_invalid_inventory_type_refused(self):
        record = deepcopy(self.record)
        record["binding"]["source_files"] = []
        record["binding_sha256"] = core.digest(core.canonical(record["binding"]))
        with self.assertRaises(core.DevelopmentError):
            core.verify(record, self.root)

    def test_mid_capture_inventory_change_refused(self):
        original = core.source_inventory(self.root)
        with patch.object(core, "source_inventory", side_effect=[original, {}]):
            with self.assertRaisesRegex(core.DevelopmentError, "while capturing"):
                core.capture(self.root)

    def test_generated_private_records_not_part_of_source_inventory(self):
        private = self.root / ".atlas-dev/cache"
        private.mkdir(parents=True)
        (private / "receipt.json").write_text("{}")
        cache = self.path.parent / "__pycache__"
        cache.mkdir()
        (cache / "example.pyc").write_bytes(b'not executable by this test')
        self.assertEqual(core.verify(self.record, self.root), self.record["binding_sha256"])

    def test_missing_source_root_refused(self):
        (self.root / "tests").rmdir()
        with self.assertRaises(core.DevelopmentError):
            core.source_inventory(self.root)

    def test_file_and_total_inventory_limits(self):
        with patch.object(core, "MAX_FILES", 0), self.assertRaises(core.DevelopmentError):
            core.source_inventory(self.root)
        with patch.object(core, "MAX_TOTAL", 1), self.assertRaises(core.DevelopmentError):
            core.source_inventory(self.root)


class FixtureTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="atlas-dev-oracle-test-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / "development/fixtures/runtime_graph.json"
        self.path.parent.mkdir(parents=True)
        self.data = fixture.load_fixture(ROOT)
        self.write()

    def write(self):
        self.path.write_bytes(core.canonical(self.data))

    def test_public_fixture_has_independent_expected_values(self):
        self.assertEqual(fixture.load_fixture(self.root)["expected"], {"a": 2, "b": 3, "c": 3, "d": 11})

    def test_bool_base_is_not_an_integer_quantity(self):
        self.data["nodes"][0]["base"] = True
        self.write()
        with self.assertRaises(core.DevelopmentError):
            fixture.load_fixture(self.root)

    def test_forward_unknown_and_duplicate_parents_refused(self):
        for parents in (["d"], ["unknown"], ["a", "a"]):
            self.data["nodes"][2]["parents"] = parents
            self.write()
            with self.subTest(parents=parents), self.assertRaises(core.DevelopmentError):
                fixture.load_fixture(self.root)

    def test_duplicate_node_refused(self):
        self.data["nodes"][1]["id"] = "a"
        self.write()
        with self.assertRaises(core.DevelopmentError):
            fixture.load_fixture(self.root)

    def test_missing_expected_value_refused(self):
        del self.data["expected"]["d"]
        self.write()
        with self.assertRaises(core.DevelopmentError):
            fixture.load_fixture(self.root)

    def test_fixture_size_limit(self):
        self.data["nodes"] *= 5
        self.write()
        with self.assertRaises(core.DevelopmentError):
            fixture.load_fixture(self.root)

    def test_nonpublic_fixture_refused(self):
        self.data["scope"] = "CANON"
        self.write()
        with self.assertRaises(core.DevelopmentError):
            fixture.load_fixture(self.root)


class EnvironmentAndCommandTests(unittest.TestCase):
    def test_doctor_has_no_native_import_side_effect(self):
        before = {name for name in sys.modules if name.startswith("work.")}
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli.main(["doctor"]), 0)
        after = {name for name in sys.modules if name.startswith("work.")}
        self.assertEqual(after, before)
        result = json.loads(output.getvalue())
        self.assertIn("native-r5-continuation", result["unavailable_routes"])
        self.assertEqual(result["environment_policy"]["third_party_requirements"], [])

    def test_captured_package_execution_is_verified(self):
        inventory = core.source_inventory()
        core.verify_executed(inventory)
        with patch.object(core, "_ATLAS_DEV_EXECUTED_SHA256", "0" * 64):
            with self.assertRaisesRegex(core.DevelopmentError, "executed public"):
                core.verify_executed(inventory)

    def test_changed_on_disk_identity_cannot_describe_old_executed_package(self):
        inventory = core.source_inventory()
        inventory["development/atlas_dev/core.py"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(core.DevelopmentError, "executed public"):
            core.verify_executed(inventory)

    def test_profile_names_are_explicit_and_bounded(self):
        config = core.profiles()
        self.assertEqual(set(config["profiles"]), {"runtime", "numerics", "tooling"})
        self.assertNotIn("work.native_terrain_r1.test_hillslope.AnalyticalDecayTests",
                         config["profiles"]["numerics"]["tests"])

    def test_malformed_profile_test_name_refused(self):
        config = core.profiles()
        config["profiles"]["runtime"]["tests"] = ["../../private"]
        with patch.object(core, "parse", return_value=config), self.assertRaises(core.DevelopmentError):
            core.profiles()

    def test_reports_cannot_overwrite_project_sources(self):
        with self.assertRaises(core.DevelopmentError):
            cli._check_outside_source(ROOT / "README.md")
        with self.assertRaises(core.DevelopmentError):
            cli._check_outside_source(ROOT / ".atlas-dev/../AGENTS.md")

    def test_private_report_location_is_allowed(self):
        self.assertEqual(cli._check_outside_source(ROOT / ".atlas-dev/test.json"),
                         ROOT / ".atlas-dev/test.json")

    def test_existing_venv_is_never_reused_or_deleted(self):
        with tempfile.TemporaryDirectory(prefix="atlas-dev-bootstrap-test-") as directory:
            root = Path(directory)
            target = root / ".atlas-dev/venv"
            target.mkdir(parents=True)
            marker = target / "keep.txt"
            marker.write_text("existing environment")
            with patch.object(core, "runtime_identity", return_value={}):
                with self.assertRaises(FileExistsError):
                    core.bootstrap(root)
            self.assertEqual(marker.read_text(), "existing environment")

    def test_failed_bootstrap_preserves_partial_directory(self):
        with tempfile.TemporaryDirectory(prefix="atlas-dev-bootstrap-test-") as directory:
            root = Path(directory)
            with patch.object(core, "runtime_identity", return_value={}), \
                    patch.object(core.venv.EnvBuilder, "create", side_effect=OSError("injected")):
                with self.assertRaisesRegex(core.DevelopmentError, "partial directory retained"):
                    core.bootstrap(root)
            self.assertTrue((root / ".atlas-dev/venv").is_dir())

    def test_bootstrap_requests_no_downloads_or_installed_packages(self):
        with tempfile.TemporaryDirectory(prefix="atlas-dev-bootstrap-test-") as directory:
            root = Path(directory)
            def build(destination):
                interpreter = destination / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                interpreter.parent.mkdir(parents=True)
                interpreter.write_bytes(b'synthetic interpreter marker, never executed')
            with patch.object(core, "runtime_identity", return_value={}), patch.object(core, "install_sources") as install, \
                    patch.object(core.venv, "EnvBuilder") as factory:
                factory.return_value.create.side_effect = build
                core.bootstrap(root)
                install.assert_called_once()
                options = factory.call_args.kwargs
                for option in ("system_site_packages", "with_pip", "upgrade", "upgrade_deps", "clear"):
                    self.assertFalse(options[option])

    def test_editable_install_contains_only_explicit_paths(self):
        raw = core.source_link(ROOT)
        self.assertEqual(raw.decode().splitlines(), [str(ROOT / "development"), str(ROOT / "engineering")])
        self.assertNotIn(b"import ", raw)

    def test_editable_path_cannot_inject_pth_code(self):
        with self.assertRaises(core.DevelopmentError):
            core.source_link(ROOT / "bad\nimport os")

    def test_launcher_requires_isolation_and_no_bytecode(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/develop.py"), "doctor"],
                                capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("-I -B", result.stderr)

    def test_cli_refuses_saved_native_control_without_importing_it(self):
        with tempfile.TemporaryDirectory(prefix="atlas-dev-cli-test-") as directory:
            path = Path(directory) / "control.json"
            path.write_text('{"storage_schema":"diadem.native-shared-history-controls.r5"}')
            errors = io.StringIO()
            with patch.object(core, "runtime_identity", return_value={}), redirect_stderr(errors):
                self.assertEqual(cli.main(["check", "--binding", str(path)]), 2)
            self.assertIn("no historical checkpoints", errors.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
