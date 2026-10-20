"""Synthetic checks of the published Plan02 metadata repair; no store or solve."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "optimisation/workbench/plan02"
SPEC = importlib.util.spec_from_file_location("public_plan02_transfer", SOURCE / "native_transfer.py")
TRANSFER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TRANSFER
SPEC.loader.exec_module(TRANSFER)
INITIAL = {"schema": "synthetic-collar-fields", "plan_id": "1" * 64,
           "source_id": "2" * 64, "parent_id": "3" * 64, "time_s": 0}
EVOLVED = dict(INITIAL, time_s=1, heat_id="4" * 64, transport_id="5" * 64)


class Plan02MetadataTests(unittest.TestCase):
    def test_old_exact_key_gate_refuses_evolved_shape(self):
        with self.assertRaises(TRANSFER.TransferRefused):
            TRANSFER._keys(EVOLVED, TRANSFER._FIELD_KEYS, label="historical collar fields")
        TRANSFER._historical_collar_fields(EVOLVED)

    def test_initial_and_evolved_shapes_preserve_metadata(self):
        for fields in (INITIAL, EVOLVED):
            value = deepcopy(fields)
            before = TRANSFER._json(value)
            TRANSFER._historical_collar_fields(value)
            self.assertEqual(before, TRANSFER._json(value))

    def test_missing_unknown_and_non_mapping_fields_refuse(self):
        for fields in (INITIAL, EVOLVED):
            for key in INITIAL:
                broken = dict(fields)
                del broken[key]
                with self.subTest(missing=key), self.assertRaises(TRANSFER.TransferRefused):
                    TRANSFER._historical_collar_fields(broken)
            with self.assertRaises(TRANSFER.TransferRefused):
                TRANSFER._historical_collar_fields(dict(fields, future_physics=None))
        for value in (None, [], "fields"):
            with self.subTest(value=value), self.assertRaises(TRANSFER.TransferRefused):
                TRANSFER._historical_collar_fields(value)

    def test_partial_evolved_pair_refuses(self):
        for key in ("heat_id", "transport_id"):
            value = dict(EVOLVED)
            del value[key]
            with self.subTest(missing=key), self.assertRaisesRegex(
                    TRANSFER.TransferRefused, "must occur together"):
                TRANSFER._historical_collar_fields(value)

    def test_malformed_ids_refuse(self):
        for key in ("heat_id", "transport_id"):
            for bad in (None, True, 3, "", "a" * 63, "A" * 64, "g" * 64, ["a" * 64]):
                with self.subTest(key=key, value=bad), self.assertRaisesRegex(
                        TRANSFER.TransferRefused, "SHA-256"):
                    TRANSFER._historical_collar_fields(dict(EVOLVED, **{key: bad}))

    def test_both_ids_contribute_to_snapshot_identity(self):
        arrays = {"enthalpy_j": {"shape": [1], "sha256": "6" * 64}}
        original = TRANSFER._snapshot_id(EVOLVED, arrays)
        for key in ("heat_id", "transport_id"):
            changed = dict(EVOLVED, **{key: "7" * 64})
            TRANSFER._historical_collar_fields(changed)
            self.assertNotEqual(original, TRANSFER._snapshot_id(changed, arrays))

    def test_public_source_map_matches_all_selected_files(self):
        record = json.loads((SOURCE / "SOURCE-MAP.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "SOURCE_SNAPSHOT_NOT_A_RUNNABLE_PROFILE")
        self.assertEqual(len(record["files"]), 25)
        self.assertEqual(len({row["path"] for row in record["files"]}), 25)
        for row in record["files"]:
            with self.subTest(path=row["path"]):
                raw = (SOURCE / row["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), row["public_sha256"])
        self.assertFalse(any(name == "atlas_tectonics" or name.startswith("atlas_tectonics.")
                             for name in sys.modules))


if __name__ == "__main__":
    unittest.main()
