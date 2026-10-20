"""Check the Plan04 publication without importing its tools or private runtime."""
import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "optimisation/workbench/plan04"
HEX = re.compile(r"[0-9a-f]{64}")
PRIVATE_HOME = re.compile(
    r"""(?i)(?:[a-z]:[\\/]+Users[\\/]+|/(?:home|Users)/)([^\\/\s"'<>]+)"""
)
PRIVATE_COORDINATION = re.compile(r"#(?:staff-room|task-[a-z0-9_-]+|plan-\d+)(?:/\d+)?", re.I)


def safe_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("source-map path is not a portable relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(
        part in ("", ".", "..") for part in value.split("/")
    ):
        raise ValueError("unsafe source-map path")
    if any(ord(character) < 32 for character in value):
        raise ValueError("source-map path contains a control character")
    return path


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON key: " + name)
        result[name] = value
    return result


def check_manifest(document, payloads):
    if not isinstance(document, dict):
        raise ValueError("source-map must be an object")
    expected = {
        "schema": "atlas.public.plan04-source-map.v1",
        "status": "SOURCE_SNAPSHOT_NOT_A_RUNNABLE_PROFILE",
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
    folded_names = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("source-map file row must be an object")
        name = str(safe_path(row.get("path")))
        if name == "SOURCE-MAP.json":
            raise ValueError("source-map cannot include its own digest")
        if name.casefold() in folded_names:
            raise ValueError("duplicate source-map path")
        names.add(name)
        folded_names.add(name.casefold())
        for key in ("original_sha256", "public_sha256"):
            if not isinstance(row.get(key), str) or HEX.fullmatch(row[key]) is None:
                raise ValueError("invalid source digest: " + key)
        transformations = row.get("transformations")
        if not isinstance(transformations, list) or any(
            not isinstance(item, str) or not item.strip() for item in transformations
        ):
            raise ValueError("invalid transformation list")
        if row["original_sha256"] != row["public_sha256"] and not transformations:
            raise ValueError("changed publication bytes require a transformation")
        if name not in payloads:
            raise ValueError("mapped file is absent: " + name)
        if sha256(payloads[name]).hexdigest() != row["public_sha256"]:
            raise ValueError("public digest differs: " + name)
    if names != set(payloads):
        raise ValueError("source-map inventory differs")


def check_source_hygiene(name, raw):
    path = safe_path(name)
    forbidden_parts = {
        "evidence", "captures", "logs", "receipts", "__pycache__",
        ".atlas-dev", "bridge",
    }
    forbidden_suffixes = {
        ".pkl", ".pickle", ".jsonl", ".gz", ".zip", ".log",
        ".exit", ".pyc", ".pyo",
    }
    forbidden_names = {
        "composition.json", "test_composition.json", "queue.json", "peaks.json",
        "selection.json", "prepared.json", "child-result.json", "result.json",
        "restart-profile-live-r21.json", "caller-closure-r1.json",
    }
    if {part.casefold() for part in path.parts} & forbidden_parts:
        raise ValueError("private run-data directory: " + name)
    if path.suffix.lower() in forbidden_suffixes or path.name.casefold() in forbidden_names:
        raise ValueError("private run-data file: " + name)
    text = raw.decode("utf8")
    for match in PRIVATE_HOME.finditer(text.replace(r"\/", "/")):
        if match.group(1) != "LOCAL_USER":
            raise ValueError("personal home path: " + name)
    if PRIVATE_COORDINATION.search(text):
        raise ValueError("private coordination reference: " + name)


class Plan04Publication(unittest.TestCase):
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

    def test_metadata_exact_inventory_and_public_digests(self):
        check_manifest(self.document, self.payloads)

    def test_no_private_run_data_paths_or_coordination(self):
        for name, raw in {"SOURCE-MAP.json": self.map_bytes, **self.payloads}.items():
            with self.subTest(path=name):
                check_source_hygiene(name, raw)

    def test_python_sources_compile_without_import(self):
        sources = {name: raw for name, raw in self.payloads.items() if name.endswith(".py")}
        self.assertTrue(sources)
        for name, raw in sources.items():
            with self.subTest(path=name):
                compile(raw, name, "exec", dont_inherit=True)

    def test_json_sources_have_no_duplicate_keys(self):
        for name, raw in self.payloads.items():
            if name.endswith(".json"):
                with self.subTest(path=name):
                    json.loads(raw, object_pairs_hook=unique_object)

    def test_exported_readiness_guards_remain_false(self):
        found = set()
        for name, raw in self.payloads.items():
            if not name.endswith(".py") or PurePosixPath(name).name.startswith("test_"):
                continue
            for node in ast.parse(raw, filename=name).body:
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {
                        "EXTRACTION_READY", "REPAIRS_COMPLETE"
                    }:
                        with self.subTest(path=name, guard=target.id):
                            self.assertIsInstance(node.value, ast.Constant)
                            self.assertIs(node.value.value, False)
                            found.add(target.id)
        self.assertEqual(found, {"EXTRACTION_READY", "REPAIRS_COMPLETE"})


class Plan04PublicationRefusals(unittest.TestCase):
    def setUp(self):
        self.payloads = {"tool.py": b"VALUE = 1\n"}
        digest = sha256(self.payloads["tool.py"]).hexdigest()
        self.document = {
            "schema": "atlas.public.plan04-source-map.v1",
            "status": "SOURCE_SNAPSHOT_NOT_A_RUNNABLE_PROFILE",
            "collective_review": "DEFERRED",
            "private_run_data_included": False,
            "files": [{
                "path": "tool.py",
                "original_sha256": digest,
                "public_sha256": digest,
                "transformations": [],
            }],
        }

    def test_minimal_unchanged_publication_is_admitted(self):
        check_manifest(self.document, self.payloads)

    def test_distinct_original_digest_requires_disclosed_transformation(self):
        self.document["files"][0]["original_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "require a transformation"):
            check_manifest(self.document, self.payloads)
        self.document["files"][0]["transformations"] = ["sanitised publication path"]
        check_manifest(self.document, self.payloads)
        self.assertEqual(self.document["files"][0]["original_sha256"], "0" * 64)

    def test_corrupt_public_digest_is_rejected(self):
        self.document["files"][0]["public_sha256"] = "0" * 64
        self.document["files"][0]["transformations"] = ["fixture mutation"]
        with self.assertRaisesRegex(ValueError, "public digest differs"):
            check_manifest(self.document, self.payloads)

    def test_changed_payload_is_rejected(self):
        self.payloads["tool.py"] = b"VALUE = 2\n"
        with self.assertRaisesRegex(ValueError, "public digest differs"):
            check_manifest(self.document, self.payloads)

    def test_missing_and_unlisted_payloads_are_rejected(self):
        for payloads, reason in (
            ({}, "mapped file is absent"),
            ({**self.payloads, "extra.py": b""}, "inventory differs"),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                check_manifest(self.document, payloads)

    def test_unsafe_paths_are_rejected(self):
        for name in (
            "", "/tool.py", "../tool.py", "sub/../tool.py", "./tool.py",
            "sub//tool.py", "sub\\tool.py", "C:/tool.py", "tool.py:stream", "a\n.py",
        ):
            document = deepcopy(self.document)
            document["files"][0]["path"] = name
            with self.subTest(path=name), self.assertRaises(ValueError):
                check_manifest(document, self.payloads)

    def test_duplicate_and_case_alias_paths_are_rejected(self):
        for name in ("tool.py", "TOOL.py"):
            document = deepcopy(self.document)
            extra = deepcopy(document["files"][0])
            extra["path"] = name
            document["files"].append(extra)
            with self.subTest(path=name), self.assertRaisesRegex(ValueError, "duplicate"):
                check_manifest(document, self.payloads)

    def test_duplicate_json_keys_are_rejected(self):
        for raw in (
            '{"files": [], "files": []}',
            '{"files": [{"path": "a.py", "path": "b.py"}]}',
        ):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "duplicate"):
                json.loads(raw, object_pairs_hook=unique_object)

    def test_wrong_disposition_or_schema_is_rejected(self):
        for key, value in (
            ("schema", "atlas.public.plan06-source-map.v1"),
            ("status", "READY"),
            ("collective_review", "ACCEPTED"),
            ("private_run_data_included", True),
            ("private_run_data_included", 0),
        ):
            document = deepcopy(self.document)
            document[key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(
                ValueError, "disposition differs"
            ):
                check_manifest(document, self.payloads)

    def test_malformed_digests_or_transformations_are_rejected(self):
        for key, value in (
            ("original_sha256", "a" * 63),
            ("public_sha256", "G" * 64),
            ("public_sha256", None),
            ("transformations", "sanitised"),
            ("transformations", [None]),
            ("transformations", [""]),
        ):
            document = deepcopy(self.document)
            document["files"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                check_manifest(document, self.payloads)

    def test_private_source_paths_and_run_files_are_rejected(self):
        for name, raw in (
            ("tool.py", b"ROOT = 'C:/Users/PRIVATE_PERSON/project'\n"),
            ("record.json", br'{"path":"C:\\Users\\PRIVATE_PERSON\\project"}'),
            ("tool.py", b"ROOT = '/home/PRIVATE_PERSON/project'\n"),
            ("README.md", b"#staff-room/123"),
            ("README.md", b"#plan-04/123"),
            ("evidence/result.json", b"{}"),
            ("run.log", b"complete"),
        ):
            with self.subTest(path=name, content=raw), self.assertRaises(ValueError):
                check_source_hygiene(name, raw)
        check_source_hygiene("tool.py", b"ROOT = 'C:/Users/LOCAL_USER/project'\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
