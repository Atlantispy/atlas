"""Validate the Plan05 publication without importing its private execution route."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import unittest

from test_plan04_publication import check_source_hygiene, safe_path, unique_object


ROOT = Path(__file__).resolve().parents[1] / "optimisation/workbench/plan05"


def validate_map(document, payloads):
    if document["schema"] != "atlas.public.plan05-source-map.v1":
        raise ValueError("Unexpected Plan05 publication schema")
    if document["status"] != "SOURCE_SNAPSHOT_NOT_A_RUNNABLE_PROFILE":
        raise ValueError("Public export is not a native execution profile")
    if document["private_run_data_included"] is not False:
        raise ValueError("Private execution records must remain excluded")
    names = set()
    for item in document["files"]:
        name = str(safe_path(item["path"]))
        if name.casefold() in names:
            raise ValueError("Duplicate publication path")
        names.add(name.casefold())
        for key in ("original_sha256", "public_sha256"):
            digest = item[key]
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Invalid digest")
        if (item["original_sha256"] != item["public_sha256"]
                and not item["transformations"]):
            raise ValueError("Changed public bytes need a transformation trail")
        if sha256(payloads[name]).hexdigest() != item["public_sha256"]:
            raise ValueError("Published bytes differ")
    if names != {name.casefold() for name in payloads}:
        raise ValueError("Publication inventory differs")


class Plan05Publication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads((ROOT / "SOURCE-MAP.json").read_bytes(),
                                  object_pairs_hook=unique_object)
        cls.payloads = {}
        for path in ROOT.rglob("*"):
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise ValueError("Linked publication path")
            if path.is_file() and path.name != "SOURCE-MAP.json":
                cls.payloads[path.relative_to(ROOT).as_posix()] = path.read_bytes()

    def test_complete_public_inventory_and_digests(self):
        validate_map(self.document, self.payloads)

    def test_privacy_and_no_raw_run_data(self):
        for name, raw in {
            "SOURCE-MAP.json": (ROOT / "SOURCE-MAP.json").read_bytes(),
            **self.payloads,
        }.items():
            with self.subTest(path=name):
                check_source_hygiene(name, raw)

    def test_compile_without_import_and_strict_json(self):
        for name, raw in self.payloads.items():
            with self.subTest(path=name):
                if name.endswith(".py"):
                    compile(raw, name, "exec", dont_inherit=True)
                elif name.endswith(".json"):
                    json.loads(raw, object_pairs_hook=unique_object)

    def test_global_manifest_contains_exact_export(self):
        optimisation = ROOT.parents[1]
        manifest = json.loads((optimisation / "MANIFEST.json").read_bytes(),
                              object_pairs_hook=unique_object)
        prefix = "workbench/plan05/"
        paths = [row["path"][len(prefix):] for row in manifest["files"]
                 if row["path"].startswith(prefix)]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(set(paths), {*self.payloads, "SOURCE-MAP.json"})

    def test_public_summary_preserves_failure_and_holds(self):
        summary = json.loads(self.payloads["RETAINED-RESULTS.json"],
                             object_pairs_hook=unique_object)
        self.assertEqual(summary["historical_q10"], "FAIL")
        self.assertEqual(summary["q22"], "HELD")
        self.assertEqual(summary["collective_correctness_acceptance"], "PENDING")
        self.assertIs(summary["full_plan_scientific_acceptance"], False)
        self.assertEqual(summary["corrected_pair"]["historical_linkage"], "NOT_REPRODUCED")
        self.assertIs(summary["corrected_pair"]["queue_and_launcher_failure_retained"], True)

    def test_changed_public_bytes_are_rejected(self):
        payloads = dict(self.payloads)
        name = next(iter(payloads))
        payloads[name] += b"\nchanged\n"
        with self.assertRaisesRegex(ValueError, "Published bytes differ"):
            validate_map(self.document, payloads)

    def test_missing_or_unlisted_file_is_rejected(self):
        payloads = dict(self.payloads)
        payloads["unlisted.py"] = b"VALUE = 1\n"
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            validate_map(self.document, payloads)
        payloads = dict(self.payloads)
        del payloads[next(iter(payloads))]
        with self.assertRaises(KeyError):
            validate_map(self.document, payloads)

    def test_missing_transformation_trail_is_rejected(self):
        document = deepcopy(self.document)
        document["files"][0]["original_sha256"] = "0" * 64
        document["files"][0]["transformations"] = []
        with self.assertRaisesRegex(ValueError, "transformation trail"):
            validate_map(document, self.payloads)


if __name__ == "__main__":
    unittest.main()
