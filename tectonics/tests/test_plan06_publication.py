"""Check the Plan06 source export without importing Atlas or opening a live queue."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "optimisation/workbench/plan06"
HEX = re.compile(r"[0-9a-f]{64}")
PRIVATE_USER_PATH = re.compile(
    r"""(?i)[a-z]:[\\/]+Users[\\/]+([^\\/\s"'<>]+)"""
)


def safe_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("source-map path is not a portable relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(
        part in ("", ".", "..") for part in value.split("/")
    ):
        raise ValueError("unsafe source-map path")
    return path


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON key: " + name)
        result[name] = value
    return result


def check_manifest(document, payloads):
    expected = {
        "status": "SOURCE_SNAPSHOT_NOT_A_RUNNABLE_PROFILE",
        "enabled": False,
        "collective_review": "DEFERRED",
        "private_run_data_included": False,
    }
    for key, value in expected.items():
        if type(document.get(key)) is not type(value) or document[key] != value:
            raise ValueError("source-map disposition differs: " + key)
    rows = document.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("source-map files must be a nonempty list")
    names = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("source-map file row must be an object")
        name = str(safe_path(row.get("path")))
        if name.casefold() in names:
            raise ValueError("duplicate source-map path")
        names.add(name.casefold())
        for key in ("original_sha256", "public_sha256"):
            if not isinstance(row.get(key), str) or HEX.fullmatch(row[key]) is None:
                raise ValueError("invalid source digest: " + key)
        if not isinstance(row.get("transformations"), list):
            raise ValueError("missing transformation list")
        if name not in payloads:
            raise ValueError("mapped file is absent: " + name)
        if sha256(payloads[name]).hexdigest() != row["public_sha256"]:
            raise ValueError("public digest differs: " + name)


@contextmanager
def no_bytecode():
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        sys.dont_write_bytecode = previous


class Plan06Publication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.map_bytes = (SOURCE / "SOURCE-MAP.json").read_bytes()
        cls.document = json.loads(cls.map_bytes, object_pairs_hook=unique_object)
        cls.payloads = {}
        for path in SOURCE.rglob("*"):
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise ValueError("source export contains a linked path")
            if path.is_file() and path != SOURCE / "SOURCE-MAP.json":
                relative = path.relative_to(SOURCE).as_posix()
                safe_path(relative)
                cls.payloads[relative] = path.read_bytes()

    def test_metadata_and_exact_digests(self):
        check_manifest(self.document, self.payloads)

    def test_exact_inventory(self):
        listed = {row["path"] for row in self.document["files"]}
        self.assertEqual(listed, set(self.payloads))
        self.assertNotIn("SOURCE-MAP.json", listed)

    def test_no_private_run_data_or_paths(self):
        forbidden_parts = {
            "evidence", "captures", "logs", "receipts", "composed-r6",
            "c6-diagnostic-fault-fixture", "__pycache__",
        }
        forbidden_suffixes = {
            ".pkl", ".pickle", ".jsonl", ".gz", ".zip", ".log",
            ".exit", ".pyc", ".pyo",
        }
        forbidden_names = {
            "TEST_COMPOSITION.json", "composition.json", "queue.json", "peaks.json",
            "reviewed-d5-r1.json", "stage-record.json", "stage-record-r2.json",
        }
        for name, raw in {"SOURCE-MAP.json": self.map_bytes, **self.payloads}.items():
            with self.subTest(path=name):
                path = PurePosixPath(name)
                self.assertFalse(set(path.parts) & forbidden_parts)
                self.assertNotIn(path.suffix.lower(), forbidden_suffixes)
                self.assertNotIn(path.name, forbidden_names)
                text = raw.decode("utf8")
                for match in PRIVATE_USER_PATH.finditer(text):
                    self.assertEqual(match.group(1), "LOCAL_USER")

    def test_python_sources_compile_without_import(self):
        sources = {name: raw for name, raw in self.payloads.items() if name.endswith(".py")}
        self.assertTrue(sources)
        for name, raw in sources.items():
            with self.subTest(path=name):
                compile(raw, name, "exec", dont_inherit=True)

    def test_corrupt_digest_is_rejected(self):
        bad = deepcopy(self.document)
        row = bad["files"][0]
        row["public_sha256"] = "0" * 64 if row["public_sha256"] != "0" * 64 else "1" * 64
        with self.assertRaisesRegex(ValueError, "public digest differs"):
            check_manifest(bad, self.payloads)

    def fixture_suite(self, folder, fixture, companions, class_name, count):
        """Copy only the fixture's source dependencies into a disposable directory."""
        with tempfile.TemporaryDirectory(prefix="plan06-public-") as temporary:
            root = Path(temporary)
            for name in [fixture, *companions]:
                (root / name).write_bytes(self.payloads[folder + "/" + name])
            module_name = "_plan06_public_" + class_name
            spec = importlib.util.spec_from_file_location(module_name, root / fixture)
            module = importlib.util.module_from_spec(spec)
            output = io.StringIO()
            with no_bytecode(), patch.dict(
                os.environ,
                {"RUNQ_DIR": str(root), "RUNQ_LOCK": str(root / "fixture-lock.json")},
            ):
                sys.modules[module_name] = module
                try:
                    spec.loader.exec_module(module)
                    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
                    self.assertEqual(suite.countTestCases(), count)
                    self.assertTrue(all(
                        test.id().startswith(module_name + "." + class_name + ".")
                        for group in suite for test in group
                    ))
                    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
                    self.assertEqual(result.testsRun, count, output.getvalue())
                    self.assertTrue(result.wasSuccessful(), output.getvalue())
                finally:
                    sys.modules.pop(module_name, None)

    def test_d5_adapter_fixtures(self):
        self.fixture_suite(
            "integration", "test_d5_adapter.py", ["assemble_r3_plan06.py"], "Adapter", 14
        )

    def test_disabled_equivalence_fixture(self):
        self.fixture_suite(
            "integration", "test_disabled_equivalence.py",
            ["assemble_r3_plan06.py", "reference_assemble_r3.py"], "Disabled", 1,
        )

    def test_queue_liveness_fixtures(self):
        self.fixture_suite(
            "queue-fix", "test_pid_liveness.py", ["runq.py"], "LivenessTests", 6
        )

    def test_runtime_entry_environment_controls(self):
        with tempfile.TemporaryDirectory(prefix="plan06-entry-") as temporary:
            root = Path(temporary)
            for name in ("runtime_entry.py", "test_runtime_entry.py"):
                (root / name).write_bytes(self.payloads[name])
            (root / "evidence").mkdir()
            result = subprocess.run(
                [sys.executable, "-B", "-I", str(root / "test_runtime_entry.py")],
                cwd=root, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((root / "evidence/runtime-entry-check.json").read_bytes())
            self.assertIs(report["passed"], True)
            self.assertEqual(len(report["cases"]), 5)
            self.assertTrue(all(row["ok"] is True for row in report["cases"]))
            self.assertEqual(
                report["entry_sha256"], sha256(self.payloads["runtime_entry.py"]).hexdigest()
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
